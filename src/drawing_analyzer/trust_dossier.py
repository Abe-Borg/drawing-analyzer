# Purpose: explain the shipped trust boundary to the AEC professional who must
# check and put their name on a review. This is evidence, not a correctness pledge.
# If the implementation changes, this changes with it. A trust document that has
# drifted from the code is worse than none.
"""Source-linked dossier data and a self-contained, accessible HTML edition.

The desktop renderer consumes the same small Section/Note/Table/Contrast/Runtime
primitives. No model request, network connection, or external asset is used to build it.
The claims ledger was created before this copy; refs name its inventory rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from importlib import import_module


# Facts without an exported production constant. Tests pin these to the actual
# SDK defaults and JavaScript literals. Do not move production policy here.
PINNED_FACTS = {
    "api_host": "api.anthropic.com", "sdk_retries": 2,
    "sdk_connect_seconds": 5, "sdk_read_seconds": 600,
    "chat_continuations": 8, "chat_tool_rounds": 10,
    "chat_searches": 8, "chat_fetches": 4, "chat_fetch_tokens": 40000,
    "chat_storage_chars": 500000, "verify_dpi": 300,
}

# Every interpolated fact retains the exact source symbol for the ledger/tests.
FACT_SOURCES: dict[str, str] = {}


def fact(source: str):
    module, symbol = source.rsplit(".", 1)
    value = getattr(import_module(f"drawing_analyzer.{module}"), symbol)
    FACT_SOURCES[source] = source
    return value


def n(source: str) -> str:
    return f"{fact(source):,}"


@dataclass(frozen=True)
class Paragraph:
    text: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Note:
    title: str
    text: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Bullets:
    items: tuple[str, ...]
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Contrast:
    leaves: str
    stays: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Diagram:
    svg: str
    description: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class Links:
    items: tuple[tuple[str, str], ...]
    refs: tuple[str, ...]


RUNTIME_ROWS = ("You do", "What runs", "What is sent", "AI involved", "Bounded by")


@dataclass(frozen=True)
class Runtime:
    id: str
    title: str
    trigger: str
    runs: str
    sent: str
    ai: str
    bound: str

    @property
    def refs(self):
        return (self.id,)

    @property
    def rows(self):
        return tuple(zip(RUNTIME_ROWS, (self.trigger, self.runs, self.sent, self.ai, self.bound)))


@dataclass(frozen=True)
class Section:
    id: str
    kicker: str
    title: str
    blocks: tuple


DIAGRAM_DESCRIPTION = (
    "Your computer reads selected drawings and specifications, renders images, and writes local review files. "
    "Approved analysis and sent chat questions connect to Anthropic; its optional server web tools reach other websites. "
    "A dashed automatic update connection reaches GitHub and redirects. A dashed optional installer connection reaches "
    "the HTTPS host named by the manifest. Explicit further-reading links open in your browser. "
    "Batch results use a provider-supplied results URL. Desktop provider and proxy settings can change the route."
)

# Trusted inline SVG, shared with the native Canvas renderer. Its deliberately
# tiny vocabulary (rect/line/text) needs no SVG package, raster image or font.
BOUNDARY_SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 360" role="img" aria-label="{escape(DIAGRAM_DESCRIPTION, quote=True)}">
<rect x="10" y="10" width="700" height="340" rx="14" fill="none" stroke="currentColor"/>
<rect x="30" y="100" width="210" height="130" rx="10" fill="none" stroke="currentColor"/>
<text x="45" y="124">Your computer</text><text x="45" y="150">Selected PDFs / specs</text>
<text x="45" y="176">Local checks + exports</text><text x="45" y="202">Key + caches + logs</text>
<line x1="240" y1="125" x2="340" y2="125" stroke="currentColor"/>
<text x="250" y="110">Approved run</text>
<rect x="340" y="85" width="340" height="70" rx="8" fill="none" stroke="currentColor"/>
<text x="355" y="110">Anthropic API + batch results URL</text><text x="355" y="136">Images / text / sent chat context</text>
<line x1="510" y1="155" x2="510" y2="185" stroke="currentColor" stroke-dasharray="6 4"/>
<text x="355" y="204">Provider web search / fetch → websites</text>
<line x1="240" y1="225" x2="340" y2="265" stroke="currentColor" stroke-dasharray="6 4"/>
<text x="350" y="260">Automatic: GitHub manifest + redirects</text>
<text x="350" y="286">Optional: manifest's installer HTTPS host</text>
<text x="45" y="325">Optional browser links · provider / proxy overrides can change routes</text>
</svg>'''


def engine_rows() -> tuple[tuple[str, ...], ...]:
    """Resolved models/settings now; shipping defaults are identified separately."""
    from . import citation_check, critique, cross_qc, focus, investigate
    from . import prose_harvest, review_planner, set_identity, synthesis, verify
    from .core import api_config as cfg

    def row(job, model, effort, cap, why):
        return (job, f"{model}; {effort} reasoning; up to {cap:,} output tokens", why)

    return (
        row("Sheet digest", cfg.REVIEW_MODEL_DEFAULT, fact("digest.DEFAULT_DIGEST_EFFORT"),
            fact("digest.DEFAULT_DIGEST_MAX_TOKENS"), "Read page pictures and selectable text; runs at Anthropic."),
        row("Critique", critique.critique_model(), fact("critique.DEFAULT_CRITIQUE_EFFORT"),
            fact("critique.DEFAULT_CRITIQUE_MAX_TOKENS"), "Look again for problems at Anthropic; repeated reads are compared."),
        row("Identity", set_identity.default_identity_model(), fact("set_identity.DEFAULT_IDENTITY_EFFORT"),
            fact("set_identity.DEFAULT_IDENTITY_MAX_TOKENS"), "Suggest discipline and governing context from bounded text; advisory."),
        row("Review plan", review_planner.default_review_plan_model(), fact("review_planner.DEFAULT_PLAN_EFFORT"),
            fact("review_planner.DEFAULT_PLAN_MAX_TOKENS"), "Propose this set's checklist at Anthropic; code bounds its structure."),
        row("Set overview", synthesis.default_synthesis_model(), fact("synthesis.DEFAULT_SYNTHESIS_EFFORT"),
            fact("synthesis.DEFAULT_SYNTHESIS_MAX_TOKENS"), "Summarize sheet digests at Anthropic, rather than reread source PDFs."),
        row("Focus report", focus.default_focus_model(), fact("focus.DEFAULT_FOCUS_EFFORT"),
            fact("focus.DEFAULT_FOCUS_MAX_TOKENS"), "Answer your focus from digests at Anthropic."),
        row("Cross-sheet QC", cross_qc.cross_qc_model(), cfg.default_effort_for_phase(cfg.PHASE_CROSS_QC),
            fact("cross_qc.DEFAULT_CROSS_QC_MAX_TOKENS"), "Compare sheet accounts at Anthropic; larger sets are split and reconciled."),
        row("Prose harvest", prose_harvest.harvest_model(), cfg.default_effort_for_phase(cfg.PHASE_HARVEST),
            fact("prose_harvest.DEFAULT_HARVEST_MAX_TOKENS"), "Turn unmatched prose items into structured findings at Anthropic."),
        row("Crop verification", verify.default_verify_model(), (cfg.effort_config_for(model=verify.default_verify_model(), phase=cfg.PHASE_VERIFICATION) or {}).get("effort", "provider-default"),
            fact("verify.DEFAULT_VERIFY_MAX_TOKENS"), "Judge visible evidence at Anthropic; a crop verdict is still a model judgment."),
        row("Investigation", investigate.investigation_model(), cfg.default_effort_for_phase(cfg.PHASE_INVESTIGATION),
            fact("core.api_config.INVESTIGATION_OUTPUT_CAP"), "Ask for bounded extra drawing evidence at Anthropic."),
        row("Citation check", citation_check.citation_model(), cfg.default_effort_for_phase(cfg.PHASE_CITATION),
            fact("citation_check.DEFAULT_CITATION_MAX_TOKENS"), "Research claims with Anthropic's server web tools."),
        row("Report Ask-AI", cfg.CHAT_MODEL_DEFAULT, "high (when supported)", cfg.model_capabilities(cfg.CHAT_MODEL_DEFAULT).max_output_tokens,
            "Answer from the full report, history and tools at Anthropic; requests leave your browser."),
        ("Local machinery", "Python, PDF readers, Decimal arithmetic, browser tools; no model",
         "Render, search, compare, label and export on your computer."),
    )


def runtime_cards() -> tuple[Runtime, ...]:
    engines = engine_rows()
    ai_by_job = {r[0]: r[1] for r in engines}

    def ai(*jobs):
        return "; ".join(f"{job}: {ai_by_job[job]}" for job in jobs) + ". Adaptive thinking on supported models; temperature unspecified."

    def card(id, title, trigger, runs, bound, sent="Nothing.", model="None."):
        return Runtime(id, title, trigger, runs, sent, model, bound)

    local = "Local state only; no API charge."
    export = "Cancel writes nothing. A selected existing destination can be overwritten; export does not undo paid analysis."
    retry = f"Transient app retries: {n('digest.DEFAULT_DIGEST_MAX_RETRIES')} beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling."
    return (
        card("U01", "Add drawings", "Browse for PDFs or drop files.", "Filter extensions, deduplicate path strings, count readable pages and refresh the estimate; profile suggestions may run locally.", "Unreadable PDFs can be absent from the preview count; the actual run inventories rejections. Picker Cancel keeps the selection."),
        card("U02", "Set your desktop key", "Type/paste a key; press Return or leave the field.", "Normalize the value in memory. On finishing an edit, save to a tested OS credential store; ask before a plaintext fallback. Analyze snapshots its own key.", "Declining plaintext storage leaves a session key. Clearing the field does not delete a previously saved credential. Local storage has no API charge."),
        card("U03", "Show the desktop key", "Show / Hide beside the key.", "Change field masking; no validation request.", local),
        card("U04", "Open a reference", "Get an API key, or an external help link.", "Open built-in help or ask your OS browser to follow the selected link.", "Browser privacy, cookies and further navigation are outside the app; no AI request is initiated by the link handler.", "For a link, its URL goes to your browser and the destination; the app does not append your project or key."),
        card("U05", "Write your focus", "Edit Per-run focus; open/close its larger editor, including Escape.", "Synchronize the text boxes; update the local estimate. Ordinary text editing and available editor undo operate on this text.", "Edits alone do not send text. Analyze snapshots the text; there is no undo of an analysis or project save/load."),
        card("U06", "Attach specifications", "Upload spec documents…; accept the warning and choose files.", "Extract text locally from PDF, DOCX, TXT or MD on a worker. Replace the loaded spec context and report errors/truncation.", f"Per-file and combined prompt budget: {n('spec_documents.SPEC_FILE_CHAR_BUDGET')} / {n('spec_documents.SPEC_TOTAL_CHAR_BUDGET')} characters. No OCR for scanned spec PDFs. Cancel keeps existing context; extraction is not a currency/completeness check."),
        card("U07", "Choose QC Markups", "Toggle QC Markups.", "Select the exhaustive stack for your next run and enable its sub-options; update a local cost estimate.", "Off by default. It starts paid QC only after Analyze and cost confirmation; failures can leave partial output."),
        card("U08", "Restrict the ink", "Verified & deterministic only.", "Select which statuses may be drawn in the next QC run.", "Off by default. It filters ink, not the ledger, and does not certify the allowed findings as correct."),
        card("U09", "Include rejected findings", "Include rejected (grey).", "Select whether rejected findings appear as grey/struck annotations in the next QC run.", "Off by default. A rejected model verdict is not a human decision; the index keeps its accounting."),
        card("U10", "Choose the local audit", "Reference audit.", "Enable text auditors for the next analysis. QC Markups includes them already.", "The auditors add zero API calls. Analyze still runs a paid digest; this checkbox is not an offline analysis mode."),
        card("U11", "Choose the queue", "Economy, Hybrid or Fast.", "Economy batches digest and critique; Hybrid sends digest now and batches critique; Fast sends both now. Recalculate the estimate locally.", "Economy is the GUI default. Other QC stages still use real-time calls; the transport choice is not a run spending cap."),
        card("U12", "Keep tile images", "Save tile images + per-tile notes.", "Tell the next run to retain rendered tiles for Export All, including rerendering warm cached sheets.", "Off by default. Rerendering adds local work and disk use; it alone does not make an extra model call."),
        card("U13", "Choose a checklist", "Select/deselect a review profile.", "Record your manual choice, which takes precedence over local auto-suggestions; snapshot profiles for the next critique.", "No built-in profiles ship by default. User Markdown profiles change model instructions when the next QC run is approved."),
        card("U14", "Choose key embedding", "Embed API key in HTML report.", "Set the export option that writes the key literally into generated HTML.", "Off by default. The exported file becomes a credential if enabled; Forget key cannot remove that literal. Ask-AI still requires network access."),
        card("U15", "Clear the desktop session", "Clear.", "Reset selected drawings, specs, context, profile choices and activity display.", "Disabled while analyzing. It does not erase the saved key, cache, diagnostic file, browser chat, old exports or temp evidence."),
        card("U16", "Start the review", "Analyze Drawings, then confirm the cost dialog.", "Snapshot key/files/focus/specs/options; start a daemon worker. The automatic cards below describe inventory through exportable results, with overlapping independent work.", "Declining sends no analysis request. Estimates are local approximations. There is no desktop Stop button or global spend cap; quitting is not guaranteed remote cancellation.", "Approved work sends page images/text, optional specs/focus/checklists, filenames/page labels and subsequent findings to Anthropic (or a configured desktop SDK endpoint).", ai("Sheet digest", "Set overview", "Focus report", "Identity", "Review plan", "Critique", "Cross-sheet QC", "Prose harvest", "Crop verification", "Investigation", "Citation check")),
        card("U17", "Save an HTML report", "Save HTML Report…; choose a filename.", "Build an HTML file with inline code/styles, findings and report text, optionally an embedded key; open it with your OS browser.", export + " Opening the report does not send an AI question."),
        card("U18", "Save reviewed PDFs", "Save Reviewed PDF(s)…; choose a folder.", "Copy reviewed files from temporary work to the selected folder; report missing files and per-file copy failures.", export + " Earlier successful copies remain if a later copy fails."),
        card("U19", "Export the audit record", "Export All…; choose a folder.", "Stage report, Markdown, findings, source text, evidence, reviewed PDFs, optional tiles, logs and manifests on a worker; hash artifacts and publish the folder; open the folder.", "Staging/publish errors use export rollback. This does not roll back API spending. Keep the exported folder because temp evidence may later be pruned."),
        card("U20", "Read diagnostics", "Open Diagnostics Log.", "Open the file/folder in your OS viewer or show its path if opening fails.", "Logs are local and pattern-redacted, not generally anonymized. File logging can be disabled by DRAWING_ANALYZER_DIAGNOSTICS."),
        card("U21", "Check for updates", "Check for Updates.", "GET the version manifest, compare versions and record the check time in local JSON. Show the result; do not install yet.", f"Manifest limit {n('core.updates.MAX_MANIFEST_BYTES')} bytes; socket timeout {fact('core.updates.DEFAULT_MANIFEST_TIMEOUT'):g} seconds. DRAWING_ANALYZER_DISABLE_UPDATE_CHECK also disables manual checks.", "Updater User-Agent/Accept and ordinary connection metadata go to GitHub/redirects, or DRAWING_ANALYZER_UPDATE_URL. No app-built project/key payload."),
        card("U22", "Download and install", "Download & Install, then accept Install update.", "Download to a partial file, compute SHA-256 (a file fingerprint), compare with the manifest, rename on success. Ask again before starting the installer and quitting.", f"Socket timeout {fact('core.updates.DEFAULT_DOWNLOAD_TIMEOUT'):g} seconds, with no total-time or byte ceiling. Failure removes the partial file. A hash from the same manifest is not an independent publisher signature. Analysis blocks the download trigger.", "GET to the manifest's HTTPS installer URL and redirect hosts; app sends no drawings or API key."),
        card("U23", "Defer an update", "Later.", "Close the update offer.", local + " No installer starts."),
        card("U24", "Skip an update", "Skip this Version.", "Write the skipped version into update_check.json and close the offer.", "Automatic offers suppress that version; manual checks can show it again. No install or API charge."),
        card("U25", "Dismiss a downloading update", "Close the update window during download.", "Mark completion as dismissed and destroy the window; the download worker continues.", "This does not abort the transfer. A verified installer can remain cached; completion will not start it or show an install prompt.", "The already-started GET to the installer host can continue."),
        card("U26", "Read help and the dossier", "How to use / How it works / Why trust it? / About; dossier button; contents; Close or Escape.", "Render local content. The dossier stacks over Why trust it; contents move within the same document. Closing returns focus to its opener.", "The trust surfaces load no external assets. One Escape closes the top trust dialog; the lower topic stays open."),
        card("U27", "Expand a desktop section", "Click a section's caret/header.", "Show/hide the same local controls and refresh their summaries.", local),
        card("U28", "Quit the desktop app", "Close the main window; confirm Quit anyway if busy.", "Destroy the window and end daemon work when the process exits; reject the prompt to keep working.", "In-memory results can be lost. Already accepted API work can remain billed/running; quitting does not promise batch cancellation or deletion of temporary evidence."),
        card("U29", "Browse the report", "Search/filter/sort; group repeats; contents/sheet/evidence/PDF links; expand/collapse.", "Search report text, filter rows, sort and navigate locally. Evidence/PDF links open referenced files; external citation links open websites.", "Filters can hide findings without removing them. PDF/evidence links need the adjacent files and a viewer; HTTPS links are not authority/privacy checks.", "Nothing for local browsing. A clicked external citation URL goes to that website via your browser."),
        card("U30", "Copy report text", "Copy all.", "Copy raw report Markdown to the clipboard, with a local fallback if the clipboard API fails.", "No API call. Clipboard contents can be read by your other software or OS clipboard sync."),
        card("U31", "Open or close Ask-AI", "Ask AI; panel ×; reopen.", "Show/hide the report's chat panel and restore available local state.", "Closing the panel is not Stop. It can leave a sent question running."),
        card("U32", "Choose the report's key", "Save key / Return; Change key; Use the report's key.", "Keep your entered key in memory and best-effort sessionStorage (tab-scoped browser storage). Your entered key takes precedence over an embedded key.", "No authentication request until Send. Local HTML files in the same tab can share sessionStorage; browser recovery may persist tabs. Use a trusted tab or a separate HTTPS origin."),
        card("U33", "Forget the report key", "Forget key.", "Remove the entered key from memory and sessionStorage; fall back to an embedded author key if the file has one.", "An embedded key remains in HTML. Remove it by regenerating/deleting the file, and revoke it with its provider if exposed. This does not erase transcripts."),
        card("U34", "Show the report key", "Show / Hide in the chat key form.", "Change the field's masking locally.", local),
        card("U35", "Ask a question", "Send / Enter; starter question; select text and Ask AI about this; remove excerpt chip.", "Stage typed/selected text locally; sending streams an answer and may automatically run the tools and follow-ups in A18. Dismissing the chip only clears pending selection.", "No per-question cost confirmation or dollar ceiling. The full report and growing history are resent; no automatic history trimming. Provider context/output limits can cut off an answer.", "Nothing while composing/selecting/dismissing an excerpt. On Send, full report context, source labels, question/excerpt, conversation and tool results go to api.anthropic.com with the active tab/embedded key.", "Composing/selecting/dismissing: None. Sent questions: " + ai("Report Ask-AI")),
        card("U36", "Stop a chat answer", "Stop.", "Latch a turn stop, abort the current browser fetch, flush received text, and prevent new follow-up requests after the handler checks the stop.", "Work accepted by Anthropic remains potentially billed; abort is not server-side rollback. Local tools already running may finish; interrupted usage can be incomplete.", "No new request from Stop; the accepted remote request may still run."),
        card("U37", "Start a new chat", "New chat.", "Abort the current fetch, invalidate its late callbacks, clear history/display and erase the stored transcript for this report.", "New chat erases the stored browser copy; it does not delete saved JSON/PDF copies or reverse spend. The key can remain."),
        card("U38", "Save a conversation", "Save in Ask-AI.", "Serialize conversation and tool results to chat_history.json for browser download; scrub recognized sk-ant- key patterns.", "The saved file is not capped by the browser autosave limit. It contains project text; it is outside the sealed run manifest. Pattern scrubbing is not general secret detection."),
        card("U39", "Load a conversation", "Load; choose a saved JSON file.", "Read and validate transcript structure/report identity, normalize unfinished exchanges, replace history, render with safe text nodes and save local state. Recorded tools are displayed, not reexecuted.", "Cancel keeps history. A loaded transcript can be false or malicious text and will be included in a later sent question; validation does not authenticate its claims."),
        card("U40", "Print a conversation", "PDF in Ask-AI; choose print/save or Cancel.", "Temporarily prepare the chat view for the browser print dialog, then restore display.", "Local browser/OS print rules apply, including any remote printer or sync you configured. The app does not issue a model request."),
        card("U41", "Arrange the chat panel", "Drag/resize panel or message box; expand composer; double-click to reset.", "Change layout and save geometry in browser local storage.", "Local storage has no app expiry. Browser policy controls retention; layout does not change model settings."),
        card("A01", "Local work at startup", "You launch the app; no extra click.", "Start/reset pattern-redacted diagnostics; load an environment key once and remove that variable from this process; otherwise read/repair keyring or migrate matching legacy key files; discover Markdown profiles.", f"Logs rotate at {n('diagnostics._MAX_BYTES')} bytes with {n('diagnostics._BACKUP_COUNT')} backups and reset next launch. Key migration can delete matching plaintext files; unrelated files remain. No model runs."),
        card("A02", "Automatic update check", "The startup timer runs without a click.", "If enabled and the local throttle allows, perform the same manifest check as U21; record successes or failures and show an available unskipped update.", f"Default throttle {n('core.updates.DEFAULT_MIN_INTERVAL_DAYS')} day(s). Set DRAWING_ANALYZER_DISABLE_UPDATE_CHECK=1 to disable. No automatic download/install.", "Same GitHub/redirect or overridden HTTPS manifest route as U21; no project/key in the app-built request."),
        card("A03", "Local selection helpers", "You change files/options or finish spec extraction.", "Count pages and estimate costs locally. When user profiles exist, a serialized background text scan suggests checklists and captures geometry for a sharper estimate; stale scans are ignored.", "Default install has no profiles, so this profile preflight normally does not run. An estimate is not an exact token count or a file-validity guarantee."),
        card("A04", "Inventory, cache and rendering", "An approved analysis worker starts.", "Inventory selected sources and errors, assign identities/hash bytes, look up persistent caches; render misses sequentially and extract selectable text without existing annotations. Library token-count helper is not called by this pipeline.", f"Configured input guards: {n('source_registry.DEFAULT_MAX_FILES')} files / {n('source_registry.DEFAULT_MAX_SHEETS')} sheets (DRAWING_ANALYZER_MAX_FILES / DRAWING_ANALYZER_MAX_SHEETS). Default grid {n('tiling.DEFAULT_GRID_ROWS')}×{n('tiling.DEFAULT_GRID_COLS')}, {fact('tiling.DEFAULT_OVERLAP_FRAC'):.0%} overlap; prompt text cap {n('render.SHEET_TEXT_MAX_CHARS')} characters with truncation disclosure. Near-blank suppression is opt-in, not default."),
        card("A05", "Uploads, queue and recovery", "An approved Economy/Hybrid run needs batch images/results.", "Upload images on a bounded pool; share uploaded IDs for repeated reads; submit Message Batches, poll progress, harvest finished reads, attempt cancellations and submit recoverable follow-ups. Delete released image IDs best effort, sometimes in a background thread.", f"Upload workers {n('file_upload.DEFAULT_UPLOAD_WORKERS')}, status retries {n('file_upload.DEFAULT_UPLOAD_MAX_RETRIES')}; batch elapsed {n('batch_digest.DEFAULT_BATCH_MAX_ELAPSED_HOURS')} hours, resubmit rounds {n('batch_digest.DEFAULT_MAX_BATCH_RESUBMIT_ROUNDS')}. Poll {n('batch_digest.DEFAULT_POLL_INTERVAL_SECONDS')}–{n('batch_digest.DEFAULT_POLL_MAX_INTERVAL_SECONDS')} seconds; consecutive-error bound {n('batch_digest.DEFAULT_MAX_CONSECUTIVE_POLL_ERRORS')}; initial/later stall {fact('batch_digest.DEFAULT_FIRST_BATCH_STALL_TIMEOUT_SECONDS') // 60}/{fact('batch_digest.DEFAULT_BATCH_STALL_TIMEOUT_SECONDS') // 60} minutes. DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS, DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS and DRAWING_ANALYZER_BATCH_STALL_TIMEOUT_MIN change these. Expiry is not a guaranteed erasure; failed cancel/delete can leave provider work/files. No silent switch to full-rate recovery.", "PNG bytes and bare image filenames, request context and file IDs to the desktop provider; polling/cancel/delete IDs to it; results downloaded from its supplied results_url.", "Uploads, polling, cancel and delete: None. Submitted/recovered items run " + ai("Sheet digest", "Critique")),
        card("A06", "Read each sheet", "The analysis has a sheet cache miss or a recoverable read.", "Send overview/tiles and bounded text plus prompt/focus/specs; parse finished findings/claims apart from prose. Transient errors/output limits may retry; supported real-time models request a server refusal fallback.", f"Up to {n('digest.MAX_FINDINGS_PER_SHEET')} parsed findings and {n('digest.MAX_CLAIMS_PER_SHEET')} numeric claims per sheet. Output retry ceiling {n('digest.MAX_TOKENS_RETRY_CEILING')} tokens, model-clamped. {retry} DRAWING_ANALYZER_MODEL changes the default model; DRAWING_ANALYZER_REFUSAL_FALLBACK=0 disables fallback. A fallback-specific rejection retries without that feature.", "Page PNGs or file references, bounded text, filename/page label, focus/spec context to the desktop provider. Prompt tags separate input from instructions but do not guarantee immunity to malicious input.", ai("Sheet digest")),
        card("A07", "Summarize the set and your focus", "Enough readable sheets exist; your focus is nonempty for a focus report.", "Send budgeted digests for synthesis and/or focus. These independent calls can overlap identity/planning/critique; assembly records results in a stable order.", f"Synthesis requires {n('synthesis.MIN_SHEETS_FOR_SYNTHESIS')} readable sheets; focus requires {n('focus.MIN_SHEETS_FOR_FOCUS')}. Budgeted input can omit tails; failures preserve sheet output and report errors. DRAWING_ANALYZER_SYNTHESIS_MODEL and DRAWING_ANALYZER_FOCUS_MODEL override routing. {retry}", "Budgeted model-authored sheet digests and focus, to the desktop provider.", ai("Set overview", "Focus report")),
        card("A08", "Identify the set and draft a plan", "QC Markups starts its identity/planning stages.", "Build a bounded text corpus, infer set context, union locally harvested adopted editions, then ask for specialist checklists; sanitize fields and convert plans to profiles.", f"Plan items bounded by DRAWING_ANALYZER_MAX_PLAN_ITEMS (default {n('review_planner._DEFAULT_MAX_PLAN_ITEMS')}). Advisory context can be wrong; failures do not suppress the whole review. DRAWING_ANALYZER_IDENTITY_MODEL and DRAWING_ANALYZER_REVIEW_PLAN_MODEL override models. {retry}", "Digest heads, bounded extracted-text/edition windows, inferred set identity, to the desktop provider.", ai("Identity", "Review plan")),
        card("A09", "Critique the sheets", "QC Markups enables critique.", "Read each sheet again with selected/model-authored profiles; reuse pixels/uploads where valid, rerender otherwise. Compare repeated findings and retain valid completed reads; recover eligible batch failures.", f"Default repeated reads {n('critique.DEFAULT_CRITIQUE_RUNS')}; DRAWING_ANALYZER_CRITIQUE_RUNS and DRAWING_ANALYZER_CRITIQUE_MODEL change them. Agreement is repeatability, not independent proof. Invalid/unfinished reads do not enter trusted results. {retry}", "Page images/text, focus/spec context and checklist instructions, to the desktop provider.", ai("Critique")),
        card("A10", "Compare across sheets", "QC Markups has enough readable sheets.", "Compare digest/text accounts in one request for small sets; split larger sets, validate shard evidence against source text, and reconcile compact facts. The small-set path relies on later anchoring rather than that shard admission gate.", f"Small-set threshold {n('cross_qc.MAX_SHEETS_SINGLE_CALL')}; per-sheet prompt text {n('cross_qc._TEXT_LAYER_BUDGET')} characters. Findings cap {n('cross_qc.DEFAULT_CROSS_QC_MAX_FINDINGS')}, map facts {n('cross_qc.DEFAULT_MAP_MAX_FACTS')}, reconcile fact budget {n('cross_qc.MAX_FACTS_PER_RECONCILE')}, pair-call ceiling {n('cross_qc._MAX_RECONCILE_PAIR_CALLS')}. Omitted/refused items are limits on coverage. DRAWING_ANALYZER_CROSS_QC_MODEL changes routing. {retry}", "Digests, bounded sheet text, source handles, inferred context and then compact facts, to the desktop provider.", ai("Cross-sheet QC")),
        card("A11", "Local checks and finding assembly", "Your selected audit/QC stages reach the ledger.", "Check references, naming, title blocks, sheet indexes and editions; check transcribed numeric claims using Decimal, an arithmetic component that avoids binary rounding. Ground operands AND the stated relationship before deterministic arithmetic status; anchor quotes, merge conservatively and assign QC numbers.", "Host checks can be wrong if extraction/identity is wrong or a rule does not fit the drawing. Tile/unanchored locations are not exact text matches. Model-origin operands that fail grounding remain uncertain; not every possible equation is discovered."),
        card("A12", "Mirror prose into findings", "QC stages examine digest, synthesis and focus prose.", "Filter non-findings locally, match existing ledger entries; ask a model to structure residual items. Unstructured/degraded items and accounting remain visible where supported.", f"Source-text cap {n('prose_harvest._HARVEST_TEXT_CAP')} characters. Filtering/matching can miss or misclassify prose; this is not a completeness guarantee. DRAWING_ANALYZER_HARVEST_MODEL changes the model. {retry}", "Residual item and bounded on-sheet text/context to the desktop provider.", ai("Prose harvest")),
        card("A13", "Recheck visible evidence", "QC reaches an eligible anchored finding.", "Render crops, save and hash evidence before requesting a verdict; replay eligible cached verdicts or send the crop(s)/claim. Validate status; schema rejection can fall back to ordinary JSON parsing.", f"Default crops {PINNED_FACTS['verify_dpi']} DPI (dots per inch). DETERMINISTIC entries skip model verification; unlocatable findings cannot get ordinary crop confirmation. CONFIRMED becomes VERIFIED, CONTRADICTED becomes REJECTED, NOT_VISIBLE/invalid/failed stays UNCERTAIN. DRAWING_ANALYZER_VERIFICATION_MODEL (legacy DRAWING_ANALYZER_VERIFY_MODEL) changes routing. {retry}", "Saved crop image(s), finding text/quote and framing to the desktop provider.", ai("Crop verification")),
        card("A14", "Investigate uncertain findings", "QC has eligible uncertain findings and remaining investigation slots.", "Ask for extra crops/text searches/overviews from loaded sheets. Validate inputs, save/hash images and append tool results to follow-up requests. Replayed cached investigations must reproduce evidence hashes. Withdraw tool permission at the evidence limit.", f"Default evidence requests {n('investigate._DEFAULT_MAX_ROUNDS')}; pause resumes {n('investigate._MAX_PAUSE_RESUMES')}; advisory task budget {n('investigate._DEFAULT_TASK_BUDGET_TOKENS')} tokens. Default run slots min({n('investigate._DEFAULT_MAX_INVESTIGATIONS')} + floor(sheets/{n('investigate._INVESTIGATION_SHEETS_PER_EXTRA')}), {n('investigate._MAX_INVESTIGATIONS_CEILING')}). DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS, DRAWING_ANALYZER_INVESTIGATION_MAX_FINDINGS and DRAWING_ANALYZER_INVESTIGATION_TASK_BUDGET override these; the findings override can exceed the default ceiling. Budget rejection removes the advisory token budget, but host evidence/iteration limits remain. Failure/exhaustion does not mean rejected. {retry}", "Finding, initial saved crop, bounded loaded-sheet index, requested local evidence and accumulated tool conversation to the desktop provider.", ai("Investigation")),
        card("A15", "Check cited sources", "QC has unique cited references or plan references to check.", "Split distinct claims into complete chunks; ask server-side web_search/web_fetch to examine adopted/current editions; parse assessments, require claim coverage and cache verdicts with a reuse TTL (validity period).", f"Claims/request {n('citation_check._MAX_CLAIMS_PER_REQUEST')}; searches/fetches per request {n('citation_check._WEB_SEARCH_MAX_USES')}/{n('citation_check._WEB_FETCH_MAX_USES')}; fetched text {n('citation_check._WEB_FETCH_MAX_CONTENT_TOKENS')} tokens; pause resumes {n('citation_check._MAX_PAUSE_RESUMES')}; cache validity {n('citation_check._DEFAULT_CITATION_TTL_DAYS')} days. DRAWING_ANALYZER_CITATION_MODEL, DRAWING_ANALYZER_WEB_SEARCH_MAX_USES, DRAWING_ANALYZER_WEB_FETCH_MAX_USES and DRAWING_ANALYZER_CITATION_TTL_DAYS tune these. Limits refresh per request/resume; not a whole-run search ceiling. Paywalls/incorrect editions can leave uncertain checks. {retry}", "Code references, claims/quotes and edition context to the desktop provider; model-selected queries/URLs to websites via provider tools. Queries are not guaranteed free of project information.", ai("Citation check")),
        card("A16", "Write and check the annotations", "QC Markups reaches the output stage.", "Write new reviewed PDFs in temporary work; draw according to status/options and plan index entries. Stamp mandatory annotation components, reopen PDFs and reconcile saved receipts with the plan.", "Missing/failed/duplicate/unexpected required marks make coverage INCOMPLETE, reflected in naming/report. This proves planned marks were found, not that every engineering problem was found or every annotation is visually ideal."),
        card("A17", "Remember the report session", "You open a report or a chat turn completes/stops/fails.", "Restore locally saved history and layout; save updated transcript after settled turns, stripping recognized sk-ant- key patterns. Replay uses safe display paths and does not rerun past tools. Local timers animate/search the interface.", f"Browser autosave ceiling {PINNED_FACTS['chat_storage_chars']:,} serialized characters; failure warns to Save. Browser local storage has no app expiry and local HTML files can share its origin. New chat clears this report's stored copy; file copies remain."),
        card("A18", "Automatic chat follow-ups", "Your sent question returns tool requests or a paused server turn.", "Anthropic can search/fetch websites. Browser tools read findings/summary, navigate/filter/highlight and calculate; requested tools run in parallel, then results go back for a new streamed answer. Received/model text is displayed as data.", f"Server continuation limit {PINNED_FACTS['chat_continuations']}; forced text close starts when local tool rounds exceed {PINNED_FACTS['chat_tool_rounds']} (the comparison allows an extra tool-bearing round). Search/fetch budget {PINNED_FACTS['chat_searches']}/{PINNED_FACTS['chat_fetches']} and fetch-text cap {PINNED_FACTS['chat_fetch_tokens']:,} tokens reset on each request. No app fetch timeout, dollar ceiling, automatic history truncation, SDK retry or refusal-fallback parameter. Stop prevents later follow-ups after its checks; tools already started may finish.", "Full report, question/history and tool results to api.anthropic.com; provider tools can send model-chosen queries/URLs to other sites.", ai("Report Ask-AI")),
        card("A19", "Clean up run work", "A later analysis starts; a run exits normally or through cleanup.", "Prune stale drawing_qc_* temp trees at run entry; keep recent/uncertain trees. Remove this run's render spool on exit and release retained uploaded image IDs best effort.", f"Default stale age {fact('pipeline._WORKDIR_MAX_AGE_HOURS'):g} hours; DRAWING_ANALYZER_WORKDIR_MAX_AGE_HOURS=0 disables pruning. Temp evidence is not erased on close; export promptly. Remote deletion failures are swallowed, and files still needed by uncanceled batches may be kept.", "Released file IDs for deletion to the desktop provider. Local pruning sends nothing."),
    )


def sections() -> tuple[Section, ...]:
    from .core import api_config as cfg, pricing, updates
    opus, sonnet = cfg.MODEL_OPUS_55, cfg.MODEL_SONNET_55
    op, so = pricing.price_for(opus), pricing.price_for(sonnet)
    refs_all = tuple(f"N{i:02d}" for i in range(1, 7))
    return (
        Section("answer", "Start here", "The short answer", (
            Note("Your sources and the model's proposals are different", "You supply drawings, specifications and optional focus/checklists. A model is the provider's AI system; it authors report prose. Findings record origin tags and evidence/status separately. A tag tells you which channel supplied a finding, not whether it is right.", ("A06", "A11", "A12")),
            Note("Approving work starts automatic follow-ups", "No independent AI review starts at launch. Update checks and local startup work do. Once you approve Analyze or send a chat question, model calls, retries, tool rounds and cleanup can continue without another click; the runtime cards name them.", ("A01", "A02", "A05", "A18")),
            Note("You can inspect the evidence, not rederive every judgment", "Local arithmetic, anchors and receipt counts can be checked against source text/images and exports. Model judgments are probabilistic: you can review their evidence, but repeating the request need not reproduce the judgment. Human sign-off remains your job.", ("A11", "A13", "A16", "U19")),
        )),
        Section("origins", "Provenance", "Where the output comes from", (
            Paragraph("A hash is a fingerprint of saved file bytes, not a truth certificate. JSON is a structured text format you can open in a text editor; Markdown is readable text with heading/list notation. Decimal means base-ten arithmetic. SQLite is the local database format used by the cache, which stores results for reuse.", ("A04", "A11", "U19")),
            Table(("Origin", "What it actually is", "How you can tell"), (
                ("You", "Selected drawings/specs; typed focus; selected Markdown profiles.", "Drawing inventory/hashes, focus/configuration, profile snapshots and sheet_text files in Export All. Attached specifications are not archived as separate source files/text with original-file hashes; keep your own copies."),
                ("Built-in rules", "Text auditors, grounded Decimal arithmetic, location/merge/numbering rules and annotation templates.", "Finding origin tags, operand_origin/computation_method, anchor and markup receipt fields; source code."),
                ("Model proposal", "Sheet prose, findings, identity, authored review plan, summary/focus, crop/citation judgments and chat answers.", "Prose sections, finding sources, review_plan.md/profile source, verification/citation fields and Ask-AI labels."),
                ("Retrieved web material", "Search snippets/fetched pages selected by server tools; relevance/edition may be wrong.", "Citation assessments/evidence URLs and chat citation/tool chips; not every intermediate provider step is logged."),
                ("Local cache", "A prior result whose cache identity/reuse rules match; origin remains its original channel.", "Cache-hit/transport records in run usage; cache SQLite payloads. A cache hit is not a new independent review."),
            ), ("A04", "A06", "A08", "A11", "A13", "A15", "A18", "U19")),
            Note("Things that are not happening", "The code does not add a private drawing corpus, a shared app account, an app-hosted cloud workspace, or a training job. It does supply built-in prompts/rules, and models bring their pretrained knowledge; optional web tools add outside material. Provider retention/training policy cannot be verified or enforced by this desktop code. Read your provider agreement before sending restricted work.", ("N01", "N05", "A06")),
        )),
        Section("engine", "Components", "What the engine actually is", (
            Paragraph(f"Shipping model defaults are {opus} for review work and {sonnet} for identity, harvest, crop verification, citations and report chat. The table shows the models resolved in this process; environment variables can change them. A token is a unit the provider uses to count text/image processing. Output caps include reasoning, not just visible words.", ("A06", "A07", "A08", "A09", "A10", "A12", "A13", "A14", "A15", "A18")),
            Table(("Job", "Model or component", "Why"), engine_rows(), ("A06", "A07", "A08", "A09", "A10", "A11", "A12", "A13", "A14", "A15", "A18")),
            Paragraph("Supported default models use adaptive thinking: the provider chooses reasoning length within the request cap. Requests do not set temperature, a control some models use for sampling variation. Overrides can remove unsupported thinking/effort/web tools and clamp output budgets; the table states requested stage caps, not a promise of usable output. The desktop SDK (the provider's Python client) uses its configured endpoint; the report always targets the fixed Anthropic API, its request service.", ("N01", "A06", "A18")),
            Note("Automatic fallback is part of the engine", f"Supported desktop real-time requests ask for a server refusal fallback by default. The registered alternatives include {cfg.MODEL_OPUS_5}, {cfg.MODEL_OPUS_48} and {cfg.MODEL_SONNET_5}; batch recovery uses declared routes too. DRAWING_ANALYZER_REFUSAL_FALLBACK=0 disables the real-time feature. The ledger may price the requested model even when a fallback served the request. The report chat does not request that feature.", ("A05", "A06", "A18")),
        )),
        Section("boundary", "The boundary", "What leaves your computer, and where it goes", (
            Diagram(BOUNDARY_SVG, DIAGRAM_DESCRIPTION, refs_all),
            Contrast(f"Approved analysis sends page PNGs (image files), bounded source/spec text, bare filenames/page labels, focus/checklists and later findings/evidence to {PINNED_FACTS['api_host']}. Report Send transmits the full report and accumulated history, with the active key in request headers. Desktop ANTHROPIC_BASE_URL and proxy configuration can change the route. Batch collection downloads the SDK's provider-supplied results_url. Citation/chat server web tools may send project-derived queries to other websites. Updates request {updates._DEFAULT_MANIFEST_URL} plus redirect targets. Download uses the manifest's arbitrary HTTPS installer URL and redirects. Explicit external links open via your browser with its own cookies and network metadata.",
                     "The originals remain local during normal pipeline processing; their content travels as images/text. Rendering, source hashes, local auditors, arithmetic, anchoring, merging, annotations and exports run locally. Keys are loaded/stored locally but sent to authenticate the API. Cache/log/export/evidence/transcript files stay local unless you share/sync them or software outside this app does. Folder paths are not deliberately added as API metadata, but private details present in drawing/spec text or filenames travel with that content.", refs_all + ("A04", "U02", "U19", "A17")),
            Note("Routes are not a closed hostname list", "GitHub redirects, manifest-selected installer URLs, SDK results URLs, custom endpoints/proxies and provider web tools make a finite guaranteed hostname list impossible. No analytics/crash uploader, application server listener or external font/script fetch was found in the runtime code. This claim does not cover your OS, browser extensions or configured third-party integrations. The trust views themselves use local text, inline styles/code and an inline SVG.", refs_all),
            Paragraph("Clicked built-in help links can reach github.com, console.anthropic.com, privacy.anthropic.com, trust.anthropic.com, www.anthropic.com, www.gnu.org and www.linkedin.com. Citation/source links can reach other HTTPS websites. Your browser controls cookies, authentication, redirects and subsequent navigation.", ("N06",)),
        )),
        Section("runtime", "Runtime", "What runs when you click — and afterward", (
            Paragraph("Each card has the same rows. User cards name aliases that share the same effects; automatic cards describe work an earlier click or launch starts. ‘Nothing’ describes the app's own outbound payload for that step, not your OS/browser's independent activity. ‘None’ means that step does not generate a model request. API costs already incurred are not refunded by local failure, Clear or closing a window.", ("U15", "U28", "U36", "A01", "A05")),
            *runtime_cards(),
            Note("Layered bounds, not a run budget", f"The release SDK retries up to {PINNED_FACTS['sdk_retries']} times per request by default, beneath application retries. Default SDK timeouts are {PINNED_FACTS['sdk_connect_seconds']} seconds for connect and {PINNED_FACTS['sdk_read_seconds']} seconds for read/write/pool operations; they are not a run elapsed ceiling. A batch bound applies to its collection/recovery phase, not the entire review. Set-level and QC calls can overlap on worker pools; repeated errors or provider latency still lengthen a run. No application dollar cutoff exists.", ("N01", "A05", "A06", "A07", "A13", "A18")),
        )),
        Section("tools", "Blast radius", "What the AI may touch, and what it cannot", (
            Table(("Tool or capability", "What it can do", "Constraint"), (
                ("Digest / critique / summary / plan", "Propose text, structured findings and numeric claims.", "Code parses allowed fields/categories, bounds lists and binds references; it does not execute proposed code. Structure validation is not truth validation."),
                ("crop_region", "Request a rectangle on a loaded drawing.", f"Loaded-sheet lookup, finite/bounded rectangle and {n('investigate._MIN_CROP_DPI')}–{n('investigate._MAX_CROP_DPI')} DPI; evidence saved/hashed before sending."),
                ("find_text", "Search extracted words on loaded sheets.", f"Literal local text search; at most {n('investigate._MAX_FIND_TEXT_MATCHES')} matches; no arbitrary file path or shell command."),
                ("view_sheet", "Request a loaded sheet overview.", f"Known sheet lookup; overview at {n('investigate._VIEW_SHEET_DPI')} DPI. Bounded visible index {n('investigate._MAX_SHEET_INDEX_ENTRIES')}; allowed lookup still stays within loaded sheets."),
                ("web_search / web_fetch", "Research model-selected websites at Anthropic.", "Per-request use/content bounds and source-quality blocked domains; no promise queries exclude project information or sources are correct."),
                ("scroll_to_report / filter_report / highlight_term", "Move, reveal, filter or highlight this report in your browser.", "Fixed dispatch functions and report DOM (page elements); no arbitrary script evaluator. A tool can change what you see without changing finding truth."),
                ("query_findings / get_report_summary", "Read embedded structured records and run accounting.", "Local report data; bounded query return list. Returned content is sent in later tool rounds."),
                ("calculate", "Evaluate an arithmetic expression in report chat.", "Restricted parser for numbers/operators, not eval. Browser floating-point arithmetic differs from the review's Decimal checks and is not engineering validation."),
            ), ("A06", "A08", "A11", "A14", "A15", "A18")),
            Paragraph("These declared tools cannot run a shell (a system command interpreter), execute model-written code, choose arbitrary desktop files, or rewrite your input PDFs. Their evidence/rendering handlers do write local evidence and their report handlers can change your view. Network research is available through the named provider web tools; prompts alone are not a sandbox against misleading instructions in a drawing or transcript.", ("A14", "A15", "A18")),
        )),
        Section("terms", "Exact words", "What the key terms mean, exactly", (
            Note("Grounded — the exact claim", "A reported quote has passed a supported match/location rule against the relevant source text; the anchor records exact, fuzzy or character-stream matching, or reduced-trust tile fallback. It does not establish that the model's interpretation, code edition or missing-item allegation is correct.", ("A10", "A11")),
            Note("DETERMINISTIC — the exact claim", "A host rule produced the finding; arithmetic gains this status only after operand and relationship grounding. It does not mean the input text is accurate, every numeric relationship was checked, or a heuristic rule applies to your project.", ("A11",)),
            Note("VERIFIED / REJECTED — the exact claim", "A completed model crop verdict confirmed/contradicted the particular finding. Rejected findings remain accounted for in the ledger/index. Neither status is professional approval, independent proof, or a full-sheet inspection by a person.", ("A13", "A16")),
            Note("UNCERTAIN / UNVERIFIED / UNANCHORED — the exact claim", "UNCERTAIN means a check did not settle the claim; UNVERIFIED means no verification result ran for it; UNANCHORED describes missing supported location. These are different gaps, not synonyms for false. A quote/location failure does not necessarily mean deliberate hallucination.", ("A11", "A13")),
            Note("COMPLETE / INCOMPLETE — the exact claim", "COMPLETE is the roll-up of expected configured stage outcomes. Markup coverage counts required saved components found after reopening, and INCOMPLETE names missing/failed receipt coverage. Neither means every defect was found, every mark is readable, or the set is safe to issue.", ("A04", "A10", "A13", "A16")),
            Note("Secure — the exact claim", "Keys prefer a tested OS credential store; consent gates plaintext fallback. HTML uses escaping, safe text nodes, an HTTPS link policy and a Content Security Policy (browser rules restricting scripts/connections). This does not encrypt project artifacts/cache, certify vendor security, or prevent a model being misled.", ("U02", "U14", "A17", "A18", "N01")),
        )),
        Section("local", "No AI here", "The parts with no AI in them", (
            Bullets(("Choosing files, local spec extraction and cost estimation.", "PDF rendering/text extraction, source fingerprints, cache identity checks and local cache reads.", "Reference, naming, title-block, sheet-index and edition text rules; arithmetic once claims are supplied.", "Quote matching, conservative merging, QC numbering and local status/usage arithmetic.", "Annotation layout, reopen/receipt reconciliation, staging, hashes and exports.", "Report search/filter/sort/navigation, clipboard copy, transcript import/replay, layout and printing.", "Help, update version comparison and installer hashing (update fetch/download themselves need network)."), ("U01", "U06", "U19", "U26", "U29", "U30", "U39", "U40", "A04", "A11", "A16")),
            Note("What works disconnected", "You can read help and saved reports/PDFs, browse/filter their embedded content, extract local specs, inspect cache/exports, copy and print. There is no fully offline mode for a fresh model review: a missing cached result needs the provider. A warm cache can skip some calls, but is not an air-gapped guarantee. Reference audit inside Analyze still accompanies a digest. Ask-AI needs the API even if a key is embedded.", ("U10", "U14", "U26", "U29", "A04", "A06", "A18")),
        )),
        Section("privacy", "Safeguards", "Security and privacy, mechanism by mechanism", (
            Table(("Concern", "How it is handled"), (
                ("Desktop credential", "Environment key loaded once and removed from this process environment; run snapshots its own client. OS keyring is preferred after verified readback. Plaintext fallback requires consent; POSIX owner permissions are tightened. Clearing the input is not deleting the store."),
                ("Files at rest", "Config uses the platform's DrawingAnalyzer directory: drawing_analyzer_api_key.txt fallback (also read beside executable), logs/drawing_analyzer.log, update_check.json and updates/ installers. No app retention limit on installed credential/state/cached installers; inspect permissions and delete/revoke when appropriate."),
                ("Review cache", "~/.drawing_analyzer/drawing_digest_cache.json is SQLite despite its suffix. It holds project-derived results in readable payloads; no general expiry/encryption. DRAWING_ANALYZER_CACHE_PATH changes its location; DRAWING_ANALYZER_CACHE_PERSIST=0 disables default persistence. Citation TTL controls reuse, not erasure."),
                ("Profiles, specifications and temporary work", "User Markdown profiles live in ~/.drawing_analyzer/profiles (DRAWING_ANALYZER_PROFILES_DIR override). Attached spec text is kept in the desktop context and sent with approved work; Export All does not archive the original specifications as separate source artifacts. drawing_qc_* trees in system temp hold evidence/reviewed output and survive close until later pruning. Render spool is removed on run exit. Exported copies persist where you put them."),
                ("Browser credential and transcript", "Entered key: memory plus best-effort sessionStorage da-api-key. Transcript: local storage da-chat-tx-<reportId>; geometry too. Browser controls disk/profile recovery and same-origin exposure. Local HTML files can share storage. Forget key can fall back to an embedded author key; New chat erases the stored transcript, not saved files."),
                ("Logs and exports", "Diagnostics redacts recognized key/secret patterns; DRAWING_ANALYZER_DEBUG adds SDK detail. Run journal/export status strings scrub recognized secrets and private paths. Drawing/model content is not generally scrubbed; exports, cache, transcripts and evidence contain private project data. No app crash-upload path was found."),
                ("Remote file lifecycle", "Uploaded images are reused, then best-effort deleted after safe release; some failed cancellations retain files for still-running batches. Provider retention/backup/training handling is its contract, not a local guarantee. Check provider file/batch state when work is interrupted."),
                ("Untrusted input", "Model/file strings are escaped into HTML; streamed and loaded chat use text-node construction. Unsafe link schemes degrade to inert text; CSP restricts report connections/scripts. Imported tools do not replay. Prompt separation reduces ambiguity but does not prove resistance to prompt injection or certify suggestions."),
                ("Local exposure and updates", "No app HTTP server/listener is started. SDK/environment proxy settings can route traffic differently. Updater requires HTTPS and a matching manifest hash, but not a fixed host or independent signature; an untrusted custom manifest is an installer trust decision."),
            ), ("U02", "U14", "U15", "U22", "U32", "U33", "U37", "U39", "A01", "A04", "A05", "A17", "A19", "N01", "N03")),
        )),
        Section("money", "Money", "What is billed, estimated, and missing", (
            Paragraph("Anthropic bills the account for the active key; the app has no separate charge code. Desktop estimates use local page/image/text allowances and a price table. Report chat uses the reader's entered key, falling back to an embedded author key. Its spend is outside the analysis run ledger. Configured custom providers can have different terms.", ("U16", "U32", "A06", "A18", "N01")),
            Table(("Figure", "What it means"), (
                ("Price table", f"Effective {fact('core.pricing.PRICING_EFFECTIVE_DATE')}; {opus}: ${op.input_per_mtok:g} input / ${op.output_per_mtok:g} output; {sonnet}: ${so.input_per_mtok:g} / ${so.output_per_mtok:g}, per million tokens. The table is not live billing."),
                ("Batch / provider prompt cache", f"Eligible batch rates multiply by {fact('core.pricing.BATCH_DISCOUNT'):g}. Cache writes multiply base input by {fact('core.pricing.CACHE_WRITE_MULTIPLIER_5M'):g} for {fact('core.pricing.CACHE_TTL_5M')} or {fact('core.pricing.CACHE_WRITE_MULTIPLIER_1H'):g} for {fact('core.pricing.CACHE_TTL_1H')}; default-model read multipliers {op.cache_read_multiplier:g} / {so.cache_read_multiplier:g}. Local result reuse is separate from paid provider prompt caching."),
                ("Search surcharge", f"Table adds ${fact('core.pricing.WEB_SEARCH_COST_PER_USE')} per server search to analysis usage where reported. Chat's displayed estimate omits this surcharge; fetch content still consumes tokens."),
                ("Run usage", "Append-only records carry reported tokens, transport/model and calculated cost. Interrupted output can be unreported, so totals can be lower bounds. Failed attempts with missing usage are not a reliable zero-cost record."),
                ("Fallback discrepancy", "Some fallback models cost more than the requested default, but run pricing uses the requested model; an apparently precise total can understate the provider bill."),
                ("Estimate versus exact", "Provider-reported counts are exact for the usage fields actually received; locally estimated images/tokens and calculated dollar figures are estimates. The provider console/invoice settles money, including failed/stopped/remote-running work."),
            ), ("A04", "A05", "A06", "A15", "A18", "U36")),
            Note("A confirmation is not a spending stop", "Analyze asks before work begins. It does not enforce the estimate as a cap. Retries, repeated reads, citations and investigations can add spend automatically; chat has no cost-confirmation dialog. Quitting, Stop or an export failure does not roll back provider charges.", ("U16", "U28", "U35", "U36", "A05", "A14", "A15", "A18")),
        )),
        Section("limits", "Honesty", "What this does not do", (
            Bullets(("It does not certify code compliance, safety, design adequacy or a complete defect list. A fluent model can quote accurately and interpret incorrectly; compare the actual drawing and governing specification/code.", "It does not prove the specifications you attach are complete, current or applicable. The warning asks you to judge that; extracted text/truncation records cannot establish it.", "A wrong PDF text layer, raster-only page, faint linework or ambiguous quote can produce confident errors. Crops and location/status fields help you inspect them; extraction is not a guarantee against a wrong digit.", "Parsers, list/text caps, shard reconciliation limits and prose filtering can omit items. Partial/discard accounting explains recorded losses; it cannot count defects the model never proposed.", "Agreement between repeated reads is not independent validation. Crop/citation checks are also model judgments; missing context, paywalls and edition confusion can produce a confident wrong verdict.", "There is no desktop analysis Stop, resumable project save/load, application undo of a paid run, universal request transcript, or global dollar ceiling. Chat Stop and transcript Save/Load have narrower effects.", "Hashes prove saved bytes match a record, not that the claim is true or the record is authentic. COMPLETE and receipt coverage describe completed work, not professional sign-off.", "No warranty of correctness follows from this help or from the source license. Provider guarantees and data handling are matters for your own account/contract."), ("U06", "U28", "U36", "U38", "U39", "A04", "A06", "A09", "A10", "A11", "A12", "A13", "A15", "A16")),
        )),
        Section("audit", "The point", "Check it yourself", (
            Bullets(("Read Why trust it and this dossier without a connection: they remain local. In the saved report, show all findings and inspect origin/status, quote, location and rejected/index rows against the drawings.", "Click Open Diagnostics Log. You will see the local session trace; it resets at the next launch. For SDK request/retry details enable DRAWING_ANALYZER_DEBUG before launch, recognizing that debug detail is still private project data and may not be a complete request transcript.", "Use Export All, including for a failed run that returned a context. Open run.log and run_manifest.json: inspect input rejection/unread-page accounting, resolved configuration/models, stage outcomes, usage/transport, profile snapshots and artifact hashes.", "Open findings.json and markup_manifest.json in a text editor. Compare source tags, anchors, operand provenance, crop/citation verdicts and saved annotation receipts with the reviewed PDF. Open evidence PNGs and their request/investigation records: you can see the pixels/tools the recorded checks used.", "Save chat with Save and read chat_history.json. It contains questions, answers and tool results; it is not covered by the earlier run manifest. Inspect browser storage for persisted transcript/key/layout, then use New chat / Forget key and verify which copies remain.", "Compare usage with your provider console/invoice; inspect its batches/files if interrupted. You may see spend absent from a stopped stream's local record or from chat's search estimate. Recompute Decimal arithmetic from the printed equation rather than trusting a verdict.", "Disconnect the network and browse saved artifacts. Fresh misses and sent chat questions fail; local report navigation, copies, help and inspections work. Do not start a paid review just to test that a cached review might need the network.", "Inspect the source and claims ledger; compare your firewall/proxy log or browser Network panel during work you intended to run. Expect the API, automatic GitHub/redirect checks, optional installer URLs and explicit clicked links; provider web research is visible at the provider side, not as direct local connections to every website."), ("U19", "U20", "U29", "U33", "U37", "U38", "A05", "A11", "A13", "A14", "A15", "A18", "N01", "N02", "N03", "N04", "N05", "N06")),
            Links((
                ("Anthropic privacy policy and privacy center", "https://privacy.anthropic.com/"),
                ("Anthropic trust center", "https://trust.anthropic.com/"),
                ("Anthropic commercial terms", "https://www.anthropic.com/legal/commercial-terms"),
                ("Anthropic usage console", "https://console.anthropic.com/settings/usage"),
                ("Application docs and source", f"https://github.com/{updates.GITHUB_OWNER}/{updates.GITHUB_REPO}/blob/main/README.md"),
                ("Security mechanisms", f"https://github.com/{updates.GITHUB_OWNER}/{updates.GITHUB_REPO}/blob/main/SECURITY.md"),
                ("Claims ledger", f"https://github.com/{updates.GITHUB_OWNER}/{updates.GITHUB_REPO}/blob/main/docs/TRUST_CLAIMS.md"),
                ("Release page", updates._RELEASES_PAGE_URL),
            ), ("N06",)),
            Note("Still not convinced?", "Good. Use the output as a set of leads you can check. Read the source/evidence, keep uncertain items visible, verify significant claims yourself, and keep your own review record. If your project cannot be sent to your configured provider or its tools, do not approve the analysis or send chat questions.", ("U16", "U35", "A13", "N01", "N05")),
        )),
    )


def plain_blocks(block) -> tuple[str, ...]:
    """Selectable fallback text, also used by the existing HelpDocument API."""
    if isinstance(block, Paragraph):
        return (block.text,)
    if isinstance(block, Note):
        return (block.title, block.text)
    if isinstance(block, Table):
        return tuple(" · ".join(row) for row in (block.headers, *block.rows))
    if isinstance(block, Runtime):
        return (f"{block.id} · {block.title}", *(f"{label}: {value}" for label, value in block.rows))
    if isinstance(block, Bullets):
        return block.items
    if isinstance(block, Contrast):
        return ("Leaves your machine: " + block.leaves, "Stays on your machine: " + block.stays)
    if isinstance(block, Diagram):
        return (block.description,)
    if isinstance(block, Links):
        return tuple(label for label, _url in block.items)
    raise TypeError(type(block))


def render_html() -> str:
    """Portable companion page: identical content, one scroll, no asset fetches."""
    parts = []
    for section in sections():
        parts.append(f'<section id="{section.id}" aria-labelledby="title-{section.id}"><small>{escape(section.kicker)}</small><h2 id="title-{section.id}">{escape(section.title)}</h2>')
        for block in section.blocks:
            if isinstance(block, Paragraph):
                parts.append(f"<p>{escape(block.text)}</p>")
            elif isinstance(block, Note):
                parts.append(f'<aside class="note"><h3>{escape(block.title)}</h3><p>{escape(block.text)}</p></aside>')
            elif isinstance(block, Table):
                parts.append('<div class="table-wrap"><table><thead><tr>' + ''.join(f'<th scope="col">{escape(h)}</th>' for h in block.headers) + '</tr></thead><tbody>')
                for row in block.rows:
                    parts.append('<tr>' + ''.join(f'<td>{escape(c)}</td>' for c in row) + '</tr>')
                parts.append('</tbody></table></div>')
            elif isinstance(block, Runtime):
                parts.append(f'<article class="runtime" id="{block.id}"><h3>{escape(block.id)} · {escape(block.title)}</h3><dl>')
                parts.extend(f'<dt>{escape(label)}</dt><dd>{escape(value)}</dd>' for label, value in block.rows)
                parts.append('</dl></article>')
            elif isinstance(block, Diagram):
                parts.append(block.svg + f'<p class="caption">{escape(block.description)}</p>')
            elif isinstance(block, Bullets):
                parts.append('<ul>' + ''.join(f'<li>{escape(i)}</li>' for i in block.items) + '</ul>')
            elif isinstance(block, Contrast):
                parts.append(f'<div class="contrast"><div><h3>Leaves your machine</h3><p>{escape(block.leaves)}</p></div><div><h3>Stays on your machine</h3><p>{escape(block.stays)}</p></div></div>')
            elif isinstance(block, Links):
                parts.append('<aside class="note"><h3>Further reading</h3><ul>' + ''.join(f'<li><a href="{escape(url, quote=True)}" rel="noopener noreferrer">{escape(label)}</a></li>' for label, url in block.items) + '</ul></aside>')
        parts.append('</section>')
    contents = ''.join(f'<a href="#{s.id}">{escape(s.kicker)} · {escape(s.title)}</a>' for s in sections())
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; img-src 'none'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Drawing Analyzer — exactly what runs</title><style>
:root{color-scheme:light dark;--bg:#fff;--card:#f4f6f8;--fg:#17202b;--muted:#465465;--line:#c9d1dc;--accent:#2563eb}
@media(prefers-color-scheme:dark){:root{--bg:#0d0d0d;--card:#1a1a1a;--fg:#fff;--muted:#b0b0b0;--line:#444;--accent:#60a5fa}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.65 system-ui,sans-serif;overflow-wrap:anywhere}header{padding:2rem;max-width:1100px;margin:auto}h1,h2,h3{line-height:1.3}h2{font-size:1.8rem}h3{font-size:1.1rem}small,a{color:var(--accent)}a:focus-visible{outline:3px solid var(--accent);outline-offset:3px}.layout{display:grid;grid-template-columns:240px minmax(0,1fr);gap:2rem;max-width:1100px;margin:auto;padding:0 2rem 4rem}nav{position:sticky;top:1rem;align-self:start}nav a{display:block;padding:.3rem 0;font-size:.85rem}section{margin-bottom:3rem;scroll-margin-top:1rem}p{max-width:75ch}li{margin:.75rem 0}.note,.runtime{padding:1rem 1.25rem;margin:1rem 0;border:1px solid var(--line);border-radius:8px;background:var(--card)}.runtime dl{display:grid;grid-template-columns:120px minmax(0,1fr);gap:.6rem}dt{font-weight:bold}dd{margin:0;color:var(--muted)}.contrast{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}svg{width:100%;height:auto;color:var(--fg)}svg text{font:14px system-ui,sans-serif;fill:currentColor}.caption{color:var(--muted);font-size:.9rem}.table-wrap{overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;font-size:.9rem}th,td{padding:.75rem;border:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--card)}@media(max-width:760px){.layout{display:block;padding:0 1rem 2rem}header{padding:1rem}nav{position:static;margin-bottom:2rem}.contrast{display:block}.runtime dl{display:block}dt{margin-top:.8rem}table{font-size:.8rem}th,td{padding:.4rem}}
</style><header><p>Drawing Analyzer · Why trust it?</p><h1>I'm not convinced — show me exactly what runs</h1><p>For the professional responsible for checking and signing the review.</p></header><div class="layout"><nav aria-label="Contents">''' + contents + '</nav><main>' + ''.join(parts) + '</main></div></html>'
