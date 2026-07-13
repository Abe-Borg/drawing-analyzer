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
from .models import (
    Finding,
    NumericClaim,
    RunConfiguration,
    RunUsage,
    SheetGeometry,
    StageResult,
    UsageRecord,
    resolve_run_configuration,
    roll_up_qc_status,
    source_page_key,
)
from .render import inspect_inputs, iter_rendered_sheets, iter_sheet_prescan, list_sheets
from .source_registry import EST_BYTES_PER_SHEET, check_set_limits, check_work_disk

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

# Phase 23 temporary completeness gate (§8, §15.5). While this is closed, a fully
# successful exhaustive QC run is capped at ``QCStatus.PARTIAL`` rather than
# ``COMPLETE`` — Phases 24–25 have not yet landed the cross-shard reconciliation,
# claim-complete citations, complete evidence, and callout-overflow guarantees a
# COMPLETE exhaustive review must prove. Phase 26 opens the gate once those close.
# It is deliberately a module constant so a single edit removes the gate.
EXHAUSTIVE_QC_COMPLETENESS_GATE_OPEN = False

_log = get_logger()


def _record_usage(
    run_usage: RunUsage,
    *,
    family: str,
    instance: str,
    model: str,
    transport: str = "REAL_TIME",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    billable_tool_uses: "dict | None" = None,
    cache_hit: bool = False,
    parse_success: bool = True,
    terminal_status: str = "COMPLETE",
    parent: "str | None" = None,
    attempt: int = 1,
    request_id: str = "",
) -> UsageRecord:
    """Build a priced :class:`UsageRecord` and append it to the run's usage ledger.

    The one place a stage's reported usage becomes a record (§15.6) — append-only,
    so no stage can overwrite another's counters. ``estimated_cost`` is priced at
    the record's own rate class (batch vs real-time, cache read/write, tool uses);
    a ``CACHE`` transport passes zero token counts, so its token cost is zero.
    """
    from .core.pricing import usage_record_cost

    cost = usage_record_cost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        billable_tool_uses=billable_tool_uses,
        batch=(transport == "BATCH"),
    )
    return run_usage.add(
        UsageRecord(
            stage_family=family,
            stage_instance=instance,
            model=model,
            transport=transport,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            cache_read_tokens=int(cache_read_tokens),
            cache_write_tokens=int(cache_write_tokens),
            billable_tool_uses=dict(billable_tool_uses or {}),
            cache_hit=cache_hit,
            parse_success=parse_success,
            terminal_status=terminal_status,
            parent_stage_instance=parent,
            attempt_number=attempt,
            billing_rate_class=transport.lower(),
            request_or_custom_id=request_id,
            estimated_cost=cost,
        )
    )


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


def _markup_appendix_enabled() -> bool:
    """Whether the reviewed PDFs get the optional "checked and consistent"
    appendix page (``DRAWING_ANALYZER_MARKUP_APPENDIX=1``; off by default)."""
    return (os.environ.get("DRAWING_ANALYZER_MARKUP_APPENDIX") or "").strip() in (
        "1", "true", "yes", "on",
    )


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
    # verified. ``reference_findings`` are the deterministic-auditor findings
    # (Phase 14: references + arithmetic + naming + title-block + sheet-index; all
    # already anchored, DETERMINISTIC). ``reviewed_pdf_paths`` are the
    # ``*_reviewed.pdf`` files written when qc_markups is on; ``sheet_geometries``
    # carries each sheet's text/geometry for the findings exports; ``qc_work_dir``
    # holds the run's evidence crops + reviewed PDFs until they are exported.
    # ``audit_stats`` is the deterministic battery's checks-run/passed tally (e.g.
    # the "N numeric relationships checked ✓" line).
    findings: list[Finding] = field(default_factory=list)
    reference_findings: list[Finding] = field(default_factory=list)
    reviewed_pdf_paths: list[Path] = field(default_factory=list)
    sheet_geometries: list[Any] = field(default_factory=list)
    qc_work_dir: Path | None = None
    audit_stats: dict = field(default_factory=dict)
    # Part III (§18): the run's coverage tally over the findings ledger —
    # {"cloud": n, "margin": n, "rejected": n, ("gated": n)}. It accounts for
    # PDF ink, so it is empty when no QC stage ran OR markups were disabled.
    # Surfaced in the GUI completion summary and the report header.
    ledger_tally: dict = field(default_factory=dict)
    # Display names of sources whose bytes changed between analysis and markup
    # (Phase 18C §10.6). Non-empty means QC is incomplete: those sources were
    # NOT marked up (stale anchors are never written onto changed bytes), a
    # rerun is required, and the change is also recorded in ``errors``.
    mutated_sources: list[str] = field(default_factory=list)
    # Phase 21 (DA-007): the run's receipt-derived markup coverage.
    # ``coverage_status`` is NOT_REQUESTED (no markups), COMPLETE (every planned
    # placement proven in the saved PDF), or INCOMPLETE (a placement is missing /
    # failed / a source changed mid-run). ``markup_run`` is the full
    # :class:`~drawing_analyzer.models.MarkupRunResult` (placements + receipts)
    # that backs ``markup_manifest.json``. Surfaced as a banner in the report and
    # a three-state completion in the GUI.
    coverage_status: str = "NOT_REQUESTED"
    markup_run: Any = None
    # Phase 23A (§15.1 / §15.4): the resolved run configuration, the typed
    # per-stage outcomes, and the overall QC status the completion dialog / report
    # header lead with. ``qc_status`` is NOT_REQUESTED unless exhaustive QC ran;
    # otherwise COMPLETE / PARTIAL / FAILED per the §3.3 roll-up (capped at PARTIAL
    # by the Phase 23 temporary completeness gate).
    run_configuration: Any = None
    stage_results: list = field(default_factory=list)
    qc_status: str = "NOT_REQUESTED"
    # Phase 23B (§15.6): the run's append-only usage ledger. ``total_input_tokens`` /
    # ``total_output_tokens`` above are derived sums over it; ``total_estimated_cost``
    # and the per-stage-family breakdown come from it too.
    run_usage: Any = None

    @property
    def total_estimated_cost(self) -> Any:
        """The run's estimated USD cost (``Decimal``), or ``None`` if unpriceable."""
        ru = self.run_usage
        return ru.total_estimated_cost if ru is not None else None

    @property
    def usage_by_family(self) -> dict:
        """Per-stage-family token/cost/call rollup (empty when no usage recorded)."""
        ru = self.run_usage
        return ru.by_family() if ru is not None else {}

    @property
    def configuration_kind(self) -> str:
        """NORMAL, or DEBUG_OVERRIDE when an explicit flag weakened exhaustive QC."""
        cfg = self.run_configuration
        return getattr(cfg, "configuration_kind", "NORMAL") if cfg is not None else "NORMAL"

    @property
    def qc_status_label(self) -> str:
        """A human three-state label for the GUI completion dialog / report (§3.3)."""
        return {
            "NOT_REQUESTED": "Completed",
            "COMPLETE": "Exhaustive QC complete",
            "PARTIAL": "Completed with QC warnings",
            "FAILED": "QC incomplete",
        }.get(self.qc_status, "Completed")

    @property
    def ledger_tally_line(self) -> str:
        """The Phase 21 run-summary line, or ``""`` when no markups were written."""
        if not self.ledger_tally:
            return ""
        return _tally_line(self.finding_count, self.ledger_tally, self.coverage_status)

    @property
    def markup_incomplete(self) -> bool:
        """True when markups were requested but coverage came back INCOMPLETE."""
        return self.coverage_status == "INCOMPLETE"

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
        """Findings clouded by this run (from the ledger tally when QC ran)."""
        if self.ledger_tally:
            return int(self.ledger_tally.get("cloud", 0))
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
    on_page_error: "Any" = None,
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
        paths, rows=rows, cols=cols, overlap_frac=overlap_frac, only=only,
        on_page_error=on_page_error,
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
    on_page_error: "Any" = None,
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
                geometry_sink=geometry_sink, only=only, on_page_error=on_page_error,
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
    snapshot_by_path: "dict[str, tuple[str, int, int]] | None" = None,
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
        paths, rows=rows, cols=cols, overlap_frac=overlap_frac, snapshot_by_path=snapshot_by_path
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
    audit_stats: dict = field(default_factory=dict)
    ledger_tally: dict = field(default_factory=dict)
    mutated_sources: list[str] = field(default_factory=list)
    # Phase 21 (DA-007): the artifact-backed markup accounting. ``coverage_status``
    # is receipt-derived (COMPLETE / INCOMPLETE / NOT_REQUESTED); ``markup_run`` is
    # the full :class:`MarkupRunResult` (placements + receipts) for the manifest.
    coverage_status: str = "NOT_REQUESTED"
    markup_run: Any = None
    # Phase 23A (§15.4): the QC-stage outcomes the overall status rolls up from —
    # auditors, prose harvest, verification, citation, and markup/coverage. The
    # pre-ledger stages (synthesis, critique, cross-QC) are recorded by the caller.
    stage_results: list[StageResult] = field(default_factory=list)


def _critique_level1_partition(
    paths: list[Path],
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
    cache: Any,
    model: str,
    runs: int,
    profiles_key: str | None,
    snapshot_by_path: "dict[str, tuple[str, int, int]] | None" = None,
) -> "tuple[dict, set, dict]":
    """Pre-render level-1 cache scan for the critique stage (Phase 19B, §11.5).

    Mirrors :func:`_level1_partition` for the digest: walks every sheet via
    :func:`iter_sheet_prescan` (page access only, no rasterization), computes the
    critique level-1 key over the *same* render identity the digest keys on, and
    probes the critique cache. Returns ``(cached_by_ref, miss_only, level1_keys)``
    — a hit is served as a merged :class:`~drawing_analyzer.critique.CritiqueResult`
    with neither a render nor an API call; a miss renders and critiques and its
    result is stored under its level-1 key (store-under-both).
    """
    from .critique import (
        CRITIQUE_PROMPT_VERSION,
        DEFAULT_CRITIQUE_EFFORT,
        DEFAULT_CRITIQUE_MAX_TOKENS,
        critique_result_from_entry,
    )
    from .digest_cache import critique_cache_key_level1

    cached_by_ref: dict[tuple[str, int], Any] = {}
    miss_only: set[tuple[str, int]] = set()
    level1_keys: dict[tuple[str, int], str] = {}
    for ref, identity, _geom in iter_sheet_prescan(
        paths, rows=rows, cols=cols, overlap_frac=overlap_frac, snapshot_by_path=snapshot_by_path
    ):
        key = critique_cache_key_level1(
            identity,
            model=model,
            prompt_version=CRITIQUE_PROMPT_VERSION,
            max_tokens=DEFAULT_CRITIQUE_MAX_TOKENS,
            effort=DEFAULT_CRITIQUE_EFFORT,
            use_thinking=True,
            runs=runs,
            profiles_key=profiles_key,
        )
        rk = _refkey(ref)
        level1_keys[rk] = key
        entry = cache.get(key)
        if entry is not None:
            cached_by_ref[rk] = critique_result_from_entry(entry, ref)
        else:
            miss_only.add(rk)
    return cached_by_ref, miss_only, level1_keys


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
    run_usage: RunUsage,
    profiles: list | None = None,
    snapshot_by_path: "dict[str, tuple[str, int, int]] | None" = None,
) -> tuple[list[Finding], list[NumericClaim]]:
    """Critique every sheet (Phase 11): self-consistent critique, cached two ways.

    A **level-1** pre-render cache scan (Phase 19B) recognizes unchanged sheets
    before rasterizing, so a warm exhaustive re-run skips **both** the render and
    the critique API calls for a cached sheet — the level-2 (PNG-bytes) cache alone
    still had to rasterize to discover the hit. Only the sheets that miss level-1
    are re-rendered (streamed on the calling thread) and critiqued on the same
    bounded pool the digests use; each complete result is then stored under its
    level-1 key too (store-under-both). Additive and non-fatal: a per-sheet failure
    is logged and contributes no findings; the run continues.

    Returns ``(critique_findings, claims)``; the findings are sorted deterministically
    so the pooled result is independent of completion order (I-7). ``claims`` are the
    numeric relationships the critique transcribed (Phase 14), fed to the deterministic
    arithmetic auditor. Per-sheet usage is appended to ``run_usage`` (§15.6): a
    ``critique`` record per sheet (``CACHE`` for a hit — zero billed tokens — else
    ``REAL_TIME``); each record aggregates the sheet's two self-consistency reads.
    """
    from .critique import (
        critique_cache_entry_from_result,
        critique_model,
        critique_runs,
        critique_sheet_self_consistent,
    )
    from .profiles import profiles_cache_fragment

    model = critique_model()
    runs = critique_runs()
    profiles_key = profiles_cache_fragment(profiles or [])

    cached_by_ref: dict[tuple[str, int], Any] = {}
    level1_keys: dict[tuple[str, int], str] = {}
    only: set[tuple[str, int]] | None = None
    if cache is not None:
        cached_by_ref, only, level1_keys = _critique_level1_partition(
            paths, rows=rows, cols=cols, overlap_frac=overlap_frac, cache=cache,
            model=model, runs=runs, profiles_key=profiles_key, snapshot_by_path=snapshot_by_path,
        )
        if cached_by_ref:
            _log.info(
                "level-1 critique cache: %d/%d sheet(s) hit — skipping render",
                len(cached_by_ref), total,
            )

    workers = _resolve_workers(max_workers, max(1, total))
    findings: list[Finding] = []
    claims: list[NumericClaim] = []
    done = 0

    def _record_critique(res: Any, key: "tuple[str, int]") -> None:
        cached = bool(getattr(res, "cached", False))
        _record_usage(
            run_usage, family="critique",
            instance=f"critique:{key[0]}:p{key[1]}",
            model=model,
            transport="CACHE" if cached else "REAL_TIME",
            # A cache hit made no API call this run — zero billed tokens (as the
            # digest path does); the record still carries the cache-hit metadata.
            input_tokens=0 if cached else res.input_tokens,
            output_tokens=0 if cached else res.output_tokens,
            cache_hit=cached,
            parse_success=(getattr(res, "error", None) is None),
            terminal_status=(
                "COMPLETE" if getattr(res, "error", None) is None else "PARTIAL"
            ),
        )

    # Cached hits contribute findings/claims with no render and no token cost.
    for rk, res in cached_by_ref.items():
        findings.extend(res.findings)
        claims.extend(res.claims)
        _record_critique(res, rk)
        done += 1
        if progress is not None:
            progress(total, total, f"Critiquing sheet {done}/{total}")

    miss_total = total if only is None else len(only)
    if miss_total > 0:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            in_flight: dict = {}

            def _collect_one() -> None:
                nonlocal done
                finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for fut in finished:
                    ref = in_flight.pop(fut)
                    done += 1
                    try:
                        res = fut.result()
                    except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
                        _log.warning("critique failed for a sheet: %s", exc)
                        continue
                    if res.error:
                        _log.warning("critique degraded for a sheet: %s", res.error)
                    findings.extend(res.findings)
                    claims.extend(res.claims)
                    _record_critique(res, _refkey(ref))
                    # Store-under-both: promote a *complete* result to its level-1
                    # key so the next run skips rendering this sheet entirely. A
                    # partial (a dropped run) is never cached — mirrors the level-2
                    # guard inside critique_sheet_self_consistent.
                    key = level1_keys.get(_refkey(ref)) if cache is not None else None
                    if key is not None and res.error is None and res.runs == runs:
                        cache.put(key, critique_cache_entry_from_result(res))
                    if progress is not None:
                        progress(total, total, f"Critiquing sheet {done}/{total}")

            for rendered in iter_rendered_sheets(
                paths, rows=rows, cols=cols, overlap_frac=overlap_frac, only=only
            ):
                in_flight[executor.submit(
                    critique_sheet_self_consistent,
                    rendered, client=client, cache=cache, profiles=profiles,
                )] = rendered.ref
                while len(in_flight) >= workers:
                    _collect_one()
            while in_flight:
                _collect_one()

    findings.sort(key=lambda f: (source_page_key(f), f.id))
    _log.info(
        "critique: %d finding(s), %d numeric claim(s) across %d sheet(s)",
        len(findings), len(claims), total,
    )
    return findings, claims


def _run_qc_stages(
    *,
    sheets: list[SheetDigest],
    geometries: list[SheetGeometry],
    pdf_paths: list[Path],
    config: RunConfiguration,
    run_usage: RunUsage,
    client: Any,
    qc_work_dir: Path | None,
    progress: ProgressCallback | None,
    total: int,
    errors: list[str],
    critique_findings: list[Finding] | None = None,
    cross_findings: list[Finding] | None = None,
    claims: list[NumericClaim] | None = None,
    synthesis_text: str = "",
    accepted_documents: list | None = None,
) -> _QCResult:
    """Run the ledger pipeline: ingest → harvest → anchor → number → verify → markups.

    Part III (§16): every QC item from every channel is ingested into **the
    findings ledger** — the digest's JSON findings, the critique reads, the
    cross-sheet conflicts, the deterministic auditors, and the harvested prose
    (digest Coordination/Conflict items, synthesis conflicts, opted-in focus
    items). Ingest merges duplicates (unioning provenance); anchoring runs, then
    ``number()`` assigns the run's positional ``QC-###`` numbers; verification, the
    citation check, and the markup writer then consume the ledger and nothing else.
    At the end of a markup run every entry is accounted for — clouded, margin
    callout, or listed in the rejected index — and the tally is logged (§18).

    Which stages actually run is read entirely from the resolved
    :class:`RunConfiguration` (§15.1), so this one function serves every product
    mode: a **standard** run only ingests the digest findings and anchors them for
    free (DA-012); the **deterministic-audit-only** run adds the auditors but no
    model call, and in particular no prose structuring (DA-013); the **exhaustive**
    run turns on auditors, prose harvest, verification, citation, and markup.

    Every stage is additive and non-fatal (I-3): a failure is recorded in
    ``errors`` (and its typed :class:`StageResult`) and the standard deliverable
    still ships. Reviewed PDFs and evidence crops are written under ``work_dir`` (a
    fresh temp dir when none is given), to be exported later.
    """
    from .ledger import Ledger

    # Resolved switches — the body reads these, never the raw run kwargs (§15.1).
    reference_audit_enabled = config.run_auditors
    qc_markups = config.run_markup
    markup_verified_only = config.markup_verified_only
    verify_enabled = config.run_verification
    citation_check_enabled = config.run_citation
    ink_rejected = config.ink_rejected
    focus_findings_to_markups = config.focus_findings_to_markups
    run_prose_harvest = config.run_prose_harvest

    # Typed per-stage outcomes (§15.4) rolled up into the overall QC status.
    stage_results: list[StageResult] = []

    ledger = Ledger()
    work_dir = qc_work_dir
    audit_stats: dict = {}

    # --- ingest: every channel lands in the ledger ---------------------------
    digest_findings = [f for sd in sheets for f in getattr(sd, "findings", None) or []]
    ledger.add(digest_findings, "digest_json")

    # Critique findings already carry real per-read provenance (``critique_1`` /
    # ``critique_2``), stamped at production and unioned through the self-consistency
    # merge (Phase 22 §14.3) — the report's ``critique×N`` chip reads from it. The
    # old reconstruct-from-``reproduced`` heuristic is gone; a stray legacy finding
    # with no sources still falls back to a single-read tag.
    for f in critique_findings or []:
        if not f.sources:
            f.sources = ["critique_1"]
    ledger.add(critique_findings or [])
    ledger.add(cross_findings or [], "cross_qc")

    audit_stage = StageResult(stage="auditors", expected=reference_audit_enabled)
    if reference_audit_enabled and geometries:
        if progress is not None:
            progress(total, total, "Auditing references")
        try:
            from .auditors import run_auditors

            # The whole deterministic battery (Phase 14): references, arithmetic
            # (over the claims the critique / cross-QC transcribed), naming,
            # title-block, and sheet-index. All findings are DETERMINISTIC and
            # (where a quote exists) already anchored; each stamps its own
            # provenance tag at creation.
            audit_res = run_auditors(geometries, claims=claims or [])
            audit_stats = audit_res.stats
            ledger.add(audit_res.findings)
            audit_stage.status = "COMPLETE"
            audit_stage.items_out = len(audit_res.findings)
            _log.info(
                "auditors: %d deterministic finding(s); %s",
                len(audit_res.findings), audit_stats,
            )
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            errors.append(f"Deterministic auditors: {exc}")
            audit_stage.status = "FAILED"
            audit_stage.errors.append(str(exc))
            _log.warning("deterministic auditors failed: %s", exc)
    elif reference_audit_enabled:
        # Requested but no geometry to audit — a valid (empty) skip, not a failure.
        audit_stage.status = "SKIPPED_VALID"
    stage_results.append(audit_stage)

    # --- prose harvest (§17): the legacy channel's carry-through guarantee ----
    # Exhaustive QC only (§14.7 / §15.3): standard and audit-only runs keep any
    # unmatched prose in the prose and incur no straggler-structuring model call.
    harvest_stage = StageResult(stage="prose_harvest", expected=run_prose_harvest)
    if run_prose_harvest and sheets:
        if progress is not None:
            progress(total, total, "Harvesting prose findings")
        try:
            from .prose_harvest import harvest_prose

            from .prose_harvest import harvest_model

            hres = harvest_prose(
                ledger, sheets, geometries, client=client,
                synthesis_text=synthesis_text,
                focus_findings_to_markups=focus_findings_to_markups,
            )
            # The straggler-structuring call's usage — an independent record, never
            # folded into (and overwritten by) the verification counters (§15.6).
            _record_usage(
                run_usage, family="harvest", instance="prose_harvest",
                model=harvest_model(),
                input_tokens=hres.input_tokens, output_tokens=hres.output_tokens,
                terminal_status="PARTIAL" if hres.missing else "COMPLETE",
            )
            harvest_stage.items_in = getattr(hres, "items", 0)
            # §14.9: every enumerated prose item must reach a ledger entry. Any that
            # could not be recovered even by the final degraded attempt is an
            # invariant failure — surface it so the run is never presented as a
            # complete carry-through.
            if hres.missing:
                errors.append(
                    f"Prose harvest: {hres.missing} enumerated prose item(s) could not "
                    "be accounted for in the ledger — exhaustive QC is incomplete."
                )
                harvest_stage.status = "PARTIAL"
                harvest_stage.errors.append(f"{hres.missing} prose item(s) unaccounted")
                _log.error("prose harvest: %d item(s) unaccounted (§14.9)", hres.missing)
            elif harvest_stage.items_in == 0:
                # No enumerated prose to carry through — an applicable, valid skip.
                harvest_stage.status = "SKIPPED_VALID"
            else:
                harvest_stage.status = "COMPLETE"
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            errors.append(f"Prose harvest: {exc}")
            harvest_stage.status = "FAILED"
            harvest_stage.errors.append(str(exc))
            _log.warning("prose harvest failed: %s", exc)
    stage_results.append(harvest_stage)

    # --- seal ingestion, then anchor, reconcile, and number (§12.4) -----------
    # QC ids must be POSITIONAL, so numbering happens *after* anchoring — the
    # freeze-before-anchor ordering is gone (Phase 20). Seal first (no more
    # entries), anchor every primary + leg, fold any duplicate the ingest pass
    # could not see without geometry, and only then assign QC-### in visual order.
    entries = ledger.seal()

    # Anchor the entries that don't already carry a rectangle (auditor entries do).
    # The WHOLE block is wrapped (not just the per-sheet resolves): a throw in the
    # setup (imports, key-building) must not skip numbering below and ship entries
    # with empty QC ids — pre-Phase-20 freeze() ran before anchoring, so numbering
    # always survived; number() now runs after, so anchoring must stay non-fatal (I-3).
    if entries and geometries:
        if progress is not None:
            progress(total, total, "Anchoring findings")
        try:
            from .anchor import resolve_anchors, resolve_conflict_legs

            geom_by_key = {source_page_key(g.ref): g for g in geometries}
            by_sheet: dict[tuple, list[Finding]] = {}
            for finding in entries:
                by_sheet.setdefault(source_page_key(finding), []).append(finding)
            for key, sheet_findings in by_sheet.items():
                geometry = geom_by_key.get(key)
                if geometry is None:
                    continue
                try:
                    resolve_anchors(sheet_findings, geometry)
                except Exception as exc:  # noqa: BLE001 - never fatal
                    _log.warning("anchoring failed for %s: %s", key, exc)
            # Anchor the cross-sheet findings' also_on legs, each on its own sheet.
            resolve_conflict_legs(entries, geom_by_key)
        except Exception as exc:  # noqa: BLE001 - anchoring must never sink numbering
            _log.warning("anchoring stage failed: %s", exc)

    # Cautious post-anchor reconciliation (Pass B, §12.1): geometry is now available.
    try:
        from .ledger import reconcile_post_anchor

        reconcile_post_anchor(ledger)
    except Exception as exc:  # noqa: BLE001 - reconciliation must never sink the run
        _log.warning("post-anchor reconciliation failed: %s", exc)

    # Assign the run's positional QC-### numbers now that anchors exist (§12.4).
    entries = ledger.number()
    if ledger.post_seal_adds:
        # An entry landed after the seal — an orchestration invariant failure. The
        # entries still ship (I-3), but the run is flagged incomplete rather than
        # presented as ordinary, fully-numbered output (§12.3).
        errors.append(
            f"Ledger: {ledger.post_seal_adds} finding(s) ingested after seal — "
            "exhaustive QC is incomplete (a stage produced findings too late)."
        )

    all_findings = entries

    # Verify the model entries (deterministic auditor entries are skipped by the
    # verifier). Only when markups are requested — clouds are what demand trust.
    verify_stage = StageResult(
        stage="verification", expected=bool(qc_markups and verify_enabled)
    )
    if qc_markups and verify_enabled and entries:
        from .verify import default_verify_model
        from .verify import verify_findings as _run_verify

        verify_model = default_verify_model()

        if work_dir is None:
            import tempfile

            work_dir = Path(tempfile.mkdtemp(prefix="drawing_qc_"))
        evidence_dir = work_dir / "evidence"

        def _verify_progress(done: int, tot: int, label: str) -> None:
            if progress is not None:
                progress(total, total, label)   # keep the sheet bar full; label = "Verifying finding k/n"

        vres = None
        cres = None
        primary_failed = False
        cross_failed = False
        try:
            vres = _run_verify(
                all_findings, geometries, client=client,
                evidence_dir=evidence_dir, progress=_verify_progress,
            )
            _record_usage(
                run_usage, family="verify", instance="verify",
                model=verify_model,
                input_tokens=vres.input_tokens, output_tokens=vres.output_tokens,
            )
            _log.info(
                "verification: %d verified, %d rejected, %d uncertain, %d skipped",
                vres.verified, vres.rejected, vres.uncertain, vres.skipped,
            )
        except Exception as exc:  # noqa: BLE001 - never fatal
            errors.append(f"Verification: {exc}")
            primary_failed = True
            verify_stage.errors.append(str(exc))
            _log.warning("verification failed: %s", exc)

        # Cross-sheet (dual-anchored) findings verify with one crop per leg in a
        # single call, so the verifier can actually compare the sheets and reach
        # VERIFIED/REJECTED (the single-crop pass above skips them — a cross-sheet
        # claim can't be judged from one crop). Additive and non-fatal.
        try:
            from .verify import verify_cross_findings

            cres = verify_cross_findings(
                all_findings, geometries, client=client,
                evidence_dir=evidence_dir, progress=_verify_progress,
            )
            _record_usage(
                run_usage, family="verify", instance="verify_cross",
                model=verify_model, parent="verify",
                input_tokens=cres.input_tokens, output_tokens=cres.output_tokens,
            )
            if cres.verified or cres.rejected or cres.uncertain or cres.skipped:
                _log.info(
                    "cross-verification: %d verified, %d rejected, %d uncertain, %d skipped",
                    cres.verified, cres.rejected, cres.uncertain, cres.skipped,
                )
        except Exception as exc:  # noqa: BLE001 - never fatal
            errors.append(f"Cross-sheet verification: {exc}")
            cross_failed = True
            verify_stage.errors.append(str(exc))
            _log.warning("cross-sheet verification failed: %s", exc)

        # The verifier returns *normally* with everything SKIPPED when the client is
        # unavailable or no crop could be built — it does not raise. So the stage
        # status is derived from the actual verdicts, not merely from "no exception":
        # findings actually judged (VERIFIED/REJECTED/UNCERTAIN) make it COMPLETE;
        # eligible findings that were *all* skipped make it PARTIAL (verification was
        # required but could not run); zero eligible/counted findings is a valid skip.
        def _counts(r: "Any") -> "tuple[int, int]":
            if r is None:
                return 0, 0
            judged = r.verified + r.rejected + r.uncertain
            return judged, judged + r.skipped
        p_judged, p_counted = _counts(vres)
        c_judged, c_counted = _counts(cres)
        judged, counted = p_judged + c_judged, p_counted + c_counted
        verify_stage.items_out = judged
        if primary_failed:
            verify_stage.status = "FAILED"
        elif counted == 0:
            verify_stage.status = "SKIPPED_VALID"   # no eligible model findings
        elif judged == 0:
            # Eligible findings existed but every one was skipped (client down /
            # crops failed) — the required stage did not actually verify anything.
            verify_stage.status = "PARTIAL"
            verify_stage.warnings.append(
                "all eligible findings were skipped (client unavailable or crops failed)"
            )
        elif cross_failed:
            verify_stage.status = "PARTIAL"
        else:
            verify_stage.status = "COMPLETE"
    elif qc_markups and verify_enabled:
        # Requested, but no model entries were eligible to verify (§3.3).
        verify_stage.status = "SKIPPED_VALID"
    stage_results.append(verify_stage)

    # Citation check (Phase 15): one web-search-backed call per unique code ref,
    # judged against the editions the set adopts (harvested from the text
    # layers). Verdicts attach to the findings and ride the popup/CSV/report; a
    # MISMATCH downgrades nothing. Additive and non-fatal (I-3).
    citation_stage = StageResult(stage="citation", expected=citation_check_enabled)
    if citation_check_enabled:
        if not any(getattr(f, "refs", None) for f in all_findings):
            # No cited claims to check — a valid skip, not a failure (§3.3).
            citation_stage.status = "SKIPPED_VALID"
        else:
            from .citation_check import check_citations, citation_model

            def _citation_progress(done: int, tot: int, label: str) -> None:
                if progress is not None:
                    progress(total, total, label)

            try:
                cires = check_citations(
                    all_findings, geometries, client=client, progress=_citation_progress,
                )
                # Best-effort web-search fee: the citation stage does not yet surface
                # the exact server ``web_search_requests`` count, so bill one search
                # per unique citation checked (a lower bound — each ref runs ≥1
                # search). Tokens are exact; the search micro-fee is approximate.
                _record_usage(
                    run_usage, family="citation", instance="citation",
                    model=citation_model(),
                    input_tokens=cires.input_tokens, output_tokens=cires.output_tokens,
                    billable_tool_uses={"web_search": int(getattr(cires, "checked", 0) or 0)},
                    terminal_status="PARTIAL" if cires.error else "COMPLETE",
                )
                if cires.error:
                    errors.append(f"Citation check: {cires.error}")
                    citation_stage.status = "PARTIAL"
                    citation_stage.errors.append(str(cires.error))
                else:
                    citation_stage.status = "COMPLETE"
            except Exception as exc:  # noqa: BLE001 - never fatal
                errors.append(f"Citation check: {exc}")
                citation_stage.status = "FAILED"
                citation_stage.errors.append(str(exc))
                _log.warning("citation check failed: %s", exc)
    stage_results.append(citation_stage)

    reviewed_pdf_paths: list[Path] = []
    mutated_sources: list[str] = []
    mutated_ids: set[str] = set()
    ledger_tally: dict[str, int] = {}
    coverage_status = "NOT_REQUESTED"
    markup_run: Any = None
    if qc_markups:
        from .annotate import (
            _is_set_level_finding,
            _result_from_receipts,
            new_artifact_run_id,
            write_reviewed_pdfs,
            write_set_review_notes_pdf,
        )
        from .source_registry import detect_mutations

        # §10.6: re-verify each source hasn't changed since the inventory
        # snapshot before we reopen it to write ink. A source whose bytes
        # changed is passed to the writer as a *skipped* source: its findings'
        # placements get FAILED receipts (source changed) instead of stale ink,
        # and the change is recorded so the operator re-runs. The standard
        # artifacts already produced (findings, exports) are retained.
        if accepted_documents:
            mutated = detect_mutations(accepted_documents)
            if mutated:
                mutated_ids = set(mutated)
                by_id = {d.source_id: d for d in accepted_documents}
                for sid, reason in mutated.items():
                    name = by_id[sid].display_name
                    mutated_sources.append(name)
                    errors.append(
                        f"{name}: {reason} — reviewed markup was skipped for it; "
                        "re-run to mark up the current revision."
                    )
                    _log.warning("source mutated mid-run: %s (%s)", name, reason)

        if work_dir is None:
            import tempfile

            work_dir = Path(tempfile.mkdtemp(prefix="drawing_qc_"))
        if progress is not None:
            progress(total, total, "Writing markups")
        try:
            # Set-level findings (a synthesis conflict naming no in-set sheet, §14.8)
            # belong to no source PDF — route them to the dedicated
            # Drawing_Set_Review_Notes.pdf, and everything else to the per-source
            # reviewed PDFs. One shared artifact run id ties both to this run.
            artifact_run_id = new_artifact_run_id()
            source_findings = [f for f in all_findings if not _is_set_level_finding(f)]
            set_level_findings = [f for f in all_findings if _is_set_level_finding(f)]

            # Artifact-backed markup (Phase 21, DA-007): every planned placement —
            # each finding and each cross-sheet leg — is written, stamped, and
            # reconciled against the reopened PDF, so the tally and coverage below
            # come from proven receipts, never from an intention classifier.
            markup_run = write_reviewed_pdfs(
                source_findings, pdf_paths, work_dir,
                include_unverified=not markup_verified_only,
                ink_rejected=ink_rejected,
                geometries=geometries,
                audit_stats=audit_stats,
                include_appendix=_markup_appendix_enabled(),
                skip_source_ids=mutated_ids,
                artifact_run_id=artifact_run_id,
            )
            # Commit the per-source result *before* the set-level writer runs, so a
            # failure inside the notes writer can never discard the reviewed PDFs
            # already written to disk (they stay listed; coverage just rolls to
            # INCOMPLETE). Only the set-notes call + merge is separately guarded.
            reviewed_pdf_paths = list(markup_run.reviewed_pdfs)
            ledger_tally = dict(markup_run.tally)
            coverage_status = markup_run.coverage_status
            # The set-level review-notes artifact — its own receipts, folded into the
            # one MarkupRunResult so coverage/tally cover the whole run (§14.8).
            # NB: the ``markup_verified_only`` gate is deliberately NOT applied here.
            # That gate suppresses unverified *ink on the drawings*; a set-level
            # synthesis conflict has no sheet to cloud and cannot be crop-verified, so
            # Drawing_Set_Review_Notes.pdf IS its index entry (a review-notes artifact,
            # not authoritative drawing ink). Gating it would hide the very conflicts
            # the notes exist to surface, so a verified-only run still lists them.
            if set_level_findings:
                try:
                    set_run = write_set_review_notes_pdf(
                        set_level_findings, work_dir, artifact_run_id=artifact_run_id,
                    )
                    markup_run = _result_from_receipts(
                        markup_run.receipts + set_run.receipts,
                        markup_run.placements + set_run.placements,
                        markup_run.reviewed_pdfs + set_run.reviewed_pdfs,
                    )
                    reviewed_pdf_paths = list(markup_run.reviewed_pdfs)
                    ledger_tally = dict(markup_run.tally)
                    coverage_status = markup_run.coverage_status
                except Exception as exc:  # noqa: BLE001 - never drop the source PDFs
                    errors.append(f"Set-level review notes: {exc}")
                    _log.warning("set-level notes writing failed: %s", exc)
                    coverage_status = "INCOMPLETE"   # notes failed → incomplete, source kept
            _log.info(
                "markups: %d reviewed PDF(s) written, coverage %s",
                len(reviewed_pdf_paths), coverage_status,
            )
        except Exception as exc:  # noqa: BLE001 - never fatal
            errors.append(f"Markup writing: {exc}")
            _log.warning("markup writing failed: %s", exc)
            coverage_status = "INCOMPLETE"

        # A mutated source means QC is incomplete (§10.6) even when that source
        # produced no findings — it contributes no FAILED receipt in that case, so
        # force INCOMPLETE here rather than rely on receipts alone. A post-seal add
        # (an orchestration invariant failure, §12.3) likewise marks the run
        # incomplete; reflect both in coverage so the report/GUI never present such
        # a run as fully successful.
        if mutated_ids or ledger.post_seal_adds:
            coverage_status = "INCOMPLETE"
        if coverage_status == "INCOMPLETE":
            failed = ledger_tally.get("failed", 0)
            _log.warning(
                "markup coverage INCOMPLETE: %d failed, %d skipped (source changed)",
                failed, ledger_tally.get("mutated", 0),
            )
        _log.info("%s", _tally_line(len(entries), ledger_tally, coverage_status))

    # Markup/coverage as a typed stage: COMPLETE only when every planned placement
    # was proven in the reopened PDF (receipt-derived, DA-007); an INCOMPLETE
    # coverage (a failed write, a mutated source, a post-seal add) is PARTIAL.
    markup_stage = StageResult(stage="markup", expected=qc_markups)
    if qc_markups:
        if coverage_status == "COMPLETE":
            markup_stage.status = "COMPLETE"
        else:
            markup_stage.status = "PARTIAL"
            markup_stage.errors.append(f"coverage {coverage_status}")
    stage_results.append(markup_stage)

    # The context's two buckets are a *view* of the one ledger: entries produced
    # only by the deterministic auditors keep their historical
    # ``reference_findings`` home; everything else (model, prose, merged) is
    # ``findings``. Concatenated they are exactly ``ledger.entries`` — every
    # consumer downstream reads the ledger and nothing else (§16).
    reference_findings = [
        e for e in entries
        if e.sources and all(s.startswith("auditor_") for s in e.sources)
    ]
    _ref_ids = {id(e) for e in reference_findings}
    findings = [e for e in entries if id(e) not in _ref_ids]

    return _QCResult(
        findings=findings,
        reference_findings=reference_findings,
        reviewed_pdf_paths=reviewed_pdf_paths,
        work_dir=work_dir,
        # QC-stage usage is recorded directly on the shared ``run_usage`` ledger now,
        # so the aggregate token fields are unused (kept at 0 for back-compat).
        audit_stats=audit_stats,
        ledger_tally=ledger_tally,
        mutated_sources=mutated_sources,
        coverage_status=coverage_status,
        markup_run=markup_run,
        stage_results=stage_results,
    )


def _tally_line(
    total_entries: int, tally: dict[str, int], coverage_status: str = ""
) -> str:
    """The Phase 21 run-summary line, derived from receipts.

    e.g. ``Ledger 47: 39 clouded, 5 margin, 2 rejected (indexed), 1 gated
    (verified-only mode), 0 failed; coverage COMPLETE``. The core three buckets
    are always shown; the optional gated / failed / skipped buckets appear when
    non-zero, and the coverage verdict is appended when known.
    """
    parts = [f"{tally.get('cloud', 0)} clouded", f"{tally.get('margin', 0)} margin"]
    parts.append(f"{tally.get('rejected', 0)} rejected (indexed)")
    if tally.get("gated"):
        parts.append(f"{tally['gated']} gated (verified-only mode)")
    if tally.get("failed"):
        parts.append(f"{tally['failed']} failed")
    if tally.get("mutated"):
        parts.append(f"{tally['mutated']} skipped (source changed)")
    line = f"Ledger {total_entries}: " + ", ".join(parts)
    if coverage_status in ("COMPLETE", "INCOMPLETE"):
        line += f"; coverage {coverage_status}"
    return line


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
    synthesize: bool | None = None,
    synthesis_model: str | None = None,
    use_batch: bool = False,
    on_log: LogCallback | None = None,
    on_status: StatusCallback | None = None,
    focus: str | None = None,
    focus_model: str | None = None,
    reference_audit: bool = False,
    qc_markups: bool = False,
    markup_verified_only: bool = False,
    verify_findings: bool | None = None,
    critique: bool | None = None,
    profiles: list | None = None,
    cross_qc: bool | None = None,
    citation_check: bool | None = None,
    ink_rejected: bool = False,
    focus_findings_to_markups: bool = False,
    qc_work_dir: Path | None = None,
    confirm_large_set: bool = False,
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

    ``cross_qc=True`` (Phase 13) adds a **cross-sheet QC pass**: one text-only
    reasoning call over all the digests + text layers (no images) that hunts
    conflicts *between* sheets — the same tag valued two ways, twin notes diverged,
    a note contradicted elsewhere, a reference whose target disclaims what the
    pointer claims. Its findings carry **dual anchors** (``also_on`` legs), so the
    markup writer clouds **both** sheets of a conflict, each popup cross-referencing
    the other. Distinct from the prose ``synthesize`` (which is untouched); additive
    and non-fatal, and — like the critique — the prose ``combined_text`` never sees
    it (I-2). Large sets shard by discipline.

    ``citation_check=True`` (Phase 15) adds a **citation check**: one web-search-
    backed call per unique code ref the findings cite, judged against the editions
    the set adopts (harvested from the general-notes text) and the current
    edition. The verdict (``CHECKED_SUPPORTS`` / ``CHECKED_MISMATCH`` /
    ``UNCHECKED``) attaches to each citing finding and appears in the markup
    popup, the CSV, and the report; a MISMATCH downgrades nothing automatically —
    sometimes the stale citation *is* the finding. Real-time only; additive and
    non-fatal.

    **Part III — the findings ledger and the gating amendment (§16–18).** When
    any QC stage runs, every QC item from every channel is ingested into one
    per-run ledger (the digest's JSON findings, its harvested prose
    Coordination/Conflict items, the critique reads, cross-sheet conflicts, the
    deterministic auditors, harvested synthesis conflicts, and — behind
    ``focus_findings_to_markups`` — the per-sheet Focus sections). Duplicates
    merge with unioned provenance (``Finding.sources``); the exhaustive default
    inks **everything except REJECTED**: anchored entries cloud (UNCERTAIN
    dashed), rect-less entries become margin callouts (``[SHEET]`` /
    ``[UNANCHORED]`` prefixes), and REJECTED entries are listed on the index
    page's "Rejected by verification" section (inked grey only with
    ``ink_rejected=True``). ``markup_verified_only=True`` is the conservative
    opt-in that restricts ink to VERIFIED + DETERMINISTIC (it now defaults
    **off** — §18 supersedes the old default). The run-end coverage tally lands
    on ``ctx.ledger_tally`` / ``ctx.ledger_tally_line`` (markup runs only —
    without ``qc_markups`` there is no PDF ink to account for).
    """
    if cache is None and use_cache:
        from .digest_cache import get_default_digest_cache

        cache = get_default_digest_cache()

    focus = normalize_focus(focus) or ""

    # Normalize the run options into one immutable configuration (§15.1): the
    # single place ``qc_markups=True`` becomes the exhaustive stack, ``reference_audit``
    # (alone) becomes the free offline battery, and a per-stage ``bool | None`` flag
    # is resolved to a product default (None) or honored as an explicit expert
    # override (True/False). Every stage below reads ``config``; the raw kwargs are
    # not consulted again, so the meaning cannot drift across call sites.
    config = resolve_run_configuration(
        qc_markups=qc_markups,
        reference_audit=reference_audit,
        synthesize=synthesize,
        critique=critique,
        cross_qc=cross_qc,
        citation_check=citation_check,
        verify_findings=verify_findings,
        markup_verified_only=markup_verified_only,
        ink_rejected=ink_rejected,
        focus_findings_to_markups=focus_findings_to_markups,
        use_batch=use_batch,
    )

    # Inventory (Phase 18B): classify every selected input once, so a corrupt /
    # encrypted / zero-page / duplicate file degrades individually and *visibly*
    # instead of vanishing. Downstream stages process only accepted documents.
    all_paths = [Path(p) for p in pdf_paths]
    inventory = inspect_inputs(all_paths)
    inventory_errors = inventory.error_lines()
    for line in inventory_errors:
        _log.info("input inventory: %s", line)

    # Preflight (§10.7, DA-035): a large legitimate set requires explicit
    # confirmation rather than being silently truncated; a QC run that would
    # write evidence crops / reviewed PDFs into ``qc_work_dir`` is blocked early
    # if that location lacks room, rather than failing late after paid API work.
    # A pathological file was already rejected by the inventory.
    block_reason = check_set_limits(
        inventory.accepted_documents, confirmed=confirm_large_set
    )
    if block_reason is None and qc_work_dir is not None:
        est_sheets = sum(d.page_count for d in inventory.accepted_documents)
        block_reason = check_work_disk(
            est_sheets * EST_BYTES_PER_SHEET, qc_work_dir
        )
    if block_reason is not None:
        if progress is not None:
            progress(0, 0, "Cannot start run")
        return DrawingContext(
            combined_text="",
            file_count=len(all_paths),
            sheet_count=0,
            errors=inventory_errors + [block_reason],
        )

    paths = inventory.accepted_paths
    refs = list_sheets(paths)
    total = len(refs)
    file_count = len(inventory.accepted_documents)

    # The inventory already hashed every accepted source once (§10.1); the prescan
    # reuses that for the level-1 render identity (DA-004) via a stat fast-gate, and
    # re-hashes only a source whose bytes drifted since — so a file rewritten between
    # the inventory and the prescan keys on its *current* revision, never a stale
    # hit (§10.6). ``str(path) -> (content_sha256, byte_size, mtime_ns)``.
    snapshot_by_path = {
        str(d.pdf_path): (d.content_sha256, d.byte_size, d.initial_mtime_ns)
        for d in inventory.accepted_documents
        if d.content_sha256
    }

    # Page-level render failures (§10.5) are recorded and the page is excluded,
    # but the rest of the set still processes — never a whole-run abort.
    page_error_lines: list[str] = []

    def _on_page_error(ref: Any, exc: Exception) -> None:
        page_error_lines.append(
            f"{ref.display_label}: page could not be rendered ({type(exc).__name__})"
        )

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
            file_count=len(all_paths),
            sheet_count=0,
            errors=inventory_errors
            + ["No readable PDF pages found in the selected files."],
        )

    # Capture each sheet's lightweight text/geometry record (words + text layer,
    # **no PNG bytes**) as it renders — the batch path discards the rendered sheet
    # after upload, so this is the only place the per-sheet geometry survives.
    # DA-012 (§15.2): this is captured on *every* run, not just QC ones — a
    # standard run retains its sheet text and anchors its digest findings offline
    # for free, and exports ``findings.json`` / ``findings.csv`` / ``sheet_text/``.
    need_geometry = True
    sheet_geometries: list[SheetGeometry] = []
    geometry_sink = sheet_geometries

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
            effort=effort, focus=focus or None, snapshot_by_path=snapshot_by_path,
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
                on_page_error=_on_page_error,
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

    # Seed the run errors with the inventory rejections and any page-level
    # render failures (§10.5 / §10.7) so a partial run explains what it dropped.
    errors: list[str] = list(inventory_errors) + list(page_error_lines)
    # Typed per-stage outcomes for the pre-ledger stages (synthesis, critique,
    # cross-QC); the ledger stages append theirs inside ``_run_qc_stages`` (§15.4).
    stage_results: list[StageResult] = []
    # Append-only usage ledger (§15.6): every API call/attempt below appends a
    # priced record; the run's token/cost totals are *derived* sums over it, so no
    # stage can overwrite another's counters. ``img_tok`` is a separate informational
    # estimate of the image portion (already folded into each digest's input tokens).
    run_usage = RunUsage()
    img_tok = 0
    digest_transport = "BATCH" if use_batch else "REAL_TIME"
    for sd in sheets:
        # A cached sheet made no API call, so it costs zero tokens *this run* — its
        # record carries the cache-hit metadata but zero billed tokens. A fresh
        # digest records its actual reported usage (billable even if it errored).
        cached = bool(getattr(sd, "cached", False))
        if not cached:
            img_tok += sd.image_token_estimate
        _record_usage(
            run_usage, family="digest",
            instance=f"digest:{_refkey(sd.ref)[0]}:p{_refkey(sd.ref)[1]}",
            model=model,
            transport="CACHE" if cached else digest_transport,
            input_tokens=0 if cached else sd.input_tokens,
            output_tokens=0 if cached else sd.output_tokens,
            cache_hit=cached,
            parse_success=(sd.error is None),
            terminal_status="FAILED" if sd.error else "COMPLETE",
        )
        if sd.error:
            errors.append(f"{sd.ref.display_label}: {sd.error}")

    # Critique pass (Phase 11): a second, adversarial full-coverage read per sheet
    # whose only job is finding problems, run self-consistently (twice) and merged.
    # Additive and non-fatal; its findings pool with the digest findings in the QC
    # stage below. Re-renders each sheet (the digest images are gone by now), so
    # it runs before the QC stages that consume the pooled findings.
    critique_findings: list[Finding] = []
    # Numeric claims (Phase 14) transcribed by the critique / cross-sheet QC passes,
    # pooled and handed to the deterministic arithmetic auditor below.
    numeric_claims: list[NumericClaim] = []
    critique_stage = StageResult(stage="critique", expected=config.run_critique)
    if config.run_critique:
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
            critique_findings, c_claims = _run_critique_stage(
                paths, rows=rows, cols=cols, overlap_frac=overlap_frac,
                client=client, cache=cache, progress=progress, total=total,
                max_workers=max_workers, run_usage=run_usage,
                profiles=resolved_profiles, snapshot_by_path=snapshot_by_path,
            )
            numeric_claims.extend(c_claims)
            critique_stage.status = "COMPLETE"
            critique_stage.items_out = len(critique_findings)
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            errors.append(f"Critique: {exc}")
            critique_stage.status = "FAILED"
            critique_stage.errors.append(str(exc))
            _log.warning("critique stage failed: %s", exc)
    stage_results.append(critique_stage)

    # Cross-sheet QC pass (Phase 13): a deliberate whole-set conflict hunt over the
    # digests + text layers (text only), producing dual-anchored findings that
    # cloud both sheets. Distinct from the prose synthesis (which stays as-is).
    # Additive and non-fatal.
    cross_findings: list[Finding] = []
    cross_stage = StageResult(stage="cross_qc", expected=config.run_cross_qc)
    if config.run_cross_qc:
        if progress is not None:
            progress(total, total, "Cross-sheet QC")
        try:
            from .cross_qc import cross_qc_model, cross_sheet_qc

            cross_res = cross_sheet_qc(sheets, sheet_geometries, client=client)
            cross_findings = cross_res.findings
            numeric_claims.extend(cross_res.claims)
            _record_usage(
                run_usage, family="cross_qc", instance="cross_qc",
                model=cross_qc_model(),
                input_tokens=cross_res.input_tokens, output_tokens=cross_res.output_tokens,
                terminal_status="PARTIAL" if cross_res.error else "COMPLETE",
            )
            cross_stage.items_out = len(cross_findings)
            if cross_res.error:
                errors.append(f"Cross-sheet QC: {cross_res.error}")
                cross_stage.status = "PARTIAL"
                cross_stage.errors.append(str(cross_res.error))
                _log.warning("cross-sheet QC: %s", cross_res.error)
            else:
                cross_stage.status = "COMPLETE"
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            errors.append(f"Cross-sheet QC: {exc}")
            cross_stage.status = "FAILED"
            cross_stage.errors.append(str(exc))
            _log.warning("cross-sheet QC stage failed: %s", exc)
    stage_results.append(cross_stage)

    # Cross-sheet synthesis (one text-only call after all digests). Skipped for
    # <2 readable sheets; on failure we keep the per-sheet digests and record
    # the error rather than losing the whole run. Runs BEFORE the QC stages
    # (Part III): the prose harvester mirrors the synthesis's conflict
    # statements into the findings ledger, so the text must exist by then — the
    # prose itself is untouched either way (I-2).
    synthesis_text = ""
    synthesis_stage = StageResult(stage="synthesis", expected=config.run_synthesis)
    if config.run_synthesis:
        if progress is not None:
            progress(total, total, "Synthesizing set overview")
        from .synthesis import (
            MIN_SHEETS_FOR_SYNTHESIS,
            default_synthesis_model,
            synthesize_drawing_set,
        )

        _log.info("synthesis: starting cross-sheet overview")
        result = synthesize_drawing_set(sheets, client=client, model=synthesis_model)
        if result.ok:
            synthesis_text = result.text
            synthesis_stage.status = "COMPLETE"
            # The synthesis call is billed, so its usage is recorded (§15.6).
            _record_usage(
                run_usage, family="synthesis", instance="synthesis",
                model=synthesis_model or default_synthesis_model(),
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            )
            _log.info(
                "synthesis: ok (input=%d output=%d tok)",
                result.input_tokens, result.output_tokens,
            )
        elif result.error and len([s for s in sheets if s.ok]) >= MIN_SHEETS_FOR_SYNTHESIS:
            # A genuine failure (not the "too few sheets" skip) is worth surfacing.
            errors.append(f"Cross-sheet synthesis: {result.error}")
            synthesis_stage.status = "FAILED"
            synthesis_stage.errors.append(str(result.error))
            _log.warning("synthesis: failed: %s", result.error)
        else:
            # Fewer than two readable sheets — an applicable, valid skip (§3.3).
            synthesis_stage.status = "SKIPPED_VALID"
            _log.info("synthesis: skipped (<%d readable sheet(s))", MIN_SHEETS_FOR_SYNTHESIS)
    stage_results.append(synthesis_stage)

    # Set-level focus report (one text-only call; independent of synthesis).
    # Additive: a failure here is recorded and the standard deliverable —
    # per-sheet digests plus any synthesis — ships exactly as it would have.
    focus_report_text = ""
    if focus:
        if progress is not None:
            progress(total, total, "Generating focus report")
        from .focus import (
            MIN_SHEETS_FOR_FOCUS,
            default_focus_model,
            generate_focus_report,
        )

        _log.info("focus report: starting set-level pass")
        fresult = generate_focus_report(
            sheets, focus, client=client, model=focus_model
        )
        if fresult.ok:
            focus_report_text = fresult.text
            # The focus call is billed, so its usage is recorded (§15.6).
            _record_usage(
                run_usage, family="focus", instance="focus",
                model=focus_model or default_focus_model(),
                input_tokens=fresult.input_tokens, output_tokens=fresult.output_tokens,
            )
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

    # Ledger pipeline (Part III): ingest every channel into the findings ledger,
    # harvest the prose (exhaustive only), anchor, number, then verify → citation
    # → markups — all consuming the ledger and nothing else. Runs on *every* mode
    # (§15.2): a standard run only ingests + anchors the digest findings for free;
    # what else runs is read from ``config``. Additive and non-fatal; the prose
    # deliverables above are never modified (I-2).
    qc = _run_qc_stages(
        sheets=sheets, geometries=sheet_geometries, pdf_paths=paths,
        config=config, run_usage=run_usage,
        client=client, qc_work_dir=qc_work_dir, progress=progress,
        total=total, errors=errors, critique_findings=critique_findings,
        cross_findings=cross_findings, claims=numeric_claims,
        synthesis_text=synthesis_text,
        accepted_documents=inventory.accepted_documents,
    )
    stage_results.extend(qc.stage_results)

    # Roll the per-stage outcomes into one overall QC status (§3.3). The temporary
    # completeness gate keeps an exhaustive run at PARTIAL until Phases 24–26 land.
    qc_status = roll_up_qc_status(
        config, stage_results, qc.coverage_status,
        completeness_gate_open=EXHAUSTIVE_QC_COMPLETENESS_GATE_OPEN,
    )

    if progress is not None:
        progress(total, total, "Done")

    # Run token totals are derived from the append-only usage ledger (§15.6).
    in_tok = run_usage.total_input_tokens
    out_tok = run_usage.total_output_tokens
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
        audit_stats=qc.audit_stats,
        ledger_tally=qc.ledger_tally,
        mutated_sources=qc.mutated_sources,
        coverage_status=qc.coverage_status,
        markup_run=qc.markup_run,
        run_configuration=config,
        stage_results=stage_results,
        qc_status=qc_status,
        run_usage=run_usage,
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
