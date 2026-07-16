"""Hermetic acceptance suite — Phase 10 proxies + the Phase 27 trust gauntlet.

Part 1 (below) encodes the original plan's manual acceptance script (§Phase 10)
as a repeatable, no-network test. Part 2 (the sections marked "Phase 27") is the
§19.1 automated trust gauntlet over the synthetic oracle set in
``tests/fixtures/gauntlet.py`` — first-run assertions 1–15, the unchanged
warm-cache run, the mutation run, per-stage failure injection, review-notes
overflow — plus the §19.2 large-set cross-shard acceptance. Everything here is
hermetic (fake client, no key, no network); the genuinely manual gates live in
``docs/WINDOWS_ACCEPTANCE.md`` and ``docs/RELEASE_ACCEPTANCE_TEMPLATE.md``.

The Phase 10 script's steps and their in-code proxies:

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
from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.cross_qc import CROSS_QC_SYSTEM_PROMPT  # noqa: E402
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
from drawing_analyzer.review_planner import PLANNER_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.set_identity import IDENTITY_SYSTEM_PROMPT  # noqa: E402
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
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    # A parse-valid empty read — a bare "ok" would (correctly,
                    # §3.3) hold the critique stage at PARTIAL since Phase 27.
                    return FakeMessage(
                        content=[FakeTextBlock(text='```json\n{"findings":[]}\n```')],
                        usage=FakeUsage(input_tokens=10, output_tokens=4),
                    )
                if system.startswith(CROSS_QC_SYSTEM_PROMPT):
                    # Same contract: a structured response, even when empty.
                    return FakeMessage(
                        content=[FakeTextBlock(text='```json\n{"findings":[],"claims":[]}\n```')],
                        usage=FakeUsage(input_tokens=10, output_tokens=4),
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
                if system == IDENTITY_SYSTEM_PROMPT:
                    payload = {
                        "disciplines": ["fire protection"],
                        "jurisdiction": "California, United States",
                        "language": "en", "units": "imperial",
                        "adopted_codes": [], "confidence": "medium",
                    }
                    return FakeMessage(
                        content=[FakeTextBlock(
                            text="```json\n" + json.dumps(payload) + "\n```")],
                        usage=FakeUsage(input_tokens=30, output_tokens=10),
                    )
                if system == PLANNER_SYSTEM_PROMPT:
                    plan = {"plans": [{
                        "discipline": "fire protection", "title": "FP QC",
                        "items": [{"text": "Flag a hydraulic schedule row with no "
                                           "density stated.",
                                   "severity": "medium", "refs": []}],
                    }]}
                    return FakeMessage(
                        content=[FakeTextBlock(
                            text="```json\n" + json.dumps(plan) + "\n```")],
                        usage=FakeUsage(input_tokens=30, output_tokens=10),
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
    # viewers. Two sources, one cloudable finding each → two reviewed PDFs, each
    # carrying a cloud + its QC-number tag (Phase 15).
    assert ctx.clouded_finding_count == 2
    assert len(ctx.reviewed_pdf_paths) == 2
    objs = [o for pdf in ctx.reviewed_pdf_paths for o in _annot_xref_objects(pdf)]
    assert len(objs) == 4
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


# =========================================================================== #
# Phase 27 — §19.1 automated trust gauntlet (the synthetic oracle set)
# =========================================================================== #

import csv  # noqa: E402
import hashlib  # noqa: E402
import io  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from drawing_analyzer.annotate import count_annotations  # noqa: E402
from tests.fixtures import gauntlet as G  # noqa: E402


@pytest.fixture(scope="module")
def oracle(tmp_path_factory):
    """One cold exhaustive run over the full §19.1 oracle set + its export.

    Module-scoped: the gauntlet's fifteen first-run assertions all interrogate
    this single deterministic run (and its exported folder), which is exactly
    the point — one run, every guarantee.
    """
    root = tmp_path_factory.mktemp("gauntlet")
    oset = G.build_oracle_set(root / "set")
    client = G.oracle_client()
    work = root / "qc"
    ctx = extract_drawing_context(
        oset.inputs, client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, qc_work_dir=work,
    )
    export = write_drawing_export(ctx, root / "out", source_names=oset.source_names)
    return SimpleNamespace(ctx=ctx, set=oset, client=client, work=work, export=export)


def _one(findings, **want):
    """Exactly one finding matching every given attribute (quote=, text_has=...)."""
    hits = []
    for f in findings:
        if "quote" in want and f.source_quote != want["quote"]:
            continue
        if "text_has" in want and want["text_has"] not in f.text:
            continue
        hits.append(f)
    assert len(hits) == 1, (want, [(f.qc_id, f.source_quote, f.text) for f in hits])
    return hits[0]


def _geom_map(ctx):
    return {(g.ref.source_id, g.ref.page_index): g for g in ctx.sheet_geometries}


def _raw_annots(pdf_path: Path) -> list:
    doc = pymupdf.open(str(pdf_path))
    try:
        return [
            {"type": a.type, "content": a.info.get("content", ""),
             "title": a.info.get("title", ""), "page": page.number}
            for page in doc for a in page.annots()
        ]
    finally:
        doc.close()


def _reviewed(ctx, name: str) -> Path:
    matches = [p for p in ctx.reviewed_pdf_paths if p.name == name]
    assert matches, (name, [p.name for p in ctx.reviewed_pdf_paths])
    return matches[0]


# ---- first-run assertion 1: bad input recorded, good pages complete ---------


def test_gauntlet_bad_input_recorded_good_pages_complete(oracle):
    ctx = oracle.ctx
    docs = ctx.input_inventory.documents
    assert len(docs) == 6
    accepted = [d for d in docs if d.accepted]
    assert [d.source_id for d in accepted] == [
        "SRC-0001", "SRC-0002", "SRC-0003", "SRC-0004", "SRC-0005"
    ]
    bad = [d for d in docs if not d.accepted]
    assert len(bad) == 1 and bad[0].display_name == "corrupt.pdf"
    assert bad[0].error
    # The bad file is a recorded run error, not a run-stopper: every readable
    # sheet digested.
    assert ctx.sheet_count == 5 and ctx.ok_sheet_count == 5
    assert any("corrupt.pdf" in e for e in ctx.errors)
    # Honest two-level status: the QC stack itself is clean (COMPLETE), while
    # the run-level outcome is PARTIAL because one input was never analyzed.
    assert ctx.qc_status == "COMPLETE"
    assert ctx.run_journal.final_status == "PARTIAL"


# ---- assertion 2: same-basename sources stay isolated end to end ------------


def test_gauntlet_same_basename_sources_isolated(oracle):
    ctx = oracle.ctx
    f1 = _one(ctx.all_findings, quote=G.Q_F1)      # lives on a/M-101.pdf
    f4 = _one(ctx.all_findings, quote=G.Q_F4)      # lives on b/M-101.pdf
    assert f1.source_id == "SRC-0001"
    assert f4.source_id == "SRC-0002"

    # Distinct reviewed PDFs with deterministic source-disambiguated names.
    a_pdf = _reviewed(ctx, "M-101__SRC-0001_reviewed.pdf")
    b_pdf = _reviewed(ctx, "M-101__SRC-0002_reviewed.pdf")

    a_contents = " ".join(x["content"] for x in _raw_annots(a_pdf))
    b_contents = " ".join(x["content"] for x in _raw_annots(b_pdf))
    # B's fire-pump finding never leaks onto A, and vice versa.
    assert "Fire pump" in b_contents
    assert "Fire pump" not in a_contents
    assert "service clearance" in a_contents
    assert "service clearance" not in b_contents

    # Evidence stays per-source too.
    assert f1.verification.evidence[0].source_id == "SRC-0001"
    assert f4.verification.evidence[0].source_id == "SRC-0002"


# ---- assertion 3: unrelated same-tile findings stay distinct -----------------


def test_gauntlet_same_tile_unrelated_findings_distinct(oracle):
    ctx = oracle.ctx
    f1 = _one(ctx.all_findings, quote=G.Q_F1)
    f2 = _one(ctx.all_findings, quote=G.Q_F2)
    assert f1.id != f2.id and f1.qc_id != f2.qc_id
    assert f1.tile == f2.tile == [0, 0]            # same tile, still two entries


# ---- assertion 4: every rectangle is valid in the canonical view space ------


def test_gauntlet_every_rect_valid_in_view_space(oracle):
    ctx = oracle.ctx
    geoms = _geom_map(ctx)

    def _check(rect, source_id, page_index, label):
        assert rect is not None, label
        x0, y0, x1, y1 = rect
        for v in rect:
            assert v == v and abs(v) != float("inf"), (label, rect)   # finite
        assert x0 < x1 and y0 < y1, (label, rect)
        g = geoms[(source_id, page_index)]
        assert x1 <= g.page_width_pt + 1.0 and y1 <= g.page_height_pt + 1.0, (
            label, rect, g.page_width_pt, g.page_height_pt)
        assert x0 >= -1.0 and y0 >= -1.0, (label, rect)

    anchored = 0
    for f in ctx.all_findings:
        if f.anchor.status != "UNANCHORED" and f.anchor.rect_pdf is not None:
            _check(f.anchor.rect_pdf, f.source_id, f.page_index, f.qc_id)
            anchored += 1
        for leg in f.also_on:
            if leg.anchor.status != "UNANCHORED" and leg.anchor.rect_pdf is not None:
                _check(leg.anchor.rect_pdf, leg.source_id, leg.page_index,
                       f"{f.qc_id}/leg")
    assert anchored >= 8    # rotations 0/90/180/270 + CropBox all anchored

    # Rotated + cropped sheets anchored EXACT (the Phase 19 guarantee, e2e).
    for quote in (G.Q_F4, G.Q_F5, G.Q_F6):
        assert _one(ctx.all_findings, quote=quote).anchor.status == "EXACT"

    # Repeated source text: the tile hint disambiguates the two occurrences of
    # "TYP DETAIL 5" — the r2c2-tagged finding anchors in the r2c2 quadrant.
    f3 = _one(ctx.all_findings, quote=G.Q_REPEATED)
    g = geoms[(f3.source_id, f3.page_index)]
    x0, y0, x1, y1 = f3.anchor.rect_pdf
    assert (x0 + x1) / 2 > g.page_width_pt / 2
    assert (y0 + y1) / 2 > g.page_height_pt / 2


# ---- assertion 5: every verifier image equals a saved evidence artifact -----


def test_gauntlet_verify_images_equal_saved_evidence(oracle):
    ctx, work, client = oracle.ctx, oracle.work, oracle.client

    sent = sorted(
        hashlib.sha256(img).hexdigest()
        for _text, images in client.verify_requests for img in images
    )
    assert sent, "verifier was never called"

    on_disk = sorted(
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (work / "evidence").rglob("leg-*.png")
    )
    assert sent == on_disk    # byte-for-byte: what the model saw IS what's saved

    # Every artifact record's hash matches its file, and its request trail exists.
    for f in ctx.all_findings:
        for art in f.verification.evidence:
            saved = work / art.relative_path
            assert saved.exists(), art.relative_path
            assert hashlib.sha256(saved.read_bytes()).hexdigest() == art.sha256
            assert (work / "evidence" / f.qc_id / "request.json").exists()


# ---- assertion 6: critique provenance + reproduced status are truthful ------


def test_gauntlet_critique_provenance_truthful(oracle):
    ctx = oracle.ctx
    cr1 = _one(ctx.all_findings, quote=G.Q_CR1)     # returned by both reads
    cr2 = _one(ctx.all_findings, quote=G.Q_CR2)     # returned by read 1 only
    assert cr1.reproduced is True
    assert {"critique_1", "critique_2"} <= set(cr1.sources)
    assert cr2.reproduced is False
    assert set(cr2.sources) & {"critique_1", "critique_2"} == {"critique_1"}
    # Each sheet received exactly two critique reads.
    assert all(n == 2 for n in oracle.client.critique_calls.values())


# ---- assertion 7: every enumerated prose item is accounted -------------------


def test_gauntlet_every_prose_item_accounted(oracle):
    ctx = oracle.ctx
    acc = ctx.prose_accounting
    assert acc["missing"] == 0 and acc["complete"] is True
    assert acc["matched"] >= 1 and acc["structured"] >= 1
    assert acc["degraded"] >= 1 and acc["set_level"] >= 1

    # The matched item landed as provenance on the digest finding.
    f2 = _one(ctx.all_findings, quote=G.Q_F2)
    assert "digest_json" in f2.sources and "digest_prose_coordination" in f2.sources
    # The straggler structured cleanly; the forced-failure item degraded, verbatim.
    _one(ctx.all_findings, text_has="fire wrap")
    degraded = _one(ctx.all_findings, text_has="Access panels")
    assert degraded.sources == ["digest_prose_coordination"]
    assert oracle.client.harvest_calls == 2        # one per straggler, no more


# ---- assertion 8: the cross-sheet conflict lands on every leg ----------------


def test_gauntlet_cross_conflict_on_every_leg(oracle):
    ctx = oracle.ctx
    cq = _one(ctx.all_findings, quote=G.Q_CQ_PRIMARY)
    assert cq.source_id == "SRC-0001" and len(cq.also_on) == 1
    leg = cq.also_on[0]
    assert leg.source_id == "SRC-0003" and leg.anchor.status == "EXACT"

    # A placement per leg, each with a terminal successful receipt.
    receipts = [r for r in ctx.markup_run.receipts
                if r.placement.finding_id == cq.id]
    legs = {r.placement.leg_id for r in receipts}
    assert "primary" in legs and len(legs) >= 2
    assert all(r.status == "WRITTEN" for r in receipts)

    # Both sheets' reviewed PDFs carry the conflict ink, cross-referencing.
    e_pdf = _reviewed(ctx, "E-201_reviewed.pdf")
    e_contents = " ".join(x["content"] for x in _raw_annots(e_pdf))
    assert "12 KW" in e_contents or "M-101" in e_contents

    # Dual-crop verification saved one crop per leg, in request order.
    ev = cq.verification.evidence
    assert [a.leg_index for a in ev] == [0, 1]
    assert ev[0].source_id != ev[1].source_id


# ---- assertion 9: citation assessments cover exactly the included claims ----


def test_gauntlet_citations_claim_complete(oracle):
    ctx, client = oracle.ctx, oracle.client
    f1 = _one(ctx.all_findings, quote=G.Q_F1)
    f2 = _one(ctx.all_findings, quote=G.Q_F2)

    # Both materially different claims were actually included in the request.
    joined = "\n".join(client.citation_requests)
    assert G.SHARED_REF in joined
    assert f1.text in joined and f2.text in joined

    # Each finding carries its own claim-specific verdict — one shared reference,
    # two different outcomes, never one verdict smeared across both claims.
    a1 = next(a for a in f1.citations if a.reference == G.SHARED_REF)
    a2 = next(a for a in f2.citations if a.reference == G.SHARED_REF)
    assert a1.status == "CHECKED_SUPPORTS"
    assert a2.status == "CHECKED_MISMATCH"
    assert f1.id in a1.claim_finding_ids
    assert f2.id in a2.claim_finding_ids

    # Phase B exact billing: the run bills the server-reported search count
    # (the scripted client reports a fixed figure per request), never the old
    # 1-per-request approximation when the exact number is available.
    (citation_rec,) = [r for r in ctx.run_usage.records
                       if r.stage_family == "citation"]
    billed = citation_rec.billable_tool_uses.get("web_search")
    assert billed == len(client.citation_requests) * G.ScriptedQCClient.CITATION_SEARCHES_PER_REQUEST

    # Phase B structured provenance: the scripted checked/current editions and
    # the https evidence URL land on the assessments end-to-end.
    assert a1.checked_edition == "NFPA 13 2016"
    assert a1.current_edition == "NFPA 13 2025"
    assert a1.evidence_url == "https://codes.example.org/nfpa13"


# ---- assertion 10: QC ids are positional (source, page, anchored, position) -


def test_gauntlet_qc_ids_follow_source_page_position(oracle):
    ctx = oracle.ctx
    in_qc_order = sorted(ctx.all_findings, key=lambda f: f.qc_id)
    order_of = {"SRC-0001": 1, "SRC-0002": 2, "SRC-0003": 3, "SRC-0004": 4, "": 9}

    source_seq = [order_of[f.source_id] for f in in_qc_order]
    assert source_seq == sorted(source_seq)        # input order, set-level last

    # Within a source, anchored entries precede unanchored/sheet-level entries.
    for sid in ("SRC-0001", "SRC-0004"):
        statuses = [f.anchor.status for f in in_qc_order if f.source_id == sid]
        first_unanchored = next(
            (i for i, s in enumerate(statuses) if s == "UNANCHORED"), len(statuses))
        assert all(s == "UNANCHORED" for s in statuses[first_unanchored:])

    # Same tile, two findings: page position (top y) breaks the tie.
    f1 = _one(ctx.all_findings, quote=G.Q_F1)      # y ≈ 100
    f2 = _one(ctx.all_findings, quote=G.Q_F2)      # y ≈ 128
    assert f1.qc_id < f2.qc_id

    # Ids are dense and start at QC-001.
    assert in_qc_order[0].qc_id == "QC-001"
    assert len({f.qc_id for f in in_qc_order}) == len(in_qc_order)


# ---- assertion 11: every expected placement has a terminal receipt ----------


def test_gauntlet_every_placement_has_terminal_receipt(oracle):
    ctx = oracle.ctx
    run = ctx.markup_run
    assert run is not None and run.placements
    assert len(run.receipts) == len(run.placements)
    expected_ids = {p.placement_id for p in run.placements}
    receipt_ids = [r.placement.placement_id for r in run.receipts]
    assert set(receipt_ids) == expected_ids        # none missing, none unexpected
    assert len(receipt_ids) == len(set(receipt_ids))   # no duplicate receipts
    assert all(r.status in ("WRITTEN", "INDEXED") for r in run.receipts)
    assert ctx.coverage_status == "COMPLETE"
    # The tally counts artifact placements, so the dual-leg conflict contributes
    # one cloud per sheet: entries + extra legs = placements accounted.
    extra_legs = sum(len(f.also_on) for f in ctx.all_findings)
    assert sum(ctx.ledger_tally.values()) == ctx.finding_count + extra_legs
    assert ctx.ledger_tally == {"cloud": 11, "margin": 3, "rejected": 1,
                                "review_notes": 1}


# ---- assertion 12: pre-existing annotations survive, originals untouched ----


def test_gauntlet_existing_annotations_intact(oracle):
    ctx, oset = oracle.ctx, oracle.set
    # The original input still holds exactly its one pre-existing note.
    original = _raw_annots(oset.a_m101)
    assert len(original) == 1 and G.PREEXISTING_NOTE in original[0]["content"]

    # The reviewed copy carries the pre-existing note — once, unmodified —
    # alongside the analyzer's marks.
    a_pdf = _reviewed(ctx, "M-101__SRC-0001_reviewed.pdf")
    raw = _raw_annots(a_pdf)
    stray = [x for x in raw if x["title"] == "prior-reviewer"]
    assert len(stray) == 1 and G.PREEXISTING_NOTE in stray[0]["content"]
    assert len(raw) > 1                                   # analyzer ink is there too

    # DA-029: the stray annotation satisfies no receipt — reconciliation matched
    # every placement to a run-stamped mark and still came back COMPLETE.
    assert ctx.coverage_status == "COMPLETE"
    a_receipts = [r for r in ctx.markup_run.receipts
                  if r.output_pdf == "M-101__SRC-0001_reviewed.pdf"]
    assert a_receipts and all(r.status in ("WRITTEN", "INDEXED") for r in a_receipts)


# ---- assertion 13: report, CSV, JSON, PDFs, manifests and log agree ---------


def test_gauntlet_all_outputs_agree(oracle):
    ctx, export = oracle.ctx, oracle.export
    qc_ids = sorted(f.qc_id for f in ctx.all_findings)

    data = json.loads((export / "findings.json").read_text(encoding="utf-8"))
    assert sorted(f["qc_id"] for f in data["findings"]) == qc_ids

    csv_text = (export / "findings.csv").read_bytes().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert sorted(r["qc_id"] for r in rows) == qc_ids

    html = (export / "report.html").read_text(encoding="utf-8")
    for qc_id in qc_ids:
        assert qc_id in html
    assert 'data-status="COMPLETE"' in html            # QC status banner
    assert 'data-coverage="COMPLETE"' in html          # coverage banner

    manifest = json.loads((export / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"]["qc_status"] == "COMPLETE"
    assert manifest["findings"]["total"] == ctx.finding_count
    assert manifest["markup_coverage"]["coverage_status"] == "COMPLETE"
    assert manifest["prose_accounting"] == ctx.prose_accounting

    mm = json.loads((export / "markup_manifest.json").read_text(encoding="utf-8"))
    assert len(mm["receipts"]) == len(ctx.markup_run.receipts)
    assert mm["coverage_status"] == "COMPLETE"

    log = (export / "run.log").read_text(encoding="utf-8")
    assert ctx.ledger_tally_line in log
    assert "QC status:   COMPLETE" in log

    # The reviewed PDFs' ink/index carries the same QC ids.
    pdf_text = []
    for p in ctx.reviewed_pdf_paths:
        pdf_text.extend(x["content"] for x in _raw_annots(p))
        doc = pymupdf.open(str(p))
        pdf_text.extend(page.get_text() for page in doc)
        doc.close()
    joined = " ".join(pdf_text)
    for qc_id in qc_ids:
        assert qc_id in joined, qc_id

    # No absolute private path leaks into the portable deliverables.
    private_root = str(oracle.set.root)
    for name in ("findings.json", "run.log", "run_manifest.json", "markup_manifest.json"):
        assert private_root not in (export / name).read_text(encoding="utf-8"), name


# ---- assertion 14: sacred prose ----------------------------------------------


def test_gauntlet_combined_text_is_sacred(oracle):
    ctx = oracle.ctx
    assert "```json" not in ctx.combined_text
    assert '"findings"' not in ctx.combined_text
    assert "VAV-7 serves the north zone" in ctx.combined_text
    assert G.SET_LEVEL_CONFLICT_SENTENCE in ctx.combined_text   # synthesis prose kept


# ---- assertion 15: COMPLETE only because every required component succeeded -


def test_gauntlet_exhaustive_status_complete(oracle):
    ctx = oracle.ctx
    assert ctx.qc_status == "COMPLETE"
    assert ctx.qc_status_label == "Exhaustive QC complete"
    assert ctx.configuration_kind == "NORMAL"
    assert ctx.coverage_status == "COMPLETE"
    statuses = {s.stage: s.status for s in ctx.stage_results}
    for stage in ("identity", "critique", "cross_qc", "synthesis", "auditors",
                  "prose_harvest", "verification", "citation", "markup"):
        assert statuses[stage] in ("COMPLETE", "SKIPPED_VALID"), (stage, statuses)
    # Usage totals are the exact sum of the append-only ledger.
    assert ctx.total_input_tokens == sum(r.input_tokens for r in ctx.run_usage.records)
    assert ctx.total_output_tokens == sum(r.output_tokens for r in ctx.run_usage.records)
    # Phase A: exactly one identity call, its usage in the ledger, and the
    # detected identity on the context + woven into the combined text.
    assert oracle.client.identity_calls == 1
    assert any(r.stage_family == "identity" for r in ctx.run_usage.records)
    assert ctx.set_identity is not None
    assert "fire protection" in ctx.set_identity.disciplines
    assert "## Set Identity (model-detected)" in ctx.combined_text
    # Phase A: exactly one plan-authoring call, its items injected into every
    # critique read's checklist, snapshotted as model-source profiles.
    assert oracle.client.plan_calls == 1
    assert any(r.stage_family == "review_plan" for r in ctx.run_usage.records)
    assert ctx.review_plan_profiles and ctx.review_plan_markdown
    assert all("no +30% increase applied" in s
               for s in oracle.client.critique_system_prompts)
    assert any(s.source == "model" for s in ctx.profile_snapshots)
    # Phase A: the identity context reached the downstream consumers — every
    # citation request carries the jurisdiction + merged-editions lines, and
    # every cross-QC input opens with the set-context preamble.
    assert oracle.client.citation_requests
    for req in oracle.client.citation_requests:
        assert "PROJECT JURISDICTION/LOCALE: California, United States" in req
        assert "NFPA 13 2016" in req
    assert oracle.client.cross_request_texts
    assert all(t.startswith("SET IDENTITY (model-detected):")
               for t in oracle.client.cross_request_texts)


# ---- the remaining §19.1 set contents: rejection, unanchored, set-level, ----
# ---- deterministic arithmetic, raster disclosure                          ----


def test_gauntlet_rejected_finding_indexed_not_inked(oracle):
    ctx = oracle.ctx
    f5 = _one(ctx.all_findings, quote=G.Q_F5)
    assert f5.verification.status == "REJECTED"
    receipts = [r for r in ctx.markup_run.receipts
                if r.placement.finding_id == f5.id]
    assert len(receipts) == 1
    assert receipts[0].placement.expected == "REJECTED_INDEX"
    assert receipts[0].status == "INDEXED"
    assert ctx.ledger_tally.get("rejected", 0) >= 1


def test_gauntlet_unanchored_finding_gets_margin_placement(oracle):
    ctx = oracle.ctx
    f7 = _one(ctx.all_findings, quote=G.Q_F7_MISSING)
    assert f7.anchor.status == "UNANCHORED"
    receipts = [r for r in ctx.markup_run.receipts
                if r.placement.finding_id == f7.id]
    assert len(receipts) == 1
    assert receipts[0].placement.expected in ("MARGIN", "REVIEW_NOTES")
    assert receipts[0].status == "WRITTEN"


def test_gauntlet_set_level_synthesis_conflict_routed_to_notes(oracle):
    ctx = oracle.ctx
    set_level = [f for f in ctx.all_findings
                 if not f.source_id and (f.anchor_hint or "").upper() in ("SET", "SET_INDEX")]
    assert len(set_level) == 1
    assert "no single sheet" in set_level[0].text
    assert "Drawing_Set_Review_Notes.pdf" in {p.name for p in ctx.reviewed_pdf_paths}
    assert ctx.ledger_tally.get("review_notes", 0) >= 1


def test_gauntlet_deterministic_auditors_fired(oracle):
    ctx = oracle.ctx
    stale = _one(ctx.reference_findings, text_has="M-999")
    assert stale.verification.status == "DETERMINISTIC"
    assert "closest in set" in stale.text

    arith = _one(ctx.reference_findings, quote=G.Q_ARITH)
    assert arith.verification.status == "DETERMINISTIC"
    assert arith.verification.operand_origin == "TEXT_EXTRACTED"
    assert "350" in arith.text and "375" in arith.text


def test_gauntlet_raster_sheet_disclosed(oracle):
    ctx = oracle.ctx
    assert oracle.client.raster_placeholder_seen is True
    raster = [g for g in ctx.sheet_geometries if g.is_raster]
    assert len(raster) == 1
    assert raster[0].ref.source_id == "SRC-0005"


# =========================================================================== #
# Phase 27 — §19.1 second run (warm cache) and third run (source mutation)
# =========================================================================== #


def test_gauntlet_warm_and_mutated_runs(tmp_path, monkeypatch):
    """Three sequential runs over one persistent cache.

    Run 1 (cold) populates the two-level digest cache + the critique level-1
    cache. Run 2 (unchanged) must hit: zero digest/critique API calls, zero
    full-sheet rasterization, findings rebound to the *current* source identity,
    stable QC numbering, and fresh markup receipts that still reconcile. Run 3
    mutates one source (a new text line): only that source misses, the new
    content demonstrably reaches analysis, and nothing stale is reused.
    """
    import drawing_analyzer.render as render_mod

    oset = G.build_oracle_set(tmp_path / "set")
    cache = DigestCache(tmp_path / "digest_cache.json")     # persistent on disk

    renders = {"n": 0}
    real_render = render_mod.render_sheet

    def _counting_render(*a, **k):
        renders["n"] += 1
        return real_render(*a, **k)

    monkeypatch.setattr(render_mod, "render_sheet", _counting_render)

    def _run(client, work):
        return extract_drawing_context(
            oset.inputs, client=client, rows=2, cols=2, cache=cache,
            reference_audit=True, qc_markups=True, qc_work_dir=work,
        )

    def _fingerprint(ctx):
        return sorted(
            (f.qc_id, f.source_id, f.source_quote, f.anchor.status,
             f.verification.status, f.text)
            for f in ctx.all_findings
        )

    # -- run 1: cold -------------------------------------------------------- #
    c1 = G.oracle_client()
    ctx1 = _run(c1, tmp_path / "qc1")
    assert ctx1.qc_status == "COMPLETE"
    renders_cold = renders["n"]
    # Cold real-time runs render each readable sheet twice: once for the digest
    # and once for the critique reads (the batch path shares one upload instead;
    # the level-1 caches erase both on a warm run).
    assert renders_cold == 10
    assert sum(c1.digest_calls.values()) == 5
    assert sum(c1.critique_calls.values()) == 10   # 5 sheets x 2 reads

    # -- run 2: unchanged (warm) --------------------------------------------- #
    renders["n"] = 0
    c2 = G.oracle_client()
    ctx2 = _run(c2, tmp_path / "qc2")
    # Zero new digest/critique API calls; zero full-sheet rasterization.
    assert c2.digest_calls == {} and c2.critique_calls == {}
    assert renders["n"] == 0
    # Cached stages are CACHE-transport, zero-billed records (§6.3).
    for family in ("digest", "critique"):
        recs = [r for r in ctx2.run_usage.records if r.stage_family == family]
        assert recs and all(r.transport == "CACHE" and r.cache_hit for r in recs)
        assert all(r.input_tokens == 0 and r.output_tokens == 0 for r in recs)
    # Verification is deliberately stateless — it re-checked this run.
    assert c2.verify_calls > 0
    # Cached findings were rebound to the current run's source identities (the
    # set-level synthesis note alone carries none, by design) and the whole
    # semantic output (incl. QC numbering) is stable.
    sheet_scoped = [f for f in ctx2.findings
                    if (f.anchor_hint or "").upper() not in ("SET", "SET_INDEX")]
    assert sheet_scoped
    assert {f.source_id for f in sheet_scoped} <= {
        "SRC-0001", "SRC-0002", "SRC-0003", "SRC-0004"}
    assert _fingerprint(ctx2) == _fingerprint(ctx1)
    assert ctx2.combined_text == ctx1.combined_text
    # Fresh markup receipts still reconcile against the new artifacts.
    assert ctx2.coverage_status == "COMPLETE"
    assert ctx2.qc_status == "COMPLETE"
    assert ctx2.cached_sheet_count == 5

    # -- run 3: mutate one source ------------------------------------------- #
    G.build_vector_sheet(
        oset.e201, sheet_id="E-201", rotation=180,
        lines=[(72, 100, G.Q_CQ_LEG), (72, 128, G.Q_F5),
               (72, 156, "REV 2 ISSUED FOR CONSTRUCTION")],
    )
    renders["n"] = 0
    c3 = G.oracle_client()
    ctx3 = _run(c3, tmp_path / "qc3")
    # Only the mutated source misses the cache…
    assert c3.digest_calls == {G.Q_CQ_LEG: 1}
    assert c3.critique_calls == {G.Q_CQ_LEG: 2}
    assert renders["n"] == 2                       # one digest + one critique render
    # …and the NEW visual/text state is what reached analysis.
    assert any("REV 2 ISSUED FOR CONSTRUCTION" in t for t in c3.digest_request_texts)
    # The other sheets served from cache; the run still reconciles cleanly.
    assert ctx3.cached_sheet_count == 4
    assert ctx3.qc_status == "COMPLETE"
    assert ctx3.coverage_status == "COMPLETE"
    # The mutated sheet's geometry reflects the new revision (no stale text).
    e_geom = next(g for g in ctx3.sheet_geometries if g.ref.source_id == "SRC-0003")
    assert "REV 2 ISSUED FOR CONSTRUCTION" in e_geom.sheet_text


# =========================================================================== #
# Phase 27 — §19.1 failure injection: every required stage, one at a time
# =========================================================================== #


def _mini_run(tmp_path, client, **kw):
    srcs = G.build_mini_set(tmp_path / "set")
    return extract_drawing_context(
        srcs, client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True,
        qc_work_dir=tmp_path / "qc", **kw,
    )


def _assert_degraded_honestly(ctx, stage: str, allowed=("PARTIAL", "FAILED")):
    statuses = {s.stage: s.status for s in ctx.stage_results}
    assert statuses[stage] in allowed, (stage, statuses)
    assert ctx.qc_status in ("PARTIAL", "FAILED")
    assert ctx.qc_status != "COMPLETE"
    # I-3: the standard deliverable survives every QC failure.
    assert "VAV-3 serves Room 120" in ctx.combined_text
    assert ctx.ok_sheet_count == 2


@pytest.mark.parametrize(
    "sabotage,stage",
    [
        ("synthesis", "synthesis"),
        ("critique_read2", "critique"),
        ("cross_qc", "cross_qc"),
        ("citation_empty", "citation"),
        ("identity", "identity"),
        ("review_plan_malformed", "review_plan"),
    ],
)
def test_gauntlet_failure_injection_bad_model_output(tmp_path, sabotage, stage):
    ctx = _mini_run(tmp_path, G.mini_client(sabotage=sabotage))
    _assert_degraded_honestly(ctx, stage)


def test_gauntlet_plan_failure_leaves_critique_on_user_profiles(tmp_path, monkeypatch):
    # Phase A: a malformed plan degrades the review_plan stage only — the
    # critique still runs, and a user-selected profile still rides its prompt.
    user_dir = tmp_path / "profiles"
    user_dir.mkdir()
    (user_dir / "office.md").write_text(
        "---\nname: office-list\ndisciplines: M\n---\n- Flag every OFFICE-TOKEN mismatch. [high]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DRAWING_ANALYZER_PROFILES_DIR", str(user_dir))
    client = G.mini_client(sabotage="review_plan_malformed")
    ctx = _mini_run(tmp_path, client, profiles=["office-list"])
    assert client.plan_calls == 1
    assert ctx.review_plan_profiles == []
    assert sum(client.critique_calls.values()) > 0
    # The user checklist still rode into every critique read.
    assert all("OFFICE-TOKEN" in s for s in client.critique_system_prompts)
    assert [s.name for s in ctx.profile_snapshots] == ["office-list"]
    assert any(e.startswith("Review plan:") for e in ctx.errors)


def test_gauntlet_plan_in_export(oracle):
    # review_plan.md ships with the export and is hashed into the manifest.
    import json as _json

    art = oracle.export / "review_plan.md"
    assert art.exists()
    body = art.read_text(encoding="utf-8")
    assert body.startswith("# Model-authored review plan")
    assert "NFPA 13 2016 §19.2.3.2.5" in body
    manifest = _json.loads((oracle.export / "run_manifest.json").read_text(encoding="utf-8"))
    assert any(a["path"] == "review_plan.md" for a in manifest["artifacts"])
    assert manifest["configuration"]["run_review_plan"] is True
    # The injected plan appears in the manifest's profiles with source=model.
    assert any(p.get("source") == "model" for p in manifest["profiles"])


def test_gauntlet_identity_failure_never_blocks_the_review(tmp_path):
    # Phase A: an unparseable identity reply degrades the identity stage only —
    # the critique still runs (identity-less), findings still land, and the
    # combined text simply has no Set Identity section.
    client = G.mini_client(sabotage="identity")
    ctx = _mini_run(tmp_path, client)
    assert ctx.set_identity is None
    assert client.identity_calls == 1
    assert sum(client.critique_calls.values()) > 0        # critique still ran
    assert ctx.finding_count >= 1
    assert "## Set Identity (model-detected)" not in ctx.combined_text
    assert any(e.startswith("Set identity:") for e in ctx.errors)


def test_gauntlet_identity_misdetection_is_advisory(tmp_path):
    # Phase A advisory contract: a confidently WRONG identity (landscape /
    # Iceland on a California mechanical set) steers context only. Nothing is
    # gated: the same findings land, the run still earns COMPLETE, and the
    # misdetection is visible — not laundered — in the manifest record.
    from drawing_analyzer.export import build_run_manifest

    wrong = _mini_run(tmp_path, G.mini_client(sabotage="identity_misdetect"))
    assert wrong.qc_status == "COMPLETE"
    assert wrong.set_identity is not None
    assert wrong.set_identity.disciplines == ("landscape",)
    baseline_count = _mini_run(tmp_path, G.mini_client()).finding_count
    assert wrong.finding_count == baseline_count          # nothing suppressed
    manifest = build_run_manifest(wrong)
    assert manifest["set_identity"]["disciplines"] == ["landscape"]
    assert manifest["set_identity"]["jurisdiction"] == "Reykjavik, Iceland"


def test_gauntlet_identity_in_export_and_manifest(oracle):
    # The identity record ships as set_identity.json (hashed into the manifest's
    # artifact walk) and as the manifest's set_identity key.
    import json as _json

    art = oracle.export / "set_identity.json"
    assert art.exists()
    data = _json.loads(art.read_text(encoding="utf-8"))
    assert "fire protection" in data["disciplines"]
    manifest = _json.loads((oracle.export / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["set_identity"]["disciplines"] == data["disciplines"]
    assert any(a["path"] == "set_identity.json" for a in manifest["artifacts"])
    assert manifest["configuration"]["run_identity"] is True


@pytest.mark.parametrize(
    "module_name,attr,stage",
    [
        ("drawing_analyzer.auditors", "run_auditors", "auditors"),
        ("drawing_analyzer.prose_harvest", "harvest_prose", "prose_harvest"),
        ("drawing_analyzer.verify", "verify_findings", "verification"),
    ],
)
def test_gauntlet_failure_injection_stage_crash(tmp_path, monkeypatch,
                                                module_name, attr, stage):
    import importlib

    mod = importlib.import_module(module_name)

    def _boom(*a, **k):
        raise RuntimeError(f"injected {stage} failure")

    monkeypatch.setattr(mod, attr, _boom)
    ctx = _mini_run(tmp_path, G.mini_client())
    _assert_degraded_honestly(ctx, stage)
    assert any("injected" in e or stage in e.lower() for e in ctx.errors)


def test_gauntlet_failure_injection_markup_writer(tmp_path, monkeypatch):
    import drawing_analyzer.annotate as A

    def _boom(*a, **k):
        raise RuntimeError("injected cloud failure")

    monkeypatch.setattr(A, "_add_cloud", _boom)
    ctx = _mini_run(tmp_path, G.mini_client())

    # Failed writes are FAILED receipts, coverage is INCOMPLETE, the partial
    # PDF is clearly labeled, and the run can never present as fully successful.
    assert ctx.coverage_status == "INCOMPLETE"
    assert ctx.qc_status == "PARTIAL"
    failed = [r for r in ctx.markup_run.receipts if r.status == "FAILED"]
    assert failed and all(r.error for r in failed)
    assert any(p.name.endswith("_reviewed_INCOMPLETE.pdf")
               for p in ctx.reviewed_pdf_paths)
    assert ctx.ledger_tally.get("failed", 0) >= 1
    # The tally never claims a cloud that was not written.
    assert ctx.ledger_tally.get("cloud", 0) == 0
    # I-3 still: the digest shipped.
    assert "VAV-3 serves Room 120" in ctx.combined_text


# =========================================================================== #
# Phase 27 — §19.1 review-notes overflow (dense page, no clear band)
# =========================================================================== #


def test_gauntlet_dense_page_overflows_to_review_notes(tmp_path):
    # A page whose every band is occupied by drawing text: sheet-level callouts
    # cannot pack without obscuring content, so they overflow to the appended
    # AI Review Notes page (§17.6) with real REVIEW_NOTES receipts — never
    # silently stacked over the drawing.
    lines = []
    y = 40.0
    while y < 585.0:
        lines.append((36.0, y, "DENSE CONTENT " * 9))
        y += 13.0
    dense = G.build_vector_sheet(tmp_path / "D-901.pdf", sheet_id="D-901",
                                 lines=lines)

    unplaced = [
        {"sheet_id": "D-901", "category": "question", "severity": "low",
         "text": f"Sheet-level question {i}: item not shown on any tile.",
         "source_quote": f"NOT ON THE SHEET {i}"}
        for i in range(1, 6)
    ]
    client = G.ScriptedQCClient(
        [G.SheetScript(token="DENSE CONTENT", prose="Sheet D-901 - Plan\nDense.",
                       findings=unplaced)],
    )
    ctx = extract_drawing_context(
        [dense], client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )

    notes_receipts = [r for r in ctx.markup_run.receipts
                      if r.placement.expected == "REVIEW_NOTES"]
    assert notes_receipts, "expected at least one review-notes overflow"
    assert all(r.status == "WRITTEN" for r in notes_receipts)
    assert ctx.ledger_tally.get("review_notes", 0) >= 1
    assert ctx.coverage_status == "COMPLETE"

    # The overflow page really exists in the reviewed PDF (source had 1 page).
    reviewed = next(p for p in ctx.reviewed_pdf_paths if "D-901" in p.name)
    doc = pymupdf.open(str(reviewed))
    try:
        assert doc.page_count > 1
        appended_text = "".join(doc[i].get_text() for i in range(1, doc.page_count))
    finally:
        doc.close()
    assert "Sheet-level question" in appended_text


# =========================================================================== #
# Phase 27 — §19.2 large-set acceptance (cross-shard reconciliation)
# =========================================================================== #
# Lightweight by design (plan §19.2): synthetic SheetDigest/SheetGeometry
# objects and a fake client drive ``cross_sheet_qc`` directly — no rasterizing
# of dozens of PDFs in CI. The smaller real-PDF end-to-end path is the oracle
# run's dual-leg conflict above.

import re  # noqa: E402

from drawing_analyzer import cross_qc as X  # noqa: E402
from drawing_analyzer.cross_qc import cross_sheet_qc  # noqa: E402
from drawing_analyzer.digest import SheetDigest  # noqa: E402
from drawing_analyzer.models import SheetGeometry, source_page_key  # noqa: E402

_NOOP_SLEEP = lambda *_a, **_k: None  # noqa: E731
_LW, _LH = 792.0, 612.0


def _ls_digest(source: str) -> SheetDigest:
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source, page_count=1)
    return SheetDigest(ref=ref, text="Sheet - Plan")


def _ls_geom(source: str, sid: str, note: str = "") -> SheetGeometry:
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source, page_count=1)
    return SheetGeometry(
        ref=ref, page_width_pt=_LW, page_height_pt=_LH, rows=2, cols=2,
        words=[(_LW - 300, _LH - 160, _LW - 240, _LH - 148, sid, 0, 0, 0)],
        sheet_text=f"{sid} title. {note} sheet text layer",
    )


class _ShardOracleClient:
    """Map calls emit one grounded fact per handle; the reconcile call reports the
    seeded conflict ONLY when both its sheets' handles are present in the request
    body — proving the cross-group comparison genuinely happened."""

    def __init__(self, conflict: dict):
        self.map_calls = 0
        self.reconcile_calls = 0
        self._conflict = conflict
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                body = kw["messages"][0]["content"][0]["text"]
                if system.startswith(X.CROSS_QC_RECONCILE_SYSTEM_PROMPT[:60]):
                    outer.reconcile_calls += 1
                    fin = outer._conflict
                    needed = [fin["sheet_handle"]] + [
                        leg["sheet_handle"] for leg in fin.get("also_on", [])
                    ]
                    present = all(re.search(rf"\b{h}\b", body) for h in needed)
                    obj = {"findings": [fin] if present else [], "claims": []}
                else:
                    outer.map_calls += 1
                    handles = re.findall(r"SHEET (S\d+)", body)
                    obj = {
                        "findings": [], "claims": [],
                        "facts": [
                            {"sheet_handle": h, "entity_or_tag": "COLO",
                             "attribute": "serves", "value": "area",
                             "exact_quote": "sheet text layer", "context": "note"}
                            for h in handles
                        ],
                    }
                return FakeMessage(
                    content=[FakeTextBlock(text="```json\n" + json.dumps(obj) + "\n```")],
                    usage=FakeUsage(input_tokens=800, output_tokens=60),
                )

        self.messages = _Msgs()


def test_acceptance_cross_shard_conflict_found_above_40_sheets():
    # §19.2: a 44-sheet two-discipline set shards (2 map calls); the seeded
    # conflict's sheets sit in DIFFERENT shards and neither local call reports
    # it — only the reconciliation can, and does.
    sheets, geoms = [], []
    sheets.append(_ls_digest("f0.pdf"))
    geoms.append(_ls_geom("f0.pdf", "F-D-00-1", "COLO 5 SERVES AREA A."))
    for i in range(1, 22):
        sheets.append(_ls_digest(f"f{i}.pdf"))
        geoms.append(_ls_geom(f"f{i}.pdf", f"F-D-{i:02d}-1"))
    sheets.append(_ls_digest("m0.pdf"))
    geoms.append(_ls_geom("m0.pdf", "M-D-00-1", "COLO 1 SERVES AREA A."))
    for i in range(1, 22):
        sheets.append(_ls_digest(f"m{i}.pdf"))
        geoms.append(_ls_geom(f"m{i}.pdf", f"M-D-{i:02d}-1"))
    assert len(sheets) == 44

    conflict = {
        "sheet_handle": "S001", "category": "conflict", "severity": "high",
        "text": "COLO 5 on F-D-00-1 conflicts with COLO 1 on M-D-00-1.",
        "source_quote": "COLO 5 SERVES AREA A",
        "also_on": [{"sheet_handle": "S023", "source_quote": "COLO 1 SERVES AREA A"}],
    }
    client = _ShardOracleClient(conflict)
    res = cross_sheet_qc(sheets, geoms, client=client, max_retries=0, sleep=_NOOP_SLEEP)

    assert client.map_calls == 2 and client.reconcile_calls == 1
    assert res.shards_planned == 2 and res.shards_completed == 2
    assert res.reconciliation_required and res.reconciliation_completed
    assert res.complete is True and res.error is None
    assert res.facts_collected == 44
    # The finding resolves BOTH legs to real, distinct source identities.
    conflicts = [f for f in res.findings if f.also_on]
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.source_name == "f0.pdf" and c.also_on[0].source_name == "m0.pdf"
    assert source_page_key(c) != source_page_key(c.also_on[0])
    # Usage covers every shard AND the reconciliation call (§19.2).
    assert res.input_tokens == 800 * 3
    assert res.output_tokens == 60 * 3


def test_acceptance_84_sheet_reduction_reaches_every_shard():
    # §19.2 (80+ sheets): three map shards; the seeded conflict spans shard 1 and
    # shard 3 — the reduction/reconciliation hierarchy must not isolate groups.
    sheets, geoms = [], []
    for i in range(84):
        note = ""
        if i == 0:
            note = "COLO 5 SERVES AREA A."
        if i == 80:
            note = "COLO 1 SERVES AREA A."
        sheets.append(_ls_digest(f"f{i}.pdf"))
        geoms.append(_ls_geom(f"f{i}.pdf", f"F-D-{i:02d}-1", note))

    conflict = {
        "sheet_handle": "S001", "category": "conflict", "severity": "high",
        "text": "COLO 5 (shard 1) conflicts with COLO 1 (shard 3).",
        "source_quote": "COLO 5 SERVES AREA A",
        "also_on": [{"sheet_handle": "S081", "source_quote": "COLO 1 SERVES AREA A"}],
    }
    client = _ShardOracleClient(conflict)
    res = cross_sheet_qc(sheets, geoms, client=client, max_retries=0, sleep=_NOOP_SLEEP)

    assert client.map_calls == 3                       # 84 sheets → 40/40/4
    assert client.reconcile_calls >= 1
    assert res.shards_planned == 3 and res.shards_completed == 3
    assert res.reconciliation_completed and res.complete is True
    conflicts = [f for f in res.findings if f.also_on]
    assert len(conflicts) == 1
    assert conflicts[0].source_name == "f0.pdf"
    assert conflicts[0].also_on[0].source_name == "f80.pdf"


def test_acceptance_failed_shard_holds_cross_qc_partial():
    # §19.2: one failed shard → completeness is honestly PARTIAL while the other
    # shard's findings stay usable (never a silent gap). The degraded shard's
    # response carries a parseable claims block but NO findings object — the
    # claims are salvaged for the arithmetic auditor (additive, §2.4) even
    # though the shard counts failed.
    sheets, geoms = [], []
    for i in range(44):
        prefix = "f" if i < 22 else "m"
        disc = "F" if i < 22 else "M"
        sheets.append(_ls_digest(f"{prefix}{i}.pdf"))
        geoms.append(_ls_geom(f"{prefix}{i}.pdf", f"{disc}-D-{i:02d}-1"))

    degraded_body = (
        "the model rambled instead of finishing the findings object\n"
        "```json\n"
        + json.dumps({"claims": [{"sheet_id": "S001", "quote": "TOTAL 540",
                                  "kind": "sum", "terms": [180, 180, 180],
                                  "expected": 540}]})
        + "\n```"
    )

    class _OneShardFails(_ShardOracleClient):
        def __init__(self):
            super().__init__({"sheet_handle": "S001", "category": "conflict",
                              "severity": "high", "text": "x", "source_quote": "q",
                              "also_on": []})
            inner = self.messages
            outer = self

            class _Msgs:
                def create(_self, **kw):  # noqa: ANN001, ANN202
                    system = kw.get("system", "")
                    if not system.startswith(X.CROSS_QC_RECONCILE_SYSTEM_PROMPT[:60]):
                        if outer.map_calls == 0:       # sabotage the first shard
                            outer.map_calls += 1
                            return FakeMessage(
                                content=[FakeTextBlock(text=degraded_body)],
                                usage=FakeUsage(input_tokens=800, output_tokens=10),
                            )
                    return inner.create(**kw)

            self.messages = _Msgs()

    client = _OneShardFails()
    res = cross_sheet_qc(sheets, geoms, client=client, max_retries=0, sleep=_NOOP_SLEEP)
    assert res.shards_planned == 2 and res.shards_completed == 1
    assert res.complete is False
    assert res.error and "no parseable findings object" in res.error
    # The degraded shard's claims survived, rebound to the real sheet identity.
    assert len(res.claims) == 1
    assert res.claims[0].sheet_id == "F-D-00-1"
    assert res.claims[0].source_name == "f0.pdf"
