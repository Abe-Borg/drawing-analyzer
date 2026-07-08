"""Orchestration: drawing PDFs -> per-sheet vision digests -> combined text.

This is the public entry point for the drawing subsystem. It flattens the given
PDFs into sheets (one per page), renders and digests each sheet independently,
and concatenates the per-sheet digests into a single text artifact ready to be
spliced into the spec reviewer's Project Context.

Rendering (PyMuPDF) runs sequentially on the calling thread — it is fast and the
PDF backend is not thread-safe to share — while the slow, independent per-sheet
*digest* (one vision call each) runs on a bounded thread pool, so a large set
completes in roughly ``1/workers`` of the wall-clock. Results are reassembled in
page order, so the combined digest and every total are deterministic regardless
of completion order.
"""
from __future__ import annotations

import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .core.api_config import REVIEW_MODEL_DEFAULT
from .core.tokenizer import estimate_image_tokens
from .diagnostics import get_logger
from . import tiling
from .digest import (
    DEFAULT_DIGEST_EFFORT,
    DEFAULT_DIGEST_MAX_TOKENS,
    SheetDigest,
    digest_sheet,
    normalize_focus,
)
from .render import iter_rendered_sheets, list_sheets

# ``progress(done, total, label)`` — called once as each sheet *finishes*
# (done = number completed so far, in completion order) and once at the end
# (done == total, label "Done").
ProgressCallback = Callable[[int, int, str], None]

# ``on_log(message, level=...)`` — leveled diagnostic messages from the batch
# path (e.g. a batch that detached past the elapsed bound, or repeated poll
# failures). Optional; when omitted the batch path falls back to surfacing these
# on the progress line, preserving the prior behavior.
LogCallback = Callable[..., None]

# ``on_status(text)`` — a transient, status-line-only update (never logged), for
# high-frequency feedback like per-image upload progress that would otherwise
# swamp the milestone-oriented activity log. Batch path only; ``progress`` and
# ``on_log`` remain the channels that drive the log.
StatusCallback = Callable[[str], None]

# Default per-set digest concurrency. Vision calls are latency-bound, so a few
# in flight cut wall-clock sharply; kept modest so a large set doesn't trip rate
# limits (transient 429/5xx are retried per-sheet anyway — see digest.py).
# Override per-call via ``max_workers=`` or globally via
# ``DRAWING_ANALYZER_MAX_WORKERS``.
DEFAULT_DIGEST_WORKERS = 4

_log = get_logger()


def _resolve_workers(max_workers: int | None, total: int) -> int:
    """Resolve the effective worker count: arg > env > default, clamped sanely.

    Floored at 1 (0/negative would create an invalid pool) and capped at
    ``total`` (no point spinning up more workers than sheets). A malformed env
    value falls back to the default rather than raising.
    """
    if max_workers is None:
        env = os.environ.get("DRAWING_ANALYZER_MAX_WORKERS")
        if env and env.strip():
            try:
                max_workers = int(env.strip())
            except ValueError:
                max_workers = DEFAULT_DIGEST_WORKERS
        else:
            max_workers = DEFAULT_DIGEST_WORKERS
    return min(max(1, int(max_workers)), max(1, total))


@dataclass
class DrawingContext:
    """The combined result of digesting a drawing set."""

    combined_text: str
    sheets: list[SheetDigest] = field(default_factory=list)
    file_count: int = 0
    sheet_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_image_token_estimate: int = 0
    errors: list[str] = field(default_factory=list)
    # The cross-sheet synthesis overview (empty when synthesis was off, skipped
    # for <2 readable sheets, or failed). When present it is also prepended into
    # ``combined_text`` as the "Drawing Set Overview" section.
    synthesis_text: str = ""
    # The operator's per-run focus (normalized; "" when none was supplied) and
    # the set-level focus report answering it (empty when no focus, no readable
    # sheets, or the focus pass failed). When present the report is also woven
    # into ``combined_text`` as the "Focus Report" section. The standard
    # deliverable is never displaced by these — they are additive.
    focus: str = ""
    focus_report_text: str = ""

    @property
    def ok_sheet_count(self) -> int:
        return sum(1 for s in self.sheets if s.ok)

    @property
    def cached_sheet_count(self) -> int:
        """Sheets served from the digest cache (no API call / token cost)."""
        return sum(1 for s in self.sheets if getattr(s, "cached", False))


def _sheet_header(index: int, total: int, ref) -> str:
    return f"## Sheet {index}/{total}: {ref.display_label}"


def _combine(
    sheets: list[SheetDigest],
    *,
    file_count: int,
    overview: str = "",
    focus: str = "",
    focus_report: str = "",
) -> str:
    """Build the combined digest document from per-sheet results.

    When ``overview`` (the cross-sheet synthesis) is non-empty it is inserted as
    a "Drawing Set Overview" section right after the intro and before the
    per-sheet sections, so a reviewer reads the reconciled set picture first.
    When ``focus_report`` is non-empty it is inserted as a "Focus Report"
    section ahead of even the overview — it answers the question the operator
    explicitly asked this run — quoting the ``focus`` so the document is
    self-describing. Both are additive; the per-sheet digests are unchanged.
    """
    total = len(sheets)
    lines: list[str] = [
        "# Drawing Set Context Digest",
        "",
        f"_{total} sheet(s) from {file_count} file(s), analyzed from the "
        f"construction drawings. Each section is one sheet; the spec reviewer "
        f"should treat this as reference context describing what the drawings "
        f"show._",
        "",
    ]
    if focus_report.strip():
        lines.append("## Focus Report (operator-requested)")
        lines.append("")
        if focus.strip():
            lines.append(f"_Operator focus for this run: {focus.strip()}_")
            lines.append("")
        lines.append(focus_report.strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    if overview.strip():
        lines.append("## Drawing Set Overview (cross-sheet synthesis)")
        lines.append("")
        lines.append(overview.strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    for i, sd in enumerate(sheets, start=1):
        lines.append(_sheet_header(i, total, sd.ref))
        lines.append("")
        if sd.error:
            lines.append(f"> [drawing analysis failed for this sheet: {sd.error}]")
        else:
            lines.append(sd.text.strip())
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _digest_sheets_concurrent(
    paths: list[Path],
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
    client: Any,
    model: str,
    max_tokens: int,
    use_thinking: bool,
    effort: str | None,
    cache: Any,
    progress: ProgressCallback | None,
    total: int,
    max_workers: int | None,
    focus: str | None = None,
) -> list[SheetDigest]:
    """Real-time path: render sequentially, digest on a bounded thread pool.

    Rendering (PyMuPDF, fast, not thread-safe to share) streams on the calling
    thread; the slow per-sheet digests run concurrently. ``results`` is filled by
    page index so the assembled order is deterministic, and at most ``workers``
    rendered sheets are held in flight, bounding memory on a large set.
    """
    workers = _resolve_workers(max_workers, total)
    results: list[SheetDigest | None] = [None] * total
    completed = 0

    def _run(index: int, rendered) -> tuple[int, SheetDigest]:
        return index, digest_sheet(
            rendered,
            client=client,
            model=model,
            max_tokens=max_tokens,
            use_thinking=use_thinking,
            effort=effort,
            cache=cache,
            focus=focus,
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight: set = set()

        def _collect_one() -> None:
            nonlocal completed
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in finished:
                in_flight.discard(fut)
                index, sd = fut.result()
                results[index] = sd
                completed += 1
                if progress is not None:
                    progress(completed, total, f"Analyzed {sd.ref.display_label}")

        for index, rendered in enumerate(
            iter_rendered_sheets(paths, rows=rows, cols=cols, overlap_frac=overlap_frac)
        ):
            in_flight.add(executor.submit(_run, index, rendered))
            while len(in_flight) >= workers:
                _collect_one()
        while in_flight:
            _collect_one()

    # Every slot is now populated (digest_sheet never raises); order preserved.
    return [sd for sd in results if sd is not None]


def _digest_sheets_via_batch(
    paths: list[Path],
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
    client: Any,
    model: str,
    max_tokens: int,
    use_thinking: bool,
    effort: str | None,
    cache: Any,
    progress: ProgressCallback | None,
    total: int,
    on_log: LogCallback | None = None,
    on_status: StatusCallback | None = None,
    focus: str | None = None,
) -> list[SheetDigest]:
    """Batch path: render-stream → Files-API upload → one Message Batch.

    Imported lazily so the real-time path (and a test that never touches batch)
    doesn't pull in the batch module. The client is resolved here when not
    injected, since the upload happens at submit time (the real-time path defers
    client creation to ``digest_sheet``).
    """
    from .batch_digest import collect_drawing_batch, submit_drawing_batch

    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    # Leveled batch diagnostics go to ``on_log`` when the caller supplies one
    # (the GUI routes these to its activity log); otherwise fall back to the
    # prior behavior of surfacing them on the progress line.
    if on_log is None and progress is not None:
        def on_log(msg: str, level: str = "info") -> None:
            progress(total, total, msg)

    batch = submit_drawing_batch(
        iter_rendered_sheets(paths, rows=rows, cols=cols, overlap_frac=overlap_frac),
        client=client,
        model=model,
        max_tokens=max_tokens,
        use_thinking=use_thinking,
        effort=effort,
        cache=cache,
        progress=progress,
        total=total,
        on_status=on_status,
        focus=focus,
    )
    # Run the post-batch file cleanup off the calling thread: the digests are
    # already in hand, and deleting a few hundred uploaded images one-by-one
    # (slower still under the Files-API overload that drove the run) would
    # otherwise leave the UI frozen for minutes after the work is really done.
    # Retry the batch's own per-item failures (server-side 500s/overload,
    # expired items, thinking-ate-the-budget empty digests) in one follow-up
    # batch while the uploaded file_ids are still alive — a real run lost 10
    # of 33 sheets to exactly these one-shot failures. Items the follow-up
    # batch still can't land (the batch backend itself erroring — a real run
    # lost all 8 sheets to `api_error` in both rounds) are digested via
    # synchronous per-item Messages calls on the same file_ids before cleanup.
    # The same opt-in covers a batch that never terminates at all (two real
    # runs sat `in_progress` with zero completions for the full 4h bound and
    # returned nothing): the stuck batch is canceled and every sheet digested
    # via those direct calls instead of the run coming back empty.
    return collect_drawing_batch(
        batch,
        client=client,
        cache=cache,
        progress=progress,
        on_log=on_log,
        cleanup_in_background=True,
        retry_failed_items=True,
    )


def _api_environment_fingerprint() -> str:
    """Name the SDK build and any base-URL override in one log token.

    These are the two facts that decide where an API request actually lands. A
    run whose every Files-API upload 404'd (a real incident) was undiagnosable
    from the per-request errors alone — the code was identical to the previous
    day's working run; what differed was the environment. Recording both at run
    start turns the next such incident into a one-line diff between a good run
    and a bad one. Import is lazy/defensive so the hermetic tests (which run
    against fake clients, without the SDK) never need ``anthropic`` installed.
    """
    try:
        from anthropic import __version__ as sdk_version
    except Exception:  # noqa: BLE001 - a missing/odd SDK must not sink the run
        sdk_version = "unavailable"
    base_url = os.environ.get("ANTHROPIC_BASE_URL") or "default"
    return f"sdk=anthropic-{sdk_version} base_url={base_url}"


def extract_drawing_context(
    pdf_paths: list[Path],
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    model: str = REVIEW_MODEL_DEFAULT,
    client: Any = None,
    max_tokens: int = DEFAULT_DIGEST_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_DIGEST_EFFORT,
    progress: ProgressCallback | None = None,
    cache: Any = None,
    use_cache: bool = False,
    max_workers: int | None = None,
    synthesize: bool = False,
    synthesis_model: str | None = None,
    use_batch: bool = False,
    on_log: LogCallback | None = None,
    on_status: StatusCallback | None = None,
    focus: str | None = None,
    focus_model: str | None = None,
) -> DrawingContext:
    """Render and digest every sheet in ``pdf_paths`` into one text context.

    ``progress`` (if given) is invoked as ``progress(done, total, label)`` as
    each sheet finishes and once at completion, so a GUI can show "k/n".
    ``on_log(message, level=...)`` (batch path only) receives leveled
    diagnostics — a batch that detached past the elapsed bound, or repeated poll
    failures — so a GUI can surface *why* a partial run came back incomplete;
    when omitted these fall back onto ``progress``.
    ``on_status(text)`` (batch path only) receives transient status-line updates —
    per-image upload progress, including any transient-503 retry wave — that are
    intentionally *not* logged, so a GUI's status line keeps moving during a
    sheet's multi-image upload without flooding its activity history.
    ``client`` is injectable for tests. Per-sheet failures are captured on the
    returned :class:`DrawingContext` (``errors`` and the failing sheet's
    ``SheetDigest.error``); they never abort the run.

    Digest caching is opt-in: pass an explicit ``cache``
    (:class:`~drawing_analyzer.digest_cache.DigestCache`), or ``use_cache=True`` to
    use the process-wide persistent cache, so an unchanged sheet on a re-run is
    served without a new vision call. Left off, the engine behaves exactly as
    before (hermetic tests never touch the on-disk cache).

    Digests run concurrently on up to ``max_workers`` threads (default
    :data:`DEFAULT_DIGEST_WORKERS`, or ``DRAWING_ANALYZER_MAX_WORKERS``);
    rendering stays sequential. Sheets are reassembled in page order, so the
    output is independent of completion order. ``max_workers=1`` forces fully
    sequential processing.

    ``synthesize=True`` runs one extra text-only pass after the digests that
    reconciles them into a "Drawing Set Overview" (cross-sheet references /
    conflicts), prepended to ``combined_text`` and exposed on
    ``DrawingContext.synthesis_text``. It is skipped for <2 readable sheets and
    falls back to the plain per-sheet digests on failure (the failure is
    recorded in ``errors``). ``synthesis_model`` overrides the synthesis model.

    ``use_batch=True`` digests every (uncached) sheet through the Message
    Batches API instead of the per-sheet real-time pool — 50% cheaper, and each
    sheet's images ride as Files-API ``file_id`` references so no request body
    approaches the 32 MB Messages-API limit (the failure the inline-base64 path
    hit on dense sheets). The batch is polled to completion on the calling
    thread; the cross-sheet synthesis still runs as one synchronous text-only
    call afterward. Caching, page ordering, and per-sheet error capture behave
    identically to the real-time path.

    ``focus`` (optional, at the operator's discretion) is a free-text per-run
    focus — e.g. *"I am particularly interested in the rooms, and what types of
    plumbing fixtures each has"*. The standard deliverable is unchanged; the
    focus is purely additive: each sheet's digest gains a final ``**Focus
    findings**`` section (the vision pass reads the drawings with the question
    in mind), and one extra text-only pass assembles the set-level **Focus
    Report** answering it (exposed on ``DrawingContext.focus_report_text`` and
    woven into ``combined_text``; ``focus_model`` overrides its model). The
    focus is folded into the digest cache key, so re-running with the same
    focus is served from cache, while changing or clearing it re-digests —
    a no-focus run keeps hitting pre-focus cache entries.
    """
    if cache is None and use_cache:
        from .digest_cache import get_default_digest_cache

        cache = get_default_digest_cache()

    focus = normalize_focus(focus) or ""

    paths = [Path(p) for p in pdf_paths]
    refs = list_sheets(paths)
    total = len(refs)
    file_count = len({r.pdf_path for r in refs})

    _log.info(
        "===== run start: %d file(s), %d sheet(s) | model=%s path=%s cache=%s "
        "synthesize=%s focus=%s | %s =====",
        file_count, total, model, "batch" if use_batch else "real-time",
        bool(cache is not None or use_cache), synthesize,
        repr(focus[:80]) if focus else False,
        _api_environment_fingerprint(),
    )

    if total == 0:
        if progress is not None:
            progress(0, 0, "No sheets found")
        return DrawingContext(
            combined_text="",
            file_count=len(paths),
            sheet_count=0,
            errors=["No readable PDF pages found in the selected files."],
        )

    if use_batch:
        sheets = _digest_sheets_via_batch(
            paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
            client=client, model=model, max_tokens=max_tokens,
            use_thinking=use_thinking, effort=effort, cache=cache,
            progress=progress, total=total, on_log=on_log, on_status=on_status,
            focus=focus or None,
        )
    else:
        sheets = _digest_sheets_concurrent(
            paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
            client=client, model=model, max_tokens=max_tokens,
            use_thinking=use_thinking, effort=effort, cache=cache,
            progress=progress, total=total, max_workers=max_workers,
            focus=focus or None,
        )

    errors: list[str] = []
    in_tok = out_tok = img_tok = 0
    for sd in sheets:
        # A cached sheet made no API call, so it costs zero tokens *this run*.
        # Excluding it keeps the run totals honest — a fully-cached re-run
        # reports ~0 tokens rather than the original (already-paid) usage that
        # ``SheetDigest`` still carries as provenance.
        if not sd.cached:
            in_tok += sd.input_tokens
            out_tok += sd.output_tokens
            img_tok += sd.image_token_estimate
        if sd.error:
            errors.append(f"{sd.ref.display_label}: {sd.error}")

    # Cross-sheet synthesis (one text-only call after all digests). Skipped for
    # <2 readable sheets; on failure we keep the per-sheet digests and record
    # the error rather than losing the whole run.
    synthesis_text = ""
    if synthesize:
        if progress is not None:
            progress(total, total, "Synthesizing set overview")
        from .synthesis import MIN_SHEETS_FOR_SYNTHESIS, synthesize_drawing_set

        _log.info("synthesis: starting cross-sheet overview")
        result = synthesize_drawing_set(sheets, client=client, model=synthesis_model)
        if result.ok:
            synthesis_text = result.text
            # The synthesis call is billed, so its tokens belong in the run total.
            in_tok += result.input_tokens
            out_tok += result.output_tokens
            _log.info(
                "synthesis: ok (input=%d output=%d tok)",
                result.input_tokens, result.output_tokens,
            )
        elif result.error and len([s for s in sheets if s.ok]) >= MIN_SHEETS_FOR_SYNTHESIS:
            # A genuine failure (not the "too few sheets" skip) is worth surfacing.
            errors.append(f"Cross-sheet synthesis: {result.error}")
            _log.warning("synthesis: failed: %s", result.error)
        else:
            _log.info("synthesis: skipped (<%d readable sheet(s))", MIN_SHEETS_FOR_SYNTHESIS)

    # Set-level focus report (one text-only call; independent of synthesis).
    # Additive: a failure here is recorded and the standard deliverable —
    # per-sheet digests plus any synthesis — ships exactly as it would have.
    focus_report_text = ""
    if focus:
        if progress is not None:
            progress(total, total, "Generating focus report")
        from .focus import MIN_SHEETS_FOR_FOCUS, generate_focus_report

        _log.info("focus report: starting set-level pass")
        fresult = generate_focus_report(
            sheets, focus, client=client, model=focus_model
        )
        if fresult.ok:
            focus_report_text = fresult.text
            # The focus call is billed, so its tokens belong in the run total.
            in_tok += fresult.input_tokens
            out_tok += fresult.output_tokens
            _log.info(
                "focus report: ok (input=%d output=%d tok)",
                fresult.input_tokens, fresult.output_tokens,
            )
        elif fresult.error and len([s for s in sheets if s.ok]) >= MIN_SHEETS_FOR_FOCUS:
            errors.append(f"Focus report: {fresult.error}")
            _log.warning("focus report: failed: %s", fresult.error)
        else:
            _log.info(
                "focus report: skipped (<%d readable sheet(s))", MIN_SHEETS_FOR_FOCUS
            )

    if progress is not None:
        progress(total, total, "Done")

    ok_count = sum(1 for s in sheets if s.ok)
    cached_count = sum(1 for s in sheets if s.cached)
    _log.info(
        "===== run done: %d/%d ok, %d cached, %d issue(s) | input=%d output=%d "
        "image_est=%d tok =====",
        ok_count, total, cached_count, len(errors), in_tok, out_tok, img_tok,
    )
    for err in errors:
        _log.warning("issue: %s", err)

    return DrawingContext(
        combined_text=_combine(
            sheets,
            file_count=file_count,
            overview=synthesis_text,
            focus=focus,
            focus_report=focus_report_text,
        ),
        sheets=sheets,
        file_count=file_count,
        sheet_count=total,
        total_input_tokens=in_tok,
        total_output_tokens=out_tok,
        total_image_token_estimate=img_tok,
        errors=errors,
        synthesis_text=synthesis_text,
        focus=focus,
        focus_report_text=focus_report_text,
    )


def estimate_image_tokens_for_set(
    sheet_count: int,
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    model: str = REVIEW_MODEL_DEFAULT,
) -> int:
    """Rough upper-bound image-token estimate for a set, for a GUI budget preview.

    Assumes every image (overview + tiles) lands at the per-model cap, which is
    the worst case for a dense sheet at the target render resolution. Uses the
    **raster** long-edge target as that per-image size: a sheet's rasterness is
    unknown before rendering, and a raster sheet renders larger (the raster
    target) than a vector one (the reduced default), so quoting the raster target
    keeps this a true upper bound that never under-quotes. Vector sheets — the
    common case — then render smaller and cost less than quoted, which is the
    safe direction for a pre-run budget confirmation.
    """
    images_per_sheet = tiling.total_images_for_grid(rows, cols)
    long_edge = tiling.target_long_edge_px(images_per_sheet, is_raster=True)
    # A square image at the long-edge target is the largest area (hence most
    # tokens) the renderer can emit, so it bounds the per-image cost from above.
    per_image = estimate_image_tokens(long_edge, long_edge, model=model)
    return sheet_count * images_per_sheet * per_image
