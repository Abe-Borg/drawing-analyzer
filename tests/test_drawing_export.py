"""Tests for ``drawing_export`` — serializing a drawing digest to a folder.

Fully hermetic: no tkinter, no PyMuPDF, no network. The context and its sheets
are duck-typed fakes (``tests.fixtures.fake_context``) exposing only the
attributes ``drawing_export`` reads.
"""
from __future__ import annotations

from datetime import datetime

from drawing_analyzer import export as dx
from tests.fixtures.fake_context import FakeContext as _Ctx
from tests.fixtures.fake_context import FakeRef as _Ref
from tests.fixtures.fake_context import FakeSheet as _Sheet

SRC = "Weld_County_Mechanical_Permit_Set.pdf"
NOW = datetime(2026, 6, 7, 7, 2, 0)


def _make_ctx() -> _Ctx:
    sheets = [
        _Sheet(_Ref(SRC, 0, 3), text="VAV-3 serves Rm 120", input_tokens=100, output_tokens=50),
        _Sheet(_Ref(SRC, 1, 3), text="WH-1 schedule transcribed", cached=True),
        _Sheet(_Ref(SRC, 2, 3), error="api_error: Internal Server Error"),
    ]
    return _Ctx(
        sheets=sheets,
        synthesis_text="# Overview\n\nSet-level reconciliation across sheets.",
        combined_text="# Drawing Set Context Digest\n\n## Sheet 1/3\nVAV-3 serves Rm 120",
        file_count=1,
        errors=["Weld_County_Mechanical_Permit_Set.pdf (page 3/3): api_error: Internal Server Error"],
        total_input_tokens=100,
        total_output_tokens=50,
    )


# --------------------------------------------------------------------------- #
# export_folder_name
# --------------------------------------------------------------------------- #


def test_export_folder_name_uses_first_stem_and_timestamp():
    assert (
        dx.export_folder_name([SRC], now=NOW)
        == "Weld_County_Mechanical_Permit_Set_drawings_2026-06-07_070200"
    )


def test_export_folder_name_no_sources_falls_back():
    assert dx.export_folder_name([], now=NOW) == "drawings_2026-06-07_070200"


def test_export_folder_name_is_filesystem_safe():
    name = dx.export_folder_name(["M&P / set: rev#2.pdf"], now=NOW)
    assert "/" not in name and ":" not in name and "&" not in name and "#" not in name


# --------------------------------------------------------------------------- #
# build_export_documents
# --------------------------------------------------------------------------- #


def test_build_export_documents_order_and_filenames():
    docs = dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW)
    names = [n for n, _ in docs]

    # The browser report leads (it is where an operator should start), then the
    # Markdown index / synthesis / per-sheet files / combined document.
    assert names[0] == "report.html"
    assert names[1] == "00_index.md"
    assert names[2] == "00_synthesis.md"
    assert names[-1] == "combined.md"
    middle = names[3:-1]
    assert len(middle) == 3
    # Per-sheet files are in page order with a global NN prefix and p<page> suffix.
    assert middle[0].startswith("01_") and middle[0].endswith("_p1.md")
    assert middle[1].startswith("02_") and middle[1].endswith("_p2.md")
    assert middle[2].startswith("03_") and middle[2].endswith("_p3.md")
    # Filenames are unique.
    assert len(set(names)) == len(names)


def test_build_export_documents_per_sheet_bodies():
    docs = dict(dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW))

    ok = docs["01_Weld_County_Mechanical_Permit_Set_p1.md"]
    assert "VAV-3 serves Rm 120" in ok
    assert "**Status:** OK" in ok
    assert "100 in / 50 out" in ok

    cached = docs["02_Weld_County_Mechanical_Permit_Set_p2.md"]
    assert "served from cache" in cached
    assert "WH-1 schedule transcribed" in cached

    failed = docs["03_Weld_County_Mechanical_Permit_Set_p3.md"]
    assert "FAILED" in failed
    assert "api_error: Internal Server Error" in failed  # error becomes the body


def test_build_export_documents_synthesis_and_combined():
    docs = dict(dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW))
    assert "Set-level reconciliation across sheets." in docs["00_synthesis.md"]
    assert "Drawing Set Context Digest" in docs["combined.md"]


def test_build_export_documents_synthesis_fallback_when_absent():
    ctx = _make_ctx()
    ctx.synthesis_text = ""
    docs = dict(dx.build_export_documents(ctx, source_names=[SRC], now=NOW))
    assert "No cross-sheet synthesis was produced" in docs["00_synthesis.md"]


def test_index_lists_counts_errors_and_files():
    docs = dict(dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW))
    index = docs["00_index.md"]
    assert SRC in index
    assert "2/3" in index  # ok/total (1 cached counts as ok)
    assert "## Errors" in index
    assert "api_error: Internal Server Error" in index
    assert "combined.md" in index and "00_synthesis.md" in index
    assert "report.html" in index  # the index points operators at the browser view


def test_build_export_documents_forwards_api_key_to_html_report_only():
    key = "sk-ant-test-456"
    docs = dict(
        dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW, api_key=key)
    )
    # The HTML report gains the Q&A assistant — but by default the key is NOT
    # written into the file (Phase 8: it prompts at runtime, sessionStorage).
    assert 'id="da-chat-config"' in docs["report.html"]
    assert key not in docs["report.html"]
    # The key never leaks into any deliverable at all in the default path.
    for content in docs.values():
        assert key not in content
    # Opt in with embed_api_key=True to bake the key into the report only.
    embedded = dict(dx.build_export_documents(
        _make_ctx(), source_names=[SRC], now=NOW, api_key=key, embed_api_key=True
    ))
    assert key in embedded["report.html"]
    for name, content in embedded.items():
        if name != "report.html":
            assert key not in content
    # Default (no key) still ships the assistant (DA-026: it prompts on first
    # use), but writes no key material into any deliverable.
    plain = dict(dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW))
    assert 'id="da-chat-config"' in plain["report.html"]
    assert '"apiKey"' not in plain["report.html"]
    # include_chat=False is the explicit opt-out for an assistant-free report.
    nochat = dict(dx.build_export_documents(
        _make_ctx(), source_names=[SRC], now=NOW, include_chat=False
    ))
    assert "da-chat-config" not in nochat["report.html"]


# --------------------------------------------------------------------------- #
# write_drawing_export
# --------------------------------------------------------------------------- #


def test_write_drawing_export_creates_folder_and_all_files(tmp_path):
    folder = dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)

    assert folder.parent == tmp_path
    assert folder.name == "Weld_County_Mechanical_Permit_Set_drawings_2026-06-07_070200"
    written = sorted(p.name for p in folder.iterdir())
    assert written == sorted(
        [
            "report.html",
            "00_index.md",
            "00_synthesis.md",
            "01_Weld_County_Mechanical_Permit_Set_p1.md",
            "02_Weld_County_Mechanical_Permit_Set_p2.md",
            "03_Weld_County_Mechanical_Permit_Set_p3.md",
            "combined.md",
        ]
    )
    # A failed sheet still produced a real file carrying its error.
    assert "api_error" in (folder / "03_Weld_County_Mechanical_Permit_Set_p3.md").read_text(
        encoding="utf-8"
    )


def test_write_drawing_export_unique_on_collision(tmp_path):
    first = dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)
    second = dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)
    assert first != second
    assert second.name.endswith("_2")
    assert first.exists() and second.exists()


# --------------------------------------------------------------------------- #
# per-run focus deliverable (00_focus.md)
# --------------------------------------------------------------------------- #

FOCUS = "the rooms, and what types of plumbing fixtures each has"


def test_no_focus_writes_no_focus_file():
    docs = dict(dx.build_export_documents(_make_ctx(), source_names=[SRC], now=NOW))
    assert "00_focus.md" not in docs
    assert "Per-run focus" not in docs["00_index.md"]


def test_focus_adds_its_own_document_and_index_entries():
    ctx = _make_ctx()
    ctx.focus = FOCUS
    ctx.focus_report_text = "Room 101: WC-1, LAV-2 (per P-101/P-501)."
    docs = dx.build_export_documents(ctx, source_names=[SRC], now=NOW)
    names = [n for n, _ in docs]

    # The focus report slots in after the synthesis, before the per-sheet files,
    # and the rest of the export is unchanged.
    assert names[2] == "00_synthesis.md" and names[3] == "00_focus.md"
    body = dict(docs)["00_focus.md"]
    assert FOCUS in body                                  # self-describing
    assert "Room 101: WC-1, LAV-2" in body                # the report itself
    index = dict(docs)["00_index.md"]
    assert f"**Per-run focus:** {FOCUS}" in index
    assert "`00_focus.md`" in index


def test_focus_with_failed_report_still_writes_the_file():
    ctx = _make_ctx()
    ctx.focus = FOCUS
    ctx.focus_report_text = ""  # the report pass failed
    docs = dict(dx.build_export_documents(ctx, source_names=[SRC], now=NOW))
    body = docs["00_focus.md"]
    assert FOCUS in body
    assert "No focus report was produced" in body


# --------------------------------------------------------------------------- #
# Findings CSV (Phase 6)
# --------------------------------------------------------------------------- #

from drawing_analyzer.models import Anchor, Finding, Verification  # noqa: E402


def _finding(**over):
    base = dict(
        sheet_id="M-101", source_name="M-101.pdf", page_index=2, category="code",
        severity="high", text="Missing, clearance", source_quote='VAV-3 "typ"',
        tile=[2, 3], refs=["CMC 310", "NFPA 90A"],
        anchor=Anchor(status="EXACT", rect_pdf=[10.25, 20.0, 88.5, 33.0], method="exact"),
    )
    base.update(over)
    f = Finding(**base)
    f.verification = Verification(status="VERIFIED", note="ok", evidence_png="evidence/x.png")
    return f


def test_findings_csv_header_and_row_flattening():
    csv = dx.build_findings_csv([_finding()])
    lines = csv.split("\r\n")
    assert lines[0] == ",".join(dx.FINDINGS_CSV_HEADER)
    row = lines[1]
    assert '"Missing, clearance"' in row          # comma-bearing field quoted
    assert '"VAV-3 ""typ"""' in row               # embedded quotes doubled
    assert '"2,3"' in row                          # tile as row,col
    assert "CMC 310; NFPA 90A" in row              # refs joined
    assert "10.2, 20.0, 88.5, 33.0" in row         # rect flattened + rounded
    # qc_id first (empty until assigned), then the content id
    assert row.startswith("," + _finding().id + ",")
    # page is 1-based (page_index 2 -> page 3)
    assert ",3,code,high," in row
    assert "VERIFIED" in row and "evidence/x.png" in row


def test_findings_csv_carries_qc_id_and_citation():
    from drawing_analyzer.models import Citation, assign_qc_ids

    f = _finding()
    f.citation = Citation(status="CHECKED_MISMATCH", note="renumbered in 2019")
    assign_qc_ids([f])
    row = dx.build_findings_csv([f]).split("\r\n")[1]
    assert row.startswith("QC-001,")
    assert "CHECKED_MISMATCH" in row and "renumbered in 2019" in row


def test_findings_csv_is_crlf_terminated():
    csv = dx.build_findings_csv([_finding(), _finding(text="another")])
    assert csv.count("\r\n") == 3                   # header + 2 rows
    assert "\n" not in csv.replace("\r\n", "")      # no bare LFs


def test_findings_csv_empty_is_just_the_header():
    csv = dx.build_findings_csv([])
    assert csv == ",".join(dx.FINDINGS_CSV_HEADER) + "\r\n"


def test_write_findings_csv_has_bom_and_crlf(tmp_path):
    path = dx.write_findings_csv([_finding()], tmp_path / "findings.csv")
    raw = path.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"               # UTF-8 BOM for Excel
    assert b"\r\n" in raw
    # decodes cleanly with the BOM stripped
    text = raw.decode("utf-8-sig")
    assert text.startswith("qc_id,id,sheet_id,source_name,page,")


def test_findings_csv_tolerates_sparse_finding():
    # A finding with no tile / refs / evidence still produces a clean row.
    f = Finding(sheet_id="F", source_name="s.pdf", page_index=0, category="conflict",
                severity="low", text="x")
    csv = dx.build_findings_csv([f])
    row = csv.split("\r\n")[1]
    assert row.startswith("," + f.id + ",F,s.pdf,1,conflict,low,x,")


# --------------------------------------------------------------------------- #
# QC review inventory (Phase 7)
# --------------------------------------------------------------------------- #

from types import SimpleNamespace  # noqa: E402


def _geom(source="M-101.pdf", page=0, text="VAV-3 SERVES ROOM 120"):
    return SimpleNamespace(ref=_Ref(source, page, 1), sheet_text=text)


def _qc_ctx(tmp_path, *, with_reviewed=True, with_evidence=True):
    findings = [_finding(), _finding(text="second", severity="low")]
    reference = [
        Finding(sheet_id="M-101", source_name="M-101.pdf", page_index=0,
                category="reference", severity="medium", text="References M-999; not present"),
    ]
    reviewed = []
    if with_reviewed:
        rp = tmp_path / "qc" / "M-101_reviewed.pdf"
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_bytes(b"%PDF-1.7 fake")
        reviewed = [rp]
    if with_evidence:
        ev = tmp_path / "qc" / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / f"{findings[0].id}.png").write_bytes(b"\x89PNG")
    return SimpleNamespace(
        findings=findings, reference_findings=reference,
        reviewed_pdf_paths=reviewed, sheet_geometries=[_geom(), _geom(page=1)],
        qc_work_dir=tmp_path / "qc",
    )


def test_has_qc_outputs():
    assert dx.has_qc_outputs(_make_ctx()) is False   # a plain digest ctx
    assert dx.has_qc_outputs(SimpleNamespace(findings=[_finding()])) is True


def test_write_qc_outputs_writes_full_inventory(tmp_path):
    ctx = _qc_ctx(tmp_path)
    folder = tmp_path / "out"
    folder.mkdir()
    written = dx.write_qc_outputs(ctx, folder)

    assert (folder / "findings.json").exists()
    assert (folder / "findings.csv").read_bytes()[:3] == b"\xef\xbb\xbf"
    # findings.json carries model + reference findings.
    import json
    data = json.loads((folder / "findings.json").read_text())
    assert len(data["findings"]) == 3
    # sheet_text/, reviewed PDF, and evidence all landed.
    assert (folder / "sheet_text" / "M_101_p1.txt").read_text() == "VAV-3 SERVES ROOM 120"
    assert (folder / "sheet_text" / "M_101_p2.txt").exists()
    assert (folder / "M-101_reviewed.pdf").read_bytes() == b"%PDF-1.7 fake"
    assert (folder / "evidence" / f"{ctx.findings[0].id}.png").exists()
    assert "findings.csv" in written and "sheet_text/" in written


def test_write_qc_outputs_noop_without_qc(tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    assert dx.write_qc_outputs(_make_ctx(), folder) == []
    assert not (folder / "findings.csv").exists()


def test_write_qc_outputs_tolerates_missing_reviewed_pdf(tmp_path):
    ctx = _qc_ctx(tmp_path)
    ctx.reviewed_pdf_paths = [tmp_path / "qc" / "vanished.pdf"]   # never written
    folder = tmp_path / "out"
    folder.mkdir()
    dx.write_qc_outputs(ctx, folder)   # must not raise
    assert not (folder / "vanished.pdf").exists()
    assert (folder / "findings.json").exists()   # the rest still written


def test_write_qc_outputs_writes_empty_findings_when_qc_ran(tmp_path):
    # A clean QC run (geometry captured, but zero findings) still advertises
    # findings.json/csv in the index, so both must exist on disk — empty.
    ctx = SimpleNamespace(
        findings=[], reference_findings=[],
        reviewed_pdf_paths=[], sheet_geometries=[_geom()], qc_work_dir=None,
    )
    assert dx.has_qc_outputs(ctx) is True
    folder = tmp_path / "out"
    folder.mkdir()
    written = dx.write_qc_outputs(ctx, folder)

    assert (folder / "findings.json").exists()
    import json
    assert json.loads((folder / "findings.json").read_text()) == {"findings": []}
    # Header-only CSV, BOM intact, still a valid file for the index to point at.
    csv_bytes = (folder / "findings.csv").read_bytes()
    assert csv_bytes[:3] == b"\xef\xbb\xbf"
    assert "findings.json" in written and "findings.csv" in written
