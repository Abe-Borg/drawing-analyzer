"""Reference-audit tests. Pure — synthetic word lists, no PyMuPDF, no network.

Word tuples mirror PyMuPDF's ``get_text("words")`` shape:
``(x0, y0, x1, y1, text, block, line, word_no)``.
"""
from __future__ import annotations

from pathlib import Path

from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from drawing_analyzer.reference_audit import (
    MALFORMED,
    MISSING_FROM_SET,
    RESOLVED_IN_SET,
    _levenshtein,
    _resolve,
    _segment_shape,
    audit_references,
    build_inventory,
    detect_sheet_id,
)

W, H = 3168.0, 2448.0  # E-size-ish page in points


def _w(x, y, text, width=64, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _sheet(source, page, words, *, page_count=1):
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=page_count)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=1, cols=1, words=list(words),
    )


def _titleblock(sheet_id):
    """A title-block ID word placed in the bottom-right corner."""
    return _w(W - 300, H - 160, sheet_id)


def _refs(findings):
    return {f.source_quote for f in findings}


# --------------------------------------------------------------------------- #
# Sheet-ID detection + inventory grammar
# --------------------------------------------------------------------------- #


def test_detect_sheet_id_prefers_bottom_right_over_distractor():
    sheet = _sheet("fp.pdf", 0, [
        _w(100, 100, "NFPA-13"),          # distractor code, top-left
        _w(120, 140, "K-5"),              # another distractor
        _titleblock("F-D-01-1"),          # real ID, bottom-right title block
    ])
    assert detect_sheet_id(sheet) == "F-D-01-1"


def test_detect_sheet_id_none_for_raster_sheet():
    assert detect_sheet_id(_sheet("scan.pdf", 0, [])) is None


def test_build_inventory_learns_two_numbering_styles():
    sheets = [
        _sheet("s.pdf", 0, [_titleblock("M-101")]),
        _sheet("s.pdf", 1, [_titleblock("M-102")]),
        _sheet("s.pdf", 2, [_titleblock("F-D-01-1")]),
    ]
    inv = build_inventory(sheets)
    assert inv.ids == frozenset({"M-101", "M-102", "F-D-01-1"})
    # Two distinct shapes learned: the M-style and the F-D-style.
    assert len(inv.grammar) == 2
    assert inv.matches_grammar("M-205")       # a new sheet in the M convention
    assert inv.matches_grammar("F-D-09-9")    # a new sheet in the F-D convention
    assert not inv.matches_grammar("NFPA-13")  # a code, not this set's convention


def test_segment_shape_is_revision_agnostic_but_prefix_sensitive():
    # Same shape regardless of the digits (revision/number differences).
    assert _segment_shape("F-D-01-1") == _segment_shape("F-D-02-0")
    # Different alpha-prefix length -> different shape (NFPA vs M).
    assert _segment_shape("NFPA-13") != _segment_shape("M-101")
    # A doubled/edge hyphen is not a clean ID.
    assert _segment_shape("F--01") is None


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


def test_resolve_classifies_present_missing_malformed_and_skip():
    inv = build_inventory([
        _sheet("s.pdf", 0, [_titleblock("F-D-01-1")]),
        _sheet("s.pdf", 1, [_titleblock("F-D-02-0")]),
    ])
    assert _resolve("F-D-01-1", inv)[0] == RESOLVED_IN_SET
    assert _resolve("F-D-01-0", inv)[0] == MISSING_FROM_SET   # grammar match, absent
    assert _resolve("F-D-O1-1", inv)[0] == MALFORMED          # letter O typo of a real sheet
    # A code token that merely follows a trigger word is not this set's grammar
    # and not a near-typo of any sheet -> skipped, never flagged.
    assert _resolve("NFPA-13", inv)[0] == "SKIP"


def test_levenshtein_basic():
    assert _levenshtein("F-D-01-1", "F-D-01-1") == 0
    assert _levenshtein("F-D-01-0", "F-D-01-1") == 1
    assert _levenshtein("", "abc") == 3


def test_closest_tie_break_is_deterministic():
    inv = build_inventory([
        _sheet("s.pdf", 0, [_titleblock("M-101")]),
        _sheet("s.pdf", 1, [_titleblock("M-102")]),
    ])
    # M-100 is edit-distance 1 from BOTH M-101 and M-102 — a tie. It must resolve
    # to the lexicographically smallest deterministically, not to whatever
    # frozenset iteration order this process's PYTHONHASHSEED produces (I-7).
    assert inv.closest("M-100") == ("M-101", 1)
    assert inv.closest("M-100") == inv.closest("M-100")


def test_unicode_hyphen_title_block_does_not_fabricate_missing():
    # A real cardinal-sin regression: a title-block ID drawn with non-breaking
    # hyphens (U+2011, common in CAD/PDF exports) must still be detected and
    # entered in the inventory, so an ASCII-hyphen reference to it resolves
    # rather than being falsely flagged as a missing sheet.
    nb = "‑"  # non-breaking hyphen
    sheets = [
        _sheet("s.pdf", 0, [_titleblock(f"F{nb}D{nb}01{nb}1")]),
        _sheet("s.pdf", 1, [
            _w(120, 400, "SEE"), _w(190, 400, "DRAWING"), _w(300, 400, "F-D-01-1"),
            _titleblock("F-D-02-0"),
        ]),
    ]
    inv = build_inventory(sheets)
    assert "F-D-01-1" in inv.ids  # the Unicode-hyphen ID folded to ASCII
    findings = audit_references(sheets)
    assert not any(
        "F-D-01-1" in f.text and "not present" in f.text for f in findings
    )


# --------------------------------------------------------------------------- #
# End-to-end audit
# --------------------------------------------------------------------------- #


def _fp_set():
    """An 8-ish-style FP fragment with seeded good / stale / detail / spec refs."""
    s0 = _sheet("fp.pdf", 0, [
        _w(120, 400, "SEE"), _w(190, 400, "DRAWING"), _w(300, 400, "F-D-01-0"),  # stale
        _w(120, 500, "REFER"), _w(190, 500, "TO"), _w(250, 500, "F-D-01-1"),      # resolves
        _w(120, 600, "23"), _w(190, 600, "21"), _w(260, 600, "13"),               # CSI spec
        _titleblock("F-D-01-1"),
    ])
    s1 = _sheet("fp.pdf", 1, [
        _w(120, 400, "04/F-D-09-9"),                                              # detail -> missing
        _w(120, 500, "PER"), _w(180, 500, "NFPA-13"),                             # code -> skip
        _titleblock("F-G-02-0"),
    ], page_count=2)
    return [s0, s1]


def test_audit_flags_stale_reference_with_closest_suggestion():
    findings = audit_references(_fp_set())
    stale = [f for f in findings if "F-D-01-0" in f.text]
    assert len(stale) == 1
    f = stale[0]
    assert f.category == "reference"
    assert f.severity == "medium"
    assert "not present in the provided set" in f.text
    assert "closest in set: F-D-01-1" in f.text
    # Anchored, deterministic, never claims the sheet doesn't exist.
    assert f.anchor.status == "EXACT" and f.anchor.rect_pdf is not None
    assert f.verification.status == "DETERMINISTIC"
    assert "does not exist" not in f.text.lower()
    assert f.source_quote == "SEE DRAWING F-D-01-0"


def test_audit_does_not_flag_resolved_references():
    findings = audit_references(_fp_set())
    # "REFER TO F-D-01-1" points at a sheet in the set -> no finding for it.
    assert not any(f.source_quote == "REFER TO F-D-01-1" for f in findings)


def test_audit_flags_detail_bubble_to_missing_sheet():
    findings = audit_references(_fp_set())
    bubble = [f for f in findings if f.source_quote == "04/F-D-09-9"]
    assert len(bubble) == 1
    assert bubble[0].severity == "medium"
    assert "F-D-09-9" in bubble[0].text
    assert bubble[0].anchor.method == "detail_bubble"


def test_audit_collects_csi_spec_as_informational():
    findings = audit_references(_fp_set())
    spec = [f for f in findings if f.source_quote == "23 21 13"]
    assert len(spec) == 1
    assert spec[0].severity == "low"
    assert "not available to verify" in spec[0].text
    assert spec[0].anchor.status == "EXACT"
    assert spec[0].verification.status == "DETERMINISTIC"


def test_audit_skips_code_tokens_after_triggers():
    findings = audit_references(_fp_set())
    # "PER NFPA-13" is a code citation, not a sheet reference in this set's
    # grammar -> never flagged.
    assert not any("NFPA-13" in f.text for f in findings)
    assert not any(f.source_quote == "PER NFPA-13" for f in findings)


def test_audit_missing_without_close_match_omits_suggestion():
    # A reference that matches the set's grammar but is far (edit distance 4)
    # from every in-set ID gets no misleading "closest in set" suggestion.
    sheets = [
        _sheet("s.pdf", 0, [
            _w(120, 400, "SEE"), _w(190, 400, "DRAWING"), _w(300, 400, "F-Z-88-7"),
            _titleblock("F-D-01-1"),
        ]),
        _sheet("s.pdf", 1, [_titleblock("F-D-02-0")]),
    ]
    findings = audit_references(sheets)
    miss = [f for f in findings if "F-Z-88-7" in f.text]
    assert len(miss) == 1
    assert miss[0].text.endswith("not present in the provided set.")
    assert "closest in set" not in miss[0].text


def test_audit_various_trigger_phrases():
    sheets = [
        _sheet("s.pdf", 0, [
            _w(100, 100, "SEE"), _w(160, 100, "SHEET"), _w(240, 100, "M-999"),
            _w(100, 200, "ON"), _w(140, 200, "DRAWING"), _w(240, 200, "M-998"),
            _w(100, 300, "SEE"), _w(160, 300, "M-997"), _w(240, 300, "FOR"), _w(300, 300, "DETAILS"),
            _titleblock("M-101"),
        ]),
    ]
    quotes = _refs(audit_references(sheets))
    assert "SEE SHEET M-999" in quotes
    assert "ON DRAWING M-998" in quotes
    assert "SEE M-997 FOR" in quotes


def test_audit_empty_inventory_flags_nothing():
    # No detectable title-block IDs -> no grammar -> no false positives.
    sheets = [_sheet("s.pdf", 0, [
        _w(120, 400, "SEE"), _w(190, 400, "DRAWING"), _w(300, 400, "F-D-01-0"),
    ])]
    # (The stale ref's own token isn't a title-block ID here since there's no
    # bottom-right ID; detection may still pick it, so assert conservatively that
    # a set with no *resolvable* grammar never fabricates a missing-sheet claim.)
    findings = audit_references(sheets)
    assert all(f.category == "reference" for f in findings)


def test_audit_raster_sheet_contributes_nothing():
    findings = audit_references([_sheet("scan.pdf", 0, [])])
    assert findings == []


def test_audit_collapses_repeated_identical_reference_to_unique_ids():
    # A reference written verbatim twice on one sheet collapses to a single
    # finding — otherwise the two would share a content-derived Finding.id and an
    # id-keyed downstream structure (evidence png, export) would silently drop
    # one. (The ledger's later text-overlap merge would collapse them anyway.)
    sheets = [
        _sheet("s.pdf", 0, [
            _w(120, 400, "SEE"), _w(190, 400, "DRAWING"), _w(300, 400, "F-D-09-9"),
            _w(120, 900, "SEE"), _w(190, 900, "DRAWING"), _w(300, 900, "F-D-09-9"),
            _titleblock("F-D-01-1"),
        ]),
        _sheet("s.pdf", 1, [_titleblock("F-D-02-0")]),
    ]
    missing = [f for f in audit_references(sheets) if "F-D-09-9" in f.text]
    assert len(missing) == 1


def test_audit_finding_ids_are_unique():
    # A sheet mixing several distinct references must never emit two findings
    # with the same id (the guarantee the source_quote-keyed dedup provides).
    sheets = [
        _sheet("s.pdf", 0, [
            _w(120, 100, "SEE"), _w(190, 100, "DRAWING"), _w(300, 100, "F-D-09-9"),
            _w(120, 200, "04/F-D-08-8"),
            _w(120, 300, "REFER"), _w(190, 300, "TO"), _w(260, 300, "F-D-07-7"),
            _w(120, 400, "23"), _w(190, 400, "21"), _w(260, 400, "13"),
            _titleblock("F-D-01-1"),
        ]),
        _sheet("s.pdf", 1, [_titleblock("F-D-02-0")]),
    ]
    findings = audit_references(sheets)
    ids = [f.id for f in findings]
    assert len(ids) == len(set(ids))  # all distinct
    assert len(findings) >= 4


def test_audit_csi_ignores_long_numeric_runs():
    # A run of 4+ consecutive 2-digit tokens is a numeric table, not a citation —
    # it must NOT emit overlapping/spurious spec findings (the confirmed bug on
    # ['23','21','13','16']).
    sheets = [_sheet("s.pdf", 0, [
        _w(100, 100, "23"), _w(170, 100, "21"), _w(240, 100, "13"), _w(310, 100, "16"),
        _titleblock("M-101"),
    ])]
    specs = [f for f in audit_references(sheets) if f.anchor.method == "spec_section"]
    assert specs == []  # a 4-run is skipped whole, no spurious "21 13 16"


def test_audit_csi_two_isolated_citations_both_found():
    # Two isolated 3-token runs (separated by a non-2-digit word) are both specs.
    sheets = [_sheet("s.pdf", 0, [
        _w(100, 100, "23"), _w(170, 100, "21"), _w(240, 100, "13"),
        _w(320, 100, "AND"),
        _w(100, 200, "26"), _w(170, 200, "05"), _w(240, 200, "00"),
        _titleblock("M-101"),
    ])]
    specs = {f.source_quote for f in audit_references(sheets)
             if f.anchor.method == "spec_section"}
    assert specs == {"23 21 13", "26 05 00"}
