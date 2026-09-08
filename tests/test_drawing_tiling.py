"""Tile-geometry tests for the drawing subsystem.

Pure geometry — no PyMuPDF, no network. Locks in the completeness invariant
(every region of the sheet lands in a tile) and the vision-cap-aware long-edge
target selection.
"""
from __future__ import annotations

import pytest

from drawing_analyzer import tiling

# E-size sheet in PDF points (landscape 44"x34" * 72 pt/in).
E_W = 44 * 72
E_H = 34 * 72


def test_grid_count_is_rows_times_cols():
    rects = tiling.tile_rects(E_W, E_H, rows=6, cols=6)
    assert len(rects) == 36
    # every (row, col) appears exactly once
    coords = {(r.row, r.col) for r in rects}
    assert coords == {(r, c) for r in range(6) for c in range(6)}


def test_union_covers_whole_sheet():
    rects = tiling.tile_rects(E_W, E_H, rows=6, cols=6, overlap_frac=0.08)
    assert min(r.x0 for r in rects) == pytest.approx(0.0)
    assert min(r.y0 for r in rects) == pytest.approx(0.0)
    assert max(r.x1 for r in rects) == pytest.approx(E_W)
    assert max(r.y1 for r in rects) == pytest.approx(E_H)


def test_all_rects_within_page_bounds():
    rects = tiling.tile_rects(E_W, E_H, rows=6, cols=6, overlap_frac=0.08)
    for r in rects:
        assert 0.0 <= r.x0 < r.x1 <= E_W
        assert 0.0 <= r.y0 < r.y1 <= E_H


def test_zero_overlap_tiles_exactly():
    rects = tiling.tile_rects(E_W, E_H, rows=6, cols=6, overlap_frac=0.0)
    area = sum(r.width * r.height for r in rects)
    assert area == pytest.approx(E_W * E_H)


def test_overlap_increases_total_area_and_adjacent_tiles_overlap():
    rects = tiling.tile_rects(E_W, E_H, rows=6, cols=6, overlap_frac=0.08)
    area = sum(r.width * r.height for r in rects)
    # Overlap double-counts the shared bands, so total area exceeds the sheet.
    assert area > E_W * E_H
    by_pos = {(r.row, r.col): r for r in rects}
    left = by_pos[(2, 2)]
    right = by_pos[(2, 3)]
    # Horizontally adjacent interior tiles share an overlapping band.
    assert left.x1 > right.x0


def test_target_long_edge_respects_20_image_threshold():
    # <=20 images: full Opus long edge; >20 images: the reduced vector default.
    assert tiling.target_long_edge_px(10) == tiling.TARGET_LONG_EDGE_PX_FEW_IMAGES
    assert tiling.target_long_edge_px(20) == tiling.TARGET_LONG_EDGE_PX_FEW_IMAGES
    assert tiling.target_long_edge_px(21) == tiling.TARGET_LONG_EDGE_PX_DEFAULT
    # A 6x6 sheet (36 tiles + overview = 37 images) lands in the clamped regime.
    assert tiling.total_images_for_grid(6, 6) == 37
    assert tiling.target_long_edge_px(37) == tiling.TARGET_LONG_EDGE_PX_DEFAULT


def test_raster_sheet_renders_at_the_higher_raster_target():
    # A raster sheet (empty text layer) forgoes the token-saving default: pixels
    # are its only information channel, so it renders at the legacy margin-under-
    # cap target. The <=20-image regime is unaffected (downscale-safe).
    assert tiling.target_long_edge_px(37, is_raster=True) == tiling.TARGET_LONG_EDGE_PX_RASTER
    assert tiling.target_long_edge_px(37, is_raster=False) == tiling.TARGET_LONG_EDGE_PX_DEFAULT
    assert tiling.TARGET_LONG_EDGE_PX_RASTER > tiling.TARGET_LONG_EDGE_PX_DEFAULT
    assert tiling.target_long_edge_px(10, is_raster=True) == tiling.TARGET_LONG_EDGE_PX_FEW_IMAGES


def test_default_target_dropped_to_1560():
    # Locked product decision: the many-image render target drops 1992 -> 1560.
    assert tiling.TARGET_LONG_EDGE_PX_DEFAULT == 1560


def test_many_image_targets_are_strictly_under_the_hard_cap():
    # Both many-image targets must sit BELOW the API's hard reject cap, so that
    # rasterizer rounding (which can round a tile UP by ~1 px) never produces an
    # image that exceeds the cap and gets the whole request rejected (HTTP 400).
    assert tiling.TARGET_LONG_EDGE_PX_DEFAULT < tiling.MANY_IMAGES_LONG_EDGE_CAP_PX
    assert tiling.TARGET_LONG_EDGE_PX_RASTER < tiling.MANY_IMAGES_LONG_EDGE_CAP_PX
    # The raster target is the tight one (cap - 8 px); its margin must comfortably
    # exceed the proven <=1 px rounding overshoot.
    margin = tiling.MANY_IMAGES_LONG_EDGE_CAP_PX - tiling.TARGET_LONG_EDGE_PX_RASTER
    assert margin >= 2


def _mupdf_round_pixels(origin_pt: float, extent_pt: float, zoom: float) -> int:
    """Pixel extent PyMuPDF produces for a clip edge, mirroring ``fz_round_rect``.

    MuPDF builds the pixmap's integer rectangle from the *transformed* clip by
    flooring the low corner and ceiling the high corner (with a 0.001 epsilon),
    so the rendered pixel count can exceed ``extent_pt * zoom`` by up to ~1 px
    when the edge doesn't fall on a whole-pixel boundary. This is the exact
    arithmetic that made every 2000 px-target tile render at 2001 px and get the
    drawing batch rejected.
    """
    import math

    lo = math.floor(origin_pt * zoom + 0.001)
    hi = math.ceil((origin_pt + extent_pt) * zoom - 0.001)
    return hi - lo


def test_rendered_tile_never_exceeds_hard_cap_under_rounding():
    # Regression for the 2000 px many-image rejection: simulate the rasterizer's
    # whole-pixel rounding across many sub-pixel tile origins and assert that NO
    # rendered edge exceeds the hard cap, for the real 6x6 grid on an E-size
    # sheet plus a near-square aspect ratio (the worst case for the short edge).
    cap = tiling.MANY_IMAGES_LONG_EDGE_CAP_PX
    # Check both many-image targets: the reduced vector default AND the raster
    # target (cap - 8 px), which is the tight one the margin exists to protect.
    for target in (tiling.TARGET_LONG_EDGE_PX_DEFAULT, tiling.TARGET_LONG_EDGE_PX_RASTER):
        for page_w, page_h in [(E_W, E_H), (E_H, E_W), (3024.0, 3024.0), (2448.0, 3168.0)]:
            for rect in tiling.tile_rects(page_w, page_h, rows=6, cols=6, overlap_frac=0.08):
                zoom = tiling.zoom_for_rect(rect.width, rect.height, target)
                w_px = _mupdf_round_pixels(rect.x0, rect.width, zoom)
                h_px = _mupdf_round_pixels(rect.y0, rect.height, zoom)
                assert w_px <= cap, (target, page_w, page_h, rect.row, rect.col, w_px)
                assert h_px <= cap, (target, page_w, page_h, rect.row, rect.col, h_px)
            # The overview (whole page at the same target) must also stay under cap.
            zoom = tiling.zoom_for_rect(page_w, page_h, target)
            assert _mupdf_round_pixels(0.0, page_w, zoom) <= cap
            assert _mupdf_round_pixels(0.0, page_h, zoom) <= cap


def test_zoom_for_rect_hits_target_long_edge():
    assert tiling.zoom_for_rect(1000, 500, 2000) == pytest.approx(2.0)
    assert tiling.zoom_for_rect(500, 1000, 2000) == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# Vector render-target override (measurement knob, default off)
# --------------------------------------------------------------------------- #

_MANY = 37  # the real 6x6 grid + overview


def test_override_changes_only_the_vector_many_image_target(monkeypatch):
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1240")

    # Vector, >20 images: the swept value.
    assert tiling.target_long_edge_px(_MANY, is_raster=False) == 1240
    # Raster is NOT overridable — with no text layer the pixels are the only
    # channel, and keeping it fixed preserves raster >= vector, which the cost
    # estimate's upper-bound claim depends on.
    assert tiling.target_long_edge_px(_MANY, is_raster=True) == tiling.TARGET_LONG_EDGE_PX_RASTER
    # <=20 images is a different regime (oversized images are downscaled, not
    # rejected) and is not where the payload problem lives.
    assert tiling.target_long_edge_px(10) == tiling.TARGET_LONG_EDGE_PX_FEW_IMAGES


def test_override_is_read_per_call_not_captured_at_import(monkeypatch):
    """The trap that makes DRAWING_ANALYZER_MODEL ineffective after import.

    A module-level ``os.environ.get`` would freeze the first value the process
    ever saw, so a sweep that sets the variable between runs in one process
    would silently measure the same target twice.
    """
    assert tiling.target_long_edge_px(_MANY) == tiling.TARGET_LONG_EDGE_PX_DEFAULT
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1400")
    assert tiling.target_long_edge_px(_MANY) == 1400
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1100")
    assert tiling.target_long_edge_px(_MANY) == 1100
    monkeypatch.delenv(tiling.TILE_TARGET_PX_ENV)
    assert tiling.target_long_edge_px(_MANY) == tiling.TARGET_LONG_EDGE_PX_DEFAULT


@pytest.mark.parametrize("raw", ["", "   ", "abc", "1560px", "-500", "1.5e3", "0x400"])
def test_invalid_override_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, raw)
    assert tiling.target_long_edge_px(_MANY) == tiling.TARGET_LONG_EDGE_PX_DEFAULT


def test_override_is_clamped_under_the_hard_rejection_cap(monkeypatch):
    """No setting of this variable may construct a request the API rejects.

    A >20-image request whose long edge exceeds 2000 px is rejected outright —
    not downscaled — so an operator typo of "2000" (or "20000") must not be able
    to fail every sheet in a set. The ceiling is the same margin-under-cap the
    raster target uses, because the rasterizer rounds a clipped pixmap up.
    """
    ceiling = tiling.MANY_IMAGES_LONG_EDGE_CAP_PX - tiling._MANY_IMAGES_RENDER_MARGIN_PX
    for typo in ("2000", "2576", "20000"):
        monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, typo)
        assert tiling.target_long_edge_px(_MANY) == ceiling
    # ...and a floor, so a fat-fingered small value still renders a legible crop.
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1")
    assert tiling.target_long_edge_px(_MANY) == tiling._MIN_TILE_TARGET_PX


@pytest.mark.parametrize("target_px", [1100, 1240, 1400, 1560, 1992])
def test_swept_target_never_renders_over_the_hard_cap(monkeypatch, target_px):
    """The rounding guard must hold at every value a sweep can select.

    Same arithmetic as ``test_rendered_tile_never_exceeds_hard_cap_under_rounding``,
    run against the override rather than the two fixed constants.
    """
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, str(target_px))
    effective = tiling.target_long_edge_px(_MANY, is_raster=False)
    cap = tiling.MANY_IMAGES_LONG_EDGE_CAP_PX
    for page_w, page_h in [(E_W, E_H), (E_H, E_W), (3024.0, 3024.0), (2448.0, 3168.0)]:
        for rect in tiling.tile_rects(page_w, page_h, rows=6, cols=6, overlap_frac=0.08):
            zoom = tiling.zoom_for_rect(rect.width, rect.height, effective)
            assert _mupdf_round_pixels(rect.x0, rect.width, zoom) <= cap
            assert _mupdf_round_pixels(rect.y0, rect.height, zoom) <= cap
        zoom = tiling.zoom_for_rect(page_w, page_h, effective)
        assert _mupdf_round_pixels(0.0, page_w, zoom) <= cap
        assert _mupdf_round_pixels(0.0, page_h, zoom) <= cap


def test_lower_target_cuts_image_tokens_quadratically(monkeypatch):
    """Why this knob is the highest-leverage number in the bill.

    Image cost is pixel area over 750, so halving the long edge quarters the
    tokens. The sweep values are chosen against this curve.
    """
    from drawing_analyzer.core.tokenizer import estimate_image_tokens

    def sheet_tokens(target: int) -> int:
        monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, str(target))
        effective = tiling.target_long_edge_px(_MANY, is_raster=False)
        total = 0
        for rect in tiling.tile_rects(E_W, E_H, rows=6, cols=6, overlap_frac=0.08):
            zoom = tiling.zoom_for_rect(rect.width, rect.height, effective)
            total += estimate_image_tokens(
                round(rect.width * zoom), round(rect.height * zoom),
                model="claude-opus-5",
            )
        zoom = tiling.zoom_for_rect(E_W, E_H, effective)
        return total + estimate_image_tokens(
            round(E_W * zoom), round(E_H * zoom), model="claude-opus-5"
        )

    at_1560 = sheet_tokens(1560)
    at_1240 = sheet_tokens(1240)
    # (1240/1560)^2 ~= 0.63, so expect roughly a 37% cut, not a 21% one.
    assert 0.60 < at_1240 / at_1560 < 0.66


def test_changed_target_invalidates_the_level_1_cache_identity(monkeypatch):
    """A sweep must re-render, or the two arms compare the same images.

    The render identity carries ``target=``, so this falls out of the existing
    design — but it is the precondition for an honest A/B, so it is asserted
    rather than assumed.
    """
    import pymupdf

    from drawing_analyzer.render import sheet_render_identity

    doc = pymupdf.open()
    page = doc.new_page(width=E_W, height=E_H)
    page.insert_text((72, 144), "M-101 MECHANICAL PLAN")

    def identity() -> str:
        return sheet_render_identity(
            doc[0], page_index=0, page_count=1, content_sha256="deadbeef",
            rows=6, cols=6, overlap_frac=0.08,
        )

    baseline = identity()
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1240")
    swept = identity()
    monkeypatch.delenv(tiling.TILE_TARGET_PX_ENV)

    assert swept != baseline
    assert "target=1240" in swept
    assert identity() == baseline  # and it comes back when the sweep ends
    doc.close()


def test_invalid_grid_and_dimensions_raise():
    with pytest.raises(ValueError):
        tiling.tile_rects(E_W, E_H, rows=0, cols=6)
    with pytest.raises(ValueError):
        tiling.tile_rects(0, E_H, rows=6, cols=6)


def test_position_label_describes_placement():
    rects = tiling.tile_rects(E_W, E_H, rows=6, cols=6)
    label = tiling.position_label(rects[0], E_W, E_H)
    assert "across" in label and "down" in label
    # top-left tile reads as "upper-left"
    assert "upper" in label and "left" in label


# --------------------------------------------------------------------------- #
# Phase 25 §17.1 — the tile_label contract (r<row>c<col>, 1-based ↔ zero-based)
# --------------------------------------------------------------------------- #


def test_parse_tile_label_maps_one_based_to_zero_based():
    assert tiling.parse_tile_label("r1c1") == [0, 0]
    assert tiling.parse_tile_label("r6c6") == [5, 5]
    assert tiling.parse_tile_label("R2C3") == [1, 2]          # case-insensitive
    assert tiling.parse_tile_label(" r1c1 ") == [0, 0]        # trimmed


def test_parse_tile_label_rejects_malformed_and_out_of_range():
    for bad in ("r0c1", "r1c0", "c1r1", "1,1", "r1", "r1c1x", "rc", "", "r-1c1"):
        assert tiling.parse_tile_label(bad) is None, bad
    assert tiling.parse_tile_label([0, 0]) is None            # not a string
    # Bounds-checked when the grid is known: r7 on a 6x6 grid is out of range.
    assert tiling.parse_tile_label("r7c1", 6, 6) is None
    assert tiling.parse_tile_label("r1c7", 6, 6) is None
    assert tiling.parse_tile_label("r6c6", 6, 6) == [5, 5]
    # Without a grid the label is still self-describing (only the lower bound).
    assert tiling.parse_tile_label("r9c9") == [8, 8]


def test_tile_label_for_is_the_inverse():
    assert tiling.tile_label_for(0, 0) == "r1c1"
    assert tiling.tile_label_for(5, 5) == "r6c6"
    for r in range(6):
        for c in range(6):
            assert tiling.parse_tile_label(tiling.tile_label_for(r, c)) == [r, c]
