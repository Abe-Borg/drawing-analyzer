"""Production's requests, sent through the real SDK (remediation WP-02.2, U26).

The suite's fakes stand in for the SDK's objects, so a request the installed
SDK refuses before sending anything passed CI: ``betas`` or ``fallbacks`` on
``client.messages`` (a ``TypeError``), or a non-streaming ``create`` above the
SDK's cap (a ``ValueError``). A stage that regressed from
``digest.stream_message`` to a plain ``create`` was green. These tests send
every production request builder through the real, installed SDK over an
in-process API stand-in (``tests/fixtures/sdk_transport.py``; nothing opens a
socket) and assert, per request, what the SDK sent:

- nothing is refused client-side: every stage of an exhaustive run completes,
  on every transport, on every registered model, with the refusal fallback on
  and off, and after each self-healing latch flips;
- a request is on the beta namespace (``?beta=true``) exactly when it carries
  an ``anthropic-beta`` header, and the header names exactly the betas it
  needs: the refusal fallback (a model that declares it, ``fallbacks`` in the
  body) and the investigation's task budget (``output_config.task_budget``);
- a non-streaming request never asks for more than the SDK's cap for its
  model, and every stage whose cap is above it streams;
- batch submits and file uploads carry no ``anthropic-beta`` header, and every
  batch item's params are ones the SDK's own batch item type names.

The facts these rest on are pinned first, so an SDK upgrade that changes one
fails here and is re-measured (the owner's rule: derive from the installed
SDK, and keep one tripwire). The fakes are held to the same SDK in
``tests/test_strict_fakes.py``.
"""
from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest

import anthropic

pytest.importorskip("pymupdf")

import drawing_analyzer.batch_digest as BD  # noqa: E402
import drawing_analyzer.core.api_config as api  # noqa: E402
import drawing_analyzer.critique as critique_mod  # noqa: E402
import drawing_analyzer.investigate as inv  # noqa: E402
import drawing_analyzer.pipeline as pl  # noqa: E402
import drawing_analyzer.prose_harvest as harvest_mod  # noqa: E402
import drawing_analyzer.verify as verify_mod  # noqa: E402
from drawing_analyzer import (  # noqa: E402
    citation_check, cross_qc, digest, focus, review_planner, set_identity, synthesis,
)
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from tests.fixtures.fake_anthropic import (  # noqa: E402
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    sdk_nonstreaming_limit,
)
from tests.fixtures.gauntlet import build_mini_set, mini_client  # noqa: E402
from tests.fixtures.sdk_transport import AnthropicAPIStub, error_400  # noqa: E402

OPUS = api.MODEL_OPUS_55
REGISTERED = (api.MODEL_OPUS_55, api.MODEL_SONNET_55, api.MODEL_OPUS_5,
              api.MODEL_SONNET_5, api.MODEL_OPUS_48, api.MODEL_SONNET_46,
              api.MODEL_HAIKU_45)
FALLBACK_BETA = api.REFUSAL_FALLBACK_BETA
TASK_BUDGET_BETA = inv.TASK_BUDGET_BETA
_TRANSPORTS = {           # (use_batch, critique_use_batch)
    "fast": (False, False),
    "batch": (True, False),
    "hybrid": (False, True),
    "economy": (True, True),
}
_STAGE_MODEL_ENV = (
    "DRAWING_ANALYZER_CRITIQUE_MODEL", "DRAWING_ANALYZER_CROSS_QC_MODEL",
    "DRAWING_ANALYZER_INVESTIGATION_MODEL", "DRAWING_ANALYZER_HARVEST_MODEL",
    "DRAWING_ANALYZER_CITATION_MODEL", "DRAWING_ANALYZER_VERIFY_MODEL",
    "DRAWING_ANALYZER_IDENTITY_MODEL", "DRAWING_ANALYZER_REVIEW_PLAN_MODEL",
)
_STRUCTURED_ENV = (
    "DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS",
    "DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS",
    "DRAWING_ANALYZER_VERIFY_STRUCTURED_OUTPUTS",
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _batch_item_keys() -> frozenset[str]:
    """The params the SDK's own plain batch item type names."""
    from anthropic.types.messages import batch_create_params

    params = typing.get_type_hints(batch_create_params.Request)["params"]
    return frozenset(typing.get_type_hints(params))


def _system_text(body: dict) -> str:
    system = body.get("system", "")
    if isinstance(system, list):
        return "".join(b.get("text", "") for b in system if isinstance(b, dict))
    return str(system or "")


_EXACT = {
    verify_mod.VERIFY_SYSTEM_PROMPT: "verification",
    inv.INVESTIGATE_SYSTEM_PROMPT: "investigation",
    set_identity.IDENTITY_SYSTEM_PROMPT: "identity",
    review_planner.PLANNER_SYSTEM_PROMPT: "review_plan",
    harvest_mod.harvest_system_prompt(): "prose_harvest",
    harvest_mod.harvest_system_prompt(structured=True): "prose_harvest",
}
_PREFIX = [
    (cross_qc.CROSS_QC_RECONCILE_SYSTEM_PROMPT, "cross_qc"),
    (cross_qc.cross_qc_system_prompt(), "cross_qc"),
    (critique_mod.CRITIQUE_SYSTEM_PROMPT, "critique"),
    (digest.DIGEST_SYSTEM_PROMPT, "digest"),
    (citation_check.CITATION_SYSTEM_PROMPT, "citation"),
    (synthesis.SYNTHESIS_SYSTEM_PROMPT, "synthesis"),
    (focus.FOCUS_REPORT_SYSTEM_PROMPT, "focus"),
]


def stage_of(body: dict) -> str:
    system = _system_text(body)
    if system in _EXACT:
        return _EXACT[system]
    for prompt, stage in _PREFIX:
        if system[:60] == prompt[:60]:
            return stage
    return "unattributed"


def _betas(record: dict) -> set[str]:
    return {b.strip() for b in (record["beta"] or "").split(",") if b.strip()}


def assert_request_contract(stub: AnthropicAPIStub, *, fallback_on: bool = True) -> dict:
    """Assert the per-request contract over everything the SDK sent.

    Returns ``{stage: [record, ...]}`` for the Messages requests, so a caller
    can add what its own scenario implies.
    """
    by_stage: dict[str, list[dict]] = {}
    item_keys = _batch_item_keys()
    for record in stub.requests:
        path, method = record["path"], record["method"]
        if path == "/v1/messages" and method == "POST":
            body = record["body"]
            stage = stage_of(body)
            by_stage.setdefault(stage, []).append(record)
            betas = _betas(record)
            model = body["model"]
            where = (stage, model, sorted(betas))
            # The beta namespace exactly when a beta header rides the request.
            assert (record["query"] == "beta=true") == bool(betas), where
            assert betas <= {FALLBACK_BETA, TASK_BUDGET_BETA}, where
            # The refusal fallback: a model that declares it, the beta and the
            # body parameter together, and only while it is on.
            has_fallback = FALLBACK_BETA in betas
            assert has_fallback == ("fallbacks" in body), where
            if has_fallback:
                assert api.model_capabilities(model).supports_refusal_fallback, where
                assert fallback_on, where
            elif fallback_on and api.model_capabilities(model).supports_refusal_fallback:
                assert api._refusal_fallback_available is False, where
            # The task budget: the beta exactly when the budget is in the body.
            output_config = body.get("output_config") or {}
            assert (TASK_BUDGET_BETA in betas) == ("task_budget" in output_config), where
            # The non-streaming cap, for the request's own model.
            if not body.get("stream"):
                assert body["max_tokens"] <= sdk_nonstreaming_limit(model), where
        elif path == "/v1/messages/batches" and method == "POST":
            assert record["beta"] is None, "a batch submit carried a beta header"
            for item in record["body"]["requests"]:
                extra = set(item["params"]) - item_keys
                assert not extra, (item["custom_id"], sorted(extra))
        elif path == "/v1/files" and method == "POST":
            assert record["beta"] is None, "an upload carried a beta header"
        elif path == "/v1/messages/count_tokens":
            assert record["beta"] is None and record["query"] == ""
    assert "unattributed" not in by_stage, [
        _system_text(r["body"])[:80] for r in by_stage["unattributed"]]
    return by_stage


def _batched(stub: AnthropicAPIStub) -> set[str]:
    return {
        stage_of(item["params"])
        for r in stub.requests
        if r["path"] == "/v1/messages/batches" and r["method"] == "POST"
        for item in r["body"]["requests"]
    }


@pytest.fixture(autouse=True)
def _fresh_latches(monkeypatch):
    """Every self-healing latch starts on and is restored after."""
    monkeypatch.setattr(api, "_refusal_fallback_available", True)
    monkeypatch.setattr(inv, "_task_budget_available", True)
    monkeypatch.setattr(inv, "_strict_tools_available", True)
    for gate in (critique_mod.STRUCTURED_OUTPUTS, harvest_mod.STRUCTURED_OUTPUTS,
                 verify_mod.STRUCTURED_OUTPUTS):
        monkeypatch.setattr(gate, "available", True)
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    monkeypatch.setattr(BD, "_run_in_background", lambda fn: fn())


def _run(tmp_path: Path, stub: AnthropicAPIStub, transport: str = "fast", **kwargs):
    use_batch, critique_batch = _TRANSPORTS[transport]
    work = tmp_path / "work"
    work.mkdir()
    return pl.extract_drawing_context(
        build_mini_set(tmp_path), client=stub.client(), rows=2, cols=2,
        cache=DigestCache(tmp_path / "cache.sqlite"), synthesize=True,
        use_batch=use_batch, critique_use_batch=critique_batch,
        focus="equipment coordination", qc_markups=True, qc_work_dir=work,
        **kwargs,
    )


def _script():
    """The gauntlet's mini-set script, with one UNCERTAIN verdict so the
    investigation (and its task budget) runs."""
    return mini_client(verify_verdicts=(("VAV-3", "NOT_VISIBLE"),))


def _statuses(ctx) -> dict[str, str]:
    return {s.stage: s.status for s in ctx.stage_results}


_EVERY_STAGE = {"digest", "identity", "review_plan", "critique", "cross_qc", "synthesis",
                "focus", "prose_harvest", "verification", "investigation", "citation"}


def _assert_every_stage_reached(stub, by_stage):
    reached = set(by_stage) | _batched(stub)
    assert _EVERY_STAGE <= reached, sorted(_EVERY_STAGE - reached)


# --------------------------------------------------------------------------- #
# The SDK facts (the tripwire: an upgrade that changes one fails here)
# --------------------------------------------------------------------------- #


def _stub_client() -> tuple[anthropic.Anthropic, AnthropicAPIStub]:
    stub = AnthropicAPIStub(lambda params: FakeMessage(content=[FakeTextBlock(text="ok")]))
    return stub.client(), stub


def _call(fn) -> str:
    try:
        fn()
    except TypeError:
        return "TypeError"
    except ValueError:
        return "ValueError"
    return "sent"


def _stream(target, **kwargs):
    with target.stream(**kwargs) as s:
        return s.get_final_message()


_MSG = [{"role": "user", "content": "x"}]

_REFUSED_ON_PLAIN = {
    "create-betas": lambda c: c.messages.create(model=OPUS, max_tokens=8, messages=_MSG, betas=["b"]),
    "create-fallbacks": lambda c: c.messages.create(model=OPUS, max_tokens=8, messages=_MSG,
                                                    fallbacks="default"),
    "stream-betas": lambda c: _stream(c.messages, model=OPUS, max_tokens=8, messages=_MSG, betas=["b"]),
    "stream-fallbacks": lambda c: _stream(c.messages, model=OPUS, max_tokens=8, messages=_MSG,
                                          fallbacks="default"),
    "batches-create-betas": lambda c: c.messages.batches.create(requests=[], betas=["b"]),
}


@pytest.mark.parametrize("case", sorted(_REFUSED_ON_PLAIN), ids=sorted(_REFUSED_ON_PLAIN))
def test_fact_the_plain_namespace_refuses_betas_and_fallbacks_before_sending(case):
    client, stub = _stub_client()
    assert _call(lambda: _REFUSED_ON_PLAIN[case](client)) == "TypeError"
    assert stub.requests == []


def test_fact_the_beta_namespace_sends_them_as_a_header_and_a_body_parameter():
    client, stub = _stub_client()
    client.beta.messages.create(model=OPUS, max_tokens=8, messages=_MSG,
                                betas=[FALLBACK_BETA], fallbacks="default")
    [record] = stub.requests
    assert (record["path"], record["query"], record["beta"]) == (
        "/v1/messages", "beta=true", FALLBACK_BETA)
    assert record["body"]["fallbacks"] == "default" and "betas" not in record["body"]


# The measured cap: 21,333 accepted and 21,334 refused, with no request sent,
# for every registered model on both namespaces (SDK 1.7.0 and 1.8.0). This is
# the one literal in the suite, and it is a tripwire, not a rule: the fakes and
# every assertion above derive the cap from the SDK. If an upgrade moves it,
# re-measure, then update this number and CLAUDE.md's streaming invariant.
_MEASURED_CAP = 21_333


@pytest.mark.parametrize("namespace", ["plain", "beta"])
@pytest.mark.parametrize("model", REGISTERED, ids=list(REGISTERED))
def test_fact_the_non_streaming_cap_is_the_measured_one(model, namespace):
    client, stub = _stub_client()
    target = client.beta.messages if namespace == "beta" else client.messages

    assert sdk_nonstreaming_limit(model) == _MEASURED_CAP
    assert _call(lambda: target.create(model=model, max_tokens=_MEASURED_CAP, messages=_MSG)) == "sent"
    sent = len(stub.requests)
    assert _call(lambda: target.create(model=model, max_tokens=_MEASURED_CAP + 1,
                                       messages=_MSG)) == "ValueError"
    assert len(stub.requests) == sent            # refused before any request
    assert _call(lambda: _stream(target, model=model, max_tokens=64_000, messages=_MSG)) == "sent"


def test_fact_batches_and_files_carry_no_beta_header():
    client, stub = _stub_client()
    image = {"type": "image", "source": {"type": "file", "file_id": "file_1"}}
    client.messages.batches.create(requests=[{"custom_id": "a", "params": {
        "model": OPUS, "max_tokens": 64_000,
        "messages": [{"role": "user", "content": [image]}]}}])
    client.files.upload(file=("a.png", b"png", "image/png"))
    assert [(r["method"], r["path"], r["beta"]) for r in stub.requests] == [
        ("POST", "/v1/messages/batches", None), ("POST", "/v1/files", None)]


def test_fact_the_production_client_keeps_the_sdks_default_timeout():
    # The SDK applies its non-streaming cap only under its default timeout, so
    # the production client must keep it for the cap to guard its requests.
    from drawing_analyzer.client import new_client

    assert new_client("sk-ant-" + "timeout-" + "0" * 16).timeout == anthropic.DEFAULT_TIMEOUT


# --------------------------------------------------------------------------- #
# Every stage, every transport, the refusal fallback on and off
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fallback", ["fallback-on", "fallback-off"])
@pytest.mark.parametrize("transport", sorted(_TRANSPORTS), ids=sorted(_TRANSPORTS))
def test_every_stage_request_is_one_the_sdk_sends(tmp_path, monkeypatch, transport, fallback):
    if fallback == "fallback-off":
        monkeypatch.setenv("DRAWING_ANALYZER_REFUSAL_FALLBACK", "0")
    stub = AnthropicAPIStub(_script()._route)

    ctx = _run(tmp_path, stub, transport)

    assert ctx.qc_status == "COMPLETE", _statuses(ctx)
    assert ctx.errors == []
    by_stage = assert_request_contract(stub, fallback_on=fallback == "fallback-on")
    _assert_every_stage_reached(stub, by_stage)
    opus_calls = [r for rs in by_stage.values() for r in rs if r["body"]["model"] == OPUS]
    assert opus_calls
    if fallback == "fallback-on":
        assert all(FALLBACK_BETA in _betas(r) for r in opus_calls)
    else:
        assert not any(FALLBACK_BETA in _betas(r) for r in opus_calls)
    # The investigation's turns carry the task budget on the beta namespace.
    assert all(TASK_BUDGET_BETA in _betas(r) for r in by_stage["investigation"])
    use_batch, critique_batch = _TRANSPORTS[transport]
    assert ("digest" in _batched(stub)) == use_batch
    assert ("critique" in _batched(stub)) == critique_batch


@pytest.mark.parametrize("transport", ["fast", "economy"])
@pytest.mark.parametrize("model", REGISTERED, ids=list(REGISTERED))
def test_every_stage_on_each_registered_model(tmp_path, monkeypatch, model, transport):
    for name in _STAGE_MODEL_ENV:
        monkeypatch.setenv(name, model)
    stub = AnthropicAPIStub(_script()._route)

    ctx = _run(tmp_path, stub, transport, model=model, synthesis_model=model, focus_model=model)

    assert ctx.qc_status == "COMPLETE", _statuses(ctx)
    by_stage = assert_request_contract(stub)
    _assert_every_stage_reached(stub, by_stage)
    models = {r["body"]["model"] for rs in by_stage.values() for r in rs}
    assert models == {model}
    declares = api.model_capabilities(model).supports_refusal_fallback
    assert all((FALLBACK_BETA in _betas(r)) == declares for rs in by_stage.values() for r in rs)


# --------------------------------------------------------------------------- #
# Each self-healing latch: the re-issued request is one the SDK sends
# --------------------------------------------------------------------------- #


def _reject_first(feature: str):
    """A 400 naming ``feature`` for the first request that carries it."""
    state = {"rejected": 0}

    def carries(body: dict) -> bool:
        output_config = body.get("output_config") or {}
        return {
            "fallback": "fallbacks" in body,
            "task-budget": "task_budget" in output_config,
            "strict-tools": any(t.get("strict") for t in body.get("tools") or []),
            "structured-outputs": "format" in output_config,
        }[feature]

    message = {
        "fallback": "fallbacks: server-side-fallback-2026-07-01 is not enabled",
        "task-budget": "output_config.task_budget: task-budgets are not enabled",
        "strict-tools": "tools.0.strict: strict tool schemas are not supported",
        "structured-outputs": "output_config.format: json_schema is not supported here",
    }[feature]

    def reject(record):
        if state["rejected"] or record["path"] != "/v1/messages" or not carries(record["body"]):
            return None
        state["rejected"] += 1
        record["rejected"] = True
        return error_400(message)

    return reject, state


_LATCH = {
    "fallback": lambda: api._refusal_fallback_available,
    "task-budget": lambda: inv._task_budget_available,
    "strict-tools": lambda: inv._strict_tools_available,
    "structured-outputs": lambda: critique_mod.STRUCTURED_OUTPUTS.available,
}


@pytest.mark.parametrize("feature", sorted(_LATCH), ids=sorted(_LATCH))
def test_a_rejected_feature_is_reissued_without_it_and_sent(tmp_path, monkeypatch, feature):
    if feature == "structured-outputs":
        for name in _STRUCTURED_ENV:
            monkeypatch.setenv(name, "1")
    reject, state = _reject_first(feature)
    stub = AnthropicAPIStub(_script()._route, reject=reject)

    ctx = _run(tmp_path, stub)

    assert state["rejected"] == 1
    assert _LATCH[feature]() is False                      # latched off
    assert ctx.qc_status == "COMPLETE", _statuses(ctx)
    [rejected] = [r for r in stub.requests if r.get("rejected")]
    # The same stage's next request went out without the feature and was sent.
    stage = stage_of(rejected["body"])
    later = stub.requests[stub.requests.index(rejected) + 1:]
    retried = [r for r in later if r["path"] == "/v1/messages" and stage_of(r["body"]) == stage]
    assert retried, stage
    stub.requests.remove(rejected)
    assert_request_contract(stub, fallback_on=True)


def test_structured_outputs_ride_the_namespace_of_their_model(tmp_path, monkeypatch):
    for name in _STRUCTURED_ENV:
        monkeypatch.setenv(name, "1")
    # Both 5.5 defaults declare the refusal fallback, so every default stage is
    # on the beta namespace. Verification is pinned to Sonnet 5, which does not,
    # so a structured request on the plain namespace is still covered.
    monkeypatch.setenv("DRAWING_ANALYZER_VERIFY_MODEL", api.MODEL_SONNET_5)
    stub = AnthropicAPIStub(_script()._route)

    ctx = _run(tmp_path, stub)

    assert ctx.qc_status == "COMPLETE", _statuses(ctx)
    by_stage = assert_request_contract(stub)
    for stage in ("critique", "prose_harvest", "verification"):
        records = by_stage[stage]
        assert records and all("format" in (r["body"].get("output_config") or {}) for r in records)
    # Opus 5.5 critique and Sonnet 5.5 harvest on the beta namespace, the
    # pinned Sonnet 5 verification on plain.
    assert all(r["query"] == "beta=true" for r in by_stage["critique"] + by_stage["prose_harvest"])
    assert all(r["query"] == "" for r in by_stage["verification"])


# --------------------------------------------------------------------------- #
# The non-streaming cap, per stage and model
# --------------------------------------------------------------------------- #


def _stage_caps(model: str) -> dict[str, tuple[int, bool]]:
    """Every stage's resolved ``max_tokens`` for ``model`` and whether it streams,
    through the production helpers (the values the request builders send)."""
    cap = api.output_cap_for_model
    return {
        "citation": (api.phase_output_cap(api.PHASE_CITATION, model=model), False),
        "cross_qc": (api.phase_output_cap(api.PHASE_CROSS_QC, model=model), False),
        "prose_harvest": (api.phase_output_cap(api.PHASE_HARVEST, model=model), False),
        "identity": (cap(model, requested=set_identity.DEFAULT_IDENTITY_MAX_TOKENS), False),
        "verification": (api.phase_output_cap(api.PHASE_VERIFICATION, model=model), False),
        "investigation": (api.phase_output_cap(api.PHASE_INVESTIGATION, model=model), True),
        "digest": (cap(model, requested=digest.DEFAULT_DIGEST_MAX_TOKENS), True),
        "digest raised-cap retry": (cap(model, requested=min(
            digest.DEFAULT_DIGEST_MAX_TOKENS * 2, digest.MAX_TOKENS_RETRY_CEILING)), True),
        "critique": (cap(model, requested=critique_mod.DEFAULT_CRITIQUE_MAX_TOKENS), True),
        "review_plan": (cap(model, requested=review_planner.DEFAULT_PLAN_MAX_TOKENS), True),
        "synthesis": (cap(model, requested=synthesis.DEFAULT_SYNTHESIS_MAX_TOKENS), True),
        "focus": (cap(model, requested=focus.DEFAULT_FOCUS_MAX_TOKENS), True),
    }


@pytest.mark.parametrize("model", REGISTERED + ("claude-unregistered-9",),
                         ids=list(REGISTERED) + ["unregistered"])
def test_every_non_streaming_stage_is_within_the_sdk_cap(model):
    limit = sdk_nonstreaming_limit(model)
    caps = _stage_caps(model)
    above = {stage for stage, (n, _) in caps.items() if n > limit}
    streamed = {stage for stage, (_, streams) in caps.items() if streams}
    assert above <= streamed, sorted(above - streamed)
    assert above, "no stage above the cap: the table no longer exercises the rule"


def test_the_cap_table_matches_what_the_stages_send(tmp_path):
    # The table above is the helpers' view; this run is the requests' view.
    stub = AnthropicAPIStub(_script()._route)
    _run(tmp_path, stub)
    caps = _stage_caps(OPUS)
    sent = assert_request_contract(stub)
    for stage, records in sent.items():
        for record in records:
            body = record["body"]
            if stage in caps and body["model"] == OPUS:
                assert body["max_tokens"] == caps[stage][0], (stage, body["max_tokens"])
                assert bool(body.get("stream")) == caps[stage][1], stage


# --------------------------------------------------------------------------- #
# The raised-cap retries stream, and a batch follow-up carries no beta
# --------------------------------------------------------------------------- #


def _truncating_first_digest(script):
    seen: dict[str, int] = {}

    def route(params):
        if stage_of(params) == "digest":
            text = json.dumps(params.get("messages", []))[:4000]
            key = "VAV" if "VAV-3" in text else "other"
            seen[key] = seen.get(key, 0) + 1
            if seen[key] == 1:
                return FakeMessage(content=[FakeTextBlock(text="partial")],
                                   stop_reason="max_tokens",
                                   usage=FakeUsage(input_tokens=10, output_tokens=5))
        return script._route(params)

    return route


@pytest.mark.parametrize("transport", ["fast", "batch"])
def test_the_raised_cap_retry_is_a_request_the_sdk_sends(tmp_path, transport):
    stub = AnthropicAPIStub(_truncating_first_digest(_script()))

    ctx = _run(tmp_path, stub, transport)

    assert _statuses(ctx)["digest"] == "COMPLETE", ctx.errors
    by_stage = assert_request_contract(stub)
    if transport == "fast":
        raised = [r for r in by_stage["digest"] if r["body"]["max_tokens"] > digest.DEFAULT_DIGEST_MAX_TOKENS]
        assert raised and all(r["body"].get("stream") for r in raised)
    else:
        items = [item["params"]["max_tokens"]
                 for r in stub.requests if r["path"] == "/v1/messages/batches" and r["method"] == "POST"
                 for item in r["body"]["requests"]]
        assert max(items) > digest.DEFAULT_DIGEST_MAX_TOKENS          # the follow-up batch


def test_count_tokens_goes_to_the_plain_endpoint():
    from drawing_analyzer.core.tokenizer import count_tokens_via_api

    client, stub = _stub_client()
    assert count_tokens_via_api(model=OPUS, messages=_MSG, system=None, client=client) == 1
    [record] = stub.requests
    assert (record["path"], record["query"], record["beta"]) == ("/v1/messages/count_tokens", "", None)


# --------------------------------------------------------------------------- #
# The review's concrete case: a stage regressed to a plain create
# --------------------------------------------------------------------------- #


def _as_create(client, kwargs):
    return api.call_with_refusal_fallback(
        client, kwargs, model=str(kwargs.get("model", "")), method="create")


_STREAMED = {
    "digest": "drawing_analyzer.digest",
    "critique": "drawing_analyzer.critique",
    "review_plan": "drawing_analyzer.review_planner",
    "synthesis": "drawing_analyzer.synthesis",
    "focus": "drawing_analyzer.focus",
}


@pytest.mark.parametrize("stage", sorted(_STREAMED), ids=sorted(_STREAMED))
def test_a_streamed_stage_regressed_to_create_is_refused_by_the_real_sdk(tmp_path, monkeypatch, stage):
    import importlib

    monkeypatch.setattr(importlib.import_module(_STREAMED[stage]), "stream_message", _as_create)
    stub = AnthropicAPIStub(_script()._route)

    ctx = _run(tmp_path, stub)

    sent = assert_request_contract(stub)
    assert stage not in sent                      # refused before any request
    assert "Streaming is required" in json.dumps(
        [ctx.errors] + [s.errors + s.warnings for s in ctx.stage_results])
