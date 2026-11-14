"""Thought stream: the model's summarized reasoning, for the live view only.

The API can return a readable *summary* of a model's reasoning in its
``thinking`` blocks (``thinking: {"type": "adaptive", "display":
"summarized"}``; the default returns them empty, and the raw chain of thought
is never returned on any setting). ``display`` changes what is shown, not what
is thought or billed. A run that has a live view asks for those summaries and
collects them here, so the *Thinking* tab can show what the model was working
through on each sheet, finding and code reference.

Three rules:

* **Display only.** A :class:`ThoughtStream` lives in memory for the run and is
  read by the live view. Nothing in it is written to an export, the journal,
  the diagnostics folder or a cache: the reasoning summary is model prose about
  the drawings, and the exports' sanitizing rules do not cover it. Call
  telemetry stays shape-and-counts only; this is a separate record.
* **Opt-in per run.** The recorder exists only when the pipeline was given a
  monitor (``extract_drawing_context(monitor=...)``) and
  ``DRAWING_ANALYZER_SHOW_THINKING`` is not ``0``. It rides the run's
  :class:`~drawing_analyzer.resource_pressure.ResourcePressure`
  (``pressure.thoughts``), so worker threads reach it through
  ``worker_binding()`` like the call telemetry and the live spend. A run
  without one sends exactly the requests it always sent.
* **Never in the way.** Every hook swallows its own failures (I-3), and the
  request-side change is cache-neutral: no cache key hashes ``display``.

Fed at the same dispatch sites as the call telemetry: each real-time request
in ``core.api_config._dispatch_messages`` (stream events as they arrive, or the
final message of a non-streamed call) and each batch result in
``batch_recovery.read_batch_results``.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from . import call_telemetry, resource_pressure

SHOW_THINKING_ENV = "DRAWING_ANALYZER_SHOW_THINKING"

# How much is kept. A thought's text is a summary (typically a few hundred
# characters); the cap bounds a pathological one. Old settled thoughts are
# dropped first; ``seen`` / ``with_text`` count everything.
MAX_THOUGHTS = 240
MAX_THOUGHT_CHARS = 6000

STATE_THINKING = "thinking"     # the model is reasoning (no answer text yet)
STATE_WRITING = "writing"       # the answer is streaming
STATE_DONE = "done"
STATE_ERROR = "error"
OPEN_STATES = frozenset({STATE_THINKING, STATE_WRITING})

TRANSPORT_STREAM = "stream"
TRANSPORT_CREATE = "create"
TRANSPORT_BATCH = "batch"


def show_thinking_enabled() -> bool:
    """Whether a monitored run may ask for reasoning summaries (env opt-out)."""
    raw = os.environ.get(SHOW_THINKING_ENV, "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@dataclass
class Thought:
    """One model call's reasoning summary, as far as it has arrived."""

    seq: int
    stage: str                      # the usage family (``digest``, ``verify``, …)
    item: str = ""                  # ``SRC-0001:p0``, a finding id, a code ref
    model: str = ""
    transport: str = TRANSPORT_STREAM
    started_at: float = 0.0         # the stream's clock (monotonic seconds)
    updated_at: float = 0.0
    state: str = STATE_THINKING
    text: str = ""
    chars_out: int = 0              # answer characters streamed so far
    truncated: bool = False         # the text hit ``MAX_THOUGHT_CHARS``

    @property
    def open(self) -> bool:
        return self.state in OPEN_STATES


def message_thinking_text(message: Any) -> str:
    """The reasoning summary in a finished message's ``thinking`` blocks."""
    parts: list[str] = []
    for block in _get(message, "content", None) or ():
        if str(_get(block, "type", "") or "") != "thinking":
            continue
        text = _get(block, "thinking", "")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


class ThoughtStream:
    """Thread-safe, bounded, in-memory collector of reasoning summaries."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._items: list[Thought] = []
        self._seq = 0
        self.version = 0            # bumped on every change a reader would see
        # The reader's copies, reused until their thought changes: a streaming
        # read changes one thought many times a second, and copying every kept
        # thought for each frame was a measurable part of the frame's cost.
        self._copies: dict[int, Thought] = {}
        self._dirty: set[int] = set()
        self.seen = 0               # calls observed
        self.with_text = 0          # calls that returned a non-empty summary

    # -- writers (the run's threads) ---------------------------------------- #

    def open(self, *, stage: str, item: str = "", model: str = "",
             transport: str = TRANSPORT_STREAM) -> Thought:
        """A call was sent: list it as in flight."""
        now = self._clock()
        with self._lock:
            self._seq += 1
            thought = Thought(
                seq=self._seq, stage=str(stage or ""), item=str(item or ""),
                model=str(model or ""), transport=transport, started_at=now,
                updated_at=now,
            )
            self._items.append(thought)
            self.seen += 1
            self._trim()
            self._touch(thought)
        return thought

    def add_thinking(self, thought: Thought, delta: str) -> None:
        if not delta or not isinstance(delta, str):
            return
        with self._lock:
            self._append(thought, delta)
            thought.updated_at = self._clock()
            self._touch(thought)

    def add_output(self, thought: Thought, chars: int) -> None:
        if chars <= 0:
            return
        with self._lock:
            thought.chars_out += int(chars)
            if thought.state == STATE_THINKING:
                thought.state = STATE_WRITING
            thought.updated_at = self._clock()
            self._touch(thought)

    def new_block(self, thought: Thought) -> None:
        """A further thinking block began: separate it from the last one."""
        with self._lock:
            if thought.text and not thought.text.endswith("\n\n"):
                self._append(thought, "\n\n")
                self._touch(thought)

    def close(self, thought: Thought, *, message: Any = None, failed: bool = False) -> None:
        """The call ended. A call that produced no summary leaves the list."""
        with self._lock:
            if not thought.text.strip() and message is not None:
                self._append(thought, message_thinking_text(message))
            thought.text = thought.text.rstrip()
            thought.state = STATE_ERROR if failed else STATE_DONE
            thought.updated_at = self._clock()
            if thought.text:
                self.with_text += 1
            else:
                try:
                    self._items.remove(thought)
                except ValueError:
                    pass
            self._touch(thought)

    def record(self, *, stage: str, item: str = "", model: str = "",
               transport: str = TRANSPORT_BATCH, message: Any = None) -> None:
        """A finished response arrived whole (a batch result)."""
        text = message_thinking_text(message)
        with self._lock:
            self.seen += 1
            if not text:
                return
            now = self._clock()
            self._seq += 1
            thought = Thought(
                seq=self._seq, stage=str(stage or ""), item=str(item or ""),
                model=str(model or ""), transport=transport, started_at=now,
                updated_at=now, state=STATE_DONE,
            )
            self._append(thought, text)
            self._items.append(thought)
            self.with_text += 1
            self._trim()
            self._touch(thought)

    def _touch(self, thought: Thought) -> None:
        """A change a reader would see (call with the lock held)."""
        self._dirty.add(thought.seq)
        self.version += 1

    def _append(self, thought: Thought, text: str) -> None:
        room = MAX_THOUGHT_CHARS - len(thought.text)
        if room <= 0:
            thought.truncated = thought.truncated or bool(text.strip())
            return
        if len(text) > room:
            thought.truncated = True
        thought.text += text[:room]

    def _trim(self) -> None:
        over = len(self._items) - MAX_THOUGHTS
        if over <= 0:
            return
        kept: list[Thought] = []
        for thought in self._items:
            if over > 0 and not thought.open:
                over -= 1
                continue
            kept.append(thought)
        self._items = kept

    # -- reader (the host's UI thread) -------------------------------------- #

    def snapshot(self, since: int = -1) -> "tuple[int, list[Thought]] | None":
        """Copies of every kept thought, oldest first; ``None`` if nothing
        changed since version ``since``.

        The run keeps writing the originals, never the copies. A thought that
        has not changed since the last snapshot is handed out as the same copy
        again, so a reader must treat copies as read-only."""
        with self._lock:
            if self.version == since:
                return None
            copies: dict[int, Thought] = {}
            out: list[Thought] = []
            for t in self._items:
                copy = self._copies.get(t.seq)
                if copy is None or t.seq in self._dirty:
                    copy = replace(t)
                copies[t.seq] = copy
                out.append(copy)
            self._copies, self._dirty = copies, set()
            return self.version, out


# --------------------------------------------------------------------------- #
# Hooks for the dispatch sites.
# --------------------------------------------------------------------------- #


def current() -> "ThoughtStream | None":
    """The calling thread's run's stream, or ``None`` (no live view attached)."""
    pressure = resource_pressure.current()
    stream = getattr(pressure, "thoughts", None)
    return stream if isinstance(stream, ThoughtStream) else None


class CallTap:
    """Follows one real-time call. Every method swallows its own failures."""

    def __init__(self, stream: ThoughtStream, thought: Thought) -> None:
        self._stream = stream
        self._thought = thought

    def event(self, event: Any) -> None:
        """One raw stream event (the SDK's higher-level events are ignored, so
        a delta is never counted twice)."""
        try:
            kind = _get(event, "type", "")
            if kind == "content_block_delta":
                delta = _get(event, "delta")
                dtype = _get(delta, "type", "")
                if dtype == "thinking_delta":
                    self._stream.add_thinking(self._thought, _get(delta, "thinking", "") or "")
                elif dtype == "text_delta":
                    self._stream.add_output(self._thought, len(_get(delta, "text", "") or ""))
                elif dtype == "input_json_delta":
                    self._stream.add_output(
                        self._thought, len(_get(delta, "partial_json", "") or ""))
            elif kind == "content_block_start":
                if _get(_get(event, "content_block"), "type", "") == "thinking":
                    self._stream.new_block(self._thought)
        except Exception:  # noqa: BLE001 - a display hook never fails a call (I-3)
            pass

    def finish(self, message: Any = None, *, failed: bool = False) -> None:
        try:
            self._stream.close(self._thought, message=message, failed=failed)
        except Exception:  # noqa: BLE001
            pass


def open_call(kwargs: dict, *, method: str) -> "CallTap | None":
    """Start following a real-time request; ``None`` when no stream is live."""
    try:
        stream = current()
        if stream is None:
            return None
        stage, item = call_telemetry.current_scope()
        thought = stream.open(
            stage=call_telemetry.canonical_stage(stage), item=item,
            model=str((kwargs or {}).get("model") or ""),
            transport=TRANSPORT_STREAM if method == "stream" else TRANSPORT_CREATE,
        )
        return CallTap(stream, thought)
    except Exception:  # noqa: BLE001
        return None


def note_batch_results(batch_id: str, results: dict) -> None:
    """Collect the reasoning summaries in a batch's results (never raises)."""
    try:
        stream = current()
        if stream is None:
            return
        calls = getattr(resource_pressure.current(), "calls", None)
        for custom_id, entry in dict(results or {}).items():
            result = _get(entry, "result")
            if str(_get(result, "type") or "") != "succeeded":
                continue
            message = _get(result, "message")
            record = None
            lookup = getattr(calls, "batch_item", None)
            if lookup is not None:
                record = lookup(batch_id, custom_id)
            stream.record(
                stage=call_telemetry.canonical_stage(
                    str(getattr(record, "stage", "") or "batch")),
                item=str(getattr(record, "item", "") or ""),
                model=str(getattr(record, "model", "") or _get(message, "model") or ""),
                message=message,
            )
    except Exception:  # noqa: BLE001
        pass
