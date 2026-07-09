"""Tests for ``html_report`` — the navigable, single-file HTML view of a digest.

Fully hermetic: no tkinter, no PyMuPDF, no network. The context and its sheets
are duck-typed fakes exposing only the attributes the report reads (mirroring
``test_drawing_export``). Covers three layers independently: the section
classifier (drives the filter chips), the small Markdown→HTML renderer (must be
lossless and HTML-safe), and the assembled document.
"""
from __future__ import annotations

from datetime import datetime

from drawing_analyzer import html_report as hr
from drawing_analyzer.models import Anchor, Finding, Verification
from tests.fixtures.fake_context import FakeContext as _Ctx
from tests.fixtures.fake_context import FakeGeometry as _Geom
from tests.fixtures.fake_context import FakeRef as _Ref
from tests.fixtures.fake_context import FakeSheet as _Sheet

SRC = "Weld_County_Mechanical_Permit_Set.pdf"
NOW = datetime(2026, 6, 7, 7, 2, 0)


_OK_DIGEST = (
    "Sheet M-101 - Mechanical - Floor Plan\n\n"
    "**Scope / systems shown**\n"
    "- VAV-3 serves Rm 120\n\n"
    "**Equipment & schedules**\n\n"
    "| Tag | Size |\n"
    "| --- | ---: |\n"
    "| VAV-3 | 10 in |\n\n"
    "**Coordination / cross-discipline items**\n"
    "- Duct penetration at grid `C-4` must agree with structural.\n"
)


def _make_ctx() -> _Ctx:
    sheets = [
        _Sheet(_Ref(SRC, 0, 3), text=_OK_DIGEST, input_tokens=100, output_tokens=50),
        _Sheet(_Ref(SRC, 1, 3), text="WH-1 schedule transcribed", cached=True),
        _Sheet(_Ref(SRC, 2, 3), error="api_error: Internal Server Error"),
    ]
    return _Ctx(
        sheets=sheets,
        synthesis_text=(
            "**Cross-sheet / cross-discipline conflicts**\n"
            "- `VAV-3` scheduled on M-501 but never drawn on M-101.\n"
        ),
        combined_text="# Drawing Set Context Digest\n\nVAV-3 serves Rm 120 <unique-marker>",
        errors=["Weld_County_Mechanical_Permit_Set.pdf (page 3/3): api_error"],
        total_input_tokens=100,
        total_output_tokens=50,
    )


# --------------------------------------------------------------------------- #
# classify_section — what drives the category filter chips
# --------------------------------------------------------------------------- #


def test_classify_section_coordination_and_conflict():
    assert hr.classify_section("Coordination / cross-discipline items") == "coordination"
    # A header that reads as both resolves to conflict (the higher-value output).
    assert hr.classify_section("Cross-sheet / cross-discipline conflicts") == "conflict"
    assert hr.classify_section("Tag cross-references") == "coordination"


def test_classify_section_other_categories():
    assert hr.classify_section("Equipment & schedules") == "equipment"
    assert hr.classify_section("General notes, keynotes, and callouts") == "notes"
    assert hr.classify_section("Key dimensions, elevations, clearances") == "dimensions"
    assert hr.classify_section("Scope / systems shown") == "scope"


def test_classify_section_unknown_and_none():
    assert hr.classify_section(None) == "other"
    assert hr.classify_section("Some unrelated header") == "other"


# --------------------------------------------------------------------------- #
# markdown_to_html — must be lossless and HTML-safe
# --------------------------------------------------------------------------- #


def test_markdown_headings_bold_code():
    assert "<h2>Title</h2>" in hr.markdown_to_html("## Title")
    out = hr.markdown_to_html("This is **bold** and `VAV-3` code")
    assert "<strong>bold</strong>" in out
    assert "<code>VAV-3</code>" in out


def test_markdown_lists_nested_and_ordered():
    out = hr.markdown_to_html("- a\n  - b\n- c")
    assert out.count("<ul>") == 2 and "<li>a<ul><li>b</li></ul></li>" in out
    ordered = hr.markdown_to_html("1. first\n2. second")
    assert "<ol>" in ordered and "<li>first</li>" in ordered


def test_markdown_list_irregular_indent_is_lossless():
    # The model emits inconsistent indentation; no item may ever be dropped. The
    # 4-space → 2-space dedent below the deepest level, and the second top-level
    # item after it, must both survive (the earlier recursive builder lost them).
    out = hr.markdown_to_html("- a\n    - deep\n  - middle\n- last")
    for word in ("a", "deep", "middle", "last"):
        assert f"<li>{word}" in out, f"{word!r} dropped from {out!r}"
    # A list whose first bullet is indented must not swallow later top-level items.
    out2 = hr.markdown_to_html("  - indented first\n- zero one\n- zero two")
    for word in ("indented first", "zero one", "zero two"):
        assert word in out2


def test_markdown_table_renders_cells_and_alignment():
    md = "| Tag | Size |\n| --- | ---: |\n| VAV-3 | 10 in |"
    out = hr.markdown_to_html(md)
    assert "<table>" in out
    assert "<th>Tag</th>" in out
    assert "<td>VAV-3</td>" in out
    assert 'style="text-align:right"' in out  # the ':' alignment marker is honored


def test_markdown_blockquote_and_hr():
    assert "<blockquote>" in hr.markdown_to_html("> heads up")
    assert "<hr>" in hr.markdown_to_html("text\n\n---\n\nmore")


def test_markdown_escapes_html_and_never_drops_text():
    # Angle brackets / ampersands in the model text are escaped, not interpreted.
    out = hr.markdown_to_html("clearance < 2\" & slope > 1%")
    assert "&lt; 2" in out and "&amp;" in out and "&gt; 1%" in out
    assert "< 2" not in out  # the raw bracket never reaches the document
    # An injection attempt is inert.
    inj = hr.markdown_to_html("<script>alert(1)</script>")
    assert "<script>" not in inj and "&lt;script&gt;" in inj
    # A plain line still appears (lossless fallback to a paragraph).
    assert "<p>just words</p>" == hr.markdown_to_html("just words")


# --------------------------------------------------------------------------- #
# split_into_sections — header detection + lead-in handling
# --------------------------------------------------------------------------- #


def test_split_into_sections_headers_and_intro():
    sections = hr.split_into_sections(_OK_DIGEST)
    headers = [h for h, _ in sections]
    # Lead-in prose (the "Sheet …" line) is a header-less intro section.
    assert headers[0] is None
    assert "Scope / systems shown" in headers
    assert "Coordination / cross-discipline items" in headers
    # The bold marker is stripped from the stored header text.
    assert "**" not in "".join(h for h in headers if h)


def test_prose_with_two_bold_spans_is_not_a_header():
    # A sentence that merely starts and ends with a bold span is body text, not a
    # section header — it must not be folded into the table of contents (and its
    # text must be preserved verbatim, not mangled by header-stripping).
    sections = hr.split_into_sections("**VAV-3** is shown on **M-501**")
    assert sections == [(None, "**VAV-3** is shown on **M-501**")]


# --------------------------------------------------------------------------- #
# build_html_report — the assembled, self-contained document
# --------------------------------------------------------------------------- #


def test_report_is_self_contained_html():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert doc.startswith("<!DOCTYPE html>")
    # Styling and behavior are inlined — one portable file, no external assets.
    assert "<style>" in doc and "<script>" in doc
    assert "http://" not in doc and "https://" not in doc
    assert "src=" not in doc and "<link" not in doc


def test_report_contains_every_sheet_and_the_overview():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="overview"' in doc
    assert 'id="sheet-1"' in doc and 'id="sheet-3"' in doc
    assert "VAV-3 serves Rm 120" in doc            # rendered sheet content
    assert "WH-1 schedule transcribed" in doc      # cached sheet content
    assert "Cached" in doc                          # status badge


def test_report_tags_blocks_with_categories_for_filtering():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'data-category="coordination"' in doc
    assert 'data-category="conflict"' in doc        # from the synthesis
    assert 'data-category="equipment"' in doc
    # The filter UI exposes the "isolate the issues" affordances the user asked for.
    assert 'data-filter="issues"' in doc
    assert 'data-filter="coordination"' in doc


def test_report_surfaces_failed_sheet_and_errors():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'data-status="failed"' in doc
    assert "could not be analyzed" in doc
    assert "api_error: Internal Server Error" in doc
    assert "1 issue(s) this run" in doc             # run-level errors block


def test_report_embeds_verbatim_raw_markdown_losslessly():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    # The exact combined Markdown is embedded (escaped) so nothing is ever lost.
    assert "Complete raw Markdown" in doc
    assert "VAV-3 serves Rm 120 &lt;unique-marker&gt;" in doc


def test_report_escapes_content_in_structured_view():
    ctx = _make_ctx()
    ctx.sheets[1].text = "danger <img src=x onerror=alert(1)>"
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert "<img src=x" not in doc
    assert "&lt;img src=x" in doc


def test_report_handles_empty_synthesis():
    ctx = _make_ctx()
    ctx.synthesis_text = ""
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert "No cross-sheet synthesis was produced" in doc


# --------------------------------------------------------------------------- #
# per-run focus card + filter
# --------------------------------------------------------------------------- #

FOCUS = "the rooms, and what types of plumbing fixtures each has"


def test_classify_section_focus():
    assert hr.classify_section("Focus findings") == "focus"


def test_report_without_focus_has_no_focus_card_or_chip():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="focus"' not in doc
    assert 'data-filter="focus"' not in doc  # a chip that can't match is noise


def test_report_with_focus_pins_the_report_card_and_chip():
    ctx = _make_ctx()
    ctx.focus = FOCUS
    ctx.focus_report_text = (
        "**Room-by-room**\n- Rm 101: `WC-1`, `LAV-2` (P-101, schedule P-501)\n"
    )
    ctx.sheets[0].text += (
        "\n**Focus findings**\n- Rm 120: `WC-1` shown at north wall.\n"
    )
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)

    assert 'id="focus"' in doc                       # the pinned report card
    assert "the rooms, and what types of plumbing" in doc  # question quoted
    assert "Rm 101" in doc                           # the report content
    # The card leads the page: it appears before the overview card.
    assert doc.index('id="focus"') < doc.index('id="overview"')
    # Per-sheet "Focus findings" sections are tagged and filterable.
    assert 'data-category="focus"' in doc
    assert 'data-filter="focus"' in doc
    # And the sidebar links to it.
    assert 'data-target="focus"' in doc


def test_report_with_focus_but_failed_report_explains_itself():
    ctx = _make_ctx()
    ctx.focus = FOCUS
    ctx.focus_report_text = ""
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert 'id="focus"' in doc
    assert "No focus report was produced" in doc


def test_focus_card_body_survives_the_focus_filter():
    # The report's own headers usually do NOT contain "focus" — they're shaped
    # by the question ("Room-by-room", "Equipment & schedules", …) and would
    # classify as other/equipment/etc. Every block inside the focus card must
    # still carry data-category="focus", or selecting the Focus chip hides the
    # report's body and the run looks like it produced no focus results.
    ctx = _make_ctx()
    ctx.focus = FOCUS
    ctx.focus_report_text = (
        "**Room-by-room**\n- Rm 101: `WC-1`, `LAV-2`\n\n"
        "**Equipment & schedules**\n- `WC-1` wall-hung (schedule P-501)\n\n"
        "**Cross-sheet / cross-discipline conflicts**\n- `LAV-2` scheduled, never drawn\n"
    )
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)

    card = doc[doc.index('id="focus"'): doc.index('id="overview"')]
    # Four blocks (ask + three report sections), all filterable as focus.
    assert card.count('data-category="focus"') == 4
    assert 'data-category="other"' not in card
    assert 'data-category="equipment"' not in card
    assert 'data-category="conflict"' not in card
    assert "Rm 101" in card
    # The informative pill still reflects the keyword classification, so the
    # conflict section inside the report keeps its Conflicts tag.
    assert "cat-conflict" in card


# --------------------------------------------------------------------------- #
# in-report Q&A assistant (opt-in via api_key)
# --------------------------------------------------------------------------- #


def test_report_without_key_has_no_chat_and_no_network_references():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert "da-chat" not in doc
    assert "api.anthropic.com" not in doc
    # Blank / whitespace keys behave exactly like no key.
    blank = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW, api_key="  ")
    assert blank == doc


def test_report_with_key_default_prompts_and_never_writes_the_key():
    # Phase 8: the DEFAULT (no embed_api_key) includes the assistant but does NOT
    # write the key into the file — it prompts at runtime and uses sessionStorage.
    key = "sk-ant-SECRET-do-not-embed"
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW, api_key=key)
    # Widget present and wired to the API...
    assert 'id="da-chat-config"' in doc
    assert hr.CHAT_MODEL_DEFAULT in doc
    assert "api.anthropic.com/v1/messages" in doc
    assert "web_search_20260209" in doc and "web_fetch_20260209" in doc
    # ...but the key literal appears NOWHERE, and the config carries no apiKey.
    assert key not in doc
    assert '"apiKey"' not in doc
    # The runtime path uses sessionStorage and says the key isn't saved.
    assert "sessionStorage" in doc
    assert "never saved into this file" in doc


def test_report_with_embed_api_key_embeds_the_key_with_a_warning():
    doc = hr.build_html_report(
        _make_ctx(), source_names=[SRC], now=NOW,
        api_key="sk-ant-test-123", embed_api_key=True,
    )
    # The config block carries the key + chat model for the browser-side JS.
    assert 'id="da-chat-config"' in doc
    assert "sk-ant-test-123" in doc
    assert '"apiKey"' in doc
    assert hr.CHAT_MODEL_DEFAULT in doc
    assert "api.anthropic.com/v1/messages" in doc
    assert "anthropic-dangerous-direct-browser-access" in doc
    assert "adaptive" in doc
    # The report block is cache-marked so follow-ups reread it at cache prices.
    assert "cache_control" in doc
    # The reader is warned (in red) about the embedded key.
    assert "don't share it" in doc
    assert "da-key-warn" in doc


def test_embed_api_key_without_a_key_stays_in_prompt_mode():
    # embed flag but no key to embed → widget present, still no key literal.
    doc = hr.build_html_report(
        _make_ctx(), source_names=[SRC], now=NOW, api_key=None, embed_api_key=True
    )
    assert 'id="da-chat-config"' in doc
    assert '"apiKey"' not in doc
    assert "sessionStorage" in doc


def test_chat_config_cannot_break_out_of_its_script_tag():
    # `</` in any config value (e.g. a hostile source filename) must be escaped
    # to `<\/` so it can never close the JSON <script> block early.
    doc = hr.build_html_report(
        _make_ctx(),
        source_names=['evil</script><script>alert(1)//x.pdf'],
        now=NOW,
        api_key="sk-ant-test-123",
    )
    start = doc.index('id="da-chat-config"')
    config = doc[start: doc.index("</script>", start)]
    assert "</" not in config[config.index(">"):]
    assert "<\\/script" in config


# --------------------------------------------------------------------------- #
# QC Findings card + status chips (Phase 8)
# --------------------------------------------------------------------------- #


def _finding(sheet_id="M-101", category="code", severity="high",
             text="VAV-3 has no shown clearance", quote="VAV-3",
             page_index=0, source_name=SRC,
             anchor_status="EXACT", verify_status="VERIFIED", evidence=""):
    return Finding(
        sheet_id=sheet_id, source_name=source_name, page_index=page_index,
        category=category, severity=severity, text=text, source_quote=quote,
        anchor=Anchor(status=anchor_status,
                      rect_pdf=[0, 0, 1, 1] if anchor_status != "UNANCHORED" else None),
        verification=Verification(status=verify_status, evidence_png=evidence),
    )


def _findings_ctx(findings=None, reference=None, geometries=None):
    ctx = _make_ctx()
    ctx.findings = findings or []
    ctx.reference_findings = reference or []
    ctx.sheet_geometries = geometries or []
    return ctx


def test_finding_display_status_priority():
    # REJECTED wins; DETERMINISTIC and VERIFIED next; an unanchored non-empty
    # quote reads UNANCHORED; anchored-but-unconfirmed collapses to UNCERTAIN.
    f = hr._finding_display_status
    assert f(_finding(verify_status="REJECTED")) == "REJECTED"
    assert f(_finding(verify_status="DETERMINISTIC")) == "DETERMINISTIC"
    assert f(_finding(verify_status="VERIFIED")) == "VERIFIED"
    assert f(_finding(anchor_status="UNANCHORED", verify_status="SKIPPED")) == "UNANCHORED"
    assert f(_finding(anchor_status="EXACT", verify_status="UNCERTAIN")) == "UNCERTAIN"
    assert f(_finding(anchor_status="EXACT", verify_status="SKIPPED")) == "UNCERTAIN"


def test_findings_card_renders_table_chips_and_sheet_link():
    ctx = _findings_ctx(
        findings=[
            _finding(severity="high", verify_status="VERIFIED"),
            _finding(text="stray note", quote="", category="question",
                     severity="low", anchor_status="UNANCHORED", verify_status="SKIPPED"),
        ],
        reference=[
            _finding(sheet_id="M-101", category="reference", severity="medium",
                     text="References M-999; not present", quote="M-999",
                     verify_status="DETERMINISTIC"),
        ],
    )
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    # The pinned card + its TOC entry appear.
    assert 'id="findings"' in doc
    assert 'data-target="findings"' in doc
    assert "3 finding(s)" in doc
    # Sortable headers carry the sort keys.
    for key in ("sheet", "category", "severity", "status", "text", "quote"):
        assert f'data-sort="{key}"' in doc
    # Status chips render with their colored classes.
    assert "fchip-verified" in doc
    assert "fchip-deterministic" in doc
    assert "fchip-unanchored" in doc
    # Rows carry the filter/sort hooks the JS keys on.
    assert 'class="finding-row"' in doc
    assert 'data-severity="3"' in doc and 'data-status="VERIFIED"' in doc
    # The sheet cell links to the card for the sheet the finding sits on.
    assert 'href="#sheet-1"' in doc


def test_no_findings_card_when_there_are_none():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="findings"' not in doc               # no card
    assert 'data-target="findings"' not in doc      # no TOC entry


def test_evidence_thumbnail_only_with_link_evidence():
    ctx = _findings_ctx(findings=[_finding(evidence="evidence/abc123.png")])
    plain = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    # The CSS class always exists; the <img> markup must not (single-file stays light).
    assert 'class="evidence-thumb"' not in plain
    linked = hr.build_html_report(ctx, source_names=[SRC], now=NOW, link_evidence=True)
    assert 'class="evidence-thumb"' in linked
    assert 'src="evidence/abc123.png"' in linked


# --------------------------------------------------------------------------- #
# Per-sheet raw text layer + raster badge (Phase 8)
# --------------------------------------------------------------------------- #


def test_rawtext_block_feeds_search_and_flags_raster():
    ctx = _findings_ctx(geometries=[
        _Geom(_Ref(SRC, 0, 3), sheet_text="PANEL SCHEDULE RAWMARKER-XYZ"),
        _Geom(_Ref(SRC, 1, 3), sheet_text="", is_raster=True),
    ])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    # Sheet 1's raw text layer is embedded (searchable) in a collapsed block.
    assert "Sheet text layer" in doc
    assert "RAWMARKER-XYZ" in doc
    assert 'class="block block-rawtext"' in doc
    # Sheet 2 (empty text layer) is badged as raster with an explanatory note.
    assert 'class="badge badge-raster"' in doc
    assert "Raster sheet" in doc
