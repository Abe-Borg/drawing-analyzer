"""Remediation WP-05.2: the anchor matches whole source words, punctuation folded.

Two defects in the anchor resolver (``anchor.resolve_anchors``), which places
each finding's quote on its sheet and so decides what is clouded, what reaches
verification and investigation, and which arithmetic operands are trusted:

- **B4 (its punctuation part).** Each PDF word was tokenized with its
  punctuation glued on (``psi,``, ``(568``, ``min)``, ``3:``), so a quote that is
  verbatim sheet text apart from that punctuation went UNANCHORED: excluded from
  verification and investigation, and inked as the hallucination signal
  ``[QUOTE NOT FOUND]``.
- **N12 (its anchor part).** ``_normalize`` turns an infix hyphen into a space,
  so ``VAV-2-1`` is the tokens ``vav 2 1``, and a quote's tokens matched the
  start, end or middle of one PDF word: ``VAV-2`` EXACT-matched inside
  ``VAV-2-1``, and the wrong equipment was clouded.

The rules, decided by the owner before any code:

- **Whole source words in every tier.** The WP-05.1 rule (``anchor.word_core``)
  applied to the anchor: EXACT and the sub-phrase tier match only whole words,
  through the matcher cross-QC uses; a fuzzy window must start and end on a
  word; and inside a window a quote's number may not match part of a sheet word
  (``VAV-2`` against ``VAV-2-1``, ``1/2"`` against ``2-1/2"``).
- **Brackets and sentence punctuation fold** off every word, on the sheet and in
  the quote alike: leading ``( [ {``, trailing ``) ] } , ; : . ! ?``. Never
  ``"`` or ``'`` (inch and foot marks), ``<`` or ``>`` (comparisons), ``%``,
  ``/``, ``-``, or a leading ``.`` (a decimal point).
- **One matcher.** Cross-QC grounds through it too
  (``_CROSS_QC_CACHE_CONTRACT`` 4 -> 5), so the two agree.
- **A folded match is still EXACT / ``exact``.** It shows the quote's numbers
  are printed there, so the arithmetic auditor may trust them.

Hermetic: fake clients only, no key, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer.anchor import numbers_grounded, resolve_anchors, resolve_conflict_legs
from drawing_analyzer.auditors.arithmetic import audit_arithmetic
from drawing_analyzer.cross_qc import (
    CrossQCDiscardCounts,
    _finding_from_handles,
    _parse_facts,
    classify_quote_evidence,
)
from drawing_analyzer.investigate import _candidates
from drawing_analyzer.models import (
    EVIDENCE_TEXT_GROUNDED,
    ConflictLeg,
    MODEL_TRANSCRIBED,
    TEXT_EXTRACTED,
    Finding,
    NumericClaim,
    SheetGeometry,
    SheetRef,
    Verification,
)
from drawing_analyzer.verify import _has_anchored_legs, _is_verifiable
from tests.test_cross_qc_grounding import _CHANGED, _CUT_A_WORD, _SAME_TEXT, _WHOLE_WORDS

W, H = 3168.0, 2448.0


def _w(x, y, text, width=60, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _line(text: str, y: float = 100.0) -> list:
    return [_w(100 + 70 * i, y, t) for i, t in enumerate(text.split())]


def _sheet(words, source: str = "m.pdf") -> SheetGeometry:
    """One sheet for both matchers: its words for the anchor, their text for cross-QC."""
    text = " ".join(str(w[4]) for w in words)
    return SheetGeometry(
        ref=SheetRef(pdf_path=Path(source), page_index=0, source_name=source, page_count=1),
        page_width_pt=W, page_height_pt=H, rows=6, cols=6, words=list(words),
        sheet_text=text, full_sheet_text=text, is_raster=not text,
    )


def _finding(quote: str, **kw) -> Finding:
    return Finding(sheet_id="M-101", source_name="m.pdf", page_index=0, category="code",
                   severity="high", text="t", source_quote=quote, **kw)


def _place(quote: str, words: list, **kw):
    """The anchor ``quote`` gets on ``words``, and the sheet's words it covers."""
    f = _finding(quote, **kw)
    matched: dict = {}
    resolve_anchors([f], _sheet(words), matched_text=matched)
    return f.anchor, matched.get(id(f))


# --------------------------------------------------------------------------- #
# B4: brackets and sentence punctuation fold off a word
# --------------------------------------------------------------------------- #

_B4 = [
    # (quote, the sheet's line, the sheet's words the match covers, as printed)
    ("RATED 175 PSI TYP", "RATED 175 PSI, TYP.", "RATED 175 PSI, TYP."),
    ("NOTE 3", "SEE NOTE 3: PROVIDE ACCESS", "NOTE 3:"),
    ("150 GPM 568 L/MIN", "FLOW 150 GPM (568 L/MIN) AT", "150 GPM (568 L/MIN)"),
    ("P-1", "SEE P-1, TYP", "P-1,"),
    ("P-1", "SEE (P-1), TYP", "(P-1),"),
    ("VERIFY IN FIELD", "NOTE: VERIFY IN FIELD!", "VERIFY IN FIELD!"),
    ("R-1", "SEE {R-1}; TYP", "{R-1};"),
    ("REF 2", "[REF 2] BELOW", "[REF 2]"),
]


@pytest.mark.parametrize(("quote", "text", "span"), _B4)
def test_b4_a_quote_verbatim_but_for_punctuation_anchors_exact(quote, text, span):
    anchor, matched = _place(quote, _line(text))
    assert (anchor.status, anchor.method) == ("EXACT", "exact")
    assert matched == span, "the sheet's own words, punctuation and all"


_QUOTE_SIDE = [
    # The quote carries the punctuation and the sheet does not: folded alike.
    ("P-1,", "SEE P-1 TYP", "P-1"),
    ("NOTE 3:", "SEE NOTE 3 PROVIDE", "NOTE 3"),
    ("(568 L/MIN)", "FLOW 150 GPM 568 L/MIN AT", "568 L/MIN"),
    ("RATED 175 PSI, TYP.", "RATED 175 PSI TYP", "RATED 175 PSI TYP"),
]


@pytest.mark.parametrize(("quote", "text", "span"), _QUOTE_SIDE)
def test_b4_the_quotes_own_edge_punctuation_folds_too(quote, text, span):
    anchor, matched = _place(quote, _line(text))
    assert (anchor.status, anchor.method, matched) == ("EXACT", "exact", span)


_KEPT_OUTSIDE = [
    # word_core at a match's two ends: the sheet's " ' < > may stay outside the
    # match, as cross-QC has allowed since WP-05.1. They never fold INSIDE one.
    ("P-1", 'SEE "P-1" TYP', '"P-1"'),
    ("PROVIDE 6", 'PROVIDE 6" DRAIN', 'PROVIDE 6"'),
    ("5 PSI", "SET <5 PSI MAX", "<5 PSI"),
]


@pytest.mark.parametrize(("quote", "text", "span"), _KEPT_OUTSIDE)
def test_b4_a_quote_mark_or_comparison_at_a_matchs_end_stays_outside(quote, text, span):
    anchor, matched = _place(quote, _line(text))
    assert (anchor.status, anchor.method, matched) == ("EXACT", "exact", span)


def test_b4_a_lone_punctuation_word_says_nothing():
    """Extraction can print a comma as its own word; it folds to nothing."""
    anchor, matched = _place("RATED 175 PSI TYP", _line("RATED 175 PSI , TYP ."))
    assert (anchor.status, anchor.method) == ("EXACT", "exact")
    assert matched == "RATED 175 PSI TYP"


def test_b4_a_verbatim_quote_anchors_as_before():
    for text in ("RATED 175 PSI, TYP.", "SEE NOTE 3: PROVIDE", "FLOW 150 GPM (568 L/MIN) AT"):
        anchor, matched = _place(text, _line(text))
        assert (anchor.status, anchor.method, matched) == ("EXACT", "exact", text)


def test_b4_the_numeric_veto_compares_folded_words():
    """A window whose sheet glues punctuation to a number (``500,``): the veto
    finds the quote's ``500`` there. One word is misspelled, so it is a window."""
    sheet = "FIRE PUMP RATED AT 500, GPM AND 100 PSI NET."
    anchor, matched = _place("FIRE PUMP RATED AT 500 GPM AND 100 PSI NETT", _line(sheet))
    assert (anchor.status, anchor.method) == ("FUZZY", "fuzzy_window")
    assert matched == sheet


def test_b4_the_numeric_veto_still_refuses_a_substitution_on_punctuated_text():
    """Every substitution the veto refuses is refused with the sheet's
    punctuation folded, and the true quote anchors EXACT there."""
    from tests.test_drawing_anchor import SUBSTITUTIONS

    sheet = _line("PROVIDE 6 INCH DRAIN, AT COLUMN LINE 4.")
    for quote, what in SUBSTITUTIONS:
        assert _place(quote, sheet)[0].status == "UNANCHORED", what
    assert _place("PROVIDE 6 INCH DRAIN AT COLUMN LINE 4", sheet)[0].status == "EXACT"


_NEVER = [
    ('6"', "PROVIDE 6' CLEARANCE"),              # an inch mark is not a foot mark
    ("6'", 'PROVIDE 6" CLEARANCE'),
    ('PROVIDE 6" DRAIN', "PROVIDE 6' DRAIN"),
    ("5", "SET AT .5 IN"),                        # a leading decimal point
    (".5", "SET AT 5 IN"),
    ("5", "ELEV -5 FT"),                          # a sign
    ("-5", "ELEV 5 FT"),
    ("30", "OPEN AREA 30% MIN"),                  # a percent
    ("12", "12,500 CFM"),                         # a thousands group
    ("12", "CLG 12'-6\" AFF"),                    # feet and inches
    ("AHU-10", "SEE AHU-101 SCHEDULE"),           # a longer tag
    ("P-1", "PUMP P-10 TYP"),
    ("P-1 SERVES", "XP-1 SERVES"),
    ("RATED 175 PSI TYP", "RATED 165 PSI, TYP."),   # a changed number
    ("RATED 175 PSIG TYP", "RATED 175 PSI, TYP."),  # a changed unit
    ("NOTE 4", "SEE NOTE 3: PROVIDE ACCESS"),
    ("SET 5 PSI", "SET <5 PSI"),                  # < never folds inside a match
]


@pytest.mark.parametrize(("quote", "text"), _NEVER)
def test_negatives_never_anchor(quote, text):
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)


# --------------------------------------------------------------------------- #
# N12: whole source words, in every tier
# --------------------------------------------------------------------------- #

_INSIDE_A_LONGER_TAG = [
    ("VAV-2", "VAV-2-1 SERVES ROOM 12"),
    ("AHU-1", "SEE AHU-1-2 SCHEDULE"),
    ("ACCESS PANEL AT VAV-2", "PROVIDE ACCESS PANEL AT VAV-2-1 TYP"),
    ("2-1 SERVES", "VAV-2-1 SERVES ROOM"),        # starts inside a word
]


@pytest.mark.parametrize(("quote", "text"), _INSIDE_A_LONGER_TAG)
def test_n12_a_quote_that_cuts_a_word_never_anchors(quote, text):
    """Each was EXACT on the longer tag. Refused by EXACT alone, each would fall
    through to the window at 100% overlap, so the window's edges are bounded too."""
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)


_NOTE = "PROVIDE ACCESS PANEL AT {} FOR SERVICE OF THE DAMPER ACTUATOR AND CONTROLS PER DETAIL 4"


@pytest.mark.parametrize(("quoted", "printed"), [("VAV-2", "VAV-2-1"), ("AHU-1", "AHU-1-2")])
def test_n12_a_window_never_puts_a_tag_inside_a_longer_one(quoted, printed):
    """17 tokens. The window leaves out one quote word and takes in the tag's
    extra number; its edges are whole words, so only the word veto refuses it."""
    anchor, matched = _place(_NOTE.format(quoted), _line(_NOTE.format(printed)))
    assert anchor.status == "UNANCHORED", (anchor, matched)


def test_n12_a_window_never_puts_a_fraction_inside_a_mixed_number():
    """``1/2"`` is not the second half of ``2-1/2"``: a pipe size."""
    anchor, matched = _place('PROVIDE 1/2" PIPE AT COLUMN LINE 4 AND 5',
                             _line('PROVIDE 2-1/2" PIPE AT COLUMN LINE 4 AND 5'))
    assert anchor.status == "UNANCHORED", (anchor, matched)


def test_n12_a_sub_phrase_never_starts_inside_a_word():
    """No window fits (the quote is longer than the sheet's line); the only
    sub-phrase holding the quote's numbers started inside ``VAV-2-1``."""
    anchor, matched = _place("PER NOTE 2-1 SERVES ROOM 12 MAXIMUM", _line("VAV-2-1 SERVES ROOM 12"))
    assert anchor.status == "UNANCHORED", (anchor, matched)


@pytest.mark.parametrize("alone_first", [True, False])
def test_n12_a_tag_printed_alone_and_inside_a_longer_one_anchors_alone(alone_first):
    """Not ambiguous any more: only the one printed alone is a whole-word match."""
    alone, longer = _line("VAV-2 SERVES ROOM 14", y=900), _line("VAV-2-1 SERVES ROOM 12", y=100)
    anchor, matched = _place("VAV-2", alone + longer if alone_first else longer + alone)
    assert (anchor.status, anchor.method, matched) == ("EXACT", "exact", "VAV-2")
    assert anchor.rect_pdf[1] > 800, "the tag printed alone, at y=900"


def test_n12_a_quote_that_cut_the_start_of_a_word_is_not_exact_on_it():
    """``ACTION`` is not ``PRE-ACTION``: the quote anchors on the words it covers whole."""
    anchor, matched = _place("ACTION VALVE PV-3 SERVES DATA HALL 2",
                             _line("PRE-ACTION VALVE PV-3 SERVES DATA HALL 2"))
    assert (anchor.status, anchor.method) == ("FUZZY", "fuzzy_subphrase")
    assert matched == "VALVE PV-3 SERVES DATA HALL 2"


_KEPT = [
    # (quote, the sheet's line, the tier): the rule refuses none of these.
    ("VAV-2-1 SERVES", "VAV-2-1 SERVES ROOM", "EXACT"),
    ("VAV-3 SERVES", "VAV 3 SERVES", "EXACT"),
    ('2 1/2" PIPE', '2-1/2" PIPE', "EXACT"),
    # The sheet prints an extra word; the window covers whole words.
    ("PROVIDE 6 INCH DRAIN AT COLUMN LINE 4", "PROVIDE 6-INCH DIA DRAIN AT COLUMN LINE 4", "FUZZY"),
    # The quote abbreviates a word of a hyphenated one; its number is whole.
    ("PROVIDE 6 IN DRAIN AT COLUMN LINE 4", "PROVIDE 6-INCH DRAIN AT COLUMN LINE 4", "FUZZY"),
    # The sheet prints a number the quote left out, as its own word.
    ("FIRE PUMP RATED 500 GPM AT 100 PSI NET PRESSURE PER NFPA 20 SECTION",
     "FIRE PUMP RATED 500 GPM AT 100 PSI (689 KPA) NET PRESSURE PER NFPA 20", "FUZZY"),
]


@pytest.mark.parametrize(("quote", "text", "status"), _KEPT, ids=[f"kept{i}" for i in range(len(_KEPT))])
def test_n12_whole_word_matches_still_anchor(quote, text, status):
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == status, (anchor, matched)


@pytest.mark.parametrize(("quote", "text"), _CUT_A_WORD)
def test_n12_the_wp_05_1_cut_word_table_never_anchors(quote, text):
    """WP-05.1's cross-QC table, through the anchor."""
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)


@pytest.mark.parametrize(("quote", "text"), _WHOLE_WORDS)
def test_n12_the_wp_05_1_whole_word_table_anchors_exact(quote, text):
    anchor, _ = _place(quote, _line(text))
    assert (anchor.status, anchor.method) == ("EXACT", "exact")


def test_recorded_limit_a_letter_only_tag_inside_a_long_window():
    """The word veto reads numbers, so a quote naming ``VAV-A`` still anchors
    FUZZY on ``VAV-A-1`` inside a 17-token note (decided: the other veto, "a
    window may add no number", also refused a window whose sheet prints a
    conversion the quote left out)."""
    anchor, matched = _place(_NOTE.format("VAV-A"), _line(_NOTE.format("VAV-A-1")))
    assert (anchor.status, anchor.method) == ("FUZZY", "fuzzy_window")
    assert "VAV-A-1" in matched


@pytest.mark.parametrize(("quote", "text"), [
    ('PROVIDE 6" DRAIN', 'PROVIDE 6 " DRAIN'),          # a separated inch mark
    ("PROVIDE INCH DRAIN", "PROVIDE INCHDRAIN"),          # words merged by extraction
    ("CLG 12'-6\" AFF", "CLG 12' - 6\" AFF"),             # split feet and inches
    ("SLOPE 2% MIN", "SLOPE 2 % MIN"),                    # a separated percent mark
], ids=["inch", "merged", "feet", "percent"])
def test_recorded_limit_the_character_stream_cases_are_wp_05_3s(quote, text):
    """B4's other four pairs need a character-stream tier with a quantity-aware
    veto (remediation WP-05.3), which flips these."""
    assert _place(quote, _line(text))[0].status == "UNANCHORED"


def test_recorded_limit_a_sub_phrase_can_drop_a_separated_unit():
    """Present before this slice for unbracketed text; the fold extends it to a
    bracketed number. The veto reads numbers, not their separated units
    (WP-05.3's quantity-aware veto)."""
    anchor, matched = _place("150 GPM 568 L/S", _line("FLOW 150 GPM (568 L/MIN) AT"))
    assert (anchor.status, anchor.method) == ("FUZZY", "fuzzy_subphrase")
    assert matched == "150 GPM (568"


# --------------------------------------------------------------------------- #
# One matcher: the anchor and cross-QC agree
# --------------------------------------------------------------------------- #

_AGREEMENT = (
    _CUT_A_WORD + _WHOLE_WORDS + _SAME_TEXT + _CHANGED
    + [(q, t) for q, t, _ in _B4 + _QUOTE_SIDE + _KEPT_OUTSIDE]
    + _INSIDE_A_LONGER_TAG + _NEVER
    + [("RATED 175 PSI TYP", "RATED 175 PSI , TYP ."),
       (_NOTE.format("VAV-2"), _NOTE.format("VAV-2-1")),
       ("ACTION VALVE PV-3 SERVES DATA HALL 2", "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2")]
    + [(q, t) for q, t, _ in _KEPT]
)


@pytest.mark.parametrize(("quote", "text"), _AGREEMENT, ids=[f"row{i}" for i in range(len(_AGREEMENT))])
def test_the_anchor_is_exact_exactly_where_cross_qc_grounds(quote, text):
    """Cross-QC has only an exact tier; where the anchor's fuzzy tiers go
    further (a misspelled word, a dropped word), that is by design."""
    sheet = _sheet(_line(text))
    grounded = classify_quote_evidence(quote, sheet) == EVIDENCE_TEXT_GROUNDED
    anchor, matched = _place(quote, _line(text))
    assert (anchor.status == "EXACT") is grounded, (anchor, matched, grounded)


def test_cross_qc_admits_a_leg_quoted_without_the_sheets_punctuation():
    """Both legs ground and both anchor EXACT, so the dual-crop check sees it.
    Before, cross-QC dropped both legs as NOT_MATCHED."""
    a = _sheet(_line("PUMP P-1 RATED 175 PSI, TYP."), "a.pdf")
    b = _sheet(_line("PUMP P-1 RATED 150 PSI, TYP."), "b.pdf")
    counts = CrossQCDiscardCounts()
    finding = _finding_from_handles(
        {"category": "conflict", "severity": "high", "text": "ratings disagree",
         "sheet_handle": "S001", "source_quote": "RATED 175 PSI TYP",
         "also_on": [{"sheet_handle": "S002", "source_quote": "RATED 150 PSI TYP"}]},
        {"S001": ("S001", a), "S002": ("S002", b)}, counts,
    )
    assert finding is not None
    assert finding.evidence_state == EVIDENCE_TEXT_GROUNDED
    assert counts.legs_accepted_grounded == 2
    resolve_anchors([finding], a)
    resolve_conflict_legs([finding], {("a.pdf", 0): a, ("b.pdf", 0): b})
    assert finding.anchor.status == "EXACT" and finding.also_on[0].anchor.status == "EXACT"
    assert _has_anchored_legs(finding)


def test_cross_qc_admits_a_fact_quoted_without_the_brackets():
    counts = CrossQCDiscardCounts()
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": "150 GPM 568 L/MIN"}]},
        {"S001": ("S001", _sheet(_line("FLOW 150 GPM (568 L/MIN) AT")))}, {}, counts,
    )
    assert [f.evidence_state for f in facts] == [EVIDENCE_TEXT_GROUNDED]
    assert counts.facts_accepted == 1


@pytest.mark.parametrize("quote", [",", "(", ".", "))", ": :"])
def test_a_quote_of_only_punctuation_matches_nothing(quote):
    """It folds to nothing, so neither matcher finds it (it used to match a lone
    punctuation word on the sheet)."""
    text = "RATED 175 PSI , TYP . ( A ) )) : :"
    assert classify_quote_evidence(quote, _sheet(_line(text))) != EVIDENCE_TEXT_GROUNDED
    assert _place(quote, _line(text))[0].status == "UNANCHORED"


def test_a_short_tag_cross_qc_grounds_is_now_placed_by_the_anchor():
    """WP-05.1 left the two disagreeing: cross-QC grounded ``P-1`` in ``P-1,``
    (a full-trust leg) and the anchor could not place it (UNANCHORED, and no
    tile fallback, which is for unavailable evidence only)."""
    sheet = _sheet(_line("SEE P-1, TYP"))
    assert classify_quote_evidence("P-1", sheet) == EVIDENCE_TEXT_GROUNDED
    leg_owner = Finding(sheet_id="M-102", source_name="n.pdf", page_index=0, category="conflict",
                        severity="high", text="t", source_quote="PUMP P-1 SERVES")
    leg_owner.also_on = [ConflictLeg(sheet_id="M-101", source_name="m.pdf", page_index=0,
                                     source_quote="P-1", evidence_state=EVIDENCE_TEXT_GROUNDED)]
    resolve_conflict_legs([leg_owner], {("m.pdf", 0): sheet})
    leg = leg_owner.also_on[0]
    assert (leg.anchor.status, leg.anchor.method) == ("EXACT", "exact")


# --------------------------------------------------------------------------- #
# The rule is defined once
# --------------------------------------------------------------------------- #


def test_the_fold_is_word_cores_edge_punctuation_minus_marks_and_comparisons():
    """Everything ``word_core`` lets a match leave outside, except the marks
    that can carry meaning: ``"`` ``'`` (inches, feet) and ``<`` ``>``."""
    from drawing_analyzer import anchor

    assert anchor.WORD_LEADING_FOLD == frozenset("([{")
    assert anchor.WORD_TRAILING_FOLD == frozenset(")]},;:.!?")
    assert anchor.WORD_LEADING_FOLD == anchor.WORD_LEADING_PUNCTUATION - set("<\"'")
    assert anchor.WORD_TRAILING_FOLD == anchor.WORD_TRAILING_PUNCTUATION - set(">\"'")
    assert anchor.fold_word("(p 1),") == "p 1"
    assert anchor.fold_word('6"),') == '6"'
    assert anchor.fold_word(".5") == ".5"
    assert anchor.fold_word("30%") == "30%"
    assert anchor.fold_word("<5") == "<5"
    assert anchor.fold_word("( 1/2)") == "1/2"
    assert anchor.fold_word(",") == ""


def test_both_matchers_share_one_implementation():
    """Cross-QC's grounding and the anchor's EXACT tier both read ``SourceWords``."""
    from drawing_analyzer import anchor

    words = anchor.SourceWords(words=["SEE", "(P-1),", "XP-1", "AND", "VAV-2-1", "TYP."])
    assert words.spans("P-1") == ((1, 1),)
    assert words.spans("VAV-2") == ()
    assert words.spans("VAV-2-1 TYP") == ((4, 5),)
    assert anchor.SourceWords("SEE (P-1), XP-1").contains("P-1") is True


# --------------------------------------------------------------------------- #
# The consumers of an anchor
# --------------------------------------------------------------------------- #


def test_a_folded_exact_match_grounds_arithmetic_operands():
    """The sheet prints ``(20 + 20 = 540)``; the model quotes it without the
    brackets. EXACT / ``exact``, so the operands are the sheet's own."""
    sheet = _sheet(_line("(20 + 20 = 540)"))
    claim = NumericClaim(kind="sum", terms=[20, 20], expected=540, quote="20 + 20 = 540",
                         sheet_id="M-101", source_name="m.pdf", page_index=0)
    (f,) = audit_arithmetic([claim], [sheet]).findings
    assert (f.anchor.status, f.anchor.method) == ("EXACT", "exact")
    assert numbers_grounded(f.anchor)
    assert f.verification.status == "DETERMINISTIC"
    assert f.verification.operand_origin == TEXT_EXTRACTED


def test_a_quote_inside_a_longer_dimension_is_never_trusted_arithmetic():
    """The quote starts inside ``2-1/2"``: it no longer anchors at all."""
    sheet = _sheet(_line('2-1/2" + 2-1/2" = 4"'))
    claim = NumericClaim(kind="sum", terms=["1/2", "2 1/2"], expected=4, quote='1/2" + 2 1/2" = 4"',
                         sheet_id="M-101", source_name="m.pdf", page_index=0)
    (f,) = audit_arithmetic([claim], [sheet]).findings
    assert f.anchor.status == "UNANCHORED"
    assert f.verification.operand_origin == MODEL_TRANSCRIBED


def test_a_newly_anchored_finding_reaches_verification_and_investigation():
    b4 = _finding("RATED 175 PSI TYP")
    resolve_anchors([b4], _sheet(_line("RATED 175 PSI, TYP.")))
    assert _is_verifiable(b4)
    b4.verification = Verification(status="UNCERTAIN")
    assert b4 in _candidates([b4])


def test_a_quote_inside_a_longer_tag_is_neither_verified_nor_investigated():
    n12 = _finding("VAV-2")
    resolve_anchors([n12], _sheet(_line("VAV-2-1 SERVES ROOM 12")))
    assert not _is_verifiable(n12)
    n12.verification = Verification(status="UNCERTAIN")
    assert n12 not in _candidates([n12])


# --------------------------------------------------------------------------- #
# Through the pipeline
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")


def _pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "RATED 175 PSI, TYP.")
    page.insert_text((80, 200), "VAV-2-1 SERVES ROOM 12")
    page.insert_text((650, 560), "M-101")
    doc.save(str(path))
    doc.close()
    return path


_B4_FINDING = {
    "sheet_id": "M-101", "category": "code", "severity": "high",
    "text": "Relief valve rating is below the pump shutoff pressure.",
    "source_quote": "RATED 175 PSI TYP", "tile": [0, 0],
}
_N12_FINDING = {
    "sheet_id": "M-101", "category": "coordination", "severity": "medium",
    "text": "VAV-2 has no access panel shown.", "source_quote": "VAV-2", "tile": [0, 0],
}


def test_pipeline_clouds_the_punctuated_quote_and_not_the_longer_tag(tmp_path):
    """The B4 finding is clouded and costs one verification call; the N12 one
    is a ``[QUOTE NOT FOUND]`` margin callout and costs none."""
    from drawing_analyzer.pipeline import extract_drawing_context
    from tests.test_drawing_qc_pipeline import _RoutingClient

    client = _RoutingClient([_B4_FINDING, _N12_FINDING])
    ctx = extract_drawing_context(
        [_pdf(tmp_path / "M-101.pdf")], client=client, rows=2, cols=2,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    b4 = next(f for f in ctx.findings if f.source_quote == _B4_FINDING["source_quote"])
    n12 = next(f for f in ctx.findings if f.source_quote == _N12_FINDING["source_quote"])
    assert (b4.anchor.status, b4.anchor.method) == ("EXACT", "exact")
    assert b4.verification.status == "VERIFIED"
    assert n12.anchor.status == "UNANCHORED"
    assert client.verify_calls == 1
    expected = {p.qc_id: p.expected for p in ctx.markup_run.placements}
    assert expected[b4.qc_id] == "CLOUD"
    assert expected[n12.qc_id] == "MARGIN"


# --------------------------------------------------------------------------- #
# Cost: one long whitespace-free run (the WP-05.1 Codex review, anchor side)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("unit", ["XP-1", "P-1X"])
def test_a_quote_recurring_inside_one_long_word_anchors_in_linear_time(unit):
    """The quote recurs 250,000 times inside one 1,000,000-character word.

    Built here, never passed as the parameter: pytest names a test after a
    string parameter, and Windows caps ``PYTEST_CURRENT_TEST`` at 32,767
    characters.
    """
    import time

    words = [_w(100, 100, "NOTE"), _w(200, 100, unit * 250_000),
             _w(300, 100, "PUMP"), _w(400, 100, "P-1"), _w(500, 100, "END")]
    t0 = time.perf_counter()
    anchor, matched = _place("P-1", words)
    elapsed = time.perf_counter() - t0
    assert (anchor.status, matched) == ("EXACT", "P-1")
    assert elapsed < 5.0, f"anchoring is superlinear: {elapsed:.2f}s"
