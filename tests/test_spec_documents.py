"""Project-specifications upload: extraction, budgeting, prompt injection,
cache keying, and pipeline integration.

Hermetic, mirroring ``test_drawing_focus.py``'s structure: pure prompt/cache
tests use the dependency-free models and a fake client; pipeline integration
tests render a synthetic PDF and are skipped without PyMuPDF.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer.digest import (
    DIGEST_PROMPT_VERSION,
    DIGEST_SYSTEM_PROMPT,
    SheetDigest,
    build_specs_addendum,
    build_user_content,
    digest_sheet,
    digest_system_prompt,
    normalize_specs_text,
    specs_cache_fragment,
)
from drawing_analyzer.digest_cache import DigestCache, digest_cache_key
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from drawing_analyzer.spec_documents import (
    SPEC_FILE_CHAR_BUDGET,
    SPEC_TOTAL_CHAR_BUDGET,
    SpecDocument,
    build_specs_text,
    enforce_specs_budget,
    extract_spec_documents,
    extract_spec_text,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

OPUS = "claude-opus-4-8"
BEAM_SPEC = "All structural steel beams shall be W12x26 minimum, per AISC 360."


def _system_text(kw: dict) -> str:
    """Normalize a captured request's ``system`` (plain string, or the
    two-block cached-prefix list a specs-bearing digest request now uses)."""
    system = kw.get("system", "")
    if isinstance(system, list):
        return "".join(block.get("text", "") for block in system)
    return system or ""


def _make_sheet(rows: int = 2, cols: int = 2) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=Path("S-101.pdf"), page_index=0, source_name="S-101.pdf", page_count=1
    )
    overview = ImageTile(
        png_bytes=b"OVERVIEW", width_px=2000, height_px=1500, kind="overview"
    )
    tiles = [
        ImageTile(
            png_bytes=f"T{r}{c}".encode(), width_px=2000, height_px=1500,
            kind="tile", row=r, col=c, label=f"r{r}c{c}",
        )
        for r in range(rows)
        for c in range(cols)
    ]
    return RenderedSheet(
        ref=ref, overview=overview, tiles=tiles,
        page_width_pt=3168, page_height_pt=2448, rows=rows, cols=cols,
    )


class _FakeClient:
    def __init__(self, responder):
        self.calls: list[dict] = []

        class _Msgs:
            def create(_self, **kw):
                self.calls.append(kw)
                return responder(kw)

        self.messages = _Msgs()


# --------------------------------------------------------------------------- #
# Extraction (spec_documents.py, pure)
# --------------------------------------------------------------------------- #


def test_extract_txt_reads_directly(tmp_path):
    p = tmp_path / "spec.txt"
    p.write_text("Section 1: All beams shall be W12x26.\n")
    doc = extract_spec_text(p)
    assert doc.ok
    assert doc.text == "Section 1: All beams shall be W12x26."


def test_extract_md_reads_directly(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# Spec\n\nAll beams shall be W12x26.")
    doc = extract_spec_text(p)
    assert doc.ok
    assert "W12x26" in doc.text


def test_extract_pdf_text(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    p = tmp_path / "spec.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page()
    page.insert_text((72, 72), "SECTION 05 12 00 - STRUCTURAL STEEL")
    page.insert_text((72, 100), "All beams shall be W12x26 minimum.")
    doc_pdf.save(str(p))
    doc_pdf.close()

    doc = extract_spec_text(p)
    assert doc.ok
    assert "STRUCTURAL STEEL" in doc.text
    assert "W12x26" in doc.text


def test_extract_docx_text_including_tables(tmp_path):
    docx = pytest.importorskip("docx")
    p = tmp_path / "spec.docx"
    w = docx.Document()
    w.add_paragraph("SECTION 03 30 00 - CAST-IN-PLACE CONCRETE")
    w.add_paragraph("Concrete shall achieve 4000 psi at 28 days.")
    table = w.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Mix"
    table.cell(0, 1).text = "4000 psi"
    w.save(str(p))

    doc = extract_spec_text(p)
    assert doc.ok
    assert "CAST-IN-PLACE CONCRETE" in doc.text
    assert "Mix | 4000 psi" in doc.text


def test_extract_unsupported_extension_is_a_captured_error(tmp_path):
    p = tmp_path / "spec.xyz"
    p.write_text("whatever")
    doc = extract_spec_text(p)
    assert not doc.ok
    assert "unsupported file type" in doc.error


def test_extract_missing_file_is_a_captured_error(tmp_path):
    doc = extract_spec_text(tmp_path / "does_not_exist.pdf")
    assert not doc.ok
    assert doc.error


def test_extract_corrupt_pdf_is_a_captured_error(tmp_path):
    p = tmp_path / "corrupt.pdf"
    p.write_bytes(b"not actually a pdf")
    doc = extract_spec_text(p)
    assert not doc.ok
    assert doc.error


def test_extract_empty_text_file_is_a_captured_error(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("   \n\n  ")
    doc = extract_spec_text(p)
    assert not doc.ok
    assert "no extractable text" in doc.error


def test_extract_spec_documents_one_bad_file_does_not_abort_the_rest(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("real spec text")
    bad = tmp_path / "bad.xyz"
    bad.write_text("whatever")

    docs = extract_spec_documents([good, bad])
    assert len(docs) == 2
    assert docs[0].ok and not docs[1].ok


# --------------------------------------------------------------------------- #
# Budgeting (spec_documents.py, pure)
# --------------------------------------------------------------------------- #


def test_build_specs_text_under_budget_is_unchanged():
    docs = [SpecDocument(path=Path("a.txt"), display_name="a.txt", text="hello spec")]
    text, budget = build_specs_text(docs)
    assert "hello spec" in text
    assert "a.txt" in text
    assert not budget.degraded
    assert budget.omitted_chars == 0


def test_build_specs_text_per_file_budget_caps_one_huge_file():
    docs = [
        SpecDocument(path=Path("a.txt"), display_name="a.txt", text="x" * (SPEC_FILE_CHAR_BUDGET + 500)),
        SpecDocument(path=Path("b.txt"), display_name="b.txt", text="y" * 100),
    ]
    text, budget = build_specs_text(docs)
    assert budget.degraded
    assert "a.txt" in budget.omitted_files
    assert "b.txt" not in budget.omitted_files
    assert "y" * 100 in text  # the small file survives intact


def test_build_specs_text_total_budget_caps_the_whole_block():
    docs = [
        SpecDocument(path=Path(f"{i}.txt"), display_name=f"{i}.txt", text="z" * 1_000)
        for i in range(200)  # 200,000 chars total, well over the whole-block cap
    ]
    text, budget = build_specs_text(docs)
    assert len(text) <= SPEC_TOTAL_CHAR_BUDGET + 100  # + truncation marker slack
    assert budget.degraded


def test_build_specs_text_skips_failed_documents():
    docs = [
        SpecDocument(path=Path("a.txt"), display_name="a.txt", text="kept"),
        SpecDocument(path=Path("b.txt"), display_name="b.txt", error="bad file"),
    ]
    text, _budget = build_specs_text(docs)
    assert "kept" in text
    assert "b.txt" not in text


def test_enforce_specs_budget_empty_and_none():
    text, budget = enforce_specs_budget(None)
    assert text == "" and not budget.degraded
    text, budget = enforce_specs_budget("   ")
    assert text == "" and not budget.degraded


def test_enforce_specs_budget_defensive_backstop():
    text, budget = enforce_specs_budget("q" * (SPEC_TOTAL_CHAR_BUDGET + 1_000))
    assert len(text) <= SPEC_TOTAL_CHAR_BUDGET + 100
    assert budget.degraded
    assert budget.omitted_chars == 1_000


# --------------------------------------------------------------------------- #
# Prompt assembly (digest.py, pure)
# --------------------------------------------------------------------------- #


def test_digest_system_prompt_without_specs_is_a_plain_string():
    base = digest_system_prompt(None, None)
    assert isinstance(base, str)
    assert digest_system_prompt(None, "") == base
    assert digest_system_prompt(None, "   ") == base
    assert base.startswith(DIGEST_SYSTEM_PROMPT)
    assert "PROJECT SPECIFICATIONS" not in base


def test_digest_system_prompt_with_specs_is_a_two_block_list():
    prompt = digest_system_prompt(None, BEAM_SPEC)
    assert isinstance(prompt, list)
    assert len(prompt) == 2
    assert prompt[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in prompt[1]
    assert prompt[0]["text"].startswith(DIGEST_SYSTEM_PROMPT)
    assert BEAM_SPEC in prompt[0]["text"]
    assert "<project_specifications>" in prompt[0]["text"]
    assert "FINDINGS (final section" in prompt[1]["text"]


def test_digest_system_prompt_specs_and_focus_together():
    # The specs+base prefix (block 0) is identical regardless of focus — the
    # core claim behind caching it independently of the per-run focus.
    no_focus = digest_system_prompt(None, BEAM_SPEC)
    with_focus = digest_system_prompt("check egress widths", BEAM_SPEC)
    assert no_focus[0] == with_focus[0]
    assert no_focus[1] != with_focus[1]
    assert "ADDITIONAL PER-RUN FOCUS" in with_focus[1]["text"]
    assert "ADDITIONAL PER-RUN FOCUS" not in no_focus[1]["text"]


def test_digest_system_prompt_cache_specs_false_returns_plain_string():
    prompt = digest_system_prompt(None, BEAM_SPEC, cache_specs=False)
    assert isinstance(prompt, str)
    assert BEAM_SPEC in prompt
    assert prompt.startswith(DIGEST_SYSTEM_PROMPT)


def test_specs_do_not_change_user_content():
    sheet = _make_sheet()
    resp = FakeMessage(content=[FakeTextBlock(text="digest")])
    plain = _FakeClient(lambda kw: resp)
    specced = _FakeClient(lambda kw: resp)
    digest_sheet(sheet, client=plain, model=OPUS)
    digest_sheet(sheet, client=specced, model=OPUS, specs_text=BEAM_SPEC)
    assert plain.calls[0]["messages"] == specced.calls[0]["messages"]
    assert "PROJECT SPECIFICATIONS" not in _system_text(plain.calls[0])
    assert BEAM_SPEC in _system_text(specced.calls[0])


def test_build_specs_addendum_does_not_ask_for_a_new_section():
    addendum = build_specs_addendum(BEAM_SPEC)
    assert "ORDINARY finding" in addendum
    assert "Do NOT add a separate prose section" in addendum
    assert "Focus findings" not in addendum


def test_normalize_specs_text():
    assert normalize_specs_text(None) is None
    assert normalize_specs_text("") is None
    assert normalize_specs_text("   \n\t ") is None
    assert normalize_specs_text("  W12x26  ") == "W12x26"


# --------------------------------------------------------------------------- #
# Cache-key isolation
# --------------------------------------------------------------------------- #


def _key(sheet, specs_fragment=None):
    kwargs = dict(
        model=OPUS, prompt_version=DIGEST_PROMPT_VERSION, max_tokens=16_000,
        effort="high", use_thinking=True,
    )
    if specs_fragment is not None:
        kwargs["specs"] = specs_fragment
    return digest_cache_key(sheet, **kwargs)


def test_cache_key_without_specs_is_backward_compatible():
    sheet = _make_sheet()
    assert _key(sheet) == _key(sheet, specs_fragment=None)
    assert _key(sheet) == _key(sheet, specs_fragment=specs_cache_fragment(None))
    assert _key(sheet) == _key(sheet, specs_fragment=specs_cache_fragment("  "))


def test_cache_key_folds_specs_in():
    sheet = _make_sheet()
    plain = _key(sheet)
    beams = _key(sheet, specs_fragment=specs_cache_fragment(BEAM_SPEC))
    other = _key(sheet, specs_fragment=specs_cache_fragment("concrete shall be 4000 psi"))
    assert plain != beams
    assert beams != other
    assert beams == _key(sheet, specs_fragment=specs_cache_fragment(BEAM_SPEC))


def test_cache_key_specs_and_focus_are_independent_axes():
    from drawing_analyzer.digest import focus_cache_fragment

    sheet = _make_sheet()
    specs_only = digest_cache_key(
        sheet, model=OPUS, prompt_version=DIGEST_PROMPT_VERSION, max_tokens=16_000,
        effort="high", use_thinking=True, specs=specs_cache_fragment(BEAM_SPEC),
    )
    focus_only = digest_cache_key(
        sheet, model=OPUS, prompt_version=DIGEST_PROMPT_VERSION, max_tokens=16_000,
        effort="high", use_thinking=True, focus=focus_cache_fragment("check egress"),
    )
    both = digest_cache_key(
        sheet, model=OPUS, prompt_version=DIGEST_PROMPT_VERSION, max_tokens=16_000,
        effort="high", use_thinking=True,
        specs=specs_cache_fragment(BEAM_SPEC), focus=focus_cache_fragment("check egress"),
    )
    assert len({specs_only, focus_only, both, _key(sheet)}) == 4


def test_digest_sheet_specs_isolated_in_cache():
    sheet = _make_sheet()
    cache = DigestCache(None, persist=False)
    client = _FakeClient(lambda kw: FakeMessage(content=[FakeTextBlock(text="digest body")]))

    first = digest_sheet(sheet, client=client, model=OPUS, cache=cache)
    assert first.ok and not first.cached
    assert len(client.calls) == 1

    specced = digest_sheet(sheet, client=client, model=OPUS, cache=cache, specs_text=BEAM_SPEC)
    assert specced.ok and not specced.cached
    assert len(client.calls) == 2

    specced_again = digest_sheet(sheet, client=client, model=OPUS, cache=cache, specs_text=BEAM_SPEC)
    assert specced_again.cached
    assert len(client.calls) == 2

    plain_again = digest_sheet(sheet, client=client, model=OPUS, cache=cache)
    assert plain_again.cached
    assert len(client.calls) == 2


# --------------------------------------------------------------------------- #
# Cache-token telemetry
# --------------------------------------------------------------------------- #


def test_digest_sheet_records_cache_tokens_from_response():
    sheet = _make_sheet()
    resp = FakeMessage(
        content=[FakeTextBlock(text="digest")],
        usage=FakeUsage(input_tokens=500, output_tokens=50,
                         cache_creation_input_tokens=300, cache_read_input_tokens=0),
    )
    client = _FakeClient(lambda kw: resp)
    sd = digest_sheet(sheet, client=client, model=OPUS, specs_text=BEAM_SPEC)
    assert sd.cache_write_tokens == 300
    assert sd.cache_read_tokens == 0


def test_digest_sheet_cache_hit_reports_zero_cache_tokens():
    sheet = _make_sheet()
    cache = DigestCache(None, persist=False)
    resp = FakeMessage(
        content=[FakeTextBlock(text="digest body")],
        usage=FakeUsage(cache_creation_input_tokens=300, cache_read_input_tokens=50),
    )
    client = _FakeClient(lambda kw: resp)
    digest_sheet(sheet, client=client, model=OPUS, cache=cache, specs_text=BEAM_SPEC)
    hit = digest_sheet(sheet, client=client, model=OPUS, cache=cache, specs_text=BEAM_SPEC)
    assert hit.cached
    assert hit.cache_write_tokens == 0
    assert hit.cache_read_tokens == 0


def test_batch_digest_disables_cache_specs():
    # The actual parallel batch-item build (batch_digest.py's submit_drawing_batch)
    # always passes cache_specs=False to build_digest_request_params — a parallel
    # batch has no reader for a cache write, so a breakpoint there would only add
    # the 1.25x write cost with nothing to read. Exercise that call shape directly.
    from drawing_analyzer.digest import build_digest_request_params

    params = build_digest_request_params(
        [{"type": "text", "text": "content"}], model=OPUS,
        specs_text=BEAM_SPEC, cache_specs=False,
    )
    assert isinstance(params["system"], str)
    assert BEAM_SPEC in params["system"]


# --------------------------------------------------------------------------- #
# Pipeline integration (renders a synthetic PDF; needs PyMuPDF)
# --------------------------------------------------------------------------- #


def _make_pdf(pymupdf, path: Path, *, page_text: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), page_text)
    page.insert_text((650, 560), "S-101")  # title-block sheet id
    doc.save(str(path))
    doc.close()
    return path


def _digest_block(findings: list[dict]) -> str:
    return "```json\n" + json.dumps({"findings": findings}) + "\n```"


_SPEC_CONFLICT_FINDING = {
    "sheet_id": "S-101", "category": "conflict", "severity": "high",
    "text": "Beam shown as W10X22, but spec requires W12x26 minimum.",
    "source_quote": "W10X22", "tile": [0, 0],
    "refs": [],
}


def _routing_client(calls: list, *, findings: list[dict]):
    prose = "Sheet S-101 - Structural - Plan\nBeam W10X22 shown at gridline 3."
    digest_text = prose + "\n\n" + _digest_block(findings)

    def responder(kw):
        calls.append(kw)
        return FakeMessage(
            content=[FakeTextBlock(text=digest_text)],
            usage=FakeUsage(input_tokens=100, output_tokens=20),
        )

    class _C:
        def __init__(self):
            class _M:
                def create(_s, **kw):
                    return responder(kw)

            self.messages = _M()

    return _C()


def test_pipeline_specs_fold_into_findings_not_a_new_section(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", page_text="BEAM W10X22 AT GRIDLINE 3")
    calls: list = []
    ctx = extract_drawing_context(
        [path], client=_routing_client(calls, findings=[_SPEC_CONFLICT_FINDING]),
        rows=1, cols=1, project_specifications=BEAM_SPEC,
    )

    assert ctx.project_specifications == BEAM_SPEC
    # The conflict is an ordinary finding, routed through the standard ledger —
    # NOT a new bolt-on prose section (contrast with focus's "Focus Report").
    assert len(ctx.findings) == 1
    assert "W12x26" in ctx.findings[0].text
    assert "Project Specifications" not in ctx.combined_text
    assert "Spec Report" not in ctx.combined_text
    # Every digest call carried the specs block.
    assert len(calls) == 1
    assert BEAM_SPEC in _system_text(calls[0])
    assert "<project_specifications>" in _system_text(calls[0])
    assert ctx.errors == []


def test_pipeline_no_specs_changes_nothing(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", page_text="BEAM W10X22 AT GRIDLINE 3")
    calls: list = []
    ctx = extract_drawing_context(
        [path], client=_routing_client(calls, findings=[]), rows=1, cols=1,
    )

    assert ctx.project_specifications == ""
    assert len(calls) == 1
    assert "PROJECT SPECIFICATIONS" not in _system_text(calls[0])
    assert _system_text(calls[0]).startswith(DIGEST_SYSTEM_PROMPT)


def test_pipeline_specs_truncation_appends_a_warning_to_errors(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", page_text="BEAM W10X22 AT GRIDLINE 3")
    calls: list = []
    huge_specs = "q" * (SPEC_TOTAL_CHAR_BUDGET + 5_000)
    ctx = extract_drawing_context(
        [path], client=_routing_client(calls, findings=[]), rows=1, cols=1,
        project_specifications=huge_specs,
    )

    assert any("Project specifications" in e and "omitted" in e for e in ctx.errors)
    assert len(ctx.project_specifications) <= SPEC_TOTAL_CHAR_BUDGET + 100


def test_pipeline_specs_under_budget_produces_no_warning(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", page_text="BEAM W10X22 AT GRIDLINE 3")
    calls: list = []
    ctx = extract_drawing_context(
        [path], client=_routing_client(calls, findings=[]), rows=1, cols=1,
        project_specifications=BEAM_SPEC,
    )
    assert ctx.errors == []
