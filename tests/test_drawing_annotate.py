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
