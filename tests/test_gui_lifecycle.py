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
import tempfile
import threading
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
        assert stub._applied_key == _KEY          # WP-16.2: the app holds it,
        assert "ANTHROPIC_API_KEY" not in os.environ   # never the environment
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
    assert stub._applied_key == ""
    assert os.environ["ANTHROPIC_API_KEY"] == "placeholder"   # WP-16.2: untouched
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
        assert key == _KEY and "ANTHROPIC_API_KEY" not in os.environ   # WP-16.2
        assert stub._key_load_notes == ()

        config.write_text("hello world", encoding="utf-8")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
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


# --------------------------------------------------------------------------- #
# WP-16.2 (G2) — a run keeps the key it started with; the key never reaches
# os.environ, so no later stage and no child process can see an edit
# --------------------------------------------------------------------------- #
#
# The owner's rules (three rounds, measured first): Analyze reads the applied key
# (the normalized field value) once, before the cost dialog; the worker builds one
# real SDK client from it with ``client.new_client`` and passes ``client=`` to
# ``extract_drawing_context``; the GUI never writes ANTHROPIC_API_KEY, and one
# inherited at launch pre-fills the field (normalized, with a value-free warning
# when it is not an ``sk-ant-`` key) and is then removed from the environment;
# the exports embed the applied key (the store fallback is WP-16.3's); the key
# entry (not Show) is locked while an analysis runs, beside the status word
# "locked while analyzing", and unlocked on every exit.


_KEY_B = "sk-ant-api03-" + "B" * 86 + "BB"
_LOCKED = "locked while analyzing"


def _key_class(value) -> str:
    """A key as a class label, so neither a failure message nor a test id ever
    carries a key value."""
    if value is None:
        return "none"
    return {_KEY: "key A", _KEY_B: "key B", _KEY[:-1]: "truncated", "": "empty"}.get(
        value, "other"
    )


def _child_sees_a_key() -> bool:
    return "ANTHROPIC_API_KEY" in os.environ


class _Widget:
    def __init__(self) -> None:
        self.state = "normal"
        self.options: dict = {}

    def configure(self, **kw):
        if "state" in kw:
            self.state = kw["state"]
        self.options.update(kw)

    def cget(self, name):
        return self.options.get(name)


_WIDGETS = ("analyze_btn", "clear_btn", "html_btn", "reviewed_btn", "export_btn",
            "upload_specs_btn", "key_entry", "key_show_btn", "key_status_label",
            "progress_label")
_BOUND = ("_worker", "_on_done", "_on_error", "_set_key_status", "_on_key_changed",
          "_persist_key", "_export_all_worker", "_on_export_all_done",
          "_on_export_all_failed", "_set_key_editable", "_report_key_at_startup")


class _App:
    """A stub ``DrawingAnalyzerApp`` driven through the real handlers.

    It mirrors ``__init__``'s key lines (the launch load, the field pre-filled
    before its write trace is added) and captures the worker thread instead of
    starting it, so a test runs the worker, then the ``after`` callbacks, in
    order on its own thread.
    """

    def __init__(self, gui, tk, monkeypatch, tmp_path, *, launch_env=None, stored=None):
        from drawing_analyzer.core import api_key_store

        self.gui, self.tk = gui, tk
        monkeypatch.setattr(api_key_store, "_KEYRING_AVAILABLE", False)
        monkeypatch.setattr(api_key_store, "_keyring", None)
        key_file = tmp_path / "drawing_analyzer_api_key.txt"
        monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [key_file])
        if stored is not None:
            key_file.write_text(stored, encoding="utf-8")
        if launch_env is None:
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        else:
            monkeypatch.setenv("ANTHROPIC_API_KEY", launch_env)
        self.logs: list[tuple[str, str]] = []
        self.dialogs: list[tuple[str, str]] = []
        self.thread = None
        self.after_queue: list = []
        self.answers: dict[str, bool] = {}

        def ask(title, message="", **_kw):
            self.dialogs.append((title, message))
            return self.answers.get(title, True)

        def show(title, message="", **_kw):
            self.dialogs.append((title, message))

        tk.messagebox.askyesno = ask
        tk.messagebox.showerror = show
        tk.messagebox.showinfo = show
        proxy = types.SimpleNamespace(**{
            n: getattr(threading, n) for n in dir(threading) if not n.startswith("__")
        })
        proxy.Thread = self._thread
        monkeypatch.setattr(gui, "threading", proxy)

        D = gui.DrawingAnalyzerApp
        s = types.SimpleNamespace()
        self.s = s
        for name in _WIDGETS:
            setattr(s, name, _Widget())
        for name in _BOUND:
            if hasattr(D, name):
                setattr(s, name, getattr(D, name).__get__(s))
        s._log = lambda message, level="info", **_k: self.logs.append((message, level))
        s._set_progress_text = lambda *a, **k: None
        s._set_focus_editable = lambda _enabled: None
        s._clear_log = lambda: None
        s._current_focus = lambda: ""
        s._current_specs_text = lambda: ""
        s._qc_markups_var = types.SimpleNamespace(get=lambda: True)
        for name in ("_qc_verified_only_var", "_ink_rejected_var", "_reference_audit_var",
                     "_save_tiles_var"):
            setattr(s, name, types.SimpleNamespace(get=lambda: False))
        s._processing_mode_var = types.SimpleNamespace(get=lambda: "Fast")
        s._selected_profiles = lambda: []
        s._usable_preflight_bases = lambda: None
        s._embed_key_var = types.SimpleNamespace(get=lambda: True)
        s.after = lambda _ms, fn: self.after_queue.append(fn)
        s._progress_from_thread = lambda *a: None
        s._log_from_thread = lambda *a, **k: None
        s._status_from_thread = lambda *a: None
        s._open_in_os = lambda _p: None
        s._default_digest_filename = lambda **_k: "report.html"
        s._busy = False
        s._export_busy = False
        s._ctx = None
        s._pdfs = []
        # __init__'s key lines, in its order.
        s._initial_key = D._load_api_key(s)
        s._has_key = bool(s._initial_key)
        s._applied_key = s._initial_key or ""
        s._persisted_key = s._initial_key
        s._key_var = _TclVar(s._initial_key or "")
        s._key_var.trace_add("write", lambda *_a: D._on_key_changed(s))
        if hasattr(D, "_report_key_at_startup"):
            s._report_key_at_startup()

    def _thread(self, target=None, args=(), kwargs=None, daemon=None, **_kw):
        self.thread = (target, args, dict(kwargs or {}))
        return types.SimpleNamespace(start=lambda: None)

    def type_key(self, value):
        """A keystroke reaches the variable only while the entry is enabled
        (real Tk 8.6 + customtkinter 6.0.0: a disabled CTkEntry refuses
        typing, Backspace, Paste, Ctrl+V and Cut)."""
        if self.s.key_entry.state != "disabled":
            self.s._key_var.set(value)

    def analyze(self, pdfs):
        self.thread = None
        self.s._pdfs = list(pdfs)
        self.gui.DrawingAnalyzerApp._on_process(self.s)
        return self.thread is not None

    def run(self):
        """Run the captured worker, then the callbacks it scheduled."""
        target, args, kwargs = self.thread
        target(*args, **kwargs)
        while self.after_queue:
            self.after_queue.pop(0)()

    def status(self):
        return self.s.key_status_label.cget("text")

    def texts(self):
        return [m for m, _ in self.logs] + [f"{t} {m}" for t, m in self.dialogs] + [
            str(self.status())
        ]


def _fake_run(gui, monkeypatch, app, *, raises=None):
    """Replace the pipeline with a recorder: the kwargs it got and the key
    controls' state while it ran."""
    seen: dict = {}

    def _extract(pdfs, **kw):
        seen.update(kw)
        seen["entry"] = app.s.key_entry.state
        seen["show"] = app.s.key_show_btn.state
        seen["status"] = app.status()
        seen["env"] = _key_class(os.environ.get("ANTHROPIC_API_KEY"))
        if raises is not None:
            raise raises
        return gui.DrawingContext(combined_text="Sheet M-101 digest")

    monkeypatch.setattr(gui, "extract_drawing_context", _extract)
    return seen


def _one_pdf(tmp_path):
    return [_mini_set(tmp_path)[0]]


def _mini_set(tmp_path):
    from tests.fixtures.gauntlet import build_mini_set

    pytest.importorskip("pymupdf")
    return build_mini_set(tmp_path)


def test_the_run_gets_one_real_client_built_from_the_applied_key(tmp_path, monkeypatch):
    import anthropic

    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path)
        seen = _fake_run(gui, monkeypatch, app)
        app.type_key(_KEY)
        assert app.analyze(_one_pdf(tmp_path))
        app.run()

    client = seen.get("client")
    assert isinstance(client, anthropic.Anthropic), type(client).__name__
    assert _key_class(client.api_key) == "key A"
    assert seen["env"] == "none"                      # the run never needed it
    assert "ANTHROPIC_API_KEY" not in os.environ


@pytest.mark.parametrize(
    "edit",
    ["field backspace", "field emptied", "env set to key B", "env removed"],
    ids=["field-backspace", "field-emptied", "env-key-b", "env-removed"],
)
def test_an_edit_mid_run_does_not_reach_a_later_stage(tmp_path, monkeypatch, edit):
    """G2 itself: every stage after the digest keeps the run's key.

    The field is set through its variable, so ``_on_key_changed`` runs even
    though the real entry is locked: the lock is a courtesy, the run's client
    is the correctness.
    """
    import drawing_analyzer.client as client_mod
    import drawing_analyzer.digest_cache as digest_cache
    import drawing_analyzer.pipeline as pl
    from tests.fixtures.gauntlet import mini_client

    calls: list[str] = []                      # the key class of every request

    def _factory(api_key=None, **_kw):
        fake = mini_client()
        route = fake._route
        label = _key_class(api_key)

        def _recording(kw):
            calls.append(label)
            return route(kw)

        fake._route = _recording
        return fake

    monkeypatch.setattr(client_mod, "Anthropic", _factory)
    monkeypatch.setattr(client_mod, "_cached_client", None)
    monkeypatch.setattr(client_mod, "_cached_key", None)
    monkeypatch.setattr(digest_cache, "_default_cache",
                        digest_cache.DigestCache(tmp_path / "cache.sqlite"))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setenv("DRAWING_ANALYZER_STAGE_OVERLAP", "0")
    pdfs = _mini_set(tmp_path)
    digest_calls: list[int] = []

    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        real = pl._digest_sheets_concurrent

        def _digest_then_edit(*a, **k):
            out = real(*a, **k)
            digest_calls.append(len(calls))
            if edit == "field backspace":
                app.s._key_var.set(_KEY[:-1])
            elif edit == "field emptied":
                app.s._key_var.set("")
            elif edit == "env set to key B":
                os.environ["ANTHROPIC_API_KEY"] = _KEY_B
            else:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            return out

        monkeypatch.setattr(pl, "_digest_sheets_concurrent", _digest_then_edit)
        assert app.analyze(pdfs)
        app.run()
        ctx = app.s._ctx

    assert digest_calls, "the digest phase never ran"
    later = calls[digest_calls[0]:]
    assert later, "no stage ran after the digest"
    assert set(later) == {"key A"}, sorted(set(later))
    assert not [e for e in ctx.errors if "ANTHROPIC_API_KEY" in e]
    assert ctx.qc_status == "COMPLETE"


@pytest.mark.parametrize("exit_path", ["done", "worker raised"], ids=["done", "raised"])
def test_the_key_entry_is_locked_while_busy_and_unlocked_on_every_exit(
    tmp_path, monkeypatch, exit_path,
):
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        before = app.status()
        seen = _fake_run(gui, monkeypatch, app, raises=(
            RuntimeError("worker failed") if exit_path == "worker raised" else None))
        assert app.analyze(_one_pdf(tmp_path))
        app.run()

    assert seen["entry"] == "disabled"
    assert seen["show"] == "normal"               # Show still reveals the run's key
    assert seen["status"] == _LOCKED
    assert app.s.key_entry.state == "normal"
    assert app.status() == before == "loaded"
    if exit_path == "worker raised":
        assert ("Analysis failed", "worker failed") in app.dialogs


def test_a_keystroke_while_locked_never_reaches_the_field(tmp_path, monkeypatch):
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        seen: dict = {}

        def _extract(pdfs, **kw):
            app.type_key(_KEY[:-1])                  # Backspace during the run
            seen["field"] = _key_class(app.s._key_var.get())
            seen["applied"] = _key_class(app.s._applied_key)
            return gui.DrawingContext(combined_text="x")

        monkeypatch.setattr(gui, "extract_drawing_context", _extract)
        assert app.analyze(_one_pdf(tmp_path))
        app.run()
    assert seen == {"field": "key A", "applied": "key A"}


def test_a_status_set_during_the_run_is_kept_when_the_entry_unlocks(tmp_path, monkeypatch):
    """A save that lands during the run (``<FocusOut>`` still fires on a
    disabled entry) reports its own outcome; unlocking does not overwrite it."""
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)

        def _extract(pdfs, **kw):
            app.s._set_key_status("session only", None)
            return gui.DrawingContext(combined_text="x")

        monkeypatch.setattr(gui, "extract_drawing_context", _extract)
        assert app.analyze(_one_pdf(tmp_path))
        app.run()
    assert app.status() == "session only"


@pytest.mark.parametrize(
    "launch, expect_key, expect_note",
    [
        (_BOM + _KEY + "\r\n", "key A", False),
        ("  " + _KEY + "​", "key A", False),
        ("not-a-key-" + "Z" * 30, "other", True),
        (_BOM + " ", "empty", False),
    ],
    ids=["bom-crlf", "spaces-zwsp", "not-a-key", "only-invisible"],
)
def test_the_launch_key_is_read_once_normalized_and_removed(
    tmp_path, monkeypatch, launch, expect_key, expect_note,
):
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=launch)
    assert _key_class(app.s._initial_key) == expect_key
    assert _key_class(app.s._key_var.get()) == expect_key     # the field shows it
    assert "ANTHROPIC_API_KEY" not in os.environ              # no child inherits it
    notes = [n.text for n in app.s._key_load_notes]
    if expect_note:
        assert len(notes) == 1 and "ANTHROPIC_API_KEY" in notes[0]
        assert "sk-ant-" in notes[0] and "Z" * 10 not in notes[0]
        assert (notes[0], "warning") in app.logs
    else:
        assert notes == []


def test_a_launch_key_that_is_not_a_key_is_still_the_one_used(tmp_path, monkeypatch):
    """The owner's rule: warn and use it, like a typed value (a future key
    format keeps working for the session); the saved key does not replace it."""
    odd = "not-a-key-" + "Z" * 30
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=odd, stored=_KEY_B)
        seen = _fake_run(gui, monkeypatch, app)
        assert app.analyze(_one_pdf(tmp_path))
        app.run()
    assert seen["client"].api_key == odd


def _spawn_child_sees_a_key() -> bool:
    import multiprocessing

    from drawing_analyzer import annotate

    context = multiprocessing.get_context("spawn")
    with annotate._PROCESS_POOL_EXECUTOR(max_workers=1, mp_context=context) as pool:
        return pool.submit(_child_sees_a_key).result(timeout=120)


def _subprocess_child_sees_a_key() -> bool:
    import subprocess

    probe = "import os, sys; sys.exit(3 if 'ANTHROPIC_API_KEY' in os.environ else 4)"
    return subprocess.run([sys.executable, "-c", probe], check=False).returncode == 3


@pytest.mark.parametrize("source", ["typed in the field", "inherited at launch"],
                         ids=["typed", "launch-env"])
def test_no_child_process_inherits_the_key(tmp_path, monkeypatch, source):
    """The annotation pool's spawn workers and ``subprocess.run`` (the
    ``open``/``xdg-open`` path) inherit ``os.environ``; ``os.startfile`` and
    the update installer do too on Windows (not run here)."""
    with _gui_module() as (gui, tk):
        if source == "typed in the field":
            app = _App(gui, tk, monkeypatch, tmp_path)
            app.type_key(_KEY)
        else:
            app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        assert _key_class(app.s._applied_key) == "key A"
        seen = {"spawn": _spawn_child_sees_a_key(), "subprocess": _subprocess_child_sees_a_key()}
    assert seen == {"spawn": False, "subprocess": False}


def _capture_exports(gui, tk, monkeypatch, tmp_path, app):
    import drawing_analyzer.export as export_mod

    got: dict = {}
    monkeypatch.setattr(gui, "build_html_report", lambda ctx, **kw: (
        got.__setitem__("html", _key_class(kw.get("api_key"))) or "<html></html>"))
    monkeypatch.setattr(export_mod, "write_drawing_export", lambda ctx, folder, **kw: (
        got.__setitem__("export all", _key_class(kw.get("api_key"))) or tmp_path))
    tk.filedialog.asksaveasfilename = lambda **_k: str(tmp_path / "report.html")
    tk.filedialog.askdirectory = lambda **_k: str(tmp_path)
    app.s._ctx = gui.DrawingContext(combined_text="Sheet M-101 digest")
    return got


@pytest.mark.parametrize("source", ["session only", "inherited at launch"],
                         ids=["session-only", "launch-env"])
def test_the_exports_embed_the_applied_key(tmp_path, monkeypatch, source):
    with _gui_module() as (gui, tk):
        if source == "session only":
            app = _App(gui, tk, monkeypatch, tmp_path)
            app.answers["No secure key storage available"] = False   # plaintext declined
            app.type_key(_KEY)
            app.s._persist_key()
        else:
            app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        got = _capture_exports(gui, tk, monkeypatch, tmp_path, app)
        gui.DrawingAnalyzerApp._on_save_html(app.s)
        gui.DrawingAnalyzerApp._on_export_all(app.s)
        app.run()
    assert got == {"html": "key A", "export all": "key A"}
    assert not (tmp_path / "drawing_analyzer_api_key.txt").exists()


def test_export_all_embeds_the_key_applied_when_it_was_clicked(tmp_path, monkeypatch):
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        got = _capture_exports(gui, tk, monkeypatch, tmp_path, app)
        gui.DrawingAnalyzerApp._on_export_all(app.s)
        app.type_key(_KEY_B)                       # edited while the export runs
        assert app.s.key_entry.state == "normal"   # no lock during an export
        app.run()
    assert got == {"export all": "key A"}


def test_analyze_refuses_when_the_field_was_emptied(tmp_path, monkeypatch):
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path, launch_env=_KEY)
        app.type_key("")
        assert not app.analyze(_one_pdf(tmp_path))
    assert app.dialogs[-1][0] == "No API key"


def test_a_typed_value_that_is_not_a_key_still_runs(tmp_path, monkeypatch):
    """WP-16.1's accepted cost, kept by the owner: it is applied to the session
    (a future key format keeps working) though it is never saved."""
    with _gui_module() as (gui, tk):
        app = _App(gui, tk, monkeypatch, tmp_path)
        seen = _fake_run(gui, monkeypatch, app)
        app.type_key("hello world")
        assert app.analyze(_one_pdf(tmp_path))
        app.run()
    assert seen["client"].api_key == "hello world"


def test_init_starts_the_applied_key_from_the_launch_load():
    """Structural, like the hooks test above: ``__init__`` cannot run without a
    display, and the harness mirrors these lines."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent / "src" / "drawing_analyzer" / "gui.py"
    ).read_text(encoding="utf-8")
    app = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ClassDef) and n.name == "DrawingAnalyzerApp"
    )
    init = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    init_src = ast.unparse(init)
    assert "self._initial_key = self._load_api_key()" in init_src
    assert "self._applied_key = self._initial_key or ''" in init_src


def test_no_message_status_dialog_log_record_or_output_carries_the_key(
    tmp_path, monkeypatch, caplog, capfd,
):
    """Every path this slice touches, with the key in play: none of what the
    user or a log sees carries it (nor the value of a launch variable that is
    not a key). Asserted non-vacuously: the scenarios produced text."""
    import logging

    odd = "not-a-key-" + "Z" * 30
    texts: list[str] = []
    caplog.set_level(logging.DEBUG)
    with _gui_module() as (gui, tk):
        for launch in (_BOM + _KEY, odd, None):
            app = _App(gui, tk, monkeypatch, tmp_path, launch_env=launch)
            if launch is None:
                app.answers["No secure key storage available"] = False
                app.type_key(_KEY)
                app.s._persist_key()
            _fake_run(gui, monkeypatch, app)
            app.analyze(_one_pdf(tmp_path))
            app.run()
            _fake_run(gui, monkeypatch, app, raises=RuntimeError("worker failed"))
            app.analyze(_one_pdf(tmp_path))
            app.run()
            _capture_exports(gui, tk, monkeypatch, tmp_path, app)
            gui.DrawingAnalyzerApp._on_save_html(app.s)
            texts += app.texts()
    out, err = capfd.readouterr()
    texts += [r.getMessage() for r in caplog.records] + [out, err]
    assert len([t for t in texts if t.strip()]) >= 12
    blob = "\n".join(texts)
    assert _KEY[:24] not in blob and "A" * 20 not in blob
    assert "Z" * 20 not in blob
