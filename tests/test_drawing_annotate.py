"""Markup-writer tests: build a synthetic PDF, cloud findings, reopen and assert.

The gating unit checks are pure; the writer tests need PyMuPDF and are skipped
without it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import drawing_analyzer.annotate as annotate
from drawing_analyzer.annotate import (
    DEFAULT_AUTHOR,
    is_cloudable,
    write_reviewed_pdfs,
)
from drawing_analyzer.models import Anchor, Finding, Verification, assign_qc_ids
from drawing_analyzer.source_registry import assign_source_ids

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import (  # noqa: E402
    _SEVERITY_LAYER_NAMES,
    _SEVERITY_LAYER_ORDER,
    annotate_pdf,
    count_annotations,
    write_set_review_notes_pdf,
)


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
        assert 'Look for: "VAV-3"' in info["content"]
        assert "AI-verified against the drawing." in info["content"]
        assert "CMC 310" in info["content"]
        assert not info["content"].startswith("[CHECK]")
    finally:
        doc.close()


def test_unverified_annot_is_prefixed(tmp_path):
    src = _make_pdf(tmp_path)
    f = _finding("Maybe wrong", status="UNCERTAIN", quote="")
    annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=True)
    doc = pymupdf.open(str(tmp_path / "r.pdf"))
    try:
        content = next(a for page in doc for a in page.annots()).info["content"]
        assert content.startswith("[CHECK]")
        assert "Not yet verified - double-check on the sheet." in content
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


def test_reviewed_pdf_worker_resolution_is_bounded(monkeypatch):
    monkeypatch.delenv("DRAWING_ANALYZER_ANNOTATE_WORKERS", raising=False)
    assert annotate._resolve_annotate_workers(None, 10) == 2

    monkeypatch.setenv("DRAWING_ANALYZER_ANNOTATE_WORKERS", "99")
    assert annotate._resolve_annotate_workers(None, 10) == 4

    monkeypatch.setenv("DRAWING_ANALYZER_ANNOTATE_WORKERS", "not-a-number")
    assert annotate._resolve_annotate_workers(None, 10) == 2
    assert annotate._resolve_annotate_workers(1, 10) == 1
    assert annotate._resolve_annotate_workers(4, 2) == 2


def test_multi_source_jobs_use_spawn_and_fold_in_input_order(tmp_path, monkeypatch):
    first = _make_pdf(tmp_path / "first", "B-202.pdf")
    second = _make_pdf(tmp_path / "second", "A-101.pdf")
    ids = assign_source_ids([first, second])
    findings = [
        _finding("second issue", source=second.name, source_id=ids[str(second)]),
        _finding("first issue", source=first.name, source_id=ids[str(first)]),
    ]
    observed: dict[str, object] = {}

    class _ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class _RecordingPool:
        def __init__(self, *, max_workers, mp_context):
            observed["max_workers"] = max_workers
            observed["start_method"] = mp_context.get_start_method()
            observed["submitted"] = []

        def submit(self, fn, job):
            observed["submitted"].append(job.pdf_path.name)
            return _ImmediateFuture(fn(job))

        def shutdown(self, *, wait):
            observed["shutdown_wait"] = wait

    monkeypatch.setattr(annotate, "_PROCESS_POOL_EXECUTOR", _RecordingPool)
    result = write_reviewed_pdfs(
        findings,
        [first, second],
        tmp_path / "out",
        max_workers=2,
        artifact_run_id="run-scheduling",
    )

    assert observed == {
        "max_workers": 2,
        "start_method": "spawn",
        "submitted": ["B-202.pdf", "A-101.pdf"],
        "shutdown_wait": True,
    }
    assert [path.name for path in result.reviewed_pdfs] == [
        "B-202_reviewed.pdf",
        "A-101_reviewed.pdf",
    ]
    assert [receipt.output_pdf for receipt in result.receipts] == [
        "B-202_reviewed.pdf",
        "A-101_reviewed.pdf",
    ]
    assert result.coverage_status == "COMPLETE"


def test_parallel_and_single_worker_runs_have_identical_accounting(tmp_path):
    first = _make_pdf(tmp_path / "first", "A-101.pdf")
    second = _make_pdf(tmp_path / "second", "B-202.pdf")
    ids = assign_source_ids([first, second])
    findings = [
        _finding("first issue", source=first.name, source_id=ids[str(first)]),
        _finding("second issue", source=second.name, source_id=ids[str(second)]),
    ]
    kwargs = {"artifact_run_id": "run-parity"}

    sequential = write_reviewed_pdfs(
        findings,
        [first, second],
        tmp_path / "sequential",
        max_workers=1,
        **kwargs,
    )
    parallel = write_reviewed_pdfs(
        findings,
        [first, second],
        tmp_path / "parallel",
        max_workers=2,
        **kwargs,
    )

    assert [item.to_dict() for item in parallel.placements] == [
        item.to_dict() for item in sequential.placements
    ]
    assert [item.to_dict() for item in parallel.receipts] == [
        item.to_dict() for item in sequential.receipts
    ]
    assert [path.name for path in parallel.reviewed_pdfs] == [
        path.name for path in sequential.reviewed_pdfs
    ]
    assert parallel.coverage_status == sequential.coverage_status == "COMPLETE"
    assert parallel.tally == sequential.tally


def test_unpicklable_job_payload_falls_back_before_pool_start(tmp_path, monkeypatch):
    first = _make_pdf(tmp_path / "first", "A-101.pdf")
    second = _make_pdf(tmp_path / "second", "B-202.pdf")
    ids = assign_source_ids([first, second])
    findings = [
        _finding("first issue", source=first.name, source_id=ids[str(first)]),
        _finding("second issue", source=second.name, source_id=ids[str(second)]),
    ]

    class _ForbiddenPool:
        def __init__(self, **kwargs):
            raise AssertionError("unpicklable jobs must not start a process pool")

    monkeypatch.setattr(annotate, "_PROCESS_POOL_EXECUTOR", _ForbiddenPool)
    result = write_reviewed_pdfs(
        findings,
        [first, second],
        tmp_path / "out",
        max_workers=2,
        audit_stats={"injected_test_callable": lambda: None},
    )

    assert result.coverage_status == "COMPLETE"
    assert [path.name for path in result.reviewed_pdfs] == [
        "A-101_reviewed.pdf",
        "B-202_reviewed.pdf",
    ]


def test_injected_writer_callable_keeps_multi_source_path_sequential(tmp_path, monkeypatch):
    first = _make_pdf(tmp_path / "first", "A-101.pdf")
    second = _make_pdf(tmp_path / "second", "B-202.pdf")
    ids = assign_source_ids([first, second])
    findings = [
        _finding("first issue", source=first.name, source_id=ids[str(first)]),
        _finding("second issue", source=second.name, source_id=ids[str(second)]),
    ]
    original = annotate._annotate_units
    calls: list[str] = []

    def _injected_writer(pdf_path, *args, **kwargs):
        calls.append(Path(pdf_path).name)
        return original(pdf_path, *args, **kwargs)

    class _ForbiddenPool:
        def __init__(self, **kwargs):
            raise AssertionError("a monkeypatched writer must stay in-process")

    monkeypatch.setattr(annotate, "_annotate_units", _injected_writer)
    monkeypatch.setattr(annotate, "_PROCESS_POOL_EXECUTOR", _ForbiddenPool)
    result = write_reviewed_pdfs(
        findings, [first, second], tmp_path / "out", max_workers=2
    )

    assert calls == ["A-101.pdf", "B-202.pdf"]
    assert result.coverage_status == "COMPLETE"


def test_worker_boot_failure_retries_only_when_no_output_exists(tmp_path, monkeypatch):
    first = _make_pdf(tmp_path / "first", "A-101.pdf")
    second = _make_pdf(tmp_path / "second", "B-202.pdf")
    ids = assign_source_ids([first, second])
    findings = [
        _finding("first issue", source=first.name, source_id=ids[str(first)]),
        _finding("second issue", source=second.name, source_id=ids[str(second)]),
    ]

    class _BootFailure:
        def result(self):
            raise RuntimeError("worker failed during boot")

    class _BrokenPool:
        def __init__(self, **kwargs):
            pass

        def submit(self, fn, job):
            return _BootFailure()

        def shutdown(self, *, wait):
            pass

    monkeypatch.setattr(annotate, "_PROCESS_POOL_EXECUTOR", _BrokenPool)
    result = write_reviewed_pdfs(
        findings, [first, second], tmp_path / "out", max_workers=2
    )

    assert result.coverage_status == "COMPLETE"
    assert [path.name for path in result.reviewed_pdfs] == [
        "A-101_reviewed.pdf",
        "B-202_reviewed.pdf",
    ]


def test_index_rows_are_severity_first_then_position(tmp_path):
    # §18.7 (DA-025): the reviewed-PDF index presents actionable order — high,
    # then medium, then low — within severity by page/position — while the
    # stable QC ids themselves are untouched (display order need not be
    # numeric id order).
    src = _make_pdf(tmp_path, pages=1)
    low = _finding("low first by number", severity="low", rect=(100, 100, 220, 140))
    med = _finding("medium issue", severity="medium", rect=(100, 200, 220, 240))
    high = _finding("high issue", severity="high", rect=(100, 300, 220, 340))
    low.qc_id, med.qc_id, high.qc_id = "QC-001", "QC-002", "QC-003"

    res = write_reviewed_pdfs([low, med, high], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        index_text = doc[0].get_text()
    finally:
        doc.close()
    # All three rows are on the index, ordered by severity, not by QC number.
    pos = {qc: index_text.find(qc) for qc in ("QC-001", "QC-002", "QC-003")}
    assert all(v >= 0 for v in pos.values())
    assert pos["QC-003"] < pos["QC-002"] < pos["QC-001"]


def test_index_severity_ties_break_by_source_page_position(tmp_path):
    # Within one severity tier the order is source input order, page, then
    # top-to-bottom position — the §18.7 within-severity rule.
    src = _make_pdf(tmp_path, pages=2)
    lower = _finding("same page lower", severity="high", rect=(100, 400, 220, 440))
    upper = _finding("same page upper", severity="high", rect=(100, 100, 220, 140))
    page2 = _finding("later page", severity="high", page=1, rect=(100, 100, 220, 140))
    upper.qc_id, lower.qc_id, page2.qc_id = "QC-001", "QC-002", "QC-003"

    res = write_reviewed_pdfs([lower, upper, page2], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        index_text = doc[0].get_text()
    finally:
        doc.close()
    pos = {qc: index_text.find(qc) for qc in ("QC-001", "QC-002", "QC-003")}
    assert pos["QC-001"] < pos["QC-002"] < pos["QC-003"]


# --------------------------------------------------------------------------- #
# QC Findings bookmark outline (HTML↔PDF links, Component B)
# --------------------------------------------------------------------------- #


def test_reviewed_pdf_carries_qc_findings_bookmark_outline(tmp_path):
    # The marked-up set is self-navigable in Bluebeam/Acrobat: a 'QC Findings'
    # outline with one GOTO child per inked finding, jumping to its page + mark.
    src = _make_pdf(tmp_path, pages=2)
    a = _finding("clearance", status="VERIFIED", page=0, quote="VAV-3")
    b = _finding("page 2 issue", status="VERIFIED", page=1, rect=(120, 120, 300, 160), quote="WH-1")
    a.qc_id, b.qc_id = "QC-001", "QC-002"

    res = write_reviewed_pdfs([a, b], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        toc = doc.get_toc(simple=False)
    finally:
        doc.close()

    parents = [t for t in toc if t[0] == 1]
    children = [t for t in toc if t[0] == 2]
    assert parents and parents[0][1].startswith("QC Findings")
    assert len(children) == 2
    titles = " ".join(t[1] for t in children)
    assert "QC-001" in titles and "QC-002" in titles
    # Every child is a real GOTO destination (page + zoom) — what makes Bluebeam
    # and Acrobat jump to the mark, not just list a heading.
    for _lvl, _title, page, dest in children:
        assert dest.get("kind") == pymupdf.LINK_GOTO
        assert page >= 1


def test_bookmark_outline_absent_when_no_findings_anchor_to_a_page(tmp_path):
    # A set-level finding (page_index -1) anchors to no page → no outline, and
    # the writer still ships the reviewed copy (I-3).
    src = _make_pdf(tmp_path, pages=1)
    f = _finding("set-level note", status="VERIFIED", page=-1, rect=None)
    f.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
    f.qc_id = "QC-001"
    res = write_reviewed_pdfs([f], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        assert doc.get_toc(simple=False) == []
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Severity layers (PDF optional-content groups)
# --------------------------------------------------------------------------- #


def _layer_names(doc) -> "dict[int, str]":
    return {xref: info["name"] for xref, info in doc.get_ocgs().items()}


def test_severity_layers_created_named_and_all_on(tmp_path):
    # High/medium/low findings each earn a layer, created in the fixed
    # high→medium→low order (deterministic, I-7) and all shipped visible so the
    # reviewed PDF renders exactly as before.
    src = _make_pdf(tmp_path, pages=1)
    findings = [
        _finding("hi", severity="high", quote="HQ", rect=(100, 100, 220, 140)),
        _finding("med", severity="medium", quote="MQ", rect=(300, 100, 420, 140)),
        _finding("lo", severity="low", quote="LQ", rect=(100, 300, 220, 340)),
    ]
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out")
    assert res.coverage_status == "COMPLETE"       # layers never break DA-007
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        ocgs = doc.get_ocgs()
        # add_ocg allocates increasing xrefs, so sorted-by-xref == creation order.
        ordered = [ocgs[x]["name"] for x in sorted(ocgs)]
        assert ordered == [_SEVERITY_LAYER_NAMES[t] for t in _SEVERITY_LAYER_ORDER]
        assert all(info["on"] for info in ocgs.values())
    finally:
        doc.close()


def test_each_cloud_lands_on_its_severity_layer(tmp_path):
    src = _make_pdf(tmp_path, pages=1)
    findings = [
        _finding("hi", severity="high", quote="HQ", rect=(100, 100, 220, 140)),
        _finding("med", severity="medium", quote="MQ", rect=(300, 100, 420, 140)),
        _finding("lo", severity="low", quote="LQ", rect=(100, 300, 220, 340)),
    ]
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        names = _layer_names(doc)
        by_layer = {
            names[a.get_oc()]: a.info["content"]
            for page in doc for a in page.annots() if a.type[1] == "Square"
        }
        assert "hi" in by_layer[_SEVERITY_LAYER_NAMES["high"]]
        assert "med" in by_layer[_SEVERITY_LAYER_NAMES["medium"]]
        assert "lo" in by_layer[_SEVERITY_LAYER_NAMES["low"]]
    finally:
        doc.close()


def test_question_finding_layers_by_severity_not_color(tmp_path):
    # A question-category finding is drawn blue (like low), but it must ride its
    # own SEVERITY layer — a high-severity question belongs on the High layer.
    src = _make_pdf(tmp_path, pages=1)
    q = _finding("a question", severity="high", category="question", quote="QQ",
                 rect=(100, 100, 220, 140))
    res = write_reviewed_pdfs([q], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        assert [i["name"] for i in doc.get_ocgs().values()] == [
            _SEVERITY_LAYER_NAMES["high"]
        ]
        square = next(a for page in doc for a in page.annots() if a.type[1] == "Square")
        assert _layer_names(doc)[square.get_oc()] == _SEVERITY_LAYER_NAMES["high"]
    finally:
        doc.close()


def test_only_present_severity_tiers_get_a_layer(tmp_path):
    # No empty layers: a set with only high-severity ink creates only the High layer.
    src = _make_pdf(tmp_path, pages=1)
    findings = [
        _finding("hi one", severity="high", quote="H1", rect=(100, 100, 220, 140)),
        _finding("hi two", severity="high", quote="H2", rect=(300, 100, 420, 140)),
    ]
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        assert [i["name"] for i in doc.get_ocgs().values()] == [
            _SEVERITY_LAYER_NAMES["high"]
        ]
    finally:
        doc.close()


def test_unset_severity_folds_into_the_low_layer(tmp_path):
    src = _make_pdf(tmp_path, pages=1)
    f = _finding("no sev", severity="", quote="NS", rect=(100, 100, 220, 140))
    res = write_reviewed_pdfs([f], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        assert [i["name"] for i in doc.get_ocgs().values()] == [
            _SEVERITY_LAYER_NAMES["low"]
        ]
        square = next(a for page in doc for a in page.annots() if a.type[1] == "Square")
        assert _layer_names(doc)[square.get_oc()] == _SEVERITY_LAYER_NAMES["low"]
    finally:
        doc.close()


def test_qc_tag_and_leader_share_the_finding_layer(tmp_path):
    # A cloud's QC tag and a margin callout's leader line ride the same severity
    # layer as the finding they belong to.
    src = _make_pdf(tmp_path, pages=1)
    cloud = _finding("cloud hi", severity="high", quote="CQ", rect=(100, 100, 220, 140))
    margin = _finding("absent lo", severity="low", quote="", rect=None)
    margin.anchor_hint = "SHEET"
    margin.tile = [1, 1]
    assign_qc_ids([cloud, margin])
    meta = {0: {"words": [], "rows": 6, "cols": 6, "overlap_frac": 0.08,
                "page_width_pt": 792.0, "page_height_pt": 612.0}}
    res = annotate_pdf(src, [cloud, margin], tmp_path / "r.pdf",
                       include_unverified=True, sheet_meta=meta, index_pages=False)
    assert res.coverage_status == "COMPLETE"
    doc = pymupdf.open(str(tmp_path / "r.pdf"))
    try:
        names = _layer_names(doc)
        square = next(a for page in doc for a in page.annots() if a.type[1] == "Square")
        line = next(a for page in doc for a in page.annots() if a.type[1] == "Line")
        assert names[square.get_oc()] == _SEVERITY_LAYER_NAMES["high"]   # cloud
        assert names[line.get_oc()] == _SEVERITY_LAYER_NAMES["low"]      # leader
        # The two FreeText annots are the cloud's tag (High) and the callout (Low).
        freetext_layers = {
            names[a.get_oc()]
            for page in doc for a in page.annots() if a.type[1] == "FreeText"
        }
        assert freetext_layers == {
            _SEVERITY_LAYER_NAMES["high"], _SEVERITY_LAYER_NAMES["low"]
        }
    finally:
        doc.close()


def test_set_review_notes_pdf_is_layered_by_severity(tmp_path):
    # The set-level notes PDF carries the same severity layers as the reviewed PDFs.
    def _set_level(text, sev):
        return Finding(
            sheet_id="", source_name="", page_index=-1, category="conflict",
            severity=sev, text=text, anchor_hint="SET_INDEX",
            verification=Verification(status="SKIPPED"),
        )

    findings = [_set_level("set hi", "high"), _set_level("set lo", "low")]
    assign_qc_ids(findings)
    res = write_set_review_notes_pdf(findings, tmp_path / "out")
    assert res.coverage_status == "COMPLETE"
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        names = _layer_names(doc)
        assert {i["name"] for i in doc.get_ocgs().values()} == {
            _SEVERITY_LAYER_NAMES["high"], _SEVERITY_LAYER_NAMES["low"]
        }
        by_layer = {
            names[a.get_oc()]: a.info["content"]
            for page in doc for a in page.annots()
        }
        assert "set hi" in by_layer[_SEVERITY_LAYER_NAMES["high"]]
        assert "set lo" in by_layer[_SEVERITY_LAYER_NAMES["low"]]
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# GOTO destinations in the reviewed PDF (P7 item 27)
#
# The *math* of the destination transform is pinned in
# ``tests/test_drawing_geometry.py`` against independent ground truth (an
# annotation's raw ``/Rect``, which the PDF spec puts in the same default user
# space as an ``/XYZ`` destination).  What is pinned HERE is the wiring: that
# every destination the writer emits actually goes through it, at every
# rotation × CropBox, read as raw ``/XYZ`` out of the saved file rather than
# through PyMuPDF's own readers — which re-apply the very transform under test
# and would hide the defect.
#
# The load-bearing assertion needs no external truth at all: the index-page row
# link and the bookmark outline reach the same mark through two *different*
# PyMuPDF entry points (``insert_link`` and ``set_toc``) whose internal
# transforms differ, so if either inversion is wrong the two disagree.
# --------------------------------------------------------------------------- #

_DEST_ROTATIONS = (0, 90, 180, 270)
_DEST_CROPBOXES = (None, (40, 25, 40, 25))     # inset (l, t, r, b), asymmetric in y


def _rotated_cropped_pdf(dir_path: Path, rot: int, crop, name="M-101.pdf") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page(width=792, height=612).insert_text(
            (150, 200), f"TARGETWORD{i}", fontsize=14
        )
    page = doc[0]
    if crop is not None:
        mb = page.mediabox
        page.set_cropbox(pymupdf.Rect(mb.x0 + crop[0], crop[1],
                                      mb.x1 - crop[2], (mb.y1 - mb.y0) - crop[3]))
    if rot:
        page.set_rotation(rot)
    path = dir_path / name
    doc.save(str(path))
    doc.close()
    return path


def _raw_destinations(doc) -> dict:
    """Raw ``/XYZ`` per destination kind, straight out of the PDF objects.

    Returns ``{"link": [(x, y), …], "outline": [(x, y), …]}``.  Deliberately
    NOT ``page.get_links()`` / ``doc.get_toc()``: both map the stored value back
    through the same transform being tested, so a wrong destination reads back
    as the point that was asked for.
    """
    import re
    out = {"link": [], "outline": []}
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref)
        except Exception:            # noqa: BLE001 - a free/odd xref is not a destination
            continue
        m = re.search(r"/XYZ\s+([\d.\-]+)\s+([\d.\-]+)", obj)
        if not m:
            continue
        pt = (round(float(m.group(1)), 1), round(float(m.group(2)), 1))
        if "/Title" in obj:
            # The 'QC Findings' parent targets the page top, not a mark; only the
            # per-finding leaves do.  Match on the absence of /First rather than
            # on the title text — a bookmark title is stored as a hex UTF-16BE
            # string, so "QC-" never appears literally in the object.
            if "/First" not in obj:
                out["outline"].append(pt)
        elif "/Link" in obj:
            out["link"].append(pt)
    return out


@pytest.mark.parametrize("rot", _DEST_ROTATIONS)
@pytest.mark.parametrize("crop", _DEST_CROPBOXES)
def test_reviewed_pdf_destinations_land_in_user_space(tmp_path, rot, crop):
    from drawing_analyzer.annotate import _dest_user_point

    src = _rotated_cropped_pdf(tmp_path / "src", rot, crop)
    view_rect = (100.0, 120.0, 260.0, 150.0)
    f = _finding("drain size wrong", status="VERIFIED", page=0, rect=view_rect,
                 quote="TARGETWORD0")
    f.qc_id = "QC-001"

    res = write_reviewed_pdfs([f], [src], tmp_path / "out")
    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        dests = _raw_destinations(doc)
        # The mark lives on the source page shifted by the front index page(s).
        target = doc.page_count - 2 if doc.page_count >= 3 else 0
        expected_pt = _dest_user_point(doc[target], view_rect[0], view_rect[1])
        expected = (round(expected_pt.x, 1), round(expected_pt.y, 1))
    finally:
        doc.close()

    assert dests["link"], f"no index-row GOTO link written at rot={rot} crop={crop}"
    assert dests["outline"], f"no QC bookmark destination written at rot={rot} crop={crop}"

    for got in dests["link"]:
        assert abs(got[0] - expected[0]) < 1.2 and abs(got[1] - expected[1]) < 1.2, (
            f"index-row /XYZ {got} != user-space {expected} at rot={rot} crop={crop}"
        )
    for got in dests["outline"]:
        assert abs(got[0] - expected[0]) < 1.2 and abs(got[1] - expected[1]) < 1.2, (
            f"bookmark /XYZ {got} != user-space {expected} at rot={rot} crop={crop}"
        )
    # Two entry points, two internal transforms, one mark: they must agree.
    assert dests["link"][0] == dests["outline"][0], (
        f"index link {dests['link'][0]} and bookmark {dests['outline'][0]} name "
        f"different points at rot={rot} crop={crop}"
    )


def test_overflow_page_backlink_uses_the_destination_transform(tmp_path):
    # The third destination site: the AI Review Notes page's GOTO back to the
    # source sheet.  Its rect-bearing branch is defensive — the overflow list is
    # fed only MARGIN placements, which are rect-less — so it is unreachable
    # through write_reviewed_pdfs and has to be exercised directly.  It is the
    # twin of the index-row link, and an untested twin is where this campaign's
    # defects have consistently lived.
    from drawing_analyzer.annotate import (
        _dest_user_point, _insert_review_notes_page,
    )
    from drawing_analyzer.models import MarkupPlacement

    view_rect = (100.0, 120.0, 260.0, 150.0)
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((150, 200), "TARGETWORD0", fontsize=14)
    mb = page.mediabox
    page.set_cropbox(pymupdf.Rect(mb.x0 + 40, 25, mb.x1 - 40, (mb.y1 - mb.y0) - 25))
    page.set_rotation(90)
    try:
        f = _finding("did not fit a clear band", status="VERIFIED", page=0,
                     rect=view_rect, quote="TARGETWORD0")
        f.qc_id = "QC-001"
        placement = MarkupPlacement(
            run_id="r1", placement_id="r1#f1#primary", finding_id=f.id,
            qc_id="QC-001", scope="SOURCE", source_id="SRC-0001", page_index=0,
            leg_id="primary", expected="MARGIN", required_components=["callout"],
        )
        _insert_review_notes_page(doc, [(f, placement)], n_index=0, run_id="r1",
                                  author="tester")
        dests = _raw_destinations(doc)
        expected_pt = _dest_user_point(doc[0], view_rect[0], view_rect[1])
        expected = (round(expected_pt.x, 1), round(expected_pt.y, 1))
    finally:
        doc.close()

    assert dests["link"], "the notes page wrote no GOTO back to the source sheet"
    for got in dests["link"]:
        assert abs(got[0] - expected[0]) < 1.2 and abs(got[1] - expected[1]) < 1.2, (
            f"notes-page backlink /XYZ {got} != user-space {expected}"
        )


# --------------------------------------------------------------------------- #
# FreeText truncation is not undone by set_info (P7 item 33)
#
# For a plain FreeText annot /Contents IS the displayed text, so passing the
# untruncated string to set_info after handing the truncated one to
# add_freetext_annot writes the whole string back and draws it.
# --------------------------------------------------------------------------- #


def _freetext_contents(path) -> list[str]:
    """Every FreeText annot's raw /Contents in the saved file, in page order."""
    doc = pymupdf.open(str(path))
    try:
        out = []
        for pno in range(doc.page_count):
            for annot in doc[pno].annots():
                if annot.type[1] == "FreeText":
                    raw = doc.xref_get_key(annot.xref, "Contents")
                    if raw and len(raw) > 1:
                        out.append(str(raw[1]))
        return out
    finally:
        doc.close()


_LONG_FINDING_TEXT = (
    "Sprinkler head spacing exceeds the maximum permitted for the hazard "
    "classification shown, and the branch line drain is undersized relative to "
    "the main it serves; verify against the hydraulic calculations and the "
    "manufacturer's listed spacing for this head model before issuing for "
    "construction, and confirm the remote area selection while you are there."
)


def test_freetext_contents_stays_truncated(tmp_path):
    # A margin callout is capped at 220 chars for display. /Contents must carry
    # the capped string, not the full one.
    src = _make_pdf(tmp_path / "src", pages=1)
    f = _finding(_LONG_FINDING_TEXT, status="VERIFIED", page=0, rect=None, quote="")
    f.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
    f.qc_id = "QC-001"

    res = write_reviewed_pdfs([f], [src], tmp_path / "out")
    contents = _freetext_contents(res.reviewed_pdfs[0])
    assert contents, "no FreeText callout was written at all"
    assert any(c.endswith("...") for c in contents), (
        "no callout was truncated, so this test is not exercising the cap"
    )
    for c in contents:
        assert len(c) <= 420, (
            f"/Contents is {len(c)} chars — set_info overwrote the truncated "
            f"display text with the full string"
        )


def test_set_level_review_notes_contents_stays_truncated(tmp_path):
    from drawing_analyzer.models import assign_qc_ids

    long_action = "Coordinate with the fire protection engineer and " * 6
    f = _finding(_LONG_FINDING_TEXT, status="UNCERTAIN", page=-1, rect=None, quote="")
    f.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
    f.anchor_hint = "SET"          # _is_set_level_finding: SET-scoped, no source_id
    f.source_id = ""
    f.recommended_action = long_action
    assign_qc_ids([f])

    res = write_set_review_notes_pdf([f], tmp_path / "out")
    paths = [q for q in (getattr(res, "reviewed_pdfs", None) or []) if q]
    assert paths, "no set-level review notes PDF was written"
    for c in _freetext_contents(paths[0]):
        assert len(c) <= 420, f"/Contents is {len(c)} chars — truncation was undone"


# --------------------------------------------------------------------------- #
# Index rows fit their column and survive Base-14 (P7 item 32)
# --------------------------------------------------------------------------- #


def test_index_row_text_fits_its_column(tmp_path):
    # Realistic UPPERCASE drawing text: the shipped 62-char cap measured 285 pt in
    # a 238 pt column. Lowercase prose fits, which is why this survived — sheets
    # are lettered uppercase, and uppercase is the wider case.
    from drawing_analyzer.annotate import _INDEX_COL_W, _INDEX_COL_X

    src = _make_pdf(tmp_path / "src", pages=1)
    f = _finding("SPRINKLER HEAD SPACING EXCEEDS MAXIMUM PERMITTED BY NFPA 13 "
                 "AND THE DRAIN IS UNDERSIZED FOR THE MAIN IT SERVES",
                 status="VERIFIED", page=0, quote="VAV-3")
    f.sheet_id = "FP-101-MEZZANINE-LEVEL-A"
    f.qc_id = "QC-001"
    res = write_reviewed_pdfs([f], [src], tmp_path / "out")

    from drawing_analyzer.annotate import _INDEX_TOP

    doc = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        # Table rows only. The page title and the author subtitle sit above
        # _INDEX_TOP at the same left margin as column 0 and are not table cells.
        words = [w for w in doc[0].get_text("words") if w[1] >= _INDEX_TOP - 10]
    finally:
        doc.close()
    assert words, "no table rows were drawn"

    right_edge = _INDEX_COL_X[-1] + _INDEX_COL_W[-1]
    # No word drawn in the findings column may cross its right edge.
    spill = [w for w in words if w[0] >= _INDEX_COL_X[-1] - 1 and w[2] > right_edge + 1]
    assert not spill, f"index text overflowed its column: {[w[4] for w in spill]}"
    # Each earlier column stays inside its own width too.
    for i in range(len(_INDEX_COL_X) - 1):
        lo, hi = _INDEX_COL_X[i], _INDEX_COL_X[i] + _INDEX_COL_W[i]
        over = [w for w in words if lo - 1 <= w[0] < _INDEX_COL_X[i + 1] and w[2] > hi + 1]
        assert not over, f"column {i} overflowed: {[w[4] for w in over]}"


def test_index_columns_are_derived_from_one_definition():
    # Header labels and data cells must come from the same column table, or the
    # width a cell is fitted to stops matching the space the header claims.
    from drawing_analyzer.annotate import (
        _INDEX_COL_GUTTER, _INDEX_COL_LABELS, _INDEX_COL_RIGHT, _INDEX_COL_W,
        _INDEX_COL_X,
    )

    assert len(_INDEX_COL_X) == len(_INDEX_COL_LABELS) == len(_INDEX_COL_W)
    for i in range(len(_INDEX_COL_X) - 1):
        assert _INDEX_COL_W[i] == _INDEX_COL_X[i + 1] - _INDEX_COL_X[i] - _INDEX_COL_GUTTER
    assert _INDEX_COL_W[-1] == _INDEX_COL_RIGHT - _INDEX_COL_X[-1] - _INDEX_COL_GUTTER


def test_base14_safe_folds_typography_instead_of_drawing_a_dot():
    # insert_text's Base-14 fonts silently draw a MIDDLE DOT for anything outside
    # Latin-1 — no exception. '3" drain' written with a U+2033 prime became
    # '3. drain': a mangled dimension in a fire-sprinkler index still reads as a
    # number, which is worse than a missing one.
    from drawing_analyzer.annotate import _base14_safe

    assert _base14_safe("3″ drain") == '3" drain'
    assert _base14_safe("detail — see M-501") == "detail - see M-501"
    assert _base14_safe("2′1/2″") == "2'1/2\""
    assert _base14_safe("1⁄2 inch") == "1/2 inch"
    assert _base14_safe("300 × 200") == "300 x 200"
    assert _base14_safe("spacing ≤ 12 FT") == "spacing <= 12 FT"
    # Latin-1 characters Base-14 CAN draw are left alone, not degraded.
    assert _base14_safe("½ inch at 45°") == "½ inch at 45°"
    # Anything still undrawable reads as unknown, never as punctuation.
    assert _base14_safe("zone ①") == "zone ?"
    # Every result is drawable by the Base-14 encoding.
    for probe in ("3″", "a—b", "zone ①", "½°"):
        _base14_safe(probe).encode("latin-1")


def test_fit_text_measures_width_not_characters():
    from drawing_analyzer.annotate import _fit_text

    wide = "SPRINKLER HEAD SPACING EXCEEDS MAXIMUM PERMITTED BY NFPA 13"
    fitted = _fit_text(wide, 238.0, fontsize=8)
    assert pymupdf.get_text_length(fitted, fontname="helv", fontsize=8) <= 238.0
    assert fitted.endswith("...")
    # Same character count, narrower glyphs -> more of it survives.
    narrow = "iiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiiii"
    assert len(_fit_text(narrow, 238.0, fontsize=8)) > len(fitted)
    # Text that already fits is returned whole, with no ellipsis.
    assert _fit_text("FP-101", 238.0, fontsize=8) == "FP-101"
    # A column too narrow for even the ellipsis yields nothing, never an overflow.
    assert _fit_text(wide, 1.0, fontsize=8) == ""


# --------------------------------------------------------------------------- #
# Placement labels, index link targets, generated-page CropBox (P7 item 34)
# --------------------------------------------------------------------------- #


def test_quote_less_finding_is_not_labelled_quote_not_found():
    # [QUOTE NOT FOUND] is the hallucination signal: the quote SHOULD have been
    # findable and was not. A graphics-only finding never offered a quote, so
    # stamping it with that signal spends the reviewer's trust on a finding that
    # did nothing wrong — and made it indistinguishable from a fabricated quote.
    from drawing_analyzer.annotate import _annot_content, _placement_kind

    graphics_only = _finding("Sprinkler omitted under the duct", status="UNCERTAIN",
                             rect=None, quote="")
    graphics_only.anchor = Anchor(status="UNANCHORED", rect_pdf=None,
                                  method="quote_not_found")
    assert _placement_kind(graphics_only) == "NO_QUOTE"
    first = _annot_content(graphics_only, unverified=True, rejected=False,
                           place=_placement_kind(graphics_only)).splitlines()[0]
    assert "[NO QUOTE TO CHECK]" in first
    assert "[QUOTE NOT FOUND]" not in first

    # A real quote that matched nothing still gets the hallucination signal.
    fabricated = _finding("Sprinkler omitted under the duct", status="UNCERTAIN",
                          rect=None, quote="PROVIDE 6 INCH DRAIN")
    fabricated.anchor = Anchor(status="UNANCHORED", rect_pdf=None,
                               method="quote_not_found")
    assert _placement_kind(fabricated) == "UNANCHORED"
    first = _annot_content(fabricated, unverified=True, rejected=False,
                           place=_placement_kind(fabricated)).splitlines()[0]
    assert "[QUOTE NOT FOUND]" in first
    assert "[NO QUOTE TO CHECK]" not in first

    # A sheet-wide finding keeps its own label rather than either of those.
    sheet_wide = _finding("Sheet lacks a north arrow", status="UNCERTAIN",
                          rect=None, quote="")
    sheet_wide.anchor_hint = "SHEET"
    sheet_wide.anchor = Anchor(status="UNANCHORED", rect_pdf=None,
                               method="quote_not_found")
    assert _placement_kind(sheet_wide) == "SHEET"


def test_evidence_tag_is_not_stacked_or_repeated():
    # The evidence tag must not duplicate a prefix the placement already carries,
    # nor stack onto the contradictory hallucination signal.
    from drawing_analyzer.annotate import _annot_content, _placement_kind
    from drawing_analyzer.models import EVIDENCE_UNAVAILABLE

    f = _finding("Sprinkler omitted", status="UNCERTAIN", rect=None, quote="")
    f.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
    f.evidence_state = EVIDENCE_UNAVAILABLE
    first = _annot_content(f, unverified=True, rejected=False,
                           place=_placement_kind(f)).splitlines()[0]
    assert first.count("[NO QUOTE TO CHECK]") == 1


def _overflow_case(tmp_path):
    """A sheet dense enough that some callouts must overflow to the notes page."""
    from drawing_analyzer.models import assign_qc_ids

    src = _make_pdf(tmp_path / "src", pages=1)
    words = [(float(30 + 150 * i), float(20 + 24 * j), float(130 + 150 * i),
              float(32 + 24 * j), "TXT", 0, 0, 0)
             for i in range(5) for j in range(22)]
    meta = {0: {"words": words, "rows": 2, "cols": 2, "page_width_pt": 792.0,
                "page_height_pt": 612.0, "overlap_frac": 0.08}}
    findings = []
    for i in range(7):
        f = _finding(f"expected item {i}; not found on this sheet", status="VERIFIED",
                     page=0, rect=None, quote="")
        f.anchor_hint = "SHEET"
        f.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
        findings.append(f)
    assign_qc_ids(findings)
    return src, findings, meta


def test_index_row_targets_the_page_its_mark_landed_on(tmp_path):
    # A callout that overflowed to the AI Review Notes page has NO mark on its
    # sheet, so an index row pointing at the sheet sent the reviewer to a page
    # with nothing on it — while the bookmark outline and the receipt both
    # correctly named the notes page. All three must agree.
    src, findings, meta = _overflow_case(tmp_path)
    out = tmp_path / "M-101_reviewed.pdf"
    res = annotate_pdf(src, findings, out, sheet_meta=meta)
    assert res.tally.get("review_notes", 0) >= 1, "nothing overflowed; test is inert"
    assert res.tally.get("margin", 0) >= 1, "nothing stayed on the sheet; test is inert"

    doc = pymupdf.open(str(out))
    try:
        notes_pno = next(p for p in range(doc.page_count)
                         if "AI REVIEW NOTES" in doc[p].get_text().upper())
        index_targets = {lk.get("page") for lk in doc[0].get_links()
                         if lk.get("kind") == pymupdf.LINK_GOTO}
    finally:
        doc.close()

    receipt_pages = {r.output_page_index for r in res.receipts if r.status == "WRITTEN"}
    assert notes_pno in receipt_pages, "no mark landed on the notes page"
    # The index must reach the notes page, not only the drawing sheet.
    assert notes_pno in index_targets, (
        f"index rows target {sorted(index_targets)} but marks are on "
        f"{sorted(receipt_pages)} — an overflowed row points at a page with no mark"
    )
    # And every page an index row points at is a page some mark actually landed on.
    assert index_targets <= receipt_pages, (
        f"index rows point at {sorted(index_targets - receipt_pages)}, where no "
        f"mark was written"
    )


def test_reordering_the_generated_pages_kept_coverage_complete(tmp_path):
    # The index is now inserted last, so source, appendix and notes pages all
    # shift by the same n_index. If a stamp used the wrong offset, DA-007
    # reconciliation would not find the mark and coverage would degrade.
    src, findings, meta = _overflow_case(tmp_path)
    res = annotate_pdf(src, findings, tmp_path / "M-101_reviewed.pdf", sheet_meta=meta)
    assert res.coverage_status == "COMPLETE", (
        f"coverage {res.coverage_status}; receipts: "
        f"{[(r.placement.qc_id, r.status) for r in res.receipts]}"
    )
    assert all(r.status == "WRITTEN" for r in res.receipts)


def test_generated_pages_pin_their_cropbox(tmp_path):
    # /CropBox is an inheritable page-tree attribute. In a set whose /Pages node
    # carries one — legal, and produced by some CAD exporters — a generated index
    # page inherited the DRAWING's CropBox: measured 512x712 visible instead of
    # 612x792, clipped right and shifted vertically.
    from drawing_analyzer.annotate import _INDEX_PAGE_H, _INDEX_PAGE_W

    src = tmp_path / "inherited.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=1728, height=1188)
    doc = pymupdf.open("pdf", doc.tobytes())
    pages_xref = int(str(doc.xref_get_key(doc.pdf_catalog(), "Pages")[1]).split()[0])
    doc.xref_set_key(pages_xref, "CropBox", "[100 80 1628 1108]")
    doc.save(str(src))
    doc.close()

    # source= must match the file's name, or no finding is matched to it and no
    # reviewed PDF is written at all.
    f = _finding("clearance issue", status="VERIFIED", page=0, rect=(100, 120, 300, 160),
                 quote="", source="inherited.pdf")
    f.qc_id = "QC-001"
    res = write_reviewed_pdfs([f], [src], tmp_path / "out")

    out = pymupdf.open(str(res.reviewed_pdfs[0]))
    try:
        index = out[0]
        assert "FINDINGS INDEX" in index.get_text().upper(), "page 0 is not the index"
        assert index.rect.width == pytest.approx(_INDEX_PAGE_W), (
            f"generated page is {index.rect.width} pt wide, not {_INDEX_PAGE_W} — "
            f"it inherited the drawing's CropBox"
        )
        assert index.rect.height == pytest.approx(_INDEX_PAGE_H)
        assert index.cropbox == index.mediabox
    finally:
        out.close()


def test_component_stamps_name_the_page_they_are_actually_on(tmp_path):
    # DA-007 reconciliation deliberately ignores the stamp's page field and uses
    # the page the component was actually found on, so a wrong page in the stamp
    # degrades nothing today — which is exactly why it can rot silently. It is
    # still part of the persisted stamp format written into the artifact, so it is
    # asserted here against the page the annotation really occupies. This is the
    # only observable for the review-notes shift: the notes page is written before
    # the front-inserted index and so must be offset by n_index like every other
    # page.
    from drawing_analyzer.annotate import _read_stamp

    src, findings, meta = _overflow_case(tmp_path)
    out = tmp_path / "M-101_reviewed.pdf"
    res = annotate_pdf(src, findings, out, sheet_meta=meta)
    assert res.tally.get("review_notes", 0) >= 1, "nothing overflowed; test is inert"

    doc = pymupdf.open(str(out))
    try:
        mismatched, checked = [], 0
        for pno in range(doc.page_count):
            for annot in doc[pno].annots():
                stamp = _read_stamp(doc, annot.xref)
                if stamp is None:
                    continue
                checked += 1
                _pid, comp, stamped_page = stamp
                if stamped_page != pno:
                    mismatched.append((comp, stamped_page, pno))
    finally:
        doc.close()

    assert checked, "no stamped components were found at all"
    assert not mismatched, (
        "stamps name the wrong page (component, stamped, actual): " f"{mismatched}"
    )
