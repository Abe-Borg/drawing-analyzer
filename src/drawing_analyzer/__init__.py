"""Drawing Analyzer — extract structured information from construction drawings.

A standalone vision pipeline that turns construction-drawing PDFs (mechanical /
plumbing / fire-protection sheets, etc.) into a structured *text* digest.

Design:

- **One sheet per request.** Each PDF page is a sheet; each sheet is rendered to
  an overview image plus a 6x6 grid of high-resolution tiles and sent to Claude
  Opus 4.8 in a *single* vision request, so the model sees the whole sheet at
  once (coherence beats the marginal resolution gain of splitting a sheet across
  calls).
- **No sheet limit.** Sheets are processed independently and their text digests
  are concatenated, so a set of any size builds up incrementally — the set never
  has to fit in one context window.
- **Vision -> text.** The output is plain structured text, ready to read, save,
  or feed to any downstream consumer.

Module layout::

    tiling.py         dependency-free tile geometry (clip rects + render zoom)
    source_registry.py host-owned source identity (SRC-#### per input; DA-001)
    render.py         PyMuPDF rasterization (PyMuPDF importer 1 of exactly 2)
    digest.py         per-sheet vision request -> structured text + findings block
    batch_digest.py   Message Batches / Files API digest path
    digest_cache.py   two-level content-keyed digest cache
    synthesis.py      cross-sheet reconciliation pass (text-only)
    focus.py          optional per-run focus -> set-level Focus Report (text-only)
    pipeline.py       orchestration: PDFs -> sheets -> digests -> QC -> combined text
    ledger.py         the per-run findings ledger every QC channel feeds (Part III)
    auditors/         deterministic zero-API auditors (references, arithmetic,
                      naming, title-block, sheet-index)
    critique.py       second full-coverage "reviewer" vision read (self-consistent)
    cross_qc.py       cross-sheet conflict hunt (text-only, dual anchors)
    prose_harvest.py  prose Coordination/Conflict/synthesis items -> ledger entries
    anchor.py         finding quote -> PDF rectangle resolution (offline)
    verify.py         per-finding crop verification pass
    citation_check.py web-search check of cited code sections
    annotate.py       reviewed-PDF markup writer + reopen/reconcile receipts
                      (artifact-backed coverage, DA-007; PyMuPDF importer 2 of 2)
    export.py         folder export: findings.csv/json, sheet text, evidence,
                      markup_manifest.json (placement receipts + coverage proof)
    html_report.py    self-contained HTML report (+ in-browser Ask AI assistant)
    gui.py            standalone CustomTkinter window
    __main__.py       ``python -m drawing_analyzer`` launches the GUI

PyMuPDF (AGPL) is deliberately confined to ``render.py`` + ``annotate.py`` —
see the README's Licensing section before adding an import elsewhere.
"""
from __future__ import annotations

from .digest import SheetDigest
from .pipeline import (
    DrawingContext,
    estimate_image_tokens_for_set,
    extract_drawing_context,
)

__version__ = "0.1.0"

__all__ = [
    "DrawingContext",
    "SheetDigest",
    "extract_drawing_context",
    "estimate_image_tokens_for_set",
    "__version__",
]
