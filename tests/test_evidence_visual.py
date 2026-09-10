"""WP-03B — evidence that is not in the text layer at all.

The three-state grounding contract (README, "Evidence the host cannot check";
CLAUDE.md, `classify_quote_evidence`). WP-03A recovered quotes past the prompt
cap, where the text was still there to find. This covers the cases where there
is nothing to find:

- a **scanned** sheet has no text layer, so every quote on it failed grounding
  and — worse — `_parse_facts` dropped every fact, excluding the sheet from
  cross-shard reconciliation entirely;
- a **hybrid** sheet has words (so `is_raster` is False) and still cannot
  support a text check over its pasted raster detail;
- a leg with **no quote at all** short-circuited the check and was trusted more
  readily than one whose quote merely failed to match.

The fix admits these at *reduced trust* rather than dropping them — but §2.2 is
emphatic that admission without a location is a dead end, so this file also pins
the three-part route that makes them verifiable, and the negative half: on a
text-bearing sheet an unmatched quote is still the hallucination signal.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import drawing_analyzer.cross_qc as X
from drawing_analyzer.anchor import resolve_anchors, resolve_conflict_legs
from drawing_analyzer.cross_qc import (
    CrossQCFact,
    _finding_from_handles,
    _parse_facts,
    classify_quote_evidence,
    cross_sheet_qc,
    fact_tile_lookup,
)
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.investigate import _candidates
from drawing_analyzer.models import (
    EVIDENCE_NOT_MATCHED,
    EVIDENCE_TEXT_GROUNDED,
    EVIDENCE_UNAVAILABLE,
    ConflictLeg,
    Finding,
    SheetGeometry,
    SheetRef,
    Verification,
    is_reduced_trust,
)
from drawing_analyzer.verify import _has_anchored_legs
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage
from tests.test_drawing_cross_qc import BetaClientMixin, StreamingMessagesMixin

W, H = 792.0, 612.0
SCANNED_QUOTE = "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2"


def _w(x, y, text, w=60, h=12):
    return (float(x), float(y), float(x + w), float(y + h), text, 0, 0, 0)


def _ref(source: str) -> SheetRef:
    return SheetRef(pdf_path=Path(source), page_index=0, source_name=source,
                    page_count=1)


def _geom(source: str, sid: str, *, text: str, words=None) -> SheetGeometry:
    """``text=""`` models a scanned sheet: no text layer to check against."""
    return SheetGeometry(
        ref=_ref(source), page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=list(words if words is not None else [_w(10, 10, sid)]),
        sheet_text=text, full_sheet_text=text, is_raster=not words and not text,
    )


def _entry(handle: str, geom: SheetGeometry) -> dict:
    return {handle: (handle, geom)}


# --------------------------------------------------------------------------- #
# §8.3 — three states, and the one that must not be renamed "contradicted"
# --------------------------------------------------------------------------- #


def test_scanned_sheet_yields_unavailable_not_a_refutation():
    geom = _geom("scan.pdf", "AS-1", text="", words=[])
    assert classify_quote_evidence(SCANNED_QUOTE, geom) == EVIDENCE_UNAVAILABLE


def _hybrid_geom() -> SheetGeometry:
    """A *real* hybrid sheet: selectable title block, pasted raster detail.

    The first cut of this test used ``text="   "``, which strips to empty — that
    is a scanned sheet with a stray space, not a hybrid one, and it passed for
    the wrong reason (a code review caught it). A genuine hybrid sheet has a
    populated text layer, so ``full_sheet_text`` is non-empty and any
    sheet-level "is there text?" question answers *yes*. The whole point is that
    the answer must be asked of the **region** the quote was read from.

    Layout on a 792x612 page, 2x2 grid: every word sits in the bottom-right
    quadrant (the title block); the top-left tile [0, 0] is the pasted detail
    and holds none. Tiles overlap by ``DEFAULT_OVERLAP_FRAC``, so the words are
    placed well clear of the boundary rather than just past it.
    """
    title_block = [
        _w(600, 520, "MECHANICAL"), _w(600, 540, "PLAN"),
        _w(600, 560, "M-1"), _w(600, 580, "SCALE 1/8"),
    ]
    return SheetGeometry(
        ref=_ref("hybrid.pdf"), page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=title_block,
        sheet_text="MECHANICAL PLAN M-1 SCALE 1/8",
        full_sheet_text="MECHANICAL PLAN M-1 SCALE 1/8",
        is_raster=False,
    )


def test_hybrid_sheet_is_reached_without_consulting_is_raster():
    """A hybrid sheet has words *and* text, so neither flag routes it — §2.1.

    `render.py` populates `full_sheet_text` from `page.get_text()`, so a single
    selectable title block makes the sheet-level evidence non-empty. Classifying
    on that alone sends a quote read off the pasted detail to
    `EVIDENCE_NOT_MATCHED`, which drops it: the advertised hybrid recovery would
    never fire on any real hybrid page. The classifier therefore asks whether
    *the reported tile* carries words.
    """
    geom = _hybrid_geom()
    assert geom.is_raster is False
    assert geom.full_sheet_text.strip(), "a hybrid sheet does have a text layer"
    # Sheet-level: there IS text, so the sheet-wide question answers "yes".
    assert X._grounded(SCANNED_QUOTE, geom.full_sheet_text) is False
    # Region-level: tile [0, 0] is the pasted detail — pixels only.
    assert X._tile_has_words(geom, [0, 0]) is False
    assert classify_quote_evidence(SCANNED_QUOTE, geom, [0, 0]) == EVIDENCE_UNAVAILABLE


def test_hybrid_sheet_text_bearing_tile_still_signals_a_bad_quote():
    """The other half: a quote attributed to the *title block* tile.

    That region has selectable words. A quote that is not among them is the
    hallucination signal exactly as before — the region rule must not become a
    blanket amnesty for every quote on a sheet that happens to contain one
    image.
    """
    geom = _hybrid_geom()
    assert X._tile_has_words(geom, [1, 1]) is True
    assert classify_quote_evidence(SCANNED_QUOTE, geom, [1, 1]) == EVIDENCE_NOT_MATCHED


def test_hybrid_sheet_without_a_tile_is_not_given_the_benefit_of_the_doubt():
    """No location reported -> the sheet-level answer stands (NOT_MATCHED).

    `_tile_has_words` returns True for an unknown tile precisely so absence of a
    location cannot be read as "the region had no text". Without that, every
    unlocatable bad quote on a text-bearing sheet would be laundered into
    reduced-trust admission.
    """
    geom = _hybrid_geom()
    assert X._tile_has_words(geom, None) is True
    assert classify_quote_evidence(SCANNED_QUOTE, geom) == EVIDENCE_NOT_MATCHED


def test_unmatched_quote_on_a_text_bearing_sheet_stays_the_signal():
    geom = _geom("v.pdf", "FP-1", text="FP-1 title. SOME OTHER NOTE.")
    assert classify_quote_evidence(SCANNED_QUOTE, geom) == EVIDENCE_NOT_MATCHED


def test_found_quote_is_text_grounded():
    geom = _geom("v.pdf", "FP-1", text=f"FP-1 title. {SCANNED_QUOTE} end.")
    assert classify_quote_evidence(SCANNED_QUOTE, geom) == EVIDENCE_TEXT_GROUNDED


def test_absent_quote_is_never_implicitly_grounded():
    """Trigger 3 closed: silence is at best 'unavailable', never trusted."""
    geom = _geom("v.pdf", "FP-1", text=f"FP-1 title. {SCANNED_QUOTE} end.")
    assert classify_quote_evidence("", geom) == EVIDENCE_UNAVAILABLE
    assert classify_quote_evidence("   ", geom) == EVIDENCE_UNAVAILABLE


# --------------------------------------------------------------------------- #
# Trigger 2's larger half — a scanned sheet must reach reconciliation
# --------------------------------------------------------------------------- #


def test_scanned_sheet_now_contributes_facts():
    """With no facts, that sheet never entered cross-shard reconciliation."""
    entries = _entry("S001", _geom("scan.pdf", "AS-1", text="", words=[]))
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": SCANNED_QUOTE,
                    "tile_label": "r1c1"}]},
        entries, {},
    )
    assert len(facts) == 1
    assert facts[0].evidence_state == EVIDENCE_UNAVAILABLE
    assert facts[0].tile == [0, 0]


def test_a_fact_the_model_could_not_place_carries_no_tile():
    entries = _entry("S001", _geom("scan.pdf", "AS-1", text="", words=[]))
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": SCANNED_QUOTE}]},
        entries, {},
    )
    assert facts[0].tile is None, "never synthesize a location"


def test_an_out_of_bounds_tile_label_degrades_to_none():
    entries = _entry("S001", _geom("scan.pdf", "AS-1", text="", words=[]))
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": SCANNED_QUOTE,
                    "tile_label": "r9c9"}]},          # grid is 2x2
        entries, {},
    )
    assert facts[0].tile is None, "a bad label must not become a wrong rectangle"


# --------------------------------------------------------------------------- #
# §8.4 Part 1 — the map path carries a location
# --------------------------------------------------------------------------- #


def test_map_prompt_requests_a_tile_label_for_facts_and_legs():
    prompt = X.cross_qc_map_system_prompt()
    assert prompt.count("tile_label") >= 3, "findings, also_on legs and facts"


def test_sharded_finding_no_longer_hardcodes_no_tile():
    entries = {
        **_entry("S001", _geom("a.pdf", "A-1", text="A-1 title. ALPHA NOTE.")),
        **_entry("S002", _geom("b.pdf", "B-1", text="B-1 title. BETA NOTE.")),
    }
    finding = _finding_from_handles({
        "category": "conflict", "severity": "high", "text": "x",
        "sheet_handle": "S001", "source_quote": "ALPHA NOTE", "tile_label": "r1c2",
        "also_on": [{"sheet_handle": "S002", "source_quote": "BETA NOTE",
                     "tile_label": "r2c1"}],
    }, entries)
    assert finding is not None
    assert finding.tile == [0, 1]
    assert finding.also_on[0].tile == [1, 0], "each leg resolves on its OWN grid"


# --------------------------------------------------------------------------- #
# §8.4 Part 2 — the location survives reconciliation
# --------------------------------------------------------------------------- #


def test_fact_tile_lookup_joins_on_handle_and_normalized_quote():
    facts = [CrossQCFact(sheet_handle="S001", sheet_id="A-1", discipline="a",
                         entity_or_tag="PV-3", attribute="serves", value="hall",
                         exact_quote=SCANNED_QUOTE, tile=[1, 1])]
    lookup = fact_tile_lookup(facts)
    # The reconcile prompt requires quotes copied verbatim, and the join folds
    # them exactly as grounding does — so cosmetic drift still hits.
    assert lookup[("S001", X._norm_for_match(SCANNED_QUOTE.lower()))] == [1, 1]


def _fact(quote: str, tile, *, handle: str = "S001") -> CrossQCFact:
    return CrossQCFact(sheet_handle=handle, sheet_id="A-1", discipline="a",
                       entity_or_tag="PV-3", attribute="serves", value="hall",
                       exact_quote=quote, tile=tile)


def test_ambiguous_fact_join_yields_no_tile_rather_than_the_first_one():
    """A short quote can repeat on one sheet; each occurrence is its own fact.

    The obvious ``setdefault`` keeps whichever fact was parsed first and hands
    every later occurrence a rectangle belonging to somewhere else. That is
    worse than no tile: a wrong tile still anchors (``_tile_anchor``) and still
    passes ``_tile_has_words``, so it launders a guess into an artifact-backed
    location the reviewer is told to go look at.
    """
    lookup = fact_tile_lookup([_fact("150 gpm", [0, 0]), _fact("150 gpm", [3, 4])])
    assert lookup == {}


def test_ambiguity_is_order_independent_and_survives_a_later_agreeing_fact():
    """Poisoned stays poisoned — otherwise the answer depends on parse order."""
    facts = [_fact("150 gpm", [0, 0]), _fact("150 gpm", [3, 4]),
             _fact("150 gpm", [0, 0])]
    assert fact_tile_lookup(facts) == {}
    assert fact_tile_lookup(list(reversed(facts))) == {}


def test_agreeing_duplicate_facts_still_resolve():
    """Two facts, same quote, same tile: no ambiguity, so no loss of location."""
    lookup = fact_tile_lookup([_fact("150 gpm", [3, 4]), _fact("150 gpm", [3, 4])])
    assert lookup[("S001", X._norm_for_match("150 gpm"))] == [3, 4]


def test_same_quote_on_different_sheets_is_not_a_collision():
    """The handle is part of the key — "TYP." on two sheets is two facts."""
    lookup = fact_tile_lookup([_fact("TYP.", [0, 0]),
                               _fact("TYP.", [3, 4], handle="S002")])
    assert lookup[("S001", X._norm_for_match("TYP."))] == [0, 0]
    assert lookup[("S002", X._norm_for_match("TYP."))] == [3, 4]


def test_reconciled_leg_inherits_the_tile_from_its_own_fact():
    """The cross-shard path — the reason the sharded design exists (DA-015)."""
    entries = {
        **_entry("S001", _geom("scan.pdf", "AS-1", text="", words=[])),
        **_entry("S002", _geom("b.pdf", "B-1", text=f"B-1. {SCANNED_QUOTE} end.")),
    }
    facts = [
        CrossQCFact(sheet_handle="S001", sheet_id="AS-1", discipline="a",
                    entity_or_tag="PV-3", attribute="serves", value="hall",
                    exact_quote=SCANNED_QUOTE, tile=[1, 0]),
        CrossQCFact(sheet_handle="S002", sheet_id="B-1", discipline="b",
                    entity_or_tag="PV-3", attribute="serves", value="hall",
                    exact_quote=SCANNED_QUOTE, tile=[0, 1]),
    ]
    # A reconcile response: handles and quotes only, exactly as the contract says.
    finding = _finding_from_handles({
        "category": "conflict", "severity": "high", "text": "disagrees",
        "sheet_handle": "S001", "source_quote": SCANNED_QUOTE,
        "also_on": [{"sheet_handle": "S002", "source_quote": SCANNED_QUOTE}],
    }, entries, None, fact_tile_lookup(facts))
    assert finding is not None
    assert finding.tile == [1, 0], "primary leg lost its location"
    assert finding.also_on[0].tile == [0, 1], "secondary leg lost its location"


def test_a_leg_whose_quote_joins_to_no_fact_gets_no_tile():
    """A location is derived from committed evidence, never invented."""
    entries = {
        **_entry("S001", _geom("a.pdf", "A-1", text="A-1. ALPHA NOTE.")),
        **_entry("S002", _geom("b.pdf", "B-1", text="B-1. BETA NOTE.")),
    }
    facts = [CrossQCFact(sheet_handle="S001", sheet_id="A-1", discipline="a",
                         entity_or_tag="x", attribute="y", value="z",
                         exact_quote="A DIFFERENT STRING ENTIRELY", tile=[1, 1])]
    finding = _finding_from_handles({
        "category": "conflict", "severity": "high", "text": "x",
        "sheet_handle": "S001", "source_quote": "ALPHA NOTE",
        "also_on": [{"sheet_handle": "S002", "source_quote": "BETA NOTE"}],
    }, entries, None, fact_tile_lookup(facts))
    assert finding.tile is None and finding.also_on[0].tile is None


# --------------------------------------------------------------------------- #
# §8.4 Part 3 — the resolver may use the tile, but only for reduced trust
# --------------------------------------------------------------------------- #


def _anchor(finding: Finding, geom: SheetGeometry) -> Finding:
    resolve_anchors([finding], geom)
    return finding


def test_unmatched_quote_with_no_text_evidence_falls_back_to_its_tile():
    geom = _geom("scan.pdf", "AS-1", text="", words=[])
    f = Finding(sheet_id="AS-1", source_name="scan.pdf", page_index=0,
                category="conflict", severity="high", text="t",
                source_quote=SCANNED_QUOTE, tile=[0, 1],
                evidence_state=EVIDENCE_UNAVAILABLE)
    _anchor(f, geom)
    assert f.anchor.status == "TILE"
    assert f.anchor.rect_pdf is not None
    assert f.anchor.method == "tile_no_text_evidence"


def test_unmatched_quote_on_text_bearing_evidence_stays_unanchored():
    """The negative half. Part 3 must not become a blanket relaxation."""
    geom = _geom("v.pdf", "FP-1", text="FP-1 title. SOME OTHER NOTE.")
    f = Finding(sheet_id="FP-1", source_name="v.pdf", page_index=0,
                category="conflict", severity="high", text="t",
                source_quote=SCANNED_QUOTE, tile=[0, 1],
                evidence_state=EVIDENCE_NOT_MATCHED)
    _anchor(f, geom)
    assert f.anchor.status == "UNANCHORED"
    assert f.anchor.method == "quote_not_found"


def test_a_finding_with_no_evidence_state_is_unchanged():
    """Digest, critique and whole-set cross-QC never set the field."""
    geom = _geom("v.pdf", "FP-1", text="FP-1 title. SOME OTHER NOTE.")
    f = Finding(sheet_id="FP-1", source_name="v.pdf", page_index=0,
                category="conflict", severity="high", text="t",
                source_quote=SCANNED_QUOTE, tile=[0, 1])
    assert f.evidence_state == ""
    _anchor(f, geom)
    assert f.anchor.status == "UNANCHORED"
    assert f.anchor.method == "quote_not_found"


def test_reduced_trust_without_a_reported_tile_is_still_unanchored():
    geom = _geom("scan.pdf", "AS-1", text="", words=[])
    f = Finding(sheet_id="AS-1", source_name="scan.pdf", page_index=0,
                category="conflict", severity="high", text="t",
                source_quote=SCANNED_QUOTE, tile=None,
                evidence_state=EVIDENCE_UNAVAILABLE)
    _anchor(f, geom)
    assert f.anchor.status == "UNANCHORED", "no location was reported to use"


# --------------------------------------------------------------------------- #
# §2.2 — the whole point: a recovered finding must REACH verification
# --------------------------------------------------------------------------- #


def test_a_recovered_finding_reaches_verification_and_investigation():
    """Asserted against the real gatekeepers, not a copy of their conditions."""
    scanned = _geom("scan.pdf", "AS-1", text="", words=[])
    other = _geom("b.pdf", "B-1", text="", words=[])
    f = Finding(sheet_id="AS-1", source_name="scan.pdf", page_index=0,
                category="conflict", severity="high", text="t",
                source_quote=SCANNED_QUOTE, tile=[0, 1],
                evidence_state=EVIDENCE_UNAVAILABLE,
                also_on=[ConflictLeg(sheet_id="B-1", source_name="b.pdf",
                                     page_index=0, source_quote=SCANNED_QUOTE,
                                     tile=[1, 1],
                                     evidence_state=EVIDENCE_UNAVAILABLE)])
    resolve_anchors([f], scanned)
    resolve_conflict_legs([f], {("b.pdf", 0): other, ("scan.pdf", 0): scanned})

    assert _has_anchored_legs(f), "the dual-crop check cannot see it"
    f.verification = Verification(status="UNCERTAIN")
    assert f in _candidates([f]), "the investigation loop cannot see it"


def test_the_same_finding_without_a_location_reaches_neither():
    """The dead end §2.2 describes — admission alone is not recovery."""
    scanned = _geom("scan.pdf", "AS-1", text="", words=[])
    f = Finding(sheet_id="AS-1", source_name="scan.pdf", page_index=0,
                category="conflict", severity="high", text="t",
                source_quote=SCANNED_QUOTE, tile=None,
                evidence_state=EVIDENCE_UNAVAILABLE,
                also_on=[ConflictLeg(sheet_id="B-1", source_name="b.pdf",
                                     page_index=0, source_quote=SCANNED_QUOTE)])
    resolve_anchors([f], scanned)
    assert not _has_anchored_legs(f)
    f.verification = Verification(status="UNCERTAIN")
    assert _candidates([f]) == []


# --------------------------------------------------------------------------- #
# §8.3 — reduced trust must be visible, and must survive a ledger merge
# --------------------------------------------------------------------------- #


def test_evidence_state_rides_the_atomic_bundle_through_a_merge():
    """A trust label belongs to its quote; pairing it with another is §12.2's bug."""
    from drawing_analyzer.ledger import Ledger

    weak = Finding(sheet_id="A-1", source_name="a.pdf", page_index=0,
                   category="conflict", severity="high", text="valves disagree",
                   source_quote="PV", evidence_state=EVIDENCE_UNAVAILABLE)
    strong = Finding(sheet_id="A-1", source_name="a.pdf", page_index=0,
                     category="conflict", severity="high", text="valves disagree",
                     source_quote="PRE-ACTION VALVE PV-3 SERVES DATA HALL 2",
                     evidence_state=EVIDENCE_TEXT_GROUNDED)
    ledger = Ledger()
    ledger.add([weak], source="cross_qc")
    ledger.add([strong], source="cross_qc")
    ledger.seal()
    entries = list(ledger.entries)
    if len(entries) == 1:                       # they merged
        merged = entries[0]
        assert (merged.source_quote, merged.evidence_state) in {
            ("PV", EVIDENCE_UNAVAILABLE),
            ("PRE-ACTION VALVE PV-3 SERVES DATA HALL 2", EVIDENCE_TEXT_GROUNDED),
        }, "the trust label drifted away from the quote it describes"


def test_markup_says_why_it_could_not_be_checked():
    from drawing_analyzer.annotate import _annot_content

    f = Finding(sheet_id="AS-1", source_name="scan.pdf", page_index=0,
                category="conflict", severity="high", text="valves disagree",
                source_quote=SCANNED_QUOTE, evidence_state=EVIDENCE_UNAVAILABLE)
    content = _annot_content(f, unverified=True, place="SHEET")
    assert "[NO TEXT TO CHECK]" in content
    assert "No searchable text on this sheet" in content
    assert content.isascii(), "base-14 fonts miss non-ASCII glyphs"


def test_markup_is_unchanged_for_a_text_grounded_finding():
    from drawing_analyzer.annotate import _annot_content

    f = Finding(sheet_id="FP-1", source_name="v.pdf", page_index=0,
                category="conflict", severity="high", text="valves disagree",
                source_quote=SCANNED_QUOTE, evidence_state=EVIDENCE_TEXT_GROUNDED)
    content = _annot_content(f, unverified=True, place="SHEET")
    assert "[NO TEXT TO CHECK]" not in content
    assert "No searchable text" not in content


def test_report_flags_a_reduced_trust_quote():
    from drawing_analyzer.html_report import _finding_row_html

    f = Finding(sheet_id="AS-1", source_name="scan.pdf", page_index=0,
                category="conflict", severity="high", text="valves disagree",
                source_quote=SCANNED_QUOTE, evidence_state=EVIDENCE_UNAVAILABLE)
    row = _finding_row_html(f, None, link_evidence=False)
    assert "finding-evidence-note" in row
    assert "not checked automatically" in row


def test_report_is_unchanged_for_a_text_grounded_quote():
    from drawing_analyzer.html_report import _finding_row_html

    f = Finding(sheet_id="FP-1", source_name="v.pdf", page_index=0,
                category="conflict", severity="high", text="valves disagree",
                source_quote=SCANNED_QUOTE, evidence_state=EVIDENCE_TEXT_GROUNDED)
    assert "finding-evidence-note" not in _finding_row_html(f, None, link_evidence=False)


def test_the_reviewer_is_never_told_a_text_bearing_sheet_has_no_text():
    """F4: `EVIDENCE_UNAVAILABLE` covers two situations, not one.

    An omitted quote is unavailable evidence just as a scanned sheet is — the
    host can check neither — but a reviewer looking at a sheet whose text they
    can select, being told "No searchable text on this sheet", learns that the
    tool's caveats are unreliable. One false caveat discredits every true one on
    the same page.
    """
    from drawing_analyzer.annotate import _annot_content
    from drawing_analyzer.html_report import _finding_row_html

    no_quote = Finding(sheet_id="M-1", source_name="hybrid.pdf", page_index=0,
                       category="conflict", severity="high", text="valves disagree",
                       source_quote="", evidence_state=EVIDENCE_UNAVAILABLE)
    content = _annot_content(no_quote, unverified=True, place="SHEET")
    assert "No searchable text" not in content
    assert "gave no quote" in content
    assert "[NO QUOTE TO CHECK]" in content
    assert content.isascii(), "base-14 fonts miss non-ASCII glyphs"

    row = _finding_row_html(no_quote, None, link_evidence=False)
    assert "No searchable text" not in row
    assert "No quote supplied" in row


def test_the_two_unavailable_cases_read_differently():
    """Same state, different sentence — that is the whole point of §8.3's F4.

    Compares the *trust note* rather than the whole annotation body: the body
    also embeds the quote, so two findings that differ only by having one would
    compare unequal no matter what the note said.
    """
    from drawing_analyzer.annotate import _trust_note

    def note(quote: str) -> str:
        return _trust_note(
            Finding(sheet_id="X", source_name="x.pdf", page_index=0,
                    category="conflict", severity="high", text="t",
                    source_quote=quote, evidence_state=EVIDENCE_UNAVAILABLE),
            unverified=True, rejected=False,
        )

    assert note("") != note(SCANNED_QUOTE)
    # ...and both still say, in their own way, that nothing was checked.
    assert "confirm it visually" in note("")
    assert "confirm it visually" in note(SCANNED_QUOTE)


def test_reduced_trust_reason_classifies_all_three_cases():
    from drawing_analyzer.models import (
        TRUST_REASON_NO_QUOTE, TRUST_REASON_NO_TEXT, TRUST_REASON_NOT_FOUND,
        reduced_trust_reason,
    )

    def f(quote, state):
        return Finding(sheet_id="X", source_name="x.pdf", page_index=0,
                       category="conflict", severity="high", text="t",
                       source_quote=quote, evidence_state=state)

    assert reduced_trust_reason(f("", EVIDENCE_UNAVAILABLE)) == TRUST_REASON_NO_QUOTE
    assert reduced_trust_reason(f("   ", EVIDENCE_UNAVAILABLE)) == TRUST_REASON_NO_QUOTE
    assert reduced_trust_reason(f("q", EVIDENCE_UNAVAILABLE)) == TRUST_REASON_NO_TEXT
    assert reduced_trust_reason(f("q", EVIDENCE_NOT_MATCHED)) == TRUST_REASON_NOT_FOUND
    assert reduced_trust_reason(f("q", EVIDENCE_TEXT_GROUNDED)) == ""
    assert reduced_trust_reason(f("q", "")) == ""


def test_a_legs_own_evidence_state_reaches_its_own_markup():
    """F3: a conflict can be grounded on one sheet and visual on the other.

    `_units_for_finding` draws one mark per leg from a synthetic `Finding`. It
    copied the leg's quote and anchor but the *parent's* trust, so the mark
    sitting on the sheet with nothing to check against carried no caveat, while
    the mark on the corroborated sheet could inherit one it had not earned.
    """
    import itertools

    from drawing_analyzer.annotate import _units_for_finding

    leg = ConflictLeg(sheet_id="AS-1", source_name="scan.pdf", source_id="SRC-0002",
                      page_index=1, source_quote=SCANNED_QUOTE,
                      evidence_state=EVIDENCE_UNAVAILABLE)
    parent = Finding(sheet_id="FP-1", source_name="v.pdf", source_id="SRC-0001",
                     page_index=0, category="conflict", severity="high",
                     text="valves disagree", source_quote=SCANNED_QUOTE,
                     evidence_state=EVIDENCE_TEXT_GROUNDED, also_on=[leg])
    units = _units_for_finding(parent, run_id="r", ordinals=itertools.count(1),
                               include_unverified=True, ink_rejected=False)
    by_sheet = {u.finding.sheet_id: u.finding for u in units}
    assert by_sheet["AS-1"].evidence_state == EVIDENCE_UNAVAILABLE
    assert by_sheet["FP-1"].evidence_state == EVIDENCE_TEXT_GROUNDED
    # And the primary, seen as a leg of the synthetic one, keeps its own state.
    assert by_sheet["AS-1"].also_on[0].evidence_state == EVIDENCE_TEXT_GROUNDED


def test_legacy_findings_are_not_relabelled():
    """"" means "not assessed"; treating it as reduced would relabel everything."""
    f = Finding(sheet_id="A", source_name="a.pdf", page_index=0,
                category="conflict", severity="high", text="t", source_quote="q")
    assert is_reduced_trust(f) is False


# --------------------------------------------------------------------------- #
# §8.5 — the map-prompt edit is what invalidates the cache (no contract bump)
# --------------------------------------------------------------------------- #


def test_the_prompt_edit_supplies_the_invalidation():
    """All three prompts ride every cross-QC key, so editing one changes them all."""
    geom = _geom("a.pdf", "A-1", text="A-1 title.")
    entries = [("A-1", "digest", geom.sheet_text, geom)]
    key = X._cross_qc_cache_key(entries, model="m", preamble="")

    original = X.cross_qc_map_system_prompt
    X.cross_qc_map_system_prompt = lambda: original() + " EDITED"
    try:
        assert X._cross_qc_cache_key(entries, model="m", preamble="") != key
    finally:
        X.cross_qc_map_system_prompt = original


def test_contract_counter_is_not_bumped_by_this_package():
    # 3, not 2, because P8 item 11 bumped it for its own reason (the `_norm_id`
    # fold — host-side binding that no key input covers). WP-03B added nothing to
    # it, which is what this tripwire keeps honest: a bump has to be justified
    # here before the value moves again.
    assert X._CROSS_QC_CACHE_CONTRACT == 3
