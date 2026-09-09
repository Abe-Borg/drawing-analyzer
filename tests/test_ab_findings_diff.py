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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ab_findings_diff import (  # noqa: E402
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


def _leg(sheet_id: str, quote: str = "SEE MECH") -> ConflictLeg:
    return ConflictLeg(sheet_id=sheet_id, source_name="arch.pdf",
                       source_id="SRC-0002", page_index=1, source_quote=quote)


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
