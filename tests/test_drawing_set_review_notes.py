"""Set-level review notes (Drawing_Set_Review_Notes.pdf) — Phase 22 §14.8.

A synthesis conflict that names no in-set sheet belongs to no source PDF, so it
is written to a dedicated, deterministic, analyzer-owned PDF whose rows are
reopened and reconciled into Phase-21 receipts (never counted from intention).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from drawing_analyzer.annotate import (
    SET_REVIEW_NOTES_FILENAME,
    _reconcile_pdf,
    write_set_review_notes_pdf,
)
from drawing_analyzer.models import Finding


def _set(text, *, qc="QC-005", sev="high"):
    return Finding(
        sheet_id="(set-level)", source_name="", source_id="", page_index=-1,
        category="conflict", severity=sev, text=text, anchor_hint="SET_INDEX", qc_id=qc,
    )


def _source(text="on a real sheet"):
    return Finding(
        sheet_id="M-101", source_name="a.pdf", source_id="SRC-0001", page_index=0,
        category="code", severity="low", text=text, qc_id="QC-001",
    )


def test_writes_notes_pdf_with_written_receipts(tmp_path):
    res = write_set_review_notes_pdf(
        [_set("Pump schedule disagrees with the specified pump across the set.", qc="QC-005"),
         _set("Detail callout numbering is inconsistent set-wide.", qc="QC-006", sev="medium"),
         _source()],                       # a non-set finding is ignored
        tmp_path, artifact_run_id="run-fixed01",
    )
    assert [p.name for p in res.reviewed_pdfs] == [SET_REVIEW_NOTES_FILENAME]
    assert res.coverage_status == "COMPLETE"
    assert res.tally == {"review_notes": 2}
    assert len(res.receipts) == 2 and all(r.status == "WRITTEN" for r in res.receipts)
    assert (tmp_path / SET_REVIEW_NOTES_FILENAME).exists()


def test_notes_are_present_and_stamped_after_reopen(tmp_path):
    res = write_set_review_notes_pdf(
        [_set("A genuine set-level conflict that must show as ink.")],
        tmp_path, artifact_run_id="run-fixed02",
    )
    out = tmp_path / SET_REVIEW_NOTES_FILENAME
    doc = pymupdf.open(str(out))
    try:
        annots = [a for pno in range(doc.page_count) for a in doc[pno].annots()]
        assert len(annots) == 1                       # one stamped callout, real ink
    finally:
        doc.close()
    # The receipt is independently reconcilable against the saved file.
    receipts = _reconcile_pdf(out, res.placements, "run-fixed02")
    assert all(r.status == "WRITTEN" for r in receipts)


def test_empty_input_writes_no_file(tmp_path):
    res = write_set_review_notes_pdf([_source()], tmp_path)   # only non-set findings
    assert res.reviewed_pdfs == [] and res.receipts == []
    assert not (tmp_path / SET_REVIEW_NOTES_FILENAME).exists()


def test_draw_failure_is_a_failed_receipt_and_incomplete(tmp_path, monkeypatch):
    # Force every note draw to fail: no component is stamped, so reconciliation
    # reports a FAILED receipt and the file is labeled INCOMPLETE (§13.6) — never a
    # silent success.
    def _boom(self, *a, **k):
        raise RuntimeError("annot boom")

    monkeypatch.setattr(pymupdf.Page, "add_freetext_annot", _boom, raising=True)
    res = write_set_review_notes_pdf(
        [_set("this note cannot be drawn")], tmp_path, artifact_run_id="run-fixed03",
    )
    assert res.coverage_status == "INCOMPLETE"
    assert any(r.status == "FAILED" for r in res.receipts)
    names = [p.name for p in res.reviewed_pdfs]
    assert names and names[0].endswith("_INCOMPLETE.pdf")
