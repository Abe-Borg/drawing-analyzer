"""Phase 20 — lossless ledger reconciliation & the QC-ID lifecycle (§12).

Pure and hermetic: synthetic findings, no PyMuPDF, no network. Covers the §12
required behaviors — tile/geometry are never sufficient to merge, coherent
grounding, order-independent numbering, positional QC ids, cross-sheet leg
distinctness, and the OPEN→SEALED→NUMBERED lifecycle with post-anchor Pass B.
"""
from __future__ import annotations

from pathlib import Path

from drawing_analyzer.ledger import Ledger, reconcile_post_anchor
from drawing_analyzer.models import Anchor, ConflictLeg, Finding, Verification


def _f(text, *, sid="SRC-0001", source="M-101.pdf", page=0, quote="", cat="code",
       sev="medium", rect=None, tile=None, hint="", also_on=None):
    return Finding(
        sheet_id="M-101", source_name=source, source_id=sid, page_index=page,
        category=cat, severity=sev, text=text, source_quote=quote, tile=tile,
        anchor_hint=hint,
        anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="t") if rect else Anchor(),
        also_on=list(also_on or []),
    )


# --------------------------------------------------------------------------- #
# §12.1 — a tile / geometry is never sufficient to merge
# --------------------------------------------------------------------------- #


def test_unrelated_same_tile_stays_two_entries():
    led = Ledger()
    led.add([_f("VAV-3 has no clearance to the wall", quote="VAV-3", tile=[0, 0])], "digest_json")
    led.add([_f("Unrelated note about pipe insulation", quote="INSUL", tile=[0, 0])], "critique_1")
    assert len(led) == 2                       # same tile is NOT identity


def test_overlapping_rects_stay_separate_without_semantic_match():
    led = Ledger()
    led.add([_f("cleanout required at base of stack", rect=[0, 0, 10, 10])], "digest_json")
    led.add([_f("backflow preventer size is wrong", rect=[1, 1, 10, 10])], "critique_1")
    led.seal()
    reconcile_post_anchor(led)                 # Pass B sees geometry — still keeps both
    assert len(led) == 2


def test_true_text_duplicate_different_tiles_merges():
    led = Ledger()
    led.add([_f("missing cleanout at the base of the soil stack", tile=[0, 0])], "digest_json")
    led.add([_f("missing cleanout at base of the soil stack riser", tile=[5, 5])], "critique_1")
    assert len(led) == 1                       # strong topical overlap, different tiles


def test_true_quote_duplicate_merges_and_unions_provenance():
    led = Ledger()
    led.add([_f("relief valve setting too high", quote="RV-3 SET 125 PSI")], "digest_json")
    led.add([_f("RV-3 pressure exceeds vessel MAWP", quote="RV-3 SET 125 PSI")], "critique_1")
    assert len(led) == 1
    e = led.entries[0]
    assert set(e.sources) == {"digest_json", "critique_1"}   # provenance unioned


# --------------------------------------------------------------------------- #
# §12.2 — coherent grounding (the K-factor / relief-valve mixed-finding trap)
# --------------------------------------------------------------------------- #


def test_merge_never_mixes_one_findings_text_with_anothers_quote():
    led = Ledger()
    # Same issue, strong overlap; one has a short quote, the other a long one.
    led.add([_f("VAV-3 has no clearance shown to the wall",
                quote="VAV-3", sev="low")], "digest_json")
    led.add([_f("VAV-3 has no clearance shown to the wall here",
                quote="VAV-3 SCHEDULE ROOM 120", sev="high")], "critique_1")
    assert len(led) == 1
    e = led.entries[0]
    # The representative's text and quote are from the SAME member (atomic bundle);
    # the loser's quote is preserved as support, never spliced onto the text.
    assert e.source_quote == "VAV-3 SCHEDULE ROOM 120"
    assert e.text == "VAV-3 has no clearance shown to the wall here"
    assert "VAV-3" in e.supporting_quotes
    assert e.severity == "high"


def test_ingest_order_independent_entries_and_numbers():
    def build():
        return [
            _f("relief valve setting too high", quote="RV-3 SET 125 PSI", rect=[10, 200, 60, 220]),
            _f("RV-3 pressure exceeds vessel MAWP", quote="RV-3 SET 125 PSI", rect=[12, 202, 62, 222]),
            _f("VAV-3 has no clearance to the wall", quote="VAV-3", rect=[10, 20, 60, 40]),
            _f("Unrelated pipe insulation note", quote="INSUL", rect=[300, 400, 360, 420]),
        ]

    def run(order):
        led = Ledger()
        items = build()
        for i in order:
            led.add([items[i]], "digest_json")
        led.seal()
        reconcile_post_anchor(led)
        led.number()
        return sorted((e.qc_id, e.id, e.text) for e in led.entries)

    a = run([0, 1, 2, 3])
    b = run([3, 2, 1, 0])
    c = run([2, 0, 3, 1])
    assert a == b == c                          # same entries AND same QC numbers


# --------------------------------------------------------------------------- #
# §12.4 — positional QC numbering, after anchoring
# --------------------------------------------------------------------------- #


def test_qc_numbers_follow_source_input_order_then_position():
    led = Ledger()
    # Two sources (SRC-0001 before SRC-0002 in input order) with anchored findings.
    led.add([_f("s2 lower", sid="SRC-0002", source="E-201.pdf", rect=[10, 300, 60, 320])], "digest_json")
    led.add([_f("s2 upper", sid="SRC-0002", source="E-201.pdf", rect=[10, 50, 60, 70])], "digest_json")
    led.add([_f("s1 lower", sid="SRC-0001", source="M-101.pdf", rect=[10, 300, 60, 320])], "digest_json")
    led.add([_f("s1 upper", sid="SRC-0001", source="M-101.pdf", rect=[10, 50, 60, 70])], "digest_json")
    led.seal()
    led.number()
    order = [e.text for e in sorted(led.entries, key=lambda f: f.qc_id)]
    # Source input order first (SRC-0001 before SRC-0002), then top-to-bottom.
    assert order == ["s1 upper", "s1 lower", "s2 upper", "s2 lower"]


def test_unanchored_sorts_after_anchored_on_same_sheet():
    led = Ledger()
    led.add([_f("anchored middle", rect=[10, 200, 60, 220])], "digest_json")
    led.add([_f("sheet-level absence", hint="SHEET")], "critique_1")   # no rect
    led.add([_f("anchored top", rect=[10, 40, 60, 60])], "digest_json")
    led.seal()
    led.number()
    order = [e.text for e in sorted(led.entries, key=lambda f: f.qc_id)]
    assert order == ["anchored top", "anchored middle", "sheet-level absence"]


# --------------------------------------------------------------------------- #
# §12 test 9 — cross-sheet conflicts with the same primary quote but different legs
# --------------------------------------------------------------------------- #


def test_cross_sheet_same_primary_quote_different_legs_stay_distinct():
    led = Ledger()
    led.add([_f("conflict A", quote="4 INCH MAIN",
                also_on=[ConflictLeg(sheet_id="E-201")])], "cross_qc")
    led.add([_f("conflict B", quote="4 INCH MAIN",
                also_on=[ConflictLeg(sheet_id="P-301")])], "cross_qc")
    assert len(led) == 2                        # same primary quote, different legs → distinct


def test_post_anchor_reconciliation_folds_a_geometric_duplicate():
    # Two entries the ingest pass could NOT merge — only *moderate* text overlap and
    # no geometry yet — become one once anchored to overlapping rects (Pass B, where
    # geometry is supporting evidence for the moderate text match). Mirrors the
    # pipeline: ingest unanchored → seal → anchor → reconcile.
    led = Ledger()
    led.add([_f("cleanout required at base of the soil stack per code", quote="CO-1")], "digest_json")
    led.add([_f("cleanout required at base of stack riser assembly detail", quote="CLEANOUT")], "critique_1")
    assert len(led) == 2                       # ingest can't merge (moderate text, no rects)
    led.seal()
    # Anchor both to heavily-overlapping rectangles (as resolve_anchors would).
    for e in led.entries:
        e.anchor = Anchor(status="EXACT", rect_pdf=[10, 20, 60, 42], method="t")
    folded = reconcile_post_anchor(led)
    assert folded == 1                         # geometry + moderate text → now one
    assert len(led) == 1
    e = led.entries[0]
    assert e.supporting_quotes                  # the loser's quote is preserved
