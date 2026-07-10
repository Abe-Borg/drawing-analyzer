"""Dependency-free data models for the drawing subsystem.

Kept separate from :mod:`render` so consumers (:mod:`digest`, :mod:`pipeline`)
can reference these shapes without transitively importing the PyMuPDF backend.
Only :mod:`render` produces these; everything else just consumes them.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
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
class Verification:
    """The verification verdict for a finding (filled by the verify pass).

    ``DETERMINISTIC`` marks a finding produced by an offline auditor that never
    hit the API (a reference/arithmetic/naming check); such findings are trusted
    without a model re-check. ``evidence_png`` is a run-relative path to the crop
    the verifier saw (empty for deterministic findings, which have none).
    """

    status: str = "SKIPPED"             # one of VERIFICATION_STATUSES
    note: str = ""
    evidence_png: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "note": self.note,
            "evidence_png": self.evidence_png,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Verification":
        return cls(
            status=d.get("status", "SKIPPED"),
            note=d.get("note", ""),
            evidence_png=d.get("evidence_png", ""),
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


@dataclass
class Finding:
    """One QC finding: a single reviewable issue anchored to a sheet.

    See §4.1 of the QC plan for the full contract. ``source_quote`` is a string
    copied **verbatim** from the sheet's text layer (required when the sheet has
    a text layer; ``""`` only for a purely graphical finding). ``tile`` is the
    ``[row, col]`` grid position the model reported (``None`` for offline /
    deterministic findings, which carry exact anchors instead). ``id`` is derived
    from the content when not supplied, so callers normally omit it.

    ``anchor_hint`` is an optional coarse placement hint from the model — currently
    ``"SHEET"`` for a sheet-level / *absence* finding (something the reviewer
    expected but did not find), which has no ``source_quote`` to anchor and is
    placed against the whole sheet rather than a rectangle. ``reproduced`` is a
    soft confidence signal: ``True`` unless a self-consistency pass saw the finding
    in only one of several independent reads (an uncorroborated singleton). It
    never suppresses a finding — the report and the markup writer only *surface*
    it — so it defaults ``True`` for every finding that never went through that
    pass (digest findings, the deterministic auditors).

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
    anchor_hint: str = ""               # "SHEET" for a sheet-level / absence finding
    reproduced: bool = True             # corroborated by a second read (self-consistency)
    also_on: list["ConflictLeg"] = field(default_factory=list)  # cross-sheet legs (Phase 13)
    anchor: Anchor = field(default_factory=Anchor)
    verification: Verification = field(default_factory=Verification)
    qc_id: str = ""                     # "QC-001" … (assigned by assign_qc_ids)
    citation: Citation | None = None    # web-search citation check (Phase 15)
    sources: list[str] = field(default_factory=list)  # provenance tags (Part III)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = compute_finding_id(
                self.sheet_id, self.category, self.source_quote or self.text,
                self.source_id,
            )

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
            "also_on": [leg.to_dict() for leg in self.also_on],
            "sources": list(self.sources),
            "anchor": self.anchor.to_dict(),
            "verification": self.verification.to_dict(),
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
            also_on=[ConflictLeg.from_dict(leg) for leg in (d.get("also_on") or []) if isinstance(leg, dict)],
            sources=[str(s) for s in (d.get("sources") or [])],
            anchor=Anchor.from_dict(d.get("anchor") or {}),
            verification=Verification.from_dict(d.get("verification") or {}),
            qc_id=d.get("qc_id", "") or "",
            citation=Citation.from_dict(d["citation"]) if isinstance(d.get("citation"), dict) else None,
            id=d.get("id", ""),
        )


def assign_qc_ids(findings: list["Finding"]) -> list["Finding"]:
    """Assign sequential review numbers (``QC-001`` …) across a run's findings.

    Ordered **sheet then position** (Phase 15): source file, page, then the
    anchor rectangle's top-left in reading order (top-to-bottom, left-to-right).
    Findings with no rectangle (sheet-level / unanchored) sort after the anchored
    ones on their sheet. The sort is deterministic — tie-broken by the stable
    content ``id`` — so the same findings get the same numbers regardless of the
    order they arrive in (I-7). Assigns in place and returns the same list; ids
    are assigned exactly once per run (numbering everything, not only the inked
    findings, so the CSV/report/index all share one namespace).
    """

    def _pos(f: "Finding") -> tuple:
        rect = f.anchor.rect_pdf if f.anchor is not None else None
        if rect:
            return (0, float(rect[1]), float(rect[0]))
        return (1, 0.0, 0.0)            # rect-less findings sort after anchored ones

    ordered = sorted(
        findings,
        key=lambda f: (source_page_key(f), _pos(f), f.id),
    )
    width = max(3, len(str(len(ordered))))
    for n, finding in enumerate(ordered, start=1):
        finding.qc_id = f"QC-{n:0{width}d}"
    return findings


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
