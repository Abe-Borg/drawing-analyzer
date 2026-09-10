"""Anchor-resolver tests. Pure — synthetic word lists, no PyMuPDF, no network.

Word tuples mirror PyMuPDF's ``get_text("words")`` shape:
``(x0, y0, x1, y1, text, block, line, word_no)``.
"""
from __future__ import annotations

from pathlib import Path

from drawing_analyzer import tiling
from drawing_analyzer.anchor import _normalize, resolve_anchors
from drawing_analyzer.models import Anchor, Finding, ImageTile, RenderedSheet, SheetRef

W, H = 3168.0, 2448.0
ROWS = COLS = 6


def _w(x, y, text, width=60, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _sheet(words, *, rows=ROWS, cols=COLS, overlap=0.08):
    ref = SheetRef(pdf_path=Path("m.pdf"), page_index=0, source_name="m.pdf", page_count=1)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=rows, cols=cols, words=list(words), overlap_frac=overlap,
    )


def _finding(quote, tile=None, *, category="code"):
    return Finding(
        sheet_id="M-101", source_name="m.pdf", page_index=0,
        category=category, severity="high", text="t", source_quote=quote, tile=tile,
    )


def _anchor(quote, words, tile=None):
    f = _finding(quote, tile=tile)
    resolve_anchors([f], _sheet(words))
    return f.anchor


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def test_normalize_folds_unicode_and_whitespace():
    # NFKC, dash/quote/prime folding, infix-hyphen->space, lowercase, collapse.
    assert _normalize("VAV‑3") == "vav 3"                  # non-breaking infix hyphen
    assert _normalize("2-1/2\"") == _normalize("2 1/2″")   # infix hyphen==space, ″ -> "
    assert _normalize("  RELIEF\nVALVE  ") == "relief valve"    # linebreak collapse
    assert _normalize("“QUOTED”") == '"quoted"'       # curly -> straight
    assert _normalize("Ø6 PIPE") == "o6 pipe"              # Ø diameter -> o


def test_normalize_preserves_leading_sign_hyphen():
    # Only an INFIX hyphen folds to a space; a leading/sign hyphen is kept, so a
    # below-datum value never collapses onto its above-datum twin.
    assert _normalize("-6\"") != _normalize("6\"")
    assert _normalize("VAV-3") == "vav 3"                  # infix still folds


def test_signed_value_does_not_anchor_to_unsigned_twin():
    # A quoted below-datum "-6\"" must not EXACT-match a separate above-datum "6\"".
    words = [_w(100, 100, '6"'), _w(2900, 2200, '-6"')]
    f = _finding('-6"', tile=None)
    resolve_anchors([f], _sheet(words))
    # It anchors to the actual "-6\"" word (bottom-right), not the "6\"" (top-left).
    assert f.anchor.status == "EXACT" and f.anchor.rect_pdf[0] > 2000


# --------------------------------------------------------------------------- #
# EXACT
# --------------------------------------------------------------------------- #


def test_exact_single_hit_unions_and_pads_words():
    words = [_w(100, 100, "VAV"), _w(160, 100, "3"), _w(300, 100, "SERVES")]
    a = _anchor("VAV-3 serves", words)
    assert a.status == "EXACT" and a.method == "exact"
    # Union of words at x∈[100,360], y∈[100,114], padded 8pt each side.
    assert a.rect_pdf == [92.0, 92.0, 368.0, 122.0]


def test_exact_matches_across_split_tokens():
    # A single word "2-1/2\"" normalizes to two tokens; matching on the token
    # stream (not per-word equality) is what lets the quote hit it.
    words = [_w(100, 100, '2-1/2"'), _w(200, 100, "PIPE")]
    a = _anchor('2 1/2" pipe', words)
    assert a.status == "EXACT"


def test_exact_ambiguous_without_tile_flag_and_first():
    # "BATTERY ROOM" appears twice; no tile hint -> first hit, flagged ambiguous.
    words = [
        _w(100, 100, "BATTERY"), _w(200, 100, "ROOM"),
        _w(2900, 2200, "BATTERY"), _w(3000, 2200, "ROOM"),
    ]
    a = _anchor("BATTERY ROOM", words)
    assert a.status == "EXACT" and a.method == "exact_ambiguous"
    assert a.rect_pdf[0] < 200            # the first (top-left) occurrence


def test_exact_tile_preference_disambiguates():
    words = [
        _w(100, 100, "BATTERY"), _w(200, 100, "ROOM"),          # base cell (0,0)
        _w(2900, 2200, "BATTERY"), _w(3000, 2200, "ROOM"),      # base cell (5,5)
    ]
    # The model saw it in the bottom-right tile -> pick that occurrence cleanly.
    a = _anchor("BATTERY ROOM", words, tile=[5, 5])
    assert a.status == "EXACT" and a.method == "exact"
    assert a.rect_pdf[0] > 2000           # the bottom-right occurrence


# --------------------------------------------------------------------------- #
# FUZZY
# --------------------------------------------------------------------------- #


def test_fuzzy_window_on_token_off():
    # Same length as the quote but one token differs (>=85% overlap for the
    # matching window). Query and window are both 6 tokens; 5/6 ≈ 0.83 < 0.85,
    # so use a 7/8 case instead.
    words = [_w(100 + 60 * i, 100, t) for i, t in enumerate(
        ["FIRE", "PUMP", "RATED", "AT", "500", "GPM", "AND", "100"])]
    a = _anchor("fire pump rated at 500 gpm and XXX", words)  # 8 tokens, 7 match
    assert a.status == "FUZZY" and a.method == "fuzzy_window"


def test_fuzzy_window_uses_multiset_overlap_not_set():
    # A quote with repeated tokens whose DISTINCT set is fully present on the
    # sheet must NOT spuriously fuzzy-match — bag overlap (count/m), not set
    # overlap, is what preserves the UNANCHORED hallucination signal here.
    words = [_w(100, 100, "PUMP"), _w(160, 100, "VALVE"),
             _w(220, 100, "X"), _w(280, 100, "TANK")]
    a = _anchor("valve valve valve x", words)  # bag overlap 2/4 = 0.5 < 0.85
    assert a.status == "UNANCHORED"


def test_fuzzy_subphrase_partial_match():
    # The sheet has a clean 6-token phrase; the quote embeds it with extra
    # leading/trailing tokens, so the same-length window can't align but the
    # longest contiguous sub-phrase ("relief valve set at 165 psi") matches.
    words = [_w(100 + 60 * i, 100, t) for i, t in enumerate(
        ["RELIEF", "VALVE", "SET", "AT", "165", "PSI"])]
    a = _anchor("per note relief valve set at 165 psi maximum", words)
    assert a.status == "FUZZY" and a.method == "fuzzy_subphrase"
    # Anchored to the matched phrase (starts at "RELIEF" x=100).
    assert a.rect_pdf[0] <= 100


# --------------------------------------------------------------------------- #
# TILE / UNANCHORED
# --------------------------------------------------------------------------- #


def test_tile_anchor_for_graphics_only_finding():
    a = _anchor("", [], tile=[2, 3])
    assert a.status == "TILE" and a.method == "tile"
    expected = {(t.row, t.col): t for t in tiling.tile_rects(W, H, rows=ROWS, cols=COLS)}[(2, 3)]
    assert a.rect_pdf == [expected.x0, expected.y0, expected.x1, expected.y1]


def test_unanchored_when_quote_matches_nothing():
    words = [_w(100, 100, "VAV"), _w(160, 100, "3")]
    a = _anchor("FABRICATED TAG XYZ-999 NOWHERE", words)
    assert a.status == "UNANCHORED" and a.method == "quote_not_found"
    assert a.rect_pdf is None


def test_unanchored_when_no_quote_and_no_tile():
    a = _anchor("", [], tile=None)
    assert a.status == "UNANCHORED" and a.method == "no_quote_no_tile"


def test_out_of_range_tile_is_ignored():
    # A graphics finding whose tile is out of the grid -> no tile rect -> unanchored.
    a = _anchor("", [], tile=[99, 99])
    assert a.status == "UNANCHORED" and a.method == "no_quote_no_tile"


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #


def test_already_anchored_findings_are_left_untouched():
    # A deterministic (reference-audit) finding arrives already EXACT-anchored;
    # the resolver must not re-anchor or overwrite it.
    f = _finding("VAV-3 serves")
    f.anchor = Anchor(status="EXACT", rect_pdf=[1.0, 2.0, 3.0, 4.0], method="reference_word_rect")
    resolve_anchors([f], _sheet([_w(100, 100, "VAV"), _w(160, 100, "3"), _w(300, 100, "SERVES")]))
    assert f.anchor.method == "reference_word_rect" and f.anchor.rect_pdf == [1.0, 2.0, 3.0, 4.0]


def test_resolve_anchors_returns_the_list_and_anchors_all():
    words = [_w(100, 100, "VAV"), _w(160, 100, "3")]
    fs = [_finding("VAV-3"), _finding("", tile=[0, 0]), _finding("nope nope nope")]
    out = resolve_anchors(fs, _sheet(words))
    assert out is not None and len(out) == 3
    assert [f.anchor.status for f in fs] == ["EXACT", "TILE", "UNANCHORED"]


def test_rects_are_within_page_bounds():
    # A word near the corner: padding must clamp to the page, not go negative.
    a = _anchor("CORNER", [_w(2.0, 1.0, "CORNER")])
    assert a.status == "EXACT"
    x0, y0, x1, y1 = a.rect_pdf
    assert x0 >= 0.0 and y0 >= 0.0 and x1 <= W and y1 <= H


def test_raster_sheet_non_empty_quote_is_unanchored():
    # No words (raster): a quoted finding can't be placed -> UNANCHORED, but a
    # graphics finding with a tile still gets a TILE anchor.
    assert _anchor("some quote", [], tile=[1, 1]).status == "UNANCHORED"
    assert _anchor("", [], tile=[1, 1]).status == "TILE"


# --------------------------------------------------------------------------- #
# The numeric veto (P7 item 30)
#
# Bag-of-token overlap is blind to the substitution that matters most on a
# drawing: swap one digit and the score barely moves. On
# "PROVIDE 6 INCH DRAIN AT COLUMN LINE 4" every one-number substitution cleared
# the 0.85 floor at 6/7 = 0.857 and clouded onto the real text, while a wholly
# invented sentence correctly went UNANCHORED — so UNANCHORED, the hallucination
# signal, was blind exactly where a wrong number is least cosmetic.
#
# Fixed by ADDING A VETO. The threshold is a standing prohibition and is asserted
# untouched below.
# --------------------------------------------------------------------------- #

_DRAIN_SHEET = ["PROVIDE", "6", "INCH", "DRAIN", "AT", "COLUMN", "LINE", "4"]
_SPACING_SHEET = ["SPRINKLER", "HEAD", "SPACING", "SHALL", "NOT", "EXCEED",
                  "12", "FT", "ON", "CENTER", "PER", "NFPA", "13"]


def _line(tokens, y=100):
    return [_w(100 + 70 * i, y, t) for i, t in enumerate(tokens)]


def test_fuzzy_overlap_threshold_is_unchanged():
    # A standing prohibition: item 30 is fixed by adding a veto, never by moving
    # this floor. If a future change raises it, that is a different decision and
    # this test should fail loudly rather than let it pass as "the item 30 fix".
    from drawing_analyzer.anchor import _FUZZY_WINDOW_MIN_OVERLAP

    assert _FUZZY_WINDOW_MIN_OVERLAP == 0.85


def test_exact_quote_still_anchors_exact():
    a = _anchor("PROVIDE 6 INCH DRAIN AT COLUMN LINE 4", _line(_DRAIN_SHEET))
    assert a.status == "EXACT" and a.method == "exact"


SUBSTITUTIONS = [
    # (quote, what was swapped) — each one previously clouded onto the real text.
    ("PROVIDE 4 INCH DRAIN AT COLUMN LINE", "pipe size 6 -> 4"),
    ("PROVIDE 12 INCH DRAIN AT COLUMN LINE", "pipe size 6 -> 12"),
    ("PROVIDE 4 INCH DRAIN AT COLUMN LINE 4", "size 6 -> 4, digit available nearby"),
    ("PROVIDE 6 INCH DRAIN AT COLUMN LINE 7", "column line 4 -> 7"),
    ("PROVIDE 14 INCH DRAIN AT COLUMN LINE 4", "6 -> 14, a superstring of the real 4"),
]


def test_numeric_substitution_is_never_precisely_anchored():
    # The core guarantee: a wrong measurement must not be clouded onto text that
    # says something else. On a fire-sprinkler drain that is not cosmetic.
    for quote, what in SUBSTITUTIONS:
        a = _anchor(quote, _line(_DRAIN_SHEET))
        assert a.status == "UNANCHORED", (
            f"{what}: anchored {a.status}/{a.method} at {a.rect_pdf} — a wrong "
            f"measurement clouded onto the sheet's real text"
        )
        assert a.rect_pdf is None


def test_numeric_substitution_cannot_slide_the_window_to_borrow_a_digit():
    # The subtle half. Multiset agreement alone is satisfied by SLIDING: dropping
    # PROVIDE from the front lets the window pick up the trailing 4 of
    # "COLUMN LINE 4", so the quote's 4 is "found" playing a different role while
    # the text still reads 6 INCH. Sliding one further borrows it from the NEXT
    # LINE of the sheet. Both must be refused.
    words = _line(_DRAIN_SHEET) + _line(["SPRINKLER", "HEAD", "SPACING", "12", "FT"], y=400)
    a = _anchor("PROVIDE 4 INCH DRAIN AT COLUMN LINE", words)
    assert a.status == "UNANCHORED", f"borrowed a digit: {a.method} {a.rect_pdf}"


def test_repeated_measurement_needs_one_occurrence_per_mention():
    # "4 4-INCH DRAINS" against a sheet reading "4 6-INCH DRAINS" must not
    # satisfy both of the quote's 4s from the sheet's single one — which is why
    # the positional check consumes each span position once.
    #
    # Eight tokens deliberately: with one mismatch the window scores 7/8 = 0.875
    # and CLEARS the 0.85 floor, so the veto is actually consulted. The six-token
    # version of this scenario scores 5/6 = 0.833 and is refused by the floor
    # before the veto runs, which makes it useless as a guard for this line.
    sheet = ["PROVIDE", "4", "6", "INCH", "DRAINS", "AT", "COLUMN", "LINE"]
    quote = "PROVIDE 4 4 INCH DRAINS AT COLUMN LINE"
    a = _anchor(quote, _line(sheet))
    assert a.status == "UNANCHORED", f"double-counted one digit: {a.method}"
    # …and the honest version of the same quote still anchors.
    good = ["PROVIDE", "4", "4", "INCH", "DRAINS", "AT", "COLUMN", "LINE"]
    assert _anchor(quote, _line(good)).status == "EXACT"


def test_subphrase_may_not_drop_the_measurement():
    # The sub-phrase path compounds the defect from the other direction: a 3-8
    # token slice can omit the number entirely, anchoring a numeric claim to text
    # that never carried it. Here "INCH DRAIN AT COLUMN LINE" matches verbatim.
    a = _anchor("PROVIDE 2-1/2 INCH DRAIN AT COLUMN LINE", _line(_DRAIN_SHEET))
    assert a.status == "UNANCHORED", (
        f"a sub-phrase dropped the pipe size and anchored anyway: {a.method}"
    )


def test_vetoed_quote_reaches_the_hallucination_signal_not_a_softer_tier():
    # A reported tile must NOT soften the outcome. The sheet has text and the
    # quote's measurement is not in it, so this is a fabricated number and
    # UNANCHORED is the signal that says so. Routing it to TILE instead would
    # hide a hallucination behind a plausible-looking region.
    a = _anchor("PROVIDE 4 INCH DRAIN AT COLUMN LINE", _line(_DRAIN_SHEET), tile=[0, 0])
    assert a.status == "UNANCHORED" and a.method == "quote_not_found"


def test_veto_composes_with_the_no_text_evidence_relief_valve():
    # WP-03B §8.4 Part 3: when the host recorded that no textual check was
    # possible for this leg — a scanned sheet, or the pasted raster region of a
    # hybrid one — an unmatched quote is not evidence of fabrication, and the leg
    # falls back to its tile so it can still reach the crop check and the
    # investigation loop. The veto must not defeat that: it declines to place a
    # precise rect, and the existing fallback still applies.
    from drawing_analyzer.models import EVIDENCE_UNAVAILABLE

    f = _finding("PROVIDE 4 INCH DRAIN AT COLUMN LINE", tile=[0, 0])
    f.evidence_state = EVIDENCE_UNAVAILABLE
    resolve_anchors([f], _sheet(_line(_DRAIN_SHEET)))
    assert f.anchor.status == "TILE"
    assert f.anchor.method == "tile_no_text_evidence"
    assert f.anchor.rect_pdf is not None


# The recall side. A veto that refuses legitimate transcription variance is a
# different bug, so these are asserted as tightly as the substitutions above:
# they are exactly what fuzzy matching exists to tolerate.
LEGITIMATE = [
    (["PROVIDE", "6", "INCH", "DIA", "DRAIN", "AT", "COLUMN", "LINE", "4"],
     "PROVIDE 6 INCH DRAIN AT COLUMN LINE 4", "sheet has an extra word"),
    (_DRAIN_SHEET, "PROVIDE 6 INCH DRAIN AT COL LINE 4", "quote abbreviates a word"),
    (_SPACING_SHEET,
     "SPRINKLER HEAD SPACING SHALL NOT EXCEED 12 FT ON CENTRE PER NFPA 13",
     "spelling variant"),
    (_SPACING_SHEET,
     "SPRINKLER HEAD SPACING MUST NOT EXCEED 12 FT ON CENTER PER NFPA 13",
     "one word paraphrased"),
]


def test_legitimate_transcription_variance_still_anchors():
    for sheet, quote, what in LEGITIMATE:
        a = _anchor(quote, _line(sheet))
        assert a.status in ("EXACT", "FUZZY"), (
            f"{what}: the veto refused a legitimate match ({a.status}/{a.method})"
        )
        assert a.rect_pdf is not None


def test_quote_without_digits_is_unaffected_by_the_veto():
    # Prose findings must anchor exactly as before — the veto has nothing to say
    # about a quote that claims no measurement.
    sheet = ["MAINTAIN", "ADEQUATE", "CLEARANCE", "BELOW", "SPRINKLER", "DEFLECTOR"]
    a = _anchor("MAINTAIN CLEARANCE BELOW SPRINKLER DEFLECTOR", _line(sheet))
    assert a.status in ("EXACT", "FUZZY") and a.rect_pdf is not None


def test_window_slack_is_derived_from_the_overlap_floor():
    # The drift budget must come from the floor, not a hand-picked constant, so
    # the two can never disagree: a window is the same length as the query, so
    # drift can only come from a token the floor already permits to differ.
    import math

    from drawing_analyzer.anchor import _FUZZY_WINDOW_MIN_OVERLAP, _fuzzy_window_slack

    for m in (4, 7, 8, 12, 20, 40):
        allowed = m - math.ceil(m * _FUZZY_WINDOW_MIN_OVERLAP)
        assert _fuzzy_window_slack(m) == max(1, allowed)


def test_veto_considers_every_candidate_not_only_the_best_scoring():
    # Review feedback on this PR. Filtering only the best-overlap windows discards
    # a legitimate match whenever a higher-scoring WRONG-number occurrence exists
    # elsewhere on the sheet. Here a 20-token quote meets two copies:
    #   row A — identical but 500 -> 600: 19/20 = 0.95, the sole best window
    #   row B — the correct 500, with two OCR word errors: 18/20 = 0.90
    # Vetoing row A and stopping there returned UNANCHORED and never looked at
    # row B, so the veto turned a real finding into a phantom hallucination signal.
    quote = ("FIRE PUMP RATED AT 500 GPM AND 100 PSI NET AT THE PUMP DISCHARGE "
             "FLANGE AS SHOWN PER NFPA 20")
    tokens = quote.split()
    assert len(tokens) == 20, len(tokens)          # the scores below depend on this

    row_a = list(tokens); row_a[4] = "600"                     # wrong measurement
    row_b = list(tokens); row_b[11] = "AAT"; row_b[13] = "TEH"  # right measurement, 2 typos
    words = _line(row_a, y=100) + _line(row_b, y=900)

    a = _anchor(quote, words)
    assert a.status == "FUZZY", (
        f"a correct-measurement window at 0.90 was discarded because a "
        f"wrong-measurement window at 0.95 outscored it ({a.status}/{a.method})"
    )
    ymid = (a.rect_pdf[1] + a.rect_pdf[3]) / 2.0
    assert ymid > 500, (
        f"anchored to the WRONG-number row at y={ymid:.0f}; it must reach the "
        f"correct-number row near y=900"
    )


def test_best_scoring_window_still_wins_when_it_passes_the_veto():
    # The other direction: the veto must not change ranking among candidates that
    # all pass it. Two correct-number copies, one a better match — the better one
    # still wins, exactly as before the veto existed.
    quote = "PROVIDE 6 INCH DRAIN AT COLUMN LINE 4"
    tokens = quote.split()
    exact_row = list(tokens)
    noisy_row = list(tokens); noisy_row[5] = "COL"
    words = _line(noisy_row, y=100) + _line(exact_row, y=900)

    a = _anchor(quote, words)
    assert a.status == "EXACT"                      # the verbatim row wins outright
    ymid = (a.rect_pdf[1] + a.rect_pdf[3]) / 2.0
    assert ymid > 500
