"""P9 items 47 and N32 — the three ways the shipped GUI failed silently.

The launcher is declared under ``[project.gui-scripts]``, which on Windows means
a console-less executable, and the frozen PyInstaller build is windowed for the
same reason. Anything written to ``sys.stdout``/``sys.stderr`` therefore goes
nowhere, which turned three ordinary failures into "the app did nothing":

* an ``import customtkinter`` failure (the toolkit lives in the ``gui`` extra, so
  ``pip install drawing-analyzer`` installs a launcher that cannot start) — item 47;
* clicking the window's X during a run: the worker threads are daemons and the
  export happens *after* the analysis returns, so a paid run vanished with no
  prompt, while the help, focus-popout and update windows each already confirmed
  on close — item 47;
* an exception inside a Tk callback: Tk's default handler prints a traceback to
  the stderr that does not exist — N32.

Hermetic: ``tkinter`` is not installed in the test environment at all, so these
inject a minimal fake toolkit (enough for ``drawing_analyzer.gui`` to import) and
drive the handlers with a stub ``self``. No window is ever created.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import types

import pytest


def _fake_tkinter() -> types.ModuleType:
    tk = types.ModuleType("tkinter")

    class _Var:
        def __init__(self, value=None):
            self._v = value

        def get(self):
            return self._v

        def set(self, v):
            self._v = v

        def trace_add(self, *a, **k):
            pass

    tk.BooleanVar = tk.StringVar = _Var
    tk.filedialog = types.SimpleNamespace()
    tk.messagebox = types.SimpleNamespace()
    return tk


@contextlib.contextmanager
def _gui_module(ctk: types.ModuleType | None = None):
    """Import ``drawing_analyzer.gui`` against a fake toolkit, then restore."""
    tk = _fake_tkinter()
    if ctk is None:
        ctk = types.ModuleType("customtkinter")

        class _CTk:
            def __init__(self, *a, **k):
                pass

        ctk.CTk = _CTk
    names = {
        "tkinter": tk,
        "tkinter.filedialog": tk.filedialog,
        "tkinter.messagebox": tk.messagebox,
        "customtkinter": ctk,
    }
    saved = {n: sys.modules.get(n) for n in (*names, "drawing_analyzer.gui")}
    sys.modules.update(names)
    sys.modules.pop("drawing_analyzer.gui", None)
    try:
        yield importlib.import_module("drawing_analyzer.gui"), tk
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


# --------------------------------------------------------------------------- #
# item 47a — a missing GUI toolkit must say so, not exit silently
# --------------------------------------------------------------------------- #


class _ExplodingCustomTkinter(types.ModuleType):
    """A ``customtkinter`` whose import raises, as a broken install's would."""

    def __getattr__(self, name):
        raise ModuleNotFoundError("No module named 'customtkinter'")


def test_missing_customtkinter_reports_instead_of_dying_quietly():
    shown: list[tuple[str, str]] = []

    tk = _fake_tkinter()
    tk.messagebox.showerror = lambda title, message, **kw: shown.append((title, message))
    ctk_broken = types.ModuleType("customtkinter")

    names = {
        "tkinter": tk,
        "tkinter.filedialog": tk.filedialog,
        "tkinter.messagebox": tk.messagebox,
    }
    saved = {n: sys.modules.get(n) for n in (*names, "customtkinter", "drawing_analyzer.gui")}
    sys.modules.update(names)
    # Make the import itself fail, the way a missing/broken wheel does.
    sys.modules["customtkinter"] = None       # None => ImportError on import
    sys.modules.pop("drawing_analyzer.gui", None)
    try:
        with pytest.raises(ImportError) as failure:
            importlib.import_module("drawing_analyzer.gui")
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        del ctk_broken

    # The user gets a dialog — the only channel a console-less build has...
    assert shown, "no messagebox was shown for a missing GUI toolkit"
    title, message = shown[0]
    assert "cannot start" in title.lower()
    # ...and it names the fix, not just the failure.
    assert 'pip install "drawing-analyzer[gui]"' in message
    # ...and the raised error is an ImportError, NOT SystemExit: app_entry.py's
    # --selfcheck catches Exception, and SystemExit would sail straight past it
    # and report a successful self-check.
    assert 'pip install "drawing-analyzer[gui]"' in str(failure.value)


def test_the_toolkit_reporter_survives_a_dead_display():
    """No display, or a broken tkinter: still returns an error to raise."""
    with _gui_module() as (gui, tk):
        def boom(*a, **k):
            raise RuntimeError("no display")

        tk.messagebox.showerror = boom
        error = gui._gui_toolkit_unavailable(ModuleNotFoundError("customtkinter"))
    assert isinstance(error, ImportError)
    assert "customtkinter" in str(error)


# --------------------------------------------------------------------------- #
# item 47b — closing the window mid-run must confirm first
# --------------------------------------------------------------------------- #


def test_describe_busy_names_the_job_in_flight():
    with _gui_module() as (gui, _tk):
        assert gui._describe_busy(False, False) == ""
        assert "analysis" in gui._describe_busy(True, False)
        assert "export" in gui._describe_busy(False, True)
        both = gui._describe_busy(True, True)
        assert "analysis" in both and "export" in both


def _stub_app(gui, *, busy=False, export_busy=False):
    destroyed: list[bool] = []
    stub = types.SimpleNamespace(
        _busy=busy, _export_busy=export_busy,
        destroy=lambda: destroyed.append(True),
    )
    return stub, destroyed


def test_closing_while_idle_closes_immediately():
    """This is a guard, not a ceremony: a quiet window must not prompt."""
    with _gui_module() as (gui, tk):
        asked: list[str] = []
        tk.messagebox.askyesno = lambda *a, **k: asked.append("asked") or True
        stub, destroyed = _stub_app(gui)
        gui.DrawingAnalyzerApp._on_close_request(stub)
    assert destroyed == [True]
    assert not asked


@pytest.mark.parametrize(
    "busy,export_busy", [(True, False), (False, True), (True, True)]
)
def test_closing_mid_run_asks_first_and_can_be_cancelled(busy, export_busy):
    with _gui_module() as (gui, tk):
        tk.messagebox.askyesno = lambda *a, **k: False        # "no, keep working"
        stub, destroyed = _stub_app(gui, busy=busy, export_busy=export_busy)
        gui.DrawingAnalyzerApp._on_close_request(stub)
        assert destroyed == [], "the run was discarded despite the user saying no"

        tk.messagebox.askyesno = lambda *a, **k: True         # "yes, quit anyway"
        stub, destroyed = _stub_app(gui, busy=busy, export_busy=export_busy)
        gui.DrawingAnalyzerApp._on_close_request(stub)
        assert destroyed == [True], "the user said quit and the window stayed open"


def test_the_close_prompt_says_what_quitting_costs():
    """A prompt that does not say why is a prompt the user clicks through."""
    seen: list[dict] = []
    with _gui_module() as (gui, tk):
        def record(title, message, **kw):
            seen.append({"title": title, "message": message, **kw})
            return False

        tk.messagebox.askyesno = record
        stub, _ = _stub_app(gui, busy=True)
        gui.DrawingAnalyzerApp._on_close_request(stub)
    assert seen
    message = seen[0]["message"]
    assert "discards" in message
    assert "billed" in message                    # the money, said out loud
    assert seen[0].get("default") == "no"         # X should not default to losing it


def test_a_broken_dialog_cannot_trap_the_user_in_the_window():
    with _gui_module() as (gui, tk):
        def boom(*a, **k):
            raise RuntimeError("no display")

        tk.messagebox.askyesno = boom
        stub, destroyed = _stub_app(gui, busy=True)
        gui.DrawingAnalyzerApp._on_close_request(stub)
    assert destroyed == [True]


# --------------------------------------------------------------------------- #
# N32 — a Tk callback exception must reach the user and the trace
# --------------------------------------------------------------------------- #


def test_callback_exception_is_logged_shown_and_non_fatal(monkeypatch):
    with _gui_module() as (gui, tk):
        shown: list[str] = []
        logged: list[tuple] = []
        tk.messagebox.showerror = lambda title, message, **kw: shown.append(message)

        class _Logger:
            def error(self, msg, exc_info=None):
                logged.append((msg, exc_info))

        # monkeypatch, not assignment: ``diagnostics`` is the one shared module
        # object, so a bare assignment here poisoned every later import of
        # drawing_analyzer.gui in the same session (it did, for 11 tests).
        monkeypatch.setattr(gui.diagnostics, "get_logger", lambda: _Logger())
        activity: list[str] = []
        stub = types.SimpleNamespace(_log=lambda m, **k: activity.append(m))
        try:
            raise ValueError("widget exploded")
        except ValueError as exc:
            info = (type(exc), exc, exc.__traceback__)
        # Non-fatal, exactly like Tk's own handler: it must not re-raise.
        gui.DrawingAnalyzerApp._on_callback_exception(stub, *info)

    assert logged and logged[0][1][0] is ValueError
    assert activity and "widget exploded" in activity[0]
    assert shown and "widget exploded" in shown[0]
    assert "still running" in shown[0]


def test_callback_reporter_survives_every_channel_failing(monkeypatch):
    """The reporter of last resort must never raise from inside Tk's handler."""
    with _gui_module() as (gui, tk):
        def boom(*a, **k):
            raise RuntimeError("gone")

        tk.messagebox.showerror = boom
        monkeypatch.setattr(gui.diagnostics, "get_logger", boom)
        stub = types.SimpleNamespace(_log=boom)
        gui.DrawingAnalyzerApp._on_callback_exception(
            stub, ValueError, ValueError("x"), None
        )


# --------------------------------------------------------------------------- #
# both hooks must actually be wired onto the MAIN window
# --------------------------------------------------------------------------- #


def test_the_main_window_wires_both_hooks_in_init():
    """Structural: the handlers are worthless unbound.

    Asserted against ``__init__``'s source rather than by constructing the app,
    which needs a real display. The three secondary windows already called
    ``protocol("WM_DELETE_WINDOW", …)``; the main one is the one that did not, so
    counting call sites is exactly what this has to check.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "src" / "drawing_analyzer" / "gui.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    app = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "DrawingAnalyzerApp"
    )
    init = next(
        n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"
    )
    init_src = ast.unparse(init)
    assert "self.protocol('WM_DELETE_WINDOW', self._on_close_request)" in init_src
    assert "self.report_callback_exception = self._on_callback_exception" in init_src


# --------------------------------------------------------------------------- #
# WP-16.1 (G3) — the key field shows, applies and saves the normalized key
# --------------------------------------------------------------------------- #

# Built at runtime: a literal ``sk-ant-`` followed by 30 key characters is what
# scripts/scan_secrets.py (run by CI) refuses.
_KEY = "sk-ant-api03-" + "A" * 86 + "AA"
_BOM = "\ufeff"


class _TclVar:
    """A ``StringVar`` whose write traces run the way Tcl runs them.

    Each ``set`` runs the variable's write traces once, and a ``set`` made
    while one of its traces is running runs none (Tcl disables a variable's
    traces while one is active; measured with Tk 8.6 and customtkinter 6.0.0
    under Xvfb). ``reenter=True`` models a toolkit that does re-run them, to
    show the field rewrite stops after one level anyway.
    """

    def __init__(self, value: str = "", *, reenter: bool = False):
        self._value = value
        self._traces: list = []
        self._active = False
        self.reenter = reenter
        self.callbacks = 0

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        if self._active and not self.reenter:
            return
        previous, self._active = self._active, True
        try:
            for callback in self._traces:
                self.callbacks += 1
                callback()
        finally:
            self._active = previous

    def trace_add(self, _mode, callback):
        self._traces.append(callback)


def _key_stub(gui, var, *, persisted=""):
    statuses: list[str] = []
    logs: list[tuple[str, str]] = []
    stub = types.SimpleNamespace(
        _key_var=var, _persisted_key=persisted, _has_key=False,
        _set_key_status=lambda text, _color: statuses.append(text),
        _log=lambda message, level="info": logs.append((message, level)),
    )
    var.trace_add("write", lambda *_a: gui.DrawingAnalyzerApp._on_key_changed(stub))
    return stub, statuses, logs


@pytest.mark.parametrize("reenter", [False, True])
def test_the_key_field_shows_applies_and_saves_the_normalized_key(monkeypatch, reenter):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    saved: list[str] = []
    with _gui_module() as (gui, _tk):
        monkeypatch.setattr(gui, "save_api_key", lambda key, **_kw: saved.append(key))
        var = _TclVar(reenter=reenter)
        stub, statuses, _logs = _key_stub(gui, var)

        var.set(_BOM + _KEY + " \r\n")            # a paste from a "UTF-8 with BOM" file

        assert var.get() == _KEY                  # the field shows what is used
        assert var.callbacks <= 2                 # one level, even if re-entered
        assert os.environ["ANTHROPIC_API_KEY"] == _KEY
        assert stub._has_key is True

        gui.DrawingAnalyzerApp._persist_key(stub)

    assert saved == [_KEY]
    assert stub._persisted_key == _KEY
    assert statuses[-1] == "saved"


def test_a_clean_key_is_not_rewritten_in_the_field(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with _gui_module() as (gui, _tk):
        var = _TclVar()
        _key_stub(gui, var)
        var.set(_KEY)
    assert var.get() == _KEY and var.callbacks == 1


def test_a_field_holding_only_invisible_characters_is_no_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    with _gui_module() as (gui, _tk):
        var = _TclVar()
        stub, statuses, _logs = _key_stub(gui, var)
        var.set(_BOM + "\u200b ")
    assert var.get() == ""
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert stub._has_key is False and statuses[-1] == "no key"


def test_saving_a_value_that_is_not_a_key_says_so_without_the_value(monkeypatch):
    from drawing_analyzer.core import api_key_store

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(api_key_store, "_KEYRING_AVAILABLE", False)
    monkeypatch.setattr(api_key_store, "_keyring", None)
    typed = _KEY + " my work key"
    with _gui_module() as (gui, tk):
        tk.messagebox.askyesno = lambda *a, **k: pytest.fail("no consent dialog")
        var = _TclVar()
        stub, statuses, logs = _key_stub(gui, var)
        var.set(typed)
        gui.DrawingAnalyzerApp._persist_key(stub)

    assert statuses[-1] == "not saved"
    assert stub._persisted_key == ""
    assert logs and all("A" * 20 not in m and "work key" not in m for m, _ in logs)
    assert "sk-ant-" in logs[-1][0]


def test_startup_loads_the_normalized_key_and_keeps_the_notes(tmp_path, monkeypatch):
    from drawing_analyzer.core import api_key_store

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = tmp_path / "drawing_analyzer_api_key.txt"
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [config])
    monkeypatch.setattr(api_key_store, "_KEYRING_AVAILABLE", False)
    monkeypatch.setattr(api_key_store, "_keyring", None)
    config.write_bytes(b"\xef\xbb\xbf" + _KEY.encode())
    with _gui_module() as (gui, _tk):
        stub = types.SimpleNamespace()
        key = gui.DrawingAnalyzerApp._load_api_key(stub)
        assert key == _KEY and os.environ["ANTHROPIC_API_KEY"] == _KEY
        assert stub._key_load_notes == ()

        config.write_text("hello world", encoding="utf-8")
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        assert gui.DrawingAnalyzerApp._load_api_key(stub) == ""
        assert "ANTHROPIC_API_KEY" not in os.environ
        assert len(stub._key_load_notes) == 1
        assert str(config) in stub._key_load_notes[0].text


@pytest.mark.parametrize("has_key", [False, True])
def test_the_startup_status_shows_the_key_notes_in_the_activity_log(has_key):
    from drawing_analyzer.core.api_key_store import KeyNote

    notes = (
        KeyNote("Key file not used: C:/x/drawing_analyzer_api_key.txt ...", True),
        KeyNote("The API key in the OS keyring was cleaned and saved again.", False),
    )
    with _gui_module() as (gui, _tk):
        statuses: list[str] = []
        logs: list[tuple[str, str]] = []
        stub = types.SimpleNamespace(
            _has_key=has_key, _key_load_notes=notes,
            _set_key_status=lambda text, _color: statuses.append(text),
            _log=lambda message, level="info": logs.append((message, level)),
        )
        gui.DrawingAnalyzerApp._report_key_at_startup(stub)

    assert logs[:2] == [(notes[0].text, "warning"), (notes[1].text, "muted")]
    assert statuses == (["loaded"] if has_key else ["no key"])
    assert len(logs) == 3                         # then today's one summary line
