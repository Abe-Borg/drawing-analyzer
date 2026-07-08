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

## Structured findings

Alongside the prose digest, the vision model emits a **machine-readable findings
block** — a fenced `json` block appended after all prose:

```json
{"findings": [
  {"sheet_id": "M-101", "category": "code", "severity": "high",
   "text": "VAV-3 has no shown clearance to the wall.",
   "source_quote": "VAV-3", "tile": [2, 3], "refs": ["CMC 310"]}
]}
```

Each finding carries a `category` (`code` / `conflict` / `coordination` /
`question`), a `severity` (`high` / `medium` / `low`), a one-to-two-sentence
`text`, a `source_quote` copied **verbatim** from the sheet's text layer (the
hook the anchor resolver uses to place it, and the hallucination alarm when a
quote can't be found), the `tile` where the model saw it, and any `refs` it
believes apply. The model emits at most 40 per sheet.

A tolerant parser splits this block off and **strips it from the prose**, so the
digest text — and the `combined_text` a downstream spec reviewer consumes — is
byte-for-byte what it was before the block existed (the prose digest is sacred).
The parser absorbs the small ways models drift: it takes the last fenced block,
trims to the outermost `{…}`, tolerates a trailing comma, and drops any item
that fails validation (logging the count). A malformed or missing block is never
fatal — the prose digest still ships; the findings simply come back empty. Parsed
findings are cached with the digest, so a cached re-run restores them for free.

## Anchoring findings

A finding is only useful on a marked-up drawing if it sits **on the thing it's
about**. The anchor resolver maps each finding's verbatim `source_quote` back to
a rectangle on its page (in the PDF's own points), offline and with no model
call, using a tiered strategy that records which tier fired:

- **EXACT** — the normalized quote matches a run of words verbatim. When the
  quote appears more than once on the sheet (the *"BATTERY ROOM in two schedule
  rows"* trap), the occurrence inside the tile the model reported is preferred;
  if that still doesn't settle it, the finding is flagged `exact_ambiguous`.
- **FUZZY** — no exact run, but a sliding window of words overlaps the quote's
  tokens ≥ 85%, or the longest distinctive sub-phrase (≥ 3 tokens) of the quote
  appears verbatim. Whitespace/linebreak artifacts and Unicode punctuation (dashes,
  curly quotes, the `2 1/2"` vs `2-1/2"` and `″`/`"` inch marks, the `Ø` diameter
  symbol) are the usual reason exact fails; normalization folds most of them.
- **TILE** — a graphics-only finding (empty quote) is anchored to its reported
  tile's rectangle: coarse, but honest.
- **UNANCHORED** — a *non-empty* quote that matches nothing anywhere. This is the
  **hallucination signal**: the finding is kept and flagged, but never clouded by
  default (a wrong cloud on an issued drawing is worse than a missing one).

Findings the deterministic auditors already placed (the reference audit) arrive
pre-anchored and are left untouched. Like the tile geometry, the resolver imports
no PDF engine — it works on the extracted word rectangles alone.

## Reference audit

Construction sheets constantly point at each other — *"SEE DRAWING F-D-01-1"*,
detail bubbles like `04/F-G-02-0`, spec citations like `23 21 13`. When a sheet
is revised those pointers go stale (a note still says `F-D-01-0` after the sheet
reissued as `F-D-01-1`) or send the reader to a sheet that isn't in the package.

The analyzer includes a **deterministic, zero-API reference auditor** that reads
only the extracted vector text layers — no model call, milliseconds of CPU — and
flags broken cross-references. It:

- **learns the set's own sheet-ID convention** by detecting each sheet's ID from
  its title block (bottom-right) and generalizing the grammar from that harvest,
  so it works across offices without a hardcoded numbering scheme;
- **harvests references** — trigger phrases (`SEE DRAWING/SHEET X`, `SEE X FOR`,
  `REFER TO X`, `PER X`, `ON DRAWING X`), detail bubbles (`NN/<sheet-id>`), and
  CSI spec sections (collected as informational, since the drawing set can't
  confirm a spec reference);
- **resolves** each against the set: present → no finding; well-formed but
  **not present in the provided set** → a finding at the reference's exact
  location, with the closest in-set ID suggested by edit distance; a malformed
  pointer → flagged as a likely typo.

It never claims a referenced sheet *doesn't exist* — only that it *isn't in the
set you provided* — because a partial set legitimately omits sheets. Every
reference finding is anchored to its own word rectangle and marked
`DETERMINISTIC` (trusted without a model re-check). On a real 8-sheet
fire-protection set this caught three genuine coordination errors. The auditor is
exposed as `drawing_analyzer.reference_audit.audit_references(rendered_sheets)`;
it wires into the run output alongside the QC-markup workflow (forthcoming).

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
