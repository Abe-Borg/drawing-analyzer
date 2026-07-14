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
- Verification is deliberately stateless: it re-runs (and re-bills) on every
  exhaustive run, including warm ones. The digest/critique caches are the
  warm-run savings; verify/citation/cross/synthesis are not cached.

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
