"""Cross-QC terminal honesty (remediation WP-06.3; U6, U7 observability, N14).

The owner's rules, decided with measured case tables (seven choices, two rounds;
``_plans/DECISIONS.md`` D-1's, D-2's and D-4's WP-06.3 notes):

1. **Every cross-QC call streams** (whole-set, shard map, reconcile) through
   ``digest.stream_reply`` with the module's own ``stream_message``: one
   transport, transient failures and interrupted streams retried, a partial
   read judged like any reply.
2. **A reply stopped at ``max_tokens`` gets one retry** at twice the cap, up to
   ``digest.MAX_TOKENS_RETRY_CEILING``, clamped by the model (32,000), on every
   path. The digest's rank decides which read is kept (N16); a discarded
   attempt is named in the error.
3. **A reply cut off** (``max_tokens``, the context window, no stop reason) keeps
   the complete items of its ``findings`` / ``facts`` / ``claims`` arrays, each
   validated and grounded as usual; the item it was cut in is dropped and
   counted; the call stays failed and is never cached. A refusal, a
   continuation or an unknown stop keeps nothing.
4. **Status:** the stage is FAILED when it obtained nothing (the failure flag
   before counts, D-2's all-failed rule at the call level), PARTIAL when any
   call failed or was cut, COMPLETE otherwise. The error is the ladder's, with
   a noun per call (``cross-qc``, ``cross-qc shard``, ``cross-qc
   reconciliation``), and a reconcile failure says why.
5. **N14:** a result short only by its budget (text omitted, the findings cap)
   is cached with its PARTIAL status and replayed warm; anything with a failed
   or cut-off call never is.
6. **U7:** a fact past the per-shard cap, a fact or a leg that is not an object
   is counted (``CrossQCDiscardCounts``) and named in one observational warning.
7. **No client:** the stage reads FAILED, never COMPLETE beside its error.

Every reply goes through the real SDK over
``tests/fixtures/sdk_transport.AnthropicAPIStub``.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

import drawing_analyzer.cross_qc as X
import drawing_analyzer.digest as D
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import SheetGeometry, SheetRef
from tests.fixtures import sdk_responses as R
from tests.fixtures.sdk_transport import AnthropicAPIStub
# The contract tests' autouse fixture: every self-healing latch starts on.
from tests.test_sdk_contract import _fresh_latches  # noqa: F401

QA, QB = "VAV-3 SERVES ROOM 120", "EQUIPMENT SCHEDULE SHOWN"
W, H = 792.0, 612.0
_NOOP = lambda *_a, **_k: None  # noqa: E731
CAP = 16_000
RAISED = 32_000


# --------------------------------------------------------------------------- #
# A two-sheet set and a cross-QC route that answers every path
# --------------------------------------------------------------------------- #


def _geom(source_id: str, sid: str, text: str) -> SheetGeometry:
    ref = SheetRef(pdf_path=Path(f"/set/{sid}.pdf"), page_index=0,
                   source_name=f"{sid}.pdf", page_count=1, source_id=source_id)
    return SheetGeometry(
        ref=ref, page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=[(W - 300, H - 160, W - 240, H - 148, sid, 0, 0, 0)],
        sheet_text=f"{sid} title. {text} sheet text layer",
    )


def _set(text_a: str = QA, text_b: str = QB):
    from drawing_analyzer.digest import SheetDigest

    geoms = [_geom("SRC-0001", "M-101", text_a), _geom("SRC-0002", "M-102", text_b)]
    sheets = [SheetDigest(ref=g.ref, text=f"Sheet {g.ref.source_name} digest.") for g in geoms]
    return sheets, geoms


def _finding(n: int) -> dict:
    return {"sheet_handle": "S001", "category": "conflict", "severity": "medium",
            "text": f"Conflict {n}: the VAV-3 note on M-101 disagrees with the M-102 schedule.",
            "recommended_action": "Confirm with the engineer of record.",
            "source_quote": QA, "also_on": [{"sheet_handle": "S002", "source_quote": QB}]}


def _claim(handle: str) -> dict:
    return {"sheet_id": handle, "quote": QA, "kind": "sum", "terms": [100, 20],
            "expected": 120, "note": "room total"}


def _path(params: dict) -> str | None:
    system = params.get("system")
    if isinstance(system, list):
        system = "".join(b.get("text", "") for b in system if isinstance(b, dict))
    if system == X.cross_qc_system_prompt():
        return "whole_set"
    if system == X.cross_qc_map_system_prompt():
        return "map"
    if system == X.CROSS_QC_RECONCILE_SYSTEM_PROMPT:
        return "reconcile"
    return None


def _reply_object(params: dict) -> dict:
    path = _path(params)
    if path == "map":
        user = json.dumps(params.get("messages", []))
        facts = []
        for handle, quote in (("S001", QA), ("S002", QB)):
            if f"SHEET {handle} =" in user:
                facts += [{"sheet_handle": handle, "entity_or_tag": tag, "attribute": "note",
                           "value": quote, "exact_quote": quote, "context": "general note"}
                          for tag in ("VAV-3", "SCHED")]
        return {"findings": [], "claims": [], "facts": facts}
    return {"findings": [_finding(1), _finding(2)], "claims": [_claim("S001")]}


def _fenced(obj: dict) -> str:
    return "```json\n" + json.dumps(obj, indent=1) + "\n```"


def _body(params: dict) -> dict:
    return R.message([R.text(_fenced(_reply_object(params)))],
                     model=params.get("model", ""), usage_=R.usage(800, 60))


def _route(shape=None, target: str = "whole_set", times: int = 1):
    """Ordinary replies on every path; ``shape(body, obj)`` reshapes the first
    ``times`` replies on ``target``."""
    seen = {"n": 0}

    def route(params: dict) -> dict:
        body = _body(params)
        if shape is not None and _path(params) == target:
            seen["n"] += 1
            if seen["n"] <= times:
                body = shape(body, _reply_object(params))
        return body

    return route


def _cross_requests(stub: AnthropicAPIStub) -> list[dict]:
    return [r["body"] for r in stub.requests if r["path"] == "/v1/messages" and _path(r["body"])]


def _run(stub: AnthropicAPIStub, *, cache=None, sharded: bool = False, monkeypatch=None,
         sheets=None):
    if sharded:
        # Two one-sheet shards, mapped in order on one worker (deterministic).
        monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
        monkeypatch.setenv("DRAWING_ANALYZER_CROSS_QC_WORKERS", "1")
    s, g = sheets if sheets is not None else _set()
    return X.cross_sheet_qc(s, g, client=stub.client(), cache=cache, sleep=_NOOP)


def _warm_requests(cache, *, sharded=False, monkeypatch=None) -> int:
    stub = AnthropicAPIStub(_route())
    _run(stub, cache=cache, sharded=sharded, monkeypatch=monkeypatch)
    return len(_cross_requests(stub))


# --------------------------------------------------------------------------- #
# Shapes
# --------------------------------------------------------------------------- #


def _stop(stop):
    def shape(body, obj):
        body["stop_reason"] = stop
        return body
    return shape


def _no_fence(body, obj):
    body["content"] = [R.text("```json\n" + json.dumps(obj, indent=1) + "\n")]
    body["stop_reason"] = "max_tokens"
    return body


def _cut(body, obj):
    """Cut inside the second item of the reply's main array (facts on a map)."""
    text = "```json\n" + json.dumps(obj, indent=1)
    key = '"facts"' if obj.get("facts") else '"findings"'
    start = text.index(key)
    second = [m.start() for m in re.finditer(r"\n  \{", text[start:])][1]
    body["content"] = [R.text(text[:start + second + 30])]
    body["stop_reason"] = "max_tokens"
    return body


def _empty(stop):
    def shape(body, obj):
        body["content"] = []
        body["stop_reason"] = stop
        return body
    return shape


def _refused(*, text: bool, category: str | None, parseable: bool = False):
    def shape(body, obj):
        if not parseable:
            body["content"] = [R.text("I can't help with comparing these sheets.")] if text else []
        body["stop_reason"] = "refusal"
        if category is not None:
            body["stop_details"] = R.refusal_stop_details(category, explanation="declined")
        return body
    return shape


def _fallback_streamed(body, obj):
    text = body["content"][0]["text"]
    return R.splice_fallback(body, text.index("VAV-3") + 2, to_model="claude-opus-5")


def _fallback_whole(body, obj):
    body["content"] = [R.fallback_block(body["model"], "claude-opus-5"), body["content"][0]]
    body["model"] = "claude-opus-5"
    return body


# (shape, times): what each path's first replies look like.
SHAPES = {
    "end_turn": (None, 0),
    "max_tokens_closed": (_stop("max_tokens"), 1),
    "max_tokens_no_fence": (_no_fence, 1),
    "max_tokens_cut": (_cut, 1),
    "max_tokens_empty": (_empty("max_tokens"), 1),
    "max_tokens_closed_twice": (_stop("max_tokens"), 2),
    "max_tokens_cut_twice": (_cut, 2),
    "max_tokens_empty_twice": (_empty("max_tokens"), 2),
    "refusal_text": (_refused(text=True, category="cyber"), 1),
    "refusal_empty": (_refused(text=False, category=None), 1),
    "refusal_parseable": (_refused(text=True, category="cyber", parseable=True), 1),
    "stop_none": (_stop(None), 1),
    "context_window": (_stop("model_context_window_exceeded"), 1),
    "tool_use": (_stop("tool_use"), 1),
    "pause_turn": (_stop("pause_turn"), 1),
    "fallback_streamed": (_fallback_streamed, 1),
    "fallback_whole": (_fallback_whole, 1),
}

# What each shape becomes on the whole-set path: status, findings kept, the
# error's pattern (None: no error), cached (the warm run asks nothing).
_WHOLE = {
    "end_turn": ("COMPLETE", 2, None, True),
    "max_tokens_closed": ("COMPLETE", 2, None, True),
    "max_tokens_no_fence": ("COMPLETE", 2, None, True),
    "max_tokens_cut": ("COMPLETE", 2, None, True),
    "max_tokens_empty": ("COMPLETE", 2, None, True),
    "max_tokens_closed_twice": ("PARTIAL", 2, r"^truncated cross-qc \(stop_reason='max_tokens'\)$", False),
    "max_tokens_cut_twice": ("PARTIAL", 1, r"^truncated cross-qc \(stop_reason='max_tokens'\)$", False),
    "max_tokens_empty_twice": ("FAILED", 0, r"^empty cross-qc \(stop_reason='max_tokens'\)$", False),
    "refusal_text": ("FAILED", 0, r"^refused cross-qc \(stop_reason='refusal', category='cyber'\)$", False),
    "refusal_empty": ("FAILED", 0, r"^refused cross-qc \(stop_reason='refusal'\)$", False),
    "refusal_parseable": ("FAILED", 0, r"^refused cross-qc \(stop_reason='refusal', category='cyber'\)$", False),
    "stop_none": ("PARTIAL", 2, r"^unfinished cross-qc \(stop_reason=None\)$", False),
    "context_window": ("PARTIAL", 2,
                       r"^truncated cross-qc \(stop_reason='model_context_window_exceeded'\)$", False),
    "tool_use": ("FAILED", 0, r"^unfinished cross-qc \(stop_reason='tool_use'\)$", False),
    "pause_turn": ("FAILED", 0, r"^unfinished cross-qc \(stop_reason='pause_turn'\)$", False),
    "fallback_streamed": ("COMPLETE", 2, None, True),
    "fallback_whole": ("COMPLETE", 2, None, True),
}


def _requests_on(stub, path: str) -> list[dict]:
    return [b for b in _cross_requests(stub) if _path(b) == path]


@pytest.mark.parametrize("name", list(SHAPES), ids=list(SHAPES))
def test_whole_set_terminal_shape(name, tmp_path):
    shape, times = SHAPES[name]
    status, kept, error, cached = _WHOLE[name]
    cache = DigestCache(tmp_path / "c.sqlite")
    stub = AnthropicAPIStub(_route(shape, "whole_set", times))

    res = _run(stub, cache=cache)

    assert res.stage_status == status, (res.error, res.complete, res.failed)
    assert len(res.findings) == kept
    if error is None:
        assert res.error is None
    else:
        assert re.match(error, res.error), res.error
    assert all(b.get("stream") for b in _cross_requests(stub))        # every call streams
    retried = name.startswith("max_tokens")
    assert [b["max_tokens"] for b in _cross_requests(stub)] == ([CAP, RAISED] if retried else [CAP])
    assert _warm_requests(cache) == (0 if cached else 1)


# The sharded path (two one-sheet shards and a reconcile call): the shape on
# the first map call, or on the reconcile call.
_MAP = {
    "end_turn": ("COMPLETE", 2, 4, None, True),
    "max_tokens_closed": ("COMPLETE", 2, 4, None, True),
    "max_tokens_cut": ("COMPLETE", 2, 4, None, True),
    "max_tokens_closed_twice": ("PARTIAL", 2, 4, r"^truncated cross-qc shard \(stop_reason='max_tokens'\)$", False),
    "max_tokens_cut_twice": ("PARTIAL", 2, 3, r"^truncated cross-qc shard \(stop_reason='max_tokens'\)$", False),
    "max_tokens_empty_twice": ("PARTIAL", 2, 2, r"^empty cross-qc shard \(stop_reason='max_tokens'\)$", False),
    "refusal_text": ("PARTIAL", 2, 2, r"^refused cross-qc shard \(stop_reason='refusal', category='cyber'\)$", False),
    "refusal_parseable": ("PARTIAL", 2, 2, r"^refused cross-qc shard \(stop_reason='refusal', category='cyber'\)$", False),
    "stop_none": ("PARTIAL", 2, 4, r"^unfinished cross-qc shard \(stop_reason=None\)$", False),
    "context_window": ("PARTIAL", 2, 4,
                       r"^truncated cross-qc shard \(stop_reason='model_context_window_exceeded'\)$", False),
    "tool_use": ("PARTIAL", 2, 2, r"^unfinished cross-qc shard \(stop_reason='tool_use'\)$", False),
    "fallback_whole": ("COMPLETE", 2, 4, None, True),
}


@pytest.mark.parametrize("name", list(_MAP), ids=list(_MAP))
def test_map_terminal_shape(name, tmp_path, monkeypatch):
    shape, times = SHAPES[name]
    status, kept, facts, error, cached = _MAP[name]
    cache = DigestCache(tmp_path / "c.sqlite")
    stub = AnthropicAPIStub(_route(shape, "map", times))

    res = _run(stub, cache=cache, sharded=True, monkeypatch=monkeypatch)

    assert res.shards_planned == 2
    assert res.stage_status == status, res.error
    assert (len(res.findings), res.facts_collected) == (kept, facts)
    if error is None:
        assert res.error is None
    else:
        assert re.match(error, res.error), res.error
    assert all(b.get("stream") for b in _cross_requests(stub))
    assert _warm_requests(cache, sharded=True, monkeypatch=monkeypatch) == (0 if cached else 3)


_RECONCILE = {
    "end_turn": ("COMPLETE", 2, None, True),
    "max_tokens_closed": ("COMPLETE", 2, None, True),
    "max_tokens_cut": ("COMPLETE", 2, None, True),
    "max_tokens_closed_twice": ("PARTIAL", 2, "truncated cross-qc reconciliation (stop_reason='max_tokens')", False),
    "max_tokens_cut_twice": ("PARTIAL", 1, "truncated cross-qc reconciliation (stop_reason='max_tokens')", False),
    "max_tokens_empty_twice": ("PARTIAL", 0, "empty cross-qc reconciliation (stop_reason='max_tokens')", False),
    "refusal_text": ("PARTIAL", 0,
                     "refused cross-qc reconciliation (stop_reason='refusal', category='cyber')", False),
    "refusal_empty": ("PARTIAL", 0, "refused cross-qc reconciliation (stop_reason='refusal')", False),
    "stop_none": ("PARTIAL", 2, "unfinished cross-qc reconciliation (stop_reason=None)", False),
    "context_window": ("PARTIAL", 2,
                       "truncated cross-qc reconciliation (stop_reason='model_context_window_exceeded')", False),
    "pause_turn": ("PARTIAL", 0, "unfinished cross-qc reconciliation (stop_reason='pause_turn')", False),
    "fallback_streamed": ("COMPLETE", 2, None, True),
}


@pytest.mark.parametrize("name", list(_RECONCILE), ids=list(_RECONCILE))
def test_reconcile_terminal_shape(name, tmp_path, monkeypatch):
    shape, times = SHAPES[name]
    status, kept, reason, cached = _RECONCILE[name]
    cache = DigestCache(tmp_path / "c.sqlite")
    stub = AnthropicAPIStub(_route(shape, "reconcile", times))

    res = _run(stub, cache=cache, sharded=True, monkeypatch=monkeypatch)

    assert res.shards_completed == 2 and res.facts_collected == 4
    assert res.stage_status == status, res.error
    assert len(res.findings) == kept
    if reason is None:
        assert res.error is None and res.reconciliation_completed
    else:
        # A reconcile failure says why (a refusal names itself).
        assert res.error == f"cross-qc reconciliation incomplete ({reason})"
        assert not res.reconciliation_completed
    assert all(b.get("stream") for b in _cross_requests(stub))
    assert _warm_requests(cache, sharded=True, monkeypatch=monkeypatch) == (0 if cached else 3)


# --------------------------------------------------------------------------- #
# The raised-cap retry
# --------------------------------------------------------------------------- #


def test_the_raised_cap_retry_streams_once_at_twice_the_cap_and_sums_usage(tmp_path):
    stub = AnthropicAPIStub(_route(_cut, "whole_set", 1))

    res = _run(stub, cache=DigestCache(tmp_path / "c.sqlite"))

    first, retry = _cross_requests(stub)
    assert (first["max_tokens"], retry["max_tokens"]) == (CAP, RAISED)
    assert first["stream"] and retry["stream"]
    # The retry is the same request at the raised cap, nothing else.
    assert {k: v for k, v in retry.items() if k != "max_tokens"} == \
        {k: v for k, v in first.items() if k != "max_tokens"}
    assert res.stage_status == "COMPLETE" and len(res.findings) == 2
    assert (res.input_tokens, res.output_tokens) == (1600, 120)        # both attempts billed


def test_the_retry_is_clamped_to_what_the_model_serves(tmp_path, monkeypatch):
    # A model whose ceiling leaves no headroom above the cap is not retried.
    monkeypatch.setattr(X, "output_cap_for_model", lambda model, *, requested: CAP)
    stub = AnthropicAPIStub(_route(_stop("max_tokens"), "whole_set", 1))

    res = _run(stub, cache=DigestCache(tmp_path / "c.sqlite"))

    assert [b["max_tokens"] for b in _cross_requests(stub)] == [CAP]
    assert res.stage_status == "PARTIAL" and res.error.startswith("truncated cross-qc")


@pytest.mark.parametrize("retry", ["refused", "empty", "tool_use"], ids=["refused", "empty", "tool_use"])
def test_a_worse_retry_never_loses_the_first_read_and_is_named(tmp_path, retry):
    shapes = {"refused": _refused(text=True, category="cyber"), "empty": _empty("end_turn"),
              "tool_use": _empty("tool_use")}
    seen = {"n": 0}

    def route(params):
        body = _body(params)
        if _path(params) == "whole_set":
            seen["n"] += 1
            obj = _reply_object(params)
            body = _cut(body, obj) if seen["n"] == 1 else shapes[retry](body, obj)
        return body

    res = _run(AnthropicAPIStub(route), cache=DigestCache(tmp_path / "c.sqlite"))

    assert res.stage_status == "PARTIAL" and len(res.findings) == 1     # the first read's item
    assert res.error.startswith("truncated cross-qc (stop_reason='max_tokens'); retry: ")
    assert res.salvage.calls == 1 and res.salvage.items_cut == 1


def test_a_retry_that_raises_keeps_the_first_read_and_says_so(tmp_path):
    seen = {"n": 0}

    def reject(record):
        import httpx2

        if record["path"] == "/v1/messages" and _path(record["body"]) == "whole_set":
            seen["n"] += 1
            if seen["n"] == 2:
                return httpx2.Response(400, json={"type": "error", "error": {
                    "type": "invalid_request_error", "message": "bad request"}})
        return None

    stub = AnthropicAPIStub(_route(_cut, "whole_set", 1), reject=reject)
    res = _run(stub, cache=DigestCache(tmp_path / "c.sqlite"))

    assert res.stage_status == "PARTIAL" and len(res.findings) == 1
    assert res.error.startswith("truncated cross-qc (stop_reason='max_tokens'); retry failed: HTTP 400")


def test_a_still_truncated_reply_is_never_cached(tmp_path):
    cache = DigestCache(tmp_path / "c.sqlite")
    stub = AnthropicAPIStub(_route(_stop("max_tokens"), "whole_set", 99))

    res = _run(stub, cache=cache)

    assert res.stage_status == "PARTIAL" and len(res.findings) == 2
    assert _warm_requests(cache) == 1


# --------------------------------------------------------------------------- #
# Salvage
# --------------------------------------------------------------------------- #


def _items_text(obj: dict, cut_at: int | None = None) -> str:
    text = "```json\n" + json.dumps(obj, indent=1)
    return text if cut_at is None else text[:cut_at]


_SALVAGE_OBJ = {"findings": [{"a": 1, "q": "x }] {[ \" y"}, {"a": 2}], "claims": [{"c": 1}],
                "facts": [{"f": 1}, {"f": 2}, {"f": 3}]}


def _cut_inside(nth_item_of: str, n: int) -> int:
    text = _items_text(_SALVAGE_OBJ)
    start = text.index(f'"{nth_item_of}"')
    return start + [m.start() for m in re.finditer(r"\n  \{", text[start:])][n] + 6


@pytest.mark.parametrize("cut,expected,items_cut", [
    (None, _SALVAGE_OBJ, 0),
    (_cut_inside("findings", 1), {"findings": [_SALVAGE_OBJ["findings"][0]]}, 1),
    (_cut_inside("facts", 2), {"findings": _SALVAGE_OBJ["findings"], "claims": [{"c": 1}],
                               "facts": [{"f": 1}, {"f": 2}]}, 1),
    (_items_text(_SALVAGE_OBJ).index('"claims"') + 3, {"findings": _SALVAGE_OBJ["findings"]}, 0),
    (_items_text(_SALVAGE_OBJ).index('"findings"') + 14, {"findings": []}, 0),
], ids=["closed", "inside_second_finding", "inside_third_fact", "inside_a_key", "after_open_bracket"])
def test_salvage_keeps_only_complete_items(cut, expected, items_cut):
    obj, cut_n = X._salvage_object(_items_text(_SALVAGE_OBJ, cut))
    assert obj == expected and cut_n == items_cut


@pytest.mark.parametrize("raw", [
    "no json here at all",
    "```json\n",
    "```json\n{\"findings\": ",
    "```json\n{\"claims\": [{\"c\": 1}]}\n```",
    "```python\n{\"findings\": [{\"a\": 1}]}\n```",
], ids=["prose", "bare_opener", "no_array_yet", "claims_only", "not_json"])
def test_salvage_reads_nothing_without_a_findings_or_facts_array(raw):
    assert X._salvage_object(raw)[0] is None


def test_salvage_is_one_linear_pass():
    items = [{"sheet_handle": "S001", "text": f"item {i} " + "x" * 40} for i in range(20_000)]
    text = _items_text({"findings": items})
    starts = [m.start() for m in re.finditer(r"\n  \{", text)]
    start = time.perf_counter()
    obj, cut = X._salvage_object(text[:starts[19_998] + 20])
    assert obj["findings"] == items[:19_998] and cut == 1
    assert time.perf_counter() - start < 2.0


def test_salvaged_items_are_validated_and_grounded(tmp_path):
    def shape(body, obj):
        bad_quote = dict(_finding(3), source_quote="AHU-9 NOT PRINTED")
        bad_field = dict(_finding(4), severity="question")
        # The findings last, so the cut falls inside the fourth one.
        obj = {"claims": obj["claims"], "findings": [_finding(1), bad_quote, bad_field, _finding(2)]}
        body["content"] = [R.text(_fenced(obj)[:-40])]
        body["stop_reason"] = "model_context_window_exceeded"
        return body

    res = _run(AnthropicAPIStub(_route(shape, "whole_set", 1)), cache=DigestCache(tmp_path / "c"))

    assert [f.text.split(":")[0] for f in res.findings] == ["Conflict 1"]   # the cut one dropped
    assert res.discards.legs_ungrounded_quote_text_bearing_sheet == 1
    assert res.invalid.findings_invalid_severity == 1
    assert (res.salvage.calls, res.salvage.findings, res.salvage.items_cut) == (1, 1, 1)
    assert res.stage_status == "PARTIAL"


def test_a_salvaged_reply_keeps_its_complete_claims(tmp_path):
    res = _run(AnthropicAPIStub(_route(_stop(None), "whole_set", 1)), cache=DigestCache(tmp_path / "c"))
    assert [(c.sheet_id, c.source_id) for c in res.claims] == [("M-101", "SRC-0001")]
    assert res.salvage.claims == 1


def test_a_refusal_keeps_nothing_not_even_claims(tmp_path):
    res = _run(AnthropicAPIStub(_route(_refused(text=True, category="cyber", parseable=True))),
               cache=DigestCache(tmp_path / "c"))
    assert res.findings == [] and res.claims == [] and res.salvage.calls == 0


def test_the_salvage_note_counts_what_was_kept(tmp_path):
    res = _run(AnthropicAPIStub(_route(_cut, "whole_set", 2)), cache=DigestCache(tmp_path / "c"))
    assert res.salvage.note() == (
        "1 call(s) did not finish; kept the 1 finding(s), 0 fact(s) and 0 claim(s) "
        "they completed; 1 item(s) cut off were dropped")


# --------------------------------------------------------------------------- #
# Interrupted streams, on each path
# --------------------------------------------------------------------------- #


def _interrupt(target: str, times: int, end: str = "error", error: dict | None = None):
    seen = {"n": 0}

    def stream(record):
        if _path(record["body"]) != target:
            return None
        seen["n"] += 1
        if seen["n"] > times:
            return None
        return ("after_text", end, error) if error else ("after_text", end)

    return stream


@pytest.mark.parametrize("target", ["whole_set", "map", "reconcile"],
                         ids=["whole_set", "map", "reconcile"])
def test_an_interrupted_stream_is_retried_and_counted(tmp_path, monkeypatch, target):
    monkeypatch.setattr(D, "_retry_backoff_seconds", lambda attempt: 0.0)
    stub = AnthropicAPIStub(_route(), stream=_interrupt(target, 1))

    res = _run(stub, cache=DigestCache(tmp_path / "c"), sharded=target != "whole_set",
               monkeypatch=monkeypatch)

    assert res.stage_status == "COMPLETE" and res.error is None
    assert res.interrupted_attempts == 1
    assert len(_requests_on(stub, target)) == (2 if target != "map" else 3)


@pytest.mark.parametrize("end", ["error", "drop"], ids=["error", "drop"])
@pytest.mark.parametrize("target", ["whole_set", "reconcile"], ids=["whole_set", "reconcile"])
def test_a_stream_interrupted_every_time_is_a_partial_read(tmp_path, monkeypatch, target, end):
    monkeypatch.setattr(D, "_retry_backoff_seconds", lambda attempt: 0.0)
    stub = AnthropicAPIStub(_route(), stream=_interrupt(target, 99, end))

    res = _run(stub, cache=DigestCache(tmp_path / "c"), sharded=target != "whole_set",
               monkeypatch=monkeypatch)

    cause = "overloaded_error" if end == "error" else "connection dropped"
    noun = "cross-qc" if target == "whole_set" else "cross-qc reconciliation"
    assert f"unfinished {noun} (stop_reason=None, interrupted='{cause}')" in res.error
    assert res.stage_status == "PARTIAL"
    assert res.interrupted_attempts == 3                 # the call and its two retries
    assert len(_requests_on(stub, target)) == 3


def test_a_permanent_interruption_is_not_retried(tmp_path, monkeypatch):
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    stub = AnthropicAPIStub(_route(), stream=_interrupt("whole_set", 99, "error", error))

    res = _run(stub, cache=DigestCache(tmp_path / "c"))

    assert len(_requests_on(stub, "whole_set")) == 1
    assert "interrupted='invalid_request_error'" in res.error


def test_a_map_interrupted_every_time_holds_the_stage_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_retry_backoff_seconds", lambda attempt: 0.0)
    stub = AnthropicAPIStub(_route(), stream=_interrupt("map", 3, "drop"))     # the first shard

    res = _run(stub, cache=DigestCache(tmp_path / "c"), sharded=True, monkeypatch=monkeypatch)

    assert res.stage_status == "PARTIAL"
    assert "unfinished cross-qc shard (stop_reason=None, interrupted='connection dropped')" in res.error
    assert res.interrupted_attempts == 3


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fields,status", [
    ({}, "COMPLETE"),
    ({"complete": False, "budget_degraded": True}, "PARTIAL"),
    ({"complete": False, "error": "x"}, "PARTIAL"),
    ({"complete": False, "error": "x", "failed": True}, "FAILED"),
    ({"complete": True, "failed": True}, "FAILED"),               # the failure flag first
    ({"skipped": True}, "COMPLETE"),
], ids=["complete", "budget", "error", "failed", "failed_before_counts", "skipped"])
def test_the_stage_status_reads_the_failure_flag_first(fields, status):
    assert X.CrossQCResult(**fields).stage_status == status


def test_a_whole_set_reply_with_no_findings_object_is_failed(tmp_path):
    def prose(body, obj):
        body["content"] = [R.text("I compared the sheets and found nothing structured to report.")]
        return body

    res = _run(AnthropicAPIStub(_route(prose)), cache=DigestCache(tmp_path / "c"))

    assert res.stage_status == "FAILED" and res.error == X._NO_FINDINGS_OBJECT


def test_every_shard_failing_is_failed(tmp_path, monkeypatch):
    res = _run(AnthropicAPIStub(_route(_refused(text=False, category=None), "map", 99)),
               cache=DigestCache(tmp_path / "c"), sharded=True, monkeypatch=monkeypatch)

    assert res.shards_completed == 0 and res.stage_status == "FAILED"
    assert res.error == ("refused cross-qc shard (stop_reason='refusal'); "
                         "refused cross-qc shard (stop_reason='refusal')")


def test_no_client_reads_failed(monkeypatch):
    sheets, geoms = _set()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    res = X.cross_sheet_qc(sheets, geoms, client=None)

    assert res.error and res.complete is False and res.failed is True
    assert res.stage_status == "FAILED"


# --------------------------------------------------------------------------- #
# N14: a budget-only shortfall is cached with its status
# --------------------------------------------------------------------------- #


def _degraded_set():
    return _set(text_a=QA + " " + "X" * 9_000)


def test_a_text_budget_shortfall_is_cached_partial_and_replayed(tmp_path):
    cache = DigestCache(tmp_path / "c.sqlite")
    cold_stub = AnthropicAPIStub(_route())
    cold = _run(cold_stub, cache=cache, sheets=_degraded_set())
    warm_stub = AnthropicAPIStub(_route())
    warm = _run(warm_stub, cache=cache, sheets=_degraded_set())

    assert len(_cross_requests(cold_stub)) == 1 and _cross_requests(warm_stub) == []
    for res in (cold, warm):
        assert res.stage_status == "PARTIAL" and res.budget_degraded and not res.complete
        assert res.text_chars_omitted == cold.text_chars_omitted > 0
        assert len(res.findings) == 2 and res.error is None
    assert warm.cached and not cold.cached
    assert warm.discards.to_dict() == cold.discards.to_dict()


def test_a_findings_cap_shortfall_is_cached_partial_and_replayed(tmp_path):
    def many(body, obj):
        obj = dict(obj, findings=[dict(_finding(i)) for i in range(X.DEFAULT_CROSS_QC_MAX_FINDINGS + 5)])
        body["content"] = [R.text(_fenced(obj))]
        return body

    cache = DigestCache(tmp_path / "c.sqlite")
    cold = _run(AnthropicAPIStub(_route(many, "whole_set", 99)), cache=cache)
    warm_stub = AnthropicAPIStub(_route())
    warm = _run(warm_stub, cache=cache)

    assert _cross_requests(warm_stub) == []
    for res in (cold, warm):
        assert res.stage_status == "PARTIAL" and res.findings_omitted == 5
        assert len(res.findings) == X.DEFAULT_CROSS_QC_MAX_FINDINGS


def test_a_sharded_budget_shortfall_is_cached_partial(tmp_path, monkeypatch):
    cache = DigestCache(tmp_path / "c.sqlite")
    _run(AnthropicAPIStub(_route()), cache=cache, sharded=True, monkeypatch=monkeypatch,
         sheets=_degraded_set())
    warm_stub = AnthropicAPIStub(_route())
    warm = _run(warm_stub, cache=cache, sharded=True, monkeypatch=monkeypatch,
                sheets=_degraded_set())

    assert _cross_requests(warm_stub) == [] and warm.stage_status == "PARTIAL"


def test_a_budget_shortfall_with_a_failed_call_is_never_cached(tmp_path):
    cache = DigestCache(tmp_path / "c.sqlite")
    _run(AnthropicAPIStub(_route(_stop(None), "whole_set", 1)), cache=cache, sheets=_degraded_set())
    warm_stub = AnthropicAPIStub(_route())
    _run(warm_stub, cache=cache, sheets=_degraded_set())

    assert len(_cross_requests(warm_stub)) == 1


@pytest.mark.parametrize("payload,served", [
    ({"complete": True, "budget_degraded": False}, True),
    ({"complete": False, "budget_degraded": True}, True),
    ({"complete": False, "budget_degraded": False}, False),
    ({"complete": True, "budget_degraded": True}, False),
], ids=["complete", "budget_only", "incomplete_without_reason", "contradictory"])
def test_the_read_side_serves_only_a_complete_or_budget_only_entry(payload, served):
    res = X._cross_qc_from_cache({"findings": [], "claims": [], **payload})
    assert (res is not None) == served
    if served:
        assert res.stage_status == ("COMPLETE" if payload["complete"] else "PARTIAL")


def test_the_cross_qc_contract_moved_for_terminal_honesty():
    """Host-side admission and binding changed for byte-identical request inputs:
    a reply the model did not finish is no longer stored as complete, a cut-off
    reply's complete items are kept (never stored), a budget-only shortfall is
    stored with its status, and a fact or leg that is not an object is counted.
    One mechanism, the existing contract term (plan §2 rule 15)."""
    assert X._CROSS_QC_CACHE_CONTRACT == 10


# --------------------------------------------------------------------------- #
# U7: facts past the cap, items that are not objects
# --------------------------------------------------------------------------- #


def test_facts_past_the_cap_and_non_objects_are_counted():
    sheets, geoms = _set()
    handles = X._assign_handles(X._canonical_order(
        [("M-101", "d", g.sheet_text, g) for g in geoms[:1]]))
    facts = [{"sheet_handle": "S001", "entity_or_tag": f"T{i}", "attribute": "a", "value": "v",
              "exact_quote": QA} for i in range(X.DEFAULT_MAP_MAX_FACTS + 3)]
    facts[5:5] = ["not a fact", 7]
    counts = X.CrossQCDiscardCounts()

    out = X._parse_facts({"facts": facts}, handles.entry_by_handle,
                         handles.discipline_by_handle, counts, handles.by_label)

    assert len(out) == X.DEFAULT_MAP_MAX_FACTS
    assert (counts.facts_over_cap, counts.facts_not_object) == (3, 2)
    assert counts.facts_accepted == X.DEFAULT_MAP_MAX_FACTS


@pytest.mark.parametrize("value", ["none", {"sheet_handle": "S001"}, 7], ids=["string", "dict", "int"])
def test_facts_that_are_not_a_list_hold_nothing(value):
    counts = X.CrossQCDiscardCounts()
    assert X._parse_facts({"facts": value}, {}, {}, counts) == []
    assert counts.to_dict() == X.CrossQCDiscardCounts().to_dict()


def test_a_leg_that_is_not_an_object_is_counted(tmp_path):
    item = dict(_finding(1), also_on=["S002", {"sheet_handle": "S002", "source_quote": QB}, 3])

    def shape(body, obj):
        body["content"] = [R.text(_fenced(dict(obj, findings=[item])))]
        return body

    res = _run(AnthropicAPIStub(_route(shape)), cache=DigestCache(tmp_path / "c"))

    assert len(res.findings) == 1
    assert res.discards.legs_not_object == 2


def test_also_on_that_is_not_a_list_holds_no_legs(tmp_path):
    item = dict(_finding(1), also_on={"sheet_handle": "S002", "source_quote": QB})

    def shape(body, obj):
        body["content"] = [R.text(_fenced(dict(obj, findings=[item])))]
        return body

    res = _run(AnthropicAPIStub(_route(shape)), cache=DigestCache(tmp_path / "c"))

    assert res.findings == [] and res.discards.legs_not_object == 0
    assert res.discards.findings_dropped_under_two_legs == 1


@pytest.mark.parametrize("fields,note", [
    ({}, ""),
    ({"facts_over_cap": 45}, "45 fact(s) past the per-shard cap of 40 were not compared across shards"),
    ({"facts_not_object": 1, "legs_not_object": 2},
     "1 fact(s) and 2 leg(s) that were not objects were skipped"),
    ({"facts_over_cap": 3, "legs_not_object": 1},
     "3 fact(s) past the per-shard cap of 40 were not compared across shards; "
     "0 fact(s) and 1 leg(s) that were not objects were skipped"),
], ids=["none", "cap", "not_objects", "both"])
def test_the_omission_note(fields, note):
    assert X.CrossQCDiscardCounts(**fields).omission_note() == note


def test_the_new_counters_round_trip_and_default_to_zero():
    counts = X.CrossQCDiscardCounts(facts_over_cap=2, facts_not_object=1, legs_not_object=4)
    assert X.CrossQCDiscardCounts.from_dict(counts.to_dict()) == counts
    older = {k: v for k, v in counts.to_dict().items()
             if k not in {"facts_over_cap", "facts_not_object", "legs_not_object"}}
    back = X.CrossQCDiscardCounts.from_dict(older)
    assert (back.facts_over_cap, back.facts_not_object, back.legs_not_object) == (0, 0, 0)


def test_the_counters_are_observational(tmp_path, monkeypatch):
    def shape(body, obj):
        obj = dict(obj)
        obj["facts"] = obj["facts"] + ["junk"] + [dict(obj["facts"][0], entity_or_tag=f"X{i}")
                                                  for i in range(X.DEFAULT_MAP_MAX_FACTS)]
        body["content"] = [R.text(_fenced(obj))]
        return body

    cache = DigestCache(tmp_path / "c")
    res = _run(AnthropicAPIStub(_route(shape, "map", 1)), cache=cache, sharded=True,
               monkeypatch=monkeypatch)

    assert res.discards.facts_over_cap == 2 and res.discards.facts_not_object == 1
    assert res.stage_status == "COMPLETE" and res.complete
    assert _warm_requests(cache, sharded=True, monkeypatch=monkeypatch) == 0


# --------------------------------------------------------------------------- #
# Through the pipeline: status, usage, warnings, run.log, the manifest
# --------------------------------------------------------------------------- #


def _pipeline_route(shape=None, target: str = "whole_set", times: int = 1):
    """The gauntlet's mini set: its script for every stage but cross-QC."""
    from tests.fixtures.sdk_transport import message_json
    from tests.test_sdk_contract import _script

    script = _script()
    cross = _route(shape, target, times)

    def route(params: dict) -> dict:
        if _path(params) is not None:
            return cross(params)
        return message_json(script._route(params), model=params.get("model", ""))

    return route


def _pipeline(tmp_path, route, *, stream=None, cache=None, work: str = "qc"):
    import drawing_analyzer.pipeline as pl
    from tests.fixtures.gauntlet import build_mini_set

    stub = AnthropicAPIStub(route, stream=stream)
    ctx = pl.extract_drawing_context(
        build_mini_set(tmp_path / "set"), client=stub.client(), rows=2, cols=2,
        cross_qc=True, qc_work_dir=tmp_path / work,
        cache=cache if cache is not None else DigestCache(tmp_path / "cache.sqlite"))
    return ctx, stub


def _stage(ctx):
    [stage] = [s for s in ctx.stage_results if s.stage == "cross_qc"]
    return stage


def _usage(ctx):
    [record] = [r for r in ctx.run_usage.records if r.stage_family == "cross_qc"]
    return record


def _export(ctx, tmp_path):
    from drawing_analyzer.export import write_drawing_export

    out = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101", "M-102"])
    return ((out / "run.log").read_text(encoding="utf-8"),
            json.loads((out / "run_manifest.json").read_text(encoding="utf-8")))


def test_pipeline_a_cut_off_reply_is_partial_and_says_what_it_kept(tmp_path):
    ctx, stub = _pipeline(tmp_path, _pipeline_route(_cut, "whole_set", 2))

    stage = _stage(ctx)
    assert stage.status == "PARTIAL" and stage.items_out == 1
    assert "Cross-sheet QC: truncated cross-qc (stop_reason='max_tokens')" in ctx.errors
    note = ("1 call(s) did not finish; kept the 1 finding(s), 0 fact(s) and 0 claim(s) "
            "they completed; 1 item(s) cut off were dropped")
    assert stage.warnings == [note]
    record = _usage(ctx)
    assert (record.terminal_status, record.input_tokens, record.output_tokens) == ("PARTIAL", 1600, 120)
    log, manifest = _export(ctx, tmp_path)
    # The stage table shows the error first and counts the rest.
    (row,) = [line for line in log.splitlines() if line.split()[:2] == ["cross_qc", "PARTIAL"]]
    assert "truncated cross-qc (stop_reason='max_tokens') (+1 more)" in row
    (m_stage,) = [s for s in manifest["stages"] if s["stage"] == "cross_qc"]
    assert m_stage["status"] == "PARTIAL" and m_stage["warnings"] == [note]


def test_pipeline_a_refused_reply_is_failed_with_a_failed_usage_record(tmp_path):
    ctx, _stub = _pipeline(tmp_path, _pipeline_route(_refused(text=True, category="cyber")))

    assert _stage(ctx).status == "FAILED" and _stage(ctx).items_out == 0
    assert _usage(ctx).terminal_status == "FAILED"
    assert ctx.qc_status != "COMPLETE"


def test_pipeline_no_client_reads_failed(tmp_path, monkeypatch):
    real = X.cross_sheet_qc
    monkeypatch.setattr(X, "cross_sheet_qc", lambda *a, **k: real(*a, **{**k, "client": None}))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    ctx, _stub = _pipeline(tmp_path, _pipeline_route())

    assert _stage(ctx).status == "FAILED"
    assert "Cross-sheet QC: ANTHROPIC_API_KEY environment variable not set" in ctx.errors
    assert _usage(ctx).terminal_status == "FAILED"


def test_pipeline_an_interrupted_stream_is_counted_on_the_usage_record(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_retry_backoff_seconds", lambda attempt: 0.0)
    ctx, _stub = _pipeline(tmp_path, _pipeline_route(), stream=_interrupt("whole_set", 99, "drop"))

    record = _usage(ctx)
    assert record.interrupted_attempts == 3 and record.terminal_status == "PARTIAL"
    assert ctx.run_usage.interrupted_attempts == 3
    log, manifest = _export(ctx, tmp_path)
    assert "3 attempt(s) interrupted mid-stream" in log
    assert manifest["usage"]["interrupted_attempts"] == 3


def test_pipeline_a_budget_only_shortfall_replays_partial_warm(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "_TEXT_LAYER_BUDGET", 10)
    cache = DigestCache(tmp_path / "cache.sqlite")
    cold, _stub = _pipeline(tmp_path, _pipeline_route(), cache=cache)
    warm, warm_stub = _pipeline(tmp_path, _pipeline_route(), cache=cache, work="qc2")

    assert _cross_requests(warm_stub) == []
    for ctx in (cold, warm):
        stage = _stage(ctx)
        assert stage.status == "PARTIAL" and stage.items_out == 2
        assert stage.warnings == _stage(cold).warnings
        assert stage.warnings[0].startswith("text budget degraded: ")
        assert _usage(ctx).terminal_status == "PARTIAL"
    assert _usage(warm).transport == "CACHE" and _usage(cold).transport == "REAL_TIME"


def test_pipeline_the_findings_cap_names_its_own_loss(tmp_path):
    def many(body, obj):
        obj = dict(obj, findings=[_finding(i) for i in range(X.DEFAULT_CROSS_QC_MAX_FINDINGS + 5)])
        body["content"] = [R.text(_fenced(obj))]
        return body

    ctx, _stub = _pipeline(tmp_path, _pipeline_route(many))

    stage = _stage(ctx)
    assert stage.status == "PARTIAL"
    assert stage.warnings == ["5 finding(s) past the per-response cap were dropped"]


def test_pipeline_the_omission_counters_reach_the_warnings_and_the_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
    monkeypatch.setenv("DRAWING_ANALYZER_CROSS_QC_WORKERS", "1")

    def junk(body, obj):
        obj = dict(obj)
        obj["facts"] = obj["facts"] + ["junk"] + [
            dict(obj["facts"][0], entity_or_tag=f"X{i}") for i in range(X.DEFAULT_MAP_MAX_FACTS)]
        body["content"] = [R.text(_fenced(obj))]
        return body

    ctx, _stub = _pipeline(tmp_path, _pipeline_route(junk, "map", 1))

    stage = _stage(ctx)
    note = ("2 fact(s) past the per-shard cap of 40 were not compared across shards; "
            "1 fact(s) and 0 leg(s) that were not objects were skipped")
    assert stage.status == "COMPLETE" and stage.warnings == [note]
    assert (ctx.cross_qc_discards["facts_over_cap"], ctx.cross_qc_discards["facts_not_object"],
            ctx.cross_qc_discards["legs_not_object"]) == (2, 1, 0)
    _log, manifest = _export(ctx, tmp_path)
    assert manifest["cross_qc_discards"]["facts_over_cap"] == 2
