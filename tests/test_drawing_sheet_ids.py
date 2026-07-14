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
    # not the leading project code (3+ leading letters + digits = project code).
    assert S.discipline_token("AVC10-F-D-01-1") == "f"
    assert S.discipline_token("PROJ2-M-101") == "m"
    assert S.discipline_token("AVC10.F.D.01.1") == "f"
    # A pure-alpha lead (a real short discipline) is NOT treated as a project code.
    assert S.discipline_token("FP-101") == "fp"
    # A single discipline letter followed by digits in one segment is compact,
    # not a project prefix.
    assert S.discipline_token("M1-01") == "m"


def test_discipline_token_two_letter_compact_with_suffix_is_not_a_project_code():
    # Regression: a compact TWO-letter discipline followed by a suffix segment
    # (matchline/revision/phase letters) must keep its discipline, not read the
    # suffix. The earlier >=2 guard misread FP101-A as a project code -> "a".
    assert S.discipline_token("FP101-A") == "fp"
    assert S.discipline_token("FA101-N") == "fa"
    assert S.discipline_token("CE201-X") == "ce"
    assert S.discipline_token("AD101-B") == "ad"
    assert S.discipline_token("FP101-DEMO") == "fp"
    assert S.discipline_token("M101-2") == "m"


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


# --------------------------------------------------------------------------- #
# Learned ID grammar — signatures (§17.3)
# --------------------------------------------------------------------------- #


def test_id_signature_is_revision_agnostic_but_prefix_and_separator_sensitive():
    # Revision/number differences share a signature; prefix length and separators
    # do not.
    assert S.id_signature("F-D-01-1") == S.id_signature("F-D-02-0")
    assert S.id_signature("M-101") == S.id_signature("M-999")           # digit-agnostic
    assert S.id_signature("NFPA-13") != S.id_signature("M-101")         # A4 vs A1 prefix
    assert S.id_signature("M-1-01") != S.id_signature("M1.01")          # separators differ
    assert S.id_signature("FP101") != S.id_signature("F-101")           # compact vs hyphenated


def test_id_signature_rejects_malformed():
    assert S.id_signature("F--01") is None       # doubled hyphen
    assert S.id_signature("-M101") is None        # leading separator
    assert S.id_signature("M101-") is None        # trailing separator
    assert S.id_signature("5/FP101") is None      # a slash is not a clean id char
    assert S.id_signature("") is None


def test_learn_and_match_grammar_across_families():
    g = S.learn_grammar(["FP101", "FP102", "F-D-01-1"])
    assert len(g) == 2                                    # compact + hyphenated
    assert S.matches_grammar("FP205", g)                  # compact convention
    assert S.matches_grammar("F-D-09-9", g)               # hyphenated convention
    assert not S.matches_grammar("NFPA-13", g)


def test_closest_in_set_is_deterministic_tie_break():
    ids = ["M-101", "M-102"]
    assert S.closest_in_set("M-100", ids) == ("M-101", 1)   # tie -> lexicographically first
    assert S.closest_in_set("M-100", ids) == S.closest_in_set("M-100", ids)
    assert S.closest_in_set("X-9", []) == (None, None)


# --------------------------------------------------------------------------- #
# Negative corpus + resolution policy (§17.3)
# --------------------------------------------------------------------------- #


def test_negative_corpus_rejects_non_sheet_tokens():
    for t in ("NFPA-13", "IBC-202", "IFC-1", "UL-300", "T24", "RFI-123", "ASI-3",
              "480V", "120/208V", "23", "101", "12-6"):
        assert S.is_non_sheet_reference(t), t
    # Real sheet ids are NOT in the negative corpus.
    for t in ("M-101", "FP101", "F-D-01-1", "M1.01"):
        assert not S.is_non_sheet_reference(t), t


def test_classify_reference_full_policy():
    ids = ["F-D-01-1", "F-D-02-0"]
    g = S.learn_grammar(ids)
    assert S.classify_reference("F-D-01-1", ids, g).status == S.RESOLVED_IN_SET
    assert S.classify_reference("F-D-01-0", ids, g).status == S.MISSING_FROM_SET
    assert S.classify_reference("F-D-O1-1", ids, g).status == S.MALFORMED   # O/0 typo
    # A code token that is coincidentally a near-typo of a real sheet is still
    # ignored — the negative corpus vetoes the malformed path.
    assert S.classify_reference("NFPA-13", ids, g).status == S.IGNORE
    assert S.classify_reference("480V", ids, g).status == S.IGNORE


def test_classify_reference_low_confidence_suppresses_only_the_fuzzy_path():
    ids = ["M-101"]
    g = S.learn_grammar(ids)
    # A well-formed reference that matches the (single) learned convention and is
    # absent is still a real miss — a strong trigger should surface it (§17.3).
    assert S.classify_reference("M-102", ids, g, low_confidence=True).status == S.MISSING_FROM_SET
    assert S.classify_reference("M-101", ids, g, low_confidence=True).status == S.RESOLVED_IN_SET
    # But the fuzzy near-typo (MALFORMED) path is suppressed on a thin grammar —
    # a one-id convention can't reliably guess that an out-of-grammar token is a
    # typo of the single sheet.
    typo = S.classify_reference("MX-1-1", ids, g, low_confidence=True)
    assert typo.status == S.IGNORE
    assert S.classify_reference("MX-1-1", ids, g, low_confidence=False).status == S.MALFORMED


def test_reference_resolution_suggestion_within_distance():
    r = S.classify_reference("F-D-01-0", ["F-D-01-1"], S.learn_grammar(["F-D-01-1"]))
    assert r.suggestion == " (closest in set: F-D-01-1)"
    far = S.ReferenceResolution(S.MISSING_FROM_SET, "F-Z-88-7", "F-D-01-1", 5)
    assert far.suggestion == ""
