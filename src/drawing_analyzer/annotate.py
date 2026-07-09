"""Markup writer: cloud each finding onto a copy of its source PDF.

This turns verified findings into **real annotation objects** on a
``<stem>_reviewed.pdf`` — a Square (rectangle) annot per finding, drawn with a
revision-cloud border, colored by severity, and carrying the finding as its
popup comment. Opened in Bluebeam Revu the annots populate the Markups List
(filter / sort / reply / export all work); Acrobat and Chromium render them too.

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
from typing import Iterable

import pymupdf  # AGPL-3.0 — see module docstring; the 2nd of two blessed importers.

from .diagnostics import get_logger
from .models import ConflictLeg, Finding

_log = get_logger()

# The annot author — provenance is unmistakable in the Markups List.
DEFAULT_AUTHOR = "Drawing Analyzer (AI review)"

# Verification statuses trusted enough to cloud by default. Everything else
# (UNCERTAIN / SKIPPED) is "unverified" and only inked when opted in; REJECTED is
# never inked. (Part III later flips the default to ink-everything-but-rejected;
# that lands with the ledger phase, not here.)
_TRUSTED = frozenset({"VERIFIED", "DETERMINISTIC"})

# Stroke color by severity (RGB 0–1): red / orange / blue, grey fallback.
_SEVERITY_COLORS = {
    "high": (0.84, 0.11, 0.11),
    "medium": (0.90, 0.49, 0.07),
    "low": (0.16, 0.42, 0.82),
}
_DEFAULT_COLOR = (0.40, 0.40, 0.40)

_BORDER_WIDTH = 1.5


def _status(finding: Finding) -> str:
    v = getattr(finding, "verification", None)
    return v.status if v is not None else "SKIPPED"


def is_cloudable(finding: Finding, *, include_unverified: bool) -> bool:
    """Whether this finding gets inked.

    Requires an anchor rectangle (an unanchored finding has nowhere to draw). A
    ``REJECTED`` finding is never clouded (a known-wrong cloud on an issued
    drawing is the one failure worse than a missing one); ``VERIFIED`` /
    ``DETERMINISTIC`` always are; the rest only when ``include_unverified``.
    """
    anchor = getattr(finding, "anchor", None)
    if anchor is None or anchor.rect_pdf is None:
        return False
    status = _status(finding)
    if status == "REJECTED":
        return False
    if status in _TRUSTED:
        return True
    return include_unverified


def _is_unverified(finding: Finding) -> bool:
    return _status(finding) not in _TRUSTED


def _annot_content(finding: Finding, *, unverified: bool) -> str:
    """The popup comment: the finding plus its quote / verification / refs, and —
    for a cross-sheet finding — a cross-reference to the other sheet(s)."""
    lines = [finding.text.strip()]
    quote = finding.source_quote.strip()
    if quote:
        lines.append(f'Quote: "{quote}"')
    for leg in getattr(finding, "also_on", None) or []:
        lq = f': "{leg.source_quote.strip()}"' if leg.source_quote.strip() else ""
        lines.append(f"Conflicts with {leg.sheet_id}{lq}")
    v = getattr(finding, "verification", None)
    if v is not None:
        lines.append(f"Verification: {v.status}" + (f" — {v.note}" if v.note else ""))
    if finding.refs:
        lines.append("Refs: " + ", ".join(str(r) for r in finding.refs))
    content = "\n".join(lines)
    return f"[UNVERIFIED] {content}" if unverified else content


def _add_cloud(
    page: "pymupdf.Page", finding: Finding, *, unverified: bool, author: str
) -> None:
    """Add one Square annot for ``finding`` to ``page`` (revision-cloud styled)."""
    annot = page.add_rect_annot(pymupdf.Rect(*finding.anchor.rect_pdf))
    annot.set_colors(stroke=_SEVERITY_COLORS.get(finding.severity.lower(), _DEFAULT_COLOR))
    try:
        if unverified:
            annot.set_border(width=_BORDER_WIDTH, dashes=[4, 3])   # dashed = tentative
        else:
            annot.set_border(width=_BORDER_WIDTH, clouds=2)        # revision cloud
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


def count_annotations(pdf_path: Path | str) -> int:
    """Total annotations across all pages of ``pdf_path`` (for the round-trip check)."""
    doc = pymupdf.open(str(pdf_path))
    try:
        return sum(1 for page in doc for _ in page.annots())
    finally:
        doc.close()


def annotate_pdf(
    pdf_path: Path | str,
    findings: Iterable[Finding],
    out_path: Path | str,
    *,
    include_unverified: bool = False,
    author: str = DEFAULT_AUTHOR,
) -> int:
    """Write a ``_reviewed`` copy of ``pdf_path`` with each cloudable finding inked.

    Returns the number of annots written. Opens the *original* read-only and
    saves a **new** file (``out_path`` must differ from the source), so the source
    is never modified. Per-finding failures are logged and skipped (I-3); after
    saving, the file is reopened and its annot count compared to what was written
    (a mismatch is logged, not raised).
    """
    src = Path(pdf_path)
    out = Path(out_path)
    if out.resolve() == src.resolve():
        raise ValueError("reviewed PDF path must differ from the source PDF")

    doc = pymupdf.open(str(src))
    written = 0
    try:
        page_count = doc.page_count
        for finding in findings:
            if not is_cloudable(finding, include_unverified=include_unverified):
                continue
            page_index = finding.page_index
            if not (0 <= page_index < page_count):
                _log.warning(
                    "finding %s page_index %d out of range for %s",
                    finding.id, page_index, src.name,
                )
                continue
            try:
                _add_cloud(
                    doc[page_index], finding,
                    unverified=_is_unverified(finding), author=author,
                )
                written += 1
            except Exception:  # noqa: BLE001 - one bad annot must not sink the file
                _log.warning("could not add markup for finding %s", finding.id)
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
    *its* sheet, inheriting the parent's category/severity/verification (so gating
    is identical) and carrying its own ``also_on`` pointing back at the primary
    and the sibling legs, so its popup cross-references them too. A finding with
    no legs passes through unchanged. Synthetic legs live only here — never in the
    findings record — so counts/exports stay one-entry-per-conflict.
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
            ))
    return out


def write_reviewed_pdfs(
    findings: Iterable[Finding],
    pdf_paths: Iterable[Path | str],
    output_dir: Path | str,
    *,
    include_unverified: bool = False,
    author: str = DEFAULT_AUTHOR,
) -> list[Path]:
    """Write one ``<stem>_reviewed.pdf`` per source PDF that has cloudable findings.

    Findings are matched to a source PDF by ``source_name`` (the file basename);
    a source with no cloudable finding gets no reviewed copy. A cross-sheet finding
    is clouded on **every** sheet it touches (see :func:`_expand_for_markup`).
    Output filenames are de-duplicated (``_reviewed`` / ``_reviewed_2`` / …) so two
    inputs sharing a stem don't clobber each other. Returns the reviewed-PDF paths,
    in input order.
    """
    output_dir = Path(output_dir)
    by_source: dict[str, list[Finding]] = {}
    for finding in _expand_for_markup(findings):
        by_source.setdefault(finding.source_name, []).append(finding)

    out_paths: list[Path] = []
    used_names: set[str] = set()
    for pdf_path in pdf_paths:
        pdf_path = Path(pdf_path)
        sheet_findings = by_source.get(pdf_path.name, [])
        if not any(
            is_cloudable(f, include_unverified=include_unverified) for f in sheet_findings
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
        )
        out_paths.append(out)
    return out_paths
