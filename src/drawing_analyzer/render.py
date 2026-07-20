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
import platform
import re
from pathlib import Path
from typing import Callable, Iterator

import pymupdf  # AGPL-3.0 — see module docstring.

from . import tiling
from .diagnostics import get_logger
from .models import (
    COORDINATE_SPACE_VERSION,
    ImageTile,
    PageGeometry,
    RenderedSheet,
    SheetGeometry,
    SheetRef,
    transform_rect,
)
from .source_registry import (
    ACCEPTED,
    DUPLICATE,
    EMPTY,
    ENCRYPTED,
    UNREADABLE,
    InputInventory,
    SourceDocument,
    assign_source_ids,
    canonical_path,
    content_sha256,
    current_content_sha256,
    format_source_id,
    page_dimensions_ok,
)

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

    Back-compat wrapper: the Phase 18B pipeline classifies inputs up front with
    :func:`inspect_inputs` and enumerates only accepted documents; this keeps
    the old ``paths → refs`` shape for existing callers/tests. The ``paths`` are
    treated as the accepted, deduped set (source ids are assigned over them in
    order), so pass an already-filtered list to keep ids aligned with the
    inventory.
    """
    source_ids = assign_source_ids(pdf_paths)
    seen_canon: set[str] = set()
    refs: list[SheetRef] = []
    for path in pdf_paths:
        path = Path(path)
        canon = canonical_path(path)
        if canon in seen_canon:      # a duplicate selection enumerates once
            continue
        try:
            doc = pymupdf.open(str(path))
        except Exception:
            continue
        try:
            count = doc.page_count
            source_id = source_ids.get(str(path), "")
            for i in range(count):
                refs.append(
                    SheetRef(
                        pdf_path=path,
                        page_index=i,
                        source_name=path.name,
                        page_count=count,
                        source_id=source_id,
                    )
                )
        finally:
            doc.close()
        seen_canon.add(canon)
    return refs


def _classify_input(path: Path) -> tuple[str, int, str]:
    """Open one PDF and classify it: ``(status, page_count, sanitized_error)``.

    The single PyMuPDF-touching step of the inventory (I-5), and deliberately
    **file-level**: it distinguishes encrypted (password-required) from
    plain-corrupt from zero-page, and reports the page count. A *single* bad or
    pathological page does **not** reject the whole file — that is handled
    per-page in :func:`iter_rendered_sheets` (§10.5), which also dimension-checks
    each page *before* rasterizing it so a pathological box fails visibly
    without exhausting memory (§10.7).
    """
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # noqa: BLE001 - a bad file is data, not a crash
        return UNREADABLE, 0, _sanitize_open_error(exc)
    try:
        # PyMuPDF exposes password state as needs_pass / needsPass; a doc that
        # still needs a password after a blank authenticate is encrypted.
        needs_pass = bool(getattr(doc, "needs_pass", False) or getattr(doc, "needsPass", False))
        if needs_pass:
            return ENCRYPTED, 0, "password-protected (no password supplied)"
        try:
            count = int(doc.page_count)
        except Exception as exc:  # noqa: BLE001
            return UNREADABLE, 0, _sanitize_open_error(exc)
        if count <= 0:
            return EMPTY, 0, "the PDF has zero pages"
        return ACCEPTED, count, ""
    finally:
        doc.close()


_ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\|/)[^\s'\"]*[/\\][^\s'\"]*")


def _sanitize_open_error(exc: BaseException) -> str:
    """A short, **path-free** reason string for a rejected input.

    A PyMuPDF / OSError message routinely echoes the offending absolute path
    (``[Errno 2] No such file or directory: '/home/alice/secret/M-101.pdf'``),
    and this string flows into ``ctx.errors`` and the report — so any
    absolute-path token is replaced with ``<path>`` before it can leak the
    user's directory structure. Then whitespace-collapse and truncate.
    """
    msg = str(exc).strip() or type(exc).__name__
    msg = _ABS_PATH_RE.sub("<path>", msg)
    return " ".join(msg.split())[:160]


def inspect_inputs(pdf_paths: list[Path]) -> InputInventory:
    """Classify every selected input path once (Phase 18B, DA-002).

    Returns an :class:`~drawing_analyzer.source_registry.InputInventory` whose
    documents are in input order. Each path is classified ``ACCEPTED`` /
    ``DUPLICATE`` (same canonical path already accepted) / ``UNREADABLE``
    (missing, permission-denied, corrupt, not a PDF, or a page that won't load)
    / ``ENCRYPTED`` (password-required) / ``EMPTY`` (zero pages). ``source_id``
    is assigned ``SRC-####`` over the **accepted** stream only, so a rejected
    input never consumes an id and the accepted ids match what
    :func:`list_sheets` derives from :attr:`InputInventory.accepted_paths`.

    Accepted docs carry a stat-guarded ``content_sha256`` (the revision identity
    Phase 18C checks) plus page count and size. This is the one inventory pass;
    downstream stages consume accepted documents and never re-open a rejected
    file with a lower-level iterator.
    """
    documents: list[SourceDocument] = []
    accepted_canon: dict[str, str] = {}   # canonical path → accepted source_id
    order = 0
    for path in pdf_paths:
        path = Path(path)
        canon = canonical_path(path)
        display = path.name
        if canon in accepted_canon:
            documents.append(SourceDocument(
                source_id="", pdf_path=path, display_name=display, input_order=0,
                status=DUPLICATE,
                error="the same file was selected more than once (processed once)",
                duplicate_of=accepted_canon[canon],
            ))
            continue
        status, count, err = _classify_input(path)
        if status != ACCEPTED:
            documents.append(SourceDocument(
                source_id="", pdf_path=path, display_name=display, input_order=0,
                status=status, page_count=count, error=err,
            ))
            continue
        # Accepted — assign the next id and capture the revision identity.
        try:
            sha, size, mtime = content_sha256(path)
        except OSError as exc:
            documents.append(SourceDocument(
                source_id="", pdf_path=path, display_name=display, input_order=0,
                status=UNREADABLE, page_count=count,
                error=f"could not read stable file contents: {_sanitize_open_error(exc)}",
            ))
            continue
        order += 1
        sid = format_source_id(order)
        accepted_canon[canon] = sid
        documents.append(SourceDocument(
            source_id=sid, pdf_path=path, display_name=display, input_order=order,
            status=ACCEPTED, page_count=count,
            content_sha256=sha, byte_size=size, initial_mtime_ns=mtime,
        ))
    return InputInventory(documents=documents)


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


def _renderer_environment_fingerprint() -> str:
    """OS/arch + rasterizer versions — the environment that decides pixels (§11.5).

    A level-1 cache moved between installations with different font substitution or
    raster behaviour must not produce a hit, so the platform and the PyMuPDF/MuPDF
    build are folded into the render identity: a cross-environment entry then misses
    safely rather than serving pixels this install would not reproduce.
    """
    mupdf = getattr(pymupdf, "mupdf_version", None) or getattr(pymupdf, "MUPDF_VERSION", "?")
    return (
        f"{platform.system()}/{platform.machine()}"
        f"|pymupdf={pymupdf.__version__}|mupdf={mupdf}"
    )


# Bumped when the render-identity SCHEME changes (a new term / a changed meaning),
# so every pre-change level-1 entry misses once and re-renders. Phase 19B (DA-004)
# replaced the per-page object-graph fingerprint — which missed page rotation,
# CropBox origin, and rendered annotation appearance streams — with the whole
# **source** content hash (``SourceDocument.content_sha256``), which covers every
# byte of the file (so rotation, CropBox, and annotations are all captured), plus
# the canonical coordinate-space version and the renderer-environment fingerprint.
_RENDER_IDENTITY_SCHEME = "render-identity-v3"

_XREF_REF_RE = re.compile(r"(?<!\d)(\d+)\s+\d+\s+R\b")
_PARENT_REF_RE = re.compile(r"/Parent\s+\d+\s+\d+\s+R\b")
_MAX_PAGE_DEPENDENCY_OBJECTS = 20_000
_INHERITED_PAGE_KEYS = ("Resources", "MediaBox", "CropBox", "Rotate", "UserUnit")
_CATALOG_RENDER_KEYS = ("OCProperties", "OutputIntents")


def _refs_in(text: str) -> set[int]:
    return {int(match.group(1)) for match in _XREF_REF_RE.finditer(text or "")}


def _page_dependency_sha256(
    page: "pymupdf.Page",
    whole_source_sha256: str,
    object_cache: "dict[int, tuple[bytes, tuple[int, ...]]] | None" = None,
) -> str:
    """Hash the transitive PDF dependencies capable of changing this page's pixels.

    The page-tree ``/Parent`` is handled specially: traversing it wholesale reaches
    ``/Kids`` and makes every sibling page a dependency.  We instead hash the page
    dictionary and resolve only its effective inherited rendering attributes.  All
    other references are walked transitively, including streams, fonts, images,
    forms, annotations and appearance streams.  Document globals that influence
    rendering are included too.  Any uncertainty safely falls back to the supplied
    whole-source hash; false misses are acceptable, while a false hit is not.
    """
    source_token = str(whole_source_sha256)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", source_token):
        return "source:" + str(whole_source_sha256)
    doc = page.parent
    object_cache = object_cache if object_cache is not None else {}
    try:
        xref_len = int(doc.xref_length())
        page_xref = int(page.xref)
        if page_xref <= 0 or page_xref >= xref_len:
            raise ValueError("invalid page xref")

        inherited_parts: list[str] = []
        inherited_refs: set[int] = set()
        unresolved = set(_INHERITED_PAGE_KEYS)
        current = page_xref
        visited_parents: set[int] = set()
        while current > 0 and current not in visited_parents:
            visited_parents.add(current)
            for key in tuple(unresolved):
                kind, value = doc.xref_get_key(current, key)
                if kind and kind != "null":
                    inherited_parts.append(f"{key}:{kind}:{value}")
                    inherited_refs.update(_refs_in(value))
                    unresolved.remove(key)
            kind, parent_value = doc.xref_get_key(current, "Parent")
            parent_refs = sorted(_refs_in(parent_value)) if kind == "xref" else []
            if len(parent_refs) > 1:
                raise ValueError("ambiguous page parent")
            current = parent_refs[0] if parent_refs else 0

        global_parts: list[str] = []
        global_refs: set[int] = set()
        catalog = int(doc.pdf_catalog())
        for key in _CATALOG_RENDER_KEYS:
            kind, value = doc.xref_get_key(catalog, key)
            if kind and kind != "null":
                global_parts.append(f"catalog:{key}:{kind}:{value}")
                global_refs.update(_refs_in(value))

        # A widget without /AP may be synthesized from these AcroForm defaults.
        # Do not traverse /Fields: that would lead through widgets on every page.
        acro_kind, acro_value = doc.xref_get_key(catalog, "AcroForm")
        acro_refs = sorted(_refs_in(acro_value)) if acro_kind == "xref" else []
        if len(acro_refs) > 1:
            raise ValueError("ambiguous AcroForm reference")
        if acro_refs:
            acro_xref = acro_refs[0]
            for key in ("DR", "DA", "Q", "NeedAppearances"):
                kind, value = doc.xref_get_key(acro_xref, key)
                if kind and kind != "null":
                    global_parts.append(f"acroform:{key}:{kind}:{value}")
                    global_refs.update(_refs_in(value))

        digest = hashlib.sha256()
        digest.update(b"drawing-analyzer-page-dependencies-v1\0")
        for part in sorted(inherited_parts + global_parts):
            digest.update(part.encode("utf-8", errors="surrogatepass"))
            digest.update(b"\0")

        queue = [page_xref, *sorted(inherited_refs | global_refs)]
        seen: set[int] = set()
        while queue:
            xref = int(queue.pop())
            if xref in seen:
                continue
            if xref <= 0 or xref >= xref_len:
                raise ValueError(f"out-of-range referenced xref {xref}")
            seen.add(xref)
            if len(seen) > _MAX_PAGE_DEPENDENCY_OBJECTS:
                raise ValueError("page dependency graph exceeded safety cap")
            cached_object = object_cache.get(xref)
            if cached_object is None:
                obj = doc.xref_object(xref, compressed=False)
                object_digest = hashlib.sha256()
                object_digest.update(obj.encode("utf-8", errors="surrogatepass"))
                object_digest.update(b"\0")
                if doc.xref_is_stream(xref):
                    raw = doc.xref_stream_raw(xref)
                    if raw is None:
                        raise ValueError(f"stream {xref} could not be read")
                    object_digest.update(raw)
                    object_digest.update(b"\0")
                cached_object = (
                    object_digest.digest(),
                    tuple(sorted(_refs_in(obj))),
                )
                object_cache[xref] = cached_object
            object_hash, object_refs = cached_object
            digest.update(f"xref:{xref}\0".encode("ascii"))
            digest.update(object_hash)
            digest.update(b"\0")
            refs = object_refs
            if xref == page_xref:
                # The cached generic ref list includes /Parent; recompute this one
                # small page dictionary without it so /Kids never enters the graph.
                obj = doc.xref_object(xref, compressed=False)
                refs = tuple(sorted(_refs_in(_PARENT_REF_RE.sub("", obj))))
            for ref in sorted(refs, reverse=True):
                if ref not in seen:
                    queue.append(ref)
        return "page:" + digest.hexdigest()
    except Exception as exc:  # noqa: BLE001 - correctness-first fallback
        _log.debug(
            "page-local render identity unavailable for page %s; using whole source: %s",
            getattr(page, "number", "?"), exc,
        )
        return "source:" + str(whole_source_sha256)


def sheet_render_identity(
    page: "pymupdf.Page",
    *,
    content_sha256: str,
    page_index: int,
    page_count: int,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    dependency_cache: "dict[int, tuple[bytes, tuple[int, ...]]] | None" = None,
) -> str:
    """A stable digest of everything that determines this sheet's rendered images
    **except** the model/request params — computed without rasterizing.

    The source's ``content_sha256`` is the trusted root, while a conservative
    per-page dependency walk narrows it to the objects capable of changing this
    page's pixels: content streams, forms, images, fonts, effective inherited page
    attributes, annotations/appearance streams, and relevant document rendering
    globals. This lets an edit to one page preserve sibling-page hits. If the
    graph is malformed, ambiguous, or exceeds its safety bound, identity falls
    back to the whole-source hash, so optimization can create false misses but
    never a false hit. ``page_index`` / ``page_count`` name the page. The rest
    fingerprints the render *configuration*: the coordinate-space version, the
    renderer environment (§11.5), the annotation-render policy, the grid + overlap,
    the resolved target (which flips on the raster/vector split), the near-blank
    suppression mode, and the text-extraction cap. A cache keyed on this (see
    :func:`digest_cache.digest_cache_key_level1`) serves an unchanged sheet's digest
    without ever rendering it.
    """
    is_raster = len(page.get_text("words")) == 0
    total_images = tiling.total_images_for_grid(rows, cols)
    target_px = tiling.target_long_edge_px(total_images, is_raster=is_raster)
    near_blank, near_blank_bytes = _near_blank_config()
    page_dependency = _page_dependency_sha256(
        page, content_sha256, object_cache=dependency_cache
    )
    parts = [
        _RENDER_IDENTITY_SCHEME,
        f"content_dependency={page_dependency}",
        f"page_index={int(page_index)}",
        f"page_count={int(page_count)}",
        f"coord_space={COORDINATE_SPACE_VERSION}",
        f"env={_renderer_environment_fingerprint()}",
        "render_annots=1",                 # current policy: annotations ARE rendered
        f"rows={rows}",
        f"cols={cols}",
        f"overlap={overlap_frac:.4f}",
        f"target={target_px}",
        f"raster={int(is_raster)}",
        f"nearblank={int(near_blank)}:{near_blank_bytes if near_blank else 0}",
        f"textcap={SHEET_TEXT_MAX_CHARS}",
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


def page_geometry(page: "pymupdf.Page") -> PageGeometry:
    """Capture ``page``'s canonical geometry + the page↔view transforms (Phase 19).

    The one place the PyMuPDF matrices are read: ``page.rotation_matrix`` maps the
    un-rotated, CropBox-relative page space that ``get_text`` / annotations use into
    the post-CropBox, post-rotation **page-view** space the rendered images live in;
    ``page.derotation_matrix`` is its inverse (used by the markup writer). Stored as
    plain floats so no PyMuPDF type escapes this module (I-5).
    """
    r = page.rect
    return PageGeometry(
        coordinate_space=COORDINATE_SPACE_VERSION,
        view_width_pt=float(r.width),
        view_height_pt=float(r.height),
        media_box=[float(v) for v in page.mediabox],
        crop_box=[float(v) for v in page.cropbox],
        rotation=int(page.rotation or 0),
        page_to_view=[float(v) for v in page.rotation_matrix],
        view_to_page=[float(v) for v in page.derotation_matrix],
    )


def _words_to_view(words: list, geometry: PageGeometry) -> list:
    """Transform ``get_text('words')`` rects into canonical PAGE_VIEW_V2 space.

    ``get_text`` reports un-rotated, CropBox-relative coordinates; the anchor
    resolver, verifier, and tile grid all work in page-view space, so the word
    rects are transformed **once** here (in a blessed PyMuPDF module) to match the
    images the model saw. On an un-rotated page the transform is the identity, so
    the words pass through untouched — the common case pays nothing. Each word tuple
    keeps its non-geometry tail (``word, block, line, word_no``) verbatim.
    """
    if geometry.has_identity_transform:
        return list(words)
    m = geometry.page_to_view
    out: list = []
    for w in words:
        try:
            # ``require_area=False``: a degenerate (zero-area) word — possible in an
            # OCR/text layer — still has a valid POSITION, so it is transformed into
            # view space like every other word rather than kept in the wrong (page)
            # space, which would mix coordinate spaces in the anchor union.
            vx0, vy0, vx1, vy1 = transform_rect(
                (w[0], w[1], w[2], w[3]), m, require_area=False
            )
            out.append((vx0, vy0, vx1, vy1, *tuple(w[4:])))
        except (ValueError, TypeError, IndexError):
            # Only truly-unusable (non-finite / non-numeric) coordinates reach here;
            # such a word can never anchor, so drop it rather than pollute the
            # stream with mixed-space coordinates.
            continue
    return out


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
    geometry = page_geometry(page)

    # Text layer first — negligible cost (measured 0.32 s / 8 sheets / 6,636
    # words) and it decides the render target. ``words`` are plain tuples, so no
    # PyMuPDF type escapes this module (I-5 isolation). They are transformed into
    # canonical PAGE_VIEW_V2 space (Phase 19) so anchoring/verification/tiling all
    # share the frame the model saw — a no-op on an un-rotated page.
    raw_text = page.get_text() or ""
    words = _words_to_view(list(page.get_text("words")), geometry)
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
        geometry=geometry,
    )


def iter_rendered_sheets(
    pdf_paths: list[Path],
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    only: "set[tuple[str, int]] | None" = None,
    on_page_error: "Callable[[SheetRef, Exception], None] | None" = None,
) -> Iterator[RenderedSheet]:
    """Yield a :class:`RenderedSheet` for every page across all ``pdf_paths``.

    Each PDF is opened once and its pages rendered in order, so the dominant
    cost (rasterization) streams sheet-by-sheet — the caller can digest each
    sheet as it arrives and report progress without holding the whole set in
    memory. Pass the inventory's accepted paths (see :func:`inspect_inputs`);
    a PDF that fails to open still raises, since a rejected file should never
    reach here.

    Page-level resilience (§10.5): if a single page fails to load/render, the
    remaining pages of that PDF — and every other PDF — still stream. The failed
    page is reported via ``on_page_error(ref, exc)`` (so the caller can record a
    failed sheet and count it) and skipped, rather than aborting the run.

    ``only`` — when given, a set of ``(str(pdf_path), page_index)`` identities;
    pages not in it are skipped **without rendering**. The pipeline's level-1
    cache uses this to render only the sheets that actually missed the cache, so
    a fully-cached re-run rasterizes nothing.
    """
    source_ids = assign_source_ids(pdf_paths)
    for path in pdf_paths:
        path = Path(path)
        doc = pymupdf.open(str(path))
        try:
            count = doc.page_count
            source_id = source_ids.get(str(path), "")
            for i in range(count):
                if only is not None and (str(path), i) not in only:
                    continue
                ref = SheetRef(
                    pdf_path=path,
                    page_index=i,
                    source_name=path.name,
                    page_count=count,
                    source_id=source_id,
                )
                try:
                    page = doc[i]
                    rect = page.rect
                    # Dimension preflight BEFORE get_pixmap: a pathological box
                    # would otherwise allocate a ruinous pixmap (§10.7). Failing
                    # here skips just this page, not the file (§10.5).
                    if not page_dimensions_ok(float(rect.width), float(rect.height)):
                        raise ValueError(
                            f"pathological page size {rect.width:.0f}×{rect.height:.0f} pt"
                        )
                    sheet = render_sheet(
                        page, ref, rows=rows, cols=cols, overlap_frac=overlap_frac
                    )
                except Exception as exc:  # noqa: BLE001 - one bad page never aborts the set
                    _log.warning(
                        "render failed for %s: %s", ref.display_label, exc
                    )
                    if on_page_error is not None:
                        on_page_error(ref, exc)
                    continue
                yield sheet
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
    geometry = page_geometry(page)
    raw_text = page.get_text() or ""
    words = _words_to_view(list(page.get_text("words")), geometry)
    return SheetGeometry(
        ref=ref,
        page_width_pt=geometry.view_width_pt,
        page_height_pt=geometry.view_height_pt,
        rows=rows,
        cols=cols,
        overlap_frac=overlap_frac,
        words=words,
        sheet_text=_cap_sheet_text(raw_text),
        is_raster=len(words) == 0,
        geometry=geometry,
    )


def iter_sheet_prescan(
    pdf_paths: list[Path],
    *,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    snapshot_by_path: "dict[str, tuple[str, int, int]] | None" = None,
) -> "Iterator[tuple[SheetRef, str, SheetGeometry]]":
    """Yield ``(ref, render_identity, geometry)`` per page **without rendering**.

    The cheap pre-render pass behind the level-1 cache: for every sheet it lifts
    the render identity (:func:`sheet_render_identity`) the cache keys on and the
    lightweight geometry the QC stages need, from page-object access alone. The
    pipeline uses the identities to decide which sheets can skip rasterization and
    only feeds the misses to :func:`iter_rendered_sheets`.

    The render identity derives a conservative page-local dependency hash from the
    source's ``content_sha256`` (computed **once per source**) and falls back to
    that whole-source hash whenever dependency isolation is uncertain. Crucially,
    it uses the bytes on disk *at prescan time*. ``snapshot_by_path`` carries the inventory's captured
    ``str(path) -> (sha, byte_size, mtime_ns)`` so the common (unchanged) case
    reuses the hash via a ``stat`` fast-gate without re-reading; a source whose
    ``stat`` drifted since the inventory is **re-hashed now**
    (:func:`~drawing_analyzer.source_registry.current_content_sha256`), so a file
    rewritten between the inventory and this prescan keys on its *current* revision
    and a stale level-1 hit is impossible (§10.6). If the content genuinely can't be
    hashed (unreadable / mid-rewrite), the identity falls back to the source's
    **canonical path** — so two different unhashable sources can never collide on one
    cache entry, and the sheet simply always renders.
    """
    source_ids = assign_source_ids(pdf_paths)
    snapshot_by_path = snapshot_by_path or {}
    for path in pdf_paths:
        path = Path(path)
        sha = current_content_sha256(path, snapshot_by_path.get(str(path)))
        if not sha:
            # No usable content hash: disambiguate by source so a false cross-source
            # hit is impossible, and (not being a real content hash) it always misses.
            sha = f"unhashed:{canonical_path(path)}"
        doc = pymupdf.open(str(path))
        try:
            count = doc.page_count
            source_id = source_ids.get(str(path), "")
            dependency_cache: dict[int, tuple[bytes, tuple[int, ...]]] = {}
            for i in range(count):
                ref = SheetRef(
                    pdf_path=path,
                    page_index=i,
                    source_name=path.name,
                    page_count=count,
                    source_id=source_id,
                )
                page = doc[i]
                identity = sheet_render_identity(
                    page, content_sha256=sha, page_index=i, page_count=count,
                    rows=rows, cols=cols, overlap_frac=overlap_frac,
                    dependency_cache=dependency_cache,
                )
                geometry = _sheet_geometry_no_render(
                    page, ref, rows=rows, cols=cols, overlap_frac=overlap_frac
                )
                yield ref, identity, geometry
        finally:
            doc.close()
