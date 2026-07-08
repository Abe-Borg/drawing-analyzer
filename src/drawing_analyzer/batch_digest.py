"""Batch-mode per-sheet drawing digest via the Message Batches API.

The real-time path (:func:`drawing_analyzer.digest.digest_sheet`) sends one
synchronous vision request per sheet. This path instead submits all *uncached*
sheets as a single Message Batch — 50% cheaper per Anthropic's batch pricing —
and references each sheet's images by Files-API ``file_id`` (see
:mod:`drawing_analyzer.file_upload`) so no per-item body approaches the 32 MB
Messages-API request limit that broke the inline-base64 path on dense sheets.

Flow::

    render → cache hit?  ── yes → reuse digest (no upload, no batch item)
                         └─ no  → upload images + build a batch request
    submit batch → poll to completion → collect → parse each item → SheetDigest
    → write fresh digests to the cache → delete the uploaded files

Caching is preserved exactly as in the real-time path: an unchanged sheet on a
re-run is served from the digest cache and never enters the batch. Results are
assembled in page order regardless of completion order. Per-sheet failures
(upload error, batch item ``errored``/``expired``) are captured on that sheet's
:class:`SheetDigest` and never abort the rest of the set.

Files-API outage fallback: if a sheet's image upload comes back ``404`` (the
/v1/files route is unavailable for the key/workspace while the Messages/Batches
API itself is healthy), that sheet is digested *inline* via the real-time path
(:func:`~drawing_analyzer.digest.digest_sheet`, base64 images in one synchronous
vision request) and its result is attached straight to the slot — so a dead
Files API degrades the run to per-sheet inline digests instead of zeroing it
out. After a few consecutive 404s the doomed upload attempts stop and every
remaining sheet goes straight to the inline path. The inline digest is the same
shape (and shares the same cache key) as a batch digest; it just forgoes the
50% batch discount, which is the right trade when the alternative is no result.
A 401/403 upload rejection is credential-level — an inline request would fail
identically — so those keep the original stop-and-skip behavior.

Batch-backend outage fallback: a collected batch's retryable per-item failures
are resubmitted as one follow-up batch (:func:`_resubmit_failed_items`) — but
when the Batches backend *itself* is the sick component, the follow-up rides
the same sick component and fails identically (a real 8-sheet run watched every
item fail with ``api_error: Internal Server Error`` in BOTH rounds while the
same run's ~300 Files-API uploads had just succeeded). A batch whose EVERY item
failed that way therefore skips the doomed follow-up round outright, and items
still failing retryably after a (partial-failure) follow-up round are rescued
via synchronous, streamed Messages calls carrying each item's exact request
params (:func:`_rescue_failed_items_sync`) — the uploaded ``file_id``
references stay alive until cleanup, so the rescue bypasses batch processing
entirely at the cost of the 50% discount for just the rescued sheets.

Stuck-batch fallback: a batch that never reaches a terminal state at all used
to zero the whole run — two real runs (50 and 20 sheets) sat ``in_progress``
with ZERO completions from submit straight to the 4h elapsed bound, then
returned nothing but "not collected" errors even though every upload and
request in hand was valid. When per-item recovery is enabled
(``retry_failed_items``), the primary poll now holds back a slice of the
collection budget (:func:`_rescue_reserve_seconds`), gives up on a batch whose
request counts haven't moved for :data:`DEFAULT_BATCH_STALL_TIMEOUT_SECONDS`
("stalled"), best-effort cancels the abandoned batch (its results will never
be read, so left running it only burns quota and pins the uploaded files), and
digests every unresolved sheet through the same direct-call rescue — so a
stuck Batches backend now degrades the run to full-price direct calls instead
of losing it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .core.api_config import REVIEW_MODEL_DEFAULT
from .core.tokenizer import estimate_image_tokens_total
from .diagnostics import get_logger, request_id_of, summarize_exc
from .digest import (
    DEFAULT_DIGEST_EFFORT,
    DEFAULT_DIGEST_MAX_RETRIES,
    DEFAULT_DIGEST_MAX_TOKENS,
    DIGEST_PROMPT_VERSION,
    SheetDigest,
    _clean_error,
    _get,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    build_digest_request_params,
    digest_sheet,
    focus_cache_fragment,
    normalize_focus,
)
from .digest_cache import digest_cache_key
from .file_upload import (
    FILES_API_BETA,
    delete_files,
    run_fatal_upload_status,
    upload_failure_allows_inline_fallback,
    upload_failure_hint,
    upload_sheet_images,
)
from .models import SheetRef

# Bounded polling. Mirrors the review/verification batch policy: bound by total
# elapsed (drawing batches of a handful of sheets typically land in minutes, but
# the Batches API may take up to 24h), with progressive backoff so a long batch
# doesn't hammer the poll endpoint.
DEFAULT_BATCH_MAX_ELAPSED_SECONDS = 4 * 3600
DEFAULT_POLL_INTERVAL_SECONDS = 15
DEFAULT_POLL_MAX_INTERVAL_SECONDS = 120
DEFAULT_POLL_BACKOFF_AFTER_SECONDS = 5 * 60
DEFAULT_MAX_CONSECUTIVE_POLL_ERRORS = 10

# Give-up threshold for a batch showing NO per-item progress. Anthropic's
# guidance is that most batches complete within 1h (24h worst case), and this
# app's healthy drawing batches land in minutes — while the two real stuck
# batches sat at ``processing=N`` with zero completions from submit to the 4h
# bound. One hour of completely frozen request counts separates the two
# cleanly: patient enough for a deep queue under load (any completion resets
# the timer), early enough to leave most of the collection budget for the
# direct-call rescue. The stall watch runs only when the caller opted into
# recovery (``retry_failed_items``): without a recovery path, giving up early
# would just lose the sheets sooner.
DEFAULT_BATCH_STALL_TIMEOUT_SECONDS = 60 * 60

# Slice of the collection budget held back from the primary poll when recovery
# is enabled, so a batch that runs the poll's full bound without terminating
# ("detached") still leaves the direct-call rescue room to work — otherwise
# the poll would consume the entire budget and the rescue could attempt
# nothing. Capped at 25% of the budget so a small bound still gives the poll
# the lion's share.
DEFAULT_RESCUE_RESERVE_SECONDS = 30 * 60

# Consecutive sheets failing their upload with the SAME run-fatal status
# (credential/route-level — see ``RUN_FATAL_UPLOAD_STATUSES``) tolerated before
# the submit loop stops attempting uploads for the remaining sheets. Three
# identical strikes rules out a one-off blip while keeping a real outage cheap:
# a 33-sheet run against a dead /v1/files route previously spent ~2 minutes
# failing every sheet one request at a time. Remaining sheets are still
# rendered and reported (each carries a clear "skipped" error naming the
# original failure), so the per-sheet result list stays complete — only the
# doomed API calls stop.
MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES = 3

ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[..., None]
# ``on_status(text)`` — a transient, status-line-only update (never logged). Used
# for high-frequency feedback (per-image upload progress) that would swamp the
# milestone-oriented activity log, so the GUI can show continuous motion without
# spamming its history.
StatusCallback = Callable[[str], None]

_log = get_logger()


def _run_in_background(fn: Callable[[], None]) -> None:
    """Run ``fn`` on a fire-and-forget daemon thread (seam for tests to stub)."""
    threading.Thread(target=fn, daemon=True).start()


def _release_uploaded_files(
    client: Any,
    file_ids: list[str],
    *,
    in_background: bool,
    on_log: LogCallback | None,
) -> None:
    """Delete a collected batch's uploaded files; optionally off the hot path.

    Cleanup deletes one file per request, so a collected set of a few hundred
    images can take many minutes — and under a Files-API overload (the same wave
    that makes the uploads themselves slow) it stretches further, all of it after
    the digests are already in hand. Run synchronously it strands the result
    behind a long, silent stall (the GUI looks frozen after the run is really
    done). With ``in_background`` the digests return immediately and the
    best-effort delete runs on a daemon thread; the files cost nothing to store,
    so losing the tail of the cleanup if the process exits is harmless.
    """
    if not file_ids:
        return
    if not in_background:
        delete_files(client, file_ids)
        return
    if on_log is not None:
        on_log(
            f"Releasing {len(file_ids)} uploaded file(s) in the background",
            level="muted",
        )

    def _do() -> None:
        delete_files(client, file_ids)
        _log.debug("background cleanup released %d uploaded file(s)", len(file_ids))

    _run_in_background(_do)


@dataclass
class _Slot:
    """One sheet's place in the page-ordered result, plus how it's being served."""

    index: int
    ref: SheetRef
    image_estimate: int
    # Set immediately for a cache hit or an upload failure (no batch item).
    digest: SheetDigest | None = None
    # Set when the sheet was uploaded and submitted as a batch item.
    custom_id: str | None = None
    cache_key: str | None = None
    file_ids: list[str] = field(default_factory=list)
    # The exact request params this slot was submitted with. Kept so a
    # retryable per-item failure can be resubmitted verbatim (the file_id
    # references stay valid until cleanup) without re-rendering or
    # re-uploading the sheet.
    params: dict | None = None


@dataclass
class DrawingBatch:
    """A submitted (or fully-cached) drawing batch, awaiting collection."""

    batch_id: str | None
    slots: list[_Slot]
    total: int

    @property
    def submitted_slots(self) -> list[_Slot]:
        return [s for s in self.slots if s.custom_id is not None]

    @property
    def all_file_ids(self) -> list[str]:
        return [fid for s in self.slots for fid in s.file_ids]


def _batch_item_error_text(result_obj: Any) -> str:
    """Human-readable error for a non-succeeded batch item (no repr noise)."""
    rtype = _get(result_obj, "type", "errored") or "errored"
    error = _get(result_obj, "error", None)
    if error is not None:
        inner = _get(error, "error", error)
        etype = str(_get(inner, "type", "") or "")
        emsg = str(_get(inner, "message", "") or "").strip()
        if emsg:
            return f"{etype}: {emsg}" if etype else emsg
    return f"batch request {rtype}"


# Batch-item error types that are PERMANENT: the request itself was rejected,
# so resubmitting the identical item can only fail the same way. Anything else
# on an ``errored`` item — ``api_error``, ``overloaded_error``, and whatever
# transient types the future brings — is a server-side blip the Batches docs
# call "safe to retry", and an ``expired`` item is explicitly "resubmit".
_PERMANENT_ITEM_ERROR_TYPES = frozenset(
    {
        "invalid_request_error",
        "authentication_error",
        "permission_error",
        "not_found_error",
        "request_too_large",
    }
)

# Output-cap ceiling for the empty-at-max_tokens resubmission. Batch items
# never stream, so the ~16k non-streaming-timeout rationale behind
# ``DEFAULT_DIGEST_MAX_TOKENS`` doesn't bind inside a batch; 64k stays within
# every whitelisted model's hard output ceiling, and output is billed by
# actual tokens, so the extra headroom costs nothing unless the sheet uses it.
# The direct-call rescue can carry this raised cap too because it STREAMS its
# request (see ``_rescue_failed_items_sync``) — the SDK refuses a plain
# non-streaming ``create`` whose cap implies >10 minutes of output (a
# client-side ValueError at ~21k tokens under the default timeout).
MAX_TOKENS_RETRY_CEILING = 64_000


def _item_retry_params(
    slot: _Slot,
    result_obj: Any,
    digest: SheetDigest | None,
    *,
    params: dict | None = None,
) -> dict | None:
    """The request params to resubmit this slot's failed item with, or ``None``.

    Three retryable shapes: an ``errored`` item whose error type is not a
    permanent request rejection (see ``_PERMANENT_ITEM_ERROR_TYPES``), an
    ``expired`` item, and a "succeeded" item whose digest came back EMPTY at
    ``stop_reason=max_tokens`` — adaptive thinking consumed the entire output
    budget before any digest text landed, so that one is resubmitted with the
    cap doubled to leave room for both the thinking and the digest.

    ``params`` is the request the item was LAST submitted with (defaults to
    ``slot.params``, the primary round's request). The empty-at-``max_tokens``
    doubling starts from it, so evaluating a follow-up-round failure keeps
    raising the cap (2x → 4x, bounded by :data:`MAX_TOKENS_RETRY_CEILING`)
    instead of re-proposing the exact cap that just came back empty.
    """
    params = slot.params if params is None else params
    if params is None:
        return None
    rtype = _get(result_obj, "type", None)
    if rtype == "expired":
        return params
    if rtype == "errored":
        error = _get(result_obj, "error", None)
        inner = _get(error, "error", error) if error is not None else None
        etype = str(_get(inner, "type", "") or "")
        return None if etype in _PERMANENT_ITEM_ERROR_TYPES else params
    if (
        rtype == "succeeded"
        and digest is not None
        and digest.error
        and not digest.text
        and digest.stop_reason == "max_tokens"
    ):
        old = int(params.get("max_tokens") or DEFAULT_DIGEST_MAX_TOKENS)
        return {**params, "max_tokens": min(old * 2, MAX_TOKENS_RETRY_CEILING)}
    return None


def _is_retryable_server_failure(result_obj: Any) -> bool:
    """True when a batch item's envelope is a retryable SERVER-side failure.

    ``expired`` items, and ``errored`` items whose error type is not a
    permanent request rejection (``api_error``, ``overloaded_error``, …).
    Narrower than :func:`_item_retry_params`, which also proposes a retry for
    the empty-at-``max_tokens`` "succeeded" shape — an item the backend
    *successfully processed*, and therefore evidence the backend is healthy
    rather than sick. The distinction is what lets the whole-batch-failed
    fast path tell "the Batches backend is down" apart from "thinking ate
    every output budget".
    """
    rtype = _get(result_obj, "type", None)
    if rtype == "expired":
        return True
    if rtype != "errored":
        return False
    error = _get(result_obj, "error", None)
    inner = _get(error, "error", error) if error is not None else None
    etype = str(_get(inner, "type", "") or "")
    return etype not in _PERMANENT_ITEM_ERROR_TYPES


def _rescue_reserve_seconds(max_elapsed_seconds: float) -> float:
    """The recovery slice held back from the primary poll's elapsed budget.

    ``min(``:data:`DEFAULT_RESCUE_RESERVE_SECONDS```, 25%)`` — enough for the
    direct-call rescue to make real progress after a batch that never
    terminates, without starving the poll on a small budget. Clamped at zero
    so a non-positive budget (tests force an immediate detach that way)
    passes through unchanged.
    """
    return max(0.0, min(DEFAULT_RESCUE_RESERVE_SECONDS, max_elapsed_seconds * 0.25))


def _cancel_batch(
    client: Any, batch_id: str, *, on_log: LogCallback | None = None
) -> bool:
    """Best-effort cancel of a batch this run has given up collecting.

    Canceling is the correct disposition for a stuck batch: its results will
    never be read (the run is about to digest the sheets directly), so left
    running it can only keep burning processing quota — and as long as it MAY
    still be running, the uploaded files it references cannot be released.
    Returns ``True`` when the API accepted the cancellation (the caller may
    then delete the uploaded files once the rescue is done); ``False`` leaves
    the remote batch presumed running, so the files stay retained for it.
    """
    try:
        client.messages.batches.cancel(batch_id)
    except Exception as exc:  # noqa: BLE001 - cancel is advisory; the rescue proceeds either way
        _log.warning("batch %s cancel failed: %s", batch_id, summarize_exc(exc))
        return False
    _log.info("batch %s canceled (this run will not collect it)", batch_id)
    if on_log is not None:
        on_log(f"Canceled remote batch {batch_id}")
    return True


def _rescue_failed_items_sync(
    rescue: list[tuple[_Slot, dict]],
    results: list,
    *,
    client: Any,
    cache: Any,
    sleep: Callable[[float], None],
    max_elapsed_seconds: float,
) -> int:
    """Digest still-failed batch items via synchronous Messages calls.

    The terminal recovery stage, for the one failure the follow-up batch cannot
    fix: the Batches backend itself erroring server-side. A real 8-sheet run
    watched every item fail with ``api_error: Internal Server Error`` in BOTH
    batch rounds while the same run's ~300 Files-API uploads had just succeeded
    — the batch backend was the sick component, and the follow-up batch rode it
    straight back into the same failure. Each still-retryable item is re-issued
    here as one synchronous, *streamed* Messages call
    (``client.beta.messages.stream``) carrying the item's exact request params
    (the uploaded ``file_id`` references are still alive — cleanup runs only
    after recovery), so batch processing is bypassed entirely. Costs the 50%
    batch discount for just the rescued sheets — the same trade the 404 inline
    fallback makes when the alternative is no result.

    Sequential and bounded by ``max_elapsed_seconds`` (the remainder of the
    collect budget). The bound is best-effort in the same sense as the batch
    poll loop's: it is re-checked before every call *and* before every retry
    backoff — never mid-call — so the worst overrun is one in-flight request
    (itself capped by the SDK's own timeout), and once the budget is spent no
    further sheet is attempted. Sheets not reached keep their batch error. A
    transient failure on a rescue call is retried with the real-time digest
    policy (:data:`~drawing_analyzer.digest.DEFAULT_DIGEST_MAX_RETRIES`,
    exponential backoff); a permanent one keeps that sheet's — fresher —
    batch error. Returns the number of sheets recovered.
    """
    started = time.monotonic()
    recovered = 0
    out_of_budget = False
    for pos, (slot, params) in enumerate(rescue):
        if out_of_budget or time.monotonic() - started >= max_elapsed_seconds:
            _log.warning(
                "direct-call rescue stopped by the collection budget: %d of %d "
                "sheet(s) not attempted",
                len(rescue) - pos, len(rescue),
            )
            break
        attempt = 0
        message = None
        while True:
            try:
                # Streamed rather than a plain ``create``: the rescue may
                # carry a raised max_tokens cap (up to
                # ``MAX_TOKENS_RETRY_CEILING``) for an empty-at-max_tokens
                # item, and the SDK refuses a non-streaming call whose cap
                # implies >10 minutes of output — a client-side ValueError,
                # before any HTTP request, at ~21k tokens under the default
                # timeout (some model overrides carry even lower non-streaming
                # caps). Streaming lifts that ceiling; ``get_final_message()``
                # returns the same Message shape ``create`` would have.
                with client.beta.messages.stream(
                    **params, betas=[FILES_API_BETA]
                ) as stream:
                    message = stream.get_final_message()
                break
            except Exception as exc:  # noqa: BLE001 - retried if transient; else the batch error stands
                if _is_transient_error(exc) and attempt < DEFAULT_DIGEST_MAX_RETRIES:
                    backoff = _retry_backoff_seconds(attempt)
                    remaining = max_elapsed_seconds - (time.monotonic() - started)
                    if backoff >= remaining:
                        # Sleeping would spend budget no remaining sheet has —
                        # this sheet keeps its batch error and the stage ends.
                        out_of_budget = True
                        _log.warning(
                            "direct-call rescue out of collection budget "
                            "mid-retry for %s (%s); keeping the batch error | %s",
                            slot.custom_id, slot.ref.display_label,
                            summarize_exc(exc),
                        )
                        break
                    _log.warning(
                        "direct-call rescue transient error, retry %d/%d in "
                        "%.0fs: %s (%s) | %s",
                        attempt + 1, DEFAULT_DIGEST_MAX_RETRIES, backoff,
                        slot.custom_id, slot.ref.display_label,
                        summarize_exc(exc),
                    )
                    sleep(backoff)
                    attempt += 1
                    continue
                _log.warning(
                    "direct-call rescue FAILED for %s (%s); keeping the batch "
                    "error | %s",
                    slot.custom_id, slot.ref.display_label, summarize_exc(exc),
                )
                break
        if message is None:
            continue  # the sheet keeps its batch-round error
        digest = _digest_from_message(slot, message, cache=cache)
        # Even an empty-digest result is fresher provenance than the batch
        # error it replaces, and its stop_reason names what happened.
        results[slot.index] = digest
        if digest.error is None:
            recovered += 1
            _log.info(
                "direct-call rescue ok: %s (%s) in=%d out=%d",
                slot.custom_id, slot.ref.display_label,
                digest.input_tokens, digest.output_tokens,
            )
        else:
            _log.warning(
                "direct-call rescue returned no digest for %s (%s): %s",
                slot.custom_id, slot.ref.display_label, digest.error,
            )
    return recovered


def _resubmit_failed_items(
    batch: DrawingBatch,
    results: list,
    raw: dict[str, Any],
    *,
    client: Any,
    cache: Any,
    progress: ProgressCallback | None,
    on_log: LogCallback | None,
    sleep: Callable[[float], None],
    max_elapsed_seconds: float,
) -> bool:
    """One follow-up batch for a collected batch's retryable per-item failures.

    A collected batch can carry failures that say nothing about the requests
    themselves: server-side ``api_error``/``overloaded_error`` blips,
    ``expired`` items, and the empty-at-``max_tokens`` digest. A real 33-sheet
    run lost 10 sheets to exactly these — every one resubmittable for free,
    because the sheet images stay uploaded until cleanup. This selects those
    items (via :func:`_item_retry_params`), resubmits them as one more batch
    reusing the same ``file_id`` references, polls it with the same policy as
    the primary batch, and fills the recovered digests into ``results``.

    ``max_elapsed_seconds`` is the REMAINDER of the caller's collection budget
    (the primary poll already spent the rest), so one ``collect`` call never
    blocks past the bound it was given. With less than one poll interval left
    the round is skipped outright — submitting a batch we won't wait for would
    only strand the uploaded files behind a detach.

    One follow-up *batch* only — and none at all when EVERY submitted item
    failed with a retryable server-side error, the signature of the Batches
    backend itself being down: a follow-up would ride the same sick backend
    into the same failure, so those runs go straight to the rescue. An item
    still failing retryably after the follow-up round (or a follow-up submit
    that itself errors) is likewise handed to the direct-call rescue
    (:func:`_rescue_failed_items_sync`): one synchronous Messages call per
    item, reusing the same params and still-uploaded ``file_id``s, so a
    Batches-backend outage no longer zeroes the run. A sheet the rescue can't
    recover keeps its (fresher) error rather than looping, so a systemic
    outage still ends with clean per-sheet errors.
    Returns ``True`` when the uploaded files are safe to delete afterwards;
    ``False`` when the follow-up batch detached (still running remotely, so it
    still needs the files — mirroring the primary batch's detach policy).
    """
    started = time.monotonic()

    def _rescue_remaining(items: list[tuple[_Slot, dict]]) -> None:
        """Run the direct-call rescue on whatever budget this round has left."""
        remaining = max_elapsed_seconds - (time.monotonic() - started)
        _log.info(
            "digesting %d still-failed batch item(s) via direct Messages calls",
            len(items),
        )
        if on_log is not None:
            on_log(
                f"Batch retries exhausted; digesting {len(items)} sheet(s) "
                "directly"
            )
        n = _rescue_failed_items_sync(
            items, results,
            client=client, cache=cache, sleep=sleep,
            max_elapsed_seconds=remaining,
        )
        _log.info("direct-call rescue recovered %d/%d sheet(s)", n, len(items))
        if on_log is not None:
            on_log(f"Recovered {n} of {len(items)} sheet(s) directly")

    retry: list[tuple[_Slot, dict]] = []
    server_failures = 0
    for slot in batch.submitted_slots:
        result_obj = _get(raw.get(slot.custom_id), "result")
        params = _item_retry_params(slot, result_obj, results[slot.index])
        if params is not None:
            retry.append((slot, params))
            if _is_retryable_server_failure(result_obj):
                server_failures += 1
    if not retry:
        return True

    # When EVERY item in the batch failed with a retryable server-side error,
    # the Batches backend itself is the sick component — a follow-up batch
    # would ride the same sick backend into the same failure (a real 8-sheet
    # run watched every item fail with ``api_error`` in BOTH rounds, wasting
    # ~10 minutes proving it). Skip the doomed round and digest directly.
    # An all-items empty-at-``max_tokens`` batch does NOT qualify: those
    # items were processed successfully, so the backend is healthy and the
    # follow-up batch (with raised caps, at the 50% discount) is the right
    # next step. Partial failures keep the follow-up too — blips on some
    # items while others succeeded say the backend is basically up.
    if server_failures == len(retry) == len(batch.submitted_slots):
        _log.warning(
            "all %d batch item(s) failed with retryable server-side errors; "
            "skipping the follow-up batch and digesting directly",
            len(retry),
        )
        if on_log is not None:
            on_log(
                f"Batch backend failed all {len(retry)} sheet(s); "
                "digesting them directly",
                level="warning",
            )
        _rescue_remaining(retry)
        return True

    if max_elapsed_seconds < DEFAULT_POLL_INTERVAL_SECONDS:
        _log.warning(
            "skipping follow-up batch for %d retryable item(s): collection "
            "budget exhausted (%.0fs remaining)",
            len(retry), max_elapsed_seconds,
        )
        return True

    _log.info("resubmitting %d failed batch item(s) in a follow-up batch", len(retry))
    if on_log is not None:
        on_log(f"Retrying {len(retry)} failed sheet(s) in a follow-up batch")
    reqs = [{"custom_id": s.custom_id, "params": p} for s, p in retry]
    try:
        mb = client.beta.messages.batches.create(requests=reqs, betas=[FILES_API_BETA])
    except Exception as exc:  # noqa: BLE001 - recovery is best-effort; unrescued errors stand
        # The batch backend rejecting even the submit is the strongest signal
        # yet that batch processing is the sick component — skip straight to
        # the direct-call rescue instead of giving up.
        _log.warning(
            "follow-up batch submit failed: %s; falling back to direct calls",
            summarize_exc(exc),
        )
        _rescue_remaining(retry)
        return True
    retry_id = _get(mb, "id")
    _log.info(
        "follow-up batch submitted: id=%s items=%d request_id=%s",
        retry_id, len(reqs), request_id_of(mb),
    )

    status = _poll_until_terminal(
        client,
        retry_id,
        total=batch.total,
        cached_done=max(0, batch.total - len(retry)),
        progress=progress,
        on_log=on_log,
        sleep=sleep,
        max_elapsed_seconds=max_elapsed_seconds,
        stall_timeout_seconds=DEFAULT_BATCH_STALL_TIMEOUT_SECONDS,
    )
    if status not in ("ended", "failed", "expired", "canceled"):
        if status in ("poll_failed", "stalled"):
            # Repeated retrieve failures, or a follow-up batch frozen with no
            # per-item progress, are themselves batch-backend-sick signals:
            # its results are unreachable (or never coming) from here, so
            # cancel it best-effort and recover what the budget allows via
            # the direct calls. Files are released only when the cancel
            # landed — an uncanceled batch may still be running and
            # referencing them.
            canceled = _cancel_batch(client, retry_id, on_log=on_log)
            if on_log is not None:
                on_log(
                    f"Follow-up batch {status} (id={retry_id}); "
                    "digesting the failed sheets directly",
                    level="warning",
                )
            _rescue_remaining(retry)
            return canceled
        # "detached": the poll spent the whole remaining collection budget,
        # so there is none left for a rescue either — keep the first-round
        # errors and the files (the remote batch is still running).
        if on_log is not None:
            on_log(
                f"Follow-up batch still running (id={retry_id}); "
                "keeping first-round errors",
                level="warning",
            )
        return False

    raw_retry: dict[str, Any] = {}
    for result in client.messages.batches.results(retry_id):
        raw_retry[_get(result, "custom_id")] = result
    recovered = 0
    rescue: list[tuple[_Slot, dict]] = []
    for slot, params in retry:
        res = raw_retry.get(slot.custom_id)
        if res is None:
            # No envelope for the item in the follow-up round. The first-round
            # error stands for now — but it was retryable (that is why the item
            # was resubmitted), so the direct-call rescue still gets a shot.
            rescue.append((slot, params))
            continue
        digest = _parse_item(slot, res, cache=cache)
        if digest.error is None:
            recovered += 1
        results[slot.index] = digest
        # An item still failing retryably after BOTH batch rounds is the batch
        # backend itself erroring — hand it to the direct-call rescue. Passing
        # the follow-up round's params keeps the empty-at-max_tokens cap
        # doubling cumulative instead of re-proposing the cap that just failed.
        again = _item_retry_params(
            slot, _get(res, "result"), digest, params=params
        )
        if again is not None:
            rescue.append((slot, again))
    _log.info(
        "follow-up batch recovered %d/%d failed sheet(s)", recovered, len(retry)
    )
    if on_log is not None:
        on_log(f"Recovered {recovered} of {len(retry)} failed sheet(s)")
    if rescue:
        _rescue_remaining(rescue)
    return True


def _normalize_status(status: Any) -> str:
    return str(status or "").replace("-", "_")


def _progressive_interval(elapsed: float) -> int:
    """Snappy while short, stretching toward the cap for a long-running batch."""
    base = DEFAULT_POLL_INTERVAL_SECONDS
    cap = DEFAULT_POLL_MAX_INTERVAL_SECONDS
    threshold = DEFAULT_POLL_BACKOFF_AFTER_SECONDS
    if elapsed <= threshold:
        return base
    progress = min(1.0, (elapsed - threshold) / max(1, threshold))
    return max(base, min(cap, int(base + (cap - base) * progress)))


def submit_drawing_batch(
    rendered_sheets,
    *,
    client: Any,
    model: str = REVIEW_MODEL_DEFAULT,
    max_tokens: int = DEFAULT_DIGEST_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_DIGEST_EFFORT,
    cache: Any = None,
    progress: ProgressCallback | None = None,
    total: int = 0,
    on_status: StatusCallback | None = None,
    focus: str | None = None,
) -> DrawingBatch:
    """Render-stream → cache-or-upload → submit one Message Batch.

    ``rendered_sheets`` is an iterable of :class:`RenderedSheet` (streamed, so at
    most one sheet's images are held at a time). Cache hits are recorded directly
    and skip both the upload and the batch; misses upload their images via the
    Files API and become one batch item. Returns a :class:`DrawingBatch` to hand
    to :func:`collect_drawing_batch`. ``batch_id`` is ``None`` when every sheet
    was cached (or failed to upload) — there is nothing to poll.

    ``focus`` (the optional per-run operator focus) rides on each item's system
    prompt — the uploaded images and user content are unchanged — and is folded
    into the cache key, so a focused run never reuses a no-focus digest and
    vice-versa.
    """
    focus = normalize_focus(focus)
    focus_fragment = focus_cache_fragment(focus)
    slots: list[_Slot] = []
    reqs: list[dict] = []

    # Upload circuit breaker. After MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES
    # sheets in a row fail with the same credential/route-level status, the
    # remaining sheets stop attempting the (doomed) upload:
    #   - 404 (Files API route down, Messages/Batches healthy) -> inline the
    #     images as base64 instead, via ``inline_fallback_active``. No sheet is
    #     lost; only the upload round-trips stop.
    #   - 401/403 (credential) -> ``uploads_disabled_error`` skips the sheet with
    #     a clear, actionable error, since an inline request would fail the same
    #     way. Cache hits are still served in either case — only uploads stop.
    fatal_streak = 0
    last_fatal_status: int | None = None
    uploads_disabled_error: str | None = None
    inline_fallback_active = False

    def _serve_inline(slot: _Slot, sheet) -> None:
        """Digest a sheet inline (base64, real-time) and resolve its slot.

        The Files-API upload route is unavailable, so the sheet's images ride
        inline in one synchronous vision request instead of being uploaded and
        referenced by ``file_id``. The result is attached straight to the slot
        (exactly like a cache hit), so the sheet never becomes a batch item —
        which also keeps the inline payload out of the 256 MB batch envelope —
        and :func:`collect_drawing_batch` resolves it with no special-casing.
        Reuses :func:`~drawing_analyzer.digest.digest_sheet`, so caching,
        transient-retry, and error capture match the real-time path; the only
        cost is forgoing the 50% batch discount for this sheet.
        """
        if on_status is not None:
            on_status(
                f"[{slot.index + 1}/{total}] Inlining {sheet.ref.display_label} "
                "(Files API unavailable)"
            )
        slot.digest = digest_sheet(
            sheet,
            client=client,
            model=model,
            max_tokens=max_tokens,
            use_thinking=use_thinking,
            effort=effort,
            cache=cache,
            focus=focus,
        )
        slots.append(slot)
        verb = "Inlined" if slot.digest.ok else "Inline digest failed for"
        _log.debug(
            "sheet %d served inline (Files API unavailable): %s",
            slot.index, sheet.ref.display_label,
        )
        if progress is not None:
            progress(slot.index + 1, total or 0, f"{verb} {sheet.ref.display_label}")

    for index, sheet in enumerate(rendered_sheets):
        image_est = estimate_image_tokens_total(sheet.image_sizes, model=model)
        slot = _Slot(index=index, ref=sheet.ref, image_estimate=image_est)

        cache_key: str | None = None
        if cache is not None:
            cache_key = digest_cache_key(
                sheet,
                model=model,
                prompt_version=DIGEST_PROMPT_VERSION,
                max_tokens=max_tokens,
                effort=effort,
                use_thinking=use_thinking,
                focus=focus_fragment,
                sheet_text=sheet.sheet_text,
            )
            hit = cache.get(cache_key)
            if hit is not None:
                slot.digest = SheetDigest(
                    ref=sheet.ref,
                    text=hit.get("text", ""),
                    input_tokens=int(hit.get("input_tokens", 0) or 0),
                    output_tokens=int(hit.get("output_tokens", 0) or 0),
                    image_token_estimate=image_est,
                    stop_reason=hit.get("stop_reason"),
                    error=None,
                    cached=True,
                )
                slots.append(slot)
                _log.debug("sheet %d cache hit: %s", index, sheet.ref.display_label)
                if progress is not None:
                    progress(index + 1, total or 0, f"Cached {sheet.ref.display_label}")
                continue

        # Files API confirmed unavailable (consecutive 404s already proved the
        # /v1/files route is down while Messages/Batches is healthy): inline this
        # sheet's images as base64 rather than attempt a doomed upload. Sits
        # after the cache check so cached sheets are still served for free.
        if inline_fallback_active:
            _serve_inline(slot, sheet)
            continue

        # Breaker tripped on a credential rejection (401/403): the same
        # rejection will hit every remaining upload, and an inline request would
        # fail identically, so mark the sheet (keeping the per-sheet report
        # complete) without spending more requests. Sits after the cache check
        # so cached sheets are still served even when the Files API is dead.
        if uploads_disabled_error is not None:
            slot.digest = SheetDigest(
                ref=sheet.ref,
                text="",
                image_token_estimate=image_est,
                error=uploads_disabled_error,
            )
            slots.append(slot)
            _log.debug(
                "sheet %d upload skipped (uploads disabled): %s",
                index, sheet.ref.display_label,
            )
            if progress is not None:
                progress(index + 1, total or 0, f"Upload skipped: {sheet.ref.display_label}")
            continue

        # Per-image status (status-line only) so a sheet's tens-of-seconds,
        # multi-image upload — and any transient-503 retry wave within it — shows
        # continuous motion instead of a frozen line. Built only when a status
        # sink is wired, so the no-callback path (and the tests) is unchanged.
        on_image = None
        if on_status is not None:
            def on_image(pos, n, retrying, *, _k=index + 1, _label=sheet.ref.display_label):
                verb = "Retrying" if retrying else "Uploading"
                tail = " after overload" if retrying else ""
                on_status(f"[{_k}/{total}] {verb} image {pos}/{n}{tail} — {_label}")

        try:
            upload = upload_sheet_images(client, sheet, on_image=on_image)
        except Exception as exc:  # noqa: BLE001 - one sheet's upload failing is captured, not fatal
            rid = request_id_of(exc)
            hint = upload_failure_hint(exc)
            status = run_fatal_upload_status(exc)

            # A Files-API 404 means the upload route is unavailable while the
            # Messages/Batches API (this batch's own transport) is healthy, so
            # inline this sheet's images as base64 rather than lose it. The
            # breaker still counts the consecutive 404s: once it trips, every
            # remaining sheet skips the doomed upload and goes straight to the
            # inline path above. No sheet is dropped — only the upload attempts
            # stop. (Cache hits never reach here, so they carry no signal.)
            if upload_failure_allows_inline_fallback(exc):
                _log.warning(
                    "sheet %d Files-API upload 404'd; inlining images as base64: "
                    "%s (%s)",
                    index, sheet.ref.display_label, summarize_exc(exc),
                )
                _serve_inline(slot, sheet)
                fatal_streak = fatal_streak + 1 if status == last_fatal_status else 1
                last_fatal_status = status
                if (
                    fatal_streak >= MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES
                    and not inline_fallback_active
                ):
                    inline_fallback_active = True
                    _log.warning(
                        "Files API unreachable after %d consecutive HTTP 404 "
                        "upload failure(s); inlining images as base64 for the "
                        "remaining sheets%s",
                        fatal_streak, f" — {hint}" if hint else "",
                    )
                continue

            # Credential-level (401/403) or non-fatal failure: capture it on the
            # sheet and continue. The request-id (when the SDK carried one) and
            # the actionable hint are surfaced on the sheet error so the GUI's
            # per-sheet line — not just the diagnostics file — names the exact
            # call to quote and what to check.
            error = f"image upload failed: {_clean_error(exc)}"
            if rid:
                error += f" (request-id {rid})"
            if hint:
                error += f" — {hint}"
            slot.digest = SheetDigest(
                ref=sheet.ref,
                text="",
                image_token_estimate=image_est,
                error=error,
            )
            slots.append(slot)
            _log.warning(
                "sheet %d upload failed (%s): %s",
                index, sheet.ref.display_label, summarize_exc(exc),
            )
            if progress is not None:
                progress(index + 1, total or 0, f"Upload failed: {sheet.ref.display_label}")

            # Breaker accounting: only an unbroken run of the SAME
            # credential/route-level status trips it; any other failure
            # (transient retries exhausted, payload-shaped 4xx) resets the
            # streak because it says nothing about the next sheet's fate.
            if status is None:
                fatal_streak = 0
                last_fatal_status = None
                continue
            fatal_streak = fatal_streak + 1 if status == last_fatal_status else 1
            last_fatal_status = status
            if fatal_streak >= MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES:
                uploads_disabled_error = (
                    f"image upload skipped: uploads stopped after {fatal_streak} "
                    f"consecutive HTTP {status} upload failures"
                )
                if hint:
                    uploads_disabled_error += f" — {hint}"
                _log.warning(
                    "disabling Files-API uploads for the remaining sheets after "
                    "%d consecutive HTTP %d failures (last: %s)",
                    fatal_streak, status, summarize_exc(exc),
                )
            continue

        # A successful upload proves the Files API is reachable with this key,
        # so any accumulated run-fatal streak was intermittent after all —
        # reset it, keeping the breaker true to its "consecutive" contract.
        # (Cache hits never reach here, so they carry no signal either way.)
        fatal_streak = 0
        last_fatal_status = None

        custom_id = f"sheet__{index}"
        slot.custom_id = custom_id
        slot.cache_key = cache_key
        slot.file_ids = upload.file_ids
        slot.params = build_digest_request_params(
            upload.content,
            model=model,
            max_tokens=max_tokens,
            use_thinking=use_thinking,
            effort=effort,
            focus=focus,
        )
        reqs.append({"custom_id": custom_id, "params": slot.params})
        slots.append(slot)
        _log.debug(
            "sheet %d uploaded %d image(s) as %s: %s",
            index, len(upload.file_ids), custom_id, sheet.ref.display_label,
        )
        if progress is not None:
            progress(index + 1, total or 0, f"Uploaded {sheet.ref.display_label}")

    batch_id: str | None = None
    if reqs:
        mb = client.beta.messages.batches.create(requests=reqs, betas=[FILES_API_BETA])
        batch_id = _get(mb, "id")
        # Record the batch id + the custom_id → sheet map up front. This is the
        # rosetta stone for reading the rest of the run: a later "item sheet__3
        # FAILED" line, or a lookup of the batch in the Anthropic console, maps
        # straight back to the human sheet label here.
        _log.info(
            "batch submitted: id=%s items=%d request_id=%s",
            batch_id, len(reqs), request_id_of(mb),
        )
        for s in slots:
            if s.custom_id is not None:
                _log.info(
                    "  %s -> %s (%d image file(s))",
                    s.custom_id, s.ref.display_label, len(s.file_ids),
                )

    return DrawingBatch(batch_id=batch_id, slots=slots, total=total or len(slots))


def _poll_until_terminal(
    client: Any,
    batch_id: str,
    *,
    total: int,
    cached_done: int,
    progress: ProgressCallback | None,
    on_log: LogCallback | None,
    sleep: Callable[[float], None],
    max_elapsed_seconds: float,
    stall_timeout_seconds: float | None = None,
) -> str:
    """Poll ``batch_id`` to a terminal state. Returns the status or a sentinel.

    Returns the terminal ``processing_status`` (``ended`` / ``failed`` / …), or
    ``"detached"`` when the elapsed bound is hit (the remote batch keeps running),
    or ``"poll_failed"`` after repeated retrieve errors, or ``"stalled"`` when
    ``stall_timeout_seconds`` is set and the batch's request counts have not
    moved at all for that long — the stuck-batch signature (two real batches
    sat at zero completions from submit straight to the 4h bound). Callers
    enable the stall watch only when they can recover the sheets another way;
    without recovery, giving up early would just lose them sooner.
    """
    started = time.monotonic()
    consecutive_errors = 0
    last_done = -1  # the first successful poll always registers as progress
    progressed_at = started
    while True:
        elapsed = time.monotonic() - started
        if elapsed > max_elapsed_seconds:
            _log.warning(
                "batch %s detached: still processing after %.1fh; remote batch "
                "left running (files retained)",
                batch_id, max_elapsed_seconds / 3600,
            )
            if on_log is not None:
                on_log(
                    f"Drawing batch still processing after "
                    f"{max_elapsed_seconds / 3600:.1f}h; id={batch_id}",
                    level="warning",
                )
            return "detached"
        try:
            batch = client.messages.batches.retrieve(batch_id)
            consecutive_errors = 0
        except Exception as exc:  # noqa: BLE001 - retried; terminal after the cap
            consecutive_errors += 1
            _log.warning(
                "batch %s poll error %d/%d: %s",
                batch_id, consecutive_errors, DEFAULT_MAX_CONSECUTIVE_POLL_ERRORS,
                summarize_exc(exc),
            )
            if consecutive_errors >= DEFAULT_MAX_CONSECUTIVE_POLL_ERRORS:
                _log.error("batch %s poll failed repeatedly; giving up", batch_id)
                if on_log is not None:
                    on_log(f"Drawing batch poll failed repeatedly: {exc}", level="error")
                return "poll_failed"
            sleep(min(DEFAULT_POLL_INTERVAL_SECONDS * (2**consecutive_errors), 300))
            continue

        counts = _get(batch, "request_counts")
        done_in_batch = sum(
            int(_get(counts, k, 0) or 0)
            for k in ("succeeded", "errored", "canceled", "expired")
        )
        status = _normalize_status(_get(batch, "processing_status"))
        _log.debug(
            "poll batch=%s status=%s succeeded=%s errored=%s canceled=%s "
            "expired=%s processing=%s elapsed=%.0fs",
            batch_id, status,
            _get(counts, "succeeded", 0), _get(counts, "errored", 0),
            _get(counts, "canceled", 0), _get(counts, "expired", 0),
            _get(counts, "processing", 0), elapsed,
        )
        if progress is not None:
            done = min(total, cached_done + done_in_batch)
            progress(done, total, f"Analyzing {done}/{total} sheet(s) — batch {status}")
        if status in ("ended", "failed", "expired", "canceled"):
            _log.info(
                "batch %s reached terminal status=%s after %.0fs",
                batch_id, status, elapsed,
            )
            return status
        if done_in_batch > last_done:
            last_done = done_in_batch
            progressed_at = time.monotonic()
        elif (
            stall_timeout_seconds is not None
            and time.monotonic() - progressed_at >= stall_timeout_seconds
        ):
            _log.warning(
                "batch %s stalled: no per-item progress in %.0f min "
                "(status=%s, %d item(s) done); giving up on this batch",
                batch_id, stall_timeout_seconds / 60, status, done_in_batch,
            )
            if on_log is not None:
                on_log(
                    f"Drawing batch has made no progress in "
                    f"{stall_timeout_seconds / 60:.0f} min; giving up on it "
                    f"(id={batch_id})",
                    level="warning",
                )
            return "stalled"
        sleep(_progressive_interval(elapsed))


def _digest_from_message(slot: _Slot, message: Any, *, cache: Any) -> SheetDigest:
    """Parse one Messages-API response into the slot's :class:`SheetDigest`.

    Shared by the batch item parse (:func:`_parse_item`) and the direct-call
    rescue (:func:`_rescue_failed_items_sync`), so a rescued digest is shaped —
    and cached, under the same key — exactly as if the batch had returned it.
    """
    text = _message_text(message)
    in_tok, out_tok = _message_usage(message)
    stop = _get(message, "stop_reason")
    error = None if text else f"empty digest (stop_reason={stop!r})"
    if cache is not None and slot.cache_key and error is None and text:
        cache.put(
            slot.cache_key,
            {
                "text": text,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "stop_reason": stop,
                "created_ts": time.time(),
            },
        )
    return SheetDigest(
        ref=slot.ref,
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        image_token_estimate=slot.image_estimate,
        stop_reason=stop,
        error=error,
    )


def _parse_item(slot: _Slot, result: Any, *, cache: Any) -> SheetDigest:
    """Turn one batch result envelope into the sheet's :class:`SheetDigest`."""
    if result is None:
        _log.warning(
            "item %s (%s): batch returned no result envelope",
            slot.custom_id, slot.ref.display_label,
        )
        return SheetDigest(
            ref=slot.ref,
            text="",
            image_token_estimate=slot.image_estimate,
            error="batch returned no result for this sheet",
        )
    rr = _get(result, "result")
    if _get(rr, "type") != "succeeded":
        # A per-item failure inside the batch (e.g. an `api_error` 500 on one
        # sheet while the rest succeed). Log the result type + cleaned error so
        # the cause is attributable to the sheet, not just "3 failed".
        item_error = _batch_item_error_text(rr)
        _log.warning(
            "item %s (%s) FAILED: result_type=%s detail=%s",
            slot.custom_id, slot.ref.display_label,
            _get(rr, "type", "errored"), item_error,
        )
        return SheetDigest(
            ref=slot.ref,
            text="",
            image_token_estimate=slot.image_estimate,
            error=item_error,
        )
    message = _get(rr, "message")
    digest = _digest_from_message(slot, message, cache=cache)
    if digest.error is not None:
        _log.warning(
            "item %s (%s): empty digest (stop_reason=%r)",
            slot.custom_id, slot.ref.display_label, digest.stop_reason,
        )
    else:
        _log.debug(
            "item %s (%s) ok: in=%d out=%d stop=%s request_id=%s",
            slot.custom_id, slot.ref.display_label, digest.input_tokens,
            digest.output_tokens, digest.stop_reason, request_id_of(message),
        )
    return digest


def collect_drawing_batch(
    batch: DrawingBatch,
    *,
    client: Any,
    cache: Any = None,
    progress: ProgressCallback | None = None,
    on_log: LogCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_elapsed_seconds: int = DEFAULT_BATCH_MAX_ELAPSED_SECONDS,
    cleanup_in_background: bool = False,
    retry_failed_items: bool = False,
) -> list[SheetDigest]:
    """Poll the batch to completion and assemble per-sheet digests in page order.

    Cache hits / upload failures are already resolved on their slots. Submitted
    items are polled, collected, parsed, and (on success) written to the cache;
    the uploaded files are then deleted. ``cleanup_in_background`` runs that final
    delete on a daemon thread so the digests return immediately instead of
    stalling behind a long, silent file-by-file cleanup (see
    :func:`_release_uploaded_files`); left ``False`` (the default) the delete is
    synchronous, which the unit tests rely on. If the batch can't be collected
    (detached past the elapsed bound, or repeated poll failures) the uploaded
    files are **left in place** (the remote batch may still be running and needs
    them) and each submitted sheet is marked with a clear, retriable error.

    ``retry_failed_items`` resubmits the collected batch's retryable per-item
    failures (server-side ``api_error``/``overloaded_error``, ``expired``
    items, and the empty-at-``max_tokens`` digest) as ONE follow-up batch
    before cleanup, while the same uploaded ``file_id`` references are still
    valid — see :func:`_resubmit_failed_items` (which skips straight to the
    direct calls when every item failed server-side — the Batches backend
    itself being down). Items still failing retryably after that round are
    then digested via synchronous per-item Messages calls reusing the same
    params and ``file_id``s (:func:`_rescue_failed_items_sync`).

    ``retry_failed_items`` also covers the batch never terminating at all —
    the failure that used to return an entire run of "not collected" errors
    after the full elapsed bound. The primary poll then holds back a rescue
    reserve from ``max_elapsed_seconds`` (:func:`_rescue_reserve_seconds`)
    and watches for a stall (no per-item progress for
    :data:`DEFAULT_BATCH_STALL_TIMEOUT_SECONDS`); a batch that stalls,
    detaches, or can't be polled is best-effort canceled and every submitted
    sheet digested through the same direct-call rescue, with the uploaded
    files released only when the cancel landed. All recovery stages run
    within this call's ``max_elapsed_seconds`` budget, so opting in never
    lets a collect block meaningfully past the bound it was given. The
    pipeline opts in; direct callers and the unit tests keep the
    single-round default.
    """
    # Size by the actual slot count (one slot per rendered sheet, indices
    # 0..n-1 in page order) so a divergent display ``total`` can never
    # mis-size or drop a result.
    results: list[SheetDigest | None] = [None] * len(batch.slots)
    for slot in batch.slots:
        if slot.digest is not None:
            results[slot.index] = slot.digest

    submitted = batch.submitted_slots
    if batch.batch_id and submitted:
        cached_done = sum(1 for s in batch.slots if s.digest is not None)
        collect_started = time.monotonic()
        # With recovery enabled, hold back a slice of the budget from the
        # poll — so a batch that never terminates leaves the direct-call
        # rescue room to run — and watch for a stalled batch (request counts
        # frozen for an hour). Without recovery there is nothing useful to do
        # earlier, so the poll keeps the whole bound and only the elapsed
        # detach applies, exactly as before.
        poll_budget: float = max_elapsed_seconds
        stall_timeout: float | None = None
        if retry_failed_items:
            poll_budget = max_elapsed_seconds - _rescue_reserve_seconds(
                max_elapsed_seconds
            )
            stall_timeout = DEFAULT_BATCH_STALL_TIMEOUT_SECONDS
        status = _poll_until_terminal(
            client,
            batch.batch_id,
            total=batch.total,
            cached_done=cached_done,
            progress=progress,
            on_log=on_log,
            sleep=sleep,
            max_elapsed_seconds=poll_budget,
            stall_timeout_seconds=stall_timeout,
        )
        if status in ("ended", "failed", "expired", "canceled"):
            raw = {}
            for result in client.messages.batches.results(batch.batch_id):
                raw[_get(result, "custom_id")] = result
            for slot in submitted:
                results[slot.index] = _parse_item(
                    slot, raw.get(slot.custom_id), cache=cache
                )
            files_released = True
            if retry_failed_items:
                # The follow-up round spends what's LEFT of this call's
                # collection budget — the bound the caller gave applies to
                # the whole collect, not per batch round.
                remaining = max_elapsed_seconds - (time.monotonic() - collect_started)
                files_released = _resubmit_failed_items(
                    batch, results, raw,
                    client=client, cache=cache, progress=progress,
                    on_log=on_log, sleep=sleep,
                    max_elapsed_seconds=remaining,
                )
            if files_released:
                _release_uploaded_files(
                    client,
                    batch.all_file_ids,
                    in_background=cleanup_in_background,
                    on_log=on_log,
                )
        else:
            # The batch never reached a terminal state: request counts frozen
            # past the stall window ("stalled"), the poll bound hit
            # ("detached"), or the poll endpoint failing repeatedly
            # ("poll_failed"). This is the failure that used to zero a run —
            # two real runs (50 and 20 sheets) sat `in_progress` with zero
            # completions for 4h and returned nothing, despite every upload
            # and request in hand being valid. With recovery enabled the
            # batch is abandoned for good: best-effort canceled (its results
            # will never be read, so left running it only burns quota) and
            # every unresolved sheet digested via the direct-call rescue on
            # the same still-uploaded file_ids, spending what remains of the
            # collection budget (the poll held back a rescue reserve for
            # exactly this). Without recovery the original behavior stands:
            # files retained for the still-running batch, and a clear,
            # retriable per-sheet error.
            canceled = False
            if retry_failed_items:
                canceled = _cancel_batch(client, batch.batch_id, on_log=on_log)
                rescue = [
                    (slot, slot.params)
                    for slot in submitted
                    if results[slot.index] is None and slot.params is not None
                ]
                if rescue:
                    remaining = max_elapsed_seconds - (
                        time.monotonic() - collect_started
                    )
                    _log.info(
                        "digesting %d sheet(s) from the %s batch via direct "
                        "Messages calls (%.0fs of collection budget left)",
                        len(rescue), status, max(0.0, remaining),
                    )
                    if on_log is not None:
                        on_log(
                            f"Drawing batch {status}; digesting "
                            f"{len(rescue)} sheet(s) directly"
                        )
                    n = _rescue_failed_items_sync(
                        rescue, results,
                        client=client, cache=cache, sleep=sleep,
                        max_elapsed_seconds=remaining,
                    )
                    _log.info(
                        "direct-call rescue recovered %d/%d sheet(s) from "
                        "the %s batch", n, len(rescue), status,
                    )
                    if on_log is not None:
                        on_log(f"Recovered {n} of {len(rescue)} sheet(s) directly")
            tail = (
                f"remote batch id={batch.batch_id} was canceled"
                if canceled
                else f"remote batch id={batch.batch_id} may still be running"
            )
            for slot in submitted:
                if results[slot.index] is None:
                    results[slot.index] = SheetDigest(
                        ref=slot.ref,
                        text="",
                        image_token_estimate=slot.image_estimate,
                        error=f"drawing batch not collected ({status}); {tail}",
                    )
            if canceled:
                # The canceled batch can no longer need the uploaded files,
                # and anything the rescue produced is already in hand.
                _release_uploaded_files(
                    client,
                    batch.all_file_ids,
                    in_background=cleanup_in_background,
                    on_log=on_log,
                )

    ref_by_index = {s.index: s.ref for s in batch.slots}
    for i, digest in enumerate(results):
        if digest is None:  # defensive — every slot resolves above
            _log.error("slot %d produced no digest result (defensive backfill)", i)
            results[i] = SheetDigest(
                ref=ref_by_index.get(i, batch.slots[0].ref if batch.slots else None),
                text="",
                error="sheet produced no digest result",
            )

    final = [r for r in results if r is not None]
    ok = sum(1 for r in final if r.error is None and (r.text or "").strip())
    _log.info(
        "batch collect done: %d/%d sheet(s) ok, %d failed (batch id=%s)",
        ok, len(final), len(final) - ok, batch.batch_id,
    )
    return final
