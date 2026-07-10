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
there is no server. The assistant is present **by default**, whether or not the
report was built with a key. **By default the report does not contain your API
key**: the assistant asks for one the first time you use it and keeps it only in
that browser tab (`sessionStorage`), so the file is safe to share and the key never
touches disk (a **Forget key** control clears it). If you'd rather have a
zero-friction, double-click-and-ask file, tick **Embed API key in HTML report**
(GUI) or pass `embed_api_key=True` — the key is then baked into the HTML, the report
shows a red *"don't share this file"* warning, and you should treat the file like a
credential (a runtime "forget" cannot remove an embedded key — only regenerating or
deleting the file can). Pass `include_chat=False` to omit the assistant entirely.
The chat model defaults to Opus 4.8 and can be overridden with
`DRAWING_ANALYZER_CHAT_MODEL`.

See [SECURITY.md](SECURITY.md) for the report's trust boundary (all model output is
treated as hostile and can never execute), API-key handling, secret redaction in
logs, and what project data each artifact and the Ask-AI assistant contains.

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

Two **QC review** checkboxes sit beside the focus:

- **Reference audit** — a free, zero-API pass that runs the whole deterministic
  auditor battery: references, arithmetic, naming, title-block, and sheet-index
  (see [Deterministic auditors](#deterministic-auditors)).
- **QC Markups** — runs the anchor → verify → ink chain and produces a
  **marked-up PDF + findings CSV** (see [Reviewed PDFs & findings CSV](#reviewed-pdfs--findings-csv)).
  By default **every ledger entry gets ink except the ones the verifier proved
  wrong** ([§18 gating](#gating--all-findings-get-ink-part-iii-18)): unverified
  findings draw dashed with an `[UNVERIFIED]` prefix, rect-less ones become
  margin callouts. Two sub-toggles adjust that — **Verified & deterministic
  only** (off by default; the conservative opt-in that suppresses unverified
  ink) and **Include rejected (grey)** (also inks verifier-rejected findings,
  struck grey). The cost line notes the extra per-finding verification spend
  (~$0.01–0.03 each) while markups are on.

After a QC run, the completion summary reports the finding count, how many were
clouded, and the ledger coverage tally
(`Ledger 47: 39 clouded, 6 margin, 2 rejected (indexed)`), and two extra
buttons light up: **Save Findings CSV…** and **Save Reviewed PDF(s)…** (the
latter copies every `*_reviewed.pdf` into a folder you pick).

### Browsing the result

The HTML report (the folder export's `report.html`, or *Save HTML Report…* in the
GUI) makes a large set easy to navigate:

- **Sidebar table of contents** — jump to the QC findings, the cross-sheet
  overview, or any sheet; each sheet shows an OK / cached / failed dot.
- **QC Findings card** (when a QC run produced findings) — a pinned, **sortable**
  table (ID, sheet, category, severity, status, finding, quote). Each row carries a
  color-coded **status chip** — `Verified` (green), `Deterministic` (blue),
  `Uncertain` (amber), `Unanchored` (red outline), `Rejected` (struck grey) — and
  links to the sheet it sits on. The chips honour the filter chips and **⚠ Issues
  only**; folder exports also thumbnail the verifier's evidence crop on each row.
- **Search** — live full-text filter across every sheet. When a QC run captured
  the sheets' **raw text layers**, search runs over what each *sheet* actually
  says (a collapsed *Sheet text layer* block per sheet), not only what the digest
  said about it. Scanned / pasted-raster sheets are badged **Raster**.
- **Category filters** — one-click chips, including **⚠ Issues only**, which
  isolates the *Coordination* and *Conflict* sections (and every finding) the
  model flagged across the entire set. Those sections are also highlighted inline.
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
    # QC review (all optional, off by default):
    reference_audit=True,        # free, zero-API deterministic auditor battery
    qc_markups=True,             # anchor → verify → ink; write reviewed PDFs
    markup_verified_only=False,  # opt-in conservative mode (§18 default: ink all but REJECTED)
    verify_findings=True,        # run the per-finding verification pass
    critique=True,               # second "reviewer" read/sheet, self-consistent (pricier)
    profiles=["fire-protection"],# review-profile checklists to apply (needs critique=True)
    cross_qc=True,               # hunt cross-sheet conflicts; cloud both sheets
    citation_check=True,         # web-search check of cited code sections
    ink_rejected=False,          # also draw verifier-rejected findings (grey/struck)
    focus_findings_to_markups=False,  # harvest Focus sections into markups too
    qc_work_dir=Path("run-out"), # where evidence crops + reviewed PDFs land
)
print(ctx.combined_text)
print(ctx.focus_report_text)   # the set-level answer to the focus ("" if none)
for sheet in ctx.sheets:
    print(sheet.ref.display_label, "->", "ok" if sheet.ok else sheet.error)

# QC results (empty unless a QC flag was on):
for f in ctx.all_findings:      # model findings + deterministic reference findings
    print(f.sheet_id, f.category, f.anchor.status, f.verification.status, "-", f.text)
print(ctx.finding_count, "findings,", ctx.clouded_finding_count, "clouded")
for pdf in ctx.reviewed_pdf_paths:   # the *_reviewed.pdf files (qc_markups only)
    print("marked-up:", pdf)
```

`extract_drawing_context` returns a `DrawingContext` (combined text, per-sheet
`SheetDigest`s, token totals, errors, optional `synthesis_text`, and — when a
focus was given — `focus` / `focus_report_text`). When a QC flag is on it also
carries the QC record: `findings` (the model's, anchored + verified),
`reference_findings` (the deterministic auditors', anchored + `DETERMINISTIC`),
the `all_findings` / `finding_count` / `clouded_finding_count` conveniences,
`reviewed_pdf_paths`, the lightweight `sheet_geometries`, `audit_stats` (the
auditors' checks-passed tally), `ledger_tally` / `ledger_tally_line` (the §18
coverage tally), and `qc_work_dir` (holding `evidence/` crops and the reviewed
PDFs). Every finding carries its sequential `qc_id` review number (`QC-001` …),
its provenance tags (`sources` — see the [findings ledger](#the-findings-ledger-part-iii)),
and, when the citation check ran, a `citation` verdict. `write_drawing_export(ctx, parent_dir, ...)` folds all of it
into the export folder — `findings.json`, `findings.csv`, `sheet_text/<sheet>.txt`
per sheet, the `*_reviewed.pdf` copies, and the `evidence/` crops — alongside the
prose digest and HTML report.

## How it works

```
PDFs → list sheets → render (overview + 6×6 tiles) + extract vector text layer
     → per-sheet vision digest (images + verbatim text layer)
     → optional cross-sheet synthesis → optional focus report → combined Markdown
     → optional QC: deterministic auditors + anchor → verify → cloud (reviewed PDFs, CSV)
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
  sheet only re-pays vision for the changed sheet. It is now **two-level** — a
  cheap *pre-render* key recognizes an unchanged sheet before rasterizing, so a
  cached re-run skips rendering entirely (see [Performance](#performance)).

## Performance

Two headline savings, both measured on real dense sets, plus a deliberate
non-goal:

- **Skip-render on a cache hit (two-level key).** Rasterizing a sheet's overview
  + 36 tiles is the dominant re-run cost (~4.5 s/sheet; ~2.5 min for a 33-sheet
  set). A digest is deterministic given the rendered images, so before rendering
  the pipeline computes a **level-1 key** from cheap page access alone — the
  PyMuPDF version, grid/overlap/render-target, and a hash of the page's content
  streams + referenced image bytes + rect — and, on a hit, serves the cached
  digest **without rendering**. A fully-cached 33-sheet re-run drops ~2.5 min of
  render to ~0. On a miss the sheet renders, the digest is computed, and it is
  stored under **both** the level-1 key and the existing rendered-bytes (level-2)
  key, so the *next* run skips it. Any change that would alter the pixels — the
  page content, the render target, the grid, the PyMuPDF version — re-keys and
  re-renders, so the cache stays correct, not just fast.
- **Parallel Files-API uploads.** A sheet's ~37 images upload on a small pool
  (default 6, `DRAWING_ANALYZER_UPLOAD_WORKERS`) instead of one at a time — the
  dominant batch-path latency after rendering. Parallelism changes only
  *scheduling*: each image keeps the same retry taxonomy (transient `503`s
  re-issued with backoff; ambiguous connection/timeout errors left to the SDK's
  idempotent retries), so a lost response still can't orphan a stored file, and
  the first hard failure stops the sheet's remaining uploads.
- **Blank-tile suppression.** A tile whose pixmap is **pixel-uniform** (a truly
  empty crop of a sparse sheet) carries no information, so it is dropped before
  upload and disclosed to the model (*"Tiles omitted as completely blank: …"*).
  The strict, uniform-only check is always on and can never drop a tile with any
  mark on it. An opt-in **near-blank** heuristic (`DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK=1`,
  a PNG-byte threshold) is far more aggressive — it dropped ~9 % of tiles on a
  dense fire-protection set and up to a third on schedule sheets — but *can* drop
  a tile bearing a few faint marks, so it is **off by default**: data over
  savings.
- **Non-goal — render-once-then-crop.** Benchmarked against the current per-tile
  clip rendering on a real dense set (34.4 s vs 35.7 s — a wash: the ~75-megapixel
  full-page raster on sparse sheets eats the display-list savings on dense ones),
  so the current render path is left as-is. Process-parallel rendering across
  sheets remains a legitimate future option for 100+-sheet sets.

Note: the two-level key and blank-tile suppression both change what is stored/sent,
so the digest cache's schema version is bumped — **every pre-existing cache entry
is invalidated once**; the first run after upgrading re-digests each sheet, then
caches as before.

**Cost of the exhaustive critique.** A plain digest is roughly $0.4–0.6/sheet
real-time (~half that via Batches). Turning on the [critique pass](#critique-pass-the-reviewer)
adds a second full-coverage read run twice — on the order of **$1–1.5/sheet** at
Opus pricing, plus its re-render — so an exhaustive `critique=True` run lands
around **$2–3.5/sheet** once verification is included. The offline stages
(reference audit, anchoring, markup, text extraction) stay $0. Every stage is
individually cached, so a re-run of an unchanged set skips the model calls.

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

## Critique pass (the reviewer)

The digest *describes* a sheet; the critique *attacks* it. Turned on with
`critique=True` (the exhaustive QC mode), the analyzer makes a **second
full-coverage vision read** of each sheet — the same overview + tile grid +
verbatim text layer the digest saw — but under a different persona: a senior
engineer performing a rigorous back-check / QA markup of a check print before it
is issued, whose *only* job is to find problems. It is instructed to report, with
severity: outright errors; likely code concerns (cited conservatively); RFI-worthy
ambiguities; internal inconsistencies; stale / copy-paste text; and — crucially —
**absences**: content a complete sheet of that discipline should show but this one
doesn't (a required test, drain, sign, clearance, note, or detail), each phrased
*"expected X; not found on this sheet."* Absence and sheet-level findings carry an
`anchor_hint` of `SHEET` instead of a quote, so the anchor resolver places them
against the whole sheet.

The critique emits only the machine-readable findings block — no prose — so the
prose digest (and `combined_text`) is untouched (I-2).

**Self-consistency.** The critique runs **twice**. Two independent reads of the
same sheet disagree at the margins, and that disagreement is signal: a finding
both runs surface is **corroborated** (`reproduced = true`); a singleton one run
raised is *kept* (more markups is better) but flagged `reproduced = false`. The
merge deduplicates by position (anchor-rect overlap once anchored, else the same
reported tile) and normalized-text overlap. The digest's findings and the merged
critique's then pool into one per-sheet set before anchoring — an issue the digest
*and* the critique independently raised is also marked reproduced. `reproduced`
is a soft confidence signal surfaced in the report and markup; it **never**
suppresses a finding.

The merged critique is cached under its own key, so a re-run skips the extra
calls. Because the digest's images are gone by the time the critique runs (the
batch path streams and discards them), the critique **re-renders** each sheet —
so `critique=True` is meaningfully more expensive than a plain digest (see
[Performance](#performance)). It is additive and non-fatal: a failure is recorded
and the standard deliverable ships. The model defaults to Opus 4.8
(`DRAWING_ANALYZER_CRITIQUE_MODEL`); the run count is `DRAWING_ANALYZER_CRITIQUE_RUNS`
(default 2; set 1 to disable self-consistency).

## Review profiles

The critique reads with a senior engineer's *general* judgment. A **review
profile** makes that judgment *specific and repeatable*: it is the owner's QC
knowledge written down as a versioned checklist, injected into the critique
prompt so the model applies each item deliberately, not incidentally. Pass the
profile names to a critique run:

```python
ctx = extract_drawing_context(
    pdfs, critique=True, qc_markups=True,
    profiles=["fire-protection"],   # names of profiles to apply
)
```

Selected profiles' checklists are appended to the critique prompt under *"APPLY
THIS REVIEW CHECKLIST EXPLICITLY, ITEM BY ITEM"*, and the set of profiles (name +
version + a content hash of each) folds into the critique cache key — so
**editing a checklist re-critiques** the affected sheets, while an unchanged
selection is served from cache. A very long checklist is split across the two
self-consistency runs (each run covers a slice; the union is complete) rather
than truncated. Profiles only take effect with `critique=True`; unknown names are
skipped without failing the run.

A starter **fire-protection** profile (NFPA 13 sprinkler QC) ships with the tool.
`drawing_analyzer.profiles.suggest_profiles(sheet_ids)` proposes profiles whose
disciplines match a set's sheet numbering (e.g. `F-…` sheets → the
fire-protection profile).

### Writing a profile

A profile is a Markdown file with a small frontmatter header and a flat list of
one-line checklist items:

```markdown
---
name: fire-protection
title: Fire Protection — NFPA 13 sprinkler QC
disciplines: F, FP, SP
version: 1
author: Your Name
date: 2026-07-08
---

- Dry/DIPA design areas carry the +30% increase over the wet base; flag a dry
  row whose remote area equals the wet base. [high] (NFPA 13 §19.2.3.2.5)
- EH standard-spray coverage ≤ 100 ft²; flag a larger max-area value. [medium]
- Every dry/preaction system must show its ITV, air supply, low-point drains,
  and gauges; flag any missing (an absence). [medium]
```

- **Frontmatter** (between the `---` lines): `name` (stable id — reused to
  *shadow* a built-in), `title`, `disciplines` (comma-separated tags matched
  against sheet-id prefixes for auto-suggest), `version`, `author`, `date`.
- **Items**: each Markdown bullet is one check, injected **verbatim** — say what
  to check, what "wrong" looks like, a severity hint in `[brackets]`, and a code
  reference where one applies. Absences read best as *"expected X; not found on
  this sheet."*

Profiles are discovered from the built-in set shipped with the package and from
your own directory — **`~/.drawing_analyzer/profiles/`** (override with
`DRAWING_ANALYZER_PROFILES_DIR`) — where a file reusing a built-in `name` wins,
so you can tune the shipped checklist without editing the install. Bump `version`
(or just edit — the content hash changes either way) to re-run the critique
against the new checklist.

## Cross-sheet QC

The digest and critique read each sheet on its own. A whole class of real errors
is only visible *between* sheets: the same tag valued two ways, a standard note
that diverged on a sibling sheet, a note on one sheet contradicted by another, a
cross-reference sending you to a sheet that disclaims what the pointer promised.
Turned on with `cross_qc=True`, the **cross-sheet QC pass** hunts exactly those.

It is a *text-reasoning* task — one Opus call over all the per-sheet **digests +
verbatim text layers**, with **no images** (large sets shard by discipline). It is
distinct from the prose [synthesis](#how-it-works), which stays as-is, and like
the critique it never touches `combined_text` (the conflicts live only in the
findings artifacts).

Its findings carry **dual anchors**: a primary anchor on one sheet plus one or
more `also_on` legs on the other sheets in the conflict, each resolved to its own
sheet (via the set's title-block sheet-ids). The markup writer then clouds
**both** sheets — each cloud's popup cross-references the other (*"Conflicts with
F-A-01-1: 'COLO 1'"*) — so a reviewer opening either drawing sees the conflict and
where its counterpart lives. The model defaults to Opus 4.8
(`DRAWING_ANALYZER_CROSS_QC_MODEL`).

A cross-sheet conflict can't be judged from one sheet's crop, so these findings
get a **dual-crop verification**: the verifier is sent **one crop per sheet in a
single call** and asked whether the sheets actually conflict — so a cross-sheet
finding can reach `VERIFIED` / `REJECTED` on the merits like any other finding
(and a rejected one loses its ink, [§18](#gating--all-findings-get-ink-part-iii-18))
instead of idling at `UNCERTAIN`.

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
  **hallucination signal**: with no rectangle to cloud, the finding lands as a
  **margin callout** with an `[UNANCHORED]` prefix
  ([§18](#gating--all-findings-get-ink-part-iii-18)) — flagged loudly, never
  dropped, and never drawn as if it had a location.

Findings the [deterministic auditors](#deterministic-auditors) already placed
arrive pre-anchored and are left untouched. Like the tile geometry, the resolver
imports no PDF engine — it works on the extracted word rectangles alone.

## Verification pass

Coverage proposes; precision disposes. Before any finding is clouded onto an
issued drawing, the verification pass takes a **surgical second look**: for each
*anchored* finding the model itself produced, it renders a high-DPI crop around
the anchor and asks **one small model call** whether the finding actually holds
**in that crop** — instructed to judge *only* what's visible, not re-argue the
whole issue. The crop the verifier saw is written to `evidence/<finding_id>.png`
regardless of the verdict; the audit trail is the point.

The model answers `CONFIRMED` / `CONTRADICTED` / `NOT_VISIBLE`, mapped to a
finding status:

| Status | Source | Meaning |
|---|---|---|
| `VERIFIED` | verifier `CONFIRMED` | the crop shows the finding is correct |
| `REJECTED` | verifier `CONTRADICTED` | the crop shows the finding is wrong — pulled from the ink and listed in the index's *Rejected by verification* section (grey struck ink only with `ink_rejected=True`) |
| `UNCERTAIN` | verifier `NOT_VISIBLE` (or a garbled reply) | can't be decided from this crop (e.g. it depends on another sheet) — a perfectly fine outcome |
| `DETERMINISTIC` | the offline auditors | trusted without a model re-check (references, arithmetic, naming, title-block, sheet-index) |
| `SKIPPED` | — | nothing to look at (unanchored), no crop, or the pass was unavailable (no key) |

The pass is additive and non-fatal: crops render sequentially (PyMuPDF is not
thread-safe) while the small verify calls run on a bounded pool; a per-finding
failure degrades that finding to `UNCERTAIN`, and a fatal auth failure marks the
rest `SKIPPED` — the run always completes. Each call is tiny (one ~1–2k-token
crop image + a short prompt), on the order of $0.01–0.03 per finding. The model
defaults to Opus 4.8, overridable with `DRAWING_ANALYZER_VERIFY_MODEL`.

## Reviewed PDFs & findings CSV

Turned on with the GUI's **QC Markups** checkbox or `qc_markups=True` in the
library. The payoff is a **marked-up copy of the original drawing** — `<stem>_reviewed.pdf`
— that reads like a numbered, navigable, senior plan-review set. Every annotation
is a **real PDF object** authored *"Drawing Analyzer (AI review)"* so provenance
is unmistakable: opened in **Bluebeam Revu** they populate the Markups List
(filter, sort, reply, export all work), and Acrobat and Chromium render them too
(the appearance stream is built explicitly, so nothing shows up blank).

### Markup anatomy (the legend)

- **QC numbers.** Every finding in the run gets a sequential review number
  (`QC-001` …, ordered sheet → position). Each inked finding carries the number
  as a small **FreeText tag** beside its markup, in the severity color; the same
  number appears in `findings.csv`, `findings.json`, the HTML report, and the
  index page — one namespace everywhere.
- **Severity colors.** high = **red**, medium = **orange**, low and any
  *question*-category finding = **blue**.
- **Border styles say who found it.** A model finding that verified draws a
  **revision cloud**; a **`DETERMINISTIC`** (auditor) finding draws a **solid**
  border — the host computed it, no cloud theatrics; an opted-in unverified
  finding draws **dashed** with an `[UNVERIFIED]` popup prefix.
- **Sheet-level / absence findings** (`anchor_hint="SHEET"` — "expected X; not
  found on this sheet") have no rectangle to cloud. They become **callout boxes
  stacked in a computed clear margin band** — the largest text-free horizontal
  strip on the sheet, found from the word rectangles — with a **leader-line
  arrow** to the reported tile's centroid when one is known.
- **Index page(s).** Each reviewed PDF opens with **"AI DRAFT REVIEW - FINDINGS
  INDEX"** — a table (ID, sheet, severity, status, one-line finding) where every
  row is a **GOTO link** that jumps straight to the finding's page and rectangle
  (works in Revu, Acrobat, and Chromium). Multi-page as needed.
- **Popups are exhaustive**: the finding text, the verbatim quote, the
  cross-sheet pointer (dual-anchored conflicts cite each other by QC number),
  verification status + verifier note, code refs plus the
  [citation-check](#citation-check) verdict, the reproduced flag (when a
  self-consistency read didn't corroborate it), the evidence-crop filename, and
  both ids.
- **Optional appendix** (`DRAWING_ANALYZER_MARKUP_APPENDIX=1`, off by default):
  a final **"checked and consistent"** page listing what the deterministic
  auditors verified *clean* — numeric relationships that checked out, references
  that resolved — the balance column of a real review.

### Gating — all findings get ink (Part III, §18)

The exhaustive default puts **every ledger entry on the paper except the ones
the verifier proved wrong**:

| Entry | Default ink |
|---|---|
| Anchored, `VERIFIED` / `DETERMINISTIC` | cloud (or solid border for deterministic) |
| Anchored, `UNCERTAIN` / `SKIPPED` | **dashed** cloud, `[UNVERIFIED]` prefix |
| Rect-less: sheet-level / absence | margin callout, `[SHEET]` prefix |
| Rect-less: quote matched nothing | margin callout, `[UNANCHORED]` prefix — the hallucination signal, flagged loudly, never dropped |
| `REJECTED` (verifier contradicted it) | **no ink** — but listed on the index page under *"Rejected by verification (n)"* with page links, so nothing is invisible. `ink_rejected=True` (GUI: **Include rejected (grey)**) additionally draws them grey and dashed with a `[REJECTED]` prefix. |

The conservative mode is the opt-in: `markup_verified_only=True` (GUI:
**Verified & deterministic only**, default **off**) suppresses everything but
`VERIFIED` + `DETERMINISTIC`; suppressed entries are tallied as *gated*.

At the end of a markup run the pipeline asserts **every ledger entry is
accounted for** — clouded, margin callout, or rejected-indexed — and logs the
tally (`Ledger 47: 39 clouded, 6 margin, 2 rejected (indexed)`), which also
appears in the GUI completion summary, the report's findings card, and
`ctx.ledger_tally` / `ctx.ledger_tally_line`. The tally describes PDF ink, so
runs without markups (reference audit only) leave it empty.

The writer opens the original read-only and saves a *new* file (the source is
never touched), then reopens it and checks the annotation count as a self-test.
Every finding — inked or not — is also written to **`findings.csv`**, one row per
finding with every field flattened (`qc_id` first; provenance in the `sources`
column; citation columns at the end), UTF-8 with a BOM and CRLF line endings so
Excel on Windows opens it cleanly.

## Citation check

Findings often cite code sections (`refs`), and citations have a failure mode of
their own: a drawing citing **2016-era numbering under a 2019 basis** (the
prototype found exactly that — NFPA 13's Table 13.2.1 became §4.3.1.7 in the 2019
renumbering). The drawing set can't validate its own citations, so
`citation_check=True` adds one **web-search-backed model call per unique
citation** (the API's server-side `web_search` tool): does this section — in the
edition the set adopts *and* in the current edition — actually support the
finding citing it?

The **adopted editions** are harvested offline from the sheet text layers (the
general-notes "NFPA 13, 2016 EDITION" claims) and included in the prompt. Each
verdict — `CHECKED_SUPPORTS` / `CHECKED_MISMATCH` / `UNCHECKED` — attaches to
every finding citing that ref and appears in the markup popup, the CSV, and the
report. **A MISMATCH downgrades nothing automatically** — it is surfaced for the
engineer, because sometimes the stale citation *is* the finding. Real-time only
(a handful of interactive calls; ~$0.03–0.08 per unique ref), additive, and
non-fatal: any failure degrades that ref to `UNCHECKED`.

## The findings ledger (Part III)

Every QC item from **every** channel becomes an entry in one append-only
per-run **findings ledger** — and everything downstream (anchoring,
verification, the citation check, the markup writer, the CSV/JSON exports, the
report's findings table, the index page) consumes the ledger and nothing else.
If an item is not in the ledger it does not exist; if it is, the coverage
assertion guarantees it is accounted for on the PDF.

Duplicates **merge at ingest** (same sheet + rect overlap, same tile, or strong
text overlap): merging unions the provenance, keeps the most severe severity,
prefers the longest verbatim quote, and preserves the best anchor/verification
either member carries — so an auditor's pre-anchored `DETERMINISTIC` duplicate
*upgrades* a model entry. Multi-source provenance doubles as a confidence
signal, shown as chips in the report rows and the markup popups
(`prose+json+critique×2`). The `QC-###` numbers are assigned when the ledger
freezes.

**Source-tag glossary** (`Finding.sources`):

| Tag | Channel |
|---|---|
| `digest_json` | the digest's machine-read findings block |
| `digest_prose_coordination` / `digest_prose_conflict` | harvested digest prose sections |
| `critique_1` / `critique_2` | the critique's self-consistency reads (both = corroborated) |
| `cross_qc` | the cross-sheet conflict hunt |
| `synthesis_prose` | harvested synthesis conflict statements |
| `auditor_reference` / `auditor_arithmetic` / `auditor_naming` / `auditor_titleblock` / `auditor_sheet_index` | the deterministic auditors |
| `focus_prose` | per-sheet Focus sections (only with `focus_findings_to_markups=True`) |

### Prose harvest — the legacy channel's guarantee

The prose digest predates the structured findings and feeds a downstream
consumer, so it is never modified — it is **mirrored**. Three layered
mechanisms make the mirror a guarantee: (1) the digest prompt requires every
prose Coordination/Conflict item to also appear in the JSON block; (2) the
harvester splits those prose sections into items (using the same section
grammar as the report's "⚠ Issues only" filter) and fuzzy-matches each against
the same-sheet ledger entries — a match just tags provenance, free; (3) each
unmatched straggler gets **one small structuring call** (item + the sheet's
text layer → one finding with a verbatim quote), and if even that fails a
**degraded entry** is ingested — the prose item verbatim, sheet-level — which
still reaches the PDF as a margin callout. **No prose QC item can fail to
produce a ledger entry.** Synthesis prose contributes its conflict statements
the same way, anchored on the first sheet each names and dual-anchored when a
second sheet is named.

## Deterministic auditors

Alongside the model reads, the analyzer runs a **battery of deterministic,
zero-API auditors** over the extracted vector text layers — no model call,
milliseconds of CPU. They catch the class of defect a vision model is *unreliable*
at but code is *exact* at: a stale cross-reference, a column that doesn't add up, a
tag spelled two ways, a title-block field that drifted, an index that disagrees
with the set. Every finding they emit is anchored to its own word rectangle and
marked **`DETERMINISTIC`** — trusted without a model re-check — so it is clouded
onto the reviewed PDFs by default when QC Markups is on.

They live in the `drawing_analyzer.auditors` package; `run_auditors(rendered_sheets,
claims=…)` runs the whole battery and returns the combined findings plus a small
`stats` tally. Each auditor is isolated, so one failing never loses the others
(I-3). The battery wires into a run through `reference_audit=True` (or the GUI's
**Reference audit** checkbox); its findings arrive on `ctx.reference_findings`,
join `ctx.all_findings`, and the checks-passed tally lands on `ctx.audit_stats`.

| Auditor | Module | What it catches | Anchoring | Severity |
|---|---|---|---|---|
| **References** | `auditors.references` | Stale / missing cross-references (`SEE DRAWING X`, detail bubbles `NN/X`, CSI spec sections) resolved against the set inventory | the reference's own words | medium (miss), low (spec/malformed) |
| **Arithmetic** | `auditors.arithmetic` | Numbers that don't add up — column totals, density × area = demand, base area × 1.3 = design area — **computed by the host, never the model** | the claim's verbatim quote | graded by magnitude |
| **Naming** | `auditors.naming` | The same thing tagged two ways across the set (`C1R` vs `C1-R`; a one-off `A1-2` drifting from the `A2` vocabulary) | each drifting occurrence | low (question) |
| **Title-block** | `auditors.titleblock` | A project-number / date / field value that drifts on one sheet from the set-wide norm | the drifting token | low (coordination) |
| **Sheet-index** | `auditors.sheet_index` | A drawing index that lists a sheet not in the set, or omits one that is | the index entry / header | medium / low |

The **references** auditor learns the set's own sheet-ID grammar from each sheet's
title-block ID (so it works across offices without a hardcoded numbering scheme),
harvests trigger phrases and detail bubbles, and resolves each pointer: present →
no finding; well-formed but **not present in the provided set** → a finding with
the closest in-set ID suggested by edit distance; malformed → a likely typo. It
never claims a sheet *doesn't exist* — only that it *isn't in the set you
provided* — because a partial set legitimately omits sheets. On a real 8-sheet
fire-protection set this alone caught three genuine coordination errors.

### The numeric-claims contract (arithmetic auditor)

The arithmetic auditor embodies the tool's core principle — *coverage proposes,
precision disposes* — for the one thing a vision model is worst at: mental
arithmetic on a table it just transcribed (the prototype watched one misread a
flow-test total, `540` → `660`). So the model never calculates. The critique and
cross-sheet QC passes emit, alongside their findings, a **`claims`** array — the
numbers they read and how those should relate:

```json
{
  "sheet_id": "F-D-01-1",
  "quote": "20  20  20   TOTAL  540",
  "kind": "sum",                  // "sum" | "product" | "factor"
  "terms": [20, 20, 20],
  "expected": 540,
  "note": "flow-test column total"
}
```

The host then **does the arithmetic itself** — parsing every term to an exact
decimal (tolerant of commas, units, and fractions like `2 1/2`), adding or
multiplying with the standard library, **never `eval`, never the model's answer**
— and raises a finding only when the numbers genuinely don't add up (`base area ×
1.3 = 1950`, but the DIPA row still states `1500`). Relationships that check out
are counted, not flagged, and surfaced in the report as *"N numeric relationships
checked ✓"* — the balance column of a real review.

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
| `DRAWING_ANALYZER_VERIFY_MODEL` | Opus 4.8 | Per-finding verification model (crop + short prompt). |
| `DRAWING_ANALYZER_CRITIQUE_MODEL` | Opus 4.8 | Critique-pass vision model (`critique=True`). |
| `DRAWING_ANALYZER_CROSS_QC_MODEL` | Opus 4.8 | Cross-sheet QC model, text-only (`cross_qc=True`). |
| `DRAWING_ANALYZER_CITATION_MODEL` | Opus 4.8 | Citation-check model, with web search (`citation_check=True`). |
| `DRAWING_ANALYZER_HARVEST_MODEL` | Opus 4.8 | Prose-harvest structuring model (one small call per straggler). |
| `DRAWING_ANALYZER_CHAT_MODEL` | Opus 4.8 | The HTML report's in-browser **Ask AI** assistant (needs current-generation web-search / thinking support). |
| `DRAWING_ANALYZER_WEB_SEARCH_TOOL_TYPE` | `web_search_20260209` | Server-side web-search tool type string (survives an API rename). |
| `DRAWING_ANALYZER_MARKUP_APPENDIX` | off | Append the "checked and consistent" page to reviewed PDFs. |
| `DRAWING_ANALYZER_CRITIQUE_RUNS` | `2` | Critique self-consistency reads to merge (`1` disables it). |
| `DRAWING_ANALYZER_ARITHMETIC_REL_TOL` | `0.01` | Arithmetic auditor's relative match tolerance (drawings round). |
| `DRAWING_ANALYZER_NAMING_DOMINANT_MIN_FREQ` | `2` | Naming auditor: occurrences that make a tag "established" vocabulary. |
| `DRAWING_ANALYZER_NAMING_DRIFT_MAX_FREQ` | `2` | Naming auditor: a tag is only flagged as drift when this rare. |
| `DRAWING_ANALYZER_PROFILES_DIR` | `~/.drawing_analyzer/profiles` | User review-profile directory (wins over built-ins on name). |
| `DRAWING_ANALYZER_MAX_WORKERS` | `4` | Real-time digest concurrency (`1` = sequential). |
| `DRAWING_ANALYZER_UPLOAD_WORKERS` | `6` | Files-API image-upload concurrency per sheet (`1` = sequential). |
| `DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK` | off | Also drop near-blank tiles (PNG-byte threshold), not just pixel-uniform ones. |
| `DRAWING_ANALYZER_NEAR_BLANK_MAX_BYTES` | `3072` | Near-blank PNG-byte threshold (only when the above is on). |
| `DRAWING_ANALYZER_CACHE_PATH` | `~/.drawing_analyzer/drawing_digest_cache.json` | On-disk digest cache. |
| `DRAWING_ANALYZER_CACHE_PERSIST` | on | Disable to keep the cache in-memory only. |
| `DRAWING_ANALYZER_DIAGNOSTICS` | on | Set `0`/`false` to disable the rotating `drawing_analyzer.log` diagnostics file the GUI writes. |
| `DRAWING_ANALYZER_DEBUG` | off | Also route the Anthropic SDK / httpx wire-level logs (status codes, request-ids, retries) into the diagnostics file. |
| `DRAWING_ANALYZER_CACHE_DIAGNOSTICS` | off | Request the prompt-cache diagnostics beta on API calls (operator debugging only). |

## Testing

```bash
python -m pytest
```

The suite is hermetic — no API key, no network. Tests that render real PDFs are
skipped when PyMuPDF is unavailable. `tests/test_drawing_acceptance.py` encodes
the QC acceptance script end to end (a fresh both-checkbox run, the reviewed-PDF
appearance streams, the stale-reference suggestion, a zero-digest-API cached
re-run, and the raster fallback) against fake clients, so the whole findings →
verify → cloud chain is exercised without a key.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for a consolidated record of changes,
including the QC findings / verification / markup integration and the periodic
re-verification of the Anthropic vision / Files / Batches API facts these
constants depend on.

## Licensing

This project depends on **[PyMuPDF](https://pymupdf.readthedocs.io/), which is
licensed AGPL-3.0**, so the project is distributed under **AGPL-3.0-or-later** (see
`LICENSE`). All PyMuPDF usage is isolated to exactly **two** modules —
`src/drawing_analyzer/render.py` (rasterizing sheets and crops) and
`src/drawing_analyzer/annotate.py` (writing cloud annotations onto reviewed
PDFs) — so the PDF backend can be swapped for a permissively-licensed one by
rewriting just those two files, should you want to relicense.

For the rasterization side, `pypdfium2` + `Pillow` is a drop-in permissive
replacement. The markup writer is the harder swap: `pypdf` can build `/Square`
annotations with a cloud border-effect dict (`/BE {/S /C /I 2}`), but it does
**not** generate the appearance stream (`/AP`) that PyMuPDF's `annot.update()`
produces, so some viewers render those annotations blank — which is why PyMuPDF
is used here. That trade-off is documented in `annotate.py`'s module docstring.
