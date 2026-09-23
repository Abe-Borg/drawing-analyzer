"""Remediation WP-07.2 (A8): strict numeric tokens and host-side relationship
checks for the arithmetic auditor.

WP-07.1 (N3) made a mismatch trusted (``DETERMINISTIC``,
``operand_origin=TEXT_EXTRACTED``) only when the claim's quote anchors on its
own sheet and the numbers printed there carry every operand once per use. Two
holes were left, both reproduced on ``ba394bb`` and ``3e7fd78``, each shape
DETERMINISTIC with an EXACT anchor:

* **Numbers that are not one value.** ``_numbers_in_text`` read the digits of a
  tag or sheet id (``SEE FP101 TOTAL 540 AT 439 GPM`` scanned as 101, 540, 439,
  so ``sum [101, 540] = 439`` was trusted), read a hyphen after a letter as a
  minus sign (``M-101 P-3 AHU-2`` scanned as -101, -3, -2), and both it and
  ``parse_number`` truncated scientific notation (``1e3`` was 1, ``2.5e-2`` was
  2.5, so ``sum ["1e3", 500] = 1600`` inked as "the sum of 1, 500 is 501").
* **The relationship was never checked.** A claim names an operation and its
  roles (these terms, this stated value); the host only checked that the
  numbers were printed. ``20 x 2 = 40`` transcribed as ``sum [20, 2] = 40`` was
  "the sum of 20, 2 is 22" on a correct product, and ``A 100 B 250 TOTAL 375``
  with ``sum [100, 375] = 250`` was trusted though the row checks out.

Decided with the owner (WP-07.2 handoff), each as recommended:

1. Scientific notation is rejected: ``1e3`` is not a value the parser or the
   scanner reads, so a term spelled that way makes its claim unusable.
2. Digits glued after a letter, with or without a hyphen (``FP101``, ``M-101``,
   ``AHU-2``, ``A1.01``), are a tag's, never a number, and a hyphen after a
   letter is never a minus sign. Letters after a number are its unit
   (``20A``, ``150GPM``) unless digits follow them directly (``24x12``,
   ``2P20A``, ``10A1``, ``100m2``, ``1e3``): then the token is not one value.
3. A mismatch is trusted only when the quote AND the sheet's words under the
   matched span each state the claim as one equation: the stated value is the
   first number after ``=`` or TOTAL, the operands before it are exactly the
   claim's terms, joined all by ``+`` (sum) or all by ``x``/``×``/``*``
   (product, factor); an operator-less list is a sum only with TOTAL. Anything
   else stays MODEL_TRANSCRIBED / UNCERTAIN for the crop verifier.

Pure where it can be (synthetic words, no PyMuPDF); the pipeline test at the
end renders a PDF and skips without PyMuPDF. Hermetic: no network.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from drawing_analyzer.auditors import run_auditors
from drawing_analyzer.auditors.arithmetic import (
    _numbers_in_text,
    audit_arithmetic,
    claim_value_key,
    parse_number,
)
from drawing_analyzer.models import (
    Finding,
    ImageTile,
    NumericClaim,
    RenderedSheet,
    SheetRef,
    compute_finding_id,
)

W, H = 3168.0, 2448.0
SHEET_ID = "F-D-01-1"

TRUSTED_NOTE = "Math checked by computer from the sheet's own printed numbers."
TRANSCRIBED_NOTE = (
    "Computed from numbers as read by the AI - re-check the math against the sheet."
)


def _w(x, y, text, width=64, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _row(texts, *, y=300, x0=100, step=80):
    return [_w(x0 + step * i, y, t) for i, t in enumerate(texts)]


def _sheet(words, *, source="s.pdf", page=0, sheet_id=SHEET_ID):
    words = list(words) + [_w(W - 300, H - 160, sheet_id)]
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=1, cols=1, words=words,
    )


def _claim(kind, terms, expected, quote, *, sheet_id=SHEET_ID, source="s.pdf", page=0):
    return NumericClaim(
        sheet_id=sheet_id, quote=quote, kind=kind, terms=list(terms),
        expected=expected, source_name=source, page_index=page,
    )


def _on_its_sheet(kind, terms, expected, quote):
    """Audit one claim whose sheet prints exactly its quote, one word per token."""
    return audit_arithmetic([_claim(kind, terms, expected, quote)], [_sheet(_row(quote.split()))])


def _one(kind, terms, expected, quote):
    res = _on_its_sheet(kind, terms, expected, quote)
    assert res.checked == 1 and res.mismatched == 1 and len(res.findings) == 1, (
        res.checked, res.mismatched, res.unusable)
    f = res.findings[0]
    assert f.anchor.status == "EXACT", f.anchor
    return f


def _trusted(f: Finding) -> bool:
    v = f.verification
    return v.status == "DETERMINISTIC" and v.operand_origin == "TEXT_EXTRACTED"


def _transcribed(f: Finding) -> bool:
    v = f.verification
    return (
        v.status == "UNCERTAIN"
        and v.operand_origin == "MODEL_TRANSCRIBED"
        and v.computation_method == "HOST_DETERMINISTIC"
    )


# --------------------------------------------------------------------------- #
# Strict tokens: what the scanner and the parser read as a number
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text, numbers",
    [
        ("SEE FP101 TOTAL 540 AT 439 GPM", [540, 439]),   # the review's case
        ("M-101 P-3 AHU-2", []),                         # the step 5 case
        ("FP101", []),
        ("FP-101", []),
        ("VAV-3", []),                                  # the pipeline fixture's quote
        ("A1.01 M1.01", []),                            # dotted sheet ids
        ("SEE M-501 AND M-502 FOR 20 GPM", [20]),
        ("M\u2013101 P\u2010 3", [3]),                   # a Unicode hyphen joins a tag too
        ("AHU-2A", []),
        ("CH-1 150 GPM", [150]),
    ],
)
def test_the_digits_of_a_tag_or_sheet_id_are_never_numbers(text, numbers):
    assert _numbers_in_text(text) == [Decimal(n) for n in numbers], text


@pytest.mark.parametrize(
    "text",
    ["M-101", "P-3", "AHU-2", "VAV-3", "SEE M-101 FOR DETAILS", "EF-12 AND EF-13"],
)
def test_a_hyphen_after_a_letter_is_never_a_minus_sign(text):
    assert all(n >= 0 for n in _numbers_in_text(text)), text
    assert _numbers_in_text(text) == [], text


@pytest.mark.parametrize(
    "raw, value",
    [
        ("20A", Decimal(20)),
        ("150GPM", Decimal(150)),
        ("12IN", Decimal(12)),
        ("165 psi", Decimal(165)),
        ("0.20 gpm/ft\u00b2", Decimal("0.20")),
        ("1,950 ft\u00b2", Decimal(1950)),
        ('2-1/2"', Decimal("2.5")),
        ("2 1/2", Decimal("2.5")),
        ("1,200", Decimal(1200)),
        ("12' clear", Decimal(12)),
        ("6-INCH", Decimal(6)),
        ("2HR", Decimal(2)),
    ],
)
def test_a_unit_after_the_number_still_parses(raw, value):
    """Trailing letters are units (plan WP-07 step 5), in the parser and the
    scanner alike."""
    assert parse_number(raw) == value, raw
    assert _numbers_in_text(raw) == [value], raw


@pytest.mark.parametrize(
    "raw, why",
    [
        ("1e3", "scientific notation is rejected, never truncated to 1"),
        ("1E3", "the same, upper case"),
        ("2.5e-2", "an exponent with a sign, never 2.5"),
        ("1E+3", "the same, plus"),
        ("2E1", "a panel tag as often as an exponent"),
        ("24x12", "a duct size, not the number 24"),
        ("24\u00d712", "the same, with the multiplication sign"),
        ("2P20A", "a breaker (two-pole, 20 A), not the number 2"),
        ("10A1", "an identifier, not the number 10"),
        ("100m2", "letters with digits after them: not one value"),
        ("12'\u20136\"", "a dimension with an en dash, never 12 and 6"),
        ("12\u20136", "an en-dash pair, as 12-6 already was"),
        ("2\u00bd\"", "a vulgar fraction glued on: 2.5, never 2"),
        ("1\u20442", "a fraction slash: one half, never 1 and 2"),
        ("\u22125", "a Unicode minus sign: its sign cannot be read, so not 5"),
    ],
)
def test_a_token_that_is_not_one_value_is_refused_by_both(raw, why):
    assert parse_number(raw) is None, why
    assert _numbers_in_text(raw) == [], why


def test_the_current_safeguards_still_hold():
    # Percent, dimensions, malformed groupings, repeated legitimate values.
    for raw in ("30%", "30 %", "12'-6\"", "12,5", "1.2.3", "12-6"):
        assert parse_number(raw) is None, raw
    assert _numbers_in_text("1500 SF + 30% = 1950 SF") == [Decimal(1500), Decimal(1950)]
    assert _numbers_in_text("20 20 20 TOTAL 540") == [Decimal(20)] * 3 + [Decimal(540)]
    assert _numbers_in_text("0.5, 1.5, TOTAL 2.0") == [Decimal("0.5"), Decimal("1.5"), Decimal("2.0")]
    # A spaced sign is still a sign, and a '+' glued to a unit is an operator.
    assert _numbers_in_text("OFFSET -5 IN") == [Decimal(-5)]
    assert _numbers_in_text("250GPM+100GPM=350GPM") == [Decimal(250), Decimal(100), Decimal(350)]


@pytest.mark.parametrize(
    "token",
    ["20A", "150GPM", "FP101", "M-101", "1e3", "2.5e-2", "24x12", "2P20A", "10A1",
     "100m2", '2-1/2"', "1,200", "30%", "12'-6\"", "2\u00bd\"", "12\u20136", "6-INCH"],
)
def test_the_scanner_and_the_parser_agree_on_every_single_token(token):
    """A single token scans as exactly what it parses to (§17.5): the scanner
    never reads a number the parser refuses, and never refuses one it reads."""
    parsed = parse_number(token)
    assert _numbers_in_text(token) == ([] if parsed is None else [parsed]), token


def test_the_dashes_that_bind_are_the_ones_the_anchor_folds_to_a_hyphen():
    """One definition of "a dash": the scanner refuses a number glued to exactly
    the characters ``anchor._normalize`` treats as a hyphen, so a tag written
    with any of them anchors as a tag and never scans as a number."""
    from drawing_analyzer.anchor import _CHAR_FOLD
    from drawing_analyzer.auditors.arithmetic import _UNICODE_DASHES

    folded = {chr(c) for c, v in _CHAR_FOLD.items() if v == "-"}
    assert set(_UNICODE_DASHES) == folded
    for dash in sorted(folded):
        assert _numbers_in_text(f"M{dash}101") == [], repr(dash)
        assert _numbers_in_text(f"12'{dash}6\"") == [], repr(dash)
        assert parse_number(f"12{dash}6") is None, repr(dash)


def test_a_refused_spelling_never_collapses_into_the_number_it_used_to_parse_as():
    # Before WP-07.2 "1e3" keyed as "1", so it was the same claim as 1.
    assert claim_value_key("1e3") == "raw:1e3" != claim_value_key(1)
    assert claim_value_key("24x12") == "raw:24x12" != claim_value_key(24)
    assert claim_value_key("20A") == claim_value_key(20) == "20"


# --------------------------------------------------------------------------- #
# The auditor: the review's A8 shapes
# --------------------------------------------------------------------------- #


def test_a_sheet_numbers_digits_do_not_ground_an_operand():
    """``SEE FP101 TOTAL 540 AT 439 GPM``: the 101 is the sheet's own number."""
    f = _one("sum", [101, 540], 439, "SEE FP101 TOTAL 540 AT 439 GPM")
    assert _transcribed(f), f.verification


def test_a_tags_digits_read_as_a_negative_do_not_ground_an_operand():
    f = _one("sum", [-3, 100, 100], 200, "VAV-3 100 + 100 = 200")
    assert _transcribed(f), f.verification


@pytest.mark.parametrize("term", ["1e3", "1E3", "2.5e-2", "24x12", "2P20A"])
def test_a_term_that_is_not_one_value_makes_its_claim_unusable(term):
    """Never truncated: ``sum ["1e3", 500] = 1600`` used to ink as "the sum of
    1, 500 is 501", DETERMINISTIC. Unusable is counted, never a finding."""
    res = _on_its_sheet("sum", [term, 500], 1600, f"{term} + 500 = 1600")
    assert res.findings == [] and res.checked == 0 and res.unusable == 1


# --------------------------------------------------------------------------- #
# The auditor: the relationship must be stated on the sheet
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("times", ["x", "X", "\u00d7", "*"])
def test_a_product_transcribed_as_a_sum_is_not_trusted(times):
    """``20 x 2 = 40`` is a correct product. Transcribed as ``sum [20, 2] =
    40`` it prints every operand once, and was "the sum of 20, 2 is 22"."""
    f = _one("sum", [20, 2], 40, f"20 {times} 2 = 40")
    assert _transcribed(f), f.verification
    assert f.text.startswith("Arithmetic does not check out: the sum of 20, 2 is 22")


def test_a_sum_transcribed_as_a_product_is_not_trusted():
    f = _one("product", [20, 3], 40, "20 + 3 = 40")
    assert _transcribed(f), f.verification


@pytest.mark.parametrize(
    "quote, terms, expected",
    [
        ("A 100 B 250 TOTAL 375", [100, 375], 250),    # the review's role swap
        ("A 100 B 250 TOTAL 375", [250, 375], 100),
        ("100 + 250 = 375", [100, 375], 250),
        ("100 + 250 = 375", [375, 250], 100),
    ],
)
def test_a_swapped_role_is_not_trusted(quote, terms, expected):
    """The row checks out (100 + 250 = 375); a claim that puts the total among
    the terms and a term in the total's place is the model's reading, not the
    sheet's."""
    f = _one("sum", terms, expected, quote)
    assert _transcribed(f), f.verification


def test_a_correct_sum_with_an_operand_left_out_is_not_trusted():
    """``20 20 20 TOTAL 60`` is correct. A claim that drops one 20 prints all
    its numbers (the occurrence rule passes) and would be a false
    DETERMINISTIC mismatch on a correct equation."""
    f = _one("sum", [20, 20], 60, "20 20 20 TOTAL 60")
    assert _transcribed(f), f.verification


def test_a_correct_subtraction_is_not_trusted_as_a_sum():
    """The claims contract has no subtraction; ``100 - 20 = 80`` transcribed as
    ``sum [100, 20] = 80`` was a DETERMINISTIC mismatch on a correct equation."""
    f = _one("sum", [100, 20], 80, "100 - 20 = 80")
    assert _transcribed(f), f.verification


@pytest.mark.parametrize(
    "kind, terms, expected, quote, why",
    [
        ("sum", [1500, "1.3"], 1950, "1500 SF 1.3 = 1950",
         "no operator and no TOTAL: the operation is not on the sheet"),
        ("factor", [1500, "1.3"], 2000, "1500 SF 1.3 = 2000", "the same, as a factor"),
        ("sum", ["0.20", 1500], 350, "0.20 @ 1500 TOTAL 350",
         "an unrecognized symbol between operands"),
        ("sum", [20, 30], 60, "20 + FP101 + 30 = 60",
         "a number the scan cannot read sits between the operands"),
        ("sum", [20, 30, 2], 80, "20 + 30 x 2 = 80", "mixed operators"),
        ("product", [20, 30, 2], 80, "20 + 30 x 2 = 80", "mixed operators"),
        ("sum", [20, 20, 20], 540, "RISER 3: 20 20 20 TOTAL 540",
         "a printed number before the operands is an operand of the row"),
        ("sum", [20, 30], 70, "20 20 TOTAL 40 30 30 TOTAL 70",
         "operands from two different rows"),
        ("sum", [20, 20], 50, "20 + 20 50",
         "no result marker: the stated value is not in a result's place"),
    ],
)
def test_a_relationship_the_sheet_does_not_state_is_not_trusted(kind, terms, expected, quote, why):
    f = _one(kind, terms, expected, quote)
    assert _transcribed(f), why


@pytest.mark.parametrize(
    "kind, terms, expected, quote",
    [
        ("sum", [20, 20, 20], 540, "20 20 20 TOTAL 540"),            # a TOTAL row
        ("sum", [100, 250], 375, "TOTAL 100 + 250 = 375"),          # the gauntlet's
        ("sum", [100, 250], 375, "A 100 B 250 TOTAL 375"),          # labels between
        ("factor", [1500, "1.3"], 1560, "AREA 1500 X 1.3 = 1560"),
        ("product", ["0.20", 1500], 350, "0.20 GPM/SF x 1500 SF = 350 GPM"),
        ("product", [1500, "1.3"], 2000, "1500 SF \u00d7 1.3 = 2000 SF"),
        ("sum", ["2 1/2", "2 1/2"], 6, "2 1/2 + 2 1/2 = 6"),
        ("sum", ["0.5", "1.5"], "2.5", "0.5, 1.5, TOTAL 2.5"),
        ("sum", ["20A", "30A"], "60A", "20A + 30A = 60A"),
        ("sum", ["1,200", "2,400"], "3,700", "1,200 + 2,400 = 3,700"),
        ("sum", [20, 20, 20], 540, "FP-101: 20 20 20 TOTAL 540"),   # a tag label first
        ("sum", [300, 250], 600, "0.20 x 1500 = 300 + 250 = 600"),  # a running total
        ("sum", [30, 30], 70, "20 20 TOTAL 40 30 30 TOTAL 70"),     # the second row
        ("sum", [20, 30], 20, "20 + 30 = 20"),                      # the result in its own right
        ("sum", [20, 20, 20], 540, "20 20 20 TOTAL: 540 GPM AT RISER 3"),
    ],
)
def test_a_relationship_the_sheet_states_is_still_trusted(kind, terms, expected, quote):
    """Actual deterministic mismatches still work (WP-07 acceptance)."""
    f = _one(kind, terms, expected, quote)
    assert _trusted(f), f.verification


@pytest.mark.parametrize(
    "kind, terms, expected, quote",
    [
        ("sum", [20, -5], 20, "20 + -5 = 20"),
        ("product", [20, 2], 50, "20 x +2 = 50"),
        ("product", [20, -2], 50, "20 x -2 = 50"),
    ],
)
def test_a_signed_operand_after_an_explicit_operator_is_still_trusted(kind, terms, expected, quote):
    """Codex review on PR #164: the operand's own sign was read as a second
    operator beside the printed one, so a stated equation was refused and sent
    to the crop verifier for nothing."""
    f = _one(kind, terms, expected, quote)
    assert _trusted(f), f.verification


def test_the_relationship_must_be_stated_on_the_sheet_not_only_in_the_quote():
    """The window anchors FUZZY: one non-numeric token differs, and it is the
    operator. The quote says ``+`` where the sheet prints ``x``; the sheet's
    ``20 x 2 = 40`` is a correct product, so a sum claim over it must not be
    trusted on the model's word for the operator."""
    printed = ["FLOW", "TEST", "20", "x", "2", "=", "40", "GPM", "AT", "RISER", "3"]
    quote = "FLOW TEST 20 + 2 = 40 GPM AT RISER 3"
    res = audit_arithmetic([_claim("sum", [20, 2], 40, quote)], [_sheet(_row(printed))])
    (f,) = res.findings
    assert (f.anchor.status, f.anchor.method) == ("FUZZY", "fuzzy_window")
    assert _transcribed(f), f.verification


def test_the_finding_itself_does_not_move_only_its_trust_label():
    """Text, severity, anchor, discriminator and id are what they were: the
    investigation cache key reads the id and the note, and the note keeps its
    wording for each provenance (WP-07.1)."""
    quote = "20 x 2 = 40"
    f = _one("sum", [20, 2], 40, quote)
    assert f.severity == "high"
    assert f.claim_discriminator == "arithmetic/1:sum:2,20=40"
    assert f.id == compute_finding_id(
        f.sheet_id, "conflict", quote, f.source_id, f.claim_discriminator,
    )
    assert f.verification.note == (
        "computed sum of terms = 22; stated = 40 "
        "(host-computed from model-transcribed terms — verify against the sheet)"
    )


# --------------------------------------------------------------------------- #
# The relationship reader (new API: imported inside the tests)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "kind, terms, expected, text, stated",
    [
        ("sum", [20, 20, 20], 540, "20 20 20 TOTAL 540", True),
        ("sum", [20, 20, 20], 540, "20 20 20 = 540", False),     # a list needs TOTAL
        ("sum", [20, 20, 20], 540, "TOTAL 20 20 20 = 540", True),
        ("sum", [100, 250], 375, "TOTAL 100 + 250 = 375", True),
        ("product", [100, 250], 375, "TOTAL 100 + 250 = 375", False),
        ("factor", [1500, "1.3"], 1950, "1500 x 1.3 = 1950", True),
        ("sum", [1500, "1.3"], 1950, "1500 x 1.3 = 1950", False),
        ("sum", [20, 30], 50, "20 +30 = 50", True),              # a '+' glued to the operand
        ("sum", [20, -5], 15, "20 -5 = 15", False),              # a subtraction
        # A sign after an explicit operator is the operand's own (Codex review):
        ("sum", [20, -5], 15, "20 + -5 = 15", True),
        ("sum", [20, 5], 25, "20 + +5 = 25", True),
        ("product", [20, 2], 40, "20 x +2 = 40", True),
        ("product", [20, -2], -40, "20 x -2 = -40", True),
        ("sum", [20, -5], 25, "20 - -5 = 25", False),            # still a subtraction
        ("sum", [300, -50], 250, "0.2 x 1500 = 300 + -50 = 250", True),
        ("sum", [-5, 20], 15, "-5 + 20 = 15", True),             # a leading negative
        ("sum", [300, 250], 550, "0.2 x 1500 = 300 + 250 = 550", True),
        ("sum", [20, 30], 50, "20 + 30 = $50", False),           # an unrecognized symbol
        ("sum", [20, 30], 50, "SUBTOTAL 20 + 30 = 50", True),
        ("sum", [20, 30], 50, "", False),
    ],
)
def test_the_relationship_reader(kind, terms, expected, text, stated):
    from drawing_analyzer.auditors.arithmetic import _relationship_stated

    values = [parse_number(t) for t in terms]
    assert _relationship_stated(kind, values, parse_number(expected), text) is stated, text


def test_the_relationship_needs_both_the_quote_and_the_sheet_words():
    from drawing_analyzer.auditors.arithmetic import _relationship_grounded

    terms, expected = [Decimal(20), Decimal(2)], Decimal(40)
    assert _relationship_grounded("sum", terms, expected, "20 + 2 = 40", "20 + 2 = 40")
    assert not _relationship_grounded("sum", terms, expected, "20 + 2 = 40", "20 x 2 = 40")
    assert not _relationship_grounded("sum", terms, expected, "20 x 2 = 40", "20 + 2 = 40")


def test_a_failure_while_checking_the_relationship_leaves_only_that_finding_uncertain(monkeypatch):
    from drawing_analyzer.auditors import arithmetic as arith

    real = arith._relationship_grounded

    def _flaky(kind, terms, expected, quote, matched_text):
        if expected == Decimal(375):
            raise RuntimeError("synthetic failure while checking the relationship")
        return real(kind, terms, expected, quote, matched_text)

    monkeypatch.setattr(arith, "_relationship_grounded", _flaky)
    sheet = _sheet(_row(["100", "+", "250", "=", "375"])
                   + _row(["20", "+", "20", "=", "50"], y=900))
    res = audit_arithmetic([
        _claim("sum", [100, 250], 375, "100 + 250 = 375"),
        _claim("sum", [20, 20], 50, "20 + 20 = 50"),
    ], [sheet])
    assert res.mismatched == len(res.findings) == 2 and res.unusable == 0
    by_quote = {f.source_quote: f for f in res.findings}
    assert _transcribed(by_quote["100 + 250 = 375"])
    assert _trusted(by_quote["20 + 20 = 50"])


# --------------------------------------------------------------------------- #
# What the change reaches downstream
# --------------------------------------------------------------------------- #


def test_run_auditors_counts_what_it_could_check_and_keeps_both_verdicts():
    sheet = _sheet(_row(["20", "x", "2", "=", "40"])
                   + _row(["100", "+", "250", "=", "375"], y=900)
                   + _row(["1e3", "+", "500", "=", "1600"], y=1500))
    res = run_auditors([sheet], claims=[
        _claim("sum", [20, 2], 40, "20 x 2 = 40"),               # sum on a product
        _claim("sum", [100, 250], 375, "100 + 250 = 375"),       # stated: trusted
        _claim("sum", ["1e3", 500], 1600, "1e3 + 500 = 1600"),   # not one value
    ])
    arith = {f.source_quote: f for f in res.findings if "auditor_arithmetic" in f.sources}
    assert res.stats["arithmetic_checked"] == 2
    assert res.stats["arithmetic_unusable"] == 1
    assert res.stats["arithmetic_mismatched"] == len(arith) == 2
    assert _transcribed(arith["20 x 2 = 40"])
    assert _trusted(arith["100 + 250 = 375"])


def test_an_unstated_relationship_goes_to_the_crop_verifier_with_its_caveat():
    from drawing_analyzer.annotate import _trust_note
    from drawing_analyzer.verify import _is_verifiable

    f = _one("sum", [20, 2], 40, "20 x 2 = 40")
    assert _is_verifiable(f) is True
    assert _trust_note(f, unverified=True, rejected=False) == TRANSCRIBED_NOTE
    stated = _one("sum", [100, 250], 375, "100 + 250 = 375")
    assert _is_verifiable(stated) is False
    assert _trust_note(stated, unverified=False, rejected=False) == TRUSTED_NOTE


def test_the_critique_and_cross_qc_dedups_keep_a_refused_spelling_apart():
    from drawing_analyzer.critique import _dedup_claims as critique_dedup
    from drawing_analyzer.cross_qc import _dedup_claims as cross_dedup

    pair = [_claim("sum", ["1e3", 500], 1600, "1e3 + 500 = 1600"),
            _claim("sum", [1, 500], 1600, "1e3 + 500 = 1600")]
    assert len(critique_dedup(pair)) == 2
    assert len(cross_dedup(pair)) == 2


# --------------------------------------------------------------------------- #
# End to end: the pipeline sends an unstated relationship to the crop verifier
# --------------------------------------------------------------------------- #


def _make_pdf(path: Path, pymupdf) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "DENSITY 20 x 2 = 40")
    page.insert_text((80, 200), "TOTAL 100 + 250 = 375")
    page.insert_text((80, 280), "SEE FP101 TOTAL 540 AT 439 GPM")
    page.insert_text((650, 560), "M-101")
    doc.save(str(path))
    doc.close()
    return path


def test_the_pipeline_crop_verifies_unstated_relationships_and_trusts_the_stated_one(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")

    from drawing_analyzer.annotate import _trust_note
    from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT
    from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT
    from drawing_analyzer.pipeline import extract_drawing_context
    from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT
    from tests.fixtures.fake_anthropic import (
        BetaClientMixin,
        FakeMessage,
        FakeTextBlock,
        FakeUsage,
        StreamingMessagesMixin,
    )

    claims = [
        {"sheet_id": "M-101", "quote": "20 x 2 = 40", "kind": "sum",
         "terms": [20, 2], "expected": 40, "note": "density"},
        {"sheet_id": "M-101", "quote": "SEE FP101 TOTAL 540 AT 439 GPM", "kind": "sum",
         "terms": [101, 540], "expected": 439, "note": "flow"},
        {"sheet_id": "M-101", "quote": "TOTAL 100 + 250 = 375", "kind": "sum",
         "terms": [100, 250], "expected": 375, "note": "column total"},
    ]
    digest_text = (
        "Sheet M-101 - Mechanical - Plan\nDensity and totals.\n\n"
        "```json\n" + json.dumps({"findings": []}) + "\n```"
    )
    critique_text = "```json\n" + json.dumps({"findings": [], "claims": claims}) + "\n```"
    verify_texts: list[str] = []

    def _user_text(kw) -> str:
        out = []
        for m in kw.get("messages") or []:
            content = m.get("content")
            if isinstance(content, str):
                out.append(content)
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "text":
                    out.append(block.get("text", ""))
        return "\n".join(out)

    class _Client(BetaClientMixin):
        def __init__(self):
            class _Msgs(StreamingMessagesMixin):
                def create(_self, **kw):
                    system = kw.get("system", "")
                    if isinstance(system, str) and system.startswith(CRITIQUE_SYSTEM_PROMPT):
                        text = critique_text
                    elif isinstance(system, str) and system.startswith(DIGEST_SYSTEM_PROMPT):
                        text = digest_text
                    elif system == VERIFY_SYSTEM_PROMPT:
                        verify_texts.append(_user_text(kw))
                        text = '{"verdict":"CONFIRMED","note":"legible"}'
                    else:
                        text = "ok"
                    return FakeMessage(content=[FakeTextBlock(text=text)],
                                       usage=FakeUsage(input_tokens=50, output_tokens=10))

            self.messages = _Msgs()

    src = _make_pdf(tmp_path / "M-101.pdf", pymupdf)
    ctx = extract_drawing_context(
        [src], client=_Client(), rows=2, cols=2,
        reference_audit=True, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    arith = {f.source_quote: f for f in ctx.all_findings
             if "auditor_arithmetic" in f.sources}
    assert set(arith) == {"20 x 2 = 40", "SEE FP101 TOTAL 540 AT 439 GPM",
                          "TOTAL 100 + 250 = 375"}

    # Each unstated relationship was crop-verified once and keeps its caveat.
    for quote, computed in (("20 x 2 = 40", "the sum of 20, 2 is 22"),
                            ("SEE FP101 TOTAL 540 AT 439 GPM", "the sum of 101, 540 is 641")):
        f = arith[quote]
        assert sum(computed in t for t in verify_texts) == 1, quote
        assert f.verification.status == "VERIFIED"
        assert f.verification.operand_origin == "MODEL_TRANSCRIBED"
        assert _trust_note(f, unverified=False, rejected=False) == TRANSCRIBED_NOTE

    # The stated one is still ground truth and never re-checked.
    stated = arith["TOTAL 100 + 250 = 375"]
    assert not any("the sum of 100, 250 is 350" in t for t in verify_texts)
    assert _trusted(stated)
    assert ctx.audit_stats["arithmetic_mismatched"] == 3
