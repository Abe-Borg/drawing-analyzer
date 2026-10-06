# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"      # engine + pytest   (GUI too: pip install -e ".[gui,dev]")
python -m pytest             # full suite — hermetic: no API key, no network
python -m pytest tests/test_drawing_ledger.py                # one file
python -m pytest tests/test_drawing_ledger.py::test_name     # one test
drawing-analyzer             # launch the GUI   (or: python -m drawing_analyzer)
python scripts/run_acceptance.py   # release gates (PASS/FAIL; hermetic — never the canary)
python scripts/check_browser_suite.py browser-results.xml   # a skip is not a pass
python scripts/measure_evidence_coverage.py --pdf SET.pdf   # coverage scan (zero API calls)
```

Python 3.11+. No linter/formatter is configured (CI runs ruff **correctness
classes only** — E9/F63/F7/F82). The `network` pytest marker is reserved for
tests that need real API access (`tests/test_live_api_canary.py`); everything
that runs by default uses the fakes in `tests/fixtures/fake_anthropic.py`.
`conftest` skips `network` tests only when no real key is set and
`pyproject.toml` sets no default exclusion, so **any entry point that spawns
pytest must deselect the marker itself**: `run_acceptance.py` routes every gate
through `_pytest_cmd()`, which ANDs `not network` into the child's `-m`, and
`tests/test_run_acceptance.py` fails if a bare `"pytest"` argv literal
reappears anywhere else in that script. The trust-gauntlet oracle set and
all-stage scripted client live in `tests/fixtures/gauntlet.py`; release docs
live in `docs/`; `requirements-release.lock` pins release builds.

`pytest -m browser` writes a JUnit report and `scripts/check_browser_suite.py`
fails the job below a floor of genuinely *executed* tests. Failures count as
executed; skips and setup errors do not. The same floor is applied inside
`run_acceptance.py`'s browser gate, through the same script. `release.yml`'s
`publish` needs `gates` (full `run_acceptance.py`, Chromium, ruff/licenses/
pip-audit) and `gates-windows` (hermetic suite on Windows) in its own `needs`
chain, because branch protection does not apply to a tag push. `ci.yml`
triggers on `v*` tags for visibility only.

## Writing tests

Every test must be able to fail for a behavioral reason. Do not add tests that
only check wording (help text, dialog copy, prompt phrasing, log text), search
source or workflow files for a string, or restate a constant, default, or
registry entry (`assert X == 400_000`, a model id). They break on every copy
edit or model upgrade and catch nothing. Golden cache-key hashes are not
constant pins (they pin a cache contract, I-6), and absence checks that guard
security (escaping, CSP, no `innerHTML`, no key written) stay.

Before adding a test function, add a case to the parametrized test or the test
that already drives that code path. Before adding another end-to-end pipeline
run, check whether the module-scoped gauntlet `oracle` in
`tests/test_drawing_acceptance.py` already observes it. Reuse the existing
fakes (`tests/fixtures/fake_anthropic.py`, `tests/fixtures/gauntlet.py`,
`_FakeClient` in `tests/test_drawing_batch.py`) instead of writing another
routing client. Compare results whose order the code does not promise (anything
built on a thread pool, such as deleted Files API ids) as sorted lists or sets.

## Architecture

A vision pipeline (src layout, package `drawing_analyzer`): each PDF page is one
*sheet*, rendered to an overview + a per-page tile grid and sent — together with its
verbatim vector text layer — in a single vision request per sheet, returning a
structured Markdown digest plus a machine-readable findings block.
`pipeline.extract_drawing_context()` returns a `DrawingContext`. The per-module
map lives in `src/drawing_analyzer/__init__.py`.

- **Config & status** (`models.py`): `resolve_run_configuration()` resolves GUI
  checkboxes and public API kwargs **once** into an immutable `RunConfiguration`.
  `qc_markups=True` is the exhaustive stack; `reference_audit` alone is the free
  zero-API auditor battery; the standard path retains findings and text and
  offline-anchors them. Every stage reads that config. Each QC stage, including
  the digest (`expected=True`), records one typed `StageResult` — the single
  `STAGE_END` for that stage. `roll_up_qc_status()` folds those plus
  `coverage_status` into `qc_status` (`NOT_REQUESTED` / `COMPLETE` / `PARTIAL` /
  `FAILED`). Test a stage's own failure flag **before** any count from its
  result: an exception leaves the result `None`. The completeness gate is open:
  a clean NORMAL exhaustive run earns `COMPLETE`; a failed reconciliation,
  unchecked cited claim, missing
  evidence leg, or mutated source holds a required stage at PARTIAL, which the
  roll-up can never call COMPLETE.
- **Usage** (`ctx.run_usage`): append-only `RunUsage`. Every API call appends a
  priced `UsageRecord` (family, `transport` REAL_TIME/BATCH/CACHE, model, tokens,
  tool uses, cache-hit, `estimated_cost`); `total_*` are derived sums. A stage
  that placed no call and took no cache hit appends nothing. Guard a real-time
  record on the call count alone. `core.pricing.usage_record_cost` prices one
  record; costs carry `PRICING_EFFECTIVE_DATE`. `RunUsage.is_billable_but_unpriced`
  is the single rule for billable usage the table cannot price: it counts cache
  read/write tokens, and tool uses **by value** (`_record_usage` drops zero
  counts before storing). Do not restate that rule. `cost.estimate_exhaustive_run_cost`
  is the pre-run estimate (verification/citation as a low–high band); price every
  stage with **its own resolved model** and the runtime's own `critique_runs()`.
  Count critique imagery with the critique model, never reused from the digest
  count (`estimate_image_tokens` clamps at 4784 hi-res / 1568 standard).
- **Image-token geometry:** the GUI starts drawing preflight whenever files
  are loaded, even with no installed profiles. It prices from real page shapes
  once that scan has measured the current file list, and from the conservative
  allowance otherwise. Profile suggestions apply only to installed profiles.
  There is no separate scan. `profiles.preflight_scan`
  returns sheet ids and `SheetCostBasis` from one walk; `estimate_*_cost(bases=…)`
  uses them **only when they cover every sheet** — a partial list falls back
  whole. An unreadable page inside a measured set still takes the conservative
  allowance; `shape_aware` comes from `ImageTokenEstimate.fully_measured`, never
  list length. Bases are gated on `source_registry.sources_fingerprint` (path +
  size + mtime), re-checked at consumption. The GUI holds them under the same
  generation guard as the profile suggestions. `_add_pdfs` refreshes the summary
  before preflight clears the previous selection's bases.
  `pipeline.estimate_image_tokens_for_set` remains a true upper bound: without
  sizes it covers the adaptive 100-image budget (478,400 tokens/page on Opus 5).
  Explicit 6×6 / fixed-grid mode keeps the legacy 177,008 allowance.
  `cost.estimate_image_tokens_for_bases` prices each page from a `SheetCostBasis`
  (displayed w/h, vector/raster/unknown, capped text length, geometry
  availability and error — no words, full text, image bytes, or path). Aspect
  ratio and whether the page has words come from a scan that never rasterizes
  (`render.iter_sheet_cost_bases`, or `models.sheet_cost_basis(geom)`).
  `tiling.image_pixel_sizes` is the single home for tile pixel geometry and
  mirrors `(rect * matrix).irect`, which is **position**-dependent. Count every
  tile: blank suppression is decided from rendered pixels and must never be
  predicted from word absence. An `unknown` page takes the conservative
  allowance and is never assumed vector; an unmeasurable page is still quoted.
- **Physical-size grids:** `tiling.choose_grid` is the single resolver for
  rendering, no-render geometry, render identity and image cost geometry.
  Default `rows=None, cols=None` means adaptive; pinning either dimension wins
  (the unpinned dimension stays six). `DRAWING_ANALYZER_FIXED_GRID=1`, read per
  call, restores fixed 6×6. Search rectangular grids within 100 images, price
  each with `image_pixel_sizes` + Opus 5's tokenizer, and minimize image tokens
  subject to every overlapping tile meeting ANSI E's 44×34 inch 6×6 minimum
  DPI (183.39 vector / 234.17 raster at 8% overlap). Compare like with like and
  resolve the <=20-image 2576 px target versus >20-image 1560/1992 targets
  before testing DPI. A page with no feasible grid fails explicitly. Cost
  estimation substitutes the conservative allowance and discloses the fallback;
  digest and critique prescans report that page's failure and continue, keeping
  both stages partial while processing the other pages. Keep I-1.
  ANSI E (34×44) and ARCH E1 (30×42), either orientation, retain 6×6 and their
  cache keys; no prompt/schema/render-identity version bump is needed because
  actual rows/cols/target already key the render. Level 2 hashes PNG bytes plus
  tile layout on non-6×6 grids, so blank suppression cannot collide grids;
  6×6 retains the legacy key format.
  Consumers must use `RenderedSheet` / `SheetGeometry.rows, cols`, including
  label parsing, TILE anchors, cross-QC legs, verify/investigate crops, artifacts,
  and critique spool/upload matching. Never compare adaptive pages to global
  `None` grid arguments. Cost bases choose the same grid before pricing it with
  the stage's model; a cheaper model changes pricing, not the selected geometry.
  Measured Opus 5 image tokens per read, before blank suppression: vector
  Letter 93,013 → 7,399 (20×1, −92.0%, 183.53 DPI); vector Tabloid 77,905 →
  14,352 (2×1, −81.6%, 234.18 DPI); raster Letter 151,619 → 9,568 (1×1,
  −93.7%, 234.18 DPI). The 20×1 strip result follows the image-count target
  discontinuity; square grids are not necessarily the token minimum. Digest
  and both critique reads benefit. E / E1 counts and images stay unchanged.
- **Work dirs:** verify, investigate, and markup create a `drawing_qc_*` temp
  dir when the caller supplied no `work_dir`. `pipeline._prune_stale_work_dirs`
  reaps them on the way **in** (`DRAWING_ANALYZER_WORKDIR_MAX_AGE_HOURS`, default
  24, `0` disables, resolved at call time). Do not prune at run end: export
  copies evidence out after `extract_drawing_context` returns. Judge age with
  `_tree_is_recent`, not the directory mtime (crops land in
  `evidence/<QC-###>/<leg>.png`); an empty young dir still needs the directory
  check. Uncertainty fails safe (keep). The zero-sheet early return cleans up
  the dir it created, in the same form as its `block_reason` twin.
- **Journal** (`run_journal.py`): append-only, thread-safe `RunJournal`. Every
  field is sanitized at emit (`redact_secrets` plus an absolute-path scrubber →
  `.../basename`, one line, bounded). Events: RUN_START / INPUT_* /
  SHEET_DIGESTED / STAGE_START / STAGE_END / LEDGER_* / MARKUP_RECEIPTS /
  USAGE_TOTALS / RUN_END. Every export gets `run.log` (UTF-8+CRLF) and
  `run_manifest.json` (schema v1: status/config/sources-without-paths/stages/
  usage/coverage + sha256 of every artifact), written **last**: artifacts →
  markup manifest → run.log → run manifest (excludes only itself).
  `stage_instance` labels are portable (`digest:SRC-0001:p0`). `private_roots`
  matches case-insensitively, across both separators, only at a component
  boundary (`_private_root_re`, `(?=[\\/]|$)`). Every renderer of both artifacts
  gets that list. `redact_for_display` is the same boundary without flattening
  or truncation, for host status/error text only — never digest prose (I-2) or
  model findings.
- **Resource pressure** (`resource_pressure.py`): the per-run starvation record
  (`ctx.resource_pressure`), rendered into run.log (`Starvation:` header line +
  *Resource pressure* section), `run_manifest.json` (`resource_pressure`), the
  report's run-record block and the GUI completion summary. One process-global
  active recorder per run (`tracked_run` on `extract_drawing_context`;
  `current()`), the diagnostics-logger pattern. **Every transient retry loop
  goes through `digest.transient_retry_wait(exc, attempt, max_retries, sleep,
  stage=…)`**, which records the wait or the give-up; never reintroduce a bare
  `sleep(_retry_backoff_seconds(attempt))`. The upload, files-cleanup and
  batch-results loops call `resource_pressure.note_api_retry` /
  `note_api_give_up` directly. Exhausted agent budgets are
  `note_budget_exhausted(stage, kind, count=…)`; a zero count records nothing.
  The host sampler is a daemon thread on an `Event.wait` cadence
  (`DRAWING_ANALYZER_RESOURCE_SAMPLE_SECONDS`, `0` disables); its scheduling lag
  is the CPU signal. Probes are stdlib + ctypes (no psutil, no PyMuPDF); a
  metric that cannot be read is `unavailable`, never 0. Disk is reported by
  label (`temp` / `work_dir` / `cache`), never by path. Stored API events and
  journal incidents are bounded; the aggregates count everything. Advisory and
  never fatal. Tests inject `probe=` / `interval=` and patch
  `digest._retry_backoff_seconds` to 0 so a 429 fixture never sleeps.
- **Digest path:** `tiling.py` (geometry) → `render.py` (raster) → `digest.py`
  or `batch_digest.py` (Message Batches + Files) → `digest_cache.py` (two-level
  content-keyed cache; a hit skips rendering and restores parsed findings).
  Findings fences are **line-anchored**, accept 3+ backticks or tildes, and a
  closer must match its opener's character and length. Never cache a truncated
  read: both transports treat an unfinished reply (empty or cut off) as an
  error, retry once at `digest.MAX_TOKENS_RETRY_CEILING`, and refuse the cache
  write if it is still cut off. Real-time usage accumulates across both
  attempts and falls back to the truncated first read if the raised-cap call
  cannot land. Critique does not re-rasterize: `render_spool.py` rebuilds the
  same `RenderedSheet` from the digest's PNG bytes; the batch path adopts the
  digest's terminal uploads. A second render is the per-page fallback
  (`_one_page_fallback` re-renders exactly the page that failed). A failed spool
  write leaves the key absent (I-3).
- **Batch recovery** stays on the batch transport for the pipeline
  and records every accepted digest, follow-up, resubmission, and critique batch
  in the digest cache's `pending_batches` SQLite table before polling. Receipts
  carry batch/custom IDs, both cache keys, sheet identity, transport, submit
  time, and result-retention deadline (29 days from API creation). Run start
  collects terminal receipts into the cache before new work; live or unreadable
  receipts block duplicate requests. Every `results()` stream retries transient
  failures from byte zero through `batch_recovery.read_batch_results`. An
  exhausted read returns retriable per-sheet errors (I-3) and keeps the receipt;
  it never submits another paid round just to retry a download. Successful cache
  writes must be durable before deleting receipts; expired receipts are pruned.
  Explicit memory-only caches keep receipts in memory, as with digest entries.
  Receipt recovery and blocking also run with ordinary cache reuse disabled and
  after a transport switch. If a receipt write fails after acceptance, request
  cancellation and confirm a terminal status before releasing the uploads;
  unconfirmed cancellation retains them and stops further paid recovery rounds.
  `retry_failed_items` cancels a stalled batch and resubmits unresolved sheets
  (`_recover_via_batch_resubmit`); there is no real-time recovery path. Never
  silently drop to full-rate real-time; when the rounds or budget are spent,
  unreached sheets keep a retriable batch error. Every site that abandons a
  batch harvests it first (`_harvest_abandoned_batch`): `results()` is filled
  only from a terminal read, so harvest between cancel and the resubmission
  list, **successes only**, and park billed empty attempts
  (`_park_usage_attempts`). Harvest time is additional — add it back to the
  caller's start mark. A batch that will not settle within the bound harvests
  nothing. The collection bound is **24h** (`DEFAULT_BATCH_MAX_ELAPSED_HOURS`),
  overridable via `DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS`, resolved at call
  time from a `None` default. `DETACHED_MOVING` vs `DETACHED` is diagnostic
  only. Stall watch is tiered (`_stall_timeout_seconds`): 25 min primary, 60 min
  on every resubmission; `DRAWING_ANALYZER_BATCH_STALL_TIMEOUT_MIN` overrides
  both. Heartbeat every 5 minutes. An abandoned batch appends a non-billable
  `DigestUsageAttempt` (`billable=False`, `terminal_status="ABANDONED_*"`, zero
  tokens) per sheet, so usage sees every attempt while the image-token estimate
  still counts only response-bearing ones. Each slot records `served_by`.
- **Text extraction** (`render.py`): sheet text comes from
  `page.get_displaylist(annots=False)` via `TextPage.extractWORDS()`
  (`_page_text_and_view_words`, `_page_word_count`, `_page_text_and_word_count`).
  Those words are already PAGE_VIEW_V2; `get_text("words")` is
  rotation-invariant, so `_page_text_and_view_words` owns the conversion for
  both routes. `_RENDER_IDENTITY_SCHEME` is **v4**. See the PyMuPDF gotcha on
  annotation text.
- **Page identity:** any other `/Type /Page` reached by `_page_dependency_sha256`
  is an opaque leaf. A GOTO destination is not hashed; the reference already
  rides the referencing annot, so retargeting still moves the key.
- **GUI** (`gui.py`): console-less entry (`[project.gui-scripts]` on Windows;
  the frozen build is windowed). The guarded `customtkinter` import reports
  through a stdlib `messagebox` and raises **ImportError**, not `SystemExit`
  (`app_entry.py --selfcheck` catches `Exception`). `WM_DELETE_WINDOW` →
  `_on_close_request` (workers are daemons; export runs after analysis returns).
  `report_callback_exception` → `_on_callback_exception`. Both reporters swallow
  every failure of their own channels.
- **`core/`:** model ids and env overrides (`api_config.py`), key store, pricing,
  tokenizer, structured-outputs gate. The tokenizer is estimate-only; the exact
  count is `count_tokens_via_api`, and the local path is the conservative
  safety-factor table. `reference_audit.py` is a shim over
  `auditors/references.py`. No built-in review profiles ship: packaged
  `profiles/` is empty; user checklists live in `~/.drawing_analyzer/profiles/`;
  a worked example is `docs/examples/fire_protection.md`.

**QC stack** (each stage optional and independently cached). Anchoring,
verification, the citation check, the markup writer, the exports, and the report
consume ledger entries and nothing else.

- **Planning:** `set_identity.py` — one text-only call → advisory `SetIdentity`
  (consumers take `SetIdentity | None` and never gate a finding on it). The
  regex edition harvest unions in as `origin="regex"`. Runs on Sonnet 5.5. Coerce
  every list-shaped field through `set_identity._as_list` (a string must not be
  consumed per character). The international code-designation regex is
  **case-sensitive**; `Eurocode` keeps its own case-insensitive group.
  `review_planner.py` — one text-only call for the per-discipline checklist,
  bounded at ≤60 items (`DRAWING_ANALYZER_MAX_PLAN_ITEMS`), overage taken from
  the **longest** plan each round; overlong items are dropped, never truncated.
  Every code-based item names code + section + edition inline and never invents
  a section. Plans become `Profile` objects injected **after** user profiles
  (`source="model"`), so `profiles_cache_fragment` stays correct. Both stages
  cache in `DigestCache` (`stage=identity` / `stage=review_plan`) and ride the
  critique stack (`run_identity` also on with citation alone); the standard run
  stays zero-extra-cost. Artifacts: `set_identity.json`, `review_plan.md`, a
  manifest `set_identity` key, and an additive combined-text section (I-2).
  Identity feeds
  `check_citations(identity=)` and `cross_sheet_qc(identity=)`.
- **Finders:** the digest findings block; `critique.py` (a second full-coverage
  vision read, twice; self-consistency sets `reproduced`). On the real-time path
  the two reads prompt-cache their shared image prefix when `runs>=2`; the batch
  path stays uncached. `use_batch` resolves from `DRAWING_ANALYZER_USE_BATCH`
  when the caller leaves it `None`. Structured outputs are opt-in and **critique
  only** among high-volume calls (`DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS=1`
  + registry capability + that stage's `StructuredOutputsGate`). `prose_harvest`
  and `verify` reuse the gate type under their own env vars and their own latch
  instances. `attach_format` / `detach_format` is the one request rule; the
  critique latch's rejection vocabulary overlaps investigation's only while no
  request carries both features. Off by default: vision × schema is undocumented
  upstream and is settled by `test_live_critique_under_output_config_format`.
  `_CRITIQUE_STRUCTURED_INSTRUCTION` is derived from
  `_CRITIQUE_FINDINGS_INSTRUCTION` by substitution, with an import-time assert.
  The schema omits the 40-finding cap (`maxItems`, `minimum`/`maximum`,
  `minLength`, and `minItems`>1 are rejected); the cap stays host-enforced.
  Merge `format` into `output_config`. Cache-neutral: `CRITIQUE_PROMPT_VERSION`
  is untouched and `structured_key` folds in only when set; it rides **both**
  cache levels. Rebuild both store keys after the reads (the latch can flip;
  `_ingest_miss` keeps the render identity). The batch transport pins
  `structured=False`. `cross_qc.py` is the text-only cross-sheet conflict hunt
  (dual anchors via `also_on`). `auditors/` holds five deterministic zero-API
  auditors on `auditors/sheet_ids.py` (`id_signature` / `learn_grammar`,
  `classify_reference`, `is_non_sheet_reference`). `_ANNOTATION_PREFIXES`
  (REV/DET/DWG/TYP/SIM/NTS) stays separate from the transmittal set; paper sizes
  are absent from the corpus. `references.detect_sheet_id_word` vetoes with
  `never_a_sheets_own_id` — a strict subset of the reference corpus, so
  `_TRANSMITTAL_PREFIXES` is excluded — before the position score, and never
  with the learned grammar (a same-shape distractor can still win; a two-pass
  harvest is not done). Memoize it on the sheet object (`None` needs a
  sentinel). `_merge_adjacent_id_words` caps on **length**, not fragment count.
  `naming.py` reports drift with no frequency winner only when both spellings
  share an `_arrangement`; an established winner still outranks structural
  doubt. `sheet_index.py`'s harvest stays unbounded; both diff directions
  already run `classify_reference`. `prose_harvest.py` mirrors prose
  Coordination/Conflict items, synthesis conflicts, and opted-in focus items
  (match first; one structuring call for stragglers on Sonnet 5.5 at
  `EFFORT_LOW`). Its boilerplate filter is anchored at **both** ends, length
  floor 8; the `filtered` count is observational and feeds neither `missing` nor
  `complete`. Opt-in `DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS`:
  `HARVEST_STRUCTURED_SYSTEM_PROMPT` is one substitution on the fenced prompt;
  `HARVEST_FINDING_SCHEMA` mirrors that field list one-for-one
  (`additionalProperties: false`; enums from `digest._MODEL_FINDING_CATEGORIES`
  / `_FINDING_SEVERITIES`). `HARVEST_STRUCTURED_PROMPT_VERSION` folds into the
  item key only when the request carried the schema; re-resolve the store key
  after the call. A bare-JSON parse is attempted only under the structured
  contract, and a fenced reply still wins.
- **Cross-QC grounding** reads `models.sheet_evidence_text(geom)`, not the capped
  `sheet_text`. A present-but-empty full text means no textual evidence and does
  not fall back; `None` means unavailable; a non-string is unavailable. Prompt
  bytes stay capped. `_cross_qc_cache_key` adds `evidence_sha256` **only for a
  truncated sheet**. Grounding is three-state (`classify_quote_evidence`):
  `TEXT_GROUNDED` / `NOT_MATCHED_IN_TEXT` / `TEXT_EVIDENCE_UNAVAILABLE`. Ask the
  **reported tile** (`_tile_has_words`) before classification; an unknown tile
  answers that there was text. A quote unmatched where the sheet has text is a
  discard. An absent quote is `TEXT_EVIDENCE_UNAVAILABLE`. Reduced trust carries
  `evidence_state` and must reach verification: `anchor._anchor_one` falls back
  to the tile **only** for that state. `fact_tile_lookup` rejoins a leg by
  `(handle, normalized quote)`; the key is not unique, and a collision drops
  rather than picks — only unanimity resolves. The reduced-trust reason is
  per finding (`models.reduced_trust_reason`): `[NO TEXT TO CHECK]` vs
  `[NO QUOTE TO CHECK]`. It is a note on the quote, not a status chip.
  `evidence_state` rides the atomic grounding bundle; each per-leg mark gets
  that leg's state. Sheet handles canonicalize with
  `auditors.sheet_ids.normalize_sheet_id` at all four compare sites (`_norm_id`,
  `critique._leg_targets`, `critique._dedup_claims`,
  `auditors.arithmetic._claim_dedup_key`). That host-side binding carries
  `_CROSS_QC_CACHE_CONTRACT` **3**. Sharded-path `CrossQCDiscardCounts` are
  count-only and observational (`discards is None` means not recorded; the
  whole-set ≤40 path does no host-side grounding).
- **Ledger** (`ledger.py`): the exclusive findings container. See the ledger
  rules under Binding invariants.
- **Edition audit:** `citation_check.reconcile_cited_editions` is zero-API and
  **strictly pre-seal** (gated `run_citation or run_auditors`; stage
  `edition_audit`). Basis = identity `adopted_codes` (model entries need a
  quote; regex-union entries are ignored) ∪ a citation-shaped regex harvest (a
  mention followed by a section marker is a citation, never an adoption). Both
  operands re-found in sheet text → medium + `DETERMINISTIC`; otherwise low,
  advisory-labeled, and crop-verified. Anchor to the stale-edition span, never
  the citing finding's quote.
- **Text normalization:** `anchor._normalize` rewrites vulgar fractions
  **before** NFKC (`_VULGAR_FRACTION_TABLE`). `_CHAR_FOLD` also covers the
  fraction slash, division slash, and multiplication sign. Invisible code points
  in `anchor.py` and `auditors/sheet_ids.py` are `\uXXXX` escapes, never
  literals.
- **Disposition:** `anchor.py` maps a quote to a PDF rect: EXACT / FUZZY / TILE
  / UNANCHORED (UNANCHORED is the hallucination signal). Both fuzzy tiers carry
  the numeric veto: each digit-bearing token must sit at its own position in
  the matched span, within `_fuzzy_window_slack` (derived from the overlap
  floor), and each span position is consumed once. The sub-phrase tier uses
  `_numbers_agree`. The 0.85 threshold stays as asserted. `verify.py` is the
  high-DPI crop re-check (VERIFIED / REJECTED / UNCERTAIN) at medium effort
  inside an 8k envelope. Count every live call that returns no verdict
  (`malformed` / `truncated` / `failed` via `_degrade_kind`); `degradation_note()`
  is one observational stage warning. Opt-in
  `DRAWING_ANALYZER_VERIFY_STRUCTURED_OUTPUTS`: decide once at submit time and
  thread `structured=` to the worker; if the latch is already off, send plain.
  Store under the contract actually sent. A verdict replaces status and never
  the arithmetic provenance (`_provenance_restorer` snapshots at each public
  entry and restores at every exit). `investigate.py` carries
  `computation_method` and `operand_origin` forward. It escalates each anchored
  UNCERTAIN verdict through `crop_region` / `find_text` / `view_sheet`, all
  `strict: true`. Charge `tool_round += len(granted)` even when a block returns
  `is_error`. Strict cannot express array length: `len(raw) != 4`, the DPI
  clamp, and the 2-char query floor stay enforced in `_ToolExecutor`.
  `relax_strict_tools` (not a rebuild) powers the latch, which nests outside the
  task-budget latch and uses a disjoint marker vocabulary. Save every image
  before send, with an `investigation.json` trace. Sequential (I-5). Per finding, `…_INVESTIGATION_MAX_ROUNDS`
  (default 6) is spent per **evidence request** and enforced before execution;
  blocks past the remaining budget are refused unexecuted in the same user turn
  and do not advance the counter. Per run, `…_MAX_FINDINGS` is severity-first,
  10 + one per 4 sheets, ceiling 40, unless an explicit env value pins it.
  Commit the assistant turn before answering tools; answer every tool_use id in
  one user turn; force a no-tools close at the cap. A capped or garbled outcome
  stays UNCERTAIN — never REJECTED — and is a designed stage COMPLETE; it only
  updates `finding.verification` in place. Concluded verdicts cache in
  `stage=investigation` (finding identity + whole-set fingerprint +
  model/prompt/round-budget/task-budget), complete-only; a warm hit replays the
  tool trace with sha-compare and has no TTL. `citation_check.py` runs on
  Sonnet 5.5 (`web_search` + `web_fetch` per unique code ref; web fetch is
  unavailable on Opus 5). Both tools carry the shared source-quality blocklist.
  The resolved tool set rides the verdict cache key.
  The prompt-cache split rides `_CheckOutcome` → `CitationCheckResult` → the
  ledger, including `pause_turn` resumes and error or still-paused exits.
  `digest._message_cache_usage` is the shared dict-tolerant reader.
  `annotate.py` inks every entry except REJECTED/gated (those get index rows).
  Rect-less entries become margin callouts packed into visually clear bands
  (validated against words, a rendered occupancy mask, and siblings);
  overflow goes to an appended *AI Review Notes* page (`REVIEW_NOTES`) with a
  GOTO back. Stamp every mark, reopen the saved PDF, and reconcile each
  placement. Build the index **last**, after the notes page. `_placement_kind`
  returns `NO_QUOTE` for a quote-less finding. `_clear_bands` gates the
  **padded** band and is column-aware. `_fit_text` / `_base14_safe` fit by
  measured width and fold glyphs Base-14 cannot draw. Return a
  `MarkupRunResult` (`WRITTEN` / `INDEXED` / `FAILED`) whose receipts derive
  `coverage_status`. Place finding annotations on per-severity optional-content
  layers (`QC markups - High/Medium/Low severity`), only for tiers with ink, in
  high→medium→low order; the `/OC` reference is independent of the placement
  stamp. GOTO destinations, CropBox, and occupancy sampling are in the PyMuPDF
  gotchas. `export.py` writes `markup_manifest.json`; `html_report.py` renders
  the report. Opt-in `save_tile_artifacts` (`DRAWING_ANALYZER_SAVE_TILES`,
  `tile_artifacts.py`) bypasses the level-1 render skip so tiles exist on warm
  runs; the level-2 cache still serves the digests.
- **Export** (`export.py`): every write inside the atomic publish goes through
  `long_path(folder)`, derived **once** in `write_drawing_export`.
  `_long_path_text` turns UNC into `\\?\UNC\…` (never a bare prefix; idempotent;
  device paths untouched). `long_path` is an identity off Windows. `_unique_dir`
  probes and `mkdir` creates through it; past MAX_PATH an unprefixed `exists()`
  answers false for a directory that is there. The prefixed form is internal;
  the path returned to the caller is plain. Name dedupe is `casefold()`-keyed
  at all four allocators (`models.name_is_taken` / `record_name`); the original
  case is still written. The publish rename waits between attempts
  (`_publish_backoff`, 0.1s/0.4s) and never sleeps after the last attempt.
- **HTML report** (`html_report.py`): `_finding_display_status` keeps `UNCERTAIN`
  distinct from `UNVERIFIED` / *Not checked*. `_STATUS_RANK` stays
  integer-valued. Repeated quotes collapse in the browser only
  (`data-repeat-key` is a sha256 of the normalized quote, never the quote text);
  grouping recomputes after every sort or filter. Journal timestamps render
  through `_local_stamp`. The chat widget wraps the report in a byte-stable
  `<document>…</document>` block so the 1h cache breakpoint holds. Its turn loop
  generation-guards every `history`
  commit inside `step`; Stop is a turn latch (`stopRequested`) checked before
  and after tools; `stripDanglingToolUse` drops an unanswered `tool_use`; a
  turn's note is DOM-only unless that turn owns the last `displays` entry;
  `activeStream` is released by identity. Request shape (`thinking`,
  `webSearch`, `webFetch`) comes from the capability registry. A reader-supplied
  key outranks the embedded one, and the key row renders in both modes.

## Binding invariants (cited by number in code comments)

- **I-1 — full coverage:** every sheet is read whole (overview + all tiles);
  optimizations may never drop content-bearing tiles.
- **I-2 — the prose digest is sacred:** nothing may alter `combined_text`. The
  findings block is stripped byte-exactly; prose QC items are mirrored into the
  ledger, never moved or edited.
- **I-3 — QC is additive and non-fatal:** every QC stage catches its own
  exceptions, appends to `ctx.errors`, and lets the standard deliverable ship.
- **I-4 — hermetic tests:** use `tests/fixtures/fake_anthropic.py`
  (`FakeMessage` / `FakeTextBlock` / `FakeUsage`) and the routing-client
  patterns in existing tests. No test may hit the network or need a key.
- **I-5 — PyMuPDF isolation:** only `render.py` and `annotate.py` may import
  PyMuPDF. The README's AGPL licensing story depends on this; `anchor.py` and
  `tiling.py` work on extracted word rectangles to preserve it.
- **I-6 — cache correctness:** prompt versions are content hashes
  (`DIGEST_PROMPT_VERSION`, `CRITIQUE_PROMPT_VERSION`); when what is stored or
  sent changes beyond those hashes, bump only the affected namespace constant
  in `digest_cache`: `_DIGEST_SCHEMA_VERSION` for digest parsing/request/storage
  (both key levels and batch recovery), `_CRITIQUE_SCHEMA_VERSION` for critique parsing/merging/
  request/storage (both key levels and batch recovery), `_IDENTITY_SCHEMA_VERSION`
  for set identity, `_REVIEW_PLAN_SCHEMA_VERSION` for review plans,
  `_CITATION_SCHEMA_VERSION` for citation verdicts, and
  `_INVESTIGATION_SCHEMA_VERSION` for investigation verdicts/traces. Shared
  serialized finding changes may require both digest and critique bumps. All
  six start at 10 to preserve existing keys; `_LEGACY_SCHEMA_VERSION` stays
  fixed at 10 for JSON migration. `_DB_FORMAT_VERSION` is storage-only:
  migrate tables in place, never wipe paid rows on a version mismatch. Unused
  rows expire after 180 idle days, at most 256 per open/hourly write sweep;
  migration starts a full retention window and hits refresh it (daily).
  A hash covers only what it is given. Model-visible user-turn framing
  lives in `digest.SHARED_USER_FRAMING_STRINGS`, which **both** hashes splat.
  A string added elsewhere must be hashed by the author.
- **I-7 — deterministic assembly:** same inputs → same ordering (QC numbering,
  index rows, merged output); no randomness or time-dependence in assembly.
  The citation verdict cache TTL (`DRAWING_ANALYZER_CITATION_TTL_DAYS`,
  injectable `now=`) governs cache admission only, never numbering, ordering, or
  merged output.
- **The model never calculates:** models transcribe `NumericClaim`s;
  `auditors/arithmetic.py` does the math with `Decimal` — never `eval`, never
  the model's arithmetic. Operands are trusted (`DETERMINISTIC`, and
  deterministic-only ink) only when the quote independently carries every one
  (`operand_origin=TEXT_EXTRACTED`); a `MODEL_TRANSCRIBED` mismatch stays
  `UNCERTAIN` until crop-verified. Refuse a term that is not one value (`12,5`,
  `12'-6"`, `1.2.3`) and refuse `%` outright. Apply `_head_denies` /
  `_tail_denies` at the quote-scan site. A binder is tight: no whitespace on
  either side. `_fmt` uses `format(v, "f")`, never `quantize`. Each claim has
  its own `try` with a tally rollback.
- **Ledger is the only findings container:** every channel ingests into
  `ledger.py` with source tags. A tile/rect overlap is never sufficient to
  merge; merges need semantic sameness and compatible critical signatures
  (`critique.signatures_compatible` / `critique.critical_signature` — public, one
  copy). A measurement in that signature is its **value** (`1/2"` is `0.5in`;
  `12'-6"` keeps both halves and neither goes negative; plurals fold; `psig`
  does not fold into `psi`). Text, quote, tile, rect, evidence-state, and
  verdict are one atomic bundle from a single representative; the loser's quote
  goes to `supporting_quotes`. `_grounding_quality` ranks host-computed
  provenance first, and both quality tuples are computed **before** the severity
  union. There is no independent verdict adoption and no backfill of a loser's
  verdict. An unanchored winner never erases a rect that places its own quote.
  Union `sources`, keep the most-severe severity, and when provenance spans two
  families raise `reproduced` and `confidence` together. Lifecycle: `seal()`
  (OPEN→SEALED) → anchor → `reconcile_post_anchor` (Pass B, history from
  `Ledger.member_history`, snapshotted when a merge is about to mutate) →
  `number()` (positional `QC-###` after anchoring). A post-seal add marks the
  run incomplete (no `QC-XTRA` id); a post-seal duplicate is counted and
  dropped, not merged.
  `Finding.to_dict` / `from_dict` must default new fields so older cached
  payloads still load.
- **Ledger coverage is artifact-backed:** on markup runs every ledger entry and
  cross-sheet leg becomes a planned `MarkupPlacement`. The writer stamps each
  drawn mark, reopens the saved PDF, and reconciles to one `MarkupReceipt`
  (`WRITTEN` / `INDEXED` / `FAILED`) per placement. `coverage_status` comes from
  those receipts, never from `ink_disposition`. A placement counts only when its
  stamped mandatory component is found again; missing, failed, duplicate, or
  unexpected → `INCOMPLETE`. Stamps embed a per-run id, so prior-run annotations
  are ignored. An INCOMPLETE reviewed PDF is renamed `…_reviewed_INCOMPLETE.pdf`.
  `markup_manifest.json` carries the plan and receipts with no key and no
  absolute path.
- **Tiles use the `tile_label` contract:** the model returns the exact visible
  label (`"r1c1"`); `tiling.parse_tile_label` converts it to the canonical
  **zero-based** `[row, col]`. A legacy `tile` array is accepted only as
  explicit zero-based, bounds-checked.
- **Thinking and effort are always explicit.** On the 5-generation Opus and Sonnet (5 and 5.5) an omitted
  `thinking` key runs adaptive thinking, and thinking shares the `max_tokens`
  envelope with the answer. Every request builder states `thinking` and
  `effort`, resolved through the `core.api_config` phase registry (including
  the model-ceiling clamp). Digest and critique clamp per request via
  `clamp_effort_for_model` (`DEFAULT_DIGEST_EFFORT` /
  `DEFAULT_CRITIQUE_EFFORT` = `default_effort_for_phase(PHASE_REVIEW)`, which is
  `EFFORT_HIGH`). `PHASE_CROSS_CHECK` stays at `xhigh` and is unused. `effort` is
  part of `digest_cache_key` / `critique_cache_key`. A phase that wants shallow
  work registers `EFFORT_LOW` and does not send `{"type": "disabled"}`.
- **Above ~21k `max_tokens`, streaming is mandatory.** The SDK refuses a
  non-streaming `create` whose cap implies >10 minutes of output, client-side,
  before any HTTP request. `digest.stream_message` is the single place that
  knows this; digest, critique, review-plan, synthesis, and focus go through it.
  Batch items never stream. A cap raise without the matching streaming
  conversion is a hard failure, including the batch→real-time fallbacks.
- **Refusal fallback is a registry capability.**
  `ModelCapabilities.supports_refusal_fallback` decides which models opt in —
  never a comparison against one model id. Opus 5.5 is today's only declarer
  (`stop_reason="refusal"`, HTTP 200); Opus 4.8 is the fallback target, with
  the same effort, thinking, output cap, hi-res vision, and $5/$25 pricing.
  `core.api_config.call_with_refusal_fallback` attaches `fallbacks: "default"`
  (beta `server-side-fallback-2026-07-01`) on Opus-5-routed real-time calls
  (`digest.stream_message`, `verify.py`, the investigation loop) and re-routes
  through `client.beta.messages`. The parameter is rejected on the Batches API.
  `verify.py` resolves one model (`VERIFICATION_MODEL_DEFAULT`) and never
  escalates; `VERIFICATION_ESCALATION_MODEL` belongs to `investigate.py`. A 400
  naming the fallback beta turns the feature off for the process
  (`_refusal_fallback_available`).

## PyMuPDF gotchas (hard-won; they crash or render blank)

- A plain FreeText annot rejects `border_color` (raises unless rich text) —
  severity is carried by colored text instead.
- For FreeText, `/Contents` is the displayed text: `set_info(content=...)`
  overwrites what is drawn, so display prefixes (`[UNVERIFIED]`, `[SHEET]`)
  must be composed into the content string.
- Annot objects unbind when the `annots()` generator advances or the page tree
  changes (`insert_page`): snapshot properties during iteration, re-fetch pages
  by index after inserting, and never call `.get_text()` on an annot.
- `annot.update()` must be called to build the appearance stream (`/AP`), or
  the annotation renders blank in Acrobat/Chromium.
- Base-14 fonts miss `✓`, `…`, and em-dash glyphs — use ASCII in inserted page
  text.
- PyMuPDF is not thread-safe: rendering stays sequential; concurrency lives in
  the API calls.
- **A GOTO destination is a third coordinate space.** `/XYZ` is default user
  space; `add_*_annot()` and `insert_text()` take the un-rotated CropBox-relative
  space. `Page.insert_link` maps `to` through `~page.transformation_matrix`;
  `Document.set_toc` does `y = cropbox.height - y` then `* page.rotation_matrix`.
  Never share one helper between them. `_derotate_point` is annotation space and
  is wrong for a destination. Ground truth is an annotation's raw `/Rect`.
- **`page.cropbox` is top-left; `page.mediabox` is the raw box.** `page.cropbox`
  is in PyMuPDF's top-left convention; `page.mediabox` comes back un-normalized
  in PDF bottom-left. `mediabox.y1 - cropbox.y0` is the CropBox's top edge in
  user space.
- **`/CropBox` and `/Rotate` are inheritable.** A `new_page()` inherits a
  `/CropBox` on `/Pages`, so `_new_generated_page` pins CropBox to MediaBox.
  PyMuPDF writes `/Rotate` explicitly on pages created by `new_page()`, so a
  brand-new page does not pick up a parent `/Pages` `/Rotate` unless you set it.
- **`get_text()` includes annotation text.** Use
  `pymupdf.TextPage(page.get_displaylist(annots=False).get_textpage())`. The raw
  `FzStextPage` has no `extractText`, and `page.get_text(textpage=…)` rejects
  even the wrapper, so words come from `TextPage.extractWORDS()`. Those words
  are in rotated view space; `get_text("words")` is rotation-invariant.
- **A thin line can be invisible in a downscaled pixmap.** At 0.12 a 0.5 pt line
  antialiases above a 210 dark threshold, and the result depends on pixel-grid
  alignment, so a pixel-fraction occupancy test is non-monotonic in scale.
  `_page_occupancy` samples at 1:1 and min-filters over point-sized cells.
- **Rotation and CropBox use two coordinate spaces.** `get_text("words")` and
  `add_*_annot()` work in an un-rotated, CropBox-relative space;
  `get_pixmap(clip=...)` clips in the rotated page-view space (`page.rect`).
  The canonical space is `PAGE_VIEW_V2` (post-CropBox, post-rotation):
  `render.py` moves words in via `page.rotation_matrix`; `annotate.py` moves
  rects back via `page.derotation_matrix` before drawing and draws FreeText with
  `rotate=page.rotation`. Never feed a raw `get_text` rect to
  `get_pixmap(clip=...)`, or a raw view-space rect to `add_*_annot()`.
