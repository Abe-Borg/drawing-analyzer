"""A refused batch item is recovered under the selected transport, inside one
per-sheet retry budget (remediation WP-01.5, R2; the owner's rules).

Before WP-01.5 a batch digest the model refused was failed and never retried
at the primary collect, the fresh-batch rounds, the follow-up batch or the
direct rescue, and the abandoned-batch harvest resubmitted it on the same
model; nothing read ``stop_details`` (measured on SDK 1.7.0 and 1.8.0). The
owner's rules, recorded in ``_plans/DECISIONS.md`` (D-1's WP-01.5 note):

* **The gate is a registry route per category.**
  ``ModelCapabilities.refusal_fallback_routes`` declares, per refusing model,
  which ``stop_details.category`` has a fallback and to which model. Opus 5
  declares ``cyber`` -> Opus 4.8; everything else is not retried. The 5.5
  defaults declare no route yet, so a batch item refused on one fails with its
  category named.
* **The target** is ``stop_details.recommended_model`` when it names a
  registered model other than the one that refused, else the route's target.
  The request is rebuilt for it (``digest.retarget_digest_request``).
* **One per-sheet retry budget** (``DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS``,
  default 4) counts every resubmission of a sheet, at every site. A refusal is
  retried at most once: the fallback refusing too ends it.
* **The harvest** asks the same predicate: a refusal it read gets its
  fallback item (or is final), a permanent error is not resubmitted.
* **The selected transport:** under ``RECOVERY_BATCH`` (the pipeline) a
  refused sheet is only ever retried as a batch item; under
  ``RECOVERY_DIRECT`` it takes the path any retryable item takes.
* **The cache:** a finished fallback read is admitted under the requested
  model's key, as the server-side fallback's is.
* **Logged:** the category in the sheet's error, and category,
  ``recommended_model``, target and explanation (redacted, one line, capped)
  in the diagnostics log.

Every test drives the real SDK over ``tests/fixtures/sdk_transport.py``.
"""
from __future__ import annotations

import logging
import typing

import httpx2
import pytest

import drawing_analyzer.batch_critique as BC
import drawing_analyzer.batch_digest as BD
import drawing_analyzer.core.api_config as api
import drawing_analyzer.digest as D
from drawing_analyzer import diagnostics
from drawing_analyzer.digest_cache import DigestCache
from tests.fixtures import sdk_responses as R
from tests.fixtures.sdk_transport import AnthropicAPIStub
from tests.test_drawing_batch import _make_sheet
# The contract tests' autouse fixture: every self-healing latch starts on, one
# upload worker, the upload release run inline.
from tests.test_sdk_contract import _fresh_latches, assert_request_contract  # noqa: F401

OPUS = "claude-opus-5"
OPUS_48 = "claude-opus-4-8"
SONNET = "claude-sonnet-5"
OPUS_55 = "claude-opus-5-5"
SONNET_55 = "claude-sonnet-5-5"
PROSE = "## M-10x\nA digest body.\n\n```json\n{\"findings\": []}\n```"
CATEGORIES = ("cyber", "bio", "frontier_llm", "reasoning_extraction", "general_harms")
UNROUTED = tuple(c for c in CATEGORIES if c != "cyber")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Clock:
    """A monotonic clock the fake ``sleep`` advances, so a stall watch fires."""

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += float(seconds)


class _StallingStub(AnthropicAPIStub):
    """The stub, with the batches named in ``stall`` (1-based submit order)
    reading ``in_progress`` until canceled, then ``ended``."""

    def __init__(self, route, *, stall=(), **kwargs):
        super().__init__(route, **kwargs)
        self.stall = set(stall)
        self._ordinal: dict[str, int] = {}

    def _answer(self, request, record, raw):
        path, method = record["path"], record["method"]
        if path == "/v1/messages/batches" and method == "POST":
            response = super()._answer(request, record, raw)
            self._ordinal[response.json()["id"]] = len(self._ordinal) + 1
            return response
        if path.startswith("/v1/messages/batches/") and method == "GET":
            batch_id, _, tail = path[len("/v1/messages/batches/"):].partition("/")
            if (not tail and self._ordinal.get(batch_id) in self.stall
                    and batch_id not in self._canceled):
                return httpx2.Response(200, json=self._batch(batch_id, "in_progress"))
        return super()._answer(request, record, raw)


def _ok(params: dict) -> dict:
    return R.message([R.text(PROSE)], model=params.get("model", OPUS))


def _refused(params: dict, category: str | None = "cyber", *, details: bool = True,
             recommended: str | None = None, explanation: str | None = "declined") -> dict:
    stop_details = (R.refusal_stop_details(category, explanation=explanation,
                                           recommended_model=recommended)
                    if details else None)
    return R.message([], model=params.get("model", OPUS), stop_reason="refusal",
                     stop_details=stop_details)


def _refusal_envelope(params: dict, category: str | None = "cyber", **kwargs) -> dict:
    return R.succeeded(_refused(params, category, **kwargs))


def _sheet0(per_attempt):
    """``batch_result``: sheet 0's k-th batch item (1-based) is answered with
    ``per_attempt(k, params)`` (``None``: the ordinary reply). Others succeed."""
    seen = {"n": 0}

    def batch_result(custom_id: str, params: dict):
        if custom_id != "sheet__0":
            return None
        seen["n"] += 1
        return per_attempt(seen["n"], params)

    return batch_result


def _collect(stub, monkeypatch, *, transport, n: int = 2, cache=None, model: str = OPUS):
    """Submit ``n`` sheets on ``model`` and collect them with recovery on."""
    clock = _Clock()
    monkeypatch.setattr(BD.time, "monotonic", clock.monotonic)
    client = stub.client()
    batch = BD.submit_drawing_batch([_make_sheet(i) for i in range(n)], client=client,
                                    model=model, cache=cache, total=n)
    return BD.collect_drawing_batch(batch, client=client, cache=cache, sleep=clock.sleep,
                                    retry_failed_items=True, recovery_transport=transport,
                                    max_elapsed_seconds=100_000)


def _items(stub, custom_id: str = "sheet__0") -> list[dict]:
    """Every batch item submitted for ``custom_id``, in submit order."""
    return [item["params"] for r in stub.requests
            if r["path"] == "/v1/messages/batches" and r["method"] == "POST"
            for item in r["body"]["requests"] if item["custom_id"] == custom_id]


def _realtime(stub) -> list[dict]:
    return [r["body"] for r in stub.messages()]


_TRANSPORTS = [BD.RECOVERY_BATCH, BD.RECOVERY_DIRECT]


# --------------------------------------------------------------------------- #
# The registry: routes, targets, the retargeted request
# --------------------------------------------------------------------------- #


def test_opus_5_routes_cyber_refusals_to_opus_4_8_and_nothing_else():
    assert api.refusal_fallback_target(OPUS, "cyber") == OPUS_48
    for category in UNROUTED + (None, "", "a_future_category"):
        assert api.refusal_fallback_target(OPUS, category) is None, category
    for model in (OPUS_55, SONNET_55, SONNET, OPUS_48, "claude-sonnet-4-6", "claude-haiku-4-5",
                  "claude-unregistered-9"):
        for category in CATEGORIES:
            assert api.refusal_fallback_target(model, category) is None, (model, category)


def test_supports_refusal_fallback_is_unchanged():
    # The server-side opt-in and the host route are two capabilities: WP-01.5
    # moved neither the set that opts in (the 5.5 models joined it with the
    # move to the 5.5 defaults) nor any request that set sends.
    declaring = {m for m in api._MODEL_CAPABILITIES
                 if api.model_capabilities(m).supports_refusal_fallback}
    assert declaring == {OPUS_55, SONNET_55, OPUS}


def test_every_route_is_a_registered_model_that_takes_the_source_request():
    routes = {m: dict(api.model_capabilities(m).refusal_fallback_routes)
              for m in api._MODEL_CAPABILITIES}
    assert {m: r for m, r in routes.items() if r} == {OPUS: {"cyber": OPUS_48}}
    for source, table in routes.items():
        src = api.model_capabilities(source)
        for category, target in table.items():
            assert api.is_registered_model(target), target
            assert target != source
            dst = api.model_capabilities(target)
            assert dst.supports_adaptive_thinking or not src.supports_adaptive_thinking
            assert src.supported_effort_levels <= dst.supported_effort_levels
            assert dst.max_output_tokens >= src.max_output_tokens
            assert dst.supports_hires_vision == src.supports_hires_vision


def test_route_categories_are_the_sdks_refusal_categories():
    from anthropic.types import RefusalStopDetails

    literal = typing.get_args(typing.get_args(RefusalStopDetails.model_fields["category"].annotation)[0])
    assert set(literal) == set(CATEGORIES)          # the tripwire: an SDK that adds one fails here
    for model in api._MODEL_CAPABILITIES:
        for category, _target in api.model_capabilities(model).refusal_fallback_routes:
            assert category in literal, (model, category)


def test_is_registered_model():
    assert api.is_registered_model(OPUS) and api.is_registered_model(OPUS_48)
    assert not api.is_registered_model("claude-unregistered-9")
    assert not api.is_registered_model("")


@pytest.mark.parametrize("target", [OPUS_48, SONNET, "claude-sonnet-4-6", "claude-haiku-4-5"],
                         ids=["opus-4-8", "sonnet-5", "sonnet-4-6", "haiku-4-5"])
def test_a_retargeted_request_is_the_request_built_for_the_target(target):
    content = [{"type": "text", "text": "a sheet"}]
    built = D.build_digest_request_params(content, model=OPUS, max_tokens=64_000)
    expected = D.build_digest_request_params(content, model=target, max_tokens=64_000)
    expected["max_tokens"] = api.output_cap_for_model(target, requested=64_000)
    assert D.retarget_digest_request(built, target) == expected
    assert built["model"] == OPUS                    # the original is not mutated


# --------------------------------------------------------------------------- #
# Batch item error types
# --------------------------------------------------------------------------- #


def test_billing_error_is_permanent_and_request_too_large_is_kept():
    assert BD._PERMANENT_ITEM_ERROR_TYPES == {
        "invalid_request_error", "authentication_error", "permission_error",
        "not_found_error", "billing_error", "request_too_large",
    }
    # request_too_large is the API's 413 type, not one of the SDK's batch item
    # error types; it is kept as a permanent rejection (the owner's rule).
    assert "request_too_large" not in R.ERROR_TYPES
    assert BD._PERMANENT_ITEM_ERROR_TYPES - {"request_too_large"} <= set(R.ERROR_TYPES)


@pytest.mark.parametrize("transport", _TRANSPORTS, ids=["batch", "direct"])
def test_a_billing_error_is_not_resubmitted(monkeypatch, transport):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: R.errored("billing_error", "credit balance too low") if k == 1 else None))
    sd, other = _collect(stub, monkeypatch, transport=transport)
    assert sd.error == "billing_error: credit balance too low"
    assert len(_items(stub)) == 1 and not _realtime(stub)
    assert other.ok


# --------------------------------------------------------------------------- #
# The ladder names the category, and the diagnostics log carries the rest
# --------------------------------------------------------------------------- #


def test_a_refusal_names_its_category_in_the_error():
    assert (D.digest_terminal_error("", "refusal", category="cyber")
            == "refused digest (stop_reason='refusal', category='cyber')")
    assert (D.digest_terminal_error("text", "refusal", noun="critique", category="bio")
            == "refused critique (stop_reason='refusal', category='bio')")
    # No category: the wording is unchanged.
    assert D.digest_terminal_error("", "refusal") == "refused digest (stop_reason='refusal')"
    assert D.digest_terminal_error("", "refusal", category=None) == "refused digest (stop_reason='refusal')"
    # Not a refusal: the category is not consulted.
    assert D.digest_terminal_error("x", "end_turn", category="cyber") is None


def test_refusal_details_are_read_on_both_namespaces():
    import anthropic

    stub = AnthropicAPIStub(lambda p: _refused(p, "cyber", recommended=OPUS_48))
    client = stub.client()
    req = {"model": OPUS, "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}
    plain = client.messages.create(**req)
    beta = client.beta.messages.create(**req, betas=[api.REFUSAL_FALLBACK_BETA])
    for message in (plain, beta, plain.model_dump(), None):
        details = D.refusal_details(message)
        if message is None:
            assert details is None
            continue
        assert (details.category, details.explanation, details.recommended_model) == (
            "cyber", "declined", OPUS_48)
    assert D.refusal_details(R.message([R.text("ok")])) is None      # no stop_details
    assert isinstance(plain.stop_details, anthropic.types.RefusalStopDetails)


def test_the_refusal_log_line_is_redacted_single_line_and_capped():
    key = "sk-ant-" + "api03-" + "x" * 40                     # built at runtime: never a real key
    details = D.RefusalDetails(category="cyber", recommended_model=None,
                               explanation="line one\nline two " + key + " " + "y" * 500)
    line = D.describe_refusal(details)
    assert "\n" not in line and key not in line and "[REDACTED]" in line
    assert "category='cyber'" in line and "recommended_model=None" in line
    explanation = line.split("explanation=", 1)[1]
    assert len(explanation) <= D.REFUSAL_EXPLANATION_MAX_CHARS + 2      # the quotes


def test_a_refused_batch_item_logs_its_details_and_its_target(monkeypatch, caplog):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber", explanation="a classifier said no") if k == 1 else None))
    with caplog.at_level(logging.INFO, logger=diagnostics.LOGGER_NAME):
        _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    text = "\n".join(caplog.messages)
    assert "category='cyber'" in text and "a classifier said no" in text
    assert f"retrying on {OPUS_48}" in text


# --------------------------------------------------------------------------- #
# A routed refusal is resubmitted on the fallback model, on either transport
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("transport", _TRANSPORTS, ids=["batch", "direct"])
def test_a_cyber_refusal_is_resubmitted_on_the_fallback_model(monkeypatch, transport):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else None))
    sd, other = _collect(stub, monkeypatch, transport=transport)
    items = _items(stub)
    assert [p["model"] for p in items] == [OPUS, OPUS_48]
    retry = dict(items[1])
    assert retry.pop("model") == OPUS_48
    assert retry == {k: v for k, v in items[0].items() if k != "model"}   # only the model moved
    assert sd.ok and sd.error is None
    assert sd.fallback_model == OPUS_48
    assert not _realtime(stub)                                  # a batch item, never real time
    assert other.ok and [p["model"] for p in _items(stub, "sheet__1")] == [OPUS]
    assert_request_contract(stub)


@pytest.mark.parametrize("category", UNROUTED, ids=list(UNROUTED))
def test_an_unrouted_category_is_not_retried_and_says_so(monkeypatch, category):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, category) if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert len(_items(stub)) == 1
    assert sd.error == (f"refused digest (stop_reason='refusal', category={category!r}); "
                        f"not retried: no fallback for category {category!r} on {OPUS}")


@pytest.mark.parametrize("details", [True, False], ids=["category-null", "no-stop-details"])
def test_a_refusal_with_no_category_is_not_retried(monkeypatch, details):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, None, details=details) if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert len(_items(stub)) == 1
    assert sd.error == "refused digest (stop_reason='refusal')"


@pytest.mark.parametrize("model", [OPUS_55, SONNET_55], ids=["opus-5-5", "sonnet-5-5"])
def test_a_cyber_refusal_on_a_55_model_is_not_retried(monkeypatch, model):
    # The 5.5 models (the defaults since they were registered) declare no host
    # route, so a cyber refusal on one is not resubmitted and says so, as any
    # unrouted refusal. Declaring a route for them is the owner's call; this
    # pins today's registry.
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else None))
    sd, other = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH, model=model)
    assert len(_items(stub)) == 1 and not _realtime(stub)
    assert sd.error == ("refused digest (stop_reason='refusal', category='cyber'); "
                        f"not retried: no fallback for category 'cyber' on {model}")
    assert other.ok


@pytest.mark.parametrize(
    "recommended, expected",
    [(SONNET, SONNET), ("claude-unregistered-9", OPUS_48), (OPUS, OPUS_48), (None, OPUS_48)],
    ids=["registered", "unregistered", "the-refusing-model", "absent"],
)
def test_recommended_model_is_the_target_only_when_registered(monkeypatch, recommended, expected):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber", recommended=recommended) if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    items = _items(stub)
    assert [p["model"] for p in items] == [OPUS, expected]
    assert items[1] == D.retarget_digest_request(items[0], expected)
    assert sd.ok


def test_recommended_model_does_not_open_an_unrouted_category(monkeypatch):
    # The gate decides whether, the target where (the owner's rules).
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "bio", recommended=OPUS_48) if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert len(_items(stub)) == 1 and not sd.ok


@pytest.mark.parametrize("transport", _TRANSPORTS, ids=["batch", "direct"])
def test_a_fallback_that_refuses_too_is_final(monkeypatch, transport):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(lambda k, p: _refusal_envelope(p, "cyber")))
    sd, _ = _collect(stub, monkeypatch, transport=transport)
    assert [p["model"] for p in _items(stub)] == [OPUS, OPUS_48]
    assert not _realtime(stub)
    assert sd.error == f"refused digest on {OPUS_48} (stop_reason='refusal', category='cyber')"


def test_a_fallback_that_comes_back_worse_is_named_on_the_refusal(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1
        else R.errored("invalid_request_error", "the detail")))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert len(_items(stub)) == 2
    assert sd.error == ("refused digest (stop_reason='refusal', category='cyber'); "
                        f"retry on {OPUS_48}: invalid_request_error: the detail")


def test_a_fallback_transient_failure_is_retried_on_the_fallback(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1
        else R.errored("overloaded_error", "busy") if k == 2 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert [p["model"] for p in _items(stub)] == [OPUS, OPUS_48, OPUS_48]
    assert sd.ok


def test_a_truncated_fallback_gets_the_raised_cap_on_the_fallback(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1
        else R.succeeded(R.message([], model=p["model"], stop_reason="max_tokens")) if k == 2
        else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert [(p["model"], p["max_tokens"]) for p in _items(stub)] == [
        (OPUS, 64_000), (OPUS_48, 64_000), (OPUS_48, 128_000)]
    assert sd.ok


# --------------------------------------------------------------------------- #
# One per-sheet retry budget
# --------------------------------------------------------------------------- #


def test_the_refusal_retry_counts_against_the_budget(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "1")
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else R.errored("overloaded_error", "busy")))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert [p["model"] for p in _items(stub)] == [OPUS, OPUS_48]
    assert sd.error == ("refused digest (stop_reason='refusal', category='cyber'); "
                        f"retry on {OPUS_48}: overloaded_error: busy")


def test_the_budget_covers_the_direct_rescue(monkeypatch):
    # RECOVERY_DIRECT: the follow-up batch spends the only retry, so the
    # full-rate rescue is not reached. Before WP-01.5 the rescue ran whatever
    # the round ceiling said.
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "1")
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(lambda k, p: R.errored("overloaded_error", "busy")))
    sd, other = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)
    assert len(_items(stub)) == 2 and not _realtime(stub)
    assert sd.error == "overloaded_error: busy" and other.ok


def test_the_default_budget_keeps_the_direct_rescue(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(lambda k, p: R.errored("overloaded_error", "busy")))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)
    assert len(_items(stub)) == 2 and len(_realtime(stub)) == 1
    assert sd.ok and sd.rescued


@pytest.mark.parametrize("rounds", [1, 2, 4], ids=["1", "2", "4"])
def test_no_sheet_is_resubmitted_more_than_the_budget(monkeypatch, rounds):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", str(rounds))
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else R.errored("overloaded_error", "busy")))
    _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert len(_items(stub)) == 1 + rounds


# --------------------------------------------------------------------------- #
# The selected transport
# --------------------------------------------------------------------------- #


def _reject_batch_creates_after(n: int):
    seen = {"n": 0}

    def reject(record):
        if record["path"] == "/v1/messages/batches" and record["method"] == "POST":
            seen["n"] += 1
            if seen["n"] > n:
                return httpx2.Response(500, json={"type": "error", "error": {
                    "type": "api_error", "message": "batch backend down"}})
        return None

    return reject


def test_the_pipelines_transport_never_rescues_a_refusal_in_real_time(monkeypatch):
    stub = AnthropicAPIStub(_ok, reject=_reject_batch_creates_after(1), batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert not _realtime(stub)
    assert sd.error == "refused digest (stop_reason='refusal', category='cyber')"


def test_direct_recovery_rescues_the_fallback_at_full_rate_when_its_batch_cannot_run(monkeypatch):
    stub = AnthropicAPIStub(_ok, reject=_reject_batch_creates_after(1), batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)
    [call] = _realtime(stub)
    assert call["model"] == OPUS_48 and "fallbacks" not in call      # the host's swap, not the server's
    assert sd.ok and sd.rescued and sd.fallback_model == OPUS_48


def test_direct_recovery_rescues_a_refusal_first_seen_in_the_follow_up_at_full_rate(monkeypatch):
    # RECOVERY_DIRECT is the full-rate policy a caller selects: an item still
    # failing after the follow-up batch goes to the rescue, and so does a sheet
    # the follow-up itself came back refused for, on its fallback.
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: R.errored("overloaded_error", "busy") if k == 1
        else _refusal_envelope(p, "cyber") if k == 2 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_DIRECT)
    assert [p["model"] for p in _items(stub)] == [OPUS, OPUS]
    [call] = _realtime(stub)
    assert call["model"] == OPUS_48
    assert sd.ok and sd.rescued


def test_the_pipelines_transport_keeps_a_refusal_first_seen_in_a_round_on_the_batch(monkeypatch):
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: R.errored("overloaded_error", "busy") if k == 1
        else _refusal_envelope(p, "cyber") if k == 2 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert [p["model"] for p in _items(stub)] == [OPUS, OPUS, OPUS_48]
    assert not _realtime(stub) and sd.ok


# --------------------------------------------------------------------------- #
# The abandoned-batch harvest asks the same predicate
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("transport", _TRANSPORTS, ids=["batch", "direct"])
def test_a_harvested_cyber_refusal_goes_to_the_fallback(monkeypatch, transport):
    stub = _StallingStub(_ok, stall={1}, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else None))
    sd, other = _collect(stub, monkeypatch, transport=transport)
    assert sd.ok and sd.fallback_model == OPUS_48
    assert other.ok
    if transport == BD.RECOVERY_BATCH:
        assert [p["model"] for p in _items(stub)] == [OPUS, OPUS_48] and not _realtime(stub)
    else:
        [call] = _realtime(stub)
        assert call["model"] == OPUS_48


@pytest.mark.parametrize("transport", _TRANSPORTS, ids=["batch", "direct"])
def test_a_harvested_permanent_error_is_not_resubmitted(monkeypatch, transport):
    stub = _StallingStub(_ok, stall={1}, batch_result=_sheet0(
        lambda k, p: R.errored("invalid_request_error", "the detail") if k == 1 else None))
    sd, other = _collect(stub, monkeypatch, transport=transport)
    assert len(_items(stub)) == 1 and not _realtime(stub)
    assert sd.error == "invalid_request_error: the detail"          # held, not "not collected"
    assert other.ok


def test_a_harvested_unrouted_refusal_is_held_and_not_resubmitted(monkeypatch):
    stub = _StallingStub(_ok, stall={1}, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "bio") if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert len(_items(stub)) == 1
    assert sd.error == ("refused digest (stop_reason='refusal', category='bio'); "
                        f"not retried: no fallback for category 'bio' on {OPUS}")


def test_a_harvested_refusal_whose_fallback_fails_keeps_the_refusal(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "1")
    stub = _StallingStub(_ok, stall={1}, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else R.errored("overloaded_error", "busy")))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert sd.error == ("refused digest (stop_reason='refusal', category='cyber'); "
                        f"retry on {OPUS_48}: overloaded_error: busy")


def test_a_harvested_canceled_item_is_still_resubmitted(monkeypatch):
    # The harvest canceled the batch itself, so an item it never processed
    # reads canceled and is resubmitted on its own model, as before.
    stub = _StallingStub(_ok, stall={1}, batch_result=_sheet0(lambda k, p: R.PENDING if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH)
    assert [p["model"] for p in _items(stub)] == [OPUS, OPUS]
    assert sd.ok


# --------------------------------------------------------------------------- #
# The cache: the requested model's key
# --------------------------------------------------------------------------- #


def test_a_fallback_read_is_cached_under_the_requested_models_key(monkeypatch, tmp_path):
    cache = DigestCache(tmp_path / "cache.sqlite")
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(
        lambda k, p: _refusal_envelope(p, "cyber") if k == 1 else None))
    sd, _ = _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH, cache=cache)
    assert sd.ok
    warm = AnthropicAPIStub(_ok)
    served, _ = _collect(warm, monkeypatch, transport=BD.RECOVERY_BATCH,
                         cache=DigestCache(tmp_path / "cache.sqlite"))
    assert served.cached and served.ok and not warm.requests


def test_an_unfinished_fallback_read_is_not_cached(monkeypatch, tmp_path):
    cache = DigestCache(tmp_path / "cache.sqlite")
    stub = AnthropicAPIStub(_ok, batch_result=_sheet0(lambda k, p: _refusal_envelope(p, "cyber")))
    _collect(stub, monkeypatch, transport=BD.RECOVERY_BATCH, cache=cache)
    warm = AnthropicAPIStub(_ok)
    served, _ = _collect(warm, monkeypatch, transport=BD.RECOVERY_BATCH,
                         cache=DigestCache(tmp_path / "cache.sqlite"))
    assert not served.cached and len(_items(warm)) == 1


def test_recorded_limit_a_fallback_read_is_labelled_with_the_requested_model(tmp_path):
    """Recorded limit (WP-14.3, U1): a host fallback read served by Opus 4.8 is
    recorded in the usage ledger under the requested model (claude-opus-5, the
    one model with a host route, so the run names it), as the server-side
    fallback's is (``test_response_shapes::test_recorded_limit_the_serving_
    model_is_not_read``). Same price today ($5/$25). WP-14.3 reads the serving
    model: this record names claude-opus-4-8."""
    import drawing_analyzer.pipeline as pl
    from tests.fixtures.gauntlet import build_mini_set
    from tests.test_response_shapes import _about_m101, _first, _records, _shaped
    from tests.test_sdk_contract import _script, stage_of

    def refusal(body, params):
        body["content"] = []
        body["stop_reason"] = "refusal"
        body["stop_details"] = R.refusal_stop_details("cyber", explanation="declined")
        return body

    stub = AnthropicAPIStub(_shaped(_script(), refusal, stages={"digest"},
                                    when=_first(lambda p: stage_of(p) == "digest" and _about_m101(p))))
    ctx = pl.extract_drawing_context(build_mini_set(tmp_path), client=stub.client(), rows=2, cols=2,
                                     cache=DigestCache(tmp_path / "cache.sqlite"), use_batch=True,
                                     model=OPUS)
    m101 = [r for r in _records(ctx, "digest") if r.stage_instance == "digest:SRC-0001:p0"]
    assert [(r.attempt_number, r.model, r.terminal_status) for r in m101] == [
        (1, OPUS, "FAILED"), (2, OPUS, "COMPLETE")]


# --------------------------------------------------------------------------- #
# The batch critique: an errored read keeps its type; a refusal its category
# --------------------------------------------------------------------------- #

_CRIT = "```json\n{\"findings\": []}\n```"


def _critique_first_read(envelope):
    first = {"done": False}

    def batch_result(custom_id, params):
        if custom_id == "sheet__0__r1" and not first["done"]:
            first["done"] = True
            return envelope(params)
        return None

    stub = AnthropicAPIStub(lambda p: R.message([R.text(_CRIT)], model=p.get("model", OPUS)),
                            batch_result=batch_result)
    clock = _Clock()
    client = stub.client()
    batch = BC.submit_critique_batch([_make_sheet(i) for i in range(2)], client=client, runs=2,
                                     total=2, sleep=clock.sleep)
    [(_, first_sheet), _] = BC.collect_critique_batch(batch, client=client, sleep=clock.sleep,
                                                      max_elapsed_seconds=100_000)
    return first_sheet


@pytest.mark.parametrize("error_type", R.ERROR_TYPES, ids=list(R.ERROR_TYPES))
def test_an_errored_critique_read_keeps_its_error_type(error_type):
    res = _critique_first_read(lambda p: R.errored(error_type, "the detail"))
    assert res.read_errors == [f"{error_type}: the detail"]
    assert res.completed_runs == 1


@pytest.mark.parametrize("envelope, text", [(R.CANCELED, "batch item canceled"),
                                            (R.EXPIRED, "batch item expired")],
                         ids=["canceled", "expired"])
def test_a_canceled_or_expired_critique_read_keeps_its_text(envelope, text):
    res = _critique_first_read(lambda p: envelope)
    assert res.read_errors == [text]


def test_a_refused_critique_read_names_its_category():
    res = _critique_first_read(lambda p: _refusal_envelope(p, "cyber"))
    assert res.read_errors == ["refused critique (stop_reason='refusal', category='cyber')"]


# --------------------------------------------------------------------------- #
# Real time: the category is named; the server-side fallback is unchanged
# --------------------------------------------------------------------------- #


def test_a_real_time_refusal_names_its_category_and_is_not_retried_by_the_host():
    stub = AnthropicAPIStub(lambda p: _refused(p, "cyber", recommended=OPUS_48))
    sd = D.digest_sheet(_make_sheet(0), client=stub.client(), model=OPUS, sleep=lambda s: None)
    assert sd.error == "refused digest (stop_reason='refusal', category='cyber')"
    [call] = _realtime(stub)
    assert call["model"] == OPUS and call.get("fallbacks") == "default"   # the server's fallback
