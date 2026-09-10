"""The A/B sweep harness's pure logic: summarize, diff, screen, render.

The harness itself spends real money on real drawings, so what is tested here is
everything up to the API boundary — the record it builds from a finished run, the
comparison, and the screen that decides whether a cost win came at a quality
cost. Those are exactly the parts where a bug would quietly bless a bad change.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ab_sweep_drawing_analyzer import (  # noqa: E402
    VALIDITY_COMPARABLE,
    VALIDITY_NOT_COMPARABLE,
    VALIDITY_QUALIFIED,
    RECORD_CONTRACT_VERSION,
    RECORDS_MISSING,
    RECORDS_PRESENT,
    RECORDS_STALE_CONTRACT,
    RECORDS_UNREADABLE,
    _parse_env,
    _pct_delta,
    _tally,
    _findings_path,
    comparison_validity,
    diff_summaries,
    load_arm_records,
    write_arm_records,
    render_diff,
    summarize_run,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _Anchor:
    def __init__(self, status): self.status = status


class _Verification:
    def __init__(self, status): self.status = status


_UNSET = object()


class _Finding:
    def __init__(self, severity="medium", anchor="EXACT", verify="VERIFIED",
                 confidence="REPRODUCED", sources=_UNSET):
        self.severity = severity
        self.anchor = _Anchor(anchor)
        self.verification = _Verification(verify)
        self.confidence = confidence
        # A sentinel, not ``or``: an explicitly-empty ``sources`` is a real case
        # (an untagged finding) that the summary must bucket as "(untagged)".
        # Collapsing it to the default would hide exactly that behavior.
        self.sources = ["critique"] if sources is _UNSET else sources


class _SheetRef:
    def __init__(self, source_id, page_index):
        self.source_id = source_id
        self.source_name = "set.pdf"
        self.page_index = page_index


class _Sheet:
    def __init__(self, source_id="SRC-0001", page_index=0, ok=True):
        self.ref = _SheetRef(source_id, page_index)
        self.ok = ok


class _Ctx:
    def __init__(self, findings, *, cost=1.0, in_tok=1000, out_tok=100,
                 sheets=None):
        self.all_findings = findings
        # Four pages of one source unless a test cares which ones were read.
        self.sheets = ([_Sheet(page_index=i) for i in range(4)]
                       if sheets is None else sheets)
        self.sheet_count = len(self.sheets)
        self.ok_sheet_count = sum(1 for s in self.sheets if s.ok)
        self.errors = []
        self.qc_status = "COMPLETE"
        self.coverage_status = "COMPLETE"
        self.total_input_tokens = in_tok
        self.total_output_tokens = out_tok
        self.total_image_token_estimate = in_tok - 200
        self.total_estimated_cost = cost
        self.run_usage = None


# --------------------------------------------------------------------------- #
# _tally
# --------------------------------------------------------------------------- #


def test_tally_never_drops_a_value():
    """An unrecognized verdict must land in ``other``, not vanish.

    A silently-dropped value would make one arm's population look smaller than
    it is, which reads as "cleaner" on every rate the screen computes.
    """
    t = _tally(["EXACT", "EXACT", "WEIRD_NEW_TIER", ""], ("EXACT", "FUZZY"))
    assert t["EXACT"] == 2
    assert t["FUZZY"] == 0
    assert t["other"] == 2          # the unknown tier AND the empty string
    assert sum(t.values()) == 4     # sums to the population


def test_tally_keeps_declared_keys_even_when_empty():
    t = _tally([], ("EXACT", "FUZZY", "TILE", "UNANCHORED"))
    assert list(t) == ["EXACT", "FUZZY", "TILE", "UNANCHORED", "other"]


# --------------------------------------------------------------------------- #
# summarize_run
# --------------------------------------------------------------------------- #


def test_summary_captures_the_three_quality_signals():
    ctx = _Ctx([
        _Finding(anchor="EXACT", verify="VERIFIED", confidence="REPRODUCED"),
        _Finding(anchor="UNANCHORED", verify="REJECTED", confidence="SINGLETON"),
        _Finding(anchor="TILE", verify="UNCERTAIN", confidence="REPRODUCED"),
    ])
    s = summarize_run(ctx)

    assert s["findings_total"] == 3
    assert s["anchor_tiers"]["UNANCHORED"] == 1
    assert s["verification"]["REJECTED"] == 1
    assert s["confidence"]["REPRODUCED"] == 2
    assert s["estimated_cost_usd"] == 1.0


def test_summary_counts_a_finding_under_every_source_tag():
    """Findings carry multiple provenance tags; the rollup must not pick one."""
    ctx = _Ctx([
        _Finding(sources=["critique", "digest"]),
        _Finding(sources=["critique"]),
        _Finding(sources=[]),
    ])
    s = summarize_run(ctx)
    assert s["findings_by_source"]["critique"] == 2
    assert s["findings_by_source"]["digest"] == 1
    assert s["findings_by_source"]["(untagged)"] == 1


# --------------------------------------------------------------------------- #
# _pct_delta
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("base,var,expected", [
    (100, 50, -50.0),
    (100, 150, 50.0),
    (0, 10, None),      # undefined, not +inf
    (None, 10, None),
    (10, None, None),
])
def test_pct_delta(base, var, expected):
    assert _pct_delta(base, var) == expected


# --------------------------------------------------------------------------- #
# The screen
# --------------------------------------------------------------------------- #


def _arms(base_findings, var_findings, *, base_cost=10.0, var_cost=6.0):
    return (
        summarize_run(_Ctx(base_findings, cost=base_cost)),
        summarize_run(_Ctx(var_findings, cost=var_cost)),
    )


def test_screen_is_clean_when_cost_drops_and_quality_holds():
    findings = [_Finding() for _ in range(10)]
    base, var = _arms(findings, [_Finding() for _ in range(10)])
    d = diff_summaries(base, var)

    assert d["verdict"]["clean_screen"] is True
    assert d["cost"]["pct"] == pytest.approx(-40.0)


def test_screen_flags_a_rise_in_unanchored():
    """The hallucination signal — a cheaper arm inventing more quotes."""
    base = [_Finding(anchor="EXACT") for _ in range(10)]
    var = [_Finding(anchor="EXACT") for _ in range(6)] + [
        _Finding(anchor="UNANCHORED") for _ in range(4)
    ]
    d = diff_summaries(*_arms(base, var))
    concerns = " ".join(d["verdict"]["concerns"])

    assert d["verdict"]["clean_screen"] is False
    assert "UNANCHORED" in concerns
    assert "hallucination" in concerns


def test_screen_flags_a_rise_in_rejected():
    base = [_Finding(verify="VERIFIED") for _ in range(10)]
    var = [_Finding(verify="VERIFIED") for _ in range(7)] + [
        _Finding(verify="REJECTED") for _ in range(3)
    ]
    d = diff_summaries(*_arms(base, var))
    assert "REJECTED" in " ".join(d["verdict"]["concerns"])


def test_screen_flags_a_fall_in_reproduction():
    base = [_Finding(confidence="REPRODUCED") for _ in range(10)]
    var = [_Finding(confidence="REPRODUCED") for _ in range(5)] + [
        _Finding(confidence="SINGLETON") for _ in range(5)
    ]
    d = diff_summaries(*_arms(base, var))
    assert "REPRODUCED" in " ".join(d["verdict"]["concerns"])


def test_screen_catches_the_quiet_failure_of_simply_finding_less():
    """Fewer findings at a flat verified rate reads as 'cheaper AND cleaner'.

    Every other line in the report improves: cost down, REJECTED count down,
    UNANCHORED count down. Only the population shrank. This is the failure mode
    most likely to be mistaken for a win, so it gets its own check.
    """
    base = [_Finding(verify="VERIFIED") for _ in range(20)]
    var = [_Finding(verify="VERIFIED") for _ in range(10)]   # half the findings
    d = diff_summaries(*_arms(base, var))
    concerns = " ".join(d["verdict"]["concerns"])

    assert d["verdict"]["clean_screen"] is False
    assert "finding count fell" in concerns
    # WP-06 §11.3: the screen raises the drop as a REVIEW REQUIREMENT and must
    # not claim it proves defects went unseen — it cannot tell missed defects
    # from removed noise, changed dedup, or run-to-run variance, and asserting
    # the first is how a legitimate noise reduction gets rejected.
    assert "REVIEW REQUIRED" in concerns
    assert "findings_diff.json" in concerns
    assert "missed findings, not cleaner ones" not in concerns
    # And note the rates alone would NOT have caught it:
    assert d["verification"]["VERIFIED"]["delta"] == -10


def test_screen_tolerates_small_rate_movement():
    """Model runs are not deterministic; a hair-trigger rejects on noise."""
    base = [_Finding(anchor="EXACT") for _ in range(100)]
    var = [_Finding(anchor="EXACT") for _ in range(97)] + [
        _Finding(anchor="UNANCHORED") for _ in range(3)
    ]
    d = diff_summaries(*_arms(base, var))
    assert d["verdict"]["clean_screen"] is True   # 3% < 5% tolerance


def test_screen_is_silent_not_approving():
    """A clean screen must not be rendered as an endorsement."""
    findings = [_Finding() for _ in range(10)]
    d = diff_summaries(*_arms(findings, list(findings)))
    out = render_diff(d, base_label="defaults", var_label="X=1")

    assert "NOT an approval" in out
    assert "cannot establish that a change is safe" in out


def test_empty_arms_do_not_crash_the_screen():
    """A run that produced no findings must not divide by zero."""
    d = diff_summaries(*_arms([], []))
    assert d["verdict"]["clean_screen"] is True
    render_diff(d, base_label="a", var_label="b")  # must not raise


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def test_render_shows_cost_delta_and_the_signal_tables():
    base = [_Finding(anchor="EXACT", verify="VERIFIED") for _ in range(8)]
    var = [_Finding(anchor="FUZZY", verify="VERIFIED") for _ in range(8)]
    out = render_diff(
        diff_summaries(*_arms(base, var)),
        base_label="defaults",
        var_label="DRAWING_ANALYZER_CRITIQUE_MODEL=claude-sonnet-5",
    )

    assert "DRAWING_ANALYZER_CRITIQUE_MODEL=claude-sonnet-5" in out
    assert "-40.0%" in out            # 10.00 -> 6.00
    assert "anchor tier" in out
    assert "verification verdict" in out
    assert "self-consistency" in out
    # Zero/zero rows are suppressed so the tables stay scannable.
    assert "TILE" not in out


# --------------------------------------------------------------------------- #
# Env parsing
# --------------------------------------------------------------------------- #


def test_parse_env():
    assert _parse_env("") == {}
    assert _parse_env("A=1") == {"A": "1"}
    assert _parse_env("A=1,B=two") == {"A": "1", "B": "two"}
    assert _parse_env(" A = 1 , B=2 ") == {"A": "1", "B": "2"}
    # A value containing '=' survives (partition, not split).
    assert _parse_env("A=x=y") == {"A": "x=y"}


def test_parse_env_rejects_a_bare_name():
    with pytest.raises(ValueError, match="NAME=VALUE"):
        _parse_env("JUST_A_NAME")


@pytest.mark.parametrize("baseline,variant", [
    ("", ""),                                        # both defaults
    ("DRAWING_ANALYZER_TILE_TARGET_PX=1240",
     "DRAWING_ANALYZER_TILE_TARGET_PX=1240"),        # same non-empty mapping
    ("A=1,B=2", "B=2,A=1"),                          # same mapping, written differently
])
def test_identical_arms_are_rejected(baseline, variant):
    """Two identical arms measure nothing; the CLI must refuse rather than bill.

    Checking only "is the variant mapping empty" let the second and third cases
    through — two identical, billable runs whose diff is guaranteed to be noise.
    What decides an arm is the environment its process ends up with, so that is
    what is compared.
    """
    from ab_sweep_drawing_analyzer import main

    with pytest.raises(SystemExit) as e:
        main(["--pdf", "x.pdf", "--baseline", baseline, "--variant", variant])
    assert e.value.code != 0


def test_differing_arms_are_accepted_past_the_equality_guard(monkeypatch, tmp_path):
    """The guard must not block a genuine sweep."""
    from ab_sweep_drawing_analyzer import main

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Past the equality guard, the next gate is the missing-key check (exit 2),
    # which proves the arms were accepted as different without billing anything.
    assert main([
        "--pdf", str(pdf), "--baseline", "",
        "--variant", "DRAWING_ANALYZER_TILE_TARGET_PX=1240",
    ]) == 2


# --------------------------------------------------------------------------- #
# Transport resolution
# --------------------------------------------------------------------------- #


def test_transport_matches_the_runtime_default(monkeypatch):
    """--estimate must price the transport the arms will actually run on.

    ``extract_drawing_context`` defaults to REAL-TIME when the caller passes no
    ``use_batch`` and the env var is unset, while the exhaustive estimator
    defaults to ``batch=True``. Quoting the estimator's default against a
    real-time run under-states digest and critique — the two stages that are
    91% of the bill — by half, in the one place whose whole job is to say what
    a run will cost before you commit to it.
    """
    from ab_sweep_drawing_analyzer import resolve_transport
    from drawing_analyzer.pipeline import _resolve_use_batch

    monkeypatch.delenv("DRAWING_ANALYZER_USE_BATCH", raising=False)
    assert resolve_transport() == (False, False)
    assert resolve_transport()[0] == _resolve_use_batch(None)

    monkeypatch.setenv("DRAWING_ANALYZER_USE_BATCH", "1")
    assert resolve_transport() == (True, True)
    assert resolve_transport()[0] == _resolve_use_batch(None)

    # Critique follows the digest transport; this harness never splits them.
    for value in ("0", "false", "off", ""):
        monkeypatch.setenv("DRAWING_ANALYZER_USE_BATCH", value)
        digest, critique = resolve_transport()
        assert digest is critique is False


def test_estimate_prices_real_time_by_default_not_batch(monkeypatch, capsys, tmp_path):
    """End-to-end: the printed estimate follows the resolved transport."""
    from ab_sweep_drawing_analyzer import main

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.delenv("DRAWING_ANALYZER_USE_BATCH", raising=False)
    monkeypatch.setattr(
        "drawing_analyzer.render.list_sheets", lambda pdfs: [object()] * 10
    )

    main(["--pdf", str(pdf), "--variant", "DRAWING_ANALYZER_TILE_TARGET_PX=1240",
          "--estimate"])
    real_time = capsys.readouterr().out
    assert "(real-time)" in real_time
    assert "(batch)" not in real_time

    monkeypatch.setenv("DRAWING_ANALYZER_USE_BATCH", "1")
    main(["--pdf", str(pdf), "--variant", "DRAWING_ANALYZER_TILE_TARGET_PX=1240",
          "--estimate"])
    batched = capsys.readouterr().out
    assert "(batch)" in batched

    # And the batch quote is materially cheaper than the real-time one — proof
    # the flag reached the estimator rather than just the label.
    def first_dollar(text: str) -> float:
        import re
        return float(re.search(r"\$([\d,]+\.\d\d)", text).group(1).replace(",", ""))

    assert first_dollar(batched) < first_dollar(real_time)


def test_estimate_does_not_leak_arm_env_into_the_parent(monkeypatch, tmp_path):
    """Pricing an arm sets its env temporarily; the parent must be restored."""
    from ab_sweep_drawing_analyzer import main

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setenv("DRAWING_ANALYZER_TILE_TARGET_PX", "1560")
    monkeypatch.setattr(
        "drawing_analyzer.render.list_sheets", lambda pdfs: [object()] * 2
    )

    main(["--pdf", str(pdf), "--variant", "DRAWING_ANALYZER_TILE_TARGET_PX=1100",
          "--estimate"])
    import os as _os
    assert _os.environ["DRAWING_ANALYZER_TILE_TARGET_PX"] == "1560"


# --------------------------------------------------------------------------- #
# WP-04 §9.1 — the estimate crosses the same configuration boundary as an arm
# --------------------------------------------------------------------------- #
#
# The defect these pin, measured before the fix: pricing
# ``DRAWING_ANALYZER_MODEL=claude-sonnet-5`` against a 10-sheet exhaustive run
# quoted **$28.59**, byte-identical to the Opus baseline, because
# ``REVIEW_MODEL_DEFAULT`` was bound when the parent imported ``api_config`` and
# no later ``os.environ`` write could move it. The true figure is $11.60. The
# estimator was not merely imprecise about the variant — it never priced the
# variant at all, and the whole point of that arm is the model swap.
#
# These spawn real child processes. That is not incidental: an in-process test
# CANNOT distinguish a correct fix from the rejected one, because the failure
# mode *is* the import binding. Each child is hermetic — local inspection only,
# no key, no client, no network.

import ast                    # noqa: E402
import json as _json          # noqa: E402
import os as _os              # noqa: E402
import subprocess as _subprocess  # noqa: E402

from ab_sweep_drawing_analyzer import (  # noqa: E402
    _estimate_in_process,
    _is_secret_env,
    env_label,
    estimate_arm,
    run_arm,
)

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ab_sweep_drawing_analyzer.py"
#: Obvious fake. Deliberately not credential-shaped — ``scripts/scan_secrets.py``
#: flags ``sk-ant-`` followed by 30+ characters, and a realistic sentinel fails
#: the repo's own secret scan.
_FAKE_KEY = "not-a-real-key-do-not-use-wp04"


def _price(env: dict, *, sheets: int = 10, exhaustive: bool = True) -> dict:
    return estimate_arm("t", env, sheets, 1, exhaustive=exhaustive)


def _fresh_process_stage_models(env: dict) -> dict:
    """What a fresh process resolves, computed independently of the script.

    This is the oracle for "matches the execution child": ``_run_arm_in_process``
    resolves its models with exactly this expression, in exactly this kind of
    freshly-started process. Re-deriving it here rather than importing the
    script's own helper means a bug in the helper cannot make both sides agree.
    """
    src = Path(__file__).resolve().parent.parent / "src"
    code = (
        "import json,sys;sys.path.insert(0,%r);"
        "from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT as M;"
        "from drawing_analyzer.cost import resolve_stage_models;"
        "json.dump(vars(resolve_stage_models(model=M)),sys.stdout)" % str(src)
    )
    proc = _subprocess.run([sys.executable, "-c", code], env={**_os.environ, **env},
                           capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return _json.loads(proc.stdout)


#: Every stage whose resolver is ``os.environ.get(<own var>) or
#: REVIEW_MODEL_DEFAULT``. The plan named four; ``review_plan`` has the same
#: shape (``review_planner.default_review_plan_model``) and makes five.
_FALLBACK_STAGES = ("critique", "cross_qc", "synthesis", "focus", "review_plan")


def _bind_parents_model() -> str:
    """Import ``api_config`` HERE so this process's binding is definitely stale.

    Without this the tests below depend on pytest's import order. ``api_config``
    binds ``REVIEW_MODEL_DEFAULT`` on first import; if nothing in the session has
    imported it yet, an in-process estimator that sets the environment *before*
    that first import resolves the variant model correctly by accident — and the
    rejected design passes. Running one test file in isolation was enough to hit
    it. Forcing the binding up front makes the test measure the process boundary
    rather than the order the suite happened to import things in.
    """
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT
    return REVIEW_MODEL_DEFAULT


def test_estimate_children_resolve_the_arm_model_not_the_parents():
    """§9.3 case 1. The baseline and variant must price different models."""
    assert _bind_parents_model() != "claude-sonnet-5", "precondition: parent is not on the variant"
    base = _price({})
    var = _price({"DRAWING_ANALYZER_MODEL": "claude-sonnet-5"})
    assert base["model"] != var["model"]
    assert var["model"] == "claude-sonnet-5"
    # And the money moved with it. Equal totals were the whole bug.
    assert var["low_cost"] < base["low_cost"]


def test_a_global_model_variant_moves_every_fallback_dependent_stage():
    """§9.3 case 2 — the regression an in-process fix passes only for digest.

    Setting ``DRAWING_ANALYZER_MODEL`` alone must move the digest *and* all five
    stages that fall back to ``REVIEW_MODEL_DEFAULT``. A fix that re-reads the
    environment for the digest inside the parent satisfies the first assertion
    and fails every one after it, while the execution child resolves all six.
    """
    assert _bind_parents_model() != "claude-sonnet-5", "precondition: parent is not on the variant"
    env = {"DRAWING_ANALYZER_MODEL": "claude-sonnet-5"}
    stages = _price(env)["stage_models"]
    assert stages["digest"] == "claude-sonnet-5"
    for stage in _FALLBACK_STAGES:
        assert stages[stage] == "claude-sonnet-5", stage
    # Stages with their own non-fallback default must NOT move — otherwise this
    # would pass by resolving everything to the variant model.
    assert stages["identity"] == "claude-sonnet-5"      # Sonnet by policy anyway
    assert stages["investigation"] != "claude-sonnet-5"


def test_estimate_child_agrees_with_a_fresh_process_resolution():
    """§9.3 case 2, other half: the estimate matches what execution will do."""
    assert _bind_parents_model() != "claude-sonnet-5", "precondition: parent is not on the variant"
    for env in ({}, {"DRAWING_ANALYZER_MODEL": "claude-sonnet-5"}):
        assert _price(env)["stage_models"] == _fresh_process_stage_models(env)


def test_explicit_per_stage_overrides_survive_a_different_global_model():
    """§9.3 case 3. Sonnet digest, explicit Opus critique and cross-QC."""
    assert _bind_parents_model() != "claude-sonnet-5", "precondition: parent is not on the variant"
    stages = _price({
        "DRAWING_ANALYZER_MODEL": "claude-sonnet-5",
        "DRAWING_ANALYZER_CRITIQUE_MODEL": "claude-opus-5",
        "DRAWING_ANALYZER_CROSS_QC_MODEL": "claude-opus-5",
    })["stage_models"]
    assert stages["digest"] == "claude-sonnet-5"
    assert stages["critique"] == "claude-opus-5"
    assert stages["cross_qc"] == "claude-opus-5"
    # The stages with no explicit override still follow the global model.
    assert stages["synthesis"] == stages["focus"] == "claude-sonnet-5"


def test_estimate_transport_matches_what_the_arm_will_run_on():
    """§9.3 case 4."""
    assert _price({"DRAWING_ANALYZER_USE_BATCH": "1"})["transport"] == {
        "digest_batch": True, "critique_batch": True,
    }
    assert _price({"DRAWING_ANALYZER_USE_BATCH": "0"})["transport"] == {
        "digest_batch": False, "critique_batch": False,
    }
    # And the rate really applied, not just the label.
    assert (_price({"DRAWING_ANALYZER_USE_BATCH": "1"})["low_cost"]
            < _price({"DRAWING_ANALYZER_USE_BATCH": "0"})["low_cost"])


def test_parent_environment_is_untouched_by_a_successful_estimate(monkeypatch, tmp_path):
    """§9.3 case 5, success half — and that nothing is ever cleared."""
    from ab_sweep_drawing_analyzer import main

    monkeypatch.setenv("DRAWING_ANALYZER_MODEL", "claude-opus-5")
    monkeypatch.setenv("WP04_PARENT_ONLY", "keep-me")
    before = dict(_os.environ)
    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr("drawing_analyzer.render.list_sheets", lambda pdfs: [object()] * 3)

    main(["--pdf", str(pdf), "--variant", "DRAWING_ANALYZER_MODEL=claude-sonnet-5",
          "--estimate"])

    assert dict(_os.environ) == before
    assert _os.environ["WP04_PARENT_ONLY"] == "keep-me"


def test_parent_environment_survives_a_failing_estimate(monkeypatch):
    """§9.3 case 5, failure half. A dead child must not strand the parent."""
    before = dict(_os.environ)

    def _boom(cmd, **kw):
        class _P:
            returncode = 3
            stdout = ""
            stderr = "child exploded"
        return _P()

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _boom)
    with pytest.raises(SystemExit) as exc:
        estimate_arm("variant", {"DRAWING_ANALYZER_MODEL": "x"}, 4, 1, exhaustive=True)
    assert dict(_os.environ) == before
    # Honest propagation: a failed estimate is never a zero-cost arm.
    assert "variant" in str(exc.value) and "child exploded" in str(exc.value)


def test_unreadable_child_output_is_an_error_not_a_free_arm(monkeypatch):
    """A child that exits 0 with garbage must not be read as $0.00."""
    class _P:
        returncode = 0
        stdout = "Warning: something\nnot json at all"
        stderr = ""

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", lambda *a, **k: _P())
    with pytest.raises(SystemExit, match="unreadable output"):
        estimate_arm("variant", {}, 4, 1, exhaustive=True)


def test_estimate_needs_no_api_key(tmp_path):
    """§9.3 case 6, subprocess half: a real child with the key removed."""
    env = {k: v for k, v in _os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = _subprocess.run(
        [sys.executable, str(_SCRIPT), "--_estimate-arm", "--sheets", "5",
         "--file-count", "1", "--exhaustive"],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert _json.loads(proc.stdout)["low_cost"] > 0


def test_estimate_never_constructs_a_client(monkeypatch):
    """§9.3 case 6, in-process half: a client factory that raises if called.

    Run in-process precisely because a subprocess cannot be monkeypatched. This
    proves the function body reaches no provider client; the subprocess test
    above proves the shipped path needs no key.
    """
    def _explode(*a, **k):
        raise AssertionError("estimate constructed an API client")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _explode)
    monkeypatch.setattr("drawing_analyzer.client.Anthropic", _explode)
    out = _estimate_in_process(6, 1, exhaustive=True)
    assert out["sheets"] == 6 and out["low_cost"] is not None


def test_an_unpriced_model_stays_unknown_rather_than_zero():
    """§9.3 case 7. Silence beats a confidently wrong small number."""
    _bind_parents_model()
    est = _price({"DRAWING_ANALYZER_MODEL": "claude-not-a-real-model-wp04"})
    assert est["low_cost"] is None and est["high_cost"] is None
    est_std = _price({"DRAWING_ANALYZER_MODEL": "claude-not-a-real-model-wp04"},
                     exhaustive=False)
    assert est_std["low_cost"] is None


def test_an_unpriced_stage_does_not_publish_a_partial_total():
    """One unpriced stage must void the total, not quietly shrink it."""
    _bind_parents_model()
    est = _price({"DRAWING_ANALYZER_CRITIQUE_MODEL": "claude-not-a-real-model-wp04"})
    assert est["low_cost"] is None, (
        "a total that drops the unpriced stage under-quotes the run while "
        "looking complete"
    )


def test_arm_argv_is_an_array_and_carries_paths_with_spaces(monkeypatch, tmp_path):
    """§9.3 case 9. No shell-composed strings; no dependence on a home dir."""
    captured = {}

    class _P:
        returncode = 0

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["env"] = kw.get("env")
        (tmp_path / "arm_x.json").write_text("{}", encoding="utf-8")
        return _P()

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _fake_run)
    spacey = tmp_path / "Project Set A" / "M-101 rev 2.pdf"
    spacey.parent.mkdir(parents=True)
    spacey.write_bytes(b"%PDF-1.7\n")

    run_arm("x", {"DRAWING_ANALYZER_MODEL": "m"}, [spacey], tmp_path, exhaustive=True)

    cmd = captured["cmd"]
    assert isinstance(cmd, list) and all(isinstance(a, str) for a in cmd)
    # The path travels as ONE argv element, unquoted and unmangled. A
    # shell-composed string would have needed quoting and would split here.
    assert str(spacey) in cmd
    assert cmd[0] == sys.executable
    assert captured["env"]["DRAWING_ANALYZER_MODEL"] == "m"


def test_estimate_child_argv_is_an_array(monkeypatch):
    captured = {}

    class _P:
        returncode = 0
        stdout = '{"low_cost": 1.0, "high_cost": 1.0}'
        stderr = ""

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _P()

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _fake_run)
    estimate_arm("x", {}, 7, 2, exhaustive=False)
    cmd = captured["cmd"]
    assert isinstance(cmd, list) and cmd[0] == sys.executable
    assert "--sheets" in cmd and "7" in cmd
    assert "--no-exhaustive" in cmd


# --------------------------------------------------------------------------- #
# §9.3 case 10 — a secret in the environment never reaches printed or saved text
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", [
    "ANTHROPIC_API_KEY", "anthropic_api_key", "SOME_TOKEN", "DB_PASSWORD",
    "MY_SECRET", "AWS_CREDENTIAL_FILE",
])
def test_secret_env_names_are_recognized(name):
    assert _is_secret_env(name)


@pytest.mark.parametrize("name", [
    "DRAWING_ANALYZER_MODEL", "DRAWING_ANALYZER_TILE_TARGET_PX",
    "DRAWING_ANALYZER_USE_BATCH", "PATH",
])
def test_ordinary_env_names_are_not_redacted(name):
    assert not _is_secret_env(name)
    assert f"{name}=1" == env_label({name: "1"})


def test_env_label_redacts_by_name_not_by_value_shape():
    """A credential that does not look like one must still be covered."""
    label = env_label({"ANTHROPIC_API_KEY": _FAKE_KEY, "DRAWING_ANALYZER_MODEL": "m"})
    assert _FAKE_KEY not in label
    assert "ANTHROPIC_API_KEY=[REDACTED]" in label
    assert "DRAWING_ANALYZER_MODEL=m" in label


def test_no_secret_reaches_the_printed_estimate(monkeypatch, capsys, tmp_path):
    """End to end: a key passed as an arm setting is never echoed."""
    from ab_sweep_drawing_analyzer import main

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    monkeypatch.setattr("drawing_analyzer.render.list_sheets", lambda pdfs: [object()] * 2)
    main(["--pdf", str(pdf),
          "--variant", f"ANTHROPIC_API_KEY={_FAKE_KEY}",
          "--estimate"])
    out = capsys.readouterr().out
    assert _FAKE_KEY not in out
    assert "[REDACTED]" in out


# --------------------------------------------------------------------------- #
# §9.1 — one configuration resolver, shared by estimation and execution
# --------------------------------------------------------------------------- #


def test_the_estimate_reports_every_lever_that_moves_the_bill():
    """§9.1: stage models, both transports, grid, overlap, target, mode."""
    est = _price({"DRAWING_ANALYZER_TILE_TARGET_PX": "1240"})
    for key in ("model", "stage_models", "transport", "grid", "overlap_frac",
                "tile_target_px", "tile_target_effective", "exhaustive"):
        assert key in est, key
    assert est["tile_target_px"] == "1240"
    assert est["tile_target_effective"] == 1240
    assert est["grid"] == [6, 6]
    assert est["exhaustive"] is True


def test_a_clamped_tile_target_is_reported_as_clamped():
    """The typed value and the effective one are both shown when they differ.

    ``tiling._vector_target_override`` silently clamps out-of-range values. An
    arm priced at the clamped target while the operator believes the typed one
    is a comparison of something other than what they asked for.
    """
    est = _price({"DRAWING_ANALYZER_TILE_TARGET_PX": "3"})   # below the floor
    assert est["tile_target_px"] == "3"
    assert est["tile_target_effective"] != 3
    assert est["tile_target_effective"] >= 400


def test_an_unset_target_reports_the_default_rather_than_a_blank():
    est = _price({})
    assert est["tile_target_px"] == ""
    assert est["tile_target_effective"] is None
    assert est["tile_target_default"] > 0


def test_execution_and_estimate_describe_the_arm_with_the_same_resolver():
    """Both children call ``resolve_arm_configuration``; drift is the failure.

    Asserted structurally: the execution arm's summary must carry exactly the
    configuration record the estimate emits, so the quote you approved and the
    run you paid for are comparable field by field. Two hand-maintained copies
    is how they stop matching.
    """
    import ab_sweep_drawing_analyzer as mod
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(c, ast.Call) and getattr(c.func, "id", "") == "resolve_arm_configuration"
            for c in ast.walk(node)
        )
    }
    assert {"_run_arm_in_process", "_estimate_in_process"} <= callers, callers


def test_configuration_record_carries_no_secret_value(monkeypatch):
    """§9.3 case 10 for the saved record, not just the printed label."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", _FAKE_KEY)
    est = _price({})
    assert _FAKE_KEY not in _json.dumps(est)


# --------------------------------------------------------------------------- #
# WP-06 §11.1 — usage axes the family/model rollups do not carry
# --------------------------------------------------------------------------- #
#
# The plan is explicit that this extends the existing summary rather than
# building a second benchmarking system, and that nothing here re-prices: every
# dollar figure comes from ``UsageRecord.estimated_cost``, computed by the run at
# its own rate class. These tests pin the *view*, and pin that it stays a view.

from decimal import Decimal  # noqa: E402

from ab_sweep_drawing_analyzer import (  # noqa: E402
    CONFIDENCE_LEVELS,
    ArmSpec,
    parse_overlap,
    usage_breakdown,
)
from drawing_analyzer.models import RunUsage, UsageRecord  # noqa: E402


def _usage(*records) -> RunUsage:
    ru = RunUsage()
    for r in records:
        ru.add(r)
    return ru


def _rec(**kw) -> UsageRecord:
    base = dict(stage_family="digest", stage_instance="digest:SRC-0001:p0",
                model="claude-opus-5", input_tokens=1000, output_tokens=100,
                estimated_cost=Decimal("0.01"))
    base.update(kw)
    return UsageRecord(**base)


def test_per_family_cost_reconciles_with_the_run_total():
    """§11.5: family costs must sum to what the run already says it spent."""
    ru = _usage(
        _rec(stage_family="digest", estimated_cost=Decimal("1.00")),
        _rec(stage_family="critique", estimated_cost=Decimal("2.50")),
        _rec(stage_family="critique", estimated_cost=Decimal("0.50")),
    )
    families = ru.by_family()
    assert float(families["digest"]["estimated_cost"]) == 1.00
    assert float(families["critique"]["estimated_cost"]) == 3.00
    assert float(ru.total_estimated_cost) == 4.00


def test_the_summary_now_emits_family_cost_alongside_tokens():
    """It computed this and dropped it: "cheaper" could not be told from "did less"."""
    ctx = _Ctx([_Finding()])
    ctx.run_usage = _usage(_rec(stage_family="critique", estimated_cost=Decimal("2.50")))
    summary = summarize_run(ctx)
    assert summary["by_family"]["critique"]["cost"] == 2.50
    assert summary["by_family"]["critique"]["input"] == 1000


def test_an_unpriced_family_stays_none_not_zero():
    """Same rule as the grand total: unknown price is never a smaller number."""
    ru = _usage(
        _rec(stage_family="critique", model="mystery", estimated_cost=None),
        _rec(stage_family="critique", estimated_cost=Decimal("2.00")),
    )
    assert ru.by_family()["critique"]["estimated_cost"] is None
    assert usage_breakdown(ru)["unpriced_records"] == 1


def test_transport_is_broken_out_because_it_moves_the_rate():
    """Two arms can be token-identical and differ by half on transport alone."""
    ru = _usage(
        _rec(transport="REAL_TIME"),
        _rec(transport="BATCH"), _rec(transport="BATCH"),
    )
    axes = usage_breakdown(ru)
    assert axes["by_transport"]["BATCH"]["records"] == 2
    assert axes["by_transport"]["REAL_TIME"]["records"] == 1
    assert axes["by_transport"]["BATCH"]["input_tokens"] == 2000


def test_cache_tokens_are_not_folded_into_input():
    """Read and write are separately priced multipliers on the input rate.

    Summing them into "input" makes a prompt-cache experiment — the exact thing
    the critique's shared-prefix breakpoint is — unmeasurable.
    """
    ru = _usage(
        _rec(cache_write_tokens=90_000, input_tokens=0),
        _rec(cache_read_tokens=90_000, input_tokens=0),
    )
    axes = usage_breakdown(ru)
    assert axes["cache_write_tokens"] == 90_000
    assert axes["cache_read_tokens"] == 90_000


def test_the_requested_write_ttl_is_recorded_because_it_picks_the_rate():
    """5-minute writes bill 1.25x base input; one-hour writes bill 2x."""
    ru = _usage(
        _rec(cache_write_tokens=1000, cache_write_ttl=None),
        _rec(cache_write_tokens=2000, cache_write_ttl="1h"),
    )
    ttls = usage_breakdown(ru)["cache_write_tokens_by_ttl"]
    assert ttls == {"1h": 2000, "5m": 1000}


def test_outcomes_are_not_collapsed_into_one_paid_calls_number():
    """§11.1 names this specifically, and the reason is an arm that looks cheap.

    A served cache hit costs nothing. An abandoned batch attempt costs nothing
    *and* produced no response. A failed-parse call consumed real tokens. Folding
    them together lets an arm that abandoned half its batches read as a saving.
    """
    ru = _usage(
        _rec(),                                                    # served
        _rec(cache_hit=True, transport="CACHE", input_tokens=0,
             output_tokens=0, estimated_cost=Decimal("0")),        # cache hit
        _rec(terminal_status="ABANDONED_EXPIRED", input_tokens=0,
             output_tokens=0, estimated_cost=Decimal("0")),        # non-billable
        _rec(parse_success=False),                                 # billed, unusable
        _rec(terminal_status="FAILED"),                            # failed
    )
    outcomes = usage_breakdown(ru)["by_outcome"]
    assert outcomes == {"served": 1, "cache_hit": 1, "abandoned": 1,
                        "parse_failed": 1, "failed": 1}
    assert sum(outcomes.values()) == usage_breakdown(ru)["records"]


def test_record_granularity_is_labelled_not_implied():
    """§11.1: verification is aggregated, so a record count is not a call count."""
    axes = usage_breakdown(_usage(_rec()))
    assert "verification" in axes["record_granularity"]
    assert "aggregat" in axes["record_granularity"]


def test_an_empty_ledger_does_not_crash_the_summary():
    axes = usage_breakdown(None)
    assert axes["records"] == 0
    ctx = _Ctx([])
    ctx.run_usage = None
    assert summarize_run(ctx)["usage_axes"]["records"] == 0


def test_existing_summary_fields_are_preserved():
    """§11.5: this extends the contract; it must not break the old one."""
    ctx = _Ctx([_Finding()])
    ctx.run_usage = _usage(_rec())
    summary = summarize_run(ctx)
    for key in ("sheets", "findings_total", "anchor_tiers", "verification",
                "confidence", "by_model", "estimated_cost_usd", "qc_status"):
        assert key in summary, key
    # per-model cost and the confidence tally were already there and stay.
    assert "cost" in summary["by_model"]["claude-opus-5"]
    assert set(summary["confidence"]) >= set(CONFIDENCE_LEVELS)


# --------------------------------------------------------------------------- #
# WP-06 §11.4 — typed geometry, validated before anything costly
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw,expected", [
    (None, None), ("", None), ("0", 0.0), ("0.08", 0.08), ("0.5", 0.5),
    ("0.1234", 0.1234),
])
def test_valid_overlaps_are_accepted(raw, expected):
    assert parse_overlap(raw, label="--x") == expected


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "NaN", "Infinity"])
def test_non_finite_overlaps_are_rejected(raw):
    """They survive ``float()``, reach tiling, and — worse — produce a *stable*
    cache key: ``f"{float('nan'):.4f}"`` is ``"nan"``."""
    with pytest.raises(ValueError, match="finite"):
        parse_overlap(raw, label="--variant-overlap")


@pytest.mark.parametrize("raw", ["-0.01", "0.51", "1.0", "100"])
def test_out_of_range_overlaps_are_rejected(raw):
    with pytest.raises(ValueError, match="range"):
        parse_overlap(raw, label="--variant-overlap")


@pytest.mark.parametrize("raw", ["0.12345", "0.080001", "0.000001"])
def test_overlaps_finer_than_the_render_identity_are_rejected(raw):
    """The identity is ``f"overlap={overlap_frac:.4f}"``.

    Two values differing in the fifth decimal render different pixels and share a
    level-1 cache key — so one arm would be scored against the other's cached
    renders. Rejecting is the honest response; silently rounding would run an
    experiment the operator did not ask for under the label they typed.
    """
    with pytest.raises(ValueError, match="decimal places"):
        parse_overlap(raw, label="--variant-overlap")


def test_distinct_accepted_overlaps_produce_distinct_render_identities():
    """The flip side: an accepted pair must actually be distinguishable."""
    from drawing_analyzer import tiling

    a, b = parse_overlap("0.0800", label="--x"), parse_overlap("0.0801", label="--y")
    assert f"overlap={a:.4f}" != f"overlap={b:.4f}"
    # ...and they really do tile differently.
    assert (tiling.tile_rects(2448.0, 3168.0, overlap_frac=a)[0].width
            != tiling.tile_rects(2448.0, 3168.0, overlap_frac=b)[0].width)


def test_an_overlap_only_experiment_is_expressible():
    """The old whole-environment guard could not express this at all."""
    same_env = {"DRAWING_ANALYZER_MODEL": "claude-opus-5"}
    a = ArmSpec(env=same_env, overlap_frac=0.04)
    b = ArmSpec(env=same_env, overlap_frac=0.16)
    assert a.identity() != b.identity()


def test_identical_reviewed_configuration_is_still_rejected():
    a = ArmSpec(env={"X": "1"}, overlap_frac=0.08)
    b = ArmSpec(env={"X": "1"}, overlap_frac=0.08)
    assert a.identity() == b.identity()


def test_the_arm_label_names_the_overlap_and_still_redacts_secrets():
    spec = ArmSpec(env={"ANTHROPIC_API_KEY": _FAKE_KEY}, overlap_frac=0.16)
    label = spec.label()
    assert "overlap=0.16" in label
    assert _FAKE_KEY not in label and "[REDACTED]" in label
    assert ArmSpec(env={}).label() == "defaults"


def test_the_resolved_overlap_is_recorded_not_the_spelling(monkeypatch):
    """§11.4: record resolved values. An omitted option is the shipping default."""
    from drawing_analyzer import tiling

    import ab_sweep_drawing_analyzer as mod

    omitted = mod.resolve_arm_configuration(exhaustive=True)
    assert omitted["overlap_frac"] == tiling.DEFAULT_OVERLAP_FRAC
    assert omitted["overlap_overridden"] is False

    given = mod.resolve_arm_configuration(exhaustive=True, overlap_frac=0.16)
    assert given["overlap_frac"] == 0.16 and given["overlap_overridden"] is True


def test_overlap_reaches_both_children_as_the_same_argument(monkeypatch):
    """§11.5: estimate and execution must render/price the same geometry."""
    seen = {}

    class _P:
        returncode = 0
        stdout = '{"low_cost": 1.0, "high_cost": 1.0}'
        stderr = ""

    def _fake_run(cmd, **kw):
        seen.setdefault("cmds", []).append(cmd)
        return _P()

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _fake_run)
    estimate_arm("x", {}, 4, 1, exhaustive=True, overlap_frac=0.16)
    assert "--overlap" in seen["cmds"][0]
    assert "0.16" in seen["cmds"][0]

    # ...and omitting it passes nothing, so the pipeline default stands.
    seen["cmds"].clear()
    estimate_arm("x", {}, 4, 1, exhaustive=True)
    assert "--overlap" not in seen["cmds"][0]


def test_the_execution_child_forwards_overlap_to_the_pipeline(tmp_path, monkeypatch):
    seen = {}

    class _P:
        returncode = 0

    def _fake_run(cmd, **kw):
        seen["cmd"] = cmd
        (tmp_path / "arm_x.json").write_text("{}", encoding="utf-8")
        return _P()

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _fake_run)
    run_arm("x", {}, [tmp_path / "a.pdf"], tmp_path, exhaustive=True, overlap_frac=0.04)
    assert "--overlap" in seen["cmd"] and "0.04" in seen["cmd"]


def test_an_invalid_overlap_fails_before_any_child_is_spawned(monkeypatch):
    """§11.5: cheap validation must precede costly work."""
    from ab_sweep_drawing_analyzer import main

    def _explode(*a, **k):
        raise AssertionError("a child was spawned despite an invalid argument")

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _explode)
    with pytest.raises(SystemExit):
        main(["--pdf", __file__, "--variant-overlap", "0.123456", "--estimate"])


# --------------------------------------------------------------------------- #
# Review round: three defects, one of them in production pricing
# --------------------------------------------------------------------------- #


def test_cache_only_usage_under_an_unknown_model_poisons_the_total():
    """The sharpest form: a complete-looking figure that omits real spend.

    Cache tokens are billable usage priced as multipliers on the input rate, and
    the predicate that decides "unknown price means no dollar figure" did not
    look at them. A run with one $5.00 digest beside a record carrying 180k cache
    tokens under an unpriceable model reported **$5.00** — which is exactly the
    failure ``total_estimated_cost``'s own docstring says it prevents.

    Found through the A/B harness's copy of the rule; the copy is gone and the
    harness calls the production predicate, so the two views cannot disagree
    about what was spent.
    """
    ru = _usage(
        _rec(estimated_cost=Decimal("5.00")),
        _rec(stage_family="critique", model="mystery", input_tokens=0,
             output_tokens=0, cache_read_tokens=90_000,
             cache_write_tokens=90_000, estimated_cost=None),
    )
    assert ru.total_estimated_cost is None
    assert usage_breakdown(ru)["unpriced_records"] == 1


@pytest.mark.parametrize("field", ["cache_read_tokens", "cache_write_tokens"])
def test_either_cache_token_kind_counts_as_billable_usage(field):
    r = _rec(input_tokens=0, output_tokens=0, estimated_cost=None, **{field: 1})
    assert RunUsage.is_billable_but_unpriced(r) is True


def test_a_genuinely_free_cache_hit_still_does_not_poison_the_total():
    """The other half: a zero-token served hit is not unpriced usage."""
    ru = _usage(
        _rec(estimated_cost=Decimal("5.00")),
        _rec(model="mystery", transport="CACHE", cache_hit=True, input_tokens=0,
             output_tokens=0, estimated_cost=None),
    )
    assert float(ru.total_estimated_cost) == 5.00
    assert usage_breakdown(ru)["unpriced_records"] == 0


def test_the_harness_does_not_reimplement_the_billable_rule():
    """Two copies of a pricing rule is how the two views drifted apart."""
    import ast
    import inspect

    import ab_sweep_drawing_analyzer as mod

    tree = ast.parse(inspect.getsource(mod.usage_breakdown))
    assert any(
        isinstance(n, ast.Attribute) and n.attr == "is_billable_but_unpriced"
        for n in ast.walk(tree)
    ), "usage_breakdown must call the production predicate, not restate it"


def test_a_request_that_never_got_a_response_is_failed_not_parse_failed():
    """``parse_failed`` means tokens were spent on something unusable.

    A request that raised before any response also carries
    ``parse_success=False`` — there was nothing to parse — and the pipeline pairs
    it with ``terminal_status="FAILED"`` and zero tokens. Sweeping those into
    ``parse_failed`` emptied the ``failed`` bucket and inverted the one question
    these buckets answer: unusable answers, or no answers? Those call for
    opposite responses.
    """
    ru = _usage(_rec(parse_success=False, terminal_status="FAILED",
                     input_tokens=0, output_tokens=0, estimated_cost=Decimal("0")))
    assert usage_breakdown(ru)["by_outcome"]["failed"] == 1
    assert usage_breakdown(ru)["by_outcome"]["parse_failed"] == 0


def test_a_response_that_arrived_and_could_not_be_parsed_is_parse_failed():
    """The case the bucket is for: real tokens, unusable output."""
    ru = _usage(_rec(parse_success=False, terminal_status="COMPLETE",
                     input_tokens=1000, output_tokens=50))
    assert usage_breakdown(ru)["by_outcome"]["parse_failed"] == 1
    assert usage_breakdown(ru)["by_outcome"]["failed"] == 0


def test_an_abandoned_attempt_still_outranks_both():
    ru = _usage(_rec(terminal_status="ABANDONED_EXPIRED", parse_success=False,
                     input_tokens=0, output_tokens=0, estimated_cost=Decimal("0")))
    assert usage_breakdown(ru)["by_outcome"]["abandoned"] == 1


def test_the_guard_compares_resolved_settings_not_the_spelling():
    """An omitted option and an explicit default are the same experiment.

    `(env, None)` vs `(env, 0.08)` differ as raw options while rendering
    identically — so the guard would wave through two identical billable runs,
    which is the very bug it exists to prevent, in a new dress.
    """
    from drawing_analyzer import tiling

    omitted = ArmSpec(env={"X": "1"}, overlap_frac=None)
    explicit = ArmSpec(env={"X": "1"}, overlap_frac=tiling.DEFAULT_OVERLAP_FRAC)
    assert omitted.identity() == explicit.identity()
    assert omitted.resolved_overlap == tiling.DEFAULT_OVERLAP_FRAC


def test_a_real_overlap_difference_is_still_an_experiment():
    """The fix must not make every arm identical."""
    assert (ArmSpec(env={}, overlap_frac=0.04).identity()
            != ArmSpec(env={}).identity())
    assert (ArmSpec(env={}, overlap_frac=0.04).identity()
            != ArmSpec(env={}, overlap_frac=0.16).identity())


def test_an_explicit_default_overlap_pair_is_rejected_end_to_end(monkeypatch):
    """Through `main`, so the guard is exercised where it actually runs."""
    from ab_sweep_drawing_analyzer import main

    def _explode(*a, **k):
        raise AssertionError("a child was spawned for two identical arms")

    monkeypatch.setattr("ab_sweep_drawing_analyzer.subprocess.run", _explode)
    with pytest.raises(SystemExit):
        main(["--pdf", __file__, "--variant-overlap", "0.08", "--estimate"])


# --------------------------------------------------------------------------- #
# WP-06 §11.3 — comparison validity and evidence-trust composition
# --------------------------------------------------------------------------- #


class _TrustFinding(_Finding):
    """A fake finding that also carries WP-03B grounding state and legs."""

    def __init__(self, *, evidence_state="", legs=(), **kw):
        super().__init__(**kw)
        self.evidence_state = evidence_state
        self.also_on = [_Leg(s) for s in legs]


class _Leg:
    def __init__(self, evidence_state=""):
        self.evidence_state = evidence_state


def test_clean_arms_are_comparable_and_may_claim_a_saving():
    base, var = _arms([_Finding() for _ in range(10)],
                      [_Finding() for _ in range(10)])
    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_COMPARABLE
    assert v["savings_claim_allowed"] is True
    assert v["blocking"] == [] and v["qualifiers"] == []


def test_a_failed_arm_never_gets_a_comparable_savings_verdict():
    """A cheaper arm that did not finish is not a cheaper way to do the work.

    This is the misreading that actually gets acted on: the failed arm's total
    is genuinely lower, every rate looks fine, and adopting it ships a variant
    that cannot complete a run.
    """
    base, var = _arms([_Finding() for _ in range(10)],
                      [_Finding() for _ in range(10)],
                      base_cost=10.0, var_cost=2.0)
    var["qc_status"] = "FAILED"
    v = comparison_validity(base, var)

    assert v["status"] == VALIDITY_NOT_COMPARABLE
    assert v["savings_claim_allowed"] is False
    assert any("FAILED" in b for b in v["blocking"])

    d = diff_summaries(base, var)
    concerns = " ".join(d["verdict"]["concerns"])
    assert "NOT comparable" in concerns
    assert "not a saving" in concerns
    report = render_diff(d, base_label="base", var_label="var")
    assert "COMPARISON VALIDITY: NOT_COMPARABLE" in report
    assert "is NOT a saving" in report


def test_fewer_sheets_read_blocks_comparison():
    """Fewer sheets read is a smaller job, not a cheaper one."""
    base = summarize_run(_Ctx([_Finding()]))
    var = summarize_run(_Ctx([_Finding()], sheets=[
        _Sheet(page_index=0), _Sheet(page_index=1),
        _Sheet(page_index=2, ok=False), _Sheet(page_index=3, ok=False),
    ]))
    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_NOT_COMPARABLE
    assert any("different populations" in b for b in v["blocking"])


def test_equal_sheet_counts_over_different_sheets_still_blocks():
    """The count is not the population.

    Baseline reads {p0, p1, p2}, variant reads {p0, p1, p3} — one transient
    failure each, which is ordinary on a two-arm run. Both report ok_sheets=3,
    so a count check passes. Every finding on p2 then reads as something the
    variant missed and every finding on p3 as something it found, attributing a
    population difference to the tested model or geometry change.
    """
    base = summarize_run(_Ctx([_Finding()], sheets=[
        _Sheet(page_index=0), _Sheet(page_index=1),
        _Sheet(page_index=2), _Sheet(page_index=3, ok=False),
    ]))
    var = summarize_run(_Ctx([_Finding()], sheets=[
        _Sheet(page_index=0), _Sheet(page_index=1),
        _Sheet(page_index=2, ok=False), _Sheet(page_index=3),
    ]))
    assert base["ok_sheets"] == var["ok_sheets"] == 3      # the count agrees

    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_NOT_COMPARABLE
    assert v["savings_claim_allowed"] is False
    blocking = " ".join(v["blocking"])
    assert "different populations" in blocking
    assert "only in baseline: SRC-0001:p2" in blocking
    assert "only in variant: SRC-0001:p3" in blocking


def test_identical_sheet_populations_do_not_block():
    base, var = _arms([_Finding()], [_Finding()])
    assert base["ok_sheet_ids"] == var["ok_sheet_ids"]
    assert comparison_validity(base, var)["status"] == VALIDITY_COMPARABLE


def test_a_summary_without_sheet_ids_falls_back_to_the_count():
    """An arm summary written before ``ok_sheet_ids`` existed still compares.

    Additive serialization: an older payload keeps working, at the weaker check
    it was always getting, rather than silently skipping the check entirely.
    """
    base, var = _arms([_Finding()], [_Finding()])
    del base["ok_sheet_ids"]
    var["ok_sheets"] = 2
    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_NOT_COMPARABLE
    assert any("successfully-read sheets differ" in b for b in v["blocking"])


def test_missing_cost_data_blocks_the_comparison_in_both_directions():
    base, var = _arms([_Finding()], [_Finding()])
    var["estimated_cost_usd"] = None
    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_NOT_COMPARABLE
    assert v["savings_claim_allowed"] is False


def test_partial_arm_is_qualified_not_silently_comparable():
    """PARTIAL is a caveat that must ride with every number, not a blocker.

    Collapsing it into NOT_COMPARABLE would put most real sweeps in the
    unreadable bucket, which is how a validity field stops being read at all.
    """
    base, var = _arms([_Finding()], [_Finding()])
    var["qc_status"] = "PARTIAL"
    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_QUALIFIED
    assert v["savings_claim_allowed"] is False
    assert any("PARTIAL" in q for q in v["qualifiers"])


def test_unpriced_records_qualify_the_total_as_a_floor():
    base, var = _arms([_Finding()], [_Finding()])
    var["usage_axes"] = {"unpriced_records": 3, "by_outcome": {}}
    v = comparison_validity(base, var)
    assert v["status"] == VALIDITY_QUALIFIED
    assert any("floor, not a total" in q for q in v["qualifiers"])


def test_summary_reports_evidence_trust_composition():
    s = summarize_run(_Ctx([
        _TrustFinding(evidence_state="TEXT_GROUNDED", verify="VERIFIED"),
        _TrustFinding(evidence_state="TEXT_EVIDENCE_UNAVAILABLE",
                      verify="UNCERTAIN",
                      legs=("TEXT_EVIDENCE_UNAVAILABLE",)),
    ]))
    trust = s["evidence_trust"]
    assert trust["units"] == 3                   # 2 findings + 1 leg
    assert trust["grounded_verified_units"] == 1
    assert trust["reduced_trust_unverified_units"] == 2


def test_an_arm_cannot_be_called_equivalent_on_count_alone():
    """Same count, same severity mix — different evidence underneath.

    §11.3: an arm whose finding count held up on reduced-trust, unverified legs
    is not equivalent to one that was text-grounded and verified. Every
    aggregate table in this report shows these two arms as identical.
    """
    base = [_TrustFinding(evidence_state="TEXT_GROUNDED", verify="VERIFIED")
            for _ in range(10)]
    var = [_TrustFinding(evidence_state="TEXT_EVIDENCE_UNAVAILABLE",
                         verify="UNCERTAIN") for _ in range(10)]
    b, v = _arms(base, var)
    assert b["findings_total"] == v["findings_total"]
    assert b["findings_by_severity"] == v["findings_by_severity"]

    d = diff_summaries(b, v)
    concerns = " ".join(d["verdict"]["concerns"])
    assert "reduced-trust unverified evidence rose" in concerns
    assert "not equivalent" in concerns
    assert d["evidence_trust"]["by_state"]["TEXT_GROUNDED"]["delta"] == -10

    report = render_diff(d, base_label="base", var_label="var")
    assert "evidence trust (per grounded unit)" in report
    assert "grounded AND verified" in report


def test_a_flat_count_is_a_note_not_a_concern():
    """The most ordinary outcome must not fill the concern list.

    It still gets said — a flat total can hide one real issue replaced by one
    false positive — but as a note, so "a signal degraded" stays a rare event.
    """
    findings = [_Finding() for _ in range(10)]
    d = diff_summaries(*_arms(findings, [_Finding() for _ in range(10)]))
    assert d["verdict"]["clean_screen"] is True
    assert d["verdict"]["screen_result"] == "NO_CONCERNS_DETECTED"
    notes = " ".join(d["verdict"]["notes"])
    assert "NOT evidence the same issues were found" in notes
    assert "findings_diff.json" in notes


def test_screen_result_has_no_approval_value():
    """"No concerns detected" must stay distinct from "quality approved"."""
    d = diff_summaries(*_arms([_Finding()], [_Finding()]))
    assert d["verdict"]["screen_result"] == "NO_CONCERNS_DETECTED"
    report = render_diff(d, base_label="base", var_label="var")
    assert "NOT an approval" in report
    # No spelling of "approved" anywhere: the screen has no value that means it,
    # and a reader skimming for one must not find a word that looks like it.
    assert "approve" not in report.lower().replace("not an approval", "")
    assert "screen found nothing" in report


def test_findings_sidecar_sits_beside_its_arm_summary(tmp_path):
    assert _findings_path(tmp_path / "arm_baseline.json").name == \
        "arm_baseline_findings.json"


def test_a_missing_or_corrupt_sidecar_reports_its_status_not_just_emptiness(tmp_path):
    """An empty list cannot say whether the sidecar was read.

    Missing, unreadable and "read fine, no findings" all hand back ``[]``. If
    the caller can only see the list, a missing baseline sidecar turns every
    variant record into a one-sided difference — a comparison result
    manufactured out of a failed file read — so the status is returned beside
    the records rather than inferred from them.
    """
    arm = tmp_path / "arm_baseline.json"
    assert load_arm_records(arm) == (RECORDS_MISSING, [])

    _findings_path(arm).write_text("{not json", encoding="utf-8")
    assert load_arm_records(arm) == (RECORDS_UNREADABLE, [])

    # Valid JSON, wrong shape: still unreadable, not "an arm with no findings".
    _findings_path(arm).write_text('["nope"]', encoding="utf-8")
    assert load_arm_records(arm) == (RECORDS_UNREADABLE, [])

    # Read fine, genuinely no findings — distinct from every case above.
    _findings_path(arm).write_text(
        json.dumps({"contract_version": RECORD_CONTRACT_VERSION, "records": []}),
        encoding="utf-8",
    )
    assert load_arm_records(arm) == (RECORDS_PRESENT, [])

    _findings_path(arm).write_text(
        json.dumps({"contract_version": RECORD_CONTRACT_VERSION,
                    "records": [{"finding_id": "abc"}]}),
        encoding="utf-8",
    )
    assert load_arm_records(arm) == (RECORDS_PRESENT, [{"finding_id": "abc"}])


def test_a_sidecar_from_a_different_contract_is_refused_not_compared(tmp_path):
    """Records that parse perfectly and mean something else are the worst case.

    ``critical_signature`` is computed at ARM-RUN time and stored inside each
    record, and the comparison re-applies ``signatures_compatible`` to those
    stored dicts rather than recomputing them. So an arm produced before a
    signature-rule change is scored under a rule it never ran with, and the
    resulting differences get reported as if the arm's model or geometry swap
    caused them — a comparison result manufactured out of a code change.

    The version was written into every sidecar and echoed into every comparison
    from the start, and read back by nobody; the contract its own comment
    describes was declarative only until it was enforced here.

    Refusing beats warning because the failure is SILENT: every reader uses
    ``.get(...) or {}``, and a one-sided signal never blocks a match, so a stale
    record whose measurements simply vanished degrades toward "exact match".
    """
    arm = tmp_path / "arm_baseline.json"
    records = [{"finding_id": "abc", "critical_signature": {"measurements": ["2in"]}}]

    _findings_path(arm).write_text(
        json.dumps({"contract_version": RECORD_CONTRACT_VERSION - 1, "records": records}),
        encoding="utf-8",
    )
    assert load_arm_records(arm) == (RECORDS_STALE_CONTRACT, [])

    # A sidecar with NO version predates the field, which is strictly older than
    # the current contract — stale, never "current by default".
    _findings_path(arm).write_text(json.dumps({"records": records}), encoding="utf-8")
    assert load_arm_records(arm) == (RECORDS_STALE_CONTRACT, [])

    # And the status is a fourth value, not a flavour of UNREADABLE: the sidecar
    # read perfectly, which is exactly what makes it dangerous.
    assert RECORDS_STALE_CONTRACT not in (RECORDS_UNREADABLE, RECORDS_MISSING,
                                          RECORDS_PRESENT)


def test_the_records_envelope_round_trips_between_the_child_and_the_parent(tmp_path):
    """The writer runs in the arm child, the reader in the parent.

    Two hand-written JSON literals across a process boundary is exactly where a
    key rename goes unnoticed: the parent would report "no records" for an arm
    that produced hundreds, and the finding-level comparison would silently
    become a no-op on a run that already cost real money.
    """
    arm = tmp_path / "arm_variant.json"
    records = [{"finding_id": "abc123", "identity_key": "deadbeef"}]
    written = write_arm_records(arm, records)
    assert written == _findings_path(arm)
    assert load_arm_records(arm) == (RECORDS_PRESENT, records)
