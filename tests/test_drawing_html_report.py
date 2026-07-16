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
    # Product invariant: one portable file — no external assets (stylesheets,
    # script files, images). The default report DOES name the Anthropic API
    # endpoint (the Ask-AI assistant's runtime target + its CSP allowance);
    # that is a runtime opt-in network feature, not a page asset.
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert doc.startswith("<!DOCTYPE html>")
    assert "<style>" in doc and "<script>" in doc
    assert "<link" not in doc
    assert 'src="http' not in doc and "src='http" not in doc
    # The only https reference is the Anthropic Messages endpoint.
    for prefix in ("http://", "https://"):
        rest = doc
        while prefix in rest:
            i = rest.index(prefix)
            assert rest[i:].startswith("https://api.anthropic.com"), rest[i : i + 60]
            rest = rest[i + len("https://api.anthropic.com"):]


def test_report_without_chat_has_no_network_references_at_all():
    # include_chat=False restores the strict zero-network document.
    doc = hr.build_html_report(
        _make_ctx(), source_names=[SRC], now=NOW, include_chat=False
    )
    assert "da-chat" not in doc
    assert "http://" not in doc and "https://" not in doc
    assert "<link" not in doc


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


# --------------------------------------------------------------------------- #
# Phase 23A — the run-level QC status banner (§3.3 / §15.5)
# --------------------------------------------------------------------------- #


def test_report_has_no_qc_status_banner_for_a_standard_run():
    # A standard run (qc_status NOT_REQUESTED) emits no QC status banner *element*
    # (the CSS rule is always in the <style> block; the div is what's conditional).
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert '<div class="qc-status-banner"' not in doc


def test_report_qc_status_banner_partial_names_the_debug_override_cause():
    # §18.0 (gate open): a PARTIAL with no degraded stage has exactly one
    # cause — an explicit debug override — and the banner says so instead of
    # the retired gate-era "intentionally withheld" wording.
    from drawing_analyzer.models import StageResult

    ctx = _make_ctx()
    ctx.qc_status = "PARTIAL"
    ctx.stage_results = [
        StageResult(stage="critique", expected=True, status="COMPLETE"),
        StageResult(stage="citation", expected=True, status="SKIPPED_VALID"),
    ]
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert 'class="qc-status-banner" data-status="PARTIAL"' in doc
    assert "QC status: PARTIAL" in doc
    assert "deliberately weakened the exhaustive contract" in doc
    assert "withheld pending later remediation" not in doc


def test_report_qc_status_banner_names_degraded_stages_and_debug_override():
    from drawing_analyzer.models import StageResult, resolve_run_configuration

    ctx = _make_ctx()
    ctx.qc_status = "PARTIAL"
    ctx.run_configuration = resolve_run_configuration(qc_markups=True, critique=False)
    ctx.stage_results = [StageResult(stage="cross_qc", expected=True, status="FAILED")]
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert "cross_qc (FAILED)" in doc
    assert "DEBUG_OVERRIDE" in doc


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
# in-report Q&A assistant (present by default; key prompted at first use)
# --------------------------------------------------------------------------- #


def test_report_without_key_still_shows_ask_ai_and_prompts_first_use():
    # Product invariant (Phase 17, DA-026): the assistant is available even
    # when the report was built with NO key — it prompts the reader on first
    # use and keeps the key in sessionStorage only. (The old assertion that a
    # key-less report omits the widget encoded the defect.)
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="da-chat-config"' in doc
    assert "api.anthropic.com/v1/messages" in doc
    assert '"apiKey"' not in doc                  # no key material in the file
    assert "sessionStorage" in doc
    assert "never saved into this file" in doc
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


def test_report_key_entry_ui_present_when_not_embedded():
    # A key-less (default) report ships the in-panel key-entry field so the
    # reader can supply their own key — a real masked input, not window.prompt,
    # and still no key material written into the file.
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="da-chat-key-input"' in doc
    assert 'id="da-chat-key-save"' in doc
    assert 'id="da-chat-key-toggle"' in doc
    assert 'id="da-chat-key-change"' in doc
    assert 'type="password"' in doc          # the key field is masked
    assert "window.prompt(" not in doc       # the old native prompt call is gone
    assert '"apiKey"' not in doc             # no key material in the file


def test_chat_config_cannot_break_out_of_its_script_tag():
    # Every `<` in any config value (e.g. a hostile source filename) is emitted
    # as the JSON string escape `\u003c`, so no value can close the JSON
    # <script> block early or form markup — and JSON.parse round-trips it.
    import json

    hostile = 'evil</script><script>alert(1)//x.pdf'
    doc = hr.build_html_report(
        _make_ctx(),
        source_names=[hostile],
        now=NOW,
        api_key="sk-ant-test-123",
    )
    start = doc.index('id="da-chat-config"')
    body = doc[doc.index(">", start) + 1: doc.index("</script>", start)]
    assert "<" not in body
    assert "\\u003c" in body
    assert json.loads(body)["sources"] == [hostile]


# --------------------------------------------------------------------------- #
# Chat client-tool data blocks (#da-findings / #da-summary).
# --------------------------------------------------------------------------- #


def _script_block_body(doc: str, block_id: str) -> str:
    start = doc.index(f'id="{block_id}"')
    return doc[doc.index(">", start) + 1: doc.index("</script>", start)]


def test_findings_and_summary_data_blocks_present_and_structured():
    # The chat's client tools read structured findings + run metadata from inert
    # application/json blocks (data the prose digest deliberately omits).
    import json

    ctx = _findings_ctx(findings=[
        _finding(sheet_id="M-501", category="conflict", severity="high",
                 text="VAV-3 clearance missing", quote="VAV-3", verify_status="VERIFIED"),
    ])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)

    findings = json.loads(_script_block_body(doc, "da-findings"))
    assert isinstance(findings, list) and len(findings) == 1
    row = findings[0]
    assert set(row) >= {"id", "sheet", "target", "category", "severity",
                        "status", "text", "quote"}
    assert row["category"] == "conflict" and row["severity"] == "high"
    assert row["status"] == "VERIFIED" and row["quote"] == "VAV-3"

    summary = json.loads(_script_block_body(doc, "da-summary"))
    assert set(summary) >= {"generated", "sheets", "qc_status", "coverage_status",
                            "tokens", "estimated_cost_usd", "errors", "sources"}
    assert summary["sources"] == [SRC]


def test_findings_data_block_cannot_break_out_of_its_script_tag():
    # Hostile finding text/quote can't close the JSON <script> block: every `<`
    # becomes `<` and JSON.parse round-trips it (same guarantee the chat
    # config block carries).
    import json

    hostile = 'evil</script><script>window.__pwned=1</script>'
    ctx = _findings_ctx(findings=[
        _finding(text=hostile, quote=hostile, category="conflict", severity="high"),
    ])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    body = _script_block_body(doc, "da-findings")
    assert "<" not in body
    assert "\\u003c" in body
    parsed = json.loads(body)
    assert parsed[0]["text"] == hostile and parsed[0]["quote"] == hostile


def test_findings_data_block_exposes_cross_sheet_legs_and_citations():
    # The cross-sheet and cited-code starters are answerable from #da-findings:
    # also_on legs, code refs, and the citation verdict are serialized so the
    # assistant does not have to guess (PR #65 review).
    import json

    from drawing_analyzer.models import Citation, ConflictLeg

    f_cross = _finding(sheet_id="M-501", category="conflict", severity="high",
                       text="Duct main conflicts with beam", quote="DUCT-1")
    f_cross.also_on = [ConflictLeg(sheet_id="S-201")]
    f_code = _finding(sheet_id="P-201", category="code", severity="medium",
                      text="Cleanout spacing", quote="cleanout")
    f_code.refs = ["IPC 708.3.1"]
    f_code.citation = Citation(status="CHECKED_MISMATCH", note="renumbered in 2021")

    ctx = _findings_ctx(findings=[f_cross, f_code])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    rows = {r["sheet"]: r for r in json.loads(_script_block_body(doc, "da-findings"))}

    assert rows["M-501"]["also_on"] == ["S-201"]
    assert rows["P-201"]["refs"] == ["IPC 708.3.1"]
    assert rows["P-201"]["citation"]["status"] == "CHECKED_MISMATCH"
    # Findings without legs/refs stay lean — the keys are omitted, not empty.
    assert "also_on" not in rows["P-201"]
    assert "refs" not in rows["M-501"] and "citation" not in rows["M-501"]


def test_data_blocks_absent_without_chat():
    # include_chat=False must stay free of every chat artifact (the no-network
    # invariant): neither data block is emitted.
    ctx = _findings_ctx(findings=[_finding()])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW, include_chat=False)
    assert "da-findings" not in doc
    assert "da-summary" not in doc


def test_findings_data_block_absent_when_no_findings():
    # No findings → no #da-findings block (the tool reports an empty ledger); the
    # summary block is still emitted (there is always a run to describe).
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="da-findings"' not in doc
    assert 'id="da-summary"' in doc


# --------------------------------------------------------------------------- #
# Starter prompts (#da-starters) — deterministic, run-tailored, click-to-send.
# --------------------------------------------------------------------------- #


def test_starter_prompts_capped_at_five_and_deduped():
    # Never more than five; every entry unique (even with many findings).
    findings = [
        _finding(sheet_id=f"M-{500 + i}", category="conflict", severity="high",
                 text=f"clash {i}", quote=f"D-{i}")
        for i in range(8)
    ]
    prompts = hr._starter_prompts(_findings_ctx(findings=findings), [], [SRC])
    assert 1 <= len(prompts) <= 5
    assert len(prompts) == len(set(prompts))


def test_starter_prompts_name_the_real_top_finding_sheet():
    # The most-severe finding drives a prompt naming its actual sheet + category —
    # no invented tag, no fabricated discipline.
    ctx = _findings_ctx(findings=[
        _finding(sheet_id="P-201", category="coordination", severity="high",
                 text="floor drain clash", quote="FD-2"),
    ])
    prompts = hr._starter_prompts(ctx, [], [SRC])
    assert any("P-201" in p and "coordination item" in p for p in prompts)


def test_starter_prompts_flag_critical_conflicts_and_top_category():
    ctx = _findings_ctx(findings=[
        _finding(sheet_id="M-501", category="conflict", severity="high",
                 text="duct vs beam", quote="D-1"),
        _finding(sheet_id="M-502", category="conflict", severity="medium",
                 text="another duct", quote="D-2"),
    ])
    prompts = hr._starter_prompts(ctx, [], [SRC])
    assert "What are the most critical conflicts across these sheets?" in prompts
    assert "Summarize the conflicts." in prompts


def test_starter_prompts_flag_cross_sheet_issues():
    f = _finding(sheet_id="M-101", category="reference", severity="low",
                 text="spans sheets", quote="X", verify_status="VERIFIED")
    f.also_on = [object()]   # any also_on leg marks a cross-sheet finding (DA-016)
    prompts = hr._starter_prompts(_findings_ctx(findings=[f]), [], [SRC])
    assert "Which issues span more than one sheet?" in prompts


def test_starter_prompts_flag_cited_code():
    f = _finding(sheet_id="M-101", category="code", severity="medium",
                 text="IBC clearance", quote="IBC", verify_status="VERIFIED")
    f.refs = ["IBC 1004.5"]
    prompts = hr._starter_prompts(_findings_ctx(findings=[f]), [], [SRC])
    assert "Do the cited code sections check out?" in prompts


def test_starter_prompts_flag_unverified_findings():
    ctx = _findings_ctx(findings=[
        _finding(sheet_id="M-101", category="question", severity="low",
                 text="unsure", quote="Q",
                 anchor_status="UNANCHORED", verify_status="SKIPPED"),
    ])
    prompts = hr._starter_prompts(ctx, [], [SRC])
    assert "Which findings could not be verified against the drawings?" in prompts


def test_starter_prompts_fall_back_to_set_aware_prompts_without_findings():
    # A clean, findings-free run still gets relevant prompts built from the real
    # sheet count and source name — never the old fabricated VAV-3 / plumbing line.
    prompts = hr._starter_prompts(_findings_ctx(findings=[]), [], [SRC])
    assert prompts
    assert any(SRC in p for p in prompts)
    assert any("3-sheet" in p for p in prompts)   # _make_ctx has three sheets
    assert all("VAV-3" not in p for p in prompts)


def test_starters_data_block_present_and_structured():
    import json

    ctx = _findings_ctx(findings=[
        _finding(sheet_id="M-501", category="conflict", severity="high",
                 text="VAV-3 clash", quote="VAV-3"),
    ])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    starters = json.loads(_script_block_body(doc, "da-starters"))
    assert isinstance(starters, list) and 1 <= len(starters) <= 5
    assert all(isinstance(s, str) and s.strip() for s in starters)


def test_starters_replace_the_old_hardcoded_examples():
    # The fabricated VAV-3 / plumbing example line is gone; the chips row is in.
    assert "Which sheets mention VAV-3" not in hr._CHAT_HTML
    assert "plumbing coordination items" not in hr._CHAT_HTML
    assert 'id="da-starters-row"' in hr._CHAT_HTML


def test_starters_data_block_cannot_break_out_of_its_script_tag():
    import json

    hostile = 'M-1</script><script>window.__pwned=1</script>'
    ctx = _findings_ctx(findings=[
        _finding(sheet_id=hostile, category="conflict", severity="high",
                 text="x", quote="x"),
    ])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    body = _script_block_body(doc, "da-starters")
    assert "<" not in body
    assert any(hostile in p for p in json.loads(body))


def test_starters_data_block_absent_without_chat():
    ctx = _findings_ctx(findings=[_finding()])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW, include_chat=False)
    assert "da-starters" not in doc


def test_chat_request_defines_client_tools_and_closure_loop():
    # The six client-executed tools are declared with input schemas; the loop
    # answers tool_use with tool_result and force-closes with tools disabled so a
    # run can never end on a dangling tool call.
    js = hr._CHAT_JS
    for name in ("scroll_to_report", "query_findings", "filter_report",
                 "get_report_summary", "highlight_term", "calculate"):
        assert f"name: '{name}'" in js, f"{name} tool not declared"
    assert "input_schema" in js
    assert "tool_choice" in js and "type: 'none'" in js
    assert "stopReason === 'tool_use'" in js
    assert "type: 'tool_result'" in js
    # The safe calculator never uses eval/Function.
    assert "eval(" not in js and "new Function" not in js


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


def test_finding_action_renders_and_is_escaped():
    f = _finding()
    f.recommended_action = "Confirm the clearance & <verify> the schedule."
    doc = hr.build_html_report(_findings_ctx(findings=[f]), source_names=[SRC], now=NOW)
    assert 'class="finding-action"' in doc
    assert "Action: Confirm the clearance &amp; &lt;verify&gt; the schedule." in doc
    # No action → no empty Action div.
    bare = hr.build_html_report(
        _findings_ctx(findings=[_finding()]), source_names=[SRC], now=NOW
    )
    assert 'class="finding-action"' not in bare


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
# QC-### → marked-up-PDF deep links (HTML↔PDF navigation)
# --------------------------------------------------------------------------- #


def _qc(finding, qc_id):
    finding.qc_id = qc_id
    return finding


def test_qc_cell_deep_links_to_reviewed_pdf_when_mapped():
    # A finding whose qc_id is in the pdf_links map gets a QC-### cell that opens
    # the marked-up PDF at its page in a new tab; an unmapped finding stays plain.
    ctx = _findings_ctx(findings=[
        _qc(_finding(severity="high", verify_status="VERIFIED"), "QC-001"),
        _qc(_finding(text="unmapped", severity="low", verify_status="UNCERTAIN"), "QC-002"),
    ])
    links = {"QC-001": {"pdf": "M-101_reviewed.pdf", "page": 5}}
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW, pdf_links=links)
    assert (
        '<a class="pdf-link" href="M-101_reviewed.pdf#page=5" target="_blank" '
        'rel="noopener noreferrer" title="Open QC-001 in the marked-up PDF">QC-001</a>'
    ) in doc
    # The finding not in the map keeps the plain cell (no second link).
    assert '<td class="fcol-qcid">QC-002</td>' in doc
    assert doc.count('class="pdf-link"') == 1


def test_qc_cell_plain_without_pdf_links():
    # Default (single-file report / non-markup run): no PDF links at all.
    ctx = _findings_ctx(findings=[_qc(_finding(), "QC-001")])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert 'class="pdf-link"' not in doc
    assert '<td class="fcol-qcid">QC-001</td>' in doc


def test_pdf_link_filename_is_percent_encoded():
    # A reviewed-PDF basename with a space is a valid file but not a valid raw
    # URL — the href must percent-encode the name while leaving #page= intact.
    ctx = _findings_ctx(findings=[_qc(_finding(), "QC-001")])
    links = {"QC-001": {"pdf": "M 101 reviewed.pdf", "page": 2}}
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW, pdf_links=links)
    assert 'href="M%20101%20reviewed.pdf#page=2"' in doc


def test_pdf_link_hostile_filename_cannot_break_out():
    # Even a hostile reviewed-PDF name can't inject markup: it is percent-encoded
    # (no raw < or ") before it ever reaches the href attribute.
    ctx = _findings_ctx(findings=[_qc(_finding(), "QC-001")])
    links = {"QC-001": {"pdf": 'x"><img src=x onerror=alert(1)>.pdf', "page": 1}}
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW, pdf_links=links)
    # The raw injected payload never appears — < > " are all percent-encoded.
    assert 'x"><img src=x onerror=alert(1)>' not in doc
    assert "<img src=x" not in doc
    # The link is still present and points at page 1 of the encoded name.
    assert 'class="pdf-link"' in doc and "#page=1" in doc


def test_findings_data_block_mirrors_pdf_link():
    # The inert #da-findings JSON the assistant reads carries the same deep link.
    import json

    ctx = _findings_ctx(findings=[_qc(_finding(verify_status="VERIFIED"), "QC-001")])
    links = {"QC-001": {"pdf": "M-101_reviewed.pdf", "page": 5}}
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW, pdf_links=links)
    rows = json.loads(_script_block_body(doc, "da-findings"))
    assert rows[0]["pdf"] == "M-101_reviewed.pdf#page=5"
    # No map → empty pdf field (kept for a stable schema).
    plain = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert json.loads(_script_block_body(plain, "da-findings"))[0]["pdf"] == ""


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


def test_same_basename_sheets_keep_their_own_text_layer():
    # Two PDFs share the basename "M-101.pdf" but live in different directories.
    # The geometry index keys on the full path, so each sheet card must show its
    # OWN raw text layer — not the first sheet's (regression for the basename
    # collision).
    name = "M-101.pdf"
    sheets = [
        _Sheet(_Ref(name, 0, 1, pdf_path="/rev_a/M-101.pdf"), text="rev A digest"),
        _Sheet(_Ref(name, 0, 1, pdf_path="/rev_b/M-101.pdf"), text="rev B digest"),
    ]
    geoms = [
        _Geom(_Ref(name, 0, 1, pdf_path="/rev_a/M-101.pdf"), sheet_text="ALPHA_ONLY_TEXT"),
        _Geom(_Ref(name, 0, 1, pdf_path="/rev_b/M-101.pdf"), sheet_text="BRAVO_ONLY_TEXT"),
    ]
    ctx = _Ctx(sheets=sheets, combined_text="x", sheet_geometries=geoms)
    doc = hr.build_html_report(ctx, source_names=[name], now=NOW)
    # Both distinct text layers survive; before the fix the second sheet reused
    # the first geometry, so BRAVO_ONLY_TEXT would be missing entirely.
    assert "ALPHA_ONLY_TEXT" in doc
    assert "BRAVO_ONLY_TEXT" in doc


# --------------------------------------------------------------------------- #
# Phase 17A — report security trust boundary (DA-011).
#
# The browser-side execution proof (CSP + file:// + real event dispatch) lands
# in Phase 17B's headless-Chromium suite. These hermetic tests pin the two
# static halves of the boundary: (1) the Python side never emits a
# model/run-controlled string into live markup, and (2) the emitted JS keeps
# the safe-DOM discipline (no HTML sinks, one URL validator).
# --------------------------------------------------------------------------- #

# A corpus of payloads that must never produce executable markup or handlers.
_ATTACK_STRINGS = [
    '</script><script>sentinel()</script>',
    '<img src=x onerror=sentinel()>',
    '<svg onload=sentinel()></svg>',
    '" autofocus onfocus="sentinel()',
    "javascript:sentinel()",
    "<iframe src=javascript:sentinel()>",
    "<script>sentinel()</script>",
]


def _assert_inert(doc: str) -> None:
    """No attack payload survives as live markup/handlers.

    The executable surface is an *unescaped* dangerous tag opener or a script
    body — never an escaped fragment. ``&lt;img … onerror=sentinel()&gt;`` is
    safe (the ``<`` was neutralized to ``&lt;``); the handler substring only
    matters when it sits on a real element, which the tag-opener bans catch.
    The report itself never emits svg/iframe/object/embed, and its one
    legitimate ``<img`` uses ``class=`` (never the attack's ``src=x``).
    """
    low = doc.lower()
    assert "<script>sentinel" not in low          # no injected script element
    assert "sentinel()</script>" not in low       # nor a closing-half break-out
    for opener in ("<svg", "<iframe", "<object", "<embed", "<img src=x"):
        assert opener not in low, opener
    # A broken-out attribute needs a real quote before the handler; every model
    # quote is escaped to &quot;, so the raw-quote handler form must be absent.
    for handler in ('onerror="sentinel', 'onfocus="sentinel', 'onload="sentinel'):
        assert handler not in low, handler


def test_hostile_filenames_are_inert_in_the_report():
    for payload in _ATTACK_STRINGS:
        doc = hr.build_html_report(
            _make_ctx(), source_names=[payload + ".pdf"], now=NOW
        )
        _assert_inert(doc)
        # The literal still round-trips through the inert JSON config island.
        import json
        start = doc.index('id="da-chat-config"')
        body = doc[doc.index(">", start) + 1: doc.index("</script>", start)]
        assert payload + ".pdf" in json.loads(body)["sources"]


def test_hostile_sheet_text_and_synthesis_are_escaped():
    ctx = _make_ctx()
    ctx.sheets[0].text = "**Scope**\n- " + "</script><script>sentinel()</script>"
    ctx.synthesis_text = "**Conflicts**\n- <img src=x onerror=sentinel()>"
    ctx.combined_text = '<svg onload=sentinel()></svg>'
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    _assert_inert(doc)
    assert "&lt;img src=x" in doc  # rendered as visible text, escaped


def test_hostile_finding_fields_are_escaped():
    f = _finding(
        sheet_id='</script><script>sentinel()</script>',
        text='<img src=x onerror=sentinel()>',
        quote='" autofocus onfocus="sentinel()',
        category='<svg onload=sentinel()>',
    )
    doc = hr.build_html_report(_findings_ctx(findings=[f]), source_names=[SRC], now=NOW)
    _assert_inert(doc)


def test_hostile_run_errors_are_escaped():
    ctx = _make_ctx()
    ctx.errors = ['boom </script><script>sentinel()</script>']
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    _assert_inert(doc)


def test_hostile_focus_text_is_escaped():
    ctx = _make_ctx()
    ctx.focus = '<img src=x onerror=sentinel()>'
    ctx.focus_report_text = "**Rooms**\n- </script><script>sentinel()</script>"
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    _assert_inert(doc)


def test_evidence_links_use_noopener_noreferrer():
    f = _finding(verify_status="VERIFIED", evidence="evidence/QC-001/leg-01.png")
    doc = hr.build_html_report(
        _findings_ctx(findings=[f]), source_names=[SRC], now=NOW, link_evidence=True
    )
    assert 'rel="noopener noreferrer"' in doc


# --------------------------------------------------------------------------- #
# Static DOM-safety discipline of the emitted JavaScript.
# --------------------------------------------------------------------------- #


def test_report_scripts_have_no_html_injection_sinks():
    for src in (hr._JS, hr._CHAT_JS):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in src, f"{sink} present in report script"


def test_chat_js_builds_dom_and_validates_urls():
    js = hr._CHAT_JS
    # The safe-DOM renderer and single URL validator are present...
    assert "renderMdInto" in js and "renderMdReplace" in js
    assert "function safeUrl" in js and "function linkEl" in js
    # ...and https-only is enforced with credential + control/whitespace
    # rejection (0x00–0x20 covers all raw whitespace incl. space, tab, newline).
    assert "u.protocol !== 'https:'" in js
    assert "u.username || u.password" in js
    assert "\\u0000-\\u0020" in js
    # Citations must go through the same link factory, not raw href assembly.
    assert "linkEl(c.url" in js
    # Displayed errors are scrubbed of key material.
    assert "scrubSecrets" in js


# --------------------------------------------------------------------------- #
# Content-Security-Policy (defense in depth).
# --------------------------------------------------------------------------- #


def test_csp_present_pins_script_hashes_and_restricts_connect():
    import base64
    import hashlib

    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert "Content-Security-Policy" in doc

    def _hash(source: str) -> str:
        return "sha256-" + base64.b64encode(
            hashlib.sha256(source.encode("utf-8")).digest()
        ).decode("ascii")

    assert _hash(hr._JS) in doc
    assert _hash(hr._CHAT_JS) in doc          # chat on by default
    assert "connect-src https://api.anthropic.com" in doc
    assert "object-src 'none'" in doc
    assert "base-uri 'none'" in doc
    assert "form-action 'none'" in doc
    # No inline event handlers anywhere, so 'unsafe-inline' script is never used.
    assert "script-src 'unsafe-inline'" not in doc


def test_csp_connect_src_is_none_without_chat():
    doc = hr.build_html_report(
        _make_ctx(), source_names=[SRC], now=NOW, include_chat=False
    )
    assert "connect-src 'none'" in doc
    import base64
    import hashlib
    chat_hash = "sha256-" + base64.b64encode(
        hashlib.sha256(hr._CHAT_JS.encode("utf-8")).digest()
    ).decode("ascii")
    assert chat_hash not in doc  # only the JS actually emitted is allowlisted


def test_embedded_key_forget_control_is_truthful():
    # Forget-key exists; embedded mode admits the key stays in the file.
    doc = hr.build_html_report(
        _make_ctx(), source_names=[SRC], now=NOW,
        api_key="sk-ant-test-123", embed_api_key=True,
    )
    assert 'id="da-chat-forget"' in doc
    assert "Removing the key requires regenerating" in doc


# --------------------------------------------------------------------------- #
# Phase 26B — §18.6 report completeness: stage table, severity toggle, shown
# count, source disambiguation, run record, citation assessments, a11y.
# --------------------------------------------------------------------------- #


def test_stage_status_table_renders_per_stage_rows():
    from drawing_analyzer.models import StageResult

    ctx = _make_ctx()
    ctx.qc_status = "PARTIAL"
    ctx.stage_results = [
        StageResult(stage="critique", expected=True, status="COMPLETE",
                    calls_planned=2, calls_succeeded=2, items_in=3, items_out=5),
        StageResult(stage="citation", expected=True, status="SKIPPED_VALID",
                    warnings=["no cited claims"]),
        StageResult(stage="cross_qc", expected=True, status="FAILED",
                    errors=["api_error: <boom>"]),
    ]
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert "QC stage status" in doc
    assert 'class="usage-table stage-table"' in doc
    # Status cells carry a per-status class (colored like the banners)...
    assert 'class="st-complete"' in doc
    assert 'class="st-skipped"' in doc
    assert 'class="st-failed"' in doc
    # ...calls/items are tallied, and the first error/warning shows — escaped.
    assert "2/2" in doc
    assert "no cited claims" in doc
    assert "api_error: &lt;boom&gt;" in doc
    assert "api_error: <boom>" not in doc


def test_no_stage_status_table_without_stage_results():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert "QC stage status" not in doc
    assert 'class="usage-table stage-table"' not in doc


def test_high_severity_toggle_is_standalone_with_aria_pressed():
    # DA-025: a toggle, not a member of the exclusive category-chip group — it
    # carries no data-filter, so the exclusive-chip JS never touches it.
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert 'id="sev-high"' in doc
    assert "High severity only" in doc
    sev_btn = doc[doc.index('<button class="chip chip-toggle" id="sev-high"'):]
    sev_btn = sev_btn[: sev_btn.index("</button>")]
    assert 'aria-pressed="false"' in sev_btn
    assert "data-filter" not in sev_btn
    # The JS keeps an independent highOnly state keyed to the numeric rank.
    assert "var highOnly = false" in hr._JS
    assert "row.getAttribute('data-severity') === '3'" in hr._JS
    assert "sevHigh.setAttribute('aria-pressed'" in hr._JS


def test_findings_shown_span_present_and_totals_stay_static():
    ctx = _findings_ctx(findings=[_finding()])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    # The live "showing K of N" line sits in the findings card header...
    assert '<span id="findings-shown" class="muted" aria-live="polite">' in doc
    # ...while the static total badge is untouched by filtering (§18.6).
    assert "1 finding(s)" in doc
    assert "findingsShown.textContent" in hr._JS


def test_duplicate_display_names_get_source_id_suffix():
    # Two different sources share the basename; labels get the opaque source id.
    name = "M-101.pdf"
    ref_a = _Ref(name, 0, 1, pdf_path="/rev_a/M-101.pdf", source_id="SRC-0001")
    ref_b = _Ref(name, 0, 1, pdf_path="/rev_b/M-101.pdf", source_id="SRC-0002")
    ctx = _Ctx(
        sheets=[_Sheet(ref_a, text="rev A digest"), _Sheet(ref_b, text="rev B digest")],
        combined_text="x",
    )
    f = _finding(sheet_id="M-101", source_name=name)
    f.source_id = "SRC-0002"
    ctx.findings = [f]
    doc = hr.build_html_report(ctx, source_names=[name], now=NOW)
    # Sheet cards (and the TOC rows) name which source each page came from.
    assert "M-101.pdf (page 1/1) · SRC-0001" in doc
    assert "M-101.pdf (page 1/1) · SRC-0002" in doc
    # The finding's sheet cell is disambiguated the same way.
    assert "M-101 · SRC-0002" in doc


def test_unique_display_names_get_no_source_id_suffix():
    ctx = _findings_ctx(findings=[_finding()])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert " · SRC-" not in doc


def test_run_record_details_renders_journal_and_manifest_pointer():
    class _Journal:
        run_id = "a3f9c2d871e4"
        started_at = datetime(2026, 6, 7, 7, 0, 0)
        ended_at = datetime(2026, 6, 7, 7, 2, 0)
        final_status = "PARTIAL"

    ctx = _make_ctx()
    ctx.run_journal = _Journal()
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert "Run record" in doc
    assert "a3f9c2d871e4" in doc
    assert "2026-06-07 07:00:00" in doc          # started_at via str()
    assert "Final status: PARTIAL" in doc
    # The exported per-run record is named for the operator.
    assert "run.log" in doc and "run_manifest.json" in doc
    assert "written into every export folder" in doc


def test_no_run_record_details_without_a_journal():
    doc = hr.build_html_report(_make_ctx(), source_names=[SRC], now=NOW)
    assert "Run record" not in doc
    assert "run_manifest.json" not in doc


def test_citations_list_renders_per_reference_assessments():
    from drawing_analyzer.models import CitationAssessment

    f = _finding()
    f.citations = [
        CitationAssessment(reference="IMC 403.3", status="CHECKED_SUPPORTS",
                           note="matches the table"),
        CitationAssessment(reference="NEC 210.8", status="CHECKED_MISMATCH",
                           note="x" * 200),
    ]
    doc = hr.build_html_report(_findings_ctx(findings=[f]), source_names=[SRC], now=NOW)
    # One span per reference: "[REF: STATUS — note]".
    assert "[IMC 403.3: CHECKED_SUPPORTS — matches the table]" in doc
    assert "[NEC 210.8: CHECKED_MISMATCH — " in doc
    # Long notes are truncated to ~120 chars.
    assert "x" * 120 not in doc
    assert "x" * 119 + "…" in doc
    # Phase B: a mismatch reads as a warning, never the muted pass styling.
    assert 'class="citation-note citation-mismatch"' in doc
    assert ".citation-mismatch{" in doc


def test_citation_mismatch_renders_editions_and_evidence_link():
    from drawing_analyzer.models import CitationAssessment

    f = _finding()
    f.citations = [CitationAssessment(
        reference="NFPA 13 §8.15.1", status="CHECKED_MISMATCH", note="moved",
        adopted_edition="NFPA 13 2016", checked_edition="NFPA 13 2016",
        current_edition="NFPA 13 2025",
        evidence_url="https://codes.example.org/nfpa13?a=1&b=2",
    )]
    doc = hr.build_html_report(_findings_ctx(findings=[f]), source_names=[SRC], now=NOW)
    assert "(adopted: NFPA 13 2016; checked: NFPA 13 2016; current: NFPA 13 2025)" in doc
    # Evidence link: https-only, escaped, no-opener.
    assert 'href="https://codes.example.org/nfpa13?a=1&amp;b=2"' in doc
    assert 'rel="noopener noreferrer"' in doc
    # A non-https URL never becomes a link (defense in depth beyond the parser).
    f2 = _finding()
    f2.citations = [CitationAssessment(reference="R", status="CHECKED_SUPPORTS",
                                       evidence_url="javascript:alert(1)")]
    doc2 = hr.build_html_report(_findings_ctx(findings=[f2]), source_names=[SRC], now=NOW)
    assert "javascript:alert(1)" not in doc2
    assert 'class="citation-evidence"' not in doc2


def test_legacy_single_citation_fallback_when_citations_empty():
    from drawing_analyzer.models import Citation

    f = _finding()
    f.citation = Citation(status="CHECKED_SUPPORTS", note="ok per 2021 edition")
    doc = hr.build_html_report(_findings_ctx(findings=[f]), source_names=[SRC], now=NOW)
    assert "[citation supports: ok per 2021 edition]" in doc
    # The legacy fallback also distinguishes a mismatch (Phase B).
    f2 = _finding()
    f2.citation = Citation(status="CHECKED_MISMATCH", note="renumbered")
    doc2 = hr.build_html_report(_findings_ctx(findings=[f2]), source_names=[SRC], now=NOW)
    assert 'class="citation-note citation-mismatch"' in doc2


def test_prose_chip_renders_item_count():
    f = _finding()
    f.prose_item_ids = ["M-101:p0:i1", "M-101:p0:i2"]
    doc = hr.build_html_report(_findings_ctx(findings=[f]), source_names=[SRC], now=NOW)
    assert "prose×2" in doc


def test_a11y_attributes_present():
    ctx = _findings_ctx(findings=[_finding()])
    doc = hr.build_html_report(ctx, source_names=[SRC], now=NOW)
    assert 'aria-label="Search the report"' in doc
    assert 'id="result-count" role="status"' in doc
    assert 'aria-label="Report contents"' in doc
    # Every chip starts with an explicit pressed state ("All" is preselected).
    assert 'data-filter="all" aria-pressed="true"' in doc
    assert 'data-filter="issues" aria-pressed="false"' in doc
    # Card heads announce their expanded state; sortable headers are keyboard-
    # reachable and announce their sort direction.
    assert 'role="button" tabindex="0" aria-expanded="true"' in doc
    assert 'data-sort="severity" tabindex="0" aria-sort="none"' in doc
    # The JS keeps all three in sync.
    assert "setAttribute('aria-pressed'" in hr._JS
    assert "setAttribute('aria-expanded'" in hr._JS
    assert "setAttribute('aria-sort'" in hr._JS
