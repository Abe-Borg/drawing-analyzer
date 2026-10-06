"""Durable Message Batch receipts and idempotent, restartable result reads.

Receipts live beside cache entries in SQLite and are committed synchronously.
An explicitly memory-only DigestCache also keeps receipts in memory, so tests
and callers opting out of persistence never touch the user's cache.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import diagnostics
from . import resource_pressure
from .digest import DEFAULT_DIGEST_MAX_RETRIES, _is_transient_error, _retry_backoff_seconds
from .digest_cache import DigestCache, cache_schema_version, get_default_digest_cache
from .models import SheetRef

_log = diagnostics.get_logger()
# Anthropic retains results for 29 days from batch creation, not completion.
RESULTS_RETENTION_SECONDS = 29 * 24 * 60 * 60


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def recovery_cache(cache: Any) -> DigestCache:
    if isinstance(cache, DigestCache):
        return cache
    # A get/put adapter need not expose a durable receipt API. Retain its cache
    # semantics while keeping receipts in the configured default digest store.
    # This also protects callers that disabled cache lookups for the run.
    return get_default_digest_cache()


def _read_with_retry(call: Callable[[], Any], *, sleep: Callable[[float], None]) -> Any:
    for attempt in range(DEFAULT_DIGEST_MAX_RETRIES + 1):
        try:
            return call()
        except Exception as exc:
            # JSONL iteration can raise raw transport errors after the SDK has
            # returned the response, outside its built-in retry boundary.
            transient = _is_transient_error(exc) or isinstance(exc, (ConnectionError, TimeoutError))
            transient = transient or any(base.__name__ in {
                "TransportError", "NetworkError", "ProtocolError", "TimeoutException",
                "ReadError", "RemoteProtocolError",
            } for base in type(exc).__mro__)
            if not transient:
                raise
            if attempt == DEFAULT_DIGEST_MAX_RETRIES:
                resource_pressure.note_api_give_up(
                    exc, stage="batch_results", attempts=attempt + 1,
                )
                raise
            delay = _retry_backoff_seconds(attempt)
            _log.warning("batch read interrupted; retry %d/%d in %.0fs: %s",
                         attempt + 1, DEFAULT_DIGEST_MAX_RETRIES, delay, type(exc).__name__)
            resource_pressure.note_api_retry(
                exc, stage="batch_results", attempt=attempt + 1, backoff_seconds=delay,
            )
            sleep(delay)


def read_batch_results(client: Any, batch_id: str, *, sleep=time.sleep) -> dict[str, Any]:
    """Retry the entire stream from byte zero, discarding partial attempts."""
    def read() -> dict[str, Any]:
        stream = client.messages.batches.results(batch_id)
        try:
            return {_get(item, "custom_id"): item for item in stream}
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()
    return _read_with_retry(read, sleep=sleep)


class BatchReceiptError(OSError):
    """An accepted batch could not be recorded; uploads may still be in use."""

    def __init__(self, batch_id: str, *, files_safe: bool):
        self.files_safe = files_safe
        disposition = "cancellation confirmed" if files_safe else "cancellation unconfirmed; uploads retained"
        super().__init__(f"batch {batch_id} receipt persistence failed ({disposition}); "
                         "restore the recovery store before retrying")


def _cancel_unrecorded_batch(client: Any, batch_id: str, *, sleep) -> bool:
    """Request cancellation, then confirm the batch no longer uses its files."""
    terminal = {"ended", "failed", "expired", "canceled"}
    try:
        batch = _read_with_retry(lambda: client.messages.batches.cancel(batch_id), sleep=sleep)
        for attempt in range(DEFAULT_DIGEST_MAX_RETRIES + 1):
            if str(_get(batch, "processing_status", "")).lower() in terminal:
                return True
            if attempt:
                sleep(_retry_backoff_seconds(attempt - 1))
            batch = _read_with_retry(lambda: client.messages.batches.retrieve(batch_id), sleep=sleep)
        return str(_get(batch, "processing_status", "")).lower() in terminal
    except Exception:
        _log.exception("unrecorded batch %s cancellation could not be confirmed; retain uploads", batch_id)
        return False


def record_submitted_batch(cache: Any, batch_id: str, slots: list, *, client: Any,
                           stage="digest", runs=1, by_custom_id=None, submitted=None,
                           sleep=time.sleep) -> None:
    try:
        _persist_submitted_batch(cache, batch_id, slots, stage=stage, runs=runs,
                                 by_custom_id=by_custom_id, submitted=submitted)
    except Exception as exc:
        _log.exception("accepted batch %s receipt persistence failed; requesting cancellation", batch_id)
        files_safe = _cancel_unrecorded_batch(client, batch_id, sleep=sleep)
        raise BatchReceiptError(batch_id, files_safe=files_safe) from exc


def _persist_submitted_batch(cache: Any, batch_id: str, slots: list, *,
                             stage, runs, by_custom_id, submitted) -> None:
    items = {}
    for slot in slots:
        ids = slot.custom_ids if stage == "critique" else [slot.custom_id]
        ref = asdict(slot.ref)
        ref["pdf_path"] = str(ref["pdf_path"])
        for custom_id in ids:
            if custom_id is None:
                continue
            items[custom_id] = {
                "cache_key": slot.cache_key, "level1_key": getattr(slot, "level1_key", None),
                "slot_index": slot.index,
                "ref": ref, "rows": slot.rows, "cols": slot.cols,
                "image_estimate": getattr(slot, "image_estimate", 0),
                "attempts_submitted": max(1, getattr(slot, "attempts_submitted", 1)),
                "run_id": by_custom_id[custom_id][1] if by_custom_id else None,
            }
    created = _get(submitted, "created_at")
    if isinstance(created, str):
        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
    created_ts = created.timestamp() if isinstance(created, datetime) else time.time()
    recovery_cache(cache).record_batch({
        "batch_id": batch_id, "transport": "BATCH", "stage": stage,
        "submitted_at": time.time(), "results_expire_at": created_ts + RESULTS_RETENTION_SECONDS,
        "schema_version": cache_schema_version(stage), "runs": runs, "items": items,
        "file_ids": list(dict.fromkeys(fid for slot in slots for fid in slot.file_ids)),
    })


def _record_keys(record: dict) -> list[str]:
    return list(dict.fromkeys(key for item in record["items"].values()
                             for key in (item["cache_key"], item.get("level1_key")) if key))


def finish_batch_record(cache: Any, batch_id: str, raw: dict) -> dict[str, dict]:
    """Persist all usable results before removing the receipt; safe to replay."""
    store = recovery_cache(cache)
    record = next((r for r in store.pending_batches() if r["batch_id"] == batch_id), None)
    if record is None:
        return {}
    entries: dict[str, dict] = {}
    if record["schema_version"] == cache_schema_version(record["stage"]):
        if record["stage"] == "digest":
            from .batch_digest import _Slot, _parse_item
            from .digest import cache_entry_from_digest
            for custom_id, item in record["items"].items():
                ref_data = dict(item["ref"])
                ref_data["pdf_path"] = Path(ref_data["pdf_path"])
                slot = _Slot(index=0, ref=SheetRef(**ref_data), rows=item["rows"],
                             cols=item["cols"], image_estimate=item["image_estimate"],
                             custom_id=custom_id, attempts_submitted=item["attempts_submitted"])
                result = _parse_item(slot, raw.get(custom_id), cache=None)
                if result.error is None and result.text:
                    entry = cache_entry_from_digest(result)
                    for key in (item["cache_key"], item.get("level1_key")):
                        if key:
                            entries[key] = entry
        else:
            from .batch_critique import _outcome_from_envelope
            from .critique import critique_cache_entry_from_result, result_from_outcomes
            # Two distinct sheets can have identical pixels/cache keys. Merge
            # self-consistency reads per submitted sheet, never across sheets.
            grouped: dict[int, list] = {}
            metadata: dict[int, dict] = {}
            for custom_id, item in record["items"].items():
                ref_data = dict(item["ref"])
                ref_data["pdf_path"] = Path(ref_data["pdf_path"])
                slot_index = item["slot_index"]
                metadata[slot_index] = item
                grouped.setdefault(slot_index, []).append(_outcome_from_envelope(
                    raw.get(custom_id), run_id=item["run_id"], ref=SheetRef(**ref_data),
                    rows=item["rows"], cols=item["cols"],
                ))
            for slot_index, outcomes in grouped.items():
                result = result_from_outcomes(outcomes, requested_runs=record["runs"], label="recovered batch")
                if result.error is None and result.completed_runs == record["runs"]:
                    entry = critique_cache_entry_from_result(result)
                    item = metadata[slot_index]
                    for alias in (item["cache_key"], item.get("level1_key")):
                        if alias:
                            entries[alias] = entry
    for key, entry in entries.items():
        store.put(key, entry)
        if cache is not None and cache is not store:
            cache.put(key, entry)
    if not store.batch_entries_persisted(list(entries)):
        raise OSError(f"batch {batch_id} results have not reached the durable cache; retry next run")
    store.forget_batch(batch_id)
    return entries


@dataclass
class BatchRecovery:
    blocked: dict[str, str] = field(default_factory=dict)
    recovered: dict[str, dict] = field(default_factory=dict)


def recover_pending_batches(client: Any, cache: Any, *, sleep=time.sleep) -> BatchRecovery:
    """Collect retained terminal batches before spending on new submissions."""
    store = recovery_cache(cache)
    state = BatchRecovery()
    for record in store.pending_batches():
        batch_id = record["batch_id"]
        if time.time() >= record["results_expire_at"]:
            store.forget_batch(batch_id)
            _log.warning("batch %s results retention expired; removing recovery receipt", batch_id)
            continue
        try:
            resolved_client = client
            if resolved_client is None:
                from .client import get_client
                resolved_client = get_client()
            batch = _read_with_retry(lambda: resolved_client.messages.batches.retrieve(batch_id), sleep=sleep)
            status = str(_get(batch, "processing_status", "")).lower()
            if status not in ("ended", "failed", "expired", "canceled"):
                error = f"batch {batch_id} is still processing; retry later to collect it"
            else:
                raw = read_batch_results(resolved_client, batch_id, sleep=sleep)
                state.recovered.update(finish_batch_record(cache, batch_id, raw))
                from .batch_digest import _release_uploaded_files
                # Several rounds can share uploads. Do not delete files still
                # referenced by another receipt whose collection is pending.
                protected = {fid for pending in store.pending_batches()
                             for fid in pending.get("file_ids", [])}
                _release_uploaded_files(
                    resolved_client, [fid for fid in record.get("file_ids", []) if fid not in protected],
                    in_background=True, on_log=None, cache=store,
                )
                _log.info("recovered retained batch %s without a new submission", batch_id)
                continue
        except Exception as exc:
            _log.exception("retained batch %s collection failed; receipt kept", batch_id)
            error = f"batch {batch_id} collection failed ({type(exc).__name__}); retry next run to collect the existing batch"
        for key in _record_keys(record):
            state.blocked[key] = error
    # Also covers crashes during upload, before any receipt existed, and files
    # retained after failed cancellation. File delete retries must not delay
    # analysis; only receipt recovery belongs on the synchronous path.
    from .file_upload import start_upload_reaper
    start_upload_reaper(client, store, sleep=sleep)
    return state
