"""Static help content for the GUI's header modals.

The GUI header carries four buttons — **How to use**, **How it works**,
**Why trust it?**, and **About** — each opening a scrollable modal. The
*content* of those modals lives here as plain data (:class:`HelpDocument`
trees) with **no GUI / tkinter import**, so it is importable and unit-testable
in the hermetic suite even on machines without ``tkinter`` / ``customtkinter``
installed. ``gui.py`` owns only the thin CustomTkinter rendering (see
``_open_help_modal``).

Keep the prose faithful to the README and ``CLAUDE.md``: these panels are the
in-app version of that documentation, so a claim here (verification, gating,
artifact-backed coverage, "the model never calculates", the licensing story)
must match what the pipeline actually does and what LICENSE actually says.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import __version__


@dataclass(frozen=True)
class HelpBlock:
    """One rendered block within a section: a paragraph, bullet, or link.

    ``href`` is set only on ``kind="link"`` blocks; the GUI renders those as a
    clickable label that opens the URL in the default browser.
    """

    kind: str  # "para" | "bullet" | "link"
    text: str
    href: str | None = None


@dataclass(frozen=True)
class HelpSection:
    """A titled group of blocks."""

    heading: str
    blocks: tuple[HelpBlock, ...]


@dataclass(frozen=True)
class HelpDocument:
    """One modal's worth of content."""

    key: str           # stable id used to de-duplicate open windows
    button_label: str  # header button text
    title: str         # modal window + heading text
    intro: str         # one-line summary under the title
    sections: tuple[HelpSection, ...]


# --------------------------------------------------------------------------
# Cost & time expectations (shared, single-sourced)
#
# The live estimator (``cost.py``) owns the precise dollar figure for a given
# set; these are the deliberately-rough "what to expect" rules of thumb for a
# full QC review. They are kept in ONE place and sprinkled across the GUI — the
# Processing checkbox hint, the cost-confirm dialog, and the "Batch vs
# real-time" help panel — so an operator builds the cost/time picture
# progressively rather than reading one dense paragraph. Change a number here
# and every surface agrees.
# --------------------------------------------------------------------------

# Cost scales with the depth of the review, so each figure names its workload:
# batch is exactly half the real-time rate for the *same* run, and the cheap
# ~$0.50/sheet number is a plain digest — not a full QC review, which costs
# correspondingly more (about half of the real-time $3–5).
REALTIME_COST_PER_SHEET = "roughly $3–5 per sheet for a full QC review"
REALTIME_TIME_PER_SHEET = "about 4–6 minutes per sheet"
BATCH_COST_PER_SHEET = "around $0.50 per sheet"


def transport_hint(realtime: bool) -> str:
    """One-line, mode-aware hint shown under the Processing checkbox.

    ``realtime`` is the checkbox state (True = real-time, False = batch). The
    two branches trade the same money-for-speed story from opposite sides.
    """
    if realtime:
        return (
            f"No queue — each sheet is analyzed right away ({REALTIME_TIME_PER_SHEET}), "
            f"at {REALTIME_COST_PER_SHEET}. Choose this when you need results now."
        )
    return (
        "Sheets wait in Anthropic's shared queue and come back when they reach "
        "the front — often within a few hours, sometimes overnight (8+ hours). "
        f"About half the real-time rate, and a plain digest runs {BATCH_COST_PER_SHEET}; "
        "ideal for an overnight run when you're not in a rush."
    )


def _para(text: str) -> HelpBlock:
    return HelpBlock(kind="para", text=text)


def _bullet(text: str) -> HelpBlock:
    return HelpBlock(kind="bullet", text=text)


def _link(text: str, href: str) -> HelpBlock:
    return HelpBlock(kind="link", text=text, href=href)


def _section(heading: str, *blocks: HelpBlock) -> HelpSection:
    return HelpSection(heading=heading, blocks=tuple(blocks))


# --------------------------------------------------------------------------
# How to use
# --------------------------------------------------------------------------

_HOW_TO_USE = HelpDocument(
    key="how_to_use",
    button_label="How to use",
    title="How to use Drawing Analyzer",
    intro="From a stack of drawing PDFs to a navigable, marked-up review in a few clicks.",
    sections=(
        _section(
            "1 · Set your API key",
            _para(
                "The analyzer reads your drawings with the Anthropic API, so it "
                "needs a key. Set ANTHROPIC_API_KEY in your environment, or paste "
                "a key into the Anthropic API Key field at the top of the window."
            ),
            _bullet("A pasted key takes effect immediately — there is no extra button to press."),
            _bullet(
                "It is remembered for next launch in your OS keyring (or, only with "
                "your explicit consent, a local file). An environment variable always "
                "wins over a saved key."
            ),
        ),
        _section(
            "2 · Add drawing PDFs",
            _para(
                "Drop construction-drawing PDFs onto the drop zone, or click Browse…. "
                "Multi-page PDFs are split automatically — every page becomes one sheet, "
                "and the whole set is analyzed together."
            ),
        ),
        _section(
            "3 · (Optional) Add a per-run focus",
            _para(
                "Type anything you especially want pulled out this run — e.g. “the "
                "rooms, and what plumbing fixtures each has.” You always get the "
                "standard digest; a focus adds a dedicated Focus Report on top."
            ),
            _bullet(
                "Changing the focus re-analyzes sheets (cached results from a different "
                "focus don't apply)."
            ),
        ),
        _section(
            "4 · (Optional) Attach project specifications",
            _para(
                "Upload the real, complete, current project spec documents "
                "(.pdf / .docx / .txt / .md) so QC can check the drawings against them. "
                "Any conflict folds into an ordinary finding — there is no separate spec "
                "report."
            ),
        ),
        _section(
            "5 · Choose a QC level",
            _para("Two checkboxes sit beside the focus:"),
            _bullet(
                "QC Markups — the full exhaustive engineering review: synthesis, two "
                "critique reads per sheet, cross-sheet QC, the deterministic auditors, "
                "anchoring, verification, citation checks, and marked-up PDFs. It costs "
                "more than a plain digest; the cost line tells you how much before you commit."
            ),
            _bullet(
                "Deterministic audit only — a free, zero-API pass that adds the whole "
                "deterministic auditor battery. (It is already included inside QC Markups.)"
            ),
            _bullet(
                "Two sub-toggles refine the markups: Verified & deterministic only "
                "(suppress unverified ink) and Include rejected (grey)."
            ),
            _para(
                "Even with neither box checked a run is not throwaway: it still keeps each "
                "sheet's extracted text and the digest's parsed findings, anchors them "
                "offline for free, shows them in the report, and exports them."
            ),
        ),
        _section(
            "6 · Analyze & confirm the cost",
            _para(
                "Press Analyze Drawings. A dialog shows the estimated cost before any paid "
                "call is made — confirm to proceed. Progress and per-sheet diagnostics "
                "stream into the activity log as the run works."
            ),
        ),
        _section(
            "7 · Save your results",
            _bullet(
                "Save HTML Report… — one portable, self-contained file with a table of "
                "contents, full-text search, category filters, and a built-in Ask-AI "
                "assistant grounded in the report's own text."
            ),
            _bullet("Save Reviewed PDF(s)… — the marked-up drawings (lights up after a QC run)."),
            _bullet(
                "Export All… — the complete review folder in one action (report, Markdown, "
                "findings.json / findings.csv, per-sheet text, evidence, reviewed PDFs, and "
                "the run.log / run_manifest.json record) — written even for a failed run."
            ),
            _bullet("Open Diagnostics Log — the detailed request-level trace, available any time."),
        ),
    ),
)


# --------------------------------------------------------------------------
# How it works
# --------------------------------------------------------------------------

_HOW_IT_WORKS = HelpDocument(
    key="how_it_works",
    button_label="How it works",
    title="How Drawing Analyzer works",
    intro="A vision pipeline: every sheet is read whole, grounded in its own text layer.",
    sections=(
        _section(
            "The pipeline",
            _para(
                "PDFs → list sheets → render (overview + 6×6 tiles) and extract "
                "the vector text layer → per-sheet vision digest → optional "
                "cross-sheet synthesis → optional focus report → combined Markdown "
                "→ optional QC (auditors + anchor → verify → markup)."
            ),
            _para(
                "Each PDF page is one sheet. Every sheet is read whole — the overview plus "
                "all 36 tiles — so the model sees the entire drawing at once, never a "
                "cropped fragment."
            ),
        ),
        _section(
            "Text-layer grounding",
            _para(
                "Before rasterizing, each sheet's vector text layer is lifted losslessly "
                "and spliced into the prompt verbatim, ahead of the images, as the source "
                "of truth for exact strings — tags, schedule values, note numbers, sheet "
                "references. Vector text can't misread a digit the way OCR of a "
                "low-resolution embedded raster can."
            ),
        ),
        _section(
            "Render & digest",
            _para(
                "Each sheet is rendered to an overview image plus a 6×6 grid of "
                "high-resolution tiles and sent, together with its text layer, to Claude "
                "Opus 4.8 in a single request. The model returns a structured Markdown "
                "digest plus a machine-readable findings block."
            ),
            _bullet(
                "Ordinary vector sheets render tiles at 1560 px; a scanned or pasted-raster "
                "sheet (empty text layer) renders at 1992 px, because there the pixels are "
                "the only information channel."
            ),
        ),
        _section(
            "Batch vs real-time",
            _para(
                "Every sheet is a paid vision call, so how those calls are sent is the "
                "single biggest lever on what a run costs and how long it takes. The "
                "output is byte-identical either way — you are only trading money for "
                "speed — and cached sheets are free in both modes."
            ),
            _bullet(
                "Batch mode (the GUI default) submits every uncached sheet through the "
                "Message Batches API. Your sheets join Anthropic's shared queue and are "
                "processed once they reach the front — so a run can finish in a few "
                "minutes, a few hours, or run overnight (8+ hours) depending on how busy "
                "that queue is. In exchange it costs about half the real-time rate — a "
                f"plain digest runs {BATCH_COST_PER_SHEET}, and a full QC review costs "
                "correspondingly more. Ideal for an overnight run when you're not in a rush."
            ),
            _bullet(
                "Real-time mode skips the queue: every sheet is analyzed immediately and "
                f"concurrently ({REALTIME_TIME_PER_SHEET}) — {REALTIME_COST_PER_SHEET}. "
                "Roughly double the batch rate, and running the exhaustive stack "
                "real-time is the most expensive configuration — but you get results now. "
                "Choose it when you're in a rush."
            ),
        ),
        _section(
            "Caching",
            _para(
                "Caching is content-keyed per sheet, so re-running a set after editing one "
                "sheet only re-pays for the changed sheet. A two-level key recognizes an "
                "unchanged sheet before rasterizing, so a fully cached re-run skips "
                "rendering entirely."
            ),
        ),
        _section(
            "Cross-sheet synthesis & focus",
            _para(
                "An optional synthesis pass reconciles tags and conflicts across the whole "
                "set. An optional per-run focus adds a dedicated Focus Report answering "
                "your specific question, on top of the standard digest."
            ),
        ),
        _section(
            "The QC stack",
            _para("When QC Markups is on, a layered review runs on top of the digests:"),
            _bullet(
                "Deterministic auditors — zero-API checks over the text layers (references, "
                "arithmetic, naming, title-block, sheet-index)."
            ),
            _bullet(
                "Critique — a second full-coverage vision read, run twice and merged for "
                "self-consistency."
            ),
            _bullet("Cross-sheet QC — a text-only hunt for conflicts that span sheets."),
            _bullet(
                "Anchor → verify → investigate — each finding's quote is mapped to a "
                "rectangle, then re-checked against a high-DPI crop; stubborn cases get an "
                "agentic evidence-gathering loop."
            ),
            _bullet("Citation check — a web search for each unique cited code section."),
            _bullet(
                "Markup — findings are clouded onto reviewed PDFs, then the file is reopened "
                "and reconciled to prove the ink actually landed."
            ),
            _para(
                "Every channel feeds one per-run findings ledger; de-duplication is "
                "conservative and lossless (a tile overlap is never enough on its own)."
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# Why trust it?
# --------------------------------------------------------------------------

_WHY_TRUST_IT = HelpDocument(
    key="why_trust_it",
    button_label="Why trust it?",
    title="Why you can trust the review",
    intro="The whole design assumes the model can be wrong — and checks its work.",
    sections=(
        _section(
            "Grounded in the drawing's own text",
            _para(
                "Exact strings come from each sheet's vector text layer, sent verbatim — "
                "not from OCR. A tag or schedule value the model reports is grounded in "
                "text lifted losslessly from the PDF, so it can't quietly misread a digit."
            ),
        ),
        _section(
            "The model never calculates",
            _para(
                "Models transcribe numbers; the host does the math with exact Decimal "
                "arithmetic — never the model's own arithmetic, never eval. A column that "
                "doesn't total or a density×area that doesn't match is caught by code, "
                "not by opinion."
            ),
        ),
        _section(
            "Deterministic auditors",
            _para(
                "A battery of zero-API auditors runs over the text layers, catching the "
                "class of defect a vision model is unreliable at but code is exact at: a "
                "stale cross-reference, a column that doesn't add up, a tag spelled two "
                "ways, a drifted title-block field, an index that disagrees with the set. "
                "Their findings are marked DETERMINISTIC — trusted without a model re-check."
            ),
        ),
        _section(
            "Hallucinations are flagged, never hidden",
            _para(
                "Every finding's quote is anchored back to a rectangle on its page. A "
                "non-empty quote that matches nothing anywhere is the hallucination signal: "
                "it is labeled [UNANCHORED], flagged loudly as a margin callout, and never "
                "drawn as if it had a real location."
            ),
        ),
        _section(
            "Findings are verified against the pixels",
            _para(
                "Before a finding is clouded onto an issued drawing, the verification pass "
                "renders a high-DPI crop around it and asks a focused model call whether it "
                "actually holds in that crop. Every crop is saved and hashed before it is "
                "sent, so no verdict rests on an image absent from the trail."
            ),
            _bullet(
                "CONFIRMED → VERIFIED (solid cloud). CONTRADICTED → REJECTED "
                "(pulled from the ink, but kept in an index row). NOT_VISIBLE → "
                "UNCERTAIN (drawn dashed with an [UNVERIFIED] prefix)."
            ),
            _bullet(
                "A budget cap or a garbled reply can never mark a finding wrong — it stays "
                "UNCERTAIN, never REJECTED."
            ),
        ),
        _section(
            "Nothing is silently dropped",
            _para(
                "On an exhaustive run every ledger entry gets ink except the ones the "
                "verifier proved wrong — and even those get a reconciled index row with "
                "page links. A finding is either on the paper or accounted for in the "
                "index; it is never simply invisible."
            ),
        ),
        _section(
            "Coverage is proven, not claimed",
            _para(
                "After each reviewed PDF is saved it is reopened and reconciled against the "
                "plan: every cloud, callout, and index row is stamped with a private id, "
                "and a placement counts only when its stamp is found again in the saved "
                "file. If any planned markup is missing, the run is marked INCOMPLETE — the "
                "PDF is renamed, the report shows a red banner, and it is never presented "
                "as a clean success."
            ),
            _bullet(
                "Stamps carry a per-run id, so pre-existing annotations and markups from an "
                "earlier review run can neither satisfy nor break the accounting."
            ),
        ),
        _section(
            "One honest, guarded status",
            _para(
                "An exhaustive run carries a single rolled-up QC status — NOT_REQUESTED, "
                "COMPLETE, PARTIAL, or FAILED. A failed reconciliation, an unchecked cited "
                "claim, a missing verification crop, or a source that changed mid-run holds "
                "the run below COMPLETE. A clean review is a guarded claim, not an assumption."
            ),
        ),
        _section(
            "Model output is treated as hostile",
            _para(
                "Everything the model returns is treated as untrusted data that can never "
                "execute — in the reviewed PDF, the exports, and the HTML report's Ask-AI "
                "assistant. See SECURITY.md for the full trust boundary."
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# About
# --------------------------------------------------------------------------

_ABOUT = HelpDocument(
    key="about",
    button_label="About",
    title="About Drawing Analyzer",
    intro=f"Version {__version__} — free software under the GNU AGPL.",
    sections=(
        _section(
            "License",
            _para(
                "Drawing Analyzer is free software, distributed under the GNU "
                "Affero General Public License, version 3 or later "
                "(AGPL-3.0-or-later). Anyone may use, study, modify, and "
                "redistribute it — commercially or otherwise — provided derived "
                "versions stay under the same license and their source is made "
                "available, including when the software is offered as a network "
                "service."
            ),
            _para(
                "The full license text ships with the source as the LICENSE "
                "file. This program comes with NO WARRANTY, to the extent "
                "permitted by law."
            ),
            _bullet(
                "Why AGPL: the PDF engine, PyMuPDF, is itself licensed "
                "AGPL-3.0, so a combined work distributed with it must carry "
                "the same license."
            ),
        ),
        _section(
            "Updates",
            _para(
                "Drawing Analyzer checks for a newer version once a day when it "
                "starts, and you can check any time with the \"Check for "
                "Updates\" button in the bottom-right corner. When an update is "
                "available it offers to download and install it — you're always "
                "in control of when to update."
            ),
            _bullet(
                "Every downloaded update is integrity-checked against a "
                "published SHA-256 hash before it is ever run, so a corrupted "
                "or tampered download is rejected automatically."
            ),
            _bullet(
                "The installer is not code-signed, so Windows SmartScreen may "
                "show a \"Windows protected your PC\" notice the first time you "
                "run it. Choose \"More info\" then \"Run anyway\" to continue — "
                "this is expected for independent software."
            ),
        ),
        _section(
            "Author & copyright",
            _para("Copyright © 2026 Abraham Borg."),
            _link(
                "Abraham Borg — www.linkedin.com/in/abrahamborg",
                "https://www.linkedin.com/in/abrahamborg/",
            ),
        ),
    ),
)


# Ordered as they appear on the header, left → right.
HELP_DOCUMENTS: tuple[HelpDocument, ...] = (
    _HOW_TO_USE,
    _HOW_IT_WORKS,
    _WHY_TRUST_IT,
    _ABOUT,
)


def help_document(key: str) -> HelpDocument:
    """Return the :class:`HelpDocument` with ``key`` (raises ``KeyError`` if absent)."""
    for doc in HELP_DOCUMENTS:
        if doc.key == key:
            return doc
    raise KeyError(key)
