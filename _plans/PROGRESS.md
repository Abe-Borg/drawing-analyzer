# Remediation progress tracker

**Next up:** Wave 1 in order: `WP-07.2` (A8), which depends only on WP-07.1. WP-07.1 is done: an arithmetic mismatch is trusted (DETERMINISTIC) only when its claim resolved to a sheet, its quote anchored there EXACT or by a numerically vetoed FUZZY match, and the terms and the stated value each have their own printed number where both the quote and the sheet's words print it (N3; the three rule choices were the owner's). WP-07 is not done: WP-07.2 (strict tokens, relationships) and WP-07.3 (counters, N18) remain. WP-03 is not done: WP-03.4, WP-03.5 and WP-03.6 remain (Wave 2). WP-04 is not done: its acceptance needs quantity roles, slice `WP-04.3` (Wave 2). First check the open PRs ([`README.md`](README.md), step 1). Before the next stable tag, the owner should look at O-5.
**Last updated:** 2026-09-23 by the WP-07.1 session (PR to follow).

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
| WP-03 | Durable finding identity and lossless, symmetric merging | P0 | 03.1–03.7 | todo |
| WP-04 | Engineering quantity and tag comparison | P0 | 04.1–04.3 | todo |
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
| WP-01.2 | Shared terminal-outcome helper; the digest (real-time and batch) never admits a refusal, truncation or `stop_reason=None` read as success or into either cache level; cached refusals are rejected when read; decides D-1 (N4 digest, N27) | M/L | — | done | [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156), 2026-09-23. One classifier, `core.terminal_outcome.classify_stop_reason` (D-1), its vocabulary pinned by test to the SDK's `StopReason` ∪ `BetaStopReason`. Both transports share one ladder (`digest.digest_terminal_error`), one write predicate (`digest.digest_cache_admits`, both levels) and one loader (`digest.sheet_digest_from_cache_entry`, all three cache hits), which serves only a stored finished stop reason; a stored `null` and a missing key are misses (D-4 started, one migration-register row, no schema or key change). Tests: `tests/test_digest_terminal_outcome.py`, `tests/test_terminal_outcome.py`, `tests/test_drawing_acceptance.py::test_a_refused_or_unfinished_digest_holds_the_run_below_complete`. Residual: N15, an errored digest's findings still reach the ledger (WP-01.3) |
| WP-04.1 | Quantity tokenizer: hyphenated units, thousands groups, opaque malformed tokens, `deg`/`°` (angle vs temperature), lists and ranges, W×H and V/A with a negative corpus; critique-scoped cache term (B2, B3, B12, N19) | M | — | done | [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157), 2026-09-23. `critique._quantity_tokens`, a scanner that reads each quantity whole. A composite (list, range, W×H size, voltage pair) is ONE token, compared whole; the representation is documented at the tokenizer and pinned by `tests/test_quantity_signature.py`. Compact `A` needs electrical context (negative corpus in the same file). Critique cache term `digest_cache._CRITIQUE_CACHE_CONTRACT = 1` inside both critique builders; A/B `RECORD_CONTRACT_VERSION` 2 → 3. Tests: `tests/test_quantity_signature.py`, the WP-04.1 section of `tests/test_drawing_cache_identity.py`, four tests in `tests/test_ab_findings_diff.py`. Residual partial signatures (loose-comma lists, `to` ranges, `and`/`or` lists, a bare `20A`) are listed in the handoff |
| WP-04.2 | Compatibility rule over per-unit value sets and partial tag overlap; one shared `signature_conflicts` that the A/B harness also uses (N1) | M | WP-04.1 | done | [PR #158](https://github.com/Abe-Borg/drawing-analyzer/pull/158), 2026-09-23. `critique.signature_conflicts` (axes `tags`, `measurements`, `absence_polarity`, `cross_sheet_legs`); `signatures_compatible` is its negation, and the A/B harness reports its axes (its restated copy is gone). Quantities compare per kind (a unit, or one of the `_QUANTITY_KIND` groups: lengths, degrees, `psi`/`psig`, volts, liquid flow, real power, apparent power): for every kind both carry, one side's tokens must include the other's; no value is converted. Tags compare by inclusion, not by prefix. Sharing no quantity at all still conflicts. Critique contract 1 → 2, fingerprint pinned under 2; `RECORD_CONTRACT_VERSION` stays 3 (rule-only change; plan step 6 corrected). Tests: `tests/test_signature_compatibility.py`, the N1 rows and the corroboration, retention and recorded-limit tables in `tests/test_quantity_signature.py`, the WP-04.2 sections of `tests/test_ab_findings_diff.py` and `tests/test_drawing_cache_identity.py`. Roles are not compared: WP-04.3 |
| WP-03.1 | Symmetric complete-link in Pass B, order-independent entry count (B1, count part) | S | — | done | [PR #159](https://github.com/Abe-Borg/drawing-analyzer/pull/159), 2026-09-23. `ledger.reconcile_post_anchor` folds an entry only when every member of its `Ledger.member_history` is `_is_duplicate` of every member of the survivor's (both sides, each as it arrived). The B1 case ends with two entries in all six orders, under seven severity and quote-length variants; histories stay cliques; a second pass folds nothing. The candidate index cannot miss a fold (argued at `_candidates`, pinned against an index-free reference). Geometry: recorded as a recall loss, not lent (Pass B now folds only entries that absorbed nothing in Pass A). Tests: `tests/test_pass_b_complete_link.py`, `tests/test_drawing_dedup_lifecycle.py::test_pass_b_keeps_a_conflict_the_incoming_entry_absorbed`. No cache or key change. Found N28 (WP-03.7) |
| WP-03.2 | Deterministic total-order tie-break in `assign_qc_ids` (K5) | S | — | done | [PR #160](https://github.com/Abe-Borg/drawing-analyzer/pull/160), 2026-09-23. `models.assign_qc_ids` keeps the positional order and breaks a tie by the content `id` (first, so a pair whose ids differ keeps its number), then the text, then `_qc_content_key`: every field but `qc_id`, with `_ARRIVAL_ORDERED_FIELDS` (`sources`, `refs`, `supporting_quotes`, `prose_item_ids`, `citations`) sorted, built only for runs the cheap key leaves tied. No existing fixture renumbered (checked by instrumenting the full suite). `qc_id` is in no cache key. Tests: `tests/test_qc_numbering_tiebreak.py`. Found N29 (WP-03.5). Still following arrival, recorded on WP-03.4: the row order of `findings.json`/`findings.csv` and of the report table among equal severity and status |
| WP-03.3 | Remove the auditor coordinator's id dedup; arithmetic claim discriminator so the ledger keeps two different same-row mismatches; Decimal claim-dedup keys (B7) | S/M | — | done | [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161), 2026-09-23. `run_auditors` dedups nothing (the ledger decides); `audit_titleblock` keys its two-path dedup on (sheet, quote). `Finding.claim_discriminator` (additive, serialized only when set), set by the arithmetic auditor from `arithmetic.claim_content_key` (host operation, terms as a multiset of exact decimals, stated value; scheme `arithmetic/1`). `critique._claims_differ` refuses a merge when both findings carry one and they disagree, before every accepting branch of `_is_duplicate` (so Pass A and Pass B); it is folded into `id` (`compute_finding_id`'s last argument, only when non-empty) and rides the representative's bundle. All three claim dedups (arithmetic, critique, cross-QC) share `claim_content_key`. Merge-rule fingerprint unchanged; one migration-register row re-keys arithmetic investigations. Tests: `tests/test_arithmetic_claim_discriminator.py` |
| WP-03.7 | The geometry branch folds two different issues that quote one tag (N28): decide what, besides a shared quote and an overlapping rectangle, may fold two findings, and apply it in both passes | S/M | WP-03.3 | done | [PR #162](https://github.com/Abe-Borg/drawing-analyzer/pull/162), 2026-09-23. **Decided by the owner (option a):** the geometry branch of `critique._is_duplicate` is removed, in both passes; the predicate reads no rectangle (D-3 input in `DECISIONS.md`). A rectangle is resolved from the finding's own quote, so "equal quote + overlapping rect" was the quote-alone merge. Measured before deciding (instrumented full suite): the branch decided 10 folds, all in 6 synthetic tests (gauntlet and pipeline fixtures: none); a claim discriminator for model findings could not separate the pair host-side (both sign as `{tags: [P1]}`) and a model-emitted one re-bills every digest and critique; a shared-word rule was a threshold at one word. Pass B now folds nothing Pass A refused (zero folds over the suite). The `CO-1` same-spot paraphrase stays two findings (the decided cost; retention pinned). Merge-rule ratchet unchanged (`63dbfe17…`, critique contract 2); no cache or key change. Tests: `tests/test_position_is_not_sameness.py` (incl. the pipeline-level pair); flipped: the N28 recorded limit, the `CO-1` fold, the Pass B omit fold; the K5 lifecycle now asserts its numbers |
| WP-07.1 | Occurrence-aware, sheet-grounded operand support; provenance decided after anchoring; a fabricated quote or unresolved sheet is never DETERMINISTIC (N3) | M | — | done | PR to follow, 2026-09-23. **Rule decided with the owner (three choices, measured first):** a mismatch is TEXT_EXTRACTED / DETERMINISTIC only when the claim resolved to a sheet, its quote anchored there EXACT or FUZZY by a numerically vetoed method (`anchor.numbers_grounded`, fail-closed on method; never TILE or UNANCHORED), and the terms and the stated value together fit, one occurrence each, the numbers that both the quote and the sheet's words under the matched span print (`arithmetic._operands_grounded`, per value the smaller count; `anchor.resolve_anchors(matched_text=)`). Every mismatch is built MODEL_TRANSCRIBED and promoted after the auditor's own anchoring pass; a failure while deciding, or anchoring one sheet, leaves it UNCERTAIN. Ids, text, severity and the verification note's wording are unchanged; no cache or key effect. Tests: `tests/test_arithmetic_operand_grounding.py`; the three pinned `audit_arithmetic(..., [])` tests re-baselined with sheet words |
| WP-07.2 | Strict numeric tokens (tag and sheet-id digits, hyphen-as-minus, `1e3`) and host-side relationship checks (A8) | M | WP-07.1 | todo | From WP-07.1: operands are counted by `arithmetic._operands_grounded` over `_numbers_in_text` of BOTH the quote and the sheet's matched words (`anchor.resolve_anchors(matched_text=)`), so a stricter scanner applies to both sides at once; keep the scanner/parser agreement test. A grounded claim can still name the wrong operation: `20 × 2 = 40` transcribed as `sum [20, 2] = 40` prints every operand once, so it is a DETERMINISTIC "the sum of 20, 2 is 22" mismatch on a correct product. That, and swapped roles, is this slice's relationship check. Relationship checks stay host-side (plan WP-07 step 4) |
| WP-05.1 | Cross-QC grounding: a real match for every non-empty quote at word boundaries; no text means unavailable evidence; one normalizer shared with `anchor`; `_CROSS_QC_CACHE_CONTRACT` 3→4 (B5, N12 cross-QC part, N13) | M | — | todo | |
| WP-05.2 | Anchor punctuation folding and a source-word-boundary rule (B4: `PSI,`, `NOTE 3:`, `(568 L/MIN)`; N12 anchor part: `VAV-2` in `VAV-2-1`) | M | — | todo | |
| WP-06.1 | Cross-QC prompt says category `question` with severity `low`; invalid-field counters on both paths; candidate duplicates go to the ledger instead of being destroyed (B6, N2) | S/M | — | todo | |
| WP-09.1 | Boilerplate filter with repeatable qualifiers; negation-aware synthesis conflict extraction (B11, N11) | S | — | todo | |
| WP-09.2 | Prose matching rejects signature-incompatible candidates; per-item outcome counters; labelled paraphrase corpus (no threshold change) (N10, U11) | M | WP-04.2, WP-09.1 | todo | |
| WP-01.3 | Digest partial reads: a raised-cap retry never loses the first read; findings from an errored, refused or truncated digest are labelled or held out of the ledger (N15, N16) | M | WP-01.2 | todo | Since WP-01.2 a refused or unfinished digest carries an error too, so N15 now also covers, for example, an N27 partial read whose unclosed findings block was salvaged: its findings still reach the ledger unlabelled. `digest.digest_terminal_error` is the ladder to extend, not restate |
| WP-01.4 | Critique: `max_tokens`/refusal/unknown terminal states are not completed reads on either transport; critique-only cache contract term (N4 critique) | M | WP-01.2 | todo | The critique-only term exists since WP-04.1 (`digest_cache._CRITIQUE_CACHE_CONTRACT`, folded inside both critique builders). Bump it for this admission change rather than adding a second term (D-4), and pin the merge-rule fingerprint under the new value in `tests/test_drawing_cache_identity.py` |
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
| WP-04.3 | Quantity roles for repeated same-kind values: the WP-04 matrix row "repeated values in different roles" (swapped: `6 in main, 4 in branch` / `4 in main, 6 in branch`; one value in two roles: `6 in supply, 6 in return` / `6 in supply, 8 in return`) | M | WP-04.2 | todo | Added by WP-04.2 (README 7.3): WP-04's acceptance does not hold without it. Nothing extracts a quantity's role, and the signature is a set, so both pairs carry compatible tokens and the same words. Do not settle it by keeping apart every pair that carries two or more values of one kind on both sides: that splits the commonest duplicate there is, the same "500 gpm shown, 550 gpm required" from both critique reads. It needs a role signal (for example the noun a quantity qualifies) with a negative corpus. Both pairs are pinned as recorded limits in `tests/test_quantity_signature.py::_RECORDED_LIMITS`; move them to `_CONFLICTS`. A role in the stored signature changes what an A/B record stores (`RECORD_CONTRACT_VERSION` 3 → 4) and what a critique entry holds (critique contract 2 → 3). Related, and under the same bump: `critique._TAG_RE` reads the `x12` of a tight `24"x12"` as a tag, and under WP-04.2's tag inclusion that stray tag beside a different extra reference on the other finding keeps apart two findings the old rule merged |
| WP-06.2 | Whole-set cross-QC on host handles (label shown beside handle), grounded against **uncapped** evidence text like the sharded path, claims rebound through handles, framing hashed into the key; decides D-8 if not yet decided (N6, U8, K2) | L | WP-05.1 | todo | |
| WP-06.3 | Cross-QC terminal honesty: `stop_reason` checked, streaming, bounded raised-cap retry, bounded partial-array salvage, fact-cap and omission counters; decision recorded for N14 (U6, U7 observability, N14) | M | WP-01.2 | todo | |
| WP-10.1 | Tile-label and display-label contract folded into the keys without invalidating unchanged entries (K1) | S | — | todo | |
| WP-10.2 | Critique contract resolved per transport at probe and store; batch runs log that the structured flag is ignored (K3) | S/M | — | todo | |
| WP-10.3 | Planner loss metadata stored with the plan; legacy entries report loss as unknown (K4) | S/M | WP-01.1 | todo | |
| WP-10.4 | Cache map with the admission predicate of every write; N4 read-side migration completed; migration register filled (N4 cache part; WP-10 steps 1, 7, 9) | S/M | WP-01.2, WP-01.4 | todo | |
| WP-03.4 | Versioned `claim_id` beside the existing `id`; the inventoried consumers switched; cross-QC and prose-harvest cache restores rebound; decides D-3 (B8 identity) | L | WP-03.2 | todo | From WP-03.2: `investigate._candidates`, `annotate._severity_first_key`, `_set_findings_outline`, `_annotate_units` and `tile_artifacts._finding_sort_key` sort by `qc_id` before `id`, and every entry is numbered, so in a run they follow the numbering now; their `id` fallback is reached only by an unnumbered finding. Three orders still follow arrival: `pipeline._run_critique_stage`'s pre-ingest sort `(source_page_key, id)` keeps thread-completion order among ties, which becomes ledger order; `findings.json` and `findings.csv` are written in ledger order (`ctx.findings + ctx.reference_findings`, split from `ledger.number()`'s arrival-ordered list); and the report table sorts by severity and status only (`html_report._key`, a stable sort), so ties keep ledger order. Sorting `entries` by `qc_id` after `ledger.number()` would put every row in QC order, a visible change to decide here. From WP-03.3: `Finding.claim_discriminator` exists (arithmetic only, folded into `id`); decide whether `claim_id` builds on it (D-3 records it as an input). The A/B harness's `identity_key` hashes quote-or-text, not the discriminator, so two mismatches on one row still share an A/B identity (`scripts/ab_findings_diff.py`, in this slice's consumer inventory) |
| WP-03.5 | Lossless observations: upstream merges hand observations to the ledger; observations and alternative actions serialized (incl. critique cache); specificity-aware representative (B9, B1 rest, N29; N30's lost text) | L | WP-03.1, WP-03.4, WP-04.2 | todo | From WP-03.2 (N29): `_merge_into` compares an incoming member with the live survivor, whose severity an earlier merge may have raised, so with three or more duplicates the representative follows arrival order. Choose it from the members' own qualities (their snapshots), not the live survivor's, and flip `tests/test_qc_numbering_tiebreak.py::_N29_REPRESENTATIVE` to one representative in every order. From WP-03.1: flip `tests/test_pass_b_complete_link.py::_500_EXPORTED` ("500" leaves the exports in ABC/ACB/BAC, where the generic bridge wins A's bundle). Also hand the prose harvest's matched mirror to the ledger as an observation: `prose_harvest._process_free_pending` sets `also_on` on a live entry directly, so legs attached after that entry's first merge are in no member snapshot and Pass B's complete-link cannot see them (narrow since WP-03.1: Pass B folds such an entry only through a member anchored before ingest). From WP-03.7 (N30): the quote branch folds two different issues that share boilerplate wording ("pump P-1 impeller diameter conflicts with the curve" / "pump P-1 selected flow conflicts with the curve at 480", overlap 0.5, one quote), and the loser's text is lost; its observation is what must survive From WP-07.1: fewer arithmetic mismatches are DETERMINISTIC (only those whose operands the sheet prints where the quote anchors), so `_grounding_quality`'s first rank settles fewer merged entries. When an ungrounded auditor mismatch merges with a model twin, the representative falls to quote length and severity, and a twin that wins carries its own text and verdict into the entry (the auditor's `MODEL_TRANSCRIBED` provenance stays on its member snapshot only). Present before for model-transcribed mismatches; weigh it in the specificity-aware representative |
| WP-03.6 | Canonical final clustering over retained observations; per-observation anchors; idempotent reconciliation (WP-03 clustering clarification) | M/L | WP-03.5 | todo | From WP-03.1: flip `tests/test_pass_b_complete_link.py::_BRIDGE_JOINS` (which cluster the generic bridge joins follows arrival order) and `::test_recorded_limit_a_four_finding_chain_still_counts_by_arrival_order` (entry count 2 or 3 by order). From WP-03.7: the geometric recall WP-03.1 gave up does not come back. A rectangle is resolved from the quote, so it is evidence of where, never of which claim (D-3 input); per-observation anchors map evidence and must not merge two observations (`tests/test_pass_b_complete_link.py::test_a_same_spot_pair_never_folds_on_position`). Pass B now folds nothing Pass A refused, so canonical clustering may replace it rather than extend it |
| WP-06.4 | Direction-free merge for reversed cross-sheet conflicts with a stated same-claim predicate (B10) | M | WP-03.4, WP-06.1 | todo | |
| WP-07.3 | Truthful arithmetic counters split by provenance; contradictory transcriptions of one quote flagged (N18; WP-07 step 7) | S/M | WP-07.1, WP-03.3 | todo | From WP-03.3: the "claim dedup keys move to Decimals" part of WP-07 step 7 is done (`arithmetic.claim_content_key`, shared by all three claim dedups). Since WP-03.3 two contradictory mismatch transcriptions of one quote (different terms) are two findings, where the coordinator used to keep the first one silently; a contradictory pair where one read matches and the other does not still counts one matched and one mismatched (N18 as reproduced) |
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
| WP-21.4 | One display vocabulary: sheet-level observation, no quote, quote not found, not checked, inconclusive, failed attempt (H2) | M/L | WP-05.1, WP-05.2, WP-01.1 | todo | From WP-07.1: an arithmetic mismatch checked against model-transcribed operands is built `UNCERTAIN` before any verifier looks, so on a run with no verification (standard, audit-only) the report shows "Uncertain" ("a verifier looked and could not settle") where "Not checked" is the truth (`html_report._finding_display_status` reads only the status). Present since §17.5; more common since WP-07.1, which makes every ungrounded mismatch `UNCERTAIN`. Include it in the vocabulary (the popup's trust note is already right: `annotate._trust_note` reads `operand_origin` first) |
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
| B1 | Pass B complete-link checks one direction; a 550 gpm finding absorbs the 500 gpm one | P0 | 03.1, 03.5 | open (count part implemented+validated in 03.1; "both measurements survive" in the exports (03.5) stays open) | `tests/test_pass_b_complete_link.py` (all six orders under seven severity and quote-length variants; entry count per variant; the history clique; idempotence; an index-free reference over generated sets) and `tests/test_drawing_dedup_lifecycle.py::test_pass_b_keeps_a_conflict_the_incoming_entry_absorbed` (WP-03.1, [PR #159](https://github.com/Abe-Borg/drawing-analyzer/pull/159)). Remaining: "500" still leaves the exports in ABC/ACB/BAC (`_500_EXPORTED`, WP-03.5); which cluster the bridge joins still follows arrival order (`_BRIDGE_JOINS`, WP-03.6) |
| B2 | Hyphenated units (`6-inch`) get no measurement signature | P0 | 04.1 | implemented+validated | `tests/test_quantity_signature.py` (the B2 token table; the `B2 …` conflict and equivalence pairs, each asserted in the critique merge and the ledger); `tests/test_ab_findings_diff.py::test_a_changed_hyphenated_quantity_is_never_an_exact_match` (WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157)) |
| B3 | Thousands separators split numbers (`12,500` signs as `500`) | P0 | 04.1 | implemented+validated | `tests/test_quantity_signature.py` (the B3 token table, incl. `15,000` once signing as zero and the malformed `1,2,500` kept whole; the `B3 …` pairs); `tests/test_ab_findings_diff.py::test_thousands_grouped_quantities_compare_by_value` (WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157)) |
| B4 | Verbatim quotes fail to anchor on punctuation/spacing variance | P0/P1 | 05.2, 05.3 | open | |
| B5 | Cross-QC quotes under 6 chars are "grounded" without a check | P0 | 05.1 | open | |
| B6 | Cross-QC prompt asks for severity `question`; the items are dropped silently | P0 | 06.1 | open | |
| B7 | Distinct same-row arithmetic mismatches: coordinator dedup, then a ledger geometry merge | P0 | 03.3 | implemented+validated | `tests/test_arithmetic_claim_discriminator.py` (WP-03.3, [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161)): the review's pair and the `[30,30]=500` pair through `run_auditors` (two findings, two ids, `arithmetic_mismatched == len(findings)`); `run_auditors` → `Ledger.add` → seal → Pass B → `number()` in both orders, anchored and on an unresolved sheet, DETERMINISTIC beside UNCERTAIN, each keeping its own id, text, verdict and number; three mismatches on one row in all six orders; the text, quote and geometry branches each refused in Pass A, and geometry in Pass B; an absorbed member's discriminator blocking a generic bridge; true duplicates still merge (a model twin, with the auditor winning the bundle; one claim read twice); Decimal claim keys in all three dedups, incl. unparseable terms |
| B8 | `Finding.id` not unique; numbering, bookmarks and index links treat it as identity | P0 | 03.2, 03.4, 21.3 | open (numbering part implemented+validated in 03.2, as K5; identity (03.4) and navigation (21.3) stay open) | `tests/test_qc_numbering_tiebreak.py` (WP-03.2, [PR #160](https://github.com/Abe-Borg/drawing-analyzer/pull/160)): the `PUMP P-1` pair gets the same numbers and evidence directories in both orders. Since WP-03.3 two arithmetic mismatches on one row get distinct ids (the claim discriminator is folded in; `tests/test_arithmetic_claim_discriminator.py`), and two id dedups are gone (`run_auditors`; `audit_titleblock` now keys on sheet and quote); model findings are unchanged. Since WP-03.7 (N28) every pair of different issues quoting one string reaches the exports as two entries; they still share one content id, so the navigation part below now applies to each such pair (numbers and evidence directories are distinct, pinned in `tests/test_position_is_not_sameness.py`). Remaining: `claim_id` (WP-03.4); bookmark dedup and `mark_page_by_finding` keyed by the content id (WP-21.3) |
| B9 | Merge discards the loser's text and recommended action | P0 | 03.5 | open | |
| B10 | A→B and B→A copies of one conflict both survive | P1 | 06.4 | open | |
| B11 | "No conflicts noted on this sheet." becomes a medium finding | P1 | 09.1 | open | |
| B12 | `deg`/`°` sign differently; `90 deg F` vs `90 deg C` compatible | P0 | 04.1 | implemented+validated | `tests/test_quantity_signature.py` (the B12 token table; the `B12 …` pairs, incl. no inferred scale); `tests/test_ab_findings_diff.py::test_a_changed_temperature_scale_is_never_an_exact_match` (WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157)) |
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
| K5 | QC numbering depends on ingest order | P0 | 03.2 | implemented+validated | `tests/test_qc_numbering_tiebreak.py` (WP-03.2, [PR #160](https://github.com/Abe-Borg/drawing-analyzer/pull/160)): the review's `PUMP P-1` pair in both orders, unanchored and on one rectangle, directly and through the ledger; ledger entries sharing text, quote, category and id (kept apart by absorbed members; by legs); rect-less and set-level findings in every order; generated same-sheet sets in every order (distinct texts, and repeated texts compared by claim); numbering twice; every pair the old key ordered keeps its order. Numbering follows the content it is given: N29 (WP-03.5) can still give it arrival-dependent content |
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
| N1 | One shared value (`100 psi`, `12ft`) masks conflicting measurements | P0 | 04.2 | implemented+validated | `tests/test_quantity_signature.py` (the `N1 …` rows of `_CONFLICTS`, each asserted in the critique merge and the ledger; `_CORROBORATIONS`, `_NO_SHARED_QUANTITY`, `_CONSERVATIVE_RETENTION`, `_RECORDED_LIMITS`); `tests/test_signature_compatibility.py` (tags incl. sheet, grid and detail references; the per-kind table; complete-link in the critique merge, `Ledger.add` and Pass B; the rule never merges a pair the flat rule blocked); `tests/test_ab_findings_diff.py::test_a_conflict_beside_a_shared_value_is_never_an_exact_match` and `::test_a_second_tag_that_changed_is_never_an_exact_match` (WP-04.2, [PR #158](https://github.com/Abe-Borg/drawing-analyzer/pull/158)). Closes every conflict the signature can see. Still merged, as recorded limits: quantity roles (WP-04.3), a bare `12'` against `12'-6"`, and WP-04.1's partial signatures |
| N2 | Cross-QC dedup destroys distinct claims sharing sheet/quote/legs | P0 | 06.1 | open | |
| N3 | Reused operand membership (and fabricated quotes) give false DETERMINISTIC | P0 | 07.1 | implemented+validated | `tests/test_arithmetic_operand_grounding.py` (WP-07.1, PR to follow): the review's `sum [20,20,20] = 40` on `20 + 20 = 40` and on `20 20 TOTAL 40`; a fabricated (UNANCHORED) quote; a quote printed only on another sheet; an unresolved sheet (id not in the set, and no sheets); the stated result reusing a term's number; a FUZZY quote that dropped a printed operand; a quote that starts inside `2-1/2"`; verification eligibility and the trust note; the pipeline sending the N3 mismatch to the crop verifier while the grounded one stays DETERMINISTIC; failures while anchoring or deciding leave it UNCERTAIN. Kept: repeated printed values, equal values in two spellings, a result printed in its own right, `exact_ambiguous`, a vetoed FUZZY anchor. Role swap, sum versus product and A8 stay open (WP-07.2) |
| N4 | Refused/truncated digests and critiques accepted and cached | P0 | 01.2, 01.4, 10.4 | open (digest part implemented+validated in 01.2; the critique part (01.4) and the cache map (10.4) stay open) | `tests/test_digest_terminal_outcome.py` (both transports, both cache levels, the read-side reject, the warm re-run of a refusal the old code cached, the delivery contract) and `tests/test_drawing_acceptance.py::test_a_refused_or_unfinished_digest_holds_the_run_below_complete` (WP-01.2, [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156)). Remaining: the critique (WP-01.4: `critique.outcome_from_message`, and a critique-only contract term, since critique entries store no stop reason); the cache map and the other writers' admission predicates (WP-10.4) |
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
| N19 | W×H duct sizes, `20A`/`480V`, ranges and lists get no or partial signature | P0 | 04.1 | implemented+validated | `tests/test_quantity_signature.py` (the size, volt, amp, range and list tables; the negative corpus; the `N19 …` pairs; `test_a_shared_name_is_not_a_shared_quantity`) (WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157)). Covers the named forms. By decision these still sign partially: loose-comma lists (`2, 4, 6 in`), `to` ranges and `and`/`or` lists, and a bare `20A` with no electrical context. **A conflict hidden by a shared value is N1, not N19:** a pair whose differing quantities sit beside a shared one (`6 in` / `4 in` beside `100 psi`; `12'-6"` / `12'-8"`, both `12ft`) merged until WP-04.2 fixed N1 |
| N20 | Investigation executes and echoes pre-fallback `tool_use` blocks | P1 | 13.4 | open | |
| N21 | Files-API failure fallbacks send full-rate requests under Economy; inline can exceed the size limit | P1 | 18.1, 18.2 | open | |
| N22 | Code and help text claim uploads "expire server-side"; they persist until deleted | P1 | 18.4, 18.5 | open | |
| N23 | GUI cost preflight never runs in a default install (no profiles ship) | P1 | 15.1 | open | |
| N24 | `render.list_sheets` runs on the UI thread outside the preflight lock | P1 | 15.1 | open | |
| N25 | `DRAWING_ANALYZER_CRITIQUE_RUNS ≥ 3` fabricates cross-family corroboration | P1 | 22.2 | open | |
| N26 | Chat transcript kept in `localStorage` on `file://`, readable by other local files | P1 | 20.3 | open | |
| N27 | A stream that ends without `message_stop` is cached as a complete digest | P0 | 01.2 | implemented+validated | `tests/test_digest_terminal_outcome.py::test_n27_a_real_sdk_stream_that_ends_without_message_stop_is_not_a_digest` (the real SDK's stream accumulator over an in-process transport, through `digest_sheet`), plus the `stop_reason=None` cases on both transports, at both cache levels and through the pipeline (WP-01.2, [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156)) |
| N28 | The geometry branch folds two different issues that quote one tag once both anchor there (`PUMP P-1` voltage / impeller); the loser's text is lost | P0 | 03.7 | implemented+validated | `tests/test_position_is_not_sameness.py` (WP-03.7, [PR #162](https://github.com/Abe-Borg/drawing-analyzer/pull/162)): the pair on one rectangle, through the lifecycle in both orders with its numbers and evidence directories, through the pipeline (two digest findings quoting `VAV-3`), and between findings anchored before ingest (Pass A); the predicate reads no rectangle; Pass B adds no fold over generated sets. The recorded limit is flipped: `tests/test_pass_b_complete_link.py::test_two_issues_that_quote_one_tag_stay_apart_after_anchoring`. The pair still shares one content `id` (B8: WP-03.4, WP-21.3) |
| N29 | A merged entry's representative follows arrival order once three or more duplicates merge: an earlier merge's severity union feeds the next `_grounding_quality` comparison | P1 | 03.5 | open | Found by WP-03.2 and pinned as a recorded limit: `tests/test_qc_numbering_tiebreak.py::test_recorded_limit_a_merged_entrys_representative_follows_arrival_order` (`_N29_REPRESENTATIVE`: X's bundle in two of six orders, Z's in four; flip it) |
| N30 | The quote branch (equal quote, text overlap ≥ 0.4) folds two different issues that share boilerplate wording (`PUMP P-1` impeller / selected flow, overlap 0.5); the loser's text is lost | P1 | 03.5 | open | Found by WP-03.7 while measuring N28 (not fixed there; reproduced in its handoff). WP-03.5's lossless observations keep the loser's text; keeping the two apart needs a rule backed by labelled evidence (O-10), not a new threshold (U11) |
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

### 2026-09-23 — WP-07.1: arithmetic operands are trusted only where the sheet prints them (PR to follow)

- **Slice and IDs:** WP-07.1. N3 (implemented+validated). No `DECISIONS.md`
  contract is decided (operand provenance is none of D-1 … D-8); the owner's
  three choices are recorded here, in the plan's WP-07 notes and in CLAUDE.md.
  No migration-register row: no cache or key effect (below). WP-07 is not done
  (WP-07.2, WP-07.3), so there is no package acceptance check.
- **Reproduced first** on `b3f60bb` (scratch script, the real auditor): all four
  shapes were DETERMINISTIC / TEXT_EXTRACTED at high severity:
  `sum [20,20,20] = 40` on the quote `20 + 20 = 40` (anchored EXACT); a
  fabricated quote `20 + 20 + 20 = 40` over a sheet reading `20 + 20 = 40`
  (UNANCHORED); the same claim on a sheet id not in the set (unresolved); and
  `sum [20,30] = 20` on `20 + 30` (the result reusing a term's number).
- **Facts confirmed, not assumed:**
  - Provenance was decided at `audit_arithmetic` 565–573, before its anchoring
    pass (631–641), from `_operands_supported(terms, expected, quote)`
    (`any(p == n)` per operand), and read neither the anchor nor whether the
    sheet resolved. The anchoring pass is inside `audit_arithmetic`, so
    provenance is now decided after it and still before `ledger.add`.
  - Ids do not change: `Finding.__post_init__` calls `compute_finding_id`
    with sheet, category, quote-or-text, source id and claim discriminator,
    never the verdict (pinned in the new N3 test).
  - Critique and cross-QC entries store claims, not provenance; the claims
    contract (`critique._CRITIQUE_FINDINGS_INSTRUCTION` and its cross-QC twin)
    is untouched, so `CRITIQUE_PROMPT_VERSION` does not move.
  - Verification needs a rect (`verify._is_verifiable`), so only a mismatch
    whose quote anchored becomes a new crop-verification call; an UNANCHORED
    or unresolved one has nothing to crop and is only no longer trusted.
- **The decision, made by the owner before any code** (AskUserQuestion with
  measured options). Chosen, each as recommended:
  - **Tiers:** EXACT, or FUZZY by a method that carries the numeric veto.
    `anchor.numbers_grounded(anchor)`: `exact`, `exact_ambiguous`,
    `fuzzy_window` (`_numbers_aligned`), `fuzzy_subphrase` (`_numbers_agree`).
    A method not in that table grounds nothing (fail-closed for a future
    tier); TILE and UNANCHORED never.
  - **The stated result needs its own printed occurrence:** the terms and the
    expected value are counted together (`Counter([*terms, expected])` must fit
    the printed numbers). `20 + 30` states no total of 20; `20 + 30 = 20`
    (two printed 20s) stays trusted.
  - **Evidence: both must print it.** An operand counts where both the quote
    and the sheet's own words under the matched span print it, per value the
    smaller count (`arithmetic._operands_grounded`). Options not taken:
    counting the quote only (anchor-gated; it takes the model's spelling: a
    quote starting inside `2-1/2"` reads a `1/2` the sheet never printed), and
    counting the span words only (reads numbers the quote left out, and reads
    the sheet's non-ASCII forms with ASCII rules: an en-dash `12'–6"` gave a
    phantom `12` and `6`). Three edge cases were run on the real code to show
    the difference (a FUZZY quote that dropped a printed `20`, an en-dash
    dimension, a sheet's `2½"`); the new tests pin the first, plus a quote that
    starts inside `2-1/2"`, where counting the quote alone trusts a number the
    sheet never printed.
  - **Measured first**, as the request asked: a scratch copy of `origin/main`
    logged, for every mismatch in the full suite, today's provenance and all
    12 combinations (evidence quote / span / both × result joint / separate ×
    tiers EXACT / EXACT+FUZZY). The hooks ran 67 `audit_arithmetic` calls, 115
    claims, 89 mismatches (51 EXACT, 38 UNANCHORED, 0 FUZZY). **All 12
    combinations agree on the suite:** 10 claims move TE→MT, none MT→TE, and
    every one is an unresolved-sheet claim from a test calling
    `audit_arithmetic(..., [])`. No fixture has a duplicated operand, a reused
    result or a FUZZY anchor, so the choices differ only on the new tests.
- **What changed:**
  - `anchor.py`: the three quote tiers also return the token span they
    matched; `_anchor_one` returns `(anchor, span)`; `resolve_anchors` takes an
    optional keyword `matched_text` and, for every finding it anchors EXACT or
    FUZZY, records the sheet's own words under that span (`_span_text`: whole
    words as printed, reading order; `_span_word_indices` is now shared with
    `_span_rect`). Nothing about an anchor changes (pinned: equal anchors with
    and without the keyword; every anchor test passes unchanged).
    `numbers_grounded` sits beside the veto it relies on.
  - `auditors/arithmetic.py`: `_operands_supported` is occurrence-aware over a
    `Counter` of printed values; `_operands_grounded` counts quote ∩ span;
    `_arithmetic_verification` builds both verdicts with the notes
    byte-identical to before. Every mismatch is built MODEL_TRANSCRIBED /
    UNCERTAIN, kept on a `pending` list rolled back with the findings on a
    per-claim failure, and promoted after the anchoring pass only when the
    claim resolved, `numbers_grounded(anchor)` holds and `_operands_grounded`
    holds. Fail-safe: anchoring is now guarded per sheet (an error on one
    sheet used to propagate out of `audit_arithmetic`, and `run_auditors` then
    lost every arithmetic finding and the four stat keys), and a failure while
    deciding leaves that one finding UNCERTAIN. Module and function docstrings
    updated.
  - The matched path (`result.matched`) still does not check provenance
    (N18/WP-07.3, as scoped).
- **Contracts decided:** none of D-1 … D-8. The operand-grounding rule is the
  owner's (above).
- **Cache/schema effects: none**, confirmed:
  - The verification note keeps its exact wording for each provenance (pinned
    by `test_the_verification_note_keeps_its_wording_for_each_provenance`), so
    `investigate._payload_hash`, which reads the prior note, is unchanged for
    every mismatch that stays model-transcribed. A mismatch that becomes
    model-transcribed was DETERMINISTIC before, which verification and
    investigation never take, so it has no stored entry to miss: its
    verification and investigation calls are new work, not misses.
  - The verify keys include `operand_origin` (`_computation_cache_metadata`)
    and the anchor; neither changes for a mismatch that stays
    model-transcribed, and anchors are unchanged for everything.
  - No prompt, claims contract, request shape, id, anchor, `_SCHEMA_VERSION` or
    critique/cross-QC contract changed; `tests/test_drawing_cache_identity.py`
    passes unchanged.
  - The A/B `RECORD_CONTRACT_VERSION` stays 3: a record stores the
    verification status as an arm output, and its docstring bumps only when
    what a record stores changes shape or meaning (as WP-03.7 and WP-04.2).
    Comparing an arm run before WP-07.1 with one after reports the N3
    findings' status as a delta, which is the code change it is.
- **Re-baselined tests** (the three the plan names, given the case they
  model):
  - `tests/test_drawing_auditors.py::test_a_comma_separated_operand_list_stays_text_extracted`,
    `::test_arithmetic_text_extracted_operands_stay_deterministic` and
    `::test_arithmetic_mixed_fraction_operand_is_text_extracted` called
    `audit_arithmetic(..., [])` and asserted DETERMINISTIC. Each now gets a
    sheet printing its quote's row, and still asserts DETERMINISTIC /
    TEXT_EXTRACTED. Checked both ways: the edited file passes on the base
    (74/74), and the original file fails exactly these three on the fix.
  - **Plan corrected** (README step 7):
    `::test_arithmetic_unresolved_sheet_still_records_finding_unanchored` did
    not need a re-baseline. Its finding was already UNCERTAIN on 1.7.0 and
    `b3f60bb` (its quote `X` carries no operand). It gains one assertion
    (UNCERTAIN, true on both trees); the unresolved case with an operand-bearing
    quote is in the new file.
  - Passing unchanged: the gauntlet's `test_gauntlet_deterministic_auditors_fired`
    (its quote `TOTAL 100 + 250 = 375` is on the sheet: still DETERMINISTIC),
    `tests/test_drawing_qc_pipeline.py::test_arithmetic_auditor_flags_bad_claim_end_to_end`
    (MODEL_TRANSCRIBED), all of `tests/test_arithmetic_claim_discriminator.py`
    (incl. the lifecycle test, which compares each entry with the auditor's
    verdict for its claim alone, and `…_merges_with_its_model_twin_and_wins_the_bundle`,
    whose row stays DETERMINISTIC), `tests/test_drawing_ledger.py` (69, 85),
    `tests/test_drawing_dedup_lifecycle.py::test_a_deterministic_member_wins_the_representative_and_keeps_its_verdict`,
    `tests/test_drawing_verify.py` (817–905), `tests/test_drawing_investigate.py`
    (961, 995), `tests/test_drawing_markup_rich.py` (146), and
    `::test_the_quote_scanner_and_the_operand_parser_never_disagree`.
- **Fixture effects, instrumented over the whole fixed suite** (a scratch copy
  logging every mismatch with its old-rule and new-rule provenance): 91
  `audit_arithmetic` calls, 117 mismatches; **24 changed, all TE→MT, none
  MT→TE**. 17 are the new file's own cases. The other 7 are unresolved-sheet
  claims in four tests of `tests/test_arithmetic_claim_discriminator.py`
  (the lifecycle test's unresolved arm, 4; the absorbed-member test; the Pass B
  test; the discriminator matrix's quote row), and none of them asserts that
  status. The gauntlet and pipeline fixtures do not move.
- **New tests:** `tests/test_arithmetic_operand_grounding.py` (31): the N3
  pair (`20 + 20 = 40`, `20 20 TOTAL 40`) with anchor, text, severity and id
  unchanged; repeated printed values, equal values in two spellings, and a
  result printed in its own right stay trusted; the result reusing a term; a
  fabricated quote; a quote printed only on another sheet; an unresolved sheet
  (id not in the set, and no sheets); `exact_ambiguous` stays trusted; a vetoed
  FUZZY anchor grounds, and a FUZZY quote that dropped a printed `20` is
  bounded by the quote; a quote starting inside `2-1/2"`; `numbers_grounded`
  over every status and method (9 rows, incl. an unknown FUZZY method);
  `resolve_anchors(matched_text=)` (whole words, nothing for TILE, UNANCHORED
  or pre-anchored findings, anchors equal without it); verification
  eligibility; the trust note; `run_auditors`' tally with both verdicts; the
  note's wording; an anchoring failure on one sheet and a failure deciding one
  finding (both leave only that finding UNCERTAIN); and **the pipeline**: on an
  exhaustive run the N3 mismatch is sent to the crop verifier once and ends
  VERIFIED with its MODEL_TRANSCRIBED caveat, while `TOTAL 100 + 250 = 375`
  stays DETERMINISTIC and is never re-checked.
- **Downstream consumers walked:**
  - Verification (`_is_verifiable`): an anchored ungrounded mismatch is now
    eligible (one crop call each on exhaustive runs); it enters verification's
    D-2 denominator like any finding. Investigation (`_candidates`): eligible
    if the crop leaves it UNCERTAIN.
  - Markups (`annotate`): the popup's trust note reads `operand_origin` first
    ("Computed from numbers as read by the AI - re-check the math against the
    sheet."), before and after a verdict; verified-only mode no longer inks an
    ungrounded mismatch unless the verifier confirms it; the index says
    "Check" (or "Verified") instead of "Computed". Placement kind, severity
    layer and stamping are unchanged (the anchor is unchanged).
  - Report (`html_report._finding_display_status`): "Deterministic" becomes
    "Uncertain", "Unanchored" (a fabricated quote) or the verifier's verdict.
    Where no verifier ran, "Uncertain" overstates what happened (noted on
    WP-21.4).
  - Exports: `findings.csv` `verification_status` / `verification_note` and
    `markup_manifest.json` dispositions follow the status; `findings.json` is
    otherwise unchanged (no new field).
  - Ledger: fewer entries rank first in `_grounding_quality` (noted on WP-03.5).
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,258 passed, 2 skipped, 10 deselected** (213 s) on `b3f60bb`,
    identical to the WP-03.7 handoff.
  - **Failing first.** The new file and the edited `tests/test_drawing_auditors.py`
    were run in a `git archive` copy of `origin/main` (`b3f60bb`), classified
    from `--junitxml`: **new file: 15 failed on behaviour, 11 failed only on
    the new API** (`numbers_grounded` ×9, the `matched_text` keyword,
    `_operands_grounded`), **5 passed** (they pin what the fix keeps: repeated
    values, two spellings, a result printed in its own right, `exact_ambiguous`,
    a vetoed FUZZY anchor). The edited `tests/test_drawing_auditors.py`: 74
    passed.
  - **After:** full suite **3,289 passed, 2 skipped, 10 deselected** (204 s): the baseline plus the 31 new
    tests, with the same two environment skips (IPv6 loopback; chmod as root).
  - **Browser suite:** not run separately; no report JS, HTML or chat code
    changed (the browser tests ran inside the full suite).
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds one unused
    import, on `origin/main` already and on a line this change does not touch
    (`arithmetic._wtext`; WP-22.5). `scan_secrets.py` is clean over
    202 tracked files, the new one included. `compileall src` passes.
- **Docs:** CHANGELOG (Fixed, N3, with the visible effect, the extra
  verification calls and the cache note); CLAUDE.md (the "model never
  calculates" invariant, the anchor paragraph, the `_grounding_quality`
  sentence); README (the verification status table and the numeric-claims
  contract); the plan (WP-07 step 2 and step 3 notes: the decisions, and the
  unresolved-sheet test correction); PROGRESS (this entry, the WP-07.1 and N3
  rows, notes on WP-07.2, WP-21.4 and WP-03.5).
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: how many real mismatches are ungrounded, so how many
  verification calls this adds per run, is unmeasured (O-10). Windows is
  covered by this PR's CI.
- **Risks and residual gaps:**
  - **More paid calls, by design:** every anchored ungrounded mismatch is now
    crop-verified on exhaustive runs, and investigated if the crop cannot
    settle it. The pre-run cost estimate does not price auditor findings
    separately (unchanged).
  - **A grounded claim can still name the wrong relationship:** `20 × 2 = 40`
    transcribed as `sum [20, 2] = 40` prints every operand once, so it is a
    DETERMINISTIC "the sum of 20, 2 is 22" mismatch on a correct product
    (checked on the fixed tree). Role swap, sum versus product and A8 are
    WP-07.2's (noted on its row).
  - **Non-ASCII forms are refused, not read:** the sheet's `2½"` parses as `2`,
    so a claim over it is UNCERTAIN even when the model's `2 1/2` is right.
    The safe direction; WP-07.2's strict tokens can decide whether to read it.
  - "Uncertain" in the report on a run with no verifier (WP-21.4 note).
- **Re-checked (U31):** the other auditors build their anchors from their own
  word rects and never call `resolve_anchors`; the pipeline's anchor stage
  skips a finding that already carries a rect and re-derives the same
  UNANCHORED result for one that does not (same words, same resolver), so it
  cannot change an arithmetic finding's anchor after its provenance was
  decided.
- **Next:** WP-07.2 (A8, strict tokens and relationships), which depends only
  on WP-07.1.

### 2026-09-23 — WP-03.7: position is not evidence that two findings are one ([PR #162](https://github.com/Abe-Borg/drawing-analyzer/pull/162))

- **Slice and IDs:** WP-03.7. N28 (implemented+validated). B8 stays `open`
  (identity WP-03.4, navigation WP-21.3); its row notes that every pair N28
  folded now reaches the exports as two entries sharing one content id. No
  `DECISIONS.md` contract is decided: D-3 stays open for WP-03.4 and gains a
  WP-03.7 input ("what may fold two findings"). One new finding, **N30**,
  recorded, not fixed (WP-03.5). No migration-register row: no cache or key
  effect (below).
- **The decision, made by the owner before any code** (the session request
  asked for it; AskUserQuestion with measured options). Chosen: **(a) drop
  the geometry branch** of `critique._is_duplicate`, in both passes.
  - **Why no threshold, restated with the mechanism.** The anchor stage
    resolves each rectangle from the finding's own quote (`anchor._anchor_one`:
    the quote, and the tile only to choose among repeated occurrences). Two
    findings quoting one string therefore share a rectangle by construction, so
    "equal quote + IoU > 0.5" was the quote-alone merge the quote branch
    refuses on purpose (Phase 20 review FM-1), applied once anchors existed.
    History: `a7a1619` (FM-2) replaced the branch's text-or-substring check with
    an equal quote, which is where the text check went missing.
  - **Measured first** (a scratch copy of `origin/main` logging, for every
    Pass A add, Pass B entry and critique `_cluster` step, the decision under
    today's rule, option (a) and a shared-word option (c), with the test name
    from `PYTEST_CURRENT_TEST`; the hooks ran 4,260 Pass A adds, 4,607 Pass B
    entries, 334 `_cluster` findings and 13,532 predicate calls, 22 of them
    accepted by the geometry branch). The branch decided **10 folds, all in 6
    synthetic tests**: 7 in Pass B, 3 in Pass A (one pre-anchored pair in
    `test_ingest_order_independent_entries_and_numbers`, which asserts only
    order independence). `_cluster`: none (critique reads are unanchored).
    Gauntlet (`tests/test_drawing_acceptance.py`: 173 Pass A adds, 169 Pass B
    entries, 62 predicate calls) and pipeline fixtures
    (`tests/test_drawing_qc_pipeline.py`: 82/82/6): **no fold changes** under
    any option.
  - **Options not taken.** (b) A claim discriminator for model findings: the
    host cannot derive one that separates the pair (both sign as
    `{tags: [P1], measurements: [], absence: False, legs: []}`; `480` and `208`
    carry no unit), and a model-emitted one needs digest and critique schema
    changes, which move `DIGEST_PROMPT_VERSION` / `CRITIQUE_PROMPT_VERSION`
    (every cached read re-billed), need live evidence (O-4), and move the
    ratchet (contract 2 → 3). (c) Geometry plus one content word shared outside
    the quote: separates the two fixtures but is a threshold at one word;
    "pump P-1 impeller diameter conflicts with the curve" / "pump P-1 motor
    nameplate voltage conflicts with panel LP-2" (overlap 0.31, share
    "conflicts") still folded on one rectangle. Geometry only between findings
    anchored before ingest: keeps N28 between two auditors.
- **What changed:**
  - `critique._is_duplicate`: the geometry branch and `_IOU_DUP_THRESHOLD` are
    gone; the docstring states the rule and why. Two accepting branches remain,
    both needing text agreement. `_rect_iou` stays (tests import it; plan §2
    rule 15), with a note that no merge rule reads it.
  - **Pass B folds nothing Pass A refused**, derived and measured: every pair of
    members two entries hold was compared by Pass A (an entry's first member
    met every member of each earlier entry, and the index cannot miss one),
    and nothing the predicate reads changes afterwards except a cross-sheet
    leg the prose harvest adds to a leg-less entry
    (`prose_harvest._process_free_pending` sets `also_on` only when empty),
    which can only block. A scratch copy of the fixed tree counted Pass B
    folds over the whole suite: see Validation. `reconcile_post_anchor` stays
    (cheap, idempotent); its docstring now says so, with the WP-03.1 history.
    Removing it or rebuilding clustering is WP-03.6's (row updated: the
    geometric recall does not come back through per-observation anchors).
  - Comments that described the branch: `ledger.py` (module docstring, the
    candidate-index comment, `_freeze_history_head`, `reconcile_post_anchor`,
    `_candidates`), `pipeline.py` (the Pass B call), `citation_check.py` (why
    the edition divergence anchors to its own span).
  - **Plan corrected** (README step 7): WP-03 step 6's "choose one of" note and
    the slices paragraph record the resolution; N30 added to §3, WP-03's
    "Covers", §7.1's range and §7.2.
  - **Codex review, P1, fixed in this PR** ("offset markups for same-anchor
    findings"). Keeping the pair apart was only half of it if the reviewed
    drawing cannot show it: `annotate._add_qc_tag` laid a QC tag out from its
    cloud's rectangle alone, so two findings on one rectangle got their tags
    at one spot and the later, white-filled, covered the earlier. Verified on
    the PR head (both tag rects identical, also on a sheet rotated 90°). Root
    cause, not only this pair: WP-03.3's two arithmetic mismatches on one row
    collided the same way. Now `_annotate_units` lays out every page's tags
    before drawing (`_plan_tag_boxes`, in QC-number order, never drawing
    order, which follows arrival, I-7): a tag with nothing in its way keeps
    its home spot (`_home_tag_box`, the old formula, so every other markup
    is unchanged), and one that would cover an earlier tag slides along the
    row and then to the next row away from the cloud (`_clear_tag_box`,
    bounded: a row is crossed in at most `len(placed) + 1` steps and each
    placed tag blocks at most two rows; no clear spot falls back to home, so
    a tag is never dropped). Non-fatal: a planning failure leaves every tag
    at home. The two clouds still coincide, as the finding's location; the
    tags tell them apart. Stamping and reconciliation are untouched (the tag
    stays an optional, stamped component).
- **Contracts decided:** none (D-3 input recorded: position is evidence of
  where, never of which claim).
- **Cache/schema effects: none**, confirmed:
  - The merge-rule ratchet (`tests/test_drawing_cache_identity.py`) passes
    unchanged: its corpus is unanchored, and the fingerprint recomputed with
    the branch removed equals the pinned contract-2 value
    (`63dbfe17…`). The critique cache stores `_cluster`'s output, whose inputs
    are unanchored (`_representative` resets anchors; 0 `_cluster` events).
    `_CRITIQUE_CACHE_CONTRACT` stays 2.
  - The ledger (both passes) is rebuilt every run and never cached.
  - `CRITIQUE_PROMPT_VERSION` / `DIGEST_PROMPT_VERSION` hash prompt strings,
    untouched; `_SCHEMA_VERSION` untouched; cross-QC does not call
    `_is_duplicate`.
  - Downstream per-finding caches key on one finding's own content (verify:
    request shape; investigation: id, text, quote, category, severity, rect,
    prior note, source fingerprint). A finding that is now kept separate is a
    new finding with its own key, and a survivor that no longer absorbs it can
    carry a different severity or sources (a miss for that entry), as with any
    change in the set. No key definition changed, so no register row.
  - The A/B `RECORD_CONTRACT_VERSION` stays 3 (a rule-only change, as WP-04.2).
- **Re-baselined tests** (each is the case it modelled under the new rule):
  - `tests/test_drawing_dedup_lifecycle.py`:
    `test_post_anchor_reconciliation_folds_a_geometric_duplicate` →
    `test_post_anchor_reconciliation_keeps_a_same_spot_paraphrase_apart`
    (folded 1 → 0): the decided cost, pinned as retention.
  - `tests/test_pass_b_complete_link.py`:
    `test_a_geometric_duplicate_folds_only_between_entries_that_absorbed_nothing`
    → `test_a_same_spot_pair_never_folds_on_position` (all 8 configurations
    stay two; the live pair is no longer a duplicate);
    `test_recorded_limit_the_geometry_branch_folds_two_issues_that_quote_one_tag`
    → `test_two_issues_that_quote_one_tag_stay_apart_after_anchoring` (the
    flip). `_BRIDGE_JOINS`, `_500_EXPORTED` and the four-finding chain are
    untouched and pass. Module docstring updated.
  - `tests/test_signature_compatibility.py`:
    `test_pass_b_still_folds_a_reference_one_side_omits` →
    `test_pass_b_does_not_fold_a_compatible_pair_on_position_alone`
    ((2, 1) → (2, 2), with the signatures still asserted compatible); the
    rule it illustrated is pinned on text by
    `test_a_reference_one_side_omits_still_merges`, unchanged.
  - `tests/test_arithmetic_claim_discriminator.py`: the branch matrix's
    geometry row is removed (no branch accepts that pair any more, so its
    discriminators have nothing to block); the pair moved to
    `test_two_arithmetic_mismatches_on_one_row_stay_apart_without_their_discriminators`
    in the new file. Two docstrings reworded. Pass B after ingest (354) and
    the coordinator twin test (139, identical texts) pass unchanged.
  - `tests/test_qc_numbering_tiebreak.py`:
    `test_the_k5_pair_through_the_whole_lifecycle_on_one_rectangle` now also
    asserts the WP-03.2 numbers (`QC-001` motor, `QC-002` pump), as its
    docstring anticipated.
  - Passing unchanged: `test_overlapping_rects_stay_separate_without_semantic_match`,
    `test_same_quote_unrelated_text_stays_two_entries`,
    `test_a_deterministic_member_wins_the_representative_and_keeps_its_verdict`
    (same quote + moderate text), `test_duplicate_matrix` (its r1/r3 fold is
    strong text), `tests/test_drawing_ledger.py` (69, 85), the ratchet, the
    gauntlet, and `test_ingest_order_independent_entries_and_numbers` (4
    entries instead of 3; it asserts order independence only).
- **New tests:** `tests/test_position_is_not_sameness.py` (27): the N28 pair
  on one rectangle (predicate), through the lifecycle in both orders, with its
  numbers and evidence directories; two auditor-shaped findings anchored before
  ingest (Pass A, both orders); the real arithmetic auditor's same-row pair
  without discriminators; the predicate reads no rectangle over 8 same-quote
  pairs × 5 placements; the pairs that fold on text still fold; Pass B adds no
  fold over generated sets (1,080 runs; the seed is one whose sets contain the
  same-spot shape, counted so the test cannot pass vacuously: the old rule
  folded 36 times there); and **the pipeline**: two digest findings quoting
  `VAV-3` on a standard run are two findings with `QC-001`/`QC-002` on one
  EXACT rectangle (on the base, "post-anchor reconciliation folded 1"). Added
  for the Codex P1 (8): two findings on one rectangle get two non-overlapping
  tags on the reopened reviewed PDF (both orders, rotation 0 and 90); the same
  through the pipeline with QC markups on; a lone tag keeps its old spot;
  twelve tags on one rectangle never overlap, stay on the page and come out
  the same in any input order; tags move away from a cloud at the top edge,
  and a page with no room still gets every tag.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,232 passed, 2 skipped, 10 deselected** (219 s) on `614951d`,
    identical to the WP-03.3 handoff.
  - **Failing first.** The new file and the five edited test files were run
    in a `git archive` copy of `origin/main` (`614951d`), classified from
    `--junitxml`: **27 failed, all on behaviour, 0 on a new API; 241 passed.**
    The 27: the 8 same-spot configurations, the N28 flip, the `CO-1`
    retention, the Pass B omit pair, the K5 lifecycle numbers, and 15 of the
    new file's 19 (the 4 that pass pin what the fix keeps: the three
    predicate rows that fold or never fold on text, and the text folds).
  - **After:** full suite **3,250 passed, 2 skipped, 10 deselected** (217 s):
    the baseline plus 19 new, minus the removed matrix row, with the same two
    environment skips (IPv6 loopback; chmod as root).
  - **After the Codex P1 fix:** full suite **3,258 passed, 2 skipped, 10
    deselected** (213 s): the 3,250 above plus the 8 tag tests. Those 8 were
    first run in a `git archive` of the PR head before the fix (`1c35a87`):
    5 failed on behaviour (both tag rects identical, incl. the pipeline run
    with QC markups), 3 only on the new helpers; the 19 earlier tests passed.
    A rendered check of the reviewed PDF shows `QC-001` at its old spot and
    `QC-002` beside it over one cloud. `annotate.py` adds one pre-existing
    F401 hit to the list below (`ANNOTATION_COMPONENTS`, on `origin/main`).
  - **Pass B folds after the fix:** a scratch copy of the fixed tree counted
    them over the full suite (3,250 passed): **0 folds** in 7,322 Pass B
    entries, beside 8,000 Pass A adds (the base had 7 folds, all refused by
    the new rule).
  - **Browser suite:** not run separately; no report JS, HTML or chat code
    changed (the browser tests ran inside the full suite).
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds three unused
    imports, all on `origin/main` already and on lines this change does not
    touch (`critique.DEFAULT_DIGEST_MAX_TOKENS`, `pipeline.normalize_specs_text`,
    `pathlib.Path` in `tests/test_drawing_dedup_lifecycle.py`; WP-22.5).
    `scan_secrets.py` is clean over 201 tracked files, the new one included.
    `compileall src` passes.
- **Docs:** CHANGELOG (Fixed, N28, with the visible effect, the decided cost
  and the cache note); CLAUDE.md (the ledger paragraph's opening, the
  `_is_duplicate` gate text, the Pass B text and the recorded limits); README
  (the merge rule, the lifecycle, the auditors intro, and the ledger paragraph
  that named N28 as a known gap); DECISIONS (D-3 input); the plan (above).
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: how often two findings quote one string at one spot,
  and how many of those pairs are paraphrases rather than different issues,
  is unmeasured (O-10). Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **Recall, decided.** A same-spot paraphrase that shares fewer than 0.4 of
    its content words is two findings (the `CO-1` and `RV-3` shapes). A
    reviewer sees one more row; nothing is lost.
  - **Same content id, two entries.** Every pair N28 used to fold now ships as
    two entries sharing one `id` (the id hashes the quote, B8). Numbers and
    evidence directories are distinct (pinned); bookmark dedup and
    `mark_page_by_finding` still key on the id, so the second of such a pair
    can lack an outline entry or have its index row link to the other's page
    (WP-21.3). This existed before for unanchored pairs; it is now as common
    as the pairs themselves.
  - **N30 (new, P1, WP-03.5).** The quote branch folds two different issues
    that share boilerplate: "pump P-1 impeller diameter conflicts with the
    curve" / "pump P-1 selected flow conflicts with the curve at 480" (one
    quote, overlap 0.5) are one entry in Pass A and the impeller text is lost
    (reproduced). The same class as N28 on a text branch; out of this slice,
    and a threshold change needs labelled evidence (U11, O-10). WP-03.5's
    lossless observations are where the text survives.
  - Pass B now does no work in the pipeline; it costs one complete-link sweep
    per run (measured at ~0.4 s on a synthetic 1,693-entry ledger by WP-03.1).
- **Next:** WP-07.1 (Wave 1, no dependencies).

### 2026-09-23 — WP-03.3: distinct same-row arithmetic mismatches survive ([PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161))

- **Slice and IDs:** WP-03.3. B7 (implemented+validated). B8 stays `open`: two
  arithmetic mismatches on one row no longer share an id, but `claim_id`
  (WP-03.4) and navigation (WP-21.3) remain. No `DECISIONS.md` contract is
  decided: D-3 stays open for WP-03.4 and records the discriminator as an
  input; D-4 gains a WP-03.3 note; three migration-register rows.
- **What changed:**
  - **Reproduced first** on `37cbd98` (scratch script, both trees). Claims
    `sum [20,20,20] = 540` (operands on the row: DETERMINISTIC) and
    `sum [30,30] = 500` (UNCERTAIN), and the review's
    `factor [1500, "1.3"] = 2000`, on the quote `20 20 20 TOTAL 540`:
    `audit_arithmetic` gave two findings with one id (`915ec7e11272`),
    `run_auditors` kept one with `arithmetic_mismatched == 2`, and with the
    coordinator bypassed `Ledger.add` folded them in both orders into the
    DETERMINISTIC one. `20` against `"20.0"` gave `checked=2, mismatched=2`
    and two same-id findings. **Correction:** `540` against `"540"` did not
    reproduce: `str(540) == "540"`, so those already shared a key. The gaps
    were `20` against `"20.0"` or the JSON float `20.0`, `1200` against
    `"1,200"`, terms in another order, and `factor` against `product`.
  - **The coordinator** (`auditors.run_auditors`) no longer de-duplicates. The
    ledger decides: a true cross-auditor duplicate (one quote, one rectangle)
    still becomes one entry with both tags (pinned). `audit_titleblock`'s
    two-path dedup keys on `(source_page_key, source_quote)` instead of the id;
    behaviour-identical today (both paths build the same sheet id and
    category), and pinned against an id that folds the text.
  - **The discriminator.** `Finding.claim_discriminator: str = ""`, appended
    last. The choice: an additive field, not derived host-side, because the
    only host-side source would be the finding's display text, and because it
    must survive serialization (`findings.json`) and ride a merge. `to_dict`
    emits it only when set (the `citation` precedent), so every other finding
    and every critique/cross-QC cache entry serializes byte-identically;
    `from_dict` defaults it to `""`.
    - Its value is `auditors.arithmetic.arithmetic_claim_discriminator`:
      `arithmetic/1:<operation>:<terms>=<stated>`, from `claim_content_key`
      (the host operation, with `factor` as `product`; the terms as a sorted
      multiset, since both operations commute; exact decimals by
      `canonical_decimal`, never rounded at 28 digits and never raising).
    - `critique._claims_differ` refuses a merge when BOTH findings carry one
      and they differ. It runs in `_is_duplicate` before every accepting
      branch, so it holds in Pass A and Pass B. One side alone never blocks,
      so an auditor finding still merges with its model twin and wins the
      bundle (the three pinned tests pass unchanged, and a new one uses the
      real auditor's output).
    - Folded into `id`: `compute_finding_id` takes it as a last argument,
      appended after `\x01` only when non-empty (the `source_id` precedent),
      so every other id is byte-identical (`tests/test_drawing_models.py`,
      `tests/test_source_identity.py` pass unchanged). `Finding.__post_init__`
      and `digest._rebind_cached_finding` pass it.
    - It rides the representative's bundle in `ledger._merge_into` and
      `critique._representative`, with the id it is folded into. When the
      bundle goes to a member without one, the absorbed arithmetic member
      still blocks a different claim from its snapshot (pinned with a generic
      bridge that duplicates both mismatches).
    - Scoped by who sets it: only the arithmetic auditor. Designed to
      generalize (WP-03.7): a versioned scheme, a producer-neutral field, a
      rule that needs both sides.
  - **Decimal claim keys.** All three claim dedups share `claim_content_key`:
    `arithmetic._claim_dedup_key` (the last before any count or finding),
    `critique._dedup_claims` and `cross_qc._dedup_claims`. The request named
    two; cross-QC has its own copy (it does not call the critique's) with the
    same `str()` keys, so it moved too (plan text corrected, README step 7).
    An unparseable term keeps its raw spelling behind a `raw:` tag, so it never
    collapses two different claims and never equals a number.
    `critique._dedup_claims`' source part (`source_name.lower()`, page) is
    **not** a DA-001 defect: it only ever sees one sheet's reads (both callers
    of `result_from_outcomes` are per sheet), so that part is constant; noted
    in its docstring. The Decimal change touched the same tuple (the kind,
    terms and expected elements), and left the source part alone.
- **Contracts decided:** none (D-3 input recorded; D-4 note added).
- **Cache/schema effects** (three migration-register rows):
  - **Investigation** (`stage=investigation`): the key hashes `id`, and every
    arithmetic finding's id changed. Only a mismatch checked against
    model-transcribed numbers that stays UNCERTAIN and anchored after
    verification is ever investigated, so only those entries miss once (a paid
    re-investigation, exhaustive runs only). One mechanism: the id change
    itself; no term, no `_SCHEMA_VERSION` bump.
  - **Critique** (stored claims): no change. A stored entry can hold two
    spellings of one claim; the arithmetic auditor collapses them exactly as a
    cold run would (one entry is one sheet). The merge-rule ratchet
    (`tests/test_drawing_cache_identity.py`) passes unchanged, so the critique
    contract stays at 2: `_claims_differ` only fires on two findings that both
    carry a discriminator, and no critique finding does.
  - **Cross-QC** (stored claims): no change, with one narrow residual,
    accepted and recorded: this dedup compares the quote lowercased and the
    auditor's does not, so two transcriptions whose quotes differ in case AND
    whose numbers are spelled differently are counted twice from a stored
    entry and once cold (the tally only; their findings share a discriminator
    and merge in the ledger, checked). WP-05.1's planned bump (3 → 4) retires
    those entries.
  - Not affected: the verify keys (no `id`), the citation check (arithmetic
    findings carry no `refs`), the digest cache (`_SCHEMA_VERSION` untouched),
    the A/B record contract (a record stores `finding_id` as a reference and
    an unchanged `critical_signature`).
- **Re-baselined tests:** none. Every pinned test the request listed passes
  unchanged: `tests/test_drawing_auditors.py` (the stats contract; the
  540/660 lesson; `deduplicates_repeated_claims`; `anchors_mismatch_via_quote`;
  `unresolved_sheet_still_records_finding_unanchored`; the three
  `run_auditors` tests, incl. "no two findings share an id"; the title-block
  tests), `tests/test_drawing_dedup_lifecycle.py` (85, 252, 307),
  `tests/test_drawing_ledger.py` (69, 85), the gauntlet's
  `test_gauntlet_deterministic_auditors_fired`, `tests/test_drawing_cross_qc.py`,
  `tests/test_source_identity.py`, `tests/test_drawing_cache_identity.py` and
  `tests/test_qc_numbering_tiebreak.py`. The new tests do not pin operand
  provenance where WP-07.1 changes it: the lifecycle test compares each
  entry's verdict with what the auditor gives its claim alone, and asserts
  DETERMINISTIC only for the anchored row.
- **Fixture effects, checked by instrumenting the full suite** (a scratch copy
  whose hooks logged every merge `_claims_differ` newly refused, every claim
  any of the three dedups newly collapsed or newly kept, every finding the old
  coordinator id dedup would have dropped, and every title-block call where
  the old and new keys disagree). **All 82 events came from
  `tests/test_arithmetic_claim_discriminator.py`**; no existing test produced
  one. The hooks were exercised: over the gauntlet, pipeline, auditor, ledger
  and lifecycle suites, 81 `run_auditors` calls, 7 of them with arithmetic
  findings, and never two discriminated findings compared with each other. So
  the existing corpus cannot show this change, which is why the new file
  covers the matrix.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,204 passed, 2 skipped, 10 deselected** (208 s) on `37cbd98`,
    identical to the WP-03.2 handoff.
  - **Failing first.** The new file (28 tests) was run in a `git archive` copy
    of `origin/main` (`37cbd98`) with only that file added, classified from
    `--junitxml`:
    - **20 failed on behaviour:** distinct ids (both second claims); both
      mismatches through `run_auditors` (both); the tally against retained
      findings; the coordinator handing both twins to the ledger; the
      title-block key; the lifecycle in both orders (anchored, unresolved);
      three mismatches in six orders; the three branches; Pass B after
      ingest; the absorbed member's discriminator; a model twin joining its
      own mismatch; one claim read twice; Decimal dedup in the auditor, the
      critique and cross-QC.
    - **5 failed only on the new API:** the 5-argument `compute_finding_id`,
      the new field (round trip, bundle), the new helpers
      (`arithmetic_claim_discriminator`, `claim_value_key`).
    - **3 passed**, pinning what the fix keeps: the auditor still merges with
      its model twin and wins the bundle; findings without a discriminator
      merge as before; an unparseable term never collapses two claims.
  - **After:** the 28 new tests pass. Full suite **3,232 passed, 2 skipped,
    10 deselected** (203 s): the baseline plus 28, with the same two
    environment skips (IPv6 loopback; chmod as root).
  - **Browser suite:** not run separately; no report JS, HTML or chat code
    changed (the browser tests ran inside the full suite).
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds two unused
    imports, both on `origin/main` already and on lines this change does not
    touch (`arithmetic._wtext`, `critique.DEFAULT_DIGEST_MAX_TOKENS`; WP-22.5).
    `scan_secrets.py` is clean over 200 tracked files, the new one included.
    `compileall src` passes.
- **Docs:** CHANGELOG (Fixed, B7, with the visible effect and the cache
  note); CLAUDE.md (the auditors paragraph, the `_is_duplicate` gate and the
  bundle in the ledger paragraph, "one claim" in the model-never-calculates
  invariant); README (the auditors intro, the numeric-claims contract, the
  ledger merge paragraph); the plan's WP-03 step 5 note (the third dedup; the
  `540` correction).
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: how often two mismatches share a row is unmeasured
  (O-10). Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **Visible changes, by design.** A row with two different mistakes shows
    two findings. Every arithmetic finding's id changes (CSV `id` column,
    `markup_manifest.json` `finding_id`), and `findings.json` gains a
    `claim_discriminator` key on arithmetic findings only.
  - Two reads that transcribe one relationship with contradictory terms now
    produce two findings where the coordinator kept the first. Honest (the
    reads disagree), and N18's flagging is WP-07.3's.
  - A model twin that duplicates two different mismatches joins whichever
    arrives first (the generic-bridge limit, WP-03.6); both mismatches still
    survive. Not observed with realistic wording: the twin in the tests
    matches only its own mismatch in every order.
  - The A/B harness's `identity_key` does not see the discriminator (noted on
    WP-03.4).
- **Re-checked (U31):** every other id-keyed dedup over findings
  (`cross_qc._dedup_findings`, `references._audit_sheet`'s quote dedup) is
  outside this slice and unchanged; `run_auditors`'s only production caller
  ingests its findings straight into the ledger.
- **Next:** WP-03.7 (N28), which needs a decision first; its row now records
  what the arithmetic discriminator settles and what generalizing it costs.

### 2026-09-23 — WP-03.2: QC numbers break a positional tie by content ([PR #160](https://github.com/Abe-Borg/drawing-analyzer/pull/160))

- **Slice and IDs:** WP-03.2. K5 (implemented+validated), and with it B8's
  numbering part; B8 stays `open` for its identity (WP-03.4) and navigation
  (WP-21.3) parts. No `DECISIONS.md` contract is decided: the tie-break is a
  display order, not an identity, so D-3 stays open for WP-03.4. One new
  finding, **N29**, recorded and pinned, not fixed; it goes to **WP-03.5**.
- **What changed:**
  - **Reproduced first** on `2300762`. The review's pair (X "pump P-1 has no
    isolation valve on the suction side", Y "motor horsepower for P-1
    disagrees with the pump schedule", both quoting `PUMP P-1` on one sheet,
    page and source, one category and severity) shares an id.
    `assign_qc_ids([X, Y])` gave X `QC-001` and `[Y, X]` gave Y `QC-001`,
    unanchored and on one shared rectangle alike. Through the ledger (ingest,
    seal, both `UNANCHORED` with `quote_not_found`, Pass B, `number()`) the
    numbers followed arrival too. Anchored to one rectangle, Pass B folds the
    pair instead (N28).
  - **The tie-break** (`models.assign_qc_ids`). The positional order is
    unchanged: set-level last, then source input order, page, anchored before
    rect-less, top, left. A tie is broken by, most significant first:
    1. the content `id`, the old tie-break, kept first so every pair whose
       ids differ keeps its number;
    2. the text, as in `ledger._grounding_quality` (the precedent: id, then
       text). It separates the K5 pair: "motor…" gets `QC-001` in both
       orders;
    3. `_qc_content_key`: every `Finding` field but `qc_id`, as one canonical
       JSON string. It walks `dataclasses.fields`, so a field added later is
       covered. `_ARRIVAL_ORDERED_FIELDS` are sorted: the four lists
       `ledger._merge_into` unions in arrival order (`sources`, `refs`,
       `supporting_quotes`, `prose_item_ids`) and `citations`, which the
       citation stage writes in `refs` order. `tile` and `also_on` keep their
       order: `[row, col]`, and one producer's legs, numbered in that order on
       the evidence.
  - **Why the order is total** (argued in the docstring, pinned by tests).
    Two findings that tie on all three are equal in every field except `qc_id`
    and the order of those five lists: the same claim with the same evidence.
    Text and quote alone are not enough, as the session request warned: Pass A
    keeps two entries apart when members they absorbed conflict, and the two
    can still share text, quote, category and id. Built through the ledger in
    all 24 orders (two critique representatives with one text and one quote
    whose supporting quotes say 500 and 550 gpm, each absorbing the digest
    finding that agrees with it), what separates them is their supporting
    quotes. Three cross-QC findings with one text, one quote and different
    legs are separated by `also_on`. Two ledger entries can also differ only
    in members that left no trace on the live entry, since a merge keeps only
    the representative's text (B9). Nothing after numbering reads the members:
    `member_history` and `merge_trace` have no reader outside the ledger, and
    Pass B runs before numbering. Such entries are interchangeable until
    WP-03.5 serializes observations.
  - **Cost.** The content key is built only for the runs the cheap key
    (position, id, text) leaves tied. For 2,000 realistic findings, numbering
    takes 4.6 ms against 2.8 ms on the base. The worst case, 2,000 findings
    all tied on position, id and text, takes 85 ms. Building the key for every
    finding took about 100 ms (measured, not adopted).
  - **Docstrings corrected:** `assign_qc_ids`, whose "tie-broken by the stable
    content id … regardless of the order they arrive in" did not hold, and
    `Ledger.number`. `_grounding_quality`'s docstring now says its promise
    ("regardless of ingest order for a fixed set of members") holds only
    within one merge (N29).
  - **Plan corrected** (README step 7): N29 is added to §3, §7.1's range,
    §7.2, and WP-03's "Covers" and slice paragraph.
  - **Docs:**
    - CHANGELOG: Fixed, K5, with the visible effect, "nothing is migrated",
      and what stays open.
    - CLAUDE.md: the ledger lifecycle sentence gains the tie-break and the
      no-cache-key fact; the severity-union sentence gains N29.
    - README: the ledger lifecycle paragraph. The visible numbering of a tied
      pair changes.
- **Contracts decided:** none.
- **Cache/schema effects:** none, confirmed.
  - No cache key or model request reads `qc_id`.
    - The verify keys (`_single_verify_cache_key`, `_cross_verify_cache_key`)
      hash the finding's text, quote, category, severity, sheet, source, page,
      anchor and computation metadata, and the request itself. No model
      request carries `qc_id`: checked over `verify._build_request`,
      `_build_dual_request` and the investigation's `_build_initial_content`
      and `_investigation_message` (only the evidence files
      `request.json` and `investigation.json` record it).
    - The investigation key (`_payload_hash`) hashes `id`, text, quote,
      category, severity, rect, prior note and `set_content_fingerprint`. A
      cached investigation stores status, note, rounds and a tool trace of
      source keys, rects, DPI and sha256, with no directory name: the replay
      takes the directory from the current run's evidence or number.
    - `qc_id` does not occur in `digest_cache.py`, `citation_check.py`,
      `critique.py`, `cross_qc.py` or `prose_harvest.py`.
  - The ledger is rebuilt every run.

  So no key, contract or `_SCHEMA_VERSION` change, and no migration-register
  row. A tied pair's numbers can differ from 1.7.0's, which renames its
  evidence directories; historical exports are untouched.
- **Re-baselined tests:** none. Every pinned test passes unchanged:
  - `tests/test_drawing_dedup_lifecycle.py`:
    `test_ingest_order_independent_entries_and_numbers`,
    `test_qc_numbers_follow_source_input_order_then_position`,
    `test_unanchored_sorts_after_anchored_on_same_sheet`,
    `test_a_post_numbered_duplicate_is_counted_and_never_rewrites_the_entry`;
  - `tests/test_drawing_ledger.py`: `test_ledger_freeze_assigns_stable_qc_ids`,
    `test_ledger_post_seal_add_marks_incomplete_not_fatal`;
  - `tests/test_drawing_markup_rich.py`: `test_qc_ids_ordered_sheet_then_position`,
    `test_qc_ids_stable_regardless_of_input_order`,
    `test_qc_id_round_trips_through_dict`;
  - the gauntlet's numbering assertions in `tests/test_drawing_acceptance.py`,
    the `QC-001`/`QC-002` pins in `tests/test_drawing_qc_pipeline.py`, and
    every file that hard-codes `QC-0xx` (1,243 tests over 22 files, run
    together).

  A green run does not show that no fixture renumbered, so the full suite also
  ran once in a scratch copy whose `assign_qc_ids` logged every call where the
  new order differed from the 1.7.0 key's (position, then id). Every logged
  call came from `tests/test_qc_numbering_tiebreak.py`. No existing fixture,
  the gauntlet's full pipeline run included, holds a tie the new rule orders
  differently.
- **The consumers of `qc_id`** (session request step 3): display and order
  only, never a cache key.
  - Evidence directory names (`verify._reserve_evidence_dir`, reused by the
    investigation's replay), `request.json` and `investigation.json`.
  - The pipeline's recovered-verdict match (`qc_id in verify_not_judged`,
    within one run).
  - The markup tags, the index and the outline; the report's deep links; the
    export's `qc_id` column; the tile notes.

  Five sort keys order by `qc_id` before `id`: `investigate._candidates`,
  `annotate._severity_first_key`, `_set_findings_outline`, `_annotate_units`
  and `tile_artifacts._finding_sort_key`. Every entry in a run is numbered,
  so these follow the numbering now; their `id` fallback is reached only by
  an unnumbered finding.
  Three orders still follow arrival once numbering is fixed; recorded on the
  WP-03.4 row, not fixed here:
  - the critique stage's pre-ingest sort `(source_page_key, id)` keeps
    thread-completion order among ties, and that becomes ledger order;
  - `findings.json` and `findings.csv` are written in ledger order;
  - the report table sorts by severity and status only (a stable sort), so
    its ties keep ledger order.
- **New finding N29** (P1; WP-03.5, noted on its row; plan §3 and §7.2). A
  merged entry's representative can follow arrival order.
  - `_merge_into` computes both quality tuples before this merge's severity
    union, which fixed the pair case
    (`test_the_representative_does_not_depend_on_ingest_order`). But it
    compares the incoming member with the live survivor, whose severity an
    EARLIER merge may already have raised.
  - Members X (22-character quote, `low`), Y (10-character quote, `high`)
    and Z (22-character quote, `medium`) all merge into one entry. X's bundle
    wins in XYZ and YXZ; Z's wins in the other four orders.
  - Numbering is a function of each entry's content, so it cannot repair
    content that was assembled in arrival order. Pinned as a recorded limit:
    `tests/test_qc_numbering_tiebreak.py::_N29_REPRESENTATIVE`.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,179 passed, 2 skipped, 10 deselected** (232 s) on `2300762`,
    identical to the WP-03.1 handoff.
  - **Failing first.** The 25 new tests were run in a `git archive` copy of
    `origin/main` (`2300762`) with only the new test file added, and the
    results were classified from `--junitxml`:
    - **11 failed on behaviour:** the K5 pair directly (both placements),
      through the ledger (unanchored; one rectangle without the fold), the
      evidence directories, the absorbed-conflict entries, the legs entries,
      the rect-less set, the set-level set, and both generated-set
      properties.
    - **3 failed only on importing the new helpers:** the content key's
      field coverage, the list classification, and never-raises.
    - **11 passed**, pinning what the fix keeps: the precondition (both
      placements), the whole lifecycle on one rectangle (N28 folds the pair
      the same way in both orders), numbering twice, every pair the old key
      ordered, and the six N29 recorded-limit rows.
  - **After:** the 25 new tests pass. Full suite **3,204 passed, 2 skipped,
    10 deselected** (221 s): the baseline plus the 25 new tests, with the
    same two environment skips (IPv6 loopback; chmod as root).
  - The generated-set properties are not vacuous: 25 of the 60 seeded sets
    with distinct texts tie on the old key somewhere, and 29 of the 80 with
    repeated texts tie on id **and** text. Their floors (15 each) guard
    against a generator change.
  - **Browser suite:** not run separately. No report JS, HTML or chat code
    changed; the browser tests ran inside the full suite.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (the
    pinned 0.14.5) is clean. F401/F811/F841 over the touched source and test
    files is clean. `scan_secrets.py` is clean over 199 tracked files, the new
    one included. `compileall src` passes.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: every fixture is synthetic, and how often a real set
  holds a tie the id did not break is unmeasured (O-10). Windows is covered by
  this PR's CI.
- **Risks and residual gaps:**
  - **A visible change, by design.** A tied pair can be numbered the other way
    round than in 1.7.0, and its evidence directories, tags, index rows and
    bookmark swap with it.
  - The third tie-break compares canonical JSON strings, so which field
    decides between two such findings follows the alphabetical order of the
    field names. It is deterministic, not meaningful; it is only reached when
    id and text tie.
  - `_canonical_json`'s `default=str` fallback only meets values no stage
    stores (a hand-built test double). For an object whose `str` holds a
    memory address, the order would change between processes; no `Finding`
    field holds one.
- **Re-checked (U31):**
  - `assign_qc_ids` has one production caller, `Ledger.number()`. The
    pipeline calls it once, after Pass B, outside any `try`, which is why the
    key must never raise; it doesn't (a test covers it).
  - `from_dict` restores a stored `qc_id`, and the new key excludes `qc_id`,
    so a stale number never feeds the order.
- **Next:** WP-03.3 (Wave 1). WP-03.7 waits on WP-03.3 and needs a decision
  first; WP-03.4 now has its dependency done.

### 2026-09-23 — WP-03.1: symmetric complete-link in Pass B ([PR #159](https://github.com/Abe-Borg/drawing-analyzer/pull/159))

- **Slice and IDs:** WP-03.1. B1, count part (B1 stays `open` for WP-03.5,
  as N4 stays open for its critique part). No `DECISIONS.md` contract is
  decided (D-3 stays open for WP-03.4). One new finding, **N28**, recorded and
  pinned, not fixed; it gets slice **WP-03.7** (below).
- **What changed:**
  - **The predicate** (`ledger.reconcile_post_anchor`). An entry `e` folds
    into a survivor `s` only when every member of `Ledger.member_history(e)`
    is `critique._is_duplicate` of every member of `s`'s history: Pass A's
    all-pairs relation, over both sides, each member as it arrived. Before, the
    live `e` alone was compared with `s`'s members. In the B1 case the live
    `e` had handed its bundle to the generic member in Pass A, so the
    `500 gpm` it absorbed never met the `550 gpm` survivor. `_is_duplicate` is
    symmetric, so the outcome no longer depends on which entry sorts first. A
    new survivor's local history is the list it was just compared through
    (`members[id(e)] = incoming`), the same objects `member_history` returns.
  - **Reproduced first** on `321cb8e`: ABC, ACB and BAC ended with one entry
    and no `500` in text, quote or `supporting_quotes`; BCA, CAB and CBA kept
    two. Now two entries in all six orders.
  - **The candidate index cannot miss a fold** the predicate allows, argued
    at `_candidates` and pinned. It looks survivors up by `e`'s live text
    tokens and quote. Every accepting branch of `_is_duplicate` needs a shared
    text token or an equal quote. The pair of representatives (the members
    carrying each entry's live text and quote: the last bundle winner's
    snapshot, or the live head) is always among the pairs checked, and a
    survivor's own signals were indexed when it became one and never change
    in Pass B, since the best-first sort means it always keeps its bundle. A
    survivor the index skips shares nothing with that pair, so the predicate
    would refuse it anyway. Pinned by comparing Pass B's partition with an
    index-free reference over generated sets
    (`test_generated_sets_keep_the_invariants_in_every_order`).
  - **The geometry decision: record the loss, don't lend the rect.** Pass A
    snapshots are frozen before anchoring, so they carry no rectangle, and the
    geometry branch needs one on both sides. Two entries Pass A kept apart hold
    a pair of members Pass A did not find to be duplicates, and a rectangle is
    the only evidence Pass B has that Pass A lacked. So Pass B now folds only
    entries that absorbed nothing in Pass A (or whose absorbed members were
    anchored before ingest, as auditor findings are). Measured in
    `test_a_geometric_duplicate_folds_only_between_entries_that_absorbed_nothing`
    (both sides quote `CO-1` and anchor to one rectangle, too little shared
    text for Pass A):

    | Which side absorbed a Pass A member | Before | After |
    |---|---|---|
    | neither | folds | folds |
    | the survivor only | stays two | stays two |
    | the incoming entry only | folds | **stays two** |
    | both | stays two | stays two |

    Geometric duplicates share a quote, so they tie on quote length (and, with
    one category, on id); which side was "incoming" was decided by severity,
    then text. So before, whether two such clusters folded was arbitrary. Now
    they never do.
    Why not lend the resolved rect to snapshots that quote the same string
    (the first of the three options in the plan's WP-03 verification note on
    step 6)? The geometry branch has no text check, so it already folds two
    different issues that quote one tag once both anchor there (N28, below),
    and lending would extend that rule to every cluster quoting one string. And `anchor.resolve_anchors` picks among repeated
    occurrences by each finding's own `tile`, so a lent rect is a guess about
    where that member was. Anchoring each observation (the second option)
    belongs to WP-03.6's per-observation anchors. Plan §2.1: conservative
    retention over unproven merging.
  - **What Pass B can still fold, measured** (scratch, not committed; 400
    generated sets of 3–5 findings, all orders, none anchored before ingest):
    0 folds involved a Pass-A-merged entry, against 1,671 on the base;
    singleton-to-singleton folds were identical on both trees (982). Over
    15,180 runs the new partition equalled the base's 13,646 times and was
    strictly finer 1,534 times; it never folded a pair the base kept apart.
    That follows from the code one fold at a time: for an incoming entry that
    absorbed nothing, the old and new rules check the same pairs, and one that
    absorbed something no longer folds. Only the sequence of folds can differ.
  - **Plan corrected** (README step 7): N28 is added to plan §1.1's ID scope
    line, §3, §7.1's range and §7.2, and to WP-03's "Covers" and slice list
    (WP-03.1 … WP-03.7, with the reason).
  - **Docs:**
    - CHANGELOG: Fixed, B1 count part, with the visible effect and what stays
      open.
    - CLAUDE.md: the "every complete-link check" sentence now covers both
      sides. The Pass B sentences are rewritten for the symmetric predicate,
      the index argument, the geometry decision and the recorded limits.
    - README: the ledger lifecycle paragraph. The visible count changes.
    - `critique.py`: the "Growing signatures" paragraph of
      `signature_conflicts` and the `_sig_text` comment. **Pass B's incoming
      entry no longer sees a grown signature**; two places still do (a
      critique representative entering the ledger, WP-03.5; the A/B harness).
    - `ledger.py`: the `reconcile_post_anchor` docstring and the comments on
      `_members`, `_freeze_history_head`, `_candidates` and the predicate.
- **Contracts decided:** none.
- **Cache/schema effects:** none, confirmed:
  - The ledger (Pass A and Pass B) is rebuilt every run and never cached.
  - The critique cache stores `_cluster`'s output, which this slice does not
    touch.
  - The merge-rule ratchet (`tests/test_drawing_cache_identity.py`)
    fingerprints `critical_signature`, `_is_duplicate` and
    `merge_self_consistency` over unanchored findings, all untouched. It
    passes unchanged.
  - `CRITIQUE_PROMPT_VERSION` hashes prompt strings, not module source, so
    the docstring edits move no key.
  - The downstream per-finding caches key on one finding's own content, not
    on the fold structure. Investigation keys on id, text, quote, category,
    severity, rect, prior note and `set_content_fingerprint`, which hashes the
    source documents, not ledger entries. An entry the fix keeps separate is
    a finding with its own key, as with any other change in the set.

  So no cached consumer of Pass B's result exists. No key, contract or
  `_SCHEMA_VERSION` change, and no migration-register row.
- **Re-baselined tests:** none. Every pinned test passes unchanged:
  - the 24 existing tests of `tests/test_drawing_dedup_lifecycle.py`, incl.
    `test_overlapping_rects_stay_separate_without_semantic_match`,
    `test_ingest_order_independent_entries_and_numbers`,
    `test_complete_link_ingest_survives_representative_switch`,
    `test_pass_b_complete_link_does_not_collapse_a_conflicting_chain`,
    `test_the_representative_does_not_depend_on_ingest_order`,
    `test_post_anchor_reconciliation_folds_a_geometric_duplicate`,
    `test_pass_b_keeps_a_conflict_carried_in_text_not_the_quote` and
    `test_a_second_merge_cannot_capture_the_first_merges_result_as_history`;
  - `tests/test_signature_compatibility.py` (its Pass B pairs are both
    singletons) and `tests/test_drawing_ledger.py`;
  - `tests/test_drawing_qc_pipeline.py` and `tests/test_drawing_acceptance.py`
    (the trust gauntlet).

  The evidence's claim that the review's symmetric patch keeps both files
  green holds again with today's larger files. Edited without changing an
  assertion: the "Growing signatures" comment in
  `tests/test_signature_compatibility.py`.
- **Recorded limits** (pinned in `tests/test_pass_b_complete_link.py` so the
  closing slice flips them deliberately; the WP-03.5, WP-03.6 and WP-03.7
  rows name them):
  - which cluster the generic bridge joins still follows arrival order: A's
    in ABC/ACB/BAC, C's in BCA/CAB/CBA (`_BRIDGE_JOINS`, WP-03.6);
  - whether `500` reaches the exports: lost in ABC/ACB/BAC, where the bridge's
    longer quote wins A's bundle in Pass A; `500` then lives only in the
    runtime member history (`_500_EXPORTED`, WP-03.5);
  - a four-finding chain (A–B, B–C, C–D duplicates, every other pair in
    conflict) still ends with two or three entries by arrival order: Pass A's
    online clustering is greedy (WP-03.6). The count is order-independent for
    three findings (no three-finding generated set varied: 0 of 500 in the
    scratch search, against 21 on the base) but not beyond;
  - N28 (next item).
- **New finding N28** (P0; slice WP-03.7, Wave 1 after WP-03.3; plan §3 and
  §7.2). `_is_duplicate`'s geometry branch folds two different issues that
  quote one tag. `pump P-1 voltage listed as 480 should be 208` and
  `pump P-1 impeller diameter conflicts with the curve`, both quoting
  `PUMP P-1`, stay apart in Pass A (the quote alone is not enough), then fold
  in Pass B once both anchor to the tag. The impeller issue is gone: its text
  is overwritten and its quote equals the survivor's. WP-03's regression "two
  `PUMP P-1` issues retain separate identities" cannot hold at the pipeline
  level while this stands. No text-overlap threshold separates it from the
  paraphrase fold `test_post_anchor_reconciliation_folds_a_geometric_duplicate`
  pins (0.09 against 0.25), so WP-03.7 starts with a decision.
- **Validation (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):**
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,063 passed, 2 skipped, 10 deselected** (220 s) on `321cb8e`,
    identical to the WP-04.2 handoff.
  - **Failing first.** The 116 new tests (115 in
    `tests/test_pass_b_complete_link.py`, plus the reverse-order twin), run in
    a `git archive` copy of `origin/main` (`321cb8e`) with only the two test
    files replaced, results classified from `--junitxml`:
    - **23 failed, all on behaviour, none on import.** They are 12 of the 42
      B1-matrix cases (`b1` ABC/ACB/BAC, `mirror` BCA/CAB/CBA,
      `500-most-severe` BCA/CAB/CBA, `550-most-severe` ABC/ACB/BAC), 4 of the
      7 per-variant count tests, 2 of the 8 geometry configurations (the
      absorbing side sorting second), 3 of the 6 bridge-cluster limits (the
      base put all three findings in one entry), the generated-sets property
      test, and the twin.
    - **93 passed.** They pin what the fix keeps: the other 30 matrix cases,
      all 42 idempotence cases (idempotence held on the base too: randomized
      searches over 1,300 generated sets, all orders, found no base
      counterexample), the 3 control variants' counts (`review-as-written` is
      the review's own construction, with B quoting nothing, which does not
      fail on `main`), 6 geometry configurations, the three recorded limits
      the fix does not change, and the check that the variants cover both
      roles and both bundle winners.
    - The 24 existing lifecycle tests passed on the base.
  - **After:** the 116 new tests pass. Full suite **3,179 passed, 2 skipped,
    10 deselected** (215 s): the baseline plus the 116 new tests, with the same
    two environment skips (IPv6 loopback; chmod as root).
  - **Browser suite:** not run separately. No report JS, HTML or chat code
    changed; the browser tests ran inside the full suite.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` (the pinned 0.14.5,
    run as `python -m ruff`: the container's `ruff` on `PATH` is 0.15.8) is
    clean. F401/F811/F841 over the touched files shows two hits, both present
    on the base (WP-22.5 territory); none is new. `scan_secrets.py` is clean
    over 198 tracked files, the new one included. `compileall src` passes.
  - **Cost:** Pass B on a synthetic 1,693-entry, 40-sheet ledger with 103
    Pass-A-merged entries, best of 5: 418 ms against 438 ms on the base. It
    folded 60 entries, against 63 on the base.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: every fixture is synthetic, and how often the
  geometric recall loss occurs on a real set is unmeasured (O-10). Windows is
  covered by this PR's CI.
- **Risks and residual gaps:**
  - **A visible behaviour change, by design.** A report can show one more
    finding where a conflicting measurement used to be folded away, and a
    same-spot duplicate of an already-merged finding now appears as its own
    row.
  - **Geometric recall loss (decided).** A finding that quotes the same string
    at the same spot but is worded differently no longer folds into an entry
    that absorbed a member in Pass A, on either side. The live pair is a
    geometric duplicate (asserted in the test); the snapshots are not.
  - **Legs the prose harvest attaches after a merge.**
    `prose_harvest._process_free_pending` sets `also_on` on a live entry
    directly, outside `_merge_into`: the only signature-relevant mutation of a
    ledger entry between ingest and Pass B (a grep for `.also_on =`). Legs
    attached after the entry's first merge are in no member snapshot, so
    complete-link cannot see them on either side. Before, it could not on the
    survivor side either. Since WP-03.1 such an entry folds only through a
    member anchored before ingest, so the gap is narrow; noted on WP-03.5 (hand
    the harvest's match to the ledger as an observation).
  - **Not pairwise stricter in one contrived shape.** The old rule compared
    the incoming entry's grown signature, which holds the winner's text and
    every member's quote. That union can conflict where no member does. The
    member-wise judgment is the faithful one (WP-04.2 already rules out
    comparing grown signatures). Only an entry with a member anchored before
    ingest could reach that case, since Pass B no longer folds any other
    merged entry.
- **Re-checked (U31):**
  - Pass B's only production caller is `pipeline.py`, which swallows any
    exception with a warning (I-3). The new tests call
    `reconcile_post_anchor` directly.
  - `member_history` and `adopt_members` have no other callers.
  - `resolve_anchors` resolves each finding from its own quote and `tile`,
    and skips findings already anchored.
  - The investigation key's set fingerprint covers source documents, not
    ledger entries.
- **Next:** WP-03.2 (Wave 1). WP-03.5 now waits on WP-03.4; WP-03.7 waits on
  WP-03.3 and needs a decision first.

### 2026-09-23 — WP-04.2: the compatibility rule behind the critical signature ([PR #158](https://github.com/Abe-Borg/drawing-analyzer/pull/158))

- **Slice and IDs:** WP-04.2. N1. No `DECISIONS.md` contract is decided here.
  D-4 stays open; this slice adds one migration-register row and one sentence
  to D-4. **WP-04 is not done** (acceptance check below): WP-04.3 is added for
  quantity roles.
- **What changed:**
  - **One copy of the rule.** New `critique.signature_conflicts(a, b) ->
    list[str]` names the conflicting axes, always in the order `tags`,
    `measurements`, `absence_polarity`, `cross_sheet_legs` (the names the A/B
    report already printed). `signatures_compatible` is its negation. It takes
    two `critical_signature` records, so stored signatures are judged exactly
    as live ones are.
  - **Quantities, per kind.** A token's unit is what follows its value's last
    digit (WP-04.1's representation), and a composite stays one whole token.
    Units group into kinds (`critique._QUANTITY_KIND`): lengths (`in`, `ft`,
    `mm`, `cm`, and the empty unit of a unitless W×H size), degrees (`°`, `°f`,
    `°c`), pressures (`psi`, `psig`), voltages (`volt`, `vac`, `vdc`, `kv`),
    liquid flow (`gpm`, `gph`, `gpd`), real power (`hp`, `kw`) and apparent
    power (`va`, `kva`); every other unit is its own kind. `cfm` stays apart
    from liquid flow, and apparent from real power, on purpose: each pair names
    two quantities (a coil's water and air flow; a transformer's kVA rating and
    a load's kW), not one quantity in two units. Two signatures conflict on measurements
    when both carry some and either they share no token at all (the old flat
    rule, kept: `6 in` / `150 mm`, `24x12` / `24x10 in`) or, for some kind both
    carry, each holds a token of that kind the other lacks.
  - **Two choices beyond the plan's "minimum rule" (disjoint value sets per
    unit), and why:**
    - *Inclusion, not disjointness.* WP-04.1's handoff lists three N1 pairs.
      Disjoint-per-unit closes two (`12'-6"` / `12'-8"`; `6 in` / `4 in` beside
      `100 psi`), but not the third, two lists written with a unit on every
      element that share one element (`2 in, 4 in and 6 in` / `3 in, 5 in and
      6 in`): the `in` values intersect. The same holds for a shown/required
      pair sharing the shown value (`500` / `550` against `500` / `600 gpm`).
      Inclusion blocks them and still lets one side add detail.
    - *Kinds, not bare units.* With units alone, a conflict between two units
      the tokenizer keeps apart on purpose was still masked by a value shared
      in another unit: `90°F` / `90°C` beside a shared `6 in`, `20 psig` /
      `20 psi`, `120V` / `24VAC` controls beside a shared `480V`, `6 in` /
      `100 mm` beside `100 psi`. That is N1 again. A kind relates units without
      converting any value (`12 in` never equals `1 ft`, `psig` is never `psi`,
      no scale is inferred), so it can only ever block a merge. Explicit
      fixtures for every kind: `tests/test_signature_compatibility.py::_KIND_CASES`.
  - **Tags: inclusion, not grouped by prefix.** One finding may name a
    reference the other omits (`P-1` / `P-1 + V-3`, `VAV-3` / `VAV-3 per
    M-501`, a grid or a detail reference) and they merge. Two findings that
    each name a tag the other lacks conflict: `P-1 + V-3` / `P-1 + V-4`, and
    also `EF-1 on LP-1` / `EF-1 on HP-1`, which a prefix grouping (the per-unit
    analogue) would have merged, since `LP` and `HP` are different prefixes of
    one role. The cost: two findings that each name a different *kind* of
    extra reference (`P-1 + V-3` / `P-1 per M-501`) stay apart. That is
    deliberate conservative retention, recorded in the fixtures
    (`_TAG_RETENTION`). Tested against sheet ids, grid references and detail
    references in both directions.
  - **The rule only ever blocks more.** Every pair the old flat rule blocked is
    still blocked (`test_the_rule_blocks_every_pair_the_flat_rule_blocked`,
    over a corpus where the old rule blocks 50+ pairs). No finding that was
    separate before becomes merged.
  - **Growing signatures (plan step 4 asks for a statement).** A survivor's
    signature includes its `supporting_quotes`, so its sets grow as it absorbs
    members, and inclusion then accepts any newcomer the grown set contains.
    The complete-link checks never compare a newcomer with the grown survivor:
    the critique's `_cluster` checks each read's original finding,
    `Ledger.add` checks the member snapshots, and Pass B's survivor side reads
    `Ledger.member_history`. Tested in all three
    (`tests/test_signature_compatibility.py`, "Growing signatures"). Three
    places still see a grown signature:
    - Pass B's *incoming* entry, which is the live object (B1, WP-03.1);
    - a critique representative entering the ledger as one finding. Its reads
      were merged upstream, and its signature holds their quotes but not their
      texts (B9). That is why a read whose tag sits in its quote still blocks a
      conflicting digest finding
      (`test_a_critique_representative_brings_its_members_quotes_into_the_ledger`),
      and why one whose tag sits only in its text does not (WP-03.5);
    - the A/B harness, which compares each arm's final findings.
  - **Roles are not compared** (the matrix's "repeated values in different
    roles"). Recorded as a limit, not handled conservatively: the conservative
    rule (keep apart any pair with two or more values of one kind on both
    sides) would split the commonest duplicate there is, the same "500 gpm
    shown, 550 gpm required" from both critique reads. Pinned in
    `tests/test_quantity_signature.py::_RECORDED_LIMITS` with the other pairs
    that still merge: swapped roles, one value in two roles, a bare `12'`
    against `12'-6"` (feet-inches is two tokens), and WP-04.1's partial
    signatures (`4 to 6 in`, loose-comma lists, a bare `20A`).
  - **A/B harness.** `_signature_conflicts`, the restated copy, is gone.
    `_conflicting_axes` calls `critique.signature_conflicts`; `_compatible`
    still calls `signatures_compatible`. Axis names are unchanged.
    `RECORD_CONTRACT_VERSION` stays **3**: a record stores the signature's
    tokens, which did not change, and the rule is re-applied whenever two
    records are compared, so a v3 record is judged by the new rule exactly as
    a fresh one is. The version's comment says so, and a test round-trips a
    v3 record through JSON and gets the new verdict.
  - **Plan corrected** (README step 7): the WP-04 verification note "Step 6"
    said to bump `RECORD_CONTRACT_VERSION`; it was written before WP-04.1 took
    that bump for the tokenizer. The plan's slice list now names WP-04.3.
  - **Review follow-up (Codex P1 on this PR).** A unit left out of the kind
    table is a kind of its own, so a shared value could still hide a conflict
    between two units of one quantity: `500 gpm` / `12,000 gph` beside a shared
    `100 psi` stayed compatible, and so did `5 hp` / `7.5 kW` and `500 VA` /
    `1 kVA` beside a shared voltage. The root cause was an incomplete table, not
    one pair, so every group of units the tokenizer emits for one quantity is
    now listed (liquid flow, real power, apparent power) and the table's comment
    names what stays apart on purpose (`cfm`; kVA against kW) and the units that
    are alone (`fpm`, `hz`, `amp`, `gal`, `%`). A check over the tokenizer's
    unit list confirmed nothing else is missing. The 10 new tests failed on this
    PR's head before the fix; 3 more pin what stays apart. The ratchet's corpus
    gained a gpm/gph and an hp/kW pair, each of which merges under the
    pre-review rule and not under this one, and key 2 was re-pinned (the value
    is new in this PR, so nothing released is edited).
  - **Docs:** CHANGELOG (Fixed: N1, with the one-time critique re-run and the
    visible effect; WP-04.1's "Not in this change" note points to it), CLAUDE.md
    (the ledger paragraph describes the rule, the growth statement and the
    limits; the `12'-6"` entry is removed from "Known-inaccurate statements",
    since keeping both halves now does keep `12'-6"` and `12'-8"` apart), README
    (the ledger section's N1 limit replaced by the rule and its remaining
    limits; the critique-cache paragraph names the one-time re-run),
    `docs/PERFORMANCE_AND_COST_VALIDATION.md` (the harness's axes now come from
    the rule).
- **Contracts decided:** none. D-4 (open) gains a sentence: WP-04.2 bumped the
  critique contract to 2.
- **Cache/schema effects:**
  - Critique cache, both levels: `digest_cache._CRITIQUE_CACHE_CONTRACT` 1 → 2.
    Every critique entry written under 1 misses once (it can hold a merge the
    new rule refuses). Nothing is deleted. The next exhaustive run re-critiques
    every sheet once; digest, identity, review-plan, citation and investigation
    keys are byte-identical, pinned by
    `test_wp_04_2_moves_every_critique_key_and_no_other_key` (the contract-1
    keys are pinned in the test). One migration-register row.
  - The merge-rule ratchet is pinned under key 2 (`63dbfe…`). Its corpus gained
    12 rows (tag overlap, a shared list element, a shared value across one kind,
    a flow and a power in two units, and the extra detail that still merges);
    key 1's value is kept and noted as computed over the old corpus. Over the
    extended corpus WP-04.1's rule fingerprints as `73da95…` (recorded in the
    test), and this PR's rule before the review follow-up as `6aaf8a…`, so a rule change that
    forgets the bump still fails there.
  - No `_SCHEMA_VERSION` bump. A/B records: no change (above).
- **Re-baselined tests:** none of the pinned tests changed outcome. The listed
  ones (`test_duplicate_matrix`, `test_signature_measurements_carry_the_unit`,
  `test_signature_regexes_avoid_false_positives`,
  `test_feet_inches_keeps_both_halves_and_neither_goes_negative`,
  `tests/test_drawing_dedup_lifecycle.py`, `tests/test_drawing_ledger.py`,
  WP-04.1's tables, `tests/test_ab_findings_diff.py`, `tests/test_ab_sweep.py`)
  pass unchanged. Edited without changing an assertion: the module docstring of
  `tests/test_quantity_signature.py` and the docstring of
  `test_a_shared_name_is_not_a_shared_quantity` (both described the old rule).
  The ratchet gained key 2; key 1 is untouched.
- **Validation (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):**
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **2,927 passed, 2 skipped, 10 deselected** (230 s), identical to the
    WP-04.1 handoff.
  - **Reproduced first.** On the base code the 12 `N1 …` rows of `_CONFLICTS`,
    the 6 tag-conflict pairs and the Pass B pair all merged.
  - **Failing first.** The new tests, run in a `git archive` copy of
    `origin/main` (`d5d7084`) with only the test files replaced:
    **123 new tests: 42 failed on behaviour, 66 failed only because
    `signature_conflicts` did not exist (the axis-name checks), and 15
    passed.** The 15 pin what the fix keeps: 3 quantity corroborations, the
    two no-shared-quantity pairs, the six recorded limits, the equivalence
    beside a shared value, the Pass B fold of a one-sided reference, the A/B
    exact match with one added reference, and the flat-rule dominance test.
    Of the 250 existing tests in those four files, 249 passed and one failed:
    the merge-rule ratchet, whose corpus grew.
  - **After:** the new tests pass. Full suite **3,063 passed, 2 skipped,
    10 deselected** (215 s): the baseline plus 136 new tests (the 123 above
    and the review follow-up's 13), with the same two environment skips (IPv6
    loopback; chmod as root). Before the follow-up it was 3,050.
  - **Browser suite:** not run separately. No report JS, HTML or chat code
    changed; the browser tests ran inside the full suite above.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` is clean.
    F401/F811/F841 over the touched files shows two hits, both present on the
    base (WP-22.5 territory); none is new. `scan_secrets.py` is clean over 197
    tracked files, the new one included. `compileall src` passes.
  - **Cost of the rule:** a synthetic 1,800-finding, 40-sheet ledger ingest
    (25,879 signature comparisons), best of 3: 0.72 s against 0.66 s on the
    base code, about 2 µs per comparison. The signature's own regexes dominate
    either way.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). How often the retention and the limits occur on real drawings: every
  pair is synthetic (O-10). Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **A visible behaviour change, by design.** Findings that differ in a value
    beside a shared one no longer merge. A report can show more findings, and
    a pair the two critique reads disagreed on appears as two `SINGLETON`
    findings instead of one `REPRODUCED` one.
  - **Conservative retention** (pinned): the same pipe in two unit systems
    (`6 in` / `150 mm`) or one clearance in two units (`3 ft` / `36 in`)
    beside a shared value; two findings that each name a different extra
    reference; a loose-comma list against the tight list of the same sizes.
  - **Stray tags now matter more.** `_TAG_RE` reads the `x12` of a tight
    `24"x12"` as a tag `X12` (known since the 2026-09-22 verification). Under
    inclusion, that stray tag on one finding and a different extra reference
    on the other (`… at grid C-4`) keep apart two findings the old rule
    merged. Fixing `_TAG_RE` is a tag-tokenizer change, left out of scope and
    noted on WP-04.3, which bumps the same contract.
  - **Still merged** (pinned in `_RECORDED_LIMITS`): quantity roles (WP-04.3),
    a bare `12'` against `12'-6"`, and WP-04.1's partial signatures.
  - **Growth at the critique boundary:** a read whose conflicting value sits
    only in its text is lost to the ledger's comparison when another read wins
    the representative (B9; WP-03.5).
- **WP-04 acceptance check (README step 7.3).** "Demonstrated conflicting pairs
  never merge, equivalent supported spelling compares consistently, and
  existing fraction/sign/unit safeguards remain intact. Record any deliberate
  conservative duplicate retention in the evaluation fixtures."
  - Every matrix pair and matrix addition is pinned, and every conflicting one
    stays two findings, except **"repeated values in different roles"**, which
    merges (recorded limit). So the first criterion does not hold, and
    **WP-04 stays `todo`**, with WP-04.3 (M, Wave 2) added for roles.
  - Equivalent spellings compare consistently: `_EQUIVALENTS`, including a
    pair beside a shared value. The safeguards (fractions, signs, units,
    `psig` ≠ `psi`, feet-inches) pass unchanged, and conservative retention is
    recorded (`_CONSERVATIVE_RETENTION`, `_TAG_RETENTION`).
  - **How WP-04.1's partial signatures bear on it:** they are outside the
    plan's matrix (which names `4-6 in` and `2,4,6 in`, both read whole) and
    are not supported spellings, so they do not decide the acceptance. Each is
    still a way a real conflict can merge (`4 to 6 in` / `6 in`; two
    loose-comma lists ending in the same size; `20A` / `30A` on a shared
    `120V`), now pinned in `_RECORDED_LIMITS`, and a loose list against a
    tight one is now kept apart (retention). If the owner wants them closed,
    that is a tokenizer slice with a critique contract bump.
- **Re-checked (U31):**
  - The rule's live consumers are the critique's `_cluster` (through
    `merge_self_consistency`, whose output is cached), `Ledger.add` and
    `reconcile_post_anchor`, all through `_is_duplicate`. The A/B harness is
    the only out-of-process one. `merge_finding_groups` has no production
    caller (tests only). `prose_harvest` matches on `_token_overlap` only
    (N10, WP-09.2); `cross_qc._dedup_findings` keys on ids.
  - "The critique cache stores post-merge findings" still holds
    (`critique_cache_entry_from_result`).
- **Next:** WP-03.1 (Wave 1). WP-09.2 now waits only on WP-09.1; WP-03.5 waits
  on WP-03.1 and WP-03.4; WP-04.3 (Wave 2) is available.

### 2026-09-23 — WP-04.1: the quantity tokenizer behind the critical signature ([PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157))

- **Slice and IDs:** WP-04.1. B2, B3, B12 and N19. No `DECISIONS.md`
  contract is decided here. D-4 stays open (WP-10.4 completes it); this slice
  adds two migration-register rows and a note to D-4 (below). The WP-04
  package stays `todo`: its acceptance ("demonstrated conflicting pairs never
  merge") also needs WP-04.2 (N1).
- **What changed:**
  - **One tokenizer, rewritten as a scanner** (`critique._quantity_tokens`,
    behind `_measurements` and so `critical_signature`). It finds each number
    at a legal start, reads the whole quantity, and resumes past it, so no part
    of a quantity is read again on its own. The item-23 number-start rule is
    kept and extended: never after a letter, digit, `.`, `/` **or `,`** (B3),
    never after an alphanumeric-hyphen, and a sign is refused after `'` `"`
    **`°` `%`** (a hyphen there is a join: `90°-95°F` no longer yields
    `-95°f`).
  - **Hyphenated alpha units** (B2): `6-inch`, `6-in`, `6-in.` sign `6in`.
    `foot` and `gallon(s)` were missing outright and are added (`10-foot` is
    `10ft`, `100-gallon` is `100gal`).
  - **Thousands groups** (B3): a valid grouping is one number (`12,500` is
    `12500`, `1,500.5` is `1500.5`, `15,000` is no longer `0`). A tight comma
    run that is not a valid grouping is kept whole (`1,2,500 cfm` is
    `1,2,500cfm`), never its trailing fragment and never a guess.
  - **Degrees** (B12): `deg`/`degree(s)`/`°` are `°`; `deg F`, `deg. F`,
    `degrees F`, `degF`, `°F`, `° F` and `degrees Fahrenheit` are `°f` (C
    likewise). A scale is never inferred (`90°` stays `90°`). A tight `°F`
    keeps its old meaning whatever follows (`80°FDB`); a spaced or word-form
    scale needs a boundary (`45° Flange`, `90 deg flange` stay angles).
  - **N19:**
    - W×H sizes (`24x12`, `24 x 12`, `24×12`, `24"x12"`, `24x12-inch`,
      `600x300 mm`, `24x12x6`) with per-dimension units that must agree.
      Multiplication (`4 x 25 gpm`), mixed units (`6" x 12'`) and feet-inches
      W×H (`10'-6" x 12'-0"`) fall back to single tokens, keeping every
      dimension in the tight form too (review follow-up below).
    - Compact volts (`480V`, `24VAC`, `24VDC`) anywhere but a slope
      (`3H:1V`). Voltage pairs (`120/208V`, `208Y/120V`, `120/208 volts`) are
      one token, low first; `120/208 volts` used to sign as the fraction
      0.5769…volt.
    - Compact amps only with electrical context: a pole count after
      (`20A/1P`, `20A-2P`, `20A 3P`), an overcurrent device after
      (`breaker`, `bkr`, `cb`, `fuse(s)`, `fused`, `non-fused`,
      `disconnect(s)`, `mcb`, `mlo`, `ocpd`) unless a name precedes the number
      (`panel`, `room`, `grid`, `line`, `column`, `level`, `floor`, `type`,
      `detail`, `keynote`, `note`, `sheet`, `unit`, `area`, `zone`, `suite`,
      `bay`, `space`, `circuit` and abbreviations), or a rating label before
      (`MCA`, `MOCP`, `MOP`, `FLA`, `RLA`, `OCPD`, `breaker`, `bkr`, `cb`,
      `fuse(s)`).
    - Ranges `4-6 in`, `4 - 6 in`, `65-75°F`, `1,000-2,000 cfm` (a lopsided
      `4 -6 in` is a sign; a mixed number wins first).
    - Tight comma lists `2,4,6 in`.
  - **Memoized.** `_quantity_tokens` is an `lru_cache(4096)` keyed on the
    signature text, the whole input, so a hit is never stale. Measured on a
    synthetic 1,800-finding, 40-sheet ledger ingest (79,114 signature calls):
    old regex 1.35–1.52 s, new scanner uncached 1.86 s, cached 0.91–0.95 s.
  - **The representation WP-04.2 consumes** (documented at the tokenizer, and
    pinned by `test_every_token_is_a_value_followed_by_a_unit`): every token is
    `<value><unit>`, unit canonical and lowercase (empty for a unitless size).
    The value is one canonical number, or ONE composite: a list `2,4,6`, a
    range `4..6` (low first), a size `24x12` (written order), a voltage pair
    `120/208` (low first). A composite is compared whole and never split:
    splitting `1,2,500` would recreate the trailing fragment plan WP-04
    step 2 forbids.
  - **Critique cache term.** `digest_cache._CRITIQUE_CACHE_CONTRACT = 1`,
    folded as `critique_contract=1` inside both `critique_cache_key` and
    `critique_cache_key_level1` (not caller-supplied, so a probe and a store
    cannot disagree). No `_SCHEMA_VERSION` bump. The new term makes every
    critique key new, so four statements that a key stays byte-identical to
    keys written before profiles or F-01 existed became false: two sentences
    in `critique_cache_key`'s docstring and two comments in `critique.py`.
    They now state what was true when those features landed.
  - **A/B harness:** `RECORD_CONTRACT_VERSION` 2 → 3; `_signature_conflicts`
    is untouched (WP-04.2 replaces it).
  - **Review follow-up (Codex P1 on this PR).** A tight W×H candidate that was
    not a size lost its second dimension: the scanner resumed after the first
    number, and a number may not start right after `x`. So `6"x12'` signed
    only `6in` and `4x25 gpm` signed nothing (the spaced forms were fine; the
    base code lost them too). `_read_quantity` now hands back where the next
    dimension starts, and the scanner reads it in place (`_NUMBER_AT_RE`, the
    same number grammar without the start guard). `6"x12'` is `{6in, 12ft}`,
    `4x25 gpm` is `{25gpm}`, `10'x12'-6"` keeps its `12ft`. A pair such as
    `6"x12'` / `6"x14'` still shares `6in`, so under today's rule it can still
    merge: that is N1 (WP-04.2).
  - **Docs:** CHANGELOG (Fixed: B2, B3, B12, N19, with the one-time critique
    re-run as the visible cost), CLAUDE.md (the ledger paragraph's signature
    description, I-6 and the new term), README (the ledger section's
    measurement passage, which appeared twice verbatim, now appears once and
    carries the new spellings; the critique cache paragraph names the one-time
    re-run).
- **Contracts decided:** none. D-4 (open) gains a note: the critique's
  contract term now exists, so WP-04.2 and WP-01.4 bump it rather than adding
  a second term.
- **Cache/schema effects:**
  - Critique cache, both levels: every entry written before this slice misses
    once (new key term). Nothing is deleted. The next exhaustive run
    re-critiques every sheet once; digests, identity, review plan, citation
    and investigation entries are untouched, pinned byte-for-byte by
    `tests/test_drawing_cache_identity.py::test_wp_04_1_moves_every_critique_key_and_no_other_key`.
  - A/B arm sidecars: a v2 record is refused as `RECORDS_STALE_CONTRACT`.
  - Two migration-register rows.
- **Re-baselined tests:** none. Every existing test passed unchanged,
  including `test_duplicate_matrix`, `test_signature_measurements_carry_the_unit`,
  `test_signature_regexes_avoid_false_positives`, the four item-23 tests,
  `tests/test_ab_findings_diff.py` and `tests/test_ab_sweep.py` (whose stale
  contract test uses `RECORD_CONTRACT_VERSION - 1`).
- **New guard:** `test_the_critique_contract_is_pinned_to_the_merge_rule`
  fingerprints the merge rule (signatures, the pairwise `_is_duplicate` matrix
  and a self-consistency merge over a fixed 34-finding corpus) and pins it per
  contract value. The base commit's rule fingerprints differently
  (`70a2e0…`, recorded in the test), and so does this PR's head before the
  review follow-up (`715fa2…`), so a rule change that forgets the bump fails
  there.
- **Validation (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):**
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **2,726 passed, 2 skipped, 10 deselected** (238 s), identical to the
    WP-01.2 handoff.
  - **Reproduced first.** On the base code: `Provide 6-inch drain` signed
    nothing; `12,500 cfm` and `1,500 cfm` both signed `500cfm`; `15,000 cfm`
    signed `0cfm`; `90 deg F` and `90 deg C` both signed `90deg`; `24x12`,
    `20A`, `480V` and `4-6 in` signed nothing; `2,4,6 in` signed `6in`; and
    `120/208 volts` signed `0.5769230769230769230769230769volt`.
  - **Failing first.** The 201 new tests, run in a full copy of the base
    commit with only the new test files added: **125 failed, 76 passed**
    (`tests/test_quantity_signature.py` 117/76; all four cache-identity tests
    and all four A/B tests failed). The review follow-up's five tests, and the
    ratchet, also failed on this PR's head before it. The 76 pin what the fix
    keeps: the item-23 safeguards, the negative corpus, the spellings that
    already signed, and merge outcomes the old rule already got right
    (`90°F`/`90°C`, `90°`/`90°F`,
    `1/2"`/`2"`, `-6 in`/`6 in`, `2 1/2"`=`2.5"`, the three shared-name pairs,
    and `2,4,6 in`/`2,4,8 in`, blocked before only because the trailing
    fragments differed). One pair (`10'x12'` against `10'x14'`) was blocked on
    the base code only by the stray `x12` tag, so the test uses the spaced
    form, which failed.
  - **After:** the 201 new tests pass. Full suite **2,927 passed, 2 skipped, 10 deselected** (237 s), the baseline
    plus the 201 new tests, with the same two environment skips (IPv6
    loopback; chmod as root).
  - **Browser suite:** not run separately. No report JS, HTML or chat code
    changed; the browser tests also ran inside the full suite above.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` is clean.
    F401/F811/F841 over the touched files shows two hits, both present on the
    base (WP-22.5 territory); none is new. `scan_secrets.py` is clean over 196
    tracked files, the new one included. `compileall src` passes.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawing text: the negative corpus is synthetic, written from
  common drawing conventions, not mined from a real set (O-10). Windows is
  covered by this PR's CI.
- **Risks and residual gaps:**
  - **N1 (WP-04.2).** One shared value still makes two findings compatible,
    so a conflict hidden by a shared value can still merge: `6 in … 100 psi`
    against `4 in … 100 psi`, `12'-6"` against `12'-8"` (both `12ft`), and
    two lists written with a unit on every element that share one element.
  - **Partial signatures that remain, by decision:**
    - loose-comma lists (`2, 4, 6 in` keeps only `6in`): a comma and a space
      are prose punctuation as often as a list separator (`column 4, 10 ft`);
    - `to` ranges and `and`/`or` lists (`4 to 6 in`, `4 and 6 in`) keep only
      the far end;
    - a bare `20A` with no electrical context (`20A 120V circuit`) is
      unsigned, and a `V`-suffixed room or grid label (`101V`) would sign as a
      voltage (V suffixes are not a room or grid convention);
    - `UL 94V-0` signs as `94volt`;
    - a number after `/` still never starts (item 23), so `30A/2P/240V` loses
      `240V` and `80°FDB/67°FWB` loses `67°f`;
    - Unicode dashes, primes and vulgar fractions are not folded (N13 /
      WP-05.1's shared normalizer); `24×12` is handled because the size
      separator is in scope.
  - **The `in` preposition** remains the tokenizer's oldest false positive
    (`see pages 4-6 in the manual` now signs `4..6in`, as `6 in the manual`
    signed `6in` before).
  - **One-time cost:** the first exhaustive run after upgrade re-critiques
    every sheet (one cold critique pass).
- **Re-checked (U31):**
  - "The critique cache stores post-merge findings, and only it depends on the
    signature": `critique_cache_entry_from_result` stores merged findings; the
    ledger (Pass A and B) is never cached; `prose_harvest` matches on
    `_token_overlap` only; `cross_qc._dedup_findings` keys on ids.
  - "`_measurements` has no caller outside critique.py" (grep).
- **Next:** WP-04.2 (compatibility rule; bump `_CRITIQUE_CACHE_CONTRACT` 1 → 2
  and pin the new fingerprint). WP-05.3 now waits only on WP-05.2.

### 2026-09-23 — WP-01.2: the digest never admits a read the model did not finish ([PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156))

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
    refusal or a stream that ended early: once if the re-read finishes, and on
    every run while it keeps failing. That is by design, since an unfinished
    read is never served.
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
