"""The suite's fakes refuse what the installed SDK refuses (remediation WP-02.2, U26).

The fakes used to take any keyword on either namespace. Every plain
``create``/``stream`` accepted ``**kwargs``, ``_BetaMessagesProxy`` dropped
``betas``, 16 test-local sites popped ``betas``/``fallbacks``, and 13 batch
fakes took a ``betas`` the real ``client.messages.batches.create`` rejects. So
a request the SDK refuses before sending anything was green in CI. Measured on
SDK 1.7.0 and 1.8.0, over a transport that sends nothing:

- ``betas`` or ``fallbacks`` on ``client.messages.create``/``.stream``, and
  ``betas`` on ``client.messages.batches.create``, raise ``TypeError``;
- a non-streaming ``create`` above 21,333 ``max_tokens`` raises ``ValueError``
  ("Streaming is required ...") for every model the app registers.

The owner's rules for the fakes:

- a fake entry point accepts exactly the keywords the installed SDK method's
  signature lists (``inspect.signature``), and raises the SDK's own
  ``TypeError`` for any other;
- the non-streaming cap is derived from the SDK's public ``create`` once per
  model, never a literal and never its private helper;
- every fake production reaches routes through the one shared check in
  ``tests/fixtures/fake_anthropic.py``;
- a fake's plain and beta namespaces are separate entry points, each checked
  as its own namespace.

Production's own requests, sent through the real SDK, are
``tests/test_sdk_contract.py``.
"""
from __future__ import annotations

import ast
import functools
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import anthropic
import httpx2

from tests.fixtures import fake_anthropic as fa
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FinalMessageStream,
    StreamingMessagesMixin,
    add_stream,
)

OPUS = "claude-opus-5-5"
_REGISTERED = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-sonnet-5",
               "claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5")
_TESTS = Path(__file__).resolve().parent


# --------------------------------------------------------------------------- #
# The real SDK's answer, over a transport that sends nothing
# --------------------------------------------------------------------------- #


class _Sent(Exception):
    """The SDK reached the transport: it accepted the request."""


def _stop(request):
    raise _Sent


def _sdk_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="sk-ant-" + "strict-" + "0" * 20, max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(_stop)),
    )


def _outcome(call) -> tuple[str, str]:
    """(``"sent"`` | exception type name, its message) for one call."""
    try:
        call()
    except (_Sent, anthropic.APIConnectionError):
        return "sent", ""
    except (TypeError, ValueError) as exc:
        return type(exc).__name__, str(exc)
    return "sent", ""


def _sdk_outcome(namespace: str, method: str, kwargs: dict) -> tuple[str, str]:
    client = _sdk_client()
    target = client.beta.messages if namespace == "beta" else client.messages
    if method == "create":
        return _outcome(lambda: target.create(**kwargs))

    def _stream():
        with target.stream(**kwargs) as s:
            s.get_final_message()
    return _outcome(_stream)


# --------------------------------------------------------------------------- #
# Every kind of fake entry point the suite has
# --------------------------------------------------------------------------- #


def _reply(**_kw) -> FakeMessage:
    return FakeMessage(content=[FakeTextBlock(text="ok")])


class _Messages(StreamingMessagesMixin):
    def create(self, **kwargs):
        return _reply(**kwargs)


class _Unbound(StreamingMessagesMixin):
    @staticmethod
    def create(**kwargs):
        return _reply(**kwargs)


class _MixinClient(BetaClientMixin):
    def __init__(self):
        self.messages = _Messages()


def _stream_through(stream_fn, kwargs):
    with stream_fn(**kwargs) as s:
        return s.get_final_message()


def _split():
    """A test-local fake built the way the suite's hand-rolled fakes are."""
    messages, beta = fa.sdk_namespaces(
        create=lambda **kw: _reply(**kw),
        stream=lambda **kw: FinalMessageStream(_reply(**kw)),
    )
    return SimpleNamespace(messages=messages, beta=beta)


_ENTRIES = {
    # entry id: (namespace, method, call(kwargs))
    "mixin-plain-create": ("plain", "create", lambda kw: _Messages().create(**kw)),
    "mixin-plain-stream": ("plain", "stream", lambda kw: _stream_through(_Messages().stream, kw)),
    "mixin-unbound-create": ("plain", "create", lambda kw: _Unbound.create(**kw)),
    "mixin-unbound-stream": ("plain", "stream", lambda kw: _stream_through(_Unbound.stream, kw)),
    "add-stream-plain-stream": ("plain", "stream", lambda kw: _stream_through(
        add_stream(SimpleNamespace(create=lambda **k: _reply(**k))).stream, kw)),
    "proxy-beta-create": ("beta", "create", lambda kw: _MixinClient().beta.messages.create(**kw)),
    "proxy-beta-stream": ("beta", "stream", lambda kw: _stream_through(
        _MixinClient().beta.messages.stream, kw)),
    "split-plain-create": ("plain", "create", lambda kw: _split().messages.create(**kw)),
    "split-plain-stream": ("plain", "stream", lambda kw: _stream_through(_split().messages.stream, kw)),
    "split-beta-create": ("beta", "create", lambda kw: _split().beta.messages.create(**kw)),
    "split-beta-stream": ("beta", "stream", lambda kw: _stream_through(_split().beta.messages.stream, kw)),
}

_BASE = {"model": OPUS, "messages": [{"role": "user", "content": "x"}]}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


@functools.lru_cache(maxsize=None)
def _cap(model: str = OPUS) -> int:
    """The SDK's cap, found here without the fixture's helper (so a fixture that
    derived it wrongly cannot also define what "right" is)."""
    client = _sdk_client()
    lo, hi = 1, 1 << 20
    while lo < hi:
        mid = (lo + hi + 1) // 2
        kind, _ = _outcome(lambda: client.messages.create(
            model=model, max_tokens=mid, messages=_BASE["messages"]))
        if kind == "sent":
            lo = mid
        else:
            hi = mid - 1
    return lo


_CASES = {
    "legal": lambda: {**_BASE, "max_tokens": 16},
    "betas": lambda: {**_BASE, "max_tokens": 16, "betas": [_FALLBACK_BETA]},
    "fallbacks": lambda: {**_BASE, "max_tokens": 16, "fallbacks": "default"},
    "betas-and-fallbacks": lambda: {**_BASE, "max_tokens": 16, "betas": [_FALLBACK_BETA],
                                    "fallbacks": "default"},
    "unknown-temperature": lambda: {**_BASE, "max_tokens": 16, "temperature": 0},
    "at-the-cap": lambda: {**_BASE, "max_tokens": _cap()},
    "one-above-the-cap": lambda: {**_BASE, "max_tokens": _cap() + 1},
    "64k": lambda: {**_BASE, "max_tokens": 64_000},
    "64k-with-own-timeout": lambda: {**_BASE, "max_tokens": 64_000, "timeout": 900},
}


@pytest.mark.parametrize("case", sorted(_CASES), ids=sorted(_CASES))
@pytest.mark.parametrize("entry", sorted(_ENTRIES), ids=sorted(_ENTRIES))
def test_a_fake_refuses_exactly_what_the_sdk_refuses(entry, case):
    namespace, method, call = _ENTRIES[entry]
    kwargs = _CASES[case]()
    expected = _sdk_outcome(namespace, method, dict(kwargs))

    got = _outcome(lambda: call(dict(kwargs)))

    assert got == expected, (entry, case)


def test_the_table_covers_every_refusal_it_names():
    # Non-vacuous: the table above holds both kinds of refusal on the plain
    # namespace, and acceptance of the same keywords on the beta namespace.
    plain = {c: _sdk_outcome("plain", "create", _CASES[c]())[0] for c in _CASES}
    beta = {c: _sdk_outcome("beta", "create", _CASES[c]())[0] for c in _CASES}
    assert plain["betas"] == plain["fallbacks"] == "TypeError"
    assert beta["betas"] == beta["fallbacks"] == beta["betas-and-fallbacks"] == "sent"
    assert plain["one-above-the-cap"] == beta["one-above-the-cap"] == "ValueError"
    assert plain["64k-with-own-timeout"] == "sent"      # the SDK's own escape
    assert plain["unknown-temperature"] == beta["unknown-temperature"] == "TypeError"


# --------------------------------------------------------------------------- #
# The cap is the SDK's, per model
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model", _REGISTERED + ("claude-unregistered-9",),
                         ids=list(_REGISTERED) + ["unregistered"])
def test_the_fake_cap_is_the_sdks_for_every_model(model):
    assert fa.sdk_nonstreaming_limit(model) == _cap(model)


def test_the_fake_cap_refusal_is_the_sdks_own_message():
    kwargs = {**_BASE, "max_tokens": fa.sdk_nonstreaming_limit(OPUS) + 1}
    expected = _sdk_outcome("plain", "create", dict(kwargs))
    with pytest.raises(ValueError) as caught:
        fa.check_sdk_request("plain", "create", dict(kwargs))
    assert (type(caught.value).__name__, str(caught.value)) == expected


def test_the_fake_keywords_are_the_sdks_signatures():
    import inspect

    from anthropic.resources.beta.messages.messages import Messages as Beta
    from anthropic.resources.messages.batches import Batches
    from anthropic.resources.messages.messages import Messages as Plain

    def names(fn):
        return frozenset(inspect.signature(fn).parameters) - {"self"}

    assert fa.SDK_KEYWORDS == {
        ("plain", "create"): names(Plain.create),
        ("plain", "stream"): names(Plain.stream),
        ("beta", "create"): names(Beta.create),
        ("beta", "stream"): names(Beta.stream),
        ("plain", "batches.create"): names(Batches.create),
    }
    assert {"betas", "fallbacks"} <= fa.SDK_KEYWORDS[("beta", "create")]
    assert not {"betas", "fallbacks"} & fa.SDK_KEYWORDS[("plain", "create")]


def test_a_batch_create_with_betas_is_refused_like_the_sdk():
    client = _sdk_client()
    expected = _outcome(lambda: client.messages.batches.create(requests=[], betas=["x"]))
    with pytest.raises(TypeError) as caught:
        fa.check_sdk_request("plain", "batches.create", {"requests": [], "betas": ["x"]})
    assert ("TypeError", str(caught.value)) == expected


# --------------------------------------------------------------------------- #
# A regressed stage fails in the suite (the review's concrete case)
# --------------------------------------------------------------------------- #


pymupdf = pytest.importorskip("pymupdf")

import drawing_analyzer.batch_digest as BD  # noqa: E402
import drawing_analyzer.core.api_config as api  # noqa: E402
import drawing_analyzer.pipeline as pl  # noqa: E402
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from tests.fixtures.gauntlet import build_mini_set, mini_client  # noqa: E402


@pytest.fixture(autouse=True)
def _latches(monkeypatch):
    monkeypatch.setattr(api, "_refusal_fallback_available", True)
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    monkeypatch.setattr(BD, "_run_in_background", lambda fn: fn())


def _run(tmp_path, client, **kwargs):
    work = tmp_path / "work"
    work.mkdir()
    return pl.extract_drawing_context(
        build_mini_set(tmp_path), client=client, rows=2, cols=2,
        cache=DigestCache(tmp_path / "cache.sqlite"), synthesize=True,
        focus="equipment coordination", qc_markups=True, qc_work_dir=work,
        **kwargs,
    )


def _as_create(client, kwargs):
    """``stream_message`` regressed to a plain, non-streaming ``create``."""
    return api.call_with_refusal_fallback(
        client, kwargs, model=str(kwargs.get("model", "")), method="create")


# stage -> (module that calls stream_message, its stage record). Each asks for
# 32,000-64,000 tokens, above the cap; the investigation's 16,000 is not, so a
# plain create there is a request the SDK accepts.
_STREAMED = {
    "digest": ("drawing_analyzer.digest", "digest"),
    "critique": ("drawing_analyzer.critique", "critique"),
    "review-plan": ("drawing_analyzer.review_planner", "review_plan"),
    "synthesis": ("drawing_analyzer.synthesis", "synthesis"),
    "focus": ("drawing_analyzer.focus", None),
}


def _stage_text(ctx, stage):
    rec = next((s for s in ctx.stage_results if s.stage == stage), None)
    return " ".join((rec.errors + rec.warnings) if rec else []) + " ".join(ctx.errors)


@pytest.mark.parametrize("stage", sorted(_STREAMED), ids=sorted(_STREAMED))
def test_a_streamed_stage_regressed_to_create_fails_in_the_fakes(tmp_path, monkeypatch, stage):
    import importlib

    module, record = _STREAMED[stage]
    monkeypatch.setattr(importlib.import_module(module), "stream_message", _as_create)

    ctx = _run(tmp_path, mini_client(), use_batch=False, critique_use_batch=False)

    # The focus report has no stage record of its own; its failure is a run error.
    text = _stage_text(ctx, record) if record else " ".join(ctx.errors)
    assert "Streaming is required" in text, (stage, text[:400])
    if record:
        rec = next(s for s in ctx.stage_results if s.stage == record)
        assert rec.status != "COMPLETE"


def test_the_same_run_unregressed_completes(tmp_path):
    # Control for the table above: the scripted client answers every stage.
    ctx = _run(tmp_path, mini_client(), use_batch=False, critique_use_batch=False)
    assert ctx.qc_status == "COMPLETE", {s.stage: s.status for s in ctx.stage_results}
    assert not [e for e in ctx.errors if "Streaming is required" in e]


def test_betas_on_the_plain_namespace_fail_in_the_fakes(tmp_path, monkeypatch):
    # ``messages_namespace`` regressed to always pick ``client.messages``: every
    # Opus 5 request then carries ``betas``/``fallbacks`` on the plain namespace.
    monkeypatch.setattr(api, "messages_namespace", lambda client, kwargs: client.messages)

    ctx = _run(tmp_path, mini_client(), use_batch=False, critique_use_batch=False)

    assert "unexpected keyword argument 'betas'" in " ".join(ctx.errors)
    digest = next(s for s in ctx.stage_results if s.stage == "digest")
    assert digest.status == "FAILED"


def test_an_unknown_keyword_fails_in_the_fakes(tmp_path, monkeypatch):
    # A request builder that grows a keyword the SDK method does not take.
    real = api._dispatch_messages

    def _with_temperature(client, kwargs, method):
        return real(client, {**kwargs, "temperature": 0}, method)

    monkeypatch.setattr(api, "_dispatch_messages", _with_temperature)

    ctx = _run(tmp_path, mini_client(), use_batch=False, critique_use_batch=False)

    assert "unexpected keyword argument 'temperature'" in " ".join(ctx.errors)


def test_betas_on_a_plain_batch_create_fail_in_the_fakes(tmp_path, monkeypatch):
    from tests.test_source_page_isolation import _Pipe

    pipe = _Pipe()
    real_create = pipe.messages.batches.create
    raised: list[BaseException] = []

    def _submit_with_betas(*, requests, **kwargs):
        # A submit that grew the extended-output beta on the plain namespace.
        try:
            return real_create(requests=requests, betas=["output-300k-2026-03-24"], **kwargs)
        except BaseException as exc:
            raised.append(exc)
            raise

    pipe.messages.batches.create = _submit_with_betas

    ctx = _run(tmp_path, pipe, use_batch=True, critique_use_batch=False)

    assert [(type(e).__name__, str(e)) for e in raised] == [
        ("TypeError", "Batches.create() got an unexpected keyword argument 'betas'")]
    # The digest phase stops on it (WP-11.2 names the type only).
    assert _stage_text(ctx, "digest").count("(TypeError)") >= 1
    assert next(s for s in ctx.stage_results if s.stage == "digest").status == "FAILED"


# --------------------------------------------------------------------------- #
# No fake strips what the SDK would refuse (structural)
# --------------------------------------------------------------------------- #


def _test_sources():
    for path in sorted(_TESTS.rglob("*.py")):
        if path.name in {"fake_anthropic.py", "test_strict_fakes.py"}:
            continue
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_test_fake_drops_betas_or_fallbacks():
    """A fake that pops ``betas``/``fallbacks`` accepts on the plain namespace
    what the SDK refuses; the one place that may strip the ``betas`` header
    from a beta call's body is ``fake_anthropic``'s checked beta entry."""
    offenders = []
    for path, tree in _test_sources():
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "pop"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in ("betas", "fallbacks")
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_no_test_fake_accepts_a_betas_parameter():
    """``client.messages.batches.create`` and ``client.messages.stream`` take no
    ``betas``; a fake with a ``betas`` parameter accepts what the SDK refuses."""
    offenders = []
    for path, tree in _test_sources():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.Lambda)):
                args = node.args
                names = [a.arg for a in args.args + args.kwonlyargs + args.posonlyargs]
                if "betas" in names:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def _decorator_names(node) -> set[str]:
    names = set()
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
    return names


def test_every_batch_create_fake_is_sdk_checked():
    """A fake ``messages.batches.create`` (a function taking a keyword-only
    ``requests``) goes through the shared check, in the tests and in the
    benchmark script's fakes alike. Production submits at four sites, so
    this is a scan rather than the dispatch guard below."""
    sources = list(_test_sources())
    for path in sorted((_TESTS.parent / "scripts").glob("*.py")):
        sources.append((path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))))
    fakes, unchecked = [], []
    for path, tree in sources:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and "requests" in [a.arg for a in node.args.kwonlyargs]:
                fakes.append(f"{path.name}:{node.lineno}")
                if "checked_batch_create" not in _decorator_names(node):
                    unchecked.append(f"{path.name}:{node.lineno}")
    assert len(fakes) >= 14                          # the scan sees the batch fakes
    assert unchecked == []


# --------------------------------------------------------------------------- #
# The guard: production never reaches an unchecked Messages fake
# --------------------------------------------------------------------------- #


class _Unchecked:
    """The shape Codex's review found: a fake ``create`` taking ``**kwargs``."""

    def create(self, **kwargs):
        return _reply(**kwargs)


def _send(client, **extra):
    return api.call_with_refusal_fallback(
        client, {"model": "claude-sonnet-5", "max_tokens": 16, "messages": _BASE["messages"],
                 **extra},
        model="claude-sonnet-5", method="create",
    )


def test_the_guard_records_an_unchecked_fake_production_reaches(sdk_checked_guard):
    # The unchecked fake takes a keyword the SDK refuses; only the guard sees it.
    _send(SimpleNamespace(messages=_Unchecked()), temperature=0)

    assert sdk_checked_guard == ["plain.create -> _Unchecked.create"]
    sdk_checked_guard.clear()          # deliberate: this test's own finding


def test_the_guard_passes_a_checked_fake_and_the_real_sdk(sdk_checked_guard):
    checked = SimpleNamespace(messages=SimpleNamespace(
        create=fa.checked_entry("plain", "create", _Unchecked().create)))
    _send(checked)
    with pytest.raises(TypeError, match="unexpected keyword argument 'temperature'"):
        _send(checked, temperature=0)

    from tests.fixtures.sdk_transport import AnthropicAPIStub

    stub = AnthropicAPIStub(lambda params: _reply())
    _send(stub.client())
    assert [r["path"] for r in stub.requests] == ["/v1/messages"]
    assert sdk_checked_guard == []


def test_the_guard_leaves_a_missing_namespace_to_production(sdk_checked_guard):
    # A fake with no beta namespace fails in production with AttributeError;
    # that is the test's subject, not an unchecked entry.
    with pytest.raises(AttributeError):
        api.call_with_refusal_fallback(
            SimpleNamespace(messages=_Messages()),
            {"model": OPUS, "max_tokens": 16, "messages": _BASE["messages"]},
            model=OPUS, method="create",
        )
    assert sdk_checked_guard == []


def test_the_structural_scans_see_the_suite():
    # Non-vacuous: the scans read the files that hold the suite's fakes.
    names = {path.name for path, _ in _test_sources()}
    assert {"test_drawing_batch.py", "test_source_page_isolation.py",
            "test_critique_terminal_outcome.py", "test_digest_partial_reads.py"} <= names
    assert json.dumps(sorted(names))  # a list the failure message can print
