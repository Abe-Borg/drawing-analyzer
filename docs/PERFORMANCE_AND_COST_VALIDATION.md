# Performance, memory & cost qualification (Phase 27, §19.7)

This document defines the measurement scenarios, the required gates, and the
recording template for a release candidate. Numbers are judged on **medians of
repeated runs**, never single runs. The harness is
`scripts/benchmark_drawing_analyzer.py`; it writes
`benchmark_report.{json,md}` for attachment to the release record.

## How to run

```bash
# Hermetic (free): the analyzer itself — render, cache, ledger, markup, export
python scripts/benchmark_drawing_analyzer.py --check --sheets 8 --repeats 5

# Live (billable): real tokens/costs on a representative approved set
ANTHROPIC_API_KEY=... python scripts/benchmark_drawing_analyzer.py \
    --live --pdf setA/M-101.pdf --pdf setA/E-201.pdf [--exhaustive]
```

`--check` turns the mechanical gates below into hard failures (nonzero exit).

### A/B-ing a cost lever against quality

```bash
# Price both arms first — spends nothing, needs no API key
python scripts/ab_sweep_drawing_analyzer.py --pdf setA/M-101.pdf \
    --variant DRAWING_ANALYZER_CRITIQUE_MODEL=claude-sonnet-5 --estimate

# Then run it (billable, both arms cold)
ANTHROPIC_API_KEY=... python scripts/ab_sweep_drawing_analyzer.py \
    --pdf setA/M-101.pdf --pdf setA/E-201.pdf \
    --variant DRAWING_ANALYZER_TILE_TARGET_PX=1240 --out ab_out
```

`--estimate` prices each arm in a **fresh child process**, the same
configuration boundary a real arm crosses (WP-04 §9.1). This is not tidiness.
`REVIEW_MODEL_DEFAULT` is an `os.environ.get` evaluated at module scope in
`core/api_config.py`, and six stages resolve through it — the digest plus five
whose resolvers read `os.environ.get(<their own var>) or REVIEW_MODEL_DEFAULT`
(critique, cross-QC, synthesis, focus, review plan). Setting
`DRAWING_ANALYZER_MODEL` in the parent after import moves none of them, so the
estimator used to price a global-model variant at the **baseline's** figure: a
10-sheet exhaustive Sonnet arm quoted $28.59, the Opus number, against a true
$11.60. It was not imprecise about the arm; it never priced the arm.

The estimate output names the stages the two arms actually disagree on, which is
where the fallback effect becomes visible:

```
  baseline  $8.68 - $9.16             (real-time)  defaults
  variant   $3.51 - $3.98             (real-time)  DRAWING_ANALYZER_MODEL=claude-sonnet-5

Stage models that differ between the arms:
  stage         baseline               variant
  critique      claude-opus-5          claude-sonnet-5
  cross_qc      claude-opus-5          claude-sonnet-5
  digest        claude-opus-5          claude-sonnet-5
  focus         claude-opus-5          claude-sonnet-5
  review_plan   claude-opus-5          claude-sonnet-5
  synthesis     claude-opus-5          claude-sonnet-5
```

Estimation is local inspection only — no client is constructed, nothing is
uploaded, no batch is created, no cache is touched — so it runs with no
`ANTHROPIC_API_KEY` at all. A failed estimate raises rather than printing a
zero-cost arm, and an arm setting whose **name** looks credential-bearing
(`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`) is redacted from every
printed label and from the saved `diff.txt`.

#### Sweeping tile overlap

```bash
# An overlap-only experiment — not expressible before WP-06
python scripts/ab_sweep_drawing_analyzer.py --pdf setA.pdf \
    --baseline-overlap 0.04 --variant-overlap 0.16 --out ab_out
```

Overlap is a typed per-arm option rather than an environment variable, forwarded
to the estimate child and the execution child as the same `overlap_frac`
pipeline argument. Values are validated **before** any child runs: finite,
within `[0.0, 0.5]`, and at most **four** decimal places — because the render
identity records `f"overlap={overlap_frac:.4f}"`, so two values differing in the
fifth decimal render different pixels while sharing a level-1 cache key, and one
arm would be scored against the other's cached renders. Finer precision is
rejected rather than silently rounded: rounding runs an experiment the operator
did not ask for and reports it under the label they typed.

Note that `--estimate` cannot see an overlap difference, and says so. The
estimate prices the conservative allowance — sheets × images-per-grid × a square
at the target — and every one of those terms is overlap-invariant. Overlap
changes the rendered *rectangle*, which only the shape-aware path sees, so the
difference appears in the run's actual image tokens.

The same-configuration guard now compares the arms' **reviewed parameters**
rather than whole environment dictionaries. The old comparison failed in both
directions: an irrelevant variable differing between two shells defeated it, and
an overlap-only experiment could not be expressed at all.

#### What each arm's summary records

Beyond the three quality signals, `arm_*.json` carries per-family **cost** (not
just tokens — otherwise "the critique got cheaper" cannot be told from "the
critique did less work"), and a `usage_axes` block for the axes the family and
model rollups drop:

| axis | why it is separate |
|---|---|
| transport (REAL_TIME / BATCH / CACHE) | two arms can be token-identical and differ by half on rate alone |
| cache read / write tokens, and the requested write TTL | separately priced multipliers on the input rate — 1.25× for a 5-minute write, 2× for one hour. Folded into "input", a prompt-cache experiment is unmeasurable |
| outcome: served / cache hit / abandoned / parse-failed / failed | a served cache hit costs nothing; an abandoned batch attempt costs nothing *and* produced no response; a failed-parse call consumed real tokens. Collapsed into one "paid calls" number, an arm that abandoned half its batches reads as a saving |
| `unpriced_records` | the honest companion to a `None` cost: it separates "no model price" from "no usage" |

Nothing here re-prices anything. Every dollar figure comes from the run's own
`UsageRecord.estimated_cost`, computed at its own rate class; this is a view over
the append-only ledger, not a second billing calculator. `record_granularity`
states in the output that the pipeline aggregates some verification work into one
record, so a record count is not universally an API-call count.

The summary also carries `evidence_trust` (the per-unit grounding composition
described above) and names its finding-record sidecar in `findings_records`, as
a bare filename — the arm ran in a directory nobody else has.

The hermetic suite cannot answer whether a cheaper configuration still finds the
same defects — the §19.1 gauntlet routes canned responses by system-prompt
identity and never reads the model id, so a model swap changes nothing it
returns. This harness runs the same set twice, cold on both arms, with one
variable changed, and reports cost against **four signals that need no ground
truth**:

| Signal | Regression looks like |
|---|---|
| Anchor tier mix (EXACT/FUZZY/TILE/**UNANCHORED**) | UNANCHORED share rises — the documented hallucination signal |
| Verification verdict mix (VERIFIED/REJECTED/UNCERTAIN) | REJECTED share rises — more false positives |
| Self-consistency (REPRODUCED/SINGLETON) | REPRODUCED share falls — the two reads agree less |
| Evidence trust, per grounded unit (WP-03B) | reduced-trust **unverified** share rises, or the text-grounded-AND-verified share falls |

Evidence trust is counted per *unit* — the finding's own quote, plus one per
cross-sheet leg — because a conflict can be text-grounded on one sheet and read
off a raster detail on the other, and a single per-finding state reports one of
those two facts and discards the other. `NOT_ASSESSED` is its own state: a
standard run assesses nothing, and calling that either "grounded" or "reduced
trust" would invent a signal. The concern this axis exists for is the one §11.3
names: an arm whose finding count held up on reduced-trust, unverified legs is
**not** equivalent to one that was text-grounded and verified, and no count,
severity or anchor table can tell them apart.

#### A count drop is a review requirement, not a finding (§11.3)

A large drop in finding count still stops the sweep — it reads as "cheaper and
cleaner" on every other line, which is what makes it the failure most likely to
be approved. But the screen no longer claims it *proves* real defects went
unseen. A drop can be missed defects, removed noise, different dedup behaviour,
or plain run-to-run variance, and this screen cannot tell them apart. What
resolves it is the finding-level comparison below: the unmatched baseline
records name the findings that went missing.

The mirror case is reported as a **note** rather than a concern, because it is
the most ordinary outcome there is and a concern list that fires every run stops
being read: counts within 5% of each other are *not* evidence the same issues
were found, since a flat total can hide one real issue replaced by one false
positive.

A clean screen is **not an approval** — it means the screen found nothing.
`screen_result` has exactly two values, `NO_CONCERNS_DETECTED` and
`CONCERNS_RAISED`; there is deliberately no value that means approved. One run
of one set cannot establish that a change is safe.

#### Comparison validity — when a lower total is not a saving

`diff.json` carries a `validity` block with three states, and only one of them
permits a cost delta to be described as a saving:

| status | when | `savings_claim_allowed` |
|---|---|---|
| `COMPARABLE` | both arms finished, read the same sheets, and priced every record | yes |
| `QUALIFIED` | a `PARTIAL` stage, recorded errors, abandoned/failed/parse-failed calls, unpriced records, or INCOMPLETE markup coverage | no |
| `NOT_COMPARABLE` | an arm's `qc_status` is `FAILED`, the arms successfully read **different sheets**, or either total is unpriced | no |

Three states rather than two on purpose: most real sweeps land in `QUALIFIED`
(one retry, one unpriceable record), and folding that into "not comparable"
would put the ordinary case in the unreadable bucket — at which point the
`NOT_COMPARABLE` cases stop being read too. A cheaper arm that did not finish is
not a cheaper way to do the work; its lower total is the price of a different,
smaller job, and the report says so in those words.

The sheet check compares **identities**, not counts. Each arm records
`ok_sheet_ids` — path-free `SRC-####:p<n>` entries for the sheets it actually
read. A count check passes when the baseline read `{p0, p1, p2}` and the variant
read `{p0, p1, p3}` (one transient failure each, which is ordinary on a two-arm
run), and every finding on `p2` then reads as something the variant missed while
every finding on `p3` reads as something it found — a population difference
attributed to the tested change. The blocking reason names the sheets that
differ. An arm summary written before `ok_sheet_ids` existed falls back to the
count check rather than skipping the check entirely.

#### Finding-level comparison (§11.2)

Every table above is an aggregate, and no aggregate can answer *is this the same
set of findings?* Two arms can report 287 findings each with identical severity,
anchor and verification mixes and share only 200 of them.

Each arm therefore writes `arm_<label>_findings.json`: one compact record per
finding — source id/page, sheet, category, severity, text, quote, every
cross-sheet leg, anchor tier and rectangle, confidence, verification
disposition, WP-03B evidence state, and provenance. `findings_diff.json` matches
the two arms in three deterministic tiers:

| tier | what it means |
|---|---|
| `exact` | equal identity **and** compatible critical signatures, unique on both sides — the only tier that is a match |
| `candidates` | a 1:1 pair for a human to judge: same quote reworded, same legs, heavily-overlapping anchors, or an identity match whose critical signature conflicts |
| unmatched / `ambiguous` | only in one arm, or a many-to-many group left explicitly unresolved |

Two identities are deliberately **not** used. `QC-###` is positional — it is
assigned after anchoring, so an arm that dropped finding #12 renumbers every
finding below it, and matching on it would report 275 unchanged findings as
changed. `Finding.id` alone is not enough either: `compute_finding_id` hashes
sheet id, category, quote-or-text and source id, and **excludes legs**, so two
cross-sheet conflicts quoting the same primary text but pointing at different
second sheets collide on one id. The identity used here adds the leg signature
for exactly that reason, and a test asserts the underlying collision still
exists rather than assuming it.

The "compatible critical signatures" check is `critique.signatures_compatible`,
the same rule the in-run dedup uses — imported, not restated. A changed
quantity, a changed equipment tag, or a flipped absence polarity therefore can
never become an exact match, and geometry never produces one at all: rect
overlap only ever *suggests* a candidate. Nothing is deleted, no fuzzy score is
promoted to an equivalence, and no second model is asked to adjudicate — that
would make a comparison harness cost money and depend on the thing under test.
Ambiguity loses rather than picks: a many-to-many group names every record in it
and stays unresolved, the same discipline `cross_qc.fact_tile_lookup` follows.

An empty record list is never read as a result. `load_arm_records` returns a
status — `PRESENT` / `MISSING` / `UNREADABLE` — beside the records, because
"read fine, no findings", "sidecar never written" and "sidecar corrupt" all hand
back `[]`. With the baseline's sidecar missing, every variant record would
otherwise render as a one-sided difference: a comparison result manufactured out
of a failed file read. The status rides `findings_diff.json` as
`comparison_status` / `record_status` rather than only the rendered text, so a
reader opening the JSON alone cannot miss it, and an INCOMPLETE comparison still
lists the surviving records while refusing to call them differences.

Source correspondence is the positional `SRC-####` id, so both arms agree
without either one's absolute paths reaching the artifact. Evidence crops
referenced by a record are copied out of the arm's workspace into
`arm_<label>_artifacts/` **before** that workspace is deleted, and linked
relative to the output directory — a link into a deleted temp directory is worse
than no link.

Each arm runs in a subprocess because `REVIEW_MODEL_DEFAULT` binds at *import*
in `core.api_config`, so setting `DRAWING_ANALYZER_MODEL` in-process has no
effect.

## Scenarios (§19.7)

| # | Scenario | Mode | Harness scenario id |
|---|---|---|---|
| 1 | Cold-cache standard, real-time | offline + live | `standard-cold` / `live-standard-cold` |
| 2 | Cold-cache standard, batch | live only — measured on a real batch run (the harness does not wait out a Message Batch); record the run.log/usage of an actual `use_batch=True` run | — |
| 3 | Fully warm unchanged run | offline + live | `standard-warm` / `live-standard-warm` |
| 4 | One changed source in a warm set | offline | `one-source-changed` |
| 5 | Full exhaustive QC | offline + live | `exhaustive-cold` / `live-exhaustive` |
| 6 | >40-sheet reconciliation | hermetic acceptance tests (`test_acceptance_cross_shard_conflict_found_above_40_sheets`, `..._84_sheet_reduction...`) prove call topology; live cost is estimated from per-call usage | — |
| 7 | Mixed vector/raster | covered by the §19.1 oracle set (raster sheet included); record separately on the representative real set | — |
| 8 | Partial set with a corrupt file | offline | `corrupt-partial` |
| 9 | Dense representative construction set | live, owner-supplied approved/redacted set | `live-standard-*` over that set |

Record for each: OS/hardware, sheet composition (vector/raster/hybrid, page
sizes), per-scenario wall medians, peak resident memory, API call counts,
tokens by stage family, cache hits, upload counts (batch runs),
annotation/receipt counts, and the priced estimate.

## Required gates

Mechanical (enforced by `--check` and/or the hermetic suite):

- [ ] **Totals reconcile:** run token totals equal the exact sum of the
      append-only usage records (also asserted by the trust gauntlet).
- [ ] **Warm run is genuinely warm:** zero new digest/critique API calls and
      zero full-sheet rasterizations for cached results.
- [ ] **Hash once per source:** content hashing happens once per source per
      run, never once per page.
- [ ] **Batch pricing applies only to batch calls:** usage records carry
      `transport=BATCH` only on the Message-Batches path (hermetic tests
      `test_drawing_batch*`; verify on the live batch run's manifest).
- [ ] **Memory stays streaming:** peak RSS on the 8-sheet offline exhaustive
      scenario stays flat as `--sheets` grows (spot-check 4 vs 12); the
      pipeline must not retain every rendered PNG.
- [ ] **Request/image limits respected:** no live scenario logs an
      over-limit rejection.

Judgement (owner-reviewed against the previous release's recorded medians):

- [ ] **No unexplained local regression** in rendering/cache/export wall time
      beyond the owner-approved tolerance — initial recommendation **15–20%**,
      measured on repeated-run medians on the same hardware.
- [ ] **README/UI cost claims match measured behavior** (per-sheet standard
      cost, exhaustive multiplier, batch discount claims).
- [ ] Live wall times are recorded **descriptively** — network/model service
      variability is not a gate (§19.7).

## Known cost-shape notes (current architecture)

- **A cold exhaustive run does not rasterize every sheet twice.** An earlier
  revision of this note said it did — that the digest and the critique each
  rendered every readable sheet — and budgeting from it overstated cold wall
  time. `render_spool` spools the digest's already-compressed PNG bytes to a
  private temp directory and reconstructs the same `RenderedSheet`
  **byte-for-byte** for the critique: nothing is resized, recompressed or
  filtered, so the two stages are shown the same pixels rather than two
  renders that ought to agree. The batch path reuses the digest's terminal
  uploads for the same reason (Phase 23C), and shares one upload across both
  critique reads.

  A second rasterization is the **fallback**, and it is per page, not per run:
  it happens for a page whose entry the spool does not have (a digest cache hit
  rendered nothing to spool), when the grid does not match, when the manifest is
  unavailable, or when a spool read or write failed. Each of those degrades that
  one page to the historical renderer — `_one_page_fallback` re-renders exactly
  the page that failed and never misassigns another — while every other page
  still reuses. The spool is a run-local performance cache, not a durable
  analysis cache: a failed write simply leaves the key absent. Warm runs skip
  both renders entirely via the level-1 caches (Phase 19B).
- **Two image-token regimes, and only one of them responds to the render
  target.** The vision API treats a request with more than 20 images differently
  from one with 20 or fewer, and every cost intuition here depends on which side
  you are on.

  | | >20 images (a sheet: overview + 36 tiles) | ≤20 images |
  |---|---|---|
  | oversized image | **rejected** outright | silently downscaled |
  | render target | 1560 px vector / 1992 px raster, both a margin under the hard 2000 px cap | 2576 px, the full Opus native long edge |
  | per-image cost vs the cap | **under it** — a square tile at 1560 px costs 3,245 of the 4,784 tokens allowed | **over it** — a 4:3 image at 2576 px works out to 6,636, so it clamps |
  | what moves the token count | page **aspect ratio**, the grid, overlap — and the **render target, quadratically** | nothing you can set: the count is the cap |

  The 2576 branch is deliberate policy, not an oversight: at ≤20 images an
  oversized image is downscaled rather than rejected, so no safety margin is
  needed and an off-by-one there is harmless. It is also why `--estimate` and
  the GUI preview behave differently on a one-sheet job than on a set.

  **The render target is the highest-leverage cost knob, and only in the >20
  regime.** Nothing clamps there, so image tokens go as the square of the
  target. Measured through `cost.estimate_image_tokens_for_bases` on an E-size
  vector sheet at the shipped 6×6 grid, Opus 5:

  | `DRAWING_ANALYZER_TILE_TARGET_PX` | image tokens | vs default | (t/1560)² |
  |---|---|---|---|
  | 1560 (default) | 90,276 | 1.000 | 1.000 |
  | 1400 | 72,723 | 0.806 | 0.805 |
  | 1240 | 57,062 | 0.632 | 0.632 |
  | 1100 | 44,914 | 0.498 | 0.497 |

  Quadratic to three decimals. Whether a lower target still *reads* the drawing
  is a separate, unanswered question — which is what the A/B harness is for.

  **The invariance that does hold is to the page's physical size**, and it is a
  different claim from the one above. Rendering normalizes every page to the
  target long edge, so two pages of the same aspect ratio cost the same
  regardless of how big they are on paper: an E-size 48×36 in sheet, a 24×18 in
  half-size print of it, and a 12×9 in reduction all come to 90,276 tokens.
  That is exactly why `cost.estimate_image_tokens_for_bases` needs only two
  facts per page — aspect ratio, and whether the page has words — and why the
  correction against the conservative allowance is ~1.9× on a vector E-size
  sheet. An earlier revision of this note called the >20 regime
  "scale-invariant" without saying invariant to *what*, and a reader would
  reasonably have taken it to mean the render target — the opposite of the
  measurement above, on the one number most worth tuning.

  `DRAWING_ANALYZER_TILE_TARGET_PX` overrides the **vector** target only. The
  raster target is deliberately not overridable — on a sheet with no text layer
  the pixels are the only channel, so trading resolution there trades data — and
  keeping it fixed also preserves `raster >= vector`, which
  `pipeline.estimate_image_tokens_for_set` relies on to stay a true upper bound.
  The ≤20-image target is untouched too: that regime is not where the payload
  problem lives.

- **Overlap does not buy resolution; it approximately preserves it.** Reducing
  tile overlap shrinks the rendered rectangle each tile covers, so for a fixed
  target the *interior* of a tile keeps roughly the resolution it had. What
  changes is the edges: less of each neighbour is visible, the boundary context
  a symbol or dimension string straddles gets thinner, and the overview — which
  does not tile — is unaffected either way. So an overlap change is a change to
  how much duplicated edge context the model sees, not a free resolution win.
  It is worth measuring against a real set rather than assuming, which is what
  `--baseline-overlap` / `--variant-overlap` exist for. Note that `--estimate`
  cannot see an overlap difference at all (above): the conservative allowance is
  overlap-invariant, so the effect shows up only in a run's actual image tokens.

- **Three vision reads is not three full-price image reads.** A real-time
  exhaustive run sends three vision passes per sheet — one digest, two
  self-consistency critique reads — and that is the most expensive configuration
  the app offers. But the two critique reads are byte-identical in their image
  prefix, so when `runs >= 2` the second read bills those images at the
  cache-read multiplier (~0.1×) rather than at full rate. Identical tokens in,
  so the findings are unaffected. The batch critique path stays uncached (parallel
  submission means a breakpoint buys the write premium with nothing yet written
  to read), and takes the ~50% batch discount instead.

  Do not infer the bill from the read count in either direction. The cache
  write/read tokens ride the `RunUsage` ledger as their own priced fields, and
  `usage_axes` in an A/B arm summary separates them from ordinary input — what a
  run actually cost is what its `UsageRecord`s say it cost, and an estimate that
  multiplies a per-read figure by three is quoting a configuration nobody ran.

- **Every model stage caches, not just digest/critique.** Verification caches
  through `stage_cache` (`verify._VERIFY_CACHE_STAGE` / `_VERIFY_CROSS_CACHE_STAGE`),
  as do cross-QC, synthesis, focus and prose harvest; identity, review plan,
  investigation and citation each own a `DigestCache` namespace (the citation
  verdict cache carries a TTL, `DRAWING_ANALYZER_CITATION_TTL_DAYS`, default 30
  days). So a warm exhaustive re-run should show near-zero API calls across the
  board — not just on the two vision stages. An earlier revision of this note
  said verification was stateless and re-billed every run; that stopped being
  true when the stage cache landed, and a warm run that *does* re-bill
  verification is now a cache-correctness bug worth chasing, not expected
  behavior.
- **Cache-write cost depends on the requested TTL.** A `ttl: "1h"` breakpoint
  costs 2x base input; the default 5-minute entry costs 1.25x. The ledger
  records which was requested per record (`UsageRecord.cache_write_ttl`), so a
  run manifest's cache-write spend can be reconciled against the breakpoints the
  stages actually asked for.

## Record

| Field | Value |
|---|---|
| Date / tester | |
| Commit (full SHA) / version | |
| OS / CPU / RAM | |
| Python / PyMuPDF / SDK versions | |
| Set composition (sheets, vector/raster, sizes) | |
| `benchmark_report.json` attached | ☐ |
| Live batch run manifest attached (scenario 2) | ☐ |
| Gates above all checked | ☐ |
| Owner sign-off on regressions/tolerances | |

### Benchmark medians — 8 sheets, 5 repeats, offline (WP-08)

Commit `c086f1c`, Linux 6.18.44 / x86_64, Python 3.11.15, PyMuPDF 1.28.2,
SDK 1.4.0. `Mechanical gates: PASS`.

| scenario | median wall (s) | mechanical assertion | notes |
|---|---:|---|---|
| standard-cold | 3.161 | — | 8 digest calls, 8 renders, 8 hashes |
| standard-warm | **0.030** | 0 API calls, 0 renders | 8 cache hits |
| one-source-changed | 0.417 | exactly 1 digest call | 1 render |
| exhaustive-cold | 3.191 | — | qc_status PARTIAL, coverage COMPLETE |
| corrupt-partial | 3.190 | — | ok_sheets 8, errors 1 (the corrupt input) |

Peak RSS 189.0 MB. The warm run is ~105× faster than cold and touches neither
the API nor the rasterizer — the property the gate exists to protect.

**These are fake-client timings.** They measure host-side work only: the offline
client answers by system-prompt identity and never reads the model id, so
nothing here says anything about model latency, findings quality, or cost.

They are also the **first** numbers this gate has produced that describe the
application at all. Before WP-08 every scenario failed identically because the
benchmark's fake client had not tracked two transport changes — unconditional
streaming through `digest.stream_message`, and the Opus-5 refusal fallback's
re-route through `client.beta.messages`. Every sheet raised
`'OfflineClient' object has no attribute 'beta'`, I-3 caught it per sheet, and
the run finished with zero digests while the gate reported what looked like app
regressions ("cached run still rasterized", "expected exactly 1 digest call, got
0"). `tests/test_benchmark_harness.py` now fails the moment the fake stops being
reached, asserting that work was *done* rather than that particular attributes
exist — production is free to rename those, which was the whole problem.

### Confirmation-time cost scan — the measurement (WP-05 §10.3)

```bash
# Your own sets — what the plan actually asks for. Zero API calls.
python scripts/measure_scan_time.py --pdf setA.pdf --pdf setB.pdf

# Synthetic sweep when no real set is at hand
python scripts/measure_scan_time.py --synthetic
```

§10.3 is a measurement step before a design step, because `render.py`'s
"0.32 s / 8 sheets / 6,636 words" is one reading and not a bound. Measured here
(synthetic uniform E-size pages, medians of 3):

| set | fresh cost scan | wait behind a running preflight | derive from the preflight's geometry |
|---|---:|---:|---:|
| 8 sheets × 500 w | 62 ms | 194 ms | 0.0 ms |
| 39 sheets × 500 w | 330 ms | 1,009 ms | 0.1 ms |
| 120 sheets × 500 w | 959 ms | 2,912 ms | 0.4 ms |
| 8 sheets × 4,000 w | 477 ms | 1,450 ms | 0.0 ms |
| 39 sheets × 4,000 w | 2,399 ms | 7,494 ms | 0.1 ms |
| **120 sheets × 4,000 w** | **6,896 ms** | **22,457 ms** | **0.4 ms** |

Three things follow.

**The scan tracks word count, not sheet count** — ~15 ms per 1,000 words across
every configuration, so 8 ms/page on a sparse set and 60 ms/page on a dense one.
That is why a per-sheet figure was never a bound: a hyperscale fire-protection
set is mostly dense schedule sheets. As a cross-check, the same instrument
reproduces the number already in `render.py`: 48.4 ms/1k words × 6.636k words =
321 ms against the recorded 320 ms.

**The preflight is the larger term, by 3×**, because `iter_sheet_prescan` also
computes each page's render identity — a content hash over its dependency graph
that the level-1 cache needs and a cost estimate does not. A scan that wants
PyMuPDF waits behind that lock.

**So there is no separate scan.** §10.3 Step 2's default design — run it once at
the Analyze click — would freeze the UI for ~7 seconds on a large dense set, at
the exact moment money is committed. Item 3's "prefer **reusing** its results" is
the right branch and is nearly free: `preflight_sheet_ids` already builds a full
`SheetGeometry` per page and keeps only the sheet id, so emitting a
`SheetCostBasis` from the object it discards costs 0.4 ms for 120 pages — 0.01%
of a fresh scan, inside a lock already held, with no second PDF owner. When no
usable scan exists (the user clicked Analyze first, or it failed), the dialog
prices conservatively and says so.

The GUI cases that need a real window are in `docs/WINDOWS_MANUAL_ACCEPTANCE.md`.
