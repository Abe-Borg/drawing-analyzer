"""The run kill switch: stop a run in flight, on every transport.

A caller (the GUI's **Stop** button) creates a :class:`CancelToken` and passes
it to :func:`~drawing_analyzer.pipeline.extract_drawing_context` as
``cancel=``. Cancelling the token:

* refuses every new paid request — real-time Messages calls
  (``core.api_config._dispatch_messages``, the single dispatch every stage
  uses), Message Batch submissions, and Files-API uploads — by raising
  :class:`RunCancelled` at the call site;
* abandons a streamed response at its next event, which closes the connection
  so the server stops generating (digest, critique, synthesis, focus, review
  plan, investigation);
* cancels every Message Batch the run still has open **immediately, from a
  background thread** — wherever the run's own thread happens to be — through
  the callbacks registered with :func:`track_remote_batch`;
* wakes poll and retry-backoff waits (:func:`pause`) at once.

A non-streamed request already in flight (verification, citation checks,
cross-sheet QC, identity, prose harvest) is not interrupted: those calls are
capped short, and nothing new is sent once it returns.

:class:`RunCancelled` derives from ``BaseException``, as
``asyncio.CancelledError`` does, so the stage guards' ``except Exception`` (the
I-3 non-fatal contract) cannot swallow a stop and carry on to the next paid
stage. Code that must clean up on a stop catches it by name.

Binding mirrors :mod:`~drawing_analyzer.resource_pressure`: per thread. The
run's own thread is bound by :func:`bound_run` (on ``extract_drawing_context``)
and every pool the run opens binds its workers through
``resource_pressure.worker_binding()``. A thread bound to no token is never
cancelled — there is no "lone live run" fallback, because a stop must never
reach another run's work. Cleanup (file deletes, receipt bookkeeping, the
cancel calls themselves) is never gated.

Stdlib only.
"""
from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any, Callable

# The diagnostics logger, by name: this module stays a stdlib-only leaf so
# ``core.api_config`` can import it.
_log = logging.getLogger("drawing_analyzer.diagnostics")


class RunCancelled(BaseException):
    """The run was stopped by the user; no further paid work may start."""

    def __init__(self, message: str = "run stopped by the user") -> None:
        super().__init__(message)


class CancelToken:
    """One run's kill switch. Thread-safe; :meth:`cancel` never blocks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._remote: dict[str, Callable[[], Any]] = {}
        self._worker: threading.Thread | None = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        """Stop the run. Idempotent; remote cancels run on a daemon thread."""
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            pending = list(self._remote.items())
            self._remote.clear()
            if pending:
                self._worker = threading.Thread(
                    target=self._run_remote_cancels, args=(pending,),
                    daemon=True, name="run-cancel",
                )
                self._worker.start()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise RunCancelled()

    def wait(self, seconds: float) -> bool:
        """Block up to ``seconds``; ``True`` as soon as the token is cancelled."""
        return self._event.wait(max(0.0, seconds))

    def track_remote(self, key: str, cancel_fn: Callable[[], Any]) -> None:
        """Register remote work to cancel on a stop.

        A key registered after the stop (a submit that was already in flight
        when the user pressed Stop) is cancelled at once, on the calling thread.
        """
        with self._lock:
            if not self._event.is_set():
                self._remote[key] = cancel_fn
                return
        self._invoke(key, cancel_fn)

    def forget_remote(self, key: str) -> None:
        """The remote work settled (terminal, or already cancelled)."""
        with self._lock:
            self._remote.pop(key, None)

    def wait_for_remote_cancels(self, timeout: float) -> bool:
        """Wait for the stop's remote cancels to finish; ``True`` once done."""
        with self._lock:
            worker = self._worker
        if worker is None:
            return True
        worker.join(max(0.0, timeout))
        return not worker.is_alive()

    def _run_remote_cancels(self, pending: list[tuple[str, Callable[[], Any]]]) -> None:
        for key, cancel_fn in pending:
            self._invoke(key, cancel_fn)

    @staticmethod
    def _invoke(key: str, cancel_fn: Callable[[], Any]) -> None:
        try:
            cancel_fn()
        except Exception:  # noqa: BLE001 - one failed cancel never skips the rest
            _log.exception("remote cancel of %s failed", key)


# --------------------------------------------------------------------------- #
# Thread binding — see the module docstring.
# --------------------------------------------------------------------------- #

_binding = threading.local()


def current() -> CancelToken | None:
    """The calling thread's token, or ``None`` (an unbound thread never stops)."""
    return getattr(_binding, "token", None)


def bind_thread(token: CancelToken | None) -> CancelToken | None:
    """Bind the calling thread to ``token``; returns its previous binding."""
    previous = getattr(_binding, "token", None)
    _binding.token = token
    return previous


def bound_run(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: bind the call's ``cancel=`` token to this thread for its duration."""
    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        previous = bind_thread(kwargs.get("cancel"))
        try:
            return fn(*args, **kwargs)
        except RunCancelled:
            _log.warning("===== run stopped by the user =====")
            raise
        finally:
            bind_thread(previous)

    return _wrapped


def is_cancelled() -> bool:
    token = current()
    return token is not None and token.cancelled


def check() -> None:
    """Raise :class:`RunCancelled` if this thread's run was stopped."""
    token = current()
    if token is not None:
        token.raise_if_cancelled()


def pause(seconds: float, sleep: Callable[[float], None] = time.sleep) -> None:
    """Sleep for ``seconds``, raising :class:`RunCancelled` as soon as the run stops.

    A real ``time.sleep`` becomes a wait on the token, so a stop wakes a long
    poll interval or Retry-After backoff at once. An injected ``sleep`` (a test
    clock) is honored as given and the stop is re-checked after it.
    """
    token = current()
    if token is None:
        sleep(seconds)
        return
    token.raise_if_cancelled()
    if sleep is time.sleep:
        if token.wait(seconds):
            raise RunCancelled()
        return
    sleep(seconds)
    token.raise_if_cancelled()


def track_remote_batch(batch_id: str, cancel_fn: Callable[[], Any]) -> None:
    """Have a stop cancel ``batch_id`` (no-op on an unbound thread)."""
    token = current()
    if token is not None and batch_id:
        token.track_remote(batch_id, cancel_fn)


def forget_remote_batch(batch_id: str | None) -> None:
    """``batch_id`` settled; a stop no longer needs to cancel it."""
    token = current()
    if token is not None and batch_id:
        token.forget_remote(batch_id)
