"""Dependency-free data models for the drawing subsystem.

Kept separate from :mod:`render` so consumers (:mod:`digest`, :mod:`pipeline`)
can reference these shapes without transitively importing the PyMuPDF backend.
Only :mod:`render` produces these; everything else just consumes them.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SheetRef:
    """Identifies one sheet: a single page within a source PDF."""

    pdf_path: Path
    page_index: int          # zero-based
    source_name: str         # pdf_path.name, for display / provenance
    page_count: int          # pages in the source PDF

    @property
    def display_label(self) -> str:
        return f"{self.source_name} (page {self.page_index + 1}/{self.page_count})"


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

    @property
    def image_sizes(self) -> list[tuple[int, int]]:
        """``(width, height)`` for every image (overview + tiles), for token est."""
        sizes = [(self.overview.width_px, self.overview.height_px)]
        sizes.extend((t.width_px, t.height_px) for t in self.tiles)
        return sizes


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


def compute_finding_id(sheet_id: str, category: str, quote_or_text: str) -> str:
    """Stable short id for a finding: ``sha1(sheet_id + category + quote/text)``.

    Deterministic and content-derived so the *same* finding gets the *same* id
    across runs (and so two harvests of one issue collapse to one id, which the
    later dedup/ledger stages rely on). ``quote_or_text`` should be the verbatim
    ``source_quote`` when present, else the finding ``text``.
    """
    h = hashlib.sha1()
    h.update(sheet_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(category.encode("utf-8"))
    h.update(b"\x00")
    h.update(quote_or_text.encode("utf-8"))
    return h.hexdigest()[:12]


@dataclass
class Anchor:
    """Where a finding sits on its page (filled by the anchor resolver).

    ``rect_pdf`` is ``[x0, y0, x1, y1]`` in **PyMuPDF top-left-origin points**
    (the same coordinate space ``get_text("words")`` reports and the markup
    writer draws in — no flip needed as long as both stay in PyMuPDF). ``None``
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
class Finding:
    """One QC finding: a single reviewable issue anchored to a sheet.

    See §4.1 of the QC plan for the full contract. ``source_quote`` is a string
    copied **verbatim** from the sheet's text layer (required when the sheet has
    a text layer; ``""`` only for a purely graphical finding). ``tile`` is the
    ``[row, col]`` grid position the model reported (``None`` for offline /
    deterministic findings, which carry exact anchors instead). ``id`` is derived
    from the content when not supplied, so callers normally omit it.
    """

    sheet_id: str
    source_name: str
    page_index: int
    category: str                       # one of FINDING_CATEGORIES
    severity: str                       # one of FINDING_SEVERITIES
    text: str
    source_quote: str = ""
    tile: list[int] | None = None
    refs: list[str] = field(default_factory=list)
    anchor: Anchor = field(default_factory=Anchor)
    verification: Verification = field(default_factory=Verification)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = compute_finding_id(
                self.sheet_id, self.category, self.source_quote or self.text
            )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sheet_id": self.sheet_id,
            "source_name": self.source_name,
            "page_index": self.page_index,
            "category": self.category,
            "severity": self.severity,
            "text": self.text,
            "source_quote": self.source_quote,
            "tile": list(self.tile) if self.tile is not None else None,
            "refs": list(self.refs),
            "anchor": self.anchor.to_dict(),
            "verification": self.verification.to_dict(),
        }

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
            page_index=int(d.get("page_index", 0) or 0),
            category=d.get("category", ""),
            severity=d.get("severity", ""),
            text=d.get("text", ""),
            source_quote=d.get("source_quote", ""),
            tile=[int(v) for v in tile] if tile else None,
            refs=list(d.get("refs", []) or []),
            anchor=Anchor.from_dict(d.get("anchor") or {}),
            verification=Verification.from_dict(d.get("verification") or {}),
            id=d.get("id", ""),
        )
