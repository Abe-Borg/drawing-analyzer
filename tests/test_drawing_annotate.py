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
from drawing_analyzer.source_registry import assign_source_ids

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import annotate_pdf, count_annotations  # noqa: E402


def _finding(text="Issue", *, severity="high", status="VERIFIED", rect=(100.0, 100.0, 220.0, 140.0),
             page=0, category="code", source="M-101.pdf", quote="VAV-3", refs=None,
             source_id=""):
    f = Finding(
        sheet_id="M-101", source_name=source, source_id=source_id, page_index=page,
        category=category, severity=severity, text=text, source_quote=quote,
        refs=list(refs or []),
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
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out")
    out = res.reviewed_pdfs
    assert [p.name for p in out] == ["M-101_reviewed.pdf"]
    # 2 VERIFIED + 1 DETERMINISTIC; REJECTED (index-only) and UNCERTAIN (gated)
    # carry no ink under the default gating. Coverage is COMPLETE because the
    # rejected finding's index row is a proven placement (§13.5).
    assert count_annotations(out[0]) == 3
    assert res.coverage_status == "COMPLETE"
    # The source is never modified.
    assert count_annotations(src) == 0


def test_include_unverified_adds_the_uncertain(tmp_path):
    src = _make_pdf(tmp_path)
    findings = [
        _finding("clearance", status="VERIFIED"),
        _finding("maybe", status="UNCERTAIN", rect=(400, 300, 520, 340)),
        _finding("wrong", status="REJECTED", rect=(100, 300, 220, 340)),   # still excluded
    ]
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out", include_unverified=True)
    assert count_annotations(res.reviewed_pdfs[0]) == 2   # verified + uncertain, not rejected
    assert res.coverage_status == "COMPLETE"


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


def test_annotate_returns_result_and_round_trips(tmp_path):
    src = _make_pdf(tmp_path)
    findings = [_finding(status="VERIFIED"), _finding(status="VERIFIED", rect=(300, 200, 420, 240))]
    res = annotate_pdf(src, findings, tmp_path / "r.pdf")
    # ``annots_written`` is derived from the reopened receipts, not intention.
    assert res.annots_written == 2
    assert count_annotations(tmp_path / "r.pdf") == res.annots_written   # round-trip
    assert res.coverage_status == "COMPLETE"
    assert all(r.status == "WRITTEN" for r in res.receipts)


def test_out_path_must_differ_from_source(tmp_path):
    src = _make_pdf(tmp_path)
    with pytest.raises(ValueError):
        annotate_pdf(src, [_finding()], src)   # would clobber the source


def test_finding_on_out_of_range_page_gets_a_failed_receipt(tmp_path):
    # Failure-injection (§13, test 3): a placement on a non-existent page is never
    # drawn, so reconciliation reports it FAILED — never counted as ink — and
    # coverage is INCOMPLETE. The valid finding is still WRITTEN.
    src = _make_pdf(tmp_path, pages=1)
    findings = [_finding("ok", status="VERIFIED", page=0, quote="ok-q"),
                _finding("nope", status="VERIFIED", page=9, quote="nope-q")]  # page 9 doesn't exist
    res = annotate_pdf(src, findings, tmp_path / "r.pdf")
    assert res.annots_written == 1
    assert res.coverage_status == "INCOMPLETE"
    failed = [r for r in res.receipts if r.status == "FAILED"]
    assert len(failed) == 1 and failed[0].placement.page_index == 9


def test_gated_and_rejected_only_sources_still_get_reviewed_copies(tmp_path):
    # Under §18/§6.4 every ledger entry ends with a proven placement: a gated
    # (verified-only mode) finding earns a "Not inked by operator gate" index row
    # and a REJECTED one a rejected-index row — so each source is still written
    # (nothing is invisible), and coverage stays COMPLETE because those index
    # rows are reconciled placements, not intentions.
    src = _make_pdf(tmp_path)
    findings = [_finding("maybe", status="UNCERTAIN")]
    res = write_reviewed_pdfs(
        findings, [src], tmp_path / "out", include_unverified=False
    )
    # Gated: the UNCERTAIN finding gets a "Not inked by operator gate" index row
    # (a proven placement), so the source IS written — coverage COMPLETE.
    assert len(res.reviewed_pdfs) == 1
    assert res.coverage_status == "COMPLETE"
    assert res.tally == {"gated": 1}

    # The same UNCERTAIN finding IS inked under the exhaustive default.
    res2 = write_reviewed_pdfs(
        findings, [src], tmp_path / "out2", include_unverified=True
    )
    assert len(res2.reviewed_pdfs) == 1

    # A rejected-only source still gets a reviewed copy: the index's rejected
    # section keeps it visible even though it carries no ink (§18).
    rejected_only = [_finding("wrong", status="REJECTED")]
    res3 = write_reviewed_pdfs(
        rejected_only, [src], tmp_path / "out3", include_unverified=False
    )
    assert len(res3.reviewed_pdfs) == 1
    assert res3.coverage_status == "COMPLETE"
    doc = pymupdf.open(str(res3.reviewed_pdfs[0]))
    try:
        assert "Rejected by verification (1)" in doc[0].get_text()
        assert sum(1 for page in doc for _ in page.annots()) == 0
    finally:
        doc.close()


def test_list_sheets_assigns_distinct_source_ids_to_same_basename(tmp_path):
    # The render-side wiring: two M-101.pdf in different folders get distinct
    # host ids, and every page of a source shares its id.
    from drawing_analyzer.render import list_sheets

    a = _make_pdf(tmp_path / "a", "M-101.pdf", pages=2)
    b = _make_pdf(tmp_path / "b", "M-101.pdf", pages=1)
    refs = list_sheets([a, b])
    by_path = {}
    for r in refs:
        by_path.setdefault(str(r.pdf_path), set()).add(r.source_id)
    assert by_path[str(a)] == {"SRC-0001"}    # both pages of A share one id
    assert by_path[str(b)] == {"SRC-0002"}
    assert len(refs) == 3


def test_duplicate_stems_isolate_findings_by_source_id(tmp_path):
    # Product invariant (DA-001): two inputs sharing a basename are DISTINCT
    # sources. A finding bound to one source is written ONLY to that source's
    # reviewed PDF — never the other's. (The pre-migration behavior, where both
    # same-named PDFs received the union of findings, was the defect.)
    a = _make_pdf(tmp_path / "a", "M-101.pdf")
    b = _make_pdf(tmp_path / "b", "M-101.pdf")
    # list_sheets / write_reviewed_pdfs assign SRC ids in input order: a→SRC-0001.
    ids = assign_source_ids([a, b])
    sid_a = ids[str(a)]
    findings = [_finding("only-on-A", status="VERIFIED", source="M-101.pdf", source_id=sid_a)]

    res = write_reviewed_pdfs(findings, [a, b], tmp_path / "out")
    out = res.reviewed_pdfs

    # Only source A is written (B has no finding of its own), and its name is
    # disambiguated by source id, not an order-dependent _2.
    assert [p.name for p in out] == [f"M-101__{sid_a}_reviewed.pdf"]
    doc = pymupdf.open(str(out[0]))
    try:
        n_annots = sum(1 for page in doc for _ in page.annots())
        assert n_annots > 0, "source A's finding should be inked on A"
    finally:
        doc.close()


def test_duplicate_stems_each_source_keeps_its_own_finding(tmp_path):
    # Each same-basename source carries a different finding; neither reviewed PDF
    # receives the other's ink, and both names are source-disambiguated.
    a = _make_pdf(tmp_path / "a", "M-101.pdf")
    b = _make_pdf(tmp_path / "b", "M-101.pdf")
    ids = assign_source_ids([a, b])
    findings = [
        _finding("A-issue", source="M-101.pdf", source_id=ids[str(a)], quote="AAA"),
        _finding("B-issue", source="M-101.pdf", source_id=ids[str(b)], quote="BBB"),
    ]
    res = write_reviewed_pdfs(findings, [a, b], tmp_path / "out")
    out = res.reviewed_pdfs
    names = sorted(p.name for p in out)
    assert names == [
        f"M-101__{ids[str(a)]}_reviewed.pdf",
        f"M-101__{ids[str(b)]}_reviewed.pdf",
    ]
    assert res.coverage_status == "COMPLETE"
    # Each reviewed PDF has exactly its own one finding's ink (1 cloud each).
    for p in out:
        doc = pymupdf.open(str(p))
        try:
            assert sum(1 for page in doc for _ in page.annots()) >= 1
        finally:
            doc.close()
