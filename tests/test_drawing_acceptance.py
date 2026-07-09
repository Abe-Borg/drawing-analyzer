"""Hermetic acceptance suite — Phase 10 of the QC plan.

Encodes the plan's manual acceptance script (§Phase 10) as a repeatable,
no-network test. The script's steps and their in-code proxies:

1. Fresh run, both checkboxes on → completes, findings > 0, ``report.html``
   findings table renders, every VERIFIED finding has an evidence PNG.
2. Open a ``*_reviewed.pdf`` in Bluebeam Revu / Acrobat / Chromium (a human
   step). Its machine-checkable core — the reason clouds render non-blank in
   those viewers — is that every annotation carries an ``/AP`` appearance
   stream (PyMuPDF's ``annot.update()`` built it). That is asserted here.
3. Seed a stale ``SEE DRAWING …`` reference → the audit flags it with a
   closest-in-set suggestion.
4. Re-run unchanged → level-1 cache hits: zero *digest* API calls and
   byte-identical outputs (the two-level cache's guarantee).
5. Add a scanned (raster / empty-text-layer) page → it renders at the 1992 px
   raster target, the prompt discloses it has no text layer, and the report
   badges it.
6. Windows: the findings CSV opens cleanly in Excel — UTF-8 BOM + CRLF.

What genuinely needs a live key or a human viewer (the visual Revu spot-check,
the real 8-sheet IFC set) is out of a hermetic suite's reach and is left to the
manual script; everything mechanically checkable is pinned here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer import tiling  # noqa: E402
from drawing_analyzer.digest import (  # noqa: E402
    DIGEST_SYSTEM_PROMPT,
    _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER,
)
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from drawing_analyzer.export import write_drawing_export  # noqa: E402
from drawing_analyzer.html_report import build_html_report  # noqa: E402
from drawing_analyzer.models import SheetRef  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.render import render_sheet  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402
from tests.fixtures.fake_anthropic import (  # noqa: E402
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
)

_PAGE_W, _PAGE_H = 792.0, 612.0


# --------------------------------------------------------------------------- #
# Synthetic drawing set (built in-test with PyMuPDF)
# --------------------------------------------------------------------------- #


def _vector_pdf(
    path: Path, *, sheet_id: str, body: list[str], refs: tuple[str, ...] = ()
) -> Path:
    """A one-page vector sheet: body lines, optional references, a title-block id.

    The id sits in the bottom-right, where the reference auditor learns each
    sheet's number from; ``refs`` are cross-reference call-outs to flag.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    y = 90.0
    for line in list(body) + list(refs):
        page.insert_text((72, y), line)
        y += 28
    page.insert_text((_PAGE_W - 150, _PAGE_H - 36), sheet_id)  # title-block id
    doc.save(str(path))
    doc.close()
    return path


def _raster_pdf(path: Path) -> Path:
    """A sheet with graphics but **no text layer** (empty ``get_text('words')``).

    Only shapes are drawn — no ``insert_text`` — so the page has zero words and
    the pipeline treats it as scanned / pasted-raster (``is_raster``).
    """
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.draw_rect(pymupdf.Rect(100, 100, 420, 320), fill=(0.20, 0.42, 0.78))
    page.draw_line(pymupdf.Point(60, 60), pymupdf.Point(720, 540))
    page.draw_circle(pymupdf.Point(560, 400), 90, fill=(0.85, 0.30, 0.22))
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------- #
# One fake client answering the whole set's digest + verify calls
# --------------------------------------------------------------------------- #


def _joined_text(messages: list) -> str:
    """All text blocks of a Messages request, concatenated (images ignored)."""
    parts: list[str] = []
    for m in messages:
        content = m.get("content", []) if isinstance(m, dict) else []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


class _AcceptanceClient:
    """Routes digest + verify by system prompt over the acceptance set.

    A digest whose sheet text mentions ``VAV-3`` (the seeded vector sheet)
    returns the seeded finding; any other sheet returns an empty findings
    block. Records call counts and whether the raster placeholder was ever
    presented, so tests can assert on the request the model actually received.
    """

    def __init__(self, *, findings: list[dict], verdict: str = "CONFIRMED") -> None:
        self.digest_calls = 0
        self.verify_calls = 0
        self.raster_placeholder_seen = False
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                text = _joined_text(kw.get("messages", []))
                if system == VERIFY_SYSTEM_PROMPT:
                    outer.verify_calls += 1
                    body = json.dumps({"verdict": verdict, "note": "seen in crop"})
                    return FakeMessage(
                        content=[FakeTextBlock(text=body)],
                        usage=FakeUsage(input_tokens=40, output_tokens=8),
                    )
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    outer.digest_calls += 1
                    if _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER in text:
                        outer.raster_placeholder_seen = True
                    sheet_findings = findings if "VAV-3" in text else []
                    prose = (
                        "Sheet - Fire Protection - Plan\n"
                        "General notes and hydraulic schedule."
                    )
                    block = "```json\n" + json.dumps({"findings": sheet_findings}) + "\n```"
                    return FakeMessage(
                        content=[FakeTextBlock(text=prose + "\n\n" + block)],
                        usage=FakeUsage(input_tokens=500, output_tokens=90),
                    )
                return FakeMessage(content=[FakeTextBlock(text="ok")])  # unused

        self.messages = _Msgs()


# The model's finding on the vector sheet. ``source_quote`` is verbatim on the
# sheet so it anchors EXACT; the verifier confirms it, so it verifies.
_VAV_FINDING = {
    "sheet_id": "F-D-01-1",
    "category": "code",
    "severity": "high",
    "text": "VAV-3 shows no clearance to the adjacent wall.",
    "source_quote": "VAV-3",
    "tile": [0, 0],
    "refs": ["CMC 310"],
}


def _annot_xref_objects(pdf_path: Path) -> list[str]:
    """The PDF object source of every annotation on a saved PDF."""
    doc = pymupdf.open(str(pdf_path))
    try:
        return [doc.xref_object(a.xref) for page in doc for a in page.annots()]
    finally:
        doc.close()


def _build_set(tmp_path: Path) -> tuple[Path, Path]:
    """A two-sheet fire-protection set: a demand sheet + a general sheet whose
    note points at a *stale* revision of the demand sheet (F-D-01-0 vs -1)."""
    demand = _vector_pdf(
        tmp_path / "fp-demand.pdf",
        sheet_id="F-D-01-1",
        body=["VAV-3 SERVES ROOM 120", "HYDRAULIC DEMAND SCHEDULE"],
    )
    general = _vector_pdf(
        tmp_path / "fp-general.pdf",
        sheet_id="F-G-02-0",
        body=["GENERAL NOTES"],
        refs=("SEE DRAWING F-D-01-0",),
    )
    return demand, general


# --------------------------------------------------------------------------- #
# Step 1 + 2 + 6 — fresh both-checkbox run produces the full QC deliverable
# --------------------------------------------------------------------------- #


def test_acceptance_fresh_run_produces_full_qc_deliverable(tmp_path):
    demand, general = _build_set(tmp_path)
    client = _AcceptanceClient(findings=[_VAV_FINDING])
    work = tmp_path / "qc"
    names = ["fp-demand.pdf", "fp-general.pdf"]

    ctx = extract_drawing_context(
        [demand, general], client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True,       # both checkboxes on
        qc_work_dir=work,
    )

    # 1a. The run completes: both sheets digested without error.
    assert ctx.sheet_count == 2
    assert ctx.ok_sheet_count == 2
    assert ctx.errors == []

    # 1b. Findings > 0: the model's VAV-3 finding + the deterministic stale ref.
    assert ctx.finding_count >= 2
    assert len(ctx.findings) == 1
    assert len(ctx.reference_findings) == 1

    # 1c. Every VERIFIED finding has its evidence crop on disk.
    verified = [f for f in ctx.all_findings if f.verification.status == "VERIFIED"]
    assert verified, "expected at least one verified finding"
    for f in verified:
        assert f.verification.evidence_png.startswith("evidence/")
        assert (work / f.verification.evidence_png).exists()

    # 1d. report.html renders a findings table with the finding and its chip.
    html = build_html_report(ctx, source_names=names)
    assert "QC Findings" in html
    assert "VAV-3" in html and "F-D-01-0" in html
    assert "Verified" in html and "Deterministic" in html

    # 2. Appearance-stream proxy for the Revu/Acrobat/Chromium spot-check: each
    # cloudable finding was inked, and every annotation carries an /AP appearance
    # stream (annot.update() built it) so it renders non-blank in third-party
    # viewers. Two sources, one cloudable finding each → two reviewed PDFs.
    assert ctx.clouded_finding_count == 2
    assert len(ctx.reviewed_pdf_paths) == 2
    objs = [o for pdf in ctx.reviewed_pdf_paths for o in _annot_xref_objects(pdf)]
    assert len(objs) == 2
    assert all("/AP" in o for o in objs)
    # The originals are never touched.
    assert _annot_xref_objects(demand) == []
    assert _annot_xref_objects(general) == []

    # 6. The folder export writes the §4.5 inventory, and findings.csv is
    # Excel-on-Windows-friendly: a UTF-8 BOM and CRLF line endings.
    export = write_drawing_export(ctx, tmp_path / "out", source_names=names)
    for name in ("report.html", "combined.md", "findings.json", "findings.csv"):
        assert (export / name).exists(), name
    assert (export / "sheet_text").is_dir()
    assert (export / "evidence").is_dir()
    assert (export / "fp-demand_reviewed.pdf").exists()
    assert (export / "fp-general_reviewed.pdf").exists()
    csv_bytes = (export / "findings.csv").read_bytes()
    assert csv_bytes.startswith(b"\xef\xbb\xbf")   # UTF-8 BOM
    assert b"\r\n" in csv_bytes                     # CRLF


# --------------------------------------------------------------------------- #
# Step 3 — the reference audit flags a stale pointer with a closest-match hint
# --------------------------------------------------------------------------- #


def test_acceptance_reference_audit_flags_stale_reference(tmp_path):
    demand, general = _build_set(tmp_path)
    client = _AcceptanceClient(findings=[])   # deterministic audit needs no model
    ctx = extract_drawing_context(
        [demand, general], client=client, rows=2, cols=2, reference_audit=True,
    )

    stale = [f for f in ctx.reference_findings if "F-D-01-0" in f.text]
    assert len(stale) == 1
    f = stale[0]
    assert f.category == "reference"
    assert "not present in the provided set" in f.text
    assert "closest in set: F-D-01-1" in f.text     # edit-distance suggestion
    assert "does not exist" not in f.text.lower()    # never overclaims
    # Free + trustworthy: exact anchor, deterministic, no API call.
    assert f.anchor.status == "EXACT" and f.anchor.rect_pdf is not None
    assert f.verification.status == "DETERMINISTIC"
    assert client.digest_calls == 2 and client.verify_calls == 0


# --------------------------------------------------------------------------- #
# Step 4 — an unchanged re-run is served from cache: zero digest API, identical
# --------------------------------------------------------------------------- #


def test_acceptance_cached_rerun_freezes_digest_api_and_reproduces(tmp_path):
    demand, general = _build_set(tmp_path)
    client = _AcceptanceClient(findings=[_VAV_FINDING])
    cache = DigestCache(None, persist=False)   # in-memory, hermetic

    def _run(work: Path):
        return extract_drawing_context(
            [demand, general], client=client, rows=2, cols=2, cache=cache,
            reference_audit=True, qc_markups=True, qc_work_dir=work,
        )

    first = _run(tmp_path / "qc1")
    digests_after_first = client.digest_calls
    assert digests_after_first == 2          # one vision call per sheet

    second = _run(tmp_path / "qc2")
    # The two-level cache serves both sheets pre-render: ZERO new digest calls.
    assert client.digest_calls == digests_after_first
    # Identical outputs: byte-identical prose and the same findings restored
    # from cache (id, category, anchor, verdict all reproduced).
    assert second.combined_text == first.combined_text
    assert second.finding_count == first.finding_count

    def _fingerprint(ctx):
        return sorted(
            (f.id, f.category, f.anchor.status, f.verification.status, f.text)
            for f in ctx.all_findings
        )

    assert _fingerprint(second) == _fingerprint(first)
    # Verification is intentionally *stateless* — it re-checks each run rather
    # than caching a verdict — so the digest cache, not the verify pass, is what
    # this step pins. The verifier ran again on the re-run.
    assert client.verify_calls == 2


# --------------------------------------------------------------------------- #
# Step 5 — a raster (empty-text-layer) sheet: 1992 px target, disclosed, badged
# --------------------------------------------------------------------------- #


def _render_first_page(path: Path, *, rows: int, cols: int):
    doc = pymupdf.open(str(path))
    try:
        ref = SheetRef(
            pdf_path=path, page_index=0, source_name=path.name,
            page_count=doc.page_count,
        )
        return render_sheet(doc[0], ref, rows=rows, cols=cols)
    finally:
        doc.close()


def test_acceptance_raster_sheet_target_disclosure_and_badge(tmp_path):
    raster = _raster_pdf(tmp_path / "scan.pdf")
    vector = _vector_pdf(tmp_path / "vec.pdf", sheet_id="M-101", body=["NOTE 1"])

    # Renders at the higher raster target (1992 px) — a full 6x6 grid so the
    # >20-image many-image regime is in force, where the target actually varies.
    # A vector sheet at the same grid renders at the 1560 px default; the raster
    # long edge is strictly larger.
    r_sheet = _render_first_page(raster, rows=6, cols=6)
    v_sheet = _render_first_page(vector, rows=6, cols=6)
    assert r_sheet.is_raster is True
    assert v_sheet.is_raster is False

    def _long_edge(s):
        return max(s.overview.width_px, s.overview.height_px)

    assert abs(_long_edge(r_sheet) - tiling.TARGET_LONG_EDGE_PX_RASTER) <= 2
    assert abs(_long_edge(v_sheet) - tiling.TARGET_LONG_EDGE_PX_DEFAULT) <= 2
    assert _long_edge(r_sheet) > _long_edge(v_sheet)

    # Through the pipeline: the prompt discloses the missing text layer, the
    # geometry is flagged raster, and the report badges the sheet.
    client = _AcceptanceClient(findings=[])
    ctx = extract_drawing_context(
        [raster], client=client, rows=2, cols=2, reference_audit=True,
    )
    assert client.raster_placeholder_seen is True
    assert len(ctx.sheet_geometries) == 1
    assert ctx.sheet_geometries[0].is_raster is True

    html = build_html_report(ctx, source_names=["scan.pdf"])
    assert "badge-raster" in html
    assert ">Raster<" in html
