"""Tests for the cross-sheet QC pass (Phase 13) — the dual-anchored conflict hunt.

Most is hermetic and PyMuPDF-free (synthetic ``SheetGeometry`` word tuples drive
sheet-id detection and anchoring); the markup and end-to-end pipeline checks need
PyMuPDF and are gated at the bottom.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer import cross_qc as X
from drawing_analyzer.anchor import resolve_conflict_legs
from drawing_analyzer.cross_qc import cross_sheet_qc, cross_qc_system_prompt
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.models import ConflictLeg, Finding, SheetGeometry, SheetRef
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

_NOOP = lambda *_a, **_k: None  # noqa: E731
W, H = 792.0, 612.0


def _w(x, y, text, w=60, h=12):
    return (float(x), float(y), float(x + w), float(y + h), text, 0, 0, 0)


def _geom(source, sid, extra_words=()):
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source, page_count=1)
    words = [_w(W - 300, H - 160, sid), *extra_words]      # title-block id bottom-right
    return SheetGeometry(
        ref=ref, page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=list(words), sheet_text=f"{sid} sheet text layer",
    )


def _digest(source, text="Sheet - FP - Plan"):
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source, page_count=1)
    return SheetDigest(ref=ref, text=text)


def _block(findings):
    return "```json\n" + json.dumps({"findings": findings}) + "\n```"


class _CrossClient:
    """Returns a scripted cross-QC findings block; counts calls."""

    def __init__(self, findings_per_call):
        # findings_per_call: list — one findings-list per expected call (cycles last).
        self._script = list(findings_per_call)
        self.calls = 0
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                i = min(outer.calls, len(outer._script) - 1)
                outer.calls += 1
                return FakeMessage(
                    content=[FakeTextBlock(text=_block(outer._script[i]))],
                    usage=FakeUsage(input_tokens=800, output_tokens=60),
                )

        self.messages = _Msgs()


_CONFLICT = {
    "sheet_id": "F-D-01-1", "category": "conflict", "severity": "high",
    "text": "The COLO 5 note sits on the COLO 1 sheet; the two sheets disagree.",
    "source_quote": "COLO 5", "tile": [0, 0],
    "also_on": [{"sheet_id": "F-A-01-1", "source_quote": "COLO 1", "tile": [0, 0]}],
}


# --------------------------------------------------------------------------- #
# Prompt / skip
# --------------------------------------------------------------------------- #


def test_system_prompt_and_between_sheets_mandate():
    sysp = cross_qc_system_prompt()
    assert "CROSS-SHEET" in sysp and "FINDINGS" in sysp
    assert "also_on" in sysp
    assert "claims" in sysp        # Phase 14: numeric-claim transcription


class _ClaimsCrossClient:
    """Returns a fixed cross-QC findings+claims block."""

    def __init__(self, claims):
        self._text = "```json\n" + json.dumps({"findings": [], "claims": claims}) + "\n```"
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                return FakeMessage(
                    content=[FakeTextBlock(text=outer._text)],
                    usage=FakeUsage(input_tokens=800, output_tokens=60),
                )

        self.messages = _Msgs()


def test_cross_qc_returns_numeric_claims():
    claim = {"sheet_id": "F-D-01-1", "quote": "TOTAL 540", "kind": "sum",
             "terms": [180, 180, 180], "expected": 540}
    res = cross_sheet_qc(
        [_digest("a.pdf"), _digest("b.pdf")],
        [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1")],
        client=_ClaimsCrossClient([claim]), max_retries=0, sleep=_NOOP,
    )
    assert len(res.claims) == 1 and res.claims[0].kind == "sum"
    # No emitting-sheet ref (the pass spans the set) — the auditor resolves by id.
    assert res.claims[0].source_name == "" and res.claims[0].sheet_id == "F-D-01-1"


def test_skips_below_two_readable_sheets():
    res = cross_sheet_qc([_digest("a.pdf")], [_geom("a.pdf", "F-D-01-1")],
                         client=_CrossClient([[]]), max_retries=0, sleep=_NOOP)
    assert res.skipped is True and res.findings == []


def test_skips_failed_or_empty_digests():
    a = _digest("a.pdf", "")            # empty digest → excluded
    b = _digest("b.pdf")
    b.error = "boom"                    # failed digest → excluded
    res = cross_sheet_qc([a, b], [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1")],
                         client=_CrossClient([[]]), max_retries=0, sleep=_NOOP)
    assert res.skipped is True          # fewer than two usable sheets


# --------------------------------------------------------------------------- #
# Parse + dual-anchor stamping
# --------------------------------------------------------------------------- #


def test_conflict_is_stamped_with_dual_anchors():
    sheets = [_digest("a.pdf"), _digest("b.pdf")]
    geoms = [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1")]
    client = _CrossClient([[_CONFLICT]])
    res = cross_sheet_qc(sheets, geoms, client=client, max_retries=0, sleep=_NOOP)
    assert client.calls == 1 and len(res.findings) == 1
    f = res.findings[0]
    assert f.source_name == "a.pdf" and f.source_quote == "COLO 5"
    assert len(f.also_on) == 1
    leg = f.also_on[0]
    assert leg.sheet_id == "F-A-01-1" and leg.source_name == "b.pdf"
    assert leg.source_quote == "COLO 1"
    assert res.input_tokens == 800 and res.output_tokens == 60


def test_finding_needs_two_resolvable_sheets():
    # also_on references a sheet not in the set → only one leg resolves → dropped.
    bad = dict(_CONFLICT, also_on=[{"sheet_id": "Z-9-99", "source_quote": "x"}])
    res = cross_sheet_qc(
        [_digest("a.pdf"), _digest("b.pdf")],
        [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1")],
        client=_CrossClient([[bad]]), max_retries=0, sleep=_NOOP,
    )
    assert res.findings == []


def test_promotes_first_resolvable_leg_when_primary_unknown():
    # Primary sheet_id doesn't resolve, but two also_on legs do → still placed.
    item = {
        "sheet_id": "GHOST", "category": "coordination", "severity": "medium",
        "text": "Tag differs between the two demand sheets.",
        "source_quote": "P", "tile": [0, 0],
        "also_on": [
            {"sheet_id": "F-D-01-1", "source_quote": "COLO 5", "tile": [0, 0]},
            {"sheet_id": "F-A-01-1", "source_quote": "COLO 1", "tile": [1, 1]},
        ],
    }
    res = cross_sheet_qc(
        [_digest("a.pdf"), _digest("b.pdf")],
        [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1")],
        client=_CrossClient([[item]]), max_retries=0, sleep=_NOOP,
    )
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.source_name == "a.pdf" and f.source_quote == "COLO 5"   # promoted
    assert [l.source_name for l in f.also_on] == ["b.pdf"]


def test_large_set_shards_by_discipline():
    sheets, geoms = [], []
    for i in range(45):                                  # one discipline, over the 40 cap
        src = f"f{i}.pdf"
        sheets.append(_digest(src))
        geoms.append(_geom(src, f"F-D-{i:02d}-1"))
    client = _CrossClient([[]])
    res = cross_sheet_qc(sheets, geoms, client=client, max_retries=0, sleep=_NOOP)
    assert client.calls == 2 and res.skipped is False    # 45 → chunks of 40 → 2 calls


def test_dedup_keeps_distinct_conflicts_sharing_a_primary_quote():
    # Two conflicts, same primary sheet + quote, but a DIFFERENT other sheet — a
    # real "this value conflicts with two sheets in two ways" case. Keying dedup on
    # Finding.id alone (which excludes also_on) would drop one; the full-conflict
    # key keeps both.
    c2 = {
        "sheet_id": "F-D-01-1", "category": "conflict", "severity": "high",
        "text": "COLO 5 also disagrees with the general sheet.",
        "source_quote": "COLO 5", "tile": [0, 0],
        "also_on": [{"sheet_id": "F-G-02-0", "source_quote": "COLO 5 zone", "tile": [1, 1]}],
    }
    res = cross_sheet_qc(
        [_digest("a.pdf"), _digest("b.pdf"), _digest("c.pdf")],
        [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1"), _geom("c.pdf", "F-G-02-0")],
        client=_CrossClient([[_CONFLICT, c2]]), max_retries=0, sleep=_NOOP,
    )
    assert len(res.findings) == 2
    assert {leg.sheet_id for f in res.findings for leg in f.also_on} == {"F-A-01-1", "F-G-02-0"}


def test_leg_on_the_primary_sheet_is_not_a_second_sheet():
    # also_on repeats the primary's sheet → only one DISTINCT sheet resolves → the
    # finding is dropped (a conflict must span two real sheets).
    item = dict(_CONFLICT, also_on=[{"sheet_id": "F-D-01-1", "source_quote": "COLO 5 again"}])
    res = cross_sheet_qc(
        [_digest("a.pdf"), _digest("b.pdf")],
        [_geom("a.pdf", "F-D-01-1"), _geom("b.pdf", "F-A-01-1")],
        client=_CrossClient([[item]]), max_retries=0, sleep=_NOOP,
    )
    assert res.findings == []


def test_csv_export_includes_also_on_column():
    from drawing_analyzer.export import FINDINGS_CSV_HEADER, build_findings_csv

    assert "also_on" in FINDINGS_CSV_HEADER
    f = Finding(
        sheet_id="F-D-01-1", source_name="a.pdf", page_index=0, category="conflict",
        severity="high", text="conflict", source_quote="COLO 5",
        also_on=[ConflictLeg(sheet_id="F-A-01-1", source_quote="COLO 1")],
    )
    csv = build_findings_csv([f])
    assert "F-A-01-1" in csv and "COLO 1" in csv


# --------------------------------------------------------------------------- #
# Leg anchoring (pure — word tuples)
# --------------------------------------------------------------------------- #


def test_resolve_conflict_legs_anchors_each_leg_on_its_sheet():
    ga = _geom("a.pdf", "F-D-01-1", extra_words=[_w(80, 120, "COLO"), _w(150, 120, "5")])
    gb = _geom("b.pdf", "F-A-01-1", extra_words=[_w(80, 120, "COLO"), _w(150, 120, "1")])
    geom_by_key = {(g.ref.source_name, g.ref.page_index): g for g in (ga, gb)}
    f = Finding(
        sheet_id="F-D-01-1", source_name="a.pdf", page_index=0, category="conflict",
        severity="high", text="conflict", source_quote="COLO 5", tile=[0, 0],
        also_on=[ConflictLeg(sheet_id="F-A-01-1", source_name="b.pdf", page_index=0,
                             source_quote="COLO 1", tile=[0, 0])],
    )
    resolve_conflict_legs([f], geom_by_key)
    assert f.also_on[0].anchor.status == "EXACT"
    assert f.also_on[0].anchor.rect_pdf is not None
    # a leg whose sheet is absent from the map is left unanchored, not crashed
    g = Finding(sheet_id="x", source_name="a.pdf", page_index=0, category="conflict",
                severity="low", text="t", source_quote="COLO 5", tile=[0, 0],
                also_on=[ConflictLeg(sheet_id="Q", source_name="missing.pdf", page_index=0,
                                     source_quote="COLO 1")])
    resolve_conflict_legs([g], geom_by_key)
    assert g.also_on[0].anchor.status == "UNANCHORED"


# --------------------------------------------------------------------------- #
# Markup + pipeline (need PyMuPDF)
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import _expand_for_markup, count_annotations, write_reviewed_pdfs  # noqa: E402
from drawing_analyzer.anchor import resolve_anchors  # noqa: E402
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402


def _mkpdf(path, body, sid):
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((80, 120), body)
    page.insert_text((650, 560), sid)
    doc.save(str(path))
    doc.close()
    return path


def test_expand_for_markup_yields_a_cloud_per_sheet():
    primary = Finding(
        sheet_id="F-D-01-1", source_name="a.pdf", page_index=0, category="conflict",
        severity="high", text="conflict", source_quote="COLO 5",
        also_on=[ConflictLeg(sheet_id="F-A-01-1", source_name="b.pdf", page_index=0,
                             source_quote="COLO 1")],
    )
    expanded = _expand_for_markup([primary])
    assert [f.source_name for f in expanded] == ["a.pdf", "b.pdf"]
    # the synthetic leg cross-references the primary
    assert expanded[1].also_on[0].sheet_id == "F-D-01-1"


def test_cross_finding_clouds_both_sheets_with_cross_reference(tmp_path):
    a = _mkpdf(tmp_path / "F-D-01-1.pdf", "COLO 5 SERVES AREA", "F-D-01-1")
    b = _mkpdf(tmp_path / "F-A-01-1.pdf", "COLO 1 SERVES AREA", "F-A-01-1")

    def geom(path):
        doc = pymupdf.open(str(path))
        words = list(doc[0].get_text("words"))
        doc.close()
        ref = SheetRef(pdf_path=path, page_index=0, source_name=path.name, page_count=1)
        return SheetGeometry(ref=ref, page_width_pt=W, page_height_pt=H, rows=2, cols=2, words=words)

    ga, gb = geom(a), geom(b)
    geom_by_key = {(g.ref.source_name, g.ref.page_index): g for g in (ga, gb)}
    f = Finding(
        sheet_id="F-D-01-1", source_name="F-D-01-1.pdf", page_index=0, category="conflict",
        severity="high", text="COLO 5 vs COLO 1 conflict.", source_quote="COLO 5", tile=[0, 0],
        also_on=[ConflictLeg(sheet_id="F-A-01-1", source_name="F-A-01-1.pdf", page_index=0,
                             source_quote="COLO 1", tile=[0, 0])],
    )
    resolve_anchors([f], ga)
    resolve_conflict_legs([f], geom_by_key)
    outs = write_reviewed_pdfs([f], [a, b], tmp_path / "out", include_unverified=True)
    assert {p.name for p in outs} == {"F-D-01-1_reviewed.pdf", "F-A-01-1_reviewed.pdf"}
    assert all(count_annotations(p) == 1 for p in outs)
    # each popup names the other sheet
    contents = []
    for p in outs:
        doc = pymupdf.open(str(p))
        contents += [an.info.get("content", "") for pg in doc for an in pg.annots()]
        doc.close()
    assert any("F-A-01-1" in c for c in contents)
    assert any("F-D-01-1" in c for c in contents)


class _PipelineClient:
    """digest + cross-QC + verify. Cross-QC returns one COLO conflict."""

    def __init__(self, *, verify_verdict="NOT_VISIBLE"):
        self.digest_calls = 0
        self.cross_calls = 0
        self.verify_calls = 0
        self.verify_image_counts = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                if system == VERIFY_SYSTEM_PROMPT:
                    outer.verify_calls += 1
                    imgs = sum(
                        1 for b in kw["messages"][0]["content"]
                        if isinstance(b, dict) and b.get("type") == "image"
                    )
                    outer.verify_image_counts.append(imgs)
                    return FakeMessage(
                        content=[FakeTextBlock(text=f'{{"verdict":"{verify_verdict}","note":"x"}}')],
                        usage=FakeUsage(input_tokens=40, output_tokens=8))
                if system.startswith(X.CROSS_QC_SYSTEM_PROMPT):
                    outer.cross_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text=_block([_CONFLICT]))],
                                       usage=FakeUsage(input_tokens=800, output_tokens=60))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    outer.digest_calls += 1
                    prose = "Sheet - FP - Plan\nColocation area note."
                    return FakeMessage(content=[FakeTextBlock(text=prose + "\n\n" + _block([]))],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


def test_pipeline_cross_qc_clouds_both_sheets(tmp_path):
    a = _mkpdf(tmp_path / "F-D-01-1.pdf", "COLO 5 SERVES AREA", "F-D-01-1")
    b = _mkpdf(tmp_path / "F-A-01-1.pdf", "COLO 1 SERVES AREA", "F-A-01-1")
    client = _PipelineClient()
    ctx = extract_drawing_context(
        [a, b], client=client, rows=2, cols=2, cross_qc=True, qc_markups=True,
        markup_verified_only=False,       # cross-sheet verifies UNCERTAIN → ink under this
        qc_work_dir=tmp_path / "qc",
    )
    assert client.cross_calls == 1
    # One dual-anchored conflict finding in the record...
    conflicts = [f for f in ctx.findings if f.also_on]
    assert len(conflicts) == 1 and conflicts[0].source_quote == "COLO 5"
    assert conflicts[0].also_on[0].source_name == "F-A-01-1.pdf"
    # ...clouded on BOTH sheets.
    assert {p.name for p in ctx.reviewed_pdf_paths} == {"F-D-01-1_reviewed.pdf", "F-A-01-1_reviewed.pdf"}
    assert all(count_annotations(p) == 1 for p in ctx.reviewed_pdf_paths)
    # I-2: the conflict never leaks into the prose.
    assert "COLO 5 vs COLO 1" not in ctx.combined_text
    assert "```json" not in ctx.combined_text


def test_pipeline_dual_crop_verify_clouds_under_default_gating(tmp_path):
    # The whole point of the dual-crop verifier: a cross-sheet finding gets one crop
    # PER sheet in a single call, so it can reach VERIFIED and be clouded under the
    # DEFAULT verified-only gating (a single-crop verify could only say NOT_VISIBLE).
    a = _mkpdf(tmp_path / "F-D-01-1.pdf", "COLO 5 SERVES AREA", "F-D-01-1")
    b = _mkpdf(tmp_path / "F-A-01-1.pdf", "COLO 1 SERVES AREA", "F-A-01-1")
    client = _PipelineClient(verify_verdict="CONFIRMED")
    ctx = extract_drawing_context(
        [a, b], client=client, rows=2, cols=2, cross_qc=True, qc_markups=True,
        qc_work_dir=tmp_path / "qc",          # markup_verified_only defaults True
    )
    conflict = next(f for f in ctx.findings if f.also_on)
    assert conflict.verification.status == "VERIFIED"
    assert conflict.verification.evidence_png.startswith("evidence/")
    # The verify call carried a crop for EACH sheet (dual crop), not just one.
    assert client.verify_calls == 1 and client.verify_image_counts == [2]
    # Clouded on BOTH sheets under the default (verified-only) gate.
    assert {p.name for p in ctx.reviewed_pdf_paths} == {"F-D-01-1_reviewed.pdf", "F-A-01-1_reviewed.pdf"}
    assert all(count_annotations(p) == 1 for p in ctx.reviewed_pdf_paths)


def test_pipeline_without_cross_qc_is_unchanged(tmp_path):
    a = _mkpdf(tmp_path / "F-D-01-1.pdf", "COLO 5 SERVES AREA", "F-D-01-1")
    b = _mkpdf(tmp_path / "F-A-01-1.pdf", "COLO 1 SERVES AREA", "F-A-01-1")
    client = _PipelineClient()
    ctx = extract_drawing_context(
        [a, b], client=client, rows=2, cols=2, cross_qc=False, qc_markups=True,
        qc_work_dir=tmp_path / "qc",
    )
    assert client.cross_calls == 0
    assert [f for f in ctx.findings if f.also_on] == []
