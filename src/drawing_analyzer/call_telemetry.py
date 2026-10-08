"""Per-call agent telemetry: what every model call was given, and what it used.

The usage ledger records what each stage *billed*; the resource-pressure record
says whether the API or the host held the run back. Neither answers the
question a reviewer asks of an agent that produced a thin result: **did it have
enough room to do its job?** Was it given a large enough output envelope, the
effort level and thinking mode it was meant to have, the tools it needed and
enough uses of them — and how close to each of those limits did it actually
run? That has to be read off the requests themselves, because the limits live
in the request (``max_tokens``, ``output_config.effort``, ``thinking``, a
server tool's ``max_uses``, a ``task_budget``, a forced ``tool_choice``) and
the consumption lives in the response (``usage``, ``stop_reason``, the tool
blocks).

This module records one :class:`CallRecord` per model request, at the two
places every request passes through:

- :func:`drawing_analyzer.core.api_config._dispatch_messages` — every
  real-time Messages request (stream or create) of every stage;
- :func:`drawing_analyzer.batch_digest._create_batch` (one record per batch
  item, provisioning only) and
  :func:`drawing_analyzer.batch_recovery.read_batch_results` (fills in the
  consumption side when the results are read).

A record is **request shape and counts only**: model, caps, effort, thinking
mode, tool *names* and limits, token counts, stop reason, tool-call counts,
timing and the message id. Never a prompt, an image, drawing text, a reply, or
a key. Free-form strings (errors, item labels) pass the journal's sanitize
boundary when an export renders them.

Who made the call
-----------------
Each call site wraps its request in :func:`scope` — ``with
call_telemetry.scope("verify", finding.id):`` — naming the stage (the same
family names the usage ledger uses) and the work item (a portable sheet key
``SRC-0001:p0``, a finding id, a code reference). Item-level allotments that
are not visible in the request ride the scope too (the investigation loop's
``evidence_rounds``). The scope is thread-local, so it is set inside the
worker that makes the call. A call made outside any scope is still recorded,
labeled ``unattributed`` with the calling module, so a new call site shows up
instead of vanishing.

What is derived
---------------
:meth:`CallTelemetry.stage_summaries` folds the records per stage into a
**headroom verdict** — ``STARVED`` / ``TIGHT`` / ``ADEQUATE`` — with the
evidence for it (see :func:`_stage_verdict` for the rules), plus what the stage
was given (models, effort, thinking, caps, tools and their limits) and which
abilities it lost mid-run (a feature present on its early calls and absent on
later ones, e.g. structured outputs latched off after a rejection).
:meth:`CallTelemetry.model_map` answers "where was each model called".

Run-scoped like the resource-pressure record: the recorder is owned by the
run's :class:`~drawing_analyzer.resource_pressure.ResourcePressure` (it is the
provisioning leg of "were the agents starved?") and reaches every worker
thread through that record's existing thread binding. Advisory, never fatal:
every public entry swallows its own failures.
"""
from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator

from .diagnostics import request_id_of, summarize_exc

# Headroom verdicts, worst first.
HEADROOM_STARVED = "STARVED"
HEADROOM_TIGHT = "TIGHT"
HEADROOM_ADEQUATE = "ADEQUATE"
HEADROOM_NOT_ASSESSED = "NOT_ASSESSED"     # no model call was made (all cache hits)
_VERDICT_RANK = {
    HEADROOM_NOT_ASSESSED: 0, HEADROOM_ADEQUATE: 1, HEADROOM_TIGHT: 2, HEADROOM_STARVED: 3,
}

# Call outcomes.
OUTCOME_OK = "OK"                     # end_turn / stop_sequence
OUTCOME_TOOL_USE = "TOOL_USE"         # stopped to have client tools run (a normal turn)
OUTCOME_MAX_TOKENS = "MAX_TOKENS"     # cut off at the output cap
OUTCOME_PAUSE_TURN = "PAUSE_TURN"     # the server-tool loop hit its iteration limit
OUTCOME_REFUSAL = "REFUSAL"           # declined (after any server-side fallback)
OUTCOME_ERROR = "ERROR"               # the request raised, or the batch item errored
OUTCOME_CANCELLED = "CANCELLED"       # the run was stopped (or the batch item canceled)
OUTCOME_EXPIRED = "EXPIRED"           # a batch item the API expired
OUTCOME_PENDING = "NO_RESULT"         # a batch item whose result was never read

TRANSPORT_REAL_TIME = "REAL_TIME"
TRANSPORT_BATCH = "BATCH"

# A call that used this much of its ``max_tokens`` without hitting it ran close
# to the cap. Adaptive thinking shares the envelope with the answer, so this
# fraction covers thinking + reply together (the API does not report them
# separately).
NEAR_CAP_FRACTION = 0.9

# Bound on stored records. A 1,000-sheet exhaustive run makes a few thousand
# calls; past the bound the record count keeps counting and the analysis says
# it covers the stored calls only.
MAX_STORED_CALLS = 20_000

UNATTRIBUTED = "unattributed"

# The pipeline order the summaries are listed in; anything else follows
# alphabetically. Names are the usage ledger's stage families.
_STAGE_ORDER = (
    "identity", "review_plan", "digest", "critique", "cross_qc", "harvest",
    "verify", "investigate", "citation", "synthesis", "focus",
)

# ResourcePressure budget notes use their retry-loop stage names; map them onto
# the usage families this module (and the run.log usage table) uses.
_STAGE_ALIASES = {
    "verification": "verify",
    "investigation": "investigate",
    "prose_harvest": "harvest",
}

_EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")


def canonical_stage(stage: str) -> str:
    return _STAGE_ALIASES.get(stage, stage)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{dt.microsecond // 1000:03d}Z"
    )


def _get(value: Any, key: str, default: Any = None) -> Any:
    if value is None:
        return default
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _int_or_none(value: Any) -> int | None:
    try:
        return None if value is None or isinstance(value, bool) else int(value)
    except (TypeError, ValueError):
        return None


def _count(value: Any, key: str) -> int:
    return _int_or_none(_get(value, key, 0)) or 0


# --------------------------------------------------------------------------- #
# The record.
# --------------------------------------------------------------------------- #


@dataclass
class CallRecord:
    """One model request: what it was given and what it used."""

    seq: int
    stage: str
    item: str = ""
    transport: str = TRANSPORT_REAL_TIME
    method: str = ""                        # stream | create | batch
    started_at: str = ""
    duration_seconds: float | None = None   # batch: submit → results read
    # --- what the call was given -------------------------------------------
    model: str = ""                          # the model the request named
    max_tokens: int | None = None
    thinking: str = "omitted"                # adaptive | enabled | disabled | omitted
    thinking_budget: int | None = None
    effort: str | None = None                # None = field omitted
    model_effort_ceiling: str | None = None  # highest level the model accepts
    task_budget: int | None = None
    tools: tuple[str, ...] = ()
    tool_limits: dict = field(default_factory=dict)   # tool name -> max_uses
    tool_choice: str = ""
    strict_tools: bool = False
    structured_output: bool = False
    refusal_fallback: bool = False
    betas: tuple[str, ...] = ()
    images: int = 0
    messages: int = 0
    item_limits: dict = field(default_factory=dict)   # e.g. evidence_rounds
    custom_id: str = ""
    batch_id: str = ""
    # --- what it used --------------------------------------------------------
    outcome: str = ""
    stop_reason: str | None = None
    served_model: str | None = None          # set when a refusal fallback answered
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_blocks: int = 0
    tool_calls: dict = field(default_factory=dict)        # tool name -> calls made
    server_tool_requests: dict = field(default_factory=dict)  # usage.server_tool_use
    tool_errors: dict = field(default_factory=dict)       # error_code -> count
    request_id: str = ""
    error: str = ""

    @property
    def output_fraction(self) -> float | None:
        """Share of ``max_tokens`` the reply (thinking included) consumed."""
        if not self.max_tokens or self.outcome in ("", OUTCOME_PENDING, OUTCOME_ERROR):
            return None
        return self.output_tokens / self.max_tokens

    @property
    def tools_at_limit(self) -> list[str]:
        """Tools whose per-call ``max_uses`` this call used up."""
        hit = []
        for name, limit in sorted(self.tool_limits.items()):
            used = self.tool_uses(name)
            if limit and used >= limit:
                hit.append(name)
        return hit

    def tool_uses(self, name: str) -> int:
        """Uses of ``name``: the server's own count when it reported one."""
        reported = self.server_tool_requests.get(f"{name}_requests")
        return int(reported) if reported is not None else int(self.tool_calls.get(name, 0))

    @property
    def forced_close(self) -> bool:
        """Tools were offered but ``tool_choice`` withheld them (a cap was reached)."""
        return bool(self.tools) and self.tool_choice == "none"

    def to_dict(self) -> dict:
        fraction = self.output_fraction
        return {
            "seq": self.seq,
            "stage": self.stage,
            "item": self.item,
            "transport": self.transport,
            "method": self.method,
            "started_at": self.started_at,
            "duration_seconds": (
                None if self.duration_seconds is None else round(self.duration_seconds, 3)
            ),
            "model": self.model,
            "served_model": self.served_model,
            "max_tokens": self.max_tokens,
            "thinking": self.thinking,
            "thinking_budget": self.thinking_budget,
            "effort": self.effort,
            "model_effort_ceiling": self.model_effort_ceiling,
            "task_budget": self.task_budget,
            "tools": list(self.tools),
            "tool_limits": dict(sorted(self.tool_limits.items())),
            "tool_choice": self.tool_choice,
            "strict_tools": self.strict_tools,
            "structured_output": self.structured_output,
            "refusal_fallback": self.refusal_fallback,
            "betas": list(self.betas),
            "images": self.images,
            "messages": self.messages,
            "item_limits": dict(sorted(self.item_limits.items())),
            "custom_id": self.custom_id,
            "batch_id": self.batch_id,
            "outcome": self.outcome,
            "stop_reason": self.stop_reason,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "output_fraction": None if fraction is None else round(fraction, 4),
            "thinking_blocks": self.thinking_blocks,
            "tool_calls": dict(sorted(self.tool_calls.items())),
            "server_tool_requests": dict(sorted(self.server_tool_requests.items())),
            "tools_at_limit": self.tools_at_limit,
            "tool_errors": dict(sorted(self.tool_errors.items())),
            "forced_close": self.forced_close,
            "request_id": self.request_id,
            "error": self.error,
        }


# CSV layout of ``diagnostics/api_calls.csv`` (one row per call). Dict-valued
# fields are flattened to ``name=value;…`` cells.
CSV_COLUMNS = (
    "seq", "stage", "item", "transport", "method", "started_at", "duration_seconds",
    "model", "served_model", "effort", "model_effort_ceiling", "thinking",
    "thinking_budget", "max_tokens", "output_tokens", "output_fraction",
    "input_tokens", "cache_read_tokens", "cache_write_tokens", "outcome",
    "stop_reason", "tools", "tool_limits", "tool_calls", "tools_at_limit",
    "tool_errors", "tool_choice", "forced_close", "task_budget", "item_limits",
    "structured_output", "strict_tools", "refusal_fallback", "images", "messages",
    "thinking_blocks", "custom_id", "batch_id", "request_id", "error",
)


def csv_cell(value: Any) -> str:
    """One CSV cell for a :meth:`CallRecord.to_dict` value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        return ";".join(f"{k}={v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ";".join(str(v) for v in value)
    return str(value)


# --------------------------------------------------------------------------- #
# Reading a request and a response (pure; never raise into the caller).
# --------------------------------------------------------------------------- #


def _effort_ceiling(model: str) -> str | None:
    try:
        from .core.api_config import model_capabilities

        levels = model_capabilities(model).supported_effort_levels
    except Exception:  # noqa: BLE001 - advisory
        return None
    ranked = [lvl for lvl in _EFFORT_ORDER if lvl in levels]
    return ranked[-1] if ranked else None


def _count_images(messages: Any) -> int:
    total = 0
    for message in messages or ():
        content = _get(message, "content")
        if not isinstance(content, (list, tuple)):
            continue
        for block in content:
            kind = _get(block, "type")
            if kind == "image":
                total += 1
            elif kind == "tool_result":
                inner = _get(block, "content")
                if isinstance(inner, (list, tuple)):
                    total += sum(1 for b in inner if _get(b, "type") == "image")
    return total


def describe_request(kwargs: dict) -> dict:
    """The provisioning half of a record, read off one request's parameters."""
    model = str(kwargs.get("model") or "")
    thinking = kwargs.get("thinking")
    output_config = kwargs.get("output_config") or {}
    task_budget = _get(output_config, "task_budget")
    tools: list[str] = []
    limits: dict[str, int] = {}
    strict = False
    for tool in kwargs.get("tools") or ():
        name = str(_get(tool, "name") or _get(tool, "type") or "?")
        tools.append(name)
        max_uses = _int_or_none(_get(tool, "max_uses"))
        if max_uses is not None:
            limits[name] = max_uses
        strict = strict or bool(_get(tool, "strict"))
    choice = kwargs.get("tool_choice")
    choice_text = ""
    if choice is not None:
        choice_text = str(_get(choice, "type") or "")
        if choice_text == "tool" and _get(choice, "name"):
            choice_text = f"tool:{_get(choice, 'name')}"
    effort = _get(output_config, "effort")
    return {
        "model": model,
        "max_tokens": _int_or_none(kwargs.get("max_tokens")),
        "thinking": "omitted" if thinking is None else str(_get(thinking, "type") or "?"),
        "thinking_budget": _int_or_none(_get(thinking, "budget_tokens")),
        "effort": None if effort is None else str(effort),
        "model_effort_ceiling": _effort_ceiling(model),
        "task_budget": _int_or_none(_get(task_budget, "total")),
        "tools": tuple(tools),
        "tool_limits": limits,
        "tool_choice": choice_text,
        "strict_tools": strict,
        "structured_output": _get(output_config, "format") is not None,
        "refusal_fallback": kwargs.get("fallbacks") is not None,
        "betas": tuple(str(b) for b in (kwargs.get("betas") or ())),
        "images": _count_images(kwargs.get("messages")),
        "messages": len(kwargs.get("messages") or ()),
    }


_STOP_OUTCOMES = {
    "end_turn": OUTCOME_OK,
    "stop_sequence": OUTCOME_OK,
    "tool_use": OUTCOME_TOOL_USE,
    "max_tokens": OUTCOME_MAX_TOKENS,
    "pause_turn": OUTCOME_PAUSE_TURN,
    "refusal": OUTCOME_REFUSAL,
}


def describe_response(message: Any) -> dict:
    """The consumption half of a record, read off one response."""
    from .core.request_usage import fallback_served_model

    usage = _get(message, "usage")
    stop = _get(message, "stop_reason")
    tool_calls: dict[str, int] = {}
    tool_errors: dict[str, int] = {}
    thinking_blocks = 0
    for block in _get(message, "content") or ():
        kind = str(_get(block, "type") or "")
        if kind in ("thinking", "redacted_thinking"):
            thinking_blocks += 1
        elif kind in ("tool_use", "server_tool_use"):
            name = str(_get(block, "name") or "?")
            tool_calls[name] = tool_calls.get(name, 0) + 1
        elif kind.endswith("_tool_result"):
            inner = _get(block, "content")
            code = None if isinstance(inner, (list, tuple, str)) else _get(inner, "error_code")
            if code:
                tool_errors[str(code)] = tool_errors.get(str(code), 0) + 1
    server: dict[str, int] = {}
    reported = _get(usage, "server_tool_use")
    if reported is not None:
        for key in ("web_search_requests", "web_fetch_requests"):
            value = _int_or_none(_get(reported, key))
            if value is not None:
                server[key] = value
    return {
        "stop_reason": None if stop is None else str(stop),
        "outcome": _STOP_OUTCOMES.get(str(stop), OUTCOME_OK if stop is None else str(stop).upper()),
        "served_model": fallback_served_model(message),
        "input_tokens": _count(usage, "input_tokens"),
        "output_tokens": _count(usage, "output_tokens"),
        "cache_read_tokens": _count(usage, "cache_read_input_tokens"),
        "cache_write_tokens": _count(usage, "cache_creation_input_tokens"),
        "thinking_blocks": thinking_blocks,
        "tool_calls": tool_calls,
        "server_tool_requests": server,
        "tool_errors": tool_errors,
        "request_id": str(_get(message, "id", "") or "") or (request_id_of(message) or ""),
    }


# --------------------------------------------------------------------------- #
# Attribution scope (thread-local).
# --------------------------------------------------------------------------- #

_scope = threading.local()

# The item label of a stage that makes one logical request per run (identity,
# review plan, synthesis, focus). A shared label lets a raised-cap re-send be
# recognized as the same work item recovering, not a second item.
SET_ITEM = "set"


def sheet_item(ref: Any) -> str:
    """A sheet's portable item label (``SRC-0001:p0``) — never a path."""
    key = getattr(ref, "key", None)
    if isinstance(key, tuple) and len(key) == 2:
        return f"{key[0]}:p{key[1]}"
    return str(getattr(ref, "source_id", "") or "?")


@contextmanager
def scope(stage: str, item: Any = "", **item_limits: int) -> Iterator[None]:
    """Attribute every model call made inside the block to ``stage`` / ``item``.

    ``item_limits`` names allotments of the work item that the request itself
    does not carry (``evidence_rounds=6``). Thread-local: set it in the thread
    that makes the call. Nesting restores the outer scope on exit.
    """
    previous = getattr(_scope, "value", None)
    _scope.value = (str(stage), "" if item is None else str(item), dict(item_limits))
    try:
        yield
    finally:
        _scope.value = previous


# Frames that are transport plumbing, not the stage that wanted the call.
_PLUMBING_MODULES = frozenset({
    __name__,
    "drawing_analyzer.core.api_config",
    "drawing_analyzer.batch_recovery",
    "contextlib",
})
_PLUMBING_FUNCTIONS = frozenset({
    "stream_message", "stream_with_cap_retry", "_create_batch",
    "_investigation_message", "_investigation_message_turn",
})


def _calling_module() -> str:
    """The first non-plumbing module on the stack (for unattributed calls)."""
    try:
        frame = sys._getframe(2)
    except ValueError:
        return "?"
    for _ in range(24):
        if frame is None:
            break
        module = str(frame.f_globals.get("__name__", "?"))
        if module not in _PLUMBING_MODULES and frame.f_code.co_name not in _PLUMBING_FUNCTIONS:
            return module.rsplit(".", 1)[-1]
        frame = frame.f_back
    return "?"


def _current_scope() -> tuple[str, str, dict]:
    value = getattr(_scope, "value", None)
    if value is not None:
        return value
    return (f"{UNATTRIBUTED} ({_calling_module()})", "", {})


# --------------------------------------------------------------------------- #
# The recorder.
# --------------------------------------------------------------------------- #


class CallTelemetry:
    """The run's per-call record. Thread-safe; every entry swallows failures."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        exhaustions: Callable[[], Iterable[Any]] | None = None,
    ) -> None:
        """``exhaustions`` supplies the owning record's budget notes
        (:class:`~drawing_analyzer.resource_pressure.BudgetExhaustion`); an
        allotment the pipeline saw a stage exhaust starves that stage."""
        self._lock = threading.Lock()
        self._exhaustion_source = exhaustions
        self._clock = clock or _utc_now
        self._monotonic = monotonic
        self.records: list[CallRecord] = []
        self.calls_seen = 0
        self.dropped = 0
        self._started: dict[int, float] = {}
        self._batch_items: dict[tuple[str, str], CallRecord] = {}

    # -- writing ------------------------------------------------------------ #

    def _new_record(self, request: dict, *, transport: str, method: str) -> CallRecord | None:
        stage, item, limits = _current_scope()
        with self._lock:
            self.calls_seen += 1
            seq = self.calls_seen
            if len(self.records) >= MAX_STORED_CALLS:
                self.dropped += 1
                return None
            record = CallRecord(
                seq=seq, stage=stage, item=item, transport=transport, method=method,
                started_at=_iso(self._clock()), item_limits=dict(limits), **request,
            )
            self.records.append(record)
            return record

    def begin(self, kwargs: dict, *, method: str) -> CallRecord | None:
        """Open a record for one real-time request about to be sent."""
        try:
            record = self._new_record(
                describe_request(kwargs), transport=TRANSPORT_REAL_TIME, method=method,
            )
            if record is not None:
                with self._lock:
                    self._started[record.seq] = self._monotonic()
            return record
        except Exception:  # noqa: BLE001 - advisory, never fatal
            return None

    def finish(
        self,
        record: CallRecord | None,
        *,
        message: Any = None,
        error: BaseException | None = None,
        cancelled: bool = False,
    ) -> None:
        """Close a real-time record with its response, or with why it has none."""
        if record is None:
            return
        try:
            with self._lock:
                started = self._started.pop(record.seq, None)
            if started is not None:
                record.duration_seconds = max(0.0, self._monotonic() - started)
            if message is not None:
                for key, value in describe_response(message).items():
                    setattr(record, key, value)
            elif cancelled:
                record.outcome = OUTCOME_CANCELLED
            else:
                record.outcome = OUTCOME_ERROR
                if error is not None:
                    record.error = summarize_exc(error)
                    record.request_id = request_id_of(error) or ""
        except Exception:  # noqa: BLE001
            pass

    def note_batch_submit(
        self, batch_id: str, requests: Iterable[dict], *, items: dict | None = None,
    ) -> None:
        """One provisioning record per item of an accepted Message Batch."""
        try:
            items = dict(items or {})
            for req in requests:
                custom_id = str(_get(req, "custom_id") or "")
                params = _get(req, "params") or {}
                record = self._new_record(
                    describe_request(params), transport=TRANSPORT_BATCH, method="batch",
                )
                if record is None:
                    continue
                record.custom_id = custom_id
                record.batch_id = str(batch_id or "")
                record.outcome = OUTCOME_PENDING
                if items.get(custom_id):
                    record.item = str(items[custom_id])
                with self._lock:
                    self._started[record.seq] = self._monotonic()
                    self._batch_items[(record.batch_id, custom_id)] = record
        except Exception:  # noqa: BLE001
            pass

    def note_batch_results(self, batch_id: str, results: dict) -> None:
        """Fill the consumption side of a batch's items from its results stream.

        A result whose batch this run did not submit (receipt recovery at run
        start collects batches earlier runs submitted) gets a response-only
        record under the ``recovered_batch`` stage.
        """
        try:
            for custom_id, entry in dict(results or {}).items():
                key = (str(batch_id or ""), str(custom_id or ""))
                with self._lock:
                    record = self._batch_items.get(key)
                    started = self._started.pop(record.seq, None) if record else None
                if record is None:
                    record = self._new_record(
                        {}, transport=TRANSPORT_BATCH, method="batch",
                    )
                    if record is None:
                        continue
                    if record.stage.startswith(UNATTRIBUTED):
                        record.stage = "recovered_batch"
                    record.custom_id, record.batch_id = key[1], key[0]
                    with self._lock:
                        self._batch_items[key] = record
                elif record.outcome != OUTCOME_PENDING:
                    continue             # already filled (a harvest read it first)
                if started is not None:
                    record.duration_seconds = max(0.0, self._monotonic() - started)
                result = _get(entry, "result")
                kind = str(_get(result, "type") or "")
                if kind == "succeeded":
                    message = _get(result, "message")
                    for k, value in describe_response(message).items():
                        setattr(record, k, value)
                    if not record.model:
                        record.model = str(_get(message, "model") or "")
                elif kind == "canceled":
                    record.outcome = OUTCOME_CANCELLED
                elif kind == "expired":
                    record.outcome = OUTCOME_EXPIRED
                else:
                    record.outcome = OUTCOME_ERROR
                    error = _get(result, "error")
                    detail = _get(error, "message") or _get(_get(error, "error"), "message")
                    record.error = str(detail or kind or "errored")[:300]
        except Exception:  # noqa: BLE001
            pass

    # -- reading ------------------------------------------------------------ #

    def snapshot(self) -> list[CallRecord]:
        with self._lock:
            return list(self.records)

    def _exhaustions(self) -> list[Any]:
        try:
            return list(self._exhaustion_source() or ()) if self._exhaustion_source else []
        except Exception:  # noqa: BLE001 - advisory
            return []

    def stage_summaries(self) -> list[dict]:
        """Per-stage provisioning, consumption and headroom verdict, pipeline order."""
        records = self.snapshot()
        exhaustions = self._exhaustions()
        by_stage: dict[str, list[CallRecord]] = {}
        for record in records:
            by_stage.setdefault(record.stage, []).append(record)
        budget: dict[str, list[dict]] = {}
        for e in exhaustions or ():
            stage = canonical_stage(str(getattr(e, "stage", "") or ""))
            budget.setdefault(stage, []).append({
                "kind": str(getattr(e, "kind", "") or ""),
                "count": int(getattr(e, "count", 0) or 0),
                "detail": str(getattr(e, "detail", "") or ""),
            })
        for stage in budget:
            by_stage.setdefault(stage, [])
        return [
            _summarize_stage(stage, by_stage[stage], budget.get(stage, []))
            for stage in sorted(by_stage, key=_stage_sort_key)
        ]

    def model_map(self) -> list[dict]:
        """Where each model was called: one row per (model, stage)."""
        rows: dict[tuple[str, str], dict] = {}
        for record in self.snapshot():
            model = record.served_model or record.model or "(unknown)"
            row = rows.setdefault((model, record.stage), {
                "model": model, "stage": record.stage, "calls": 0,
                "real_time_calls": 0, "batch_calls": 0, "items": set(),
                "input_tokens": 0, "output_tokens": 0, "requested_as": set(),
            })
            row["calls"] += 1
            row["real_time_calls" if record.transport == TRANSPORT_REAL_TIME
                else "batch_calls"] += 1
            if record.item:
                row["items"].add(record.item)
            row["input_tokens"] += record.input_tokens
            row["output_tokens"] += record.output_tokens
            if record.served_model and record.model:
                row["requested_as"].add(record.model)
        out = []
        for (model, stage), row in sorted(
            rows.items(), key=lambda kv: (kv[0][0], _stage_sort_key(kv[0][1])),
        ):
            row = dict(row)
            row["items"] = len(row["items"])
            row["requested_as"] = sorted(row["requested_as"])
            out.append(row)
        return out

    @property
    def headroom_status(self) -> str:
        return _overall(self.stage_summaries())

    def summary_line(self) -> str:
        """One line for the run.log header, the GUI and the report."""
        try:
            stages = self.stage_summaries()
            return _summary_line(stages, self.calls_seen, self.dropped)
        except Exception as exc:  # noqa: BLE001 - advisory
            return f"{HEADROOM_NOT_ASSESSED} — headroom could not be derived ({type(exc).__name__})"

    def render_lines(self) -> list[str]:
        """The run.log *Agent provisioning & headroom* section body."""
        stages = self.stage_summaries()
        lines = [f"  headroom: {_summary_line(stages, self.calls_seen, self.dropped)}"]
        for s in stages:
            lines.extend(_stage_block(s))
        if not stages:
            lines.append("  (no model call was made — every stage was served from cache "
                         "or did not run)")
        return lines

    def render_model_map_lines(self) -> list[str]:
        """The run.log *Model calls by stage* section body."""
        rows = self.model_map()
        if not rows:
            return ["  (no model call was made)"]
        width = max(len(r["model"]) for r in rows) + 2
        lines = [
            f"  {'model':<{width}}{'stage':<18}{'calls':>7}{'real-time':>11}{'batch':>7}"
            f"{'items':>7}{'input tok':>13}{'output tok':>12}"
        ]
        for r in rows:
            line = (
                f"  {r['model']:<{width}}{r['stage']:<18}{r['calls']:>7}"
                f"{r['real_time_calls']:>11}{r['batch_calls']:>7}{r['items']:>7}"
                f"{r['input_tokens']:>13,}{r['output_tokens']:>12,}"
            )
            if r["requested_as"]:
                line += f"   (refusal fallback; requested {', '.join(r['requested_as'])})"
            lines.append(line)
        lines.append("  (cache hits make no model call and are not listed; see Usage)")
        return lines

    def to_dict(self) -> dict:
        """JSON-ready summary for ``run_manifest.json`` (no per-call rows)."""
        stages = self.stage_summaries()
        return {
            "headroom_status": _overall(stages),
            "summary": _summary_line(stages, self.calls_seen, self.dropped),
            "calls_recorded": len(self.records),
            "calls_seen": self.calls_seen,
            "calls_not_stored": self.dropped,
            "stages": stages,
            "model_map": self.model_map(),
            "thresholds": {
                "near_cap_fraction": NEAR_CAP_FRACTION,
                "max_stored_calls": MAX_STORED_CALLS,
            },
        }


# --------------------------------------------------------------------------- #
# Stage analysis (pure functions over records).
# --------------------------------------------------------------------------- #


def _stage_sort_key(stage: str) -> tuple[int, str]:
    try:
        return (_STAGE_ORDER.index(stage), stage)
    except ValueError:
        return (len(_STAGE_ORDER), stage)


def _tally(values: Iterable[Any]) -> dict:
    out: dict[str, int] = {}
    for value in values:
        key = "omitted" if value is None or value == "" else str(value)
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _ability_coverage(records: list[CallRecord], attr: str) -> str:
    on = sum(1 for r in records if getattr(r, attr))
    if not on:
        return "none"
    return "all" if on == len(records) else f"{on}/{len(records)}"


def _dropped_abilities(records: list[CallRecord]) -> list[str]:
    """Features a stage's early calls carried that its later calls did not.

    Every such feature is turned off for the process by a self-healing latch
    after a rejection (structured outputs, strict tools, the refusal-fallback
    beta, the investigation task budget), so a stage that started with one and
    lost it is a stage whose later calls ran with less than it was built for.
    """
    ordered = sorted(
        (r for r in records if r.transport == TRANSPORT_REAL_TIME), key=lambda r: r.seq,
    )
    dropped = []
    checks = (
        ("structured outputs", lambda r: r.structured_output),
        ("strict tool schemas", lambda r: r.strict_tools),
        ("refusal fallback", lambda r: r.refusal_fallback),
        ("task budget", lambda r: r.task_budget is not None),
    )
    for label, has in checks:
        seen_on = False
        for r in ordered:
            if has(r):
                seen_on = True
            elif seen_on:
                dropped.append(label)
                break
    return dropped


def _requested_tool_calls(record: CallRecord) -> int:
    return sum(record.tool_calls.values())


# How one call counts against a named item allotment (default: tool calls).
_ITEM_LIMIT_COUNTERS: dict[str, Callable[[CallRecord], int]] = {
    "pause_resumes": lambda r: 1 if r.outcome == OUTCOME_PAUSE_TURN else 0,
}


def _final_calls(records: list[CallRecord]) -> list[CallRecord]:
    """Each work item's last call (a call with no item is its own item)."""
    last: dict[str, CallRecord] = {}
    for r in sorted(records, key=lambda r: r.seq):
        last[r.item or f"#{r.seq}"] = r
    return list(last.values())


def _summarize_stage(stage: str, records: list[CallRecord], budget: list[dict]) -> dict:
    answered = [r for r in records if r.outcome not in ("", OUTCOME_PENDING, OUTCOME_ERROR,
                                                          OUTCOME_CANCELLED, OUTCOME_EXPIRED)]
    fractions = [r.output_fraction for r in answered if r.output_fraction is not None]
    cap_hits = [r for r in answered if r.outcome == OUTCOME_MAX_TOKENS]
    finals = _final_calls(records)
    final_cap_hits = [r for r in finals if r.outcome == OUTCOME_MAX_TOKENS]
    pauses = [r for r in answered if r.outcome == OUTCOME_PAUSE_TURN]
    final_pauses = [r for r in finals if r.outcome == OUTCOME_PAUSE_TURN]
    near_cap = [
        r for r in answered
        if r.outcome != OUTCOME_MAX_TOKENS and r.output_fraction is not None
        and r.output_fraction >= NEAR_CAP_FRACTION
    ]
    tools_offered: dict[str, int | None] = {}
    tool_calls: dict[str, int] = {}
    at_limit: dict[str, int] = {}
    tool_errors: dict[str, int] = {}
    for r in records:
        for name in r.tools:
            limit = r.tool_limits.get(name)
            prev = tools_offered.get(name)
            tools_offered[name] = limit if prev is None else (
                max(prev, limit) if limit is not None else prev
            )
        for name in set(r.tools) | set(r.tool_calls):
            uses = r.tool_uses(name)
            if uses:
                tool_calls[name] = tool_calls.get(name, 0) + uses
        for name in r.tools_at_limit:
            at_limit[name] = at_limit.get(name, 0) + 1
        for code, n in r.tool_errors.items():
            tool_errors[code] = tool_errors.get(code, 0) + n
    # Item-level allotments: how much of each did items ask for? Evidence
    # rounds count the tool calls the model requested across the item's turns
    # — a request past the remaining allotment is refused unexecuted, so this
    # can exceed the limit, and that is exactly the agent asking for more.
    # Pause resumes count the item's pause_turn stops.
    item_limits: dict[str, dict] = {}
    per_item: dict[str, dict[str, int]] = {}
    for r in records:
        for name, limit in r.item_limits.items():
            entry = item_limits.setdefault(name, {"limit": limit, "items": set(),
                                                  "items_at_limit": set(), "max_requested": 0})
            entry["limit"] = max(int(entry["limit"] or 0), int(limit or 0))
            entry["items"].add(r.item)
            counter = _ITEM_LIMIT_COUNTERS.get(name, _requested_tool_calls)
            used = per_item.setdefault(r.item, {}).get(name, 0) + counter(r)
            per_item[r.item][name] = used
            entry["max_requested"] = max(entry["max_requested"], used)
            if limit and used >= limit:
                entry["items_at_limit"].add(r.item)
    item_limits_out = {
        name: {
            "limit": e["limit"], "items": len(e["items"]),
            "items_at_limit": len(e["items_at_limit"]), "max_requested": e["max_requested"],
        }
        for name, e in sorted(item_limits.items())
    }
    durations = [r.duration_seconds for r in records
                 if r.duration_seconds is not None and r.transport == TRANSPORT_REAL_TIME]
    caps = [r.max_tokens for r in records if r.max_tokens]
    summary = {
        "stage": stage,
        "calls": len(records),
        "answered_calls": len(answered),
        "real_time_calls": sum(1 for r in records if r.transport == TRANSPORT_REAL_TIME),
        "batch_calls": sum(1 for r in records if r.transport == TRANSPORT_BATCH),
        "items": len({r.item for r in records if r.item}),
        "outcomes": _tally(r.outcome for r in records),
        "models": _tally(r.model for r in records),
        "served_by_fallback": _tally(r.served_model for r in records if r.served_model),
        "effort": _tally(r.effort for r in records),
        "model_effort_ceiling": {
            m: c for m, c in sorted({(r.model, r.model_effort_ceiling) for r in records
                                     if r.model and r.model_effort_ceiling})
        },
        "thinking": _tally(r.thinking for r in records),
        "max_tokens": {"min": min(caps), "max": max(caps)} if caps else None,
        "output_tokens_peak": max((r.output_tokens for r in answered), default=0),
        "output_fraction_peak": round(max(fractions), 4) if fractions else None,
        "output_fraction_mean": round(sum(fractions) / len(fractions), 4) if fractions else None,
        "near_cap_calls": len(near_cap),
        "max_tokens_stops": len(cap_hits),
        "max_tokens_unrecovered": len(final_cap_hits),
        "pause_turns": len(pauses),
        "pause_turns_unresolved": len(final_pauses),
        "refusals": sum(1 for r in answered if r.outcome == OUTCOME_REFUSAL),
        "forced_closes": sum(1 for r in records if r.forced_close),
        "errors": sum(1 for r in records if r.outcome == OUTCOME_ERROR),
        "cancelled": sum(1 for r in records if r.outcome == OUTCOME_CANCELLED),
        "no_result": sum(1 for r in records if r.outcome in (OUTCOME_PENDING, OUTCOME_EXPIRED)),
        "tools_offered": dict(sorted(tools_offered.items())),
        "tool_calls": dict(sorted(tool_calls.items())),
        "tool_limit_reached_calls": dict(sorted(at_limit.items())),
        "tool_errors": dict(sorted(tool_errors.items())),
        "task_budget": _tally(r.task_budget for r in records if r.task_budget is not None),
        "item_limits": item_limits_out,
        "abilities": {
            "structured_output": _ability_coverage(records, "structured_output"),
            "strict_tools": _ability_coverage(records, "strict_tools"),
            "refusal_fallback": _ability_coverage(records, "refusal_fallback"),
            "task_budget": _ability_coverage(records, "task_budget"),
        },
        "abilities_dropped": _dropped_abilities(records),
        "input_tokens": sum(r.input_tokens for r in records),
        "output_tokens": sum(r.output_tokens for r in records),
        "cache_read_tokens": sum(r.cache_read_tokens for r in records),
        "cache_write_tokens": sum(r.cache_write_tokens for r in records),
        "duration_total_seconds": round(sum(durations), 3) if durations else None,
        "duration_max_seconds": round(max(durations), 3) if durations else None,
        "budget_exhaustions": budget,
    }
    verdict, reasons = _stage_verdict(summary)
    summary["verdict"] = verdict
    summary["reasons"] = reasons
    return summary


def _plural(n: int, one: str, many: str | None = None) -> str:
    return one if n == 1 else (many or one + "s")


def _stage_verdict(s: dict) -> tuple[str, list[str]]:
    """``STARVED`` / ``TIGHT`` / ``ADEQUATE`` and the evidence for it.

    STARVED — the stage ran out of something it needed and the result shows it:
    a work item whose *last* call was still cut off at ``max_tokens``; a server
    tool that refused a use because ``max_uses`` was spent; a server-tool loop
    still paused when the resumes ran out; or an allotment the pipeline saw the
    stage exhaust (evidence rounds, per-run finding or reference cap, output
    cap, a batch abandoned by the time bound).

    TIGHT — it got what it needed, but with no margin, or with less than it was
    built for: a call at >= :data:`NEAR_CAP_FRACTION` of its cap, a cap hit a
    raised-cap retry recovered, a tool used up to its per-call limit, a work
    item that used its whole item allotment, a forced no-tools close, a
    recovered ``pause_turn``, or an ability lost mid-run.

    ADEQUATE — every call finished inside its limits with room to spare.

    NOT_ASSESSED — no call came back with a response (all failed, were
    stopped, or are batch items whose result was never read), so there is no
    consumption to judge; the stage's own status and the resource-pressure
    record say why.
    """
    starved: list[str] = []
    tight: list[str] = []
    if s["max_tokens_unrecovered"]:
        n = s["max_tokens_unrecovered"]
        starved.append(f"{n} work {_plural(n, 'item')} still cut off at max_tokens on the last call")
    exceeded = s["tool_errors"].get("max_uses_exceeded", 0)
    if exceeded:
        starved.append(f"a server tool refused {exceeded} {_plural(exceeded, 'use')}: max_uses spent")
    if s["pause_turns_unresolved"]:
        n = s["pause_turns_unresolved"]
        starved.append(f"{n} work {_plural(n, 'item')} still paused (pause_turn) when resumes ran out")
    for e in s["budget_exhaustions"]:
        starved.append(
            f"{e['kind']} x{e['count']}" + (f" ({e['detail']})" if e["detail"] else "")
        )
    recovered = s["max_tokens_stops"] - s["max_tokens_unrecovered"]
    if recovered > 0:
        tight.append(f"{recovered} {_plural(recovered, 'call')} hit max_tokens and were re-sent at a raised cap")
    if s["near_cap_calls"]:
        n = s["near_cap_calls"]
        tight.append(
            f"{n} {_plural(n, 'call')} used >= {NEAR_CAP_FRACTION:.0%} of max_tokens"
        )
    for name, n in s["tool_limit_reached_calls"].items():
        limit = s["tools_offered"].get(name)
        tight.append(
            f"{name} used its full per-call limit ({limit}) on {n} {_plural(n, 'call')}"
        )
    for name, info in s["item_limits"].items():
        if info["items_at_limit"]:
            n = info["items_at_limit"]
            tight.append(
                f"{n} {_plural(n, 'item')} asked for at least the {info['limit']} "
                f"{name.replace('_', ' ')} allowed"
            )
    if s["forced_closes"]:
        n = s["forced_closes"]
        tight.append(f"{n} forced no-tools {_plural(n, 'close')} (allotment reached)")
    recovered_pauses = s["pause_turns"] - s["pause_turns_unresolved"]
    if recovered_pauses > 0:
        tight.append(f"{recovered_pauses} pause_turn {_plural(recovered_pauses, 'stop')} resumed")
    for ability in s["abilities_dropped"]:
        tight.append(f"{ability} turned off mid-run (later calls ran without it)")
    if starved:
        return HEADROOM_STARVED, starved + tight
    if tight:
        return HEADROOM_TIGHT, tight
    if not s["answered_calls"]:
        return HEADROOM_NOT_ASSESSED, []
    return HEADROOM_ADEQUATE, []


def _overall(stages: list[dict]) -> str:
    worst = HEADROOM_NOT_ASSESSED
    for s in stages:
        if _VERDICT_RANK[s["verdict"]] > _VERDICT_RANK[worst]:
            worst = s["verdict"]
    return worst


def _summary_line(stages: list[dict], calls_seen: int, dropped: int) -> str:
    verdict = _overall(stages)
    flagged = [s for s in stages if s["verdict"] in (HEADROOM_STARVED, HEADROOM_TIGHT)]
    if flagged:
        body = "; ".join(f"{s['stage']} {s['verdict']}: {s['reasons'][0]}" for s in flagged)
    elif calls_seen:
        n_stages = sum(1 for s in stages if s["calls"])
        body = (
            f"{calls_seen} model {_plural(calls_seen, 'call')} across {n_stages} "
            f"{_plural(n_stages, 'stage')}; every call finished inside its output cap "
            "and tool limits"
        )
    else:
        body = "no model call was made (cache hits only, or no model stage ran)"
    if dropped:
        body += f" (analysis covers the first {calls_seen - dropped} of {calls_seen} calls)"
    return f"{verdict} — {body}"


def _fmt_tally(tally: dict) -> str:
    return ", ".join(f"{k} x{v}" for k, v in tally.items()) or "—"


def _stage_block(s: dict) -> list[str]:
    head = (
        f"  {s['stage']:<14}{s['verdict']:<14}{s['calls']} {_plural(s['calls'], 'call')}"
        f" (real-time {s['real_time_calls']}, batch {s['batch_calls']})"
    )
    if s["items"]:
        head += f" over {s['items']} {_plural(s['items'], 'item')}"
    pad = " " * 16
    lines = [head]
    if not s["calls"]:
        for reason in s["reasons"]:
            lines.append(f"{pad}! {reason}")
        return lines
    lines.append(f"{pad}model: {_fmt_tally(s['models'])}"
                 + (f" · served by refusal fallback: {_fmt_tally(s['served_by_fallback'])}"
                    if s["served_by_fallback"] else ""))
    ceiling = ", ".join(f"{m} accepts up to {c}" for m, c in s["model_effort_ceiling"].items())
    lines.append(
        f"{pad}effort: {_fmt_tally(s['effort'])}" + (f" ({ceiling})" if ceiling else "")
        + f" · thinking: {_fmt_tally(s['thinking'])}"
    )
    cap = s["max_tokens"]
    cap_text = "—" if not cap else (
        f"{cap['min']:,}" if cap["min"] == cap["max"] else f"{cap['min']:,}–{cap['max']:,}"
    )
    peak = s["output_fraction_peak"]
    mean = s["output_fraction_mean"]
    lines.append(
        f"{pad}max_tokens: {cap_text} · output used: peak "
        + ("—" if peak is None else f"{peak:.0%} ({s['output_tokens_peak']:,} tok)")
        + ("" if mean is None else f", mean {mean:.0%}")
        + f" · cap hits {s['max_tokens_stops']} (unrecovered {s['max_tokens_unrecovered']})"
    )
    if s["tools_offered"]:
        parts = []
        for name, limit in s["tools_offered"].items():
            used = s["tool_calls"].get(name, 0)
            parts.append(f"{name} used {used}" + (f" (max {limit}/call)" if limit else ""))
        lines.append(f"{pad}tools: " + ", ".join(parts))
    for name, info in s["item_limits"].items():
        lines.append(
            f"{pad}{name.replace('_', ' ')}: limit {info['limit']} per item · most requested "
            f"{info['max_requested']} · {info['items_at_limit']} of {info['items']} "
            f"{_plural(info['items'], 'item')} reached it"
        )
    if s["task_budget"]:
        lines.append(f"{pad}task budget (tokens): {_fmt_tally(s['task_budget'])}")
    abilities = [k.replace("_", " ") + f" {v}" for k, v in s["abilities"].items() if v != "none"]
    if abilities:
        lines.append(f"{pad}abilities sent: " + ", ".join(abilities))
    extra = []
    if s["errors"]:
        extra.append(f"{s['errors']} failed")
    if s["refusals"]:
        extra.append(f"{s['refusals']} declined (refusal)")
    if s["cancelled"]:
        extra.append(f"{s['cancelled']} cancelled")
    if s["no_result"]:
        extra.append(f"{s['no_result']} batch item(s) without a result")
    if s["duration_total_seconds"] is not None:
        extra.append(
            f"real-time call time {s['duration_total_seconds']:.1f}s "
            f"(longest {s['duration_max_seconds']:.1f}s)"
        )
    if extra:
        lines.append(f"{pad}" + " · ".join(extra))
    for reason in s["reasons"]:
        lines.append(f"{pad}! {reason}")
    return lines


# --------------------------------------------------------------------------- #
# Module-level forwarding to the run's recorder (no-op outside a run).
# --------------------------------------------------------------------------- #


def current() -> CallTelemetry | None:
    """The calling thread's run recorder, via the resource-pressure binding."""
    from . import resource_pressure

    return getattr(resource_pressure.current(), "calls", None)


def begin(kwargs: dict, *, method: str) -> CallRecord | None:
    recorder = current()
    return recorder.begin(kwargs, method=method) if recorder is not None else None


def finish(record: CallRecord | None, **outcome: Any) -> None:
    recorder = current()
    if recorder is not None and record is not None:
        recorder.finish(record, **outcome)


def note_batch_submit(batch_id: str, requests: Iterable[dict], *, items: dict | None = None) -> None:
    recorder = current()
    if recorder is not None:
        recorder.note_batch_submit(batch_id, requests, items=items)


def note_batch_results(batch_id: str, results: dict) -> None:
    recorder = current()
    if recorder is not None:
        recorder.note_batch_results(batch_id, results)
