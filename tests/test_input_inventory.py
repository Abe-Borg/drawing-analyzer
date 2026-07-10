"""Resilient input inventory + preflight bounds (Phase 18B, DA-002 / DA-035).

A corrupt, locked, or duplicate input must degrade *individually and visibly*
rather than aborting an otherwise-valid drawing set or silently vanishing. These
tests build real PDFs (so they need PyMuPDF, like the annotate/pipeline suites)
and drive the classifier, the preflight bounds, and one end-to-end mixed
good/bad run through ``extract_drawing_context`` with a fake client.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pymupdf
import pytest

from drawing_analyzer import source_registry as sr
from drawing_analyzer.render import inspect_inputs, list_sheets
from drawing_analyzer.source_registry import (
    ACCEPTED,
    DUPLICATE,
    ENCRYPTED,
    UNREADABLE,
    check_set_limits,
    check_work_disk,
    content_sha256,
)


def _pdf(path: Path, *, pages: int = 1, name_text: str = "SHEET") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page(width=612, height=792).insert_text((72, 72), f"{name_text} p{i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def _corrupt(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7 this is not really a pdf \x00\x01\x02")
    return path


def _encrypted(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    doc.new_page(width=612, height=792).insert_text((72, 72), "secret")
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
             owner_pw="o", user_pw="u")
    doc.close()
    return path


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def test_corrupt_plus_valid_accepts_good_records_bad(tmp_path):
    good = _pdf(tmp_path / "M-101.pdf")
    bad = _corrupt(tmp_path / "broken.pdf")
    inv = inspect_inputs([bad, good])

    by_name = {d.display_name: d for d in inv.documents}
    assert by_name["broken.pdf"].status == UNREADABLE
    assert by_name["broken.pdf"].error                       # a useful reason
    assert by_name["M-101.pdf"].status == ACCEPTED
    assert inv.accepted_paths == [good]
    assert inv.error_lines() and "broken.pdf" in inv.error_lines()[0]


def test_encrypted_input_is_classified_distinctly(tmp_path):
    enc = _encrypted(tmp_path / "locked.pdf")
    (doc,) = inspect_inputs([enc]).documents
    assert doc.status == ENCRYPTED
    assert "password" in doc.error.lower()


def test_missing_input_is_unreadable(tmp_path):
    (doc,) = inspect_inputs([tmp_path / "nope.pdf"]).documents
    assert doc.status == UNREADABLE


def test_inventory_error_never_leaks_the_absolute_path(tmp_path):
    # A missing absolute path: the OS/PyMuPDF message echoes the full path, but
    # the sanitized reason (and the summary line reports use) must be path-free.
    missing = tmp_path / "private_dir" / "secret_M-101.pdf"
    (rec,) = inspect_inputs([missing]).documents
    assert rec.status == UNREADABLE
    assert str(missing) not in rec.error
    assert str(missing.parent) not in rec.error
    assert str(missing) not in rec.summary_line()
    assert rec.display_name == "secret_M-101.pdf"          # basename is fine


def test_duplicate_selection_processed_once(tmp_path):
    good = _pdf(tmp_path / "M-101.pdf")
    inv = inspect_inputs([good, good])
    statuses = [d.status for d in inv.documents]
    assert statuses == [ACCEPTED, DUPLICATE]
    assert inv.accepted_paths == [good]
    assert inv.documents[1].duplicate_of == inv.documents[0].source_id


def test_same_basename_different_dirs_get_distinct_ids(tmp_path):
    a = _pdf(tmp_path / "a" / "M-101.pdf")
    b = _pdf(tmp_path / "b" / "M-101.pdf")
    inv = inspect_inputs([a, b])
    ids = [d.source_id for d in inv.accepted_documents]
    assert ids == ["SRC-0001", "SRC-0002"]      # distinct — the DA-001 core


def test_source_ids_are_over_accepted_inputs_only(tmp_path):
    # A rejected input must not consume an id: the good file (2nd in input order)
    # is still SRC-0001, and list_sheets over the accepted paths agrees.
    bad = _corrupt(tmp_path / "broken.pdf")
    good = _pdf(tmp_path / "M-101.pdf", pages=2)
    inv = inspect_inputs([bad, good])
    (acc,) = inv.accepted_documents
    assert acc.source_id == "SRC-0001"
    refs = list_sheets(inv.accepted_paths)
    assert {r.source_id for r in refs} == {"SRC-0001"}
    assert len(refs) == 2


def test_pathological_page_is_skipped_but_good_pages_survive(tmp_path):
    # A file whose 2nd page has a pathological box: the file is ACCEPTED (a bad
    # page never rejects the whole file, §10.5), and the pathological page is
    # excluded at render time BEFORE rasterizing it (§10.7) while the good page
    # still renders.
    from drawing_analyzer.render import iter_rendered_sheets

    path = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    doc.new_page(width=612, height=792).insert_text((72, 72), "GOOD PAGE")
    doc.new_page(width=999999, height=999999)          # pathological
    doc.save(str(path))
    doc.close()

    (rec,) = inspect_inputs([path]).documents
    assert rec.status == ACCEPTED and rec.page_count == 2

    errors: list = []
    sheets = list(iter_rendered_sheets(
        [path], rows=2, cols=2, on_page_error=lambda ref, exc: errors.append((ref, exc))
    ))
    assert [s.ref.page_index for s in sheets] == [0]    # only the good page
    assert len(errors) == 1 and errors[0][0].page_index == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits only")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses permission bits, so chmod 000 is still readable",
)
def test_permission_denied_is_unreadable(tmp_path):
    good = _pdf(tmp_path / "M-101.pdf")
    good.chmod(0o000)
    try:
        (rec,) = inspect_inputs([good]).documents
        assert rec.status == UNREADABLE
    finally:
        good.chmod(0o644)   # let tmp cleanup remove it


# --------------------------------------------------------------------------- #
# Content hash (revision identity for Phase 18C)
# --------------------------------------------------------------------------- #


def test_content_sha256_is_stable_and_reports_size(tmp_path):
    good = _pdf(tmp_path / "M-101.pdf")
    h1, size, mtime = content_sha256(good)
    h2, size2, _ = content_sha256(good)
    assert h1 == h2 and len(h1) == 64
    assert size == size2 == good.stat().st_size
    # Different content → different hash.
    other = _pdf(tmp_path / "E-201.pdf", name_text="OTHER")
    assert content_sha256(other)[0] != h1


# --------------------------------------------------------------------------- #
# Preflight bounds (DA-035)
# --------------------------------------------------------------------------- #


def _accepted(n_files: int, pages_each: int):
    return [
        sr.SourceDocument(source_id=sr.format_source_id(i + 1), pdf_path=Path(f"/x/{i}.pdf"),
                          display_name=f"{i}.pdf", input_order=i + 1, status=ACCEPTED,
                          page_count=pages_each)
        for i in range(n_files)
    ]


def test_check_set_limits_blocks_oversized_without_confirmation():
    docs = _accepted(3, 10)          # 30 sheets
    reason = check_set_limits(docs, max_sheets=20, max_files=100)
    assert reason and "sheets" in reason
    # Explicit confirmation lets it through (no silent truncation).
    assert check_set_limits(docs, confirmed=True, max_sheets=20) is None
    # File-count bound too.
    assert check_set_limits(_accepted(5, 1), max_files=3) is not None


def test_check_work_disk_blocks_when_probe_reports_full():
    tiny = lambda _d: 1 << 20                     # 1 MB free
    assert check_work_disk(500 << 20, "/x", free_bytes_probe=tiny) is not None
    plenty = lambda _d: 100 << 30                 # 100 GB free
    assert check_work_disk(500 << 20, "/x", free_bytes_probe=plenty) is None
    # A probe failure must never block a run.
    def boom(_d):
        raise OSError("no such dir")
    assert check_work_disk(1, "/x", free_bytes_probe=boom) is None


def test_env_num_falls_back_on_malformed(monkeypatch):
    # A blank / non-numeric override must degrade to the default, never crash
    # the app at import (parity with worker-count env handling).
    from drawing_analyzer.source_registry import _env_num

    monkeypatch.setenv("DA_TEST_NUM", "not-a-number")
    assert _env_num("DA_TEST_NUM", 42, int) == 42
    monkeypatch.setenv("DA_TEST_NUM", "   ")
    assert _env_num("DA_TEST_NUM", 7, int) == 7
    monkeypatch.delenv("DA_TEST_NUM", raising=False)
    assert _env_num("DA_TEST_NUM", 9, int) == 9
    monkeypatch.setenv("DA_TEST_NUM", "123")
    assert _env_num("DA_TEST_NUM", 1, int) == 123


# --------------------------------------------------------------------------- #
# End-to-end: a mixed good/bad set completes with a partial deliverable (test 7)
# --------------------------------------------------------------------------- #


def _fake_digest_client(text="Sheet M-101 - Plan\nVAV-3 serves Room 120."):
    from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return FakeMessage(content=[FakeTextBlock(text=text)],
                                   usage=FakeUsage(input_tokens=10, output_tokens=5))

    return _Client()


def test_pipeline_completes_with_partial_deliverable_on_mixed_inputs(tmp_path):
    from drawing_analyzer.pipeline import extract_drawing_context

    good = _pdf(tmp_path / "M-101.pdf")
    bad = _corrupt(tmp_path / "broken.pdf")

    # Bad file first — the good file must still digest, and the bad one is
    # recorded (not silently dropped, not fatal).
    ctx = extract_drawing_context([bad, good], client=_fake_digest_client(), rows=2, cols=2)

    assert ctx.sheet_count == 1                    # only the good file's page
    assert any("broken.pdf" in e for e in ctx.errors)
    assert "VAV-3 serves Room 120" in ctx.combined_text


def test_pipeline_blocks_early_on_insufficient_work_disk(tmp_path, monkeypatch):
    # The DA-035 disk preflight must actually fire in the run path for a QC run
    # (qc_work_dir set), returning early before any paid work.
    import drawing_analyzer.pipeline as pl
    from drawing_analyzer.pipeline import extract_drawing_context

    good = _pdf(tmp_path / "M-101.pdf")
    monkeypatch.setattr(
        pl, "check_work_disk",
        lambda needed, target, **kw: "insufficient free space (test)",
    )
    ctx = extract_drawing_context(
        [good], client=_fake_digest_client(), qc_work_dir=tmp_path / "work",
        rows=2, cols=2,
    )
    assert ctx.sheet_count == 0
    assert any("insufficient free space" in e for e in ctx.errors)
