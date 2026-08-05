"""Static help content for the GUI's header modals.

The GUI header carries four buttons — **How to use**, **How it works**,
**Why trust it?**, and **About** — each opening a scrollable modal. The
*content* of those modals lives here as plain data (:class:`HelpDocument`
trees) with **no GUI / tkinter import**, so it is importable and unit-testable
in the hermetic suite even on machines without ``tkinter`` / ``customtkinter``
installed. ``gui.py`` owns only the thin CustomTkinter rendering (see
``_open_help_modal``).

Two documents are *standalone* — reachable from inside the app but not from a
header button: :data:`GET_API_KEY` (from the key field) and
:data:`RUNTIME_TRANSPARENCY` (from the "I'm not convinced" link at the foot of
**Why trust it?**). Both render through the same machinery and are resolvable
via :func:`help_document`.

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
    """One rendered block within a section.

    ``kind`` selects the renderer in ``gui.DrawingAnalyzerApp._render_help_body``:

    ``para``    a wrapped paragraph.
    ``bullet``  a wrapped paragraph carrying a bullet mark.
    ``link``    a clickable label that opens ``href`` in the default browser.
                Only this kind sets ``href``, and it must be ``https``.
    ``pre``     a pre-formatted monospace block (the ASCII diagrams and tables
                in the runtime-transparency briefing). It is rendered
                **verbatim and never re-wrapped**, so every line has to stay
                inside :data:`PRE_MAX_WIDTH` or it will run off the panel at
                the modal's minimum width.
    ``modal``   a clickable label that opens *another* help document, named by
                ``doc_key``. This is what lets one panel hand off to a deeper
                one without ``gui.py`` hard-coding the relationship.
    """

    kind: str  # "para" | "bullet" | "link" | "pre" | "modal"
    text: str
    href: str | None = None
    doc_key: str | None = None


#: Hard ceiling on a ``pre`` block's line length. The help modal is scrollable
#: vertically but not horizontally, and its minimum width is 520 px, so a
#: monospace line much longer than this is clipped rather than wrapped. Guarded
#: by ``tests/test_help_content.py``.
PRE_MAX_WIDTH = 64


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

PROCESSING_MODE_ECONOMY = "Economy"
PROCESSING_MODE_HYBRID = "Hybrid"
PROCESSING_MODE_FAST = "Fast"
PROCESSING_MODES = (
    PROCESSING_MODE_ECONOMY,
    PROCESSING_MODE_HYBRID,
    PROCESSING_MODE_FAST,
)


def processing_transports(mode: str) -> tuple[bool, bool]:
    """Return ``(digest_batch, critique_batch)`` for a GUI processing mode."""
    normalized = str(mode or "").strip().casefold()
    if normalized == PROCESSING_MODE_ECONOMY.casefold():
        return True, True
    if normalized == PROCESSING_MODE_HYBRID.casefold():
        return False, True
    if normalized == PROCESSING_MODE_FAST.casefold():
        return False, False
    raise ValueError(f"unknown processing mode: {mode!r}")


def transport_hint(realtime: bool | str) -> str:
    """One-line, mode-aware hint shown under the Processing checkbox.

    The bool spelling is retained for API/backward compatibility.  The GUI now
    passes ``Economy``, ``Hybrid``, or ``Fast`` so digest and critique transport
    can be chosen independently without exposing implementation details.
    """
    if isinstance(realtime, str):
        digest_batch, critique_batch = processing_transports(realtime)
        if digest_batch and critique_batch:
            return (
                "All eligible vision reads use Anthropic's shared Batch queue: "
                "lowest API price (about half-rate), but often hours and sometimes "
                "overnight. Best when cost matters more than turnaround."
            )
        if not digest_batch and critique_batch:
            return (
                "The initial sheet analysis runs immediately; the two exhaustive-QC "
                "critique reads use the half-rate Batch queue. Standard analysis is "
                "fast; a QC run can still wait hours for its critique batch."
            )
        return (
            f"All reads skip the queue ({REALTIME_TIME_PER_SHEET}); fastest turnaround "
            f"at {REALTIME_COST_PER_SHEET}."
        )
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


def _pre(text: str) -> HelpBlock:
    """A verbatim monospace block (diagram / table). See :data:`PRE_MAX_WIDTH`."""
    return HelpBlock(kind="pre", text=text.strip("\n"))


def _modal(text: str, doc_key: str) -> HelpBlock:
    """A clickable label that opens another :class:`HelpDocument` by key."""
    return HelpBlock(kind="modal", text=text, doc_key=doc_key)


def _section(heading: str, *blocks: HelpBlock) -> HelpSection:
    return HelpSection(heading=heading, blocks=tuple(blocks))


# --------------------------------------------------------------------------
# Outbound links used across the panels. Single-sourced so a moved page is a
# one-line fix and so the tests can assert every href is https.
# --------------------------------------------------------------------------

REPO_URL = "https://github.com/abe-borg/drawing-analyzer"
SECURITY_DOC_URL = f"{REPO_URL}/blob/main/SECURITY.md"
README_URL = f"{REPO_URL}/blob/main/README.md"
ANTHROPIC_PRIVACY_URL = "https://privacy.anthropic.com/"
ANTHROPIC_TRUST_URL = "https://trust.anthropic.com/"
ANTHROPIC_TERMS_URL = "https://www.anthropic.com/legal/commercial-terms"
ANTHROPIC_USAGE_URL = "https://console.anthropic.com/settings/usage"
AGPL_URL = "https://www.gnu.org/licenses/agpl-3.0.html"


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
            _bullet(
                "Don't have a key yet? Click “How do I get one?” beside the key field "
                "for a short, step-by-step walkthrough of creating one."
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
            _bullet(
                "Click Expand beside the box to edit in a larger, resizable window — "
                "handy for a long, structured focus. The two stay in sync as you type."
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
            _para("The QC review section holds two checkboxes:"),
            _bullet(
                "QC Markups — the full exhaustive engineering review: the set's identity "
                "and a model-authored review plan, synthesis, two critique reads per sheet, "
                "cross-sheet QC, the deterministic auditors, the prose harvest, anchoring, "
                "verification, citation checks, marked-up PDFs, and coverage "
                "reconciliation. It costs more than a plain digest; the cost line tells you "
                "how much before you commit."
            ),
            _bullet(
                "Deterministic audit only — adds the whole deterministic auditor battery on "
                "top of the standard analysis and makes no API calls of its own, so it is "
                "free. It does not make the run offline — the sheets are still read. (It is "
                "already included inside QC Markups.)"
            ),
            _bullet(
                "Two sub-toggles refine the markups: Verified & deterministic only "
                "(suppress unverified ink) and Include rejected (grey)."
            ),
            _bullet(
                "Below the checkboxes, Review profiles lists any checklists found in "
                "your profiles folder, pre-ticking the ones that suit the sheet ids it "
                "sees. Your manual choice always wins. No profiles ship with the app — "
                "on a QC run the model writes the review plan for this set itself."
            ),
            _para(
                "Even with neither box checked a run is not throwaway: it still keeps each "
                "sheet's extracted text and the digest's parsed findings, anchors them "
                "offline for free, shows them in the report, and exports them."
            ),
        ),
        _section(
            "6 · (Optional) Pick a processing mode",
            _para(
                "Under Processing, choose how the paid vision reads are sent. The output "
                "contract is identical in all three — you are only trading money for speed."
            ),
            _bullet(
                "Economy (default) — every eligible read goes through Anthropic's shared "
                "Batch queue at about half rate; a run can take hours, sometimes overnight."
            ),
            _bullet(
                "Hybrid — sheet digests run immediately, the QC critique reads go to the "
                "batch queue."
            ),
            _bullet(f"Fast — nothing queues ({REALTIME_TIME_PER_SHEET}); the most expensive option."),
            _bullet(
                "Save tile images + per-tile notes adds a tiles/ folder to the export. It "
                "re-renders cached sheets but costs no extra API money."
            ),
        ),
        _section(
            "7 · Analyze & confirm the cost",
            _para(
                "Press Analyze Drawings. A dialog shows the estimated cost before any paid "
                "call is made — confirm to proceed. The estimate is computed entirely on "
                "your machine; nothing is sent until you accept. Progress and per-sheet "
                "diagnostics stream into the activity log as the run works."
            ),
        ),
        _section(
            "8 · Save your results",
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
            _para(
                "Embed API key in HTML report is off by default, and should usually stay "
                "off: the report's Ask-AI assistant asks for a key the first time you use "
                "it and keeps it only in that browser tab. Ticking the box bakes your key "
                "into the file — convenient, but the file then IS a credential and must "
                "not be shared."
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# Getting an API key
#
# Reached from a "How do I get a key?" link beside the API-key field — this is
# the first wall a non-technical user hits, so the steps are deliberately terse
# and concrete. It is NOT one of the four header modals (HELP_DOCUMENTS), so it
# is exported separately as GET_API_KEY and rendered through the same modal
# machinery.
# --------------------------------------------------------------------------

_CONSOLE_KEYS_URL = "https://console.anthropic.com/settings/keys"

GET_API_KEY = HelpDocument(
    key="get_api_key",
    button_label="How do I get a key?",
    title="How to get an Anthropic API key",
    intro="A one-time setup, about five minutes. You only do this once.",
    sections=(
        _section(
            "What a key is",
            _para(
                "An API key is a secret password that lets this app use Anthropic's "
                "Claude models on your behalf. You pay Anthropic directly for what you "
                "use — there is no subscription, and this app shows the cost before "
                "every paid run."
            ),
        ),
        _section(
            "Get one in four steps",
            _bullet(
                "1 · Go to console.anthropic.com and sign up, or log in if you already "
                "have an account. Creating one is free."
            ),
            _bullet(
                "2 · Open Billing (or “Plans & billing”), add a payment method, and buy "
                "a little credit to start — $5 goes a long way. Usage is pay-as-you-go."
            ),
            _bullet(
                "3 · Open API keys in the left-hand menu, click Create Key, give it any "
                "name, and press Copy. The key is shown only once, so copy it now."
            ),
            _bullet(
                "4 · Paste it into the Anthropic API Key field at the top of this "
                "window. It works immediately and is remembered for next time."
            ),
        ),
        _section(
            "Open the console",
            _para("The Create Key page lives here:"),
            _link("console.anthropic.com/settings/keys", _CONSOLE_KEYS_URL),
        ),
        _section(
            "Keep it safe",
            _para(
                "Your key begins with “sk-ant-”. Treat it like a password: anyone who "
                "has it can spend your credit. This app stores it in your operating "
                "system's secure keyring (never in plain text unless you explicitly "
                "allow it), so you won't have to paste it again."
            ),
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
                "and spliced into the prompt ahead of the images, as the source of truth "
                "for exact strings — tags, schedule values, note numbers, sheet "
                "references. Vector text can't misread a digit the way OCR of a "
                "low-resolution embedded raster can."
            ),
            _bullet(
                "It is sent as-is up to 15,000 characters per sheet — ample for a dense "
                "E-size sheet. A sheet that exceeds it is clipped and explicitly marked "
                "[TRUNCATED] rather than silently shortened, and its images are still sent "
                "whole."
            ),
        ),
        _section(
            "Render & digest",
            _para(
                "Each sheet is rendered to an overview image plus a 6×6 grid of "
                "high-resolution tiles and sent, together with its text layer, to Claude "
                "Opus 5 in a single request. The model returns a structured Markdown "
                "digest plus a machine-readable findings block."
            ),
            _bullet(
                "Ordinary vector sheets render tiles at 1560 px; a scanned or pasted-raster "
                "sheet (empty text layer) renders at 1992 px, because there the pixels are "
                "the only information channel."
            ),
        ),
        _section(
            "Economy, Hybrid, and Fast processing",
            _para(
                "Every sheet is a paid vision call, so how those calls are sent is the "
                "single biggest lever on what a run costs and how long it takes. The "
                "output contract is identical in every mode — you are only trading money for "
                "speed — and cached sheets are free in every mode."
            ),
            _bullet(
                "Economy (the GUI default) submits every eligible vision read through the "
                "Message Batches API. Your sheets join Anthropic's shared queue and are "
                "processed once they reach the front — so a run can finish in a few "
                "minutes, a few hours, or run overnight (8+ hours) depending on how busy "
                "that queue is. In exchange it costs about half the real-time rate — a "
                f"plain digest runs {BATCH_COST_PER_SHEET}, and a full QC review costs "
                "correspondingly more. Ideal for an overnight run when you're not in a rush."
            ),
            _bullet(
                "Hybrid analyzes the initial sheet digests immediately, then sends the two "
                "extra per-sheet critique reads required by QC through the half-rate Batch "
                "queue. A standard (non-QC) run therefore finishes like Fast; a full QC run "
                "can still wait for the critique queue."
            ),
            _bullet(
                "Fast skips the queue: every sheet is analyzed immediately and "
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
            _para(
                "Successful set-level and QC model stages are cached too, but only against "
                "their complete inputs, prompt, model, and settings. Partial or malformed "
                "answers are never reused, and evidence-backed verification still recreates "
                "its audit artifacts."
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
            "Knowing what the set is before reviewing it",
            _para(
                "A QC run does not apply a canned checklist. Two short text-only calls run "
                "first: one works out what the set IS — the disciplines present, which "
                "sheet belongs to which, the jurisdiction, the language and units, and the "
                "codes the set adopts (each with a verbatim quote from the drawings). The "
                "second writes the review checklist a specialist for THIS set would apply."
            ),
            _bullet(
                "Codes from any system are recognized — NFPA, IBC, Eurocode/EN, BS, DIN, "
                "AS/NZS, GB. A plain text search for edition statements is always merged "
                "in as a backstop, so a stated edition can never be argued away."
            ),
            _bullet(
                "The identity is advisory only. It steers the review but never gates or "
                "suppresses a finding, and it is written out to set_identity.json so a "
                "wrong reading is visible rather than laundered."
            ),
            _bullet(
                "Every code-based checklist item must name its code, section, and edition. "
                "Those references flow into the findings and are then verified by the "
                "citation check — the model's own plan is checked, not trusted."
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
                "Prose harvest — coordination and conflict items the digest wrote in prose "
                "are mirrored into the findings so nothing the model raised is left behind."
            ),
            _bullet(
                "Edition audit — a zero-API check that turns a note citing one edition of a "
                "code the set adopts at another into a first-class finding."
            ),
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
        _section(
            "The marked-up PDF",
            _para(
                "Your original files are never modified. A reviewed copy is written beside "
                "them, and every mark is a real PDF annotation authored “Drawing Analyzer "
                "(AI review)”, so it opens as a normal markup list in Bluebeam, Acrobat, or "
                "any other reviewer."
            ),
            _bullet(
                "Marks also ride per-severity PDF layers (High / Medium / Low), so a "
                "reviewer can switch a whole severity tier off in one click."
            ),
            _bullet(
                "A finding with no location on the page becomes a margin callout, placed "
                "in a band checked against the drawing's own content so it never covers "
                "the work. One that will not fit overflows to an appended AI Review Notes "
                "page with a link back."
            ),
        ),
        _section(
            "Every run writes its own record",
            _para(
                "Each export carries run.log (readable) and run_manifest.json "
                "(machine-readable): the run id, the environment, every input accepted or "
                "rejected, the resolved configuration, a per-sheet and per-stage table, "
                "token and cost usage, the coverage accounting, and the SHA-256 of every "
                "file in the export. Both are written even when the run fails."
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
            "Your drawings are never edited",
            _para(
                "The analyzer reads your PDFs and writes new files beside them. The files "
                "you loaded are opened read-only and are never modified, moved, or "
                "overwritten — the markups land on a separate reviewed copy."
            ),
        ),
        _section(
            "Even the AI's own checklist is checked",
            _para(
                "On a QC run the model writes the review plan for this particular set, and "
                "every code-based item on it has to name its code, section, and edition. "
                "Those references are then put through the citation check like any other — "
                "a section the model invented comes back as a mismatch instead of quietly "
                "becoming the standard you were reviewed against."
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
            "The run audits itself, in writing",
            _para(
                "Every export carries run.log and run_manifest.json: the run id, the exact "
                "software and model versions, every input accepted or rejected, the "
                "settings actually used, a per-stage table with statuses and call counts, "
                "the token and dollar usage, and the SHA-256 hash of every file produced. "
                "They are written even when the run fails, so a bad run leaves the same "
                "trail as a good one."
            ),
            _bullet(
                "Both are scrubbed as they are written — API keys redacted, absolute paths "
                "reduced to file names — so the record can be filed with the project "
                "without carrying your credentials or your folder layout."
            ),
        ),
        _section(
            "Model output is treated as hostile",
            _para(
                "A drawing is untrusted input: its text and images become the prompt, so "
                "what the model writes back can be influenced by what is on the page. "
                "Everything it returns is therefore handled as data that can never execute "
                "— in the reviewed PDF, the exports, and the HTML report's Ask-AI assistant."
            ),
            _link("The full trust boundary — SECURITY.md", SECURITY_DOC_URL),
        ),
        _section(
            "Still not convinced?",
            _para(
                "Good. None of the above should be taken on faith. The panel below is the "
                "long version: every model call the app can make, exactly what leaves your "
                "computer and what never does, what the AI is allowed to touch, and how to "
                "check each claim for yourself."
            ),
            _modal(
                "I'm not convinced — show me exactly what the AI does at runtime",
                "runtime_transparency",
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# Runtime transparency — "I'm not convinced"
#
# Reached from the link at the foot of "Why trust it?", for the reader who
# wants the mechanism rather than the reassurance. It is NOT a header modal.
#
# Audience: competent AEC professionals who are not software developers. So:
# name the real mechanism (model ids, tool names, file names, env vars) but
# always say what it *means* in the same breath. Where a claim is Anthropic's
# policy rather than something this app enforces, say so — the whole point of
# this panel is that it does not ask to be believed.
#
# The ASCII diagrams are `pre` blocks rendered verbatim; keep every line inside
# PRE_MAX_WIDTH or it will be clipped at the modal's minimum width.
# --------------------------------------------------------------------------

_TRUST_BOUNDARY_DIAGRAM = """
+-- YOUR COMPUTER ----------------------------+
|  drawing PDFs    spec docs    your API key  |
|                                             |
|  render tiles + lift the vector text layer  |
|  deterministic auditors, exact-decimal math |
|  anchor quotes, draw markups, write exports |
+---------------------+-----------------------+
                      |  HTTPS + your API key
                      v
         +-- api.anthropic.com -------------+
         |  Claude reads the images + text  |
         |  and writes the findings back    |
         |  web_search runs HERE, not on    |
         |  your machine (citation check)   |
         +----------------------------------+
"""

_STAGE_TABLE = """
WHAT HAPPENS                    WHO       PAID?
------------------------------- --------- -----
list sheets, render tiles       your PC   free
lift the vector text layer      your PC   free
sheet digest   (1 call/sheet)   Anthropic paid
focus report   (1 call/set)     Anthropic paid
set identity + review plan      Anthropic paid
critique       (2 calls/sheet)  Anthropic paid
cross-sheet QC (1 call/set)     Anthropic paid
deterministic auditors          your PC   free
arithmetic re-check (Decimal)   your PC   free
edition audit                   your PC   free
anchor quotes -> rectangles     your PC   free
verify         (1 call/finding) Anthropic paid
investigate    (<=10 per run)   Anthropic paid
citation check (per code ref)   Anthropic paid
draw markups, reopen, reconcile your PC   free
report, exports, run manifest   your PC   free
"""

_INVESTIGATION_DIAGRAM = """
   an UNCERTAIN finding
           |
           v
   Claude asks for ONE piece of evidence  <---+
           |                                  |
           v                                  |
   your PC runs it and saves the image        |  up to 6
   BEFORE sending it:                         |  rounds,
      crop_region - a region of a sheet       |  then the
      find_text   - text search (free)        |  host ends
      view_sheet  - another sheet overview    |  the loop
           |                                  |
           +----------------------------------+
           |
           v
   CONFIRMED / CONTRADICTED / still UNCERTAIN
   (running out of budget NEVER means "wrong")
"""


RUNTIME_TRANSPARENCY = HelpDocument(
    key="runtime_transparency",
    button_label="I'm not convinced",
    title="What the AI actually does at runtime",
    intro=(
        "Every model call this app can make, what leaves your computer, what the "
        "AI is allowed to touch — and how to check all of it yourself."
    ),
    sections=(
        _section(
            "Why this panel exists",
            _para(
                "“Why trust it?” describes the safeguards. This one describes the "
                "machinery, because a safeguard you can't inspect is just a promise. "
                "Nothing here needs to be taken on faith: every claim below names a file, "
                "a setting, or an artifact you can open yourself, and the last section "
                "tells you where to look."
            ),
            _para(
                "The short version: this is a desktop program that reads your drawings "
                "and writes a report. It sends page images and page text to Anthropic and "
                "gets words back. It never edits your drawings, never runs code the model "
                "wrote, and never talks to a server belonging to whoever made this app — "
                "because there isn't one."
            ),
        ),
        _section(
            "The trust boundary, in one picture",
            _pre(_TRUST_BOUNDARY_DIAGRAM),
            _para(
                "There is exactly one place your project data goes: Anthropic's API, "
                "authenticated with the key you supplied and billed to your own account. "
                "There is no account to create here, no cloud workspace, no upload step, "
                "and no analytics, telemetry, or crash reporting of any kind."
            ),
            _bullet(
                "The one other outbound connection is the update check, which reads a "
                "small version file from github.com. It carries no project data, and it "
                "can be switched off."
            ),
            _bullet(
                "Web searching during the citation check runs on Anthropic's servers, not "
                "from your machine, and only ever searches for the code section named in a "
                "finding — never your drawing content."
            ),
        ),
        _section(
            "Exactly what leaves your computer",
            _para("On a paid stage, the request body contains:"),
            _bullet(
                "Rendered images of the sheet — one overview plus a 6×6 grid of tiles. "
                "These are pictures of your drawing, so treat them as you would treat "
                "emailing the PDF."
            ),
            _bullet(
                "The sheet's text layer — the PDF's own selectable text, sent as-is, up to "
                "15,000 characters per sheet. That comfortably holds a dense E-size sheet; "
                "a pathological one (a huge embedded schedule) is cut at the limit and "
                "marked [TRUNCATED], so the model knows it is reading a clipped text layer "
                "rather than a complete one. The images are never truncated — the sheet is "
                "still read whole either way."
            ),
            _bullet(
                "The file name of each PDF and which page this sheet is — every request is "
                "framed with something like “M-101.pdf (page 3/12)”, and the batch path "
                "names its uploads from the same label. Only the bare name travels, never "
                "the folder it came from. If your file names carry a client or a project "
                "you would rather not send, rename the copies before loading them."
            ),
            _bullet(
                "The text of any spec documents you attached, and the focus sentence you "
                "typed."
            ),
            _bullet(
                "In later stages, much smaller things: a cropped image around one finding, "
                "the sentence being checked, and a code section number."
            ),
            _bullet(
                "Your API key, in the authorization header. That is what a key is for; it "
                "is what tells Anthropic whose account to bill."
            ),
            _para(
                "What is NOT in the request: the path to your files (only the bare file "
                "name travels, never the folder structure around it), your machine name, "
                "your identity, your other projects, or anything from any drawing you did "
                "not load into this run."
            ),
        ),
        _section(
            "What Anthropic does with it — and what this app can promise",
            _para(
                "This app can promise where it sends data. It cannot promise what happens "
                "after that, so here is the honest split."
            ),
            _bullet(
                "Anthropic's commercial terms for the API state that inputs and outputs "
                "are not used to train its models. That is Anthropic's policy and your "
                "contract with them — not something this software enforces. Read it "
                "yourself; the links are below."
            ),
            _bullet(
                "Retention, regional processing, zero-data-retention arrangements, and "
                "enterprise controls are all settings on YOUR Anthropic account, not on "
                "this app. If your firm needs a particular arrangement, it is negotiated "
                "there and this app inherits it automatically."
            ),
            _bullet(
                "If your project genuinely cannot leave your premises, this is not the "
                "right tool. There is no offline mode: reading a sheet means sending it. "
                "Say so before a set goes in, not after."
            ),
            _link("Anthropic Privacy Center", ANTHROPIC_PRIVACY_URL),
            _link("Anthropic Trust Center (security, compliance, subprocessors)", ANTHROPIC_TRUST_URL),
            _link("Anthropic commercial terms of service", ANTHROPIC_TERMS_URL),
        ),
        _section(
            "Which model does what",
            _para(
                "Different jobs go to different models, chosen for the job rather than for "
                "the price tag. Every one of these can be overridden with an environment "
                "variable if your firm standardizes on something else."
            ),
            _bullet(
                "Claude Opus 5 — reading the sheets, the critique, working out the set's "
                "identity, writing the review plan, the cross-sheet conflict hunt, and the "
                "investigation loop. The deep-reasoning work."
            ),
            _bullet(
                "Claude Sonnet 5 — the first verification look at each finding. Smaller, "
                "faster and cheaper, because the question is narrow: does this one thing "
                "hold in this one crop? It also runs the report's Ask-AI assistant, which "
                "needs to fetch web pages — a thing Opus 5 cannot do."
            ),
            _bullet(
                "Escalation is one-way and upward. A finding the smaller model could not "
                "settle does not get left at the cheap answer — worst severity first, it "
                "goes to the Opus-driven investigation loop below."
            ),
        ),
        _section(
            "One run, stage by stage — who does it and who pays",
            _pre(_STAGE_TABLE),
            _para(
                "Everything marked “your PC” is ordinary Python running locally: geometry, "
                "string matching, exact decimal arithmetic, PDF drawing. It costs nothing, "
                "works with no network, and produces the same answer every time."
            ),
            _para(
                "A standard run without QC pays for exactly one thing: the per-sheet "
                "digest — plus the focus report, and only if you typed a focus. Set "
                "identity and the review plan belong to the QC stack and do not run "
                "otherwise, and ticking Deterministic audit only adds no paid rows at all."
            ),
        ),
        _section(
            "Loading drawings and estimating the cost — zero API calls",
            _para(
                "Dropping in PDFs opens them locally to count pages and check whether each "
                "has a real text layer. The cost estimate is computed on your machine from "
                "sheet count, image sizes, and a local token estimator, then priced from a "
                "built-in rate table. Nothing is transmitted, and no money is spent, until "
                "you press Confirm on the estimate dialog."
            ),
        ),
        _section(
            "Standard analysis — the per-sheet digest",
            _para(
                "One paid request per uncached sheet. It carries the sheet's images and "
                "its text layer, and asks for a structured description plus a "
                "machine-readable findings block."
            ),
            _bullet(
                "The text layer is sent ahead of the images and named as the source of "
                "truth for exact strings, so tags and schedule numbers come from the PDF's "
                "own text rather than from the model reading pixels."
            ),
            _bullet(
                "The reply is parsed by ordinary code, not interpreted. The findings block "
                "is cut out byte-exactly; the prose is stored untouched. Malformed output "
                "fails the sheet loudly instead of being patched up."
            ),
            _bullet(
                "Sheets are never split, summarized, or sampled — every sheet is read "
                "whole, every time."
            ),
        ),
        _section(
            "Per-run focus and spec documents",
            _para(
                "The focus text you type is added to the prompt for each sheet and drives "
                "an extra Focus Report. It never replaces the standard digest."
            ),
            _para(
                "Spec documents are read locally (PDF, Word, text, Markdown), converted to "
                "plain text, budgeted, and folded into the review prompts as reference "
                "material. They are treated as ground truth to check the drawings against; "
                "the app does not modify them and does not produce a separate spec report."
            ),
        ),
        _section(
            "Processing mode — the same review, sent differently",
            _para(
                "Economy, Hybrid, and Fast change only how requests are transported. Same "
                "models, same prompts, same inputs, same output contract."
            ),
            _bullet(
                "Economy and Hybrid use Anthropic's Message Batches API: images are "
                "uploaded once through the Files API, the job joins a shared queue, and "
                "results come back when it reaches the front — hours, sometimes overnight, "
                "at roughly half the price."
            ),
            _bullet(
                "Uploaded files are released on every exit path — a finished batch, a "
                "cancelled one, or a collection error. A batch that can't be cancelled "
                "leaves its files to expire on Anthropic's side."
            ),
            _bullet(
                "If a batch stalls, the app resubmits the unfinished sheets as fresh "
                "batches. It deliberately does NOT fall back to full-price real-time calls "
                "behind your back — a run cannot silently cost double."
            ),
            _bullet(
                "Fast sends everything immediately. On the two critique reads it reuses "
                "the identical image prefix so the second read bills those image tokens at "
                "about a tenth — same tokens in, so the findings are unchanged."
            ),
        ),
        _section(
            "Deterministic audit only — the checks with no AI in them",
            _para(
                "The auditor battery itself makes zero API calls. It is plain Python "
                "reading the text layers: stale sheet cross-references, columns that don't "
                "total, a tag spelled two ways, title-block fields that drifted across the "
                "set, an index that disagrees with the sheets present. Its findings are "
                "marked DETERMINISTIC and are trusted without asking a model."
            ),
            _para(
                "Be clear about what the checkbox does, though: it adds these checks on "
                "top of a normal run, and a normal run still reads every sheet with the "
                "API. It costs nothing extra — it does not make the run offline. There is "
                "no fully offline mode."
            ),
            _bullet(
                "Reference checking first learns the set's own numbering convention from "
                "the sheets themselves, then judges each reference against it — with a "
                "negative list so a voltage, an RFI number, a dimension, or a code section "
                "is never mistaken for a missing sheet."
            ),
            _bullet(
                "Arithmetic is done with exact decimal arithmetic, never floating point "
                "and never by evaluating text as code."
            ),
        ),
        _section(
            "QC Markups — what each stage actually sends",
            _bullet(
                "Set identity — one text-only call over the digest summaries, the early "
                "sheets' text, and the text around every code-edition mention. Returns "
                "disciplines, jurisdiction, units, and adopted codes with quotes."
            ),
            _bullet(
                "Review plan — one text-only call that writes this set's checklist. Capped "
                "at 60 items; an over-long item is dropped rather than truncated; every "
                "code item must name code, section, and edition."
            ),
            _bullet(
                "Critique — the sheet's images and text again, under a hostile persona "
                "whose only job is to find problems, including things that should be on "
                "the sheet and aren't. Run twice; agreement is recorded, disagreement is "
                "kept rather than resolved by discarding."
            ),
            _bullet(
                "Cross-sheet QC — text only, no images: the sheet summaries together, "
                "hunting for conflicts that only appear when sheets are compared."
            ),
            _bullet(
                "Verification — for each finding, a high-DPI crop around its location plus "
                "a short question: does this hold in this crop? The crop is written to "
                "disk and hashed BEFORE it is sent, so no verdict can rest on an image "
                "that isn't in the evidence folder."
            ),
            _bullet(
                "Citation check — for each unique code reference, a web-search-backed call "
                "asking whether that section, in the edition this set adopts, supports the "
                "claim citing it."
            ),
            _para(
                "Between and after these, everything else is local: merging findings into "
                "one ledger, mapping quotes to rectangles, numbering, drawing, and "
                "reconciling."
            ),
        ),
        _section(
            "The investigation loop — the only agentic part of the app",
            _para(
                "When the verifier honestly answers “I can't see that in this crop”, the "
                "app can let the model ask for more evidence. This is the one place the "
                "model drives a loop instead of answering a single question, so it is "
                "worth understanding precisely."
            ),
            _pre(_INVESTIGATION_DIAGRAM),
            _bullet(
                "The model does not execute anything. It names a tool and its arguments; "
                "YOUR machine decides whether that is legal, runs it, and hands back the "
                "result."
            ),
            _bullet(
                "There are exactly three tools, all read-only, all confined to the sheets "
                "in this run: crop a region of a sheet, search a sheet's text, or view "
                "another sheet's overview. No file system access, no shell, no network, no "
                "writing, no reaching outside the loaded set."
            ),
            _bullet(
                "Every image it requests is saved to the finding's evidence folder before "
                "being sent, alongside investigation.json recording the whole exchange in "
                "order. You can replay what it looked at."
            ),
            _bullet(
                "Hard budgets: 6 evidence requests per finding, 10 findings per run, worst "
                "severity first. At the cap the host forces a final text answer. A finding "
                "it could not settle stays UNCERTAIN — a spent budget or a garbled reply "
                "can never mark a finding wrong."
            ),
            _bullet(
                "The loop runs strictly one finding at a time, and its conclusions are "
                "cached against the content of the whole set — so a warm re-run replays "
                "the same evidence with no API calls, and any edit to a drawing throws the "
                "cached answer away."
            ),
        ),
        _section(
            "The citation check — the only time anything is searched online",
            _para(
                "Code citations are the one thing a drawing set genuinely cannot validate "
                "about itself, so this stage asks the internet. The search runs as a "
                "server-side tool inside Anthropic's API, not from your machine."
            ),
            _bullet(
                "The query is the code reference and the claim — a section number and a "
                "sentence. Your sheets, images, and file names are not searched for."
            ),
            _bullet(
                "Sources are filtered by a built-in blocklist: forums, Q&A aggregators, "
                "DIY content farms, social media, general encyclopedias, and other AI "
                "assistants' output. Another model's answer is not a citable source."
            ),
            _bullet(
                "The companion fetch tool can only open a page that already appeared in a "
                "search result in the same conversation, so the model cannot fetch a URL "
                "it invented — and it is capped in both page count and page size."
            ),
            _bullet(
                "A mismatch never silently downgrades a finding. It is surfaced with which "
                "edition the verdict was checked against, what the current edition is, and "
                "a link — because sometimes the stale citation IS the finding."
            ),
            _bullet(
                "Verdicts are cached for 30 days by default; a partial or failed check is "
                "never cached, so a cache hit can never hide an unchecked claim."
            ),
        ),
        _section(
            "Marking up the PDFs — and what is not touched",
            _para(
                "The markup stage is entirely local. Your original files are opened "
                "read-only; a separate reviewed copy is written."
            ),
            _bullet(
                "Every mark is a standard PDF annotation authored “Drawing Analyzer (AI "
                "review)”. Provenance is unmistakable in Bluebeam, Acrobat, or any other "
                "reviewer, and any recipient can delete the whole layer."
            ),
            _bullet(
                "After saving, the app reopens the file it just wrote and looks for every "
                "mark it intended to place, matched by a private per-run stamp. If "
                "anything is missing the file is renamed to say INCOMPLETE. Markups from "
                "an earlier run can neither satisfy nor break that count."
            ),
        ),
        _section(
            "The HTML report's Ask-AI assistant",
            _para(
                "The report is a single self-contained file. Its chat panel calls "
                "Anthropic directly from your browser — there is no server in between, and "
                "nothing about your question reaches anyone else."
            ),
            _bullet(
                "By default your key is NOT written into the file. The panel asks for one "
                "on first use and keeps it only in that browser tab's sessionStorage, "
                "cleared when the tab closes or when you press Forget key. The file is "
                "safe to send to a colleague."
            ),
            _bullet(
                "Embed API key in HTML report is an explicit opt-in that bakes the key "
                "into the file. The report then shows a red warning, and the file must be "
                "treated as a credential — deleting or regenerating it is the only way to "
                "remove the key."
            ),
            _bullet(
                "The conversation is kept for you. It saves into that browser's local "
                "storage for that report, so a refresh or reopening the file does not "
                "lose it, and New chat erases it. Save writes it to a JSON file you "
                "choose and Load reads one back, so a conversation can live beside the "
                "report or go to a colleague. None of that is uploaded anywhere."
            ),
            _bullet(
                "A saved conversation never contains your API key: anything shaped like "
                "a key is redacted from the whole document before it is written, and the "
                "file format has no field for one. A conversation you load back in is "
                "treated as untrusted -- rendered as text like any model output, and any "
                "tool call recorded in it is shown as a label, never re-run."
            ),
            _bullet(
                "The model's answers are inserted as text nodes, never as markup, and "
                "every link is validated to be an absolute https URL before it becomes "
                "clickable. The page also carries a content-security policy that pins the "
                "scripts by hash and permits network access to nowhere except Anthropic's "
                "API."
            ),
        ),
        _section(
            "Updates, logs, and what is kept on your disk",
            _bullet(
                "Update check — once a day at launch, plus the button in the corner. It "
                "reads a version file from github.com and sends nothing about you or your "
                "project. Any download is verified against a published SHA-256 hash before "
                "it is allowed to run, and you choose when to install."
            ),
            _bullet(
                "Diagnostics log — a rotating local file, never uploaded. Every line runs "
                "through a redaction filter first, so keys, authorization headers, and "
                "named secret fields are replaced before they are written."
            ),
            _bullet(
                "Cache — analysis results are cached in a file under your home folder, "
                "keyed by the content of each sheet. Editing a sheet re-analyzes only that "
                "sheet. Deleting the file loses nothing but money."
            ),
            _bullet(
                "Chat transcripts — the report's assistant keeps your conversation in "
                "that browser's local storage for that report, and Save writes a JSON "
                "copy wherever you choose. Both stay on this machine; New chat erases "
                "the stored one. Note that a report opened straight off disk shares one "
                "local-storage area with every other local page in that browser, so the "
                "per-report key separates conversations but does not wall them off."
            ),
            _bullet(
                "API key — stored in your operating system's credential manager (Windows "
                "Credential Manager, macOS Keychain, Secret Service on Linux). If none is "
                "available it is NOT quietly written to disk: the app asks first, and "
                "declining keeps it for the session only."
            ),
            _bullet(
                "Exports — the report, the reviewed PDFs, the evidence crops, the "
                "structured findings, and the run record all land in the folder you "
                "choose. They describe your project; file them like drawings."
            ),
        ),
        _section(
            "What the model is structurally not allowed to do",
            _para(
                "These are not instructions in a prompt asking the model to behave. They "
                "are things the surrounding program does not offer it."
            ),
            _bullet(
                "It cannot run code. Nothing it returns is ever evaluated, executed, or "
                "used to build a command."
            ),
            _bullet(
                "It cannot read or write files. The three investigation tools are the only "
                "way it can reach anything, they are read-only, and they are scoped to the "
                "sheets in the current run."
            ),
            _bullet(
                "It cannot do the arithmetic. It transcribes the numbers it sees; the "
                "program does the maths exactly. A number it merely transcribed is not "
                "trusted as ground truth until a crop confirms it."
            ),
            _bullet(
                "It cannot number, order, or assemble the output. Numbering happens after "
                "everything is anchored, positionally, in code — the same inputs produce "
                "the same report every time."
            ),
            _bullet(
                "It cannot declare the run complete. Coverage is counted from marks found "
                "in the saved PDF, and a stage that failed holds the status down no matter "
                "what any model said."
            ),
            _bullet(
                "It cannot delete or hide a finding. Merging duplicates requires semantic "
                "sameness AND compatible details; overlapping on the page is never enough "
                "on its own."
            ),
        ),
        _section(
            "The attack you should actually worry about",
            _para(
                "The realistic threat is not the model going rogue. It is a drawing "
                "containing text crafted to steer it — a note that reads like an "
                "instruction. Because the drawing becomes the prompt, the model's reply can "
                "be influenced by whatever is on the page."
            ),
            _para("So every reply is treated as hostile text, and that is contained three ways:"),
            _bullet(
                "It is never executed anywhere — not in the PDF, not in the exports, not "
                "in the report, which escapes every value and pins its scripts by hash."
            ),
            _bullet(
                "It is anchored. A quote that matches nothing anywhere in the set is the "
                "hallucination signal: it is labelled UNANCHORED, shown loudly in the "
                "margin, and never drawn as though it had a real location."
            ),
            _bullet(
                "It is bounded. Fabricated code sections come back from the citation check "
                "as mismatches; invented arithmetic loses to the exact calculation; a "
                "claimed finding that a crop contradicts is pulled from the ink."
            ),
        ),
        _section(
            "What this is not",
            _para(
                "Stated plainly, because the honest limits matter as much as the "
                "safeguards."
            ),
            _bullet(
                "It is not a stamped review and carries no professional liability. It is a "
                "back-check that produces markups for a qualified person to adjudicate. "
                "The engineer of record is still the engineer of record."
            ),
            _bullet(
                "It is not exhaustive. It will miss things a good reviewer catches — "
                "particularly anything that depends on project history, a conversation, or "
                "a document you didn't give it."
            ),
            _bullet(
                "It produces false positives on purpose. The design keeps a doubtful "
                "finding and labels it rather than dropping it, because a wrong markup "
                "costs you a minute and a missed conflict costs you a change order."
            ),
            _bullet(
                "Models are probabilistic. Two runs of the same set can differ in what "
                "they raise. The assembly around them is deterministic; the reading is not."
            ),
            _bullet(
                "It comes with no warranty. It is free software under the AGPL, offered "
                "as-is."
            ),
        ),
        _section(
            "Don't take our word for it — check",
            _bullet(
                "Watch it work: Open Diagnostics Log during a run shows every request as "
                "it happens, with the key redacted."
            ),
            _bullet(
                "Read the receipts: run.log and run_manifest.json in any export list every "
                "stage, every call, every token, and the SHA-256 of every file produced."
            ),
            _bullet(
                "Look at the evidence: the evidence/ folder holds the exact image crop the "
                "verifier saw for each finding, plus the tool trace for anything "
                "investigated. Judge the verdicts yourself."
            ),
            _bullet(
                "Check the bill: your Anthropic console shows spend independently of "
                "anything this app reports."
            ),
            _bullet(
                "Watch the wire: point any network monitor at it. You will see "
                "api.anthropic.com and, once a day, github.com. Nothing else."
            ),
            _bullet(
                "Read the source: all of it, including everything described in this panel. "
                "The licence requires it to stay open, which is why this claim is "
                "checkable rather than promotional."
            ),
            _link("Source code on GitHub", REPO_URL),
            _link("SECURITY.md — the full trust boundary", SECURITY_DOC_URL),
            _link("README — the complete technical description", README_URL),
            _link("Your Anthropic usage and spend", ANTHROPIC_USAGE_URL),
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
            _bullet(
                "In practice this is also a transparency guarantee: the "
                "complete source of the version you are running must be "
                "available, so every claim the help panels make about what the "
                "software does can be checked against the code."
            ),
            _link("Source code on GitHub", REPO_URL),
            _link("The GNU Affero General Public License, version 3", AGPL_URL),
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


# Reachable from inside the app, but not from a header button. Every ``modal``
# block's ``doc_key`` must resolve through :func:`help_document`, so anything
# linked from a panel has to be registered here (or in HELP_DOCUMENTS).
STANDALONE_DOCUMENTS: tuple[HelpDocument, ...] = (
    GET_API_KEY,
    RUNTIME_TRANSPARENCY,
)


def help_document(key: str) -> HelpDocument:
    """Return the :class:`HelpDocument` with ``key`` (raises ``KeyError`` if absent).

    Covers the four header modals (:data:`HELP_DOCUMENTS`) and the standalone
    panels (:data:`STANDALONE_DOCUMENTS`) — the API-key guide reached from the
    key field, and the runtime-transparency briefing reached from the "I'm not
    convinced" link at the foot of "Why trust it?".
    """
    for doc in (*HELP_DOCUMENTS, *STANDALONE_DOCUMENTS):
        if doc.key == key:
            return doc
    raise KeyError(key)
