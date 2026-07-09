"""End-to-end QC-pipeline wiring: digests → findings → audit → anchor → verify
→ markups, driven through ``extract_drawing_context``.

Renders a synthetic PDF and needs PyMuPDF (for text extraction, crop rendering,
and the reviewed-PDF markups), so the whole module is skipped without it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402
from tests.fixtures.fake_anthropic import (  # noqa: E402
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
)


def _make_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "VAV-3 SERVES ROOM 120")
    page.insert_text((80, 200), "SEE DRAWING M-999 FOR CONTINUATION")
    page.insert_text((650, 560), "M-101")   # title-block sheet id (bottom-right)
    doc.save(str(path))
    doc.close()
    return path


def _digest_block(findings: list[dict]) -> str:
    return "```json\n" + json.dumps({"findings": findings}) + "\n```"


class _RoutingClient:
    """One fake client that answers digest, verify, and synthesis calls."""

    def __init__(self, digest_findings: list[dict], *, verdict: str = "CONFIRMED"):
        self.digest_calls = 0
        self.verify_calls = 0

        prose = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120."
        digest_text = prose + "\n\n" + _digest_block(digest_findings)
        verdict_text = f'{{"verdict":"{verdict}","note":"seen"}}'

        class _Msgs:
            def create(_self, **kw):
                system = kw.get("system", "")
                if system == VERIFY_SYSTEM_PROMPT:
                    self.verify_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text=verdict_text)],
                                       usage=FakeUsage(input_tokens=40, output_tokens=8))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    self.digest_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                # anything else (unused here)
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


_VAV_FINDING = {
    "sheet_id": "M-101", "category": "code", "severity": "high",
    "text": "VAV-3 has no shown clearance.", "source_quote": "VAV-3", "tile": [0, 0],
    "refs": ["CMC 310"],
}


def _annot_count(pdf_path: Path) -> int:
    doc = pymupdf.open(str(pdf_path))
    try:
        return sum(1 for page in doc for _ in page.annots())
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# Full chain
# --------------------------------------------------------------------------- #


def test_full_qc_chain(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])

    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, markup_verified_only=True,
        qc_work_dir=tmp_path / "qc",
    )

    # Model finding: parsed, anchored EXACT (its quote is on the sheet), verified.
    assert len(ctx.findings) == 1
    f = ctx.findings[0]
    assert f.anchor.status == "EXACT" and f.anchor.rect_pdf is not None
    assert f.verification.status == "VERIFIED"
    assert f.verification.evidence_png.startswith("evidence/")
    assert (tmp_path / "qc" / "evidence" / f"{f.id}.png").exists()
    assert client.verify_calls == 1

    # Reference finding: the stale M-999 pointer, deterministic (never verified).
    assert len(ctx.reference_findings) == 1
    ref = ctx.reference_findings[0]
    assert ref.category == "reference" and "M-999" in ref.text
    assert ref.verification.status == "DETERMINISTIC"

    # Geometry retained (no PNG bytes) for the QC stages.
    assert len(ctx.sheet_geometries) == 1
    assert len(ctx.sheet_geometries[0].words) > 0

    # A reviewed PDF was written with both cloudable findings (VERIFIED +
    # DETERMINISTIC), each carrying its QC-number tag (Phase 15): 2 clouds + 2 tags.
    assert len(ctx.reviewed_pdf_paths) == 1
    assert ctx.reviewed_pdf_paths[0].name == "M-101_reviewed.pdf"
    assert _annot_count(ctx.reviewed_pdf_paths[0]) == 4
    # Sequential review numbers were assigned across the run's findings.
    assert sorted(f.qc_id for f in ctx.all_findings) == ["QC-001", "QC-002"]
    # The original is untouched.
    assert _annot_count(src) == 0
    # Findings surface on the context.
    assert ctx.finding_count == 2 and ctx.clouded_finding_count == 2


# --------------------------------------------------------------------------- #
# Flag matrix
# --------------------------------------------------------------------------- #


def test_no_qc_flags_leaves_findings_empty(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context([src], client=client, rows=2, cols=2)   # no QC flags
    assert ctx.findings == [] and ctx.reference_findings == []
    assert ctx.reviewed_pdf_paths == [] and ctx.sheet_geometries == []
    assert client.verify_calls == 0


def test_reference_audit_only_no_markups_no_verify(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, reference_audit=True, qc_markups=False,
    )
    # Reference findings produced; model findings parsed + anchored but NOT verified
    # (no markups requested) and no reviewed PDF written.
    assert len(ctx.reference_findings) == 1
    assert len(ctx.findings) == 1
    assert ctx.findings[0].anchor.status == "EXACT"
    assert ctx.findings[0].verification.status == "SKIPPED"   # not verified
    assert client.verify_calls == 0
    assert ctx.reviewed_pdf_paths == []


def test_qc_markups_include_unverified(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    # Verifier says NOT_VISIBLE -> the model finding is UNCERTAIN; with
    # markup_verified_only=False it still gets clouded (dashed).
    client = _RoutingClient([_VAV_FINDING], verdict="NOT_VISIBLE")
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, markup_verified_only=False,
        qc_work_dir=tmp_path / "qc",
    )
    assert ctx.findings[0].verification.status == "UNCERTAIN"
    # Both the UNCERTAIN model finding and the DETERMINISTIC reference are inked,
    # each with its QC tag (Phase 15): 2 clouds + 2 tags.
    assert _annot_count(ctx.reviewed_pdf_paths[0]) == 4


def test_verify_disabled_still_anchors_and_marks(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        qc_markups=True, verify_findings=False, markup_verified_only=False,
        qc_work_dir=tmp_path / "qc",
    )
    assert client.verify_calls == 0
    assert ctx.findings[0].anchor.status == "EXACT"
    assert ctx.findings[0].verification.status == "SKIPPED"
    # include-unverified inks the SKIPPED model finding (cloud + QC tag).
    assert _annot_count(ctx.reviewed_pdf_paths[0]) == 2


# --------------------------------------------------------------------------- #
# Batch-path geometry retention
# --------------------------------------------------------------------------- #


def test_batch_path_retains_words_for_qc(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    # The batch path streams and discards each rendered sheet after upload; the
    # geometry sink must still capture each sheet's words/text as it renders, so
    # the QC stages survive. (The minimal fake client has no Files API, so the
    # batch digest itself no-ops — but geometry capture happens at render time,
    # before upload, which is exactly what this asserts. The full chain is
    # covered on the real-time path above.)
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, use_batch=True,
        reference_audit=True, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    assert len(ctx.sheet_geometries) == 1
    assert len(ctx.sheet_geometries[0].words) > 0
    assert ctx.sheet_geometries[0].sheet_text != ""
    # The offline reference audit runs off that retained geometry alone.
    assert len(ctx.reference_findings) == 1 and "M-999" in ctx.reference_findings[0].text


def test_combined_text_has_no_findings_block(tmp_path):
    # I-2: the QC findings never leak into the prose combined_text.
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, reference_audit=True, qc_markups=True,
        qc_work_dir=tmp_path / "qc",
    )
    assert "```json" not in ctx.combined_text
    assert '"findings"' not in ctx.combined_text
    assert "VAV-3 serves Room 120" in ctx.combined_text


# --------------------------------------------------------------------------- #
# Part III — the findings ledger: prose carry-through + coverage assertion
# --------------------------------------------------------------------------- #


class _ProseRoutingClient:
    """Digest with a prose Coordination item beyond its JSON block; the harvest's
    structuring call gets garbage (forcing the degraded path); verify confirms."""

    def __init__(self):
        self.harvest_calls = 0
        prose = (
            "Sheet M-101 - Mechanical - Plan\n"
            "VAV-3 serves Room 120.\n\n"
            "**Coordination / cross-discipline items**\n"
            "- VAV-3 has no clearance.\n"
            "- Fire-smoke damper at the corridor wall is furnished by another discipline.\n"
        )
        digest_text = prose + "\n" + _digest_block([_VAV_FINDING])
        verdict_text = '{"verdict":"CONFIRMED","note":"seen"}'

        from drawing_analyzer.prose_harvest import HARVEST_SYSTEM_PROMPT

        class _Msgs:
            def create(_self, **kw):
                system = kw.get("system", "")
                if system == HARVEST_SYSTEM_PROMPT:
                    self.harvest_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text="not json")],
                                       usage=FakeUsage(input_tokens=50, output_tokens=10))
                if system == VERIFY_SYSTEM_PROMPT:
                    return FakeMessage(content=[FakeTextBlock(text=verdict_text)],
                                       usage=FakeUsage(input_tokens=40, output_tokens=8))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


def test_ledger_coverage_every_entry_accounted_on_the_pdf(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _ProseRoutingClient()
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )

    # The prose section had two items: one restates the JSON finding (matched —
    # its entry gains prose provenance), one is a straggler whose structuring
    # call was forced to fail → a degraded SHEET entry (the §17 invariant).
    assert client.harvest_calls == 1
    matched = next(f for f in ctx.findings if "digest_json" in f.sources)
    assert "digest_prose_coordination" in matched.sources
    degraded = next(f for f in ctx.findings if f.sources == ["digest_prose_coordination"])
    assert degraded.anchor_hint == "SHEET"
    assert "another discipline" in degraded.text

    # Coverage (§18): every ledger entry is exactly one of cloud/margin/rejected.
    # 3 entries: the VERIFIED model finding (cloud), the degraded prose item
    # (margin callout), and the DETERMINISTIC reference finding (cloud).
    assert ctx.finding_count == 3
    assert ctx.ledger_tally == {"cloud": 2, "margin": 1}
    assert sum(ctx.ledger_tally.values()) == ctx.finding_count
    assert ctx.ledger_tally_line == "Ledger 3: 2 clouded, 1 margin, 0 rejected (indexed)"
    assert not any(e.startswith("Ledger coverage") for e in ctx.errors)

    # The ink matches the tally: 2 clouds + 2 QC tags + 1 margin callout.
    assert _annot_count(ctx.reviewed_pdf_paths[0]) == 5

    # Provenance reaches the CSV (source-tag column).
    from drawing_analyzer.export import build_findings_csv

    csv_text = build_findings_csv(ctx.all_findings)
    assert "digest_json; digest_prose_coordination" in csv_text
    assert "auditor_reference" in csv_text


def test_verified_only_mode_gates_and_tallies_gated(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _ProseRoutingClient()
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, markup_verified_only=True,
        qc_work_dir=tmp_path / "qc",
    )
    # The degraded SKIPPED prose entry is suppressed by the conservative mode and
    # accounted as gated — the tally still covers every entry.
    assert ctx.ledger_tally == {"cloud": 2, "gated": 1}
    assert "1 gated (verified-only mode)" in ctx.ledger_tally_line
    assert sum(ctx.ledger_tally.values()) == ctx.finding_count


# --------------------------------------------------------------------------- #
# Arithmetic auditor via critique-transcribed claims (Phase 14)
# --------------------------------------------------------------------------- #


class _ClaimsRoutingClient:
    """Answers digest and critique calls; the critique emits a numeric claim."""

    def __init__(self, claims: list[dict]):
        self.digest_calls = 0
        self.critique_calls = 0
        prose = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120."
        digest_text = prose + "\n\n" + _digest_block([])
        critique_text = "```json\n" + json.dumps({"findings": [], "claims": claims}) + "\n```"

        class _Msgs:
            def create(_self, **kw):
                system = kw.get("system", "")
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    self.critique_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text=critique_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    self.digest_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


def test_arithmetic_auditor_flags_bad_claim_end_to_end(tmp_path):
    src = _make_pdf(tmp_path / "M-101.pdf")
    # The reviewer transcribes a column that should total 540 but is printed 200;
    # the deterministic auditor — not the model — catches the bad arithmetic. The
    # quote ("VAV-3") is on the sheet, so the finding anchors EXACT.
    claim = {"sheet_id": "M-101", "quote": "VAV-3", "kind": "sum",
             "terms": [100, 100], "expected": 540, "note": "column total"}
    client = _ClaimsRoutingClient([claim])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        reference_audit=True, critique=True, qc_markups=False,
    )
    assert client.critique_calls >= 1
    arith = [f for f in ctx.reference_findings
             if f.category == "conflict" and f.verification.status == "DETERMINISTIC"]
    assert len(arith) == 1
    assert "540" in arith[0].text and "200" in arith[0].text   # computed vs stated
    assert arith[0].anchor.status == "EXACT"
    # The report tally counts the relationship that was checked.
    assert ctx.audit_stats.get("arithmetic_checked") == 1
    assert ctx.audit_stats.get("arithmetic_mismatched") == 1
