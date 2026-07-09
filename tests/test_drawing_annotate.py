"""Markup-writer tests: build a synthetic PDF, cloud findings, reopen and assert.

The gating unit checks are pure; the writer tests need PyMuPDF and are skipped
without it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer.annotate import (
    DEFAULT_AUTHOR,
    is_cloudable,
    write_reviewed_pdfs,
)
from drawing_analyzer.models import Anchor, Finding, Verification

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import annotate_pdf, count_annotations  # noqa: E402


def _finding(text="Issue", *, severity="high", status="VERIFIED", rect=(100.0, 100.0, 220.0, 140.0),
             page=0, category="code", source="M-101.pdf", quote="VAV-3", refs=None):
    f = Finding(
        sheet_id="M-101", source_name=source, page_index=page, category=category,
        severity=severity, text=text, source_quote=quote, refs=list(refs or []),
        anchor=Anchor(status="EXACT", rect_pdf=list(rect) if rect else None, method="exact"),
    )
    f.verification = Verification(status=status, note="looks right" if status == "VERIFIED" else "")
    return f


def _make_pdf(dir_path: Path, name="M-101.pdf", pages=2) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page(width=792, height=612).insert_text((80, 80), f"SHEET {name} p{i + 1}")
    path = dir_path / name
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------- #
# Gating (pure)
# --------------------------------------------------------------------------- #


def test_gating_matrix():
    # Default: only VERIFIED + DETERMINISTIC are inked; REJECTED never; the rest
    # only when include_unverified.
    cases = {
        "VERIFIED": (True, True),
        "DETERMINISTIC": (True, True),
        "UNCERTAIN": (False, True),
        "SKIPPED": (False, True),
        "REJECTED": (False, False),
    }
    for status, (default, opted) in cases.items():
        f = _finding(status=status)
        assert is_cloudable(f, include_unverified=False) is default, status
        assert is_cloudable(f, include_unverified=True) is opted, status


def test_gating_unanchored_never_cloudable():
    f = _finding(status="VERIFIED", rect=None)
    f.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
    assert is_cloudable(f, include_unverified=True) is False


# --------------------------------------------------------------------------- #
# Writer (PyMuPDF)
# --------------------------------------------------------------------------- #


def test_write_reviewed_pdf_default_gating(tmp_path):
    src = _make_pdf(tmp_path)
    findings = [
        _finding("clearance", status="VERIFIED", refs=["CMC 310"]),
        _finding("stale ref", status="DETERMINISTIC", category="reference", rect=(300, 200, 420, 240)),
        _finding("wrong", status="REJECTED", rect=(100, 300, 220, 340)),
        _finding("maybe", status="UNCERTAIN", rect=(400, 300, 520, 340)),
        _finding("page 2", status="VERIFIED", page=1),
    ]
    out = write_reviewed_pdfs(findings, [src], tmp_path / "out")
    assert [p.name for p in out] == ["M-101_reviewed.pdf"]
    # 2 VERIFIED + 1 DETERMINISTIC; REJECTED and UNCERTAIN excluded.
    assert count_annotations(out[0]) == 3
    # The source is never modified.
    assert count_annotations(src) == 0


def test_include_unverified_adds_the_uncertain(tmp_path):
    src = _make_pdf(tmp_path)
    findings = [
        _finding("clearance", status="VERIFIED"),
        _finding("maybe", status="UNCERTAIN", rect=(400, 300, 520, 340)),
        _finding("wrong", status="REJECTED", rect=(100, 300, 220, 340)),   # still excluded
    ]
    out = write_reviewed_pdfs(findings, [src], tmp_path / "out", include_unverified=True)
    assert count_annotations(out[0]) == 2   # verified + uncertain, not rejected


def test_annot_info_fields_populated(tmp_path):
    src = _make_pdf(tmp_path)
    f = _finding("Missing clearance", status="VERIFIED", category="code",
                 quote="VAV-3", refs=["CMC 310"])
    annotate_pdf(src, [f], tmp_path / "r.pdf")

    doc = pymupdf.open(str(tmp_path / "r.pdf"))
    try:
        annots = [a for page in doc for a in page.annots()]
        assert len(annots) == 1
        info = annots[0].info
        assert info["title"] == DEFAULT_AUTHOR
        assert info["subject"] == "code"
        assert "Missing clearance" in info["content"]
        assert 'Quote: "VAV-3"' in info["content"]
        assert "Verification: VERIFIED" in info["content"]
        assert "CMC 310" in info["content"]
        assert not info["content"].startswith("[UNVERIFIED]")
    finally:
        doc.close()


def test_unverified_annot_is_prefixed(tmp_path):
    src = _make_pdf(tmp_path)
    f = _finding("Maybe wrong", status="UNCERTAIN", quote="")
    annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=True)
    doc = pymupdf.open(str(tmp_path / "r.pdf"))
    try:
        content = next(a for page in doc for a in page.annots()).info["content"]
        assert content.startswith("[UNVERIFIED]")
    finally:
        doc.close()


def test_annotate_returns_count_and_round_trips(tmp_path):
    src = _make_pdf(tmp_path)
    findings = [_finding(status="VERIFIED"), _finding(status="VERIFIED", rect=(300, 200, 420, 240))]
    n = annotate_pdf(src, findings, tmp_path / "r.pdf")
    assert n == 2
    assert count_annotations(tmp_path / "r.pdf") == n   # round-trip


def test_out_path_must_differ_from_source(tmp_path):
    src = _make_pdf(tmp_path)
    with pytest.raises(ValueError):
        annotate_pdf(src, [_finding()], src)   # would clobber the source


def test_finding_on_out_of_range_page_is_skipped(tmp_path):
    src = _make_pdf(tmp_path, pages=1)
    findings = [_finding("ok", status="VERIFIED", page=0),
                _finding("nope", status="VERIFIED", page=9)]   # page 9 doesn't exist
    n = annotate_pdf(src, findings, tmp_path / "r.pdf")
    assert n == 1


def test_no_reviewed_pdf_when_nothing_cloudable(tmp_path):
    src = _make_pdf(tmp_path)
    findings = [_finding("wrong", status="REJECTED"), _finding("maybe", status="UNCERTAIN")]
    out = write_reviewed_pdfs(findings, [src], tmp_path / "out")   # default gating
    assert out == []   # no ink -> no reviewed copy


def test_duplicate_stems_get_unique_output_names(tmp_path):
    # Two source PDFs sharing a stem must not clobber each other's reviewed copy.
    a = _make_pdf(tmp_path / "a", "M-101.pdf")
    b = _make_pdf(tmp_path / "b", "M-101.pdf")
    findings = [
        _finding("a1", status="VERIFIED", source="M-101.pdf"),
    ]
    # both PDFs share basename M-101.pdf, so both receive the finding
    out = write_reviewed_pdfs(findings, [a, b], tmp_path / "out")
    names = sorted(p.name for p in out)
    assert names == ["M-101_reviewed.pdf", "M-101_reviewed_2.pdf"]
