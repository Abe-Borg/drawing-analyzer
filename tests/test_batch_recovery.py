"""Paid batches survive interrupted streams and fresh-process cache reopens."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing_analyzer import batch_digest, batch_recovery, batch_critique, digest_cache, pipeline
from drawing_analyzer.batch_recovery import BatchReceiptError, recover_pending_batches, read_batch_results
from drawing_analyzer.digest_cache import DigestCache
from tests.test_drawing_batch import _FakeClient, _flaky_then_ok, _make_sheet, _succeed, OPUS, NOSLEEP
from tests.fixtures.fake_anthropic import FakeBatchResult, FakeBatchResultEnvelope, FakeMessage, FakeTextBlock
from tests.test_drawing_batch_critique import (
    _FakeClient as CritiqueClient, _succeed as critique_succeed,
)


@pytest.fixture(autouse=True)
def sequential_uploads(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")


@pytest.mark.parametrize("stage", ["digest", "critique"])
def test_partial_results_stream_restarts_from_beginning(stage, monkeypatch):
    cache = DigestCache(None, persist=False)
    client = _FakeClient(_succeed) if stage == "digest" else CritiqueClient(critique_succeed)
    module = batch_digest if stage == "digest" else batch_critique
    submit = module.submit_drawing_batch if stage == "digest" else module.submit_critique_batch
    collect = module.collect_drawing_batch if stage == "digest" else module.collect_critique_batch
    batch = submit([_make_sheet(0), _make_sheet(1)], client=client, model=OPUS, cache=cache)
    original = client.messages.batches.results
    calls = []
    closed = []

    def results(batch_id):
        calls.append(batch_id)
        try:
            for index, item in enumerate(original(batch_id)):
                yield item
                if len(calls) == 1 and index == 0:
                    raise ConnectionError("stream dropped after first item")
        finally:
            closed.append(batch_id)

    monkeypatch.setattr(client.messages.batches, "results", results)
    slept = []
    collected = collect(batch, client=client, cache=cache, sleep=slept.append)
    assert len(calls) == len(closed) == 2
    assert slept == [2.0]
    assert len(client.create_calls) == 1
    assert len(collected) == 2
    assert all((result if stage == "digest" else result[1]).error is None for result in collected)
    assert cache.pending_batches() == []


@pytest.mark.parametrize("error", [ConnectionError("down"), RuntimeError("bad result")])
def test_read_retries_are_bounded_and_permanent_errors_are_not_retried(error):
    calls = []

    def results(_):
        calls.append(1)
        raise error

    client = SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(results=results)))
    slept = []
    with pytest.raises(type(error)):
        read_batch_results(client, "batch", sleep=slept.append)
    assert len(calls) == (3 if isinstance(error, ConnectionError) else 1)
    assert slept == ([2.0, 4.0] if isinstance(error, ConnectionError) else [])


def make_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "drawings.pdf"
    with pymupdf.open() as doc:
        for i in range(2):
            page = doc.new_page(width=300, height=200)
            page.insert_text((30, 30), f"DRAWING M-10{i}")
        doc.save(path)
    return path


def run_pipeline(path, client, cache):
    return pipeline.extract_drawing_context(
        [path], client=client, cache=cache, use_batch=True,
        rows=1, cols=1, model=OPUS, synthesize=False,
    )


def test_run_exit_after_submit_recovers_with_zero_new_submissions(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    cache_path = tmp_path / "digest.sqlite3"
    first_cache = DigestCache(cache_path)
    first_client = _FakeClient(_succeed)

    def exit_after_submit(*args, **kwargs):
        raise SystemExit("process died after API accepted the batch")

    with monkeypatch.context() as patch:
        patch.setattr(batch_digest, "collect_drawing_batch", exit_after_submit)
        with pytest.raises(SystemExit):
            run_pipeline(path, first_client, first_cache)
    first_cache.close()

    # A fresh client/cache has no run-local slots or request metadata. Only the
    # server's retained results and the committed receipt survive the exit.
    next_cache = DigestCache(cache_path)
    receipt, = next_cache.pending_batches()
    assert receipt["batch_id"] == "batch_abc"
    assert receipt["transport"] == "BATCH" and receipt["submitted_at"] > 0
    assert len(receipt["items"]) == 2
    assert all(item["cache_key"] and item["level1_key"] and item["ref"]["source_id"]
               for item in receipt["items"].values())
    next_client = _FakeClient(_succeed)
    next_client.submitted = first_client.submitted
    monkeypatch.setattr(pipeline, "_rendered_stream", lambda *a, **k: pytest.fail("recovery should warm level-1 keys"))
    ctx = run_pipeline(path, next_client, next_cache)
    assert ctx.ok_sheet_count == ctx.sheet_count == 2
    assert next_client.create_calls == []
    assert next_client.files.uploaded_ids == []
    assert next_cache.pending_batches() == []
    assert all(sheet.cached for sheet in ctx.sheets)


def test_ungraceful_process_exit_leaves_a_durable_submission_receipt(tmp_path):
    cache_path = tmp_path / "digest.sqlite3"
    script = """
import os, sys
from drawing_analyzer.batch_digest import submit_drawing_batch
from drawing_analyzer.digest_cache import DigestCache
from tests.test_drawing_batch import _FakeClient, _make_sheet, _succeed, OPUS
cache = DigestCache(sys.argv[1])
submit_drawing_batch([_make_sheet(0)], client=_FakeClient(_succeed),
                     cache=cache, model=OPUS)
os._exit(17)  # No finally, destructor, close(), or WAL checkpoint.
"""
    repo = Path(__file__).resolve().parents[1]
    child = subprocess.run(
        [sys.executable, "-c", script, str(cache_path)], cwd=repo,
        env={**os.environ, "PYTHONPATH": str(repo / "src")},
        capture_output=True, text=True, timeout=30,
    )
    assert child.returncode == 17, child.stderr
    assert Path(f"{cache_path}-wal").stat().st_size > 0
    cache = DigestCache(cache_path)
    record, = cache.pending_batches()
    client = _FakeClient(_succeed)
    client.submitted = [{"custom_id": cid} for cid in record["items"]]
    recovered = batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, cache=cache, model=OPUS)
    assert recovered.slots[0].digest.ok and recovered.slots[0].digest.cached
    assert client.create_calls == []
    assert cache.pending_batches() == []


def test_collection_failure_does_not_abort_extract_and_next_run_recovers(tmp_path):
    path = make_pdf(tmp_path)
    cache_path = tmp_path / "digest.sqlite3"
    cache = DigestCache(cache_path)
    client = _FakeClient(_succeed)
    client.results_raises = RuntimeError("results body unavailable")
    ctx = run_pipeline(path, client, cache)
    assert ctx.sheet_count == 2 and ctx.ok_sheet_count == 0
    assert len(ctx.errors) >= 2
    assert all("retry next run" in sheet.error for sheet in ctx.sheets)
    assert len(client.create_calls) == 1
    assert len(cache.pending_batches()) == 1
    cache.close()
    recovered_cache = DigestCache(cache_path)
    client.results_raises = None
    ctx = run_pipeline(path, client, recovered_cache)
    assert ctx.ok_sheet_count == 2
    assert len(client.create_calls) == 1
    assert recovered_cache.pending_batches() == []


def test_pending_processing_batch_is_not_duplicated(tmp_path):
    cache_path = tmp_path / "digest.sqlite3"
    cache = DigestCache(cache_path)
    client = _FakeClient(_succeed, status="in_progress")
    batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=cache)
    cache.close()
    next_cache = DigestCache(cache_path)
    batch = batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=next_cache)
    results = batch_digest.collect_drawing_batch(batch, client=client, cache=next_cache, sleep=NOSLEEP)
    assert batch.batch_id is None and len(client.create_calls) == 1
    assert "still processing" in results[0].error and "retry" in results[0].error
    assert len(next_cache.pending_batches()) == 1


def test_failed_recovery_blocks_new_submissions_and_keeps_receipt(tmp_path):
    cache = DigestCache(tmp_path / "digest.sqlite3")
    client = _FakeClient(_succeed)
    batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=cache)
    client.results_raises = ConnectionError("results unavailable")
    batch = batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=cache, sleep=NOSLEEP)
    assert batch.batch_id is None
    assert "retry next run" in batch.slots[0].digest.error
    assert len(client.create_calls) == len(cache.pending_batches()) == 1


def test_critique_receipt_recovers_all_reads_into_fresh_cache(tmp_path):
    path = tmp_path / "digest.sqlite3"
    cache = DigestCache(path)
    client = CritiqueClient(critique_succeed)
    batch_critique.submit_critique_batch([_make_sheet(0)], client=client, cache=cache, model=OPUS, runs=2)
    cache.close()
    cache = DigestCache(path)
    batch = batch_critique.submit_critique_batch([_make_sheet(0)], client=client, cache=cache, model=OPUS, runs=2)
    assert batch.batch_id is None and len(client.create_calls) == 1
    assert batch.slots[0].result.cached
    assert batch.slots[0].result.completed_runs == 2
    assert cache.pending_batches() == []


@pytest.mark.parametrize("stage, bumped", [("digest", "critique"), ("critique", "digest")])
def test_other_stage_schema_bump_preserves_paid_batch_recovery(stage, bumped, tmp_path, monkeypatch):
    path = tmp_path / "digest.sqlite3"
    cache = DigestCache(path)
    client = _FakeClient(_succeed) if stage == "digest" else CritiqueClient(critique_succeed)
    submit = batch_digest.submit_drawing_batch if stage == "digest" else batch_critique.submit_critique_batch
    kwargs = {"runs": 2} if stage == "critique" else {}
    submit([_make_sheet(0)], client=client, cache=cache, model=OPUS, **kwargs)
    record, = cache.pending_batches()
    assert record["stage"] == stage and record["schema_version"] == 10
    cache.close()
    monkeypatch.setattr(digest_cache, f"_{bumped.upper()}_SCHEMA_VERSION", 11)
    cache = DigestCache(path)
    try:
        batch = submit([_make_sheet(0)], client=client, cache=cache, model=OPUS, **kwargs)
        result = batch.slots[0].digest if stage == "digest" else batch.slots[0].result
        assert result.cached
        assert batch.batch_id is None and len(client.create_calls) == 1
        assert cache.pending_batches() == []
    finally:
        cache.close()


@pytest.mark.parametrize("stage", ["digest", "critique"])
def test_new_batch_receipt_uses_its_namespace_version(stage, tmp_path, monkeypatch):
    monkeypatch.setattr(digest_cache, f"_{stage.upper()}_SCHEMA_VERSION", 11)
    cache = DigestCache(tmp_path / "digest.sqlite3")
    client = _FakeClient(_succeed) if stage == "digest" else CritiqueClient(critique_succeed)
    submit = batch_digest.submit_drawing_batch if stage == "digest" else batch_critique.submit_critique_batch
    try:
        submit([_make_sheet(0)], client=client, cache=cache, model=OPUS)
        record, = cache.pending_batches()
        assert record["schema_version"] == 11
    finally:
        cache.close()


def test_critique_recovery_groups_identical_sheet_pixels_by_slot(tmp_path):
    cache_path = tmp_path / "digest.sqlite3"
    cache = DigestCache(cache_path)
    client = CritiqueClient(critique_succeed)
    first = _make_sheet(0)
    second = replace(first, ref=_make_sheet(1).ref)
    batch = batch_critique.submit_critique_batch([first, second], client=client, cache=cache, model=OPUS, runs=2)
    assert batch.slots[0].cache_key == batch.slots[1].cache_key
    cache.close()
    cache = DigestCache(cache_path)
    recovered = batch_critique.submit_critique_batch([first, second], client=client, cache=cache, model=OPUS, runs=2)
    assert len(client.create_calls) == 1
    assert all(slot.result.cached and slot.result.completed_runs == 2 for slot in recovered.slots)
    assert cache.pending_batches() == []


def test_expiration_uses_creation_time_and_allows_new_work(tmp_path):
    cache = DigestCache(tmp_path / "digest.sqlite3")
    client = _FakeClient(_succeed)
    batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=cache)
    record, = cache.pending_batches()
    record["results_expire_at"] = 0
    cache.record_batch(record)
    batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=cache)
    assert len(client.create_calls) == 2


def test_cache_write_failure_keeps_receipt_for_next_run(tmp_path, monkeypatch):
    cache = DigestCache(tmp_path / "digest.sqlite3")
    client = _FakeClient(_succeed)
    batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, model=OPUS, cache=cache)
    with monkeypatch.context() as patch:
        patch.setattr(cache, "put", lambda *_: None)
        state = recover_pending_batches(client, cache, sleep=NOSLEEP)
        assert state.blocked and len(cache.pending_batches()) == 1
    state = recover_pending_batches(client, cache, sleep=NOSLEEP)
    assert state.recovered and not state.blocked
    assert cache.pending_batches() == []


def test_batch_stage_exception_preserves_cached_sheets(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    cache = DigestCache(tmp_path / "digest.sqlite3")
    client = _FakeClient(_succeed)
    run_pipeline(path, client, cache)
    # Force one sheet to miss in the pre-scan while the other remains available.
    partition = pipeline._level1_partition
    def partial(*args, **kwargs):
        hits, misses, keys, geoms = partition(*args, **kwargs)
        key = next(iter(hits))
        hits.pop(key)
        misses.add(key)
        return hits, misses, keys, geoms
    monkeypatch.setattr(pipeline, "_level1_partition", partial)
    monkeypatch.setattr(pipeline, "_digest_sheets_via_batch", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stage crashed")))
    ctx = run_pipeline(path, client, cache)
    assert ctx.sheet_count == 2 and ctx.ok_sheet_count == 1
    assert any("retry next run" in error for error in ctx.errors)


@pytest.mark.parametrize("fail_once", [True, False])
def test_resubmission_reads_retry_without_another_paid_round(fail_once, monkeypatch):
    # The primary's empty reply is billed; the retry's valid result must survive
    # an interrupted download without resubmitting it or losing prior usage.
    empty = FakeBatchResult(custom_id="sheet__0", result=FakeBatchResultEnvelope(
        type="succeeded", message=FakeMessage(content=[], stop_reason="max_tokens"),
    ))
    client = _FakeClient(_flaky_then_ok({"sheet__0": empty}))
    cache = DigestCache(None, persist=False)
    batch = batch_digest.submit_drawing_batch([_make_sheet(0), _make_sheet(1)], client=client, cache=cache, model=OPUS)
    original = client.messages.batches.results
    reads = []
    server_results = {}

    def results(batch_id):
        round_no = len(client.create_calls)
        server_results.setdefault(round_no, list(original(batch_id)) if round_no not in server_results else [])
        reads.append(round_no)
        for item in server_results[round_no]:
            yield item
            if round_no == 2 and (not fail_once or reads.count(2) == 1):
                raise ConnectionError("retry download dropped")

    monkeypatch.setattr(client.messages.batches, "results", results)
    digests = batch_digest.collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP,
        retry_failed_items=True,
    )
    assert len(client.create_calls) == 2
    assert client.rescue_calls == []
    assert digests[1].ok
    assert reads.count(2) == (2 if fail_once else 3)
    if fail_once:
        assert digests[0].ok and cache.pending_batches() == []
        assert len(digests[0].usage_attempts) == 2
    else:
        assert "retry next run" in digests[0].error
        assert len(cache.pending_batches()) == 1
        assert len(digests[0].usage_attempts) == 1  # the billed primary is retained


def test_harvest_read_retries_the_stream(monkeypatch):
    client = _FakeClient(_succeed)
    cache = DigestCache(None, persist=False)
    batch = batch_digest.submit_drawing_batch([_make_sheet(0), _make_sheet(1)], client=client, cache=cache, model=OPUS)
    original = client.messages.batches.results
    calls = []
    def results(batch_id):
        calls.append(batch_id)
        for item in original(batch_id):
            yield item
            if len(calls) == 1:
                raise ConnectionError("harvest body interrupted")
    monkeypatch.setattr(client.messages.batches, "results", results)
    digests = [None, None]
    outcome = batch_digest._harvest_abandoned_batch(
        batch.submitted_slots, digests, batch_id=batch.batch_id,
        client=client, cache=cache, sleep=NOSLEEP, on_log=None, budget_seconds=30,
    )
    assert outcome.resolved == {0, 1}
    assert len(calls) == 2 and len(client.create_calls) == 1
    assert cache.pending_batches() == []


def test_harvest_collection_failure_defers_instead_of_resubmitting(monkeypatch):
    client = _FakeClient(_succeed)
    cache = DigestCache(None, persist=False)
    batch = batch_digest.submit_drawing_batch([_make_sheet(0)], client=client, cache=cache, model=OPUS)
    client.results_raises = ConnectionError("harvest body unreachable")
    monkeypatch.setattr(batch_digest, "_poll_until_terminal", lambda *a, **k: "stalled")
    digests = batch_digest.collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP,
        retry_failed_items=True,
    )
    assert len(client.create_calls) == 1 and client.rescue_calls == []
    assert "retry next run" in digests[0].error
    assert len(cache.pending_batches()) == 1


def test_run_with_live_batch_does_not_duplicate_it_after_switching_transport(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    cache = DigestCache(tmp_path / "digest.sqlite3")
    client = _FakeClient(_succeed, status="in_progress")
    with monkeypatch.context() as patch:
        patch.setattr(batch_digest, "collect_drawing_batch", lambda *a, **k: (_ for _ in ()).throw(SystemExit()))
        with pytest.raises(SystemExit):
            run_pipeline(path, client, cache)
    ctx = pipeline.extract_drawing_context(
        [path], client=client, cache=cache, use_batch=False,
        rows=1, cols=1, model=OPUS, synthesize=False,
    )
    assert ctx.sheet_count == 2 and ctx.ok_sheet_count == 0
    assert len(client.create_calls) == 1 and client.messages_create_calls == []
    assert all("still processing" in sheet.error for sheet in ctx.sheets)


@pytest.mark.parametrize("stage", ["digest", "critique"])
@pytest.mark.parametrize("cancellation", ["ended", "in_progress", "failed"])
def test_receipt_write_failure_cancels_before_releasing_uploads(stage, cancellation, monkeypatch):
    cache = DigestCache(None, persist=False)
    client = _FakeClient(_succeed) if stage == "digest" else CritiqueClient(critique_succeed)
    module = batch_digest if stage == "digest" else batch_critique
    events = []

    def disk_full(_):
        raise OSError("receipt disk full")

    def cancel(batch_id):
        events.append("cancel")
        client.cancel_calls.append(batch_id)
        if cancellation == "failed":
            raise RuntimeError("cancel refused")
        return SimpleNamespace(processing_status="canceling")

    def retrieve(_):
        # The first check is still canceling: accepting the cancellation is
        # insufficient proof that the remote request no longer uses its files.
        status = "canceling" if "retrieve" not in events else cancellation
        events.append("retrieve")
        return SimpleNamespace(processing_status=status)

    def delete(file_id):
        assert cancellation == "ended" and events.count("retrieve") == 2
        events.append("delete")
        client.files.deleted.append(file_id)

    monkeypatch.setattr(cache, "record_batch", disk_full)
    monkeypatch.setattr(client.messages.batches, "cancel", cancel)
    monkeypatch.setattr(client.messages.batches, "retrieve", retrieve)
    monkeypatch.setattr(client.files, "delete", delete)
    submit = module.submit_drawing_batch if stage == "digest" else module.submit_critique_batch
    if stage == "digest":
        with pytest.raises(BatchReceiptError) as caught:
            submit([_make_sheet(0)], client=client, cache=cache, model=OPUS, sleep=NOSLEEP)
        assert caught.value.files_safe == (cancellation == "ended")
    else:
        batch = submit([_make_sheet(0)], client=client, cache=cache, model=OPUS, sleep=NOSLEEP)
        assert batch.batch_id is None
        assert "receipt persistence failed" in batch.slots[0].result.error
    assert len(client.create_calls) == len(client.cancel_calls) == 1
    assert cache.pending_batches() == []
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids if cancellation == "ended" else [])


@pytest.mark.parametrize("prose", ["", "Real prose, cut off mid-"], ids=["empty", "cut-off"])
@pytest.mark.parametrize("confirmed", [True, False])
def test_retry_receipt_failure_stops_paid_rounds_and_retains_live_uploads(confirmed, prose, monkeypatch):
    # A primary cut off with prose keeps that prose through the deferral, and
    # its error carries the receipt failure as well as its own.
    first = FakeBatchResult(custom_id="sheet__0", result=FakeBatchResultEnvelope(
        type="succeeded", message=FakeMessage(
            content=[FakeTextBlock(text=prose)] if prose else [], stop_reason="max_tokens",
        ),
    ))
    client = _FakeClient(_flaky_then_ok({"sheet__0": first}))
    cache = DigestCache(None, persist=False)
    batch = batch_digest.submit_drawing_batch([_make_sheet(0), _make_sheet(1)], client=client, cache=cache, model=OPUS)
    monkeypatch.setattr(cache, "record_batch", lambda _: (_ for _ in ()).throw(OSError("disk full")))

    def cancel(batch_id):
        client.cancel_calls.append(batch_id)
        return SimpleNamespace(processing_status="ended" if confirmed else "canceling")

    monkeypatch.setattr(client.messages.batches, "cancel", cancel)
    if not confirmed:
        original = client.messages.batches.retrieve
        monkeypatch.setattr(client.messages.batches, "retrieve", lambda bid:
                            original(bid) if len(client.create_calls) == 1 else
                            SimpleNamespace(processing_status="canceling"))
    digests = batch_digest.collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP, cleanup_in_background=False,
        retry_failed_items=True,
    )
    assert len(client.create_calls) == 2 and len(client.cancel_calls) == 1
    assert client.rescue_calls == []
    assert "receipt persistence failed" in digests[0].error
    assert digests[0].text == prose
    assert ("truncated digest" in digests[0].error) == bool(prose)
    assert len(digests[0].usage_attempts) == 1 and digests[1].ok
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids if confirmed else [])


@pytest.mark.parametrize("status", ["ended", "in_progress", "unreadable"])
@pytest.mark.parametrize("legacy_receipt", [False, True])
def test_uncached_restart_switching_to_realtime_never_duplicates_paid_work(tmp_path, monkeypatch, status, legacy_receipt):
    from drawing_analyzer import digest_cache

    path = make_pdf(tmp_path)
    client = _FakeClient(_succeed, status="in_progress" if status == "in_progress" else "ended")
    with monkeypatch.context() as patch:
        patch.setattr(batch_digest, "collect_drawing_batch", lambda *a, **k: (_ for _ in ()).throw(SystemExit()))
        with pytest.raises(SystemExit):
            pipeline.extract_drawing_context(
                [path], client=client, cache=None, use_cache=False, use_batch=True,
                rows=1, cols=1, model=OPUS, synthesize=False,
            )
    store = digest_cache.get_default_digest_cache()
    record, = store.pending_batches()
    assert all(item["level1_key"] for item in record["items"].values())
    if legacy_receipt:
        for item in record["items"].values():
            item["level1_key"] = None
        store.record_batch(record)
    store.close()
    monkeypatch.setattr(digest_cache, "_default_cache", None)
    if status == "unreadable":
        client.results_raises = RuntimeError("download unavailable")
    ctx = pipeline.extract_drawing_context(
        [path], client=client, cache=None, use_cache=False, use_batch=False,
        rows=1, cols=1, model=OPUS, synthesize=False,
    )
    assert len(client.create_calls) == 1 and client.messages_create_calls == []
    assert ctx.sheet_count == 2 and ctx.ok_sheet_count == (2 if status == "ended" else 0)
    if status == "ended":
        assert all(sheet.cached for sheet in ctx.sheets)
        assert digest_cache.get_default_digest_cache().pending_batches() == []
    else:
        assert all("retry" in sheet.error for sheet in ctx.sheets)
        assert len(digest_cache.get_default_digest_cache().pending_batches()) == 1


@pytest.mark.parametrize("status", ["ended", "in_progress", "unreadable"])
@pytest.mark.parametrize("use_batch", [False, True])
@pytest.mark.parametrize("legacy_receipt", [False, True])
def test_uncached_critique_stage_uses_startup_recovery_before_new_calls(tmp_path, monkeypatch, status, use_batch, legacy_receipt):
    from drawing_analyzer import critique, digest_cache
    from drawing_analyzer.models import RunUsage

    path = make_pdf(tmp_path)
    client = CritiqueClient(critique_succeed, status="in_progress" if status == "in_progress" else "ended")
    kwargs = dict(rows=1, cols=1, overlap_frac=0.05, client=client, cache=None,
                  progress=None, total=2, max_workers=1, run_usage=RunUsage())
    with monkeypatch.context() as patch:
        patch.setattr(batch_critique, "collect_critique_batch", lambda *a, **k: (_ for _ in ()).throw(SystemExit()))
        with pytest.raises(SystemExit):
            pipeline._run_critique_stage([path], use_batch=True, **kwargs)
    store = digest_cache.get_default_digest_cache()
    record, = store.pending_batches()
    assert all(item["level1_key"] for item in record["items"].values())
    if legacy_receipt:
        for item in record["items"].values():
            item["level1_key"] = None
        store.record_batch(record)
    store.close()
    monkeypatch.setattr(digest_cache, "_default_cache", None)
    if status == "unreadable":
        client.results_raises = RuntimeError("critique download unavailable")
    recovery = recover_pending_batches(client, None, sleep=NOSLEEP)
    monkeypatch.setattr(critique, "critique_sheet_self_consistent", lambda *a, **k: pytest.fail("paid critique was duplicated"))
    findings, _, errors = pipeline._run_critique_stage([path], use_batch=use_batch, recovery_state=recovery, **kwargs)
    assert len(client.create_calls) == 1
    assert bool(findings) == (status == "ended")
    assert len(errors) == (0 if status == "ended" else 2)
    assert len(digest_cache.get_default_digest_cache().pending_batches()) == (0 if status == "ended" else 1)


def test_unavailable_receipt_store_blocks_uncached_realtime_spending(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    client = _FakeClient(_succeed)
    monkeypatch.setattr(batch_recovery, "recover_pending_batches", lambda *a, **k: (_ for _ in ()).throw(OSError("store locked")))
    ctx = pipeline.extract_drawing_context(
        [path], client=client, cache=None, use_cache=False, use_batch=False,
        rows=1, cols=1, model=OPUS, synthesize=False,
    )
    assert ctx.sheet_count == 2 and ctx.ok_sheet_count == 0
    assert all("recovery store unavailable" in sheet.error for sheet in ctx.sheets)
    assert client.create_calls == client.messages_create_calls == []


def test_uncached_run_does_not_reuse_ordinary_entries_after_receipt_is_collected(tmp_path):
    from drawing_analyzer.digest_cache import get_default_digest_cache

    path = make_pdf(tmp_path)
    client = _FakeClient(_succeed)
    kwargs = dict(client=client, cache=None, use_cache=False, rows=1, cols=1,
                  model=OPUS, synthesize=False)
    first = pipeline.extract_drawing_context([path], use_batch=True, **kwargs)
    assert first.ok_sheet_count == 2 and get_default_digest_cache().pending_batches() == []
    second = pipeline.extract_drawing_context([path], use_batch=False, **kwargs)
    assert second.ok_sheet_count == 2 and second.cached_sheet_count == 0
    assert len(client.create_calls) == 1 and len(client.messages_create_calls) == 2


def test_receipt_write_failure_degrades_pipeline_after_confirmed_cancellation(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    client = _FakeClient(_succeed)
    cache = DigestCache(tmp_path / "digest.sqlite3")
    monkeypatch.setattr(cache, "record_batch", lambda _: (_ for _ in ()).throw(OSError("disk full")))
    ctx = run_pipeline(path, client, cache)
    assert ctx.sheet_count == 2 and ctx.ok_sheet_count == 0
    assert all("receipt persistence failed" in sheet.error for sheet in ctx.sheets)
    assert len(client.create_calls) == len(client.cancel_calls) == 1
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)
