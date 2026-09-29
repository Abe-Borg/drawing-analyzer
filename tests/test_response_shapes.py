"""What production does with each response shape the API sends (remediation WP-02.3, U26).

Every test here runs the gauntlet's mini set (``tests/fixtures/gauntlet.py``)
through the real SDK over ``tests/fixtures/sdk_transport.AnthropicAPIStub``,
with one response shape from ``tests/fixtures/sdk_responses.py``: nested batch
errors of every SDK error type, ``canceled`` and ``expired`` items, a batch
polled through ``in_progress`` and ``canceling`` with its results out of order,
``None`` usage counters, ``iterations``, ``output_tokens_details``, the
``cache_creation`` TTL split, ``web_fetch_requests``, a refusal with
``stop_details``, a ``fallback`` block mid-content, a serving model that is not
the requested one, and event streams cut before any text, after text and after
the complete findings JSON, ended cleanly, by an ``error`` event or by a
dropped connection. Each was measured on SDK 1.7.0 and 1.8.0 (s2 of WP-02.3,
identical on both).

Where production is right today, the test asserts it: the WP-02 acceptance
this slice owns ("tests fail for missed terminal guards, realistic canceled
envelopes and duplicated usage") rests on those. Where it is not, the test is a
**recorded limit** (the owner's rule): ``test_recorded_limit_*`` asserts
today's behaviour, and its docstring names the slice that fixes it and what the
assertion becomes. A fix fails the test, so it cannot land silently; the owning
slice flips the assertion in its own PR (a re-baseline it records).
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pymupdf")

import drawing_analyzer.batch_digest as BD  # noqa: E402
import drawing_analyzer.pipeline as pl  # noqa: E402
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from tests.fixtures import sdk_responses as R  # noqa: E402
from tests.fixtures.gauntlet import build_mini_set  # noqa: E402
from tests.fixtures.sdk_transport import AnthropicAPIStub, message_json  # noqa: E402
from tests.test_sdk_contract import _TRANSPORTS, _script, stage_of  # noqa: E402
# The contract tests' autouse fixture: every self-healing latch starts on, one
# upload worker, the upload release run inline.
from tests.test_sdk_contract import _fresh_latches  # noqa: E402,F401

M101 = "VAV-3"                      # M-101's distinctive text: in every request about it
OPUS = "claude-opus-5-5"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _about_m101(params: dict) -> bool:
    return M101 in json.dumps(params.get("messages", []))


def _run(tmp_path: Path, stub: AnthropicAPIStub, transport: str = "fast", *,
         full: bool = True, cache: DigestCache | None = None, work: str = "work",
         model: str | None = None):
    """The mini set through ``stub``: the whole exhaustive stack, or (``full``
    False) the digest alone; on ``model`` when given, else the review default."""
    use_batch, critique_batch = _TRANSPORTS[transport]
    extra = {} if model is None else {"model": model}
    if full:
        work_dir = tmp_path / work
        work_dir.mkdir()
        extra.update(synthesize=True, focus="equipment coordination", qc_markups=True,
                     qc_work_dir=work_dir)
    return pl.extract_drawing_context(
        build_mini_set(tmp_path), client=stub.client(), rows=2, cols=2,
        cache=cache if cache is not None else DigestCache(tmp_path / "cache.sqlite"),
        use_batch=use_batch, critique_use_batch=critique_batch, **extra,
    )


def _warm_calls(tmp_path: Path, transport: str = "fast", *, full: bool = True,
                model: str | None = None) -> dict[str, int]:
    """Re-run over the same cache with ordinary replies: the requests each stage
    made, so a read that was cached made none."""
    stub = AnthropicAPIStub(_script()._route)
    _run(tmp_path, stub, transport, full=full, cache=DigestCache(tmp_path / "cache.sqlite"), work="warm",
         model=model)
    return _calls(stub)


def _calls(stub: AnthropicAPIStub) -> dict[str, int]:
    out: dict[str, int] = {}
    for record in stub.requests:
        if record["path"] == "/v1/messages":
            stage = stage_of(record["body"])
            out[stage] = out.get(stage, 0) + 1
        elif record["path"] == "/v1/messages/batches" and record["method"] == "POST":
            for item in record["body"]["requests"]:
                stage = "batch:" + stage_of(item["params"])
                out[stage] = out.get(stage, 0) + 1
    return out


def _batch_items(stub: AnthropicAPIStub, stage: str) -> list[list[dict]]:
    """Each batch submit's items for ``stage``, in submit order."""
    return [
        [item for item in r["body"]["requests"] if stage_of(item["params"]) == stage]
        for r in stub.requests if r["path"] == "/v1/messages/batches" and r["method"] == "POST"
    ]


def _statuses(ctx) -> dict[str, str]:
    return {s.stage: s.status for s in ctx.stage_results}


def _sheet(ctx, name: str):
    [sheet] = [s for s in ctx.sheets if s.ref.display_label.startswith(name)]
    return sheet


def _records(ctx, family: str) -> list:
    return [r for r in ctx.run_usage.records if r.stage_family == family]


def _totals(ctx) -> dict[str, tuple[int, int, int, int]]:
    out: dict[str, list[int]] = {}
    for r in ctx.run_usage.records:
        t = out.setdefault(r.stage_family, [0, 0, 0, 0])
        t[0] += r.input_tokens
        t[1] += r.output_tokens
        t[2] += r.cache_read_tokens
        t[3] += r.cache_write_tokens
    return {k: tuple(v) for k, v in out.items()}


def _shaped(script, shape, *, stages=None, when=lambda params: True):
    """A route answering with the script's reply as API JSON, reshaped by
    ``shape(body, params)`` for the requests of ``stages`` (all by default)."""
    def route(params: dict) -> dict:
        body = message_json(script._route(params), model=params.get("model", ""))
        if (stages is None or stage_of(params) in stages) and when(params):
            body = shape(body, params)
        return body

    return route


def _first(predicate):
    """True for the first request that matches ``predicate``, never again."""
    seen = {"n": 0}

    def once(params: dict) -> bool:
        if not predicate(params):
            return False
        seen["n"] += 1
        return seen["n"] == 1

    return once


# --------------------------------------------------------------------------- #
# Nested batch errors, canceled and expired items (digest on the batch transport)
# --------------------------------------------------------------------------- #

# Measured: production classifies the nested error's own type. These four are
# a rejection of the request itself, so the identical item is not resubmitted;
# these four are server-side and are.
_PERMANENT = ("invalid_request_error", "authentication_error", "permission_error", "not_found_error")
_TRANSIENT = ("rate_limit_error", "timeout_error", "api_error", "overloaded_error")


def _item_once(envelope, stage: str = "digest"):
    """``batch_result`` answering M-101's first ``stage`` item with ``envelope``."""
    first = _first(lambda params: stage_of(params) == stage and _about_m101(params))
    return lambda custom_id, params: envelope if first(params) else None


def test_every_sdk_error_type_is_classified():
    # The two tables above cover every type the SDK names, but billing_error,
    # which is permanent since WP-01.5 (below).
    assert set(_PERMANENT) | set(_TRANSIENT) | {"billing_error"} == set(R.ERROR_TYPES)


@pytest.mark.parametrize("error_type", _PERMANENT, ids=list(_PERMANENT))
def test_a_permanent_item_error_is_named_and_not_resubmitted(tmp_path, error_type):
    stub = AnthropicAPIStub(_script()._route,
                            batch_result=_item_once(R.errored(error_type, "the detail")))

    ctx = _run(tmp_path, stub, "batch", full=False)

    assert _statuses(ctx)["digest"] == "PARTIAL"
    assert _sheet(ctx, "M-101").error == f"{error_type}: the detail"   # the nested type, not "error"
    assert _sheet(ctx, "M-102").error is None
    rounds = _batch_items(stub, "digest")
    assert len(rounds) == 1                                      # no follow-up batch
    assert "digest" not in _calls(stub)                          # and no full-rate real-time call


@pytest.mark.parametrize("error_type", _TRANSIENT, ids=list(_TRANSIENT))
def test_a_transient_item_error_is_resubmitted_and_recovered(tmp_path, error_type):
    stub = AnthropicAPIStub(_script()._route,
                            batch_result=_item_once(R.errored(error_type, "the detail")))

    ctx = _run(tmp_path, stub, "batch", full=False)

    assert _statuses(ctx)["digest"] == "COMPLETE"
    assert _sheet(ctx, "M-101").error is None
    rounds = _batch_items(stub, "digest")
    assert [len(r) for r in rounds] == [2, 1]                    # M-101 alone, in a follow-up batch
    assert "digest" not in _calls(stub)


def test_an_expired_item_is_resubmitted_and_recovered(tmp_path):
    stub = AnthropicAPIStub(_script()._route, batch_result=_item_once(R.EXPIRED))

    ctx = _run(tmp_path, stub, "batch", full=False)

    assert _statuses(ctx)["digest"] == "COMPLETE"
    assert [len(r) for r in _batch_items(stub, "digest")] == [2, 1]


def test_a_canceled_item_is_named_and_not_resubmitted(tmp_path):
    # The realistic envelope carries only its type: no message, no error.
    stub = AnthropicAPIStub(_script()._route, batch_result=_item_once(R.CANCELED))

    ctx = _run(tmp_path, stub, "batch", full=False)

    assert _statuses(ctx)["digest"] == "PARTIAL"
    assert _sheet(ctx, "M-101").error == "batch request canceled"
    assert [len(r) for r in _batch_items(stub, "digest")] == [2]
    assert _warm_calls(tmp_path, "batch", full=False) == {"batch:digest": 1}   # never cached


def test_a_billing_error_is_named_and_not_resubmitted(tmp_path):
    """``billing_error`` is a rejection of the account, not a server blip:
    resubmitting the identical item fails the same way while the account is
    out of credit. Remediation WP-01.5 (the owner's rule) made it permanent;
    it was resubmitted in a follow-up batch like a transient error (WP-02.3's
    recorded limit, flipped here)."""
    stub = AnthropicAPIStub(_script()._route,
                            batch_result=_item_once(R.errored("billing_error", "credit balance")))

    ctx = _run(tmp_path, stub, "batch", full=False)

    assert [len(r) for r in _batch_items(stub, "digest")] == [2]      # no follow-up batch
    assert _sheet(ctx, "M-101").error == "billing_error: credit balance"
    assert _statuses(ctx)["digest"] == "PARTIAL"
    assert "digest" not in _calls(stub)                                # and no real-time call


def test_recorded_limit_a_recovered_item_keeps_no_record_of_its_failed_attempt(tmp_path):
    """Recorded limit (WP-14.1, R3): the first attempt came back ``errored`` and
    the resubmission succeeded, but the ledger has one record for the sheet,
    numbered attempt 2; the errored attempt left none. WP-14.1 keeps a
    non-billable record for every non-succeeded envelope: this becomes two."""
    stub = AnthropicAPIStub(_script()._route,
                            batch_result=_item_once(R.errored("overloaded_error", "busy")))

    ctx = _run(tmp_path, stub, "batch", full=False)

    m101 = [r for r in _records(ctx, "digest") if r.stage_instance == "digest:SRC-0001:p0"]
    assert [(r.attempt_number, r.transport, r.terminal_status) for r in m101] == [(2, "BATCH", "COMPLETE")]


# --------------------------------------------------------------------------- #
# The critique's batch (hybrid): a failed envelope is a failed read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("envelope", [R.errored("overloaded_error", "busy"), R.CANCELED, R.EXPIRED],
                         ids=["errored", "canceled", "expired"])
def test_a_failed_critique_envelope_is_a_failed_read_that_is_read_again(tmp_path, envelope):
    stub = AnthropicAPIStub(_script()._route, batch_result=_item_once(envelope, "critique"))

    ctx = _run(tmp_path, stub, "hybrid")

    assert _statuses(ctx)["critique"] == "PARTIAL"
    assert ctx.errors == ["Critique: 1 sheet(s) returned incomplete or malformed critique reads"]
    assert _warm_calls(tmp_path, "hybrid").get("batch:critique") == 2      # M-101's two reads again


# --------------------------------------------------------------------------- #
# A batch polled through in_progress and canceling, results out of order
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("transport", ["batch", "hybrid", "economy"], ids=["batch", "hybrid", "economy"])
def test_a_batch_polled_to_its_end_completes_whatever_the_result_order(tmp_path, monkeypatch, transport):
    monkeypatch.setattr(BD, "_progressive_interval", lambda elapsed: 0)
    stub = AnthropicAPIStub(_script()._route, statuses=("in_progress", "canceling", "ended"),
                            order="reverse")

    ctx = _run(tmp_path, stub, transport)

    assert ctx.qc_status == "COMPLETE", _statuses(ctx)
    retrieves = [r for r in stub.requests if r["method"] == "GET" and r["path"].count("/") == 4]
    assert len(retrieves) >= 3 * len(_batch_items(stub, "digest") or _batch_items(stub, "critique"))
    # Each sheet kept its own digest though the results came back reversed.
    assert _sheet(ctx, "M-101").text.startswith("Sheet M-101")
    assert _sheet(ctx, "M-102").text.startswith("Sheet M-102")


# --------------------------------------------------------------------------- #
# Usage shapes: None counters, iterations, output details; nothing counted twice
# --------------------------------------------------------------------------- #


def _none_counters(body: dict, params: dict) -> dict:
    usage = body["usage"]
    usage["cache_read_input_tokens"] = None
    usage["cache_creation_input_tokens"] = None
    usage["server_tool_use"] = None
    return body


def _with_iterations(body: dict, params: dict) -> dict:
    usage = body["usage"]
    half_in, half_out = usage["input_tokens"] // 2, usage["output_tokens"] // 2
    usage["iterations"] = [
        R.iteration("message", input_tokens=half_in, output_tokens=half_out),
        R.iteration("fallback_message", model="claude-opus-4-8",
                    input_tokens=usage["input_tokens"] - half_in,
                    output_tokens=usage["output_tokens"] - half_out),
    ]
    usage["fallback_credit"] = {"status": {"type": "redeemed"}}
    usage["output_tokens_details"] = {"thinking_tokens": half_out}
    return body


def _control_totals(tmp_path: Path, transport: str):
    control = tmp_path / "control"
    control.mkdir()
    return _totals(_run(control, AnthropicAPIStub(_script()._route), transport))


@pytest.mark.parametrize("transport", ["fast", "economy"], ids=["fast", "economy"])
def test_none_usage_counters_read_as_zero_on_every_stage(tmp_path, transport):
    run = tmp_path / "run"
    run.mkdir()
    stub = AnthropicAPIStub(_shaped(_script(), _none_counters))

    ctx = _run(run, stub, transport)

    assert ctx.qc_status == "COMPLETE"
    assert _totals(ctx) == _control_totals(tmp_path, transport)
    # server_tool_use null: the citation check falls back to its one-per-request
    # lower bound rather than reading the count as zero.
    assert [r.billable_tool_uses for r in _records(ctx, "citation")] == [{"web_search": 1}]


@pytest.mark.parametrize("transport", ["fast", "economy"], ids=["fast", "economy"])
def test_iterations_and_output_details_are_not_counted_twice(tmp_path, transport):
    # The top-level usage already totals every iteration, and output_tokens
    # already includes the thinking tokens: adding either would double-count.
    run = tmp_path / "run"
    run.mkdir()
    stub = AnthropicAPIStub(_shaped(_script(), _with_iterations))

    ctx = _run(run, stub, transport)

    assert ctx.qc_status == "COMPLETE"
    assert _totals(ctx) == _control_totals(tmp_path, transport)


def test_a_streamed_reply_counts_its_cumulative_usage_once(tmp_path):
    # message_start carries the input tokens and message_delta the cumulative
    # usage again (the API's shape): the digest's record is the reply's usage
    # once, the same as a non-streamed reply of the same body.
    ctx = _run(tmp_path, AnthropicAPIStub(_script()._route), full=False)

    assert [(r.input_tokens, r.output_tokens) for r in _records(ctx, "digest")] == [(500, 90), (500, 90)]


def _cache_split(body: dict, params: dict) -> dict:
    body["usage"].update(R.usage(body["usage"]["input_tokens"], body["usage"]["output_tokens"],
                                 cache_read=400, cache_split=(300, 700)))
    return body


def test_recorded_limit_the_cache_write_ttl_split_is_priced_at_one_rate(tmp_path):
    """Recorded limit (WP-14.2, C3): the reply splits its 1,000 cache-write
    tokens 300 at the 5-minute rate and 700 at the 1-hour rate
    (``usage.cache_creation``), but nothing reads the split: each record is
    priced at its one ``cache_write_ttl``. At Opus 5.5's rates ($4/M input,
    $20/M output, $0.20/M cache read, $5/M 5-minute and $8/M 1-hour cache
    write), a digest record (500 in, 90 out, 400 read) costs $0.008880 flat and
    $0.010980 split. The investigation's record sums its two turns (1-hour
    breakpoint: 160 in, 32 out, 800 read, 2,000 written, split 600 and 1,400):
    $0.017440 flat, $0.015640 split. WP-14.2 prices by the split: these become
    the split figures. (First recorded at Opus 5's rates: $0.011200 / $0.013825
    and $0.022000 / $0.019750. Re-priced for the Opus 5.5 default; the limit is
    unchanged.)"""
    stub = AnthropicAPIStub(_shaped(_script(), _cache_split))

    ctx = _run(tmp_path, stub)

    assert [(r.cache_read_tokens, r.cache_write_tokens, r.cache_write_ttl, r.estimated_cost)
            for r in _records(ctx, "digest")] == [(400, 1000, None, Decimal("0.008880"))] * 2
    [inv] = _records(ctx, "investigate")
    assert (inv.cache_write_tokens, inv.cache_write_ttl, inv.estimated_cost) == (2000, "1h", Decimal("0.017440"))


def test_recorded_limit_web_fetch_requests_are_not_counted(tmp_path):
    """Recorded limit (WP-14.3, U1): the citation reply reports 2 searches and
    3 fetches (``usage.server_tool_use``); the ledger keeps the searches only.
    WP-14.3's shared reader counts fetches too: this gains ``web_fetch: 3``."""
    def fetches(body, params):
        body["usage"]["server_tool_use"] = R.server_tool_use(web_search=2, web_fetch=3)
        return body

    stub = AnthropicAPIStub(_shaped(_script(), fetches, stages={"citation"}))

    ctx = _run(tmp_path, stub)

    assert [r.billable_tool_uses for r in _records(ctx, "citation")] == [{"web_search": 2}]


def test_recorded_limit_the_serving_model_is_not_read(tmp_path):
    """Recorded limit (WP-14.3 and WP-14.6, U1): every Opus 5.5 reply was served
    by Opus 4.8 (``message.model``, as after a refusal fallback), but the
    ledger names the requested model. WP-14.3 reads the serving model and
    WP-14.6 carries it to the manifest: these records name claude-opus-4-8."""
    def served_by_opus_48(body, params):
        body["model"] = "claude-opus-4-8"
        return body

    stub = AnthropicAPIStub(_shaped(_script(), served_by_opus_48,
                                    when=lambda params: params.get("model") == OPUS))

    ctx = _run(tmp_path, stub)

    assert ctx.qc_status == "COMPLETE"
    opus_families = {"digest", "critique", "review_plan", "cross_qc", "synthesis", "focus", "investigate"}
    assert {r.model for r in ctx.run_usage.records if r.stage_family in opus_families} == {OPUS}


# --------------------------------------------------------------------------- #
# A refusal carrying stop_details
# --------------------------------------------------------------------------- #


def _refusal(body: dict, params: dict) -> dict:
    body["content"] = [R.text("I can't help with that request.")]
    body["stop_reason"] = "refusal"
    body["stop_details"] = R.refusal_stop_details("cyber", explanation="declined",
                                                  recommended_model="claude-opus-4-8")
    return body


def test_a_refused_digest_fails_its_sheet_and_is_read_again(tmp_path):
    stub = AnthropicAPIStub(_shaped(_script(), _refusal, stages={"digest"}, when=_about_m101))

    ctx = _run(tmp_path, stub, full=False)

    # The category from stop_details is named (remediation WP-01.5, the
    # owner's rule; re-baselined from "refused digest (stop_reason='refusal')").
    assert _sheet(ctx, "M-101").error == "refused digest (stop_reason='refusal', category='cyber')"
    assert _statuses(ctx)["digest"] == "PARTIAL"
    assert _warm_calls(tmp_path, full=False) == {"digest": 1}


# stage -> (its status, whether the warm run asks again) with every request of
# that stage refused. Measured; each is right today.
_REFUSED_RIGHT = {
    "identity": ("FAILED", True),
    "review_plan": ("FAILED", True),
    "critique": ("FAILED", True),
    "verification": ("FAILED", True),
    "citation": ("PARTIAL", True),
}


@pytest.mark.parametrize("stage", sorted(_REFUSED_RIGHT), ids=sorted(_REFUSED_RIGHT))
def test_a_refused_stage_is_not_complete_and_not_cached(tmp_path, stage):
    stub = AnthropicAPIStub(_shaped(_script(), _refusal, stages={stage}))

    ctx = _run(tmp_path, stub)

    status, asks_again = _REFUSED_RIGHT[stage]
    assert _statuses(ctx)[stage] == status
    assert (_warm_calls(tmp_path).get(stage, 0) > 0) == asks_again


@pytest.mark.parametrize("stage", ["synthesis", "focus"], ids=["synthesis", "focus"])
def test_recorded_limit_synthesis_and_focus_keep_and_cache_a_refusal(tmp_path, stage):
    """Recorded limit (WP-01.6): neither stage reads the stop reason, so a
    refusal's explanation is kept as the synthesis or the focus report (the
    synthesis stage reads COMPLETE) and cached: the warm run asks nothing.
    WP-01.6 moves them onto ``core.terminal_outcome``: the refusal fails the
    stage, is not cached, and the warm run asks again."""
    stub = AnthropicAPIStub(_shaped(_script(), _refusal, stages={stage}))

    ctx = _run(tmp_path, stub)

    kept = ctx.synthesis_text if stage == "synthesis" else ctx.focus_report_text
    assert "I can't help with that request." in kept
    assert _statuses(ctx)["synthesis"] == "COMPLETE"
    assert _warm_calls(tmp_path).get(stage, 0) == 0


def test_recorded_limit_cross_qc_names_only_an_empty_refusal(tmp_path):
    """Recorded limit (WP-06.3): cross-QC checks only for an empty reply, so a
    refusal with an explanation reads as unparseable output. WP-06.3 checks the
    stop reason: the error names the refusal."""
    stub = AnthropicAPIStub(_shaped(_script(), _refusal, stages={"cross_qc"}))

    ctx = _run(tmp_path, stub)

    assert _statuses(ctx)["cross_qc"] == "PARTIAL"
    [error] = [e for e in ctx.errors if e.startswith("Cross-sheet QC")]
    assert "no parseable findings object" in error and "refusal" not in error


def test_a_refused_batch_item_is_resubmitted_on_the_fallback_model(tmp_path):
    """R2 (remediation WP-01.5, the owner's rules): a batch digest refused with
    ``stop_details`` naming the cyber category is resubmitted as a batch item on
    the registry's fallback (``claude-opus-4-8``, also the recommended model
    here), inside the shared per-sheet retry budget, never in real time; the
    finished read is cached under the requested model's key, so the warm run
    asks nothing. It was failed and never retried (WP-02.3's recorded limit,
    flipped here). On Opus 5, the one model that declares a host route (the
    5.5 defaults declare none: ``test_batch_refusal_recovery``)."""
    stub = AnthropicAPIStub(_shaped(_script(), _refusal, stages={"digest"},
                                    when=_first(lambda p: stage_of(p) == "digest" and _about_m101(p))))

    ctx = _run(tmp_path, stub, "batch", full=False, model="claude-opus-5")

    assert _sheet(ctx, "M-101").error is None
    rounds = _batch_items(stub, "digest")
    assert [len(r) for r in rounds] == [2, 1]
    assert rounds[1][0]["params"]["model"] == "claude-opus-4-8"
    assert _statuses(ctx)["digest"] == "COMPLETE"
    assert "digest" not in _calls(stub)                                # never real time
    assert _warm_calls(tmp_path, "batch", full=False, model="claude-opus-5") == {}


# --------------------------------------------------------------------------- #
# Event streams: cut early, ended cleanly, by an error event, or dropped
# --------------------------------------------------------------------------- #


def _stream_once(stage: str, cut: str, end: str, when=lambda params: True):
    first = _first(lambda params: stage_of(params) == stage and when(params))
    return lambda record: (cut, end) if first(record["body"]) else None


@pytest.mark.parametrize("cut", ["before_text", "after_text", "after_content"],
                         ids=["before_text", "after_text", "after_content"])
def test_a_digest_stream_that_ends_before_message_delta_fails_and_is_read_again(tmp_path, cut):
    stub = AnthropicAPIStub(_script()._route, stream=_stream_once("digest", cut, "eof", _about_m101))

    ctx = _run(tmp_path, stub, full=False)

    sheet = _sheet(ctx, "M-101")
    assert sheet.stop_reason is None and sheet.error.endswith("(stop_reason=None)")
    assert _warm_calls(tmp_path, full=False) == {"digest": 1}


def test_a_stream_missing_only_message_stop_is_a_complete_read(tmp_path):
    # The SDK cannot tell it from a complete stream: message_delta carried the
    # stop reason. So neither can production, rightly.
    stub = AnthropicAPIStub(_script()._route,
                            stream=_stream_once("digest", "before_message_stop", "eof", _about_m101))

    ctx = _run(tmp_path, stub, full=False)

    assert _sheet(ctx, "M-101").error is None
    assert _warm_calls(tmp_path, full=False) == {}


@pytest.mark.parametrize("cut", ["before_text", "after_content"], ids=["before_text", "after_content"])
def test_a_critique_stream_that_ends_before_message_delta_is_a_failed_read(tmp_path, cut):
    stub = AnthropicAPIStub(_script()._route, stream=_stream_once("critique", cut, "eof", _about_m101))

    ctx = _run(tmp_path, stub)

    assert _statuses(ctx)["critique"] == "PARTIAL"
    assert _warm_calls(tmp_path).get("critique") == 2


@pytest.mark.parametrize("end", ["error", "drop"], ids=["error-event", "dropped"])
def test_recorded_limit_an_interrupted_digest_stream_is_not_retried_and_its_usage_is_lost(tmp_path, end):
    """Recorded limit (WP-01.7, U1): the stream fails mid-read, by an SSE
    ``error`` event (the SDK raises ``APIStatusError`` with status 200) or a
    dropped connection (``httpx2.RemoteProtocolError``, which the SDK does not
    wrap). The digest's transient-error test knows neither, so the sheet fails
    after one request; and the attempt is recorded with 0 tokens, though
    ``message_start`` had reported 500 input tokens. WP-01.7 captures the
    partial read and its usage (``current_message_snapshot``) and threads the
    outcome through the retry loop: this becomes a retry and a record of the
    attempt's usage."""
    stub = AnthropicAPIStub(_script()._route, stream=_stream_once("digest", "after_text", end, _about_m101))

    ctx = _run(tmp_path, stub, full=False)

    digest_requests = [r for r in stub.messages() if stage_of(r["body"]) == "digest"]
    assert sum(_about_m101(r["body"]) for r in digest_requests) == 1
    sheet = _sheet(ctx, "M-101")
    assert sheet.error is not None and (sheet.input_tokens, sheet.output_tokens) == (0, 0)
    [m101] = [r for r in _records(ctx, "digest") if r.stage_instance == "digest:SRC-0001:p0"]
    assert (m101.input_tokens, m101.output_tokens) == (0, 0)


@pytest.mark.parametrize("stage, cut", [("synthesis", "after_text"), ("focus", "after_text"),
                                        ("review_plan", "after_content")],
                         ids=["synthesis", "focus", "review_plan"])
def test_recorded_limit_a_stream_cut_before_message_delta_is_kept_and_cached(tmp_path, stage, cut):
    """Recorded limit (WP-01.6): the stream ended cleanly before its
    ``message_delta``, so the reply has no stop reason (N27's shape) and only
    ``message_start``'s usage (0 output tokens); the synthesis and focus keep
    the half-written text and the planner the plan, and each is cached: the
    warm run asks nothing. WP-01.6 treats a missing stop reason as
    unfinished: none is kept or cached."""
    stub = AnthropicAPIStub(_script()._route, stream=_stream_once(stage, cut, "eof"))

    ctx = _run(tmp_path, stub)

    assert _statuses(ctx).get(stage, "COMPLETE") == "COMPLETE"
    assert [r.output_tokens for r in _records(ctx, stage)] == [0]     # the cut reply, kept
    if stage == "synthesis":
        assert ctx.synthesis_text and "consistent" not in ctx.synthesis_text   # the first half only
    assert _warm_calls(tmp_path).get(stage, 0) == 0


# stage -> the usage records a dropped stream leaves: none, or one of 0 tokens.
_DROPPED_USAGE = {"synthesis": [], "focus": [], "review_plan": [(0, 0)]}


@pytest.mark.parametrize("stage", sorted(_DROPPED_USAGE), ids=sorted(_DROPPED_USAGE))
def test_recorded_limit_an_interrupted_stream_loses_its_usage(tmp_path, stage):
    """Recorded limit (WP-01.7, WP-14.5): a dropped connection mid-stream
    leaves the stage with an error and its usage lost, though the request was
    billed from ``message_start`` (300 input tokens for the planner, 300 for
    synthesis, 1 for the focus report): synthesis and the focus report record
    nothing, the planner a record of 0 tokens. WP-01.7 captures the partial
    usage: each gains a record of what ``message_start`` reported."""
    stub = AnthropicAPIStub(_script()._route, stream=_stream_once(stage, "after_text", "drop"))

    ctx = _run(tmp_path, stub)

    assert [(r.input_tokens, r.output_tokens) for r in _records(ctx, stage)] == _DROPPED_USAGE[stage]
    assert any("peer closed connection" in e for e in ctx.errors)


# --------------------------------------------------------------------------- #
# A fallback block mid-content
# --------------------------------------------------------------------------- #


def _split_mid_word(where: str):
    """Splice a fallback block into the reply's text, mid-word, inside the
    fenced JSON (``json``) or in the prose before it (``prose``)."""
    def shape(body: dict, params: dict) -> dict:
        whole = "".join(b["text"] for b in body["content"] if b.get("type") == "text")
        fence = whole.find("```")
        lo, hi = (fence, len(whole)) if where == "json" and fence >= 0 else (0, max(fence, 0) or len(whole))
        words = [m for m in re.finditer(r"[A-Za-z]{4,}", whole) if lo <= m.start() < hi]
        word = words[len(words) // 2]
        return R.splice_fallback(body, word.start() + len(word.group()) // 2, to_model="claude-opus-4-8")

    return shape


def test_recorded_limit_a_fallback_inside_the_findings_json_loses_the_finding_and_is_cached(tmp_path):
    """Recorded limit (WP-01.6, U2): ``digest._message_text`` joins the text
    blocks on either side of a ``fallback`` block with ``"\\n"``, so a boundary
    inside the fenced findings JSON breaks it: M-101's one finding is lost (the
    block is noted unparseable) and the read is cached as finished. WP-01.6's
    fallback-aware join keeps the finding (1)."""
    stub = AnthropicAPIStub(_shaped(_script(), _split_mid_word("json"), stages={"digest"}, when=_about_m101))

    ctx = _run(tmp_path, stub, full=False)

    sheet = _sheet(ctx, "M-101")
    assert sheet.error is None and sheet.findings == []
    assert "unparseable" in sheet.findings_note
    assert _warm_calls(tmp_path, full=False) == {}


def test_recorded_limit_a_fallback_in_the_prose_splits_a_word_and_is_cached(tmp_path):
    """Recorded limit (WP-01.6, U2): the same join puts a ``"\\n"`` inside a
    word of the prose digest (I-2: the prose is sacred) and the read is cached.
    WP-01.6's join keeps the prose byte-identical to the served text."""
    stub = AnthropicAPIStub(_shaped(_script(), _split_mid_word("prose"), stages={"digest"}, when=_about_m101))

    ctx = _run(tmp_path, stub, full=False)
    control = tmp_path / "control"
    control.mkdir()
    served = _sheet(_run(control, AnthropicAPIStub(_script()._route), full=False), "M-101").text

    sheet = _sheet(ctx, "M-101")
    assert sheet.error is None and len(sheet.findings) == 1
    # The served prose with one "\n" inserted mid-word, nothing else.
    assert sheet.text != served and len(sheet.text) == len(served) + 1
    assert any(sheet.text[:i] + sheet.text[i + 1:] == served
               for i, ch in enumerate(sheet.text) if ch == "\n"
               and sheet.text[i - 1:i].isalpha() and sheet.text[i + 1:i + 2].isalpha())
    assert _warm_calls(tmp_path, full=False) == {}


def test_recorded_limit_a_fallback_in_a_critique_fails_a_good_read(tmp_path):
    """Recorded limit (WP-01.6, U2): the critique's reply is fenced JSON, so the
    ``"\\n"`` join across the fallback boundary makes it unparseable and a
    finished, correct read fails. WP-01.6's join: the reads are COMPLETE."""
    stub = AnthropicAPIStub(_shaped(_script(), _split_mid_word("json"), stages={"critique"}))

    ctx = _run(tmp_path, stub)

    assert _statuses(ctx)["critique"] == "FAILED"


def test_recorded_limit_the_investigation_executes_a_pre_fallback_tool_use(tmp_path):
    """Recorded limit (WP-13.4, N20): the investigation's first turn carries a
    ``tool_use`` from the declined model, a ``fallback`` block, then the serving
    model's ``tool_use``. Both are executed and answered, and the fallback
    block is echoed into the next request. WP-13.4 filters pre-fallback blocks
    before building the tool requests: only ``toolu_post`` is answered."""
    def pre_and_post(body: dict, params: dict) -> dict:
        tools = [b for b in body["content"] if b.get("type") == "tool_use"]
        if not tools:
            return body
        pre = dict(tools[0], id="toolu_pre", input={"rect": [1.0, 1.0, 50.0, 50.0]})
        post = dict(tools[0], id="toolu_post")
        body["content"] = [pre, R.fallback_block(OPUS, "claude-opus-4-8"), post]
        body["model"] = "claude-opus-4-8"
        return body

    stub = AnthropicAPIStub(_shaped(_script(), pre_and_post, stages={"investigation"},
                                    when=_first(lambda p: stage_of(p) == "investigation")))

    _run(tmp_path, stub)

    turns = [r["body"]["messages"] for r in stub.messages() if stage_of(r["body"]) == "investigation"]
    answered = [b["tool_use_id"] for m in turns[1] if isinstance(m.get("content"), list)
                for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"]
    echoed = [b.get("type") for m in turns[1] if m["role"] == "assistant" for b in m["content"]]
    assert answered == ["toolu_pre", "toolu_post"]
    assert echoed == ["tool_use", "fallback", "tool_use"]
