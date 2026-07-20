# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project aims to
adhere to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Replaced whole-file JSON cache rewrites with transactional SQLite/WAL row
  storage and automatic in-place legacy migration.
- Added exact complete-result caching for paid post-digest review stages; failed,
  malformed, incomplete, or evidence-invalid results are never reused.
- Reused digest renders and Files-API uploads for critique, and overlapped Batch
  rendering with upload through a bounded one-sheet lookahead.
- Added bounded, deterministic concurrency for independent cross-QC, prose,
  verification, and per-source reviewed-PDF work while keeping PDF access safe.
- Narrowed pre-render invalidation to conservative page dependency graphs, with a
  whole-source fallback whenever page isolation cannot be proven.
- Added Economy, Hybrid, and Fast processing choices and full-stack QC estimates;
  model/retry usage now records each billable transport attempt separately.
- Accelerated exact anchoring and ledger de-duplication with indexed candidates,
  and moved Export All work off the GUI thread.

## [1.1.0] - 2026-07-18

A usability-focused release: the standalone GUI is now more compact and
self-explanatory. No engine, output, or pricing changes — analysis, exports, and
the review pipeline are byte-for-byte identical to 1.0.0. Installed 1.0.0 apps
are offered this update automatically.

### Added

- **Collapsible input sections in the GUI.** The optional inputs — Anthropic API
  Key, drawing-PDF drop zone, per-run focus, project specifications, QC review,
  and processing — each fold into a thin click-to-toggle header, so the window
  opens compact and a section only claims space when it's in use. Collapsed
  headers carry a live one-line state summary (e.g. `3 PDF(s)`, `2 on`,
  `loaded`). The drop zone auto-collapses once files are loaded and re-expands on
  Clear; the API-key section starts collapsed when a key is already present and
  expanded (prompting for one) when it isn't.
- **Collapsible activity log.** The activity log now folds away like the sections
  above it. Its collapsed header shows the latest status line, folding it never
  shifts the action buttons, and the always-visible progress line above it keeps
  live run status in view even while the log is collapsed.
- **In-app "How do I get a key?" guide.** A link beside the API-key field opens a
  short, step-by-step guide to creating an Anthropic API key, so a first-run user
  is never stranded at the first screen.
- **Cost & time expectations surfaced throughout the GUI.** Mode-aware hints now
  state the concrete cost/time to expect at each decision point (batch vs
  real-time transport, the exhaustive QC run), single-sourced so the checkbox,
  the cost dialog, and the help panel never disagree.

### Fixed

- Corrected the batch cost framing so the "~$0.50" figure is tied to the digest,
  not the full QC run.
- Fixed misaligned bullets in the GUI help modals.

## [1.0.0] - 2026-07-17

The first public release — the full vision pipeline, the exhaustive QC stack, the
run journal/manifests, and the Windows desktop app. (Entries below accumulated
during pre-1.0 development and all shipped in 1.0.0.)

### Added — QC markups on severity layers

- **Every finding's ink now lands on a per-severity PDF layer.** The reviewed
  PDFs group their markups into three optional-content layers —
  `QC markups - High/Medium/Low severity` — so a reviewer can show or hide a
  whole severity tier at once in Bluebeam Revu / Acrobat / Chromium (e.g. "just
  the high-severity issues"). Clouds, QC tags, margin callouts, leader lines, the
  overflow *AI Review Notes* callouts, and the set-level
  `Drawing_Set_Review_Notes.pdf` notes are all layered. Findings are grouped
  strictly by `severity` (a question-category finding rides its own tier even
  though its *color* stays blue; an unset/other severity folds into the low tier,
  mirroring the index triage rank). Layers are created only for tiers that carry
  ink, in a fixed high→medium→low order (deterministic output, I-7), and every
  layer ships **on** — a freshly-opened reviewed set renders exactly as before,
  the layers only add the option to filter. Additive and non-fatal (I-3): if the
  backend cannot create a layer the ink is drawn unlayered, and the DA-007
  reopen-and-reconcile coverage protocol is untouched (the `/OC` layer reference
  and the placement stamp are independent keys on the annotation object).

### Added — About modal in the GUI header

- **A fourth header button, "About", beside the three explainers.** It opens
  the same style of scrollable modal (content in `help_content.py`, pure data,
  hermetic-testable) showing the package version, the licensing story
  (AGPL-3.0-or-later, why PyMuPDF makes the copyleft mandatory, the NO
  WARRANTY notice), the author's copyright (© 2026 Abraham Borg), and a
  clickable link to the author's LinkedIn. `HelpBlock` gains an additive
  `kind="link"` / `href` field; `gui.py` renders link blocks as underlined
  labels that open the default browser. Short button labels get a narrower
  width so the four-button row still fits beside the title.

### Added — project specifications upload

- **Upload real spec documents to ground the QC read.** A new "Upload spec
  documents…" button (`.pdf`/`.docx`/`.txt`/`.md`, extracted via `pypdf`/
  `python-docx` — new core dependencies, no PyMuPDF import, I-5 intact) lets
  the operator attach the project's actual written specifications for a run,
  gated by a blocking quality warning shown every time it's clicked. The
  extracted text is folded into the digest system prompt as a distinct,
  clearly-labeled `<project_specifications>` block (never conflated with the
  unrelated external "Project Context" term, nor with the existing "Per-run
  focus" question field) — the model reports drawing-vs-spec conflicts as
  ordinary findings, so they flow through the existing ledger/anchor/verify/
  markup pipeline with no new plumbing. The block rides a prompt-cache
  breakpoint on the real-time path (never on the parallel batch-item build,
  which would only pay the cache-write premium with nothing to read); a
  two-tier character budget (400k/file, 400k total — a single spec may fill the
  whole budget) bounds cost and attention dilution, with truncation surfaced as
  a non-fatal run warning. Pre-run cost estimates now show the specs'
  contribution, priced correctly for each transport (flat repeated input on the
  batch path; cache write-once/read-many on real-time).
  `digest_cache._SCHEMA_VERSION` bumped 7→8.

### Changed — stuck/sick batch recovery stays on the batch transport

- **A stalled or backend-sick drawing batch is now recovered by resubmitting
  the unresolved sheets as a fresh batch, never by dropping to full-rate
  real-time calls.** Previously, when the primary batch made no per-item
  progress for the stall window (`Drawing batch stalled; digesting N sheet(s)
  directly`) — or when the Batches backend errored every item — the run rescued
  those sheets via synchronous, streamed Messages calls
  (`_rescue_failed_items_sync`), which forfeited the 50% batch discount for the
  rescued sheets (flagged `rescued`, billed at full rate). `collect_drawing_batch`
  now takes a `recovery_transport`, and the pipeline passes the new
  `RECOVERY_BATCH`: the stuck batch is canceled and its sheets resubmitted as
  fresh batches (same still-uploaded `file_id`s, same params, discount intact)
  in a bounded loop (`_recover_via_batch_resubmit`), each resubmission carrying
  its own stall watch. The loop is bounded on both axes — at most
  `DEFAULT_MAX_BATCH_RESUBMIT_ROUNDS` (4, override
  `DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS`) fresh batches, and never past the
  collection budget — so a genuinely dead backend can't loop forever; once the
  rounds/budget are spent, unreached sheets keep a clean, retriable batch error
  (still never a real-time call). The original `RECOVERY_DIRECT` behavior is kept
  as the default for direct callers and the unit tests. Trade-off: a persistently
  stuck backend now takes longer to give up (repeated batch rounds rather than an
  immediate real-time rescue), in exchange for never silently degrading a run to
  real-time pricing.

### Changed (GUI export options cleanup — GUI-only)

- **Trimmed the GUI's per-artifact export buttons.** The standalone window's
  *Save Markdown…* and *Save Findings CSV…* buttons were removed to keep it fast
  and uncluttered; the window now shows *Save HTML Report…*, *Save Reviewed
  PDF(s)…* (after a QC run), and *Export All…*. **Export All… is kept** — it is
  the only GUI path that writes the `run.log` / `run_manifest.json` run record,
  including for a failed run that produced no digest and no reviewed PDF, so it
  stays enabled even then. This is a **GUI-only** change — no engine or export
  functionality was deleted. The two removed buttons' handlers (`_on_save`,
  `_on_save_csv`) remain in place as dead code (marked as such in `gui.py`), the
  folder export still emits `findings.json` / `findings.csv` / `sheet_text/` /
  the raw Markdown, and the library API (`write_drawing_export`,
  `write_findings_csv`, `build_html_report`) is unchanged, so either button can
  be re-surfaced later.

### Added (Phase 27 — end-to-end acceptance & release gate, DA-027)

- **The §19.1 automated trust gauntlet.** One deterministic synthetic *oracle
  set* (`tests/fixtures/gauntlet.py`) packs every product guarantee into a
  single hermetic exhaustive run: two different PDFs sharing a basename, pages
  at 0°/90°/180°/270° plus a reduced CropBox, vector/raster/hybrid pages, a
  pre-existing reviewer annotation (DA-029), unrelated same-tile findings,
  repeated source text disambiguated by tile hint, prose items that match /
  structure / degrade (one structuring call forced to fail), a critique finding
  reproduced across both reads plus a read-1 singleton, a deterministic
  arithmetic mismatch (`TEXT_EXTRACTED` operands, §17.5), a stale-reference
  auditor finding, a dual-leg cross-sheet conflict, a REJECTED finding, an
  unanchored margin finding, a set-level synthesis conflict, two materially
  different claims citing one code reference (DA-017), and a corrupt input.
  The cold run asserts the fifteen §19.1 guarantees (source isolation through
  byte-exact verifier evidence — every image the verifier saw equals a saved,
  hashed artifact — to receipt-backed coverage, output agreement across
  report/CSV/JSON/PDF/manifests/run.log, sacred prose, and
  `COMPLETE`-only-when-everything-succeeded). The second run proves the warm
  cache (zero digest/critique API calls, zero rasterization, findings rebound
  to current source identity, stable QC numbering); the third mutates one
  source and proves only it misses the cache and the new content reaches
  analysis. Per-stage failure injection (bad model output for
  synthesis/critique/cross-QC/citation; crashes for auditors/harvest/verify;
  a markup writer failure) proves every required stage degrades to
  PARTIAL/FAILED honestly — incomplete PDFs are renamed, tallies never claim
  unwritten ink — while the standard digest ships (I-3). A dense-page run
  proves callout overflow lands on the appended AI Review Notes page with
  receipts, never over drawing content (§17.6).
- **§19.2 large-set acceptance.** Synthetic-digest tests prove the 44-sheet
  two-discipline map→reconcile topology finds a conflict absent from every
  local shard, resolves both legs to distinct real sources, and bills every
  shard + reconciliation call; the 84-sheet three-shard variant proves the
  reduction never isolates a group; a failed shard holds the pass at
  PARTIAL with its findings still usable.
- **§19.3 live API canary** (`tests/test_live_api_canary.py`, `network`
  marker — skipped without a real key, never in CI): live digest schema +
  structured-findings parse, critique structured-output compliance across both
  reads, the pinned `web_search` tool type + real tool-result parsing with
  claim-complete assessments, the Files API upload→delete lifecycle (deleted
  ids must be unretrievable), no-key-in-exports redaction, and an
  environment-identity printout for the release record.
- **Release-gate tooling.** `scripts/run_acceptance.py` (one-command §19.8
  automated gates with a PASS/FAIL table), `scripts/scan_secrets.py`
  (credential-shape scan over tracked files; wired into CI),
  `scripts/check_licenses.py` (stdlib dependency-license/AGPL-notice audit),
  and `scripts/benchmark_drawing_analyzer.py` (§19.7 scenario harness —
  offline hermetic by default with mechanical gates: warm runs make zero
  digest/critique calls and rasterize nothing, sources hash once per run,
  usage totals reconcile; `--live` measures real tokens/cost descriptively).
- **CI release gates (§19.8).** Two new pinned, least-privilege jobs:
  `security-gates` (secret scan; ruff correctness-classes E9/F63/F7/F82 only —
  no style churn; the license/AGPL audit; `pip-audit` with a documented dated
  `--ignore-vuln` exception policy) and `build` (wheel/sdist under the new
  committed `requirements-release.lock` constraints, `twine check`, clean-venv
  install smoke proving packaged profiles + version metadata agreement).
- **Acceptance documents.** `docs/WINDOWS_ACCEPTANCE.md` (§19.4 real-Windows
  path/input/GUI matrix), `docs/PERFORMANCE_AND_COST_VALIDATION.md` (§19.7
  scenarios, gates, medians-based tolerance, recording template), and
  `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` (the master §19.9 record: automated
  gates, live canary, Windows, Bluebeam Revu / Acrobat / Chromium script
  (§19.5), Excel/Notepad script (§19.6), deferral/waiver table, sign-off).
- **Release metadata.** Version bumped to **1.0.0rc1** (release candidate; the
  final tag requires the completed acceptance record); a new
  `tests/test_release_metadata.py` pins `pyproject.toml` and
  `drawing_analyzer.__version__` together, and the CI install smoke pins the
  installed-distribution leg (what `run.log`'s `app=` reports).

### Fixed (Phase 27 gauntlet regressions — §3.3/§4 status honesty)

- **Incomplete critique reads now hold the critique stage at PARTIAL.** A
  sheet whose two self-consistency reads did not both return parse-valid
  output (or whose critique call raised) was logged and recorded in usage but
  never surfaced into the stage status, so a run with a partial critique could
  still roll up `COMPLETE — "Exhaustive QC complete"`. `_run_critique_stage`
  now returns the degraded sheets and the stage scores PARTIAL with the
  per-sheet reasons (§3.3: "incomplete critique reads → PARTIAL or FAILED,
  never a valid skip"); the useful findings are kept and the run error names
  the count. Caught by the gauntlet's failure-injection matrix.
- **A cross-QC response with no parseable findings object is no longer a
  clean empty.** Prose-only, malformed, or truncated structured output from
  the whole-set call, a shard map call, or a reconcile call parsed as
  "0 conflicts, COMPLETE" (§4 item 4 violation: a failed parser presented as
  a clean empty result). Each call site now returns an explicit error —
  holding the stage at PARTIAL and, on the sharded path, counting the shard
  failed — while still salvaging any parseable numeric claims (additive,
  I-3). Test fixtures that returned *bare unfenced* JSON for cross-QC calls
  (never valid under the fenced contract, silently tolerated before) were
  corrected to fenced blocks (§22).

### Added (Phase 26B — final exhaustive activation, export hardening & report completion, DA-010/025/026/031/033)

- **The exhaustive completeness gate is OPEN (§18.0, DA-010).** A clean NORMAL
  `qc_markups=True` run now rolls up to **`COMPLETE` — "Exhaustive QC
  complete"** end to end (pipeline status, GUI completion line, report banner,
  run.log/run_manifest). The §8 phase-gates are permanent regressions enforced
  by stage statuses themselves: a failed cross-shard reconciliation, an
  unchecked cited claim (DA-017), a missing evidence crop/leg, unresolved
  callout overflow, or a mid-run source mutation each hold a required stage at
  PARTIAL / coverage at INCOMPLETE, which the §3.3 roll-up can never call
  COMPLETE — gate or no gate (regression-tested). The GUI's "complete
  intentionally withheld" notice is replaced by an explicit DEBUG_OVERRIDE
  explanation (the one remaining cause of a no-degraded-stage PARTIAL).
- **Excel-safe `findings.csv` (§18.5.1, DA-031).** Model/drawing-controlled
  text cells whose first meaningful character is a formula sigil
  (`=`, `+`, `-`, `@`, tab, CR — even behind leading whitespace/control
  characters) are apostrophe-prefixed so `=HYPERLINK(...)`/DDE payloads open
  inert in Excel. Host-owned numeric/enum columns (page, rect, statuses) are
  untouched — an ordinary negative coordinate survives exactly — and
  `findings.json` keeps the canonical values.
- **Export containment + atomic publish (§18.5, DA-033).** Every artifact
  name/destination passes one allocator boundary (`safe_artifact_name` +
  `contained_target`): traversal components and absolute/drive prefixes are
  dropped (a POSIX file legally named `..\\..\\evil.pdf` lands flat), invalid
  and ADS-colon characters are substituted, Windows reserved device names and
  trailing dots/spaces neutralized, lengths capped, collisions deduped
  deterministically — and every resolved target is **proven** beneath the
  export root before a byte is written. Evidence copies never follow symlinks
  (`os.walk(followlinks=False)` + per-file checks). The export itself now
  writes into a temporary sibling directory and publishes with one atomic
  same-volume rename: an interrupted export leaves an explicit
  `*_INCOMPLETE`-labeled folder, never a final-looking one missing artifacts.
- **Severity-first reviewed-PDF index (§18.7, DA-025).** Index rows (and the
  per-source overflow notes + `Drawing_Set_Review_Notes.pdf`) now sort high →
  medium → low/question, then source input order → page → anchored position →
  QC id, so the index reads as a punch list. Section structure (rejected /
  operator-gated), GOTO links, receipts, and the stable `QC-###` ids are
  unchanged — display order simply stops tracking numeric id order.
- **GUI "Export All…" (§18.0/§18.5).** The GUI gains a primary action that
  writes the complete export folder via `write_drawing_export` — report.html,
  Markdown set, findings.json/csv, `sheet_text/`, reviewed PDFs, `evidence/`,
  `markup_manifest.json`, `run.log`, `run_manifest.json` — atomically
  published to a picked directory (the per-artifact save buttons remain). Key
  handling matches Save HTML Report: never embedded unless the checkbox opts
  in.
- **HTML report §18.6 completion.** Prominent status banners gain a per-stage
  status table; a **High severity only** toggle joins the existing
  issues-only/category/search controls (filters never change the underlying
  totals — a live "showing K of N" counter appears instead); duplicate display
  names are disambiguated with the opaque source id; citation assessments
  render per reference; prose carry-through and provenance chips; a "Run
  record" panel names the run id and the exported `run.log` /
  `run_manifest.json`; accessibility pass (labels, `aria-pressed`,
  `aria-sort`, keyboard sorting, live regions). Ask-AI key-on-first-use and
  the 401 session-key clear were verified already present (DA-026, Phase 17).

### Added (Phase 26A — run journal, run.log & run manifest, DA-024)

- **Per-run journal (`run_journal.py`, §18.1).** Every `extract_drawing_context`
  call — GUI or library, standard or exhaustive, even an all-inputs-rejected
  run — now owns a `RunJournal` (`ctx.run_journal`): an append-only event trace
  with a fresh opaque `RUN-…` id and a **thread-safe monotonic sequence**, so
  events emitted concurrently from the digest worker pool are totally ordered.
  The pipeline emits typed events end to end: `RUN_START` (with environment/
  version identity), per-input `INPUT_ACCEPTED`/`INPUT_REJECTED`, `RUN_BLOCKED`
  (preflight), `CACHE_PRESCAN`, per-sheet `SHEET_DIGESTED` (ok/failed, cache
  hit, digest size, raster/vector, text-layer length, omitted blank tiles,
  findings-parser drift), `STAGE_START`/`STAGE_END` for every stage (mirroring
  each recorded `StageResult`, giving the run.log stage table its durations),
  `LEDGER_SEALED`/`LEDGER_NUMBERED` (with post-seal adds), `SOURCE_MUTATED`,
  `MARKUP_RECEIPTS` (expected vs WRITTEN/INDEXED/FAILED, receipt-derived),
  `USAGE_TOTALS`, and `RUN_END`.
- **Sanitize-at-emit boundary (§18.3).** Every journal field value passes the
  shared Phase 17 secret-redaction filter (`diagnostics.redact_secrets`) plus a
  new absolute-path scrubber (`/home/user/…/M-101.pdf` → `.../M-101.pdf`;
  Windows drive/UNC/quoted/`file://` forms handled; https URLs untouched),
  is flattened to one line, and is length-bounded **before it is stored** — a
  secret or private directory name can never enter the journal, whatever
  renders it later. Emission never raises (advisory, I-3 spirit).
- **`run.log` in every export (§18.2, DA-024).** `write_drawing_export` now
  writes a per-run, human-readable log: run id + start/end, app/OS/Python/
  PyMuPDF/SDK versions, model + prompt/cache-schema/coordinate-space versions,
  the classified input inventory (submitted/accepted/rejected with `SRC-####`
  ids), normalized configuration + profile snapshots, a per-sheet table, a
  stage table (status/calls/items/duration), per-family usage + derived totals
  (sub-cent costs shown as `<$0.01`, never rounded to zero), ledger/receipt/
  coverage accounting, prose carry-through counts (§14.9), outputs written,
  sanitized errors, the full event trace, and the final three-state outcome —
  the same vocabulary as the GUI completion line (§3.3). UTF-8 + CRLF for
  Notepad. Explicitly excluded: keys, headers, base64/image bytes, prompts,
  drawing text, long quotes, raw wire logs, absolute paths.
- **`run_manifest.json` in every export (§18.4, DA-024).** The machine-readable
  counterpart (`schema_version` 1): run identity + environment, final status
  (`qc_status`/coverage/configuration kind/counts), `RunConfiguration`,
  source inventory (**no absolute paths, no content SHAs** — `source_id` +
  input order are the portable provenance; §6.1/§10.4), profile snapshots,
  typed stage results, the append-only usage ledger with derived totals +
  `pricing_effective_date`, findings/prose/evidence summaries, receipt-derived
  markup coverage, sanitized errors, and the **sha256 + byte size of every
  artifact in the export**. Non-circular finalization order: ordinary
  artifacts → `markup_manifest.json` → `run.log` → `run_manifest.json` (hashes
  everything, `run.log` included, excludes only itself). `00_index.md` lists
  both new artifacts.
- **Context additions.** `DrawingContext` gains `run_journal`,
  `input_inventory` (the §6.1 `SourceDocument` records, previously discarded),
  and `prose_accounting` (the §14.9 harvest carry-through counts, previously
  discarded with the `HarvestResult`). `SheetGeometry` gains
  `omitted_tile_count` (`None` = not recorded, e.g. a level-1 cache hit that
  never re-rendered — the run.log says so instead of claiming zero).

### Fixed (Phase 26A review — multi-angle adversarial review + Codex P2)

A 8-angle adversarial review of the Phase 26A diff (line-scan, removed-behavior,
cross-file, reuse, simplification, efficiency, altitude, conventions) plus a
Codex bot finding surfaced 17 issues, all fixed with regression tests:

- **Export can no longer fail after the deliverable is written.** The new
  `run.log`/`run_manifest.json` writers were unguarded on
  `write_drawing_export`'s critical path — a duck-typed context field (a raw
  `Decimal` from a third-party `to_dict`, a malformed `prose_accounting`)
  raised *after* every ordinary artifact was on disk. Rendering/serialization
  now degrades per section (run.log) or to an error-bearing stub manifest;
  stray non-JSON values serialize through the sanitize boundary
  (`json.dumps(default=…)` so a `Path` can't leak a directory); only real
  file-write failures propagate.
- **`omitted_tile_count` was dead on every cache-enabled run** (the GUI's
  default): with a cache active, all geometry came from the no-render prescan,
  so even freshly rendered misses reported nothing. A `_GeometryOmissionSink`
  now merges the render-time blank-tile count onto the prescan record for
  misses; true cache hits honestly stay "not recorded".
- **Run-level terminal status (Codex P2).** `journal.finish()` stored the QC
  status, so a clean standard run's manifest said `final_status:
  "NOT_REQUESTED"` — indistinguishable from "didn't finish". A shared
  `derive_run_outcome` (COMPLETE/PARTIAL/FAILED: nothing analyzed → FAILED;
  digest shipped but errors/partial QC → PARTIAL) now feeds both `finish()`
  and run.log's outcome line, and `RUN_END` carries `outcome=` alongside the
  QC `status=`.
- **Scrubber hardening (empirically reproduced cases):** URLs are masked
  during the path scrub and restored byte-identical, so a `:`-before-slash
  URL segment (`…/wiki/File:/x/y.png`) is never mangled; the Windows-drive
  pattern now requires a directory component (`option A:/B`, `drive C:\ is
  full` untouched); `file://` matching is case-insensitive; and the journal
  gains **known private roots** (input parents, work dir, home — registered
  by the pipeline) replaced literally before the regexes run, which is what
  makes spacey Windows directories (`C:\Users\John Smith\…`) scrub reliably.
  HTML 5xx bodies in exception strings are tag-stripped like the diagnostics
  file does.
- **Empty-but-error-free digests are now failures in every accounting
  surface** (`SheetDigest.ok` semantics): `SHEET_DIGESTED` status, the digest
  `STAGE_END` ok/failed counts, and run.log's per-sheet rows all agree with
  the header sums (previously such a sheet was "OK" in the event but "failed"
  in the summary).
- **Single-source helpers replace drift-prone copies:** one
  `models.receipt_status_counts` behind the journal event / run.log line /
  manifest coverage block (was 3 hand-kept tallies); `_finish_stage()` records
  a StageResult AND emits its journal event in one call (a stage can no longer
  land in the roll-up but miss the trace); run.log's outcome line composes
  from the shared `qc_status_label` (§3.3 vocabulary); `evidence_summary` is
  shared by run.log + manifest; prose accounting keys are defined once at the
  producer (`HarvestResult.accounting()`); `run_manifest.json`'s
  `generated_at` uses the journal's UTC-Z timestamp dialect (was naive local
  in the same document); critique usage labels derive from the stamped refs
  (no path-list ordering precondition); reviewed PDFs are hashed once per
  export (shared cache between the two manifests); run.log's Outputs section
  derives from the folder itself (cannot drift from what the manifest
  hashes); `_journal_environment` uses plain imports (a broken import can no
  longer silently erase the whole version-identity block); dead
  `events_for` removed; emit no longer runs the full sanitize pipeline on
  code-owned field keys.

### Changed (Phase 26A)

- **Usage `stage_instance` labels are now portable (§10.4).** The per-sheet
  digest/critique usage records previously embedded the raw PDF path
  (`digest:/abs/path/M-101.pdf:p0`); they now carry the host-owned portable
  identity (`digest:SRC-0001:p0`), because `run_manifest.json` exports usage
  records verbatim and an absolute path in a portable artifact would leak the
  user's directory layout. Rollups were always per-family, so no consumer
  changes. The manifest additionally passes the whole usage block through the
  sanitize boundary as defense in depth.
- `export.write_drawing_export` writes two more files into every export folder
  (`run.log`, `run_manifest.json`) and returns the same folder path as before;
  `build_export_documents` (the pure document builder) is unchanged.

### Added (Phase 25 — reference grammar, tile semantics, auditors & callout placement, DA-019/020/021/022)

- **Unified sheet-ID grammar & negative corpus (DA-020, §17.2/17.3).**
  `auditors/sheet_ids.py` is now the single host-owned foundation every auditor
  (reference / sheet-index / naming / title-block) and the profile / cross-sheet
  resolvers share. It learns the set's numbering **convention** from the ids it
  actually contains (alpha/digit/separator *signatures*) and recognizes the
  hyphenated (`M-101`), **compact** (`FP101`), and **dotted** (`M1.01`) families —
  the compact/dotted families were previously unrecognized, so a compact-numbered
  set had an *empty* inventory and no reference could resolve. A **negative
  corpus** (`is_non_sheet_reference`) keeps code/standard citations (`NFPA 13`,
  `IBC 202`), transmittal numbers (`RFI-123`), voltages (`480V`), room numbers,
  and dimensions from ever becoming a sheet finding, even when close to a real id.
  Strong/medium trigger tiering and a **low-confidence** mode (a one-sheet set runs
  strong triggers only, suppresses the fuzzy near-typo path, and reports the
  confidence limitation). Sheet IDs **split across adjacent PDF words** (`"M-"`
  `"101"`) are rejoined so the sheet still enters the inventory.
- **Stronger deterministic auditors (DA-021, §17.4).**
  - *Title-block:* a high-confidence **label→value** field-class path (project
    number, package/project **name** incl. multiword, date) flags a value that
    differs from the set consensus at **any** distance — catching substantially
    different and multiword values the recurrence path (edit-distance-≤2 single
    tokens) cannot. A labelled field on too few sheets, or a label-less lone token,
    stays telemetry; mere absence is never flagged.
  - *Sheet-index:* each entry is classified through the shared resolver, so a
    malformed / out-of-convention entry (a likely index typo, low) is surfaced —
    not silently dropped — and kept distinct from a grammar-valid absent entry
    ("not present in the provided set", medium).
  - *Naming:* clusters by a `(letters, digits)` key, so a changed **number** is
    meaning-bearing — `A1-2` no longer merges with `A2` — while `C1R`/`C1-R`
    (same digits, separator-only drift) still does.
- **`tile_label` contract removes tile base ambiguity (DA-019, §17.1).** The model
  now returns the exact visible label it saw (`"tile_label": "r1c1"`) instead of an
  ambiguous `[row, col]` array; `tiling.parse_tile_label` converts it to the
  canonical zero-based `[row, col]` with a grid bounds-check. A legacy `tile` array
  is still accepted, **explicitly** as zero-based and bounds-checked (never guessing
  `[1,1]` meant `r1c1`). `findings.csv` gains a human `tile_label` column.
- **Precise arithmetic provenance (§17.5).** A mismatch is trusted `DETERMINISTIC`
  only when the claim's own quote independently carries every operand
  (`operand_origin=TEXT_EXTRACTED`); a mismatch computed from model-transcribed
  terms stays `UNCERTAIN` and is crop-verified before it inks as ground truth. The
  popup states the provenance. A magnitude-aware relative tolerance replaces the
  blanket abs-0.5 rule that hid small-value errors (`0.2+0.2` printed `0.5`).
- **Non-obscuring callout placement + review-notes overflow (DA-022, §17.6).**
  Rect-less findings are packed into visually-clear bands — each box validated
  against the words, a rendered **occupancy mask** (piping/symbols/raster), and its
  siblings — and a leader is drawn only when it would not cross another callout.
  A callout that will not fit overflows to an appended **AI Review Notes** page
  (with a GOTO link back to its source), never stacked over the drawing.

### Changed (Phase 25)

- Digest cache schema **6 → 7**: the tile parse changed and `Verification` gained
  `computation_method` / `operand_origin`, so pre-v7 entries miss once and re-derive.
- `DIGEST_PROMPT_VERSION` / `CRITIQUE_PROMPT_VERSION` auto-bump (the findings
  instruction now requests `tile_label`), invalidating stale digest/critique caches.

### Fixed (Phase 24 review remediation — 16 adversarial-review findings)

A multi-agent adversarial review of the Phase 24 diff surfaced 16 confirmed
issues, now all fixed with regression tests:

- **`discipline_token` regression** — a compact two-letter discipline with a suffix
  segment (`FP101-A`, `FA101-N`, `CE201-X`) was misread as a project code and
  returned the wrong discipline. The project-prefix guard now requires **3+** leading
  letters (disciplines are 1-2; project codes are 3+), so `FP101-A` → `fp` again
  while `AVC10-F-D-01-1` → `f` still holds.
- **Sharded cross-QC numeric claims were orphaned** — the map/reconcile prompt keyed
  claims by `sheet_handle`, but the shared claim parser only reads `sheet_id`, so
  those claims never reached the arithmetic auditor. The prompt now emits the handle
  in `sheet_id`, and it is rebound to the real sheet host-side.
- **Cross-QC reduction tree missed cross-group conflicts** — when facts overflowed
  one reconcile call, the old tree kept only the first child (`merged[:cap]`). It now
  splits facts into half-cap groups and reconciles **every pair**, so a conflict whose
  two sheets land in different fact groups is still found (fan-out capped, honest
  degradation past the cap).
- **GUI profile leak & mislabel** — auto-suggested profiles now reset when the file
  set changes / on Clear (a fire-protection suggestion no longer carries into an
  unrelated electrical run), and a profile in the default user dir is labeled `user`,
  not `built-in`. The apply logic reuses the tested `resolve_profile_selection`.
- **GUI preflight PyMuPDF thread-safety** — overlapping preflights now serialize their
  PyMuPDF access under a lock (I-5) and only the most recent result is applied.
- **Citation cost, tally & handle tolerance** — the web-search fee is billed per
  *request* (a reference with many claims issues several), `CitationCheckResult.by_ref`
  is populated again, the no-client fallback records its assessments (so `items_out`
  is right), and claim/sheet handles are matched case/bracket-tolerantly.
- **Test-quality fixes** — the citation fake clients now route by request *content*
  instead of worker-thread arrival order (removing flakiness), the DA-017
  "verdict-never-covers-an-omitted-claim" guard now forces the cross-chunk scenario
  deterministically, and the dual-crop evidence test proves the two legs are
  byte-distinct crops from distinct sources.

### Added (Phase 24 — cross-sheet, profile, citation & evidence completion, DA-015/016/017/018/028)

- **Cross-sheet QC is now whole-set at every size (DA-015).** Above 40 sheets the
  pass no longer "shards and unions" (which silently missed any conflict whose two
  sheets fell in different shards — it made **no** reconciliation call at all).
  It now uses a **map → reconcile** architecture: it shards by discipline; each
  shard call returns its local conflicts *and* a set of compact, grounded
  `CrossQCFact`s (the comparable data points another shard might contradict); then a
  final **reconciliation** call compares those facts across *all* shards and emits
  the cross-shard conflicts, so a coordination error spanning a mechanical and a
  fire-protection sheet is found. Facts that overflow one call reduce through a
  balanced tree. The model never sees source identity — in the sharded path it works
  with **request-local opaque handles** (`S001` …) that are validated against the
  request manifest and translated to real sources on the host (an unknown handle
  leaves the item unbound); and every fact's `exact_quote` (and every reconciliation
  quote) is validated against the retained source text before it is trusted, so an
  ungrounded quote never becomes a trusted dual-anchor finding. `CrossQCResult` now
  reports shard/reconciliation completeness and a failed shard or reconciliation
  holds the stage at `PARTIAL` while its findings stay usable.
- **Cross-QC text budgeting is loss-aware (DA-028).** An over-long sheet text layer
  is still capped, but the omission is now **counted and surfaced**
  (`text_chars_omitted` / `budget_degraded`, a stage warning, and the run log),
  never a silent slice — and a degraded budget holds the pass at `PARTIAL`.
- **Citation verdicts are claim-complete (DA-017).** A citation verdict now attaches
  to a finding **only if that finding's claim was in the request that produced it**.
  Every distinct claim for a reference is checked (chunked into claim-complete
  requests when there are many — the old path sent only the first three finding
  texts and pinned that single verdict onto *every* citing finding), the model
  returns a **per-claim** verdict keyed by a request-local opaque handle validated
  against the request, and each `CitationAssessment` (`reference`,
  `claim_finding_ids`, `status`, `request_id`, editions, sources) is bound to exactly
  the findings whose claim it covered. A finding that cites several references keeps
  one assessment **per reference** (`finding.citations`); the legacy
  `finding.citation` is derived as a summary. A request/parser/tool failure leaves
  the claim `UNCHECKED` and marks the stage `PARTIAL` — and never downgrades the
  engineering finding.
- **The verifier's evidence trail is complete and byte-exact (DA-016).** Every crop
  a verify call saw is now saved **and hashed before it is sent**, and only saved
  crops are sent — a verdict may never rest on an image absent from the trail. Each
  finding gets an `evidence/<QC-ID>/` directory with one `leg-NN__<sheet>_pN.png` per
  leg (a cross-sheet conflict saves every sheet's crop, in request order) and a
  `request.json` recording the ordered artifact metadata + verdict (no key, no
  unrelated drawing text). Each `EvidenceArtifact` carries the crop's `sha256` (the
  hash of the bytes on disk, which are the bytes the model judged), rects, dpi, and
  request order. A cross-sheet conflict is **never** decided from a single crop —
  fewer than two saved legs degrades to `SKIPPED` with a precise missing-leg reason.
  The folder export copies the **complete nested** evidence tree, and the HTML report
  and PDF popup list **every** artifact. `Verification.evidence_png` is retained as a
  back-compat alias to the first artifact.
- **Profile auto-suggest, snapshot, and selection (DA-018, §16.0/§16.4).** A new
  shared, host-owned sheet-id foundation (`auditors/sheet_ids.py`) provides
  normalization, a candidate lexer, an ambiguity-safe inventory resolver
  (`RESOLVED` / `UNBOUND` / `AMBIGUOUS`, never a silent first-wins), and
  **project-prefix-aware** discipline detection — so a project-coded id like
  `AVC10-F-D-01-1` now detects the fire-protection segment (`F`) instead of the
  project code (`AVC`), while plain forms (`FP-101`, `M1`, `E1.01`) are unchanged.
  A cheap **text-only preflight** (`preflight_sheet_ids`, no rasterization) detects
  each sheet id and auto-suggests profiles; `resolve_profile_selection` makes manual
  choice win (a deselection survives a later suggest refresh); and the selected
  profiles are **snapshotted** (name + version + content hash + source) at Analyze
  time onto `DrawingContext.profile_snapshots`, with a typed `profiles` stage
  (`SKIPPED_VALID` with no applicable profile, `PARTIAL` when a requested profile
  can't be resolved). The GUI grows a review-profile multi-select panel that
  auto-suggests off the loaded files and passes the selection into the exhaustive run.

### Added (Phase 23C — batch critique & upload lifecycle, DA-030/DA-034)

- **The critique now rides the Message Batches path in a `use_batch` run, at the
  ~50% batch rate (DA-030).** Previously the reviewer's two self-consistency reads
  ran real-time and inlined each sheet's ~37 images as base64 *twice* (once per
  read), making the exhaustive QC pass the dominant cost and leaving the documented
  "roughly half via Batches" economics untrue for the critique. A new
  `batch_critique` module uploads each uncached sheet's images to the Files API
  **once** and submits both reads as batch items (distinct `custom_id`s
  `sheet__{i}__r1` / `…__r2`) referencing that single shared upload — so the
  imagery is neither re-rendered per read nor re-uploaded, and both reads are
  batch-priced. The usage ledger records the reads with `transport=BATCH`, so the
  cost preview's critique component is now batch-priced and the discount is real.
  The self-consistency merge, provenance stamping, caching, and partial/failed-read
  semantics are the *identical* code the real-time path uses (a shared
  `outcome_from_message` / `result_from_outcomes`), so a batched sheet's verdict is
  byte-for-byte what a real-time one would be. Additive and non-fatal (I-3): an
  upload failure degrades **only that sheet** to a real-time fallback reusing the
  in-hand render, and a batch that can't be collected degrades those sheets'
  critique while the standard digest deliverable ships untouched. A whole-run
  Files-API outage trips the same run-fatal upload circuit breaker the digest path
  uses (after a few consecutive 401/403/404s the remaining sheets skip the doomed
  upload and go straight to the real-time read). *Scope note:*
  the reuse is **within** the critique's two reads; sharing one upload across the
  digest **and** the critique (§15.8's ideal) is a deliberately deferred follow-up.
- **Uploaded Files-API images are released on every exit path (DA-034).** Cleanup
  is no longer reached only on specific branches. In the new critique batch it runs
  in a `try/finally`; in the digest batch, `submit_drawing_batch` now deletes every
  already-uploaded file if `batches.create` raises (a submit failure used to leak
  the whole batch's uploads), and `collect_drawing_batch` releases the files if an
  unexpected error escapes the terminal-collection path (`results()`/parse/the
  follow-up round raising) before re-raising. A batch that is neither collected nor
  cancelable keeps its files to expire server-side ("detach safely"), and that
  retention is logged.

### Fixed (Phase 23B — usage & cost accounting, DA-014)

- **Token accounting is now an append-only usage ledger; no stage can overwrite
  another's counters (DA-014).** The QC pipeline used to fold the prose-harvest
  tokens into `v_in, v_out` and then **overwrite** them with `v_in, v_out =
  vres.…` (`=`, not `+=`) when verification ran — silently dropping the harvest
  tokens from the run total. Every API call/attempt now appends a priced
  `UsageRecord` (`stage_family`, `stage_instance`, `transport`
  REAL_TIME/BATCH/CACHE, model, input/output/cache tokens, tool uses, `cache_hit`,
  `parse_success`, `terminal_status`, `estimated_cost`) to a `RunUsage` ledger on
  `DrawingContext.run_usage`; `total_input_tokens` / `total_output_tokens` /
  `total_estimated_cost` are **derived** sums over it, so the grand total always
  equals the exact sum of the records. A cache hit records zero billed tokens with
  its cache-hit metadata; a response that consumed tokens but failed to parse stays
  billable; a batch call is priced at the batch rate and a real-time call at the
  standard rate — per record, so a mixed run prices each stage correctly.
- **Per-record pricing with a verified effective date (§15.7).**
  `core.pricing.usage_record_cost` prices one record by its own rate class —
  ordinary input/output, cache read (0.1×) / write (1.25×), and per-use web-search
  tool fee, with the batch discount applied only to token cost. `PRICING_EFFECTIVE_DATE`
  stamps when the rates were last verified (surfaced in the GUI/report so a stale
  figure is never presented as authoritative).

### Added (Phase 23B — honest exhaustive cost preview + post-run actuals, §15.7)

- **The GUI cost dialog previews the *exhaustive* run when QC Markups is on** —
  `estimate_exhaustive_run_cost` breaks the spend down per stage (digest+synthesis
  on the batch path; two critique reads/sheet, cross-sheet QC, prose harvest,
  verification, and citation real-time) and quotes a low–high **range** because
  verification and citation scale with the finding / unique-claim count. The
  completion summary and a collapsible **Token usage & estimated cost by stage**
  table in the HTML report show the *actuals* from the ledger — the same records
  the totals derive from, so GUI, report, and context always agree.

### Changed (Phase 23A — run configuration, status & persistence, DA-010/DA-012/DA-013)

- **`qc_markups=True` now resolves to — and runs — the full exhaustive stack
  (DA-010).** The GUI's *QC Markups* checkbox and the public API used to run only
  digest → anchor → verify → markup on the digest's own findings; critique,
  cross-sheet QC, the deterministic auditors, and citation checks never ran unless
  each was passed separately. A single normalization point,
  `resolve_run_configuration(...)` → an immutable `RunConfiguration`, is now the one
  place the option matrix is interpreted (§15.1): `qc_markups=True` turns on
  synthesis (≥2 sheets), two critique reads per sheet, cross-sheet QC, the
  auditors, prose harvest, anchoring, verification, citation checks, markup, and
  coverage reconciliation. The GUI *QC Markups* label now reads "exhaustive
  engineering review + marked-up PDFs" and inherits this behavior. Every stage
  reads the resolved config; no call site re-derives the boolean combination.
- **Per-stage flags are now `bool | None` (a tri-state).** `synthesize`, `critique`,
  `cross_qc`, `citation_check`, and `verify_findings` default to `None` — "use the
  product default." An explicit `True`/`False` is honored as an expert override;
  disabling a normally-required exhaustive stage (e.g. `qc_markups=True,
  critique=False`) records a `DEBUG_OVERRIDE` configuration and forces
  `qc_status=PARTIAL`, never a clean `COMPLETE`. Every legacy keyword still works.
- **One canonical run-status vocabulary (§3.3).** `DrawingContext` gains
  `qc_status` (`NOT_REQUESTED`/`COMPLETE`/`PARTIAL`/`FAILED`), a typed
  `stage_results` list (`StageResult`, one per QC stage with
  `NOT_REQUESTED`/`COMPLETE`/`PARTIAL`/`FAILED`/`SKIPPED_VALID`), and the resolved
  `run_configuration`. `roll_up_qc_status` derives the overall status
  deterministically; the GUI completion dialog and a new HTML report banner lead
  with it. A **temporary completeness gate**
  (`EXHAUSTIVE_QC_COMPLETENESS_GATE_OPEN = False`) keeps a clean exhaustive run at
  `PARTIAL` — Phase 23 must not advertise a completeness that Phases 24–25 have not
  yet delivered (cross-shard reconciliation, claim-complete citations, evidence and
  callout completeness). Phase 26 opens the gate.

### Fixed (Phase 23A — run configuration, status & persistence, DA-010/DA-012/DA-013)

- **A standard run now retains and exports its findings and sheet text (DA-012).**
  With neither QC checkbox, the pipeline used to discard geometry and leave
  `ctx.findings` empty. It now always captures each sheet's lightweight text/geometry
  record, ingests the digest's JSON findings into the ledger, binds them to source
  identity, and anchors them offline **for free** (no verify/critique/citation/
  prose-structuring/markup). The folder export always writes `findings.json`,
  `findings.csv`, and `sheet_text/`, the HTML findings card renders, and the export
  index is labeled "Findings & sheet text" (not "QC review") for a run that did no QC.
- **The deterministic-audit-only path is now truly zero incremental API cost
  (DA-013).** The prose harvester's straggler-structuring model call is gated to
  exhaustive QC only; the *Deterministic audit only* selection runs the auditors over
  the already-extracted text/geometry and makes **no** model calls beyond the digest.
  Its GUI label now reads "Deterministic audit only — no additional API calls", and
  the checkbox is disabled/marked redundant while *QC Markups* is checked (the
  battery is already included).

### Fixed (Phase 22 — structured-output, critique & prose-harvest correctness, DA-008/DA-009/DA-023)

- **A truncated / unclosed findings block can no longer leak into the sacred prose
  (DA-009).** The old fenced-block scanner required a closing ` ``` `, so a response
  cut off mid-JSON (max_tokens) matched *nothing* and its whole partial machine block
  was returned verbatim as `combined_text`. A new line-aware scanner
  (`scan_structured_blocks`) recognises an **unclosed** fence too, and
  `parse_findings_detailed` classifies every ending (`ABSENT` / `PARSED_CLOSED` /
  `PARSED_UNCLOSED` / `MALFORMED_CLOSED` / `MALFORMED_UNCLOSED` / `TRUNCATED`): in
  every non-absent case the prose is cut at the opener, so no machine block reaches
  the prose regardless of how the response ended. Ordinary prose that merely contains
  the word "findings" is still returned byte-for-byte (I-2). The one scanner is shared
  by digest, critique, cross-QC, and prose-harvest, so all four are truncation-safe.
- **A malformed / partial critique read can no longer look clean or corroborated
  (DA-008).** A critique read is now a *success* only when it returned a valid findings
  schema (an explicit `{"findings": []}` counts); a prose-only, missing-object,
  truncated, or malformed body is a **failure** — never an empty success. So it is
  neither merged as a clean read nor cached as complete. Each read is a
  `CritiqueRunOutcome` stamped with its own provenance (`critique_1` / `critique_2`) at
  production; the report's `critique×2` chip now reads from **real** provenance rather
  than being re-inferred from the `reproduced` boolean (that pipeline heuristic is
  gone). Self-consistency follows the truth table: two valid reads → `REPRODUCED` /
  `SINGLETON`; a requested read that *failed* → `NOT_ASSESSED_PARTIAL` (never silently
  reproduced); single-read mode → `NOT_APPLICABLE`. `Finding.confidence` carries the
  verdict and `reproduced` is derived from it. A result is cached only when every
  requested read parsed validly (the entry records `requested_runs` / `completed_runs`).
- **A long review checklist is no longer split into different items across the two
  reads.** The reads are compared for self-consistency, so both now receive the *same*
  full checklist — a finding prompted only in read 1 can no longer be stamped an
  uncorroborated singleton merely because read 2 was never asked about it.
- **A synthesis conflict that names no in-set sheet is no longer dropped (DA-023).**
  It becomes a **set-level** finding (`scope=SET`, no `source_id`,
  `anchor_hint="SET_INDEX"`) written to a new deterministic
  **`Drawing_Set_Review_Notes.pdf`** — analyzer-owned pages with their own artifact,
  placement ids, and reopened-and-reconciled Phase-21 receipts (`REVIEW_NOTES`). It is
  never pinned onto an arbitrary drawing, and it sorts into a final section after every
  source-scoped `QC-###`.
- **Every enumerated prose item now has an artifact-backed carry-through guarantee
  (§14.9).** The harvest enumerates each candidate item into a stable
  `prose_item_id` *before* processing, runs each under its own guard (one item's
  failure can no longer abandon the rest), and at the end reconciles the enumerated
  ids against the ledger — degrading any straggler one last time and reporting any that
  is still unaccounted as an invariant failure (surfaced in `ctx.errors`). The ledger
  merge unions `prose_item_ids` so an item's provenance survives dedup.
- **New:** `Finding.confidence` and `Finding.prose_item_ids` (additively serialized);
  a `ProseItem` data contract; `CritiqueRunOutcome`; parser-status and confidence
  constants in `models`; `scope` + `confidence` columns appended to `findings.csv`.
- **Cache schema bumped to 6:** stored findings gained the new fields, the critique
  entry records the read counts, and the parser was rebuilt — so every pre-v6 entry
  misses once and is re-derived rather than served as current. Prompt versions are
  unchanged (the prompts did not change in this phase).
- Review hardening: a critique read whose findings array was **non-empty but every
  item failed validation** (e.g. a category outside the enum) is now a *failed* read,
  not a clean empty success — a content-bearing body can never be frozen clean
  (`FindingsParse.raw_item_count` exposes the pre-validation count). And a partial
  critique that produced **no** merged findings (a valid-but-empty read paired with a
  failed one) is surfaced on `CritiqueResult.error` instead of reading as a genuinely
  clean sheet. The set-level `Drawing_Set_Review_Notes.pdf` is intentionally exempt
  from the `markup_verified_only` gate (it is a review-notes artifact, not drawing
  ink) — documented at both call and writer sites.
- Adversarial-review hardening (5 confirmed findings fixed): (1) a `max_tokens`
  truncation that cut **before the `"findings":` colon** — or before any key — now
  strips the fragment instead of leaking the `\`\`\`json` fence into the prose;
  (2) a fence line **truncated before its newline** (`\`\`\`json` at EOF, even a
  partial `\`\`\`jso`) is likewise recognised and stripped; (3) `compute_prose_item_id`
  now folds `page_index`, so an identical boilerplate note on two pages of one
  multi-page PDF no longer collides to one id and silently drops a distinct item
  (§14.9); (4) a set-level item recovered by the final reconciliation is tallied as
  `set_level`, not `degraded`; (5) a failure inside the set-level notes writer no
  longer discards the per-source reviewed PDFs already written to disk (the source
  result is committed before the notes writer runs; a notes failure only rolls
  coverage to `INCOMPLETE`).

### Fixed (Phase 21 — artifact-backed markup coverage, DA-007/DA-029)

- **A finding can no longer be reported as clouded when no annotation was written.**
  The old coverage tally was computed from an *intention* classifier
  (`ink_disposition`) — it described what the writer *meant* to draw, never what
  landed in the saved PDF. The writer now follows a **plan → draw → stamp → save →
  reopen → reconcile** protocol (DA-007): every analyzer annotation and every
  generated index row is stamped with a private PDF object key carrying its logical
  **placement id**, and after saving the file is reopened and each placement is
  reconciled against what is actually found. A placement counts only when its
  stamped, mandatory component is found again in the saved artifact; anything
  missing, failed, duplicated, or unexpected is reported honestly.
- **`annotate_pdf` / `write_reviewed_pdfs` now return a
  [`MarkupRunResult`](src/drawing_analyzer/models.py)** — the per-placement
  `MarkupReceipt`s (`WRITTEN` / `INDEXED` / `FAILED`), a **receipt-derived** tally,
  the reviewed-PDF paths, and a `coverage_status` (`COMPLETE` / `INCOMPLETE`). The
  old integer/`list[Path]` returns are available as `result.annots_written` /
  `result.reviewed_pdfs`. A per-finding draw failure becomes a `FAILED` receipt, not
  a silent skip counted as a success (I-3 still holds — the file ships for
  diagnosis).
- **Pre-existing / prior-run annotations can no longer distort reconciliation
  (DA-029).** Stamps embed a per-run `artifact_run_id`, so a stamp left by an
  *earlier* review of the same PDF (a different run id) never satisfies this run's
  plan, and an annotation the analyzer never wrote carries no stamp at all — both
  are transparently ignored. Coverage counts only *this run's* proven marks.
- **Gated and rejected findings now carry a real, reconciled index row.** A
  conservatively **gated** finding (verified-only mode) earns a "Not inked by
  operator gate" index row and a **rejected** finding a "Rejected by verification"
  row — each a proven `INDEXED` placement, never a bare no-artifact status (§6.4).
- **Incomplete markup output is labeled, never presented as complete (§13.6).** A
  reviewed PDF whose planned placements did not all succeed is written under an
  explicit `…_reviewed_INCOMPLETE.pdf` name; the run's `coverage_status` rolls to
  `INCOMPLETE`; the HTML report shows a red **Markup coverage: INCOMPLETE** banner;
  and the GUI's completion line reads **QC incomplete** (distinct from *Completed*
  and *Completed with QC warnings*). A source that changed mid-run (§10.6) is a
  `FAILED` (source-changed) placement, so it forces `INCOMPLETE` too.
- **New `markup_manifest.json` export (§13.7):** every planned placement, its
  terminal receipt, the coverage status, the receipt-derived tally, and the sha256
  of each reviewed PDF. It contains no API key and no absolute path (receipts
  reference basenames only), so it is portable. `00_index.md` and the report list it
  and describe the coverage state.
- **The run summary line is now receipt-derived** — e.g.
  `Ledger 3: 2 clouded, 1 margin, 0 rejected (indexed); coverage COMPLETE` — with
  `failed` / skipped buckets and a coverage verdict; nothing is counted from
  intention.
- Review hardening: each index row is reconciled against **its own** GOTO link (by
  the row's unique position), so two same-page rejected/gated rows can't cover for
  each other's missing link; **every** planned placement gets exactly one terminal
  receipt — an unroutable finding (source id/name matching no supplied PDF) is an
  explicit `FAILED`, never silently dropped into a false `COMPLETE`; a mutated
  source forces `INCOMPLETE` even when it produced no findings; and `FAILED`
  receipt errors carry only the exception *type*, so no absolute path can reach the
  portable manifest.
- Tests: reversed every markup test that asserted an intention-based count or the
  old return types; added `tests/test_drawing_markup_coverage.py`, a
  failure-injection suite that forces clouds, callouts, index pages, saves, and
  reopens to fail and proves the receipts report it (coverage `INCOMPLETE`, no false
  ink), plus prior-run-stamp isolation, pre-existing-annotation isolation (DA-029),
  dual-leg partial coverage, rotated-page receipts, duplicate-basename isolation,
  same-page index-row link matching, unroutable-finding accounting, and the
  portable manifest.

### Fixed (Phase 20 — lossless ledger reconciliation & QC-ID lifecycle, DA-005/DA-006)

- **Deduplication no longer deletes unrelated findings, and no longer fabricates a
  finding by mixing one issue's text with another's quote.** Two findings merge only
  when they are semantically the same *and* their **critical signatures** agree:
  a shared **tile is a search hint, never identity** (same-tile-alone merging is
  gone, DA-005), geometric rectangle overlap alone is never sufficient, and a
  conflicting signature blocks the merge even when the prose is similar —
  `500 gpm` vs `550 gpm`, `M-101` vs `M-102`, `shown` vs `not shown`, or different
  cross-sheet legs. Clustering is now complete-link (compatible with *every* member,
  not just the representative), so an `A+B+C` chain where `A` conflicts with `C`
  never collapses.
- **Coherent grounding (DA-006/§12.2):** a merged entry's grounded bundle — text,
  category, quote, tile, anchor — comes from **one** representative atomically; the
  loser's distinct quote is preserved in a new `supporting_quotes` field rather than
  spliced onto the survivor's text (the reproduced K-factor/relief-valve mixed-finding
  trap is closed). The representative of a cluster is chosen by a **total** quality
  order, so a given set of duplicates always collapses to the same entry and id; the
  pipeline ingests channels in a fixed order, so the run is reproducible (I-7).
- **QC ids are now positional (DA-006/§12.4):** the ledger gained an explicit
  `OPEN → seal() → SEALED → number() → NUMBERED` lifecycle. Numbering happens
  **after** anchoring (the freeze-before-anchor ordering is gone), so `QC-001…`
  follow source input order → page → anchored-before-unanchored → top → left. A
  cautious post-anchor **Pass B** (`reconcile_post_anchor`) folds a duplicate the
  ingest pass couldn't see without geometry. A post-seal add is now an
  invariant failure that marks the run incomplete instead of inventing a `QC-XTRA`
  number that reads like ordinary output.

### Fixed (Phase 19B — cache identity & schema migration, DA-004)

- **A stale cached digest can no longer be served after a visible PDF change.** The
  level-1 (pre-render) cache key hashed only a page's content streams + referenced
  images + `page.rect` *dimensions*, which missed page **rotation** (a 180° flip
  changes neither), a same-size **CropBox** re-crop, and any rendered
  **annotation** — so an edited sheet could hit a stale entry and skip rendering,
  serving the wrong (and, after Phase 19A, wrong-coordinate-space) digest. The
  premise was confirmed empirically against the old fingerprint (180° rotation,
  same-dims CropBox offset, and an added markup all hashed identically).
- **Level-1 identity rebased on the whole source file's `content_sha256`** (§11.5):
  hashed **once per source** (reusing the inventory's value), it covers every byte —
  content, forms, images, rotation, CropBox, and annotation appearance streams — so
  any visible change re-keys. Folded in alongside it: the canonical coordinate-space
  version (`PAGE_VIEW_V2`), a **renderer-environment fingerprint** (OS/arch +
  PyMuPDF/MuPDF build, so a cache moved between installations misses rather than
  serving pixels this one wouldn't reproduce), the annotation-render policy, the
  page index/count, the grid/overlap/target, the blank-suppression mode, and the
  text-extraction cap. The per-page object-graph fingerprint is retired (the
  whole-source hash subsumes its form-XObject special case). The prescan hashes the
  bytes **on disk at prescan time**: it reuses the inventory hash through a `stat`
  fast-gate but **re-hashes on any drift** (`current_content_sha256`), so a source
  rewritten between the inventory and the prescan keys on its *current* revision —
  a stale level-1 hit that served the previous revision's digest is impossible
  (§10.6), including in a non-markup run the mid-run mutation check doesn't cover.
- **Critique level-1 cache added** (`critique_cache_key_level1`): the critique reads
  the same images as the digest, so an unchanged exhaustive re-run previously had to
  rasterize every sheet merely to compute the PNG-bytes critique key and discover
  the result was already cached. A pre-render level-1 scan now serves a cached
  critique with **neither a render nor an API call**; misses render, critique, and
  store under the level-1 key too (store-under-both). A warm exhaustive re-run now
  skips **both** the critique API calls and rasterization.
- **Cache schema bumped to 5**, so every pre-existing level-1 / critique entry
  misses once and is recomputed (a concise expectation, not a run error). Two
  critique cache-serving/storing helpers were extracted so the level-1 and level-2
  tiers materialize a hit and a stored entry through one code path.

### Fixed (Phase 19A — canonical page geometry, DA-003)

- **Findings are now placed correctly on rotated and cropped drawing pages.** A
  sheet with `/Rotate 90|180|270`, or a `CropBox` smaller than / offset from the
  `MediaBox`, previously mis-placed its findings: the anchor rectangle came from
  PyMuPDF's un-rotated, CropBox-relative text-extraction space, but the
  verification crop clips in the *rotated* page-view space — so on a rotated page
  the crop the verifier saw was blank, tile disambiguation chose the wrong
  occurrence of a repeated quote, and margin callouts drifted. The two spaces were
  characterized empirically against the pinned `pymupdf==1.28.0` (rendering real
  pixels, preserved as fixtures in `tests/test_drawing_geometry.py`), not assumed.
- **One canonical coordinate space, `PAGE_VIEW_V2`** (top-left origin, post-CropBox,
  post-rotation — the frame of the images the model reads) now carries every word
  rectangle, anchor, verification crop, and persisted finding rectangle.
  `render.py` transforms extracted words into view space once (via the page's
  rotation matrix) and captures a new `PageGeometry` (view dims, MediaBox/CropBox,
  rotation, and both affine matrices as plain floats) on `RenderedSheet` /
  `SheetGeometry`. `annotate.py` transforms each rectangle/point back to page space
  (via the derotation matrix) at the write boundary and draws FreeText callouts with
  `rotate=page.rotation` so they read upright on a rotated sheet. `anchor.py`,
  `tiling.py`, and `verify.py` are unchanged in logic — they now operate on
  view-space coordinates consistently and remain PyMuPDF-free.
- **New pure helpers** `models.normalize_rect` / `models.transform_rect` (finite +
  positive-area validation; a rect that inverts under a transform is *sorted*, never
  clamped — so the previously reproducible inverted rectangle is impossible by
  construction). `models.PageGeometry` round-trips to/from `dict` additively.
- **No coordinate flip on an ordinary page:** rotation 0 with a default CropBox
  yields identity transforms, so the common case is byte-for-byte unchanged. The
  digest cache is intentionally untouched here — anchors are recomputed every run
  from freshly-extracted view-space words, so no stale-space rectangle can be
  served; the level-1 fingerprint's coverage of rotation/CropBox/annotations is
  Phase 19B. I-5 is preserved (the new geometry math is pure Python; the PyMuPDF
  transforms live only in `render.py` / `annotate.py`).

### Added (Phase 18C — mid-run source mutation detection, DA-001 §10.6)

- **A source PDF that changes on disk between analysis and markup can no longer
  get stale ink.** Every input is snapshotted (`content_sha256`) at inventory
  time; immediately before the markup writer reopens a file, the pipeline
  re-verifies each source against its snapshot (a `stat` fast-gate, then a full
  re-hash on any drift). A source whose bytes changed is **excluded from
  markup** — its findings, and any cross-sheet leg landing on it, are not inked
  (anchors computed from the earlier revision would land on the wrong content) —
  recorded on `ctx.errors` with a "re-run to mark up the current revision"
  message, and surfaced on the new `DrawingContext.mutated_sources`. Only the
  *findings* are filtered — the full accepted path list is preserved so the
  markup writer's `SRC-####` assignment does not renumber (dropping a middle
  path would misplace the survivors' ink); a mutated source ends up with no
  findings and is simply not written. The coverage tally accounts those skipped
  entries under a distinct `mutated` disposition ("N skipped (source changed)")
  rather than reporting ink no reviewed PDF contains. The good files still get
  their reviewed PDFs, and the standard artifacts already produced are retained.
  The check is pure (no PyMuPDF), so it stays outside the I-5 boundary.

### Added (Phase 18B — resilient input inventory, DA-002 / DA-035)

- **A corrupt, encrypted, or duplicate input no longer aborts an otherwise
  valid drawing set — or vanishes silently.** A new inventory step
  (`render.inspect_inputs`) classifies every selected path once as `ACCEPTED` /
  `DUPLICATE` / `UNREADABLE` (missing, permission-denied, corrupt, not a PDF) /
  `ENCRYPTED` (password-required) / `EMPTY` (zero pages), each with a sanitized,
  path-free reason. The pipeline processes only accepted documents and records
  every rejection on `ctx.errors`, so a mixed good/bad run ships a partial
  standard deliverable that names what it dropped. `source_id` is assigned over
  the **accepted** inputs in order, so a rejected file never consumes an id.
- **`SourceDocument` inventory records** (`source_registry`) carry the revision
  identity — a stat-guarded `content_sha256` (re-reads if the file changes
  mid-hash rather than register a mixed-revision hash), `byte_size`,
  `initial_mtime_ns`, and `page_count` — the foundation Phase 18C's mid-run
  mutation detection builds on.
- **Page-level resilience (§10.5):** if a single page fails to load or render,
  the remaining pages of that PDF — and every other file — still process; the
  failed page is recorded on `ctx.errors` and excluded, never a whole-run abort.
- **Preflight bounds (§10.7):** each page is dimension-checked *before*
  rasterization, so a pathological/NaN/oversized box fails visibly instead of
  allocating a ruinous pixmap; a large *legitimate* set above a configurable
  threshold (`DRAWING_ANALYZER_MAX_SHEETS` / `_MAX_FILES`) requires explicit
  confirmation (`extract_drawing_context(..., confirm_large_set=True)`) rather
  than being silently truncated; and a work/export-disk capacity check runs
  before a QC run begins (`qc_work_dir` set), blocking early rather than failing
  after paid API work. Inventory error reasons are scrubbed of any absolute-path
  token, and the `DRAWING_ANALYZER_MAX_*` overrides parse defensively (a config
  typo degrades to the default instead of crashing at import). PyMuPDF stays
  confined to `render.py` (I-5) — the inventory data model, hashing, and bounds
  are PyMuPDF-free in `source_registry`.

### Fixed (Phase 18A — host-owned source identity, DA-001)

- **A finding can no longer be attributed to the wrong source PDF when two
  inputs share a basename.** Previously every internal `(source, page)` lookup
  keyed on the file *basename*, so two `M-101.pdf` files from different folders
  collided: a finding from one could be anchored, verified, or **clouded onto
  the other**, and the reviewed copies received the union of both files'
  findings. Each accepted input now gets an opaque, host-generated `source_id`
  (`SRC-0001` …, assigned in input order by the new `source_registry`), which the
  model never sees and which does not depend on the filename.
- **`source_id` threaded end to end.** Added to `SheetRef`, `Finding`,
  `ConflictLeg`, and `NumericClaim` (additive, defaults to `""`), stamped at
  every production site (digest, critique, cross-QC, prose harvest, and all five
  deterministic auditors) and carried through serialization. A new
  `source_page_key()` helper replaces every collision-prone
  `(source_name, page_index)` key across the pipeline, ledger, anchor, verify,
  cross-QC, prose-harvest, auditor, and report lookups. `source_name` remains
  display-only.
- **`verify.py` no longer skips same-basename sheets.** Its ambiguity guard —
  which used to mark a duplicate-basename finding `SKIPPED` rather than crop the
  wrong drawing — is now a fallback that only fires when no `source_id` was
  assigned; real runs verify every sheet against its own source.
- **Reviewed-PDF names are source-disambiguated, not order-dependent.** When two
  inputs share a stem, the reviewed copies are named
  `<stem>__SRC-0002_reviewed.pdf` (deterministic, source-identifying) instead of
  a bare `_2`; unique stems keep their friendly `<stem>_reviewed.pdf` name.
- **Content ids fold in source identity.** `compute_finding_id` now includes
  `source_id`, so two different inputs sharing a sheet id, category, and quote
  can never collide in the evidence directory or the ledger. When no `source_id`
  is present the historical (source-independent) id is preserved exactly.
- **Cache hits are rebound to the current source (§10.3).** A content-keyed
  digest/critique cache entry can carry a former run's identity; on a hit,
  restored findings/claims are re-stamped with the current `SheetRef`, a
  source-derived fallback `sheet_id` is rebuilt (a real model id like `M-101` is
  preserved), and the content id is recomputed. Digest cache
  `_SCHEMA_VERSION` 3 → 4, so pre-existing entries miss once and re-digest.
- **`NumericClaim` carries `source_id` through its whole path.** Fresh critique
  claims are stamped at production, the arithmetic auditor's geometry resolution
  and claim-dedup key are `source_page_key`-based (so a duplicate-basename claim
  resolves to — and is never merged across — the right source), and the
  critique-cache rebind rebuilds a source-derived fallback claim `sheet_id`.
- **CSV/JSON exports gain a `source_id` column/field**; no absolute path leaks
  into any public artifact. New tests cover same-basename isolation through
  anchor / verify / annotate / ledger / export / report, the registry's
  dedup/ordering (identical canonical path, relative-vs-absolute), the cache
  rebind, and the source-aware id. This is Phase 18A of the split; input
  resilience (18B) and mid-run mutation detection (18C) follow.

### Security / CI (Phase 17B — headless-browser exploit tests + CI foundation)

- **Real headless-Chromium exploit suite for the report (DA-011/DA-027),**
  `tests/test_report_browser_security.py` (marker `browser`). It builds the
  actual report, loads it over `file://`, and proves the trust boundary end to
  end where a DOM emulator can't: an execution sentinel must stay unset while a
  malicious answer streams through the assistant's **incremental and final**
  render paths, while a hostile corpus (filenames, sheet IDs, quotes,
  categories, findings, focus, errors, evidence paths) sits in the report body,
  and after real hover/focus/click/image-error events. It also asserts the
  https-only URL policy on streamed markdown links and citations, that the
  no-key report prompts on first use and **Forget key** clears sessionStorage,
  and that the CSP actually blocks an injected inline `<script>`. Hermetic: the
  Anthropic `fetch` is stubbed with a canned stream — no network, no key — and
  the suite skips cleanly when Playwright/its browser is absent.
- **Fixed a streamed-answer render race in the assistant:** a trailing debounced
  markdown re-render could fire after the final block render and wipe the
  citation chips it had just appended. `finishBlock` now cancels any pending
  debounced render so the final render (with citations) is authoritative. The
  browser citation test surfaced this.
- **PyMuPDF import-isolation test (I-5),** `tests/test_import_isolation.py`: a
  static AST scan asserting only `render.py` and `annotate.py` import PyMuPDF,
  so the AGPL-confinement invariant fails loudly the moment a stray import
  appears.
- **Continuous integration,** `.github/workflows/ci.yml`: the hermetic suite on
  Windows + Ubuntu across Python 3.11/3.12 (byte-compile → import-isolation →
  full suite) plus the headless-Chromium security suite on Linux. Actions are
  pinned to immutable commit SHAs, permissions are read-only, and it triggers on
  `pull_request` (never `pull_request_target`). New `browsertest` extra pins
  Playwright for reproducible browser CI. (Marking the checks *required* is a
  one-time branch-protection step for an owner/admin.)

### Security (Phase 17A — report trust boundary, key store, log redaction)

- **The HTML report can no longer execute model-controlled HTML (DA-011).** The
  in-report Ask-AI assistant previously rendered streamed Markdown by assigning
  model output to `innerHTML` — drawing text feeds the prompts, so that output
  is attacker-influenceable. The renderer is rebuilt as a **safe DOM builder**
  (`createElement` + `textContent` only; no `innerHTML`/`outerHTML`/
  `insertAdjacentHTML`/`document.write` with model data anywhere in the report
  scripts). Every link — Markdown links **and** streamed citations — passes
  through a single URL validator that accepts only absolute `https:` URLs and
  rejects `javascript:`/`data:`/`file:`/`blob:`, protocol-relative, credential-
  bearing, and control-character URLs; a rejected URL degrades to inert text.
- **The whole report is now a hardened trust boundary, not just the chat.**
  Every untrusted value (source filenames, sheet IDs, titles, findings, quotes,
  errors, focus text, configuration) is escaped into element content or
  attributes on the Python side. The chat config is emitted as an inert
  `type="application/json"` island serialized so every `<` (and U+2028/U+2029)
  becomes a JSON string escape — no value can close the script element or form
  markup, and `JSON.parse` still round-trips it exactly.
- **Defense in depth: a hash-pinned Content-Security-Policy.** Reports carry a
  CSP `<meta>` that allows only the exact inline scripts by SHA-256 hash (no
  `'unsafe-inline'` for scripts; there are no inline event handlers), restricts
  `connect-src` to the Anthropic API (or `'none'` when the assistant is
  omitted), and forbids objects, `<base>` rewriting, and form submission.
- **Ask AI is present by default and prompts for a key on first use (DA-026).**
  A report built with no key previously omitted the assistant entirely; it now
  ships the assistant and asks the reader for a key at first use (kept only in
  the browser tab's `sessionStorage`), with a **Forget key** control that
  clears memory + `sessionStorage`. Embedded-key mode states truthfully that a
  runtime "forget" cannot remove the key from the file. New `include_chat`
  parameter (`build_html_report` / export builders) opts the assistant out.
- **Credential-safe API-key persistence (DA-032).** `save_api_key` now stores
  the key only in an OS credential store (Windows Credential Manager / macOS
  Keychain / Secret Service via `keyring`), trusted **only** after a verified
  round-trip. With no secure backend it raises `SecureKeyStorageUnavailable`
  instead of silently writing a plaintext file; the GUI turns that into an
  explicit consent prompt (declining keeps the key session-only). Legacy
  plaintext key files are migrated into the keyring on load/save and removed.
  `keyring` added to the `gui` extra.
- **Shared secret-redaction filter for diagnostics logs.** A
  `RedactingFormatter` masks `sk-ant-…` key material, `Authorization`/`Bearer`
  values, and named secret fields (`x-api-key`, `api_key`, `token`, `secret`,
  `password`, …) in every line the diagnostics file handler writes — including
  the optional SDK wire capture and formatted tracebacks — before serialization.
  Token *counts* (`input_tokens=…`) are preserved. This is the shared boundary
  the Phase 26 run journal will reuse.
- Added **SECURITY.md** documenting the report trust boundary, URL policy, CSP,
  API-key handling, log redaction, and the project data each artifact contains.

*Note:* the mandatory headless-Chromium exploit test and the Windows/Linux CI
matrix are Phase 17B (pre-authorized split); this change lands the safe
renderer, redaction, key-store hardening, and their hermetic tests.

### Documentation

- **README brought fully in line with the §18 gating amendment.** The GUI
  section no longer describes the retired "Verified findings only (on by
  default)" sub-toggle — it now documents the exhaustive-ink default, the
  renamed **Verified & deterministic only** opt-in (default off), and the
  **Include rejected (grey)** toggle; the cross-sheet-QC and anchoring sections
  no longer reference the old verified-only default (an `UNANCHORED` finding is
  documented as landing in a margin callout); the findings-card column list
  gains the `ID` column; the configuration table gains the previously
  undocumented `DRAWING_ANALYZER_CHAT_MODEL`, `DRAWING_ANALYZER_DIAGNOSTICS`,
  `DRAWING_ANALYZER_DEBUG`, and `DRAWING_ANALYZER_CACHE_DIAGNOSTICS` variables.
- **Package docstring updated** (`drawing_analyzer/__init__.py`): the module
  map now covers the full QC stack, and the stale "render.py is the ONLY module
  that imports PyMuPDF" claim is corrected (`annotate.py` is the second,
  deliberate importer — matching the README's licensing section).
- **`CLAUDE.md` added**: commands, big-picture architecture, the binding
  invariants (I-1…I-7, no-eval arithmetic, additive serialization, ledger
  coverage), and the PyMuPDF pitfalls, for AI-assisted development sessions.

### Fixed (post-Phase-16 review)

- **Synthesis sheet-id matching is boundary-aware.** A set holding both `A-1`
  and `A-10` no longer reads a synthesis mention of `A-10` as also naming
  `A-1` (which could make the never-named prefix sheet the conflict's primary
  anchor and add a bogus `also_on` leg): a neighbour that is alphanumeric —
  or a `.`/`-` connector with an alphanumeric beyond it, so naming detail
  `A-1.1` never names sheet `A-1` — rejects the match, while sentence
  punctuation (`"… on A-1."`) and slashes (`P-1/P-2`) stay valid boundaries;
  a shorter id additionally never counts inside a longer in-set id's mention.
- **A `DETERMINISTIC` verdict survives ledger merges without a rectangle.** A
  rect-less auditor duplicate (an arithmetic mismatch whose quote didn't
  resolve) no longer loses its host-computed verdict when merged into an
  earlier model entry — previously it would be treated as unverified and gated
  in verified-only mode; the anchored-member merge path also can no longer
  downgrade an existing deterministic verdict.
- **The §18 coverage tally only runs on markup runs.** A reference-audit-only
  run (`qc_markups=False`) no longer logs/reports `Ledger N: X clouded, …` for
  clouds that were never written to any PDF; `ctx.ledger_tally` stays empty and
  `ctx.ledger_tally_line` is `""` for such runs.

### The findings ledger — guaranteed carry-through of ALL QC items (Part III / Phase 16)

Nothing QC-flavored may live only in prose: every item from every channel lands
in one ledger and, from there, on the reviewed PDF.

#### Added

- **`ledger.py`** — the append-only per-run findings collection. Every channel
  ingests into it (the digest's JSON findings, the critique reads, cross-sheet
  conflicts, the deterministic auditors, harvested prose); duplicates merge at
  ingest (Phase 11's rules), **unioning provenance** (`Finding.sources`, new),
  keeping the most severe severity and the longest quote, and preserving the best
  anchor/verification either member carries (an auditor's pre-anchored
  DETERMINISTIC duplicate upgrades a model entry). `freeze()` assigns the run's
  `QC-###` numbers. Anchoring, verification, the citation check, the markup
  writer, the exports, the report table, and the index page now consume the
  ledger and nothing else. Provenance renders as chips
  (`prose+json+critique×2`) in the report rows and markup popups, and as a
  `sources` CSV column.
- **`prose_harvest.py`** — the legacy channel's guarantee (§17). The digest's
  prose Coordination/Conflict sections are split into items (the same section
  grammar as the report's "⚠ Issues only" filter — the prose is mirrored, never
  modified, I-2) and fuzzy-matched against same-sheet ledger entries; each
  unmatched straggler gets one small structuring call (item + text layer → one
  finding with a verbatim quote); a failure ingests a **degraded sheet-level
  entry** — the invariant is that no prose QC item fails to produce a ledger
  entry. Synthesis conflict statements are harvested per referenced sheet,
  dual-anchored when two sheets are named (synthesis now runs *before* the QC
  stages so its text exists to harvest). Per-sheet Focus sections harvest only
  behind `focus_findings_to_markups` (default OFF). The digest prompt gained the
  coupling sentence (prose Coordination/Conflict items must also appear in the
  JSON block), bumping the digest prompt version.

#### Changed

- **Gating amendment (§18) — all findings get ink.** The exhaustive default inks
  everything except REJECTED: anchored entries cloud (UNCERTAIN/SKIPPED dashed),
  rect-less entries become margin callouts (`[SHEET]` / `[UNANCHORED]`
  prefixes — the unanchored hallucination signal is flagged on the page, never
  dropped). REJECTED findings carry no ink by default but are always listed on
  the index page under **"Rejected by verification (n)"** with page links; the
  new `ink_rejected=True` (GUI: **Include rejected (grey)**) draws them grey and
  dashed. The GUI's "Verified findings only" sub-toggle became **"Verified &
  deterministic only"**, defaulting **OFF** (`markup_verified_only` default
  flipped False); suppressed entries tally as *gated*.
- **Coverage assertion.** At run end every ledger entry must be exactly one of
  clouded / margin-callout / rejected-indexed (gated only under the opt-in
  conservative mode); the tally is logged
  (`Ledger 47: 39 clouded, 6 margin, 2 rejected (indexed)`) and surfaced on
  `ctx.ledger_tally` / `ledger_tally_line`, in the GUI completion summary, and
  on the report's findings card. An unaccounted entry is recorded as a run error
  and fails the hermetic end-to-end test.

### Markup richness, citation check & index pages (Phase 15)

The reviewed PDF now reads like a numbered, navigable, senior plan-review set.

#### Added

- **QC numbering.** Every finding gets a sequential review number (`QC-001` …,
  ordered sheet → position; `assign_qc_ids`, stable within a run). Inked findings
  carry the number as a small FreeText tag beside the markup in the severity
  color; the same id appears in `findings.csv` (new leading `qc_id` column),
  `findings.json`, the HTML report (new sortable ID column), and the index page.
- **Severity styling & annotation types.** high = red, medium = orange, low /
  question = blue. DETERMINISTIC findings draw a **solid** border, model findings
  a revision **cloud**, opted-in unverified findings **dashed** + `[UNVERIFIED]`.
  Sheet-level / absence findings (`anchor_hint="SHEET"`) are now inked as FreeText
  **callout boxes stacked in a computed clear margin band** (largest text-free
  horizontal band, found from the word rectangles — `find_clear_band`), with a
  **leader-line arrow** to the reported tile's centroid when known.
- **Findings index pages** at the front of each reviewed PDF ("AI DRAFT REVIEW -
  FINDINGS INDEX"): a table of ID / sheet / severity / status / one-line text
  where every row carries a GOTO link to the finding's page + rectangle
  (link targets account for the inserted pages). Multi-page as needed.
- **Citation check (`citation_check=True`).** One web-search-backed call per
  unique cited code ref (server-side `web_search_20260209` tool — verified
  current, env-overridable), judged against the editions the set adopts
  (harvested offline from the general-notes text) and the current edition.
  Verdict (`CHECKED_SUPPORTS` / `CHECKED_MISMATCH` / `UNCHECKED`) attaches to the
  citing findings and shows in the popup, CSV, and report; a MISMATCH downgrades
  nothing — sometimes the stale citation *is* the finding. Handles `pause_turn`
  resumption; real-time only; new `Citation` model.
- **Exhaustive popups**: finding text, verbatim quote, cross-sheet pointer (legs
  cite each other by QC number), verification status/note, refs + citation
  verdict, the reproduced flag when uncorroborated, evidence filename, both ids.
- **Optional appendix page** (`DRAWING_ANALYZER_MARKUP_APPENDIX=1`, off by
  default): "checked and consistent" — arithmetic relationships that checked out
  and references that resolved (the references auditor now counts its resolved
  pointers into `audit_stats`).

### Deterministic auditor expansion (Phase 14)

More high-precision, zero-API markups for free — the class of defect a vision
model is unreliable at but code is exact at.

#### Added

- **`auditors/` package.** The single reference auditor grew into a battery;
  `run_auditors(rendered_sheets, claims=…)` runs the whole set and returns the
  combined `DETERMINISTIC` findings plus a `stats` tally. Each auditor is isolated
  so one failing never loses the others (I-3), and the package imports no PDF
  engine (I-5). `reference_audit=True` (the GUI **Reference audit** checkbox) now
  runs the whole battery, and its checks-passed tally lands on `ctx.audit_stats`.
- **Arithmetic auditor.** The critique and cross-sheet QC passes now additionally
  emit a `claims` array — numeric relationships they *transcribed* off a sheet
  (`{sheet_id, quote, kind: sum|product|factor, terms, expected, note}`). The host
  does the arithmetic itself (exact `Decimal`, tolerant of commas / units /
  fractions like `2 1/2`), **never `eval`, never the model's math**, and flags only
  relationships that genuinely don't add up (a flow-test total, a DIPA row missing
  its +30%). Matches are counted and surfaced as *"N numeric relationships checked
  ✓"*. New `NumericClaim` model; `parse_numeric_claims()` lifts claims from the same
  fenced block the findings come from; the critique caches claims alongside findings.
- **Naming-consistency auditor.** Harvests the set's tag lexicon, clusters tags
  sharing an alphabet shape within a small edit distance, and flags a rare spelling
  that drifts from the established one (`C1R` vs `C1-R`; a one-off `A1-2` against an
  `A2` vocabulary) — without flagging a legitimately distinct vocabulary
  (`A1`/`A2`/`A3`). Low-severity questions, every flagged occurrence anchored.
- **Title-block auditor.** Learns each sheet's title-block x-band from its sheet-ID
  location and flags a field value (project number, date) that drifts to a close
  variant of the set-wide norm on one sheet. Conservative: fires only on a variant
  of a value most of the set agrees on, never on mere absence.
- **Sheet-index auditor.** Detects a drawing index and diffs it against the set
  inventory both ways — an entry listed but not present ("in the provided set"), or
  a set sheet the index omits.
- **`reference_audit.py` is now a backward-compatibility shim** re-exporting the
  auditor from its canonical home `drawing_analyzer.auditors.references`.

#### Changed

- The critique and cross-sheet QC findings instructions gained the `claims` array
  (the critique prompt version bumps, re-critiquing rather than serving a stale
  read). The reviewed-PDF gating, prose digest, and `combined_text` are untouched.

### Exhaustive QC — the critique pass

Part II of the QC work: make the markup read like an experienced engineer's
review, not the digest's incidental noticing.

#### Added

- **Critique pass (`critique=True`) — "the reviewer".** A second full-coverage
  vision read per sheet (the same overview + tiles + text layer the digest sees),
  under a senior-QA-engineer persona whose only job is to find problems: errors,
  code concerns (cited conservatively), RFI-worthy ambiguities, internal
  inconsistencies, stale/copy-paste text, and **absences** — content a complete
  sheet should show but doesn't (`anchor_hint: "SHEET"`, no quote). It emits only
  the findings block, so the prose digest and `combined_text` are untouched (I-2).
- **Self-consistency.** The critique runs twice; a finding both reads surface is
  corroborated (`reproduced`), a singleton is kept but flagged. The merge
  deduplicates by anchor-rect overlap (IoU) once anchored, else the reported tile,
  and by normalized-text overlap. Digest and critique findings then pool into one
  per-sheet set before anchoring — cross-source agreement also marks `reproduced`.
  The flag is a soft confidence signal; it never suppresses a finding.
- **`Finding` gains `anchor_hint` and `reproduced`** (both optional, backward-
  compatible — read tolerantly from cache, no cache invalidation) and the critique
  is cached under its own key (a distinct namespace from the digest).
- **Cross-sheet QC pass (`cross_qc=True`).** A deliberate whole-set conflict
  hunt — one text-only reasoning call over all the digests + text layers (no
  images; large sets shard by discipline) that finds conflicts *between* sheets:
  the same tag valued two ways, twin notes diverged, a note contradicted
  elsewhere, a cross-reference whose target disclaims the pointer's claim.
  Distinct from the prose synthesis (untouched); `combined_text` never sees it
  (I-2). Findings carry **dual anchors** — a primary plus `also_on` legs resolved
  to their own sheets via the set's title-block ids — so the markup writer clouds
  **both** sheets of a conflict, each popup cross-referencing the other. `Finding`
  gains a backward-compatible `also_on`; the anchor resolver, markup writer,
  verification pass, and pipeline gained additive dual-leg support (a finding with
  no legs is unchanged). Cross-sheet findings are verified with a **dual-crop**
  pass — one crop per sheet in a single call — so a conflict can reach `VERIFIED`
  and cloud under the default verified-only gating (a single-sheet crop could only
  ever say NOT_VISIBLE).
- **Review profiles (`profiles=[…]`).** The owner's QC knowledge as versioned,
  injectable Markdown checklists: each profile's items are appended to the
  critique prompt ("APPLY THIS REVIEW CHECKLIST EXPLICITLY, ITEM BY ITEM"), so the
  reviewer applies encoded checks deliberately, not incidentally. Profiles load
  from the package's built-in set and from `~/.drawing_analyzer/profiles/`
  (override `DRAWING_ANALYZER_PROFILES_DIR`; a user file wins over a built-in by
  reusing its `name`). The selected profiles' fingerprint (name + version +
  content hash) folds into the critique cache key, so editing a checklist
  re-critiques; a very long checklist is split across the self-consistency runs
  rather than truncated. A starter **fire-protection** (NFPA 13) profile ships,
  and `profiles.suggest_profiles(sheet_ids)` proposes profiles by discipline.

### QC findings, verification & markup integration

Turns the analyzer from a pure coverage instrument into one that also
*proposes, verifies, and marks up* discrete review findings — **coverage
proposes, precision disposes.** Everything below is additive and off by default;
a plain digest run is byte-for-byte what it was before, and the prose digest that
feeds the downstream spec reviewer is never touched.

#### Added

- **Vector text-layer grounding.** Each sheet's `page.get_text()` text layer is
  lifted losslessly and sent verbatim in the digest prompt, ahead of the images,
  as the source of truth for exact strings (tags, schedule values, note numbers,
  sheet references) — the antidote to the OCR-of-raster digit errors that vector
  text can't make.
- **Structured findings.** The digest model additionally emits a machine-readable
  `findings` JSON block (category / severity / text / verbatim `source_quote` /
  tile / refs), parsed out of the response by a tolerant parser without
  disturbing the prose. Findings are cached alongside the digest.
- **Reference audit** (`reference_audit=True`, or the GUI **Reference audit**
  checkbox) — a deterministic, zero-API pass over the text layers that learns the
  set's own sheet-ID grammar and flags stale / missing / malformed
  cross-references, each anchored to its exact word rectangle with a closest-in-set
  suggestion. It never claims a sheet "doesn't exist," only that it "isn't in the
  provided set."
- **Anchor resolver.** Maps each finding's `source_quote` back to a rectangle on
  its page (EXACT / FUZZY / TILE / UNANCHORED tiers), offline and PDF-engine-free;
  an unmatched non-empty quote is the hallucination signal and is never clouded by
  default.
- **Verification pass.** For each anchored model finding, renders a high-DPI crop
  and asks one small Opus call whether the finding holds *in that crop*, mapping
  to VERIFIED / REJECTED / UNCERTAIN; the crop is written to
  `evidence/<finding_id>.png` regardless of verdict. Additive and non-fatal.
- **Reviewed PDFs + findings CSV** (`qc_markups=True`, or the GUI **QC Markups**
  checkbox) — a `<stem>_reviewed.pdf` per source PDF with real revision-cloud
  annotations (severity-colored, authored *"Drawing Analyzer (AI review)"*,
  populating Bluebeam Revu's Markups List), plus a Windows-Excel-friendly
  `findings.csv` (UTF-8 BOM, CRLF). VERIFIED + DETERMINISTIC findings are clouded
  by default; the original source PDF is never modified.
- **Folder-export QC inventory** — `findings.json`, `findings.csv`,
  `sheet_text/<sheet>.txt` per sheet, and `evidence/<finding_id>.png` crops
  written alongside the existing report / Markdown, plus the reviewed PDFs.
- **HTML report findings.** A pinned, sortable **QC Findings** card with
  color-coded status chips (Verified / Deterministic / Uncertain / Unanchored /
  Rejected); a per-sheet raw text-layer block that now feeds the report's
  full-text search; and a **Raster** badge on empty-text-layer sheets.
- **Performance.** A two-level digest cache that recognizes an unchanged sheet
  *before* rendering — skipping ~4.5 s/sheet of rasterization on a cached re-run —
  and a bounded parallel Files-API upload pool
  (`DRAWING_ANALYZER_UPLOAD_WORKERS`, default 6).
- **Hermetic acceptance suite** (`tests/test_drawing_acceptance.py`) encoding the
  end-to-end acceptance script: a fresh both-checkbox run, the reviewed-PDF
  appearance-stream guarantee, the stale-reference closest-match suggestion, a
  zero-digest-API cached re-run with identical outputs, and the raster fallback.

#### Changed

- **Render target 1992 px → 1560 px** per tile for ordinary vector sheets, now
  that the text layer carries the exact strings — cutting PNG bytes and image
  tokens ~40%. A sheet with an *empty* text layer (scanned / pasted raster) still
  renders at 1992 px, where the pixels are the only information channel.
- **Strict blank-tile suppression.** Only provably pixel-uniform tiles are
  dropped, and the omission is disclosed to the model. An opt-in near-blank
  heuristic (`DRAWING_ANALYZER_SUPPRESS_NEAR_BLANK`) defaults off.
- **Digest cache schema and prompt versions bumped.** The render-target change,
  the text-layer block, the findings block, and the two-level key each invalidate
  prior cache entries once; the first run after upgrading re-digests every sheet,
  then caches as before.
- **API facts re-verified** against the current Anthropic docs
  (`platform.claude.com`, 2026-07). The vision per-image caps (Opus 4.8 = 4784
  tokens / 2576 px), the >20-image 2000 px hard-reject rule, the 32 MB request-size
  limit, and the ~50% Message Batches discount all still hold, so **no `tiling.py`
  constant changed**; only the docstring's section citation ("General limits" →
  "Request limits") and the token estimator's hi-res-roster note were refreshed.
  (The high-resolution vision tier has since grown beyond Opus; the estimator
  intentionally keys the hi-res tier off the Opus whitelist, which is exact for
  this Opus-only tool and a safe under-estimate for anything else.)

#### Security

- **The API key is no longer embedded in the HTML report by default.** The
  in-report Ask-AI assistant prompts for a key on first use and keeps it only in
  the browser tab's `sessionStorage`, so the report file is safe to share. The old
  behavior is opt-in (`embed_api_key=True`, or a GUI checkbox) and stamps the
  report with a red *"don't share this file"* warning.

#### Isolation

- PyMuPDF (AGPL-3.0) imports remain confined to named modules: `render.py`
  (rasterizing sheets and crops) and now `annotate.py` (writing cloud annotations
  onto reviewed PDFs). No other module imports the PDF backend, so it can be
  swapped for a permissively-licensed one by rewriting just those two files.
