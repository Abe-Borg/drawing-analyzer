# Measurement packages and standing prohibitions

Extracted from `REVIEW_IMPLEMENTATION_PLAN.md` when that document was retired.
The plan's implementation packages (WP-00 … WP-08) are complete and merged —
what they changed is recorded in `CHANGELOG.md`, and what was verified in
`REVIEW_RELEASE_EVIDENCE.md`. The two sections below did **not** retire with it:

- **The measurement packages have not been run.** They need approved drawing
  sets and a budget, and none of them has billed anything. They are subsequent
  research decisions, not release blockers — but the protocol for running them
  honestly is worth keeping, because the failure modes it guards against (one
  run reported as conclusive, two factors changed at once, a provider cache
  presumed cold) are the ones that produce confident wrong answers.
- **The prohibitions are standing.** Each records a shortcut that was
  considered and rejected for a reason, usually a reason discovered the
  expensive way. They apply to future work, not just to the packages that
  are done.

The plan itself remains in git history at `168f4ec` if the full reasoning
behind a decision is ever needed.

---

## 1. Measurement packages: no default changes before evidence

The immediate corrective release can complete without a paid experiment. The
packages below are subsequent research decisions, not hidden release blockers.
Reuse the improved A/B harness and existing benchmark/release record process.

**Ordering:** R-04's zero-call half is `scripts/measure_evidence_coverage.py`,
which is implemented and runs first; its measured half precedes R-01 and R-02, because it bounds review quality
rather than cost.

### 1.1 Common experiment protocol

1. Select approved representative drawings and record their composition:
   E/D/letter/detail, vector/raster/**hybrid**, dense schedules, reduced-format
   drawings, faint linework, tile-boundary symbols, and cross-sheet conflicts.
2. Include a >40-readable-sheet case for the corrected sharded path, a case
   containing textless and hybrid sheets, and a smaller control set. Keep a
   stable set of human-confirmed important findings.
3. Record the exact baseline and variant configuration, prompt contracts, model
   IDs, pricing date, source identities, and transports before execution.
4. Estimate both arms using corrected process resolution; obtain the intended run
   budget and dataset scope before launching paid work.
5. Run each arm with an independent cold local result cache. Provider prompt
   caches are separate and cannot be presumed cold; inspect their reported
   read/write usage and record order effects.
6. Change one intended factor at a time. If two factors are intentionally
   coupled, such as target and overlap to preserve interior resolution, identify
   that compound experiment explicitly.
7. Use repeated runs where variance matters. Start with a small pilot; determine
   further repetitions from observed variability and budget. Do not report one
   run as statistically conclusive.
8. Compare stage costs, retained-sheet populations, completion status, finding
   identity/candidate matches, severity, anchors, verification, evidence-trust
   composition, and critique confidence.
9. Have a qualified reviewer assess baseline-only and ambiguous important
   findings. Record confirmed retention/loss for known defects separately from
   unknown unmatched findings.
10. Reject promotion when an important confirmed defect is lost or a material
    unexplained omission remains. Fewer false positives can be beneficial only
    when the removed items are actually adjudicated as noise.
11. Store the decision and limitations. A clean automatic screen is not approval
    to change defaults.

A dense >40-entry case may remain partial because the existing cross-QC text
budget omits input. Use that case to verify recovered evidence and report
diagnostic observations. Even if both arms have the same degradation, it cannot
satisfy the complete-arm cost/quality promotion gate. Use an additional eligible
complete case for that comparison; never relax completeness to make an
optimization study look successful.

### 1.2 R-04: text budget and evidence coverage (**now first**)

`scripts/measure_evidence_coverage.py` supplies the zero-call half — how often
truncation occurs, by sheet type, plus the textless/hybrid population and the
surviving-finding anchor-tier distribution — and states in its own output what
it cannot see. The **discard rate** needs one instrumented run and is the only
item here that bills; it has never been run. The
remaining paid work inspects what was actually lost and whether a larger model
text budget recovers it.

WP-03 fixes host validation without increasing model prompts. A larger cap is a
separate experiment. Any move of full evidence into identity/citation/model
prompts must preserve bounded context and re-evaluate request/cache identities.
Separate deterministic source validation from model-visible corpus expansion. For
edition checks, retain evidence quotes, source identity, and adopted-edition
semantics; do not infer adoption from every code citation in a newly exposed
tail.

Remember that cross-QC's input is the digest prose **plus** the budgeted text
layer (README, "Host evidence vs. prompt text"). The 4,000-character budget
bounds direct source-text evidence, not
the stage's whole information input; frame the experiment accordingly.

Do not infer "25× cheaper per unit of information" from a text-vs-image token
ratio. They represent different information, and token cost does not establish
equivalent evidence content.

### 1.3 R-01: Sonnet digest with Opus critique

Priority: first model-cost experiment after tooling is trustworthy and WP-02's
measurements are in hand.

Use existing routing. In the environment-based harness, set the global digest
default to Sonnet and explicitly keep critique and cross-QC on Opus before the
child imports application modules. Resolve and compare every other stage too; if
another stage inherits the global default, pin it so the experiment remains
digest-only. This is the `REVIEW_MODEL_DEFAULT` fallback chain: five stage
resolvers read `os.environ.get(<their own var>) or REVIEW_MODEL_DEFAULT`, which
binds at *import*, so setting `DRAWING_ANALYZER_MODEL` in the parent moves none
of them (docs/PERFORMANCE_AND_COST_VALIDATION.md, on why `--estimate` crosses a
process boundary). `tests/test_ab_sweep.py` pins that the harness reports it
honestly. The public `model=` parameter is another
valid entry point.

Measure digest transcription, digest-origin findings, downstream cross-QC
effects, and known-defect retention. The nominal 60% per-token rate reduction on
the digest is not guaranteed stage savings: tokens, thinking, retries, and
findings can change. Capability flags prove request compatibility, not equal
quality. No new digest environment variable is prerequisite.

### 1.4 R-02: overlap/target rebalance

Compare shipping 8%/1560 against 4%/1452 only after WP-06 passes
effective-configuration tests. With E-size source-formula estimates, image tokens
fall from 92,871 to 80,409 (13.42%). Interior DPI is approximately preserved;
edge DPI falls about 3.34% and overview DPI about 6.92%.

Inspect boundary-straddling symbols, detail bubbles, match lines, thin text, and
reduced-format sheets. The target override changes vector sheets only, while a
run-level overlap argument also affects raster sheets; stratify results and do
not describe raster evidence as unchanged. Retain raster target protections.
Document any decision to keep production raster overlap unchanged in a future
design.

### 1.5 R-03: per-sheet adaptive grids

Priority: after R-04/R-01/R-02 measurements; requires its own design review.

Do not call this low risk merely because page rectangles remain covered. A
letter-size PDF may be a reduced large-format drawing; physical DPI alone is
insufficient evidence of legibility — and physical page size does not enter the
token estimate at all (docs/PERFORMANCE_AND_COST_VALIDATION.md, "Two
image-token regimes": same aspect ratio, same tokens at any physical size), so a cost model cannot be used as a legibility proxy.

Both target regimes must be modeled. In the >20-image regime cost scales with
aspect ratio and target; in the ≤20-image regime most images clamp to the model
token cap, so cost is essentially image count. An E-size sheet at 3×3 costs
10 × 4,784 = 47,840 tokens with interior tile resolution falling from about 183
to about 151 DPI. Specify a per-sheet policy that jointly selects rows, columns,
and target rather than changing grid alone. C-size 3×3 at 1560 can fall below
180 DPI in the interior.

Trace resolved per-sheet parameters through rendering, prescan identities,
digest/critique keys, spool reuse, label validation, omitted-tile disclosure,
anchor geometry, batch reuse, telemetry, and cost preview. Several data models
already carry per-sheet rows/cols/overlap; preserve those contracts rather than
rebuilding them. Define changed-sheet cache invalidation and prove unchanged
E-size sheets retain compatible keys if their requests are identical.

As a hypothesis, use the real-time exhaustive image arithmetic: one digest read
at full price, plus a critique cache write at 1.25x and a critique cache read at
0.1x, is **2.35 full-price reads** per sheet, not three. Actual savings
require the real sheet mix, suppression, and usage. No adaptive default is
included in the immediate work.

### 1.6 R-05: batch first-pass verification

First extract actual verification cost from the usage ledger. Finding count is
not paid-call count: deterministic/unanchored/cache-hit entries differ, and
cross-sheet verification has another path. The later investigation loop is
adaptive and remains a separate stage. Note that WP-03B deliberately increases
the anchored population, so re-derive this after it lands rather than from
pre-fix data.

If eligible first-pass verification is material, design batch submission, result
binding, partial failure, cancellation, bounded waiting, retry accounting,
crop/file cleanup, and preservation of NOT_VISIBLE → UNCERTAIN semantics. Measure
added disposition latency. A 50% token discount on eligible calls is not a 50%
run saving. Do not add this transport speculatively in the corrective release.

### 1.7 R-06: shared digest/critique prefix

Measure current real-time cache-hit rates and the population of real-time
exhaustive runs before spending engineering effort. Compare against 2.35
successful-hit image-read equivalents, not an assumed three full-price reads.

Changing system/persona placement alters prompts and can change review quality.
Investigate common prefix identity, thinking/effort compatibility,
source-text/image ordering, TTL, stage timing, and specification/profile
differences. Batch caching is supported by the provider on a best-effort basis;
the current application simply does not organize those requests to rely on it.

At three total reads, the one-hour shared-prefix proposal has only a 6.4%
image-component advantage over the current successful-cache case. Do not
restructure the pipeline around the original brief's 27% claim.

## 2. Explicit non-goals and rejected shortcuts

- Do not accept any quote found only in model output, another sheet, or a
  manufactured joined string as **text-grounded**. WP-03B admits unmatched
  evidence at reduced trust with a required visual check; that is not the same as
  trusting it.
- Do not synthesize an anchor rectangle the model did not report in order to make
  a recovered finding verifiable.
- Do not remove cross-QC grounding checks or weaken fuzzy anchoring thresholds.
- Do not add a capped-text grounding check to the ≤40-entry whole-set path; that
  imports the truncation defect into the common case.
- Do not bump a cache contract counter and add a new hashed key field for the
  same change — either alone invalidates everything (REVIEW_RELEASE_EVIDENCE.md
  §4 records which mechanism each evidence change actually used, and why the
  contract counter is not the record of either).
- Do not change two identical critique reads into digest-plus-critique while
  retaining the same confidence label semantics.
- Do not replace all `except Exception` guards with `except BaseException`, or
  dismiss a native panic as safe to continue without a concrete boundary
  analysis.
- Do not assume `tiktoken.count_tokens` is a current production hot path; the
  review found no production callers of those helpers. Note separately that
  `core/tokenizer.py` imports `tiktoken` at module scope, so the dependency is
  not removable by deleting the helper.
- Do not infer a tile is empty from absence of words/vector operations or enable
  the near-blank heuristic by default.
- Do not change image format to claim token savings; current token estimation is
  dimensional. Compression can affect transport or quality, which are different
  questions.
- Do not treat a physical page size as a legibility or cost signal on its own
  (docs/PERFORMANCE_AND_COST_VALIDATION.md, "Two image-token regimes").
- Do not shrink the overview or lower output caps as an unmeasured cost fix.
- Do not broadly rename defaults, remove unused compatibility APIs, split the
  GUI/report generators, or add a build system as incidental cleanup.
- Do not replace existing A/B and benchmark tools with a parallel evaluation
  framework, or rebuild telemetry that already exists (per-model cost, the
  `confidence` tally).
- Do not claim full artifact byte equality between cold and warm runs whose
  journals/usage legitimately differ; compare the appropriate content and
  deterministic assembly contracts.
- Do not treat PDF-import isolation as a newly established legal conclusion.
  Preserve the existing project boundary and licensing policy.
- Do not update dependencies based solely on unfamiliar package names in the
  external brief.
- Do not adjust global schema versions, prompt hashes, model defaults, or pricing
  dates without a specific changed contract.
