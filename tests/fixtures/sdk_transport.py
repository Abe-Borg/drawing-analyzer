"""The real SDK over an in-process Anthropic API stand-in (remediation WP-02.2, WP-02.3).

The suite's fakes stand in for the SDK's *objects*; this stands in for the
*API* behind the real, installed SDK, so a test can send production's request
builders through the SDK's own code and see what it refuses before sending
(a ``TypeError`` for a keyword its method does not take, a ``ValueError`` for a
non-streaming ``create`` above its cap) and what it sends: the URL, the
``?beta=true`` query that marks the beta namespace, the ``anthropic-beta``
header and the JSON body. And, since WP-02.3, what production does with each
response shape the API sends (the shapes are ``tests/fixtures/sdk_responses.py``).

``AnthropicAPIStub(route)`` answers through ``httpx2.MockTransport`` (the SDK's
transport; nothing opens a socket):

- ``POST /v1/messages``: ``route(params)`` (any scripted fake's router, which
  returns a FakeMessage, or an API JSON dict) serialized as the API's JSON, or
  as an SSE stream when the body asks for one. The serving model is the
  requested one unless the reply names its own;
- the Message Batches endpoints: create (each item answered by ``route`` at
  submit), retrieve, results (JSONL at the batch's ``results_url``), cancel;
- the Files endpoints: upload and delete;
- ``POST /v1/messages/count_tokens``.

The defaults are the ordinary shape: a complete stream, every batch item
``succeeded``, a batch ``ended`` at the first retrieve, results in submit
order. Each is a knob (the owner's rules, WP-02.3):

- ``stream(record) -> (cut, end) | None`` stops a streamed reply early
  (``sdk_responses.CUTS`` x ``ENDS``: a clean end, an SSE ``error`` event, or a
  dropped connection, raised by the transport as the SDK would see it);
- ``batch_result(custom_id, params) -> dict | None`` answers an item with its
  own envelope (``sdk_responses.errored(...)``, ``CANCELED``, ``EXPIRED``, or
  ``PENDING``: not finished when the batch ends, so ``canceled`` after a cancel
  and ``expired`` otherwise);
- ``statuses`` is the ``processing_status`` each successive retrieve of a
  batch answers (the last repeats; note that the SDK's ``results()`` retrieves
  once more before it reads the JSONL);
- ``order`` is the results order: ``"submit"``, ``"reverse"``, or a function
  of the result lines.

``reject(record)`` may answer any request first (a 400 that names a feature,
to drive the self-healing latches). Every request is recorded in ``requests``.
"""
from __future__ import annotations

import dataclasses
import itertools
import json
from typing import Any, Callable, Iterator, Sequence

import anthropic
import httpx2
import pydantic

from tests.fixtures import sdk_responses as R


def model_items(obj: pydantic.BaseModel) -> Iterator[tuple[str, Any]]:
    """An SDK model's fields under the API's names, then its extra keys.

    A field whose Python name differs from its wire name carries an alias (a
    fallback block's ``from``, which is a Python keyword, is ``from_``), and
    the API's JSON uses the alias. The walk reads ``__dict__`` rather than
    ``model_dump``, because a fake built with ``model_construct`` may hold a
    value no serializer expects (a dict, a namespace)."""
    fields = type(obj).model_fields
    for name, value in obj.__dict__.items():
        info = fields.get(name)
        yield (info.alias if info is not None and info.alias else name), value
    yield from (obj.__pydantic_extra__ or {}).items()


def api_json(obj: Any) -> Any:
    """A fake response object (SDK models, dataclasses, namespaces, dicts) as API JSON."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [api_json(x) for x in obj]
    if isinstance(obj, dict):
        return {k: api_json(v) for k, v in obj.items()}
    if isinstance(obj, pydantic.BaseModel):
        return {k: api_json(v) for k, v in model_items(obj)}
    if dataclasses.is_dataclass(obj):
        return {f.name: api_json(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if hasattr(obj, "__dict__"):
        return {k: api_json(v) for k, v in vars(obj).items() if not k.startswith("_")}
    return obj


def message_json(message: Any, *, model: str) -> dict:
    """``message`` as the API's JSON, served for a request for ``model``.

    The serving model is the requested one unless the reply names its own: a
    fake built without a ``model`` (an SDK-model fake records the fields it was
    given) is served as ``model``, as the API serves an ordinary request."""
    out = api_json(message)
    given = getattr(message, "model_fields_set", None)
    if given is not None and "model" not in given:
        out["model"] = model
    else:
        out["model"] = out.get("model") or model
    out.setdefault("id", "msg_stub")
    out.setdefault("type", "message")
    out.setdefault("role", "assistant")
    out.setdefault("stop_sequence", None)
    usage = dict(out.get("usage") or {})
    usage.setdefault("input_tokens", 0)
    usage.setdefault("output_tokens", 0)
    out["usage"] = usage
    return out


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def message_sse(
    message: dict,
    *,
    cut: str | None = None,
    end: str = "eof",
    error: dict | None = None,
) -> bytes:
    """The event stream for ``message``: complete by default.

    ``cut`` stops it early (``sdk_responses.CUTS``); ``end="error"`` then adds
    an SSE ``error`` event (``error``, default an ``overloaded_error``). A
    dropped connection (``end="drop"``) is the transport's to raise, after
    these bytes: see :class:`AnthropicAPIStub`."""
    if end not in R.ENDS:
        raise ValueError(f"unknown end {end!r}; expected one of {R.ENDS}")
    parts = [_event(name, data) for name, data in R.cut_events(R.sse_events(message), cut)]
    if end == "error":
        parts.append(_event("error", error or R.stream_error()))
    return "".join(parts).encode()


#: What the transport raises when a stream's connection drops.
DROPPED = "peer closed connection without sending complete message body"


def sse_response(message: dict, *, cut: str | None = None, end: str = "eof",
                 error: dict | None = None) -> httpx2.Response:
    """An SSE response for ``message`` stopped at ``cut`` and ended by ``end``."""
    body = message_sse(message, cut=cut, end=end, error=error)

    def chunks():
        if body:
            yield body
        if end == "drop":
            raise httpx2.RemoteProtocolError(DROPPED)

    return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=chunks())


class AnthropicAPIStub:
    """An in-process Anthropic API for the real SDK; see the module docstring."""

    def __init__(
        self,
        route: Callable[[dict], Any],
        *,
        reject: Callable[[dict], httpx2.Response | None] | None = None,
        stream: Callable[[dict], tuple[str | None, str] | None] | None = None,
        batch_result: Callable[[str, dict], dict | None] | None = None,
        statuses: Sequence[str] = ("ended",),
        order: str | Callable[[list[dict]], list[dict]] = "submit",
    ) -> None:
        if not statuses:
            raise ValueError("statuses must name at least one processing_status")
        self.route = route
        self.reject = reject
        self.stream = stream
        self.batch_result = batch_result
        self.statuses = tuple(statuses)
        self.order = order
        self.requests: list[dict] = []
        self._batches: dict[str, list[dict]] = {}
        self._retrieves: dict[str, int] = {}
        self._canceled: set[str] = set()
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
                shape = self.stream(record) if self.stream is not None else None
                cut, end = shape if shape is not None else (None, "eof")
                return sse_response(message, cut=cut, end=end)
            return httpx2.Response(200, json=message)
        if path == "/v1/messages/count_tokens" and method == "POST":
            return httpx2.Response(200, json={"input_tokens": 1})
        if path == "/v1/messages/batches" and method == "POST":
            batch_id = f"msgbatch_{next(self._ids)}"
            self._batches[batch_id] = [
                {"custom_id": item["custom_id"], "result": self._item_result(item)}
                for item in body["requests"]
            ]
            return httpx2.Response(200, json=self._batch(batch_id, "in_progress"))
        if path.startswith("/v1/messages/batches/"):
            batch_id, _, tail = path[len("/v1/messages/batches/"):].partition("/")
            if tail == "results":
                lines = "\n".join(json.dumps(r) for r in self._results(batch_id))
                return httpx2.Response(200, content=lines.encode(),
                                       headers={"content-type": "application/binary"})
            if tail == "cancel":
                self._canceled.add(batch_id)
                return httpx2.Response(200, json=self._batch(batch_id, "canceling"))
            n = self._retrieves.get(batch_id, 0)
            self._retrieves[batch_id] = n + 1
            status = self.statuses[min(n, len(self.statuses) - 1)]
            return httpx2.Response(200, json=self._batch(batch_id, status))
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

    def _item_result(self, item: dict) -> dict:
        params = item["params"]
        if self.batch_result is not None:
            shaped = self.batch_result(item["custom_id"], dict(params))
            if shaped is not None:
                return shaped
        return R.succeeded(message_json(self.route(dict(params)), model=params.get("model", "")))

    def _results(self, batch_id: str) -> list[dict]:
        """The batch's result lines as the API reports them once it ended."""
        pending = R.CANCELED if batch_id in self._canceled else R.EXPIRED
        lines = [
            {**line, "result": pending if line["result"] == R.PENDING else line["result"]}
            for line in self._batches.get(batch_id, [])
        ]
        if self.order == "reverse":
            lines.reverse()
        elif callable(self.order):
            lines = list(self.order(lines))
        elif self.order != "submit":
            raise ValueError(f"unknown order {self.order!r}")
        return lines

    def _batch(self, batch_id: str, status: str) -> dict:
        n = len(self._batches.get(batch_id, []))
        ended = status == "ended"
        counts = {"processing": n, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}
        if ended:
            counts["processing"] = 0
            for line in self._results(batch_id):
                counts[line["result"]["type"]] += 1
        return {
            "id": batch_id, "type": "message_batch", "processing_status": status,
            "request_counts": counts,
            "ended_at": "2026-01-01T00:01:00Z" if ended else None,
            "created_at": "2026-01-01T00:00:00Z", "expires_at": "2026-01-02T00:00:00Z",
            "archived_at": None,
            "cancel_initiated_at": "2026-01-01T00:00:30Z" if batch_id in self._canceled else None,
            "results_url": (f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results"
                            if ended else None),
        }


def error_400(message: str) -> httpx2.Response:
    return httpx2.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error", "message": message}})
