# Remediation progress tracker

**Next up:** `WP-23.1`, then Wave 1 in order (`WP-02.2` is unblocked by WP-02.1 but sits in Wave 2). First check the open PRs ([`README.md`](README.md), step 1).
**Last updated:** 2026-09-23 by the WP-02.1 session ([PR #153](https://github.com/Abe-Borg/drawing-analyzer/pull/153)).

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
| WP-23 | Reproducible packaging and enforceable release acceptance | P1 | 23.1–23.5 | todo |
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
| WP-23.1 | A stable `publish` fails unless `docs/releases/ACCEPTANCE-<ver>.md` reads SHIP or lists unexpired waivers; `environment:` on `publish`; RC tags unaffected (N8) | S | — | todo | Admin half is O-5 |

### Wave 1 — P0 correctness (independent slices first)

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-01.1 | Verification is `COMPLETE` only when every eligible item was judged; failures and skips are counted separately; decides D-2 (N5) | M | — | todo | |
| WP-01.2 | Shared terminal-outcome helper; the digest (real-time and batch) never admits a refusal, truncation or `stop_reason=None` read as success or into either cache level; cached refusals are rejected when read; decides D-1 (N4 digest, N27) | M/L | — | todo | |
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
| WP-01.3 | Digest partial reads: a raised-cap retry never loses the first read; findings from an errored, refused or truncated digest are labelled or held out of the ledger (N15, N16) | M | WP-01.2 | todo | |
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
| WP-01.5 | Batch refusal recovery under the selected transport policy, retry bound shared with truncation retries, `stop_details` logged (R2) | M | WP-01.2 | todo | |
| WP-01.6 | Remaining response consumers (planner, identity, synthesis, focus, prose harvest cache writes); fallback-aware shared text join (U2; WP-09 step 6) | M | WP-01.2, WP-02.3 | todo | |
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
| N4 | Refused/truncated digests and critiques accepted and cached | P0 | 01.2, 01.4, 10.4 | open | |
| N5 | Verification COMPLETE with no judgments or with skipped items | P0 | 01.1 | open | |
| N6 | Duplicate sheet labels bind first-wins (whole-set, dedup, arithmetic, legs) | P1 | 06.2 | open | |
| N7 | Calculator accepts malformed numbers; inexact large integers | P1 | 20.1 | open | |
| N8 | Stable publish ignores the acceptance hold (it happened for 1.7.0) | P1 | 23.1, O-1, O-5 | open | |
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
| N27 | A stream that ends without `message_stop` is cached as a complete digest | P0 | 01.2 | open | |
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
