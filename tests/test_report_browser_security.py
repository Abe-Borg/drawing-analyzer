"""Headless-Chromium exploit tests for the HTML report (Phase 17B, DA-011/027).

A DOM emulator cannot prove CSP enforcement, ``file://`` behavior, browser URL
normalization, real event dispatch, or streamed rendering — so this suite drives
the *actual* report in headless Chromium and asserts that no attacker-influenced
string (drawing text feeds the prompts, so model output is hostile) ever reaches
an executable sink.

Hermetic: the report is built in-process and loaded over ``file://``; the
Anthropic ``fetch`` is stubbed with a canned malicious SSE stream, so there is
no network and no API key. The whole thing skips cleanly when Playwright (or its
browser binary) is unavailable, so the default ``pytest`` run on a machine
without a browser is unaffected; CI installs Chromium and runs it on Linux.

The load-bearing assertion is a global execution **sentinel** (``window.__pwned``):
every attack payload tries to set it. Safe DOM construction (textContent, no
``innerHTML`` with model data) plus the hash-pinned CSP mean it must stay
``false`` through incremental *and* final render paths and after real
hover/focus/click/image-error events.
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

NOW = datetime(2026, 7, 10, 8, 0)

# Every payload attempts to set window.__pwned. If any executes, the sentinel
# flips and the test fails. These cover the plan's required corpus.
_ATTACKS = {
    "filename": '</script><script>window.__pwned=1</script>x.pdf',
    "sheet_id": '"><img src=x onerror=window.__pwned=1>',
    "quote": '" autofocus onfocus="window.__pwned=1',
    "category": '<svg onload=window.__pwned=1>',
    "text": '<img src=x onerror=window.__pwned=1> and </script><script>window.__pwned=1</script>',
    "focus": '<iframe src=javascript:window.__pwned=1></iframe>',
    "error": 'boom </script><script>window.__pwned=1</script>',
    "evidence": 'evidence/"><img src=x onerror=window.__pwned=1>.png',
}


def _launch(p):
    """Launch headless Chromium, tolerating a pre-provisioned browser whose
    build number does not match the installed Playwright (sandboxed images)."""
    try:
        return p.chromium.launch(headless=True)
    except PlaywrightError:
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        for pat in (
            "chromium-*/chrome-linux/chrome",
            "chromium-*/chrome-linux64/chrome",
            "chromium-*/chrome-win/chrome.exe",
        ):
            hits = sorted(glob.glob(os.path.join(root, pat)))
            if hits:
                return p.chromium.launch(headless=True, executable_path=hits[-1])
        raise


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = _launch(p)
        except Exception as exc:  # noqa: BLE001 - no browser here → skip, don't fail
            pytest.skip(f"headless Chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    # Arm the sentinel and a CSP-violation recorder before any page script runs.
    pg.add_init_script(
        "window.__pwned = false;"
        "window.__csp = [];"
        "document.addEventListener('securitypolicyviolation',"
        " function(e){ window.__csp.push(e.violatedDirective + ' ' + e.blockedURI); });"
    )
    yield pg
    ctx.close()


def _load(page, doc: str, tmp_path):
    f = tmp_path / "report.html"
    f.write_text(doc, encoding="utf-8")
    page.goto(f.as_uri())
    return page


# --------------------------------------------------------------------------- #
# 1. The report body: hostile values across every surface stay inert.
# --------------------------------------------------------------------------- #


def _hostile_ctx() -> _Ctx:
    f = Finding(
        sheet_id=_ATTACKS["sheet_id"],
        source_name=_ATTACKS["filename"],
        page_index=0,
        category=_ATTACKS["category"],
        severity="high",
        text=_ATTACKS["text"],
        source_quote=_ATTACKS["quote"],
        anchor=Anchor(status="EXACT", rect_pdf=[0, 0, 1, 1]),
        verification=Verification(status="VERIFIED", evidence_png=_ATTACKS["evidence"]),
    )
    ctx = _Ctx(
        sheets=[_Sheet(_Ref(_ATTACKS["filename"], 0, 1),
                       text="**Conflicts**\n- " + _ATTACKS["text"])],
        synthesis_text="**Conflicts**\n- " + _ATTACKS["text"],
        combined_text=_ATTACKS["text"],
        errors=[_ATTACKS["error"]],
        focus=_ATTACKS["focus"],
        focus_report_text="**Focus**\n- " + _ATTACKS["text"],
    )
    ctx.findings = [f]
    return ctx


def test_report_body_corpus_is_inert(page, tmp_path):
    doc = hr.build_html_report(
        _hostile_ctx(), source_names=[_ATTACKS["filename"]], now=NOW, link_evidence=True
    )
    _load(page, doc, tmp_path)

    # Dispatch the events attack payloads rely on, across every element.
    page.evaluate(
        """() => {
          document.querySelectorAll('*').forEach(el => {
            ['mouseover','focus','click'].forEach(type => {
              try { el.dispatchEvent(new Event(type, {bubbles:true})); } catch(e){}
            });
            if (el.tagName === 'IMG' && el.onerror) { try { el.onerror(); } catch(e){} }
          });
        }"""
    )
    # Force any <img> to actually attempt a load (fires onerror if a real,
    # attacker-created img slipped through).
    page.evaluate(
        "() => document.querySelectorAll('img').forEach(i => { i.src = i.src; })"
    )
    page.wait_for_timeout(150)

    assert page.evaluate("window.__pwned") is False, "an attack payload executed"
    # No attacker-created dangerous elements exist in the live DOM.
    assert page.evaluate("!!document.querySelector('iframe,object,embed,svg')") is False
    # The hostile text is present — as escaped, visible text (never dropped).
    assert page.evaluate(
        "document.body.textContent.includes('window.__pwned=1')"
    ), "escaped payload text should be visible"


# --------------------------------------------------------------------------- #
# 2. The Ask-AI assistant: a malicious streamed answer stays inert through the
#    incremental (debounced) AND final render paths.
# --------------------------------------------------------------------------- #

# Split the payload across deltas so touchText's 90ms incremental render fires
# mid-stream, then content_block_stop drives the final render.
_MAL_DELTAS = [
    "A link [x](javascript:window.__pwned=1) then ",
    'an image <img src=x onerror="window.__pwned=1"> then ',
    "a break-out </script><script>window.__pwned=1</script> and a "
    "[safe link](https://example.com/page).",
]


def _sse(frames) -> str:
    return "".join(f"data: {json.dumps(fr)}\n\n" for fr in frames)


def _malicious_stream() -> str:
    frames = [
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
    ]
    frames += [
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": d}}
        for d in _MAL_DELTAS
    ]
    frames += [
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "index": 0, "delta": {"stop_reason": "end_turn"}},
    ]
    return _sse(frames)


_FETCH_STUB = """
(function(){
  var enc = new TextEncoder();
  var bytes = enc.encode(window.__SSE);
  // Replace fetch entirely: the assistant only ever calls the Anthropic
  // endpoint, and we return a chunked stream so incremental rendering fires.
  window.fetch = function(){
    var n = bytes.length, cuts = [Math.floor(n/3), Math.floor(2*n/3), n], ci = 0, pos = 0;
    var reader = { read: function(){
      if (pos >= n) return Promise.resolve({done:true, value:undefined});
      return new Promise(function(resolve){
        setTimeout(function(){
          var end = cuts[Math.min(ci, cuts.length-1)]; ci++;
          var chunk = bytes.slice(pos, end); pos = end;
          resolve({done:false, value: chunk});
        }, 40);
      });
    }};
    return Promise.resolve({ ok:true, status:200, body:{ getReader:function(){ return reader; } } });
  };
})();
"""


def _ask(page, question="attack me"):
    page.click("#da-chat-fab")
    page.fill("#da-chat-input", question)
    page.click("#da-chat-send")
    # Streaming disables Send; wait for it to re-enable (turn finished).
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send');"
        " return b && b.disabled; }", timeout=5000
    )
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send');"
        " return b && !b.disabled; }", timeout=10000
    )
    page.wait_for_timeout(150)  # let any trailing debounced render settle


def test_ask_ai_malicious_stream_is_inert(page, tmp_path):
    # Embed a fake key so ensureKey() doesn't prompt; the stub intercepts fetch.
    doc = hr.build_html_report(
        _hostile_ctx(), source_names=[_ATTACKS["filename"]], now=NOW,
        api_key="sk-ant-fake-not-real", embed_api_key=True,
    )
    page.add_init_script("window.__SSE = " + json.dumps(_malicious_stream()) + ";")
    page.add_init_script(_FETCH_STUB)
    _load(page, doc, tmp_path)
    _ask(page)

    assert page.evaluate("window.__pwned") is False, "streamed payload executed"
    # The safe https link rendered as a real anchor, hardened.
    anchor = page.query_selector(".da-ai a[href='https://example.com/page']")
    assert anchor is not None, "legitimate https link should render"
    assert set((anchor.get_attribute("rel") or "").split()) >= {"noopener", "noreferrer"}
    assert anchor.get_attribute("target") == "_blank"
    # No live javascript: link, and no attacker-created dangerous elements.
    assert page.evaluate(
        "() => Array.from(document.querySelectorAll('a'))"
        ".every(a => a.protocol !== 'javascript:')"
    )
    assert page.evaluate(
        "!!document.querySelector('.da-ai script, .da-ai iframe, .da-ai svg')"
    ) is False
    # The break-out text is visible as inert text, proving it was escaped.
    assert page.evaluate(
        "document.querySelector('.da-ai').textContent.includes('window.__pwned=1')"
    )


def test_ask_ai_malicious_citation_is_inert(page, tmp_path):
    # A citations_delta carrying a javascript: URL must not become a live link.
    frames = [
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "See source."}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "citations_delta",
                   "citation": {"url": "javascript:window.__pwned=1", "title": "evil"}}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "citations_delta",
                   "citation": {"url": "https://good.example/ref", "title": "ok"}}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "index": 0, "delta": {"stop_reason": "end_turn"}},
    ]
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
        api_key="sk-ant-fake-not-real", embed_api_key=True,
    )
    page.add_init_script("window.__SSE = " + json.dumps(_sse(frames)) + ";")
    page.add_init_script(_FETCH_STUB)
    _load(page, doc, tmp_path)
    _ask(page, "cite something")

    assert page.evaluate("window.__pwned") is False
    # Only the safe citation became a link; the javascript: one was dropped.
    hrefs = page.evaluate(
        "() => Array.from(document.querySelectorAll('.da-cites a')).map(a => a.href)"
    )
    assert "https://good.example/ref" in hrefs
    assert all(not h.startswith("javascript:") for h in hrefs)


# --------------------------------------------------------------------------- #
# 3. Ask AI works without a build-time key: first send prompts for one.
# --------------------------------------------------------------------------- #


def test_ask_ai_without_key_prompts_on_first_use(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,   # no api_key → prompt-on-use mode
    )
    page.add_init_script("window.__SSE = " + json.dumps(_malicious_stream()) + ";")
    page.add_init_script(_FETCH_STUB)
    _load(page, doc, tmp_path)

    prompted = {"count": 0}

    def _on_dialog(dialog):
        prompted["count"] += 1
        dialog.accept("sk-ant-entered-at-runtime")

    page.on("dialog", _on_dialog)
    page.click("#da-chat-fab")
    page.fill("#da-chat-input", "hello")
    page.click("#da-chat-send")
    page.wait_for_timeout(500)

    assert prompted["count"] == 1, "first send with no key must prompt"
    # The prompted key lives only in sessionStorage, never in the file.
    assert "sk-ant-entered-at-runtime" not in doc
    assert page.evaluate("sessionStorage.getItem('da-api-key')") == "sk-ant-entered-at-runtime"
    # Forget key clears it from the tab.
    page.click("#da-chat-forget")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None


# --------------------------------------------------------------------------- #
# 4. CSP is actually enforced: an injected inline <script> does not execute.
# --------------------------------------------------------------------------- #


def test_csp_blocks_injected_inline_script(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    _load(page, doc, tmp_path)
    # Try to inject an inline script with no CSP hash allowance (what an XSS
    # would attempt). The browser must refuse to run it.
    page.evaluate(
        """() => {
          var s = document.createElement('script');
          s.textContent = 'window.__pwned = true;';
          document.body.appendChild(s);
        }"""
    )
    page.wait_for_timeout(50)
    assert page.evaluate("window.__pwned") is False
    assert page.evaluate("window.__csp.length") > 0, "a CSP violation should be recorded"
