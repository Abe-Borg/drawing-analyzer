"""Mid-run source mutation detection (Phase 18C, DA-001 §10.6).

If a source PDF's bytes change between the inventory snapshot and the markup
write, applying anchors computed from the earlier revision would place ink on
the wrong content. These tests cover the pure re-hash check and the end-to-end
guard: a mutated source is excluded from markup, recorded on ``ctx.errors``, and
flagged on ``ctx.mutated_sources``, while the good files still get reviewed PDFs.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

from drawing_analyzer.render import inspect_inputs
from drawing_analyzer.source_registry import (
    SourceDocument,
    content_changed,
    content_sha256,
    detect_mutations,
)


def _pdf(path: Path, text: str = "ORIGINAL", *, pages: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page(width=612, height=792).insert_text((72, 72), f"{text} p{i + 1}")
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------- #
# The pure re-hash check
# --------------------------------------------------------------------------- #


def test_content_changed_detects_mutation(tmp_path):
    p = _pdf(tmp_path / "M-101.pdf", "ORIGINAL")
    (doc,) = inspect_inputs([p]).accepted_documents
    assert content_changed(doc) == ""            # unchanged → clean

    # Rewrite the file with different content.
    _pdf(p, "REPLACED WITH SOMETHING ELSE")
    reason = content_changed(doc)
    assert reason and "changed" in reason


def test_content_changed_on_deleted_file(tmp_path):
    p = _pdf(tmp_path / "M-101.pdf")
    (doc,) = inspect_inputs([p]).accepted_documents
    p.unlink()
    assert "no longer readable" in content_changed(doc)


def test_content_changed_tolerates_stat_only_touch(tmp_path):
    # A touch that bumps mtime but leaves the bytes identical is NOT a mutation:
    # the fast stat gate misses, but the full re-hash confirms same content.
    p = _pdf(tmp_path / "M-101.pdf")
    sha, size, _ = content_sha256(p)
    doc = SourceDocument(
        source_id="SRC-0001", pdf_path=p, display_name="M-101.pdf", input_order=1,
        status="ACCEPTED", page_count=1, content_sha256=sha, byte_size=size,
        initial_mtime_ns=1,          # deliberately wrong mtime → forces re-hash
    )
    assert content_changed(doc) == ""            # bytes match → not a mutation


def test_content_changed_no_snapshot_is_never_flagged(tmp_path):
    # A hand-built doc with no snapshot hash (e.g. a test fixture) can't be
    # compared, so it is never spuriously reported as changed.
    p = _pdf(tmp_path / "M-101.pdf")
    doc = SourceDocument(source_id="SRC-0001", pdf_path=p, display_name="M-101.pdf",
                         input_order=1, status="ACCEPTED", page_count=1)
    assert content_changed(doc) == ""


def test_detect_mutations_maps_changed_sources(tmp_path):
    a = _pdf(tmp_path / "a" / "M-101.pdf", "AAA")
    b = _pdf(tmp_path / "b" / "E-201.pdf", "BBB")
    docs = inspect_inputs([a, b]).accepted_documents
    _pdf(a, "AAA MUTATED")                        # change only the first
    changed = detect_mutations(docs)
    assert set(changed) == {docs[0].source_id}
    assert docs[1].source_id not in changed


# --------------------------------------------------------------------------- #
# End-to-end: a source mutated between analysis and markup is not inked
# --------------------------------------------------------------------------- #


def test_pipeline_skips_markup_for_mutated_source(tmp_path, monkeypatch):
    import json

    import drawing_analyzer.pipeline as pl
    from drawing_analyzer.pipeline import extract_drawing_context
    from drawing_analyzer.render import inspect_inputs as _real_inspect
    from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

    good = _pdf(tmp_path / "good" / "M-101.pdf", "VAV-3 SERVES ROOM 120")
    victim = _pdf(tmp_path / "victim" / "E-201.pdf", "PANEL LP-1 FEEDS ROOM 200")

    # A digest that emits one anchored finding per sheet, so both sheets have
    # markup-eligible ink.
    def _digest_for(system: str) -> str:
        block = json.dumps({"findings": [{
            "sheet_id": "S", "category": "code", "severity": "high",
            "text": "issue", "source_quote": "ROOM",
        }]})
        return "Sheet\nprose.\n\n```json\n" + block + "\n```"

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return FakeMessage(
                    content=[FakeTextBlock(text=_digest_for(kw.get("system", "")))],
                    usage=FakeUsage(input_tokens=10, output_tokens=5),
                )

    # Simulate a mid-run change to the victim by tampering its inventory snapshot
    # hash — the markup-time re-check re-hashes the (unchanged-on-disk) file and
    # finds it differs from the recorded snapshot, exactly as it would for a real
    # mid-run rewrite. This drives the §10.6 guard deterministically on every
    # platform, without racing PyMuPDF's open file handle (a real rewrite while
    # the render generator holds the file open fails on Windows).
    def _tampered_inspect(paths):
        inv = _real_inspect(paths)
        for d in inv.accepted_documents:
            if d.display_name == "E-201.pdf":
                d.content_sha256 = "0" * 64        # will never match the real hash
                d.byte_size = 0                    # break the stat fast-gate -> forces re-hash
        return inv

    monkeypatch.setattr(pl, "inspect_inputs", _tampered_inspect)

    ctx = extract_drawing_context(
        [good, victim], client=_Client(), rows=2, cols=2,
        qc_markups=True, verify_findings=False, qc_work_dir=tmp_path / "work",
    )

    # The victim "changed" vs its snapshot → flagged, recorded, and NOT marked
    # up; the good file still produced a reviewed PDF.
    assert "E-201.pdf" in ctx.mutated_sources
    assert any("E-201.pdf" in e and "re-run" in e for e in ctx.errors)
    names = sorted(p.name for p in ctx.reviewed_pdf_paths)
    assert names == ["M-101_reviewed.pdf"]       # only the unchanged source
    # The tally accounts the skipped entry honestly (not as clouded ink), and the
    # run's markup coverage is INCOMPLETE (Phase 21): a skipped source is a FAILED
    # placement receipt, never presented as a clean success.
    assert ctx.ledger_tally.get("mutated", 0) >= 1
    assert ctx.coverage_status == "INCOMPLETE"


def test_mutated_middle_source_does_not_misassign_ink(tmp_path, monkeypatch):
    # THE regression for the id-renumbering trap: with [A(mutated), B, C], the
    # writer recomputes SRC-#### from its path list, so B's/C's ink must NOT
    # shift onto the wrong file when A is excluded. Keeping the full path list
    # (filtering only findings) preserves the mapping; B and C each get their own
    # correct reviewed PDF, A gets none.
    import json

    import drawing_analyzer.pipeline as pl
    from drawing_analyzer.pipeline import extract_drawing_context
    from drawing_analyzer.render import inspect_inputs as _real_inspect
    from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

    a = _pdf(tmp_path / "a" / "A-1.pdf", "ALPHA ROOM")
    b = _pdf(tmp_path / "b" / "B-2.pdf", "BRAVO ROOM")
    c = _pdf(tmp_path / "c" / "C-3.pdf", "CHARLIE ROOM")

    def _client_text(**kw):
        block = json.dumps({"findings": [{
            "sheet_id": "S", "category": "code", "severity": "high",
            "text": "issue", "source_quote": "ROOM",
        }]})
        return FakeMessage(content=[FakeTextBlock(text="p\n\n```json\n" + block + "\n```")],
                           usage=FakeUsage(input_tokens=10, output_tokens=5))

    class _Client:
        class messages:
            create = staticmethod(_client_text)

    def _tampered_inspect(paths):
        inv = _real_inspect(paths)
        for d in inv.accepted_documents:
            if d.display_name == "A-1.pdf":         # the FIRST (middle-risk) source
                d.content_sha256 = "0" * 64
                d.byte_size = 0                     # break the stat fast-gate -> forces re-hash
        return inv

    monkeypatch.setattr(pl, "inspect_inputs", _tampered_inspect)

    ctx = extract_drawing_context(
        [a, b, c], client=_Client(), rows=2, cols=2,
        qc_markups=True, verify_findings=False, qc_work_dir=tmp_path / "work",
    )

    # A is skipped; B and C each get their OWN correctly-named reviewed PDF —
    # never B's ink on C.
    names = sorted(p.name for p in ctx.reviewed_pdf_paths)
    assert names == ["B-2_reviewed.pdf", "C-3_reviewed.pdf"]
    assert "A-1.pdf" in ctx.mutated_sources
