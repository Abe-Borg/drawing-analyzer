"""Hermetic tests for the GUI's help-modal content and wiring.

The modal *content* lives in ``drawing_analyzer.help_content`` — pure data with
no ``tkinter`` / ``customtkinter`` import — so it is testable everywhere,
including CI without the ``python3-tk`` system package. The GUI side
(``gui.py``) needs ``customtkinter``, so it is imported under a minimal fake
toolkit and its real rendering code is driven directly.
"""
from __future__ import annotations

import contextlib
import sys
import types

import pytest

from drawing_analyzer.help_content import (
    GET_API_KEY,
    HELP_DOCUMENTS,
    PRE_MAX_WIDTH,
    RUNTIME_TRANSPARENCY,
    STANDALONE_DOCUMENTS,
    HelpBlock,
    HelpDocument,
    HelpSection,
    help_document,
    processing_transports,
    transport_hint,
)

_ALL_DOCUMENTS = (*HELP_DOCUMENTS, *STANDALONE_DOCUMENTS)

_BLOCK_KINDS = {"para", "bullet", "link", "pre", "modal"}


def _assert_well_formed(doc: HelpDocument) -> None:
    """The structural contract every rendered document must satisfy."""
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
            assert block.kind in _BLOCK_KINDS
            assert block.text.strip()
            if block.kind == "link":
                assert block.href and block.href.startswith("https://")
                assert block.doc_key is None
            elif block.kind == "modal":
                # Every hand-off must resolve, or the link is a dead end.
                assert block.doc_key, "a modal block must name a target document"
                assert help_document(block.doc_key) is not None
                assert block.href is None
            else:
                assert block.href is None
                assert block.doc_key is None


def _all_text(doc: HelpDocument) -> str:
    parts = [doc.title, doc.intro]
    for section in doc.sections:
        parts.append(section.heading)
        parts.extend(block.text for block in doc_blocks(section))
    return "\n".join(parts)


def doc_blocks(section: HelpSection):
    return section.blocks


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


@pytest.mark.parametrize("doc", _ALL_DOCUMENTS, ids=lambda d: d.key)
def test_document_is_well_formed(doc: HelpDocument) -> None:
    """Every doc has a title, intro, sections, and non-empty, valid blocks."""
    _assert_well_formed(doc)


@pytest.mark.parametrize("doc", _ALL_DOCUMENTS, ids=lambda d: d.key)
def test_pre_blocks_fit_the_panel(doc: HelpDocument) -> None:
    """``pre`` blocks are never re-wrapped, so an over-wide line is clipped."""
    for section in doc.sections:
        for block in section.blocks:
            if block.kind != "pre":
                continue
            for line in block.text.splitlines():
                assert len(line) <= PRE_MAX_WIDTH, (
                    f"{doc.key}/{section.heading}: pre line is {len(line)} chars "
                    f"(max {PRE_MAX_WIDTH}): {line!r}"
                )


def test_help_document_lookup() -> None:
    assert help_document("why_trust_it").title == "Why you can trust the review"
    with pytest.raises(KeyError):
        help_document("does_not_exist")


def test_about_links_to_the_author_source_and_licence() -> None:
    """About points at the author, and at the two things that back its claims.

    The AGPL story is only checkable if the source and the licence text are
    reachable from the panel that makes the claim, so both links are required
    alongside the author credit.
    """
    hrefs = [
        block.href
        for section in help_document("about").sections
        for block in section.blocks
        if block.kind == "link"
    ]
    assert "https://www.linkedin.com/in/abrahamborg/" in hrefs
    assert "https://github.com/abe-borg/drawing-analyzer" in hrefs
    assert "https://www.gnu.org/licenses/agpl-3.0.html" in hrefs


def test_about_states_the_version() -> None:
    """The About intro shows the real package version, not a stale copy."""
    from drawing_analyzer import __version__

    assert __version__ in help_document("about").intro


# --------------------------------------------------------------------------
# Get-an-API-key guide — a standalone modal reached from the key field, not
# one of the four header buttons.
# --------------------------------------------------------------------------


def test_get_api_key_is_not_a_header_modal() -> None:
    """The guide is standalone — not in the header row, but reachable by key."""
    assert GET_API_KEY.key not in {d.key for d in HELP_DOCUMENTS}
    assert help_document("get_api_key") is GET_API_KEY


def test_get_api_key_links_to_the_console() -> None:
    """The guide carries a link to the console's key-creation page."""
    links = [
        block
        for section in GET_API_KEY.sections
        for block in section.blocks
        if block.kind == "link"
    ]
    assert links, "the guide must offer a clickable link to the console"
    assert all(link.href.startswith("https://console.anthropic.com") for link in links)


# --------------------------------------------------------------------------
# Runtime transparency — the "I'm not convinced" deep dive reached from the
# foot of "Why trust it?".
# --------------------------------------------------------------------------


def test_runtime_transparency_is_standalone_and_reachable() -> None:
    """Not a header button, but resolvable by key and registered as standalone."""
    assert RUNTIME_TRANSPARENCY.key not in {d.key for d in HELP_DOCUMENTS}
    assert RUNTIME_TRANSPARENCY in STANDALONE_DOCUMENTS
    assert help_document("runtime_transparency") is RUNTIME_TRANSPARENCY


def test_why_trust_it_links_to_the_runtime_briefing() -> None:
    """The 'I'm not convinced' hand-off exists, is last, and targets the briefing."""
    doc = help_document("why_trust_it")
    modal_blocks = [
        block
        for section in doc.sections
        for block in section.blocks
        if block.kind == "modal"
    ]
    assert len(modal_blocks) == 1
    assert modal_blocks[0].doc_key == "runtime_transparency"
    assert "not convinced" in modal_blocks[0].text.lower()
    # It sits at the very bottom of the panel, as the closing offer.
    assert doc.sections[-1].blocks[-1] is modal_blocks[0]


def test_runtime_transparency_discloses_the_full_outbound_inventory() -> None:
    """The 'what leaves' list must not understate what actually leaves.

    Two things are easy to omit and were: the source PDF's *basename* rides
    every request (``SheetRef.display_label`` is spliced into the digest and
    critique framing, and the batch path names its uploads from it), and the
    text layer is capped at ``render.SHEET_TEXT_MAX_CHARS`` with a
    ``[TRUNCATED]`` marker rather than sent whole. An inventory that claims to
    be exact has to say both.
    """
    from drawing_analyzer.render import SHEET_TEXT_MAX_CHARS

    text = _all_text(RUNTIME_TRANSPARENCY)
    assert f"{SHEET_TEXT_MAX_CHARS:,}" in text
    assert "[TRUNCATED]" in text
    assert "file name" in text.lower()
    # The precise distinction: the name travels, the path does not.
    assert "never the folder" in text.lower()


# --------------------------------------------------------------------------
# Processing modes — transport selection and the hint each mode shows.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "expected", "hint_needles"),
    [
        ("Economy", (True, True), ("lowest",)),
        ("Hybrid", (False, True), ("initial", "critique", "queue")),
        ("Fast", (False, False), ("fastest",)),
    ],
)
def test_processing_modes_resolve_digest_and_critique_transport(
    mode, expected, hint_needles
) -> None:
    assert processing_transports(mode) == expected
    # The hint must describe the branch this mode actually takes.
    hint = transport_hint(mode).lower()
    for needle in hint_needles:
        assert needle in hint


# --------------------------------------------------------------------------
# GUI widgets — the real gui.py driven under the fake toolkit below.
# --------------------------------------------------------------------------


def test_collapsible_section_expand_mode_fills_and_survives_collapse() -> None:
    """expand=True fills vertically; the container keeps expand while collapsed.

    Drives the real CollapsibleSection under the fake toolkit so the toggle
    logic — not just its source — is exercised.
    """
    with _fake_gui_toolkit() as (gui_module, ctk):
        sec = gui_module.CollapsibleSection(
            ctk.CTkFrame(), "Activity log", expand=True
        )
        # Container claims vertical slack, and so does the body while expanded.
        assert sec.container.pack_kwargs.get("fill") == "both"
        assert sec.container.pack_kwargs.get("expand") is True
        assert sec.expanded is True
        assert sec.body.mapped is True
        assert sec.body.pack_kwargs.get("fill") == "both"
        assert sec.body.pack_kwargs.get("expand") is True

        # Collapsing hides the body but leaves the container packed with
        # expand=True — so the header stays anchored and siblings never shift.
        sec.toggle()
        assert sec.expanded is False
        assert sec.body.mapped is False
        assert sec.container.pack_kwargs.get("expand") is True

        # Re-expanding re-packs the body with the fill mode it was built for.
        sec.toggle()
        assert sec.expanded is True
        assert sec.body.mapped is True
        assert sec.body.pack_kwargs.get("expand") is True


def test_collapsible_section_default_mode_is_unchanged() -> None:
    """Without expand, sections still pack fill='x' (regression guard)."""
    with _fake_gui_toolkit() as (gui_module, ctk):
        sec = gui_module.CollapsibleSection(
            ctk.CTkFrame(), "QC review", expanded=False
        )
        assert sec.expanded is False
        assert sec.body.mapped is False  # starts collapsed
        assert sec.container.pack_kwargs.get("fill") == "x"
        assert sec.container.pack_kwargs.get("expand") in (None, False)
        sec.toggle()
        assert sec.expanded is True
        assert sec.body.mapped is True
        assert sec.body.pack_kwargs.get("fill") == "x"
        assert sec.body.pack_kwargs.get("expand") in (None, False)


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
        # Bound callbacks by sequence, so a test can actually *fire* a click
        # (used to drive the help modals' link / modal hand-off blocks).
        self.handlers: dict = {}
        # pack geometry state, so tests can assert how a widget was packed and
        # whether it is currently mapped (used by the CollapsibleSection tests).
        self.pack_kwargs: dict = {}
        self.mapped = False
        _FakeWidget.created.append((type(self).__name__, kw))
        _FakeWidget.instances.append(self)

    def pack(self, *a, **k):
        self.pack_kwargs = k
        self.mapped = True
        return self

    def pack_forget(self, *a, **k):
        self.mapped = False
        return self

    def configure(self, *a, **k):
        return self

    def bind(self, sequence=None, func=None, *a, **k):
        self.bound.append(sequence)
        if func is not None:
            self.handlers[sequence] = func
        return self

    def fire(self, sequence, event=None):
        """Invoke a bound handler the way tkinter would on a real click."""
        return self.handlers[sequence](event)

    def winfo_exists(self):
        return True


@contextlib.contextmanager
def _fake_gui_toolkit():
    _FakeWidget.created = []
    _FakeWidget.instances = []

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


@pytest.mark.parametrize("doc", _ALL_DOCUMENTS, ids=lambda d: d.key)
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


def test_render_help_body_keeps_pre_blocks_unwrapped() -> None:
    """A diagram must render monospace and with NO wraplength, or it shears."""
    with _fake_gui_toolkit() as (gui_module, ctk):
        body = ctk.CTkScrollableFrame()
        _FakeWidget.created = []
        gui_module.DrawingAnalyzerApp._render_help_body(body, RUNTIME_TRANSPARENCY)

    pre_texts = {
        b.text for s in RUNTIME_TRANSPARENCY.sections for b in s.blocks if b.kind == "pre"
    }
    assert len(pre_texts) >= 3, "the briefing's visuals are part of the deliverable"
    rendered = [
        kw for name, kw in _FakeWidget.created
        if name == "CTkLabel" and kw.get("text") in pre_texts
    ]
    assert len(rendered) == len(pre_texts)
    for kw in rendered:
        assert kw.get("wraplength") is None, "a wrapped diagram is a broken diagram"
        assert kw.get("font", {}).get("family") == "Consolas"


def test_render_help_body_wires_the_modal_hand_off() -> None:
    """Clicking 'I'm not convinced' invokes the callback with the target key."""
    opened: list[str] = []
    with _fake_gui_toolkit() as (gui_module, ctk):
        body = ctk.CTkScrollableFrame()
        _FakeWidget.created = []
        gui_module.DrawingAnalyzerApp._render_help_body(
            body, help_document("why_trust_it"), on_modal_link=opened.append
        )
        # The modal block is the only bound Button-1 label that isn't a web link.
        link_texts = {
            b.text
            for s in help_document("why_trust_it").sections
            for b in s.blocks
            if b.kind == "modal"
        }
        widgets = [
            w for w in _FakeWidget.instances
            if getattr(w, "kw", {}).get("text") in link_texts
        ]
        assert len(widgets) == 1
        assert "<Button-1>" in widgets[0].bound
        widgets[0].fire("<Button-1>")

    assert opened == ["runtime_transparency"]


def test_render_help_body_modal_block_is_inert_without_a_callback() -> None:
    """The content-only path still renders the label, just not clickable."""
    with _fake_gui_toolkit() as (gui_module, ctk):
        body = ctk.CTkScrollableFrame()
        _FakeWidget.created = []
        gui_module.DrawingAnalyzerApp._render_help_body(
            body, help_document("why_trust_it")
        )
        modal_text = help_document("why_trust_it").sections[-1].blocks[-1].text
        widgets = [w for w in _FakeWidget.instances if w.kw.get("text") == modal_text]
        assert len(widgets) == 1
        assert widgets[0].bound == []
