"""Standalone CustomTkinter window for the drawing-context extractor.

Drop (or browse for) construction drawing PDFs, press Analyze, and the
subsystem renders + digests every sheet and shows the combined text digest,
which can be saved to a ``.md`` file for use as Project Context in the spec
reviewer. Runs the analysis on a worker thread so the UI stays responsive, and
reuses the main app's color palette for a consistent look.

Launch with ``python -m drawing_analyzer``.
"""
from __future__ import annotations

import math
import os
import shlex
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, filedialog, messagebox



def _gui_toolkit_unavailable(exc: BaseException) -> "BaseException":
    """Report a missing GUI toolkit the only way a windowed app can (P9 item 47).

    ``customtkinter`` is in the ``gui`` extra, so ``pip install drawing-analyzer``
    without it installs a working engine and a launcher that cannot start. The
    launcher is declared under ``[project.gui-scripts]``, which on Windows builds
    a console-less ``.exe``: the ``ModuleNotFoundError`` is written to a stdout
    that does not exist, so running ``drawing-analyzer`` produced **nothing at
    all** — no window, no message, no exit code the user ever sees. The frozen
    PyInstaller build is windowed for the same reason.

    ``tkinter`` is stdlib and ships with every Windows Python (and PyInstaller
    bundles it), so a messagebox is the one output channel that survives; if even
    that is unavailable this still writes to stderr and returns the error to
    raise. Returns rather than raises so the caller's ``raise ... from exc``
    keeps the original traceback.
    """
    detail = f"{type(exc).__name__}: {exc}"
    message = (
        "Drawing Analyzer could not start because its user-interface "
        "libraries are missing.\n\n"
        f"{detail}\n\n"
        "Install the GUI extras and try again:\n\n"
        '    pip install "drawing-analyzer[gui]"'
    )
    try:
        messagebox.showerror("Drawing Analyzer - cannot start", message)
    except Exception:  # noqa: BLE001 - no display, or tkinter itself is broken
        pass
    try:
        print(message, file=sys.stderr)
    except Exception:  # noqa: BLE001 - a windowed build may have no stderr either
        pass
    return ImportError(message)


try:
    import customtkinter as ctk
except Exception as _ctk_exc:  # noqa: BLE001 - any import failure is fatal here
    raise _gui_toolkit_unavailable(_ctk_exc) from _ctk_exc

try:  # drag-and-drop is optional (mirrors the main app shell)
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - optional/native Tk can be unavailable
    DND_FILES = None
    TkinterDnD = None

if TkinterDnD is not None:
    class _CTkDnDRoot(ctk.CTk, TkinterDnD.DnDWrapper):
        pass
else:  # pragma: no cover - exercised only without tkinterdnd2
    _CTkDnDRoot = ctk.CTk

from . import __version__, diagnostics
from .cancellation import CancelToken, RunCancelled
from .core import preferences, updates
from .core.api_config import REVIEW_MODEL_DEFAULT
from .core.api_key_store import (
    SecureKeyStorageUnavailable,
    load_api_key_from_file,
    save_api_key,
)
from .core.app_paths import api_key_paths, app_config_dir
from .colors import COLORS
from .source_registry import sources_fingerprint
from .cost import (
    drawing_file_tokens,
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
    estimate_text_tokens,
    format_drawing_cost_prompt,
    format_exhaustive_cost_prompt,
    spend_forecast,
    xfast_note,
)
from .live_spend import SpendMonitor, format_money, format_spend_line
from .help_content import (
    GET_API_KEY,
    HELP_DOCUMENTS,
    PROCESSING_MODE_ECONOMY,
    PROCESSING_MODE_HYBRID,
    PROCESSING_MODES,
    HelpDocument,
    help_document,
    processing_fast_mode,
    processing_transports,
    transport_hint,
)
from .call_telemetry import sheet_item
from .html_report import build_html_report
from .live_panel import LivePanel
from .live_scene import BG as LIVE_BG
from .live_view import planned_stages
from .models import resolve_run_configuration
from .pipeline import DrawingContext, _resolve_save_tiles, extract_drawing_context
from .render import list_sheets
from .spec_documents import (
    CONTEXT_TOTAL_CHAR_BUDGET,
    SPEC_TOTAL_CHAR_BUDGET,
    SpecBudget,
    SpecDocument,
)

_PDF_FILETYPES = [("PDF drawings", "*.pdf"), ("All files", "*.*")]

_SPEC_FILETYPES = [
    ("Spec documents", "*.pdf *.docx *.txt *.md"),
    ("PDF", "*.pdf"),
    ("Word (.docx)", "*.docx"),
    ("Text", "*.txt"),
    ("Markdown", "*.md"),
    ("All files", "*.*"),
]

_CHECKLIST_FILETYPES = [
    ("Checklists", "*.md *.txt *.docx *.pdf *.xlsx *.xlsm *.csv"),
    ("Excel", "*.xlsx *.xlsm"),
    ("Word (.docx)", "*.docx"),
    ("PDF", "*.pdf"),
    ("Markdown / text", "*.md *.txt"),
    ("CSV", "*.csv"),
    ("All files", "*.*"),
]

_ATLAS_FILETYPES = [
    ("Excel workbook", "*.xlsx *.xlsm"),
    ("CSV", "*.csv"),
    ("All files", "*.*"),
]

# Width of a file row's label before it wraps; the Remove button sits right.
_FILE_ROW_WRAP = 600

_SPEC_WARNING_TITLE = "Confirm project specification documents"
_SPEC_WARNING_BODY = (
    "You're about to attach project specification documents for this run.\n\n"
    "For QC to be meaningful, these must be the REAL, COMPLETE, CURRENT "
    "project specifications — not a placeholder, an early draft, or an "
    "unrelated template. Uploading incomplete or inaccurate specs will "
    "reduce the quality of the QC findings (missed conflicts, or wrong "
    "ones).\n\n"
    "Choose spec document(s) now?"
)

_log = diagnostics.get_logger()

# Collapsible-section carets. Kept as constants so switching to the full-size
# glyphs (▼/►) or ASCII (−/+) is a one-line change if a target machine renders
# the small triangles as tofu.
_CARET_OPEN = "▾"
_CARET_SHUT = "▸"

# The Activity section's two views (the toggle's labels).
_VIEW_LIVE = "Live view"
_VIEW_LOG = "Log"


class CollapsibleSection:
    """A click-to-toggle section: a thin header bar over a hideable body frame.

    Each section owns its own ``container`` (packed into the parent where the
    old flat ``*_row`` frame used to pack), holding a full-width header button
    and a ``body`` frame. Collapsing ``pack_forget()``s the body; expanding
    re-``pack()``s it — and because the container is never unpacked and the
    header is always its first child, the body re-appears directly under its
    header, so toggling never reorders sibling sections (no re-pack needed).

    ``summary_provider`` is an optional zero-arg callable read lazily on every
    header render, so the collapsed bar can show live state (e.g. "2 on")
    without any edits to the existing state handlers.

    ``expand=True`` makes the section claim vertical slack: its container and
    body pack with ``fill="both", expand=True`` so the body grows to fill the
    window. The container keeps ``expand=True`` even while collapsed, so its
    header stays anchored under the content above it and the reclaimed space
    falls below the header (sibling widgets never shift) — used by the activity
    log, the one section that should absorb the space collapsed sections hand
    back and hand its own back when collapsed.

    ``hold_when_collapsed=False`` (with ``expand=True``) is for an expanding
    section in the *middle* of the window — the loaded-files list: collapsed,
    its container drops back to ``fill="x"`` without ``expand`` so it leaves
    no empty gap; expanded, it shares the slack with the log again. Its
    position in the packing order never changes (``pack_configure``).

    ``on_toggle(expanded)`` (optional) is told after every collapse/expand —
    the Activity section uses it to wake the Live view when it is re-opened
    (collapsed, the board draws nothing).
    """

    def __init__(
        self,
        master,
        title: str,
        *,
        expanded: bool = True,
        summary_provider=None,
        pady=(0, 8),
        expand: bool = False,
        hold_when_collapsed: bool = True,
        on_toggle=None,
    ) -> None:
        self.title = title
        self._expanded = expanded
        self._on_toggle = on_toggle
        self._summary_provider = summary_provider
        self._expand = expand
        self._hold_when_collapsed = hold_when_collapsed
        # Reproduces each old *_row's geometry exactly so surrounding spacing is
        # unchanged (the sections used fill="x", padx=16, pady=(0, 8)). An
        # ``expand`` section instead claims the vertical slack (fill="both",
        # expand=True) and keeps it even while collapsed (see the class docstring).
        self.container = ctk.CTkFrame(master, fg_color="transparent")
        if expand and (expanded or hold_when_collapsed):
            self.container.pack(fill="both", expand=True, padx=16, pady=pady)
        else:
            self.container.pack(fill="x", padx=16, pady=pady)
        # A CTkButton makes the whole row clickable with hover for free; a bare
        # frame wouldn't receive clicks that land on a child label on top of it.
        self.header = ctk.CTkButton(
            self.container, text="", anchor="w", corner_radius=6, height=28,
            fg_color="transparent", hover_color=COLORS["bg_input"],
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            command=self.toggle,
        )
        self.header.pack(fill="x")
        self.body = ctk.CTkFrame(self.container, fg_color="transparent")
        if self._expanded:
            self._pack_body()
        self._render_header()

    def _pack_body(self) -> None:
        """Pack the body with the fill mode this section was built for."""
        if self._expand:
            self.body.pack(fill="both", expand=True)
        else:
            self.body.pack(fill="x")

    def toggle(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self._pack_body()
        else:
            self.body.pack_forget()
        if self._expand and not self._hold_when_collapsed:
            if self._expanded:
                self.container.pack_configure(fill="both", expand=True)
            else:
                self.container.pack_configure(fill="x", expand=False)
        self._render_header()
        if self._on_toggle is not None:
            try:
                self._on_toggle(self._expanded)
            except Exception:  # noqa: BLE001 - a listener must never break the toggle
                pass

    def set_expanded(self, expanded: bool) -> None:
        """Idempotently force a collapse/expand (used by host auto-collapse)."""
        if expanded != self._expanded:
            self.toggle()

    @property
    def expanded(self) -> bool:
        """Whether the body is currently shown (read-only)."""
        return self._expanded

    def refresh(self) -> None:
        """Re-pull the state summary into the collapsed/expanded header bar."""
        self._render_header()

    def _render_header(self) -> None:
        caret = _CARET_OPEN if self._expanded else _CARET_SHUT
        summary = ""
        if self._summary_provider is not None:
            try:
                text = self._summary_provider()
            except Exception:  # noqa: BLE001 - a summary must never break the UI
                text = ""
            if text:
                summary = f"   —  {text}"
        self.header.configure(text=f"{caret}  {self.title}{summary}")


class DrawingAnalyzerApp(_CTkDnDRoot):
    """Minimal standalone window driving the drawing-digest pipeline."""

    def __init__(self) -> None:
        super().__init__()
        if TkinterDnD is not None:
            try:  # initialize the tkdnd runtime, as the main app does
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception:
                pass

        self.title("Drawing Context Analyzer")
        # The optional sections (and the API key when a key is already loaded)
        # start collapsed; the Activity slot (Live view / log) and the
        # Loaded-files list — the two expand=True sections — share any slack and
        # grow as sections collapse. 720 tall fits the file list's minimum
        # beside the QC and Processing headers with every action row visible
        # (they are packed first); open taller when the screen has room, so
        # the Live view board gets space to breathe.
        # CTk scales geometry by its window scaling, so compare in its units.
        try:
            scaling = float(ctk.ScalingTracker.get_window_scaling(self)) or 1.0
            screen_h = int(self.winfo_screenheight() / scaling)
        except Exception:  # noqa: BLE001 - no screen metrics; keep the old size
            screen_h = 0
        height = max(720, min(880, screen_h - 110)) if screen_h else 720
        self.geometry(f"820x{height}")
        # Width floor: the header must fit the title (~230px) plus the
        # four-button bar (3×112 + 68 + padding ≈ 428px) inside the 32+32px
        # outer/card padding — 640 clipped the row once "About" was added.
        self.minsize(740, 560)
        self.configure(fg_color=COLORS["bg_dark"])
        # Closing the window while a run is in flight throws the run away: the
        # worker threads are daemons, so the interpreter exits without them and
        # nothing has been exported yet (the export happens after the analysis
        # returns). A run costs real money and can take an hour, and the three
        # secondary windows in this app each already confirm on close while the
        # MAIN one did not — one stray click on the X and the whole set was gone
        # with no prompt (P9 item 47).
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        # An exception raised inside a Tk callback goes to Tk's own handler,
        # which writes a traceback to stderr — and this is a windowed build with
        # no stderr, so the app simply appeared to ignore the click (N32). Route
        # it to the diagnostics trace and tell the user something failed.
        self.report_callback_exception = self._on_callback_exception

        self._pdfs: list[Path] = []
        self._ctx: DrawingContext | None = None
        self._busy = False
        self._export_busy = False
        # The running analysis's kill switch (Stop button, and quitting mid-run);
        # None while no analysis runs. See drawing_analyzer.cancellation.
        self._run_cancel: CancelToken | None = None
        # The current (or last) run's live spend, read by the spend line.
        self._spend: SpendMonitor | None = None
        self._quitting = False
        # Uploaded project specifications (optional) — see spec_documents.py.
        # Distinct from "Per-run focus" below: this is ground-truth reference
        # material, extracted once at upload time (not a live textbox).
        self._spec_documents: list[SpecDocument] = []
        self._specs_text: str = ""
        self._specs_budget: SpecBudget | None = None
        # Additional project context (background documents: basis of design,
        # owner standards, prior comments) — extracted and budgeted like the
        # specs, sent beside them under its own prompt block.
        self._context_documents: list[SpecDocument] = []
        self._context_text: str = ""
        self._context_budget: SpecBudget | None = None
        # Uploaded checklist files, each parsed into a review Profile the QC
        # critique applies item by item (profiles.load_checklist_file).
        self._checklists: list = []
        # AHJ Atlas Input (optional): the loaded workbook and the jurisdiction
        # chosen from it. Its editions govern the run (governing_editions=).
        self._atlas = None
        self._atlas_choice = None
        # While a run or an extraction is in flight the file list's Add/Remove
        # buttons are disabled (inputs are snapshotted at Analyze).
        self._inputs_locked = False
        self._last_log_msg: str | None = None
        # Latest activity-log line, surfaced in the log section's collapsed
        # header so the most recent status stays visible without expanding it.
        self._log_summary_text: str | None = None
        # QC review options (see _build_ui). Reference audit is free; QC markups
        # add the verification pass + a marked-up PDF. Under the Part III gating
        # amendment (§18) the exhaustive default inks everything except REJECTED;
        # the "Verified & deterministic only" sub-toggle is the conservative
        # opt-in (default OFF), and "Include rejected (grey)" opts rejected
        # findings back onto the paper in a struck style.
        self._qc_markups_var = BooleanVar(value=False)
        self._qc_verified_only_var = BooleanVar(value=False)
        self._ink_rejected_var = BooleanVar(value=False)
        self._reference_audit_var = BooleanVar(value=False)
        # Named transport plans: Economy batches digest + critique, Hybrid runs
        # digests now and batches critique, Fast runs both now. The GUI passes
        # both resolved values explicitly, so the choice is auditable.
        self._processing_mode_var = StringVar(value=PROCESSING_MODE_ECONOMY)
        # Review-profile selection (Phase 24 §16.4): name -> checkbox var, plus the
        # sets of profiles the user manually forced on/off — a manual override always
        # wins and survives a later preflight auto-suggest refresh. Preflight PyMuPDF
        # access is serialized (not thread-safe) and generation-guarded (latest wins).
        self._profile_vars: dict[str, BooleanVar] = {}
        self._profile_forced_on: set[str] = set()
        self._profile_forced_off: set[str] = set()
        self._profile_suggested: set[str] = set()
        self._preflight_lock = threading.Lock()
        # WP-05 §10.3: the cost bases the preflight produced, and a fingerprint of
        # the exact files on disk they describe. Never a partial list — a
        # half-scanned set must price conservatively, not blend two bases.
        self._preflight_bases: "list | None" = None
        self._preflight_fingerprint: "tuple | None" = None
        self._preflight_gen = 0
        # HTML report: off by default the key is NOT written into the file (the
        # Ask-AI panel prompts for one at runtime). On restores the old embedded
        # -key convenience — with a red warning in the report; don't share it.
        self._embed_key_var = BooleanVar(value=False)
        # Diagnostics: stage every rendered tile PNG into the export's tiles/
        # folder. Starts from DRAWING_ANALYZER_SAVE_TILES; the box then wins.
        self._save_tiles_var = BooleanVar(value=_resolve_save_tiles(None))
        # Full-QC cost confirmation: on unless the user ticked "Don't show this
        # again" in that dialog. Persisted in gui_preferences.json; the QC
        # section's "Confirm estimated cost" box turns it back on.
        self._prefs_path = preferences.default_preferences_path()
        self._confirm_full_qc_var = BooleanVar(
            value=not preferences.get_bool(
                self._prefs_path, preferences.SKIP_FULL_QC_CONFIRM
            )
        )
        # Budget cap: stops the run when its spend reaches the amount. Both
        # stay editable while a run works (see _on_budget_change).
        self._budget_on_var = BooleanVar(
            value=preferences.get_bool(self._prefs_path, preferences.BUDGET_CAP_ENABLED)
        )
        self._budget_var = StringVar(
            value=preferences.get_str(self._prefs_path, preferences.BUDGET_CAP_AMOUNT)
        )
        self._key_shown = False
        self._initial_key = self._load_api_key()
        self._has_key = bool(self._initial_key)
        # Tracks what's currently persisted so finishing an edit only rewrites
        # the store when the key actually changed (and never auto-persists an
        # unchanged, env-supplied key).
        self._persisted_key = self._initial_key
        # Open help modals ("How to use" / "How it works" / "Why trust it?" /
        # "About", plus the standalone API-key and runtime-transparency
        # panels), keyed by HelpDocument.key so a second click re-focuses the
        # existing window instead of stacking a duplicate.
        self._help_windows: dict[str, ctk.CTkToplevel] = {}
        # A help modal opened *from another help modal* (the "I'm not
        # convinced" link) records its opener here, so closing the child hands
        # the application-modal grab back to its parent instead of leaving the
        # still-visible parent ungrabbed.
        self._help_parents: dict[str, ctk.CTkToplevel] = {}
        # Resizable pop-out editor for the per-run focus box (see
        # _open_focus_popout); focus_popout_box is None whenever it's closed.
        self._focus_popout: ctk.CTkToplevel | None = None
        self.focus_popout_box: ctk.CTkTextbox | None = None
        # Self-update checker (Windows desktop build). The last-check date and
        # any "skipped" version persist in the app config dir; the network
        # fetch/download always runs off the UI thread. See core/updates.py and
        # docs/RELEASE_WINDOWS.md.
        self._update_state_path = updates.default_state_path()
        self._update_checking = False
        # Guards the download lifecycle: only one download at a time, and a
        # download whose dialog was dismissed is cancelled so its completion
        # never pops a stray install prompt. (The daemon worker can't be killed,
        # but its result is ignored.)
        self._update_downloading = False
        self._update_download_cancelled = False
        self._update_dialog: ctk.CTkToplevel | None = None
        # Live view (live_panel.py): the animated run board. Built in _build_ui;
        # None until then (and in handler tests that drive a stub ``self``).
        # The sheet rows are cached by the files' fingerprint so a QC toggle
        # does not reopen every PDF.
        self._live: LivePanel | None = None
        self._live_selected = False
        self._live_sheet_key: "tuple | None" = None
        self._live_sheet_rows: list = []
        self._log_unseen = 0

        self._build_ui()
        self._register_dnd()
        self._refresh_summary()
        self._refresh_files_panel()
        # Silent, throttled (once/day) update check shortly after the window
        # paints — never blocks startup, and only surfaces a dialog when an
        # update is actually available. The footer's "Check for Updates" button
        # runs the same path on demand with visible results.
        self.after(1500, self._maybe_auto_check_for_updates)

    # ------------------------------------------------------------------ setup

    def _load_api_key(self) -> str:
        """Resolve a key from the environment or saved store and apply it.

        Returns the resolved key (or ``""``) so the caller can both flip the
        ``_has_key`` flag and pre-fill the key field. The env var wins over the
        saved store, matching the precedence the rest of the app expects.
        """
        key = os.environ.get("ANTHROPIC_API_KEY") or load_api_key_from_file()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
        return key

    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=8)
        outer.pack(fill="both", expand=True, padx=16, pady=(16, 12))

        # Footer packed first (side="bottom") so the version + "Check for
        # Updates" strip reserves the bottom edge before the content below
        # claims the remaining space with expand=True.
        self._build_footer(outer)

        # Header row: title on the left, the header buttons on the right
        # ("How to use", "How it works", "Why trust it?", "About"). Each opens
        # a scrollable modal built from help_content.py (pure text, no engine
        # dependency) via _open_help_modal.
        header = ctk.CTkFrame(outer, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(20, 4))
        ctk.CTkLabel(
            header,
            text="Drawing Context Analyzer",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left", anchor="w")
        self._build_help_buttons(header)
        ctk.CTkLabel(
            outer,
            text=(
                "Drop construction drawing PDFs "
                "(one or many; multi-sheet PDFs are split page-by-page). "
                "Each sheet is read by Claude Opus 5.5 and summarized to text."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            wraplength=740,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # API key — paste a key here when ANTHROPIC_API_KEY isn't set in the
        # environment. It applies the moment it's entered (no button), and is
        # saved (OS keyring, or a local key file) when editing finishes.
        # Collapsed on launch when a key is already loaded (the common case);
        # expanded when there's none, so a first-run user is prompted for it.
        self._key_sec = CollapsibleSection(
            outer, "Anthropic API Key", expanded=not self._has_key,
            pady=(0, 10),
            summary_provider=lambda: "loaded"
            if getattr(self, "_key_var", None) and self._key_var.get().strip()
            else "no key",
        )
        # The section body stacks vertically: the entry + buttons on one row,
        # then the "how do I get a key?" hint beneath it — so the hint hides
        # along with the field when the section is collapsed (key already set).
        key_row = ctk.CTkFrame(self._key_sec.body, fg_color="transparent")
        key_row.pack(fill="x")
        self._key_var = StringVar(value=self._initial_key or "")
        self.key_entry = ctk.CTkEntry(
            key_row, show="•", textvariable=self._key_var,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"], height=32,
        )
        self.key_entry.pack(side="left", fill="x", expand=True)
        # Apply on every edit (typing, Ctrl+V, right-click paste) so the app is
        # ready to analyze as soon as a key is present; persist on finish.
        self._key_var.trace_add("write", self._on_key_changed)
        self.key_entry.bind("<FocusOut>", self._persist_key)
        self.key_entry.bind("<Return>", self._persist_key)
        self.key_show_btn = ctk.CTkButton(
            key_row, text="Show", width=64, height=32,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=self._on_toggle_key,
        )
        self.key_show_btn.pack(side="left", padx=(8, 0))
        self.key_status_label = ctk.CTkLabel(
            key_row, text="", font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_muted"],
        )
        self.key_status_label.pack(side="left", padx=(8, 0))

        # "How do I get a key?" — most users have never seen an API key. A small
        # clickable hint under the field opens the terse step-by-step guide
        # (help_content.GET_API_KEY) so they're never left stuck at this first
        # wall. Rendered as an underlined link that reuses the help-modal path.
        # Lives inside the key section so it collapses away with the field.
        hint_row = ctk.CTkFrame(self._key_sec.body, fg_color="transparent")
        hint_row.pack(fill="x", pady=(6, 0))
        ctk.CTkLabel(
            hint_row, text="Don't have a key?",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        ).pack(side="left", padx=(0, 6))
        get_key_link = ctk.CTkLabel(
            hint_row, text="How do I get one?",
            font=ctk.CTkFont(family="Segoe UI", size=11, underline=True),
            text_color=COLORS["accent_glow"], cursor="hand2",
        )
        get_key_link.pack(side="left")
        get_key_link.bind(
            "<Button-1>", lambda _e: self._open_help_modal(GET_API_KEY)
        )

        # Drop zone. Expanded on launch (and while empty): drag-and-drop is
        # registered only on this widget (_register_dnd), so a hidden drop
        # target can't receive files — the host auto-collapses it once files
        # are loaded (and re-expands on Clear) via _sync_dropzone_section().
        self._drop_sec = CollapsibleSection(
            outer, "Drawing PDFs",
            summary_provider=lambda: f"{len(self._pdfs)} PDF(s)"
            if self._pdfs else "",
        )
        self.drop_zone = ctk.CTkFrame(
            self._drop_sec.body, fg_color=COLORS["bg_input"], corner_radius=8,
            border_width=2, border_color=COLORS["border"], height=90,
        )
        self.drop_zone.pack(fill="x")
        self.drop_zone.pack_propagate(False)
        self.drop_label = ctk.CTkLabel(
            self.drop_zone,
            text="Drop drawing PDFs here  —  or  —",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_muted"],
        )
        self.drop_label.pack(side="left", expand=True, padx=(16, 4), pady=16)
        ctk.CTkButton(
            self.drop_zone, text="Browse…", width=110, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_card"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=self._on_browse,
        ).pack(side="right", padx=(4, 16), pady=16)

        # Optional per-run focus — free text the operator can add at their
        # discretion. The standard digest is always produced unchanged; a focus
        # additionally asks each sheet read for "Focus findings" and adds a
        # set-level Focus Report deliverable answering it. Snapshotted when
        # Analyze is pressed (mid-run edits don't affect a running analysis).
        self._focus_sec = CollapsibleSection(
            outer, "Per-run focus (optional)", expanded=False,
            summary_provider=lambda: "set"
            if getattr(self, "focus_box", None)
            and self.focus_box.get("1.0", "end").strip()
            else "",
        )
        focus_row = self._focus_sec.body
        ctk.CTkLabel(
            focus_row,
            text=(
                "Anything you particularly want pulled out this run — e.g. "
                "“the rooms, and what types of plumbing fixtures each has”. "
                "You always get the standard digest; a focus adds a Focus "
                "Report on top. Changing the focus re-analyzes sheets (cached "
                "results from other focuses don't apply). Click “Expand” to "
                "edit in a larger, resizable window."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
            wraplength=740,
            justify="left",
        ).pack(anchor="w")
        focus_box_row = ctk.CTkFrame(focus_row, fg_color="transparent")
        focus_box_row.pack(fill="x", pady=(4, 0))
        self.focus_box = ctk.CTkTextbox(
            focus_box_row, height=56, fg_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=2,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=12), wrap="word",
        )
        self.focus_box.pack(side="left", fill="x", expand=True)
        # Keep the cost line live as the focus toggles between empty/non-empty
        # (a focus adds the focus-report pass to the estimate); also mirrors
        # into the pop-out editor below when it's open.
        self.focus_box.bind(
            "<KeyRelease>", lambda _e: self._sync_focus_boxes(self.focus_box)
        )
        self.focus_expand_btn = ctk.CTkButton(
            focus_box_row, text="Expand", width=70, height=28,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color=COLORS["bg_card"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=self._open_focus_popout,
        )
        self.focus_expand_btn.pack(side="left", padx=(6, 0))

        # Loaded files — every input this run will send, by category, each
        # file with its own Remove button and every category with its token
        # count. Specifications and additional context ride every sheet's
        # digest prompt; checklists ride the QC critique; the AHJ Atlas Input
        # sets the governing code editions. Drawings come from the drop zone
        # above or "Add drawings…" here. Rebuilt by _refresh_files_panel.
        self._files_sec = CollapsibleSection(
            outer, "Loaded files", expanded=False,
            summary_provider=self._files_summary,
            expand=True, hold_when_collapsed=False,
        )
        files_body = self._files_sec.body
        add_row = ctk.CTkFrame(files_body, fg_color="transparent")
        add_row.pack(fill="x", pady=(2, 4))
        self._add_buttons: dict[str, ctk.CTkButton] = {}
        for key, text, width, command in (
            ("drawings", "Add drawings…", 118, self._on_browse),
            ("specs", "Add specs…", 104, self._on_upload_specs),
            ("checklists", "Add checklists…", 124, self._on_add_checklists),
            ("context", "Add context…", 112, self._on_add_context),
            ("atlas", "Load AHJ Atlas Input…", 170, self._on_load_atlas),
        ):
            btn = ctk.CTkButton(
                add_row, text=text, width=width, height=30,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                fg_color=COLORS["bg_card"], hover_color=COLORS["border"],
                border_width=1, border_color=COLORS["border"],
                text_color=COLORS["text_secondary"], command=command,
            )
            btn.pack(side="left", padx=(0, 6))
            self._add_buttons[key] = btn
        # Back-compat handle: the specs button keeps its old attribute name.
        self.upload_specs_btn = self._add_buttons["specs"]
        # A small requested height: the list grows into the window's slack
        # (shared with the activity log) and scrolls past it, so a long file
        # list never pushes the QC / Processing headers off a short window.
        self._files_list = ctk.CTkScrollableFrame(
            files_body, height=90, fg_color=COLORS["bg_input"],
            border_width=1, border_color=COLORS["border"],
        )
        self._files_list.pack(fill="both", expand=True, pady=(0, 2))
        # The frame's vertical scrollbar requests a 200 px default height,
        # which overrides ``height`` above as the list's minimum. Lower it so
        # the requested height is honored (the bar still stretches to fill).
        try:
            self._files_list._scrollbar.configure(height=20)
        except Exception:  # noqa: BLE001 - cosmetic; an older CTk keeps 200 px
            pass

        # QC review options.
        self._qc_sec = CollapsibleSection(
            outer, "QC review (optional)", expanded=False,
            summary_provider=self._qc_summary,
        )
        qc_row = self._qc_sec.body
        self._qc_markups_check = ctk.CTkCheckBox(
            qc_row, text="QC Markups — full QC stack + marked-up PDFs",
            variable=self._qc_markups_var, command=self._on_qc_toggle,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"],
        )
        self._qc_markups_check.pack(anchor="w", pady=(4, 0))
        self._qc_verified_only_check = ctk.CTkCheckBox(
            qc_row, text="Verified & deterministic only (conservative — suppress unverified ink)",
            variable=self._qc_verified_only_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self._qc_verified_only_check.pack(anchor="w", padx=(28, 0), pady=(2, 0))
        self._ink_rejected_check = ctk.CTkCheckBox(
            qc_row, text="Include rejected (grey) — ink verifier-rejected findings struck",
            variable=self._ink_rejected_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self._ink_rejected_check.pack(anchor="w", padx=(28, 0), pady=(2, 0))
        # A preference, not a run option: always editable, and the way back
        # after "Don't show this again" in the full-QC cost dialog.
        self._confirm_full_qc_check = ctk.CTkCheckBox(
            qc_row, text="Confirm estimated cost before each full QC run",
            variable=self._confirm_full_qc_var,
            command=self._on_confirm_full_qc_toggle,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self._confirm_full_qc_check.pack(anchor="w", padx=(28, 0), pady=(2, 0))
        self._reference_audit_check = ctk.CTkCheckBox(
            qc_row, text="Deterministic audit only — no additional API calls",
            variable=self._reference_audit_var, command=self._on_reference_audit_toggle,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"],
        )
        self._reference_audit_check.pack(anchor="w", pady=(2, 0))
        # A muted hint that turns visible when QC Markups makes the audit redundant.
        self._reference_audit_hint = ctk.CTkLabel(
            qc_row, text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self._reference_audit_hint.pack(anchor="w", padx=(28, 0))
        self._on_qc_toggle()   # set the sub-toggle's initial enabled state

        # Governing code editions now come from the AHJ Atlas Input (Loaded
        # files above), not a typed field: say so where the field used to be.
        ctk.CTkLabel(
            qc_row,
            text=("Governing code editions: load an AHJ Atlas Input (Excel) under "
                  "Loaded files. Optional — without one, the editions on the "
                  "drawings are used."),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"], wraplength=700, justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Review-profile selector (Phase 24 §16.4): a checkbox per available
        # profile, showing its title/version/discipline/source. Applicable profiles
        # are auto-suggested (pre-checked) once files are loaded; manual choice wins.
        # Its own frame, so a checklist saved from the Live view's Plan tab can
        # be listed without rebuilding the section (_reload_profile_panel).
        self._profile_holder = ctk.CTkFrame(qc_row, fg_color="transparent")
        self._profile_holder.pack(fill="x", anchor="w")
        self._build_profile_panel(self._profile_holder)

        # Processing transport.
        self._transport_sec = CollapsibleSection(
            outer, "Processing", expanded=False,
            summary_provider=lambda: self._processing_mode_var.get().lower(),
        )
        transport_row = self._transport_sec.body
        ctk.CTkLabel(
            transport_row, text="Processing mode",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", pady=(4, 2))
        self._processing_mode_menu = ctk.CTkOptionMenu(
            transport_row,
            values=list(PROCESSING_MODES),
            variable=self._processing_mode_var,
            command=self._on_transport_toggle,
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self._processing_mode_menu.pack(anchor="w")
        # A muted, mode-aware hint carrying the concrete cost/time expectation
        # (and the "batch is a shared queue" explanation) right at the decision
        # point. Text is single-sourced in help_content.transport_hint so the
        # checkbox, cost dialog, and help panel never drift apart.
        self._transport_hint = ctk.CTkLabel(
            transport_row, text=self._transport_hint_text(),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"], justify="left", wraplength=720,
        )
        self._transport_hint.pack(anchor="w", pady=(2, 0))

        # Summary + actions row. Packed below with the bottom rows (see the
        # ``after=`` chain there), so the Analyze button can never be pushed off
        # a short window by expanded sections.
        row = ctk.CTkFrame(outer, fg_color="transparent")
        self._action_row = row
        # Wraps rather than widening: a long full-QC estimate used to squeeze
        # the Stop button to a sliver at the minimum window width.
        self.summary_label = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], justify="left", wraplength=400,
        )
        self.summary_label.pack(side="left")
        self.clear_btn = ctk.CTkButton(
            row, text="Clear", width=80, height=32,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=self._on_clear,
        )
        self.clear_btn.pack(side="right")
        self.analyze_btn = ctk.CTkButton(
            row, text="Analyze Drawings", width=170, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._on_process,
        )
        self.analyze_btn.pack(side="right", padx=(0, 8))
        # The kill switch: live only while an analysis runs, on every
        # processing mode. See _on_stop.
        self.stop_btn = ctk.CTkButton(
            row, text="Stop", width=80, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=COLORS["error"], hover_color=COLORS["critical"],
            state="disabled", command=self._on_stop,
        )
        self.stop_btn.pack(side="right", padx=(0, 8))

        # Progress
        self.progress_label = ctk.CTkLabel(
            outer, text="", font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["text_muted"], anchor="w",
        )

        # Live spend + budget cap. The line fills in while a run works (see
        # _tick_spend). The cap box and its amount are a preference and stay
        # editable during a run: a change applies to the run in progress.
        self._spend_row = ctk.CTkFrame(outer, fg_color="transparent")
        self.spend_label = ctk.CTkLabel(
            self._spend_row, text="", font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["text_muted"], anchor="w", justify="left", wraplength=420,
        )
        self.spend_label.pack(side="left", fill="x", expand=True)
        self._budget_entry = ctk.CTkEntry(
            self._spend_row, textvariable=self._budget_var, width=84, height=26,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        self._budget_entry.pack(side="right")
        self._budget_entry.bind("<Return>", self._on_budget_change)
        self._budget_entry.bind("<FocusOut>", self._on_budget_change)
        self._budget_check = ctk.CTkCheckBox(
            self._spend_row, text="Stop the run at $",
            variable=self._budget_on_var, command=self._on_budget_change,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self._budget_check.pack(side="right", padx=(8, 4))

        # Activity — one slot, two views, switched by the toggle on its first row:
        #   * Live view (live_panel.py / live_scene.py): the animated run board —
        #     the pipeline track, one cell per sheet, live spend / token flow and
        #     the findings breakdown at the end. Purely a display of the run's
        #     own journal and call records; it never changes a run.
        #   * Log: live status + per-sheet diagnostics. The digest itself is
        #     not shown here; it is written only to the saved Markdown file.
        # The toggle is the visuals' on/off switch and is remembered. Sharing
        # the slot keeps the board from squeezing the log off a short window.
        # Collapsible like the sections above, and the sole ``expand=True``
        # section: it absorbs the slack the collapsed sections hand back, and
        # hands its own space to the action buttons below when collapsed. The
        # always-visible progress label above keeps the live status in view
        # even while the section is collapsed.
        live_on = preferences.get_bool(self._prefs_path, preferences.LIVE_VIEW, True)
        self._log_sec = CollapsibleSection(
            outer, "Activity", expand=True,
            summary_provider=self._log_summary,
            on_toggle=lambda _expanded: self._live.kick(),
        )
        view_row = ctk.CTkFrame(self._log_sec.body, fg_color="transparent")
        view_row.pack(fill="x", pady=(2, 0))
        self._activity_switch = ctk.CTkSegmentedButton(
            view_row, values=[_VIEW_LIVE, _VIEW_LOG], height=24,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            command=self._show_activity_view,
        )
        self._activity_switch.pack(side="left")
        # While the board is showing, warnings logged behind it are counted
        # here (click to read them), so a log-only problem is never missed.
        self._log_alert = ctk.CTkLabel(
            view_row, text="", font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["warning"], cursor="hand2",
        )
        self._log_alert.pack(side="left", padx=(10, 0))
        self._log_alert.bind("<Button-1>", lambda _e: self._show_activity_view(_VIEW_LOG))
        activity = ctk.CTkFrame(self._log_sec.body, fg_color="transparent")
        activity.pack(fill="both", expand=True)
        try:
            live_scale = float(ctk.ScalingTracker.get_widget_scaling(self))
        except Exception:  # noqa: BLE001 - older CTk: unscaled
            live_scale = 1.0
        # Requests the height the log box requests, so the slot asks for the
        # same space either way; both grow into the window's slack.
        self.live_canvas = ctk.CTkCanvas(
            activity, height=int(200 * live_scale), bg=LIVE_BG,
            highlightthickness=0, bd=0,
        )
        self._live = LivePanel(
            self.live_canvas,
            schedule=self.after, cancel=self.after_cancel,
            visible=lambda: self._log_sec.expanded and self._live_selected
            and bool(self.live_canvas.winfo_viewable()),
            on_summary=lambda: (not self._log_sec.expanded) and self._log_sec.refresh(),
            on_tab=self._remember_live_tab,
            on_request=self._on_live_request,
            tab=preferences.get_str(self._prefs_path, preferences.LIVE_TAB, ""),
            scale=live_scale, enabled=live_on,
        )
        self.live_canvas.bind("<Motion>", lambda e: self._live.hover(e.x, e.y))
        self.live_canvas.bind("<Leave>", lambda _e: self._live.hover(None))
        # The board's tabs (Board | Story | Thinking | Plan | Findings) are
        # drawn on the canvas: a click picks one, the wheel scrolls its lists.
        # On the Plan tab a click also picks checks to keep (_on_live_request).
        self.live_canvas.bind("<Button-1>", lambda e: self._live.click(e.x, e.y))
        self.live_canvas.bind(
            "<MouseWheel>", lambda e: self._live.scroll(_wheel_steps(e.delta)))
        self.live_canvas.bind("<Button-4>", lambda _e: self._live.scroll(1))
        self.live_canvas.bind("<Button-5>", lambda _e: self._live.scroll(-1))
        self.live_canvas.bind("<Configure>", lambda _e: self._live.kick())
        self.live_canvas.bind("<Map>", lambda _e: self._live.kick())
        self.log_box = ctk.CTkTextbox(
            activity, fg_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=2,
            text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
        )
        for _tag, _color in (
            ("muted", COLORS["text_muted"]),
            ("info", COLORS["text_secondary"]),
            ("accent", COLORS["accent_glow"]),
            ("success", COLORS["success"]),
            ("warning", COLORS["warning"]),
            ("error", COLORS["error"]),
            ("ts", COLORS["text_muted"]),
        ):
            self.log_box.tag_config(_tag, foreground=_color)
        self.log_box.configure(state="disabled")
        # padx comes from the section container (inset 16 from the card).
        self._show_activity_view(_VIEW_LIVE if live_on else _VIEW_LOG, remember=False)

        # HTML report option — embedding the API key makes the report's Ask-AI
        # work on a double-click with no key to paste, but writes the key into
        # the file (so it must not be shared). Off by default: the report prompts
        # for a key at first use and keeps it only in the browser tab.
        # The two bottom rows are packed against the footer (``after=``) so
        # they claim their space before the sections above: with many sections
        # expanded on a short window, the activity log and the sections give
        # way, never the export buttons or the tile-image option.
        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=(0, 8), after=self._footer)
        opt_row = ctk.CTkFrame(outer, fg_color="transparent")
        opt_row.pack(side="bottom", fill="x", padx=16, pady=(0, 4), after=btn_row)
        # Then the progress line and the Analyze row, above the options: the
        # activity log sits between the sections and the Analyze row and is
        # the first thing to give way on a short window.
        self.progress_label.pack(side="bottom", fill="x", padx=16, pady=(0, 2), after=opt_row)
        self._spend_row.pack(
            side="bottom", fill="x", padx=16, pady=(0, 2), after=self.progress_label,
        )
        self._action_row.pack(
            side="bottom", fill="x", padx=16, pady=(4, 2), after=self._spend_row,
        )
        self._embed_key_check = ctk.CTkCheckBox(
            opt_row,
            text="Embed API key in HTML report (Ask-AI works offline; don't share the file)",
            variable=self._embed_key_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self._embed_key_check.pack(anchor="w")

        # Bottom action row: open the on-disk diagnostics log (always available —
        # the detailed request-level trace lives in a file, not this activity
        # log), and save the digest (enabled once a run produces text).
        # The diagnostics log button with its one option stacked beneath it,
        # so the right-hand export buttons keep their width at the minimum
        # window size.
        diag_col = ctk.CTkFrame(btn_row, fg_color="transparent")
        diag_col.pack(side="left")
        self.open_log_btn = ctk.CTkButton(
            diag_col, text="Open Diagnostics Log", width=190, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=self._on_open_log,
        )
        self.open_log_btn.pack(anchor="w")
        # Diagnostics option, kept with the log it belongs to: stage every
        # rendered tile image into the export's tiles/ folder (with per-tile
        # notes). Off unless DRAWING_ANALYZER_SAVE_TILES is set; never places a
        # call and never changes a result.
        self._save_tiles_check = ctk.CTkCheckBox(
            diag_col, text="Save tile images (export tiles/ folder)",
            variable=self._save_tiles_var,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
            checkbox_width=16, checkbox_height=16,
        )
        self._save_tiles_check.pack(anchor="w", pady=(4, 0))
        # GUI export surface trimmed (gui-export-options-cleanup): the per-artifact
        # "Save Markdown…" and "Save Findings CSV…" buttons were removed from the
        # GUI to keep it fast and uncluttered — the operator's two review
        # deliverables are the HTML report and the marked-up ("reviewed") PDFs.
        #
        # NOTE: this is a GUI-only change. Those two buttons' handlers (_on_save,
        # _on_save_csv) and all the underlying export code are deliberately LEFT
        # IN PLACE as dead code — nothing was removed from the engine — so either
        # can be re-surfaced later just by re-adding a button here and re-wiring
        # the enable/disable calls. See README ("GUI export options").
        #
        # "Export All…" is deliberately KEPT: it is the only GUI path that writes
        # the run record (run.log / run_manifest.json) — the diagnostic artifact
        # for a failed run that produced no digest text and no reviewed PDF — so
        # it stays available even then (see the unconditional enable in _on_done).
        # It writes the complete §18.5 deliverable in one go — report.html,
        # Markdown, findings.json/csv, sheet_text/, reviewed PDFs, evidence/,
        # markup_manifest.json, run.log and run_manifest.json — atomically
        # published into a picked folder (Phase 26B, DA-024/DA-033).
        self.export_btn = ctk.CTkButton(
            btn_row, text="Export All…", width=140, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._on_export_all, state="disabled",
        )
        self.export_btn.pack(side="right")
        self.html_btn = ctk.CTkButton(
            btn_row, text="Save HTML Report…", width=180, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            command=self._on_save_html, state="disabled",
        )
        self.html_btn.pack(side="right", padx=(0, 8))
        self.reviewed_btn = ctk.CTkButton(
            btn_row, text="Save Reviewed PDF(s)…", width=190, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            command=self._on_save_reviewed, state="disabled",
        )
        self.reviewed_btn.pack(side="right", padx=(0, 8))

        self._log("Ready — drop or browse for drawing PDFs to analyze.", level="muted")
        diag_path = diagnostics.configured_log_path()
        if diag_path is not None:
            # Surfaced prominently (info, not muted) and tied to the button, so
            # the detailed trace is discoverable rather than hidden in a file.
            self._log(
                f"Diagnostics log: {diag_path}  ·  click “Open Diagnostics Log” "
                f"below to view it any time.",
                level="info",
            )
        if not self._has_key:
            self._set_key_status("no key", COLORS["warning"])
            self._log(
                "No API key found — paste your Anthropic API key above to begin.",
                level="warning",
            )
        else:
            self._set_key_status("loaded", COLORS["text_muted"])
            self._log("Anthropic API key loaded.", level="muted")

    def _register_dnd(self) -> None:
        if DND_FILES is None:
            return
        try:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:  # pragma: no cover - platform dependent
            pass

    # ------------------------------------------------------------- help modals

    def _build_help_buttons(self, parent) -> None:
        """Pack the header buttons (explainers + About) at the right.

        The buttons appear left → right in ``HELP_DOCUMENTS`` order; a shared
        sub-frame packed to the right keeps them grouped beside the title.
        Short labels ("About") get a narrower button so the four-button row
        still fits beside the title at modest window widths.
        """
        bar = ctk.CTkFrame(parent, fg_color="transparent")
        bar.pack(side="right", anchor="e")
        for doc in HELP_DOCUMENTS:
            ctk.CTkButton(
                bar, text=doc.button_label,
                width=112 if len(doc.button_label) > 6 else 68, height=30,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
                border_width=1, border_color=COLORS["border"],
                text_color=COLORS["text_secondary"],
                command=lambda d=doc: self._open_help_modal(d),
            ).pack(side="left", padx=(6, 0))

    def _open_help_modal(self, doc: HelpDocument, parent=None) -> None:
        """Open (or re-focus) the scrollable modal for one help document.

        The content is pure data from :mod:`help_content`; this method only
        renders it. Re-clicking a button whose window is already open lifts and
        focuses that window rather than stacking a duplicate.

        ``parent`` is the help modal this one was opened *from* (the "I'm not
        convinced" hand-off out of "Why trust it?"). It makes the child
        transient to the panel that spawned it and lets
        :meth:`_close_help_modal` return the modal grab to that parent, so
        closing the deep-dive leaves the panel behind it usable again.
        """
        existing = self._help_windows.get(doc.key)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        owner = parent if (parent is not None and parent.winfo_exists()) else self
        win = ctk.CTkToplevel(owner)
        self._help_windows[doc.key] = win
        if owner is not self:
            self._help_parents[doc.key] = owner
        win.title(doc.title)
        win.configure(fg_color=COLORS["bg_dark"])
        # Panels carrying pre-formatted blocks (the runtime-transparency
        # diagrams and tables) are rendered verbatim and never re-wrapped, so
        # they open wider — a narrow window would clip them rather than reflow.
        if any(b.kind == "pre" for s in doc.sections for b in s.blocks):
            win.geometry("880x760")
            win.minsize(620, 420)
        else:
            win.geometry("720x640")
            win.minsize(520, 400)
        win.transient(owner)
        win.bind("<Escape>", lambda _e: self._close_help_modal(doc.key))
        win.protocol("WM_DELETE_WINDOW", lambda: self._close_help_modal(doc.key))
        # Grabbing input before the toplevel is viewable raises on some
        # platforms; defer it a beat so the modal reliably takes focus.
        win.after(150, lambda: self._grab_help_modal(win))

        card = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=8)
        card.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            card, text=doc.title,
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color=COLORS["text_primary"], justify="left",
        ).pack(anchor="w", padx=18, pady=(16, 2))
        if doc.intro:
            ctk.CTkLabel(
                card, text=doc.intro,
                font=ctk.CTkFont(family="Segoe UI", size=12),
                text_color=COLORS["text_secondary"], wraplength=640, justify="left",
            ).pack(anchor="w", padx=18, pady=(0, 8))

        # Bottom bar first so the scrollable body fills the space between it and
        # the header (pack reserves the bottom before the expand widget claims
        # the rest).
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=18, pady=(4, 14))
        ctk.CTkButton(
            bottom, text="Close", width=100, height=32,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=lambda: self._close_help_modal(doc.key),
        ).pack(side="right")

        body = ctk.CTkScrollableFrame(card, fg_color=COLORS["bg_dark"], corner_radius=6)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._render_help_body(
            body,
            doc,
            on_modal_link=lambda key: self._open_help_modal(
                help_document(key), parent=win
            ),
        )

    @staticmethod
    def _render_help_body(body, doc: HelpDocument, on_modal_link=None) -> None:
        """Render each section's heading, paragraphs, and bullets into ``body``.

        ``on_modal_link`` receives the ``doc_key`` of a ``modal`` block when
        the reader clicks it; when it is ``None`` (the content-only test path)
        such a block still renders, just as inert text.
        """
        wrap = 610
        for section in doc.sections:
            ctk.CTkLabel(
                body, text=section.heading,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                text_color=COLORS["accent_glow"], wraplength=wrap, justify="left",
            ).pack(anchor="w", padx=10, pady=(14, 3))
            for block in section.blocks:
                if block.kind == "bullet":
                    row = ctk.CTkFrame(body, fg_color="transparent")
                    row.pack(fill="x", padx=10, pady=(1, 1))
                    ctk.CTkLabel(
                        row, text="•",
                        font=ctk.CTkFont(family="Segoe UI", size=12),
                        text_color=COLORS["text_secondary"],
                    ).pack(side="left", anchor="n", padx=(4, 6))
                    ctk.CTkLabel(
                        row, text=block.text,
                        font=ctk.CTkFont(family="Segoe UI", size=12),
                        text_color=COLORS["text_secondary"],
                        wraplength=wrap - 28, justify="left", anchor="w",
                    ).pack(side="left", anchor="w")
                elif block.kind == "link" and block.href:
                    link = ctk.CTkLabel(
                        body, text=block.text,
                        font=ctk.CTkFont(family="Segoe UI", size=12, underline=True),
                        text_color=COLORS["accent_glow"],
                        wraplength=wrap, justify="left", cursor="hand2",
                    )
                    link.pack(anchor="w", padx=10, pady=(2, 2))
                    link.bind(
                        "<Button-1>",
                        lambda _e, url=block.href: webbrowser.open(url),
                    )
                elif block.kind == "pre":
                    # Verbatim monospace: NO wraplength, so the ASCII diagrams
                    # and tables keep their alignment. help_content bounds the
                    # line length (PRE_MAX_WIDTH) and the modal opens wider
                    # when a doc contains one of these. Breathing room comes
                    # from pack's ipadx/ipady — CTkLabel forwards a constructor
                    # `padx`/`pady` straight into its internal tkinter.Label,
                    # which already sets both, and the duplicate raises.
                    ctk.CTkLabel(
                        body, text=block.text,
                        font=ctk.CTkFont(family="Consolas", size=11),
                        text_color=COLORS["text_secondary"],
                        fg_color=COLORS["bg_card"], corner_radius=6,
                        justify="left", anchor="w",
                    ).pack(anchor="w", padx=10, pady=(6, 6), ipadx=12, ipady=8)
                elif block.kind == "modal" and block.doc_key:
                    # A hand-off to another help document. Rendered like a web
                    # link but routed back through _open_help_modal, so the
                    # panel relationship lives in the content, not in gui.py.
                    jump = ctk.CTkLabel(
                        body, text=block.text,
                        font=ctk.CTkFont(family="Segoe UI", size=12, underline=True),
                        text_color=COLORS["accent_glow"],
                        wraplength=wrap, justify="left",
                        cursor="hand2" if on_modal_link else "",
                    )
                    jump.pack(anchor="w", padx=10, pady=(4, 2))
                    if on_modal_link is not None:
                        jump.bind(
                            "<Button-1>",
                            lambda _e, key=block.doc_key: on_modal_link(key),
                        )
                else:
                    ctk.CTkLabel(
                        body, text=block.text,
                        font=ctk.CTkFont(family="Segoe UI", size=12),
                        text_color=COLORS["text_secondary"],
                        wraplength=wrap, justify="left",
                    ).pack(anchor="w", padx=10, pady=(2, 2))

    def _grab_help_modal(self, win) -> None:
        """Make a help modal application-modal once it is viewable (best-effort)."""
        try:
            if win.winfo_exists():
                win.grab_set()
                win.focus_force()
        except Exception:  # pragma: no cover - platform dependent
            pass

    def _close_help_modal(self, key: str) -> None:
        """Release the grab and destroy a help modal, forgetting its handle.

        When the modal was opened from another one, the grab is handed back to
        that parent — otherwise closing the child would leave the still-open
        panel behind it visible but not accepting input.
        """
        win = self._help_windows.pop(key, None)
        parent = self._help_parents.pop(key, None)
        if win is None:
            return
        try:
            win.grab_release()
        except Exception:  # pragma: no cover - platform dependent
            pass
        try:
            win.destroy()
        except Exception:  # pragma: no cover - platform dependent
            pass
        if parent is not None:
            try:
                if parent.winfo_exists():
                    self._grab_help_modal(parent)
            except Exception:  # pragma: no cover - platform dependent
                pass

    # --------------------------------------------------------------- api key

    def _on_toggle_key(self) -> None:
        """Flip the key field between masked (•) and plaintext."""
        self._key_shown = not self._key_shown
        self.key_entry.configure(show="" if self._key_shown else "•")
        self.key_show_btn.configure(text="Hide" if self._key_shown else "Show")

    def _set_key_status(self, text: str, color: str | None) -> None:
        """Update the small status label beside the key field."""
        self.key_status_label.configure(
            text=text, text_color=color or COLORS["text_muted"]
        )

    def _on_key_changed(self, *_args) -> None:
        """Apply the field's current value to the process as it is edited.

        Bound to the entry's text variable so typing, Ctrl+V, and right-click
        paste all take effect immediately — the app is ready to analyze the
        moment a non-empty key is present, with no button to press.
        ``client.get_client`` re-reads ``ANTHROPIC_API_KEY`` on its next call
        and rebuilds its cached client when the key changes, so setting the env
        var is enough. Writing to disk is deferred to :meth:`_persist_key` (on
        finish) so a half-typed key is never persisted.
        """
        key = self._key_var.get().strip()
        if key:
            os.environ["ANTHROPIC_API_KEY"] = key
            self._has_key = True
            # Show "set" only while there are unsaved edits, so we don't stomp
            # the "saved"/"loaded" indicator when nothing actually changed.
            if key != self._persisted_key:
                self._set_key_status("set", COLORS["text_secondary"])
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self._has_key = False
            self._set_key_status("no key", COLORS["warning"])

    def _persist_key(self, *_args) -> None:
        """Save the current key for next launch once editing finishes.

        Bound to ``<FocusOut>`` and ``<Return>``. No-ops when the field is
        empty or unchanged since the last save, so merely tabbing through the
        field never rewrites an unchanged (or env-supplied) key. Persistence is
        best-effort: a failure leaves the key working for this session (already
        applied by :meth:`_on_key_changed`) and is surfaced, not raised.

        Credential safety (Phase 17, DA-032): persistence goes to the OS
        credential store. When no secure backend exists the key is **not**
        silently written to a plaintext file — the user is asked for explicit
        informed consent; declining keeps the key session-only.
        """
        key = self._key_var.get().strip()
        if not key or key == self._persisted_key:
            return
        try:
            location = save_api_key(key)
        except SecureKeyStorageUnavailable:
            if not messagebox.askyesno(
                "No secure key storage available",
                "No OS-secured credential store (Windows Credential Manager / "
                "macOS Keychain / Secret Service) is available on this "
                "machine, so the key cannot be saved securely.\n\n"
                "Save it as a PLAIN-TEXT file instead?\n\n"
                f"It would be written to:\n{api_key_paths()[0]}\n\n"
                "Anyone who can read that file can use your key. Choose No "
                "to keep the key for this session only (you'll re-enter it "
                "next launch).",
                icon="warning",
            ):
                self._log(
                    "API key kept for this session only — not saved "
                    "(no secure credential store; plaintext declined).",
                    level="warning",
                )
                self._set_key_status("session only", COLORS["warning"])
                return
            try:
                location = save_api_key(key, allow_plaintext_fallback=True)
            except Exception as exc:  # noqa: BLE001 - persistence is best-effort
                self._log(
                    f"API key set for this session, but could not be saved: {exc}",
                    level="warning",
                )
                self._set_key_status("not saved", COLORS["warning"])
                return
            self._persisted_key = key
            self._log(
                f"API key saved as plain text ({location}) with your consent — "
                "treat that file as a credential.",
                level="warning",
            )
            self._set_key_status("saved (plaintext)", COLORS["warning"])
            return
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort
            self._log(
                f"API key set for this session, but could not be saved: {exc}",
                level="warning",
            )
            self._set_key_status("not saved", COLORS["warning"])
            return
        self._persisted_key = key
        where = "OS keyring" if location is None else str(location)
        self._log(f"API key saved ({where}).", level="success")
        self._set_key_status("saved", COLORS["success"])

    # ------------------------------------------------------------- selection

    def _parse_paths(self, payload: str) -> list[Path]:
        if not payload:
            return []
        try:
            items = list(self.tk.splitlist(payload))
        except Exception:
            try:
                items = shlex.split(payload)
            except ValueError:
                items = [payload]
        out: list[Path] = []
        for item in items:
            name = item.strip().strip("{}").strip('"')
            if name:
                out.append(Path(name))
        return out

    def _on_drop(self, event) -> None:
        self._add_pdfs(self._parse_paths(getattr(event, "data", "")))

    def _on_browse(self) -> None:
        files = filedialog.askopenfilenames(
            title="Select drawing PDFs", filetypes=_PDF_FILETYPES
        )
        if files:
            self._add_pdfs([Path(f) for f in files])

    def _add_pdfs(self, paths: list[Path]) -> None:
        if self._busy:
            return
        added = False
        existing = {str(p) for p in self._pdfs}
        for p in paths:
            if p.suffix.lower() != ".pdf":
                continue
            if str(p) not in existing:
                self._pdfs.append(p)
                existing.add(str(p))
                added = True
        if added:
            self._sync_dropzone_section()
            self._refresh_summary()
            self._refresh_profile_suggestions()
            self._refresh_files_panel()
            self._reveal_files()

    def _remove_pdf(self, path: Path) -> None:
        """Drop one drawing PDF from the run (its Remove button)."""
        if self._busy:
            return
        kept = [p for p in self._pdfs if str(p) != str(path)]
        if len(kept) == len(self._pdfs):
            return
        self._pdfs = kept
        self._ctx = None
        self._log(f"Removed drawing: {Path(path).name}", level="muted")
        self._sync_dropzone_section()
        self._refresh_summary()
        # A new file list: the measured bases describe the old one. The
        # preflight clears and re-measures (and re-suggests profiles).
        self._refresh_profile_suggestions()
        self._refresh_files_panel()

    # ---------------------------------------------------- reference documents

    def _on_upload_specs(self) -> None:
        """Prompt the quality warning, then let the operator pick spec files.

        The warning is shown on EVERY click, before the file picker opens —
        matches the existing ``askyesno(..., icon="warning")`` pattern used
        for the cost-confirm / plaintext-key-storage dialogs. Only "Yes"
        opens the picker. Picked files are ADDED to those already loaded (a
        file picked again replaces its earlier copy); each loaded file has its
        own Remove button in the Loaded files list.
        """
        if self._busy:
            return
        if not messagebox.askyesno(_SPEC_WARNING_TITLE, _SPEC_WARNING_BODY, icon="warning"):
            return
        files = filedialog.askopenfilenames(
            title="Select project specification documents", filetypes=_SPEC_FILETYPES
        )
        if files:
            self._start_document_extraction("specs", [Path(f) for f in files])

    def _on_add_context(self) -> None:
        """Pick additional context documents (basis of design, owner standards…)."""
        if self._busy:
            return
        files = filedialog.askopenfilenames(
            title="Select additional context documents", filetypes=_SPEC_FILETYPES
        )
        if files:
            self._start_document_extraction("context", [Path(f) for f in files])

    def _start_document_extraction(self, kind: str, paths: list[Path]) -> None:
        """Extract text off the UI thread; the result lands via ``after``.

        Mirrors the main analyze flow's busy guard: without it, Analyze or
        Clear could run before the background thread finishes (Clear would
        then have this extraction's stale result applied on top of it).
        """
        self._busy = True
        self._set_inputs_editable(False)
        self.analyze_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        noun = "spec documents" if kind == "specs" else "context documents"
        self._set_progress_text(f"Reading {noun}…", color=COLORS["text_secondary"])
        threading.Thread(
            target=self._extract_documents_worker, args=(kind, paths), daemon=True,
        ).start()

    def _extract_documents_worker(self, kind: str, paths: list[Path]) -> None:
        """Per-file failures are captured on each ``SpecDocument`` (I-3) and
        never raise; this still guards the whole pass so an unexpected failure
        reports back and clears the busy state instead of sticking."""
        try:
            from .spec_documents import extract_spec_documents

            docs = extract_spec_documents(paths)
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            self.after(0, lambda e=exc: self._on_document_extraction_error(kind, str(e)))
            return
        self.after(0, lambda: self._apply_documents_result(kind, docs))

    # Kept under its historical name for callers that still use it.
    def _extract_specs_worker(self, paths: list[Path]) -> None:
        self._extract_documents_worker("specs", paths)

    def _end_extraction(self) -> None:
        self._busy = False
        self._set_inputs_editable(True)
        self.analyze_btn.configure(state="normal")
        self.clear_btn.configure(state="normal")
        self._set_progress_text("")

    def _on_document_extraction_error(self, kind: str, message: str) -> None:
        self._end_extraction()
        noun = "spec documents" if kind == "specs" else "context documents"
        self._log(f"Could not read {noun}: {message}", level="error")

    def _on_specs_extraction_error(self, message: str) -> None:
        self._on_document_extraction_error("specs", message)

    def _apply_documents_result(self, kind: str, docs: list[SpecDocument]) -> None:
        """Merge freshly extracted documents into the category and rebuild it."""
        self._end_extraction()
        current = self._spec_documents if kind == "specs" else self._context_documents
        picked = {str(d.path) for d in docs}
        merged = [d for d in current if str(d.path) not in picked]
        ok = [d for d in docs if d.ok]
        merged += ok
        if kind == "specs":
            self._spec_documents = merged
        else:
            self._context_documents = merged
        label = "spec document(s)" if kind == "specs" else "context document(s)"
        if ok:
            self._log(
                f"Loaded {label}: " + ", ".join(d.display_name for d in ok),
                level="success",
            )
        for d in docs:
            if not d.ok:
                self._log(f"Could not read {d.display_name}: {d.error}", level="warning")
        self._rebuild_document_text(kind)
        if ok:
            self._reveal_files()

    def _apply_specs_result(
        self, paths: list[Path], docs: list[SpecDocument], text: str = "",
        budget: SpecBudget | None = None,
    ) -> None:
        """Historical entry point; the text is rebuilt from the documents."""
        self._apply_documents_result("specs", docs)

    def _rebuild_document_text(self, kind: str) -> None:
        """Re-join a category's loaded documents under its budget (no re-reading)."""
        from .spec_documents import build_specs_text

        if kind == "specs":
            text, budget = build_specs_text(self._spec_documents, budget_chars=SPEC_TOTAL_CHAR_BUDGET)
            self._specs_text, self._specs_budget = text, budget
            noun = "Spec"
        else:
            text, budget = build_specs_text(
                self._context_documents, budget_chars=CONTEXT_TOTAL_CHAR_BUDGET,
            )
            self._context_text, self._context_budget = text, budget
            noun = "Context"
        if budget.degraded:
            self._log(
                f"{noun} text truncated to the {budget.budget_chars:,}-char "
                f"budget ({budget.omitted_chars:,} char(s) omitted).",
                level="warning",
            )
        self._refresh_summary()
        self._refresh_files_panel()

    def _remove_document(self, kind: str, path: Path) -> None:
        if self._busy:
            return
        if kind == "specs":
            self._spec_documents = [d for d in self._spec_documents if str(d.path) != str(path)]
        else:
            self._context_documents = [
                d for d in self._context_documents if str(d.path) != str(path)
            ]
        self._log(f"Removed {Path(path).name}", level="muted")
        self._rebuild_document_text(kind)

    def _current_specs_text(self) -> str:
        return self._specs_text or ""

    def _current_context_text(self) -> str:
        return self._context_text or ""

    # ------------------------------------------------------------- checklists

    def _on_add_checklists(self) -> None:
        """Pick checklist files; each becomes a review profile for QC critique."""
        if self._busy:
            return
        files = filedialog.askopenfilenames(
            title="Select review checklists", filetypes=_CHECKLIST_FILETYPES
        )
        if not files:
            return
        paths = [Path(f) for f in files]
        self._busy = True
        self._set_inputs_editable(False)
        self.analyze_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        self._set_progress_text("Reading checklists…", color=COLORS["text_secondary"])

        def _work() -> None:
            from .profiles import load_checklist_file

            loaded, failed = [], []
            for path in paths:
                try:
                    loaded.append(load_checklist_file(path))
                except Exception as exc:  # noqa: BLE001 - one bad file never sinks the rest
                    failed.append((path, str(exc)))
            self.after(0, lambda: self._apply_checklists(loaded, failed))

        threading.Thread(target=_work, daemon=True).start()

    def _apply_checklists(self, loaded: list, failed: list) -> None:
        self._end_extraction()
        picked = {str(p.source_path) for p in loaded}
        self._checklists = [
            p for p in self._checklists if str(p.source_path) not in picked
        ] + list(loaded)
        for prof in loaded:
            self._log(
                f"Loaded checklist {prof.title}: {len(prof.items)} item(s).",
                level="success",
            )
        for path, error in failed:
            self._log(f"Could not read checklist {Path(path).name}: {error}", level="warning")
        self._refresh_summary()
        self._refresh_files_panel()
        if loaded:
            self._reveal_files()

    def _on_scope_checklist(self, profile) -> None:
        """Ask which sheets a loaded checklist applies to (by number prefix)."""
        if self._busy:
            return
        current = ", ".join(t.upper() for t in profile.disciplines) or "all sheets"
        dialog = ctk.CTkInputDialog(
            title="Checklist scope",
            text=(
                f"{profile.title}\nCurrently applies to: {current}\n\n"
                "Sheet-number prefixes this checklist applies to, separated by "
                "commas (for example: F, FP, SP). Leave blank for all sheets."
            ),
        )
        raw = dialog.get_input()
        if raw is None:      # cancelled
            return
        self._set_checklist_scope(profile, raw)

    def _set_checklist_scope(self, profile, raw: str) -> None:
        from .profiles import scoped_to

        updated = scoped_to(profile, raw)
        self._checklists = [updated if p is profile else p for p in self._checklists]
        scope = ", ".join(t.upper() for t in updated.disciplines)
        self._log(
            f"Checklist {updated.title} applies to "
            + (f"sheets numbered {scope}." if scope else "all sheets."),
            level="muted",
        )
        self._refresh_summary()
        self._refresh_files_panel()

    def _remove_checklist(self, profile) -> None:
        if self._busy:
            return
        self._checklists = [p for p in self._checklists if p is not profile]
        self._log(f"Removed checklist {profile.title}", level="muted")
        self._refresh_summary()
        self._refresh_files_panel()

    # -------------------------------------------------------------- AHJ atlas

    def _on_load_atlas(self) -> None:
        """Load the AHJ Atlas Input (Excel) — the run's governing code editions."""
        if self._busy:
            return
        path = filedialog.askopenfilename(
            title="Load AHJ Atlas Input (Excel)", filetypes=_ATLAS_FILETYPES
        )
        if not path:
            return
        self._busy = True
        self._set_inputs_editable(False)
        self.analyze_btn.configure(state="disabled")
        self.clear_btn.configure(state="disabled")
        self._set_progress_text("Reading AHJ Atlas Input…", color=COLORS["text_secondary"])

        def _work() -> None:
            from .ahj_atlas import load_ahj_atlas

            atlas = load_ahj_atlas(Path(path))  # never raises (I-3)
            self.after(0, lambda: self._apply_atlas(atlas))

        threading.Thread(target=_work, daemon=True).start()

    def _apply_atlas(self, atlas) -> None:
        self._end_extraction()
        for warning in atlas.warnings[:10]:
            self._log(f"AHJ Atlas: {warning}", level="warning")
        if len(atlas.warnings) > 10:
            self._log(f"AHJ Atlas: {len(atlas.warnings) - 10} more warning(s).", level="warning")
        if not atlas.ok:
            self._log(f"AHJ Atlas Input not loaded: {atlas.error}", level="error")
            messagebox.showerror("AHJ Atlas Input", f"{atlas.display_name}\n\n{atlas.error}")
            return
        if len(atlas.jurisdictions) == 1:
            self._set_atlas(atlas, atlas.jurisdictions[0])
        else:
            self._choose_jurisdiction(atlas)

    def _set_atlas(self, atlas, jurisdiction) -> None:
        self._atlas, self._atlas_choice = atlas, jurisdiction
        where = f" — {jurisdiction.name}" if jurisdiction.name else ""
        self._log(
            f"AHJ Atlas Input loaded ({atlas.display_name}{where}): "
            f"{jurisdiction.summary()}. These editions replace the ones detected "
            "on the drawings for the codes named.",
            level="success",
        )
        self._refresh_summary()
        self._refresh_files_panel()
        self._reveal_files()

    def _remove_atlas(self) -> None:
        if self._busy:
            return
        self._atlas, self._atlas_choice = None, None
        self._log("Removed the AHJ Atlas Input.", level="muted")
        self._refresh_summary()
        self._refresh_files_panel()

    def _choose_jurisdiction(self, atlas) -> None:
        """Ask which jurisdiction of a multi-AHJ atlas governs this project."""
        win = ctk.CTkToplevel(self)
        win.title("Choose the AHJ")
        win.configure(fg_color=COLORS["bg_dark"])
        win.geometry("520x460")
        win.minsize(400, 320)
        win.transient(self)
        card = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=8)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(
            card,
            text=(f"{atlas.display_name} lists {len(atlas.jurisdictions)} "
                  "jurisdictions. Which one governs this project?"),
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=COLORS["text_primary"], wraplength=460, justify="left",
        ).pack(anchor="w", padx=14, pady=(14, 6))
        query = ctk.CTkEntry(
            card, placeholder_text="Filter by name or code…", height=30,
            fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
        )
        query.pack(fill="x", padx=14, pady=(0, 6))
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=(6, 14))
        listing = ctk.CTkScrollableFrame(card, fg_color=COLORS["bg_input"])
        listing.pack(fill="both", expand=True, padx=14)
        choice = StringVar(value="0")

        def _fill(*_args) -> None:
            for child in listing.winfo_children():
                child.destroy()
            needle = query.get().strip().casefold()
            for i, j in enumerate(atlas.jurisdictions):
                text = f"{j.label}  —  {j.summary()}"
                if needle and needle not in text.casefold():
                    continue
                ctk.CTkRadioButton(
                    listing, text=text, variable=choice, value=str(i),
                    font=ctk.CTkFont(family="Segoe UI", size=12),
                    text_color=COLORS["text_primary"],
                ).pack(anchor="w", pady=2)

        query.bind("<KeyRelease>", _fill)
        _fill()

        def _use() -> None:
            try:
                picked = atlas.jurisdictions[int(choice.get())]
            except (ValueError, IndexError):
                return
            win.destroy()
            self._set_atlas(atlas, picked)

        ctk.CTkButton(
            bottom, text="Use this AHJ", width=130, height=32,
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"], command=_use,
        ).pack(side="right")
        ctk.CTkButton(
            bottom, text="Cancel", width=90, height=32,
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=win.destroy,
        ).pack(side="right", padx=(0, 8))
        win.bind("<Escape>", lambda _e: win.destroy())
        try:
            win.grab_set()
        except Exception:  # noqa: BLE001 - a grab failure only loses modality
            pass

    def _current_governing(self):
        """The governing-edition entries from the AHJ Atlas Input (``[]``: none)."""
        choice = getattr(self, "_atlas_choice", None)
        return list(choice.entries) if choice is not None else []

    # -------------------------------------------------------- loaded-file list

    def _set_inputs_editable(self, enabled: bool) -> None:
        """Enable/disable every Add button and (via a rebuild) every Remove."""
        self._inputs_locked = not enabled
        for btn in getattr(self, "_add_buttons", {}).values():
            btn.configure(state="normal" if enabled else "disabled")
        self._refresh_files_panel()

    def _files_summary(self) -> str:
        """Collapsed Loaded-files header: what is loaded, by category."""
        parts = []
        if self._pdfs:
            parts.append(f"{len(self._pdfs)} drawing PDF(s)")
        if self._spec_documents:
            parts.append(f"{len(self._spec_documents)} spec(s)")
        if self._checklists:
            parts.append(f"{len(self._checklists)} checklist(s)")
        if self._context_documents:
            parts.append(f"{len(self._context_documents)} context doc(s)")
        if self._atlas_choice is not None:
            parts.append("AHJ Atlas")
        if not parts:
            return "add drawings, specs, checklists, context or the AHJ Atlas Input"
        return " · ".join(parts)

    def _reveal_files(self) -> None:
        """Expand the Loaded-files list when something is added, so the user
        sees what was loaded (and its Remove button) without hunting for it."""
        sec = getattr(self, "_files_sec", None)
        if sec is not None and not self._busy:
            sec.set_expanded(True)

    def _file_groups(self) -> list[dict]:
        """The Loaded-files list as data: one dict per category.

        Each group: ``title``, ``detail`` (count + tokens), ``empty`` (shown when
        nothing is loaded) and ``rows`` — ``(label, detail, remove_callback)``.
        Kept separate from the widgets so the token arithmetic is one place.
        """
        groups: list[dict] = []

        # Drawings — image + text-layer tokens for one digest read each.
        counts = [len(list_sheets([p])) for p in self._pdfs]
        files = drawing_file_tokens(
            counts, self._usable_preflight_bases(), model=REVIEW_MODEL_DEFAULT,
        )
        rows = []
        for path, ft in zip(self._pdfs, files):
            text = (f" + ~{ft.text_tokens:,} text" if ft.text_tokens is not None else "")
            basis = "" if ft.measured else " (allowance until measured)"
            rows.append((
                path.name,
                f"{ft.sheets} sheet(s) · ~{ft.image_tokens:,} image{text} tokens{basis}",
                lambda p=path: self._remove_pdf(p),
            ))
        total = sum(f.total for f in files)
        groups.append({
            "title": "Drawings",
            "detail": (f"{len(self._pdfs)} file(s), {sum(counts)} sheet(s) · "
                       f"~{total:,} tokens per digest read") if self._pdfs else "",
            "empty": "none — drop PDFs above or Add drawings…",
            "rows": rows,
        })

        for kind, title, docs, text, note in (
            ("specs", "Specifications", self._spec_documents, self._specs_text,
             "sent with every sheet"),
            ("context", "Additional context", self._context_documents, self._context_text,
             "sent with every sheet"),
        ):
            rows = [
                (d.display_name, f"~{estimate_text_tokens(len(d.text)):,} tokens",
                 lambda k=kind, p=d.path: self._remove_document(k, p))
                for d in docs
            ]
            budget = self._specs_budget if kind == "specs" else self._context_budget
            cut = (f" (budget reached: {budget.omitted_chars:,} chars omitted)"
                   if budget is not None and budget.degraded else "")
            groups.append({
                "title": title,
                "detail": (f"{len(docs)} file(s) · ~{estimate_text_tokens(len(text)):,} "
                           f"tokens, {note}{cut}") if docs else "",
                "empty": ("none — the project specifications, if you have them"
                          if kind == "specs" else
                          "none — e.g. basis of design, owner standards, prior comments"),
                "rows": rows,
            })

        from .profiles import build_checklist_prompt, flatten_items

        rows = [
            (p.title, f"{len(p.items)} item(s) · "
                      f"~{estimate_text_tokens(len(build_checklist_prompt(p.items))):,} tokens · "
                      + (f"applies to sheets {', '.join(t.upper() for t in p.disciplines)}"
                         if p.disciplines else "applies to all sheets"),
             lambda prof=p: self._remove_checklist(prof))
            for p in self._checklists
        ]
        all_items = flatten_items(self._checklists)
        groups.append({
            "title": "Checklists",
            "detail": (f"{len(self._checklists)} file(s), {len(all_items)} item(s) · "
                       f"~{estimate_text_tokens(len(build_checklist_prompt(all_items))):,} "
                       "tokens, applied by the QC Markups critique") if self._checklists else "",
            "empty": "none — applied by the QC Markups critique",
            "rows": rows,
            # One extra button per row, parallel to ``rows``: limit a checklist
            # to the sheets whose number starts with a discipline prefix.
            "row_actions": [
                ("Scope…", lambda prof=p: self._on_scope_checklist(prof))
                for p in self._checklists
            ],
        })

        choice = self._atlas_choice
        rows = []
        if choice is not None and self._atlas is not None:
            where = f"{choice.name} · " if choice.name else ""
            rows.append((
                self._atlas.display_name,
                f"{where}{choice.summary()} · "
                f"~{estimate_text_tokens(len('; '.join(choice.entries))):,} tokens",
                self._remove_atlas,
            ))
        groups.append({
            "title": "AHJ Atlas Input (optional)",
            "detail": (f"{len(choice.codes)} governing edition(s)" if choice is not None else ""),
            "empty": "none — the editions on the drawings are used",
            "rows": rows,
        })
        return groups

    def _refresh_files_panel(self) -> None:
        """Rebuild the Loaded-files list (called whenever an input changes)."""
        frame = getattr(self, "_files_list", None)
        if frame is None:
            return
        try:
            for child in frame.winfo_children():
                child.destroy()
            groups = self._file_groups()
        except Exception as exc:  # noqa: BLE001 - a list refresh must never break the UI
            _log.warning("loaded-files refresh failed: %s", exc)
            return
        state = "disabled" if self._inputs_locked else "normal"
        for group in groups:
            head = ctk.CTkFrame(frame, fg_color="transparent")
            head.pack(fill="x", pady=(6, 0))
            ctk.CTkLabel(
                head, text=group["title"],
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                text_color=COLORS["text_primary"],
            ).pack(side="left")
            if group["detail"]:
                ctk.CTkLabel(
                    head, text=f"  {group['detail']}",
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                    text_color=COLORS["text_secondary"],
                ).pack(side="left")
            if not group["rows"]:
                ctk.CTkLabel(
                    head, text=f"  {group['empty']}",
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                    text_color=COLORS["text_muted"],
                ).pack(side="left")
            actions = group.get("row_actions") or []
            for i, (label, detail, remove) in enumerate(group["rows"]):
                row = ctk.CTkFrame(frame, fg_color="transparent")
                row.pack(fill="x", padx=(14, 0), pady=1)
                ctk.CTkButton(
                    row, text="Remove", width=70, height=24,
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                    fg_color=COLORS["bg_card"], hover_color=COLORS["error"],
                    border_width=1, border_color=COLORS["border"],
                    text_color=COLORS["text_secondary"], command=remove, state=state,
                ).pack(side="right", padx=(6, 4))
                if i < len(actions) and actions[i]:
                    action_text, action = actions[i]
                    ctk.CTkButton(
                        row, text=action_text, width=70, height=24,
                        font=ctk.CTkFont(family="Segoe UI", size=11),
                        fg_color=COLORS["bg_card"], hover_color=COLORS["border"],
                        border_width=1, border_color=COLORS["border"],
                        text_color=COLORS["text_secondary"], command=action, state=state,
                    ).pack(side="right", padx=(6, 0))
                ctk.CTkLabel(
                    row, text=f"{label}  ·  {detail}",
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                    text_color=COLORS["text_secondary"], anchor="w", justify="left",
                    wraplength=_FILE_ROW_WRAP,
                ).pack(side="left", fill="x", expand=True)
        note = self._files_total_text(groups)
        if note:
            ctk.CTkLabel(
                frame, text=note, font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLORS["text_muted"], justify="left",
                wraplength=_FILE_ROW_WRAP,
            ).pack(anchor="w", pady=(8, 2))
        sec = getattr(self, "_files_sec", None)
        if sec is not None:
            sec.refresh()
        # Every input change lands here, so the Live view previews the set.
        self._refresh_live_preview()

    def _files_total_text(self, groups: list[dict]) -> str:
        if not any(g["rows"] for g in groups):
            return ""
        return (
            "Tokens per digest read (≈4 characters per text token). Specs and "
            "context ride every sheet's request; the cost line prices it all."
        )

    def _on_clear(self) -> None:
        if self._busy:
            return
        self._pdfs = []
        self._ctx = None
        self._spec_documents = []
        self._specs_text = ""
        self._specs_budget = None
        self._context_documents = []
        self._context_text = ""
        self._context_budget = None
        self._checklists = []
        self._atlas = None
        self._atlas_choice = None
        self._reset_profile_selection()
        self._clear_log()
        self.html_btn.configure(state="disabled")
        self.reviewed_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self._set_progress_text("")
        self._sync_dropzone_section()
        self._refresh_summary()
        self._refresh_files_panel()

    def _on_qc_toggle(self) -> None:
        """Enable the markup sub-toggles only when QC Markups is on.

        QC Markups runs the full exhaustive stack — the deterministic auditors are
        already included (§15.3), so the standalone audit checkbox is disabled and
        marked redundant while QC Markups is checked.
        """
        on = self._qc_markups_var.get()
        for name in ("_qc_verified_only_check", "_ink_rejected_check"):
            check = getattr(self, name, None)
            if check is not None:
                check.configure(state="normal" if on else "disabled")
        audit = getattr(self, "_reference_audit_check", None)
        if audit is not None:
            audit.configure(state="disabled" if on else "normal")
        hint = getattr(self, "_reference_audit_hint", None)
        if hint is not None:
            hint.configure(
                text="Already included in QC Markups." if on else ""
            )
        self._refresh_summary()
        self._refresh_live_preview()

    def _on_reference_audit_toggle(self) -> None:
        self._refresh_summary()
        self._refresh_live_preview()

    # --------------------------------------------------------------------- #
    # Live view (live_panel.py)
    # --------------------------------------------------------------------- #

    def _refresh_live_preview(self) -> None:
        """Show the loaded set and the planned pipeline on the idle board.

        The plan comes from the same ``resolve_run_configuration`` the run
        uses, so the track grows the QC stages the moment QC Markups is
        ticked. Ignored mid-run (the run's own plan is on the board) and
        before the panel exists.
        """
        live = getattr(self, "_live", None)
        if live is None or self._busy:
            return
        try:
            key = sources_fingerprint(self._pdfs) if self._pdfs else ()
            if key != self._live_sheet_key:
                refs = list_sheets(self._pdfs) if self._pdfs else []
                self._live_sheet_rows = [
                    (sheet_item(r), r.display_label, r.source_id) for r in refs
                ]
                self._live_sheet_key = key
            config = resolve_run_configuration(
                qc_markups=bool(self._qc_markups_var.get()),
                reference_audit=bool(self._reference_audit_var.get()),
                synthesize=True,
            )
            stages = planned_stages(config, focus=bool(self._current_focus()))
            if len(self._live_sheet_rows) < 2:
                # The set overview needs two readable sheets.
                stages = [s for s in stages if s != "synthesis"]
            live.preview(self._live_sheet_rows, stages, revision=self._live_sheet_key)
        except Exception as exc:  # noqa: BLE001 - a preview is decoration
            _log.debug("live view preview failed: %s", exc)

    def _show_activity_view(self, view: str, *, remember: bool = True) -> None:
        """Show the Live view board or the log in the Activity slot."""
        live_on = view == _VIEW_LIVE
        self._live_selected = live_on
        if self._activity_switch.get() != view:
            self._activity_switch.set(view)
        if live_on:
            self.log_box.pack_forget()
            self.live_canvas.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self.live_canvas.pack_forget()
            self.log_box.pack(fill="both", expand=True, pady=(4, 0))
            self.log_box.see("end")
            self._log_unseen = 0
            self._log_alert.configure(text="")
        if remember:
            self._remember_live_view(live_on)
        else:
            self._live.set_enabled(live_on)

    def _remember_live_tab(self, tab: str) -> None:
        """Keep the Live view's showing tab for the next launch."""
        try:
            preferences.set_preference(self._prefs_path, preferences.LIVE_TAB, str(tab))
        except Exception:  # noqa: BLE001 - a preference that cannot be saved is not an error
            _log.debug("could not save the Live view tab", exc_info=True)

    # --------------------------------------------------------------------- #
    # Keeping checks from the Live view's Plan tab
    # --------------------------------------------------------------------- #

    def _on_live_request(self, request) -> None:
        """The Plan tab asked to save picked checks or copy one check's text."""
        from .live_tabs import CopyRequest, SaveRequest

        if isinstance(request, CopyRequest):
            try:
                self.clipboard_clear()
                self.clipboard_append(request.text)
            except Exception as exc:  # noqa: BLE001 - no clipboard (remote session)
                self._log(f"Could not copy {request.id}: {exc}", level="warning")
                return
            live = getattr(self, "_live", None)
            if live is not None:
                live.announce(f"Copied {request.id} to the clipboard", "info")
        elif isinstance(request, SaveRequest):
            _save_checks_dialog(self, request, on_saved=self._on_checks_saved)

    def _on_checks_saved(self, plan) -> None:
        """A save went through: mark the rows, say so, and list the checklist."""
        ids = [c.id for c in plan.adding]
        # Where a skipped check already was, as its row says it: a run id
        # (``U1.2``), or the checklist it was being added to.
        held = {c.id: (plan.name if where.startswith("item ") else where)
                for c, where in plan.skipped}
        n = len(ids)
        message = f"Saved {n} check{'s' if n != 1 else ''} to “{plan.title}”"
        if held:
            message += f" · {len(held)} already kept, skipped"
        live = getattr(self, "_live", None)
        if live is not None:
            live.mark_saved(ids, plan.name, held, message=message)
        self._log(f"{message} ({plan.path.name} in your profiles folder)", level="success")
        self._reload_profile_panel()

    def _reload_profile_panel(self) -> None:
        """Re-read the profiles folder into the Review profiles list.

        Ticks the user set are kept; a newly saved checklist is ticked when it
        matches the loaded set's sheet prefixes, like any installed profile.
        """
        holder = getattr(self, "_profile_holder", None)
        if holder is None:
            return
        previous = {name: var.get() for name, var in self._profile_vars.items()}
        try:
            for child in holder.winfo_children():
                child.destroy()
            self._profile_vars.clear()
            self._build_profile_panel(holder)
        except Exception as exc:  # noqa: BLE001 - the list is a convenience
            _log.warning("could not refresh the review profiles list: %s", exc)
            return
        for name, var in self._profile_vars.items():
            if name in previous:
                var.set(previous[name])
        if self._pdfs:
            self._refresh_profile_suggestions()

    def _remember_live_view(self, on: bool) -> None:
        """Turn the visuals on/off and keep the choice for the next launch."""
        try:
            preferences.set_preference(self._prefs_path, preferences.LIVE_VIEW, bool(on))
        except Exception:  # noqa: BLE001 - a preference that cannot be saved is not an error
            _log.debug("could not save the Live view preference", exc_info=True)
        live = getattr(self, "_live", None)
        if live is not None:
            live.set_enabled(on)

    # ----------------------------------------------- live spend + budget cap

    def _budget_cap(self) -> float | None:
        """The cap the box and amount ask for; ``ValueError`` if unreadable."""
        if not self._budget_on_var.get():
            return None
        return parse_budget(self._budget_var.get())

    def _on_budget_change(self, _event=None) -> None:
        """The cap box or amount changed: remember it and apply it to a live run.

        An unreadable amount leaves the run's current cap in force. A cap at
        or below what the run has already spent would stop it at once, so that
        change is confirmed first and reverted if declined.
        """
        if getattr(self, "_budget_confirming", False):
            return          # the confirmation dialog took focus from the entry
        try:
            cap = self._budget_cap()
        except ValueError:
            self._mark_budget_entry(valid=False)
            return
        self._mark_budget_entry(valid=True)
        monitor = self._spend
        if monitor is not None and self._busy and cap != monitor.budget:
            snap = monitor.snapshot()
            if cap is not None and cap <= snap.committed and not self._confirm_stopping_cap(
                cap, snap.committed
            ):
                previous = monitor.budget
                self._budget_on_var.set(previous is not None)
                if previous is not None:
                    self._budget_var.set(f"{previous:.2f}")
            else:
                monitor.set_budget(cap)
                self._log(
                    f"Budget cap set to {format_money(cap)}." if cap is not None
                    else "Budget cap turned off for this run.",
                    level="accent",
                )
            self._refresh_spend_line()
        preferences.set_preference(
            self._prefs_path, preferences.BUDGET_CAP_ENABLED, bool(self._budget_on_var.get())
        )
        preferences.set_preference(
            self._prefs_path, preferences.BUDGET_CAP_AMOUNT, self._budget_var.get().strip()
        )

    def _confirm_stopping_cap(self, cap: float, committed: float) -> bool:
        self._budget_confirming = True
        try:
            return bool(messagebox.askyesno(
                "Stop this run?",
                f"This run has already spent about {format_money(committed)}, "
                f"which is at or above a cap of {format_money(cap)}.\n\n"
                "Setting this cap stops the run now. Continue?",
                icon="warning", parent=self,
            ))
        finally:
            self._budget_confirming = False

    def _mark_budget_entry(self, *, valid: bool) -> None:
        entry = getattr(self, "_budget_entry", None)
        if entry is not None:
            entry.configure(border_color=COLORS["border"] if valid else COLORS["error"])

    def _refresh_spend_line(self) -> None:
        monitor = self._spend
        if monitor is None:
            self.spend_label.configure(text="")
            return
        snap = monitor.snapshot()
        color = COLORS["text_secondary"]
        if snap.budget_hit is not None:
            color = COLORS["error"]
        elif snap.budget is not None and snap.committed >= 0.8 * snap.budget:
            color = COLORS["warning"]
        self.spend_label.configure(text=format_spend_line(snap), text_color=color)

    def _tick_spend(self) -> None:
        """Refresh the spend line once a second for as long as a run works."""
        if not self._busy or self._spend is None:
            return
        self._refresh_spend_line()
        self.after(SPEND_REFRESH_MS, self._tick_spend)

    def _on_confirm_full_qc_toggle(self) -> None:
        """Persist the full-QC cost-confirmation preference (best-effort)."""
        preferences.set_preference(
            self._prefs_path, preferences.SKIP_FULL_QC_CONFIRM,
            not bool(self._confirm_full_qc_var.get()),
        )

    # --------------------------------------------------------------------- #
    # Review profiles (Phase 24 §16.4)
    # --------------------------------------------------------------------- #

    def _build_profile_panel(self, parent) -> None:
        """A checkbox per available review profile (title · version · source).

        Best-effort and non-fatal: a discovery/parse failure must never break the
        QC panel, so the whole build is guarded.
        """
        try:
            from .profiles import list_profiles

            profiles = list_profiles()
        except Exception as exc:  # noqa: BLE001 - a bad profile dir can't sink the UI
            _log.warning("profile discovery failed: %s", exc)
            return
        self._profiles_by_name = {p.name: p for p in profiles}
        if not profiles:
            # Phase A: with no local checklists the review plan is authored by
            # the model per set — say so instead of showing an empty panel.
            ctk.CTkLabel(
                parent,
                text=("Review checklists: authored automatically per set "
                      "(model-planned). Add your own with Add checklists… under "
                      "Loaded files, or keep .md checklists in "
                      "~/.drawing_analyzer/profiles."),
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLORS["text_muted"], wraplength=520, justify="left",
            ).pack(anchor="w", padx=(28, 0), pady=(6, 0))
            return
        from .profiles import snapshot_profiles

        ctk.CTkLabel(
            parent, text="Review profiles (auto-suggested from sheet ids)",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", padx=(28, 0), pady=(6, 0))
        for p in profiles:
            var = BooleanVar(value=False)
            self._profile_vars[p.name] = var
            # Provenance from the authoritative snapshot (exact parent-dir match),
            # not a loose substring — the default user dir ~/.drawing_analyzer/
            # profiles must read as 'user', not 'built-in'.
            source = snapshot_profiles([p])[0].source or "user"
            label = f"{p.title} · v{p.version} · {source}"
            ctk.CTkCheckBox(
                parent, text=label, variable=var,
                command=lambda n=p.name: self._on_profile_toggle(n),
                font=ctk.CTkFont(family="Segoe UI", size=11),
                text_color=COLORS["text_muted"],
            ).pack(anchor="w", padx=(40, 0), pady=(1, 0))

    def _on_profile_toggle(self, name: str) -> None:
        """Record a manual override (on/off) so it survives a preflight refresh."""
        var = self._profile_vars.get(name)
        if var is None:
            return
        if var.get():
            self._profile_forced_on.add(name)
            self._profile_forced_off.discard(name)
        else:
            self._profile_forced_off.add(name)
            self._profile_forced_on.discard(name)

    def _usable_preflight_bases(self) -> "list | None":
        """The measured bases, or ``None`` when they no longer describe the files.

        The generation counter tracks *selection* changes, so it cannot see a PDF
        overwritten in place between the scan and the Analyze click — a normal
        thing to do when re-exporting a set to the same filenames. A replacement
        with the same page count would otherwise be priced with the previous
        revision's dimensions and vector/raster classification while the dialog
        said it had measured the current pages.

        Checking here rather than only at assignment also means a stale set can
        never be consumed by whichever caller runs first: the summary refresh in
        ``_add_pdfs`` fires before the preflight clears the previous selection's
        bases, and this gate catches that ordering rather than depending on it.
        """
        if not self._preflight_bases:
            return None
        if self._preflight_fingerprint != sources_fingerprint(self._pdfs):
            return None
        return self._preflight_bases

    def _refresh_profile_suggestions(self) -> None:
        """Measure loaded files and suggest any installed profiles off the UI thread.

        Runs the cheap text-only preflight in a worker thread and marshals the
        checkbox updates back via ``after`` so the UI stays responsive (§16.4). The
        PyMuPDF access is serialized under a lock (PyMuPDF is not thread-safe), and
        a generation counter means only the most recent preflight's result is applied.
        """
        if self._busy:
            return
        pdfs = list(self._pdfs)
        self._preflight_gen += 1
        gen = self._preflight_gen
        # The bases on hand describe the PREVIOUS file list. Drop them now rather
        # than at apply time: between here and the worker's result the dialog
        # would otherwise price the new selection with the old set's shapes.
        self._preflight_bases = None
        self._preflight_fingerprint = None
        fingerprint = sources_fingerprint(pdfs)
        available = dict(self._profiles_by_name) if self._profile_vars else {}

        def _work() -> None:
            bases: list = []
            try:
                from .profiles import preflight_scan, suggest_profiles

                # Serialize PyMuPDF access across overlapping preflights (I-5).
                # One walk yields both the profile suggestion and the per-page
                # cost bases (§10.3): deriving the bases from geometry this pass
                # already built measured 0.4 ms for 120 sheets, against 6,896 ms
                # for a second scan of the same set — so there is no second scan.
                with self._preflight_lock:
                    scan = preflight_scan(pdfs)
                bases = scan.cost_bases
                profiles = suggest_profiles(scan.sheet_ids, available=available) if available else []
                names = [p.name for p in profiles]
            except Exception as exc:  # noqa: BLE001 - preflight is a hint, never fatal
                _log.info("drawing preflight failed: %s", exc)
                names = []
            self.after(0, lambda: self._apply_profile_suggestions(
                names, gen, bases, fingerprint))

        threading.Thread(target=_work, daemon=True).start()

    def _apply_profile_suggestions(
        self, names: list[str], gen: int = 0, bases: "list | None" = None,
        fingerprint: "tuple | None" = None,
    ) -> None:
        """Apply a preflight result: suggested-and-not-forced-off OR forced-on are
        checked; everything else is unchecked (so a suggestion for one file set does
        not leak into the next). A stale result (superseded generation) is ignored."""
        if gen and gen != self._preflight_gen:
            return
        # Same generation guard, same reason: a superseded scan describes a file
        # list the user has already replaced, and pricing the new one with it
        # would be worse than pricing conservatively.
        self._preflight_bases = list(bases) if bases else None
        self._preflight_fingerprint = fingerprint if bases else None
        if self._profile_vars:
            from .profiles import resolve_profile_selection

            self._profile_suggested = set(names)
            on = set(resolve_profile_selection(
                names, user_selected=self._profile_forced_on,
                user_deselected=self._profile_forced_off,
            ))
            for name, var in self._profile_vars.items():
                var.set(name in on)  # non-suggested, non-forced → unchecked
        # The estimate the summary is showing was computed before these bases
        # existed. Without this it stays on the conservative figure until some
        # unrelated option toggle happens to refresh it — so the measured number
        # would appear only by accident.
        self._refresh_summary()
        # The per-file token counts in the Loaded-files list sharpen the same way.
        self._refresh_files_panel()

    def _reset_profile_selection(self) -> None:
        """Clear all profile state (called on Clear) so nothing carries into a new set.

        Bumps the preflight generation so a preflight still running from the previous
        file set can't re-apply its (now stale) suggestions after the list is cleared
        — its ``_apply_profile_suggestions`` callback fails the generation check.
        """
        self._preflight_gen += 1
        self._profile_forced_on.clear()
        self._profile_forced_off.clear()
        self._profile_suggested.clear()
        for var in self._profile_vars.values():
            var.set(False)

    def _selected_profiles(self) -> list[str]:
        """The profile names currently checked, in discovery order."""
        return [n for n, var in self._profile_vars.items() if var.get()]

    def _current_focus(self) -> str:
        """The per-run focus currently in the box (stripped; "" when empty).

        Defensive: returns "" before the box exists (early ``_refresh_summary``)
        or if the widget read fails, so the focus can never break a refresh.
        """
        box = getattr(self, "focus_box", None)
        if box is None:
            return ""
        try:
            return box.get("1.0", "end").strip()
        except Exception:  # noqa: BLE001 - a widget hiccup must not break refresh
            return ""

    def _open_focus_popout(self) -> None:
        """Open (or re-focus) a larger, resizable editor for the focus text.

        Mirrors the header textbox live in both directions via
        ``_sync_focus_boxes``: typing in either box updates the other, so
        ``_current_focus`` — which only ever reads the header ``focus_box`` —
        stays correct without needing to know a pop-out exists.
        """
        existing = self._focus_popout
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        win = ctk.CTkToplevel(self)
        self._focus_popout = win
        win.title("Per-run focus")
        win.configure(fg_color=COLORS["bg_dark"])
        win.geometry("640x420")
        win.minsize(420, 260)
        win.transient(self)
        win.bind("<Escape>", lambda _e: self._close_focus_popout())
        win.protocol("WM_DELETE_WINDOW", self._close_focus_popout)

        card = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=8)
        card.pack(fill="both", expand=True, padx=12, pady=12)
        ctk.CTkLabel(
            card, text="Per-run focus",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=14, pady=(14, 6))

        # Bottom bar first so the textbox fills the space between it and the
        # header (pack reserves the bottom before the expand widget claims
        # the rest) — mirrors _open_help_modal's layout.
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=(6, 14))
        ctk.CTkButton(
            bottom, text="Done", width=100, height=32,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._close_focus_popout,
        ).pack(side="right")

        self.focus_popout_box = ctk.CTkTextbox(
            card, fg_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=2,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=13), wrap="word",
        )
        self.focus_popout_box.pack(fill="both", expand=True, padx=14, pady=(0, 4))
        self.focus_popout_box.insert("1.0", self._current_focus())
        self.focus_popout_box.bind(
            "<KeyRelease>",
            lambda _e: self._sync_focus_boxes(self.focus_popout_box),
        )
        if self._busy:
            self.focus_popout_box.configure(state="disabled")
        self.focus_popout_box.focus_set()

    def _close_focus_popout(self) -> None:
        """Destroy the focus pop-out, if open (no-op otherwise)."""
        win = self._focus_popout
        self._focus_popout = None
        self.focus_popout_box = None
        if win is not None and win.winfo_exists():
            win.destroy()

    def _sync_focus_boxes(self, source) -> None:
        """Mirror ``source``'s text into whichever other focus box exists.

        Called from both the header box's and the pop-out's ``<KeyRelease>``
        so the two always agree, whichever one the operator is typing in.
        """
        try:
            text = source.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001 - a widget hiccup must not break typing
            return
        for box in (self.focus_box, self.focus_popout_box):
            if box is None or box is source:
                continue
            try:
                box.delete("1.0", "end")
                box.insert("1.0", text)
            except Exception:  # noqa: BLE001 - a widget hiccup must not break typing
                pass
        self._refresh_summary()

    def _set_focus_editable(self, enabled: bool) -> None:
        """Enable/disable the focus box, its Expand button, and the pop-out.

        One call covers all three surfaces so a run's start/finish never
        leaves the pop-out editable while the header box (and everything
        that reads it) is locked, or vice versa. The loaded-file list is a
        run input too, so its Add/Remove buttons lock and unlock with them.
        """
        state = "normal" if enabled else "disabled"
        self.focus_box.configure(state=state)
        self.focus_expand_btn.configure(state=state)
        if self.focus_popout_box is not None:
            self.focus_popout_box.configure(state=state)
        self._set_inputs_editable(enabled)

    def _transport_hint_text(self) -> str:
        """The Processing hint; XFast adds the fast-mode price premium."""
        mode = self._processing_mode_var.get()
        text = transport_hint(mode)
        if processing_fast_mode(mode):
            text += " " + xfast_note(REVIEW_MODEL_DEFAULT)
        return text

    def _on_transport_toggle(self, _selection: str | None = None) -> None:
        # Keep the muted hint under the Processing menu in sync with the
        # chosen mode, then refresh the cost summary (whose rate also depends
        # on the batch/real-time choice and on XFast's fast-mode premium).
        hint = getattr(self, "_transport_hint", None)
        if hint is not None:
            hint.configure(text=self._transport_hint_text())
        self._refresh_summary()

    def _qc_summary(self) -> str:
        """Collapsed QC-header hint: how many of the four QC options are on."""
        on = sum(
            bool(v.get()) for v in (
                self._qc_markups_var, self._qc_verified_only_var,
                self._ink_rejected_var, self._reference_audit_var,
            )
        )
        parts = [f"{on} on"] if on else []
        if self._current_governing():
            parts.append("AHJ editions")
        return " · ".join(parts)

    def _log_summary(self) -> str:
        """Collapsed activity-log header hint: the latest log line.

        Shown only while the log is collapsed, so the most recent status stays
        visible at a glance; when expanded the log below already shows it, so the
        header stays uncluttered. Whitespace/newlines are flattened to one line
        and the result is truncated so a long line never blows out the header.
        """
        sec = getattr(self, "_log_sec", None)
        if sec is None or sec.expanded:
            return ""
        live = getattr(self, "_live", None)
        if live is not None and getattr(self, "_live_selected", False):
            # The board is the chosen view: its one-line run state.
            board = live.model.summary_line()
            if board:
                return board
        text = " ".join((self._log_summary_text or "").split())
        return text if len(text) <= 48 else text[:47] + "…"

    def _refresh_section_headers(self) -> None:
        """Re-pull each collapsible header's live state summary.

        Called from _refresh_summary (the central state hook), so headers stay
        current as focus text / QC options / transport change — no per-handler
        wiring needed. Guarded because _refresh_summary can fire mid-build.
        """
        for name in (
            "_key_sec", "_drop_sec", "_files_sec", "_focus_sec",
            "_qc_sec", "_transport_sec", "_log_sec",
        ):
            sec = getattr(self, name, None)
            if sec is not None:
                sec.refresh()

    def _sync_dropzone_section(self) -> None:
        """Auto-collapse the drop zone once files are loaded, expand when empty.

        Keeps the ~90px drop target visible exactly when it's useful (drag-drop
        is only registered on it) and hands its space back afterwards.
        """
        sec = getattr(self, "_drop_sec", None)
        if sec is not None:
            sec.set_expanded(not self._pdfs)

    def _refresh_summary(self) -> None:
        # Keep the collapsible headers' state summaries live on every state
        # change (this is the central hook). Guarded inside the helper.
        self._refresh_section_headers()
        # Defensive: _on_qc_toggle() fires this during _build_ui before the
        # summary label exists (mirrors _current_focus's early-refresh guard on
        # focus_box). __init__ calls _refresh_summary() again once the UI is
        # fully built, which sets the initial text.
        label = getattr(self, "summary_label", None)
        if label is None:
            return
        if not self._pdfs:
            label.configure(text="No drawings selected.")
            return
        refs = list_sheets(self._pdfs)
        sheets = len(refs)
        files = len({r.pdf_path for r in refs})
        mode = self._processing_mode_var.get()
        digest_batch, critique_batch = processing_transports(mode)
        fast = processing_fast_mode(mode)
        # Specs and context share the per-sheet reference block, so the
        # estimate prices their combined size.
        reference_chars = len(self._current_specs_text()) + len(self._current_context_text())
        # §10.3 item 1 says not to replace every refresh with a synchronous scan.
        # This does not: it reads whatever the background preflight has already
        # produced, or nothing. The summary sharpens on its own once the scan
        # lands, and never waits for it.
        bases = self._usable_preflight_bases()
        digest_est = estimate_drawing_set_cost(
            sheets, file_count=files, model=REVIEW_MODEL_DEFAULT,
            batch=digest_batch,
            focus=bool(self._current_focus()),
            spec_chars=reference_chars,
            bases=bases,
            fast_mode=fast,
        )
        if self._qc_markups_var.get():
            full = estimate_exhaustive_run_cost(
                sheets, file_count=files, model=REVIEW_MODEL_DEFAULT,
                batch=digest_batch, critique_batch=critique_batch,
                focus=bool(self._current_focus()),
                spec_chars=reference_chars,
                bases=bases,
                fast_mode=fast,
            )
            cost = (
                f"~${full.low_cost:,.2f}–${full.high_cost:,.2f} (full QC est.)"
                if full.low_cost is not None and full.high_cost is not None
                else "full QC cost n/a"
            )
        else:
            cost = (
                f"~${digest_est.low_cost:,.2f}–${digest_est.high_cost:,.2f} (est.)"
                if digest_est.low_cost is not None and digest_est.high_cost is not None
                else "cost n/a"
            )
        label.configure(
            text=(
                f"{files} file(s), {sheets} sheet(s)  ·  "
                f"~{digest_est.image_tokens:,} digest image tokens  ·  {cost}"
            )
        )

    # --------------------------------------------------------------- process

    def _on_process(self) -> None:
        if self._busy:
            return
        if not self._pdfs:
            messagebox.showinfo("No drawings", "Add one or more drawing PDFs first.")
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            messagebox.showerror(
                "No API key",
                "No Anthropic API key is set. Paste your key in the field at the "
                "top, then try again.",
            )
            return

        try:
            budget_cap = self._budget_cap()
        except ValueError:
            self._mark_budget_entry(valid=False)
            messagebox.showerror(
                "Budget cap",
                "The budget cap is on, but its amount is not a dollar figure "
                "greater than zero. Enter an amount (for example 50) or turn "
                "the cap off.",
            )
            return

        # Snapshot every input with the file list, so mid-run edits can't
        # change what a running analysis was asked to do.
        governing_editions = self._current_governing()
        atlas_choice = getattr(self, "_atlas_choice", None)
        focus = self._current_focus()
        project_specifications = self._current_specs_text() or None
        project_context = self._current_context_text() or None
        qc_markups = self._qc_markups_var.get()
        markup_verified_only = self._qc_verified_only_var.get()
        ink_rejected = self._ink_rejected_var.get()
        reference_audit = self._reference_audit_var.get()
        checklists = list(getattr(self, "_checklists", []))
        # Installed profiles by name, uploaded checklists as Profile objects —
        # resolve_profiles takes both.
        profiles = self._selected_profiles() + checklists
        processing_mode = self._processing_mode_var.get()
        use_batch, critique_use_batch = processing_transports(processing_mode)
        fast_mode = processing_fast_mode(processing_mode)
        save_tiles = bool(self._save_tiles_var.get())
        reference_chars = len(project_specifications or "") + len(project_context or "")

        # Cost-confirm gate — show the estimated spend before anything is sent.
        # For an exhaustive QC run (DA-010) show the full per-stage estimate with a
        # low–high band (§15.7); otherwise the digest-only figure. Nothing is sent
        # until this is confirmed.
        refs = list_sheets(self._pdfs)
        # WP-05 §10.3/§10.4: price from each page's real shape when the drawing
        # preflight has already measured this exact file list, and fall back to
        # the conservative allowance otherwise — the user clicked Analyze before
        # the scan finished, or it failed. No blocking, no second PDF owner, and
        # no spinner: the work was already done under a lock we do not touch.
        bases = self._usable_preflight_bases()
        skipped_estimate: str | None = None
        quoted = None
        if qc_markups:
            quoted = exh = estimate_exhaustive_run_cost(
                len(refs), file_count=len(self._pdfs), model=REVIEW_MODEL_DEFAULT,
                batch=use_batch, critique_batch=critique_use_batch,
                focus=bool(focus),
                spec_chars=reference_chars,
                bases=bases,
                fast_mode=fast_mode,
            )
            prompt = format_exhaustive_cost_prompt(exh)
            if self._confirm_full_qc_var.get():
                proceed, dont_show = _ask_cost_confirmation(
                    self, "Confirm full QC run", prompt
                )
                if not proceed:
                    return
                if dont_show:
                    self._confirm_full_qc_var.set(False)
                    self._on_confirm_full_qc_toggle()
            else:
                # The user opted out of the dialog; the estimate still reaches
                # the activity log once the run starts.
                skipped_estimate = (
                    f"${exh.low_cost:,.2f}–${exh.high_cost:,.2f}"
                    if exh.low_cost is not None and exh.high_cost is not None
                    else "unavailable"
                )
        else:
            quoted = estimate = estimate_drawing_set_cost(
                len(refs), file_count=len(self._pdfs), model=REVIEW_MODEL_DEFAULT,
                batch=use_batch, focus=bool(focus),
                spec_chars=reference_chars,
                bases=bases,
                fast_mode=fast_mode,
            )
            prompt = format_drawing_cost_prompt(estimate)
            if not messagebox.askyesno("Confirm drawing analysis", prompt):
                return

        self._busy = True
        self._ctx = None
        self._run_cancel = CancelToken()
        # The run's live spend: priced as responses arrive, projected from the
        # estimate just quoted, and capped by the budget box (which stays live).
        self._spend = SpendMonitor(budget=budget_cap, forecast=spend_forecast(quoted))
        self.analyze_btn.configure(state="disabled", text="Analyzing…")
        self.stop_btn.configure(state="normal", text="Stop")
        self.clear_btn.configure(state="disabled")
        self.html_btn.configure(state="disabled")
        self.reviewed_btn.configure(state="disabled")
        self.export_btn.configure(state="disabled")
        self._set_focus_editable(False)
        # The inputs are locked for the run; hand their space to the log.
        files_sec = getattr(self, "_files_sec", None)
        if files_sec is not None:
            files_sec.set_expanded(False)
        self._clear_log()
        self._log(
            f"Starting analysis — {len(self._pdfs)} file(s), {len(refs)} sheet(s).",
            level="accent",
        )
        if skipped_estimate is not None:
            self._log(
                f"Full QC estimated cost: {skipped_estimate} — confirmation "
                "skipped (turn it back on under QC review → Confirm estimated "
                "cost before each full QC run).",
                level="warning",
            )
        if budget_cap is not None:
            self._log(
                f"Budget cap: {format_money(budget_cap)} — the run stops if its "
                "spend reaches it. The cap can be changed or turned off while "
                "the run works.",
                level="accent",
            )
            low = getattr(quoted, "low_cost", None)
            if low is not None and low > budget_cap:
                self._log(
                    f"The estimate's low end ({format_money(low)}) is above the "
                    "cap, so this run is likely to be stopped before it finishes.",
                    level="warning",
                )
        if focus:
            self._log(f"Per-run focus: {focus}", level="accent")
            self._log(
                "The standard digest is unchanged; a Focus Report will be added "
                "for this focus. Sheets cached without this focus are "
                "re-analyzed.",
                level="muted",
            )
        if atlas_choice is not None:
            if qc_markups or reference_audit:
                where = f" for {atlas_choice.name}" if atlas_choice.name else ""
                self._log(
                    f"AHJ Atlas Input{where}: {atlas_choice.summary()} (these "
                    "replace the editions detected on the drawings).",
                    level="accent",
                )
            else:
                self._log(
                    "AHJ Atlas Input loaded, but no QC option is on — the governing "
                    "editions are used only by QC Markups or the deterministic audit.",
                    level="warning",
                )
        if project_specifications:
            self._log(
                f"Project specifications attached: {len(project_specifications):,} "
                "chars — conflicts will be reported as ordinary findings.",
                level="accent",
            )
        if project_context:
            self._log(
                f"Additional context attached: {len(project_context):,} chars — "
                "requirements it states are checked like the specifications.",
                level="accent",
            )
        if checklists:
            if qc_markups:
                self._log(
                    f"Checklists applied by the QC critique: "
                    + ", ".join(p.title for p in checklists) + ".",
                    level="accent",
                )
            else:
                self._log(
                    "Checklists loaded, but QC Markups is off — checklists are "
                    "applied only by the QC critique.",
                    level="warning",
                )
        if save_tiles:
            self._log(
                "Tile images will be saved (Export All writes them to tiles/).",
                level="muted",
            )
        if processing_mode == PROCESSING_MODE_ECONOMY:
            self._log(
                "Economy mode: all eligible vision reads join Anthropic's shared queue — often ready in "
                "a few hours, but it can run overnight (8+ hours). Cheapest option; "
                "leave it running and check back later.",
                level="muted",
            )
        elif processing_mode == PROCESSING_MODE_HYBRID:
            self._log(
                "Hybrid mode: initial sheet analysis runs now; QC critique "
                "reads use the half-rate Batch queue and may take hours.",
                level="muted",
            )
        elif fast_mode:
            self._log(
                "XFast mode: full-rate API calls with immediate results, and Opus "
                "requests in fast mode. " + xfast_note(REVIEW_MODEL_DEFAULT),
                level="warning",
            )
        else:
            self._log(
                "Fast mode: full-rate API calls with immediate results "
                "(~4–6 min/sheet; batch is ~50% cheaper).",
                level="muted",
            )
        self._set_progress_text("Starting…", color=COLORS["text_secondary"])
        # Arm the Live view: the run attaches its journal and call record to
        # this monitor, and the board animates from them.
        live = getattr(self, "_live", None)
        monitor = live.begin() if live is not None else None

        pdfs = list(self._pdfs)
        threading.Thread(
            target=self._worker,
            args=(pdfs, focus, project_specifications, qc_markups,
                  markup_verified_only, reference_audit, ink_rejected, profiles,
                  use_batch, critique_use_batch, self._run_cancel,
                  governing_editions, project_context, fast_mode, save_tiles,
                  monitor, self._spend),
            daemon=True,
        ).start()
        self._tick_spend()

    def _worker(
        self,
        pdfs: list[Path],
        focus: str,
        project_specifications: str | None = None,
        qc_markups: bool = False,
        markup_verified_only: bool = False,
        reference_audit: bool = False,
        ink_rejected: bool = False,
        profiles: list[str] | None = None,
        use_batch: bool = True,
        critique_use_batch: bool | None = None,
        cancel: CancelToken | None = None,
        governing_editions: "str | list[str]" = "",
        project_context: str | None = None,
        fast_mode: bool = False,
        save_tile_artifacts: bool = False,
        monitor=None,
        spend: SpendMonitor | None = None,
    ) -> None:
        try:
            ctx = extract_drawing_context(
                pdfs,
                model=REVIEW_MODEL_DEFAULT,
                progress=self._progress_from_thread,
                on_log=self._log_from_thread,
                on_status=self._status_from_thread,
                use_cache=True,
                synthesize=True,
                use_batch=use_batch,
                critique_use_batch=critique_use_batch,
                focus=focus or None,
                project_specifications=project_specifications,
                reference_audit=reference_audit,
                qc_markups=qc_markups,
                markup_verified_only=markup_verified_only,
                ink_rejected=ink_rejected,
                profiles=profiles or None,
                # The "Save tile images" box under the diagnostics log button
                # (seeded from DRAWING_ANALYZER_SAVE_TILES).
                save_tile_artifacts=save_tile_artifacts,
                governing_editions=governing_editions or None,
                project_context=project_context,
                fast_mode=fast_mode,
                cancel=cancel,
                # The Live view's window onto this run (read-only).
                monitor=monitor,
                spend=spend,
            )
        except RunCancelled:
            # The user's Stop (or quitting mid-run). A BaseException, so it is
            # caught by name: ``except Exception`` would leave the UI busy forever.
            self.after(0, self._on_cancelled)
            return
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
            _log.exception("Analysis worker failed")
            self.after(0, lambda e=exc: self._on_error(str(e)))
            return
        self.after(0, lambda: self._on_done(ctx))

    def _progress_from_thread(self, done: int, total: int, label: str) -> None:
        self.after(0, lambda: self._set_progress(done, total, label))

    def _log_from_thread(self, message: str, level: str = "info") -> None:
        self.after(0, lambda: self._log(message, level=level))

    def _status_from_thread(self, text: str) -> None:
        """Update only the live status line (no activity-log entry).

        High-frequency, status-line-only feedback from the batch path — per-image
        upload progress, including any 503 retry wave — so the line keeps moving
        during a sheet's tens-of-seconds upload instead of looking frozen, while
        the activity log stays a clean per-sheet milestone history.
        """
        self.after(
            0,
            lambda t=text: self._set_progress_text(t, color=COLORS["text_secondary"]),
        )

    def _set_progress(self, done: int, total: int, label: str) -> None:
        pct = f"[{done}/{total}] " if total else ""
        self._set_progress_text(f"{pct}{label}", color=COLORS["text_secondary"])
        # Mirror each *distinct* status into the log, collapsing the repeated
        # batch-poll line so the history shows one entry per state change.
        if label and label != self._last_log_msg:
            self._last_log_msg = label
            lowered = label.lower()
            level = "warning" if ("fail" in lowered or "error" in lowered) else "muted"
            self._log(f"{pct}{label}", level=level)

    def _set_progress_text(self, text: str, *, color: str | None = None) -> None:
        self.progress_label.configure(
            text=text, text_color=color or COLORS["text_muted"]
        )

    def _log(self, message: str, *, level: str = "info") -> None:
        """Append one timestamped, color-coded line to the activity log.

        Called only on the main thread (worker-thread callbacks marshal through
        ``self.after`` first). The box is kept read-only between writes.
        """
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{ts}  ", "ts")
        self.log_box.insert("end", f"{message}\n", level)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        # Keep the collapsed log header's latest-line hint live. No-op work is
        # avoided while expanded (the summary is empty then); refreshing only
        # when collapsed also keeps this off the hot path during a normal run.
        self._log_summary_text = message
        sec = getattr(self, "_log_sec", None)
        if sec is not None and not sec.expanded:
            sec.refresh()
        if level in ("warning", "error") and getattr(self, "_live_selected", False):
            self._log_unseen = getattr(self, "_log_unseen", 0) + 1
            alert = getattr(self, "_log_alert", None)
            if alert is not None:
                n = self._log_unseen
                alert.configure(text=f"● {n} warning{'s' if n != 1 else ''} in the log")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._last_log_msg = None
        self._log_summary_text = None
        self._log_unseen = 0
        alert = getattr(self, "_log_alert", None)
        if alert is not None:
            alert.configure(text="")
        sec = getattr(self, "_log_sec", None)
        if sec is not None:
            sec.refresh()

    def _on_stop(self) -> None:
        """The kill switch: stop the running analysis, on any processing mode.

        Nothing new is sent after this, streamed requests in flight are
        abandoned, and every Message Batch the run has open is canceled at once
        from a background thread (see :mod:`drawing_analyzer.cancellation`).
        """
        token = self._run_cancel
        if token is None or token.cancelled or not self._busy:
            return
        try:
            confirmed = messagebox.askyesno(
                "Stop this run?",
                "Stop the analysis now?\n\n"
                "Nothing new is sent. Remote batches are canceled and requests "
                "in flight are abandoned. Requests already made are still "
                "billed.\n\n"
                "Sheets that already finished stay in the cache, so re-running "
                "the same files reuses them at no cost.",
                icon="warning",
                parent=self,
            )
        except Exception:  # noqa: BLE001 - a broken dialog must not disable the kill switch
            confirmed = True
        if confirmed:
            self._request_stop()

    def _request_stop(self) -> None:
        token = self._run_cancel
        if token is None or token.cancelled:
            return
        token.cancel()
        self.stop_btn.configure(state="disabled", text="Stopping…")
        self._log(
            "Stop requested — nothing new will be sent; canceling remote batches "
            "and abandoning requests in flight…",
            level="warning",
        )
        self._set_progress_text("Stopping…", color=COLORS["warning"])

    def _end_run_controls(self) -> bool:
        """Reset the kill switch after a run ends; ``True`` if a stop was requested."""
        token, self._run_cancel = self._run_cancel, None
        self.stop_btn.configure(state="disabled", text="Stop")
        return token is not None and token.cancelled

    def _on_cancelled(self) -> None:
        self._busy = False
        self._end_run_controls()
        live = getattr(self, "_live", None)
        if live is not None:
            live.stop()
        self.analyze_btn.configure(state="normal", text="Analyze Drawings")
        self.clear_btn.configure(state="normal")
        self._set_focus_editable(True)
        self._refresh_spend_line()
        hit = self._spend.snapshot().budget_hit if self._spend is not None else None
        if hit is not None:
            self._log(
                f"Budget cap reached — the run was stopped at about "
                f"{format_money(hit.committed)} against a cap of "
                f"{format_money(hit.limit)}. Requests already made are still "
                "billed, so the final charge can be a little higher.",
                level="error",
            )
        self._log(
            "Run stopped. Nothing further will be sent. Sheets that finished are "
            "in the cache — re-running the same files reuses them at no cost, and "
            "the next run collects anything a canceled batch finished first.",
            level="warning",
        )
        self._set_progress_text(
            "Stopped — budget cap reached." if hit is not None else "Stopped.",
            color=COLORS["warning"],
        )
        if hit is not None:
            messagebox.showwarning(
                "Budget cap reached",
                f"The run was stopped because its spend reached the budget cap "
                f"of {format_money(hit.limit)}.\n\n"
                "Sheets that finished are in the cache. Raise the cap or turn "
                "it off and run again to continue from there.",
            )

    def _on_done(self, ctx: DrawingContext) -> None:
        self._busy = False
        self._ctx = ctx
        live = getattr(self, "_live", None)
        if live is not None:
            live.finish(ctx)
        if self._end_run_controls():
            self._log(
                "The stop arrived after the run's last paid request, so the run "
                "finished; its results are below.",
                level="warning",
            )
        self.analyze_btn.configure(state="normal", text="Analyze Drawings")
        self.clear_btn.configure(state="normal")
        self._set_focus_editable(True)
        self._refresh_spend_line()
        has_text = bool(ctx.combined_text.strip())
        if has_text:
            self.html_btn.configure(state="normal")
        # Export All stays available even for a run that analyzed nothing —
        # the run record (run.log, inventory, run_manifest.json) is the
        # diagnostic artifact for exactly those failures (§18.1).
        self.export_btn.configure(state="normal")
        # QC outputs — enable the reviewed-PDF save action only when a run
        # produced marked-up PDFs. (The per-artifact Markdown / findings-CSV
        # buttons were removed from the GUI; their handlers remain as dead code
        # — see the btn_row note in _build_ui.)
        if getattr(ctx, "reviewed_pdf_paths", None):
            self.reviewed_btn.configure(state="normal")

        ok = ctx.ok_sheet_count
        cached = ctx.cached_sheet_count
        failed = ctx.sheet_count - ok

        # Per-sheet diagnostics — surface *why* each unprocessed sheet failed
        # (image upload error, batch item errored/expired, empty digest, batch
        # not collected, …) so a partial run is explainable rather than silent.
        if ctx.errors:
            self._log(
                f"{len(ctx.errors)} issue(s) — per-sheet detail follows:",
                level="warning",
            )
            for err in ctx.errors:
                self._log(f"  • {err}", level="error")
            diag_path = diagnostics.configured_log_path()
            if diag_path is not None:
                self._log(
                    "Full request-level detail (status codes, request-ids, "
                    f"batch id) in the diagnostics log:\n    {diag_path}",
                    level="muted",
                )

        cached_note = f", {cached} from cache" if cached else ""
        failed_note = f", {failed} failed" if failed else ""
        # Completion states (§3.3 / §15.5): when exhaustive QC ran, the state leads
        # with its normalized ``qc_status`` — FAILED / a receipt-derived INCOMPLETE
        # coverage is "QC incomplete"; PARTIAL is "Completed with QC warnings";
        # COMPLETE is "All QC stages complete" (reachable since the §18.0 gate
        # opened). A run that did not request exhaustive QC keeps the simple
        # errors-based states.
        qc_status = getattr(ctx, "qc_status", "NOT_REQUESTED")
        if getattr(ctx, "markup_incomplete", False) or qc_status == "FAILED":
            state, level = "QC incomplete", "error"
        elif qc_status == "PARTIAL":
            state, level = "Completed with QC warnings", "warning"
        elif qc_status == "COMPLETE":
            state, level = "All QC stages complete", "success"
        elif ctx.errors:
            state, level = "Completed with QC warnings", "warning"
        else:
            state, level = "Completed", "success"
        est_cost = getattr(ctx, "total_estimated_cost", None)
        cost_note = f" · est. ${float(est_cost):,.2f}" if est_cost is not None else ""
        summary = (
            f"{state} — {ok}/{ctx.sheet_count} sheet(s) analyzed{cached_note}"
            f"{failed_note} · input {ctx.total_input_tokens:,} tok, "
            f"output {ctx.total_output_tokens:,} tok{cost_note}"
        )
        self._log(summary, level=level)
        self._set_progress_text(summary, color=COLORS[level])
        # Post-run actuals: per-stage token/cost breakdown from the usage ledger
        # (§15.7). Derived from the same records the total above sums, so they agree.
        by_family = getattr(ctx, "usage_by_family", None) or {}
        if by_family:
            for fam in sorted(by_family):
                g = by_family[fam]
                fam_cost = g.get("estimated_cost")
                money = f" · ${float(fam_cost):,.2f}" if fam_cost is not None else ""
                hits = f", {g['cache_hits']} cached" if g.get("cache_hits") else ""
                self._log(
                    f"  {fam}: {g['calls']} call(s){hits} · "
                    f"in {g['input_tokens']:,} / out {g['output_tokens']:,} tok{money}",
                    level="muted",
                )
        # Resource-starvation verdict (API throttling, host CPU/memory/disk,
        # exhausted agent budgets): one line from the run's own record, so a
        # slow or partial run says whether the agents were starved and of what.
        # The full numbers are in run.log / run_manifest.json.
        pressure = getattr(ctx, "resource_pressure", None)
        # An API spend limit stops the run's paid work outright, so it gets its
        # own line ahead of the starvation summary, with the API's message (it
        # says when access resumes).
        spend_hit = getattr(pressure, "spend_limit", None)
        if spend_hit is not None:
            try:
                self._log(
                    f"API spend limit reached ({spend_hit.label}) during "
                    f"{spend_hit.stage}: {spend_hit.message} No further API requests "
                    "were sent; work finished before that point is in this export, and "
                    "a rerun after access resumes reuses any cached results.",
                    level="error",
                )
            except Exception:  # noqa: BLE001 - a diagnostic never breaks the summary
                pass
        summary_line = getattr(pressure, "summary_line", None)
        if callable(summary_line):
            try:
                starved = getattr(pressure, "starvation_status", "") == "DETECTED"
                self._log(
                    f"Resource starvation check: {summary_line()}",
                    level="warning" if starved else "muted",
                )
            except Exception:  # noqa: BLE001 - a diagnostic never breaks the summary
                pass
        # Agent headroom: did each stage's model calls have room to work (output
        # cap, effort, thinking, tool limits, per-item budgets)? The per-call
        # detail is in the export's diagnostics/ folder.
        telemetry = getattr(ctx, "call_telemetry", None)
        headroom_line = getattr(telemetry, "summary_line", None)
        if callable(headroom_line):
            try:
                starved = getattr(telemetry, "headroom_status", "") == "STARVED"
                self._log(
                    f"Agent headroom: {headroom_line()}",
                    level="warning" if starved else "muted",
                )
            except Exception:  # noqa: BLE001 - a diagnostic never breaks the summary
                pass
        # When exhaustive QC ran, surface the per-stage status so the operator can
        # see which stages are COMPLETE/PARTIAL/FAILED/SKIPPED_VALID (§15.5). With
        # the Phase 26B completeness gate open, a PARTIAL with no degraded stage
        # has exactly one remaining cause: an explicit debug override weakened the
        # exhaustive contract (§3.3 ConfigurationKind) — say so.
        cfg = getattr(ctx, "run_configuration", None)
        if cfg is not None and getattr(cfg, "exhaustive_qc", False):
            stages = getattr(ctx, "stage_results", None) or []
            incomplete = [s for s in stages if s.status in ("PARTIAL", "FAILED")]
            if incomplete:
                self._log(
                    "QC stages needing attention: "
                    + ", ".join(f"{s.stage} ({s.status})" for s in incomplete),
                    level="warning",
                )
            elif qc_status == "PARTIAL":
                self._log(
                    "Full QC ran with an explicit debug override "
                    "(a normally-required stage was disabled), so the run is "
                    "PARTIAL by definition — not a production-complete review.",
                    level="muted",
                )
        if ctx.focus:
            if ctx.focus_report_text.strip():
                self._log(
                    "Focus report ready — it leads the saved digest and has its "
                    "own card in the HTML report.",
                    level="success",
                )
            else:
                self._log(
                    "No focus report was produced for this run — see the "
                    "issue(s) above. Per-sheet Focus findings (where present) "
                    "are still in the digest.",
                    level="warning",
                )
        # Phase A: what the run detected the set to BE, and the authored plan.
        identity = getattr(ctx, "set_identity", None)
        if identity is not None:
            bits = []
            if getattr(identity, "disciplines", ()):
                bits.append(", ".join(identity.disciplines))
            where = getattr(identity, "jurisdiction", "") or ", ".join(
                p for p in (getattr(identity, "region", ""),
                            getattr(identity, "country", "")) if p
            )
            if where:
                bits.append(where)
            locale = " / ".join(
                p for p in (getattr(identity, "units", ""),
                            getattr(identity, "language", "")) if p
            )
            if locale:
                bits.append(locale)
            if bits:
                self._log("Set identity (model-detected): " + " — ".join(bits) + ".",
                          level="muted")
        plan_profiles = getattr(ctx, "review_plan_profiles", None) or []
        if plan_profiles:
            plan_items = sum(len(p.items) for p in plan_profiles)
            self._log(
                f"Review plan: model-authored — {plan_items} item(s) across "
                f"{len(plan_profiles)} discipline(s); see review_plan.md in the export.",
                level="muted",
            )
        # QC findings summary — surface the count (and how many would be inked
        # under the default verified-only gating) when a QC run produced any.
        finding_count = getattr(ctx, "finding_count", 0)
        if finding_count:
            clouded = getattr(ctx, "clouded_finding_count", 0)
            reviewed = len(getattr(ctx, "reviewed_pdf_paths", None) or [])
            parts = [f"{finding_count} QC finding(s)"]
            if reviewed:
                parts.append(f"{clouded} clouded across {reviewed} reviewed PDF(s)")
            self._log(
                f"{' · '.join(parts)}."
                + (" Save the reviewed PDF(s) with the button below."
                   if reviewed else ""),
                level="accent",
            )
            if getattr(ctx, "markup_incomplete", False):
                self._log(
                    "Markup coverage is INCOMPLETE — some planned markups are "
                    "missing/failed, or a source changed mid-run. Reviewed PDF(s) "
                    "with unaccounted markups are named …_reviewed_INCOMPLETE.pdf; "
                    "see markup_manifest.json in the export and re-run to complete.",
                    level="warning",
                )
        # Checklist results: how many items were violated, reported met, or
        # left unanswered. The detail is in the report and checklist_matrix.csv.
        checklist_report = getattr(ctx, "checklist_report", None)
        if checklist_report:
            try:
                from .checklist_matrix import (
                    CELL_NOT_REVIEWED, CELL_UNANSWERED, summary_line,
                )

                unanswered = (checklist_report.cell_total(CELL_UNANSWERED)
                              + checklist_report.cell_total(CELL_NOT_REVIEWED))
                self._log(
                    summary_line(checklist_report)
                    + " See Checklist Results in the report.",
                    level="warning" if unanswered else "accent",
                )
            except Exception as exc:  # noqa: BLE001 - a summary line never breaks completion
                _log.warning("checklist summary failed: %s", exc)
        # Part III coverage tally — every ledger entry accounted for (§18).
        tally_line = getattr(ctx, "ledger_tally_line", "") or ""
        if tally_line:
            self._log(tally_line + ".", level="muted")
        # Deterministic auditors' balance column: relationships that checked out.
        stats = getattr(ctx, "audit_stats", None) or {}
        arith_checked = int(stats.get("arithmetic_checked", 0) or 0)
        if arith_checked:
            arith_ok = int(stats.get("arithmetic_matched", 0) or 0)
            self._log(
                f"Deterministic checks: {arith_ok} of {arith_checked} numeric "
                "relationship(s) checked out ✓.",
                level="muted",
            )
        if has_text:
            self._log(
                "Digest ready — click “Save HTML Report…” for a navigable, "
                "searchable browser view of the review.",
                level="accent",
            )
        else:
            self._log("No digest text was produced for this set.", level="error")

    def _on_error(self, message: str) -> None:
        self._busy = False
        self._end_run_controls()
        live = getattr(self, "_live", None)
        if live is not None:
            live.stop(failed=True, message=message)
        self.analyze_btn.configure(state="normal", text="Analyze Drawings")
        self.clear_btn.configure(state="normal")
        self._set_focus_editable(True)
        self._refresh_spend_line()
        self._log(f"Analysis failed: {message}", level="error")
        self._set_progress_text(f"Failed: {message}", color=COLORS["error"])
        messagebox.showerror("Analysis failed", message)

    def _default_digest_filename(self, *, ext: str = ".md") -> str:
        """Suggested filename: ``<pdf-stem>-drawings-context-analysis-<stamp><ext>``.

        Named after the first uploaded PDF (the common case is one multi-sheet
        set) and stamped with the local date/time, so each saved digest is
        traceable back to its source drawings and the run that produced it.
        """
        stem = self._pdfs[0].stem if self._pdfs else "drawings"
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        return f"{stem}-drawings-context-analysis-{stamp}{ext}"

    def _on_save(self) -> None:
        # DEAD CODE (gui-export-options-cleanup): the "Save Markdown…" button
        # was removed from the GUI; this handler is retained so it can be
        # re-wired later. See the btn_row note in _build_ui.
        if not self._ctx or not self._ctx.combined_text.strip():
            return
        path = filedialog.asksaveasfilename(
            title="Save drawing digest",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
            initialfile=self._default_digest_filename(),
        )
        if not path:
            return
        try:
            Path(path).write_text(self._ctx.combined_text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._log(f"Save failed: {exc}", level="error")
            messagebox.showerror("Save failed", str(exc))
            return
        self._set_progress_text(f"Saved to {path}", color=COLORS["success"])
        self._log(f"Saved digest to {path}", level="success")

    def _on_save_html(self) -> None:
        """Write a single self-contained HTML report and open it in the browser.

        One portable file (all styling/behavior inlined) with a sidebar table of
        contents, full-text search, and category filters — so the operator can
        isolate, e.g., just the coordination items or the conflicts the model
        flagged — while still carrying every word of the digest verbatim. The
        saved file is opened with the OS default handler as a convenience (the
        whole point of the HTML view is to look at it); a failed open is
        non-fatal — the file is already written and its path is logged.
        """
        if not self._ctx or not self._ctx.combined_text.strip():
            return
        path = filedialog.asksaveasfilename(
            title="Save HTML report",
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")],
            initialfile=self._default_digest_filename(ext=".html"),
        )
        if not path:
            return
        embed_key = self._embed_key_var.get()
        try:
            source_names = [p.name for p in self._pdfs]
            # The same key that ran the analysis powers the report's built-in
            # Ask-AI assistant. By default it is NOT written into the file (the
            # panel prompts for a key at runtime); the checkbox embeds it for a
            # zero-friction, but unshareable, report.
            api_key = os.environ.get("ANTHROPIC_API_KEY") or load_api_key_from_file()
            html_doc = build_html_report(
                self._ctx, source_names=source_names, api_key=api_key or None,
                embed_api_key=embed_key,
            )
            Path(path).write_text(html_doc, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._log(f"HTML export failed: {exc}", level="error")
            messagebox.showerror("HTML export failed", str(exc))
            return
        self._set_progress_text(f"Saved HTML report to {path}", color=COLORS["success"])
        self._log(f"Saved HTML report to {path}", level="success")
        if embed_key and api_key:
            self._log(
                "The report includes the Ask-AI assistant with your API key "
                "embedded in the file — don't share it.",
                level="warning",
            )
        else:
            # The assistant is included by default (DA-026); it prompts for a
            # key on first use and never writes one into the file.
            self._log(
                "The report includes the Ask-AI assistant; it will ask for an "
                "API key on first use (kept only in the browser, not in the file).",
                level="muted",
            )
        try:
            self._open_in_os(Path(path))
            self._log("Opened the report in your browser.", level="muted")
        except Exception as exc:  # noqa: BLE001 - opener is best-effort
            self._log(f"Saved, but could not auto-open the report: {exc}", level="warning")

    def _on_export_all(self) -> None:
        """Write the complete export folder (§18.5) into a picked directory.

        One call to :func:`drawing_analyzer.export.write_drawing_export` — the
        same normalized deliverable the library API produces: the HTML report,
        every Markdown file, findings.json/csv, sheet_text/, the reviewed PDFs
        and evidence crops, markup_manifest.json, and the per-run run.log +
        run_manifest.json, staged and atomically published (DA-033). The key
        handling matches Save HTML Report: never embedded unless the checkbox
        opts in.
        """
        ctx = self._ctx
        # Deliberately NOT gated on digest text: an all-inputs-rejected or
        # preflight-blocked run is exactly when the operator needs the run
        # record (run.log, input inventory, run_manifest.json) for diagnosis —
        # the export writes an honest placeholder digest either way (§18.1).
        if not ctx or self._export_busy:
            return
        folder = filedialog.askdirectory(title="Export everything to folder")
        if not folder:
            return
        embed_key = self._embed_key_var.get()
        self._export_busy = True
        self.export_btn.configure(state="disabled", text="Exporting...")
        self._set_progress_text("Exporting full run record...", color=COLORS["text_secondary"])
        self._log("Exporting the full run record in the background...", level="muted")
        threading.Thread(
            target=self._export_all_worker,
            args=(ctx, folder, [p.name for p in self._pdfs], embed_key),
            daemon=True,
        ).start()

    def _export_all_worker(
        self,
        ctx: DrawingContext,
        folder: str,
        source_names: list[str],
        embed_key: bool,
    ) -> None:
        """Build/hash/copy a complete export without blocking Tk's event loop."""
        from .export import write_drawing_export

        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY") or load_api_key_from_file()
            out = write_drawing_export(
                ctx, folder, source_names=source_names,
                api_key=api_key or None, embed_api_key=embed_key,
            )
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda e=exc: self._on_export_all_failed(e))
            return
        self.after(0, lambda: self._on_export_all_done(ctx, out))

    def _on_export_all_failed(self, exc: Exception) -> None:
        self._export_busy = False
        self.export_btn.configure(state="normal", text="Export All...")
        self._log(f"Export failed: {exc}", level="error")
        self._set_progress_text(f"Export failed: {exc}", color=COLORS["error"])
        messagebox.showerror("Export failed", str(exc))

    def _on_export_all_done(self, ctx: DrawingContext, out: Path) -> None:
        self._export_busy = False
        self.export_btn.configure(state="normal", text="Export All...")
        self._set_progress_text(f"Exported everything to {out}", color=COLORS["success"])
        self._log(f"Exported the full run record to {out}", level="success")
        if getattr(ctx, "markup_incomplete", False):
            self._log(
                "Markup coverage is INCOMPLETE — the reviewed PDF(s) are labeled "
                "and markup_manifest.json / run.log carry the failed placements.",
                level="warning",
            )
        try:
            self._open_in_os(out)
        except Exception as exc:  # noqa: BLE001 - opener is best-effort
            self._log(f"Exported, but could not open the folder: {exc}", level="warning")

    def _on_save_csv(self) -> None:
        """Write the findings CSV (Excel-friendly: UTF-8 BOM + CRLF).

        DEAD CODE (gui-export-options-cleanup): the "Save Findings CSV…" button
        was removed from the GUI; this handler is retained so it can be re-wired
        later. See the btn_row note in _build_ui.
        """
        ctx = self._ctx
        if not ctx or not getattr(ctx, "finding_count", 0):
            return
        from .export import write_findings_csv

        path = filedialog.asksaveasfilename(
            title="Save findings CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            initialfile=self._default_digest_filename(ext=".csv"),
        )
        if not path:
            return
        try:
            write_findings_csv(ctx.all_findings, path)
        except Exception as exc:  # noqa: BLE001
            self._log(f"CSV export failed: {exc}", level="error")
            messagebox.showerror("CSV export failed", str(exc))
            return
        self._set_progress_text(f"Saved findings CSV to {path}", color=COLORS["success"])
        self._log(f"Saved findings CSV to {path}", level="success")

    def _on_save_reviewed(self) -> None:
        """Copy the run's marked-up ``*_reviewed.pdf`` files into a chosen folder.

        The reviewed PDFs live in the run's temporary work dir until saved; this
        copies each one out into a directory the operator picks. Copies are
        best-effort per file — a missing source is skipped and noted — so one bad
        file never aborts the rest.
        """
        ctx = self._ctx
        reviewed = list(getattr(ctx, "reviewed_pdf_paths", None) or [])
        if not reviewed:
            return
        folder = filedialog.askdirectory(title="Save reviewed PDF(s) to folder")
        if not folder:
            return
        import shutil

        dest_dir = Path(folder)
        saved = 0
        for src in reviewed:
            src_path = Path(src)
            if not src_path.exists():
                self._log(f"Skipped missing reviewed PDF: {src_path.name}", level="warning")
                continue
            try:
                shutil.copy2(src_path, dest_dir / src_path.name)
                saved += 1
            except Exception as exc:  # noqa: BLE001
                self._log(f"Could not copy {src_path.name}: {exc}", level="error")
        if saved:
            self._set_progress_text(
                f"Saved {saved} reviewed PDF(s) to {dest_dir}", color=COLORS["success"]
            )
            self._log(f"Saved {saved} reviewed PDF(s) to {dest_dir}", level="success")
        else:
            self._log("No reviewed PDFs were saved.", level="warning")
            messagebox.showwarning(
                "Save reviewed PDFs", "None of the reviewed PDFs could be saved."
            )

    # ----------------------------------------------------------- diagnostics

    def _open_in_os(self, target: Path) -> None:
        """Open a file or folder with the OS default handler (cross-platform)."""
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        else:
            subprocess.run(["xdg-open", str(target)], check=False)

    def _on_open_log(self) -> None:
        """Open the diagnostics log file (or its folder) in the OS viewer.

        The detailed, request-level trace (which image failed, HTTP status,
        request-id, batch id) lives in a file rather than this activity log; this
        button makes it reachable without hunting through the platform config
        dir. Falls back to revealing the folder if the file does not exist yet,
        and to a dialog showing the path if the OS opener fails.
        """
        path = diagnostics.configured_log_path()
        if path is None:
            messagebox.showinfo(
                "Diagnostics log",
                "Diagnostics file logging is not active for this session.\n\n"
                "It is on by default; check that DRAWING_ANALYZER_DIAGNOSTICS is "
                "not set to 0.",
            )
            return
        target = path if path.exists() else path.parent
        try:
            self._open_in_os(target)
            self._log(f"Opened diagnostics log: {path}", level="muted")
        except Exception as exc:  # noqa: BLE001 - opener is best-effort
            self._log(f"Could not open the diagnostics log: {exc}", level="warning")
            messagebox.showinfo(
                "Diagnostics log", f"The diagnostics log is here:\n\n{path}"
            )

    # ------------------------------------------------------------ self-update

    def _build_footer(self, parent) -> None:
        """A slim footer: version at left, an update-status note, and a button.

        Deliberately NOT a fifth header button — the header row is
        width-constrained (see ``_build_help_buttons``). The footer keeps the
        version visible and gives the manual update check a permanent home,
        matching the "Help ▸ About / Check for Updates" placement desktop users
        expect. See ``core/updates.py`` for the mechanism.
        """
        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=16, pady=(0, 12))
        self._footer = footer
        ctk.CTkLabel(
            footer, text=f"v{__version__}",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        ).pack(side="left")
        self.update_status_label = ctk.CTkLabel(
            footer, text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )
        self.update_status_label.pack(side="left", padx=(10, 0))
        self.check_update_btn = ctk.CTkButton(
            footer, text="Check for Updates", width=150, height=28,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            command=self._on_check_for_updates_clicked,
        )
        self.check_update_btn.pack(side="right")

    def _set_update_status(self, text: str, *, color: str | None = None) -> None:
        label = getattr(self, "update_status_label", None)
        if label is not None:
            try:
                label.configure(text=text, text_color=color or COLORS["text_muted"])
            except Exception:  # pragma: no cover - defensive UI update
                pass

    def _maybe_auto_check_for_updates(self) -> None:
        """Launch a silent, throttled update check (once/day). Never nags.

        Only surfaces a dialog if an update is available and the user has not
        chosen to skip that version; a clean or failed check stays silent.
        """
        try:
            if updates.update_check_disabled():
                return
            state = updates.load_state(self._update_state_path)
            if not updates.should_auto_check(state, now=datetime.now()):
                return
        except Exception:  # noqa: BLE001 - startup convenience, never fatal
            return
        self._start_update_check(manual=False)

    def _on_check_for_updates_clicked(self) -> None:
        """The footer button: an explicit check that always reports its result."""
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        if self._update_checking:
            return
        self._update_checking = True
        if manual:
            try:
                self.check_update_btn.configure(state="disabled", text="Checking…")
            except Exception:  # pragma: no cover - defensive UI update
                pass
            self._set_update_status("Checking for updates…")
        threading.Thread(
            target=self._update_check_worker, args=(manual,), daemon=True
        ).start()

    def _update_check_worker(self, manual: bool) -> None:
        """Fetch + compare off the UI thread; marshal the result back via after()."""
        result = updates.check_for_update(__version__)
        # Record the check time regardless of outcome so the daily throttle holds.
        try:
            state = updates.load_state(self._update_state_path)
            updates.record_check(state, now=datetime.now())
            updates.save_state(self._update_state_path, state)
        except Exception:  # noqa: BLE001 - best-effort state write
            pass
        self.after(0, lambda: self._on_update_check_done(result, manual))

    def _on_update_check_done(self, result, manual: bool) -> None:
        self._update_checking = False
        try:
            self.check_update_btn.configure(state="normal", text="Check for Updates")
        except Exception:  # pragma: no cover - defensive UI update
            pass

        if result.status == updates.STATUS_UPDATE_AVAILABLE and result.info is not None:
            info = result.info
            self._set_update_status(
                f"Update available: v{info.version}", color=COLORS["accent_glow"]
            )
            skipped = False
            if not manual:
                try:
                    state = updates.load_state(self._update_state_path)
                    skipped = updates.version_is_skipped(state, info.version)
                except Exception:  # noqa: BLE001
                    skipped = False
            if manual or not skipped:
                self._show_update_dialog(info)
            return

        if result.status == updates.STATUS_UP_TO_DATE:
            self._set_update_status("You're up to date.")
            if manual:
                messagebox.showinfo(
                    "Up to date",
                    f"You're running the latest version (v{__version__}).",
                )
            return

        if result.status == updates.STATUS_DISABLED:
            if manual:
                messagebox.showinfo(
                    "Update checks are off",
                    "Automatic update checks are disabled by the "
                    "DRAWING_ANALYZER_DISABLE_UPDATE_CHECK environment variable.",
                )
            return

        # STATUS_ERROR
        self._set_update_status("Update check failed.")
        if manual:
            messagebox.showwarning(
                "Couldn't check for updates",
                "Could not reach the update service.\n\n"
                f"{result.error or 'Unknown error.'}\n\n"
                "You can download the latest version manually from the "
                "releases page.",
            )

    def _show_update_dialog(self, info) -> None:
        """A styled dialog offering to download + install ``info`` (or skip / defer)."""
        existing = getattr(self, "_update_dialog", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        win = ctk.CTkToplevel(self)
        self._update_dialog = win
        win.title("Update available")
        win.configure(fg_color=COLORS["bg_dark"])
        win.geometry("560x480")
        win.minsize(460, 380)
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW", self._close_update_dialog)
        win.after(150, lambda: self._grab_help_modal(win))

        card = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=8)
        card.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            card, text=f"Version {info.version} is available",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color=COLORS["text_primary"], justify="left",
        ).pack(anchor="w", padx=18, pady=(16, 2))
        ctk.CTkLabel(
            card,
            text=(
                f"You have v{__version__}. Update to get the latest fixes and "
                "improvements. The app will close so the installer can replace it."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], wraplength=490, justify="left",
        ).pack(anchor="w", padx=18, pady=(0, 8))

        # Bottom button bar first so pack reserves the bottom edge.
        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=18, pady=(4, 14))
        self._update_download_btn = ctk.CTkButton(
            bottom, text="Download & Install", width=170, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=lambda: self._start_update_download(info),
        )
        self._update_download_btn.pack(side="right")
        self._update_later_btn = ctk.CTkButton(
            bottom, text="Later", width=80, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            command=self._close_update_dialog,
        )
        self._update_later_btn.pack(side="right", padx=(0, 8))
        self._update_skip_btn = ctk.CTkButton(
            bottom, text="Skip this Version", width=140, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_muted"],
            command=lambda: self._skip_update_version(info),
        )
        self._update_skip_btn.pack(side="left")

        # Progress row — created now, packed only once a download starts.
        self._update_progress = ctk.CTkProgressBar(card, height=10)
        self._update_progress.set(0)
        self._update_progress_status = ctk.CTkLabel(
            card, text="",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
        )

        ctk.CTkLabel(
            card, text="What's new",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLORS["accent_glow"],
        ).pack(anchor="w", padx=18, pady=(6, 2))
        notes = (info.notes or "").strip() or "No release notes were provided."
        notes_box = ctk.CTkTextbox(
            card, fg_color=COLORS["bg_dark"], text_color=COLORS["text_secondary"],
            wrap="word", height=150,
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        notes_box.pack(fill="both", expand=True, padx=18, pady=(0, 6))
        notes_box.insert("1.0", notes)
        notes_box.configure(state="disabled")

        link = ctk.CTkLabel(
            card, text="View this release on GitHub",
            font=ctk.CTkFont(family="Segoe UI", size=11, underline=True),
            text_color=COLORS["accent_glow"], cursor="hand2",
        )
        link.pack(anchor="w", padx=18, pady=(0, 4))
        link.bind("<Button-1>", lambda _e: self._open_releases_page())

    def _start_update_download(self, info) -> None:
        if self._update_downloading:
            # A download is already running (e.g. the dialog was closed and
            # reopened). Don't start a second writer to the same file.
            self._set_update_status("A download is already in progress…")
            return
        if self._busy:
            messagebox.showinfo(
                "Analysis in progress",
                "Please wait for the current analysis to finish before updating.",
            )
            return
        self._update_downloading = True
        self._update_download_cancelled = False
        for name in ("_update_download_btn", "_update_skip_btn", "_update_later_btn"):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state="disabled")
                except Exception:  # pragma: no cover - defensive UI update
                    pass
        try:
            self._update_progress_status.pack(side="bottom", fill="x", padx=18, pady=(0, 2))
            self._update_progress.pack(side="bottom", fill="x", padx=18, pady=(2, 4))
            self._update_progress.set(0)
            self._update_progress_status.configure(text="Starting download…")
        except Exception:  # pragma: no cover - defensive UI update
            pass
        threading.Thread(
            target=self._update_download_worker, args=(info,), daemon=True
        ).start()

    def _update_download_worker(self, info) -> None:
        try:
            dest_dir = app_config_dir() / "updates"

            def _progress(done: int, total: int) -> None:
                self.after(0, lambda d=done, t=total: self._on_update_download_progress(d, t))

            path = updates.download_installer(info, dest_dir, progress=_progress)
        except Exception as exc:  # noqa: BLE001 - surfaced in the dialog
            self.after(0, lambda e=str(exc): self._on_update_download_error(e))
            return
        self.after(0, lambda p=path: self._on_update_download_done(p))

    def _on_update_download_progress(self, done: int, total: int) -> None:
        mb = 1024 * 1024
        try:
            if total > 0:
                self._update_progress.set(min(1.0, done / total))
                self._update_progress_status.configure(
                    text=f"Downloading… {done // mb} / {total // mb} MB"
                )
            else:
                self._update_progress_status.configure(
                    text=f"Downloading… {done // mb} MB"
                )
        except Exception:  # pragma: no cover - defensive UI update
            pass

    def _on_update_download_done(self, path) -> None:
        self._update_downloading = False
        if self._update_download_cancelled or self._update_dialog is None:
            # The user dismissed the update dialog while the download was in
            # flight — respect that and don't pop a surprise install prompt. The
            # verified file stays cached; the next check will offer it again.
            self._set_update_status("Update downloaded — install it later.")
            return
        try:
            self._update_progress.set(1.0)
            self._update_progress_status.configure(text="Download verified.")
        except Exception:  # pragma: no cover - defensive UI update
            pass
        proceed = messagebox.askyesno(
            "Install update",
            "The update downloaded and passed its integrity check.\n\n"
            "Drawing Analyzer will now close so the installer can replace it. "
            "Continue?",
        )
        if not proceed:
            self._reset_update_dialog_buttons()
            self._set_update_status("Update downloaded (not installed).")
            return
        try:
            updates.spawn_installer(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Couldn't start the installer",
                f"The installer was saved to:\n\n{path}\n\n"
                f"but could not be launched automatically ({exc}).\n"
                "You can run it manually.",
            )
            self._reset_update_dialog_buttons()
            return
        # Release the modal grab / tear down the dialog, then exit so the
        # installer can replace the running files (installer.iss sets
        # CloseApplications=yes to close any lingering handle on them).
        self._close_update_dialog()
        self.quit()

    def _on_update_download_error(self, message: str) -> None:
        self._update_downloading = False
        if self._update_download_cancelled or self._update_dialog is None:
            # Dialog was dismissed mid-download; fail quietly.
            self._set_update_status("Update download cancelled.")
            return
        self._reset_update_dialog_buttons()
        self._set_update_status("Update download failed.")
        messagebox.showerror(
            "Download failed",
            f"The update could not be downloaded or verified:\n\n{message}\n\n"
            "You can download it manually from the releases page.",
        )

    def _reset_update_dialog_buttons(self) -> None:
        for name in ("_update_download_btn", "_update_skip_btn", "_update_later_btn"):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.configure(state="normal")
                except Exception:  # pragma: no cover - defensive UI update
                    pass
        for name in ("_update_progress", "_update_progress_status"):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.pack_forget()
                except Exception:  # pragma: no cover - defensive UI update
                    pass

    def _skip_update_version(self, info) -> None:
        try:
            state = updates.load_state(self._update_state_path)
            updates.mark_skipped(state, info.version)
            updates.save_state(self._update_state_path, state)
        except Exception:  # noqa: BLE001 - best-effort state write
            pass
        self._set_update_status(f"Skipped v{info.version}.")
        self._close_update_dialog()

    def _open_releases_page(self) -> None:
        try:
            webbrowser.open(updates.releases_page_url())
        except Exception:  # pragma: no cover - best-effort external opener
            pass

    def _close_update_dialog(self) -> None:
        if self._update_downloading:
            # Cancel the in-flight download's completion handling so it can't
            # pop a surprise install prompt after the dialog is dismissed.
            self._update_download_cancelled = True
        win = getattr(self, "_update_dialog", None)
        self._update_dialog = None
        if win is None:
            return
        try:
            win.grab_release()
        except Exception:  # pragma: no cover - platform dependent
            pass
        try:
            win.destroy()
        except Exception:  # pragma: no cover - platform dependent
            pass

    # -- window lifecycle ------------------------------------------------- #

    def _on_close_request(self) -> None:
        """Confirm before discarding an in-flight run (P9 item 47).

        The worker threads are daemons and the export runs *after* the analysis
        returns, so closing mid-run destroys a paid run's results with nothing on
        disk. A quiet window closes immediately — this is a guard, not a
        ceremony.

        Quitting mid-analysis pulls the kill switch first: a daemon worker dies
        with the process, but a remote Message Batch would keep running — and
        billing — after the window closed (see :meth:`_stop_then_quit`). A
        second close request while that stop settles closes at once.
        """
        if self._quitting:
            self.destroy()
            return
        busy = _describe_busy(bool(self._busy), bool(self._export_busy))
        stops_run = bool(self._busy) and self._run_cancel is not None
        if busy:
            consequence = (
                "Quitting stops the run first: nothing new is sent, remote "
                "batches are canceled, and requests in flight are abandoned. "
                if stops_run else ""
            )
            try:
                keep_open = not messagebox.askyesno(
                    "Quit Drawing Analyzer?",
                    f"{busy}\n\n"
                    f"{consequence}"
                    "Quitting now discards it — nothing has been exported yet, "
                    "and the API calls already made are still billed.\n\n"
                    "Quit anyway?",
                    default="no",
                    icon="warning",
                    parent=self,
                )
            except Exception:  # noqa: BLE001 - never trap the user in the window
                keep_open = False
            if keep_open:
                return
            if stops_run:
                self._stop_then_quit()
                return
        self.destroy()

    def _stop_then_quit(self) -> None:
        """Stop the run, then close once the stop has settled (or the grace ends).

        Settled means the worker has unwound — so a batch whose submit was in
        flight at the stop has been canceled on its way out — and the stop's
        remote batch cancels have been sent. The wait is bounded: the window
        never hangs on a slow network.
        """
        token = self._run_cancel
        self._quitting = True
        self._request_stop()
        self._set_progress_text("Stopping the run before quitting…", color=COLORS["warning"])
        deadline = time.monotonic() + QUIT_STOP_GRACE_SECONDS

        def _poll() -> None:
            settled = not self._busy and (
                token is None or token.wait_for_remote_cancels(0)
            )
            if settled or time.monotonic() >= deadline:
                if not settled:
                    diagnostics.get_logger().warning(
                        "quit: the stop did not settle within %ss; closing anyway",
                        QUIT_STOP_GRACE_SECONDS,
                    )
                self.destroy()
                return
            self.after(100, _poll)

        _poll()

    def _on_callback_exception(self, exc_type, exc_value, exc_tb) -> None:
        """Tk callback error hook (N32).

        Tk's default handler prints a traceback to ``sys.stderr``; the shipped
        app is a windowed build where that is ``None``, so an exception in a
        button handler left the UI looking like the click did nothing. Record it
        in the diagnostics trace, put one line in the activity log, and say so
        once — while staying non-fatal, exactly as Tk's own handler is.
        """
        try:
            # ``diagnostics.get_logger()`` rather than the module-level ``_log``,
            # which this class shadows with its activity-log method.
            diagnostics.get_logger().error(
                "tk callback failed", exc_info=(exc_type, exc_value, exc_tb)
            )
        except Exception:  # noqa: BLE001 - the reporter must never raise
            pass
        detail = f"{getattr(exc_type, '__name__', exc_type)}: {exc_value}"
        try:
            self._log(f"Internal error: {detail}")
        except Exception:  # noqa: BLE001 - the log widget may be gone
            pass
        try:
            messagebox.showerror(
                "Drawing Analyzer - internal error",
                "Something went wrong handling that action:\n\n"
                f"{detail}\n\n"
                "The app is still running. Details were written to the "
                'diagnostics log - see "Open Diagnostics Log".',
                parent=self,
            )
        except Exception:  # noqa: BLE001 - no display / window already gone
            pass


# How long quitting mid-run waits for the stop to settle (worker unwound,
# remote batch cancels sent) before closing anyway.
QUIT_STOP_GRACE_SECONDS = 30.0


# How often the spend line re-reads the run's monitor.
SPEND_REFRESH_MS = 1000


def parse_budget(text: str) -> float:
    """A typed budget cap as dollars. ``ValueError`` unless it is a positive amount."""
    cleaned = str(text or "").strip().lstrip("$").replace(",", "").strip()
    amount = float(cleaned)            # ValueError on "" or non-numeric text
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("a budget cap must be greater than zero")
    return amount


def _wheel_steps(delta: int) -> float:
    """Mouse-wheel notches from a Tk ``<MouseWheel>`` delta.

    Windows reports multiples of 120 per notch; macOS reports small integers.
    """
    delta = int(delta or 0)
    if abs(delta) >= 120:
        return delta / 120.0
    return float(max(-3, min(3, delta)))


def _describe_busy(analysis: bool, export: bool) -> str:
    """Which long-running job is in flight, for the confirm-on-close prompt.

    Split out from the handler so the wording is testable without a Tk root.
    """
    if analysis and export:
        return "An analysis run and an export are still running."
    if analysis:
        return "An analysis run is still in progress."
    if export:
        return "An export is still being written."
    return ""


def _ask_cost_confirmation(parent, title: str, prompt: str) -> tuple[bool, bool]:
    """A Yes/No cost confirmation with a "Don't show this again" checkbox.

    Modal over ``parent``; returns ``(proceed, dont_show_again)``. Closing the
    window or Escape is No. The opt-out is reported only on Yes — skipping the
    dialog means proceeding, so a ticked box on No would remember nothing.
    """
    result = {"proceed": False}
    win = ctk.CTkToplevel(parent)
    win.title(title)
    win.configure(fg_color=COLORS["bg_dark"])
    win.geometry("760x620")
    win.minsize(560, 400)
    win.transient(parent)
    dont_show = BooleanVar(master=win, value=False)

    def finish(proceed: bool) -> None:
        result["proceed"] = proceed
        try:
            win.grab_release()
        except Exception:  # noqa: BLE001 - platform dependent
            pass
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    win.bind("<Escape>", lambda _e: finish(False))

    card = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=8)
    card.pack(fill="both", expand=True, padx=12, pady=12)
    ctk.CTkLabel(
        card, text=title,
        font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
        text_color=COLORS["text_primary"], justify="left",
    ).pack(anchor="w", padx=18, pady=(16, 8))

    # Bottom bar first so pack reserves the bottom edge before the text expands.
    bottom = ctk.CTkFrame(card, fg_color="transparent")
    bottom.pack(side="bottom", fill="x", padx=18, pady=(4, 14))
    yes_btn = ctk.CTkButton(
        bottom, text="Yes", width=90, height=34,
        font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
        command=lambda: finish(True),
    )
    yes_btn.pack(side="right")
    ctk.CTkButton(
        bottom, text="No", width=90, height=34,
        font=ctk.CTkFont(family="Segoe UI", size=12),
        fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
        border_width=1, border_color=COLORS["border"],
        text_color=COLORS["text_secondary"],
        command=lambda: finish(False),
    ).pack(side="right", padx=(0, 8))
    ctk.CTkCheckBox(
        bottom, text="Don't show this again", variable=dont_show,
        font=ctk.CTkFont(family="Segoe UI", size=12),
        text_color=COLORS["text_secondary"],
        checkbox_width=18, checkbox_height=18,
    ).pack(side="left")

    body = ctk.CTkTextbox(
        card, fg_color=COLORS["bg_dark"], text_color=COLORS["text_secondary"],
        font=ctk.CTkFont(family="Segoe UI", size=12), wrap="word",
    )
    body.pack(fill="both", expand=True, padx=18, pady=(0, 8))
    body.insert("1.0", prompt)
    body.configure(state="disabled")

    def grab() -> None:
        try:
            if win.winfo_exists():
                win.grab_set()
                yes_btn.focus_set()
        except Exception:  # noqa: BLE001 - grabbing before viewable can raise
            pass

    # Grabbing before the toplevel is viewable raises on some platforms.
    win.after(150, grab)
    parent.wait_window(win)
    return result["proceed"], result["proceed"] and bool(dont_show.get())


def _display_path(path: Path) -> str:
    """``path`` with the home folder shown as ``~`` (shorter, and no user name)."""
    try:
        return str(Path("~") / Path(path).resolve().relative_to(Path.home().resolve()))
    except (ValueError, OSError, RuntimeError):
        return str(path)


def _save_checks_dialog(parent, request, *, on_saved) -> None:
    """Save checks picked on the Live view's Plan tab into a checklist.

    Non-modal to the event loop (the Save button does the work): the checks
    go into a new checklist in the profiles folder, or are added to one that
    is already there (:mod:`checklist_save`). What will be written — the file,
    the checks added, the ones skipped because their text is already kept —
    is re-planned as the reader changes the form, and planned once more
    against the disk when Save is pressed. ``on_saved`` gets the written
    :class:`~drawing_analyzer.checklist_save.SavePlan`.
    """
    from . import checklist_save as cs

    checks = [cs.PickedCheck(id=r.id, text=r.text) for r in request.checks]
    if not checks:
        return
    try:
        targets = cs.saved_checklists()
    except Exception as exc:  # noqa: BLE001 - an unreadable folder still allows a new file
        _log.warning("could not list saved checklists: %s", exc)
        targets = []
    labels: list[str] = []
    for t in targets:
        label = t.title if t.title not in labels else f"{t.title} ({t.path.name})"
        labels.append(label)
    titles = list(dict.fromkeys(r.title for r in request.checks if r.title))
    prefixes = list(cs.clean_prefixes([p for r in request.checks for p in r.prefixes]))
    known_ids = {str(k[0]) for k in request.known}
    n = len(checks)

    win = ctk.CTkToplevel(parent)
    win.title("Save checks")
    win.configure(fg_color=COLORS["bg_dark"])
    win.geometry("700x660")
    win.minsize(560, 520)
    win.transient(parent)
    mode = StringVar(master=win, value="new")
    name_var = StringVar(master=win, value=titles[0] if len(titles) == 1 else cs.DEFAULT_TITLE)
    target_var = StringVar(master=win, value=labels[0] if labels else "(no checklists yet)")
    font = ctk.CTkFont(family="Segoe UI", size=12)
    small = ctk.CTkFont(family="Segoe UI", size=11)

    def close() -> None:
        try:
            win.grab_release()
        except Exception:  # noqa: BLE001 - platform dependent
            pass
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda _e: close())

    card = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=8)
    card.pack(fill="both", expand=True, padx=12, pady=12)
    ctk.CTkLabel(
        card, text=f"Save {n} check{'s' if n != 1 else ''} to a checklist",
        font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
        text_color=COLORS["text_primary"],
    ).pack(anchor="w", padx=18, pady=(16, 2))
    ctk.CTkLabel(
        card, text=("Saved checks join your checklists and are sent to the reviewer "
                    "on future runs, alongside the model's plan."),
        font=small, text_color=COLORS["text_muted"], wraplength=620, justify="left",
    ).pack(anchor="w", padx=18, pady=(0, 10))

    # Bottom bar first so pack reserves the bottom edge before the list expands.
    bottom = ctk.CTkFrame(card, fg_color="transparent")
    bottom.pack(side="bottom", fill="x", padx=18, pady=(4, 14))
    save_btn = ctk.CTkButton(
        bottom, text="Save", width=130, height=34,
        font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
    )
    save_btn.pack(side="right")
    ctk.CTkButton(
        bottom, text="Cancel", width=90, height=34, font=font,
        fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
        border_width=1, border_color=COLORS["border"],
        text_color=COLORS["text_secondary"], command=close,
    ).pack(side="right", padx=(0, 8))
    path_label = ctk.CTkLabel(
        bottom, text="", font=ctk.CTkFont(family="Consolas", size=11),
        text_color=COLORS["text_muted"], anchor="w",
    )
    path_label.pack(side="left", fill="x", expand=True)
    # The notes sit above the bar, also reserved before the list expands.
    notes = ctk.CTkLabel(card, text="", font=small, text_color=COLORS["text_secondary"],
                         wraplength=640, justify="left", anchor="w")
    notes.pack(side="bottom", fill="x", padx=18, pady=(8, 4))

    form = ctk.CTkFrame(card, fg_color="transparent")
    form.pack(fill="x", padx=18)
    form.grid_columnconfigure(1, weight=1)

    def field_label(row: int, text: str) -> None:
        ctk.CTkLabel(form, text=text, font=font, text_color=COLORS["text_secondary"]).grid(
            row=row, column=0, sticky="w", padx=(0, 14), pady=5)

    field_label(0, "Save to")
    radios = ctk.CTkFrame(form, fg_color="transparent")
    radios.grid(row=0, column=1, sticky="w", pady=5)
    ctk.CTkRadioButton(
        radios, text="A new checklist", variable=mode, value="new", font=font,
        text_color=COLORS["text_primary"], command=lambda: refresh(),
    ).pack(side="left", padx=(0, 24))
    ctk.CTkRadioButton(
        radios, text="Add to an existing one" if targets else "Add to an existing one (none yet)",
        variable=mode, value="existing", font=font, text_color=COLORS["text_primary"],
        state="normal" if targets else "disabled", command=lambda: refresh(),
    ).pack(side="left")

    field_label(1, "Name")
    name_entry = ctk.CTkEntry(
        form, textvariable=name_var, height=30, font=font,
        fg_color=COLORS["bg_input"], border_color=COLORS["border"],
        text_color=COLORS["text_primary"],
    )
    name_entry.grid(row=1, column=1, sticky="ew", pady=5)
    name_entry.bind("<KeyRelease>", lambda _e: refresh())

    field_label(2, "Existing")
    target_menu = ctk.CTkOptionMenu(
        form, values=labels or [target_var.get()], variable=target_var, font=font,
        fg_color=COLORS["bg_input"], button_color=COLORS["border"],
        button_hover_color=COLORS["accent_hover"], text_color=COLORS["text_primary"],
        command=lambda _v: refresh(),
    )
    target_menu.grid(row=2, column=1, sticky="ew", pady=5)

    field_label(3, "Applies to")
    applies = ctk.CTkFrame(form, fg_color="transparent")
    applies.grid(row=3, column=1, sticky="ew", pady=5)
    chip_box = ctk.CTkFrame(applies, fg_color="transparent")
    chip_box.pack(side="left")
    prefix_entry = ctk.CTkEntry(
        applies, width=130, height=28, font=small, placeholder_text="+ sheet prefix",
        fg_color=COLORS["bg_input"], border_color=COLORS["border"],
        text_color=COLORS["text_primary"],
    )
    prefix_entry.pack(side="left")

    ctk.CTkLabel(
        card, text="CHECKS TO SAVE", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
        text_color=COLORS["text_muted"],
    ).pack(anchor="w", padx=18, pady=(12, 2))
    listing = ctk.CTkTextbox(
        card, height=150, fg_color=COLORS["bg_dark"], text_color=COLORS["text_primary"],
        font=font, wrap="word",
    )
    listing.pack(fill="both", expand=True, padx=18)
    listing.insert("1.0", "\n".join(f"{c.id}    {c.text}" for c in checks))
    listing.configure(state="disabled")

    def target() -> "cs.SavedChecklist | None":
        try:
            return targets[labels.index(target_var.get())]
        except ValueError:
            return None

    def add_prefixes(_event=None) -> None:
        for tag in cs.clean_prefixes(prefix_entry.get()):
            if tag not in prefixes:
                prefixes.append(tag)
        prefix_entry.delete(0, "end")
        refresh()

    def remove_prefix(tag: str) -> None:
        if tag in prefixes:
            prefixes.remove(tag)
        refresh()

    prefix_entry.bind("<Return>", add_prefixes)

    def render_chips(existing: bool, chosen) -> None:
        for child in chip_box.winfo_children():
            child.destroy()
        shown = list(chosen.disciplines) if existing and chosen is not None else prefixes
        for tag in shown:
            ctk.CTkButton(
                chip_box, text=tag.upper() if existing else f"{tag.upper()}  ×",
                width=44, height=26, corner_radius=13, font=small,
                fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
                border_width=1, border_color=COLORS["accent"],
                text_color=COLORS["accent_glow"], text_color_disabled=COLORS["accent_glow"],
                state="disabled" if existing else "normal",
                command=lambda t=tag: remove_prefix(t),
            ).pack(side="left", padx=(0, 6))
        if not shown:
            ctk.CTkLabel(chip_box, text="every sheet", font=small,
                         text_color=COLORS["text_muted"]).pack(side="left", padx=(0, 8))
        prefix_entry.configure(state="disabled" if existing else "normal")

    def refresh() -> None:
        existing = mode.get() == "existing" and bool(targets)
        chosen = target() if existing else None
        name_entry.configure(state="disabled" if existing else "normal")
        target_menu.configure(state="normal" if existing else "disabled")
        render_chips(existing, chosen)
        try:
            if existing:
                plan = cs.plan_append(chosen, checks, known=request.known)
            else:
                plan = cs.plan_new(name_var.get(), checks, disciplines=prefixes,
                                   known=request.known)
        except Exception as exc:  # noqa: BLE001 - shown in the dialog, never raised
            notes.configure(text=f"Cannot save there: {exc}", text_color=COLORS["error"])
            save_btn.configure(state="disabled", text="Save")
            path_label.configure(text="")
            return
        lines: list[str] = []
        for check, where in plan.skipped:
            if where.startswith("item "):
                lines.append(f"{check.id} is already in “{plan.title}” ({where}) "
                             "and will be skipped.")
            elif where in known_ids:
                lines.append(f"{check.id} is already in your checklist ({where}) "
                             "and will be skipped.")
            else:
                lines.append(f"{check.id} repeats {where} and will be skipped.")
        codes = ", ".join(request.codes)
        lines.append("Code citations are kept as written" + (f" ({codes})" if codes else "")
                     + ". Re-check them before using this checklist on a set that adopts "
                     "another edition.")
        tags = plan.disciplines
        if tags:
            lines.append("Suggested automatically for sets whose sheet numbers start with "
                         + ", ".join(f"{t.upper()}-" for t in tags) + ".")
        else:
            lines.append("No sheet prefix: it applies to every sheet; tick it under "
                         "Review profiles to use it.")
        notes.configure(text="\n".join(f"•  {ln}" for ln in lines),
                        text_color=COLORS["text_secondary"])
        k = len(plan.adding)
        save_btn.configure(
            state="normal" if k else "disabled",
            text=f"Save {k} check{'s' if k != 1 else ''}" if k else "Nothing new to save",
        )
        path_label.configure(text="→ " + _display_path(plan.path))

    def save() -> None:
        if prefix_entry.get().strip():
            add_prefixes()
        existing = mode.get() == "existing" and bool(targets)
        try:
            if existing:
                result = cs.save_append(target(), checks, known=request.known)
            else:
                result = cs.save_new(name_var.get(), checks, disciplines=prefixes,
                                     known=request.known)
        except (OSError, ValueError, TypeError) as exc:
            notes.configure(text=f"Not saved: {exc}", text_color=COLORS["error"])
            return
        close()
        on_saved(result)

    save_btn.configure(command=save)
    refresh()

    def grab() -> None:
        try:
            if win.winfo_exists():
                win.grab_set()
                name_entry.focus_set()
                name_entry.select_range(0, "end")
        except Exception:  # noqa: BLE001 - grabbing before viewable can raise
            pass

    # Grabbing before the toplevel is viewable raises on some platforms.
    win.after(150, grab)


def main() -> None:
    # Start the on-disk diagnostics trace before anything else so the whole
    # session (including startup) is captured. Best-effort: never fatal.
    diagnostics.configure_file_logging()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = DrawingAnalyzerApp()
    # The app has loaded its saved key; maintenance must not block the UI.
    from .file_upload import start_upload_reaper
    start_upload_reaper()
    app.mainloop()
