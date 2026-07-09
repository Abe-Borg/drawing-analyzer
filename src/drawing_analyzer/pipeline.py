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
    DIGEST_PROMPT_VERSION,
    SheetDigest,
    cache_entry_from_digest,
    digest_sheet,
    focus_cache_fragment,
    normalize_focus,
    sheet_digest_from_cache_entry,
)
from .digest_cache import digest_cache_key_level1
from .models import Finding, SheetGeometry
from .render import iter_rendered_sheets, iter_sheet_prescan, list_sheets

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
    # --- QC findings (populated when reference_audit / qc_markups are on) ------
    # Model findings parsed from the digests, anchored and (when qc_markups)
    # verified. ``reference_findings`` are the deterministic reference-audit
    # findings (already anchored, DETERMINISTIC). ``reviewed_pdf_paths`` are the
    # ``*_reviewed.pdf`` files written when qc_markups is on; ``sheet_geometries``
    # carries each sheet's text/geometry for the findings exports; ``qc_work_dir``
    # holds the run's evidence crops + reviewed PDFs until they are exported.
    findings: list[Finding] = field(default_factory=list)
    reference_findings: list[Finding] = field(default_factory=list)
    reviewed_pdf_paths: list[Path] = field(default_factory=list)
    sheet_geometries: list[Any] = field(default_factory=list)
    qc_work_dir: Path | None = None

    @property
    def ok_sheet_count(self) -> int:
        return sum(1 for s in self.sheets if s.ok)

    @property
    def cached_sheet_count(self) -> int:
        """Sheets served from the digest cache (no API call / token cost)."""
        return sum(1 for s in self.sheets if getattr(s, "cached", False))

    @property
    def all_findings(self) -> list["Finding"]:
        """Model findings + deterministic reference findings (the full record)."""
        return list(self.findings) + list(self.reference_findings)

    @property
    def finding_count(self) -> int:
        return len(self.findings) + len(self.reference_findings)

    @property
    def clouded_finding_count(self) -> int:
        """Findings that would be inked under default (verified-only) gating."""
        from .annotate import is_cloudable

        return sum(
            1 for f in self.all_findings if is_cloudable(f, include_unverified=False)
        )


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


def _rendered_stream(
    paths: list[Path],
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
    geometry_sink: list | None,
    only: "set[tuple[str, int]] | None" = None,
) -> "Any":
    """Stream :class:`RenderedSheet`, capturing each sheet's lightweight geometry.

    When ``geometry_sink`` is given, a :class:`SheetGeometry` (text + geometry,
    **no PNG bytes**) is appended per sheet as it renders, so the QC stages can
    anchor / verify / export after the images are gone — the batch path streams
    and discards each rendered sheet after upload, so this is the only place the
    per-sheet geometry survives. ``None`` disables capture (a plain digest run
    keeps no findings state and holds nothing extra).

    ``only`` restricts rendering to the given sheet identities (the level-1 cache
    passes the set of sheets that missed, so cached sheets never render). Geometry
    for cached sheets is captured separately during the pre-scan, so when ``only``
    is in play the caller passes ``geometry_sink=None`` here.
    """
    for rendered in iter_rendered_sheets(
        paths, rows=rows, cols=cols, overlap_frac=overlap_frac, only=only
    ):
        if geometry_sink is not None:
            geometry_sink.append(SheetGeometry.from_rendered(rendered))
        yield rendered


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
    geometry_sink: list | None = None,
    only: "set[tuple[str, int]] | None" = None,
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
            _rendered_stream(
                paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
                geometry_sink=geometry_sink, only=only,
            )
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
    geometry_sink: list | None = None,
    only: "set[tuple[str, int]] | None" = None,
) -> list[SheetDigest]:
    """Batch path: render-stream → Files-API upload → one Message Batch.

    Imported lazily so the real-time path (and a test that never touches batch)
    doesn't pull in the batch module. The client is resolved here when not
    injected, since the upload happens at submit time (the real-time path defers
    client creation to ``digest_sheet``). ``geometry_sink`` captures each sheet's
    lightweight geometry as it renders (before the batch discards the rendered
    sheet), so the QC stages survive the upload.
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
        _rendered_stream(
            paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
            geometry_sink=geometry_sink, only=only,
        ),
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


def _refkey(ref: Any) -> tuple[str, int]:
    """Full sheet identity (PDF path + page) — the merge/skip key for level-1."""
    return (str(getattr(ref, "pdf_path", "")), int(getattr(ref, "page_index", 0) or 0))


def _level1_partition(
    paths: list[Path],
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
    cache: Any,
    model: str,
    max_tokens: int,
    use_thinking: bool,
    effort: str | None,
    focus: str | None,
) -> "tuple[dict, set, dict, list]":
    """Pre-render level-1 cache scan (Phase 9).

    Walks every sheet with :func:`iter_sheet_prescan` — page access only, no
    rasterization — and, per sheet, computes the level-1 key and probes the cache.
    Returns ``(cached_by_ref, miss_only, level1_keys, geometries)``:

    - ``cached_by_ref`` — ``_refkey`` → a cached :class:`SheetDigest` for each hit
      (served without ever rendering, ``cached=True``);
    - ``miss_only`` — the set of ``(str(path), page_index)`` that missed, handed to
      the render stream's ``only`` so exactly those sheets rasterize;
    - ``level1_keys`` — ``_refkey`` → level-1 key, so a miss's fresh digest can be
      stored under it;
    - ``geometries`` — every sheet's lightweight geometry (hit or miss), for QC.
    """
    cached_by_ref: dict[tuple[str, int], SheetDigest] = {}
    miss_only: set[tuple[str, int]] = set()
    level1_keys: dict[tuple[str, int], str] = {}
    geometries: list[SheetGeometry] = []
    focus_frag = focus_cache_fragment(focus)
    for ref, identity, geometry in iter_sheet_prescan(
        paths, rows=rows, cols=cols, overlap_frac=overlap_frac
    ):
        geometries.append(geometry)
        key = digest_cache_key_level1(
            identity,
            model=model,
            prompt_version=DIGEST_PROMPT_VERSION,
            max_tokens=max_tokens,
            effort=effort,
            use_thinking=use_thinking,
            focus=focus_frag,
        )
        rk = _refkey(ref)
        level1_keys[rk] = key
        entry = cache.get(key)
        if entry is not None:
            cached_by_ref[rk] = sheet_digest_from_cache_entry(entry, ref)
        else:
            miss_only.add(rk)
    return cached_by_ref, miss_only, level1_keys, geometries


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


@dataclass
class _QCResult:
    findings: list[Finding] = field(default_factory=list)
    reference_findings: list[Finding] = field(default_factory=list)
    reviewed_pdf_paths: list[Path] = field(default_factory=list)
    work_dir: Path | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def _run_critique_stage(
    paths: list[Path],
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
    client: Any,
    cache: Any,
    progress: ProgressCallback | None,
    total: int,
    max_workers: int | None,
    profiles: list | None = None,
) -> tuple[list[Finding], int, int]:
    """Critique every sheet (Phase 11): re-render, then self-consistent critique.

    Path-agnostic — it re-renders from the PDFs because none of the digest paths
    (batch, real time, or a cache hit) retain the images the critique needs — so
    it streams renders on the calling thread while the per-sheet self-consistent
    critiques run on the same bounded pool the digests use. Each sheet's *merged*
    critique is cached under its own key, so a re-run skips the model calls (the
    render still runs; a level-1 render-skip for the critique is a later
    optimization). Additive and non-fatal: a per-sheet failure is logged and
    contributes no findings; the run continues.

    Returns ``(critique_findings, input_tokens, output_tokens)``; the findings are
    sorted deterministically so the pooled result is independent of completion
    order (I-7).
    """
    from .critique import critique_sheet_self_consistent

    workers = _resolve_workers(max_workers, total)
    findings: list[Finding] = []
    in_tok = out_tok = 0
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight: set = set()

        def _collect_one() -> None:
            nonlocal done, in_tok, out_tok
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in finished:
                in_flight.discard(fut)
                done += 1
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
                    _log.warning("critique failed for a sheet: %s", exc)
                    continue
                if res.error:
                    _log.warning("critique degraded for a sheet: %s", res.error)
                findings.extend(res.findings)
                # A cache hit made no API call this run, so exclude its (original)
                # token cost — keeping run totals honest, as the digest path does
                # for cached sheets.
                if not res.cached:
                    in_tok += res.input_tokens
                    out_tok += res.output_tokens
                if progress is not None:
                    progress(total, total, f"Critiquing sheet {done}/{total}")

        for rendered in iter_rendered_sheets(
            paths, rows=rows, cols=cols, overlap_frac=overlap_frac
        ):
            in_flight.add(
                executor.submit(
                    critique_sheet_self_consistent,
                    rendered, client=client, cache=cache, profiles=profiles,
                )
            )
            while len(in_flight) >= workers:
                _collect_one()
        while in_flight:
            _collect_one()

    findings.sort(key=lambda f: (f.source_name, f.page_index, f.id))
    _log.info("critique: %d finding(s) across %d sheet(s)", len(findings), total)
    return findings, in_tok, out_tok


def _run_qc_stages(
    *,
    sheets: list[SheetDigest],
    geometries: list[SheetGeometry],
    pdf_paths: list[Path],
    reference_audit_enabled: bool,
    qc_markups: bool,
    markup_verified_only: bool,
    verify_enabled: bool,
    client: Any,
    qc_work_dir: Path | None,
    progress: ProgressCallback | None,
    total: int,
    errors: list[str],
    critique_findings: list[Finding] | None = None,
) -> _QCResult:
    """Run the QC pipeline after the digests: audit → anchor → verify → markups.

    Every stage is additive and non-fatal (I-3): a failure is recorded in
    ``errors`` and the standard deliverable still ships. Model findings come from
    the parsed digests; reference findings from the deterministic audit (already
    anchored). Reviewed PDFs and evidence crops are written under ``work_dir`` (a
    fresh temp dir when none is given), to be exported later.

    ``critique_findings`` (Phase 11), when present, are pooled with the digest
    findings before anchoring: :func:`drawing_analyzer.critique.merge_finding_groups`
    deduplicates the two sources per sheet (``_is_duplicate`` is same-sheet-gated,
    so passing the whole set as two groups only ever merges within a sheet) and
    marks an issue both the digest and the critique raised as ``reproduced``.
    """
    digest_findings = [f for sd in sheets for f in getattr(sd, "findings", None) or []]
    if critique_findings:
        from .critique import merge_finding_groups

        findings = merge_finding_groups([digest_findings, critique_findings])
    else:
        findings = digest_findings
    reference_findings: list[Finding] = []
    work_dir = qc_work_dir

    if reference_audit_enabled and geometries:
        if progress is not None:
            progress(total, total, "Auditing references")
        try:
            from .reference_audit import audit_references

            reference_findings = audit_references(geometries)
            _log.info("reference audit: %d finding(s)", len(reference_findings))
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            errors.append(f"Reference audit: {exc}")
            _log.warning("reference audit failed: %s", exc)

    # Anchor model findings (reference findings arrive already anchored).
    if findings and geometries and (qc_markups or reference_audit_enabled or critique_findings):
        if progress is not None:
            progress(total, total, "Anchoring findings")
        from .anchor import resolve_anchors

        geom_by_key = {(g.ref.source_name, g.ref.page_index): g for g in geometries}
        by_sheet: dict[tuple, list[Finding]] = {}
        for finding in findings:
            by_sheet.setdefault((finding.source_name, finding.page_index), []).append(finding)
        for key, sheet_findings in by_sheet.items():
            geometry = geom_by_key.get(key)
            if geometry is None:
                continue
            try:
                resolve_anchors(sheet_findings, geometry)
            except Exception as exc:  # noqa: BLE001 - never fatal
                _log.warning("anchoring failed for %s: %s", key, exc)

    all_findings = findings + reference_findings
    v_in = v_out = 0

    # Verify model findings (deterministic reference findings are skipped by the
    # verifier). Only when markups are requested — clouds are what demand trust.
    if qc_markups and verify_enabled and findings:
        from .verify import verify_findings as _run_verify

        if work_dir is None:
            import tempfile

            work_dir = Path(tempfile.mkdtemp(prefix="drawing_qc_"))
        evidence_dir = work_dir / "evidence"

        def _verify_progress(done: int, tot: int, label: str) -> None:
            if progress is not None:
                progress(total, total, label)   # keep the sheet bar full; label = "Verifying finding k/n"

        try:
            vres = _run_verify(
                all_findings, geometries, client=client,
                evidence_dir=evidence_dir, progress=_verify_progress,
            )
            v_in, v_out = vres.input_tokens, vres.output_tokens
            _log.info(
                "verification: %d verified, %d rejected, %d uncertain, %d skipped",
                vres.verified, vres.rejected, vres.uncertain, vres.skipped,
            )
        except Exception as exc:  # noqa: BLE001 - never fatal
            errors.append(f"Verification: {exc}")
            _log.warning("verification failed: %s", exc)

    reviewed_pdf_paths: list[Path] = []
    if qc_markups:
        from .annotate import write_reviewed_pdfs

        if work_dir is None:
            import tempfile

            work_dir = Path(tempfile.mkdtemp(prefix="drawing_qc_"))
        if progress is not None:
            progress(total, total, "Writing markups")
        try:
            reviewed_pdf_paths = write_reviewed_pdfs(
                all_findings, pdf_paths, work_dir,
                include_unverified=not markup_verified_only,
            )
            _log.info("markups: %d reviewed PDF(s) written", len(reviewed_pdf_paths))
        except Exception as exc:  # noqa: BLE001 - never fatal
            errors.append(f"Markup writing: {exc}")
            _log.warning("markup writing failed: %s", exc)

    return _QCResult(
        findings=findings,
        reference_findings=reference_findings,
        reviewed_pdf_paths=reviewed_pdf_paths,
        work_dir=work_dir,
        input_tokens=v_in,
        output_tokens=v_out,
    )


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
    reference_audit: bool = False,
    qc_markups: bool = False,
    markup_verified_only: bool = True,
    verify_findings: bool = True,
    critique: bool = False,
    profiles: list | None = None,
    qc_work_dir: Path | None = None,
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

    ``critique=True`` (Phase 11) adds a dedicated **critique pass**: a second
    full-coverage vision read per sheet, under a senior-QA-engineer persona, whose
    only job is finding problems (errors, code concerns, RFI-worthy ambiguities,
    inconsistencies, stale text, and *absences*). It runs self-consistently — two
    independent reads merged, an issue both raise flagged ``reproduced`` — and its
    findings pool with the digest's before anchoring, so ``findings`` carries the
    union. Additive and non-fatal (a failure is recorded in ``errors``); the prose
    digest is untouched (I-2). The merged critique is cached under its own key, so
    a re-run skips the extra calls. It re-renders each sheet (the digest images are
    gone by then), so it is meaningfully more expensive — the exhaustive QC mode.

    ``profiles`` (Phase 12) is a list of review-profile names (or
    :class:`~drawing_analyzer.profiles.Profile` objects) whose checklists are
    injected into the critique prompt, so the model applies the owner's encoded QC
    knowledge item by item. Unknown names are skipped (non-fatal). The selected
    profiles' fingerprint folds into the critique cache key, so choosing or editing
    a profile re-critiques. Ignored unless ``critique=True``.
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

    # The QC stages (reference audit, anchoring, verification, markups) run over
    # each sheet's text/geometry after the digests, so capture that lightweight
    # record as sheets render (the batch path discards the rendered sheets after
    # upload). Only captured when a QC stage will actually use it.
    need_geometry = reference_audit or qc_markups or critique
    sheet_geometries: list[SheetGeometry] = []
    geometry_sink = sheet_geometries if need_geometry else None

    # Level-1 cache pre-scan (Phase 9): recognize unchanged sheets *before*
    # rendering and skip rasterization for them (the dominant re-run cost). Only
    # when a cache is active — with no cache every sheet renders as before, and
    # geometry (for the QC stages) is captured during that render.
    cached_by_ref: dict[tuple[str, int], SheetDigest] = {}
    level1_keys: dict[tuple[str, int], str] = {}
    only: set[tuple[str, int]] | None = None
    if cache is not None:
        cached_by_ref, only, level1_keys, prescan_geoms = _level1_partition(
            paths, rows=rows, cols=cols, overlap_frac=overlap_frac, cache=cache,
            model=model, max_tokens=max_tokens, use_thinking=use_thinking,
            effort=effort, focus=focus or None,
        )
        if need_geometry:
            sheet_geometries.extend(prescan_geoms)
        # The pre-scan already captured geometry for every sheet, so the render
        # stream must not re-capture (it only sees the misses anyway).
        geometry_sink = None
        _log.info(
            "level-1 cache: %d/%d sheet(s) hit — skipping render for them",
            len(cached_by_ref), total,
        )
        if cached_by_ref and progress is not None:
            progress(
                len(cached_by_ref), total,
                f"{len(cached_by_ref)} sheet(s) from cache — skipping render",
            )

    miss_total = total if only is None else len(only)

    miss_sheets: list[SheetDigest] = []
    if miss_total > 0:
        if use_batch:
            miss_sheets = _digest_sheets_via_batch(
                paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
                client=client, model=model, max_tokens=max_tokens,
                use_thinking=use_thinking, effort=effort, cache=cache,
                progress=progress, total=miss_total, on_log=on_log,
                on_status=on_status, focus=focus or None,
                geometry_sink=geometry_sink, only=only,
            )
        else:
            miss_sheets = _digest_sheets_concurrent(
                paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
                client=client, model=model, max_tokens=max_tokens,
                use_thinking=use_thinking, effort=effort, cache=cache,
                progress=progress, total=miss_total, max_workers=max_workers,
                focus=focus or None, geometry_sink=geometry_sink, only=only,
            )

    # Store each miss's result under its level-1 key too (store-under-both), so a
    # next run recognizes the sheet pre-render and skips rasterization. Only a
    # real, non-empty digest is stored — mirroring digest_sheet's own guard.
    if cache is not None:
        for sd in miss_sheets:
            if sd.error is None and (sd.text or "").strip():
                key = level1_keys.get(_refkey(sd.ref))
                if key is not None:
                    cache.put(key, cache_entry_from_digest(sd))

    # Merge cached + freshly-digested sheets, restoring original (page) order.
    by_ref = dict(cached_by_ref)
    for sd in miss_sheets:
        by_ref[_refkey(sd.ref)] = sd
    sheets = [by_ref[_refkey(r)] for r in refs if _refkey(r) in by_ref]

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

    # Critique pass (Phase 11): a second, adversarial full-coverage read per sheet
    # whose only job is finding problems, run self-consistently (twice) and merged.
    # Additive and non-fatal; its findings pool with the digest findings in the QC
    # stage below. Re-renders each sheet (the digest images are gone by now), so
    # it runs before the QC stages that consume the pooled findings.
    critique_findings: list[Finding] = []
    if critique:
        if progress is not None:
            progress(total, total, "Critiquing sheets")
        try:
            from .profiles import resolve_profiles

            resolved_profiles = resolve_profiles(profiles)
            if resolved_profiles:
                _log.info(
                    "critique: applying %d review profile(s): %s",
                    len(resolved_profiles),
                    ", ".join(p.name for p in resolved_profiles),
                )
            critique_findings, c_in, c_out = _run_critique_stage(
                paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
                client=client, cache=cache, progress=progress, total=total,
                max_workers=max_workers, profiles=resolved_profiles,
            )
            in_tok += c_in
            out_tok += c_out
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            errors.append(f"Critique: {exc}")
            _log.warning("critique stage failed: %s", exc)

    # QC pipeline (audit → anchor → verify → markups). Additive and non-fatal;
    # runs before synthesis/focus so those are untouched. Only the reference
    # audit and the markups are gated by their flags; findings are always parsed
    # off the digests (and pooled with any critique findings), but they are only
    # anchored/verified when a QC stage needs them (``need_geometry``).
    qc = _QCResult()
    if need_geometry:
        qc = _run_qc_stages(
            sheets=sheets, geometries=sheet_geometries, pdf_paths=paths,
            reference_audit_enabled=reference_audit, qc_markups=qc_markups,
            markup_verified_only=markup_verified_only, verify_enabled=verify_findings,
            client=client, qc_work_dir=qc_work_dir, progress=progress,
            total=total, errors=errors, critique_findings=critique_findings,
        )
        in_tok += qc.input_tokens
        out_tok += qc.output_tokens

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
        findings=qc.findings,
        reference_findings=qc.reference_findings,
        reviewed_pdf_paths=qc.reviewed_pdf_paths,
        sheet_geometries=sheet_geometries,
        qc_work_dir=qc.work_dir,
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
