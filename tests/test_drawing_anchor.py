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
    # NFKC, dash/quote/prime folding, hyphen->space, lowercase, whitespace collapse.
    assert _normalize("VAV‑ 3") == "vav 3"                 # non-breaking hyphen
    assert _normalize("2-1/2\"") == _normalize("2 1/2″")   # hyphen==space, ″ -> "
    assert _normalize("  RELIEF\nVALVE  ") == "relief valve"    # linebreak collapse
    assert _normalize("“QUOTED”") == '"quoted"'       # curly -> straight
    assert _normalize("Ø6 PIPE") == "o6 pipe"              # Ø diameter -> o


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
