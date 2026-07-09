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
   Coordinates are **PyMuPDF top-left-origin points** — the exact space
   ``anchor.rect_pdf`` is already in (it came from ``get_text("words")`` via the
   resolver), so **no coordinate flip is needed** as long as everything stays in
   PyMuPDF. If anyone ever swaps to a bottom-left-origin PDF library, convert:
   ``y_pdf = page_height - y_mupdf`` (top/bottom swap), and account for a
   non-zero ``CropBox`` origin.

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

_log = get_logger()

# The annot author — provenance is unmistakable in the Markups List.
DEFAULT_AUTHOR = "Drawing Analyzer (AI review)"
# The index/appendix page label — same provenance rule. ASCII hyphen, not an
# em-dash: insert_text's Base-14 fonts have no U+2014 glyph.
INDEX_PAGE_LABEL = "AI DRAFT REVIEW - FINDINGS INDEX"
APPENDIX_PAGE_LABEL = "AI DRAFT REVIEW - CHECKED AND CONSISTENT"

# Verification statuses trusted enough to ink by default. Everything else
# (UNCERTAIN / SKIPPED) is "unverified" and only inked when opted in; REJECTED is
# never inked. (Part III later flips the default to ink-everything-but-rejected;
# that lands with the ledger phase, not here.)
_TRUSTED = frozenset({"VERIFIED", "DETERMINISTIC"})

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

    A ``REJECTED`` finding is never inked (a known-wrong cloud on an issued
    drawing is the one failure worse than a missing one); ``VERIFIED`` /
    ``DETERMINISTIC`` always are; the rest only when ``include_unverified``.
    """
    anchor = getattr(finding, "anchor", None)
    if anchor is None or anchor.rect_pdf is None:
        return False
    return _trust_gate(finding, include_unverified=include_unverified)


def is_margin_callout(finding: Finding, *, include_unverified: bool) -> bool:
    """Whether this finding gets a margin callout box (Phase 15).

    Sheet-level / absence findings (``anchor_hint="SHEET"``) have no rectangle to
    cloud — they are drawn as FreeText boxes stacked in the sheet's clear margin
    band instead, under the same trust gating as clouds.
    """
    anchor = getattr(finding, "anchor", None)
    if anchor is not None and anchor.rect_pdf is not None:
        return False                      # anchored → it clouds instead
    if (getattr(finding, "anchor_hint", "") or "").upper() != "SHEET":
        return False
    return _trust_gate(finding, include_unverified=include_unverified)


def is_inked(finding: Finding, *, include_unverified: bool) -> bool:
    """Whether the finding lands on the PDF at all (cloud or margin callout)."""
    return is_cloudable(finding, include_unverified=include_unverified) or (
        is_margin_callout(finding, include_unverified=include_unverified)
    )


def _is_unverified(finding: Finding) -> bool:
    return _status(finding) not in _TRUSTED


def _color(finding: Finding) -> tuple[float, float, float]:
    if (finding.category or "").lower() == "question":
        return _QUESTION_COLOR
    return _SEVERITY_COLORS.get((finding.severity or "").lower(), _DEFAULT_COLOR)


def _annot_content(finding: Finding, *, unverified: bool) -> str:
    """The popup comment — exhaustive and descriptive (Phase 15 template).

    Order: the finding itself first (Revu's Markups List previews the first
    line), then the verbatim quote, cross-sheet pointers, verification, refs +
    citation-check verdict, the reproduced flag (only when it carries signal),
    the evidence filename, and the ids.
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
    if not getattr(finding, "reproduced", True):
        lines.append("Reproduced: no (seen in a single read)")
    if v is not None and v.evidence_png:
        lines.append(f"Evidence: {v.evidence_png}")
    lines.append(f"Finding ID: {finding.id}")
    content = "\n".join(lines)
    return f"[UNVERIFIED] {content}" if unverified else content


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
# Drawing (each helper returns how many annots it added)
# --------------------------------------------------------------------------- #


def _add_qc_tag(
    page: "pymupdf.Page", rect: "pymupdf.Rect", finding: Finding, *, author: str
) -> int:
    """A small FreeText tag with the finding's QC number beside its markup."""
    if not finding.qc_id:
        return 0
    color = _color(finding)
    tag_w = 6.0 * len(finding.qc_id) + 8.0
    x0 = max(2.0, min(rect.x0, page.rect.width - tag_w - 2.0))
    y0 = rect.y0 - _TAG_HEIGHT - 2.0
    if y0 < 2.0:
        y0 = min(rect.y1 + 2.0, page.rect.height - _TAG_HEIGHT - 2.0)
    tag_rect = pymupdf.Rect(x0, y0, x0 + tag_w, y0 + _TAG_HEIGHT)
    annot = page.add_freetext_annot(
        tag_rect, finding.qc_id,
        fontsize=_TAG_FONTSIZE, text_color=color, fill_color=(1, 1, 1),
    )
    annot.set_info(title=author, subject="QC tag", content=finding.qc_id)
    # No border_color: PyMuPDF rejects it on plain (non-rich) FreeText annots —
    # the severity-colored text itself is the tag's legend.
    annot.update()
    return 1


def _add_cloud(
    page: "pymupdf.Page", finding: Finding, *, unverified: bool, author: str
) -> int:
    """The finding's Square annot + its QC tag; returns annots written.

    Style (Phase 15): DETERMINISTIC findings draw a **solid** border (the host
    computed them — no cloud theatrics), model findings a revision cloud, and
    opted-in unverified findings a dashed border.
    """
    rect = pymupdf.Rect(*finding.anchor.rect_pdf)
    annot = page.add_rect_annot(rect)
    annot.set_colors(stroke=_color(finding))
    try:
        if unverified:
            annot.set_border(width=_BORDER_WIDTH, dashes=[4, 3])   # dashed = tentative
        elif _status(finding) == "DETERMINISTIC":
            annot.set_border(width=_BORDER_WIDTH)                   # solid = computed
        else:
            annot.set_border(width=_BORDER_WIDTH, clouds=2)         # cloud = model finding
    except Exception:  # noqa: BLE001 - library-version variance -> plain rect border
        pass
    annot.set_info(
        title=author,
        subject=finding.category,
        content=_annot_content(finding, unverified=unverified),
    )
    # `update()` builds the appearance stream (/AP); without it some viewers draw
    # nothing. This is the whole reason PyMuPDF is used here (see module docstring).
    annot.update()
    return 1 + _add_qc_tag(page, rect, finding, author=author)


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
    bx0, by0, bx1, by1 = find_clear_band(words, page_w, page_h)

    written = 0
    x, y = bx0, by0
    for finding in findings:
        if x + _CALLOUT_W > bx1:                      # wrap to the next row
            x = bx0
            y += _CALLOUT_H + _CALLOUT_GAP
        if y + _CALLOUT_H > by1:                      # band full — keep stacking below,
            _log.info("margin band full on %s; callouts continue below it", page)
            by1 = y + _CALLOUT_H                      # honest: never silently drop ink
        box = pymupdf.Rect(x, y, x + _CALLOUT_W, y + _CALLOUT_H)
        unverified = _is_unverified(finding)
        color = _color(finding)
        prefix = "[UNVERIFIED] [SHEET] " if unverified else "[SHEET] "
        text = f"{prefix}{finding.qc_id + ': ' if finding.qc_id else ''}{finding.text.strip()}"
        # Severity-colored text carries the legend (PyMuPDF rejects border_color
        # on plain FreeText annots); unverified callouts also dash their border.
        annot = page.add_freetext_annot(
            box, text[:220],
            fontsize=7.5, text_color=color, fill_color=(1.0, 1.0, 0.92),
        )
        try:
            if unverified:
                annot.set_border(width=1.0, dashes=[4, 3])
        except Exception:  # noqa: BLE001
            pass
        annot.set_info(
            title=author, subject=finding.category,
            content=_annot_content(finding, unverified=unverified),
        )
        annot.update()
        written += 1

        centroid = _tile_centroid(finding.tile, meta)
        if centroid is not None:
            try:
                start = pymupdf.Point((box.x0 + box.x1) / 2.0, box.y0 if centroid[1] < box.y0 else box.y1)
                line = page.add_line_annot(start, pymupdf.Point(*centroid))
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


def _index_entries(findings: list[Finding], *, include_unverified: bool) -> list[Finding]:
    """The inked findings, in QC-number order (the index lists what's on paper)."""
    inked = [f for f in findings if is_inked(f, include_unverified=include_unverified)]
    return sorted(inked, key=lambda f: (f.qc_id or "~", f.id))


def _insert_index_pages(
    doc: "pymupdf.Document", entries: list[Finding], *, author: str
) -> int:
    """Insert the findings index at the front of ``doc``; return pages inserted.

    Every row carries a GOTO link to its finding's page + rectangle. Link targets
    are offset by the number of index pages, which is computed **before** any
    page is inserted (inserting at the front shifts every original page down).
    """
    if not entries:
        return 0
    n_pages = (len(entries) + _INDEX_ROWS_PER_PAGE - 1) // _INDEX_ROWS_PER_PAGE

    for i in range(n_pages):
        page = doc.new_page(pno=i, width=_INDEX_PAGE_W, height=_INDEX_PAGE_H)
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

        batch = entries[i * _INDEX_ROWS_PER_PAGE:(i + 1) * _INDEX_ROWS_PER_PAGE]
        y = _INDEX_TOP + 4
        for finding in batch:
            color = _color(finding)
            page.insert_text((36, y), finding.qc_id or "—", fontsize=8, fontname="hebo", color=color)
            page.insert_text((95, y), (finding.sheet_id or "")[:20], fontsize=8, color=(0, 0, 0))
            page.insert_text((210, y), (finding.severity or "")[:6], fontsize=8, color=color)
            page.insert_text((258, y), _status_label(finding)[:13], fontsize=8, color=(0, 0, 0))
            text = finding.text.strip().replace("\n", " ")
            if len(text) > 62:
                text = text[:59] + "..."
            page.insert_text((340, y), text, fontsize=8, color=(0, 0, 0))

            target_page = int(finding.page_index) + n_pages
            rect = getattr(finding.anchor, "rect_pdf", None) if finding.anchor else None
            to = pymupdf.Point(rect[0], rect[1]) if rect else pymupdf.Point(36, 36)
            if 0 <= target_page < doc.page_count:
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
    leaders. Per-finding failures are logged and skipped (I-3); after saving, the
    file is reopened and its annot count compared to what was written (a mismatch
    is logged, not raised).
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
            page_index = finding.page_index
            if not (0 <= page_index < page_count):
                if is_inked(finding, include_unverified=include_unverified):
                    _log.warning(
                        "finding %s page_index %d out of range for %s",
                        finding.id, page_index, src.name,
                    )
                continue
            if is_cloudable(finding, include_unverified=include_unverified):
                try:
                    written += _add_cloud(
                        doc[page_index], finding,
                        unverified=_is_unverified(finding), author=author,
                    )
                except Exception:  # noqa: BLE001 - one bad annot must not sink the file
                    _log.warning("could not add markup for finding %s", finding.id)
            elif is_margin_callout(finding, include_unverified=include_unverified):
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
                _insert_index_pages(
                    doc,
                    _index_entries(findings, include_unverified=include_unverified),
                    author=author,
                )
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
            sheet_id=f.sheet_id, source_name=f.source_name, page_index=f.page_index,
            source_quote=f.source_quote, tile=f.tile, anchor=f.anchor,
        )
        for i, leg in enumerate(legs):
            others = [primary_as_leg] + [l for j, l in enumerate(legs) if j != i]
            out.append(Finding(
                sheet_id=leg.sheet_id, source_name=leg.source_name,
                page_index=leg.page_index, category=f.category, severity=f.severity,
                text=f.text, source_quote=leg.source_quote, refs=list(f.refs),
                also_on=others, anchor=leg.anchor, verification=f.verification,
                qc_id=f.qc_id, citation=f.citation,
            ))
    return out


def write_reviewed_pdfs(
    findings: Iterable[Finding],
    pdf_paths: Iterable[Path | str],
    output_dir: Path | str,
    *,
    include_unverified: bool = False,
    author: str = DEFAULT_AUTHOR,
    geometries: Iterable[Any] | None = None,
    audit_stats: dict | None = None,
    include_appendix: bool = False,
) -> list[Path]:
    """Write one ``<stem>_reviewed.pdf`` per source PDF that has inked findings.

    Findings are matched to a source PDF by ``source_name`` (the file basename);
    a source with no inked finding gets no reviewed copy. A cross-sheet finding
    is inked on **every** sheet it touches (see :func:`_expand_for_markup`).
    ``geometries`` (the run's :class:`~drawing_analyzer.models.SheetGeometry`
    records) supply the word rectangles and grid used for margin-band placement
    and leader lines; ``audit_stats`` feeds the optional appendix page. Output
    filenames are de-duplicated (``_reviewed`` / ``_reviewed_2`` / …) so two
    inputs sharing a stem don't clobber each other. Returns the reviewed-PDF
    paths, in input order.
    """
    output_dir = Path(output_dir)
    by_source: dict[str, list[Finding]] = {}
    for finding in _expand_for_markup(findings):
        by_source.setdefault(finding.source_name, []).append(finding)

    meta_by_source: dict[str, dict[int, dict]] = {}
    for geom in geometries or []:
        ref = getattr(geom, "ref", None)
        if ref is None:
            continue
        meta_by_source.setdefault(ref.source_name, {})[int(ref.page_index)] = {
            "words": getattr(geom, "words", None) or [],
            "rows": getattr(geom, "rows", 0),
            "cols": getattr(geom, "cols", 0),
            "overlap_frac": getattr(geom, "overlap_frac", tiling.DEFAULT_OVERLAP_FRAC),
            "page_width_pt": getattr(geom, "page_width_pt", 0.0),
            "page_height_pt": getattr(geom, "page_height_pt", 0.0),
        }

    out_paths: list[Path] = []
    used_names: set[str] = set()
    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        sheet_findings = by_source.get(pdf_path.name, [])
        if not any(
            is_inked(f, include_unverified=include_unverified) for f in sheet_findings
        ):
            continue
        name = f"{pdf_path.stem}_reviewed.pdf"
        n = 1
        while name in used_names:
            n += 1
            name = f"{pdf_path.stem}_reviewed_{n}.pdf"
        used_names.add(name)
        out = output_dir / name
        annotate_pdf(
            pdf_path, sheet_findings, out,
            include_unverified=include_unverified, author=author,
            sheet_meta=meta_by_source.get(pdf_path.name),
            audit_stats=audit_stats, include_appendix=include_appendix,
        )
        out_paths.append(out)
    return out_paths
