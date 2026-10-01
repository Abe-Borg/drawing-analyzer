# Drawing Analyzer

Drawing Analyzer turns construction-drawing PDFs into searchable sheet digests
and an HTML report using Claude vision. Optional engineering QC adds findings,
cross-sheet checks and marked-up PDFs. It runs as a Windows desktop app;
model requests use your Anthropic account and API key.

Use the normal sheet analysis first. Turn on the additional QC work when you
need it. A model review can miss defects or invent them: check the output
against the drawings before relying on it.

## Install on Windows

The latest published 1.7.0 has a preserved
[HOLD acceptance record](docs/releases/ACCEPTANCE-1.7.0.md).
This cleanup does not change that release decision.

1. Download `DrawingAnalyzerSetup.exe` from the
   [releases page](https://github.com/Abe-Borg/drawing-analyzer/releases).
   Choose a stable release for normal use; an `rc` is a pre-release for testing.
2. Run the installer. Current builds show an AGPL license agreement; older
   published installers may omit that page, but the license still applies.
   It installs per user and adds a Start-menu shortcut. The installer is unsigned, so Windows may
   display SmartScreen; verify the download source before allowing it.
3. Open Drawing Analyzer and paste your Anthropic API key into the field.
   A working OS credential store saves it for next time. If that is unavailable,
   the app asks before saving a plaintext file; declining keeps a session key.

The app checks for updates at launch, at most daily, and has a **Check for
Updates** button. Updates require your approval to download/install. The download
hash protects against corruption; it is supplied by the same manifest as the
installer and does not independently authenticate its publisher. Set
`DRAWING_ANALYZER_DISABLE_UPDATE_CHECK=1` to disable update checks.

## Analyze a set

1. Browse to or drop in your PDFs. Each page is a sheet. Vector PDFs give the
   model both pictures and extracted text; scans depend on the pictures.
2. Leave **QC Markups** off for basic sheet analysis. **Deterministic audit
   only** optionally adds local reference, arithmetic and naming checks without
   additional model calls; the sheet analysis itself still costs money.
3. Choose **Economy** if waiting is acceptable. It batches the sheet reads at
   discounted token rates. **Fast** reads immediately at full rates. **Hybrid**
   reads sheets immediately and batches critique reads when QC is enabled;
   it does not discount ordinary sheet analysis.
4. Optionally add a **Per-run focus** or attach project specifications. Focus
   changes the sheet requests and can require paid rereads of cached sheets.
5. Click **Analyze**, review the estimated cost and confirm. Keep the app open
   while it works. Economy may take hours or overnight; batch completion can
   take up to the provider's 24-hour window. There is no desktop Stop button
   or global spending ceiling. Closing the app can lose unsaved output while
   accepted remote work continues and remains billable.
6. Save the **HTML Report**. Use **Export All** for a folder containing the
   report, Markdown digests, findings, extracted sheet text and run records.
   After a QC run, **Save Reviewed PDF(s)** copies the marked-up files to a
   folder you choose. Save before closing the app; do not overwrite originals.

## Control cost

Economy is the default GUI transport. Eligible batch requests use roughly half
of the corresponding real-time token rates; set-level calls, recovery and other
work can still have different charges. That is a rate discount, not a promise
that the whole review costs half as much.

Full **QC Markups** is much more expensive than basic analysis: it adds two
critique reads per sheet and set-level checks, crop verification, investigation
and citation work. Keep it off when you only want drawing data. Report **Ask AI**
questions also cost money and are separate from the analysis run's totals.

The confirmation dialog is a planning estimate, not a quote. Drawing density,
output length, retries and fallback models change the bill; some incomplete
usage and chat tool charges may be absent from displayed totals. Check your
Anthropic usage. If your observed cost is about $4 per sheet, budget from that
until a representative run establishes a better figure; advertised rules of
thumb are not evidence for your set.

Unchanged requests can reuse the local cache. A changed drawing, focus, model,
rendering setting or request contract can cause paid rereads. Keep your normal
cache; do not clear it to test whether the app is faster. Compare versions with
separate test caches. Changing image resolution, tile coverage or model defaults
to save money needs a real-drawing check first. See the
[small comparison plan](docs/PERFORMANCE_AND_COST_VALIDATION.md).

## Read the result

The HTML report has sheet navigation, search and category filters. Read any
failed-sheet or partial-stage warnings before trusting its coverage. A digest
retains the recorded sheet prose; parsing and filters can omit model proposals
from the structured findings. A wrong or incomplete PDF text layer can also
mislead a reading. The overview and 6×6 tile grid provide whole-sheet visual
coverage; pixel-uniform tiles may be omitted with disclosure.

For occasional QC, enable **QC Markups** before analysis. The reviewed PDF
includes numbered findings, severity styling and an index. **Verified &
deterministic only** restricts which findings receive ink; **Include rejected
(grey)** includes findings the model verifier rejected. Unverified findings can
otherwise be marked. VERIFIED is a model judgment, not professional approval;
DETERMINISTIC applies to supported local checks. Host arithmetic uses `Decimal`
and drawing-grounded claims, but this does not make every model statement correct.

**COMPLETE** means the configured stages completed, not that every design defect
was found. Saved markup is checked against its placement plan. An
`_INCOMPLETE.pdf` name or incomplete-coverage warning means planned marks were
missing or failed; inspect the export's `markup_manifest.json`. Text, anchors,
citation editions and markup placement still need human review. Callout margin
placement is a heuristic and may cover drawing content. Keep your originals.

| Output | What it is for |
|---|---|
| HTML report | Read/search the digest and findings; optional paid Ask AI chat |
| Reviewed PDFs | Inspect QC marks against the source drawing, after QC |
| Export All folder | Keep Markdown, `findings.json`/CSV, `sheet_text/`, evidence and run records |
| `run.log` / `run_manifest.json` | Diagnose missing/failed work and inspect configuration, usage and artifact hashes |

The run manifest inventories exported artifacts, not the completeness or
correctness of the engineering review. Keep your own copies of attached
specifications: the export does not archive their originals separately.

## Privacy and report chat

Approved analysis sends drawing images, extracted text and supplied context to
Anthropic by default. Citation and chat web tools may research project-derived
information. Updates, custom endpoints/proxies and clicked links have separate
network destinations. Check your project rules and provider agreement before
sending restricted drawings. Local caches, temporary evidence, exports and
browser conversations contain project data and do not share one deletion control.

HTML reports omit the API key by default. **Embed API key in HTML report** writes
it into the file: treat that file as a credential and never share it. **Forget
key** cannot remove an embedded key. A typed chat key uses browser tab storage;
browser recovery and local-file origins do not guarantee isolation or disk-free
storage. Chat sends the report and conversation to the provider when you ask a
question; conversations are saved locally and can contain private project text.

See [Security & Privacy](SECURITY.md) for the key, retention and HTML boundaries.
The in-app **Why trust it?** help explains mechanisms and limits.

## Developers

Python 3.11+ is required. Install the GUI from a checkout:

```powershell
python -m pip install -e ".[gui]"
python -m drawing_analyzer
```

The `drawing-analyzer` command also launches the GUI. There is no separate
analysis command-line interface. The Python library exposes the same pipeline:

```python
from pathlib import Path
from drawing_analyzer import extract_drawing_context
from drawing_analyzer.export import write_drawing_export

ctx = extract_drawing_context(
    [Path("M-101.pdf")], use_batch=True, use_cache=True,
)
write_drawing_export(ctx, Path("review-output"), source_names=["M-101.pdf"])
```

Library callers supply a client or use `ANTHROPIC_API_KEY`. Do not put a real
key in source files or command history. The GUI captures its key for the run;
editing the field later cannot change a running job.

The module map is in `src/drawing_analyzer/__init__.py`; use source signatures
for advanced options. Optional checklist examples are in
[docs/examples](docs/examples/README.md); no built-in discipline profiles ship.
The example's cited NFPA edition must match the project's adopted edition.

For development checks:

```powershell
python -m pip install -e ".[gui,dev,browsertest]"
python -m pytest -q -m "not network"
```

Tests must need no API key and cannot reach external networks. Browser checks
also require the configured Chromium installation. Live checks need separately
approved private drawings and a written spending budget.

Maintainer guidance is in [CLAUDE.md](CLAUDE.md), current work in
[_plans/PROGRESS.md](_plans/PROGRESS.md), and release steps in
[docs/RELEASE_WINDOWS.md](docs/RELEASE_WINDOWS.md). Historical release acceptance
records remain in [docs/releases](docs/releases); shortening documentation does
not change an acceptance decision or authorize publishing.

## Licensing

Copyright © 2026 Abraham Borg; licensed under **AGPL-3.0-or-later**, with no
warranty. See [LICENSE](LICENSE). PyMuPDF is AGPL/commercial dual-licensed;
preserve the project's existing AGPL licensing policy when distributing it.
Only `render.py` and `annotate.py` may import PyMuPDF. That technical boundary
keeps PDF work isolated; it does not itself establish permission to relicense
the combined application.
