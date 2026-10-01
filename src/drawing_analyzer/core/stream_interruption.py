"""A stream that broke after it started (remediation WP-01.7, D-1's WP-01.7 note).

``core.api_config._dispatch_messages`` raises :class:`StreamInterrupted` for a
failure while a stream's events are read, carrying the SDK's exception and the
read it had accumulated. It lives in its own module, stdlib only, so the class
is one object for the process: ``digest`` and ``batch_digest`` test for it with
``isinstance``, and a module that re-creates it (``importlib.reload`` of
``api_config``, which the report-chat tests do to re-read the environment)
would otherwise raise a class those tests no longer recognise.
"""
from __future__ import annotations

from typing import Any


class StreamInterrupted(Exception):
    """A streamed request that raised after its stream started (remediation WP-01.7).

    The SDK's own ``max_retries`` re-sends a request, never a stream that has
    already answered 200 (measured on SDK 1.7.0 and 1.8.0), so a failure while
    the events are read reached the caller as whatever the transport raised:
    an SSE ``error`` event is an ``APIStatusError`` whose ``status_code`` is the
    stream's 200 and whose type is the event's (``overloaded_error``), a
    dropped connection is the transport's own ``RemoteProtocolError`` (not
    wrapped), and a stream that ended with no event at all is the SDK's
    ``AssertionError``. None of them read as transient, and the read the SDK
    had accumulated was lost with its usage.

    ``cause`` is that exception (also ``__cause__``). ``partial`` is the SDK's
    ``current_message_snapshot`` when the stream raised: the reply so far,
    with ``message_start``'s usage and no stop reason (``None`` when no
    ``message_start`` arrived). ``kind`` names the cause:

    - ``"error_event"``: an SSE ``error`` event; ``error_type`` and
      ``error_message`` are its body's;
    - ``"connection"``: the transport dropped the stream;
    - ``"timeout"``: the transport timed out reading it;
    - ``"no_event"``: the stream ended with no event at all;
    - ``"other"``: anything else (a caller judges it as the cause itself).

    Whether it is retried is ``digest._is_transient_error``'s decision, and
    what the partial read means is each stage's (D-1's WP-01.7 note). Only a
    failure while the stream is read is wrapped: one before it exists (a 400,
    a 529 the SDK already retried) propagates unchanged, since the
    self-healing latches read it.
    """

    def __init__(self, cause: BaseException, partial: Any = None) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.partial = partial
        self.error_type: str | None = None
        self.error_message: str = ""
        self.kind = self._classify()

    def _classify(self) -> str:
        cause = self.cause
        body = getattr(cause, "body", None)
        error = body.get("error") if isinstance(body, dict) else None
        if getattr(cause, "status_code", None) == 200 and isinstance(error, dict):
            # An SSE ``error`` event: the stream's status was 200, the event's
            # body names what went wrong.
            kind = error.get("type")
            if isinstance(kind, str) and kind:
                self.error_type = kind
                message = error.get("message")
                self.error_message = message if isinstance(message, str) else ""
                return "error_event"
        names = {(c.__module__.split(".")[0], c.__name__) for c in type(cause).__mro__}
        # The transport's own errors, by name so this kernel imports neither
        # the SDK nor its HTTP client (``httpx2``; ``httpx`` too).
        if any(mod.startswith("httpx") and name == "TimeoutException" for mod, name in names):
            return "timeout"
        if any(mod.startswith("httpx") and name == "TransportError" for mod, name in names):
            return "connection"
        if self.partial is None and isinstance(cause, AssertionError):
            return "no_event"
        return "other"

    @property
    def label(self) -> str:
        """What interrupted the stream, as the error wording names it:
        the event's type, ``connection dropped`` (a stream with no event
        reads as dropped, the owner's rule), ``timed out``, or the cause's
        type name."""
        if self.kind == "error_event":
            return str(self.error_type)
        if self.kind in ("connection", "no_event"):
            return "connection dropped"
        if self.kind == "timeout":
            return "timed out"
        return type(self.cause).__name__


def stream_snapshot(stream: Any) -> Any:
    """The stream's ``current_message_snapshot``, or ``None`` when it holds
    none (the SDK asserts before any ``message_start``)."""
    try:
        return stream.current_message_snapshot
    except Exception:  # noqa: BLE001 - no snapshot is an answer, not a failure
        return None
