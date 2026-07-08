# Drawing Analyzer

Extract structured information from a set of construction-drawing PDFs using Claude
vision. Each PDF page is treated as one *sheet*; every sheet is rendered to an
overview image plus a 6×6 grid of high-resolution tiles — **and its vector text
layer is extracted and sent verbatim alongside the images** — to Claude Opus 4.8
in a single vision request, which returns a structured text **digest** of the sheet
(sheet number, discipline, equipment, tags, notes, schedules, etc.). An optional
cross-sheet **synthesis** pass reconciles tags and conflicts across the set, and an
optional **per-run focus** (anything you particularly want pulled out — see below)
adds a dedicated **Focus Report** on top of the standard output.

The output comes two ways: a **self-contained HTML report** (`report.html`) — one
portable file with a sidebar table of contents, full-text search, and category
filters so you can isolate, say, just the coordination items or the conflicts the
model flagged across the whole set — and the underlying **plain Markdown**, for
reading, diffing, or feeding to anything downstream. The HTML is a lossless
re-presentation of the same content (it even embeds the verbatim Markdown), so
nothing the model returned is lost.

The HTML report also includes an **Ask AI** assistant (bottom-right button): a chat
grounded in the report's own text, so you can ask things like *"what are the biggest
conflicts?"* or *"which sheets mention VAV-3?"* right inside the file. It streams
answers, shows its reasoning, and can search / read the web (codes, standards,
product data) — all by calling the Anthropic API **directly from your browser**;
there is no server. To make that work with a double-clickable file, **the API key
that ran the analysis is embedded in the report**, so treat the file like a
credential: don't email or share it. (Reports generated without a key simply omit
the assistant.) The chat model defaults to Opus 4.8 and can be overridden with
`DRAWING_ANALYZER_CHAT_MODEL`.

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
every sheet. Save the result as a **navigable HTML report** (*Save HTML Report…* —
opens in your browser, searchable and filterable) or as the raw **Markdown**
digest (*Save Markdown…*).

Optionally, type a **per-run focus** before pressing Analyze — e.g. *"the rooms,
and what types of plumbing fixtures each has"*. You always get the standard
digest; a focus adds the Focus Report on top (see [Per-run focus](#per-run-focus)).

### Browsing the result

The HTML report (the folder export's `report.html`, or *Save HTML Report…* in the
GUI) makes a large set easy to navigate:

- **Sidebar table of contents** — jump to the cross-sheet overview or any sheet;
  each sheet shows an OK / cached / failed dot.
- **Search** — live full-text filter across every sheet.
- **Category filters** — one-click chips, including **⚠ Issues only**, which
  isolates the *Coordination* and *Conflict* sections the model flagged across the
  entire set. Those sections are also visually highlighted inline.
- **Lossless** — a collapsed *Complete raw Markdown* block carries the exact model
  output, so the original text is always one copy away.

### Library

```python
from pathlib import Path
from drawing_analyzer import extract_drawing_context

ctx = extract_drawing_context(
    [Path("M-101.pdf"), Path("P-201.pdf")],
    use_batch=True,     # Message Batches API (≈50% cheaper)
    use_cache=True,     # skip re-paying for unchanged sheets
    synthesize=True,    # add a cross-sheet overview
    focus="the rooms, and what types of plumbing fixtures each has",  # optional
)
print(ctx.combined_text)
print(ctx.focus_report_text)   # the set-level answer to the focus ("" if none)
for sheet in ctx.sheets:
    print(sheet.ref.display_label, "->", "ok" if sheet.ok else sheet.error)
```

`extract_drawing_context` returns a `DrawingContext` (combined text, per-sheet
`SheetDigest`s, token totals, errors, optional `synthesis_text`, and — when a
focus was given — `focus` / `focus_report_text`).

## How it works

```
PDFs → list sheets → render (overview + 6×6 tiles) + extract vector text layer
     → per-sheet vision digest (images + verbatim text layer)
     → optional cross-sheet synthesis → optional focus report → combined Markdown
```

- **Text-layer grounding.** Before rasterizing, each sheet's vector text layer is
  lifted losslessly (`page.get_text()` — free, ~0.3 s for 8 sheets) and spliced
  into the digest prompt **verbatim, before the images**, as the source of truth
  for exact strings (tags, schedule values, note numbers, sheet references). Vector
  text can't misread a digit the way OCR of a low-resolution embedded raster can,
  so grounding the read in it is the antidote to that class of error.
- **Render resolution.** Ordinary (vector) sheets now render each tile at a
  **1560 px** long edge (down from 1992 px) — the text layer carries the exact
  strings, so the tiles trade ~40% of their PNG bytes and image tokens for a
  smaller, cheaper request while staying crisp for note text. **Raster fallback:**
  a sheet with an *empty* text layer (scanned or pasted-raster) instead renders at
  **1992 px**, because there the pixels are the only information channel; such
  sheets are flagged in the run and (later) badged in the report.
- **Batch mode** (`use_batch=True`, the GUI default) digests every uncached sheet
  through the Message Batches API, uploading images via the Files API so no request
  body approaches the 32 MB limit. ~50% cheaper than real time. If the Files API is
  unavailable for your key/workspace (uploads return `404`), each affected sheet
  falls back to an inline real-time digest so the run still completes instead of
  producing nothing.
- **Real-time mode** (`use_batch=False`) digests sheets concurrently on a bounded
  thread pool while rendering stays sequential (PyMuPDF is not thread-safe).
- **Caching** is content-keyed per sheet, so re-running a set after editing one
  sheet only re-pays vision for the changed sheet. Note: the new render target
  changes the rendered PNG bytes (and the digest prompt now carries the text
  layer), so **every pre-existing cache entry is naturally invalidated** — the
  first run after this change re-digests each sheet once, then caches as before.

## Per-run focus

The analyzer's built-in goals are fixed (a spec-reviewer-oriented digest). A
**per-run focus** lets you add your own, for one run, at your discretion — it is
never required, and the standard output is always produced unchanged. With a
focus set:

- **Each sheet is read with your question in mind** — the vision prompt asks for
  one extra, final **`Focus findings`** section per sheet (the standard digest
  sections are unaffected).
- **A set-level Focus Report** is assembled in one extra text-only pass: a
  direct, cross-sheet answer to your focus, citing the sheets that carry each
  fact. It leads the combined Markdown, is written as `00_focus.md` in folder
  exports, and gets a pinned card (plus a *Focus* filter chip) in the HTML
  report.

Cache interplay: the focus is folded into the per-sheet cache key. Re-running
with the **same** focus is served from cache; **changing or adding** a focus
re-analyzes the sheets (the model must re-read the drawings with the new
question), while your existing no-focus cache entries remain valid for ordinary
runs.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required (or paste the key into the GUI). |
| `DRAWING_ANALYZER_MODEL` | Opus 4.8 | Vision model for per-sheet digests. |
| `DRAWING_ANALYZER_SYNTHESIS_MODEL` | Opus 4.8 | Cross-sheet synthesis model (text-only). |
| `DRAWING_ANALYZER_FOCUS_MODEL` | Opus 4.8 | Focus-report model (text-only). |
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
