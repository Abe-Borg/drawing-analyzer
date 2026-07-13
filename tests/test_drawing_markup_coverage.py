"""Phase 21 (DA-007): artifact-backed markup coverage — the writer-and-reopen
receipt protocol.

These tests exercise the *failure* side of the writer: they force clouds,
callouts, index pages, saves, and reopens to fail and prove the receipts report
those failures honestly (coverage INCOMPLETE, a tally that never claims ink a PDF
never received). They also prove the two isolation guarantees — a run's stamps
never satisfy a *different* run's plan (§13.3) and unrelated pre-existing source
annotations are ignored (DA-029).

Every mark the writer draws is stamped with a private PDF object key; the writer
reopens the saved file and reconciles those stamps against the plan. So these
tests inspect the *reopened artifact*, never the writer's intentions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer import annotate  # noqa: E402
from drawing_analyzer.annotate import (  # noqa: E402
    _PLACEMENT_KEY,
    _reconcile_pdf,
    annotate_pdf,
    count_annotations,
    new_artifact_run_id,
    write_reviewed_pdfs,
)
from drawing_analyzer.models import (  # noqa: E402
    Anchor,
    ConflictLeg,
    Finding,
    MarkupPlacement,
    Verification,
    assign_qc_ids,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _pdf(dir_path: Path, name="M-101.pdf", pages=1, rotation=0) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"SHEET {name} p{i + 1}")
        if rotation:
            page.set_rotation(rotation)
    path = dir_path / name
    doc.save(str(path))
    doc.close()
    return path


def _f(text, *, quote, source="M-101.pdf", source_id="SRC-0001", page=0,
       rect=(72.0, 66.0, 200.0, 84.0), status="VERIFIED", hint="", cat="code",
       sev="high", also_on=None):
    anchor = Anchor(status="EXACT", rect_pdf=list(rect), method="t") if rect else Anchor()
    return Finding(
        sheet_id="M-101", source_name=source, source_id=source_id, page_index=page,
        category=cat, severity=sev, text=text, source_quote=quote,
        anchor_hint=hint, anchor=anchor, also_on=list(also_on or []),
        verification=Verification(status=status),
    )


def _reviewed_annots(path: Path) -> int:
    return count_annotations(path)


# --------------------------------------------------------------------------- #
# 1. Whole-writer failure — no false ink, coverage INCOMPLETE
# --------------------------------------------------------------------------- #


def test_whole_writer_failure_reports_no_ink(tmp_path, monkeypatch):
    src = _pdf(tmp_path)
    findings = [_f("cloud one", quote="q1"), _f("cloud two", quote="q2")]
    assign_qc_ids(findings)

    def _boom(*a, **k):
        raise RuntimeError("writer exploded")

    monkeypatch.setattr(annotate, "_annotate_units", _boom)
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out", include_unverified=True)

    assert res.reviewed_pdfs == []
    assert res.coverage_status == "INCOMPLETE"
    assert all(r.status == "FAILED" for r in res.receipts)
    # The tally cannot claim a cloud/margin nothing was written for.
    assert res.tally.get("cloud", 0) == 0 and res.tally.get("margin", 0) == 0
    assert res.tally.get("failed", 0) == 2


# --------------------------------------------------------------------------- #
# 2. One cloud fails, one succeeds — receipts distinguish them
# --------------------------------------------------------------------------- #


def test_one_cloud_fails_one_succeeds(tmp_path, monkeypatch):
    src = _pdf(tmp_path)
    findings = [_f("ok", quote="ok"), _f("boom", quote="boom")]
    assign_qc_ids(findings)

    orig = annotate._add_cloud

    def _sel(page, finding, **kw):
        if finding.text == "boom":
            raise RuntimeError("cloud failed")
        return orig(page, finding, **kw)

    monkeypatch.setattr(annotate, "_add_cloud", _sel)
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out", include_unverified=True)

    statuses = sorted(r.status for r in res.receipts)
    assert statuses == ["FAILED", "WRITTEN"]
    assert res.coverage_status == "INCOMPLETE"
    # The written cloud is proven; the failed one carries a reason.
    failed = next(r for r in res.receipts if r.status == "FAILED")
    assert "missing mandatory component" in failed.error
    # The reviewed PDF is labeled incomplete so it is never mistaken for complete.
    assert res.reviewed_pdfs and res.reviewed_pdfs[0].name.endswith("_reviewed_INCOMPLETE.pdf")


# --------------------------------------------------------------------------- #
# 3. Out-of-range page → FAILED receipt (never counted as ink)
# --------------------------------------------------------------------------- #


def test_out_of_range_page_is_a_failed_receipt(tmp_path):
    src = _pdf(tmp_path, pages=1)
    findings = [_f("on page 9", quote="q", page=9)]
    res = annotate_pdf(src, findings, tmp_path / "r.pdf", include_unverified=True)
    assert res.annots_written == 0
    assert res.coverage_status == "INCOMPLETE"
    assert [r.status for r in res.receipts] == ["FAILED"]


# --------------------------------------------------------------------------- #
# 4. Margin-callout generation failure
# --------------------------------------------------------------------------- #


def test_margin_callout_failure(tmp_path, monkeypatch):
    src = _pdf(tmp_path)
    f = _f("missing detail", quote="", hint="SHEET", rect=None)
    assign_qc_ids([f])

    monkeypatch.setattr(
        annotate, "_add_margin_callouts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("callout failed")),
    )
    res = annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=True)
    assert res.coverage_status == "INCOMPLETE"
    assert [r.status for r in res.receipts] == ["FAILED"]
    assert "missing mandatory component" in res.receipts[0].error


# --------------------------------------------------------------------------- #
# 5. Index-page generation failure for a rejected (index-only) finding
# --------------------------------------------------------------------------- #


def test_index_failure_fails_rejected_placement(tmp_path, monkeypatch):
    src = _pdf(tmp_path)
    f = _f("wrong", quote="wq", status="REJECTED")
    assign_qc_ids([f])

    monkeypatch.setattr(
        annotate, "_insert_index_pages",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("index failed")),
    )
    res = annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=True)
    # The rejected finding's only artifact is its index row — with the index gone,
    # the placement is FAILED (not silently "planned").
    assert res.coverage_status == "INCOMPLETE"
    assert [r.status for r in res.receipts] == ["FAILED"]
    assert "index row not found" in res.receipts[0].error


# --------------------------------------------------------------------------- #
# 6. Reopen failure → every placement FAILED (nothing proven)
# --------------------------------------------------------------------------- #


def test_reopen_failure_fails_every_placement(tmp_path):
    not_a_pdf = tmp_path / "garbage.pdf"
    not_a_pdf.write_text("this is not a pdf")
    run_id = "run-abc"
    placements = [
        MarkupPlacement(
            run_id=run_id, placement_id=f"{run_id}#deadbeef#primary#00000",
            finding_id="deadbeef", qc_id="QC-001", scope="SOURCE",
            source_id="SRC-0001", page_index=0, leg_id="primary", expected="CLOUD",
            required_components=["cloud"],
        )
    ]
    receipts = _reconcile_pdf(not_a_pdf, placements, run_id)
    assert [r.status for r in receipts] == ["FAILED"]
    assert "could not reopen" in receipts[0].error


def test_save_failure_is_non_fatal_and_fails_receipts(tmp_path):
    # A save into an un-creatable path fails the whole source's placements without
    # raising, and produces no reviewed PDF.
    src = _pdf(tmp_path)
    f = _f("cloud", quote="q")
    assign_qc_ids([f])
    # Point the output dir at a path that already exists as a *file*, so mkdir /
    # save cannot create the reviewed PDF beneath it.
    clash = tmp_path / "outblock"
    clash.write_text("x")
    res = write_reviewed_pdfs(f and [f], [src], clash, include_unverified=True)
    assert res.reviewed_pdfs == []
    assert res.coverage_status == "INCOMPLETE"
    assert all(r.status == "FAILED" for r in res.receipts)
    # The FAILED receipt error carries only the exception TYPE — no absolute path
    # can leak into the portable manifest (which serializes receipt errors).
    for r in res.receipts:
        assert str(tmp_path) not in r.error


def test_unroutable_finding_fails_coverage_not_silently_dropped(tmp_path):
    # A finding whose source_id matches no supplied PDF (and whose name matches no
    # basename) must get an explicit FAILED receipt — never be silently dropped,
    # which would leave coverage COMPLETE while its mark is absent (a hidden
    # failure, the dangerous direction).
    src = _pdf(tmp_path, "M-101.pdf")
    good = _f("routable", quote="q1", source="M-101.pdf", source_id="SRC-0001")
    orphan = _f("orphan", quote="q2", source="GHOST.pdf", source_id="SRC-9999")
    assign_qc_ids([good, orphan])
    res = write_reviewed_pdfs([good, orphan], [src], tmp_path / "out", include_unverified=True)

    assert res.coverage_status == "INCOMPLETE"
    by_fid = {r.placement.finding_id: r for r in res.receipts}
    assert by_fid[good.id].status == "WRITTEN"
    assert by_fid[orphan.id].status == "FAILED"
    assert "could not be routed" in by_fid[orphan.id].error
    # Every planned placement is accounted for exactly once (no drop, no dup).
    assert len(res.receipts) == len(res.placements) == 2


def test_name_fallback_no_double_draw_on_duplicate_basenames(tmp_path):
    # A finding WITHOUT a host source_id routes by source_name. Two inputs that
    # share a basename must not both receive that one finding (which would double-
    # count the placement and falsely report the run INCOMPLETE). It lands on the
    # first source only; coverage stays COMPLETE.
    a = _pdf(tmp_path / "a", "M-101.pdf")
    b = _pdf(tmp_path / "b", "M-101.pdf")
    f = _f("no-source-id", quote="q", source="M-101.pdf", source_id="")
    assign_qc_ids([f])
    res = write_reviewed_pdfs([f], [a, b], tmp_path / "out", include_unverified=True)
    assert res.coverage_status == "COMPLETE"
    assert len(res.reviewed_pdfs) == 1
    # exactly one placement, one WRITTEN receipt — never a duplicate.
    assert len(res.placements) == 1
    assert [r.status for r in res.receipts] == ["WRITTEN"]


# --------------------------------------------------------------------------- #
# 7. Pre-existing unrelated annotations are ignored (DA-029)
# --------------------------------------------------------------------------- #


def test_pre_existing_annotations_are_ignored(tmp_path):
    src = _pdf(tmp_path)
    # Seed the SOURCE with a stray, non-analyzer annotation.
    doc = pymupdf.open(str(src))
    a = doc[0].add_rect_annot(pymupdf.Rect(300, 300, 360, 340))
    a.set_info(title="Someone Else")
    a.update()
    doc.save(str(src), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    doc.close()

    f = _f("real finding", quote="q")
    assign_qc_ids([f])
    out = tmp_path / "r.pdf"
    res = annotate_pdf(src, [f], out, include_unverified=True)

    # Coverage counts only the analyzer's own cloud + QC tag; the stray annot is
    # ignored — one WRITTEN receipt, coverage COMPLETE.
    assert res.coverage_status == "COMPLETE"
    assert [r.status for r in res.receipts] == ["WRITTEN"]
    assert res.annots_written == 2                 # cloud + its QC tag
    # The reviewed copy still physically carries the stray annot (3 total: stray +
    # cloud + tag), so a naive total-count would be wrong — the receipt count is not.
    assert _reviewed_annots(out) == 3


# --------------------------------------------------------------------------- #
# 8. Dual-leg conflict: one leg fails → coverage INCOMPLETE
# --------------------------------------------------------------------------- #


def test_dual_leg_conflict_one_leg_fails(tmp_path, monkeypatch):
    a = _pdf(tmp_path, "F-D-01-1.pdf")
    b = _pdf(tmp_path, "F-A-01-1.pdf")
    conflict = _f(
        "COLO conflict", quote="COLO 5", source="F-D-01-1.pdf", source_id="",
        also_on=[ConflictLeg(
            sheet_id="F-A-01-1", source_name="F-A-01-1.pdf", source_id="",
            page_index=0, source_quote="COLO 1",
            anchor=Anchor(status="EXACT", rect_pdf=[72, 66, 200, 84], method="t"),
        )],
    )
    assign_qc_ids([conflict])

    orig = annotate._add_cloud

    def _fail_b(page, finding, **kw):
        if finding.source_name == "F-A-01-1.pdf":
            raise RuntimeError("leg B cloud failed")
        return orig(page, finding, **kw)

    monkeypatch.setattr(annotate, "_add_cloud", _fail_b)
    res = write_reviewed_pdfs([conflict], [a, b], tmp_path / "out", include_unverified=True)

    # Primary leg (A) written, secondary leg (B) failed → INCOMPLETE.
    assert res.coverage_status == "INCOMPLETE"
    statuses = sorted(r.status for r in res.receipts)
    assert statuses == ["FAILED", "WRITTEN"]
    # B's reviewed PDF is the one labeled incomplete.
    inc = [p.name for p in res.reviewed_pdfs if p.name.endswith("_INCOMPLETE.pdf")]
    assert inc == ["F-A-01-1_reviewed_INCOMPLETE.pdf"]


# --------------------------------------------------------------------------- #
# 9 & 10. Gated / rejected findings are accounted (INDEXED), never FAILED
# --------------------------------------------------------------------------- #


def test_gated_finding_is_indexed_not_failed(tmp_path):
    src = _pdf(tmp_path)
    f = _f("maybe", quote="mq", status="UNCERTAIN")
    assign_qc_ids([f])
    # verified-only gating → the uncertain finding is gated to an index row.
    res = annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=False)
    assert res.coverage_status == "COMPLETE"
    assert res.tally == {"gated": 1}
    assert [r.status for r in res.receipts] == ["INDEXED"]
    assert res.receipts[0].placement.expected == "GATED_INDEX"


def test_rejected_default_has_a_real_index_receipt(tmp_path):
    src = _pdf(tmp_path)
    f = _f("wrong", quote="wq", status="REJECTED")
    assign_qc_ids([f])
    res = annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=True)
    assert res.coverage_status == "COMPLETE"
    assert [r.status for r in res.receipts] == ["INDEXED"]
    receipt = res.receipts[0]
    assert receipt.placement.expected == "REJECTED_INDEX"
    assert receipt.index_entry_ref  # points at the reconciled index row


# --------------------------------------------------------------------------- #
# 11. Rotated-page receipts reopen successfully (Phase 19 + 21)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rot", (0, 90, 180, 270))
def test_rotated_page_receipts_reopen(tmp_path, rot):
    src = _pdf(tmp_path / f"rot{rot}", rotation=rot)
    f = _f("rotated finding", quote="q", rect=(80.0, 90.0, 200.0, 120.0))
    assign_qc_ids([f])
    res = annotate_pdf(src, [f], tmp_path / f"r{rot}.pdf", include_unverified=True)
    assert res.coverage_status == "COMPLETE", f"rot={rot}"
    assert res.annots_written >= 1
    assert [r.status for r in res.receipts] == ["WRITTEN"]


# --------------------------------------------------------------------------- #
# 12. Duplicate-basename sources stay isolated in receipts (Phase 18 + 21)
# --------------------------------------------------------------------------- #


def test_duplicate_basename_receipts_stay_isolated(tmp_path):
    from drawing_analyzer.source_registry import assign_source_ids

    a = _pdf(tmp_path / "a", "M-101.pdf")
    b = _pdf(tmp_path / "b", "M-101.pdf")
    ids = assign_source_ids([a, b])
    findings = [
        _f("A-only", quote="AAA", source="M-101.pdf", source_id=ids[str(a)]),
        _f("B-only", quote="BBB", source="M-101.pdf", source_id=ids[str(b)]),
    ]
    assign_qc_ids(findings)
    res = write_reviewed_pdfs(findings, [a, b], tmp_path / "out")

    assert res.coverage_status == "COMPLETE"
    # Every receipt's source_id matches the PDF it was written to.
    by_pdf: dict[str, set[str]] = {}
    for r in res.receipts:
        by_pdf.setdefault(r.output_pdf, set()).add(r.placement.source_id)
    assert by_pdf == {
        f"M-101__{ids[str(a)]}_reviewed.pdf": {ids[str(a)]},
        f"M-101__{ids[str(b)]}_reviewed.pdf": {ids[str(b)]},
    }


# --------------------------------------------------------------------------- #
# 13. A prior run's stamp cannot satisfy this run's placement
# --------------------------------------------------------------------------- #


def test_old_run_stamp_cannot_satisfy_new_placement(tmp_path):
    src = _pdf(tmp_path)
    # Seed the source with an OLD analyzer run's stamped cloud (same author, same
    # QC id it would reuse) at the very spot the new finding would land.
    doc = pymupdf.open(str(src))
    old = doc[0].add_rect_annot(pymupdf.Rect(72, 66, 200, 84))
    old.set_info(title=annotate.DEFAULT_AUTHOR)
    old.update()
    doc.xref_set_key(old.xref, _PLACEMENT_KEY, "(run-OLD#deadbeef#primary#00000|cloud|0)")
    doc.save(str(src), incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
    doc.close()

    # A new finding on a page that does NOT exist → its cloud can't be drawn. The
    # old stamped object must not be mistaken for the new run's mark.
    f = _f("new finding", quote="q", page=9)
    assign_qc_ids([f])
    res = annotate_pdf(src, [f], tmp_path / "r.pdf", include_unverified=True,
                       artifact_run_id="run-NEW")
    assert res.coverage_status == "INCOMPLETE"
    assert [r.status for r in res.receipts] == ["FAILED"]
    assert "missing mandatory component" in res.receipts[0].error


# --------------------------------------------------------------------------- #
# 14. Reconciliation detects missing / unexpected / duplicate marks
# --------------------------------------------------------------------------- #


def _stamp(doc, xref, pid, comp, page):
    doc.xref_set_key(xref, _PLACEMENT_KEY, f"({pid}|{comp}|{page})")


def test_reconcile_detects_missing_unexpected_and_duplicate(tmp_path):
    run_id = "run-recon"
    out = tmp_path / "crafted.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)

    # placement P1: draw ONE cloud (WRITTEN).
    a1 = page.add_rect_annot(pymupdf.Rect(10, 10, 60, 40)); a1.update()
    _stamp(doc, a1.xref, f"{run_id}#f1#primary#00000", "cloud", 0)
    # placement P2 (duplicate): draw TWO clouds with the SAME placement id.
    a2 = page.add_rect_annot(pymupdf.Rect(70, 10, 120, 40)); a2.update()
    a3 = page.add_rect_annot(pymupdf.Rect(130, 10, 180, 40)); a3.update()
    _stamp(doc, a2.xref, f"{run_id}#f2#primary#00001", "cloud", 0)
    _stamp(doc, a3.xref, f"{run_id}#f2#primary#00001", "cloud", 0)
    # an UNEXPECTED mark stamped with this run but not in the plan.
    a4 = page.add_rect_annot(pymupdf.Rect(10, 70, 60, 100)); a4.update()
    _stamp(doc, a4.xref, f"{run_id}#f9#primary#00099", "cloud", 0)
    doc.save(str(out))
    doc.close()

    def _pl(fid, ordinal):
        return MarkupPlacement(
            run_id=run_id, placement_id=f"{run_id}#{fid}#primary#{ordinal:05d}",
            finding_id=fid, qc_id="", scope="SOURCE", source_id="SRC-0001",
            page_index=0, leg_id="primary", expected="CLOUD",
            required_components=["cloud"],
        )

    placements = [
        _pl("f1", 0),   # P1: one cloud → WRITTEN
        _pl("f2", 1),   # P2: two clouds → duplicate → FAILED
        _pl("f3", 2),   # P3: no cloud in the file → missing → FAILED
    ]
    receipts = _reconcile_pdf(out, placements, run_id)
    by_id = {r.placement.placement_id: r for r in receipts}

    assert by_id[f"{run_id}#f1#primary#00000"].status == "WRITTEN"
    assert by_id[f"{run_id}#f2#primary#00001"].status == "FAILED"
    assert "duplicate" in by_id[f"{run_id}#f2#primary#00001"].error
    assert by_id[f"{run_id}#f3#primary#00002"].status == "FAILED"
    assert "missing" in by_id[f"{run_id}#f3#primary#00002"].error
    # The unexpected mark surfaces as its own FAILED receipt.
    unexpected = [r for r in receipts if "unexpected" in r.error]
    assert len(unexpected) == 1
    assert unexpected[0].placement.placement_id == f"{run_id}#f9#primary#00099"


def test_same_page_index_rows_are_matched_to_their_own_link(tmp_path):
    # Codex review (annotate.py index reconciliation): two index-only rows that
    # target the SAME drawing page must each be matched to their OWN row's GOTO
    # link — not to any link that merely shares the target. Here only row A's link
    # is present; row B (same target) must FAIL even though a link to that page
    # exists on the page.
    run_id = "run-idx"
    out = tmp_path / "idx.pdf"
    doc = pymupdf.open()
    doc.new_page(width=_INDEX_PW(), height=_INDEX_PH())          # page 0: the index
    doc.new_page(width=300, height=300)                          # page 1: the drawing
    index = doc[0]   # re-fetch after the page tree changed (PyMuPDF unbinds pages)

    pid_a = f"{run_id}#fa#primary#00000"
    pid_b = f"{run_id}#fb#primary#00001"
    # Row A at top 100, row B at top 120 — both GOTO page 1, but only A gets a link.
    index.insert_link({
        "kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(34, 100, 200, 112),
        "page": 1, "to": pymupdf.Point(5, 5), "zoom": 0,
    })
    doc.xref_set_key(index.xref, "DAIndexPage", f"({run_id})")
    doc.xref_set_key(index.xref, "DAIndexRows", f"({pid_a}@1@100;{pid_b}@1@120)")
    doc.save(str(out))
    doc.close()

    def _pl(pid, expected):
        return MarkupPlacement(
            run_id=run_id, placement_id=pid, finding_id=pid.split("#")[1], qc_id="",
            scope="SOURCE", source_id="SRC-0001", page_index=0, leg_id="primary",
            expected=expected, required_components=["index_row"],
        )

    receipts = _reconcile_pdf(out, [_pl(pid_a, "REJECTED_INDEX"), _pl(pid_b, "GATED_INDEX")], run_id)
    by_id = {r.placement.placement_id: r for r in receipts}
    assert by_id[pid_a].status == "INDEXED"       # its own link is present
    assert by_id[pid_b].status == "FAILED"        # no link at row B's position
    assert "own GOTO link" in by_id[pid_b].error


def _INDEX_PW():
    from drawing_analyzer.annotate import _INDEX_PAGE_W
    return _INDEX_PAGE_W


def _INDEX_PH():
    from drawing_analyzer.annotate import _INDEX_PAGE_H
    return _INDEX_PAGE_H


# --------------------------------------------------------------------------- #
# markup_manifest.json — portable, receipt-backed (§13.7)
# --------------------------------------------------------------------------- #


def test_markup_manifest_is_portable_and_receipt_backed(tmp_path):
    import json
    from types import SimpleNamespace

    from drawing_analyzer.export import (
        build_markup_manifest,
        has_markup_manifest,
        write_qc_outputs,
    )

    src = _pdf(tmp_path)
    findings = [_f("cloud", quote="q1"), _f("reject", quote="q2", status="REJECTED")]
    assign_qc_ids(findings)
    run = write_reviewed_pdfs(findings, [src], tmp_path / "qc", include_unverified=True)
    assert run.coverage_status == "COMPLETE"

    ctx = SimpleNamespace(
        findings=findings, reference_findings=[],
        reviewed_pdf_paths=run.reviewed_pdfs, sheet_geometries=[],
        qc_work_dir=tmp_path / "qc", markup_run=run,
        coverage_status=run.coverage_status, ledger_tally=run.tally,
        mutated_sources=[],
    )
    assert has_markup_manifest(ctx)

    folder = tmp_path / "out"
    folder.mkdir()
    written = write_qc_outputs(ctx, folder)
    assert "markup_manifest.json" in written

    manifest = json.loads((folder / "markup_manifest.json").read_text())
    assert manifest["coverage_status"] == "COMPLETE"
    assert len(manifest["placements"]) == 2 and len(manifest["receipts"]) == 2
    # Every receipt names a placement and a terminal status.
    assert {r["status"] for r in manifest["receipts"]} == {"WRITTEN", "INDEXED"}
    # Output hashes describe the concrete reviewed PDF on disk.
    assert manifest["outputs"] and all("sha256" in o for o in manifest["outputs"])

    # Portable: no absolute path, no API key literal.
    text = (folder / "markup_manifest.json").read_text()
    assert str(tmp_path) not in text
    assert "sk-ant" not in text


def test_manifest_records_incomplete_coverage(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from drawing_analyzer.export import build_markup_manifest

    src = _pdf(tmp_path, pages=1)
    findings = [_f("on page 9", quote="q", page=9)]           # forces a FAILED receipt
    run = write_reviewed_pdfs(findings, [src], tmp_path / "qc", include_unverified=True)
    assert run.coverage_status == "INCOMPLETE"
    ctx = SimpleNamespace(
        markup_run=run, coverage_status=run.coverage_status,
        ledger_tally=run.tally, mutated_sources=[], reviewed_pdf_paths=run.reviewed_pdfs,
    )
    manifest = build_markup_manifest(ctx, folder=None)
    assert manifest["coverage_status"] == "INCOMPLETE"
    assert any(r["status"] == "FAILED" for r in manifest["receipts"])


# --------------------------------------------------------------------------- #
# Report coverage banner (§13.6)
# --------------------------------------------------------------------------- #


def test_report_coverage_banner():
    from types import SimpleNamespace

    from drawing_analyzer.html_report import _coverage_banner_html

    complete = _coverage_banner_html(SimpleNamespace(
        coverage_status="COMPLETE",
        ledger_tally_line="Ledger 3: 2 clouded, 1 margin, 0 rejected (indexed); coverage COMPLETE",
        mutated_sources=[],
    ))
    assert 'data-coverage="COMPLETE"' in complete
    assert "COMPLETE" in complete

    incomplete = _coverage_banner_html(SimpleNamespace(
        coverage_status="INCOMPLETE", ledger_tally_line="", mutated_sources=["a.pdf"],
    ))
    assert 'data-coverage="INCOMPLETE"' in incomplete
    assert "INCOMPLETE" in incomplete
    assert "markup_manifest.json" in incomplete
    assert "1 source(s) changed" in incomplete

    # No banner when markups were not requested.
    assert _coverage_banner_html(SimpleNamespace(coverage_status="NOT_REQUESTED")) == ""
