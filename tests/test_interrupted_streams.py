"""An interrupted stream: its partial read, its retry and its usage (remediation WP-01.7).

U1's partial-stream part and plan WP-14 step 7, under the owner's rules (D-1's
WP-01.7 note in ``_plans/DECISIONS.md``), decided with measured options:

- **The capture site** is ``core.api_config._dispatch_messages``. A stream that
  raises after it started (an SSE ``error`` event, a dropped connection, a clean
  end with no event at all) raises ``StreamInterrupted``, carrying the SDK's
  exception and ``current_message_snapshot`` (``None`` when no
  ``message_start`` arrived). A snapshot that already got ``message_delta``
  carries the model's stop reason and final usage: it is the reply at once, as
  its clean-end twin is, and nothing is retried.
- **The retry.** ``digest._is_transient_error`` learns the interruption: a
  dropped connection (and a stream with no event) and an ``error`` event whose
  type stands for a transient status (the existing ``_TRANSIENT_STATUSES``,
  through ``_ERROR_TYPE_STATUS``). Every streamed stage retries it inside its
  existing transient retries; a permanent type is not retried.
- **The partial read** is the reply once the retries are spent, judged by D-1's
  one classifier: no stop reason is UNFINISHED, so each stage takes its
  existing N27 path (the digest keeps its text under an error, holds its
  findings out, caches nothing; the other stages keep nothing). The digest
  keeps the best read across its attempts (``keep_digest_read``, N16).
- **The wording** is the ladder's with the cause in its parentheses
  (``unfinished digest (stop_reason=None, interrupted='overloaded_error')``);
  with nothing held, ``stream interrupted (<type>: <message>)`` or
  ``stream interrupted (connection dropped — try again)``.
- **The usage**: every attempt's reported usage is the stage's (the snapshot
  holds ``message_start``'s), and ``interrupted_attempts`` on the usage record
  counts the attempts whose final usage never arrived, totalled on the run
  and named in run.log.

Every stage runs through the real SDK over
``tests/fixtures/sdk_transport.AnthropicAPIStub``; expected usage is read off
the replies the stub served, never off production.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

pytest.importorskip("pymupdf")

import drawing_analyzer.batch_digest as BD  # noqa: E402
import drawing_analyzer.core.api_config as api  # noqa: E402
import drawing_analyzer.digest as D  # noqa: E402
from drawing_analyzer import run_journal  # noqa: E402
from drawing_analyzer.core.reply_text import reply_text  # noqa: E402
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from drawing_analyzer.models import RunUsage, UsageRecord  # noqa: E402
from tests.fixtures import sdk_responses as R  # noqa: E402
from tests.fixtures.fake_anthropic import FinalMessageStream, sdk_namespaces  # noqa: E402
from tests.fixtures.sdk_transport import AnthropicAPIStub, message_json  # noqa: E402
from tests.test_batch_refusal_recovery import _collect, _ok, _realtime, _sheet0  # noqa: E402
from tests.test_response_shapes import (  # noqa: E402
    _about_m101, _calls, _records, _run, _script, _sheet, _statuses, _warm_calls,
)
from tests.test_sdk_contract import stage_of  # noqa: E402
# The contract tests' autouse fixture: every self-healing latch starts on, one
# upload worker, the upload release run inline.
from tests.test_sdk_contract import _fresh_latches  # noqa: E402,F401

OPUS_55 = "claude-opus-5-5"
SONNET_55 = "claude-sonnet-5-5"
MODELS = (OPUS_55, SONNET_55)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DROPPED = "connection dropped — try again"
BODY = ("Sheet M-101 shows VAV-3 at 450 cfm.\n```json\n"
        '{"findings": [{"category": "coordination", "severity": "medium", '
        '"text": "VAV-3 airflow", "quote": "VAV-3"}]}\n```')
MSG = R.message([R.text(BODY)], usage_=R.usage(500, 120, cache_read=40, cache_write=60,
                                                 cache_split=(60, 0)))
BEFORE_DELTA = ("empty", "before_text", "after_text", "after_content")
TRANSIENT_TYPES = ("rate_limit_error", "api_error", "timeout_error", "overloaded_error")
EVERY_TYPE = tuple(R.ERROR_TYPES) + ("request_too_large",)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """The transient retries sleep 2 s and 4 s: not in a test."""
    import drawing_analyzer.critique as critique_mod
    import drawing_analyzer.focus as focus_mod
    import drawing_analyzer.investigate as inv_mod
    import drawing_analyzer.review_planner as planner_mod
    import drawing_analyzer.synthesis as synthesis_mod

    for mod in (D, BD, critique_mod, focus_mod, inv_mod, planner_mod, synthesis_mod):
        if hasattr(mod, "_retry_backoff_seconds"):
            monkeypatch.setattr(mod, "_retry_backoff_seconds", lambda attempt: 0.0)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _stream_seq(stage: str, shapes, when=lambda params: True):
    """``stream``: the k-th request of ``stage`` matching ``when`` stops as
    ``shapes[k]`` (``(cut, end)`` or ``(cut, end, error)``); later ones are
    complete."""
    seen = {"n": 0}

    def stream(record):
        body = record["body"]
        if stage_of(body) != stage or not when(body):
            return None
        k = seen["n"]
        seen["n"] += 1
        return shapes[k] if k < len(shapes) else None

    return stream


class _Served:
    """The script's route, keeping the usage of every reply it served:
    ``(stage, input_tokens, output_tokens, about_m101)`` in request order. An
    interrupted reply bills its input (``message_start``) and no output."""

    def __init__(self, script=None) -> None:
        self.script = script if script is not None else _script()
        self.log: list[tuple[str, int, int, bool]] = []

    def __call__(self, params: dict) -> dict:
        body = message_json(self.script._route(params), model=params.get("model", ""))
        self.log.append((stage_of(params), int(body["usage"]["input_tokens"]),
                         int(body["usage"]["output_tokens"]), _about_m101(params)))
        return body

    def inputs(self, stage: str, *, m101: bool | None = None) -> list[int]:
        return [i for s, i, _, about in self.log if s == stage and (m101 is None or about == m101)]

    def outputs(self, stage: str, *, m101: bool | None = None) -> list[int]:
        return [o for s, _, o, about in self.log if s == stage and (m101 is None or about == m101)]


def _stub(served: _Served, stage: str, shapes, when=lambda params: True) -> AnthropicAPIStub:
    return AnthropicAPIStub(served, stream=_stream_seq(stage, shapes, when))


def _record(ctx, family: str, instance: str | None = None):
    [rec] = [r for r in _records(ctx, family) if instance is None or r.stage_instance == instance]
    return rec


def _m101_requests(stub: AnthropicAPIStub, stage: str) -> int:
    return sum(1 for r in stub.messages() if stage_of(r["body"]) == stage and _about_m101(r["body"]))


def _dispatch(client, ns: str, model: str = OPUS_55):
    kwargs = {"model": model, "max_tokens": 1000, "messages": [{"role": "user", "content": "x"}]}
    if ns == "beta":
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    return api._dispatch_messages(client, kwargs, "stream")


def _fake_client(stream):
    """A client whose ``stream`` returns ``stream(kwargs)`` (a FinalMessageStream)."""
    messages, beta = sdk_namespaces(stream=lambda **kwargs: stream(kwargs))
    return SimpleNamespace(messages=messages, beta=beta)


def _interrupted_by(error_type: str, *, cut: str = "empty", message: str = "the detail"):
    """The ``StreamInterrupted`` an SSE ``error`` event of ``error_type`` raises."""
    client = _fake_client(lambda kw: FinalMessageStream(
        anthropic.types.Message.model_validate(MSG), cut=cut, end="error",
        error=R.stream_error(error_type, message)))
    with pytest.raises(api.StreamInterrupted) as info:
        _dispatch(client, "plain")
    return info.value


# --------------------------------------------------------------------------- #
# The capture site, through the real SDK (both namespaces, both 5.5 models)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("end", ["error", "drop"], ids=["error-event", "dropped"])
@pytest.mark.parametrize("cut", BEFORE_DELTA, ids=list(BEFORE_DELTA))
@pytest.mark.parametrize("model", MODELS, ids=list(MODELS))
@pytest.mark.parametrize("ns", ["plain", "beta"], ids=["plain", "beta"])
def test_a_stream_that_raises_before_message_delta_carries_its_snapshot(ns, model, cut, end):
    stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: (cut, end))

    with pytest.raises(api.StreamInterrupted) as info:
        _dispatch(stub.client(), ns, model)

    exc = info.value
    expected = R.partial_message(MSG, cut)
    if expected is None:
        assert exc.partial is None
    else:
        assert reply_text(exc.partial) == reply_text(anthropic.types.Message.model_validate(expected))
        assert exc.partial.stop_reason is None
        usage = exc.partial.usage
        assert (usage.input_tokens, usage.output_tokens) == (500, 0)          # message_start's
        assert (usage.cache_read_input_tokens, usage.cache_creation_input_tokens) == (40, 60)
    assert exc.__cause__ is exc.cause
    if end == "error":
        assert type(exc.cause) is anthropic.APIStatusError and exc.cause.status_code == 200
        assert (exc.kind, exc.error_type) == ("error_event", "overloaded_error")
    else:
        assert type(exc.cause) is httpx2.RemoteProtocolError
        assert (exc.kind, exc.error_type) == ("connection", None)
    assert len(stub.messages()) == 1


@pytest.mark.parametrize("end", ["error", "drop"], ids=["error-event", "dropped"])
@pytest.mark.parametrize("ns", ["plain", "beta"], ids=["plain", "beta"])
def test_a_stream_that_raises_after_message_delta_is_the_reply_at_once(ns, end):
    # The owner's rule: the read is complete (only message_stop is missing), as
    # its clean-end twin is, so it is the reply and nothing is retried.
    stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: ("before_message_stop", end))

    reply = _dispatch(stub.client(), ns)

    assert reply.stop_reason == "end_turn" and reply_text(reply) == BODY
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (500, 120)
    assert len(stub.messages()) == 1


@pytest.mark.parametrize("cut", BEFORE_DELTA[1:] + ("before_message_stop",),
                         ids=list(BEFORE_DELTA[1:]) + ["before_message_stop"])
@pytest.mark.parametrize("ns", ["plain", "beta"], ids=["plain", "beta"])
def test_a_clean_early_end_is_unchanged(ns, cut):
    stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: (cut, "eof"))

    reply = _dispatch(stub.client(), ns)

    assert reply.stop_reason == (None if cut != "before_message_stop" else "end_turn")


@pytest.mark.parametrize("ns", ["plain", "beta"], ids=["plain", "beta"])
def test_a_stream_with_no_event_at_all_is_an_interruption_holding_nothing(ns):
    stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: ("empty", "eof"))

    with pytest.raises(api.StreamInterrupted) as info:
        _dispatch(stub.client(), ns)

    assert info.value.partial is None and info.value.kind == "no_event"
    assert type(info.value.cause) is AssertionError                # the SDK's own check


def test_a_reload_of_api_config_keeps_one_exception_class(monkeypatch):
    # The report-chat tests reload core.api_config to re-read the environment.
    # The class lives in its own module, so the capture site still raises the
    # class digest tests for (in the full suite it did not, and an interrupted
    # stream was neither retried nor counted in every later test).
    import importlib

    from drawing_analyzer.core import stream_interruption

    importlib.reload(api)
    try:
        assert api.StreamInterrupted is stream_interruption.StreamInterrupted is D.StreamInterrupted
        stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: ("after_text", "drop"))
        with pytest.raises(D.StreamInterrupted) as info:
            _dispatch(stub.client(), "plain")
        assert D._is_transient_error(info.value)
    finally:
        importlib.reload(api)


@pytest.mark.parametrize("status, cls", [(400, anthropic.BadRequestError),
                                         (529, anthropic.OverloadedError)],
                         ids=["400", "529"])
def test_a_failure_before_the_stream_starts_is_not_wrapped(status, cls):
    # The self-healing latches and the SDK's own retries read these; they are
    # not interruptions.
    stub = AnthropicAPIStub(lambda params: MSG, reject=lambda record: httpx2.Response(
        status, json={"type": "error", "error": {"type": "api_error", "message": "no"}}))

    with pytest.raises(anthropic.APIStatusError) as info:
        _dispatch(stub.client(), "plain")

    assert isinstance(info.value, cls) and not isinstance(info.value, api.StreamInterrupted)


# --------------------------------------------------------------------------- #
# The retry predicate and the wording
# --------------------------------------------------------------------------- #


def test_every_api_error_type_stands_for_a_status():
    # The SDK's error types, plus the API's 413 type the SDK does not name.
    assert set(D._ERROR_TYPE_STATUS) == set(EVERY_TYPE)
    assert {t for t, s in D._ERROR_TYPE_STATUS.items() if s in D._TRANSIENT_STATUSES} == set(TRANSIENT_TYPES)


@pytest.mark.parametrize("error_type", EVERY_TYPE, ids=list(EVERY_TYPE))
def test_an_error_event_is_retried_exactly_when_its_type_is_transient(error_type):
    exc = _interrupted_by(error_type)

    assert D._is_transient_error(exc) is (error_type in TRANSIENT_TYPES)
    assert D._clean_error(exc) == f"stream interrupted ({error_type}: the detail)"


def test_a_dropped_connection_is_retried_and_named():
    stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: ("empty", "drop"))
    with pytest.raises(api.StreamInterrupted) as info:
        _dispatch(stub.client(), "plain")

    assert D._is_transient_error(info.value)
    assert D._clean_error(info.value) == f"stream interrupted ({DROPPED})"


def test_a_stream_with_no_event_is_retried_and_reads_as_dropped():
    stub = AnthropicAPIStub(lambda params: MSG, stream=lambda record: ("empty", "eof"))
    with pytest.raises(api.StreamInterrupted) as info:
        _dispatch(stub.client(), "plain")

    assert D._is_transient_error(info.value)
    assert D._clean_error(info.value) == f"stream interrupted ({DROPPED})"


def test_a_read_timeout_mid_stream_is_retried_and_named():
    exc = api.StreamInterrupted(httpx2.ReadTimeout("read timed out"), None)

    assert exc.kind == "timeout" and D._is_transient_error(exc)
    assert D._clean_error(exc) == "stream interrupted (timed out — try again)"


def test_any_other_cause_is_judged_as_itself():
    boom = api.StreamInterrupted(RuntimeError("boom"), None)
    assert boom.kind == "other" and not D._is_transient_error(boom)
    assert D._clean_error(boom) == "boom"

    class _Status503(Exception):
        status_code = 503

    busy = api.StreamInterrupted(_Status503("busy"), None)
    assert D._is_transient_error(busy)
    assert D._clean_error(busy) == D._clean_error(_Status503("busy"))


def test_the_error_event_message_is_cleaned():
    exc = _interrupted_by("api_error", message="<html><b>Internal</b>\n  error</html>")

    assert D._clean_error(exc) == "stream interrupted (api_error: Internal error)"


_LADDER = [
    ("", None, "empty digest (stop_reason=None, interrupted='connection dropped')"),
    ("text", None, "unfinished digest (stop_reason=None, interrupted='connection dropped')"),
    ("text", "max_tokens", "truncated digest (stop_reason='max_tokens', interrupted='connection dropped')"),
    ("text", "end_turn", None),
]


@pytest.mark.parametrize("raw, stop, expected", _LADDER, ids=["empty", "unfinished", "truncated", "finished"])
def test_the_ladder_names_the_interruption_in_its_parentheses(raw, stop, expected):
    assert D.digest_terminal_error(raw, stop, interrupted="connection dropped") == expected


def test_the_ladder_is_unchanged_without_an_interruption():
    assert D.digest_terminal_error("text", None) == "unfinished digest (stop_reason=None)"
    assert D.digest_terminal_error("", "refusal", category="cyber") == (
        "refused digest (stop_reason='refusal', category='cyber')")
    assert D.digest_terminal_error("", "refusal", category="cyber", interrupted="connection dropped") == (
        "refused digest (stop_reason='refusal', category='cyber', interrupted='connection dropped')")


# --------------------------------------------------------------------------- #
# The digest (real time, through the pipeline)
# --------------------------------------------------------------------------- #

_DROP = ("after_text", "drop")
_ERROR = ("after_text", "error")


def _digest_run(tmp_path, shapes, served=None):
    served = served if served is not None else _Served()
    stub = _stub(served, "digest", shapes, _about_m101)
    return _run(tmp_path, stub, full=False), stub, served


@pytest.mark.parametrize("shape", [_ERROR, _DROP], ids=["error-event", "dropped"])
def test_an_interrupted_digest_read_is_retried_and_its_usage_kept(tmp_path, shape):
    ctx, stub, served = _digest_run(tmp_path, [shape])

    assert _m101_requests(stub, "digest") == 2
    sheet = _sheet(ctx, "M-101")
    assert sheet.error is None and len(sheet.findings) == 1
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert (rec.input_tokens, rec.output_tokens) == (
        sum(served.inputs("digest", m101=True)), served.outputs("digest", m101=True)[-1])
    assert (rec.terminal_status, rec.interrupted_attempts) == ("COMPLETE", 1)
    assert _statuses(ctx)["digest"] == "COMPLETE"
    assert _warm_calls(tmp_path, full=False) == {}                       # the finished read was cached


def test_a_permanent_error_event_is_not_retried_and_keeps_the_partial_read(tmp_path):
    error = R.stream_error("invalid_request_error", "bad field")
    ctx, stub, served = _digest_run(tmp_path, [("after_text", "error", error)])

    assert _m101_requests(stub, "digest") == 1
    sheet = _sheet(ctx, "M-101")
    assert sheet.error == "unfinished digest (stop_reason=None, interrupted='invalid_request_error')"
    assert sheet.text                                                    # the prose that came back
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert (rec.input_tokens, rec.output_tokens, rec.interrupted_attempts) == (
        served.inputs("digest", m101=True)[0], 0, 1)
    assert rec.terminal_status == "FAILED"
    assert _warm_calls(tmp_path, full=False) == {"digest": 1}            # not cached


def test_a_digest_interrupted_on_every_attempt_keeps_the_last_partial_read(tmp_path):
    ctx, stub, served = _digest_run(tmp_path, [_DROP] * 3)

    assert _m101_requests(stub, "digest") == 3                           # 1 + the 2 transient retries
    sheet = _sheet(ctx, "M-101")
    assert sheet.error == "unfinished digest (stop_reason=None, interrupted='connection dropped')"
    assert sheet.text
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert (rec.input_tokens, rec.output_tokens, rec.interrupted_attempts) == (
        sum(served.inputs("digest", m101=True)), 0, 3)
    assert any(e.endswith("interrupted='connection dropped')") for e in ctx.errors)
    assert _warm_calls(tmp_path, full=False) == {"digest": 1}


def test_a_complete_looking_findings_object_from_an_interrupted_read_is_held_out(tmp_path):
    ctx, _, _ = _digest_run(tmp_path, [("after_content", "drop")] * 3)

    sheet = _sheet(ctx, "M-101")
    assert sheet.error == "unfinished digest (stop_reason=None, interrupted='connection dropped')"
    assert len(sheet.findings) == 1                                      # parsed, and
    assert ctx.digest_findings_held_out == {"SRC-0001:p0": 1}            # held out of the review (N15)
    assert _warm_calls(tmp_path, full=False) == {"digest": 1}


def test_an_interruption_before_any_text_reads_empty(tmp_path):
    ctx, _, _ = _digest_run(tmp_path, [("before_text", "drop")] * 3)

    assert _sheet(ctx, "M-101").error == (
        "empty digest (stop_reason=None, interrupted='connection dropped')")


def test_an_interruption_before_any_event_holds_nothing_but_is_counted(tmp_path):
    ctx, stub, _ = _digest_run(tmp_path, [("empty", "drop")] * 3)

    assert _m101_requests(stub, "digest") == 3
    sheet = _sheet(ctx, "M-101")
    assert sheet.error == f"stream interrupted ({DROPPED})" and sheet.text == ""
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert (rec.input_tokens, rec.output_tokens, rec.interrupted_attempts) == (0, 0, 3)


def test_an_interruption_after_message_delta_is_a_finished_read(tmp_path):
    ctx, stub, served = _digest_run(tmp_path, [("before_message_stop", "drop")])

    assert _m101_requests(stub, "digest") == 1                           # nothing retried
    assert _sheet(ctx, "M-101").error is None
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert (rec.input_tokens, rec.output_tokens, rec.interrupted_attempts) == (
        served.inputs("digest", m101=True)[0], served.outputs("digest", m101=True)[0], 0)
    assert _warm_calls(tmp_path, full=False) == {}                       # admitted, as its twin is


def test_a_partial_read_survives_a_retry_that_returns_nothing(tmp_path):
    # N16: the later attempts raised before any event; the sheet keeps the
    # partial read and names the call's final failure once.
    ctx, _, _ = _digest_run(tmp_path, [_DROP, ("empty", "drop"), ("empty", "drop")])

    assert _sheet(ctx, "M-101").error == (
        "unfinished digest (stop_reason=None, interrupted='connection dropped'); "
        f"retry failed: stream interrupted ({DROPPED})")
    assert _sheet(ctx, "M-101").text


def test_a_partial_read_with_content_outranks_later_empty_ones(tmp_path):
    ctx, _, _ = _digest_run(tmp_path, [("after_content", "drop"), ("before_text", "drop"),
                                       ("before_text", "drop")])

    sheet = _sheet(ctx, "M-101")
    assert sheet.error == (
        "unfinished digest (stop_reason=None, interrupted='connection dropped'); "
        "2 retries, the last: empty digest (stop_reason=None, interrupted='connection dropped')")
    assert len(sheet.findings) == 1 and ctx.digest_findings_held_out == {"SRC-0001:p0": 1}


def test_a_raised_cap_retry_that_is_interrupted_keeps_the_first_read(tmp_path):
    # The first reply stops at max_tokens; every attempt of its raised-cap
    # retry drops before any event. The first read is kept and names the
    # retry once, as a raised-cap retry that raised always was.
    script = _script()

    def route(params):
        body = message_json(script._route(params), model=params.get("model", ""))
        if stage_of(params) == "digest" and _about_m101(params) and params["max_tokens"] <= 64_000:
            body["stop_reason"] = "max_tokens"
        return body

    served = _Served(SimpleNamespace(_route=route))
    ctx, stub, _ = _digest_run(tmp_path, [None] + [("empty", "drop")] * 3, served)

    assert _m101_requests(stub, "digest") == 4
    assert _sheet(ctx, "M-101").error == (
        f"truncated digest (stop_reason='max_tokens'); retry failed: stream interrupted ({DROPPED})")
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert rec.interrupted_attempts == 3


# --------------------------------------------------------------------------- #
# The critique (a read: kept only when finished)
# --------------------------------------------------------------------------- #


def test_an_interrupted_critique_read_is_retried_and_its_usage_kept(tmp_path):
    served = _Served()
    stub = _stub(served, "critique", [("after_content", "drop")], _about_m101)

    ctx = _run(tmp_path, stub)

    assert _m101_requests(stub, "critique") == 3                         # two reads, one retried
    assert _statuses(ctx)["critique"] == "COMPLETE"
    rec = _record(ctx, "critique", "critique:SRC-0001:p0")
    assert (rec.input_tokens, rec.output_tokens) == (
        sum(served.inputs("critique", m101=True)), sum(served.outputs("critique", m101=True)[1:]))
    assert rec.interrupted_attempts == 1
    assert _warm_calls(tmp_path).get("critique", 0) == 0


def test_a_permanently_interrupted_critique_read_fails_and_keeps_its_usage(tmp_path):
    served = _Served()
    error = R.stream_error("invalid_request_error", "bad field")
    stub = _stub(served, "critique", [("after_content", "error", error)], _about_m101)

    ctx = _run(tmp_path, stub)

    assert _m101_requests(stub, "critique") == 2
    assert _statuses(ctx)["critique"] == "PARTIAL"
    [stage] = [s for s in ctx.stage_results if s.stage == "critique"]
    assert any("unfinished critique (stop_reason=None, interrupted='invalid_request_error')" in e
               for e in stage.errors)
    rec = _record(ctx, "critique", "critique:SRC-0001:p0")
    # The failed read's tokens are billed on the sheet's record (they were dropped).
    assert (rec.input_tokens, rec.interrupted_attempts) == (sum(served.inputs("critique", m101=True)), 1)
    assert _warm_calls(tmp_path).get("critique") == 2


def test_a_critique_read_interrupted_after_message_delta_counts(tmp_path):
    stub = _stub(_Served(), "critique", [("before_message_stop", "drop")], _about_m101)

    ctx = _run(tmp_path, stub)

    assert _m101_requests(stub, "critique") == 2
    assert _statuses(ctx)["critique"] == "COMPLETE"


# --------------------------------------------------------------------------- #
# The review plan, synthesis and the focus report
# --------------------------------------------------------------------------- #

_TEXT_STAGES = {"review_plan": ("review plan", "review_plan_markdown"),
                "synthesis": ("synthesis", "synthesis_text"),
                "focus": ("focus report", "focus_report_text")}


@pytest.mark.parametrize("stage", sorted(_TEXT_STAGES), ids=sorted(_TEXT_STAGES))
def test_a_set_level_stage_interrupted_on_every_attempt_fails_and_keeps_its_usage(tmp_path, stage):
    noun, attr = _TEXT_STAGES[stage]
    served = _Served()
    stub = _stub(served, stage, [_DROP] * 3)

    ctx = _run(tmp_path, stub)

    assert _calls(stub)[stage] == 3
    assert getattr(ctx, attr) == ""
    assert f"unfinished {noun} (stop_reason=None, interrupted='connection dropped')" in " ".join(ctx.errors)
    rec = _record(ctx, stage)
    assert (rec.input_tokens, rec.output_tokens, rec.terminal_status, rec.interrupted_attempts) == (
        sum(served.inputs(stage)), 0, "FAILED", 3)
    assert _warm_calls(tmp_path).get(stage, 0) == 1                      # nothing cached


@pytest.mark.parametrize("stage", sorted(_TEXT_STAGES), ids=sorted(_TEXT_STAGES))
def test_a_set_level_stage_with_no_event_is_recorded_as_interrupted(tmp_path, stage):
    stub = _stub(_Served(), stage, [("empty", "drop")] * 3)

    ctx = _run(tmp_path, stub)

    assert f"stream interrupted ({DROPPED})" in " ".join(ctx.errors)
    rec = _record(ctx, stage)
    assert (rec.input_tokens, rec.output_tokens, rec.terminal_status, rec.interrupted_attempts) == (
        0, 0, "FAILED", 3)


@pytest.mark.parametrize("stage", sorted(_TEXT_STAGES), ids=sorted(_TEXT_STAGES))
def test_a_set_level_stage_interrupted_after_message_delta_is_used_and_cached(tmp_path, stage):
    _, attr = _TEXT_STAGES[stage]
    stub = _stub(_Served(), stage, [("before_message_stop", "error")])

    ctx = _run(tmp_path, stub)

    assert _calls(stub)[stage] == 1
    assert getattr(ctx, attr)
    assert _record(ctx, stage).interrupted_attempts == 0
    assert _warm_calls(tmp_path).get(stage, 0) == 0


# --------------------------------------------------------------------------- #
# The investigation (the owner's rule: retried; a partial turn is never used)
# --------------------------------------------------------------------------- #


def test_an_interrupted_investigation_turn_is_retried_and_its_usage_kept(tmp_path):
    served = _Served()
    stub = _stub(served, "investigation", [_DROP])

    ctx = _run(tmp_path, stub)

    assert _calls(stub)["investigation"] == 3                            # 2 turns, the first retried
    assert _statuses(ctx)["investigation"] == "COMPLETE"
    rec = _record(ctx, "investigate")
    assert (rec.input_tokens, rec.interrupted_attempts) == (sum(served.inputs("investigation")), 1)


def test_an_investigation_turn_interrupted_on_every_attempt_runs_nothing_from_it(tmp_path):
    served = _Served()
    stub = _stub(served, "investigation", [("after_content", "drop")] * 3)

    ctx = _run(tmp_path, stub)

    assert _calls(stub)["investigation"] == 3                            # no tool answered, no next turn
    assert _statuses(ctx)["investigation"] == "PARTIAL"
    [stage] = [s for s in ctx.stage_results if s.stage == "investigation"]
    assert any(f"stream interrupted ({DROPPED})" in e for e in stage.errors)
    rec = _record(ctx, "investigate")
    assert (rec.input_tokens, rec.output_tokens, rec.terminal_status, rec.interrupted_attempts) == (
        sum(served.inputs("investigation")), 0, "FAILED", 3)


# --------------------------------------------------------------------------- #
# The batch direct-call rescue (RECOVERY_DIRECT)
# --------------------------------------------------------------------------- #


def _rescue_stub(shapes):
    return AnthropicAPIStub(_ok, batch_result=_sheet0(lambda k, p: R.errored("overloaded_error", "busy")),
                            stream=_stream_seq("digest", shapes))


def test_an_interrupted_rescue_is_retried_and_its_attempt_recorded(monkeypatch):
    stub = _rescue_stub([_DROP])

    sd, other = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)

    assert len(_realtime(stub)) == 2 and sd.ok and sd.rescued and other.ok
    attempts = [a for a in sd.usage_attempts if a.transport == "REAL_TIME"]
    assert [(a.interrupted_attempts, a.output_tokens > 0, a.terminal_status) for a in attempts] == [
        (1, False, "FAILED"), (0, True, "COMPLETE")]


def test_a_rescue_interrupted_on_every_attempt_keeps_its_partial_read(monkeypatch):
    stub = _rescue_stub([_DROP] * 3)

    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)

    assert len(_realtime(stub)) == 3
    assert sd.error == "unfinished digest (stop_reason=None, interrupted='connection dropped')"
    assert sd.text                                                       # outranks the errored batch reads
    assert sum(a.interrupted_attempts for a in sd.usage_attempts) == 3


def test_a_rescue_with_no_event_keeps_the_batch_read_and_names_it(monkeypatch):
    stub = _rescue_stub([("empty", "drop")] * 3)

    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)

    assert len(_realtime(stub)) == 3
    assert sd.error == f"overloaded_error: busy; retry failed: stream interrupted ({DROPPED})"
    interrupted = [a for a in sd.usage_attempts if a.interrupted_attempts]
    assert [(a.transport, a.billable, a.input_tokens) for a in interrupted] == [("REAL_TIME", False, 0)] * 3


def test_the_batch_inline_fallback_counts_its_interrupted_attempt(tmp_path):
    # A Files-API 404 serves the sheet inline through digest_sheet (batch's
    # _serve_inline): its one REAL_TIME attempt record carries the count.
    stub = AnthropicAPIStub(
        _script()._route, stream=_stream_seq("digest", [_DROP], _about_m101),
        reject=lambda record: httpx2.Response(404, json={"type": "error", "error": {
            "type": "not_found_error", "message": "no files"}})
        if record["path"] == "/v1/files" else None)

    ctx = _run(tmp_path, stub, "batch", full=False)

    assert _sheet(ctx, "M-101").error is None
    rec = _record(ctx, "digest", "digest:SRC-0001:p0")
    assert (rec.transport, rec.interrupted_attempts) == ("REAL_TIME", 1)


# --------------------------------------------------------------------------- #
# The usage surfaces
# --------------------------------------------------------------------------- #


def test_the_usage_record_counts_interrupted_attempts_additively():
    rec = UsageRecord(stage_family="digest", stage_instance="digest:SRC-0001:p0")
    assert rec.interrupted_attempts == 0 and rec.to_dict()["interrupted_attempts"] == 0

    usage = RunUsage()
    usage.add(UsageRecord(stage_family="digest", stage_instance="a", interrupted_attempts=2))
    usage.add(UsageRecord(stage_family="synthesis", stage_instance="b", interrupted_attempts=1))
    assert usage.interrupted_attempts == 3 and usage.to_dict()["interrupted_attempts"] == 3


def test_run_log_and_the_manifest_say_the_totals_are_lower_bounds(tmp_path):
    ctx, _, _ = _digest_run(tmp_path, [_DROP] * 3)

    lines = run_journal._usage_lines(ctx)
    assert ("  3 attempt(s) interrupted mid-stream: their output tokens were not reported, "
            "so the output and cost totals are lower bounds") in lines
    assert json.loads(json.dumps(ctx.run_usage.to_dict()))["interrupted_attempts"] == 3


def test_a_run_with_no_interruption_says_nothing_new(tmp_path):
    ctx = _run(tmp_path, AnthropicAPIStub(_script()._route), full=False)

    assert not any("interrupted" in line for line in run_journal._usage_lines(ctx))
    assert ctx.run_usage.to_dict()["interrupted_attempts"] == 0


def test_a_cached_digest_is_never_an_interrupted_read(tmp_path):
    # The loader's rule is unchanged: a stored entry is a finished read, and
    # carries no interruption.
    _digest_run(tmp_path, [("before_message_stop", "drop")])
    ctx = _run(tmp_path, AnthropicAPIStub(_script()._route), full=False,
               cache=DigestCache(tmp_path / "cache.sqlite"), work="warm")

    assert _record(ctx, "digest", "digest:SRC-0001:p0").interrupted_attempts == 0
    assert _sheet(ctx, "M-101").cached


def test_no_cache_term_moved():
    # No key, contract or schema moved (the owner's rule, D-4's WP-01.7 note):
    # a finished snapshot is stored like any finished reply, under the same key.
    from drawing_analyzer import digest_cache

    assert (digest_cache._SCHEMA_VERSION, digest_cache._CRITIQUE_CACHE_CONTRACT) == (10, 3)
