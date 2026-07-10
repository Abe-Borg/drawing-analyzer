"""Host-owned source identity (DA-001, Phase 18A).

The registry assigns each accepted input an opaque ``SRC-####`` id in input
order — the authority that keeps two same-basename PDFs apart everywhere
downstream. These tests pin the assignment/dedup contract; the end-to-end
isolation (a finding never lands on the wrong PDF) is exercised in
``test_source_identity.py`` and ``test_drawing_annotate.py``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from drawing_analyzer.source_registry import (
    assign_source_ids,
    canonical_path,
    format_source_id,
)


def _k(p: str) -> str:
    """The dict key assign_source_ids uses — ``str(Path(p))`` — so the lookup is
    robust to platform separator normalization (Windows turns ``/x/a`` into
    ``\\x\\a``). This mirrors how render.py / annotate.py look ids up."""
    return str(Path(p))


def test_ids_are_assigned_in_input_order():
    ids = assign_source_ids(["/x/a.pdf", "/x/b.pdf", "/x/c.pdf"])
    assert ids[_k("/x/a.pdf")] == "SRC-0001"
    assert ids[_k("/x/b.pdf")] == "SRC-0002"
    assert ids[_k("/x/c.pdf")] == "SRC-0003"


def test_same_basename_different_dirs_get_distinct_ids():
    # THE core requirement: two M-101.pdf in different folders are different
    # sources and must never share an id.
    ids = assign_source_ids(["/rev_a/M-101.pdf", "/rev_b/M-101.pdf"])
    assert ids[_k("/rev_a/M-101.pdf")] != ids[_k("/rev_b/M-101.pdf")]
    assert set(ids.values()) == {"SRC-0001", "SRC-0002"}


def test_identical_canonical_path_twice_dedupes_to_one_id(tmp_path):
    f = tmp_path / "M-101.pdf"
    f.write_text("pdf", encoding="utf-8")
    ids = assign_source_ids([f, f])
    assert ids[str(f)] == "SRC-0001"
    # The same file supplied twice is one source, not two.
    assert set(ids.values()) == {"SRC-0001"}


def test_relative_and_absolute_reference_to_same_file_dedupe(tmp_path, monkeypatch):
    f = tmp_path / "M-101.pdf"
    f.write_text("pdf", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    ids = assign_source_ids(["M-101.pdf", str(f)])
    # Relative "M-101.pdf" and the absolute path are the same file → one id,
    # even though the two dict keys differ.
    assert len(set(ids.values())) == 1


def test_canonical_path_is_case_normalized_only_where_the_os_is():
    # normcase lower-cases on Windows and is identity on POSIX; assert we follow
    # the platform rather than hard-coding case-folding (Windows-safety).
    a = canonical_path("/X/Foo.PDF")
    if os.name == "nt":
        assert a == a.lower()
    else:
        assert "Foo.PDF" in a  # case preserved on case-sensitive platforms


def test_format_source_id_is_zero_padded():
    assert format_source_id(1) == "SRC-0001"
    assert format_source_id(42) == "SRC-0042"


def test_empty_input_yields_empty_map():
    assert assign_source_ids([]) == {}
