"""Finding-level A/B comparison (WP-06 §11.2/§11.3).

Every case here exists because an aggregate table cannot see it. Two arms with
identical totals, identical severity mixes and identical anchor tiers can share
none of their findings; an arm that failed halfway can look like the cheap one.
The tests are written against the exact traps §11.5 enumerates, so each one
names the wrong answer it is there to reject.

Hermetic (I-4): pure data, real ``Finding`` objects, no client, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ab_findings_diff import (  # noqa: E402
    COMPARISON_COMPLETE,
    COMPARISON_INCOMPLETE,
    RECORD_CONTRACT_VERSION,
    RECORDS_MISSING,
    RECORDS_PRESENT,
    copy_linked_artifacts,
    evidence_trust_composition,
    finding_record,
    finding_records,
    match_records,
    render_findings_diff,
)
from drawing_analyzer.models import (  # noqa: E402
    Anchor,
    ConflictLeg,
    EvidenceArtifact,
    Finding,
    Verification,
)


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #

def _f(**kw) -> Finding:
    base = dict(
        sheet_id="M-101", source_name="mech.pdf", source_id="SRC-0001",
        page_index=0, category="coordination", severity="medium",
        text="ceiling clearance conflicts with the duct run",
        source_quote="DUCT SCHEDULE",
    )
    base.update(kw)
    return Finding(**base)


# Each sheet id on its own page of arch.pdf (remediation WP-06.2: a leg is its
# page, so two ids on one page would be one leg target, as they are one sheet).
_LEG_PAGES = {"M-201": 1, "M-301": 2}


def _leg(sheet_id: str, quote: str = "SEE MECH") -> ConflictLeg:
    return ConflictLeg(sheet_id=sheet_id, source_name="arch.pdf",
                       source_id="SRC-0002", page_index=_LEG_PAGES.get(sheet_id, 1),
                       source_quote=quote)


def _rect(x0=10.0, y0=10.0, x1=110.0, y1=60.0) -> Anchor:
    return Anchor(status="EXACT", rect_pdf=[x0, y0, x1, y1], method="exact")


# --------------------------------------------------------------------------- #
# §11.5 — "Same finding after positional renumbering is comparable"
# --------------------------------------------------------------------------- #

def test_positional_renumbering_does_not_change_a_finding_identity():
    """Dropping one finding renumbers every finding below it.

    ``QC-###`` is assigned positionally after anchoring, so an arm that found
    one fewer issue reports *different* QC ids for every surviving finding after
    it. Matching on that number would report 2 of 3 findings as "changed" when
    nothing about them changed at all.
    """
    a = _f(text="issue A", source_quote="QUOTE A", qc_id="QC-001")
    b = _f(text="issue B", source_quote="QUOTE B", qc_id="QC-002")
    c = _f(text="issue C", source_quote="QUOTE C", qc_id="QC-003")
    # The variant lost B, so C is renumbered QC-002.
    c2 = _f(text="issue C", source_quote="QUOTE C", qc_id="QC-002")
    a2 = _f(text="issue A", source_quote="QUOTE A", qc_id="QC-001")

    m = match_records(finding_records([a, b, c]), finding_records([a2, c2]))

    assert m["counts"]["exact"] == 2
    assert m["counts"]["unmatched_base"] == 1
    assert m["unmatched_base"][0]["source_quote"] == "QUOTE B"
    assert m["counts"]["unmatched_variant"] == 0
    # The renumbered finding matched, and its changed qc_id is carried as a
    # reference on both sides rather than as a difference.
    matched = [x for x in m["exact"] if x["base"]["source_quote"] == "QUOTE C"][0]
    assert matched["base"]["qc_id"] == "QC-003"
    assert matched["variant"]["qc_id"] == "QC-002"
    assert matched["attribute_deltas"] == {}


# --------------------------------------------------------------------------- #
# §11.5 — "identical primary quote with different secondary legs is not collapsed"
# --------------------------------------------------------------------------- #

def test_finding_id_collides_on_different_legs_but_identity_does_not():
    """The documented ``compute_finding_id`` gap, proved rather than assumed.

    ``compute_finding_id`` hashes sheet id, category, quote-or-text and source
    id. Legs are not in it. Two cross-sheet conflicts that quote the same primary
    text but point at *different* second sheets therefore share one
    ``Finding.id`` — which is why this comparison must not use it alone.
    """
    to_201 = _f(also_on=[_leg("M-201")])
    to_301 = _f(also_on=[_leg("M-301")])
    assert to_201.id == to_301.id, "the collision this test exists for is gone"

    r201, r301 = finding_record(to_201), finding_record(to_301)
    assert r201["identity_key"] != r301["identity_key"]

    m = match_records([r201], [r301])
    assert m["counts"]["exact"] == 0
    assert m["counts"]["unmatched_base"] == 0      # they are candidates, not lost
    assert m["counts"]["candidates"] == 1
    reasons = " ".join(m["candidates"][0]["reasons"])
    assert "different cross-sheet legs" in reasons
    assert "cross_sheet_legs" in m["candidates"][0]["signature_conflicts"]


def test_same_legs_and_quote_is_an_exact_match():
    m = match_records(finding_records([_f(also_on=[_leg("M-201")])]),
                      finding_records([_f(also_on=[_leg("M-201")])]))
    assert m["counts"]["exact"] == 1
    assert m["counts"]["candidates"] == 0


# --------------------------------------------------------------------------- #
# §11.5 — "Changed quantities/tags/polarity cannot become an exact match
#          merely because geometry overlaps"
# --------------------------------------------------------------------------- #

def _overlapping_pair(base_text: str, var_text: str) -> dict:
    base = _f(text=base_text, anchor=_rect())
    var = _f(text=var_text, anchor=_rect(12.0, 12.0, 112.0, 62.0))  # ~IoU 0.9
    return match_records(finding_records([base]), finding_records([var]))


def test_changed_quantity_is_never_an_exact_match():
    m = _overlapping_pair("provide 6 in clearance", "provide 8 in clearance")
    assert m["counts"]["exact"] == 0
    assert m["counts"]["candidates"] == 1
    assert "measurements" in m["candidates"][0]["signature_conflicts"]


def test_changed_equipment_tag_is_never_an_exact_match():
    m = _overlapping_pair("duct conflicts with M-101 routing",
                          "duct conflicts with M-201 routing")
    assert m["counts"]["exact"] == 0
    assert "tags" in m["candidates"][0]["signature_conflicts"]


def test_flipped_absence_polarity_is_never_an_exact_match():
    """"not shown" and "shown" are opposite claims about the same words."""
    m = _overlapping_pair("duct size is not shown on the schedule",
                          "duct size is shown on the schedule")
    assert m["counts"]["exact"] == 0
    assert "absence_polarity" in m["candidates"][0]["signature_conflicts"]


def test_pure_rewording_matches_but_is_flagged_as_reworded():
    """Same grounded quote, no critical attribute moved: the same finding.

    Reported as exact — but a reviewer is still told the description changed,
    because "the same finding, described differently" and "the same finding"
    are different things to a person reading a diff.
    """
    m = match_records(
        finding_records([_f(text="ceiling clearance conflicts with the duct")]),
        finding_records([_f(text="the duct run conflicts with ceiling clearance")]),
    )
    assert m["counts"]["exact"] == 1
    assert m["exact"][0]["text_changed"] is True
    assert m["exact"][0]["attribute_deltas"] == {}


def test_geometry_overlap_alone_never_produces_an_exact_match():
    """Two unrelated findings sharing a rectangle are a candidate at most."""
    base = _f(text="missing fire damper", source_quote="", anchor=_rect())
    var = _f(text="incorrect sprinkler spacing", source_quote="",
             anchor=_rect(11.0, 11.0, 111.0, 61.0))
    m = match_records(finding_records([base]), finding_records([var]))
    assert m["counts"]["exact"] == 0
    assert m["counts"]["candidates"] == 1
    assert "IoU" in " ".join(m["candidates"][0]["reasons"])


# --------------------------------------------------------------------------- #
# Remediation WP-04.1 — the tokenizer behind the stored signatures
# --------------------------------------------------------------------------- #

def test_a_changed_hyphenated_quantity_is_never_an_exact_match():
    """B2: "6-inch" and "4-inch" carried no measurement at all, so the pair
    matched EXACT on the shared quote: a changed pipe size reported as the same
    finding."""
    m = _overlapping_pair("provide 6-inch drain at the riser",
                          "provide 4-inch drain at the riser")
    assert m["counts"]["exact"] == 0
    assert "measurements" in m["candidates"][0]["signature_conflicts"]


def test_a_changed_temperature_scale_is_never_an_exact_match():
    """B12: "90 deg F" and "90 deg C" both signed as ``90deg``."""
    m = _overlapping_pair("supply air setpoint is 90 deg F",
                          "supply air setpoint is 90 deg C")
    assert m["counts"]["exact"] == 0
    assert "measurements" in m["candidates"][0]["signature_conflicts"]


def test_thousands_grouped_quantities_compare_by_value():
    """B3: "12,500" signed as its trailing "500", so 12,500 and 1,500 cfm
    matched exact while 12,500 and 12500 cfm, one quantity, did not."""
    changed = _overlapping_pair("supply air is 12,500 cfm", "supply air is 1,500 cfm")
    assert changed["counts"]["exact"] == 0
    assert "measurements" in changed["candidates"][0]["signature_conflicts"]

    same = _overlapping_pair("supply air is 12,500 cfm", "supply air is 12500 cfm")
    assert same["counts"]["exact"] == 1
    assert same["exact"][0]["text_changed"] is True


def test_records_are_written_under_the_wp_06_2_contract():
    """A record stores ``critical_signature`` computed when the arm ran, so a v2
    record holds the old tokens (``6-inch`` signed as nothing, ``12,500`` as
    ``500``), a v3 record holds no quantity roles (remediation WP-04.3), which
    the rule reads as "no role", so a swapped main and branch would match
    EXACT, and a v4 record holds the partial readings (``4 to 6 in`` as
    ``6in``) and no feet-inches pairs (remediation WP-04.4), so a bare ``12'``
    against ``12'-6"`` would match EXACT. Comparing any of them with a v5 arm
    would report a code change as a model difference; ``load_arm_records``
    refuses it (``tests/test_ab_sweep.py``). Re-pinned 3 -> 4 by WP-04.3 and
    4 -> 5 by WP-04.4 (the owner's decisions). A v5 record names each leg by its
    sheet id, where a v6 record names its page (remediation WP-06.2), so an
    unchanged cross-sheet conflict would read as one with different legs:
    re-pinned 5 -> 6 (the owner's decision)."""
    assert RECORD_CONTRACT_VERSION == 6
    record = finding_record(_f(text="provide 6-inch drain at 12,500 cfm"))
    assert record["critical_signature"]["measurements"] == ["12500cfm", "6in"]
    record = finding_record(_f(text="provide 6 in main and 4 in branch"))
    assert record["critical_signature"]["roles"] == ["branch=4in", "main=6in"]
    assert record["critical_signature"]["ambiguous_roles"] == []
    record = finding_record(_f(text="maintain 4 to 6 in clear, 12'-6\" headroom"))
    assert record["critical_signature"]["measurements"] == ["12ft", "4..6in", "6in"]
    assert record["critical_signature"]["feet_inches"] == ["12ft6in"]
    record = finding_record(_f(also_on=[_leg("M-301")]))
    assert record["critical_signature"]["leg_targets"] == ["SRC-0002#p2"]


# --------------------------------------------------------------------------- #
# Remediation WP-04.2 — the compatibility rule, applied to stored signatures
# --------------------------------------------------------------------------- #

def test_a_conflict_beside_a_shared_value_is_never_an_exact_match():
    """N1: one shared value made two signatures compatible, so a pipe size that
    changed beside an unchanged pressure matched EXACT."""
    for base_text, var_text in (
        ("pump discharge is 6 in at 100 psi", "pump discharge is 4 in at 100 psi"),
        ("maintain 12'-6\" clear headroom", "maintain 12'-8\" clear headroom"),
    ):
        m = _overlapping_pair(base_text, var_text)
        assert m["counts"]["exact"] == 0, base_text
        assert m["candidates"][0]["signature_conflicts"] == ["measurements"]


def test_a_second_tag_that_changed_is_never_an_exact_match():
    """N1, tags: the shared P-1 excused the changed valve."""
    m = _overlapping_pair("duct conflicts with P-1 and V-3 routing",
                          "duct conflicts with P-1 and V-4 routing")
    assert m["counts"]["exact"] == 0
    assert m["candidates"][0]["signature_conflicts"] == ["tags"]


def test_a_reference_one_arm_adds_is_still_an_exact_match():
    """The other direction: an arm that names one more reference, or states one
    more quantity, found the same finding."""
    for base_text, var_text in (
        ("duct conflicts with P-1 routing", "duct conflicts with P-1 routing per M-501"),
        ("pump flow is 500 gpm", "pump flow is 500 gpm at 100 psi"),
    ):
        m = _overlapping_pair(base_text, var_text)
        assert m["counts"]["exact"] == 1, base_text
        assert m["exact"][0]["text_changed"] is True


def test_the_named_axes_come_from_the_production_rule():
    """Plan WP-04 step 6: one copy of the rule. The harness used to restate the
    disjoint-set test to name the axes, and that copy would have named nothing
    for a pair the new verdict refuses: a candidate with an empty reason."""
    import ab_findings_diff
    from drawing_analyzer.critique import signature_conflicts

    assert not hasattr(ab_findings_diff, "_signature_conflicts")
    for base_text, var_text in (
        ("pump discharge is 6 in at 100 psi", "pump discharge is 4 in at 100 psi"),
        ("duct conflicts with P-1 and V-3 routing", "duct conflicts with P-1 and V-4 routing"),
        ("duct size is not shown on the schedule", "duct size is shown on the schedule"),
    ):
        base = finding_records([_f(text=base_text, anchor=_rect())])
        var = finding_records([_f(text=var_text, anchor=_rect(12.0, 12.0, 112.0, 62.0))])
        (cand,) = match_records(base, var)["candidates"]
        assert cand["signature_conflicts"] == signature_conflicts(
            base[0]["critical_signature"], var[0]["critical_signature"])
        assert cand["signature_conflicts"]


def test_a_v6_record_is_compared_under_the_current_rule_without_a_bump():
    """A record stores the signature's tokens, and the rule is re-applied when
    two records are compared. WP-04.2 changed the rule, not the tokens, so a
    record read back from disk still means what it says: no
    ``RECORD_CONTRACT_VERSION`` bump for a rule-only change (see the version's
    comment). Renamed from the v3 test by WP-04.3, whose bump was for what a
    record stores (the roles), from the v4 test by WP-04.4, whose bump was for
    the tokens and the feet-inches pairs a record stores, and from the v5 test
    by WP-06.2, whose bump was for the leg targets a record stores."""
    assert RECORD_CONTRACT_VERSION == 6
    base = finding_records([_f(text="pump discharge is 6 in at 100 psi", anchor=_rect())])
    var = finding_records([_f(text="pump discharge is 4 in at 100 psi",
                              anchor=_rect(12.0, 12.0, 112.0, 62.0))])
    sidecar = json.loads(json.dumps(
        {"contract_version": RECORD_CONTRACT_VERSION, "records": base}))
    m = match_records(sidecar["records"], var)
    assert m["counts"]["exact"] == 0
    assert m["candidates"][0]["signature_conflicts"] == ["measurements"]


# --------------------------------------------------------------------------- #
# Remediation WP-04.3 — quantity roles, stored in the record
# --------------------------------------------------------------------------- #

def test_swapped_roles_are_never_an_exact_match():
    """The two arms name the same sizes for opposite roles. The token sets are
    equal, so before WP-04.3 this matched EXACT."""
    for base_text, var_text in (
        ("provide 6 in main and 4 in branch at the riser",
         "provide 4 in main and 6 in branch at the riser"),
        ("provide 6 in supply and 6 in return at the riser",
         "provide 6 in supply and 8 in return at the riser"),
    ):
        m = _overlapping_pair(base_text, var_text)
        assert m["counts"]["exact"] == 0, base_text
        assert m["candidates"][0]["signature_conflicts"] == ["measurements"]


def test_the_roles_are_compared_from_the_stored_record():
    """The rule reads the roles a record stored when its arm ran, read back
    from JSON, never recomputed from the record's text."""
    base = finding_records([_f(text="provide 6 in main and 4 in branch", anchor=_rect())])
    var = finding_records([_f(text="provide 4 in main and 6 in branch",
                              anchor=_rect(12.0, 12.0, 112.0, 62.0))])
    stored = json.loads(json.dumps({"contract_version": RECORD_CONTRACT_VERSION, "records": base}))
    m = match_records(stored["records"], var)
    assert m["counts"]["exact"] == 0
    assert m["candidates"][0]["signature_conflicts"] == ["measurements"]
    # The same records with the roles removed (what a v3 arm stored) would
    # have matched EXACT, which is why a v3 sidecar is refused.
    for record in stored["records"] + var:
        record["critical_signature"].pop("roles", None)
        record["critical_signature"].pop("ambiguous_roles", None)
    assert match_records(stored["records"], var)["counts"]["exact"] == 1


def test_a_v3_sidecar_is_refused(tmp_path):
    from ab_findings_diff import RECORDS_STALE_CONTRACT
    from ab_sweep_drawing_analyzer import _findings_path, load_arm_records

    arm = tmp_path / "arm_baseline.json"
    records = finding_records([_f(text="provide 6 in main and 4 in branch")])
    for record in records:           # what a v3 arm stored: no roles
        record["critical_signature"].pop("roles", None)
        record["critical_signature"].pop("ambiguous_roles", None)
    _findings_path(arm).write_text(
        json.dumps({"contract_version": 3, "records": records}), encoding="utf-8")
    assert load_arm_records(arm) == (RECORDS_STALE_CONTRACT, [])


# --------------------------------------------------------------------------- #
# Remediation WP-04.4 — the tokenizer residuals, stored in the record
# --------------------------------------------------------------------------- #

_RESIDUAL_PAIRS = {
    "a bare feet value": ("maintain 12'-6\" clear headroom at the riser",
                          "maintain 12' clear headroom at the riser"),
    "a to range": ("maintain 4 to 6 in clearance at the pump",
                   "maintain 6 in clearance at the pump"),
    "a loose-comma list": ("provide 2, 4, 6 in floor drains at the east wall",
                           "provide 3, 5, 6 in floor drains at the east wall"),
    "a compact A beside a voltage": ("provide 20A 120V circuit for fan EF-1",
                                     "provide 30A 120V circuit for fan EF-1"),
}


@pytest.mark.parametrize("pair", sorted(_RESIDUAL_PAIRS), ids=sorted(_RESIDUAL_PAIRS))
def test_a_changed_residual_quantity_is_never_an_exact_match(pair):
    """Each side signed only part of its quantity (or, for feet, nothing that
    told a bare ``12'`` from ``12'-6"``), and the parts agreed, so before
    WP-04.4 each pair matched EXACT."""
    m = _overlapping_pair(*_RESIDUAL_PAIRS[pair])
    assert m["counts"]["exact"] == 0
    assert m["candidates"][0]["signature_conflicts"] == ["measurements"]


def test_the_feet_inches_pairs_are_compared_from_the_stored_record():
    """The rule reads the pairs a record stored when its arm ran, read back
    from JSON, never recomputed from the record's text."""
    base = finding_records([_f(text="maintain 12'-6\" clear headroom", anchor=_rect())])
    var = finding_records([_f(text="maintain 12' clear headroom",
                              anchor=_rect(12.0, 12.0, 112.0, 62.0))])
    stored = json.loads(json.dumps({"contract_version": RECORD_CONTRACT_VERSION, "records": base}))
    m = match_records(stored["records"], var)
    assert m["counts"]["exact"] == 0
    assert m["candidates"][0]["signature_conflicts"] == ["measurements"]
    # The same records without the pairs (what a v4 arm stored) would have
    # matched EXACT, which is why a v4 sidecar is refused.
    for record in stored["records"] + var:
        record["critical_signature"].pop("feet_inches", None)
    assert match_records(stored["records"], var)["counts"]["exact"] == 1


def test_a_v4_sidecar_is_refused(tmp_path):
    from ab_findings_diff import RECORDS_STALE_CONTRACT
    from ab_sweep_drawing_analyzer import _findings_path, load_arm_records

    arm = tmp_path / "arm_baseline.json"
    records = finding_records([_f(text="maintain 12' clear headroom")])
    for record in records:           # what a v4 arm stored: no feet-inches pairs
        record["critical_signature"].pop("feet_inches", None)
    _findings_path(arm).write_text(
        json.dumps({"contract_version": 4, "records": records}), encoding="utf-8")
    assert load_arm_records(arm) == (RECORDS_STALE_CONTRACT, [])


# --------------------------------------------------------------------------- #
# Remediation WP-06.2 — a leg target is a page, stored in the record
# --------------------------------------------------------------------------- #

def _to_m201_on(source_id: str) -> Finding:
    return _f(also_on=[ConflictLeg(sheet_id="M-201", source_name="arch.pdf",
                                   source_id=source_id, page_index=0,
                                   source_quote="SEE MECH")])


def test_two_pdfs_that_carry_one_id_are_two_leg_targets():
    """N6: legs to two PDFs that both carry M-201 were one target (the id), so an
    arm that moved a conflict's leg to the other PDF matched EXACT."""
    base = finding_records([_to_m201_on("SRC-0002")])
    var = finding_records([_to_m201_on("SRC-0003")])
    m = match_records(base, var)
    assert m["counts"]["exact"] == 0
    assert m["candidates"][0]["signature_conflicts"] == ["cross_sheet_legs"]
    # The same records with the targets a v5 arm stored (the sheet id) would
    # have matched EXACT, which is why a v5 sidecar is refused.
    for record in base + var:
        record["critical_signature"]["leg_targets"] = ["M-201"]
    assert match_records(base, var)["counts"]["exact"] == 1


def test_a_v5_sidecar_is_refused(tmp_path):
    from ab_findings_diff import RECORDS_STALE_CONTRACT
    from ab_sweep_drawing_analyzer import _findings_path, load_arm_records

    arm = tmp_path / "arm_baseline.json"
    records = finding_records([_to_m201_on("SRC-0002")])
    for record in records:           # what a v5 arm stored: the leg's sheet id
        record["critical_signature"]["leg_targets"] = ["M-201"]
    _findings_path(arm).write_text(
        json.dumps({"contract_version": 5, "records": records}), encoding="utf-8")
    assert load_arm_records(arm) == (RECORDS_STALE_CONTRACT, [])


# --------------------------------------------------------------------------- #
# §11.5 — "Identical count/mix with one baseline finding replaced still exposes
#          the unmatched records"
# --------------------------------------------------------------------------- #

def test_equal_totals_with_a_swapped_finding_expose_both_unmatched_records():
    """The case every aggregate table in the harness reads as "no change".

    Same count, same severity mix, same anchor tiers, same verification mix —
    and one real issue traded for a different one.
    """
    keep = [_f(text=f"issue {i}", source_quote=f"QUOTE {i}") for i in range(4)]
    dropped = _f(text="missing standpipe hose valve", source_quote="STANDPIPE")
    added = _f(text="duct penetration lacks a damper", source_quote="PENETRATION")

    m = match_records(finding_records(keep + [dropped]),
                      finding_records(keep + [added]))

    assert m["counts"]["base_total"] == m["counts"]["variant_total"] == 5
    assert m["counts"]["exact"] == 4
    assert [r["source_quote"] for r in m["unmatched_base"]] == ["STANDPIPE"]
    assert [r["source_quote"] for r in m["unmatched_variant"]] == ["PENETRATION"]
    assert m["counts"]["reconciles"] is True


# --------------------------------------------------------------------------- #
# §11.5 — "Ambiguous candidate matches remain explicitly unresolved"
# --------------------------------------------------------------------------- #

def test_many_to_many_candidates_stay_unresolved():
    """Two plausible pairings each way: picking one would launder a guess.

    The same failure ``cross_qc.fact_tile_lookup`` exists to avoid — a collision
    must lose, not pick. All four records are reported, none is matched, and
    none is silently dropped.
    """
    base = [_f(text="issue one", source_quote="", anchor=_rect()),
            _f(text="issue two", source_quote="",
               anchor=_rect(11.0, 11.0, 111.0, 61.0))]
    var = [_f(text="issue three", source_quote="",
              anchor=_rect(12.0, 12.0, 112.0, 62.0)),
           _f(text="issue four", source_quote="",
              anchor=_rect(13.0, 13.0, 113.0, 63.0))]

    m = match_records(finding_records(base), finding_records(var))

    assert m["counts"]["exact"] == 0
    assert m["counts"]["candidates"] == 0
    assert m["counts"]["ambiguous_groups"] == 1
    assert m["ambiguous"][0]["kind"] == "MANY_TO_MANY"
    assert len(m["ambiguous"][0]["base"]) == 2
    assert len(m["ambiguous"][0]["variant"]) == 2
    assert m["counts"]["reconciles"] is True


def test_duplicate_identity_within_an_arm_is_never_paired_arbitrarily():
    """One identity, two records in an arm: the pairing would be a coin flip."""
    dup = _f(text="issue", source_quote="QUOTE")
    m = match_records(finding_records([dup, dup]), finding_records([dup]))
    assert m["counts"]["exact"] == 0
    assert m["ambiguous"][0]["kind"] == "IDENTITY_COLLISION"
    assert m["counts"]["duplicate_identity_base"] == 1
    assert m["counts"]["reconciles"] is True


# --------------------------------------------------------------------------- #
# Disposition changes on an otherwise-identical finding
# --------------------------------------------------------------------------- #

def test_matched_finding_reports_its_changed_disposition():
    """The same finding, verified in one arm and rejected in the other.

    Aggregates show this as "one more REJECTED"; only the pairing says *which*
    finding, which is what a reviewer needs to judge whether the change matters.
    """
    base = _f(anchor=_rect(), verification=Verification(status="VERIFIED"),
              severity="high", confidence="REPRODUCED")
    var = _f(anchor=Anchor(status="TILE", rect_pdf=[0, 0, 50, 50], method="tile"),
             verification=Verification(status="UNCERTAIN"),
             severity="low", confidence="SINGLETON",
             evidence_state="TEXT_EVIDENCE_UNAVAILABLE")
    m = match_records(finding_records([base]), finding_records([var]))
    deltas = m["exact"][0]["attribute_deltas"]
    assert deltas["severity"] == {"base": "high", "variant": "low"}
    assert deltas["verification_status"] == {"base": "VERIFIED", "variant": "UNCERTAIN"}
    assert deltas["anchor_status"] == {"base": "EXACT", "variant": "TILE"}
    assert deltas["confidence"] == {"base": "REPRODUCED", "variant": "SINGLETON"}
    assert deltas["evidence_state"]["variant"] == "TEXT_EVIDENCE_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Evidence-trust composition (§11.3)
# --------------------------------------------------------------------------- #

def test_evidence_trust_counts_legs_separately_from_their_finding():
    """A conflict can be grounded on one sheet and unavailable on the other.

    Folding a conflict into a single state would report exactly one of those two
    facts and silently discard the other.
    """
    f = _f(evidence_state="TEXT_GROUNDED",
           verification=Verification(status="VERIFIED"),
           also_on=[ConflictLeg(sheet_id="M-201",
                                evidence_state="TEXT_EVIDENCE_UNAVAILABLE")])
    trust = evidence_trust_composition([f])
    assert trust["units"] == 2
    assert trust["by_state"]["TEXT_GROUNDED"] == 1
    assert trust["by_state"]["TEXT_EVIDENCE_UNAVAILABLE"] == 1
    assert trust["reduced_trust_units"] == 1
    assert trust["grounded_verified_units"] == 1
    # VERIFIED covers the finding, so the reduced-trust leg is not "unverified"
    # in the sense that matters: a verifier did look at this finding.
    assert trust["reduced_trust_unverified_units"] == 0


def test_unassessed_evidence_is_its_own_state():
    """A standard run assesses nothing; calling that "grounded" invents a signal."""
    trust = evidence_trust_composition([_f(), _f(text="other", source_quote="Q2")])
    assert trust["by_state"]["NOT_ASSESSED"] == 2
    assert trust["by_state"]["TEXT_GROUNDED"] == 0
    assert trust["reduced_trust_units"] == 0
    assert trust["grounded_verified_units"] == 0


def test_reduced_trust_unverified_is_counted():
    f = _f(evidence_state="TEXT_EVIDENCE_UNAVAILABLE",
           verification=Verification(status="UNCERTAIN"))
    trust = evidence_trust_composition([f])
    assert trust["reduced_trust_unverified_units"] == 1
    assert trust["grounded_verified_units"] == 0


# --------------------------------------------------------------------------- #
# Artifact links (§11.2: copy before cleanup)
# --------------------------------------------------------------------------- #

def test_saved_links_resolve_after_the_arm_workspace_is_deleted(tmp_path):
    """A link into a deleted temp directory is worse than no link.

    The arm's evidence crops live under a workspace that is destroyed when the
    run ends, so the copy has to happen while it still exists and the link has
    to be relative to where the JSON lands.
    """
    out_dir = tmp_path / "ab_out"
    out_dir.mkdir()
    with TemporaryDirectory() as tmp:
        work = Path(tmp)
        crop = work / "evidence" / "QC-001" / "leg-00__M-101_p1.png"
        crop.parent.mkdir(parents=True)
        crop.write_bytes(b"\x89PNG-not-really")
        f = _f(verification=Verification(status="VERIFIED", evidence=[
            EvidenceArtifact(evidence_id="QC-001#00", qc_id="QC-001",
                             relative_path="evidence/QC-001/leg-00__M-101_p1.png",
                             sha256="deadbeef"),
        ]))
        records = finding_records([f])
        copied = copy_linked_artifacts(
            records, work, out_dir / "arm_baseline_artifacts", link_from=out_dir
        )
        (out_dir / "arm_baseline_findings.json").write_text(
            json.dumps({"records": records}), encoding="utf-8")

    assert copied == 1
    link = records[0]["evidence_artifacts"][0]["link"]
    assert link == "arm_baseline_artifacts/evidence/QC-001/leg-00__M-101_p1.png"
    assert not Path(tmp).exists()                       # the workspace is gone
    assert (out_dir / link).is_file()                   # the link still resolves
    assert (out_dir / link).read_bytes() == b"\x89PNG-not-really"


def test_missing_artifact_is_skipped_not_fatal(tmp_path):
    """An arm that produced no crops must still produce its records."""
    f = _f(verification=Verification(status="VERIFIED", evidence=[
        EvidenceArtifact(relative_path="evidence/QC-001/gone.png"),
    ]))
    records = finding_records([f])
    assert copy_linked_artifacts(records, tmp_path / "nope", tmp_path / "dest",
                                 link_from=tmp_path) == 0
    assert "link" not in records[0]["evidence_artifacts"][0]


# --------------------------------------------------------------------------- #
# Portability and determinism
# --------------------------------------------------------------------------- #

def test_records_carry_no_absolute_paths():
    """The comparison is shared; the arm ran in a directory nobody else has."""
    blob = json.dumps(finding_records([_f(also_on=[_leg("M-201")])]))
    assert "/home/" not in blob and "C:\\\\" not in blob
    assert str(Path.cwd()) not in blob
    # Source correspondence is the positional SRC id, not a path.
    assert json.loads(blob)[0]["identity"]["source_key"] == "SRC-0001"


def test_source_key_falls_back_to_the_basename_when_no_source_id():
    rec = finding_record(_f(source_id="", source_name="mech.pdf"))
    assert rec["identity"]["source_key"] == "mech.pdf"


def test_matching_is_order_independent_and_deterministic():
    """I-7: same inputs, same output — including when the arms shuffle."""
    findings = [_f(text=f"issue {i}", source_quote=f"QUOTE {i}") for i in range(6)]
    extra = _f(text="only here", source_quote="ONLY")
    forward = match_records(finding_records(findings + [extra]),
                            finding_records(findings))
    reversed_ = match_records(finding_records([extra] + findings[::-1]),
                              finding_records(findings[::-1]))
    assert json.dumps(forward, sort_keys=True) == json.dumps(reversed_, sort_keys=True)


def test_empty_arms_reconcile():
    m = match_records([], [])
    assert m["counts"]["reconciles"] is True
    assert m["counts"]["base_total"] == 0


def test_render_is_plain_text_and_names_the_unmatched_records():
    base = [_f(text="issue A", source_quote="QUOTE A"),
            _f(text="dropped", source_quote="DROPPED")]
    var = [_f(text="issue A", source_quote="QUOTE A"),
           _f(text="added", source_quote="ADDED")]
    m = match_records(finding_records(base), finding_records(var))
    text = render_findings_diff(m, base_label="defaults", var_label="MODEL=x")
    assert "only in baseline" in text
    assert "DROPPED" in text and "ADDED" in text
    assert "A candidate is a pointer for a" in text
    assert "\t" not in text


# --------------------------------------------------------------------------- #
# Record availability — an empty list is not a result
# --------------------------------------------------------------------------- #

def test_two_arms_that_genuinely_found_nothing_ran_a_complete_comparison():
    """Both sidecars read fine and both were empty. That IS a comparison.

    Calling it "no comparison ran" would be the §11.3 error inverted: an arm
    pair that agreed perfectly reported as one that could not be checked.
    """
    m = match_records([], [])
    assert m["comparison_status"] == COMPARISON_COMPLETE
    assert m["incomplete_reasons"] == []
    text = render_findings_diff(m, base_label="base", var_label="var")
    assert "INCOMPLETE" not in text
    assert "Unmatched records are the result" in text


def test_a_missing_sidecar_makes_the_surviving_records_not_a_difference():
    """The variant's 2 records are all it produced, not 2 findings the base missed.

    With the baseline sidecar gone the matcher still reports the variant's
    records — they are real data — but the comparison is marked INCOMPLETE and
    the renderer refuses to describe them as one-sided differences. Reporting a
    file-read failure as "the variant found 2 issues the baseline did not" is a
    result invented out of an I/O error.
    """
    var = finding_records([_f(text="a", source_quote="A"),
                           _f(text="b", source_quote="B")])
    m = match_records([], var, base_status=RECORDS_MISSING,
                      variant_status=RECORDS_PRESENT)

    assert m["comparison_status"] == COMPARISON_INCOMPLETE
    assert m["incomplete_reasons"] == ["baseline records are MISSING"]
    assert m["record_status"] == {"base": "MISSING", "variant": "PRESENT"}
    # The records are still there — nothing is thrown away.
    assert m["counts"]["unmatched_variant"] == 2
    assert m["counts"]["reconciles"] is True

    text = render_findings_diff(m, base_label="base", var_label="var")
    assert "[INCOMPLETE]" in text
    assert "NOT one-sided differences" in text
    assert "Unmatched records are the result" not in text


def test_record_status_defaults_to_present_for_a_standalone_caller():
    m = match_records(finding_records([_f()]), finding_records([_f()]))
    assert m["record_status"] == {"base": RECORDS_PRESENT, "variant": RECORDS_PRESENT}
    assert m["comparison_status"] == COMPARISON_COMPLETE
