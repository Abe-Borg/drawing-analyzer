"""Tests for the deterministic auditors (Phase 14).

Pure — synthetic word lists, no PyMuPDF, no network. Word tuples mirror PyMuPDF's
``get_text("words")`` shape: ``(x0, y0, x1, y1, text, block, line, word_no)``.

Covers the four new auditors (arithmetic, naming, title-block, sheet-index), the
``run_auditors`` orchestrator, the no-``eval`` construction guarantee, and the
number-parser fuzz table. Reference-auditor coverage stays in
``test_drawing_reference_audit.py`` (which drives the same code via the shim).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from drawing_analyzer.auditors import run_auditors
from drawing_analyzer.auditors.arithmetic import (
    audit_arithmetic,
    parse_number,
)
from drawing_analyzer.auditors.naming import audit_naming
from drawing_analyzer.auditors.sheet_index import audit_sheet_index
from drawing_analyzer.auditors.titleblock import audit_titleblock
from drawing_analyzer.models import ImageTile, NumericClaim, RenderedSheet, SheetRef

W, H = 3168.0, 2448.0  # E-size-ish page in points


def _w(x, y, text, width=64, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _sheet(source, page, words, *, page_count=1):
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=page_count)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=1, cols=1, words=list(words),
    )


def _titleblock(sheet_id):
    """A title-block ID word placed in the bottom-right corner."""
    return _w(W - 300, H - 160, sheet_id)


# --------------------------------------------------------------------------- #
# Number parser — the fuzz table (units, commas, fractions), NO eval.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        (540, Decimal(540)),
        (3.14, Decimal("3.14")),
        ("540", Decimal(540)),
        ("1,200", Decimal(1200)),
        ("1,200,000", Decimal(1200000)),
        ("1,950 ft²", Decimal(1950)),
        ("165 psi", Decimal(165)),
        ("0.20 gpm/ft²", Decimal("0.20")),
        ("2 1/2", Decimal("2.5")),
        ("1/2", Decimal("0.5")),
        ('2-1/2"', Decimal("2.5")),
        ("-1/2", Decimal("-0.5")),
        ("  42  ", Decimal(42)),
        (".5", Decimal("0.5")),
        ("12' clear", Decimal(12)),          # a unit tail is still just a unit
        ("TOTAL 540", None),                 # no LEADING number -> not a number
    ],
)
def test_parse_number_table(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "$5.00", None, "1/0", True, [1, 2], {"a": 1}])
def test_parse_number_rejects_unparseable(raw):
    assert parse_number(raw) is None


@pytest.mark.parametrize(
    "raw, why",
    [
        ("12,5", "a comma that is not a thousands grouping"),
        ("1.2.3", "a second decimal point"),
        ("12'-6\"", "feet-inches: twelve feet six, not twelve"),
        ("12-6", "a joined pair, not a single value"),
        ("30%", "a ratio, not the quantity (item 25d)"),
        ("30 %", "same, spaced"),
    ],
)
def test_parse_number_rejects_a_number_bound_to_more_number(raw, why):
    # The parser took the leading run and silently dropped the rest, which is the
    # one thing it must not do: the host then computes with a number the sheet
    # never states and inks the result as an exact text check.
    #
    # "12,5" is the sharpest case, because _THOUSANDS_RE deliberately declines to
    # strip that comma so the value is "left alone rather than silently mangled"
    # -- and _PLAIN_NUMBER_RE mangled it anyway, one line later.
    #
    # A rejected term makes its claim UNUSABLE, i.e. reported as unchecked. That
    # is the safe direction: never a mismatch finding built on a misread operand.
    assert parse_number(raw) is None, why


def test_a_percent_operand_cannot_promote_a_claim_to_ground_truth():
    # The nastier half of item 25d. "1500 SF + 30% = 1950 SF" is not "the sum of
    # 1500 and 30" -- but the bare 30 appears literally in the quote, so
    # _operands_supported found every operand present, and the claim cleared the
    # independent-validation gate and inked as DETERMINISTIC / TEXT_EXTRACTED:
    # a HIGH-severity "the product of 1500, 30 is 45000" wearing the host's label.
    from drawing_analyzer.auditors.arithmetic import _numbers_in_text

    assert _numbers_in_text("1500 SF + 30% = 1950 SF") == [Decimal(1500), Decimal(1950)]

    res = audit_arithmetic(
        [NumericClaim(
            sheet_id="FP-101", source_name="fp.pdf", page_index=0,
            kind="product", terms=["1500", "30%"], expected="1950 SF",
            quote="1500 SF + 30% = 1950 SF",
        )],
        [],
    )
    assert res.findings == []          # no finding at all, let alone a trusted one
    assert res.checked == 0 and res.unusable == 1


def test_the_quote_scanner_and_the_operand_parser_never_disagree():
    # §17.5's stated invariant, and the reason the head/tail rules live at the
    # scan site rather than inside parse_number: the scanner is handed surrounding
    # text and the parser only a substring, so only the scanner can see what bound
    # a number. Scanning "12'-6\"" linearly, refusing 12 for its tail and then
    # offering the -6 the scan resumed on would put a quantity in the
    # "present in the quote" set that the quote never states.
    from drawing_analyzer.auditors.arithmetic import _numbers_in_text

    assert _numbers_in_text('12\'-6" CLEAR') == []
    assert parse_number('12\'-6"') is None

    # ...while a genuine column of numbers is untouched. Whitespace is not a
    # binder; the flow-test total is the case this auditor exists for.
    assert _numbers_in_text("20  20  20   TOTAL  540") == [
        Decimal(20), Decimal(20), Decimal(20), Decimal(540),
    ]
    # And a separating space keeps two real quantities apart.
    assert _numbers_in_text('PIPE 2" 150 PSI') == [Decimal(2), Decimal(150)]


def test_an_unprintable_result_does_not_lose_the_run(caplog):
    # _fmt expanded an integral result with quantize(Decimal(1)), which raises
    # InvalidOperation once the expansion needs more digits than the decimal
    # context allows (28). Reachable from ordinary string terms, and it raised
    # INSIDE the Finding(...) constructor expression, so there was no
    # partially-built finding to recover -- audit_arithmetic aborted mid-loop and
    # the caller discarded the whole result.
    huge = NumericClaim(
        sheet_id="FP-101", source_name="fp.pdf", page_index=0, kind="product",
        terms=["100000000000000000000", "1000000000000000000000"], expected="5",
        quote="",
    )
    good = NumericClaim(
        sheet_id="FP-102", source_name="fp.pdf", page_index=0, kind="sum",
        terms=["100", "200"], expected="500", quote="",
    )
    res = audit_arithmetic([huge, good], [])
    assert res.mismatched == 2
    assert len(res.findings) == 2
    assert any("100000000000000000000000000000000000000000" in f.text for f in res.findings)
    assert any("the sum of 100, 200 is 300" in f.text for f in res.findings)


def test_a_claim_that_fails_MID_FINDING_leaves_the_tally_consistent(monkeypatch):
    # The rollback half of item 10b, and the case the _fmt bug actually hit:
    # result.mismatched is incremented BEFORE the Finding is built, and _fmt was
    # called four times inside the constructor expression. So a raise there left a
    # counted mismatch with no finding behind it -- breaking ArithmeticResult's
    # own documented invariant (mismatched == len(findings)) for every consumer
    # downstream, including the report's "N numeric relationships checked" line.
    from drawing_analyzer.auditors import arithmetic as arith

    real_severity = arith._severity_for

    def _boom(actual, expected):
        if expected == Decimal(660):
            raise RuntimeError("synthetic failure after the counters moved")
        return real_severity(actual, expected)

    monkeypatch.setattr(arith, "_severity_for", _boom)

    doomed = NumericClaim(
        sheet_id="FP-101", source_name="fp.pdf", page_index=0, kind="sum",
        terms=["180", "180", "180"], expected="660", quote="",
    )
    good = NumericClaim(
        sheet_id="FP-102", source_name="fp.pdf", page_index=0, kind="sum",
        terms=["100", "200"], expected="500", quote="",
    )
    res = audit_arithmetic([doomed, good], [])

    assert res.mismatched == len(res.findings) == 1
    assert "the sum of 100, 200 is 300" in res.findings[0].text
    assert res.unusable == 1        # the doomed claim, counted as unchecked
    assert res.checked == 1         # ...and NOT counted as one the host computed


def test_one_bad_claim_does_not_lose_the_runs_arithmetic(monkeypatch):
    # The orchestrator wraps the WHOLE batch in one try, so any per-claim failure
    # aborted audit_arithmetic mid-loop and the caller discarded the result: every
    # finding already produced was lost, and all four arithmetic_* stat keys went
    # ABSENT -- so the summary line then read "arith=0/0" via stats.get(..., 0),
    # rendering the failure as "nothing to check". Indistinguishable from a set
    # with no claims at all.
    from drawing_analyzer.auditors import arithmetic as arith

    real_compute = arith._compute

    def _boom(kind, terms):
        if terms and terms[0] == Decimal(999):
            raise RuntimeError("synthetic per-claim failure")
        return real_compute(kind, terms)

    monkeypatch.setattr(arith, "_compute", _boom)

    bad = NumericClaim(
        sheet_id="FP-101", source_name="fp.pdf", page_index=0, kind="sum",
        terms=["999", "1"], expected="5", quote="",
    )
    good = NumericClaim(
        sheet_id="FP-102", source_name="fp.pdf", page_index=0, kind="sum",
        terms=["100", "200"], expected="500", quote="",
    )
    res = run_auditors([], claims=[bad, good])

    assert len(res.findings) == 1
    assert "the sum of 100, 200 is 300" in res.findings[0].text
    # The stats are PRESENT, not merely zero -- absent keys are what made the
    # failure read as "no claims".
    for key in ("arithmetic_checked", "arithmetic_matched",
                "arithmetic_mismatched", "arithmetic_unusable"):
        assert key in res.stats, key
    assert res.stats["arithmetic_unusable"] == 1        # the bad claim, counted
    # The tally invariant survives the rollback: mismatched is incremented before
    # the Finding is built, so a failure between the two would otherwise leave a
    # counted mismatch with no finding behind it.
    assert res.stats["arithmetic_mismatched"] == len(res.findings)


def test_parse_number_boolean_is_not_one():
    # bool is an int subclass, but True is a JSON true, not the number 1.
    assert parse_number(True) is None
    assert parse_number(False) is None


def test_no_eval_in_arithmetic_module():
    """Construction-level guarantee: the arithmetic auditor never evaluates code."""
    src = Path("src/drawing_analyzer/auditors/arithmetic.py").read_text(encoding="utf-8")
    assert "eval(" not in src
    assert "exec(" not in src
    assert "__import__" not in src


# --------------------------------------------------------------------------- #
# Arithmetic auditor
# --------------------------------------------------------------------------- #


def _claim(kind, terms, expected, *, quote="Q", sheet_id="F-D-01-1",
           source="s.pdf", page=0, note=""):
    return NumericClaim(
        sheet_id=sheet_id, quote=quote, kind=kind, terms=list(terms),
        expected=expected, note=note, source_name=source, page_index=page,
    )


def test_arithmetic_sum_match_is_counted_not_flagged():
    res = audit_arithmetic([_claim("sum", [100, 200, 240], 540)], [])
    assert res.checked == 1 and res.matched == 1 and res.mismatched == 0
    assert res.findings == []


def test_arithmetic_sum_mismatch_flags_the_540_660_lesson():
    # A flow-test column that should total 540 but is printed as 660. The terms
    # are model-transcribed (the quote "Q" doesn't carry them), so §17.5 keeps the
    # mismatch UNCERTAIN — it must be crop-verified, not trusted as ground truth.
    res = audit_arithmetic([_claim("sum", [180, 180, 180], 660)], [])
    assert res.mismatched == 1 and len(res.findings) == 1
    f = res.findings[0]
    assert f.verification.status == "UNCERTAIN"
    assert f.verification.computation_method == "HOST_DETERMINISTIC"
    assert f.verification.operand_origin == "MODEL_TRANSCRIBED"
    assert f.category == "conflict"
    assert "540" in f.text and "660" in f.text  # computed vs stated
    assert f.severity == "high"                  # 22% off
    # Deterministic auditors carry a handcrafted "what to do" sentence.
    assert f.recommended_action == (
        "Re-check the math: the sum of the printed values is 540, "
        "not the stated 660 - correct whichever is wrong."
    )


def test_arithmetic_text_extracted_operands_stay_deterministic():
    # When the quote itself carries every operand, the operands are independently
    # validated — a mismatch is trusted DETERMINISTIC and auto-inks (§17.5).
    res = audit_arithmetic(
        [_claim("factor", [1500, "1.3"], 1560, quote="AREA 1500 X 1.3 = 1560")], []
    )
    assert res.mismatched == 1
    f = res.findings[0]
    assert f.verification.status == "DETERMINISTIC"
    assert f.verification.operand_origin == "TEXT_EXTRACTED"
    assert "1950" in f.text                        # host computed 1500*1.3


def test_arithmetic_relative_tolerance_catches_small_value_error():
    # §17.5: the old blanket abs-0.5 tolerance falsely matched 0.2+0.2 printed as
    # 0.5 (actual 0.4, a 20% error). The magnitude-aware relative rule flags it.
    res = audit_arithmetic([_claim("sum", ["0.20", "0.20"], "0.5")], [])
    assert res.mismatched == 1 and res.matched == 0


def test_arithmetic_mixed_fraction_operand_is_text_extracted():
    # §17.5: the quote scanner must tokenize a mixed fraction the same way the
    # operand parser does ("2 1/2" -> 2.5, not 2 and 1/2), so a text-extracted
    # mixed-fraction operand is recognised as TEXT_EXTRACTED, not falsely marked
    # model-transcribed. 2.5 + 2.5 = 5, but the sheet states 6 -> DETERMINISTIC.
    res = audit_arithmetic(
        [_claim("sum", ["2 1/2", "2 1/2"], 6, quote="2 1/2 + 2 1/2 = 6")], []
    )
    assert res.mismatched == 1
    f = res.findings[0]
    assert f.verification.status == "DETERMINISTIC"
    assert f.verification.operand_origin == "TEXT_EXTRACTED"


def test_arithmetic_factor_catches_missing_dipa_increase():
    # Base area 1500 × 1.3 = 1950, but the DIPA row still states 1500.
    res = audit_arithmetic([_claim("factor", [1500, "1.3"], 1500, note="DIPA +30%")], [])
    assert len(res.findings) == 1
    assert "1950" in res.findings[0].text and "DIPA +30%" in res.findings[0].text


def test_arithmetic_product_match():
    # density 0.20 gpm/ft² × 1500 ft² = 300 gpm demand.
    res = audit_arithmetic([_claim("product", ["0.20", 1500], 300)], [])
    assert res.matched == 1 and res.findings == []


def test_arithmetic_rounding_within_tolerance_is_a_match():
    # 1500 × 1.3 = 1950; a printed 1949 is rounding, not an error.
    res = audit_arithmetic([_claim("factor", [1500, "1.3"], 1949)], [])
    assert res.matched == 1 and res.findings == []


def test_arithmetic_severity_grades_by_magnitude():
    low = audit_arithmetic([_claim("sum", [100], 104)], []).findings      # 4% off
    high = audit_arithmetic([_claim("sum", [100], 200)], []).findings     # 100% off
    assert low[0].severity == "medium"
    assert high[0].severity == "high"


def test_arithmetic_unusable_claims_are_dropped_not_guessed():
    claims = [
        _claim("weird", [1, 2], 3),          # bad kind
        _claim("sum", ["abc"], 3),           # unparseable term
        _claim("product", [5], 5),           # too few terms for a product
    ]
    res = audit_arithmetic(claims, [])
    assert res.checked == 0 and res.findings == []
    assert res.unusable == 3


def test_arithmetic_deduplicates_repeated_claims():
    c = _claim("sum", [1, 1], 5)
    res = audit_arithmetic([c, c, c], [])
    assert res.checked == 1 and res.mismatched == 1 and len(res.findings) == 1


def test_arithmetic_anchors_mismatch_via_quote():
    sheet = _sheet("s.pdf", 0, [_w(200, 300, "TOTAL"), _w(280, 300, "540")])
    res = audit_arithmetic(
        [_claim("sum", [100, 100], 540, quote="TOTAL 540")], [sheet]
    )
    assert len(res.findings) == 1
    anchor = res.findings[0].anchor
    assert anchor.status == "EXACT" and anchor.rect_pdf is not None


def test_arithmetic_unresolved_sheet_still_records_finding_unanchored():
    # No geometry to anchor against → finding kept, UNANCHORED (nothing dropped).
    res = audit_arithmetic([_claim("sum", [1, 1], 9, quote="X")], [])
    assert len(res.findings) == 1
    assert res.findings[0].anchor.status == "UNANCHORED"


# --------------------------------------------------------------------------- #
# Naming-consistency auditor
# --------------------------------------------------------------------------- #


def test_naming_flags_hyphenation_drift():
    # "C1-R" is the established riser tag (used 4×); "C1R" appears once.
    sheets = [
        _sheet("s.pdf", 0, [_titleblock("F-D-01-1"),
                            _w(200, 200, "C1-R"), _w(400, 200, "C1-R")]),
        _sheet("s.pdf", 1, [_titleblock("F-D-01-2"),
                            _w(200, 200, "C1-R"), _w(400, 200, "C1-R"),
                            _w(600, 200, "C1R")]),
    ]
    findings = audit_naming(sheets)
    drift = [f for f in findings if f.source_quote == "C1R"]
    assert len(drift) == 1
    assert drift[0].category == "question" and drift[0].severity == "low"
    assert drift[0].verification.status == "DETERMINISTIC"
    assert drift[0].anchor.status == "EXACT"
    assert "C1-R" in drift[0].text                 # suggests the established spelling


def test_naming_does_not_flag_a_legitimate_vocabulary():
    # A1 / A2 / A3 are three real zones, each used repeatedly — not drift.
    words0 = [_titleblock("F-D-01-1")]
    for tag in ("A1", "A2", "A3"):
        for x in (200, 400, 600):
            words0.append(_w(x, 200 + 20 * len(words0), tag))
    findings = audit_naming([_sheet("s.pdf", 0, words0)])
    assert findings == []


def test_naming_does_not_merge_meaningful_digit_difference():
    # REVERSED (§17.4): A1-2 vs A2 differ in DIGIT CONTENT ("12" vs "2") — a
    # changed number is meaning-bearing (a different zone/circuit), not a
    # spelling drift, so the auditor must NOT flag A1-2 as a variant of A2.
    words = [_titleblock("F-D-01-1")]
    for _ in range(4):
        words.append(_w(200, 200 + 20 * len(words), "A2"))
    words.append(_w(800, 800, "A1-2"))
    findings = audit_naming([_sheet("s.pdf", 0, words)])
    assert not any(f.source_quote == "A1-2" for f in findings)


def test_naming_still_flags_pure_format_drift_same_digits():
    # A tag with the SAME letters and SAME digits but different separators (A1-2
    # vs A12) is a real formatting drift and is still flagged.
    words = [_titleblock("F-D-01-1")]
    for _ in range(4):
        words.append(_w(200, 200 + 20 * len(words), "A12"))
    words.append(_w(800, 800, "A1-2"))
    findings = audit_naming([_sheet("s.pdf", 0, words)])
    drift = [f for f in findings if f.source_quote == "A1-2"]
    assert len(drift) == 1 and "A12" in drift[0].text


def test_naming_does_not_manufacture_drift_out_of_alphabetical_order():
    # Item 25a. With no frequency winner (every spelling seen once) the auditor
    # fell back to the LEXICOGRAPHICALLY FIRST member as canonical and reported
    # everything else as drift from it. Alphabetical order is not evidence of a
    # convention, and the results were embarrassing in both directions: a
    # canonical NCS "FP-101" reported as drift from the mangled "F-P101", and
    # "VAV-21" called a misspelling of "VAV-2-1" -- which on a real schedule are
    # two different boxes, not two spellings of one.
    #
    # The guard is the ARRANGEMENT, not the digits: a separator between two
    # different kinds is formatting, a separator inside a digit run regroups the
    # number.
    words = [_titleblock("F-D-01-1")]
    for i, tag in enumerate(["VAV-2-1", "VAV-21", "FP-101", "F-P101", "M-101", "M1-01"]):
        words.append(_w(200, 200 + 20 * i, tag))
    assert audit_naming([_sheet("s.pdf", 0, words)]) == []


def test_a_pure_separator_drift_is_still_flagged_without_a_winner():
    # The complement, and the reason the guard is on arrangement rather than a
    # blanket "no winner -> report nothing": C1R and C1-R are the same
    # arrangement (A1, D1, A1), so a separator difference between two rare
    # spellings is still the drift this auditor exists to catch.
    words = [_titleblock("F-D-01-1"), _w(200, 200, "C1R"), _w(200, 240, "C1-R")]
    findings = audit_naming([_sheet("s.pdf", 0, words)])
    assert len(findings) == 1
    assert findings[0].source_quote == "C1R" and "C1-R" in findings[0].text


def test_an_established_convention_outranks_structural_doubt():
    # The arrangement guard applies ONLY where there is no frequency winner.
    # A12 seen four times IS evidence of a convention, so the single A1-2 is
    # still drift from it even though their arrangements differ -- which is what
    # test_naming_still_flags_pure_format_drift_same_digits pins, and why the
    # guard could not simply be applied everywhere.
    words = [_titleblock("F-D-01-1")]
    for _ in range(4):
        words.append(_w(200, 200 + 20 * len(words), "A12"))
    words.append(_w(800, 800, "A1-2"))
    findings = audit_naming([_sheet("s.pdf", 0, words)])
    assert [f.source_quote for f in findings] == ["A1-2"]


def test_naming_ignores_sheet_ids_and_bare_words():
    # Pure words (no digit) and the sheet's own ID never enter the lexicon.
    sheets = [
        _sheet("s.pdf", 0, [_titleblock("F-D-01-1"),
                            _w(200, 200, "NOTES"), _w(300, 200, "GENERAL")]),
        _sheet("s.pdf", 1, [_titleblock("F-D-01-2"),
                            _w(200, 200, "NOTE"), _w(300, 200, "GENERALS")]),
    ]
    assert audit_naming(sheets) == []


# --------------------------------------------------------------------------- #
# Title-block auditor
# --------------------------------------------------------------------------- #


def _tb_sheet(source, page, sheet_id, project_no):
    """A sheet with a title-block band: sheet id + a project-number field."""
    return _sheet(source, page, [
        _titleblock(sheet_id),
        _w(W - 300, H - 220, project_no),   # in the same right-edge x-band
    ])


def test_titleblock_flags_a_drifting_project_number():
    sheets = [
        _tb_sheet("s.pdf", 0, "F-D-01-1", "2021-045"),
        _tb_sheet("s.pdf", 1, "F-D-01-2", "2021-045"),
        _tb_sheet("s.pdf", 2, "F-D-02-0", "2021-045"),
        _tb_sheet("s.pdf", 3, "F-D-03-0", "2021-046"),   # the odd sheet out
    ]
    findings = audit_titleblock(sheets)
    assert len(findings) == 1
    f = findings[0]
    assert f.source_quote == "2021-046" and f.page_index == 3
    assert f.category == "coordination" and f.verification.status == "DETERMINISTIC"
    assert "2021-045" in f.text and f.anchor.status == "EXACT"


def test_titleblock_quiet_on_small_sets():
    sheets = [
        _tb_sheet("s.pdf", 0, "F-D-01-1", "2021-045"),
        _tb_sheet("s.pdf", 1, "F-D-01-2", "2021-046"),
    ]
    assert audit_titleblock(sheets) == []   # below the min-sheets floor


def test_titleblock_quiet_when_no_field_is_shared():
    # Every sheet has a *different* project number → no set-wide norm to drift from.
    sheets = [_tb_sheet("s.pdf", i, f"F-D-0{i}-1", f"2021-04{i}") for i in range(5)]
    assert audit_titleblock(sheets) == []


# Phase 25 §17.4 — high-confidence label→value field-class path.

def _tb_labeled(source, page, sheet_id, lines):
    """A title-block band with labelled fields. ``lines`` is a list of word lists,
    each placed on its own y-line inside the right-edge band (x >= ~2300)."""
    words = [_titleblock(sheet_id)]
    y = 300
    for line_words in lines:
        x = 2320
        for tok in line_words:
            words.append(_w(x, y, tok, width=90))
            x += 110
        y += 40
    return _sheet(source, page, words)


def test_titleblock_flags_multiword_package_name_mismatch():
    # §17.4: a multiword PACKAGE NAME that differs on one sheet is caught by the
    # label→value path — the recurrence path (single digit-bearing tokens) can't
    # see a bare-word name at all.
    sheets = [
        _tb_labeled("s.pdf", i, f"F-D-0{i}-1", [["PACKAGE", "CENTRAL", "PLANT", "UPGRADE"]])
        for i in range(3)
    ]
    sheets.append(_tb_labeled("s.pdf", 3, "F-D-03-1", [["PACKAGE", "NORTH", "TOWER", "FITOUT"]]))
    findings = audit_titleblock(sheets)
    odd = [f for f in findings if f.page_index == 3]
    assert len(odd) == 1
    assert "NORTH TOWER FITOUT" in odd[0].source_quote
    assert "CENTRAL PLANT UPGRADE" in odd[0].text
    assert odd[0].category == "coordination" and odd[0].verification.status == "DETERMINISTIC"


def test_titleblock_flags_substantially_different_value():
    # §17.4: a wholly different project number (not a one-char neighbor) is caught
    # via its label — the recurrence path only fires on edit-distance ≤2 variants.
    sheets = [
        _tb_labeled("s.pdf", i, f"F-D-0{i}-1", [["PROJECT", "NO.", "2021-045"]])
        for i in range(3)
    ]
    sheets.append(_tb_labeled("s.pdf", 3, "F-D-03-1", [["PROJECT", "NO.", "2099-999"]]))
    findings = audit_titleblock(sheets)
    odd = [f for f in findings if f.page_index == 3]
    assert len(odd) == 1 and odd[0].source_quote == "2099-999"
    assert "2021-045" in odd[0].text


def test_titleblock_low_confidence_labeled_field_is_telemetry_not_a_finding():
    # §17.4: a labelled field present on too few sheets to form a consensus is
    # telemetry, not a false deterministic markup.
    sheets = [
        _tb_labeled("s.pdf", 0, "F-D-01-1", [["PROJECT", "NO.", "2021-045"]]),
        _tb_labeled("s.pdf", 1, "F-D-02-1", [["PROJECT", "NO.", "2099-999"]]),
        _tb_sheet("s.pdf", 2, "F-D-03-1", "9999-000"),   # no label at all
        _tb_sheet("s.pdf", 3, "F-D-04-1", "8888-000"),
    ]
    # Only 2 sheets carry the labelled PROJECT NO. — below the consensus floor,
    # and the remaining project numbers neither share a value nor carry a label.
    assert audit_titleblock(sheets) == []


# --------------------------------------------------------------------------- #
# Sheet-index auditor
# --------------------------------------------------------------------------- #


def _index_sheet():
    """An index sheet listing itself + two real sheets + one phantom."""
    words = [
        _w(300, 200, "DRAWING"), _w(500, 200, "INDEX"),
        _w(300, 300, "F-D-00-0"),
        _w(300, 340, "F-D-01-1"),
        _w(300, 380, "F-D-01-2"),
        _w(300, 420, "F-D-99-9"),          # listed but not in the set
        _titleblock("F-D-00-0"),
    ]
    return _sheet("idx.pdf", 0, words)


def test_sheet_index_diffs_both_directions():
    sheets = [
        _index_sheet(),
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-01-2")]),
        _sheet("c.pdf", 0, [_titleblock("F-D-02-0")]),   # in set, not in the index
    ]
    findings = audit_sheet_index(sheets)
    quotes = {f.source_quote for f in findings}
    texts = " || ".join(f.text for f in findings)
    # Direction 1: a phantom index entry.
    assert "F-D-99-9" in quotes
    phantom = next(f for f in findings if f.source_quote == "F-D-99-9")
    assert phantom.severity == "medium" and "not present in the provided set" in phantom.text
    # Direction 2: a set sheet missing from the index.
    assert "F-D-02-0" in texts
    missing = next(f for f in findings if "F-D-02-0" in f.text)
    assert missing.severity == "low" and missing.anchor.status == "EXACT"


def test_sheet_index_distinguishes_malformed_entry_from_absent(monkeypatch):
    # §17.4: an index entry that is a near-typo of a real sheet (does not match
    # the set's convention) is surfaced as a LOW malformed-entry finding — not
    # silently dropped, and distinct from the MEDIUM "not in the provided set".
    words = [
        _w(300, 200, "DRAWING"), _w(500, 200, "INDEX"),
        _w(300, 300, "F-D-00-0"), _w(300, 340, "F-D-01-1"), _w(300, 380, "F-D-01-2"),
        _w(300, 420, "F-D-99-9"),   # grammar-valid, absent -> "not in set" (medium)
        _w(300, 460, "F-D-O1-1"),   # letter-O typo of F-D-01-1 -> malformed (low)
        _titleblock("F-D-00-0"),
    ]
    sheets = [
        _sheet("idx.pdf", 0, words),
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-01-2")]),
    ]
    findings = audit_sheet_index(sheets)
    absent = next(f for f in findings if f.source_quote == "F-D-99-9")
    assert absent.severity == "medium" and "not present" in absent.text
    malformed = next(f for f in findings if f.source_quote == "F-D-O1-1")
    assert malformed.severity == "low" and "does not match" in malformed.text


def test_sheet_index_ignored_without_a_header():
    # Same ID list, but no index header → not treated as an index sheet.
    no_header = _sheet("x.pdf", 0, [
        _w(300, 300, "F-D-01-1"), _w(300, 340, "F-D-01-2"),
        _w(300, 380, "F-D-99-9"), _titleblock("F-D-00-0"),
    ])
    assert audit_sheet_index([no_header]) == []


def test_a_legend_citation_never_reaches_the_index_diff_as_a_finding():
    # Item 25c, and the reason P4 does NOT add a veto at the harvest. The harvest
    # reads every word on the page -- nothing bounds it to the index table's own
    # region -- so a code citation or transmittal number in a legend IS collected
    # as an index row. But both diff directions run every entry through
    # classify_reference, which consults the negative corpus and returns IGNORE,
    # so it never becomes a finding. Nothing pinned that, and a second copy of
    # the corpus check at the harvest would have been the restated-rule drift
    # this codebase has already paid for once.
    #
    # What is still unfixed is the harvest itself: an equipment tag like "P-3" is
    # not in the corpus and would still be reported. That needs region bounding,
    # which is deferred.
    words = [_w(300, 200, "DRAWING"), _w(500, 200, "INDEX")]
    for i, e in enumerate(["F-D-00-0", "F-D-01-1", "F-D-02-0"]):
        words.append(_w(300, 300 + 40 * i, e))
    # ...and a legend block far below the table.
    words += [_w(300, 1800, "NFPA-13"), _w(300, 1840, "RFI-102"), _w(300, 1880, "REV-2")]
    words.append(_titleblock("F-D-00-0"))
    sheets = [
        _sheet("idx.pdf", 0, words),
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-02-0")]),
    ]
    texts = " || ".join(f.text for f in audit_sheet_index(sheets))
    for phantom in ("NFPA-13", "RFI-102", "REV-2"):
        assert phantom not in texts, phantom


def test_an_index_that_lists_itself_is_still_recognised_as_an_index():
    # The other rejected "cheap fix": excluding the sheet's own id. An index
    # legitimately lists itself, and dropping it can push a real index below the
    # _MIN_INDEX_ENTRIES recognition gate -- turning a working index sheet into
    # no index at all, which is a far worse failure than one phantom row. The
    # phantom that motivated it was really item N22 upstream: the page's own id
    # had been mis-detected, so its genuine self-listing looked absent.
    words = [_w(300, 200, "DRAWING"), _w(500, 200, "INDEX")]
    for i, e in enumerate(["F-D-00-0", "F-D-01-1", "F-D-02-0"]):
        words.append(_w(300, 300 + 40 * i, e))
    words.append(_titleblock("F-D-00-0"))          # the index lists itself
    sheets = [
        _sheet("idx.pdf", 0, words),
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-02-0")]),
    ]
    # Recognised, and reporting nothing: every listed sheet is present.
    assert audit_sheet_index(sheets) == []


def _index_page(source, own_id, entries):
    words = [_w(300, 200, "DRAWING"), _w(500, 200, "INDEX")]
    for i, e in enumerate(entries):
        words.append(_w(300, 300 + 40 * i, e))
    words.append(_titleblock(own_id))
    return _sheet(source, 0, words)


def test_sheet_index_unions_split_index_pages():
    # A discipline-split / multi-page index: idx1 lists some sheets, idx2 the rest.
    # A sheet listed on idx2 must NOT be reported missing when idx1 is processed —
    # only a sheet listed on NEITHER page is a real omission.
    sheets = [
        _index_page("i1.pdf", "F-D-00-0", ["F-D-00-0", "F-D-00-1", "F-D-01-1"]),
        _index_page("i2.pdf", "F-D-00-1", ["F-D-02-0", "F-D-00-0", "F-D-00-1"]),
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-02-0")]),   # listed on idx2 only
        _sheet("c.pdf", 0, [_titleblock("F-D-03-0")]),   # listed on NEITHER index
    ]
    findings = audit_sheet_index(sheets)
    texts = " || ".join(f.text for f in findings)
    # The real omission is flagged...
    assert "F-D-03-0" in texts
    # ...but the sheet listed on the other index page is NOT falsely flagged.
    assert "F-D-02-0" not in texts
    omissions = [f for f in findings if f.verification.note.startswith("set sheet missing")]
    assert len(omissions) == 1


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


def test_run_auditors_combines_findings_and_stats():
    sheets = [
        _index_sheet(),
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1"), _w(200, 200, "C1-R"),
                            _w(400, 200, "C1-R"), _w(600, 200, "C1R")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-01-2")]),
    ]
    claims = [_claim("sum", [1, 1], 2, source="a.pdf"),          # matches
              _claim("sum", [1, 1], 9, source="a.pdf", quote="Z")]  # mismatch
    res = run_auditors(sheets, claims=claims)
    assert res.stats["arithmetic_checked"] == 2
    assert res.stats["arithmetic_matched"] == 1
    assert res.stats["arithmetic_mismatched"] == 1
    assert res.stats["naming_findings"] >= 1
    # Reference / naming / title-block / index findings are text-extracted and
    # trusted DETERMINISTIC. The arithmetic mismatch was computed from
    # model-transcribed terms (its quote "Z" carries no operand), so it stays
    # UNCERTAIN and will be crop-verified (§17.5) — never blanket-trusted.
    for f in res.findings:
        if "auditor_arithmetic" in f.sources:
            assert f.verification.status == "UNCERTAIN"
            assert f.verification.operand_origin == "MODEL_TRANSCRIBED"
        else:
            assert f.verification.status == "DETERMINISTIC"
    # No two findings share an id (dedup by content).
    ids = [f.id for f in res.findings]
    assert len(ids) == len(set(ids))


def test_run_auditors_isolates_a_failing_auditor(monkeypatch):
    import drawing_analyzer.auditors as A

    def _boom(_sheets):
        raise RuntimeError("naming exploded")

    monkeypatch.setattr(A, "audit_naming", _boom)
    # References still run and produce their findings; the run does not die.
    sheets = [
        _sheet("a.pdf", 0, [_titleblock("F-D-01-1"),
                            _w(200, 200, "SEE"), _w(260, 200, "DRAWING"),
                            _w(420, 200, "F-D-09-9")]),
        _sheet("b.pdf", 0, [_titleblock("F-D-01-2")]),
    ]
    res = run_auditors(sheets)
    assert res.stats["naming_findings"] == 0            # the failed auditor contributed nothing
    assert res.stats["reference_findings"] >= 1         # the others still ran


def test_run_auditors_empty_set():
    res = run_auditors([])
    assert res.findings == []
