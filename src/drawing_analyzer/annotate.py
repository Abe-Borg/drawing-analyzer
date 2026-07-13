"""Markup writer: turn findings into a numbered, navigable, reviewed PDF.

This writes **real annotation objects** onto a ``<stem>_reviewed.pdf`` so the
result reads like a senior plan-review set (Phase 15):

- every inked finding carries a sequential **QC tag** (``QC-001`` …) — a small
  FreeText label beside its cloud in the severity color; the same number appears
  in the CSV, ``findings.json``, the HTML report, and the index page;
- **severity styling**: high = red, medium = orange, low / question = blue;
  DETERMINISTIC (auditor) findings draw a **solid** border, model findings a
  **revision cloud** (``clouds=2``), opted-in unverified findings **dashed** with
  an ``[UNVERIFIED]`` popup prefix;
- text-anchored defects are Square clouds; **sheet-level / absence findings**
  (``anchor_hint="SHEET"``) become FreeText **callout boxes stacked in a computed
  clear margin band** (the largest text-free horizontal band, found from the
  sheet's word rectangles), with a **leader Line** arrow to the reported tile's
  centroid when one is known;
- **findings index pages** are inserted at the front of each reviewed PDF —
  a table (ID, sheet, severity, status, one-line text) where every row carries a
  GOTO link jumping to the finding's page and rectangle; labeled
  "AI DRAFT REVIEW — index";
- an optional **appendix page** (off by default) lists the deterministic checks
  that *passed* — the balance column of a real review;
- popups are exhaustive and descriptive: finding text, verbatim quote, refs plus
  the citation-check verdict, verification status/note, the cross-sheet pointer,
  the reproduced flag, the evidence filename, and both finding ids.

Opened in Bluebeam Revu the annots populate the Markups List (filter / sort /
reply / export all work); Acrobat and Chromium render them too, and the index
links jump in all three.

.. warning::
   PyMuPDF is licensed **AGPL-3.0**. This is the **second and only other** module
   permitted to import it (the first is :mod:`render`); every other module works
   on the dependency-free :class:`~drawing_analyzer.models.Finding` /
   geometry, so the PDF backend stays swappable. If this project is distributed
   and you need to relicense, a permissive alternative is ``pypdf`` building
   ``/Square`` annots with a manual border-effect dict
   (``/BE {/S /C /I 2}`` for the cloud) — but pypdf does **not** generate an
   appearance stream, so some viewers render nothing; PyMuPDF's ``annot.update()``
   (below) builds the ``/AP`` that makes the cloud show everywhere. That gap is
   why PyMuPDF is used here.

.. note::
   Finding rectangles arrive in the canonical **PAGE_VIEW_V2** space (Phase 19) —
   post-CropBox, post-rotation, matching the images the model saw. PyMuPDF's
   ``add_*_annot`` / link APIs, however, place ink in the page's *un-rotated,
   CropBox-relative* space (characterized empirically — see
   ``tests/test_drawing_geometry.py``). So every rect/point is transformed
   view→page via the live page's ``derotation_matrix`` (== ``PageGeometry.
   view_to_page``) right before it is drawn (:func:`_derotate_rect` /
   :func:`_derotate_point`), and FreeText text is drawn with ``rotate=
   page.rotation`` so callouts read upright on a rotated sheet. On an un-rotated
   page the transform is the identity, so the common case is unchanged. The
   transform lives here (a blessed PyMuPDF module), keeping every other module
   working on plain PAGE_VIEW_V2 numbers.

The writer never touches the source file: it opens the original, adds annots in
memory, and saves a *new* ``_reviewed.pdf``. It proves its work (Phase 21,
DA-007): every mark is stamped with its logical placement id, and after saving
the file is reopened and reconciled against the plan — a placement counts only
when its stamped component is found again in the saved artifact. Stamps embed a
per-run id, so a re-review of a PDF that already carries analyzer annotations
reconciles against *this* run's marks, and unrelated pre-existing source
annotations (which carry no stamp) are ignored (DA-029). The writer returns a
:class:`~drawing_analyzer.models.MarkupRunResult` — the receipts, the
receipt-derived coverage status/tally, and the reviewed-PDF paths.
"""
from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import pymupdf  # AGPL-3.0 — see module docstring; the 2nd of two blessed importers.

from . import tiling
from .diagnostics import get_logger
from .models import (
    ANNOTATION_COMPONENTS,
    PRIMARY_LEG_ID,
    REQUIRED_COMPONENTS,
    SET_LEG_ID,
    ConflictLeg,
    Finding,
    MarkupPlacement,
    MarkupReceipt,
    MarkupRunResult,
    leg_identity,
)
from .source_registry import assign_source_ids

_log = get_logger()

# The annot author — provenance is unmistakable in the Markups List.
DEFAULT_AUTHOR = "Drawing Analyzer (AI review)"
# The index/appendix page label — same provenance rule. ASCII hyphen, not an
# em-dash: insert_text's Base-14 fonts have no U+2014 glyph.
INDEX_PAGE_LABEL = "AI DRAFT REVIEW - FINDINGS INDEX"
APPENDIX_PAGE_LABEL = "AI DRAFT REVIEW - CHECKED AND CONSISTENT"

# Verification statuses trusted unconditionally. Under the Part III gating
# amendment (§18) the exhaustive default inks EVERYTHING except REJECTED —
# UNCERTAIN / SKIPPED render in the dashed "unverified" style; the conservative
# "verified & deterministic only" mode (opt-in) restricts ink to this set.
_TRUSTED = frozenset({"VERIFIED", "DETERMINISTIC"})
# Rejected findings render grey/struck when explicitly opted in (--ink-rejected).
_REJECTED_COLOR = (0.45, 0.45, 0.45)

# Stroke color by severity (RGB 0–1): red / orange / blue, grey fallback. A
# "question"-category finding is blue regardless of its severity (Phase 15 spec:
# high = red, medium = orange, question/low = blue).
_SEVERITY_COLORS = {
    "high": (0.84, 0.11, 0.11),
    "medium": (0.90, 0.49, 0.07),
    "low": (0.16, 0.42, 0.82),
}
_QUESTION_COLOR = (0.16, 0.42, 0.82)
_DEFAULT_COLOR = (0.40, 0.40, 0.40)

_BORDER_WIDTH = 1.5
_TAG_FONTSIZE = 8.0
_TAG_HEIGHT = 12.0

# Margin callout layout (sheet-level / absence findings).
_CALLOUT_W = 230.0
_CALLOUT_H = 54.0
_CALLOUT_GAP = 8.0

# Index-page layout (US letter portrait).
_INDEX_PAGE_W, _INDEX_PAGE_H = 612.0, 792.0
_INDEX_TOP = 90.0
_INDEX_ROW_H = 14.0
_INDEX_BOTTOM_MARGIN = 40.0
_INDEX_ROWS_PER_PAGE = int((_INDEX_PAGE_H - _INDEX_TOP - _INDEX_BOTTOM_MARGIN) / _INDEX_ROW_H)

# --------------------------------------------------------------------------- #
# Artifact-backed markup coverage (Phase 21, DA-007) — the writer-and-reopen
# receipt protocol that replaces the old intention tally.
#
# Every analyzer-owned annotation and every generated index row is stamped with a
# **private PDF object key** carrying its logical placement id + component kind +
# the page it lands on. On reopen the writer scans for these stamps and
# reconciles them against the plan: a mark counts only if it is found again in
# the saved file. Because the placement id embeds a per-run ``artifact_run_id``,
# stamps left by an *earlier* review of the same source PDF never satisfy this
# run's plan (§13.3), and annotations the analyzer never wrote carry no stamp at
# all — so unrelated pre-existing source annotations are transparently ignored
# (DA-029). The stamp lives on the PDF object dict (``xref_set_key``), not in the
# displayed text, so it never pollutes the popup and never adds an annotation.
# --------------------------------------------------------------------------- #
_PLACEMENT_KEY = "DAPlacement"       # per-annot / per-index-link: "pid|component|page"
_INDEX_PAGE_KEY = "DAIndexPage"      # per generated index page: the run id
_INDEX_ROWS_KEY = "DAIndexRows"      # per index page: "pid@target;pid@target;…" (index-only rows)
_STAMP_SEP = "|"


def new_artifact_run_id() -> str:
    """A fresh per-run nonce distinguishing THIS run's marks from a prior run's.

    Injectable into :func:`annotate_pdf` / :func:`write_reviewed_pdfs` (tests pin
    it); a random default otherwise. It never affects finding ordering, numbering,
    or content (I-7) — it exists only so a re-review of a PDF that already carries
    analyzer annotations reconciles against *this* run's stamps, not the old ones.
    """
    return "run-" + uuid.uuid4().hex[:12]


def _safe_pdf_string(value: str) -> str:
    """Strip the three PDF string-literal metacharacters so ``xref_set_key`` is safe.

    Placement ids are built from run nonces, sha1 hex, ``QC-``/``SRC-`` labels and
    the ``|``/``@`` separators — none of which contain ``()\\`` — but we defend in
    depth so a future id shape can never corrupt the object stream.
    """
    return value.replace("(", "").replace(")", "").replace("\\", "")


def _stamp_component(
    doc: "pymupdf.Document", xref: int, placement_id: str, component: str, page: int
) -> None:
    """Stamp one drawn component (annotation) with its placement identity."""
    val = _safe_pdf_string(f"{placement_id}{_STAMP_SEP}{component}{_STAMP_SEP}{int(page)}")
    doc.xref_set_key(xref, _PLACEMENT_KEY, f"({val})")


def _read_stamp(doc: "pymupdf.Document", xref: int) -> "tuple[str, str, int] | None":
    """Read a component stamp back → ``(placement_id, component, page)`` or ``None``."""
    try:
        kind, value = doc.xref_get_key(xref, _PLACEMENT_KEY)
    except Exception:  # noqa: BLE001 - a malformed object never sinks reconciliation
        return None
    if kind != "string" or not value:
        return None
    parts = value.split(_STAMP_SEP)
    if len(parts) != 3:
        return None
    try:
        return parts[0], parts[1], int(parts[2])
    except (TypeError, ValueError):
        return None


@dataclass
class _DrawUnit:
    """One thing to actually draw: a finding (or a synthetic cross-sheet leg) plus
    the :class:`MarkupPlacement` that accounts for it."""

    finding: Finding
    placement: MarkupPlacement


def _scope_of(finding: Finding, leg_id: str) -> str:
    if leg_id == SET_LEG_ID:
        return "SET"
    if (finding.anchor_hint or "").upper() in {"SET", "SET_INDEX"} and not finding.source_id:
        return "SET"
    return "SOURCE"


def _expected_kind(
    finding: Finding, *, include_unverified: bool, ink_rejected: bool
) -> str:
    """The placement kind this finding will become — mirrors the drawing branches.

    Built on the same :func:`ink_disposition` classifier the writer draws from, so
    the plan can never disagree with the ink: ``cloud`` → CLOUD, ``margin`` →
    MARGIN, ``gated`` → GATED_INDEX (a real "not inked by operator gate" index
    row, §6.4), and a REJECTED finding → its grey CLOUD/MARGIN when
    ``ink_rejected`` else a REJECTED_INDEX row.
    """
    disposition = ink_disposition(
        finding, include_unverified=include_unverified, ink_rejected=ink_rejected
    )
    if disposition == "cloud":
        return "CLOUD"
    if disposition == "margin":
        return "MARGIN"
    if disposition == "gated":
        return "GATED_INDEX"
    # disposition == "rejected"
    if ink_rejected:
        anchored = finding.anchor is not None and finding.anchor.rect_pdf is not None
        return "CLOUD" if anchored else "MARGIN"
    return "REJECTED_INDEX"


def _make_placement(
    finding: Finding,
    *,
    parent_id: str,
    leg_id: str,
    run_id: str,
    ordinal: int,
    include_unverified: bool,
    ink_rejected: bool,
) -> MarkupPlacement:
    kind = _expected_kind(
        finding, include_unverified=include_unverified, ink_rejected=ink_rejected
    )
    # The ordinal is a deterministic per-run tiebreaker so the placement id stays
    # unique even if two distinct findings happen to share a content id (same
    # sheet / category / quote — hand-built or pre-dedup). The finding id + leg id
    # remain in the placement fields for traceability (§13.1).
    return MarkupPlacement(
        run_id=run_id,
        placement_id=f"{run_id}#{parent_id}#{leg_id}#{ordinal:05d}",
        finding_id=parent_id,
        qc_id=finding.qc_id,
        scope=_scope_of(finding, leg_id),
        source_id=finding.source_id,
        page_index=int(finding.page_index),
        leg_id=leg_id,
        expected=kind,
        required_components=list(REQUIRED_COMPONENTS[kind]),
        severity=finding.severity,
        source_name=finding.source_name,
    )


def _units_for_finding(
    finding: Finding,
    *,
    run_id: str,
    ordinals: "Iterator[int]",
    include_unverified: bool,
    ink_rejected: bool,
) -> list[_DrawUnit]:
    """A finding's own placement plus one placement per cross-sheet leg.

    The primary unit draws the finding on its own sheet (``leg_id="primary"``);
    each ``also_on`` leg becomes a synthetic finding drawn on *its* sheet, its
    placement tagged ``finding_id=<parent id>`` / ``leg_id=<stable leg id>`` so the
    manifest ties every leg back to one logical conflict and no two placements
    collide. ``ordinals`` yields the run-wide unique tiebreakers. Synthetic legs
    live only here (never in the findings record), exactly as before Phase 21.
    """

    def _plan(f: Finding, leg_id: str) -> MarkupPlacement:
        return _make_placement(
            f, parent_id=finding.id, leg_id=leg_id, run_id=run_id,
            ordinal=next(ordinals),
            include_unverified=include_unverified, ink_rejected=ink_rejected,
        )

    units = [_DrawUnit(finding, _plan(finding, PRIMARY_LEG_ID))]
    legs = getattr(finding, "also_on", None) or []
    if not legs:
        return units
    primary_as_leg = ConflictLeg(
        sheet_id=finding.sheet_id, source_name=finding.source_name,
        source_id=finding.source_id, page_index=finding.page_index,
        source_quote=finding.source_quote, tile=finding.tile, anchor=finding.anchor,
    )
    for i, leg in enumerate(legs):
        others = [primary_as_leg] + [l for j, l in enumerate(legs) if j != i]
        leg_finding = Finding(
            sheet_id=leg.sheet_id, source_name=leg.source_name, source_id=leg.source_id,
            page_index=leg.page_index, category=finding.category, severity=finding.severity,
            text=finding.text, source_quote=leg.source_quote, refs=list(finding.refs),
            also_on=others, anchor=leg.anchor, verification=finding.verification,
            qc_id=finding.qc_id, citation=finding.citation, sources=list(finding.sources),
        )
        lid = leg_identity(
            leg.source_id, leg.source_name, leg.page_index, leg.source_quote, i
        )
        units.append(_DrawUnit(leg_finding, _plan(leg_finding, lid)))
    return units


def _finding_touches(finding: Finding, source_ids: "set[str]") -> bool:
    """True when the finding's own source or any of its legs sits on a listed source."""
    if getattr(finding, "source_id", "") in source_ids:
        return True
    for leg in getattr(finding, "also_on", None) or []:
        if getattr(leg, "source_id", "") in source_ids:
            return True
    return False


def _status(finding: Finding) -> str:
    v = getattr(finding, "verification", None)
    return v.status if v is not None else "SKIPPED"


def _trust_gate(finding: Finding, *, include_unverified: bool) -> bool:
    """The shared status gate: REJECTED never inks; trusted always; rest opt-in."""
    status = _status(finding)
    if status == "REJECTED":
        return False
    if status in _TRUSTED:
        return True
    return include_unverified


def is_cloudable(finding: Finding, *, include_unverified: bool) -> bool:
    """Whether this finding gets a Square cloud (needs an anchor rectangle).

    A ``REJECTED`` finding is never default-inked (a known-wrong cloud on an
    issued drawing is the one failure worse than a missing one); ``VERIFIED`` /
    ``DETERMINISTIC`` always are; the rest only when ``include_unverified`` —
    the exhaustive default under §18, where the conservative
    verified-&-deterministic-only mode is the opt-in.
    """
    anchor = getattr(finding, "anchor", None)
    if anchor is None or anchor.rect_pdf is None:
        return False
    return _trust_gate(finding, include_unverified=include_unverified)


def is_margin_callout(finding: Finding, *, include_unverified: bool) -> bool:
    """Whether this finding gets a margin callout box.

    Under the Part III gating amendment (§18) **every rect-less finding** gets a
    callout — sheet-level / absence findings (``anchor_hint="SHEET"``) *and*
    ``UNANCHORED`` ones (the quote-matched-nothing hallucination signals, drawn
    with an ``[UNANCHORED]`` prefix so they read as flagged, never dropped) —
    subject to the same trust gating as clouds.
    """
    anchor = getattr(finding, "anchor", None)
    if anchor is not None and anchor.rect_pdf is not None:
        return False                      # anchored → it clouds instead
    return _trust_gate(finding, include_unverified=include_unverified)


def is_inked(finding: Finding, *, include_unverified: bool) -> bool:
    """Whether the finding lands on the PDF at all (cloud or margin callout)."""
    return is_cloudable(finding, include_unverified=include_unverified) or (
        is_margin_callout(finding, include_unverified=include_unverified)
    )


def ink_disposition(
    finding: Finding, *, include_unverified: bool, ink_rejected: bool = False
) -> str:
    """How the run accounts for one ledger entry (Part III's coverage tally).

    ``"cloud"`` — anchored, drawn as a Square; ``"margin"`` — rect-less, drawn
    as a margin callout; ``"rejected"`` — verifier-contradicted, listed in the
    index's rejected section (and inked grey when ``ink_rejected``); ``"gated"``
    — suppressed by the opt-in verified-&-deterministic-only mode. Under the
    exhaustive default (``include_unverified=True``) every entry is exactly one
    of cloud / margin / rejected — the §18 coverage assertion.
    """
    if _status(finding) == "REJECTED":
        return "rejected"
    if is_cloudable(finding, include_unverified=include_unverified):
        return "cloud"
    if is_margin_callout(finding, include_unverified=include_unverified):
        return "margin"
    return "gated"


def _is_unverified(finding: Finding) -> bool:
    return _status(finding) not in _TRUSTED


def _color(finding: Finding) -> tuple[float, float, float]:
    if (finding.category or "").lower() == "question":
        return _QUESTION_COLOR
    return _SEVERITY_COLORS.get((finding.severity or "").lower(), _DEFAULT_COLOR)


def _annot_content(
    finding: Finding, *, unverified: bool, rejected: bool = False, place: str = ""
) -> str:
    """The popup comment — exhaustive and descriptive (Phase 15 template).

    Order: the finding itself first (Revu's Markups List previews the first
    line), then the verbatim quote, cross-sheet pointers, verification, refs +
    citation-check verdict, provenance, the reproduced flag (only when it
    carries signal), the evidence filename, and the ids. ``place`` is the §18
    placement prefix for margin callouts (``[SHEET]`` / ``[UNANCHORED]``) — for a
    FreeText annot ``/Contents`` *is* the displayed text, so the prefix must live
    here to be visible on the box.
    """
    head = f"{finding.qc_id}: " if finding.qc_id else ""
    lines = [f"{head}{finding.text.strip()}"]
    quote = finding.source_quote.strip()
    if quote:
        lines.append(f'Quote: "{quote}"')
    for leg in getattr(finding, "also_on", None) or []:
        lq = f': "{leg.source_quote.strip()}"' if leg.source_quote.strip() else ""
        pointer = f"Conflicts with {leg.sheet_id}{lq}"
        if finding.qc_id:
            pointer += f" — see {finding.qc_id} there"
        lines.append(pointer)
    v = getattr(finding, "verification", None)
    if v is not None:
        lines.append(f"Verification: {v.status}" + (f" — {v.note}" if v.note else ""))
    if finding.refs:
        lines.append("Refs: " + ", ".join(str(r) for r in finding.refs))
    citation = getattr(finding, "citation", None)
    if citation is not None and citation.status != "UNCHECKED":
        cite = f"Citation check: {citation.status}"
        if citation.note:
            cite += f" — {citation.note}"
        if citation.edition_notes:
            cite += f" (editions: {citation.edition_notes})"
        lines.append(cite)
    sources = getattr(finding, "sources", None) or []
    if sources:
        from .ledger import provenance_label

        lines.append(f"Sources: {provenance_label(sources)}")
    if not getattr(finding, "reproduced", True):
        lines.append("Reproduced: no (seen in a single read)")
    if v is not None and v.evidence_png:
        lines.append(f"Evidence: {v.evidence_png}")
    lines.append(f"Finding ID: {finding.id}")
    content = "\n".join(lines)
    trust = "[REJECTED] " if rejected else ("[UNVERIFIED] " if unverified else "")
    placement = f"{place} " if place else ""
    return f"{trust}{placement}{content}"


# --------------------------------------------------------------------------- #
# Clear-margin-band computation (pure — unit-testable without a PDF)
# --------------------------------------------------------------------------- #


def find_clear_band(
    words: list[Any],
    page_w: float,
    page_h: float,
    *,
    max_height: float = 170.0,
) -> tuple[float, float, float, float]:
    """The largest text-free horizontal band inside the sheet border.

    Scans the word rectangles' vertical extents and returns the tallest gap —
    ``(x0, y0, x1, y1)`` in top-left-origin points, inset from the page edges and
    capped at ``max_height``. With no words (a raster sheet, or no geometry
    retained) it falls back to a bottom strip. Pure over the plain word tuples,
    so the placement rule is testable without PyMuPDF.
    """
    inset_x = 0.03 * page_w
    inset_y = 0.02 * page_h
    top, bottom = inset_y, page_h - inset_y

    intervals: list[tuple[float, float]] = []
    for w in words or []:
        y0, y1 = float(w[1]), float(w[3])
        if y1 <= top or y0 >= bottom:
            continue
        intervals.append((max(y0, top), min(y1, bottom)))
    if not intervals:
        band_h = min(max_height, max(40.0, 0.1 * page_h))
        return (inset_x, bottom - band_h, page_w - inset_x, bottom)

    intervals.sort()
    merged: list[list[float]] = [list(intervals[0])]
    for y0, y1 in intervals[1:]:
        if y0 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], y1)
        else:
            merged.append([y0, y1])

    # Candidate gaps: above the first block, between blocks, below the last.
    gaps: list[tuple[float, float]] = []
    prev = top
    for y0, y1 in merged:
        if y0 > prev:
            gaps.append((prev, y0))
        prev = max(prev, y1)
    if bottom > prev:
        gaps.append((prev, bottom))

    if not gaps:
        band_h = min(max_height, 60.0)
        return (inset_x, bottom - band_h, page_w - inset_x, bottom)

    g0, g1 = max(gaps, key=lambda g: g[1] - g[0])
    pad = min(4.0, (g1 - g0) / 10.0)
    y0 = g0 + pad
    y1 = min(g1 - pad, y0 + max_height)
    return (inset_x, y0, page_w - inset_x, y1)


def _tile_centroid(
    tile: list[int] | None, meta: dict | None
) -> tuple[float, float] | None:
    """The reported tile's centroid in page points, when geometry is available."""
    if not tile or not meta:
        return None
    rows = int(meta.get("rows", 0) or 0)
    cols = int(meta.get("cols", 0) or 0)
    w = float(meta.get("page_width_pt", 0.0) or 0.0)
    h = float(meta.get("page_height_pt", 0.0) or 0.0)
    if rows <= 0 or cols <= 0 or w <= 0 or h <= 0:
        return None
    overlap = float(meta.get("overlap_frac", tiling.DEFAULT_OVERLAP_FRAC))
    try:
        row, col = int(tile[0]), int(tile[1])
        for tr in tiling.tile_rects(w, h, rows=rows, cols=cols, overlap_frac=overlap):
            if tr.row == row and tr.col == col:
                return ((tr.x0 + tr.x1) / 2.0, (tr.y0 + tr.y1) / 2.0)
    except Exception:  # noqa: BLE001 - a bad tile never sinks the callout
        return None
    return None


# --------------------------------------------------------------------------- #
# View→page transform (Phase 19): finding rects are in PAGE_VIEW_V2 space; the
# PyMuPDF annotation/link APIs place ink in the page's un-rotated, CropBox-relative
# space. All layout math below is done in view space (natural — it matches the
# model's frame and reading order), then each final rect/point is transformed here,
# once, right before it is drawn. Identity on an un-rotated page.
# --------------------------------------------------------------------------- #


def _derotate_rect(page: "pymupdf.Page", view_rect: Any) -> "pymupdf.Rect":
    """A PAGE_VIEW_V2 rect → this page's un-rotated (annotation) space, normalized."""
    r = pymupdf.Rect(
        float(view_rect[0]), float(view_rect[1]), float(view_rect[2]), float(view_rect[3])
    ) * page.derotation_matrix
    r.normalize()
    return r


def _derotate_point(page: "pymupdf.Page", x: float, y: float) -> "pymupdf.Point":
    """A PAGE_VIEW_V2 point → this page's un-rotated (annotation) space."""
    return pymupdf.Point(float(x), float(y)) * page.derotation_matrix


# --------------------------------------------------------------------------- #
# Drawing (each helper returns how many annots it added)
# --------------------------------------------------------------------------- #


def _add_qc_tag(
    page: "pymupdf.Page", view_rect: "pymupdf.Rect", finding: Finding, *, author: str
) -> "int | None":
    """A small FreeText tag with the finding's QC number beside its markup.

    ``view_rect`` is the finding's cloud rectangle in PAGE_VIEW_V2 space; the tag is
    laid out relative to it in view space (``page.rect`` dims are view dims), then
    transformed to page space for drawing so it lands correctly on a rotated sheet.
    Returns the tag annot's xref (for stamping), or ``None`` when the finding has
    no QC number and therefore no tag.
    """
    if not finding.qc_id:
        return None
    color = _color(finding)
    tag_w = 6.0 * len(finding.qc_id) + 8.0
    x0 = max(2.0, min(view_rect.x0, page.rect.width - tag_w - 2.0))
    y0 = view_rect.y0 - _TAG_HEIGHT - 2.0
    if y0 < 2.0:
        y0 = min(view_rect.y1 + 2.0, page.rect.height - _TAG_HEIGHT - 2.0)
    tag_rect = _derotate_rect(page, (x0, y0, x0 + tag_w, y0 + _TAG_HEIGHT))
    annot = page.add_freetext_annot(
        tag_rect, finding.qc_id,
        fontsize=_TAG_FONTSIZE, text_color=color, fill_color=(1, 1, 1),
        rotate=int(page.rotation or 0),
    )
    annot.set_info(title=author, subject="QC tag", content=finding.qc_id)
    # No border_color: PyMuPDF rejects it on plain (non-rich) FreeText annots —
    # the severity-colored text itself is the tag's legend.
    annot.update()
    return annot.xref


def _add_cloud(
    page: "pymupdf.Page", finding: Finding, *, unverified: bool, author: str,
    rejected: bool = False,
) -> "list[tuple[str, int]]":
    """The finding's Square annot + its QC tag; returns ``[(component, xref), …]``.

    Style (Phase 15): DETERMINISTIC findings draw a **solid** border (the host
    computed them — no cloud theatrics), model findings a revision cloud, and
    opted-in unverified findings a dashed border. An opted-in **rejected**
    finding (§18's ``--ink-rejected``) draws grey and dashed with a
    ``[REJECTED]`` popup prefix — visibly struck, never mistaken for a live
    finding. The ``cloud`` component is mandatory; the ``tag`` is optional (only
    when the finding carries a QC number).
    """
    view_rect = pymupdf.Rect(*finding.anchor.rect_pdf)
    annot = page.add_rect_annot(_derotate_rect(page, view_rect))
    annot.set_colors(stroke=_REJECTED_COLOR if rejected else _color(finding))
    try:
        if rejected or unverified:
            annot.set_border(width=_BORDER_WIDTH, dashes=[4, 3])   # dashed = tentative/struck
        elif _status(finding) == "DETERMINISTIC":
            annot.set_border(width=_BORDER_WIDTH)                   # solid = computed
        else:
            annot.set_border(width=_BORDER_WIDTH, clouds=2)         # cloud = model finding
    except Exception:  # noqa: BLE001 - library-version variance -> plain rect border
        pass
    annot.set_info(
        title=author,
        subject=finding.category,
        content=_annot_content(finding, unverified=unverified, rejected=rejected),
    )
    # `update()` builds the appearance stream (/AP); without it some viewers draw
    # nothing. This is the whole reason PyMuPDF is used here (see module docstring).
    annot.update()
    components: list[tuple[str, int]] = [("cloud", annot.xref)]
    tag_xref = _add_qc_tag(page, view_rect, finding, author=author)
    if tag_xref is not None:
        components.append(("tag", tag_xref))
    return components


def _add_margin_callouts(
    page: "pymupdf.Page",
    pairs: "list[tuple[Finding, MarkupPlacement]]",
    *,
    meta: dict | None,
    author: str,
) -> "dict[str, list[tuple[str, int]]]":
    """Sheet-level / absence findings as FreeText boxes stacked in the clear band.

    Boxes fill the band left→right, wrapping rows; each carries the full popup
    content and, when the finding reported a tile, a leader Line annot with an
    arrow from the box to that tile's centroid. Returns ``{placement_id:
    [(component, xref), …]}`` — the ``callout`` component is mandatory; the
    ``leader`` is optional.
    """
    drawn: dict[str, list[tuple[str, int]]] = {}
    if not pairs:
        return drawn
    words = list((meta or {}).get("words") or [])
    page_w, page_h = page.rect.width, page.rect.height
    bx0, by0, bx1, _by1 = find_clear_band(words, page_w, page_h)

    page_bottom = page_h - 2.0
    x = bx0
    # First row: the band top, pulled up if the band is shallower than a box.
    first_row_y = min(by0, max(2.0, page_bottom - _CALLOUT_H))
    y = first_row_y
    stacking_up = False
    for finding, placement in pairs:
        if x + _CALLOUT_W > bx1:                      # wrap to the next row
            x = bx0
            if not stacking_up:
                nxt = y + _CALLOUT_H + _CALLOUT_GAP
                if nxt + _CALLOUT_H <= page_bottom:
                    y = nxt
                else:
                    # No room below the band: stack upward from the band top so
                    # every box stays on the visible page. Off-page ink would
                    # pass the annot count but be invisible to the reviewer —
                    # the one failure this feature exists to avoid. Upward rows
                    # may overlap sheet content (visible beats hidden); log it.
                    stacking_up = True
                    y = first_row_y
                    _log.info(
                        "margin band full; stacking callouts upward on the page"
                    )
            if stacking_up:
                y = max(2.0, y - (_CALLOUT_H + _CALLOUT_GAP))
        box = pymupdf.Rect(x, y, x + _CALLOUT_W, y + _CALLOUT_H)   # PAGE_VIEW_V2 space
        rejected = _status(finding) == "REJECTED"
        unverified = _is_unverified(finding) and not rejected
        color = _REJECTED_COLOR if rejected else _color(finding)
        # Placement prefix (§18): sheet-level absences read [SHEET]; a quote that
        # matched nothing reads [UNANCHORED] — the flagged-loudly hallucination
        # signal, on the page but never dressed as a placed finding. For FreeText
        # /Contents IS the displayed text, so the prefixed content set below is
        # exactly what the box shows.
        place = "[SHEET]" if (finding.anchor_hint or "").upper() == "SHEET" else "[UNANCHORED]"
        content = _annot_content(
            finding, unverified=unverified, rejected=rejected, place=place
        )
        components = drawn.setdefault(placement.placement_id, [])
        # Severity-colored text carries the legend (PyMuPDF rejects border_color
        # on plain FreeText annots); unverified/rejected callouts dash the border.
        # ``rotate=page.rotation`` keeps the text upright on a rotated sheet; the
        # box is transformed view→page so it lands in the computed clear band.
        annot = page.add_freetext_annot(
            _derotate_rect(page, box), content[:220],
            fontsize=7.5, text_color=color, fill_color=(1.0, 1.0, 0.92),
            rotate=int(page.rotation or 0),
        )
        try:
            if unverified or rejected:
                annot.set_border(width=1.0, dashes=[4, 3])
        except Exception:  # noqa: BLE001
            pass
        annot.set_info(title=author, subject=finding.category, content=content)
        annot.update()
        components.append(("callout", annot.xref))

        centroid = _tile_centroid(finding.tile, meta)
        if centroid is not None:
            try:
                start_v = ((box.x0 + box.x1) / 2.0, box.y0 if centroid[1] < box.y0 else box.y1)
                start = _derotate_point(page, start_v[0], start_v[1])
                line = page.add_line_annot(start, _derotate_point(page, centroid[0], centroid[1]))
                line.set_colors(stroke=color)
                try:
                    line.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
                except Exception:  # noqa: BLE001 - line-end styles vary by version
                    pass
                line.set_info(title=author, subject="QC leader", content=finding.qc_id or "")
                line.update()
                components.append(("leader", line.xref))
            except Exception:  # noqa: BLE001 - a failed leader never drops the box
                _log.warning("could not draw leader line for %s", finding.id)

        x += _CALLOUT_W + _CALLOUT_GAP
    return drawn


# --------------------------------------------------------------------------- #
# Index + appendix pages
# --------------------------------------------------------------------------- #


def _status_label(finding: Finding) -> str:
    return _status(finding)


def _index_groups(
    pairs: "list[tuple[Finding, MarkupPlacement]]",
) -> "tuple[list, list, list]":
    """``(inked, rejected, gated)`` (finding, placement) rows in QC-number order.

    The main table lists what's on paper; the rejected section (§18) and the
    "Not inked by operator gate" section (§6.4) make the verifier-contradicted and
    the conservatively-gated findings *visible* on the index — nothing is ever
    silently absent from the record. A gated finding's index row is its **sole
    artifact**, so it must exist and be reconciled (a bare no-ink status is
    insufficient).
    """
    def _order(items: list) -> list:
        return sorted(items, key=lambda fp: (fp[0].qc_id or "~", fp[0].id))

    inked, rejected, gated = [], [], []
    for finding, placement in pairs:
        if placement.expected == "GATED_INDEX":
            gated.append((finding, placement))
        elif _status(finding) == "REJECTED":
            rejected.append((finding, placement))
        elif placement.expected in ("CLOUD", "MARGIN", "REVIEW_NOTES"):
            inked.append((finding, placement))
    return _order(inked), _order(rejected), _order(gated)


def _insert_index_pages(
    doc: "pymupdf.Document",
    inked: list,
    rejected: list,
    gated: list,
    *,
    run_id: str,
    author: str,
) -> int:
    """Insert the findings index at the front of ``doc``; return pages inserted.

    Every finding row carries a GOTO link to its finding's page + rectangle.
    ``rejected`` entries follow the main table under a "Rejected by verification"
    heading, and ``gated`` entries under "Not inked by operator gate"; both carry
    the same page links. Link targets are offset by the number of index pages,
    which is computed **before** any page is inserted (inserting at the front
    shifts every original page down).

    Each generated index page is stamped analyzer-owned (:data:`_INDEX_PAGE_KEY`
    == ``run_id``), and the **index-only** placements it hosts (REJECTED_INDEX /
    GATED_INDEX rows — the ones whose only artifact is the index) are recorded in
    :data:`_INDEX_ROWS_KEY` as ``pid@target`` so reconciliation can prove each
    row exists and links to the right page.
    """
    # A uniform row stream ("heading" rows carry no link) paginates the main
    # table and the two trailing sections together. ``index_only`` marks the rows
    # whose sole artifact is this index row (so reconciliation must find them).
    rows: list[tuple[str, Any, bool]] = [("entry", fp, False) for fp in inked]
    if rejected:
        rows.append(("heading", f"Rejected by verification ({len(rejected)})", False))
        rows.extend(
            ("rejected", fp, fp[1].expected == "REJECTED_INDEX") for fp in rejected
        )
    if gated:
        rows.append(("heading", f"Not inked by operator gate ({len(gated)})", False))
        rows.extend(("gated", fp, True) for fp in gated)
    if not rows:
        return 0
    n_pages = (len(rows) + _INDEX_ROWS_PER_PAGE - 1) // _INDEX_ROWS_PER_PAGE

    # Insert EVERY index page before drawing any rows: link targets are numbered
    # for the final document, so drawing while later index pages are still
    # missing would make those targets fail the bounds guard and silently drop
    # the first page's links on a multi-page index. Pages are re-fetched by
    # index below — inserting a page invalidates previously-held Page objects.
    for i in range(n_pages):
        doc.new_page(pno=i, width=_INDEX_PAGE_W, height=_INDEX_PAGE_H)
    for i in range(n_pages):
        page = doc[i]
        title = INDEX_PAGE_LABEL + (f"  (page {i + 1}/{n_pages})" if n_pages > 1 else "")
        page.insert_text((36, 42), title, fontsize=13, fontname="hebo", color=(0.1, 0.1, 0.1))
        page.insert_text(
            (36, 60),
            f"Author: {author} - draft review; every row links to its markup.",
            fontsize=8, color=(0.35, 0.35, 0.35),
        )
        # Column headers.
        y = _INDEX_TOP - 8
        for x, label in ((36, "ID"), (95, "Sheet"), (210, "Sev"), (258, "Status"), (340, "Finding")):
            page.insert_text((x, y), label, fontsize=8, fontname="hebo", color=(0.25, 0.25, 0.25))

        batch = rows[i * _INDEX_ROWS_PER_PAGE:(i + 1) * _INDEX_ROWS_PER_PAGE]
        # "pid@target@rowY" for index-only placements here. rowY is the row's link
        # ``from``-rect top — unique per row on the page (rows are one line apart),
        # so reconciliation matches each placement to *its own* row/link, never to
        # any link that merely happens to share the target page (link custom keys
        # do not survive save, but the link's /Rect does).
        index_only_rows: list[str] = []
        y = _INDEX_TOP + 4
        for kind, payload, index_only in batch:
            if kind == "heading":
                page.insert_text((36, y), str(payload), fontsize=9, fontname="hebo",
                                 color=(0.3, 0.3, 0.3))
                y += _INDEX_ROW_H
                continue
            finding, placement = payload
            struck = kind in ("rejected", "gated")
            color = _REJECTED_COLOR if struck else _color(finding)
            text_color = _REJECTED_COLOR if struck else (0, 0, 0)
            page.insert_text((36, y), finding.qc_id or "—", fontsize=8, fontname="hebo", color=color)
            page.insert_text((95, y), (finding.sheet_id or "")[:20], fontsize=8, color=text_color)
            page.insert_text((210, y), (finding.severity or "")[:6], fontsize=8, color=color)
            page.insert_text((258, y), _status_label(finding)[:13], fontsize=8, color=text_color)
            text = finding.text.strip().replace("\n", " ")
            if len(text) > 62:
                text = text[:59] + "..."
            page.insert_text((340, y), text, fontsize=8, color=text_color)

            target_page = int(finding.page_index) + n_pages
            rect = getattr(finding.anchor, "rect_pdf", None) if finding.anchor else None
            if 0 <= target_page < doc.page_count:
                # The destination rect is in PAGE_VIEW_V2 space; a GOTO target lands
                # in the target page's un-rotated space, so derotate the corner with
                # that page's own matrix (identity on an un-rotated page).
                to = pymupdf.Point(36, 36)
                if rect:
                    to = _derotate_point(doc[target_page], rect[0], rect[1])
                row_top = y - 9
                page.insert_link({
                    "kind": pymupdf.LINK_GOTO,
                    "from": pymupdf.Rect(34, row_top, _INDEX_PAGE_W - 34, y + 3),
                    "page": target_page,
                    "to": to,
                    "zoom": 0,
                })
                if index_only:
                    index_only_rows.append(
                        f"{placement.placement_id}@{target_page}@{int(round(row_top))}"
                    )
            y += _INDEX_ROW_H

        # Stamp this page analyzer-owned and record its index-only rows so
        # reconciliation matches them by placement id (not by scanning text).
        doc.xref_set_key(page.xref, _INDEX_PAGE_KEY, f"({_safe_pdf_string(run_id)})")
        if index_only_rows:
            doc.xref_set_key(
                page.xref, _INDEX_ROWS_KEY,
                f"({_safe_pdf_string(';'.join(index_only_rows))})",
            )
    return n_pages


def _insert_appendix_page(
    doc: "pymupdf.Document", audit_stats: dict | None, *, author: str
) -> None:
    """The optional 'checked and consistent' page at the end of the document."""
    stats = audit_stats or {}
    page = doc.new_page(width=_INDEX_PAGE_W, height=_INDEX_PAGE_H)
    page.insert_text((36, 42), APPENDIX_PAGE_LABEL, fontsize=13, fontname="hebo", color=(0.1, 0.1, 0.1))
    page.insert_text(
        (36, 60),
        f"Author: {author} - deterministic checks that passed (the balance column).",
        fontsize=8, color=(0.35, 0.35, 0.35),
    )
    lines: list[str] = []
    checked = int(stats.get("arithmetic_checked", 0) or 0)
    if checked:
        matched = int(stats.get("arithmetic_matched", 0) or 0)
        lines.append(f"Numeric relationships checked: {matched} of {checked} checked out OK")
    resolved = int(stats.get("references_resolved", 0) or 0)
    if resolved:
        lines.append(f"Cross-references resolved in the set: {resolved}")
    if not lines:
        lines.append("No deterministic checks were recorded for this run.")
    y = 96
    for line in lines:
        # "[OK]" not "✓" — the Base-14 fonts insert_text uses have no U+2713 glyph.
        page.insert_text((36, y), "[OK]  " + line, fontsize=10, color=(0.1, 0.45, 0.2))
        y += 18


# --------------------------------------------------------------------------- #
# Whole-file writer
# --------------------------------------------------------------------------- #


def count_annotations(pdf_path: Path | str) -> int:
    """Total annotations across all pages of ``pdf_path`` (for the round-trip check)."""
    doc = pymupdf.open(str(pdf_path))
    try:
        return sum(1 for page in doc for _ in page.annots())
    finally:
        doc.close()


def count_annotations_by_type(pdf_path: Path | str) -> dict[str, int]:
    """Annotation counts keyed by type name (``Square`` / ``FreeText`` / ``Line``)."""
    out: dict[str, int] = {}
    doc = pymupdf.open(str(pdf_path))
    try:
        for page in doc:
            for annot in page.annots():
                name = annot.type[1] if isinstance(annot.type, (tuple, list)) else str(annot.type)
                out[name] = out.get(name, 0) + 1
        return out
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Reopen-and-reconcile: prove every planned placement in the saved artifact.
# --------------------------------------------------------------------------- #

_BUCKET_BY_KIND = {
    "CLOUD": "cloud",
    "MARGIN": "margin",
    "REVIEW_NOTES": "review_notes",
    "REJECTED_INDEX": "rejected",
    "GATED_INDEX": "gated",
}
# A placement skipped because its source changed mid-run (§10.6) is a distinct,
# operator-actionable failure — kept out of the generic ``failed`` bucket so the
# tally can say "N skipped (source changed)" and the operator knows to re-run.
_MUTATED_ERROR_PREFIX = "source changed"


def _receipt_for(
    placement: MarkupPlacement,
    out_name: str,
    found: "dict[str, dict[str, list[tuple[int, int]]]]",
    index_rows: "dict[str, tuple[int, int, int]]",
    index_page_links: "dict[int, list[tuple[int, int]]]",
) -> MarkupReceipt:
    """Turn one placement + what was found in the reopened file into a receipt."""
    pid = placement.placement_id
    if placement.expected in ("REJECTED_INDEX", "GATED_INDEX"):
        if pid not in index_rows:
            return MarkupReceipt(
                placement, "FAILED", output_pdf=out_name,
                error="expected index row not found in the saved PDF",
            )
        idx_pno, target, row_top = index_rows[pid]
        # This placement's OWN row must carry a GOTO link to the right page — a
        # link at this row's unique top position, not merely *some* link on the
        # page to the same target (which a sibling row could supply).
        links = index_page_links.get(idx_pno, [])
        if not any(abs(ly - row_top) <= 1 and lt == target for ly, lt in links):
            return MarkupReceipt(
                placement, "FAILED", output_pdf=out_name, output_page_index=idx_pno,
                error="index row present but its own GOTO link is missing/mis-targeted",
            )
        return MarkupReceipt(
            placement, "INDEXED", output_pdf=out_name, output_page_index=idx_pno,
            index_entry_ref=f"index_p{idx_pno}#{pid}",
            annotation_refs=[f"index_row:{target}@{row_top}"],
        )

    comps = found.get(pid, {})
    missing = [c for c in placement.required_components if not comps.get(c)]
    if missing:
        return MarkupReceipt(
            placement, "FAILED", output_pdf=out_name,
            error=f"missing mandatory component(s): {', '.join(missing)}",
        )
    dup = [c for c in placement.required_components if len(comps.get(c, [])) > 1]
    if dup:
        return MarkupReceipt(
            placement, "FAILED", output_pdf=out_name,
            error=f"duplicate mandatory component(s): {', '.join(dup)}",
        )
    refs = [f"{c}:{x}" for c, entries in comps.items() for (x, _pno) in entries]
    page_found = None
    for c in placement.required_components:
        if comps.get(c):
            page_found = comps[c][0][1]
            break
    return MarkupReceipt(
        placement, "WRITTEN", output_pdf=out_name, output_page_index=page_found,
        annotation_refs=refs,
    )


def _reconcile_pdf(
    out_path: Path, placements: list[MarkupPlacement], run_id: str
) -> list[MarkupReceipt]:
    """Reopen the saved PDF and reconcile it against the plan → one receipt each.

    Only marks stamped with **this** ``run_id`` count — a stamp left by an earlier
    review of the same source PDF (a different run id) and any annotation the
    analyzer never wrote (no stamp) are transparently ignored. Index-only rows are
    proven from the index page's stamped rows key plus a real GOTO link to the
    right page — never by scanning for a QC id in the page text (§13.4).
    """
    out_name = out_path.name
    prefix = run_id + "#"
    try:
        doc = pymupdf.open(str(out_path))
    except Exception as exc:  # noqa: BLE001 - an unreadable save proves nothing
        # Keep the raw exception (which may embed an absolute path) out of the
        # portable manifest — the receipt carries only the exception TYPE; the
        # full detail goes to the private diagnostics log.
        _log.warning("could not reopen %s to reconcile markups: %s", out_name, exc)
        return [
            MarkupReceipt(pl, "FAILED", output_pdf=out_name,
                          error=f"could not reopen saved PDF ({type(exc).__name__})")
            for pl in placements
        ]
    try:
        # Annotation-object component stamps: pid -> component -> [(xref, page)].
        found: dict[str, dict[str, list[tuple[int, int]]]] = {}
        for pno in range(doc.page_count):
            for annot in doc[pno].annots():
                stamp = _read_stamp(doc, annot.xref)
                if stamp is None:
                    continue
                pid, comp, _stamped_page = stamp
                if not pid.startswith(prefix):
                    continue                         # prior-run / unrelated ink
                found.setdefault(pid, {}).setdefault(comp, []).append((annot.xref, pno))

        # Index-only rows: pid -> (index_page, target_page, row_top); and every
        # GOTO link on each analyzer index page as (row_top, target) so each row is
        # matched to its OWN link by position, not to any link sharing the target.
        index_rows: dict[str, tuple[int, int, int]] = {}
        index_page_links: dict[int, list[tuple[int, int]]] = {}
        for pno in range(doc.page_count):
            page = doc[pno]
            kt, kv = doc.xref_get_key(page.xref, _INDEX_PAGE_KEY)
            if kt != "string" or kv != run_id:
                continue
            index_page_links[pno] = [
                (int(round(lk["from"].y0)), int(lk.get("page", -1)))
                for lk in page.get_links()
                if lk.get("kind") == pymupdf.LINK_GOTO and lk.get("from") is not None
            ]
            rt, rv = doc.xref_get_key(page.xref, _INDEX_ROWS_KEY)
            if rt == "string" and rv:
                for entry in rv.split(";"):
                    parts = entry.split("@")
                    if len(parts) == 3 and parts[0].startswith(prefix):
                        try:
                            index_rows[parts[0]] = (pno, int(parts[1]), int(parts[2]))
                        except ValueError:
                            pass

        expected_ids = {pl.placement_id for pl in placements}
        receipts = [
            _receipt_for(pl, out_name, found, index_rows, index_page_links)
            for pl in placements
        ]
        # Marks stamped with THIS run but absent from the plan — an orchestration
        # bug, not pre-existing ink; each becomes a FAILED receipt so coverage
        # cannot report clean (§13.4/§13.5).
        for pid in sorted((set(found) | set(index_rows)) - expected_ids):
            receipts.append(MarkupReceipt(
                MarkupPlacement(
                    run_id=run_id, placement_id=pid, finding_id="", qc_id="",
                    scope="SOURCE", source_id="", page_index=-1, leg_id="", expected="",
                ),
                "FAILED", output_pdf=out_name,
                error="unexpected analyzer mark not in the placement plan",
            ))
        return receipts
    finally:
        doc.close()


def _coverage_status(
    placements: list[MarkupPlacement], receipts: list[MarkupReceipt]
) -> str:
    """COMPLETE only when every placement has exactly one successful receipt and
    there are no missing / unexpected / duplicate / failed receipts (§13.5)."""
    expected_ids = {pl.placement_id for pl in placements}
    per_id: dict[str, list[MarkupReceipt]] = {}
    for r in receipts:
        per_id.setdefault(r.placement.placement_id, []).append(r)
    missing = expected_ids - set(per_id)
    unexpected = set(per_id) - expected_ids
    duplicates = [pid for pid in expected_ids if len(per_id.get(pid, [])) > 1]
    failed = any(r.status == "FAILED" for r in receipts)
    if missing or unexpected or duplicates or failed:
        return "INCOMPLETE"
    return "COMPLETE"


def _tally_from_receipts(receipts: list[MarkupReceipt]) -> dict[str, int]:
    """Receipt-derived run tally (never from intention): successes bucket by
    placement kind, failures into ``failed`` (§13.5)."""
    tally: dict[str, int] = {}
    for r in receipts:
        if r.status == "FAILED":
            bucket = "mutated" if r.error.startswith(_MUTATED_ERROR_PREFIX) else "failed"
        else:
            bucket = _BUCKET_BY_KIND.get(r.placement.expected)
        if bucket:
            tally[bucket] = tally.get(bucket, 0) + 1
    return tally


def _result_from_receipts(
    receipts: list[MarkupReceipt],
    placements: list[MarkupPlacement],
    reviewed_pdfs: list[Path],
) -> MarkupRunResult:
    return MarkupRunResult(
        reviewed_pdfs=list(reviewed_pdfs),
        placements=list(placements),
        receipts=list(receipts),
        coverage_status=_coverage_status(placements, receipts),
        tally=_tally_from_receipts(receipts),
    )


# --------------------------------------------------------------------------- #
# Whole-file writer (draw → stamp → save → reopen → reconcile)
# --------------------------------------------------------------------------- #


def _annotate_units(
    pdf_path: Path | str,
    pairs: "list[tuple[Finding, MarkupPlacement]]",
    out_path: Path | str,
    *,
    run_id: str,
    author: str = DEFAULT_AUTHOR,
    sheet_meta: dict[int, dict] | None = None,
    index_pages: bool = True,
    audit_stats: dict | None = None,
    include_appendix: bool = False,
) -> list[MarkupReceipt]:
    """Draw every ``(finding, placement)`` pair onto a copy of ``pdf_path``, stamp
    each component, save, then reopen and reconcile → one receipt per placement.

    Opens the *original* read-only and saves a **new** file (``out_path`` must
    differ from the source), so the source is never modified. Every drawn
    component is stamped with its placement id + component kind + final page, so
    the reopen step proves it exists (not merely that we intended it). Per-finding
    draw failures are caught and left un-stamped, so reconciliation reports them as
    FAILED (I-3: the file still ships for diagnosis).
    """
    src = Path(pdf_path)
    out = Path(out_path)
    if out.resolve() == src.resolve():
        raise ValueError("reviewed PDF path must differ from the source PDF")

    placements = [pl for _, pl in pairs]
    doc = pymupdf.open(str(src))
    # collected[placement_id] = [(component, xref, original_page_index), …]
    collected: dict[str, list[tuple[str, int, int]]] = {}
    try:
        page_count = doc.page_count
        callouts_by_page: dict[int, list[tuple[Finding, MarkupPlacement]]] = {}
        for finding, placement in pairs:
            kind = placement.expected
            if kind in ("REJECTED_INDEX", "GATED_INDEX"):
                continue                              # index-only; drawn by the index
            page_index = int(finding.page_index)
            if not (0 <= page_index < page_count):
                _log.warning(
                    "finding %s page_index %d out of range for %s — placement will fail",
                    finding.id, page_index, src.name,
                )
                continue                              # no components → FAILED at reconcile
            rejected = _status(finding) == "REJECTED"
            if kind == "CLOUD":
                try:
                    comps = _add_cloud(
                        doc[page_index], finding,
                        unverified=_is_unverified(finding) and not rejected,
                        author=author, rejected=rejected,
                    )
                    collected.setdefault(placement.placement_id, []).extend(
                        (c, x, page_index) for c, x in comps
                    )
                except Exception:  # noqa: BLE001 - one bad annot must not sink the file
                    _log.warning("could not add markup for finding %s", finding.id)
            else:                                     # MARGIN / REVIEW_NOTES
                callouts_by_page.setdefault(page_index, []).append((finding, placement))

        for page_index, group in sorted(callouts_by_page.items()):
            group.sort(key=lambda fp: (fp[0].qc_id or "~", fp[0].id))
            try:
                drawn = _add_margin_callouts(
                    doc[page_index], group,
                    meta=(sheet_meta or {}).get(page_index), author=author,
                )
                for pid, comps in drawn.items():
                    collected.setdefault(pid, []).extend(
                        (c, x, page_index) for c, x in comps
                    )
            except Exception:  # noqa: BLE001 - callouts must not sink the file
                _log.warning("could not add margin callouts on page %d", page_index)

        n_index = 0
        if index_pages:
            try:
                inked, rejected_rows, gated_rows = _index_groups(pairs)
                n_index = _insert_index_pages(
                    doc, inked, rejected_rows, gated_rows, run_id=run_id, author=author,
                )
            except Exception:  # noqa: BLE001 - the index must not sink the file
                _log.warning("could not build the findings index for %s", src.name)
        if include_appendix:
            try:
                _insert_appendix_page(doc, audit_stats, author=author)
            except Exception:  # noqa: BLE001
                _log.warning("could not build the appendix for %s", src.name)

        # Stamp each drawn component with its FINAL page — inserting the index at
        # the front shifted the originals down by ``n_index``. Xref numbers are
        # stable across page insertion, so stamping by xref is safe here.
        for pid, comps in collected.items():
            for component, xref, orig_page in comps:
                try:
                    _stamp_component(doc, xref, pid, component, orig_page + n_index)
                except Exception:  # noqa: BLE001 - a failed stamp → that placement fails
                    _log.warning("could not stamp %s for %s", component, pid)

        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()

    return _reconcile_pdf(out, placements, run_id)


def annotate_pdf(
    pdf_path: Path | str,
    findings: Iterable[Finding],
    out_path: Path | str,
    *,
    include_unverified: bool = False,
    ink_rejected: bool = False,
    author: str = DEFAULT_AUTHOR,
    sheet_meta: dict[int, dict] | None = None,
    index_pages: bool = True,
    audit_stats: dict | None = None,
    include_appendix: bool = False,
    artifact_run_id: str | None = None,
) -> MarkupRunResult:
    """Write a ``_reviewed`` copy of ``pdf_path`` with each finding drawn + proven.

    Each given finding becomes exactly one placement (no cross-sheet leg
    expansion — that is :func:`write_reviewed_pdfs`'s job, since legs land on other
    files). The copy is drawn, every mark stamped, saved, then reopened and
    reconciled; the returned :class:`MarkupRunResult` carries the per-placement
    receipts, the receipt-derived coverage status/tally, and (for the old int
    contract) ``.annots_written``. Opens the original read-only and saves a new
    file (``out_path`` must differ from the source). ``sheet_meta`` maps page
    index → the sheet's retained geometry for margin-band / leader placement.
    ``ink_rejected`` (§18) draws verifier-REJECTED findings grey and dashed;
    otherwise they carry no ink but get a reconciled index row. Additive and
    non-fatal (I-3): a per-finding failure becomes a FAILED receipt, not a raise.
    """
    run_id = artifact_run_id or new_artifact_run_id()
    ordinals = itertools.count()
    pairs = [
        (
            f,
            _make_placement(
                f, parent_id=f.id, leg_id=PRIMARY_LEG_ID, run_id=run_id,
                ordinal=next(ordinals),
                include_unverified=include_unverified, ink_rejected=ink_rejected,
            ),
        )
        for f in findings
    ]
    receipts = _annotate_units(
        pdf_path, pairs, out_path, run_id=run_id, author=author,
        sheet_meta=sheet_meta, index_pages=index_pages, audit_stats=audit_stats,
        include_appendix=include_appendix,
    )
    return _result_from_receipts(receipts, [pl for _, pl in pairs], [Path(out_path)])


def _expand_for_markup(findings: Iterable[Finding]) -> list[Finding]:
    """Explode a cross-sheet finding into one drawable finding per sheet it touches.

    Back-compat helper: returns the flat list of findings-to-draw (the primary
    plus one synthetic finding per ``also_on`` leg, each on its own sheet). The
    placement identity now lives on :class:`MarkupPlacement` (see
    :func:`_units_for_finding`); this flat view is preserved for callers/tests
    that only need the exploded findings. Synthetic legs live only here — never in
    the findings record.
    """
    run_id = new_artifact_run_id()
    ordinals = itertools.count()
    out: list[Finding] = []
    for f in findings:
        for unit in _units_for_finding(
            f, run_id=run_id, ordinals=ordinals,
            include_unverified=True, ink_rejected=False,
        ):
            out.append(unit.finding)
    return out


def write_reviewed_pdfs(
    findings: Iterable[Finding],
    pdf_paths: Iterable[Path | str],
    output_dir: Path | str,
    *,
    include_unverified: bool = False,
    ink_rejected: bool = False,
    author: str = DEFAULT_AUTHOR,
    geometries: Iterable[Any] | None = None,
    audit_stats: dict | None = None,
    include_appendix: bool = False,
    artifact_run_id: str | None = None,
    skip_source_ids: "set[str] | None" = None,
) -> MarkupRunResult:
    """Write one ``<stem>_reviewed.pdf`` per source with QC content, receipt-backed.

    Findings are matched to a source PDF by the host-owned ``source_id``
    (DA-001), so two inputs that share a basename each receive **only their own**
    findings — the reviewed copies are never cross-contaminated. (A finding that
    predates source ids — e.g. a hand-built test finding — falls back to matching
    by ``source_name``.) A source with no placement at all gets no reviewed copy;
    a source whose only findings are rejected / gated still gets one (their index
    rows keep them visible — §18: nothing is invisible). A cross-sheet finding is
    placed on **every** sheet it touches, each leg its own reconciled placement.

    Every planned placement is reconciled against the reopened output. The
    returned :class:`MarkupRunResult` carries the receipts, the receipt-derived
    coverage status/tally, and the reviewed-PDF paths. A source whose placements
    did not all succeed is written under an explicit ``…_reviewed_INCOMPLETE.pdf``
    name so it can never be mistaken for a complete reviewed set (§13.6). A source
    in ``skip_source_ids`` (its bytes changed mid-run, §10.6) is **not** reopened —
    every placement it touches gets a FAILED receipt and no ink is drawn on stale
    bytes.

    Output filenames stay friendly (``<stem>_reviewed.pdf``) when stems are
    unique; when two inputs share a stem, the colliding ones are disambiguated by
    their ``source_id`` (``<stem>__SRC-0002_reviewed.pdf``) — a deterministic,
    source-identifying suffix, not an order-dependent ``_2`` (§10.4).
    """
    run_id = artifact_run_id or new_artifact_run_id()
    skip = set(skip_source_ids or [])
    output_dir = Path(output_dir)
    pdf_paths = [Path(p) for p in pdf_paths]
    # Recompute the same host-owned ids list_sheets assigned (pure function of
    # the ordered path list), so a finding's source_id maps back to its file.
    path_to_sid = assign_source_ids(pdf_paths)

    all_placements: list[MarkupPlacement] = []
    all_receipts: list[MarkupReceipt] = []
    reviewed_pdfs: list[Path] = []

    # Split logical findings: a finding touching a changed source (primary or any
    # leg) is skipped entirely — every placement it plans gets a FAILED receipt
    # (source changed), and no stale ink is drawn (§10.6). Every writable unit is
    # also tracked flat, so a placement that routes to no input still gets a
    # terminal receipt below (never silently dropped — §13.5).
    units_by_sid: dict[str, list[_DrawUnit]] = {}
    units_by_name: dict[str, list[_DrawUnit]] = {}
    writable_units: list[_DrawUnit] = []
    ordinals = itertools.count()
    for finding in findings:
        units = _units_for_finding(
            finding, run_id=run_id, ordinals=ordinals,
            include_unverified=include_unverified, ink_rejected=ink_rejected,
        )
        if skip and _finding_touches(finding, skip):
            for unit in units:
                all_placements.append(unit.placement)
                all_receipts.append(MarkupReceipt(
                    unit.placement, "FAILED", output_pdf="",
                    error="source changed after analysis; markup skipped — "
                          "re-run to mark up the current revision",
                ))
            continue
        for unit in units:
            writable_units.append(unit)
            if unit.finding.source_id:
                units_by_sid.setdefault(unit.finding.source_id, []).append(unit)
            else:
                units_by_name.setdefault(unit.finding.source_name, []).append(unit)

    def _meta_of(geom: Any) -> dict:
        return {
            "words": getattr(geom, "words", None) or [],
            "rows": getattr(geom, "rows", 0),
            "cols": getattr(geom, "cols", 0),
            "overlap_frac": getattr(geom, "overlap_frac", tiling.DEFAULT_OVERLAP_FRAC),
            "page_width_pt": getattr(geom, "page_width_pt", 0.0),
            "page_height_pt": getattr(geom, "page_height_pt", 0.0),
        }

    meta_by_source_id: dict[str, dict[int, dict]] = {}
    meta_by_name: dict[str, dict[int, dict]] = {}
    for geom in geometries or []:
        ref = getattr(geom, "ref", None)
        if ref is None:
            continue
        if getattr(ref, "source_id", ""):
            meta_by_source_id.setdefault(ref.source_id, {})[int(ref.page_index)] = _meta_of(geom)
        else:
            meta_by_name.setdefault(ref.source_name, {})[int(ref.page_index)] = _meta_of(geom)

    # Which stems collide, so only those get the source-id-disambiguated name.
    stem_counts: dict[str, int] = {}
    for p in pdf_paths:
        stem_counts[p.stem] = stem_counts.get(p.stem, 0) + 1

    used_names: set[str] = set()
    done_keys: set[str] = set()          # a source's units are written exactly once
    for pdf_path in pdf_paths:
        sid = path_to_sid.get(str(pdf_path), "")
        key = sid or f"name::{pdf_path.name}"
        if key in done_keys:
            continue
        done_keys.add(key)
        # Source-id units route unambiguously. Name-fallback units (findings with
        # no host source_id) are *consumed once* via pop, so a finding is drawn on
        # exactly one source — never duplicated onto every input that happens to
        # share a basename (which would double-count the placement and falsely
        # report the run INCOMPLETE).
        units = list(units_by_sid.get(sid, [])) + units_by_name.pop(pdf_path.name, [])
        if not units:
            continue
        pairs = [(u.finding, u.placement) for u in units]
        if stem_counts.get(pdf_path.stem, 0) > 1 and sid:
            name = f"{pdf_path.stem}__{sid}_reviewed.pdf"
        else:
            name = f"{pdf_path.stem}_reviewed.pdf"
        n = 1
        while name in used_names:   # last-resort guard (e.g. no source_id to split them)
            n += 1
            name = f"{pdf_path.stem}_reviewed_{n}.pdf"
        used_names.add(name)
        out = output_dir / name
        sheet_meta = {
            **meta_by_name.get(pdf_path.name, {}),
            **meta_by_source_id.get(sid, {}),   # source-id meta wins per page
        }
        try:
            receipts = _annotate_units(
                pdf_path, pairs, out, run_id=run_id, author=author,
                sheet_meta=sheet_meta or None,
                audit_stats=audit_stats, include_appendix=include_appendix,
            )
        except Exception as exc:  # noqa: BLE001 - a source-level failure is non-fatal
            # Receipt error carries only the exception TYPE (the raw message may
            # embed an absolute source/temp path); full detail → private log.
            _log.warning("could not write reviewed PDF for %s: %s", pdf_path.name, exc)
            receipts = [
                MarkupReceipt(u.placement, "FAILED", output_pdf=name,
                              error=f"reviewed-PDF write failed ({type(exc).__name__})")
                for u in units
            ]
            all_receipts.extend(receipts)
            continue

        # A source whose placements did not all succeed is labeled INCOMPLETE so it
        # is never mistaken for a complete reviewed set (§13.6).
        incomplete = any(not r.ok for r in receipts)
        final_out = out
        if incomplete and out.exists():
            inc_name = name[:-4] + "_INCOMPLETE.pdf" if name.lower().endswith(".pdf") else name + "_INCOMPLETE"
            final_out = output_dir / inc_name
            try:
                out.replace(final_out)
                for r in receipts:
                    if r.output_pdf == name:
                        r.output_pdf = inc_name
            except OSError as exc:
                _log.warning("could not label incomplete reviewed PDF %s: %s", name, exc)
                final_out = out
        all_receipts.extend(receipts)
        reviewed_pdfs.append(final_out)

    # Every writable placement is expected; any that reached no input (a finding
    # or leg whose source_id/name matched no supplied PDF) gets an explicit FAILED
    # receipt, so an unroutable mark can never leave coverage reporting COMPLETE
    # (§13.5 — every expected placement has exactly one terminal outcome).
    all_placements.extend(u.placement for u in writable_units)
    receipted = {r.placement.placement_id for r in all_receipts}
    for unit in writable_units:
        if unit.placement.placement_id not in receipted:
            all_receipts.append(MarkupReceipt(
                unit.placement, "FAILED", output_pdf="",
                error="finding could not be routed to any supplied source PDF",
            ))

    return _result_from_receipts(all_receipts, all_placements, reviewed_pdfs)


# --------------------------------------------------------------------------- #
# Set-level review notes (Drawing_Set_Review_Notes.pdf) — Phase 22 §14.8.
# A synthesis conflict that names no in-set sheet belongs to no source PDF and so
# can never be clouded on a drawing. Instead each becomes one REVIEW_NOTES row on
# an analyzer-owned page of a dedicated, deterministic PDF: visible ink with its
# own artifact hash, placement ids, and reopened-and-reconciled receipts.
# --------------------------------------------------------------------------- #

SET_REVIEW_NOTES_FILENAME = "Drawing_Set_Review_Notes.pdf"
SET_REVIEW_NOTES_LABEL = "AI DRAFT REVIEW - SET-LEVEL / SHEET NOT IDENTIFIED"
_NOTE_LEFT = 36.0
_NOTE_TOP = 96.0
_NOTE_BOX_H = 60.0
_NOTE_GAP = 10.0
_NOTES_PER_PAGE = max(
    1, int((_INDEX_PAGE_H - _NOTE_TOP - _INDEX_BOTTOM_MARGIN) / (_NOTE_BOX_H + _NOTE_GAP))
)


def _is_set_level_finding(finding: Finding) -> bool:
    """A set-level finding: a SET-scoped item that belongs to no source sheet."""
    return (finding.anchor_hint or "").upper() in {"SET", "SET_INDEX"} and not finding.source_id


def write_set_review_notes_pdf(
    findings: Iterable[Finding],
    output_dir: Path | str,
    *,
    author: str = DEFAULT_AUTHOR,
    artifact_run_id: str | None = None,
) -> MarkupRunResult:
    """Write ``Drawing_Set_Review_Notes.pdf`` for the set-level findings (§14.8).

    Only set-level findings are written (anything else is ignored). Each becomes one
    stamped ``REVIEW_NOTES`` callout on an analyzer-owned page; the file is then
    reopened and every planned placement reconciled against what is actually found
    (Phase 21). An empty input yields an empty :class:`MarkupRunResult` (no file), so
    the caller lists the artifact only when it exists. A file whose placements did
    not all succeed is labeled ``…_INCOMPLETE.pdf`` (§13.6). Additive / non-fatal:
    a per-note draw failure becomes a FAILED receipt, never a raise.
    """
    items = [f for f in findings if _is_set_level_finding(f)]
    if not items:
        return _result_from_receipts([], [], [])

    run_id = artifact_run_id or new_artifact_run_id()
    output_dir = Path(output_dir)
    items.sort(key=lambda f: (f.qc_id or "~", f.id))     # deterministic order (I-7)
    ordinals = itertools.count()
    pairs: list[tuple[Finding, MarkupPlacement]] = []
    for f in items:
        pairs.append((f, MarkupPlacement(
            run_id=run_id,
            placement_id=f"{run_id}#{f.id}#{SET_LEG_ID}#{next(ordinals):05d}",
            finding_id=f.id, qc_id=f.qc_id, scope="SET", source_id="",
            page_index=-1, leg_id=SET_LEG_ID, expected="REVIEW_NOTES",
            required_components=list(REQUIRED_COMPONENTS["REVIEW_NOTES"]),
            severity=f.severity, source_name="",
        )))
    placements = [pl for _, pl in pairs]

    out = output_dir / SET_REVIEW_NOTES_FILENAME
    collected: dict[str, list[tuple[str, int, int]]] = {}
    doc = pymupdf.open()                                  # a fresh, analyzer-owned doc
    try:
        n_pages = (len(pairs) + _NOTES_PER_PAGE - 1) // _NOTES_PER_PAGE
        for pno in range(n_pages):
            page = doc.new_page(width=_INDEX_PAGE_W, height=_INDEX_PAGE_H)
            title = SET_REVIEW_NOTES_LABEL + (f"  (page {pno + 1}/{n_pages})" if n_pages > 1 else "")
            page.insert_text((_NOTE_LEFT, 42), title, fontsize=12, fontname="hebo", color=(0.1, 0.1, 0.1))
            page.insert_text(
                (_NOTE_LEFT, 62),
                f"Author: {author} - findings that belong to no single sheet in the set.",
                fontsize=8, color=(0.35, 0.35, 0.35),
            )
            batch = pairs[pno * _NOTES_PER_PAGE:(pno + 1) * _NOTES_PER_PAGE]
            y = _NOTE_TOP
            for finding, placement in batch:
                box = pymupdf.Rect(_NOTE_LEFT, y, _INDEX_PAGE_W - _NOTE_LEFT, y + _NOTE_BOX_H)
                content = (
                    f"{finding.qc_id or '-'}  [set-level / {finding.severity}]\n"
                    f"{finding.text.strip()}"
                )
                try:
                    annot = page.add_freetext_annot(
                        box, content[:400], fontsize=8,
                        text_color=_color(finding), fill_color=(1.0, 1.0, 0.92),
                    )
                    annot.set_info(title=author, subject="set-level review note", content=content)
                    annot.update()
                    collected.setdefault(placement.placement_id, []).append(
                        ("callout", annot.xref, pno)
                    )
                except Exception:  # noqa: BLE001 - one bad note must not sink the file
                    _log.warning("could not draw set-level note for %s", finding.id)
                y += _NOTE_BOX_H + _NOTE_GAP

        for pid, comps in collected.items():
            for component, xref, pno in comps:
                try:
                    _stamp_component(doc, xref, pid, component, pno)
                except Exception:  # noqa: BLE001 - a failed stamp → that placement fails
                    _log.warning("could not stamp set-level note %s", pid)

        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()

    receipts = _reconcile_pdf(out, placements, run_id)
    final_out = out
    if any(not r.ok for r in receipts) and out.exists():
        inc = output_dir / (SET_REVIEW_NOTES_FILENAME[:-4] + "_INCOMPLETE.pdf")
        try:
            out.replace(inc)
            for r in receipts:
                if r.output_pdf == out.name:
                    r.output_pdf = inc.name
            final_out = inc
        except OSError as exc:
            _log.warning("could not label incomplete set-level notes PDF: %s", exc)
    return _result_from_receipts(receipts, placements, [final_out])
