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
memory, and saves a *new* ``_reviewed.pdf``. It self-checks by reopening and
counting annots (a mismatch is logged, never fatal — I-3).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import pymupdf  # AGPL-3.0 — see module docstring; the 2nd of two blessed importers.

from . import tiling
from .diagnostics import get_logger
from .models import ConflictLeg, Finding
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
) -> int:
    """A small FreeText tag with the finding's QC number beside its markup.

    ``view_rect`` is the finding's cloud rectangle in PAGE_VIEW_V2 space; the tag is
    laid out relative to it in view space (``page.rect`` dims are view dims), then
    transformed to page space for drawing so it lands correctly on a rotated sheet.
    """
    if not finding.qc_id:
        return 0
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
    return 1


def _add_cloud(
    page: "pymupdf.Page", finding: Finding, *, unverified: bool, author: str,
    rejected: bool = False,
) -> int:
    """The finding's Square annot + its QC tag; returns annots written.

    Style (Phase 15): DETERMINISTIC findings draw a **solid** border (the host
    computed them — no cloud theatrics), model findings a revision cloud, and
    opted-in unverified findings a dashed border. An opted-in **rejected**
    finding (§18's ``--ink-rejected``) draws grey and dashed with a
    ``[REJECTED]`` popup prefix — visibly struck, never mistaken for a live
    finding.
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
    return 1 + _add_qc_tag(page, view_rect, finding, author=author)


def _add_margin_callouts(
    page: "pymupdf.Page",
    findings: list[Finding],
    *,
    meta: dict | None,
    author: str,
) -> int:
    """Sheet-level / absence findings as FreeText boxes stacked in the clear band.

    Boxes fill the band left→right, wrapping rows; each carries the full popup
    content and, when the finding reported a tile, a leader Line annot with an
    arrow from the box to that tile's centroid. Returns annots written.
    """
    if not findings:
        return 0
    words = list((meta or {}).get("words") or [])
    page_w, page_h = page.rect.width, page.rect.height
    bx0, by0, bx1, _by1 = find_clear_band(words, page_w, page_h)

    written = 0
    page_bottom = page_h - 2.0
    x = bx0
    # First row: the band top, pulled up if the band is shallower than a box.
    first_row_y = min(by0, max(2.0, page_bottom - _CALLOUT_H))
    y = first_row_y
    stacking_up = False
    for finding in findings:
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
        written += 1

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
                written += 1
            except Exception:  # noqa: BLE001 - a failed leader never drops the box
                _log.warning("could not draw leader line for %s", finding.id)

        x += _CALLOUT_W + _CALLOUT_GAP
    return written


# --------------------------------------------------------------------------- #
# Index + appendix pages
# --------------------------------------------------------------------------- #


def _status_label(finding: Finding) -> str:
    return _status(finding)


def _index_entries(
    findings: list[Finding], *, include_unverified: bool
) -> tuple[list[Finding], list[Finding]]:
    """``(inked, rejected)`` in QC-number order.

    The main table lists what's on paper; the rejected list (§18) makes the
    verifier-contradicted findings *visible* on the index — nothing is ever
    silently absent from the record — even though they carry no ink by default.
    """
    def _order(fs: list[Finding]) -> list[Finding]:
        return sorted(fs, key=lambda f: (f.qc_id or "~", f.id))

    inked = [f for f in findings if is_inked(f, include_unverified=include_unverified)]
    rejected = [f for f in findings if _status(f) == "REJECTED"]
    return _order(inked), _order(rejected)


def _insert_index_pages(
    doc: "pymupdf.Document",
    entries: list[Finding],
    rejected: list[Finding],
    *,
    author: str,
) -> int:
    """Insert the findings index at the front of ``doc``; return pages inserted.

    Every finding row carries a GOTO link to its finding's page + rectangle.
    ``rejected`` entries follow the main table under a "Rejected by verification
    (n)" heading, with the same page links. Link targets are offset by the
    number of index pages, which is computed **before** any page is inserted
    (inserting at the front shifts every original page down).
    """
    # A uniform row stream ("heading" rows carry no link) paginates the main
    # table and the rejected section together.
    rows: list[tuple[str, Any]] = [("entry", f) for f in entries]
    if rejected:
        rows.append(("heading", f"Rejected by verification ({len(rejected)})"))
        rows.extend(("rejected", f) for f in rejected)
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
        y = _INDEX_TOP + 4
        for kind, payload in batch:
            if kind == "heading":
                page.insert_text((36, y), str(payload), fontsize=9, fontname="hebo",
                                 color=(0.3, 0.3, 0.3))
                y += _INDEX_ROW_H
                continue
            finding = payload
            struck = kind == "rejected"
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
                page.insert_link({
                    "kind": pymupdf.LINK_GOTO,
                    "from": pymupdf.Rect(34, y - 9, _INDEX_PAGE_W - 34, y + 3),
                    "page": target_page,
                    "to": to,
                    "zoom": 0,
                })
            y += _INDEX_ROW_H
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
) -> int:
    """Write a ``_reviewed`` copy of ``pdf_path`` with each inked finding drawn.

    Returns the number of annots written. Opens the *original* read-only and
    saves a **new** file (``out_path`` must differ from the source), so the source
    is never modified. ``sheet_meta`` maps page index → the sheet's retained
    geometry (``words`` / ``rows`` / ``cols`` / page size) for margin-band and
    leader placement; without it callouts fall back to a bottom strip and skip
    leaders. ``ink_rejected`` (§18) additionally draws verifier-REJECTED findings
    grey and dashed; by default they carry no ink but are listed on the index
    page's rejected section. Per-finding failures are logged and skipped (I-3);
    after saving, the file is reopened and its annot count compared to what was
    written (a mismatch is logged, not raised).
    """
    src = Path(pdf_path)
    out = Path(out_path)
    if out.resolve() == src.resolve():
        raise ValueError("reviewed PDF path must differ from the source PDF")

    findings = list(findings)
    doc = pymupdf.open(str(src))
    written = 0
    try:
        page_count = doc.page_count
        callouts_by_page: dict[int, list[Finding]] = {}
        for finding in findings:
            disposition = ink_disposition(
                finding, include_unverified=include_unverified, ink_rejected=ink_rejected
            )
            if disposition == "gated" or (disposition == "rejected" and not ink_rejected):
                continue
            page_index = finding.page_index
            if not (0 <= page_index < page_count):
                _log.warning(
                    "finding %s page_index %d out of range for %s",
                    finding.id, page_index, src.name,
                )
                continue
            rejected = disposition == "rejected"
            anchored = finding.anchor is not None and finding.anchor.rect_pdf is not None
            if disposition == "cloud" or (rejected and anchored):
                try:
                    written += _add_cloud(
                        doc[page_index], finding,
                        unverified=_is_unverified(finding) and not rejected,
                        author=author, rejected=rejected,
                    )
                except Exception:  # noqa: BLE001 - one bad annot must not sink the file
                    _log.warning("could not add markup for finding %s", finding.id)
            else:                                   # margin (or rect-less rejected)
                callouts_by_page.setdefault(page_index, []).append(finding)

        for page_index, group in sorted(callouts_by_page.items()):
            group.sort(key=lambda f: (f.qc_id or "~", f.id))
            try:
                written += _add_margin_callouts(
                    doc[page_index], group,
                    meta=(sheet_meta or {}).get(page_index), author=author,
                )
            except Exception:  # noqa: BLE001 - callouts must not sink the file
                _log.warning("could not add margin callouts on page %d", page_index)

        if index_pages:
            try:
                entries, rejected_entries = _index_entries(
                    findings, include_unverified=include_unverified
                )
                _insert_index_pages(doc, entries, rejected_entries, author=author)
            except Exception:  # noqa: BLE001 - the index must not sink the file
                _log.warning("could not build the findings index for %s", src.name)
        if include_appendix:
            try:
                _insert_appendix_page(doc, audit_stats, author=author)
            except Exception:  # noqa: BLE001
                _log.warning("could not build the appendix for %s", src.name)

        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()

    reopened = count_annotations(out)
    if reopened != written:
        _log.warning(
            "markup round-trip mismatch for %s: wrote %d, reopened %d",
            out.name, written, reopened,
        )
    return written


def _expand_for_markup(findings: Iterable[Finding]) -> list[Finding]:
    """Explode a cross-sheet finding into one cloud request per sheet it touches.

    A cross-sheet conflict must be clouded on **both** sheets (Phase 13). The
    primary finding clouds on its own sheet (its ``also_on`` drives the popup's
    cross-reference); each ``also_on`` leg becomes a synthetic finding placed on
    *its* sheet, inheriting the parent's category/severity/verification/**qc_id**
    (so gating is identical and both popups show the same review number, each
    cross-referencing the other) and carrying its own ``also_on`` pointing back at
    the primary and the sibling legs. A finding with no legs passes through
    unchanged. Synthetic legs live only here — never in the findings record — so
    counts/exports stay one-entry-per-conflict.
    """
    out: list[Finding] = []
    for f in findings:
        out.append(f)
        legs = getattr(f, "also_on", None) or []
        if not legs:
            continue
        primary_as_leg = ConflictLeg(
            sheet_id=f.sheet_id, source_name=f.source_name, source_id=f.source_id,
            page_index=f.page_index,
            source_quote=f.source_quote, tile=f.tile, anchor=f.anchor,
        )
        for i, leg in enumerate(legs):
            others = [primary_as_leg] + [l for j, l in enumerate(legs) if j != i]
            out.append(Finding(
                sheet_id=leg.sheet_id, source_name=leg.source_name,
                source_id=leg.source_id,
                page_index=leg.page_index, category=f.category, severity=f.severity,
                text=f.text, source_quote=leg.source_quote, refs=list(f.refs),
                also_on=others, anchor=leg.anchor, verification=f.verification,
                qc_id=f.qc_id, citation=f.citation, sources=list(f.sources),
            ))
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
) -> list[Path]:
    """Write one ``<stem>_reviewed.pdf`` per source PDF that has QC content.

    Findings are matched to a source PDF by the host-owned ``source_id``
    (DA-001), so two inputs that share a basename each receive **only their own**
    findings — the reviewed copies are never cross-contaminated. (A finding that
    predates source ids — e.g. a hand-built test finding — falls back to matching
    by ``source_name``.) A source with neither an inked finding nor a rejected
    one gets no reviewed copy (rejected-only sources still get one, so their
    index's rejected section keeps them visible — §18: nothing is invisible). A
    cross-sheet finding is inked on **every** sheet it touches (see
    :func:`_expand_for_markup`). ``geometries`` supply the word rectangles/grid
    for margin-band placement; ``audit_stats`` feeds the optional appendix.

    Output filenames stay friendly (``<stem>_reviewed.pdf``) when stems are
    unique; when two inputs share a stem, the colliding ones are disambiguated by
    their ``source_id`` (``<stem>__SRC-0002_reviewed.pdf``) — a deterministic,
    source-identifying suffix, not an order-dependent ``_2`` (§10.4). Returns the
    reviewed-PDF paths, in input order.
    """
    output_dir = Path(output_dir)
    pdf_paths = [Path(p) for p in pdf_paths]
    # Recompute the same host-owned ids list_sheets assigned (pure function of
    # the ordered path list), so a finding's source_id maps back to its file.
    path_to_sid = assign_source_ids(pdf_paths)

    by_source_id: dict[str, list[Finding]] = {}
    by_name: dict[str, list[Finding]] = {}   # fallback pool for source_id-less findings
    for finding in _expand_for_markup(findings):
        if finding.source_id:
            by_source_id.setdefault(finding.source_id, []).append(finding)
        else:
            by_name.setdefault(finding.source_name, []).append(finding)

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

    out_paths: list[Path] = []
    used_names: set[str] = set()
    for pdf_path in pdf_paths:
        sid = path_to_sid.get(str(pdf_path), "")
        sheet_findings = list(by_source_id.get(sid, [])) + list(by_name.get(pdf_path.name, []))
        has_ink = any(
            is_inked(f, include_unverified=include_unverified) for f in sheet_findings
        )
        has_rejected = any(_status(f) == "REJECTED" for f in sheet_findings)
        if not has_ink and not has_rejected:
            continue
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
        annotate_pdf(
            pdf_path, sheet_findings, out,
            include_unverified=include_unverified, ink_rejected=ink_rejected,
            author=author,
            sheet_meta=sheet_meta or None,
            audit_stats=audit_stats, include_appendix=include_appendix,
        )
        out_paths.append(out)
    return out_paths
