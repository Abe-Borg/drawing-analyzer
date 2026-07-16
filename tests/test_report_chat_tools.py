"""Headless-Chromium tests for the report chat's client-side tools + the
highlight-to-ask flow (companion to ``test_report_browser_security.py``).

These behaviours cannot be proven by a DOM emulator: the client tool-execution
loop, real ``getSelection`` capture, and the display-vs-API-content decoupling
only exist in a real browser driving the actual report. Hermetic — the report is
built in-process, loaded over ``file://``, and the Anthropic ``fetch`` is stubbed
with a queue of canned SSE streams (no network, no key). Skips cleanly when
Playwright or its browser binary is unavailable.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from drawing_analyzer import html_report as hr  # noqa: E402
from drawing_analyzer.models import Anchor, Finding, Verification  # noqa: E402
from tests.fixtures.fake_context import FakeContext as _Ctx  # noqa: E402
from tests.fixtures.fake_context import FakeRef as _Ref  # noqa: E402
from tests.fixtures.fake_context import FakeSheet as _Sheet  # noqa: E402

pytestmark = pytest.mark.browser

NOW = datetime(2026, 7, 14, 8, 0)
KEY = "sk-ant-fake-not-real"


def _launch(p):
    try:
        return p.chromium.launch(headless=True)
    except PlaywrightError:
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        for pat in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-linux64/chrome"):
            hits = sorted(glob.glob(os.path.join(root, pat)))
            if hits:
                return p.chromium.launch(headless=True, executable_path=hits[-1])
        raise


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = _launch(p)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"headless Chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.add_init_script("window.__pwned = false;")
    yield pg
    ctx.close()


def _sse(frames) -> str:
    return "".join(f"data: {json.dumps(fr)}\n\n" for fr in frames)


# A queue-based fetch stub: each fetch records the parsed request body into
# window.__REQ and returns the next SSE string from window.__SSE_QUEUE (falling
# back to a plain end_turn). This lets a single turn span multiple rounds (the
# client tool loop) while we inspect exactly what was sent each round.
_FETCH_STUB = """
(function(){
  window.__REQ = [];
  var enc = new TextEncoder();
  window.fetch = function(url, opts){
    try { window.__REQ.push(JSON.parse(opts.body)); } catch(e){ window.__REQ.push(null); }
    var sse = (window.__SSE_QUEUE && window.__SSE_QUEUE.length)
      ? window.__SSE_QUEUE.shift() : window.__SSE_END;
    var bytes = enc.encode(sse), sent = false;
    var reader = { read: function(){
      if(sent) return Promise.resolve({done:true, value:undefined});
      sent = true;
      // A macrotask delay so `setStreaming(true)` is observable (otherwise the
      // whole turn resolves within one microtask flush and the disabled→enabled
      // transition is never seen by the test harness).
      return new Promise(function(resolve){
        setTimeout(function(){ resolve({done:false, value: bytes}); }, 25);
      });
    }};
    return Promise.resolve({ ok:true, status:200, body:{ getReader:function(){ return reader; } } });
  };
})();
"""


def _text_turn(text: str) -> str:
    return _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
    ])


def _load(page, doc, tmp_path, *, queue=None):
    page.add_init_script(_FETCH_STUB)
    page.add_init_script("window.__SSE_END = " + json.dumps(_text_turn("done.")) + ";")
    page.add_init_script(
        "window.__SSE_QUEUE = " + json.dumps(list(queue or [])) + ";"
    )
    f = tmp_path / "report.html"
    f.write_text(doc, encoding="utf-8")
    page.goto(f.as_uri())
    return page


def _finish(page):
    # Streaming disables Send; wait for the whole (possibly multi-round) turn.
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send'); return b && b.disabled; }",
        timeout=5000,
    )
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send'); return b && !b.disabled; }",
        timeout=10000,
    )
    page.wait_for_timeout(120)


def _ask(page, question):
    page.click("#da-chat-fab")
    page.fill("#da-chat-input", question)
    page.click("#da-chat-send")
    _finish(page)


def _findings_ctx():
    f = Finding(
        sheet_id="M-501", source_name="a.pdf", page_index=0,
        category="conflict", severity="high",
        text="HIGHSEVMARKER VAV-3 has no clearance shown", source_quote="VAV-3",
        anchor=Anchor(status="EXACT", rect_pdf=[0, 0, 1, 1]),
        verification=Verification(status="VERIFIED", evidence_png=""),
    )
    ctx = _Ctx(
        sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="**Conflicts**\n- VAV-3 clearance")],
        combined_text="# Digest\n\nVAV-3 clearance note.",
        total_input_tokens=100, total_output_tokens=40,
    )
    ctx.findings = [f]
    return ctx


# --------------------------------------------------------------------------- #
# 1. Client tool-execution loop: tool_use → local execution → tool_result →
#    a second round that answers in text. Two tools in one turn, both answered.
# --------------------------------------------------------------------------- #


def test_client_tool_loop_executes_and_answers_all_ids(page, tmp_path):
    round1 = _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "tu_1", "name": "query_findings", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"severity":"high"}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "tu_2", "name": "calculate", "input": {}}},
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "input_json_delta", "partial_json": '{"expression":"1234567890123+1"}'}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ])
    round2 = _text_turn("One high-severity finding; the sum is 1234567890124.")

    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path, queue=[round1, round2])
    _ask(page, "check findings and math")

    reqs = page.evaluate("window.__REQ")
    assert len(reqs) == 2, "the loop should make a second request after tool_use"

    # Round 1 offered the six client tools alongside the two server tools.
    tool_names = [t.get("name") for t in reqs[0]["tools"]]
    for name in ("web_search", "web_fetch", "scroll_to_report", "query_findings",
                 "filter_report", "get_report_summary", "highlight_term", "calculate"):
        assert name in tool_names

    # Round 2's last message is a single user turn answering BOTH tool_use ids.
    last = reqs[1]["messages"][-1]
    assert last["role"] == "user"
    results = {b["tool_use_id"]: b for b in last["content"] if b.get("type") == "tool_result"}
    assert set(results) == {"tu_1", "tu_2"}, "every tool_use id must be answered once"
    # query_findings actually read #da-findings and returned the high finding.
    assert "HIGHSEVMARKER" in results["tu_1"]["content"]
    # calculate did EXACT arithmetic — a large representable integer is not
    # rounded away (guards the toPrecision(15) precision fix).
    assert "1234567890124" in results["tu_2"]["content"]
    assert "1234567890120" not in results["tu_2"]["content"]

    # Both client-tool chips resolved to the done state; nothing executed.
    assert page.eval_on_selector_all(".da-tool.da-tool-done", "els => els.length") >= 2
    assert page.evaluate("window.__pwned") is False


def test_report_driving_tools_execute(page, tmp_path):
    # filter_report drives the report's own search/chips, get_report_summary
    # reads #da-summary + counts findings, highlight_term paints matches — all in
    # one tool round, each answered with a sensible tool_result.
    round1 = _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "f1", "name": "filter_report", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"category":"conflict"}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1,
         "content_block": {"type": "tool_use", "id": "s1", "name": "get_report_summary", "input": {}}},
        {"type": "content_block_stop", "index": 1},
        {"type": "content_block_start", "index": 2,
         "content_block": {"type": "tool_use", "id": "h1", "name": "highlight_term", "input": {}}},
        {"type": "content_block_delta", "index": 2,
         "delta": {"type": "input_json_delta", "partial_json": '{"term":"VAV-3"}'}},
        {"type": "content_block_stop", "index": 2},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ])
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path, queue=[round1, _text_turn("did it.")])
    _ask(page, "focus conflicts, summarize, and highlight VAV-3")

    reqs = page.evaluate("window.__REQ")
    results = {b["tool_use_id"]: b["content"]
               for b in reqs[1]["messages"][-1]["content"] if b.get("type") == "tool_result"}
    assert "Applied filter" in results["f1"]
    summary = json.loads(results["s1"])
    assert summary["findings_total"] == 1 and "qc_status" in summary
    assert "Highlighted" in results["h1"]
    # The term highlight was actually painted on the page.
    assert page.evaluate("!!(window.CSS && CSS.highlights && CSS.highlights.has('da-term'))")
    assert page.evaluate("window.__pwned") is False


def _one_tool_round(tool_id, name, input_json):
    return _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": input_json}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ])


def test_filter_report_search_reports_post_debounce_count(page, tmp_path):
    # A search filter debounces the report's apply() ~90ms; filter_report must
    # return the UPDATED count, not the stale pre-filter one. A nonsense term
    # filters everything out, so a correct (post-debounce) read says "0 of".
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path,
          queue=[_one_tool_round("ft", "filter_report", '{"search":"zznomatchzz"}'),
                 _text_turn("nothing matched.")])
    _ask(page, "search zznomatchzz")

    reqs = page.evaluate("window.__REQ")
    result = [b["content"] for b in reqs[1]["messages"][-1]["content"]
              if b.get("type") == "tool_result"][0]
    assert "0 of" in result, result


def test_scroll_to_report_reveals_filter_hidden_blocks(page, tmp_path):
    # scroll_to_report to a card the active filter hid must reveal the card AND
    # its inner blocks (not land on a visible-but-empty card), while leaving the
    # filter active elsewhere (a targeted reveal, not a filter reset).
    ctx = _Ctx(
        sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="**Conflicts**\n- VAV-3 clearance conflict")],
        synthesis_text="**Cross-sheet / cross-discipline conflicts**\n- overview conflict item",
        combined_text="# Digest\n\nx",
    )
    doc = hr.build_html_report(
        ctx, source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    if 'id="overview"' not in doc or 'id="sheet-1"' not in doc:
        pytest.skip("expected overview + sheet-1 cards in this report")
    _load(page, doc, tmp_path,
          queue=[_one_tool_round("flt", "filter_report", '{"category":"coordination"}'),
                 _one_tool_round("scr", "scroll_to_report", '{"target":"sheet-1"}'),
                 _text_turn("jumped there.")])
    _ask(page, "filter to coordination then jump to sheet 1")

    # sheet-1 and its blocks are visible again...
    assert page.eval_on_selector("#sheet-1", "el => el.classList.contains('hidden')") is False
    assert page.eval_on_selector_all("#sheet-1 .block.hidden", "els => els.length") == 0
    # ...but the coordination filter is still active (overview stays hidden).
    assert page.eval_on_selector("#overview", "el => el.classList.contains('hidden')") is True
    assert page.evaluate("window.__pwned") is False


def test_tool_loop_forces_text_close_when_budget_exhausted(page, tmp_path):
    # If the model keeps calling a tool forever, the loop must eventually re-ask
    # with tools withdrawn (tool_choice:none) so the run ends in text, never on a
    # dangling tool_use. We feed an endless calculate loop and assert the final
    # request carried tool_choice:none.
    calc_round = _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "tu_x", "name": "calculate", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"expression":"1+1"}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
    ])
    # More rounds than MAX_TOOL_ROUNDS; __SSE_END (a text turn) covers the close.
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path, queue=[calc_round] * 12)
    _ask(page, "loop forever")

    reqs = page.evaluate("window.__REQ")
    # The final request disabled tools so the model had to answer in text.
    assert reqs[-1].get("tool_choice", {}).get("type") == "none"
    assert "tools" not in reqs[-1]
    assert page.evaluate("window.__pwned") is False


# --------------------------------------------------------------------------- #
# 2. Highlight → ask: a report selection becomes an excerpt sent to the model,
#    while the transcript shows only what the user typed.
# --------------------------------------------------------------------------- #


def test_selection_becomes_excerpt_in_request_not_transcript(page, tmp_path):
    ctx = _Ctx(
        sheets=[_Sheet(_Ref("a.pdf", 0, 1),
                       text="**Scope**\n- UNIQUEPHRASE alpha bravo charlie delta")],
        combined_text="# Digest\n\nnothing special",
    )
    doc = hr.build_html_report(
        ctx, source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path)

    # Select the report element carrying our marker, then fire a real mouseup.
    selected = page.evaluate(
        """() => {
          var el = Array.from(document.querySelectorAll('main.content li, main.content p'))
            .find(n => n.textContent.indexOf('UNIQUEPHRASE') !== -1);
          if(!el) return false;
          var r = document.createRange(); r.selectNodeContents(el);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          document.querySelector('main.content').dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
          return true;
        }"""
    )
    assert selected, "expected a report element containing the marker"

    page.wait_for_selector("#da-sel-pop", timeout=3000)
    page.click("#da-sel-pop")
    page.wait_for_selector("#da-sel-chip", timeout=3000)   # excerpt chip above compose
    assert page.evaluate("document.getElementById('da-chat-panel').hidden") is False

    page.fill("#da-chat-input", "explain this")
    page.click("#da-chat-send")
    _finish(page)

    # The API request embedded the excerpt (fenced), not just the typed question.
    reqs = page.evaluate("window.__REQ")
    sent = reqs[0]["messages"][-1]["content"]
    assert isinstance(sent, str)
    assert "<excerpt>" in sent and "UNIQUEPHRASE" in sent and "explain this" in sent

    # The transcript bubble shows the typed question + a disclosure — the raw
    # excerpt is not dumped as the visible question line.
    user_txt = page.eval_on_selector(".da-user", "el => el.textContent")
    assert "explain this" in user_txt
    assert "about selected excerpt" in user_txt

    # Sending clears the pending chip (the excerpt now lives in history).
    assert page.query_selector("#da-sel-chip") is None
    assert page.evaluate("window.__pwned") is False


# --------------------------------------------------------------------------- #
# Starter prompts: run-tailored chips render, and clicking one sends that exact
# question (the same path as typing it) and clears the chip row.
# --------------------------------------------------------------------------- #


def test_starter_chip_click_sends_that_question_and_hides_the_row(page, tmp_path):
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path, queue=[_text_turn("answered.")])
    page.click("#da-chat-fab")

    # Chips rendered from the inert #da-starters block; at least one, at most five.
    page.wait_for_selector(".da-starter", timeout=3000)
    chips = page.eval_on_selector_all(".da-starter", "els => els.map(e => e.textContent)")
    assert 1 <= len(chips) <= 5
    # The high-severity conflict on M-501 drives the top chip — a real sheet id.
    assert any("M-501" in c for c in chips)

    first = chips[0]
    page.click(".da-starter >> nth=0")
    _finish(page)

    # Clicking sent the chip's text verbatim as the user turn (no excerpt wrapper).
    reqs = page.evaluate("window.__REQ")
    sent = reqs[0]["messages"][-1]["content"]
    assert sent == first
    # The visible user bubble shows it, and the chip row is hidden for the thread.
    assert first in page.eval_on_selector(".da-user", "el => el.textContent")
    assert page.evaluate(
        "document.getElementById('da-starters-row').style.display"
    ) == "none"
    assert page.evaluate("window.__pwned") is False


def test_new_chat_restores_the_starter_chips(page, tmp_path):
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path, queue=[_text_turn("answered.")])
    page.click("#da-chat-fab")
    page.wait_for_selector(".da-starter", timeout=3000)

    page.click(".da-starter >> nth=0")
    _finish(page)
    assert page.evaluate(
        "document.getElementById('da-starters-row').style.display"
    ) == "none"

    page.click("#da-chat-clear")   # "New chat"
    assert page.evaluate(
        "document.getElementById('da-starters-row').style.display"
    ) == ""
    assert page.eval_on_selector_all(".da-starter", "els => els.length") >= 1
