"""Tests for the shared sheet-ID foundation (Phase 24 §16.0) — normalization,
project-prefix-aware discipline detection, the candidate lexer, and the
inventory/ambiguity resolver. Pure and hermetic (no model, no PyMuPDF).
"""
from __future__ import annotations

from drawing_analyzer.auditors import sheet_ids as S


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


def test_normalize_folds_dashes_uppercases_and_trims_edges():
    # Unicode dashes fold to ASCII "-"; surrounding punctuation/space stripped;
    # internal separators preserved; case folded up.
    assert S.normalize_sheet_id("  f‑d–01–1 ") == "F-D-01-1"
    assert S.normalize_sheet_id("(M-101).") == "M-101"
    assert S.normalize_sheet_id("m1.01") == "M1.01"
    assert S.normalize_sheet_id("") == "" and S.normalize_sheet_id(None) == ""


def test_normalize_never_swaps_lookalike_characters():
    # A "cleanup" that swapped O/0 or I/1 would destroy a real numbering
    # distinction — normalization must not do it.
    assert S.normalize_sheet_id("M-O1") == "M-O1"
    assert S.normalize_sheet_id("E-I0") == "E-I0"


# --------------------------------------------------------------------------- #
# Discipline detection (DA-018)
# --------------------------------------------------------------------------- #


def test_discipline_token_plain_forms():
    assert S.discipline_token("F-D-01-1") == "f"
    assert S.discipline_token("FP-101") == "fp"
    assert S.discipline_token("M-101") == "m"
    assert S.discipline_token("F101") == "f"
    assert S.discipline_token("FP101") == "fp"
    assert S.discipline_token("FP201") == "fp"
    assert S.discipline_token("M1") == "m"
    assert S.discipline_token("E1.01") == "e"
    assert S.discipline_token("101") == "" and S.discipline_token("") == ""


def test_discipline_token_is_project_prefix_aware():
    # The core DA-018 fix: a project-coded id must yield the discipline segment,
    # not the leading project code.
    assert S.discipline_token("AVC10-F-D-01-1") == "f"
    assert S.discipline_token("PROJ2-M-101") == "m"
    assert S.discipline_token("AVC10.F.D.01.1") == "f"
    # A pure-alpha lead (a real short discipline) is NOT treated as a project code.
    assert S.discipline_token("FP-101") == "fp"
    # A single discipline letter followed by digits in one segment is compact,
    # not a project prefix.
    assert S.discipline_token("M1-01") == "m"


def test_discipline_tokens_collects_distinct():
    assert S.discipline_tokens(["F-D-01-1", "FP101", "M-101", ""]) == {"f", "fp", "m"}


# --------------------------------------------------------------------------- #
# Candidate lexer
# --------------------------------------------------------------------------- #


def test_looks_like_sheet_id_recognizes_families():
    for good in ("M-101", "F-D-01-1", "AVC10-F-D-01-1", "M101", "FP101", "A001", "M1.01", "E2.1"):
        assert S.looks_like_sheet_id(good), good
    for bad in ("NOTES", "SEE", "101", "", "F", "ABCDEF"):
        assert not S.looks_like_sheet_id(bad), bad


def test_bubble_target_extracts_referenced_id():
    assert S.bubble_target("5/FP101") == "FP101"
    assert S.bubble_target("04/F-D-01-1") == "F-D-01-1"
    assert S.bubble_target("12 / M-101") == "M-101"
    assert S.bubble_target("M-101") is None          # not a bubble
    assert S.bubble_target("5/NOTES") is None         # target is not an id


# --------------------------------------------------------------------------- #
# Inventory / ambiguity resolver
# --------------------------------------------------------------------------- #


def test_index_resolves_a_unique_id():
    idx = S.SheetIdIndex([("M-101", "a"), ("E-201", "b")])
    r = idx.resolve("m-101")                          # case/normalization-insensitive
    assert r.status == S.RESOLVED and r.value == "a"
    assert idx.resolve(" M‑101 ").value == "a"   # unicode dash + edges


def test_index_reports_zero_candidates_as_unbound():
    idx = S.SheetIdIndex([("M-101", "a")])
    r = idx.resolve("M-999")
    assert r.status == S.UNBOUND and r.value is None and r.candidates == ()


def test_index_reports_collision_as_ambiguous_never_first_wins():
    # Two different sources normalize to the same id — the resolver must report
    # the collision, not silently pick one (§10.4 / §16.1).
    idx = S.SheetIdIndex([("M-101", "srcA"), ("M-101", "srcB")])
    r = idx.resolve("M-101")
    assert r.status == S.AMBIGUOUS and r.value is None
    assert set(r.candidates) == {"srcA", "srcB"}
    assert idx.is_ambiguous("m-101") is True


def test_index_dedupes_identical_payload_under_one_key():
    # The same source registered twice is idempotent — not fabricated ambiguity.
    idx = S.SheetIdIndex()
    idx.add("M-101", "src")
    idx.add("M-101", "src")
    assert idx.resolve("M-101").status == S.RESOLVED
    # A blank id is ignored.
    assert idx.add("", "x") == "" and "" not in idx.ids
