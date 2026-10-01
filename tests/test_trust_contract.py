"""Native help focus, screen bounds and reflow; no provider calls."""
from __future__ import annotations

import os
import time

import pytest

from drawing_analyzer.help_content import help_document


def widgets(root):
    for widget in root.winfo_children():
        yield widget
        yield from widgets(widget)


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


def test_native_trust_help_keyboard_link_and_escape(native_app, monkeypatch):
    import customtkinter as ctk
    app = native_app
    opener = next(w for w in widgets(app)
                  if isinstance(w, ctk.CTkButton) and w.cget("text") == "Why trust it?")
    opener.invoke()
    app._test_pump()
    win = app._help_windows["why_trust_it"]
    assert app.grab_current() is win
    link, close = app._help_focus_targets["why_trust_it"]
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    app._help_tab("why_trust_it", None)
    app._test_pump()
    assert app.focus_get() is link
    canvas = link.master.master._parent_canvas
    assert canvas.winfo_rooty() <= link.winfo_rooty() < canvas.winfo_rooty() + canvas.winfo_height()
    for sequence in ("<Return>", "<space>"):
        link.event_generate(sequence)
        app.update()
    assert opened == [help_document("why_trust_it").sections[-1].blocks[-1].href] * 2
    app._help_tab("why_trust_it", None)
    assert str(app.focus_get()).startswith(str(close))
    app._open_help_modal(help_document("why_trust_it"))
    assert app._help_windows["why_trust_it"] is win
    win.event_generate("<Escape>")
    app.update()
    assert "why_trust_it" not in app._help_windows
    assert app.grab_current() is None
    assert str(app.focus_get()).startswith(str(opener))


@pytest.mark.parametrize("scale", (1.5, 2.0))
def test_native_scaled_dialog_stays_inside_screen(native_app, scale):
    import customtkinter as ctk
    app = native_app
    try:
        ctk.set_window_scaling(scale)
        app._open_help_modal(help_document("why_trust_it"))
        app._test_pump()
        win = app._help_windows["why_trust_it"]
        assert win.winfo_width() <= win.winfo_screenwidth() * .92 + 2
        assert win.winfo_height() <= win.winfo_screenheight() * .88 + 2
        assert win.tk.call("wm", "maxsize", str(win))[1] <= win.winfo_screenheight() * .88
    finally:
        ctk.set_window_scaling(1.0)


@pytest.mark.parametrize("doc_key", ("how_to_use", "why_trust_it", "about"))
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
