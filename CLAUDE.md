# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"      # engine + pytest   (GUI too: pip install -e ".[gui,dev]")
python -m pytest             # full suite — hermetic: no API key, no network
python -m pytest tests/test_drawing_ledger.py                # one file
python -m pytest tests/test_drawing_ledger.py::test_name     # one test
drawing-analyzer             # launch the GUI   (or: python -m drawing_analyzer)
```

Python 3.11+. No linter/formatter is configured. The `network` pytest marker is
reserved for tests that need real API access; everything that runs by default
uses the fakes in `tests/fixtures/fake_anthropic.py`.

## Architecture

A vision pipeline (src layout, package `drawing_analyzer`): each PDF page is one
*sheet*, rendered to an overview + 6×6 tile grid and sent — together with its
verbatim vector text layer — in a single vision request per sheet, returning a
structured Markdown digest plus a machine-readable findings block.
`pipeline.extract_drawing_context()` orchestrates everything and returns a
`DrawingContext`. The per-module map lives in `src/drawing_analyzer/__init__.py`.

**Run configuration & status (Phase 23A, models.py).** The GUI checkboxes and the
public API keyword args are resolved **once** by `resolve_run_configuration()` into
an immutable `RunConfiguration` (§15.1) — the single place `qc_markups=True` becomes
the exhaustive stack, `reference_audit` (alone) the free zero-API auditor battery,
and neither the standard path (findings + text retained and offline-anchored for
free, DA-012). Every stage reads the resolved config; no call site re-derives the
booleans. Each QC stage records a typed `StageResult`; `roll_up_qc_status()` folds
them (+ Phase 21 `coverage_status`) into one `qc_status` (`NOT_REQUESTED` / `COMPLETE`
/ `PARTIAL` / `FAILED`, §3.3). The Phase 23 completeness gate is **OPEN** (Phase 26B
§18.0): a clean NORMAL exhaustive run earns `COMPLETE`; the §8 phase-gates are
permanent regressions enforced by the stage statuses themselves (a failed
reconciliation / unchecked cited claim / missing evidence leg / mutated source
holds a required stage at PARTIAL, which the roll-up can never call COMPLETE).

**Usage & cost (Phase 23B, §15.6).** Token/cost accounting is an **append-only**
`RunUsage` ledger (`ctx.run_usage`): every API call/attempt appends a priced
`UsageRecord` (family, `transport` REAL_TIME/BATCH/CACHE, model, tokens, tool uses,
cache-hit, `estimated_cost`), and the run's `total_*` are *derived* sums — no stage
can overwrite another's counters (the old `v_in, v_out = vres…` overwrite is gone).
`core.pricing.usage_record_cost` prices one record by its rate class; costs carry a
`PRICING_EFFECTIVE_DATE`. `cost.estimate_exhaustive_run_cost` is the pre-run
per-stage estimate (verification/citation quoted as a low–high band).

**Run journal & manifests (Phase 26A, §18.1–18.4).** Every run owns a
`RunJournal` (`ctx.run_journal`, `run_journal.py`): an append-only, thread-safe
event trace whose every field is **sanitized at emit time** (shared Phase 17
`redact_secrets` + an absolute-path scrubber → `.../basename`; one line;
bounded). The pipeline emits RUN_START/INPUT_*/SHEET_DIGESTED/STAGE_START/
STAGE_END/LEDGER_*/MARKUP_RECEIPTS/USAGE_TOTALS/RUN_END; `ctx.input_inventory`
and `ctx.prose_accounting` are retained for the manifests. Every export gets
`run.log` (rendered §18.2 log, UTF-8+CRLF) and `run_manifest.json`
(schema v1: status/config/sources-without-paths/stages/usage/coverage + sha256
of every artifact), written **last** in the §18.4 non-circular order (artifacts
→ markup manifest → run.log → run manifest, which excludes only itself). Usage
`stage_instance` labels are portable (`digest:SRC-0001:p0`, never a path).

**Digest path:** `tiling.py` (pure geometry) → `render.py` (rasterization) →
`digest.py` (prompt + tolerant findings-block parser), or `batch_digest.py`
(Message Batches + Files APIs, ~50% cheaper) → `digest_cache.py` (two-level
content-keyed cache — a hit skips rendering entirely and restores parsed
findings for free).

**QC stack** (each stage optional and independently cached):

- *Finders:* the digest's findings block; `critique.py` (a second full-coverage
  vision read, run twice — self-consistency merge sets `reproduced`);
  `cross_qc.py` (text-only cross-sheet conflict hunt; dual anchors via
  `also_on` legs); `auditors/` (five deterministic zero-API auditors over the
  text layers, **all** grounded on the shared `auditors/sheet_ids.py` grammar
  foundation — Phase 25 §17.2/17.3: `id_signature`/`learn_grammar` learn the set's
  hyphenated/compact/dotted numbering convention, `classify_reference` +
  `is_non_sheet_reference` adjudicate a reference against it with a negative corpus
  so a code/tag/voltage/RFI/dimension never becomes a sheet finding);
  `prose_harvest.py` (mirrors prose Coordination/Conflict items,
  synthesis conflicts, and opted-in focus items into findings — match first,
  one small structuring call for stragglers, degraded sheet-level entry on
  failure).
- ***`ledger.py` is the exclusive findings container*** (Part III §16): every
  channel ingests into it with source tags. Dedup is conservative and lossless
  (Phase 20 §12): a tile/rect overlap is never sufficient — merges need semantic
  sameness with **compatible critical signatures** (`_signatures_compatible`:
  tags, measurements, absence polarity, cross-sheet legs); merging keeps
  **coherent grounding** (the text/quote/tile bundle is atomic, from one
  representative chosen by a total quality order; the loser's quote → the new
  `supporting_quotes`), unions `sources`, keeps most-severe severity, and
  preserves auditor anchors + `DETERMINISTIC` verdicts. Explicit lifecycle:
  `seal()` (OPEN→SEALED) → anchor → `reconcile_post_anchor` (Pass B) →
  `number()` (SEALED→NUMBERED assigns positional `QC-###` **after** anchoring).
  A post-seal add marks the run incomplete (no `QC-XTRA` masquerade).
  Anchoring, verification, the citation check, the markup writer, the exports,
  and the report consume ledger entries and nothing else.
- *Disposition:* `anchor.py` (quote → PDF rect, tiered
  EXACT/FUZZY/TILE/UNANCHORED — UNANCHORED is the hallucination signal) →
  `verify.py` (high-DPI crop re-check → VERIFIED/REJECTED/UNCERTAIN) →
  `citation_check.py` (server-side web-search per unique code ref) →
  `annotate.py` (§18 gating + Phase 21 receipts: every entry gets ink except
  REJECTED/gated, which get reconciled index rows; rect-less entries become
  margin callouts **packed into visually-clear bands** — validated against words,
  a rendered occupancy mask, and siblings so they never obscure the drawing
  (Phase 25 §17.6); one that will not fit overflows to an appended *AI Review
  Notes* page with a GOTO link back, rerouted to a `REVIEW_NOTES` placement; the
  writer stamps every mark, reopens the saved PDF, and reconciles
  each **placement** against what it finds — returning a `MarkupRunResult` with
  per-placement `WRITTEN`/`INDEXED`/`FAILED` receipts and a receipt-derived
  `coverage_status`) → `export.py` (`markup_manifest.json`) / `html_report.py`.

`core/` is a shared kernel (model ids + env overrides in `api_config.py`, key
store, pricing, tokenizer). `reference_audit.py` is a back-compat shim over
`auditors/references.py`.

## Binding invariants (cited by number in code comments)

- **I-1 — full coverage:** every sheet is read whole (overview + all tiles);
  optimizations may never drop content-bearing tiles.
- **I-2 — the prose digest is sacred:** nothing may alter `combined_text`. The
  findings block is stripped byte-exactly; prose QC items are *mirrored* into
  the ledger, never moved or edited.
- **I-3 — QC is additive and non-fatal:** every QC stage catches its own
  exceptions, appends to `ctx.errors`, and lets the standard deliverable ship.
- **I-4 — hermetic tests:** use `tests/fixtures/fake_anthropic.py`
  (`FakeMessage`/`FakeTextBlock`/`FakeUsage`) and the routing-client patterns
  in existing tests. No test may hit the network or need a key.
- **I-5 — PyMuPDF isolation:** only `render.py` and `annotate.py` may import
  PyMuPDF. The README's AGPL licensing story depends on this; `anchor.py` and
  `tiling.py` work on extracted word rectangles precisely to preserve it.
- **I-6 — cache correctness:** prompt versions are content hashes
  (`DIGEST_PROMPT_VERSION`, `CRITIQUE_PROMPT_VERSION`), so prompt edits
  auto-invalidate; `digest_cache._SCHEMA_VERSION` is manual — bump it whenever
  what is stored or sent changes.
- **I-7 — deterministic assembly:** same inputs → same ordering (QC numbering,
  index rows, merged output); no randomness or time-dependence in assembly.
- **The model never calculates:** models transcribe `NumericClaim`s;
  `auditors/arithmetic.py` does the math with `Decimal` — never `eval`, never
  the model's own arithmetic. The host *operation* is always deterministic, but the
  *operands* are trusted (`DETERMINISTIC` + auto deterministic-only ink) only when
  the claim's quote independently carries every one (`operand_origin=TEXT_EXTRACTED`,
  Phase 25 §17.5); a mismatch from `MODEL_TRANSCRIBED` terms stays `UNCERTAIN` and
  is crop-verified before it inks as ground truth.
- **Tiles use the `tile_label` contract (Phase 25 §17.1):** the model returns the
  exact visible label (`"r1c1"`); `tiling.parse_tile_label` converts it to the
  canonical **zero-based** internal `[row, col]`. A legacy `tile` array is accepted
  only as explicit zero-based, bounds-checked — never guessed to be 1-based.
- **Additive serialization:** `Finding.to_dict`/`from_dict` must default new
  fields cleanly so cached payloads from older runs still load.
- **Ledger coverage is artifact-backed (Phase 21, DA-007):** on markup runs every
  ledger entry (and every cross-sheet leg) becomes a planned `MarkupPlacement`;
  the writer stamps each drawn mark with a private PDF key, reopens the saved PDF,
  and reconciles → one `MarkupReceipt` (`WRITTEN`/`INDEXED`/`FAILED`) per
  placement. The tally and `coverage_status` are derived from those receipts,
  **never** from intention (`ink_disposition` remains only a planning helper). A
  placement counts only when its stamped, mandatory component is found again in
  the artifact; missing/failed/duplicate/unexpected → `INCOMPLETE`. Stamps embed a
  per-run id, so prior-run/pre-existing annotations are ignored (DA-029). An
  INCOMPLETE reviewed PDF is renamed `…_reviewed_INCOMPLETE.pdf`; the plan +
  receipts are exported to `markup_manifest.json` (no key, no absolute path).

## PyMuPDF gotchas (hard-won; they crash or render blank)

- A plain FreeText annot rejects `border_color` (raises unless rich text) —
  severity is carried by colored *text* instead.
- For FreeText, `/Contents` IS the displayed text: `set_info(content=...)`
  overwrites what's drawn, so display prefixes (`[UNVERIFIED]`, `[SHEET]`)
  must be composed into the content string, not set afterwards.
- Annot objects unbind when the `annots()` generator advances or the page tree
  changes (`insert_page`): snapshot properties during iteration, re-fetch pages
  by index after inserting, and never call `.get_text()` on an annot.
- `annot.update()` must be called to build the appearance stream (`/AP`), or
  the annotation renders blank in Acrobat/Chromium.
- Base-14 fonts miss `✓`, `…`, and em-dash glyphs — use ASCII in inserted page
  text.
- PyMuPDF is not thread-safe: rendering stays sequential; concurrency lives in
  the API calls.
- **Rotation/CropBox use two coordinate spaces (Phase 19).** `get_text("words")`
  and `add_*_annot()` work in an *un-rotated, CropBox-relative* space; but
  `get_pixmap(clip=...)` clips in the *rotated page-view* space (`page.rect` dims).
  They diverge on a rotated/cropped page. The codebase's canonical space is
  `PAGE_VIEW_V2` (post-CropBox, post-rotation — what the model sees): `render.py`
  moves words into it via `page.rotation_matrix`, `annotate.py` moves rects back
  via `page.derotation_matrix` before drawing (and draws FreeText with
  `rotate=page.rotation` for upright text). Identity on an un-rotated page. Never
  feed a raw `get_text` rect to `get_pixmap(clip=...)`, or a raw view-space rect to
  `add_*_annot()`.
