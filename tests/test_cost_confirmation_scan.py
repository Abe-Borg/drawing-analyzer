"""WP-05 §10.3/§10.4 — pricing the confirmation from pages already measured.

§10.3 is a *measurement* step before a design step, and the measurement
(`scripts/measure_scan_time.py`, this machine, medians of 3) chose the design:

    120 sheets x 4,000 words
      fresh cost scan                 6,896 ms
      wait behind a running preflight 22,457 ms   (it also hashes render identity)
      derive from the preflight's own geometry        0.4 ms   (0.01%)

The scan cost tracks **word count**, not sheet count — ~15 ms per 1,000 words
across every configuration measured — which is why "0.32 s / 8 sheets" was never
a bound: a dense schedule set is 20x the words of a sparse one at the same sheet
count. (That figure does reproduce: 48.4 ms/1k words x 6.636k words = 321 ms
against the 320 ms recorded in `render.py`.)

So §10.3 Step 2's default design — "run the improved scan once, at the Analyze
click" — is measurably the wrong choice on a large dense set: a 6.9-second
freeze at the moment money is committed. Item 3's "prefer **reusing** its
results" is the right one, and it is nearly free because `preflight_sheet_ids`
already built the geometry and threw it away.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer.cost import (
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
    format_drawing_cost_prompt,
    format_exhaustive_cost_prompt,
)
from drawing_analyzer.models import (
    CLASSIFICATION_VECTOR,
    SheetCostBasis,
)

OPUS = "claude-opus-5"


def bases(n: int, *, shape=(34, 44)) -> list[SheetCostBasis]:
    w, h = shape
    return [
        SheetCostBasis(source_name="set.pdf", page_index=i,
                       width_pt=w * 72.0, height_pt=h * 72.0,
                       classification=CLASSIFICATION_VECTOR)
        for i in range(n)
    ]


# --------------------------------------------------------------------------- #
# One walk, both products
# --------------------------------------------------------------------------- #


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "set.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page(width=34 * 72, height=44 * 72)
        page.insert_text((72, 72), f"FP-10{i}")
        page.insert_text((72, 96), "PRE-ACTION VALVE SCHEDULE")
    doc.save(str(path))
    doc.close()
    return path


def test_the_preflight_yields_cost_bases_from_the_walk_it_already_makes(sample_pdf):
    from drawing_analyzer.profiles import preflight_scan

    scan = preflight_scan([sample_pdf])
    assert len(scan.cost_bases) == 3
    assert [b.page_index for b in scan.cost_bases] == [0, 1, 2]
    assert all(b.classification == CLASSIFICATION_VECTOR for b in scan.cost_bases)
    assert all(b.width_pt == pytest.approx(34 * 72.0) for b in scan.cost_bases)


def test_the_legacy_entry_point_still_returns_only_ids(sample_pdf):
    """`preflight_sheet_ids` delegates, so there is one walk, not two."""
    from drawing_analyzer.profiles import preflight_scan, preflight_sheet_ids

    assert preflight_sheet_ids([sample_pdf]) == preflight_scan([sample_pdf]).sheet_ids


def test_an_unreadable_source_does_not_sink_the_scan(tmp_path, sample_pdf):
    """Best-effort, exactly as the profile preflight already was."""
    from drawing_analyzer.profiles import preflight_scan

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    scan = preflight_scan([broken, sample_pdf])
    assert len(scan.cost_bases) == 3          # the good file still contributed


# --------------------------------------------------------------------------- #
# The estimators use measured shapes only when they cover the whole set
# --------------------------------------------------------------------------- #


def test_measured_bases_lower_the_estimate_and_are_flagged():
    plain = estimate_drawing_set_cost(10, model=OPUS, batch=False)
    measured = estimate_drawing_set_cost(10, model=OPUS, batch=False, bases=bases(10))
    assert plain.shape_aware is False and measured.shape_aware is True
    assert measured.total_cost < plain.total_cost
    assert measured.image_tokens < plain.image_tokens


def test_a_partial_scan_falls_back_rather_than_blending():
    """Neither figure, and no way to see which sheets were missing.

    A total that mixes three measured sheets with seven conservative ones is not
    a conservative estimate and not a measured one; it is a number whose basis
    varies per sheet and is invisible in the sum.
    """
    partial = estimate_drawing_set_cost(10, model=OPUS, bases=bases(3))
    plain = estimate_drawing_set_cost(10, model=OPUS)
    assert partial.shape_aware is False
    assert partial.image_tokens == plain.image_tokens


def test_more_bases_than_sheets_also_falls_back():
    """A stale scan of a longer file list must not price a shorter one."""
    assert estimate_drawing_set_cost(3, model=OPUS, bases=bases(10)).shape_aware is False


def test_empty_bases_are_the_same_as_none():
    assert estimate_drawing_set_cost(10, model=OPUS, bases=[]).shape_aware is False


def test_the_exhaustive_estimate_uses_measured_shapes_too():
    plain = estimate_exhaustive_run_cost(10, model=OPUS, batch=False)
    measured = estimate_exhaustive_run_cost(10, model=OPUS, batch=False, bases=bases(10))
    assert measured.shape_aware is True and plain.shape_aware is False
    assert measured.low_cost < plain.low_cost
    assert measured.high_cost < plain.high_cost


def test_the_critique_line_is_measured_with_its_own_model(monkeypatch):
    """Set totals are resolved per stage model, not counted once and reused."""
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_MODEL", "claude-haiku-4-5-20251001")
    est = estimate_exhaustive_run_cost(10, model=OPUS, batch=False, bases=bases(10))
    digest = next(c for c in est.components if c.stage == "Digest")
    critique = next(c for c in est.components if c.stage.startswith("Critique"))
    # Two reads of a cheaper-capped model still carry fewer image tokens per read.
    assert critique.input_tokens / 2 < digest.input_tokens


# --------------------------------------------------------------------------- #
# §10.4 — the reader can tell which basis produced the number
# --------------------------------------------------------------------------- #


def test_the_dialog_names_its_basis():
    conservative = format_drawing_cost_prompt(
        estimate_drawing_set_cost(10, model=OPUS, batch=False)
    )
    measured = format_drawing_cost_prompt(
        estimate_drawing_set_cost(10, model=OPUS, batch=False, bases=bases(10))
    )
    assert "Conservative planning estimate" in conservative
    assert "measured size and text layer" in measured
    assert "Conservative planning estimate" not in measured


def test_the_exhaustive_dialog_names_its_basis_too():
    measured = format_exhaustive_cost_prompt(
        estimate_exhaustive_run_cost(10, model=OPUS, batch=False, bases=bases(10))
    )
    assert "measured size and text layer" in measured


def test_a_measured_dialog_does_not_call_its_figure_a_worst_case():
    """That sentence describes the allowance, and is false once pages are measured."""
    measured = format_drawing_cost_prompt(
        estimate_drawing_set_cost(10, model=OPUS, batch=False, bases=bases(10))
    )
    assert "per-model worst case" not in measured
    assert "comes from the pages themselves" in measured
    # ...but the honest caveat survives in both.
    assert "not a cap" in measured


def test_no_dialog_claims_a_confidence_interval_or_a_maximum():
    """§10.4: do not label a hypothetical range as either."""
    for text in (
        format_drawing_cost_prompt(estimate_drawing_set_cost(10, model=OPUS)),
        format_drawing_cost_prompt(
            estimate_drawing_set_cost(10, model=OPUS, bases=bases(10))),
        format_exhaustive_cost_prompt(estimate_exhaustive_run_cost(10, model=OPUS)),
        format_exhaustive_cost_prompt(
            estimate_exhaustive_run_cost(10, model=OPUS, bases=bases(10))),
    ):
        lowered = text.lower()
        assert "confidence interval" not in lowered
        assert "guaranteed" not in lowered
        assert "maximum" not in lowered
        assert "not a cap" in lowered


def test_the_confirmation_question_is_still_asked():
    """§10.3/§10.4: the pre-send confirmation behaviour is unchanged."""
    text = format_drawing_cost_prompt(
        estimate_drawing_set_cost(10, model=OPUS, bases=bases(10))
    )
    assert "Nothing is sent until you confirm." in text
    assert text.rstrip().endswith("Proceed with the analysis?")


# --------------------------------------------------------------------------- #
# §10.5 GUI cases — the staleness guard, tested where the logic lives
# --------------------------------------------------------------------------- #
#
# `tkinter` is not importable in this environment and the repo ships no GUI test
# harness, so these drive the real methods against a stub `self` carrying only
# the attributes they touch. That is deliberate rather than a workaround: the
# behaviour under test is the generation guard and the bases lifetime, neither of
# which involves a widget. The parts that do need a window — cancellation, window
# close, rapid file replacement — are in the Windows manual checklist
# (`docs/WINDOWS_MANUAL_ACCEPTANCE.md`), which is where the plan puts them.


def test_the_stale_guard_precedes_the_bases_assignment():
    """The generation guard must gate the bases, not run beside them.

    `gui.py` cannot be imported here or in CI — it needs `tkinter` and the `gui`
    extras, neither of which the test job installs — so this reads the source
    instead of executing it. That is a real limitation and worth naming: it
    catches the ordering defect it targets (assigning `_preflight_bases` before
    the `gen != self._preflight_gen` early return, which would let a superseded
    scan of a *different* file list price the current one) and it would not catch
    a defect in what the surrounding widget code does with the result. The cases
    that genuinely need a window — cancellation, window close, rapid file
    replacement — are in `docs/WINDOWS_MANUAL_ACCEPTANCE.md`, which is where the
    plan puts them.
    """
    import ast

    src = Path(__file__).resolve().parent.parent / "src" / "drawing_analyzer" / "gui.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_apply_profile_suggestions"
    )
    guard_line = next(
        node.lineno for node in ast.walk(fn)
        if isinstance(node, ast.Return) and node.value is None
    )
    assign_line = next(
        node.lineno for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_preflight_bases"
            for t in node.targets
        )
    )
    assert guard_line < assign_line, (
        "_preflight_bases is assigned before the stale-generation guard returns, "
        "so a superseded scan would price the current file list"
    )


def test_a_new_preflight_clears_the_previous_sets_bases():
    """Cleared at kick-off, not at apply time.

    Between starting a scan for the new selection and its result arriving, the
    bases on hand describe the *old* files. Holding them until the new result
    lands means the dialog can price the new selection with the old set's shapes
    — measured-looking, and about different drawings.
    """
    import ast

    src = Path(__file__).resolve().parent.parent / "src" / "drawing_analyzer" / "gui.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_refresh_profile_suggestions"
    )
    cleared = [
        node for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_preflight_bases"
            for t in node.targets
        )
        and isinstance(node.value, ast.Constant) and node.value.value is None
    ]
    assert cleared, "_refresh_profile_suggestions must drop the previous set's bases"


def test_the_estimate_path_never_constructs_a_client(monkeypatch):
    """§10.5: no request or upload before the existing confirmation.

    The estimators are pure arithmetic over the basis records, but that is the
    kind of property that stops being true by accident, so it is pinned.
    """
    def _explode(*a, **k):
        raise AssertionError("cost preview constructed an API client")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _explode)
    monkeypatch.setattr("drawing_analyzer.client.Anthropic", _explode)
    assert estimate_drawing_set_cost(10, model=OPUS, bases=bases(10)).total_cost > 0
    assert estimate_exhaustive_run_cost(10, model=OPUS, bases=bases(10)).low_cost > 0


def test_the_preflight_scan_makes_no_api_call(sample_pdf, monkeypatch):
    from drawing_analyzer.profiles import preflight_scan

    def _explode(*a, **k):
        raise AssertionError("preflight constructed an API client")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _explode)
    assert len(preflight_scan([sample_pdf]).cost_bases) == 3


# --------------------------------------------------------------------------- #
# Review round: the label must match what was actually measured
# --------------------------------------------------------------------------- #


def test_one_unreadable_page_stops_the_measured_claim():
    """`estimate_image_tokens_for_bases` already substitutes the conservative
    allowance for a page it cannot read — which is right, and better than
    discarding a whole scan over one bad page. But the resulting figure is then
    only *partly* measured, and the dialog's "based on each page's measured size"
    would be false for that page.

    `ImageTokenEstimate.fully_measured` is the honest predicate; deriving the
    label from list length alone was the defect.
    """
    from drawing_analyzer.models import CLASSIFICATION_UNKNOWN

    mixed = bases(9) + [
        SheetCostBasis(source_name="set.pdf", page_index=9, width_pt=0.0,
                       height_pt=0.0, classification=CLASSIFICATION_UNKNOWN,
                       geometry_ok=False, error="could not measure page")
    ]
    est = estimate_drawing_set_cost(10, model=OPUS, bases=mixed)
    assert est.shape_aware is False
    assert est.unmeasured_pages == 1
    # ...and the number still uses the nine pages it could measure.
    assert est.image_tokens < estimate_drawing_set_cost(10, model=OPUS).image_tokens


def test_a_partly_measured_set_says_so_rather_than_claiming_either_extreme():
    """Three states, each true of what it describes."""
    from drawing_analyzer.models import CLASSIFICATION_UNKNOWN

    mixed = bases(9) + [
        SheetCostBasis(source_name="set.pdf", page_index=9, width_pt=0.0,
                       height_pt=0.0, classification=CLASSIFICATION_UNKNOWN,
                       geometry_ok=False)
    ]
    text = format_drawing_cost_prompt(
        estimate_drawing_set_cost(10, model=OPUS, batch=False, bases=mixed)
    )
    assert "except 1 page(s) that could not be read" in text
    # Neither of the two absolute claims.
    assert "Conservative planning estimate" not in text
    assert text.count("Based on each page's measured size and text layer.") == 0


def test_the_exhaustive_dialog_reports_the_partial_case_too():
    from drawing_analyzer.models import CLASSIFICATION_UNKNOWN

    mixed = bases(9) + [
        SheetCostBasis(source_name="set.pdf", page_index=9, width_pt=0.0,
                       height_pt=0.0, classification=CLASSIFICATION_UNKNOWN,
                       geometry_ok=False)
    ]
    text = format_exhaustive_cost_prompt(
        estimate_exhaustive_run_cost(10, model=OPUS, batch=False, bases=mixed)
    )
    assert "except 1 page(s) that could not be read" in text


def test_a_fully_measured_set_still_claims_it():
    est = estimate_drawing_set_cost(10, model=OPUS, bases=bases(10))
    assert est.shape_aware is True and est.unmeasured_pages == 0
    assert "measured size and text layer." in format_drawing_cost_prompt(est)


# --------------------------------------------------------------------------- #
# Review round: bases must describe the files as they are on disk NOW
# --------------------------------------------------------------------------- #


def test_the_fingerprint_gate_and_the_summary_refresh_are_wired():
    """`gui.py` is unimportable here and in CI (needs tkinter + the gui extras),
    so this reads the source. Stated limits, same as the staleness tests above:
    it pins that both estimate call sites go through the validity gate and that
    the summary re-renders once bases land, and it would not catch a defect in
    what the gate itself computes — which is why `_sources_fingerprint` is
    exercised directly below.
    """
    import ast

    src = Path(__file__).resolve().parent.parent / "src" / "drawing_analyzer" / "gui.py"
    text = src.read_text(encoding="utf-8")
    tree = ast.parse(text)

    # Every consumer goes through the gate; none reads the raw attribute.
    gate_calls = sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_usable_preflight_bases"
    )
    assert gate_calls >= 2, "both the summary and the confirmation must use the gate"

    apply_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_apply_profile_suggestions"
    )
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_refresh_summary"
        for n in ast.walk(apply_fn)
    ), "installing bases must refresh the summary, or the measured figure only appears by accident"


def test_a_rewritten_file_changes_the_fingerprint(tmp_path):
    """The case the generation counter cannot see: same selection, new bytes.

    Re-exporting a set over the same filenames is ordinary practice, and the old
    bases would otherwise price the previous revision while the dialog claimed to
    have measured the current pages.

    Lives in `source_registry`, not `gui`, precisely so it can be executed rather
    than read: it is pure path/stat logic with no widget in it, and the first
    version of this test could not run at all because `gui.py` needs `tkinter`.
    """
    import os
    import time

    from drawing_analyzer.source_registry import sources_fingerprint

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\nfirst revision\n")
    before = sources_fingerprint([pdf])

    pdf.write_bytes(b"%PDF-1.7\nsecond revision, longer\n")
    later = time.time_ns() + 1_000_000_000
    os.utime(pdf, ns=(later, later))
    assert sources_fingerprint([pdf]) != before


def test_a_same_size_rewrite_is_still_caught_by_mtime(tmp_path):
    """The interesting half: a re-export with byte-identical length.

    Page count is unchanged too, so nothing upstream of this notices — which is
    exactly why the length check alone was insufficient.
    """
    import os
    import time

    from drawing_analyzer.source_registry import sources_fingerprint

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\nrevision A\n")
    before = sources_fingerprint([pdf])
    pdf.write_bytes(b"%PDF-1.7\nrevision B\n")   # same length
    later = time.time_ns() + 1_000_000_000
    os.utime(pdf, ns=(later, later))
    after = sources_fingerprint([pdf])
    assert before[0][1] == after[0][1], "precondition: identical size"
    assert before != after


def test_an_unchanged_file_keeps_its_fingerprint(tmp_path):
    """The gate must not reject a set nobody touched — that would make the
    measured path unreachable in practice."""
    from drawing_analyzer.source_registry import sources_fingerprint

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    assert sources_fingerprint([pdf]) == sources_fingerprint([pdf])


def test_a_deleted_or_unreadable_file_still_fingerprints(tmp_path):
    """It must not raise: a set containing one bad file still needs comparing."""
    from drawing_analyzer.source_registry import sources_fingerprint

    pdf = tmp_path / "set.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    before = sources_fingerprint([pdf])
    pdf.unlink()
    after = sources_fingerprint([pdf])
    assert after != before
    assert after == ((str(pdf), None, None),)


def test_reordering_or_adding_files_changes_the_fingerprint(tmp_path):
    from drawing_analyzer.source_registry import sources_fingerprint

    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"%PDF-1.7\na\n")
    b.write_bytes(b"%PDF-1.7\nbb\n")
    assert sources_fingerprint([a, b]) != sources_fingerprint([b, a])
    assert sources_fingerprint([a]) != sources_fingerprint([a, b])
