# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"      # engine + pytest   (GUI too: pip install -e ".[gui,dev]")
python -m pytest             # full suite — hermetic: no API key, no network
python -m pytest tests/test_drawing_ledger.py                # one file
python -m pytest tests/test_drawing_ledger.py::test_name     # one test
drawing-analyzer             # launch the GUI   (or: python -m drawing_analyzer)
python scripts/run_acceptance.py   # Phase 27 release gates (PASS/FAIL; hermetic — never the canary)
python scripts/measure_evidence_coverage.py --pdf SET.pdf   # WP-02 §7.1 coverage scan (zero API calls)
```

Python 3.11+. No linter/formatter is configured (CI runs ruff **correctness
classes only** — E9/F63/F7/F82). The `network` pytest marker is reserved for
tests that need real API access (the Phase 27 live canary,
`tests/test_live_api_canary.py`); everything that runs by default uses the
fakes in `tests/fixtures/fake_anthropic.py`. `conftest` skips `network` tests
only when no real key is set and `pyproject.toml` sets no default exclusion, so
**any entry point that spawns pytest must deselect the marker itself**:
`run_acceptance.py` routes every gate through `_pytest_cmd()`, which ANDs
`not network` into the child's `-m`, and `tests/test_run_acceptance.py` fails if
a bare `"pytest"` argv literal reappears anywhere else in that script. The §19.1 trust-gauntlet oracle
set + all-stage scripted client live in `tests/fixtures/gauntlet.py`; release
docs (Windows/viewer/Excel manual scripts, benchmark record, §19.9 checklist)
live in `docs/`; `requirements-release.lock` pins release builds.

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
booleans. Each QC stage records a typed `StageResult` — **including the digest**,
which carries one (`expected=True`) so a sheet the run never read reaches the
roll-up instead of only `ctx.errors` and the journal; it is the single
`STAGE_END` for that stage, since two would cost `stage_durations()` the
duration. `roll_up_qc_status()` folds them (+ Phase 21 `coverage_status`) into one
`qc_status` (`NOT_REQUESTED` / `COMPLETE` / `PARTIAL` / `FAILED`, §3.3). A stage's
own failure flag is always tested **before** any count derived from its result: an
exception leaves that result `None`, so a crash judged by counts alone is
indistinguishable from having had nothing to do (the bug that let a crashed
cross-verifier report `SKIPPED_VALID`). The Phase 23 completeness gate is **OPEN** (Phase 26B
§18.0): a clean NORMAL exhaustive run earns `COMPLETE`; the §8 phase-gates are
permanent regressions enforced by the stage statuses themselves (a failed
reconciliation / unchecked cited claim / missing evidence leg / mutated source
holds a required stage at PARTIAL, which the roll-up can never call COMPLETE).

**Usage & cost (Phase 23B, §15.6).** Token/cost accounting is an **append-only**
`RunUsage` ledger (`ctx.run_usage`): every API call/attempt appends a priced
`UsageRecord` (family, `transport` REAL_TIME/BATCH/CACHE, model, tokens, tool uses,
cache-hit, `estimated_cost`), and the run's `total_*` are *derived* sums — no stage
can overwrite another's counters (the old `v_in, v_out = vres…` overwrite is gone).
The ledger describes work that **happened**, not stages that were configured: a
stage that placed no call and took no cache hit appends nothing. Guard the
real-time record on the call count alone — the old `if X.api_calls or not
X.cache_hits` fired exactly in the no-work case it meant to exclude, so a
verification that verified nothing still reported two real-time calls.
`core.pricing.usage_record_cost` prices one record by its rate class; costs carry a
`PRICING_EFFECTIVE_DATE`. `RunUsage.is_billable_but_unpriced` is the single rule
for "this consumed billable usage the table cannot price", and it counts **cache
read/write tokens** as usage: omitting them let a record carrying 180k cache
tokens under an unpriceable model pass as "no usage", so a run with one $5.00
digest beside it reported **$5.00** — a complete-looking total that dropped real
spend, the exact failure the rule exists to prevent. It also counts tool uses by
**value, not key**: the dict is truthy whenever it has one, so `{"web_search": 0}`
— what citation writes when every ref came warm from the verdict cache — read as
billable usage and unknowned a run in which nothing unpriceable happened. Both
ends are fixed (`_record_usage` drops zero counts before storing) because either
alone lets the other bring it back. Never restate that rule; the
A/B harness had a second copy and it drifted within one commit. `cost.estimate_exhaustive_run_cost` is the pre-run
per-stage estimate (verification/citation quoted as a low–high band), and every
stage is priced with **its own resolved model** and the runtime's own
`critique_runs()` — the standard path once priced synthesis/focus at the digest's
threaded `model` while those stages actually follow `REVIEW_MODEL_DEFAULT`, and
the critique line was fixed at two reads regardless of
`DRAWING_ANALYZER_CRITIQUE_RUNS`. Critique imagery is counted with the critique
model, never reused from the digest count: `estimate_image_tokens` clamps at a
per-model cap (4784 hi-res / 1568 standard tier), so one count for two tiers is a
~3× error.

**Geometry-aware image tokens (WP-05 §10.1/§10.3).** The GUI prices from real
page shapes when the **profile preflight** has already measured the current file
list, and from the conservative allowance otherwise. There is no separate scan,
and that is a measured decision, not a preference: a fresh scan of 120 dense
sheets takes 6,896 ms and can wait 22,457 ms behind the preflight's lock, while
deriving the same records from geometry the preflight already built takes 0.4 ms
(`scripts/measure_scan_time.py`; the scan tracks **word count**, ~15 ms/1k words,
not sheet count). So `profiles.preflight_scan` returns sheet ids *and*
`SheetCostBasis` records from one walk, the GUI holds them under the same
generation guard the profile suggestions use, and `estimate_*_cost(bases=…)`
uses them **only when they cover every sheet** — a partial *list* falls back
whole, since a total mixing measured and conservative sheets is neither figure.
Covering every sheet is not measuring every sheet: a page that could not be read
still takes the conservative allowance inside an otherwise measured set, so
`shape_aware` comes from `ImageTokenEstimate.fully_measured` (never list length)
and the dialog names the count that fell back rather than claiming either
extreme. Bases are also gated on `source_registry.sources_fingerprint` — path +
size + mtime per file, re-checked at consumption — because the generation counter
tracks *selection* changes and cannot see a PDF overwritten in place, which is
ordinary when re-exporting a set to the same filenames. That gate is what makes
the ordering safe too: `_add_pdfs` refreshes the summary before the preflight
clears the previous selection's bases.
`pipeline.estimate_image_tokens_for_set` remains the deliberately conservative
allowance — every image a square at the *raster* target, at the model cap — and
its public meaning is unchanged. `cost.estimate_image_tokens_for_bases` is the
successor that prices each page from its real shape, given a `SheetCostBasis`
(`models.py`: displayed w/h in points, vector/raster/unknown, capped text length,
geometry-availability + error state — and deliberately no words, no full text, no
image bytes, no path). Two facts per page carry the whole correction: aspect
ratio and *does this page have words*, both from a scan that never rasterizes
(`render.iter_sheet_cost_bases`, or `models.sheet_cost_basis(geom)` to reuse an
existing prescan/preflight rather than becoming a second PDF owner). The
correction is ~1.9× on a vector E-size sheet.
`tiling.image_pixel_sizes` is the single home for that geometry (GUI, CLI and
tests all call it) and mirrors PyMuPDF's `(rect * matrix).irect` sizing — which is
**position**-dependent, so two identically-sized tiles can differ by a pixel and
no dimension-rounding rule reproduces it. Every tile is counted: blank
suppression is decided from rendered pixels and must never be *predicted* from
word absence, since a vector sheet's words sit in the title block while the body
is lines. An `unknown` page falls back to the conservative allowance and is never
assumed vector — vector is the cheaper target, so guessing it quotes low on
exactly the pages least understood — and an unmeasurable page is still quoted,
never silently dropped.

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

**Text extraction excludes annotations (P7 item 28).** `page.get_text()` folds
annotation text in, so a re-reviewed set fed its own prior QC callouts back as
`sheet_text`, contaminated `full_sheet_text` (which host grounding treats as
source evidence), and inflated the word count that decides `is_raster`.
`render._page_text_and_view_words` / `_page_word_count` /
`_page_text_and_word_count` read `page.get_displaylist(annots=False)` instead. The
raw `FzStextPage` it yields has no `extractText` and is rejected by
`page.get_text(textpage=…)` **even wrapped**, so words come from
`TextPage.extractWORDS()`. The trap: that display list is built for `page.rect`,
so its words are **already** canonical PAGE_VIEW_V2 while `page.get_text("words")`
is rotation-*invariant* — applying `_words_to_view` on top double-rotates every
anchor on a rotated sheet. `_page_text_and_view_words` owns that conversion for
both routes so the asymmetry cannot reach a caller; measured bit-exact against the
canonical long way round at every rotation × CropBox, and ~1.6× faster because one
display list serves both extractions. `_RENDER_IDENTITY_SCHEME` is **v4** for this
(the annotation bytes do not move, so a cached page would otherwise be served
contaminated text without re-extracting); no key *term* was added, since that
would be a second mechanism for one change.

**Page identity is page-local even across links (N23).** Any other `/Type /Page`
object reached transitively by `_page_dependency_sha256` is an **opaque leaf**: a
GOTO link annot references its destination page, whose `/Parent` is not stripped
the way the hashed page's own is, so the walk reached `/Kids` and every sibling and
one cross-sheet hyperlink made every sheet re-key whenever any sheet changed.
Nothing about the destination is hashed and nothing needs to be — the reference
already rides the referencing annot object, so retargeting still moves the key.

**Digest path:** `tiling.py` (pure geometry) → `render.py` (rasterization) →
`digest.py` (prompt + tolerant findings-block parser — fences are **line-anchored**,
accept 3+ backticks or tildes, and a closer must match its opener's character and
length, because an un-anchored scan let an inline ``` span open a phantom block
that swallowed the real findings JSON into the sacred prose), or `batch_digest.py`
(Message Batches + Files APIs, ~50% cheaper) → `digest_cache.py` (two-level
content-keyed cache — a hit skips rendering entirely and restores parsed
findings for free — but never a **truncated** read: both transports treat a
reply the model did not finish as an error whether it came back *empty or merely
cut off*, retry once at a raised cap from the shared
`digest.MAX_TOKENS_RETRY_CEILING`, and refuse the cache write if it is still cut
off, since a stored truncation is indistinguishable from a complete one on every
later run. Real-time accumulates usage across both attempts — each was billed —
and falls back to the truncated first read if the raised-cap call cannot land, so
the retry can only improve on that read, never lose it). The critique does **not** re-rasterize what the digest
already rendered: `render_spool.py` spools the digest's already-compressed PNG
bytes to a private temp dir and rebuilds the same `RenderedSheet` byte-for-byte
(nothing resized, recompressed or filtered), and the batch path adopts the
digest's terminal uploads instead. A second render is the per-page **fallback**
— an unspooled page (a digest cache hit rendered nothing), a grid mismatch, an
unavailable manifest, a failed spool read/write — and `_one_page_fallback`
re-renders exactly the page that failed without misassigning another. Run-local
and advisory: a failed spool write just leaves the key absent (I-3). Batch recovery of a stuck/backend-sick batch stays on the
batch transport for the pipeline (`recovery_transport=RECOVERY_BATCH`): a
stalled batch is canceled and its unresolved sheets resubmitted as fresh
batches (bounded rounds + collection budget, `_recover_via_batch_resubmit`), so
a run **never silently drops to full-rate real-time calls**; when the rounds/
budget are spent, unreached sheets keep a clean retriable batch error.
Every site that abandons a batch first **harvests** it
(`_harvest_abandoned_batch`, DA-035): `results` is filled only from a terminal
`results()` read, so on a non-terminal batch every slot reads `None` —
including sheets it completed **and billed** — and the rescue list was
therefore all of them. Cancellation is asynchronous, so a canceled batch still
reaches `ended` and its finished items stay readable; the harvest reads them
back between the cancel and the rescue list at all three sites (primary,
resubmission, follow-up — the last re-billing at full real-time rate). It
resolves **successes only**: an item that came back empty still needs the
rescue, but its billed attempt is parked on the slot
(`_park_usage_attempts`) so §15.6 keeps it. Its time is **additional**, added
back to each caller's start mark rather than deducted — it competes with the
rescue for the same seconds exactly on the `detached` path, and charging it
there turned a 3/3 recovery into 0/3, trading re-billing for lost sheets. A
batch that will not settle within the bound harvests nothing and the caller
resubmits everything, as before. The collection bound is
**24h** (`DEFAULT_BATCH_MAX_ELAPSED_HOURS`, the Batches API's own SLA),
overridable per call via `DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS`
(`_batch_max_elapsed_seconds`, resolved at call time from a `None` default, not
frozen at import) — safe to raise only because of the harvest. Hitting it
returns `DETACHED_MOVING` when items were still completing and `DETACHED` when
none had; the split is **diagnostic** (log line, per-sheet error,
`ABANDONED_*` terminal status), never a different disposition: leaving a
healthy-but-slow batch running would strand every sheet it was already billed
for, since `results()` is served only after a batch ends. The
legacy full-rate direct-call rescue (`_rescue_failed_items_sync`) is the
`RECOVERY_DIRECT` default kept only for direct callers/tests. The stall watch is
**tiered** (`_stall_timeout_seconds`): 25 min on the primary batch ("is it
moving at all?" — a healthy 39-sheet batch lands in ~10 min), 60 min on every
resubmission after it ("deep queue or sick backend?"); a flat hour on the first
watch once cost a real run two frozen hours for ~25 min of work.
`DRAWING_ANALYZER_BATCH_STALL_TIMEOUT_MIN` overrides **both** tiers with one
value. A queued batch is never silent: `_poll_until_terminal` emits a 5-minute
heartbeat (elapsed, items done, time left on the watch) to the log and `on_log`,
and the progress line carries elapsed minutes. Every abandoned batch appends a
**non-billable** `DigestUsageAttempt` (`billable=False`,
`terminal_status="ABANDONED_*"`, zero tokens) per sheet via
`_mark_batch_abandoned`, parked on the `_Slot` until the real digest absorbs it
— so §15.6 sees every attempt while the image-token estimate still counts only
response-bearing ones. Each slot records `served_by`, so the collect log names
both the submitted batch and the one that actually served the digests.

**QC stack** (each stage optional and independently cached):

- *Planning (Phase A §20, universal reviewer):* `set_identity.py` — one text-only
  call over a budgeted corpus (every digest head + early text layers + verbatim
  windows around each code-edition mention) → a bounded `SetIdentity`
  (disciplines, sheet→discipline map, jurisdiction, language, units, adopted
  codes with evidence quotes; the regex edition harvest unions in as
  `origin="regex"` — the backstop the model can't argue away). **Advisory only**:
  consumers take `SetIdentity | None` and never gate a finding on it — which,
  with the regex backstop, is why this stage runs on **Sonnet 5**.
  Both sanitizers coerce every list-shaped field through
  `set_identity._as_list` (P8 item 9): they are documented as never raising and
  the stages treat an exception as stage FAILED, yet a dict raised `TypeError:
  unhashable type: 'slice'` and a **string** passed silently and was consumed per
  character — `"refs": "NFPA 13 2016 §8.17"` reached the citation check as
  `('N','F','P')`, three live web searches for single letters. The
  international code-designation regex is **case-sensitive** (item 12): under
  `IGNORECASE` ordinary lowercase notes matched, so `is 1000 mm clearance` became
  Indian Standard 1000; `Eurocode` keeps its own case-insensitive group.
  `review_planner.py` — one text-only call authoring the per-discipline review
  checklist (bounded host-side: ≤60 items via `DRAWING_ANALYZER_MAX_PLAN_ITEMS`,
  the overage taken from the **longest** plan each round — trimming the last
  plan's tail deleted `mechanical` and `plumbing` outright while `architectural`
  kept everything, since plans sort by slug (N5) —
  overlong items dropped-never-truncated; every code-based item must name
  code+section+edition inline and never invent a section — the refs flow into
  `Finding.refs`, which the citation check verifies). Plans become caller-built
  `Profile` objects injected AFTER user profiles (snapshot `source="model"`),
  so `profiles_cache_fragment` gives cache correctness for free; both stages
  cache in `DigestCache` namespaces (`stage=identity` / `stage=review_plan`) so
  warm re-runs keep the critique `profiles_key` byte-stable. Both ride the
  critique stack (`run_identity` also on with citation alone); the standard run
  stays zero-extra-cost (DA-012/DA-013). Artifacts: `set_identity.json`,
  `review_plan.md`, a manifest `set_identity` key, and an additive combined-text
  section (I-2). Identity also feeds `check_citations(identity=)` (merged
  editions + jurisdiction line) and `cross_sheet_qc(identity=)` (preamble).
- *Finders:* the digest's findings block; `critique.py` (a second full-coverage
  vision read, run twice — self-consistency merge sets `reproduced`; on the
  real-time path the two byte-identical reads prompt-cache their shared image
  prefix when `runs>=2`, so the second bills it at ~0.1× — cache write/read tokens
  ride the ledger; the parallel batch path stays uncached, and `use_batch` resolves
  from `DRAWING_ANALYZER_USE_BATCH` when the caller leaves it `None`);
  `cross_qc.py` (text-only cross-sheet conflict hunt; dual anchors via
  `also_on` legs); `auditors/` (five deterministic zero-API auditors over the
  text layers, **all** grounded on the shared `auditors/sheet_ids.py` grammar
  foundation — Phase 25 §17.2/17.3: `id_signature`/`learn_grammar` learn the set's
  hyphenated/compact/dotted numbering convention, `classify_reference` +
  `is_non_sheet_reference` adjudicate a reference against it with a negative corpus
  so a code/tag/voltage/RFI/**drawing annotation**/dimension never becomes a sheet
  finding. `_ANNOTATION_PREFIXES` (REV/DET/DWG/TYP/SIM/NTS) is kept separate from
  the transmittal set because it is a different kind of thing; paper sizes are
  deliberately absent, since `A1`–`A4` are ISO sizes *and* real architectural ids
  and the corpus never consults the set. `references.detect_sheet_id_word` also vetoes
  before its bottom-right position score: position alone let a code citation in the
  general notes become the sheet's own id, and `build_inventory` learns the set's
  grammar from exactly those ids, so one general note redefined the convention
  every downstream auditor adjudicates against. That veto is
  **`never_a_sheets_own_id`, a strict subset of the reference corpus** — the
  reference corpus answers "does this token point at a sheet in the set?", safely
  No for things a sheet can still be *named*, so `_TRANSMITTAL_PREFIXES` is
  excluded: `SK-1` is a sketch issued as a sheet, and so are `PR-04` / `ADD-2`.
  Using the full corpus removed such a sheet's real title-block id from the
  running, and one un-vetoed `A-101` in a note then won at any position, so the
  sheet vanished from the inventory under its real name. Only that structural
  veto, never the learned grammar — that would be circular — so a same-shape
  distractor (`M-999`) can still win; closing that needs a two-pass harvest and is
  **not** done. `detect_sheet_id_word` is
  memoized on the sheet **object** (14 live call sites, none cached before); a
  ref-keyed process-wide dict would serve one stage's answer to another stage's
  rebuilt geometry, and `None` is a real answer so the memo needs a sentinel.
  `_merge_adjacent_id_words` caps its scan on **length, not fragment count** — the
  pathological input is a per-glyph text layer where a real `M-101` is five
  fragments, so a fragment cap would stop reconstructing the very ids it exists to
  find; the length cap takes it from n²·¹ (10 s at 2,000 words, ~5 min at 10,000)
  to linear with byte-identical output. `naming.py` refuses to report drift when
  there is no frequency winner unless both spellings share an `_arrangement`
  (same-kind runs, separators breaking them): without evidence of a convention the
  fallback was *lexicographically first wins*, which reported canonical `FP-101` as
  drift from mangled `F-P101` and `VAV-21` as a misspelling of `VAV-2-1`. An
  established winner still outranks structural doubt. `sheet_index.py`'s harvest
  remains unbounded and is deliberately **not** patched with a second copy of the
  corpus check — both diff directions already run every entry through
  `classify_reference` — because the real fix is region bounding, which moves the
  `_MIN_INDEX_ENTRIES` gate and re-baselines both directions together);
  `prose_harvest.py` — whose boilerplate filter is anchored at **both** ends
  (P8 item 6: anchored only at the start, it discarded every real finding that
  *opened* with No/None/Nothing/N/A, which is how an absence finding naturally
  opens), with the length floor at 8 and a `filtered` count so a drop cannot
  vanish — `expected` is built from what survived the filter, so `missing` read 0
  and `complete` was True over a real loss. That count is **observational** (the
  §7.2 discard-counter contract): filler is not a lost finding, so it feeds
  neither. `prose_harvest.py` (mirrors prose Coordination/Conflict items,
  synthesis conflicts, and opted-in focus items into findings — match first,
  one small structuring call for stragglers on **Sonnet 5** at `EFFORT_LOW`,
  degraded sheet-level entry on failure).
  Cross-QC's host-side grounding reads **`models.sheet_evidence_text(geom)`**,
  not `sheet_text` (WP-03A §2.1 trigger 1): `sheet_text` is the *capped* string
  the model was shown, while `full_sheet_text` is the uncapped reading-order
  text retained for host checks and **never sent**. A quote transcribed from
  pixels past `SHEET_TEXT_MAX_CHARS` is real source text, and grounding it
  against the cap silently dropped the leg — and with it the whole finding,
  which needs two grounded sheets. The helper is deliberately not
  `full_sheet_text or sheet_text`: a present-but-empty full text means "no
  textual evidence" and must not fall back, while `None` (older caller,
  hand-built fixture) means "unavailable" and does. A non-string is treated as
  unavailable rather than stringified into trusted evidence. Prompt bytes are
  unchanged — `cross_sheet_qc` entries and `_budgeted_text_layer` still carry
  the capped text — and `_cross_qc_cache_key` adds an `evidence_sha256` **only
  for a truncated sheet**, so every untruncated key stays byte-identical and no
  stored result was discarded (hence no `_CROSS_QC_CACHE_CONTRACT` bump).
  Grounding is **three-state** (WP-03B §8.3, `classify_quote_evidence`), not a
  boolean: `TEXT_GROUNDED` / `NOT_MATCHED_IN_TEXT` / `TEXT_EVIDENCE_UNAVAILABLE`.
  Collapsing the last two was the §2.1 trigger-2 bug — a scanned sheet, or the
  pasted raster region of a *hybrid* one (which has words, so `is_raster` is
  False and cannot identify it), can never satisfy a text check, and treating
  that silence as refutation dropped every leg **and every fact**, excluding the
  sheet from cross-shard reconciliation entirely. The question is asked of the
  **reported tile**, not the sheet (`_tile_has_words`): `render.py` fills
  `full_sheet_text` from `page.get_text()`, so one selectable title block — which
  every real hybrid sheet has — makes the sheet-level answer "yes" and sends
  every quote off the pasted detail back to `NOT_MATCHED_IN_TEXT`, i.e. the
  hybrid recovery never fires on a real page. So the tile is resolved **before**
  classification at both call sites, and an *unknown* tile answers "there was
  text" — absence of a location is not evidence of pixels, and the other default
  would launder every unlocatable bad quote into admission. Those are now admitted at
  reduced trust carrying `Finding.evidence_state` / `ConflictLeg.evidence_state`;
  a quote unmatched on text the sheet *does* have stays a discard, the
  hallucination signal. An absent quote is `TEXT_EVIDENCE_UNAVAILABLE`, never
  implicitly grounded (trigger 3, closed).
  Reduced trust must **reach verification**, so the location travels in three
  parts: the shard-map prompt requests `tile_label` per fact and leg
  (`CrossQCFact.tile`, resolved on that leg's own grid); `fact_tile_lookup`
  rejoins a reconciled leg to its originating fact by `(handle, normalized
  quote)` — the reconcile contract carries no tile, and the model never supplies
  the location, it is *derived* from evidence already committed to. That key is
  **not unique** (one sheet, two "150 gpm" facts, two tiles), and a collision
  loses rather than picks: keeping the first would hand the second occurrence a
  rectangle that still anchors and still passes the region test, laundering a
  guess into a location the reviewer is sent to. Disagreement drops the key
  order-independently; only unanimity resolves. And
  `anchor._anchor_one` falls back to that tile **only** for
  `TEXT_EVIDENCE_UNAVAILABLE`, so TILE anchoring makes
  `verify._has_anchored_legs` and `investigate._candidates` reachable. Every
  other path keeps `quote_not_found`. Reduced trust is visible in the markup and
  the report (a note on the quote cell, not a new status chip — `_STATUS_RANK`
  drives the browser sort and evidence trust is an orthogonal axis), and the
  *reason* is chosen per finding by `models.reduced_trust_reason`, because
  `TEXT_EVIDENCE_UNAVAILABLE` covers two situations a reviewer must not be told
  are one: no text to search (`[NO TEXT TO CHECK]`) and no quote to search *for*
  (`[NO QUOTE TO CHECK]`). Saying "no searchable text on this sheet" to someone
  looking at selectable text discredits every true caveat beside it. A trust
  label belongs to **its own quote**: `evidence_state` rides the atomic grounding
  bundle through a ledger merge, and `annotate._units_for_finding` gives each
  per-leg mark that leg's state rather than the parent's — a conflict can be
  text-grounded on one sheet and read off a raster detail on the other.
  Sheet **handles fold before matching** (P8 item 11): `_norm_id` runs
  `auditors.sheet_ids.fold_text` (NFKC + dash fold), not a bare `.strip().upper()`,
  because a handle written with a non-breaking hyphen, en dash, U+2010 hyphen or
  fullwidth digits missed its plain-ASCII twin — the leg was dropped, and a
  cross-sheet finding needs two grounded sheets, so the finding went with it.
  `critique._leg_targets` folds **identically**, and is asserted equal to
  `_norm_id` rather than merely self-consistent: it feeds
  `critical_signature["leg_targets"]`, so a disagreement has cross-QC resolving a
  leg the ledger then refuses to recognise as the same leg. That fold is host-side
  binding no key input covers, so it carries `_CROSS_QC_CACHE_CONTRACT` **2 → 3**.
  Cross-QC also carries **count-only discard counters** on the sharded path
  (`CrossQCDiscardCounts`, WP-02 §7.2): how many legs/facts the host dropped and
  why — unresolved handle, quote absent, quote present but unmatched, split by
  whether the target sheet had any extractable text at all. Purely
  observational: nothing there feeds `complete` or `budget_degraded`, and it
  holds counts, never quote text. `discards is None` means **not recorded**
  (the whole-set ≤40 path performs no host-side grounding, and a result cached
  before the field existed has none) — never "nothing was discarded". It exists
  because `_finding_from_handles` / `_parse_facts` drop before `CrossQCResult`
  is built, so a run that kept 3 findings and one that kept 3 after dropping 40
  ungrounded legs were previously indistinguishable.
- ***`ledger.py` is the exclusive findings container*** (Part III §16): every
  channel ingests into it with source tags. Dedup is conservative and lossless
  (Phase 20 §12): a tile/rect overlap is never sufficient — merges need semantic
  sameness with **compatible critical signatures** (`critique.signatures_compatible`
  over `critique.critical_signature`: tags, measurements, absence polarity,
  cross-sheet legs — public because the A/B harness's finding-level comparison
  applies the same rule across two runs, and a restated copy is the drift this
  codebase has already paid for once — and a measurement in that signature is its
  **value**, not its spelling: `1/2"` is `0.5in`, not the denominator `2in` it used
  to collapse to, which made *Provide 1/2" drain* and *Provide 2" drain* one
  finding. `12'-6"` keeps both halves and neither goes negative, which needs TWO
  lookbehinds — a single `[A-Za-z0-9.\-]` class blocks the `101` in `M-101`
  (right) *and* the `6` in `12'-6"` (wrong, and unsafe: `12'-6"` and `12'-8"` then
  both sign as `{12ft}`). Plurals fold; `psig` deliberately does not fold into
  `psi`); merging keeps
  **coherent grounding** — the text/quote/tile/rect/evidence-state **and the
  verdict** are one atomic bundle from a single representative, and the loser's
  quote → `supporting_quotes`. `_grounding_quality` ranks **host-computed
  provenance first**, above quote length: a `DETERMINISTIC` verdict is a
  statement about one computation over one quote, so it must not be decided
  separately from the text it describes. It was, and the auditor holds the
  *shorter* quote (it quotes only the term it computed over), so the model's
  "the sum is 560" won the bundle and inherited the host's label — skipping
  `verify._TERMINAL_STATUSES` and inking as "an exact text check, not an AI
  judgment". Both quality tuples are computed **before** the severity union,
  which used to raise the survivor's severity to the max and erase the very
  difference it feeds (one order saw ranks (3, 2), the reverse (3, 3), and the
  tiebreak fell to raw text, where `"…560…"` sorts above `"…540…"`). There is
  deliberately **no** independent verdict adoption and **no** backfill of a
  loser's verdict onto an empty winner. An unanchored winner never erases a rect
  that places its own quote. The merge also unions `sources`, keeps most-severe
  severity, and — when the merged provenance spans two families — raises
  `reproduced` **and** `confidence` together (`critique.merge_finding_groups`'s
  rule; the ledger implemented only half of it, so entries read
  `reproduced=True` beside `confidence=SINGLETON`). Explicit lifecycle:
  `seal()` (OPEN→SEALED) → anchor → `reconcile_post_anchor` (Pass B) →
  `number()` (SEALED→NUMBERED assigns positional `QC-###` **after** anchoring).
  Pass B's complete-link history comes from `Ledger.member_history`, never a
  fresh `{id(e): [e]}` map — the live survivor may no longer carry the signature
  of what it absorbed, and rebuilding from it let Pass B undo a fold Pass A had
  refused, destroying a conflicting measurement that lived in `text` rather than
  the quote. Those snapshots are taken **when a merge is about to mutate an
  entry**, not eagerly at ingest: anchors are resolved after ingest, so an eager
  copy is a permanently *unanchored* twin of a live entry and `_is_duplicate`'s
  geometry branch could never fire against it. A post-seal add marks the run
  incomplete (no `QC-XTRA` masquerade) — including a post-seal **duplicate**,
  which used to reach neither the counter nor the log because the merge branch
  returned first, and which is counted and **dropped** rather than merged: it
  would otherwise rewrite text, quote, id, severity and anchor underneath an
  already-exported `QC-###`.
  Anchoring, verification, the citation check, the markup writer, the exports,
  and the report consume ledger entries and nothing else.
- *Edition audit (Phase B):* `citation_check.reconcile_cited_editions` — a
  zero-API, **strictly pre-seal** check turning an adopted-vs-cited edition
  divergence into a first-class ledger finding (gated `run_citation or
  run_auditors`; stage `edition_audit`). Basis = identity `adopted_codes`
  (model entries need a quote; regex-union entries are ignored here) ∪ a
  citation-shape-filtered regex harvest (`_basis_edition_claims` — a mention
  followed by a section marker is a citation, never an adoption). Two-tier
  trust mirroring §17.5: both operands re-found in sheet text → medium +
  `DETERMINISTIC`; else low + advisory-labeled, crop-verified downstream. The
  finding anchors to the stale-edition text's own matched span (never the
  citing finding's quote — an identical quote would collide in Pass B).
**Text normalization (P8 N7/N8).** `anchor._normalize` rewrites **vulgar
fractions before NFKC** (`_VULGAR_FRACTION_TABLE`): NFKC expands `½` to `1⁄2`
with no separating space, so `2½"` became `21⁄2"` and could never match a sheet
reading `2-1/2"` — a 2.5 inch drain quoted as a 21 inch one. `_CHAR_FOLD` also
covers the fraction slash, division slash and multiplication sign. Every
invisible code point in `anchor.py` and `auditors/sheet_ids.py` is written as a
`\uXXXX` **escape**, never a literal: as literals they are invisible in every
editor and diff, and a test fails if one reappears.

- *Disposition:* `anchor.py` (quote → PDF rect, tiered
  EXACT/FUZZY/TILE/UNANCHORED — UNANCHORED is the hallucination signal. Both fuzzy
  tiers carry the **numeric veto** (P7 item 30): token overlap is blind to a
  swapped digit, so on `PROVIDE 6 INCH DRAIN AT COLUMN LINE 4` every one-number
  substitution scored 6/7 = 0.857, cleared the 0.85 floor, and clouded a wrong
  pipe size onto the sheet's real text. `_numbers_aligned` requires each
  digit-bearing token to sit at **its own position** in the matched span, within
  `_fuzzy_window_slack` — derived from the overlap floor, never a constant, so the
  two cannot disagree — and consumes each span position once, so `4 4-INCH DRAINS`
  cannot satisfy both mentions from a single `4`. Presence anywhere in the span is
  not evidence: multiset agreement alone is defeated by the window *sliding* to
  borrow a digit from the next line. The sub-phrase tier instead uses
  `_numbers_agree`, because its span is the slice verbatim and its failure mode is
  *dropping* a measurement, not mismatching one. The 0.85 threshold is a standing
  prohibition and is asserted unchanged) →
  `verify.py` (high-DPI crop re-check → VERIFIED/REJECTED/UNCERTAIN; adaptive
  thinking at medium effort inside an 8k envelope — thinking shares the
  `max_tokens` budget with the answer, and the old 1k cap fit neither, so
  verdicts came back empty and degraded to UNCERTAIN. A verdict **replaces** the
  status, never the arithmetic provenance behind it: all 18 `Verification(...)`
  constructions assign wholesale and populate neither `computation_method` nor
  `operand_origin`, so `_provenance_restorer` snapshots them at each public
  entry point and restores them at every exit — success, skip, error, abort and
  warm-cache alike. Restoring at the boundary rather than at the ten assignment
  sites is deliberate: patching those leaves the next branch someone adds to
  reintroduce it silently. Losing them *inverted* the reviewer's caveat, since
  `annotate._trust_note` reads `operand_origin` first — "re-check the math
  against the sheet" became "AI-verified against the drawing" — and the exposure
  is precisely targeted, because `auditors/arithmetic` emits UNCERTAIN for
  `MODEL_TRANSCRIBED` operands while only DETERMINISTIC is terminal here.
  `investigate.py` carries both fields forward at its own three sites) →
  `investigate.py` (Phase C: a host-driven client-tool loop escalating each
  anchored UNCERTAIN verdict — the model requests evidence via `crop_region`
  / zero-API `find_text` / `view_sheet`, every image saved-before-send into
  the finding's evidence dir with an `investigation.json` trace; strictly
  sequential (I-5), budget-capped per finding (`…_INVESTIGATION_MAX_ROUNDS`,
  default 6, spent per **evidence request** and enforced *before* execution —
  one turn may carry several `tool_use` blocks and each is a real crop
  rendered, saved and sent; charging the turn let a 6-request budget buy 18+,
  and merely counting them after the fact still paid for the crops. Blocks past
  the remaining budget are refused unexecuted, answered in the same user turn
  as an `is_error` result, and cost nothing so they do not advance the counter) and per run (`…_MAX_FINDINGS`, severity-first, **scaled to the set**
  — 10 + one per 4 sheets, ceiling 40, an explicit env value pinning it) with the
  assistant turn committed before its tools are answered, every tool_use id
  answered in ONE user turn, and a forced no-tools text close at the cap so a
  run never dangles; a capped/garbled outcome stays UNCERTAIN — never
  REJECTED — and is a designed stage COMPLETE; it only ever UPDATES
  `finding.verification` in place (legal post-seal); concluded verdicts cache
  in `stage=investigation` keyed on finding identity + a whole-set content
  fingerprint + model/prompt/round-budget/task-budget, complete-only admission,
  and a warm hit
  deterministically REPLAYS the tool trace with sha-compare so evidence bytes
  are recreated and warm output stays byte-identical, no TTL) →
  `citation_check.py` (**Sonnet 5**: server-side `web_search` + `web_fetch` per
  unique code ref — web fetch is unavailable on Opus 5, so an Opus citation
  check can only read search snippets rather than the section text; both tools
  carry the shared source-quality blocklist, and the resolved tool set rides
  the verdict cache key because what the model was allowed to do is part of
  what its answer means. Its tool schemas carry a cache breakpoint, so after the
  first request most of the input is billed as a cache **read** while
  `input_tokens` reports only the remainder: the prompt-cache split rides
  `_CheckOutcome` → `CitationCheckResult` → the ledger, summed across
  `pause_turn` resumes and carried on the error and still-paused exits too, since
  those attempts were billed. `digest._message_cache_usage` is the shared,
  dict-tolerant reader — attribute-only `extract_cache_usage` silently zeroes a
  dict-shaped usage, which undercounts rather than failing) →
  `annotate.py` (§18 gating + Phase 21 receipts: every entry gets ink except
  REJECTED/gated, which get reconciled index rows; rect-less entries become
  margin callouts **packed into visually-clear bands** — validated against words,
  a rendered occupancy mask, and siblings so they never obscure the drawing
  (Phase 25 §17.6); one that will not fit overflows to an appended *AI Review
  Notes* page with a GOTO link back, rerouted to a `REVIEW_NOTES` placement; the
  writer stamps every mark, reopens the saved PDF, and reconciles
  each **placement** against what it finds. A **GOTO destination is default user
  space** (PDF §12.3.2.2), a third space beyond the two §19 names, so
  `_dest_user_point` converts and `_dest_point` / `_outline_dest_point` invert
  whichever transform the entry point applies — `insert_link` maps `to` through
  `~page.transformation_matrix`, `set_toc` flips y about `cropbox.height` then
  applies `rotation_matrix`, and they are **not** interchangeable. `_derotate_point`
  is annotation space and is wrong for a destination (P7 item 27: 12 of 24 cases
  wrong via `insert_link`, 22 via `set_toc`). Every generated page comes from
  `_new_generated_page`, which pins `CropBox` to `MediaBox` because `/CropBox` is
  **inheritable** and a set carrying one on `/Pages` rendered a 612×792 index page
  as 512×712. The index is built **last**, after the notes page, so a row links to
  the page its mark actually landed on rather than guessing its source sheet; every
  page written before it shifts by the same `n_index`. `_placement_kind` returns
  `NO_QUOTE` for a quote-less finding — `[QUOTE NOT FOUND]` is the hallucination
  signal and must not be spent on a graphics-only finding that never had a quote.
  `_clear_bands` gates the **padded** band (a 58 pt gap once returned a 50 pt band
  the packer could never use) and is **column-aware**: a full-width word-free
  y-range is nearly unobtainable beside a title block, so per-column bands are
  computed from only the words intersecting that column — which preserves the
  word-free guarantee `_pack_callouts` relies on to skip its word scan.
  `_page_occupancy` samples at **1:1** with a **min-filter over point-sized cells**,
  because at a coarse scale a 0.5 pt pipe line antialiases *lighter* than the ink
  threshold and a pixel-fraction verdict is non-monotonic in scale; `_fit_text` /
  `_base14_safe` fit page text by measured width and fold glyphs Base-14 cannot
  draw, which it otherwise renders as a middle dot — returning a `MarkupRunResult` with
  per-placement `WRITTEN`/`INDEXED`/`FAILED` receipts and a receipt-derived
  `coverage_status`. Every finding annotation (cloud, tag, callout, leader,
  overflow/set-level note) is also placed on a per-**severity** PDF
  optional-content layer (`QC markups - High/Medium/Low severity`, all shipped on)
  so a reviewer can toggle a whole severity tier; layered strictly by `severity`
  (question rides its own tier), created only for tiers with ink in fixed
  high→medium→low order (I-7), additive/non-fatal (I-3), and the `/OC` reference
  is independent of the DA-007 placement stamp so reconciliation is untouched) →
  `export.py` (`markup_manifest.json`) / `html_report.py`. The opt-in
  `save_tile_artifacts` option (GUI "Save tile images + per-tile notes",
  `DRAWING_ANALYZER_SAVE_TILES`) stages every rendered tile PNG at render time
  (`tile_artifacts.py`) and exports a `tiles/` folder with mirrored per-tile
  notes; it bypasses the level-1 render skip so tiles exist on warm runs, while
  the level-2 (PNG-keyed) cache still serves the digests with zero API calls.

**HTML report (`html_report.py`).** `_finding_display_status` folds anchor +
verification into one chip, and keeps `UNCERTAIN` ("a verifier looked and could
not settle") distinct from `UNVERIFIED` / *Not checked* ("no verification stage
ran") — the state of every finding on a standard run; collapsing them once
labelled all 287 findings of a clean 39-sheet run "Uncertain". `_STATUS_RANK`
must stay **integer-valued** (the browser sorts it through `parseInt`).
Findings quoting the same verbatim text carry a `data-repeat-key`
(`_repeat_key`: sha256 of the case/whitespace-normalized quote, so it is stable
per I-7 and never puts quote text in an attribute) and collapse behind the first
row in the browser — **display only**: the ledger, exports, markups and the badge
total keep every finding (§18.6), and the grouping recomputes after every
sort/filter so a follower never outlives its lead. Journal timestamps render
through `_local_stamp` in the same clock as the report header (the raw UTC value
beside a local header read as a report predating its own run). The chat widget's **turn loop** owns four rules a DOM emulator cannot check
(P6): every commit into `history` is generation-guarded (`gen !== turnGen`)
**inside `step`**, not only on the outer catch/then — New chat and Load
*reassign* `history`, so an in-flight turn otherwise writes its assistant turn
into the next conversation, which the API rejects, `dropUnansweredTail` cannot
heal (it trims only a **trailing** unanswered exchange) and `saveTranscript`
persists. Stop is a **turn** latch (`stopRequested`), not the per-request
`AbortController` that `streamOnce` rebuilds on every call, and it is checked
both before the tools run and after they finish. A `tool_use` block nothing
will answer is stripped before commit (`stripDanglingToolUse`) — dropped, never
answered with a synthetic result, because the call never ran. And a turn's note
is DOM-only unless that turn owns the last `displays` entry, since the catch's
pops run first. `activeStream` is released **by identity**, so a stream
settling after its thread was replaced cannot clear the new turn's handle.
The request shape is resolved host-side from the capability registry —
`thinking`, `webSearch` and `webFetch` all ride `CFG` and the browser omits
what the model will not take, because `DRAWING_ANALYZER_CHAT_MODEL` is
overridable and an unsupported `thinking` or web-search *variant* is a 400 that
kills every question. In the chat
widget a **reader-supplied key outranks the embedded one** — the key row renders
in both modes, since hiding it billed every shared report's questions to its
author and left a rotated-key report dead.

`core/` is a shared kernel (model ids + env overrides in `api_config.py`, key
store, pricing, tokenizer). `reference_audit.py` is a back-compat shim over
`auditors/references.py`. **No built-in review profiles ship** (Phase A): the
packaged `profiles/` dir is empty by design — the model authors the plan per
set; user checklists live in `~/.drawing_analyzer/profiles/` and a worked
example is parked at `docs/examples/fire_protection.md`.

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
  what is stored or sent changes. A hash only covers what it is given: the
  user-turn framing (sheet introduction, omitted-tile disclosure, overview and
  per-tile labels) once sat outside both, so editing it changed the request
  while every key stayed identical. Those strings now live in
  `digest.SHARED_USER_FRAMING_STRINGS`, which **both** hashes splat — the
  critique reuses the same builder, so a string covered by only one hash
  re-keys that cache while silently replaying the other. Add a model-visible
  string to the shared builder and it is covered automatically; add one
  elsewhere and it is your job to hash it.
- **I-7 — deterministic assembly:** same inputs → same ordering (QC numbering,
  index rows, merged output); no randomness or time-dependence in assembly.
  One documented carve-out (Phase B): the citation verdict cache's TTL clock
  (`DRAWING_ANALYZER_CITATION_TTL_DAYS`, injectable `now=`) governs cache
  admission/refresh only — whether an API call is made — never numbering,
  ordering, or merged output; a warm run's assembled output is byte-identical
  to the run that populated the cache.
- **The model never calculates:** models transcribe `NumericClaim`s;
  `auditors/arithmetic.py` does the math with `Decimal` — never `eval`, never
  the model's own arithmetic. The host *operation* is always deterministic, but the
  *operands* are trusted (`DETERMINISTIC` + auto deterministic-only ink) only when
  the claim's quote independently carries every one (`operand_origin=TEXT_EXTRACTED`,
  Phase 25 §17.5); a mismatch from `MODEL_TRANSCRIBED` terms stays `UNCERTAIN` and
  is crop-verified before it inks as ground truth. A term that is not **one** value
  is refused rather than truncated to its leading run (`12,5`, `12'-6"`, `1.2.3`),
  and a `%` is refused outright: a percent is a ratio, and because the bare `30` in
  `1500 SF + 30% = 1950 SF` appears literally in the quote it *cleared* the
  TEXT_EXTRACTED gate and inked "the product of 1500, 30 is 45000" as host-computed.
  `_head_denies` / `_tail_denies` are applied at the **quote-scan** site, not inside
  `parse_number`, because only the scanner can see what bound a number — that is
  what keeps the two from disagreeing. A binder must be **tight** — no whitespace
  on either side: `20 20 20 TOTAL 540` is four numbers and `0.5, 1.5, TOTAL 2.0`
  is an operand list, while `12,5` and `10,20` stay rejected. A loose binder cost
  no wrong answers but downgraded such a list to MODEL_TRANSCRIBED and paid for a
  crop check to re-learn what the quote already said. `_fmt` expands an integral with `format(v, "f")`, never
  `quantize`, which raises above the decimal context's 28 digits from ordinary
  string terms — inside the `Finding(...)` expression, *after* `mismatched` was
  incremented. Each claim now has its own `try` with a tally rollback: the
  orchestrator's single batch-wide `try` meant one bad claim lost every arithmetic
  finding **and** all four `arithmetic_*` stat keys, after which the summary line
  read `arith=0/0` — indistinguishable from a set with no claims.
- **Tiles use the `tile_label` contract (Phase 25 §17.1):** the model returns the
  exact visible label (`"r1c1"`); `tiling.parse_tile_label` converts it to the
  canonical **zero-based** internal `[row, col]`. A legacy `tile` array is accepted
  only as explicit zero-based, bounds-checked — never guessed to be 1-based.
- **Thinking is always explicit; never omitted (§C).** On Opus 5 and Sonnet 5 an
  *omitted* `thinking` key runs adaptive thinking — it does not disable it — and
  thinking draws from the same `max_tokens` envelope as the answer. Three stages
  once relied on omission meaning "off" and starved their own output. Every
  request builder therefore states `thinking` and `effort` explicitly, resolved
  through the `core.api_config` phase registry (which also applies the
  model-ceiling clamp). A phase that wants shallow work registers `EFFORT_LOW`;
  it does **not** send `{"type": "disabled"}`, which risks leaking reasoning tags
  into a response the host parses as JSON.
- **Above ~21k `max_tokens`, streaming is mandatory, not preferred.** The SDK
  refuses a non-streaming `create` whose cap implies >10 minutes of output with a
  client-side `ValueError`, before any HTTP request. `digest.stream_message` is
  the single place that knows this; digest / critique / review-plan / synthesis /
  focus all go through it. Batch items never stream and are unaffected. A cap
  raise without the matching streaming conversion is a hard failure, including
  via the batch→real-time fallbacks in `batch_digest`/`batch_critique`.
- **Every real-time call whose model declares it opts into the server-side
  refusal fallback.** Which models is
  `ModelCapabilities.supports_refusal_fallback`, a registry capability beside
  each model's other request-shape decisions — never a test against one model
  id. The gate read `model != MODEL_OPUS_5`, so any other id (a newer Opus, a
  changed default) silently lost the protection with nothing raised and nothing
  logged. Opus 5 is today's only declarer; Opus 4.8 is the fallback *target*,
  not a source.
  Opus 5's elevated safety classifiers can decline a request outright
  (`stop_reason="refusal"`, HTTP 200); `core.api_config.call_with_refusal_fallback`
  attaches `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) for
  every Opus-5-routed real-time call — `digest.stream_message` (digest, critique,
  the batch direct-call rescue), `verify.py`'s crop re-check calls, and the
  investigation loop — and re-routes through `client.beta.messages`. (These are
  not "escalation" calls: `verify.py` resolves one model,
  `VERIFICATION_MODEL_DEFAULT`, and never escalates. The wrapper is applied
  because a verification call *can* be Opus-routed via
  `DRAWING_ANALYZER_VERIFICATION_MODEL`, not because a second tier exists.
  `VERIFICATION_ESCALATION_MODEL` belongs to `investigate.py`, WP-07 §12.13.) The
  parameter is rejected on the Batches API, so this never touches the bulk
  batch-submitted review traffic. Opus 4.8, the documented cyber-refusal
  fallback target, is registered in `_MODEL_CAPABILITIES` with identical
  effort/thinking/output-cap/hi-res-vision support and identical $5/$25
  pricing to Opus 5, so a fallback changes nothing about request shape or
  billing. Self-healing, mirroring investigation's own `_task_budget_available`
  latch: a 400 naming the fallback beta/parameter turns the feature off for the
  rest of the process (`_refusal_fallback_available`) rather than permanently
  breaking every subsequent Opus 5 call on a platform that doesn't support it.
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
- **A GOTO destination is a THIRD space (P7 item 27).** `/XYZ` is default user
  space; `add_*_annot()` and `insert_text()` take the un-rotated CropBox-relative
  space. Worse, the two writers disagree with each other: `Page.insert_link` maps
  `to` through `~page.transformation_matrix`, while `Document.set_toc` does
  `y = cropbox.height - y` then `* page.rotation_matrix`. Never share one helper
  between them. Ground truth is an annotation's raw `/Rect`, which the spec puts in
  the same space as `/XYZ`.
- **`page.cropbox` is top-left; `page.mediabox` is the RAW box.** `page.cropbox`
  is reported in PyMuPDF's top-left convention (a `set_cropbox([50,30,562,700])`
  stores `/CropBox [50 92 562 762]`), while `page.mediabox` comes back
  un-normalized in PDF bottom-left. `mediabox.y1 - cropbox.y0` is the CropBox's top
  edge in user space. This asymmetry has produced several confidently wrong probes.
- **`/CropBox` is inheritable; `/Rotate` is written explicitly.** A `new_page()` in
  a document whose `/Pages` node carries a `/CropBox` **inherits** it — a 612×792
  page came back with a 512×712 visible rect — so pin it. A new page does not
  inherit `/Rotate`, verified rather than assumed.
- **`get_text()` includes annotation text.** Use
  `pymupdf.TextPage(page.get_displaylist(annots=False).get_textpage())`; the raw
  `FzStextPage` has no `extractText` and `page.get_text(textpage=…)` rejects even
  the wrapper, so words come from `TextPage.extractWORDS()`. Those words are in
  **rotated view** space, unlike `get_text("words")`, which is rotation-invariant.
- **A thin line can be invisible in a downscaled pixmap.** At 0.12 a 0.5 pt line
  antialiases to ~223, above a 210 "dark" threshold, and whether it registers at
  all depends on pixel-grid alignment — so a pixel-fraction occupancy test is
  non-monotonic in scale. Sample at 1:1 and min-filter.
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
