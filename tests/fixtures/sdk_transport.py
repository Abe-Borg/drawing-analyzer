"""The real SDK over an in-process Anthropic API stand-in (remediation WP-02.2).

The suite's fakes stand in for the SDK's *objects*; this stands in for the
*API* behind the real, installed SDK, so a test can send production's request
builders through the SDK's own code and see what it refuses before sending
(a ``TypeError`` for a keyword its method does not take, a ``ValueError`` for a
non-streaming ``create`` above its cap) and what it sends: the URL, the
``?beta=true`` query that marks the beta namespace, the ``anthropic-beta``
header and the JSON body.

``AnthropicAPIStub(route)`` answers through ``httpx2.MockTransport`` (the SDK's
transport; nothing opens a socket):

- ``POST /v1/messages``: ``route(params)`` (any scripted fake's router, which
  returns a FakeMessage) serialized as the API's JSON, or as an SSE stream when
  the body asks for one;
- the Message Batches endpoints: create (each item answered by ``route`` at
  submit), retrieve (ended), results (JSONL at the batch's ``results_url``),
  cancel;
- the Files endpoints: upload and delete;
- ``POST /v1/messages/count_tokens``.

``reject(record)`` may answer any request first (a 400 that names a feature,
to drive the self-healing latches). Every request is recorded in ``requests``.
This is a transport stand-in, not a fidelity model of the API's responses:
nested batch errors, canceled envelopes, ``None`` usage fields and partial SSE
sequences are WP-02.3's.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
from typing import Any, Callable

import anthropic
import httpx2


def api_json(obj: Any) -> Any:
    """A fake response object (dataclasses, namespaces, dicts) as API JSON."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [api_json(x) for x in obj]
    if isinstance(obj, dict):
        return {k: api_json(v) for k, v in obj.items()}
    if dataclasses.is_dataclass(obj):
        return {f.name: api_json(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if hasattr(obj, "__dict__"):
        return {k: api_json(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def message_json(message: Any, *, model: str) -> dict:
    out = api_json(message)
    out.setdefault("id", "msg_stub")
    out.setdefault("type", "message")
    out.setdefault("role", "assistant")
    out["model"] = out.get("model") or model
    out.setdefault("stop_sequence", None)
    usage = dict(out.get("usage") or {})
    usage.setdefault("input_tokens", 0)
    usage.setdefault("output_tokens", 0)
    out["usage"] = usage
    return out


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def message_sse(message: dict) -> bytes:
    """A complete, well-formed event stream for ``message`` (message_stop included)."""
    head = {**message, "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {**message["usage"], "output_tokens": 0}}
    parts = [_event("message_start", {"type": "message_start", "message": head})]
    for i, block in enumerate(message.get("content") or []):
        kind = block.get("type")
        if kind == "text":
            start = {"type": "text", "text": ""}
            delta = {"type": "text_delta", "text": block.get("text", "")}
        elif kind in ("tool_use", "server_tool_use"):
            start = {**{k: v for k, v in block.items() if k != "input"}, "input": {}}
            delta = {"type": "input_json_delta", "partial_json": json.dumps(block.get("input") or {})}
        else:
            start, delta = block, None
        parts.append(_event("content_block_start",
                            {"type": "content_block_start", "index": i, "content_block": start}))
        if delta is not None:
            parts.append(_event("content_block_delta",
                                {"type": "content_block_delta", "index": i, "delta": delta}))
        parts.append(_event("content_block_stop", {"type": "content_block_stop", "index": i}))
    parts.append(_event("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": message.get("stop_reason"),
                  "stop_sequence": message.get("stop_sequence")},
        "usage": message["usage"],
    }))
    parts.append(_event("message_stop", {"type": "message_stop"}))
    return "".join(parts).encode()


class AnthropicAPIStub:
    """An in-process Anthropic API for the real SDK; see the module docstring."""

    def __init__(
        self,
        route: Callable[[dict], Any],
        *,
        reject: Callable[[dict], httpx2.Response | None] | None = None,
    ) -> None:
        self.route = route
        self.reject = reject
        self.requests: list[dict] = []
        self._batches: dict[str, list[dict]] = {}
        self._ids = itertools.count(1)

    # -- the SDK's side ------------------------------------------------------ #

    def client(self, **kwargs: Any) -> anthropic.Anthropic:
        """A real SDK client whose transport is this stub (no retries)."""
        key = "sk-ant-" + "stub-" + "0" * 20     # built at runtime: never a real key
        return anthropic.Anthropic(
            api_key=key, max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(self.handle)),
            **kwargs,
        )

    def messages(self) -> list[dict]:
        return [r for r in self.requests if r["path"] == "/v1/messages"]

    # -- the API's side ------------------------------------------------------ #

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        raw = request.read()
        body = None
        if raw and request.headers.get("content-type", "").startswith("application/json"):
            body = json.loads(raw)
        query = request.url.query
        record = {
            "method": request.method,
            "path": request.url.path,
            "query": query.decode("ascii") if isinstance(query, bytes) else str(query),
            "beta": request.headers.get("anthropic-beta"),
            "body": body,
        }
        self.requests.append(record)
        if self.reject is not None:
            refused = self.reject(record)
            if refused is not None:
                return refused
        return self._answer(request, record, raw)

    def _answer(self, request: httpx2.Request, record: dict, raw: bytes) -> httpx2.Response:
        path, method, body = record["path"], record["method"], record["body"]
        if path == "/v1/messages" and method == "POST":
            message = message_json(self.route(dict(body)), model=body.get("model", ""))
            if body.get("stream"):
                return httpx2.Response(200, headers={"content-type": "text/event-stream"},
                                       content=message_sse(message))
            return httpx2.Response(200, json=message)
        if path == "/v1/messages/count_tokens" and method == "POST":
            return httpx2.Response(200, json={"input_tokens": 1})
        if path == "/v1/messages/batches" and method == "POST":
            batch_id = f"msgbatch_{next(self._ids)}"
            self._batches[batch_id] = [
                {"custom_id": item["custom_id"], "result": {
                    "type": "succeeded",
                    "message": message_json(self.route(dict(item["params"])),
                                            model=item["params"].get("model", "")),
                }}
                for item in body["requests"]
            ]
            return httpx2.Response(200, json=self._batch(batch_id, "in_progress"))
        if path.startswith("/v1/messages/batches/"):
            batch_id, _, tail = path[len("/v1/messages/batches/"):].partition("/")
            if tail == "results":
                lines = "\n".join(json.dumps(r) for r in self._batches.get(batch_id, []))
                return httpx2.Response(200, content=lines.encode(),
                                       headers={"content-type": "application/binary"})
            if tail == "cancel":
                return httpx2.Response(200, json=self._batch(batch_id, "canceling"))
            return httpx2.Response(200, json=self._batch(batch_id, "ended"))
        if path == "/v1/files" and method == "POST":
            return httpx2.Response(200, json={
                "id": f"file_{next(self._ids)}", "type": "file", "filename": "sheet.png",
                "mime_type": "image/png", "size_bytes": len(raw),
                "created_at": "2026-01-01T00:00:00Z", "downloadable": False,
            })
        if path.startswith("/v1/files/") and method == "DELETE":
            return httpx2.Response(200, json={"id": path.rsplit("/", 1)[-1], "type": "file_deleted"})
        return httpx2.Response(404, json={"type": "error", "error": {
            "type": "not_found_error", "message": f"{method} {path}"}})

    def _batch(self, batch_id: str, status: str) -> dict:
        n = len(self._batches.get(batch_id, []))
        ended = status == "ended"
        return {
            "id": batch_id, "type": "message_batch", "processing_status": status,
            "request_counts": {"processing": 0 if ended else n, "succeeded": n if ended else 0,
                               "errored": 0, "canceled": 0, "expired": 0},
            "ended_at": "2026-01-01T00:01:00Z" if ended else None,
            "created_at": "2026-01-01T00:00:00Z", "expires_at": "2026-01-02T00:00:00Z",
            "archived_at": None, "cancel_initiated_at": None,
            "results_url": (f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results"
                            if ended else None),
        }


def error_400(message: str) -> httpx2.Response:
    return httpx2.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": message}})
