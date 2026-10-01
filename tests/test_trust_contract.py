"""Pin trust copy to shipped mechanisms, and exercise the actual native stack."""
from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
import re
import time
from xml.etree import ElementTree

import pytest

from drawing_analyzer import trust_dossier as trust
from drawing_analyzer import html_report
from drawing_analyzer.help_content import TRUST_SHORT_SOURCES, help_document

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/TRUST_CLAIMS.md"
SRC = ROOT / "src/drawing_analyzer"


def copy_text():
    return "\n".join(text for s in trust.sections() for b in s.blocks for text in trust.plain_blocks(b))


def test_runtime_inventory_is_complete():
    # IDs come from Phase 1's ledger, not from the implementation being tested.
    ledger = LEDGER.read_text()
    ids = re.findall(r"^\| ([UA]\d{2}) \|", ledger, re.M)
    cards = trust.runtime_cards()
    assert len(ids) == len(set(ids))
    assert [c.id for c in cards] == ids
    assert len({c.id for c in cards}) == len(cards)
    # Transport bookkeeping is local/non-model, but batch submission starts AI.
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT
    assert REVIEW_MODEL_DEFAULT in next(c for c in cards if c.id == "A05").ai
    for card in cards:
        assert tuple(label for label, _ in card.rows) == trust.RUNTIME_ROWS
        assert all(value.strip() for _label, value in card.rows)
        if card.ai == "None.":
            assert "AI involved: None." in trust.plain_blocks(card)
    refs = set(ids) | set(re.findall(r"^\| (N\d{2}) \|", ledger, re.M))
    for section in trust.sections():
        for block in section.blocks:
            assert block.refs and set(block.refs) <= refs
    for source_ids in TRUST_SHORT_SOURCES.values():
        assert set(source_ids) <= refs
    # Source symbols in the inventory must exist, not merely look plausible.
    for path, symbols in re.findall(r"`([^` :]+\.py): ([^`]+)`", ledger.split("<!-- BEGIN GENERATED")[0]):
        source = (SRC / path).read_text()
        for symbol in symbols.split(", "):
            symbol = symbol.split(" (")[0].split(" /")[0]
            if symbol.isidentifier():
                assert re.search(r"\b" + re.escape(symbol) + r"\b", source), (path, symbol)


def test_shipped_button_callbacks_have_inventory_sources():
    tree = ast.parse((SRC / "gui.py").read_text())
    callbacks = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "command" and isinstance(node.value, ast.Attribute):
            name = node.value.attr
            if name not in {"toggle", "_close_focus_popout", "_close_update_dialog"}:
                callbacks.add(name)
    ledger = LEDGER.read_text()
    assert callbacks
    assert all(callback in ledger for callback in callbacks)


def test_trust_facts(monkeypatch):
    # Unexported literals: compare with their actual request builders/SDK.
    from anthropic import Anthropic
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    client = Anthropic(api_key="test-contract-no-network")
    p = trust.PINNED_FACTS
    assert client.base_url.host == p["api_host"]
    assert client.max_retries == p["sdk_retries"]
    assert client.timeout.connect == p["sdk_connect_seconds"]
    assert client.timeout.read == client.timeout.write == client.timeout.pool == p["sdk_read_seconds"]
    js = html_report._CHAT_JS
    for fact_name, symbol in (("chat_continuations", "MAX_CONTINUATIONS"), ("chat_tool_rounds", "MAX_TOOL_ROUNDS"), ("chat_storage_chars", "TX_MAX_CHARS")):
        assert int(re.search(r"var " + symbol + r" = (\d+)", js)[1]) == p[fact_name]
    assert f"https://{p['api_host']}/v1/messages" in js
    assert f"name: 'web_search', max_uses: {p['chat_searches']}" in js
    assert f"name: 'web_fetch', max_uses: {p['chat_fetches']}" in js
    assert f"max_content_tokens: {p['chat_fetch_tokens']}" in js
    assert "toolRound > MAX_TOOL_ROUNDS" in js  # pins the documented off-by-one
    from drawing_analyzer import verify
    assert verify.verify_findings.__kwdefaults__["dpi"] == p["verify_dpi"]
    assert verify.verify_cross_findings.__kwdefaults__["dpi"] == p["verify_dpi"]

    trust.sections()  # resolves FACT_SOURCES
    ledger = LEDGER.read_text()
    for source in trust.FACT_SOURCES:
        module, name = source.rsplit(".", 1)
        assert hasattr(importlib.import_module("drawing_analyzer." + module), name)
        assert name in ledger, f"unledgered numerical source {source}"


def test_every_quoted_number_has_evidence():
    """Catch a newly hand-written figure outside source facts and pinned literals."""
    short = help_document("why_trust_it")
    short_copy = short.intro + " ".join(s.heading + " ".join(b.text for b in s.blocks) for s in short.sections)
    text = re.sub(r"\b[UA]\d{2}\b", "", copy_text() + short_copy)
    allowed_values = list(trust.PINNED_FACTS.values())
    allowed_values.extend(trust.fact(s) for s in tuple(trust.FACT_SOURCES))
    from drawing_analyzer.core import api_config, pricing
    allowed_values.extend(api_config._MODEL_CAPABILITIES)
    for caps in api_config._MODEL_CAPABILITIES.values():
        allowed_values.extend((caps.max_output_tokens, caps.context_window))
    for price in pricing.MODEL_PRICING.values():
        allowed_values.extend((price.input_per_mtok, price.output_per_mtok, price.cache_read_multiplier))
    # Config booleans, SHA-256 algorithm name, unit conversions and millions
    # are defined/pinned by the tests below and the ledger's source tables.
    allowed_values.extend((0, 1, 256))
    for source in ("batch_digest.DEFAULT_FIRST_BATCH_STALL_TIMEOUT_SECONDS", "batch_digest.DEFAULT_BATCH_STALL_TIMEOUT_SECONDS"):
        allowed_values.append(trust.fact(source) // 60)
    allowed_values.append(trust.fact("tiling.DEFAULT_OVERLAP_FRAC") * 100)
    def numbers(value):
        return set(re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", "")))
    allowed = set().union(*(numbers(v) for v in allowed_values))
    quoted = numbers(text)
    # Filenames/profile key patterns and view IDs are structural identifiers.
    assert quoted <= allowed, f"numbers without a source: {quoted - allowed}"


def test_trust_switches_and_unused_token_count(monkeypatch):
    from drawing_analyzer.core import updates
    from drawing_analyzer import digest_cache, pipeline
    monkeypatch.setenv("DRAWING_ANALYZER_DISABLE_UPDATE_CHECK", "1")
    assert updates.update_check_disabled()
    monkeypatch.setenv("DRAWING_ANALYZER_CACHE_PERSIST", "0")
    assert not digest_cache.persistence_enabled()
    monkeypatch.setenv("DRAWING_ANALYZER_WORKDIR_MAX_AGE_HOURS", "0")
    assert pipeline._workdir_max_age_seconds() == 0
    # Source scan excludes the helper definition, docs and tests; no claimed
    # token-count preflight may quietly become an undisclosed network action.
    callers = []
    for path in SRC.rglob("*.py"):
        if path.name.startswith("trust_"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                if name == "count_tokens_via_api":
                    callers.append(path.name)
    assert not callers


def test_models_hosts_settings_and_switches_in_copy_have_real_sources():
    text = copy_text()
    # Exact identifiers and configuration switches cannot be invented in prose.
    implementation = "\n".join(p.read_text() for p in SRC.rglob("*.py") if not p.name.startswith("trust_") and p.name != "help_content.py")
    for setting in set(re.findall(r"(?:DRAWING_ANALYZER|ANTHROPIC)_[A-Z_]+", text)):
        assert setting in implementation
    from drawing_analyzer.core import api_config
    for model in set(re.findall(r"claude-[a-z0-9-]+", text)):
        assert model in api_config._MODEL_CAPABILITIES
    # The auth header claim is fixed by production browser request code.
    assert "'x-api-key': apiKey" in html_report._CHAT_JS
    # The default GUI, unlike the library, enables synthesis and uses the queue.
    gui = (SRC / "gui.py").read_text()
    assert "synthesize=True" in gui and "value=PROCESSING_MODE_ECONOMY" in gui
    from urllib.parse import urlsplit
    from drawing_analyzer.help_content import HELP_DOCUMENTS, GET_API_KEY
    help_hosts = {urlsplit(b.href).hostname for doc in (*HELP_DOCUMENTS, GET_API_KEY)
                  for section in doc.sections for b in section.blocks if b.href}
    boundary = next(s for s in trust.sections() if s.id == "boundary")
    boundary_text = " ".join(t for b in boundary.blocks for t in trust.plain_blocks(b))
    assert all(host in boundary_text for host in help_hosts)


def test_short_topic_has_eight_mechanisms_and_exact_button():
    doc = help_document("why_trust_it")
    assert len(doc.sections[:-1]) == len(TRUST_SHORT_SOURCES) == 8
    assert len((doc.intro + " ".join(s.heading + " ".join(b.text for b in s.blocks) for s in doc.sections)).split()) <= 380
    for section in doc.sections[:-1]:
        assert 5 <= len(section.heading.split()) <= 8
        assert all(b.kind == "para" for b in section.blocks)
    last = doc.sections[-1]
    assert last.heading == "Not convinced?"
    assert last.blocks[0].text == "Fair. The points above are claims — here is the mechanism behind each one, action by action, plus how to audit any of it yourself."
    assert last.blocks[1].text == "I'm not convinced — show me exactly what runs →"
    assert last.blocks[1].doc_key == "runtime_transparency"


def test_trust_loads_no_external_assets():
    from html.parser import HTMLParser
    class Audit(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            assert tag not in {"img", "iframe", "object", "embed", "link", "script"}
            assert "src" not in attributes
            if "href" in attributes and not attributes["href"].startswith("#"):
                assert tag == "a" and attributes["href"].startswith("https://")
    Audit().feed(trust.render_html())
    svg = ElementTree.fromstring(trust.BOUNDARY_SVG)
    assert svg.attrib["aria-label"] == trust.DIAGRAM_DESCRIPTION
    assert svg.attrib["role"] == "img"
    assert any("stroke-dasharray" in element.attrib for element in svg)
    assert all(e.tag.rsplit("}", 1)[-1] in {"svg", "rect", "line", "text"} for e in svg.iter())
    native = (SRC / "trust_ui.py").read_text()
    assert not re.search(r"urlopen|requests|fetch\(|PhotoImage|Image\.open", native)


def test_generated_docs_match_content_and_ledger():
    assert (ROOT / "docs/TRUST.html").read_text() == trust.render_html()
    from drawing_analyzer.trust_contract_docs import ledger_copy_map
    ledger = LEDGER.read_text()
    assert ledger_copy_map() in ledger


@pytest.mark.browser
@pytest.mark.parametrize("theme,width", (("light", 1440), ("dark", 1440), ("light", 375), ("dark", 375)))
def test_portable_trust_page_themes_reflow_and_no_requests(theme, width, tmp_path):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright
    from tests.test_report_browser_security import _launch
    path = tmp_path / "trust.html"
    path.write_text(trust.render_html())
    with sync_playwright() as p:
        try:
            browser = _launch(p)
        except Exception as exc:
            pytest.skip(f"headless Chromium unavailable: {exc}")
        try:
            page = browser.new_page(viewport={"width": width, "height": 950}, color_scheme=theme)
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.goto(path.as_uri())
            assert requests == [path.as_uri()]
            assert page.evaluate("document.documentElement.scrollWidth") <= width
            assert page.locator("h1").bounding_box()["height"] > 0
            assert page.locator("main section").count() == len(trust.sections())
            assert page.locator("article.runtime").count() == len(trust.runtime_cards())
            for card in page.locator("article.runtime").all():
                assert card.locator("dt").all_text_contents() == list(trust.RUNTIME_ROWS)
            if width > 760:
                assert page.locator("nav").evaluate("e => getComputedStyle(e).position") == "sticky"
            assert page.locator("body").evaluate("e => getComputedStyle(e).color !== getComputedStyle(e).backgroundColor")
        finally:
            browser.close()


@pytest.fixture
def native_app(monkeypatch, tmp_path):
    # CI can run this under its own X server; do not pretend a missing display
    # tested keyboard behavior. The work report states the native result.
    if not os.environ.get("DISPLAY") and os.name != "nt":
        pytest.skip("native keyboard test requires a display (use Xvfb/Xorg)")
    pytest.importorskip("customtkinter")
    import tkinter as tk
    try:
        root = tk.Tk(); root.destroy()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    from drawing_analyzer.gui import DrawingAnalyzerApp
    monkeypatch.setenv("DRAWING_ANALYZER_DISABLE_UPDATE_CHECK", "1")
    monkeypatch.setattr(DrawingAnalyzerApp, "_load_api_key", lambda self: "")
    # Avoid reading/writing the operator's credential store; no Analyze invoked.
    monkeypatch.setattr(DrawingAnalyzerApp, "_report_key_at_startup", lambda self: None)
    app = DrawingAnalyzerApp()
    callback_errors = []
    # Surface callback failures as test failures instead of blocking on an
    # interactive error dialog while the test waits for Tk to finish updating.
    app.report_callback_exception = lambda _type, error, _traceback: callback_errors.append(error)
    def pump():
        until = time.monotonic() + .25
        while time.monotonic() < until:
            app.update(); time.sleep(.005)
        assert not callback_errors, callback_errors
    app._test_pump = pump
    pump()
    yield app
    app.destroy()


def test_native_two_levels_focus_escape_and_contents(native_app):
    app = native_app
    def widgets(root):
        for widget in root.winfo_children():
            yield widget
            yield from widgets(widget)
    import customtkinter as ctk
    header = next(w for w in widgets(app) if isinstance(w, ctk.CTkButton) and w.cget("text") == "Why trust it?")
    header.invoke()
    app._test_pump()
    parent = app._help_windows["why_trust_it"]
    opener = app._help_focus_targets["why_trust_it"][0]
    assert opener.cget("text") == "I'm not convinced — show me exactly what runs →"
    # Tab to the off-screen action must reveal it before keyboard activation.
    app._help_focus_targets["why_trust_it"][-1].focus_set(); app.update()
    app._help_tab("why_trust_it", None); app._test_pump()
    body = opener.master
    canvas = body._parent_canvas
    assert canvas.winfo_rooty() <= opener.winfo_rooty() < canvas.winfo_rooty() + canvas.winfo_height()
    opener.invoke()
    app._test_pump()
    child = app._help_windows["runtime_transparency"]
    view = child._dossier_view
    assert parent.winfo_exists() and child.winfo_exists()
    assert str(child.transient()) == str(parent)
    assert app.grab_current() is child
    assert str(app.focus_get()).startswith(str(child))
    assert child.winfo_height() <= child.winfo_screenheight() * .88 + 2
    # CTk's setter-only override raises when called as a getter; inspect Tk.
    assert child.tk.call("wm", "maxsize", str(child))[1] <= child.winfo_screenheight() * .88
    assert len(view.marks) == 12
    view.jump("section_audit")
    app._test_pump()
    assert view.current == 11
    # Wrap forwards/backwards, retaining focus in the top dialog.
    targets = [w for w in app._help_focus_targets["runtime_transparency"] if w.winfo_ismapped()]
    targets[-1].focus_set(); app.update()
    app._help_tab("runtime_transparency", None); app.update()
    assert app.focus_get() is targets[0]
    app._help_tab("runtime_transparency", None, backwards=True); app.update()
    assert str(app.focus_get()).startswith(str(targets[-1]))
    child.event_generate("<Escape>"); app.update()
    assert "runtime_transparency" not in app._help_windows
    assert parent.winfo_exists() and app.grab_current() is parent
    assert str(app.focus_get()).startswith(str(opener))
    parent.event_generate("<Escape>"); app.update()
    assert "why_trust_it" not in app._help_windows
    assert str(app.focus_get()).startswith(str(header))


def test_native_narrow_reflow_keeps_all_sections(native_app):
    app = native_app
    app._open_help_modal(help_document("runtime_transparency"))
    app._test_pump()
    win = app._help_windows["runtime_transparency"]
    view = win._dossier_view
    win.geometry("540x600")
    app._test_pump()
    assert not view.rail.winfo_ismapped()
    assert len(view.marks) == 12
    assert len(view.text.mark_names()) >= len(trust.runtime_cards())
    view.jump("section_audit"); app._test_pump()
    assert view.current == 11
    for frame, labels, _cols in view.windows:
        # Tk retains the last actual geometry of an off-screen embedded window.
        assert frame.winfo_reqwidth() <= view.text.winfo_width()
        assert all(int(label.cget("wraplength")) <= view.text.winfo_width() for label in labels)
    for _kind, _window, index in view.text.dump("1.0", "end", window=True):
        view.text.yview(index)
        app._test_pump()
        widget = view.text.nametowidget(_window)
        assert widget.winfo_width() <= view.text.winfo_width()


@pytest.mark.parametrize("scale", (1.5, 2.0))
def test_native_scaled_dialog_stays_inside_screen(native_app, scale):
    import customtkinter as ctk
    app = native_app
    try:
        ctk.set_window_scaling(scale)
        app._open_help_modal(help_document("runtime_transparency"))
        app._test_pump()
        win = app._help_windows["runtime_transparency"]
        assert win.winfo_width() <= win.winfo_screenwidth() * .92 + 2
        assert win.winfo_height() <= win.winfo_screenheight() * .88 + 2
        assert win.tk.call("wm", "maxsize", str(win))[1] <= win.winfo_screenheight() * .88
    finally:
        ctk.set_window_scaling(1.0)


@pytest.mark.parametrize("doc_key", ("how_to_use", "about"))
@pytest.mark.parametrize("scale", (1.0, 2.0))
def test_native_standard_help_reflows_bullets_and_links(native_app, monkeypatch, doc_key, scale):
    import customtkinter as ctk
    app = native_app
    doc = help_document(doc_key)
    # Screen-bounded sizing can open below the former 520 logical-pixel floor.
    monkeypatch.setattr(ctk.CTkToplevel, "winfo_screenwidth", lambda self: 480)
    try:
        ctk.set_window_scaling(scale)
        ctk.set_widget_scaling(scale)
        app._open_help_modal(doc)
        app._test_pump()
        win = app._help_windows[doc_key]
        assert win.winfo_width() <= 480 * .92 + 2

        def widgets(root):
            for widget in root.winfo_children():
                yield widget
                yield from widgets(widget)

        body = next(w for w in widgets(win) if isinstance(w, ctk.CTkScrollableFrame))
        labels = [w for w in widgets(body) if isinstance(w, ctk.CTkLabel)]
        for section in doc.sections:
            for block in section.blocks:
                if block.kind not in {"para", "bullet", "link"}:
                    continue
                label = next(w for w in labels if w.cget("text") == block.text)
                canvas = body._parent_canvas
                # Check text's requested size: pack can shrink its container
                # while silently clipping the internal label's unwrapped text.
                assert label._label.winfo_reqwidth() <= label.winfo_width() + 2
                assert label.winfo_rootx() >= canvas.winfo_rootx()
                assert label.winfo_rootx() + label.winfo_width() <= canvas.winfo_rootx() + canvas.winfo_width() + 2
    finally:
        app._close_help_modal(doc_key)
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)
