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

Uploaded files are best-effort deleted after the batch is collected
(:func:`delete_files`); they cost nothing to store, but cleanup keeps the org's
file storage from accumulating a fresh image set on every run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .diagnostics import get_logger, summarize_exc
from .digest import (
    _error_status,
    _is_transient_status_error,
    _retry_backoff_seconds,
    build_user_content_blocks,
)
from .models import ImageTile, RenderedSheet

_log = get_logger()

# Files API beta header. Current/recognized per Anthropic's Files API docs; the
# SDK sets it automatically on ``client.beta.files.*`` calls. It must also be
# attached to the message/batch that *references* a file_id — for the batch path
# that is the ``betas=`` arg on ``client.beta.messages.batches.create``. An
# *unrecognized* anthropic-beta value is rejected with HTTP 400, so this is the
# one current value, attached only where a file_id is actually used.
FILES_API_BETA = "files-api-2025-04-14"

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
# The pinned SDK *does* post to ``/v1/files`` with the required
# ``anthropic-beta: files-api-2025-04-14`` header on every
# ``client.beta.files.upload`` call (verified against the 0.97.x resource), and
# the call still comes back with an Anthropic ``request_id`` — so a 404 there is
# the server declining the route, not a malformed request. In practice that is
# the Files API not being enabled for the key/workspace, an
# ``ANTHROPIC_BASE_URL``/proxy override that doesn't forward /v1/files (or strips
# the beta header), or a different installed ``anthropic`` package than the
# pinned one. The run no longer dies on it — it inlines the images as base64
# instead (see ``INLINE_FALLBACK_UPLOAD_STATUSES``) — but the diagnosis is still
# logged so the underlying misconfiguration stays visible.
_RUN_FATAL_UPLOAD_HINTS = {
    401: "the API key was rejected — re-enter or rotate the key",
    403: "the API key/workspace lacks permission for the Files API",
    404: (
        "the Files API is not answering /v1/files for this key — most often it "
        "is not enabled on the workspace, or an ANTHROPIC_BASE_URL/proxy "
        "override is not forwarding /v1/files (or is stripping the "
        "'anthropic-beta: files-api-2025-04-14' header), or the installed "
        "anthropic SDK differs from the pinned version"
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
    sleep: Any = time.sleep,
    on_image: ImageProgress | None = None,
) -> SheetUpload:
    """Upload a sheet's overview + tiles via the Files API; build file-id content.

    Returns the user-turn content blocks (image-by-file_id, identical framing to
    the base64 path via :func:`~drawing_analyzer.digest.build_user_content_blocks`)
    plus the uploaded ``file_id``s for cleanup. Raises on an upload failure; the
    caller treats the sheet as failed and deletes any ids already uploaded, so a
    partial upload never leaks files.

    Each image upload is retried on a transient *status* rejection
    (:func:`~drawing_analyzer.digest._is_transient_status_error` — the Files-API
    ``503 overloaded_error`` among them) up to ``max_retries`` times with
    exponential backoff, the same policy the per-sheet digest uses. The retry is
    per *image*, so a blip on one of a sheet's ~37 uploads no longer discards the
    images already uploaded for that sheet. Connection / timeout errors are
    deliberately *not* re-issued here: the server may have already stored the
    file before the response was lost, so a fresh upload could orphan it (a file
    id never captured for cleanup) — those are left to the SDK's idempotent
    internal retries. ``sleep`` is injectable so tests don't wait; a permanent
    failure (or exhausted retries) re-raises for the caller to capture as a
    failed sheet.
    """
    stem = _safe_stem(sheet)
    label = sheet.ref.display_label
    file_ids: list[str] = []
    mapping: dict[int, str] = {}
    total_images = 1 + len(sheet.tiles)

    def _upload(image: ImageTile, name: str) -> None:
        position = len(file_ids) + 1  # 1-based index of this image within the sheet
        attempt = 0
        while True:
            try:
                uploaded = client.beta.files.upload(
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
                        position, total_images, len(image.png_bytes),
                        summarize_exc(exc),
                    )
                    if on_image is not None:
                        on_image(position, total_images, True)
                    sleep(backoff)
                    attempt += 1
                    continue
                # Permanent, or transient retries exhausted: pinpoint the exact
                # image (overview vs which tile), its size, and the API status /
                # request-id so the failure that doomed this sheet is fully
                # attributable after the fact.
                _log.warning(
                    "files-api upload FAILED: sheet=%s image=%s (#%d/%d, %d bytes) | %s",
                    label, name, position, total_images,
                    len(image.png_bytes), summarize_exc(exc),
                )
                raise
        fid = _uploaded_id(uploaded)
        file_ids.append(fid)
        mapping[id(image)] = fid
        _log.debug(
            "files-api upload ok: sheet=%s image=%s (#%d/%d) file_id=%s",
            label, name, len(file_ids), total_images, fid,
        )
        if on_image is not None:
            on_image(len(file_ids), total_images, False)

    _log.debug("uploading %d image(s) for sheet=%s", total_images, label)
    try:
        _upload(sheet.overview, f"{stem}-overview.png")
        for tile in sheet.tiles:
            _upload(tile, f"{stem}-r{tile.row + 1}c{tile.col + 1}.png")
    except Exception:
        delete_files(client, file_ids)  # don't leak a half-uploaded set
        _log.warning(
            "deleted %d already-uploaded image(s) after a failed sheet upload: "
            "sheet=%s",
            len(file_ids), label,
        )
        raise

    content = build_user_content_blocks(sheet, lambda t: _file_image_block(mapping[id(t)]))
    return SheetUpload(content=content, file_ids=file_ids)


def delete_files(client: Any, file_ids: list[str]) -> None:
    """Best-effort delete uploaded files; never raises (cleanup is advisory)."""
    files = getattr(getattr(client, "beta", None), "files", None)
    deleter = getattr(files, "delete", None)
    if deleter is None:
        return
    for fid in file_ids:
        if not fid:
            continue
        try:
            deleter(fid)
        except Exception:  # noqa: BLE001 - cleanup must never sink a run
            pass
