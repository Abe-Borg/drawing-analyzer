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
