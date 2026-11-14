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
  count (`estimate_image_tokens` prices ⌈w/28⌉·⌈h/28⌉ patches after the API's
  resize, at most 4784 hi-res / 1568 standard).
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
  Explicit 6×6 / fixed-grid mode keeps the legacy 177,008 allowance. Both bound
  each image with `core.tokenizer.image_tokens_upper_bound`, never by pricing a
  square: the API resizes an oversized square below the cap that a narrower
  image of the same long edge reaches.
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
  before testing DPI. The floor is tested at the DPI the model **reads**:
  `effective_tile_dpi` scales each tile's render DPI by the API's downscale
  (`core.tokenizer.resized_image_size`, the documented resize to ≤2576 px and
  ⌈w/28⌉·⌈h/28⌉ ≤ 4784 patches on the hi-res tier), on the worse axis. Render
  DPI alone overstates it: a near-square 2576 px tile reads at about 0.75×.
  `tiling._GRID_MODEL` (Opus 5) both prices the search and sets that tier, so
  geometry has one rule. A page with no feasible grid fails explicitly. Cost
  estimation substitutes the conservative allowance and discloses the fallback;
  digest and critique prescans report that page's failure and continue, keeping
  both stages partial while processing the other pages. Keep I-1.
  ANSI E (34×44) and ARCH E1 (30×42), either orientation, retain 6×6 and their
  cache keys; no prompt/schema/render-identity version bump is needed because
  actual rows/cols/target already key the render (a floor change that moves a
  page's grid re-renders and re-digests it once). Level 2 hashes PNG bytes plus
  tile layout on non-6×6 grids, so blank suppression cannot collide grids;
  6×6 retains the legacy key format.
  Consumers must use `RenderedSheet` / `SheetGeometry.rows, cols`, including
  label parsing, TILE anchors, cross-QC legs, verify/investigate crops, artifacts,
  and critique spool/upload matching. Never compare adaptive pages to global
  `None` grid arguments. Cost bases choose the same grid before pricing it with
  the stage's model; a cheaper model changes pricing, not the selected geometry.
  Measured Opus 5 image tokens per read (patch-priced), before blank
  suppression, with the minimum DPI read: vector Letter 91,168 → 7,280 (43×1,
  −92.0%, 183.53 DPI); vector Tabloid 76,216 → 14,125 (2×1, −81.5%, 190.91 DPI);
  raster Letter 148,248 → 11,736 (27×1, −92.1%, 234.35 DPI); vector ANSI D
  22×34 76,216 → 47,040 (7×3, −38.3%, 183.39 DPI); vector ARCH D 24×36
  78,288 → 51,952 (5×2, −33.6%, 184.29 DPI). The 43×1 / 27×1 strip results
  follow the image-count target discontinuity and patch rounding, which favors
  strips just under a whole number of 28 px patches tall; square grids are not
  necessarily the token minimum. A sheet larger than ANSI E can cost more than
  6×6, because 6×6 reads it below the floor (ARCH E 36×48: 6×6 reads 168.10
  DPI; 7×5 costs 107,408 vs 87,024). Digest and both critique reads use the
  chosen grid. E / E1 counts and images stay unchanged.
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
  usage/coverage/`agent_headroom` + sha256 of every artifact), written
  **last**: artifacts (including `diagnostics/`) → markup manifest → run.log →
  run manifest (excludes only itself).
  `stage_instance` labels are portable (`digest:SRC-0001:p0`). `private_roots`
  matches case-insensitively, across both separators, only at a component
  boundary (`_private_root_re`, `(?=[\\/]|$)`). Every renderer of both artifacts
  gets that list. `redact_for_display` is the same boundary without flattening
  or truncation, for host status/error text only — never digest prose (I-2) or
  model findings.
- **Resource pressure** (`resource_pressure.py`): the per-run starvation record
  (`ctx.resource_pressure`), rendered into run.log (`Starvation:` header line +
  *Resource pressure* section), `run_manifest.json` (`resource_pressure`), the
  report's run-record block and the GUI completion summary. The active
  recorder is **thread-bound**: `tracked_run` (on `extract_drawing_context`)
  binds the run's thread and registers the recorder as live; **every
  `ThreadPoolExecutor` a run opens takes `**resource_pressure.worker_binding()`**
  so its workers bind to the same run (two concurrent runs never see each
  other's retries). `current()` resolves the thread's binding, else the lone
  live recorder, else `None` — never a guess. **Every transient retry loop
  goes through `digest.transient_retry_wait(exc, attempt, max_retries, sleep,
  stage=…)`**, which records the wait or the give-up; never reintroduce a bare
  `sleep(_retry_backoff_seconds(attempt))`. The upload, files-cleanup,
  batch-results, batch-poll, batch-harvest and batch-resubmit loops call
  `resource_pressure.note_api_retry` / `note_api_give_up` directly. Exhausted
  agent budgets are
  `note_budget_exhausted(stage, kind, count=…)`; a zero count records nothing.
  The host sampler is a daemon thread on an `Event.wait` cadence
  (`DRAWING_ANALYZER_RESOURCE_SAMPLE_SECONDS`, `0` disables); its scheduling lag
  is the CPU signal. Probes are stdlib + ctypes (no psutil, no PyMuPDF); a
  metric that cannot be read is `unavailable`, never 0. Disk is reported by
  label (`temp` / `work_dir` / `cache`), never by path. Stored API events and
  journal incidents are bounded; the aggregates count everything. Advisory and
  never fatal — except the **spend-limit latch**, which only stops spending.
  `resource_pressure.spend_limit_kind(exc)` is the one classifier (429 with
  `error.details.error_code == "enforced_spend_limit_reached"` = tier cap; 400
  "You have reached your specified … API usage limits" = Console limit);
  `digest._is_transient_status_error` excludes it, so no loop retries it.
  `note_spend_limit(exc, stage=)` latches the run (first hit kept, each
  exception object counted once) at `_dispatch_messages`, `_create_batch`, the
  upload loop and `transient_retry_wait`. `check_spend_limit()` refuses at the
  same three gates as `cancellation.check()` (uploads pass `count=False`: not
  billed); batch polls, results reads and cleanup are never gated, so an
  accepted batch is still collected. `SpendLimitReached` is an ordinary
  `Exception` (I-3 absorbs it; a stop is `RunCancelled`) with no status, so it
  is never transient. The batch-resubmit loop `break`s on a spend limit
  instead of backing off. Tests inject `probe=` / `interval=` and patch
  `digest._retry_backoff_seconds` to 0 so a 429 fixture never sleeps.
- **Call telemetry** (`call_telemetry.py`): one `CallRecord` per model
  request — what it was given (model, `max_tokens`, effort + the model's
  highest accepted effort, thinking, tools with `max_uses`, `tool_choice`, task
  budget, structured/strict/fallback flags, image count) and what it used
  (stop reason, tokens, tool calls, server tool counts, tool `error_code`s,
  duration, message id). Recorded at `_dispatch_messages` (every real-time
  call, including errors and stops) and at `_create_batch` +
  `read_batch_results` (batch items, filled when results are read; results of
  a batch this run did not submit get a `recovered_batch` record). The recorder
  rides the run's `ResourcePressure` (`pressure.calls`, `ctx.call_telemetry`),
  so it reaches workers through `worker_binding()`; outside a run it records
  nothing. **Every call site wraps its request in
  `call_telemetry.scope(stage, item)`**, with `stage` = the usage family
  (`digest`, `critique`, `verify`, `investigate`, `citation`, `harvest`,
  `absence_check`, `action_plan`, `identity`, `review_plan`, `cross_qc`,
  `synthesis`, `focus`)
  and `item` = `sheet_item(ref)`, a finding id, a code ref, a chunk label
  (`absences-<n>`), or `SET_ITEM` for one-per-run stages (a shared item is what lets a raised-cap resend read as recovered).
  Item allotments the request does not carry ride the scope
  (`evidence_rounds=`, `pause_resumes=`). An unscoped call is recorded as
  `unattributed (<module>)`; the gauntlet asserts one record per billed
  real-time response under the ledger's own family, and that every request
  stated thinking and effort. Records hold shape and counts only — never
  prompt, text, image or key. `_stage_verdict` derives STARVED / TIGHT /
  ADEQUATE / NOT_ASSESSED per stage; budget notes from `ResourcePressure`
  starve their stage (names mapped by `canonical_stage`). Bounded at
  `MAX_STORED_CALLS`; `calls_seen` counts everything.
- **Diagnostics folder** (`diagnostics_bundle.py`): every export gets
  `diagnostics/` (`00_summary.md`, `api_calls.csv/.json`,
  `agent_headroom.json`, `api_retries.csv`, `host_samples.csv`,
  `events.csv`), written as an ordinary artifact before `run.log` and the run
  manifest. Each file is written independently; a failure leaves a
  `.error.txt` note, never a failed export. Strings pass `sanitize_text` with
  the journal's private roots; CSVs are UTF-8-BOM + CRLF with `_excel_safe` on
  text cells. `ResourcePressure.host_series` is the bounded, decimating host
  timeline (`MAX_STORED_HOST_SAMPLES`, stride doubles past it).
- **Kill switch** (`cancellation.py`): `extract_drawing_context(cancel=CancelToken)`
  (the GUI's **Stop**, and quitting mid-run). `RunCancelled` is a
  **BaseException** so the I-3 `except Exception` guards cannot swallow a stop;
  code that must clean up on a stop catches it by name. The token is
  thread-bound like the resource recorder (`bound_run` on the run thread;
  `resource_pressure.worker_binding()` binds it too) with **no lone-live
  fallback** — an unbound thread is never stopped. Gates: every real-time
  request goes through `core.api_config._dispatch_messages` (`check()` before
  sending; a bound run reads the stream event by event and raises at the next
  event — fake streams must be iterable), every batch through
  `batch_digest._create_batch` (inside `cancellation.submitting()`, which
  refuses after a stop and holds `wait_for_remote_cancels` open; then
  `track_remote_batch` so `cancel()` cancels it from a daemon thread, or at
  once if accepted after the stop), Files uploads per image. Spending waits use `cancellation.pause`
  (`transient_retry_wait`, batch polls, harvest, resubmit backoff); cleanup
  waits (`_read_with_retry`, deletes, `_cancel_unrecorded_batch`) never do.
  Forget a tracked batch when it settles (terminal poll, accepted cancel). A
  stopped batch keeps its receipt and files; a stopped submit deletes its
  uploads. A resource a skipped later stage would have released registers
  `cancellation.on_stop` (run on the run thread after unwinding — e.g. the
  retained digest uploads). Stage starts `check()` up to markup writing, the
  last stop point.
- **Live spend** (`live_spend.py`): `extract_drawing_context(spend=SpendMonitor)`
  (the GUI's spend line and **Stop the run at $** box). The usage ledger fills
  in at stage ends, so the monitor is fed at the dispatch sites instead:
  `live_spend.note_response` in `_dispatch_messages`, `note_batch_submit` in
  `_create_batch`, `note_batch_results` in `read_batch_results`. It rides
  `ResourcePressure.spend`, so workers reach it through `worker_binding()`;
  stage and item come from `call_telemetry.current_scope()`.
  `response_cost` must price a response as `_record_usage` does (per fallback
  hop, batch rate, inferred fast speed, web searches by value); the gauntlet
  asserts the live per-family figures equal the ledger's. *In flight* is batch
  items submitted and unread; a result for an item this monitor never saw
  submitted (receipt recovery) is not this run's spend. The projection needs a
  forecast (`cost.spend_forecast(estimate)`, built from each
  `CostComponent.family` / `items`; empty if any stage is unpriced): per
  stage, billed plus remaining items at a per-item rate shrunk from the
  quote's toward the stage's observed mean (`SHRINK_ITEMS`). `_finish_stage`
  closes a stage (requested or not), `live_spend.expect(family, n)` reports
  its paid item count after cache lookups, and `finish(run_usage)` replaces
  the live figures with the ledger's. A new paid stage needs a `family` on its
  estimate component. The budget cap compares `billed + in_flight_floor` (the
  low per-item rate, counted only for a `measured` forecast — `shape_aware` —
  or from the stage's observed mean, never the conservative allowance) and
  calls `CancelToken.cancel(reason)` (`token.reason`; `bound_run` logs it), so
  a capped run ends in `RunCancelled` like a user stop. `set_budget` is
  thread-safe and takes effect at once; a monitor with a budget and no
  `cancel=` raises `ValueError` at run start. The GUI polls `snapshot()` on
  `after(SPEND_REFRESH_MS)`; the cap box and amount are never locked during a
  run and persist in `core/preferences.py` (`BUDGET_CAP_*`). Advisory apart
  from the cap: every hook swallows its own failures.
- **Digest path:** `tiling.py` (geometry) → `render.py` (raster) → `digest.py`
  or `batch_digest.py` (Message Batches + Files) → `digest_cache.py` (two-level
  content-keyed cache; a hit skips rendering and restores parsed findings).
  Findings fences are **line-anchored**, accept 3+ backticks or tildes, and a
  closer must match its opener's character and length. Never cache a truncated
  read: both transports treat an unfinished reply (empty, cut off, or declined
  with `refusal` — `digest.unfinished_reply_error` is the one rule) as an
  error, retry a cut-off one once at `digest.MAX_TOKENS_RETRY_CEILING` (never a
  refusal: a capable model's real-time request already carried the fallback, a
  batch item has none), and refuse the cache write if it is still unfinished.
  Partial text still ships (I-3), in `combined_text` too, with the error
  disclosed under it (`_combine`). Real-time usage accumulates across both
  attempts. Both transports fall back to the truncated first read if the
  raised-cap call cannot land or returns no text: real time in
  `digest.stream_with_cap_retry` (shared with synthesis and focus), batch in
  `batch_digest._replace_result_with_attempt_history` (see Batch recovery).
  Every persistent digest-cache read (both levels, both transports) goes through
  `digest.finished_digest_entry`: an entry an older build stored under an
  unfinished `stop_reason` reads as a miss (no schema bump). An unfinished
  synthesis or focus reply ships its partial text with a `_combine`
  disclosure, holds its stage at PARTIAL, records every billed response, and
  is never cached; a partial overview is never harvested.
  Critique does not re-rasterize: `render_spool.py` rebuilds the
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
  still counts only response-bearing ones. Every result replacement goes
  through `_replace_result_with_attempt_history`: a failed replacement with no
  text never displaces a result with text. That result stays whole (a partial
  read stays an error, never cached) and takes the merged attempt history; a
  deferral (`_defer_batch_collection`) appends its note to its error. The next
  round is still decided from the round's own reply. Each slot records
  `served_by`, the batch its kept result was parsed from.
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
- **Fast mode / XFast** (`fast_mode=`): resolves on only when both transports
  are real-time (`RunConfiguration.fast_mode`); the pipeline sets
  `ResourcePressure.requested_speed = "fast"`, which reaches workers through
  `worker_binding()`. `call_with_refusal_fallback` attaches `speed` via
  `extra_body` (the pinned SDK exposes `speed` only on the beta namespace) to
  models declaring `supports_fast_mode` (Opus 5.5 only); a 400 naming speed
  latches `_fast_mode_available` off and resends at standard speed (each latch
  flips once, so the loop ends). Billing: `ModelPrice.fast_mode_multiplier`,
  `UsageRecord.speed` from `RequestUsage.speed` (`usage.speed`), or — for a
  stage that summed its tokens — inferred by `_record_usage` from
  `fast_mode_active_for` on REAL_TIME records. Estimates take `fast_mode=`
  (a context variable in `cost.py`): price every stage through
  `_estimate_request_cost` / `_usage_record_cost`, never the raw pricing calls.
  Fast mode never touches a cache key.
- **Reference documents:** `project_context` (additional context) is budgeted
  like specs (`CONTEXT_TOTAL_CHAR_BUDGET`) and threaded as `specs_text` via
  `digest.compose_reference_text`, which returns a `ReferenceMaterial` **only**
  when context is present — a specs-only run stays a plain string, so its
  prompt and digest keys are byte-identical. The specs fragment hashes the
  rendered addendum, so context moves the key by itself. `ahj_atlas.py` reads
  the AHJ Atlas Input (`.xlsx`/`.xlsm`/`.csv`; long, wide, tab-per-AHJ and
  free-text layouts) into governing-edition entries; `profiles.load_checklist_file`
  turns uploaded checklists into `Profile`s named `upload:<file name>`
  (snapshot source `uploaded`). Both import `openpyxl` lazily and never raise
  past their documented contract (the atlas captures every failure).
- **GUI** (`gui.py`): console-less entry (`[project.gui-scripts]` on Windows;
  the frozen build is windowed). The guarded `customtkinter` import reports
  through a stdlib `messagebox` and raises **ImportError**, not `SystemExit`
  (`app_entry.py --selfcheck` catches `Exception`). `WM_DELETE_WINDOW` →
  `_on_close_request` (workers are daemons; export runs after analysis returns);
  mid-analysis it stops the run and closes once the stop settles
  (`QUIT_STOP_GRACE_SECONDS`). `_worker` catches `RunCancelled` by name.
  `report_callback_exception` → `_on_callback_exception`. Both reporters swallow
  every failure of their own channels. The optional-input Add buttons live in
  their own *Reference files (optional)* section (`_add_buttons`, keyed like
  `help_content.INPUT_HELP`; each has a "?" that opens `_open_input_help`, one
  popup at a time) right above the *Loaded files* list (`_file_groups` is the
  data, `_refresh_files_panel` the widgets; call it on every input change,
  never from `_refresh_summary`; focus-box typing goes through
  `_refresh_summary_soon`, which waits for a pause, and the sheet list comes
  from `_sheet_refs`, cached by `sources_fingerprint`). Drawings are
  added only from the drop zone. The bottom rows, progress line and Analyze row are packed
  `side="bottom", after=` the footer so a short window clips the log and
  sections, never the actions. `CTkScrollableFrame`'s vertical scrollbar
  requests 200 px and overrides `height=`: lower it (`_scrollbar.configure`)
  or the list cannot shrink. Persisted GUI preferences (not secrets, not run
  inputs) live in `core/preferences.py` (`gui_preferences.json`, tolerant read,
  best-effort atomic write): the budget cap (`BUDGET_CAP_*`) and
  `SKIP_FULL_QC_CONFIRM`, set by the
  full-QC cost dialog's "Don't show this again" (`gui._ask_cost_confirmation`,
  remembered on Yes only) and cleared by the QC section's confirm box, and
  `LIVE_VIEW`, set by the Activity section's Live view | Log toggle. A
  skipped dialog logs the estimate. GUI lifecycle tests drive real handlers on a
  `SimpleNamespace` stub — a handler that calls a new method needs it stubbed.
- **Live view** (`live_view.py` / `live_scene.py` / `live_panel.py`, all
  toolkit-free): `extract_drawing_context(monitor=RunMonitor())` gets the run's
  journal, `ResourcePressure` (its `.calls` telemetry), config and focus when
  the host sampler starts, and the sheets after `list_sheets`, both through
  `live_view.notify_monitor` (swallows everything; a monitor never changes a
  run). `LiveRunModel.poll` reads only what is new (cursors over the
  append-only journal events and call records). It re-reads a settled call
  record for `_SETTLE_WINDOW_SECONDS` (`describe_response` sets `outcome`
  before the tokens) and retries an open batch record until its `item` is set.
  Sheets match call records by `sheet_item` (critique appends `:<read>`;
  `sheet_key_of`) and journal events by display label (sanitized as the
  journal does), narrowed by `source`. Live spend prices settled records with
  `core.pricing.usage_record_cost` and is marked `≈`; `finish(ctx)` replaces it
  with `ctx.total_estimated_cost`. `LiveScene.build` is a pure frame of keyed
  `Prim`s (`animating` = anything moving); `CanvasPainter` diffs by key, sends
  `itemconfigure` only the options that changed (a re-sent font or text makes
  Tk lay the item out again), and slots each new item in with one `tag_lower`
  under the next surviving item; it restacks the whole frame only when
  survivors swap places. Never go back to raising everything after a new item:
  a read starting or finishing cost ~1,200 Tk calls in one frame.
  `LivePanel` paces at ≤25 fps and ≥5× the last frame's cost, and that cost
  includes Tk's repaint (`_draw` calls the canvas's `update_idletasks`). Input
  anywhere but the canvas (`gui._on_window_input`, bound with `bind_all`)
  calls `note_input`, which holds drawing for `INPUT_QUIET_MS` while polling
  continues. It polls at 1 Hz while hidden mid-run, and stops when idle.
  `ThoughtStream.snapshot` reuses the copy of every thought that has not
  changed since the last snapshot, so readers treat copies as read-only. GUI: the Activity section's `Live view | Log` toggle
  (`_show_activity_view`; `core.preferences.LIVE_VIEW`). Handlers reach
  the panel via `getattr(self, "_live", None)`, so stub-driven handler tests
  need no new stubs. The gauntlet `oracle` runs with a monitor.
- **Live view tabs** (`live_tabs.py`, toolkit-free): the canvas carries a tab
  strip under the HUD (Board | Story | Thinking | Plan | Findings), drawn only
  when the panel is at least 192 px tall (a shorter one shows the board
  whatever tab is picked). `LiveScene` owns the state: `tab`, per-tab `scroll`
  and `follow`, the tab hit boxes and the hover regions a view registers with
  `add_tip`. The host's inputs are `click` and `wheel` (`LivePanel.click` /
  `.scroll`; the GUI binds `<Button-1>`, `<MouseWheel>`, `<Button-4/5>`), and
  `core.preferences.LIVE_TAB` remembers the tab. A canvas cannot clip: a
  scrolling list emits only the rows inside its rectangle, keyed by **slot**
  (`ck0`, `fl0`, `mi_l0`), and fades the edge rows. Bold small-caps labels are
  measured with `caps_width`, not `text_width`. Anything that moves after a run
  ends keeps the loop awake forever, so a view sets `scene.animating` only for
  motion that stops (the test that a finished board rests covers every tab).
  The pipeline hands the run's own objects over with
  `notify_monitor(monitor, "publish", kind, obj)`: `identity`, `checklist`,
  `checklist_answers`, `digests`, `critique_findings`, `cross_findings`,
  `ledger`. They are live references; `LiveRunModel` re-reads them every
  `INSIGHT_REFRESH_SECONDS` (unthrottled in `finish` / `stop`), each reader in
  its own `try` so one odd object blanks one tab. A new stage needs a sentence
  in `live_tabs.STAGE_STORY`.
- **Keeping checks** (Plan tab → `checklist_save.py`): `LiveScene.picks`
  (`live_tabs.ChecklistPicks`) is display state only, cleared by
  `reset_views`. Only `origin == "model"` items are pickable; saved/held ids
  are not. A view registers click regions per frame with `scene.add_hit`
  (topmost wins; `menu=True` regions alone act while a check's menu is open,
  any other click just closes it; the wheel and a tab switch close it too).
  Every row slot emits the same keys in every state (`_hidden` placeholders),
  so a toggle redraws instead of recreating. A click that needs the host
  leaves `SaveRequest` / `CopyRequest` on `picks.request`; `LivePanel.click`
  takes it and calls `on_request` **after** `kick()`. The GUI answers with
  `_save_checks_dialog` (non-blocking toplevel) and reports back through
  `LivePanel.mark_saved(ids, label, held)`, then `_reload_profile_panel`
  (the profile list lives in `_profile_holder`). Prefill prefixes come from
  `ChecklistPlan.sheet_prefixes` → `LiveCheckGroup.prefixes`. Writes: plan
  first, re-plan against the disk at Save (`save_new` / `save_append`),
  temp file + `os.replace` to append; a new file lands by `os.link` (atomic
  refusal; exclusive create where links are unsupported) and a taken name
  retries at the next free file and profile name. A save while `_busy`
  defers the profile suggestion (`_suggest_after_busy`); every place busy
  ends calls `_resume_deferred_suggestions`. Repeats compare `normalize_check` (case-folded, whitespace
  collapsed, trailing punctuation off) against the target file, the run's own
  user items, and earlier picks. Appending keeps the file's lines and line
  endings; only an integer `version` and `date` in its header change.
- **Reasoning summaries** (`thought_stream.py`): a run with a monitor (and
  `DRAWING_ANALYZER_SHOW_THINKING` not `0`) puts a `ThoughtStream` on
  `ResourcePressure.thoughts`, so workers reach it through `worker_binding()`.
  `core.api_config.apply_thinking_display` then adds `display: "summarized"`
  to plain adaptive `thinking` in `call_with_refusal_fallback` and in
  `batch_digest._create_batch` (`with_thinking_display`). No request builder
  or cache key knows about it, and a run without a monitor sends what it
  always sent. The field must never cost a read. A 400 naming `display`
  latches `_thinking_display_available` off and resends, real time and batch
  submit alike. A batch item errored for it latches too
  (`note_batch_item_error`), and `_item_retry_params` treats that one
  `invalid_request_error` as retryable, so the digest's resubmission sends the
  sheet's own `params` (which never carried the field). The critique batch has
  no resubmission, so `_create_batch` asks it only for a model already seen to
  accept the field (`confirmed_only`; a real-time answer or a succeeded item of
  a batch that asked confirms a model). A digest submit passes
  `resubmits_rejected_items=True` only because its collect retries.
  `_dispatch_messages` taps raw stream events
  (`content_block_delta` only; the SDK's echo events would double-count) and
  the final message of a `create`; `read_batch_results` records batch
  summaries under the item's telemetry label (`CallTelemetry.batch_item`).
  **Display only:** summaries are model prose about the drawings and are never
  written to an export, the journal, diagnostics or a cache; call telemetry
  stays shape-and-counts.
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
  (consumers take `SetIdentity | None` and never gate a finding on it). Regex
  edition hits the model did not adopt go to `mentioned_codes`
  (`origin="regex"`), never `adopted_codes`: the regex cannot tell a mention
  from an adoption. Consumers label them (`context_block`, the planner's
  `mentioned_not_adopted_codes`, the citation request's mentioned line, which
  folds into its payload hash only when non-empty). Runs on Haiku 5.5 at
  medium effort. Coerce
  every list-shaped field through `set_identity._as_list` (a string must not be
  consumed per character). The international code-designation regex is
  **case-sensitive**; `Eurocode` keeps its own case-insensitive group.
  `review_planner.py` — one text-only call for the per-discipline checklist,
  bounded at ≤60 items (`DRAWING_ANALYZER_MAX_PLAN_ITEMS`), overage taken from
  the **longest** plan each round; overlong items are dropped, never truncated.
  Every code-based item names code + section + edition inline and never invents
  a section. Plans become `Profile` objects injected **after** user profiles
  (`source="model"`, name prefix `profiles.MODEL_PLAN_PREFIX`), so the checklist block and its key stay correct. Both stages
  cache in `DigestCache` (`stage=identity` / `stage=review_plan`) and ride the
  critique stack (`run_identity` also on with citation alone); the standard run
  stays zero-extra-cost. Artifacts: `set_identity.json`, `review_plan.md`, a
  manifest `set_identity` key, and an additive combined-text section (I-2).
  Identity feeds
  `check_citations(identity=)` and `cross_sheet_qc(identity=)`.
  Reviewer-set governing editions (`governing_editions=`, parsed once into
  `RunConfiguration.governing_editions` by `models.parse_governing_editions`;
  an unreadable entry raises `ValueError`) are applied by
  `models.apply_governing_editions` right after the identity stage, outside its
  cache, only when a consumer runs (`RunConfiguration.reads_adopted_editions`:
  identity, citation, auditors, cross-QC or review plan). For each named code
  they replace the detected adoption (`origin="operator"`, no quote needed; the
  edition audit trusts them like text) and move the overruled edition to
  `mentioned_codes`.
- **Checklists** (`profiles.py`, `checklist_matrix.py`): every item gets an id
  assigned over the **whole** selection (`U1.3` user, `M2.7` model plan;
  `checklist_items`), never per sheet, so scoping cannot renumber anything.
  `ChecklistPlan(profiles, scopes)` is built once per run and
  `plan.for_ref(ref)` returns that sheet's `SheetChecklist` (`prompt`, `ids`,
  `key`). **Every** site that builds a critique cache key, request or batch
  receipt takes the checklist from `for_ref` / `for_key` — the level-1
  partition, the recovery loop, `_ingest_miss`, the batch `level1_keys`, the
  real-time read, `submit_critique_batch`. There is no run-wide profiles key;
  `profiles_cache_fragment` is the unscoped form for direct callers. Scopes
  come from `build_sheet_scopes` (keyed by `models.sheet_ref_key`): a person's
  checklist by `discipline_token` of the title-block sheet id, a model plan by
  the slug of the identity's `sheet_disciplines`. `profile_applies` **fails
  open** (no tags, unknown sheet, a discipline no plan was written for →
  applies). The answer-every-item contract lives in `_CHECKLIST_HEADER`, inside
  the checklist block, so the block's own hash covers it:
  `CRITIQUE_PROMPT_VERSION`, no-checklist keys and `_CRITIQUE_SCHEMA_VERSION`
  do not move. Keep it that way: answers are stored in the cache entry only
  when the sheet was given a checklist, and `Finding.to_dict` writes
  `checklist_items` only when non-empty. `critique.read_checklist_answers` is
  the one validator (ids the sheet was not given are dropped and counted, a
  citing finding makes an item violated, an unmentioned item is `UNANSWERED`);
  `outcome_from_message` / `result_from_outcomes` need `checklist_ids`, and a
  batch receipt item carries them for recovery. `CritiqueResult.checklist` is
  `{id: [one answer per valid read]}`; `models.merged_check_status` folds it.
  `_representative` and `ledger._merge_into` union `checklist_items`.
  `build_checklist_report` joins the answers to the **final** findings after
  `_run_qc_stages`; a cell is `VIOLATED` only when a non-rejected finding
  stands against the item on that sheet. `MET` is unverified and is worded
  "Reported met", never "pass". The `checklist` stage is `expected=False`:
  unanswered checks are a warning and never lower `qc_status`. Outputs: the
  report's *Checklist Results* card, `checklist_matrix.csv`, the manifest
  `checklist` key, a `checklist_items` column in `findings.csv`. The gauntlet
  fake answers the checklist from the ids in the system prompt
  (`critique_checklist_ids` records what each sheet was given).
- **Finders:** the digest findings block; `critique.py` (a second full-coverage
  vision read, twice; self-consistency sets `reproduced`). On the real-time path
  the two reads prompt-cache their shared image prefix when `runs>=2`; the batch
  path stays uncached. A failed real-time read gets one replacement; one cut
  off at `max_tokens` is replaced at the digest's raised cap
  (`MAX_TOKENS_RETRY_CEILING`). `use_batch` resolves from `DRAWING_ANALYZER_USE_BATCH`
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
  (match first; one structuring call per unmatched straggler on Haiku 5.5 at
  medium effort). Its boilerplate filter is anchored at **both** ends, length
  floor 8; the `filtered` count is observational and feeds neither `missing` nor
  `complete`. Opt-in `DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS`:
  `HARVEST_STRUCTURED_SYSTEM_PROMPT` is one substitution on the fenced prompt;
  `HARVEST_FINDING_SCHEMA` mirrors that field list one-for-one
  (`additionalProperties: false`; enums from `digest._MODEL_FINDING_CATEGORIES`
  / `_FINDING_SEVERITIES`). `HARVEST_STRUCTURED_PROMPT_VERSION` folds into the
  item key only when the request carried the schema; re-resolve the store key
  after the call. A bare-JSON parse is attempted only under the structured
  contract, and a fenced reply still wins.
- **Sheet blocks** (`sheet_blocks.py`): every text-only stage that sends sheet
  text or digest prose (cross-QC whole-set/map/reconcile, synthesis, focus,
  identity, the planner's digest fallback, absence check, harvest) wraps each
  sheet with `sheet_block(id, [(tag, body)], label=)` →
  `<sheet id="…"><digest>…</digest><text_layer>…</text_layer></sheet>`, and its
  system prompt carries `SHEET_CONTENT_RULE`. The planner states the rule in
  its uncached fallback turn instead, so `PLANNER_PROMPT_VERSION` (and through
  the plan, the critique's profiles key) does not move. Bodies are neutralized:
  a `<` that starts any `SHEET_BLOCK_TAGS` name (any case, inner whitespace)
  becomes U+2039; attributes are escaped. Host user-turn framing never spells a
  literal tag. Reconcile facts are grouped per handle, one line per fact.
  Cross-QC's key hashes prompts and per-sheet inputs, not the composed turn, so
  `_CROSS_QC_USER_FRAMING` (including `SHEET_BLOCK_FRAMING_VERSION`) rides its
  `prompt`; the other stages hash their whole user text. The digest's own
  `<sheet_text_layer>` is separate and stays un-neutralized: changing it would
  re-key every digest.
- **Cross-QC grounding** reads `models.sheet_evidence_text(geom)`, not the capped
  `sheet_text`. A present-but-empty full text means no textual evidence and does
  not fall back; `None` means unavailable; a non-string is unavailable. Prompt
  bytes stay capped. `_cross_qc_cache_key` adds `evidence_sha256` **only for a
  truncated sheet**. Grounding is three-state (`classify_quote_evidence`):
  `TEXT_GROUNDED` / `NOT_MATCHED_IN_TEXT` / `TEXT_EVIDENCE_UNAVAILABLE`. Ask the
  **reported tile** (`_tile_has_words`) before classification; an unknown tile
  answers that there was text. No cross-QC prompt asks for a `tile_label`: the
  stage never sees a tile or the sheet's grid, so a label would be a guess. A
  volunteered one is still bounds-checked. A quote unmatched where the sheet has text is a
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
  quote; regex-union entries are ignored) ∪ a regex harvest that drops
  citation-shaped mentions (followed by a section marker) and, for a family the
  identity adopts, every year the identity does not adopt (a mention, never an
  adoption); a family the identity does not cover keeps the scan. Both
  operands re-found in sheet text → medium + `DETERMINISTIC`; otherwise low,
  advisory-labeled, and crop-verified. Anchor to the stale-edition span, never
  the citing finding's quote.
- **Text normalization:** `anchor._normalize` rewrites vulgar fractions
  **before** NFKC (`_VULGAR_FRACTION_TABLE`). `_CHAR_FOLD` also covers the
  fraction slash, division slash, and multiplication sign. Invisible code points
  in `anchor.py` and `auditors/sheet_ids.py` are `\uXXXX` escapes, never
  literals.
- **Absence cross-check** (`absence_check.py`): after numbering, before
  verification; rides `run_critique` (`absence_check=False` is a debug
  override; an explicit `True` counts in `any_paid_expert`, since it is not
  gated on markup). Candidates are `is_sheet_absence` (`anchor_hint="SHEET"`,
  no `also_on`, a source page, `critique._ABSENCE_RE` text). One text-only call
  per 25 on Haiku 5.5 at medium effort (`PHASE_ABSENCE_CHECK`) over the set's
  capped `sheet_text` under opaque `S###` handles, budgeted by `_allowances`
  (`_CORPUS_BUDGET`, under Haiku's 100k-token tier; the cut is counted). A
  FOUND counts only when `_ground` re-finds the quote (normalized, ≥2 words and
  ≥6 chars) in the **named** sheet's `sheet_evidence_text`; an accepted hit sets
  `Finding.located_elsewhere` and lowers high/medium to low. Never deletes;
  NOT_FOUND changes nothing; specs are never searched. A reply missing a
  handle, unparsed, or unfinished leaves those absences UNCHECKED and the stage
  PARTIAL; only complete, non-fallback replies cache (`stage=absence_check`,
  `_CACHE_CONTRACT`), and cached replies are re-grounded on every read.
- **Action plan** (`action_plan.py`): the last paid stage, after the citation
  check and only on a markup run (`config.run_action_plan and qc_markups`;
  `action_plan=False` is a debug override). One text-only call per 80 open
  findings (REJECTED is never sent) on Sonnet 5.5 at medium effort
  (`PHASE_ACTION_PLAN`) sets `Finding.action` (`models.ActionItem`: `bucket` in
  `ACTION_BUCKETS`, `instruction`, `clear_fix`, `source`). The bucket stands as
  given; `_checked_item` drops (never repairs) an instruction that is over
  length or that `_invented` flags against `_finding_material`: a number the
  finding lacks (`_numbers` — the model never calculates) or a lettered
  identifier it lacks (`_identifiers`, compared whole and hyphen-folded:
  FP-501 is not M-501 for sharing its digits; the finding's side is read
  loosely so "FP 501" counts), and clears
  `clear_fix` on a hedged line (`_is_hedged`: a hedging verb counts only as a
  clause's verb, so "check valve" is not a hedge). The pipeline then calls
  `apply_severity_fallback` so every open finding has a group;
  `models.action_bucket` / `bucket_is_ranked` are the readers. The stage is
  `expected=False`: PARTIAL/FAILED is a warning and never lowers `qc_status`.
  Complete, non-fallback replies cache (`stage=action_plan`, `_CACHE_CONTRACT`)
  on the exact finding blocks, and a cached reply goes through `_checked_item`
  again. **What may be drawn on a sheet is `models.on_sheet_instruction`, and
  nothing else**: the model's `clear_fix` plus the host's own confirmation
  (`needs_verify` false, VERIFIED/DETERMINISTIC, anchor EXACT/FUZZY, not a
  question, not `located_elsewhere`). Do not loosen it from the prompt side.
  `to_dict` writes `action` only when set. A new estimate component
  (`family="action_plan"`) keeps the live-spend forecast non-empty.
- **Disposition:** `anchor.py` maps a quote to a PDF rect: EXACT / FUZZY / TILE
  / UNANCHORED (UNANCHORED is the hallucination signal). Both fuzzy tiers carry
  the numeric veto: each digit-bearing token must sit at its own position in
  the matched span, within `_fuzzy_window_slack` (derived from the overlap
  floor), and each span position is consumed once. The sub-phrase tier uses
  `_numbers_agree`. The 0.85 threshold stays as asserted. `verify.py` is the
  high-DPI crop re-check (VERIFIED / REJECTED / UNCERTAIN) at medium effort
  inside an 8k envelope. The dual-crop cross-sheet call sends
  `VERIFY_CROSS_SYSTEM_PROMPT`, not the single-crop prompt; routing fakes match
  both, and a verify prompt edit bumps `VERIFY_PROMPT_VERSION`. Count every live call that returns no verdict
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
  one user turn; force a no-tools close at the cap. Its breakpoints use the
  5-minute default (`api_config.CACHE_BREAKPOINT_TTL`; turns re-read within
  seconds). The close's `tool_choice` change voids the messages tier, so it
  marks no message breakpoint. A capped or garbled outcome
  stays UNCERTAIN — never REJECTED — and is a designed stage COMPLETE; it only
  updates `finding.verification` in place. Concluded verdicts cache in
  `stage=investigation` (finding identity + whole-set fingerprint +
  model/prompt/round-budget/task-budget), complete-only; a warm hit replays the
  tool trace with sha-compare and has no TTL. `citation_check.py` runs on
  Sonnet 5.5 at medium effort (`web_search` + `web_fetch` per unique code ref;
  web fetch is unavailable on Opus 5, available on Opus 5.5, so Sonnet is a cost
  choice). Both tools carry the shared source-quality blocklist.
  The resolved tool set rides the verdict cache key. Model verdicts are
  `CHECKED_SUPPORTS` / `CHECKED_MISMATCH` / `UNRESOLVABLE` (`_VALID_VERDICTS`);
  `_verdict_fields` records a support with no https evidence URL as
  `UNRESOLVABLE`. That is a concluded check (cached, stage COMPLETE); only
  `UNCHECKED` holds the stage at PARTIAL.
  The prompt-cache split rides `_CheckOutcome` → `CitationCheckResult` → the
  ledger, including `pause_turn` resumes and error or still-paused exits.
  `digest._message_cache_usage` is the shared dict-tolerant reader.
  `annotate.py` inks every entry except REJECTED/gated. A gated entry gets an
  index row; a REJECTED one is `REPORT_ONLY` — nothing in the PDF (no ink, no
  cover row, no bookmark), receipt `REPORTED`, and a source with nothing else
  gets no reviewed copy. `ink_rejected` draws it grey and lists it under
  *Ruled out* instead.
  **Text an engineer reads at a glance carries one signal.** The cover page is
  ID / Sheet / What to do (`_what_to_do`: the action plan's instruction or the
  channel's own action, then the finding; severity is the ID's color), listed
  under the three to-do groups (`_index_rows`; a `note` row discloses any
  severity fallback; a leg sits in its parent's group and is not counted as a
  finding), and a callout box leads with `_callout_prefix`; both say
  `VERIFY:` exactly when `models.needs_verify` is true and nothing when it is not.
  Bookmarks are filed under the same groups (level 2 folders, level 3
  entries; destinations are patched by toc index). `_subject` puts the group
  (`1 - Do this first` …) on every part of a finding's markup.
  Do not add status words, bracket tags or pipeline terms to either: the
  bracket tags (`[CHECK]`, `[NO TEXT TO CHECK]`, …) belong to a cloud's popup
  comment only. The cover's last line (`_omitted_note`) names QC numbers that
  are missing because they were ruled out.
  Rect-less entries become margin callouts packed into visually clear bands
  (validated against words, a rendered occupancy mask, and siblings);
  overflow goes to an appended *AI Review Notes* page (`REVIEW_NOTES`) with a
  GOTO back. Stamp every mark, reopen the saved PDF, and reconcile each
  placement. Build the index **last**, after the notes page. `_placement_kind`
  returns `NO_QUOTE` for a quote-less finding. `_clear_bands` gates the
  **padded** band and is column-aware. `_fit_text` / `_base14_safe` fit by
  measured width and fold glyphs Base-14 cannot draw. Return a
  `MarkupRunResult` (`WRITTEN` / `INDEXED` / `REPORTED` / `FAILED`) whose receipts derive
  `coverage_status`. Place finding annotations on per-severity optional-content
  layers (`QC markups - High/Medium/Low severity`), only for tiers with ink, in
  high→medium→low order; the `/OC` reference is independent of the placement
  stamp. `_add_instructions_and_stamps` runs after the clouds and callouts:
  an `instruction` component (optional, never gates coverage) is a native
  FreeText **callout** (`callout=` leader, `/IT /FreeTextCallout`) placed by
  `_place_near` only where `_is_clear` passes — a fresh `_page_occupancy`
  render (so the page's own marks count) plus `taken` (every cloud, every box
  placed so far); its leader may cross linework but not a word or another
  mark (`_leader_is_clear`). No clear spot → no box; never relax that to get
  one. The sheet stamp is **page content** on the `QC markups - Sheet notes`
  layer (`insert_textbox(oc=…, rotate=page.rotation)`), not an annotation, so
  annotation counts and the Markups List are unchanged; `_stamp_text` says
  only what is true of that sheet. Every link and bookmark is a `/FitR` destination built by `_mark_dest`
  (the drawn mark's own `/Rect`, else the anchor rect, else `/Fit`), padded and
  grown to a minimum view by `_zoom_box`; `_annotate_units` hands the index and
  the outline `marks` (placement id → page, xref). GOTO destinations, CropBox,
  and occupancy sampling are in the PyMuPDF gotchas. `export.py` writes `markup_manifest.json`; `html_report.py` renders
  the report. Opt-in `save_tile_artifacts` (`DRAWING_ANALYZER_SAVE_TILES`,
  `tile_artifacts.py`; the GUI's *Save tile images* checkbox under *Open
  Diagnostics Log*, seeded from the env var, passes it explicitly) bypasses the level-1 render skip so tiles exist on warm
  runs; the level-2 cache still serves the digests.
- **Export** (`export.py`): `write_drawing_export` writes `report.html` after the
  other ordinary artifacts (`include_report=False`, then `build_report_document`
  with `build_export_file_list(staging)`), so its Files panel lists the folder
  as published; `run.log` / `run_manifest.json` are named up front because they
  are written next. Every write inside the atomic publish goes through
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
  integer-valued. A `VERIFIED` code finding is worded as a confirmed drawing
  fact (`models.verified_drawing_fact_only`, the one rule the report chip and
  `annotate`'s popup share, and the reason the cover page marks such a finding
  `VERIFY:` until its citation is `CHECKED_SUPPORTS`); its stored status stays
  `VERIFIED`. Repeated quotes collapse in the browser only
  (`data-repeat-key` is a sha256 of the normalized quote, never the quote text);
  grouping recomputes after every sort or filter. Journal timestamps render
  through `_local_stamp`. The chat widget wraps the report in a byte-stable
  `<document>…</document>` block so the 1h cache breakpoint holds. Its turn loop
  generation-guards every `history`
  commit inside `step`; Stop is a turn latch (`stopRequested`) checked before
  and after tools; `stripDanglingToolUse` drops an unanswered `tool_use`; a
  turn's note is DOM-only unless that turn owns the last `displays` entry;
  `activeStream` is released by identity. The overview and focus cards open
  with `_pre_qc_note` (QC ran and left findings): that prose predates QC, and
  the chat system prompt ranks a finding's status above it. Request shape (`thinking`,
  `webSearch`, `webFetch`) comes from the capability registry. A reader-supplied
  key outranks the embedded one, and the key row renders in both modes. A 401
  whose message begins `CORS requests are not allowed` (the organization
  blocks browser calls) is not a key failure: keep the key, don't reopen the
  form; every other 401 forgets the reader's key.
  **Inline artifacts** (`create_artifact`: chart / table / memo cards) have no
  storage of their own: an artifact *is* its recorded `tool_use` input in
  `history`, so transcripts carry it. `artifactSpec` is the one validator, live
  and on replay; ids (`A1`…) are the order of successful calls, and replay
  re-registers in order — a recorded success that no longer validates still
  takes its id. Replay re-renders `create_artifact` / `share_file` from their
  input only when the recorded `tool_result` is not `is_error`; every other
  recorded tool stays a chip. Chart colours come from the fixed
  `SERIES_COLORS`, never the spec; serialization (SVG, memo `.html`) uses
  `XMLSerializer` (no `innerHTML`, not even a read). The Files panel derives
  from `artifacts` plus the inert, chat-gated `#da-exports` block
  (`_exports_data_block` drops unsafe paths); `exportLinkEl` is the only
  non-https link (host-listed relative paths, every segment percent-encoded).
  `TX_PREFIX_VERSION` bumps whenever tools or system blocks change shape.

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
  six started at 10 to preserve existing keys; identity is at 11 (regex
  mentions left `adopted_codes`), and `tests/test_drawing_cache_versions.py`
  records each bump's new golden key in `BUMPED_KEYS`. `_LEGACY_SCHEMA_VERSION` stays
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
  (`WRITTEN` / `INDEXED` / `REPORTED` / `FAILED`) per placement. `REPORTED` is
  the `REPORT_ONLY` outcome (a ruled-out finding): nothing was planned for the
  PDF, so it is the one success that is not read back from it. `coverage_status` comes from
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
  never a comparison against one model id. Opus 5.5, Sonnet 5.5 and Opus 5
  declare it (`stop_reason="refusal"`, HTTP 200); Haiku 5.5 has no server-side
  fallback and does not. The API picks the substitute
  by refusal category (Opus 5.5 → Opus 5 / Opus 4.8, cyber → Opus 4.8;
  Sonnet 5.5 → Sonnet 5). `core.api_config.call_with_refusal_fallback`
  attaches `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) on
  every real-time call (`digest.stream_message` and every stage's `create`)
  and re-routes through `client.beta.messages`. The parameter is rejected on
  the Batches API. The served-by signal is a `fallback_message` entry in
  `usage.iterations`, read once by `RequestUsage.from_message` (`served_model`,
  per-attempt `hops`). Never compare top-level `model` with the request (an
  alias echoes back canonical; the fakes default to `claude-opus-5`). A
  fallback answer: (1) is priced per attempt at the model that ran it —
  `_record_usage` and the batch rescue's `_attach_usage_attempt` split `hops`
  (declined = `REFUSED`, rescue carries `requested_model`); (2) is never cached
  — every write site checks `any_fallback_served` / `fallback_served_model`;
  (3) is reported by `RunUsage.model_fallbacks()` (run.log `Fallback:` line,
  manifest `usage.model_fallbacks`). A stage whose usage reaches the ledger
  must carry `request_usage`, or its fallback is priced at the requested
  model. Content echoed back into history goes through
  `api_config.drop_declined_partial` (investigation turns, citation pause
  resumes): the declined partial's thinking/`tool_use` is neither executed nor
  echoed.
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
- **PyMuPDF holds the GIL** for the whole of `get_pixmap` and `tobytes("png")`,
  so a render on a worker thread freezes the GUI's Tk thread. The GUI calls
  `render.enable_raster_worker()` (one spawned process; `_rasterize` is the one
  pixel path for tiles, overviews and `render_region`) and
  `annotate.isolate_writes_from_caller(True)`. The worker must stay
  byte-identical (same file, page, clip and zoom); any failure falls back
  in-process, a dying pool is dropped after `_RASTER_MAX_POOL_FAILURES`, and a
  patched `get_pixmap` / `tobytes` / `open` keeps the in-process path. Render
  batches end with `_release_raster_worker_docs()` so the worker never holds a
  source file open. Off by default for every other caller.
- **A GOTO destination is a third coordinate space.** A destination is default
  user space; `add_*_annot()` and `insert_text()` take the un-rotated
  CropBox-relative space. `_derotate_point` / `_derotate_rect` are annotation
  space and are wrong for a destination; `_view_rect_to_user` is the conversion.
  Ground truth is an annotation's raw `/Rect`, which is why a link to a drawn
  mark reads that `/Rect` back instead of converting anything.
- **PyMuPDF only writes `/XYZ` destinations**, through `insert_link` and
  `set_toc` alike, and each applies its own transform to the point. The writer
  creates the object with a plain page jump and replaces `/A` with a `/FitR`
  action (`_insert_goto_link`; the outline items via `get_outline_xrefs()`).
  `Page.get_links()` does not report a link inserted earlier in the same
  session — find it by diffing `/Annots`. `get_links()` / `get_toc()` read a
  `/FitR` back as a page jump to `Point(0, 0)`, so tests read destinations raw
  (`tests/fixtures/pdf_links.py`); `get_toc(simple=False)` → `set_toc` therefore
  flattens any `/Fit*` bookmark the source already had to a page-top `/XYZ`.
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
