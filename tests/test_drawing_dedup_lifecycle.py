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
    led.add([_f("relief valve RV-3 setting is too high", quote="RV-3 SET 125 PSI")], "digest_json")
    led.add([_f("relief valve RV-3 setting exceeds maximum", quote="RV-3 SET 125 PSI")], "critique_1")
    assert len(led) == 1                          # same quote + moderate text
    e = led.entries[0]
    assert set(e.sources) == {"digest_json", "critique_1"}   # provenance unioned


def test_same_quote_unrelated_text_stays_two_entries():
    # Two DIFFERENT issues about one component both quote its tag verbatim; the
    # quote alone must not merge them (§12.1, DA-005 no-data-loss).
    led = Ledger()
    led.add([_f("pump P-1 voltage listed as 480 should be 208", quote="PUMP P-1")], "digest_json")
    led.add([_f("pump P-1 impeller diameter conflicts with the curve", quote="PUMP P-1")], "critique_1")
    assert len(led) == 2


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


def test_complete_link_ingest_survives_representative_switch():
    # Complete-link regression (Codex P1): A folds into a higher-quality B; a later
    # C that duplicates B but CONFLICTS with A must NOT fold — the member history
    # keeps A's original signature even though B mutated the survivor object.
    led = Ledger()
    led.add([_f("clearance issue at VAV-3 near the wall", quote="VAV-3")], "digest_json")
    # B: same issue, longer quote → wins the representative and mutates the survivor.
    led.add([_f("clearance issue at VAV-3 near the wall here",
                quote="VAV-3 SUPPLY DIFFUSER SCHEDULE")], "critique_1")
    assert len(led) == 1
    # C: overlaps B's text but is about VAV-4 → conflicts with the folded A (VAV-3).
    led.add([_f("clearance issue at VAV-4 near the wall", quote="VAV-4")], "cross_qc")
    assert len(led) == 2                         # C kept distinct, not wrongly folded


def test_pass_b_complete_link_does_not_collapse_a_conflicting_chain():
    # Reviewer #1: Pass B must be complete-link too. A signature-less bridge that is
    # the highest-quality survivor must not fold two findings that conflict with each
    # other (M-101 vs M-102) just because each duplicates the bridge.
    led = Ledger()
    led.add([_f("coordinate riser with M-101 diagram", quote="M-101")], "digest_json")
    led.add([_f("coordinate riser with M-102 diagram", quote="M-102")], "digest_json")
    # The bridge: longest quote (→ highest quality → sorts first as survivor),
    # overlaps both on text, carries no conflicting tag of its own.
    led.add([_f("coordinate riser routing per the schedule and details",
                quote="RISER COORDINATION SCHEDULE AND DETAILS")], "critique_1")
    assert len(led) == 3
    led.seal()
    for e in led.entries:                        # anchor all three to the same cell
        e.anchor = Anchor(status="EXACT", rect_pdf=[10, 20, 200, 40], method="t")
    reconcile_post_anchor(led)
    # The two conflicting refs stay separate; only true duplicates could fold.
    assert len(led) >= 2
    tags = {e.source_quote for e in led.entries}
    assert "M-101" in tags and "M-102" in tags   # neither M-ref was swallowed


def test_merge_does_not_cross_ground_anchor_from_a_different_quote():
    # C-2: a better-grounded member with a DIFFERENT quote must not inherit an
    # auditor's rectangle (which was resolved from the auditor's quote).
    led = Ledger()
    auditor = _f("beam load 12 kips exceeds capacity", quote="12 KIPS", rect=[10, 10, 60, 24])
    auditor.verification = Verification(status="DETERMINISTIC")
    led.add([auditor])
    # A model duplicate with a LONGER but DIFFERENT quote wins the representative.
    led.add([_f("beam load 12 kips exceeds the allowable capacity",
                quote="BEAM B12 LOAD 12 KIPS PER SCHEDULE")], "critique_1")
    assert len(led) == 1
    e = led.entries[0]
    assert e.source_quote == "BEAM B12 LOAD 12 KIPS PER SCHEDULE"   # new representative
    # The auditor's rect (from "12 KIPS") is NOT grafted onto the different quote.
    assert e.anchor.rect_pdf is None
    assert e.verification.status == "DETERMINISTIC"                 # verdict still survives


def test_post_anchor_reconciliation_folds_a_geometric_duplicate():
    # Two entries the ingest pass could NOT merge — same verbatim quote but text too
    # different to merge on text, and no geometry yet — become one once anchored to
    # overlapping rects (Pass B: same quote + rect overlap). Mirrors the pipeline:
    # ingest unanchored → seal → anchor → reconcile.
    led = Ledger()
    led.add([_f("cleanout required at base of the soil stack per code", quote="CO-1")], "digest_json")
    led.add([_f("provide a cleanout fitting shown on the plumbing detail", quote="CO-1")], "critique_1")
    assert len(led) == 2                       # ingest can't merge (weak text, no rects)
    led.seal()
    # Anchor both to heavily-overlapping rectangles (as resolve_anchors would).
    for e in led.entries:
        e.anchor = Anchor(status="EXACT", rect_pdf=[10, 20, 60, 42], method="t")
    folded = reconcile_post_anchor(led)
    assert folded == 1                         # same quote + rect overlap → now one
    assert len(led) == 1
