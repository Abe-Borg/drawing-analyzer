"""Dependency-free data models for the drawing subsystem.

Kept separate from :mod:`render` so consumers (:mod:`digest`, :mod:`pipeline`)
can reference these shapes without transitively importing the PyMuPDF backend.
Only :mod:`render` produces these; everything else just consumes them.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SheetRef:
    """Identifies one sheet: a single page within a source PDF.

    ``source_id`` is the **host-owned** identity of the input this page belongs
    to (``"SRC-0001"`` …), assigned once per accepted input by
    :func:`render.list_sheets` (DA-001). It is what disambiguates two inputs
    that share a basename: ``source_name`` is display-only and *not* authority.
    It defaults to ``""`` so hand-built refs (older callers, tests that don't
    care about isolation) keep working; every collision-safe lookup falls back
    to ``source_name`` when ``source_id`` is blank (see :func:`source_page_key`).
    """

    pdf_path: Path
    page_index: int          # zero-based
    source_name: str         # pdf_path.name, for display / provenance
    page_count: int          # pages in the source PDF
    source_id: str = ""      # host-owned input identity ("SRC-0001"); "" → source_name

    @property
    def display_label(self) -> str:
        return f"{self.source_name} (page {self.page_index + 1}/{self.page_count})"

    @property
    def key(self) -> tuple[str, int]:
        """Collision-safe ``(source, page)`` key — see :func:`source_page_key`."""
        return (self.source_id or self.source_name, self.page_index)


def source_page_key(obj: Any) -> tuple[str, int]:
    """The collision-safe ``(source, page_index)`` key for any source-scoped object.

    Duck-typed over :class:`SheetRef`, :class:`Finding`, :class:`ConflictLeg`,
    :class:`NumericClaim`, and the geometry records — anything carrying
    ``source_id`` / ``source_name`` / ``page_index`` (or a ``.ref`` that does).
    Uses the host-owned ``source_id`` when populated, so two inputs sharing a
    basename never collide; falls back to ``source_name`` only when no
    ``source_id`` was assigned (hand-built objects, legacy cache). This is the
    one key every internal map/group/lookup must use instead of a bare
    ``(source_name, page_index)`` (DA-001).
    """
    ref = getattr(obj, "ref", None)
    if ref is not None and getattr(ref, "source_name", None) is not None:
        obj = ref
    sid = (getattr(obj, "source_id", "") or "").strip()
    name = getattr(obj, "source_name", "") or ""
    page = int(getattr(obj, "page_index", 0) or 0)
    return (sid or name, page)


# ---------------------------------------------------------------------------
# Canonical page geometry (Phase 19, DA-003)
#
# One coordinate space carries a finding from extraction through anchoring,
# verification, and annotation: **PAGE_VIEW_V2** — top-left origin, *post-CropBox*
# and *post-rotation*, whose width/height match the overview + tile grid the model
# actually saw. It is the only space anchors / tiles / persisted finding rects use.
#
# It exists because PyMuPDF (characterized empirically under the pinned build, not
# assumed — see ``tests/test_drawing_geometry.py``) reports and accepts coordinates
# in *two different* spaces that diverge on a rotated or cropped page:
#
#   - ``page.get_text("words")`` and ``page.add_*_annot(rect)`` use an
#     **un-rotated, CropBox-relative** "page space" (identical rects at every
#     rotation);
#   - ``page.get_pixmap(clip=rect)`` — what rasterizes the tiles the model sees —
#     uses the **rotated page-view** space (``page.rect`` dims).
#
# So a word rect used verbatim as a pixmap clip renders the *wrong* (usually blank)
# region on a rotated page — the DA-003 defect. The fix: transform words into
# page-view space **once** at extraction (in :mod:`render`, a blessed PyMuPDF
# module) via ``page_to_view``; everything downstream then works in one space, and
# only the annotation writer (:mod:`annotate`, the other blessed module) transforms
# back to page space via ``view_to_page`` to place ink. At rotation 0 with a
# default CropBox both matrices are the identity, so the common case is unchanged.
# ---------------------------------------------------------------------------

COORDINATE_SPACE_VERSION = "PAGE_VIEW_V2"

# A 6-float affine matrix in PDF/PyMuPDF convention ``(a, b, c, d, e, f)``:
# a point ``(x, y)`` maps to ``(a*x + c*y + e, b*x + d*y + f)``.
IDENTITY_MATRIX: list[float] = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def is_identity_matrix(matrix: Any, *, tol: float = 1e-6) -> bool:
    """True when ``matrix`` is (within ``tol``) the identity — the no-op transform.

    The rotation/derotation matrices are the identity for an un-rotated page, so a
    caller can skip transforming word rects entirely in the common case.
    """
    try:
        vals = [float(v) for v in matrix]
    except (TypeError, ValueError):
        return False
    if len(vals) != 6:
        return False
    return all(abs(a - b) <= tol for a, b in zip(vals, IDENTITY_MATRIX))


def normalize_rect(rect: Any, *, require_area: bool = True) -> list[float]:
    """Return ``rect`` as a validated ``[x0, y0, x1, y1]`` — finite, corners sorted.

    Sorts the corners (``x0 <= x1``, ``y0 <= y1``) rather than clamping an inverted
    rect: a flip is a *transform* artifact to fold, not a coordinate to truncate.
    Always raises :class:`ValueError` for a non-finite / non-numeric rect. With
    ``require_area`` (the default, for a rect that must become ink) it *also* rejects
    an empty (zero/negative-area) rect, so the caller records a placement error
    instead of drawing a bogus rectangle (Phase 19 §11.2). Pass ``require_area=
    False`` to keep a valid zero-area *position* (a degenerate word's bbox), which
    still transforms to a correct point but carries no area. Never silently repairs
    an impossible rect.
    """
    try:
        x0, y0, x1, y1 = (float(v) for v in rect)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"rect is not four numbers: {rect!r}") from exc
    for v in (x0, y0, x1, y1):
        if not math.isfinite(v):
            raise ValueError(f"non-finite rect coordinate in {rect!r}")
    lo_x, hi_x = (x0, x1) if x0 <= x1 else (x1, x0)
    lo_y, hi_y = (y0, y1) if y0 <= y1 else (y1, y0)
    if require_area and (hi_x <= lo_x or hi_y <= lo_y):
        raise ValueError(f"rect has non-positive area: {rect!r}")
    return [lo_x, lo_y, hi_x, hi_y]


def transform_rect(rect: Any, matrix: Any, *, require_area: bool = True) -> list[float]:
    """Affine-transform ``rect`` by ``matrix`` and return the normalized bounds.

    Transforms all four corners (a rotation moves each to a different place) and
    takes their min/max bounding box, then :func:`normalize_rect` validates it.
    Pure numeric — no PyMuPDF — so anchoring, tests, and any boundary crossing use
    one transform implementation. Matches ``pymupdf.Rect(*rect) * pymupdf.Matrix``
    exactly for the rotation/derotation matrices this codebase uses. ``require_area``
    is forwarded to :func:`normalize_rect`: a boundary rect that must ink keeps the
    default (rejects a degenerate result), while a word-position transform passes
    ``False`` so a zero-area word still lands — correctly — in the target space
    rather than being kept in the wrong one.
    """
    a, b, c, d, e, f = (float(v) for v in matrix)
    x0, y0, x1, y1 = (float(v) for v in rect)
    xs, ys = [], []
    for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        xs.append(a * x + c * y + e)
        ys.append(b * x + d * y + f)
    return normalize_rect([min(xs), min(ys), max(xs), max(ys)], require_area=require_area)


@dataclass(frozen=True)
class PageGeometry:
    """A page's coordinate frame + the transforms between page space and view space.

    ``coordinate_space`` names the version (:data:`COORDINATE_SPACE_VERSION`).
    ``view_width_pt`` / ``view_height_pt`` are the post-CropBox, post-rotation
    dimensions (``page.rect``) — the frame the rendered images live in. ``media_box``
    / ``crop_box`` / ``rotation`` are the raw page attributes (informational /
    cache-identity inputs). ``page_to_view`` maps an un-rotated CropBox-relative rect
    (``get_text`` / annotation space) into page-view space; ``view_to_page`` is its
    inverse. Both are plain 6-float lists so no PyMuPDF type escapes :mod:`render`
    (I-5): the writer re-derives the live matrix from the reopened page, and this
    record is the portable data-contract copy for exports, tests, and manifests.
    """

    coordinate_space: str = COORDINATE_SPACE_VERSION
    view_width_pt: float = 0.0
    view_height_pt: float = 0.0
    media_box: list[float] = field(default_factory=list)
    crop_box: list[float] = field(default_factory=list)
    rotation: int = 0
    page_to_view: list[float] = field(default_factory=lambda: list(IDENTITY_MATRIX))
    view_to_page: list[float] = field(default_factory=lambda: list(IDENTITY_MATRIX))

    @property
    def has_identity_transform(self) -> bool:
        """True when page space and view space coincide (un-rotated page)."""
        return is_identity_matrix(self.page_to_view)

    def to_view(self, rect: Any) -> list[float]:
        """Map a page-space (``get_text``) rect into canonical page-view space."""
        if self.has_identity_transform:
            return normalize_rect(rect)
        return transform_rect(rect, self.page_to_view)

    def to_page(self, rect: Any) -> list[float]:
        """Map a canonical page-view rect back into page space (annotation writing)."""
        if is_identity_matrix(self.view_to_page):
            return normalize_rect(rect)
        return transform_rect(rect, self.view_to_page)

    def to_dict(self) -> dict:
        return {
            "coordinate_space": self.coordinate_space,
            "view_width_pt": self.view_width_pt,
            "view_height_pt": self.view_height_pt,
            "media_box": list(self.media_box),
            "crop_box": list(self.crop_box),
            "rotation": self.rotation,
            "page_to_view": list(self.page_to_view),
            "view_to_page": list(self.view_to_page),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PageGeometry":
        def _mat(v: Any) -> list[float]:
            try:
                out = [float(x) for x in v]
            except (TypeError, ValueError):
                return list(IDENTITY_MATRIX)
            return out if len(out) == 6 else list(IDENTITY_MATRIX)

        return cls(
            coordinate_space=str(d.get("coordinate_space") or COORDINATE_SPACE_VERSION),
            view_width_pt=float(d.get("view_width_pt", 0.0) or 0.0),
            view_height_pt=float(d.get("view_height_pt", 0.0) or 0.0),
            media_box=[float(x) for x in (d.get("media_box") or [])],
            crop_box=[float(x) for x in (d.get("crop_box") or [])],
            rotation=int(d.get("rotation", 0) or 0),
            page_to_view=_mat(d.get("page_to_view")),
            view_to_page=_mat(d.get("view_to_page")),
        )


@dataclass
class ImageTile:
    """A rendered PNG image: either the whole-sheet overview or one grid tile."""

    png_bytes: bytes
    width_px: int
    height_px: int
    kind: str                # "overview" or "tile"
    row: int = -1            # grid row (tiles only; -1 for overview)
    col: int = -1            # grid col (tiles only; -1 for overview)
    label: str = ""          # human placement description (tiles only)


@dataclass
class RenderedSheet:
    """A sheet rendered to an overview image plus a grid of tile images.

    Beyond the imagery, :mod:`render` also lifts the page's vector text layer
    (free, lossless) so the digest can be *grounded* in exact strings and later
    stages can *anchor* findings to on-sheet rectangles:

    - ``sheet_text`` — plain reading-order text (``page.get_text()``), capped and
      marked ``[TRUNCATED]`` if it runs long. Sent verbatim in the digest prompt.
    - ``words`` — ``page.get_text("words")`` output (``(x0, y0, x1, y1, word,
      block, line, word_no)`` tuples, plain Python — no PyMuPDF types leak here).
      Consumed offline by the anchor resolver; never sent to the model.
    - ``is_raster`` — ``True`` when ``words`` is empty (a scanned / pasted-raster
      sheet). Drives the higher raster render target, a prompt disclosure line,
      and a report badge.
    - ``omitted_tiles`` — grid positions dropped by blank-tile suppression
      (populated later; empty by default).
    - ``overlap_frac`` — the fractional tile overlap the sheet was rendered with,
      retained so the anchor resolver can reconstruct the exact tile rectangles
      (``tiling.tile_rects``) it needs for tile-preference disambiguation and
      tile-level anchors. Defaults to the tiling module default.
    """

    ref: SheetRef
    overview: ImageTile
    tiles: list[ImageTile]
    page_width_pt: float
    page_height_pt: float
    rows: int
    cols: int
    sheet_text: str = ""
    words: list[Any] = field(default_factory=list)
    is_raster: bool = False
    omitted_tiles: list[tuple[int, int]] = field(default_factory=list)
    overlap_frac: float = 0.08  # mirrors tiling.DEFAULT_OVERLAP_FRAC
    # Canonical geometry + transforms (Phase 19). ``page_width_pt`` /
    # ``page_height_pt`` above equal ``geometry.view_width_pt`` /
    # ``view_height_pt`` and ``words`` are already in PAGE_VIEW_V2 space; the
    # geometry additionally carries the view↔page transforms the markup writer
    # needs. Defaults to ``None`` so hand-built sheets (older callers, tests) keep
    # working — a ``None`` geometry means an identity transform (un-rotated page).
    geometry: "PageGeometry | None" = None

    @property
    def image_sizes(self) -> list[tuple[int, int]]:
        """``(width, height)`` for every image (overview + tiles), for token est."""
        sizes = [(self.overview.width_px, self.overview.height_px)]
        sizes.extend((t.width_px, t.height_px) for t in self.tiles)
        return sizes


@dataclass
class SheetGeometry:
    """A sheet's text + geometry, **without the rendered image bytes**.

    The QC stages that run *after* the digests — the reference audit, the anchor
    resolver, the verification pass, and the ``sheet_text`` export — need each
    sheet's words / page size / grid, but not its (large) tile PNGs. The batch
    path streams and then discards every :class:`RenderedSheet` after upload, so
    the pipeline captures this lightweight record as sheets render and carries it
    through instead. It exposes exactly the attributes those stages duck-type on
    (``ref``, ``words``, ``page_width_pt`` / ``page_height_pt``, ``rows`` /
    ``cols`` / ``overlap_frac``, ``sheet_text``), so a ``SheetGeometry`` is a
    drop-in for a ``RenderedSheet`` everywhere images aren't needed.
    """

    ref: SheetRef
    page_width_pt: float
    page_height_pt: float
    rows: int
    cols: int
    overlap_frac: float = 0.08
    words: list[Any] = field(default_factory=list)
    sheet_text: str = ""
    is_raster: bool = False
    # PAGE_VIEW_V2 geometry + transforms (Phase 19); see :class:`RenderedSheet`.
    geometry: "PageGeometry | None" = None
    # Phase 26A (§18.2): how many blank tiles the render omitted for this sheet
    # (the documented I-1 exception, disclosed to the model). ``None`` = not
    # recorded — a level-1 cache hit never re-rendered, so the count is unknown
    # there, and the run.log must say so rather than claim zero.
    omitted_tile_count: "int | None" = None

    @classmethod
    def from_rendered(cls, rendered: "RenderedSheet") -> "SheetGeometry":
        return cls(
            ref=rendered.ref,
            page_width_pt=rendered.page_width_pt,
            page_height_pt=rendered.page_height_pt,
            rows=rendered.rows,
            cols=rendered.cols,
            overlap_frac=rendered.overlap_frac,
            words=rendered.words,
            sheet_text=rendered.sheet_text,
            is_raster=rendered.is_raster,
            geometry=rendered.geometry,
            omitted_tile_count=len(rendered.omitted_tiles or []),
        )


# ---------------------------------------------------------------------------
# QC findings — the structured, anchorable, verifiable unit the QC stages
# (reference audit, structured digest findings, critique, cross-sheet QC, the
# deterministic auditors) all produce and every downstream stage (anchor,
# verify, markup, CSV/JSON export, HTML report) consumes. A ``Finding`` carries
# its own provenance and, as it flows through the pipeline, is progressively
# filled in: parsed → anchored (a rectangle on the page) → verified (a small
# per-finding model check, or DETERMINISTIC for the offline auditors).
#
# String taxonomies are kept as plain constants (not ``enum``) so a ``Finding``
# round-trips to/from JSON without custom (de)serialization.
# ---------------------------------------------------------------------------

# ``category`` — what kind of issue.
FINDING_CATEGORIES = frozenset(
    {"code", "conflict", "coordination", "reference", "question"}
)
# ``severity`` — how much it matters.
FINDING_SEVERITIES = frozenset({"high", "medium", "low"})
# ``anchor.status`` — how confidently the finding was placed on the page.
ANCHOR_STATUSES = frozenset({"EXACT", "FUZZY", "TILE", "UNANCHORED"})
# ``verification.status`` — the outcome of the (model or deterministic) check.
VERIFICATION_STATUSES = frozenset(
    {"VERIFIED", "REJECTED", "UNCERTAIN", "DETERMINISTIC", "SKIPPED"}
)
# Arithmetic-provenance vocabulary (Phase 25 §17.5). ``computation_method`` records
# that the *operation* was done by the host (never the model's own arithmetic);
# ``operand_origin`` records whether the numbers it operated on were independently
# validated against the sheet's quoted text (``TEXT_EXTRACTED`` — trusted, may
# earn the DETERMINISTIC verdict + the deterministic-only ink gate) or only
# transcribed by the model (``MODEL_TRANSCRIBED`` — the mismatch stays UNCERTAIN
# and must be crop-verified, since a misread term can't be trusted).
HOST_DETERMINISTIC = "HOST_DETERMINISTIC"
TEXT_EXTRACTED = "TEXT_EXTRACTED"
MODEL_TRANSCRIBED = "MODEL_TRANSCRIBED"
COMPUTATION_METHODS = frozenset({"", HOST_DETERMINISTIC})
OPERAND_ORIGINS = frozenset({"", TEXT_EXTRACTED, MODEL_TRANSCRIBED})
# ``NumericClaim.kind`` — how a claim's terms combine into its expected value.
# ``sum`` → terms add up; ``product``/``factor`` → terms multiply (a "factor" is a
# product where one term is a multiplier, e.g. base-area × 1.3). The host does the
# arithmetic; the model only transcribes the numbers (Phase 14).
CLAIM_KINDS = frozenset({"sum", "product", "factor"})
# ``Finding.sources`` — the provenance tags a ledger entry may carry (Part III,
# §16). Every QC channel stamps its entries; the ledger unions tags on merge.
SOURCE_TAGS = frozenset({
    "digest_json",
    "digest_prose_coordination",
    "digest_prose_conflict",
    "critique_1",
    "critique_2",
    "cross_qc",
    "synthesis_prose",
    "auditor_reference",
    "auditor_arithmetic",
    "auditor_naming",
    "auditor_titleblock",
    "auditor_sheet_index",
    "focus_prose",
})

# ``Finding.confidence`` — the self-consistency verdict for a critique finding
# (Phase 22 §14.4). ``reproduced`` (a bool) is kept as a derived compatibility
# property; ``confidence`` is the richer signal the report surfaces:
#   REPRODUCED           — two independent successful reads both raised it.
#   SINGLETON            — two successful reads; only one raised it.
#   NOT_ASSESSED_PARTIAL — a second read was requested but failed, so corroboration
#                          could not be assessed (never silently "reproduced").
#   NOT_APPLICABLE       — self-consistency did not apply (single-read mode, or a
#                          non-critique channel: digest / auditors / prose).
CONFIDENCE_REPRODUCED = "REPRODUCED"
CONFIDENCE_SINGLETON = "SINGLETON"
CONFIDENCE_NOT_ASSESSED_PARTIAL = "NOT_ASSESSED_PARTIAL"
CONFIDENCE_NOT_APPLICABLE = "NOT_APPLICABLE"
CONFIDENCE_LEVELS = frozenset({
    CONFIDENCE_REPRODUCED,
    CONFIDENCE_SINGLETON,
    CONFIDENCE_NOT_ASSESSED_PARTIAL,
    CONFIDENCE_NOT_APPLICABLE,
})

# Structured-block parser status (Phase 22 §14.2). The line-aware scanner in
# ``digest.py`` classifies the model's findings attempt so a digest never leaks a
# truncated/unclosed machine block into the sacred prose (DA-009), and the
# critique can tell a genuine ``{"findings": []}`` from a parse failure (DA-008).
#   ABSENT            — no findings attempt (plain prose; prose returned verbatim).
#   PARSED_CLOSED     — a closed fenced block whose ``{"findings": …}`` parsed.
#   PARSED_UNCLOSED   — an unclosed (truncated) fence whose JSON was nonetheless
#                       complete and valid; findings extracted, drift recorded.
#   MALFORMED_CLOSED  — a closed findings attempt whose body would not parse.
#   MALFORMED_UNCLOSED— an unclosed findings attempt whose body would not parse.
#   TRUNCATED         — a findings attempt cut off immediately after the opener or
#                       mid-JSON (no recoverable object).
# ``PARSED_*`` are the only success states; every other state yields no findings.
# In every non-ABSENT state the prose is cut at the opener, so the machine block
# can never reach ``combined_text`` regardless of how the response ended.
FINDINGS_ABSENT = "ABSENT"
FINDINGS_PARSED_CLOSED = "PARSED_CLOSED"
FINDINGS_PARSED_UNCLOSED = "PARSED_UNCLOSED"
FINDINGS_MALFORMED_CLOSED = "MALFORMED_CLOSED"
FINDINGS_MALFORMED_UNCLOSED = "MALFORMED_UNCLOSED"
FINDINGS_TRUNCATED = "TRUNCATED"
FINDINGS_PARSE_STATUSES = frozenset({
    FINDINGS_ABSENT,
    FINDINGS_PARSED_CLOSED,
    FINDINGS_PARSED_UNCLOSED,
    FINDINGS_MALFORMED_CLOSED,
    FINDINGS_MALFORMED_UNCLOSED,
    FINDINGS_TRUNCATED,
})
# The parse states that carry a valid findings schema (an explicit empty list is
# a valid schema). A critique read is a success only in one of these states.
FINDINGS_PARSE_OK = frozenset({FINDINGS_PARSED_CLOSED, FINDINGS_PARSED_UNCLOSED})


def compute_finding_id(
    sheet_id: str, category: str, quote_or_text: str, source_id: str = ""
) -> str:
    """Stable short id for a finding: ``sha1(sheet_id + category + quote/text)``.

    Deterministic and content-derived so the *same* finding gets the *same* id
    across runs (and so two harvests of one issue collapse to one id, which the
    later dedup/ledger stages rely on). ``quote_or_text`` should be the verbatim
    ``source_quote`` when present, else the finding ``text``.

    ``source_id`` — when the host has assigned one (DA-001), it is folded into
    the hash so two *different* inputs that happen to share a sheet id, category,
    and quote can never collide on one artifact/evidence id. It is appended (not
    interleaved) and only when non-empty, so a legacy/single-source finding with
    no ``source_id`` keeps its historical id exactly.
    """
    h = hashlib.sha1()
    h.update(sheet_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(category.encode("utf-8"))
    h.update(b"\x00")
    h.update(quote_or_text.encode("utf-8"))
    if source_id:
        h.update(b"\x00")
        h.update(source_id.encode("utf-8"))
    return h.hexdigest()[:12]


@dataclass
class Anchor:
    """Where a finding sits on its page (filled by the anchor resolver).

    ``rect_pdf`` is ``[x0, y0, x1, y1]`` in the canonical **PAGE_VIEW_V2** space
    (:data:`COORDINATE_SPACE_VERSION`) — top-left origin, post-CropBox,
    post-rotation, matching the overview + tile grid the model saw. The anchor
    resolver builds it from PAGE_VIEW_V2 word rects; the verifier clips it
    directly (``get_pixmap`` wants view space); the markup writer transforms it to
    page space via :attr:`PageGeometry.view_to_page` before drawing. ``None``
    until/unless the finding is anchored.
    """

    status: str = "UNANCHORED"          # one of ANCHOR_STATUSES
    rect_pdf: list[float] | None = None
    method: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "rect_pdf": list(self.rect_pdf) if self.rect_pdf is not None else None,
            "method": self.method,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Anchor":
        rect = d.get("rect_pdf")
        return cls(
            status=d.get("status", "UNANCHORED"),
            rect_pdf=[float(v) for v in rect] if rect else None,
            method=d.get("method", ""),
        )


@dataclass
class EvidenceArtifact:
    """One crop the verifier actually saw, preserved byte-for-byte (Phase 24 §6.6).

    The evidence trail must contain *every* crop sent to a verify call, in send
    order, exactly as sent (DA-016): the pass renders a crop once, saves those
    bytes, hashes those bytes, and sends those same bytes — so ``sha256`` is the
    hash of the file on disk *and* of the image the model judged. ``leg_index`` is
    ``0`` for a single-crop finding / a conflict's primary and ``1..`` for each
    ``also_on`` leg; ``request_order`` is the crop's position in the request.
    ``relative_path`` is run-relative (e.g. ``evidence/QC-041/leg-01__M-101_p1.png``)
    so the manifest/report stay portable — no absolute path.
    """

    evidence_id: str = ""
    qc_id: str = ""
    leg_index: int = 0
    source_id: str = ""
    source_name: str = ""
    page_index: int = 0
    canonical_anchor_rect: list[float] | None = None
    crop_rect: list[float] | None = None
    dpi: int = 0
    request_order: int = 0
    relative_path: str = ""
    sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "qc_id": self.qc_id,
            "leg_index": self.leg_index,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "page_index": self.page_index,
            "canonical_anchor_rect": list(self.canonical_anchor_rect)
            if self.canonical_anchor_rect is not None else None,
            "crop_rect": list(self.crop_rect) if self.crop_rect is not None else None,
            "dpi": self.dpi,
            "request_order": self.request_order,
            "relative_path": self.relative_path,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvidenceArtifact":
        car = d.get("canonical_anchor_rect")
        cr = d.get("crop_rect")
        return cls(
            evidence_id=str(d.get("evidence_id", "") or ""),
            qc_id=str(d.get("qc_id", "") or ""),
            leg_index=int(d.get("leg_index", 0) or 0),
            source_id=str(d.get("source_id", "") or ""),
            source_name=str(d.get("source_name", "") or ""),
            page_index=int(d.get("page_index", 0) or 0),
            canonical_anchor_rect=[float(v) for v in car] if car else None,
            crop_rect=[float(v) for v in cr] if cr else None,
            dpi=int(d.get("dpi", 0) or 0),
            request_order=int(d.get("request_order", 0) or 0),
            relative_path=str(d.get("relative_path", "") or ""),
            sha256=str(d.get("sha256", "") or ""),
        )


@dataclass
class Verification:
    """The verification verdict for a finding (filled by the verify pass).

    ``DETERMINISTIC`` marks a finding produced by an offline auditor that never
    hit the API (a reference/arithmetic/naming check); such findings are trusted
    without a model re-check. ``evidence`` is the full ordered list of
    :class:`EvidenceArtifact` crops the verifier saw — one for a single-crop
    finding, one per included leg for a cross-sheet conflict (DA-016).
    ``evidence_png`` is retained as a back-compat alias to the **first**
    artifact's run-relative path (§21.5 migration; new consumers read ``evidence``).
    """

    status: str = "SKIPPED"             # one of VERIFICATION_STATUSES
    note: str = ""
    evidence_png: str = ""
    evidence: list["EvidenceArtifact"] = field(default_factory=list)
    # Arithmetic provenance (Phase 25 §17.5) — empty for non-arithmetic findings.
    computation_method: str = ""        # "" | HOST_DETERMINISTIC
    operand_origin: str = ""            # "" | TEXT_EXTRACTED | MODEL_TRANSCRIBED

    def __post_init__(self) -> None:
        # Keep the legacy scalar alias in sync with the artifact list: it always
        # points at the first saved crop, so existing popup/report/CSV consumers
        # that read ``evidence_png`` keep working unchanged.
        if self.evidence and not self.evidence_png:
            self.evidence_png = self.evidence[0].relative_path

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "note": self.note,
            "evidence_png": self.evidence_png,
            "evidence": [a.to_dict() for a in self.evidence],
            "computation_method": self.computation_method,
            "operand_origin": self.operand_origin,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Verification":
        evidence = [
            EvidenceArtifact.from_dict(a)
            for a in (d.get("evidence") or [])
            if isinstance(a, dict)
        ]
        return cls(
            status=d.get("status", "SKIPPED"),
            note=d.get("note", ""),
            evidence_png=d.get("evidence_png", ""),
            evidence=evidence,
            computation_method=str(d.get("computation_method", "") or ""),
            operand_origin=str(d.get("operand_origin", "") or ""),
        )


@dataclass
class ConflictLeg:
    """One *additional* sheet a cross-sheet finding touches (Phase 13).

    A cross-sheet conflict's primary anchor sits on one sheet; each
    ``ConflictLeg`` is the same issue's counterpart on another sheet — the tag
    that differs, the note it contradicts. ``sheet_id`` is model-reported;
    ``source_name`` / ``page_index`` are resolved from the set's sheet-id map so
    the leg can be anchored and clouded on its own sheet. ``source_quote`` /
    ``tile`` / ``anchor`` mirror a finding's, so the anchor resolver places a leg
    exactly as it places a finding.
    """

    sheet_id: str
    source_name: str = ""
    page_index: int = 0
    source_quote: str = ""
    tile: list[int] | None = None
    anchor: Anchor = field(default_factory=Anchor)
    source_id: str = ""       # host-owned identity of the leg's sheet (DA-001)

    def to_dict(self) -> dict:
        return {
            "sheet_id": self.sheet_id,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "page_index": self.page_index,
            "source_quote": self.source_quote,
            "tile": list(self.tile) if self.tile is not None else None,
            "anchor": self.anchor.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConflictLeg":
        tile = d.get("tile")
        return cls(
            sheet_id=d.get("sheet_id", ""),
            source_name=d.get("source_name", ""),
            page_index=int(d.get("page_index", 0) or 0),
            source_quote=d.get("source_quote", ""),
            tile=[int(v) for v in tile] if tile else None,
            anchor=Anchor.from_dict(d.get("anchor") or {}),
            source_id=str(d.get("source_id", "") or ""),
        )

    @property
    def tile_label(self) -> str:
        """The human 1-based tile label (``"r1c1"``) for this leg's zero-based tile."""
        if not self.tile or len(self.tile) != 2:
            return ""
        return f"r{int(self.tile[0]) + 1}c{int(self.tile[1]) + 1}"


@dataclass
class Citation:
    """The outcome of the web-search citation check for a finding's refs (Phase 15).

    ``CHECKED_SUPPORTS`` — the cited section(s), in the edition the set adopts and
    in the current edition, support the finding. ``CHECKED_MISMATCH`` — the check
    found a discrepancy (a stale section number, a renumbered edition, a section
    that says something else). A MISMATCH downgrades nothing automatically — it is
    surfaced for the engineer; sometimes the stale citation *is* the finding.
    ``UNCHECKED`` — the check didn't run or couldn't reach a verdict.
    """

    status: str = "UNCHECKED"           # CHECKED_SUPPORTS | CHECKED_MISMATCH | UNCHECKED
    note: str = ""
    edition_notes: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "note": self.note,
            "edition_notes": self.edition_notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Citation":
        return cls(
            status=d.get("status", "UNCHECKED") or "UNCHECKED",
            note=d.get("note", "") or "",
            edition_notes=d.get("edition_notes", "") or "",
        )


# Per-claim citation verdict statuses. ``UNRESOLVABLE`` marks a reference the
# checker could not evaluate at all; ``UNCHECKED`` a claim whose request/parser
# failed. Both make the citation stage PARTIAL but never downgrade the finding.
CITATION_ASSESSMENT_STATUSES = (
    "CHECKED_SUPPORTS", "CHECKED_MISMATCH", "UNCHECKED", "UNRESOLVABLE",
)


@dataclass
class CitationAssessment:
    """One reference's verdict for the exact claim(s) it was checked against (§6.5).

    DA-017: a citation verdict may attach to a finding ONLY if that finding's claim
    was included in the request that produced it. ``claim_finding_ids`` is the set
    of findings whose claim (their ``text``) was sent in ``request_id``; the verdict
    therefore covers those findings and no others. A finding with several references
    keeps one assessment *per reference* rather than collapsing them into one
    ambiguous status. ``adopted_edition`` is the set's stated basis (harvested
    offline); ``edition_notes`` carries the model's free-text renumbering finding;
    ``current_edition`` is a reserved structured field (populated only when a
    caller can supply it — the web-search verdict reports its finding in
    ``edition_notes``); ``sources`` are the web-search citations backing the verdict.
    """

    reference: str
    status: str = "UNCHECKED"           # one of CITATION_ASSESSMENT_STATUSES
    claim_finding_ids: list[str] = field(default_factory=list)
    note: str = ""
    edition_notes: str = ""
    adopted_edition: str = ""
    current_edition: str = ""
    sources: list[str] = field(default_factory=list)
    request_id: str = ""

    def to_dict(self) -> dict:
        return {
            "reference": self.reference,
            "status": self.status,
            "claim_finding_ids": list(self.claim_finding_ids),
            "note": self.note,
            "edition_notes": self.edition_notes,
            "adopted_edition": self.adopted_edition,
            "current_edition": self.current_edition,
            "sources": list(self.sources),
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CitationAssessment":
        return cls(
            reference=str(d.get("reference", "") or ""),
            status=str(d.get("status", "UNCHECKED") or "UNCHECKED"),
            claim_finding_ids=[str(x) for x in (d.get("claim_finding_ids") or [])],
            note=str(d.get("note", "") or ""),
            edition_notes=str(d.get("edition_notes", "") or ""),
            adopted_edition=str(d.get("adopted_edition", "") or ""),
            current_edition=str(d.get("current_edition", "") or ""),
            sources=[str(x) for x in (d.get("sources") or [])],
            request_id=str(d.get("request_id", "") or ""),
        )


@dataclass
class Finding:
    """One QC finding: a single reviewable issue anchored to a sheet.

    See §4.1 of the QC plan for the full contract. ``source_quote`` is a string
    copied **verbatim** from the sheet's text layer (required when the sheet has
    a text layer; ``""`` only for a purely graphical finding). ``tile`` is the
    ``[row, col]`` grid position the model reported (``None`` for offline /
    deterministic findings, which carry exact anchors instead). ``id`` is derived
    from the content when not supplied, so callers normally omit it.

    ``anchor_hint`` is an optional coarse placement hint from the model — ``"SHEET"``
    for a sheet-level / *absence* finding (something the reviewer expected but did
    not find), which has no ``source_quote`` to anchor and is placed against the
    whole sheet rather than a rectangle; ``"SET_INDEX"`` for a **set-level** finding
    (a cross-sheet synthesis conflict that names no resolvable in-set sheet, Phase 22
    §14.8) which — together with an empty ``source_id`` — belongs to no single source
    and is written to the deterministic ``Drawing_Set_Review_Notes.pdf`` artifact.
    ``reproduced`` is a soft confidence signal: ``True`` unless a self-consistency
    pass saw the finding in only one of several independent reads (an uncorroborated
    singleton). It never suppresses a finding — the report and the markup writer only
    *surface* it — so it defaults ``True`` for every finding that never went through
    that pass (digest findings, the deterministic auditors). ``confidence`` is the
    richer Phase-22 form of the same signal (one of :data:`CONFIDENCE_LEVELS`);
    ``reproduced`` is derived from it (``REPRODUCED`` ⇒ ``True``, everything else the
    read's own outcome). ``prose_item_ids`` records every enumerated prose item this
    entry accounts for (Phase 22 §14.6), so the harvest can prove — item by item —
    that nothing was dropped.

    ``qc_id`` is the human-facing sequential review number (``QC-001`` …), assigned
    once per run by :func:`assign_qc_ids` (ordered sheet → position) and shown on
    the markup tag, the index page, the CSV, and the report. ``citation`` is the
    optional web-search citation-check verdict for the finding's ``refs``.

    ``sources`` is the finding's **provenance** (Part III): every channel that
    produced or corroborated it, from :data:`SOURCE_TAGS`. The ledger unions
    sources when it merges duplicate findings, so multi-source provenance doubles
    as a confidence signal (report/popup chips like ``prose+json+critique×2``).
    """

    sheet_id: str
    source_name: str
    page_index: int
    category: str                       # one of FINDING_CATEGORIES
    severity: str                       # one of FINDING_SEVERITIES
    text: str
    source_id: str = ""                 # host-owned identity of the source (DA-001)
    source_quote: str = ""
    tile: list[int] | None = None
    refs: list[str] = field(default_factory=list)
    anchor_hint: str = ""               # "SHEET"/"SET_INDEX" placement hint
    reproduced: bool = True             # corroborated by a second read (self-consistency)
    confidence: str = ""                # one of CONFIDENCE_LEVELS ("" = not set → NOT_APPLICABLE)
    also_on: list["ConflictLeg"] = field(default_factory=list)  # cross-sheet legs (Phase 13)
    anchor: Anchor = field(default_factory=Anchor)
    verification: Verification = field(default_factory=Verification)
    qc_id: str = ""                     # "QC-001" … (assigned by assign_qc_ids)
    citation: Citation | None = None    # web-search citation check (Phase 15)
    # Per-reference, claim-complete citation assessments (Phase 24 §16.5, DA-017).
    # Each entry is one reference's verdict for the exact claim it was checked
    # against; ``citation`` above is the derived back-compat summary over these.
    citations: list["CitationAssessment"] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # provenance tags (Part III)
    # Verbatim quotes from *other* members merged into this entry (Phase 20 §12.2).
    # The grounded fields (``text`` / ``category`` / ``source_quote`` / ``tile`` /
    # ``anchor``) always come from ONE representative as an atomic bundle — a
    # duplicate's alternate quote is preserved here, never spliced onto this entry's
    # text (which would fabricate a text/quote pair that never appeared together).
    supporting_quotes: list[str] = field(default_factory=list)
    # Enumerated prose items (Phase 22 §14.6) this entry accounts for. A harvested
    # prose sentence attaches its ``prose_item_id`` here; the ledger unions these on
    # merge so the harvest's expected-vs-accounted reconciliation can prove every
    # item survived. Empty for non-prose findings.
    prose_item_ids: list[str] = field(default_factory=list)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = compute_finding_id(
                self.sheet_id, self.category, self.source_quote or self.text,
                self.source_id,
            )

    @property
    def tile_label(self) -> str:
        """The human 1-based tile label (``"r1c1"``) for the zero-based ``tile``.

        Derived, not stored — the internal ``tile`` stays the canonical zero-based
        ``[row, col]``; this is the model-facing / export-facing label (Phase 25
        §17.1). ``""`` when the finding has no tile.
        """
        if not self.tile or len(self.tile) != 2:
            return ""
        return f"r{int(self.tile[0]) + 1}c{int(self.tile[1]) + 1}"

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "qc_id": self.qc_id,
            "sheet_id": self.sheet_id,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "page_index": self.page_index,
            "category": self.category,
            "severity": self.severity,
            "text": self.text,
            "source_quote": self.source_quote,
            "tile": list(self.tile) if self.tile is not None else None,
            "refs": list(self.refs),
            "anchor_hint": self.anchor_hint,
            "reproduced": self.reproduced,
            "confidence": self.confidence,
            "also_on": [leg.to_dict() for leg in self.also_on],
            "sources": list(self.sources),
            "supporting_quotes": list(self.supporting_quotes),
            "prose_item_ids": list(self.prose_item_ids),
            "anchor": self.anchor.to_dict(),
            "verification": self.verification.to_dict(),
            "citations": [a.to_dict() for a in self.citations],
        }
        if self.citation is not None:
            out["citation"] = self.citation.to_dict()
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        """Reconstruct a Finding from its :meth:`to_dict` form (cache round-trip).

        Preserves the stored ``id`` verbatim rather than recomputing it, so a
        finding served from cache is byte-identical to the one first produced.
        """
        tile = d.get("tile")
        return cls(
            sheet_id=d.get("sheet_id", ""),
            source_name=d.get("source_name", ""),
            source_id=str(d.get("source_id", "") or ""),
            page_index=int(d.get("page_index", 0) or 0),
            category=d.get("category", ""),
            severity=d.get("severity", ""),
            text=d.get("text", ""),
            source_quote=d.get("source_quote", ""),
            tile=[int(v) for v in tile] if tile else None,
            refs=list(d.get("refs", []) or []),
            anchor_hint=d.get("anchor_hint", "") or "",
            reproduced=bool(d.get("reproduced", True)),
            confidence=str(d.get("confidence", "") or ""),
            also_on=[ConflictLeg.from_dict(leg) for leg in (d.get("also_on") or []) if isinstance(leg, dict)],
            sources=[str(s) for s in (d.get("sources") or [])],
            supporting_quotes=[str(q) for q in (d.get("supporting_quotes") or [])],
            prose_item_ids=[str(p) for p in (d.get("prose_item_ids") or [])],
            anchor=Anchor.from_dict(d.get("anchor") or {}),
            verification=Verification.from_dict(d.get("verification") or {}),
            qc_id=d.get("qc_id", "") or "",
            citation=Citation.from_dict(d["citation"]) if isinstance(d.get("citation"), dict) else None,
            citations=[
                CitationAssessment.from_dict(a)
                for a in (d.get("citations") or [])
                if isinstance(a, dict)
            ],
            id=d.get("id", ""),
        )


def compute_prose_item_id(
    channel: str,
    source_id: str | None,
    section: str,
    ordinal: int,
    verbatim_text: str,
    page_index: int = 0,
) -> str:
    """Stable identity for one enumerated prose item (Phase 22 §14.6).

    Derived from the channel, the emitting source identity (``""`` for a set-level
    item), the **page index** within that source, the prose section, the item's
    ordinal within that section, and its verbatim text — so the same sentence gets
    the same id across runs, two identical sentences at *different* ordinals or on
    *different pages of one multi-page source* stay distinct, and the harvest can
    prove — id by id — that every enumerated item reached a ledger entry.

    ``page_index`` matters because a source id identifies the input file, not the
    page: without it, an identical boilerplate note (e.g. a general coordination
    note repeated on every sheet) on two pages of one PDF — both enumerated at the
    same per-page ordinal — would collide to one id and defeat the §14.9 id-based
    reconciliation (a distinct item could be silently dropped).
    """
    payload = "\x00".join([
        channel or "",
        source_id or "",
        str(int(page_index)),
        section or "",
        str(int(ordinal)),
        verbatim_text or "",
    ])
    return "PI-" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class ProseItem:
    """One enumerated prose QC item (a Coordination/Conflict/synthesis/Focus line).

    The prose-harvest carry-through guarantee (§14.6/§14.9) works over these
    records: every candidate sentence becomes a ``ProseItem`` with a stable
    :func:`compute_prose_item_id` *before* processing, so the harvest can reconcile
    the set of enumerated ids against the set actually attached to ledger entries
    and degrade — never silently drop — any straggler.

    ``scope`` is ``SOURCE`` for an item that names a resolvable in-set sheet and
    ``SET`` for a synthesis conflict that names none (it lives in the set-level
    review-notes artifact, not on an arbitrary sheet). ``source_id`` is the emitting
    source for a SOURCE item and ``None`` for a SET item.
    """

    prose_item_id: str
    channel: str                       # a prose SOURCE_TAG (digest_prose_* / synthesis_prose / focus_prose)
    scope: str                         # "SOURCE" | "SET"
    source_id: str | None
    section: str
    ordinal: int
    verbatim_text: str
    mentioned_sheet_ids: list[str] = field(default_factory=list)


def assign_qc_ids(findings: list["Finding"]) -> list["Finding"]:
    """Assign sequential review numbers (``QC-001`` …) across a run's findings.

    Ordered **sheet then position** (Phase 15): source file, page, then the
    anchor rectangle's top-left in reading order (top-to-bottom, left-to-right).
    Findings with no rectangle (sheet-level / unanchored) sort after the anchored
    ones on their sheet. **Set-level** findings (a synthesis conflict belonging to no
    source sheet, §12.4/§14.8) sort after *every* source-scoped finding, in a final
    section of their own. The sort is deterministic — tie-broken by the stable
    content ``id`` — so the same findings get the same numbers regardless of the
    order they arrive in (I-7). Assigns in place and returns the same list; ids
    are assigned exactly once per run (numbering everything, not only the inked
    findings, so the CSV/report/index all share one namespace).
    """

    def _is_set_level(f: "Finding") -> bool:
        return (f.anchor_hint or "").upper() in {"SET", "SET_INDEX"} and not f.source_id

    def _pos(f: "Finding") -> tuple:
        rect = f.anchor.rect_pdf if f.anchor is not None else None
        if rect:
            return (0, float(rect[1]), float(rect[0]))
        return (1, 0.0, 0.0)            # rect-less findings sort after anchored ones

    ordered = sorted(
        findings,
        # Set-level findings sort last (a separate final section); within each group
        # the usual source → page → position → id order holds.
        key=lambda f: (1 if _is_set_level(f) else 0, source_page_key(f), _pos(f), f.id),
    )
    width = max(3, len(str(len(ordered))))
    for n, finding in enumerate(ordered, start=1):
        finding.qc_id = f"QC-{n:0{width}d}"
    return findings


# --------------------------------------------------------------------------- #
# Markup coverage receipts (Phase 21, DA-007) — the artifact-backed accounting
# that supersedes the old intention classifier (``ink_disposition``). Plain data
# (no PyMuPDF import here — the writer in :mod:`annotate` produces these): the
# writer plans one placement per finding/leg, draws stamped components, reopens
# the saved PDF, and reconciles the plan against what it actually finds, emitting
# one terminal receipt per placement. The pipeline rolls the receipts into the
# run's coverage status; :mod:`export` serializes them into
# ``markup_manifest.json``. Nothing is ever counted from intention — a tally
# entry exists only because a mark was found again in the saved file.
# --------------------------------------------------------------------------- #

# What a planned placement is expected to become in the saved artifact.
PLACEMENT_KINDS = ("CLOUD", "MARGIN", "REVIEW_NOTES", "REJECTED_INDEX", "GATED_INDEX")
# The terminal outcome of one placement, read back from the saved artifact.
RECEIPT_STATUSES = ("WRITTEN", "INDEXED", "FAILED")
# A whole run's placement coverage over the ledger.
COVERAGE_STATUSES = ("NOT_REQUESTED", "COMPLETE", "INCOMPLETE")


def receipt_status_counts(receipts: Any) -> "dict[str, int]":
    """Tally terminal receipts by status, keyed by :data:`RECEIPT_STATUSES`.

    The one shared counter behind the journal's MARKUP_RECEIPTS event, the
    run.log placements line, and ``run_manifest.json``'s coverage block
    (Phase 26A) — so a status added to :data:`RECEIPT_STATUSES` reaches all
    three consumers at once instead of drifting across hand-kept copies.
    Duck-typed and tolerant: an unknown/malformed status is simply not
    counted (the coverage reconciliation, not this tally, polices validity).
    """
    counts = {status: 0 for status in RECEIPT_STATUSES}
    for receipt in receipts or []:
        status = str(getattr(receipt, "status", "") or "")
        if status in counts:
            counts[status] += 1
    return counts

# The mandatory component kind(s) each placement must carry, exactly once, in the
# saved PDF. A placement may also carry optional components (a QC tag beside a
# cloud, a leader line from a callout); those are recorded but never gate
# coverage — the plan's "reject missing or duplicate components" rule applies to
# the mandatory kinds only.
REQUIRED_COMPONENTS = {
    "CLOUD": ("cloud",),
    "MARGIN": ("callout",),
    "REVIEW_NOTES": ("callout",),
    "REJECTED_INDEX": ("index_row",),
    "GATED_INDEX": ("index_row",),
}
# Component kinds that are real annotation objects (i.e. "ink"); ``index_row`` is
# a stamped GOTO link on a generated index page — visible navigation, not ink.
ANNOTATION_COMPONENTS = frozenset({"cloud", "tag", "callout", "leader"})

PRIMARY_LEG_ID = "primary"
SET_LEG_ID = "set_level"


def leg_identity(
    source_id: str, source_name: str, page_index: int, source_quote: str, index: int
) -> str:
    """A stable id for one cross-sheet leg's placement within an artifact run.

    Distinguishes each ``also_on`` leg of a conflict from the primary and from
    its siblings so their placements never collide — the leg ``index`` guarantees
    uniqueness even when two legs share a sheet id and quote, while the content
    hash keeps it recognizable. :data:`PRIMARY_LEG_ID` is reserved for a
    finding's own anchor and :data:`SET_LEG_ID` for a set-scoped finding.
    """
    h = hashlib.sha1()
    for part in (source_id, source_name, str(int(page_index)), source_quote):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return f"leg-{index:02d}-{h.hexdigest()[:8]}"


@dataclass
class MarkupPlacement:
    """One logical mark the run intends to write for a finding or a leg (§6.4).

    ``placement_id`` is the machine key — ``"{run_id}#{finding_id}#{leg_id}"`` —
    unique within one artifact run and **embedding the run id** so a prior run's
    stamped annotations (a re-review of the same source PDF) never satisfy this
    run's plan. ``qc_id`` is a display aid, never the key (§13.1). ``leg_id`` is
    :data:`PRIMARY_LEG_ID` for the finding's own anchor, a :func:`leg_identity`
    value for a cross-sheet leg, or :data:`SET_LEG_ID` for a set-scoped finding.
    ``page_index`` is the *source* page (``-1`` for a set-level placement).
    """

    run_id: str
    placement_id: str
    finding_id: str
    qc_id: str
    scope: str                          # SOURCE | SET
    source_id: str                      # "" for set-level
    page_index: int                     # source page (-1 for set-level)
    leg_id: str                         # primary | leg-.. | set_level
    expected: str                       # one of PLACEMENT_KINDS
    required_components: list[str] = field(default_factory=list)
    severity: str = ""
    source_name: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "placement_id": self.placement_id,
            "finding_id": self.finding_id,
            "qc_id": self.qc_id,
            "scope": self.scope,
            "source_id": self.source_id,
            "page_index": self.page_index,
            "leg_id": self.leg_id,
            "expected": self.expected,
            "required_components": list(self.required_components),
            "severity": self.severity,
            "source_name": self.source_name,
        }


@dataclass
class MarkupReceipt:
    """The proven outcome of one placement, read back from the saved artifact (§6.4).

    ``WRITTEN`` (ink) / ``INDEXED`` (a generated index/review-notes row) are the
    two success states; ``FAILED`` carries a sanitized ``error``. ``output_pdf``
    is a **basename only** (no absolute path — the manifest is portable).
    ``annotation_refs`` list the concrete components found again in the reopened
    file as ``"{component}:{xref}"``; ``index_entry_ref`` names the index row's
    marker when the placement is index-backed.
    """

    placement: MarkupPlacement
    status: str                          # WRITTEN | INDEXED | FAILED
    output_pdf: str = ""
    output_page_index: int | None = None
    annotation_refs: list[str] = field(default_factory=list)
    index_entry_ref: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("WRITTEN", "INDEXED")

    def to_dict(self) -> dict:
        return {
            "placement": self.placement.to_dict(),
            "status": self.status,
            "output_pdf": self.output_pdf,
            "output_page_index": self.output_page_index,
            "annotation_refs": list(self.annotation_refs),
            "index_entry_ref": self.index_entry_ref,
            "error": self.error,
        }


@dataclass
class MarkupRunResult:
    """The whole markup run's artifact-backed accounting (§6.4).

    ``reviewed_pdfs`` are the written files (incomplete ones carry an explicit
    ``_INCOMPLETE`` name). ``coverage_status`` is derived from the receipts, never
    from intention: ``COMPLETE`` only when every expected placement — including
    every cross-sheet leg — has a successful receipt with its unique mandatory
    components and there are no missing / unexpected / duplicate / failed
    receipts. ``tally`` is the receipt-derived run summary.
    """

    reviewed_pdfs: list[Path] = field(default_factory=list)
    placements: list[MarkupPlacement] = field(default_factory=list)
    receipts: list[MarkupReceipt] = field(default_factory=list)
    coverage_status: str = "NOT_REQUESTED"
    tally: dict = field(default_factory=dict)

    @property
    def annots_written(self) -> int:
        """Total annotation objects (ink) proven in the saved files.

        Derived from the reconciled receipts — the artifact-backed replacement
        for the old ``annotate_pdf`` integer return. Index-row (GOTO link)
        components are navigation, not ink, so they are excluded.
        """
        return sum(
            1
            for r in self.receipts
            if r.ok
            for ref in r.annotation_refs
            if ref.split(":", 1)[0] in ANNOTATION_COMPONENTS
        )

    @property
    def failed_receipts(self) -> list["MarkupReceipt"]:
        return [r for r in self.receipts if r.status == "FAILED"]

    def to_dict(self) -> dict:
        return {
            "coverage_status": self.coverage_status,
            "tally": dict(self.tally),
            "reviewed_pdfs": [Path(p).name for p in self.reviewed_pdfs],
            "placements": [p.to_dict() for p in self.placements],
            "receipts": [r.to_dict() for r in self.receipts],
        }


@dataclass
class NumericClaim:
    """A numeric relationship the model *transcribed* off a sheet (Phase 14).

    The reviewer (critique / cross-sheet QC) does not do arithmetic — it only
    reports the numbers it read and how they are supposed to relate: "these terms
    should ``sum``/``product``/``factor`` to this expected value". The deterministic
    arithmetic auditor then *computes* the relationship itself (no ``eval``, no
    trust in the model's math) and raises a finding only when the numbers don't
    add up. This keeps the one class of error a vision model is worst at — mental
    arithmetic on a table it just read — out of the trusted path.

    ``terms`` / ``expected`` are kept **raw** (JSON numbers, or strings that may
    carry commas, units, or fractions like ``"2 1/2"``); the auditor parses them
    to exact decimals. ``quote`` is the verbatim on-sheet string the claim came
    from — the anchor hook, exactly like a :class:`Finding`'s ``source_quote``.
    ``source_name`` / ``page_index`` identify the emitting sheet when it is known
    (a per-sheet critique fills them in); otherwise the auditor resolves the
    claim's ``sheet_id`` against the set's sheet-id map.
    """

    sheet_id: str
    quote: str
    kind: str                           # one of CLAIM_KINDS
    terms: list[Any] = field(default_factory=list)
    expected: Any = None
    note: str = ""
    source_name: str = ""
    page_index: int = 0
    source_id: str = ""       # host-owned identity of the emitting sheet (DA-001)

    def to_dict(self) -> dict:
        return {
            "sheet_id": self.sheet_id,
            "quote": self.quote,
            "kind": self.kind,
            "terms": list(self.terms),
            "expected": self.expected,
            "note": self.note,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "page_index": self.page_index,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NumericClaim":
        terms = d.get("terms")
        return cls(
            sheet_id=str(d.get("sheet_id", "") or ""),
            quote=str(d.get("quote", "") or ""),
            kind=str(d.get("kind", "") or "").strip().lower(),
            terms=list(terms) if isinstance(terms, list) else [],
            expected=d.get("expected"),
            note=str(d.get("note", "") or ""),
            source_name=str(d.get("source_name", "") or ""),
            page_index=int(d.get("page_index", 0) or 0),
            source_id=str(d.get("source_id", "") or ""),
        )


# --------------------------------------------------------------------------- #
# Run configuration & QC status (Phase 23A — §15.1 / §15.4 / §3.3)
# --------------------------------------------------------------------------- #
#
# The GUI presents checkboxes, and the public API keeps its per-stage keyword
# arguments, but their *meaning* is resolved exactly once into a single immutable
# ``RunConfiguration`` so the same boolean combination can never drift across call
# sites (§15.1). Every stage consults the resolved object; the pipeline and GUI
# must not independently reconstruct the switch matrix. The status vocabulary is
# the one canonical set used throughout the code, manifests, GUI, and docs (§3.3).

# Overall roll-up over an exhaustive QC run.
QC_STATUSES = ("NOT_REQUESTED", "COMPLETE", "PARTIAL", "FAILED")
# Per-stage outcome. ``SKIPPED_VALID`` is an applicable-but-not-needed skip (e.g.
# synthesis with <2 sheets, citation with no cited claims) — never a failure.
STAGE_STATUSES = ("NOT_REQUESTED", "COMPLETE", "PARTIAL", "FAILED", "SKIPPED_VALID")
# ``DEBUG_OVERRIDE`` marks a run whose exhaustive configuration was deliberately
# weakened by an explicit expert flag (e.g. ``qc_markups=True, critique=False``).
CONFIGURATION_KINDS = ("NORMAL", "DEBUG_OVERRIDE")

# The exhaustive stages that ``qc_markups=True`` turns on by default and that an
# explicit ``False`` may override (recording a DEBUG_OVERRIDE). Anchoring, the
# deterministic auditors, prose harvest, markup, and coverage are structural to
# exhaustive QC and are not individually overridable here.
_OVERRIDABLE_EXHAUSTIVE_STAGES = (
    "synthesis", "critique", "cross_qc", "verification", "citation",
    "identity", "review_plan",
)


@dataclass
class StageResult:
    """One QC stage's normalized outcome (§15.4). Additive telemetry.

    Sits alongside the run's flat ``errors`` list (which stays the human-readable
    record every existing consumer reads); a :class:`StageResult` adds the typed
    per-stage accounting the overall :data:`QC_STATUSES` roll-up is computed from.
    ``expected`` records whether the resolved configuration asked for this stage —
    an unexpected stage that ran anyway, or an expected stage that did not, is
    exactly what the roll-up must notice. Usage records attach in Phase 23B.
    """

    stage: str
    expected: bool = False
    status: str = "NOT_REQUESTED"
    calls_planned: int = 0
    calls_succeeded: int = 0
    calls_failed: int = 0
    items_in: int = 0
    items_out: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "expected": self.expected,
            "status": self.status,
            "calls_planned": self.calls_planned,
            "calls_succeeded": self.calls_succeeded,
            "calls_failed": self.calls_failed,
            "items_in": self.items_in,
            "items_out": self.items_out,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class ProfileSnapshot:
    """An immutable record of a review profile as it was at Analyze time (§16.4).

    Captured once when the run starts so the run manifest and the report can show
    exactly which profile (name + version + content hash + source) was injected,
    and so a later edit / disappearance of the on-disk profile can be detected. No
    absolute path leaves here — ``source`` is ``"builtin"`` / ``"user"`` only.
    """

    name: str
    title: str = ""
    version: str = "0"
    content_hash: str = ""
    source: str = ""                    # "builtin" | "user" | "model" | ""
    disciplines: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "version": self.version,
            "content_hash": self.content_hash,
            "source": self.source,
            "disciplines": list(self.disciplines),
        }


@dataclass(frozen=True)
class AdoptedCode:
    """One code/standard the set adopts, as stated on the drawings (Phase A §20.1).

    ``quote`` is the verbatim evidence string lifted from a sheet's text layer —
    the containment contract: an adopted-code claim without a quote is a model
    assertion, one with a quote is checkable against the source. ``origin`` is
    ``"model"`` for entries the identity call extracted and ``"regex"`` for
    entries only the deterministic :func:`citation_check.harvest_code_editions`
    scan found (the regex backstop can never be hallucinated away).
    """

    code: str
    edition: str = ""
    amendment_note: str = ""
    quote: str = ""
    source_sheet: str = ""
    origin: str = "model"               # "model" | "regex"

    @property
    def display(self) -> str:
        """``"NFPA 13 2016"`` — the code + edition token citation prompts use."""
        return (self.code + " " + self.edition).strip()

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "edition": self.edition,
            "amendment_note": self.amendment_note,
            "quote": self.quote,
            "source_sheet": self.source_sheet,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AdoptedCode":
        data = data or {}
        return cls(
            code=str(data.get("code", "") or ""),
            edition=str(data.get("edition", "") or ""),
            amendment_note=str(data.get("amendment_note", "") or ""),
            quote=str(data.get("quote", "") or ""),
            source_sheet=str(data.get("source_sheet", "") or ""),
            origin=str(data.get("origin", "model") or "model"),
        )


@dataclass(frozen=True)
class SetIdentity:
    """What the drawing set *is* — the model-detected intake record (Phase A §20.1).

    Produced once per run by the identity stage from the digests + text layers:
    the disciplines present, where the project sits (jurisdiction / country /
    region), its language and units, and the codes the set says it adopts. It is
    **advisory context**: consumers (the review planner, citation check,
    cross-sheet QC) accept ``SetIdentity | None`` and behave exactly as before
    when it is ``None`` — a misdetection can steer emphasis but can never gate
    or suppress a finding. ``sheet_disciplines`` maps sheet id → discipline and
    is the future per-discipline delegation key.

    Deterministic assembly (I-7): every tuple is sorted at construction, so the
    same parsed payload always yields the same record regardless of the order
    the model emitted it in.
    """

    disciplines: tuple[str, ...] = ()
    sheet_disciplines: tuple[tuple[str, str], ...] = ()
    project_type: str = ""
    set_type: str = ""
    jurisdiction: str = ""
    country: str = ""
    region: str = ""
    language: str = ""
    units: str = ""
    adopted_codes: tuple["AdoptedCode", ...] = ()
    confidence: str = ""
    evidence: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        # Normalize to sorted tuples so assembly is order-independent (I-7).
        object.__setattr__(self, "disciplines", tuple(sorted(self.disciplines)))
        object.__setattr__(
            self, "sheet_disciplines", tuple(sorted(tuple(p) for p in self.sheet_disciplines))
        )
        object.__setattr__(
            self,
            "adopted_codes",
            tuple(sorted(self.adopted_codes, key=lambda c: (c.code, c.edition, c.origin))),
        )
        object.__setattr__(self, "evidence", tuple(self.evidence))

    @property
    def has_content(self) -> bool:
        """True when the identity carries at least one usable field."""
        return bool(
            self.disciplines or self.sheet_disciplines or self.project_type
            or self.set_type or self.jurisdiction or self.country or self.region
            or self.language or self.units or self.adopted_codes
        )

    def context_block(self) -> str:
        """The canonical multi-line ``SET IDENTITY`` context text.

        Consumed verbatim by the review planner's input, the cross-sheet QC
        preamble, and the ``combined_text`` section — one rendering, so every
        consumer sees the same facts. Empty fields are omitted.
        """
        lines = ["SET IDENTITY (model-detected):"]
        if self.disciplines:
            lines.append(f"- Disciplines: {', '.join(self.disciplines)}")
        project = self.project_type
        if self.set_type:
            project = f"{project} ({self.set_type})" if project else self.set_type
        if project:
            lines.append(f"- Project: {project}")
        where = self.jurisdiction or ", ".join(p for p in (self.region, self.country) if p)
        if where:
            lines.append(f"- Jurisdiction: {where}")
        locale_bits = []
        if self.language:
            locale_bits.append(f"language: {self.language}")
        if self.units:
            locale_bits.append(f"units: {self.units}")
        if locale_bits:
            lines.append(f"- {'; '.join(locale_bits)}")
        if self.adopted_codes:
            lines.append("- Adopted codes:")
            for c in self.adopted_codes:
                extra = f" ({c.amendment_note})" if c.amendment_note else ""
                src = f" [per {c.source_sheet}]" if c.source_sheet else ""
                lines.append(f"  - {c.display}{extra}{src}")
        if self.confidence:
            lines.append(f"- Detection confidence: {self.confidence}")
        if self.notes:
            lines.append(f"- Notes: {self.notes}")
        return "\n".join(lines)

    def citation_context_line(self) -> str:
        """One line of locale context for the citation-check prompt ("" if none)."""
        bits = []
        where = self.jurisdiction or ", ".join(p for p in (self.region, self.country) if p)
        if where:
            bits.append(where)
        if self.language:
            bits.append(f"language {self.language}")
        if self.units:
            bits.append(f"units {self.units}")
        return "; ".join(bits)

    def to_dict(self) -> dict:
        return {
            "disciplines": list(self.disciplines),
            "sheet_disciplines": [list(p) for p in self.sheet_disciplines],
            "project_type": self.project_type,
            "set_type": self.set_type,
            "jurisdiction": self.jurisdiction,
            "country": self.country,
            "region": self.region,
            "language": self.language,
            "units": self.units,
            "adopted_codes": [c.to_dict() for c in self.adopted_codes],
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SetIdentity":
        # Tolerant: every field defaults, unknown keys are ignored, so cached
        # payloads from older/newer runs still load (additive serialization).
        data = data or {}
        pairs = []
        for p in data.get("sheet_disciplines") or []:
            try:
                sheet, disc = p[0], p[1]
            except (TypeError, IndexError, KeyError):
                continue
            pairs.append((str(sheet), str(disc)))
        return cls(
            disciplines=tuple(str(d) for d in (data.get("disciplines") or [])),
            sheet_disciplines=tuple(pairs),
            project_type=str(data.get("project_type", "") or ""),
            set_type=str(data.get("set_type", "") or ""),
            jurisdiction=str(data.get("jurisdiction", "") or ""),
            country=str(data.get("country", "") or ""),
            region=str(data.get("region", "") or ""),
            language=str(data.get("language", "") or ""),
            units=str(data.get("units", "") or ""),
            adopted_codes=tuple(
                AdoptedCode.from_dict(c) for c in (data.get("adopted_codes") or [])
                if isinstance(c, dict)
            ),
            confidence=str(data.get("confidence", "") or ""),
            evidence=tuple(str(e) for e in (data.get("evidence") or [])),
            notes=str(data.get("notes", "") or ""),
        )


@dataclass(frozen=True)
class RunConfiguration:
    """One immutable, normalized description of what a run will do (§15.1).

    Resolved once by :func:`resolve_run_configuration` from the user/API options.
    The user-facing QC mode is binary — OFF or exhaustive — plus an additive,
    offline deterministic-diagnostics option; the per-stage switches below are the
    *resolved* consequence, read by the pipeline and never re-derived elsewhere.

    ``deterministic_audit_only`` is the free offline battery: it runs the
    deterministic auditors over already-extracted text/geometry and adds **zero**
    incremental API calls (DA-013) — in particular it never structures prose.
    ``exhaustive_qc`` is the full stack. ``standard_analysis`` is always true: even
    with no QC requested a run retains sheet text and parsed digest findings, binds
    them to source identity, and anchors them offline for free (DA-012).
    """

    standard_analysis: bool = True
    exhaustive_qc: bool = False
    deterministic_audit_only: bool = False
    # Resolved stage switches (the pipeline reads these, never the raw kwargs).
    run_synthesis: bool = False
    run_critique: bool = False
    critique_reads: int = 0
    run_cross_qc: bool = False
    run_auditors: bool = False
    run_prose_harvest: bool = False
    run_anchoring: bool = True          # free offline anchoring runs in every mode
    run_verification: bool = False
    run_citation: bool = False
    run_markup: bool = False
    run_coverage_check: bool = False
    # Phase A (universal reviewer): the set-identity harvest and the model-authored
    # review plan. Both ride the critique stack by default (§ locked decision 3) —
    # a standard digest-only run keeps them off so it stays zero-extra-cost.
    run_identity: bool = False
    run_review_plan: bool = False
    # Markup gating / transport, carried through verbatim (not product-derived).
    markup_verified_only: bool = False
    ink_rejected: bool = False
    focus_findings_to_markups: bool = False
    use_batch: bool = False
    # Names of normally-required exhaustive stages an explicit flag disabled. A
    # non-empty tuple makes this a DEBUG_OVERRIDE configuration (§3.3 / §15.1).
    debug_overrides: tuple[str, ...] = ()

    @property
    def configuration_kind(self) -> str:
        return "DEBUG_OVERRIDE" if self.debug_overrides else "NORMAL"

    @property
    def qc_requested(self) -> bool:
        """True only for exhaustive QC — the mode the roll-up scores (§3.1).

        The deterministic-audit-only checkbox is an additive offline diagnostic,
        not a second QC effort mode, so it does not by itself make ``qc_status``
        anything other than ``NOT_REQUESTED``.
        """
        return self.exhaustive_qc

    def to_dict(self) -> dict:
        return {
            "standard_analysis": self.standard_analysis,
            "exhaustive_qc": self.exhaustive_qc,
            "deterministic_audit_only": self.deterministic_audit_only,
            "configuration_kind": self.configuration_kind,
            "run_synthesis": self.run_synthesis,
            "run_critique": self.run_critique,
            "critique_reads": self.critique_reads,
            "run_cross_qc": self.run_cross_qc,
            "run_auditors": self.run_auditors,
            "run_prose_harvest": self.run_prose_harvest,
            "run_anchoring": self.run_anchoring,
            "run_verification": self.run_verification,
            "run_citation": self.run_citation,
            "run_markup": self.run_markup,
            "run_coverage_check": self.run_coverage_check,
            "run_identity": self.run_identity,
            "run_review_plan": self.run_review_plan,
            "markup_verified_only": self.markup_verified_only,
            "ink_rejected": self.ink_rejected,
            "focus_findings_to_markups": self.focus_findings_to_markups,
            "use_batch": self.use_batch,
            "debug_overrides": list(self.debug_overrides),
        }


def resolve_run_configuration(
    *,
    qc_markups: bool = False,
    reference_audit: bool = False,
    synthesize: "bool | None" = None,
    critique: "bool | None" = None,
    cross_qc: "bool | None" = None,
    citation_check: "bool | None" = None,
    verify_findings: "bool | None" = None,
    identity: "bool | None" = None,
    review_plan: "bool | None" = None,
    markup_verified_only: bool = False,
    ink_rejected: bool = False,
    focus_findings_to_markups: bool = False,
    use_batch: bool = False,
) -> RunConfiguration:
    """Resolve the raw run options into one normalized :class:`RunConfiguration`.

    The single source of truth for what ``qc_markups=True`` means (§15.1): it
    turns on the full exhaustive stack — synthesis (for ≥2 readable sheets, gated
    downstream), two critique reads, cross-sheet QC, the deterministic auditors,
    prose harvest, anchoring, verification, citation checks, markup, and coverage
    reconciliation. The overridable stages default on but may be disabled by an
    explicit ``False`` (an expert/debug override that records itself so the run is
    scored ``PARTIAL``, never a clean ``COMPLETE``).

    ``reference_audit=True`` **without** ``qc_markups`` is the free offline
    battery: deterministic auditors + offline anchoring, no model calls. Neither
    box is the standard path: digest findings retained + anchored offline, nothing
    billed. The per-stage keyword arguments are ``bool | None`` — ``None`` means
    "not specified, use the product default"; an explicit ``True``/``False`` is an
    override honored verbatim.
    """
    exhaustive = bool(qc_markups)

    overrides: list[str] = []

    def _exhaustive_switch(flag: "bool | None", name: str) -> bool:
        # A normally-required exhaustive stage: default on; an explicit False is a
        # debug override; an explicit True is redundant but harmless.
        if not exhaustive:
            # Outside exhaustive QC these stages run only when explicitly asked
            # for (an expert/diagnostic invocation), and never structure prose.
            return bool(flag) if flag is not None else False
        if flag is False:
            overrides.append(name)
            return False
        return True

    run_synthesis = _exhaustive_switch(synthesize, "synthesis")
    run_critique = _exhaustive_switch(critique, "critique")
    run_cross_qc = _exhaustive_switch(cross_qc, "cross_qc")
    run_verification = _exhaustive_switch(verify_findings, "verification")
    run_citation = _exhaustive_switch(citation_check, "citation")

    # Phase A (universal reviewer): the two model-planning stages ride the
    # critique stack rather than being their own product mode. Unspecified,
    # the set-identity harvest runs whenever a stage that consumes it runs
    # (critique via the plan, citation via the merged editions/jurisdiction),
    # and the review plan runs whenever critique — its only consumer — runs.
    # An explicit flag is honored verbatim through the same tri-state contract
    # as the other exhaustive stages (False inside exhaustive is a recorded
    # debug override; True outside exhaustive is an expert invocation).
    if identity is None:
        run_identity = exhaustive or run_critique or run_citation
    else:
        run_identity = _exhaustive_switch(identity, "identity")
    if review_plan is None:
        run_review_plan = run_critique
    else:
        run_review_plan = _exhaustive_switch(review_plan, "review_plan")

    # ``deterministic_audit_only`` is the "free battery, zero incremental API"
    # promise (DA-013): true ONLY when reference_audit is on, QC is not exhaustive,
    # and no expert flag enabled a model-calling stage. An expert who combines
    # reference_audit with e.g. critique=True still runs the auditors, but the run
    # is no longer zero-cost, so the flag must not claim it is. (verification does
    # not run outside markup, so it never breaks the promise.) The Phase A
    # planning stages are paid model calls, so they join the paid-expert set.
    any_paid_expert = (
        run_synthesis or run_critique or run_cross_qc or run_citation
        or run_identity or run_review_plan
    )
    audit_only = bool(reference_audit) and not exhaustive and not any_paid_expert

    return RunConfiguration(
        standard_analysis=True,
        exhaustive_qc=exhaustive,
        deterministic_audit_only=audit_only,
        run_synthesis=run_synthesis,
        run_critique=run_critique,
        critique_reads=2 if run_critique else 0,
        run_cross_qc=run_cross_qc,
        # Auditors run in exhaustive QC *and* whenever the free battery was asked
        # for (reference_audit) — independent of whether the run is *purely* free.
        run_auditors=exhaustive or bool(reference_audit),
        # Prose harvest (with its straggler-structuring model call) is exhaustive
        # only — standard and audit-only runs keep unmatched prose in the prose
        # (§14.7 / §15.3), incurring no structuring calls.
        run_prose_harvest=exhaustive,
        run_anchoring=True,
        run_verification=run_verification,
        run_citation=run_citation,
        run_markup=exhaustive,
        run_coverage_check=exhaustive,
        run_identity=run_identity,
        run_review_plan=run_review_plan,
        markup_verified_only=bool(markup_verified_only),
        ink_rejected=bool(ink_rejected),
        focus_findings_to_markups=bool(focus_findings_to_markups),
        use_batch=bool(use_batch),
        debug_overrides=tuple(overrides),
    )


def roll_up_qc_status(
    config: RunConfiguration,
    stage_results: "list[StageResult]",
    coverage_status: str,
    *,
    completeness_gate_open: bool = False,
) -> str:
    """Deterministically roll per-stage outcomes into an overall QC status (§3.3).

    ``NOT_REQUESTED`` unless exhaustive QC ran. Otherwise ``COMPLETE`` only for a
    ``NORMAL`` configuration whose every *expected* required stage is ``COMPLETE``
    or ``SKIPPED_VALID`` and whose placement coverage is ``COMPLETE``; ``PARTIAL``
    when useful QC output exists but a required stage is ``PARTIAL``/``FAILED``,
    coverage is ``INCOMPLETE``, or the configuration is a debug override; else
    ``FAILED``.

    ``completeness_gate_open`` is the Phase 23 gate; it defaults to ``False``
    (the conservative direction — never claim ``COMPLETE`` unless the caller
    explicitly opens it). The pipeline opened it in Phase 26B (§18.0): Phases
    24–25 landed the cross-shard reconciliation, claim-complete citations,
    evidence, and callout-overflow guarantees, so a clean NORMAL exhaustive run
    earns ``COMPLETE``. A closed gate still caps such a run at ``PARTIAL`` for
    callers that have not made those guarantees (§8, §15.5).
    """
    if not config.qc_requested:
        return "NOT_REQUESTED"

    required = [s for s in stage_results if s.expected]
    any_failed = any(s.status in ("PARTIAL", "FAILED") for s in required)
    any_useful = any(s.status in ("COMPLETE", "PARTIAL") for s in stage_results)
    all_ok = all(s.status in ("COMPLETE", "SKIPPED_VALID") for s in required)

    coverage_ok = coverage_status in ("COMPLETE", "NOT_REQUESTED")
    coverage_incomplete = coverage_status == "INCOMPLETE"
    is_normal = config.configuration_kind == "NORMAL"

    if is_normal and all_ok and coverage_ok:
        return "PARTIAL" if not completeness_gate_open else "COMPLETE"
    if any_useful and (any_failed or coverage_incomplete or not is_normal):
        return "PARTIAL"
    return "FAILED"


# --------------------------------------------------------------------------- #
# Usage accounting (Phase 23B — §6.3 / §15.6)
# --------------------------------------------------------------------------- #
#
# Token/cost accounting is an **append-only** ledger of per-call records, never a
# mutable "current total" a stage can overwrite (the old ``v_in, v_out = …`` in the
# QC pipeline silently dropped the prose-harvest tokens when verification ran). The
# run totals are *derived* sums over the records, so two critique reads, many
# cross-QC shards, a retry, and a citation chunk each contribute their own record
# and none can clobber another's. ``estimated_cost`` is priced by the pipeline at
# record time (``core.pricing``) and stored, so this module stays dependency-free.

USAGE_TRANSPORTS = ("REAL_TIME", "BATCH", "CACHE")
USAGE_STAGE_FAMILIES = (
    "digest", "critique", "synthesis", "focus", "harvest", "cross_qc", "verify", "citation",
    "identity", "review_plan",
)
USAGE_TERMINAL_STATUSES = ("COMPLETE", "PARTIAL", "FAILED")


@dataclass
class UsageRecord:
    """One API call/attempt's reported usage (§6.3). Append-only; never mutated in place.

    ``transport`` is ``CACHE`` for a served cache hit (which bills **zero** current-run
    tokens — its token fields are 0 and ``cache_hit`` is set), ``BATCH`` for a Message
    Batches call (billed at the batch rate), else ``REAL_TIME``. ``parse_success`` is
    ``False`` for a response that consumed tokens but failed to parse — it still counts
    as billable. ``estimated_cost`` is the record's USD cost priced at its own rate
    class (``None`` when the model's price is unknown).
    """

    stage_family: str
    stage_instance: str
    model: str = ""
    transport: str = "REAL_TIME"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    billable_tool_uses: dict = field(default_factory=dict)
    cache_hit: bool = False
    parse_success: bool = True
    terminal_status: str = "COMPLETE"
    parent_stage_instance: "str | None" = None
    attempt_number: int = 1
    billing_rate_class: str = ""
    request_or_custom_id: str = ""
    estimated_cost: "Decimal | None" = None

    def to_dict(self) -> dict:
        return {
            "stage_family": self.stage_family,
            "stage_instance": self.stage_instance,
            "model": self.model,
            "transport": self.transport,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "billable_tool_uses": dict(self.billable_tool_uses),
            "cache_hit": self.cache_hit,
            "parse_success": self.parse_success,
            "terminal_status": self.terminal_status,
            "parent_stage_instance": self.parent_stage_instance,
            "attempt_number": self.attempt_number,
            "billing_rate_class": self.billing_rate_class,
            "request_or_custom_id": self.request_or_custom_id,
            "estimated_cost": None if self.estimated_cost is None else str(self.estimated_cost),
        }


@dataclass
class RunUsage:
    """The run's append-only usage ledger (§6.3). Totals are derived, never stored.

    Add a :class:`UsageRecord` per call with :meth:`add`; the ``total_*`` properties
    and :meth:`by_family` are computed on read, so no stage can overwrite another's
    counters and the grand totals always equal the exact sum of the records.
    """

    records: list = field(default_factory=list)

    def add(self, record: "UsageRecord") -> "UsageRecord":
        self.records.append(record)
        return record

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(r.cache_read_tokens for r in self.records)

    @property
    def total_cache_write_tokens(self) -> int:
        return sum(r.cache_write_tokens for r in self.records)

    @property
    def cache_hits(self) -> int:
        return sum(1 for r in self.records if r.cache_hit)

    @staticmethod
    def _billable_but_unpriced(r: "UsageRecord") -> bool:
        """A record that consumed billable usage but the model couldn't be priced.

        Its cost is genuinely *unknown*, not zero — so summing the priced records
        around it would understate the total and present it as authoritative. A
        zero-token cache hit under an unknown model is NOT billable and does not
        poison the total.
        """
        return r.estimated_cost is None and bool(
            r.input_tokens or r.output_tokens or r.billable_tool_uses
        )

    @property
    def total_estimated_cost(self) -> "Decimal | None":
        # If ANY billable record could not be priced, the aggregate is unknowable —
        # return None rather than a partial sum that silently omits real cost.
        if any(self._billable_but_unpriced(r) for r in self.records):
            return None
        priced = [r.estimated_cost for r in self.records if r.estimated_cost is not None]
        return sum(priced, Decimal("0")) if priced else None

    def by_family(self) -> "dict[str, dict]":
        """Per-``stage_family`` rollup: input/output tokens, cost, call + cache-hit counts.

        A family's ``estimated_cost`` is ``None`` when any of its records is billable
        but unpriced (same rule as the grand total) so a partial figure is never
        shown as if it were the family's full cost.
        """
        out: dict[str, dict] = {}
        unpriced: set[str] = set()
        for r in self.records:
            g = out.setdefault(
                r.stage_family,
                {"input_tokens": 0, "output_tokens": 0, "calls": 0, "cache_hits": 0,
                 "estimated_cost": None},
            )
            g["input_tokens"] += r.input_tokens
            g["output_tokens"] += r.output_tokens
            g["calls"] += 1
            if r.cache_hit:
                g["cache_hits"] += 1
            if self._billable_but_unpriced(r):
                unpriced.add(r.stage_family)
            elif r.estimated_cost is not None:
                g["estimated_cost"] = (g["estimated_cost"] or Decimal("0")) + r.estimated_cost
        for fam in unpriced:
            out[fam]["estimated_cost"] = None
        return out

    def to_dict(self) -> dict:
        cost = self.total_estimated_cost
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_write_tokens": self.total_cache_write_tokens,
            "cache_hits": self.cache_hits,
            "total_estimated_cost": None if cost is None else str(cost),
            "by_family": {
                fam: {**g, "estimated_cost": None if g["estimated_cost"] is None
                      else str(g["estimated_cost"])}
                for fam, g in self.by_family().items()
            },
            "records": [r.to_dict() for r in self.records],
        }
