"""Fake Anthropic response builders for hermetic tests.

The production parsers in ``src.reviewer``,
``src.batch``, and ``src.verifier`` consume objects that look like the
Anthropic SDK's Pydantic models — attribute access for ``content``,
``stop_reason``, ``usage``, ``content[i].type``, ``content[i].name``,
``content[i].input``, etc. The tagged-JSON / batch paths also accept plain
dicts. These builders return objects that satisfy both shapes so a single
fixture exercises both code paths.

Builders only emit data; they never hit the network. Pair them with a
``MagicMock``-style monkeypatch on ``messages.stream`` /
``messages.batches.results`` in tests that want to exercise the full
reviewer/verifier flow.

What's covered (five cases):

1. ``review_tool_use_response`` — structured ``submit_review_findings`` tool call.
2. ``verification_tool_use_response`` — structured ``submit_verification_verdict`` tool call.
3. ``verification_tool_use_response`` — stop_reason ``tool_use`` (same call; see
   ``stop_reason`` kwarg) so callers can simulate the tool-use stop path.
4. ``verification_text_fallback_response`` — JSON-in-text fallback (no tool block).
5. ``max_tokens_incomplete_response`` — stop_reason ``max_tokens`` with partial text.

Each builder also supports a ``dict_shape`` flag so tests can exercise the
plain-dict code paths (batch retrieval can return either form).
"""
from __future__ import annotations

import contextvars
import functools
import inspect
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
from anthropic.resources.beta.messages.messages import Messages as _SdkBetaMessages
from anthropic.resources.messages.batches import Batches as _SdkBatches
from anthropic.resources.messages.messages import Messages as _SdkMessages


# ---------------------------------------------------------------------------
# Attribute-accessible stand-ins for SDK Pydantic models.
# ---------------------------------------------------------------------------


@dataclass
class FakeServerToolUse:
    """Mimic ``usage.server_tool_use`` (server-reported tool telemetry)."""

    web_search_requests: int = 0


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # Present only when the response carried server tool telemetry — ``None``
    # mimics the SDK shapes that omit it (readers must treat that as unknown).
    server_tool_use: Any = None


@dataclass
class FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    name: str
    input: dict[str, Any]
    id: str = "toolu_fake_1"
    type: str = "tool_use"


@dataclass
class FakeWebSearchResultBlock:
    """Mimic the ``web_search_tool_result`` block shape used by the SDK."""
    tool_use_id: str = "srvtoolu_fake_1"
    content: list[dict[str, Any]] = field(default_factory=list)
    type: str = "web_search_tool_result"


@dataclass
class FakeServerToolUseBlock:
    """A server-side tool invocation (e.g. ``web_search``)."""
    name: str
    input: dict[str, Any]
    id: str = "srvtoolu_fake_1"
    type: str = "server_tool_use"


@dataclass
class FakeMessage:
    """SDK-ish Message: attribute access on ``content``, ``stop_reason``, ``usage``."""
    content: list[Any]
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)
    model: str = "claude-opus-5"
    id: str = "msg_fake_1"
    role: str = "assistant"
    type: str = "message"
    stop_sequence: str | None = None


# ---------------------------------------------------------------------------
# Canonical structured payloads (validate against schemas in tests).
# ---------------------------------------------------------------------------


def sample_review_findings_payload() -> dict[str, Any]:
    """Return a structured payload that matches ``REVIEW_FINDINGS_SCHEMA``.

    All schema-required keys are present so strict-mode validation passes.
    """
    return {
        "analysis_summary": "Reviewed Section 23 21 13. One stale code reference found.",
        "findings": [
            {
                "severity": "HIGH",
                "fileName": "23 21 13 - Hydronic.docx",
                "section": "2.1",
                "issue": "Cited California Plumbing Code edition is outdated for the 2025 cycle.",
                "actionType": "EDIT",
                "existingText": "per CPC 2022",
                "replacementText": "per CPC 2025",
                "codeReference": "CPC 2025",
                "confidence": 0.85,
                "anchorText": None,
                "insertPosition": None,
                # The schema now requires evidenceElementId on
                # every finding (nullable). Fixture findings cite an id
                # so request-shape tests cover the populated path.
                "evidenceElementId": "p17",
            }
        ],
    }


def sample_verification_verdict_payload(
    *,
    verdict: str = "CONFIRMED",
    grounded_sources: list[str] | None = None,
    source_quote: str | None = None,
) -> dict[str, Any]:
    """Return a structured payload that matches ``VERIFICATION_VERDICT_SCHEMA``.

    ``source_quote`` is a required-but-nullable
    schema field; for CONFIRMED / CORRECTED verdicts the verifier demotes
    empty quotes to UNVERIFIED at parse time, so this fixture defaults to
    a non-empty snippet to keep grounded test paths grounded.
    """
    if grounded_sources is None:
        grounded_sources = ["https://www.dgs.ca.gov/DSA/"]
    if source_quote is None:
        source_quote = (
            "The 2025 California Plumbing Code took effect on January 1, "
            "2026, per the California Building Standards Commission's "
            "adoption matrix."
        )
    return {
        "verdict": verdict,
        "explanation": "The 2025 California Plumbing Code is the current cycle per DSA.",
        "sources": grounded_sources,
        "correction": None,
        "source_quote": source_quote,
    }


# ---------------------------------------------------------------------------
# Response builders (case 1 – case 5).
# ---------------------------------------------------------------------------


def _maybe_dict(message: FakeMessage, *, dict_shape: bool) -> Any:
    if not dict_shape:
        return message
    return _to_dict(message)


def review_tool_use_response(
    *,
    payload: dict[str, Any] | None = None,
    stop_reason: str = "tool_use",
    dict_shape: bool = False,
    include_thinking_text: bool = False,
) -> Any:
    """Case 1: a successful structured ``submit_review_findings`` tool call.

    Mirrors the streaming + batch happy-path: a ``tool_use`` block whose
    ``input`` is the structured review payload, optionally preceded by a
    short text block (the model's pre-tool prose).
    """
    payload = payload if payload is not None else sample_review_findings_payload()
    content: list[Any] = []
    if include_thinking_text:
        content.append(FakeTextBlock(text="Reviewing the spec for code-cycle staleness..."))
    content.append(
        FakeToolUseBlock(name="submit_review_findings", input=dict(payload))
    )
    return _maybe_dict(
        FakeMessage(content=content, stop_reason=stop_reason), dict_shape=dict_shape
    )


def verification_tool_use_response(
    *,
    payload: dict[str, Any] | None = None,
    stop_reason: str = "tool_use",
    include_web_search_blocks: bool = True,
    dict_shape: bool = False,
) -> Any:
    """Cases 2 + 3: a structured ``submit_verification_verdict`` tool call.

    Defaults to ``stop_reason="tool_use"`` so this single builder also
    covers case 3 ("a verification response that stops
    with tool use"). Set ``stop_reason="end_turn"`` for the legacy path.

    When ``include_web_search_blocks=True`` (the default), the response
    also carries a ``server_tool_use`` block and a ``web_search_tool_result``
    block so grounding-detection helpers in ``verifier.py`` have something
    to match against.
    """
    payload = payload if payload is not None else sample_verification_verdict_payload()
    content: list[Any] = []
    if include_web_search_blocks:
        content.append(
            FakeServerToolUseBlock(
                name="web_search",
                input={"query": "California Plumbing Code 2025 effective date"},
            )
        )
        content.append(
            FakeWebSearchResultBlock(
                content=[
                    {
                        "type": "web_search_result",
                        "url": "https://www.dgs.ca.gov/DSA/",
                        "title": "DSA — California Code Adoptions",
                        "encrypted_content": "fake-encrypted-blob",
                    }
                ]
            )
        )
    content.append(
        FakeToolUseBlock(
            name="submit_verification_verdict", input=dict(payload)
        )
    )
    return _maybe_dict(
        FakeMessage(content=content, stop_reason=stop_reason), dict_shape=dict_shape
    )


def verification_text_fallback_response(
    *,
    payload: dict[str, Any] | None = None,
    stop_reason: str = "end_turn",
    dict_shape: bool = False,
) -> Any:
    """Case 4: a verification response that falls back to plain JSON text.

    No tool_use block — parsers must drop to ``_parse_verification_response``
    and pull the verdict out of the assistant text.
    """
    payload = payload if payload is not None else sample_verification_verdict_payload()
    body = json.dumps(payload)
    content: list[Any] = [FakeTextBlock(text=body)]
    return _maybe_dict(
        FakeMessage(content=content, stop_reason=stop_reason), dict_shape=dict_shape
    )


def max_tokens_incomplete_response(
    *,
    partial_text: str = "Reviewing… (output truncated mid-sentence",
    dict_shape: bool = False,
) -> Any:
    """Case 5: a response truncated by ``max_tokens``.

    The reviewer / batch retrieve paths treat any ``stop_reason`` other
    than ``end_turn`` or ``tool_use`` as incomplete; this fixture lets
    tests assert that the parse_status correctly degrades to ``incomplete``.
    """
    content: list[Any] = [FakeTextBlock(text=partial_text)]
    return _maybe_dict(
        FakeMessage(content=content, stop_reason="max_tokens"), dict_shape=dict_shape
    )


# ---------------------------------------------------------------------------
# Batch-result wrappers
# ---------------------------------------------------------------------------


@dataclass
class FakeBatchResultEnvelope:
    """Mimic the ``BatchResult.result`` inner type the SDK returns."""
    type: str = "succeeded"  # or "errored" / "expired" / "canceled"
    message: Any = None
    error: Any = None


@dataclass
class FakeBatchResult:
    """Mimic the outer batch result the SDK iterator yields."""
    custom_id: str
    result: FakeBatchResultEnvelope


def batch_review_result(
    custom_id: str = "review__SPEC__0",
    *,
    message: Any | None = None,
) -> FakeBatchResult:
    """Wrap a fake review response in a batch-result envelope."""
    if message is None:
        message = review_tool_use_response()
    return FakeBatchResult(
        custom_id=custom_id,
        result=FakeBatchResultEnvelope(type="succeeded", message=message),
    )


def batch_verification_result(
    custom_id: str = "verify__0",
    *,
    message: Any | None = None,
) -> FakeBatchResult:
    """Wrap a fake verification response in a batch-result envelope."""
    if message is None:
        message = verification_tool_use_response()
    return FakeBatchResult(
        custom_id=custom_id,
        result=FakeBatchResultEnvelope(type="succeeded", message=message),
    )


def batch_errored_result(
    custom_id: str = "review__SPEC__0",
    *,
    error_message: str = "fake error",
) -> FakeBatchResult:
    """Errored-request envelope, for failure-path tests."""
    error_obj = type("FakeError", (), {"message": error_message, "type": "api_error"})()
    return FakeBatchResult(
        custom_id=custom_id,
        result=FakeBatchResultEnvelope(type="errored", error=error_obj),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_dict(obj: Any) -> Any:
    """Recursively convert FakeMessage/etc into plain dicts (with no None keys for type)."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        out: dict[str, Any] = {}
        for field_name in obj.__dataclass_fields__:
            out[field_name] = _to_dict(getattr(obj, field_name))
        return out
    return obj


# ---------------------------------------------------------------------------
# The SDK's request contract (remediation WP-02.2, U26)
# ---------------------------------------------------------------------------
#
# The fakes used to take any keyword on either namespace: every plain
# ``create``/``stream`` accepted ``**kwargs``, ``_BetaMessagesProxy`` dropped
# ``betas``, and test-local fakes popped ``betas``/``fallbacks`` or took a
# ``betas`` parameter. So a request the installed SDK refuses before sending
# anything was green here. Measured on SDK 1.7.0 and 1.8.0, over a transport
# that sends nothing:
#
# - ``client.messages.create``/``.stream`` with ``betas`` or ``fallbacks``, and
#   ``client.messages.batches.create`` with ``betas``, raise ``TypeError``;
# - a non-streaming ``create`` above 21,333 ``max_tokens`` raises
#   ``ValueError`` ("Streaming is required ...") for every registered model, on
#   both namespaces (the SDK skips that check when the call passes its own
#   ``timeout``).
#
# Every fake entry point asks :func:`check_sdk_request` first, so a fake refuses
# exactly what the installed SDK refuses, with the SDK's own exception and
# message (the owner's rules, WP-02.2):
#
# - the keyword rule is the SDK method's signature (``inspect``), so a keyword
#   the SDK adds or drops moves the fakes with it;
# - the cap is derived from the SDK's public ``create`` once per model
#   (:func:`sdk_nonstreaming_limit`), never a literal or its private helper;
# - a fake's plain and beta namespaces are separate entry points, each checked
#   as its own namespace (:func:`sdk_namespaces` for a test-local fake; the
#   mixins below for the rest).
#
# ``tests/test_strict_fakes.py`` holds the fakes to the real SDK case by case;
# ``tests/test_sdk_contract.py`` sends production's own requests through it.

PLAIN = "plain"
BETA = "beta"


def _sdk_keywords(method: Any) -> frozenset[str]:
    return frozenset(inspect.signature(method).parameters) - {"self"}


#: ``(namespace, method)`` -> the keywords the installed SDK method accepts.
SDK_KEYWORDS: dict[tuple[str, str], frozenset[str]] = {
    (PLAIN, "create"): _sdk_keywords(_SdkMessages.create),
    (PLAIN, "stream"): _sdk_keywords(_SdkMessages.stream),
    (BETA, "create"): _sdk_keywords(_SdkBetaMessages.create),
    (BETA, "stream"): _sdk_keywords(_SdkBetaMessages.stream),
    (PLAIN, "batches.create"): _sdk_keywords(_SdkBatches.create),
}
# The class the SDK's own TypeError names ("Messages.create() got ...").
_SDK_OWNER = {"create": "Messages.create", "stream": "Messages.stream",
              "batches.create": "Batches.create"}


class _NotSent(Exception):
    """Raised by the probe transport: the SDK accepted the request."""


def _refuse_to_send(request: Any) -> Any:
    raise _NotSent


@functools.lru_cache(maxsize=None)
def _probe_client() -> Any:
    return anthropic.Anthropic(
        api_key="sk-ant-" + "probe-" + "0" * 20,   # built at runtime: not a key
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(_refuse_to_send)),
    )


def _sdk_refusal(model: str, max_tokens: int) -> str | None:
    """The SDK's refusal message for a non-streaming create, or ``None``."""
    try:
        _probe_client().messages.create(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": "x"}],
        )
    except ValueError as exc:
        return str(exc)
    except anthropic.APIConnectionError:
        return None                      # it reached the transport: accepted
    return None


@functools.lru_cache(maxsize=None)
def _sdk_cap(model: str) -> tuple[int, str]:
    lo, hi = 1, 1 << 20
    if _sdk_refusal(model, hi) is None:
        return hi, ""
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _sdk_refusal(model, mid) is None:
            lo = mid
        else:
            hi = mid - 1
    return lo, _sdk_refusal(model, lo + 1) or ""


def sdk_nonstreaming_limit(model: str) -> int:
    """The largest non-streaming ``max_tokens`` the installed SDK sends for
    ``model``: found once per model by asking the SDK's public ``create``
    (a bisection over a transport that sends nothing)."""
    return _sdk_cap(model)[0]


def check_sdk_request(namespace: str, method: str, kwargs: dict[str, Any]) -> None:
    """Raise what the installed SDK raises for this call before sending it.

    ``TypeError`` for a keyword the SDK method does not take (``betas`` and
    ``fallbacks`` on the plain namespace among them); ``ValueError`` for a
    non-streaming ``create`` above the SDK's cap for the model, unless the call
    passes its own ``timeout`` (the SDK's own escape).
    """
    allowed = SDK_KEYWORDS[(namespace, method)]
    for name in kwargs:
        if name not in allowed:
            raise TypeError(
                f"{_SDK_OWNER[method]}() got an unexpected keyword argument '{name}'"
            )
    max_tokens = kwargs.get("max_tokens")
    if (
        method == "create"
        and not kwargs.get("stream")
        and "timeout" not in kwargs
        and isinstance(max_tokens, int)
    ):
        limit, message = _sdk_cap(str(kwargs.get("model", "")))
        if max_tokens > limit:
            raise ValueError(message)


# The namespace a call was already checked as. A beta call that a fake forwards
# to its shared ``create`` must not be checked again as a plain one.
_CHECKED_AS: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "fake_anthropic_checked_as", default=None,
)


def checked_entry(namespace: str, method: str, handler: Any, *, header: bool = False) -> Any:
    """``handler`` behind an SDK-checked entry point for ``namespace``.

    The one wrapper every fake entry point production reaches goes through
    (the mixins, the beta proxy and :func:`sdk_namespaces` use it; a fake
    assembled by hand wraps its own entries with it). ``tests/conftest.py``
    fails a test in which production reaches a Messages entry point that is
    neither this nor the real SDK's.

    ``header``: drop ``betas`` before the handler sees the call. On the beta
    namespace it is the ``anthropic-beta`` header, not part of the body. A
    fake that records the betas it was sent keeps the default.
    """
    def entry(*args: Any, **kwargs: Any) -> Any:
        if _CHECKED_AS.get() is None:
            check_sdk_request(namespace, method, kwargs)
        if header:
            kwargs.pop("betas", None)
        token = _CHECKED_AS.set(namespace)
        try:
            return handler(*args, **kwargs)
        finally:
            _CHECKED_AS.reset(token)

    entry.__wrapped__ = handler  # type: ignore[attr-defined]
    entry.sdk_checked = True  # type: ignore[attr-defined]
    return entry


def checked_batch_create(create: Any) -> Any:
    """Decorate a fake ``messages.batches.create``: the SDK's check first.

    ``client.messages.batches.create`` takes ``requests`` and the transport
    options, never ``betas``. The fake keeps its own ``requests``-only body.
    """
    @functools.wraps(create)
    def entry(*args: Any, **kwargs: Any) -> Any:
        check_sdk_request(PLAIN, "batches.create", kwargs)
        return create(*args, requests=kwargs["requests"])

    entry.sdk_checked = True  # type: ignore[attr-defined]
    return entry


def sdk_namespaces(
    *,
    create: Any = None,
    stream: Any = None,
    batches: Any = None,
    files: Any = None,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """``(messages, beta)`` for a test-local fake: each entry point checked as
    its own namespace, both routed to the fake's own handlers.

    ``stream`` returns the context manager the SDK's ``stream`` would
    (:class:`FinalMessageStream` or the fake's own). ``batches`` (the fake's
    object, shared by both, since production submits only on the plain
    namespace) and ``files`` are set as given.
    """
    messages = SimpleNamespace(batches=batches)
    beta_messages = SimpleNamespace(batches=batches)
    for method, handler in (("create", create), ("stream", stream)):
        if handler is None:
            continue
        setattr(messages, method, checked_entry(PLAIN, method, handler))
        setattr(beta_messages, method, checked_entry(BETA, method, handler, header=True))
    return messages, SimpleNamespace(messages=beta_messages, files=files)


# ---------------------------------------------------------------------------
# Streaming transport shim
# ---------------------------------------------------------------------------
#
# The digest, critique, review-plan, synthesis and focus stages issue their
# requests through ``client.messages.stream(...)`` rather than ``.create(...)``:
# above 21,333 ``max_tokens`` the SDK refuses a non-streaming call outright
# (a client-side ValueError, before any HTTP request), and those stages run at
# 32k-64k. See ``drawing_analyzer.digest.stream_message``.
#
# A fake client therefore needs a ``messages.stream`` as well as a
# ``messages.create``. Rather than hand-writing a context manager in every test
# module, a fake ``messages`` object inherits :class:`StreamingMessagesMixin`
# and gets one that routes straight back through its own ``create`` — so the
# recorded kwargs, the scripted responses and the raised exceptions are
# identical on both transports, which is exactly the equivalence the streaming
# conversion needs to hold. The mixin also puts the ``create`` a fake defines
# behind the plain namespace's check.


class FinalMessageStream:
    """Context-manager stand-in for the SDK's streaming response object."""

    def __init__(self, message: Any) -> None:
        self._message = message

    def __enter__(self) -> "FinalMessageStream":
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def get_final_message(self) -> Any:
        return self._message


class _StreamDescriptor:
    """Resolve ``create`` against whatever ``stream`` was reached through.

    Fake ``messages`` objects come in two shapes in this suite: an *instance*
    with a normal ``def create(self, ...)``, and a bare nested ``class messages``
    with a ``@staticmethod create`` that callers use unbound. A plain method
    would only serve the first. Binding at access time serves both.
    """

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        target = obj if obj is not None else objtype

        def stream(**kwargs: Any) -> FinalMessageStream:
            return FinalMessageStream(target.create(**kwargs))

        return checked_entry(PLAIN, "stream", stream)


class StreamingMessagesMixin:
    """Give a fake ``messages`` object a ``stream()`` backed by its ``create()``.

    Mix in *before* the fake's own base so ``stream`` is inherited::

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kwargs): ...

        class messages(StreamingMessagesMixin):     # used unbound
            @staticmethod
            def create(**kwargs): ...

    Both entry points are the plain namespace's, checked against the SDK
    (:func:`check_sdk_request`); a subclass's own ``create`` is wrapped when
    the class is defined.
    """

    stream = _StreamDescriptor()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        raw = cls.__dict__.get("create")
        if isinstance(raw, staticmethod):
            cls.create = staticmethod(checked_entry(PLAIN, "create", raw.__func__))
        elif callable(raw):
            cls.create = checked_entry(PLAIN, "create", raw)


def add_stream(messages_obj: Any) -> Any:
    """Attach a ``stream`` to an already-built fake ``messages`` object.

    For fakes assembled from plain namespaces/lambdas rather than a class. Its
    ``create`` and the new ``stream`` are the plain namespace's, checked.
    """
    create = messages_obj.create
    messages_obj.create = checked_entry(PLAIN, "create", create)
    messages_obj.stream = checked_entry(
        PLAIN, "stream", lambda **kwargs: FinalMessageStream(create(**kwargs)),
    )
    return messages_obj


class _BetaMessagesProxy:
    """``client.beta.messages`` over an existing fake ``messages`` object.

    Production reaches the beta namespace whenever a request carries
    ``betas``: the Opus 5 refusal fallback (``fallbacks`` in the body, its beta
    in the header) and the investigation's task budget. The beta namespace is
    a transport detail, not a different conversation, so this routes to the
    same ``create`` and records the same body: checked against the SDK's beta
    signature first, then ``betas`` dropped, exactly as the wire header it
    becomes.
    """

    def __init__(self, messages: Any) -> None:
        self._messages = messages
        self.create = checked_entry(BETA, "create", self._create, header=True)
        self.stream = checked_entry(BETA, "stream", self._stream, header=True)

    def _create(self, **kwargs: Any) -> Any:
        return self._messages.create(**kwargs)

    def _stream(self, **kwargs: Any) -> FinalMessageStream:
        return FinalMessageStream(self._messages.create(**kwargs))


class BetaClientMixin:
    """Give a fake client a ``beta.messages`` backed by its own ``messages``.

    The setter matters: a plain ``@property`` is a data descriptor and would
    shadow — and refuse — a fake that assigns its own ``self.beta`` (the batch
    fakes do, for ``beta.messages.batches`` and ``beta.files``). An explicit
    override therefore wins, so this is safe to mix into any fake client.
    """

    _beta_override: Any = None

    @property
    def beta(self) -> Any:
        if self._beta_override is not None:
            return self._beta_override
        return SimpleNamespace(messages=_BetaMessagesProxy(self.messages))

    @beta.setter
    def beta(self, value: Any) -> None:
        self._beta_override = value
