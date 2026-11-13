"""XFast: API fast mode (``speed: "fast"``) on a run's Opus requests.

What must hold: only a run that asked for it sends ``speed``, only to a model
that declares fast mode, a platform that rejects it degrades to standard speed
instead of failing the run, and every fast response is billed — and every
estimate quoted — at the fast-mode rate. Hermetic (I-4).
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from drawing_analyzer import resource_pressure
from drawing_analyzer.core import api_config as api
from drawing_analyzer.core.request_usage import RequestUsage
from drawing_analyzer.cost import (
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
)
from drawing_analyzer.models import RunUsage, resolve_run_configuration
from drawing_analyzer.pipeline import _record_usage
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)

OPUS_55 = "claude-opus-5-5"
SONNET_55 = "claude-sonnet-5-5"
HAIKU_55 = "claude-haiku-5-5"


@pytest.fixture(autouse=True)
def _reset_latches():
    """Both self-healing latches are process-wide; never leak them."""
    api._fast_mode_available = True
    api._refusal_fallback_available = True
    yield
    api._fast_mode_available = True
    api._refusal_fallback_available = True


@contextlib.contextmanager
def _run(speed: str | None):
    """Bind this thread to a run recorder that asked for ``speed``."""
    pressure = resource_pressure.ResourcePressure()
    pressure.requested_speed = speed
    previous = resource_pressure.bind_thread(pressure)
    try:
        yield pressure
    finally:
        resource_pressure.bind_thread(previous)


class _Rejected(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class _Client:
    """Records every request on both namespaces; optionally rejects ``speed``."""

    def __init__(self, reject_speed: Exception | None = None):
        self.calls: list[dict] = []
        self._reject = reject_speed
        create = self._create
        self.messages = SimpleNamespace(create=create, stream=None)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create, stream=None))

    def _create(self, **kw):
        self.calls.append(kw)
        if self._reject is not None and (kw.get("extra_body") or {}).get("speed"):
            raise self._reject
        return SimpleNamespace(content=[], model=kw.get("model"))


def _speed(kw: dict) -> str | None:
    return (kw.get("extra_body") or {}).get("speed")


@pytest.mark.parametrize("requested, model, sent", [
    ("fast", OPUS_55, "fast"),
    ("fast", SONNET_55, None),      # no fast mode on Sonnet: never sent
    ("fast", HAIKU_55, None),
    (None, OPUS_55, None),          # a standard run never asks
])
def test_speed_is_sent_only_for_a_fast_run_on_a_fast_mode_model(requested, model, sent):
    client = _Client()
    with _run(requested):
        api.call_with_refusal_fallback(
            client, {"model": model, "max_tokens": 10}, model=model, method="create",
        )
    (call,) = client.calls
    assert _speed(call) == sent
    # Fast mode never displaces the refusal fallback on a model that has both.
    if api.model_capabilities(model).supports_refusal_fallback:
        assert call["fallbacks"] == "default"


def test_an_unbound_thread_never_sends_speed():
    client = _Client()
    api.call_with_refusal_fallback(
        client, {"model": OPUS_55, "max_tokens": 10}, model=OPUS_55, method="create",
    )
    assert _speed(client.calls[0]) is None


def test_fast_mode_merges_into_an_existing_extra_body():
    with _run("fast"):
        out = api.apply_fast_mode(
            {"model": OPUS_55, "extra_body": {"diagnostics": {"previous_message_id": None}}},
            model=OPUS_55,
        )
    assert out["extra_body"] == {
        "diagnostics": {"previous_message_id": None}, "speed": "fast",
    }


@pytest.mark.parametrize("message, latches", [
    ("invalid_request_error: speed 'fast' is not available for this organization", True),
    ("invalid_request_error: fast mode is not supported on this platform", True),
    ("invalid_request_error: max_tokens must be positive", False),
])
def test_a_fast_mode_rejection_resends_at_standard_speed_and_latches(message, latches):
    client = _Client(reject_speed=_Rejected(400, message))
    with _run("fast"):
        if not latches:
            with pytest.raises(_Rejected):
                api.call_with_refusal_fallback(
                    client, {"model": OPUS_55, "max_tokens": 10}, model=OPUS_55,
                    method="create",
                )
            assert api._fast_mode_available is True
            return
        api.call_with_refusal_fallback(
            client, {"model": OPUS_55, "max_tokens": 10}, model=OPUS_55, method="create",
        )
        # One rejected fast attempt, one standard resend; the latch holds for
        # the rest of the process, so the next request never asks again.
        assert [_speed(c) for c in client.calls] == ["fast", None]
        assert api._fast_mode_available is False
        api.call_with_refusal_fallback(
            client, {"model": OPUS_55, "max_tokens": 10}, model=OPUS_55, method="create",
        )
    assert [_speed(c) for c in client.calls] == ["fast", None, None]


def test_a_transient_error_on_a_fast_request_is_left_to_the_retry_loop():
    client = _Client(reject_speed=_Rejected(429, "rate_limit_error: fast mode capacity"))
    with _run("fast"), pytest.raises(_Rejected):
        api.call_with_refusal_fallback(
            client, {"model": OPUS_55, "max_tokens": 10}, model=OPUS_55, method="create",
        )
    assert api._fast_mode_available is True


# --------------------------------------------------------------------------- #
# Billing
# --------------------------------------------------------------------------- #


def _usage_dict(speed: str | None) -> dict:
    usage = {"input_tokens": 100_000, "output_tokens": 10_000,
             "cache_read_input_tokens": 50_000}
    if speed:
        usage["speed"] = speed
    return {"id": "msg_1", "stop_reason": "end_turn", "usage": usage}


@pytest.mark.parametrize("model, multiplier", [(OPUS_55, 2), (SONNET_55, 1)])
def test_a_fast_response_is_billed_at_the_models_fast_rate(model, multiplier):
    def billed(speed):
        usage = RunUsage()
        _record_usage(
            usage, family="digest", instance="digest:SRC-0001:p0", model=model,
            request_usage=[RequestUsage.from_message(_usage_dict(speed))],
        )
        return usage

    standard, fast = billed(None), billed("fast")
    assert fast.total_estimated_cost == standard.total_estimated_cost * multiplier
    assert fast.records[0].speed == "fast"
    assert fast.records[0].to_dict()["speed"] == "fast"
    # A standard record serializes exactly as it did before fast mode existed.
    assert "speed" not in standard.records[0].to_dict()


@pytest.mark.parametrize("transport, latched_off, fast", [
    ("REAL_TIME", False, True),
    ("BATCH", False, False),        # the Batch API has no fast mode
    ("REAL_TIME", True, False),     # the platform refused it: standard speed
])
def test_a_summed_stage_record_is_fast_exactly_when_its_requests_were(
    transport, latched_off, fast,
):
    api._fast_mode_available = not latched_off
    usage = RunUsage()
    with _run("fast"):
        record = _record_usage(
            usage, family="critique", instance="critique:SRC-0001:p0", model=OPUS_55,
            transport=transport, input_tokens=10_000, output_tokens=1_000,
        )
    assert (record.speed == "fast") is fast


# --------------------------------------------------------------------------- #
# Configuration and estimates
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("use_batch, critique_use_batch, resolved", [
    (False, False, True),
    (True, True, False),
    (False, True, False),           # Hybrid batches the critique: no fast mode
])
def test_fast_mode_resolves_only_for_an_all_real_time_run(use_batch, critique_use_batch, resolved):
    config = resolve_run_configuration(
        qc_markups=True, use_batch=use_batch, critique_use_batch=critique_use_batch,
        fast_mode=True,
    )
    assert config.fast_mode is resolved
    assert config.to_dict()["fast_mode"] is resolved


@pytest.mark.parametrize("batch, factor", [(False, 2), (True, 1)])
def test_the_digest_estimate_prices_fast_mode_on_real_time_opus_reads(batch, factor):
    standard = estimate_drawing_set_cost(1, synthesize=False, batch=batch)
    fast = estimate_drawing_set_cost(1, synthesize=False, batch=batch, fast_mode=True)
    assert fast.fast_mode is True and standard.fast_mode is False
    assert fast.low_cost == pytest.approx(standard.low_cost * factor)
    assert fast.high_cost == pytest.approx(standard.high_cost * factor)


def test_the_full_qc_estimate_prices_fast_mode_only_where_it_is_sent():
    standard = estimate_exhaustive_run_cost(4, batch=False, critique_batch=False)
    fast = estimate_exhaustive_run_cost(4, batch=False, critique_batch=False, fast_mode=True)
    by_stage = {c.stage: c for c in standard.components}
    changed = {
        c.stage for c in fast.components
        if c.cost != pytest.approx(by_stage[c.stage].cost)
    }
    assert by_stage["Digest"].cost * 2 == pytest.approx(
        next(c.cost for c in fast.components if c.stage == "Digest")
    )
    # Stages on models without fast mode keep their price, so the run total
    # rises by less than the full premium.
    assert "Digest" in changed and changed != set(by_stage)
    assert standard.high_cost < fast.high_cost < standard.high_cost * 2


# --------------------------------------------------------------------------- #
# The pipeline binds the run's speed
# --------------------------------------------------------------------------- #


def _pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "set.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=792, height=612)
        page.insert_text((80, 120), "SPRINKLER MAIN 4 IN")
        page.insert_text((650, 560), "FP-101")
        doc.save(str(path))
    return path


def _client(calls):
    class _M(StreamingMessagesMixin):
        def create(_self, **kw):
            calls.append(kw)
            return FakeMessage(
                content=[FakeTextBlock(text="Sheet FP-101\n\n```json\n{\"findings\": []}\n```")],
                usage=FakeUsage(input_tokens=100, output_tokens=20),
            )

    class _C(BetaClientMixin):
        def __init__(self):
            self.messages = _M()

    return _C()


@pytest.mark.parametrize("fast_mode, use_batch, sent", [
    (True, False, "fast"),
    (False, False, None),
])
def test_an_xfast_run_sends_its_opus_digest_in_fast_mode(tmp_path, fast_mode, use_batch, sent):
    from drawing_analyzer.pipeline import extract_drawing_context

    calls: list = []
    ctx = extract_drawing_context(
        [_pdf(tmp_path)], client=_client(calls), rows=1, cols=1,
        use_batch=use_batch, fast_mode=fast_mode, model=OPUS_55,
    )
    assert calls and all(_speed(kw) == sent for kw in calls)
    digest_records = [r for r in ctx.run_usage.records if r.stage_family == "digest"]
    assert digest_records and all(r.speed == sent for r in digest_records)
