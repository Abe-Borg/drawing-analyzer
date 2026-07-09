"""Phase 15 tests: QC numbering, markup richness, index pages, citation check.

The pure pieces (id assignment, clear-band computation, citation parsing/harvest)
run without PyMuPDF; the PDF-writing pieces build synthetic PDFs and are gated on
it, mirroring ``test_drawing_annotate.py``. Hermetic — no network, no key.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from drawing_analyzer.models import (
    Anchor,
    Citation,
    Finding,
    Verification,
    assign_qc_ids,
)

# --------------------------------------------------------------------------- #
# QC-id assignment (pure)
# --------------------------------------------------------------------------- #


def _f(text, *, source="a.pdf", page=0, rect=None, hint="", sev="medium",
       cat="code", status="VERIFIED", quote="q", refs=None, tile=None):
    anchor = Anchor(status="EXACT", rect_pdf=list(rect), method="t") if rect else Anchor()
    return Finding(
        sheet_id="S-1", source_name=source, page_index=page, category=cat,
        severity=sev, text=text, source_quote=quote, tile=tile,
        refs=list(refs or []), anchor_hint=hint, anchor=anchor,
        verification=Verification(status=status),
    )


def test_qc_ids_ordered_sheet_then_position():
    a = _f("second on page", rect=[10, 500, 60, 520])     # lower on the page
    b = _f("first on page", rect=[10, 40, 60, 60])        # top of the page
    c = _f("later sheet", source="b.pdf", rect=[5, 5, 20, 20])
    d = _f("sheet-level, sorts last on its sheet", hint="SHEET")
    assign_qc_ids([a, b, c, d])
    assert b.qc_id == "QC-001"      # top of a.pdf
    assert a.qc_id == "QC-002"      # below it
    assert d.qc_id == "QC-003"      # rect-less: after anchored ones on a.pdf
    assert c.qc_id == "QC-004"      # next source file


def test_qc_ids_stable_regardless_of_input_order():
    def build():
        return [
            _f("one", rect=[10, 40, 60, 60]),
            _f("two", rect=[10, 500, 60, 520]),
            _f("three", source="b.pdf", rect=[5, 5, 20, 20]),
            _f("four", hint="SHEET"),
        ]

    base = build()
    assign_qc_ids(base)
    expected = {f.text: f.qc_id for f in base}
    for seed in (1, 7, 42):
        shuffled = build()
        random.Random(seed).shuffle(shuffled)
        assign_qc_ids(shuffled)
        assert {f.text: f.qc_id for f in shuffled} == expected


def test_qc_id_round_trips_through_dict():
    f = _f("x", rect=[1, 2, 3, 4], refs=["NFPA 13"])
    f.citation = Citation(status="CHECKED_SUPPORTS", note="ok", edition_notes="2019+")
    assign_qc_ids([f])
    d = f.to_dict()
    back = Finding.from_dict(d)
    assert back.qc_id == f.qc_id == "QC-001"
    assert back.citation is not None and back.citation.status == "CHECKED_SUPPORTS"
    # A finding without a citation omits the key entirely (compact JSON).
    bare = _f("y")
    assert "citation" not in bare.to_dict()
    assert Finding.from_dict(bare.to_dict()).citation is None


# --------------------------------------------------------------------------- #
# Clear-margin-band computation (pure)
# --------------------------------------------------------------------------- #

from drawing_analyzer.annotate import find_clear_band  # noqa: E402

W, H = 3168.0, 2448.0


def _w(x, y, text="w", width=64, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _overlaps(band, word):
    bx0, by0, bx1, by1 = band
    x0, y0, x1, y1 = float(word[0]), float(word[1]), float(word[2]), float(word[3])
    return x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0


def test_clear_band_avoids_every_word():
    # Words dense in the top half; a clean gap in the lower middle; more words at
    # the very bottom (a title strip). The band must land in the clean gap.
    words = [_w(50 + 200 * i, 40 + 30 * j) for i in range(10) for j in range(30)]
    words += [_w(50 + 200 * i, H - 60) for i in range(10)]
    band = find_clear_band(words, W, H)
    assert all(not _overlaps(band, w) for w in words)
    bx0, by0, bx1, by1 = band
    assert by1 - by0 >= 40           # a usable height
    assert bx1 - bx0 > 0.8 * W       # spans (most of) the sheet width


def test_clear_band_falls_back_without_words():
    band = find_clear_band([], W, H)
    bx0, by0, bx1, by1 = band
    assert 0 < bx0 < bx1 < W and 0 < by0 < by1 <= H


# --------------------------------------------------------------------------- #
# Citation check (pure parsing + fake-client pass)
# --------------------------------------------------------------------------- #

from drawing_analyzer.citation_check import (  # noqa: E402
    check_citations,
    harvest_code_editions,
    web_search_tool,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage  # noqa: E402


class _Geom:
    def __init__(self, text):
        self.sheet_text = text


def test_harvest_code_editions_both_orders_and_dedup():
    geoms = [
        _Geom("ALL WORK PER NFPA 13, 2016 EDITION. SEE THE 2022 CBC."),
        _Geom("NFPA 13-2016 (repeat) AND NFPA 72 2019"),
    ]
    assert harvest_code_editions(geoms) == ["NFPA 13 2016", "CBC 2022", "NFPA 72 2019"]


def test_web_search_tool_type_is_current_and_overridable(monkeypatch):
    assert web_search_tool()["type"] == "web_search_20260209"
    assert web_search_tool()["name"] == "web_search"
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_TOOL_TYPE", "web_search_99990101")
    assert web_search_tool()["type"] == "web_search_99990101"


class _CitationClient:
    """Scripted per-call responses; captures request kwargs."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.captured = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.captured.append(kw)
                text = outer._texts[min(len(outer.captured) - 1, len(outer._texts) - 1)]
                return FakeMessage(
                    content=[FakeTextBlock(text=text)],
                    usage=FakeUsage(input_tokens=200, output_tokens=40),
                )

        self.messages = _Msgs()


def _verdict_block(status, note="n", editions="e"):
    return "searched...\n```json\n" + json.dumps(
        {"status": status, "note": note, "edition_notes": editions}
    ) + "\n```"


def test_check_citations_attaches_verdicts_per_unique_ref():
    f1 = _f("cites table", refs=["NFPA 13 Table 13.2.1"])
    f2 = _f("cites same table", refs=["NFPA 13 Table 13.2.1"])
    f3 = _f("cites relief", refs=["NFPA 13 §8.1.2"])
    client = _CitationClient([
        _verdict_block("CHECKED_MISMATCH", note="2016 numbering", editions="4.3.1.7 in 2019+"),
        _verdict_block("CHECKED_SUPPORTS", note="supports"),
    ])
    res = check_citations(
        [f1, f2, f3], [_Geom("PER NFPA 13, 2016 EDITION")],
        client=client, sleep=lambda *_: None,
    )
    # One call per UNIQUE ref (two, not three).
    assert res.checked == 2 and len(client.captured) == 2
    assert res.mismatches == 1 and res.supports == 1
    assert f1.citation is not None and f1.citation.status == "CHECKED_MISMATCH"
    assert f2.citation is not None and f2.citation.status == "CHECKED_MISMATCH"
    assert f3.citation is not None and f3.citation.status == "CHECKED_SUPPORTS"
    # The request carried the web-search tool and the harvested edition.
    kw = client.captured[0]
    assert kw["tools"][0]["name"] == "web_search"
    user_text = kw["messages"][0]["content"]
    assert "NFPA 13 2016" in user_text


def test_check_citations_garbled_reply_degrades_to_unchecked():
    f = _f("cites", refs=["CMC 310"])
    client = _CitationClient(["no json here at all"])
    res = check_citations([f], [], client=client, sleep=lambda *_: None)
    assert res.unchecked == 1
    assert f.citation is not None and f.citation.status == "UNCHECKED"


def test_check_citations_no_refs_is_a_noop():
    f = _f("no refs")
    res = check_citations([f], [], client=None)
    assert res.checked == 0 and f.citation is None


# --------------------------------------------------------------------------- #
# PDF-writing pieces (need PyMuPDF)
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import (  # noqa: E402
    INDEX_PAGE_LABEL,
    annotate_pdf,
    count_annotations,
    count_annotations_by_type,
)


def _pdf(tmp_path, name="M-101.pdf", pages=1):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=792, height=612)
        page.insert_text((80, 120), "VAV-3 SERVES ROOM 120")
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _meta(words=None):
    return {0: {
        "words": list(words or []), "rows": 2, "cols": 2,
        "page_width_pt": 792.0, "page_height_pt": 612.0, "overlap_frac": 0.08,
    }}


def test_reviewed_pdf_has_tag_index_and_correct_link_targets(tmp_path):
    src = _pdf(tmp_path, pages=2)
    findings = [
        _f("page one issue", source="M-101.pdf", page=0, rect=[10, 10, 60, 30]),
        _f("page two issue", source="M-101.pdf", page=1, rect=[100, 100, 180, 130]),
    ]
    assign_qc_ids(findings)
    out = tmp_path / "M-101_reviewed.pdf"
    written = annotate_pdf(src, findings, out)
    assert written == 4                      # 2 clouds + 2 QC tags
    assert count_annotations(out) == written  # round-trip intact

    doc = pymupdf.open(str(out))
    try:
        assert doc.page_count == 3            # 1 index + 2 source pages
        assert INDEX_PAGE_LABEL in doc[0].get_text()
        assert "QC-001" in doc[0].get_text() and "QC-002" in doc[0].get_text()
        links = sorted(doc[0].get_links(), key=lambda l: l["from"].y0)
        assert len(links) == 2
        # Index pages shift the originals by one: page 0 -> 1, page 1 -> 2.
        assert links[0]["page"] == 1 and links[1]["page"] == 2
        # The link lands at the finding's anchor point.
        assert abs(links[1]["to"].x - 100) < 1 and abs(links[1]["to"].y - 100) < 1
        # The QC tag rides beside the cloud, in the severity color.
        types = count_annotations_by_type(out)
        assert types.get("Square") == 2 and types.get("FreeText") == 2
    finally:
        doc.close()


def test_margin_callouts_stack_in_band_and_never_overlap_words(tmp_path):
    src = _pdf(tmp_path)
    # Words fill the top of the sheet; the band must sit clear of all of them.
    words = [_w(40 + 150 * i, 20 + 24 * j, width=100, height=12)
             for i in range(5) for j in range(10)]
    absences = [
        _f(f"expected item {i}; not found on this sheet", source="M-101.pdf",
           hint="SHEET", tile=[1, 1], quote="")
        for i in range(3)
    ]
    assign_qc_ids(absences)
    out = tmp_path / "M-101_reviewed.pdf"
    written = annotate_pdf(src, absences, out, sheet_meta=_meta(words))
    # 3 callout boxes + 3 leader lines (tile known).
    types = count_annotations_by_type(out)
    assert types.get("FreeText") == 3 and types.get("Line") == 3
    assert written == 6

    doc = pymupdf.open(str(out))
    try:
        page = doc[1]                          # after the index page
        boxes = [a.rect for a in page.annots() if a.type[1] == "FreeText"]
        assert len(boxes) == 3
        for box in boxes:
            for w in words:
                wrect = pymupdf.Rect(w[0], w[1], w[2], w[3])
                assert not box.intersects(wrect), f"callout {box} overlaps word {wrect}"
        # Stacked: boxes don't overlap each other either.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                assert not boxes[i].intersects(boxes[j])
    finally:
        doc.close()


def test_deterministic_solid_model_cloudy_unverified_dashed(tmp_path):
    src = _pdf(tmp_path)
    verified = _f("model", source="M-101.pdf", rect=[10, 10, 60, 30], status="VERIFIED")
    determ = _f("auditor", source="M-101.pdf", rect=[100, 100, 160, 130],
                status="DETERMINISTIC", cat="reference")
    uncertain = _f("maybe", source="M-101.pdf", rect=[200, 200, 260, 230],
                   status="UNCERTAIN", cat="question")
    assign_qc_ids([verified, determ, uncertain])
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, [verified, determ, uncertain], out, include_unverified=True)

    doc = pymupdf.open(str(out))
    try:
        # Snapshot properties during iteration — PyMuPDF unbinds an annot object
        # once the generator advances past it.
        squares = {}
        for a in doc[1].annots():
            if a.type[1] == "Square":
                squares[a.info.get("content", "")[:40]] = (
                    dict(a.border), a.info.get("content", ""), dict(a.colors)
                )
        border, _c, _cl = next(v for k, v in squares.items() if "model" in k)
        assert border.get("clouds") == 2                          # revision cloud
        border, _c, _cl = next(v for k, v in squares.items() if "auditor" in k)
        assert border.get("clouds") in (0, -1)                    # solid
        assert not border.get("dashes")
        border, content, colors = next(v for k, v in squares.items() if "maybe" in k)
        assert tuple(border.get("dashes") or ()) == (4, 3)        # dashed
        assert content.startswith("[UNVERIFIED]")
        # question category renders blue regardless of severity.
        assert abs(colors["stroke"][2] - 0.82) < 0.01
    finally:
        doc.close()


def test_popup_carries_the_full_template(tmp_path):
    src = _pdf(tmp_path)
    f = _f("clearance issue", source="M-101.pdf", rect=[10, 10, 60, 30],
           refs=["CMC 310"], quote="VAV-3")
    f.verification = Verification(status="VERIFIED", note="seen", evidence_png="evidence/x.png")
    f.citation = Citation(status="CHECKED_MISMATCH", note="renumbered", edition_notes="2019+")
    f.reproduced = False
    assign_qc_ids([f])
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, [f], out)
    doc = pymupdf.open(str(out))
    try:
        square = next(a for a in doc[1].annots() if a.type[1] == "Square")
        content = square.info.get("content", "")
        assert content.startswith("QC-001: clearance issue")
        assert 'Quote: "VAV-3"' in content
        assert "Verification: VERIFIED — seen" in content
        assert "Refs: CMC 310" in content
        assert "Citation check: CHECKED_MISMATCH — renumbered (editions: 2019+)" in content
        assert "Reproduced: no" in content
        assert "Evidence: evidence/x.png" in content
        assert f"Finding ID: {f.id}" in content
    finally:
        doc.close()


def test_appendix_page_off_by_default_and_on_when_asked(tmp_path):
    src = _pdf(tmp_path)
    f = _f("x", source="M-101.pdf", rect=[10, 10, 60, 30])
    assign_qc_ids([f])
    out1 = tmp_path / "r1.pdf"
    annotate_pdf(src, [f], out1)
    doc = pymupdf.open(str(out1))
    assert doc.page_count == 2                 # index + source; no appendix
    doc.close()

    out2 = tmp_path / "r2.pdf"
    annotate_pdf(src, [f], out2, include_appendix=True,
                 audit_stats={"arithmetic_checked": 4, "arithmetic_matched": 4,
                              "references_resolved": 9})
    doc = pymupdf.open(str(out2))
    try:
        assert doc.page_count == 3
        tail = doc[2].get_text()
        assert "CHECKED AND CONSISTENT" in tail
        assert "4 of 4" in tail and "9" in tail
    finally:
        doc.close()


def test_rejected_never_inked_even_with_qc_id(tmp_path):
    src = _pdf(tmp_path)
    rejected = _f("wrong", source="M-101.pdf", rect=[10, 10, 60, 30], status="REJECTED")
    assign_qc_ids([rejected])
    out = tmp_path / "r.pdf"
    written = annotate_pdf(src, [rejected], out, include_unverified=True)
    assert written == 0
    doc = pymupdf.open(str(out))
    assert doc.page_count == 1                 # nothing inked -> no index either
    doc.close()
