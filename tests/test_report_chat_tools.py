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
import pathlib
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


def _sent_text(message):
    """The text of a sent message, whichever container shape it arrived in.

    The rolling history cache breakpoint normalizes the *last* user turn to a
    block array on the way out (a plain string cannot carry ``cache_control``),
    so a request's final message is blocks while earlier ones stay strings.
    These assertions are about the text that reached the model, not the box it
    travelled in.
    """
    content = message["content"]
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if b.get("type") == "text")


def _cache_marked(messages):
    """Every (message index, block index) in `messages` carrying a cache_control."""
    return [
        (i, j)
        for i, m in enumerate(messages)
        if isinstance(m.get("content"), list)
        for j, b in enumerate(m["content"])
        if isinstance(b, dict) and b.get("cache_control")
    ]


def _text_turn(text: str) -> str:
    return _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": text}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
    ])


# Latches "a turn started" the instant the Send button is disabled. setStreaming()
# assigns `.disabled`, which reflects to the content attribute, so a MutationObserver
# on that attribute fires as a microtask right after the click handler — well before
# Playwright's next poll, and regardless of how fast the stubbed turn then completes.
_TURN_LATCH = """
(function(){
  window.__TURN_STARTED = false;
  function install(){
    var b = document.getElementById('da-chat-send');
    if(!b) return;
    new MutationObserver(function(){
      if(b.disabled) window.__TURN_STARTED = true;
    }).observe(b, {attributes: true, attributeFilter: ['disabled']});
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', install);
  } else { install(); }
})();
"""


def _load(page, doc, tmp_path, *, queue=None):
    page.add_init_script(_FETCH_STUB)
    page.add_init_script(_TURN_LATCH)
    page.add_init_script("window.__SSE_END = " + json.dumps(_text_turn("done.")) + ";")
    page.add_init_script(
        "window.__SSE_QUEUE = " + json.dumps(list(queue or [])) + ";"
    )
    f = tmp_path / "report.html"
    f.write_text(doc, encoding="utf-8")
    page.goto(f.as_uri())
    return page


def _finish(page):
    # Streaming disables Send, and setStreaming(false) runs exactly once when the
    # whole (possibly multi-round) turn settles — so "disabled then enabled" is the
    # right shape. But "disabled" is TRANSIENT: with a stubbed fetch the entire turn
    # can start and finish between two polls of wait_for_function, and waiting to
    # *observe* it flakes. __TURN_STARTED latches on the first disable via a
    # MutationObserver (installed at load, before any turn), so the start signal
    # survives however fast the turn completes.
    page.wait_for_function("() => window.__TURN_STARTED === true", timeout=5000)
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send'); return b && !b.disabled; }",
        timeout=10000,
    )
    page.wait_for_timeout(120)
    # Re-arm for the next turn. Every turn in these tests is followed by exactly
    # one _finish, so clearing here keeps the flag per-turn without every call
    # site having to snapshot a counter first.
    page.evaluate("() => { window.__TURN_STARTED = false; }")


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
    # Tools stay in the payload: tool definitions render at prompt position 0, so
    # dropping them would invalidate the entire cached prefix — the report block
    # included — for this request. tool_choice:none is what forces the text close,
    # and it invalidates only the messages tier.
    assert reqs[-1].get("tools"), "tool definitions must survive the forced close"
    assert reqs[-1]["tools"] == reqs[0]["tools"], "tool list must be byte-stable"
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
    sent = _sent_text(reqs[0]["messages"][-1])
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
    assert _sent_text(reqs[0]["messages"][-1]) == first
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


# --------------------------------------------------------------------------- #
# Panel resize: every edge and corner grip drags its own edge(s) while the
# opposite edge stays pinned — all eight directions, not just the original
# top / left / top-left three.
# --------------------------------------------------------------------------- #

# handle class -> (drag dx, dy) and the per-edge shift it must produce. Any edge
# not named must stay put. Every drag pushes the grip OUTWARD so the panel only
# grows: that keeps each gesture clear of the viewport margins and the min-size
# floor, so the pinned edges hold exactly.
_RESIZE_CASES = [
    ("da-rz-r",  (60, 0),    {"right": 60}),
    ("da-rz-l",  (-60, 0),   {"left": -60}),
    ("da-rz-t",  (0, -60),   {"top": -60}),
    ("da-rz-b",  (0, 60),    {"bottom": 60}),
    ("da-rz-tl", (-60, -60), {"left": -60, "top": -60}),
    ("da-rz-tr", (60, -60),  {"right": 60, "top": -60}),
    ("da-rz-bl", (-60, 60),  {"left": -60, "bottom": 60}),
    ("da-rz-br", (60, 60),   {"right": 60, "bottom": 60}),
]

# Park the panel mid-viewport with slack on every side, defeating the CSS
# floor/ceiling exactly as enterCustom() does, so each grip has room to grow.
_BASELINE_GEOM = """
(function(){
  var p = document.getElementById('da-chat-panel');
  p.style.left='485px'; p.style.top='150px';
  p.style.width='430px'; p.style.height='460px';
  p.style.right='auto'; p.style.bottom='auto';
  p.style.minHeight='0px'; p.style.maxWidth='none';
})();
"""


def _panel_rect(page):
    return page.evaluate(
        "() => { var r = document.getElementById('da-chat-panel').getBoundingClientRect();"
        " return {left:r.left, top:r.top, right:r.right, bottom:r.bottom}; }"
    )


def test_resize_grips_cover_all_eight_edges(page, tmp_path):
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    page.set_viewport_size({"width": 1400, "height": 1000})
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)

    for cls, (dx, dy), expected in _RESIZE_CASES:
        page.evaluate(_BASELINE_GEOM)
        before = _panel_rect(page)
        box = page.locator("." + cls).bounding_box()
        assert box, cls + " grip should be laid out and grabbable"
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + dx, cy + dy, steps=15)  # cross the 4px drag threshold
        page.mouse.up()
        after = _panel_rect(page)
        for edge in ("left", "top", "right", "bottom"):
            want = expected.get(edge, 0)
            got = after[edge] - before[edge]
            assert abs(got - want) <= 10, (
                cls + ": " + edge + " edge moved " + str(round(got, 1))
                + "px, expected " + str(want) + "px (pinned edges must not move)"
            )


# --------------------------------------------------------------------------- #
# Expandable ask box: it grows with what you type, the ▲ toggle and the grip
# drag pin a height the reader picked (and it survives a reload), and the cap
# never lets the box swallow the transcript it shares the panel with.
# --------------------------------------------------------------------------- #


def _open_panel(page, tmp_path):
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    page.set_viewport_size({"width": 1400, "height": 1000})
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)


def _box_h(page):
    return page.evaluate(
        "() => document.getElementById('da-chat-input').getBoundingClientRect().height"
    )


def _row_h(page, el_id):
    return page.evaluate(
        "id => document.getElementById(id).getBoundingClientRect().height", el_id
    )


def _drag_grip(page, dy):
    box = page.locator("#da-compose-grip").bounding_box()
    assert box, "the compose grip should be laid out and grabbable"
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx, cy + dy, steps=12)   # cross the 3px drag threshold
    page.mouse.up()


def test_ask_box_grows_with_typed_text_and_snaps_back(page, tmp_path):
    _open_panel(page, tmp_path)
    start = _box_h(page)

    page.fill("#da-chat-input", "\n".join("line %d" % i for i in range(8)))
    grown = _box_h(page)
    assert grown > start + 40, (
        "the box should grow with the text (%.0f -> %.0f)" % (start, grown))

    # Auto-grow is symmetric: emptying it returns to the two-row default.
    page.fill("#da-chat-input", "back to one line")
    assert abs(_box_h(page) - start) <= 1


def test_expand_toggle_grows_the_box_then_hands_it_back(page, tmp_path):
    _open_panel(page, tmp_path)
    start = _box_h(page)

    page.click("#da-chat-expand")
    tall = _box_h(page)
    assert tall > start + 100, "the toggle should jump the box to its cap"
    assert page.get_attribute("#da-chat-expand", "aria-expanded") == "true"
    assert "Shrink" in (page.get_attribute("#da-chat-expand", "aria-label") or "")

    # Expanded is a PIN: typing no longer resizes it.
    page.fill("#da-chat-input", "one line")
    assert abs(_box_h(page) - tall) <= 1

    page.click("#da-chat-expand")
    assert page.get_attribute("#da-chat-expand", "aria-expanded") == "false"
    assert abs(_box_h(page) - start) <= 2, "collapsing hands the box back to auto-grow"


@pytest.mark.parametrize("embed_key", [True, False])
@pytest.mark.parametrize("viewport", [(1400, 1000), (1200, 620), (1000, 520)])
def test_expanded_box_never_swallows_the_transcript(page, tmp_path, embed_key, viewport):
    # The panel is a flex column whose header / key form / foot do not shrink,
    # and it clips its own overflow — so a cap taken from a constant pushes the
    # footer clean out of the panel as soon as the key form is on screen or the
    # window is short. Both are covered here.
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW,
        api_key=(KEY if embed_key else None), embed_api_key=embed_key,
    )
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)
    page.click("#da-chat-expand")

    geom = page.evaluate(
        """() => {
          var r = function(id){ return document.getElementById(id).getBoundingClientRect(); };
          return {panel: r('da-chat-panel'), msgs: r('da-chat-msgs'), key: r('da-chat-key'),
                  foot: document.querySelector('.da-chat-foot').getBoundingClientRect()};
        }"""
    )
    assert geom["msgs"]["height"] >= 80, "the transcript must keep a readable slice"
    # The last two rows staying inside proves nothing was pushed out of the clip.
    assert geom["foot"]["bottom"] <= geom["panel"]["bottom"] + 1
    assert geom["key"]["bottom"] <= geom["panel"]["bottom"] + 1


def test_a_fixed_row_growing_reclamps_an_already_expanded_box(page, tmp_path):
    # The cap is measured from the fixed rows, so it goes stale the moment one of
    # them changes height on its own — and the box was already clamped against
    # the old measurement. The key row is the one that moves at runtime: the
    # compact "key set" line, the taller entry form, and a status message of one
    # to three lines are all the same row. Forget key swaps all three at once;
    # a 401 rejection takes the identical path (forgetKey + revealKeyForm).
    doc = hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=None, embed_api_key=False
    )
    page.set_viewport_size({"width": 1200, "height": 640})
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)
    page.fill("#da-chat-key-input", KEY)
    page.click("#da-chat-key-save")

    # Reload into the resting state: a key is held, so the row is the compact
    # "key set" line with no status under it — the smallest it ever is.
    page.reload()
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-key-set", state="visible", timeout=3000)
    page.click("#da-chat-expand")
    expanded, key_before = _box_h(page), _row_h(page, "da-chat-key")

    page.click("#da-chat-forget")
    page.wait_for_selector("#da-chat-key-form", state="visible", timeout=3000)

    grew = _row_h(page, "da-chat-key") - key_before
    assert grew > 0, "the entry form plus its status is taller than the key-set line"
    geom = page.evaluate(
        """() => {
          var r = function(id){ return document.getElementById(id).getBoundingClientRect(); };
          return {panel: r('da-chat-panel'), msgs: r('da-chat-msgs'), key: r('da-chat-key'),
                  foot: document.querySelector('.da-chat-foot').getBoundingClientRect()};
        }"""
    )
    assert abs((expanded - _box_h(page)) - grew) <= 1, (
        "the box must hand back exactly what the key row took (%.0fpx)" % grew)
    assert geom["msgs"]["height"] >= 80, "the transcript floor still holds"
    assert geom["foot"]["bottom"] <= geom["panel"]["bottom"] + 1
    assert geom["key"]["bottom"] <= geom["panel"]["bottom"] + 1


def test_grip_drag_resizes_the_box_and_the_height_survives_a_reload(page, tmp_path):
    _open_panel(page, tmp_path)
    start = _box_h(page)

    _drag_grip(page, -110)                    # drag the grip up = taller
    dragged = _box_h(page)
    assert dragged > start + 80, (
        "dragging the grip up should grow the box (%.0f -> %.0f)" % (start, dragged))

    page.reload()
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)
    assert abs(_box_h(page) - dragged) <= 2, "the dragged height should be remembered"

    # Double-clicking the grip is the reset — back to auto-grow, and it stays
    # reset across a reload (the stored height is dropped, not just ignored).
    page.dblclick("#da-compose-grip")
    assert abs(_box_h(page) - start) <= 2
    page.reload()
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)
    assert abs(_box_h(page) - start) <= 2


def test_sending_snaps_the_grown_box_back_to_its_default(page, tmp_path):
    _open_panel(page, tmp_path)
    start = _box_h(page)
    page.fill("#da-chat-input", "\n".join("line %d" % i for i in range(8)))
    assert _box_h(page) > start + 40

    page.click("#da-chat-send")
    _finish(page)
    assert abs(_box_h(page) - start) <= 1, "an emptied box returns to two rows"


# --------------------------------------------------------------------------- #
# Transcript persistence: the conversation auto-saves per report, replays
# faithfully, and round-trips through a JSON file. Verified in a real browser
# because localStorage, blob downloads, and the file picker only exist there.
# --------------------------------------------------------------------------- #


def _wait_turn(page, *, expect=None):
    """Wait for a turn to settle.

    ``_finish`` watches the Send button's disabled→enabled flip, which a turn
    that completes inside one poll interval can slip through. This waits for the
    settled state itself instead, so it cannot race a fast canned stream.
    """
    page.wait_for_function(
        "() => { var b = document.getElementById('da-chat-send');"
        " return b && !b.disabled && document.querySelector('.da-user'); }",
        timeout=15000,
    )
    if expect:
        page.wait_for_function(
            "t => document.getElementById('da-chat-msgs').textContent.indexOf(t) !== -1",
            arg=expect, timeout=10000,
        )
    page.wait_for_timeout(150)


def _ask_and_settle(page, question, *, expect=None):
    page.click("#da-chat-fab")
    page.fill("#da-chat-input", question)
    page.click("#da-chat-send")
    _wait_turn(page, expect=expect)


def _stored(page):
    """The auto-saved transcript for the loaded report, or None."""
    raw = page.evaluate(
        """() => {
          for (var i = 0; i < localStorage.length; i++) {
            var k = localStorage.key(i);
            if (k.indexOf('da-chat-tx-') === 0) return localStorage.getItem(k);
          }
          return null;
        }"""
    )
    return json.loads(raw) if raw else None


def _chat_doc():
    return hr.build_html_report(
        _findings_ctx(), source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )


def test_conversation_survives_a_reload(page, tmp_path):
    # The whole point of the feature: a refresh used to destroy the thread.
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("VAV-3 has no clearance shown.")])
    _ask_and_settle(page, "what are the conflicts?")

    saved = _stored(page)
    assert saved is not None
    assert saved["kind"] == "drawing_analyzer_chat_transcript"
    assert saved["schema_version"] == 1
    # The stored messages are API-clean: a stray display key would be rejected
    # on the next request, so it must never ride inside the message.
    for turn in saved["turns"]:
        assert set(turn["message"]) == {"role", "content"}
    assert saved["turns"][0]["display"]["text"] == "what are the conflicts?"

    page.reload()
    page.click("#da-chat-fab")
    assert "what are the conflicts?" in page.eval_on_selector(".da-user", "el => el.textContent")
    assert "VAV-3 has no clearance shown." in page.eval_on_selector(".da-ai", "el => el.textContent")
    assert "Restored your previous conversation" in page.eval_on_selector(
        "#da-chat-msgs", "el => el.textContent")
    # Replay is pure rendering — nothing was re-sent to the API.
    assert page.evaluate("window.__REQ.length") == 0
    # The starter chips gave way to the restored thread.
    assert page.eval_on_selector("#da-starters-row", "el => el.style.display") == "none"

    # ...and the restored history is genuinely resumable.
    page.fill("#da-chat-input", "and the second one?")
    page.click("#da-chat-send")
    _wait_turn(page)
    sent = page.evaluate("window.__REQ")[0]["messages"]
    assert sent[0]["content"] == "what are the conflicts?"
    assert sent[1]["role"] == "assistant"
    assert _sent_text(sent[-1]) == "and the second one?"
    assert page.evaluate("window.__pwned") is False


def test_new_chat_clears_the_stored_transcript(page, tmp_path):
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask_and_settle(page, "a question")
    assert _stored(page) is not None

    page.click("#da-chat-clear")           # "New chat" is the eraser
    assert _stored(page) is None

    page.reload()
    page.click("#da-chat-fab")
    assert page.eval_on_selector_all(".da-user, .da-ai", "els => els.length") == 0
    page.wait_for_selector(".da-starter", timeout=3000)   # chips are back


def test_replayed_excerpt_keeps_display_and_api_content_apart(page, tmp_path):
    # The excerpt flow deliberately shows less than it sends; persistence must
    # not collapse the two into one.
    ctx = _Ctx(
        sheets=[_Sheet(_Ref("a.pdf", 0, 1),
                       text="**Scope**\n- UNIQUEPHRASE alpha bravo charlie delta")],
        combined_text="# Digest\n\nnothing special",
    )
    doc = hr.build_html_report(
        ctx, source_names=["a.pdf"], now=NOW, api_key=KEY, embed_api_key=True
    )
    _load(page, doc, tmp_path)
    page.evaluate(
        """() => {
          var el = Array.from(document.querySelectorAll('main.content li, main.content p'))
            .find(n => n.textContent.indexOf('UNIQUEPHRASE') !== -1);
          var r = document.createRange(); r.selectNodeContents(el);
          var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
          document.querySelector('main.content').dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
        }"""
    )
    page.wait_for_selector("#da-sel-pop", timeout=3000)
    page.click("#da-sel-pop")
    page.wait_for_selector("#da-sel-chip", timeout=3000)
    page.fill("#da-chat-input", "explain this")
    page.click("#da-chat-send")
    _wait_turn(page)

    page.reload()
    page.click("#da-chat-fab")
    user_txt = page.eval_on_selector(".da-user", "el => el.textContent")
    assert "explain this" in user_txt
    assert "about selected excerpt" in user_txt
    assert "UNIQUEPHRASE" in user_txt          # inside the disclosure
    assert "<excerpt>" not in user_txt          # ...but never as the question line

    # The API side kept the full wrapped prompt.
    page.fill("#da-chat-input", "and now?")
    page.click("#da-chat-send")
    _wait_turn(page)
    first = page.evaluate("window.__REQ")[0]["messages"][0]["content"]
    assert "<excerpt>" in first and "UNIQUEPHRASE" in first


def test_replay_does_not_rerun_report_driving_tools(page, tmp_path):
    # A recorded filter_report/highlight_term must render as a settled chip, not
    # execute — re-running a past conversation's calls would silently hijack the
    # page the reader just opened.
    _load(page, _chat_doc(), tmp_path,
          queue=[_one_tool_round("ft", "filter_report", '{"search":"zznomatchzz"}'),
                 _text_turn("nothing matched.")])
    _ask_and_settle(page, "search zznomatchzz")
    assert page.eval_on_selector("#search", "el => el.value") == "zznomatchzz"

    page.reload()
    page.click("#da-chat-fab")
    # The report is untouched by the replay...
    assert page.eval_on_selector("#search", "el => el.value") == ""
    assert page.evaluate("window.__REQ.length") == 0
    # ...but the tool chip still shows the call and its recorded outcome.
    chips = page.eval_on_selector_all(".da-tool", "els => els.map(e => e.textContent)")
    assert any("zznomatchzz" in c for c in chips), chips
    assert page.eval_on_selector_all(".da-tool-done", "els => els.length") == 1
    assert page.eval_on_selector_all(".da-tool-err", "els => els.length") == 0


def test_replayed_tool_chip_shows_a_recorded_failure(page, tmp_path):
    _load(page, _chat_doc(), tmp_path,
          queue=[_one_tool_round("bad", "no_such_tool", "{}"), _text_turn("sorry.")])
    _ask_and_settle(page, "call a broken tool")
    page.reload()
    page.click("#da-chat-fab")
    assert page.eval_on_selector_all(".da-tool-err", "els => els.length") == 1


def test_save_json_downloads_a_valid_transcript(page, tmp_path):
    # Forces the download fallback (headless Chromium exposes showSaveFilePicker
    # but cannot show one), which is also the path every non-Chromium reader takes.
    page.add_init_script("window.showSaveFilePicker = undefined;")
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask_and_settle(page, "a question")

    with page.expect_download(timeout=5000) as dl:
        page.click("#da-chat-save")
    download = dl.value
    assert download.suggested_filename == "chat_history.json"
    payload = json.loads(pathlib.Path(download.path()).read_text(encoding="utf-8"))
    assert payload["kind"] == "drawing_analyzer_chat_transcript"
    assert payload["schema_version"] == 1
    assert payload["report"]["report_id"] == _stored(page)["report"]["report_id"]
    assert payload["turns"][0]["display"]["text"] == "a question"
    assert set(payload["turns"][0]["message"]) == {"role", "content"}


def test_save_json_uses_the_file_picker_when_the_browser_offers_one(page, tmp_path):
    # The picker is what lets the reader drop the file straight into the export
    # folder beside report.html; a plain download can only reach Downloads.
    page.add_init_script(
        """
        window.__PICKED = null;
        window.showSaveFilePicker = function(opts){
          window.__PICKED = opts;
          return Promise.resolve({createWritable: function(){
            return Promise.resolve({
              write: function(t){ window.__WROTE = t; },
              close: function(){}
            });
          }});
        };
        """
    )
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask_and_settle(page, "a question")
    page.click("#da-chat-save")
    page.wait_for_function("() => window.__WROTE", timeout=5000)

    assert page.evaluate("window.__PICKED.suggestedName") == "chat_history.json"
    payload = json.loads(page.evaluate("window.__WROTE"))
    assert payload["kind"] == "drawing_analyzer_chat_transcript"
    assert payload["turns"][0]["display"]["text"] == "a question"


def test_load_json_restores_and_resumes(page, tmp_path):
    page.on("dialog", lambda d: d.accept())
    doc = _chat_doc()
    _load(page, doc, tmp_path, queue=[_text_turn("answered.")])
    report_id = json.loads(
        doc[doc.index(">", doc.index('id="da-chat-config"')) + 1:
            doc.index("</script>", doc.index('id="da-chat-config"'))]
    )["reportId"]

    transcript = {
        "kind": "drawing_analyzer_chat_transcript",
        "schema_version": 1,
        "report": {"report_id": report_id, "title": "t", "generated": "g",
                   "sources": ["a.pdf"], "model": "m"},
        "saved_at": "2026-07-14T08:00:00.000Z",
        "truncated": False,
        "turns": [
            {"message": {"role": "user", "content": "earlier question"},
             "display": {"text": "earlier question", "excerpt": ""}},
            {"message": {"role": "assistant",
                         "content": [{"type": "text", "text": "earlier **answer**"}]},
             "display": {"notes": []}},
        ],
    }
    path = tmp_path / "chat_history.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")

    page.click("#da-chat-fab")
    page.set_input_files("#da-chat-load-input", str(path))
    page.wait_for_selector(".da-user", timeout=5000)
    assert "earlier question" in page.eval_on_selector(".da-user", "el => el.textContent")
    # Markdown in a loaded answer renders through the same safe-DOM path.
    assert page.eval_on_selector_all(".da-ai strong", "els => els.length") == 1

    page.fill("#da-chat-input", "follow up")
    page.click("#da-chat-send")
    _wait_turn(page)
    sent = page.evaluate("window.__REQ")[0]["messages"]
    assert sent[0]["content"] == "earlier question"
    assert _sent_text(sent[-1]) == "follow up"


def test_load_rejects_a_file_that_is_not_a_transcript(page, tmp_path):
    page.on("dialog", lambda d: d.accept())
    _load(page, _chat_doc(), tmp_path)
    page.click("#da-chat-fab")

    bad = tmp_path / "not_a_transcript.json"
    bad.write_text(json.dumps({"kind": "something_else"}), encoding="utf-8")
    page.set_input_files("#da-chat-load-input", str(bad))
    page.wait_for_selector(".da-err", timeout=5000)
    assert "not a Drawing Analyzer chat transcript" in page.eval_on_selector(
        ".da-err", "el => el.textContent")
    assert page.eval_on_selector_all(".da-user, .da-ai", "els => els.length") == 0
    assert _stored(page) is None


def test_load_drops_an_unanswered_trailing_turn(page, tmp_path):
    # A transcript ending on a user turn would make the next question the second
    # consecutive user turn — a 400 from the API. It must be trimmed on load.
    page.on("dialog", lambda d: d.accept())
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("ok.")])
    transcript = {
        "kind": "drawing_analyzer_chat_transcript", "schema_version": 1,
        "report": {"report_id": "deadbeefdeadbeef"}, "saved_at": "x", "truncated": False,
        "turns": [
            {"message": {"role": "user", "content": "answered one"},
             "display": {"text": "answered one", "excerpt": ""}},
            {"message": {"role": "assistant", "content": [{"type": "text", "text": "yes"}]},
             "display": {"notes": []}},
            {"message": {"role": "user", "content": "never answered"},
             "display": {"text": "never answered", "excerpt": ""}},
        ],
    }
    path = tmp_path / "trailing.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")
    page.click("#da-chat-fab")
    page.set_input_files("#da-chat-load-input", str(path))
    page.wait_for_selector(".da-user", timeout=5000)

    page.fill("#da-chat-input", "next")
    page.click("#da-chat-send")
    _wait_turn(page)
    roles = [m["role"] for m in page.evaluate("window.__REQ")[0]["messages"]]
    assert roles == ["user", "assistant", "user"]     # strict alternation preserved


def test_storage_failure_degrades_without_breaking_the_turn(page, tmp_path):
    # Quota exhausted / storage disabled must never cost the reader an answer.
    page.add_init_script(
        "window.addEventListener('DOMContentLoaded', function(){"
        " localStorage.setItem = function(){ var e = new Error('quota');"
        " e.name = 'QuotaExceededError'; throw e; }; });"
    )
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("still answered.")])
    _ask_and_settle(page, "a question")

    assert errors == []
    assert "still answered." in page.eval_on_selector("#da-chat-msgs", "el => el.textContent")
    assert "too large for your browser" in page.eval_on_selector(
        "#da-chat-msgs", "el => el.textContent")
    # ...and the unload warning comes back on, because now there IS something to lose.
    assert page.evaluate(
        "(() => { var e = new Event('beforeunload', {cancelable:true});"
        " window.dispatchEvent(e); return e.defaultPrevented; })()"
    ) is True


def test_beforeunload_is_silent_once_the_transcript_is_saved(page, tmp_path):
    # With the conversation persisted there is nothing to lose, and a warning on
    # every close just trains readers to click through it.
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask_and_settle(page, "a question")
    assert page.evaluate(
        "(() => { var e = new Event('beforeunload', {cancelable:true});"
        " window.dispatchEvent(e); return e.defaultPrevented; })()"
    ) is False


def test_stopping_mid_tool_loop_leaves_a_resumable_transcript(page, tmp_path):
    # A turn stopped between a tool call and its answer leaves
    # assistant(tool_use) -> user(tool_result) -> nothing. Trimming only the
    # trailing user turn would keep the dangling tool_use, and the next question
    # (a plain user turn, not a tool_result) is a 400 from the API. The whole
    # unfinished exchange has to be rewound.
    page.on("dialog", lambda d: d.accept())
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("first answer.")])
    _ask_and_settle(page, "first question", expect="first answer.")

    transcript = json.loads(page.evaluate(
        """() => {
          for (var i = 0; i < localStorage.length; i++) {
            var k = localStorage.key(i);
            if (k.indexOf('da-chat-tx-') === 0) return localStorage.getItem(k);
          }
        }"""
    ))
    # Splice on the shape a stopped tool loop leaves behind.
    transcript["turns"] += [
        {"message": {"role": "user", "content": "second question"},
         "display": {"text": "second question", "excerpt": ""}},
        {"message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "hung", "name": "calculate",
             "input": {"expression": "1+1"}}]},
         "display": {"notes": ["⏹ Stopped."]}},
        {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "hung", "content": "2"}]}},
    ]
    path = tmp_path / "stopped.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")

    page.set_input_files("#da-chat-load-input", str(path))   # panel already open
    page.wait_for_function(
        "() => document.getElementById('da-chat-msgs').textContent"
        ".indexOf('second question') === -1", timeout=5000,
    )

    page.fill("#da-chat-input", "third question")
    page.click("#da-chat-send")
    _wait_turn(page)
    messages = page.evaluate("window.__REQ")[-1]["messages"]
    # Strict alternation, and no tool_use left waiting for a tool_result.
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert not any(
        isinstance(b, dict) and b.get("type") == "tool_use"
        for m in messages if isinstance(m.get("content"), list)
        for b in m["content"]
    )
    assert _sent_text(messages[-1]) == "third question"


def test_loading_mid_stream_does_not_corrupt_the_loaded_thread(page, tmp_path):
    # Aborting an in-flight turn only makes its promise reject later. If that
    # late cleanup still edits `history`, it pops a turn off the conversation
    # that replaced it — and then saves the damage.
    page.on("dialog", lambda d: d.accept())
    doc = _chat_doc()
    _load(page, doc, tmp_path)
    report_id = json.loads(
        doc[doc.index(">", doc.index('id="da-chat-config"')) + 1:
            doc.index("</script>", doc.index('id="da-chat-config"'))]
    )["reportId"]
    transcript = {
        "kind": "drawing_analyzer_chat_transcript", "schema_version": 1,
        "report": {"report_id": report_id}, "saved_at": "x", "truncated": False,
        "turns": [
            {"message": {"role": "user", "content": "loaded question"},
             "display": {"text": "loaded question", "excerpt": ""}},
            {"message": {"role": "assistant",
                         "content": [{"type": "text", "text": "loaded answer"}]},
             "display": {"notes": []}},
        ],
    }
    path = tmp_path / "loaded.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")

    # A turn that hangs until aborted. The stub must honour opts.signal the way
    # real fetch does — a promise that merely never settles would leave the old
    # turn's cleanup un-run, and the race being tested here lives in that cleanup.
    page.evaluate(
        """() => {
          window.fetch = function(url, opts){
            return new Promise(function(_resolve, reject){
              var sig = opts && opts.signal;
              if(sig) sig.addEventListener('abort', function(){
                var e = new Error('aborted'); e.name = 'AbortError'; reject(e);
              });
            });
          };
        }"""
    )
    page.click("#da-chat-fab")
    page.fill("#da-chat-input", "in-flight question")
    page.click("#da-chat-send")
    page.wait_for_function(
        "() => { var b = document.getElementById('da-chat-send'); return b && b.disabled; }",
        timeout=5000,
    )
    page.set_input_files("#da-chat-load-input", str(path))
    page.wait_for_function(
        "() => document.getElementById('da-chat-msgs').textContent.indexOf('loaded answer') !== -1",
        timeout=5000,
    )
    page.wait_for_timeout(400)   # give the aborted turn's cleanup time to fire

    # The loaded conversation is intact, on screen and in storage.
    assert "loaded question" in page.eval_on_selector("#da-chat-msgs", "el => el.textContent")
    assert "in-flight question" not in page.eval_on_selector(
        "#da-chat-msgs", "el => el.textContent")
    saved = _stored(page)
    assert [t["message"]["role"] for t in saved["turns"]] == ["user", "assistant"]
    assert saved["turns"][0]["display"]["text"] == "loaded question"


# --------------------------------------------------------------------------- #
# 9. Prompt-cache strategy. Caching is a prefix match (tools -> system ->
#    messages), so these assertions guard the two things that make it work: the
#    system blocks must be byte-stable for the life of the page, and the rolling
#    history breakpoint must advance instead of piling up.
# --------------------------------------------------------------------------- #


def test_report_block_uses_one_hour_ttl(page, tmp_path):
    # The report never changes for the life of the page, but a reader pauses well
    # past the default 5-minute TTL between questions — and an expiry re-writes
    # the whole report.
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask(page, "what are the conflicts?")

    system = page.evaluate("window.__REQ")[0]["system"]
    assert system[-1]["text"].startswith("=== FULL REPORT")
    assert system[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    # Exactly one breakpoint in the system tier — the preamble must not carry one.
    assert [b for b in system if b.get("cache_control")] == [system[-1]]


def test_system_blocks_are_byte_stable_across_turns(page, tmp_path):
    # The single most valuable guard on the whole caching strategy: anything
    # interpolated into systemBlocks() that varies per turn (a timestamp, a
    # counter, the question itself) silently invalidates the report block on
    # every request, and nothing else in the suite would notice.
    _load(page, _chat_doc(), tmp_path,
          queue=[_text_turn("first answer."), _text_turn("second answer.")])
    _ask(page, "what are the conflicts?")
    page.fill("#da-chat-input", "and the second one?")
    page.click("#da-chat-send")
    _finish(page)

    reqs = page.evaluate("window.__REQ")
    assert len(reqs) == 2
    assert reqs[0]["system"] == reqs[1]["system"], "systemBlocks() must be byte-stable"
    # Tools render at position 0, ahead of system — a change there invalidates
    # the report block too.
    assert reqs[0]["tools"] == reqs[1]["tools"], "tool list must be byte-stable"


def test_history_breakpoint_rolls_forward(page, tmp_path):
    # One rolling breakpoint, always on the newest user turn. Two would burn the
    # 4-per-request budget; a stationary one would fall outside the API's 20-block
    # lookback window during a tool-heavy turn and silently stop matching.
    _load(page, _chat_doc(), tmp_path,
          queue=[_one_tool_round("q1", "query_findings", '{"severity":"high"}'),
                 _text_turn("one high-severity finding.")])
    _ask(page, "how many high severity findings?")

    reqs = page.evaluate("window.__REQ")
    assert len(reqs) == 2, "expected a tool round then a text close"
    first, second = _cache_marked(reqs[0]["messages"]), _cache_marked(reqs[1]["messages"])
    assert len(first) == 1, first
    assert len(second) == 1, second
    # Round 2 appended the assistant turn + the tool_result turn, so the marker
    # must have moved onto that newer user turn.
    assert second[0][0] > first[0][0], (first, second)
    # And it always lands on the last message, which is always a user turn.
    assert second[0][0] == len(reqs[1]["messages"]) - 1
    assert reqs[1]["messages"][second[0][0]]["role"] == "user"


def test_history_marker_never_reaches_the_saved_transcript(page, tmp_path):
    # `history` is serialized verbatim into the transcript, so the wire-only cache
    # marker must be stamped on a copy — otherwise a transient breakpoint becomes
    # part of a durable, user-savable document.
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask_and_settle(page, "what are the conflicts?")

    saved = _stored(page)
    assert saved is not None
    for turn in saved["turns"]:
        content = turn["message"]["content"]
        if isinstance(content, list):
            assert not any(b.get("cache_control") for b in content), turn
    # The reader's typed question also keeps its plain-string shape on disk.
    assert saved["turns"][0]["message"]["content"] == "what are the conflicts?"


def test_effort_is_sent_and_the_deep_toggle_escalates_it(page, tmp_path):
    _load(page, _chat_doc(), tmp_path,
          queue=[_text_turn("standard."), _text_turn("deep.")])
    _ask(page, "a routine lookup")
    page.check("#da-chat-deep-input")
    page.fill("#da-chat-input", "something much harder")
    page.click("#da-chat-send")
    _finish(page)

    reqs = page.evaluate("window.__REQ")
    assert reqs[0]["output_config"] == {"effort": "medium"}
    assert reqs[1]["output_config"] == {"effort": "high"}
    # Escalating effort must not disturb the cached tools+system prefix.
    assert reqs[0]["system"] == reqs[1]["system"]
    assert reqs[0]["tools"] == reqs[1]["tools"]


def test_effort_omitted_when_the_model_lacks_the_levels(page, tmp_path, monkeypatch):
    # DRAWING_ANALYZER_CHAT_MODEL can point at anything; an unsupported effort
    # level is a 400 that kills the request, so the host gates on the registry.
    monkeypatch.setattr(hr, "CHAT_MODEL_DEFAULT", "some-unregistered-model")
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask(page, "what are the conflicts?")

    assert "output_config" not in page.evaluate("window.__REQ")[0]
    # ...and the toggle that would set it is not offered.
    assert page.eval_on_selector("#da-chat-deep", "el => el.hidden") is True


def test_query_findings_compact_omits_text_and_quote(page, tmp_path):
    _load(page, _chat_doc(), tmp_path,
          queue=[_one_tool_round("qf", "query_findings", '{"compact":true}'),
                 _text_turn("counted.")])
    _ask(page, "how many findings are there?")

    reqs = page.evaluate("window.__REQ")
    payload = [b["content"] for b in reqs[1]["messages"][-1]["content"]
               if b.get("type") == "tool_result"][0]
    rows = json.loads(payload)["findings"]
    assert rows, payload
    for row in rows:
        assert set(row) == {"id", "sheet", "category", "severity", "status"}


def test_server_tool_budgets_are_modest(page, tmp_path):
    # Every server-tool result lands in `history` permanently and is re-sent on
    # every later round and question, so the per-turn budget is a running cost.
    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask(page, "what does the code say?")

    tools = page.evaluate("window.__REQ")[0]["tools"]
    for t in tools:
        if t.get("type", "").startswith(("web_search", "web_fetch")):
            assert t["max_uses"] <= 5, t


def test_usage_readout_reports_cache_activity(page, tmp_path):
    # The widget runs on the reader's key, so nothing reaches RunUsage — this
    # footer is the only place its cost is ever visible.
    stream = _sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 120, "cache_read_input_tokens": 40000,
            "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "answered."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 250}},
    ])
    _load(page, _chat_doc(), tmp_path, queue=[stream])
    _ask(page, "what are the conflicts?")

    assert page.eval_on_selector("#da-chat-usage", "el => el.hidden") is False
    text = page.eval_on_selector("#da-chat-usage", "el => el.textContent")
    assert "40k cached read" in text, text
    assert "0 written" in text, text
    assert "250 out" in text, text
    assert "est. $" in text, text

    # "New chat" owns the counter along with the thread.
    page.click("#da-chat-clear")
    assert page.eval_on_selector("#da-chat-usage", "el => el.hidden") is True


def test_request_asks_for_the_models_full_output_ceiling(page, tmp_path):
    # A truncated answer is a wrong answer the reader buys twice, so the widget
    # never imposes a budget below what the model serves. The number comes from
    # the capability registry via CFG, which is what keeps it correct across a
    # DRAWING_ANALYZER_CHAT_MODEL override.
    from drawing_analyzer.core.api_config import model_capabilities

    _load(page, _chat_doc(), tmp_path, queue=[_text_turn("answered.")])
    _ask(page, "what are the conflicts?")

    ceiling = model_capabilities(hr.CHAT_MODEL_DEFAULT).max_output_tokens
    assert page.evaluate("window.__REQ")[0]["max_tokens"] == ceiling
    assert ceiling == 128_000


def test_context_readout_measures_the_thread_against_the_window(page, tmp_path):
    # Distinct from the cost readout: this is occupancy right now, not spend to
    # date, and the cached leg counts — cached tokens still fill the window, they
    # are only billed cheaper. 120 + 40000 + 8000 prompt + 250 out = 48,370.
    stream = _sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 120, "cache_read_input_tokens": 40000,
            "cache_creation_input_tokens": 8000}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "answered."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 250}},
    ])
    _load(page, _chat_doc(), tmp_path, queue=[stream])

    # Nothing measured yet, so nothing claimed.
    assert page.eval_on_selector("#da-chat-context", "el => el.hidden") is True
    _ask(page, "what are the conflicts?")

    assert page.eval_on_selector("#da-chat-context", "el => el.hidden") is False
    text = page.eval_on_selector("#da-chat-context-text", "el => el.textContent")
    assert "48.4k" in text, text          # 48,370 tokens occupied
    assert "1M" in text, text             # ...of the model's window
    assert "(5%)" in text, text
    assert page.eval_on_selector("#da-chat-context", "el => el.dataset.tier") == "ok"
    width = page.eval_on_selector("#da-chat-context-fill", "el => el.style.width")
    assert width.startswith("4.8"), width

    # "New chat" empties the thread, so it occupies nothing again.
    page.click("#da-chat-clear")
    assert page.eval_on_selector("#da-chat-context", "el => el.hidden") is True


def test_a_window_exhausted_answer_says_so_and_the_note_survives_a_reload(page, tmp_path):
    """The other way an answer gets cut off, and the one the gauge predicts.

    Generated tokens count toward the context window, so a long thread can stop
    mid-sentence having filled it. ``model_context_window_exceeded`` is truthy,
    so before it had a branch of its own it fell past the refusal / max_tokens /
    no-stop-reason arms and the cut-off answer was committed silently — and
    replayed from the transcript looking complete, which is the one thing
    ``turnNote`` exists to prevent.
    """
    stream = _sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 980000, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "The riser diagram on M-5"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta",
         "delta": {"stop_reason": "model_context_window_exceeded"},
         "usage": {"output_tokens": 12000}},
    ])
    _load(page, _chat_doc(), tmp_path, queue=[stream])
    _ask(page, "walk me through every sheet")

    notes = page.eval_on_selector_all(".da-note", "els => els.map(e => e.textContent)")
    assert any("filled the model's context window" in n for n in notes), notes
    assert any("New chat" in n for n in notes), notes
    # It is NOT the output-cap message: nothing about the request was too small.
    assert not any("output limit reached" in n for n in notes), notes
    # And the gauge agrees the window is full rather than contradicting the note.
    assert page.eval_on_selector("#da-chat-context", "el => el.dataset.tier") == "full"

    # The note rides the transcript, so a reload does not resurrect the answer as
    # a complete one. (`_stored` reads the auto-saved browser copy.)
    saved = _stored(page)
    assert saved is not None
    assistant = [t for t in saved["turns"] if t["message"]["role"] == "assistant"]
    assert assistant, saved
    assert any("context window" in n for n in assistant[-1]["display"]["notes"]), assistant[-1]


def test_context_readout_is_a_snapshot_not_a_running_total(page, tmp_path):
    """Two questions must not read as the sum of both prompts.

    The whole point of the counter is "how full is the window now", and each
    request re-sends the report plus the transcript — so the second round's own
    prompt already contains the first. Accumulating would double-count the
    report and race to a false ceiling.
    """
    def _round(prompt, out):
        return _sse([
            {"type": "message_start", "message": {"usage": {
                "input_tokens": prompt, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "ok."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": out}},
        ])

    _load(page, _chat_doc(), tmp_path, queue=[_round(100000, 500), _round(140000, 500)])
    _ask(page, "first question")
    first = page.eval_on_selector("#da-chat-context-text", "el => el.textContent")
    assert "100.5k" in first, first

    page.fill("#da-chat-input", "second question")
    page.click("#da-chat-send")
    _finish(page)
    second = page.eval_on_selector("#da-chat-context-text", "el => el.textContent")
    assert "140.5k" in second, second     # the round's own prompt, not 240.5k

    # The cumulative counter beside it still sums, which is what makes the two
    # readouts worth having separately.
    assert "240k in" in page.eval_on_selector("#da-chat-usage", "el => el.textContent")


def test_context_readout_warns_as_the_window_fills(page, tmp_path):
    # The overrun is abrupt — the request that exceeds the window is rejected
    # outright — so the reader gets the nudge before it happens, not after.
    def _round(prompt):
        return _sse([
            {"type": "message_start", "message": {"usage": {
                "input_tokens": prompt, "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": "ok."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 0}},
        ])

    _load(page, _chat_doc(), tmp_path, queue=[_round(750_000), _round(930_000)])
    _ask(page, "a long thread")
    assert page.eval_on_selector("#da-chat-context", "el => el.dataset.tier") == "near"
    assert "filling up" in page.eval_on_selector("#da-chat-context-text", "el => el.textContent")

    page.fill("#da-chat-input", "a longer one")
    page.click("#da-chat-send")
    _finish(page)
    assert page.eval_on_selector("#da-chat-context", "el => el.dataset.tier") == "full"
    text = page.eval_on_selector("#da-chat-context-text", "el => el.textContent")
    assert "New chat" in text, text


def test_output_tokens_are_not_double_counted_across_message_deltas(page, tmp_path):
    # message_delta reports output_tokens CUMULATIVELY for the message, and a
    # message may emit more than one. Summing each event's figure would read
    # 50-then-120 as 170; the honest total is 120.
    stream = _sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 10, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "answered."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {}, "usage": {"output_tokens": 50}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 120}},
    ])
    _load(page, _chat_doc(), tmp_path, queue=[stream])
    _ask(page, "what are the conflicts?")

    text = page.eval_on_selector("#da-chat-usage", "el => el.textContent")
    assert "120 out" in text, text
    assert "170 out" not in text, text


def test_output_tokens_still_sum_across_rounds(page, tmp_path):
    # Each round is its own message, so the per-message cumulative figures must
    # still add up across a tool loop — the fix above must not clamp to a max.
    def round_with_output(frames, out):
        return _sse(frames + [{"type": "message_delta",
                               "delta": {"stop_reason": frames[-1].get("_stop", "end_turn")},
                               "usage": {"output_tokens": out}}])

    tool_round = _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "tool_use", "id": "q1", "name": "query_findings", "input": {}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "input_json_delta", "partial_json": '{"severity":"high"}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
         "usage": {"output_tokens": 30}},
    ])
    text_round = _sse([
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "one finding."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 45}},
    ])
    _load(page, _chat_doc(), tmp_path, queue=[tool_round, text_round])
    _ask(page, "how many high severity findings?")

    text = page.eval_on_selector("#da-chat-usage", "el => el.textContent")
    assert "75 out" in text, text


def test_loading_a_transcript_resets_the_usage_counter(page, tmp_path):
    # The counter belongs to the thread. Loading a saved conversation over one you
    # already spent tokens on must not keep charging the abandoned thread's spend
    # to the new one.
    stream = _sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 500, "cache_read_input_tokens": 9000,
            "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "answered."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 250}},
    ])
    _load(page, _chat_doc(), tmp_path, queue=[stream])
    _ask_and_settle(page, "what are the conflicts?")
    assert page.eval_on_selector("#da-chat-usage", "el => el.hidden") is False

    # Hand the widget a valid transcript for this same report, as Load would.
    saved = _stored(page)
    assert saved is not None
    # Replacing a non-empty thread asks for confirmation; Playwright dismisses
    # dialogs by default, which would silently abort the load.
    page.on("dialog", lambda d: d.accept())
    page.set_input_files(
        "#da-chat-load-input",
        files=[{"name": "chat.json", "mimeType": "application/json",
                "buffer": json.dumps(saved).encode()}],
    )
    page.wait_for_function(
        "() => document.getElementById('da-chat-msgs').textContent"
        ".indexOf('Conversation loaded') !== -1",
        timeout=5000,
    )
    assert page.eval_on_selector("#da-chat-usage", "el => el.hidden") is True


def test_the_usage_readout_appearing_reclamps_the_ask_box(page, tmp_path):
    # Same class of bug as test_a_fixed_row_growing_reclamps_an_already_expanded_box,
    # via a different row. The footer is one of the fixed rows composeCap()
    # measures, and the usage readout un-hides inside it after the FIRST answer —
    # so a box expanded against the readout-less footer holds a stale height the
    # moment the first question lands, and the transcript absorbs the difference.
    stream = _sse([
        {"type": "message_start", "message": {"usage": {
            "input_tokens": 120, "cache_read_input_tokens": 40000,
            "cache_creation_input_tokens": 0}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "answered."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 250}},
    ])
    page.set_viewport_size({"width": 1200, "height": 640})
    _load(page, _chat_doc(), tmp_path, queue=[stream])
    page.click("#da-chat-fab")
    page.wait_for_selector("#da-chat-panel", state="visible", timeout=3000)
    page.click("#da-chat-expand")
    expanded = _box_h(page)
    foot_before = page.evaluate(
        "() => document.querySelector('.da-chat-foot').getBoundingClientRect().height"
    )

    page.fill("#da-chat-input", "what are the conflicts?")
    page.click("#da-chat-send")
    _finish(page)

    assert page.eval_on_selector("#da-chat-usage", "el => el.hidden") is False
    foot_after = page.evaluate(
        "() => document.querySelector('.da-chat-foot').getBoundingClientRect().height"
    )
    grew = foot_after - foot_before
    assert grew > 0, "the readout should make the footer taller"

    geom = page.evaluate(
        """() => {
          var r = function(sel){ return document.querySelector(sel).getBoundingClientRect(); };
          return {panel: r('#da-chat-panel'), msgs: r('#da-chat-msgs'),
                  foot: r('.da-chat-foot')};
        }"""
    )
    # Sending resets an auto-grown box, so assert the invariants rather than an
    # exact hand-back: nothing may be pushed out of the panel's clipped overflow.
    assert _box_h(page) <= expanded + 1
    assert geom["msgs"]["height"] >= 80, "the transcript floor still holds"
    assert geom["foot"]["bottom"] <= geom["panel"]["bottom"] + 1, (
        "the footer must stay inside the panel once the readout appears")
