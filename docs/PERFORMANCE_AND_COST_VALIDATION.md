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

The hermetic suite cannot answer whether a cheaper configuration still finds the
same defects — the §19.1 gauntlet routes canned responses by system-prompt
identity and never reads the model id, so a model swap changes nothing it
returns. This harness runs the same set twice, cold on both arms, with one
variable changed, and reports cost against **three signals that need no ground
truth**:

| Signal | Regression looks like |
|---|---|
| Anchor tier mix (EXACT/FUZZY/TILE/**UNANCHORED**) | UNANCHORED share rises — the documented hallucination signal |
| Verification verdict mix (VERIFIED/REJECTED/UNCERTAIN) | REJECTED share rises — more false positives |
| Self-consistency (REPRODUCED/SINGLETON) | REPRODUCED share falls — the two reads agree less |

It also flags the quiet failure: a large drop in **finding count** at a flat
VERIFIED share, which reads as "cheaper and cleaner" on every other line while
actually meaning real defects went unseen.

A clean screen is **not an approval** — it means the screen found nothing. One
run of one set cannot establish that a change is safe. Each arm runs in a
subprocess because `REVIEW_MODEL_DEFAULT` binds at *import* in
`core.api_config`, so setting `DRAWING_ANALYZER_MODEL` in-process has no effect.

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

- A cold real-time exhaustive run renders each readable sheet **twice** (once
  for the digest, once for the critique reads). The batch path shares one
  upload for both critique reads (Phase 23C); warm runs skip both renders via
  the level-1 caches (Phase 19B). Budget accordingly when comparing cold
  medians across transports.
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
