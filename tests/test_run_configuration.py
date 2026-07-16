"""Phase 23A — the normalized run configuration and QC-status roll-up (§15.1/§3.3).

Pure, hermetic unit tests over ``resolve_run_configuration`` / ``roll_up_qc_status``
/ ``RunConfiguration`` / ``StageResult``. No PyMuPDF, no client, no network — the
resolver and roll-up are dependency-free by design so their product logic is
unit-testable in isolation from the pipeline.
"""
from __future__ import annotations

from drawing_analyzer.models import (
    CONFIGURATION_KINDS,
    QC_STATUSES,
    STAGE_STATUSES,
    RunConfiguration,
    StageResult,
    resolve_run_configuration,
    roll_up_qc_status,
)


# --------------------------------------------------------------------------- #
# resolve_run_configuration — the four product modes
# --------------------------------------------------------------------------- #


def test_standard_mode_runs_no_paid_stage():
    c = resolve_run_configuration()
    assert c.standard_analysis and not c.exhaustive_qc and not c.deterministic_audit_only
    # Only free offline anchoring; nothing that costs an API call.
    assert c.run_anchoring
    for off in (
        c.run_synthesis, c.run_critique, c.run_cross_qc, c.run_auditors,
        c.run_prose_harvest, c.run_verification, c.run_citation, c.run_markup,
        c.run_coverage_check, c.run_identity, c.run_review_plan,
    ):
        assert off is False
    assert c.critique_reads == 0
    assert c.configuration_kind == "NORMAL"
    assert c.qc_requested is False


def test_audit_only_runs_auditors_but_no_model_calls():
    c = resolve_run_configuration(reference_audit=True)
    assert c.deterministic_audit_only and not c.exhaustive_qc
    assert c.run_auditors and c.run_anchoring
    # The free battery structures no prose (DA-013) and calls no model stage.
    assert not c.run_prose_harvest
    assert not c.run_critique and not c.run_cross_qc
    assert not c.run_verification and not c.run_citation and not c.run_markup
    assert not c.run_identity and not c.run_review_plan
    # A deterministic-diagnostics run is not the QC mode the roll-up scores.
    assert c.qc_requested is False


def test_exhaustive_enables_every_required_stage():
    c = resolve_run_configuration(qc_markups=True)
    assert c.exhaustive_qc and not c.deterministic_audit_only
    for on in (
        c.run_synthesis, c.run_critique, c.run_cross_qc, c.run_auditors,
        c.run_prose_harvest, c.run_anchoring, c.run_verification, c.run_citation,
        c.run_markup, c.run_coverage_check, c.run_identity, c.run_review_plan,
    ):
        assert on is True
    assert c.critique_reads == 2
    assert c.configuration_kind == "NORMAL"
    assert c.qc_requested is True


def test_both_boxes_is_exhaustive_not_audit_only():
    # Both checkboxes on resolves to the exhaustive stack (the free battery is
    # already included), never to the diagnostics-only mode (§3.1).
    c = resolve_run_configuration(qc_markups=True, reference_audit=True)
    assert c.exhaustive_qc and not c.deterministic_audit_only and c.run_auditors


# --------------------------------------------------------------------------- #
# resolve_run_configuration — the bool|None override tri-state
# --------------------------------------------------------------------------- #


def test_explicit_false_disables_required_stage_as_debug_override():
    c = resolve_run_configuration(qc_markups=True, critique=False)
    assert c.run_critique is False
    assert c.debug_overrides == ("critique",)
    assert c.configuration_kind == "DEBUG_OVERRIDE"
    # Other required stages stay on.
    assert c.run_cross_qc and c.run_verification and c.run_citation


def test_multiple_overrides_all_recorded():
    c = resolve_run_configuration(
        qc_markups=True, critique=False, cross_qc=False, citation_check=False,
        verify_findings=False,
    )
    assert set(c.debug_overrides) == {"critique", "cross_qc", "citation", "verification"}
    assert c.configuration_kind == "DEBUG_OVERRIDE"


def test_explicit_true_is_redundant_not_an_override():
    c = resolve_run_configuration(qc_markups=True, critique=True)
    assert c.run_critique is True and c.debug_overrides == ()
    assert c.configuration_kind == "NORMAL"


def test_expert_stage_without_qc_markups_runs_but_stays_non_exhaustive():
    # An expert may enable one stage outside exhaustive QC; it runs, but the run is
    # not exhaustive and never structures prose.
    c = resolve_run_configuration(critique=True)
    assert c.run_critique is True
    assert not c.exhaustive_qc and not c.run_prose_harvest
    assert c.qc_requested is False


def test_reference_audit_with_paid_expert_stage_is_not_labeled_audit_only():
    # Combining reference_audit with an explicit paid stage still runs the auditors,
    # but the run is no longer zero-API, so it must NOT claim deterministic_audit_only
    # (the "zero incremental API calls" promise would be false for run accounting).
    c = resolve_run_configuration(reference_audit=True, critique=True)
    assert c.run_auditors is True and c.run_critique is True
    assert c.deterministic_audit_only is False
    # cross-QC / citation / synthesis as the paid expert stage likewise flip it off.
    assert resolve_run_configuration(reference_audit=True, citation_check=True).deterministic_audit_only is False
    assert resolve_run_configuration(reference_audit=True, cross_qc=True).deterministic_audit_only is False
    assert resolve_run_configuration(reference_audit=True, synthesize=True).deterministic_audit_only is False
    # A pure free battery stays audit-only and still runs the auditors.
    pure = resolve_run_configuration(reference_audit=True)
    assert pure.deterministic_audit_only is True and pure.run_auditors is True
    # verification alone never runs outside markup, so it does not break the promise.
    assert resolve_run_configuration(reference_audit=True, verify_findings=True).deterministic_audit_only is True


def test_verified_only_toggle_alters_only_ink_gating():
    base = resolve_run_configuration(qc_markups=True)
    gated = resolve_run_configuration(qc_markups=True, markup_verified_only=True)
    # The only difference is the ink gate; every stage switch is identical.
    assert gated.markup_verified_only and not base.markup_verified_only
    for field in (
        "run_synthesis", "run_critique", "run_cross_qc", "run_auditors",
        "run_prose_harvest", "run_verification", "run_citation", "run_markup",
    ):
        assert getattr(base, field) == getattr(gated, field)
    assert gated.configuration_kind == "NORMAL"


def test_carry_through_options_are_verbatim():
    c = resolve_run_configuration(
        qc_markups=True, ink_rejected=True, focus_findings_to_markups=True,
        use_batch=True,
    )
    assert c.ink_rejected and c.focus_findings_to_markups and c.use_batch


def test_to_dict_round_trips_the_switches():
    c = resolve_run_configuration(qc_markups=True, critique=False)
    d = c.to_dict()
    assert d["exhaustive_qc"] is True
    assert d["configuration_kind"] == "DEBUG_OVERRIDE"
    assert d["debug_overrides"] == ["critique"]
    assert d["critique_reads"] == 0  # critique disabled -> no reads
    assert d["run_critique"] is False


# --------------------------------------------------------------------------- #
# resolve_run_configuration — Phase A planning stages (identity / review_plan)
# --------------------------------------------------------------------------- #


def test_identity_and_plan_ride_the_critique_stack():
    # Expert critique outside exhaustive brings both planning stages with it.
    c = resolve_run_configuration(critique=True)
    assert c.run_identity is True and c.run_review_plan is True
    # Citation alone consumes identity (merged editions/jurisdiction) but no plan.
    c = resolve_run_configuration(citation_check=True)
    assert c.run_identity is True and c.run_review_plan is False
    # Synthesis alone consumes neither.
    c = resolve_run_configuration(synthesize=True)
    assert c.run_identity is False and c.run_review_plan is False


def test_explicit_false_planning_stage_inside_exhaustive_is_debug_override():
    c = resolve_run_configuration(qc_markups=True, identity=False)
    assert c.run_identity is False
    assert "identity" in c.debug_overrides
    assert c.configuration_kind == "DEBUG_OVERRIDE"
    # The plan still runs (critique is on); the planner tolerates identity=None.
    assert c.run_review_plan is True

    c = resolve_run_configuration(qc_markups=True, review_plan=False)
    assert c.run_review_plan is False and "review_plan" in c.debug_overrides
    assert c.run_identity is True


def test_critique_override_drops_plan_as_consequence_not_override():
    # Disabling critique inside exhaustive drops the plan (its only consumer)
    # WITHOUT a second override entry — the plan wasn't individually disabled.
    c = resolve_run_configuration(qc_markups=True, critique=False)
    assert c.run_review_plan is False
    assert c.debug_overrides == ("critique",)
    # Identity stays on: citation still consumes it.
    assert c.run_identity is True


def test_explicit_plan_without_critique_is_honored():
    # An expert may author+export a plan with nothing consuming it (documented
    # edge: no silent downgrade of an explicit True).
    c = resolve_run_configuration(review_plan=True)
    assert c.run_review_plan is True and c.run_critique is False
    assert not c.exhaustive_qc


def test_planning_stages_break_the_free_battery_promise_when_explicit():
    # reference_audit + an explicit paid planning stage is no longer zero-API.
    assert resolve_run_configuration(reference_audit=True, identity=True).deterministic_audit_only is False
    assert resolve_run_configuration(reference_audit=True, review_plan=True).deterministic_audit_only is False
    # The pure free battery keeps both planning stages off (zero-cost intact).
    pure = resolve_run_configuration(reference_audit=True)
    assert pure.deterministic_audit_only is True
    assert pure.run_identity is False and pure.run_review_plan is False


def test_to_dict_carries_planning_switches():
    d = resolve_run_configuration(qc_markups=True).to_dict()
    assert d["run_identity"] is True and d["run_review_plan"] is True
    d = resolve_run_configuration().to_dict()
    assert d["run_identity"] is False and d["run_review_plan"] is False


# --------------------------------------------------------------------------- #
# roll_up_qc_status — the §3.3 deterministic roll-up + the §15.5 gate
# --------------------------------------------------------------------------- #


def _sr(stage: str, expected: bool, status: str) -> StageResult:
    return StageResult(stage=stage, expected=expected, status=status)


def test_rollup_not_requested_for_non_exhaustive():
    assert roll_up_qc_status(resolve_run_configuration(), [], "NOT_REQUESTED") == "NOT_REQUESTED"
    assert (
        roll_up_qc_status(resolve_run_configuration(reference_audit=True), [], "NOT_REQUESTED")
        == "NOT_REQUESTED"
    )


def test_rollup_clean_run_is_gated_to_partial_when_gate_closed():
    cfg = resolve_run_configuration(qc_markups=True)
    stages = [
        _sr("critique", True, "COMPLETE"),
        _sr("cross_qc", True, "COMPLETE"),
        _sr("citation", True, "SKIPPED_VALID"),
    ]
    # Gate closed (Phase 23): a clean exhaustive run must be PARTIAL, never COMPLETE.
    assert roll_up_qc_status(cfg, stages, "COMPLETE", completeness_gate_open=False) == "PARTIAL"
    # Gate open (Phase 26): the same clean run becomes COMPLETE.
    assert roll_up_qc_status(cfg, stages, "COMPLETE", completeness_gate_open=True) == "COMPLETE"


def test_rollup_failed_stage_is_partial():
    cfg = resolve_run_configuration(qc_markups=True)
    stages = [_sr("critique", True, "FAILED"), _sr("cross_qc", True, "COMPLETE")]
    assert roll_up_qc_status(cfg, stages, "COMPLETE", completeness_gate_open=True) == "PARTIAL"


def test_rollup_incomplete_coverage_is_partial():
    cfg = resolve_run_configuration(qc_markups=True)
    stages = [_sr("markup", True, "PARTIAL")]
    assert roll_up_qc_status(cfg, stages, "INCOMPLETE", completeness_gate_open=True) == "PARTIAL"


def test_rollup_debug_override_is_partial_even_when_clean():
    cfg = resolve_run_configuration(qc_markups=True, critique=False)
    stages = [_sr("cross_qc", True, "COMPLETE"), _sr("verification", True, "COMPLETE")]
    # Even with the gate open, a debug-override run can never be COMPLETE.
    assert roll_up_qc_status(cfg, stages, "COMPLETE", completeness_gate_open=True) == "PARTIAL"


def test_rollup_no_useful_output_is_failed():
    cfg = resolve_run_configuration(qc_markups=True)
    stages = [_sr("critique", True, "NOT_REQUESTED"), _sr("cross_qc", True, "NOT_REQUESTED")]
    # Nothing COMPLETE/PARTIAL and a required stage not ok -> FAILED.
    assert roll_up_qc_status(cfg, stages, "NOT_REQUESTED", completeness_gate_open=True) == "FAILED"


# --------------------------------------------------------------------------- #
# StageResult + vocab surface
# --------------------------------------------------------------------------- #


def test_stage_result_to_dict():
    s = StageResult(stage="verification", expected=True, status="COMPLETE", items_out=3)
    d = s.to_dict()
    assert d["stage"] == "verification" and d["status"] == "COMPLETE"
    assert d["expected"] is True and d["items_out"] == 3
    assert "errors" in d and "warnings" in d


def test_status_vocabularies_are_the_canonical_sets():
    assert QC_STATUSES == ("NOT_REQUESTED", "COMPLETE", "PARTIAL", "FAILED")
    assert "SKIPPED_VALID" in STAGE_STATUSES
    assert CONFIGURATION_KINDS == ("NORMAL", "DEBUG_OVERRIDE")
