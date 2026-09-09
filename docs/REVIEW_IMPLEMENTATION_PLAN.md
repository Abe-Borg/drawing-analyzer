# Drawing Analyzer: corrective implementation and evaluation plan

Prepared: 2026-09-08 · **Revision 2: 2026-09-08** (post independent review)
Reviewed baseline: `89c8ecb`, version `1.3.0rc1`
Audience: coding agents implementing the work, an independent reviewing agent, and the repository owner
Status: implementation specification; the changes below have not yet been implemented

## 0. Changes in revision 2

Revision 1 was reviewed independently against the code at `89c8ecb`. Its
arithmetic was re-derived and confirmed exact; its code citations were confirmed;
several of its scope and sequencing decisions were not. This revision folds in
the agreed corrections. Work packages were **renumbered** to match the corrected
execution order — see §4.1 for the mapping.

| # | Change | Why |
|---|---|---|
| 1 | The acceptance-runner network exclusion is promoted to the **first** package (new WP-01) | It is the only item in this document that can spend money without consent. Revision 1 addressed it with an invocation wrapper in the final package, leaving the shipped script unchanged |
| 2 | New WP-02: **free coverage/truncation diagnostics before any evidence fix** | Revision 1 specified a fix whose prevalence it admitted was unmeasured, when the measurement costs nothing |
| 3 | The evidence fix is split into **WP-03A (tail, cache-preserving)** and **WP-03B (visual evidence, cache-invalidating)** | They have opposite cache consequences. Merging them forces the expensive invalidation onto the cheap fix |
| 4 | WP-03B is new: raster, hybrid and missing-quote grounding failures | Revision 1 fixed the >15,000-character tail only. Two larger grounding failures were left open (§2.1) |
| 5 | WP-03B must supply an **evidence location**, not merely admit the finding | A retained sharded finding is structurally unanchorable today, so it can never be verified or investigated (§2.2) |
| 6 | The cross-QC **contract bump is removed** from the tail fix, and the evidence fingerprint becomes conditional | The bump was provably unnecessary for that change and would discard every stored cross-QC result (§2.3) |
| 7 | The GUI package shrinks to a **measured confirmation-time scan**; the background-worker design is deferred | Image tokens are scale-invariant, so the principal correction needs an aspect ratio and one boolean per page (§2.6) |
| 8 | The A/B **estimate-only child process is retained**; the in-process alternative was evaluated and rejected | Per-stage resolvers fall back to the import-bound `REVIEW_MODEL_DEFAULT`, so in-process env mutation fixes one stage and silently leaves four stale (§2.4) |
| 9 | R-04 (text-budget truncation) moves ahead of R-01/R-02; its zero-call half becomes WP-02 §7.1 | It bounds review *quality*, not cost, and its first step needs no paid calls |
| 10 | Documentation item 14 now names its target precisely; two other documentation items were dropped as already satisfied | §2.4, §12 |

Two claims made during review were themselves wrong and are recorded so they are
not re-litigated: the stale investigation-eligibility comment **does** exist
(`core/api_config.py`, line 57 — an earlier search missed the `core/` package),
and cross-QC's model input is the digest prose **plus** the budgeted text layer,
not the 4,000-character text layer alone.

A second review pass on this revision found four further defects in it, all
confirmed against the code and folded in here:

| # | Defect in the first draft of revision 2 | Correction |
|---|---|---|
| 11 | The location route reached per-shard map findings only. Reconcile-produced findings — the cross-shard path the sharded design exists for — are built from the response with no access to the originating facts, and the reconcile output contract carries no tile | §8.4 Part 2: a host-side `(handle, normalized quote) → fact` join, using the verbatim-quote guarantee the reconcile prompt already imposes |
| 12 | Retaining a tile does not produce a TILE anchor. `_anchor_one` falls back to the tile only when the quote is **blank**; a non-empty unmatched quote — exactly the scanned and hybrid case — returns `quote_not_found` and never consults its tile | §8.4 Part 3: a tile fallback scoped to the explicitly reduced-trust state, with the hallucination signal preserved everywhere else |
| 13 | WP-02 was declared zero-call while requiring the grounding discard rate, which no stored artifact retains — the drops happen before `CrossQCResult` is built | §7 split into a zero-call tier (§7.1) and one explicitly budgeted instrumented run (§7.2) |
| 14 | §2.6 claimed the ≤20-image branch is not scale-invariant | It is. Scale invariance follows from long-edge normalization in **both** regimes; what differs is *aspect* sensitivity — 20.27% spread at 6×6/1560, 0.00% at 3×3/2576 |

Items 11 and 12 mattered most: together they meant the recommended fix would have
admitted recovered findings into the same unverifiable dead end this revision
added WP-03B to escape.

## 1. Outcome and scope

Establish free measurements first. Then implement the supported correctness and
estimation fixes. Improve the existing experiment tooling so later cost decisions
can be based on identifiable findings and actual stage costs. Preserve the
current production review quality settings while doing that work.

The intended outcomes are:

1. No acceptance or test invocation can reach the paid API by inheriting an
   environment variable.
2. The set's actual evidence coverage — text truncation, textless and hybrid
   sheets, unlocatable findings — is measured before it is engineered against.
3. A genuine cross-sheet quote does not become invalid merely because its source
   text was excluded from a model prompt budget, absent from the extracted text
   layer, or omitted entirely.
4. A recovered finding can actually be located, verified, and disclosed — not
   admitted into a state where nothing downstream can check it.
5. Estimates describe the configuration that will actually execute, including
   model routing, transport, image resolution policy, and relevant caching
   assumptions.
6. The operator can distinguish a planning estimate from a conservative image
   allowance and from actual recorded usage.
7. A/B experiments retain enough evidence to investigate lost findings instead of
   relying only on aggregate percentages.
8. Documentation accurately describes rendering reuse, text retention, cache
   behavior, and the limits of quality measurements.

This plan does **not** propose changing the shipping model defaults, the 6×6
grid, 8% overlap, 1560-pixel vector target, raster target, two-read critique,
blank suppression, or model prompt text as part of the immediate corrective
release. Research packages describe how to evaluate those changes separately.
WP-03B does change one model prompt — the sharded cross-QC map prompt — because
the recovery path cannot be completed without it; that change is scoped, and its
cache consequence is stated in §2.3.

The original external review brief is background evidence, not an implementation
specification. Several of its claims were refuted. Do not implement its
recommendations wholesale or interpret its 57-item checklist as already
completed.

The owner requested this handoff document. No live-run dataset or spending budget
was selected during planning. Implement and validate locally with hermetic
fixtures; conduct paid experiments only within an explicitly selected dataset,
configuration, and budget. Do not infer publishing, merging, or releasing
instructions from this document.

### 1.1 Decision table

| Work | Decision | Reason |
|---|---|---|
| Exclude network tests in the acceptance runner itself | **Implement first** | The only path in this document that spends money without consent |
| Coverage/truncation/locatability diagnostics | **Implement second** | Sizes every remaining evidence decision. §7.1 is zero-call; the discard rate (§7.2) needs one budgeted run |
| Separate full source text from prompt text; fix sharded tail grounding | Implement (WP-03A) | Concrete conditional loss of valid evidence; cache-preserving |
| Admit textless / hybrid / unmatched visual evidence and give it a location | Implement (WP-03B) | Larger loss than the tail case; requires cache invalidation |
| Give sharded findings a location and let the resolver use it (§8.4, three parts) | Implement inside WP-03B | Without all three, a recovered finding can never be verified (§2.2) |
| Bump `_CROSS_QC_CACHE_CONTRACT` for the tail fix | **Do not** | Provably unnecessary; discards valid stored results (§2.3) |
| Add the evidence fingerprint unconditionally to the cross-QC key | **Do not** | Changes every key, which is the invalidation it was meant to avoid. Include it conditionally (§2.3) |
| Correct A/B estimate/runtime model mismatch via an estimate-only child process | Implement | Per-stage resolvers fall back to an import-bound default; an in-process fix is incomplete (§2.4) |
| Correct transport-dependent specification-cache wording | Implement | Batch inputs are priced uncached but described as cached. Arithmetic is already correct; only the copy is wrong |
| Improve image and stage cost previews | Implement incrementally | Current square/raster allowance overstates typical imagery by ~1.9× and hides assumptions |
| Collect page metadata on a background GUI worker | **Defer pending measurement** | Aspect ratio plus one boolean per page carries the correction; measure scan and lock-wait time first (§2.6, §10.2) |
| Record family costs, actual resolved configuration, and finding-level evidence in A/B outputs | Implement | Needed to assess savings and possible missed defects. Per-model cost and the `confidence` tally already exist — preserve, do not rebuild |
| Add explicit overlap parameters to the existing experiment harness | Implement as opt-in tooling | Current environment-only variants cannot change overlap |
| Correct repository documentation and stale comments | Implement | Misleading explanations can cause future regressions |
| Add a digest-specific environment variable | Defer | Existing API parameter and stage overrides already support the experiment |
| Rewrite import-time model configuration globally | Defer | The estimate-only child fixes the demonstrated harness issue without a global refactor |
| Reduce resolution, overlap, critique reads, or change default model | Measurement required | Potential loss of review coverage or changed meaning of confidence |
| Batch first-pass verification | Measurement required | Benefit depends on actual eligible stage spend and latency |
| Share digest/critique image-prefix cache | Defer behind measurements | Smaller savings than brief claims; changes prompts and scheduling |
| Broaden exception guards to `BaseException` | Do not do as general hardening | No demonstrated supported-environment failure justifies swallowing process-control exceptions |
| Skip tiles because they lack words and vector operations | Reject this criterion | Raster images and annotations can still carry the evidence |

## 2. Evidence and corrected assumptions

Line numbers below are navigation hints at the reviewed commit. Search by symbol
after rebasing. Paths are repository-relative so this document remains portable.

### 2.1 The evidence-grounding defects

`render.render_sheet()` extracts both reading-order text and complete word
tuples. It caps only `sheet_text` (`render.py`, lines 663–666, cap
`SHEET_TEXT_MAX_CHARS = 15_000`); `anchor.resolve_anchors()` uses the full
`words` stream. A quote absent from capped prompt text can therefore still
receive an `EXACT` anchor. The brief's statement that tail quotes necessarily
become `UNANCHORED` is false.

The real defect is in cross-QC's host-side grounding validator, and it has
**three** distinct triggers, not one.

`cross_qc._grounded(quote, sheet_text)` (line 325) accepts a quote only when it
appears in that sheet's **capped** `sheet_text`. It is called from:

- `_finding_from_handles()` (line 464) — per leg; a failed leg is dropped, and a
  finding with fewer than two surviving grounded sheets is discarded entirely.
- `_parse_facts()` (line 804) — per fact; a fact with an absent or ungrounded
  `exact_quote` never reaches reconciliation.

Both are on the sharded path only. `cross_sheet_qc()` selects it when retained
entries exceed `MAX_SHEETS_SINGLE_CALL = 40` (line 1171) — the count of
*included readable entries* (a failed or empty digest is filtered out at line
1128), not the number of PDF pages selected.

**Trigger 1 — text beyond the cap.** A genuine quote after character 15,000 is
transcribed from pixels into the digest, returned by cross-QC, and then discarded
despite existing in the source and in the full word stream.

**Trigger 2 — text absent from the extracted layer.** A scanned sheet has an
empty text layer (`render.py:665` sets `is_raster = len(words) == 0`), so *every*
quote on it fails grounding. `_parse_facts` additionally requires a non-empty
quote, so a textless sheet contributes **zero facts** and is excluded from
cross-shard reconciliation entirely. This is not confined to fully raster sheets:
a hybrid sheet with a selectable title block and pasted raster details has words
(so `is_raster` is `False`) while its detail content is not in the text layer at
all. Classifying on `is_raster` alone does not identify this case.

**Trigger 3 — omission.** `_finding_from_handles` guards with
`if quote and not _grounded(...)`. A leg with **no** `source_quote` skips the
check and is trusted unconditionally. The check is opt-out by omission.

Reproduced hermetically against the real `fold_text` and `_cap_sheet_text`, with
no PDF and no client:

```
(a) dense vector sheet   full=17140  capped=15031
      grounded vs FULL   : True
      grounded vs CAPPED : False     <- trigger 1
(b) scanned/raster sheet full=0  (page.get_text() == '')
      grounded vs FULL   : False     <- trigger 2; a full-text field does not fix it
(c) empty quote          `if quote and not _grounded(...)` short-circuits
                                     <- trigger 3; leg trusted unchecked
```

Assessment: **P2 for trigger 1, P1 for trigger 2** on sets that contain scanned
or hybrid sheets. Prevalence on real projects is unmeasured for all three, which
is what WP-02 exists to establish before WP-03 is designed in detail. The
large-set rejection was established by code inspection plus the pure
reproduction above, not by an end-to-end production run.

The legacy ≤40-entry validator (`_validate_cross_item`, line 343) performs **no**
grounding check at all — it accepts any quote and relies on the anchor tier to
expose a hallucination. The two paths are therefore inconsistent in both
directions: the whole-set path never rejects, the sharded path over-rejects.
Fixing the sharded path converges their effective behavior; do not "fix" the
whole-set path by adding a capped-text check to it, which would import trigger 1
into the common case.

Important qualification, retained from revision 1: cross-QC applies its own
4,000-character per-sheet text-layer budget (`_TEXT_LAYER_BUDGET`, line 101). A
genuine over-15,000-character case already records omitted input and is
ordinarily budget-degraded, so its result is not admitted to the cross-QC cache.
Recovering a valid finding does not make that review complete. Preserve this
distinction in tests and documentation.

A second qualification, corrected in this revision: cross-QC's model input is the
**digest prose plus** the budgeted text layer (entries are built as
`(sheet_id, sd.text, geom.sheet_text, geom)` at line 1128). The 4,000-character
budget bounds direct source-text evidence, not the stage's whole information
input. It is still the tightest bound on that evidence and is the subject of
R-04.

### 2.2 Why recovered evidence does not currently reach verification

Admitting a finding is not recovering it. On the sharded path a retained finding
whose quote does not match extracted words is structurally unanchorable, and
every downstream check requires an anchor:

- `_finding_from_handles` hardcodes `tile=None` on the primary **and** on every
  `also_on` leg (`cross_qc.py`, lines 482 and 491).
- `CrossQCFact` (line 254) has no tile field, so a location cannot survive
  reconciliation even if one existed.
- The sharded map and reconcile prompts never request a tile. `tile_label` is
  requested only in the whole-set prompt (line 173), and only
  `_validate_cross_item` resolves it (`_resolve_tile`, line 386).
- Reconcile-produced findings — the cross-shard path the sharded design exists
  for (DA-015) — are built by `_reconcile_call` from the **response** items via
  `_finding_from_handles(item, entry_by_handle)`, with no access to the
  originating facts, and `CROSS_QC_RECONCILE_SYSTEM_PROMPT` (line 216) specifies
  an output contract with no tile. A location stored on a fact is discarded
  before the finding is built.
- `anchor._anchor_one` (line 339) calls `_tile_anchor` **only when
  `source_quote` is blank**, returning `UNANCHORED,
  method="no_quote_no_tile"` when no tile was reported (`anchor.py`, line 338).
  A **non-empty** quote that matches nothing — precisely the scanned and hybrid
  case — falls through EXACT/FUZZY to `UNANCHORED,
  method="quote_not_found"` (line 356) and never consults its tile at all.
- Cross-sheet verification requires an anchored primary **and** at least one
  anchored leg (`verify._has_anchored_legs`, line 144).
- Investigation requires `anchor.rect_pdf is not None`
  (`investigate._candidates`, line 1117).

So a finding admitted without a location is admitted into a dead end: never
crop-verified, never investigated, and — per the §18 markup rules — placed as a
margin callout with no ink on the drawing. That is arguably worse than dropping
it, because it presents an unverifiable claim as a review result.

The consequence for WP-03B: the fix must **obtain a usable evidence location**
and make the resolver able to use it, not merely relax the acceptance test. The
last two bullets are why a tile on the map path alone is insufficient — §8.4
specifies all three required parts.

### 2.3 Cache reachability: what actually needs invalidating

Revision 1 required both an evidence fingerprint in `_cross_qc_cache_key()` and a
`_CROSS_QC_CACHE_CONTRACT` bump. Both were wrong for the change it specified.

Trace the admission chain:

1. `_budgeted_text_layer` marks the run degraded when any sheet's text layer
   exceeds 4,000 characters; `_fold_budget` folds every shard's counters into one
   run-level budget (lines 559, 572).
2. `_cross_qc_from_cache` refuses to replay, and `_put_cross_qc_cache` refuses to
   store, any result with `budget_degraded` (lines 1057 and 1064).
3. A sheet with more than 15,000 characters necessarily exceeds 4,000.

Therefore **no cross-QC result whose grounding depended on tail text has ever
been, or can ever be, cached.** Every currently-eligible cached entry was
produced from sheets under 4,000 characters, where `sheet_text ==
full_sheet_text`, so the old and new grounding rules agree on it exactly. The
contract bump would discard valid Opus whole-set and shard results on precisely
the 40+-sheet sets that cost the most to recompute.

The key already covers more than revision 1 assumed: `cross_sheet_qc` puts the
full **capped** `text_layer` into `_cross_qc_cache_key` (line 991), not the
4,000-character budgeted version, so the entire window the validator reads today
is already part of the key.

A second correction, raised in review: `stage_cache_key` JSON-serializes its
envelope (`stage_cache.py`, line 48). **Adding a field to the hashed
`cache_inputs` dict changes every key**, which is exactly the wholesale
invalidation the bump was rejected for. Dropping the bump while adding an
unconditional field preserves nothing.

Required treatment:

**WP-03A (tail) — cache-preserving.** Include the full-evidence hash **only when
the sheet was actually truncated** (`full_sheet_text != sheet_text`). Every
currently-cacheable sheet is untruncated, so every existing key survives
byte-identically, while any future sheet whose tail is load-bearing keys
distinctly. This is the repository's own established idiom: `compute_finding_id`
appends `source_id` only when non-empty, documented as keeping a legacy
finding's historical id exactly (`models.py`, line 557). Do **not** bump the
contract. The forward-compatibility case that makes the conditional field
load-bearing is a future rise of `_TEXT_LAYER_BUDGET` above
`SHEET_TEXT_MAX_CHARS`; document that reason in the code.

**WP-03B (visual evidence) — cache-invalidating.** Textless and hybrid sheets
have short text layers, stay non-degraded, and **are** cached today with the
wrongly-dropped legs baked in. Those results must not replay. Two mechanisms are
available and only one is needed:

- If the change touches any cross-QC prompt — which the §8.4 tile route does —
  invalidation is **automatic**. All three prompts ride every cross-QC key
  (`prompt={"whole_set", "map", "reconcile"}`, line 1004), so editing the map
  prompt changes every cross-QC key on both paths. A contract bump would be
  redundant.
- If WP-03B lands as a host-side-only change with no prompt edit, advance
  `_CROSS_QC_CACHE_CONTRACT` to the next value present at implementation time.

State in the implementation log which mechanism applied and why. Do not apply
both.

Retained requirements, unchanged:

- Digest/critique image request and prompt bytes remain unchanged, so their
  result caches remain reusable.
- Do not bump `digest_cache._SCHEMA_VERSION`, `_STAGE_CACHE_SCHEMA`, PDF render
  identity, or digest/critique prompt hashes to invalidate cross-QC. A global
  schema bump clears broader stored content; that is unnecessary spend.
- Dense cases with existing budget degradation must continue to recompute
  cross-QC. Do not relax cache admission to make a warm run look clean.

Revision 1's regression case "tail-only key sensitivity must miss the cross-QC
cache" is **demoted to a unit test on `_cross_qc_cache_key`**. It cannot be
constructed from renderer output: `sheet_text` is always a prefix of the full
text, so divergence without degradation requires a hand-built object. Test the
key builder directly and do not present it as an end-to-end cache-behavior
regression.

### 2.4 Supported estimation, configuration, and documentation issues

- `pipeline.estimate_image_tokens_for_set()` (line 3659) uses square images at
  the raster target. Its 177,008-token allowance for a default sheet is
  deliberate; it is not the expected image usage of a vector E-size sheet,
  which is 92,871 tokens under the reviewed formulas — the shipped preview
  overstates the dominant line item by ~1.9×.
- `scripts/ab_sweep_drawing_analyzer.py::_estimate()` (line 422) imports
  `REVIEW_MODEL_DEFAULT` before mutating environment variables for each arm
  (lines 436–437). Actual arms execute in fresh subprocesses. A global-model
  variant is therefore estimated with the wrong model.
  **An in-process fix is insufficient.** `core/api_config.py` line 60 binds
  `REVIEW_MODEL_DEFAULT` at module scope, and the per-stage resolvers fall back
  to that binding — `critique.py` line 129 is
  `os.environ.get("DRAWING_ANALYZER_CRITIQUE_MODEL") or REVIEW_MODEL_DEFAULT`,
  and cross-QC, synthesis, focus **and the review planner**
  (`review_planner.default_review_plan_model`) follow the same shape — **five**
  fallback-dependent stages, not the four counted here originally; the planner
  was missed. Re-reading the environment for the digest model alone yields a
  corrected digest estimate beside five stale stages, while the execution child
  resolves all six correctly. That is a worse failure than the current one,
  because it looks fixed. The estimate-only child process is retained for this
  reason. `resolve_transport()` is already re-read per arm and is already
  correct.
  **Measured before the fix (WP-04):** a 10-sheet exhaustive run priced with
  `DRAWING_ANALYZER_MODEL=claude-sonnet-5` quoted **$28.59** — byte-identical to
  the Opus baseline — against a true **$11.60**. The estimator was not imprecise
  about the variant; it never priced the variant.
- `os.environ.clear()` inside the live parent process (line 436) should be
  removed on its own merits regardless of which estimate design lands.
- The same-configuration guard compares whole environment dictionaries
  (line 495), so an irrelevant variable defeats it and an overlap-only change
  cannot be expressed at all.
- `cost.format_drawing_cost_prompt()` (line 210) and
  `format_exhaustive_cost_prompt()` (line 702) describe uploaded specifications
  as cached unconditionally, including on the batch digest path.
  **The arithmetic is already correct** — `_specs_cost_contribution` prices the
  batch branch as ordinary batch input (line 79) and its docstring says so
  explicitly. Only the operator-facing copy is wrong. Fix the copy; do not
  "correct" the calculation.
- The exhaustive estimator computes image tokens once with the digest model
  (line 490) and reuses that count for critique, which is priced with
  `stage_models.critique` (line 562). Opus 5 and Sonnet 5 share the hi-resolution
  tier (4784 / 2576), so the counts coincide for the shipping pair; the mismatch
  is reachable through `DRAWING_ANALYZER_CRITIQUE_MODEL` pointing at a
  standard-tier model, where it is a ~3× error. Latent, not live.
- The standard estimator prices synthesis and focus with the digest `model`
  argument (lines 154, 164) although both have independent runtime resolvers that
  `resolve_stage_models()` (line 370) already exposes.
- The fixed prompt-token allowance does not account accurately for arbitrary
  retained sheet text. An image upper allowance does not bound the whole invoice.
- `scripts/run_acceptance.py` line 53 invokes an unfiltered
  `pytest -q` for its hermetic-suite gate. `pyproject.toml` sets
  `addopts = "-ra --strict-markers"` with no default marker exclusion, and
  `tests/conftest.py` skips `@pytest.mark.network` tests **only when no real key
  is set**. An inherited `ANTHROPIC_API_KEY` therefore turns the release
  acceptance run into a paid live-canary run. This is the one item here that
  spends money without asking.
- `docs/PERFORMANCE_AND_COST_VALIDATION.md` line 107 still says a cold real-time
  exhaustive run renders each readable sheet twice. `render_spool.py` already
  reuses the compressed PNG bytes; a second render is the fallback when reuse is
  unavailable.
- `pipeline.extract_drawing_context()` still carries the stale explanation that
  the digest images are gone before critique (line 2373).
- `core/api_config.py` line 57 states that verification "reserves Opus for
  escalation on CRITICAL/HIGH UNVERIFIED findings." `VERIFICATION_ESCALATION_MODEL`
  has no references in `verify.py` and no severity gate exists there. This is the
  precise target of documentation item 14; `README.md` lines 854 and 1266 already
  describe investigation correctly ("UNCERTAIN findings … severity-first") and
  need no change.
- `gui.py` already runs an asynchronous profile preflight
  (`_refresh_profile_suggestions`, line 1377) that serializes PyMuPDF under
  `self._preflight_lock` (line 267) behind a generation counter. Any new
  PDF-touching preview work must coordinate with it; "nothing else owns the PDFs"
  is not true at any point the user can click.

### 2.5 Correct cost arithmetic

At the reviewed pricing, Opus 5 input/output rates are $5/$25 per million tokens;
Sonnet 5 rates are $2/$10. Five-minute cache writes cost 1.25× input, one-hour
writes 2×, and cache reads 0.1× for those models. Batch token pricing is half the
standard rate.

For current real-time exhaustive image input, assuming critique read two hits its
cache:

`digest 1.0 + critique write 1.25 + critique read 0.1 = 2.35 full-price reads`

A proposed shared five-minute prefix would cost 1.45 read equivalents, a 38.3%
reduction of that image component. A shared one-hour prefix would cost 2.2
equivalents, a 6.4% reduction. These are not whole-run savings and are not
measured cache-hit guarantees. If both current critique requests miss and write,
their combined multiplier is 2.5, not 2.0; adding the digest gives 3.5 for that
image component.

The current renderer chooses 2576 pixels when a grid produces at most 20 images
(`tiling.target_long_edge_px`, line 180). A 3×3 or 2×2 grid therefore does not
retain the 1560 target used in the brief's adaptive-grid table. This branch is
**deliberate policy**, documented in that function — an oversized image is
downscaled rather than rejected below the threshold. The defect is the brief's
assumption that a smaller grid keeps the vector target, not the renderer. The
vector-target environment override does not alter this few-image branch, by
design.

For 20 E-size + 8 D-size + 6 11×17 + 2 assumed letter-size cover sheets, the
source-formula estimates are:

| Image-input scenario | Current 6×6 | Proposed per-sheet grids with current target policy | Proposed per-sheet grids with explicit 1560 throughout |
|---|---:|---:|---:|
| Image tokens for one read of the set | 3,150,948 | 2,642,892 | 2,459,178 |
| Reduction | — | 16.12% | 21.95% |
| Standard real-time image input | $15.75 | $13.21 | $12.30 |
| Standard batch image input | $7.88 | $6.61 | $6.15 |
| Exhaustive real-time image input, successful critique cache hit | $37.02 | $31.05 | $28.90 |
| Exhaustive batch image input | $23.63 | $19.82 | $18.44 |

Every value in this section was **independently re-derived during review** from
the geometry and token formulas with whole-pixel dimension rounding, and matched
exactly, including the 177,008 allowance, the 92,871 vector E-size figure, and
the mixed-set total (which resolves as ANSI E 34×44, ARCH D 24×36, ANSI B 11×17,
letter).

**Measured during WP-05: whole-pixel dimension rounding is not what the renderer
does, and it is systematically low.** `page.get_pixmap(matrix=m, clip=r)` sizes
the pixmap from `(r * m).irect` — the smallest integer rectangle *containing* the
transformed rect, i.e. floor on the top-left corner and ceil on the bottom-right.
That expands to contain rather than to nearest, and it depends on where the rect
sits, not only how big it is: on a 34×44 sheet at 6×6 / 1560, tiles `r0c1` and
`r0c2` are both 473.280 pt wide and render **1296** and **1295** px. No
dimension-only rule reproduces that pair.

The gap is small and one-directional:

| Value | Plan (round the dimension) | Renderer (`irect`) | Delta |
|---|---:|---:|---:|
| Vector E-size sheet @ 6×6 / 1560 | 92,871 | 93,013 | +0.15% |
| Square @ 6×6 / 1560 | 116,481 | 116,617 | +0.12% |
| Mixed 36-sheet set, current 6×6 | 3,150,948 | 3,155,700 | +0.15% |
| 177,008 allowance; 47,840 @ 3×3; 23,920 @ 2×2 | — | identical | 0.00% |

The values that clamp to the model token cap are unaffected, which is why the
≤20-image figures agree exactly. Nothing here invalidates §2.5's conclusions —
this section already says its numbers are cross-checks, "not production
regression fixtures requiring exact agreement with rasterizer rounding", and
that is precisely the discrepancy. WP-05's estimator mirrors `irect`, so it
matches real renders pixel-for-pixel on 18 of 20 shape/grid combinations and
within 0.0035% of token count on the other two; the plan's figures are asserted
in tests only within a 0.3% tolerance. They are not rendered-image measurements or complete run estimates. They
exclude blank suppression, prompt text, output/thinking, verification,
investigation, citation, retries, and local result-cache hits. Use them as
arithmetic cross-checks, not production regression fixtures requiring exact
agreement with rasterizer rounding.

### 2.6 Image tokens are scale-invariant; aspect sensitivity depends on the regime

`tiling.zoom_for_rect()` normalizes every rectangle's **long edge** to the render
target, so estimated pixel dimensions — and therefore token counts — are a
function of aspect ratio, grid, overlap, target, and model tier. **Physical page
size does not enter.** ANSI E 34×44 and US letter 8.5×11 share an aspect ratio
and both compute to exactly 92,871 tokens at 6×6 / 8% / 1560.

Scale invariance follows from long-edge normalization alone, so it holds in
**both** target regimes. What changes between them is **aspect-ratio
sensitivity**, because of token-cap clamping:

| Regime | Same aspect, different physical size | Different aspect (34×44 vs square) |
|---|---|---:|
| >20 images @ 1560 (shipping) | identical — 92,871 either way | 92,871 vs 116,481 — **20.27%** spread |
| ≤20 images @ 2576 | identical — 47,840 either way | 47,840 vs 47,840 — **0.00%** spread |

In the shipping >20-image regime the largest possible image (a square at 1560) is
3,245 tokens, below the 4,784 hi-resolution cap, so nothing clamps and aspect
ratio drives the number. In the ≤20-image branch a 2576-pixel long edge puts
essentially every image at the cap, so aspect ratio washes out entirely and cost
reduces to image count: an E-size sheet at 3×3 costs 10 × 4,784 = 47,840 tokens
whatever its shape.

Do not state this as "the ≤20 branch is not scale-invariant" — it is. R-03 must
model the two regimes separately because their *aspect* behavior differs, not
their scale behavior.

Decomposing the current preview's ~1.9× overstatement for a vector E-size sheet:

| Assumption corrected | Tokens per sheet | Change |
|---|---:|---:|
| current preview (square at the raster target, 1992) | 177,008 | — |
| aspect ratio only | 151,432 | −14.5% |
| **render target only** (needs one boolean: does the page have words?) | **120,065** | **−32.2%** |
| both | 92,871 | −47.5% |

The dominant lever is a single boolean per page. Both inputs come from one cheap
scan — `page.rect` plus `len(page.get_text("words"))` — with no rasterization.
This is why WP-05 does not require the metadata-collection architecture revision 1
specified. It is *not* a claim that the scan is instantaneous: see §10.2.

### 2.7 Limits of the prior review

No complete security, licensing, cache-dependency, markup-geometry, or 57-item
repository audit was performed. The reported cryptography failure was not
reproduced in a supported production environment. A Python launcher in the
checked-out virtual environment failed during read-only investigation; that is
not evidence of a product defect. Isolated dependency-free in-memory checks were
used for the anchor, grounding, and exception-class counterexamples. The
independent review of revision 1 likewise ran by code inspection and pure
arithmetic — `pytest`, `pymupdf` and `tiktoken` were unavailable in that
environment and the suite was not executed. Do not claim any of these as a
passing baseline.

## 3. Requirements that apply to every work package

1. **Full visual coverage:** no content-bearing image tile may be removed as an
   incidental effect of estimation, metadata collection, or experiments.
2. **Prose preservation:** the core digest prose must remain unchanged for
   identical model responses. Do not rebuild, normalize, or rewrite
   `combined_text` to add diagnostics. Preserve existing additive-section rules.
3. **Non-fatal QC:** new optional work must fail within its own stage. Never
   convert an exception into an empty successful result or make a partial review
   appear complete.
4. **Hermetic tests:** no real provider calls or keys in ordinary tests. Use
   existing fake clients and generated fixtures. Dependency advisory checks are
   separate from application tests. **No test-running entry point in the
   repository may reach the network by inheriting an environment variable
   (WP-01).**
5. **PDF-engine isolation:** only the existing approved production modules,
   `render.py` and `annotate.py`, may import PyMuPDF. Pure helpers and cost models
   use plain data. Respect the established sequential PDF-access discipline, and
   coordinate with `gui.py`'s existing `_preflight_lock` rather than adding a
   second independent owner.
6. **Cache correctness:** host-side acceptance inputs matter even when model
   request bytes do not change. Invalidate the affected namespace, not every
   namespace by habit — and remember that adding a field to a hashed key
   invalidates it just as thoroughly as bumping a contract counter (§2.3).
7. **Deterministic assembly:** ordered source identities, finding legs, keys, and
   artifact content must remain deterministic for fixed inputs and fixed model
   results. Run IDs, timestamps, usage histories, and cold/warm cost differences
   are not expected to be identical.
8. **Grounding:** do not weaken quote matching, accept fabricated text, or
   substitute model output for source evidence to make a regression test pass.
   Where textual grounding is genuinely unavailable, say so explicitly and route
   the claim to visual verification — never silently promote it to trusted.
9. **Trust is never gained by omission:** a claim that supplies no quote must not
   end up more trusted than one whose quote failed to match.
10. **Edition awareness:** retain the project's evidenced adopted edition as the
    basis. Do not silently replace it with the latest published edition. Preserve
    explicit handling of ambiguity and jurisdiction; this plan changes no
    code-edition rules.
11. **Accounting and receipts:** `RunUsage` remains append-only, and coverage
    remains derived from reconciled saved-PDF receipts. Estimated cost must never
    be appended as actual usage.
12. **Windows:** use supported Python and Windows-compatible process/path
    handling. Avoid POSIX-only instructions in user-facing examples.
13. **Bounded change:** no dependency upgrades, global formatting, file
    splitting, GUI redesign, or confidence-field migration unless a work package
    requires it.

## 4. Work breakdown and agent ownership

| Package | Primary responsibility | Dependencies | Suggested owner |
|---|---|---|---|
| WP-00 | Baseline, reproduction, interface agreement | None | Integrator |
| WP-01 | Acceptance-runner network exclusion | WP-00 | Integrator |
| WP-02 | Coverage/truncation/locatability diagnostics (§7.1 zero-call, §7.2 one budgeted run) | WP-00 | Evidence agent |
| WP-03A | Tail evidence text + sharded tail grounding (cache-preserving) | WP-02 | Evidence agent |
| WP-03B | Visual-evidence recovery: textless/hybrid/missing quote + location | WP-03A | Evidence agent |
| WP-04 | A/B process parity and immediate cost-copy fixes | WP-00 | Harness/cost agent |
| WP-05 | Pure shape-aware estimation + measured confirmation-time scan | WP-04; agrees interface with WP-03A | Cost agent (GUI agent for the scan) |
| WP-06 | Auditable experiment records and overlap controls | WP-04; WP-05 for estimates | Harness agent |
| WP-07 | Documentation corrections and operating instructions | Can draft early; finalize after WP-01–06 | Documentation/integrator |
| WP-08 | Independent review, full regression, release evidence | Implemented packages | Reviewer/integrator |

### 4.1 Mapping from revision 1

| Revision 1 | Revision 2 |
|---|---|
| WP-00 | WP-00 (expanded reproductions) |
| — | **WP-01** (new; was a test-invocation note inside old WP-06) |
| — | **WP-02** (new; was implicit in R-04) |
| WP-01 | WP-03A + **WP-03B** (new) |
| WP-02 | WP-04 |
| WP-03A | WP-05 (estimation half) |
| WP-03B | WP-05 (scan half, substantially reduced) |
| WP-04 | WP-06 |
| WP-05 | WP-07 |
| WP-06 | WP-08 |

With four agents, use one integrator, one evidence agent, one cost/harness agent,
and one independent reviewer. The reviewer can inspect tests and draft
documentation while implementation proceeds.

Do not let agents edit shared files concurrently without a specific handoff:

- `models.py` and `render.py`: evidence agent owns first; cost-basis additions
  follow or arrive as an agreed small patch.
- `cross_qc.py`: one owner across WP-03A and WP-03B, in that order. Do not
  parallelize them — 03B builds on 03A's evidence contract and reverses its cache
  decision.
- `cost.py` and `tests/test_cost.py`: one owner integrates WP-04 copy fixes and
  WP-05 arithmetic.
- `scripts/ab_sweep_drawing_analyzer.py` and `tests/test_ab_sweep.py`: one owner
  performs WP-04 before WP-06.
- `pipeline.py`, documentation, and changelog: integrator owns final integration.

Use small reviewable commits or draft PRs per package. Do not automatically merge
or publish. Rebase against current code and preserve unrelated user changes.

## 5. WP-00: establish the actual baseline

### Tasks

1. Record current commit, working-tree changes, Python executable/version,
   PyMuPDF version, SDK version, and active package metadata. Record only
   non-secret configuration.
2. Read repository guidance, the relevant source functions, and existing tests.
   Verify the issues are still present if HEAD differs from `89c8ecb`.
3. Establish a supported working test environment. If the local virtual
   environment launcher fails, diagnose its interpreter path before attributing
   failures to application code. Do not replace dependency pins merely to make
   local collection pass.
4. Reproduce, with pure in-memory fixtures and a fake cross-QC client, **all
   three** grounding triggers of §2.1: tail, textless/hybrid, and missing quote.
5. Reproduce the anchor dead end of §2.2: show that a sharded finding retained
   without a tile is `UNANCHORED` and is rejected by both
   `verify._has_anchored_legs` and `investigate._candidates`.
6. Reproduce the A/B estimate model mismatch without a provider client, including
   a stage that resolves through the `REVIEW_MODEL_DEFAULT` fallback so the
   incompleteness of an in-process fix is on record.
7. Confirm the acceptance-runner behavior of §2.4 without a real key — assert the
   collected node set, do not call the API.
8. Run focused existing suites for those areas and record pre-existing failures
   separately.
9. Agree the additive evidence field/helper, the fact-location contract, and the
   cost-preview data interfaces before parallel edits begin.

### Deliverable

A short implementation log in the PR/task containing reproduced failures,
baseline test outcomes, current symbols, and agreed file ownership. Do not turn
this document's observations into claims of passing tests.

## 6. WP-01: the acceptance runner must not be able to reach the network

### 6.1 Required behavior

`scripts/run_acceptance.py::gate_hermetic_suite()` (line 53) must exclude network
tests **in the script**, not in the operator's invocation. Deselect by marker in
the child it spawns, so the gate is hermetic no matter what environment it
inherits. The live canary remains available only through its own explicit,
separately documented invocation.

Apply the same treatment to any other gate in that script that spawns a broad
`pytest` run. Leave `gate_browser_security` selecting `-m browser` as it is.

Do not solve this by unsetting `ANTHROPIC_API_KEY` alone. Marker exclusion is the
property being asserted; key absence is an environment accident that a future
gate could lose.

### 6.2 Tests and acceptance

1. The hermetic gate's child command deselects the `network` marker. Assert on
   the constructed argument vector; do not run the suite inside the test.
2. With a fake key present in the environment, the gate still deselects network
   tests.
3. The browser gate's selection is unchanged.
4. A regression test fails if a future edit reintroduces an unfiltered broad
   `pytest` invocation in that script.

Acceptance: the script is hermetic with a real key in the environment. This
package ships on its own, ahead of everything else.

## 7. WP-02: measure evidence coverage before engineering against it

This package sizes WP-03A and WP-03B and feeds R-04. It has **two tiers**, and
they must not be conflated:

- **§7.1 — zero-call.** Derivable from PDFs on disk and from artifacts an
  existing run already exported. No API call, no budget approval.
- **§7.2 — one instrumented run.** The grounding **discard rate** cannot be
  recovered from any existing artifact (see below), so measuring it requires new
  counters plus one explicitly budgeted sharded run.

Do the zero-call tier first and see how much of the decision it already settles.

### 7.1 What to count — zero-call tier

Over an approved representative set (see §14.1 for composition), record per sheet
and per set:

1. Extracted text length, and whether it exceeds `SHEET_TEXT_MAX_CHARS`
   (frequency of trigger 1), broken down by sheet type.
2. Word count and text length, classifying each sheet as vector, textless, or
   **hybrid** — words present but a substantial image region with no words. State
   the hybrid heuristic explicitly and treat it as approximate; `is_raster` alone
   does not identify it (§2.1).
3. Cross-QC text-budget omission: characters offered, included, and omitted, and
   how many sheets are individually over the 4,000-character budget.
4. Whether the set takes the sharded path (retained readable entries > 40) and
   the retained-entry count.
5. **Surviving-finding locatability**, from an existing run's exported findings:
   the anchor-tier distribution (EXACT / FUZZY / TILE / UNANCHORED) on
   cross-sheet findings, and how many carry a quote at all. This is derivable
   because it describes findings that were *kept*.
6. Existing coverage and completeness fields already produced by the run
   (`budget_degraded`, `text_chars_omitted`, `findings_omitted`,
   `facts_collected`, `coverage_status`).

All of the above is derivable from PDFs on disk plus `RunJournal`,
`CrossQCResult` and the manifests of a run that already happened. Prefer reading
existing outputs to adding instrumentation; where a counter is genuinely missing,
add a count-only journal field — never raw text, never an absolute path.

### 7.2 The discard rate needs one instrumented run

The number that most directly sizes WP-03B — how many legs and facts the model
returned that were **dropped** for failing grounding, and how many of those had
no quote at all — cannot be recovered from any stored artifact.
`_finding_from_handles` and `_parse_facts` discard items before `CrossQCResult`
is constructed; the result retains only accepted findings plus the aggregate
`facts_collected`, and the stage cache stores only parsed results. No existing
counter distinguishes "the model returned nothing" from "the host dropped it."

So this tier is explicitly **not** zero-call:

1. Add count-only counters at both discard sites, separating: quote absent,
   quote present but unmatched, and handle unresolved. Counts and reasons only —
   never the quote text.
2. Run **one** sharded cross-QC pass over the approved set, on an explicitly
   approved budget, with a cold local result cache. State the expected cost from
   the corrected estimator before running it.
3. Record the discard rate by sheet classification (vector / textless / hybrid).

Reuse the run from §7.1 if one is being commissioned anyway rather than
commissioning a second. If no budget is approved, narrow the deliverable to the
§7.1 tier and say plainly that the discard rate is unmeasured — do not present a
surviving-finding distribution as if it were the discard rate.

### 7.3 Deliverable

A short measured report: frequency of each grounding trigger by sheet type, the
hybrid population, the surviving-finding anchor-tier distribution, and — if the
§7.2 run was approved — the discard rate. It converts §2.1's severity assessment
from inference to measurement and tells WP-03B whether the §8.4 location route
covers the observed cases. Label which tier each number came from.

Do not gate WP-03A on this report. Run the §7.1 tier first because it is free and
informative, but the tail fix is justified independently by the reproduction in
§2.1.

## 8. WP-03: recover source evidence without weakening grounding

WP-03A and WP-03B are sequential, share one owner, and have **opposite cache
consequences**. Land and review them separately.

### 8.1 WP-03A required behavior — full evidence text

Keep `sheet_text` as the existing capped, disclosed model-input text. Add a
separate full reading-order text value for host-side source checks. Do **not**
increase `SHEET_TEXT_MAX_CHARS` in this package.

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
- `None` or an absent attribute on older callers/fixtures: fall back to existing
  `sheet_text` for compatibility.
- A malformed non-string value: handle defensively under a documented contract;
  do not silently stringify arbitrary objects into trusted evidence.

Do not use `full_sheet_text or sheet_text`: that conflates known-empty extraction
with unavailable full text. Do not manufacture full reading-order text by joining
word tuples; that changes line boundaries and extraction semantics.

### 8.2 WP-03A implementation map

| File/symbol | Required change |
|---|---|
| `models.py::RenderedSheet` | Append optional full-text field and document distinction from capped prompt text and words |
| `models.py::SheetGeometry` | Same field; keep geometry image-free |
| `models.py::SheetGeometry.from_rendered` | Preserve full text and legacy absence correctly |
| `render.py::render_sheet` | Assign already-extracted `raw_text` to full text; keep `_cap_sheet_text(raw_text)` unchanged |
| `render.py::_sheet_geometry_no_render` | Populate the same full text on level-one cache/prescan paths without rasterizing |
| `render_spool.py::_SheetRecord`, `put`, `load` | Preserve full text exactly through the temporary render handoff |
| `cross_qc.py::_finding_from_handles` | Validate each leg using the source-evidence helper |
| `cross_qc.py::_parse_facts` | Validate map facts using the same helper |
| `cross_qc.py::_cross_qc_cache_key` | Add the evidence hash **conditionally**, only for truncated sheets (§2.3). Do not bump the contract |
| `pipeline.py` and `run_journal.py`, if needed | Count-only source/prompt truncation diagnostics, never raw text |

Keep `cross_sheet_qc()` request entries and `_budgeted_text_layer()` on the
existing capped text in this package. Do not feed full text through those
prompt-building paths just because the field now exists: omission accounting and
completeness gates could change even when the visible prefix looks similar.

Preserve the ≤40-entry validator's existing behavior. The immediate fix is to
stop the >40-entry path from rejecting source evidence that actually exists, not
to add a capped-text check to the whole-set path — which would import trigger 1
into the common case (§2.1).

### 8.3 WP-03B required behavior — visual evidence

WP-03A recovers evidence that exists in extracted text. WP-03B addresses evidence
that is genuinely not in extracted text at all.

Replace the boolean grounding result with an explicit three-state outcome. Naming
is the implementer's, but the meanings are fixed:

- **text-grounded** — the quote was re-found in the sheet's source evidence.
  Existing trust, unchanged.
- **not matched in extracted text** — a quote was supplied, the region it was
  attributed to *does* carry extractable text, and the quote was not found in
  it. This is *not* a contradiction in principle — absence from an extracted
  text layer does not refute a visual claim — but it remains the hallucination
  signal in practice: cross-QC drops the leg and the anchor resolver keeps
  `UNANCHORED` (§8.4 Part 3). The recovery this package promises is delivered by
  the classifier reaching the third state more often, **not** by relaxing this
  one.
- **textual evidence unavailable** — the sheet or the relevant region has no
  extractable text, so no textual check is possible. Admit at reduced trust,
  label the unavailability explicitly, and require visual verification.

Do not name the middle state "contradicted." Do not classify solely on
`is_raster`: a hybrid sheet has words and still cannot support a text check over
its raster regions (§2.1).

**"or the relevant region" is load-bearing, not a hedge.** `render.py` fills
`full_sheet_text` from `page.get_text()`, so one selectable title block makes a
hybrid sheet's *sheet-level* evidence non-empty — and every real hybrid sheet
has one. A classifier that asks only "does this sheet have text?" therefore
sends every quote read off a pasted raster detail to *not matched*, and the
hybrid recovery this package exists for never fires on a single real page. The
question must be asked of the **tile the quote was attributed to**: does that
grid cell contain any extracted word? Two consequences follow, and both are
required:

- the tile must be resolved **before** classification, not after — §8.4 Part 1
  is an input to §8.3, not a downstream consumer of it;
- an **unknown** tile must answer "yes, there was text" (i.e. fall back to the
  sheet-level answer). Absence of a location is not evidence of pixels, and the
  opposite default would launder every unlocatable bad quote on a text-bearing
  sheet into reduced-trust admission.

Both halves need a test: a quote from a word-free tile of a text-bearing sheet
is *unavailable*; a quote from that same sheet's title-block tile is still *not
matched*.

Trust rules, per requirement 3.9:

- A leg with **no quote** must not be admitted more readily than one whose quote
  failed to match. Close the `if quote and not _grounded(...)` bypass: an absent
  quote is at best "textual evidence unavailable," never implicitly grounded.
- A finding surviving on reduced-trust legs alone must be visibly distinguished
  in the ledger, report, and markup, and must not be presented as a
  dual-anchored, text-corroborated conflict.
- Reduced-trust evidence must reach verification. A finding that cannot be
  checked and cannot be located is not a recovered finding — it is an
  unverifiable claim, and disclosing why it could not be checked is mandatory.
- **The disclosure must be true of the finding it sits on.** "Textual evidence
  unavailable" covers two situations the reviewer must not be told are one: the
  sheet offered no text to search, and the model offered no quote to search
  *for*. The state stays single — the host's capability is identical in both,
  and the three-state vocabulary is what serialization and the trust set are
  built on — but the reviewer-facing *reason* is selected from the finding.
  Telling someone "no searchable text on this sheet" while they are looking at a
  sheet whose text they can select does not merely misinform them about that
  finding; it teaches them that the tool's caveats are unreliable, and one false
  caveat discredits every true one beside it.
- A trust label belongs to **its own quote**. Where a finding is decomposed into
  per-leg marks (`annotate._units_for_finding`), each mark carries that leg's
  evidence state, not the parent's: a conflict can be text-grounded on one sheet
  and read off a raster detail on the other, and the caveat must land on the
  half that earned it.

### 8.4 WP-03B: give recovered evidence a location

Per §2.2, admission without a location is a dead end. The route below has
**three** required parts. Landing only the first leaves the principal cross-shard
path exactly as unlocatable as it is today.

**Part 1 — carry a tile on the map path.**

1. Request `tile_label` per fact and per leg in the sharded **map** prompt, in
   the same self-describing form the whole-set prompt already uses (line 173).
2. Add a tile field to `CrossQCFact`.
3. Resolve it with the existing `digest._resolve_tile(item, rows, cols)` against
   **that leg's own sheet's** grid, exactly as `_validate_cross_item` does at
   line 386. `_resolve_tile` prefers `tile_label`, bounds-checks through
   `parse_tile_label`, and returns `None` on anything invalid, so a bad label
   degrades to today's `UNANCHORED` rather than to a wrong rectangle.
4. Stop hardcoding `tile=None` in `_finding_from_handles` (lines 482, 491).

**Part 2 — carry it across reconciliation.** Part 1 alone does not reach the
cross-shard findings, which are the whole reason the sharded design exists
(DA-015). `_reconcile_call` builds its findings with
`_finding_from_handles(item, entry_by_handle)` from the **response** items and
has no access to the originating `CrossQCFact` objects, and
`CROSS_QC_RECONCILE_SYSTEM_PROMPT` (line 216) specifies an output contract of
`{sheet_handle, category, severity, text, recommended_action, source_quote,
also_on: [{sheet_handle, source_quote}], refs}` — no tile. A tile stored on a
fact is therefore discarded before the finding is built.

Preferred remedy, **host-side lookup**: build a `(handle, normalized
exact_quote) → CrossQCFact` map for the facts sent in each reconcile request and
resolve each returned leg's tile from it. The reconcile prompt already requires
that "both quotes must come verbatim from the facts," so the join key is
deterministic and the model cannot invent a location. Normalize the quote with
the existing `_norm_for_match` so the join tolerates the same cosmetic variation
grounding already tolerates. A lookup miss yields no tile and today's behavior —
never a guessed rectangle.

**The join key is not unique, and the collision must lose rather than pick.**
One sheet can carry the same short quote ("150 gpm", "TYP.") in two places, and
the map stage reports each occurrence as its own fact with its own tile. The
obvious `setdefault` keeps whichever was parsed first and hands every later
occurrence a rectangle belonging to somewhere else — which is worse than no
rectangle, because a wrong tile still anchors and still passes the region test,
so a guess is laundered into an artifact-backed location the reviewer is sent to
go look at. Resolve a collision only when every candidate agrees; on genuine
disagreement drop the key entirely and let the leg fall back to being
unlocatable, exactly as it is today. The poisoning must be order-independent: a
later agreeing fact does not rehabilitate a key two earlier facts disagreed on,
or the answer depends on parse order (I-7).

Fallback, only if WP-02 or a pilot shows a high lookup-miss rate: extend the
reconcile output contract to carry `tile_label` per leg and resolve it with
`_resolve_tile` as in Part 1. This is second choice because it lets the model
supply a location rather than deriving one from evidence it already committed to.

**Part 3 — let the anchor resolver use the tile.** Parts 1 and 2 still do not
produce a TILE anchor for the case WP-03B targets. `anchor._anchor_one`
(line 339) calls `_tile_anchor` **only when `source_quote` is blank**; a
non-empty quote that matches nothing falls through EXACT/FUZZY and returns
`UNANCHORED, method="quote_not_found"` (line 356) — deliberately, as the
hallucination signal. The scanned and hybrid cases supply a non-empty quote that
cannot match, so they land in exactly that branch.

`_anchor_one` therefore needs the finding's evidence-trust state (§8.3) and must
distinguish two cases that look identical to it today:

- **Textual evidence unavailable** for this quote's sheet or region — no text
  check was possible, so an unmatched quote is not evidence of fabrication. Fall
  back to the reported tile, at TILE tier, and record the reduced trust.
- **Not matched on text-bearing evidence** — the quote should have been findable
  and was not. Keep `UNANCHORED, method="quote_not_found"`. This is the existing
  hallucination signal and must not weaken.

Do not implement this as a global relaxation of `quote_not_found`. The digest,
critique and whole-set cross-QC paths must keep today's behavior exactly; the
tile fallback is admissible only for a leg the host has explicitly marked
reduced-trust because no textual check was possible.

Consequences to verify, not assume:

- A reduced-trust quote anchors at **TILE** tier — coarse but honest, the same
  contract `_tile_anchor` already documents.
- TILE anchoring satisfies `verify._has_anchored_legs` and
  `investigate._candidates`, so the dual-crop check and the investigation loop
  become reachable for these findings. Assert against those functions.
- This route never consults `is_raster`, so it covers scanned sheets, hybrid
  sheets, and ordinary text-match misses uniformly — which is why it is preferred
  over a raster-classification carve-out.
- It edits a cross-QC prompt, which is already in the cache key, so it supplies
  WP-03B's invalidation automatically (§2.3).
- It adds a small amount of model output per fact and creates a new opportunity
  for a wrong-but-in-bounds tile. Quantify the second with WP-02's locatability
  baseline and the negative regressions in §8.7.
- Fabricated quotes on text-bearing sheets must still be `UNANCHORED` after the
  change. This is the regression that proves Part 3 did not become a blanket
  relaxation.

If WP-02's locatability data shows the model routinely omits tiles on the sharded
path, record that and propose an alternative in a follow-up rather than
back-filling a guessed location. **Never** synthesize a rectangle the model did
not report, and never derive one from a quote the host could not join to a fact.

### 8.5 Cache design

Governed by §2.3. In summary:

- **WP-03A:** conditional evidence hash for truncated sheets only; every existing
  key preserved; **no contract bump**. Document the forward-compatibility reason
  (a future `_TEXT_LAYER_BUDGET` above `SHEET_TEXT_MAX_CHARS`) in the code.
- **WP-03B:** invalidation is required. If the §8.4 prompt edit lands, it is
  automatic and no bump is needed. If WP-03B somehow lands host-side-only,
  advance `_CROSS_QC_CACHE_CONTRACT` to the next value present at implementation
  time. Apply exactly one mechanism and say which in the log.
- Compute any evidence hash once per key build per sheet, not once per quote or
  reconciliation pair. Hash UTF-8 bytes; never place raw text in cache or
  diagnostic metadata.
- Dense cases with existing budget degradation must continue to recompute
  cross-QC. Do not relax cache admission or assert `complete=True` because
  grounding was repaired.
- Digest/critique request and prompt bytes remain unchanged, so their result
  caches remain reusable. Do not bump `digest_cache._SCHEMA_VERSION`,
  `_STAGE_CACHE_SCHEMA`, or render identity for this work.

### 8.6 Consumer audit and explicit boundaries

Inventory all `sheet_text` consumers and classify them before final review:

| Consumer | Immediate package behavior |
|---|---|
| Digest and critique, real-time and batch | Keep existing capped text and wire bytes |
| Cross-QC model prompts | Keep existing budgets and text. WP-03B adds a tile request only |
| Cross-QC host validators | Use full evidence text (03A) and the three-state outcome (03B) |
| Anchor and word-based deterministic auditors | Preserve full-word behavior; no replacement needed |
| `citation_check.py` adoption/trust/edition checks | Document full-text opportunity; no blanket replacement here |
| `set_identity.py` harvest and model corpus | Preserve current model-visible behavior; separate future evaluation |
| `prose_harvest.py` prompts/matching | Preserve current behavior; record any demonstrated issue separately |
| `export.py` sheet-text files | Keep current content contract; document that it is capped text |
| `html_report.py` search/context text | Preserve bounds and escaping; do not embed all full text automatically |
| Logs/manifests | Counts, availability, and truncation only; no new source-text disclosure |

This audit prevents accidental changes to downstream prompts or evidence trust.
It is not a mandate to migrate every consumer in this release.

### 8.7 Meaningful regression cases

Extend existing tests in `test_drawing_models.py`, `test_drawing_render.py`,
`test_render_spool.py`, `test_drawing_cross_qc.py`, `test_drawing_stage_cache.py`,
`test_drawing_anchor.py`, `test_drawing_verify.py`, and appropriate pipeline
acceptance tests.

**WP-03A:**

1. **Tail evidence accepted:** full source contains a distinctive quote after
   character 15,000; capped prompt lacks it; the digest prose includes it,
   modeling transcription from pixels. A 41-or-more-entry sharded fake response
   cites it and another real sheet. The fact/finding survives and both legs
   resolve. Use a content-aware fake that emits the fact only when its handle and
   quote reach the shard through the digest, and emits reconciliation only when
   both facts reach the reconcile request.
2. **Fabrication still rejected:** replace that quote with a never-present
   string; it must still fail text grounding. Also test a quote found only on
   another sheet.
3. **Threshold scope:** 40 and 41 retained entries exercise the intended
   branches, including selected PDFs with failed/empty digests so selected-page
   count is not mistaken for retained-entry count.
4. **Full text stays full:** newline-sensitive and non-ASCII extraction survives
   rendered-sheet, geometry, prescan, and spool transfer without truncation or
   normalization.
5. **Compatibility:** missing/`None` full text falls back; explicit empty full
   text does not fall back to nonempty capped text.
6. **Anchor behavior unchanged:** a real tail quote anchors exactly through the
   existing complete word list; no fuzzy threshold or tile behavior changes.
7. **Prompt stability:** capture digest and critique request structures in both
   transports and cross-QC request text; the full-text addition alone changes
   none of them.
8. **Cache keys preserved:** an untruncated set produces **byte-identical**
   cross-QC keys before and after WP-03A, and a warm run makes zero new cross-QC
   calls. A truncated sheet produces a distinct key. Test
   `_cross_qc_cache_key` directly — this is a unit test on the key builder, not
   an end-to-end cache-behavior claim (§2.3).
9. **Warm render avoidance:** full evidence remains available after a level-one
   digest hit without full-sheet rasterization.
10. **Failure isolation:** extraction/spool/cache failure follows existing
    non-fatal behavior; no empty result silently upgrades review completeness.
11. **No privacy regression:** diagnostic events carry counts/flags only; raw
    tail text and absolute source paths are absent from new log fields.

**WP-03B:**

12. **Textless sheet recovered:** a sheet with no words and a quote transcribed
    from pixels yields a fact and a leg, at reduced trust, that reaches
    reconciliation.
13. **Hybrid sheet recovered:** a sheet with a **populated text layer** whose
    quote was read from a word-free region behaves the same as the textless
    case. Two fixtures do *not* satisfy this: one that passes only because
    `is_raster` is `True`, and — the sharper trap, and the one the first
    implementation fell into — one whose sheet text is whitespace and strips to
    empty. That is a scanned sheet with a stray space, not a hybrid one, and it
    passes without the region rule ever being exercised. The fixture must have a
    selectable title block, a quote from a different tile, and an assertion that
    the sheet-level text is non-empty.
13a. **The region rule is not an amnesty:** on that same hybrid fixture, a quote
    attributed to the title-block tile — which does carry words — is still *not
    matched*. Without this half, the region rule reads as "any sheet containing
    one image excuses every quote on it."
13b. **An unknown tile does not earn the benefit of the doubt:** the same
    unmatched quote with no tile reported classifies as *not matched*, not
    *unavailable*.
14. **Missing quote is not promoted:** a leg with no quote is admitted at no more
    than "textual evidence unavailable" and never at text-grounded trust.
15. **Location reaches verification:** a recovered finding with a reported tile
    anchors at TILE tier and is accepted by `verify._has_anchored_legs` and
    `investigate._candidates`. Assert against those functions, not a copy of
    their conditions.
16. **Cross-shard findings are locatable too:** a fact carrying a tile survives
    `_reconcile_facts` and the reconcile response into the finding built by
    `_finding_from_handles`. A test that only exercises per-shard map findings
    does not satisfy this case, and is the exact gap §8.4 Part 2 exists to
    close.
17. **Reconcile lookup is evidence-derived:** a returned leg whose quote does not
    join to any sent fact gets no tile and stays `UNANCHORED`. A reconcile
    response inventing a handle/quote pair cannot acquire a location.
18. **Anchor fallback is scoped, not blanket:** a non-empty unmatched quote on a
    leg marked *textual evidence unavailable* anchors at TILE tier; the same
    unmatched quote on text-bearing evidence still returns `UNANCHORED,
    method="quote_not_found"`. Assert both halves — the second is what proves
    §8.4 Part 3 did not weaken the hallucination signal.
19. **Other paths keep today's anchoring exactly:** digest, critique and
    whole-set cross-QC findings with unmatched quotes are `UNANCHORED` before
    and after the change.
20. **Bad tile degrades safely:** an out-of-range or malformed `tile_label`
    yields `None`, `UNANCHORED`, and the existing disclosure — never a wrong
    rectangle.
21. **Trust is visible:** a finding surviving on reduced-trust legs alone is
    distinguishable in the ledger, report and markup, and its unavailability
    reason is disclosed.
22. **Old cached results do not replay:** a set that was cacheable before the
    change (short text, textless sheets, non-degraded) recomputes after it.
    Assert the invalidation mechanism actually in use.
23. **An ambiguous fact join yields no tile:** two facts on one sheet with the
    same normalized quote and different tiles produce no entry, in either input
    order, and a third agreeing fact does not rehabilitate the key. Two facts
    that agree still resolve, and the same quote on two different sheets is not
    a collision at all.
24. **A leg's own trust reaches its own mark:** a conflict that is text-grounded
    on one sheet and unavailable on the other produces two marks, each carrying
    its own state — and the primary, seen as a leg of the synthetic finding,
    keeps its own state too.
25. **The reason matches the finding:** a reduced-trust finding with no quote on
    a text-bearing sheet is never told "no searchable text on this sheet," in
    either the markup or the report; the two unavailability cases produce
    different trust sentences, and both still say nothing was checked. Compare
    the *trust note*, not the whole annotation body — the body embeds the quote,
    so two findings differing only by having one compare unequal regardless of
    what the note says.

Use pure fixtures for 41-sheet topology. Only use generated PDFs where
extraction, coordinate consistency, or cold/warm render behavior is the thing
being tested. Do not create 41 expensive rendered fixtures merely to exercise a
list-length branch.

### 8.8 Acceptance and performance

Acceptance requires the positive recovery regressions and the negative
fabrication regressions **together**. Fixing one by accepting all quotes fails
the package. A recovered finding that cannot be located and cannot be verified
does not count as recovered.

Memory overhead should be the retained source text, not an additional set of PNGs
or repeated per-finding copies. Reuse immutable strings where practical.
Full-text hashing and matching must not introduce repeated PDF extraction.
Measure a dense-text fixture and increasing sheet counts with the existing
benchmark approach; use repeated-run medians for performance claims.

If repeated `_grounded()` normalization of long source strings becomes material,
prepare a source-page-scoped normalized-text map once per cross-QC invocation
while preserving existing normalization semantics. Avoid a process-global cache
or a new cap that recreates the evidence loss. Holding a field alone does not
make the model read the full page text; the fix validates facts the model already
supplies.

Recovered findings may legitimately increase ledger counts, verification work,
investigation work, and final costs. That is an expected consequence of
recovering omitted evidence, not a cost regression to suppress. WP-03B in
particular can increase verification volume, because its whole point is routing
unverifiable claims to a check that was previously unreachable. Quote that
expected increase in the implementation log using WP-02's locatability numbers.
No additional model calls should occur merely to obtain full source text.

## 9. WP-04: make A/B estimates describe the actual arm

### 9.1 Process/configuration parity

Fix `scripts/ab_sweep_drawing_analyzer.py::_estimate()` using the same
fresh-process configuration boundary as actual arms. Preferred design: an
internal estimate-only child mode that receives the arm environment before
importing application configuration, returns structured estimate data, and never
obtains a provider client.

The in-process alternative — re-reading the environment for the model inside the
arm loop — was evaluated during review and **rejected**: per-stage resolvers fall
back to the import-bound `REVIEW_MODEL_DEFAULT` (`critique.py` line 129 and the
same shape in cross-QC, synthesis, focus **and the review planner** — five
stages, one more than first counted), so it corrects the digest estimate and
silently leaves all five on the parent's model while execution resolves all six
correctly. Record this reasoning in the code comment so it is not "simplified"
back later.

**A test of this cannot run in-process.** The failure mode *is* the import
binding, so a test that never crosses a process boundary cannot tell a correct
fix from the rejected one. Worse, it can pass the rejected design outright: if
nothing in the pytest session has imported `api_config` yet, an in-process
estimator that sets the environment before that first import binds the *variant*
model correctly by accident. Running one test file in isolation is enough to hit
that. Every such test must therefore force the parent's binding first and assert
the precondition, so it measures the boundary rather than the order the suite
happened to import things in.

Reuse shared arm configuration resolution for estimation and execution. It should
describe resolved stage models, digest/critique transports, grid, overlap, target
override/effective target policy, exhaustive mode, and any selected options that
affect request cost. Avoid a new application-wide dynamic model-default system.

Requirements:

- Establish each child environment before importing `core.api_config` or modules
  whose defaults bind its values.
- Use `sys.executable` and argument arrays; no shell-composed command strings.
- Estimate-only execution performs local inspection only: no client construction,
  provider token-count call, upload, batch creation, or analysis cache mutation.
- Remove `os.environ.clear()` from the parent process (line 436). Do not clear
  and rebuild the live environment while pricing arms.
- Propagate child errors honestly; one failed estimate is not a zero-cost arm.
- Print actual resolved model/transport labels, including fallback effects of
  changing the global model.
- Keep secret-valued environment settings out of printed labels and saved
  effective-configuration records. The environment can contain an API key even
  though it is unnecessary for estimation.
- Replace the claim that cold-arm estimates are what the run "will actually cost"
  (line 461) with wording that preserves uncertainty.

Keep the specification of the child protocol minimal: an argument vector, a JSON
document on stdout, and an exit code. It does not need a general RPC layer.

### 9.2 Immediate wording corrections

In `cost.format_drawing_cost_prompt()` and `format_exhaustive_cost_prompt()` —
**copy only; the arithmetic in `_specs_cost_contribution` is already correct**
(§2.4):

- For batch digest, describe specification text as ordinary batch input; do not
  promise a prompt-cache read discount.
- For real-time digest, describe caching as conditional; parallel initial
  requests and expiry can create additional writes.
- Replace any implication that the entire invoice is bounded by the image
  allowance.
- Distinguish local result-cache hits from provider prompt-cache reads. A local
  cache hit avoids that model call; it does not guarantee every other stage is
  free. **Nor is the opposite true** — the first attempt at this fix replaced
  "cached sheets cost nothing" with "every other stage still bills", which is
  the same error mirrored: every QC stage caches independently and returns
  without a provider call on a hit (identity, review plan, cross-QC, synthesis,
  focus, critique, per-finding verification). The accurate statement has two
  halves, and needs both: the caches are per stage, so a digest hit implies
  nothing about the rest; and identity, the review plan, synthesis and cross-QC
  key on the **whole set**, so the common case — one sheet added to a set
  reviewed last week — hits the digest cache for every old sheet and still
  re-runs those four in full.
- Keep the existing pre-send confirmation behavior and actual transport selection
  unchanged.

### 9.3 Tests and acceptance

Extend `tests/test_ab_sweep.py` and `tests/test_cost.py`:

1. Baseline global model and variant global model resolve differently in estimate
   children, matching execution children.
2. **A variant that sets only the global model resolves every fallback-dependent
   stage — critique, cross-QC, synthesis, focus, review plan — to the variant
   model in both the estimate child and the execution child.** This is the
   regression that an in-process fix passes for the digest and fails for the
   rest. Assert the negative half too: a stage with its own non-fallback default
   (investigation) must *not* move, or the test would pass by resolving
   everything to the variant model. Compare against a fresh process that
   resolves the models independently, not against the script's own helper —
   otherwise a bug in the helper makes both sides agree.
3. Sonnet digest plus explicit Opus critique and cross-QC overrides shows those
   exact stage models in both modes.
4. Batch/real-time environment changes match actual arm transport.
5. Parent environment remains unchanged after success and failure, and is never
   cleared.
6. Estimate-only works with no API key and with a fake client factory that raises
   if called.
7. Unknown-priced models remain unknown, not zero or a partial known-stage total.
8. Both cost dialogs describe specification caching accurately for digest
   transport, including hybrid mode, while the priced totals are unchanged by the
   copy fix.
9. Paths containing spaces work on Windows; no test depends on a particular user
   directory.
10. Output never exposes an environment secret; use obvious fake sentinel strings
    in tests. Redact by variable **name**, not by value shape: a credential that
    does not look like one must still be covered, and the sentinel in the test
    must not itself be credential-shaped or it fails the repo's secret scan.
11. Estimation and execution describe the arm through **one** resolver. Assert it
    structurally (both children call it), not by comparing two hand-maintained
    field lists — two copies agreeing today is exactly the state that drifts.
12. A tile target outside the clamp range reports both the typed value and the
    effective one. An arm priced at a silently clamped target, while the operator
    believes the typed one, is a comparison of something other than what they
    asked for.
13. A child that exits 0 with unparseable output is an error, not a free arm.
    Exit-code checking alone leaves a `$0.00` path open, and `$0.00` is an
    invitation to spend — the one thing this mode exists to prevent.

Do not use live calls to validate process/model resolution. A child can report
its resolved configuration and estimate as JSON without running the pipeline.

## 10. WP-05: cost-preview arithmetic and a measured confirmation-time scan

### 10.1 Pure estimation

Keep `pipeline.estimate_image_tokens_for_set()` as the legacy conservative image
allowance, or introduce an explicitly named successor while preserving
compatibility. Do not silently redefine its existing public meaning to be a
typical estimate.

Add a pure estimate path using optional plain per-page information. Per §2.6 the
inputs that actually move the number are **aspect ratio** and the
**vector/raster/unknown classification**; page dimensions in points are retained
because they are needed to discuss effective DPI, not because token counts depend
on absolute size. Suggested record, final naming left to the implementer:

```text
SheetCostBasis:
    stable source/page reference
    displayed width and height in points   (for DPI discussion; tokens use the ratio)
    classification: vector / raster / unknown
    capped prompt-text character count, if inspected
    geometry availability and inspection-error state
```

Place this small record in `models.py` or a dependency-neutral module so
`render.py` can return it and `cost.py` can consume it without importing each
other cyclically. Do not retain words, raw full text, image bytes, API keys, or
persistent source paths in exported estimate diagnostics.

Image estimate algorithm, for every page and every vision-stage model:

1. Resolve image count using the actual grid plus overview.
2. Resolve target using `tiling.target_long_edge_px()` with the current
   vector/raster/few-image policy. Preserve the ≤20-image branch and override
   restrictions — that branch is deliberate (§2.5).
3. Generate overview dimensions and every tile rectangle using existing geometry
   helpers and the selected overlap.
4. Compute zoom per rectangle with `zoom_for_rect()` and estimated pixel
   dimensions. Document rounding assumptions; use rendered-fixture comparisons to
   set a defensible tolerance. **The assumption is not "round the scaled
   dimension"** — see §2.5: the rasterizer uses `(rect * matrix).irect`, which is
   position-dependent, so two identically-sized tiles can differ by a pixel.
   Mirroring `irect` makes the estimate reproduce real renders exactly rather
   than approximately, which is why the tolerance below is 0.0035% and not a
   percent or two.
5. Estimate tokens through `core.tokenizer.estimate_image_tokens()` for that
   stage's model. The same PNG dimensions can produce different model-tier
   estimates.
6. Include every tile in the planning estimate unless safe suppression has
   actually been measured. Do not predict blank tiles from vector-word absence.
7. For unknown classification, calculate explicit vector/raster scenarios or
   retain the conservative fallback; never label unknown as vector.
8. For invalid geometry, use a clearly reported fallback or unavailable estimate.
   Do not drop the page's cost silently.

Factor the geometry arithmetic once. GUI, command-line estimation, and tests use
the same helper, not independently copied formulas.

### 10.2 Cost scenarios and accounting

Represent estimates as planning scenarios with their assumptions. Retain
backward-compatible existing fields or make any intentional API change explicit
and update all callers. Do not overload `low_cost`/`high_cost` with undocumented
new meanings.

At minimum, expose:

- Geometry-aware planning estimate when page metadata is available.
- Conservative planning scenario/fallback when metadata or cache-hit behavior is
  uncertain.
- Whether estimates assume cold local result caches.
- Models, transports, critique run count, prompt/output assumptions, and pricing
  verification date.
- Unknown-priced stage names and any fallback basis.

Use `core.pricing` rate helpers, including cache-write TTL multipliers, rather
than duplicating dollar constants in the GUI or harness. Estimate digest and
critique imagery independently by resolved model (§2.4). Resolve critique run
count through the runtime's existing resolver instead of fixing the arithmetic at
two when an override is in effect.

Use runtime stage resolvers in **both** standard and exhaustive estimates. In
particular `estimate_drawing_set_cost()` currently prices synthesis/focus using
its digest `model` argument. A Sonnet digest with independently selected Opus
synthesis/focus must price each stage correctly; an unknown-priced active
synthesis/focus stage must make the standard total unavailable, just as in
exhaustive mode. Do not apply charges for an optional stage that will not
execute.

For a real-time critique prefix with `n >= 2` identical sequential reads and the
existing five-minute breakpoint:

- Successful-reuse scenario: one 1.25× prefix write plus `(n - 1)` 0.1× reads.
- No-reuse scenario: `n` 1.25× prefix writes, when each marked request misses.
- A single read without the prefix breakpoint is ordinary input under the present
  implementation.
- Price uncached suffix/input and each output separately. Do not discount output
  with an input-cache multiplier.

**Why two scenarios and not one corrected number.** The flat estimate sits
*between* them, so it is wrong in both directions and neither error is
conservative — at `n = 2` the multipliers are 2.00 flat, 1.35 on reuse, 2.50 on
total miss, i.e. the flat figure over-quotes successful reuse by ~48% and
under-quotes a full miss by ~20%, on the single largest QC line. That is also
why a test asserting the critique component scales *linearly* with run count is
wrong on the real-time path: the breakpoint only exists at `runs >= 2`, so one
read is ~40% of two, not 50%. Assert exact linearity on the **batch** path,
where no breakpoint exists and it genuinely holds.

If the actual request policy changes, resolve it from that policy rather than
keeping these formulas detached. For the current batch implementation, price
ordinary batch input and outputs without assumed cache hits. Server tools and all
synchronous stages keep their own rate rules.

Count known capped sheet-text input separately from fixed system/instruction
overhead. Character-based token estimates are approximate; identify the
heuristic. Do not call a tokenizer that downloads data or a provider endpoint
during preflight. Unknown text length must remain an explicit assumption.

Specification-cache estimates must acknowledge possible concurrent first writers
and TTL expiry. A simple documented reuse/no-reuse scenario is preferable to
inventing an empirical probability without data.

### 10.3 The confirmation-time scan

Revision 1 specified a background metadata worker with generation guards and
its own PDF-ownership discipline. That is deferred. Start smaller and let
measurement decide whether more is warranted.

**Step 1 — measure.** Instrument the scan (`page.rect` plus
`len(page.get_text("words"))`, no rasterization) over real sets of increasing
size. Record scan duration and, separately, **time spent waiting on
`gui.py`'s existing `_preflight_lock`**. `render.py`'s "0.32 s / 8 sheets /
6,636 words" is one measurement on unknown content and is not a bound for
arbitrary sets; dense schedule sheets scale with word count.

**Measured (WP-05b), and it chose against the default below.** Synthetic uniform
E-size pages, medians of 3, via `scripts/measure_scan_time.py`:

| set | fresh cost scan | wait behind a running preflight | derive from the preflight's geometry |
|---|---:|---:|---:|
| 39 sheets × 4,000 w | 2,399 ms | 7,494 ms | 0.1 ms |
| 120 sheets × 4,000 w | **6,896 ms** | **22,457 ms** | **0.4 ms** |

The scan tracks **word count**, not sheet count — ~15 ms per 1,000 words in every
configuration measured, so ~8 ms/page sparse and ~60 ms/page dense. (The same
instrument reproduces `render.py`'s recorded 0.32 s / 8 sheets / 6,636 words to
within 1 ms, which is the check that it is measuring the right thing.) The
preflight is ~3× the scan because it also hashes each page's render identity.

So **item 2 of the default design below is wrong on a large dense set**: a
synchronous scan at the Analyze click is a ~7-second freeze at the moment money
is committed, and waiting on `_preflight_lock` instead can be ~22 s more. Item 3
is the branch the measurement supports, and it is nearly free —
`preflight_sheet_ids` already builds a full `SheetGeometry` per page and keeps
only the sheet id, so emitting a `SheetCostBasis` from the object it discards
costs 0.01% of a fresh scan, inside a lock already held, with no second PDF
owner. Escalating to revision 1's background worker is **not** warranted: the
work is not on the Analyze path at all.

**Step 2 — implement the minimum the measurement supports.** Default design:

1. Keep the live selection summary on the existing conservative allowance. Do not
   replace every refresh with a synchronous scan.
2. Run the improved scan **once, at the Analyze click, before the existing
   confirmation dialog** — the point where money is about to be committed and
   where a short wait is expected.
3. Coordinate with the existing profile preflight rather than adding a second PDF
   owner. Prefer **reusing** its results: `profiles.preflight_sheet_ids()`
   already obtains geometry through `iter_sheet_prescan()`. If a preflight is in
   flight, either consume its result or wait on `_preflight_lock` with visible
   progress — never block the Tk thread silently on a contended lock.
4. Show a clear pending state while the scan runs, and fall back to the
   conservative estimate if it fails or exceeds a bounded time.

Escalate to a background worker with generation guards **only if** the measured
scan plus lock wait makes the confirmation-time design unacceptable on real sets.
If it does, revision 1's §9.1–9.2 design is the specification to return to; it
was deferred, not refuted.

Add or reuse a lightweight scanner inside `render.py` that emits
`SheetCostBasis` records without rasterizing, creating model clients, hashing
full render dependency graphs, or retaining PDF objects after the operation.
Determine vector/raster classification consistently with rendering; do not equate
any nonempty raw text with nonempty extracted words when the renderer uses the
latter.

Note that `list_sheets()` also opens PDFs, for page counts only. It must not run
concurrently with the scan or with analysis PDF access.

Do not add a persistent metadata database, new network preflight, or automatic
paid probe.

### 10.4 User-facing wording

Use plain language such as "Estimated cost" and "Conservative planning estimate."
State that detail, generated findings, retries, and cache reuse affect actual
cost. Do not label a hypothetical range as a statistical confidence interval or
guaranteed maximum.

Keep implementation details out of the primary confirmation. A compact
assumptions line can state page information available, transport, and expected
cache behavior. Retain per-stage model attribution for exhaustive mode.

### 10.5 Test matrix

- Default vector E/D/B/A shapes and non-square aspect ratios.
- **Scale invariance holds in both regimes:** two pages of the same aspect ratio
  and different physical size produce identical image-token estimates at 6×6 /
  1560 **and** at 3×3 / 2576. Do not assert the ≤20 branch is scale-sensitive —
  it is not (§2.6).
- **Aspect sensitivity differs by regime:** at 6×6 / 1560, 34×44 and a square
  page differ by about 20%; at 3×3 / 2576 they are identical because every image
  clamps to the model token cap. Assert the small-grid branch on its target, its
  cap clamping, and its image count instead.
- Raster sheet classification; unknown classification fallback.
- 6×6, 5×5, 3×3, and 2×2 grids, including the ≤20-image target branch.
- Overlap zero, shipping overlap, and an explicit experimental overlap.
- Vector target override, and that it does not override raster/few-image targets.
- Rotated displayed dimensions; nonzero CropBox fixture where actual rendered
  dimensions are compared.
- Hi-res digest model with non-hi-res critique model and the reverse.
- Standard mode with independently overridden synthesis/focus models, including
  an unknown-priced active stage and an inactive optional stage.
- Different critique run counts and corresponding prefix-cache policy.
- Economy, Hybrid, Fast, and explicit mixed transports.
- Short, long, absent, and unknown sheet text; specification text by transport.
- Unknown price propagation; no partial sum presented as the whole total.
- Output and synchronous-stage charges not batch/cache-discounted incorrectly.
- A pricing multiplier change in the central helper changes all applicable
  previews consistently.
- GUI: stale selection during a scan, damaged PDF, cancellation, window close,
  and no request or upload before the existing confirmation.

Use dimensional and arithmetic invariants, not large string snapshots. Keep a few
hand-calculated examples for independence from the implementation — §2.5 and
§2.6 supply verified values. Rendered fixture tests should validate rounding and
conservative allowances, not demand the exact pre-render estimate equal every
rasterized pixel count.

Add a short Windows manual acceptance checklist covering rapid file replacement,
option toggling, a pending scan at Analyze, a damaged PDF, cancellation, and
window close.

## 11. WP-06: extend the existing A/B harness for auditable experiments

### 11.1 Preserve actual usage by stage

`summarize_run()` already records per-family token/call totals, **already
includes per-model cost**, and **already tallies the `confidence` enum**. Treat
those as preservation checks, not new work. The gap is family-level dollar cost
and the transport/cache axes. Extend the existing JSON summary rather than
building another benchmarking system.

Record:

- Per-family cost alongside the existing per-model cost, tokens, and calls.
- Transport breakdown, cache-read/write tokens, requested write TTL when
  applicable, and unknown-price status.
- Successful responses, failed attempts, non-billable abandoned attempts, and
  local cache hits where those distinctions are actually recorded, without
  conflating them into one "paid calls" number.
- Actual resolved stage models, run mode, transports, grid/overlap/target policy,
  prompt versions or existing request-contract identifiers, and source
  composition.
- Relevant status/completeness fields; an incomplete arm cannot be treated as a
  comparable cost win.

Prefer serializing the existing sanitized usage records or canonical
aggregations. Do not create a second independent billing calculator. Preserve
`None` for unknown costs.

The current pipeline aggregates some verification work into one usage record.
Record counts are therefore not universally individual API-call counts. Label
aggregation granularity and unavailable attempt counts explicitly; do not expand
this package into a rewrite of every stage's telemetry or invent precise call
counts from aggregated tokens.

### 11.2 Finding-level comparison artifacts

Before the temporary arm workspace is deleted, persist compact finding records
alongside its summary. Include source identity/page, sheet ID, category,
severity, finding text, source quote, all cross-sheet legs, anchor
tiers/rectangles, confidence, verification disposition, evidence-trust state from
WP-03B, and provenance. Preserve original finding IDs as references.

Do not use `QC-###` as a stable identity: numbering is positional. Do not assume
`Finding.id` alone is sufficient: `compute_finding_id` hashes only sheet id,
category, quote-or-text and source id (`models.py`, line 557) — legs and severity
are excluded, so two conflicts sharing a primary quote with different secondary
legs collide on one id.

Use deterministic matching tiers:

1. Exact comparable finding/leg identity with compatible critical attributes.
2. Candidate matches for human review when wording differs but
   source/geometry/legs suggest overlap.
3. Explicit unmatched baseline findings, unmatched variant findings, and
   ambiguous many-to-many candidates.

Only the first tier may be called an exact match. Do not automatically delete
unmatched items, stamp semantic equivalence using a loose fuzzy score, or ask
another paid model to adjudicate by default. Keep source correspondence stable
within the same input set and separate from absolute paths.

Preserve human-review navigation. If artifact links are emitted, copy the needed
existing artifacts before temporary cleanup and use portable relative links. Do
not emit links into a deleted temporary directory. Keeping a full duplicate
reviewed PDF/evidence tree is optional; compact JSON plus source/page references
is the minimum required output.

### 11.3 Correct the quality-screen interpretation

Keep the existing aggregate signals as warning indicators, but change claims that
a falling count **proves** real defects went unseen. A count drop can reflect
missed defects, noise removal, dedup behavior, or model variance. A flat count
can hide replacement of a real issue by another false positive.

Report a large count drop as a review requirement. Preserve existing threshold
behavior unless a separate measured justification changes it. "No concerns
detected" must remain distinct from "quality approved." The `confidence` enum is
already what the harness tallies — keep it, and do not substitute the legacy
`reproduced` boolean.

Add an explicit comparison-validity status for failed/partial arms, mismatched
retained-sheet populations, and missing cost data. Present their diagnostics, but
do not advertise their lower total as comparable savings.

After WP-03B, add evidence-trust composition to the comparison: an arm whose
finding count held up on reduced-trust, unverified legs is not equivalent to one
whose findings were text-grounded and verified.

### 11.4 Explicit geometry controls for experiments

Keep existing environment-based `--baseline` and `--variant` syntax compatible.
Add typed per-arm overlap options, preferably `--baseline-overlap` and
`--variant-overlap`, forwarded to both estimate-only and execution children as
the same `overlap_frac` pipeline argument.

Validate finite numbers and a documented supported range before any costly work.
Reject NaN/infinity rather than allowing them into tiling or cache keys. Preserve
the shipping overlap when omitted. Record resolved values, not only the
command-line spelling.

The existing render identity serializes overlap to four decimal places
(`render.py`, line 509, `f"overlap={overlap_frac:.4f}"`). Restrict new harness
overlap values to at most four fractional decimal places, rejecting finer
precision rather than silently rounding, unless a separately reviewed
identity-contract fix makes finer values distinct. Otherwise two different
rendered overlaps could share a level-one key. This restriction does not certify
every existing direct API caller; record the broader precision issue separately
if needed.

The same-configuration guard currently compares whole environment dictionaries
(line 495). Replace it with a comparison of effective reviewed parameters. A
changed irrelevant environment variable is not a meaningful experiment, and an
overlap-only change must not be rejected as identical. Include intended options
in the shared arm specification; do not use an unrestricted snapshot of the
entire environment as the experiment identity.

Do not add production per-sheet adaptive grids here. Explicit run-level grid
options may be added only if needed for the documented experiment and routed
through the same estimate/execution contract; they must not bypass the current
target policy.

### 11.5 Required tests

- Per-family costs reconcile with existing run totals for complete priced
  records; existing per-model cost and `confidence` fields are preserved.
- Unknown prices, zero use, cache-only stages, retries, and non-billable attempts
  remain distinguishable.
- Existing summary fields continue to load; version new experiment output
  contracts if needed.
- Same finding after positional renumbering is comparable; identical primary
  quote with different secondary legs is not collapsed.
- Changed quantities/tags/polarity cannot become an exact match merely because
  geometry overlaps.
- Identical count/mix with one baseline finding replaced still exposes the
  unmatched records.
- Ambiguous candidate matches remain explicitly unresolved.
- Partial or failed arms do not receive a comparable-savings verdict.
- Evidence-trust composition is reported and an arm cannot be called equivalent
  on count alone.
- Overlap reaches both estimate and actual pipeline kwargs; omitted values retain
  defaults.
- Invalid numeric arguments, including unsupported overlap precision, fail before
  child execution; equivalent configurations are rejected consistently. Distinct
  accepted overlaps produce distinct relevant render/cache identities.
- Saved links, if included, resolve after temporary arm cleanup.
- No raw environment secret appears in console, JSON, or Markdown/text comparison
  output.

### 11.6 Implementation notes (WP-06b, recorded after building §11.2/§11.3)

Five things the specification left open, and how they were resolved.

**1. What "identity" means in this codebase.** §11.2 puts wording differences in
tier 2, but a finding's identity here is *quote-anchored*: `compute_finding_id`
hashes quote-or-text, so two records with the same verbatim on-sheet quote and a
differently-worded description are the same finding by the system's own
definition. Tier 1 therefore accepts them — guarded by the critical-signature
check, which is what catches a rewording that changed a quantity, a tag, or an
absence polarity — and sets `text_changed` so the reviewer is told. Demoting
every rewording to tier 2 would have filled the candidate list with the most
common benign difference there is and buried the real ones.

**2. The compatibility rule had to be made public.** §11.2's "compatible
critical attributes" is exactly `critique._signatures_compatible`, which was
private. It is now `critique.critical_signature` (data) +
`critique.signatures_compatible` (the rule), with the private helper delegating.
Reimplementing it in the harness was the obvious path and the wrong one: this
harness already restated `RunUsage.is_billable_but_unpriced` once and the two
copies disagreed within a commit.

**3. The `Finding.id` collision is asserted, not assumed.** The plan states that
two conflicts sharing a primary quote with different legs collide on one id.
`test_finding_id_collides_on_different_legs_but_identity_does_not` asserts the
collision *still exists* before checking that the comparison identity separates
them — so if `compute_finding_id` ever starts hashing legs, the test fails loudly
instead of quietly protecting against a gap that closed.

**4. Ambiguity needs connected components, not per-record degree.** Checking
"does this base record have exactly one candidate" is not enough: a chain
b1–v1–b2 gives v1 two claimants while b2 has only one, and a degree test would
pair b2 with v1 and leave b1 unmatched — an arbitrary choice presented as a
result. The matcher takes connected components of the bipartite candidate graph
and resolves only 1:1 components; anything else is reported as ambiguous with
every record named. Same discipline as `cross_qc.fact_tile_lookup`: a collision
loses rather than picks.

**5. A flat count is a note, not a concern.** §11.3 asks for both the count-drop
signal and the flat-count caution. Implemented as one `concerns` entry and one
`notes` entry respectively, because the flat case is the *most ordinary outcome
there is* — firing a concern on it every run would train an operator to skim the
concern list, which is the only part of the report that must never be skimmed.
`clean_screen` and `screen_result` are driven by concerns only.

## 12. WP-07: repository documentation and focused editing

Update `README.md`, `CLAUDE.md`, `docs/PERFORMANCE_AND_COST_VALIDATION.md`,
affected docstrings, and the appropriate changelog section. Do not rewrite the
historical external brief; record corrected decisions in maintained repository
documentation.

Required corrections:

1. Explain capped prompt text, full host evidence text, and complete
   word-coordinate text as distinct representations with explicit consumers.
2. Document the sharded grounding fixes — both the tail case and the
   visual-evidence case — the three-state evidence outcome, and the scoped
   cross-QC cache handling for each. State plainly that WP-03A preserved existing
   cross-QC caches and WP-03B invalidated them, and why.
3. Document that recovered findings can increase downstream verification,
   investigation, and cost.
4. Explain cold render reuse through the spool and the fallback case; remove the
   statement at `docs/PERFORMANCE_AND_COST_VALIDATION.md` line 107 that every
   cold exhaustive run rasterizes twice.
5. Distinguish three vision reads from three full-price image reads; explain that
   actual cache usage records determine cost.
6. Replace guaranteed/"slightly high" invoice claims with explicit planning
   assumptions and fallback basis.
7. Describe batch specification input accurately in both cost dialogs and help
   text.
8. Document that model-variant estimates resolve in their own processes, and
   **why** an in-process fix is insufficient (the `REVIEW_MODEL_DEFAULT` fallback
   chain, §2.4).
9. Describe the few-image 2576 target branch as deliberate policy and note the
   limited scope of the vector-target override.
10. Document that image-token estimates are scale-invariant in the >20-image
    regime and cap-dominated in the ≤20-image regime.
11. Present overlap savings as approximate preservation of interior resolution,
    with reduced edge/overview resolution and changed boundary context.
12. Correct quality-screen claims: counts, anchoring, and agreement are warnings,
    not a recall oracle. Document finding-level review outputs.
13. Fix the stale comment at `core/api_config.py` line 57, which claims
    verification escalation is reserved for CRITICAL/HIGH UNVERIFIED findings.
    `README.md` lines 854 and 1266 already describe investigation correctly and
    need no change; do not rewrite them.
14. Update `pipeline.py` line 2373's stale claim that digest images are gone
    before critique.
15. Use project-adopted edition wording consistently; do not describe "latest" as
    a substitute for evidenced adoption.
16. Fix stale predecessor-product terminology in touched docstrings when it
    obscures actual behavior. Do not delete unused public helpers merely because
    the brief calls them dead.

Two revision-1 documentation items were dropped as already satisfied: the
`confidence` versus `reproduced` distinction is already implemented and already
what `summarize_run()` reports, and the investigation-eligibility description in
`README.md` is already correct.

Re-derive cost examples through the updated pure estimator. Label formula
examples separately from observed runs. Do not update `PRICING_EFFECTIVE_DATE`
just because this document is newer; change it only after verifying the actual
rate table against official pricing.

### 12.1 Implementation notes (WP-07, recorded after the documentation pass)

Every item was checked against the current code before being written up. Two of
this section's own statements did not survive that check, and one class of item
turned out to be already satisfied.

**Item 13 was understated.** The stale comment did not merely misdescribe the
escalation trigger; it named a stage that does not exist. `verify.py` resolves
one model (`default_verify_model()` → `VERIFICATION_MODEL_DEFAULT`) and never
escalates — `VERIFICATION_ESCALATION_MODEL` is consumed by `investigate.py` and
priced by `cost.py`. Investigation's trigger is an **anchored UNCERTAIN** verdict
at any severity, ordered severity-first within a per-run budget, not a
CRITICAL/HIGH threshold. And `UNVERIFIED` is not one of `VERIFICATION_STATUSES`
at all. The same confusion had propagated into `CLAUDE.md`'s refusal-fallback
bullet ("`verify.py`'s escalation calls"), which is corrected with it.

**Item 2's cache claim was imprecise.** "WP-03B invalidated them" is true in
effect but wrong about the mechanism, and the mechanism is what a maintainer
needs. Invalidation came from the **edited map prompt**, which rides every
cross-QC cache key — deliberately one mechanism, not a contract bump beside it.
`_CROSS_QC_CACHE_CONTRACT` is at 2 for an unrelated earlier reason (entries
stored as `complete` after a silent truncation, before the findings cap became
loss-aware), so a reader who attributes the 2 to the evidence work will
mis-date it. The README now says so explicitly.

**Four items needed no change, and that was verified rather than assumed.**
Item 1 (three text representations with explicit consumers, `words` included) is
already in `README.md`. Item 12 was satisfied when the harness work landed. Item
8 is documented in `docs/PERFORMANCE_AND_COST_VALIDATION.md`, fallback chain and
all. Item 16 found no stale predecessor-product terminology anywhere in the
tree. Item 7 was half-satisfied: the cost dialog already priced the batch spec
path correctly and said so; only the help text was silent, so only the help text
changed.

**Item 10 was written up wrong on the first pass, and review caught it.** The
first draft of the WP-07 documentation said the >20-image regime was
"scale-invariant" and "cap-dominated". §2.6 says neither: it lists the render
**target** among the variables that move the count, and states plainly that the
largest possible image at 1560 px is 3,245 tokens against a 4,784 cap, so
nothing clamps. Dropping the target from that list inverted the guidance on the
single highest-leverage cost knob in the app. Re-measured through
`cost.estimate_image_tokens_for_bases` on an E-size vector sheet at 6×6, Opus 5:
1400 px = 0.806×, 1240 px = 0.632×, 1100 px = 0.498× — quadratic in the target
to three decimals, and matching the percentages already in `README.md`'s env-var
table. The invariance that does hold is to the page's **physical size** (48×36
in, 24×18 in and 12×9 in all cost 90,276 tokens), which is the claim §2.6 is
making. The corrected text now names what it is invariant *to*, since
"scale-invariant" alone is what allowed the misreading.

**Item 7's first draft understated the cached-spec cost.** "Paying for the specs
roughly once" is wrong by an order of magnitude: real-time is one 1.25× write
plus 0.1× per remaining sheet, so 100 sheets is ~11 copies, not ~1 (and more
under concurrency, since each sheet in flight before the first response pays a
write). Batch is ~50 copies across the same 100 sheets — half a copy each, not a
full one, because batch input is half rate. The help text now carries both
figures.

`PRICING_EFFECTIVE_DATE` is deliberately untouched, per this section's own
instruction: this document being newer is not evidence about the rate table.

## 13. WP-08: integration, review, and acceptance

### 13.1 Focused test groups

Run tests appropriate to each package while implementing. The following
PowerShell examples assume the repository virtual environment has been verified
to use a supported interpreter:

```powershell
# Evidence retention, grounding, location, cache, and render reuse
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_drawing_models.py tests/test_drawing_render.py tests/test_drawing_anchor.py tests/test_drawing_verify.py tests/test_drawing_cross_qc.py tests/test_drawing_stage_cache.py tests/test_drawing_cache_identity.py tests/test_render_spool.py

# Estimation, geometry, configuration parity, and experiment records
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_cost.py tests/test_ab_sweep.py tests/test_drawing_tiling.py tests/test_drawing_tokens.py tests/test_drawing_cost_optimization.py tests/test_model_capabilities.py

# Integration and unchanged request/receipt contracts
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_drawing_digest.py tests/test_drawing_critique.py tests/test_drawing_batch.py tests/test_drawing_batch_critique.py tests/test_drawing_qc_pipeline.py tests/test_drawing_acceptance.py tests/test_drawing_usage.py tests/test_import_isolation.py
```

If a listed suite has moved, use its current equivalent. Do not run all groups
repeatedly without a new change or failure justifying it.

After integration, run the full hermetic suite with network tests explicitly
excluded, plus applicable release checks:

```powershell
& .\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -m "not network and not browser"
& .\venv\Scripts\python.exe scripts/benchmark_drawing_analyzer.py --check --sheets 8 --repeats 5
& .\venv\Scripts\python.exe scripts/run_acceptance.py
```

**Once WP-01 has landed, `run_acceptance.py` is hermetic on its own** and needs
no wrapper. Until then, isolate it explicitly:

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

Inspect the current acceptance script before execution and use its documented
hermetic mode if its interface has changed. Record actual output, including skips
and environment failures. Run the existing browser-security gate when report
generation changes or as the normal release gate; do not represent a skipped
browser suite as passing.

The eight-sheet benchmark checks existing mechanical regressions. It does not
replace WP-03's separate dense-text memory/scaling measurement. Record that dense
fixture's size, page count, repeated-run timings, and peak retained memory
separately; do not claim the stock benchmark establishes those properties.

The reviewed CI matrix is Linux Python 3.11/3.12 and Windows Python 3.11 (
`.github/workflows/ci.yml`, lines 66–68); the external brief described a broader
Cartesian matrix. Use the actual workflow and document any separately run
Windows/Python coverage. Retain existing correctness lint, dependency/license
checks, wheel build, and installation smoke as release gates. This work does not
itself require dependency changes.

### 13.2 Independent review checklist

- [ ] The acceptance runner cannot reach the network with a real key present, and
      a regression guards it.
- [ ] Coverage/truncation/locatability were measured before the evidence fix was
      finalized, and the measurement is recorded, with each number labelled by
      tier — zero-call (§7.1) or the instrumented run (§7.2). A
      surviving-finding distribution is not reported as a discard rate.
- [ ] The original tail-evidence failure was demonstrated before the fix.
- [ ] Textless, hybrid, and missing-quote failures were demonstrated before the
      fix, and the hybrid case does not pass merely because `is_raster` is true.
- [ ] Real evidence survives; fabricated or wrong-sheet evidence still fails
      textual grounding.
- [ ] A recovered finding is locatable and actually reaches
      `verify._has_anchored_legs` and `investigate._candidates`.
- [ ] **Cross-shard** (reconcile-produced) findings are locatable, not only
      per-shard map findings, and their tile is derived from a host-side join to
      the sent facts rather than supplied by the model.
- [ ] The tile fallback in `_anchor_one` applies **only** to legs explicitly
      marked reduced-trust; an unmatched quote on text-bearing evidence still
      returns `quote_not_found`, and digest/critique/whole-set anchoring is
      unchanged.
- [ ] An unquoted leg is never more trusted than an unmatched one.
- [ ] Reduced-trust findings are visibly distinguished everywhere they appear.
- [ ] All cold, prescan, and spool paths carry the new field.
- [ ] Prompt bytes and production quality defaults are unchanged except the
      documented sharded map-prompt tile request.
- [ ] **WP-03A preserved existing cross-QC cache keys byte-identically**, and no
      contract bump was applied to it.
- [ ] **WP-03B invalidated affected results by exactly one mechanism**, named in
      the log.
- [ ] Unaffected digest/critique caches remain valid; no indiscriminate schema
      bump was used. Dense cross-QC cases retain existing budget degradation and
      cache ineligibility.
- [ ] Estimates and execution resolve identical stage models — including
      fallback-dependent stages under a global-model variant — transport, and
      geometry options.
- [ ] Image counts are model-tier aware; pricing distinguishes input, output,
      cache, and batch correctly.
- [ ] Estimates never present partial known prices as a complete total or a
      planning bound as a guarantee.
- [ ] The confirmation-time scan's duration and lock-wait were measured, and any
      escalation to a background worker is justified by that measurement.
- [ ] GUI preview scanning cannot freeze ordinary interaction or race analysis
      PDF access, and coordinates with the existing profile preflight.
- [ ] A/B records expose unmatched/ambiguous findings, incomplete arms, and
      evidence-trust composition.
- [ ] Finding counts and agreement rates are not asserted to prove recall.
- [ ] Full text does not leak into logs or unbounded model/report context.
- [ ] Existing deterministic ordering, provenance, ledger lifecycle, and
      saved-PDF receipt checks pass.
- [ ] Documentation reflects the implementation and clearly separates measured
      from hypothetical savings.

### 13.3 Release evidence

Provide a concise implementation report with changed behavior, before/after
regression examples, tests and environments, cache invalidation scope and the
mechanism used, performance observations, new estimate assumptions, measured scan
timings, and remaining deferred questions. Include Windows manual GUI results if
the WP-05 scan is implemented. Do not claim cost or quality improvement from
hermetic fake-client tests.

Use small package commits so a defective estimate enhancement can be reverted
without reverting the evidence fixes. Reverting WP-03B requires preserving a
contract revision or prompt identity that cannot load incompatible cached
results. Do not downgrade a cache contract counter to an older acceptance
meaning.

## 14. Measurement packages: no default changes before evidence

The immediate corrective release can complete without a paid experiment. The
packages below are subsequent research decisions, not hidden release blockers.
Reuse the improved A/B harness and existing benchmark/release record process.

**Order changed in revision 2:** R-04's zero-call half is now WP-02 §7.1 and runs
first; its measured half precedes R-01 and R-02, because it bounds review quality
rather than cost.

### 14.1 Common experiment protocol

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

### 14.2 R-04: text budget and evidence coverage (**now first**)

WP-02 §7.1 supplies the zero-call half: how often truncation occurs, by sheet
type, plus the textless/hybrid population and the surviving-finding anchor-tier
distribution. WP-02 §7.2 adds the discard rate from one instrumented run. The
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
layer (§2.1). The 4,000-character budget bounds direct source-text evidence, not
the stage's whole information input; frame the experiment accordingly.

Do not infer "25× cheaper per unit of information" from a text-vs-image token
ratio. They represent different information, and token cost does not establish
equivalent evidence content.

### 14.3 R-01: Sonnet digest with Opus critique

Priority: first model-cost experiment after tooling is trustworthy and WP-02's
measurements are in hand.

Use existing routing. In the environment-based harness, set the global digest
default to Sonnet and explicitly keep critique and cross-QC on Opus before the
child imports application modules. Resolve and compare every other stage too; if
another stage inherits the global default, pin it so the experiment remains
digest-only (this is exactly the fallback chain of §2.4 — WP-04's regression 2
proves the harness reports it honestly). The public `model=` parameter is another
valid entry point.

Measure digest transcription, digest-origin findings, downstream cross-QC
effects, and known-defect retention. The nominal 60% per-token rate reduction on
the digest is not guaranteed stage savings: tokens, thinking, retries, and
findings can change. Capability flags prove request compatibility, not equal
quality. No new digest environment variable is prerequisite.

### 14.4 R-02: overlap/target rebalance

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

### 14.5 R-03: per-sheet adaptive grids

Priority: after R-04/R-01/R-02 measurements; requires its own design review.

Do not call this low risk merely because page rectangles remain covered. A
letter-size PDF may be a reduced large-format drawing; physical DPI alone is
insufficient evidence of legibility — and per §2.6 physical size does not enter
the token estimate at all, so a cost model cannot be used as a legibility proxy.

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

Use the corrected mixed-set arithmetic in §2.5 as a hypothesis. Actual savings
require the real sheet mix, suppression, and usage. No adaptive default is
included in the immediate work.

### 14.6 R-05: batch first-pass verification

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

### 14.7 R-06: shared digest/critique prefix

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

## 15. Explicit non-goals and rejected shortcuts

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
  same change — either alone invalidates everything (§2.3).
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
  (§2.6).
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

## 16. Ready-to-use agent assignments

### Integrator (WP-00, WP-01)

Establish the baseline. Land the acceptance-runner network exclusion first, on
its own, with a regression that fails if an unfiltered broad `pytest` invocation
returns to that script. Own final integration, the changelog, and the release
evidence.

### Evidence implementer (WP-02, WP-03A, WP-03B)

Measure first: truncation frequency, the textless/hybrid population, and
locatability — the zero-call tier (§7.1) unconditionally, and the discard rate
(§7.2) if a run is budgeted; never report the first as if it were the second. Then land WP-03A — full host evidence with explicit
unavailable/empty semantics, the two sharded validation paths, and a
**conditional** cache field that preserves every existing key with **no contract
bump**. Then land WP-03B — the three-state evidence outcome, the closed
missing-quote bypass, and the sharded location route so recovered findings
actually reach verification and investigation. Prove true-tail acceptance,
textless and hybrid recovery, false-quote rejection, unquoted-leg trust ceiling,
cold/warm/spool parity, prompt stability outside the documented map-prompt
change, and the correct cache outcome for each package separately. Report any
broader text-consumer issue separately instead of expanding scope silently.

### Cost and harness implementer (WP-04, WP-05, WP-06)

Resolve estimate arms in the same fresh-process environment as execution, and
keep the recorded reason the in-process shortcut was rejected. Correct
specification-cache wording without touching the already-correct arithmetic. Add
optional shape-aware pure estimates with stage-specific model tiers and explicit
cache scenarios; preserve legacy conservative helper semantics. Measure the
confirmation-time scan before building any background worker. Extend existing A/B
outputs with reconciled stage costs and finding-level review records, preserving
the per-model cost and `confidence` fields that already exist, then add explicit
overlap controls. Do not change production routing or quality defaults.
Coordinate shared model/render interfaces with the evidence implementer before
editing them.

### Independent reviewer (WP-08)

Review behavior against this plan rather than accepting passing snapshots as
proof. Focus on: whether recovered findings are actually verifiable rather than
merely admitted; whether WP-03A preserved cache keys and WP-03B invalidated them
by exactly one mechanism; whether a global-model variant resolves every
fallback-dependent stage identically in estimate and execution; stale
asynchronous metadata; secret exposure; and invalid A/B matching. Verify that
research-only decisions have not entered shipping defaults. Report exact
remaining gaps and the release scope that actually passed.

## 17. Completion criteria

The full immediate plan is complete when WP-00 through WP-08 are implemented and
reviewed, meaningful regressions pass, the full applicable hermetic/release
checks are recorded, Windows behavior is verified for GUI changes, and the owner
has a clear statement of cache consequences and deferred experiments.

WP-01 ships on its own, first. WP-02 and WP-03A may ship as a second increment.
WP-03B may follow independently. Describe any such increment as a partial
delivery of this plan, not completion of every package.

Paid research and default changes are separate deliverables. Do not hold the
grounding fixes indefinitely for an optimization study, and do not promote an
optimization merely to mark every research row complete.

## 18. References

- Repository baseline: `89c8ecb`; function names, file paths and line numbers
  cited throughout this document were verified at that commit.
- External input: `drawing-analyzer_REVIEW_BRIEF.md`, supplied by the owner;
  several claims corrected in §2.
- Independent review of revision 1, 2026-09-08: arithmetic re-derived and
  confirmed; scope and cache corrections folded into this revision per §0.
- [Anthropic model and cache pricing](https://platform.claude.com/docs/en/about-claude/pricing)
  — checked during the 2026-09-08 review; recheck before relying on rates in a
  later release.
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
  — prefix identity, TTL multipliers, and best-effort batch support.
- [Anthropic batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)
  — provider batch behavior; distinguish it from current application policy.
- Existing repository qualification process:
  `docs/PERFORMANCE_AND_COST_VALIDATION.md`,
  `docs/RELEASE_ACCEPTANCE_TEMPLATE.md`, `docs/WINDOWS_ACCEPTANCE.md`,
  `.github/workflows/ci.yml`.
