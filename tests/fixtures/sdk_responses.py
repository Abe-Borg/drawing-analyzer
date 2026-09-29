"""Response shapes as the Anthropic API sends them (remediation WP-02.3, U26).

The suite's response side used to be one shape: a complete message whose cache
counters were 0, a batch whose every item succeeded, an event stream that
always reached ``message_stop``. Production reads other shapes in the field
(measured over the real SDK on 1.7.0 and 1.8.0): ``None`` usage counters, the
``cache_creation`` TTL split, ``iterations``, ``stop_details``, a ``fallback``
block between two text blocks, a serving model that is not the requested one,
nested batch errors, ``canceled`` and ``expired`` items, and streams that end
early or fail midway.

This module is the one vocabulary for those shapes, as the API's JSON (the
owner's rule, WP-02.3): ``tests/fixtures/sdk_transport.py`` serves it to the
real SDK, and the fakes in ``tests/fixtures/fake_anthropic.py`` parse the same
dicts with the SDK's own models. Where the SDK names a set (the batch error
types, the stream event order), it is read from the installed SDK, never
restated. ``tests/test_sdk_responses.py`` holds every builder to the SDK.
"""
from __future__ import annotations

import copy
import json
import typing
from typing import Any

from anthropic.types import ErrorObject

# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #

MODEL = "claude-opus-5"


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool_use(name: str, input: dict, *, id: str = "toolu_stub_1") -> dict:  # noqa: A002
    return {"type": "tool_use", "id": id, "name": name, "input": dict(input)}


def server_tool_use(*, web_search: int = 0, web_fetch: int = 0) -> dict:
    """``usage.server_tool_use``: both counters, as the API reports them."""
    return {"web_search_requests": web_search, "web_fetch_requests": web_fetch}


def iteration(
    kind: str = "message",
    *,
    model: str | None = MODEL,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
) -> dict:
    """One entry of the beta ``usage.iterations`` list (``message``,
    ``fallback_message``, ``compaction``...)."""
    out = {"type": kind, "input_tokens": input_tokens, "output_tokens": output_tokens,
           "cache_read_input_tokens": cache_read, "cache_creation_input_tokens": cache_write}
    if kind != "compaction":
        out["model"] = model
    return out


def usage(
    input_tokens: int = 100,
    output_tokens: int = 50,
    *,
    cache_read: int | None = 0,
    cache_write: int | None = 0,
    cache_split: tuple[int, int] | None = None,
    server_tools: dict | None = None,
    output_tokens_details: dict | None = None,
    iterations: list[dict] | None = None,
    fallback_credit: dict | None = None,
) -> dict:
    """A ``usage`` object. ``None`` for a counter is the API's null (the SDK
    types every counter but ``input_tokens``/``output_tokens`` as optional).
    ``cache_split`` is ``(5-minute, 1-hour)`` cache-write tokens: the
    ``cache_creation`` breakdown, whose sum is the flat ``cache_write``."""
    out: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_write,
        "server_tool_use": server_tools,
    }
    if cache_split is not None:
        five, hour = cache_split
        out["cache_creation"] = {"ephemeral_5m_input_tokens": five, "ephemeral_1h_input_tokens": hour}
        if cache_write == 0:
            out["cache_creation_input_tokens"] = five + hour
    if output_tokens_details is not None:
        out["output_tokens_details"] = output_tokens_details
    if iterations is not None:
        out["iterations"] = iterations
    if fallback_credit is not None:
        out["fallback_credit"] = fallback_credit
    return out


def message(
    content: list[dict] | None = None,
    *,
    model: str = MODEL,
    stop_reason: str | None = "end_turn",
    usage_: dict | None = None,
    stop_details: dict | None = None,
    id: str = "msg_stub",  # noqa: A002
) -> dict:
    """A Messages API response body."""
    out = {
        "id": id, "type": "message", "role": "assistant", "model": model,
        "content": list(content or []), "stop_reason": stop_reason, "stop_sequence": None,
        "usage": usage_ if usage_ is not None else usage(),
    }
    if stop_details is not None:
        out["stop_details"] = stop_details
    return out


def refusal_stop_details(
    category: str | None = "cyber",
    *,
    explanation: str | None = None,
    recommended_model: str | None = None,
) -> dict:
    """``stop_details`` on a refusal. ``recommended_model`` is beta-only."""
    out = {"type": "refusal", "category": category, "explanation": explanation}
    if recommended_model is not None:
        out["recommended_model"] = recommended_model
    return out


def fallback_block(from_model: str, to_model: str, *, category: str | None = "cyber") -> dict:
    """The beta ``fallback`` content block the refusal fallback leaves at the
    boundary between the declined model's output and the serving model's."""
    return {"type": "fallback", "from": {"model": from_model}, "to": {"model": to_model},
            "trigger": {"type": "refusal", "category": category}}


def splice_fallback(msg: dict, at: int, *, to_model: str, category: str | None = "cyber") -> dict:
    """``msg`` as a mid-output fallback returns it: its text split at ``at``
    around a ``fallback`` block, the rest of the content after, and the message
    relabelled with the serving model (the API relabels a non-streaming reply;
    the SDK's stream accumulator takes the model from the block)."""
    out = copy.deepcopy(msg)
    texts = [b for b in out["content"] if b.get("type") == "text"]
    rest = [b for b in out["content"] if b.get("type") != "text"]
    whole = "".join(b["text"] for b in texts)
    out["content"] = ([text(whole[:at]), fallback_block(out["model"], to_model, category=category),
                       text(whole[at:])] + rest)
    out["model"] = to_model
    return out


# --------------------------------------------------------------------------- #
# Batch results
# --------------------------------------------------------------------------- #

#: The installed SDK's batch-item error types (``ErrorObject``'s members).
ERROR_TYPES: tuple[str, ...] = tuple(
    typing.get_args(member.model_fields["type"].annotation)[0]
    for member in typing.get_args(typing.get_args(ErrorObject)[0])
)

CANCELED: dict = {"type": "canceled"}
EXPIRED: dict = {"type": "expired"}

#: For ``AnthropicAPIStub(batch_result=...)``: the item had not finished when
#: the batch ended. It reads ``canceled`` if the batch was canceled, else
#: ``expired`` (the API's rule for unprocessed requests).
PENDING: dict = {"type": "__pending__"}


def succeeded(msg: dict) -> dict:
    return {"type": "succeeded", "message": msg}


def errored(error_type: str, error_message: str = "boom", *, request_id: str | None = "req_stub") -> dict:
    """An ``errored`` item as the API nests it: the item's ``error`` is an
    error *response* (``type: "error"``) whose own ``error`` carries the type
    and message. A reader of ``result.error.type`` sees ``"error"``."""
    return {"type": "errored", "error": {
        "type": "error", "error": {"type": error_type, "message": error_message},
        "request_id": request_id}}


def individual(custom_id: str, result: dict) -> dict:
    """One line of a batch's results JSONL."""
    return {"custom_id": custom_id, "result": result}


# --------------------------------------------------------------------------- #
# Event streams
# --------------------------------------------------------------------------- #

#: Where a stream can stop, earliest first (``None``: it does not).
#: - ``empty``: no event at all;
#: - ``before_text``: ``message_start`` and the first block's start, no delta;
#: - ``after_text``: the first half of the first block, the block not closed;
#: - ``after_content``: every block closed, no ``message_delta``;
#: - ``before_message_stop``: everything but ``message_stop``.
CUTS: tuple[str, ...] = ("empty", "before_text", "after_text", "after_content", "before_message_stop")

#: How it stops: the body ends cleanly, an ``error`` event, or the connection drops.
ENDS: tuple[str, ...] = ("eof", "error", "drop")


def stream_error(error_type: str = "overloaded_error", error_message: str = "Overloaded") -> dict:
    """The body of an SSE ``error`` event."""
    return {"type": "error", "error": {"type": error_type, "message": error_message}}


def sse_events(msg: dict) -> list[tuple[str, dict]]:
    """The complete event sequence for ``msg``: ``message_start`` (usage with
    ``output_tokens`` 0), each block's start / delta(s) / stop, a
    ``message_delta`` carrying the stop reason and the **cumulative** usage,
    ``message_stop``. A text block's text arrives in two deltas."""
    head = {**msg, "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {**msg["usage"], "output_tokens": 0}}
    head.pop("stop_details", None)
    events: list[tuple[str, dict]] = [("message_start", {"type": "message_start", "message": head})]
    for i, block in enumerate(msg.get("content") or []):
        kind = block.get("type")
        if kind == "text":
            events.append(_block_start(i, {"type": "text", "text": ""}))
            whole = block.get("text", "")
            half = len(whole) // 2
            for piece in (whole[:half], whole[half:]):
                if piece:
                    events.append(_block_delta(i, {"type": "text_delta", "text": piece}))
        elif kind in ("tool_use", "server_tool_use"):
            events.append(_block_start(i, {**{k: v for k, v in block.items() if k != "input"}, "input": {}}))
            events.append(_block_delta(i, {"type": "input_json_delta",
                                           "partial_json": json.dumps(block.get("input") or {})}))
        else:
            events.append(_block_start(i, block))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    delta: dict[str, Any] = {"stop_reason": msg.get("stop_reason"), "stop_sequence": msg.get("stop_sequence")}
    if msg.get("stop_details") is not None:
        delta["stop_details"] = msg["stop_details"]
    events.append(("message_delta", {"type": "message_delta", "delta": delta, "usage": dict(msg["usage"])}))
    events.append(("message_stop", {"type": "message_stop"}))
    return events


def _block_start(index: int, block: dict) -> tuple[str, dict]:
    return ("content_block_start", {"type": "content_block_start", "index": index, "content_block": block})


def _block_delta(index: int, delta: dict) -> tuple[str, dict]:
    return ("content_block_delta", {"type": "content_block_delta", "index": index, "delta": delta})


def cut_events(events: list[tuple[str, dict]], cut: str | None) -> list[tuple[str, dict]]:
    """``events`` stopped at ``cut`` (one of :data:`CUTS`, or ``None``)."""
    if cut is None:
        return list(events)
    if cut not in CUTS:
        raise ValueError(f"unknown cut {cut!r}; expected one of {CUTS}")
    names = [name for name, _ in events]
    if cut == "empty":
        return []
    if cut == "before_message_stop":
        return events[:names.index("message_stop")]
    if cut == "after_content":
        return events[:names.index("message_delta")]
    first_delta = names.index("content_block_delta") if "content_block_delta" in names else None
    if first_delta is None:                     # no content: stop after the starts
        return events[:names.index("message_delta")]
    return events[:first_delta] if cut == "before_text" else events[:first_delta + 1]


def partial_message(msg: dict, cut: str | None) -> dict | None:
    """What the SDK's stream accumulator holds once the stream stops at
    ``cut``: the ``current_message_snapshot``, or what ``get_final_message``
    returns on a clean end. ``None`` for ``empty`` (the SDK has no snapshot).

    The rules are the SDK's (measured, ``tests/test_sdk_responses.py`` holds
    this to it at every cut): usage from ``message_start`` until a
    ``message_delta`` overwrites ``output_tokens`` and whichever optional
    counters it carries; no stop reason before ``message_delta``."""
    events = cut_events(sse_events(msg), cut)
    if not events:
        return None
    snap = copy.deepcopy(events[0][1]["message"])
    for name, data in events[1:]:
        if name == "content_block_start":
            snap["content"].append(copy.deepcopy(data["content_block"]))
        elif name == "content_block_delta":
            block = snap["content"][data["index"]]
            delta = data["delta"]
            if delta["type"] == "text_delta":
                block["text"] += delta["text"]
            elif delta["type"] == "input_json_delta":
                block["input"] = json.loads(delta["partial_json"])
        elif name == "message_delta":
            snap["stop_reason"] = data["delta"].get("stop_reason")
            snap["stop_sequence"] = data["delta"].get("stop_sequence")
            snap["stop_details"] = data["delta"].get("stop_details")
            snap["usage"]["output_tokens"] = data["usage"]["output_tokens"]
            for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                        "server_tool_use", "output_tokens_details", "iterations", "fallback_credit"):
                if data["usage"].get(key) is not None:
                    snap["usage"][key] = data["usage"][key]
    return snap
