"""Standalone CustomTkinter window for the drawing-context extractor.

Drop (or browse for) construction drawing PDFs, press Analyze, and the
subsystem renders + digests every sheet and shows the combined text digest,
which can be saved to a ``.md`` file for use as Project Context in the spec
reviewer. Runs the analysis on a worker thread so the UI stays responsive, and
reuses the main app's color palette for a consistent look.

Launch with ``python -m drawing_analyzer``.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, filedialog, messagebox

import customtkinter as ctk

try:  # drag-and-drop is optional (mirrors the main app shell)
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # pragma: no cover - depends on optional dependency
    DND_FILES = None
    TkinterDnD = None

if TkinterDnD is not None:
    class _CTkDnDRoot(ctk.CTk, TkinterDnD.DnDWrapper):
        pass
else:  # pragma: no cover - exercised only without tkinterdnd2
    _CTkDnDRoot = ctk.CTk

from . import diagnostics
from .core.api_config import REVIEW_MODEL_DEFAULT
from .core.api_key_store import load_api_key_from_file, save_api_key
from .colors import COLORS
from .cost import estimate_drawing_set_cost, format_drawing_cost_prompt
from .html_report import build_html_report
from .pipeline import DrawingContext, extract_drawing_context
from .render import list_sheets

_PDF_FILETYPES = [("PDF drawings", "*.pdf"), ("All files", "*.*")]


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
        self.geometry("820x780")
        self.minsize(640, 560)
        self.configure(fg_color=COLORS["bg_dark"])

        self._pdfs: list[Path] = []
        self._ctx: DrawingContext | None = None
        self._busy = False
        self._last_log_msg: str | None = None
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
        # HTML report: off by default the key is NOT written into the file (the
        # Ask-AI panel prompts for one at runtime). On restores the old embedded
        # -key convenience — with a red warning in the report; don't share it.
        self._embed_key_var = BooleanVar(value=False)
        self._key_shown = False
        self._initial_key = self._load_api_key()
        self._has_key = bool(self._initial_key)
        # Tracks what's currently persisted so finishing an edit only rewrites
        # the store when the key actually changed (and never auto-persists an
        # unchanged, env-supplied key).
        self._persisted_key = self._initial_key

        self._build_ui()
        self._register_dnd()
        self._refresh_summary()

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
        outer.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            outer,
            text="Drawing Context Analyzer",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=16, pady=(16, 2))
        ctk.CTkLabel(
            outer,
            text=(
                "Drop mechanical / plumbing / fire-protection drawing PDFs "
                "(one or many; multi-sheet PDFs are split page-by-page). "
                "Each sheet is read by Claude Opus 4.8 and summarized to text."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"],
            wraplength=740,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        # API key — paste a key here when ANTHROPIC_API_KEY isn't set in the
        # environment. It applies the moment it's entered (no button), and is
        # saved (OS keyring, or a local key file) when editing finishes.
        key_row = ctk.CTkFrame(outer, fg_color="transparent")
        key_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            key_row, text="Anthropic API Key",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 8))
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

        # Drop zone
        self.drop_zone = ctk.CTkFrame(
            outer, fg_color=COLORS["bg_input"], corner_radius=8,
            border_width=2, border_color=COLORS["border"], height=90,
        )
        self.drop_zone.pack(fill="x", padx=16, pady=(0, 8))
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
        focus_row = ctk.CTkFrame(outer, fg_color="transparent")
        focus_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            focus_row, text="Per-run focus (optional)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w")
        ctk.CTkLabel(
            focus_row,
            text=(
                "Anything you particularly want pulled out this run — e.g. "
                "“the rooms, and what types of plumbing fixtures each has”. "
                "You always get the standard digest; a focus adds a Focus "
                "Report on top. Changing the focus re-analyzes sheets (cached "
                "results from other focuses don't apply)."
            ),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=COLORS["text_muted"],
            wraplength=740,
            justify="left",
        ).pack(anchor="w")
        self.focus_box = ctk.CTkTextbox(
            focus_row, height=56, fg_color=COLORS["bg_input"],
            border_color=COLORS["border"], border_width=2,
            text_color=COLORS["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=12), wrap="word",
        )
        self.focus_box.pack(fill="x", pady=(4, 0))
        # Keep the cost line live as the focus toggles between empty/non-empty
        # (a focus adds the focus-report pass to the estimate).
        self.focus_box.bind("<KeyRelease>", lambda _e: self._refresh_summary())

        # QC review options.
        qc_row = ctk.CTkFrame(outer, fg_color="transparent")
        qc_row.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            qc_row, text="QC review (optional)",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w")
        self._qc_markups_check = ctk.CTkCheckBox(
            qc_row, text="QC Markups — produce a marked-up PDF + findings CSV",
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
        self._reference_audit_check = ctk.CTkCheckBox(
            qc_row, text="Reference audit — flag stale/missing cross-references (free)",
            variable=self._reference_audit_var, command=self._refresh_summary,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_primary"],
        )
        self._reference_audit_check.pack(anchor="w", pady=(2, 0))
        self._on_qc_toggle()   # set the sub-toggle's initial enabled state

        # Summary + actions row
        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 8))
        self.summary_label = ctk.CTkLabel(
            row, text="", font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=COLORS["text_secondary"], justify="left",
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

        # Progress
        self.progress_label = ctk.CTkLabel(
            outer, text="", font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["text_muted"], anchor="w",
        )
        self.progress_label.pack(fill="x", padx=16, pady=(0, 4))

        # Activity log — live status + per-sheet diagnostics. The digest itself
        # is no longer shown here; it is written only to the saved Markdown file.
        self.log_box = ctk.CTkTextbox(
            outer, fg_color=COLORS["bg_input"], border_color=COLORS["border"],
            border_width=2, text_color=COLORS["text_secondary"],
            font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=16, pady=(4, 8))
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

        # HTML report option — embedding the API key makes the report's Ask-AI
        # work on a double-click with no key to paste, but writes the key into
        # the file (so it must not be shared). Off by default: the report prompts
        # for a key at first use and keeps it only in the browser tab.
        opt_row = ctk.CTkFrame(outer, fg_color="transparent")
        opt_row.pack(fill="x", padx=16, pady=(0, 4))
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
        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        self.open_log_btn = ctk.CTkButton(
            btn_row, text="Open Diagnostics Log", width=190, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"], command=self._on_open_log,
        )
        self.open_log_btn.pack(side="left")
        # Two save options, enabled together once a run produces text. The HTML
        # report is the recommended (primary/accent) output — a single
        # self-contained, navigable, searchable file — while the Markdown digest
        # stays available (secondary) for downstream/text use.
        self.html_btn = ctk.CTkButton(
            btn_row, text="Save HTML Report…", width=180, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["accent"], hover_color=COLORS["accent_hover"],
            command=self._on_save_html, state="disabled",
        )
        self.html_btn.pack(side="right")
        self.save_btn = ctk.CTkButton(
            btn_row, text="Save Markdown…", width=150, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            command=self._on_save, state="disabled",
        )
        self.save_btn.pack(side="right", padx=(0, 8))
        # QC outputs — enabled only when a run actually produced findings /
        # reviewed PDFs (see _on_done).
        self.csv_btn = ctk.CTkButton(
            btn_row, text="Save Findings CSV…", width=170, height=34,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            fg_color=COLORS["bg_input"], hover_color=COLORS["border"],
            border_width=1, border_color=COLORS["border"],
            text_color=COLORS["text_secondary"],
            command=self._on_save_csv, state="disabled",
        )
        self.csv_btn.pack(side="right", padx=(0, 8))
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
        """
        key = self._key_var.get().strip()
        if not key or key == self._persisted_key:
            return
        try:
            location = save_api_key(key)
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
            self._refresh_summary()

    def _on_clear(self) -> None:
        if self._busy:
            return
        self._pdfs = []
        self._ctx = None
        self._clear_log()
        self.save_btn.configure(state="disabled")
        self.html_btn.configure(state="disabled")
        self.reviewed_btn.configure(state="disabled")
        self.csv_btn.configure(state="disabled")
        self._set_progress_text("")
        self._refresh_summary()

    def _on_qc_toggle(self) -> None:
        """Enable the markup sub-toggles only when QC Markups is on."""
        on = self._qc_markups_var.get()
        for name in ("_qc_verified_only_check", "_ink_rejected_check"):
            check = getattr(self, name, None)
            if check is not None:
                check.configure(state="normal" if on else "disabled")
        self._refresh_summary()

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

    def _refresh_summary(self) -> None:
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
        est = estimate_drawing_set_cost(
            sheets, file_count=files, model=REVIEW_MODEL_DEFAULT, batch=True,
            focus=bool(self._current_focus()),
        )
        cost = (
            f"~${est.total_cost:,.2f} (est.)"
            if est.total_cost is not None
            else "cost n/a"
        )
        qc_note = "  ·  + QC verify (~$0.01–0.03/finding)" if self._qc_markups_var.get() else ""
        label.configure(
            text=(
                f"{files} file(s), {sheets} sheet(s)  ·  "
                f"~{est.image_tokens:,} image tokens  ·  {cost}{qc_note}"
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

        # Snapshot the focus + QC options with the file list, so mid-run edits
        # can't change what a running analysis was asked to do.
        focus = self._current_focus()
        qc_markups = self._qc_markups_var.get()
        markup_verified_only = self._qc_verified_only_var.get()
        ink_rejected = self._ink_rejected_var.get()
        reference_audit = self._reference_audit_var.get()

        # Cost-confirm gate — show the estimated (batch-rate) spend before the
        # batch is submitted. Nothing is sent until this is confirmed.
        refs = list_sheets(self._pdfs)
        estimate = estimate_drawing_set_cost(
            len(refs), file_count=len(self._pdfs), model=REVIEW_MODEL_DEFAULT,
            batch=True, focus=bool(focus),
        )
        prompt = format_drawing_cost_prompt(estimate)
        if qc_markups:
            prompt += (
                "\n\nQC verification adds ~$0.01–0.03 per finding "
                "(count unknown until digests complete)."
            )
        if not messagebox.askyesno("Confirm drawing analysis", prompt):
            return

        self._busy = True
        self._ctx = None
        self.analyze_btn.configure(state="disabled", text="Analyzing…")
        self.clear_btn.configure(state="disabled")
        self.save_btn.configure(state="disabled")
        self.html_btn.configure(state="disabled")
        self.reviewed_btn.configure(state="disabled")
        self.csv_btn.configure(state="disabled")
        self.focus_box.configure(state="disabled")
        self._clear_log()
        self._log(
            f"Starting analysis — {len(self._pdfs)} file(s), {len(refs)} sheet(s).",
            level="accent",
        )
        if focus:
            self._log(f"Per-run focus: {focus}", level="accent")
            self._log(
                "The standard digest is unchanged; a Focus Report will be added "
                "for this focus. Sheets cached without this focus are "
                "re-analyzed.",
                level="muted",
            )
        self._set_progress_text("Starting…", color=COLORS["text_secondary"])

        pdfs = list(self._pdfs)
        threading.Thread(
            target=self._worker,
            args=(pdfs, focus, qc_markups, markup_verified_only, reference_audit,
                  ink_rejected),
            daemon=True,
        ).start()

    def _worker(
        self,
        pdfs: list[Path],
        focus: str,
        qc_markups: bool = False,
        markup_verified_only: bool = False,
        reference_audit: bool = False,
        ink_rejected: bool = False,
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
                use_batch=True,
                focus=focus or None,
                reference_audit=reference_audit,
                qc_markups=qc_markups,
                markup_verified_only=markup_verified_only,
                ink_rejected=ink_rejected,
            )
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure
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

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._last_log_msg = None

    def _on_done(self, ctx: DrawingContext) -> None:
        self._busy = False
        self._ctx = ctx
        self.analyze_btn.configure(state="normal", text="Analyze Drawings")
        self.clear_btn.configure(state="normal")
        self.focus_box.configure(state="normal")
        has_text = bool(ctx.combined_text.strip())
        if has_text:
            self.save_btn.configure(state="normal")
            self.html_btn.configure(state="normal")
        # QC outputs — enable the save actions only when a run produced them.
        if getattr(ctx, "finding_count", 0):
            self.csv_btn.configure(state="normal")
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
        summary = (
            f"Done — {ok}/{ctx.sheet_count} sheet(s) analyzed{cached_note}"
            f"{failed_note} · input {ctx.total_input_tokens:,} tok, "
            f"output {ctx.total_output_tokens:,} tok"
        )
        self._log(summary, level="success" if not ctx.errors else "warning")
        self._set_progress_text(
            summary, color=COLORS["success"] if not ctx.errors else COLORS["warning"]
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
                f"{' · '.join(parts)}. Save the findings CSV"
                + (" or the reviewed PDF(s)" if reviewed else "")
                + " with the buttons below.",
                level="accent",
            )
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
                "searchable browser view, or “Save Markdown…” for the raw text.",
                level="accent",
            )
        else:
            self._log("No digest text was produced for this set.", level="error")

    def _on_error(self, message: str) -> None:
        self._busy = False
        self.analyze_btn.configure(state="normal", text="Analyze Drawings")
        self.clear_btn.configure(state="normal")
        self.focus_box.configure(state="normal")
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
        elif api_key:
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

    def _on_save_csv(self) -> None:
        """Write the findings CSV (Excel-friendly: UTF-8 BOM + CRLF)."""
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


def main() -> None:
    # Start the on-disk diagnostics trace before anything else so the whole
    # session (including startup) is captured. Best-effort: never fatal.
    diagnostics.configure_file_logging()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = DrawingAnalyzerApp()
    app.mainloop()
