"""Tests for ``html_report`` — rendering a drawing digest to a navigable HTML page.

Fully hermetic: no tkinter, no PyMuPDF, no network. The context and its sheets
are duck-typed fakes exposing only the attributes the renderer reads (mirroring
``test_drawing_export``). Covers the Markdown subset renderer, section / header
parsing, coordination extraction, and the assembled report.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from drawing_analyzer import html_report as hr

NOW = datetime(2026, 6, 9, 9, 30, 0)
SRC = "Weld_County_Mechanical_Permit_Set.pdf"

M101 = """Sheet M-101 - Mechanical - Level 1 HVAC Plan

**Scope / systems shown**
VAV boxes serving Rooms 120-124.

**Equipment & schedules**

| Tag | Type | CFM |
| --- | --- | --- |
| VAV-3 | Single duct | 450 |

**Coordination / cross-discipline items**
- Duct penetration at grid C-4 must coordinate with structural beam.
- Danger: <script>alert(1)</script> must be escaped.
"""

P201 = """Sheet P-201 - Plumbing-Fire - Underground Plumbing

**Scope**
Underground sanitary and FP mains.

- **Coordination / cross-discipline conflict**: WH-1 vent conflicts with FP-2 main at grid B-2.
"""

SYNTHESIS = """**Systems spanning sheets**
VAV-3 appears on the M-101 plan and the M-501 schedule.

**Cross-sheet / cross-discipline conflicts**
- VAV-3 capacity differs: 450 CFM on M-101 vs 500 CFM on M-501.
"""


@dataclass
class _Ref:
    source_name: str
    page_index: int
    page_count: int

    @property
    def display_label(self) -> str:
        return f"{self.source_name} (page {self.page_index + 1}/{self.page_count})"


@dataclass
class _Sheet:
    ref: _Ref
    text: str = ""
    error: str | None = None
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


@dataclass
class _Ctx:
    sheets: list
    synthesis_text: str = ""
    combined_text: str = "x"
    errors: list = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def sheet_count(self) -> int:
        return len(self.sheets)

    @property
    def ok_sheet_count(self) -> int:
        return sum(1 for s in self.sheets if s.ok)

    @property
    def cached_sheet_count(self) -> int:
        return sum(1 for s in self.sheets if s.cached)


def _full_ctx() -> _Ctx:
    return _Ctx(
        sheets=[
            _Sheet(_Ref(SRC, 0, 3), text=M101, input_tokens=1200, output_tokens=600),
            _Sheet(_Ref(SRC, 1, 3), text=P201, cached=True),
            _Sheet(_Ref(SRC, 2, 3), error="529 overloaded (server temporarily unavailable — try again)"),
        ],
        synthesis_text=SYNTHESIS,
        total_input_tokens=1200,
        total_output_tokens=600,
    )


# --------------------------------------------------------------------------- #
# render_markdown
# --------------------------------------------------------------------------- #


def test_render_markdown_headings_offset_by_base_level():
    assert hr.render_markdown("# Title", base_level=3) == "<h3>Title</h3>"
    assert hr.render_markdown("# Title", base_level=4) == "<h4>Title</h4>"
    # Levels are clamped at h6.
    assert hr.render_markdown("###### Deep", base_level=4) == "<h6>Deep</h6>"


def test_render_markdown_inline_formatting():
    out = hr.render_markdown("A **bold** and *italic* and `code` word.")
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out
    assert "<code>code</code>" in out


def test_render_markdown_escapes_html():
    out = hr.render_markdown("danger <script>alert(1)</script> & co")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "&amp;" in out


def test_render_markdown_nested_list():
    out = hr.render_markdown("- a\n  - b\n- c")
    assert out == "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>"


def test_render_markdown_ordered_list():
    out = hr.render_markdown("1. first\n2. second")
    assert out == "<ol><li>first</li><li>second</li></ol>"


def test_render_markdown_table():
    out = hr.render_markdown("| Tag | CFM |\n| --- | --- |\n| VAV-3 | 450 |")
    assert "<table>" in out
    assert "<th>Tag</th>" in out and "<th>CFM</th>" in out
    assert "<td>VAV-3</td>" in out and "<td>450</td>" in out


def test_render_markdown_blockquote_and_hr():
    assert "<blockquote>" in hr.render_markdown("> quoted text")
    assert hr.render_markdown("---") == "<hr>"


# --------------------------------------------------------------------------- #
# parse_header
# --------------------------------------------------------------------------- #


def test_parse_header_standard():
    h = hr.parse_header("Sheet M-101 - Mechanical - Level 1 HVAC Plan")
    assert h["number"] == "M-101"
    assert h["discipline"] == "Mechanical"
    assert h["title"] == "Level 1 HVAC Plan"


def test_parse_header_keeps_internal_hyphen_in_discipline():
    h = hr.parse_header("Sheet P-201 - Plumbing-Fire - Underground Plumbing")
    assert h["number"] == "P-201"
    assert h["discipline"] == "Plumbing-Fire"
    assert h["title"] == "Underground Plumbing"


def test_parse_header_strips_markdown_decoration():
    h = hr.parse_header("## **Sheet M-501 - Mechanical - Schedules**")
    assert h["number"] == "M-501"
    assert h["discipline"] == "Mechanical"


def test_parse_header_non_header_returns_blanks():
    h = hr.parse_header("Some prose that is not a header line.")
    assert h == {"number": "", "discipline": "", "title": ""}


# --------------------------------------------------------------------------- #
# split_sections / coordination_sections
# --------------------------------------------------------------------------- #


def test_split_sections_detects_bold_line_and_heading_forms():
    titles = [t for t, _ in hr.split_sections(M101)]
    assert "Scope / systems shown" in titles
    assert "Equipment & schedules" in titles
    assert "Coordination / cross-discipline items" in titles


def test_coordination_sections_matches_heading_form():
    coord = hr.coordination_sections(M101)
    assert len(coord) == 1
    assert "structural beam" in coord[0][1]


def test_coordination_sections_matches_bullet_label_form():
    coord = hr.coordination_sections(P201)
    assert len(coord) == 1
    assert "WH-1 vent conflicts with FP-2 main" in coord[0][1]


def test_coordination_sections_ignores_non_coordination_titles():
    assert hr.coordination_sections("**Scope**\nJust scope, no issues here.") == []


# --------------------------------------------------------------------------- #
# build_html_report
# --------------------------------------------------------------------------- #


def test_build_html_report_is_self_contained_document():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    assert out.startswith("<!doctype html>")
    assert "<style>" in out and "<script>" in out
    # No external assets — the file must work fully offline.
    assert "http://" not in out and "https://" not in out


def test_build_html_report_keeps_all_sheet_content_raw():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    # Every sheet's exact digest is preserved verbatim in a collapsible raw block.
    assert '<details class="raw">' in out
    assert "Duct penetration at grid C-4" in out
    assert "WH-1 vent conflicts with FP-2 main at grid B-2." in out


def test_build_html_report_escapes_digest_content():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_build_html_report_renders_tables_and_disciplines():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    assert "<table>" in out and "<td>VAV-3</td>" in out
    # Discipline parsed from the header line -> badge + filter chip.
    assert 'data-discipline="Mechanical"' in out
    assert 'data-discipline="Plumbing-Fire"' in out
    assert 'data-filter="disc" data-value="Mechanical"' in out


def test_build_html_report_issues_panel_aggregates_findings():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    issues = out[out.index('id="issues"'):out.index('id="overview"')]
    # Failed sheet, set-wide conflict, and per-sheet coordination all surface here.
    assert "Failed sheets (1)" in issues
    assert "529 overloaded" in issues
    assert "Set-wide conflicts" in issues
    assert "VAV-3 capacity differs" in issues
    assert "structural beam" in issues
    assert "WH-1 vent conflicts" in issues


def test_build_html_report_flags_coordination_sheets():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    # Both coordination sheets are marked for the filter chip and TOC.
    assert out.count('data-coord="1"') >= 2
    assert "⚠ Coordination" in out
    # Strong-signal (heading-form) coordination gets an in-body call-out.
    assert 'class="callout coord"' in out


def test_build_html_report_marks_failed_sheet():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    assert 'data-failed="1"' in out
    assert 'class="callout failedc"' in out


def test_build_html_report_includes_synthesis_overview():
    out = hr.build_html_report(_full_ctx(), source_names=[SRC], now=NOW)
    assert 'id="overview"' in out
    assert "Set Overview" in out
    assert "VAV-3 appears on the M-101 plan" in out


def test_build_html_report_empty_issues_note():
    ctx = _Ctx(sheets=[_Sheet(_Ref(SRC, 0, 1), text="Sheet M-1 - Mechanical - Plan\nNothing to flag.")])
    out = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert "No failed sheets, cross-sheet conflicts, or coordination items" in out
    # With no synthesis there is no overview section.
    assert 'id="overview"' not in out


def test_write_html_report_writes_file(tmp_path):
    path = hr.write_html_report(_full_ctx(), tmp_path / "report.html", source_names=[SRC], now=NOW)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")
