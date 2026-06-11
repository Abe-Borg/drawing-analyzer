"""Per-run focus tests: prompt injection, cache keying, and the focus report.

Hermetic, mirroring the synthesis suite: the prompt/cache tests use the
dependency-free models and a fake client; the pipeline integration tests render
a synthetic PDF and are skipped without PyMuPDF.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer.digest import (
    DIGEST_PROMPT_VERSION,
    DIGEST_SYSTEM_PROMPT,
    FOCUS_SECTION_HEADER,
    SheetDigest,
    build_focus_addendum,
    build_user_content,
    digest_sheet,
    digest_system_prompt,
    focus_cache_fragment,
    normalize_focus,
)
from drawing_analyzer.digest_cache import DigestCache, digest_cache_key
from drawing_analyzer.focus import (
    FOCUS_REPORT_SYSTEM_PROMPT,
    build_focus_user_text,
    default_focus_model,
    generate_focus_report,
)
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

OPUS = "claude-opus-4-8"
ROOMS_FOCUS = "the rooms, and what types of plumbing fixtures each has"


class _FakeClient:
    def __init__(self, responder):
        self.calls: list[dict] = []

        class _Msgs:
            def create(_self, **kw):
                self.calls.append(kw)
                return responder(kw)

        self.messages = _Msgs()


def _make_sheet(rows: int = 2, cols: int = 2) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=Path("P-201.pdf"),
        page_index=0,
        source_name="P-201.pdf",
        page_count=1,
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


def _digest(name: str, text: str, error: str | None = None) -> SheetDigest:
    ref = SheetRef(
        pdf_path=Path(f"{name}.pdf"), page_index=0, source_name=f"{name}.pdf", page_count=1
    )
    return SheetDigest(ref=ref, text=text, error=error)


# --------------------------------------------------------------------------- #
# normalize_focus / prompt assembly (pure)
# --------------------------------------------------------------------------- #


def test_normalize_focus():
    assert normalize_focus(None) is None
    assert normalize_focus("") is None
    assert normalize_focus("   \n\t ") is None
    assert normalize_focus("  rooms and fixtures  ") == "rooms and fixtures"


def test_digest_system_prompt_without_focus_is_unchanged():
    # The default deliverable's prompt is byte-identical with no focus — the
    # feature is purely additive.
    assert digest_system_prompt(None) == DIGEST_SYSTEM_PROMPT
    assert digest_system_prompt("") == DIGEST_SYSTEM_PROMPT
    assert digest_system_prompt("  ") == DIGEST_SYSTEM_PROMPT


def test_digest_system_prompt_with_focus_appends_addendum():
    prompt = digest_system_prompt(ROOMS_FOCUS)
    # The standard prompt leads, in full, then the addendum.
    assert prompt.startswith(DIGEST_SYSTEM_PROMPT)
    assert ROOMS_FOCUS in prompt
    assert FOCUS_SECTION_HEADER in prompt
    assert prompt == DIGEST_SYSTEM_PROMPT + build_focus_addendum(ROOMS_FOCUS)


def test_focus_does_not_change_user_content():
    # The focus rides on the system prompt only, so the user content (and the
    # batch path's uploaded images) is identical with or without it.
    sheet = _make_sheet()
    assert build_user_content(sheet) == build_user_content(sheet)
    resp = FakeMessage(content=[FakeTextBlock(text="digest")])
    plain = _FakeClient(lambda kw: resp)
    focused = _FakeClient(lambda kw: resp)
    digest_sheet(sheet, client=plain, model=OPUS)
    digest_sheet(sheet, client=focused, model=OPUS, focus=ROOMS_FOCUS)
    assert plain.calls[0]["messages"] == focused.calls[0]["messages"]
    assert plain.calls[0]["system"] == DIGEST_SYSTEM_PROMPT
    assert focused.calls[0]["system"].startswith(DIGEST_SYSTEM_PROMPT)
    assert ROOMS_FOCUS in focused.calls[0]["system"]


# --------------------------------------------------------------------------- #
# Cache keying
# --------------------------------------------------------------------------- #


def _key(sheet, focus_fragment=None):
    kwargs = dict(
        model=OPUS,
        prompt_version=DIGEST_PROMPT_VERSION,
        max_tokens=16_000,
        effort="high",
        use_thinking=True,
    )
    if focus_fragment is not None:
        kwargs["focus"] = focus_fragment
    return digest_cache_key(sheet, **kwargs)


def test_cache_key_without_focus_is_backward_compatible():
    # Omitting the param, passing None, and a no-focus fragment all produce the
    # same key — pre-focus cache entries stay valid for no-focus runs.
    sheet = _make_sheet()
    assert _key(sheet) == _key(sheet, focus_fragment=None)
    assert _key(sheet) == _key(sheet, focus_fragment=focus_cache_fragment(None))
    assert _key(sheet) == _key(sheet, focus_fragment=focus_cache_fragment("  "))


def test_cache_key_folds_focus_in():
    sheet = _make_sheet()
    plain = _key(sheet)
    rooms = _key(sheet, focus_fragment=focus_cache_fragment(ROOMS_FOCUS))
    valves = _key(sheet, focus_fragment=focus_cache_fragment("valve schedules"))
    assert plain != rooms
    assert rooms != valves
    # Same focus → same key (a re-run with the same focus is served from cache).
    assert rooms == _key(sheet, focus_fragment=focus_cache_fragment(ROOMS_FOCUS))


def test_digest_sheet_focus_isolated_in_cache():
    # A digest cached without a focus must NOT be served to a focused run (and
    # vice-versa); the same focus on a re-run IS served from cache.
    sheet = _make_sheet()
    cache = DigestCache(None, persist=False)
    client = _FakeClient(
        lambda kw: FakeMessage(content=[FakeTextBlock(text="digest body")])
    )

    first = digest_sheet(sheet, client=client, model=OPUS, cache=cache)
    assert first.ok and not first.cached
    assert len(client.calls) == 1

    focused = digest_sheet(
        sheet, client=client, model=OPUS, cache=cache, focus=ROOMS_FOCUS
    )
    assert focused.ok and not focused.cached     # cache miss → fresh vision call
    assert len(client.calls) == 2

    focused_again = digest_sheet(
        sheet, client=client, model=OPUS, cache=cache, focus=ROOMS_FOCUS
    )
    assert focused_again.cached                  # same focus → served from cache
    assert len(client.calls) == 2

    plain_again = digest_sheet(sheet, client=client, model=OPUS, cache=cache)
    assert plain_again.cached                    # no-focus entry still intact
    assert len(client.calls) == 2


# --------------------------------------------------------------------------- #
# Focus-report model selection / user text
# --------------------------------------------------------------------------- #


def test_default_focus_model_env_override(monkeypatch):
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT

    monkeypatch.delenv("DRAWING_ANALYZER_FOCUS_MODEL", raising=False)
    assert default_focus_model() == REVIEW_MODEL_DEFAULT
    monkeypatch.setenv("DRAWING_ANALYZER_FOCUS_MODEL", "claude-sonnet-4-6")
    assert default_focus_model() == "claude-sonnet-4-6"


def test_build_focus_user_text_includes_focus_and_each_sheet():
    sheets = [
        _digest("P-101", "Rooms 101-104; WC-1, LAV-2 in each"),
        _digest("P-501", "fixture schedule: WC-1 wall-hung, LAV-2 counter"),
    ]
    text = build_focus_user_text(ROOMS_FOCUS, sheets)
    assert ROOMS_FOCUS in text
    assert "Sheet 1/2: P-101.pdf" in text
    assert "Sheet 2/2: P-501.pdf" in text
    assert "WC-1" in text and "LAV-2" in text
    assert text.rstrip().endswith("citing the sheet for each fact.")


# --------------------------------------------------------------------------- #
# generate_focus_report
# --------------------------------------------------------------------------- #


def test_focus_report_skipped_with_no_readable_sheets():
    client = _FakeClient(lambda kw: FakeMessage(content=[FakeTextBlock(text="x")]))
    result = generate_focus_report(
        [_digest("P-101", "", error="502 bad gateway")], ROOMS_FOCUS,
        client=client, model=OPUS,
    )
    assert not result.ok
    assert "insufficient" in result.error
    assert client.calls == []  # never hit the API


def test_focus_report_runs_for_a_single_readable_sheet():
    # Unlike synthesis (>=2), one readable sheet can answer a focus question.
    client = _FakeClient(
        lambda kw: FakeMessage(content=[FakeTextBlock(text="Room 101: WC-1")])
    )
    result = generate_focus_report(
        [_digest("P-101", "Room 101 has WC-1")], ROOMS_FOCUS,
        client=client, model=OPUS,
    )
    assert result.ok and "Room 101" in result.text


def test_focus_report_success_shape_and_telemetry():
    resp = FakeMessage(
        content=[FakeTextBlock(text="Room-by-room: 101 → WC-1, LAV-2 (P-101/P-501)")],
        usage=FakeUsage(input_tokens=700, output_tokens=90),
    )
    client = _FakeClient(lambda kw: resp)
    sheets = [_digest("P-101", "rooms plan"), _digest("P-501", "fixture schedule")]

    result = generate_focus_report(sheets, ROOMS_FOCUS, client=client, model=OPUS)

    assert result.ok
    assert result.input_tokens == 700 and result.output_tokens == 90
    assert result.model_used == OPUS
    kw = client.calls[0]
    assert kw["model"] == OPUS
    assert kw["system"] == FOCUS_REPORT_SYSTEM_PROMPT
    content = kw["messages"][0]["content"]
    assert ROOMS_FOCUS in content
    assert "rooms plan" in content and "fixture schedule" in content


def test_focus_report_excludes_failed_sheets_from_input():
    client = _FakeClient(lambda kw: FakeMessage(content=[FakeTextBlock(text="report")]))
    sheets = [
        _digest("P-101", "good plan text"),
        _digest("P-102", "", error="502 bad gateway"),
        _digest("P-501", "good schedule text"),
    ]
    generate_focus_report(sheets, ROOMS_FOCUS, client=client, model=OPUS)
    content = client.calls[0]["messages"][0]["content"]
    assert "good plan text" in content and "good schedule text" in content
    assert "502 bad gateway" not in content


def test_focus_report_api_error_is_clean_and_nonraising():
    class _StatusErr(Exception):
        status_code = 502

    def boom(_kw):
        raise _StatusErr("<html>502 Bad Gateway</html>")

    result = generate_focus_report(
        [_digest("a", "x")], ROOMS_FOCUS,
        client=_FakeClient(boom), model=OPUS, sleep=lambda _s: None,
    )
    assert not result.ok
    assert result.error == "502 bad gateway (server temporarily unavailable — try again)"


def test_focus_report_empty_response_flags_error():
    client = _FakeClient(lambda kw: FakeMessage(content=[], stop_reason="max_tokens"))
    result = generate_focus_report(
        [_digest("a", "x")], ROOMS_FOCUS, client=client, model=OPUS
    )
    assert not result.ok and "empty focus report" in result.error


def test_focus_report_retries_transient_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    class _StatusErr(Exception):
        status_code = 503

    def responder(_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _StatusErr("down")
        return FakeMessage(content=[FakeTextBlock(text="recovered report")])

    result = generate_focus_report(
        [_digest("a", "x")], ROOMS_FOCUS,
        client=_FakeClient(responder), model=OPUS, max_retries=2, sleep=slept.append,
    )
    assert result.ok and "recovered report" in result.text
    assert calls["n"] == 2 and slept == [2.0]


# --------------------------------------------------------------------------- #
# pipeline integration (renders a synthetic PDF; needs PyMuPDF)
# --------------------------------------------------------------------------- #


def _make_pdf(pymupdf, path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=792, height=612)
        page.insert_text((72, 72), f"SHEET P-20{i + 1} TEST")
    doc.save(str(path))
    doc.close()
    return path


def _routing_client(calls: list, *, focus_text="FOCUS REPORT: Room 101 → WC-1"):
    """Digest calls get digest text; the focus-report call gets the report."""

    def responder(kw):
        calls.append(kw)
        if kw["system"] == FOCUS_REPORT_SYSTEM_PROMPT:
            return FakeMessage(
                content=[FakeTextBlock(text=focus_text)],
                usage=FakeUsage(input_tokens=400, output_tokens=60),
            )
        assert kw["system"].startswith(DIGEST_SYSTEM_PROMPT)
        return FakeMessage(
            content=[FakeTextBlock(text="per-sheet digest body")],
            usage=FakeUsage(input_tokens=100, output_tokens=20),
        )

    class _C:
        def __init__(self):
            class _M:
                def create(_s, **kw):
                    return responder(kw)

            self.messages = _M()

    return _C()


def test_pipeline_focus_adds_report_and_keeps_default_output(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", pages=2)
    calls: list = []
    ctx = extract_drawing_context(
        [path], client=_routing_client(calls), rows=2, cols=2, focus=ROOMS_FOCUS
    )

    assert ctx.ok_sheet_count == 2
    assert ctx.focus == ROOMS_FOCUS
    assert ctx.focus_report_text == "FOCUS REPORT: Room 101 → WC-1"
    # The default deliverable is intact and the report is additive, leading it.
    assert "## Focus Report (operator-requested)" in ctx.combined_text
    assert ROOMS_FOCUS in ctx.combined_text
    assert "## Sheet 1/2" in ctx.combined_text and "## Sheet 2/2" in ctx.combined_text
    assert ctx.combined_text.index("Focus Report") < ctx.combined_text.index("## Sheet 1/2")
    # Every digest call carried the focus on its system prompt.
    digest_calls = [kw for kw in calls if kw["system"] != FOCUS_REPORT_SYSTEM_PROMPT]
    assert len(digest_calls) == 2
    assert all(ROOMS_FOCUS in kw["system"] for kw in digest_calls)
    # Focus-pass tokens fold into the run totals (2*100 digests + 400 report).
    assert ctx.total_input_tokens == 600
    assert ctx.errors == []


def test_pipeline_no_focus_changes_nothing(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", pages=2)
    calls: list = []
    ctx = extract_drawing_context([path], client=_routing_client(calls), rows=2, cols=2)

    assert ctx.focus == "" and ctx.focus_report_text == ""
    assert "Focus Report" not in ctx.combined_text
    # Only the two digest calls, with the unmodified system prompt.
    assert len(calls) == 2
    assert all(kw["system"] == DIGEST_SYSTEM_PROMPT for kw in calls)


def test_pipeline_focus_report_failure_ships_digests(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    path = _make_pdf(pymupdf, tmp_path / "set.pdf", pages=2)

    def responder(kw):
        if kw["system"] == FOCUS_REPORT_SYSTEM_PROMPT:
            return FakeMessage(content=[], stop_reason="max_tokens")  # empty -> error
        return FakeMessage(content=[FakeTextBlock(text="digest body")])

    class _C:
        def __init__(self):
            class _M:
                def create(_s, **kw):
                    return responder(kw)

            self.messages = _M()

    ctx = extract_drawing_context(
        [path], client=_C(), rows=2, cols=2, focus=ROOMS_FOCUS
    )

    assert ctx.focus == ROOMS_FOCUS
    assert ctx.focus_report_text == ""                  # report failed
    assert "## Focus Report" not in ctx.combined_text   # no empty section
    assert "digest body" in ctx.combined_text           # digests still shipped
    assert any("Focus report" in e for e in ctx.errors)  # failure surfaced
