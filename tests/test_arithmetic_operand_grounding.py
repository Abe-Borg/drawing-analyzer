"""Remediation WP-07.1 (N3): arithmetic operands are trusted only when the sheet
prints them, once per use, where the claim's quote anchors.

The arithmetic auditor computes a claim's relationship with ``Decimal`` and
reports a mismatch. Whether that mismatch is ground truth (``DETERMINISTIC``,
``operand_origin=TEXT_EXTRACTED``: it skips verification and inks as "Math
checked by computer from the sheet's own printed numbers") or a host
computation over numbers the model transcribed (``UNCERTAIN``,
``MODEL_TRANSCRIBED``: crop-verified first) used to be decided from the model's
quote string alone, before anchoring, by set membership:

* one printed ``20`` supported any number of transcribed ``20`` operands, so
  ``sum [20, 20, 20] = 40`` on the quote ``20 + 20 = 40`` was DETERMINISTIC at
  high severity, anchored EXACT;
* a quote the sheet does not carry (UNANCHORED), and a claim that resolved to
  no sheet at all, were DETERMINISTIC too: nothing looked at the sheet;
* the stated result could reuse a term's printed number (``20 + 30`` "states"
  a total of 20).

Decided with the owner (WP-07.1 handoff): provenance is decided after the
auditor's own anchoring pass, and an operand is grounded only when

1. the claim resolved to a sheet, and its quote anchored there EXACT or FUZZY
   by a method that carries the numeric veto (never TILE, never UNANCHORED);
2. the terms and the stated result together fit the printed numbers, one
   occurrence each (the result needs its own occurrence);
3. both the quote and the sheet's own words under the matched span print it
   (per value, the smaller count).

Pure where it can be (synthetic words, no PyMuPDF); the pipeline test at the
end renders a PDF and skips without PyMuPDF. Hermetic: no network.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from drawing_analyzer.auditors import run_auditors
from drawing_analyzer.auditors.arithmetic import audit_arithmetic
from drawing_analyzer.models import (
    Anchor,
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


def _one(claim, sheets):
    res = audit_arithmetic([claim], sheets)
    assert res.checked == 1 and res.mismatched == 1 and len(res.findings) == 1
    return res.findings[0]


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
# N3 core: one printed number supports one operand
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "printed",
    [["20", "+", "20", "=", "40"], ["20", "20", "TOTAL", "40"]],
    ids=["20+20=40", "20-20-TOTAL-40"],
)
def test_one_printed_operand_cannot_support_two_transcribed_ones(printed):
    """The review's case: the sheet prints a correct ``20 + 20 = 40``; the model
    transcribes a third ``20``. The host's sum (60) disagrees with 40, and the
    old membership test found every operand "present", so the correct equation
    got a high-severity DETERMINISTIC mismatch."""
    quote = " ".join(printed)
    f = _one(_claim("sum", [20, 20, 20], 40, quote), [_sheet(_row(printed))])
    assert _transcribed(f), f.verification
    # The finding itself is unchanged: still anchored on the quote, still the
    # same text, severity and id. Only the trust label moved.
    assert f.anchor.status == "EXACT" and f.anchor.rect_pdf is not None
    assert f.severity == "high"
    assert f.text.startswith("Arithmetic does not check out: the sum of 20, 20, 20 is 60")
    assert f.id == compute_finding_id(
        f.sheet_id, "conflict", quote, f.source_id, f.claim_discriminator,
    )


def test_genuinely_repeated_operands_stay_deterministic():
    """Three printed 20s support three 20s: a real flow-test column still
    reads as ground truth."""
    printed = ["20", "20", "20", "TOTAL", "540"]
    f = _one(_claim("sum", [20, 20, 20], 540, " ".join(printed)), [_sheet(_row(printed))])
    assert _trusted(f), f.verification


def test_equal_values_count_as_one_number_whatever_their_spelling():
    printed = ["20.0", "+", "20", "=", "50"]
    f = _one(_claim("sum", ["20", 20.0], 50, " ".join(printed)), [_sheet(_row(printed))])
    assert _trusted(f), f.verification


def test_the_stated_result_needs_its_own_printed_occurrence():
    """``20 + 30`` states no total. Reusing the term's printed 20 as "the sheet
    states 20" invents a figure the sheet never gave."""
    printed = ["20", "+", "30"]
    f = _one(_claim("sum", [20, 30], 20, "20 + 30"), [_sheet(_row(printed))])
    assert _transcribed(f), f.verification


def test_a_result_printed_in_its_own_right_is_still_trusted():
    """``20 + 30 = 20`` prints the 20 twice: once as a term, once as the (wrong)
    total. The occurrence rule is not a rule against equal values."""
    printed = ["20", "+", "30", "=", "20"]
    f = _one(_claim("sum", [20, 30], 20, "20 + 30 = 20"), [_sheet(_row(printed))])
    assert _trusted(f), f.verification


# --------------------------------------------------------------------------- #
# Grounding: the quote must anchor on the claim's own sheet
# --------------------------------------------------------------------------- #


def test_a_fabricated_quote_is_never_deterministic():
    """The quote carries every operand, but the sheet does not carry the quote:
    it anchors nowhere (the hallucination signal) and must not ink as a
    computer-checked fact."""
    sheet = _sheet(_row(["20", "+", "20", "=", "40"]))
    f = _one(_claim("sum", [20, 20, 20], 40, "20 + 20 + 20 = 40"), [sheet])
    assert f.anchor.status == "UNANCHORED"
    assert _transcribed(f), f.verification


def test_a_quote_printed_only_on_another_sheet_does_not_ground_the_claim():
    here = _sheet(_row(["FLOW", "TEST"]), source="a.pdf", sheet_id="F-D-01-1")
    there = _sheet(_row(["20", "+", "20", "=", "50"]), source="b.pdf", sheet_id="F-D-01-2")
    claim = _claim("sum", [20, 20], 50, "20 + 20 = 50", source="a.pdf")
    f = _one(claim, [here, there])
    assert f.source_name == "a.pdf" and f.anchor.status == "UNANCHORED"
    assert _transcribed(f), f.verification


@pytest.mark.parametrize("with_set", [True, False], ids=["id-not-in-set", "no-sheets"])
def test_a_claim_on_an_unresolved_sheet_is_never_deterministic(with_set):
    """No geometry, no anchoring, nothing on a sheet was looked at: the quote
    carries every operand, and that alone is the model's word for it."""
    sheets = [_sheet(_row(["20", "+", "20", "=", "50"]))] if with_set else []
    claim = NumericClaim(sheet_id="Z-999", quote="20 + 20 = 50", kind="sum",
                         terms=[20, 20], expected=50)
    f = _one(claim, sheets)
    assert f.anchor is None or f.anchor.rect_pdf is None
    assert _transcribed(f), f.verification


def test_a_quote_printed_twice_on_its_sheet_still_grounds_the_claim():
    """``exact_ambiguous``: every occurrence prints the same numbers."""
    words = (_row(["100", "+", "250", "=", "375"], y=300)
             + _row(["100", "+", "250", "=", "375"], y=900))
    f = _one(_claim("sum", [100, 250], 375, "100 + 250 = 375"), [_sheet(words)])
    assert f.anchor.status == "EXACT" and f.anchor.method == "exact_ambiguous"
    assert _trusted(f), f.verification


def test_a_fuzzy_anchor_with_the_numeric_veto_grounds_its_operands():
    """One non-numeric token differs (``TESTS`` against ``TEST``): the sliding
    window anchors FUZZY and places every number of the quote on its own sheet
    token, so the operands are grounded.

    It read ``TEST:`` until remediation WP-05.2, which folds sentence
    punctuation off every word, so a colon no longer differs: that quote now
    anchors EXACT (``tests/test_anchor_whole_words.py``)."""
    printed = ["FLOW", "TEST", "20", "20", "20", "TOTAL", "540", "GPM", "AT", "RISER", "3"]
    quote = "FLOW TESTS 20 20 20 TOTAL 540 GPM AT RISER 3"
    f = _one(_claim("sum", [20, 20, 20], 540, quote), [_sheet(_row(printed))])
    assert (f.anchor.status, f.anchor.method) == ("FUZZY", "fuzzy_window")
    assert _trusted(f), f.verification


def test_the_quote_bounds_the_support_even_where_the_sheet_prints_more():
    """The window anchors a quote that dropped one of the sheet's three 20s. The
    claim's third 20 was never in the text the model offered as its evidence,
    so the quote's two 20s are all the support there is."""
    printed = ["FLOW", "20", "20", "20", "TOTAL", "40", "GPM", "AT", "RISER"]
    quote = "FLOW 20 20 TOTAL 40 GPM AT RISER"
    f = _one(_claim("sum", [20, 20, 20], 40, quote), [_sheet(_row(printed))])
    assert f.anchor.status == "FUZZY"
    assert _transcribed(f), f.verification


def test_the_sheet_must_print_the_operand_the_quote_reads():
    """The quote reads a number the sheet does not print there. The sheet
    writes ``2½" + 2½" = 4"`` and the model quoted ``2-1/2" + 2-1/2" = 4"``,
    which anchors EXACT (the anchor's normalizer folds the vulgar fraction), but
    the sheet's own words under the span do not print a 2-1/2 the host reads as
    one value (a vulgar fraction glued to a digit is refused). Counting the
    quote alone trusted it.

    The case used to be a quote that starts in the middle of a printed
    dimension (``1/2" + 2 1/2" = 4"`` on ``2-1/2" + 2-1/2" = 4"``), which
    anchored EXACT from the dimension's second half on. Since remediation
    WP-05.2 a match covers whole source words, so that quote does not anchor at
    all (N12), and stays model-transcribed."""
    printed = ['2\u00bd"', "+", '2\u00bd"', "=", '4"']
    quote = '2-1/2" + 2-1/2" = 4"'
    f = _one(_claim("sum", ["2-1/2", "2-1/2"], 4, quote), [_sheet(_row(printed))])
    assert f.anchor.status == "EXACT"
    assert _transcribed(f), f.verification

    cut = _one(_claim("sum", ["1/2", "2 1/2"], 4, '1/2" + 2 1/2" = 4"'),
               [_sheet(_row(['2-1/2"', "+", '2-1/2"', "=", '4"']))])
    assert cut.anchor.status == "UNANCHORED"
    assert _transcribed(cut), cut.verification


# --------------------------------------------------------------------------- #
# The anchor module's side of the rule (new API: imported inside the tests)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "status, method, grounded",
    [
        ("EXACT", "exact", True),
        ("EXACT", "exact_ambiguous", True),
        ("FUZZY", "fuzzy_window", True),
        ("FUZZY", "fuzzy_subphrase", True),
        ("FUZZY", "some_future_method", False),    # fail closed until it carries the veto
        ("TILE", "tile", False),
        ("TILE", "tile_no_text_evidence", False),
        ("UNANCHORED", "quote_not_found", False),
        ("UNANCHORED", "no_quote_no_tile", False),
    ],
)
def test_only_a_numeric_vetoed_quote_match_grounds_numbers(status, method, grounded):
    from drawing_analyzer.anchor import numbers_grounded

    rect = None if status == "UNANCHORED" else [0.0, 0.0, 10.0, 10.0]
    assert numbers_grounded(Anchor(status=status, rect_pdf=rect, method=method)) is grounded
    assert numbers_grounded(None) is False


def test_resolve_anchors_reports_the_sheet_words_each_quote_matched():
    from drawing_analyzer.anchor import resolve_anchors

    words = _row(["2-1/2\"", "+", "2-1/2\"", "=", '4"', "FLOW", "TEST"])
    sheet = _sheet(words)

    def _f(quote, **kw):
        return Finding(sheet_id=SHEET_ID, source_name="s.pdf", page_index=0,
                       category="conflict", severity="low", text="t",
                       source_quote=quote, **kw)

    exact = _f('2 1/2" + 2 1/2" = 4"')
    missing = _f("NOT ON THIS SHEET AT ALL")
    graphics = _f("", tile=[0, 0])
    pre = _f("FLOW TEST", anchor=Anchor(status="EXACT", rect_pdf=[1, 1, 2, 2], method="t"))
    plain = [_f(q.source_quote, tile=q.tile) for q in (exact, missing, graphics)]

    matched: dict[int, str] = {}
    resolve_anchors([exact, missing, graphics, pre], sheet, matched_text=matched)
    resolve_anchors(plain, sheet)

    # Whole source words, as printed, in reading order: the quote writes each
    # dimension ``2 1/2"`` and the sheet ``2-1/2"``, which is what is reported.
    # (The quote used to start inside the first dimension, ``1/2" + 2 1/2"``;
    # since remediation WP-05.2 a match covers whole words, so that one does
    # not anchor.)
    assert matched == {id(exact): '2-1/2" + 2-1/2" = 4"'}
    # The keyword changes no anchor.
    for a, b in zip((exact, missing, graphics), plain):
        assert a.anchor == b.anchor
    assert pre.anchor.method == "t"          # already anchored: left alone, no text


# --------------------------------------------------------------------------- #
# What the change reaches downstream
# --------------------------------------------------------------------------- #


def test_an_ungrounded_mismatch_goes_to_the_crop_verifier():
    """DETERMINISTIC is terminal for verification; the N3 finding is anchored,
    so as UNCERTAIN it is exactly what the single-crop pass re-checks."""
    from drawing_analyzer.verify import _is_verifiable

    printed = ["20", "+", "20", "=", "40"]
    sheet = _sheet(_row(printed))
    n3 = _one(_claim("sum", [20, 20, 20], 40, " ".join(printed)), [sheet])
    assert _is_verifiable(n3) is True
    # Unanchored, it has no crop to check, and it is no longer trusted either.
    fabricated = _one(_claim("sum", [20, 20, 20], 40, "20 + 20 + 20 = 40"), [sheet])
    assert _is_verifiable(fabricated) is False and not _trusted(fabricated)
    # A grounded mismatch stays terminal: ground truth is not re-checked.
    grounded = _one(
        _claim("sum", [20, 20], 50, "20 + 20 = 50"),
        [_sheet(_row(["20", "+", "20", "=", "50"]))],
    )
    assert _trusted(grounded) and _is_verifiable(grounded) is False


def test_the_reviewer_reads_the_re_check_caveat_not_computer_checked():
    from drawing_analyzer.annotate import _trust_note

    printed = ["20", "+", "20", "=", "40"]
    sheet = _sheet(_row(printed))
    n3 = _one(_claim("sum", [20, 20, 20], 40, " ".join(printed)), [sheet])
    fabricated = _one(_claim("sum", [20, 20, 20], 40, "20 + 20 + 20 = 40"), [sheet])
    real = _one(
        _claim("sum", [20, 20], 50, "20 + 20 = 50"),
        [_sheet(_row(["20", "+", "20", "=", "50"]))],
    )
    for f in (n3, fabricated):
        assert _trust_note(f, unverified=True, rejected=False) == TRANSCRIBED_NOTE
    assert _trust_note(real, unverified=False, rejected=False) == TRUSTED_NOTE


def test_run_auditors_keeps_the_tally_and_both_verdicts():
    printed = ["20", "+", "20", "=", "40"]
    sheet = _sheet(_row(printed) + _row(["100", "+", "250", "=", "375"], y=900))
    res = run_auditors([sheet], claims=[
        _claim("sum", [20, 20, 20], 40, "20 + 20 = 40"),        # N3
        _claim("sum", [100, 250], 375, "100 + 250 = 375"),      # grounded
        _claim("sum", [20, 20], 40, "20 + 20 = 40"),            # matches
    ])
    arith = {f.source_quote: f for f in res.findings if "auditor_arithmetic" in f.sources}
    assert res.stats["arithmetic_checked"] == 3
    assert res.stats["arithmetic_matched"] == 1
    assert res.stats["arithmetic_mismatched"] == len(arith) == 2
    assert _transcribed(arith["20 + 20 = 40"])
    assert _trusted(arith["100 + 250 = 375"])


def test_the_verification_note_keeps_its_wording_for_each_provenance():
    """``investigate._payload_hash`` keys an investigation on the prior note, so
    the note must read exactly as before for each provenance: a finding that
    stays model-transcribed keeps its cached investigation, and a finding that
    is newly model-transcribed was never investigated (it was DETERMINISTIC)."""
    printed = ["20", "+", "20", "=", "40"]
    n3 = _one(_claim("sum", [20, 20, 20], 40, " ".join(printed)), [_sheet(_row(printed))])
    real = _one(
        _claim("sum", [20, 20], 50, "20 + 20 = 50"),
        [_sheet(_row(["20", "+", "20", "=", "50"]))],
    )
    assert n3.verification.note == (
        "computed sum of terms = 60; stated = 40 "
        "(host-computed from model-transcribed terms — verify against the sheet)"
    )
    assert real.verification.note == (
        "computed sum of terms = 40; stated = 50 "
        "(operands text-extracted from the sheet quote)"
    )


# --------------------------------------------------------------------------- #
# Fail safe: a failure while deciding never trusts, and never loses the rest
# --------------------------------------------------------------------------- #


def test_an_anchoring_failure_on_one_sheet_leaves_its_findings_uncertain(monkeypatch):
    import drawing_analyzer.anchor as anchor_mod

    real = anchor_mod.resolve_anchors

    def _flaky(findings, rendered_sheet, **kw):
        if rendered_sheet.ref.source_name == "bad.pdf":
            raise RuntimeError("synthetic anchoring failure")
        return real(findings, rendered_sheet, **kw)

    monkeypatch.setattr(anchor_mod, "resolve_anchors", _flaky)
    good = _sheet(_row(["100", "+", "250", "=", "375"]), source="good.pdf")
    bad = _sheet(_row(["100", "+", "250", "=", "375"]), source="bad.pdf", sheet_id="F-D-01-2")
    res = audit_arithmetic([
        _claim("sum", [100, 250], 375, "100 + 250 = 375", source="good.pdf"),
        _claim("sum", [100, 250], 375, "100 + 250 = 375", source="bad.pdf",
               sheet_id="F-D-01-2"),
    ], [good, bad])
    assert res.mismatched == len(res.findings) == 2
    by_source = {f.source_name: f for f in res.findings}
    assert _trusted(by_source["good.pdf"])
    assert _transcribed(by_source["bad.pdf"])


def test_a_failure_deciding_one_findings_provenance_leaves_it_uncertain(monkeypatch):
    from drawing_analyzer.auditors import arithmetic as arith

    real = arith._operands_grounded

    def _flaky(terms, expected, quote, matched_text):
        if expected == Decimal(375):
            raise RuntimeError("synthetic failure while deciding provenance")
        return real(terms, expected, quote, matched_text)

    monkeypatch.setattr(arith, "_operands_grounded", _flaky)
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
# End to end: the pipeline sends the N3 mismatch to the crop verifier
# --------------------------------------------------------------------------- #


def _make_pdf(path: Path, pymupdf) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "FLOW TEST 20 + 20 = 40")
    page.insert_text((80, 200), "TOTAL 100 + 250 = 375")
    page.insert_text((650, 560), "M-101")
    doc.save(str(path))
    doc.close()
    return path


def test_the_pipeline_crop_verifies_the_n3_mismatch_and_trusts_the_grounded_one(tmp_path):
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
        {"sheet_id": "M-101", "quote": "20 + 20 = 40", "kind": "sum",
         "terms": [20, 20, 20], "expected": 40, "note": "flow test"},
        {"sheet_id": "M-101", "quote": "TOTAL 100 + 250 = 375", "kind": "sum",
         "terms": [100, 250], "expected": 375, "note": "column total"},
    ]
    digest_text = (
        "Sheet M-101 - Mechanical - Plan\nFlow test and totals.\n\n"
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
    assert set(arith) == {"20 + 20 = 40", "TOTAL 100 + 250 = 375"}
    n3, grounded = arith["20 + 20 = 40"], arith["TOTAL 100 + 250 = 375"]

    # The N3 mismatch was sent to the crop verifier (once) and keeps its
    # provenance through the verdict; the popup still says to re-check the math.
    assert sum("the sum of 20, 20, 20 is 60" in t for t in verify_texts) == 1
    assert n3.verification.status == "VERIFIED"
    assert n3.verification.operand_origin == "MODEL_TRANSCRIBED"
    assert _trust_note(n3, unverified=False, rejected=False) == TRANSCRIBED_NOTE

    # The grounded mismatch is still ground truth and never re-checked.
    assert not any("the sum of 100, 250 is 350" in t for t in verify_texts)
    assert _trusted(grounded)
    assert ctx.audit_stats["arithmetic_mismatched"] == 2
