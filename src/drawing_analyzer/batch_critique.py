"""Message-Batches transport for the critique pass (Phase 23C, §15.8 / DA-030).

The digest already rides the Message Batches + Files APIs for a ~50% discount
(:mod:`drawing_analyzer.batch_digest`). Until this module, the **critique** — a
second, adversarial full-coverage read run *twice* per sheet for self-consistency
— ran real-time, re-rendering every sheet and inlining its ~37 images as base64
*for each of the two reads*. That made the exhaustive QC pass the dominant cost
and left the documented "roughly half via Batches" economics untrue for the
reviewer.

This module fixes both halves for a ``use_batch`` run:

* **One upload per sheet feeds both reads.** Each uncached sheet's overview +
  tiles are uploaded to the Files API exactly once
  (:func:`~drawing_analyzer.file_upload.upload_sheet_images`); both
  self-consistency reads become batch items that reference the *same*
  ``file_id`` set (distinct ``custom_id``s ``sheet__{i}__r1`` / ``…__r2``), so the
  imagery is neither re-rendered per read nor re-uploaded. That is the DA-030
  "image reuse" — within the critique stage.

* **The two reads ride one Message Batch** at the batch rate, so the pipeline
  prices them ``BATCH`` (a rescued real-time fallback stays ``REAL_TIME``).

* **Files are released on every exit** — a fully-collected batch, a confirmed
  cancel, or an unexpected collection error (best-effort cancel, then release).
  A non-terminal batch this run could not cancel keeps its files (it may still be
  running; they expire server-side). That is the DA-034 finally-path guarantee.

Scope note (Phase 23C, Option A): the critique batch reuses uploads **within**
the critique stage, not **across** the digest and critique stages — a sheet is
still rendered and uploaded once for the digest batch and once for the critique
batch. Sharing one upload manifest across both stages (§15.8's ideal) is a
deliberately deferred follow-up; it would restructure the digest→critique stage
sequencing and the two independent cache partitions, and is out of this PR's
scope. The batch discount and within-stage reuse land here; the cross-stage
render/upload dedup does not.

Additive & non-fatal (I-3): the critique is optional QC, so — unlike the digest,
whose loss zeroes a run and which therefore carries an elaborate follow-up-batch
+ direct-call rescue — this collector keeps things simple. A per-read failure
just fails that read (the surviving read still merges, honestly marked
``NOT_ASSESSED_PARTIAL``); a batch that never terminates degrades the affected
sheets' critique to an empty result with a clear error. The standard digest
deliverable and the digest's own findings are never touched.

Isolation (I-5): imports no PDF engine; consumes already-rendered
:class:`~drawing_analyzer.models.RenderedSheet` objects and reuses the digest's
batch-lifecycle helpers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .batch_digest import (
    DEFAULT_BATCH_MAX_ELAPSED_SECONDS,
    MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES,
    LogCallback,
    ProgressCallback,
    StatusCallback,
    _cancel_batch,
    _poll_until_terminal,
    _release_uploaded_files,
)
from .critique import (
    _CRITIQUE_TASK_INSTRUCTION,
    CRITIQUE_PROMPT_VERSION,
    DEFAULT_CRITIQUE_EFFORT,
    DEFAULT_CRITIQUE_MAX_TOKENS,
    CritiqueResult,
    CritiqueRunOutcome,
    build_critique_request_params,
    critique_cache_entry_from_result,
    critique_model,
    critique_result_from_entry,
    critique_runs,
    critique_sheet_self_consistent,
    outcome_from_message,
    result_from_outcomes,
    run_checklists,
)
from .diagnostics import get_logger, summarize_exc
from .digest import _get
from .digest_cache import critique_cache_key
from .file_upload import (
    FILES_API_BETA,
    delete_files,
    run_fatal_upload_status,
    upload_failure_hint,
    upload_sheet_images,
)
from .profiles import Profile, profiles_cache_fragment

_log = get_logger()


@dataclass
class _CSlot:
    """One sheet's place in the critique batch, plus how it is being served."""

    index: int
    ref: Any
    # Grid dims, for bounds-checking the model's tile_label at parse (§17.1).
    rows: int = 0
    cols: int = 0
    # Set for a cache hit or a real-time fallback (no batch item for this sheet).
    result: CritiqueResult | None = None
    # One custom_id per requested read; empty when the sheet was served without
    # the batch (cache hit / upload-failure fallback).
    custom_ids: list[str] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)
    cache_key: str | None = None
    # The sheet's critique was produced via a synchronous real-time fallback (its
    # Files-API upload failed), so the pipeline prices it REAL_TIME not BATCH.
    rescued: bool = False


@dataclass
class CritiqueBatch:
    """A submitted (or fully-cached) critique batch, awaiting collection."""

    batch_id: str | None
    slots: list[_CSlot]
    total: int
    runs: int
    # custom_id -> (slot, run_id) so a collected item maps back to its sheet and
    # its self-consistency read without re-parsing the id string.
    by_custom_id: dict[str, tuple[_CSlot, str]] = field(default_factory=dict)

    @property
    def submitted_slots(self) -> list[_CSlot]:
        return [s for s in self.slots if s.custom_ids]

    @property
    def all_file_ids(self) -> list[str]:
        return [fid for s in self.slots for fid in s.file_ids]


def submit_critique_batch(
    rendered_sheets,
    *,
    client: Any,
    cache: Any = None,
    model: str | None = None,
    runs: int | None = None,
    profiles: list[Profile] | None = None,
    max_tokens: int = DEFAULT_CRITIQUE_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_CRITIQUE_EFFORT,
    progress: ProgressCallback | None = None,
    total: int = 0,
    on_status: StatusCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CritiqueBatch:
    """Render-stream → cache-or-upload → submit one Message Batch of critique reads.

    ``rendered_sheets`` is an iterable of :class:`RenderedSheet` (streamed, so at
    most one sheet's images are held at a time; the pipeline passes only the sheets
    that missed the level-1 critique cache). For each sheet:

    * a **level-2** (image-bytes) critique-cache hit resolves the slot with a merged
      :class:`~drawing_analyzer.critique.CritiqueResult` — no upload, no batch item;
    * otherwise the sheet's images upload once and become ``runs`` batch items (one
      per self-consistency read) sharing the uploaded ``file_id``s;
    * an upload failure degrades **only that sheet** to a synchronous real-time
      critique that reuses the in-hand render (no re-render), marked ``rescued`` so
      the pipeline prices it REAL_TIME — the critique is additive/non-fatal (I-3).

    All reads across all sheets go in ONE ``batches.create``. If that call raises,
    every already-uploaded file is deleted and only the would-be-batched sheets
    (``custom_ids`` set, no result yet) are degraded to an errored, empty critique;
    the function still **returns** a ``CritiqueBatch(batch_id=None)`` so the slots
    already resolved (cache hits and real-time fallbacks) are preserved — the submit
    failure is additive/non-fatal (I-3) and does not propagate. Any *other*
    unexpected error escaping the submit loop deletes the uploaded files before
    propagating, so a submit failure never leaks remote files (DA-034).
    """
    model = model or critique_model()
    runs = critique_runs() if runs is None else max(1, int(runs))
    checklists = run_checklists(profiles, runs)
    profiles_key = profiles_cache_fragment(profiles or [])

    slots: list[_CSlot] = []
    reqs: list[dict] = []
    by_custom_id: dict[str, tuple[_CSlot, str]] = {}
    uploaded_all: list[str] = []  # every id uploaded so far, for submit-failure cleanup

    # Upload circuit breaker, mirroring the digest batch path (§10.1). A
    # credential/route-level rejection (401/403/404) will hit every remaining
    # upload identically, so after MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES such
    # failures in a row the remaining sheets skip the (doomed) upload and go
    # straight to the real-time fallback — otherwise a whole-run Files-API outage
    # would fire one dead upload round-trip per sheet before each fallback.
    fatal_streak = 0
    last_fatal_status: int | None = None
    uploads_dead = False

    def _serve_realtime(slot: _CSlot, sheet) -> None:
        """Critique one sheet via a synchronous real-time self-consistency read.

        Reuses the render already in hand (no re-render, no batch discount) and
        marks the result ``rescued`` so the pipeline prices it REAL_TIME. Used both
        when a sheet's upload fails and when uploads are already known dead.
        """
        slot.result = critique_sheet_self_consistent(
            sheet, client=client, cache=cache, runs=runs, model=model,
            max_tokens=max_tokens, use_thinking=use_thinking, effort=effort,
            sleep=sleep, profiles=profiles,
        )
        slot.rescued = True
        # Carry the rescue marker onto the RESULT itself — the pipeline prices each
        # sheet off ``res.rescued``. A cache hit inside the fallback keeps CACHE
        # precedence, so marking it rescued is harmless there.
        if not slot.result.cached:
            slot.result.rescued = True
        slots.append(slot)
        if progress is not None:
            progress(slot.index + 1, total or 0, f"Critiqued {sheet.ref.display_label} (inline)")

    batch_id: str | None = None
    try:
        for index, sheet in enumerate(rendered_sheets):
            slot = _CSlot(
                index=index, ref=sheet.ref,
                rows=getattr(sheet, "rows", 0), cols=getattr(sheet, "cols", 0),
            )

            cache_key: str | None = None
            if cache is not None:
                cache_key = critique_cache_key(
                    sheet,
                    model=model,
                    prompt_version=CRITIQUE_PROMPT_VERSION,
                    max_tokens=max_tokens,
                    effort=effort,
                    use_thinking=use_thinking,
                    runs=runs,
                    sheet_text=sheet.sheet_text,
                    profiles_key=profiles_key,
                )
                hit = cache.get(cache_key)
                if hit is not None:
                    slot.result = critique_result_from_entry(hit, sheet.ref)
                    slots.append(slot)
                    _log.debug("critique sheet %d cache hit: %s", index, sheet.ref.display_label)
                    if progress is not None:
                        progress(index + 1, total or 0, f"Cached critique {sheet.ref.display_label}")
                    continue
            slot.cache_key = cache_key

            # The Files API is already known dead this run (consecutive 401/403/404s):
            # skip the doomed upload and critique this sheet real-time. Cache hits are
            # still served above, so only the upload round-trips stop.
            if uploads_dead:
                _serve_realtime(slot, sheet)
                continue

            on_image = None
            if on_status is not None:
                def on_image(pos, n, retrying, *, _k=index + 1, _label=sheet.ref.display_label):
                    verb = "Retrying" if retrying else "Uploading"
                    tail = " after overload" if retrying else ""
                    on_status(f"[{_k}/{total}] critique {verb} image {pos}/{n}{tail} — {_label}")

            # This sheet needs the Files API (the upload here, and the batch/collect
            # that follow, all talk to it). The pipeline may DEFER client creation
            # and pass ``None`` — exactly as the digest batch path allows, where
            # ``_digest_sheets_via_batch`` resolves it "since the upload happens at
            # submit time". Resolve it here too, at the first sheet that actually
            # uploads. A fully cache-served pass ``continue``s above and never reaches
            # this, so a warm offline re-run still needs no key. Without this the
            # critique path handed ``None`` straight to ``client.beta.files.upload`` —
            # an ``AttributeError: 'NoneType' object has no attribute 'beta'`` that the
            # per-sheet guard below swallowed, silently degrading EVERY sheet to the
            # slow, full-price real-time fallback (Batches never used at all, DA-030).
            if client is None:
                from .client import get_client as _get_client

                client = _get_client()

            try:
                upload = upload_sheet_images(
                    client, sheet,
                    task_instruction=_CRITIQUE_TASK_INSTRUCTION,
                    on_image=on_image,
                )
            except Exception as exc:  # noqa: BLE001 - one sheet's upload failing is captured, not fatal
                # The Files-API upload failed for this sheet (route down, credential,
                # or transient exhausted). Rather than lose the sheet's critique, fall
                # back to a synchronous real-time self-consistency read that reuses the
                # render already in hand — no re-render, no batch discount for it.
                _log.warning(
                    "critique sheet %d upload failed; falling back to real-time: %s (%s)",
                    index, sheet.ref.display_label, summarize_exc(exc),
                )
                _serve_realtime(slot, sheet)
                # Breaker accounting: only an unbroken run of the SAME
                # credential/route-level status (401/403/404) trips it — those hit
                # every remaining sheet identically. Any other failure (transient
                # retries exhausted, a payload-shaped 4xx) resets the streak because it
                # says nothing about the next sheet's fate.
                status = run_fatal_upload_status(exc)
                if status is None:
                    fatal_streak = 0
                    last_fatal_status = None
                    continue
                fatal_streak = fatal_streak + 1 if status == last_fatal_status else 1
                last_fatal_status = status
                if fatal_streak >= MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES:
                    uploads_dead = True
                    hint = upload_failure_hint(exc)
                    _log.warning(
                        "Files API unreachable after %d consecutive HTTP %d critique "
                        "upload failure(s); critiquing the remaining sheets real-time%s",
                        fatal_streak, status, f" — {hint}" if hint else "",
                    )
                continue

            # A successful upload proves the Files API is reachable — reset the streak.
            fatal_streak = 0
            last_fatal_status = None
            slot.file_ids = upload.file_ids
            uploaded_all.extend(upload.file_ids)
            for i in range(runs):
                custom_id = f"sheet__{index}__r{i + 1}"
                params = build_critique_request_params(
                    upload.content,
                    model=model,
                    max_tokens=max_tokens,
                    use_thinking=use_thinking,
                    effort=effort,
                    checklist=checklists[i],
                )
                reqs.append({"custom_id": custom_id, "params": params})
                slot.custom_ids.append(custom_id)
                by_custom_id[custom_id] = (slot, f"critique_{i + 1}")
            slots.append(slot)
            _log.debug(
                "critique sheet %d uploaded %d image(s) as %d read(s): %s",
                index, len(upload.file_ids), runs, sheet.ref.display_label,
            )
            if progress is not None:
                progress(index + 1, total or 0, f"Uploaded critique {sheet.ref.display_label}")

        if reqs:
            try:
                mb = client.beta.messages.batches.create(requests=reqs, betas=[FILES_API_BETA])
            except Exception as exc:  # noqa: BLE001 - additive/non-fatal (I-3), see below
                # DA-034: the uploads are already remote but no batch will ever
                # reference them — delete every one so a submit failure never leaks
                # files. Then DEGRADE ONLY the would-be-batched sheets rather than
                # re-raise: the critique is additive and per-sheet non-fatal (I-3), and
                # re-raising here would propagate to the stage-level guard and discard
                # the results ALREADY resolved on the other slots — free cache hits and,
                # worse, the paid-for real-time fallbacks whose reads have already run.
                # Only the sheets whose reads never happened (custom_ids set, no result)
                # lose their critique; every resolved slot is preserved.
                batched = [s for s in slots if s.custom_ids and s.result is None]
                _log.warning(
                    "critique batch submit failed (%s); deleting %d uploaded file(s) "
                    "and degrading %d batched sheet(s) to no-critique",
                    summarize_exc(exc), len(uploaded_all), len(batched),
                )
                delete_files(client, uploaded_all)
                for s in batched:
                    s.result = CritiqueResult(
                        findings=[], input_tokens=0, output_tokens=0,
                        runs=0, requested_runs=runs, completed_runs=0,
                        error=f"critique batch submit failed: {summarize_exc(exc)}",
                    )
                    s.custom_ids = []   # nothing to collect for it
                    s.file_ids = []     # already deleted
                return CritiqueBatch(
                    batch_id=None, slots=slots, total=total or len(slots),
                    runs=runs, by_custom_id={},
                )
            batch_id = _get(mb, "id")
            _log.info(
                "critique batch submitted: id=%s items=%d (%d sheet(s) x %d read(s))",
                batch_id, len(reqs), len(reqs) // max(1, runs), runs,
            )
    except Exception:  # noqa: BLE001 - clean up before propagating (DA-034)
        # An unexpected error escaped the submit loop before any batch owns the
        # already-uploaded files (a cache-backend error, a fallback blowing up, …).
        # Delete them so they never leak, then propagate. The expected
        # ``batches.create`` failure is handled non-fatally above and returns, so it
        # never reaches here.
        delete_files(client, uploaded_all)
        raise

    return CritiqueBatch(
        batch_id=batch_id,
        slots=slots,
        total=total or len(slots),
        runs=runs,
        by_custom_id=by_custom_id,
    )


def _outcome_from_envelope(
    env: Any, *, run_id: str, ref: Any, rows: int = 0, cols: int = 0
) -> CritiqueRunOutcome:
    """Turn one batch result envelope into a :class:`CritiqueRunOutcome`.

    A missing or non-``succeeded`` envelope is a **failed** read (never an empty
    success): the merge runs over surviving reads and this sheet is honestly marked
    partial. A ``succeeded`` envelope is handed to the shared
    :func:`~drawing_analyzer.critique.outcome_from_message`, so a batched read is
    judged, provenance-stamped, and billed identically to a real-time one.
    """
    if env is None:
        return CritiqueRunOutcome(
            run_id=run_id, status="FAILED",
            error="critique batch returned no result for this read",
        )
    rr = _get(env, "result")
    if _get(rr, "type") != "succeeded":
        rtype = _get(rr, "type", "errored")
        error = _get(rr, "error", None)
        inner = _get(error, "error", error) if error is not None else None
        detail = str(_get(inner, "message", "") or "").strip() or f"batch item {rtype}"
        return CritiqueRunOutcome(run_id=run_id, status="FAILED", error=detail)
    return outcome_from_message(
        _get(rr, "message"), run_id=run_id, ref=ref, rows=rows, cols=cols
    )


def collect_critique_batch(
    batch: CritiqueBatch,
    *,
    client: Any,
    cache: Any = None,
    progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_elapsed_seconds: int = DEFAULT_BATCH_MAX_ELAPSED_SECONDS,
    cleanup_in_background: bool = False,
) -> list[tuple[Any, CritiqueResult]]:
    """Poll the critique batch to completion and merge each sheet's reads.

    Cache hits and upload-failure fallbacks are already resolved on their slots.
    Submitted items are polled to a terminal state, collected, grouped by sheet,
    and merged into one :class:`~drawing_analyzer.critique.CritiqueResult` per sheet
    via the shared :func:`~drawing_analyzer.critique.result_from_outcomes` — so a
    batched sheet's self-consistency verdict is identical to a real-time one. A
    complete result (every read parsed) is written to the level-2 cache.

    Returns ``[(SheetRef, CritiqueResult), …]`` in page order.

    **Cleanup (DA-034):** the uploaded files are released on every exit where the
    batch no longer needs them — a fully-collected terminal batch, a confirmed
    cancel, or an unexpected collection error (best-effort cancel, then release).
    A non-terminal batch this run could not cancel keeps its files (it may still be
    running remotely; they expire server-side) and that retention is logged.
    """
    submitted = batch.submitted_slots
    if not (batch.batch_id and submitted):
        return _assemble(batch)

    # The poll / results / cancel / delete below all talk to the API; the pipeline
    # may have deferred client creation and passed ``None`` (as the digest collect
    # path allows). A no-batch collect returned just above, so a fully cache-served
    # run still needs no key. Mirrors submit_critique_batch's resolution.
    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    terminal = False
    canceled = False
    try:
        # The poll counts batch ITEMS (reads = sheets x runs), but the critique
        # stage's progress contract is per-SHEET (pipeline.py) — the submit and
        # ingest phases already emit ``(done, total)`` in sheets. Routing the
        # sheet-progress callback through the read-counting poll would label a
        # read count "sheet(s)" and rescale a determinate bar mid-stage, so the
        # poll reports only to ``on_log`` (its diagnostics still flow); the bar
        # advances per sheet as results are ingested.
        #
        # No stall watch here (deliberately, unlike the digest path):
        # ``_poll_until_terminal`` counts only *completed* items, so it treats an
        # hour with nothing finished as ``"stalled"``. That early give-up is only
        # safe when the caller can recover the sheets another way — the digest pairs
        # it with a direct-call rescue. The critique has no rescue: a give-up would
        # cancel the batch and lose those sheets' critique. A small or image-heavy
        # critique batch can legitimately sit with zero completed items for over an
        # hour while every read is still processing, so tripping a stall watch here
        # would cancel recoverable work. It rides the full elapsed bound instead.
        status = _poll_until_terminal(
            client,
            batch.batch_id,
            total=len(submitted) * batch.runs,
            cached_done=0,
            progress=None,
            on_log=on_log,
            sleep=sleep,
            max_elapsed_seconds=max_elapsed_seconds,
        )
        if status in ("ended", "failed", "expired", "canceled"):
            terminal = True
            raw: dict[str, Any] = {}
            for result in client.messages.batches.results(batch.batch_id):
                raw[_get(result, "custom_id")] = result
            # Group each sheet's reads (keyed by slot identity, order-independent).
            outcomes: dict[int, list[CritiqueRunOutcome]] = {id(s): [] for s in submitted}
            for custom_id, (slot, run_id) in batch.by_custom_id.items():
                outcomes[id(slot)].append(
                    _outcome_from_envelope(
                        raw.get(custom_id), run_id=run_id, ref=slot.ref,
                        rows=getattr(slot, "rows", 0), cols=getattr(slot, "cols", 0),
                    )
                )
            for slot in submitted:
                res = result_from_outcomes(
                    outcomes[id(slot)], requested_runs=batch.runs,
                    label=slot.ref.display_label,
                )
                slot.result = res
                # Cache only a *complete* result — every requested read parsed. A
                # partial (a read failed) is returned but never frozen under the
                # full-runs key (DA-008), mirroring the real-time path. The write is
                # best-effort: a cache I/O failure must never discard this (or any
                # not-yet-merged) already-collected result by unwinding the loop.
                if (
                    cache is not None and slot.cache_key
                    and res.error is None and res.completed_runs == batch.runs
                ):
                    try:
                        cache.put(slot.cache_key, critique_cache_entry_from_result(res))
                    except Exception as exc:  # noqa: BLE001 - cache write is advisory
                        _log.warning(
                            "critique cache write failed for %s: %s",
                            slot.ref.display_label, summarize_exc(exc),
                        )
        else:
            # Non-terminal (detached / failed / poll_failed): the batch is abandoned
            # for collection. Best-effort cancel it (leaving it running only burns
            # quota) and degrade the unresolved sheets' critique honestly — additive
            # and non-fatal (I-3), the standard deliverable is untouched.
            canceled = _cancel_batch(client, batch.batch_id, on_log=on_log)
            tail = "was canceled" if canceled else "may still be running"
            for slot in submitted:
                if slot.result is None:
                    slot.result = CritiqueResult(
                        findings=[], input_tokens=0, output_tokens=0,
                        runs=0, requested_runs=batch.runs, completed_runs=0,
                        error=(
                            f"critique batch not collected ({status}); "
                            f"remote batch id={batch.batch_id} {tail}"
                        ),
                    )
            if on_log is not None:
                on_log(
                    f"Critique batch {status}; {len(submitted)} sheet(s) uncritiqued",
                    level="warning",
                )
    except Exception as exc:  # noqa: BLE001 - critique is additive/non-fatal (I-3)
        # An unexpected error mid-collect (e.g. results() raising). Degrade the
        # unresolved sheets and best-effort cancel so the finally can safely
        # release the files instead of leaking them (DA-034).
        _log.warning("critique batch collection error: %s", summarize_exc(exc))
        if not terminal:
            canceled = canceled or _cancel_batch(client, batch.batch_id, on_log=on_log)
        for slot in submitted:
            if slot.result is None:
                slot.result = CritiqueResult(
                    findings=[], input_tokens=0, output_tokens=0,
                    runs=0, requested_runs=batch.runs, completed_runs=0,
                    error=f"critique batch collection error: {summarize_exc(exc)}",
                )
    finally:
        # DA-034: release the uploaded files on every exit where the batch no
        # longer needs them — a terminal (fully-collected) batch or one we
        # confirmed canceled. A non-terminal batch we could NOT cancel may still be
        # running, so its files are retained (safe detach) and expire server-side.
        if terminal or canceled:
            _release_uploaded_files(
                client, batch.all_file_ids,
                in_background=cleanup_in_background, on_log=on_log,
            )
        elif batch.all_file_ids:
            _log.warning(
                "critique batch %s not collected and not canceled; retaining %d "
                "uploaded file(s) (they expire server-side)",
                batch.batch_id, len(batch.all_file_ids),
            )

    return _assemble(batch)


def _assemble(batch: CritiqueBatch) -> list[tuple[Any, CritiqueResult]]:
    """Page-ordered ``(ref, result)`` pairs; defensively backfill any empty slot."""
    out: list[tuple[Any, CritiqueResult]] = []
    for slot in sorted(batch.slots, key=lambda s: s.index):
        res = slot.result
        if res is None:  # defensive — every slot resolves above
            _log.error("critique slot %d produced no result (defensive backfill)", slot.index)
            res = CritiqueResult(
                findings=[], requested_runs=batch.runs, completed_runs=0,
                error="critique produced no result",
            )
        out.append((slot.ref, res))
    return out
