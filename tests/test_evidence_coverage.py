"""WP-02 — evidence-coverage measurement (§7.1) and discard counters (§7.2).

Two tiers that must not be conflated, so they are tested as two things:

- §7.1 is derivable from PDFs on disk and an existing export. Tested here on
  generated PDFs and hand-built export artifacts. Zero API calls.
- §7.2 counts what the *host discarded* from a model response. Tested here on
  the pure parse functions with a fake response — no client, no network.

The one property both tiers share, and the one this file exists to protect: a
surviving-finding distribution is never the discard rate. §7.1's report must say
so out loud, and §7.2's counters must be the only thing that answers it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from drawing_analyzer.cross_qc import (  # noqa: E402
    CrossQCDiscardCounts,
    _finding_from_handles,
    _parse_facts,
    _sheet_is_textless,
    sheet_counter_key,
)
from drawing_analyzer.models import RenderedSheet, SheetGeometry, SheetRef  # noqa: E402
from drawing_analyzer.render import SHEET_TEXT_MAX_CHARS  # noqa: E402

from measure_evidence_coverage import (  # noqa: E402
    HYBRID_WORD_FREE_TILE_FRACTION,
    SetCoverage,
    SheetCoverage,
    classify_sheet,
    discard_rate_by_classification,
    count_word_free_tiles,
    read_run_completeness,
    read_surviving_findings,
    render_text,
    summarize,
    scan_sheets,
)

pymupdf = pytest.importorskip("pymupdf")

_W, _H = 2448.0, 3168.0          # ANSI E in points


def _ref(name: str = "s.pdf", source_id: str = "SRC-0001") -> SheetRef:
    return SheetRef(pdf_path=Path(name), page_index=0, source_name=name,
                    page_count=1, source_id=source_id)


def _geom(*, words=(), text="", rows=6, cols=6, total=None) -> SheetGeometry:
    return SheetGeometry(
        ref=_ref(),
        page_width_pt=_W, page_height_pt=_H, rows=rows, cols=cols,
        words=list(words), sheet_text=text, is_raster=not words,
        text_chars_total=len(text) if total is None else total,
    )


# --------------------------------------------------------------------------- #
# §7.1 — classification and the word-free-tile heuristic
# --------------------------------------------------------------------------- #


def test_textless_sheet_is_classified_textless():
    assert classify_sheet(word_count=0, word_free_tiles=36, total_tiles=36) == "textless"


def test_dense_vector_sheet_is_classified_vector():
    assert classify_sheet(word_count=500, word_free_tiles=2, total_tiles=36) == "vector"


def test_sheet_with_words_but_mostly_empty_tiles_is_hybrid():
    """The case `is_raster` cannot see: words present, most of the page pixel-only."""
    free = int(36 * HYBRID_WORD_FREE_TILE_FRACTION) + 1
    assert classify_sheet(word_count=12, word_free_tiles=free, total_tiles=36) == "hybrid"


def test_hybrid_is_not_reachable_via_is_raster():
    """A hybrid sheet has words, so `is_raster` is False — the §2.1 point."""
    geom = _geom(words=[(0.0, 0.0, 10.0, 10.0, "NOTE", 0, 0, 0)], text="NOTE")
    assert geom.is_raster is False
    free, total = count_word_free_tiles(geom)
    assert classify_sheet(len(geom.words), free, total) == "hybrid"


def test_word_free_tiles_counts_only_regions_with_no_word():
    """One word in one corner leaves every other tile word-free."""
    geom = _geom(words=[(1.0, 1.0, 20.0, 20.0, "A1", 0, 0, 0)], text="A1")
    free, total = count_word_free_tiles(geom)
    assert total == 36
    assert free == 35


def test_word_free_tiles_is_zero_when_words_cover_the_page():
    words = [
        (c * _W / 6 + 1, r * _H / 6 + 1, c * _W / 6 + 20, r * _H / 6 + 20, "X", 0, 0, 0)
        for r in range(6) for c in range(6)
    ]
    free, total = count_word_free_tiles(_geom(words=words, text="X" * 36))
    assert (free, total) == (0, 36)


def test_malformed_word_tuples_do_not_crash_the_scan():
    geom = _geom(words=[("bad",), None, (1.0, 1.0, 2.0, 2.0, "OK", 0, 0, 0)], text="OK")
    free, total = count_word_free_tiles(geom)
    assert total == 36 and free == 35


def test_degenerate_page_size_yields_no_tiles_instead_of_raising():
    geom = _geom(words=[(0.0, 0.0, 1.0, 1.0, "x", 0, 0, 0)], text="x")
    geom.page_width_pt = 0.0
    assert count_word_free_tiles(geom) == (0, 0)


# --------------------------------------------------------------------------- #
# §7.1 — the pre-cap length is what makes trigger 1 measurable
# --------------------------------------------------------------------------- #


def _pdf(tmp_path: Path, name: str, *, text: str, pages: int = 1) -> Path:
    path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=_W, height=_H)
        # Many short lines: enough characters to exceed the cap when asked.
        y = 20.0
        for chunk in (text[i:i + 90] for i in range(0, len(text), 90)):
            if y > _H - 20:
                break
            page.insert_text((20, y), chunk, fontsize=6)
            y += 8.0
    doc.save(str(path))
    doc.close()
    return path


def test_text_chars_total_survives_the_cap(tmp_path):
    """A truncated sheet must not report the cap as its length."""
    long_text = "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2. " * 700
    pdf = _pdf(tmp_path, "dense.pdf", text=long_text)
    cov = scan_sheets([pdf])
    assert cov.sheets, "prescan produced no sheets"
    sheet = cov.sheets[0]
    assert sheet.text_chars_in_prompt <= SHEET_TEXT_MAX_CHARS + 64
    assert sheet.text_chars_total > SHEET_TEXT_MAX_CHARS
    assert sheet.truncated is True
    assert sheet.chars_past_cap == sheet.text_chars_total - SHEET_TEXT_MAX_CHARS
    assert sheet.chars_past_cap > 0


def test_short_sheet_is_not_reported_as_truncated(tmp_path):
    pdf = _pdf(tmp_path, "short.pdf", text="SHEET FP-101 GENERAL NOTES")
    sheet = scan_sheets([pdf]).sheets[0]
    assert sheet.truncated is False
    assert sheet.chars_past_cap == 0
    assert sheet.text_chars_total == sheet.text_chars_in_prompt


def test_render_populates_text_chars_total_on_both_construction_paths():
    """`from_rendered` must carry the count, not silently drop it."""
    rendered = RenderedSheet(
        ref=_ref(),
        overview=None, tiles=[], page_width_pt=_W, page_height_pt=_H,
        rows=6, cols=6, sheet_text="abc", text_chars_total=99,
    )
    assert SheetGeometry.from_rendered(rendered).text_chars_total == 99


def test_missing_text_chars_total_falls_back_to_the_capped_length(monkeypatch):
    """An older geometry (None) must not be reported as a zero-length sheet.

    Exercises the real fallback in ``scan_sheets`` by feeding the prescan a
    geometry that predates the field, as a cached/hand-built one would be.
    """
    import measure_evidence_coverage as mod

    geom = _geom(words=[(0.0, 0.0, 1.0, 1.0, "w", 0, 0, 0)], text="hello")
    geom.text_chars_total = None
    monkeypatch.setattr(
        "drawing_analyzer.render.iter_sheet_prescan",
        lambda paths, **kw: iter([(geom.ref, "identity", geom)]),
    )
    # The scan now pre-filters unopenable sources, so the stub must be reachable.
    monkeypatch.setattr(
        "drawing_analyzer.render.list_sheets", lambda paths, **kw: [geom.ref],
    )
    sheet = mod.scan_sheets([Path("s.pdf")]).sheets[0]
    assert sheet.text_chars_total == len("hello")
    assert sheet.truncated is False
    assert sheet.chars_past_cap == 0


def test_cross_qc_budget_accounting(tmp_path):
    long_text = "GENERAL NOTE LINE NUMBER SEVENTEEN. " * 400   # > 4,000 chars
    pdf = _pdf(tmp_path, "budget.pdf", text=long_text)
    cov = scan_sheets([pdf])
    sheet = cov.sheets[0]
    assert sheet.over_cross_qc_budget is True
    assert sheet.cross_qc_chars_omitted > 0
    assert cov.cross_qc_chars_omitted == sheet.cross_qc_chars_omitted


def test_sharded_path_is_reported_as_an_upper_bound(tmp_path):
    small = _pdf(tmp_path, "small.pdf", text="A", pages=3)
    assert scan_sheets([small]).takes_sharded_path is False


def test_unreadable_source_is_reported_not_raised(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf at all")
    cov = scan_sheets([bad])
    assert cov.sheets == []
    assert cov.unreadable_sources, "an unreadable source must be disclosed"


# --------------------------------------------------------------------------- #
# §7.1 — survivors are never the discard rate
# --------------------------------------------------------------------------- #


def _export(tmp_path: Path, findings: list[dict], manifest: dict | None = None) -> Path:
    d = tmp_path / "export"
    d.mkdir()
    (d / "findings.json").write_text(json.dumps(findings), encoding="utf-8")
    if manifest is not None:
        (d / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


def test_surviving_findings_roll_up_anchor_tiers(tmp_path):
    export = _export(tmp_path, [
        {"sources": ["cross_qc"], "source_quote": "PV-3",
         "anchor": {"status": "EXACT"},
         "also_on": [{"source_quote": "PV-3", "anchor": {"status": "FUZZY"}}]},
        {"sources": ["cross_qc"], "source_quote": "",
         "anchor": {"status": "UNANCHORED"}, "also_on": []},
        {"sources": ["critique"], "source_quote": "not cross-sheet",
         "anchor": {"status": "EXACT"}},
    ])
    out = read_surviving_findings(export)
    assert out["available"] is True
    assert out["cross_sheet_findings"] == 2
    assert out["primary_anchor_tiers"] == {"EXACT": 1, "UNANCHORED": 1}
    assert out["leg_anchor_tiers"] == {"FUZZY": 1}
    assert (out["with_source_quote"], out["without_source_quote"]) == (1, 1)


def test_surviving_findings_are_labelled_as_not_a_discard_rate(tmp_path):
    export = _export(tmp_path, [])
    out = read_surviving_findings(export)
    assert "not a discard rate" in out["note"].lower()


def test_report_states_the_discard_rate_is_unmeasured():
    """§7.3: the deliverable must label the tier and refuse the conflation."""
    report = summarize(scan_sheets([]), None, None)
    assert report["tier"].startswith("7.1")
    assert "discard_rate" in report["not_measured_here"]
    text = render_text(report)
    assert "not the discard rate" in text or "not measured here" in text.lower()


def test_missing_export_artifacts_degrade_cleanly(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert read_surviving_findings(empty)["available"] is False
    assert read_run_completeness(empty)["available"] is False


def test_corrupt_findings_json_is_reported_not_raised(tmp_path):
    d = tmp_path / "export"
    d.mkdir()
    (d / "findings.json").write_text("{not json", encoding="utf-8")
    out = read_surviving_findings(d)
    assert out["available"] is False and "error" in out


def test_run_completeness_reads_the_real_manifest_shape(tmp_path):
    """`build_run_manifest` nests these under a root `status` object.

    A flat lookup silently reported nothing for every export the application
    actually writes.
    """
    export = _export(tmp_path, [], manifest={
        "status": {
            "qc_status": "PARTIAL", "qc_status_label": "partial",
            "coverage_status": "COMPLETE", "sheet_count": 44, "ok_sheet_count": 44,
        },
        "stages": [
            {"stage": "critique", "status": "COMPLETE"},
            {"stage": "cross_qc", "status": "PARTIAL", "calls_planned": 3},
        ],
    })
    out = read_run_completeness(export)
    assert out["qc_status"] == "PARTIAL"
    assert out["coverage_status"] == "COMPLETE"
    assert out["sheet_count"] == 44
    assert out["cross_qc_stage"]["calls_planned"] == 3


def test_run_completeness_still_reads_a_flat_manifest(tmp_path):
    """Fallback for a hand-built manifest; not the shipped shape."""
    export = _export(tmp_path, [], manifest={
        "qc_status": "COMPLETE", "coverage_status": "INCOMPLETE",
    })
    out = read_run_completeness(export)
    assert out["qc_status"] == "COMPLETE"
    assert out["coverage_status"] == "INCOMPLETE"


def test_stage_entries_keyed_by_name_are_still_found(tmp_path):
    export = _export(tmp_path, [], manifest={
        "stages": [{"name": "cross_qc", "status": "COMPLETE"}],
    })
    assert read_run_completeness(export)["cross_qc_stage"]["status"] == "COMPLETE"


# --------------------------------------------------------------------------- #
# §7.2 item 3 — the join that run-level totals cannot support
# --------------------------------------------------------------------------- #


def test_discard_rate_joins_per_sheet_counts_onto_classification(tmp_path):
    cov = SetCoverage()
    cov.sheets = [
        SheetCoverage(source_id="SRC-0001", page_index=0, sheet_id="FP-101",
                      width_pt=_W, height_pt=_H, word_count=500,
                      text_chars_total=900, text_chars_in_prompt=900,
                      truncated=False, chars_past_cap=0, total_tiles=36,
                      word_free_tiles=1, word_free_fraction=0.03,
                      classification="vector", over_cross_qc_budget=False,
                      cross_qc_chars_omitted=0),
        SheetCoverage(source_id="SRC-0001", page_index=1, sheet_id="AS-BUILT",
                      width_pt=_W, height_pt=_H, word_count=0,
                      text_chars_total=0, text_chars_in_prompt=0,
                      truncated=False, chars_past_cap=0, total_tiles=36,
                      word_free_tiles=36, word_free_fraction=1.0,
                      classification="textless", over_cross_qc_budget=False,
                      cross_qc_chars_omitted=0),
    ]
    completeness = {"discards": {"by_sheet": {
        "SRC-0001:p0": {"facts_ungrounded_quote_text_bearing_sheet": 2},
        "SRC-0001:p1": {"facts_ungrounded_quote_textless_sheet": 7},
        "SRC-9999:p3": {"facts_no_quote": 1},
    }}}
    out = discard_rate_by_classification(cov, completeness)
    assert out["available"] is True
    assert out["by_classification"]["vector"] == {
        "facts_ungrounded_quote_text_bearing_sheet": 2}
    assert out["by_classification"]["textless"] == {
        "facts_ungrounded_quote_textless_sheet": 7}
    # A key with no matching sheet is surfaced, never silently folded in.
    assert out["unmatched_sheet_keys"] == ["SRC-9999:p3"]
    assert "unmatched_sheet_key" in out["by_classification"]


def test_discard_rate_is_unavailable_without_an_instrumented_run(tmp_path):
    out = discard_rate_by_classification(SetCoverage(), {"discards": None})
    assert out["available"] is False
    assert "7.2" in out["note"]


# --------------------------------------------------------------------------- #
# Finding 3 — one bad source must not erase the others
# --------------------------------------------------------------------------- #


def test_a_corrupt_pdf_does_not_erase_earlier_good_scans(tmp_path):
    """The regression: `list()` over the whole generator lost every page."""
    good = _pdf(tmp_path, "good.pdf", text="FP-101 GENERAL NOTES")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    cov = scan_sheets([good, bad])
    assert len(cov.sheets) == 1, "the readable source must survive"
    assert any("bad.pdf" in e for e in cov.unreadable_sources)


def test_a_corrupt_pdf_listed_first_still_leaves_the_good_one(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    good = _pdf(tmp_path, "good.pdf", text="FP-102 PLAN")
    cov = scan_sheets([bad, good])
    assert len(cov.sheets) == 1
    assert any("bad.pdf" in e for e in cov.unreadable_sources)


def test_report_never_contains_source_text(tmp_path):
    secret = "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2"
    pdf = _pdf(tmp_path, "quiet.pdf", text=secret * 20)
    report = summarize(scan_sheets([pdf]), None, None)
    blob = json.dumps(report)
    assert secret not in blob
    assert str(pdf) not in blob and pdf.name not in blob


# --------------------------------------------------------------------------- #
# §7.2 — discard counters at the two host-side grounding sites
# --------------------------------------------------------------------------- #


def _entry(handle: str, *, text: str) -> dict:
    geom = _geom(words=[(0.0, 0.0, 1.0, 1.0, "w", 0, 0, 0)] if text else [], text=text)
    geom.ref = _ref(f"{handle}.pdf", f"SRC-{handle}")
    return {handle: (handle, geom)}


def test_sheet_is_textless_is_about_text_not_rasterness():
    assert _sheet_is_textless(_geom(text="")) is True
    assert _sheet_is_textless(_geom(text="   ")) is True
    assert _sheet_is_textless(_geom(words=[(0, 0, 1, 1, "x", 0, 0, 0)], text="x")) is False


def test_ungrounded_leg_on_a_textless_sheet_is_counted_separately():
    entries = {**_entry("S001", text=""), **_entry("S002", text="PV-3 SERVES HALL 2")}
    counts = CrossQCDiscardCounts()
    item = {
        "category": "conflict", "severity": "high", "text": "mismatch",
        "sheet_handle": "S001", "source_quote": "TRANSCRIBED FROM PIXELS",
        "also_on": [{"sheet_handle": "S002", "source_quote": "PV-3 SERVES HALL 2"}],
    }
    assert _finding_from_handles(item, entries, counts) is None
    assert counts.legs_ungrounded_quote_textless_sheet == 1
    assert counts.legs_ungrounded_quote_text_bearing_sheet == 0
    assert counts.findings_dropped_under_two_legs == 1


def test_ungrounded_leg_on_a_text_bearing_sheet_is_counted_separately():
    entries = {**_entry("S001", text="SOME OTHER TEXT"),
               **_entry("S002", text="PV-3 SERVES HALL 2")}
    counts = CrossQCDiscardCounts()
    item = {
        "category": "conflict", "severity": "high", "text": "mismatch",
        "sheet_handle": "S001", "source_quote": "QUOTE THAT IS NOT PRESENT",
        "also_on": [{"sheet_handle": "S002", "source_quote": "PV-3 SERVES HALL 2"}],
    }
    _finding_from_handles(item, entries, counts)
    assert counts.legs_ungrounded_quote_text_bearing_sheet == 1
    assert counts.legs_ungrounded_quote_textless_sheet == 0


def test_leg_without_a_quote_is_counted_as_accepted_unchecked():
    """Trigger 3: the guard short-circuits, so this leg is trusted with no check."""
    entries = {**_entry("S001", text="PV-3 SERVES HALL 2"),
               **_entry("S002", text="OTHER SHEET TEXT")}
    counts = CrossQCDiscardCounts()
    item = {
        "category": "conflict", "severity": "high", "text": "mismatch",
        "sheet_handle": "S001", "source_quote": "PV-3 SERVES HALL 2",
        "also_on": [{"sheet_handle": "S002", "source_quote": ""}],
    }
    assert _finding_from_handles(item, entries, counts) is not None
    assert counts.legs_accepted_without_quote == 1
    assert counts.legs_accepted_grounded == 1


def test_unresolved_handle_is_counted():
    entries = _entry("S001", text="PV-3 SERVES HALL 2")
    counts = CrossQCDiscardCounts()
    item = {
        "category": "conflict", "severity": "high", "text": "x",
        "sheet_handle": "S001", "source_quote": "PV-3 SERVES HALL 2",
        "also_on": [{"sheet_handle": "S999", "source_quote": "anything"}],
    }
    _finding_from_handles(item, entries, counts)
    assert counts.legs_unresolved_handle == 1


def test_fact_discards_are_counted_by_reason():
    entries = {**_entry("S001", text=""), **_entry("S002", text="PV-3 SERVES HALL 2")}
    counts = CrossQCDiscardCounts()
    facts = _parse_facts({"facts": [
        {"sheet_handle": "S001", "exact_quote": "FROM PIXELS"},          # textless
        {"sheet_handle": "S002", "exact_quote": "NOT ON THIS SHEET"},    # text-bearing
        {"sheet_handle": "S002", "exact_quote": ""},                     # no quote
        {"sheet_handle": "S404", "exact_quote": "whatever"},             # bad handle
        {"sheet_handle": "S002", "exact_quote": "PV-3 SERVES HALL 2"},   # accepted
    ]}, entries, {}, counts)
    assert len(facts) == 1
    assert counts.facts_ungrounded_quote_textless_sheet == 1
    assert counts.facts_ungrounded_quote_text_bearing_sheet == 1
    assert counts.facts_no_quote == 1
    assert counts.facts_unresolved_handle == 1
    assert counts.facts_accepted == 1


def test_counters_are_optional_and_change_no_behaviour():
    """Passing no counter must produce byte-identical parsing results."""
    entries = {**_entry("S001", text="PV-3 SERVES HALL 2"),
               **_entry("S002", text="PV-3 SERVES HALL 2")}
    item = {
        "category": "conflict", "severity": "high", "text": "x",
        "sheet_handle": "S001", "source_quote": "PV-3 SERVES HALL 2",
        "also_on": [{"sheet_handle": "S002", "source_quote": "PV-3 SERVES HALL 2"}],
    }
    with_counts = _finding_from_handles(item, entries, CrossQCDiscardCounts())
    without = _finding_from_handles(item, entries)
    assert with_counts is not None and without is not None
    assert with_counts.to_dict() == without.to_dict()


def test_counts_merge_and_round_trip():
    a = CrossQCDiscardCounts(legs_unresolved_handle=1, facts_accepted=2)
    a.merge(CrossQCDiscardCounts(legs_unresolved_handle=3))
    assert a.legs_unresolved_handle == 4 and a.facts_accepted == 2
    assert CrossQCDiscardCounts.from_dict(a.to_dict()) == a


def test_unknown_keys_from_an_older_payload_are_ignored():
    restored = CrossQCDiscardCounts.from_dict({"facts_accepted": 5, "gone_field": 9})
    assert restored.facts_accepted == 5


def test_counters_never_carry_quote_text():
    """Counts and reasons only — the whole point of a count-only field."""
    entries = {**_entry("S001", text=""), **_entry("S002", text="X")}
    counts = CrossQCDiscardCounts()
    _parse_facts({"facts": [
        {"sheet_handle": "S001", "exact_quote": "SECRET PROPRIETARY STRING"},
    ]}, entries, {}, counts)
    payload = counts.to_dict()
    assert "SECRET" not in json.dumps(payload)
    by_sheet = payload.pop("by_sheet")
    assert all(isinstance(v, int) for v in payload.values())
    for key, counters in by_sheet.items():
        assert re.fullmatch(r"[^/\\]+:p\d+", key), key      # portable, never a path
        assert all(isinstance(v, int) for v in counters.values())


def test_discards_are_attributed_to_the_sheet_that_caused_them():
    """§7.2 item 3 needs a join key; run-level totals alone cannot supply one."""
    entries = {**_entry("S001", text=""), **_entry("S002", text="PV-3 SERVES HALL 2")}
    counts = CrossQCDiscardCounts()
    _parse_facts({"facts": [
        {"sheet_handle": "S001", "exact_quote": "FROM PIXELS"},
        {"sheet_handle": "S002", "exact_quote": "NOT ON THIS SHEET"},
        {"sheet_handle": "S002", "exact_quote": "PV-3 SERVES HALL 2"},
    ]}, entries, {}, counts)
    by_sheet = counts.to_dict()["by_sheet"]
    assert by_sheet["SRC-S001:p0"] == {"facts_ungrounded_quote_textless_sheet": 1}
    assert by_sheet["SRC-S002:p0"] == {
        "facts_ungrounded_quote_text_bearing_sheet": 1, "facts_accepted": 1,
    }


def test_sheet_counter_key_is_portable_and_never_a_path():
    geom = _geom(text="x")
    assert sheet_counter_key(geom) == "SRC-0001:p0"
    geom.ref = SheetRef(pdf_path=Path("/abs/secret/plans.pdf"), page_index=4,
                        source_name="plans.pdf", page_count=9, source_id="")
    key = sheet_counter_key(geom)
    assert key == "plans:p4"                 # basename stem, no directory
    assert "/" not in key and "\\" not in key


def test_merge_folds_per_sheet_counts_too():
    a = CrossQCDiscardCounts()
    a.by_sheet = {"SRC-0001:p0": {"facts_accepted": 1}}
    a.facts_accepted = 1
    b = CrossQCDiscardCounts()
    b.by_sheet = {"SRC-0001:p0": {"facts_accepted": 2}, "SRC-0002:p1": {"facts_no_quote": 1}}
    b.facts_accepted, b.facts_no_quote = 2, 1
    a.merge(b)
    assert a.facts_accepted == 3
    assert a.by_sheet["SRC-0001:p0"]["facts_accepted"] == 3
    assert a.by_sheet["SRC-0002:p1"]["facts_no_quote"] == 1
    assert CrossQCDiscardCounts.from_dict(a.to_dict()) == a
