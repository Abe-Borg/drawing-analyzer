# Drawing Analyzer

Extract structured information from a set of construction-drawing PDFs using Claude
vision. Each PDF page is treated as one *sheet*; every sheet is rendered to an
overview image plus a 6×6 grid of high-resolution tiles and sent to Claude Opus 4.8
in a single vision request, which returns a structured text **digest** of the sheet
(sheet number, discipline, equipment, tags, notes, schedules, etc.). An optional
cross-sheet **synthesis** pass reconciles tags and conflicts across the set.

The output is plain Markdown — read it, save it, or feed it to anything downstream.

## Install

```bash
pip install -e ".[gui]"      # GUI + engine
pip install -e ".[dev]"      # engine + test deps
```

Requires Python 3.11+. Set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or skip the env var and paste the key into the **Anthropic API Key** field at the
top of the GUI — it takes effect as soon as you enter it (no extra step), and is
saved (OS keyring when available, otherwise a local key file) once you finish
editing so it's remembered next launch. The env var still takes precedence when
both are set.

## Usage

### GUI

```bash
drawing-analyzer        # or:  python -m drawing_analyzer
```

Drop in (or browse to) PDFs, confirm the estimated cost, and the analyzer digests
every sheet. Save the result as a **navigable HTML report** (*Save HTML Report…*)
or as the raw combined Markdown (*Save Markdown…*).

The HTML report is a single self-contained file (open it by double-click, no
server or network needed) built for *finding* things in a large set rather than
scrolling a wall of text:

- a sidebar table of contents with per-sheet status and discipline tags,
- a live search box and filter chips (**All / Coordination & conflicts /
  Failed / per-discipline**), and
- an **Issues & Coordination** panel at the top that pulls together the
  cross-sheet conflicts, every per-sheet coordination / cross-discipline item,
  and any failed sheets — each linking back to its sheet.

It is **lossless**: each sheet's exact digest is preserved verbatim in a
collapsible *Raw digest (Markdown)* block, so the rendered view never drops or
paraphrases anything the model returned.

### Library

```python
from pathlib import Path
from drawing_analyzer import extract_drawing_context

ctx = extract_drawing_context(
    [Path("M-101.pdf"), Path("P-201.pdf")],
    use_batch=True,     # Message Batches API (≈50% cheaper)
    use_cache=True,     # skip re-paying for unchanged sheets
    synthesize=True,    # add a cross-sheet overview
)
print(ctx.combined_text)
for sheet in ctx.sheets:
    print(sheet.ref.display_label, "->", "ok" if sheet.ok else sheet.error)
```

`extract_drawing_context` returns a `DrawingContext` (combined text, per-sheet
`SheetDigest`s, token totals, errors, optional `synthesis_text`).

Render that same result to the self-contained HTML report from code:

```python
from drawing_analyzer import write_html_report

write_html_report(ctx, "report.html", source_names=["M-101.pdf", "P-201.pdf"])
```

## How it works

```
PDFs → list sheets → render (overview + 6×6 tiles) → per-sheet vision digest
     → optional cross-sheet synthesis → combined Markdown
```

- **Batch mode** (`use_batch=True`, the GUI default) digests every uncached sheet
  through the Message Batches API, uploading images via the Files API so no request
  body approaches the 32 MB limit. ~50% cheaper than real time.
- **Real-time mode** (`use_batch=False`) digests sheets concurrently on a bounded
  thread pool while rendering stays sequential (PyMuPDF is not thread-safe).
- **Caching** is content-keyed per sheet, so re-running a set after editing one
  sheet only re-pays vision for the changed sheet.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required (or paste the key into the GUI). |
| `DRAWING_ANALYZER_MODEL` | Opus 4.8 | Vision model for per-sheet digests. |
| `DRAWING_ANALYZER_SYNTHESIS_MODEL` | Opus 4.8 | Cross-sheet synthesis model (text-only). |
| `DRAWING_ANALYZER_MAX_WORKERS` | `4` | Real-time digest concurrency (`1` = sequential). |
| `DRAWING_ANALYZER_CACHE_PATH` | `~/.drawing_analyzer/drawing_digest_cache.json` | On-disk digest cache. |
| `DRAWING_ANALYZER_CACHE_PERSIST` | on | Disable to keep the cache in-memory only. |

## Testing

```bash
python -m pytest
```

The suite is hermetic — no API key, no network. Tests that render real PDFs are
skipped when PyMuPDF is unavailable.

## Licensing

This project depends on **[PyMuPDF](https://pymupdf.readthedocs.io/), which is
licensed AGPL-3.0**, so the project is distributed under **AGPL-3.0-or-later** (see
`LICENSE`). All PyMuPDF usage is isolated to `src/drawing_analyzer/render.py` — the
only module that imports it — so the PDF backend can be swapped for a
permissively-licensed one (e.g. `pypdfium2` + `Pillow`) by rewriting that one file,
should you want to relicense.
