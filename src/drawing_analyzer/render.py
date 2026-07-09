"""PyMuPDF rasterization of drawing PDFs into overview + tile images.

This is one of only **two** modules in the codebase that import PyMuPDF (the
other is :mod:`annotate`, which writes cloud annotations onto reviewed PDFs).
Every other drawing module works with the dependency-free geometry in
:mod:`tiling` and the in-memory :class:`RenderedSheet` / :class:`ImageTile`
produced here, so the PDF backend can be replaced (e.g. with pypdfium2 + Pillow)
by rewriting these files alone.

.. warning::
   PyMuPDF is licensed **AGPL-3.0**. If this application is distributed, review
   the licensing implications or swap the two PyMuPDF importers (this module and
   :mod:`annotate`) for a permissively-licensed backend. All PyMuPDF usage is
   contained in those two modules precisely to make that swap a two-file change.

A PDF *page* is treated as one drawing *sheet* (the standard for construction
sets — one D/E-size sheet per page). A multi-sheet PDF therefore yields multiple
sheets, and several PDFs flatten into one ordered sheet list.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterator

import pymupdf  # AGPL-3.0 — see module docstring.

from . import tiling
from .diagnostics import get_logger
from .models import ImageTile, RenderedSheet, SheetGeometry, SheetRef

_log = get_logger()

# Blank-tile suppression (Phase 9). A tile whose pixmap is *pixel-uniform* (every
# pixel identical — a truly empty crop of a sparse sheet) carries no information
# and only spends image tokens + upload time, so it is dropped and disclosed to
# the model. The strict, uniform-only check is always on (it can never drop a
# tile that has any mark on it). An optional near-blank heuristic — a tile whose
# PNG compresses below a byte threshold — is far more aggressive (it *can* drop a
# tile bearing a few faint marks), so it is off by default and env-gated; the
# owner's call is data over savings.
_NEAR_BLANK_ENV = "DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK"
_NEAR_BLANK_BYTES_ENV = "DRAWING_ANALYZER_NEAR_BLANK_MAX_BYTES"
_NEAR_BLANK_DEFAULT_BYTES = 3072
_FALSEY = {"0", "false", "no", "off", ""}


def _is_uniform_pixmap(pix: "pymupdf.Pixmap") -> bool:
    """True iff every pixel in ``pix`` is identical (a truly empty tile).

    Uses ``Pixmap.color_topusage`` — a **C-implemented** scan that returns the
    fraction of the most common pixel; ``1.0`` means one color fills the pixmap.
    Deliberately *not* ``Pixmap.is_unicolor``: in the pinned PyMuPDF that property
    reads the whole samples buffer into Python and iterates it, which is
    pathologically slow (seconds) on exactly the large *uniform* tiles this check
    targets — it can't early-out. Falls back to ``is_unicolor`` only if
    ``color_topusage`` is somehow unavailable.
    """
    try:
        fraction, _pixel = pix.color_topusage()
        return fraction >= 1.0
    except Exception:  # noqa: BLE001 - fall back if the method isn't present
        return bool(getattr(pix, "is_unicolor", False))


def _near_blank_config() -> tuple[bool, int]:
    """``(enabled, max_png_bytes)`` for the opt-in near-blank heuristic."""
    raw = os.environ.get(_NEAR_BLANK_ENV)
    enabled = raw is not None and raw.strip().lower() not in _FALSEY
    threshold = _NEAR_BLANK_DEFAULT_BYTES
    override = os.environ.get(_NEAR_BLANK_BYTES_ENV)
    if override and override.strip().isdigit():
        threshold = int(override.strip())
    return enabled, threshold

# Cap on the extracted text layer spliced into the digest prompt. A dense E-size
# sheet runs a few thousand words (~6.6k words / ~40k chars measured on an 8-sheet
# set); 15k chars comfortably holds a normal sheet's text while bounding the
# prompt for a pathological one (a giant embedded schedule). Overflow is truncated
# with an explicit marker so the model knows the text was clipped, and the event
# is logged (it should be rare).
SHEET_TEXT_MAX_CHARS = 15_000
_SHEET_TEXT_TRUNCATION_MARKER = "\n\n[TRUNCATED]"


def _cap_sheet_text(text: str) -> str:
    """Bound ``text`` to :data:`SHEET_TEXT_MAX_CHARS`, appending a clear marker.

    Pure helper (no rendering) so the cap is unit-testable in isolation. Returns
    ``text`` unchanged when it fits; otherwise the first ``SHEET_TEXT_MAX_CHARS``
    characters plus :data:`_SHEET_TEXT_TRUNCATION_MARKER`.
    """
    if len(text) <= SHEET_TEXT_MAX_CHARS:
        return text
    return text[:SHEET_TEXT_MAX_CHARS] + _SHEET_TEXT_TRUNCATION_MARKER


def list_sheets(pdf_paths: list[Path]) -> list[SheetRef]:
    """Flatten ``pdf_paths`` into an ordered list of sheets (one per page).

    Cheap: opens each PDF only to read its page count. A PDF that cannot be
    opened is skipped (its error surfaces when rendering is attempted), so a
    bad file in a drop never blocks listing the rest.
    """
    refs: list[SheetRef] = []
    for path in pdf_paths:
        path = Path(path)
        try:
            doc = pymupdf.open(str(path))
        except Exception:
            continue
        try:
            count = doc.page_count
            for i in range(count):
                refs.append(
                    SheetRef(
                        pdf_path=path,
                        page_index=i,
                        source_name=path.name,
                        page_count=count,
                    )
                )
        finally:
            doc.close()
    return refs


def _render_clip_pix(
    page: "pymupdf.Page",
    rect: "pymupdf.Rect",
    target_long_edge_px: int,
) -> "pymupdf.Pixmap":
    """Render a clip region of ``page`` to a Pixmap at the target long edge.

    RGB, no alpha (smaller PNGs and all the model needs). Rendering the clip
    directly (rather than the full page then cropping) keeps memory bounded and,
    for vector PDFs, rasterizes each region crisply from the source vectors.
    """
    zoom = tiling.zoom_for_rect(rect.width, rect.height, target_long_edge_px)
    matrix = pymupdf.Matrix(zoom, zoom)
    return page.get_pixmap(matrix=matrix, clip=rect, alpha=False)


def _render_clip(
    page: "pymupdf.Page",
    rect: "pymupdf.Rect",
    target_long_edge_px: int,
) -> tuple[bytes, int, int]:
    """Render a clip region to ``(png_bytes, width_px, height_px)``."""
    pix = _render_clip_pix(page, rect, target_long_edge_px)
    return pix.tobytes("png"), pix.width, pix.height


def _page_content_fingerprint(page: "pymupdf.Page") -> str:
    """Fingerprint a page's content **without rendering** — the cheap gate that
    lets a cache hit skip rasterization entirely (Phase 9, level-1 key).

    Hashes everything that determines the rasterized output: the page's raw
    content-stream bytes (vector ops, text, image-placement operators), the raw
    bytes of every image XObject it references (so a swapped-in image at the same
    xref is caught), and the page rectangle. All from page-object access only —
    no ``get_pixmap`` — so it is orders of magnitude cheaper than a render.
    """
    h = hashlib.sha256()
    doc = page.parent
    for xref in page.get_contents() or []:
        try:
            h.update(doc.xref_stream_raw(xref) or b"")
        except Exception:  # noqa: BLE001 - a missing stream just contributes nothing
            pass
        h.update(b"\x00")
    # Form XObjects — a page whose content stream merely *invokes* a form (the
    # real vector drawing / title block lives in the form, not the page stream)
    # would otherwise fingerprint identically after that form is regenerated,
    # since get_contents() / get_images() cover neither the form's stream. A
    # stale level-1 hit would then serve the wrong digest without rendering.
    # get_xobjects() returns every form reachable from the page (recursively,
    # including nested forms), so hashing each form's raw stream closes the hole.
    # Deduped + sorted by xref for a stable, order-independent digest.
    form_xrefs = sorted({entry[0] for entry in page.get_xobjects()})
    for xref in form_xrefs:
        h.update(f"form={xref}".encode("utf-8"))
        try:
            h.update(doc.xref_stream_raw(xref) or b"")
        except Exception:  # noqa: BLE001
            pass
        h.update(b"\x00")
    # Image XObjects — get_images(full=True) DOES recurse into forms, so a raster
    # nested inside a form is captured here even though its form is hashed above.
    for img in page.get_images(full=True):
        xref = img[0]
        h.update(f"img={xref}".encode("utf-8"))
        try:
            h.update(doc.xref_stream_raw(xref) or b"")
        except Exception:  # noqa: BLE001
            pass
        h.update(b"\x00")
    r = page.rect
    h.update(f"rect={r.width:.3f}x{r.height:.3f}".encode("utf-8"))
    return h.hexdigest()


def sheet_render_identity(
    page: "pymupdf.Page",
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
) -> str:
    """A stable digest of everything that determines this sheet's rendered images
    **except** the model/request params — computed without rasterizing.

    Folds in the PyMuPDF version (the rasterizer can change pixels across
    releases), the grid + overlap, the resolved render target (which flips on the
    raster/vector distinction), the near-blank suppression mode (which changes
    *which* tiles are emitted), and the page-content fingerprint. A cache keyed on
    this (see :func:`digest_cache.digest_cache_key_level1`) can therefore serve an
    unchanged sheet's digest without ever rendering it.
    """
    is_raster = len(page.get_text("words")) == 0
    total_images = tiling.total_images_for_grid(rows, cols)
    target_px = tiling.target_long_edge_px(total_images, is_raster=is_raster)
    near_blank, near_blank_bytes = _near_blank_config()
    parts = [
        f"pymupdf={pymupdf.__version__}",
        f"rows={rows}",
        f"cols={cols}",
        f"overlap={overlap_frac:.4f}",
        f"target={target_px}",
        f"raster={int(is_raster)}",
        f"nearblank={int(near_blank)}:{near_blank_bytes if near_blank else 0}",
        f"page={_page_content_fingerprint(page)}",
    ]
    return "|".join(parts)


# The verification pass renders a small crop around a finding at high DPI. This
# caps the crop's long edge so a coarse (whole-tile) anchor can't produce a huge
# pixmap; it sits under the single-image regime's native long edge, so a crop is
# never API-rejected.
VERIFY_CROP_DPI = 300
_VERIFY_MAX_LONG_EDGE_PX = 2000


def render_region(
    page: "pymupdf.Page",
    rect_pts: "tuple[float, float, float, float] | list[float]",
    dpi: int = VERIFY_CROP_DPI,
) -> tuple[bytes, int, int]:
    """Render a rectangular region (in PDF points) of ``page`` at ``dpi`` DPI.

    Used by the verification pass for a surgical, high-resolution re-look at one
    finding's anchored region. Returns ``(png_bytes, width_px, height_px)``. The
    effective zoom is reduced if ``dpi`` would push the long edge past
    :data:`_VERIFY_MAX_LONG_EDGE_PX`, so even a whole-tile anchor stays a
    reasonable single image. The clip is intersected with the page so a rect that
    was padded past the sheet edge still renders.
    """
    clip = pymupdf.Rect(*rect_pts) & page.rect
    long_pt = max(clip.width, clip.height)
    zoom = dpi / 72.0
    if long_pt > 0:
        zoom = min(zoom, _VERIFY_MAX_LONG_EDGE_PX / long_pt)
    matrix = pymupdf.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    return pix.tobytes("png"), pix.width, pix.height


def iter_region_crops(
    pdf_path: Path,
    requests: list[tuple],
) -> Iterator[tuple]:
    """Render a batch of region crops from one PDF, opening it exactly once.

    ``requests`` is a list of ``(key, page_index, rect_pts, dpi)``. Yields
    ``(key, png_bytes)`` in request order, or ``(key, None)`` for a crop that
    failed to render — including a **whole-file open failure** (a missing /
    corrupt / vanished source PDF): every request degrades to ``(key, None)``
    rather than propagating, so the verification pass stays non-fatal (I-3). This
    keeps all PyMuPDF use inside :mod:`render` (I-5) — the verification pass never
    imports the PDF engine.
    """
    path = Path(pdf_path)
    try:
        doc = pymupdf.open(str(path))
    except Exception:  # noqa: BLE001 - an unopenable PDF must not abort the batch
        for req in requests:
            yield req[0], None
        return
    try:
        for key, page_index, rect_pts, dpi in requests:
            try:
                png, _w, _h = render_region(doc[page_index], rect_pts, dpi)
                yield key, png
            except Exception:  # noqa: BLE001 - one bad crop must not abort the batch
                yield key, None
    finally:
        doc.close()


def render_sheet(
    page: "pymupdf.Page",
    ref: SheetRef,
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
) -> RenderedSheet:
    """Render one already-open page into an overview + ``rows*cols`` tiles.

    Before rasterizing, the page's vector text layer is lifted (cheap and
    lossless): ``page.get_text()`` for the reading-order text spliced into the
    digest prompt, and ``page.get_text("words")`` for the word-rect list the
    anchor resolver consumes. A page with **no** words is treated as raster
    (scanned / pasted image) and rendered at the higher raster target, since
    there the pixels are the only information channel.
    """
    page_rect = page.rect
    w_pt = float(page_rect.width)
    h_pt = float(page_rect.height)

    # Text layer first — negligible cost (measured 0.32 s / 8 sheets / 6,636
    # words) and it decides the render target. ``words`` are plain tuples, so no
    # PyMuPDF type escapes this module (I-5 isolation).
    raw_text = page.get_text() or ""
    words = list(page.get_text("words"))
    is_raster = len(words) == 0
    sheet_text = _cap_sheet_text(raw_text)
    if len(sheet_text) != len(raw_text):
        _log.info(
            "sheet text truncated to %d chars (from %d): %s",
            SHEET_TEXT_MAX_CHARS, len(raw_text), ref.display_label,
        )

    total_images = tiling.total_images_for_grid(rows, cols)
    target_px = tiling.target_long_edge_px(total_images, is_raster=is_raster)

    overview_png, ow, oh = _render_clip(page, page_rect, target_px)
    overview = ImageTile(
        png_bytes=overview_png, width_px=ow, height_px=oh, kind="overview"
    )

    near_blank, near_blank_bytes = _near_blank_config()
    tiles: list[ImageTile] = []
    omitted_tiles: list[tuple[int, int]] = []
    for tr in tiling.tile_rects(
        w_pt, h_pt, rows=rows, cols=cols, overlap_frac=overlap_frac
    ):
        clip = pymupdf.Rect(tr.x0, tr.y0, tr.x1, tr.y1)
        pix = _render_clip_pix(page, clip, target_px)
        # Strict: a pixel-uniform tile is empty — drop it (never drops a tile with
        # any mark). Near-blank (opt-in) also drops a tile whose PNG compresses
        # below the byte threshold.
        if _is_uniform_pixmap(pix):
            omitted_tiles.append((tr.row, tr.col))
            continue
        png = pix.tobytes("png")
        if near_blank and len(png) <= near_blank_bytes:
            omitted_tiles.append((tr.row, tr.col))
            continue
        tiles.append(
            ImageTile(
                png_bytes=png,
                width_px=pix.width,
                height_px=pix.height,
                kind="tile",
                row=tr.row,
                col=tr.col,
                label=tiling.position_label(tr, w_pt, h_pt),
            )
        )

    if omitted_tiles:
        _log.info(
            "suppressed %d blank tile(s) on %s: %s",
            len(omitted_tiles), ref.display_label, omitted_tiles,
        )

    return RenderedSheet(
        ref=ref,
        overview=overview,
        tiles=tiles,
        page_width_pt=w_pt,
        page_height_pt=h_pt,
        rows=rows,
        cols=cols,
        sheet_text=sheet_text,
        words=words,
        is_raster=is_raster,
        omitted_tiles=omitted_tiles,
        overlap_frac=overlap_frac,
    )


def iter_rendered_sheets(
    pdf_paths: list[Path],
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    only: "set[tuple[str, int]] | None" = None,
) -> Iterator[RenderedSheet]:
    """Yield a :class:`RenderedSheet` for every page across all ``pdf_paths``.

    Each PDF is opened once and its pages rendered in order, so the dominant
    cost (rasterization) streams sheet-by-sheet — the caller can digest each
    sheet as it arrives and report progress without holding the whole set in
    memory. A PDF that fails to open raises; callers that want best-effort
    behavior should pre-filter via :func:`list_sheets`.

    ``only`` — when given, a set of ``(str(pdf_path), page_index)`` identities;
    pages not in it are skipped **without rendering**. The pipeline's level-1
    cache uses this to render only the sheets that actually missed the cache, so
    a fully-cached re-run rasterizes nothing.
    """
    for path in pdf_paths:
        path = Path(path)
        doc = pymupdf.open(str(path))
        try:
            count = doc.page_count
            for i in range(count):
                if only is not None and (str(path), i) not in only:
                    continue
                ref = SheetRef(
                    pdf_path=path,
                    page_index=i,
                    source_name=path.name,
                    page_count=count,
                )
                yield render_sheet(
                    doc[i], ref, rows=rows, cols=cols, overlap_frac=overlap_frac
                )
        finally:
            doc.close()


def _sheet_geometry_no_render(
    page: "pymupdf.Page",
    ref: SheetRef,
    *,
    rows: int,
    cols: int,
    overlap_frac: float,
) -> SheetGeometry:
    """Build a :class:`SheetGeometry` from cheap page access — no rasterization.

    Mirrors what :meth:`SheetGeometry.from_rendered` would produce for a rendered
    sheet, but lifts only the (cheap, lossless) text layer + page size, so the QC
    stages have each sheet's geometry even for a sheet that skipped rendering on a
    level-1 cache hit.
    """
    raw_text = page.get_text() or ""
    words = list(page.get_text("words"))
    return SheetGeometry(
        ref=ref,
        page_width_pt=float(page.rect.width),
        page_height_pt=float(page.rect.height),
        rows=rows,
        cols=cols,
        overlap_frac=overlap_frac,
        words=words,
        sheet_text=_cap_sheet_text(raw_text),
        is_raster=len(words) == 0,
    )


def iter_sheet_prescan(
    pdf_paths: list[Path],
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
) -> "Iterator[tuple[SheetRef, str, SheetGeometry]]":
    """Yield ``(ref, render_identity, geometry)`` per page **without rendering**.

    The cheap pre-render pass behind the level-1 cache: for every sheet it lifts
    the render identity (:func:`sheet_render_identity`) the cache keys on and the
    lightweight geometry the QC stages need, from page-object access alone. The
    pipeline uses the identities to decide which sheets can skip rasterization and
    only feeds the misses to :func:`iter_rendered_sheets`.
    """
    for path in pdf_paths:
        path = Path(path)
        doc = pymupdf.open(str(path))
        try:
            count = doc.page_count
            for i in range(count):
                ref = SheetRef(
                    pdf_path=path,
                    page_index=i,
                    source_name=path.name,
                    page_count=count,
                )
                page = doc[i]
                identity = sheet_render_identity(
                    page, rows=rows, cols=cols, overlap_frac=overlap_frac
                )
                geometry = _sheet_geometry_no_render(
                    page, ref, rows=rows, cols=cols, overlap_frac=overlap_frac
                )
                yield ref, identity, geometry
        finally:
            doc.close()
