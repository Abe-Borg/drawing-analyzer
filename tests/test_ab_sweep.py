"""The A/B sweep harness's pure logic: summarize, diff, screen, render.

The harness itself spends real money on real drawings, so what is tested here is
everything up to the API boundary — the record it builds from a finished run, the
comparison, and the screen that decides whether a cost win came at a quality
cost. Those are exactly the parts where a bug would quietly bless a bad change.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ab_sweep_drawing_analyzer import (  # noqa: E402
    _parse_env,
    _pct_delta,
    _tally,
    diff_summaries,
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


class _Ctx:
    def __init__(self, findings, *, cost=1.0, in_tok=1000, out_tok=100):
        self.all_findings = findings
        self.sheet_count = 4
        self.ok_sheet_count = 4
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
    assert "missed findings" in concerns
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
