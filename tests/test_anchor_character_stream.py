"""Spacing-only anchor matches must cover contiguous source words and preserve
numbers, units and tag boundaries. Cross-QC shares the matcher; arithmetic
keeps these matches model-transcribed rather than deterministic.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer import anchor as A
from drawing_analyzer import cross_qc as X
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
    EVIDENCE_NOT_MATCHED,
    EVIDENCE_TEXT_GROUNDED,
    EVIDENCE_UNAVAILABLE,
    MODEL_TRANSCRIBED,
    TEXT_EXTRACTED,
    NumericClaim,
    Verification,
)
from drawing_analyzer.verify import _has_anchored_legs, _is_verifiable
from tests.test_anchor_whole_words import _finding, _line, _place, _sheet, _w

W, H = 3168.0, 2448.0


def _rect_of(words, idxs):
    """The padded union of the given words: the rect an anchor on them gets."""
    return A._padded(A._words_rect(words, idxs), W, H)


def _lines(*texts):
    """Several lines, one under another, in reading order."""
    out = []
    for k, text in enumerate(texts):
        out += _line(text, y=100 + 800 * k)
    return out


def _grounds(quote: str, text: str) -> str:
    return classify_quote_evidence(quote, _sheet(_line(text)))


# --------------------------------------------------------------------------- #
# B4's four character-stream pairs
# --------------------------------------------------------------------------- #

_B4 = [
    # (quote, the sheet's line, the sheet's words the match covers, as printed)
    ('PROVIDE 6" DRAIN', 'PROVIDE 6 " DRAIN', 'PROVIDE 6 " DRAIN'),
    ("PROVIDE INCH DRAIN", "PROVIDE INCHDRAIN", "PROVIDE INCHDRAIN"),
    ("CLG 12'-6\" AFF", "CLG 12' - 6\" AFF", "CLG 12' - 6\" AFF"),
    ("SLOPE 2% MIN", "SLOPE 2 % MIN", "SLOPE 2 % MIN"),
]
_B4_IDS = ["inch", "merged", "feet", "percent"]


@pytest.mark.parametrize(("quote", "text", "span"), _B4, ids=_B4_IDS)
def test_b4_the_four_pairs_anchor_by_their_own_method(quote, text, span):
    """FUZZY / ``char_stream``, never EXACT, on the whole run of the sheet's
    words, which the anchor reports as printed."""
    words = _line(text)
    anchor, matched = _place(quote, words)
    assert (anchor.status, anchor.method) == ("FUZZY", "char_stream")
    assert matched == span
    assert anchor.rect_pdf == _rect_of(words, range(len(words)))


@pytest.mark.parametrize(("quote", "text", "span"), _B4, ids=_B4_IDS)
def test_b4_cross_qc_grounds_the_four_pairs_through_the_same_matcher(quote, text, span):
    assert _grounds(quote, text) == EVIDENCE_TEXT_GROUNDED


@pytest.mark.parametrize(("quote", "text", "span"), _B4, ids=_B4_IDS)
def test_the_tier_does_not_ground_numbers_for_the_arithmetic_auditor(quote, text, span):
    """The owner's choice: a new method fails closed in ``numbers_grounded``."""
    anchor, _ = _place(quote, _line(text))
    assert not numbers_grounded(anchor)
    assert not numbers_grounded(A.Anchor(status="FUZZY", rect_pdf=[0, 0, 1, 1],
                                         method="char_stream_ambiguous"))


_MORE = [
    # (quote, the sheet's line, the sheet's words the match covers)
    # a number and a separated mark, the quote spaced instead of the sheet
    ('PROVIDE 6 " DRAIN', 'PROVIDE 6" DRAIN', 'PROVIDE 6" DRAIN'),
    ("SLOPE 2 % MIN", "SLOPE 2% MIN", "SLOPE 2% MIN"),
    # a foot mark
    ("PROVIDE 6' CLEARANCE", "PROVIDE 6 ' CLEARANCE", "PROVIDE 6 ' CLEARANCE"),
    # feet-inches spaced on one side of the hyphen, on every side, or in the quote
    ("CLG 12'-6\" AFF", "CLG 12'- 6\" AFF", "CLG 12'- 6\" AFF"),
    ("CLG 12'-6\" AFF", "CLG 12 ' - 6 \" AFF", "CLG 12 ' - 6 \" AFF"),
    ("CLG 12' - 6\" AFF", "CLG 12'-6\" AFF", "CLG 12'-6\" AFF"),
    # a mixed number and a decimal, each with its inch mark apart
    ('PROVIDE 2-1/2" DRAIN', 'PROVIDE 2-1/2 " DRAIN', 'PROVIDE 2-1/2 " DRAIN'),
    ('GAP .5" MAX', 'GAP .5 " MAX', 'GAP .5 " MAX'),
    # two marks apart, and a mark apart beside merged words
    ('PROVIDE 6" AND 4" DRAINS', 'PROVIDE 6 " AND 4 " DRAINS', 'PROVIDE 6 " AND 4 " DRAINS'),
    ('PROVIDE 6" INCH DRAIN', 'PROVIDE 6 " INCHDRAIN', 'PROVIDE 6 " INCHDRAIN'),
    # a long note whose only difference is one separated mark
    ('PROVIDE ACCESS PANEL AT VAV-2 FOR SERVICE OF THE 6" DAMPER ACTUATOR PER DETAIL 4',
     'PROVIDE ACCESS PANEL AT VAV-2 FOR SERVICE OF THE 6 " DAMPER ACTUATOR PER DETAIL 4',
     'PROVIDE ACCESS PANEL AT VAV-2 FOR SERVICE OF THE 6 " DAMPER ACTUATOR PER DETAIL 4'),
    # a part of a line, whole words at both ends
    ('6" DRAIN', 'PROVIDE 6 " DRAIN AT COLUMN LINE 4', '6 " DRAIN'),
    ("INCH DRAIN", "PROVIDE INCHDRAIN AT", "INCHDRAIN"),
    # brackets and sentence punctuation still fold
    ('PROVIDE 6" DRAIN', 'PROVIDE (6 ") DRAIN.', 'PROVIDE (6 ") DRAIN.'),
]


@pytest.mark.parametrize(("quote", "text", "span"), _MORE, ids=[f"pos{i}" for i in range(len(_MORE))])
def test_the_named_joins_anchor_whole_runs(quote, text, span):
    anchor, matched = _place(quote, _line(text))
    assert (anchor.status, anchor.method, matched) == ("FUZZY", "char_stream", span)
    assert _grounds(quote, text) == EVIDENCE_TEXT_GROUNDED


_STILL_EXACT = [
    ("RATED 175 PSI TYP", "RATED 175 PSI, TYP."),     # PSI,
    ("NOTE 3", "SEE NOTE 3: PROVIDE ACCESS"),           # NOTE 3:
    ("150 GPM 568 L/MIN", "FLOW 150 GPM (568 L/MIN) AT"),   # a metric conversion
    ('PROVIDE 6" DRAIN', 'PROVIDE 6" DRAIN'),           # verbatim
    ("SET AT .5 IN", "SET AT .5 IN"),                  # a leading decimal, whole
    ("NOTE 5", "SEE NOTE 5. PROVIDE 4 IN"),             # the '.' is part of 'NOTE 5.'
    ("20 + 20 = 40", "20 + 20 = 40"),                  # operators are words of their own
    ("RATED 5", "RATED 5 . NEXT LINE"),                # a '.' before a word, not a digit
]


@pytest.mark.parametrize(("quote", "text"), _STILL_EXACT, ids=[f"exact{i}" for i in range(len(_STILL_EXACT))])
def test_what_the_older_tiers_matched_is_unchanged(quote, text):
    anchor, _ = _place(quote, _line(text))
    assert (anchor.status, anchor.method) == ("EXACT", "exact")
    assert _grounds(quote, text) == EVIDENCE_TEXT_GROUNDED


# --------------------------------------------------------------------------- #
# The required negatives: the tier refuses anything but the named joins
# --------------------------------------------------------------------------- #

_NEVER = [
    # changed numbers
    ('PROVIDE 8" DRAIN', 'PROVIDE 6 " DRAIN'),
    ("SLOPE 3% MIN", "SLOPE 2 % MIN"),
    ("CLG 12'-8\" AFF", "CLG 12' - 6\" AFF"),
    # signs
    ('ELEV -5" AFF', 'ELEV - 5 " AFF'),
    ('ELEV 5" AFF', 'ELEV -5 " AFF'),
    ("CLG 12'-6\" AFF", "CLG 12' -6\" AFF"),       # the sheet reads a negative 6in
    # units
    ("PROVIDE 6' DRAIN", 'PROVIDE 6 " DRAIN'),
    ("SLOPE 2° MIN", "SLOPE 2 % MIN"),
    ("PROVIDE 6 DRAIN", 'PROVIDE 6 " DRAIN'),          # the quote dropped the mark
    # operand multiplicity
    ('PROVIDE 6" 6" DRAIN', 'PROVIDE 6 " DRAIN'),
    ('PROVIDE 4 4" DRAINS', 'PROVIDE 4 " DRAINS'),
    # two numbers joined, or one split
    ("ROOM 12", "ROOM 1 2"),
    ("VAV-21 SERVES", "VAV-2-1 SERVES"),
    ('PROVIDE 21/2" DRAIN', 'PROVIDE 2-1/2" DRAIN'),
    ('PROVIDE 1/2" DRAIN', 'PROVIDE 1 / 2 " DRAIN'),
    ("12500 CFM", "12 ,500 CFM"),
    ("AHU-10 SERVES", "AHU-1 0 SERVES"),
    # embedded short tags
    ("P-1 SERVES", "XP-1 SERVES"),
    ("XP-1 SERVES", "X P-1 SERVES"),
    ("X P-1 SERVES", "XP-1 SERVES"),
    ("P1 SERVES", "P-1 SERVES"),
    ("AHU-7 SERVES", "AHU 77 SERVES"),
    # adjacent unrelated words: two sheet words for one quote word
    ("THERAPIST ROOM", "THE RAPIST ROOM"),
    ("NOTE 4", "NO TE 4"),
    ("PROVIDE INCHDRAIN", "PROVIDE INCH DRAIN"),
    # a hyphen is not a word boundary of the quote
    ("PRE-ACTION VALVE", "PREACTION VALVE"),
    # fragments that are not adjacent, and a run ending inside a word
    ("PROVIDE DRAIN", 'PROVIDE 6 " DRAIN'),
    ("INCH DRAIN", "INCH 6 DRAIN"),
    ("PROVIDE INCH DRAIN", "PROVIDE INCHDRAINS"),
    ('6" DRAIN', 'PROVIDE 16 " DRAIN'),
    # joins the owner did not name
    ("PROVIDE 6INCH DRAIN", "PROVIDE 6 INCH DRAIN"),   # a unit word
    ("PROVIDE 6 INCH DRAIN", "PROVIDE 6INCH DRAIN"),
    ("PUMP 150 GPM", "PUMP 150GPM"),
    ('24"x12" DUCT', '24 " x 12 " DUCT'),               # a size
    ("SUPPLY 55°F MAX", "SUPPLY 55 °F MAX"),  # a degree sign
    ("20A BREAKER", "20 A BREAKER"),
    # a leading decimal: .5 never grounds 5
    ('5" GAP', '. 5 " GAP'),
    ('GAP 5" MAX', 'GAP . 5 " MAX'),
    ('5" GAP', '.5 " GAP'),
    ('.5" GAP', '5 " GAP'),
    ('.5" GAP', '. 5 " GAP'),
]


@pytest.mark.parametrize(("quote", "text"), _NEVER, ids=[f"neg{i}" for i in range(len(_NEVER))])
def test_negatives_never_anchor_or_ground(quote, text):
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)
    assert _grounds(quote, text) == EVIDENCE_NOT_MATCHED


_IDENTIFIER_AND_MARK = [
    ("ROOM12% MIN", "ROOM12 % MIN"),
    ("ROOM12 % MIN", "ROOM12% MIN"),                  # the quote spaced instead
    ('SEE M-101" TYP', 'SEE M-101 " TYP'),            # a tag's digits, split by its hyphen
    ('RATED AHU2" MAX', 'RATED AHU2 " MAX'),
    ("CLG A12'-6\" AFF", "CLG A12' - 6\" AFF"),       # the feet-inches join
    ("CLG 12'-6A\" AFF", "CLG 12' - 6A\" AFF"),
]


@pytest.mark.parametrize(("quote", "text"), _IDENTIFIER_AND_MARK,
                         ids=[f"ident{i}" for i in range(len(_IDENTIFIER_AND_MARK))])
def test_a_mark_is_joined_only_to_a_number(quote, text):
    """A mark is joined across a space only to a number: a word of its own
    with no letter, on the side that has the space. An identifier's digits
    (``ROOM12``, a tag's ``101``) are not one, and the quantity reader reads
    nothing on either side, so its veto cannot refuse them (Codex review)."""
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)
    assert _grounds(quote, text) == EVIDENCE_NOT_MATCHED


@pytest.mark.parametrize(("quote", "text"), [
    ("AHU-7", "SEE AHU 77 TYP"),
    ("AHU-7", "SEE AHU-7A TYP"),
    ("AHU-7", "SEE AH U-7 TYP"),
    ("XP-1", "SEE X P-1 TYP"),
    ("P1", "SEE P-1 TYP"),
    ("M101", "SEE M-101 TYP"),
    ("VAV-21", "SEE VAV-2-1 TYP"),
    ("P-1", "SEE P - 1 TYP"),
], ids=["ahu77", "ahu7a", "ah-u7", "x-p1", "p1", "m101", "vav21", "p-dash-1"])
def test_an_absent_short_tag_never_becomes_text_grounded(quote, text):
    assert _grounds(quote, text) != EVIDENCE_TEXT_GROUNDED
    assert _place(quote, _line(text))[0].status == "UNANCHORED"


def test_a_match_is_never_assembled_from_fragments_out_of_reading_order():
    """The run must be contiguous, in the order the sheet's words are read."""
    words = _lines('DRAIN AT COLUMN LINE 4', 'PROVIDE 6 " PIPE')
    assert _place('PROVIDE 6" DRAIN', words)[0].status == "UNANCHORED"
    assert A.SourceWords(words=[w[4] for w in words]).joined_spans('PROVIDE 6" DRAIN') == ()


# --------------------------------------------------------------------------- #
# The veto uses the shared quantity reader
# --------------------------------------------------------------------------- #


def test_the_veto_reuses_the_wp_04_quantity_reader(monkeypatch):
    """No second reader: the tier asks ``critique._quantity_tokens``, so a
    reader that reads two different quantities refuses a match it would take."""
    from drawing_analyzer import critique

    assert _place('PROVIDE 6" DRAIN', _line('PROVIDE 6 " DRAIN'))[0].method == "char_stream"
    real = critique._quantity_tokens
    monkeypatch.setattr(critique, "_quantity_tokens",
                        lambda text: real(text) | ({"spaced"} if ' "' in text else frozenset()))
    assert _place('PROVIDE 6" DRAIN', _line('PROVIDE 6 " DRAIN'))[0].status == "UNANCHORED"


def test_the_veto_refuses_a_quantity_the_reader_reads_differently():
    """``12' -6"`` is read as a negative six inches (a sign after a space), so
    it is not ``12'-6"``: the join rules pass it, the reader refuses it."""
    from drawing_analyzer.critique import _quantity_tokens

    assert _quantity_tokens("clg 12' -6\" aff") != _quantity_tokens("clg 12'-6\" aff")
    assert _place("CLG 12'-6\" AFF", _line("CLG 12' -6\" AFF"))[0].status == "UNANCHORED"


# --------------------------------------------------------------------------- #
# A number split around a lone '.' stays whole, in every tier
# --------------------------------------------------------------------------- #

_SPLIT_NUMBER = [
    # (quote, sheet): EXACT on the folded words before this slice
    ("SET AT 5 IN", "SET AT . 5 IN"),
    ("5 IN", "SET AT . 5 IN"),
    ("5", "RATED 5 . 25 GPM"),
    ("25 GPM", "RATED 5 . 25 GPM"),
    ("RATED 5", "RATED 5 . 25 GPM"),
    # the quote splits it: its '.5' cannot be told from '5'
    ("SET AT . 5 IN", "SET AT 5 IN"),
    (". 5 IN", "SET AT 5 IN"),
    ("SET AT . 5 IN", "SET AT .5 IN"),
    ("SET AT . 5 IN", "SET AT . 5 IN"),
]


@pytest.mark.parametrize(("quote", "text"), _SPLIT_NUMBER, ids=[f"split{i}" for i in range(len(_SPLIT_NUMBER))])
def test_a_number_split_around_a_lone_point_is_never_matched_in_part(quote, text):
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)
    assert _grounds(quote, text) == EVIDENCE_NOT_MATCHED


def test_a_sub_phrase_never_covers_a_split_number():
    """The quote is longer than the line, so no window fits; the only sub-phrase
    holding the quote's numbers covers the ``5`` after the lone point."""
    anchor, matched = _place("SET 5 IN MAX PER NOTE 7 FOR THE DRAIN",
                             _line("SET AT . 5 IN MAX PER NOTE 7"))
    assert anchor.status == "UNANCHORED", (anchor, matched)


def test_a_window_never_covers_a_split_number():
    """One quote word differs (UNDER / BELOW), so EXACT fails; the window's
    overlap clears the floor and its numbers align, but it covers the ``5``."""
    anchor, matched = _place(
        "PROVIDE 6 INCH DRAIN AT 5 IN UNDER THE SLAB PER DETAIL 4 NORTH",
        _line("PROVIDE 6 INCH DRAIN AT . 5 IN BELOW THE SLAB PER DETAIL 4 NORTH"),
    )
    assert anchor.status == "UNANCHORED", (anchor, matched)


def test_words_away_from_a_split_number_still_match():
    words = _line("SET AT . 5 IN PER NOTE 7")
    assert _place("PER NOTE 7", words)[0].status == "EXACT"
    assert _place("SET AT", words)[0].status == "EXACT"


# --------------------------------------------------------------------------- #
# Ambiguity: as EXACT
# --------------------------------------------------------------------------- #


def test_two_occurrences_without_a_tile_take_the_first_flagged_ambiguous():
    words = _lines("SLOPE 2 % MIN", "SLOPE 2 % MIN")
    anchor, _ = _place("SLOPE 2% MIN", words)
    assert (anchor.status, anchor.method) == ("FUZZY", "char_stream_ambiguous")
    assert anchor.rect_pdf == _rect_of(words, range(4)), "the first in reading order"
    again, _ = _place("SLOPE 2% MIN", list(words))
    assert again.rect_pdf == anchor.rect_pdf, "deterministic (I-7)"


def test_the_reported_tile_settles_two_occurrences():
    words = _lines("SLOPE 2 % MIN", "SLOPE 2 % MIN")
    second = _rect_of(words, range(4, 8))
    row = A._base_cell(*A._rect_center(A._words_rect(words, range(4, 8))), W, H, 6, 6)
    anchor, _ = _place("SLOPE 2% MIN", words, tile=list(row))
    assert (anchor.status, anchor.method) == ("FUZZY", "char_stream")
    assert anchor.rect_pdf == second


# --------------------------------------------------------------------------- #
# A sub-phrase keeps a number's unit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("quote", "text"), [
    ("150 GPM 568 L/S", "FLOW 150 GPM (568 L/MIN) AT"),
    ("PUMP P-2 RATED 175 PSIG", "PUMP P-2 RATED 175 PSI"),
    ("OPEN AREA SHALL BE 30 PCT", "OPEN AREA SHALL BE 30 %"),
    # the accepted cost: the rule reads positions, not units, so a word after
    # the number that is no unit of it refuses the sub-phrase too
    ("SEE RISER DIAGRAM NOTE 4 FOR THE FULL PIPE ROUTING", "REFER TO RISER DIAGRAM NOTE 4"),
], ids=["l-per-s", "psig", "pct", "next-word"])
def test_a_sub_phrase_never_ends_on_a_number_the_quote_continues(quote, text):
    """Each anchored FUZZY on a sub-phrase that stopped at the number and left
    the rest of the quote, the number's unit among it, behind."""
    anchor, matched = _place(quote, _line(text))
    assert anchor.status == "UNANCHORED", (anchor, matched)


@pytest.mark.parametrize(("quote", "text", "method", "span"), [
    ("ACTION VALVE PV-3 SERVES DATA HALL 2", "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2",
     "fuzzy_subphrase", "VALVE PV-3 SERVES DATA HALL 2"),
    ("FIRE PUMP RATED 500 GPM AT 100 PSI NET PRESSURE PER NFPA 20 SECTION",
     "FIRE PUMP RATED 500 GPM AT 100 PSI (689 KPA) NET PRESSURE PER NFPA 20",
     "fuzzy_window", "PUMP RATED 500 GPM AT 100 PSI (689 KPA) NET PRESSURE PER NFPA 20"),
    ("SEE THE FULL PIPE ROUTING ON RISER DIAGRAM NOTE 4", "REFER TO RISER DIAGRAM NOTE 4",
     "fuzzy_subphrase", "RISER DIAGRAM NOTE 4"),
], ids=["ends-on-a-word", "window", "number-ends-the-quote"])
def test_a_sub_phrase_that_keeps_its_numbers_whole_still_anchors(quote, text, method, span):
    anchor, matched = _place(quote, _line(text))
    assert (anchor.status, anchor.method, matched) == ("FUZZY", method, span)


# --------------------------------------------------------------------------- #
# Cross-QC grounds through the same matcher; the anchor and cross-QC agree
# --------------------------------------------------------------------------- #

_AGREEMENT = (
    [(q, t) for q, t, _ in _B4 + _MORE] + _STILL_EXACT + _NEVER + _SPLIT_NUMBER
    + [("150 GPM 568 L/S", "FLOW 150 GPM (568 L/MIN) AT")]
)


@pytest.mark.parametrize(("quote", "text"), _AGREEMENT, ids=[f"row{i}" for i in range(len(_AGREEMENT))])
def test_the_anchor_is_exact_or_char_stream_exactly_where_cross_qc_grounds(quote, text):
    grounded = _grounds(quote, text) == EVIDENCE_TEXT_GROUNDED
    anchor, matched = _place(quote, _line(text))
    by_text = anchor.status == "EXACT" or anchor.method.startswith("char_stream")
    assert by_text is grounded, (anchor, matched, grounded)


def test_cross_qc_admits_a_leg_whose_mark_the_sheet_printed_apart():
    """Both legs ground, and both anchor (EXACT on one sheet, ``char_stream``
    on the other), so the dual-crop check sees the conflict. Before, the leg
    was NOT_MATCHED and dropped, and the conflict with it."""
    a = _sheet(_line('DRAIN 6" AT RISER'), "a.pdf")
    b = _sheet(_line('DRAIN 4 " AT RISER'), "b.pdf")
    counts = CrossQCDiscardCounts()
    finding = _finding_from_handles(
        {"category": "conflict", "severity": "high", "text": "drain sizes disagree",
         "sheet_handle": "S001", "source_quote": 'DRAIN 6" AT RISER',
         "also_on": [{"sheet_handle": "S002", "source_quote": 'DRAIN 4" AT RISER'}]},
        {"S001": ("S001", a), "S002": ("S002", b)}, counts,
    )
    assert finding is not None
    assert finding.evidence_state == EVIDENCE_TEXT_GROUNDED
    assert finding.also_on[0].evidence_state == EVIDENCE_TEXT_GROUNDED
    assert counts.legs_accepted_grounded == 2
    resolve_anchors([finding], a)
    resolve_conflict_legs([finding], {("a.pdf", 0): a, ("b.pdf", 0): b})
    assert (finding.anchor.status, finding.anchor.method) == ("EXACT", "exact")
    leg = finding.also_on[0]
    assert (leg.anchor.status, leg.anchor.method) == ("FUZZY", "char_stream")
    assert _has_anchored_legs(finding)


def test_cross_qc_admits_a_fact_whose_words_extraction_merged():
    counts = CrossQCDiscardCounts()
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": "PROVIDE INCH DRAIN"}]},
        {"S001": ("S001", _sheet(_line("PROVIDE INCHDRAIN AT COLUMN 4")))}, {}, counts,
    )
    assert [f.evidence_state for f in facts] == [EVIDENCE_TEXT_GROUNDED]
    assert counts.facts_accepted == 1


def test_a_textless_sheet_is_still_unavailable_evidence():
    """A text match cannot ground evidence when the sheet has no text."""
    assert classify_quote_evidence('PROVIDE 6" DRAIN', _sheet([])) == EVIDENCE_UNAVAILABLE


def test_both_matchers_share_one_implementation():
    """Cross-QC's grounding and the anchor's tier both read ``SourceWords``."""
    words = A.SourceWords(words=["PROVIDE", "6", '"', "DRAIN", "AT", "INCHDRAIN"])
    assert words.contains('PROVIDE 6" DRAIN') is False
    assert words.joined_spans('PROVIDE 6" DRAIN') == ((0, 3),)
    assert words.joined_spans("AT INCH DRAIN") == ((4, 5),)
    assert words.joined_spans("VAV-21") == ()
    assert A.SourceWords('SEE 6 " DRAIN').joined_spans('6" DRAIN') == ((1, 3),)


# --------------------------------------------------------------------------- #
# The consumers of an anchor
# --------------------------------------------------------------------------- #


def test_an_arithmetic_mismatch_the_tier_anchors_stays_model_transcribed():
    """The owner's choice: ``char_stream`` does not ground numbers, so the
    mismatch is UNCERTAIN and goes to the crop verifier, never inked as
    host-computed."""
    sheet = _sheet(_line('6 " + 6 " = 14 "'))
    claim = NumericClaim(kind="sum", terms=[6, 6], expected=14, quote='6" + 6" = 14"',
                         sheet_id="M-101", source_name="m.pdf", page_index=0)
    (f,) = audit_arithmetic([claim], [sheet]).findings
    assert (f.anchor.status, f.anchor.method) == ("FUZZY", "char_stream")
    assert f.verification.status == "UNCERTAIN"
    assert f.verification.operand_origin == MODEL_TRANSCRIBED


def test_an_exact_arithmetic_quote_is_still_trusted():
    sheet = _sheet(_line("20 + 20 = 540"))
    claim = NumericClaim(kind="sum", terms=[20, 20], expected=540, quote="20 + 20 = 540",
                         sheet_id="M-101", source_name="m.pdf", page_index=0)
    (f,) = audit_arithmetic([claim], [sheet]).findings
    assert f.verification.status == "DETERMINISTIC"
    assert f.verification.operand_origin == TEXT_EXTRACTED


def test_a_newly_anchored_finding_reaches_verification_and_investigation():
    f = _finding('PROVIDE 6" DRAIN')
    resolve_anchors([f], _sheet(_line('PROVIDE 6 " DRAIN')))
    assert _is_verifiable(f)
    f.verification = Verification(status="UNCERTAIN")
    assert f in _candidates([f])


def test_a_split_number_is_neither_verified_nor_investigated():
    f = _finding("SET AT 5 IN")
    resolve_anchors([f], _sheet(_line("SET AT . 5 IN")))
    assert not _is_verifiable(f)
    f.verification = Verification(status="UNCERTAIN")
    assert f not in _candidates([f])


pymupdf = pytest.importorskip("pymupdf")


def _pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), 'PROVIDE 6 " DRAIN')
    page.insert_text((80, 200), "SLOPE 2 % MIN")
    page.insert_text((650, 560), "M-101")
    doc.save(str(path))
    doc.close()
    return path


_INCH = {
    "sheet_id": "M-101", "category": "code", "severity": "high",
    "text": "Drain is undersized for the floor area served.",
    "source_quote": 'PROVIDE 6" DRAIN', "tile": [0, 0],
}
_PERCENT = {
    "sheet_id": "M-101", "category": "coordination", "severity": "medium",
    "text": "Slope conflicts with the civil grading plan.",
    "source_quote": "SLOPE 2% MIN", "tile": [0, 0],
}


def test_pipeline_clouds_both_quotes_and_verifies_each_once(tmp_path):
    """Each was a ``[QUOTE NOT FOUND]`` margin callout that no verifier saw."""
    from drawing_analyzer.pipeline import extract_drawing_context
    from tests.test_drawing_qc_pipeline import _RoutingClient

    client = _RoutingClient([_INCH, _PERCENT])
    ctx = extract_drawing_context(
        [_pdf(tmp_path / "M-101.pdf")], client=client, rows=2, cols=2,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    found = {f.source_quote: f for f in ctx.findings}
    inch, percent = found[_INCH["source_quote"]], found[_PERCENT["source_quote"]]
    for f in (inch, percent):
        assert (f.anchor.status, f.anchor.method) == ("FUZZY", "char_stream")
        assert f.verification.status == "VERIFIED"
    assert client.verify_calls == 2
    expected = {p.qc_id: p.expected for p in ctx.markup_run.placements}
    assert expected[inch.qc_id] == "CLOUD"
    assert expected[percent.qc_id] == "CLOUD"


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("unit", ['6"X', 'X6"'])
def test_a_joined_quote_recurring_inside_one_long_word_anchors_in_linear_time(unit):
    """The joined quote recurs 250,000 times inside one 750,000-character word
    (none of them a whole word), before the one real run at the end.

    Built here, never passed as the parameter (Windows caps
    ``PYTEST_CURRENT_TEST``).
    """
    import time

    words = [_w(100, 100, "NOTE"), _w(200, 100, unit * 250_000),
             _w(300, 100, "PUMP"), _w(400, 100, "6"), _w(500, 100, '"'), _w(600, 100, "END")]
    t0 = time.perf_counter()
    anchor, matched = _place('6"', words)
    elapsed = time.perf_counter() - t0
    assert (anchor.status, anchor.method, matched) == ("FUZZY", "char_stream", '6 "')
    assert elapsed < 5.0, f"the character stream is superlinear: {elapsed:.2f}s"
