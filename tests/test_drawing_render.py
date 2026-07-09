"""Render-stage tests: vector text-layer extraction + raster-fallback target.

The text-layer cap is a pure helper and runs without PyMuPDF. The extraction /
target-selection tests render a synthetic 2-page PDF (one vector-text page, one
blank/raster-like page) and are skipped when PyMuPDF is unavailable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer import tiling
from drawing_analyzer.models import SheetRef
from drawing_analyzer.render import (
    SHEET_TEXT_MAX_CHARS,
    _cap_sheet_text,
)


def _ref(i: int, pages: int = 2) -> SheetRef:
    return SheetRef(
        pdf_path=Path("set.pdf"), page_index=i, source_name="set.pdf", page_count=pages
    )


# --------------------------------------------------------------------------- #
# _cap_sheet_text (pure — no PyMuPDF)
# --------------------------------------------------------------------------- #


def test_cap_sheet_text_passes_short_text_through():
    text = "SHEET M-101\nVAV-3 SCHEDULE"
    assert _cap_sheet_text(text) == text


def test_cap_sheet_text_truncates_at_cap_with_marker():
    text = "x" * (SHEET_TEXT_MAX_CHARS + 500)
    capped = _cap_sheet_text(text)
    assert capped.startswith("x" * SHEET_TEXT_MAX_CHARS)
    assert capped.endswith("[TRUNCATED]")
    # Exactly the cap of characters is kept before the marker.
    assert len(capped) == SHEET_TEXT_MAX_CHARS + len("\n\n[TRUNCATED]")


def test_cap_sheet_text_boundary_is_not_truncated():
    text = "y" * SHEET_TEXT_MAX_CHARS
    assert _cap_sheet_text(text) == text  # exactly at the cap: untouched


# --------------------------------------------------------------------------- #
# render_sheet extraction + target selection (needs PyMuPDF)
# --------------------------------------------------------------------------- #


def _two_page_doc(pymupdf):
    """One vector-text page + one blank (raster-like, no text layer) page."""
    doc = pymupdf.open()
    p1 = doc.new_page(width=792, height=612)
    p1.insert_text((72, 72), "SHEET M-101 VAV-3 SCHEDULE FP-2 165 psi")
    doc.new_page(width=792, height=612)  # blank -> empty text layer -> raster
    return doc


def test_render_sheet_extracts_vector_text_layer():
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import render_sheet

    doc = _two_page_doc(pymupdf)
    try:
        rs = render_sheet(doc[0], _ref(0), rows=2, cols=2)
    finally:
        doc.close()

    assert rs.is_raster is False
    assert "VAV-3 SCHEDULE" in rs.sheet_text
    assert "165 psi" in rs.sheet_text
    # words are captured for the offline anchor resolver (plain tuples, not sent
    # to the model) — non-empty for a vector page.
    assert len(rs.words) > 0
    first = rs.words[0]
    assert len(first) >= 5  # (x0, y0, x1, y1, word, ...)
    assert isinstance(first[4], str)


def test_render_sheet_flags_blank_page_as_raster():
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import render_sheet

    doc = _two_page_doc(pymupdf)
    try:
        rs = render_sheet(doc[1], _ref(1), rows=2, cols=2)
    finally:
        doc.close()

    assert rs.is_raster is True
    assert rs.sheet_text == ""
    assert rs.words == []


def test_render_sheet_target_selection_vector_vs_raster():
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import render_sheet

    # A 6x6 grid (37 images) is the many-image regime where the default/raster
    # split applies: the vector page renders at 1560, the raster page at 1992.
    doc = _two_page_doc(pymupdf)
    try:
        vector = render_sheet(doc[0], _ref(0), rows=6, cols=6)
        raster = render_sheet(doc[1], _ref(1), rows=6, cols=6)
    finally:
        doc.close()

    vector_long_edge = max(vector.overview.width_px, vector.overview.height_px)
    raster_long_edge = max(raster.overview.width_px, raster.overview.height_px)

    # Rendered long edge lands at (or within rasterizer rounding of) the target.
    assert abs(vector_long_edge - tiling.TARGET_LONG_EDGE_PX_DEFAULT) <= 2
    assert abs(raster_long_edge - tiling.TARGET_LONG_EDGE_PX_RASTER) <= 2
    # The raster fallback is unmistakably higher-resolution than the vector default.
    assert raster_long_edge > vector_long_edge


# --------------------------------------------------------------------------- #
# Blank-tile suppression (Phase 9)
# --------------------------------------------------------------------------- #


def test_render_sheet_suppresses_blank_tiles():
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import render_sheet

    # Text only in the top-left corner: on a 2x2 grid only that tile has content;
    # the other three are pixel-uniform white and are dropped + disclosed.
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((40, 40), "M-101 NORTH")
    try:
        rs = render_sheet(doc[0], _ref(0), rows=2, cols=2)
    finally:
        doc.close()

    assert len(rs.tiles) == 1                 # three blank tiles suppressed
    assert len(rs.omitted_tiles) == 3
    assert (0, 0) not in rs.omitted_tiles      # the content tile survives
    # The overview is never suppressed, even if sparse.
    assert rs.overview.png_bytes


def test_render_sheet_near_blank_is_off_by_default(monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import render_sheet

    # A tile with a tiny mark is NOT pixel-uniform, so the strict default keeps
    # it; only the opt-in near-blank heuristic (env) would drop it.
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=400)
    page.insert_text((10, 20), ".")          # a single faint mark, top-left tile
    try:
        monkeypatch.delenv("DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK", raising=False)
        strict = render_sheet(doc[0], _ref(0), rows=2, cols=2)
        monkeypatch.setenv("DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK", "1")
        monkeypatch.setenv("DRAWING_ANALYZER_NEAR_BLANK_MAX_BYTES", "100000")
        aggressive = render_sheet(doc[0], _ref(0), rows=2, cols=2)
    finally:
        doc.close()

    # Strict keeps the marked tile; near-blank (huge threshold) drops it too.
    assert (0, 0) not in strict.omitted_tiles
    assert (0, 0) in aggressive.omitted_tiles


# --------------------------------------------------------------------------- #
# Render identity (Phase 9 level-1 key input)
# --------------------------------------------------------------------------- #


def test_sheet_render_identity_stable_and_content_sensitive():
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import sheet_render_identity

    doc = pymupdf.open()
    p0 = doc.new_page(width=792, height=612)
    p0.insert_text((72, 72), "SHEET A")
    p1 = doc.new_page(width=792, height=612)
    p1.insert_text((72, 72), "SHEET B DIFFERENT")
    try:
        id_a = sheet_render_identity(doc[0], rows=6, cols=6)
        id_a2 = sheet_render_identity(doc[0], rows=6, cols=6)
        id_b = sheet_render_identity(doc[1], rows=6, cols=6)
        id_a_grid = sheet_render_identity(doc[0], rows=2, cols=2)
    finally:
        doc.close()

    assert id_a == id_a2                      # deterministic for the same page+params
    assert id_a != id_b                       # different page content
    assert id_a != id_a_grid                  # grid/target is part of the identity
    assert pymupdf.__version__ in id_a        # engine version folded in


def test_sheet_render_identity_covers_form_xobjects():
    # A page whose content stream only *invokes* a Form XObject (the real drawing
    # lives in the form) must still re-key when that form changes — otherwise a
    # regenerated sheet would hit a stale level-1 cache entry and skip rendering.
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import sheet_render_identity

    def _wrapped(text):
        src = pymupdf.open()
        sp = src.new_page(width=200, height=200)
        sp.insert_text((30, 100), text)               # content lives in the form
        tgt = pymupdf.open()
        tp = tgt.new_page(width=400, height=400)
        tp.show_pdf_page(pymupdf.Rect(0, 0, 400, 400), src, 0)  # invoke as a form
        return tgt, tp

    d1, p1 = _wrapped("TITLE BLOCK V1")
    d2, p2 = _wrapped("TITLE BLOCK V2 CHANGED")
    try:
        id1 = sheet_render_identity(p1, rows=2, cols=2)
        id2 = sheet_render_identity(p2, rows=2, cols=2)
    finally:
        d1.close()
        d2.close()
    # The wrapper page content is identical; only the invoked form's stream
    # differs — the identity must reflect it (the P1 review fix).
    assert id1 != id2
