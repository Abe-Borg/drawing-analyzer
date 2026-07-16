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
from drawing_analyzer.set_identity import IDENTITY_SYSTEM_PROMPT  # noqa: E402
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


# A parse-valid citation verdict (one cited claim per unique ref in these
# fixtures): with the §18.0 gate open, a "clean run" fixture must actually be
# claim-complete or the citation stage honestly holds the run at PARTIAL.
_CITATION_OK = (
    "searched...\n```json\n"
    + json.dumps({"status": "CHECKED_SUPPORTS", "note": "supports", "edition_notes": "e"})
    + "\n```"
)

# A parse-valid set-identity reply (Phase A): on exhaustive runs the identity
# stage is expected, so a "clean run" fixture must answer it or the run is
# honestly held at PARTIAL.
_IDENTITY_OK = (
    "```json\n"
    + json.dumps({
        "disciplines": ["mechanical"],
        "sheet_disciplines": [{"sheet_id": "M-101", "discipline": "mechanical"}],
        "project_type": "office fit-out",
        "set_type": "permit",
        "jurisdiction": "Los Angeles, California, United States",
        "country": "United States",
        "region": "California",
        "language": "en",
        "units": "imperial",
        "adopted_codes": [{
            "code": "CMC", "edition": "2022", "amendment_note": "",
            "quote": "CMC 2022", "source_sheet": "M-101",
        }],
        "confidence": "high",
        "evidence": ["title block"],
        "notes": "",
    })
    + "\n```"
)


class _RoutingClient:
    """One fake client that answers digest, verify, citation, and synthesis calls."""

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
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    # A parse-valid empty read — a bare "ok" would (correctly,
                    # §3.3) hold the critique stage at PARTIAL since Phase 27.
                    return FakeMessage(content=[FakeTextBlock(text='```json\n{"findings":[]}\n```')],
                                       usage=FakeUsage(input_tokens=10, output_tokens=4))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    self.digest_calls += 1
                    return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                       usage=FakeUsage(input_tokens=500, output_tokens=80))
                if system.startswith(CITATION_SYSTEM_PROMPT):
                    return FakeMessage(content=[FakeTextBlock(text=_CITATION_OK)],
                                       usage=FakeUsage(input_tokens=20, output_tokens=8))
                if system == IDENTITY_SYSTEM_PROMPT:
                    return FakeMessage(content=[FakeTextBlock(text=_IDENTITY_OK)],
                                       usage=FakeUsage(input_tokens=30, output_tokens=12))
                # anything else (synthesis prose)
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
    # DA-016: evidence lives in a per-QC-ID directory with a full artifact record
    # and a request.json trail (byte-exact, hashed) — not a flat <id>.png.
    assert f.verification.evidence_png.startswith(f"evidence/{f.qc_id}/")
    assert len(f.verification.evidence) == 1
    assert (tmp_path / "qc" / f.verification.evidence_png).exists()
    assert (tmp_path / "qc" / "evidence" / f.qc_id / "request.json").exists()
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
    # §18.0 (Phase 26B, DA-010): the temporary completeness gate is OPEN — a
    # clean NORMAL exhaustive run now earns COMPLETE ("Exhaustive QC complete").
    assert ctx.qc_status == "COMPLETE"
    assert ctx.qc_status_label == "Exhaustive QC complete"
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
            "verify": 0, "citation": 0, "identity": 0, "other": 0,
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
                    # Fenced, as the contract requires: a bare/unfenced object is
                    # (correctly) a failed parse since the Phase 27 regression fix.
                    return FakeMessage(content=[FakeTextBlock(text='```json\n{"findings":[],"claims":[]}\n```')],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(SYNTHESIS_SYSTEM_PROMPT):
                    calls["synth"] += 1
                    return FakeMessage(content=[FakeTextBlock(text="Overview")],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s.startswith(CITATION_SYSTEM_PROMPT):
                    calls["citation"] += 1
                    # Claim-complete verdict — an empty assessments list would
                    # (correctly, DA-017) hold the citation stage at PARTIAL.
                    return FakeMessage(content=[FakeTextBlock(text=_CITATION_OK)],
                                       usage=FakeUsage(input_tokens=1, output_tokens=1))
                if s == IDENTITY_SYSTEM_PROMPT:
                    calls["identity"] += 1
                    return FakeMessage(content=[FakeTextBlock(text=_IDENTITY_OK)],
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
    # sheet, one cross-sheet call, one synthesis (>=2 sheets), verification,
    # citation, and exactly one set-identity call (Phase A).
    assert client.calls["digest"] == 2
    assert client.calls["critique"] == 4            # 2 sheets x 2 reads
    assert client.calls["cross"] >= 1
    assert client.calls["synth"] == 1
    assert client.calls["verify"] >= 1
    assert client.calls["citation"] >= 1
    assert client.calls["identity"] == 1
    assert cfg.run_identity is True

    # Every stage is recorded; with the §18.0 gate open a clean NORMAL
    # exhaustive run earns COMPLETE.
    stages = {s.stage: s.status for s in ctx.stage_results}
    for name in ("identity", "synthesis", "critique", "cross_qc", "auditors",
                 "prose_harvest", "verification", "citation", "markup"):
        assert name in stages, name
    assert ctx.qc_status == "COMPLETE"
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
    # quote ("VAV-3") is on the sheet (so the finding anchors EXACT) but does not
    # carry the operands, so §17.5 keeps the mismatch UNCERTAIN (model-transcribed).
    claim = {"sheet_id": "M-101", "quote": "VAV-3", "kind": "sum",
             "terms": [100, 100], "expected": 540, "note": "column total"}
    client = _ClaimsRoutingClient([claim])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        reference_audit=True, critique=True, qc_markups=False,
    )
    assert client.critique_calls >= 1
    arith = [f for f in ctx.reference_findings
             if f.category == "conflict" and "auditor_arithmetic" in f.sources]
    assert len(arith) == 1
    assert arith[0].verification.status == "UNCERTAIN"
    assert arith[0].verification.operand_origin == "MODEL_TRANSCRIBED"
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


# --------------------------------------------------------------------------- #
# Run journal + run.log/run_manifest end-to-end (Phase 26A, §18.1–§18.4, DA-024)
# --------------------------------------------------------------------------- #


def test_every_run_carries_a_journal_and_inventory(tmp_path):
    # §18.1: the journal exists for library/API runs including plain standard
    # runs (no QC flags), with the inventory attached for the manifest.
    src = _make_pdf(tmp_path / "M-101.pdf")
    ctx = extract_drawing_context([src], client=_RoutingClient([]), rows=2, cols=2)

    journal = ctx.run_journal
    assert journal is not None and journal.run_id.startswith("RUN-")
    codes = [e.event_code for e in journal.events]
    assert codes[0] == "RUN_START"
    assert "INPUT_ACCEPTED" in codes
    assert "SHEET_DIGESTED" in codes
    assert codes[-1] == "RUN_END"
    assert journal.ended_at is not None
    # final_status is the RUN-level terminal outcome — a clean standard run is
    # COMPLETE even though its QC status is NOT_REQUESTED, so a manifest
    # consumer can tell "completed, no QC" apart from anything else (§18.2).
    assert journal.final_status == "COMPLETE"
    assert ctx.qc_status == "NOT_REQUESTED"
    # Sequences are contiguous even with the digest worker pool involved.
    assert [e.sequence for e in journal.events] == list(range(1, len(codes) + 1))
    # The classified inventory rides the context (manifest source of truth).
    docs = ctx.input_inventory.documents
    assert len(docs) == 1 and docs[0].accepted and docs[0].source_id == "SRC-0001"
    # Environment identity was captured (§18.2).
    assert journal.environment.get("model")
    assert journal.environment.get("coordinate_space") == "PAGE_VIEW_V2"


def test_all_inputs_rejected_run_still_journals(tmp_path):
    # §18.1: an all-input-failure run leaves an honest journal — INPUT_REJECTED
    # per file, a FAILED RUN_END, and a renderable run.log.
    bad = tmp_path / "not-a-pdf.pdf"
    bad.write_text("hello")
    ctx = extract_drawing_context([bad, tmp_path / "missing.pdf"], client=None)

    journal = ctx.run_journal
    assert journal is not None
    codes = [e.event_code for e in journal.events]
    assert codes.count("INPUT_REJECTED") == 2
    assert codes[-1] == "RUN_END"
    assert journal.final_status == "FAILED"
    assert ctx.sheet_count == 0
    from drawing_analyzer.run_journal import render_run_log

    log = render_run_log(ctx)
    assert "FAILED — no sheets were analyzed" in log
    assert "not-a-pdf.pdf" in log
    # No absolute test path leaks into the rendered log (§18.2).
    assert str(tmp_path) not in log


def test_blocked_run_attaches_journal(tmp_path, monkeypatch):
    # §10.7 preflight block: the early return still carries journal + inventory.
    import drawing_analyzer.pipeline as pl

    monkeypatch.setattr(
        pl, "check_set_limits", lambda docs, confirmed=False: "set too large (test)"
    )
    src = _make_pdf(tmp_path / "M-101.pdf")
    ctx = extract_drawing_context([src], client=_RoutingClient([]))

    assert any(e.event_code == "RUN_BLOCKED" for e in ctx.run_journal.events)
    assert ctx.run_journal.final_status == "FAILED"
    assert ctx.input_inventory is not None
    assert any("set too large" in e for e in ctx.errors)


def test_exhaustive_run_journal_receipts_and_exported_run_log(tmp_path):
    # The §18.2/§18.4 end-to-end: stage events mirror the recorded StageResults,
    # MARKUP_RECEIPTS mirrors the artifact-backed receipts, and the exported
    # run.log / run_manifest.json agree with the context.
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_VAV_FINDING])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )

    journal = ctx.run_journal
    ended = {e.stage for e in journal.events if e.event_code == "STAGE_END"}
    # Every recorded stage result has a matching STAGE_END event (§18.2)…
    assert {sr.stage for sr in ctx.stage_results if sr.status != "NOT_REQUESTED"} <= ended
    # …plus the digest phase itself (which has no StageResult by design).
    assert "digest" in ended

    receipts = [e for e in journal.events if e.event_code == "MARKUP_RECEIPTS"]
    assert len(receipts) == 1
    fields = receipts[0].fields
    assert int(fields["expected"]) == len(ctx.markup_run.placements)
    terminal = sum(1 for r in ctx.markup_run.receipts if r.status in ("WRITTEN", "INDEXED", "FAILED"))
    assert int(fields["written"]) + int(fields["indexed"]) + int(fields["failed"]) == terminal
    assert fields["coverage"] == ctx.coverage_status

    from drawing_analyzer.export import write_drawing_export

    folder = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101.pdf"])
    log = (folder / "run.log").read_text(encoding="utf-8")
    assert journal.run_id in log
    # Stage table rows and the receipt-derived ledger line (§18.2).
    for stage in ("critique", "auditors", "verification", "markup"):
        assert stage in log
    assert "markup coverage: COMPLETE" in log
    assert "Ledger " in log
    # Usage totals in the manifest equal the context's derived sums (§15.6).
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["usage"]["total_input_tokens"] == ctx.total_input_tokens
    assert manifest["usage"]["total_output_tokens"] == ctx.total_output_tokens
    assert manifest["run"]["run_id"] == journal.run_id
    assert manifest["status"]["qc_status"] == ctx.qc_status
    assert manifest["prose_accounting"] == ctx.prose_accounting
    # Sources come from the real inventory — ids, never paths (§10.4).
    assert manifest["sources"][0]["source_id"] == "SRC-0001"
    assert str(tmp_path) not in json.dumps(manifest)
    # The artifact list covers the reviewed PDF and the evidence tree.
    paths = {a["path"] for a in manifest["artifacts"]}
    assert "M-101_reviewed.pdf" in paths
    assert any(p.startswith("evidence/") for p in paths)
    assert "run.log" in paths and "run_manifest.json" not in paths


def test_geometry_omission_sink_merges_render_facts_into_prescan(tmp_path):
    # On a cache-enabled run the prescan captures geometry without rasterizing
    # (omitted_tile_count unknown); a freshly-rendered MISS must still merge
    # its blank-tile count onto the prescan record — the I-1 disclosure §18.2
    # promises for every sheet rendered THIS run — while never growing the
    # list and leaving true cache hits honestly None.
    from types import SimpleNamespace

    from drawing_analyzer.models import SheetGeometry, SheetRef
    from drawing_analyzer.pipeline import _GeometryOmissionSink

    ref_a = SheetRef(pdf_path=tmp_path / "A.pdf", page_index=0, source_name="A.pdf",
                     page_count=1, source_id="SRC-0001")
    ref_b = SheetRef(pdf_path=tmp_path / "B.pdf", page_index=0, source_name="B.pdf",
                     page_count=1, source_id="SRC-0002")
    prescan = [
        SheetGeometry(ref=ref_a, page_width_pt=612, page_height_pt=792, rows=2, cols=2),
        SheetGeometry(ref=ref_b, page_width_pt=612, page_height_pt=792, rows=2, cols=2),
    ]
    assert prescan[0].omitted_tile_count is None

    sink = _GeometryOmissionSink(prescan)
    sink.append(
        SheetGeometry(ref=ref_a, page_width_pt=612, page_height_pt=792,
                      rows=2, cols=2, omitted_tile_count=3)
    )
    assert prescan[0].omitted_tile_count == 3       # miss: render fact merged
    assert prescan[1].omitted_tile_count is None    # hit: honestly unknown
    assert len(prescan) == 2                        # never grows the list


def test_gate_open_never_masks_a_degraded_required_stage(tmp_path):
    # §18.0 permanent phase-gate regression (DA-010): opening the completeness
    # gate must NOT let a run with a degraded required stage reach COMPLETE.
    # Here the citation stage leaves the cited claim unchecked (an empty
    # assessments response — the DA-017 claim-completeness rule holds it at
    # PARTIAL), so the run stays PARTIAL even though every other stage is clean.
    src = _make_pdf(tmp_path / "M-101.pdf")

    class _CitationIncomplete(_RoutingClient):
        def __init__(self):
            super().__init__([_VAV_FINDING])
            inner = self.messages

            class _Msgs:
                def create(_self, **kw):
                    if str(kw.get("system", "")).startswith(CITATION_SYSTEM_PROMPT):
                        return FakeMessage(
                            content=[FakeTextBlock(text='{"assessments":[]}')],
                            usage=FakeUsage(input_tokens=1, output_tokens=1),
                        )
                    return inner.create(**kw)

            self.messages = _Msgs()

    ctx = extract_drawing_context(
        [src], client=_CitationIncomplete(), rows=2, cols=2,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    stages = {s.stage: s.status for s in ctx.stage_results}
    assert stages["citation"] == "PARTIAL"
    assert ctx.qc_status == "PARTIAL"          # never COMPLETE with a degraded stage
    assert ctx.qc_status_label == "Completed with QC warnings"
    # The standard deliverable still shipped (I-3).
    assert ctx.combined_text.strip()
