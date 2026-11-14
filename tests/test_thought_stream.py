"""Reasoning summaries for the live view's Thinking tab.

Hermetic: the client is a recording fake, the run binding is a real
``ResourcePressure`` activated for the test, and stream events are the dict
shapes the API sends.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from drawing_analyzer import call_telemetry, resource_pressure, thought_stream
from drawing_analyzer.batch_digest import with_thinking_display
from drawing_analyzer.core import api_config
from drawing_analyzer.thought_stream import (
    MAX_THOUGHT_CHARS,
    MAX_THOUGHTS,
    STATE_DONE,
    STATE_THINKING,
    STATE_WRITING,
    ThoughtStream,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

MODEL = "claude-haiku-5-5"      # adaptive thinking, no refusal fallback: plain namespace


def _thinking(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="thinking", thinking=text, signature="sig")


def _message(*thoughts: str, answer: str = "ok") -> FakeMessage:
    return FakeMessage(
        content=[_thinking(t) for t in thoughts] + [FakeTextBlock(text=answer)],
        stop_reason="end_turn", usage=FakeUsage(input_tokens=10, output_tokens=5),
    )


def _delta(kind: str, **fields) -> dict:
    return {"type": "content_block_delta", "delta": {"type": kind, **fields}}


class _Stream:
    def __init__(self, events, message, seen=None):
        self._events, self._message, self._seen = events, message, seen

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for event in self._events:
            if self._seen is not None:
                self._seen(event)
            yield event

    def get_final_message(self):
        return self._message


class _Client:
    """Records every request; streams ``events`` then returns ``message``."""

    def __init__(self, message, events=(), fail_first=None, on_event=None):
        self.sent: list[dict] = []
        self._message, self._events = message, list(events)
        self._fail, self._on_event = fail_first, on_event
        self.messages = self

    def _take(self, kwargs):
        self.sent.append(kwargs)
        if self._fail is not None:
            exc, self._fail = self._fail, None
            raise exc

    def create(self, **kwargs):
        self._take(kwargs)
        return self._message

    def stream(self, **kwargs):
        self._take(kwargs)
        return _Stream(self._events, self._message, self._on_event)


@pytest.fixture
def run(monkeypatch):
    """A live run's resource record with a Thinking feed, bound to this thread.

    The process-wide display state (the latch, the models seen to accept the
    field) starts fresh and is restored afterwards."""
    monkeypatch.setattr(api_config, "_thinking_display_available", True)
    monkeypatch.setattr(api_config, "_thinking_display_confirmed", set())
    monkeypatch.setattr(api_config, "_display_batches", {})
    pressure = resource_pressure.ResourcePressure()
    pressure.thoughts = ThoughtStream()
    previous = resource_pressure.activate(pressure)
    try:
        yield pressure
    finally:
        resource_pressure.deactivate(pressure, previous)


def _request() -> dict:
    return {"model": MODEL, "max_tokens": 1000, "messages": [],
            "thinking": {"type": "adaptive"}}


def test_a_streamed_call_is_followed_live_and_only_a_run_with_a_feed_asks_for_summaries(run):
    states: list[tuple[str, str, int]] = []
    feed = run.thoughts

    def watch(_event):
        (_v, (th,)) = feed.snapshot()
        states.append((th.state, th.text, th.chars_out))

    events = [
        {"type": "content_block_start", "content_block": {"type": "thinking"}},
        _delta("thinking_delta", thinking="The schedule says 1,500 gpm"),
        _delta("thinking_delta", thinking=" but the one-line says 1,250."),
        {"type": "thinking", "thinking": "IGNORED", "snapshot": "IGNORED"},   # SDK echo
        {"type": "content_block_start", "content_block": {"type": "text"}},
        _delta("text_delta", text="## Sheet"),
        _delta("signature_delta", signature="abc"),
    ]
    client = _Client(_message("unused: the stream already carried it"), events, on_event=watch)
    kwargs = _request()
    with call_telemetry.scope("digest", "SRC-0001:p3"):
        api_config.call_with_refusal_fallback(client, kwargs, model=MODEL, method="stream")

    assert client.sent[0]["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert kwargs["thinking"] == {"type": "adaptive"}          # the caller's dict is its own
    # Seen from inside the stream: thinking first, then writing, text growing.
    assert states[0] == (STATE_THINKING, "", 0)
    assert states[3][0] == STATE_THINKING and states[3][1].endswith("1,250.")
    assert states[-1] == (STATE_WRITING, "The schedule says 1,500 gpm but the one-line says 1,250.", 8)
    (_v, (done,)) = feed.snapshot()
    assert (done.state, done.stage, done.item, done.model) == (
        STATE_DONE, "digest", "SRC-0001:p3", MODEL)
    assert "IGNORED" not in done.text and "unused" not in done.text

    # A run without a feed (no live view) sends exactly what it was handed.
    run.thoughts = None
    plain = _request()
    api_config.call_with_refusal_fallback(client, plain, model=MODEL, method="stream")
    assert client.sent[-1] == plain


@pytest.mark.parametrize("thinking", [
    None,                                              # the model takes no thinking
    {"type": "between_tools"},                         # not plain adaptive thinking
    {"type": "adaptive", "display": "omitted"},        # the caller already chose
])
def test_only_plain_adaptive_thinking_gains_a_display(run, thinking):
    kwargs = {"model": MODEL, "max_tokens": 10, "messages": []}
    if thinking is not None:
        kwargs["thinking"] = thinking
    assert api_config.apply_thinking_display(kwargs) is kwargs


def test_a_non_streamed_reply_is_read_from_its_blocks_and_a_silent_one_leaves_no_entry(run):
    feed = run.thoughts
    with call_telemetry.scope("verify", "QC-014"):
        api_config.call_with_refusal_fallback(
            _Client(_message("The drain is present.", "Rejecting.")), _request(),
            model=MODEL, method="create")
        api_config.call_with_refusal_fallback(
            _Client(_message("")), _request(), model=MODEL, method="create")
    (_v, thoughts) = feed.snapshot()
    assert [(t.stage, t.item, t.text) for t in thoughts] == [
        ("verify", "QC-014", "The drain is present.\n\nRejecting.")]
    assert (feed.seen, feed.with_text) == (2, 1)


def test_a_platform_that_rejects_the_field_costs_one_resend_and_the_feature(run):
    rejection = Exception("thinking.display: Extra inputs are not permitted")
    rejection.status_code = 400
    client = _Client(_message("fine"), fail_first=rejection)
    message = api_config.call_with_refusal_fallback(
        client, _request(), model=MODEL, method="create")
    assert message.stop_reason == "end_turn"
    assert [k["thinking"] for k in client.sent] == [
        {"type": "adaptive", "display": "summarized"}, {"type": "adaptive"}]
    # Latched for the process: the next request does not try again.
    api_config.call_with_refusal_fallback(client, _request(), model=MODEL, method="create")
    assert client.sent[-1]["thinking"] == {"type": "adaptive"}


def test_a_failed_call_closes_its_entry_and_an_unrelated_400_is_not_swallowed(run):
    bad = Exception("messages: at least one message is required")
    bad.status_code = 400
    with pytest.raises(Exception, match="at least one message"):
        api_config.call_with_refusal_fallback(
            _Client(_message("x"), fail_first=bad), _request(), model=MODEL, method="create")
    assert api_config._thinking_display_available
    assert run.thoughts.snapshot()[1] == []            # nothing left listed as in flight


def test_batch_items_ask_for_summaries_and_their_results_join_the_feed_by_sheet(run):
    req = {"custom_id": "c0", "params": _request()}
    shown = with_thinking_display(req)
    assert shown["params"]["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert req["params"]["thinking"] == {"type": "adaptive"}
    with call_telemetry.scope("critique"):
        run.calls.note_batch_submit("b1", [shown], items={"c0": "SRC-0001:p2:1"})
    results = {
        "c0": {"custom_id": "c0", "result": {"type": "succeeded",
                                             "message": _message("Bracing is 45 ft apart.")}},
        "c9": {"custom_id": "c9", "result": {"type": "errored", "error": {"message": "x"}}},
    }
    run.calls.note_batch_results("b1", results)
    thought_stream.note_batch_results("b1", results)
    (_v, (th,)) = run.thoughts.snapshot()
    assert (th.stage, th.item, th.transport, th.text, th.state) == (
        "critique", "SRC-0001:p2:1", "batch", "Bracing is 45 ft apart.", STATE_DONE)

    run.thoughts = None
    assert with_thinking_display(req) is req


class _Batches:
    """A recording ``client.messages.batches``; ``refuse`` fails the next create."""

    def __init__(self, refuse=None):
        self.created: list[list[dict]] = []
        self.refuse = refuse
        self.items: dict[str, list] = {}

    def create(self, requests):
        self.created.append(requests)
        if self.refuse is not None:
            exc, self.refuse = self.refuse, None
            raise exc
        return SimpleNamespace(id=f"b{len(self.created)}")

    def results(self, batch_id):
        return iter(self.items[batch_id])


def _batch_client(**kw):
    batches = _Batches(**kw)
    return SimpleNamespace(messages=SimpleNamespace(batches=batches)), batches


def _asked(requests) -> list[bool]:
    return ["display" in r["params"]["thinking"] for r in requests]


def test_a_batch_submit_refused_for_the_field_is_sent_again_without_it(run):
    from drawing_analyzer.batch_digest import _create_batch

    refusal = Exception("requests.0.params.thinking.display: Extra inputs are not permitted")
    refusal.status_code = 400
    client, batches = _batch_client(refuse=refusal)
    reqs = [{"custom_id": "c0", "params": _request()}]
    with call_telemetry.scope("digest"):
        mb = _create_batch(client, reqs, resubmits_rejected_items=True)
    assert mb.id == "b2"
    assert [_asked(sent) for sent in batches.created] == [[True], [False]]

    # Any other refusal is the caller's to handle, exactly as before.
    other = Exception("requests: too many requests in one batch")
    other.status_code = 400
    before = api_config._thinking_display_available
    client, batches = _batch_client(refuse=other)
    with pytest.raises(Exception, match="too many requests"), call_telemetry.scope("digest"):
        _create_batch(client, reqs, resubmits_rejected_items=True)
    assert api_config._thinking_display_available == before


def test_a_batch_that_cannot_resubmit_asks_only_a_model_seen_to_accept_the_field(run):
    """The critique batch has no resubmission: a rejected item would be a lost
    read. It asks for summaries only once the model has answered a request
    carrying the field, on either transport."""
    from drawing_analyzer import batch_recovery
    from drawing_analyzer.batch_digest import _create_batch

    client, batches = _batch_client()
    reqs = [{"custom_id": "c0", "params": _request()}]
    with call_telemetry.scope("critique"):
        _create_batch(client, reqs)                           # nothing known yet: plain
        _create_batch(client, reqs, resubmits_rejected_items=True)   # the digest may ask
    assert [_asked(sent) for sent in batches.created] == [[False], [True]]

    # That digest batch comes back with a success: the model accepts the field.
    batches.items["b2"] = [{"custom_id": "c0", "result": {
        "type": "succeeded", "message": _message("fine")}}]
    batch_recovery.read_batch_results(client, "b2", sleep=lambda s: None)
    with call_telemetry.scope("critique"):
        _create_batch(client, reqs)
    assert _asked(batches.created[-1]) == [True]

    # A real-time answer confirms a model the same way.
    other = {"custom_id": "c1", "params": {**_request(), "model": "claude-opus-5-5"}}
    assert with_thinking_display(other, confirmed_only=True) is other
    api_config.call_with_refusal_fallback(
        _Client(_message("ok")), {**_request()}, model=MODEL, method="create")
    assert with_thinking_display(other, confirmed_only=True) is other    # a different model
    assert with_thinking_display(reqs[0], confirmed_only=True) is not reqs[0]


def test_a_batch_item_rejected_for_the_field_stops_later_batches_asking(run, monkeypatch):
    from drawing_analyzer import batch_recovery

    req = {"custom_id": "c0", "params": _request()}

    def results(message):
        return [{"custom_id": "c0", "result": {
            "type": "errored", "error": {"type": "error", "error": {
                "type": "invalid_request_error", "message": message}}}}]

    client = SimpleNamespace(messages=SimpleNamespace(batches=SimpleNamespace(
        results=lambda batch_id: iter(results(client.message)))))
    client.message = "max_tokens: must be at least 1"          # some other mistake
    batch_recovery.read_batch_results(client, "b1", sleep=lambda s: None)
    assert with_thinking_display(req) is not req
    client.message = "thinking.display: Extra inputs are not permitted"
    batch_recovery.read_batch_results(client, "b2", sleep=lambda s: None)
    assert with_thinking_display(req) is req                    # the resubmission is plain


def test_the_feed_is_bounded_and_tells_a_reader_only_what_changed():
    feed = ThoughtStream(clock=lambda: 5.0)
    live = feed.open(stage="digest", item="still streaming")
    for i in range(MAX_THOUGHTS + 20):
        th = feed.open(stage="digest", item=f"s{i}")
        feed.add_thinking(th, "x" * (MAX_THOUGHT_CHARS + 50) if i == 0 else f"thought {i}")
        feed.close(th)
    version, thoughts = feed.snapshot()
    assert len(thoughts) == MAX_THOUGHTS
    assert thoughts[0].item == "still streaming" and thoughts[0].open   # in flight: never dropped
    assert thoughts[-1].text == f"thought {MAX_THOUGHTS + 19}"
    assert feed.with_text == MAX_THOUGHTS + 20                          # the counts keep all
    assert feed.snapshot(version) is None
    feed.add_output(live, 12)
    version2, again = feed.snapshot(version)
    # Only the thought that changed is copied again; the rest are reused.
    assert again[0] is not thoughts[0] and again[0].chars_out == 12
    assert all(a is b for a, b in zip(again[1:], thoughts[1:]))
    assert feed.snapshot(version2) is None

    capped = ThoughtStream()
    th = capped.open(stage="digest")
    capped.add_thinking(th, "y" * (MAX_THOUGHT_CHARS + 1))
    capped.add_thinking(th, "more")
    assert (len(th.text), th.truncated) == (MAX_THOUGHT_CHARS, True)
    # A reader's copy is its own: the run keeps writing the original.
    copy = capped.snapshot()[1][0]
    capped.close(th)
    assert copy.open and not th.open


def test_the_env_switch_turns_the_feature_off(monkeypatch):
    monkeypatch.setenv(thought_stream.SHOW_THINKING_ENV, "0")
    assert not thought_stream.show_thinking_enabled()
    monkeypatch.delenv(thought_stream.SHOW_THINKING_ENV)
    assert thought_stream.show_thinking_enabled()
