"""Per-call agent telemetry (``call_telemetry.py``).

Every model request is recorded where it is sent — ``_dispatch_messages`` for
real-time calls, ``_create_batch`` + ``read_batch_results`` for batch items —
so these tests drive those real entry points with the shared fakes and read
the record back: what the call was given, what it used, and the per-stage
headroom verdict derived from it. The end-to-end cross-check (one record per
billed response, under the usage ledger's own stage names) rides the gauntlet
oracle in ``test_drawing_acceptance.py``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from drawing_analyzer import call_telemetry as ct
from drawing_analyzer import cancellation
from drawing_analyzer import resource_pressure as rp
from drawing_analyzer.batch_digest import _create_batch
from drawing_analyzer.batch_recovery import read_batch_results
from drawing_analyzer.cancellation import CancelToken, RunCancelled
from drawing_analyzer.core.api_config import _dispatch_messages
from tests.fixtures.fake_anthropic import (
    FakeBatchResult,
    FakeBatchResultEnvelope,
    FakeMessage,
    FakeServerToolUse,
    FakeTextBlock,
    FakeToolUseBlock,
    FakeUsage,
    FakeWebSearchResultBlock,
    batch_errored_result,
)

MODEL = "claude-sonnet-5-5"


@pytest.fixture
def active():
    """A run recorder, bound to this thread for the test."""
    pressure = rp.ResourcePressure()
    previous = rp.activate(pressure)
    try:
        yield pressure
    finally:
        pressure.close()
        rp.deactivate(pressure, previous)


class _Scripted:
    """``messages.create`` answers with the scripted replies, in order."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.messages = self

    def create(self, **kwargs):
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _reply(out: int = 100, stop: str = "end_turn", content=None, server=None) -> FakeMessage:
    return FakeMessage(
        content=content or [FakeTextBlock(text="ok")],
        stop_reason=stop,
        usage=FakeUsage(input_tokens=10, output_tokens=out, server_tool_use=server),
    )


def _kwargs(*, max_tokens=1000, tools=None, tool_choice=None, structured=False) -> dict:
    output_config: dict = {"effort": "medium"}
    if structured:
        output_config["format"] = {"type": "json_schema", "schema": {"type": "object"}}
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": output_config,
        "messages": [{"role": "user", "content": "check this"}],
    }
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    return kwargs


def _send(client, stage="verify", item="", limits=None, **request):
    with ct.scope(stage, item, **(limits or {})):
        try:
            _dispatch_messages(client, _kwargs(**request), "create")
        except Exception:  # noqa: BLE001 - a failing call is a case under test
            pass


WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 2}
CROP = {"name": "crop_region", "input_schema": {"type": "object"}}


# Each case: the calls one stage makes (send kwargs, reply) → the verdict and
# the counter that carries it.
_CASES = {
    "clean": (
        [({"item": "a"}, _reply(out=100))],
        ct.HEADROOM_ADEQUATE, {"near_cap_calls": 0, "max_tokens_stops": 0},
    ),
    "near_cap": (
        [({"item": "a"}, _reply(out=950))],
        ct.HEADROOM_TIGHT, {"near_cap_calls": 1},
    ),
    "cap_hit_recovered_by_a_resend": (
        [({"item": "a"}, _reply(out=1000, stop="max_tokens")),
         ({"item": "a", "max_tokens": 2000}, _reply(out=900))],
        ct.HEADROOM_TIGHT, {"max_tokens_stops": 1, "max_tokens_unrecovered": 0},
    ),
    "cap_hit_unrecovered": (
        [({"item": "a"}, _reply(out=1000, stop="max_tokens")),
         ({"item": "b"}, _reply(out=100))],
        ct.HEADROOM_STARVED, {"max_tokens_unrecovered": 1},
    ),
    "tool_used_to_its_limit": (
        [({"item": "a", "tools": [WEB_SEARCH]},
          _reply(server=FakeServerToolUse(web_search_requests=2)))],
        ct.HEADROOM_TIGHT, {"tool_limit_reached_calls": {"web_search": 1}},
    ),
    "tool_refused_past_its_limit": (
        [({"item": "a", "tools": [WEB_SEARCH]}, _reply(content=[
            FakeWebSearchResultBlock(content={"type": "web_search_tool_result_error",
                                              "error_code": "max_uses_exceeded"}),
            FakeTextBlock(text="ok"),
        ]))],
        ct.HEADROOM_STARVED, {"tool_errors": {"max_uses_exceeded": 1}},
    ),
    "pause_turn_resumed": (
        [({"item": "a"}, _reply(stop="pause_turn")), ({"item": "a"}, _reply())],
        ct.HEADROOM_TIGHT, {"pause_turns": 1, "pause_turns_unresolved": 0},
    ),
    "pause_turn_unresolved": (
        [({"item": "a"}, _reply(stop="pause_turn"))],
        ct.HEADROOM_STARVED, {"pause_turns_unresolved": 1},
    ),
    "forced_no_tools_close": (
        [({"item": "a", "tools": [CROP], "tool_choice": {"type": "none"}}, _reply())],
        ct.HEADROOM_TIGHT, {"forced_closes": 1},
    ),
    "item_asked_for_its_whole_allotment": (
        [({"item": "a", "tools": [CROP], "limits": {"evidence_rounds": 2}},
          _reply(stop="tool_use", content=[FakeToolUseBlock(name="crop_region", input={}),
                                           FakeToolUseBlock(name="crop_region", input={})])),
         ({"item": "a", "tools": [CROP], "limits": {"evidence_rounds": 2}}, _reply())],
        ct.HEADROOM_TIGHT,
        {"item_limits": {"evidence_rounds": {"limit": 2, "items": 1,
                                             "items_at_limit": 1, "max_requested": 2}}},
    ),
    "ability_lost_mid_run": (
        [({"item": "a", "structured": True}, _reply()), ({"item": "b"}, _reply())],
        ct.HEADROOM_TIGHT, {"abilities_dropped": ["structured outputs"]},
    ),
    "every_call_failed": (
        [({"item": "a"}, RuntimeError("boom"))],
        ct.HEADROOM_NOT_ASSESSED, {"errors": 1, "answered_calls": 0},
    ),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_stage_headroom_verdicts(active, case):
    calls, verdict, counters = _CASES[case]
    client = _Scripted([reply for _, reply in calls])
    for request, _ in calls:
        _send(client, **request)
    (stage,) = active.calls.stage_summaries()
    assert stage["stage"] == "verify"
    assert stage["verdict"] == verdict
    for key, value in counters.items():
        assert stage[key] == value, key
    assert active.calls.headroom_status == verdict
    assert bool(stage["reasons"]) == (verdict in (ct.HEADROOM_TIGHT, ct.HEADROOM_STARVED))


def test_an_exhausted_budget_starves_its_stage_even_without_a_call(active):
    # Budget notes use the retry-loop name; the record maps it onto the usage
    # family the headroom table (and the run.log usage table) uses.
    active.note_budget_exhausted("investigation", "finding_cap", count=3)
    (stage,) = active.calls.stage_summaries()
    assert (stage["stage"], stage["verdict"]) == ("investigate", ct.HEADROOM_STARVED)
    assert stage["budget_exhaustions"] == [{"kind": "finding_cap", "count": 3, "detail": ""}]


def test_the_record_carries_what_was_sent_and_what_came_back(active):
    client = _Scripted([_reply(out=400, content=[
        FakeTextBlock(text="ok"), FakeToolUseBlock(name="crop_region", input={}),
    ], stop="tool_use")])
    kwargs = _kwargs(max_tokens=2000, tools=[CROP, WEB_SEARCH])
    kwargs["messages"] = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "data": "AAAA"}},
        {"type": "text", "text": "PRIVATE PROMPT TEXT"},
    ]}]
    kwargs["system"] = "PRIVATE SYSTEM PROMPT"
    with ct.scope("investigate", "f-1", evidence_rounds=6):
        _dispatch_messages(client, kwargs, "create")
    (record,) = active.calls.records
    assert (record.stage, record.item, record.model) == ("investigate", "f-1", MODEL)
    assert (record.effort, record.thinking, record.max_tokens) == ("medium", "adaptive", 2000)
    assert record.tools == ("crop_region", "web_search")
    assert record.tool_limits == {"web_search": 2}
    assert record.item_limits == {"evidence_rounds": 6}
    assert record.images == 1
    assert (record.outcome, record.output_tokens, record.tool_calls) == (
        ct.OUTCOME_TOOL_USE, 400, {"crop_region": 1},
    )
    assert record.output_fraction == pytest.approx(0.2)
    assert record.duration_seconds is not None
    # Request shape and counts only: no prompt, no image bytes.
    dumped = json.dumps(record.to_dict())
    assert "PRIVATE" not in dumped and "AAAA" not in dumped


def test_a_failed_call_records_the_error_and_a_stopped_one_records_the_stop(active):
    exc = RuntimeError("upstream 529")
    exc.status_code = 529
    exc.request_id = "req_529"
    _send(_Scripted([exc]), item="a")
    failed = active.calls.records[-1]
    assert (failed.outcome, failed.request_id) == (ct.OUTCOME_ERROR, "req_529")
    assert "status=529" in failed.error

    token = CancelToken()

    class _StoppedStream:
        """A streamed reply during which the user presses Stop."""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def __iter__(self):
            token.cancel()
            yield {"type": "content_block_delta"}

    client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: _StoppedStream()))
    previous = cancellation.bind_thread(token)
    try:
        with ct.scope("digest", "SRC-0001:p0"), pytest.raises(RunCancelled):
            _dispatch_messages(client, _kwargs(), "stream")
    finally:
        cancellation.bind_thread(previous)
    stopped = active.calls.records[-1]
    assert (stopped.stage, stopped.outcome) == ("digest", ct.OUTCOME_CANCELLED)


def test_a_call_outside_any_scope_is_labeled_with_its_module(active):
    _dispatch_messages(_Scripted([_reply()]), _kwargs(), "create")
    (record,) = active.calls.records
    assert record.stage == f"{ct.UNATTRIBUTED} (test_call_telemetry)"


def test_no_run_records_nothing():
    assert ct.current() is None
    assert _dispatch_messages(_Scripted([_reply()]), _kwargs(), "create").stop_reason == "end_turn"


class _BatchClient:
    def __init__(self, results: dict) -> None:
        self._results = results
        self.messages = SimpleNamespace(batches=self)

    def create(self, requests):
        return SimpleNamespace(id="msgbatch_1")

    def results(self, batch_id):
        return iter(self._results.get(batch_id, []))


def test_batch_items_are_recorded_at_submit_and_filled_from_results(active):
    reqs = [
        {"custom_id": "sheet__0", "params": _kwargs(max_tokens=4000)},
        {"custom_id": "sheet__1", "params": _kwargs(max_tokens=4000)},
    ]
    client = _BatchClient({
        "msgbatch_1": [
            FakeBatchResult(custom_id="sheet__0", result=FakeBatchResultEnvelope(
                type="succeeded", message=_reply(out=3900, stop="max_tokens"))),
            batch_errored_result("sheet__1"),
        ],
        "msgbatch_earlier_run": [
            FakeBatchResult(custom_id="sheet__7", result=FakeBatchResultEnvelope(
                type="succeeded", message=_reply())),
        ],
    })
    with ct.scope("digest"):
        _create_batch(client, reqs, items={"sheet__0": "SRC-0001:p0", "sheet__1": "SRC-0001:p1"})
    pending = {r.custom_id: r.outcome for r in active.calls.records}
    assert pending == {"sheet__0": ct.OUTCOME_PENDING, "sheet__1": ct.OUTCOME_PENDING}

    read_batch_results(client, "msgbatch_1", sleep=lambda s: None)
    read_batch_results(client, "msgbatch_earlier_run", sleep=lambda s: None)
    by_id = {r.custom_id: r for r in active.calls.records}
    assert by_id["sheet__0"].item == "SRC-0001:p0"
    assert (by_id["sheet__0"].transport, by_id["sheet__0"].max_tokens) == (ct.TRANSPORT_BATCH, 4000)
    assert by_id["sheet__0"].outcome == ct.OUTCOME_MAX_TOKENS
    assert by_id["sheet__1"].outcome == ct.OUTCOME_ERROR
    # A batch this run did not submit (receipt recovery) still gets a record.
    assert by_id["sheet__7"].stage == "recovered_batch"
    digest = next(s for s in active.calls.stage_summaries() if s["stage"] == "digest")
    assert (digest["batch_calls"], digest["verdict"]) == (2, ct.HEADROOM_STARVED)


def test_model_map_counts_each_model_where_it_ran(active):
    client = _Scripted([_reply(), _reply(), _reply()])
    _send(client, stage="verify", item="a")
    _send(client, stage="verify", item="b")
    _send(client, stage="citation", item="NFPA 13 9.2.1")
    rows = {(r["model"], r["stage"]): (r["calls"], r["items"]) for r in active.calls.model_map()}
    assert rows == {(MODEL, "verify"): (2, 2), (MODEL, "citation"): (1, 1)}


def test_storage_is_bounded_but_every_call_is_counted(active, monkeypatch):
    monkeypatch.setattr(ct, "MAX_STORED_CALLS", 2)
    client = _Scripted([_reply() for _ in range(5)])
    for i in range(5):
        _send(client, item=str(i))
    assert (len(active.calls.records), active.calls.calls_seen, active.calls.dropped) == (2, 5, 3)
