# Performance, memory & cost qualification (Phase 27, §19.7)

This document defines the measurement scenarios, the required gates, and the
recording template for a release candidate. Numbers are judged on **medians of
repeated runs**, never single runs. The harness is
`scripts/benchmark_drawing_analyzer.py`; it writes
`benchmark_report.{json,md}` for attachment to the release record.

## Pre-run estimate assumptions

Drawing preflight runs when files are loaded, including installations with no
review profiles. A single background scan supplies page geometry and optional
profile suggestions. Generation and file fingerprints still gate measured
bases; incomplete or stale scans use the existing image allowance.

No real `run_manifest.json` usage records were supplied for this calibration.
The output range is therefore a planning allowance, **including billed adaptive
thinking**, rather than a measured average:

| Quantity | Lower planning end | Upper planning end |
| --- | --- | --- |
| Digest or critique output per read | 4,000 tokens | Runtime read envelope, currently 64,000 tokens, clamped to the stage model |
| Exhaustive findings per sheet | 8 | 20 |
| Investigation per uncertain finding | Up to 3 evidence requests + closing call; 1,500 output tokens/call | Configured request limit, currently 6 + closing call; full 16,000-token output envelope/call |

The finding assumption allows growth beyond the recorded standard run's 287
findings on 39 sheets (7.36 per sheet) from critique, cross-QC and auditors. It
is not an observed exhaustive distribution. Investigation respects the runtime
finding cap and round override; its upper input estimate includes accumulated
evidence and complete assistant replies, including thinking blocks in the tool
loop's history. The model's advisory task budget is not a
host-enforced spending limit.

Cross-QC includes map and reconciliation calls above the runtime's 40-sheet
threshold. Without known discipline groups, its band spans the fewest possible
shards through one shard per sheet, with reconciliation fact/pair limits from
the runtime. Its wide upper end describes an extreme grouping, not typical
spend. Digest thinking is never counted as input to later text passes. Batch
discounts apply to digest/critique output; prefix-cache discounts apply only to
critique input. The current Opus 5.5 price and cache-read multiplier come from
the shared pricing registry. Measured image inputs now price the renderer's
physical-size grid policy separately for each page, including mixed-size sets.

Both GUI headlines and dialogs show the band. Standard `total_cost` and
`output_tokens` retain their compatibility fields and now represent the upper
planning end; `low_cost`, `high_cost` and `output_tokens_low` expose the band.
These ranges are not spending caps: retries, input text and actual finding
volume can move a run outside them. To replace the assumptions with measured
values, use billable per-read usage output (which includes thinking), retain
paid retries, exclude local cache hits, separate stage/model/transport, and
divide findings by the run's successfully read sheet count.

## How to run

```bash
# Hermetic (free): the analyzer itself — render, cache, ledger, markup, export
python scripts/benchmark_drawing_analyzer.py --check --sheets 8 --repeats 5

# Live (billable): real tokens/costs on a representative approved set
ANTHROPIC_API_KEY=... python scripts/benchmark_drawing_analyzer.py \
    --live --pdf setA/M-101.pdf --pdf setA/E-201.pdf [--exhaustive]
```

`--check` turns the mechanical gates below into hard failures (nonzero exit).

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
  is a separate question that no recorded measurement has answered.

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
  write/read tokens ride the `RunUsage` ledger as their own priced fields,
  separate from ordinary input — what a
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
