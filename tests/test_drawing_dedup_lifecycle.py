"""Phase 20 — lossless ledger reconciliation & the QC-ID lifecycle (§12).

Pure and hermetic: synthetic findings, no PyMuPDF, no network. Covers the §12
required behaviors — tile/geometry are never sufficient to merge, coherent
grounding, order-independent numbering, positional QC ids, cross-sheet leg
distinctness, and the OPEN→SEALED→NUMBERED lifecycle with post-anchor Pass B.
"""
from __future__ import annotations

from pathlib import Path

from drawing_analyzer.ledger import Ledger, _families, reconcile_post_anchor
from drawing_analyzer.models import (
    CONFIDENCE_REPRODUCED,
    CONFIDENCE_SINGLETON,
    Anchor,
    ConflictLeg,
    Finding,
    Verification,
)


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


def test_merge_action_rides_the_winning_bundle_and_backfills():
    led = Ledger()
    led.add([_f("VAV-3 has no clearance shown to the wall",
                quote="VAV-3", sev="low")], "digest_json")
    loser_action = "Confirm the clearance with the mechanical engineer."
    led.entries[0].recommended_action = loser_action
    winner = _f("VAV-3 has no clearance shown to the wall here",
                quote="VAV-3 SCHEDULE ROOM 120", sev="high")
    winner.recommended_action = "Verify the VAV-3 clearance and revise the plan."
    led.add([winner], "critique_1")
    assert len(led) == 1
    # The action belongs to the text it was written for — it moved with the bundle.
    assert led.entries[0].recommended_action == "Verify the VAV-3 clearance and revise the plan."

    # An empty winner backfills from the loser (an action for the same deduped
    # issue is still the action) — and differing actions never block a merge.
    led2 = Ledger()
    led2.add([_f("VAV-3 has no clearance shown to the wall",
                 quote="VAV-3", sev="low")], "digest_json")
    led2.entries[0].recommended_action = loser_action
    bare_winner = _f("VAV-3 has no clearance shown to the wall here",
                     quote="VAV-3 SCHEDULE ROOM 120", sev="high")
    led2.add([bare_winner], "critique_1")
    assert len(led2) == 1
    assert led2.entries[0].recommended_action == loser_action


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
    # C-2: a better-grounded member with a DIFFERENT quote must not inherit
    # another member's rectangle (which was resolved from that member's quote).
    # Both members here are model-authored, so provenance does not decide the
    # representative and the longer quote wins on its own merits.
    led = Ledger()
    short = _f("beam load 12 kips exceeds capacity", quote="12 KIPS", rect=[10, 10, 60, 24])
    led.add([short], "digest_json")
    led.add([_f("beam load 12 kips exceeds the allowable capacity",
                quote="BEAM B12 LOAD 12 KIPS PER SCHEDULE")], "critique_1")
    assert len(led) == 1
    e = led.entries[0]
    assert e.source_quote == "BEAM B12 LOAD 12 KIPS PER SCHEDULE"   # new representative
    # The rect resolved from "12 KIPS" is NOT grafted onto the different quote.
    assert e.anchor.rect_pdf is None


def test_a_deterministic_member_wins_the_representative_and_keeps_its_verdict():
    # §17.5 / "the model never calculates". A DETERMINISTIC finding's text states
    # the result of a HOST computation over its OWN quote. The auditor quotes only
    # the term it computed over, so on quote length alone it loses to a model
    # finding quoting the whole schedule line — and the model's arithmetic then
    # inherited the DETERMINISTIC label, skipped the crop check, and inked as
    # "an exact text check of the drawings, not an AI judgment".
    #
    # Provenance now ranks first in _grounding_quality, which is what the merge
    # site's own comment always claimed. The auditor wins the bundle, so its
    # text, its rect and its verdict travel together and remain true of each
    # other.
    led = Ledger()
    auditor = _f("the sum of the terms is 540", quote="TOTAL CFM 540",
                 rect=[10, 10, 60, 24])
    auditor.verification = Verification(status="DETERMINISTIC")
    # Same quote: this is the shape that actually merges (a differing quote AND a
    # differing measurement is a conflicting signature, which dedup refuses).
    model = _f("the sum of the terms is 560", quote="TOTAL CFM 540")
    led.add([auditor], "auditor_arithmetic")
    led.add([model], "critique_1")

    assert len(led) == 1
    e = led.entries[0]
    assert "540" in e.text and "560" not in e.text     # the host's number, not the model's
    assert e.source_quote == "TOTAL CFM 540"           # the quote it computed over
    assert e.anchor.rect_pdf == [10, 10, 60, 24]       # its exact rect is not destroyed
    assert e.verification.status == "DETERMINISTIC"    # true of the text it sits on
    assert set(e.sources) == {"auditor_arithmetic", "critique_1"}   # provenance unioned


def test_the_representative_does_not_depend_on_ingest_order():
    # The severity union ran BEFORE the quality comparison it feeds, raising
    # `existing.severity` to the max and erasing the very difference being
    # compared: one order saw ranks (3, 2) and the other (3, 3). The tiebreak
    # then fell to raw text, where "...560..." sorts above "...540...".
    #
    # Every fixture in the neighbouring order-independence test uses one
    # severity, so the union is a no-op there and the claim went uncovered.
    for a_sev, b_sev in (("high", "low"), ("low", "high"), ("medium", "high")):
        surviving = set()
        for order in (0, 1):
            led = Ledger()
            a = _f("chilled water pump flow is 540 gpm", quote="CWP-1 540 GPM", sev=a_sev)
            b = _f("chilled water pump flow is 560 gpm", quote="CWP-1 540 GPM", sev=b_sev)
            pair = [(a, "digest_json"), (b, "critique_1")]
            if order:
                pair.reverse()
            for finding, tag in pair:
                led.add([finding], tag)
            assert len(led) == 1
            surviving.add(led.entries[0].text)
        assert len(surviving) == 1, (a_sev, b_sev, surviving)


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


def test_an_unanchored_winner_does_not_erase_a_compatible_rect():
    # The bundle adopted the winner's anchor unconditionally, so an UNANCHORED
    # winner replaced an exact rect with an empty one — and the anchor upgrade
    # below could not restore it, because that only fires when the *incoming*
    # member is the anchored one. The same two findings therefore kept or
    # destroyed the rectangle depending purely on which arrived first.
    #
    # Keeping it is coherent only because the quotes match: the rect anchors the
    # very string the new representative quotes. A different quote must still
    # lose the rect (see the cross-grounding test above).
    led = Ledger()
    led.add([_f("relief valve RV-3 setting is too high",
                quote="RV-3 SET 125 PSI", sev="low", rect=[10, 200, 60, 220])], "digest_json")
    led.add([_f("relief valve RV-3 setting exceeds the vessel maximum",
                quote="RV-3 SET 125 PSI", sev="high")], "critique_1")

    assert len(led) == 1
    e = led.entries[0]
    assert e.text.endswith("exceeds the vessel maximum")   # the winner's text
    assert e.anchor.rect_pdf == [10, 200, 60, 220]         # the rect survived


def test_pass_b_keeps_a_conflict_carried_in_text_not_the_quote():
    # Pass B rebuilt its complete-link history from the LIVE survivor rather
    # than the ledger's ingest snapshots. When B won the representative, A's
    # text — which held the discriminating "500 gpm" — was overwritten, and only
    # A's *quote* rode into supporting_quotes. The measurement therefore vanished
    # from the object Pass B compared against, so Pass B folded a chain Pass A
    # had explicitly refused one call earlier, and C's "550 gpm" ended up
    # nowhere at all: not in the text, not in the quotes, only a provenance tag
    # pointing at content that no longer existed.
    #
    # The neighbouring chain test survives on quotes, which do ride into
    # supporting_quotes. Every arithmetic or quantity conflict carries its signal
    # in the text instead, which is the case that was uncovered.
    led = Ledger()
    led.add([_f("riser pump flow is 500 gpm per riser schedule",
                cat="coordination", quote="RISER")], "digest_json")
    led.add([_f("riser pump flow per riser schedule", cat="coordination",
                quote="RISER PUMP FLOW PER RISER SCHEDULE AND COORDINATION DETAILS")],
            "critique_1")
    led.add([_f("riser pump flow is 550 gpm per riser schedule",
                cat="coordination", quote="RISER")], "cross_qc")

    def has_550(ledger):
        return any(
            "550" in e.text or any("550" in q for q in e.supporting_quotes)
            for e in ledger.entries
        )

    assert len(led) == 2 and has_550(led)        # Pass A refused the fold
    led.seal()
    reconcile_post_anchor(led)
    assert len(led) == 2, [e.text for e in led.entries]
    assert has_550(led), "the conflicting measurement was destroyed"


# --------------------------------------------------------------------------- #
# §14.4 — ``confidence`` must agree with ``reproduced``
# --------------------------------------------------------------------------- #


def test_cross_family_corroboration_upgrades_confidence_not_only_reproduced():
    # ``confidence`` is only ever raised by rank, and every non-critique channel
    # carries "" (rank 0), which can never raise a critique's SINGLETON. The very
    # same merge unions a second *family* into ``sources`` and flips
    # ``reproduced`` to True — so the entry said "corroborated across families"
    # and "only one of the two reads saw it" at once. critique.merge_finding_groups
    # already settles this the coherent way; the ledger implemented half of it.
    led = Ledger()
    crit = _f("branch line exceeds the maximum allowed length",
              quote="MAX BRANCH LENGTH 150 FT")
    crit.confidence = CONFIDENCE_SINGLETON
    crit.sources = ["critique_1"]
    crit.reproduced = False                 # only one of the two critique reads saw it
    dig = _f("branch line exceeds the maximum length allowed",
             quote="MAX BRANCH LENGTH 150 FT")
    dig.reproduced = False                  # so only the family span can flip it
    led.add([crit])
    led.add([dig], "digest_json")

    (e,) = led.entries
    assert len(_families(e.sources)) >= 2
    assert e.reproduced is True
    assert e.confidence == CONFIDENCE_REPRODUCED


def test_a_same_family_merge_does_not_invent_corroboration():
    # Two reads of the SAME family are not two channels. A SINGLETON that only
    # ever met its own family keeps saying so — the upgrade is corroboration,
    # not a default.
    led = Ledger()
    first = _f("branch line exceeds the maximum allowed length",
               quote="MAX BRANCH LENGTH 150 FT")
    first.confidence = CONFIDENCE_SINGLETON
    first.sources = ["critique_1"]
    first.reproduced = False
    second = _f("branch line exceeds the maximum length allowed",
                quote="MAX BRANCH LENGTH 150 FT")
    second.confidence = CONFIDENCE_SINGLETON
    second.sources = ["critique_1"]
    second.reproduced = False
    led.add([first])
    led.add([second])

    (e,) = led.entries
    assert e.confidence == CONFIDENCE_SINGLETON
    assert e.reproduced is False


# --------------------------------------------------------------------------- #
# §12.3 — a post-seal duplicate is an invariant failure, not a silent rewrite
# --------------------------------------------------------------------------- #


def test_a_post_numbered_duplicate_is_counted_and_never_rewrites_the_entry():
    # ``add`` merged and returned BEFORE the sealed guard, so the guard was
    # reachable only for a *fresh* finding. A duplicate arriving after numbering
    # therefore rewrote text, quote, content id, severity and sources underneath
    # a QC-### that is already exported, already inked on a reviewed PDF, and
    # already the name of an evidence directory — while leaving post_seal_adds
    # at 0, so the roll-up never reported the run incomplete.
    led = Ledger()
    led.add([_f("sprinkler spacing conflict on the main run",
                quote="SPACING 12 FT", rect=[10, 10, 60, 24])], "digest_json")
    led.seal()
    (numbered,) = led.number()
    before = (numbered.qc_id, numbered.id, numbered.text, numbered.source_quote,
              numbered.severity, list(numbered.sources), list(numbered.supporting_quotes))

    led.add([_f("sprinkler spacing conflict on the main run line",
                quote="SPACING 12 FT MAXIMUM PER PLAN", sev="high")], "critique_1")

    (after,) = led.entries
    assert after is numbered
    assert (after.qc_id, after.id, after.text, after.source_quote, after.severity,
            list(after.sources), list(after.supporting_quotes)) == before
    assert led.post_seal_adds == 1          # the run is marked incomplete instead


def test_a_post_seal_duplicate_is_counted_before_numbering_too():
    led = Ledger()
    led.add([_f("relief valve RV-3 setting is too high", quote="RV-3 SET 125 PSI")],
            "digest_json")
    led.seal()
    led.add([_f("relief valve RV-3 setting exceeds the maximum", quote="RV-3 SET 125 PSI")],
            "critique_1")
    assert len(led) == 1                    # not appended as a second entry either
    assert led.post_seal_adds == 1
    assert led.entries[0].sources == ["digest_json"]     # unmutated


# --------------------------------------------------------------------------- #
# §12.1 — the complete-link history freezes at the merge, not at ingest
# --------------------------------------------------------------------------- #


def test_a_second_merge_cannot_capture_the_first_merges_result_as_history():
    # An entry is its own first member and is held LIVE until a merge is about to
    # mutate it. Freezing that head is a ONE-TIME act: re-taking it on the second
    # merge would record the survivor as it is *after* the first — carrying the
    # winner's bundle — and erase the original member's signature from the very
    # history complete-link is evaluated against. It takes three merges to see:
    # on the first merge the live survivor and its snapshot are still identical.
    long_quote = "RISER PUMP FLOW PER RISER SCHEDULE AND COORDINATION DETAILS"
    led = Ledger()
    led.add([_f("riser pump flow is 500 gpm per riser schedule",
                cat="coordination", quote="RISER")], "digest_json")
    led.add([_f("riser pump flow per riser schedule", cat="coordination",
                quote=long_quote)], "critique_1")
    assert len(led) == 1                        # B won the bundle (longer quote)
    assert "500" not in led.entries[0].text     # ...so A's measurement left the text

    led.add([_f("riser pump flow per riser schedule", cat="coordination",
                quote=long_quote)], "critique_2")
    assert len(led) == 1                        # a second merge into the same entry

    led.add([_f("riser pump flow is 550 gpm per riser schedule",
                cat="coordination", quote="RISER")], "cross_qc")
    assert len(led) == 2, [e.text for e in led.entries]   # A's snapshot still refuses
