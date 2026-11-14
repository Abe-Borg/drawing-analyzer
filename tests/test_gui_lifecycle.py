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


def _stub_app(gui, *, busy=False, export_busy=False, run_cancel=None):
    destroyed: list[bool] = []
    scheduled: list = []
    stub = types.SimpleNamespace(
        _busy=busy, _export_busy=export_busy,
        _run_cancel=run_cancel, _quitting=False,
        destroy=lambda: destroyed.append(True),
        after=lambda _delay, callback: scheduled.append(callback),
        stop_btn=types.SimpleNamespace(configure=lambda **kw: None),
        _log=lambda *a, **k: None, _set_progress_text=lambda *a, **k: None,
    )
    for name in ("_request_stop", "_stop_then_quit", "_on_close_request"):
        setattr(stub, name, types.MethodType(getattr(gui.DrawingAnalyzerApp, name), stub))
    stub.scheduled = scheduled
    return stub, destroyed


def _cost_preview_app(gui, tk, monkeypatch):
    """Real GUI handlers, fake widgets, and an explicitly scheduled worker."""
    import threading

    workers, callbacks, summaries = [], [], []

    class Worker:
        def __init__(self, *, target, daemon):
            self.target = target
            assert daemon

        def start(self):
            workers.append(self.target)

    monkeypatch.setattr(gui.threading, "Thread", Worker)
    var = tk.BooleanVar
    app = types.SimpleNamespace(
        _busy=False, _pdfs=[], _profile_vars={}, _profiles_by_name={},
        _profile_forced_on=set(), _profile_forced_off=set(), _profile_suggested=set(),
        _preflight_gen=0, _preflight_bases=None, _preflight_fingerprint=None,
        _preflight_lock=threading.Lock(),
        _processing_mode_var=tk.StringVar(value="Fast"),
        _qc_markups_var=var(value=False), _qc_verified_only_var=var(value=False),
        _ink_rejected_var=var(value=False), _reference_audit_var=var(value=False),
        _current_focus=lambda: "", _current_specs_text=lambda: "",
        _current_context_text=lambda: "", _current_governing=lambda: [],
        _checklists=[], _atlas_choice=None, _save_tiles_var=var(value=False),
        _confirm_full_qc_var=var(value=True), _prefs_path=None,
        _budget_on_var=var(value=False), _budget_var=tk.StringVar(value=""),
        _spend=None, _budget_entry=None,
        spend_label=types.SimpleNamespace(configure=lambda **kw: None),
        _refresh_section_headers=lambda: None, _sync_dropzone_section=lambda: None,
        _refresh_files_panel=lambda: None, _reveal_files=lambda: None,
        summary_label=types.SimpleNamespace(configure=lambda **kw: summaries.append(kw["text"])),
        after=lambda delay, callback: callbacks.append(callback),
    )
    for name in ("_add_pdfs", "_refresh_profile_suggestions", "_apply_profile_suggestions",
                 "_usable_preflight_bases", "_refresh_summary", "_selected_profiles", "_on_process",
                 "_on_confirm_full_qc_toggle", "_budget_cap", "_mark_budget_entry",
                 "_on_budget_change", "_confirm_stopping_cap", "_refresh_spend_line",
                 "_tick_spend"):
        setattr(app, name, types.MethodType(getattr(gui.DrawingAnalyzerApp, name), app))
    return app, workers, callbacks, summaries


def _preview_pdf(tmp_path, pages=None):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "drawings.pdf"
    with pymupdf.open() as doc:
        for i, (width, height, vector) in enumerate(pages or [(34, 44, True)] * 3):
            page = doc.new_page(width=width * 72, height=height * 72)
            if vector:
                page.insert_text((72, 72), f"FP-10{i} PRE-ACTION VALVE SCHEDULE")
        doc.save(pdf)
    return pdf


@pytest.mark.parametrize("exhaustive", [False, True])
def test_loading_files_without_profiles_uses_measured_costs_in_gui(tmp_path, monkeypatch, exhaustive):
    """Regression: a shipping install has no profile checkboxes at all."""
    from drawing_analyzer import cost, profiles

    pdf = _preview_pdf(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")

    def no_profile_suggestions(*args, **kwargs):
        raise AssertionError("no profiles installed; suggestions should not run")

    monkeypatch.setattr(profiles, "suggest_profiles", no_profile_suggestions)
    with _gui_module() as (gui, tk):
        app, workers, callbacks, summaries = _cost_preview_app(gui, tk, monkeypatch)
        app._qc_markups_var.set(exhaustive)
        app._add_pdfs([pdf])
        assert len(workers) == 1
        assert app._usable_preflight_bases() is None
        workers.pop()()
        callbacks.pop()()
        measured = app._usable_preflight_bases()
        assert len(measured) == 3
        expected = cost.estimate_drawing_set_cost(3, model=gui.REVIEW_MODEL_DEFAULT, bases=measured)
        assert expected.shape_aware
        assert f"~{expected.image_tokens:,} digest image tokens" in summaries[-1]
        assert summaries[-1] != summaries[0]

        prompts = []
        tk.messagebox.askyesno = lambda title, prompt: prompts.append(prompt) or False
        # The full-QC dialog: declined with "Don't show this again" ticked.
        monkeypatch.setattr(
            gui, "_ask_cost_confirmation",
            lambda parent, title, prompt: (prompts.append(prompt) or False, True),
        )
        app._on_process()
        assert len(prompts) == 1
        # Declining never remembers the opt-out: skipping the dialog means proceeding.
        assert app._confirm_full_qc_var.get() is True
        assert "measured size and text layer" in prompts[0]
        assert "pages have not been measured" not in prompts[0]
        assert "adaptive thinking, which is billed as output" in prompts[0]
        assert not app._busy  # declining sends nothing


def test_gui_discards_superseded_preflight_and_rewritten_file_bases(tmp_path, monkeypatch):
    pdf = _preview_pdf(tmp_path)
    with _gui_module() as (gui, tk):
        app, workers, callbacks, _ = _cost_preview_app(gui, tk, monkeypatch)
        app._add_pdfs([pdf])
        first = workers.pop()
        app._refresh_profile_suggestions()
        first()
        callbacks.pop()()
        assert app._preflight_bases is None  # older generation cannot install bases
        workers.pop()()
        callbacks.pop()()
        assert app._usable_preflight_bases()
        pdf.write_bytes(pdf.read_bytes() + b"\n%changed\n")
        assert app._usable_preflight_bases() is None


def test_gui_measured_estimate_prices_each_pages_physical_grid(tmp_path, monkeypatch):
    from drawing_analyzer.cost import estimate_drawing_set_cost, estimate_exhaustive_run_cost

    pdf = _preview_pdf(tmp_path, [(8.5, 11, True), (11, 17, True),
                                 (34, 44, True), (8.5, 11, False)])
    with _gui_module() as (gui, tk):
        app, workers, callbacks, summaries = _cost_preview_app(gui, tk, monkeypatch)
        app._add_pdfs([pdf])
        workers.pop()()
        callbacks.pop()()
        bases = app._usable_preflight_bases()
        # Pixel/render oracles from the mixed-size grid qualification: 43x1,
        # 2x1, 6x6 vector grids and the 27x1 raster grid, on the hi-res tier.
        expected = 7_280 + 14_125 + 91_168 + 11_736
        standard = estimate_drawing_set_cost(4, bases=bases)
        exhaustive = estimate_exhaustive_run_cost(4, bases=bases)
        assert standard.shape_aware and exhaustive.shape_aware
        assert standard.image_tokens == expected
        digest = next(c for c in exhaustive.components if c.stage == "Digest")
        assert digest.input_tokens == expected + 4 * 800
        assert f"~{expected:,} digest image tokens" in summaries[-1]
        assert standard.output_tokens_low == 4 * 4_000 + 2_000
        assert standard.output_tokens == 4 * 64_000 + 2_000


def test_profile_suggestion_failure_keeps_measured_gui_bases(tmp_path, monkeypatch):
    from drawing_analyzer import profiles

    pdf = _preview_pdf(tmp_path)
    with _gui_module() as (gui, tk):
        app, workers, callbacks, _ = _cost_preview_app(gui, tk, monkeypatch)
        app._profile_vars = {"custom": tk.BooleanVar(value=False)}
        app._profiles_by_name = {"custom": object()}

        def fail(*args, **kwargs):
            raise ValueError("bad profile")

        monkeypatch.setattr(profiles, "suggest_profiles", fail)
        app._add_pdfs([pdf])
        workers.pop()()
        callbacks.pop()()
        assert len(app._usable_preflight_bases()) == 3


def test_installed_profile_suggestions_still_respect_manual_overrides(tmp_path, monkeypatch):
    from drawing_analyzer import profiles

    pdf = _preview_pdf(tmp_path)
    with _gui_module() as (gui, tk):
        app, workers, callbacks, _ = _cost_preview_app(gui, tk, monkeypatch)
        app._profile_vars = {name: tk.BooleanVar(value=False) for name in ("custom", "manual")}
        app._profiles_by_name = {name: types.SimpleNamespace(name=name) for name in app._profile_vars}
        app._profile_forced_off.add("custom")
        app._profile_forced_on.add("manual")
        suggestions = []

        def suggest(sheet_ids, *, available):
            suggestions.append((sheet_ids, available))
            return [available["custom"]]

        monkeypatch.setattr(profiles, "suggest_profiles", suggest)
        app._add_pdfs([pdf])
        workers.pop()()
        callbacks.pop()()
        assert len(suggestions) == 1
        assert suggestions[0][1] == app._profiles_by_name
        assert app._profile_suggested == {"custom"}
        assert not app._profile_vars["custom"].get()
        assert app._profile_vars["manual"].get()
        assert len(app._usable_preflight_bases()) == 3


def test_gui_does_not_start_a_preflight_while_busy(monkeypatch):
    with _gui_module() as (gui, tk):
        app, workers, _, _ = _cost_preview_app(gui, tk, monkeypatch)
        app._busy = True
        app._refresh_profile_suggestions()
        assert not workers and app._preflight_gen == 0


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


@pytest.mark.parametrize("worker_unwinds", [True, False])
def test_quitting_mid_analysis_stops_the_run_before_closing(monkeypatch, worker_unwinds):
    """Quit pulls the kill switch: a daemon worker dies with the process, but a
    remote batch would keep running and billing after the window closed. The
    window waits for the stop to settle — bounded, never hanging on it."""
    from drawing_analyzer.cancellation import CancelToken

    with _gui_module() as (gui, tk):
        clock = {"t": 0.0}
        monkeypatch.setattr(gui.time, "monotonic", lambda: clock["t"])
        tk.messagebox.askyesno = lambda *a, **k: True
        token = CancelToken()
        stub, destroyed = _stub_app(gui, busy=True, run_cancel=token)
        gui.DrawingAnalyzerApp._on_close_request(stub)
        assert token.cancelled
        assert destroyed == []                    # the stop has not settled yet
        stub.scheduled.pop()()                    # still busy: polls again
        assert destroyed == []
        if worker_unwinds:
            stub._busy = False                    # the worker reported back
        else:
            clock["t"] = gui.QUIT_STOP_GRACE_SECONDS + 1
        stub.scheduled.pop()()
        assert destroyed == [True]


def test_a_second_close_while_stopping_closes_at_once():
    from drawing_analyzer.cancellation import CancelToken

    with _gui_module() as (gui, tk):
        tk.messagebox.askyesno = lambda *a, **k: True
        stub, destroyed = _stub_app(gui, busy=True, run_cancel=CancelToken())
        gui.DrawingAnalyzerApp._on_close_request(stub)
        assert destroyed == []
        tk.messagebox.askyesno = lambda *a, **k: False   # never asked again
        gui.DrawingAnalyzerApp._on_close_request(stub)
        assert destroyed == [True]


@pytest.mark.parametrize("answer,stops", [(True, True), (False, False)])
def test_stop_button_cancels_only_when_confirmed(answer, stops):
    from drawing_analyzer.cancellation import CancelToken

    with _gui_module() as (gui, tk):
        tk.messagebox.askyesno = lambda *a, **k: answer
        token = CancelToken()
        stub, _ = _stub_app(gui, busy=True, run_cancel=token)
        gui.DrawingAnalyzerApp._on_stop(stub)
        assert token.cancelled is stops


def test_a_broken_stop_dialog_still_stops_the_run():
    from drawing_analyzer.cancellation import CancelToken

    with _gui_module() as (gui, tk):
        def boom(*a, **k):
            raise RuntimeError("no display")

        tk.messagebox.askyesno = boom
        token = CancelToken()
        stub, _ = _stub_app(gui, busy=True, run_cancel=token)
        gui.DrawingAnalyzerApp._on_stop(stub)
        assert token.cancelled


def test_worker_reports_a_stopped_run_as_stopped_not_failed(monkeypatch):
    from drawing_analyzer.cancellation import CancelToken, RunCancelled

    outcomes: list[str] = []
    seen: dict = {}
    with _gui_module() as (gui, _tk):
        def stopped_pipeline(*args, **kwargs):
            seen["cancel"] = kwargs.get("cancel")
            seen["monitor"] = kwargs.get("monitor")
            raise RunCancelled()

        monkeypatch.setattr(gui, "extract_drawing_context", stopped_pipeline)
        stub = types.SimpleNamespace(
            after=lambda _delay, callback: callback(),
            _on_cancelled=lambda: outcomes.append("stopped"),
            _on_error=lambda message: outcomes.append("failed"),
            _on_done=lambda ctx: outcomes.append("done"),
            _progress_from_thread=lambda *a: None,
            _log_from_thread=lambda *a: None, _status_from_thread=lambda *a: None,
        )
        token, monitor = CancelToken(), object()
        gui.DrawingAnalyzerApp._worker(stub, [], "", cancel=token, monitor=monitor)
    assert outcomes == ["stopped"]
    assert seen["cancel"] is token                # the run got the GUI's switch
    assert seen["monitor"] is monitor             # ...and the Live view's window


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


def test_worker_logs_full_traceback_before_showing_error(monkeypatch, tmp_path):
    from drawing_analyzer import diagnostics

    diagnostics.reset_for_tests()
    log_path = tmp_path / "diagnostics.log"
    diagnostics.configure_file_logging(log_path, capture_sdk=False)
    shown = []
    try:
        with _gui_module() as (gui, _tk):
            def broken_pipeline(*args, **kwargs):
                raise RuntimeError("analysis failed at the inner frame")
            monkeypatch.setattr(gui, "extract_drawing_context", broken_pipeline)
            def show_error(message):
                trace = log_path.read_text(encoding="utf-8")
                assert "Traceback (most recent call last)" in trace
                assert "broken_pipeline" in trace
                assert "RuntimeError: analysis failed at the inner frame" in trace
                shown.append(message)
            stub = types.SimpleNamespace(
                after=lambda _delay, callback: callback(), _on_error=show_error,
                _progress_from_thread=lambda *a: None,
                _log_from_thread=lambda *a: None, _status_from_thread=lambda *a: None,
            )
            gui.DrawingAnalyzerApp._worker(stub, [], "")
        assert shown == ["analysis failed at the inner frame"]
    finally:
        diagnostics.reset_for_tests()


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
# Loaded files: every input reaches the run; Remove drops exactly one file
# --------------------------------------------------------------------------- #


def _inputs_app(gui, tk, monkeypatch):
    """The cost-preview stub plus what Analyze touches once confirmed."""
    app, workers, callbacks, summaries = _cost_preview_app(gui, tk, monkeypatch)
    started = []

    class Worker:
        def __init__(self, *, target, args=(), daemon):
            self.target, self.args = target, args

        def start(self):
            started.append(self.args)

    widget = types.SimpleNamespace(configure=lambda **kw: None)
    logs = []
    app.__dict__.update(
        analyze_btn=widget, stop_btn=widget, clear_btn=widget, html_btn=widget,
        reviewed_btn=widget, export_btn=widget, _files_sec=None,
        _set_focus_editable=lambda enabled: None, _clear_log=lambda: None,
        _log=lambda message, level="info": logs.append(message),
        _set_progress_text=lambda *a, **k: None, _ctx=None, _run_cancel=None,
        _spec_documents=[], _context_documents=[], _specs_budget=None,
        _context_budget=None, _specs_text="", _context_text="", _atlas=None,
        _refresh_files_panel=lambda: None, _reveal_files=lambda: None,
        _worker=lambda *args: None,
    )
    for name in ("_remove_pdf", "_apply_documents_result", "_rebuild_document_text",
                 "_remove_document", "_current_specs_text", "_current_context_text",
                 "_current_governing", "_end_extraction", "_set_inputs_editable"):
        setattr(app, name, types.MethodType(getattr(gui.DrawingAnalyzerApp, name), app))
    app._add_buttons = {}
    monkeypatch.setattr(gui.threading, "Thread", Worker)
    tk.messagebox.askyesno = lambda title, prompt: True
    return app, started, logs


def test_analyze_hands_every_loaded_input_to_the_run(tmp_path, monkeypatch):
    from drawing_analyzer.ahj_atlas import AtlasJurisdiction
    from drawing_analyzer.models import parse_governing_editions
    from drawing_analyzer.profiles import Profile

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    pdf = _preview_pdf(tmp_path)
    with _gui_module() as (gui, tk):
        app, started, _ = _inputs_app(gui, tk, monkeypatch)
        app._pdfs = [pdf]
        app._specs_text, app._context_text = "SPEC TEXT", "BASIS OF DESIGN"
        checklist = Profile(name="upload:fp.xlsx", title="fp.xlsx", items=("Check FDC",))
        app._checklists = [checklist]
        # Scope… narrows the loaded checklist to sheet-number prefixes.
        app._refresh_summary = lambda: None
        app._set_checklist_scope = types.MethodType(
            gui.DrawingAnalyzerApp._set_checklist_scope, app)
        app._set_checklist_scope(checklist, "FP, F")
        codes, _ = parse_governing_editions("NFPA 13 2025; IBC 2024")
        app._atlas_choice = AtlasJurisdiction(
            name="Loudoun County, VA", entries=("NFPA 13 2025", "IBC 2024"), codes=codes,
        )
        app._processing_mode_var.set("XFast")
        app._save_tiles_var.set(True)
        app._budget_on_var.set(True)
        app._budget_var.set("$1,250")
        live_monitor = object()
        app._live = types.SimpleNamespace(begin=lambda: live_monitor)
        app._on_process()
        (args,) = started
        (pdfs, focus, specs, qc, _vo, _audit, _ink, profiles, use_batch,
         critique_batch, _cancel, governing, context, fast_mode, save_tiles,
         monitor, spend) = args
    assert monitor is live_monitor                 # the board watches this run
    assert pdfs == [pdf] and specs == "SPEC TEXT" and context == "BASIS OF DESIGN"
    # The run gets the scoped checklist: same items, limited to FP/F sheets.
    (sent,) = [p for p in profiles if getattr(p, "name", "") == "upload:fp.xlsx"]
    assert sent.items == checklist.items and sent.disciplines == ("fp", "f")
    assert governing == ["NFPA 13 2025", "IBC 2024"]
    assert (use_batch, critique_batch, fast_mode, save_tiles) == (False, False, True, True)
    # The run's monitor carries the typed cap and starts from the quoted estimate.
    quoted = spend.snapshot()
    assert spend.budget == 1250.0 and 0 < quoted.quoted_low <= quoted.projected_high


@pytest.mark.parametrize("typed", ["", "abc", "0", "-5", "nan", "inf"])
def test_an_unreadable_budget_cap_blocks_analyze_instead_of_running_uncapped(
    tmp_path, monkeypatch, typed,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    with _gui_module() as (gui, tk):
        app, started, _ = _inputs_app(gui, tk, monkeypatch)
        app._pdfs = [_preview_pdf(tmp_path)]
        app._budget_on_var.set(True)
        app._budget_var.set(typed)
        shown = []
        tk.messagebox.showerror = lambda title, message: shown.append(title)
        app._on_process()
    assert started == [] and len(shown) == 1


def test_the_budget_cap_can_be_changed_and_turned_off_while_a_run_works(tmp_path):
    from drawing_analyzer.cancellation import CancelToken
    from drawing_analyzer.core import preferences
    from drawing_analyzer.live_spend import SpendMonitor
    from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

    prefs = tmp_path / "config" / "gui_preferences.json"
    with _gui_module() as (gui, tk):
        token = CancelToken()
        monitor = SpendMonitor(budget=20.0)
        monitor.bind_cancel(token)
        monitor.note_response(                               # $5 on Opus 5
            FakeMessage(content=[FakeTextBlock(text="ok")],
                        usage=FakeUsage(input_tokens=1_000_000, output_tokens=0)),
            stage="digest", item="S:p0", model="claude-opus-5",
        )
        answers = []
        tk.messagebox.askyesno = lambda *a, **k: answers.pop(0)
        app = types.SimpleNamespace(
            _busy=True, _spend=monitor, _prefs_path=prefs, _budget_entry=None,
            _budget_on_var=tk.BooleanVar(value=True), _budget_var=tk.StringVar(value="20"),
            _log=lambda *a, **k: None,
            spend_label=types.SimpleNamespace(configure=lambda **kw: None),
        )
        for name in ("_budget_cap", "_on_budget_change", "_mark_budget_entry",
                     "_confirm_stopping_cap", "_refresh_spend_line"):
            setattr(app, name, types.MethodType(getattr(gui.DrawingAnalyzerApp, name), app))

        app._budget_var.set("12.50")
        app._on_budget_change()
        assert monitor.budget == 12.5

        # Something unreadable leaves the cap in force rather than lifting it.
        app._budget_var.set("twelve")
        app._on_budget_change()
        assert monitor.budget == 12.5

        # A cap under the spend would stop the run: declining keeps the old one.
        answers.append(False)
        app._budget_var.set("3")
        app._on_budget_change()
        assert monitor.budget == 12.5 and not token.cancelled
        assert float(app._budget_var.get()) == 12.5

        app._budget_on_var.set(False)
        app._on_budget_change()
        assert monitor.budget is None
        assert preferences.get_bool(prefs, preferences.BUDGET_CAP_ENABLED) is False

        # ...and accepting it stops the run at once.
        answers.append(True)
        app._budget_on_var.set(True)
        app._budget_var.set("3")
        app._on_budget_change()
        assert token.cancelled and monitor.snapshot().budget_hit.limit == 3.0
        assert preferences.get_str(prefs, preferences.BUDGET_CAP_AMOUNT) == "3"


def test_full_qc_confirmation_opt_out_persists_and_can_be_turned_back_on(tmp_path, monkeypatch):
    from drawing_analyzer.core import preferences

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-no-network")
    pdf = _preview_pdf(tmp_path)
    prefs = tmp_path / "config" / "gui_preferences.json"
    with _gui_module() as (gui, tk):
        app, started, logs = _inputs_app(gui, tk, monkeypatch)
        app.__dict__.update(_pdfs=[pdf], _prefs_path=prefs)
        app._qc_markups_var.set(True)
        asked = []
        answer = (True, True)    # "Yes" with "Don't show this again" ticked
        monkeypatch.setattr(
            gui, "_ask_cost_confirmation",
            lambda parent, title, prompt: asked.append(prompt) or answer,
        )

        app._on_process()
        assert len(asked) == 1 and len(started) == 1
        assert preferences.get_bool(prefs, preferences.SKIP_FULL_QC_CONFIRM) is True

        # A restarted GUI reads the stored choice: no dialog, the run starts,
        # and the estimate still reaches the log.
        app._busy = False
        app._confirm_full_qc_var.set(
            not preferences.get_bool(prefs, preferences.SKIP_FULL_QC_CONFIRM)
        )
        logs.clear()
        app._on_process()
        assert len(asked) == 1 and len(started) == 2
        assert any("confirmation skipped" in line and "$" in line for line in logs)

        # The QC-section box turns the dialog back on, and a plain "Yes" keeps it on.
        app._busy = False
        app._confirm_full_qc_var.set(True)
        app._on_confirm_full_qc_toggle()
        answer = (True, False)
        app._on_process()
        assert len(asked) == 2 and len(started) == 3
        assert preferences.get_bool(prefs, preferences.SKIP_FULL_QC_CONFIRM) is False


@pytest.mark.parametrize("content", [None, "{not json", "[1, 2]", '{"skip_full_qc_cost_confirm": "yes"}'])
def test_unusable_preferences_read_as_default_and_writes_keep_other_keys(tmp_path, content):
    from drawing_analyzer.core import preferences

    path = tmp_path / "gui_preferences.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert preferences.get_bool(path, preferences.SKIP_FULL_QC_CONFIRM) is False
    assert preferences.set_preference(path, "other", 3)
    assert preferences.set_preference(path, preferences.SKIP_FULL_QC_CONFIRM, True)
    assert preferences.get_bool(path, preferences.SKIP_FULL_QC_CONFIRM) is True
    assert preferences.load_preferences(path)["other"] == 3


def test_remove_drops_one_drawing_and_remeasures_the_rest(tmp_path, monkeypatch):
    a, b = _preview_pdf(tmp_path), tmp_path / "other.pdf"
    b.write_bytes(a.read_bytes())
    with _gui_module() as (gui, tk):
        app, workers, callbacks, _ = _cost_preview_app(gui, tk, monkeypatch)
        app.__dict__.update(_ctx=object(), _log=lambda *a, **k: None)
        app._remove_pdf = types.MethodType(gui.DrawingAnalyzerApp._remove_pdf, app)
        app._add_pdfs([a, b])
        workers.pop()()
        callbacks.pop()()
        assert len(app._usable_preflight_bases()) == 6
        app._remove_pdf(b)
        assert app._pdfs == [a] and app._ctx is None
        # The two-file bases no longer describe the list: cleared, re-measured.
        assert app._usable_preflight_bases() is None
        workers.pop()()
        callbacks.pop()()
        assert len(app._usable_preflight_bases()) == 3


def test_loading_documents_adds_to_the_category_and_remove_rebuilds_its_text(tmp_path, monkeypatch):
    from drawing_analyzer.spec_documents import SpecDocument

    def doc(name, text):
        return SpecDocument(path=tmp_path / name, display_name=name, text=text)

    with _gui_module() as (gui, tk):
        app, _, _ = _inputs_app(gui, tk, monkeypatch)
        app._apply_documents_result("specs", [doc("a.docx", "ALPHA")])
        app._apply_documents_result("specs", [doc("b.docx", "BRAVO")])
        assert [d.display_name for d in app._spec_documents] == ["a.docx", "b.docx"]
        assert "ALPHA" in app._specs_text and "BRAVO" in app._specs_text
        # Picking a file again replaces its earlier copy rather than doubling it.
        app._apply_documents_result("specs", [doc("a.docx", "ALPHA v2")])
        assert app._specs_text.count("ALPHA") == 1 and "ALPHA v2" in app._specs_text
        app._remove_document("specs", tmp_path / "b.docx")
        assert "BRAVO" not in app._specs_text
        # Context is its own category; the specs are untouched by it.
        app._apply_documents_result("context", [doc("bod.txt", "CONTEXT")])
        assert app._current_context_text().endswith("CONTEXT")
        assert "CONTEXT" not in app._current_specs_text()


# --------------------------------------------------------------------------- #
# Live view
# --------------------------------------------------------------------------- #


def test_idle_board_previews_the_loaded_set_and_the_planned_stack(tmp_path, monkeypatch):
    from drawing_analyzer.render import list_sheets

    pdf = _preview_pdf(tmp_path)
    with _gui_module() as (gui, tk):
        app, _workers, _callbacks, _ = _cost_preview_app(gui, tk, monkeypatch)
        previews = []
        app._live = types.SimpleNamespace(
            preview=lambda rows, stages, revision=None: previews.append((rows, stages, revision)))
        app._live_sheet_key, app._live_sheet_rows = None, []
        app._refresh_live_preview = types.MethodType(
            gui.DrawingAnalyzerApp._refresh_live_preview, app)
        app._pdfs = [pdf]
        app._refresh_live_preview()
        app._qc_markups_var.set(True)
        app._refresh_live_preview()
        (rows, plain, revision), (_rows, full, _rev) = previews
        assert [r[1] for r in rows] == [ref.display_label for ref in list_sheets([pdf])]
        assert revision == gui.sources_fingerprint([pdf])   # file content, not just ids
        assert "critique" not in plain and {"critique", "verification", "markup"} <= set(full)
        app._busy = True                            # a run owns the board
        app._refresh_live_preview()
        assert len(previews) == 2


def test_live_view_choice_is_remembered_beside_other_preferences(tmp_path):
    from drawing_analyzer.core import preferences

    prefs = tmp_path / "gui_preferences.json"
    preferences.set_preference(prefs, preferences.SKIP_FULL_QC_CONFIRM, True)
    assert preferences.get_bool(prefs, preferences.LIVE_VIEW, True) is True   # default: on
    with _gui_module() as (gui, _tk):
        toggled = []
        stub = types.SimpleNamespace(
            _prefs_path=prefs, _live=types.SimpleNamespace(set_enabled=toggled.append))
        gui.DrawingAnalyzerApp._remember_live_view(stub, False)
        # The Live view's showing tab is kept the same way, and a click's wheel
        # delta is read as notches on either platform's convention.
        gui.DrawingAnalyzerApp._remember_live_tab(stub, "findings")
        steps = [gui._wheel_steps(d) for d in (120, -240, 1, -9, 0)]
    assert toggled == [False]
    assert preferences.get_bool(prefs, preferences.LIVE_VIEW, True) is False
    assert preferences.get_bool(prefs, preferences.SKIP_FULL_QC_CONFIRM) is True
    assert preferences.get_str(prefs, preferences.LIVE_TAB) == "findings"
    assert steps == [1.0, -2.0, 1.0, -3.0, 0.0]


def test_checks_kept_from_the_plan_tab_are_marked_logged_and_listed(tmp_path):
    from drawing_analyzer import checklist_save as cs
    from drawing_analyzer.live_tabs import CopyRequest

    plan = cs.save_new("Data center FP", [
        cs.PickedCheck("M1.1", "Each data hall states its preaction type"),
        cs.PickedCheck("M1.2", "Hangers are braced for the seismic design category"),
        cs.PickedCheck("M1.3", "hangers are braced for the seismic design category."),
    ], known=[("U1.1", "Each data hall states its preaction type")], directory=tmp_path)
    with _gui_module() as (gui, _tk):
        marked, said, logged, reloaded, clip = [], [], [], [], []
        stub = types.SimpleNamespace(
            _live=types.SimpleNamespace(
                mark_saved=lambda ids, label, held, message="": marked.append(
                    (ids, label, held, message)),
                announce=lambda text, level="good": said.append(text)),
            _log=lambda m, **k: logged.append((m, k.get("level"))),
            _reload_profile_panel=lambda: reloaded.append(True),
            clipboard_clear=clip.clear, clipboard_append=clip.append,
        )
        gui.DrawingAnalyzerApp._on_checks_saved(stub, plan)
        gui.DrawingAnalyzerApp._on_live_request(stub, CopyRequest("M1.5", "Obstruction rules"))
    ids, label, held, message = marked[0]
    # The kept check is tagged with its checklist; the skipped ones say where
    # their text already was (the person's own U1.1, the M1.2 picked with it).
    assert (ids, label, held) == (["M1.2"], plan.name, {"M1.1": "U1.1", "M1.3": "M1.2"})
    assert logged == [(f"{message} ({plan.path.name} in your profiles folder)", "success")]
    assert reloaded == [True]                    # the Review profiles list re-reads the folder
    assert clip == ["Obstruction rules"] and said == ["Copied M1.5 to the clipboard"]

    # Saved mid-run: the profile list is re-read at once, but the suggestion
    # that ticks a matching checklist waits for the run to end (the preflight
    # never runs while busy), and then runs once.
    with _gui_module() as (gui, _tk):
        suggested, built = [], []
        app = types.SimpleNamespace(
            _profile_holder=types.SimpleNamespace(winfo_children=lambda: []),
            _profile_vars={}, _build_profile_panel=built.append,
            _pdfs=[tmp_path / "FP-101.pdf"], _busy=True, _suggest_after_busy=False,
            _refresh_profile_suggestions=lambda: suggested.append(True),
        )
        gui.DrawingAnalyzerApp._reload_profile_panel(app)
        assert built and suggested == []
        gui._resume_deferred_suggestions(app)              # still busy
        assert suggested == []
        app._busy = False
        gui._resume_deferred_suggestions(app)
        gui._resume_deferred_suggestions(app)
    assert suggested == [True]
