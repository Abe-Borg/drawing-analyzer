"""Markup writer: turn findings into a numbered, navigable, reviewed PDF.

This writes **real annotation objects** onto a ``<stem>_reviewed.pdf`` so the
result reads like a senior plan-review set (Phase 15):

- every inked finding carries a sequential **QC tag** (``QC-001`` …) — a small
  FreeText label beside its cloud in the severity color; the same number appears
  in the CSV, ``findings.json``, the HTML report, and the index page;
- **severity styling**: high = red, medium = orange, low / question = blue;
  DETERMINISTIC (auditor) findings draw a **solid** border, model findings a
  **revision cloud** (``clouds=2``), unverified findings **dashed** with a
  ``[CHECK]`` popup prefix (a callout box drawn on the sheet says ``VERIFY:``);
- **severity layers**: every finding's ink (cloud, QC tag, margin callout, leader
  line, overflow / set-level note) is placed on a per-severity **PDF
  optional-content layer** — ``QC markups - High/Medium/Low severity`` — so a
  reviewer can show or hide a whole severity tier's markups at once in Bluebeam
  Revu / Acrobat / Chromium. Findings layer strictly by ``severity`` (a
  question-category finding rides its own tier, even though its *color* is blue);
  every layer ships **on**, so a freshly-opened reviewed set looks exactly as it
  did before — the layers only add the *option* to filter;
- text-anchored defects are Square clouds; **sheet-level / absence findings**
  (``anchor_hint="SHEET"``) become FreeText **callout boxes stacked in a computed
  clear margin band** (the largest text-free horizontal band, found from the
  sheet's word rectangles), with a **leader Line** arrow to the reported tile's
  centroid when one is known;
- **findings index pages** are inserted at the front of each reviewed PDF —
  three columns (ID, sheet, what to do) where every row carries a GOTO link
  that zooms the viewer onto the finding's markup; labeled
  "AI DRAFT REVIEW — index". The page is written for the engineer who has to
  act on it: severity is the ID's color, the only status signal is a
  ``VERIFY:`` prefix on a finding that was not confirmed, and a finding the
  verifier ruled out is not listed at all (it stays in the CSV / HTML report);
- an optional **appendix page** (off by default) lists the deterministic checks
  that *passed* — the balance column of a real review;
- popups are lean and actionable, written for a human reviewer: finding text,
  the recommended action, the verbatim quote to look for, the cross-sheet
  pointer, human-meaningful refs plus the citation verdict in plain words, and
  a closing plain-words trust note. Machine detail (finding ids, provenance
  chips, evidence paths, raw statuses) lives in the CSV/HTML report instead.

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
import multiprocessing
import os
import pickle
import re
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import pymupdf  # AGPL-3.0 — see module docstring; the 2nd of two blessed importers.

from . import tiling
from .diagnostics import get_logger
from .models import (
    ACTION_BUCKET_LABELS,
    ACTION_BUCKETS,
    ANNOTATION_COMPONENTS,
    PRIMARY_LEG_ID,
    REQUIRED_COMPONENTS,
    SET_LEG_ID,
    ConflictLeg,
    Finding,
    MarkupPlacement,
    MarkupReceipt,
    MarkupRunResult,
    action_bucket,
    bucket_is_ranked,
    needs_verify,
    on_sheet_instruction,
    reduced_trust_reason,
    TRUST_REASON_NO_QUOTE,
    TRUST_REASON_NO_TEXT,
    TRUST_REASON_NOT_FOUND,
    leg_identity,
    name_is_taken,
    record_name,
    verified_drawing_fact_only,
)
from .source_registry import assign_source_ids

_log = get_logger()

# The annot author — provenance is unmistakable in the Markups List.
DEFAULT_AUTHOR = "Drawing Analyzer (AI review)"
DEFAULT_ANNOTATE_WORKERS = 2
MAX_ANNOTATE_WORKERS = 4
_ANNOTATE_WORKERS_ENV = "DRAWING_ANALYZER_ANNOTATE_WORKERS"
_PROCESS_POOL_EXECUTOR = ProcessPoolExecutor
# The index/appendix page label — same provenance rule. ASCII hyphen, not an
# em-dash: insert_text's Base-14 fonts have no U+2014 glyph.
INDEX_PAGE_LABEL = "AI DRAFT REVIEW - FINDINGS INDEX"
APPENDIX_PAGE_LABEL = "AI DRAFT REVIEW - CHECKED AND CONSISTENT"
# Per-source overflow page (§17.6): rect-less findings that could not be placed in
# a clear band without obscuring drawing content land here, each linking back to
# its source page — distinct from the set-level ``Drawing_Set_Review_Notes.pdf``.
REVIEW_NOTES_PAGE_LABEL = "AI DRAFT REVIEW - AI REVIEW NOTES"

# Verification statuses trusted unconditionally. Under the Part III gating
# amendment (§18) the exhaustive default inks EVERYTHING except REJECTED —
# UNCERTAIN / FAILED / SKIPPED render in the dashed "unverified" style; the conservative
# "verified & deterministic only" mode (opt-in) restricts ink to this set.
_TRUSTED = frozenset({"VERIFIED", "DETERMINISTIC"})
# Rejected findings render grey/struck when explicitly opted in (--ink-rejected).
_REJECTED_COLOR = (0.45, 0.45, 0.45)

# ---- Plain-words trust vocabulary --------------------------------------- #
# The popup speaks to a human reviewer, not to the pipeline: a short bracket
# tag on line 1 of a cloud's comment (it survives the Markups List preview)
# plus a full plain sentence at the end of the popup.
# ASCII only — the same strings must be safe on Base-14 ``insert_text`` pages.
_TRUST_PREFIX = {"REJECTED": "[REJECTED] ", "UNVERIFIED": "[CHECK] "}
#: Reduced-trust evidence tags for a cloud's comment (WP-03B §8.3), keyed by
#: :func:`reduced_trust_reason` so the tag and the sentence under it can never
#: disagree. ``[QUOTE NOT FOUND]`` means a quote SHOULD have been findable and
#: was not; the other two mean there was nothing to search, or nothing to search
#: *for* — different messages, so they stay different tags.
_QUOTE_NOT_FOUND_PREFIX = "[QUOTE NOT FOUND]"
_NO_QUOTE_PREFIX = "[NO QUOTE TO CHECK]"
_NO_TEXT_EVIDENCE_PREFIX = "[NO TEXT TO CHECK]"
_EVIDENCE_PREFIX = {
    TRUST_REASON_NO_TEXT: _NO_TEXT_EVIDENCE_PREFIX,
    TRUST_REASON_NO_QUOTE: _NO_QUOTE_PREFIX,
    TRUST_REASON_NOT_FOUND: _QUOTE_NOT_FOUND_PREFIX,
}
# ---- What is DRAWN: the cover page and the callout boxes on a sheet -------- #
# The bracket tags above belong to the popup comment, where a reviewer who
# opens a markup wants the reason. Text an engineer reads at a glance (a cover
# row, a callout box on the sheet) carries one signal instead: nothing when the
# finding was confirmed, ``VERIFY:`` when it was not (:func:`models.needs_verify`).
# Why it was not confirmed is still said, in a sentence, further down the same
# comment.
_VERIFY_PREFIX = "VERIFY: "
_VERIFY_SHEET_PREFIX = "VERIFY (whole sheet): "
_SHEET_PREFIX = "WHOLE SHEET: "
_RULED_OUT_PREFIX = "RULED OUT: "
_TRUST_NOTE = {
    "VERIFIED": "AI-verified against the drawing.",
    "DETERMINISTIC": "Found by an exact text check of the drawings - not an AI judgment.",
    "UNCERTAIN": "Not yet verified - double-check on the sheet.",
    "FAILED": "Verifier could not run - double-check on the sheet.",
    "SKIPPED": "Not yet verified - double-check on the sheet.",
    "REJECTED": "Rejected on AI re-check - kept for the record only.",
}
_TRUST_NOTE_UNVERIFIED = "Not yet verified - double-check on the sheet."
# A verified code finding (``models.verified_drawing_fact_only``): the crop
# confirmed the drawing fact, not the code violation. ASCII only.
_TRUST_NOTE_CODE_VERIFIED = (
    "AI-verified that the drawing shows this - whether it breaks the code is "
    "not settled by that check."
)
# WP-03B §8.3: a finding standing on evidence the host could not check in text
# (a scanned sheet, or the pasted raster region of a hybrid one) must not read
# like a text-corroborated conflict. Said in plain words, on the drawing, where
# the reviewer decides whether to trust it. ASCII only (base-14 fonts).
_TRUST_NOTE_NO_TEXT_EVIDENCE = (
    "No searchable text on this sheet - the quote could not be checked "
    "automatically; confirm it visually."
)
_EVIDENCE_NOTE = {
    TRUST_REASON_NO_TEXT: _TRUST_NOTE_NO_TEXT_EVIDENCE,
    # A text-bearing sheet with no quote to look for: saying "no searchable text"
    # here is plainly false to anyone who can select text on the page in front
    # of them, and a caveat the reviewer can falsify is worse than none.
    TRUST_REASON_NO_QUOTE: (
        "The AI gave no quote for this - nothing could be checked "
        "automatically; confirm it visually."
    ),
    TRUST_REASON_NOT_FOUND: (
        "The quoted text was not found on this sheet - treat it as unconfirmed."
    ),
}
_TRUST_NOTE_SINGLE_READ = "Not yet verified (seen in one AI read) - double-check on the sheet."
# Arithmetic operand provenance (§17.5) overrides the generic note: the host
# math is always deterministic, but only text-extracted operands make it
# ground truth — model-transcribed terms must read as "re-check this".
_TRUST_NOTE_TEXT_EXTRACTED = "Math checked by computer from the sheet's own printed numbers."
_TRUST_NOTE_MODEL_TRANSCRIBED = (
    "Computed from numbers as read by the AI - re-check the math against the sheet."
)
_UNANCHORED_QUOTE_CAUTION = (
    " (the AI could not find this text on the sheet - treat with caution)"
)
_CITATION_PHRASE = {
    "CHECKED_SUPPORTS": "Code ref checked - it supports this finding.",
    "CHECKED_MISMATCH": "Code ref may be outdated",  # "- note (editions: X)" appended
    "UNRESOLVABLE": "Code ref not confirmed - no authoritative text found.",
}
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

# Severity → the PDF **optional-content layer** (OCG) a finding's ink lands on.
# In Bluebeam Revu / Acrobat / Chromium a layer can be toggled on or off, so a
# reviewer can show or hide a whole severity tier's markups at once (e.g. "just
# the high-severity issues"). Findings are layered strictly by ``severity`` — a
# "question"-category finding rides its own severity tier (unlike the *color*,
# which is blue for questions) — and an unset/other severity folds into the low
# tier, mirroring the index triage rank (:data:`_INDEX_SEVERITY_RANK`). Every
# layer ships **ON**, so a freshly-opened reviewed PDF looks exactly as it did
# before layers existed; the layers only add the *option* to filter. The fixed
# high→medium→low order keeps the layer panel and the saved bytes deterministic
# (I-7). ASCII hyphen (not em-dash): the names appear in the Base-14-rendered
# layer UI of some viewers.
_SEVERITY_LAYER_NAMES = {
    "high": "QC markups - High severity",
    "medium": "QC markups - Medium severity",
    "low": "QC markups - Low severity",
}
_SEVERITY_LAYER_ORDER = ("high", "medium", "low")

_BORDER_WIDTH = 1.5
_TAG_FONTSIZE = 8.0
_TAG_HEIGHT = 12.0

# Margin callout layout (sheet-level / absence findings).
_CALLOUT_W = 230.0
_CALLOUT_H = 54.0
_CALLOUT_GAP = 8.0

# Index-page layout (US letter portrait).
_INDEX_PAGE_W, _INDEX_PAGE_H = 612.0, 792.0
# Index columns: left edge per column, and the right margin the last one runs to.
# Widths are DERIVED from the next column's edge so a row's text can be fitted to
# the space it actually has (item 32) — one definition shared by the header row
# and the data rows, so the two cannot drift apart.
_INDEX_COL_X = (36.0, 95.0, 170.0)
_INDEX_COL_LABELS = ("ID", "Sheet", "What to do")
_INDEX_COL_RIGHT = 578.0            # _INDEX_PAGE_W - 34pt right margin
_INDEX_COL_GUTTER = 4.0             # keep a column off its neighbour's first glyph
_INDEX_COL_W = tuple(
    (_INDEX_COL_X[i + 1] if i + 1 < len(_INDEX_COL_X) else _INDEX_COL_RIGHT)
    - _INDEX_COL_X[i] - _INDEX_COL_GUTTER
    for i in range(len(_INDEX_COL_X))
)
_INDEX_SUBTITLE = (
    "Click a row to jump to its markup.  "
    "Red = high, orange = medium, blue = low or a question."
)
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


@dataclass
class _ReviewedPdfJob:
    """One source-local reviewed-PDF write, safe to pickle into a worker."""

    pdf_path: Path
    pairs: list[tuple[Finding, MarkupPlacement]]
    out_path: Path
    output_name: str
    run_id: str
    author: str
    sheet_meta: dict[int, dict] | None
    audit_stats: dict | None
    include_appendix: bool


@dataclass
class _ReviewedPdfOutcome:
    """Pickle-safe worker result; exception text is retained only for the log."""

    receipts: list[MarkupReceipt]
    error_type: str = ""
    error_detail: str = ""


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
    MARGIN, ``gated`` → GATED_INDEX (a real "Not marked on the sheets" index
    row, §6.4), and a REJECTED finding → its grey CLOUD/MARGIN when
    ``ink_rejected``, else REPORT_ONLY: nothing in the PDF at all.
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
    return "REPORT_ONLY"


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
        # A trust label belongs to its quote (§8.3): this leg carries the
        # finding's own quote, so it carries the finding's own evidence state.
        evidence_state=getattr(finding, "evidence_state", ""),
    )
    for i, leg in enumerate(legs):
        others = [primary_as_leg] + [l for j, l in enumerate(legs) if j != i]
        leg_finding = Finding(
            sheet_id=leg.sheet_id, source_name=leg.source_name, source_id=leg.source_id,
            page_index=leg.page_index, category=finding.category, severity=finding.severity,
            text=finding.text, source_quote=leg.source_quote,
            recommended_action=finding.recommended_action, refs=list(finding.refs),
            also_on=others, anchor=leg.anchor, verification=finding.verification,
            qc_id=finding.qc_id, citation=finding.citation, sources=list(finding.sources),
            # The synthetic finding stands in for *this leg*, so it must inherit
            # the leg's evidence state, not the parent's: a conflict can be text
            # grounded on one sheet and read off a raster detail on the other,
            # and the reviewer needs the caveat on the mark that has no text
            # behind it.
            evidence_state=getattr(leg, "evidence_state", ""),
            # One logical finding, one place on the to-do list: every leg sits
            # in its parent's group and carries its instruction.
            action=getattr(finding, "action", None),
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
    with a ``VERIFY:`` lead-in so they read as flagged, never dropped) —
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
    as a margin callout; ``"rejected"`` — verifier-contradicted, kept out of the
    PDF (inked grey and listed as ruled out when ``ink_rejected``); ``"gated"``
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


def _callout_prefix(finding: Finding, place: str, *, rejected: bool) -> str:
    """The lead-in of a callout box drawn on a sheet (``place`` as in
    :func:`_placement_kind`)."""
    if rejected:
        return _RULED_OUT_PREFIX
    whole_sheet = place == "SHEET"
    if needs_verify(finding):
        return _VERIFY_SHEET_PREFIX if whole_sheet else _VERIFY_PREFIX
    return _SHEET_PREFIX if whole_sheet else ""


def _subject(finding: Finding) -> str:
    """The annotation Subject: the finding's to-do group, numbered so it sorts.

    Bluebeam's Markups List sorts and filters on Subject, so this is what lets
    a reviewer pull up "1 - Do this first" there (and dims the rest on the
    sheet). Every part of a finding's markup carries the same Subject, so a
    filter keeps the cloud, its tag and its instruction together.
    """
    if _status(finding) == "REJECTED":
        return "Ruled out"
    bucket = action_bucket(finding)
    return f"{ACTION_BUCKETS.index(bucket) + 1} - {ACTION_BUCKET_LABELS[bucket]}"


def _action_text(finding: Finding) -> str:
    """What to do about a finding, in one line ("" when nobody said).

    The reviewing channel's own sentence when it wrote one, else the
    action-plan pass's instruction.
    """
    action = " ".join((getattr(finding, "recommended_action", "") or "").split())
    if action:
        return action
    plan = getattr(finding, "action", None)
    return " ".join(str(getattr(plan, "instruction", "") or "").split())


def _color(finding: Finding) -> tuple[float, float, float]:
    if (finding.category or "").lower() == "question":
        return _QUESTION_COLOR
    return _SEVERITY_COLORS.get((finding.severity or "").lower(), _DEFAULT_COLOR)


def _truncate_at_word(text: str, limit: int) -> str:
    """Truncate to <= ``limit`` chars at a word boundary with an ASCII ``...``.

    Never cuts mid-word: the cut backs up to the last whitespace, unless that
    whitespace sits in the first half of the budget (one giant token), where a
    hard cut is the only option. Short text passes through unchanged. Pure and
    PyMuPDF-free, so the display-slice rule is unit-testable.

    For a plain FreeText annot the truncated string must ALSO be what is handed
    to ``set_info(content=...)``: ``/Contents`` *is* the displayed text there, so
    passing the untruncated string afterwards silently undoes this (P7 item 33).
    Callers therefore truncate once and reuse the result for both.
    """
    if len(text) <= limit:
        return text
    cut = max(limit - 3, 1)
    head = text[:cut]
    space = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
    if space > cut // 2:
        head = head[:space]
    return head.rstrip() + "..."


# --------------------------------------------------------------------------- #
# Base-14 safe, width-fitted page text (P7 item 32).
#
# ``insert_text`` draws with the Base-14 fonts, which encode Latin-1. Anything
# outside it is silently drawn as a **middle dot** — no exception, no warning —
# so ``3" drain`` written with a U+2033 prime became ``3. drain`` and an em-dash
# became a stray dot. A mangled dimension in a fire-sprinkler findings index is
# worse than a missing one, because it still reads as a number.
#
# And a character budget is not a width fit. The findings column is 238 pt wide
# and the shipped 62-char cap measured, at 8 pt Helvetica: 248.1 pt for
# ``PROVIDE 6 INCH DRAIN AT COLUMN LINE 4 PER DETAIL 3/M-501``, 285.4 pt for
# ``SPRINKLER HEAD SPACING EXCEEDS MAXIMUM PERMITTED BY NFPA 13``, 276.0 pt for
# ``VAV-3 HAS NO CLEARANCE SHOWN AND CONFLICTS WITH DUCT MAIN``. Lowercase prose
# fits at 229.4 pt, which is why this survived: drawings are lettered UPPERCASE
# and uppercase is wider, so realistic sheet text is exactly the case that
# overflows into the next column.
# --------------------------------------------------------------------------- #

#: Typographic characters folded to their ASCII equivalent before insertion.
#: Latin-1 characters that Base-14 *can* draw (``1/2``, ``deg``, accents) are
#: deliberately absent — they render correctly and must not be degraded.
_INSERT_TEXT_FOLD: dict[int, str] = {}
for _src, _dst in (
    ("\u2033\u201c\u201d\u201e", '"'),      # double prime, curly/low quotes
    ("\u2032\u2018\u2019\u201a", "'"),      # prime, curly single quotes
    ("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"),   # dashes, minus
    ("\u2044\u2215", "/"),                    # fraction slash, division slash
    ("\u00d7", "x"),                           # multiplication sign
    ("\u00f8\u2300", "dia "),                 # slashed o / diameter sign
    ("\u2264", "<="),
    ("\u2265", ">="),
):
    for _c in _src:
        _INSERT_TEXT_FOLD[ord(_c)] = _dst
_INSERT_TEXT_FOLD[ord("\u2026")] = "..."       # ellipsis
_INSERT_TEXT_FOLD[ord("\u2713")] = "[OK]"      # check mark
_INSERT_TEXT_FOLD[ord("\u00a0")] = " "         # no-break space


def _base14_safe(text: str) -> str:
    """``text`` with every glyph Base-14 ``insert_text`` cannot draw resolved.

    Known typography folds to its ASCII equivalent; anything still outside
    Latin-1 becomes ``?``, which at least reads as "unknown character" instead of
    passing for a decimal point in a dimension.
    """
    folded = (text or "").translate(_INSERT_TEXT_FOLD)
    return folded.encode("latin-1", "replace").decode("latin-1")


def _fit_text(
    text: str, width: float, *, fontsize: float, fontname: str = "helv"
) -> str:
    """``text``, Base-14-safe and shortened to actually fit ``width`` points.

    Measures with :func:`pymupdf.get_text_length` — the same metrics
    ``insert_text`` draws with — instead of counting characters, and backs up to a
    word boundary, appending an ASCII ``...`` when it had to cut. Folding happens
    **first**, because folding can change the width (``...`` is wider than the
    ellipsis it replaces, ``dia `` far wider than ``\u00f8``).
    """
    safe = _base14_safe(text)
    if width <= 0:
        return ""
    if pymupdf.get_text_length(safe, fontname=fontname, fontsize=fontsize) <= width:
        return safe
    ell = "..."
    budget = width - pymupdf.get_text_length(ell, fontname=fontname, fontsize=fontsize)
    if budget <= 0:
        return ""
    # Longest prefix that fits, then retreat to the last word boundary unless that
    # would throw away more than half of it (one very long token).
    lo, hi = 0, len(safe)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pymupdf.get_text_length(safe[:mid], fontname=fontname, fontsize=fontsize) <= budget:
            lo = mid
        else:
            hi = mid - 1
    head = safe[:lo]
    space = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
    if space > lo // 2:
        head = head[:space]
    return head.rstrip() + ell


def _placement_kind(finding: Finding) -> str:
    """What kind of rect-less finding a margin callout carries.

    ``"SHEET"`` / ``"NO_QUOTE"`` / ``"UNANCHORED"``. Unrelated to
    :data:`~drawing_analyzer.models.PLACEMENT_KINDS` and to
    ``MarkupPlacement.expected``, despite the name.

    A finding that carries **no quote** returns ``"NO_QUOTE"``, not
    ``"UNANCHORED"`` (P7 item 34): a graphics-only finding the model reported
    off the drawing itself is not a fabricated quote that matched nothing. The
    callout box no longer prints that difference — it leads with ``VERIFY:`` for
    both, and with a whole-sheet lead-in for ``"SHEET"``
    (:func:`_callout_prefix`) — but the comment's own sentences still say which
    it was.
    """
    if getattr(finding, "anchor_hint", "") == "SHEET":
        return "SHEET"
    if not str(getattr(finding, "source_quote", "") or "").strip():
        return "NO_QUOTE"
    return "UNANCHORED"


def _trust_note(finding: Finding, *, unverified: bool, rejected: bool) -> str:
    """The plain-words trust sentence that closes the popup ("" for none).

    Arithmetic operand provenance (§17.5) overrides the generic phrasing: a
    host computation over model-transcribed terms must not read as ground
    truth just because the multiplication ran in Python. The self-consistency
    ``reproduced`` flag folds into the unverified sentence — it only ever
    carries signal there.
    """
    if rejected:
        return _TRUST_NOTE["REJECTED"]
    v = getattr(finding, "verification", None)
    origin = getattr(v, "operand_origin", "") if v is not None else ""
    failed_note = _TRUST_NOTE["FAILED"] if getattr(v, "status", "") == "FAILED" else ""
    if origin == "TEXT_EXTRACTED":
        return " ".join(filter(None, (_TRUST_NOTE_TEXT_EXTRACTED, failed_note)))
    if origin == "MODEL_TRANSCRIBED":
        return " ".join(filter(None, (_TRUST_NOTE_MODEL_TRANSCRIBED, failed_note)))
    if failed_note:
        return _with_evidence_reason(finding, failed_note, status="FAILED")
    if unverified:
        note = (
            _TRUST_NOTE_SINGLE_READ
            if not getattr(finding, "reproduced", True)
            else _TRUST_NOTE_UNVERIFIED
        )
        return _with_evidence_reason(finding, note, status="")
    status = (v.status if v is not None else "") or ""
    if verified_drawing_fact_only(finding):
        return _with_evidence_reason(finding, _TRUST_NOTE_CODE_VERIFIED, status=status)
    return _with_evidence_reason(finding, _TRUST_NOTE.get(status, ""), status=status)


def _with_evidence_reason(finding: Finding, note: str, *, status: str) -> str:
    """Prepend WHY a reduced-trust finding could not be checked (WP-03B §8.3).

    Prepended rather than replacing the verification sentence: both facts matter
    to a reviewer. Skipped when a direct check already spoke — a VERIFIED crop
    read or a DETERMINISTIC host computation is the stronger statement, and
    saying "could not be checked automatically" beside it would be false.
    """
    if status in ("VERIFIED", "DETERMINISTIC"):
        return note
    reason = _EVIDENCE_NOTE.get(reduced_trust_reason(finding), "")
    if not reason:
        return note
    return f"{reason} {note}".strip()


def _located_phrase(finding: Finding) -> str:
    """Where the absence cross-check found what this absence reported missing."""
    located = getattr(finding, "located_elsewhere", None)
    if located is None:
        return ""
    where = "this sheet" if located.same_sheet else (located.sheet_id or "another sheet")
    phrase = f'Shown on {where}: "{located.quote}"'
    if located.demoted_from:
        phrase += f" (lowered from {located.demoted_from})"
    return phrase


def _citation_phrase(finding: Finding) -> str:
    """The citation-check verdict as one reviewer sentence ("" when unchecked)."""
    citation = getattr(finding, "citation", None)
    if citation is None:
        return ""
    phrase = _CITATION_PHRASE.get(citation.status, "")
    if not phrase:
        return ""
    if citation.status == "CHECKED_MISMATCH":
        if citation.note:
            phrase += f" - {citation.note}"
        if citation.edition_notes:
            phrase += f" ({citation.edition_notes} editions)"
    # Phase B: name the edition each verdict was actually checked against —
    # the reviewer-facing form of the structured provenance. Bounded; URLs and
    # raw statuses stay in the CSV/HTML report, never on the drawing.
    checked = []
    for a in (getattr(finding, "citations", None) or []):
        edition = str(getattr(a, "checked_edition", "") or "").strip()
        if edition:
            checked.append(f"{getattr(a, 'reference', '')}: {edition}")
    if checked:
        phrase += (" - checked against " + "; ".join(checked))[:220]
    return phrase


def _annot_content(
    finding: Finding, *, unverified: bool, rejected: bool = False, place: str = ""
) -> str:
    """The popup comment — lean and actionable, written for a human reviewer.

    Order: the finding itself first (Revu's Markups List previews the first
    line), then what to do about it, where to look (the verbatim quote and any
    cross-sheet pointers), human-meaningful code refs + the citation verdict in
    plain words, and a closing plain-words trust note. Machine detail (finding
    ids, provenance chips, evidence paths, raw statuses) stays in the CSV/HTML
    report — never on the drawing. ``place`` is given for a callout **box**
    (:func:`_placement_kind`): a FreeText annot's ``/Contents`` *is* the text
    drawn on the sheet, so a box leads with the one plain signal an engineer
    needs (:func:`_callout_prefix`) rather than the bracket tags a popup
    carries. ASCII only.
    """
    head = f"{finding.qc_id}: " if finding.qc_id else ""
    lines = [f"{head}{finding.text.strip()}"]
    action = _action_text(finding)
    if action:
        lines.append(f"Action: {action}")
    quote = finding.source_quote.strip()
    if quote:
        look = f'Look for: "{quote}"'
        if getattr(finding.anchor, "status", "") == "UNANCHORED":
            look += _UNANCHORED_QUOTE_CAUTION
        lines.append(look)
    for leg in getattr(finding, "also_on", None) or []:
        lq = f': "{leg.source_quote.strip()}"' if leg.source_quote.strip() else ""
        pointer = f"Conflicts with {leg.sheet_id}{lq}"
        if finding.qc_id:
            pointer += f" - see {finding.qc_id} there"
        lines.append(pointer)
    if finding.refs:
        lines.append("Refs: " + ", ".join(str(r) for r in finding.refs))
    located = _located_phrase(finding)
    if located:
        lines.append(located)
    cite = _citation_phrase(finding)
    if cite:
        lines.append(cite)
    note = _trust_note(finding, unverified=unverified, rejected=rejected)
    if note:
        lines.append(note)
    content = "\n".join(lines)
    if place:
        return f"{_callout_prefix(finding, place, rejected=rejected)}{content}"
    trust = _TRUST_PREFIX["REJECTED"] if rejected else (
        _TRUST_PREFIX["UNVERIFIED"] if unverified else ""
    )
    evidence_tag = _EVIDENCE_PREFIX.get(reduced_trust_reason(finding), "")
    placement = f"{evidence_tag} " if evidence_tag else ""
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


# --------------------------------------------------------------------------- #
# Occupancy-aware callout packing (Phase 25 §17.6) — never obscure drawing ink.
# --------------------------------------------------------------------------- #


def _clear_bands(
    words: list[Any], page_w: float, page_h: float,
    *, max_height: float = 170.0, min_height: float = _CALLOUT_H,
) -> list[tuple[float, float, float, float]]:
    """Every word-free band a callout can sit in, tallest first.

    The plural generalization of :func:`find_clear_band`. Occupancy of *non-text*
    ink (piping, symbols, raster) is checked separately at pack time — a text-free
    band is not automatically visually clear (§17.6).

    ``min_height`` is the minimum height of a **returned** band, i.e. after the
    breathing pad is taken off (N24). It used to be checked against the raw gap
    with the pad applied afterwards, so a gap that passed at 58 pt came back as a
    50 pt band that :func:`_pack_callouts` could never use — its guard is
    ``y + _CALLOUT_H <= band_bottom`` — and every finding that would have gone
    there overflowed to the review-notes page instead. Measured: gaps of 58 and
    60 pt yielded 50 and 52 pt bands against a 54 pt callout.

    Bands are also **column-aware** (N24). A band used to be a y-range no word
    occupied at *any* x, which is close to unobtainable on a real drawing: a
    right-hand title block spans almost the full sheet height, so on a 1728x1188
    sheet with a title block at y 60..1050 exactly **one** full-width band was
    found, and the entire 1448x990 pt clear drawing area beside it was unusable.
    Callouts overflowed off a sheet with room to spare.

    So the page is also considered in vertical columns, and a column's bands are
    computed from only those words that actually intersect that column in x. The
    word-free guarantee still holds exactly — a word that misses the column in x
    cannot overlap a box inside it, and one that does not was excluded from the
    gap — which is what lets :func:`_pack_callouts` keep skipping its per-candidate
    word scan. Full-width bands are generated **first** and sorting is by height,
    so a wide clear strip is still preferred and the previous behaviour is a
    subset of this one.
    """
    inset_x = 0.03 * page_w
    inset_y = 0.02 * page_h
    top, bottom = inset_y, page_h - inset_y
    left, right = inset_x, page_w - inset_x

    def bands_in_column(cx0: float, cx1: float) -> "list[tuple[float, float, float, float]]":
        intervals: list[tuple[float, float]] = []
        for w in words or []:
            y0, y1 = float(w[1]), float(w[3])
            if y1 <= top or y0 >= bottom:
                continue
            # Only words that actually intersect this column can obstruct it.
            if float(w[2]) <= cx0 or float(w[0]) >= cx1:
                continue
            intervals.append((max(y0, top), min(y1, bottom)))
        intervals.sort()
        merged: list[list[float]] = []
        for y0, y1 in intervals:
            if merged and y0 <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], y1)
            else:
                merged.append([y0, y1])
        gaps: list[tuple[float, float]] = []
        prev = top
        for y0, y1 in merged:
            if y0 > prev:
                gaps.append((prev, y0))
            prev = max(prev, y1)
        if bottom > prev:
            gaps.append((prev, bottom))
        out: list[tuple[float, float, float, float]] = []
        for g0, g1 in gaps:
            pad = min(4.0, (g1 - g0) / 10.0)
            y0 = g0 + pad
            y1 = min(g1 - pad, y0 + max_height)
            if y1 - y0 < min_height:      # gate the PADDED band, not the raw gap
                continue
            out.append((cx0, y0, cx1, y1))
        return out

    # The full width first — the best placement when it exists — then columns wide
    # enough to hold a callout. One column per callout width keeps the band count
    # bounded (about seven on an E-size sheet).
    columns: list[tuple[float, float]] = [(left, right)]
    usable_w = right - left
    col_w = _CALLOUT_W + _CALLOUT_GAP
    if usable_w >= 2.0 * col_w:
        n_cols = int(usable_w // col_w)
        step = usable_w / n_cols
        columns.extend(
            (left + i * step, left + (i + 1) * step) for i in range(n_cols)
        )

    bands: list[tuple[float, float, float, float]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for cx0, cx1 in columns:
        if cx1 - cx0 < _CALLOUT_W:
            continue
        for band in bands_in_column(cx0, cx1):
            key = tuple(int(round(v)) for v in band)
            if key in seen:                       # a column that reproduces the full width
                continue
            seen.add(key)
            bands.append(band)
    # Tallest first, then left-to-right / top-down for deterministic assembly (I-7).
    bands.sort(key=lambda b: (-(b[3] - b[1]), b[1], b[0]))
    return bands


def _rect_overlaps_any(
    box: tuple[float, float, float, float],
    rects: list[tuple[float, float, float, float]],
) -> bool:
    for r in rects:
        if box[0] < r[2] and box[2] > r[0] and box[1] < r[3] and box[3] > r[1]:
            return True
    return False


# Occupancy sampling constants (P7 item 29). Every one of these was chosen by
# measurement on an E-size (1728x1188 pt) sheet; see :func:`_page_occupancy`.
_OCCUPANCY_SCALE = 1.0            # a hairline is only genuinely dark at 1:1
_OCCUPANCY_CELL_PT = 8.0          # min-filter cell, in POINTS (scale-invariant)
_OCCUPANCY_DARK_LEVEL = 210       # a sample below this is ink
_OCCUPANCY_MIN_INKED_FRAC = 0.005  # inked-cell fraction that means "occupied"
#: OOM guard only. A page so large that 1:1 would blow past this is sampled
#: coarser, which costs thin-line sensitivity — the one case where this sampler
#: degrades back toward the old behaviour, so it is a guard, not a tuning knob.
_OCCUPANCY_MAX_PIXELS = 40_000_000


def _page_occupancy(
    page: "pymupdf.Page",
    *,
    scale: float = _OCCUPANCY_SCALE,
    cell_pt: float = _OCCUPANCY_CELL_PT,
):
    """A ``occupied(view_rect) -> bool`` sampler over a render of the page.

    A candidate callout box is "occupied" when enough of it carries non-white ink
    — catching the piping/symbols/vector-schedule/raster content a text-free band
    can still sit on (§17.6). The pixmap is rendered **lazily** on the first query
    (so a page with no clear band to pack into never renders one), in the page's
    rotated **view** space (``page.rect`` dims == PAGE_VIEW_V2), so a view-space
    box maps to pixels by ``* scale`` with no derotation. If rendering fails the
    sampler degrades to *never occupied* (callouts still avoid words), so
    occupancy analysis is additive and non-fatal (I-3).

    **Why a min-filter over cells, and why 1:1 (P7 item 29).** The shipped
    sampler rendered at 0.12 and asked what fraction of the box's *pixels* were
    dark. Both halves failed on real drawings, and measured on an E-size sheet:

    * At 0.12 a 0.5 pt pipe line covers an eighth of a pixel, so antialiasing
      returns roughly 223 — *lighter* than the 210 ink threshold. A single
      sprinkler main across a band scored **0.0000** and the band was declared
      clear, so the callout was stamped over the piping.
    * Raising the scale does not fix it, which is the counter-intuitive part: the
      verdict is **non-monotonic** in scale, because a thin line's pixel count
      grows linearly while the box's grows quadratically, so the *fraction* falls
      even as the line becomes visible. One 1 pt line measured clear at 0.12 and
      0.25, occupied at 0.5, and clear again at 1.0; three 0.5 pt branch lines
      measured occupied at 0.25 but clear at 0.5, purely on pixel-grid alignment.

    So sensitivity comes from sampling at 1:1, where a hairline really is dark,
    and stability comes from replacing the pixel fraction with a **min-filter**:
    the box is divided into cells measured in *points*, a cell counts as inked if
    **any** pixel in it is dark, and the verdict is the fraction of inked cells.
    A hairline becomes a solid run of inked cells (7% of a band, well clear of the
    0.5% floor) while isolated scanner dirt stays one cell each. Measured across
    eleven contents — blank, a faint 0.93 grey wash, 400 dots of scan speckle, a
    0.5 pt line, a 1 pt line, a diagonal, three branch lines, ten sprinkler head
    symbols, 160 hatch lines, and a solid block — this configuration is correct on
    all eleven, where the shipped one was wrong on five.

    Cost is not the reason the old scale was low: rendering an E-size page at 1:1
    measures **~1 ms**, and one query ~3 ms.

    **Known limit, stated rather than papered over.** The metric is relative to
    box area, so an *isolated short* stub is not detected: in a 1340x110 pt band a
    0.5 pt line is caught from ~100 pt of length, and below that it lands in the
    same range as heavy speckle (~2,000 isolated dots in one band), so no
    threshold separates them. Closing that needs run-length/contiguity analysis
    and is deliberately **not** done here. Words are avoided separately, and a
    band this empty is the least harmful place to be wrong.
    """
    state: dict[str, Any] = {}

    def occupied(
        view_rect,
        *,
        min_inked_frac: float = _OCCUPANCY_MIN_INKED_FRAC,
        dark_level: int = _OCCUPANCY_DARK_LEVEL,
    ) -> bool:
        if "pix" not in state:
            try:
                eff = float(scale)
                rect = page.rect
                budget = max(1.0, float(rect.width) * float(rect.height))
                if budget * eff * eff > _OCCUPANCY_MAX_PIXELS:
                    eff = (_OCCUPANCY_MAX_PIXELS / budget) ** 0.5
                    _log.info(
                        "page too large for 1:1 occupancy sampling; using scale "
                        "%.3f (thin-line sensitivity is reduced)", eff,
                    )
                state["scale"] = eff
                state["pix"] = page.get_pixmap(
                    matrix=pymupdf.Matrix(eff, eff), colorspace=pymupdf.csGRAY, alpha=False
                )
            except Exception:  # noqa: BLE001 - occupancy is a refinement, never fatal
                _log.debug("occupancy render failed; callouts fall back to word-avoidance")
                state["pix"] = None
        pix = state["pix"]
        if pix is None:
            return False                         # render unavailable → word-avoidance only
        eff = float(state.get("scale") or scale)
        w, h, samples = pix.width, pix.height, pix.samples
        x0 = max(0, int(view_rect[0] * eff)); y0 = max(0, int(view_rect[1] * eff))
        x1 = min(w, int(view_rect[2] * eff)); y1 = min(h, int(view_rect[3] * eff))
        if x1 <= x0 or y1 <= y0:
            return True                          # off-render / degenerate → unsafe
        step = max(1, int(round(float(cell_pt) * eff)))
        inked = cells = 0
        for cy in range(y0, y1, step):
            y_end = min(cy + step, y1)
            for cx in range(x0, x1, step):
                cells += 1
                x_end = min(cx + step, x1)
                for yy in range(cy, y_end):
                    base = yy * w
                    # ``min`` over the row slice is the min-filter, at C speed.
                    if min(samples[base + cx: base + x_end]) < dark_level:
                        inked += 1
                        break
        return cells > 0 and inked / cells >= min_inked_frac

    return occupied


def _segment_hits_box(
    p0: tuple[float, float], p1: tuple[float, float],
    box: tuple[float, float, float, float],
) -> bool:
    """True when the segment ``p0→p1`` passes through ``box`` (leader-crossing test)."""
    (x0, y0), (x1, y1) = p0, p1
    bx0, by0, bx1, by1 = box
    # Trivial reject: both endpoints on one outside side of the box.
    if (x0 < bx0 and x1 < bx0) or (x0 > bx1 and x1 > bx1):
        return False
    if (y0 < by0 and y1 < by0) or (y0 > by1 and y1 > by1):
        return False
    # Sample a few points along the segment; cheap and sufficient for a callout
    # leader (we only need "crosses / doesn't").
    for t in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9):
        px = x0 + (x1 - x0) * t
        py = y0 + (y1 - y0) * t
        if bx0 <= px <= bx1 and by0 <= py <= by1:
            return True
    return False


def _pack_callouts(
    pairs: "list[tuple[Finding, MarkupPlacement]]",
    words: list[Any], page_w: float, page_h: float, occupied,
) -> "tuple[list[tuple[Finding, MarkupPlacement, tuple]], list[tuple[Finding, MarkupPlacement]]]":
    """Pack callout boxes into the clear bands; return ``(placed, overflow)``.

    Each box is validated against the occupancy mask and every already-placed
    sibling before it is accepted, so a placed callout never overlaps drawing
    content or another callout (§17.6 step 5). Word rects need not be re-checked
    here: :func:`_clear_bands` builds each band as a **word-free** y-range (padded
    off the nearest word), so a box wholly inside a band cannot overlap a word —
    dropping a per-candidate O(words) scan that was pure waste on a dense sheet. A
    finding that cannot be placed in any visually-clear band is returned as
    overflow — routed to the review-notes page rather than stamped over the drawing.
    """
    bands = _clear_bands(words, page_w, page_h)
    placed: list[tuple[Finding, MarkupPlacement, tuple]] = []
    placed_boxes: list[tuple[float, float, float, float]] = []
    remaining = list(pairs)
    for bx0, by0, bx1, by1 in bands:
        y = by0
        while y + _CALLOUT_H <= by1 + 0.5 and remaining:
            x = bx0
            while x + _CALLOUT_W <= bx1 + 0.5 and remaining:
                box = (x, y, x + _CALLOUT_W, y + _CALLOUT_H)
                if not _rect_overlaps_any(box, placed_boxes) and not occupied(box):
                    f, pl = remaining.pop(0)
                    placed.append((f, pl, box))
                    placed_boxes.append(box)
                    x += _CALLOUT_W + _CALLOUT_GAP
                else:
                    # Slide past the obstacle by a coarse step (a quarter box), so a
                    # heavily-inked band is scanned in a bounded number of probes
                    # rather than an 8-pt-at-a-time crawl.
                    x += max(_CALLOUT_GAP, _CALLOUT_W / 4.0)
            y += _CALLOUT_H + _CALLOUT_GAP
    return placed, remaining


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
    """A PAGE_VIEW_V2 point → this page's un-rotated (annotation) space.

    Correct for **annotation** placement (``add_*_annot``), which is what it is
    for.  A GOTO *destination* is a different space entirely — see
    :func:`_dest_user_point` — so never reuse this for one.
    """
    return pymupdf.Point(float(x), float(y)) * page.derotation_matrix


# --------------------------------------------------------------------------- #
# GOTO destinations are NOT annotation space (P7 item 27).
#
# A destination is expressed in **default user space** (PDF 32000-1 §12.3.2.2),
# the same space an annotation's ``/Rect`` uses (§12.5.2) — which is what lets
# the two be compared, and is how the transform below was pinned: stamp a rect
# annot at a known place, save, and read the raw ``/Rect`` back out of the file.
# Annotation *placement*, by contrast, goes through PyMuPDF's un-rotated
# CropBox-relative space, so :func:`_derotate_point` is only half of the journey
# and passing its result to a destination drops the CropBox origin and the
# MediaBox origin. Measured on PyMuPDF 1.28.2 across rotation × CropBox ×
# MediaBox-origin (24 cases, ``tests/test_drawing_geometry.py``) that error
# reaches ~550 pt, i.e. off-sheet.
#
# Every link and bookmark the writer makes is a ``/FitR`` destination: a
# rectangle the viewer fits to its window, so the markup arrives centered and
# at a readable zoom whatever the reader's zoom was. (The earlier ``/XYZ``
# point said "put this corner at the window's top-left and keep your zoom",
# which lands the markup in a corner; Bluebeam Revu honors ``/FitR``.) PyMuPDF
# can only write ``/XYZ`` — through ``insert_link`` and ``set_toc`` alike — so
# the writer lets it create the object and then replaces the destination array
# in place, which also means neither of PyMuPDF's two point transforms is
# involved any more. Where a mark was drawn, the rectangle is that mark's own
# ``/Rect`` read back from the document: already default user space, so there
# is no transform to get wrong.
# --------------------------------------------------------------------------- #

# The view a link opens: the mark plus this much sheet around it, and never
# less than a window's worth of drawing — a link that fills the screen with one
# small tag has lost the context the reader needs to recognize where they are.
_DEST_PAD_PT = 72.0
_DEST_MIN_VIEW_PT = (720.0, 504.0)      # width x height as displayed (10 x 7 in.)


def _dest_user_point(page: "pymupdf.Page", x: float, y: float) -> "pymupdf.Point":
    """A PAGE_VIEW_V2 point → this page's **default user space** (PDF §12.3.2.2).

    ``page.cropbox`` is reported in PyMuPDF's *top-left* convention while
    ``page.mediabox`` is the **raw** PDF box (bottom-left, un-normalized), so
    ``mediabox.y1 - cropbox.y0`` is the CropBox's top edge in user space.  That
    asymmetry is the trap here; it is measured, not assumed.
    """
    u = pymupdf.Point(float(x), float(y)) * page.derotation_matrix
    return pymupdf.Point(
        page.cropbox.x0 + u.x,
        page.mediabox.y1 - page.cropbox.y0 - u.y,
    )


def _view_rect_to_user(page: "pymupdf.Page", view_rect: Any) -> "tuple[float, float, float, float]":
    """A PAGE_VIEW_V2 rectangle → ``(left, bottom, right, top)`` in user space.

    All four corners are mapped, because on a rotated page the view rect's
    top-left corner is not the user-space rect's top-left corner.
    """
    x0, y0, x1, y1 = (float(v) for v in view_rect)
    pts = [_dest_user_point(page, x, y) for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))]
    xs, ys = [pt.x for pt in pts], [pt.y for pt in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _annot_user_rect(
    doc: "pymupdf.Document", xref: int
) -> "tuple[float, float, float, float] | None":
    """An annotation's own ``/Rect`` — ``(left, bottom, right, top)`` in user space."""
    kind, value = doc.xref_get_key(int(xref), "Rect")
    if kind != "array":
        return None
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", value)]
    if len(nums) != 4:
        return None
    return min(nums[0], nums[2]), min(nums[1], nums[3]), max(nums[0], nums[2]), max(nums[1], nums[3])


def _zoom_box(
    page: "pymupdf.Page", user_rect: "tuple[float, float, float, float]"
) -> "tuple[float, float, float, float]":
    """The user-space rectangle a link to ``user_rect`` should fit to the window.

    The mark, padded, grown to the minimum view, then slid back inside the
    visible page (and clipped to it when the page is smaller than the view).
    The minimum is stated as displayed, so it is swapped on a page rotated a
    quarter turn, whose user-space width is its on-screen height.
    """
    left, bottom, right, top = user_rect
    min_w, min_h = _DEST_MIN_VIEW_PT
    if int(page.rotation or 0) % 180:
        min_w, min_h = min_h, min_w
    w = max(right - left + 2.0 * _DEST_PAD_PT, min_w)
    h = max(top - bottom + 2.0 * _DEST_PAD_PT, min_h)
    cx, cy = (left + right) / 2.0, (bottom + top) / 2.0
    # The visible page (CropBox) in user space — see _dest_user_point.
    page_l, page_r = page.cropbox.x0, page.cropbox.x1
    page_b = page.mediabox.y1 - page.cropbox.y1
    page_t = page.mediabox.y1 - page.cropbox.y0

    def _fit(center: float, size: float, lo: float, hi: float) -> "tuple[float, float]":
        if size >= hi - lo:
            return lo, hi
        a = min(max(center - size / 2.0, lo), hi - size)
        return a, a + size

    x0, x1 = _fit(cx, w, page_l, page_r)
    y0, y1 = _fit(cy, h, page_b, page_t)
    return x0, y0, x1, y1


def _fit_rect_dest(page: "pymupdf.Page", user_rect: "tuple[float, float, float, float]") -> str:
    """The destination array that zooms onto ``user_rect`` (padded) on ``page``."""
    x0, y0, x1, y1 = _zoom_box(page, user_rect)
    return f"[{page.xref} 0 R/FitR {x0:.2f} {y0:.2f} {x1:.2f} {y1:.2f}]"


def _fit_page_dest(page: "pymupdf.Page") -> str:
    """The destination array that shows the whole of ``page``."""
    return f"[{page.xref} 0 R/Fit]"


def _mark_dest(
    doc: "pymupdf.Document",
    page_index: int,
    *,
    mark_xref: "int | None" = None,
    view_rect: Any = None,
) -> str:
    """Where a link to a finding on ``doc[page_index]`` should land.

    The drawn mark's own rectangle when there is one; else the finding's anchor
    rectangle (a finding listed without ink); else the whole sheet.
    """
    page = doc[page_index]
    user_rect = _annot_user_rect(doc, mark_xref) if mark_xref else None
    if user_rect is None and view_rect:
        user_rect = _view_rect_to_user(page, view_rect)
    return _fit_rect_dest(page, user_rect) if user_rect else _fit_page_dest(page)


def _page_annot_xrefs(doc: "pymupdf.Document", page: "pymupdf.Page") -> "set[int]":
    """Every annotation xref on ``page``, read from ``/Annots`` itself.

    ``Page.get_links()`` does not report a link inserted earlier in the same
    session, so the array is the only way to find the object just created.
    """
    kind, value = doc.xref_get_key(page.xref, "Annots")
    if kind == "xref":
        kind, value = "array", doc.xref_object(int(value.split()[0]), compressed=True)
    if kind != "array":
        return set()
    return {int(n) for n in re.findall(r"(\d+) 0 R", value)}


def _insert_goto_link(
    doc: "pymupdf.Document", page: "pymupdf.Page", from_rect: "pymupdf.Rect",
    target_page: int, dest: str,
) -> None:
    """A link on ``page`` over ``from_rect`` that jumps to ``dest``.

    ``insert_link`` creates the annotation (and maps ``from_rect`` into the
    page's own space); the destination it wrote is then replaced with ``dest``.
    If the new object cannot be identified the link stays a plain jump to the
    target page — a coarser link, never a missing one.
    """
    before = _page_annot_xrefs(doc, page)
    page.insert_link({
        "kind": pymupdf.LINK_GOTO, "from": from_rect, "page": int(target_page),
        "to": pymupdf.Point(0, 0), "zoom": 0,
    })
    new = _page_annot_xrefs(doc, page) - before
    if len(new) == 1:
        doc.xref_set_key(new.pop(), "A", f"<</S/GoTo/D{dest}>>")
    else:
        _log.debug("could not identify a new link on page %d; left as a page jump", page.number)


# --------------------------------------------------------------------------- #
# Severity layers (PDF optional-content groups) — see _SEVERITY_LAYER_NAMES.
# The ink is grouped by severity so a reviewer can toggle a whole tier on/off in
# Bluebeam/Acrobat/Chromium. Layering is additive and non-fatal (I-3): if the
# backend cannot create a layer, or a single annot cannot be tagged, the mark is
# still drawn — just unfilterable — never lost, and DA-007 reconciliation is
# untouched (the ``/OC`` reference and the placement stamp are independent keys
# on the annotation object, verified to coexist across save/reopen).
# --------------------------------------------------------------------------- #


def _severity_layer_tier(finding: Finding) -> str:
    """The severity tier whose OCG layer this finding's ink belongs on.

    One of ``"high"`` / ``"medium"`` / ``"low"``; an unset or unrecognized
    severity folds into ``"low"`` (the index triage rank's catch-all tier), so
    every drawable finding maps to exactly one layer.
    """
    sev = (finding.severity or "").lower()
    return sev if sev in _SEVERITY_LAYER_NAMES else "low"


def _create_severity_layers(
    doc: "pymupdf.Document", tiers: "set[str]"
) -> "dict[str, int]":
    """Create the severity OCG layers named in ``tiers`` → ``{tier: ocg_xref}``.

    Only tiers that actually carry ink get a layer (no empty layers), created in
    the fixed high→medium→low order so the layer panel and the saved bytes are
    deterministic across runs (I-7). Every layer ships **ON**. Non-fatal (I-3):
    if the backend cannot create an OCG the writer returns an empty map and every
    annot is drawn unlayered, exactly as before this feature.
    """
    layers: "dict[str, int]" = {}
    for tier in _SEVERITY_LAYER_ORDER:
        if tier not in tiers:
            continue
        try:
            layers[tier] = doc.add_ocg(_SEVERITY_LAYER_NAMES[tier], on=True)
        except Exception:  # noqa: BLE001 - layering is a refinement, never fatal
            _log.warning("could not create severity OCG layers; drawing unlayered")
            return {}
    return layers


def _assign_layer(
    annot: "pymupdf.Annot", finding: Finding, oc_layers: "dict[str, int] | None"
) -> None:
    """Put ``annot`` on its finding's severity layer (a no-op without layers).

    Call **before** ``annot.update()`` so the ``/OC`` reference is folded into the
    appearance stream the viewer builds. Non-fatal (I-3): a failure leaves the
    annot unlayered — visible, just not filterable — never a dropped mark.
    """
    if not oc_layers:
        return
    xref = oc_layers.get(_severity_layer_tier(finding))
    if not xref:
        return
    try:
        annot.set_oc(xref)
    except Exception:  # noqa: BLE001 - keep the mark; drop only the layer tag
        _log.debug("could not set OCG layer for finding %s", getattr(finding, "id", "?"))


# --------------------------------------------------------------------------- #
# Drawing (each helper returns how many annots it added)
# --------------------------------------------------------------------------- #


def _add_qc_tag(
    page: "pymupdf.Page", view_rect: "pymupdf.Rect", finding: Finding, *, author: str,
    oc_layers: "dict[str, int] | None" = None,
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
    annot.set_info(title=author, subject=_subject(finding), content=finding.qc_id)
    # No border_color: PyMuPDF rejects it on plain (non-rich) FreeText annots —
    # the severity-colored text itself is the tag's legend.
    _assign_layer(annot, finding, oc_layers)
    annot.update()
    return annot.xref


def _add_cloud(
    page: "pymupdf.Page", finding: Finding, *, unverified: bool, author: str,
    rejected: bool = False, oc_layers: "dict[str, int] | None" = None,
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
        subject=_subject(finding),
        content=_annot_content(finding, unverified=unverified, rejected=rejected),
    )
    # Put the cloud on its severity layer before update() folds /OC into the /AP.
    _assign_layer(annot, finding, oc_layers)
    # `update()` builds the appearance stream (/AP); without it some viewers draw
    # nothing. This is the whole reason PyMuPDF is used here (see module docstring).
    annot.update()
    components: list[tuple[str, int]] = [("cloud", annot.xref)]
    tag_xref = _add_qc_tag(page, view_rect, finding, author=author, oc_layers=oc_layers)
    if tag_xref is not None:
        components.append(("tag", tag_xref))
    return components


def _add_margin_callouts(
    page: "pymupdf.Page",
    pairs: "list[tuple[Finding, MarkupPlacement]]",
    *,
    meta: dict | None,
    author: str,
    oc_layers: "dict[str, int] | None" = None,
) -> "tuple[dict[str, list[tuple[str, int]]], list[tuple[Finding, MarkupPlacement]]]":
    """Rect-less findings as FreeText boxes packed into visually-clear bands.

    Boxes are packed by :func:`_pack_callouts` so every one is validated clear of
    the retained words, the occupancy mask (piping/symbols/raster), and its
    siblings before it is drawn — a callout never obscures drawing content
    (§17.6). Any finding that will not fit is returned as **overflow** for the
    review-notes page rather than stamped over the sheet. A leader Line is added
    only when the finding reported a tile *and* the leader would not cross another
    callout box. Returns ``({placement_id: [(component, xref), …]}, overflow)`` —
    the ``callout`` component is mandatory; the ``leader`` is optional.
    """
    drawn: dict[str, list[tuple[str, int]]] = {}
    if not pairs:
        return drawn, []
    words = list((meta or {}).get("words") or [])
    page_w, page_h = page.rect.width, page.rect.height
    occupied = _page_occupancy(page)
    placed, overflow = _pack_callouts(pairs, words, page_w, page_h, occupied)
    placed_boxes = [box for _f, _pl, box in placed]

    for finding, placement, box_t in placed:
        box = pymupdf.Rect(*box_t)                    # PAGE_VIEW_V2 space
        rejected = _status(finding) == "REJECTED"
        unverified = _is_unverified(finding) and not rejected
        color = _REJECTED_COLOR if rejected else _color(finding)
        # The box's lead-in (§18): a sheet-level absence reads WHOLE SHEET, and
        # anything unconfirmed — a quote that matched nothing included — reads
        # VERIFY, on the page but never dressed as a placed finding. For
        # FreeText /Contents IS the displayed text, so the prefixed content set
        # below is exactly what the box shows.
        content = _annot_content(
            finding, unverified=unverified, rejected=rejected,
            place=_placement_kind(finding),
        )
        components = drawn.setdefault(placement.placement_id, [])
        # Severity-colored text carries the legend (PyMuPDF rejects border_color
        # on plain FreeText annots); unverified/rejected callouts dash the border.
        # ``rotate=page.rotation`` keeps the text upright on a rotated sheet; the
        # box is transformed view→page so it lands in the computed clear band.
        # One truncation, reused for /Contents below: for a plain FreeText annot
        # /Contents IS the displayed text, so set_info(content=full) would undo
        # this and draw the whole string (item 33).
        shown = _truncate_at_word(content, 220)
        annot = page.add_freetext_annot(
            _derotate_rect(page, box), shown,
            fontsize=7.5, text_color=color, fill_color=(1.0, 1.0, 0.92),
            rotate=int(page.rotation or 0),
        )
        try:
            if unverified or rejected:
                annot.set_border(width=1.0, dashes=[4, 3])
        except Exception:  # noqa: BLE001
            pass
        annot.set_info(title=author, subject=_subject(finding), content=shown)
        _assign_layer(annot, finding, oc_layers)
        annot.update()
        components.append(("callout", annot.xref))

        centroid = _tile_centroid(finding.tile, meta)
        start_v = ((box.x0 + box.x1) / 2.0, box.y0 if centroid and centroid[1] < box.y0 else box.y1)
        # Only draw the leader when it does not cross another callout box excessively
        # (§17.6 step 4) — a leader raked across neighbouring callout text is worse
        # than none.
        crosses = centroid is not None and any(
            _segment_hits_box(start_v, centroid, other)
            for other in placed_boxes if other != box_t
        )
        if centroid is not None and not crosses:
            try:
                start = _derotate_point(page, start_v[0], start_v[1])
                line = page.add_line_annot(start, _derotate_point(page, centroid[0], centroid[1]))
                line.set_colors(stroke=color)
                try:
                    line.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_OPEN_ARROW)
                except Exception:  # noqa: BLE001 - line-end styles vary by version
                    pass
                line.set_info(title=author, subject=_subject(finding), content=finding.qc_id or "")
                _assign_layer(line, finding, oc_layers)   # leader shares the finding's tier
                line.update()
                components.append(("leader", line.xref))
            except Exception:  # noqa: BLE001 - a failed leader never drops the box
                _log.warning("could not draw leader line for %s", finding.id)

    if overflow:
        _log.info(
            "%d callout(s) did not fit a clear band; routing to the review-notes page",
            len(overflow),
        )
    return drawn, overflow


# --------------------------------------------------------------------------- #
# On-sheet instructions and the sheet stamp
#
# A cloud says "look here"; the comment behind it says why. Neither is readable
# at a glance, so where the fix is clear-cut the instruction itself is drawn
# beside the cloud — a native callout (a FreeText with a leader), which Bluebeam
# lists and edits like one of its own. Which findings qualify is not decided
# here: :func:`models.on_sheet_instruction` is the whole rule, and it requires
# the host's own confirmation of the finding as well as the model's claim.
#
# A box is placed only where the sheet is clear. It is tested, padded, against
# an occupancy render of the page as it stands (linework, text, and the marks
# already drawn) and against every cloud on the page; if no spot near the cloud
# passes, there is no box and the finding keeps its comment. Covering part of a
# drawing to say how to fix another part is not a trade this writer makes.
#
# The stamp is the sheet's legend: how many markups, that each has a comment,
# and how many show their action. It is page content on its own layer rather
# than an annotation, so it adds no row to the Markups List and can be switched
# off with the layer.
# --------------------------------------------------------------------------- #

_INSTR_FONTSIZE = 12.0                  # a step above sheet notes: meant to be seen
_INSTR_LINE_H = 14.5
_INSTR_PAD = 4.0
_INSTR_BORDER_W = 1.5
# Box shapes to try, widest first: one long line reads best, but a dense sheet
# often has room only for a narrower, taller box.
_INSTR_TEXT_WIDTHS = (290.0, 200.0, 140.0)
_INSTR_GAPS = (26.0, 64.0, 120.0, 200.0)   # how far from the cloud to look, nearest first
_INSTR_KNEE = 10.0                      # the leader's horizontal run out of the box
_PLACE_EDGE_MARGIN = 8.0
_PLACE_CLEARANCE = 3.0                  # padding a candidate is tested with

_STAMP_FONTSIZE = 8.0
_STAMP_LINE_H = 10.5
_STAMP_PAD = 5.0
_STAMP_MAX_TEXT_W = 250.0
_STAMP_INSETS = (16.0, 40.0, 80.0, 140.0)
_SHEET_NOTES_LAYER = "QC markups - Sheet notes"


def _wrap_lines(text: str, width: float, *, fontsize: float, fontname: str = "helv") -> list[str]:
    """``text`` broken greedily at spaces into lines no wider than ``width``.

    Measured with the same metrics the text is drawn with. A single word wider
    than ``width`` keeps a line to itself rather than being split.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}" if current else word
        if current and pymupdf.get_text_length(trial, fontname=fontname, fontsize=fontsize) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _text_box_size(
    lines: list[str], *, fontsize: float, line_h: float, pad: float, fontname: str = "helv",
) -> "tuple[float, float]":
    widest = max(
        (pymupdf.get_text_length(ln, fontname=fontname, fontsize=fontsize) for ln in lines),
        default=0.0,
    )
    # A little slack on the width, so the viewer's own wrapping of the same
    # text cannot push a word onto an extra line the box has no room for.
    return widest + 2.0 * pad + 8.0, len(lines) * line_h + 2.0 * pad


def _is_clear(
    box: "tuple[float, float, float, float]", page_w: float, page_h: float,
    occupied: Any, taken: "list[tuple[float, float, float, float]]",
) -> bool:
    """Whether ``box`` (view space) is on the page and covers nothing."""
    m = _PLACE_EDGE_MARGIN
    if box[0] < m or box[1] < m or box[2] > page_w - m or box[3] > page_h - m:
        return False
    c = _PLACE_CLEARANCE
    padded = (box[0] - c, box[1] - c, box[2] + c, box[3] + c)
    return not _rect_overlaps_any(padded, taken) and not occupied(padded)


def _place_near(
    target: "tuple[float, float, float, float]",
    shapes: "list[tuple[float, float]]",
    page_w: float, page_h: float, occupied: Any,
    taken: "list[tuple[float, float, float, float]]",
    words: "list[tuple[float, float, float, float]]",
) -> "tuple[float, float, float, float] | None":
    """A clear box beside ``target`` in one of ``shapes`` (w, h), or ``None``.

    Nearest distance first; at each distance every shape, widest first, in the
    eight positions around the target, the right-hand side first (where a note
    is read next). A position counts only if its leader has a clear run too.
    """
    x0, y0, x1, y1 = target
    xc, yc = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    for gap in _INSTR_GAPS:
        for w, h in shapes:
            for bx, by in (
                (x1 + gap, yc - h / 2.0), (x1 + gap, y0 - gap - h), (x1 + gap, y1 + gap),
                (xc - w / 2.0, y0 - gap - h), (xc - w / 2.0, y1 + gap),
                (x0 - gap - w, yc - h / 2.0), (x0 - gap - w, y0 - gap - h),
                (x0 - gap - w, y1 + gap),
            ):
                box = (bx, by, bx + w, by + h)
                if not _is_clear(box, page_w, page_h, occupied, taken):
                    continue
                tip, knee, _start = _leader_points(box, target)
                if _leader_is_clear(tip, knee, words, taken, target):
                    return box
    return None


def _leader_is_clear(
    tip: "tuple[float, float]", knee: "tuple[float, float]",
    words: "list[tuple[float, float, float, float]]",
    taken: "list[tuple[float, float, float, float]]",
    target: "tuple[float, float, float, float]",
) -> bool:
    """Whether the leader's run from its knee to the target crosses no text
    and no other markup.

    A leader may cross linework — drafting leaders do — but not a label, and
    not another finding's cloud or box (``taken``, minus its own target). The
    box itself is held to the stricter rule: it covers no ink at all.
    """
    blockers = [r for r in taken if r != target] + words
    for t in (0.0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9):
        px = knee[0] + (tip[0] - knee[0]) * t
        py = knee[1] + (tip[1] - knee[1]) * t
        if _rect_overlaps_any((px - 2.0, py - 2.0, px + 2.0, py + 2.0), blockers):
            return False
    return True


def _leader_points(
    box: "tuple[float, float, float, float]", target: "tuple[float, float, float, float]",
) -> "tuple[tuple[float, float], tuple[float, float], tuple[float, float]]":
    """``(tip, knee, start)`` of a callout leader from ``box`` to ``target``.

    The leader leaves the middle of the box edge that faces the target, runs
    straight for a short knee, then goes to the nearest point of the target.
    """
    bx0, by0, bx1, by1 = box
    tx0, ty0, tx1, ty1 = target
    bxc, byc = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
    if bx0 >= tx1:
        start, knee = (bx0, byc), (bx0 - _INSTR_KNEE, byc)
    elif bx1 <= tx0:
        start, knee = (bx1, byc), (bx1 + _INSTR_KNEE, byc)
    elif by0 >= ty1:
        start, knee = (bxc, by0), (bxc, by0 - _INSTR_KNEE)
    else:
        start, knee = (bxc, by1), (bxc, by1 + _INSTR_KNEE)
    tip = (min(max(knee[0], tx0), tx1), min(max(knee[1], ty0), ty1))
    return tip, knee, start


def _add_instructions(
    page: "pymupdf.Page",
    items: "list[tuple[Finding, MarkupPlacement, str]]",
    *,
    author: str,
    occupied: Any,
    taken: "list[tuple[float, float, float, float]]",
    words: "list[tuple[float, float, float, float]] | None" = None,
    oc_layers: "dict[str, int] | None" = None,
) -> "dict[str, list[tuple[str, int]]]":
    """Draw each ``(finding, placement, instruction)`` as a callout by its cloud.

    Returns ``{placement_id: [("instruction", xref)]}`` for the ones that found
    a clear spot. ``taken`` (view-space boxes this page must not cover) grows
    with every box placed, so two instructions never overlap. One failed box
    never drops another.
    """
    drawn: dict[str, list[tuple[str, int]]] = {}
    page_w, page_h = page.rect.width, page.rect.height
    rotate = int(page.rotation or 0)
    for finding, placement, instruction in items:
        try:
            head = f"{finding.qc_id}: " if finding.qc_id else ""
            wording = _base14_safe(head + instruction.upper())
            layouts: dict[tuple[float, float], list[str]] = {}
            for text_w in _INSTR_TEXT_WIDTHS:
                wrapped = _wrap_lines(wording, text_w, fontsize=_INSTR_FONTSIZE)
                layouts.setdefault(_text_box_size(
                    wrapped, fontsize=_INSTR_FONTSIZE, line_h=_INSTR_LINE_H, pad=_INSTR_PAD,
                ), wrapped)
            target = tuple(float(v) for v in finding.anchor.rect_pdf)
            box = _place_near(
                target, list(layouts), page_w, page_h, occupied, taken, words or [],
            )
            if box is None:
                continue
            lines = layouts[(box[2] - box[0], box[3] - box[1])]
            text = "\n".join(lines)
            tip, knee, start = _leader_points(box, target)
            annot = page.add_freetext_annot(
                _derotate_rect(page, box), text,
                fontsize=_INSTR_FONTSIZE, text_color=_color(finding), fill_color=(1, 1, 1),
                border_width=_INSTR_BORDER_W, rotate=rotate,
                callout=[_derotate_point(page, *pt) for pt in (tip, knee, start)],
                line_end=pymupdf.PDF_ANNOT_LE_OPEN_ARROW,
            )
            # For FreeText /Contents IS the displayed text: hand back the same string.
            annot.set_info(title=author, subject=_subject(finding), content=text)
            _assign_layer(annot, finding, oc_layers)
            annot.update()
            taken.append(box)
            drawn.setdefault(placement.placement_id, []).append(("instruction", annot.xref))
        except Exception:  # noqa: BLE001 - the comment still carries the action
            _log.warning("could not draw the instruction for finding %s", finding.id)
    return drawn


def _stamp_text(marks: int, shown: int, all_have_actions: bool) -> str:
    """The sheet stamp's words. Says only what is true of this sheet."""
    parts = [
        f"AI DRAFT REVIEW - {marks} MARKUP{'' if marks == 1 else 'S'} ON THIS SHEET.",
        "Every markup has a comment with a suggested action; open one to read it."
        if all_have_actions else "Every markup has a comment; open one to read it.",
    ]
    if shown:
        parts.append(
            f"{shown} show{'s' if shown == 1 else ''} the required action on the sheet."
        )
    return " ".join(parts)


def _place_stamp(
    w: float, h: float, page_w: float, page_h: float, occupied: Any,
    taken: "list[tuple[float, float, float, float]]",
) -> "tuple[float, float, float, float] | None":
    """A clear spot for the stamp, out of the way: a corner first, bottom-left
    before the rest, stepping in past the sheet border; then along the bottom
    and top edges."""
    for inset in _STAMP_INSETS:
        for bx, by in (
            (inset, page_h - inset - h), (inset, inset),
            (page_w - inset - w, inset), (page_w - inset - w, page_h - inset - h),
        ):
            box = (bx, by, bx + w, by + h)
            if _is_clear(box, page_w, page_h, occupied, taken):
                return box
    for inset in _STAMP_INSETS[:2]:
        for by in (page_h - inset - h, inset):
            bx = inset
            while bx + w <= page_w - inset:
                box = (bx, by, bx + w, by + h)
                if _is_clear(box, page_w, page_h, occupied, taken):
                    return box
                bx += w / 2.0
    return None


def _add_sheet_stamp(
    page: "pymupdf.Page", text: str, *, layer: int, occupied: Any,
    taken: "list[tuple[float, float, float, float]]",
) -> bool:
    """Draw the stamp on ``page`` as layered page content; ``False`` if no room."""
    lines = _wrap_lines(_base14_safe(text), _STAMP_MAX_TEXT_W, fontsize=_STAMP_FONTSIZE)
    w, h = _text_box_size(
        lines, fontsize=_STAMP_FONTSIZE, line_h=_STAMP_LINE_H, pad=_STAMP_PAD,
    )
    box = _place_stamp(w, h, page.rect.width, page.rect.height, occupied, taken)
    if box is None:
        return False
    page.draw_rect(
        _derotate_rect(page, box), color=(0.35, 0.35, 0.35), fill=(1, 1, 1),
        width=0.6, oc=layer,
    )
    inner = (box[0] + _STAMP_PAD, box[1] + _STAMP_PAD - 1.0,
             box[2] - _STAMP_PAD, box[3] + _STAMP_LINE_H)   # room below: never clip a line
    page.insert_textbox(
        _derotate_rect(page, inner), "\n".join(lines),
        fontsize=_STAMP_FONTSIZE, lineheight=_STAMP_LINE_H / _STAMP_FONTSIZE,
        color=(0.2, 0.2, 0.2), rotate=int(page.rotation or 0), oc=layer,
    )
    taken.append(box)
    return True


def _add_instructions_and_stamps(
    doc: "pymupdf.Document",
    pairs: "list[tuple[Finding, MarkupPlacement]]",
    collected: "dict[str, list[tuple[str, int, int]]]",
    *,
    author: str,
    oc_layers: "dict[str, int] | None",
    sheet_meta: "dict[int, dict] | None" = None,
) -> None:
    """After the clouds and callouts: the instruction boxes, then each sheet's stamp.

    Mutates ``collected`` with the ``instruction`` components it draws. Nothing
    here is mandatory to any placement, so every failure is logged and skipped
    (I-3): a sheet without a stamp or a finding without its box is still a
    complete, correct markup.
    """
    finding_by_pid = {pl.placement_id: f for f, pl in pairs}
    taken_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    wanted: dict[int, list[tuple[Finding, MarkupPlacement, str]]] = {}
    for finding, placement in pairs:
        if placement.expected != "CLOUD" or not collected.get(placement.placement_id):
            continue
        page_index = int(finding.page_index)
        taken_by_page.setdefault(page_index, []).append(
            tuple(float(v) for v in finding.anchor.rect_pdf)
        )
        instruction = on_sheet_instruction(finding)
        if instruction:
            wanted.setdefault(page_index, []).append((finding, placement, instruction))

    samplers: dict[int, Any] = {}

    def sampler(page_index: int) -> Any:
        # Rendered on first use, i.e. with every cloud and callout already on
        # the page; boxes drawn after that are tracked in ``taken_by_page``.
        if page_index not in samplers:
            samplers[page_index] = _page_occupancy(doc[page_index])
        return samplers[page_index]

    for page_index, items in sorted(wanted.items()):
        items.sort(key=lambda it: (it[0].qc_id or "~", it[0].id))
        try:
            meta = (sheet_meta or {}).get(page_index) or {}
            drawn = _add_instructions(
                doc[page_index], items, author=author, oc_layers=oc_layers,
                occupied=sampler(page_index), taken=taken_by_page[page_index],
                words=[
                    tuple(float(v) for v in word[:4]) for word in (meta.get("words") or [])
                ],
            )
            for pid, comps in drawn.items():
                collected.setdefault(pid, []).extend((c, x, page_index) for c, x in comps)
        except Exception:  # noqa: BLE001
            _log.warning("could not add instructions on page %d", page_index)

    marks: dict[int, set[str]] = {}
    shown: dict[int, int] = {}
    for pid, comps in collected.items():
        for component, _xref, page_index in comps:
            if component in ("cloud", "callout"):
                marks.setdefault(page_index, set()).add(pid)
            elif component == "instruction":
                shown[page_index] = shown.get(page_index, 0) + 1
    if not marks:
        return
    try:
        layer = doc.add_ocg(_SHEET_NOTES_LAYER, on=True)
    except Exception:  # noqa: BLE001 - no layer, no stamp; the markups stand
        _log.warning("could not create the sheet-notes layer; sheets carry no stamp")
        return
    for page_index, pids in sorted(marks.items()):
        try:
            text = _stamp_text(
                len(pids), shown.get(page_index, 0),
                all(pid in finding_by_pid and _action_text(finding_by_pid[pid]) for pid in pids),
            )
            if not _add_sheet_stamp(
                doc[page_index], text, layer=layer, occupied=sampler(page_index),
                taken=taken_by_page.setdefault(page_index, []),
            ):
                _log.info("no clear spot for the sheet stamp on page %d", page_index)
        except Exception:  # noqa: BLE001
            _log.warning("could not stamp page %d", page_index)


# --------------------------------------------------------------------------- #
# Index + appendix pages
# --------------------------------------------------------------------------- #


def _what_to_do(finding: Finding) -> str:
    """One cover-page line for a finding: the action first, then what is wrong.

    The action leads because the row is a to-do item — the action-plan pass's
    short instruction when there is one, else the reviewing channel's own
    sentence. The finding text follows so the row still says what the problem
    is when the action alone would not ("Coordinate with structural"). A
    finding that was not confirmed starts with ``VERIFY:``
    (:func:`models.needs_verify`) — the page's only status signal.
    """
    text = " ".join((finding.text or "").split())
    plan = getattr(finding, "action", None)
    action = " ".join(str(getattr(plan, "instruction", "") or "").split()) or " ".join(
        (getattr(finding, "recommended_action", "") or "").split()
    )
    line = f"{action} - {text}" if action and text else (action or text)
    return (_VERIFY_PREFIX if needs_verify(finding) else "") + line


# Severity triage rank for the reviewed-PDF index (§18.7, DA-025): high, then
# medium, then everything else (low / question-tier / unset) together.
_INDEX_SEVERITY_RANK = {"high": 0, "medium": 1}


def _severity_first_key(finding: Finding) -> tuple:
    """The §18.7 index/display sort key: actionable order, stable ids intact.

    Severity tier first (high → medium → low/question), then the run's source
    input order (the zero-padded ``SRC-####`` sorts by assignment order), page,
    anchored-before-unanchored, top→left position, and finally the stable
    ``QC-###`` / finding id as the deterministic tie-break (I-7). Display order
    deliberately need NOT be numeric QC-id order — the ids themselves never
    change (§18.7).
    """
    anchor = getattr(finding, "anchor", None)
    rect = getattr(anchor, "rect_pdf", None) if anchor is not None else None
    y, x = (float(rect[1]), float(rect[0])) if rect else (0.0, 0.0)
    return (
        _INDEX_SEVERITY_RANK.get((finding.severity or "").lower(), 2),
        finding.source_id or finding.source_name or "~",
        int(finding.page_index or 0),
        rect is None,
        y,
        x,
        finding.qc_id or "~",
        finding.id,
    )


def _index_groups(
    pairs: "list[tuple[Finding, MarkupPlacement]]",
) -> "tuple[list, list, list]":
    """``(inked, rejected, gated)`` (finding, placement) rows in triage order.

    The main table lists the open findings that are on paper. ``rejected`` is
    non-empty only when the run chose to ink ruled-out findings
    (``ink_rejected``): they are drawn grey on the sheets, so the cover lists
    them, apart, under "Ruled out". Otherwise a ruled-out finding is
    ``REPORT_ONLY`` and appears in none of the three — it is not in the PDF.
    ``gated`` is the verified-only mode's findings: a gated finding's index row
    is its **sole artifact**, so it must exist and be reconciled. Rows sort
    severity-first within every section (§18.7): the page is read top-down as
    a punch list.
    """
    def _order(items: list) -> list:
        return sorted(items, key=lambda fp: _severity_first_key(fp[0]))

    inked, rejected, gated = [], [], []
    for finding, placement in pairs:
        if placement.expected == "GATED_INDEX":
            gated.append((finding, placement))
        elif placement.expected in ("CLOUD", "MARGIN", "REVIEW_NOTES"):
            if _status(finding) == "REJECTED":
                rejected.append((finding, placement))
            else:
                inked.append((finding, placement))
    return _order(inked), _order(rejected), _order(gated)


def _new_generated_page(doc: "pymupdf.Document", *, pno: int | None = None) -> "pymupdf.Page":
    """A fresh analyzer-owned page at the standard index/notes size.

    Pins an explicit ``CropBox`` equal to the page's own ``MediaBox`` (P7
    item 34). ``/CropBox`` is an **inheritable** page-tree attribute, so in a set
    whose ``/Pages`` node carries one -- legal, and produced by some CAD exporters
    -- a generated page inherits the *drawing's* CropBox. Measured on an E-size
    source cropped to ``[100 80 1628 1108]``: a new 612x792 page came back with
    ``cropbox=[100, -316, 1628, 712]`` and a visible ``rect`` of **512x712**, so
    the index table was clipped on the right and shifted vertically -- and the
    column widths item 32 fits against are computed for the full 612. Setting the
    CropBox explicitly makes the page mean what it says regardless of the source's
    page tree. (``/Rotate`` is inheritable too, but PyMuPDF writes it explicitly
    on a new page, so it does not need pinning -- verified, not assumed.)
    """
    page = (
        doc.new_page(width=_INDEX_PAGE_W, height=_INDEX_PAGE_H) if pno is None
        else doc.new_page(pno=pno, width=_INDEX_PAGE_W, height=_INDEX_PAGE_H)
    )
    try:
        page.set_cropbox(page.mediabox)
    except Exception:  # noqa: BLE001 - a page that will not take one is still usable
        _log.warning("could not pin the CropBox on a generated page")
    return page


def _omitted_note(omitted: "list[str]") -> str:
    """The cover's one line about QC numbers it does not list ("" for none).

    QC numbers are assigned before the re-check, so a finding it rules out
    leaves a gap in the list. Saying where the number went costs one line;
    leaving the reader to wonder whether a finding was lost costs their trust.
    """
    ids = sorted({qc for qc in omitted if qc})
    if not ids:
        return ""
    shown = ", ".join(ids[:6]) + (f" and {len(ids) - 6} more" if len(ids) > 6 else "")
    verb = "was" if len(ids) == 1 else "were"
    return f"Not listed: {shown} {verb} ruled out on re-check. See the HTML report."


def _index_rows(
    inked: list, rejected: list, gated: list, omitted: "list[str] | None" = None,
) -> "list[tuple[str, Any, bool]]":
    """The uniform index row stream, shared by the page count and the writer.

    The open findings are listed in the three to-do groups, in
    :data:`~drawing_analyzer.models.ACTION_BUCKETS` order, each under a
    ``("bucket", label, False)`` row; a group with nothing in it is not shown.
    When the action-plan pass did not rank a finding its group is its
    severity's, and the page says so in one line rather than passing a
    fallback off as a judgment. ``("bucket", …)``, ``("heading", …)`` and
    ``("note", …)`` rows carry no link; ``index_only`` marks the
    rows whose sole artifact is this index row (so reconciliation must find them).
    One builder, so the page count cannot disagree with what is written (P7
    item 34: the count has to be known *before* any page is inserted, because
    inserting at the front renumbers every link target).
    """
    rows: list[tuple[str, Any, bool]] = []
    unranked = {fp[1].finding_id for fp in inked if not bucket_is_ranked(fp[0])}
    if unranked:
        listed = {fp[1].finding_id for fp in inked}
        rows.append(("note", (
            "Grouped by severity." if len(unranked) == len(listed)
            else f"{len(unranked)} of {len(listed)} findings are grouped by severity."
        ), False))
    for bucket in ACTION_BUCKETS:
        group = [fp for fp in inked if action_bucket(fp[0]) == bucket]
        if not group:
            continue
        count = len({fp[1].finding_id for fp in group})     # a leg is not a finding
        rows.append(("bucket", f"{ACTION_BUCKET_LABELS[bucket]} ({count})", False))
        rows.extend(("entry", fp, False) for fp in group)
    if rejected:
        rows.append(("heading", f"Ruled out ({len(rejected)})", False))
        rows.extend(("rejected", fp, False) for fp in rejected)
    if gated:
        rows.append(("heading", f"Not marked on the sheets ({len(gated)})", False))
        rows.extend(("gated", fp, True) for fp in gated)
    note = _omitted_note(omitted or [])
    if note and rows:
        rows.append(("note", note, False))
    return rows


def _index_page_count(rows: "list[tuple[str, Any, bool]]") -> int:
    """How many index pages ``rows`` needs (0 for none)."""
    if not rows:
        return 0
    return (len(rows) + _INDEX_ROWS_PER_PAGE - 1) // _INDEX_ROWS_PER_PAGE


def _insert_index_pages(
    doc: "pymupdf.Document",
    inked: list,
    rejected: list,
    gated: list,
    *,
    run_id: str,
    marks: "dict[str, tuple[int, int]] | None" = None,
    omitted: "list[str] | None" = None,
) -> int:
    """Insert the findings index at the front of ``doc``; return pages inserted.

    Every finding row carries a GOTO link that zooms onto its markup
    (:func:`_mark_dest`). ``marks`` maps a placement id to ``(page, xref)`` —
    the page its mark landed on, as numbered **before** this insertion, and the
    mark's annotation — so a row lands on the mark itself rather than on where
    the finding was expected to be. ``rejected`` entries follow the main table
    under "Ruled out" and ``gated`` entries under "Not marked on the sheets";
    ``omitted`` is the QC numbers the cover does not list (:func:`_omitted_note`).
    Link targets are offset by the number of index pages, which is computed
    **before** any page is inserted (inserting at the front shifts every
    original page down).

    Each generated index page is stamped analyzer-owned (:data:`_INDEX_PAGE_KEY`
    == ``run_id``), and the **index-only** placements it hosts (GATED_INDEX rows
    — the ones whose only artifact is the index) are recorded in
    :data:`_INDEX_ROWS_KEY` as ``pid@target`` so reconciliation can prove each
    row exists and links to the right page.
    """
    rows = _index_rows(inked, rejected, gated, omitted)
    n_pages = _index_page_count(rows)
    if not n_pages:
        return 0
    marks = marks or {}

    # Insert EVERY index page before drawing any rows: link targets are numbered
    # for the final document, so drawing while later index pages are still
    # missing would make those targets fail the bounds guard and silently drop
    # the first page's links on a multi-page index. Pages are re-fetched by
    # index below — inserting a page invalidates previously-held Page objects.
    for i in range(n_pages):
        _new_generated_page(doc, pno=i)
    for i in range(n_pages):
        page = doc[i]
        title = INDEX_PAGE_LABEL + (f"  (page {i + 1}/{n_pages})" if n_pages > 1 else "")
        page.insert_text((36, 42), title, fontsize=13, fontname="hebo", color=(0.1, 0.1, 0.1))
        page.insert_text(
            (36, 60),
            _fit_text(_INDEX_SUBTITLE, _INDEX_COL_RIGHT - 36.0, fontsize=8),
            fontsize=8, color=(0.35, 0.35, 0.35),
        )
        # Column headers.
        y = _INDEX_TOP - 8
        for x, label in zip(_INDEX_COL_X, _INDEX_COL_LABELS):
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
            if kind in ("heading", "bucket"):
                # A to-do group is the page's structure; the two trailing
                # sections (ruled out, not marked) are quieter.
                size, shade = (10, 0.1) if kind == "bucket" else (9, 0.3)
                page.insert_text((36, y), str(payload), fontsize=size, fontname="hebo",
                                 color=(shade, shade, shade))
                y += _INDEX_ROW_H
                continue
            if kind == "note":
                page.insert_text(
                    (36, y), _fit_text(str(payload), _INDEX_COL_RIGHT - 36.0, fontsize=8),
                    fontsize=8, color=(0.35, 0.35, 0.35),
                )
                y += _INDEX_ROW_H
                continue
            finding, placement = payload
            struck = kind in ("rejected", "gated")
            color = _REJECTED_COLOR if struck else _color(finding)
            text_color = _REJECTED_COLOR if struck else (0, 0, 0)
            # Every cell is fitted to its own column width and made Base-14 safe
            # (item 32): a character cap is not a width fit, and a glyph the
            # Base-14 fonts lack is drawn as a middle dot rather than raising.
            cells = (
                (finding.qc_id or "-", "hebo", color),
                (finding.sheet_id or "", "helv", text_color),
                (_what_to_do(finding), "helv", text_color),
            )
            for x, cw, (raw, fontname, cell_color) in zip(_INDEX_COL_X, _INDEX_COL_W, cells):
                page.insert_text(
                    (x, y), _fit_text(raw, cw, fontsize=8, fontname=fontname),
                    fontsize=8, fontname=fontname, color=cell_color,
                )

            # The page the mark ACTUALLY landed on, not the finding's source page
            # (P7 item 34). A callout that overflowed to the AI Review Notes page
            # has no mark on its sheet, so a row pointing at the sheet sent the
            # reviewer to a page with nothing on it. Every page in ``marks``
            # predates the front-inserted index, so all of them shift by exactly
            # ``n_pages``, the same as a source page.
            mark_page, mark_xref = marks.get(placement.placement_id, (None, None))
            target_page = int(
                mark_page if mark_page is not None else finding.page_index
            ) + n_pages
            rect = getattr(finding.anchor, "rect_pdf", None) if finding.anchor else None
            if 0 <= target_page < doc.page_count:
                row_top = y - 9
                _insert_goto_link(
                    doc, page,
                    pymupdf.Rect(34, row_top, _INDEX_PAGE_W - 34, y + 3),
                    target_page,
                    _mark_dest(doc, target_page, mark_xref=mark_xref, view_rect=rect),
                )
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


def _insert_appendix_page(doc: "pymupdf.Document", audit_stats: dict | None) -> None:
    """The optional 'checked and consistent' page at the end of the document."""
    stats = audit_stats or {}
    page = _new_generated_page(doc)
    page.insert_text((36, 42), APPENDIX_PAGE_LABEL, fontsize=13, fontname="hebo", color=(0.1, 0.1, 0.1))
    page.insert_text(
        (36, 60),
        _fit_text("Checks that passed.", _INDEX_COL_RIGHT - 36.0, fontsize=8),
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


def _insert_review_notes_page(
    doc: "pymupdf.Document",
    overflow: "list[tuple[Finding, MarkupPlacement]]",
    *,
    run_id: str,
    author: str,
    oc_layers: "dict[str, int] | None" = None,
) -> "dict[str, list[tuple[str, int, int]]]":
    """Append an 'AI Review Notes' page carrying the callouts that did not fit.

    A rect-less finding whose callout could not be placed in a visually-clear band
    (§17.6) is written here — visible ink in the reviewed PDF — instead of stamped
    over the drawing. Each row is a ``callout`` FreeText carrying the full popup,
    plus a GOTO link back to its source page — by that page's index in the
    document as it stands when this runs, since the index pages are inserted
    afterwards and carry the link's target along with the page —
    and its placement is **rerouted** to ``REVIEW_NOTES`` so the tally counts it as
    an overflow note, not a margin callout. Returns
    ``{placement_id: [(component, xref, final_page), …]}`` for stamping. The
    ``callout`` component is reconciled exactly like a margin callout — one logical
    placement, one mandatory component — keeping this per-source overflow page
    distinct from the set-level ``Drawing_Set_Review_Notes.pdf``.
    """
    collected: dict[str, list[tuple[str, int, int]]] = {}
    if not overflow:
        return collected
    # Same severity-first triage order as the index pages (§18.7).
    ordered = sorted(overflow, key=lambda fp: _severity_first_key(fp[0]))
    per_page = _NOTES_PER_PAGE
    n_pages = (len(ordered) + per_page - 1) // per_page
    first_pno = doc.page_count
    for _ in range(n_pages):
        _new_generated_page(doc)
    for i in range(n_pages):
        pno = first_pno + i
        page = doc[pno]
        title = REVIEW_NOTES_PAGE_LABEL + (f"  (page {i + 1}/{n_pages})" if n_pages > 1 else "")
        page.insert_text((_NOTE_LEFT, 42), title, fontsize=12, fontname="hebo", color=(0.1, 0.1, 0.1))
        page.insert_text(
            (_NOTE_LEFT, 62),
            _fit_text(
                "These notes had no clear space on their sheet. "
                "Click a note to jump to its sheet.",
                _INDEX_PAGE_W - 2 * _NOTE_LEFT, fontsize=8,
            ),
            fontsize=8, color=(0.35, 0.35, 0.35),
        )
        batch = ordered[i * per_page:(i + 1) * per_page]
        y = _NOTE_TOP
        for finding, placement in batch:
            rejected = _status(finding) == "REJECTED"
            unverified = _is_unverified(finding) and not rejected
            content = (
                f"{finding.qc_id or '-'}  [{finding.sheet_id} / {finding.severity}]\n"
                + _annot_content(
                    finding, unverified=unverified, rejected=rejected,
                    place=_placement_kind(finding),
                )
            )
            box = pymupdf.Rect(_NOTE_LEFT, y, _INDEX_PAGE_W - _NOTE_LEFT, y + _NOTE_BOX_H)
            try:
                shown = _truncate_at_word(content, 400)     # reused below (item 33)
                annot = page.add_freetext_annot(
                    box, shown, fontsize=8,
                    text_color=(_REJECTED_COLOR if rejected else _color(finding)),
                    fill_color=(1.0, 1.0, 0.92),
                )
                annot.set_info(title=author, subject=_subject(finding), content=shown)
                _assign_layer(annot, finding, oc_layers)
                annot.update()
                collected.setdefault(placement.placement_id, []).append(
                    ("callout", annot.xref, pno)
                )
                # GOTO back to the source page — its index in the document as it
                # stands RIGHT NOW, with no allowance for the index pages that are
                # inserted afterwards. The destination names the page *object*, so
                # the front insertion carries the link's target along with the
                # page itself and the offset must not be pre-applied.
                target = int(finding.page_index)
                if 0 <= target < doc.page_count:
                    rect = getattr(finding.anchor, "rect_pdf", None) if finding.anchor else None
                    _insert_goto_link(
                        doc, page, pymupdf.Rect(box.x0, box.y0, box.x1, box.y1),
                        target, _mark_dest(doc, target, view_rect=rect),
                    )
            except Exception:  # noqa: BLE001 - one bad note never sinks the file
                _log.warning("could not draw review note for %s", finding.id)
            # Reroute the placement so the receipt/tally reflect where it went.
            placement.expected = "REVIEW_NOTES"
            placement.required_components = list(REQUIRED_COMPONENTS["REVIEW_NOTES"])
            y += _NOTE_BOX_H + _NOTE_GAP
    return collected


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
    "REPORT_ONLY": "rejected",
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
    if placement.expected == "REPORT_ONLY":
        # Nothing was planned for the PDF, so there is nothing to find again:
        # the finding is carried by findings.csv and the HTML report.
        return MarkupReceipt(placement, "REPORTED")
    if placement.expected == "GATED_INDEX":
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


def _set_findings_outline(
    doc: "pymupdf.Document",
    pairs: "list[tuple[Finding, MarkupPlacement]]",
    final_page_by_pid: "dict[str, int]",
    *,
    n_index: int,
    mark_xref_by_pid: "dict[str, int] | None" = None,
) -> None:
    """Write a ``QC Findings`` bookmark outline into ``doc`` (Phase: HTML↔PDF links).

    One bookmark per finding whose primary mark was actually drawn, filed under
    its to-do group as on the cover page and in ``QC-###`` order within it,
    whose destination is the page that mark **landed on**
    (``final_page_by_pid``, keyed by placement id: the source page for an
    on-sheet cloud/margin callout, the appended *AI Review Notes* page for one
    that overflowed there), so a bookmark always points at the mark, the same
    page its HTML deep link and receipt point at. Each bookmark zooms onto the
    mark exactly as its cover-page row does (:func:`_mark_dest`):
    ``mark_xref_by_pid`` names the drawn annotation, and a finding without one
    falls back to its anchor rectangle, then to the whole page. ``set_toc``
    can only write a point destination, so the entries are created as plain
    page jumps and their destinations replaced afterwards.

    Any outline already on the source PDF (a set's sheet-navigation bookmarks)
    is **preserved** — the QC section is appended, never substituted: the writer
    annotates the original document, whose outline must survive into the review
    copy. Bluebeam and Acrobat surface the merged outline in their Bookmarks
    panel, making the marked-up set self-navigable independent of the HTML
    report. No-op when no finding's mark was drawn.
    """
    page_count = doc.page_count
    mark_xref_by_pid = mark_xref_by_pid or {}
    seen: set[str] = set()
    entries: list[tuple[Finding, int, "int | None", str]] = []
    for finding, placement in pairs:
        # One bookmark per finding, at its own anchor — not per cross-sheet leg
        # or margin/index placement (those share the finding's qc_id).
        if placement.leg_id != PRIMARY_LEG_ID or finding.id in seen:
            continue
        if placement.expected == "REPORT_ONLY":
            continue                      # ruled out: not in the PDF, bookmarks included
        # The page the mark actually landed on (overflow → notes page); fall
        # back to the source page + front-index offset when the placement drew
        # nothing recorded (defensive — such a finding has no mark to point at).
        final_page = final_page_by_pid.get(placement.placement_id)
        if final_page is None:
            page_index = int(getattr(finding, "page_index", -1))
            final_page = page_index + n_index if page_index >= 0 else -1
        if not (0 <= final_page < page_count):
            continue
        seen.add(finding.id)
        kind = (
            "gated" if placement.expected == "GATED_INDEX"
            else "rejected" if _status(finding) == "REJECTED" else "open"
        )
        entries.append(
            (finding, final_page, mark_xref_by_pid.get(placement.placement_id), kind)
        )
    if not entries:
        return
    entries.sort(key=lambda e: (e[0].qc_id or "~", e[0].id))

    parent_page = 1 if n_index > 0 else entries[0][1] + 1     # index page, else first mark
    qc_toc: list = [[1, f"QC Findings ({len(entries)})", parent_page]]
    # Grouped as the cover page is: one folder per to-do group, then a folder
    # for anything drawn but not an open item (a ruled-out finding inked grey,
    # or a finding listed without a mark).
    groups: "list[tuple[str, list]]" = [
        (ACTION_BUCKET_LABELS[bucket], [
            e for e in entries
            if e[3] == "open" and action_bucket(e[0]) == bucket
        ])
        for bucket in ACTION_BUCKETS
    ]
    groups.append(("Ruled out", [e for e in entries if e[3] == "rejected"]))
    groups.append(("Not marked on the sheets", [e for e in entries if e[3] == "gated"]))
    leaves: "list[tuple[int, Finding, int, int | None]]" = []   # (toc index, …)
    for label, members in groups:
        if not members:
            continue
        qc_toc.append([2, f"{label} ({len(members)})", members[0][1] + 1])
        for finding, final_page, mark_xref, _kind in members:
            qc = finding.qc_id or "QC-?"
            sheet = (finding.sheet_id or "").strip()
            text = _what_to_do(finding)
            if len(text) > 70:
                text = text[:67].rstrip() + "…"
            title = f"[{qc}] " + (f"{sheet} — {text}" if sheet else text) if text else f"[{qc}] {sheet}".rstrip()
            leaves.append((len(qc_toc), finding, final_page, mark_xref))
            qc_toc.append([3, title, final_page + 1])
    # Append after the source PDF's own outline (get_toc(simple=False) round-
    # trips through set_toc), so existing sheet bookmarks survive the review copy.
    existing = doc.get_toc(simple=False) or []
    doc.set_toc(existing + qc_toc)

    # Our items are the last ``len(qc_toc)`` outline objects, in the order
    # written. A failure here leaves that bookmark a plain page jump.
    outline_xrefs = doc.get_outline_xrefs()[-len(qc_toc):]
    for toc_index, finding, final_page, mark_xref in leaves:
        try:
            rect = getattr(finding.anchor, "rect_pdf", None) if finding.anchor else None
            dest = _mark_dest(doc, final_page, mark_xref=mark_xref, view_rect=rect)
            doc.xref_set_key(outline_xrefs[toc_index], "A", f"<</S/GoTo/D{dest}>>")
        except Exception:  # noqa: BLE001 - a coarser bookmark, never a lost one
            _log.debug("could not set a zoom destination for bookmark %s", finding.qc_id)


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
        # Severity layers (OCGs): one per severity tier that actually carries
        # drawable ink, so a reviewer can toggle a whole tier's markups in
        # Bluebeam/Acrobat/Chromium. Placements that draw nothing (REPORT_ONLY /
        # GATED_INDEX) need no layer. Created here,
        # once, before any ink; non-fatal (I-3) — an empty map draws everything
        # unlayered, exactly as before.
        tiers_present = {
            _severity_layer_tier(f)
            for f, pl in pairs
            if pl.expected in ("CLOUD", "MARGIN", "REVIEW_NOTES")
        }
        oc_layers = _create_severity_layers(doc, tiers_present) if tiers_present else {}
        callouts_by_page: dict[int, list[tuple[Finding, MarkupPlacement]]] = {}
        for finding, placement in pairs:
            kind = placement.expected
            if kind in ("REPORT_ONLY", "GATED_INDEX"):
                continue                              # no ink: report-only / index row
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
                        author=author, rejected=rejected, oc_layers=oc_layers,
                    )
                    collected.setdefault(placement.placement_id, []).extend(
                        (c, x, page_index) for c, x in comps
                    )
                except Exception:  # noqa: BLE001 - one bad annot must not sink the file
                    _log.warning("could not add markup for finding %s", finding.id)
            else:                                     # MARGIN / REVIEW_NOTES
                callouts_by_page.setdefault(page_index, []).append((finding, placement))

        overflow: list[tuple[Finding, MarkupPlacement]] = []
        for page_index, group in sorted(callouts_by_page.items()):
            group.sort(key=lambda fp: (fp[0].qc_id or "~", fp[0].id))
            try:
                drawn, page_overflow = _add_margin_callouts(
                    doc[page_index], group,
                    meta=(sheet_meta or {}).get(page_index), author=author,
                    oc_layers=oc_layers,
                )
                for pid, comps in drawn.items():
                    collected.setdefault(pid, []).extend(
                        (c, x, page_index) for c, x in comps
                    )
                overflow.extend(page_overflow)
            except Exception:  # noqa: BLE001 - callouts must not sink the file
                _log.warning("could not add margin callouts on page %d", page_index)

        # With every cloud and callout on its sheet: the instruction boxes that
        # have a clear spot beside their cloud, then each marked sheet's stamp.
        try:
            _add_instructions_and_stamps(
                doc, pairs, collected, author=author, oc_layers=oc_layers,
                sheet_meta=sheet_meta,
            )
        except Exception:  # noqa: BLE001 - never sinks the file
            _log.warning("could not add instructions / sheet stamps for %s", src.name)

        # Generated pages are built in this order — appendix, review notes, then
        # the index inserted at the FRONT last (P7 item 34). The index is last
        # because its rows link to the page each mark landed on, and an overflowed
        # callout's page does not exist until the notes page is appended. Building
        # the index first meant a row could only guess, so it named the finding's
        # source sheet — where that finding has no mark — while the bookmark
        # outline and the receipt both correctly named the notes page.
        #
        # Front-inserting the index last also makes the shift uniform: every page
        # written before it — source, appendix, notes — moves down by exactly
        # ``n_index``, so there is no page that needs a different offset. The
        # reading order of the finished file is unchanged (index, sheets,
        # appendix, notes), because the appendix is still appended before the
        # notes page.
        #
        # ``n_index`` is needed *before* insertion, for the notes page's back-links
        # and for these stamps, so it is computed from the row stream rather than
        # returned by the writer.
        index_row_stream: list = []
        index_groups: tuple = ((), (), ())
        # QC numbers the cover will not list: ruled out, so not in this PDF.
        omitted = [f.qc_id for f, pl in pairs if pl.expected == "REPORT_ONLY"]
        n_index = 0
        if index_pages:
            try:
                index_groups = _index_groups(pairs)
                index_row_stream = _index_rows(*index_groups, omitted)
                n_index = _index_page_count(index_row_stream)
            except Exception:  # noqa: BLE001 - the index must not sink the file
                _log.warning("could not plan the findings index for %s", src.name)
                index_row_stream, n_index = [], 0

        if include_appendix:
            try:
                _insert_appendix_page(doc, audit_stats)
            except Exception:  # noqa: BLE001
                _log.warning("could not build the appendix for %s", src.name)

        # Callouts that did not fit a clear band overflow to an appended
        # 'AI Review Notes' page (§17.6) rather than obscuring the drawing. Its
        # components carry their PRE-SHIFT page here, and shift by ``n_index``
        # below along with everything else.
        notes_collected: dict[str, list[tuple[str, int, int]]] = {}
        if overflow:
            try:
                notes_collected = _insert_review_notes_page(
                    doc, overflow, run_id=run_id, author=author,
                    oc_layers=oc_layers,
                )
            except Exception:  # noqa: BLE001 - the notes page must not sink the file
                _log.warning("could not build the review-notes page for %s", src.name)

        # Where each placement's mark actually sits — its page before the
        # front-insert shift, and the annotation itself, whose /Rect is what a
        # link zooms onto. The mandatory component is recorded first (the cloud
        # before its tag, the callout before its leader); the notes page
        # overrides the source page for a callout that overflowed there.
        marks: dict[str, tuple[int, int]] = {}
        for source in (collected, notes_collected):
            for pid, comps in source.items():
                for component, xref, page_no in comps:
                    if component in ("cloud", "callout"):
                        marks[pid] = (page_no, xref)
                        break

        if index_row_stream:
            try:
                inserted = _insert_index_pages(
                    doc, *index_groups, run_id=run_id, marks=marks, omitted=omitted,
                )
                if inserted != n_index:      # planned vs written must agree
                    _log.warning(
                        "index wrote %d page(s) but %d were planned for %s",
                        inserted, n_index, src.name,
                    )
            except Exception:  # noqa: BLE001 - the index must not sink the file
                _log.warning("could not build the findings index for %s", src.name)

        # Stamp every component with its FINAL page — inserting the index at the
        # front shifted everything written before it down by ``n_index``. Xref
        # numbers are stable across page insertion, so stamping by xref is safe.
        for pid, comps in collected.items():
            for component, xref, orig_page in comps:
                try:
                    _stamp_component(doc, xref, pid, component, orig_page + n_index)
                except Exception:  # noqa: BLE001 - a failed stamp → that placement fails
                    _log.warning("could not stamp %s for %s", component, pid)
        for pid, comps in notes_collected.items():
            for component, xref, notes_page in comps:
                try:
                    _stamp_component(doc, xref, pid, component, notes_page + n_index)
                except Exception:  # noqa: BLE001
                    _log.warning("could not stamp review note %s for %s", component, pid)

        # A 'QC Findings' bookmark outline so the marked-up set is one-click
        # navigable in Bluebeam/Acrobat (each issue → the page its mark landed
        # on, zoomed). Every component — source-page and review-notes alike — was
        # recorded before the index was inserted at the front, so all of them take
        # the same ``n_index`` shift here. I-3: an outline is a nicety — a failure
        # here never sinks the file.
        try:
            final_page_by_pid: dict[str, int] = {}
            for pid, comps in collected.items():
                if comps:
                    final_page_by_pid[pid] = comps[0][2] + n_index
            for pid, comps in notes_collected.items():
                if comps:
                    final_page_by_pid[pid] = comps[0][2] + n_index
            _set_findings_outline(
                doc, pairs, final_page_by_pid, n_index=n_index,
                mark_xref_by_pid={pid: xref for pid, (_page, xref) in marks.items()},
            )
        except Exception:  # noqa: BLE001
            _log.warning("could not build the findings bookmark outline for %s", src.name)

        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()

    return _reconcile_pdf(out, placements, run_id)


def _execute_reviewed_pdf_job(job: _ReviewedPdfJob) -> _ReviewedPdfOutcome:
    """Run one source-local write without allowing its failure to stop siblings."""
    try:
        receipts = _annotate_units(
            job.pdf_path,
            job.pairs,
            job.out_path,
            run_id=job.run_id,
            author=job.author,
            sheet_meta=job.sheet_meta,
            audit_stats=job.audit_stats,
            include_appendix=job.include_appendix,
        )
        return _ReviewedPdfOutcome(receipts=receipts)
    except Exception as exc:  # noqa: BLE001 - source failures are non-fatal
        return _ReviewedPdfOutcome(
            receipts=[], error_type=type(exc).__name__, error_detail=str(exc)
        )


# A spawned process imports this module afresh, so a test-time monkeypatch or an
# injected local callable would silently disappear in the child.  Remember every
# module-local function that the writer can call and fall back to the exact old
# in-process path if any of them has been replaced.  This also keeps fault-
# injection tests honest (for example, a monkeypatched ``_add_cloud`` must run).
_PROCESS_WORKER_FUNCTIONS = {
    name: value
    for name, value in globals().items()
    if getattr(value, "__module__", None) == __name__
    and getattr(value, "__code__", None) is not None
}
_PROCESS_WORKER_PYMUPDF_OPEN = pymupdf.open


# Off by default: a library caller keeps the in-process path for one source.
_isolate_writes_from_caller = False


def isolate_writes_from_caller(enabled: bool) -> None:
    """Write reviewed PDFs in a spawned worker even when there is one source.

    The GUI turns this on so writing markups never holds its process's GIL;
    every safety rule of the multi-source pool (pristine dependencies,
    picklable payloads, sequential retry when a worker fails before creating
    its output) still applies.
    """
    global _isolate_writes_from_caller
    _isolate_writes_from_caller = bool(enabled)


def _resolve_annotate_workers(max_workers: int | None, total: int) -> int:
    """Resolve the bounded process count for independent source-PDF writes."""
    if max_workers is None:
        raw = os.environ.get(_ANNOTATE_WORKERS_ENV)
        if raw:
            try:
                max_workers = int(raw.strip())
            except ValueError:
                max_workers = DEFAULT_ANNOTATE_WORKERS
        else:
            max_workers = DEFAULT_ANNOTATE_WORKERS
    return min(
        max(1, int(max_workers)),
        MAX_ANNOTATE_WORKERS,
        max(1, int(total)),
    )


def _process_worker_dependencies_pristine() -> bool:
    """Whether a fresh spawned interpreter will execute the same writer code."""
    if pymupdf.open is not _PROCESS_WORKER_PYMUPDF_OPEN:
        return False
    return all(
        globals().get(name) is original
        for name, original in _PROCESS_WORKER_FUNCTIONS.items()
    )


def _reviewed_pdf_jobs_are_picklable(jobs: list[_ReviewedPdfJob]) -> bool:
    """Preflight every payload before any worker can create an output file."""
    for job in jobs:
        try:
            pickle.dumps(job, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:  # noqa: BLE001 - custom payload => old safe path
            _log.warning(
                "reviewed-PDF payload for %s is not process-safe; "
                "writing sequentially: %s",
                job.pdf_path.name,
                exc,
            )
            return False
    return True


def _future_failure_outcome(exc: Exception) -> _ReviewedPdfOutcome:
    return _ReviewedPdfOutcome(
        receipts=[], error_type=type(exc).__name__, error_detail=str(exc)
    )


def _run_reviewed_pdf_jobs(
    jobs: list[_ReviewedPdfJob], *, max_workers: int | None
) -> list[_ReviewedPdfOutcome]:
    """Execute independent source jobs and return outcomes in input order.

    PyMuPDF documents never cross a thread or process boundary: each spawned
    worker opens, writes, closes, and reconciles one source using plain pickled
    model data.  The parent retains all routing and artifact bookkeeping.

    With :func:`isolate_writes_from_caller` on (the GUI), even a single source
    is written in a spawned worker: PyMuPDF holds the GIL for the whole write,
    which would otherwise freeze the host's window until the PDF is saved.
    """
    workers = _resolve_annotate_workers(max_workers, len(jobs))
    parallel = len(jobs) >= 2 and workers > 1
    if (
        not jobs
        or not (parallel or _isolate_writes_from_caller)
        or not _process_worker_dependencies_pristine()
    ):
        return [_execute_reviewed_pdf_job(job) for job in jobs]
    if not _reviewed_pdf_jobs_are_picklable(jobs):
        return [_execute_reviewed_pdf_job(job) for job in jobs]

    # ``spawn`` is intentional even on platforms whose default is ``fork``:
    # inheriting PyMuPDF / MuPDF process state is not a safe isolation boundary.
    context = multiprocessing.get_context("spawn")
    try:
        pool = _PROCESS_POOL_EXECUTOR(max_workers=workers, mp_context=context)
    except Exception as exc:  # noqa: BLE001 - unavailable pool => safe old path
        _log.warning(
            "reviewed-PDF process pool unavailable; writing sequentially: %s", exc
        )
        return [_execute_reviewed_pdf_job(job) for job in jobs]

    outcomes: list[_ReviewedPdfOutcome | None] = [None] * len(jobs)
    futures: list[tuple[int, Any]] = []
    output_absent_before = [not job.out_path.exists() for job in jobs]
    future_failures: dict[int, _ReviewedPdfOutcome] = {}
    first_unscheduled = len(jobs)
    try:
        for index, job in enumerate(jobs):
            try:
                futures.append((index, pool.submit(_execute_reviewed_pdf_job, job)))
            except Exception as exc:  # noqa: BLE001 - keep other sources viable
                first_unscheduled = index
                _log.warning(
                    "could not schedule reviewed-PDF worker for %s: %s",
                    job.pdf_path.name,
                    exc,
                )
                break

        # Read futures in source order.  Workers still run concurrently, while
        # receipts and output paths remain independent of completion timing.
        for index, future in futures:
            try:
                outcomes[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - one source never sinks peers
                future_failures[index] = _future_failure_outcome(exc)
    finally:
        try:
            pool.shutdown(wait=True)
        except Exception as exc:  # noqa: BLE001 - completed outcomes stay usable
            _log.warning("could not cleanly stop reviewed-PDF workers: %s", exc)

    # An executor / worker-boot failure is an optimization failure, not a review
    # failure.  If the job began with no output and still created none, the old
    # direct path is safe and preserves quality.  Once any output path exists it
    # may be partial, so never rerun blindly; retain an honest FAILED outcome.
    for index, failure in future_failures.items():
        if output_absent_before[index] and not jobs[index].out_path.exists():
            _log.warning(
                "reviewed-PDF worker failed before creating %s; retrying "
                "sequentially: %s",
                jobs[index].output_name,
                failure.error_detail or failure.error_type,
            )
            outcomes[index] = _execute_reviewed_pdf_job(jobs[index])
        else:
            outcomes[index] = failure

    # If executor submission itself failed part-way through, only the sources
    # that were never submitted use the old direct path.  Submitted jobs are
    # never repeated, so a partial pool failure cannot double-write an artifact.
    for index in range(first_unscheduled, len(jobs)):
        outcomes[index] = _execute_reviewed_pdf_job(jobs[index])

    return [
        outcome
        if outcome is not None
        else _ReviewedPdfOutcome(
            receipts=[],
            error_type="ProcessPoolError",
            error_detail="worker produced no terminal outcome",
        )
        for outcome in outcomes
    ]


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
    max_workers: int | None = None,
) -> MarkupRunResult:
    """Write one ``<stem>_reviewed.pdf`` per source with QC content, receipt-backed.

    Findings are matched to a source PDF by the host-owned ``source_id``
    (DA-001), so two inputs that share a basename each receive **only their own**
    findings — the reviewed copies are never cross-contaminated. (A finding that
    predates source ids — e.g. a hand-built test finding — falls back to matching
    by ``source_name``.) A source with nothing for the PDF gets no reviewed copy:
    no placement at all, or only ruled-out findings — those are ``REPORT_ONLY``
    and are receipted ``REPORTED`` without the file being opened. A source whose
    only findings are gated still gets one (their index rows are their sole
    artifact). A cross-sheet finding is
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

    Independent sources are written in isolated spawned processes (never
    PyMuPDF threads), bounded by ``max_workers`` or
    ``DRAWING_ANALYZER_ANNOTATE_WORKERS`` (default 2, hard cap 4). A one-source
    run, ``max_workers=1``, or an injected writer callable uses the original
    in-process path. Results are always folded in input-source order.
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
    jobs: list[_ReviewedPdfJob] = []
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
        if all(u.placement.expected == "REPORT_ONLY" for u in units):
            # Only ruled-out findings: a "reviewed" copy would be the source
            # with nothing added. No file; the findings stay in the report.
            all_receipts.extend(MarkupReceipt(u.placement, "REPORTED") for u in units)
            continue
        pairs = [(u.finding, u.placement) for u in units]
        if stem_counts.get(pdf_path.stem, 0) > 1 and sid:
            name = f"{pdf_path.stem}__{sid}_reviewed.pdf"
        else:
            name = f"{pdf_path.stem}_reviewed.pdf"
        n = 1
        # Case-insensitive (item 45): on Windows two names differing only in case
        # are one file, and the second reviewed PDF would overwrite the first.
        while name_is_taken(name, used_names):   # last-resort guard (no source_id to split them)
            n += 1
            name = f"{pdf_path.stem}_reviewed_{n}.pdf"
        record_name(name, used_names)
        out = output_dir / name
        sheet_meta = {
            **meta_by_name.get(pdf_path.name, {}),
            **meta_by_source_id.get(sid, {}),   # source-id meta wins per page
        }
        jobs.append(_ReviewedPdfJob(
            pdf_path=pdf_path,
            pairs=pairs,
            out_path=out,
            output_name=name,
            run_id=run_id,
            author=author,
            sheet_meta=sheet_meta or None,
            audit_stats=audit_stats,
            include_appendix=include_appendix,
        ))

    outcomes = _run_reviewed_pdf_jobs(jobs, max_workers=max_workers)
    for job, outcome in zip(jobs, outcomes):
        name = job.output_name
        out = job.out_path
        if outcome.error_type:
            # Receipt error carries only the exception TYPE (the raw message may
            # embed an absolute source/temp path); full detail goes to the log.
            _log.warning(
                "could not write reviewed PDF for %s: %s",
                job.pdf_path.name,
                outcome.error_detail or outcome.error_type,
            )
            receipts = [
                MarkupReceipt(
                    placement,
                    "FAILED",
                    output_pdf=name,
                    error=f"reviewed-PDF write failed ({outcome.error_type})",
                )
                for _, placement in job.pairs
            ]
            all_receipts.extend(receipts)
            continue

        receipts = outcome.receipts
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

    This artifact is not subject to the ``markup_verified_only`` gate: that gate
    suppresses unverified ink *on the drawings*, but a set-level conflict has no
    sheet to cloud and cannot be crop-verified, so these rows are the finding's index
    entry — a review-notes artifact, not authoritative drawing ink.
    """
    items = [f for f in findings if _is_set_level_finding(f)]
    if not items:
        return _result_from_receipts([], [], [])

    run_id = artifact_run_id or new_artifact_run_id()
    output_dir = Path(output_dir)
    # Severity-first triage order, deterministic (I-7) — same rule as the
    # reviewed-PDF index pages (§18.7), so every generated listing reads
    # highest-severity first.
    items.sort(key=_severity_first_key)
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
    # Same severity layers as the reviewed PDFs, so set-level notes are filterable
    # by tier alongside the on-sheet markups.
    oc_layers = _create_severity_layers(doc, {_severity_layer_tier(f) for f in items})
    try:
        n_pages = (len(pairs) + _NOTES_PER_PAGE - 1) // _NOTES_PER_PAGE
        for pno in range(n_pages):
            page = _new_generated_page(doc)
            title = SET_REVIEW_NOTES_LABEL + (f"  (page {pno + 1}/{n_pages})" if n_pages > 1 else "")
            page.insert_text((_NOTE_LEFT, 42), title, fontsize=12, fontname="hebo", color=(0.1, 0.1, 0.1))
            page.insert_text(
                (_NOTE_LEFT, 62),
                _fit_text(
                    "These findings apply to the whole set, not to one sheet.",
                    _INDEX_PAGE_W - 2 * _NOTE_LEFT, fontsize=8,
                ),
                fontsize=8, color=(0.35, 0.35, 0.35),
            )
            batch = pairs[pno * _NOTES_PER_PAGE:(pno + 1) * _NOTES_PER_PAGE]
            y = _NOTE_TOP
            for finding, placement in batch:
                box = pymupdf.Rect(_NOTE_LEFT, y, _INDEX_PAGE_W - _NOTE_LEFT, y + _NOTE_BOX_H)
                action = getattr(finding, "recommended_action", "").strip()
                content = (
                    f"{finding.qc_id or '-'}  [set-level / {finding.severity}]\n"
                    f"{finding.text.strip()}"
                    + (f"\nAction: {action}" if action else "")
                    + "\nNot yet verified - double-check across the set."
                )
                try:
                    shown = _truncate_at_word(content, 400)  # reused below (item 33)
                    annot = page.add_freetext_annot(
                        box, shown, fontsize=8,
                        text_color=_color(finding), fill_color=(1.0, 1.0, 0.92),
                    )
                    annot.set_info(title=author, subject=_subject(finding), content=shown)
                    _assign_layer(annot, finding, oc_layers)
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
