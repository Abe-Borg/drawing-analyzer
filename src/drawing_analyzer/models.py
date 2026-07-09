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

    def to_dict(self) -> dict:
        return {
            "sheet_id": self.sheet_id,
            "source_name": self.source_name,
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
                self.sheet_id, self.category, self.source_quote or self.text
            )

    def to_dict(self) -> dict:
        out = {
            "id": self.id,
            "qc_id": self.qc_id,
            "sheet_id": self.sheet_id,
            "source_name": self.source_name,
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
        key=lambda f: (f.source_name, int(f.page_index or 0), _pos(f), f.id),
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

    def to_dict(self) -> dict:
        return {
            "sheet_id": self.sheet_id,
            "quote": self.quote,
            "kind": self.kind,
            "terms": list(self.terms),
            "expected": self.expected,
            "note": self.note,
            "source_name": self.source_name,
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
        )
