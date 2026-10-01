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

When the digest stage retained a terminal upload, the critique can adopt that
same manifest after its level-1 cache miss. Only the closing task instruction is
retasked; framing, text layer, image ordering, and ``file_id`` references remain
identical. Missing or already-claimed manifests use the historical render/upload
path.

Additive & non-fatal (I-3): the critique is optional QC, so — unlike the digest,
whose loss zeroes a run and which therefore carries an elaborate follow-up-batch
+ direct-call rescue — this collector keeps things simpler. A failed read that
the digest's own retry predicate retries (a transient errored or an expired
item, a refusal with a registry route, a ``max_tokens`` stop at a raised cap)
is resubmitted in follow-up critique batches, inside the collection bound and
its sheet's one retry budget (remediation WP-01.8, :func:`_recover_failed_reads`);
never as a full-rate real-time call. A read still failing after that just
fails (the surviving read still merges, honestly marked
``NOT_ASSESSED_PARTIAL``); a batch that never terminates degrades the affected
sheets' critique to an empty result with a clear error (there is no harvest:
a new row, WP-18.6). The standard digest deliverable and the digest's own
findings are never touched.

Isolation (I-5): imports no PDF engine; consumes already-rendered
:class:`~drawing_analyzer.models.RenderedSheet` objects and reuses the digest's
batch-lifecycle helpers.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .batch_digest import (
    DEFAULT_POLL_INTERVAL_SECONDS,
    MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES,
    LogCallback,
    ProgressCallback,
    StatusCallback,
    _batch_item_error_text,
    _batch_max_elapsed_seconds,
    _cancel_batch,
    _count_retry,
    _max_batch_resubmit_rounds,
    _note_not_retried,
    _poll_until_terminal,
    _release_uploaded_files,
    _retry_params_for,
    _within_retry_budget,
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
    keep_critique_read,
    outcome_from_message,
    result_from_outcomes,
    run_checklists,
)
from .diagnostics import get_logger, summarize_exc
from .digest import _get, _retry_backoff_seconds
from .digest_cache import critique_cache_key
from .file_upload import (
    ReusableSheetUpload,
    delete_files,
    iter_prefetched_sheets,
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
    # Remediation WP-01.8 (the owner's rule: WP-01.5's per-sheet budget): the
    # resubmissions of this sheet's reads so far, every read counting one.
    # Bounded by ``batch_digest._max_batch_resubmit_rounds``.
    retries: int = 0


@dataclass
class _CRead:
    """One submitted self-consistency read of a sheet (remediation WP-01.8).

    What the follow-up rounds need to resubmit it: its ``custom_id`` (reused in
    every round, as a digest item's is), the ``params`` it was first submitted
    with (the requested model and cap), ``last_params`` (its latest
    submission, so a raised cap doubles from the cap that just came back and a
    fallback's read knows its model) and its ``outcome`` so far. Its sheet's
    slot holds the one retry budget (``retry_budget``, which
    ``batch_digest._within_retry_budget`` and ``_count_retry`` read).
    """

    slot: _CSlot
    run_id: str
    custom_id: str
    params: dict
    last_params: dict | None = None
    outcome: CritiqueRunOutcome | None = None

    @property
    def ref(self) -> Any:
        return self.slot.ref

    @property
    def retry_budget(self) -> _CSlot:
        return self.slot

    @property
    def requested_model(self) -> str:
        return str(self.params.get("model") or "")

    def fallback_model(self, params: dict | None = None) -> str | None:
        """The model ``params`` (default: the latest submission) sent this read
        to, when a refusal fallback moved it off the requested one."""
        sent = str((params or self.last_params or self.params).get("model") or "")
        return sent if sent and sent != self.requested_model else None


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
    # Every submitted read, in submit order (remediation WP-01.8): what the
    # follow-up rounds resubmit a failed read from.
    reads: list[_CRead] = field(default_factory=list)

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

    ``rendered_sheets`` streams either :class:`RenderedSheet` objects or terminal
    digest-stage :class:`ReusableSheetUpload` manifests. The pipeline passes only
    sheets that missed the level-1 critique cache. One fallback render is
    prefetched while the current sheet uploads; order and upload-breaker decisions
    remain sequential and at most two rendered sheets are resident. For each sheet:

    * a **level-2** (image-bytes) critique-cache hit resolves the slot with a merged
      :class:`~drawing_analyzer.critique.CritiqueResult` — no upload, no batch item;
    * otherwise a retained digest upload is adopted, or the sheet's images upload
      once, and become ``runs`` batch items sharing the uploaded ``file_id``s;
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
    reads: list[_CRead] = []
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
        for index, sheet_input in enumerate(iter_prefetched_sheets(rendered_sheets)):
            reusable = (
                sheet_input if isinstance(sheet_input, ReusableSheetUpload) else None
            )
            sheet = None if reusable is not None else sheet_input
            ref = reusable.ref if reusable is not None else sheet.ref
            slot = _CSlot(
                index=index, ref=ref,
                rows=getattr(sheet_input, "rows", 0),
                cols=getattr(sheet_input, "cols", 0),
            )

            # A retained upload reaches here only after the pipeline's level-1
            # critique cache miss. A fresh render still probes the historical
            # level-2 image-bytes key before any upload.
            cache_key: str | None = None
            if reusable is None and cache is not None:
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
                    slot.result = critique_result_from_entry(hit, ref)
                    slots.append(slot)
                    _log.debug("critique sheet %d cache hit: %s", index, ref.display_label)
                    if progress is not None:
                        progress(index + 1, total or 0, f"Cached critique {ref.display_label}")
                    continue
            slot.cache_key = cache_key

            upload = None
            reused_digest_upload = False
            if reusable is not None:
                upload = reusable.transfer(_CRITIQUE_TASK_INSTRUCTION)
                if upload is None:
                    # The pipeline filters unavailable manifests and renders that
                    # page instead. This guard keeps direct callers additive if a
                    # manifest is concurrently claimed between validation/use.
                    slot.result = CritiqueResult(
                        findings=[], input_tokens=0, output_tokens=0,
                        runs=0, requested_runs=runs, completed_runs=0,
                        error="retained digest upload was no longer available",
                    )
                    slots.append(slot)
                    _log.warning(
                        "critique sheet %d retained upload unavailable: %s",
                        index, ref.display_label,
                    )
                    if progress is not None:
                        progress(index + 1, total or 0, f"Critique unavailable {ref.display_label}")
                    continue
                reused_digest_upload = True
            else:
                # The Files API is already known dead this run
                # (consecutive 401/403/404s): skip the doomed upload and critique
                # this freshly rendered sheet real-time. Retained digest uploads
                # bypass this breaker because they need no Files-API upload.
                if uploads_dead:
                    _serve_realtime(slot, sheet)
                    continue

                on_image = None
                if on_status is not None:
                    def on_image(pos, n, retrying, *, _k=index + 1, _label=ref.display_label):
                        verb = "Retrying" if retrying else "Uploading"
                        tail = " after overload" if retrying else ""
                        on_status(f"[{_k}/{total}] critique {verb} image {pos}/{n}{tail} — {_label}")

                # Resolve a deferred client only when a fresh upload is needed.
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
                    _log.warning(
                        "critique sheet %d upload failed; falling back to real-time: %s (%s)",
                        index, ref.display_label, summarize_exc(exc),
                    )
                    _serve_realtime(slot, sheet)
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

                # A successful fresh upload proves the Files API is reachable.
                fatal_streak = 0
                last_fatal_status = None

            assert upload is not None
            slot.file_ids = list(upload.file_ids)
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
                    # Explicitly OFF on the batch transport, never left to the
                    # env flag. The structured-outputs latch recovers from a
                    # rejection by re-sending the same read unconstrained, and a
                    # batch item cannot be re-sent: its shape is fixed at submit
                    # and a rejection surfaces per item, after the whole batch
                    # has been built and billed. So the transport that cannot
                    # degrade does not opt in. ``structured_key`` is omitted
                    # from this path's cache key to match (below).
                    structured=False,
                )
                reqs.append({"custom_id": custom_id, "params": params})
                slot.custom_ids.append(custom_id)
                by_custom_id[custom_id] = (slot, f"critique_{i + 1}")
                reads.append(_CRead(
                    slot=slot, run_id=f"critique_{i + 1}", custom_id=custom_id,
                    params=params,
                ))
            slots.append(slot)
            _log.debug(
                "critique sheet %d %s %d image(s) as %d read(s): %s",
                index,
                "reused digest upload with" if reused_digest_upload else "uploaded",
                len(upload.file_ids), runs, ref.display_label,
            )
            if progress is not None:
                verb = "Reused digest upload for" if reused_digest_upload else "Uploaded critique"
                progress(index + 1, total or 0, f"{verb} {ref.display_label}")

        if reqs:
            # A fully reused pass made no Files-API call, so the deferred client
            # still needs resolving before the Message Batch submission.
            if client is None:
                from .client import get_client as _get_client

                client = _get_client()
            try:
                mb = client.messages.batches.create(requests=reqs)
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
        reads=reads,
    )


def _outcome_from_envelope(
    env: Any, *, run_id: str, ref: Any, rows: int = 0, cols: int = 0,
    fallback_model: str | None = None,
) -> CritiqueRunOutcome:
    """Turn one batch result envelope into a :class:`CritiqueRunOutcome`.

    A missing or non-``succeeded`` envelope is a **failed** read (never an empty
    success): the merge runs over surviving reads and this sheet is honestly marked
    partial. A ``succeeded`` envelope is handed to the shared
    :func:`~drawing_analyzer.critique.outcome_from_message`, so a batched read is
    judged, provenance-stamped, and billed identically to a real-time one. That
    includes the stop reason (D-1; remediation WP-01.4, N4): ``succeeded`` means
    the request was served, not that the model finished, so a read inside it
    cut off at ``max_tokens``, refused, with no stop reason or with an unknown
    one fails there, however complete its findings object looks.

    ``fallback_model`` names the model a follow-up round sent the read to on
    its refusal fallback (remediation WP-01.8), for its wording.
    """
    if env is None:
        return CritiqueRunOutcome(
            run_id=run_id, status="FAILED",
            error="critique batch returned no result for this read",
        )
    rr = _get(env, "result")
    if _get(rr, "type") != "succeeded":
        # The digest's one item-error helper (remediation WP-01.5): an errored
        # read names its type with its message (``overloaded_error: …``), as a
        # digest item does; the type used to be dropped. A canceled or expired
        # read keeps its wording, ``batch item canceled``.
        return CritiqueRunOutcome(
            run_id=run_id, status="FAILED", error=_batch_item_error_text(rr, noun="item"),
        )
    return outcome_from_message(
        _get(rr, "message"), run_id=run_id, ref=ref, rows=rows, cols=cols,
        fallback_model=fallback_model,
    )


_TERMINAL_STATUSES = ("ended", "failed", "expired", "canceled")


def _read_retry_params(
    read: _CRead, envelope: Any, outcome: CritiqueRunOutcome, *, params: dict | None,
) -> dict | None:
    """What to resubmit a failed read with, or ``None`` (remediation WP-01.8).

    The digest's one retry predicate
    (:func:`~drawing_analyzer.batch_digest._retry_params_for`, the owner's
    rule): a transient errored or an expired item as it was sent, a routed
    refusal on its fallback (once: the chain ends when the fallback refuses
    too), a ``max_tokens`` stop at twice the cap while there is headroom.
    ``params`` is the request the read was last sent with. A refusal whose
    named category has no route says so in the read's error (``…; not
    retried: no fallback for category 'bio' on claude-opus-5``), as a digest
    item's does.
    """
    return _retry_params_for(
        _get(envelope, "result") if envelope is not None else None,
        params=params or None,
        requested_model=read.requested_model,
        stop_reason=outcome.stop_reason,
        failed=not outcome.ok,
        label=f"{read.custom_id} ({read.ref.display_label})",
        noun="critique",
        on_not_retried=lambda reason: _note_not_retried(outcome, reason),
    )


def _fold_retry(read: _CRead, later: CritiqueRunOutcome, *, params: dict) -> None:
    """The read keeps the better of what it holds and ``later`` (WP-01.8).

    :func:`~drawing_analyzer.critique.keep_critique_read`, the one rule the
    real-time raised-cap retry applies too: a finished retry is the read; a
    failed one is named in the read's error, with the model when a refusal
    fallback sent it elsewhere; every attempt's usage is the read's.
    """
    assert read.outcome is not None
    read.outcome = keep_critique_read(read.outcome, later, model=read.fallback_model(params))


def _recover_failed_reads(
    reads: list[_CRead],
    raw: dict[str, Any],
    *,
    client: Any,
    sleep: Callable[[float], None],
    on_log: LogCallback | None,
    max_elapsed_seconds: float,
) -> bool:
    """Retry the primary batch's failed reads in follow-up critique batches.

    Remediation WP-01.8 (the owner's rules). Each read the primary batch
    returned failed, and that the digest's predicate retries
    (:func:`_read_retry_params`), is resubmitted in a **fresh critique batch**
    reusing its sheet's uploaded ``file_id`` references, never as a full-rate
    real-time call:

    * **Bounded twice, as the digest's batch recovery is.** At most
      ``batch_digest._max_batch_resubmit_rounds()`` rounds (default 4, a
      rejected submit included), inside the remaining collection bound; and
      each sheet's one retry budget (the same value, WP-01.5's rule: every
      resubmitted read of the sheet counts one) is checked before every round
      (``batch_digest._within_retry_budget``) and spent after an accepted
      submit (``_count_retry``).
    * **No stall watch**, like the primary critique poll: nothing can recover
      a canceled read, so a round rides the remaining bound. A round that ends
      non-terminal (out of bound, unpollable) is canceled best effort and ends
      the recovery; its reads are named ``…; retry: critique batch not
      collected (<status>); remote batch id=… was canceled``.
    * **What a round returns** folds into each read (:func:`_fold_retry`); a
      read still failing goes to the next round with the predicate's params
      (a raised cap doubles from the cap just sent), and a read the round
      returned no envelope for goes again as it was sent (it was retryable).

    Never fatal (I-3): a failure inside leaves every read as it stands and
    cancels a round it had submitted. Returns ``True`` when every follow-up
    batch it submitted is terminal or confirmed canceled, i.e. none may still
    reference the uploaded files.
    """
    pending: list[tuple[_CRead, dict]] = []
    for read in reads:
        if read.outcome is None or read.outcome.ok:
            continue
        params = _read_retry_params(read, raw.get(read.custom_id), read.outcome,
                                    params=read.params)
        if params is not None:
            pending.append((read, params))
    if not pending:
        return True

    started = time.monotonic()
    files_safe = True
    attempted = len(pending)
    recovered = 0
    open_batch: str | None = None
    max_rounds = _max_batch_resubmit_rounds()
    try:
        for round_no in range(1, max_rounds + 1):
            pending = _within_retry_budget(
                pending, where=f"critique follow-up batch round {round_no}",
            )
            if not pending:
                break
            budget_left = max_elapsed_seconds - (time.monotonic() - started)
            if budget_left < DEFAULT_POLL_INTERVAL_SECONDS:
                _log.warning(
                    "critique follow-up batches out of collection budget after %d "
                    "round(s): %d read(s) not retried", round_no - 1, len(pending),
                )
                break
            reqs = [{"custom_id": read.custom_id, "params": p} for read, p in pending]
            _log.info(
                "critique follow-up batch round %d/%d: resubmitting %d failed read(s)",
                round_no, max_rounds, len(pending),
            )
            if on_log is not None:
                on_log(
                    f"Retrying {len(pending)} failed critique read(s) in a follow-up "
                    f"batch (round {round_no}/{max_rounds})"
                )
            try:
                mb = client.messages.batches.create(requests=reqs)
            except Exception as exc:  # noqa: BLE001 - recovery is best-effort; reads keep their errors
                # A rejected submit bills nothing and spends no retry; back off
                # (inside the bound) and let the next round try again.
                _log.warning(
                    "critique follow-up batch round %d submit failed: %s",
                    round_no, summarize_exc(exc),
                )
                backoff = _retry_backoff_seconds(round_no - 1)
                if backoff >= max_elapsed_seconds - (time.monotonic() - started):
                    break
                sleep(backoff)
                continue
            retry_id = _get(mb, "id")
            open_batch = retry_id
            for read, p in pending:
                _count_retry(read, p)
            _log.info(
                "critique follow-up batch submitted: id=%s items=%d", retry_id, len(reqs),
            )
            status = _poll_until_terminal(
                client, retry_id, total=len(pending), cached_done=0, progress=None,
                on_log=on_log, sleep=sleep, max_elapsed_seconds=budget_left,
            )
            if status not in _TERMINAL_STATUSES:
                canceled = _cancel_batch(client, retry_id, on_log=on_log)
                open_batch = None
                if not canceled:
                    files_safe = False
                tail = "was canceled" if canceled else "may still be running"
                why = (f"critique batch not collected ({status}); "
                       f"remote batch id={retry_id} {tail}")
                for read, p in pending:
                    _fold_retry(read, CritiqueRunOutcome(
                        run_id=read.run_id, status="FAILED", error=why), params=p)
                _log.warning(
                    "critique follow-up batch %s %s; %d read(s) keep their errors",
                    retry_id, status, len(pending),
                )
                pending = []
                break
            open_batch = None
            try:
                raw_retry: dict[str, Any] = {}
                for result in client.messages.batches.results(retry_id):
                    raw_retry[_get(result, "custom_id")] = result
            except Exception as exc:  # noqa: BLE001 - recovery is best-effort; reads keep their errors
                why = f"critique batch results could not be read ({summarize_exc(exc)})"
                for read, p in pending:
                    _fold_retry(read, CritiqueRunOutcome(
                        run_id=read.run_id, status="FAILED", error=why), params=p)
                _log.warning("critique follow-up batch %s: %s", retry_id, why)
                pending = []
                break
            still: list[tuple[_CRead, dict]] = []
            for read, p in pending:
                env = raw_retry.get(read.custom_id)
                oc = _outcome_from_envelope(
                    env, run_id=read.run_id, ref=read.ref,
                    rows=getattr(read.slot, "rows", 0), cols=getattr(read.slot, "cols", 0),
                    fallback_model=read.fallback_model(p),
                )
                # The predicate reads THIS round's reply, before the fold names
                # it, so a note it adds (an unrouted category) is in the name.
                again = (
                    None if oc.ok
                    else p if env is None
                    else _read_retry_params(read, env, oc, params=p)
                )
                _fold_retry(read, oc, params=p)
                if oc.ok:
                    recovered += 1
                elif again is not None:
                    still.append((read, again))
            pending = still
    except Exception as exc:  # noqa: BLE001 - critique is additive/non-fatal (I-3)
        _log.warning("critique follow-up batch recovery failed: %s", summarize_exc(exc))
        if open_batch is not None and not _cancel_batch(client, open_batch, on_log=on_log):
            files_safe = False
        pending = []
    if pending:
        _log.warning(
            "critique follow-up batches exhausted: %d read(s) keep their errors",
            len(pending),
        )
    _log.info("critique follow-up batches recovered %d/%d failed read(s)", recovered, attempted)
    if on_log is not None:
        on_log(f"Recovered {recovered} of {attempted} failed critique read(s)")
    return files_safe


def collect_critique_batch(
    batch: CritiqueBatch,
    *,
    client: Any,
    cache: Any = None,
    progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_elapsed_seconds: float | None = None,
    cleanup_in_background: bool = False,
) -> list[tuple[Any, CritiqueResult]]:
    """Poll the critique batch to completion and merge each sheet's reads.

    Cache hits and upload-failure fallbacks are already resolved on their slots.
    Submitted items are polled to a terminal state, collected, grouped by sheet,
    and merged into one :class:`~drawing_analyzer.critique.CritiqueResult` per sheet
    via the shared :func:`~drawing_analyzer.critique.result_from_outcomes` — so a
    batched sheet's self-consistency verdict is identical to a real-time one. A
    complete result (every read parsed) is written to the level-2 cache.

    Between the collect and the merge, a failed read the digest's predicate
    retries goes to follow-up critique batches (remediation WP-01.8,
    :func:`_recover_failed_reads`): a read that finishes there is the read, and
    a sheet whose every read finished is cached under its requested key, as
    if the primary batch had returned it.

    Returns ``[(SheetRef, CritiqueResult), …]`` in page order.

    **Cleanup (DA-034):** the uploaded files are released on every exit where the
    batch no longer needs them — a fully-collected terminal batch, a confirmed
    cancel, or an unexpected collection error (best-effort cancel, then release).
    A non-terminal batch this run could not cancel keeps its files (it may still be
    running remotely; they expire server-side) and that retention is logged.
    """
    # ``None`` means "the app's bound", resolved HERE rather than as a keyword
    # default so ``DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS`` is read per call
    # instead of frozen at import.
    if max_elapsed_seconds is None:
        max_elapsed_seconds = _batch_max_elapsed_seconds()

    submitted = batch.submitted_slots
    if not (batch.batch_id and submitted):
        return _assemble(batch)
    collect_started = time.monotonic()

    # The poll / results / cancel / delete below all talk to the API; the pipeline
    # may have deferred client creation and passed ``None`` (as the digest collect
    # path allows). A no-batch collect returned just above, so a fully cache-served
    # run still needs no key. Mirrors submit_critique_batch's resolution.
    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    terminal = False
    canceled = False
    # Every follow-up batch is terminal or confirmed canceled (WP-01.8), so
    # none of them can still reference the uploaded files.
    followups_safe = True
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
        if status in _TERMINAL_STATUSES:
            terminal = True
            raw: dict[str, Any] = {}
            for result in client.messages.batches.results(batch.batch_id):
                raw[_get(result, "custom_id")] = result
            reads = _reads_of(batch)
            for read in reads:
                read.outcome = _outcome_from_envelope(
                    raw.get(read.custom_id), run_id=read.run_id, ref=read.ref,
                    rows=getattr(read.slot, "rows", 0), cols=getattr(read.slot, "cols", 0),
                )
            # Remediation WP-01.8 (the owner's rules): a failed read the
            # digest's predicate retries goes to follow-up critique batches,
            # inside the remaining bound and its sheet's retry budget.
            followups_safe = _recover_failed_reads(
                reads, raw, client=client, sleep=sleep, on_log=on_log,
                max_elapsed_seconds=max_elapsed_seconds - (time.monotonic() - collect_started),
            )
            # Group each sheet's reads (keyed by slot identity, in read order).
            outcomes: dict[int, list[CritiqueRunOutcome]] = {id(s): [] for s in submitted}
            for read in reads:
                if read.outcome is not None and id(read.slot) in outcomes:
                    outcomes[id(read.slot)].append(read.outcome)
            for slot in submitted:
                res = result_from_outcomes(
                    outcomes[id(slot)], requested_runs=batch.runs,
                    label=slot.ref.display_label,
                )
                slot.result = res
                # Cache only a *complete* result — every requested read finished
                # and parsed (remediation WP-01.4: a read the model did not finish
                # never counts). A partial (a read failed) is returned but never
                # frozen under the full-runs key (DA-008), mirroring the real-time
                # path. The write is
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
        # The same holds for a follow-up batch (remediation WP-01.8): the files
        # go only once every batch that references them is done with them.
        if (terminal or canceled) and followups_safe:
            _release_uploaded_files(
                client, batch.all_file_ids,
                in_background=cleanup_in_background, on_log=on_log,
            )
        elif batch.all_file_ids:
            _log.warning(
                "critique batch %s %s; retaining %d uploaded file(s) (they expire "
                "server-side)",
                batch.batch_id,
                "has a follow-up batch that could not be canceled"
                if (terminal or canceled) else "not collected and not canceled",
                len(batch.all_file_ids),
            )

    return _assemble(batch)


def _reads_of(batch: CritiqueBatch) -> list[_CRead]:
    """The batch's submitted reads, in submit order.

    ``batch.reads`` for a batch :func:`submit_critique_batch` built; for one
    built by hand with only ``by_custom_id``, reads without params (collected,
    never resubmitted).
    """
    if batch.reads:
        return batch.reads
    return [
        _CRead(slot=slot, run_id=run_id, custom_id=custom_id, params={})
        for custom_id, (slot, run_id) in batch.by_custom_id.items()
    ]


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
