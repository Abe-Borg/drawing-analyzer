"""Hermetic tests for the GUI's help-modal content and wiring.

The modal *content* lives in ``drawing_analyzer.help_content`` — pure data with
no ``tkinter`` / ``customtkinter`` import — so it is testable everywhere,
including CI without the ``python3-tk`` system package. The GUI *wiring*
(``gui.py``) can't be imported without ``customtkinter``, so it is checked
structurally via ``ast`` instead of import.
"""
from __future__ import annotations

import ast
import contextlib
import sys
import types
from pathlib import Path

import pytest

from drawing_analyzer.help_content import (
    HELP_DOCUMENTS,
    HelpBlock,
    HelpDocument,
    HelpSection,
    help_document,
    transport_hint,
)

_GUI_PATH = Path(__file__).resolve().parent.parent / "src" / "drawing_analyzer" / "gui.py"


# --------------------------------------------------------------------------
# Content structure
# --------------------------------------------------------------------------


def test_exactly_the_four_header_modals() -> None:
    """The three explainers plus About exist, in header order."""
    assert [d.key for d in HELP_DOCUMENTS] == [
        "how_to_use",
        "how_it_works",
        "why_trust_it",
        "about",
    ]
    assert [d.button_label for d in HELP_DOCUMENTS] == [
        "How to use",
        "How it works",
        "Why trust it?",
        "About",
    ]


def test_keys_are_unique() -> None:
    keys = [d.key for d in HELP_DOCUMENTS]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("doc", HELP_DOCUMENTS, ids=lambda d: d.key)
def test_document_is_well_formed(doc: HelpDocument) -> None:
    """Every doc has a title, intro, sections, and non-empty, valid blocks."""
    assert isinstance(doc, HelpDocument)
    assert doc.title.strip()
    assert doc.button_label.strip()
    assert doc.intro.strip()
    assert doc.sections, "a modal with no sections would render blank"
    for section in doc.sections:
        assert isinstance(section, HelpSection)
        assert section.heading.strip()
        assert section.blocks, f"section {section.heading!r} has no content"
        for block in section.blocks:
            assert isinstance(block, HelpBlock)
            assert block.kind in {"para", "bullet", "link"}
            assert block.text.strip()
            if block.kind == "link":
                assert block.href and block.href.startswith("https://")
            else:
                assert block.href is None


@pytest.mark.parametrize("doc", HELP_DOCUMENTS, ids=lambda d: d.key)
def test_documents_are_frozen(doc: HelpDocument) -> None:
    """Content is immutable data (frozen dataclasses)."""
    with pytest.raises(Exception):
        doc.title = "mutated"  # type: ignore[misc]


def test_help_document_lookup() -> None:
    assert help_document("why_trust_it").title == "Why you can trust the review"
    with pytest.raises(KeyError):
        help_document("does_not_exist")


def test_about_links_to_linkedin() -> None:
    """The About modal carries exactly one link block, pointing at the author."""
    links = [
        block
        for section in help_document("about").sections
        for block in section.blocks
        if block.kind == "link"
    ]
    assert [link.href for link in links] == ["https://www.linkedin.com/in/abrahamborg/"]


def test_about_states_the_version() -> None:
    """The About intro shows the real package version, not a stale copy."""
    from drawing_analyzer import __version__

    assert __version__ in help_document("about").intro


# --------------------------------------------------------------------------
# Faithfulness — the panels must describe what the pipeline actually does.
# --------------------------------------------------------------------------


def _all_text(doc: HelpDocument) -> str:
    parts = [doc.title, doc.intro]
    for section in doc.sections:
        parts.append(section.heading)
        parts.extend(block.text for block in doc_blocks(section))
    return "\n".join(parts)


def doc_blocks(section: HelpSection):
    return section.blocks


@pytest.mark.parametrize(
    "key, needles",
    [
        # How to use — the operator's actual workflow surfaces.
        ("how_to_use", ["API key", "Analyze", "focus", "QC Markups", "Export All", "HTML Report"]),
        # How it works — the real pipeline vocabulary.
        ("how_it_works", ["sheet", "text layer", "tiles", "Opus 4.8", "Batch", "synthesis"]),
        # Why trust it — the trust mechanisms that exist in the code.
        (
            "why_trust_it",
            [
                "never calculates",
                "DETERMINISTIC",
                "UNANCHORED",
                "verif",
                "INCOMPLETE",
                "index",
            ],
        ),
        # About — the licensing story must match LICENSE and the README.
        (
            "about",
            [
                "AGPL",
                "redistribute",
                "NO WARRANTY",
                "Copyright © 2026 Abraham Borg",
                "PyMuPDF",
                "linkedin.com/in/abrahamborg",
            ],
        ),
    ],
)
def test_content_is_faithful(key: str, needles: list[str]) -> None:
    text = _all_text(help_document(key)).lower()
    for needle in needles:
        assert needle.lower() in text, f"{key!r} modal should mention {needle!r}"


# --------------------------------------------------------------------------
# Cost & time guidance — the sprinkled, single-sourced expectation strings.
# --------------------------------------------------------------------------


def test_transport_hint_batch_explains_the_queue_and_price() -> None:
    """The default (batch) hint teaches the shared-queue trade-off + cheap price."""
    hint = transport_hint(realtime=False)
    low = hint.lower()
    assert "queue" in low
    assert "overnight" in low or "8+ hours" in hint
    assert "0.50" in hint  # the batch per-sheet rule of thumb


def test_transport_hint_realtime_gives_time_and_price() -> None:
    """The real-time hint states the per-sheet time and (higher) price, no queue."""
    hint = transport_hint(realtime=True)
    assert "4–6 minutes" in hint
    assert "$3–5" in hint
    assert "no queue" in hint.lower()  # real-time's whole point is skipping it


def test_how_it_works_covers_the_cost_time_story() -> None:
    """The 'Batch vs real-time' panel carries the concrete queue / time / price story."""
    text = _all_text(help_document("how_it_works")).lower()
    for needle in ("queue", "overnight", "4–6 minutes", "$3–5", "0.50"):
        assert needle.lower() in text, f"how_it_works should mention {needle!r}"


# --------------------------------------------------------------------------
# GUI wiring — checked structurally (gui.py can't import without customtkinter).
# --------------------------------------------------------------------------


def _gui_module_ast() -> ast.Module:
    return ast.parse(_GUI_PATH.read_text(encoding="utf-8"))


def _app_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DrawingAnalyzerApp":
            return node
    raise AssertionError("DrawingAnalyzerApp class not found in gui.py")


def test_gui_imports_help_content() -> None:
    tree = _gui_module_ast()
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "help_content"
        for alias in node.names
    }
    assert {"HELP_DOCUMENTS", "HelpDocument", "transport_hint"} <= imported


def test_gui_wires_the_transport_hint() -> None:
    """The Processing checkbox drives a mode-aware hint via _on_transport_toggle."""
    cls = _app_class(_gui_module_ast())
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert "_on_transport_toggle" in methods
    source = _GUI_PATH.read_text(encoding="utf-8")
    assert "command=self._on_transport_toggle" in source
    assert "self._transport_hint" in source


def test_gui_defines_help_modal_methods() -> None:
    cls = _app_class(_gui_module_ast())
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert {
        "_build_help_buttons",
        "_open_help_modal",
        "_render_help_body",
        "_grab_help_modal",
        "_close_help_modal",
    } <= methods


def test_build_ui_installs_help_buttons() -> None:
    """The header wiring calls _build_help_buttons, so the buttons are shown."""
    source = _GUI_PATH.read_text(encoding="utf-8")
    assert "self._build_help_buttons(header)" in source


# --------------------------------------------------------------------------
# Rendering — exercise the real _render_help_body under a fake toolkit.
#
# gui.py needs tkinter/customtkinter, which aren't installed in the hermetic
# environment; a minimal fake toolkit lets us drive the real rendering walk
# (heading + paragraph + bullet branches) without a display, then restores
# sys.modules so nothing leaks into other tests.
# --------------------------------------------------------------------------


class _FakeWidget:
    def __init__(self, master=None, **kw):
        self.master = master
        self.kw = kw
        self.bound: list[str] = []
        _FakeWidget.created.append((type(self).__name__, kw))

    def pack(self, *a, **k):
        return self

    def configure(self, *a, **k):
        return self

    def bind(self, sequence=None, *a, **k):
        self.bound.append(sequence)
        return self

    def winfo_exists(self):
        return True


@contextlib.contextmanager
def _fake_gui_toolkit():
    _FakeWidget.created = []

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

    ctk = types.ModuleType("customtkinter")
    for _name in (
        "CTk",
        "CTkToplevel",
        "CTkFrame",
        "CTkScrollableFrame",
        "CTkLabel",
        "CTkButton",
        "CTkEntry",
        "CTkTextbox",
        "CTkCheckBox",
    ):
        setattr(ctk, _name, type(_name, (_FakeWidget,), {}))
    ctk.CTkFont = lambda **kw: kw
    ctk.set_appearance_mode = ctk.set_default_color_theme = lambda *a, **k: None

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
        import drawing_analyzer.gui as gui_module

        yield gui_module, ctk
    finally:
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


@pytest.mark.parametrize("doc", HELP_DOCUMENTS, ids=lambda d: d.key)
def test_render_help_body_visits_every_block(doc: HelpDocument) -> None:
    with _fake_gui_toolkit() as (gui_module, ctk):
        body = ctk.CTkScrollableFrame()
        _FakeWidget.created = []
        gui_module.DrawingAnalyzerApp._render_help_body(body, doc)

    labels = [kw.get("text", "") for name, kw in _FakeWidget.created if name == "CTkLabel"]
    for section in doc.sections:
        assert section.heading in labels
        for block in section.blocks:
            assert block.text in labels

    bullet_marks = sum(1 for text in labels if text == "•")
    expected_bullets = sum(
        1 for s in doc.sections for b in s.blocks if b.kind == "bullet"
    )
    assert bullet_marks == expected_bullets
