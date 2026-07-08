"""Dependency-free tile geometry for splitting a drawing sheet into a grid.

This module deliberately imports nothing from PyMuPDF (or any image library).
It computes, in PDF coordinate space (points; 72 pt = 1 inch):

- the clip rectangles for an ``rows x cols`` grid of (optionally overlapping)
  tiles, plus
- the render zoom needed to land a given rectangle at a target pixel size.

``render.py`` consumes these to rasterize tiles. Keeping the geometry pure means
it can be unit-tested without a PDF engine, and the render backend can be
swapped without touching the tiling math.

Why these numbers
-----------------
Claude's vision path caps each image at a per-model token budget *and* a max
long-edge in pixels (Opus 4.8: 4784 tokens / 2576 px; other models: 1568 /
1568). Critically, sending **more than 20 images in one request** drops the
*hard* per-image dimension cap to 2000 px on the long edge, and an image that
**exceeds** that cap is **rejected** (HTTP 400 ``invalid_request_error``), not
downscaled — unlike the <=20-image case, where an oversized image is silently
resized. A 6x6 sheet is 36 tiles + 1 overview = 37 images, so the 2000 px hard
cap applies to every drawing-digest request (Anthropic vision docs, "General
limits").

We therefore render the long edge *under* the cap, not to it. The rasterizer
(PyMuPDF) sizes a clipped pixmap by rounding the transformed clip to a
whole-pixel rectangle — floor the low corner, ceil the high corner (MuPDF
``fz_round_rect``) — so a tile whose edge doesn't fall on an exact pixel
boundary after scaling (the common case for interior tiles, whose origins are
``cell*r - overlap``) comes out at cap+1 px when rendered "to exactly the cap",
and the whole request is rejected.

Two many-image render targets both sit under the cap:

- ``TARGET_LONG_EDGE_PX_DEFAULT`` (1560 px) is the target for an ordinary
  (vector) sheet. The sheet's machine-extracted text layer is now sent verbatim
  in the digest prompt as the source of truth for exact strings (tags, schedule
  values, note numbers), so the tiles no longer have to carry every character at
  maximum resolution — 1560 px keeps note text legible while cutting PNG bytes
  and image tokens ~40% vs the legacy 1992 px. It sits far enough under the cap
  that rounding can never approach it.
- ``TARGET_LONG_EDGE_PX_RASTER`` (1992 px = cap − 8 px) is the fallback for a
  sheet with an *empty* text layer (a scanned or pasted-raster sheet), where the
  pixels are the only information channel and dropping resolution would drop
  data. It renders a few px under the cap; the 8 px margin covers the proven
  ``<=1`` px per-axis ``fz_round_rect`` overshoot (~272 effective DPI on a
  34"x44" E-size sheet, vs. ~49 DPI for the whole sheet sent as one image; the
  margin costs <0.5% of linear resolution), so a rounded tile can never reach
  cap+1 and trip the rejection.

This failure mode is invisible to the hermetic tests because a fake client never
rasterizes or serializes the pixmap.
"""
from __future__ import annotations

from dataclasses import dataclass

# Default grid. A 6x6 split of an E-size sheet lands each tile just under the
# vision cap at ~272 DPI (crisp for 3/32" note text). Overridable per call.
DEFAULT_GRID_ROWS = 6
DEFAULT_GRID_COLS = 6

# Fractional overlap added to each interior tile edge so a symbol / label that
# straddles a tile boundary still appears whole in at least one tile.
DEFAULT_OVERLAP_FRAC = 0.08

# The API's HARD per-image long-edge cap for a >20-image request. An image
# whose long edge exceeds this is rejected (HTTP 400), not downscaled — see the
# module docstring. This is the ceiling, not the render target.
MANY_IMAGES_LONG_EDGE_CAP_PX = 2000

# Margin subtracted from the cap to pick the raster render target. The
# rasterizer rounds a clipped pixmap UP to whole pixels (module docstring), so
# rendering "to exactly the cap" lands a tile at cap+1 px and trips the
# rejection. The proven worst-case overshoot is <=1 px per axis; 8 px is
# generous headroom for any backend/version rounding variance, at <0.5%
# linear-resolution cost.
_MANY_IMAGES_RENDER_MARGIN_PX = 8

# Long-edge render targets for a many-image (>20) request; both sit under the
# hard cap above.
#
# DEFAULT — an ordinary vector sheet. The verbatim text layer now rides in the
# digest prompt as the source of truth for exact strings, so the tiles don't
# have to resolve every character: 1560 px stays crisp for note text while
# cutting PNG bytes / image tokens ~40% vs the legacy 1992 px target. Far enough
# under the cap that rounding can never approach it.
TARGET_LONG_EDGE_PX_DEFAULT = 1560
# RASTER — a sheet whose text layer is empty (scanned / pasted raster). Pixels
# are the only channel there, so it renders at the legacy margin-under-cap
# target rather than dropping resolution outright.
TARGET_LONG_EDGE_PX_RASTER = MANY_IMAGES_LONG_EDGE_CAP_PX - _MANY_IMAGES_RENDER_MARGIN_PX
# Few-image (<=20) requests use the full Opus native long edge, because at <=20
# images the API downscales an oversized image rather than rejecting it (so no
# margin is needed — an off-by-one there is harmless).
TARGET_LONG_EDGE_PX_FEW_IMAGES = 2576

# The >20-images rule is a hard threshold in the vision docs.
MANY_IMAGES_THRESHOLD = 20


@dataclass(frozen=True)
class TileRect:
    """A single tile's clip rectangle in PDF points, with its grid position.

    ``row`` / ``col`` are zero-based. ``(x0, y0)`` is the top-left and
    ``(x1, y1)`` the bottom-right in PDF coordinate space.
    """

    row: int
    col: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def target_long_edge_px(total_images: int, *, is_raster: bool = False) -> int:
    """Pick the per-image long-edge *render target* for a request.

    >20 images must stay strictly under the hard 2000 px dimension cap (the API
    rejects anything over it). Within that regime an ordinary (vector) sheet
    renders at ``TARGET_LONG_EDGE_PX_DEFAULT``: the text layer, sent verbatim in
    the prompt, carries the exact strings, so the tiles trade resolution for a
    ~40% smaller payload. A raster sheet (``is_raster`` — empty text layer)
    instead renders at ``TARGET_LONG_EDGE_PX_RASTER``, a margin below the cap to
    absorb rasterizer rounding (see module docstring), because there the pixels
    are the only information channel. At <=20 images an oversized image is
    downscaled rather than rejected, so the full Opus native long edge
    (``TARGET_LONG_EDGE_PX_FEW_IMAGES``) is safe.
    """
    if total_images > MANY_IMAGES_THRESHOLD:
        return TARGET_LONG_EDGE_PX_RASTER if is_raster else TARGET_LONG_EDGE_PX_DEFAULT
    return TARGET_LONG_EDGE_PX_FEW_IMAGES


def total_images_for_grid(rows: int, cols: int) -> int:
    """Images in one sheet request: ``rows*cols`` tiles plus one overview."""
    return rows * cols + 1


def zoom_for_rect(rect_w_pt: float, rect_h_pt: float, target_px: int) -> float:
    """Render zoom (matrix scale) that lands the rect's long edge at ``target_px``.

    PyMuPDF pixel size = points * zoom, so ``zoom = target_px / longest_edge``.
    Computed per-rect so every tile lands at (or just under) the cap — edge
    tiles, which are slightly smaller after overlap clamping, simply render at a
    marginally higher DPI rather than overshooting the cap.
    """
    longest = max(rect_w_pt, rect_h_pt)
    if longest <= 0:
        return 1.0
    return target_px / longest


def tile_rects(
    page_width_pt: float,
    page_height_pt: float,
    *,
    rows: int = DEFAULT_GRID_ROWS,
    cols: int = DEFAULT_GRID_COLS,
    overlap_frac: float = DEFAULT_OVERLAP_FRAC,
) -> list[TileRect]:
    """Compute ``rows*cols`` overlapping clip rectangles covering the whole page.

    The base grid partitions the page exactly (cell = page / grid); each cell is
    then expanded outward by ``overlap_frac`` of the cell size on every side and
    clamped to the page bounds. Consequences guaranteed (and locked in by tests):

    - exactly ``rows*cols`` rectangles, one per ``(row, col)``;
    - their union is the entire page (the base grid already tiles it; overlap
      only adds), so no region of the sheet is dropped;
    - every rectangle lies within ``[0, W] x [0, H]``.
    """
    if rows < 1 or cols < 1:
        raise ValueError(f"grid must be at least 1x1, got {rows}x{cols}")
    if page_width_pt <= 0 or page_height_pt <= 0:
        raise ValueError(
            f"page dimensions must be positive, got {page_width_pt}x{page_height_pt}"
        )
    overlap_frac = max(0.0, overlap_frac)

    cell_w = page_width_pt / cols
    cell_h = page_height_pt / rows
    ox = cell_w * overlap_frac
    oy = cell_h * overlap_frac

    rects: list[TileRect] = []
    for r in range(rows):
        for c in range(cols):
            base_x0 = c * cell_w
            base_y0 = r * cell_h
            base_x1 = base_x0 + cell_w
            base_y1 = base_y0 + cell_h
            x0 = max(0.0, base_x0 - ox)
            y0 = max(0.0, base_y0 - oy)
            x1 = min(page_width_pt, base_x1 + ox)
            y1 = min(page_height_pt, base_y1 + oy)
            rects.append(TileRect(row=r, col=c, x0=x0, y0=y0, x1=x1, y1=y1))
    return rects


def position_label(rect: TileRect, page_width_pt: float, page_height_pt: float) -> str:
    """A short human-readable placement description for a tile.

    Used in the per-tile text label so the model can place each crop within the
    whole sheet (e.g. "upper-left; ~0-20% across, ~0-17% down"). The model is
    separately told to use the sheet's own grid bubbles / match-lines for
    cross-references — this is a coarse fallback frame.
    """
    cx = (rect.x0 + rect.x1) / 2.0
    cy = (rect.y0 + rect.y1) / 2.0
    horiz = "left" if cx < page_width_pt / 3 else ("right" if cx > 2 * page_width_pt / 3 else "center")
    vert = "upper" if cy < page_height_pt / 3 else ("lower" if cy > 2 * page_height_pt / 3 else "middle")
    quadrant = f"{vert}-{horiz}" if not (vert == "middle" and horiz == "center") else "center"

    def pct(v: float, total: float) -> int:
        return int(round(100.0 * v / total)) if total else 0

    across = f"~{pct(rect.x0, page_width_pt)}-{pct(rect.x1, page_width_pt)}% across"
    down = f"~{pct(rect.y0, page_height_pt)}-{pct(rect.y1, page_height_pt)}% down"
    return f"{quadrant}; {across}, {down}"
