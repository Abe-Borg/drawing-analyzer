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

from drawing_analyzer.citation_check import CITATION_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.cross_qc import CROSS_QC_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.synthesis import SYNTHESIS_SYSTEM_PROMPT  # noqa: E402
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
    # §15.5 temporary completeness gate: a clean exhaustive run is deliberately
    # PARTIAL — never COMPLETE — until Phases 24–26 land. NORMAL config (no
    # explicit stage was disabled).
    assert ctx.qc_status == "PARTIAL"
    assert ctx.configuration_kind == "NORMAL"


# --------------------------------------------------------------------------- #
# Flag matrix
# --------------------------------------------------------------------------- #


def test_standard_run_persists_findings_and_text(tmp_path):
    # Product invariant (DA-012 §15.2): a standard run — neither QC checkbox — still
    # retains the parsed digest findings and each sheet's extracted text, binds them
    # to source identity, and anchors them offline *for free*, so they show in the
    # report and export. It must NOT run any paid QC stage (no verify/critique/
    # citation/prose-structuring/markup). Reverses the old "leaves findings empty"
    # assertion, which encoded the discard defect rather than the requirement.
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context([src], client=client, rows=2, cols=2)   # no QC flags

    # The digest's finding is retained and offline-anchored (its quote is on-sheet).
    assert len(ctx.findings) == 1
    f = ctx.findings[0]
    assert f.anchor.status == "EXACT" and f.anchor.rect_pdf is not None
    assert f.qc_id == "QC-001"                       # positional id assigned, still free
    assert f.source_id                               # bound to host source identity
    # No paid QC stage ran: not verified, no deterministic auditors, no markups.
    assert f.verification.status == "SKIPPED"
    assert ctx.reference_findings == []
    assert ctx.reviewed_pdf_paths == []
    assert client.verify_calls == 0
    # Sheet text/geometry retained for the findings + sheet_text exports.
    assert len(ctx.sheet_geometries) == 1
    assert ctx.sheet_geometries[0].sheet_text != ""
    # Standard mode is not a QC mode: overall status is NOT_REQUESTED, no ink tally.
    assert ctx.qc_status == "NOT_REQUESTED"
    assert ctx.coverage_status == "NOT_REQUESTED"
    assert ctx.ledger_tally == {}


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
    # The §18 tally describes PDF ink; with markups off it must not report
    # clouds that were never written to any PDF.
    assert ctx.ledger_tally == {}
    assert ctx.ledger_tally_line == ""
    # Deterministic audit is an additive offline diagnostic, not a QC effort mode
    # (§3.1): the overall status stays NOT_REQUESTED, and it made no model calls
    # beyond the digest the user already asked for (DA-013).
    assert ctx.qc_status == "NOT_REQUESTED"
    assert ctx.run_configuration.deterministic_audit_only is True
    assert ctx.run_configuration.run_prose_harvest is False


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
    # verify_findings=False is an explicit expert override that disables only the
    # verification stage; the rest of the exhaustive stack still runs (DA-010), so
    # the deterministic auditors also fire (the M-999 stale ref).
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        qc_markups=True, verify_findings=False, markup_verified_only=False,
        qc_work_dir=tmp_path / "qc",
    )
    assert client.verify_calls == 0
    assert ctx.findings[0].anchor.status == "EXACT"
    assert ctx.findings[0].verification.status == "SKIPPED"
    # include-unverified inks the SKIPPED model finding *and* the DETERMINISTIC
    # auditor finding, each a cloud + QC tag: 2 clouds + 2 tags = 4.
    assert _annot_count(ctx.reviewed_pdf_paths[0]) == 4
    # Disabling a normally-required exhaustive stage is a debug override (§15.1).
    assert ctx.configuration_kind == "DEBUG_OVERRIDE"
    assert ctx.qc_status == "PARTIAL"


# --------------------------------------------------------------------------- #
# §15.1 — qc_markups=True resolves to (and runs) the full exhaustive stack
# --------------------------------------------------------------------------- #


class _CountingClient:
    """Fake client that counts calls per stage and answers each with valid output."""

    def __init__(self, findings: list[dict]):
        self.calls = {
            "digest": 0, "critique": 0, "cross": 0, "synth": 0,
            "verify": 0, "citation": 0, "other": 0,
        }
        prose = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120."
        digest_text = prose + "\n\n" + _digest_block(findings)
        calls = self.calls

        class _Msgs:
            def create(_self, **kw):
                s = kw.get("system", "")
                if s == VERIFY_SYSTEM_PROMPT:
                    calls["verify"] += 1
                    return FakeMessage(content=[FakeTextBlock(text='{"verdict":"CONFIRMED","note":"x"}')],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(DIGEST_SYSTEM_PROMPT):
                    calls["digest"] += 1
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(CRITIQUE_SYSTEM_PROMPT):
                    calls["critique"] += 1
                    return FakeMessage(content=[FakeTextBlock(text='```json\n{"findings":[]}\n```')],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(CROSS_QC_SYSTEM_PROMPT):
                    calls["cross"] += 1
                    return FakeMessage(content=[FakeTextBlock(text='{"findings":[],"claims":[]}')],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(SYNTHESIS_SYSTEM_PROMPT):
                    calls["synth"] += 1
                    return FakeMessage(content=[FakeTextBlock(text="Overview")],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(CITATION_SYSTEM_PROMPT):
                    calls["citation"] += 1
                    return FakeMessage(content=[FakeTextBlock(text='{"assessments":[]}')],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                calls["other"] += 1
                return FakeMessage(content=[FakeTextBlock(text="ok")],
                                   usage=FakeUsage(input_tokens=1, output_tokens=1))

        self.messages = _Msgs()


def test_qc_markups_resolves_and_runs_exhaustive_stack(tmp_path):
    # DA-010 / §15.1: the ordinary ``qc_markups=True`` contract must resolve to the
    # exhaustive configuration AND actually run every required stage — not just the
    # digest → markup path the GUI's checkbox used to invoke.
    a = _make_pdf(tmp_path / "M-101.pdf")
    b = _make_pdf(tmp_path / "M-102.pdf")
    client = _CountingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [a, b], client=client, rows=2, cols=2,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    cfg = ctx.run_configuration
    assert cfg.exhaustive_qc and cfg.run_critique and cfg.critique_reads == 2
    assert cfg.run_cross_qc and cfg.run_auditors and cfg.run_citation and cfg.run_markup

    # The stages actually executed (not just resolved on): two critique reads per
    # sheet, one cross-sheet call, one synthesis (>=2 sheets), verification, citation.
    assert client.calls["digest"] == 2
    assert client.calls["critique"] == 4            # 2 sheets x 2 reads
    assert client.calls["cross"] >= 1
    assert client.calls["synth"] == 1
    assert client.calls["verify"] >= 1
    assert client.calls["citation"] >= 1

    # Every stage is recorded, and the clean exhaustive run is gated to PARTIAL.
    stages = {s.stage: s.status for s in ctx.stage_results}
    for name in ("synthesis", "critique", "cross_qc", "auditors", "prose_harvest",
                 "verification", "citation", "markup"):
        assert name in stages, name
    assert ctx.qc_status == "PARTIAL"
    assert ctx.configuration_kind == "NORMAL"


def test_audit_only_makes_no_incremental_api_calls(tmp_path):
    # DA-013 / §15.3: the deterministic-audit-only path runs the auditors over the
    # already-extracted text/geometry and makes ZERO model calls beyond the digest —
    # in particular it never structures prose.
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _CountingClient([_VAV_FINDING])
    ctx = extract_drawing_context([src], client=client, rows=2, cols=2, reference_audit=True)
    assert client.calls["digest"] == 1
    for stage in ("critique", "cross", "synth", "verify", "citation", "other"):
        assert client.calls[stage] == 0, (stage, client.calls)
    # Auditors still fired off the retained geometry (the stale M-999 pointer).
    assert len(ctx.reference_findings) == 1
    assert ctx.qc_status == "NOT_REQUESTED"


def test_exhaustive_run_usage_is_derived_and_per_stage(tmp_path):
    # §15.6: the run's token totals are DERIVED from an append-only usage ledger —
    # every stage records independently, so harvest and verify both appear (the old
    # ``v_in, v_out = vres…`` overwrite dropped harvest) and the grand total equals
    # the exact sum of the records.
    a = _make_pdf(tmp_path / "M-101.pdf")
    b = _make_pdf(tmp_path / "M-102.pdf")
    client = _CountingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [a, b], client=client, rows=2, cols=2, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    ru = ctx.run_usage
    assert ru is not None
    # Totals are the exact sum of the records — never a mutable running counter.
    assert ctx.total_input_tokens == sum(r.input_tokens for r in ru.records)
    assert ctx.total_output_tokens == sum(r.output_tokens for r in ru.records)
    fams = set(ru.by_family())
    for needle in ("digest", "critique", "cross_qc", "synthesis", "verify", "citation"):
        assert needle in fams, needle
    # harvest and verify are BOTH present as independent records (no overwrite).
    assert "harvest" in fams and "verify" in fams
    assert ctx.total_estimated_cost is not None       # Opus is priced


def test_cached_digest_records_zero_billed_tokens(tmp_path):
    # A cache hit contributes zero current-run billed tokens but records the
    # cache-hit metadata (§6.3): the second run's digest is a CACHE record.
    from drawing_analyzer.digest_cache import DigestCache

    src = _make_pdf(tmp_path / "M-101.pdf")
    cache = DigestCache(None, persist=False)
    c1 = _RoutingClient([_VAV_FINDING])
    ctx1 = extract_drawing_context([src], client=c1, rows=2, cols=2, cache=cache)
    assert ctx1.total_input_tokens > 0                 # first run paid for the digest

    c2 = _RoutingClient([_VAV_FINDING])
    ctx2 = extract_drawing_context([src], client=c2, rows=2, cols=2, cache=cache)
    assert c2.digest_calls == 0                        # served from cache, no API call
    digest_recs = [r for r in ctx2.run_usage.records if r.stage_family == "digest"]
    assert digest_recs and all(r.transport == "CACHE" for r in digest_recs)
    assert all(r.cache_hit and r.input_tokens == 0 for r in digest_recs)
    assert ctx2.run_usage.cache_hits >= 1
    assert ctx2.total_input_tokens == 0                # a fully-cached re-run bills nothing


def test_report_and_context_usage_totals_agree(tmp_path):
    # GUI/report/context totals all derive from the one ledger, so they agree (§15.7).
    from drawing_analyzer.html_report import build_html_report

    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _CountingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    html = build_html_report(ctx, source_names=["M-101.pdf"])
    assert "Token usage &amp; estimated cost by stage" in html
    # The report's per-family rows sum to the context's derived total.
    assert sum(g["input_tokens"] for g in ctx.usage_by_family.values()) == ctx.total_input_tokens


def test_verification_stage_skipped_valid_when_no_eligible_findings(tmp_path):
    # The verifier returns normally with everything SKIPPED (it does not raise) when
    # nothing is eligible. An exhaustive run whose only finding is the DETERMINISTIC
    # auditor stale-ref (never crop-verified) leaves the single-crop verifier nothing
    # to judge, so the verification stage is SKIPPED_VALID — not a false COMPLETE —
    # and no verify call is made.
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _CountingClient([])                      # no model findings from the digest
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    assert not ctx.findings                            # no model findings
    assert len(ctx.reference_findings) == 1            # the deterministic M-999 ref
    stages = {s.stage: s.status for s in ctx.stage_results}
    assert stages["verification"] == "SKIPPED_VALID"
    assert client.calls["verify"] == 0


def test_standard_run_exports_findings_and_sheet_text(tmp_path):
    # DA-012 / §15.2: a standard run's folder export always ships findings.json,
    # findings.csv, and sheet_text/ — and the index is NOT mislabeled "QC review"
    # (that block used to only render for QC runs; geometry is now always retained).
    import json

    from drawing_analyzer.export import write_drawing_export

    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context([src], client=client, rows=2, cols=2)   # no QC flags
    folder = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101.pdf"])

    assert (folder / "findings.json").exists()
    data = json.loads((folder / "findings.json").read_text())
    assert len(data["findings"]) == 1                      # the retained digest finding
    assert (folder / "findings.csv").read_bytes()[:3] == b"\xef\xbb\xbf"
    assert (folder / "sheet_text").is_dir()
    assert any((folder / "sheet_text").iterdir())

    index = (folder / "00_index.md").read_text()
    assert "### Findings & sheet text" in index            # honest standard-run label
    assert "### QC review" not in index                    # not a QC run
    assert "QC status" not in index                        # only shown for exhaustive
    # A standard run wrote no reviewed PDFs and no QC status.
    assert not any(folder.glob("*_reviewed*.pdf"))


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

    # Coverage (Phase 21, DA-007): the tally is derived from artifact-backed
    # receipts, not intention. 3 entries: the VERIFIED model finding (cloud), the
    # degraded prose item (margin callout), and the DETERMINISTIC reference
    # finding (cloud) — every one proven in the reopened PDF, so coverage COMPLETE.
    assert ctx.finding_count == 3
    assert ctx.coverage_status == "COMPLETE"
    assert ctx.ledger_tally == {"cloud": 2, "margin": 1}
    assert sum(ctx.ledger_tally.values()) == ctx.finding_count
    assert ctx.ledger_tally_line == (
        "Ledger 3: 2 clouded, 1 margin, 0 rejected (indexed); coverage COMPLETE"
    )
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


# --------------------------------------------------------------------------- #
# Set-level synthesis conflicts → Drawing_Set_Review_Notes.pdf (Phase 22 §14.8)
# --------------------------------------------------------------------------- #


def _make_clean_pdf(path: Path, sheet_id: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "EQUIPMENT SCHEDULE - SEE PLAN")
    page.insert_text((650, 560), sheet_id)      # title-block sheet id (bottom-right)
    doc.save(str(path))
    doc.close()
    return path


class _SetLevelRoutingClient:
    """Two clean sheets; the cross-sheet synthesis reports a conflict that names no
    in-set sheet — the §14.8 set-level case. Digest/critique find nothing else."""

    def __init__(self):
        digest_text = "Sheet - Mechanical - Plan\nEquipment schedule shown.\n\n" + _digest_block([])
        critique_text = "```json\n" + json.dumps({"findings": [], "claims": []}) + "\n```"
        synth_text = (
            "Drawing Set Overview\n\n"
            "The set is largely coherent. However, the specified fire pump conflicts "
            "with the schedule and no single sheet in the set resolves which governs."
        )

        class _Msgs:
            def create(_self, **kw):
                system = kw.get("system", "")
                if system == SYNTHESIS_SYSTEM_PROMPT:
                    return FakeMessage(content=[FakeTextBlock(text=synth_text)],
                                       usage=FakeUsage(input_tokens=300, output_tokens=60))
                if system == VERIFY_SYSTEM_PROMPT:
                    return FakeMessage(content=[FakeTextBlock(text='{"verdict":"CONFIRMED","note":"x"}')],
                                       usage=FakeUsage(input_tokens=40, output_tokens=8))
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    return FakeMessage(content=[FakeTextBlock(text=critique_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


def test_set_level_synthesis_conflict_routes_to_review_notes_pdf(tmp_path):
    # DA-023 end to end: a synthesis conflict that names no in-set sheet is not
    # dropped — it becomes a set-level finding written to Drawing_Set_Review_Notes.pdf
    # (its own artifact + reconciled receipts), never pinned onto a source sheet.
    srcs = [_make_clean_pdf(tmp_path / "M-101.pdf", "M-101"),
            _make_clean_pdf(tmp_path / "M-102.pdf", "M-102")]
    client = _SetLevelRoutingClient()
    ctx = extract_drawing_context(
        srcs, client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, markup_verified_only=False,
        synthesize=True, qc_work_dir=tmp_path / "qc",
    )

    # A set-level finding exists, belongs to no source, and sorts last (§12.4).
    set_level = [f for f in ctx.all_findings
                 if (f.anchor_hint or "").upper() == "SET_INDEX" and not f.source_id]
    assert len(set_level) == 1
    assert "conflicts with the schedule" in set_level[0].text
    assert set_level[0].qc_id == max(f.qc_id for f in ctx.all_findings)

    # The dedicated artifact was written and its coverage reconciled COMPLETE.
    names = [p.name for p in ctx.reviewed_pdf_paths]
    assert "Drawing_Set_Review_Notes.pdf" in names
    assert ctx.coverage_status == "COMPLETE"
    assert ctx.ledger_tally.get("review_notes") == 1
    # The set-level statement never leaked onto a source reviewed PDF.
    assert not any(e.startswith("Prose harvest:") for e in ctx.errors)


class _SourceAndSetLevelClient:
    """Two sheets: the digest reports a real finding on each sheet (→ a source
    reviewed PDF), and the synthesis reports a conflict naming no in-set sheet
    (→ a set-level note)."""

    def __init__(self):
        prose = "Sheet - Mechanical - Plan\nEquipment schedule shown."
        digest_text = prose + "\n\n" + _digest_block([{
            "sheet_id": "M-1", "category": "code", "severity": "high",
            "text": "Schedule value is wrong.", "source_quote": "EQUIPMENT SCHEDULE",
        }])
        critique_text = "```json\n" + json.dumps({"findings": [], "claims": []}) + "\n```"
        synth_text = ("Overview.\n\nThe specified fire pump conflicts with the schedule "
                      "and no single sheet in the set resolves which governs.")

        class _Msgs:
            def create(_self, **kw):
                system = kw.get("system", "")
                if system == SYNTHESIS_SYSTEM_PROMPT:
                    return FakeMessage(content=[FakeTextBlock(text=synth_text)], usage=FakeUsage())
                if system == VERIFY_SYSTEM_PROMPT:
                    return FakeMessage(content=[FakeTextBlock(text='{"verdict":"CONFIRMED","note":"x"}')],
                                       usage=FakeUsage())
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    return FakeMessage(content=[FakeTextBlock(text=critique_text)], usage=FakeUsage())
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)], usage=FakeUsage())
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


def test_set_notes_writer_failure_keeps_source_reviewed_pdfs(tmp_path, monkeypatch):
    # Review finding: a set-notes writer exception must NOT discard the per-source
    # reviewed PDFs already written to disk. The source result is committed before
    # the notes writer runs; a notes failure only rolls coverage to INCOMPLETE.
    import drawing_analyzer.annotate as A

    srcs = [_make_clean_pdf(tmp_path / "M-101.pdf", "M-101"),
            _make_clean_pdf(tmp_path / "M-102.pdf", "M-102")]

    def _boom(*a, **k):
        raise RuntimeError("notes save failed")

    # The pipeline does `from .annotate import write_set_review_notes_pdf` at call
    # time, so patching the annotate module's attribute is what the local import sees.
    monkeypatch.setattr(A, "write_set_review_notes_pdf", _boom, raising=True)
    ctx = extract_drawing_context(
        srcs, client=_SourceAndSetLevelClient(), rows=2, cols=2,
        reference_audit=True, qc_markups=True, markup_verified_only=False,
        synthesize=True, qc_work_dir=tmp_path / "qc",
    )
    # The notes writer failed → recorded + INCOMPLETE, but the source reviewed PDFs
    # (written before the notes call) are still listed, not discarded.
    assert any("Set-level review notes" in e for e in ctx.errors)
    assert ctx.coverage_status == "INCOMPLETE"
    assert any(p.name.endswith("_reviewed.pdf") for p in ctx.reviewed_pdf_paths)
