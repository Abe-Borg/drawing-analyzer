"""Hermetic Files API cleanup: durable ownership, bounded deletes, safe reaping."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing_analyzer import batch_digest, file_upload
from drawing_analyzer.batch_recovery import recover_pending_batches
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.file_upload import (
    UPLOAD_REAP_MIN_AGE_SECONDS, delete_files, reap_uploaded_files, upload_sheet_images,
)
from tests.test_drawing_batch import _FakeClient, _make_sheet, _succeed, OPUS


NOW = 2_000_000_000.0
OLD = NOW - UPLOAD_REAP_MIN_AGE_SECONDS - 1
NOSLEEP = lambda _: None


class StatusError(Exception):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"HTTP {status}")


class Files:
    def __init__(self, behavior=None):
        self.deleted = []
        self.calls = Counter()
        self.behavior = behavior
        self.lock = threading.Lock()

    def delete(self, fid):
        with self.lock:
            self.calls[fid] += 1
            attempt = self.calls[fid]
        if self.behavior:
            self.behavior(fid, attempt)
        with self.lock:
            self.deleted.append(fid)

    def list(self, *args, **kwargs):
        raise AssertionError("cleanup must never discover files belonging to other tools")


def client_for(files, statuses=None):
    def retrieve(batch_id):
        status = (statuses or {})[batch_id]
        if isinstance(status, Exception):
            raise status
        return SimpleNamespace(processing_status=status)

    return SimpleNamespace(files=files, messages=SimpleNamespace(
        batches=SimpleNamespace(retrieve=retrieve),
    ))


def receipt(batch_id, ids, *, submitted_at=OLD):
    return {
        "batch_id": batch_id, "file_ids": ids, "submitted_at": submitted_at,
        "results_expire_at": NOW + 1000, "items": {},
    }


@pytest.fixture(params=[False, True], ids=["memory", "sqlite"])
def store(request, tmp_path):
    cache = DigestCache(tmp_path / "uploads.sqlite3", persist=request.param)
    yield cache
    cache.close()


# Delete-pool concurrency and retry policy do not depend on the journal backend;
# the SQLite record/forget path is exercised by the store-parametrized reaper and
# batch-cleanup tests below.
memory_store_only = pytest.mark.parametrize("store", [False], ids=["memory"], indirect=True)


@memory_store_only
def test_parallel_delete_is_bounded_and_retries_each_file(store):
    ids = [f"file-{n}" for n in range(12)]
    for fid in ids:
        store.record_uploaded_file(fid, uploaded_at=OLD)
    barrier = threading.Barrier(3)
    lock = threading.Lock()
    active = peak = 0

    def behavior(fid, attempt):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            if attempt == 1:
                barrier.wait(timeout=5)
                raise StatusError(503)
        finally:
            with lock:
                active -= 1

    files = Files(behavior)
    slept = []
    deleted = delete_files(client_for(files), ids + ids + [""], cache=store,
                           max_workers=3, max_retries=2, sleep=slept.append)
    assert peak == 3
    assert deleted == ids
    assert files.calls == Counter({fid: 2 for fid in ids})
    assert slept == [2.0] * len(ids)
    assert store.recorded_uploads() == []


@memory_store_only
def test_delete_cannot_exceed_worker_cap(store):
    barrier = threading.Barrier(file_upload.DEFAULT_DELETE_WORKERS)
    lock = threading.Lock()
    active = peak = 0

    def behavior(fid, attempt):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            barrier.wait(timeout=5)
        finally:
            with lock:
                active -= 1

    files = Files(behavior)
    ids = [f"file-{i}" for i in range(file_upload.DEFAULT_DELETE_WORKERS * 2)]
    assert delete_files(client_for(files), ids, cache=store, max_workers=100) == ids
    assert peak == file_upload.DEFAULT_DELETE_WORKERS


@memory_store_only
@pytest.mark.parametrize("error", [StatusError(429), StatusError(529),
                                  ConnectionError("lost connection"), TimeoutError("timeout")])
def test_delete_transient_retries_are_bounded_and_retained_for_next_startup(error, store):
    store.record_uploaded_file("file", uploaded_at=OLD)

    def fail(fid, attempt):
        raise error

    files = Files(fail)
    slept = []
    assert delete_files(client_for(files), ["file"], cache=store,
                        max_retries=2, sleep=slept.append) == []
    assert files.calls == {"file": 3}
    assert slept == [2.0, 4.0]
    assert [r["file_id"] for r in store.recorded_uploads()] == ["file"]
    files.behavior = None
    assert reap_uploaded_files(client_for(files), store, now=NOW, sleep=NOSLEEP) == ["file"]
    assert store.recorded_uploads() == []


# 401/403 take 400's path: neither 404 nor a transient status.
@memory_store_only
@pytest.mark.parametrize("status", [400, 404])
def test_permanent_delete_errors_are_not_retried_and_404_forgets_ownership(status, store):
    store.record_uploaded_file("file", uploaded_at=OLD)

    def fail(fid, attempt):
        raise StatusError(status)

    files = Files(fail)
    slept = []
    assert delete_files(client_for(files), ["file"], cache=store, sleep=slept.append) == (
        ["file"] if status == 404 else []
    )
    assert files.calls == {"file": 1}
    assert slept == []
    assert len(store.recorded_uploads()) == (0 if status == 404 else 1)


def test_reaper_age_margin_boundary_future_and_unrecorded_exclusions(store, caplog):
    for fid, timestamp in {
        "old": OLD,
        "exact-boundary": NOW - UPLOAD_REAP_MIN_AGE_SECONDS,
        "within-margin": NOW - 24 * 60 * 60 - 30 * 60,
        "young": NOW - 1000,
        "future": NOW + 1000,
    }.items():
        store.record_uploaded_file(fid, uploaded_at=timestamp)
    files = Files()
    # An old server-side file with the same app-like name still has no local ID
    # record. Nothing may enumerate or delete it.
    files.other_tools_files = ["unrecorded-drawing-overview.png"]
    with caplog.at_level(logging.INFO, logger="drawing_analyzer"):
        assert reap_uploaded_files(client_for(files), store, now=NOW, sleep=NOSLEEP) == ["old"]
    assert files.deleted == ["old"]
    assert "upload reaper deleted file_id=old" in caplog.text
    assert {r["file_id"] for r in store.recorded_uploads()} == {
        "exact-boundary", "within-margin", "young", "future",
    }


def test_reaper_live_canceling_unknown_and_shared_batch_exclusions(store):
    records = [
        receipt("live", ["live-only", "shared"]),
        receipt("canceling", ["canceling-only"]),
        receipt("unknown", ["unknown-only"]),
        receipt("ended", ["terminal-only", "shared"]),
        receipt("fresh-reuse", ["reused"], submitted_at=NOW - 100),
    ]
    store.record_uploaded_file("reused", uploaded_at=OLD)
    for record in records:
        store.record_batch(record)
    files = Files()
    statuses = {"live": "in_progress", "canceling": "canceling",
                "unknown": ConnectionError("cannot check"), "ended": "ended"}
    assert reap_uploaded_files(client_for(files, statuses), store, now=NOW, sleep=NOSLEEP) == ["terminal-only"]
    assert files.deleted == ["terminal-only"]
    assert {r["file_id"] for r in store.recorded_uploads()} == {
        "live-only", "shared", "canceling-only", "unknown-only", "reused",
    }
    assert len(store.pending_batches()) == len(records)


@pytest.mark.parametrize("status", ["ended", "failed", "expired", "canceled"])
def test_terminal_batch_files_reaped_without_discarding_receipt(status, store):
    record = receipt("batch", ["file"])
    store.record_batch(record)
    files = Files()
    assert reap_uploaded_files(client_for(files, {"batch": status}), store, now=NOW) == ["file"]
    assert store.pending_batches() == [record]


def test_reaper_fails_closed_when_receipts_unreadable(store, monkeypatch):
    store.record_uploaded_file("old", uploaded_at=OLD)

    def unreadable():
        raise OSError("receipt store unavailable")

    monkeypatch.setattr(store, "pending_batches", unreadable)
    files = Files()
    assert reap_uploaded_files(client_for(files), store, now=NOW) == []
    assert files.calls == {}


def test_reaper_rechecks_reuse_recorded_during_status_read(store):
    store.record_batch(receipt("old-terminal", ["file"]))
    files = Files()

    def retrieve(_):
        store.record_batch(receipt("new-live", ["file"], submitted_at=NOW))
        return SimpleNamespace(processing_status="ended")

    client = client_for(files)
    client.messages.batches.retrieve = retrieve
    assert reap_uploaded_files(client, store, now=NOW) == []
    assert files.deleted == []


def test_background_cleanup_captures_its_store_before_dispatch(store, monkeypatch):
    from drawing_analyzer import digest_cache

    store.record_uploaded_file("file", uploaded_at=OLD)
    monkeypatch.setattr(digest_cache, "_default_cache", store)
    jobs = []
    monkeypatch.setattr(batch_digest, "_run_in_background", jobs.append)
    files = Files()
    batch_digest._release_uploaded_files(client_for(files), ["file"],
                                         in_background=True, on_log=None)
    other_store = DigestCache(None, persist=False)
    other_store.record_uploaded_file("file", uploaded_at=NOW)
    monkeypatch.setattr(digest_cache, "_default_cache", other_store)
    jobs[0]()
    assert store.recorded_uploads() == []
    assert [r["file_id"] for r in other_store.recorded_uploads()] == ["file"]


def test_startup_recovery_reaps_orphans_after_restart(tmp_path, monkeypatch):
    path = tmp_path / "uploads.sqlite3"
    cache = DigestCache(path)
    cache.record_uploaded_file("old-orphan", uploaded_at=OLD)
    cache.close()
    cache = DigestCache(path)
    files = Files()
    monkeypatch.setattr(file_upload.time, "time", lambda: NOW)
    threads = []
    start = file_upload.start_upload_reaper

    def track(*args, **kwargs):
        threads.append(start(*args, **kwargs))

    monkeypatch.setattr(file_upload, "start_upload_reaper", track)
    state = recover_pending_batches(client_for(files), cache, sleep=NOSLEEP)
    assert not state.blocked and not state.recovered
    threads[0].join(timeout=5)
    assert not threads[0].is_alive()
    assert files.deleted == ["old-orphan"]
    cache.close()
    cache = DigestCache(path)
    assert cache.recorded_uploads() == []
    cache.close()


def test_receipt_recovery_returns_while_orphan_delete_is_stalled(store, monkeypatch):
    store.record_uploaded_file("old-orphan", uploaded_at=OLD)
    # A live receipt must be checked and block duplicate paid work before return.
    pending = receipt("live", ["live-file"], submitted_at=NOW)
    pending["items"] = {"sheet": {"cache_key": "paid-key"}}
    store.record_batch(pending)
    delete_started = threading.Event()
    release_delete = threading.Event()
    recovery_done = threading.Event()
    threads = []
    result = []
    errors = []
    monkeypatch.setattr(file_upload.time, "time", lambda: NOW)
    start = file_upload.start_upload_reaper

    def track(*args, **kwargs):
        threads.append(start(*args, **kwargs))

    def stalled_delete(fid, attempt):
        delete_started.set()
        assert release_delete.wait(timeout=5)

    files = Files(stalled_delete)
    client = client_for(files, {"live": "in_progress"})
    monkeypatch.setattr(file_upload, "start_upload_reaper", track)

    def recover():
        try:
            result.append(recover_pending_batches(client, store, sleep=NOSLEEP))
        except Exception as exc:
            errors.append(exc)
        finally:
            recovery_done.set()

    recovery = threading.Thread(target=recover, daemon=True)
    recovery.start()
    try:
        assert delete_started.wait(timeout=5)
        assert recovery_done.wait(timeout=1), "orphan delete stalled synchronous recovery"
        assert not errors
        assert "paid-key" in result[0].blocked
        assert files.deleted == []
        assert {r["file_id"] for r in store.recorded_uploads()} == {"old-orphan", "live-file"}
    finally:
        release_delete.set()
        recovery.join(timeout=5)
        for thread in threads:
            thread.join(timeout=5)
    assert files.deleted == ["old-orphan"]


def test_background_reaper_coalesces_overlapping_requests_and_allows_later_runs(store, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    def reap(client, cache, *, sleep):
        calls.append((client, cache, sleep))
        started.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(file_upload, "reap_uploaded_files", reap)
    first = file_upload.start_upload_reaper("client", store, sleep=NOSLEEP)
    try:
        assert started.wait(timeout=5)
        overlapping = file_upload.start_upload_reaper("client", store, sleep=NOSLEEP)
        overlapping.join(timeout=1)
        assert not overlapping.is_alive()
        assert calls == [("client", store, NOSLEEP)]
    finally:
        release.set()
        first.join(timeout=5)
    assert not first.is_alive()
    later = file_upload.start_upload_reaper("client", store, sleep=NOSLEEP)
    later.join(timeout=5)
    assert not later.is_alive()
    assert calls == [("client", store, NOSLEEP)] * 2


def test_legacy_pending_receipt_ids_migrate_and_are_not_resurrected(tmp_path):
    path = tmp_path / "uploads.sqlite3"
    cache = DigestCache(path)
    record = receipt("legacy", ["legacy-file"])
    # Simulate the already-landed batch recovery schema, before upload journals.
    cache._connection.execute("DROP TABLE uploaded_files")
    cache._connection.execute("INSERT INTO pending_batches VALUES (?, ?)",
                              ("legacy", json.dumps(record)))
    cache.close()
    cache = DigestCache(path)
    assert cache.recorded_uploads() == [{
        "file_id": "legacy-file", "uploaded_at": OLD, "last_needed_at": OLD,
    }]
    files = Files()
    assert reap_uploaded_files(client_for(files, {"legacy": "ended"}), cache, now=NOW) == ["legacy-file"]
    cache.close()
    cache = DigestCache(path)
    assert cache.pending_batches() == [record]
    assert cache.recorded_uploads() == []
    cache.close()


def test_process_crash_mid_upload_retains_ids_before_batch_submission(tmp_path):
    path = tmp_path / "uploads.sqlite3"
    script = """
import os, sys
from drawing_analyzer.file_upload import upload_sheet_images
from drawing_analyzer.digest_cache import DigestCache
from tests.test_drawing_batch import _FakeClient, _make_sheet, _succeed
def crash(*args):
    os._exit(17)
upload_sheet_images(_FakeClient(_succeed), _make_sheet(0), max_workers=1,
                    cache=DigestCache(sys.argv[1]), on_image=crash)
"""
    repo = Path(__file__).resolve().parents[1]
    child = subprocess.run([sys.executable, "-c", script, str(path)], cwd=repo,
                           env={**os.environ, "PYTHONPATH": str(repo / "src")},
                           capture_output=True, text=True, timeout=30)
    assert child.returncode == 17, child.stderr
    cache = DigestCache(path)
    assert cache.pending_batches() == []
    upload, = cache.recorded_uploads()
    files = Files()
    assert reap_uploaded_files(client_for(files), cache,
                               now=upload["uploaded_at"] + UPLOAD_REAP_MIN_AGE_SECONDS + 1) == ["file_0"]
    cache.close()


def test_journal_unavailable_prevents_new_uploads(tmp_path):
    cache = DigestCache(tmp_path / "uploads.sqlite3")
    cache.close()
    client = _FakeClient(_succeed)
    with pytest.raises(OSError, match="upload recovery store"):
        upload_sheet_images(client, _make_sheet(0), cache=cache)
    assert client.files.uploaded_ids == []


def test_journal_write_failure_deletes_even_the_unreturned_id(store, monkeypatch):
    client = _FakeClient(_succeed)

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "record_uploaded_file", fail)
    with pytest.raises(OSError, match="disk full"):
        upload_sheet_images(client, _make_sheet(0), max_workers=1, cache=store)
    assert client.files.uploaded_ids == client.files.deleted == ["file_0"]


@pytest.mark.parametrize("stage", ["digest", "critique"])
def test_batch_cleanup_uses_the_same_custom_upload_store(stage, store):
    from drawing_analyzer import batch_critique
    from tests.test_drawing_batch_critique import _FakeClient as CritiqueClient, _succeed as critique_succeed

    module = batch_digest if stage == "digest" else batch_critique
    client = _FakeClient(_succeed) if stage == "digest" else CritiqueClient(critique_succeed)
    submit = module.submit_drawing_batch if stage == "digest" else module.submit_critique_batch
    collect = module.collect_drawing_batch if stage == "digest" else module.collect_critique_batch
    batch = submit([_make_sheet(0)], client=client, model=OPUS, cache=store)
    assert {r["file_id"] for r in store.recorded_uploads()} == set(client.files.uploaded_ids)
    collect(batch, client=client, cache=store, sleep=NOSLEEP)
    assert store.recorded_uploads() == []


@pytest.mark.parametrize("stage", ["digest", "critique"])
def test_failed_cancel_is_revisited_after_batch_ends(stage, store, monkeypatch):
    from drawing_analyzer import batch_critique
    from tests.test_drawing_batch_critique import _FakeClient as CritiqueClient, _succeed as critique_succeed

    module = batch_digest if stage == "digest" else batch_critique
    client = _FakeClient(_succeed) if stage == "digest" else CritiqueClient(critique_succeed)
    client.status = "in_progress"
    submit = module.submit_drawing_batch if stage == "digest" else module.submit_critique_batch
    collect = module.collect_drawing_batch if stage == "digest" else module.collect_critique_batch
    batch = submit([_make_sheet(0)], client=client, model=OPUS, cache=store)
    monkeypatch.setattr(module, "_poll_until_terminal", lambda *a, **k: "detached")
    monkeypatch.setattr(module, "_cancel_batch", lambda *a, **k: False)
    collect(batch, client=client, cache=store, sleep=NOSLEEP)
    assert client.files.deleted == []
    assert store.pending_batches()
    later = max(r["last_needed_at"] for r in store.recorded_uploads()) + UPLOAD_REAP_MIN_AGE_SECONDS + 1
    assert reap_uploaded_files(client, store, now=later) == []
    client.status = "ended"
    assert set(reap_uploaded_files(client, store, now=later)) == set(client.files.uploaded_ids)
    assert store.recorded_uploads() == []


def test_gui_startup_starts_reaper_after_key_loading(monkeypatch):
    from tests.test_gui_lifecycle import _gui_module

    calls = []
    with _gui_module() as (gui, _):
        monkeypatch.setattr(gui.diagnostics, "configure_file_logging", lambda: None)
        monkeypatch.setattr(gui.ctk, "set_appearance_mode", lambda _: None, raising=False)
        monkeypatch.setattr(gui.ctk, "set_default_color_theme", lambda _: None, raising=False)

        def app():
            calls.append("app-loads-key")
            return SimpleNamespace(mainloop=lambda: calls.append("mainloop"))

        monkeypatch.setattr(gui, "DrawingAnalyzerApp", app)
        monkeypatch.setattr(file_upload, "start_upload_reaper", lambda: calls.append("reaper"))
        gui.main()
    assert calls == ["app-loads-key", "reaper", "mainloop"]
