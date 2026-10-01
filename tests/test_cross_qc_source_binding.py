"""Both cross-QC paths bind replies to unique physical sheets, ground quotes
against uncapped text and reject ambiguous labels. Numeric claims retain
source ownership, and model-visible framing participates in cache identity.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from drawing_analyzer import cross_qc as X
from drawing_analyzer.anchor import resolve_anchors
from drawing_analyzer.auditors.arithmetic import audit_arithmetic
from drawing_analyzer.cross_qc import cross_sheet_qc
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.models import (
    EVIDENCE_NOT_MATCHED,
    EVIDENCE_TEXT_GROUNDED,
    EVIDENCE_UNAVAILABLE,
    Finding,
    NumericClaim,
    SheetGeometry,
    SheetRef,
)
from drawing_analyzer.render import SHEET_TEXT_MAX_CHARS, _cap_sheet_text
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)

_NOOP = lambda *_a, **_k: None  # noqa: E731
W, H = 792.0, 612.0


def _w(x, y, text, w=30, h=12):
    return (float(x), float(y), float(x + w), float(y + h), text, 0, 0, 0)


def _geom(src, name, sid, lines=(), *, page=0, folder=None, full=None, pages=1):
    """One sheet: its id in the title block, ``lines`` printed in tile r1c1.

    ``full`` overrides the whole text layer (a dense notes sheet); the prompt
    text is then the renderer's own capped form of it.
    """
    ref = SheetRef(pdf_path=Path(f"/{folder or src}/{name}"), page_index=page,
                   source_name=name, page_count=pages, source_id=src)
    words = [_w(W - 300, H - 160, sid, w=60)] if sid else []
    y = 40.0
    for line in lines:
        x = 40.0
        for word in line.split():
            words.append(_w(x, y, word))
            x += 34.0
        y += 20.0
    text = "\n".join([sid, *lines]) if sid else "\n".join(lines)
    if full is not None:
        text = full
    return SheetGeometry(
        ref=ref, page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=words, sheet_text=_cap_sheet_text(text), full_sheet_text=text,
    )


def _digest(geom):
    return SheetDigest(ref=geom.ref, text="Sheet - Plan\nPump room.")


def _fenced(obj):
    return "```json\n" + json.dumps(obj) + "\n```"


class _Cross(BetaClientMixin):
    """Routes cross-QC calls by their own system prompts: whole-set, map, reconcile.

    Each script is a response object or a callable of the request body; the
    bodies are kept so a test can read what the model was shown.
    """

    def __init__(self, *, whole=None, map_=None, reconcile=None):
        self.scripts = {"whole": whole, "map": map_, "reconcile": reconcile}
        self.bodies = {"whole": [], "map": [], "reconcile": []}
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                body = kw["messages"][0]["content"][0]["text"]
                if system == X.CROSS_QC_RECONCILE_SYSTEM_PROMPT:
                    kind = "reconcile"
                elif system == X.cross_qc_map_system_prompt():
                    kind = "map"
                elif system == X.cross_qc_system_prompt():
                    kind = "whole"
                else:
                    raise AssertionError(f"unexpected system prompt {system[:50]!r}")
                outer.bodies[kind].append(body)
                script = outer.scripts[kind]
                if callable(script):
                    script = script(body)
                obj = {"findings": [], "claims": [], **(script or {})}
                return FakeMessage(content=[FakeTextBlock(text=_fenced(obj))],
                                   usage=FakeUsage(input_tokens=100, output_tokens=20))

        self.messages = _Msgs()


def _item(primary, quote, legs, *, key="sheet_handle", text="P-1 voltage differs.", **extra):
    """One cross-QC item; ``legs`` is ``[(reference, quote), ...]``."""
    return {key: primary, "category": "conflict", "severity": "high", "text": text,
            "source_quote": quote,
            "also_on": [{key: ref, "source_quote": q} for ref, q in legs], **extra}


def _run(geoms, whole=None, **kw):
    client = _Cross(whole=whole, **kw)
    res = cross_sheet_qc([_digest(g) for g in geoms], geoms, client=client,
                         max_retries=0, sleep=_NOOP)
    return res, client


def _bindings(res):
    """Each finding as ``(primary page, [leg pages])``, a page being (source, page)."""
    return [((f.source_id, f.page_index),
             [(leg.source_id, leg.page_index) for leg in f.also_on])
            for f in res.findings]


def _counts(res):
    """The non-zero run-level discard counters."""
    assert res.discards is not None, "the whole-set path records its discards"
    return {k: v for k, v in res.discards.to_dict().items() if k != "by_sheet" and v}


# Two PDFs that both carry M-101 (one basename, two folders), and E-101.
def _two_m101():
    return [
        _geom("SRC-0001", "M-101.pdf", "M-101", ["PUMP P-1 480V"], folder="a"),
        _geom("SRC-0002", "M-101.pdf", "M-101", ["PUMP P-1 208V"], folder="b"),
        _geom("SRC-0003", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"]),
    ]


# --------------------------------------------------------------------------- #
# Handles in the request (the owner's rule: S### handles, the id beside each)
# --------------------------------------------------------------------------- #


def test_the_whole_set_request_labels_each_sheet_by_handle_with_its_id_beside():
    _res, client = _run(_two_m101())
    (body,) = client.bodies["whole"]
    assert "===== SHEET S001 = M-101 =====" in body
    assert "===== SHEET S002 = M-101 =====" in body
    assert "===== SHEET S003 = E-101 =====" in body
    assert "===== SHEET M-101 =====" not in body, "a label is never the address"


def test_the_map_request_labels_each_sheet_by_handle_with_its_id_beside(monkeypatch):
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
    _res, client = _run(_two_m101())
    bodies = "\n".join(client.bodies["map"])
    for title in ("S001 = M-101", "S002 = M-101", "S003 = E-101"):
        assert f"===== SHEET {title} =====" in bodies


@pytest.mark.parametrize("which", ["whole", "map"])
def test_the_instruction_asks_for_handles_in_the_json_and_ids_in_text(which):
    prompt = " ".join((X.cross_qc_system_prompt() if which == "whole"
                       else X.cross_qc_map_system_prompt()).split())
    assert "Refer to sheets in the json ONLY by their handle" in prompt
    assert "in text, name them by their sheet id" in prompt
    assert '"sheet_handle"' in prompt


def test_the_whole_set_instruction_no_longer_asks_for_a_sheet_id_reference():
    prompt = " ".join(X.cross_qc_system_prompt().split())
    assert "sheet_handle (the PRIMARY sheet's handle" in prompt
    assert '{"sheet_id", "source_quote"' not in prompt
    assert "set this to the HANDLE of the sheet the numbers are on" in prompt


# --------------------------------------------------------------------------- #
# Binding: the plan's regression matrix
# --------------------------------------------------------------------------- #


def _same_tag_two_pages():
    return [
        _geom("SRC-0001", "plans.pdf", "M-101", ["AHU-1 12 KW"], page=0, pages=2),
        _geom("SRC-0001", "plans.pdf", "M-102", ["AHU-1 15 KW"], page=1, pages=2),
    ]


def _one_label_two_pages():
    return [
        _geom("SRC-0001", "plans.pdf", "M-101", ["AHU-1 12 KW"], page=0, pages=2),
        _geom("SRC-0001", "plans.pdf", "M-101", ["AHU-1 15 KW"], page=1, pages=2),
    ]


def _same_basename_no_id():
    # Two scans of one drawing name in two folders: no detectable id, so both
    # fall back to the label plan-p1.
    return [
        _geom("SRC-0001", "plan.pdf", "", ["GENERAL NOTE FOUR SEE DETAIL"], folder="a"),
        _geom("SRC-0002", "plan.pdf", "", ["GENERAL NOTE FOUR SEE PLAN"], folder="b"),
    ]


# (id, set, reply items, expected bindings, expected non-zero counters)
_BINDING = [
    ("duplicate labels: each PDF by its handle", _two_m101,
     [_item("S001", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")]),
      _item("S002", "PUMP P-1 208V", [("S003", "PUMP P-1 FEEDER 208V")])],
     [(("SRC-0001", 0), [("SRC-0003", 0)]), (("SRC-0002", 0), [("SRC-0003", 0)])],
     {"legs_accepted_grounded": 4}),
    ("duplicate labels: a conflict between the two is expressible", _two_m101,
     [_item("S001", "PUMP P-1 480V", [("S002", "PUMP P-1 208V")])],
     [(("SRC-0001", 0), [("SRC-0002", 0)])],
     {"legs_accepted_grounded": 2}),
    ("duplicate labels: a legacy reply naming the shared id is refused", _two_m101,
     [_item("M-101", "PUMP P-1 480V", [("E-101", "PUMP P-1 FEEDER 208V")], key="sheet_id")],
     [],
     {"legs_ambiguous_label": 1, "legs_accepted_grounded": 1,
      "findings_dropped_under_two_legs": 1}),
    ("duplicate labels: a legacy reply naming both is refused twice", _two_m101,
     [_item("M-101", "PUMP P-1 480V", [("M-101", "PUMP P-1 208V")], key="sheet_id")],
     [],
     {"legs_ambiguous_label": 2, "findings_dropped_under_two_legs": 1}),
    ("a legacy id naming one sheet binds it", _two_m101,
     [_item("E-101", "PUMP P-1 FEEDER 208V", [("S002", "PUMP P-1 208V")], key="sheet_id")],
     [(("SRC-0003", 0), [("SRC-0002", 0)])],
     {"legs_accepted_grounded": 2}),
    ("same basename in two folders, by handle", _same_basename_no_id,
     [_item("S001", "GENERAL NOTE FOUR SEE DETAIL", [("S002", "GENERAL NOTE FOUR SEE PLAN")])],
     [(("SRC-0001", 0), [("SRC-0002", 0)])],
     {"legs_accepted_grounded": 2}),
    ("same basename in two folders, the shared fallback id is refused", _same_basename_no_id,
     [_item("plan-p1", "GENERAL NOTE FOUR SEE DETAIL",
            [("plan-p1", "GENERAL NOTE FOUR SEE PLAN")], key="sheet_id")],
     [],
     {"legs_ambiguous_label": 2, "findings_dropped_under_two_legs": 1}),
    ("an invalid handle never binds", _two_m101,
     [_item("S099", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")])],
     [],
     {"legs_unresolved_handle": 1, "legs_accepted_grounded": 1,
      "findings_dropped_under_two_legs": 1}),
    ("a handle written loosely still binds", _two_m101,
     [_item(" s001 ", "PUMP P-1 480V", [("S003.", "PUMP P-1 FEEDER 208V")])],
     [(("SRC-0001", 0), [("SRC-0003", 0)])],
     {"legs_accepted_grounded": 2}),
    ("the same tag on two pages of one PDF", _same_tag_two_pages,
     [_item("S001", "AHU-1 12 KW", [("S002", "AHU-1 15 KW")])],
     [(("SRC-0001", 0), [("SRC-0001", 1)])],
     {"legs_accepted_grounded": 2}),
    ("one id on two pages of one PDF: by handle", _one_label_two_pages,
     [_item("S001", "AHU-1 12 KW", [("S002", "AHU-1 15 KW")])],
     [(("SRC-0001", 0), [("SRC-0001", 1)])],
     {"legs_accepted_grounded": 2}),
    ("one id on two pages of one PDF: the legacy id is refused", _one_label_two_pages,
     [_item("M-101", "AHU-1 12 KW", [("M-101", "AHU-1 15 KW")], key="sheet_id")],
     [],
     {"legs_ambiguous_label": 2, "findings_dropped_under_two_legs": 1}),
]


@pytest.mark.parametrize(
    "build,items,bindings,counts", [c[1:] for c in _BINDING], ids=[c[0] for c in _BINDING])
def test_whole_set_binding(build, items, bindings, counts):
    res, _client = _run(build(), whole={"findings": items})
    assert _bindings(res) == bindings
    assert _counts(res) == counts


def test_an_ambiguous_reference_never_binds_the_first_source():
    """N6 itself: the reply that bound the first M-101 on main binds nothing now."""
    res, _ = _run(_two_m101(), whole={"findings": [
        _item("M-101", "PUMP P-1 480V", [("E-101", "PUMP P-1 FEEDER 208V")], key="sheet_id")]})
    assert not [f for f in res.findings if f.source_id == "SRC-0001"]
    assert res.findings == []
    assert res.discards.legs_ambiguous_label == 1


def _handle_shaped_ids():
    # A set whose sheet ids read like handles: sheet 2's own id is S001.
    return [
        _geom("SRC-0001", "a.pdf", "A-101", ["PUMP P-1 480V"]),
        _geom("SRC-0002", "s.pdf", "S001", ["PUMP P-1 208V"]),
    ]


def test_handles_never_take_a_sheet_id_the_set_uses():
    """Codex review of this PR: with S001 handed to A-101, a legacy reply naming
    the sheet whose own id is S001 bound A-101, the wrong PDF. The handles now
    take a prefix no sheet id of the set uses, so a handle and an id never
    compete, and S### stays the handle of every other set."""
    _res, client = _run(_handle_shaped_ids())
    body = client.bodies["whole"][0]
    assert "===== SHEET H001 = A-101 =====" in body
    assert "===== SHEET H002 = S001 =====" in body


@pytest.mark.parametrize("ref,bound", [
    ("S001", "SRC-0002"),          # the id: the sheet that carries it
    ("H002", "SRC-0002"),          # its handle
    ("H001", "SRC-0001"),          # the other sheet's handle
], ids=["the id S001", "its handle H002", "the other handle H001"])
def test_a_handle_shaped_id_binds_its_own_sheet(ref, bound):
    res, _ = _run(_handle_shaped_ids(), whole={
        "findings": [_item(ref, "PUMP P-1 208V" if bound == "SRC-0002" else "PUMP P-1 480V",
                           [("A-101" if bound == "SRC-0002" else "S001",
                             "PUMP P-1 480V" if bound == "SRC-0002" else "PUMP P-1 208V")],
                           key="sheet_id")],
        "claims": [{"sheet_id": ref, "quote": "20 20 TOTAL 40", "kind": "sum",
                    "terms": [20, 20], "expected": 40}]})
    (f,) = res.findings
    assert f.source_id == bound
    (c,) = res.claims
    assert c.source_id == bound, "a claim is rebound to the sheet it names"


def test_a_handle_shaped_id_binds_its_own_sheet_on_the_sharded_parser():
    entries = X._canonical_order([(X.detect_sheet_id(g), "d", g.sheet_text, g)
                                  for g in _handle_shaped_ids()])
    handles = X._assign_handles(entries)
    (f,), _counts, _invalid = _parse_map(entries, handles, _item(
        "S001", "PUMP P-1 208V", [("H001", "PUMP P-1 480V")]))
    assert _state([f])[0][:2] == ("SRC-0002", 0)
    assert [(leg.source_id, leg.page_index) for leg in f.also_on] == [("SRC-0001", 0)]


def test_the_handle_prefix_skips_every_prefix_the_set_uses():
    geoms = [_geom("SRC-0001", "a.pdf", "S001", ["NOTE"]),
             _geom("SRC-0002", "b.pdf", "H002", ["NOTE"]),
             _geom("SRC-0003", "c.pdf", "M-101", ["NOTE"])]
    _res, client = _run(geoms)
    titles = re.findall(r"===== SHEET (\S+ = \S+) =====", client.bodies["whole"][0])
    assert titles == ["K001 = S001", "K002 = H002", "K003 = M-101"]


def test_a_set_with_no_handle_shaped_id_keeps_the_s_handles():
    entries = [(X.detect_sheet_id(g), "d", g.sheet_text, g) for g in _two_m101()]
    assert list(X._assign_handles(entries).entry_by_handle) == ["S001", "S002", "S003"]


def test_a_whole_set_finding_carries_its_sheet_label_not_the_reply_spelling():
    res, _ = _run(_two_m101(), whole={"findings": [
        _item(" s001 ", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")])]})
    (f,) = res.findings
    assert f.sheet_id == "M-101" and [leg.sheet_id for leg in f.also_on] == ["E-101"]


# --------------------------------------------------------------------------- #
# Input order (the owner's rule: entries sorted by source id and page)
# --------------------------------------------------------------------------- #


def _keys_seen(monkeypatch):
    seen = []
    real = X._cross_qc_cache_key

    def _spy(entries, **kw):
        key = real(entries, **kw)
        seen.append(key)
        return key

    monkeypatch.setattr(X, "_cross_qc_cache_key", _spy)
    return seen


@pytest.mark.parametrize("order", [(0, 1, 2), (2, 1, 0), (1, 2, 0)],
                         ids=["inventory order", "reversed", "rotated"])
def test_input_reorder_keeps_bindings_request_and_key(monkeypatch, order):
    keys = _keys_seen(monkeypatch)
    reply = {"findings": [_item("S002", "PUMP P-1 208V", [("S003", "PUMP P-1 FEEDER 208V")])]}
    base, base_client = _run(_two_m101(), whole=reply)
    geoms = _two_m101()
    res, client = _run([geoms[i] for i in order], whole=reply)
    assert _bindings(res) == _bindings(base) == [(("SRC-0002", 0), [("SRC-0003", 0)])]
    assert client.bodies["whole"] == base_client.bodies["whole"]
    assert keys[0] == keys[1]


def test_entries_sort_by_source_id_in_natural_order():
    geoms = [
        _geom("SRC-10000", "z.pdf", "Z-1", ["NOTE"]),
        _geom("SRC-9999", "y.pdf", "Y-1", ["NOTE"]),
        _geom("SRC-0002", "x.pdf", "X-1", ["NOTE"], page=1, pages=2),
        _geom("SRC-0002", "x.pdf", "X-0", ["NOTE"], page=0, pages=2),
    ]
    _res, client = _run(geoms)
    titles = re.findall(r"===== SHEET (S\d+ = \S+) =====", client.bodies["whole"][0])
    assert titles == ["S001 = X-0", "S002 = X-1", "S003 = Y-1", "S004 = Z-1"]


def test_sheets_without_a_source_id_keep_their_input_order():
    geoms = [_geom("", "b.pdf", "B-1", ["NOTE"]), _geom("", "a.pdf", "A-1", ["NOTE"])]
    _res, client = _run(geoms)
    titles = re.findall(r"===== SHEET (S\d+ = \S+) =====", client.bodies["whole"][0])
    assert titles == ["S001 = B-1", "S002 = A-1"]


# --------------------------------------------------------------------------- #
# Whole-set / sharded equivalence at parser level
# --------------------------------------------------------------------------- #


def _tail_text(sid, tail):
    return f"{sid} title. " + "GENERAL NOTE LINE. " * (SHEET_TEXT_MAX_CHARS // 19 + 40) + tail


_TAIL = "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2"


def _equivalence_set():
    return [
        _geom("SRC-0001", "M-101.pdf", "M-101", ["PUMP P-1 480V"], folder="a"),
        _geom("SRC-0002", "M-101.pdf", "M-101", ["PUMP P-1 208V"], folder="b"),
        _geom("SRC-0003", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"]),
        _geom("SRC-0004", "scan.pdf", "", []),
        _geom("SRC-0005", "F-101.pdf", "F-101", full=_tail_text("F-101", _TAIL)),
    ]


_EQUIVALENCE = [
    ("by handle", _item("S001", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")])),
    ("legacy unique id", _item("E-101", "PUMP P-1 FEEDER 208V", [("F-101", _TAIL)], key="sheet_id")),
    ("legacy shared id", _item("M-101", "PUMP P-1 480V", [("E-101", "PUMP P-1 FEEDER 208V")],
                               key="sheet_id")),
    ("invalid handle", _item("S099", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")])),
    ("quote the sheet does not print", _item("S001", "PUMP P-9 999V", [("S003", "PUMP P-1 FEEDER 208V")])),
    ("short tag not printed", _item("S001", "P-7", [("S003", "PUMP P-1 FEEDER 208V")])),
    ("scanned leg", _item("S004", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")])),
    ("quote past the prompt cap", _item("S005", _TAIL, [("S003", "PUMP P-1 FEEDER 208V")])),
    ("refused field", _item("S001", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")],
                            severity="question")),
]


def _parse_whole(entries, handles, item):
    counts, invalid = X.CrossQCDiscardCounts(), X.CrossQCInvalidCounts()
    client = _Cross(whole={"findings": [item]})
    findings, *_rest = X._one_cross_qc_call(
        entries, handles, client=client, model="claude-opus-5-5", max_retries=0,
        sleep=_NOOP, budget=X._Budget(), counts=counts, invalid=invalid)
    return findings, counts, invalid


def _parse_map(entries, handles, item):
    counts, invalid = X.CrossQCDiscardCounts(), X.CrossQCInvalidCounts()
    client = _Cross(map_={"findings": [item], "facts": []})
    findings, *_rest = X._map_call(
        entries, handles.entry_by_handle, handles.handle_by_key,
        handles.discipline_by_handle, client=client, model="claude-opus-5-5",
        max_retries=0, sleep=_NOOP, budget=X._Budget(), counts=counts,
        invalid=invalid, by_label=handles.by_label)
    return findings, counts, invalid


def _state(findings):
    return [(f.source_id, f.page_index, f.sheet_id, f.evidence_state,
             [(leg.source_id, leg.page_index, leg.sheet_id, leg.evidence_state)
              for leg in f.also_on]) for f in findings]


@pytest.mark.parametrize("item", [c[1] for c in _EQUIVALENCE], ids=[c[0] for c in _EQUIVALENCE])
def test_the_same_item_binds_alike_on_the_whole_set_and_sharded_parsers(item):
    geoms = _equivalence_set()
    entries = X._canonical_order([
        (X.detect_sheet_id(g) or X._fallback_id(g.ref), "digest", g.sheet_text, g)
        for g in geoms])
    handles = X._assign_handles(entries)
    whole, w_counts, w_invalid = _parse_whole(entries, handles, item)
    shard, s_counts, s_invalid = _parse_map(entries, handles, item)
    assert _state(whole) == _state(shard)
    assert w_counts.to_dict() == s_counts.to_dict()
    assert w_invalid.to_dict() == s_invalid.to_dict()


# --------------------------------------------------------------------------- #
# Grounding on the whole-set path (U8): the uncapped evidence, one matcher
# --------------------------------------------------------------------------- #


def test_a_quote_past_the_prompt_cap_grounds_on_the_whole_set_path():
    geoms = [_geom("SRC-0001", "F-101.pdf", "F-101", full=_tail_text("F-101", _TAIL)),
             _geom("SRC-0002", "F-102.pdf", "F-102", ["PRE-ACTION VALVE PV-3 SERVES DATA HALL 3"])]
    assert _TAIL not in geoms[0].sheet_text, "premise: the quote is past the prompt cap"
    res, _ = _run(geoms, whole={"findings": [
        _item("S001", _TAIL, [("S002", "PRE-ACTION VALVE PV-3 SERVES DATA HALL 3")])]})
    (f,) = res.findings
    assert f.evidence_state == EVIDENCE_TEXT_GROUNDED
    assert [leg.evidence_state for leg in f.also_on] == [EVIDENCE_TEXT_GROUNDED]


def test_the_capped_text_alone_would_have_dropped_that_quote():
    """Pins what the grounding reads: with the uncapped text unavailable, the
    capped string is all there is, and the tail quote is refuted (§2 rule 15)."""
    geoms = [_geom("SRC-0001", "F-101.pdf", "F-101", full=_tail_text("F-101", _TAIL)),
             _geom("SRC-0002", "F-102.pdf", "F-102", ["PRE-ACTION VALVE PV-3 SERVES DATA HALL 3"])]
    geoms[0].full_sheet_text = None
    res, _ = _run(geoms, whole={"findings": [
        _item("S001", _TAIL, [("S002", "PRE-ACTION VALVE PV-3 SERVES DATA HALL 3")])]})
    assert res.findings == []
    assert _counts(res)["legs_ungrounded_quote_text_bearing_sheet"] == 1


def test_a_scanned_sheet_leg_is_admitted_at_reduced_trust_and_falls_back_to_its_tile():
    geoms = [_geom("SRC-0001", "scan.pdf", "", []),
             _geom("SRC-0002", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"])]
    res, _ = _run(geoms, whole={"findings": [
        _item("S001", "P-1", [("S002", "PUMP P-1 FEEDER 208V")], tile_label="r2c2")]})
    (f,) = res.findings
    assert f.sheet_id == "scan-p1"
    assert f.evidence_state == EVIDENCE_UNAVAILABLE
    assert _counts(res) == {"legs_admitted_no_text_evidence": 1, "legs_accepted_grounded": 1}
    resolve_anchors([f], geoms[0])
    assert f.anchor.status == "TILE" and f.anchor.method == "tile_no_text_evidence"


def test_a_tile_without_words_on_a_text_bearing_sheet_is_unavailable_not_refuted():
    geoms = [_geom("SRC-0001", "M-101.pdf", "M-101", ["PUMP P-1 480V"]),
             _geom("SRC-0002", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"])]
    # r1c2 holds no word on M-101 (its lines sit in r1c1, its id in r2c2).
    res, _ = _run(geoms, whole={"findings": [
        _item("S001", "DETAIL 7 PUMP BASE", [("S002", "PUMP P-1 FEEDER 208V")],
              tile_label="r1c2")]})
    (f,) = res.findings
    assert f.evidence_state == EVIDENCE_UNAVAILABLE


def test_an_unmatched_quote_on_a_text_bearing_sheet_is_dropped_and_counted():
    geoms = [_geom("SRC-0001", "M-101.pdf", "M-101", ["PUMP P-1 480V"]),
             _geom("SRC-0002", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"])]
    res, _ = _run(geoms, whole={"findings": [
        _item("S001", "PUMP P-9 999V", [("S002", "PUMP P-1 FEEDER 208V")])]})
    assert res.findings == []
    assert _counts(res) == {"legs_ungrounded_quote_text_bearing_sheet": 1,
                            "legs_accepted_grounded": 1,
                            "findings_dropped_under_two_legs": 1}
    assert res.discards.by_sheet["SRC-0001:p0"] == {
        "legs_ungrounded_quote_text_bearing_sheet": 1}


@pytest.mark.parametrize("tag", ["P-1", "AHU-7", "M-1", "3"],
                         ids=["P-1", "AHU-7", "M-1", "a lone digit"])
def test_short_tags_get_no_exemption(tag):
    printed = [_geom("SRC-0001", "M-101.pdf", "M-101", [f"SEE {tag} HERE"]),
               _geom("SRC-0002", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"])]
    absent = [_geom("SRC-0001", "M-101.pdf", "M-101", ["SEE NOTE HERE"]),
              _geom("SRC-0002", "E-101.pdf", "E-101", ["PUMP P-1 FEEDER 208V"])]
    reply = {"findings": [_item("S001", tag, [("S002", "PUMP P-1 FEEDER 208V")])]}
    kept, _ = _run(printed, whole=reply)
    dropped, _ = _run(absent, whole=reply)
    assert [f.evidence_state for f in kept.findings] == [EVIDENCE_TEXT_GROUNDED]
    assert dropped.findings == []
    assert dropped.discards.legs_ungrounded_quote_text_bearing_sheet == 1


def test_an_unplaceable_item_is_counted_with_the_sharded_counter():
    res, _ = _run(_two_m101(), whole={"findings": [
        _item("S001", "PUMP P-1 480V", [("S001", "PUMP P-1 480V")]),      # one sheet
        _item("S001", "PUMP P-1 480V", [("Z-999", "x")]),                  # unknown leg
    ]})
    assert res.findings == []
    assert res.discards.findings_dropped_under_two_legs == 2
    assert res.invalid.total == 0, "a binding loss is not a refused field"


def test_a_refused_field_stays_a_separate_record():
    res, _ = _run(_two_m101(), whole={"findings": [
        _item("S001", "PUMP P-1 480V", [("S003", "PUMP P-1 FEEDER 208V")], severity="question")]})
    assert res.invalid.findings_invalid_severity == 1
    assert _counts(res) == {}, "refused before any sheet is resolved: no discard"


# --------------------------------------------------------------------------- #
# Claims rebound through handles
# --------------------------------------------------------------------------- #


def _claim(sheet, quote="20 20 20 TOTAL 60", terms=(20, 20, 20), expected=60):
    return {"sheet_id": sheet, "quote": quote, "kind": "sum", "terms": list(terms),
            "expected": expected}


@pytest.mark.parametrize("ref,expected", [
    ("S002", ("SRC-0002", "M-101.pdf", 0, "M-101")),
    ("E-101", ("SRC-0003", "E-101.pdf", 0, "E-101")),
    ("M-101", ("", "", 0, "M-101")),
    ("S099", ("", "", 0, "S099")),
], ids=["by handle", "a legacy id naming one sheet", "an id two PDFs carry stays unbound",
        "an invalid handle stays unbound"])
def test_whole_set_claims_are_rebound_through_handles(ref, expected):
    res, _ = _run(_two_m101(), whole={"claims": [_claim(ref)]})
    (c,) = res.claims
    assert (c.source_id, c.source_name, c.page_index, c.sheet_id) == expected


def test_the_auditor_refuses_an_unbound_claim_whose_id_two_sheets_carry():
    geoms = _two_m101()
    res, _ = _run(geoms, whole={"claims": [_claim("M-101", "20 20 TOTAL 50", (20, 20), 50)]})
    ares = audit_arithmetic(res.claims, geoms)
    assert ares.findings == [], "never checked against the first M-101"
    assert (ares.checked, ares.ambiguous) == (0, 1)


def test_claim_dedup_keeps_one_quote_on_two_same_label_sheets_apart():
    res, _ = _run(_two_m101(), whole={"claims": [_claim("S001"), _claim("S002")]})
    assert sorted(c.source_id for c in res.claims) == ["SRC-0001", "SRC-0002"]


def test_claim_dedup_still_collapses_one_claim_spelled_twice():
    res, _ = _run(_two_m101(), whole={"claims": [
        _claim("S001"), _claim("S001", terms=("20", "20.0", 20), expected="60.0")]})
    assert len(res.claims) == 1


# --------------------------------------------------------------------------- #
# Ambiguity accounting (the owner's rule: observational, a stage warning)
# --------------------------------------------------------------------------- #


def test_the_ambiguity_counters_are_additive_and_read_back_zero_from_an_older_entry():
    counts = X.CrossQCDiscardCounts.from_dict({"legs_unresolved_handle": 2})
    assert counts.legs_ambiguous_label == 0 and counts.facts_ambiguous_label == 0
    counts.bump("legs_ambiguous_label")
    again = X.CrossQCDiscardCounts.from_dict(json.loads(json.dumps(counts.to_dict())))
    assert again.legs_ambiguous_label == 1 and again.legs_unresolved_handle == 2


def test_the_ambiguity_note_names_the_refused_references():
    counts = X.CrossQCDiscardCounts()
    assert counts.ambiguity_note() == ""
    counts.bump("legs_ambiguous_label")
    counts.bump("legs_ambiguous_label")
    counts.bump("facts_ambiguous_label")
    note = counts.ambiguity_note()
    assert note.startswith("3 sheet reference(s) named a sheet id that more than one sheet carries")
    assert "2 leg(s), 1 fact(s)" in note


def test_an_ambiguous_fact_is_counted_on_the_map_path(monkeypatch):
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)

    def _map(body):
        facts = [{"sheet_handle": "M-101", "entity_or_tag": "P-1", "attribute": "v",
                  "value": "480", "exact_quote": "PUMP P-1 480V"},
                 {"sheet_handle": "E-101", "entity_or_tag": "P-1", "attribute": "v",
                  "value": "208", "exact_quote": "PUMP P-1 FEEDER 208V"}]
        return {"facts": facts if "S003 = E-101" in body else []}

    res, _ = _run(_two_m101(), map_=_map)
    assert res.discards.facts_ambiguous_label == 1
    assert res.discards.facts_accepted == 1


# --------------------------------------------------------------------------- #
# K2: the user-turn framing rides the key
# --------------------------------------------------------------------------- #


def _entries(geoms):
    return [(X.detect_sheet_id(g) or X._fallback_id(g.ref), "Sheet - Plan", g.sheet_text, g)
            for g in geoms]


def _framing_set():
    # The scan's fallback id (100-p1) has no discipline, so the manifest shows
    # the unknown-discipline mark too.
    return [*_two_m101(), _geom("SRC-0004", "100.pdf", "", [])]


def _key(geoms):
    return X._cross_qc_cache_key(_entries(geoms), model="claude-opus-5-5", preamble="")


def _requests(geoms):
    """Every user turn the three builders produce for ``geoms``."""
    entries = X._canonical_order(_entries(geoms))
    handles = X._assign_handles(entries)
    facts = [X.CrossQCFact(sheet_handle="S001", sheet_id="M-101", discipline="M",
                           entity_or_tag="P-1", attribute="v", value="480",
                           exact_quote="PUMP P-1 480V")]
    return (
        X._build_whole_set_input(entries, handles, X._Budget()),
        X._build_map_input(entries, handles.handle_by_key, X._Budget()),
        X._build_reconcile_input(handles.manifest, facts),
    )


_MODEL_VISIBLE_FRAMING = [n for n in X.CROSS_QC_USER_FRAMING_NAMES
                          if n != "_TRUNCATION_MARKER_TEMPLATE"]


@pytest.mark.parametrize("name", _MODEL_VISIBLE_FRAMING, ids=_MODEL_VISIBLE_FRAMING)
def test_each_framing_string_is_model_visible_and_in_the_key(monkeypatch, name):
    geoms = _framing_set()
    before_key, before_requests = _key(geoms), _requests(geoms)
    value = getattr(X, name)
    monkeypatch.setattr(X, name, value.replace(" ", "  ", 1) if " " in value else value + " ")
    assert _requests(geoms) != before_requests, f"{name} is not in any request"
    assert _key(geoms) != before_key, f"{name} changes the request but not the key"


def test_the_truncation_marker_is_in_the_key(monkeypatch):
    # Changing a model-visible omission marker changes the request identity.
    geoms = _two_m101()
    before = _key(geoms)
    monkeypatch.setattr(X, "_TRUNCATION_MARKER_TEMPLATE", "\n[CUT {omitted} chars]")
    assert _key(geoms) != before


def test_the_truncation_marker_is_the_one_the_budget_writes():
    budget = X._Budget()
    capped = X._budgeted_text_layer("x" * (X._TEXT_LAYER_BUDGET + 5), budget)
    assert capped.endswith(X._TRUNCATION_MARKER_TEMPLATE.format(omitted=5))


def test_every_framing_name_is_a_module_string():
    names = X.CROSS_QC_USER_FRAMING_NAMES
    assert len(set(names)) == len(names)
    framing = X.cross_qc_user_framing()
    assert list(framing) == list(names)
    assert all(isinstance(getattr(X, n), str) and framing[n] == getattr(X, n) for n in names)


def test_the_requests_keep_their_bytes_apart_from_the_sheet_title():
    """PO-03 changes source framing, preserving decoded fields and host tasks."""
    geoms = _framing_set()
    whole, shard, reconcile = _requests(geoms)
    root = ET.fromstring(f"<request>{reconcile}</request>")
    metadata = [el.text[1:-1] for el in root.findall("sheet_metadata")]
    assert "  S004 = 100-p1 (?)" in metadata
    assert whole.startswith("DRAWING SET — 4 sheet(s). For each sheet you get its "
                            "structured digest and its verbatim text layer.\n")
    assert whole.endswith("\n" + X._CROSS_QC_TASK)
    assert shard.startswith("DRAWING SET SHARD — 4 sheet(s), each labeled with an opaque "
                            "HANDLE. Refer to sheets only by handle.\n")
    assert reconcile.startswith("SHEET MANIFEST (handle = sheet-id (discipline)):\n")
    assert metadata[0] == "  S001 = M-101 (m)"
    assert root.find("cross_qc_fact").text[1:-1] == '  S001 | P-1 | v | 480 | "PUMP P-1 480V"'


# --------------------------------------------------------------------------- #
# Through the pipeline: two PDFs with one sheet id
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.export import write_drawing_export  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402


def _mkpdf(path, body, sid):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((80, 120), body)
    page.insert_text((650, 560), sid)
    doc.save(str(path))
    doc.close()
    return path


class _Pipeline(BetaClientMixin):
    """Digest + whole-set cross-QC + the dual-crop verifier."""

    def __init__(self, cross):
        self.cross = cross
        self.verify_images = []
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                if isinstance(system, list):
                    system = "".join(b.get("text", "") for b in system if isinstance(b, dict))
                body = kw["messages"][0]["content"]
                if system == VERIFY_SYSTEM_PROMPT:
                    outer.verify_images.append(sum(
                        1 for b in body if isinstance(b, dict) and b.get("type") == "image"))
                    text = '{"verdict":"CONFIRMED","note":"x"}'
                elif system.startswith(X.CROSS_QC_SYSTEM_PROMPT):
                    text = _fenced({"findings": outer.cross, "claims": []})
                elif system.startswith(DIGEST_SYSTEM_PROMPT):
                    text = "Sheet - Plan\nPump room.\n\n" + _fenced({"findings": []})
                else:
                    text = "ok"
                return FakeMessage(content=[FakeTextBlock(text=text)],
                                   usage=FakeUsage(input_tokens=100, output_tokens=20))

        self.messages = _Msgs()


def _same_label_pdfs(tmp_path):
    return [_mkpdf(tmp_path / "a" / "M-101.pdf", "PUMP P-1 480V", "M-101"),
            _mkpdf(tmp_path / "b" / "M-101.pdf", "PUMP P-1 208V", "M-101")]


def _cross_stage(ctx):
    (stage,) = [s for s in ctx.stage_results if s.stage == "cross_qc"]
    return stage


def test_pipeline_a_conflict_between_two_same_label_pdfs_is_verified_and_inked_on_both(tmp_path):
    client = _Pipeline([_item("S001", "PUMP P-1 480V", [("S002", "PUMP P-1 208V")])])
    ctx = extract_drawing_context(
        _same_label_pdfs(tmp_path), client=client, rows=2, cols=2, cross_qc=True,
        qc_markups=True, qc_work_dir=tmp_path / "qc")
    (conflict,) = [f for f in ctx.findings if f.also_on]
    assert (conflict.source_id, [leg.source_id for leg in conflict.also_on]) == (
        "SRC-0001", ["SRC-0002"])
    assert conflict.sheet_id == "M-101" and conflict.also_on[0].sheet_id == "M-101"
    assert conflict.evidence_state == EVIDENCE_TEXT_GROUNDED
    assert client.verify_images == [2], "one dual-crop call, a crop from each PDF"
    assert ctx.cross_qc_discards["legs_accepted_grounded"] == 2
    export = write_drawing_export(ctx, tmp_path / "out", source_names=["a", "b"])
    manifest = json.loads((export / "markup_manifest.json").read_text(encoding="utf-8"))
    placements = {p["placement_id"]: p["source_id"] for p in manifest["placements"]
                  if p.get("finding_id") == conflict.id}
    assert sorted(placements.values()) == ["SRC-0001", "SRC-0002"]
    written = {r["placement"]["placement_id"]: r["status"] for r in manifest["receipts"]}
    assert {written[pid] for pid in placements} == {"WRITTEN"}
    assert ctx.coverage_status == "COMPLETE"


def test_pipeline_an_ambiguous_reference_is_a_warning_and_the_stage_keeps_its_status(tmp_path):
    reply = [_item("M-101", "PUMP P-1 480V", [("M-101", "PUMP P-1 208V")], key="sheet_id")]
    ctx = extract_drawing_context(
        _same_label_pdfs(tmp_path), client=_Pipeline(reply), rows=2, cols=2,
        cross_qc=True, qc_work_dir=tmp_path / "qc")
    stage = _cross_stage(ctx)
    assert stage.status == "COMPLETE"
    assert [f for f in ctx.findings if f.also_on] == []
    (warning,) = stage.warnings
    assert warning.startswith("2 sheet reference(s) named a sheet id that more than one sheet carries")
    assert ctx.cross_qc_discards["legs_ambiguous_label"] == 2
    export = write_drawing_export(ctx, tmp_path / "out", source_names=["a", "b"])
    run_manifest = json.loads((export / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["cross_qc_discards"]["legs_ambiguous_label"] == 2
    (m_stage,) = [s for s in run_manifest["stages"] if s["stage"] == "cross_qc"]
    assert m_stage["warnings"] == [warning]


def test_pipeline_the_ambiguity_warning_survives_a_warm_run(tmp_path):
    from drawing_analyzer.digest_cache import DigestCache

    reply = [_item("M-101", "PUMP P-1 480V", [("M-101", "PUMP P-1 208V")], key="sheet_id")]
    cache = DigestCache(tmp_path / "cache.sqlite")
    pdfs = _same_label_pdfs(tmp_path)
    warnings = []
    for _ in range(2):
        ctx = extract_drawing_context(
            pdfs, client=_Pipeline(reply), rows=2, cols=2, cross_qc=True, cache=cache,
            qc_work_dir=tmp_path / "qc")
        warnings.append(_cross_stage(ctx).warnings)
    assert warnings[0] == warnings[1] and len(warnings[0]) == 1
