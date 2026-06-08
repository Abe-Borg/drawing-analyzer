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
from typing import Any

from .diagnostics import get_logger, summarize_exc
from .digest import (
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


def upload_sheet_images(
    client: Any,
    sheet: RenderedSheet,
    *,
    max_retries: int = DEFAULT_UPLOAD_MAX_RETRIES,
    sleep: Any = time.sleep,
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
