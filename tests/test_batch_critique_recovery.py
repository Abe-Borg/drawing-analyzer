"""A failed batch critique read is retried, and a critique cut off at
``max_tokens`` gets one raised-cap retry, on both critique transports
(remediation WP-01.8; the owner's rules).

Before WP-01.8 every failed batch critique read failed and was never retried:
refused, the nine errored types, canceled, expired, ``max_tokens``
(``batch_critique`` had no follow-up batch, no harvest and no rescue), and the
real-time critique had no raised-cap retry. Measured on SDK 1.7.0 and 1.8.0, on
Opus 5.5, Sonnet 5.5 and Opus 5: the pipeline's critique stage read PARTIAL
(3 of 4 reads judged) and every warm run read the sheet again. The owner's
rules, recorded in ``_plans/DECISIONS.md`` (D-1's WP-01.8 note):

* **Which reads: the digest's one retry predicate**, shared rather than
  copied (``batch_digest._item_retry_params`` made slot-agnostic): a transient
  errored item (``api_error``, ``overloaded_error``, ``rate_limit_error``,
  ``timeout_error``) and an expired one are resubmitted as they were; a
  refusal whose ``stop_details.category`` has a registry route goes to its
  fallback, once; a read stopped at ``max_tokens`` goes at twice the cap
  (64k -> 128k, clamped to the model's cap). A permanent error, a canceled
  item, an unrouted or category-less refusal, a context-window stop, no stop
  reason, a continuation, an unknown stop and a malformed read are not.
* **Where:** fresh critique batches, up to the rounds ceiling and inside the
  remaining collection bound. Never full-rate real time.
* **The budget is WP-01.5's per-sheet budget**
  (``DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS``, default 4): every
  resubmitted read of a sheet counts one.
* **The read kept:** a failed read keeps nothing (WP-01.4), so a finished
  retry becomes the read under the same ``run_id``; a retry that fails again
  leaves the read failed, its error the first attempt's with the digest's
  suffix (``; retry: …``, ``; N retries, the last: …``, ``; retry on
  <model>: …``, ``; retry failed: …``). Every attempt's tokens are the read's.
* **A follow-up batch that never ends** is canceled (best effort) and ends the
  recovery; its reads are named ``; retry: critique batch not collected (…)``.
* **The real-time critique** gets one raised-cap retry per read, as the
  real-time digest does, outside the batch budget.
* **Merge, tally, cache:** the recovered read is merged as any read, judged in
  D-2's tally (eligible stays reads, never attempts), and a result whose every
  read finished is stored at both levels under the requested key. No key,
  contract or schema moved.
* **Usage:** summed on the sheet's one critique record.

Every test drives the real SDK over ``tests/fixtures/sdk_transport.py``.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import httpx2
import pytest

import drawing_analyzer.batch_critique as BC
import drawing_analyzer.batch_digest as BD
import drawing_analyzer.critique as C
import drawing_analyzer.digest as D
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import CONFIDENCE_NOT_ASSESSED_PARTIAL, CONFIDENCE_REPRODUCED
from tests.fixtures import sdk_responses as R
from tests.fixtures.sdk_transport import AnthropicAPIStub, error_400
from tests.test_batch_refusal_recovery import _Clock, _StallingStub
from tests.test_drawing_batch import _make_sheet
# The contract tests' autouse fixture: every self-healing latch starts on, one
# upload worker, the upload release run inline.
from tests.test_sdk_contract import _fresh_latches, assert_request_contract  # noqa: F401

OPUS_55 = "claude-opus-5-5"
SONNET_55 = "claude-sonnet-5-5"
OPUS_5 = "claude-opus-5"
OPUS_48 = "claude-opus-4-8"
SONNET_5 = "claude-sonnet-5"
MODELS_55 = (OPUS_55, SONNET_55)

FINDING = {"sheet_id": "M-100", "category": "code", "severity": "low",
           "text": "Relief valve setting is above the rated pressure.",
           "source_quote": "RELIEF VALVE", "tile_label": "r1c1"}
TRANSIENT = ("rate_limit_error", "timeout_error", "api_error", "overloaded_error")
PERMANENT = ("invalid_request_error", "authentication_error", "billing_error",
             "permission_error", "not_found_error", "request_too_large")
_NOOP = lambda _s: None  # noqa: E731 - tests never wait


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _body(findings=(FINDING,)) -> str:
    return "```json\n" + json.dumps({"findings": list(findings)}) + "\n```"


def _reply(params: dict, *, text: str | None = None, stop: str | None = "end_turn",
           stop_details: dict | None = None) -> dict:
    content = [R.text(_body() if text is None else text)] if text != "" else []
    return R.message(content, model=params.get("model", OPUS_55), stop_reason=stop,
                     stop_details=stop_details)


def _ok(params: dict) -> dict:
    return _reply(params)


def _errored(error_type: str):
    return lambda params: R.errored(error_type, "the detail")


def _succeeded(**kwargs):
    return lambda params: R.succeeded(_reply(params, **kwargs))


def _refused(category: str | None = "cyber", **kwargs):
    return _succeeded(text="", stop="refusal",
                      stop_details=R.refusal_stop_details(category, explanation="declined",
                                                          **kwargs))


EXPIRED = lambda params: R.EXPIRED  # noqa: E731
CANCELED = lambda params: R.CANCELED  # noqa: E731
CUT = _succeeded(stop="max_tokens")
CUT_EMPTY = _succeeded(text="", stop="max_tokens")


def _plan(plan: dict):
    """``batch_result``: ``plan[custom_id]`` is that read's shape per attempt
    (1-based; the last repeats; ``None`` is the ordinary reply)."""
    seen: collections.Counter = collections.Counter()

    def batch_result(custom_id: str, params: dict):
        seq = plan.get(custom_id)
        if not seq:
            return None
        shape = seq[min(seen[custom_id], len(seq) - 1)]
        seen[custom_id] += 1
        return None if shape is None else shape(params)

    return batch_result


def _collect(stub, monkeypatch, *, model: str = OPUS_55, n: int = 2, runs: int = 2,
             cache=None, max_elapsed: float = 100_000):
    """Submit ``n`` sheets' critique on ``model`` and collect it."""
    clock = _Clock()
    monkeypatch.setattr(BD.time, "monotonic", clock.monotonic)
    client = stub.client()
    batch = BC.submit_critique_batch([_make_sheet(i) for i in range(n)], client=client,
                                     runs=runs, total=n, model=model, cache=cache,
                                     sleep=clock.sleep)
    return BC.collect_critique_batch(batch, client=client, cache=cache, sleep=clock.sleep,
                                     max_elapsed_seconds=max_elapsed)


def _items(stub, custom_id: str) -> list[dict]:
    """Every batch item submitted as ``custom_id``, in submit order."""
    return [item["params"] for r in stub.requests
            if r["path"] == "/v1/messages/batches" and r["method"] == "POST"
            for item in r["body"]["requests"] if item["custom_id"] == custom_id]


def _submits(stub) -> list[list[str]]:
    """The custom ids of each batch submit, in submit order."""
    return [[item["custom_id"] for item in r["body"]["requests"]] for r in stub.requests
            if r["path"] == "/v1/messages/batches" and r["method"] == "POST"]


def _first(results):
    [(_ref, first), *_rest] = results
    return first


def _batch_id(stub, ordinal: int) -> str:
    """The id of the ``ordinal``-th batch ``stub`` (a ``_StallingStub``) created."""
    return next(bid for bid, n in stub._ordinal.items() if n == ordinal)


# --------------------------------------------------------------------------- #
# Which failed reads are retried (the digest's one predicate)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model", (OPUS_55, SONNET_55, OPUS_5), ids=["opus55", "sonnet55", "opus5"])
@pytest.mark.parametrize("error_type", TRANSIENT, ids=list(TRANSIENT))
def test_a_transient_errored_read_is_resubmitted_and_recovered(monkeypatch, error_type, model):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_errored(error_type), None]}))

    res = _first(_collect(stub, monkeypatch, model=model))

    assert (res.completed_runs, res.requested_runs) == (2, 2)
    assert res.error is None and res.read_errors == []
    assert _submits(stub) == [
        ["sheet__0__r1", "sheet__0__r2", "sheet__1__r1", "sheet__1__r2"],
        ["sheet__0__r1"],                                     # the read alone, as it was
    ]
    first, retry = _items(stub, "sheet__0__r1")
    assert retry == first
    assert [m["path"] for m in stub.messages()] == []         # never full-rate real time
    # The recovered read is merged as any read: both found it.
    assert res.findings[0].confidence == CONFIDENCE_REPRODUCED
    assert sorted(res.findings[0].sources) == ["critique_1", "critique_2"]


def test_an_expired_read_is_resubmitted_and_recovered(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r2": [EXPIRED, None]}))

    res = _first(_collect(stub, monkeypatch))

    assert res.completed_runs == 2 and res.read_errors == []
    assert _submits(stub)[1] == ["sheet__0__r2"]


@pytest.mark.parametrize("error_type", PERMANENT, ids=list(PERMANENT))
def test_a_permanent_errored_read_is_not_resubmitted(monkeypatch, error_type):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_errored(error_type)]}))

    res = _first(_collect(stub, monkeypatch))

    assert res.completed_runs == 1
    assert res.read_errors == [f"{error_type}: the detail"]
    assert len(_submits(stub)) == 1


def test_a_canceled_read_is_not_resubmitted(monkeypatch):
    # As the digest's primary collect: a canceled item is named, not resubmitted.
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [CANCELED]}))

    res = _first(_collect(stub, monkeypatch))

    assert res.read_errors == ["batch item canceled"]
    assert len(_submits(stub)) == 1


_NOT_RETRIED = {
    "ctxwin": (_succeeded(stop="model_context_window_exceeded"),
               "truncated critique (stop_reason='model_context_window_exceeded')"),
    "none": (_succeeded(stop=None), "unfinished critique (stop_reason=None)"),
    "pause": (_succeeded(stop="pause_turn"), "unfinished critique (stop_reason='pause_turn')"),
    "tool": (_succeeded(stop="tool_use"), "unfinished critique (stop_reason='tool_use')"),
    "unknown": (_succeeded(stop="not_a_stop_reason"),
                "unfinished critique (stop_reason='not_a_stop_reason')"),
    "malformed": (_succeeded(text="no findings object here"),
                  "critique produced no valid findings schema (ABSENT)"),
    "refused-null": (_refused(None), "refused critique (stop_reason='refusal')"),
    "refused-no-details": (_succeeded(text="", stop="refusal"),
                           "refused critique (stop_reason='refusal')"),
}


@pytest.mark.parametrize("key", list(_NOT_RETRIED), ids=list(_NOT_RETRIED))
def test_a_read_no_retry_can_finish_is_not_resubmitted(monkeypatch, key):
    shape, error = _NOT_RETRIED[key]
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [shape]}))

    res = _first(_collect(stub, monkeypatch))

    assert res.completed_runs == 1
    assert res.read_errors == [error]
    assert len(_submits(stub)) == 1


# --------------------------------------------------------------------------- #
# A refusal: the registry's route, once
# --------------------------------------------------------------------------- #


def test_a_routed_refusal_is_resubmitted_on_its_fallback_and_recovered(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_refused("cyber"), None]}))

    res = _first(_collect(stub, monkeypatch, model=OPUS_5))

    assert res.completed_runs == 2 and res.read_errors == []
    first, retry = _items(stub, "sheet__0__r1")
    assert first["model"] == OPUS_5
    assert retry == D.retarget_digest_request(first, OPUS_48)    # the builder's rules
    assert retry["model"] == OPUS_48 and retry["max_tokens"] == 64_000
    assert [m for m in stub.messages()] == []
    assert_request_contract(stub)


def test_a_refusal_hint_names_the_target_when_it_is_registered(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan(
        {"sheet__0__r1": [_refused("cyber", recommended_model=SONNET_5), None]}))

    res = _first(_collect(stub, monkeypatch, model=OPUS_5))

    assert res.completed_runs == 2
    assert _items(stub, "sheet__0__r1")[1]["model"] == SONNET_5


def test_a_fallback_that_refuses_too_is_not_retried_again(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_refused("cyber")]}))

    res = _first(_collect(stub, monkeypatch, model=OPUS_5))

    assert [p["model"] for p in _items(stub, "sheet__0__r1")] == [OPUS_5, OPUS_48]
    assert res.completed_runs == 1
    assert res.read_errors == [
        "refused critique (stop_reason='refusal', category='cyber'); retry on "
        "claude-opus-4-8: refused critique on claude-opus-4-8 (stop_reason='refusal', "
        "category='cyber')"
    ]


@pytest.mark.parametrize("model", MODELS_55, ids=["opus55", "sonnet55"])
def test_a_refusal_on_a_55_model_is_not_retried_and_says_so(monkeypatch, model):
    # The 5.5 defaults declare no route (the owner's open WP-01.5 question).
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_refused("cyber")]}))

    res = _first(_collect(stub, monkeypatch, model=model))

    assert len(_submits(stub)) == 1
    assert res.read_errors == [
        "refused critique (stop_reason='refusal', category='cyber'); not retried: "
        f"no fallback for category 'cyber' on {model}"
    ]


def test_an_unrouted_category_on_opus_5_is_not_retried_and_says_so(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_refused("bio")]}))

    res = _first(_collect(stub, monkeypatch, model=OPUS_5))

    assert len(_submits(stub)) == 1
    assert res.read_errors == [
        "refused critique (stop_reason='refusal', category='bio'); not retried: "
        "no fallback for category 'bio' on claude-opus-5"
    ]


# --------------------------------------------------------------------------- #
# A read cut off at max_tokens: twice the cap, once
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model", (OPUS_55, SONNET_55, OPUS_5), ids=["opus55", "sonnet55", "opus5"])
@pytest.mark.parametrize("shape", [CUT, CUT_EMPTY], ids=["with-text", "empty"])
def test_a_cut_read_is_resubmitted_at_a_raised_cap_and_recovered(monkeypatch, model, shape):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [shape, None]}))

    res = _first(_collect(stub, monkeypatch, model=model))

    assert res.completed_runs == 2 and res.read_errors == []
    first, retry = _items(stub, "sheet__0__r1")
    assert first["max_tokens"] == 64_000
    assert retry == {**first, "max_tokens": D.MAX_TOKENS_RETRY_CEILING}
    assert_request_contract(stub)


def test_a_read_cut_again_at_the_raised_cap_is_not_retried_again(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [CUT]}))

    res = _first(_collect(stub, monkeypatch))

    assert [p["max_tokens"] for p in _items(stub, "sheet__0__r1")] == [64_000, 128_000]
    assert res.read_errors == [
        "truncated critique (stop_reason='max_tokens'); retry: truncated critique "
        "(stop_reason='max_tokens')"
    ]


def test_an_expired_then_cut_read_raises_its_cap_on_the_next_round(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [EXPIRED, CUT, None]}))

    res = _first(_collect(stub, monkeypatch))

    assert [p["max_tokens"] for p in _items(stub, "sheet__0__r1")] == [64_000, 64_000, 128_000]
    assert res.completed_runs == 2 and res.read_errors == []


# --------------------------------------------------------------------------- #
# The per-sheet budget (WP-01.5's)
# --------------------------------------------------------------------------- #


def test_one_read_failing_every_time_spends_the_sheets_budget(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_errored("overloaded_error")]}))

    res = _first(_collect(stub, monkeypatch))

    assert len(_items(stub, "sheet__0__r1")) == 1 + 4
    assert res.completed_runs == 1
    assert res.read_errors == [
        "overloaded_error: the detail; 4 retries, the last: overloaded_error: the detail"
    ]
    assert res.findings[0].confidence == CONFIDENCE_NOT_ASSESSED_PARTIAL


def test_two_reads_failing_every_time_share_one_budget(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({
        "sheet__0__r1": [_errored("overloaded_error")],
        "sheet__0__r2": [EXPIRED],
    }))

    res = _first(_collect(stub, monkeypatch))

    # 2 + 4 items for the sheet, not 2 + 8: every resubmitted read counts one.
    assert _submits(stub)[1:] == [["sheet__0__r1", "sheet__0__r2"]] * 2
    assert res.completed_runs == 0
    assert res.read_errors == [
        "overloaded_error: the detail; 2 retries, the last: overloaded_error: the detail",
        "batch item expired; 2 retries, the last: batch item expired",
    ]


def test_the_budget_is_counted_read_by_read_within_a_round(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "3")
    stub = AnthropicAPIStub(_ok, batch_result=_plan({
        "sheet__0__r1": [_errored("api_error")],
        "sheet__0__r2": [_errored("api_error")],
    }))

    _collect(stub, monkeypatch)

    assert _submits(stub)[1:] == [["sheet__0__r1", "sheet__0__r2"], ["sheet__0__r1"]]


@pytest.mark.parametrize("rounds", ["1", "6"], ids=["one", "six"])
def test_the_budget_follows_the_digests_knob(monkeypatch, rounds):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", rounds)
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [EXPIRED]}))

    _collect(stub, monkeypatch)

    assert len(_items(stub, "sheet__0__r1")) == 1 + int(rounds)


def test_each_sheet_has_its_own_budget(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({
        "sheet__0__r1": [EXPIRED], "sheet__1__r2": [EXPIRED],
    }))

    results = _collect(stub, monkeypatch)

    assert len(_items(stub, "sheet__0__r1")) == 5 and len(_items(stub, "sheet__1__r2")) == 5
    assert [res.completed_runs for _ref, res in results] == [1, 1]


# --------------------------------------------------------------------------- #
# Which read is kept, and how its error reads
# --------------------------------------------------------------------------- #


def test_a_retry_that_fails_differently_is_named(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan(
        {"sheet__0__r1": [_errored("overloaded_error"), _errored("invalid_request_error")]}))

    res = _first(_collect(stub, monkeypatch))

    assert len(_items(stub, "sheet__0__r1")) == 2            # a permanent error ends it
    assert res.read_errors == [
        "overloaded_error: the detail; retry: invalid_request_error: the detail"
    ]


def test_a_recovered_read_carries_every_attempts_tokens(monkeypatch):
    # The cut read billed 100 in / 50 out; the raised-cap retry the same.
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [CUT, None]}))

    res = _first(_collect(stub, monkeypatch))

    assert res.completed_runs == 2
    assert (res.input_tokens, res.output_tokens) == (300, 150)   # 2 attempts + read 2


def test_an_errored_attempt_carries_no_tokens(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [EXPIRED, None]}))

    res = _first(_collect(stub, monkeypatch))

    assert (res.input_tokens, res.output_tokens) == (200, 100)


# --------------------------------------------------------------------------- #
# A follow-up batch that never ends, or that cannot be submitted
# --------------------------------------------------------------------------- #


def test_a_follow_up_batch_that_never_ends_is_canceled_and_stops_the_recovery(monkeypatch):
    stub = _StallingStub(_ok, stall=(2,), batch_result=_plan({"sheet__0__r1": [EXPIRED, None]}))

    res = _first(_collect(stub, monkeypatch, max_elapsed=3_600))

    second = _batch_id(stub, 2)
    assert len(_submits(stub)) == 2                            # no third batch
    assert any(r["path"] == f"/v1/messages/batches/{second}/cancel" for r in stub.requests)
    assert res.completed_runs == 1
    assert res.read_errors == [
        "batch item expired; retry: critique batch not collected (detached); remote "
        f"batch id={second} was canceled"
    ]
    # Every batch that references the files is canceled or ended: released.
    uploads = [r for r in stub.requests if r["path"] == "/v1/files" and r["method"] == "POST"]
    deletes = [r for r in stub.requests if r["method"] == "DELETE"]
    assert len(deletes) == len(uploads) > 0


class _NoCancelStub(_StallingStub):
    def _answer(self, request, record, raw):
        if record["path"].endswith("/cancel"):
            return httpx2.Response(500, json={"type": "error", "error": {
                "type": "api_error", "message": "cancel failed"}})
        return super()._answer(request, record, raw)


def test_a_follow_up_batch_that_cannot_be_canceled_keeps_the_files(monkeypatch):
    stub = _NoCancelStub(_ok, stall=(2,), batch_result=_plan({"sheet__0__r1": [EXPIRED]}))

    res = _first(_collect(stub, monkeypatch, max_elapsed=3_600))

    assert res.read_errors == [
        "batch item expired; retry: critique batch not collected (detached); remote "
        f"batch id={_batch_id(stub, 2)} may still be running"
    ]
    assert [r for r in stub.requests if r["method"] == "DELETE"] == []


class _PollFailsStub(_StallingStub):
    """The second batch's retrieve answers 500 every time."""

    def _answer(self, request, record, raw):
        path = record["path"]
        if record["method"] == "GET" and path.startswith("/v1/messages/batches/"):
            batch_id = path[len("/v1/messages/batches/"):]
            if self._ordinal.get(batch_id) == 2:
                return httpx2.Response(500, json={"type": "error", "error": {
                    "type": "api_error", "message": "retrieve failed"}})
        return super()._answer(request, record, raw)


def test_a_follow_up_batch_that_cannot_be_polled_is_named(monkeypatch):
    stub = _PollFailsStub(_ok, batch_result=_plan({"sheet__0__r1": [EXPIRED, None]}))

    res = _first(_collect(stub, monkeypatch))

    assert len(_submits(stub)) == 2
    assert res.read_errors == [
        "batch item expired; retry: critique batch not collected (poll_failed); remote "
        f"batch id={_batch_id(stub, 2)} was canceled"
    ]


class _RejectSecondSubmitStub(AnthropicAPIStub):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.submits = 0

    def _answer(self, request, record, raw):
        if record["path"] == "/v1/messages/batches" and record["method"] == "POST":
            self.submits += 1
            if self.submits == 2:
                return httpx2.Response(500, json={"type": "error", "error": {
                    "type": "api_error", "message": "submit failed"}})
        return super()._answer(request, record, raw)


def test_a_rejected_follow_up_submit_spends_no_retry(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "2")
    stub = _RejectSecondSubmitStub(_ok, batch_result=_plan({"sheet__0__r1": [EXPIRED, None]}))

    res = _first(_collect(stub, monkeypatch))

    assert stub.submits == 3                                  # primary, rejected, accepted
    assert res.completed_runs == 2 and res.read_errors == []


def test_follow_up_batches_reuse_the_uploads_and_release_them_once(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [EXPIRED, EXPIRED, None]}))

    _collect(stub, monkeypatch)

    uploads = [r for r in stub.requests if r["path"] == "/v1/files" and r["method"] == "POST"]
    deletes = sorted(r["path"] for r in stub.requests if r["method"] == "DELETE")
    assert len(deletes) == len(set(deletes)) == len(uploads)
    first, *retries = _items(stub, "sheet__0__r1")
    assert all(retry["messages"] == first["messages"] for retry in retries)


# --------------------------------------------------------------------------- #
# The cache: a recovered result is stored under the requested key
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model, shape", [
    (OPUS_55, _errored("overloaded_error")),
    (OPUS_55, CUT),
    (OPUS_5, _refused("cyber")),
], ids=["transient", "raised-cap", "fallback"])
def test_a_recovered_result_is_cached_under_the_requested_key(monkeypatch, tmp_path, model, shape):
    cache = DigestCache(tmp_path / "cache.sqlite")
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [shape, None]}))
    _collect(stub, monkeypatch, model=model, cache=cache)

    warm = AnthropicAPIStub(_ok)
    results = _collect(warm, monkeypatch, model=model, cache=cache)

    assert _submits(warm) == []                               # both sheets served free
    assert all(res.cached for _ref, res in results)


def test_a_still_failed_read_is_not_cached(monkeypatch, tmp_path):
    cache = DigestCache(tmp_path / "cache.sqlite")
    stub = AnthropicAPIStub(_ok, batch_result=_plan({"sheet__0__r1": [_errored("api_error")]}))
    _collect(stub, monkeypatch, cache=cache)

    warm = AnthropicAPIStub(_ok)
    _collect(warm, monkeypatch, cache=cache)

    assert _submits(warm) == [["sheet__0__r1", "sheet__0__r2"]]   # only M-100 again


# --------------------------------------------------------------------------- #
# Real time: one raised-cap retry per read
# --------------------------------------------------------------------------- #


def _script(*shapes):
    """A route answering the k-th real-time request with ``shapes[k]`` (the
    last repeats; ``None`` is the ordinary reply)."""
    seen = {"n": 0}

    def route(params):
        shape = shapes[min(seen["n"], len(shapes) - 1)]
        seen["n"] += 1
        return _ok(params) if shape is None else shape(params)

    return route


_RT_CUT = lambda p: _reply(p, stop="max_tokens")  # noqa: E731
_RT_CUT_EMPTY = lambda p: _reply(p, text="", stop="max_tokens")  # noqa: E731


def _read(stub, *, model: str = OPUS_55, max_tokens: int = C.DEFAULT_CRITIQUE_MAX_TOKENS,
          max_retries: int = 0):
    return C._critique_read(_make_sheet(0), run_id="critique_1", client=stub.client(),
                            model=model, max_tokens=max_tokens, max_retries=max_retries,
                            sleep=_NOOP)


@pytest.mark.parametrize("model", (OPUS_55, SONNET_55, OPUS_5), ids=["opus55", "sonnet55", "opus5"])
@pytest.mark.parametrize("cut", [_RT_CUT, _RT_CUT_EMPTY], ids=["with-text", "empty"])
def test_a_real_time_read_cut_off_is_retried_once_at_a_raised_cap(model, cut):
    stub = AnthropicAPIStub(_script(cut, None))

    oc = _read(stub, model=model)

    assert oc.status == "COMPLETE" and oc.error is None
    first, retry = [m["body"] for m in stub.messages()]
    assert (first["max_tokens"], retry["max_tokens"]) == (64_000, 128_000)
    assert retry["stream"] is True                            # above 21,333: streamed
    assert {k: v for k, v in retry.items() if k != "max_tokens"} == {
        k: v for k, v in first.items() if k != "max_tokens"}
    assert (oc.input_tokens, oc.output_tokens) == (200, 100)  # both attempts billed
    assert oc.findings and oc.findings[0].sources == ["critique_1"]


def test_a_real_time_read_cut_again_is_failed_and_names_its_retry():
    stub = AnthropicAPIStub(_script(_RT_CUT))

    oc = _read(stub)

    assert len(stub.messages()) == 2
    assert oc.status == "FAILED" and oc.findings == []
    assert oc.error == (
        "truncated critique (stop_reason='max_tokens'); retry: truncated critique "
        "(stop_reason='max_tokens')")
    assert (oc.input_tokens, oc.output_tokens) == (200, 100)


def test_a_real_time_retry_that_raises_is_named_as_failed():
    calls = {"n": 0}

    def reject(record):
        if record["path"] != "/v1/messages":
            return None
        calls["n"] += 1
        return error_400("bad request here") if calls["n"] == 2 else None

    stub = AnthropicAPIStub(_script(_RT_CUT), reject=reject)

    oc = _read(stub)

    assert oc.status == "FAILED"
    assert oc.error.startswith(
        "truncated critique (stop_reason='max_tokens'); retry failed: HTTP 400: ")
    assert (oc.input_tokens, oc.output_tokens) == (100, 50)


_RT_NOT_RETRIED = {
    "ctxwin": lambda p: _reply(p, stop="model_context_window_exceeded"),
    "none": lambda p: _reply(p, stop=None),
    "refusal": lambda p: _reply(p, text="", stop="refusal",
                                stop_details=R.refusal_stop_details("cyber")),
    "pause": lambda p: _reply(p, stop="pause_turn"),
    "malformed": lambda p: _reply(p, text="prose, no findings object"),
}


@pytest.mark.parametrize("key", list(_RT_NOT_RETRIED), ids=list(_RT_NOT_RETRIED))
def test_a_real_time_read_no_raised_cap_can_finish_is_not_retried(key):
    stub = AnthropicAPIStub(_script(_RT_NOT_RETRIED[key], None))

    oc = _read(stub)

    assert len(stub.messages()) == 1 and oc.status == "FAILED"


@pytest.mark.parametrize("model, cap", [(OPUS_55, 128_000), ("claude-unregistered-9", 64_000)],
                         ids=["at-the-ceiling", "unregistered-model-cap"])
def test_a_real_time_read_with_no_headroom_is_not_retried(model, cap):
    stub = AnthropicAPIStub(_script(_RT_CUT, None))

    oc = _read(stub, model=model, max_tokens=cap)

    assert len(stub.messages()) == 1
    assert oc.error == "truncated critique (stop_reason='max_tokens')"


def test_a_real_time_retry_interrupted_mid_stream_is_named_with_its_cause():
    calls = {"n": 0}

    def stream(record):
        calls["n"] += 1
        return ("after_text", "drop") if calls["n"] == 2 else None

    stub = AnthropicAPIStub(_script(_RT_CUT, None), stream=stream)

    oc = _read(stub)

    assert len(stub.messages()) == 2 and oc.status == "FAILED"
    assert oc.error == (
        "truncated critique (stop_reason='max_tokens'); retry: unfinished critique "
        "(stop_reason=None, interrupted='connection dropped')")
    assert oc.interrupted_attempts == 1


def test_both_real_time_reads_recovered_merge_and_cache(tmp_path):
    cache = DigestCache(tmp_path / "cache.sqlite")
    stub = AnthropicAPIStub(_script(_RT_CUT, None, _RT_CUT, None))

    res = C.critique_sheet_self_consistent(_make_sheet(0), client=stub.client(), runs=2,
                                           cache=cache, sleep=_NOOP)

    assert len(stub.messages()) == 4
    assert (res.completed_runs, res.error, res.read_errors) == (2, None, [])
    assert res.findings[0].confidence == CONFIDENCE_REPRODUCED
    warm = AnthropicAPIStub(_ok)
    again = C.critique_sheet_self_consistent(_make_sheet(0), client=warm.client(), runs=2,
                                             cache=cache, sleep=_NOOP)
    assert again.cached and warm.messages() == []


def test_the_raised_cap_retry_keeps_the_structured_contract(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    body = json.dumps({"findings": [FINDING]})
    stub = AnthropicAPIStub(_script(lambda p: _reply(p, text=body, stop="max_tokens"),
                                    lambda p: _reply(p, text=body)))

    oc = C._critique_read(_make_sheet(0), run_id="critique_1", client=stub.client(),
                          model=OPUS_5, max_retries=0, sleep=_NOOP)

    first, retry = [m["body"] for m in stub.messages()]
    assert "format" in first["output_config"] and retry["output_config"] == first["output_config"]
    assert retry["max_tokens"] == 128_000 and oc.status == "COMPLETE"


class _NoUploadStub(AnthropicAPIStub):
    def _answer(self, request, record, raw):
        if record["path"] == "/v1/files" and record["method"] == "POST":
            return httpx2.Response(400, json={"type": "error", "error": {
                "type": "invalid_request_error", "message": "upload refused"}})
        return super()._answer(request, record, raw)


def test_the_upload_failure_fallback_gets_the_raised_cap_too(monkeypatch):
    stub = _NoUploadStub(_script(_RT_CUT, None))

    res = _first(_collect(stub, monkeypatch, n=1))

    assert res.rescued and res.completed_runs == 2
    assert [m["body"]["max_tokens"] for m in stub.messages()] == [64_000, 128_000, 64_000]


# --------------------------------------------------------------------------- #
# Through the pipeline: the stage, the tally, the usage record, the warm run
# --------------------------------------------------------------------------- #


pytest.importorskip("pymupdf")

import drawing_analyzer.pipeline as pl  # noqa: E402
from tests.fixtures.gauntlet import build_mini_set  # noqa: E402
from tests.fixtures.sdk_transport import message_json  # noqa: E402
from tests.test_sdk_contract import _TRANSPORTS, stage_of  # noqa: E402
from tests.test_sdk_contract import _script as _mini_script  # noqa: E402

M101 = "VAV-3"


def _about_m101(params: dict) -> bool:
    return M101 in json.dumps(params.get("messages", []))


def _m101_critique(shapes):
    """``batch_result``: M-101's first critique read (``r1``) per attempt."""
    seen = {"n": 0}

    def batch_result(custom_id, params):
        if stage_of(params) != "critique" or not _about_m101(params) or not custom_id.endswith("__r1"):
            return None
        shape = shapes[min(seen["n"], len(shapes) - 1)]
        seen["n"] += 1
        return None if shape is None else shape(params)

    return batch_result


def _run(tmp_path: Path, stub, transport: str, *, work: str = "work"):
    use_batch, critique_batch = _TRANSPORTS[transport]
    work_dir = tmp_path / work
    work_dir.mkdir()
    return pl.extract_drawing_context(
        build_mini_set(tmp_path), client=stub.client(), rows=2, cols=2,
        cache=DigestCache(tmp_path / "cache.sqlite"), use_batch=use_batch,
        critique_use_batch=critique_batch, qc_markups=True, qc_work_dir=work_dir,
    )


def _critique_calls(stub) -> int:
    n = sum(1 for r in stub.messages() if stage_of(r["body"]) == "critique")
    for r in stub.requests:
        if r["path"] == "/v1/messages/batches" and r["method"] == "POST":
            n += sum(1 for item in r["body"]["requests"] if stage_of(item["params"]) == "critique")
    return n


def _stage(ctx):
    return next(s for s in ctx.stage_results if s.stage == "critique")


def _m101_record(ctx):
    [rec] = [r for r in ctx.run_usage.records
             if r.stage_family == "critique" and r.stage_instance == "critique:SRC-0001:p0"]
    return rec


def _as_mini(shape):
    """A shape over the mini script's own critique reply."""
    script = _mini_script()

    def wrapped(params):
        body = message_json(script._route(params), model=params.get("model", ""))
        return shape(body)

    return wrapped


def _mini_cut(body):
    body["stop_reason"] = "max_tokens"
    return R.succeeded(body)


@pytest.mark.parametrize("transport", ["hybrid", "economy"], ids=["hybrid", "economy"])
@pytest.mark.parametrize("shape", [
    lambda params: R.errored("overloaded_error", "busy"),
    lambda params: R.EXPIRED,
    _as_mini(_mini_cut),
], ids=["overloaded", "expired", "max_tokens"])
def test_a_recovered_batch_read_completes_the_stage_and_is_cached(tmp_path, transport, shape):
    stub = AnthropicAPIStub(_mini_script()._route, batch_result=_m101_critique([shape, None]))

    ctx = _run(tmp_path, stub, transport)

    stage = _stage(ctx)
    assert stage.status == "COMPLETE", (stage.errors, stage.warnings)
    assert (stage.items_in, stage.items_out) == (4, 4)
    assert stage.errors == [] and stage.warnings == []
    assert not [e for e in ctx.errors if e.startswith("Critique")]
    rec = _m101_record(ctx)
    assert (rec.transport, rec.terminal_status, rec.parse_success) == ("BATCH", "COMPLETE", True)
    assert _critique_calls(stub) == 5                         # 4 reads + the one retry
    warm = AnthropicAPIStub(_mini_script()._route)
    _run(tmp_path, warm, transport, work="warm")
    assert _critique_calls(warm) == 0


def test_a_batch_read_that_stays_failed_is_named_in_the_stage(tmp_path):
    stub = AnthropicAPIStub(_mini_script()._route,
                            batch_result=_m101_critique([lambda p: R.errored("overloaded_error", "busy")]))

    ctx = _run(tmp_path, stub, "hybrid")

    stage = _stage(ctx)
    assert stage.status == "PARTIAL" and (stage.items_in, stage.items_out) == (4, 3)
    assert stage.warnings[0] == (
        "critique: 3 of 4 requested read(s) judged; 0 skipped, 1 returned no judgment")
    # M-101's surviving read found nothing, so the sheet's own error is the
    # failed read's (``critique_shortfall``), which names every retry.
    assert stage.errors[0].endswith(
        ": overloaded_error: busy; 4 retries, the last: overloaded_error: busy")
    assert _m101_record(ctx).terminal_status == "PARTIAL"
    assert _critique_calls(stub) == 4 + 4


def test_a_real_time_read_cut_off_is_recovered_through_the_pipeline(tmp_path):
    once = {"done": False}
    script = _mini_script()

    def route(params):
        body = message_json(script._route(params), model=params.get("model", ""))
        if stage_of(params) == "critique" and _about_m101(params) and not once["done"]:
            once["done"] = True
            body["stop_reason"] = "max_tokens"
        return body

    stub = AnthropicAPIStub(route)

    ctx = _run(tmp_path, stub, "fast")

    stage = _stage(ctx)
    assert stage.status == "COMPLETE" and (stage.items_in, stage.items_out) == (4, 4)
    rec = _m101_record(ctx)
    assert (rec.transport, rec.terminal_status) == ("REAL_TIME", "COMPLETE")
    caps = [r["body"]["max_tokens"] for r in stub.messages()
            if stage_of(r["body"]) == "critique" and _about_m101(r["body"])]
    assert sorted(caps) == [64_000, 64_000, 128_000]
    warm = AnthropicAPIStub(_mini_script()._route)
    _run(tmp_path, warm, "fast", work="warm")
    assert _critique_calls(warm) == 0
