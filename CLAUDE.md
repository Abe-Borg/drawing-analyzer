# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Remediation program (active)

A multi-session remediation program is under way. Its files are in `_plans/`:
- the plan: `drawing-analyzer-remediation-plan.md`;
- the tracker: `PROGRESS.md`;
- the session protocol: `README.md`;
- the contract decisions: `DECISIONS.md`.

**If your session works on it** (the user asks you to continue the plan, or names
a slice such as `WP-04.1`), start with `_plans/README.md` and follow its protocol:
- **Before starting:** check the open PRs for slices already in flight.
- **In the same PR:** mark your slice in `PROGRESS.md` and add a handoff entry.
  That is how the next session knows where to continue.
- **Never** tag, publish or approve a release, and never record a manual waiver.

Two naming collisions to keep straight:
- The `WP-00`…`WP-08`, `WP-03A/B`, "WP-02 §7.1" and "WP-05 §10.1" references in
  this file and in `docs/` belong to an earlier, completed plan.
- `R-01`…`R-06` are the measurement packages in `docs/MEASUREMENT_PACKAGES.md`,
  whose §2 standing prohibitions still bind all work.

Remediation slices are always written `WP-nn.m`.

**Known-inaccurate statements in this file** (verified 2026-09-22 against 1.7.0).
The slice named in parentheses corrects the text and removes the entry here:
- HTML report: grouping "recomputes after every sort/filter". It does not after a
  sort (H1; WP-21.2).
- Digest truncation: the raised-cap retry "can only improve on that read, never
  lose it". A retry that lands empty or refused discards the first read (N16;
  WP-01.3).
- Geometry-aware image tokens: the GUI prices from real page shapes once the
  profile preflight has run. In a default install the preflight never runs,
  because no profiles ship (N23; WP-15.1).

## Commands

```bash
pip install -e ".[dev]"      # engine + pytest   (GUI too: pip install -e ".[gui,dev]")
pip install cffi             # cloud container only: its system `cryptography` lacks _cffi_backend (3 spurious test_spec_documents panics)
python -m pytest -m "not network"   # full suite — hermetic, and the guard enforces it. Still pass the -m: CI and every gate do
python -m pytest tests/test_drawing_ledger.py                # one file
python -m pytest tests/test_drawing_ledger.py::test_name     # one test
drawing-analyzer             # launch the GUI   (or: python -m drawing_analyzer)
python scripts/run_acceptance.py   # Phase 27 release gates (PASS/FAIL; hermetic — never the canary)
python scripts/check_browser_suite.py browser-results.xml   # P9 item 42: a skip is not a pass
python scripts/check_release_acceptance.py --tag v1.8.0     # N8 publish gate dry run: reads docs/releases/ACCEPTANCE-1.8.0.md
python scripts/measure_evidence_coverage.py --pdf SET.pdf   # WP-02 §7.1 coverage scan (zero API calls)
```

Python 3.11+. No linter/formatter is configured (CI runs ruff **correctness
classes only** — E9/F63/F7/F82). The `network` pytest marker is reserved for
tests that need real API access (the Phase 27 live canary,
`tests/test_live_api_canary.py`); everything that runs by default uses the
fakes in `tests/fixtures/fake_anthropic.py`. A `network` test runs only when
`-m` selects it explicitly and a real key is set (the guard below), but
`pyproject.toml` sets no default exclusion and no gate may rest on one layer, so
**any entry point that spawns pytest must still deselect the marker itself**:
`run_acceptance.py` routes every gate through `_pytest_cmd()`, which ANDs
`not network` into the child's `-m`, `tests/test_run_acceptance.py` fails if
a bare `"pytest"` argv literal reappears anywhere else in that script, and
`tests/test_hermetic_guard.py` fails if a workflow's pytest command drops
`not network`. The §19.1 trust-gauntlet oracle
set + all-stage scripted client live in `tests/fixtures/gauntlet.py`; release
docs (Windows/viewer/Excel manual scripts, benchmark record, §19.9 checklist)
live in `docs/`; `requirements-release.lock` pins release builds.

**The hermetic guard (WP-02.1, `tests/fixtures/hermetic_guard.py`).** I-4 is
enforced, not requested. `tests/conftest.py` registers the plugin; it goes up at
`pytest_configure` and comes down only inside an opted-in `network` test's own
runtest protocol, so collection and fixtures of **every** scope are covered —
the gauntlet's module-scoped `oracle` runs the whole exhaustive pipeline before
any function-scoped fixture exists, and the old per-test key strip never
covered it. Sockets are guarded where they **connect** (`connect`/`connect_ex`
and the forward lookups), never where they are created: asyncio's self-pipe is
a socket pair (loopback TCP on Windows) and Playwright's sync API runs on
asyncio. Loopback, the unspecified addresses and `AF_UNIX` pass. A refusal
raises `ExternalNetworkBlocked` (a `RuntimeError`, so an `except OSError` cannot
mistake it for a transient failure) **and is recorded**, and the record turns the
test's teardown into an error naming the destination: the QC stages swallow
their own exceptions by design (I-3), so a raise alone let a pipeline test that
reached for the API stay green. An attempt no test owns (at import) fails the
session. Ambient configuration goes too: every `*_proxy` variable, because the
socket rule allows loopback and, measured, the SDK sent `CONNECT
api.anthropic.com:443` to an exported loopback `HTTPS_PROXY`; `NO_PROXY=*` also
stops `urllib.request.getproxies` falling back to the Windows registry, which no
env scrub reaches. And every `ANTHROPIC_*` variable — a prefix, not a list,
because a zero-arg `Anthropic()` resolves an auth token, a named profile,
workload-identity federation and custom headers, and the SDK adds sources under
that prefix — with `ANTHROPIC_CONFIG_DIR` then pointed at an empty directory:
an explicit config dir makes profile failures propagate, so a zero-arg client
raises `CredentialsError` instead of finding an `ant auth login` profile. The
key keeps its old contract (a placeholder during collection — now even over an
exported real key — and none inside a hermetic test). The opt-in rule
(`network_selected_explicitly`) runs a `network` test only when the `-m`
expression selects it *because of* that marker, evaluated with pytest's own
(private) marker-expression engine so the two cannot disagree; if a pytest
upgrade moves it the rule answers False — skip, never run — and its test fails.
The opted-in test then gets the caller's own environment and real sockets back
for exactly its own protocol. No fixture crosses that boundary: pytest caches a
module- or session-scoped fixture for every later test, so where an opted-in
test and a hermetic one are neighbours the guard tears the whole fixture stack
down between them (`teardown_exact(None)` in a `tryfirst` `pytest_runtest_teardown`).
Otherwise a credential-bearing client made on the network side reached hermetic
tests, and its finalizer — a canary's remote cleanup — ran under the guard and
was refused. Child processes inherit the scrubbed environment, not the socket
patch.

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
**Item coverage** (`models.item_coverage_status`, `_plans/DECISIONS.md` D-2)
decides a stage from what it was required to judge, after the failure flags:
nothing eligible is `SKIPPED_VALID`, everything judged `COMPLETE`, nothing
judged `FAILED` (the all-failed rule), anything between `PARTIAL`. Verification
is the first stage on it (remediation WP-01.1, N5). A later stage that
recovers an item reports it on its own record and never rewrites the earlier
one, and the roll-up does not recognise recovery.

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

**Work-dir hygiene (P9 item 46).** The verify, investigate and markup stages each
create a `drawing_qc_*` temp directory when the caller supplied no `work_dir`, and
nothing removed them — they hold the high-DPI evidence crops, so a repeatedly
reviewed set leaks the largest artifact the tool produces into `%TEMP%`.
`pipeline._prune_stale_work_dirs(keep=…)` reaps them on the way **in**
(`DRAWING_ANALYZER_WORKDIR_MAX_AGE_HOURS`, default 24, `0` disables, resolved at
call time). Pruning at run *end* is not an option: `extract_drawing_context`
returns before the caller exports and the export *copies* evidence out (DA-033),
so it would destroy the crops before anything saved them. Age is judged by
`_tree_is_recent`, not the directory's own mtime: a directory's mtime moves only
when an entry is added directly in it, and crops land in
`evidence/<QC-###>/<leg>.png` — measured, a work dir whose crop was written **0
seconds ago** but whose own mtime was 40 hours old was pruned out from under a
live run, and a run can outlive the prune age (the batch bound alone is 24h). Both
checks are needed: an empty young dir has nothing inside to date. Every
uncertainty fails **safe** (keep, never delete) — an unreadable entry, an
unscannable directory, an exhausted scan budget — because keeping a stale
directory costs disk and deleting a live one costs a paid run's evidence. The
zero-sheet early return cleans up the dir it created, in the byte-identical form
its `block_reason` twin uses.

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
`private_roots` is matched **case-insensitively, across both separators, and only
to a component boundary** (`_private_root_re`, cached per root): Windows paths are case-insensitive with two
legal separators, so a literal `str.replace` matched only the registered spelling
and one lowercase drive letter left `Abe Borg\My Drawings` in the file — the
regex path scrubber cannot bound a path containing spaces. The boundary
(`(?=[\\/]|$)`) is what stops a root matching a *sibling* whose name merely
starts with it: `…\Job` matched `…\Job2\Client Secret\…` and the partial
rewrite was worse than none, since eating the drive letter left the backstop
nothing to anchor on. And **every** renderer
of both artifacts is handed that list, not just the errors section (it was only
the errors section, so one string was scrubbed two sections below where it printed
in full); `test_run_journal.py` asserts that structurally over the module's AST,
because an assertion about today's call sites cannot see tomorrow's.
`redact_for_display` is the same boundary minus flattening and truncation, for
artifacts that render a block rather than a line: the exported Markdown
(`00_index.md`, per-sheet files) and `report.html` printed host error strings
verbatim — measured, an `AuthenticationError` repr put both the user's directory
names and an `x-api-key` value into all three while run.log beside them was
clean. Host status/error text only: digest prose (I-2) and model findings are
never routed through it, because `TOKEN: 12` on a sheet is drawing content.

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
findings for free — but never a read the model did not **finish**, remediation
WP-01.2 / D-1). Whether a read finished is decided from `stop_reason` alone,
before the text is looked at, by the shared
`core.terminal_outcome.classify_stop_reason`: only `end_turn` / `stop_sequence`
are finished; `max_tokens` and `model_context_window_exceeded` are truncations;
`refusal` is refused even when it carries explanatory text; `None` is unfinished
(N27: for a stream that ends without `message_stop`, the real SDK's
`get_final_message()` returns the partial text with `stop_reason=None` and
raises nothing); `tool_use` / `pause_turn` / the beta `compaction` are
continuations the digest never takes; anything else is unknown, never finished.
The table is pinned by test to the installed SDK's `StopReason` ∪
`BetaStopReason`, since Opus 5 calls travel the beta namespace for the refusal
fallback, so an SDK upgrade that adds a reason fails until it is classified.
Both transports (and the batch direct-call rescue, and the Files-API inline
fallback) share **one ladder**, `digest.digest_terminal_error` (a refusal is
named even when empty; the text stays on the sheet for the export), **one write
predicate**, `digest.digest_cache_admits` (both level-2 writers and the
pipeline's level-1 store-under-both), and **one loader**,
`digest.sheet_digest_from_cache_entry`, which returns `None` (a miss) unless the
stored `stop_reason` is finished. A stored `null` (the N27 shape; every writer
has stored the key since the first commit) and a missing key are both misses,
read again and overwritten, never deleted, with no `_SCHEMA_VERSION` bump (D-4).
Only `max_tokens` earns the raised-cap retry (`raised_cap_may_finish`; a larger
cap cannot make room in a full context window): retried once from the shared
`digest.MAX_TOKENS_RETRY_CEILING`, and refused by the cache if still cut off,
since a stored truncation is indistinguishable from a complete one on every
later run. Real-time accumulates usage across both attempts — each was billed —
and falls back to the truncated first read if the raised-cap call cannot land, so
the retry can only improve on that read, never lose it. The critique does **not** re-rasterize what the digest
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

**CI gates (P9 item 42).** `pytest -m browser` writes a JUnit report and
`scripts/check_browser_suite.py` fails the job below a floor of genuinely
*executed* tests. Every test in that suite skips itself when Chromium will not
launch and pytest exits **0** on an all-skipped run: measured on one commit, one
environment variable apart, `98 passed` and `98 skipped, 2180 deselected`, both
exit 0 — a green required check over a suite that proved nothing about CSP,
`file://` handling or event execution. Failures count as executed (the body ran);
skips and setup errors do not. The same floor is applied inside
`run_acceptance.py`'s own browser gate, through the same script — the release
gate and the CI job must not disagree about what "passed" means.
`release.yml`'s `publish` needs three tag-gated jobs in its own `needs` chain
(`needs: [build, gates, gates-windows, acceptance]`, pinned in two tests):
- `gates`: the full `run_acceptance.py` with Chromium installed, plus ruff,
  licenses and pip-audit.
- `gates-windows`: the hermetic suite on Windows.
- `acceptance` (remediation WP-23.1, N8): v1.7.0 was published as the stable
  `latest` release about eight minutes after its record merged saying HOLD,
  and a green suite is not acceptance.

Branch protection does not apply to a tag push, a tag can name any commit, and a
second workflow run triggered by that tag is **not** a dependency of this one.
`ci.yml` triggers on `v*` tags for visibility only.

`acceptance` runs `scripts/check_release_acceptance.py`, which decides the
channel **once**:
- an `rcN` tag is `prerelease` and needs no record;
- a stable tag needs `docs/releases/ACCEPTANCE-<ver>.md` titled for that
  version, whose Sign-off has exactly one `Release decision:` line with first
  word `SHIP` and no `HOLD`. `SHIPPED`, `Ship` and the template's unfilled
  `SHIP / HOLD` all refuse;
- every waiver row must be complete, with an unexpired ISO `Expiry` (valid
  through that UTC day). Waivers never lift a HOLD;
- anything unreadable refuses, and a tag outside the updater's `_VERSION_RE`
  grammar publishes nothing.

The script is stdlib-only (the job installs nothing) and keeps a copy of
`updates._VERSION_RE` that a test pins equal. It runs on **every** tag, because
a skipped job in `needs` skips `publish`, so the RC bypass lives in the script
and not in an `if:`. `publish` runs no repo code: it reads the job's `channel`
and `valid_through` outputs (no `*rc*` glob) and deploys to
`environment: release`. It uploads into a **draft** (`gh release create --draft`,
never a channel flag) and makes it public in one final
`gh release edit --draft=false <channel flag>`. The earliest waiver expiry is
checked before the upload and again after it, because an environment approval
can come days later and plain `gh release create` publishes at the end of its
own upload, which left the whole upload between check and use (Codex review).
A re-run finds the earlier attempt through `gh release view --json isDraft`: it
finishes a draft, and only replaces a published release's assets, so re-running
an old tag cannot take `latest` back from a newer release. Two limits hold:
- a tag runs the workflow from the tagged commit, so all of this stops
  accidents only;
- an unconfigured environment is auto-created **unprotected**, so the
  independent boundary is the admin-configured protection, confirmed through
  the API (`_plans/PROGRESS.md` O-5).

The record is read from the tagged commit and is never asked to name its own
commit (plan WP-23 step 10). Binding it to the tested commit and the artifact
hashes is WP-23.6.

**GUI lifecycle (P9 items 47/N32).** `gui.py` is a console-less entry point
(`[project.gui-scripts]` on Windows, and the frozen build is windowed), so
anything written to stdout/stderr is invisible: the `customtkinter` import is
guarded and reports through a stdlib `messagebox` naming the fix, raising
**ImportError** and not `SystemExit` (`app_entry.py`'s `--selfcheck` catches
`Exception`, and `SystemExit` would sail past it and report success). The main
window wires `WM_DELETE_WINDOW` → `_on_close_request` (the workers are daemons and
the export runs *after* the analysis returns, so closing mid-run discarded a paid
run with no prompt, while all three secondary windows already confirmed) and
`report_callback_exception` → `_on_callback_exception` (Tk's default handler
prints to the stderr that does not exist). Both reporters swallow every failure of
their own channels: a broken dialog must not trap the user in the window, and the
reporter of last resort must never raise from inside Tk's handler.

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
  from `DRAWING_ANALYZER_USE_BATCH` when the caller leaves it `None`.
  **Structured outputs, opt-in (F-01):** the critique is the ONLY high-volume
  call whose reply is JSON and nothing else, so it is the only stage
  `output_config.format` fits — the digest writes prose *then* a findings block
  and no schema describes that (F-02 would need a `record_findings` tool; not
  done, and its cost is a `_SCHEMA_VERSION` bump on the highest-traffic call).
  `DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS=1` + the registry capability +
  the per-stage latch all gate it — the three are one shared
  `core.structured_outputs.StructuredOutputsGate` (`critique.STRUCTURED_OUTPUTS`),
  reused verbatim by `prose_harvest` and `verify` under their own env vars and
  their own latch **instances**, because a vision rejection on the critique says
  nothing about a text-only call and must not switch it off; `attach_format` /
  `detach_format` are the one request rule, and the gate's rejection vocabulary
  overlaps `investigate.py`'s two latches on purpose-neutral words, which is safe
  only while no request carries both features. Off by default because
  vision × schema is **undocumented upstream**: citations and prefill are the
  only stated incompatibilities and images are not mentioned either way, so it
  is settled by one live call (`test_live_critique_under_output_config_format`),
  not by a hermetic assertion. `_CRITIQUE_STRUCTURED_INSTRUCTION` is **derived**
  from `_CRITIQUE_FINDINGS_INSTRUCTION` by substitution with an import-time
  assert, never a second copy — one author for the enum, the verbatim rule, the
  40-finding cap and the claims contract. The schema omits that cap on purpose
  (`maxItems` is rejected by the compiler, as are `minimum`/`maximum`/
  `minLength` and `minItems`>1), so it stays prose and stays host-enforced.
  `format` is **merged** into `output_config`, never assigned over it — a fresh
  dict there silently drops `effort` on every structured request. The whole
  feature is cache-neutral: `CRITIQUE_PROMPT_VERSION` is untouched and
  `structured_key` folds in ONLY when set (the `profiles_key` precedent), so a
  fenced run keys byte-identically to every pre-F-01 entry and no paid read is
  discarded. It rides **both** cache levels, and that is not optional:
  `critique_cache_key_level1` is probed *before rendering* and answers first, so
  separating only the level-2 (PNG-bytes) key closes nothing — a warm run
  enabling structured outputs would hit a stored fenced entry at level 1 and
  return it without ever issuing a structured request, and the feature would
  read as enabled while changing nothing. Both **store** keys are rebuilt after
  the reads rather than reused from the probe, because the latch can flip in
  between and a degraded run must store under the fenced key or it parks a
  fenced-produced merge exactly where the next working structured run looks
  (`_ingest_miss` keeps the render *identity*, not the finished key, for that
  reason). `tests/test_structured_outputs.py` asserts the level-1 threading over
  the pipeline's AST, since a test naming today's call sites cannot see the next
  one added. The batch transport pins
  `structured=False` — a batch item's shape is fixed at submit and a rejection
  surfaces per item after the batch is built and billed, so the transport that
  cannot degrade does not opt in);
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
  `_MIN_INDEX_ENTRIES` gate and re-baselines both directions together.
  `run_auditors` hands **every** auditor finding to the ledger and dedups
  nothing itself (remediation WP-03.3, B7): it used to dedup by content id, which
  hashes sheet, category and quote, so two different arithmetic mismatches on one
  table row were one finding while `arithmetic_mismatched` counted two. A true
  cross-auditor duplicate (one quote, one rectangle) still becomes one ledger
  entry with both tags. `audit_titleblock`'s own two-path dedup keys on
  (sheet, quote) explicitly, never on the id, which is not an identity (B8));
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
  degraded sheet-level entry on failure; opt-in structured outputs
  (`DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS`): `HARVEST_STRUCTURED_SYSTEM_PROMPT`
  is ONE substitution on the fenced prompt with an import-time assert,
  `HARVEST_FINDING_SCHEMA` mirrors the prompt's field list one-for-one as a
  closed object — `additionalProperties: false` means a field the prompt names
  must be in the schema or the grammar forbids what the prose asks for — with
  the enums taken from `digest._MODEL_FINDING_CATEGORIES` / `_FINDING_SEVERITIES`,
  `HARVEST_STRUCTURED_PROMPT_VERSION` folds into the item key ONLY when the
  request carried the schema, the store key is re-resolved after the call so a
  read that degraded mid-call lands under the fenced key, and a bare-JSON parse
  is attempted only under the structured contract with a fenced reply still
  winning).
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
  **The match is real at every length and covers whole source words**
  (remediation WP-05.1; B5, N12, N13; the owner's rules). `classify_quote_evidence`
  asks in the plan's order: no quote → unavailable; no usable text
  (`_sheet_is_textless`: nothing survives the matching normalizer, so a layer
  of zero-width characters is none) → unavailable; `_grounded` → grounded; a
  word-free reported tile → unavailable; else `NOT_MATCHED_IN_TEXT`. `_grounded`
  used to accept any quote under six folded characters without a check, and was
  asked *before* the no-text test, so a short tag (`P-1`, `AHU-7`) was
  `TEXT_GROUNDED` on a scanned sheet and on a sheet that does not print it: a
  hallucinated tag leg was kept and counted as grounded, and a scanned sheet's
  tag leg never got the tile fallback, so the tags cross-QC quotes most never
  reached verification. At six characters and more it was a plain substring
  test, so `AHU-10` grounded inside `AHU-101`. It is now
  `anchor.SourceWords.contains` over `anchor.source_words(text)` (cached per
  text): each whitespace-delimited source word is normalized on its own with
  the anchor's unchanged `_normalize` and the words are joined, which is exactly
  `_normalize(text)` (pinned over a Unicode corpus) and also keeps where each
  word starts. The normalizer puts spaces *inside* a word (`VAV-2-1` is
  `vav 2 1`), so the normalized string alone cannot tell `vav 2` from a whole
  word. A match must start and end on a source word's **core**
  (`anchor.word_core`): only a word's leading `( [ { < " '` and trailing
  `) ] } > , ; : . ! ? " '` may stay outside it, so `P-1` is in `P-1,` and
  `(P-1)` but `VAV-2` is not in `VAV-2-1`, and `5` is not in `.5`, `-5` or
  `1.5`. `12` is not in `12,500` or `12'-6"`. No length floor: `3` grounds
  only where a standalone `3` is printed. Each word's core is found once, when
  the text is indexed, and an occurrence that starts inside a word's core skips
  to the next word, so matching is bounded by the word count, not by how often
  a quote recurs inside one long whitespace-free run (a garbled or per-glyph
  text layer). Re-deriving the core per occurrence was quadratic in that run's
  length (Codex review; pinned by a timing bound and by an equivalence check
  against a direct reading of the rule). Accepted cost: a tag inside a list
  written without spaces (`P-1,P-2`, `M-101/M-102`) is inside one source word
  and does not match. The rule is defined once, in `anchor.py`, and since
  remediation WP-05.2 (B4, N12; the owner's rules) `SourceWords` is **one
  matcher** for cross-QC and the anchor's EXACT and sub-phrase tiers: before
  words compare, each word of the text and of the quote loses the brackets and
  sentence punctuation at its edges (`anchor.fold_word`: leading `( [ {`,
  trailing `) ] } , ; : . ! ?`; never `"` `'`, which are inch and foot marks,
  `<` `>`, `%`, `/`, `-` or a leading `.`), so `RATED 175 PSI TYP` grounds in
  `RATED 175 PSI, TYP.`, `150 GPM 568 L/MIN` in `150 GPM (568 L/MIN)`, and a
  quote-side `P-1,` on a printed `P-1`; a word that folds to nothing (a lone
  comma) takes no part. At a match's two ends `word_core` still leaves the
  text's own `"` `'` `<` `>` outside it. `normalized` stays the per-word
  `_normalize` join (what `_sheet_is_textless` reads); the match runs over the
  folded words (`folded`). A quote cross-QC grounds is therefore one the
  anchor places EXACT on the same words (pinned by one shared table in
  `tests/test_anchor_whole_words.py`); WP-05.1 had left them disagreeing
  (`P-1` grounded in `SEE P-1, TYP` and went UNANCHORED on the drawing).
  `_norm_for_match` **is** the matcher's own form (`anchor._fold_text`:
  `_normalize` word by word, each word folded), so the fact-tile join folds
  what the anchor folds (N13: curly quotes, primes, vulgar fractions, `×`,
  `Ø`, infix hyphens; and since WP-05.2 each word's brackets and sentence
  punctuation): a leg quoting `6”` joins the fact that printed `6"`, a leg
  quoting `RATED 175 PSI TYP` joins the fact that recorded `RATED 175 PSI,
  TYP.`, and two facts spelled either way on one sheet with different tiles
  collide and lose the tile. A quote that folds to nothing names no text and
  joins nothing. WP-05.2's first push kept the join on `_normalize` alone, so
  a leg that grounded only through the fold lost its fact's tile, which on a
  scanned sheet is its only location (Codex review). Host-side binding, so
  `_CROSS_QC_CACHE_CONTRACT` **3 → 4**, and **4 → 5** for the fold (WP-05.2).
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
  Sheet **handles canonicalize before matching** (P8 item 11): `_norm_id` runs
  `auditors.sheet_ids.normalize_sheet_id` — the declared canonical form that
  `detect_sheet_id` itself returns — not a bare `.strip().upper()`,
  because a handle written with a non-breaking hyphen, en dash, U+2010 hyphen or
  fullwidth digits missed its plain-ASCII twin — the leg was dropped, and a
  cross-sheet finding needs two grounded sheets, so the finding went with it.
  **Four** sites compare a handle and all four use that one form, asserted equal
  rather than merely self-consistent: `_norm_id`, `critique._leg_targets` (it feeds
  `critical_signature["leg_targets"]`, so a disagreement has cross-QC resolving a
  leg the ledger then refuses to recognise as the same leg), and both claim-dedup
  keys (`critique._dedup_claims`, `auditors.arithmetic._claim_dedup_key` — a
  Unicode dash in one of the two self-consistency transcriptions inflates the
  arithmetic tally). The sharpest was `arithmetic._resolve_geometry`, whose `by_id`
  map is keyed by `detect_sheet_id` and so already canonical: an uncanonical lookup
  matched **nothing**, and the claim resolved to no sheet at all. That
  canonicalization is host-side binding no key input covers, so it carries
  `_CROSS_QC_CACHE_CONTRACT` **2 → 3** (4 since remediation WP-05.1 and 5
  since WP-05.2, above).
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
  (Phase 20 §12): a tile is never sufficient and a rectangle is not read at all
  (remediation WP-03.7, below) — merges need semantic
  sameness with **compatible critical signatures** (`critique.critical_signature`:
  tags, measurements, absence polarity, cross-sheet legs, compared by
  `critique.signature_conflicts`, the ONE copy of the rule: it names the
  conflicting axes, `signatures_compatible` is its negation, and the A/B
  harness's finding-level comparison reports those axes instead of restating the
  rule — a restated copy is the drift this codebase has already paid for twice.
  Since remediation WP-04.2 (N1) one shared tag or value no longer makes two
  signatures compatible. Quantities compare **per kind**: a unit, or one of the
  `_QUANTITY_KIND` groups of units that measure one kind of quantity (lengths
  `in`/`ft`/`mm`/`cm` and a unitless W×H size; degrees `°`/`°f`/`°c`; pressures
  `psi`/`psig`; voltages `volt`/`vac`/`vdc`/`kv`; liquid flow `gpm`/`gph`/`gpd`;
  real power `hp`/`kw`; apparent power `va`/`kva` — every group of units the
  tokenizer emits for one quantity, since a unit left out is a kind of its own
  and a shared value hides it again; `cfm` stays apart from liquid flow and kVA
  from kW on purpose, as different quantities). For every kind both carry, one
  side's tokens must include the other's, and tags must include one another the
  same way; two signatures that share no quantity at all still conflict. So one
  side may add detail and still merge, but a value or tag on EACH side that the
  other lacks blocks: `6 in`/`4 in` beside a shared `100 psi`, `12'-6"`/`12'-8"`
  (both `12ft`), `90°F`/`90°C` beside a shared `6 in`, `P-1 + V-3`/`P-1 + V-4`.
  A kind relates units without converting a value (`12 in` never equals `1 ft`),
  so it can only ever block. Tags are not grouped by prefix (`LP-1` and `HP-1` are
  both panels), so two findings that each name a different extra reference stay
  apart: deliberate retention, pinned in `tests/test_signature_compatibility.py`
  and `tests/test_quantity_signature.py` beside the recorded limits that still
  merge (swapped roles, since nothing extracts quantity roles, WP-04.3; a bare
  `12'` against `12'-6"`; WP-04.1's partial signatures). A survivor's signature
  grows (it includes `supporting_quotes`), which is why every complete-link check
  compares members as they arrived, on both sides, and never a grown signature
  (`_cluster`'s reads, `Ledger.add`'s snapshots, and Pass B's `member_history`
  for the incoming entry as well as the survivor since remediation WP-03.1) — and a
  measurement in that signature is its **value**, not its spelling: `1/2"` is
  `0.5in`, not the denominator `2in` it used to collapse to, which made *Provide
  1/2" drain* and *Provide 2" drain* one finding. `12'-6"` keeps both halves and neither goes negative, which needs TWO
  lookbehinds — a single `[A-Za-z0-9.\-]` class blocks the `101` in `M-101`
  (right) *and* the `6` in `12'-6"` (wrong, and unsafe: `12'-6"` and `12'-8"` then
  both sign as `{12ft}`). Plurals fold; `psig` deliberately does not fold into
  `psi`. Since remediation WP-04.1 the tokenizer is a scanner,
  `critique._quantity_tokens` (`lru_cache`d on its text, which is the whole
  input), that reads each quantity whole and resumes past it: hyphenated units
  (`6-inch` is `6in`), thousands groups (`12,500` is `12500`; a tight run that is
  not a valid grouping, `1,2,500`, is kept whole, because a token dropped never
  blocks a merge), degrees (`deg` is `°`; `deg F`, `degF` and `°F` are `°f`; a
  scale is never inferred), and composites, each ONE token compared whole: a W×H
  size `24x12in`, a range `4..6in`, a tight list `2,4,6in`, a voltage pair
  `120/208volt`. A compact `V` reads anywhere but a slope (`3H:1V`), a compact `A`
  only beside a pole count, an overcurrent device or a rating label: a room
  `101A` read as a current would put a quantity nobody wrote into two findings'
  signatures. The critique cache stores post-merge findings, so the tokenizer and
  the rule ride `digest_cache._CRITIQUE_CACHE_CONTRACT` (2 since WP-04.2), a term
  inside both critique key builders and nothing else, never `_SCHEMA_VERSION`;
  `tests/test_drawing_cache_identity.py` pins the rule's fingerprint to its
  value, so a rule change that forgets the bump fails). One more gate precedes
  every accepting branch of `critique._is_duplicate`: two findings that **both**
  carry a `Finding.claim_discriminator` and disagree are never duplicates
  (`_claims_differ`, remediation WP-03.3, B7). Only the arithmetic auditor sets
  one (`auditors.arithmetic.arithmetic_claim_discriminator`: the host operation,
  the terms as a multiset of exact decimals, the stated value, e.g.
  `arithmetic/1:sum:20,20,20=540`), because two mismatches on one table row
  quote one string, their unitless numbers give no signature, and their texts
  share the auditor's wording: the quote branch (Jaccard 0.667) and, once
  anchored, the geometry branch folded them, so `[30,30]=500` (UNCERTAIN)
  vanished into `[20,20,20]=540` (DETERMINISTIC). A discriminator on one side
  never blocks, so an auditor finding still merges with the model finding that
  states the same mismatch, and no model finding carries one, so the critique's
  merges and the ratchet fingerprint are unchanged. It is folded into `id`
  (`compute_finding_id`'s last argument, appended only when non-empty, like
  `source_id`) and serialized only when set. It is scoped by who sets it, not
  by a source tag. After those gates `_is_duplicate` has **two** accepting
  branches, and both need text agreement: strong overlap (≥ 0.7), or an equal
  quote with moderate overlap (≥ 0.4). It reads **no rectangle** (remediation
  WP-03.7, N28): its geometry branch (IoU > 0.5 plus an equal quote, no text
  check) is gone. The anchor stage resolves each rect from the finding's own
  quote (its tile only picks among repeated occurrences), so two findings
  quoting one string share a rect by construction and that branch was the
  quote-alone merge the quote branch refuses: `pump P-1 voltage listed as 480
  should be 208` and `pump P-1 impeller diameter conflicts with the curve`
  stayed apart in Pass A and folded in Pass B, and auditor findings (anchored
  at creation) folded that way in Pass A. No text threshold separates that pair
  from a same-spot paraphrase (0.25 against the `CO-1` pair's 0.09), and a
  model-finding discriminator could not either (both sign as `{tags: [P1]}`), so
  such a paraphrase now stays two findings: the decided cost (D-3 input in
  `_plans/DECISIONS.md`). The ratchet corpus is unanchored, so its fingerprint
  and the critique contract are unchanged. Merging keeps
  **coherent grounding** — the text/quote/tile/rect/evidence-state **and the
  verdict** (and the claim discriminator, with the `id` it is folded into) are
  one atomic bundle from a single representative, and the loser's
  quote → `supporting_quotes`. When the bundle goes to a member without a
  discriminator, the absorbed arithmetic member still blocks a different claim
  from its snapshot, since every complete-link check compares member histories. `_grounding_quality` ranks **host-computed
  provenance first**, above quote length: a `DETERMINISTIC` verdict is a
  statement about one computation over one quote (and, since remediation
  WP-07.1, over numbers that quote's own sheet prints where it anchors), so it
  must not be decided separately from the text it describes. It was, and the
  auditor holds the
  *shorter* quote (it quotes only the term it computed over), so the model's
  "the sum is 560" won the bundle and inherited the host's label — skipping
  `verify._TERMINAL_STATUSES` and inking as "an exact text check, not an AI
  judgment". Both quality tuples are computed **before** the severity union,
  which used to raise the survivor's severity to the max and erase the very
  difference it feeds (one order saw ranks (3, 2), the reverse (3, 3), and the
  tiebreak fell to raw text, where `"…560…"` sorts above `"…540…"`). Across
  merges an earlier union still feeds the next comparison, so with three or more
  members the representative can follow arrival order (N29, WP-03.5; a recorded
  limit in `tests/test_qc_numbering_tiebreak.py`). There is
  deliberately **no** independent verdict adoption and **no** backfill of a
  loser's verdict onto an empty winner. An unanchored winner never erases a rect
  that places its own quote. The merge also unions `sources`, keeps most-severe
  severity, and — when the merged provenance spans two families — raises
  `reproduced` **and** `confidence` together (`critique.merge_finding_groups`'s
  rule; the ledger implemented only half of it, so entries read
  `reproduced=True` beside `confidence=SINGLETON`). Explicit lifecycle:
  `seal()` (OPEN→SEALED) → anchor → `reconcile_post_anchor` (Pass B) →
  `number()` (SEALED→NUMBERED assigns positional `QC-###` **after** anchoring).
  Position leaves ties (two rect-less findings on a sheet, two on one rectangle,
  two set-level findings), and `models.assign_qc_ids` breaks them by the
  finding's own content, never by arrival (remediation WP-03.2, K5): the content
  `id` first (the old tie-break, so a pair whose ids differ keeps its number),
  then the text (the id hashes the quote, so two issues quoting `PUMP P-1` share
  one, B8), then `_qc_content_key`: every other field but `qc_id`, with the lists
  that record only arrival (`_ARRIVAL_ORDERED_FIELDS`: `sources`, `refs`,
  `supporting_quotes`, `prose_item_ids`, `citations`) sorted. Two entries can
  share text, quote, category and id when members they absorbed conflict; what
  they absorbed reaches the live entries, so the content still orders them, and
  two findings that tie on all of it make the same claim. The content key is
  built only for the runs the cheap key leaves tied (it serializes the whole
  finding, ~25× the rest of numbering). `qc_id` is in no cache key: it names
  evidence directories and orders display, and the investigation key reads
  `id`, text, quote and the source fingerprint instead.
  Pass B's complete-link is **symmetric** (remediation WP-03.1, B1): an entry
  folds into a survivor only when every member of its `Ledger.member_history`
  duplicates every member of the survivor's, never through either live object.
  The live survivor may no longer carry the signature of what it absorbed
  (rebuilding its history from it let Pass B undo a fold Pass A had refused,
  destroying a conflicting measurement that lived in `text` rather than the
  quote), and comparing the live *incoming* entry was B1 itself: its bundle had
  passed to a generic member, so the `500 gpm` it absorbed never met the
  `550 gpm` survivor, and whether the chain collapsed depended on which entry
  sorted first. So the outcome no longer depends on direction, a second pass
  folds nothing, and every history is a clique of `_is_duplicate` pairs. The
  candidate index (each entry's live text tokens and quote) only narrows the
  search and cannot miss a fold: the pair of representatives is always among
  the pairs checked, and every accepting branch needs a shared text token.
  Those snapshots are taken **when a merge is about to mutate an
  entry**, not eagerly at ingest; the reason was the geometry branch (an eager
  copy is a permanently *unanchored* twin of a live entry), and since WP-03.7
  the live head matters only for a cross-sheet leg the prose harvest adds after
  ingest. WP-03.1 had decided not to lend the resolved rect to same-quote
  snapshots (the geometry branch had no text check, and the resolver picks
  among repeated occurrences by each finding's own tile); WP-03.7 removed the
  branch. With no branch reading a rectangle, **Pass B folds nothing Pass A
  refused**: every pair of members two entries hold was compared by Pass A
  (each entry's first member met every member of every earlier entry), and
  nothing the predicate reads changes afterwards except a leg added to a
  leg-less entry, which can only block. Measured: zero Pass B folds over the
  suite; pinned over generated sets in
  `tests/test_position_is_not_sameness.py`. Pass B stays as the post-anchor
  step; per-observation anchors and canonical clustering are WP-03.6's.
  Pinned in `tests/test_pass_b_complete_link.py` beside the recorded limits
  later slices flip: the generic bridge's cluster and a four-finding chain's
  entry count still follow arrival order (WP-03.6), and `500` still leaves the
  exports where the bridge won its bundle (WP-03.5). The N28 limit is flipped
  there (`test_two_issues_that_quote_one_tag_stay_apart_after_anchoring`). A
  post-seal add marks the run
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
editor and diff, and a test fails if one reappears. `_normalize` is the **one**
matching normalizer: cross-QC grounding and its fact-tile join use it too
(remediation WP-05.1, N13), through `SourceWords`, which also holds the one
whole-source-word rule (`word_core`, `WORD_LEADING_PUNCTUATION`,
`WORD_TRAILING_PUNCTUATION`) and, since remediation WP-05.2, the one word fold
(`fold_word`, `WORD_LEADING_FOLD`, `WORD_TRAILING_FOLD`: the edge sets minus
`"` `'` `<` `>`, pinned). `SourceWords` is built from a string (cross-QC) or
from a sheet's words (the anchor: each word's text split on whitespace, every
piece keeping its word's index), and the anchor's tiers all apply the rule, so
`VAV-2` no longer matches inside `VAV-2-1` anywhere. `_normalize` itself is
unchanged (`auditors.arithmetic._UNICODE_DASHES` is pinned to its dash fold).

- *Disposition:* `anchor.py` (quote → PDF rect, tiered
  EXACT/FUZZY/TILE/UNANCHORED — UNANCHORED is the hallucination signal. Every
  tier matches **whole source words** (remediation WP-05.2, N12; the owner's
  rules): EXACT and the sub-phrase tier through `SourceWords` (so a quote
  cross-QC grounds is one the anchor places EXACT), a fuzzy window must start
  on a source word's first token and end on one's last
  (`_Stream.on_word_edges`: without it every match EXACT refused for cutting
  a word fell through to the window at 100% overlap), and inside a window a
  quote's measurement may not match part of a sheet word
  (`_measurements_whole`): the 17-token `…AT VAV-2 FOR…` note against one
  printing `VAV-2-1` has whole-word edges, so only this refuses it, and so is
  `1/2" PIPE` on `2-1/2" PIPE`. It reads numbers, so a letter-only tag
  (`VAV-A` inside `VAV-A-1`) in a long window is a recorded limit; and it
  checks the numeric veto's greedy alignment, so a number that could align
  either inside a longer tag or to a standalone copy nearby may be refused
  (the safe direction). Words fold on both sides before they compare
  (`fold_word`, B4), so the veto reads `175` in `175,`; a folded match stays
  `exact` (the owner's decision): the fold never removes a digit, sign,
  decimal point, unit mark or `%`, so `numbers_grounded` holds and the
  arithmetic auditor reads the sheet's words as printed (`540.`, `(540)`).
  What needs a character stream (`6 "`, `2 %`, `INCHDRAIN`, `12' - 6"`) is
  remediation WP-05.3's. Both fuzzy
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
  prohibition and is asserted unchanged. Because of the veto, an EXACT or
  numerically vetoed FUZZY match proves every number of the quote is printed on
  the sheet, once per mention: `numbers_grounded(anchor)` names those methods
  (fail-closed: a new FUZZY method grounds nothing until it carries the veto),
  and `resolve_anchors(..., matched_text=)` hands back the sheet's own words
  under each matched span, whole words as printed. Both exist for the
  arithmetic auditor (remediation WP-07.1, N3); neither changes an anchor) →
  `verify.py` (high-DPI crop re-check → VERIFIED/REJECTED/UNCERTAIN; adaptive
  thinking at medium effort inside an 8k envelope — thinking shares the
  `max_tokens` budget with the answer, and the old 1k cap fit neither, so
  verdicts came back empty and degraded to UNCERTAIN. Every live call that
  returns no verdict is now **counted** on `VerifyResult` — `malformed` /
  `truncated` / `failed`, a breakdown of `uncertain`, classified by
  `_degrade_kind` from the same validity flag and stop reason the parser
  already produced and the call site used to discard — and
  `degradation_note()` becomes one stage *warning*, because a run could not
  otherwise say whether its UNCERTAIN share came from the drawings or the
  parser. Those counts also **decide completeness** (remediation WP-01.1, N5,
  D-2); until then they were observational and every UNCERTAIN counted as
  judged, so a pass whose every call came back malformed read COMPLETE, and so
  did one verified finding beside four skipped ones. `judged` = verified +
  rejected + uncertain − `not_judged` (a valid NOT_VISIBLE is a judgment; a
  cache hit always is, since only settled verdicts are stored). `eligible` is
  set from each pass's eligibility filter **before any call** and never reads
  below the tally, so a finding that escapes the tally (the single-crop loop
  swallows an unexpected error after picking one up) still counts against
  completeness. `VerifyResult.combined(vres, cres)` feeds
  `item_coverage_status` once the failure flags are tested. `coverage_note()`
  leads the stage's warnings, counting skips and no-judgment calls separately,
  because run.log, the report's stage table and the journal show only the
  first note; each pass's `degradation_note()` follows. The cross pass's
  defensive worker-failure branch now counts `DEGRADE_FAILED`: uncounted, it
  read as a judgment. `not_judged_ids` (the `qc_id`s) lets the investigation
  stage report what it recovered. Opt-in `output_config.format`
  (`DRAWING_ANALYZER_VERIFY_STRUCTURED_OUTPUTS`, `VERIFY_VERDICT_SCHEMA`, enum =
  `sorted(_VERDICT_MAP)`) leaves the prompt untouched — it already asks for a
  bare object — so the structured and plain requests differ only by the schema,
  which rides `_request_shape_params` into both cache keys for free. The
  decision is made **once, at submit time**, and threaded to the worker
  (`_verify_one(structured=)`, `_PreparedCrossVerification.kwargs`) — never
  re-derived on the pool, or the request and the cache identity resolve
  separately and a plain verdict lands under a structured key. The latch is
  the one thing that can change in between (another worker's rejection), so
  the worker honours the keyed decision unless the latch is already off, then
  sends plain without paying for a guaranteed 400, and `_CallResult.structured`
  reports the contract actually sent; both keys are built at submit time and
  the verdict is stored under that contract's key (`cache_keys[res.structured]`,
  `plain_cache_key` on the cross path, whose requests are all prepared before
  any is sent). A verdict **replaces** the
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
  / zero-API `find_text` / `view_sheet`, all three declared `strict: true`
  (F-03) so a malformed request is rejected upstream instead of spending an
  evidence slot — `tool_round += len(granted)` charges a granted block even when
  it returns `is_error`. Strict constrains the schema *language* too, and all
  three schemas used keywords it rejects (`minItems`/`maxItems` on `rect`,
  `minimum`/`maximum` on `dpi` and `page_number`, `minLength` on `query`), so
  every one moved into the parameter `description` and stays enforced in
  `_ToolExecutor`. **Strict cannot promise `rect` holds four numbers** — array
  length is exactly what it cannot express — so a 3-number rect is schema-valid,
  reaches the host, and `len(raw) != 4` is still load-bearing; same for the DPI
  clamp and the 2-char query floor. `relax_strict_tools` (not a rebuild) powers
  the `_strict_tools_available` latch, because rebuilding drops the
  `cache_control` breakpoint `tools_with_cache` put on the last entry and
  silently un-caches the tool block. That latch nests OUTSIDE the task-budget
  one and keeps a disjoint marker vocabulary — one shared list had either latch
  disabling the other's feature. Every image is saved-before-send into
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
  `finding.verification` in place (legal post-seal), never the verification
  stage's record: concluding a finding whose verdict call returned no
  judgment adds a "recovered N of M" warning to the *investigation* stage,
  and verification keeps its PARTIAL/FAILED (D-2); concluded verdicts cache
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
  `coverage_status`. QC tags are laid out per page before any is drawn
  (`_plan_tag_boxes`, in QC-number order, never drawing order, which follows
  arrival): a tag with nothing in its way keeps its home spot above its cloud,
  and one that would cover an earlier tag slides along the row, then to the next
  row away from the cloud, bounded, falling back to home rather than dropping
  the tag. Laid out from the rectangle alone, two clouds on one rectangle (the
  pairs remediation WP-03.7 keeps apart) drew both tags at one spot and the later
  white-filled one hid the other (Codex review). Every finding annotation (cloud, tag, callout, leader,
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

**Export filesystem contract (`export.py`, P9).** Every write inside the atomic
publish goes through `long_path(folder)`, derived **once** in
`write_drawing_export`: each writer builds its targets by joining onto that
folder, so a joined path inherits the `\\?\` prefix and the ~18 write sites need
no individual treatment. `_long_path_text` is the pure string transform (UNC
becomes `\\?\UNC\…`, never a bare prefix; idempotent; device paths untouched) and
`long_path` is the os-gated wrapper — an **identity function** off Windows, which
is why the Linux suite exercises byte-identical behaviour and the Windows CI leg
exercises the prefixed form end to end. `_unique_dir` probes and `mkdir` creates
through it as well, and that ordering is load-bearing twice: a parent deep enough
that the export folder *itself* passes MAX_PATH would otherwise fail before the
first prefixed write, and past MAX_PATH an unprefixed `exists()` answers *False*
for a directory that is really there — so the name reads as free and the publish
rename moves the new export over the old one. The prefixed form is internal: the path
returned to the caller (and shown in the GUI, and passed to `os.startfile`) is
always plain. Name dedupe is `casefold()`-keyed at all four allocators
(`models.name_is_taken` / `record_name`) because `M-101` and `m-101` are one file
on Windows and macOS; the original case is still written. The publish rename's
retry loop **waits** between attempts (`_publish_backoff`, 0.1s/0.4s) — sized for
a filesystem lock, not an API rate limit, so deliberately not
`digest._retry_backoff_seconds` (2s/4s/8s), and it never sleeps after the last
attempt.

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
beside a local header read as a report predating its own run). The chat widget hands the report to the model inside a
`<document><source>…</source><document_content>…</document_content></document>`
wrapper (Anthropic's long-context guidance for one large reference document);
the wrapper is byte-stable for the life of the page, so the 1h cache breakpoint
on that block still holds. The chat widget's **turn loop** owns four rules a DOM emulator cannot check
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
store, pricing, tokenizer, the structured-outputs gate, and
`terminal_outcome.py`, the one stop-reason classifier: D-1, adopted so far by the
digest's two transports only, with the other response consumers moving onto it
in their WP-01 slices rather than growing a second copy). The tokenizer is
estimate-only: `tiktoken` was removed — its only two callers had no callers,
and it fetched its encoding from a third-party host on first use, which a
locked-down workstation blocks — so the exact count is `count_tokens_via_api`
and the local path is the conservative safety-factor table. `reference_audit.py` is a back-compat shim over
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
  in existing tests. No test may hit the network or need a key. Enforced by
  `tests/fixtures/hermetic_guard.py`: a non-local connection or lookup fails the
  test that made it, even when the code under test swallowed the error.
- **I-5 — PyMuPDF isolation:** only `render.py` and `annotate.py` may import
  PyMuPDF. The README's AGPL licensing story depends on this; `anchor.py` and
  `tiling.py` work on extracted word rectangles precisely to preserve it.
- **I-6 — cache correctness:** prompt versions are content hashes
  (`DIGEST_PROMPT_VERSION`, `CRITIQUE_PROMPT_VERSION`), so prompt edits
  auto-invalidate; `digest_cache._SCHEMA_VERSION` is manual — bump it whenever
  what is stored or sent changes. The critique's host merge rule is the
  exception: it has its own term, `_CRITIQUE_CACHE_CONTRACT`, folded into the two
  critique builders only, because the schema version feeds every builder and
  its v10 bump re-billed every digest to invalidate critiques. A hash only
  covers what it is given: the
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
  *operands* are trusted (`DETERMINISTIC` + auto deterministic-only ink,
  `operand_origin=TEXT_EXTRACTED`, Phase 25 §17.5) only when the sheet prints
  every one where the claim's quote anchors, decided **after** the auditor's own
  anchoring pass (remediation WP-07.1, N3): the claim resolved to a sheet; its
  quote anchored there EXACT or FUZZY by a numerically vetoed method
  (`anchor.numbers_grounded`; never TILE, never UNANCHORED); and the terms and
  the stated value together fit, **one occurrence each**, the numbers that
  **both** the quote and the sheet's words under the matched span print
  (`arithmetic._operands_grounded`: per value the smaller count, so neither
  the model's spelling nor the sheet's non-ASCII forms can promote on their
  own). It was membership over the quote string, before anchoring: one printed
  `20` supported three transcribed `20`s (`sum [20,20,20] = 40` on
  `20 + 20 = 40` was a high-severity DETERMINISTIC mismatch on a correct
  equation), the stated value could reuse a term's number (`20 + 30` "stated"
  20), and a quote the sheet does not carry or a claim on no sheet at all was
  trusted as readily. Every mismatch is built `MODEL_TRANSCRIBED` and promoted
  only after anchoring, so a failure while deciding (an anchoring error on one
  sheet included) leaves it `UNCERTAIN`, the safe direction. A mismatch from
  `MODEL_TRANSCRIBED` terms stays `UNCERTAIN` and is crop-verified before it
  inks as ground truth. The **relationship** is checked host-side too
  (remediation WP-07.2, A8; the owner's rule): `_relationship_grounded`
  needs the quote **and** the matched span's words each to print the claim as
  one equation (`_equations`): the stated value is the first number after `=`
  or `TOTAL`/`SUBTOTAL`, its operands are **exactly** the terms (a multiset: an
  operand left out of a correct `20 20 20 TOTAL 60` would otherwise be a
  DETERMINISTIC mismatch on a correct row), and every join is the claim's
  operation (`+` for a sum; `x`/`×`/`*` for a product or factor); an
  operator-less list is a sum only with TOTAL (`20 20 20 TOTAL 540`), never
  with `=` alone. `_gap_marks` reads the text between numbers: a digit there is
  a number the scan refused (`FP101`, `30%`), so the relationship is
  unreadable, as are a subtraction or division, a symbol it does not know
  (`@`, `$`) and mixed operators; a label's number before the operands is
  read as one of them (`RISER 3: 20 20 20 TOTAL 540` has four, a recorded
  cost). So a
  product transcribed as a sum (`20 x 2 = 40` as `sum [20, 2]`), a total
  swapped into the terms and a correct subtraction all stay `UNCERTAIN`. Both
  sides, as for the operands: a FUZZY window may differ from the sheet in one
  non-numeric token, and that token can be the operator. No role or operator
  field was added to the claims contract (plan WP-07 step 4); the host reads
  roles from the printed layout only. A term that is not **one** value
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
  crop check to re-learn what the quote already said. Since remediation WP-07.2
  (A8, the owner's rules) the scanner and the parser read only a token that is
  one value. A **letter glued before** the digits makes them a tag's or sheet
  id's (`FP101`, `A1.01`, and `M-101` / `AHU-2`, where a hyphen after a letter
  joins the tag and is **never a minus sign**: `M-101 P-3 AHU-2` scanned as
  -101, -3, -2 and grounded a `-3` operand); a `+` glued to a letter stays an
  operator (`250GPM+100GPM` reads 100) except as an exponent's sign. **Letters
  after** the number are its unit (`20A`, `150GPM`, `12IN`, `0.20 gpm/ft²`)
  unless digits follow them directly: `1e3`, `2.5e-2`, `24x12`, `2P20A`,
  `10A1`, `100m2` are not one value, in the parser (`_NUMERIC_TAIL_RE`) and the
  scanner alike. **Scientific notation is rejected, not read** (`1e3` was 1, so
  `sum ["1e3", 500] = 1600` inked "the sum of 1, 500 is 501"; `2E1` is as
  likely a panel as an exponent), so a term spelled that way makes its claim
  unusable. The same refusal covers a Unicode dash wherever `-` binds or
  after a letter (`_UNICODE_DASHES`, pinned equal to the dashes
  `anchor._normalize` folds; `−5` is refused because `[-+]` cannot read its
  sign), a fraction slash, a `×` between digits and a vulgar fraction glued on
  (`2½"` was read as 2). Every change only ever **refuses**: a parse becomes
  `None` or stays what it was, and the scan only loses numbers, so no finding's
  text, discriminator or id moves and nothing is newly trusted. Accepted cost:
  an ASCII-squared `100m2` is refused, and a `Ø6"` (Ø is a letter) is read as a
  tag. `_fmt` expands an integral with `format(v, "f")`, never
  `quantize`, which raises above the decimal context's 28 digits from ordinary
  string terms — inside the `Finding(...)` expression, *after* `mismatched` was
  incremented. Each claim now has its own `try` with a tally rollback: the
  orchestrator's single batch-wide `try` meant one bad claim lost every arithmetic
  finding **and** all four `arithmetic_*` stat keys, after which the summary line
  read `arith=0/0` — indistinguishable from a set with no claims. What counts as
  **one claim** is decided on parsed values, never spellings: every claim dedup
  (`arithmetic._claim_dedup_key`, `critique._dedup_claims`,
  `cross_qc._dedup_claims`) and the discriminator share
  `arithmetic.claim_content_key` — the host operation (`factor` is a product),
  the terms as a sorted multiset of `canonical_decimal` spellings (exact, never
  rounded at 28 digits), the stated value (remediation WP-03.3). `20`, `"20.0"`
  and the JSON float `20.0` were two claims under `str()` keys, checked and
  counted twice. A term that does not parse keeps its raw spelling behind a
  `raw:` tag, so it never collapses two different claims and never equals a
  number.
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
  model-ceiling clamp). Digest and critique now read that registry too
  (`DEFAULT_DIGEST_EFFORT = default_effort_for_phase(PHASE_REVIEW)`, inherited by
  `DEFAULT_CRITIQUE_EFFORT`): they cannot use `apply_effort_config` because both
  expose `effort` as a caller override, so they clamp per request via
  `clamp_effort_for_model` instead. Before this, `PHASE_REVIEW` was registered at
  `EFFORT_XHIGH` while both stages sent a hardcoded `"high"` and **nothing read
  the entry** — two sources of truth that never had to agree, with the live one
  invisible to anyone tuning the registry. It was moved to `EFFORT_HIGH`, the
  level the stages actually send, rather than wiring them up at `xhigh`: raising
  it is a cost increase on the highest-volume calls in the pipeline AND a
  cache-wide invalidation (`effort` is a component of `digest_cache_key` /
  `critique_cache_key`), so it is a separately-priced decision and one worth an
  eval — `high` is also what the API applies when the field is omitted.
  `PHASE_CROSS_CHECK` keeps its `xhigh` and stays orphaned. A phase that wants
  shallow work registers `EFFORT_LOW`;
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
