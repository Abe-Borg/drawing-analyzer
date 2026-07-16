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
    # Phase 26A (§18.4/§18.5, DA-024): EVERY export — QC or not — carries the
    # per-run ``run.log`` and the machine-readable ``run_manifest.json``.
    assert written == sorted(
        [
            "report.html",
            "00_index.md",
            "00_synthesis.md",
            "01_Weld_County_Mechanical_Permit_Set_p1.md",
            "02_Weld_County_Mechanical_Permit_Set_p2.md",
            "03_Weld_County_Mechanical_Permit_Set_p3.md",
            "combined.md",
            "run.log",
            "run_manifest.json",
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
    csv = dx.build_findings_csv(
        [_finding(recommended_action="Verify the clearance on site.")]
    )
    lines = csv.split("\r\n")
    assert lines[0] == ",".join(dx.FINDINGS_CSV_HEADER)
    row = lines[1]
    assert '"Missing, clearance"' in row          # comma-bearing field quoted
    assert '"VAV-3 ""typ"""' in row               # embedded quotes doubled
    assert '"2,3"' in row                          # internal zero-based tile column
    assert ",r3c4," in row                         # human tile_label column (§17.1)
    # recommended_action is the appended last column
    assert row.rstrip().endswith("Verify the clearance on site.")
    assert "CMC 310; NFPA 90A" in row              # refs joined
    assert "10.2, 20.0, 88.5, 33.0" in row         # rect flattened + rounded
    # qc_id first (empty until assigned), then the content id
    assert row.startswith("," + _finding().id + ",")
    # page is 1-based (page_index 2 -> page 3)
    assert ",3,code,high," in row
    assert "VERIFIED" in row and "evidence/x.png" in row


def test_findings_csv_action_column_is_formula_guarded():
    # DA-031: the action is model text — a leading formula sigil is neutralized.
    csv = dx.build_findings_csv([_finding(recommended_action="=HYPERLINK(evil)")])
    row = csv.split("\r\n")[1]
    assert "'=HYPERLINK(evil)" in row


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
    # source_id (DA-001) sits between sheet_id and the display source_name.
    assert text.startswith("qc_id,id,sheet_id,source_id,source_name,page,")


def test_findings_csv_tolerates_sparse_finding():
    # A finding with no tile / refs / evidence still produces a clean row.
    f = Finding(sheet_id="F", source_name="s.pdf", page_index=0, category="conflict",
                severity="low", text="x")
    csv = dx.build_findings_csv([f])
    row = csv.split("\r\n")[1]
    # Empty source_id (no host id on a hand-built finding) → an empty cell
    # between sheet_id and source_name.
    assert row.startswith("," + f.id + ",F,,s.pdf,1,conflict,low,x,")


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


# --------------------------------------------------------------------------- #
# run.log + run_manifest.json (Phase 26A, §18.2/§18.4, DA-024)
# --------------------------------------------------------------------------- #

import hashlib  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from drawing_analyzer.run_journal import RunJournal, collect_environment  # noqa: E402

# Assembled from fragments so no live-looking key shape exists in the source.
_ANT = "sk-" + "ant-"
_FAKE_KEY = _ANT + "api03-abcdef1234567890"


def _fake_inventory():
    return SimpleNamespace(
        documents=[
            SimpleNamespace(
                source_id="SRC-0001", display_name="M-101.pdf", input_order=1,
                status="ACCEPTED", page_count=3, byte_size=1234, error="",
                duplicate_of="", accepted=True,
            ),
            SimpleNamespace(
                source_id="", display_name="broken.pdf", input_order=0,
                status="UNREADABLE", page_count=0, byte_size=0,
                error="not a PDF", duplicate_of="", accepted=False,
            ),
        ]
    )


def test_write_drawing_export_always_writes_run_log_and_manifest(tmp_path):
    # §18.1/§18.5: EVERY export — here a plain standard run with no QC and no
    # journal attached — still gets run.log + run_manifest.json, and the index
    # advertises them.
    folder = dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)

    log = (folder / "run.log").read_text(encoding="utf-8")
    assert "Drawing Analyzer — run log" in log
    assert "no run journal was recorded" in log      # duck-typed ctx: honest, not invented
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == dx.RUN_MANIFEST_SCHEMA_VERSION
    assert manifest["kind"] == "drawing_analyzer_run_manifest"
    index = (folder / "00_index.md").read_text(encoding="utf-8")
    assert "`run.log`" in index and "`run_manifest.json`" in index


def test_run_log_is_crlf_utf8(tmp_path):
    # §19.6: run.log opens cleanly in Windows Notepad — UTF-8, CRLF only.
    folder = dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)
    raw = (folder / "run.log").read_bytes()
    assert raw.count(b"\r\n") > 10
    assert raw.replace(b"\r\n", b"").count(b"\n") == 0
    raw.decode("utf-8")                                  # must be valid UTF-8


def test_run_manifest_hashes_every_artifact_except_itself(tmp_path):
    # §18.4 non-circular finalization: the manifest hashes every artifact —
    # run.log and markup_manifest.json included — and excludes only itself.
    ctx = _qc_ctx(tmp_path)
    ctx.sheets = _make_ctx().sheets
    ctx.combined_text = "digest"
    folder = dx.write_drawing_export(ctx, tmp_path, source_names=["M-101.pdf"], now=NOW)

    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    listed = {a["path"] for a in manifest["artifacts"]}
    actual = {
        p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()
    } - {"run_manifest.json"}
    assert listed == actual
    assert "run.log" in listed
    assert any(p.startswith("evidence/") for p in listed)      # nested tree hashed too
    for a in manifest["artifacts"]:
        digest = hashlib.sha256((folder / a["path"]).read_bytes()).hexdigest()
        assert digest == a["sha256"], a["path"]
        assert a["bytes"] == (folder / a["path"]).stat().st_size


def test_run_manifest_summarizes_qc_run(tmp_path):
    # The §18.4 machine-readable counterpart: status, sources (no paths, no
    # content SHA), stage results, receipts-derived coverage, prose accounting.
    ctx = _qc_ctx(tmp_path)
    ctx.sheets = _make_ctx().sheets
    ctx.combined_text = "digest"
    ctx.qc_status = "PARTIAL"
    ctx.coverage_status = "COMPLETE"
    ctx.input_inventory = _fake_inventory()
    ctx.prose_accounting = {"items": 5, "matched": 3, "degraded": 2, "missing": 0}
    ctx.stage_results = [
        SimpleNamespace(stage="auditors", expected=True, status="COMPLETE"),
    ]
    ctx.ledger_tally = {"cloud": 2, "margin": 1}
    ctx.mutated_sources = []
    ctx.markup_run = SimpleNamespace(
        placements=[1, 2, 3],
        receipts=[
            SimpleNamespace(status="WRITTEN"),
            SimpleNamespace(status="WRITTEN"),
            SimpleNamespace(status="INDEXED"),
        ],
    )
    folder = dx.write_drawing_export(ctx, tmp_path, source_names=["M-101.pdf"], now=NOW)
    m = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))

    assert m["status"]["qc_status"] == "PARTIAL"
    assert m["findings"] == {"model": 2, "deterministic": 1, "total": 3}
    assert m["prose_accounting"]["items"] == 5
    assert m["markup_coverage"]["placements_expected"] == 3
    assert m["markup_coverage"]["receipts"] == {"WRITTEN": 2, "INDEXED": 1, "FAILED": 0}
    assert m["markup_coverage"]["tally"] == {"cloud": 2, "margin": 1}
    assert m["stages"] == [{"stage": "auditors", "expected": True, "status": "COMPLETE"}]
    src = {s["source_id"]: s for s in m["sources"]}
    assert src["SRC-0001"]["page_count"] == 3
    assert src[""]["status"] == "UNREADABLE"
    # §6.1/§18.4 privacy: no absolute path, no content hash for sources.
    dumped = json.dumps(m["sources"])
    assert "pdf_path" not in dumped and "content_sha256" not in dumped


def test_run_log_and_manifest_leak_no_secret_or_absolute_path(tmp_path):
    # §18.2 forbidden content: keys and absolute paths cannot reach the
    # portable artifacts, even when a run error smuggles both.
    ctx = _make_ctx()
    ctx.errors = [f"digest failed: x-api-key: {_FAKE_KEY} at {tmp_path}/private/M-101.pdf"]
    journal = RunJournal(run_id="RUN-leaktest")
    journal.set_environment(collect_environment(model="claude-opus-4-8"))
    journal.emit("API_ERROR", stage="digest", detail=f"401 {_FAKE_KEY}")
    journal.finish("NOT_REQUESTED")
    ctx.run_journal = journal

    folder = dx.write_drawing_export(ctx, tmp_path, source_names=[SRC], now=NOW)
    log = (folder / "run.log").read_text(encoding="utf-8")
    manifest_text = (folder / "run_manifest.json").read_text(encoding="utf-8")
    for text in (log, manifest_text):
        assert _FAKE_KEY not in text
        assert str(tmp_path) not in text
    assert "sk-ant-[REDACTED]" in log
    assert "RUN-leaktest" in log and "RUN-leaktest" in manifest_text


def test_run_manifest_usage_block_is_sanitized_defensively(tmp_path):
    # Even if a future producer embeds a path in a usage instance or custom id,
    # the manifest scrubs it at the boundary (§18.3 defense in depth).
    ctx = _make_ctx()
    ctx.run_usage = SimpleNamespace(
        to_dict=lambda: {
            "total_input_tokens": 10,
            "records": [{"stage_instance": "digest:/home/user/private/M-101.pdf:p0"}],
        }
    )
    manifest = dx.build_run_manifest(ctx)
    assert "/home/user/private" not in json.dumps(manifest)
    assert manifest["usage"]["total_input_tokens"] == 10


def test_export_survives_hostile_duck_typed_context(tmp_path):
    # The two advisory artifacts must never sink write_drawing_export after
    # every deliverable is on disk (I-3 spirit): a third-party duck-typed
    # context with a raw-Decimal usage dict and a malformed prose_accounting
    # still exports, and the artifacts degrade honestly instead of vanishing.
    from decimal import Decimal

    ctx = _make_ctx()
    ctx.run_usage = SimpleNamespace(
        to_dict=lambda: {"total_estimated_cost": Decimal("0.10")},
        by_family=lambda: {},
    )
    ctx.prose_accounting = {"items": "three"}
    folder = dx.write_drawing_export(ctx, tmp_path, source_names=[SRC], now=NOW)

    assert (folder / "report.html").exists()
    log = (folder / "run.log").read_text(encoding="utf-8")
    assert "Drawing Analyzer — run log" in log
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    # The stray Decimal was serialized through the sanitize boundary, not fatal.
    assert manifest["usage"]["total_estimated_cost"] == "0.10"


def test_generated_at_matches_journal_timestamp_dialect(tmp_path):
    # One JSON document, one timestamp dialect: generated_at is UTC-Z like the
    # journal's started_at/ended_at (naive local `now` converted, not relabeled).
    ctx = _make_ctx()
    ctx.run_journal = RunJournal(run_id="RUN-tzcheck")
    ctx.run_journal.finish("COMPLETE")
    folder = dx.write_drawing_export(ctx, tmp_path, source_names=[SRC], now=NOW)
    m = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    assert m["generated_at"].endswith("Z")
    assert m["run"]["started_at"].endswith("Z")


# --------------------------------------------------------------------------- #
# CSV formula-injection safety (Phase 26B §18.5.1, DA-031)
# --------------------------------------------------------------------------- #

import csv as _csv  # noqa: E402
import io as _io  # noqa: E402


def _rows(csv_text: str) -> list[dict]:
    return list(_csv.DictReader(_io.StringIO(csv_text)))


def test_csv_neutralizes_formula_sigils_in_untrusted_cells():
    # DA-031: model/drawing-controlled text whose first meaningful character is
    # a formula sigil must not execute when the CSV opens in Excel.
    f = _finding(
        text='=HYPERLINK("http://evil.example/x","click")',
        source_quote="+cmd|' /C calc'!A0",
    )
    f.refs = ["@SUM(A1:A9)"]
    f.verification.note = "\t=1+1"
    row = _rows(dx.build_findings_csv([f]))[0]
    assert row["text"].startswith("'=")
    assert row["source_quote"].startswith("'+")
    assert row["refs"].startswith("'@")
    assert row["verification_note"].startswith("'")
    # findings.json keeps the canonical, un-prefixed values.
    assert f.text.startswith("=HYPERLINK")


def test_csv_guard_sees_through_leading_whitespace_and_controls():
    # Excel trims leading whitespace before interpreting, so "  =2+5" is still
    # a formula; the guard must look at the first meaningful character.
    f = _finding(text="  =2+5", source_quote=" \x00-2+3+cmd")
    row = _rows(dx.build_findings_csv([f]))[0]
    assert row["text"] == "'  =2+5"
    assert row["source_quote"].startswith("'")


def test_csv_preserves_host_numeric_and_enum_cells():
    # §18.5.1: true numeric columns stay numeric text — an anchored rect with a
    # negative coordinate and the 1-based page are NEVER apostrophe-prefixed,
    # and ordinary prose is untouched.
    from drawing_analyzer.models import Anchor

    f = _finding(text="ordinary finding text")
    f.anchor = Anchor(status="EXACT", method="text", rect_pdf=[-12.5, 4.0, 90.0, 22.0])
    row = _rows(dx.build_findings_csv([f]))[0]
    assert row["rect_pdf"].startswith("-12.5")
    assert row["page"] == "3"                      # helper's page_index=2, 1-based
    assert row["text"] == "ordinary finding text"
    assert row["severity"] in ("high", "medium", "low")


# --------------------------------------------------------------------------- #
# Artifact containment + atomic publish (Phase 26B §18.5, DA-033)
# --------------------------------------------------------------------------- #


def test_safe_artifact_name_neutralizes_hostile_components():
    san = dx.safe_artifact_name
    assert san("../../../etc/passwd") == "passwd"
    assert san(r"..\..\evil.pdf") == "evil.pdf"          # POSIX-legal backslash name
    assert san("C:\\Users\\x\\M-101.pdf") == "M-101.pdf"
    assert san("report.pdf:hidden:$DATA") == "report.pdf_hidden_$DATA"  # ADS colon gone
    assert san("trailing. . ") == "trailing"                # Windows drops these
    assert san("CON") == "_CON" and san("lpt1.txt".upper()) == "_LPT1.TXT"
    assert san('a<b>c:"d|e?f*g.pdf') == "a_b_c__d_e_f_g.pdf"
    assert san("..") == "artifact" and san("") == "artifact"
    long = san("x" * 500 + ".pdf")
    assert len(long) <= 120 and long.endswith(".pdf")
    # The dedupe suffix respects the same cap (trims the base, never overruns).
    used: set[str] = set()
    first = san("y" * 500 + ".pdf", used=used)
    second = san("y" * 500 + ".pdf", used=used)
    assert first != second and len(second) <= 120 and second.endswith(".pdf")


def test_safe_artifact_name_dedupes_deterministically():
    used: set[str] = set()
    assert dx.safe_artifact_name("M-101_reviewed.pdf", used=used) == "M-101_reviewed.pdf"
    assert dx.safe_artifact_name("M-101_reviewed.pdf", used=used) == "M-101_reviewed_2.pdf"
    assert dx.safe_artifact_name("M-101_reviewed.pdf", used=used) == "M-101_reviewed_3.pdf"


def test_contained_target_rejects_escapes(tmp_path):
    root = tmp_path / "export"
    root.mkdir()
    assert dx.contained_target(root, "findings.json") == root / "findings.json"
    import pytest as _pytest

    with _pytest.raises(ValueError):
        dx.contained_target(root, "../outside.txt")
    # A symlinked intermediate directory cannot smuggle a write outside root.
    try:
        (root / "link").symlink_to(tmp_path)
    except OSError:
        _pytest.skip("symlink creation not permitted on this platform")
    with _pytest.raises(ValueError):
        dx.contained_target(root, "link/owned.txt")


def test_evidence_copy_skips_symlinks_and_contains_targets(tmp_path):
    # DA-033: a tampered work dir with a symlink pointing outside the export
    # must neither be followed nor break the rest of the copy.
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    ctx = _qc_ctx(tmp_path, with_reviewed=False)
    ev = tmp_path / "qc" / "evidence"
    (ev / "QC-001").mkdir(parents=True, exist_ok=True)
    (ev / "QC-001" / "leg-01.png").write_bytes(b"\x89PNG")
    try:
        (ev / "QC-001" / "stolen.txt").symlink_to(secret)
        (ev / "linkdir").symlink_to(tmp_path)
    except OSError:
        import pytest as _p
        _p.skip("symlink creation not permitted on this platform")

    folder = tmp_path / "out"
    folder.mkdir()
    dx.write_qc_outputs(ctx, folder)
    copied = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert "evidence/QC-001/leg-01.png" in copied
    assert not any("stolen" in p or "secret" in p for p in copied)


import os as _os  # noqa: E402
import pytest as _pytest_mod  # noqa: E402


@_pytest_mod.mark.skipif(
    _os.name == "nt",
    reason="a backslash FILENAME is only constructible on POSIX (on Windows it is a path)",
)
def test_reviewed_pdf_with_hostile_name_lands_flat_and_contained(tmp_path):
    # A POSIX source file legally named with backslashes must not traverse when
    # its reviewed copy is exported (the export may later be opened on Windows).
    ctx = _qc_ctx(tmp_path, with_reviewed=False, with_evidence=False)
    hostile = tmp_path / "qc" / r"..\..\evil_reviewed.pdf"
    hostile.parent.mkdir(parents=True, exist_ok=True)
    hostile.write_bytes(b"%PDF-1.7 hostile")
    ctx.reviewed_pdf_paths = [hostile]
    folder = tmp_path / "out"
    folder.mkdir()
    written = dx.write_qc_outputs(ctx, folder)
    assert "evil_reviewed.pdf" in written
    assert (folder / "evil_reviewed.pdf").read_bytes() == b"%PDF-1.7 hostile"
    assert not (tmp_path / "evil_reviewed.pdf").exists()   # nothing escaped


def test_export_publishes_atomically_and_labels_partials(tmp_path, monkeypatch):
    # §18.5: the final folder name appears only after every required file
    # succeeded; a mid-export failure leaves an explicit *_INCOMPLETE label,
    # never a final-looking folder.
    folder = dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)
    assert folder.name.endswith("_070200")                # published under the final name
    assert not list(tmp_path.glob("*.partial"))

    def _boom(*a, **k):
        raise OSError("disk full (test)")

    monkeypatch.setattr(dx, "write_run_manifest", _boom)
    import pytest as _pytest

    with _pytest.raises(OSError):
        dx.write_drawing_export(_make_ctx(), tmp_path, source_names=[SRC], now=NOW)
    labels = [p.name for p in tmp_path.iterdir() if "_INCOMPLETE" in p.name]
    assert len(labels) == 1                                # explicit partial label
    # The second final name was never published.
    finals = [p.name for p in tmp_path.iterdir() if p.name.endswith("_070200")]
    assert finals == [folder.name]


def test_markup_manifest_aligns_with_deduped_pdf_names(tmp_path):
    # Codex P2 / DA-033 follow-up: when the allocator renames a reviewed-PDF
    # copy, markup_manifest.json must still hash the on-disk file and map it
    # back to the verbatim receipt name — receipts are never rewritten, but the
    # coverage record stays aligned with the folder. Exercised with the
    # portable rename cause (two same-basename sources → deterministic dedupe),
    # which is also the ambiguous case a name-keyed map would get wrong: the
    # FIRST copy keeps its name; only the second maps to the _2 copy.
    ctx = _qc_ctx(tmp_path, with_reviewed=False, with_evidence=False)
    a = tmp_path / "qc" / "site_a" / "M-101_reviewed.pdf"
    b = tmp_path / "qc" / "site_b" / "M-101_reviewed.pdf"
    for pdf, payload in ((a, b"%PDF-1.7 site-a"), (b, b"%PDF-1.7 site-b")):
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(payload)
    ctx.reviewed_pdf_paths = [a, b]
    ctx.markup_run = SimpleNamespace(
        to_dict=lambda: {
            "placements": [],
            "receipts": [
                {"status": "WRITTEN", "output_pdf": "M-101_reviewed.pdf"},
                {"status": "WRITTEN", "output_pdf": "M-101_reviewed.pdf"},
            ],
        },
        placements=[], receipts=[SimpleNamespace(status="WRITTEN")] * 2,
    )
    folder = tmp_path / "out"
    folder.mkdir()
    dx.write_qc_outputs(ctx, folder)

    manifest = json.loads((folder / "markup_manifest.json").read_text(encoding="utf-8"))
    assert manifest["renamed_outputs"] == [
        {"receipt_name": "M-101_reviewed.pdf", "name": "M-101_reviewed_2.pdf"}
    ]
    outputs = {o["name"]: o for o in manifest["outputs"]}
    # BOTH copies hashed under their on-disk names; only the renamed one maps back.
    assert "receipt_name" not in outputs["M-101_reviewed.pdf"]
    assert outputs["M-101_reviewed_2.pdf"]["receipt_name"] == "M-101_reviewed.pdf"
    assert (
        outputs["M-101_reviewed.pdf"]["sha256"]
        != outputs["M-101_reviewed_2.pdf"]["sha256"]
    )
    # Receipts stay verbatim — the writer's reconciliation record is untouched.
    assert all(r["output_pdf"] == "M-101_reviewed.pdf" for r in manifest["receipts"])


# --------------------------------------------------------------------------- #
# HTML↔PDF deep links — reviewed-PDF name allocation + qc_id→link join
# --------------------------------------------------------------------------- #


def _receipt(qc, *, pdf, page, status="WRITTEN", expected="CLOUD", leg="primary"):
    placement = SimpleNamespace(qc_id=qc, leg_id=leg, expected=expected)
    return SimpleNamespace(
        placement=placement, status=status, output_pdf=pdf, output_page_index=page
    )


def test_allocate_reviewed_pdf_names_dedupes_and_skips_missing(tmp_path):
    # Mirrors write_qc_outputs' copy loop: existing files are allocated in order
    # through the DA-033 allocator (same-basename → deterministic _2), and a
    # non-existent path is skipped so the two sites can't drift.
    a = tmp_path / "site_a" / "M-101_reviewed.pdf"
    b = tmp_path / "site_b" / "M-101_reviewed.pdf"
    for p in (a, b):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.7")
    missing = tmp_path / "gone.pdf"
    pairs = dx.allocate_reviewed_pdf_names([a, b, missing])
    assert [name for _p, name in pairs] == ["M-101_reviewed.pdf", "M-101_reviewed_2.pdf"]
    assert [p for p, _n in pairs] == [a, b]     # missing dropped


def test_build_reviewed_pdf_links_joins_receipts_to_names(tmp_path):
    pdf = tmp_path / "M-101_reviewed.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    pairs = dx.allocate_reviewed_pdf_names([pdf])
    ctx = SimpleNamespace(markup_run=SimpleNamespace(receipts=[
        _receipt("QC-001", pdf="M-101_reviewed.pdf", page=4),   # 0-based → page 5
    ]))
    links = dx.build_reviewed_pdf_links(ctx, pairs)
    assert links == {"QC-001": {"pdf": "M-101_reviewed.pdf", "page": 5}}


def test_build_reviewed_pdf_links_skips_unlinkable_receipts():
    pairs = [(Path("M-101_reviewed.pdf"), "M-101_reviewed.pdf")]
    ctx = SimpleNamespace(markup_run=SimpleNamespace(receipts=[
        _receipt("QC-001", pdf="M-101_reviewed.pdf", page=None),        # page-less
        _receipt("QC-002", pdf="M-101_reviewed.pdf", page=-1),          # set-level
        _receipt("QC-003", pdf="M-101_reviewed.pdf", page=2, status="FAILED"),
        _receipt("QC-004", pdf="unknown.pdf", page=2),                  # PDF not exported
        _receipt("", pdf="M-101_reviewed.pdf", page=2),                 # no qc_id
        _receipt("QC-005", pdf="M-101_reviewed.pdf", page=1),           # the one good link
    ]))
    links = dx.build_reviewed_pdf_links(ctx, pairs)
    assert links == {"QC-005": {"pdf": "M-101_reviewed.pdf", "page": 2}}


def test_build_reviewed_pdf_links_prefers_primary_cloud():
    # A qc_id with several receipts resolves to the finding's own on-page cloud,
    # not a cross-sheet leg or a margin/index placement.
    pairs = [(Path("R.pdf"), "R.pdf")]
    ctx = SimpleNamespace(markup_run=SimpleNamespace(receipts=[
        _receipt("QC-001", pdf="R.pdf", page=8, expected="MARGIN", leg="primary"),
        _receipt("QC-001", pdf="R.pdf", page=9, expected="CLOUD", leg="leg-abc"),
        _receipt("QC-001", pdf="R.pdf", page=4, expected="CLOUD", leg="primary"),
    ]))
    links = dx.build_reviewed_pdf_links(ctx, pairs)
    assert links == {"QC-001": {"pdf": "R.pdf", "page": 5}}     # primary cloud, page 4→5


def test_build_reviewed_pdf_links_empty_without_markup_run():
    assert dx.build_reviewed_pdf_links(SimpleNamespace(), []) == {}
    assert dx.build_reviewed_pdf_links(
        SimpleNamespace(markup_run=SimpleNamespace(receipts=[])), []
    ) == {}


def test_build_reviewed_pdf_links_skips_ambiguous_basename():
    # Two sources share the basename M-101_reviewed.pdf → the allocator lands
    # them as `…` and `…_2`, but a receipt's output_pdf carries only the
    # basename, so which copy a finding belongs to is unknowable. Rather than
    # link every such finding to the wrong file, skip them (plain text).
    pairs = [
        (Path("site_a/M-101_reviewed.pdf"), "M-101_reviewed.pdf"),
        (Path("site_b/M-101_reviewed.pdf"), "M-101_reviewed_2.pdf"),
        (Path("D-901_reviewed.pdf"), "D-901_reviewed.pdf"),          # unambiguous
    ]
    ctx = SimpleNamespace(markup_run=SimpleNamespace(receipts=[
        _receipt("QC-001", pdf="M-101_reviewed.pdf", page=1),        # ambiguous → skip
        _receipt("QC-002", pdf="D-901_reviewed.pdf", page=3),        # clean → link
    ]))
    links = dx.build_reviewed_pdf_links(ctx, pairs)
    assert links == {"QC-002": {"pdf": "D-901_reviewed.pdf", "page": 4}}
