"""Files-API transport for the per-sheet drawing digest.

A single sheet carries 1 overview + N tiles (37 images for the default 6x6
grid). Inlining those as base64 in one Messages request pushes the body past
Anthropic's **32 MB request-size limit** for a dense E-size sheet, which the API
rejects with HTTP 400 — the failure that made every sheet in a permit set fail
at once. Per Anthropic's vision guidance ("For many images, consider uploading
with the Files API and referencing by ``file_id`` to keep request payloads
small"), the fix is to upload each image once and reference it by ``file_id`` so
the request body stays tiny. The same file-id references ride into the Message
Batches API for the 50% batch discount, and the batch's 256 MB envelope is never
approached because each item body is just a handful of ids.

Uploaded files persist until deleted and count against the organization's
100 GB storage cap. Each successful upload is recorded locally before use;
parallel, retrying cleanup and a startup reaper reclaim interrupted runs.
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

from .diagnostics import get_logger, summarize_exc
from . import resource_pressure
from .digest import (
    _error_status,
    _is_transient_error,
    _is_transient_status_error,
    _retry_backoff_seconds,
    build_user_content_blocks,
)
from .models import ImageTile, RenderedSheet

_log = get_logger()

# App-level retries for a single Files-API image upload, layered ON TOP of the
# SDK's own per-call retries — same rationale as the per-sheet digest (see
# digest.py). Under load the Files API returns a transient
# ``503 overloaded_error`` ("File storage is temporarily unavailable. Please
# retry."); without a retry here a single such 503 on any one of a sheet's ~37
# images failed the *entire* sheet (and discarded every image already uploaded
# for it), which is how a brief overload wave took out more than half a set.
# A sheet fans out to many more uploads than the digest's one vision call, so
# the chance of hitting at least one transient blip is correspondingly higher —
# hence a deeper budget than ``DEFAULT_DIGEST_MAX_RETRIES``. The backoff (2s, 4s,
# 8s, 16s) rides through the wave; kept bounded so a genuine outage still ends
# with a clean per-sheet error rather than hanging. Only transient *status*
# rejections are retried here (see ``_is_transient_status_error``); ambiguous
# connection/timeout errors are left to the SDK's idempotent internal retries so
# a lost response can't orphan an already-stored file.
DEFAULT_UPLOAD_MAX_RETRIES = 4

# A sheet's ~37 image uploads are independent and each blocks on network round
# trips, so they run on a small pool instead of one-at-a-time — the dominant
# batch-path latency after rendering. Kept modest (default 6) to be a courteous
# Files-API client under the same overload the retry budget exists for.
# Overridable via ``DRAWING_ANALYZER_UPLOAD_WORKERS``. Parallelism changes only
# *scheduling*: each image keeps the exact same retry taxonomy (transient status
# rejections re-issued here; ambiguous connection/timeout left to the SDK's
# idempotent retries), so a lost response still can't orphan a stored file.
DEFAULT_UPLOAD_WORKERS = 6
_UPLOAD_WORKERS_ENV = "DRAWING_ANALYZER_UPLOAD_WORKERS"

DEFAULT_DELETE_WORKERS = 6
DEFAULT_DELETE_MAX_RETRIES = 4
# A batch may need its images for 24h after submission. Allow another hour
# for clock skew/status propagation, including later batches reusing the IDs.
UPLOAD_REAP_MIN_AGE_SECONDS = 25 * 60 * 60
_TERMINAL_BATCH_STATUSES = frozenset({"ended", "failed", "expired", "canceled"})
_reaper_lock = threading.Lock()
_active_reaper_stores: set[Any] = set()


def _resolve_upload_workers(image_count: int, override: int | None = None) -> int:
    """Concurrency for one sheet's uploads: explicit ``override`` wins, else the
    ``DRAWING_ANALYZER_UPLOAD_WORKERS`` env, else the default — then clamped to
    ``[1, image_count]`` (never more workers than images)."""
    if override is not None:
        workers = override
    else:
        workers = DEFAULT_UPLOAD_WORKERS
        raw = os.environ.get(_UPLOAD_WORKERS_ENV)
        if raw and raw.strip().isdigit():
            workers = int(raw.strip())
    return max(1, min(workers, max(1, image_count)))

# Statuses that doom every Files-API upload in the run, not just this sheet's.
# 401/403 (key rejected / key lacking Files-API permission) and 404 (the
# /v1/files route itself not resolving) are credential- or route-level
# rejections shared by every upload the run will make — they don't depend on
# the payload, so once seen, each remaining upload is guaranteed to fail
# identically. The submit loop uses this to stop attempting uploads after a few
# consecutive such failures (a real 33-sheet run burned ~2 minutes failing
# every sheet one 404 at a time). Payload-shaped 4xx (400 invalid image, 413
# too large) are deliberately NOT here: one bad sheet must not disable the
# rest of the run.
RUN_FATAL_UPLOAD_STATUSES = frozenset({401, 403, 404})

# Of the run-fatal statuses, the one for which an inline-base64 fallback is a
# viable substitute. A 404 means the /v1/files *route* is unavailable while the
# Messages/Batches API — the digest batch's own transport — is healthy, so the
# sheet's images can ride inline as base64 in a normal vision request instead of
# being uploaded and referenced by ``file_id``. A 401/403 is a credential-level
# rejection an inline request would hit identically, so those keep the
# stop-and-skip behavior; only 404 routes to the fallback.
INLINE_FALLBACK_UPLOAD_STATUSES = frozenset({404})

# Operator-facing diagnosis per run-fatal status. The 404 text exists because
# the per-request error ("HTTP 404: Not found") is uniquely unhelpful there.
# The Files API is GA (``client.files.upload``, no beta header) and the pinned
# SDK posts straight to ``/v1/files``, and the call still comes back with an
# Anthropic ``request_id`` — so a 404 there is the server declining the route,
# not a malformed request. In practice that is the Files API not being enabled
# for the key/workspace, an ``ANTHROPIC_BASE_URL``/proxy override that doesn't
# forward /v1/files, or a different installed ``anthropic`` package than the
# pinned one. The run no longer dies on it — it inlines the images as base64
# instead (see ``INLINE_FALLBACK_UPLOAD_STATUSES``) — but the diagnosis is still
# logged so the underlying misconfiguration stays visible.
_RUN_FATAL_UPLOAD_HINTS = {
    401: "the API key was rejected — re-enter or rotate the key",
    403: "the API key/workspace lacks permission for the Files API",
    404: (
        "the Files API is not answering /v1/files for this key — most often it "
        "is not enabled on the workspace, or an ANTHROPIC_BASE_URL/proxy "
        "override is not forwarding /v1/files, or the installed anthropic SDK "
        "differs from the pinned version"
    ),
}


def run_fatal_upload_status(exc: Exception) -> int | None:
    """The HTTP status of a run-fatal upload rejection, else ``None``.

    "Run-fatal" means credential- or route-level (see
    :data:`RUN_FATAL_UPLOAD_STATUSES`): the same rejection will hit every
    remaining upload in the run, so the caller may stop attempting them.
    """
    status = _error_status(exc)
    return status if status in RUN_FATAL_UPLOAD_STATUSES else None


def upload_failure_hint(exc: Exception) -> str | None:
    """An actionable diagnosis for a run-fatal upload rejection, else ``None``."""
    status = run_fatal_upload_status(exc)
    return _RUN_FATAL_UPLOAD_HINTS.get(status) if status is not None else None


def upload_failure_allows_inline_fallback(exc: Exception) -> bool:
    """Whether a failed upload can be served by inlining the image as base64.

    True only for a Files-API 404 (see :data:`INLINE_FALLBACK_UPLOAD_STATUSES`):
    the upload route is unavailable but the Messages/Batches API still works, so
    the sheet is digested inline instead of lost. A credential-level 401/403
    would fail an inline request the same way, so it is *not* inline-eligible —
    the caller keeps the stop-and-skip behavior for those.
    """
    return _error_status(exc) in INLINE_FALLBACK_UPLOAD_STATUSES


def _file_image_block(file_id: str) -> dict:
    """A content block referencing a previously-uploaded image by ``file_id``."""
    return {"type": "image", "source": {"type": "file", "file_id": file_id}}


def _uploaded_id(uploaded: Any) -> str:
    """Read the id off an SDK ``FileObject`` (attr) or a plain-dict variant."""
    if isinstance(uploaded, dict):
        return str(uploaded.get("id", ""))
    return str(getattr(uploaded, "id", ""))


@dataclass
class SheetUpload:
    """One sheet's images uploaded to the Files API.

    ``content`` is the user-turn content (file-id image blocks in the same order
    and with the same labels/framing as the inline-base64 path); ``file_ids`` is
    every uploaded id, for post-collection cleanup.
    """

    content: list[dict]
    file_ids: list[str] = field(default_factory=list)


def retask_uploaded_content(content: list[dict], task_instruction: str) -> list[dict]:
    """Return uploaded-sheet content with only its final instruction replaced.

    Digest and critique deliberately share the same framing, text layer, image
    order, labels, and uploaded ``file_id`` references.  Reusing an upload across
    those stages therefore requires changing only the final text block.  The
    input list and its blocks are never mutated, which keeps any in-flight digest
    request byte-stable.
    """
    blocks = list(content)
    replacement = {"type": "text", "text": str(task_instruction)}
    if blocks and blocks[-1].get("type") == "text":
        blocks[-1] = replacement
    else:
        # Defensive compatibility for a custom uploader that omitted the
        # closing task.  The standard builder always takes the replacement path.
        blocks.append(replacement)
    return blocks


@dataclass
class ReusableSheetUpload:
    """A run-local uploaded sheet whose file IDs can serve a later stage.

    Ownership is explicit: the manifest that holds this object must either
    release ``file_ids`` itself or transfer them to a submitted critique batch.
    The class contains no API client and performs no cleanup on destruction.
    """

    ref: Any
    rows: int
    cols: int
    content: list[dict]
    file_ids: list[str] = field(default_factory=list)
    # Content-addressed digest key, available to direct critique callers that
    # have no pipeline level-1 key. Never use remote file IDs as cache identity.
    digest_cache_key: str | None = None
    _owns_cleanup: bool = field(default=True, init=False, repr=False)
    _ownership_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    def content_for(self, task_instruction: str) -> list[dict]:
        return retask_uploaded_content(self.content, task_instruction)

    @property
    def available(self) -> bool:
        """Whether this manifest still owns IDs that may be transferred."""
        with self._ownership_lock:
            return self._owns_cleanup and bool(self.file_ids)

    def transfer(self, task_instruction: str) -> SheetUpload | None:
        """Atomically transfer cleanup ownership to one later-stage request.

        The returned :class:`SheetUpload` owns the IDs.  A second transfer (or a
        transfer after :meth:`release_ids`) returns ``None``, preventing two
        stages from independently deleting or submitting the same ownership.
        """
        with self._ownership_lock:
            if not self._owns_cleanup or not self.file_ids:
                return None
            transferred = SheetUpload(
                content=self.content_for(task_instruction),
                file_ids=list(self.file_ids),
            )
            self._owns_cleanup = False
            return transferred

    def release_ids(self) -> list[str]:
        """Take still-owned IDs for deletion, at most once."""
        with self._ownership_lock:
            if not self._owns_cleanup:
                return []
            self._owns_cleanup = False
            return list(self.file_ids)


def iter_prefetched_sheets(
    rendered_sheets: Iterable[RenderedSheet],
) -> Iterator[RenderedSheet]:
    """Render one sheet ahead while the caller uploads the current sheet.

    The source iterator is advanced only by one dedicated worker, so a PDF
    renderer is never shared across threads.  Before yielding the current sheet,
    the worker starts advancing to the next one; the caller's existing sequential
    cache/upload/circuit-breaker logic therefore runs unchanged while that render
    proceeds.  One yielded sheet plus one in-flight/ready sheet is the hard memory
    bound, and source order is preserved exactly.
    """
    iterator = iter(rendered_sheets)

    def _advance() -> tuple[bool, RenderedSheet | None]:
        try:
            return False, next(iterator)
        except StopIteration:
            return True, None

    def _close_source() -> None:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()

    with ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="sheet-render", **resource_pressure.worker_binding(),
    ) as executor:
        future = executor.submit(_advance)
        try:
            while True:
                exhausted, sheet = future.result()
                if exhausted:
                    return
                # Schedule exactly one lookahead before handing the current sheet to
                # the upload loop.  ``future.result`` above also propagates a source
                # render exception with its original traceback.
                future = executor.submit(_advance)
                assert sheet is not None
                yield sheet
        finally:
            # If upload/cache work aborts early, let the single lookahead finish
            # (or cancel it before it starts), then finalize the renderer iterator
            # on this same dedicated worker. PyMuPDF documents opened inside the
            # source generator are therefore never closed from the caller thread.
            future.cancel()
            try:
                future.result()
            except BaseException:
                pass
            try:
                executor.submit(_close_source).result()
            except Exception as exc:  # noqa: BLE001 - preserve the caller's error
                _log.warning("render source cleanup failed: %s", summarize_exc(exc))


def _safe_stem(sheet: RenderedSheet) -> str:
    raw = sheet.ref.display_label
    return "".join(c if c.isalnum() else "_" for c in raw)[:60] or "sheet"


# ``on_image(position, total_images, retrying)`` — called once per image as a
# sheet uploads: with ``retrying=False`` after each image lands, and with
# ``retrying=True`` just before a transient-503 backoff. A sheet's 37-image
# upload otherwise takes tens of seconds with no signal, so surfacing this lets a
# GUI keep its status line alive (and *show* an overload wave being ridden out)
# instead of looking frozen. Diagnostics-only by nature, so it never affects the
# upload result.
ImageProgress = Callable[[int, int, bool], None]


def upload_sheet_images(
    client: Any,
    sheet: RenderedSheet,
    *,
    max_retries: int = DEFAULT_UPLOAD_MAX_RETRIES,
    max_workers: int | None = None,
    sleep: Any = time.sleep,
    on_image: ImageProgress | None = None,
    task_instruction: str | None = None,
    cache: Any = None,
) -> SheetUpload:
    """Upload a sheet's overview + tiles via the Files API; build file-id content.

    Returns the user-turn content blocks (image-by-file_id, identical framing to
    the base64 path via :func:`~drawing_analyzer.digest.build_user_content_blocks`)
    plus the uploaded ``file_id``s for cleanup. Raises on an upload failure; the
    caller treats the sheet as failed and attempts to delete every uploaded id.
    Each successful upload is synchronously journaled in the batch recovery
    store so crashes and failed cleanup can be revisited at startup.

    ``task_instruction`` overrides the closing instruction of the assembled
    content (default: the digest task). The critique batch path (Phase 23C) passes
    its own closing instruction so one shared per-sheet upload can feed BOTH the
    critique's self-consistency reads by ``file_id`` — the reviewer sees the exact
    same imagery/text framing the digest saw and differs only in what it is asked
    to produce.

    The images upload concurrently on a small pool (:data:`DEFAULT_UPLOAD_WORKERS`,
    env-overridable; ``max_workers=1`` forces the old sequential order). This
    changes only *scheduling* — each image keeps the exact same retry taxonomy:
    a transient *status* rejection
    (:func:`~drawing_analyzer.digest._is_transient_status_error` — the Files-API
    ``503 overloaded_error`` among them) is re-issued here up to ``max_retries``
    times with exponential backoff, so a blip on one of a sheet's ~37 uploads no
    longer discards the images already uploaded for that sheet; while connection /
    timeout errors are deliberately *not* re-issued here (the server may have
    already stored the file before the response was lost, so a fresh upload could
    orphan it) — those are left to the SDK's idempotent internal retries.
    ``sleep`` is injectable so tests don't wait; a permanent failure (or exhausted
    retries) re-raises for the caller to capture as a failed sheet. On the first
    failure, every image that *did* upload is queued for retrying deletion;
    any IDs whose deletion fails remain recorded for the reaper.

    Progress callbacks are throttled to completion events: ``on_image`` fires once
    as each image lands (and once per transient-retry wave), carrying a coherent
    running completed-count so a concurrent upload's status line stays sensible.
    """
    from .batch_recovery import recovery_cache

    store = recovery_cache(cache)
    # Refuse uploads when ownership cannot be read durably.
    store.recorded_uploads()
    stem = _safe_stem(sheet)
    label = sheet.ref.display_label
    total_images = 1 + len(sheet.tiles)

    jobs: list[tuple[int, ImageTile, str]] = [(0, sheet.overview, f"{stem}-overview.png")]
    for i, tile in enumerate(sheet.tiles, start=1):
        jobs.append((i, tile, f"{stem}-r{tile.row + 1}c{tile.col + 1}.png"))

    lock = threading.Lock()
    completed = 0
    uploaded_ids: list[str] = []
    # Once any image fails for good, queued uploads short-circuit instead of
    # hammering the API for a sheet that is already doomed.  Workers already in
    # the Files API may finish; their IDs are collected and deleted below.
    aborted = threading.Event()

    def _notify(retrying: bool) -> None:
        # Called under ``lock`` so the completed-count it reports is coherent.
        if on_image is not None:
            on_image(completed, total_images, retrying)

    def _upload_one(position: int, image: ImageTile, name: str) -> tuple[int, str | None]:
        nonlocal completed
        attempt = 0
        while True:
            if aborted.is_set():
                return position, None
            try:
                uploaded = client.files.upload(
                    file=(name, image.png_bytes, "image/png")
                )
                break
            except Exception as exc:  # noqa: BLE001 - retried if transient, else re-raised
                # A Files-API 503 "overloaded"/"temporarily unavailable" is the
                # transient *status* failure that doomed whole sheets one image
                # at a time; re-attempt it with backoff (the SDK's own retries
                # weren't enough to ride a sustained overload wave) before giving
                # up on the sheet. Only status rejections are retried: a 503 means
                # the upload was cleanly rejected, so re-issuing is safe — whereas
                # a connection/timeout is ambiguous (the file may already be
                # stored) and re-issuing it as a fresh upload could orphan that
                # first file, so those are left to the SDK's idempotent retries.
                if _is_transient_status_error(exc) and attempt < max_retries:
                    backoff = _retry_backoff_seconds(attempt)
                    _log.warning(
                        "files-api upload transient error, retry %d/%d in %.0fs: "
                        "sheet=%s image=%s (#%d/%d, %d bytes) | %s",
                        attempt + 1, max_retries, backoff, label, name,
                        position + 1, total_images, len(image.png_bytes),
                        summarize_exc(exc),
                    )
                    # A 503 "overloaded" wave on the Files API is capacity
                    # starvation too; the run's resource record counts it.
                    resource_pressure.note_api_retry(
                        exc, stage="upload", attempt=attempt + 1, backoff_seconds=backoff,
                    )
                    with lock:
                        _notify(True)
                    sleep(backoff)
                    attempt += 1
                    continue
                if _is_transient_status_error(exc):
                    resource_pressure.note_api_give_up(exc, stage="upload", attempts=attempt + 1)
                # Permanent, or transient retries exhausted: pinpoint the exact
                # image (overview vs which tile), its size, and the API status /
                # request-id so the failure that doomed this sheet is fully
                # attributable after the fact.
                _log.warning(
                    "files-api upload FAILED: sheet=%s image=%s (#%d/%d, %d bytes) | %s",
                    label, name, position + 1, total_images,
                    len(image.png_bytes), summarize_exc(exc),
                )
                aborted.set()
                raise
        fid = _uploaded_id(uploaded)
        if not fid:
            aborted.set()
            raise ValueError("Files API upload returned no file id")
        with lock:
            uploaded_ids.append(fid)
        try:
            store.record_uploaded_file(fid)
        except Exception:
            aborted.set()
            raise
        with lock:
            completed += 1
            _log.debug(
                "files-api upload ok: sheet=%s image=%s (#%d/%d) file_id=%s",
                label, name, completed, total_images, fid,
            )
            _notify(False)
        return position, fid

    _log.debug("uploading %d image(s) for sheet=%s", total_images, label)
    workers = _resolve_upload_workers(total_images, max_workers)
    by_position: dict[int, str] = {}
    error: Exception | None = None
    with ThreadPoolExecutor(max_workers=workers, **resource_pressure.worker_binding()) as executor:
        futures = {
            executor.submit(_upload_one, pos, image, name): pos
            for pos, image, name in jobs
        }
        for future in as_completed(futures):
            try:
                pos, fid = future.result()
                if fid is not None:
                    by_position[pos] = fid
            except Exception as exc:  # noqa: BLE001 - first failure fails the sheet
                if error is None:
                    error = exc

    if error is not None:
        # Include IDs whose journal write or progress callback failed too.
        deleted = delete_files(client, uploaded_ids, cache=store)
        _log.warning(
            "deleted %d already-uploaded image(s) after a failed sheet upload: "
            "sheet=%s",
            len(deleted), label,
        )
        raise error

    # file_ids in stable job order (overview first, then tiles) for readable
    # cleanup logs; the content assembly maps each image to its own id directly.
    mapping = {id(image): by_position[pos] for pos, image, _name in jobs}
    file_ids = [by_position[pos] for pos, _image, _name in jobs]
    block = lambda t: _file_image_block(mapping[id(t)])  # noqa: E731
    content = (
        build_user_content_blocks(sheet, block)
        if task_instruction is None
        else build_user_content_blocks(sheet, block, task_instruction=task_instruction)
    )
    return SheetUpload(content=content, file_ids=file_ids)


def delete_files(
    client: Any, file_ids: list[str], *, cache: Any = None,
    max_workers: int = DEFAULT_DELETE_WORKERS,
    max_retries: int = DEFAULT_DELETE_MAX_RETRIES, sleep: Any = time.sleep,
) -> list[str]:
    """Delete with at most six workers and bounded transient-error retries.

    Deletion is idempotent, so status, connection and timeout failures can all
    be retried. A 404 is already deleted. Return successful/absent IDs; failed
    IDs stay in the ownership journal for startup cleanup. Cleanup errors are
    logged and never sink a run.
    """
    files = getattr(client, "files", None)
    deleter = getattr(files, "delete", None)
    if deleter is None:
        return []
    ids = list(dict.fromkeys(fid for fid in file_ids if fid))
    if not ids:
        return []
    from .batch_recovery import recovery_cache

    store = recovery_cache(cache)

    def delete_one(fid: str) -> bool:
        for attempt in range(max(0, max_retries) + 1):
            try:
                deleter(fid)
                break
            except Exception as exc:  # noqa: BLE001 - cleanup is nonfatal
                if _error_status(exc) == 404:
                    break
                transient = _is_transient_error(exc) or isinstance(exc, (ConnectionError, TimeoutError))
                if transient and attempt < max_retries:
                    delay = _retry_backoff_seconds(attempt)
                    _log.warning("files-api delete %s retry %d/%d in %.0fs: %s",
                                 fid, attempt + 1, max_retries, delay, summarize_exc(exc))
                    resource_pressure.note_api_retry(
                        exc, stage="files_cleanup", attempt=attempt + 1, backoff_seconds=delay,
                    )
                    sleep(delay)
                    continue
                if transient:
                    resource_pressure.note_api_give_up(
                        exc, stage="files_cleanup", attempts=attempt + 1,
                    )
                _log.warning("files-api delete failed; retained for reaper: %s | %s",
                             fid, summarize_exc(exc))
                return False
        try:
            store.forget_uploaded_file(fid)
        except Exception as exc:
            # A future 404 will let the reaper finish this bookkeeping.
            _log.warning("files-api delete journal update failed: %s | %s", fid, summarize_exc(exc))
        return True

    workers = max(1, min(max_workers, DEFAULT_DELETE_WORKERS, len(ids)))
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="file-delete", **resource_pressure.worker_binding(),
    ) as executor:
        results = list(executor.map(delete_one, ids))
    return [fid for fid, deleted in zip(ids, results) if deleted]


def reap_uploaded_files(client: Any = None, cache: Any = None, *, now: float | None = None,
                        sleep: Any = time.sleep) -> list[str]:
    """Reap locally recorded uploads older than the 24h batch bound + 1h.

    Never list remote files or infer ownership from filenames. A live batch
    receipt, or a receipt whose remote status cannot be checked, protects all
    its IDs regardless of age. Submission/reuse restarts the age bound.
    """
    from .batch_recovery import recovery_cache, _read_with_retry

    try:
        store = recovery_cache(cache)
        cutoff = (time.time() if now is None else now) - UPLOAD_REAP_MIN_AGE_SECONDS
        candidates = {record["file_id"] for record in store.recorded_uploads()
                      if max(record["uploaded_at"], record["last_needed_at"]) < cutoff}
        if not candidates:
            return []
        receipts = store.pending_batches()
        if client is None:
            from .client import get_client
            client = get_client()
        protected: set[str] = set()
        terminal_receipts: set[str] = set()
        for record in receipts:
            ids = set(record.get("file_ids", []))
            if not ids.intersection(candidates):
                continue
            try:
                batch = _read_with_retry(
                    lambda: client.messages.batches.retrieve(record["batch_id"]), sleep=sleep,
                )
                status = (batch.get("processing_status", "") if isinstance(batch, dict)
                          else getattr(batch, "processing_status", ""))
                if str(status).lower() in _TERMINAL_BATCH_STATUSES:
                    terminal_receipts.add(record["batch_id"])
                    continue
            except Exception as exc:
                _log.warning("upload reaper cannot check batch %s; protecting files: %s",
                             record["batch_id"], summarize_exc(exc))
            protected.update(ids)
        # Status reads can take time. Recheck local state so a new batch/reuse
        # recorded while we checked the old receipts cannot lose its images.
        candidates.intersection_update(
            record["file_id"] for record in store.recorded_uploads()
            if max(record["uploaded_at"], record["last_needed_at"]) < cutoff
        )
        for record in store.pending_batches():
            if record["batch_id"] not in terminal_receipts:
                protected.update(record.get("file_ids", []))
        deleted = delete_files(client, sorted(candidates - protected), cache=store, sleep=sleep)
        for fid in deleted:
            _log.info("upload reaper deleted file_id=%s", fid)
        _log.info("upload reaper reclaimed %d file(s); protected %d eligible file(s)",
                  len(deleted), len(candidates & protected))
        return deleted
    except Exception as exc:
        _log.warning("upload reaper skipped: %s", summarize_exc(exc))
        return []


def start_upload_reaper(client: Any = None, cache: Any = None, *,
                        sleep: Any = time.sleep) -> threading.Thread:
    """Dispatch maintenance without delaying GUI startup or receipt recovery.

    Concurrent startup/run requests share one active reaper per store. The
    daemon may be interrupted at exit; unremoved IDs remain durably recorded.
    Return the thread so callers/tests can await maintenance explicitly.
    """
    def run() -> None:
        from .batch_recovery import recovery_cache

        store = recovery_cache(cache)
        with _reaper_lock:
            if store in _active_reaper_stores:
                return
            _active_reaper_stores.add(store)
        try:
            reap_uploaded_files(client, store, sleep=sleep)
        finally:
            with _reaper_lock:
                _active_reaper_stores.discard(store)

    thread = threading.Thread(target=run, daemon=True, name="upload-reaper")
    thread.start()
    return thread
