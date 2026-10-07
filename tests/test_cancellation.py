"""The run kill switch (``drawing_analyzer.cancellation``), on every transport.

A stop must (1) send nothing new, (2) abandon a streamed response mid-flight,
(3) cancel the run's open Message Batches at once, from a background thread,
(4) wake poll and backoff waits, and (5) reach only its own run. The pipeline
tests drive one stop per processing mode — Fast (all real-time), Hybrid
(real-time digest, batched critique) and Economy (batched digest).

Hermetic (I-4): the fakes are the suite's own — ``tests/fixtures/gauntlet.py``
for the real-time stack, ``_FakeClient`` from ``tests/test_drawing_batch.py``
for the Files API + Message Batches.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from drawing_analyzer import cancellation
from drawing_analyzer import resource_pressure as rp
from drawing_analyzer.batch_digest import _create_batch, submit_drawing_batch
from drawing_analyzer.cancellation import CancelToken, RunCancelled
from drawing_analyzer.core.api_config import _dispatch_messages
from drawing_analyzer.digest import transient_retry_wait
from drawing_analyzer.digest_cache import get_default_digest_cache
from drawing_analyzer.pipeline import extract_drawing_context
from tests.fixtures import gauntlet as G
from tests.fixtures.fake_anthropic import (
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    FinalMessageStream,
)
from tests.test_drawing_batch import (
    OPUS,
    _FakeBatches,
    _FakeClient,
    _install_batches,
    _make_sheet,
    _Obj,
    _succeed,
)


@pytest.fixture(autouse=True)
def _sequential_uploads(monkeypatch):
    # The batch fakes are not thread-safe (see tests/test_drawing_batch.py).
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")


@contextmanager
def _bound(token: CancelToken | None):
    previous = cancellation.bind_thread(token)
    try:
        yield token
    finally:
        cancellation.bind_thread(previous)


def _message(text: str = "ok") -> FakeMessage:
    return FakeMessage(
        content=[FakeTextBlock(text=text)],
        usage=FakeUsage(input_tokens=10, output_tokens=2),
        stop_reason="end_turn",
    )


class _RecordingMessages:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kw):
        self.calls.append(kw)
        return _message()

    def stream(self, **kw):
        self.calls.append(kw)
        return FinalMessageStream(_message())


# --------------------------------------------------------------------------- #
# The request gate and the streamed-response abort
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", ["create", "stream"])
def test_a_stopped_run_sends_no_request(method):
    messages = _RecordingMessages()
    client = SimpleNamespace(messages=messages)
    token = CancelToken()
    token.cancel()
    with _bound(token), pytest.raises(RunCancelled):
        _dispatch_messages(client, {"model": OPUS, "messages": []}, method)
    assert messages.calls == []


class _EventStream:
    """A streamed response: ``stop_at`` is the event at which the user presses Stop."""

    def __init__(self, token: CancelToken, *, events: int, stop_at: int | None) -> None:
        self._token = token
        self._events = events
        self._stop_at = stop_at
        self.yielded = 0
        self.closed = False
        self.finalized = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True        # the SDK closes the HTTP response here
        return False

    def __iter__(self):
        for i in range(self._events):
            self.yielded += 1
            if i == self._stop_at:
                self._token.cancel()
            yield {"type": "content_block_delta"}

    def get_final_message(self):
        self.finalized = True
        return _message("complete")


@pytest.mark.parametrize("stop_at", [None, 1])
def test_a_stop_abandons_a_streamed_response_at_its_next_event(stop_at):
    token = CancelToken()
    stream = _EventStream(token, events=6, stop_at=stop_at)
    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: stream))
    with _bound(token):
        if stop_at is None:
            assert _dispatch_messages(client, {"model": OPUS}, "stream").content[0].text == "complete"
            assert stream.yielded == 6
        else:
            with pytest.raises(RunCancelled):
                _dispatch_messages(client, {"model": OPUS}, "stream")
            assert stream.yielded == stop_at + 1   # stopped at that event's boundary
            assert not stream.finalized
    assert stream.closed


# --------------------------------------------------------------------------- #
# Waits wake on a stop
# --------------------------------------------------------------------------- #


def test_pause_wakes_at_once_when_the_run_stops():
    token = CancelToken()
    threading.Timer(0.05, token.cancel).start()
    started = time.monotonic()
    with _bound(token), pytest.raises(RunCancelled):
        cancellation.pause(30.0)                # a real time.sleep becomes a token wait
    assert time.monotonic() - started < 10


def test_retry_backoff_stops_instead_of_retrying():
    class _Overloaded(Exception):
        status_code = 529

    slept: list[float] = []
    token = CancelToken()

    def sleep_then_stop(seconds: float) -> None:
        slept.append(seconds)
        token.cancel()                          # Stop pressed during the backoff

    with _bound(token), pytest.raises(RunCancelled):
        transient_retry_wait(_Overloaded("overloaded"), 0, 3, sleep_then_stop, stage="digest")
    assert len(slept) == 1
    with _bound(None):                          # no run bound: an ordinary retry
        assert transient_retry_wait(_Overloaded("overloaded"), 0, 3, slept.append, stage="digest")


# --------------------------------------------------------------------------- #
# Remote work and thread binding
# --------------------------------------------------------------------------- #


def test_a_stop_cancels_open_remote_work_from_a_background_thread():
    token = CancelToken()
    cancelled: list[tuple[str, bool]] = []
    caller = threading.current_thread()

    def recorder(name):
        return lambda: cancelled.append((name, threading.current_thread() is caller))

    token.track_remote("open", recorder("open"))
    token.track_remote("settled", recorder("settled"))
    token.forget_remote("settled")
    token.cancel()
    token.cancel()                               # idempotent: nothing runs twice
    assert token.wait_for_remote_cancels(5)
    assert cancelled == [("open", False)]        # never on the caller's thread
    # A batch accepted after the stop (its submit was already in flight) is
    # canceled at once, on the submitting thread.
    token.track_remote("late", recorder("late"))
    assert cancelled[-1] == ("late", True)


def test_a_stop_reaches_its_own_runs_workers_and_no_one_elses():
    stopped, running = CancelToken(), CancelToken()

    def pool_sees(token: CancelToken) -> list[bool]:
        with _bound(token):
            with ThreadPoolExecutor(max_workers=2, **rp.worker_binding()) as pool:
                return list(pool.map(lambda _: cancellation.is_cancelled(), range(4)))

    stopped.cancel()
    assert pool_sees(stopped) == [True] * 4
    assert pool_sees(running) == [False] * 4
    unbound: list[bool] = []
    t = threading.Thread(target=lambda: unbound.append(cancellation.is_cancelled()))
    t.start()
    t.join(5)
    assert unbound == [False]                    # no guessing which run it is


# --------------------------------------------------------------------------- #
# Batch submit
# --------------------------------------------------------------------------- #


def test_a_stop_during_batch_upload_sends_no_batch_and_deletes_the_uploads():
    client = _FakeClient(_succeed)
    token = CancelToken()
    upload = client.files.upload

    def upload_then_stop(*, file):
        uploaded = upload(file=file)
        if len(client.files.uploaded_ids) == 7:  # sheet 1's five, then two of sheet 2
            token.cancel()
        return uploaded

    client.files.upload = upload_then_stop
    with _bound(token), pytest.raises(RunCancelled):
        submit_drawing_batch(
            iter([_make_sheet(1), _make_sheet(2), _make_sheet(3)]),
            client=client, model=OPUS, total=3,
        )
    assert client.create_calls == []
    assert len(client.files.uploaded_ids) == 7               # sheet 3 never uploaded
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_a_batch_accepted_after_the_stop_is_canceled_at_once():
    client = _FakeClient(_succeed)
    token = CancelToken()
    settled_mid_submit: list[bool] = []

    class _StopDuringSubmit(_FakeBatches):
        def create(self, *, requests, betas=None):
            token.cancel()                       # Stop lands while the submit is in flight
            settled_mid_submit.append(token.wait_for_remote_cancels(0))
            return super().create(requests=requests)

    _install_batches(client, _StopDuringSubmit(client))
    with _bound(token):
        mb = _create_batch(client, [{"custom_id": "sheet__0", "params": {}}])
    assert client.cancel_calls == [mb.id]
    # A caller that waits for the stop before exiting must not be told it has
    # settled while the accepted batch is still uncanceled.
    assert settled_mid_submit == [False]
    assert token.wait_for_remote_cancels(0)


# --------------------------------------------------------------------------- #
# One stop per processing mode, through the whole pipeline
# --------------------------------------------------------------------------- #


class _QueuedUntilStop(_FakeBatches):
    """A batch still queued when the user presses Stop (on the first poll)."""

    def __init__(self, client, token: CancelToken) -> None:
        super().__init__(client)
        self._token = token
        self.realtime_calls_at_stop: int | None = None

    def retrieve(self, batch_id):
        self._c.retrieve_calls.append(batch_id)
        if self._token.cancelled:                # a poll that ignored the stop
            return _Obj(processing_status="ended", request_counts=_Obj(
                succeeded=len(self._c.submitted), errored=0, canceled=0,
                expired=0, processing=0))
        self.realtime_calls_at_stop = len(self._c.messages_create_calls)
        self._token.cancel()
        return _Obj(
            processing_status="in_progress",
            request_counts=_Obj(succeeded=0, errored=0, canceled=0, expired=0,
                                processing=len(self._c.submitted)),
        )


def _two_sheet_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page(width=792, height=612).insert_text((72, 72), f"SHEET M-10{i + 1} TEST")
    path = tmp_path / "set.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.parametrize("mode", ["economy", "hybrid"])
def test_stopping_a_batched_run_cancels_its_batch_and_keeps_the_receipt(tmp_path, mode):
    """Economy stops during the digest batch, Hybrid during the critique batch.

    Either way: the open batch is canceled remotely, nothing new is sent after
    the stop, the uploads stay for the batch's in-flight items, and the
    receipt stays so the next run collects whatever the batch finished first.
    """
    path = _two_sheet_pdf(tmp_path)
    client = _FakeClient(_succeed)
    token = CancelToken()
    batches = _QueuedUntilStop(client, token)
    _install_batches(client, batches)
    transports = (
        {"use_batch": True}
        if mode == "economy"
        else {"use_batch": False, "critique_use_batch": True, "critique": True}
    )
    with pytest.raises(RunCancelled):
        extract_drawing_context(
            [path], client=client, rows=2, cols=2, synthesize=False,
            cancel=token, **transports,
        )
    assert token.wait_for_remote_cancels(5)
    assert client.cancel_calls == ["batch_abc"]
    assert len(client.create_calls) == 1                      # no resubmission
    assert len(client.messages_create_calls) == batches.realtime_calls_at_stop
    assert client.files.deleted == []
    receipts = [r["batch_id"] for r in get_default_digest_cache().pending_batches()]
    assert receipts == ["batch_abc"]


def test_a_stop_before_critique_releases_the_retained_digest_uploads(tmp_path, monkeypatch):
    """Economy exhaustive: the finished digest batch's uploads are retained for
    the critique to reuse. A stop before the critique starts (here, during set
    identity) must still delete them, not leave them to a later run's reaper."""
    from drawing_analyzer import batch_digest

    monkeypatch.setattr(batch_digest, "_run_in_background", lambda fn: fn())
    path = _two_sheet_pdf(tmp_path)
    token = CancelToken()

    def stop_at_first_realtime_call(kwargs):
        token.cancel()
        return _message("{}")

    client = _FakeClient(_succeed, inline_responder=stop_at_first_realtime_call)
    with pytest.raises(RunCancelled):
        extract_drawing_context(
            [path], client=client, rows=2, cols=2, synthesize=False, critique=True,
            use_batch=True, critique_use_batch=True, cancel=token,
        )
    assert len(client.create_calls) == 1                      # the digest batch only
    assert client.files.uploaded_ids
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_stopping_a_fast_run_mid_critique_sends_nothing_after_the_stop(tmp_path):
    """Fast: every read is real-time. Stop during the first sheet's critique."""
    token = CancelToken()

    class _StopAtFirstCritique(G.ScriptedQCClient):
        def _critique(self, text, system=""):
            token.cancel()
            return super()._critique(text, system)

    base = G.mini_client()
    client = _StopAtFirstCritique(
        base._sheets, synthesis_text=base._synthesis_text, cross_findings=[],
    )
    with pytest.raises(RunCancelled):
        extract_drawing_context(
            G.build_mini_set(tmp_path / "set"), client=client, rows=2, cols=2,
            qc_markups=True, max_workers=1, qc_work_dir=tmp_path / "qc",
            cancel=token,
        )
    assert sum(client.digest_calls.values()) == 2             # both sheets read first
    assert client.critique_calls == {"VAV-3": 1}              # the read in flight only
    assert (client.synth_calls, client.cross_calls, client.harvest_calls,
            client.verify_calls, client.investigate_calls) == (0, 0, 0, 0, 0)
    assert client.citation_requests == []
