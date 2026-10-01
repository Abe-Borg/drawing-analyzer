"""Static help content for the GUI's header modals.

The GUI header carries four buttons — **How to use**, **How it works**,
**Why trust it?**, and **About** — each opening a scrollable modal. The
*content* of those modals lives here as plain data (:class:`HelpDocument`
trees) with **no GUI / tkinter import**, so it is importable and unit-testable
in the hermetic suite even on machines without ``tkinter`` / ``customtkinter``
installed. ``gui.py`` owns only the thin CustomTkinter rendering (see
``_open_help_modal``).

The API-key guide is reached from the key field. Keep help faithful to current
behavior; explain privacy and limits without maintaining a second code inventory.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import __version__


@dataclass(frozen=True)
class HelpBlock:
    """A paragraph, bullet, or HTTPS link in the shared help renderer."""

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
                "wins over a saved key: it fills the field at launch."
            ),
            _bullet(
                "An analysis keeps the key it started with: the field is locked "
                "until the run ends. The app keeps the key out of its own "
                "environment, so it does not pass it on to programs it starts (a key "
                "you set system-wide is visible to every program anyway)."
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
                "the run.log / run_manifest.json record) — written even for a run that "
                "analyzed nothing, which is exactly when that record is the diagnostic. "
                "A run that crashed outright has no context to export; the failure is in "
                "the activity log and the diagnostics file instead."
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
    intro="A vision pipeline that supplies page images and extracted text for a model review you must check.",
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
                "Each accepted PDF page is one sheet. Uncached digest reads receive the "
                "overview plus all 36 tiles. Smaller crops are used by later verification "
                "and investigation; supplied pixels do not prove the model noticed everything."
            ),
        ),
        _section(
            "Text-layer grounding",
            _para(
                "Before rasterizing, selectable PDF text is extracted and placed ahead "
                "of the images. It helps check strings such as tags and schedule values, "
                "but extraction order and the PDF's text layer can be wrong. Raster-only "
                "pages need the model to read the pixels."
            ),
            _bullet(
                "It is sent as-is up to 15,000 characters per sheet. A longer sheet is "
                "clipped and explicitly marked "
                "[TRUNCATED] rather than silently shortened, and its images are still sent "
                "whole."
            ),
        ),
        _section(
            "Render & digest",
            _para(
                "Each sheet is rendered to an overview image plus a 6×6 grid of "
                "high-resolution tiles and sent, together with its text layer, to Claude "
                "Opus 5.5 in a single request. The model returns a structured Markdown "
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
                "sheet can reuse unchanged sheet digests. Changed set-level inputs can "
                "still need new calls. A two-level key can avoid digest rasterizing on "
                "a warm run; verification, markups or saved tiles may still render."
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
                "The model proposes adopted codes and editions; local matching also "
                "checks supported edition statements. Check both against the actual "
                "project jurisdiction and adopted editions. Neither guarantees that "
                "every code or edition statement was recognized."
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
                "are parsed and matched into findings. Filtering and parsing can omit items."
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
                "conservative (a tile overlap is never enough on its own)."
            ),
        ),
        _section(
            "The marked-up PDF",
            _para(
                "Analysis reads your originals and writes reviewed copies in temporary "
                "work. Save Reviewed PDF(s) copies them to your chosen folder; existing "
                "destinations can be overwritten. Marks are PDF annotations authored “Drawing Analyzer "
                "(AI review)”, so it opens as a normal markup list in Bluebeam, Acrobat, or "
                "any other reviewer."
            ),
            _bullet(
                "Marks also ride per-severity PDF layers (High / Medium / Low), so a "
                "reviewer can switch a whole severity tier off in one click."
            ),
            _bullet(
                "A finding with no location on the page becomes a margin callout, placed "
                "in a band checked against detected drawing content. That heuristic is "
                "not a proof of empty space. One that will not fit overflows to an appended AI Review Notes "
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
    key="why_trust_it", button_label="Why trust it?",
    title="Why trust it?",
    intro="The design assumes you check the review, so it records origins, uncertainty and evidence instead of treating a model's answer as approval.",
    sections=(
        _section("You can separate findings from their origins", _para(
            "Prose is model-authored. Findings keep origin tags, quotes, locations and check results in the ledger — the exported list you can inspect. An origin tag is not proof.")),
        _section("Local checks support specific claims with evidence", _para(
            "The first vision pass uses an overview and tiles for each readable sheet; failed reads remain incomplete. Text checks and quote matching run locally. Decimal (base-ten) arithmetic checks transcribed equations; DETERMINISTIC status requires matching the numbers and relationship to the drawing. Whole-sheet coverage does not guarantee every issue is found: models can misread or miss content.")),
        _section("Uncertainty and rejected findings have separate labels", _para(
            "Model crop checks label findings VERIFIED, REJECTED or UNCERTAIN; missing locations are UNANCHORED. An inconclusive check does not prove a finding false. Rejected findings remain in the ledger/index.")),
        _section("Saved annotations are checked against the plan", _para(
            "The writer stamps required marks, reopens the PDFs and compares receipts with the plan. Missing required marks make coverage INCOMPLETE; this checks saved marks, not whether every defect was found.")),
        _section("Approved work can continue without another click", _para(
            "Launch may check GitHub for updates; that check can be disabled. Analyze and report Send start paid calls, retries, tools and cleanup automatically. Analysis has no Stop button or hard spending cap. Closing a window or clearing local results does not refund calls already made or cancel a submitted batch.")),
        _section("You control the key and export choices", _para(
            "Desktop keys prefer your operating system's tested credential store; a readable-file fallback needs consent. HTML omits the key by default; embedding puts it in the file. Report chat keeps entered keys in browser session storage and saved conversations in local storage when available. Protect exported reports, evidence, caches and browser data as private project files.")),
        _section("Project data and automatic connections are described", _para(
            "Reviews send page images, source/spec text and project metadata to Anthropic by default; report Send sends report context and chat history. Configured desktop endpoints or proxies can change that route. Provider web tools may research project-derived claims. Update checks reach GitHub and redirects; optional installers and clicked links can reach other hosts. Local reference checks add no API calls, but Analyze still runs a paid digest.")),
        _section("You can inspect evidence and estimated spending", _para(
            "Export All writes findings, source text, evidence, receipts and file fingerprints. Costs are estimates: interrupted usage, fallback pricing and chat search charges can be missing. Check findings and missed known issues against the drawings, and spending against your provider."),
            _link("Privacy and security details", f"{REPO_URL}/blob/main/SECURITY.md")),
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
                "file. The Windows installer shows it for you to accept and "
                "installs a copy as LICENSE.txt in the app's folder. This "
                "program comes with NO WARRANTY, to the extent permitted by law."
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
                "Every downloaded update is integrity-checked against the SHA-256 "
                "hash published in that release before it is ever run, so a "
                "corrupted, truncated or substituted download is rejected "
                "automatically. What that does not do is vouch for the release "
                "itself: the hash ships in the same release as the installer, so "
                "it protects the transfer, and trust in the contents rests on "
                "HTTPS to github.com and on who can publish a release."
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


# Reached from the key field rather than a header button.
STANDALONE_DOCUMENTS: tuple[HelpDocument, ...] = (
    GET_API_KEY,
)


def help_document(key: str) -> HelpDocument:
    """Return the :class:`HelpDocument` with ``key`` (raises ``KeyError`` if absent).

    Covers the four header modals (:data:`HELP_DOCUMENTS`) and the standalone
    API-key guide (:data:`STANDALONE_DOCUMENTS`).
    """
    for doc in (*HELP_DOCUMENTS, *STANDALONE_DOCUMENTS):
        if doc.key == key:
            return doc
    raise KeyError(key)
