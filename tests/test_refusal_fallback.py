"""Opus 5 refusal-fallback tests (``core/api_config.py``).

Claude Opus 5's elevated safety classifiers can decline a request outright
(``stop_reason="refusal"``); every real-time (non-batch) Opus 5 call in this
app opts into the server-side ``fallbacks: "default"`` recovery via
:func:`~drawing_analyzer.core.api_config.call_with_refusal_fallback`. These
tests exercise the policy in isolation — attach-only-for-Opus-5, the beta
merge, the env kill switch, and the self-healing latch (mirrors the
investigation loop's own ``_task_budget_available`` pattern) — with a small
fake client, hermetic per I-4.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from drawing_analyzer.core import api_config as api

OPUS_5 = "claude-opus-5"
OPUS_48 = "claude-opus-4-8"
SONNET_5 = "claude-sonnet-5"


@pytest.fixture(autouse=True)
def _reset_latch():
    """The self-healing latch is process-wide state; never leak it across tests."""
    api._refusal_fallback_available = True
    yield
    api._refusal_fallback_available = True


# --------------------------------------------------------------------------- #
# apply_refusal_fallback
# --------------------------------------------------------------------------- #


def test_attaches_beta_and_param_for_opus_5():
    kwargs = {"model": OPUS_5, "max_tokens": 1024, "messages": []}
    out = api.apply_refusal_fallback(kwargs, model=OPUS_5)
    assert out["betas"] == [api.REFUSAL_FALLBACK_BETA]
    assert out["fallbacks"] == "default"
    assert kwargs == {"model": OPUS_5, "max_tokens": 1024, "messages": []}  # not mutated


@pytest.mark.parametrize("model", [SONNET_5, OPUS_48, "claude-haiku-4-5", ""])
def test_untouched_for_every_model_but_opus_5(model):
    kwargs = {"model": model, "max_tokens": 1024}
    out = api.apply_refusal_fallback(kwargs, model=model)
    assert out is kwargs  # same object: no betas/fallbacks attached
    assert "betas" not in out and "fallbacks" not in out


def test_merges_into_an_existing_betas_list():
    kwargs = {"model": OPUS_5, "betas": ["task-budgets-2026-03-13"]}
    out = api.apply_refusal_fallback(kwargs, model=OPUS_5)
    assert out["betas"] == ["task-budgets-2026-03-13", api.REFUSAL_FALLBACK_BETA]


def test_idempotent_if_the_beta_is_already_present():
    kwargs = {"model": OPUS_5, "betas": [api.REFUSAL_FALLBACK_BETA]}
    out = api.apply_refusal_fallback(kwargs, model=OPUS_5)
    assert out["betas"] == [api.REFUSAL_FALLBACK_BETA]


def test_env_kill_switch_disables_the_feature(monkeypatch):
    monkeypatch.setenv(api.ENV_REFUSAL_FALLBACK, "0")
    kwargs = {"model": OPUS_5}
    out = api.apply_refusal_fallback(kwargs, model=OPUS_5)
    assert out is kwargs


def test_latched_off_disables_the_feature():
    api._refusal_fallback_available = False
    kwargs = {"model": OPUS_5}
    out = api.apply_refusal_fallback(kwargs, model=OPUS_5)
    assert out is kwargs


# --------------------------------------------------------------------------- #
# messages_namespace
# --------------------------------------------------------------------------- #


def test_messages_namespace_picks_beta_only_when_betas_present():
    client = SimpleNamespace(messages="plain", beta=SimpleNamespace(messages="beta"))
    assert api.messages_namespace(client, {"model": SONNET_5}) == "plain"
    assert api.messages_namespace(client, {"model": OPUS_5, "betas": [api.REFUSAL_FALLBACK_BETA]}) == "beta"


# --------------------------------------------------------------------------- #
# call_with_refusal_fallback
# --------------------------------------------------------------------------- #


class _Rejected(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class _FakeClient:
    """Records every ``create``/``stream`` call on both namespaces."""

    def __init__(self, *, beta_raises: Exception | None = None):
        self.plain_calls: list[dict] = []
        self.beta_calls: list[dict] = []
        self._beta_raises = beta_raises
        self.messages = SimpleNamespace(create=self._plain_create, stream=self._plain_stream)
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(create=self._beta_create, stream=self._beta_stream)
        )

    def _plain_create(self, **kw):
        self.plain_calls.append(kw)
        return SimpleNamespace(content=[], model=kw.get("model"))

    def _plain_stream(self, **kw):
        return _Stream(self._plain_create(**kw))

    def _beta_create(self, **kw):
        if self._beta_raises is not None:
            raise self._beta_raises
        self.beta_calls.append(kw)
        return SimpleNamespace(content=[], model=kw.get("model"))

    def _beta_stream(self, **kw):
        return _Stream(self._beta_create(**kw))


class _Stream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


def test_opus_5_create_routes_through_the_beta_namespace_with_fallback():
    client = _FakeClient()
    resp = api.call_with_refusal_fallback(
        client, {"model": OPUS_5, "max_tokens": 10}, model=OPUS_5, method="create"
    )
    assert client.plain_calls == []
    assert len(client.beta_calls) == 1
    assert client.beta_calls[0]["fallbacks"] == "default"
    assert client.beta_calls[0]["betas"] == [api.REFUSAL_FALLBACK_BETA]
    assert resp.model == OPUS_5


def test_opus_5_stream_routes_through_the_beta_namespace_with_fallback():
    client = _FakeClient()
    resp = api.call_with_refusal_fallback(
        client, {"model": OPUS_5, "max_tokens": 10}, model=OPUS_5, method="stream"
    )
    assert len(client.beta_calls) == 1 and client.plain_calls == []
    assert resp.model == OPUS_5


def test_sonnet_5_never_touches_the_beta_namespace():
    client = _FakeClient()
    api.call_with_refusal_fallback(
        client, {"model": SONNET_5, "max_tokens": 10}, model=SONNET_5, method="create"
    )
    assert client.beta_calls == []
    assert len(client.plain_calls) == 1
    assert "betas" not in client.plain_calls[0] and "fallbacks" not in client.plain_calls[0]


def test_fallback_rejection_self_heals_and_latches_off_for_the_process():
    """A platform without the beta enabled must not permanently break every
    subsequent Opus 5 call (digest/critique/verify/investigate are core
    deliverables, not optional QC add-ons)."""
    client = _FakeClient(
        beta_raises=_Rejected(400, "invalid_request_error: beta header 'server-side-fallback-2026-07-01' is not supported")
    )
    resp = api.call_with_refusal_fallback(
        client, {"model": OPUS_5, "max_tokens": 10}, model=OPUS_5, method="create"
    )
    # Recovered on the plain transport, no betas/fallbacks leaked into it.
    assert len(client.plain_calls) == 1
    assert "betas" not in client.plain_calls[0] and "fallbacks" not in client.plain_calls[0]
    assert resp.model == OPUS_5
    assert api._refusal_fallback_available is False

    # The next Opus 5 call in this process skips the beta namespace entirely —
    # no repeated 400s.
    client2 = _FakeClient()
    api.call_with_refusal_fallback(
        client2, {"model": OPUS_5, "max_tokens": 10}, model=OPUS_5, method="create"
    )
    assert client2.beta_calls == [] and len(client2.plain_calls) == 1


def test_unrelated_400_is_not_mistaken_for_a_fallback_rejection():
    client = _FakeClient(beta_raises=_Rejected(400, "invalid_request_error: max_tokens must be positive"))
    with pytest.raises(_Rejected):
        api.call_with_refusal_fallback(
            client, {"model": OPUS_5, "max_tokens": 10}, model=OPUS_5, method="create"
        )
    # Not latched off — this 400 had nothing to do with the fallback beta.
    assert api._refusal_fallback_available is True


def test_transient_error_propagates_without_being_swallowed():
    client = _FakeClient(beta_raises=_Rejected(529, "overloaded_error"))
    with pytest.raises(_Rejected):
        api.call_with_refusal_fallback(
            client, {"model": OPUS_5, "max_tokens": 10}, model=OPUS_5, method="create"
        )
    assert api._refusal_fallback_available is True
