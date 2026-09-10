# Release evidence — review implementation packages WP-00 … WP-08

Release evidence for the review implementation packages WP-00 … WP-08, all of
which are complete and merged. It records what
changed, what was measured, what was verified, and — at least as importantly —
what was **not**, so nobody has to infer a claim from an absence.

The plan these packages came from has been retired now that they are complete;
it remains in git history at `168f4ec`, and the work that had *not* been done —
the measurement packages and the standing prohibitions — moved to
`docs/MEASUREMENT_PACKAGES.md`. Section numbers below refer to **this**
document.

Two rules govern every number below. Nothing measured with a hermetic fake
client is presented as a cost or quality improvement; those fakes answer by
system-prompt identity and never read the model id, so a model swap changes
nothing they return. And a check that was skipped is recorded as skipped, never
folded into a pass.

---

## 1. Environment for this record

| field | value |
|---|---|
| Commit | `c086f1c` (base for WP-08) |
| App / Python / PyMuPDF / SDK | 1.3.0rc1 / 3.11.15 / 1.28.2 / 1.4.0 |
| OS / arch | Linux 6.18.44 / x86_64 |
| CI matrix (`.github/workflows/ci.yml`) | Linux 3.11, Linux 3.12, Windows 3.11 |

The reviewed CI matrix is those three jobs, not a broader Cartesian product.

### A container defect that was masking the local verdict

Every prior package in this sequence reported three `tests/test_spec_documents.py`
failures as "a known container defect — a `pyo3_runtime.Panic` from `cryptography`
inside `pypdf`, green in CI." That was accurate but incurious. The cause is that
this container ships `cryptography` 41.0.7 with **no `cffi`**, so its Rust
bindings cannot load. `pip install cffi` fixes it; all 40 tests then pass.

It never affected CI, the repository, or any released artifact. It did mean the
local suite could not be run clean, and two release gates could not run at all.
Both are now installed and exercised, so the verdicts below are complete rather
than partial.

---

## 2. Test evidence

### 2.1 Focused groups

Run on the WP-08 base. The groups were specified as PowerShell commands for a
Windows venv; the Linux equivalents were run here and the `test_ab_findings_diff.py`,
`test_cost_geometry.py` and `test_cost_confirmation_scan.py` suites were added to
the groups they belong to, since they postdate the original lists.

| group | suites | result |
|---|---|---|
| Evidence retention, grounding, location, cache, render reuse | models, render, anchor, verify, cross_qc, stage_cache, cache_identity, render_spool | **126 passed** |
| Estimation, geometry, configuration parity, experiment records | cost, ab_sweep, ab_findings_diff, tiling, tokens, cost_optimization, model_capabilities, cost_geometry, cost_confirmation_scan | **382 passed** |
| Integration and unchanged request/receipt contracts | digest, critique, batch, batch_critique, qc_pipeline, acceptance, usage, import_isolation | **285 passed** |

### 2.2 Full hermetic suite

```
python -m pytest -q -p no:cacheprovider -m "not network and not browser"
1942 passed, 1 skipped, 92 deselected in 117.96s
```

The one skip is `test_input_inventory.py:155` — the container runs as root, so
`chmod 000` is still readable and the unreadable-source case cannot be staged.
That is an environment limitation, not a passing test.

### 2.3 Release gates (`scripts/run_acceptance.py`)

| gate | result |
|---|---|
| byte-compile | PASS |
| import isolation (I-5) | PASS |
| hermetic suite + trust gauntlet | PASS |
| secret scan | PASS (164 tracked files) |
| browser security | PASS (86 tests, headless Chromium) |
| build + clean-install smoke | PASS (`drawing_analyzer-1.3.0rc1` wheel + sdist, installed into a clean venv, profile mechanism verified) |

All six pass with nothing skipped. The browser and build gates had never
executed in this container before — they reported SKIP for missing tooling, which
is not a pass and was not recorded as one.

The runner deliberately never runs the live canary
(`pytest -m network tests/test_live_api_canary.py`); that and the manual records
below remain open before tagging.

---

## 3. The benchmark gate was measuring nothing (found in WP-08)

`scripts/benchmark_drawing_analyzer.py --check` is a release gate asserting that
a warm run makes zero digest calls and rasterizes nothing, and that editing one
source re-digests exactly one sheet. On the WP-08 base it failed — and the
failures read like app regressions:

```
- standard-warm: cached run still rasterized            (x5)
- one-source-changed: expected exactly 1 digest call, got 0   (x5)
```

They were not. Every scenario reported `digest_api_calls=0`, `tok=0/0`,
`cost≈$0.0000`, and `corrupt-partial` reported `ok_sheets=0; errors=9` — every
sheet failing, including the ones that were fine. Reproducing a single run gave
the cause immediately:

```
M-100.pdf (page 1/1): 'OfflineClient' object has no attribute 'beta'
```

Two production changes landed after the benchmark's fake client was written, and
it tracked neither:

- `digest.stream_message` issues **every** digest / critique / review-plan /
  synthesis / focus request over `messages.stream` — unconditionally, not only
  above the ~21k cap that makes streaming mandatory.
- `core.api_config.call_with_refusal_fallback` re-routes every Opus-5 real-time
  call through `client.beta.messages`.

I-3 did exactly its job: it caught the `AttributeError` per sheet, appended to
`ctx.errors`, and let the run finish. That is right for a real run and wrong for
a benchmark, because the run then "succeeded" with no work done and the gate's
own counters could not tell the difference.

**Fix.** `OfflineClient` now mixes in `BetaClientMixin` and answers
`messages.stream` via `FinalMessageStream`, both imported from
`tests/fixtures/fake_anthropic.py` rather than reimplemented — a benchmark fake
that restates the transport is a fake that drifts from it again.

**Guard.** `tests/test_benchmark_harness.py` (4 tests) runs the real pipeline
against the real fake and asserts *work was done*, not that particular
attributes exist — production is free to rename those, which is the whole
problem. One test reproduces the swallowed-error failure mode deliberately;
another covers `messages.stream` directly, because Sonnet-routed stages bypass
the beta namespace and an Opus-only scenario cannot see that half. Both
mutations (drop `BetaClientMixin`, drop `stream`) were verified to fail the
guard.

### 3.1 Benchmark record — 8 sheets, 5 repeats, offline

Medians, for `docs/PERFORMANCE_AND_COST_VALIDATION.md`'s Record table. These are
the first numbers this gate has produced that describe the application.

| scenario | median wall (s) | mechanical assertion | notes |
|---|---:|---|---|
| standard-cold | 3.161 | — | 8 digest calls, 8 renders, 8 hashes |
| standard-warm | **0.030** | 0 API calls, 0 renders | 8 cache hits |
| one-source-changed | 0.417 | exactly 1 digest call | 1 render |
| exhaustive-cold | 3.191 | — | qc_status PARTIAL, coverage COMPLETE |
| corrupt-partial | 3.190 | — | ok_sheets 8, errors 1 (the corrupt input) |

Peak RSS 189.0 MB. `Mechanical gates: PASS`.

The warm run is ~105× faster than cold and touches neither the API nor the
rasterizer — the property the gate exists to protect, verified rather than
assumed. **These are fake-client timings**: they measure host-side work only and
say nothing about model latency or cost.

---

## 4. Cache invalidation scope and mechanism

Recorded precisely because the review's own summary of it was imprecise, and
because a maintainer reading a contract counter will otherwise mis-date it.

| change | cross-QC cache | mechanism |
|---|---|---|
| Grounding quotes past the prompt cap (WP-03A) | **preserved byte-identically** | `evidence_sha256` enters the key **only for a truncated sheet**; every untruncated key is unchanged. No contract bump. |
| Admitting visual evidence at reduced trust (WP-03B) | **invalidated** | Exactly one mechanism: the edited map prompt, which rides every cross-QC key. No contract bump beside it. |

`_CROSS_QC_CACHE_CONTRACT` is at 2 for an **unrelated earlier reason** — entries
written before the findings cap became loss-aware were stored as `complete` after
a silent truncation. It is not the record of either evidence change.

Digest and critique caches were not touched by the evidence work; no
indiscriminate schema bump was used. Dense cross-QC cases keep their existing
budget degradation and cache ineligibility.

### The corrective-fix packages (post-WP)

Recorded here per the standing one-mechanism rule, so that a maintainer reading
`digest_cache._SCHEMA_VERSION` can date each step of it.

| package | mechanism | what is discarded |
|---|---|---|
| P1 — status honesty | **none** | nothing. No key input, stored shape or model-visible string moved. |
| P2 — truncation | `digest_cache._SCHEMA_VERSION` **8 → 9** | every `DigestCache` entry (digest, critique, identity, review plan, citation, investigation), once. The entry stores the *post-parse* product, so entries written under the old fence scanner cannot be re-derived in place — the v6 parser rebuild is the precedent. The `SHARED_USER_FRAMING_STRINGS` prompt-hash change rides that same bump: two changes, one cold run, not two mechanisms for one change. |
| P3 — ledger truth | **none** | nothing. The ledger merge runs *after* the critique stage and its output is never cached (`critique_cache_key` stores the critique's own merged result, written before a `Ledger` exists), so a warm run replays the same findings through the corrected merge. Item 24 carries provenance forward from the finding's existing verdict rather than from storage, exactly as `investigate.py` does, so the verify stage's three-key payload is unchanged. Confirmed by `benchmark_drawing_analyzer.py --check`: `standard-warm` still makes 0 digest calls and 0 renders, `one-source-changed` still exactly 1. |
| P4 — auditor false positives | `digest_cache._SCHEMA_VERSION` **9 → 10** | every `DigestCache` entry, once. The critique entry stores the **post-merge** findings, and `critical_signature`'s measurement rule changed — a pair the new rule separates is already collapsed in a stored entry and unrecoverable, a pair it would now join is stored as two. Cannot be re-derived in place; same class as the v6 and v9 parser rebuilds. Nothing else in P4 touches a key: the auditors run per-run over the text layers and cache nothing. |
| P4 — A/B harness records | `ab_findings_diff.RECORD_CONTRACT_VERSION` **1 → 2** | finished arm sidecars only, and by refusal rather than discard — `load_arm_records` returns `RECORDS_STALE_CONTRACT` instead of comparing. A **separate mechanism for a separate change**, not a second mechanism for the schema bump: the counter covers the *cached merge product*, this covers *stored harness records* whose `critical_signature` was computed at arm-run time under the old rule. Re-run affected arms rather than comparing across versions. |

---

## 5. Measured results carried forward

| measurement | result | where |
|---|---|---|
| Confirmation-time cost scan vs. reuse | fresh scan of 120 dense sheets **6,896 ms**, up to **22,457 ms** waiting behind the preflight lock, vs **0.4 ms** deriving from geometry the preflight already built | WP-05 — the measurement overturned the design that had been specified for it |
| Scan cost driver | tracks **word count** (~15 ms / 1k words), not sheet count | same |
| Image tokens vs render target (>20-image regime) | quadratic: 1400 px = 0.806×, 1240 px = 0.632×, 1100 px = 0.498× of the 1560 px default, on an E-size vector sheet at 6×6 | WP-07, re-measured after review |
| Image tokens vs physical page size | invariant: 48×36 in, 24×18 in and 12×9 in all cost 90,276 tokens | same |
| Conservative allowance vs measured geometry | ~1.9× overstatement on a vector E-size sheet | WP-05 |
| Estimator vs renderer pixel sizing | pixel-exact on 18/20 shape/grid combinations; the whole-pixel rounding rule that had been specified differed by +0.15% | WP-05a |
| Attached spec block, real-time vs batch | ~11 copies vs ~50 across 100 sheets (1.25× write + 0.1× per sheet, vs 0.5× per sheet) | WP-07, re-measured after review |

---

## 6. What was NOT done

Recorded as open, not as passed.

| item | status | what it needs |
|---|---|---|
| Grounding **discard rate** (instrumented run) | **not measured** | One instrumented run over a set with >40 readable sheets including scanned/vendor as-built pages. Requires a named dataset and an approved budget; nothing has billed. The zero-call coverage scan (`scripts/measure_evidence_coverage.py`) is not a substitute and is not reported as one. |
| Dense-fixture memory / scaling | **not measured** | The 8-sheet benchmark checks mechanical regressions only. WP-03's dense-text measurement needs its own fixture, page count, repeated timings and peak retained memory recorded separately. |
| Windows manual GUI acceptance | **not run** | `docs/WINDOWS_ACCEPTANCE.md` / `docs/WINDOWS_MANUAL_ACCEPTANCE.md`, on real Windows. This session is Linux. |
| Live API canary | **not run** | Billable, opt-in, deliberately excluded from the gates. |
| `scripts/measure_scan_time.py` on real sets | **not run** | Zero cost, but wants real hyperscale sets rather than synthetic pages. |
| R-01 … R-06 measurement packages | **not started** | Subsequent research decisions, not release blockers — see `docs/MEASUREMENT_PACKAGES.md`. |

`PRICING_EFFECTIVE_DATE` is unchanged. It moves only after the rate table is
verified against official pricing — not because documentation is newer.

---

## 7. Independent review checklist

Worked item by item. "Verified" means a named test or a reading of the current
code, not an inference from the plan.

| # | item | status |
|---|---|---|
| 1 | Acceptance runner cannot reach the network with a real key present, and a regression guards it | **Verified** — `run_acceptance.py` routes every gate through `_pytest_cmd()`, which ANDs `not network`; `tests/test_run_acceptance.py` fails if a bare `"pytest"` argv literal reappears |
| 2 | Coverage/truncation/locatability measured before the fix, each number labelled by tier; a surviving-finding distribution is not reported as a discard rate | **Partial** — the zero-call tier is implemented and labelled (`scripts/measure_evidence_coverage.py`, which states in its own output what it cannot see). The instrumented discard-rate tier is **not measured** (§6) |
| 3 | The original tail-evidence failure was demonstrated before the fix | **Verified** — `tests/test_evidence_tail.py` |
| 4 | Textless, hybrid and missing-quote failures demonstrated; the hybrid case does not pass merely because `is_raster` is true | **Verified** — `tests/test_evidence_visual.py`; the hybrid case is asked of the reported **tile** (`_tile_has_words`), and a sheet-level answer is explicitly insufficient |
| 5 | Real evidence survives; fabricated or wrong-sheet evidence still fails grounding | **Verified** — `NOT_MATCHED_IN_TEXT` remains a discard |
| 6 | A recovered finding is locatable and reaches `verify._has_anchored_legs` and `investigate._candidates` | **Verified** — TILE anchoring via `anchor._anchor_one`, gated to `TEXT_EVIDENCE_UNAVAILABLE` |
| 7 | Cross-shard findings are locatable, tile derived from a host-side join rather than supplied by the model | **Verified** — `fact_tile_lookup` joins on `(handle, normalized quote)`; the reconcile contract carries no tile |
| 8 | The `_anchor_one` tile fallback applies only to reduced-trust legs; unmatched quotes on text-bearing evidence still return `quote_not_found`; digest/critique/whole-set anchoring unchanged | **Verified** |
| 9 | An unquoted leg is never more trusted than an unmatched one | **Verified** — an absent quote is `TEXT_EVIDENCE_UNAVAILABLE`, never implicitly grounded |
| 10 | Reduced-trust findings are visibly distinguished everywhere they appear | **Verified** — markup label, report note, per-leg state; reason chosen by `models.reduced_trust_reason` so `[NO TEXT TO CHECK]` and `[NO QUOTE TO CHECK]` are never conflated |
| 11 | All cold, prescan and spool paths carry the new field | **Verified** |
| 12 | Prompt bytes and production quality defaults unchanged except the documented sharded map-prompt tile request | **Verified** |
| 13 | WP-03A preserved cross-QC keys byte-identically, no contract bump | **Verified** — §4 |
| 14 | WP-03B invalidated by exactly one mechanism, named | **Verified** — §4, the map-prompt edit |
| 15 | Unaffected digest/critique caches remain valid; no indiscriminate schema bump; dense cases keep budget degradation | **Verified** |
| 16 | Estimates and execution resolve identical stage models — including fallback-dependent stages under a global-model variant — transport and geometry | **Verified** — both children cross the same process boundary through `resolve_arm_configuration`; `tests/test_ab_sweep.py` pins it |
| 17 | Image counts are model-tier aware; pricing distinguishes input, output, cache and batch | **Verified** — per-model caps; `usage_axes` separates transport, cache read/write and outcome |
| 18 | Estimates never present partial known prices as a complete total, or a planning bound as a guarantee | **Verified** — `RunUsage.is_billable_but_unpriced` counts cache tokens (the defect that let a $5.00 total hide 180k cache tokens); `_BASIS_MEASURED` / `_BASIS_CONSERVATIVE` label the basis and neither claims a maximum |
| 19 | The confirmation-time scan's duration and lock-wait were measured, and any escalation to a background worker is justified by that measurement | **Verified** — §5; the measurement overturned the design that had been specified, and no background worker was built |
| 20 | GUI preview scanning cannot freeze interaction or race analysis PDF access, and coordinates with the profile preflight | **Verified by construction, not on Windows** — one preflight walk, generation guard, `sources_fingerprint` re-checked at consumption. `gui.py` cannot be imported here or in CI (no tkinter), so this is code reading plus the non-GUI units; the Windows manual record remains open (§6) |
| 21 | A/B records expose unmatched/ambiguous findings, incomplete arms, and evidence-trust composition | **Verified** — WP-06b: three matching tiers, `comparison_status`, `comparison_validity`, `evidence_trust` |
| 22 | Finding counts and agreement rates are not asserted to prove recall | **Verified** — a count drop is a review requirement; `screen_result` has no value meaning approved |
| 23 | Full text does not leak into logs or unbounded model/report context | **Verified** — journal sanitizes at emit; `full_sheet_text` is never sent; discard counters hold counts, never quote text; A/B records carry no absolute paths |
| 24 | Existing deterministic ordering, provenance, ledger lifecycle and saved-PDF receipt checks pass | **Verified** — full suite green |
| 25 | Documentation reflects the implementation and separates measured from hypothetical savings | **Verified after correction** — WP-07 corrected three stale code comments and seven documentation claims; review then caught two fresh errors in that pass, both fixed and recorded as errors rather than restated |

Two items (2 and 20) are partial and one class of work (§6) is untouched. They
are listed here rather than in a footnote because a checklist whose every box is
ticked is the one nobody reads.

---

## 8. Revertability

Each package was a separate commit and a separate PR, so a defective estimate
enhancement reverts without touching the evidence fixes. Reverting WP-03B must
preserve a prompt identity that cannot load results cached under the old
acceptance meaning; do **not** downgrade `_CROSS_QC_CACHE_CONTRACT` to an older
value, which would readmit exactly those entries.
