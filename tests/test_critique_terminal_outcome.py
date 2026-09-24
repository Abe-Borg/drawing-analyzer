"""A critique read the model did not finish is not a completed read (N4, critique).

Remediation WP-01.4. The critique adopts the D-1 classifier
(``core.terminal_outcome``): only ``end_turn`` and ``stop_sequence`` finish a
read. The critique declares no tools and never resumes a paused turn, so a
continuation (``tool_use``, ``pause_turn``, ``compaction``) is not finished
either. Before this slice ``critique.outcome_from_message`` read the stop reason
only to word an empty body, so a read cut off at ``max_tokens``, refused, ended
early or stopped for an unknown reason counted as COMPLETE whenever its
findings object parsed, was merged as corroboration and was cached at both
levels, on both transports.

The owner's rules (two rounds, measured first):

- such a read keeps **nothing**: no findings, no claims (so nothing reaches the
  arithmetic auditor), like a malformed read; its tokens stay billed;
- its error comes from the digest's one ladder, with the noun ``critique``
  (``digest_terminal_error(..., noun="critique")``); ``empty critique`` keeps
  its wording;
- the critique stage adopts D-2's item rule: eligible = sheets x requested
  reads, judged = reads that finished and parsed (a cache hit counts its
  reads); COMPLETE only when every read was judged, FAILED when none was,
  otherwise PARTIAL; the stage's items are reads (eligible -> judged) and a
  coverage line leads its warnings;
- the per-sheet usage record agrees with that rule;
- ``digest_cache._CRITIQUE_CACHE_CONTRACT`` 2 -> 3 retires every entry that
  could hold such a read (the entry shape is unchanged: no stored stop
  reasons, no read-side reject).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import drawing_analyzer.digest_cache as DC
from drawing_analyzer.batch_critique import (
    _outcome_from_envelope,
    collect_critique_batch,
    submit_critique_batch,
)
from drawing_analyzer.critique import (
    CRITIQUE_SYSTEM_PROMPT,
    STRUCTURED_OUTPUTS,
    _critique_read,
    critique_sheet_self_consistent,
    outcome_from_message,
)
from drawing_analyzer.core.api_config import MODEL_OPUS_5
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT, digest_terminal_error
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import (
    CONFIDENCE_NOT_ASSESSED_PARTIAL,
    CONFIDENCE_REPRODUCED,
    ImageTile,
    RenderedSheet,
    SheetRef,
)
from drawing_analyzer.pipeline import extract_drawing_context
from drawing_analyzer.review_planner import PLANNER_SYSTEM_PROMPT
from drawing_analyzer.set_identity import IDENTITY_SYSTEM_PROMPT
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeBatchResult,
    FakeBatchResultEnvelope,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    FinalMessageStream,
    StreamingMessagesMixin,
)

_NOOP = lambda _s: None  # noqa: E731 - tests never wait

F1 = {"sheet_id": "M-101", "category": "code", "severity": "low",
      "text": "Riser is undersized at the base of the stair.", "source_quote": "VAV-3",
      "tile_label": "r1c1"}
F2 = {"sheet_id": "M-101", "category": "code", "severity": "medium",
      "text": "Relief valve setting is above the rated pressure.", "source_quote": "ROOM 120",
      "tile_label": "r1c1"}
CLAIM = {"sheet_id": "M-101", "quote": "TOTAL 50", "kind": "sum",
         "terms": [20, 20], "expected": 50}


def _obj(findings, claims=()):
    return json.dumps({"findings": list(findings), "claims": list(claims)})


def _fenced(findings, claims=()):
    return "```json\n" + _obj(findings, claims) + "\n```"


# One parseable findings object, three ways a read can carry it.
BODIES = {
    "closed-empty": _fenced([]),
    "closed": _fenced([F1], [CLAIM]),
    "unclosed": "```json\n" + _obj([F1], [CLAIM]),
}

# Every stop reason that does not finish a critique read, with the error the
# shared ladder gives a read that carried text.
NOT_FINISHED = {
    "max": ("max_tokens", "truncated critique (stop_reason='max_tokens')"),
    "ctxwin": ("model_context_window_exceeded",
               "truncated critique (stop_reason='model_context_window_exceeded')"),
    "refusal": ("refusal", "refused critique (stop_reason='refusal')"),
    "none": (None, "unfinished critique (stop_reason=None)"),
    "tool": ("tool_use", "unfinished critique (stop_reason='tool_use')"),
    "pause": ("pause_turn", "unfinished critique (stop_reason='pause_turn')"),
    "compact": ("compaction", "unfinished critique (stop_reason='compaction')"),
    "unknown": ("not_a_stop_reason", "unfinished critique (stop_reason='not_a_stop_reason')"),
}
FINISHED = ("end_turn", "stop_sequence")


def _ref():
    return SheetRef(pdf_path=Path("s.pdf"), page_index=0, source_name="s.pdf", page_count=1)


def _rendered(sheet_text="VAV-3 SERVES ROOM 120"):
    return RenderedSheet(
        ref=_ref(),
        overview=ImageTile(png_bytes=b"OVERVIEW", width_px=100, height_px=80, kind="overview"),
        tiles=[ImageTile(png_bytes=b"TILE00", width_px=50, height_px=40, kind="tile",
                         row=0, col=0, label="r1c1")],
        page_width_pt=792, page_height_pt=612, rows=1, cols=1, sheet_text=sheet_text,
    )


def _message(text, stop, *, in_tok=100, out_tok=20, cache_read=0, cache_write=0):
    return FakeMessage(
        content=[FakeTextBlock(text=text)] if text else [],
        usage=FakeUsage(input_tokens=in_tok, output_tokens=out_tok,
                        cache_read_input_tokens=cache_read,
                        cache_creation_input_tokens=cache_write),
        stop_reason=stop,
    )


class _E400(Exception):
    def __init__(self, message="HTTP 400 bad request"):
        super().__init__(message)
        self.status_code = 400


class _Scripted(BetaClientMixin):
    """Real-time critique client: each call answers the next ``(text, stop)``
    or raises the next exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                item = outer.script[min(outer.calls, len(outer.script) - 1)]
                outer.calls += 1
                if isinstance(item, Exception):
                    raise item
                return _message(*item)

        self.messages = _Msgs()


def _critique_entries(cache):
    return [v for v in cache._entries.values()
            if isinstance(v, dict) and "completed_runs" in v]


# --------------------------------------------------------------------------- #
# The one ladder, with the critique's noun
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_ladder_names_the_critique(key):
    stop, expected = NOT_FINISHED[key]
    assert digest_terminal_error("text", stop, noun="critique") == expected


def test_ladder_order_and_the_empty_wording():
    # The stop reason is read first: a refusal is named even when empty; an
    # empty reply keeps the critique's old "empty critique" wording.
    assert digest_terminal_error("", "refusal", noun="critique") == (
        "refused critique (stop_reason='refusal')")
    assert digest_terminal_error("", "max_tokens", noun="critique") == (
        "empty critique (stop_reason='max_tokens')")
    assert digest_terminal_error("", "end_turn", noun="critique") == (
        "empty critique (stop_reason='end_turn')")
    for stop in FINISHED:
        assert digest_terminal_error("text", stop, noun="critique") is None


def test_ladder_keeps_the_digest_wording():
    assert digest_terminal_error("t", "max_tokens") == "truncated digest (stop_reason='max_tokens')"
    assert digest_terminal_error("t", "refusal") == "refused digest (stop_reason='refusal')"
    assert digest_terminal_error("", "end_turn") == "empty digest (stop_reason='end_turn')"
    assert digest_terminal_error("t", None) == "unfinished digest (stop_reason=None)"


# --------------------------------------------------------------------------- #
# One read: outcome_from_message (the single fix site; both transports)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("body", list(BODIES))
@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_unfinished_read_is_failed(key, body):
    stop, expected = NOT_FINISHED[key]
    oc = outcome_from_message(
        _message(BODIES[body], stop, cache_read=7, cache_write=9),
        run_id="critique_2", ref=_ref(), rows=1, cols=1,
    )
    assert oc.status == "FAILED" and not oc.ok
    assert oc.error == expected
    # It keeps nothing: no findings, no claims.
    assert oc.findings == [] and oc.claims == []
    # Every token it billed is still counted (plan §2 rule 8).
    assert (oc.input_tokens, oc.output_tokens) == (100, 20)
    assert (oc.cache_read_tokens, oc.cache_write_tokens) == (7, 9)


@pytest.mark.parametrize("body", list(BODIES))
@pytest.mark.parametrize("stop", FINISHED)
def test_finished_read_is_unchanged(stop, body):
    oc = outcome_from_message(
        _message(BODIES[body], stop), run_id="critique_1", ref=_ref(), rows=1, cols=1,
    )
    assert oc.status == "COMPLETE" and oc.error is None
    n = 0 if body == "closed-empty" else 1
    assert len(oc.findings) == n and len(oc.claims) == n
    assert all(f.sources == ["critique_1"] for f in oc.findings)


@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_unfinished_structured_read_is_failed(key):
    # Under output_config.format the reply is the bare object: it parses
    # whole even when the model was cut off after it.
    stop, expected = NOT_FINISHED[key]
    oc = outcome_from_message(
        _message(_obj([F1], [CLAIM]), stop), run_id="critique_1", ref=_ref(),
        rows=1, cols=1, structured=True,
    )
    assert oc.status == "FAILED" and oc.error == expected
    assert oc.findings == [] and oc.claims == []


@pytest.mark.parametrize("stop", FINISHED)
def test_finished_structured_read_is_unchanged(stop):
    oc = outcome_from_message(
        _message(_obj([F1], [CLAIM]), stop), run_id="critique_1", ref=_ref(),
        rows=1, cols=1, structured=True,
    )
    assert oc.status == "COMPLETE" and len(oc.findings) == 1 and len(oc.claims) == 1


def test_a_dict_reply_without_a_stop_reason_is_unfinished():
    msg = {"content": [{"type": "text", "text": BODIES["closed"]}],
           "usage": {"input_tokens": 10, "output_tokens": 5}}
    oc = outcome_from_message(msg, run_id="critique_1", ref=_ref(), rows=1, cols=1)
    assert oc.status == "FAILED"
    assert oc.error == "unfinished critique (stop_reason=None)"
    assert (oc.input_tokens, oc.output_tokens) == (10, 5)


def test_a_finished_malformed_read_still_fails_on_its_parse():
    oc = outcome_from_message(
        _message("```json\n{\"findings\": broken\n```", "end_turn"),
        run_id="critique_1", ref=_ref(), rows=1, cols=1,
    )
    assert oc.status == "FAILED"
    assert oc.error.startswith("critique produced no valid findings schema")


# --------------------------------------------------------------------------- #
# Real time: self-consistency, the merge and the level-2 cache
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_rt_both_reads_unfinished(key):
    stop, expected = NOT_FINISHED[key]
    cache = DigestCache(None, persist=False)
    client = _Scripted([(BODIES["closed"], stop), (BODIES["closed"], stop)])
    res = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                         runs=2, max_retries=0, sleep=_NOOP)
    assert (res.completed_runs, res.requested_runs) == (0, 2)
    assert res.findings == [] and res.claims == []
    assert res.error == f"{expected}; {expected}"
    assert (res.input_tokens, res.output_tokens) == (200, 40)
    assert _critique_entries(cache) == []


@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_rt_one_read_unfinished(key):
    stop, expected = NOT_FINISHED[key]
    cache = DigestCache(None, persist=False)
    client = _Scripted([(_fenced([F1]), "end_turn"), (_fenced([F1, F2], [CLAIM]), stop)])
    res = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                         runs=2, max_retries=0, sleep=_NOOP)
    assert (res.completed_runs, res.requested_runs) == (1, 2)
    # Only the finished read merges, and nothing it says is corroborated.
    assert [f.text for f in res.findings] == [F1["text"]]
    assert res.findings[0].confidence == CONFIDENCE_NOT_ASSESSED_PARTIAL
    assert res.findings[0].reproduced is False and res.findings[0].sources == ["critique_1"]
    assert res.claims == []
    assert res.read_errors == [expected]
    assert (res.input_tokens, res.output_tokens) == (200, 40)
    assert _critique_entries(cache) == []


def test_rt_a_finished_read_and_an_empty_cut_read():
    # A finished clean read beside a cut-off one is no clean sheet.
    cache = DigestCache(None, persist=False)
    client = _Scripted([(BODIES["closed-empty"], "end_turn"), (BODIES["closed"], "max_tokens")])
    res = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                         runs=2, max_retries=0, sleep=_NOOP)
    assert res.findings == [] and res.completed_runs == 1
    assert res.error == "truncated critique (stop_reason='max_tokens')"
    assert _critique_entries(cache) == []


def test_rt_a_single_read_run_that_is_cut_off():
    client = _Scripted([(BODIES["closed"], "max_tokens")])
    res = critique_sheet_self_consistent(_rendered(), client=client, runs=1,
                                         max_retries=0, sleep=_NOOP)
    assert res.completed_runs == 0 and res.findings == []
    assert res.error == "truncated critique (stop_reason='max_tokens')"


@pytest.mark.parametrize("stop", FINISHED)
def test_rt_finished_reads_merge_cache_and_serve(stop):
    cache = DigestCache(None, persist=False)
    client = _Scripted([(_fenced([F1], [CLAIM]), stop)] * 4)
    r1 = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                        runs=2, max_retries=0, sleep=_NOOP)
    assert r1.completed_runs == 2 and r1.error is None and r1.read_errors == []
    assert r1.findings[0].confidence == CONFIDENCE_REPRODUCED and len(r1.claims) == 1
    assert len(_critique_entries(cache)) == 1
    r2 = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                        runs=2, max_retries=0, sleep=_NOOP)
    assert client.calls == 2 and r2.cached
    assert [f.to_dict() for f in r2.findings] == [f.to_dict() for f in r1.findings]


def test_rt_finished_empty_reads_are_a_clean_sheet():
    cache = DigestCache(None, persist=False)
    client = _Scripted([(BODIES["closed-empty"], "end_turn")] * 2)
    res = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                         runs=2, max_retries=0, sleep=_NOOP)
    assert res.error is None and res.completed_runs == 2 and res.findings == []
    assert len(_critique_entries(cache)) == 1


@pytest.fixture
def _structured(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    STRUCTURED_OUTPUTS.reset()
    yield
    STRUCTURED_OUTPUTS.reset()


def test_rt_structured_read_cut_off(_structured):
    client = _Scripted([(_obj([F1], [CLAIM]), "max_tokens")])
    oc = _critique_read(_rendered(), run_id="critique_1", client=client,
                        model=MODEL_OPUS_5, max_retries=0, sleep=_NOOP)
    assert client.calls == 1 and STRUCTURED_OUTPUTS.available   # the schema was sent
    assert oc.status == "FAILED"
    assert oc.error == "truncated critique (stop_reason='max_tokens')"
    assert oc.findings == [] and oc.claims == []


def test_rt_structured_reads_finished_and_cut(_structured):
    cache = DigestCache(None, persist=False)
    client = _Scripted([(_obj([F1]), "end_turn"), (_obj([F1, F2]), "refusal")])
    res = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                         model=MODEL_OPUS_5, runs=2, max_retries=0,
                                         sleep=_NOOP)
    assert res.completed_runs == 1 and [f.text for f in res.findings] == [F1["text"]]
    assert res.read_errors == ["refused critique (stop_reason='refusal')"]
    assert _critique_entries(cache) == []


# --------------------------------------------------------------------------- #
# Batch: the envelope, the merge and the level-2 cache
# --------------------------------------------------------------------------- #


def _env(message):
    return FakeBatchResult(
        custom_id="sheet__0__r1",
        result=FakeBatchResultEnvelope(type="succeeded", message=message),
    )


@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_batch_envelope_unfinished(key):
    stop, expected = NOT_FINISHED[key]
    oc = _outcome_from_envelope(_env(_message(BODIES["closed"], stop)),
                                run_id="critique_1", ref=_ref(), rows=1, cols=1)
    assert oc.status == "FAILED" and oc.error == expected
    assert oc.findings == [] and (oc.input_tokens, oc.output_tokens) == (100, 20)


@pytest.mark.parametrize("stop", ["max_tokens", "refusal", None, "MISSING"])
def test_batch_envelope_dict_shaped(stop):
    message = {"content": [{"type": "text", "text": BODIES["closed"]}],
               "usage": {"input_tokens": 10, "output_tokens": 5}}
    if stop != "MISSING":
        message["stop_reason"] = stop
    env = {"custom_id": "sheet__0__r1", "result": {"type": "succeeded", "message": message}}
    oc = _outcome_from_envelope(env, run_id="critique_1", ref=_ref(), rows=1, cols=1)
    assert oc.status == "FAILED" and oc.findings == []
    assert oc.input_tokens == 10


@pytest.mark.parametrize("stop", FINISHED)
def test_batch_envelope_finished(stop):
    oc = _outcome_from_envelope(_env(_message(BODIES["closed"], stop)),
                                run_id="critique_1", ref=_ref(), rows=1, cols=1)
    assert oc.status == "COMPLETE" and len(oc.findings) == 1


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _BatchClient:
    """Files + Message Batches for the critique collector: every item of the
    batch answers from ``replies`` in submission order (terminal at once)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.submitted: list = []
        self.create_calls = 0
        self._n = 0
        self.files = _Obj(upload=self._upload, delete=lambda file_id: None)
        batches = _Obj(create=self._create, retrieve=self._retrieve, results=self._results,
                       cancel=lambda batch_id: _Obj(id=batch_id, processing_status="canceling"))
        self.messages = _Obj(batches=batches)
        self.beta = _Obj(messages=_Obj(batches=batches), files=self.files)

    def _upload(self, *, file):
        self._n += 1
        return _Obj(id=f"file_{self._n}")

    def _create(self, *, requests, betas=None):
        self.create_calls += 1
        self.submitted = list(requests)
        return _Obj(id="batch_1")

    def _retrieve(self, batch_id):
        n = len(self.submitted)
        return _Obj(processing_status="ended", request_counts=_Obj(
            succeeded=n, errored=0, canceled=0, expired=0, processing=0))

    def _results(self, batch_id):
        for i, req in enumerate(self.submitted):
            reply = self.replies[min(i, len(self.replies) - 1)]
            yield FakeBatchResult(
                custom_id=req["custom_id"],
                result=FakeBatchResultEnvelope(type="succeeded", message=_message(*reply)),
            )


def _batch_run(client, cache, runs=2):
    batch = submit_critique_batch(iter([_rendered()]), client=client, cache=cache,
                                  model=MODEL_OPUS_5, runs=runs, total=1)
    return collect_critique_batch(batch, client=client, cache=cache, sleep=_NOOP)


@pytest.fixture
def _one_upload_worker(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")


@pytest.mark.usefixtures("_one_upload_worker")
@pytest.mark.parametrize("key", list(NOT_FINISHED))
def test_batch_one_read_unfinished(key):
    stop, expected = NOT_FINISHED[key]
    cache = DigestCache(None, persist=False)
    client = _BatchClient([(_fenced([F1]), "end_turn"), (_fenced([F1, F2], [CLAIM]), stop)])
    ((_ref_, res),) = _batch_run(client, cache)
    assert (res.completed_runs, res.requested_runs) == (1, 2)
    assert [f.text for f in res.findings] == [F1["text"]] and res.claims == []
    assert res.findings[0].confidence == CONFIDENCE_NOT_ASSESSED_PARTIAL
    assert res.read_errors == [expected]
    assert (res.input_tokens, res.output_tokens) == (200, 40)
    assert _critique_entries(cache) == []


@pytest.mark.usefixtures("_one_upload_worker")
def test_batch_both_reads_unfinished():
    cache = DigestCache(None, persist=False)
    client = _BatchClient([(BODIES["unclosed"], "max_tokens")])
    ((_ref_, res),) = _batch_run(client, cache)
    assert res.completed_runs == 0 and res.findings == [] and res.error
    assert _critique_entries(cache) == []


@pytest.mark.usefixtures("_one_upload_worker")
def test_batch_finished_reads_cache_and_serve():
    cache = DigestCache(None, persist=False)
    ((_r, res),) = _batch_run(_BatchClient([(_fenced([F1]), "end_turn")]), cache)
    assert res.completed_runs == 2 and res.error is None
    assert len(_critique_entries(cache)) == 1
    second = _BatchClient([(_fenced([F1]), "end_turn")])
    ((_r, res2),) = _batch_run(second, cache)
    assert res2.cached and second.create_calls == 0


# --------------------------------------------------------------------------- #
# Through the pipeline, on both transports
# --------------------------------------------------------------------------- #


def _system_text(system) -> str:
    if isinstance(system, str):
        return system
    return "".join(b.get("text", "") for b in system or [] if isinstance(b, dict))


def _joined_text(params: dict) -> str:
    parts: list[str] = []
    for message in params.get("messages", []) or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


class _Pipe:
    """Every stage of an exhaustive run over a small set, on both critique
    transports (Hybrid mode runs the critique through Message Batches).

    ``critique`` maps a token of a sheet's text layer to that sheet's critique
    replies, in read order: ``(text, stop_reason)`` or an exception."""

    def __init__(self, critique):
        self.critique = {k: list(v) for k, v in critique.items()}
        self.seen: dict[str, int] = {}
        self.critique_calls = 0
        self._submitted: list = []
        self._n = 0
        self.files = _Obj(upload=self._upload, delete=lambda file_id: None)
        batches = _Obj(create=self._create, retrieve=self._retrieve, results=self._results,
                       cancel=lambda batch_id: _Obj(id=batch_id, processing_status="canceling"))
        self.messages = _Obj(stream=self._stream, create=self._direct, batches=batches)
        self.beta = _Obj(messages=_Obj(stream=self._stream, create=self._direct,
                                       batches=batches), files=self.files)

    def _critique_reply(self, params):
        text = _joined_text(params)
        token = next(t for t in self.critique if t in text)
        n = self.seen.get(token, 0)
        self.seen[token] = n + 1
        self.critique_calls += 1
        seq = self.critique[token]
        item = seq[min(n, len(seq) - 1)]
        if isinstance(item, Exception):
            raise item
        return _message(*item)

    def _reply(self, params):
        system = _system_text(params.get("system", ""))
        if system == VERIFY_SYSTEM_PROMPT:
            return _message('{"verdict":"CONFIRMED","note":"seen"}', "end_turn", 40, 8)
        if system.startswith(CRITIQUE_SYSTEM_PROMPT):
            return self._critique_reply(params)
        if system.startswith(DIGEST_SYSTEM_PROMPT):
            return _message("Sheet M-101 - Mechanical - Plan\nVAV-3 serves the room.",
                            "end_turn", 500, 80)
        if system == IDENTITY_SYSTEM_PROMPT:
            payload = {"disciplines": ["mechanical"], "jurisdiction": "", "language": "en",
                       "units": "imperial", "adopted_codes": [], "confidence": "medium"}
            return _message("```json\n" + json.dumps(payload) + "\n```", "end_turn", 30, 10)
        if system == PLANNER_SYSTEM_PROMPT:
            plan = {"plans": [{"discipline": "mechanical", "title": "Mech QC", "items": [
                {"text": "Flag a relief valve set above its rated pressure.",
                 "severity": "medium", "refs": []}]}]}
            return _message("```json\n" + json.dumps(plan) + "\n```", "end_turn", 30, 10)
        return _message("ok", "end_turn", 1, 1)

    def _stream(self, **kw):
        kw.pop("betas", None)
        kw.pop("fallbacks", None)
        return FinalMessageStream(self._reply(kw))

    def _direct(self, **kw):
        kw.pop("betas", None)
        kw.pop("fallbacks", None)
        return self._reply(kw)

    def _upload(self, *, file):
        self._n += 1
        return _Obj(id=f"file_{self._n}")

    def _create(self, *, requests, betas=None):
        self._submitted = []
        for r in requests:
            try:
                env = FakeBatchResultEnvelope(type="succeeded", message=self._reply(r["params"]))
            except _E400 as exc:
                env = FakeBatchResultEnvelope(type="errored", error=_Obj(
                    error=_Obj(type="invalid_request_error", message=str(exc))))
            self._submitted.append((r, env))
        return _Obj(id="batch_1")

    def _retrieve(self, batch_id):
        n = len(self._submitted)
        return _Obj(processing_status="ended", request_counts=_Obj(
            succeeded=n, errored=0, canceled=0, expired=0, processing=0))

    def _results(self, batch_id):
        for req, env in self._submitted:
            yield FakeBatchResult(custom_id=req["custom_id"], result=env)


def _pdf(tmp_path, tokens=("SHEET M-101 VAV-3 SERVES ROOM 120 TOTAL 50",)):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for token in tokens:
        doc.new_page(width=792, height=612).insert_text((72, 100), token)
    path = tmp_path / "M-101.pdf"
    doc.save(str(path))
    doc.close()
    return path


def _run(tmp_path, client, cache, transport, work="q1", src=None):
    return extract_drawing_context(
        [src or _pdf(tmp_path)], client=client, rows=2, cols=2, qc_markups=True,
        cache=cache, qc_work_dir=tmp_path / work,
        use_batch=False, critique_use_batch=(transport == "batch"),
    )


def _stage(ctx, name="critique"):
    return next(s for s in ctx.stage_results if s.stage == name)


def _critique_records(ctx):
    return [r for r in ctx.run_usage.records if r.stage_family == "critique"]


TOKEN = "SHEET M-101"
FINISHED_PAIR = [(_fenced([F1]), "end_turn"), (_fenced([F1]), "end_turn")]
TRANSPORTS = ["realtime", "batch"]


@pytest.fixture(autouse=True)
def _sequential(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("key", ["max", "refusal", "none", "unknown"])
def test_pipeline_one_read_unfinished(tmp_path, transport, key):
    stop, expected = NOT_FINISHED[key]
    cache = DigestCache(None, persist=False)
    client = _Pipe({TOKEN: [(_fenced([F1]), "end_turn"),
                            (_fenced([F1, F2], [CLAIM]), stop)]})
    ctx = _run(tmp_path, client, cache, transport)
    stage = _stage(ctx)
    assert client.critique_calls == 2
    assert stage.status == "PARTIAL"
    assert (stage.items_in, stage.items_out) == (2, 1)
    assert stage.warnings[0] == (
        "critique: 1 of 2 requested read(s) judged; 0 skipped, 1 returned no judgment")
    assert len(stage.errors) == 1
    assert stage.errors[0].endswith(f": 1 of 2 critique read(s) finished: {expected}")
    assert any(e.startswith("Critique: 1 sheet(s)") for e in ctx.errors)
    assert ctx.qc_status == "PARTIAL"
    # The cut read left nothing: no finding of its own, no claim for the auditor.
    texts = [f.text for f in ctx.all_findings]
    assert F2["text"] not in texts
    assert not [f for f in ctx.all_findings if f.claim_discriminator]
    kept = next(f for f in ctx.all_findings if f.text == F1["text"])
    assert kept.confidence == CONFIDENCE_NOT_ASSESSED_PARTIAL
    # Both reads billed; the sheet's record says what the stage says.
    (rec,) = _critique_records(ctx)
    assert (rec.input_tokens, rec.output_tokens) == (200, 40)
    assert (rec.terminal_status, rec.parse_success) == ("PARTIAL", False)
    # Neither level stored it, so the next run reads the sheet again.
    assert _critique_entries(cache) == []
    warm = _Pipe({TOKEN: FINISHED_PAIR})
    ctx2 = _run(tmp_path, warm, cache, transport, work="q2")
    assert warm.critique_calls == 2
    assert _stage(ctx2).status == "COMPLETE"
    assert (_stage(ctx2).items_in, _stage(ctx2).items_out) == (2, 2)


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("key", ["max", "ctxwin", "none", "pause"])
def test_pipeline_both_reads_unfinished(tmp_path, transport, key):
    stop, expected = NOT_FINISHED[key]
    cache = DigestCache(None, persist=False)
    client = _Pipe({TOKEN: [(_fenced([F1, F2], [CLAIM]), stop)]})
    ctx = _run(tmp_path, client, cache, transport)
    stage = _stage(ctx)
    assert stage.status == "FAILED"
    assert (stage.items_in, stage.items_out) == (2, 0)
    assert stage.warnings[0] == (
        "critique: 0 of 2 requested read(s) judged; 0 skipped, 2 returned no judgment")
    assert stage.errors[0].endswith(f": {expected}; {expected}")
    assert ctx.qc_status == "PARTIAL"
    assert not [f for f in ctx.all_findings if any(s.startswith("critique") for s in f.sources)]
    (rec,) = _critique_records(ctx)
    assert (rec.terminal_status, rec.parse_success) == ("FAILED", False)
    assert (rec.input_tokens, rec.output_tokens) == (200, 40)
    assert _critique_entries(cache) == []


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_pipeline_second_read_raises(tmp_path, transport):
    # The gap: read 1 ships a finding and read 2 fails outright. The stage
    # read COMPLETE, cached nothing, and re-billed every warm run as COMPLETE.
    cache = DigestCache(None, persist=False)
    client = _Pipe({TOKEN: [(_fenced([F1]), "end_turn"), _E400()]})
    ctx = _run(tmp_path, client, cache, transport)
    stage = _stage(ctx)
    assert stage.status == "PARTIAL"
    assert (stage.items_in, stage.items_out) == (2, 1)
    assert "1 of 2 critique read(s) finished: " in stage.errors[0]
    assert "HTTP 400" in stage.errors[0]
    (rec,) = _critique_records(ctx)
    assert rec.terminal_status == "PARTIAL"
    assert _critique_entries(cache) == []


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_pipeline_every_read_raises(tmp_path, transport):
    client = _Pipe({TOKEN: [_E400()]})
    ctx = _run(tmp_path, client, DigestCache(None, persist=False), transport)
    stage = _stage(ctx)
    assert stage.status == "FAILED" and (stage.items_in, stage.items_out) == (2, 0)
    assert _critique_records(ctx)[0].terminal_status == "FAILED"


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_pipeline_finished_reads_are_complete(tmp_path, transport):
    cache = DigestCache(None, persist=False)
    client = _Pipe({TOKEN: FINISHED_PAIR})
    ctx = _run(tmp_path, client, cache, transport)
    stage = _stage(ctx)
    assert stage.status == "COMPLETE" and stage.errors == [] and stage.warnings == []
    assert (stage.items_in, stage.items_out) == (2, 2)
    kept = next(f for f in ctx.all_findings if f.text == F1["text"])
    assert kept.confidence == CONFIDENCE_REPRODUCED
    (rec,) = _critique_records(ctx)
    assert (rec.terminal_status, rec.parse_success) == ("COMPLETE", True)
    assert len(_critique_entries(cache)) == 2          # level 1 and level 2
    warm = _Pipe({TOKEN: FINISHED_PAIR})
    ctx2 = _run(tmp_path, warm, cache, transport, work="q2")
    stage2 = _stage(ctx2)
    assert warm.critique_calls == 0
    assert stage2.status == "COMPLETE" and (stage2.items_in, stage2.items_out) == (2, 2)
    (rec2,) = _critique_records(ctx2)
    assert (rec2.transport, rec2.terminal_status) == ("CACHE", "COMPLETE")


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_pipeline_finished_empty_reads_are_a_clean_sheet(tmp_path, transport):
    cache = DigestCache(None, persist=False)
    client = _Pipe({TOKEN: [(BODIES["closed-empty"], "end_turn")]})
    ctx = _run(tmp_path, client, cache, transport)
    assert _stage(ctx).status == "COMPLETE"
    assert len(_critique_entries(cache)) == 2


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_pipeline_two_sheets_one_cut(tmp_path, transport):
    src = _pdf(tmp_path, tokens=("SHEET M-101 VAV-3", "SHEET M-102 PANEL LP-2"))
    client = _Pipe({"SHEET M-101": FINISHED_PAIR,
                    "SHEET M-102": [(_fenced([]), "end_turn"),
                                    (_fenced([F2]), "model_context_window_exceeded")]})
    cache = DigestCache(None, persist=False)
    ctx = _run(tmp_path, client, cache, transport, src=src)
    stage = _stage(ctx)
    assert stage.status == "PARTIAL" and (stage.items_in, stage.items_out) == (4, 3)
    assert len(stage.errors) == 1 and "page 2/2" in stage.errors[0]
    # Only the finished sheet is stored, at both levels.
    assert len(_critique_entries(cache)) == 2
    statuses = sorted(r.terminal_status for r in _critique_records(ctx))
    assert statuses == ["COMPLETE", "PARTIAL"]


def test_pipeline_a_sheet_with_no_input_is_skipped(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page(width=792, height=612).insert_text((72, 100), TOKEN)
    doc.new_page(width=999999, height=999999)          # never renders
    src = tmp_path / "mixed.pdf"
    doc.save(str(src))
    doc.close()
    client = _Pipe({TOKEN: FINISHED_PAIR})
    ctx = _run(tmp_path, client, None, "realtime", src=src)
    stage = _stage(ctx)
    assert stage.status == "PARTIAL" and (stage.items_in, stage.items_out) == (4, 2)
    assert stage.warnings[0] == (
        "critique: 2 of 4 requested read(s) judged; 2 skipped, 0 returned no judgment")


@pytest.mark.parametrize("transport", TRANSPORTS)
def test_pipeline_an_entry_stored_under_contract_2_misses(tmp_path, transport, monkeypatch):
    # An entry written before this slice may hold a read the model did not
    # finish, merged as complete. The contract bump makes every one of them
    # miss once, and none is deleted.
    old = {TOKEN: [(_fenced([F1]), "end_turn")]}
    new_text = "Relief valve is not shown on the riser detail."
    new = {TOKEN: [(_fenced([dict(F1, text=new_text)]), "end_turn")]}
    cache = DigestCache(None, persist=False)
    with monkeypatch.context() as m:
        m.setattr(DC, "_CRITIQUE_CACHE_CONTRACT", 2)
        _run(tmp_path, _Pipe(old), cache, transport, work="q1")
    stored = {k: copy.deepcopy(v) for k, v in cache._entries.items() if "completed_runs" in v}
    assert len(stored) == 2
    warm = _Pipe(new)
    ctx = _run(tmp_path, warm, cache, transport, work="q2")
    assert warm.critique_calls == 2                    # read again, not served
    texts = {f.text for f in ctx.all_findings}
    assert new_text in texts and F1["text"] not in texts
    for key, entry in stored.items():                  # left on disk, unchanged
        assert cache._entries[key] == entry
    assert len(_critique_entries(cache)) == 4
