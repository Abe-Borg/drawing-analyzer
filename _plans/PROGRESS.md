# Remediation progress tracker

**Next up:** Wave 1 in order: `WP-04.1`. WP-01.2 is done: it decided D-1 and started D-4, which WP-10.4 completes. Its dependants are now available in their waves: WP-01.3 and WP-01.4 (Wave 1), WP-01.5 and WP-06.3 (Wave 2), WP-12.6 (Wave 3). First check the open PRs ([`README.md`](README.md), step 1). Before the next stable tag, the owner should look at O-5.
**Last updated:** 2026-09-23 by the WP-01.2 session.

This file is authoritative for **status and order**. Requirements live in
[`drawing-analyzer-remediation-plan.md`](drawing-analyzer-remediation-plan.md).
Every session follows the protocol in [`README.md`](README.md) and updates this
file **in its own PR**.

## Status legend

| Status | Meaning |
|---|---|
| `todo` | Not started, or its PR was closed unmerged. |
| `done` | Merged. Its regression tests failed before the fix and pass after it. PR linked. |
| `partial` | Merged, but part of the scope remains. The notes say exactly what. |
| `n/a` | Not needed: already satisfied or disproved. The notes cite the evidence. |
| `blocked: <gate>` | Waiting on an owner action (`O-n`, below) or another external gate. |

A slice whose PR is still open reads `todo` here until that PR merges. The
open PRs are the only record of work in flight, so always check them first.

**Size** is a rough guide: **S** is under ~400 changed lines, **M** is ~400–1,000,
**L** is ~1,000–1,500. A slice that grows past **L** should be split: add the new
row here.

## Baseline (2026-09-22)

- **Code.** `8521366`, identical to 1.7.0 (`da8f810`); the commits after it add
  only `_plans/`. Anthropic SDK 1.7.0, PyMuPDF 1.28.2, Python 3.11.15.
- **Full suite.** After `pip install -e ".[dev,browsertest]"` and
  `pip install cffi`, `python -m pytest -q -m "not network"` gives **2,450 passed,
  11 skipped, 0 failed** in 235 s. The 11 skips are the 10 live canaries (no key)
  and 1 root-permission test.
  - Without `cffi`, 3 tests in `tests/test_spec_documents.py` fail with
    `pyo3_runtime.PanicException`. This is an environment defect; see the README.
- **Browser suite.** `-m "browser and not network"`: 98 collected, 98 executed and
  passed. `scripts/check_browser_suite.py` passes.
- **Re-verification.** Every finding the plan names was re-checked against this
  code (plan §1.3; evidence in [`verification-2026-09-22/`](verification-2026-09-22/)).
  - None has been fixed.
  - Five descriptions were corrected: N9, A6, R3, B7 and H2.
  - Eighteen new defects were found and added as N10–N27.

## Work packages

A package is `done` only when every slice is `done` or `n/a` **and** its
**Acceptance** paragraph in the plan holds.

| WP | Title | Priority | Slices | Status |
|---|---|---|---|---|
| WP-01 | Response terminal states and truthful stage completeness | P0 | 01.1–01.7 | todo |
| WP-02 | Faithful SDK, streaming, batch and network test boundaries | P0 (enabling) | 02.1–02.5 | todo |
| WP-03 | Durable finding identity and lossless, symmetric merging | P0 | 03.1–03.6 | todo |
| WP-04 | Engineering quantity and tag comparison | P0 | 04.1–04.2 | todo |
| WP-05 | Robust anchoring and consistent quote evidence | P0/P1 | 05.1–05.3 | todo |
| WP-06 | Source-safe cross-QC and claim-preserving deduplication | P0/P1 | 06.1–06.4 | todo |
| WP-07 | Arithmetic operand trust and strict numeric parsing | P0 | 07.1–07.3 | todo |
| WP-08 | Reference, naming, sheet-ID and drawing-index auditors | P1 | 08.1–08.5 | todo |
| WP-09 | Prose harvesting without empty findings or unnecessary duplication | P1 (N10 is P0) | 09.1–09.2 | todo |
| WP-10 | Complete cache keys, faithful metadata and targeted migration | P0/P1 | 10.1–10.4 | todo |
| WP-11 | Inventory-driven source and page fault isolation | P0/P1 | 11.1–11.3 | todo |
| WP-12 | Citation parsing, full-text editions and honest adoption evidence | P1 | 12.1–12.6 | todo |
| WP-13 | Investigation budgets, replay and evidence finalization | P1 | 13.1–13.4 | todo |
| WP-14 | Attempt-level provenance, usage and pricing | P1 | 14.1–14.6 | todo |
| WP-15 | Calibrated estimates and preflight efficiency | P1/P2 | 15.1–15.5 | todo |
| WP-16 | Run-scoped clients and credential lifecycle | P1 | 16.1–16.3 | todo |
| WP-17 | Cancellation, durable job records and safe resumption | P1 | 17.1–17.4 | todo |
| WP-18 | Remote upload and local work-directory ownership | P1/P2 | 18.1–18.5 | todo |
| WP-19 | Valid report-chat history after every termination path | P1 | 19.1–19.2 | todo |
| WP-20 | Bounded assistant context, accurate chat costs and calculator input | P1/P2 | 20.1–20.5 | todo |
| WP-21 | Report vocabulary, grouping, PDF plans and destinations | P1/P2 | 21.1–21.4 | todo |
| WP-22 | Diagnostics, configuration fidelity and defensive deserialization | P1/P2 | 22.1–22.5 | todo |
| WP-23 | Reproducible packaging and enforceable release acceptance | P1 | 23.1–23.6 | todo |
| WP-24 | Update authenticity, download constraints and launch verification | P1/P2 | 24.1–24.3 | todo |
| WP-25 | Measured optimizations and viewer compatibility experiments | P2, decision-gated | 25.1–25.12 | blocked: O-4 |
| INT | Integrated acceptance and release report (plan §6, §10) | — | INT.1–INT.3 | todo |

## Slice queue

Take the **first `todo` row whose dependencies are all `done`**. Waves group the
work by priority and dependency; they are not a reason to skip an unblocked
earlier row. The user may also name a slice.

Each slice's work package in the plan ends with *Verification notes*: corrections,
unnamed sites, and the tests an implementer must re-baseline. Read them before
starting.

### Wave 0 — foundations and incident response

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-02.1 | Hermetic network and credential guard for every non-`network` test (loopback and `AF_UNIX` allowed; proxy and credential variables removed); `network` becomes an explicit opt-in; `-m "not network"` in CI (U26) | S | — | done | [PR #153](https://github.com/Abe-Borg/drawing-analyzer/pull/153), 2026-09-23. `tests/fixtures/hermetic_guard.py` (whole-run scope; swallowed attempts fail at teardown); `tests/test_hermetic_guard.py` |
| WP-23.1 | A stable `publish` fails unless `docs/releases/ACCEPTANCE-<ver>.md` reads SHIP or lists unexpired waivers; `environment:` on `publish`; RC tags unaffected (N8) | S | — | done | [PR #154](https://github.com/Abe-Borg/drawing-analyzer/pull/154), 2026-09-23. `scripts/check_release_acceptance.py` in a new read-only `acceptance` job that `publish` needs. The rule is SHIP **and** complete, unexpired waivers; waivers never lift a HOLD (plan WP-23 notes). `publish` takes the channel from the job and re-checks waiver expiry, and it deploys to `environment: release`. Tests: `tests/test_release_acceptance_gate.py`. Admin half is O-5 (open). The rest of steps 9–12 is WP-23.6 |

### Wave 1 — P0 correctness (independent slices first)

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-01.1 | Verification is `COMPLETE` only when every eligible item was judged; failures and skips are counted separately; decides D-2 (N5) | M | — | done | [PR #155](https://github.com/Abe-Borg/drawing-analyzer/pull/155), 2026-09-23. One rule, `models.item_coverage_status` (D-2), over both passes. The denominator is fixed before any call (`VerifyResult.eligible`); skips and calls that returned no judgment are counted and surfaced separately (`coverage_note`). Investigation reports the findings it recovers and never rewrites verification's record. Tests: `tests/test_drawing_acceptance.py` (N5 block), `tests/test_drawing_verify.py` (completeness section). Residual: a finding that raises after the single-crop loop picks it up keeps its prior verdict (the report shows *Not checked*); the stage counts it "not accounted for" and stays off `COMPLETE` |
| WP-01.2 | Shared terminal-outcome helper; the digest (real-time and batch) never admits a refusal, truncation or `stop_reason=None` read as success or into either cache level; cached refusals are rejected when read; decides D-1 (N4 digest, N27) | M/L | — | done | 2026-09-23. One classifier, `core.terminal_outcome.classify_stop_reason` (D-1), its vocabulary pinned by test to the SDK's `StopReason` ∪ `BetaStopReason`. Both transports share one ladder (`digest.digest_terminal_error`), one write predicate (`digest.digest_cache_admits`, both levels) and one loader (`digest.sheet_digest_from_cache_entry`, all three cache hits), which serves only a stored finished stop reason; a stored `null` and a missing key are misses (D-4 started, one migration-register row, no schema or key change). Tests: `tests/test_digest_terminal_outcome.py`, `tests/test_terminal_outcome.py`, `tests/test_drawing_acceptance.py::test_a_refused_or_unfinished_digest_holds_the_run_below_complete`. Residual: N15, an errored digest's findings still reach the ledger (WP-01.3) |
| WP-04.1 | Quantity tokenizer: hyphenated units, thousands groups, opaque malformed tokens, `deg`/`°` (angle vs temperature), lists and ranges, W×H and V/A with a negative corpus; critique-scoped cache term (B2, B3, B12, N19) | M | — | todo | |
| WP-04.2 | Compatibility rule over per-unit value sets and partial tag overlap; one shared `signature_conflicts` that the A/B harness also uses (N1) | M | WP-04.1 | todo | |
| WP-03.1 | Symmetric complete-link in Pass B, order-independent entry count (B1, count part) | S | — | todo | |
| WP-03.2 | Deterministic total-order tie-break in `assign_qc_ids` (K5) | S | — | todo | |
| WP-03.3 | Remove the auditor coordinator's id dedup; arithmetic claim discriminator so the ledger keeps two different same-row mismatches; Decimal claim-dedup keys (B7) | S/M | — | todo | |
| WP-07.1 | Occurrence-aware, sheet-grounded operand support; provenance decided after anchoring; a fabricated quote or unresolved sheet is never DETERMINISTIC (N3) | M | — | todo | |
| WP-07.2 | Strict numeric tokens (tag and sheet-id digits, hyphen-as-minus, `1e3`) and host-side relationship checks (A8) | M | WP-07.1 | todo | |
| WP-05.1 | Cross-QC grounding: a real match for every non-empty quote at word boundaries; no text means unavailable evidence; one normalizer shared with `anchor`; `_CROSS_QC_CACHE_CONTRACT` 3→4 (B5, N12 cross-QC part, N13) | M | — | todo | |
| WP-05.2 | Anchor punctuation folding and a source-word-boundary rule (B4: `PSI,`, `NOTE 3:`, `(568 L/MIN)`; N12 anchor part: `VAV-2` in `VAV-2-1`) | M | — | todo | |
| WP-06.1 | Cross-QC prompt says category `question` with severity `low`; invalid-field counters on both paths; candidate duplicates go to the ledger instead of being destroyed (B6, N2) | S/M | — | todo | |
| WP-09.1 | Boilerplate filter with repeatable qualifiers; negation-aware synthesis conflict extraction (B11, N11) | S | — | todo | |
| WP-09.2 | Prose matching rejects signature-incompatible candidates; per-item outcome counters; labelled paraphrase corpus (no threshold change) (N10, U11) | M | WP-04.2, WP-09.1 | todo | |
| WP-01.3 | Digest partial reads: a raised-cap retry never loses the first read; findings from an errored, refused or truncated digest are labelled or held out of the ledger (N15, N16) | M | WP-01.2 | todo | Since WP-01.2 a refused or unfinished digest carries an error too, so N15 now also covers, for example, an N27 partial read whose unclosed findings block was salvaged: its findings still reach the ledger unlabelled. `digest.digest_terminal_error` is the ladder to extend, not restate |
| WP-01.4 | Critique: `max_tokens`/refusal/unknown terminal states are not completed reads on either transport; critique-only cache contract term (N4 critique) | M | WP-01.2 | todo | |
| WP-11.1 | Per-source and per-page fault isolation in the render and prescan iterators; the inventory is the page denominator; every expected page gets an outcome (R1 core) | M | — | todo | |
| WP-11.2 | Digest-phase containment: completed paid digests, journal and manifest always ship; uploads and spool released on every exit (R1) | M | WP-11.1 | todo | |
| WP-16.1 | Key store: BOM-safe load, repair of BOM values already in the keyring, shape check, migration that never deletes the only good copy (G3) | S/M | — | todo | |
| WP-16.2 | Run-scoped client snapshot passed from `gui._worker`; key entry disabled while busy; the key is no longer written to `os.environ` (G2) | M | — | todo | |

### Wave 2 — P0 remainder, test fidelity, cache contracts, identity

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-02.2 | Real-SDK contract tests over `httpx2.MockTransport`; strict fakes that reject what the SDK rejects (betas or fallbacks on the plain namespace, non-streaming above the SDK-derived cap) (U26) | M | WP-02.1 | todo | |
| WP-02.3 | Fidelity fixtures: nested batch errors; canceled/expired envelopes; `None` usage fields; `web_fetch_requests`; `iterations`; `cache_creation` split; `output_tokens_details`; `stop_details`; fallback blocks; serving model; SSE sequences incl. mid-stream failure and clean EOF (U26) | M | WP-02.2 | todo | |
| WP-01.5 | Batch refusal recovery under the selected transport policy, retry bound shared with truncation retries, `stop_details` logged (R2) | M | WP-01.2 | todo | Since WP-01.2 the abandoned-batch harvest resolves only finished reads, so a refused item it reads back is resubmitted with the unresolved sheets, within the existing bounded rounds (as an empty or truncated one already was). Decide whether that resubmission is allowed and count it against the shared retry bound. Classify with `core.terminal_outcome` (D-1) |
| WP-01.6 | Remaining response consumers (planner, identity, synthesis, focus, prose harvest cache writes); fallback-aware shared text join (U2; WP-09 step 6) | M | WP-01.2, WP-02.3 | todo | Also move `verify._verdict_from_response` / `_degrade_kind` onto `core.terminal_outcome` (D-1). They test `max_tokens` and `refusal` only, so an unknown stop reason or `model_context_window_exceeded` is still parsed as a verdict (WP-01.2 left verification alone: not an N4 site) |
| WP-01.7 | Interrupted-stream outcome and usage capture (`current_message_snapshot`), threaded through the digest retry loop (U1 partial-stream part; WP-14 step 7) | M | WP-01.2, WP-02.3 | todo | |
| WP-05.3 | Character-stream fallback tier with a quantity-aware numeric veto (B4: `6 "`, `INCHDRAIN`, `12' - 6"`, `2 %`). Matches only contiguous source words, never a "manufactured joined string" (plan §2 rule 15) | M | WP-05.2, WP-04.1 | todo | |
| WP-06.2 | Whole-set cross-QC on host handles (label shown beside handle), grounded against **uncapped** evidence text like the sharded path, claims rebound through handles, framing hashed into the key; decides D-8 if not yet decided (N6, U8, K2) | L | WP-05.1 | todo | |
| WP-06.3 | Cross-QC terminal honesty: `stop_reason` checked, streaming, bounded raised-cap retry, bounded partial-array salvage, fact-cap and omission counters; decision recorded for N14 (U6, U7 observability, N14) | M | WP-01.2 | todo | |
| WP-10.1 | Tile-label and display-label contract folded into the keys without invalidating unchanged entries (K1) | S | — | todo | |
| WP-10.2 | Critique contract resolved per transport at probe and store; batch runs log that the structured flag is ignored (K3) | S/M | — | todo | |
| WP-10.3 | Planner loss metadata stored with the plan; legacy entries report loss as unknown (K4) | S/M | WP-01.1 | todo | |
| WP-10.4 | Cache map with the admission predicate of every write; N4 read-side migration completed; migration register filled (N4 cache part; WP-10 steps 1, 7, 9) | S/M | WP-01.2, WP-01.4 | todo | |
| WP-03.4 | Versioned `claim_id` beside the existing `id`; the inventoried consumers switched; cross-QC and prose-harvest cache restores rebound; decides D-3 (B8 identity) | L | WP-03.2 | todo | |
| WP-03.5 | Lossless observations: upstream merges hand observations to the ledger; observations and alternative actions serialized (incl. critique cache); specificity-aware representative (B9, B1 rest) | L | WP-03.1, WP-03.4, WP-04.2 | todo | |
| WP-03.6 | Canonical final clustering over retained observations; per-observation anchors; idempotent reconciliation (WP-03 clustering clarification) | M/L | WP-03.5 | todo | |
| WP-06.4 | Direction-free merge for reversed cross-sheet conflicts with a stated same-claim predicate (B10) | M | WP-03.4, WP-06.1 | todo | |
| WP-07.3 | Truthful arithmetic counters split by provenance; contradictory transcriptions of one quote flagged (N18; WP-07 step 7) | S/M | WP-07.1, WP-03.3 | todo | |
| WP-11.3 | Source revision checked on every reopen (verify, investigate, markup) (R1 revision part) | M | WP-11.1 | todo | |

### Wave 3 — P1 evidence quality: auditors, citations, investigation

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-12.1 | Contiguous citation text assembly (no injected newlines); source trail across `pause_turn` and web fetch (C1, C5) | S | — | todo | |
| WP-12.2 | Full evidence text and em-dash edition grammar across harvest, basis, reconcile and identity windows; identity host-contract key term (C2, C6) | M | — | todo | |
| WP-12.3 | Code-family grammar and shared alias table (ASHRAE, IECC, NEC, Title 24, ASCE, CBC) (U10 families) | M | WP-12.2 | todo | |
| WP-12.4 | Contextual code-window ranking (H4) | S | WP-12.2 | todo | |
| WP-12.5 | Mentioned vs adopted codes end to end, preserving Phase B two-tier trust (U10) | M/L | WP-12.3, WP-12.4 | todo | |
| WP-12.6 | Terminal and coverage gate before citation verdict-cache writes (WP-12 step 8) | S | WP-01.2 | todo | |
| WP-13.1 | Task-budget rejection markers narrowed; `normalize_sheet_id` in `investigate`; ambiguous crop targets refused (U3, U12 ids) | S | — | todo | |
| WP-13.2 | Evidence finalized on every exit; saved/sent/judged states; `find_text` recorded in the trace; decides D-6 (R7) | M | — | todo | |
| WP-13.3 | Separate search and image budgets, honest tool wording, prompt version and key bumped (C4) | M | WP-13.2 | todo | |
| WP-13.4 | Raised-cap turn retry without re-running tools; fallback-boundary replay that never executes pre-fallback `tool_use` (N20, U12 truncation) | M | WP-01.2, WP-02.3 | todo | |
| WP-08.1 | CSI sections need a lexical cue (fixtures move to cue forms); naming key keeps letter/digit order (A1, A2) | S/M | — | todo | |
| WP-08.2 | Inventory-scoped resolution memo on `SheetInventory`; lazy nearest match; operation-count targets (A3) | M | — | todo | |
| WP-08.3 | Reference phrase and list recall with per-target quote spans; dead `sug` removed (A4) | M | WP-08.2 | todo | |
| WP-08.4 | Label-aware own-ID ranking with surfaced ambiguity; FM handling, including references to missing FM sheets (A5, A6, N17) | M | WP-08.2 | todo | |
| WP-08.5 | Drawing-index region detection; partial-package handling in both directions (A7) | M | WP-08.4 | todo | |

### Wave 4 — P1 lifecycle, accounting, resources, diagnostics

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-14.1 | Every non-succeeded batch envelope keeps a non-billable attempt record; the harvest counts only `succeeded` as responded (R3, incl. terminal path) | S | — | todo | |
| WP-14.2 | TTL-split cache-write accounting from `usage.cache_creation`; per-TTL pricing; stale pricing comment fixed (C3) | S/M | WP-02.3 | todo | |
| WP-14.3 | One shared response-metadata reader: serving model, `iterations`, `stop_details`, `fallback_credit`, `output_tokens_details`, `web_fetch_requests` (U1) | M | WP-02.3 | todo | |
| WP-14.4 | `UsageRecord` known/unknown usage through the single `is_billable_but_unpriced` rule; `by_model` decision; pricing date on every surface; decides D-7 (WP-14 steps 4, 8) | M | WP-14.3 | todo | |
| WP-14.5 | Per-attempt usage records from every stage result type (WP-14 step 3) | L | WP-14.4, WP-01.2 | todo | |
| WP-14.6 | Serving model carried through cache payloads (additive field) and the manifest (U1 provenance) | M | WP-14.3, WP-14.4 | todo | |
| WP-16.3 | `_persist_key` reentrancy guard; Forget saved key; export never reloads a cleared key (U20) | S/M | WP-16.1 | todo | |
| WP-17.1 | Cancel: cancel event, Cancel button, batch cancel and harvest with no resubmit, honest quit wording, partial export; decides D-5 (G1 core) | M/L | WP-16.2 | todo | |
| WP-17.2 | Keyless atomic job record (batch ids, `custom_id` → source/page/cache key, upload ids); relaunch lists unresolved jobs and offers remote cancel (G1) | M | WP-17.1 | todo | |
| WP-17.3 | Harvest recorded jobs' results into `DigestCache` after fingerprint validation (G1) | M | WP-17.2 | todo | |
| WP-17.4 | Crash matrix, unresolved-submission reconciliation, instance lock/lease (G1) | L | WP-17.3 | todo | |
| WP-18.1 | Files-API failure never becomes full-rate work under Economy on either transport; recovery policy threaded into the submit functions (N21, U4) | M | — | todo | |
| WP-18.2 | Inline request size guard in the shared builder (authorized fallback and Fast/Hybrid) (U4) | S/M | WP-18.1 | todo | |
| WP-18.3 | Work-dir and render-spool leases so a live run is never pruned (U9) | M | — | todo | |
| WP-18.4 | Upload error classification; truthful retention text ("files persist until deleted") (N22) | S | — | todo | |
| WP-18.5 | Durable upload ownership and bounded reclaim of provably app-owned orphans (U5) | M/L | WP-17.2, WP-14.4 | todo | |
| WP-19.1 | Pair-aware chat history normalization at Stop, commit, cap exit, catch, save and restore; `pause_turn` rounds merged; transcript v1 accepted and repaired (R4) | M | — | todo | |
| WP-19.2 | Mixed client/server tool and pause semantics; replay canary written (run blocked on O-4) (R4, U2) | S/M | WP-19.1 | todo | Running the canary is O-4 |
| WP-22.1 | Linear secret redaction (incl. `RedactingFormatter`); path scrub handles URLs, doubled separators, `\\?\` and UNC (U13) | M | — | todo | |
| WP-22.2 | Critique read count resolved once; `critique_N` tags counted as one family (N25, U15) | S/M | — | todo | |
| WP-22.3 | One shared `refs` coercion replacing the three that disagree (U16) | S | — | todo | |
| WP-22.4 | Supported configuration matrix; required-stage roll-up cannot report COMPLETE with missing stages (U14, U15) | M | WP-01.1 | todo | |
| WP-22.5 | Hygiene: stale descriptions, "Spec Critic" docstrings, F401/F811/F841/B017 lint step in both workflows; removal only of helpers that mislead, never incidental API removal; `count_tokens_via_api` kept (U27) | S | — | todo | |

### Wave 5 — P1/P2 report, chat, estimates, packaging, updates

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-21.1 | Markup plan rebuilt from worker receipts by `placement_id`; serial and process-pool manifests agree (R5) | S | — | todo | |
| WP-21.2 | Repeat grouping recomputed after sort; cached search text with identical results; CLAUDE.md sentence fixed (H1, U18) | S/M | — | todo | |
| WP-21.3 | Index and bookmark links go to the actual written destination (notes row rect); navigation keyed by `placement_id` (N9, B8 navigation) | M | WP-21.1 | todo | |
| WP-21.4 | One display vocabulary: sheet-level observation, no quote, quote not found, not checked, inconclusive, failed attempt (H2) | M/L | WP-05.1, WP-05.2, WP-01.1 | todo | |
| WP-20.1 | Exact calculator: full numeric grammar, BigInt rationals, bounds, `is_error: true`, no "guaranteed correct" wording (N7) | S/M | — | todo | |
| WP-20.2 | Chat cost readout from final cumulative usage, cache-write TTL split and web-search charges (H3) | S/M | — | todo | |
| WP-20.3 | Reader key and transcript storage policy validated in Chromium; in-memory where isolation cannot be shown (N26, U19) | S/M | — | todo | |
| WP-20.4 | Bounded report context with index and retrieval tools; 400-sheet fixture; duplicate labels (U17) | L | WP-19.1 | todo | |
| WP-20.5 | History budgeting at complete exchange boundaries (U17) | M | WP-19.1, WP-20.4 | todo | |
| WP-15.1 | Preflight runs without profiles, has no render-identity hashing and holds the lock around every PyMuPDF use; per-file source ids (\$3, N23, N24) | M | — | todo | |
| WP-15.2 | Hybrid spool: consume it or never create it (R6) | S | — | todo | |
| WP-15.3 | Text and prompt/framing overhead priced per stage from `text_chars` (\$2) | S/M | WP-15.1 | todo | |
| WP-15.4 | Reasoning-inclusive output bands and a calibration script with an aggregate fixture (\$1) | M | WP-14.5, WP-22.2 | todo | |
| WP-15.5 | Call-plan scaling (cross-QC shards, stragglers, retries, investigation) and pending-charge wording (WP-15 steps 4–5) | M | WP-15.4, WP-17.1 | todo | |
| WP-23.2 | PyInstaller `collect_submodules` in place of `collect_all`; `dist/` secret scan before ISCC with redacted output; hooks pinned; functional keyring self-check (G4, U21) | M | — | todo | Validated by the PR's Windows build |
| WP-23.3 | Constrained runtime lock including GUI dependencies; gates run under it; freeze diff (G5) | M | WP-23.2 | todo | |
| WP-23.4 | Installer `[InstallDelete]` upgrade cleanup; architecture declarations; uninstall retention policy documented (U23) | M | WP-23.2 | todo | Manual Windows test is O-8 |
| WP-23.5 | License allowlist and pip-audit run on the shipped Windows environment (U24) | M | WP-23.3 | todo | Unknown licenses need O-9 |
| WP-23.6 | Release attestation, the rest of WP-23 steps 9–12: bind the acceptance record to the tested candidate (a code-tree fingerprint with an evidence-only allowlist: version literals, CHANGELOG heading, `docs/releases/`) and to the built artifact hashes; per-section validation (each §§2–6 item recorded or covered by a named waiver); stale, wrong-commit and wrong-artifact record tests; optional API evidence that the `release` environment is protected (N8) | M | WP-23.1 | todo | The protection evidence needs O-5 |
| WP-24.1 | One HTTPS-only opener with a host policy; download size cap; re-hash immediately before launch; update prompt deferred while busy; docs corrected (G6, U22, U25) | M | — | todo | |
| WP-24.2 | Signed-manifest verification with a test keypair (canonical encoding, key ids, rotation) | M | WP-23.3 | todo | Production key is O-6 |
| WP-24.3 | Authenticode signing and verification hook | S | WP-23.2 | blocked: O-7 | |
| WP-02.4 | Live batch and cancellation canaries written (bounded wait, cancel, harvest, cleanup, IDs reported) (U26) | S | WP-02.3 | todo | Running them is O-4 |
| WP-02.5 | Strict release mode for `scripts/run_acceptance.py`: a skipped gate is never an overall PASS (WP-02 acceptance) | S | — | todo | |

### Wave 6 — integration, live/manual acceptance, experiments

| Slice | Scope | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| INT.1 | Audit the plan §6.1 regression corpus: every fixture group exists; fill the gaps | M | Waves 0–2 | todo | |
| INT.2 | Plan §6.3 end-to-end assertions as tests, plus the §6.2 pairwise matrix | L | INT.1 | todo | |
| INT.3 | Release report: the disposition register below, completed with evidence (plan §10) | S | INT.2 | todo | |
| WP-25.1 | Experiment: shared digest/critique vision prefix and per-sheet scheduling | — | Waves 0–2 | blocked: O-4 | |
| WP-25.2 | Experiment: batch prompt caching | — | — | blocked: O-4 | |
| WP-25.3 | Experiment: critique cache TTL from measured inter-read timing | — | WP-14.2 | blocked: O-4 | |
| WP-25.4 | Experiment: cross-QC text allocation and cross-shard recall (incl. N14) | — | WP-06.3 | blocked: O-4 | |
| WP-25.5 | Experiment: structured outputs for identity, planner and cross-QC | — | WP-01.6 | blocked: O-4 | |
| WP-25.6 | Experiment: diverse second critique model or reduced read count | — | WP-22.2 | blocked: O-4 | |
| WP-25.7 | Experiment: smaller overlap, adaptive tile resolution, smaller overview | — | — | blocked: O-4 | |
| WP-25.8 | Experiment: verifier text alongside crops; initial investigation pre-search | — | WP-13.3 | blocked: O-4 | |
| WP-25.9 | Experiment: investigation forced-close cache policy and shorter TTLs | — | WP-13.4 | blocked: O-4 | |
| WP-25.10 | Experiment: batch verification | — | WP-01.1 | blocked: O-4 | |
| WP-25.11 | Experiment: new web-tool variants; web fetch on Opus 5 (U32) | — | — | blocked: O-4 | |
| WP-25.12 | Experiment: native PDF grouping and named destinations | — | WP-21.3 | blocked: O-8 | |

## Owner actions and external gates

Coding sessions must never mark these done. The owner updates them, or asks a
session to record the owner's decision.

| ID | Action | Why / blocks | Status |
|---|---|---|---|
| O-1 | Decide how to handle **v1.7.0 already published as the stable `latest` release** (2026-09-21 22:13 UTC, `da8f810`) even though `ACCEPTANCE-1.7.0.md` put it on HOLD. Either demote it to a pre-release (`latest` falls back to 1.6.0; existing 1.7.0 installs cannot downgrade), or record or waive §§2–6. Either way, correct the record: it still reads "NOT YET TAGGED"/HOLD, and the commit, published asset sha256s and Inno Setup version are unfilled. A session may draft the factual fields on request; only the owner signs. | N8 occurred; every install is offered 1.7.0 within a day | open |
| O-2 | Merge the plan-setup PR (#152) before starting coding sessions. | Sessions branch from `main` | open |
| O-3 | Choose the release cadence. Suggestion: `1.8.0rc1` after Wave 1, stable only through the WP-23.1 gate. | Release planning | open |
| O-4 | State a live API budget per session, if any. Needed for canaries (WP-02.4, WP-19.2), live structured-output checks and the WP-25 experiments. | Live evidence | open |
| O-5 | Configure a protected `release` environment and/or tag ruleset with required reviewers, and confirm it through the API. YAML alone cannot prove it; an unconfigured `environment:` is auto-created unprotected. | WP-23.1 independent boundary | open |
| O-6 | Update-manifest signing key: generate it offline, provide the public key, keep the private key only in a protected secret, and define rotation. | WP-24.2 enforcement | open |
| O-7 | Authenticode certificate (optional). | WP-24.3 | open |
| O-8 | Windows manual checks (credential store, installer upgrade/uninstall, long paths) and PDF viewer checks (Acrobat, Bluebeam, browsers). | WP-16, WP-21.3, WP-23.4, WP-25.12 | open |
| O-9 | License decisions for unknown or restricted licenses surfaced by WP-23.5. | WP-23.5 | open |
| O-10 | A private representative evaluation corpus, for comparisons that synthetic fixtures cannot make. | WP-25, INT | open |

## Finding disposition register

This is the plan §7 traceability register with dispositions (the plan §10 release
report is built from it).
- Disposition values:
  - `open`: confirmed present on 2026-09-22 against 1.7.0.
  - `implemented+validated`
  - `already satisfied`
  - `disproved`
  - `deferred (reason)`
  - `blocked (gate)`
- For every non-`open` value, the Evidence cell names the test or PR.

| ID | Summary | Pri | Slice(s) | Disposition | Evidence |
|---|---|---|---|---|---|
| B1 | Pass B complete-link checks one direction; a 550 gpm finding absorbs the 500 gpm one | P0 | 03.1, 03.5 | open | |
| B2 | Hyphenated units (`6-inch`) get no measurement signature | P0 | 04.1 | open | |
| B3 | Thousands separators split numbers (`12,500` signs as `500`) | P0 | 04.1 | open | |
| B4 | Verbatim quotes fail to anchor on punctuation/spacing variance | P0/P1 | 05.2, 05.3 | open | |
| B5 | Cross-QC quotes under 6 chars are "grounded" without a check | P0 | 05.1 | open | |
| B6 | Cross-QC prompt asks for severity `question`; the items are dropped silently | P0 | 06.1 | open | |
| B7 | Distinct same-row arithmetic mismatches: coordinator dedup, then a ledger geometry merge | P0 | 03.3 | open | |
| B8 | `Finding.id` not unique; numbering, bookmarks and index links treat it as identity | P0 | 03.2, 03.4, 21.3 | open | |
| B9 | Merge discards the loser's text and recommended action | P0 | 03.5 | open | |
| B10 | A→B and B→A copies of one conflict both survive | P1 | 06.4 | open | |
| B11 | "No conflicts noted on this sheet." becomes a medium finding | P1 | 09.1 | open | |
| B12 | `deg`/`°` sign differently; `90 deg F` vs `90 deg C` compatible | P0 | 04.1 | open | |
| R1 | Source unreadable after inventory aborts the whole run | P0/P1 | 11.1, 11.2, 11.3 | open | |
| R2 | Refused batch item never retried or rescued | P1 | 01.5 | open | |
| R3 | Canceled/errored envelopes lose attempt records (harvest and terminal path) | P1 | 14.1 | open | |
| R4 | Chat commits an unrun `server_tool_use`; history poisoned, persisted | P1 | 19.1, 19.2 | open | |
| R5 | Process-pool markup plan disagrees with receipts | P1 | 21.1 | open | |
| R6 | Hybrid spools renders to disk and never reads them | P2 | 15.2 | open | |
| R7 | Investigation error paths orphan saved evidence | P1 | 13.2 | open | |
| C1 | Citation reply split across text blocks gets a `\n` inside JSON strings | P1 | 12.1 | open | |
| C2 | Edition audit reads the capped `sheet_text` | P1 | 12.2 | open | |
| C3 | Citation cache writes priced at the 5-minute rate | P1 | 14.2 | open | |
| C4 | `find_text` described as free but charged to the evidence budget | P1 | 13.3 | open | |
| C5 | Search results after `pause_turn` and all fetch results missing from sources | P1 | 12.1 | open | |
| C6 | Em dash is not an edition separator | P1 | 12.2 | open | |
| \$1 | Estimator ignores thinking tokens on vision reads | P1 | 15.4 | open | |
| \$2 | Per-sheet prompt tokens 2–8× low; `text_chars` never read | P1 | 15.3 | open | |
| \$3 | Preflight hashes everything; hybrid double render | P2 | 15.1, 15.2 | open | |
| K1 | Tile placement label (and the display label) outside every key | P1 | 10.1 | open | |
| K2 | Cross-QC user-turn framing outside the stage key | P1 | 06.2 | open | |
| K3 | Structured flag + batch parks a fenced merge under the structured key | P1 | 10.2 | open | |
| K4 | Review plan PARTIAL cold, COMPLETE warm | P1 | 10.3 | open | |
| K5 | QC numbering depends on ingest order | P0 | 03.2 | open | |
| A1 | Any row of three 2-digit numbers becomes a CSI citation | P1 | 08.1 | open | |
| A2 | `P-3` reported as a misspelling of `3P` | P1 | 08.1 | open | |
| A3 | Reference auditor quadratic in references × sheets | P1 | 08.2 | open | |
| A4 | Reference phrases (`SEE DWG`, `REF.`, lists) not harvested | P1 | 08.3 | open | |
| A5 | Own sheet-id detection picks a bottom-right distractor | P1 | 08.4 | open | |
| A6 | A note id displaces an FM sheet's own id (see also N17) | P1 | 08.4 | open | |
| A7 | A prose sheet read as the drawing index | P1 | 08.5 | open | |
| A8 | Tag/sheet-id digits count as operands; `1e3` → 1; hyphen read as minus | P0 | 07.2 | open | |
| H1 | Sorting never recomputes repeat grouping (CLAUDE.md claims it does) | P2 | 21.2 | open | |
| H2 | A quote-less sheet-level finding is branded "Unanchored" | P1 | 21.4 | open | |
| H3 | Chat cost ignores final usage and web-search charges | P2 | 20.2 | open | |
| H4 | ALL-CAPS notes fill the identity code windows | P1 | 12.4 | open | |
| G1 | No Cancel; quitting leaves a batch billing, nothing resumable | P1 | 17.1–17.4 | open | |
| G2 | Key entry live during a run; every stage re-reads the environment | P1 | 16.2 | open | |
| G3 | BOM key migrated into the keyring, legacy file deleted | P1 | 16.1 | open | |
| G4 | PyInstaller `collect_all` bundles stray files (key file) | P1 | 23.2 | open | |
| G5 | Release gates test a different dependency set than ships | P1 | 23.3 | open | |
| G6 | Installer hashed at download only, launched hours later | P1 | 24.1 | open | |
| N1 | One shared value (`100 psi`, `12ft`) masks conflicting measurements | P0 | 04.2 | open | |
| N2 | Cross-QC dedup destroys distinct claims sharing sheet/quote/legs | P0 | 06.1 | open | |
| N3 | Reused operand membership (and fabricated quotes) give false DETERMINISTIC | P0 | 07.1 | open | |
| N4 | Refused/truncated digests and critiques accepted and cached | P0 | 01.2, 01.4, 10.4 | open (digest part implemented+validated in 01.2; the critique part (01.4) and the cache map (10.4) stay open) | `tests/test_digest_terminal_outcome.py` (both transports, both cache levels, the read-side reject, the warm re-run of a refusal the old code cached, the delivery contract) and `tests/test_drawing_acceptance.py::test_a_refused_or_unfinished_digest_holds_the_run_below_complete` (WP-01.2). Remaining: the critique (WP-01.4: `critique.outcome_from_message`, and a critique-only contract term, since critique entries store no stop reason); the cache map and the other writers' admission predicates (WP-10.4) |
| N5 | Verification COMPLETE with no judgments or with skipped items | P0 | 01.1 | implemented+validated | `tests/test_drawing_acceptance.py::test_verification_is_complete_only_when_every_eligible_finding_was_judged` (six of the plan's seven cases, plus all-truncated and all-skipped) and `::test_a_later_investigation_never_erases_the_verification_outcome` (the seventh); `tests/test_drawing_verify.py` completeness section (WP-01.1, [PR #155](https://github.com/Abe-Borg/drawing-analyzer/pull/155)) |
| N6 | Duplicate sheet labels bind first-wins (whole-set, dedup, arithmetic, legs) | P1 | 06.2 | open | |
| N7 | Calculator accepts malformed numbers; inexact large integers | P1 | 20.1 | open | |
| N8 | Stable publish ignores the acceptance hold (it happened for 1.7.0) | P1 | 23.1, 23.6, O-1, O-5 | open (publish gate implemented+validated in 23.1; the O-1 and O-5 parts stay open) | `tests/test_release_acceptance_gate.py` (WP-23.1, [PR #154](https://github.com/Abe-Borg/drawing-analyzer/pull/154)). Remaining: O-1 (the published v1.7.0 and its record), O-5 (protect and confirm the `release` environment and a `v*` tag ruleset), WP-23.6 (commit and artifact binding) |
| N9 | Overflow-note index/bookmark links land at the page top, not the row | P2 | 21.3 | open | |
| N10 | Prose-harvest matching ignores measurement signatures (4 in absorbed by 6 in) | P0 | 09.2 | open | |
| N11 | Synthesis conflict extraction is negation-blind | P1 | 09.1 | open | |
| N12 | Matches ignore word boundaries (`VAV-2` inside `VAV-2-1`; `AHU-10` inside `AHU-101`) | P0 | 05.1, 05.2 | open | |
| N13 | Cross-QC and anchor normalizers disagree (curly quotes, `½`, `×`, `Ø`) | P1 | 05.1 | open | |
| N14 | Degraded cross-QC never cached: re-billed every warm run, run stays PARTIAL | P1 | 06.3, 25.4 | open | |
| N15 | Findings from errored/refused/truncated digests ingested unlabelled | P1 | 01.3 | open | |
| N16 | A raised-cap retry can lose the first (truncated) read | P1 | 01.3 | open | |
| N17 | References to FM-numbered sheets are never reported as missing | P1 | 08.4 | open | |
| N18 | Contradictory transcriptions of one quote counted as independent checks | P1 | 07.3 | open | |
| N19 | W×H duct sizes, `20A`/`480V`, ranges and lists get no or partial signature | P0 | 04.1 | open | |
| N20 | Investigation executes and echoes pre-fallback `tool_use` blocks | P1 | 13.4 | open | |
| N21 | Files-API failure fallbacks send full-rate requests under Economy; inline can exceed the size limit | P1 | 18.1, 18.2 | open | |
| N22 | Code and help text claim uploads "expire server-side"; they persist until deleted | P1 | 18.4, 18.5 | open | |
| N23 | GUI cost preflight never runs in a default install (no profiles ship) | P1 | 15.1 | open | |
| N24 | `render.list_sheets` runs on the UI thread outside the preflight lock | P1 | 15.1 | open | |
| N25 | `DRAWING_ANALYZER_CRITIQUE_RUNS ≥ 3` fabricates cross-family corroboration | P1 | 22.2 | open | |
| N26 | Chat transcript kept in `localStorage` on `file://`, readable by other local files | P1 | 20.3 | open | |
| N27 | A stream that ends without `message_stop` is cached as a complete digest | P0 | 01.2 | implemented+validated | `tests/test_digest_terminal_outcome.py::test_n27_a_real_sdk_stream_that_ends_without_message_stop_is_not_a_digest` (the real SDK's stream accumulator over an in-process transport, through `digest_sheet`), plus the `stop_reason=None` cases on both transports, at both cache levels and through the pipeline (WP-01.2) |
| U1 | Serving model, fallback iterations and partial-stream billing unrecorded | P1 | 14.3, 14.6, 01.7 | open | |
| U2 | Fallback text joins and selective history replay | P1 | 01.6, 12.1, 13.4, 19.2 | open | |
| U3 | Generic `output_config` 400 disables task budgets process-wide | P1 | 13.1 | open | |
| U4 | Oversized inline fallback; upload quota failures (see N21) | P1 | 18.1, 18.2, 18.4 | open | |
| U5 | Remote orphan files; daemon-only cleanup (see N22) | P1 | 18.5, 17.2 | open | |
| U6 | Cross-QC output cap shared with thinking; no truncation recovery | P1 | 06.3 | open | |
| U7 | Cross-QC 4k text budget and 40-fact bottleneck | P1 | 06.3, 25.4 | open | |
| U8 | Whole-set cross-QC path does no grounding | P0/P1 | 06.2 | open | |
| U9 | Pruning can reap a live-but-idle run's work dir | P1 | 18.3 | open | |
| U10 | Mentioned vs adopted codes; missing edition families | P1 | 12.3, 12.5 | open | |
| U11 | Prose-match threshold and call prevalence (see N10) | P1 | 09.2 | open | |
| U12 | Investigation truncation; Unicode sheet ids; first-wins duplicate ids | P1 | 13.1, 13.4 | open | |
| U13 | Quadratic `redact_secrets`; path-scrub gaps | P1 | 22.1 | open | |
| U14 | Empty or partial required-stage lists roll up COMPLETE | P2 | 22.4 | open | |
| U15 | Resolved configuration differs from execution | P1 | 22.2, 22.4 | open | |
| U16 | String `refs` split into characters (three coercions disagree) | P1 | 22.3 | open | |
| U17 | Unbounded report/history context in the chat | P1 | 20.4, 20.5 | open | |
| U18 | Search rescans the whole report per keystroke | P2 | 21.2 | open | |
| U19 | Reader key in `sessionStorage` on `file://` (see N26) | P1 | 20.3 | open | |
| U20 | `_persist_key` reentrancy; cleared key reloaded on export; no Forget | P1 | 16.3 | open | |
| U21 | Frozen build never verifies a working keyring backend | P1 | 23.2 | open | |
| U22 | Update dialog appears over the cost-confirm and file dialogs | P2 | 24.1 | open | |
| U23 | Uninstall retention policy undocumented | P2 | 23.4 | open | |
| U24 | License check tests metadata presence only, never on the shipped env | P1 | 23.5 | open | |
| U25 | README network claim; checksum described as authenticity | P2 | 24.1 | open | |
| U26 | Test fake fidelity, no batch canary, no socket guard | P0 | 02.1–02.4 | open (socket/credential guard and `network` opt-in implemented+validated in 02.1) | `tests/test_hermetic_guard.py` (WP-02.1, [PR #153](https://github.com/Abe-Borg/drawing-analyzer/pull/153)). Remaining: strict fakes and real-SDK contract tests (02.2), fidelity fixtures (02.3), batch canary (02.4) |
| U27 | Narrow lint classes; production-orphaned helpers | P2 | 22.5 | open | |
| U28 | Broken system `cryptography` wheel (container) | — | — | disproved (environment) | `pip install cffi` fixes it; README step 2 |
| U29 | Remove `tiktoken` | — | — | already satisfied | 1.7.0 (`6dad8bf`) |
| U30 | Add Dependabot | — | — | already satisfied | `.github/dependabot.yml` (pre-1.6.0) |
| U31 | Revalidate broad "everything sound" claims in touched areas | — | every slice | open | Each slice's handoff says what it re-checked |
| U32 | Web fetch on Opus 5 unsettled (review §3.4) | P2 | 25.11 | blocked (O-4) | |

## Handoff log (newest first)

Each session adds one entry at the top: date, slices and IDs, PR, what changed,
contracts decided, cache/schema effects, validation actually run (with counts),
what could not be verified, risks, and next steps.

### 2026-09-23 — WP-01.2: the digest never admits a read the model did not finish

- **Slice and IDs:** WP-01.2. N4 (the digest part) and N27. Decides D-1
  (response outcome). Starts D-4 (cache contract), which WP-10.4 completes.
- **What changed:**
  - **One terminal-outcome classifier (D-1).** New `core/terminal_outcome.py`:
    `classify_stop_reason(stop_reason)` returns a `TerminalOutcome(kind,
    stop_reason)`. The kinds:
    - `FINISHED`: `end_turn`, `stop_sequence`;
    - `TRUNCATED`: `max_tokens`, `model_context_window_exceeded`;
    - `REFUSED`: `refusal`;
    - `UNFINISHED`: `None`;
    - `CONTINUATION`: `tool_use`, `pause_turn`, the beta `compaction`;
    - `UNKNOWN`: anything else, never finished.

    `raised_cap_may_finish` is true for `max_tokens` only: a larger cap cannot
    make room in a full context window. The vocabulary is the installed SDK's
    `StopReason` ∪ `BetaStopReason` (Opus 5 calls travel the beta namespace
    for the refusal fallback), and a test pins the table to it, so an SDK
    upgrade that adds a reason fails until someone classifies it.
  - **The digest, on both transports.** One ladder, `digest.digest_terminal_error`,
    is used by `digest_sheet` (and so batch's Files-API inline fallback) and by
    `batch_digest._digest_from_message` (and so the direct-call rescue).
    - A refusal, empty or with text, sets `refused digest (stop_reason='refusal')`.
    - A `None` stop reason, a continuation or an unknown reason sets
      `unfinished digest (stop_reason=…)`.
    - A context-window stop sets `truncated digest
      (stop_reason='model_context_window_exceeded')`.
    - The messages for an empty reply and a `max_tokens` truncation are
      unchanged.

    The text is kept on the sheet in every case.
  - **Cache writes.** One predicate, `digest.digest_cache_admits` (no error,
    nonempty text, a finished stop reason), guards both level-2 writers and
    the pipeline's level-1 store-under-both.
  - **Cache reads (the N4 migration).** The three loaders that forced
    `error=None` now share `digest.sheet_digest_from_cache_entry`, which
    returns `None` (a miss) unless the stored stop reason is finished: level 2
    in `digest_sheet`, level 2 in `submit_drawing_batch`, and level 1 in
    `pipeline._level1_partition`. A rejected entry is logged, left on disk,
    and overwritten by the finished re-read.
  - **Retries are unchanged.** Both raised-cap retry predicates now read
    `raised_cap_may_finish`; only `max_tokens` is retried, as before.
  - `batch_digest._parse_item` logs the sheet's actual error rather than
    always "empty digest".
  - **Docs.**
    - CHANGELOG: a Fixed entry for N4 (digest part) and N27.
    - CLAUDE.md: the digest-path paragraph and the `core/` sentence. The N16
      entry in its known-inaccurate list is untouched; WP-01.3 owns it.
    - README: the QC-status overview, a rewritten *A reply the model did not
      finish* block, and one sentence in *Stuck batches*.
- **Contracts decided:** D-1 (decided). D-4 (started: digest admission and the
  read side; WP-10.4 completes it). Both are in [`DECISIONS.md`](DECISIONS.md).
- **The migration decision** (the session request asked for it to be
  deliberate):
  - a stored `"stop_reason": null` is the N27 shape, and a miss;
  - an entry with no `stop_reason` key is a miss too. The clone was shallow,
    so the check ran over the full history (464 commits, root `87326ce`):
    - both level-2 writers have stored the key since the root commit, and the
      level-1 store since level 1 was added (`53ab354`);
    - every key folds `_SCHEMA_VERSION`, which has been 10 since `b8399f4`
      (2026-09-10);
    - the legacy JSON store was retired at schema 8 (`f4a7dd6`).

    So no entry a current key can reach lacks the key, and rejecting one
    discards no paid digest.
  - **Correction to the session request.** `2d176bb` is not the import
    commit. It is a 2026-09-04 Codex-review fix, and the root is `87326ce`
    (2026-06-07). Both predate schema 10, so the conclusion does not change.
  - **What the reject can discard.** The truncation guard (`f56796b`) also
    predates schema 10, so the reject can only discard shapes 1.6.0 and 1.7.0
    admitted wrongly: a refusal with text, a `null`, or another non-finished
    stop reason. Every finished entry is still served.
- **Cache/schema effects:** the read-side reject above, and nothing else. No
  `_SCHEMA_VERSION` bump, no key term, no prompt change. One
  migration-register row.
- **Re-baselined tests:** none. No existing test double reached the digest
  without a stop reason: each is a `FakeMessage` (which defaults to
  `end_turn`) or sets its own, and no test relied on a stop-reason-less
  `SheetDigest` being stored at level 1. Every existing test passed unchanged.
- **Validation (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):**
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **2,645 passed, 2 skipped, 10 deselected** (190 s), identical to the
    WP-01.1 handoff.
  - **Reproduced first, on the real SDK.** SDK 1.7.0 over an in-process
    `httpx2.MockTransport` (no socket), with an SSE body that stops after a
    text delta (no `message_delta`, no `message_stop`).
    `get_final_message()` returned the partial text with `stop_reason=None`
    and raised nothing. `digest_sheet` returned it with `error=None` and cached
    it. That run is now a regression test.
  - **Failing first.** The 61 new behaviour tests against the unfixed code: 52
    failed, 9 passed. The 9 pin what the fix keeps:
    - finished reads cache and are served, on both transports (6);
    - the `max_tokens` raised-cap retry (1);
    - the N27 control stream, with `message_stop` (1);
    - no raised-cap resubmission for a context-window stop (1).

    The 20 unit tests for the classifier could not import the new module.
  - **After:** the new tests, 81 passed. Full suite **2,726 passed, 2 skipped,
    10 deselected** (198 s): the baseline plus the 81 new tests, with the same
    two environment skips (IPv6 loopback; chmod as root).
  - **Browser suite** (the report's code is unchanged, but a refused sheet now
    renders with a *Failed* badge): 98 collected, 98 executed and passed;
    `check_browser_suite.py` passes.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` is clean.
    F401/F811/F841 over the touched files shows two hits, both present on the
    base (WP-22.5 territory); none is new. `scan_secrets.py` is clean over 195
    tracked files, the new ones included. `compileall src` passes.
- **Not verified:**
  - **Live API behaviour.** There is no live budget (O-4). A real refusal's
    shape, and a real stream ending mid-response, were not observed. N27 is
    proven on the real SDK's accumulator over a mock transport; refusals are
    hermetic fakes.
  - **Windows.** Covered by this PR's CI.
- **Risks and residual gaps:**
  - **A visible behaviour change.** A refused or unfinished sheet now fails:
    - it lowers the ok-sheet count and is named in `ctx.errors`;
    - it holds the digest stage at `PARTIAL`/`FAILED`, and an exhaustive
      run's `qc_status` below `COMPLETE`.

    A warm run re-reads, and re-bills, any sheet whose cached read was a
    refusal or a stream that ended early: once if the re-read finishes, and on every
    run while it keeps failing. That is by design, since an unfinished read is
    never served.
  - **N15 (WP-01.3).** An errored digest's findings still reach the ledger
    unlabelled. Now that refusals and unfinished reads carry an error, that
    includes an N27 partial read whose unclosed findings block was salvaged.
  - **N16 (WP-01.3)** is unchanged: a raised-cap retry that lands empty or
    refused still discards the first read.
  - **The abandoned-batch harvest** resolves only finished reads, so a refused
    item it reads back is now resubmitted within the bounded rounds, as empty
    and truncated items already were. Noted on WP-01.5 (R2 decides the
    policy and the shared bound).
  - **Verification keeps its own two-reason check.** Noted on WP-01.6.
  - **An SDK bump can fail CI by design.**
    `tests/test_terminal_outcome.py::test_every_sdk_stop_reason_is_classified_and_nothing_else_is`
    fails when an `anthropic` upgrade adds or removes a stop reason, until
    `core/terminal_outcome.py` classifies it. A Dependabot bump of the SDK then
    needs that one-line change. The open Dependabot PRs (#136, #148) do not
    move the SDK.
- **Re-checked (U31):**
  - "Digest entries already store `stop_reason`" (plan WP-01 step 3) holds
    across the full history (above).
  - "The level-1 put is covered only if the fix sets `error`" holds. The fix
    sets it, and the level-1 store now tests the stop reason too, through the
    shared predicate.
  - The delivery contract holds, and is now pinned for both transports:
    `pipeline._combine` drops errored prose from `combined_text`;
    `export._sheet_document` keeps it under FAILED; the HTML report renders it
    under a *Failed* badge.
- **Next:** WP-04.1 (Wave 1). Newly available: WP-01.3 and WP-01.4 (Wave 1),
  WP-01.5 and WP-06.3 (Wave 2), WP-12.6 (Wave 3). WP-10.4 still waits on
  WP-01.4; WP-01.6, WP-01.7 and WP-13.4 wait on WP-02.3; WP-14.5 waits on
  WP-14.4.

### 2026-09-23 — WP-01.1: verification is COMPLETE only when every eligible item was judged ([PR #155](https://github.com/Abe-Borg/drawing-analyzer/pull/155))

- **Slice and IDs:** WP-01.1. N5. Decides D-2 (stage accounting).
- **What changed:**
  - **One completeness rule.** New `models.item_coverage_status(eligible,
    judged)`:
    - nothing eligible is `SKIPPED_VALID`;
    - everything judged is `COMPLETE`;
    - nothing judged is `FAILED` (the all-failed rule);
    - anything between is `PARTIAL`.

    The verification ladder in `pipeline._run_qc_stages` applies it once, over
    both passes, after the two failure flags. Those are unchanged: a
    single-crop pass that raised is `FAILED`, a cross pass that raised is
    `PARTIAL`.
  - **`VerifyResult`** (`verify.py`):
    - `eligible` is set from each pass's eligibility filter
      (`_is_verifiable`, `_has_anchored_legs`) before any call, and never
      reads below the tally;
    - `judged` is verified + rejected + uncertain − `not_judged`. A valid
      NOT_VISIBLE is a judgment, and so is a cache hit;
    - `coverage_note()` is the stage's leading warning. It counts skips and
      calls that returned no judgment separately, for example
      `verification: 117 of 120 eligible finding(s) judged; 0 skipped, 3
      returned no judgment`, and adds "N not accounted for" if the tally
      falls short of `eligible`;
    - `combined(vres, cres)` sums the two passes; a pass that raised adds
      nothing;
    - `not_judged_ids` records the `qc_id`s of the findings whose call
      returned no judgment. `_count_degrade` records them, so `_degrade_kind`
      stays the only classifier.
  - **A cross worker that raised.** The cross pass's defensive branch left
    the finding UNCERTAIN without counting a failed call, so it read as a
    judgment. It now counts `DEGRADE_FAILED`.
  - **Stage record.** `items_in` is now eligible and `items_out` judged (it
    counted every UNCERTAIN). The warnings are the coverage line, then each
    pass's `degradation_note()`, unchanged. The old "all eligible findings
    were skipped" line is gone; the coverage line covers that case.
  - **Recovery** (plan step 8). Investigation adds `recovered N of M
    finding(s) whose verification call returned no judgment; the
    verification stage keeps its <status> status` to its **own** stage. The
    verification record is never rewritten, and the roll-up does not
    recognise recovery.
  - **Docs.**
    - CHANGELOG: a Fixed entry for N5.
    - CLAUDE.md: the "Run configuration & status" paragraph, the `verify.py`
      paragraph ("observational: no status moves" removed) and the
      investigation paragraph.
    - README: the QC-status overview, and a new block in the verification
      section that replaces the "Observational only" paragraph.
    - The `VerifyResult` docstring, and the header comment of the parse-loss
      tests in `tests/test_drawing_verify.py`.
- **Contracts decided:** D-2, including the all-failed rule and how recovery is
  exposed ([`DECISIONS.md`](DECISIONS.md)). Headings there now match this file
  and plan §4.1 (the session request asked for this):
  - D-1: WP-01.1 → WP-01.2;
  - D-2: WP-01.3 → WP-01.1 (now decided);
  - D-3: WP-03.2 → WP-03.4;
  - D-4: "first decided by WP-01.1, completed by WP-10" → "started by
    WP-01.2, completed by WP-10.4". WP-01.2 is the first slice that changes
    cache admission;
  - D-7: WP-14.1 → WP-14.4.
- **Plan corrected:** WP-01's "Steps 6–7" verification note. Its formula,
  COMPLETE ⇔ eligible > 0 ∧ `skipped` = 0 ∧ `not_judged` = 0, assumes every
  eligible item is tallied, and two paths broke that (the swallowed
  single-crop error and the uncounted cross worker failure). Nothing was
  weakened.
- **Cache/schema effects:** none. No key, prompt or schema changed, and
  verification's cache admission is unchanged. No migration-register row.
- **Re-baselined test:**
  `tests/test_drawing_qc_pipeline.py::test_pipeline_reports_verify_parse_loss_on_the_stage_not_as_an_error`
  pinned `COMPLETE` ("observational: status unmoved") for a pass whose only
  call came back malformed. It now pins `FAILED`, items 1 → 0, a `PARTIAL` run,
  and the coverage line ahead of the unchanged degradation line. That is
  stricter, not weaker, and the test's own point (a warning, never an error)
  is still asserted. No other existing test pinned COMPLETE on a partial
  verification: nothing else in the suite changed.
- **Validation (this container, Python 3.11.15, SDK 1.7.0):**
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **2,619 passed, 2 skipped, 10 deselected** (196 s), identical to the
    WP-23.1 handoff.
  - **Reproduced first.** Driving `extract_drawing_context` on the gauntlet
    mini set with a malformed verdict for its one eligible finding gave
    verification `COMPLETE` and run `COMPLETE`; investigation then recovered
    the finding to VERIFIED.
  - **Failing first.** The 26 new tests against the unfixed code: 24 failed,
    2 passed. The two that passed pin behaviour the fix keeps: an
    all-NOT_VISIBLE pass is `COMPLETE`, and no eligible findings is
    `SKIPPED_VALID`.
  - **After:** full suite **2,645 passed, 2 skipped, 10 deselected** (209 s),
    the baseline plus the 26 new tests, with the same two environment skips
    (IPv6 loopback; chmod as root).
  - **Browser suite** (the report's stage table renders the new values):
    98 collected, 98 executed and passed; `check_browser_suite.py` passes.
    It ran twice. The first run overlapped a sub-second `git stash` taken for
    a lint comparison, so the clean foreground re-run is the evidence. Both
    passed.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` is clean.
    F401/F811/F841 over the touched files shows five hits, the same five as on
    the base (WP-22.5 territory); none is new. `scan_secrets.py` is clean over
    192 tracked files. `compileall src` passes.
- **Not verified:**
  - **Live API behaviour.** There is no live budget (O-4). Truncated, declined
    and failed verdicts are the hermetic fakes the existing parse-loss tests
    already use.
  - **Windows.** Covered by this PR's CI.
- **Risks and residual gaps:**
  - **A visible behaviour change.** A run with an unjudged verification item
    used to read `COMPLETE` and now reads `PARTIAL`. A verification that
    judged nothing now reads `FAILED`; it read `PARTIAL` when every finding
    was skipped, and `COMPLETE` when every call failed. The A/B sweep will
    qualify such an arm as PARTIAL.
  - **A finding that escapes the single-crop tally** (an error after the loop
    picks it up, which the pass swallows under I-3) keeps its prior verdict,
    so the report shows it *Not checked*. The stage now counts it "not
    accounted for" and stays off `COMPLETE`. Giving it a SKIPPED verdict
    would change the loop's end sweep and its note, so it was left out to keep
    the slice narrow. Recorded on the slice row.
  - **An auth-fatal call counts as skipped.** The fatal path returns SKIPPED,
    not a degrade kind, so a call that was made and refused lands in
    `skipped`. Both buckets are unjudged, so the status is right; only the
    bucket is arguable. WP-01.2's terminal-outcome helper is the place to
    revisit it.
  - **Recovery matches on `qc_id`,** which `ledger.number()` assigns before
    verification. A direct caller of `verify_findings` on unnumbered findings
    records no ids, and has no investigation stage to report to.
  - **The roll-up does not recognise recovery.** D-2 says how to add that if
    the product ever wants it.
- **Re-checked (U31):**
  - "A cache hit is always a judgment" holds: `_cache_verification` stores
    only verdicts the call marked `cacheable`, and
    `_verification_from_cache_payload` admits only `valid_model_verdict:
    True`. Pinned by `test_a_valid_not_visible_and_a_cache_hit_are_both_judgments`.
  - "`skipped` counts only eligible-but-unjudged items" holds: the
    `_is_verifiable` exclusions are never counted. Pinned by
    `test_eligible_is_fixed_by_the_eligibility_filter`.
  - The verify loop's "the tally always accounts for every item" is false for
    an item that raises after being picked up (the residual above).
  - "Failure flags before counts" is kept, and
    `test_a_cross_verifier_crash_is_not_a_valid_skip` is unchanged.
- **Next:** WP-01.2 (decides D-1, starts D-4). WP-10.3 (Wave 2) and WP-22.4
  (Wave 4) waited only on WP-01.1 and are now available in their waves.
  WP-21.4 still waits on WP-05.1 and WP-05.2.

### 2026-09-23 — WP-23.1: minimal stable-release publish gate ([PR #154](https://github.com/Abe-Borg/drawing-analyzer/pull/154))

- **Slice and IDs:** WP-23.1. N8, its enforcement part. The owner actions stay
  open: the published v1.7.0 is O-1, and the admin half, protecting the
  `release` environment, is O-5. The rest of WP-23 steps 9–12 is the new slice
  WP-23.6 (Wave 5).
- **What changed:**
  - **The gate.** New `scripts/check_release_acceptance.py` (stdlib only, the
    `check_browser_suite.py` pattern) decides, once, what a tag may publish:
    - `vX.Y.ZrcN` is `prerelease` and needs no record.
    - `vX.Y.Z` is `stable` only when `docs/releases/ACCEPTANCE-X.Y.Z.md`
      meets all of these:
      - it is titled for that version;
      - its Sign-off has exactly one `Release decision:` line whose first
        word is `SHIP` and which does not also say `HOLD`;
      - every waiver row is complete (item, scope, justification, owner
        approval, `Expiry` as `YYYY-MM-DD`) and unexpired. A waiver is valid
        through its UTC expiry day.
    - Anything else refuses, as does anything unreadable. A tag outside the
      updater's `_VERSION_RE` grammar publishes nothing; a test pins the
      script's copy of the grammar equal to the updater's.
    - On success it appends `channel=` and `valid_through=` (the earliest
      waiver expiry) to `$GITHUB_OUTPUT`. On a refusal it writes nothing,
      exits 1 and names the RC route.
  - **The `acceptance` job.** New in `release.yml`: tag-only and read-only
    (checkout without credentials, setup-python, the script). It runs on every
    tag, RC included. A skipped job in `needs` skips `publish`, so the RC bypass
    lives in the script, not in an `if:`.
  - **`publish`.** It now needs `[build, gates, gates-windows, acceptance]` and
    deploys to `environment: release`. It takes the channel from
    `needs.acceptance.outputs.channel`; the `*rc*` glob is gone, and an unknown
    channel exits 1 before `gh release create`. It still runs no repo code.
  - **Draft first, publish last** (review follow-up, Codex P2 on the PR).
    - **The defect.** `publish` checked `valid_through` against `date -u` and
      then ran `gh release create`, which uploads the assets and publishes at
      the end. The whole upload therefore sat between check and use: a
      waiver lapsing at midnight UTC mid-upload still published.
    - **The fix.** The assets now upload into a `--draft` (no channel flag),
      and one final `gh release edit --draft=false <channel flag>` makes the
      release public. The expiry is checked before the upload and again
      after it.
    - **Re-runs.** A re-run finds the earlier attempt via
      `gh release view --json isDraft`. It finishes a draft. A published
      release only has its assets replaced (the old `--clobber` path) and
      keeps its flags, so re-running an old tag cannot take `latest` back
      from a newer release.
    - **Residual gap.** One API call now separates the final check from
      publication, instead of a whole upload.
  - **Docs.**
    - CHANGELOG: a Fixed entry for N8.
    - CLAUDE.md: the "CI gates" paragraph and a Commands line.
    - README: the CI section, including a corrected "two tag-gated jobs", and a
      publish-gate bullet under "Acceptance & release gate".
    - `docs/RELEASE_WINDOWS.md`: a new step 3, the approval in step 5, a new
      section "The publish boundary", the diagram and the pieces table.
    - `docs/RELEASE_ACCEPTANCE_TEMPLATE.md`: what the gate reads (the title,
      the Sign-off decision, the waiver-table format), and that it does not
      read §0.
    - A `ci.yml` comment.

    **No acceptance record was edited.**
- **Plan corrected** (WP-23 verification notes; the slices line now reads
  23.1 … 23.6):
  - "Reads SHIP or lists unexpired waivers" is ambiguous. Read as a plain OR,
    one waiver would publish a HOLD record. That contradicts WP-23's
    acceptance criterion and the records' own policy ("… and the Release
    decision line in the sign-off reads SHIP").
  - The gate therefore requires SHIP **and** complete, unexpired waivers. That
    is stricter than either reading, never weaker. The user's wording ("must
    fail unless SHIP or unexpired waivers") states a necessary condition, and
    the stricter gate satisfies it.
  - What 23.1 leaves of steps 9–12 is listed there and added as WP-23.6.
- **Contracts decided:** none of D-1 … D-8 (release tooling only).
- **Cache/schema effects:** none. `src/` is untouched: no key, prompt or schema
  changed, and there is no migration-register row.
- **Validation (this container, Python 3.11.15, SDK 1.7.0):**
  - **Baseline before the change:** `python -m pytest -q -m "not network"` gave
    **2,501 passed, 2 skipped, 10 deselected** (186 s), identical to the
    WP-02.1 handoff.
  - **Failing first.** The new file plus the re-baselined
    `tests/test_browser_suite_gate.py` gave 9 failed, 96 errors, 17 passed.
    - The errors are every script test: the script did not exist yet.
    - Three new-file tests passed. They pin properties the old workflow
      already had and the fix had to keep: `publish` runs no repo code, its
      `if:` carries no status function, and the committed records exist.
    - The re-baselined `needs:` assertion failed on the old string.
    - **The review follow-up, also failing first.** The two new text tests
      failed against the first push's workflow, and so did six of the ten
      cases that run the real `publish` script under a fake `gh` and a fake
      clock. That includes Codex's case: valid at the start, midnight passing
      mid-upload, and the old step exited 0 after a direct
      `release create … --latest`. The four refusal cases passed on both and
      pin behaviour the fix keeps.
  - **After:**
    - `tests/test_release_acceptance_gate.py`: 118 passed. The simulation
      skips on Windows, since `publish` runs on ubuntu-latest.
    - Full suite: **2,619 passed, 2 skipped, 10 deselected** (182 s). That is
      the baseline plus the 118 new tests, with the same two environment
      skips (IPv6 loopback; chmod as root). The first push measured 2,608
      with 107.
    - Browser suite, run because the slice edits that gate's test file: 98
      collected, 98 executed and passed. `check_browser_suite.py` passes.
    - `ruff check --select E9,F63,F7,F82 src tests scripts` is clean
      (F401/F811/F841 too, on the two new files). `scan_secrets.py` is clean
      over 192 tracked files, the new ones included. `compileall src scripts`
      passes.
  - **The workflow, exercised locally:**
    - PyYAML, present in this container but not a dependency, parses the
      jobs, `needs`, `environment` and outputs as intended.
    - The `publish` step's bash, extracted and run under a stub `gh`, over
      eight cases:
      - `stable` publishes with `--latest`, `prerelease` with `--prerelease`;
      - an empty channel, `Stable`, a lapsed `valid_through` and a malformed
        one each exit 1, and `gh` is never called;
      - an expiry of today or tomorrow publishes.

      That scratch check is now a test,
      `test_the_publish_step_publishes_only_what_it_should`. Its text
      extraction of the step equals PyYAML's parse byte for byte, so it runs
      the real script. The real `gh` was not run: its draft-by-tag handling
      (`gh release edit <tag> --draft=false` is gh's own documented way to
      publish a draft) is taken from gh's documentation, because this
      container's egress policy blocks gh's source.
  - **Dry run against the real records.** `v1.7.0` is refused (HOLD). `v1.6.0`
    is refused (`SHIPPED` is not SHIP). `v1.7.0rc1` is a prerelease. `v1.8.0`
    is refused (no record). The gate would have stopped both stable tags that
    shipped ahead of their acceptance.
- **Not verified:**
  - **A real tag run.** Nothing was tagged, by protocol. This PR's own
    `release.yml` run executes only `build`; `gates`, `acceptance` and
    `publish` are tag-only and skip.
  - **The environment's protection** (O-5). The `release` environment does not
    exist until a tag run creates it, and this session made no admin or API
    call to inspect or configure it.
  - **Windows.** The new tests run on this PR's Windows CI leg.
- **Risks and residual gaps:**
  - **The YAML stops accidents only.** A tag runs the workflow from the tagged
    commit. So a commit that edits `release.yml` bypasses the gate, and so
    does a tag at a commit older than this PR, whose workflow predates both
    the gate and the `environment:` line. Only O-5 closes that: environment
    reviewers with a `v*` tag policy, plus a tag ruleset restricting who may
    create, move or delete `v*` tags.
  - **Unprotected until O-5.** An unconfigured `environment: release` is
    auto-created without protection on the first tag run. Until O-5, the
    first stable tag after this merges is gated by its record alone.
  - **The environment covers RC tags too.** Once O-5 adds reviewers, RC
    publishes also wait for approval. They still publish as pre-releases, as
    the session request requires.
  - **The gate trusts the SHIP line.** It does not check that §§2–6 items are
    ticked or covered, and it does not bind the record to the tested commit
    or to the artifacts (WP-23.6). The environment reviewer is the human
    check.
  - **Record structure is now CI-checked.**
    `test_every_committed_record_is_readable_by_the_gate` parses every
    `docs/releases/ACCEPTANCE-*.md`, structure only; no decision is pinned.
    An owner edit that leaves a record unreadable, for example while
    correcting the 1.7.0 record (O-1), fails CI and names the reason. That is
    deliberate: a malformed record surfaces at PR time, not at tag time. The
    incident regressions use verbatim copies of the 1.6.0 and 1.7.0 sign-offs,
    so correcting those files cannot retire them.
  - **A partial publish leaves a draft.** If the job fails after the upload
    (the waiver lapsed, or an API error), an unpublished draft remains.
    Neither the public nor the updater can see it, and a re-run finishes it.
    A draft for a tag that will never ship is the owner's to delete.
  - **Size.** The PR is well past the **S** estimate: about 1,980 added lines
    against `main`. That is the test file (870, much of it parametrised cases
    and verbatim record fixtures), the script (536, much of it docstring and
    messages), the workflow (140), and docs and this tracker (about 430).
- **Re-checked (U31):**
  - The `release.yml` header's claim that `publish` "runs NO repo code" still
    holds, and is now pinned (`test_publish_runs_no_repo_code`).
  - The old `*rc*` glob and the updater's grammar agree on every tag this
    repository has published: `v1.0.0rc1` and `v1.3.0rc1` are pre-releases,
    the rest stable (checked against the release list).
- **Next:** Wave 1 in order, starting with WP-01.1. Before the next stable tag,
  the owner should do O-5: configure and confirm the `release` environment and a
  `v*` tag ruleset. O-1 is still open. WP-23.6 (Wave 5) holds the rest of
  WP-23 steps 9–12.

### 2026-09-23 — WP-02.1: hermetic network and credential guard ([PR #153](https://github.com/Abe-Borg/drawing-analyzer/pull/153))

- **Slice and IDs:** WP-02.1. U26, its socket-guard, credential and `network`
  opt-in part. The rest of U26 (strict fakes, fidelity fixtures, batch canary)
  stays with WP-02.2 … WP-02.4.
- **What changed:**
  - New pytest plugin `tests/fixtures/hermetic_guard.py`, registered by
    `tests/conftest.py` through `pytest_plugins`. It replaces the conftest's
    placeholder `pytest_configure`, its key-based skip rule and the
    function-scoped `_enforce_hermetic_api_key` fixture.
  - **Sockets.** `connect`/`connect_ex` and `getaddrinfo`/`gethostbyname`/`_ex`
    refuse every non-local destination. Loopback, the unspecified addresses,
    `localhost` and `AF_UNIX` pass; other socket families are refused. Sockets
    are guarded at connect, not creation, so asyncio and Playwright keep working.
  - **Recording.** A refusal raises `ExternalNetworkBlocked` (a `RuntimeError`)
    and is recorded. A recorded attempt turns that test's teardown into an error
    naming the destination and the test, even when the code swallowed the
    exception (the I-3 shape). An attempt outside any test fails the session.
  - **Environment.** Every `*_proxy` variable is removed and `NO_PROXY=*` set;
    every `ANTHROPIC_*` variable is removed; `ANTHROPIC_CONFIG_DIR` points at an
    empty temp dir; the placeholder key is set for collection (now even over an
    exported real key); no key inside hermetic tests.
  - **Scope.** Installed at configure time; lifted only inside an opted-in
    `network` test's runtest protocol, which gets the caller's environment and
    real sockets back. So module- and session-scoped fixtures are covered. The
    gauntlet's `oracle` fixture was outside the old per-test key strip.
  - **No fixture crosses the boundary** (review follow-up, Codex P2 on the PR).
    pytest caches a higher-scoped fixture for every later test. In a session
    mixing both sides, a credential-bearing object made in an opted-in test
    reached hermetic tests, and its finalizer (a canary's remote cleanup) ran
    under the guard and was refused. The guard now tears the whole fixture stack
    down between neighbours on different sides (`pytest_runtest_teardown`,
    `teardown_exact(None)`). Regression:
    `test_a_fixture_never_crosses_the_network_boundary`. Before the fix it
    failed 2 of 4 inner tests: the hermetic test received the network test's
    copy.
  - **Opt-in.** `network_selected_explicitly`: the `-m` expression must select
    the test *because of* its `network` marker (pytest's own expression engine),
    and a real key must be set.
  - **CI.** `-m "not network"` on all three `ci.yml` pytest commands (the
    browser job now selects `browser and not network`, the same 98 tests). A new
    test fails if any workflow pytest command drops it.
  - **Docs.** CLAUDE.md (commands, a guard paragraph, I-4), the README testing
    section, CHANGELOG, `_plans/README.md` step 2. Stale comments corrected in
    `scripts/run_acceptance.py`, `tests/test_run_acceptance.py` and
    `tests/test_live_api_canary.py`; the `network` marker description in
    `pyproject.toml`.
- **Plan corrected:** WP-02 step 6 verification notes. The credential list was
  incomplete for SDK 1.7.0 (`ANTHROPIC_CUSTOM_HEADERS` can carry an auth
  header; also `SERVICE_ACCOUNT_ID`, `WORKSPACE_ID`, `SCOPE`). Also added: the
  Windows/macOS proxy fallback that only `NO_PROXY=*` closes, the fail-closed
  effect of `ANTHROPIC_CONFIG_DIR`, and the module-scoped fixture gap. Nothing
  was weakened.
- **Contracts decided:** none (test harness only; D-1 … D-8 untouched).
- **Cache/schema effects:** none. No product code changed; no key, prompt or
  schema touched; no migration-register row.
- **Validation (this container, Python 3.11.15, SDK 1.7.0):**
  - Baseline before the change: `python -m pytest -q -m "not network"` gives
    **2,450 passed, 1 skipped, 10 deselected** (234 s). The pass count matches
    the recorded baseline. Its "11 skipped" counted the 10 canaries as skips,
    which is what a bare `pytest` reports; under `-m "not network"` they are
    deselected. A recording difference, not a regression.
  - After, with the review follow-up: **2,501 passed, 2 skipped, 10
    deselected** (239 s), which is the baseline plus the 51 new tests. The new
    skip is the IPv6-loopback test: this container has no IPv6
    (`EAFNOSUPPORT`). **No existing test tripped the guard.**
  - The first 50 new tests before the fix: 47 failed, 3 passed (the 51st, the
    fixture-boundary test, came with the review follow-up and failed before
    it). The three that passed
    are the two `-m network` subprocess sessions, whose behaviour did not
    change, and the pure workflow-scanner check. Against the old conftest, the
    default-run subprocess session showed each defect:
    - the exported key visible at collection;
    - proxies and `ANTHROPIC_*` credentials surviving;
    - a zero-arg client resolving them;
    - the network test **running** with only a key exported;
    - both swallowed attempts passing silently.
  - The import-time-attempt test exited 0 against the old conftest.
  - Reproduced separately before the fix: the SDK sent
    `CONNECT api.anthropic.com:443` to an exported loopback `HTTPS_PROXY`. Its
    regression now asserts zero connections reach the proxy.
  - Browser suite (`-m "browser and not network"`): 98 collected, 98 executed
    and passed; `scripts/check_browser_suite.py` passes.
  - `ruff check --select E9,F63,F7,F82 src tests scripts`: clean.
    `scripts/scan_secrets.py`: clean (190 tracked files, the new ones
    included). `compileall`: OK.
  - With a fake key exported, `pytest tests/test_live_api_canary.py` (no `-m`)
    reports 10 skipped with the opt-in reason.
- **Egress disclosure:** the failing-first runs made one TCP connect attempt to
  `192.0.2.1:443` (RFC 5737 TEST-NET-1) and DNS lookups of two `.invalid` names
  (RFC 6761). These are reserved destinations, never services. No API request
  was made and no key was used.
- **Not verified:**
  - IPv6 loopback (skipped here; it runs where the CI runner has `::1`).
  - The Windows legs: they run in this PR's CI.
  - macOS: not in CI. The `NO_PROXY=*` reasoning for its system proxy comes
    from the stdlib source, not from a run.
  - A real opt-in with a real key: no live budget (O-4). It is proven in a
    subprocess with a fake key, and nothing is sent.
- **Risks and residual gaps:**
  - The opt-in rule uses pytest's private `_pytest.mark.expression` engine. If
    an upgrade moves it, the rule fails closed (the canary is skipped) and
    `test_network_needs_an_explicit_marker_selection` fails. The boundary
    teardown uses the private `session._setupstate`; if that moves, mixed
    sessions error at teardown and
    `test_a_fixture_never_crosses_the_network_boundary` fails.
  - Deliberately uncovered, documented in the plugin:
    - child processes get the scrubbed environment but not the socket patch;
    - UDP `sendto`;
    - asyncio's Windows proactor connecting a literal IP;
    - the OS keyring: the key-store tests stub it, and the socket guard is the
      backstop.
  - Behaviour changes a later test author will meet:
    - a zero-arg `Anthropic()` in a hermetic test raises `CredentialsError` at
      construction;
    - a module- or session-scoped fixture now sees no key at all.
  - Size: larger than the **S** estimate in tests (~650 lines, mostly the
    subprocess sessions). The plugin is ~400 lines including its docstrings.
- **Re-checked (U31):** the README's "the suite is hermetic — no API key, no
  network" holds in practice: nothing in the full run reached for the network.
  `run_acceptance.py` still deselects `network` in every child.
- **Next:** WP-23.1 (Wave 0), then Wave 1 in order. WP-02.2 is now unblocked (it
  sits in Wave 2). For WP-02.2: `httpx2.MockTransport` never opens a socket, so
  real-SDK contract tests run under the guard unchanged. Construct the client
  with an explicit `api_key=`, since a zero-arg one now fails closed.

### 2026-09-22 — plan review and program setup ([PR #152](https://github.com/Abe-Borg/drawing-analyzer/pull/152))

- **Slices:** none (setup session). No product code changed.
- **What changed:**
  - Re-verified the plan against the code with eight parallel verification agents.
  - Corrected the plan (§1.2, §1.3, §3, §4, every work package's *Verification
    notes*, §6.4, §7, §10).
  - Added this tracker, `README.md` (the session protocol), `DECISIONS.md`, the
    frozen original review, and the evidence snapshot `verification-2026-09-22/`.
  - Added a pointer section to `CLAUDE.md`.
- **Findings:**
  - All plan and review items are still present on 1.7.0; none was fixed.
  - Five descriptions corrected (N9, A6, R3, B7, H2); 18 new defects (N10–N27).
  - v1.7.0 was published as the stable release despite the HOLD (O-1).
- **Validation:** the baseline above (2,450 passed, 11 skipped; browser 98/98). CI
  green on the PR.
- **Not verified:** live API behavior. Nothing was sent to the API. One verifier
  probe may have sent a single unauthenticated GET to a dummy `github.com/x/y` URL
  through the proxy while testing update redirects.
- **Next:** WP-02.1, then WP-23.1, then Wave 1 in order. The owner should look at
  O-1 and O-2 first.
