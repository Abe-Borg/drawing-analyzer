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
    # Wait for the *settled* state rather than the transient disabled→enabled
    # flip: wait_for_function's own setup can outlast a fast canned stream, and
    # watching for `disabled` then misses it and times out (a real flake under a
    # loaded machine). The user bubble is created synchronously by the send, so
    # "bubble present AND Send re-enabled" means exactly "a turn ran and
    # finished" — and it holds on the error paths, where the empty assistant
    # bubble is removed again.
    page.wait_for_function(
        "() => { var b = document.getElementById('da-chat-send');"
        " return b && !b.disabled && document.querySelector('.da-user'); }",
        timeout=15000,
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
# 3. Ask AI works without a build-time key: the reader supplies one in the
#    in-panel key field (a real masked input, never a native window.prompt);
#    a 401 forgets the key and re-surfaces the field; errors are scrubbed.
# --------------------------------------------------------------------------- #


def _wait_turn(page):
    # Send disables during streaming, then re-enables when the turn finishes.
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send'); return b && b.disabled; }",
        timeout=5000,
    )
    page.wait_for_function(
        "() => { var b=document.getElementById('da-chat-send'); return b && !b.disabled; }",
        timeout=10000,
    )
    page.wait_for_timeout(150)


def test_ask_ai_without_key_uses_inline_key_field(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,   # no api_key → inline key entry
    )
    page.add_init_script("window.__SSE = " + json.dumps(_malicious_stream()) + ";")
    page.add_init_script(_FETCH_STUB)
    # A native prompt()/alert() dialog must NEVER appear; record it if it does.
    seen = {"dialogs": 0}

    def _on_dialog(d):
        seen["dialogs"] += 1
        d.dismiss()

    page.on("dialog", _on_dialog)
    _load(page, doc, tmp_path)

    page.click("#da-chat-fab")
    # With no key, the entry form shows and the "set" state is hidden.
    assert page.is_visible("#da-chat-key-input")
    assert page.eval_on_selector("#da-chat-key-set", "el => el.hidden") is True

    # Clicking Send with no key surfaces the form (never a window.prompt) and
    # preserves the typed question.
    page.fill("#da-chat-input", "hello")
    page.click("#da-chat-send")
    page.wait_for_timeout(200)
    assert seen["dialogs"] == 0, "must not use a native prompt dialog"
    assert page.is_visible("#da-chat-key-input")
    assert page.eval_on_selector("#da-chat-input", "el => el.value") == "hello"

    # Enter a key in the field and save it.
    page.fill("#da-chat-key-input", "sk-ant-entered-at-runtime")
    page.click("#da-chat-key-save")
    # Stored only in sessionStorage, cleared from the DOM input, form collapses.
    assert page.evaluate("sessionStorage.getItem('da-api-key')") == "sk-ant-entered-at-runtime"
    assert "sk-ant-entered-at-runtime" not in doc
    assert page.eval_on_selector("#da-chat-key-input", "el => el.value") == ""
    assert page.eval_on_selector("#da-chat-key-form", "el => el.hidden") is True
    assert page.is_visible("#da-chat-key-change")

    # A question now streams normally through the stub and stays inert.
    page.fill("#da-chat-input", "hello again")
    page.click("#da-chat-send")
    _wait_turn(page)
    assert page.evaluate("window.__pwned") is False

    # Forget key clears it and brings the entry form back.
    page.click("#da-chat-forget")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None
    assert page.is_visible("#da-chat-key-input")


def test_ask_ai_401_forgets_key_and_resurfaces_field(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    # fetch → 401: the entered key must be dropped and the field re-opened.
    stub = (
        "(function(){ window.fetch = function(){"
        " return Promise.resolve({ ok:false, status:401,"
        " json:function(){ return Promise.resolve({error:{message:'unauthorized'}}); } }); }; })();"
    )
    page.add_init_script(stub)
    _load(page, doc, tmp_path)

    page.click("#da-chat-fab")
    page.fill("#da-chat-key-input", "sk-ant-will-be-rejected")
    page.click("#da-chat-key-save")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") == "sk-ant-will-be-rejected"

    page.fill("#da-chat-input", "hello")
    page.click("#da-chat-send")
    page.wait_for_selector(".da-err", timeout=5000)
    assert "401" in page.eval_on_selector(".da-err", "el => el.textContent")
    # Rejected key forgotten; the entry field is shown again for a new one.
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None
    assert page.is_visible("#da-chat-key-input")
    assert page.evaluate("window.__pwned") is False


def test_ask_ai_api_error_scrubs_key_material(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    # A non-401 API error whose message echoes a key must be redacted in the DOM.
    stub = (
        "(function(){ window.fetch = function(){"
        " return Promise.resolve({ ok:false, status:500,"
        " json:function(){ return Promise.resolve("
        "{error:{message:'boom sk-ant-LEAKED999 boom'}}); } }); }; })();"
    )
    page.add_init_script(stub)
    _load(page, doc, tmp_path)

    page.click("#da-chat-fab")
    page.fill("#da-chat-key-input", "sk-ant-some-key")
    page.click("#da-chat-key-save")
    page.fill("#da-chat-input", "hello")
    page.click("#da-chat-send")
    page.wait_for_selector(".da-err", timeout=5000)
    err = page.eval_on_selector(".da-err", "el => el.textContent")
    assert "sk-ant-LEAKED999" not in err
    assert "sk-ant-[redacted]" in err
    assert page.evaluate("document.body.textContent.indexOf('sk-ant-LEAKED999')") == -1


def test_key_field_toggle_masks_and_unmasks(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    assert page.eval_on_selector("#da-chat-key-input", "el => el.type") == "password"
    page.click("#da-chat-key-toggle")
    assert page.eval_on_selector("#da-chat-key-input", "el => el.type") == "text"
    page.click("#da-chat-key-toggle")
    assert page.eval_on_selector("#da-chat-key-input", "el => el.type") == "password"


def _embedded_key_report(tmp_path, page):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
        api_key="sk-ant-fake-not-real", embed_api_key=True,
    )
    page.add_init_script("window.__SSE = " + json.dumps(_malicious_stream()) + ";")
    page.add_init_script(_FETCH_STUB)
    return _load(page, doc, tmp_path)


def test_embedded_key_is_a_default_the_reader_can_override(page, tmp_path):
    # The embedded key runs the panel out of the box, but the entry row is
    # OFFERED, not hidden. Hiding it meant a shared report billed every question
    # to whoever generated it, with no way for the reader to use their own key.
    _embedded_key_report(tmp_path, page)
    _ask(page, "hi")   # opens the panel + sends using the embedded key
    assert page.evaluate("window.__pwned") is False

    # The row is present and says which key is in play, with the swap offered.
    assert page.eval_on_selector("#da-chat-key", "el => el.hidden") is False
    assert "embedded in this report" in page.inner_text("#da-chat-key-set-label")
    assert page.inner_text("#da-chat-key-change").strip() == "Use my own key"
    # Nothing to switch back TO yet, so that control stays hidden.
    assert page.eval_on_selector("#da-chat-key-author", "el => el.hidden") is True
    # The tall entry form is not in the way until asked for.
    assert page.is_visible("#da-chat-key-input") is False


def test_reader_key_overrides_the_embedded_one_and_can_be_handed_back(page, tmp_path):
    _embedded_key_report(tmp_path, page)
    page.click("#da-chat-fab")

    # "Use my own key" opens the field; saving a key takes precedence.
    page.click("#da-chat-key-change")
    assert page.is_visible("#da-chat-key-input")
    page.fill("#da-chat-key-input", "sk-ant-readers-own-key")
    page.click("#da-chat-key-save")

    assert page.evaluate("sessionStorage.getItem('da-api-key')") == "sk-ant-readers-own-key"
    assert "Using your API key" in page.inner_text("#da-chat-key-set-label")
    # The field never keeps the secret in the DOM.
    assert page.input_value("#da-chat-key-input") == ""
    # Now there IS something to hand back to.
    assert page.eval_on_selector("#da-chat-key-author", "el => el.hidden") is False

    # Handing it back drops the reader's key and falls through to the file's.
    page.click("#da-chat-key-author")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None
    assert "embedded in this report" in page.inner_text("#da-chat-key-set-label")
    assert page.eval_on_selector("#da-chat-key-author", "el => el.hidden") is True


def test_forget_key_does_not_claim_to_have_removed_the_embedded_one(page, tmp_path):
    # Clearing the reader's key while the FILE still carries one must say so:
    # the credential in the HTML survives and is what the next question uses.
    _embedded_key_report(tmp_path, page)
    page.click("#da-chat-fab")
    page.click("#da-chat-key-change")
    page.fill("#da-chat-key-input", "sk-ant-readers-own-key")
    page.click("#da-chat-key-save")

    page.click("#da-chat-forget")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None
    note = page.inner_text("#da-chat-msgs")
    assert "removed from this browser tab" in note
    assert "cannot remove that one" in note
    # And the panel is still usable — it fell back rather than going dead.
    assert "embedded in this report" in page.inner_text("#da-chat-key-set-label")


def test_reader_key_survives_a_key_less_report_as_before(page, tmp_path):
    # The default (no embedded key) path is unchanged: enter a key, it is kept
    # in sessionStorage only, and Forget really does clear everything.
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    assert page.is_visible("#da-chat-key-input")
    page.fill("#da-chat-key-input", "sk-ant-readers-own-key")
    page.click("#da-chat-key-save")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") == "sk-ant-readers-own-key"
    # No embedded key to fall back to, so the swap control stays hidden.
    assert page.eval_on_selector("#da-chat-key-author", "el => el.hidden") is True

    page.click("#da-chat-forget")
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None
    assert "removed from this browser tab" in page.inner_text("#da-chat-msgs")
    assert page.is_visible("#da-chat-key-input")   # field re-opens


def test_key_field_hidden_in_pdf_transcript_export(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    assert page.is_visible("#da-chat-key-input")   # visible on screen
    # "Save as PDF" adds body.da-print-chat and prints the panel as a transcript;
    # under print media the key row must be hidden so a key can never land in the
    # exported PDF (the panel itself is still shown by the transcript rules).
    page.emulate_media(media="print")
    page.evaluate("document.body.classList.add('da-print-chat')")
    assert page.is_visible("#da-chat-panel")
    assert page.is_visible("#da-chat-key") is False
    assert page.is_visible("#da-chat-key-input") is False


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


# --------------------------------------------------------------------------- #
# 5. Transcript persistence: a saved conversation is a new place model output
#    and reader input come to rest, and a new channel they come back in through.
#    Both directions are held to the same rules as the live stream.
# --------------------------------------------------------------------------- #


def _plain_ctx() -> _Ctx:
    return _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x")


def _report_id_of(doc: str) -> str:
    start = doc.index('id="da-chat-config"')
    body = doc[doc.index(">", start) + 1: doc.index("</script>", start)]
    return json.loads(body)["reportId"]


def test_saved_transcript_never_carries_key_material(page, tmp_path):
    # A reader can paste a key into the chat box, and the model can echo one
    # back. Neither may reach durable storage.
    doc = hr.build_html_report(_plain_ctx(), source_names=["a.pdf"], now=NOW)
    page.add_init_script(
        "window.__SSE = " + json.dumps(_sse([
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta",
                       "text": "you sent sk-ant-ECHOED222 back to me"}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "index": 0, "delta": {"stop_reason": "end_turn"}},
        ])) + ";"
    )
    page.add_init_script(_FETCH_STUB)
    _load(page, doc, tmp_path)

    page.click("#da-chat-fab")        # opens the panel; _ask would re-click it
    page.fill("#da-chat-key-input", "sk-ant-SESSIONKEY111")
    page.click("#da-chat-key-save")
    page.fill("#da-chat-input", "is sk-ant-PASTED000 a valid key?")
    page.click("#da-chat-send")
    page.wait_for_function(
        "() => { var b = document.getElementById('da-chat-send');"
        " return b && !b.disabled && document.querySelector('.da-user'); }",
        timeout=10000,
    )
    page.wait_for_timeout(200)

    stored = page.evaluate(
        """() => {
          for (var i = 0; i < localStorage.length; i++) {
            var k = localStorage.key(i);
            if (k.indexOf('da-chat-tx-') === 0) return localStorage.getItem(k);
          }
          return null;
        }"""
    )
    assert stored, "the conversation should have been saved"
    for secret in ("sk-ant-PASTED000", "sk-ant-ECHOED222", "sk-ant-SESSIONKEY111"):
        assert secret not in stored, f"{secret} reached durable storage"
    assert "sk-ant-[redacted]" in stored
    # The key the reader actually authenticated with is not in the document at all.
    assert "apiKey" not in stored


def test_loaded_transcript_is_inert(page, tmp_path):
    # A transcript file is untrusted input from outside the report. Every hostile
    # payload must render as text through the same safe-DOM path as a stream.
    doc = hr.build_html_report(_plain_ctx(), source_names=["a.pdf"], now=NOW)
    transcript = {
        "kind": "drawing_analyzer_chat_transcript",
        "schema_version": 1,
        "report": {"report_id": _report_id_of(doc), "title": _ATTACKS["filename"]},
        "saved_at": "2026-07-14T08:00:00.000Z",
        "truncated": False,
        "turns": [
            {"message": {"role": "user", "content": _ATTACKS["text"]},
             "display": {"text": _ATTACKS["text"], "excerpt": _ATTACKS["quote"]}},
            {"message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": _ATTACKS["text"]},
                {"type": "text", "text": _ATTACKS["text"] + " [link](javascript:window.__pwned=1)",
                 "citations": [{"url": "javascript:window.__pwned=1", "title": "evil"},
                               {"url": "https://good.example/ref", "title": "ok"}]},
                {"type": "tool_use", "id": "t1", "name": "highlight_term",
                 "input": {"term": _ATTACKS["sheet_id"]}},
            ]},
             "display": {"notes": [_ATTACKS["error"]]}},
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": _ATTACKS["text"]}]}},
            {"message": {"role": "assistant",
                         "content": [{"type": "text", "text": "done"}]},
             "display": {"notes": []}},
        ],
    }
    path = tmp_path / "hostile.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")

    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.set_input_files("#da-chat-load-input", str(path))
    page.wait_for_selector(".da-ai", timeout=5000)

    assert page.evaluate("window.__pwned") is False, "loaded transcript executed"
    assert page.evaluate(
        "!!document.querySelector('#da-chat-msgs script, #da-chat-msgs iframe,"
        " #da-chat-msgs svg, #da-chat-msgs img')"
    ) is False
    assert page.evaluate(
        "() => Array.from(document.querySelectorAll('a'))"
        ".every(a => a.protocol !== 'javascript:')"
    )
    # The safe citation still renders; the hostile one produced no anchor at all.
    assert page.query_selector(".da-ai a[href='https://good.example/ref']") is not None
    # The break-out text is visible as inert text, proving it was escaped.
    assert "window.__pwned=1" in page.eval_on_selector("#da-chat-msgs", "el => el.textContent")
    assert page.evaluate("window.__csp") == []


def test_loaded_transcript_does_not_execute_client_tools(page, tmp_path):
    # Recorded tool calls are rendered as chips, never dispatched — otherwise
    # "open a JSON file" would let a transcript drive the reader's report.
    doc = hr.build_html_report(_plain_ctx(), source_names=["a.pdf"], now=NOW)
    transcript = {
        "kind": "drawing_analyzer_chat_transcript",
        "schema_version": 1,
        "report": {"report_id": _report_id_of(doc)},
        "saved_at": "x", "truncated": False,
        "turns": [
            {"message": {"role": "user", "content": "do it"},
             "display": {"text": "do it", "excerpt": ""}},
            {"message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "f1", "name": "filter_report",
                 "input": {"search": "zznomatchzz", "high_only": True}},
            ]}, "display": {"notes": []}},
            {"message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "f1", "content": "0 of 1"}]}},
            {"message": {"role": "assistant",
                         "content": [{"type": "text", "text": "filtered"}]},
             "display": {"notes": []}},
        ],
    }
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(transcript), encoding="utf-8")

    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.set_input_files("#da-chat-load-input", str(path))
    page.wait_for_selector(".da-tool", timeout=5000)

    assert page.eval_on_selector("#search", "el => el.value") == ""
    assert page.eval_on_selector_all("main.content .hidden", "els => els.length") == 0
    assert page.evaluate("window.__pwned") is False


def test_transcript_controls_hidden_in_pdf_transcript_export(page, tmp_path):
    # Mirrors the key-field rule: the printed transcript is the conversation,
    # not the chrome around it.
    doc = hr.build_html_report(
        _plain_ctx(), source_names=["a.pdf"], now=NOW,
        api_key="sk-ant-fake-not-real", embed_api_key=True,
    )
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.evaluate("document.body.classList.add('da-print-chat')")
    page.emulate_media(media="print")
    for control in ("#da-chat-save", "#da-chat-load", "#da-chat-export"):
        assert page.is_visible(control) is False, f"{control} should not print"


# --------------------------------------------------------------------------- #
# 7. Repeat grouping: the DISPLAY collapses duplicate quotes; the ledger and the
#    counts do not. No finding may be lost behind the collapse.
# --------------------------------------------------------------------------- #


_REPEAT_QUOTE = "CONTRACTOR SHALL COORDINATE WITH PLUMBING AND CIVIL."


def _repeats_ctx(n_repeats=4):
    """One distinct finding plus ``n_repeats`` sharing a single verbatim quote."""
    findings = [
        Finding(
            sheet_id="F-A-01", source_name="a.pdf", page_index=0,
            category="conflict", severity="high",
            text="A one-off conflict", source_quote="ONLY ONCE",
            anchor=Anchor(status="EXACT"), verification=Verification(status="SKIPPED"),
        )
    ]
    for i in range(n_repeats):
        findings.append(Finding(
            sheet_id="F-D-%02d" % i, source_name="a.pdf", page_index=0,
            category="coordination", severity="medium",
            text="Coordinate with plumbing on sheet %d" % i,
            source_quote=_REPEAT_QUOTE,
            anchor=Anchor(status="EXACT"), verification=Verification(status="SKIPPED"),
        ))
    return _Ctx(
        sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x",
        findings=findings,
    )


def _visible_rows(page):
    return page.eval_on_selector_all(
        ".finding-row",
        "els => els.filter(e => !e.classList.contains('hidden')"
        " && !e.classList.contains('repeat-hidden')).length",
    )


def test_repeated_quotes_collapse_by_default_without_changing_the_total(page, tmp_path):
    # A general note printed on every plan sheet is one real finding per sheet,
    # but N identical rows are unreadable. The rows collapse; the badge total
    # stays the full count (§18.6 — the display never rewrites the ledger).
    doc = hr.build_html_report(_repeats_ctx(4), source_names=["a.pdf"], now=NOW)
    _load(page, doc, tmp_path)
    assert page.eval_on_selector_all(".finding-row", "els => els.length") == 5
    assert _visible_rows(page) == 2          # the one-off + one lead for the group
    assert "5 finding(s)" in page.inner_text("#findings .badge-findings")
    assert "3 repeated quotes collapsed into 1 group" in page.inner_text(
        "#findings-group-note"
    )
    assert "showing 2 of 5" in page.inner_text("#findings-shown")


def test_collapsed_repeats_expand_in_place_and_collapse_again(page, tmp_path):
    doc = hr.build_html_report(_repeats_ctx(4), source_names=["a.pdf"], now=NOW)
    _load(page, doc, tmp_path)
    btn = page.locator(".repeat-toggle:not([hidden])")
    assert btn.count() == 1
    assert "+3 more sheets" in btn.inner_text()

    btn.click()
    assert _visible_rows(page) == 5
    assert page.locator(".repeat-toggle:not([hidden])").inner_text() == "hide 3 repeats"

    page.locator(".repeat-toggle:not([hidden])").click()
    assert _visible_rows(page) == 2


def test_grouping_can_be_turned_off_entirely(page, tmp_path):
    doc = hr.build_html_report(_repeats_ctx(4), source_names=["a.pdf"], now=NOW)
    _load(page, doc, tmp_path)
    page.click("#findings-group-toggle")
    assert _visible_rows(page) == 5
    assert page.inner_text("#findings-group-note").strip() == ""
    page.click("#findings-group-toggle")
    assert _visible_rows(page) == 2


def test_grouping_recomputes_after_a_sort_so_no_follower_outlives_its_lead(page, tmp_path):
    # The lead of a group is whatever the reader's current sort put first. If
    # grouping were baked in at render time, sorting would strand followers with
    # no visible lead to expand them.
    doc = hr.build_html_report(_repeats_ctx(4), source_names=["a.pdf"], now=NOW)
    _load(page, doc, tmp_path)
    page.click("#findings th[data-sort='sheet']")
    assert _visible_rows(page) == 2
    assert page.locator(".repeat-toggle:not([hidden])").count() == 1
    # Whatever now leads the group is itself visible.
    assert page.eval_on_selector_all(
        ".repeat-toggle:not([hidden])",
        "els => els.every(e => !e.closest('.finding-row')"
        ".classList.contains('repeat-hidden'))",
    ) is True
    page.click("#findings th[data-sort='sheet']")   # flip direction
    assert _visible_rows(page) == 2


def test_search_reaches_a_finding_hidden_behind_its_group_lead(page, tmp_path):
    # Collapsing must never make a finding unfindable: a search that matches
    # only a follower promotes it to lead of the surviving set.
    doc = hr.build_html_report(_repeats_ctx(4), source_names=["a.pdf"], now=NOW)
    _load(page, doc, tmp_path)
    page.fill("#search", "plumbing on sheet 3")
    page.wait_for_timeout(200)
    assert _visible_rows(page) == 1
    row = page.locator(".finding-row:not(.hidden):not(.repeat-hidden)")
    assert "sheet 3" in row.inner_text()


def test_a_set_with_no_repeats_never_shows_the_grouping_control(page, tmp_path):
    doc = hr.build_html_report(_repeats_ctx(0), source_names=["a.pdf"], now=NOW)
    _load(page, doc, tmp_path)
    assert page.locator("#findings-group-toggle").count() == 0
    assert page.locator(".repeat-toggle").count() == 0
    assert _visible_rows(page) == 1


# --------------------------------------------------------------------------- #
# 8. Storage refusal: a browser that will not persist the key must not lose it,
#    and must never silently fall back to the author's key while claiming the
#    reader's is in use.
# --------------------------------------------------------------------------- #


_BREAK_SESSION_STORAGE = """
(function(){
  // Private mode / blocked site data: reads work, writes throw. This is the
  // shape that used to discard the key the reader had just typed.
  var real = window.sessionStorage.setItem.bind(window.sessionStorage);
  window.__stored = null;
  Storage.prototype.setItem = function(k, v){
    if(k === 'da-api-key') throw new DOMException('QuotaExceededError');
    return real(k, v);
  };
})();
"""


def test_entered_key_survives_a_browser_that_refuses_to_store_it(page, tmp_path):
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
    )
    page.add_init_script(_BREAK_SESSION_STORAGE)
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.fill("#da-chat-key-input", "sk-ant-readers-own-key")
    page.click("#da-chat-key-save")

    # The write was refused, but the key is held in memory and the panel is
    # usable — it must not drop back to the "enter a key" form.
    assert page.evaluate("sessionStorage.getItem('da-api-key')") is None
    assert page.is_visible("#da-chat-key-input") is False
    assert "API key set" in page.inner_text("#da-chat-key-set-label") or \
        "Using your API key" in page.inner_text("#da-chat-key-set-label")
    # And it says so honestly rather than promising sessionStorage.
    status = page.inner_text("#da-chat-key-status")
    assert "refused to store it" in status
    assert "sessionStorage" not in status


def test_storage_refusal_never_silently_bills_the_report_author(page, tmp_path):
    # The dangerous half: with an embedded key present, discarding the reader's
    # key let resolution fall back to the AUTHOR's while the panel claimed the
    # reader's key was in use — quietly billing the wrong person.
    doc = hr.build_html_report(
        _Ctx(sheets=[_Sheet(_Ref("a.pdf", 0, 1), text="x")], combined_text="x"),
        source_names=["a.pdf"], now=NOW,
        api_key="sk-ant-fake-not-real", embed_api_key=True,
    )
    page.add_init_script(_BREAK_SESSION_STORAGE)
    page.add_init_script("window.__SSE = " + json.dumps(_malicious_stream()) + ";")
    page.add_init_script(_FETCH_STUB)
    # Capture the key the request actually carries. This has to wrap the stub,
    # which replaces window.fetch wholesale — installing it first would leave
    # the capture dead and the assertion vacuous.
    page.add_init_script("""
      window.__sentKey = null;
      var stubbed = window.fetch;
      window.fetch = function(url, opts){
        try { window.__sentKey = (opts && opts.headers && opts.headers['x-api-key']) || null; } catch(e){}
        return stubbed.apply(this, arguments);
      };
    """)
    _load(page, doc, tmp_path)
    page.click("#da-chat-fab")
    page.click("#da-chat-key-change")
    page.fill("#da-chat-key-input", "sk-ant-readers-own-key")
    page.click("#da-chat-key-save")

    assert "Using your API key" in page.inner_text("#da-chat-key-set-label")
    # The claim on screen and the key on the wire must agree. The panel is
    # already open, so send directly rather than through _ask (which opens it).
    page.fill("#da-chat-input", "hi")
    page.click("#da-chat-send")
    page.wait_for_function(
        "() => { var b = document.getElementById(\'da-chat-send\');"
        " return b && !b.disabled && document.querySelector(\'.da-user\'); }",
        timeout=15000,
    )
    assert page.evaluate("window.__sentKey") == "sk-ant-readers-own-key"
    assert page.evaluate("window.__pwned") is False

    # Handing it back still works with storage broken.
    page.click("#da-chat-key-author")
    assert "embedded in this report" in page.inner_text("#da-chat-key-set-label")
