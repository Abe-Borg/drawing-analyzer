"""Phase 27 §19.3 — the opt-in live API canary.

Every test here is marked ``network``: it is **skipped unless a real
``ANTHROPIC_API_KEY`` is set** (see ``conftest.py``) and is deliberately
excluded from CI, which runs hermetically. Run it before a release:

    ANTHROPIC_API_KEY=sk-ant-... python -m pytest -m network -rs -s tests/test_live_api_canary.py

What it proves against the live service (small, cheap, non-proprietary
fixtures only):

- the digest request schema is still accepted and the structured-findings
  contract still parses (one 1-page vision call);
- the critique structured-output contract completes both self-consistency
  reads;
- the pinned server-side web-search tool type is still accepted and the
  citation parser handles a real tool-result stream;
- the Files API upload → consume → delete lifecycle works and cleans up; and
- a live run's exported ``run.log`` / ``run_manifest.json`` contain no key.

Each test prints the model/tool identifiers it exercised so the release
record (docs/RELEASE_ACCEPTANCE_TEMPLATE.md) can pin the observed versions.
Wall time is recorded descriptively, never gated (§19.7).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

pytestmark = pytest.mark.network

_PAGE_W, _PAGE_H = 792.0, 612.0


def _make_sheet(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    page.insert_text((72, 100), "VAV-3 SERVES ROOM 120")
    page.insert_text((72, 128), "SEE DRAWING M-999 FOR CONTINUATION")
    page.insert_text((_PAGE_W - 150, _PAGE_H - 60), "M-101", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _live_client():
    from drawing_analyzer.client import get_client

    return get_client()


def test_live_digest_and_export_redaction(tmp_path):
    """One real digest call; the exported log/manifest carry no key (§19.3)."""
    from drawing_analyzer.export import write_drawing_export
    from drawing_analyzer.pipeline import extract_drawing_context

    src = _make_sheet(tmp_path / "M-101.pdf")
    ctx = extract_drawing_context([src], client=_live_client(), rows=2, cols=2)

    assert ctx.ok_sheet_count == 1, ctx.errors
    assert ctx.combined_text.strip()
    assert ctx.total_input_tokens > 0 and ctx.total_output_tokens > 0
    digest_recs = [r for r in ctx.run_usage.records if r.stage_family == "digest"]
    assert digest_recs and digest_recs[0].transport == "REAL_TIME"
    print(f"\n[canary] digest model: {digest_recs[0].model}")

    export = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101.pdf"])
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    assert key, "network tests need a real key"
    for name in ("run.log", "run_manifest.json", "report.html"):
        content = (export / name).read_text(encoding="utf-8")
        assert key not in content, f"API key leaked into {name}"
        assert "sk-ant-" not in content, f"key-shaped string in {name}"


def test_live_critique_structured_output_compliance(tmp_path):
    """Both self-consistency reads return parse-valid structured output."""
    from drawing_analyzer.critique import critique_sheet_self_consistent
    from drawing_analyzer.models import SheetRef
    from drawing_analyzer.render import render_sheet

    src = _make_sheet(tmp_path / "M-101.pdf")
    doc = pymupdf.open(str(src))
    try:
        ref = SheetRef(pdf_path=src, page_index=0, source_name=src.name,
                       page_count=doc.page_count, source_id="SRC-0001")
        rendered = render_sheet(doc[0], ref, rows=2, cols=2)
    finally:
        doc.close()

    res = critique_sheet_self_consistent(rendered, client=_live_client(), cache=None)
    assert res.error is None, res.error          # structured-output compliance
    assert res.completed_runs == res.requested_runs == 2
    assert res.input_tokens > 0
    print(f"\n[canary] critique reads: {res.completed_runs}/{res.requested_runs}")


def test_live_identity_call(tmp_path):
    """One real set-identity call parses against the live service (Phase A).

    The identity content is the model's judgement — the canary asserts only the
    contract: a parseable, bounded SetIdentity comes back (fields may be empty
    on this minimal fixture). The review-plan call shares the same request
    shape (plain text ``messages.create`` + fenced JSON, already canaried by
    the digest/critique tests above), so it needs no second canary.
    """
    from drawing_analyzer.models import SetIdentity, SheetRef
    from drawing_analyzer.digest import SheetDigest
    from drawing_analyzer.set_identity import identify_set

    src = _make_sheet(tmp_path / "M-101.pdf")
    ref = SheetRef(pdf_path=src, page_index=0, source_name=src.name,
                   page_count=1, source_id="SRC-0001")
    sheet = SheetDigest(
        ref=ref,
        text="Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120.",
    )

    class _Geom:
        def __init__(self, r):
            self.ref = r
            self.sheet_text = "VAV-3 SERVES ROOM 120\nPER CMC 2022\nM-101"

    res = identify_set([sheet], [_Geom(ref)], client=_live_client())
    assert res.error is None, res.error
    assert isinstance(res.identity, SetIdentity)
    assert res.input_tokens > 0 and res.output_tokens > 0
    print(f"\n[canary] identity model: {res.model_used}; "
          f"disciplines: {list(res.identity.disciplines)}")


def test_live_citation_web_search_tool_accepted():
    """The pinned web-search tool type is accepted and the parser copes with a
    real tool-result stream. The verdict content is the model's judgement — the
    canary asserts only vocabulary + claim-completeness, never a particular
    SUPPORTS/MISMATCH outcome."""
    from drawing_analyzer.citation_check import check_citations, web_search_tool
    from drawing_analyzer.models import Finding

    tool = web_search_tool()
    print(f"\n[canary] web-search tool type: {tool['type']}")

    finding = Finding(
        sheet_id="M-101", source_name="M-101.pdf", page_index=0,
        category="code", severity="medium",
        text="Sprinkler design density cited per NFPA 13 for an ordinary hazard space.",
        source_quote="NFPA 13", refs=["NFPA 13"], source_id="SRC-0001",
    )
    res = check_citations([finding], [], client=_live_client())
    assert res.error is None, res.error
    assessments = finding.citations
    assert assessments, "the cited claim was not assessed"
    assert all(
        a.status in ("CHECKED_SUPPORTS", "CHECKED_MISMATCH", "UNCHECKED", "UNRESOLVABLE")
        for a in assessments
    )
    assert any(finding.id in a.claim_finding_ids for a in assessments)


def test_live_files_api_upload_and_cleanup(tmp_path):
    """Upload a sheet's images, then delete them; deletion must stick."""
    from drawing_analyzer.file_upload import delete_files, upload_sheet_images
    from drawing_analyzer.models import SheetRef
    from drawing_analyzer.render import render_sheet

    src = _make_sheet(tmp_path / "M-101.pdf")
    doc = pymupdf.open(str(src))
    try:
        ref = SheetRef(pdf_path=src, page_index=0, source_name=src.name,
                       page_count=doc.page_count, source_id="SRC-0001")
        rendered = render_sheet(doc[0], ref, rows=2, cols=2)
    finally:
        doc.close()

    client = _live_client()
    upload = upload_sheet_images(client, rendered)
    assert upload.file_ids, "upload produced no file ids"
    print(f"\n[canary] uploaded {len(upload.file_ids)} file(s)")

    delete_files(client, upload.file_ids)
    # Deletion is verified by retrieval failing (404/not-found) for each id.
    for fid in upload.file_ids:
        try:
            client.beta.files.retrieve_metadata(fid)
        except Exception as exc:  # noqa: BLE001 - any not-found/gone shape passes
            msg = str(exc).lower()
            assert "not" in msg or "404" in msg or "gone" in msg, exc
        else:
            pytest.fail(f"file {fid} still retrievable after delete_files")


def test_live_versions_recorded():
    """Print the environment identity for the release record (§19.3)."""
    from drawing_analyzer.run_journal import collect_environment

    env = collect_environment()
    print("\n[canary] environment identity:")
    for key in sorted(env):
        print(f"  {key} = {env[key]}")
    digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    print(f"  identity sha256 = {digest[:16]}…")
    assert env.get("anthropic_sdk") and env.get("pymupdf")
