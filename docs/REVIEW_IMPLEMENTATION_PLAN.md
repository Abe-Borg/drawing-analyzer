# Drawing Analyzer: corrective implementation and evaluation plan

Prepared: 2026-09-08  
Reviewed baseline: `89c8ecb`, version `1.3.0rc1`  
Audience: coding agents implementing the work, an independent reviewing agent, and the repository owner  
Status: implementation specification; the changes below have not yet been implemented

## 1. Outcome and scope

Implement the supported correctness and estimation fixes first. Improve the existing experiment tooling so later cost decisions can be based on identifiable findings and actual stage costs. Preserve the current production review quality settings while doing that work.

The intended outcomes are:

1. A genuine cross-sheet quote does not become invalid merely because its source text was excluded from a model prompt budget.
2. Estimates describe the configuration that will actually execute, including model routing, transport, image resolution policy, and relevant caching assumptions.
3. The operator can distinguish a planning estimate from a conservative image allowance and from actual recorded usage.
4. A/B experiments retain enough evidence to investigate lost findings instead of relying only on aggregate percentages.
5. Documentation accurately describes rendering reuse, text retention, cache behavior, and the limits of quality measurements.

This plan does **not** propose changing the shipping model defaults, the 6×6 grid, 8% overlap, 1560-pixel vector target, raster target, two-read critique, blank suppression, or model prompt text as part of the immediate corrective release. Research packages describe how to evaluate those changes separately.

The original external review brief is background evidence, not an implementation specification. Several of its claims were refuted. Do not implement its recommendations wholesale or interpret its 57-item checklist as already completed.

The owner requested this handoff document. No live-run dataset or spending budget was selected during planning. Implement and validate locally with hermetic fixtures; conduct paid experiments only within an explicitly selected dataset, configuration, and budget. Do not infer publishing, merging, or releasing instructions from this document.

### 1.1 Decision table

| Work | Decision | Reason |
|---|---|---|
| Separate full source text from prompt text; fix sharded cross-QC grounding | Implement first | Concrete conditional loss of valid evidence |
| Correct A/B estimate/runtime model mismatch | Implement | Estimate process resolves import-bound defaults differently from real arm processes |
| Correct transport-dependent specification-cache wording | Implement | Batch inputs are priced uncached but described as cached |
| Improve image and stage cost previews | Implement incrementally | Current square/raster allowance overstates typical imagery and hides assumptions |
| Record family costs, actual resolved configuration, and finding-level evidence in A/B outputs | Implement | Needed to assess savings and possible missed defects |
| Add explicit overlap parameters to the existing experiment harness | Implement as opt-in tooling | Current environment-only variants cannot change overlap |
| Correct repository documentation and stale comments | Implement | Misleading explanations can cause future regressions |
| Add a digest-specific environment variable | Defer | Existing API parameter and stage overrides already support the experiment |
| Rewrite import-time model configuration globally | Defer | Narrow subprocess resolution fixes the demonstrated harness issue |
| Reduce resolution, overlap, critique reads, or change default model | Measurement required | Potential loss of review coverage or changed meaning of confidence |
| Batch first-pass verification | Measurement required | Benefit depends on actual eligible stage spend and latency |
| Share digest/critique image-prefix cache | Defer behind measurements | Smaller savings than brief claims; changes prompts and scheduling |
| Broaden exception guards to `BaseException` | Do not do as general hardening | No demonstrated supported-environment failure justifies swallowing process-control exceptions |
| Skip tiles because they lack words and vector operations | Reject this criterion | Raster images and annotations can still carry the evidence |

## 2. Evidence and corrected assumptions

Line numbers below are navigation hints at the reviewed commit. Search by symbol after rebasing. Paths are repository-relative so this document remains portable.

### 2.1 Supported correctness issue

`render.render_sheet()` extracts both reading-order text and complete word tuples. It caps only `sheet_text`; `anchor.resolve_anchors()` uses the full `words` stream. An in-memory check demonstrated that a quote absent from capped prompt text can still receive an `EXACT` anchor. Thus the brief's statement that tail quotes necessarily become `UNANCHORED` is false.

There is a narrower issue in `cross_qc.py`:

- `MAX_SHEETS_SINGLE_CALL = 40` near line 90.
- `cross_sheet_qc()` selects the sharded path when retained entries exceed that threshold, near line 1171. This is the number of included readable entries, not necessarily the number of PDF pages selected.
- `_finding_from_handles()` checks nonempty quotes against capped `geom.sheet_text`, near line 464, and discards a finding when fewer than two grounded sheets remain.
- `_parse_facts()` applies the same capped-text test to exact quotes, near line 804.
- A genuine quote after the cap can be transcribed into a digest from pixels, returned by cross-QC, and then discarded despite existing in the source and full word stream.

Assessment: P2, high confidence in the conditional source behavior; prevalence on real projects is unmeasured. The large-set rejection was established by code inspection, not an end-to-end production run. Reproduce it hermetically before changing the implementation.

Important qualification: cross-QC also applies its own 4,000-character text-layer budget. A genuine over-15,000-character case already records omitted input and is ordinarily budget-degraded, so its result is not admitted to the cross-QC cache. Recovering a valid finding does not make that review complete. Preserve this distinction in tests and documentation.

### 2.2 Supported estimation and documentation issues

- `pipeline.estimate_image_tokens_for_set()` near line 3659 uses square images at the raster target. Its 177,008-token allowance for a default sheet is deliberate; it is not the expected image usage of a vector E-size sheet, approximately 92,871 tokens under the reviewed formulas.
- `scripts/ab_sweep_drawing_analyzer.py::_estimate()` imports `REVIEW_MODEL_DEFAULT` before mutating environment variables for each arm. Actual arms execute in fresh subprocesses. A global-model variant can therefore be estimated using the wrong digest model and fallback defaults.
- `cost.format_drawing_cost_prompt()` and `format_exhaustive_cost_prompt()` describe uploaded specifications as cached even when the digest batch path deliberately sends them without prompt caching.
- The exhaustive estimator computes image tokens using the digest model and reuses that count for critique. A model with a different vision-token tier needs its own count over the same image dimensions.
- The standard estimator prices synthesis and focus using the digest model, although those stages have independent runtime model resolvers. Those overrides must also be reflected in standard-mode estimates.
- The fixed prompt-token allowance does not account accurately for arbitrary retained sheet text. An image upper allowance does not establish an upper bound on the whole invoice.
- `docs/PERFORMANCE_AND_COST_VALIDATION.md` still says cold exhaustive runs necessarily render twice. `render_spool.py` already reuses rendered bytes; a second render is a fallback when reuse is unavailable.
- `pipeline.extract_drawing_context()` still contains the stale explanation that digest images are gone before critique, near line 2373.

### 2.3 Correct cost arithmetic

At the reviewed pricing, Opus 5 input/output rates are $5/$25 per million tokens; Sonnet 5 rates are $2/$10. Five-minute cache writes cost 1.25× input, one-hour writes 2×, and cache reads 0.1× for those models. Batch token pricing is half the standard rate.

For current real-time exhaustive image input, assuming critique read two hits its cache:

`digest 1.0 + critique write 1.25 + critique read 0.1 = 2.35 full-price reads`

A proposed shared five-minute prefix would cost 1.45 read equivalents, a 38.3% reduction of that image component. A shared one-hour prefix would cost 2.2 equivalents, a 6.4% reduction. These are not whole-run savings and are not measured cache-hit guarantees. If both current critique requests miss and write, their combined multiplier is 2.5, not 2.0; adding the digest gives 3.5 for that image component.

The current renderer chooses 2576 pixels when a grid produces at most 20 images. A 3×3 or 2×2 grid therefore does not automatically retain the 1560 target used in the brief's adaptive-grid table. The vector-target environment override does not alter this few-image branch.

For 20 E-size + 8 D-size + 6 11×17 + 2 assumed letter-size cover sheets, the source-formula estimates are:

| Image-input scenario | Current 6×6 | Proposed per-sheet grids with current target policy | Proposed per-sheet grids with explicit 1560 throughout |
|---|---:|---:|---:|
| Image tokens for one read of the set | 3,150,948 | 2,642,892 | 2,459,178 |
| Reduction | — | 16.12% | 21.95% |
| Standard real-time image input | $15.75 | $13.21 | $12.30 |
| Standard batch image input | $7.88 | $6.61 | $6.15 |
| Exhaustive real-time image input, successful critique cache hit | $37.02 | $31.05 | $28.90 |
| Exhaustive batch image input | $23.63 | $19.82 | $18.44 |

These values were independently recomputed from geometry/token formulas with whole-pixel dimension rounding. They are not rendered-image measurements or complete run estimates. They exclude blank suppression, prompt text, output/thinking, verification, investigation, citation, retries, and local result-cache hits. Use them as arithmetic cross-checks, not production regression fixtures requiring exact agreement with rasterizer rounding.

### 2.4 Limits of the prior review

No complete security, licensing, cache-dependency, markup-geometry, or 57-item repository audit was performed. The reported cryptography failure was not reproduced in a supported production environment. A Python launcher in the checked-out virtual environment failed during read-only investigation; that is not evidence of a product defect. Isolated dependency-free in-memory checks were used for the anchor and exception-class counterexamples. Do not claim the original brief's full-suite results as the new baseline.

## 3. Requirements that apply to every work package

1. **Full visual coverage:** no content-bearing image tile may be removed as an incidental effect of estimation, metadata collection, or experiments.
2. **Prose preservation:** the core digest prose must remain unchanged for identical model responses. Do not rebuild, normalize, or rewrite `combined_text` to add diagnostics. Preserve existing additive-section rules.
3. **Non-fatal QC:** new optional work must fail within its own stage. Never convert an exception into an empty successful result or make a partial review appear complete.
4. **Hermetic tests:** no real provider calls or keys in ordinary tests. Use existing fake clients and generated fixtures. Dependency advisory checks are separate from application tests.
5. **PDF-engine isolation:** only the existing approved production modules, `render.py` and `annotate.py`, may import PyMuPDF. Pure helpers and cost models use plain data. Respect the established sequential PDF-access discipline.
6. **Cache correctness:** host-side acceptance inputs matter even when model request bytes do not change. Invalidate the affected namespace, not every namespace by habit.
7. **Deterministic assembly:** ordered source identities, finding legs, keys, and artifact content must remain deterministic for fixed inputs and fixed model results. Run IDs, timestamps, usage histories, and cold/warm cost differences are not expected to be identical.
8. **Grounding:** do not weaken quote matching, accept fabricated text, or substitute model output for source evidence to make a regression test pass.
9. **Edition awareness:** retain the project's evidenced adopted edition as the basis. Do not silently replace it with the latest published edition. Preserve explicit handling of ambiguity and jurisdiction; this plan changes no code-edition rules.
10. **Accounting and receipts:** `RunUsage` remains append-only, and coverage remains derived from reconciled saved-PDF receipts. Estimated cost must never be appended as actual usage.
11. **Windows:** use supported Python and Windows-compatible process/path handling. Avoid POSIX-only instructions in user-facing examples.
12. **Bounded change:** no dependency upgrades, global formatting, file splitting, GUI redesign, or confidence-field migration unless a work package requires it.

## 4. Work breakdown and agent ownership

| Package | Primary responsibility | Dependencies | Suggested owner |
|---|---|---|---|
| WP-00 | Baseline, reproduction, interface agreement | None | Integrator |
| WP-01 | Full evidence text and sharded grounding fix | WP-00 | Evidence agent |
| WP-02 | A/B process parity and immediate cost-copy fixes | WP-00 | Harness/cost agent |
| WP-03A | Pure shape-aware and cache-aware estimation | WP-00; agrees interface with WP-01 | Cost agent |
| WP-03B | Responsive GUI integration of cost basis | WP-03A; WP-01 model/render edits landed | GUI agent |
| WP-04 | Auditable experiment records and overlap controls | WP-02; WP-03A for estimates | Harness agent |
| WP-05 | Documentation corrections and operating instructions | Can draft early; finalize after WP-01–04 | Documentation/integrator |
| WP-06 | Independent review, full regression, release evidence | Implemented immediate packages | Reviewer/integrator |

With four agents, use one integrator, one evidence agent, one cost/harness agent, and one independent reviewer. The reviewer can inspect tests and draft documentation while implementation proceeds. Rotate the GUI work in after shared contracts settle.

Do not let agents edit shared files concurrently without a specific handoff:

- `models.py` and `render.py`: evidence agent owns first; cost-basis additions follow or arrive as an agreed small patch.
- `cost.py` and `tests/test_cost.py`: one owner integrates WP-02 copy fixes and WP-03 arithmetic.
- `scripts/ab_sweep_drawing_analyzer.py` and `tests/test_ab_sweep.py`: one owner performs WP-02 before WP-04.
- `pipeline.py`, documentation, and changelog: integrator owns final integration.

Use small reviewable commits or draft PRs per package when the execution environment supports that workflow. Do not automatically merge or publish. Rebase against current code and preserve unrelated user changes.

## 5. WP-00: establish the actual baseline

### Tasks

1. Record current commit, working-tree changes, Python executable/version, PyMuPDF version, SDK version, and active package metadata. Record only non-secret configuration.
2. Read repository guidance, the relevant source functions, and existing tests. Verify that the issue is still present if HEAD differs from `89c8ecb`.
3. Establish a supported working test environment. If the local virtual environment launcher fails, diagnose its interpreter path before attributing failures to application code. Do not replace dependency pins merely to make local collection pass.
4. Reproduce the sharded quote rejection with an in-memory geometry/digest fixture and fake cross-QC client before implementing WP-01.
5. Reproduce the A/B estimate model mismatch without a provider client before implementing WP-02.
6. Run focused existing suites for those areas and record pre-existing failures separately.
7. Agree the additive evidence field/helper and cost-preview data interfaces before parallel edits begin.

### Deliverable

A short implementation log in the PR/task containing reproduced failures, baseline test outcomes, current symbols, and agreed file ownership. Do not turn the planning document's observations into claims of passing tests.

## 6. WP-01: retain complete source evidence without increasing prompts

### 6.1 Required behavior

Keep `sheet_text` as the existing capped, disclosed model-input text. Add a separate full reading-order text value for host-side source checks. Do not increase `SHEET_TEXT_MAX_CHARS` in this package.

Recommended additive contract:

```python
# Append to both RenderedSheet and SheetGeometry without changing existing
# positional parameter order.
full_sheet_text: str | None = None

# Pure helper, placed in models.py or another existing dependency-safe module.
def sheet_evidence_text(sheet: object) -> str:
    ...
```

The helper must distinguish:

- A present full string: use it, including an explicitly empty string.
- `None` or an absent attribute on older callers/fixtures: fall back to existing `sheet_text` for compatibility.
- A malformed non-string value: handle defensively under a documented contract; do not silently stringify arbitrary objects into trusted evidence.

Do not use `full_sheet_text or sheet_text`: that conflates known-empty extraction with unavailable full text. Do not manufacture full reading-order text by joining word tuples; that changes line boundaries and extraction semantics.

### 6.2 Implementation map

| File/symbol | Required change |
|---|---|
| `models.py::RenderedSheet` | Append optional full-text field and document distinction from capped prompt text and words |
| `models.py::SheetGeometry` | Same field; keep geometry image-free |
| `models.py::SheetGeometry.from_rendered` | Preserve full text and legacy absence correctly |
| `render.py::render_sheet` | Assign already-extracted `raw_text` to full text; keep `_cap_sheet_text(raw_text)` unchanged |
| `render.py::_sheet_geometry_no_render` | Populate the same full text on level-one cache/prescan paths without rasterizing |
| `render_spool.py::_SheetRecord`, `put`, `load` | Preserve full text exactly through the temporary render handoff |
| `cross_qc.py::_finding_from_handles` | Validate each leg using source evidence helper |
| `cross_qc.py::_parse_facts` | Validate map facts using the same helper |
| `cross_qc.py::_cross_qc_cache_key` | Include evidence identity separately from prompt text; bump scoped acceptance contract |
| `pipeline.py` and `run_journal.py`, if needed | Add count-only source/prompt truncation diagnostics, never raw text |

Keep `cross_sheet_qc()` request entries and `_budgeted_text_layer()` on the existing capped text in this corrective package. Do not feed full text through those prompt-building paths just because the field now exists: omission accounting and completeness gates could change even when the visible prefix looks similar.

The legacy ≤40-entry validator has different behavior. Preserve that behavior unless a separately demonstrated defect requires changing it. The immediate fix is to stop the >40-entry path from rejecting source evidence that actually exists, while retaining its existing anti-hallucination checks.

### 6.3 Consumer audit and explicit boundaries

Inventory all `sheet_text` consumers and classify them before final review:

| Consumer | Immediate package behavior |
|---|---|
| Digest and critique, real-time and batch | Keep existing capped text and wire bytes |
| Cross-QC model prompts | Keep existing budgets and text |
| Cross-QC host validators | Use full evidence text |
| Anchor and word-based deterministic auditors | Preserve full-word behavior; no replacement needed |
| `citation_check.py` adoption/trust/edition checks | Document full-text opportunity; no blanket replacement in WP-01 |
| `set_identity.py` harvest and model corpus | Preserve current model-visible behavior; separate future evaluation |
| `prose_harvest.py` prompts/matching | Preserve current behavior; record any demonstrated issue separately |
| `export.py` sheet-text files | Keep current content contract in immediate fix; document that it is capped text |
| `html_report.py` search/context text | Preserve bounds and escaping; do not embed all full text automatically |
| Logs/manifests | Counts, availability, and truncation only; no new source-text disclosure |

This audit is required to prevent accidental changes to downstream prompts or evidence trust. It is not a mandate to migrate every consumer in this release.

### 6.4 Cache design

Use `_CROSS_QC_CACHE_CONTRACT`, currently `2`, to invalidate cached cross-QC results produced with old grounding rules. Advance it to the next value present at implementation time; do not assume no other branch has changed it.

For each sheet, add a deterministic host-evidence fingerprint to `_cross_qc_cache_key()`. Include the evidence-availability distinction if it affects fallback or reporting. Hash the full selected evidence as UTF-8 rather than placing its raw text into diagnostic/cache metadata. Compute the hash once per key build per sheet, not once per quote or reconciliation pair.

Required cache consequences:

- Identical prompts with a changed source-text tail produce different cross-QC keys.
- Cached empty/filtered cross-QC results under the old contract cannot replay as the corrected result.
- Unchanged full evidence and configuration hit the corrected cache on a warm rerun **when the result is otherwise complete and cache-eligible**. Dense cases with existing budget degradation must continue to recompute cross-QC.
- Digest/critique image request and prompt bytes remain unchanged, so their result caches remain reusable.
- Do not bump `digest_cache._SCHEMA_VERSION`, `_STAGE_CACHE_SCHEMA`, PDF render identity, or prompt hashes merely to invalidate cross-QC. A global schema bump currently clears broader stored content; that is unnecessary spend for this fix.
- If an implementation choice actually changes a stored global format or model request, document that fact and revisit the relevant key instead of retaining a stale hit.

### 6.5 Meaningful regression cases

Extend existing tests in `test_drawing_models.py`, `test_drawing_render.py`, `test_render_spool.py`, `test_drawing_cross_qc.py`, `test_drawing_stage_cache.py`, and appropriate pipeline acceptance tests.

Required cases:

1. **Tail evidence accepted:** full source contains a distinctive quote after character 15,000; capped prompt lacks it; the digest prose includes it, modeling transcription from pixels. A 41-or-more-entry sharded fake response cites it and another real sheet. The fact/finding survives and both legs resolve. Use a content-aware fake that emits the fact only when its handle and quote reach the shard through the digest, and emits reconciliation only when both facts reach the reconcile request.
2. **Fabrication still rejected:** replace that quote with a never-present string; it must still fail grounding. Also test a quote found only on another sheet.
3. **Threshold scope:** 40 and 41 retained entries exercise the intended branches, including selected PDFs with failed/empty digests so selected-page count is not mistaken for retained-entry count.
4. **Full text stays full:** newline-sensitive and non-ASCII extraction survives rendered-sheet, geometry, prescan, and spool transfer without truncation or normalization.
5. **Compatibility:** missing/`None` full text falls back; explicit empty full text does not fall back to nonempty capped text.
6. **Anchor behavior unchanged:** a real tail quote anchors exactly through the existing complete word list; no fuzzy threshold or tile behavior changes.
7. **Prompt stability:** capture digest and critique request structures in both transports and cross-QC request text; full-text addition alone does not change them.
8. **Tail-only key sensitivity:** same capped prefix/digest/model but different full tail must miss cross-QC cache. Use a fixture holding digest text fixed to isolate the acceptance input.
9. **Old cache rejected, eligible new cache reused:** use a short-text, non-degraded fixture to seed the old scoped key, show recomputation, then show zero new cross-QC calls on the next unchanged run. Test tail-only key sensitivity directly. For the realistic dense-tail fixture, preserve budget degradation and cross-QC recomputation; do not relax cache admission or assert `complete=True` merely because grounding was repaired.
10. **Warm render avoidance:** full evidence remains available after a level-one digest hit without full-sheet rasterization.
11. **Failure isolation:** extraction/spool/cache failure follows existing non-fatal behavior; no empty result silently upgrades review completeness.
12. **No privacy regression:** diagnostic events carry counts/flags only; raw tail text and absolute source paths are absent from new log fields.

Use pure fixtures for 41-sheet topology. Only use generated PDFs where extraction, coordinate consistency, or cold/warm render behavior is the thing being tested. Do not create 41 expensive rendered fixtures merely to exercise a list-length branch.

### 6.6 Acceptance and performance

Acceptance requires the positive tail-evidence regression and negative fabricated-evidence regression together. Fixing one by accepting all quotes fails the package.

Memory overhead should be the retained source text, not an additional set of PNGs or repeated per-finding copies. Reuse immutable strings where practical. Full-text hashing and matching must not introduce repeated PDF extraction. Measure a dense-text fixture and increasing sheet counts with the existing benchmark approach; use repeated-run medians for performance claims.

If repeated `_grounded()` normalization of long source strings becomes material, prepare a source-page-scoped normalized-text map once per cross-QC invocation while preserving the existing normalization semantics. Avoid a process-global cache or a new cap that recreates the evidence loss. Holding a field alone does not make the model read the full page text; the fix only validates facts the model already supplies.

Recovered findings may legitimately increase ledger counts, verification work, and final costs. That is an expected consequence of recovering omitted evidence, not a cost regression to suppress. No additional model calls should occur merely to obtain full source text.

## 7. WP-02: make A/B estimates describe the actual arm

### 7.1 Process/configuration parity

Fix `scripts/ab_sweep_drawing_analyzer.py::_estimate()` using the same fresh-process configuration boundary as actual arms. Preferred design: an internal estimate-only child mode that receives the arm environment before importing application configuration, returns structured estimate data, and never obtains a provider client.

Reuse shared arm configuration resolution for estimation and execution. It should describe resolved stage models, digest/critique transports, grid, overlap, target override/effective target policy, exhaustive mode, and any selected options that affect request cost. Avoid a new application-wide dynamic model-default system.

Requirements:

- Establish each child environment before importing `core.api_config` or modules whose defaults bind its values.
- Use `sys.executable` and argument arrays; no shell-composed command strings.
- Estimate-only execution performs local inspection only: no client construction, provider token-count call, upload, batch creation, or analysis cache mutation.
- Do not clear and rebuild the parent process environment while pricing arms.
- Propagate child errors honestly; one failed estimate is not a zero-cost arm.
- Print actual resolved model/transport labels, including fallback effects of changing the global model.
- Keep secret-valued environment settings out of printed labels and saved effective-configuration records. The environment can contain an API key even though it is unnecessary for estimation.
- Replace the current claim that cold-arm estimates are what the run "will actually cost" with wording that preserves uncertainty.

### 7.2 Immediate wording corrections

In `cost.format_drawing_cost_prompt()` and `format_exhaustive_cost_prompt()`:

- For batch digest, describe specification text as ordinary batch input; do not promise a prompt-cache read discount.
- For real-time digest, describe caching as conditional; parallel initial requests and expiry can create additional writes.
- Replace any implication that the entire invoice is bounded by the image allowance.
- Distinguish local result-cache hits from provider prompt-cache reads. A local cache hit avoids that model call; it does not guarantee every other stage is free.
- Keep the existing pre-send confirmation behavior and actual transport selection unchanged.

### 7.3 Tests and acceptance

Extend `tests/test_ab_sweep.py` and `tests/test_cost.py`:

1. Baseline global model and variant global model resolve differently in estimate children, matching execution children.
2. Sonnet digest plus explicit Opus critique and cross-QC overrides shows those exact stage models in both modes.
3. Batch/real-time environment changes match actual arm transport.
4. Parent environment remains unchanged after success and failure.
5. Estimate-only works with no API key and with a fake client factory that raises if called.
6. Unknown-priced models remain unknown, not zero or a partial known-stage total.
7. Both cost dialogs describe specification caching accurately for digest transport, including hybrid mode.
8. Paths containing spaces work on Windows; no test depends on a particular user directory.
9. Output never exposes an environment secret; use obvious fake sentinel strings in tests.

Do not use live calls to validate process/model resolution. A child can report its resolved configuration and estimate as JSON without running the pipeline.

## 8. WP-03A: pure cost-preview arithmetic and explicit assumptions

### 8.1 Preserve the existing upper-allowance helper

Keep `pipeline.estimate_image_tokens_for_set()` as the legacy conservative image allowance, or introduce an explicitly named successor while preserving compatibility. Do not silently redefine its existing public meaning to be a typical estimate.

Add a pure estimate path using optional plain per-page information. Suggested record, with final naming left to the implementer:

```text
SheetCostBasis:
    stable source/page reference
    displayed width and height in points
    classification: vector / raster / unknown
    capped prompt-text character count, if inspected
    geometry availability and inspection-error state
```

Place this small record in `models.py` or a dependency-neutral module so `render.py` can return it and `cost.py` can consume it without importing each other cyclically. Do not retain words, raw full text, image bytes, API keys, or persistent source paths in exported estimate diagnostics.

### 8.2 Image estimate algorithm

For every page and every vision-stage model:

1. Resolve image count using the actual grid plus overview.
2. Resolve target using `tiling.target_long_edge_px()` with the current vector/raster/few-image policy. Preserve the ≤20-image branch and override restrictions.
3. Generate overview dimensions and every tile rectangle using existing geometry helpers and the selected overlap.
4. Compute zoom per rectangle with `zoom_for_rect()` and estimated pixel dimensions. Document rounding assumptions; use rendered-fixture comparisons to set a defensible tolerance.
5. Estimate tokens through `core.tokenizer.estimate_image_tokens()` for that stage's model. The same PNG dimensions can produce different model-tier estimates.
6. Include every tile in the planning estimate unless safe suppression has actually been measured. Do not predict blank tiles from vector-word absence.
7. For unknown classification, calculate explicit vector/raster scenarios or retain the conservative fallback; never label unknown as vector.
8. For invalid geometry, use a clearly reported fallback or unavailable estimate. Do not drop the page's cost silently.

Factor the geometry arithmetic once. GUI, command-line estimation, and tests should use the same helper, not independently copied formulas.

### 8.3 Cost scenarios and accounting

Represent estimates as planning scenarios with their assumptions. Retain backward-compatible existing fields or make any intentional API change explicit and update all callers. Do not overload `low_cost`/`high_cost` with undocumented new meanings.

At minimum, expose:

- Geometry-aware planning estimate when page metadata is available.
- Conservative planning scenario/fallback when metadata or cache-hit behavior is uncertain.
- Whether estimates assume cold local result caches.
- Models, transports, critique run count, prompt/output assumptions, and pricing verification date.
- Unknown-priced stage names and any fallback basis.

Use `core.pricing` rate helpers, including cache-write TTL multipliers, rather than duplicating dollar constants in the GUI or harness. Estimate digest and critique imagery independently by resolved model. Resolve critique run count through the runtime's existing resolver instead of fixing the arithmetic at two when an override is in effect.

Use runtime stage resolvers in **both** standard and exhaustive estimates. In particular, `estimate_drawing_set_cost()` currently prices synthesis/focus using its digest `model` argument. A Sonnet digest with independently selected Opus synthesis/focus must price each stage correctly; an unknown-priced active synthesis/focus stage must make the standard total unavailable, just as in exhaustive mode. Do not apply charges for an optional stage that will not execute.

For a real-time critique prefix with `n >= 2` identical sequential reads and the existing five-minute breakpoint:

- Successful-reuse scenario: one 1.25× prefix write plus `(n - 1)` 0.1× reads.
- No-reuse scenario: `n` 1.25× prefix writes, when each marked request misses.
- A single read without the prefix breakpoint is ordinary input under the present implementation.
- Price uncached suffix/input and each output separately. Do not discount output with an input-cache multiplier.

If the actual request policy changes, resolve it from that policy rather than keeping these formulas detached. For the current batch implementation, price ordinary batch input and outputs without assumed cache hits. Server tools and all synchronous stages keep their own rate rules.

Count known capped sheet-text input separately from fixed system/instruction overhead. Character-based token estimates are approximate; identify the heuristic. Do not call a tokenizer that downloads data or a provider endpoint during preflight. Unknown text length must remain an explicit assumption.

Specification-cache estimates must acknowledge possible concurrent first writers and TTL expiry. A simple documented reuse/no-reuse scenario is preferable to inventing an empirical probability without data.

### 8.4 Pure test matrix

- Default vector E/D/B/A shapes and non-square aspect ratios.
- Raster sheet classification; unknown classification fallback.
- 6×6, 5×5, 3×3, and 2×2 grids, including the ≤20-image target branch.
- Overlap zero, shipping overlap, and an explicit experimental overlap.
- Vector target override and the fact that it does not override raster/few-image targets.
- Rotated displayed dimensions; nonzero CropBox fixture where actual rendered dimensions are compared.
- Hi-res digest model with non-hi-res critique model and the reverse.
- Standard mode with independently overridden synthesis/focus models, including an unknown-priced active stage and an inactive optional stage.
- Different critique run counts and corresponding prefix-cache policy.
- Economy, Hybrid, Fast, and explicit mixed transports.
- Short, long, absent, and unknown sheet text; specification text by transport.
- Unknown price propagation; no partial sum presented as the whole total.
- Output and synchronous-stage charges not batch/cache-discounted incorrectly.
- A pricing multiplier change in the central helper changes all applicable previews consistently.

Use dimensional and arithmetic invariants, not large string snapshots. Keep a few hand-calculated examples for independence from the implementation. Rendered fixture tests should validate rounding and conservative allowances, not demand the exact pre-render estimate equal every rasterized pixel count.

## 9. WP-03B: integrate estimates without freezing the GUI

### 9.1 Metadata collection

Current `_refresh_summary()` and `_on_process()` call `render.list_sheets()`, primarily a page-count operation. Do not replace every refresh with a synchronous full-text scan.

`list_sheets()` still opens PDFs. Once background PDF inspection exists, move page counting under the same serialized ownership boundary too. Summary and confirmation should consume immutable counts from the current selected-file snapshot; they must not open PDFs on the Tk thread while another preflight is active or block Tk on a contended PDF lock. For a new selection with no counts yet, show that the estimate is being prepared.

Add or reuse a lightweight scanner inside `render.py` that emits `SheetCostBasis` records without rasterizing, creating model clients, hashing full render dependency graphs, or retaining PDF objects after the operation. Determine vector/raster classification consistently with rendering; do not equate any nonempty raw text with nonempty extracted words if the renderer uses the latter.

Run richer inspection on a bounded background job following the GUI's existing `_refresh_profile_suggestions()` / `_apply_profile_suggestions()` generation-guard patterns. Coordinate with the existing `_preflight_lock`; preferably share the preflight operation/results instead of adding a second independent PDF worker. `profiles.preflight_sheet_ids()` already obtains geometry through `iter_sheet_prescan()`, so reuse a suitable existing result when available without forcing expensive render-dependency hashing solely for pricing. Use one PDF-engine owner at a time. Never share live documents/pages between threads or overlap metadata PDF access with the analysis pipeline's PDF access.

Maintain a run-local/in-memory result associated with the selected files and inspection generation. On selection change, discard stale results. Lightweight file stats can invalidate a display cache but are not cryptographic evidence identities; do not reuse this cache for analysis correctness.

### 9.2 GUI state transitions

1. Selection changes: display a count-based conservative estimate immediately only when current-snapshot counts already exist; otherwise show a pending estimate and obtain counts through the serialized worker. Schedule or reuse metadata inspection.
2. Current-generation inspection succeeds: update the summary on the Tk thread with the improved planning estimate.
3. Inspection partially fails: show the fallback basis for affected pages; retain a useful preview.
4. Selection/options change during inspection: ignore stale result and recompute from current options/available metadata.
5. Analyze selected: snapshot files/options as today, obtain a consistent estimate or clearly labeled fallback, and present the existing confirmation.
6. Analysis begins: ensure metadata work cannot concurrently access PDFs. Stop/join or serialize through the established ownership mechanism without a long blocking wait on the Tk thread.
7. Window closes/cancels: release documents, worker resources, and pending UI callbacks safely.

Do not add a persistent metadata database, new network preflight, or automatic paid probe.

### 9.3 User-facing wording

Use plain language such as “Estimated cost” and “Conservative planning estimate.” State that detail, generated findings, retries, and cache reuse affect actual cost. Do not label a hypothetical range as a statistical confidence interval or guaranteed maximum.

Keep implementation details out of the primary confirmation. A compact assumptions line can state page information available, transport, and expected cache behavior. Retain per-stage model attribution for exhaustive mode.

### 9.4 Validation

Test pure state/generation logic with fake workers and callbacks where possible. Add a small Windows manual acceptance checklist covering rapid file replacement, option toggling, pending scan at Analyze, damaged PDF, cancellation, and window close. Verify that no request/upload occurs before the existing confirmation and that analysis cannot overlap PDF-engine access with preview scanning.

Include rapid selection changes and summary refreshes during a scan, instrumenting page-count access as well as text extraction. A test that serializes only the new scanner while permitting `list_sheets()` concurrently does not establish safe PDF ownership.

## 10. WP-04: extend the existing A/B harness for auditable experiments

### 10.1 Preserve actual usage by stage

`summarize_run()` already records per-family token/call totals but omits family dollar costs available from `RunUsage.by_family()`. Extend the existing JSON summary rather than building another benchmarking system.

Record:

- Per-family and per-model cost, tokens, and calls.
- Transport breakdown, cache-read/write tokens, requested write TTL when applicable, and unknown-price status.
- Successful responses, failed attempts, non-billable abandoned attempts, and local cache hits where those distinctions are actually recorded, without conflating them into one “paid calls” number.
- Actual resolved stage models, run mode, transports, grid/overlap/target policy, prompt versions or existing request-contract identifiers, and source composition.
- Relevant status/completeness fields; an incomplete arm cannot be treated as a comparable cost win.

Prefer serializing the existing sanitized usage records or canonical aggregations. Do not create a second independent billing calculator. Preserve `None` for unknown costs.

The current pipeline aggregates some verification work into one usage record. Record counts are therefore not universally individual API-call counts. Label aggregation granularity and unavailable attempt counts explicitly; do not expand this package into a rewrite of every stage's telemetry or invent precise call counts from aggregated tokens.

### 10.2 Finding-level comparison artifacts

Before the temporary arm workspace is deleted, persist compact finding records alongside its summary. Include source identity/page, sheet ID, category, severity, finding text, source quote, all cross-sheet legs, anchor tiers/rectangles, confidence, verification disposition, and provenance. Preserve original finding IDs as references.

Do not use `QC-###` as a stable identity: numbering is positional. Do not assume `Finding.id` alone is sufficient: the reviewed implementation hashes only a subset of finding attributes and is sensitive to quote wording. Two conflicts sharing a primary quote may have different secondary legs.

Use deterministic matching tiers:

1. Exact comparable finding/leg identity with compatible critical attributes.
2. Candidate matches for human review when wording differs but source/geometry/legs suggest overlap.
3. Explicit unmatched baseline findings, unmatched variant findings, and ambiguous many-to-many candidates.

Only the first tier may be called an exact match. Do not automatically delete unmatched items, stamp semantic equivalence using a loose fuzzy score, or ask another paid model to adjudicate by default. Keep source correspondence stable within the same input set and separate from absolute paths.

Preserve human-review navigation. If artifact links are emitted, copy the needed existing artifacts before temporary cleanup and use portable relative links. Do not emit links into a deleted temporary directory. Keeping a full duplicate reviewed PDF/evidence tree is optional; compact JSON plus source/page references is the minimum required output.

### 10.3 Correct the quality-screen interpretation

Keep the existing aggregate signals as warning indicators, but change claims that a falling count **proves** real defects went unseen. A count drop can reflect missed defects, noise removal, dedup behavior, or model variance. A flat count can hide replacement of a real issue by another false positive.

Report a large count drop as a review requirement. Preserve existing threshold behavior unless a separate measured justification changes it. “No concerns detected” must remain distinct from “quality approved.” Use the `confidence` enum for the critique self-consistency statistic; do not silently substitute the legacy cross-family `reproduced` boolean.

Add an explicit comparison-validity status for failed/partial arms, mismatched retained-sheet populations, and missing cost data. Present their diagnostics, but do not advertise their lower total as comparable savings.

### 10.4 Explicit geometry controls for experiments

Keep existing environment-based `--baseline` and `--variant` syntax compatible. Add typed per-arm overlap options, preferably `--baseline-overlap` and `--variant-overlap`, forwarded to both estimate-only and execution children as the same `overlap_frac` pipeline argument.

Validate finite numbers and a documented supported range before any costly work. Reject NaN/infinity rather than allowing them into tiling or cache keys. Preserve the shipping overlap when omitted. Record resolved values, not only the command-line spelling.

The existing render identity serializes overlap to four decimal places (`render.py`, `f"overlap={overlap_frac:.4f}"`). Restrict new harness overlap values to at most four fractional decimal places, rejecting finer precision rather than silently rounding, unless a separately reviewed identity-contract fix makes finer values distinct. Otherwise two different rendered overlaps could share a level-one key. This restriction does not certify every existing direct API caller; record the broader precision issue separately if needed.

The same-configuration guard must compare effective reviewed parameters as well as environment overrides. A changed irrelevant environment variable is not a meaningful experiment, and an overlap-only change must not be incorrectly rejected as identical. Include intended options in the shared arm specification; do not use an unrestricted snapshot of the entire environment as the experiment identity.

Do not add production per-sheet adaptive grids here. Explicit run-level grid options may be added only if needed for the documented experiment and routed through the same estimate/execution contract; they must not bypass the current target policy.

### 10.5 Required tests

- Per-family costs reconcile with existing run totals for complete priced records.
- Unknown prices, zero use, cache-only stages, retries, and non-billable attempts remain distinguishable.
- Existing summary fields continue to load; version new experiment output contracts if needed.
- Same finding after positional renumbering is comparable; identical primary quote with different secondary legs is not collapsed.
- Changed quantities/tags/polarity cannot become an exact match merely because geometry overlaps.
- Identical count/mix with one baseline finding replaced still exposes the unmatched records.
- Ambiguous candidate matches remain explicitly unresolved.
- Partial or failed arms do not receive a comparable-savings verdict.
- Overlap reaches both estimate and actual pipeline kwargs; omitted values retain defaults.
- Invalid numeric arguments, including unsupported overlap precision, fail before child execution; equivalent configurations are rejected consistently. Distinct accepted overlaps produce distinct relevant render/cache identities.
- Saved links, if included, resolve after temporary arm cleanup.
- No raw environment secret appears in console, JSON, or Markdown/text comparison output.

## 11. WP-05: repository documentation and focused editing

Update `README.md`, `CLAUDE.md`, `docs/PERFORMANCE_AND_COST_VALIDATION.md`, affected docstrings, and the appropriate changelog section. Do not rewrite the historical external brief in Downloads; record corrected decisions in maintained repository documentation.

Required corrections:

1. Explain capped prompt text, full host evidence text, and complete word-coordinate text as distinct representations with explicit consumers.
2. Document the sharded grounding fix and scoped cross-QC cache invalidation. Note that recovered findings can increase downstream cost.
3. Explain cold render reuse through the spool and the fallback case; remove the statement that every cold exhaustive run necessarily rasterizes twice.
4. Distinguish three vision reads from three full-price image reads; explain actual cache usage records determine cost.
5. Replace guaranteed/“slightly high” invoice claims with explicit planning assumptions and fallback basis.
6. Describe batch specification input accurately in both cost dialogs and help text.
7. Document model-variant estimates resolving in their own processes, with no claim that changing an imported default dynamically works.
8. Describe the few-image 2576 target branch and the limited scope of the vector-target override.
9. Present overlap savings as approximate preservation of interior resolution, with reduced edge/overview resolution and changed boundary context.
10. Correct quality-screen claims: counts, anchoring, and agreement are warnings, not a recall oracle. Document finding-level review outputs.
11. Distinguish the critique `confidence` field from the legacy `reproduced` boolean. Do not migrate behavior while correcting prose.
12. Use project-adopted edition wording consistently; do not describe “latest” as a substitute for evidenced adoption.
13. Fix stale predecessor-product terminology in touched docstrings when it obscures actual behavior. Do not delete unused public helpers merely because the brief calls them dead.
14. Describe the current uncertainty-to-investigation path accurately; avoid the stale claim that only CRITICAL/HIGH UNVERIFIED entries are eligible.

Re-derive cost examples through the updated pure estimator. Label formula examples separately from observed runs. Do not update `PRICING_EFFECTIVE_DATE` just because this document is newer; change it only after verifying the actual rate table against official pricing.

## 12. WP-06: integration, review, and acceptance

### 12.1 Focused test groups

Run tests appropriate to each package while implementing. The following PowerShell examples assume the repository virtual environment has been verified to use a supported interpreter:

```powershell
# Evidence retention, grounding, cache, and render reuse
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_drawing_models.py tests/test_drawing_render.py tests/test_drawing_anchor.py tests/test_drawing_cross_qc.py tests/test_drawing_stage_cache.py tests/test_drawing_cache_identity.py tests/test_render_spool.py

# Estimation, geometry, configuration parity, and experiment records
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cost.py tests/test_ab_sweep.py tests/test_drawing_tiling.py tests/test_drawing_tokens.py tests/test_drawing_cost_optimization.py tests/test_model_capabilities.py

# Integration and unchanged request/receipt contracts
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_drawing_digest.py tests/test_drawing_critique.py tests/test_drawing_batch.py tests/test_drawing_batch_critique.py tests/test_drawing_qc_pipeline.py tests/test_drawing_acceptance.py tests/test_drawing_usage.py tests/test_import_isolation.py
```

If a listed suite has moved, use its current equivalent. Do not run all groups repeatedly without a new change or failure justifying it.

After integration, run the full hermetic suite with network tests explicitly excluded, plus applicable release checks:

```powershell
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not network and not browser"
& .\venv\Scripts\python.exe scripts/benchmark_drawing_analyzer.py --check --sheets 8 --repeats 5
```

Run acceptance with network tests explicitly excluded in its child environment. At the reviewed commit, `run_acceptance.py` invokes an unfiltered `pytest -q` internally, and an inherited real API key can enable the live canary. The filtered pytest command above does not protect that separate invocation. This PowerShell example isolates the acceptance child without changing persistent or parent environment settings:

```powershell
@'
import os
import subprocess
import sys

acceptance_env = os.environ.copy()
acceptance_env.pop("ANTHROPIC_API_KEY", None)
acceptance_env["PYTEST_ADDOPTS"] = '-m "not network"'
raise SystemExit(subprocess.call(
    [sys.executable, "scripts/run_acceptance.py"],
    env=acceptance_env,
))
'@ | & .\venv\Scripts\python.exe -
```

Inspect the current acceptance script before execution and use its documented hermetic mode if its interface has changed. Record actual output, including skips and environment failures. Run the existing browser-security gate when report generation changes or as the normal release gate; do not represent a skipped browser suite as passing.

The eight-sheet benchmark checks existing mechanical regressions. It does not replace WP-01's separate dense-text memory/scaling measurement. Record that dense fixture's size, page count, repeated-run timings, and peak retained memory separately; do not claim the stock benchmark establishes those properties.

The reviewed CI matrix is Linux Python 3.11/3.12 and Windows Python 3.11; the external brief described a broader Cartesian matrix. Use the actual workflow and document any separately run Windows/Python coverage. Retain existing correctness lint, dependency/license checks, wheel build, and installation smoke as release gates. This work does not itself require dependency changes.

### 12.2 Independent review checklist

- [ ] The original tail-evidence failure was demonstrated before the fix.
- [ ] Real tail evidence survives; fabricated or wrong-sheet evidence still fails.
- [ ] All cold, prescan, and spool paths carry the new field.
- [ ] Prompt bytes and production quality defaults remain unchanged in immediate packages.
- [ ] Cross-QC cache keys change for both acceptance-contract revision and tail-only evidence changes.
- [ ] Unaffected digest/critique caches remain valid; no indiscriminate schema bump was used. Dense cross-QC cases retain existing budget degradation and cache ineligibility.
- [ ] Estimates and execution resolve identical stage models, transport, and geometry options.
- [ ] Image counts are model-tier aware; pricing distinguishes input, output, cache, and batch correctly.
- [ ] Estimates never present partial known prices as a complete total or a planning bound as a guarantee.
- [ ] GUI metadata scanning cannot freeze ordinary interaction or race the analysis PDF access.
- [ ] A/B records expose unmatched/ambiguous findings and incomplete arms.
- [ ] Finding counts and agreement rates are not asserted to prove recall.
- [ ] Full text does not leak into logs or unbounded model/report context.
- [ ] Existing deterministic ordering, provenance, ledger lifecycle, and saved-PDF receipt checks pass.
- [ ] Documentation reflects the implementation and clearly separates measured from hypothetical savings.

### 12.3 Release evidence

Provide a concise implementation report with changed behavior, before/after regression examples, tests and environments, cache invalidation scope, performance observations, new estimate assumptions, and remaining deferred questions. Include Windows manual GUI results if WP-03B is implemented. Do not claim cost or quality improvement from hermetic fake-client tests.

Use small package commits so a defective GUI estimate enhancement can be reverted without reverting the evidence fix. Reverting the evidence fix requires preserving a contract revision that cannot load incompatible cached results. Do not downgrade a cache contract counter to an older acceptance meaning.

## 13. Measurement packages: no default changes before evidence

The immediate corrective release can complete without a paid experiment. The packages below are subsequent research decisions, not hidden release blockers. Reuse the improved A/B harness and existing benchmark/release record process.

### 13.1 Common experiment protocol

1. Select approved representative drawings and record their composition: E/D/letter/detail, vector/raster/hybrid, dense schedules, reduced-format drawings, faint linework, tile-boundary symbols, and cross-sheet conflicts.
2. Include a >40-readable-sheet case for the corrected sharded path and a smaller control set. Keep a stable set of human-confirmed important findings.
3. Record the exact baseline and variant configuration, prompt contracts, model IDs, pricing date, source identities, and transports before execution.
4. Estimate both arms using corrected process resolution; obtain the intended run budget and dataset scope before launching paid work.
5. Run each arm with an independent cold local result cache. Provider prompt caches are separate and cannot be presumed cold; inspect their reported read/write usage and record order effects.
6. Change one intended factor at a time. If two factors are intentionally coupled, such as target and overlap to preserve interior resolution, identify that compound experiment explicitly.
7. Use repeated runs where variance matters. Start with a small pilot; determine further repetitions from observed variability and budget. Do not report one run as statistically conclusive.
8. Compare stage costs, retained-sheet populations, completion status, finding identity/candidate matches, severity, anchors, verification, and critique confidence.
9. Have a qualified reviewer assess baseline-only and ambiguous important findings. Record confirmed retention/loss for known defects separately from unknown unmatched findings.
10. Reject promotion when an important confirmed defect is lost or a material unexplained omission remains. Fewer false positives can be beneficial only when the removed items are actually adjudicated as noise.
11. Store the decision and limitations. A clean automatic screen is not approval to change defaults.

A dense >40-entry case may remain partial because the existing cross-QC text budget omits input. Use that case to verify recovered evidence and report diagnostic observations. Even if both arms have the same degradation, it cannot satisfy the complete-arm cost/quality promotion gate. Use an additional eligible complete case for that comparison; never relax completeness to make an optimization study look successful.

### 13.2 R-01: Sonnet digest with Opus critique

Priority: first model-cost experiment after tooling is trustworthy.

Use existing routing. In the environment-based harness, set the global digest default to Sonnet and explicitly keep critique and cross-QC on Opus before the child imports application modules. Resolve and compare every other stage too; if another stage inherits the global default, pin it so the experiment remains digest-only. The public `model=` parameter is another valid entry point.

Measure digest transcription, digest-origin findings, downstream cross-QC effects, and known-defect retention. The nominal 60% per-token rate reduction on the digest is not guaranteed stage savings: tokens, thinking, retries, and findings can change. Capability flags prove request compatibility, not equal quality. No new digest environment variable is prerequisite.

### 13.3 R-02: overlap/target rebalance

Compare shipping 8%/1560 against 4%/1452 only after WP-04 passes effective-configuration tests. With E-size source-formula estimates, image tokens fall from 92,871 to 80,409 (13.42%). Interior DPI is approximately preserved; edge DPI falls about 3.34% and overview DPI about 6.92%.

Inspect boundary-straddling symbols, detail bubbles, match lines, thin text, and reduced-format sheets. The target override changes vector sheets only, while a run-level overlap argument also affects raster sheets; stratify results and do not describe raster evidence as unchanged. Retain raster target protections. Document any decision to keep production raster overlap unchanged in a future design.

### 13.4 R-03: per-sheet adaptive grids

Priority: after R-01/R-02 measurements; requires its own design review.

Do not call this low risk merely because page rectangles remain covered. A letter-size PDF may be a reduced large-format drawing; physical DPI alone is insufficient evidence of legibility.

If pursued, specify a per-sheet policy that jointly selects rows, columns, and target, rather than changing grid alone and accidentally entering the 2576 few-image branch. Validate content legibility across interior and edge tiles. C-size 3×3 at 1560 can fall below 180 DPI in the interior.

Trace resolved per-sheet parameters through rendering, prescan identities, digest/critique keys, spool reuse, label validation, omitted-tile disclosure, anchor geometry, batch reuse, telemetry, and cost preview. Several data models already carry per-sheet rows/cols/overlap; preserve those contracts rather than rebuilding them. Define changed-sheet cache invalidation and prove unchanged E-size sheets retain compatible keys if their requests are identical.

Use the corrected mixed-set arithmetic in section 2 as a hypothesis. Actual savings require the real sheet mix, suppression, and usage. No adaptive default is included in the immediate work.

### 13.5 R-04: larger model text budget or broader full-evidence consumers

First measure how often truncation occurs, by sheet type, and inspect known lost information. WP-01 fixes host validation without increasing model prompts. A larger cap is a separate experiment.

Any move of full evidence into identity/citation/model prompts must preserve bounded context and re-evaluate request/cache identities. Separate deterministic source validation from model-visible corpus expansion. For edition checks, retain evidence quotes, source identity, and adopted-edition semantics; do not infer adoption from every code citation in a newly exposed tail.

Do not infer “25× cheaper per unit of information” from a text-vs-image token ratio. They represent different information, and token cost does not establish equivalent evidence content.

### 13.6 R-05: batch first-pass verification

First extract actual verification cost from the usage ledger. Finding count is not paid-call count: deterministic/unanchored/cache-hit entries differ, and cross-sheet verification has another path. The later investigation loop is adaptive and remains a separate stage.

If eligible first-pass verification is material, design batch submission, result binding, partial failure, cancellation, bounded waiting, retry accounting, crop/file cleanup, and preservation of NOT_VISIBLE → UNCERTAIN semantics. Measure added disposition latency. A 50% token discount on eligible calls is not a 50% run saving. Do not add this transport speculatively in the corrective release.

### 13.7 R-06: shared digest/critique prefix

Measure current real-time cache-hit rates and the population of real-time exhaustive runs before spending engineering effort. Compare against 2.35 successful-hit image-read equivalents, not an assumed three full-price reads.

Changing system/persona placement alters prompts and can change review quality. Investigate common prefix identity, thinking/effort compatibility, source-text/image ordering, TTL, stage timing, and specification/profile differences. Batch caching is supported by the provider on a best-effort basis; the current application simply does not organize those requests to rely on it.

At three total reads, the one-hour shared-prefix proposal has only a 6.4% image-component advantage over the current successful-cache case. Do not restructure the pipeline around the original brief's 27% claim.

## 14. Explicit non-goals and rejected shortcuts

- Do not accept any quote found only in model output, another sheet, or a manufactured joined string to repair grounding.
- Do not remove cross-QC grounding checks or weaken fuzzy anchoring thresholds.
- Do not change two identical critique reads into digest-plus-critique while retaining the same confidence label semantics.
- Do not replace all `except Exception` guards with `except BaseException`, or dismiss a native panic as safe to continue without a concrete boundary analysis.
- Do not assume `tiktoken.count_tokens` is a current production hot path; the review found no production callers of those helpers.
- Do not infer a tile is empty from absence of words/vector operations or enable the near-blank heuristic by default.
- Do not change image format to claim token savings; current token estimation is dimensional. Compression can affect transport or quality, which are different questions.
- Do not shrink the overview or lower output caps as an unmeasured cost fix.
- Do not broadly rename defaults, remove unused compatibility APIs, split the GUI/report generators, or add a build system as incidental cleanup.
- Do not replace existing A/B and benchmark tools with a parallel evaluation framework.
- Do not claim full artifact byte equality between cold and warm runs whose journals/usage legitimately differ; compare the appropriate content and deterministic assembly contracts.
- Do not treat PDF-import isolation as a newly established legal conclusion. Preserve the existing project boundary and licensing policy.
- Do not update dependencies based solely on unfamiliar package names in the external brief.
- Do not adjust global schema versions, prompt hashes, model defaults, or pricing dates without a specific changed contract.

## 15. Ready-to-use agent assignments

### Evidence implementer

Implement WP-01 after WP-00 reproduction. Own models/render/spool and cross-QC changes. Preserve all model prompt text and quality defaults. Add complete host evidence with explicit unavailable/empty semantics, fix the two sharded validation paths, and scope invalidation to cross-QC with full-evidence identity. Prove true-tail acceptance, false-quote rejection, cold/warm/spool parity, prompt stability, and unaffected digest-cache reuse. Report any broader text-consumer issue separately instead of expanding scope silently.

### Cost and harness implementer

Implement WP-02, WP-03A, then WP-04. Resolve estimate arms in the same fresh-process environment as execution. Correct specification-cache wording. Add optional shape-aware pure estimates with stage-specific model tiers and explicit cache scenarios. Preserve legacy conservative helper semantics. Extend existing A/B outputs with reconciled stage costs and finding-level review records, then add explicit overlap controls. Do not change production routing or quality defaults. Coordinate shared model/render interfaces with the evidence implementer before editing them.

### GUI implementer

Implement WP-03B only after pure cost interfaces settle. Collect local metadata without rasterization or provider access. Keep Tk responsive, reject stale results, and serialize PDF-engine ownership with analysis. Preserve existing confirmation and cancellation behavior. Report manual Windows outcomes and any fallback paths. Avoid a general GUI refactor.

### Independent reviewer/integrator

Review behavior against this plan rather than accepting passing snapshots as proof. Focus on tail-evidence false negatives, cache-key omissions, prompt changes, model/transport estimate mismatch, stale asynchronous metadata, secret exposure, and invalid A/B matching. Finalize WP-05 documentation and WP-06 evidence. Verify that research-only decisions have not entered shipping defaults. Report exact remaining gaps and the release scope that actually passed.

## 16. Completion criteria

The full immediate plan is complete when WP-01 through WP-06 are implemented and reviewed, meaningful regressions pass, the full applicable hermetic/release checks are recorded, Windows behavior is verified for GUI changes, and the owner has a clear statement of cache consequences and deferred experiments. WP-01 and WP-02 may ship independently as earlier corrective increments; describe such an increment as a partial delivery of this plan, not completion of every package.

Paid research and default changes are separate deliverables. Do not hold the grounding fix indefinitely for an optimization study, and do not promote an optimization merely to mark every research row complete.

## 17. References

- Repository baseline: `89c8ecb`; function names and tests cited throughout this document.
- External input: `drawing-analyzer_REVIEW_BRIEF.md`, supplied by the owner; several claims corrected above.
- [Anthropic model and cache pricing](https://platform.claude.com/docs/en/about-claude/pricing) — checked during the 2026-09-08 review; recheck before relying on rates in a later release.
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — prefix identity, TTL multipliers, and best-effort batch support.
- [Anthropic batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing) — provider batch behavior; distinguish it from current application policy.
- Existing repository qualification process: `docs/PERFORMANCE_AND_COST_VALIDATION.md`, `docs/RELEASE_ACCEPTANCE_TEMPLATE.md`, `docs/WINDOWS_ACCEPTANCE.md`, `.github/workflows/ci.yml`.
