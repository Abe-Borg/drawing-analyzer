"""Structured-findings parsing + digest integration. Pure — no PyMuPDF/network.

Covers the FINDINGS block contract: the model appends a fenced ``json`` block
after the prose digest; the parser extracts it and hands back the prose with the
block removed, so ``combined_text`` (the sacred prose, I-2) is untouched and the
findings live only in their own artifacts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer.digest import (
    MAX_FINDINGS_PER_SHEET,
    SheetDigest,
    digest_sheet,
    findings_from_cache,
    parse_findings,
)
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

OPUS = "claude-opus-4-8"


def _ref(source="M-101.pdf", page=0):
    return SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)


def _block(findings):
    return "```json\n" + json.dumps({"findings": findings}) + "\n```"


def _item(**over):
    base = {"sheet_id": "M-101", "category": "code", "severity": "high", "text": "An issue."}
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# parse_findings
# --------------------------------------------------------------------------- #


def test_parse_prose_only_is_byte_identical():
    prose = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Rm 120."
    out_prose, findings, note = parse_findings(prose, _ref())
    assert out_prose == prose      # byte-for-byte unchanged (I-2)
    assert findings == [] and note == ""


def test_parse_extracts_block_and_cleans_prose():
    prose = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Rm 120."
    raw = prose + "\n\n" + _block([
        _item(source_quote="VAV-3", tile=[2, 3], refs=["CMC 310"]),
    ])
    out_prose, findings, note = parse_findings(raw, _ref())
    assert out_prose == prose                     # block (and its fence) removed
    assert "findings" not in out_prose and "```" not in out_prose
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "code" and f.severity == "high"
    assert f.source_quote == "VAV-3" and f.tile == [2, 3] and f.refs == ["CMC 310"]
    assert f.source_name == "M-101.pdf" and f.page_index == 0
    # DRAFT state: unanchored, unverified.
    assert f.anchor.status == "UNANCHORED" and f.verification.status == "SKIPPED"
    assert note == ""


def test_parse_drops_invalid_items_and_notes_count():
    raw = "prose\n" + _block([
        _item(),                                   # valid
        _item(category="bogus"),                   # invalid category
        _item(severity="urgent"),                  # invalid severity
        {"category": "code", "severity": "low"},   # missing text
        _item(text="   "),                         # blank text
    ])
    _, findings, note = parse_findings(raw, _ref())
    assert len(findings) == 1
    assert "dropped 4" in note


def test_parse_sheet_id_fallback_when_absent():
    raw = "prose\n" + _block([{"category": "conflict", "severity": "low", "text": "x"}])
    _, findings, _ = parse_findings(raw, _ref("P-201.pdf", page=3))
    assert findings[0].sheet_id == "P-201-p4"      # stem + 1-based page


def test_parse_takes_last_block_and_strips_from_first():
    raw = (
        "Prose.\n"
        + _block([_item(text="first")])
        + "\nmid-prose\n"
        + _block([_item(text="second-authoritative")])
    )
    out_prose, findings, _ = parse_findings(raw, _ref())
    # Last block wins for extraction; prose is cut at the FIRST block so neither
    # JSON block leaks into the prose.
    assert [f.text for f in findings] == ["second-authoritative"]
    assert out_prose == "Prose."


def test_parse_malformed_block_strips_but_yields_no_findings():
    raw = "Prose here.\n```json\n{\"findings\": [ {\"category\": ,, ] BROKEN\n```"
    out_prose, findings, note = parse_findings(raw, _ref())
    assert out_prose == "Prose here."
    assert findings == []
    assert "unparseable" in note


def test_parse_non_findings_fenced_block_is_left_in_prose():
    # A fenced block that isn't a findings block (a code snippet, some other
    # json) must not be stripped or mistaken for findings.
    raw = "Prose.\n```\nsome pseudo-code\n```\ntail"
    out_prose, findings, note = parse_findings(raw, _ref())
    assert out_prose == raw and findings == [] and note == ""


# --- DA-009: a truncated / unclosed findings block must NEVER leak into prose --


def test_parse_truncated_unclosed_block_does_not_leak_into_prose():
    # Phase 22 §14.2 (DA-009): the model's output was cut off (max_tokens) mid-JSON
    # so there is NO closing ``` fence. The old scanner required one, so the whole
    # partial machine block leaked verbatim into the sacred prose. It must not.
    from drawing_analyzer.digest import parse_findings_detailed
    from drawing_analyzer.models import FINDINGS_TRUNCATED

    prose = "Sheet M-101 - Mechanical - Plan.\nVAV-3 serves Rm 120."
    raw = prose + '\n\n```json\n{"findings": [ {"category": "code", "severity":'
    r = parse_findings_detailed(raw, _ref())
    assert r.prose == prose                       # cut at the opener, byte-clean
    assert "```" not in r.prose and '"findings"' not in r.prose
    assert r.findings == [] and r.status == FINDINGS_TRUNCATED


def test_parse_unclosed_but_complete_json_is_recovered():
    # §14.2: an unclosed fence whose JSON object is nonetheless complete and valid
    # → parse it, record the drift, and still keep the prose clean.
    from drawing_analyzer.digest import parse_findings_detailed
    from drawing_analyzer.models import FINDINGS_PARSED_UNCLOSED

    raw = 'Prose.\n```json\n{"findings": [' + json.dumps(_item(source_quote="VAV-3"))[0:] + "]}"
    r = parse_findings_detailed(raw, _ref())
    assert r.prose == "Prose." and len(r.findings) == 1
    assert r.status == FINDINGS_PARSED_UNCLOSED and "unclosed" in r.note.lower()


def test_parse_prose_with_word_findings_is_not_stripped():
    # §14.1: ordinary prose that merely contains the English word "findings" (no
    # json-labeled block) is returned byte-identical — never mistaken for a block.
    raw = "My findings: the sheet is coherent and ready to issue."
    out_prose, findings, note = parse_findings(raw, _ref())
    assert out_prose == raw and findings == [] and note == ""


def test_parse_unclosed_malformed_block_is_stripped_not_leaked():
    # §14.2: an unclosed fence whose body is garbage (not a recoverable object) is
    # still a findings attempt — stripped from prose, yields no findings.
    from drawing_analyzer.digest import parse_findings_detailed

    prose = "Prose digest."
    raw = prose + '\n```json\n{"findings": [ garbage } not-json {'
    r = parse_findings_detailed(raw, _ref())
    assert r.prose == prose and r.findings == []
    assert "```" not in r.prose and "findings" not in r.prose


def test_digest_sheet_truncated_block_keeps_prose_clean_and_ships():
    # End-to-end (DA-009): a truncated findings block must not fail the sheet (I-3)
    # and must not contaminate the shipped prose digest.
    raw = "Good prose digest of the sheet.\n```json\n{\"findings\": [ {\"category\":"
    client = _FakeClient(lambda kw: FakeMessage(
        content=[FakeTextBlock(text=raw)], stop_reason="max_tokens"))
    sd = digest_sheet(_sheet(), client=client, model=OPUS)
    assert sd.ok and sd.error is None
    assert sd.text == "Good prose digest of the sheet."
    assert "```" not in sd.text and '"findings"' not in sd.text
    assert sd.findings == []


def test_parse_caps_at_max():
    raw = "prose\n" + _block([_item(text=f"f{i}") for i in range(MAX_FINDINGS_PER_SHEET + 12)])
    _, findings, note = parse_findings(raw, _ref())
    assert len(findings) == MAX_FINDINGS_PER_SHEET
    assert f"capped at {MAX_FINDINGS_PER_SHEET}" in note


def test_parse_tolerates_trailing_comma():
    raw = 'prose\n```json\n{"findings": [{"category":"code","severity":"low","text":"x"},]}\n```'
    _, findings, _ = parse_findings(raw, _ref())
    assert len(findings) == 1


def test_parse_preserves_verbatim_quote_with_comma_before_bracket():
    # A comma INSIDE a string value that happens to precede "]"/"}" must NOT be
    # stripped — well-formed JSON is parsed as-is, so the verbatim source_quote
    # (which drives anchoring and the finding id) survives exactly.
    raw = (
        "prose\n```json\n"
        '{"findings":[{"category":"coordination","severity":"low",'
        '"text":"see note","source_quote":"KEYNOTES 3,]","tile":null,"refs":[]}]}'
        "\n```"
    )
    _, findings, _ = parse_findings(raw, _ref())
    assert len(findings) == 1
    assert findings[0].source_quote == "KEYNOTES 3,]"   # not "KEYNOTES 3]"


def test_parse_trailing_comma_repair_is_string_aware():
    # Genuine trailing comma (before ]) is repaired, while a comma-before-bracket
    # inside a string value in the SAME payload is preserved.
    raw = (
        "prose\n```json\n"
        '{"findings":[{"category":"code","severity":"low",'
        '"text":"a, b]","source_quote":"x",},]}'
        "\n```"
    )
    _, findings, _ = parse_findings(raw, _ref())
    assert len(findings) == 1
    assert findings[0].text == "a, b]"                  # verbatim, comma intact


# --------------------------------------------------------------------------- #
# digest_sheet integration
# --------------------------------------------------------------------------- #


def _sheet(rows=2, cols=2):
    ref = _ref()
    ov = ImageTile(png_bytes=b"OVERVIEW", width_px=2000, height_px=1500, kind="overview")
    tiles = [
        ImageTile(png_bytes=f"T{r}{c}".encode(), width_px=2000, height_px=1500,
                  kind="tile", row=r, col=c, label=f"r{r}c{c}")
        for r in range(rows) for c in range(cols)
    ]
    return RenderedSheet(ref=ref, overview=ov, tiles=tiles,
                         page_width_pt=3168, page_height_pt=2448, rows=rows, cols=cols,
                         sheet_text="VAV-3 serves Rm 120")


class _FakeClient:
    def __init__(self, responder):
        self.calls = []

        class _Msgs:
            def create(_s, **kw):
                self.calls.append(kw)
                return responder(kw)

        self.messages = _Msgs()


def test_digest_sheet_populates_findings_and_clean_prose():
    raw = "Sheet M-101 digest body." + "\n\n" + _block([_item(source_quote="VAV-3")])
    client = _FakeClient(lambda kw: FakeMessage(
        content=[FakeTextBlock(text=raw)], usage=FakeUsage(input_tokens=500, output_tokens=80)))
    sd = digest_sheet(_sheet(), client=client, model=OPUS)
    assert sd.ok and sd.error is None
    assert sd.text == "Sheet M-101 digest body."     # prose only, block stripped
    assert "```" not in sd.text
    assert len(sd.findings) == 1 and sd.findings[0].source_quote == "VAV-3"


def test_digest_sheet_malformed_block_does_not_fail_the_sheet():
    raw = "Good prose digest.\n```json\n{\"findings\": broken\n```"
    client = _FakeClient(lambda kw: FakeMessage(content=[FakeTextBlock(text=raw)]))
    sd = digest_sheet(_sheet(), client=client, model=OPUS)
    # The prose shipped, so the sheet is OK; findings are empty and the parse
    # problem is telemetry only — never on `error`.
    assert sd.ok and sd.error is None
    assert sd.text == "Good prose digest."
    assert sd.findings == [] and "unparseable" in sd.findings_note


def test_digest_sheet_caches_and_reconstructs_findings():
    raw = "Prose body." + "\n" + _block([
        _item(source_quote="VAV-3", tile=[1, 1], refs=["CMC 310"]),
        _item(category="conflict", severity="low", text="second"),
    ])
    cache = DigestCache(None, persist=False)
    client = _FakeClient(lambda kw: FakeMessage(content=[FakeTextBlock(text=raw)]))

    first = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    assert not first.cached and len(first.findings) == 2
    assert len(client.calls) == 1

    second = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    assert second.cached and len(client.calls) == 1          # served from cache
    assert second.text == "Prose body."
    # Findings survive the cache round-trip byte-for-byte (ids and all).
    assert [f.to_dict() for f in second.findings] == [f.to_dict() for f in first.findings]


def test_findings_from_cache_is_defensive():
    assert findings_from_cache({}, _ref()) == []
    assert findings_from_cache({"findings": "not a list"}, _ref()) == []
    assert findings_from_cache({"findings": [42, "junk"]}, _ref()) == []


# --------------------------------------------------------------------------- #
# pipeline I-2: combined_text stays prose-clean end-to-end (needs PyMuPDF)
# --------------------------------------------------------------------------- #


def test_pipeline_combined_text_excludes_findings_block(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    doc = pymupdf.open()
    doc.new_page(width=792, height=612).insert_text((72, 72), "SHEET M-101 VAV-3")
    path = tmp_path / "set.pdf"
    doc.save(str(path))
    doc.close()

    raw = "Sheet M-101 - Mechanical digest body." + "\n\n" + _block([
        _item(source_quote="VAV-3", tile=[0, 0]),
    ])
    client = _FakeClient(lambda kw: FakeMessage(content=[FakeTextBlock(text=raw)]))
    ctx = extract_drawing_context([path], client=client, rows=2, cols=2)

    # The sacred prose digest reached combined_text; the JSON block did NOT (I-2).
    assert "Mechanical digest body" in ctx.combined_text
    assert "```json" not in ctx.combined_text
    assert '"findings"' not in ctx.combined_text
    # The structured findings rode out on the sheet result instead.
    assert len(ctx.sheets) == 1 and len(ctx.sheets[0].findings) == 1
    assert ctx.sheets[0].findings[0].source_quote == "VAV-3"
