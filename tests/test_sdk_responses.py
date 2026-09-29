"""The response-side fixtures, held to the installed SDK (remediation WP-02.3, U26).

WP-02.2 made the fakes refuse what the SDK refuses on the way *out*. This file
holds the way *in*: every response shape in ``tests/fixtures/sdk_responses.py``
parses with the SDK's own models; ``sdk_transport.message_sse`` stopped at each
cut and ended each way does to the real SDK what the API would; the fakes'
responses are the installed SDK's own models; ``FinalMessageStream`` fails
mid-stream exactly as the SDK's stream does; and the stub's knobs (a batch
item's envelope, the status sequence, the result order, the serving model)
reach the SDK as the API sends them.

The SDK facts these rest on are pinned first (the owner's rule since WP-02.2:
derive from the installed SDK, keep one tripwire), measured identical on SDK
1.7.0 and 1.8.0.
"""
from __future__ import annotations

import json
import os
import typing
from pathlib import Path

import anthropic
import httpx2
import pytest
from anthropic.types import ErrorObject, Message, ParsedMessage, TextBlock, ToolUseBlock, Usage
from anthropic.types.beta import BetaMessage, BetaUsage
from anthropic.types.beta.parsed_beta_message import ParsedBetaMessage
from anthropic.types.messages import (
    MessageBatchCanceledResult,
    MessageBatchErroredResult,
    MessageBatchExpiredResult,
    MessageBatchIndividualResponse,
    MessageBatchSucceededResult,
)

from tests.fixtures import fake_anthropic as F
from tests.fixtures import sdk_responses as R
from tests.fixtures.sdk_transport import (
    DROPPED,
    AnthropicAPIStub,
    api_json,
    message_json,
    message_sse,
    sse_response,
)

pytest_plugins = ["pytester"]

OPUS = "claude-opus-5"
_MSG = [{"role": "user", "content": "x"}]


def _client(handler) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="sk-ant-" + "resp-" + "0" * 20,          # built at runtime: never a key
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )


def _plain(obj) -> object:
    """An SDK object or API dict as plain JSON, nulls dropped (the SDK omits
    unset optional fields; the API may send them as null)."""
    if hasattr(obj, "to_dict"):
        obj = obj.to_dict()
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_plain(v) for v in obj]
    return obj


def _reply(stop_reason: str = "end_turn") -> dict:
    return R.message(
        [R.text("Sheet M-101 - Mechanical.\n```json\n{\"findings\": []}\n```"),
         R.tool_use("crop_region", {"rect": [1, 2, 3, 4]})],
        stop_reason=stop_reason,
        usage_=R.usage(120, 45, cache_read=3, cache_write=7),
    )


# --------------------------------------------------------------------------- #
# The SDK facts (the tripwire: an upgrade that changes one fails here)
# --------------------------------------------------------------------------- #

# The batch-item error types, measured (SDK 1.7.0 and 1.8.0). The fixtures
# derive the set from the SDK; this literal only notices when it moves.
_MEASURED_ERROR_TYPES = (
    "invalid_request_error", "authentication_error", "billing_error", "permission_error",
    "not_found_error", "rate_limit_error", "timeout_error", "api_error", "overloaded_error",
)


def _members(tp) -> tuple:
    """A union's member types, through an ``Annotated`` wrapper if any."""
    if typing.get_origin(tp) is typing.Annotated:
        tp = typing.get_args(tp)[0]
    return typing.get_args(tp)


def test_fact_the_batch_error_types_are_the_measured_ones():
    assert R.ERROR_TYPES == _MEASURED_ERROR_TYPES
    assert len(_members(ErrorObject)) == len(R.ERROR_TYPES)


def test_fact_the_response_fields_the_fixtures_build_exist_on_the_sdk_models():
    assert {"cache_creation", "cache_creation_input_tokens", "cache_read_input_tokens",
            "output_tokens_details", "server_tool_use", "service_tier",
            "inference_geo"} <= set(Usage.model_fields)
    assert {"iterations", "fallback_credit", "speed"} <= set(BetaUsage.model_fields) - set(Usage.model_fields)
    assert "stop_details" in Message.model_fields and "stop_details" in BetaMessage.model_fields
    for name in ("cache_creation_input_tokens", "cache_read_input_tokens", "server_tool_use"):
        assert not Usage.model_fields[name].is_required()        # the API may send null
    assert {"web_search_requests", "web_fetch_requests"} == set(anthropic.types.ServerToolUsage.model_fields)
    assert {c.__name__ for c in _members(MessageBatchIndividualResponse.model_fields["result"].annotation)} == {
        "MessageBatchSucceededResult", "MessageBatchErroredResult",
        "MessageBatchCanceledResult", "MessageBatchExpiredResult"}


# --------------------------------------------------------------------------- #
# Every shape parses with the SDK's own model
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("error_type", R.ERROR_TYPES, ids=list(R.ERROR_TYPES))
def test_an_errored_item_is_nested_as_the_sdk_reads_it(error_type):
    line = R.individual("sheet-1", R.errored(error_type, "detail"))
    parsed = MessageBatchIndividualResponse.model_validate(line)

    assert isinstance(parsed.result, MessageBatchErroredResult)
    assert parsed.result.error.type == "error"                 # the envelope, not the error
    assert parsed.result.error.error.type == error_type
    assert parsed.result.error.error.message == "detail"


@pytest.mark.parametrize("envelope, cls", [(R.CANCELED, MessageBatchCanceledResult),
                                           (R.EXPIRED, MessageBatchExpiredResult)],
                         ids=["canceled", "expired"])
def test_a_canceled_or_expired_item_carries_only_its_type(envelope, cls):
    parsed = MessageBatchIndividualResponse.model_validate(R.individual("sheet-1", envelope))

    assert isinstance(parsed.result, cls)
    assert set(type(parsed.result).model_fields) == {"type"}
    assert not hasattr(parsed.result, "message") and not hasattr(parsed.result, "error")


def test_usage_shapes_parse_with_the_sdk():
    nulls = Usage.model_validate(R.usage(cache_read=None, cache_write=None))
    assert (nulls.cache_read_input_tokens, nulls.cache_creation_input_tokens, nulls.server_tool_use) == (None, None, None)

    split = Usage.model_validate(R.usage(cache_split=(300, 700), cache_read=400))
    assert split.cache_creation_input_tokens == 1000
    assert (split.cache_creation.ephemeral_5m_input_tokens, split.cache_creation.ephemeral_1h_input_tokens) == (300, 700)

    tools = Usage.model_validate(R.usage(server_tools=R.server_tool_use(web_search=2, web_fetch=3),
                                         output_tokens_details={"thinking_tokens": 20}))
    assert (tools.server_tool_use.web_search_requests, tools.server_tool_use.web_fetch_requests) == (2, 3)
    assert tools.output_tokens_details.thinking_tokens == 20

    beta = BetaUsage.model_validate(R.usage(
        160, 32,
        iterations=[R.iteration("message", input_tokens=60, output_tokens=12),
                    R.iteration("fallback_message", model="claude-opus-4-8", input_tokens=100, output_tokens=20)],
        fallback_credit={"status": {"type": "redeemed"}}))
    assert [type(i).__name__ for i in beta.iterations] == ["BetaMessageIterationUsage",
                                                           "BetaFallbackMessageIterationUsage"]
    assert beta.iterations[1].model == "claude-opus-4-8"
    assert beta.fallback_credit.status.type == "redeemed"


def test_refusal_stop_details_parse_on_both_namespaces():
    body = R.message([R.text("I can't help with that.")], stop_reason="refusal",
                     stop_details=R.refusal_stop_details("cyber", explanation="declined",
                                                         recommended_model="claude-opus-4-8"))
    plain, beta = Message.model_validate(body), BetaMessage.model_validate(body)

    assert plain.stop_details.category == beta.stop_details.category == "cyber"
    assert beta.stop_details.recommended_model == "claude-opus-4-8"


def test_a_spliced_fallback_is_a_beta_message_whose_texts_rejoin_to_the_original():
    original = _reply()
    spliced = R.splice_fallback(original, 17, to_model="claude-opus-4-8")
    parsed = BetaMessage.model_validate(spliced)

    assert [b.type for b in parsed.content] == ["text", "fallback", "text", "tool_use"]
    assert parsed.model == "claude-opus-4-8"
    assert (parsed.content[1].from_.model, parsed.content[1].to.model) == (OPUS, "claude-opus-4-8")
    assert parsed.content[0].text + parsed.content[2].text == original["content"][0]["text"]


def test_a_parsed_model_serializes_under_the_apis_field_names():
    # ``from`` is a Python keyword, so the SDK's fallback block names the
    # field ``from_`` and aliases it to the wire name. A reply built as an SDK
    # model must reach the SDK as the API would send it.
    parsed = BetaMessage.model_validate(R.splice_fallback(_reply(), 17, to_model="claude-opus-4-8"))

    for wire in (api_json(parsed), F._to_dict(parsed)):
        block = wire["content"][1]
        assert "from" in block and "from_" not in block
        assert BetaMessage.model_validate(wire) == parsed


def test_a_parsed_fallback_reply_reaches_the_sdk_through_the_stub():
    parsed = BetaMessage.model_validate(R.splice_fallback(_reply(), 17, to_model="claude-opus-4-8"))
    stub = AnthropicAPIStub(lambda _params: parsed)
    reply = stub.client().beta.messages.create(
        model=OPUS, max_tokens=1_000, messages=_MSG, betas=["server-side-fallback-2026-07-01"])

    fallback = reply.content[1]
    assert fallback.type == "fallback"
    assert (fallback.from_.model, fallback.to.model) == (OPUS, "claude-opus-4-8")


# --------------------------------------------------------------------------- #
# Event streams through the real SDK: every cut, every end
# --------------------------------------------------------------------------- #


def _through_sdk(body: dict, cut, end, *, beta: bool = False):
    """Run the real SDK over ``message_sse(body, cut, end)``; return
    ``(outcome, snapshot)`` where outcome is ``("returned", message)`` or
    ``("raised", exc)`` and snapshot the stream's ``current_message_snapshot``
    (or the ``AssertionError`` the SDK raises for it)."""
    client = _client(lambda request: sse_response(body, cut=cut, end=end))
    target = client.beta.messages if beta else client.messages
    kwargs = dict(model=OPUS, max_tokens=64_000, messages=_MSG)
    if beta:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
    stream = None
    try:
        with target.stream(**kwargs) as stream:
            outcome = ("returned", stream.get_final_message())
    except Exception as exc:  # noqa: BLE001 - the outcome under test
        outcome = ("raised", exc)
    try:
        snapshot = stream.current_message_snapshot
    except AssertionError as exc:
        snapshot = exc
    return outcome, snapshot


# Every cut with every end, and the complete stream (which only ends cleanly).
_SHAPES = [(None, "eof")] + [(cut, end) for cut in R.CUTS for end in R.ENDS]
_SHAPE_IDS = ["complete"] + [f"{cut}-{end}" for cut in R.CUTS for end in R.ENDS]


@pytest.mark.parametrize("cut, end", _SHAPES, ids=_SHAPE_IDS)
def test_the_sdk_on_each_cut_and_end(cut, end):
    body = _reply()
    outcome, snapshot = _through_sdk(body, cut, end)
    expected = R.partial_message(body, cut)

    # What the stream raises is decided by how it ended, never by the cut.
    if end == "drop":
        assert outcome[0] == "raised" and type(outcome[1]) is httpx2.RemoteProtocolError
        assert str(outcome[1]) == DROPPED
    elif end == "error":
        exc = outcome[1]
        assert outcome[0] == "raised" and type(exc) is anthropic.APIStatusError
        assert (exc.status_code, exc.type) == (200, "overloaded_error")
    elif cut == "empty":
        assert outcome[0] == "raised" and type(outcome[1]) is AssertionError
    else:
        assert outcome[0] == "returned"
        assert _plain(outcome[1]) == _plain(expected)
    # The snapshot is the partial read, or none at all before message_start.
    if expected is None:
        assert isinstance(snapshot, AssertionError)
    else:
        assert _plain(snapshot) == _plain(expected)


def test_the_partial_message_rules_the_fixtures_rely_on():
    body = _reply()
    # Before message_delta the read has no stop reason and message_start's usage.
    early = R.partial_message(body, "after_content")
    assert early["stop_reason"] is None and early["usage"]["output_tokens"] == 0
    assert early["usage"]["input_tokens"] == 120
    # A stream missing only message_stop is indistinguishable from a complete one.
    assert R.partial_message(body, "before_message_stop") == R.partial_message(body, None)
    assert R.partial_message(body, None)["stop_reason"] == "end_turn"
    # Half the first text block, the block not closed.
    half = R.partial_message(body, "after_text")["content"][0]["text"]
    assert body["content"][0]["text"].startswith(half) and 0 < len(half) < len(body["content"][0]["text"])
    assert R.partial_message(body, "empty") is None


def test_the_beta_accumulator_takes_the_serving_model_from_a_fallback_block():
    spliced = R.splice_fallback(_reply(), 17, to_model="claude-opus-4-8")
    spliced["model"] = OPUS                    # message_start names the requested model
    (kind, final), _snap = _through_sdk(spliced, None, "eof", beta=True)

    assert kind == "returned" and final.model == "claude-opus-4-8"
    assert [b.type for b in final.content] == ["text", "fallback", "text", "tool_use"]


# --------------------------------------------------------------------------- #
# FinalMessageStream fails exactly as the SDK's stream does
# --------------------------------------------------------------------------- #


def _through_fake(body: dict, cut, end, *, beta: bool = False):
    """``_through_sdk``'s twin over a fake: the stream is reached through the
    namespace's checked entry point, as production reaches it."""
    streams: list = []

    def stream(**_kwargs):
        streams.append(F.FinalMessageStream(body, cut=cut, end=end))
        return streams[-1]

    messages, beta_client = F.sdk_namespaces(stream=stream)
    target = beta_client.messages if beta else messages
    kwargs = dict(model=OPUS, max_tokens=64_000, messages=_MSG)
    if beta:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
    try:
        with target.stream(**kwargs) as s:
            outcome = ("returned", s.get_final_message())
    except Exception as exc:  # noqa: BLE001 - the outcome under test
        outcome = ("raised", exc)
    try:
        snapshot = streams[0].current_message_snapshot
    except AssertionError as exc:
        snapshot = exc
    return outcome, snapshot


_NAMESPACE_IDS = ["plain", "beta"]


@pytest.mark.parametrize("beta", [False, True], ids=_NAMESPACE_IDS)
@pytest.mark.parametrize("cut, end", _SHAPES, ids=_SHAPE_IDS)
def test_final_message_stream_mirrors_the_sdk(cut, end, beta):
    body = _reply()
    (real_kind, real), real_snap = _through_sdk(body, cut, end, beta=beta)
    (fake_kind, fake), fake_snap = _through_fake(body, cut, end, beta=beta)

    assert fake_kind == real_kind
    if real_kind == "raised":
        assert type(fake) is type(real)
        assert str(fake) == str(real)
        assert getattr(fake, "status_code", None) == getattr(real, "status_code", None)
        assert getattr(fake, "type", None) == getattr(real, "type", None)
    else:
        assert _plain(fake) == _plain(real)
    if isinstance(real_snap, AssertionError):
        assert isinstance(fake_snap, AssertionError)
    else:
        assert _plain(fake_snap) == _plain(real_snap)
    # A stopped stream's read is the namespace's own type, blocks included (a
    # complete one returns the object it was given: the test below).
    if cut is not None:
        for fake_read, real_read in ((fake, real), (fake_snap, real_snap)):
            if isinstance(real_read, (Exception, AssertionError)):
                continue
            assert type(fake_read) is type(real_read)
            assert [type(b) for b in fake_read.content] == [type(b) for b in real_read.content]


def test_a_stopped_stream_built_outside_an_entry_point_reads_as_the_plain_namespace():
    body = _reply()
    (_kind, real), _snap = _through_sdk(body, "after_content", "eof")
    fake = F.FinalMessageStream(body, cut="after_content").get_final_message()

    assert type(fake) is type(real) is ParsedMessage
    assert _plain(fake) == _plain(real)


@pytest.mark.parametrize("namespace", [F.PLAIN, F.BETA], ids=_NAMESPACE_IDS)
def test_a_stream_names_its_namespace_or_takes_the_outermost_entrys(namespace):
    body = _reply()
    expected = ParsedBetaMessage if namespace == F.BETA else ParsedMessage
    # Named when built: an entry point does not rename it.
    named = F.FinalMessageStream(body, cut="after_content", namespace=namespace)
    messages, _beta = F.sdk_namespaces(stream=lambda **_kw: named)
    with messages.stream(model=OPUS, max_tokens=64_000, messages=_MSG) as s:
        assert type(s.get_final_message()) is expected
    # Unnamed and reached through a beta entry that forwards to the plain one:
    # the namespace production called is the outer one.
    plain, _unused = F.sdk_namespaces(
        stream=lambda **_kw: F.FinalMessageStream(body, cut="after_content"))
    entry = F.checked_entry(namespace, "stream", lambda **kw: plain.stream(**kw),
                            header=namespace == F.BETA)
    kwargs = dict(model=OPUS, max_tokens=64_000, messages=_MSG)
    if namespace == F.BETA:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
    with entry(**kwargs) as s:
        assert type(s.get_final_message()) is expected


def test_final_message_stream_before_consumption_has_no_snapshot_like_the_sdk():
    with pytest.raises(AssertionError):
        F.FinalMessageStream(_reply(), cut="after_text", end="drop").current_message_snapshot


def test_final_message_stream_of_a_complete_reply_returns_the_object_it_was_given():
    reply = F.FakeMessage(content=[F.FakeTextBlock(text="ok")])
    stream = F.FinalMessageStream(reply)
    assert stream.get_final_message() is reply
    assert stream.current_message_snapshot is reply


# --------------------------------------------------------------------------- #
# The fakes are the installed SDK's own models
# --------------------------------------------------------------------------- #

_FAKES = {
    "FakeMessage": (lambda: F.FakeMessage(content=[F.FakeTextBlock(text="a")]), Message),
    "FakeUsage": (lambda: F.FakeUsage(), Usage),
    "FakeTextBlock": (lambda: F.FakeTextBlock(text="a"), TextBlock),
    "FakeToolUseBlock": (lambda: F.FakeToolUseBlock(name="crop_region", input={"rect": [1, 2, 3, 4]}),
                         ToolUseBlock),
    "FakeServerToolUse": (lambda: F.FakeServerToolUse(web_search_requests=2),
                          anthropic.types.ServerToolUsage),
    "FakeServerToolUseBlock": (lambda: F.FakeServerToolUseBlock(name="web_search", input={"query": "q"}),
                               anthropic.types.ServerToolUseBlock),
    "FakeWebSearchResultBlock": (lambda: F.FakeWebSearchResultBlock(), anthropic.types.WebSearchToolResultBlock),
    "FakeBatchResult": (lambda: F.FakeBatchResult(custom_id="a", result=F.FakeBatchResultEnvelope(
        type="succeeded", message=F.FakeMessage(content=[]))), MessageBatchIndividualResponse),
}


@pytest.mark.parametrize("name", sorted(_FAKES), ids=sorted(_FAKES))
def test_each_fake_is_the_sdks_own_model(name):
    build, cls = _FAKES[name]
    obj = build()
    assert type(obj) is cls
    # Every field the SDK model declares can be read (no AttributeError).
    for field in cls.model_fields:
        getattr(obj, field)


@pytest.mark.parametrize("kind, cls", [
    ("succeeded", MessageBatchSucceededResult), ("errored", MessageBatchErroredResult),
    ("canceled", MessageBatchCanceledResult), ("expired", MessageBatchExpiredResult),
], ids=["succeeded", "errored", "canceled", "expired"])
def test_a_fake_envelope_is_the_sdks_member_for_its_type(kind, cls):
    envelope = F.FakeBatchResultEnvelope(type=kind)
    assert type(envelope) is cls and envelope.type == kind


def test_the_fake_errored_result_is_nested_like_the_api():
    result = F.batch_errored_result("a", error_message="overloaded").result
    assert result.error.type == "error"
    assert (result.error.error.type, result.error.error.message) == ("api_error", "overloaded")


def test_a_fake_response_echoed_into_the_next_request_is_sent_by_the_real_sdk():
    # The investigation echoes the assistant turn it was given into its next
    # request. With dataclass fakes the SDK raised TypeError (not JSON
    # serializable) on every such echo: 41 tests in five files, measured.
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[F.FakeTextBlock(text="done")]))
    turn = F.FakeMessage(content=[
        F.FakeTextBlock(text="Checking."),
        F.FakeToolUseBlock(name="crop_region", input={"rect": [1.0, 2.0, 3.0, 4.0]}, id="toolu_1"),
    ])
    stub.client().messages.create(model=OPUS, max_tokens=8, messages=[
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": turn.content},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}]},
    ])
    [request] = stub.messages()
    echoed = request["body"]["messages"][1]["content"]
    assert [b["type"] for b in echoed] == ["text", "tool_use"]
    assert echoed[1]["input"] == {"rect": [1.0, 2.0, 3.0, 4.0]} and echoed[1]["id"] == "toolu_1"


def test_fakes_keep_value_equality_and_attribute_assignment():
    a, b = F.FakeTextBlock(text="x"), F.FakeTextBlock(text="x")
    assert a == b and a != F.FakeTextBlock(text="y")
    msg = F.FakeMessage(content=[a])
    msg.stop_reason = "max_tokens"
    assert msg.stop_reason == "max_tokens"
    assert (msg.usage.input_tokens, msg.usage.output_tokens) == (100, 50)
    assert F.FakeMessage(content=[]).usage is not F.FakeMessage(content=[]).usage


# --------------------------------------------------------------------------- #
# The stub's knobs reach the SDK as the API sends them
# --------------------------------------------------------------------------- #


def test_the_stub_serves_the_requested_model_unless_the_reply_names_one():
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[F.FakeTextBlock(text="ok")]))
    served = stub.client().messages.create(model="claude-sonnet-5", max_tokens=8, messages=_MSG)
    assert served.model == "claude-sonnet-5"

    named = AnthropicAPIStub(lambda params: F.FakeMessage(content=[], model="claude-opus-4-8"))
    assert named.client().messages.create(model=OPUS, max_tokens=8, messages=_MSG).model == "claude-opus-4-8"
    assert message_json(R.message([], model="claude-haiku-4-5"), model=OPUS)["model"] == "claude-haiku-4-5"


def test_the_stream_knob_stops_one_request_and_not_the_next():
    calls = []

    def stream(record):
        calls.append(record["body"]["model"])
        return ("after_text", "eof") if len(calls) == 1 else None

    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[F.FakeTextBlock(text="full reply here")]),
                            stream=stream)
    client = stub.client()
    with client.messages.stream(model=OPUS, max_tokens=8, messages=_MSG) as s:
        first = s.get_final_message()
    with client.messages.stream(model=OPUS, max_tokens=8, messages=_MSG) as s:
        second = s.get_final_message()

    assert (first.stop_reason, first.content[0].text) == (None, "full re")
    assert (second.stop_reason, second.content[0].text) == ("end_turn", "full reply here")


def _submit(client, n: int = 3) -> str:
    return client.messages.batches.create(requests=[
        {"custom_id": f"sheet-{i}", "params": {"model": OPUS, "max_tokens": 8, "messages": _MSG}}
        for i in range(n)
    ]).id


def test_batch_envelopes_reach_the_sdk_as_its_own_types():
    envelopes = {"sheet-0": R.errored("overloaded_error", "busy"), "sheet-1": R.CANCELED,
                 "sheet-2": R.EXPIRED}
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[F.FakeTextBlock(text="ok")]),
                            batch_result=lambda custom_id, params: envelopes.get(custom_id))
    client = stub.client()
    batch_id = _submit(client, 4)

    results = {r.custom_id: r.result for r in client.messages.batches.results(batch_id)}

    assert results["sheet-0"].error.error.type == "overloaded_error"
    assert (type(results["sheet-1"]), type(results["sheet-2"])) == (MessageBatchCanceledResult,
                                                                    MessageBatchExpiredResult)
    assert results["sheet-3"].message.content[0].text == "ok"
    counts = client.messages.batches.retrieve(batch_id).request_counts
    assert (counts.succeeded, counts.errored, counts.canceled, counts.expired, counts.processing) == (1, 1, 1, 1, 0)


@pytest.mark.parametrize("canceled", [True, False], ids=["canceled", "not-canceled"])
def test_a_pending_item_is_canceled_after_a_cancel_and_expired_otherwise(canceled):
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[F.FakeTextBlock(text="ok")]),
                            batch_result=lambda custom_id, params: R.PENDING if custom_id == "sheet-1" else None)
    client = stub.client()
    batch_id = _submit(client, 2)
    if canceled:
        assert client.messages.batches.cancel(batch_id).processing_status == "canceling"

    results = {r.custom_id: r.result.type for r in client.messages.batches.results(batch_id)}

    assert results == {"sheet-0": "succeeded", "sheet-1": "canceled" if canceled else "expired"}


def test_the_status_sequence_is_answered_in_order_and_the_last_repeats():
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[]),
                            statuses=("in_progress", "canceling", "ended"))
    client = stub.client()
    batch_id = _submit(client)

    seen = [client.messages.batches.retrieve(batch_id) for _ in range(4)]

    assert [b.processing_status for b in seen] == ["in_progress", "canceling", "ended", "ended"]
    assert [b.results_url is not None for b in seen] == [False, False, True, True]
    assert seen[0].request_counts.processing == 3


def test_a_batch_that_has_not_ended_has_no_results_in_the_sdk():
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[]), statuses=("in_progress",))
    client = stub.client()
    with pytest.raises(anthropic.AnthropicError, match="results_url"):
        client.messages.batches.results(_submit(client))


@pytest.mark.parametrize("order", ["reverse", "by-id-desc"], ids=["reverse", "callable"])
def test_the_result_order_knob(order):
    knob = order if order == "reverse" else (lambda lines: sorted(lines, key=lambda l: l["custom_id"], reverse=True))
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[]), order=knob)
    client = stub.client()
    batch_id = _submit(client)

    assert [r.custom_id for r in client.messages.batches.results(batch_id)] == ["sheet-2", "sheet-1", "sheet-0"]


def test_the_default_stub_is_unchanged():
    # WP-02.2's contract tests rely on it: a complete stream, succeeded items,
    # ended at the first retrieve, submit order.
    stub = AnthropicAPIStub(lambda params: F.FakeMessage(content=[F.FakeTextBlock(text="ok")]))
    client = stub.client()
    batch_id = _submit(client)
    assert client.messages.batches.retrieve(batch_id).processing_status == "ended"
    assert [(r.custom_id, r.result.type) for r in client.messages.batches.results(batch_id)] == [
        ("sheet-0", "succeeded"), ("sheet-1", "succeeded"), ("sheet-2", "succeeded")]
    assert message_sse(message_json(F.FakeMessage(content=[F.FakeTextBlock(text="ok")]), model=OPUS)
                       ).decode().rstrip().endswith('data: {"type": "message_stop"}')
    with client.messages.stream(model=OPUS, max_tokens=8, messages=_MSG) as s:
        assert s.get_final_message().stop_reason == "end_turn"
    assert json.loads(json.dumps(stub.requests[-1]["body"]))["stream"] is True


# --------------------------------------------------------------------------- #
# A background upload release finishes inside the test that started it
# --------------------------------------------------------------------------- #

_INNER_RELEASE_FILE = '''
import time

import drawing_analyzer.batch_digest as batch_digest

DELETED = []


class _Files:
    def delete(self, file_id):
        time.sleep(0.5)                  # a slow Files API: the thread outlives the call
        DELETED.append(file_id)


class _Client:
    files = _Files()


def test_a_starts_a_background_release():
    batch_digest._release_uploaded_files(_Client(), ["file_1", "file_2"],
                                         in_background=True, on_log=None)
    assert DELETED == []                 # still running on the release thread


def test_b_runs_after_it_finished():
    assert DELETED == ["file_1", "file_2"]
'''


def test_a_background_release_finishes_inside_the_test_that_started_it(pytester, monkeypatch):
    # Remediation WP-02.3 (the owner's rule): tests/conftest.py joins every
    # release thread a test starts at that test's teardown, so its
    # files.delete calls land in that test and not in the next one (measured
    # before: 2 to 4 of the suite's 80 releases landed in a later test).
    repo = Path(__file__).resolve().parent.parent
    pytester.makeconftest((repo / "tests" / "conftest.py").read_text(encoding="utf-8"))
    pytester.makeini("[pytest]\nmarkers =\n    network: live API access\n")
    for name in list(os.environ):
        if name.lower().endswith("_proxy") or name.upper().startswith("ANTHROPIC_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(repo), os.environ.get("PYTHONPATH")])))
    pytester.makepyfile(test_release=_INNER_RELEASE_FILE)

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-m", "not network", timeout=300)

    result.assert_outcomes(passed=2)
