# Remediation progress tracker

**Next up:** WP-06.2 is done (PR pending): both cross-QC paths address sheets by the same host handles (`S001` …, in source order) with each sheet's id beside its handle, and one resolver binds every reply (a handle, else an id exactly one sheet carries); an id more than one sheet carries is refused and counted (`legs_ambiguous_label` / `facts_ambiguous_label`, an observational stage warning), never bound to the first. The whole-set path grounds against the uncapped text through the sharded validator (U8; plan Step 6 reverses WP-03A's scope), its claims are rebound through the handles, the arithmetic auditor refuses an id two sheets carry (`arithmetic_ambiguous_sheet`), the prose synthesis map sends one to the set-level path, `critique._leg_targets` names pages, and the user-turn framing rides the cross-QC key (K2). **D-8 is decided.** Cross-QC contract 8 → 9, A/B `RECORD_CONTRACT_VERSION` 5 → 6; the critique contract and its fingerprint are unchanged (the owner's rules, eight choices over two rounds, measured first). Measured: 0 of 43 whole-set bindings, 177 arithmetic lookups and 50 leg-bearing merge decisions moved; the whole-set grounding dropped 0 suite items for a paraphrase. In queue order the next slice is Wave 2 `WP-06.3` (cross-QC terminal honesty); WP-10.1, WP-10.2, WP-10.3, WP-10.4, WP-03.4, WP-07.3 and WP-11.3 (Wave 2) are available too. **WP-01 stays open** (the owner's decision, 2026-09-30): its acceptance waits on WP-06.3 (cross-QC), WP-12.6 (the citation cache gate) and WP-13.4 (the investigation). Still open for the owner from WP-01.5: whether Opus 5.5 and Sonnet 5.5 get host refusal routes. Each of WP-06.3, WP-13.4, WP-14.1, WP-14.2 and WP-14.3 starts from its `test_recorded_limit_*` tests (named on its row; WP-14.3 also has one in `tests/test_batch_refusal_recovery.py`). WP-02 is not done: WP-02.4 (the canaries are written there; running them is O-4) and WP-02.5 remain. WP-17.1 (Wave 4, cancel; decides D-5), WP-16.3 and WP-18.6 (Wave 4) are unblocked. WP-09 is not done: WP-09.3 (N32, Wave 3) remains. WP-06 is not done: WP-06.3 (Wave 2) is available, and WP-06.4 still waits on WP-03.4. WP-13.1 now carries the investigation tools' id map (D-8 names it). WP-07 is not done: WP-07.3. WP-03 is not done: WP-03.4, WP-03.5 and WP-03.6 remain (Wave 2); WP-03.5 also carries the measured N30 exposure of cross-QC's same-pair conflicts, and WP-03.4 has two WP-04 D-3 inputs. WP-11 is not done: WP-11.3 remains. WP-16 is not done: WP-16.3 remains. First check the open PRs ([`README.md`](README.md), step 1); [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot) and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0 support) are open and not remediation slices. Before the next stable tag, the owner should look at O-5.
**Last updated:** 2026-10-01 by the WP-06.2 session (PR pending).

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
| WP-01 | Response terminal states and truthful stage completeness | P0 | 01.1–01.8 | todo: all eight slices done; acceptance waits on WP-06.3, WP-12.6, WP-13.4 (the owner's decision, 2026-09-30; the plan's WP-01 Acceptance note) |
| WP-02 | Faithful SDK, streaming, batch and network test boundaries | P0 (enabling) | 02.1–02.5 | todo |
| WP-03 | Durable finding identity and lossless, symmetric merging | P0 | 03.1–03.7 | todo |
| WP-04 | Engineering quantity and tag comparison | P0 | 04.1–04.4 | done (2026-09-30: every slice done and the plan's WP-04 Acceptance holds, checked by WP-04.4; the owner's decision: done, with the two shapes left unread recorded as limits) |
| WP-05 | Robust anchoring and consistent quote evidence | P0/P1 | 05.1–05.3 | done (2026-09-30: every slice done and the plan's WP-05 Acceptance holds, checked by WP-05.3) |
| WP-06 | Source-safe cross-QC and claim-preserving deduplication | P0/P1 | 06.1–06.4 | todo: 06.1 and 06.2 done; WP-06.3 and WP-06.4 remain (WP-06.4 waits on WP-03.4), and the N30 note stays WP-03.5's |
| WP-07 | Arithmetic operand trust and strict numeric parsing | P0 | 07.1–07.3 | todo |
| WP-08 | Reference, naming, sheet-ID and drawing-index auditors | P1 | 08.1–08.5 | todo |
| WP-09 | Prose harvesting without empty findings or unnecessary duplication | P1 (N10 is P0) | 09.1–09.3 | todo |
| WP-10 | Complete cache keys, faithful metadata and targeted migration | P0/P1 | 10.1–10.4 | todo |
| WP-11 | Inventory-driven source and page fault isolation | P0/P1 | 11.1–11.3 | todo |
| WP-12 | Citation parsing, full-text editions and honest adoption evidence | P1 | 12.1–12.6 | todo |
| WP-13 | Investigation budgets, replay and evidence finalization | P1 | 13.1–13.4 | todo |
| WP-14 | Attempt-level provenance, usage and pricing | P1 | 14.1–14.6 | todo |
| WP-15 | Calibrated estimates and preflight efficiency | P1/P2 | 15.1–15.5 | todo |
| WP-16 | Run-scoped clients and credential lifecycle | P1 | 16.1–16.3 | todo |
| WP-17 | Cancellation, durable job records and safe resumption | P1 | 17.1–17.4 | todo |
| WP-18 | Remote upload and local work-directory ownership | P1/P2 | 18.1–18.6 | todo |
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
| WP-07.1 | Occurrence-aware, sheet-grounded operand support; provenance decided after anchoring; a fabricated quote or unresolved sheet is never DETERMINISTIC (N3) | M | — | done | [PR #163](https://github.com/Abe-Borg/drawing-analyzer/pull/163), 2026-09-23. **Rule decided with the owner (three choices, measured first):** a mismatch is TEXT_EXTRACTED / DETERMINISTIC only when the claim resolved to a sheet, its quote anchored there EXACT or FUZZY by a numerically vetoed method (`anchor.numbers_grounded`, fail-closed on method; never TILE or UNANCHORED), and the terms and the stated value together fit, one occurrence each, the numbers that both the quote and the sheet's words under the matched span print (`arithmetic._operands_grounded`, per value the smaller count; `anchor.resolve_anchors(matched_text=)`). Every mismatch is built MODEL_TRANSCRIBED and promoted after the auditor's own anchoring pass; a failure while deciding, or anchoring one sheet, leaves it UNCERTAIN. Ids, text, severity and the verification note's wording are unchanged; no cache or key effect. Tests: `tests/test_arithmetic_operand_grounding.py`; the three pinned `audit_arithmetic(..., [])` tests re-baselined with sheet words |
| WP-07.2 | Strict numeric tokens (tag and sheet-id digits, hyphen-as-minus, `1e3`) and host-side relationship checks (A8) | M | WP-07.1 | done | [PR #164](https://github.com/Abe-Borg/drawing-analyzer/pull/164), 2026-09-23. **Rules decided with the owner (three choices, measured first):** (1) scientific notation is rejected (`1e3`, `2.5e-2`, `2E1` are not one value; a term spelled that way makes its claim unusable); (2) digits glued after a letter, with or without a hyphen, are a tag's (`FP101`, `M-101`, `AHU-2`, `A1.01`) and a hyphen after a letter is never a minus sign; letters after a number are its unit (`20A`, `150GPM`) unless digits follow them directly (`24x12`, `2P20A`, `10A1`, `100m2`: refused), in `parse_number` (`_NUMERIC_TAIL_RE`) and the scanner (`_head_denies`) alike, with Unicode dashes, the fraction slash, `×` between digits and glued vulgar fractions refused the same way; (3) `arithmetic._relationship_grounded`: the quote AND the sheet's words under the span each print the claim as one equation (`_equations`: the result is the first number after `=` or TOTAL, the operands are exactly the terms, every join is `+` for a sum or `x`/`×`/`*` for a product; an operator-less list is a sum only with TOTAL). Every change only refuses, so no surviving finding's text or id moves; no cache key changes (one stored-claims residual in the migration register). Tests: `tests/test_arithmetic_tokens_and_relationships.py`; no pinned test re-baselined |
| WP-05.1 | Cross-QC grounding: a real match for every non-empty quote at word boundaries; no text means unavailable evidence; one normalizer shared with `anchor`; `_CROSS_QC_CACHE_CONTRACT` 3→4 (B5, N12 cross-QC part, N13) | M | — | done | [PR #165](https://github.com/Abe-Borg/drawing-analyzer/pull/165), 2026-09-23. **Rules decided by the owner (four choices, measured first):** (1) a match covers whole source words: it may start and end only on a word's core (`anchor.word_core`: the whitespace-delimited word without leading `( [ { < " '` or trailing `) ] } > , ; : . ! ? " '`); (2) the rule is defined once, in `anchor.py`, for WP-05.2 to apply to `_Stream`'s words; (3) the evidence is normalized one source word at a time with the unchanged `anchor._normalize` (`anchor.SourceWords`, exactly `_normalize(text)`), and `cross_qc._norm_for_match` is `_normalize`, so the tile join folds the same way; (4) any length gets a real match (no floor). `classify_quote_evidence` asks in the plan's order: no quote, no usable text (`_sheet_is_textless`, now on the normalizer), the match, the word-free tile, NOT_MATCHED. Accepted cost: a tag inside a list written without spaces (`P-1,P-2`) does not match. `_CROSS_QC_CACHE_CONTRACT` 3 → 4 (one migration-register row; retires the WP-03.3 and WP-07.2 stored-claims residuals). No anchor changes: `_normalize` is untouched and every anchor test passes unchanged. Tests: `tests/test_cross_qc_grounding.py`; `tests/test_evidence_visual.py::test_a_recovered_finding_reaches_verification_and_investigation` extended to `P-1`, `AHU-1`, `M-101`; the three contract tripwires re-baselined |
| WP-05.2 | Anchor punctuation folding and a source-word-boundary rule (B4: `PSI,`, `NOTE 3:`, `(568 L/MIN)`; N12 anchor part: `VAV-2` in `VAV-2-1`) | M | — | done | [PR #166](https://github.com/Abe-Borg/drawing-analyzer/pull/166), 2026-09-24. **Rules decided by the owner (four choices, measured first):** (1) whole source words in every tier: EXACT and the sub-phrase tier match through `anchor.SourceWords` (the WP-05.1 `word_core`, the matcher cross-QC uses), a fuzzy window starts and ends on whole words (`_Stream.on_word_edges`), and inside a window a quote's measurement may not match part of a sheet word (`anchor._measurements_whole`); measured: a boundary on EXACT alone moves every refused match to the window at 100% overlap, and window edges alone miss the 17-token note; (2) `anchor.fold_word` folds leading `( [ {` and trailing `) ] } , ; : . ! ?` off every word, sheet and quote alike (never `"` `'` `<` `>` `%` `/` `-` or a leading `.`); (3) cross-QC grounds through the same matcher, and its fact-tile join keys on the same folded form (Codex review, fixed in this PR), `_CROSS_QC_CACHE_CONTRACT` 4 → 5 (one register row); (4) a folded match keeps EXACT/`exact`, so `numbers_grounded` holds. `anchor._normalize` untouched. Tests: `tests/test_anchor_whole_words.py` (incl. one agreement table through both matchers). Re-baselined: three arithmetic tests (given the case they model), the three contract tripwires, and two WP-05.1 tests (its reference matcher and its join-key normalizer test). Recorded limits: a letter-only tag (`VAV-A` in `VAV-A-1`) in a long window; a sub-phrase dropping a unit printed as its own word; B4's four character-stream cases (WP-05.3) |
| WP-06.1 | Cross-QC prompt says category `question` with severity `low`; invalid-field counters on both paths; candidate duplicates go to the ledger instead of being destroyed (B6, N2) | S/M | — | done | [PR #167](https://github.com/Abe-Borg/drawing-analyzer/pull/167), 2026-09-24. **Rules decided by the owner (four choices, measured first):** (1) a refused item is **observational**: a stage warning after the status-deciding ones, the stage keeps its status, the result is cached with its counts (D-2 note); (2) the counts are a **separate record**, `CrossQCInvalidCounts` (`CrossQCResult.invalid`), filled on both paths, so `discards is None` keeps meaning "grounding not measured" on the whole-set path; `run_manifest.json` carries `cross_qc_invalid`; (3) each refused item counts **once, under the first check it fails** (`cross_qc._invalid_field`, shared by both validators: not an object, category, severity, text), and a whitespace-only fact quote is dropped and counted `facts_no_quote` (the WP-05.1 note, resolved); (4) **only findings identical in every field collapse** (`_drop_exact_repeats` replaced `_dedup_findings`), and the ledger decides the rest. The persona asks for category `question` with severity `low`; validation is unchanged. `_CROSS_QC_CACHE_CONTRACT` 5 → 6 beside the prompt edit (two changes, two mechanisms; D-4 note, one register row). Tests: `tests/test_cross_qc_validation_and_dedup.py`. Re-baselined: the three contract tripwires only. Recorded limits: a re-report phrased apart stays two ledger entries (WP-06.4); a terse same-pair conflict folds in the ledger (N30, WP-03.5) |
| WP-09.1 | Boilerplate filter with repeatable qualifiers; negation-aware synthesis conflict extraction (B11, N11) | S | — | done | [PR #168](https://github.com/Abe-Borg/drawing-analyzer/pull/168), 2026-09-24. **Rules decided by the owner (six choices, measured first):** (1) filler is a **closed vocabulary**: `_TRIVIAL_RE` drops an item only when the whole item is `none` / `n/a` / `nothing [further]` or `no` + up to two listed modifiers + a listed noun, with an optional listed label and up to four listed qualifiers in any order; any other word keeps it; (2) **one vocabulary, two anchored forms**: the same word lists build the whole-item filter (`_split_items`, the one filter site) and the synthesis assurance spans (`_ASSURANCE_RE`); (3) a synthesis statement is an **assurance** (`_is_assurance`) only when every conflict signal sits inside an assurance span ("no [modifiers] <conflict noun> [between <sheet ids, discipline names, listed words>] [were] <detection word>", "nothing inconsistent", "there are no <noun>", "found no <noun>", a conflict label right before one), the noun is the head, and every other word is a listed frame word (sheet ids, discipline and document names, a few function words; since the Codex review, which found a contrast list missing `yet`, `nevertheless` and `while`); (4) synthesis items are split **per section** with the report's `split_into_sections` (N31, found and fixed here), and a heading that is not a listed label is an item of its own (Codex review: a whole-line bold conflict was lost); (5) dropped assurances are counted in `HarvestResult.assurances`, observational like `filtered` (D-2 note); (6) ordinals count the kept items, so dropping filler before a real item moves that item's `prose_item_id` once. No cache contract, key, prompt or schema moves (`_HARVEST_CACHE_CONTRACT` stays 1). Tests: `tests/test_prose_filler_and_assurances.py` (207). No pinned test re-baselined; no fixture item changed decision. Recorded limits (kept, a paid call as before): wording outside the lists ("No duct conflicts noted.", "No items requiring coordination.", "M-101 does not conflict with P-101.", "Checked M-101 against P-101 for conflicts; none were found.") |
| WP-09.2 | Prose matching rejects signature-incompatible candidates; per-item outcome counters; labelled paraphrase corpus (no threshold change) (N10, U11) | M | WP-04.2, WP-09.1 | done | [PR #169](https://github.com/Abe-Borg/drawing-analyzer/pull/169), 2026-09-24. **Rules decided by the owner (eight choices, measured first):** (1) `_match_entry` refuses a candidate at or above 0.7 whose critical signature conflicts with the item's (`prose_harvest._veto_axes`: `critique.signature_conflicts` over `critique.critical_signature`, the one rule), signing "text against text": the item from its text and its synthesis legs, the candidate from its text, quote and legs with its `anchor_hint` set aside (measured: a bare-text item refused 5 of the suite's 17 matches, its own quote-less twins, and broke two pinned tests; the item taking the candidate's placement switched the polarity axis off against every SHEET entry); (2) the next-best compatible candidate wins; (3) a refused item is a straggler (a structuring call or a degraded entry; the calls accepted); (4) N32 goes to its own slice, WP-09.3; (5) every enumerated item has one `ProseItemOutcome` (`HarvestResult.outcomes`: channel, outcome, call, folded, refused), the counters are the number of items with each outcome (`_record_outcome`; an ingest that raised used to count one item structured and degraded, fixed), and `vetoed`, `folded`, `filtered_focus` and a per-channel `by_channel` table reach `prose_accounting` (`run.log` one line per channel, `run_manifest.json`), all observational (D-2 note); (6) suppressed items are counted per channel, focus filler included whether or not focus is harvested (new `filtered_focus`), with no ids; (7) a straggler the ledger folds keeps its outcome and is counted `folded`; (8) the labelled corpus pins its numbers at 0.5 to 0.9 with and without the veto, `_MATCH_OVERLAP == 0.7` asserted. No cache contract or key moves (`_HARVEST_CACHE_CONTRACT` stays 1). Tests: `tests/test_prose_match_signatures.py`, `tests/test_prose_paraphrase_corpus.py`, `tests/test_drawing_acceptance.py::test_gauntlet_prose_outcomes_are_exact`. No pinned test re-baselined; no fixture changes outcome (instrumented). Recorded limits: a SHEET absence with no absence word takes a presence item; a refused presence item that degrades to a SHEET entry can fold into an absence entry in the ledger (`_is_absence`); near misses the signature cannot read (corpus) |
| WP-01.3 | Digest partial reads: a raised-cap retry never loses the first read; findings from an errored, refused or truncated digest are labelled or held out of the ledger (N15, N16) | M | WP-01.2 | done | [PR #170](https://github.com/Abe-Borg/drawing-analyzer/pull/170), 2026-09-24. **Rules decided by the owner (seven choices, two rounds, measured first):** (1) one rank decides which read a sheet keeps, on both transports (`digest.keep_digest_read`, over `digest._read_rank`): finished > a partial read with content (prose or findings) > refused > nothing (empty, errored envelope, a raise); the later read wins a tie, so of two partial reads the raised-cap one is kept and of two content-free reads the fresher error; reads are never mixed (I-2); every attempt's usage is kept; applied by the real-time retry in `digest_sheet` and by `batch_digest._replace_result_with_attempt_history` at all five sites; (2) the kept read's error names the discarded attempt (`; retry: <its error>`, `; retry failed: <error>` for a raise, the batch direct rescue included, `; N retries, the last: …` for several); (3) the stalled-batch harvest holds a partial read (`digest.is_partial_read`) as the sheet's result while the sheet is still rescued (rescue list from `harvest.resolved`); (4) N15: an unfinished read's findings are held out of the review (`models.review_findings` / `held_out_findings`), listed in the sheet's own export file and report card, and counted observationally (`ctx.digest_findings_held_out`, a digest-stage warning, `findings_held_out` on `SHEET_DIGESTED` and the run.log *Sheets* line, the manifest's `digest_findings_held_out`; D-2 note). No cache contract, key, prompt or schema moved (only finished reads are cached, pinned for both transports). Tests: `tests/test_digest_partial_reads.py` (75). Re-baselined: `tests/test_drawing_digest.py::test_a_failed_retry_keeps_the_truncated_first_read` (its error gains the raise's text, approved). Found and fixed here beyond the request's description: a batch resubmission that comes back as an errored envelope also wiped the first read, and the harvest dropped a cut-off read with prose. Found, not fixed: the advisory set-identity corpus reads an errored sheet's text (WP-01.6 note) |
| WP-01.4 | Critique: `max_tokens`/refusal/unknown terminal states are not completed reads on either transport; critique-only cache contract term (N4 critique) | M | WP-01.2 | done | [PR #171](https://github.com/Abe-Borg/drawing-analyzer/pull/171), 2026-09-24. **Rules decided by the owner (six choices, two rounds, measured first):** (1) a critique read the model did not finish (D-1: anything but `end_turn`/`stop_sequence`; the critique declares no tools, so `tool_use`/`pause_turn`/`compaction` too) keeps **nothing**, like a malformed read: no findings, no claims for the arithmetic auditor; its tokens stay billed. The one fix site, `critique.outcome_from_message`, reads the stop reason first on both transports; (2) the critique stage adopts **D-2's item rule**: its items are reads (eligible = sheets x requested reads, judged = finished with a valid findings object; a cache hit counts all its reads), COMPLETE only when every read was judged, FAILED when none was (it read PARTIAL), else PARTIAL; a coverage line leads the warnings and `critique.critique_shortfall` names each short sheet (`pipeline._CritiqueReadTally`, a `read_tally` sink on `_run_critique_stage`). This closes the gap: a sheet whose surviving read shipped findings kept `error=None` and read COMPLETE, cached nothing and was re-billed every warm run; (3) the per-sheet usage record agrees (COMPLETE only when every read counted, FAILED when none did, else PARTIAL); (4) one ladder: `digest.digest_terminal_error(..., noun="critique")` (`empty critique (…)` kept, the digest's wording unchanged); (5) no stored per-read stop reasons; (6) the stage's items are reads (eligible -> judged). `digest_cache._CRITIQUE_CACHE_CONTRACT` 2 -> 3 (one register row; the unchanged merge-rule fingerprint pinned under 3; the contract-2 keys pinned). `FINDINGS_PARSE_OK`, `_SCHEMA_VERSION` and the merge rule unchanged. Tests: `tests/test_critique_terminal_outcome.py` (128), the WP-01.4 section of `tests/test_drawing_cache_identity.py` (2). No pinned assertion re-baselined (one data row: the fingerprint under 3). Instrumented over the whole suite: only critique stage items (reads), 12 all-failed critiques PARTIAL -> FAILED and their usage records moved |
| WP-11.1 | Per-source and per-page fault isolation in the render and prescan iterators; the inventory is the page denominator; every expected page gets an outcome (R1 core) | M | — | done | [PR #172](https://github.com/Abe-Borg/drawing-analyzer/pull/172), 2026-09-24. **Rules decided by the owner (six choices, two rounds, measured first):** (1) the pages a run owes are the inventory's, built without reopening a file (`render.inventory_sheet_refs`, `InputInventory.expected_page_counts`), and D-8's page part is decided narrowly (a sheet the run owes is one page `(source_id, page_index)` of an accepted inventory document); (2) both iterators take `expected_pages`: a source that will not open again fails every expected page with one shared `render.SourceUnreadableError`, a page past the source's current end fails with `render.PageNotInSourceError`, and a source none of whose pages is wanted is never opened; (3) an unread page is a typed record (`models.UnreadPage`: `ctx.unread_pages`, `unread_pages` in `run_manifest.json`, a `NOT READ` line in run.log's Sheets section) plus one `PAGE_UNREAD` event, so every expected page ends with exactly one per-page event; a page neither yielded nor reported gets one too; (4) `ctx.errors` and the digest stage's errors say a source-level failure once per source, a page failure once per page; (5) the prescan is best effort: what it cannot scan goes to the render path (the one reporter), and `_GeometryOmissionSink(order=)` adds a routed page's geometry in page order; (6) a source with more pages is read for its inventoried pages and named in one run error (the stage stays COMPLETE, the run PARTIAL), fewer pages fail the missing ones; labels keep the inventory's count, the render identity the opened file's; (7) the critique takes the same refs (`list_sheets` only as a direct caller's fallback): a source lost after the digest is critiqued from the spooled renders or retained uploads, and on Hybrid each page it cannot obtain is named with the reason. No key, prompt or schema moved (`tests/test_drawing_cache_identity.py` unchanged); `run_manifest.json` gains `unread_pages`. Tests: `tests/test_source_page_isolation.py` (77). No pinned test re-baselined; outside the new file only the critique's degraded line in the 2 fixtures with an unrenderable page (it now names the reason) and 3 `PAGE_UNREAD` events moved (instrumented) |
| WP-11.2 | Digest-phase containment: completed paid digests, journal and manifest always ship; uploads and spool released on every exit (R1) | M | WP-11.1 | done | [PR #173](https://github.com/Abe-Borg/drawing-analyzer/pull/173), 2026-09-25. **Rules decided by the owner (eight choices, two rounds, measured first):** (1) an unexpected `Exception` inside the digest phase stops the phase, not the run: the digests in hand ship (both transports fill a `collected` list; real time keeps each read in flight), every page not reached is an `UnreadPage` (`not read: the digest phase stopped early (<Type>)`), and `_stopped_run_context` ends the run after the phase: no later stage makes a call, reopens a source or writes a reviewed PDF, none is recorded, the read sheets' digest findings are ledgered offline (DA-012), `RUN_END` carries `stopped="digest"`, and the context goes to the normal exporter; (2) the digest stage reads FAILED whatever was read (D-2 note); (3) the collect side harvests what finished, then releases (`_abandon_after_collect_error`; a batch it cannot cancel keeps its files); (4) `Exception` only: `KeyboardInterrupt` and `SystemExit` still end the run (D-5 input note); (5) one run-level line after the inventory's, type name only, path-free (`_digest_phase_line`); (6) the phase's unreached pages carry that reason and no per-page line; (7) the reads in flight are kept; (8) the line says what was kept ("the N page(s) read are exported and cached, so a re-run does not pay for them again"). Also: the level-1 store runs over the digests in hand (a re-run renders and reads only the rest); `submit_drawing_batch` gains the DA-034 outer guard (`slots_out=`), `collect_drawing_batch` a guard over its whole body (`results_out=`); `@_with_run_release` releases the render spool and the retained uploads on every exit. Review round 1 (Codex): both level-2 cache writes are advisory (a raising `put` lost the paid read on real time and every billed item in the batch collect and harvest), the accounting is recorded page by page (one bad usage record dropped every later sheet's usage), and the line's cache promise needs a level-1 store that did not fail. No key, prompt, schema or manifest key moved. Tests: `tests/test_digest_phase_containment.py` (36). No pinned test re-baselined; outside the new file only one release of zero files moved (instrumented) |
| WP-16.1 | Key store: BOM-safe load, repair of BOM values already in the keyring, shape check, migration that never deletes the only good copy (G3) | S/M | — | done | [PR #176](https://github.com/Abe-Borg/drawing-analyzer/pull/176), 2026-09-28. **Rules decided by the owner (eleven choices, three rounds, measured first):** (1) one normalizer, `core.api_key_format.normalize_api_key`: whitespace and Unicode format characters (Cf) stripped from both ends only; (2) one shape check, `looks_like_api_key`: a full match of the diagnostics redactor's `sk-ant-[A-Za-z0-9_-]+`, now one shared constant (`ANTHROPIC_KEY_RE`), no length floor; (3) it applies to migration, save and the keyring; (4) a key file that fails it is not used, not migrated and kept, and the next location is tried; (5) a keyring entry stored un-normalized is rewritten through the verified round-trip (if that fails, the entry is left and the clean key is used for the session); (6) a keyring entry that fails the check is not served and not deleted; (7) a migration deletes only the files that hold the key it verified (`_migrate_legacy_file_key` → `_remove_key_files_holding`), and save keeps its every-location rule (pinned); (8) a UTF-16 file is decoded, and an unreadable, non-UTF-8 or >64 KiB file is skipped and named; (9) every note (`KeyNote`, from `load_api_key_with_notes`; `load_api_key_from_file` unchanged) goes to the GUI activity log and the diagnostics log, and names the file, never the value; (10) the status stays "loaded"/"no key"; (11) the GUI field shows the normalized value (real Tk measured: no re-entry). No cache, key, prompt or schema moved. Tests: the WP-16.1 sections of `tests/test_api_key_store.py` (66) and `tests/test_gui_lifecycle.py` (8). No pinned test re-baselined; only the 12 store tests reach the store (instrumented), and their events are unchanged |
| WP-16.2 | Run-scoped client snapshot passed from `gui._worker`; key entry disabled while busy; the key is no longer written to `os.environ` (G2) | M | — | done | [PR #177](https://github.com/Abe-Borg/drawing-analyzer/pull/177), 2026-09-29. **Rules decided by the owner (eleven choices, three rounds, measured first):** (1) `_on_process` reads the applied key once, before the cost dialog; `_worker(api_key=)` builds one real `anthropic.Anthropic` with `client.new_client` (the construction `get_client` now uses too) and passes `client=`, off the UI thread (the first build imports the SDK: 0.6-0.7 s measured); (2) the applied key (`_applied_key`) is the normalized field value only, started from the launch key; (3) an inherited `ANTHROPIC_API_KEY` is read at launch, then removed from `os.environ`; the GUI never writes it; (4) the exports read the applied key (Export All at the click), store fallback unchanged; (5) the key entry only is disabled while an analysis runs (Show stays live); (6) no lock during Export All; (7) `<FocusOut>`/`<Return>` unchanged while locked (WP-16.3's); (8) the status reads "locked while analyzing" and is restored on unlock unless something reported since; (9) the launch value is normalized, and one that is not an `sk-ant-` key is used with a value-free warning; (10) a typed value that is not a key still runs (WP-16.1's accepted cost); (11) the four WP-16.1 env asserts re-baselined (380, 406, 442; 448 holds as written). `get_client()` and its environment read are unchanged. No cache, key, prompt or schema moved. Tests: the WP-16.2 section of `tests/test_gui_lifecycle.py` (23) and `tests/test_run_scoped_client.py` (10) |

### Wave 2 — P0 remainder, test fidelity, cache contracts, identity

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-02.2 | Real-SDK contract tests over `httpx2.MockTransport`; strict fakes that reject what the SDK rejects (betas or fallbacks on the plain namespace, non-streaming above the SDK-derived cap) (U26) | M | WP-02.1 | done | [PR #178](https://github.com/Abe-Borg/drawing-analyzer/pull/178), 2026-09-29. **Rules decided by the owner (eight choices, two rounds, measured first; the per-builder assertions delegated):** (1) a fake entry point accepts exactly the keywords the installed SDK method's signature lists and raises the SDK's own `TypeError` for any other (a missing required argument is not checked); (2) the non-streaming cap is derived from the SDK's public `create` once per model (`fake_anthropic.sdk_nonstreaming_limit`), never a literal or the private helper; (3) every fake production reaches routes through one shared check (`fake_anthropic.check_sdk_request`): the mixins and the beta proxy, the 13 batch-create fakes (`@checked_batch_create`, no `betas` parameter), and the 7 test-local fakes behind the 16 pop sites; (4) their plain and beta namespaces are separate entry points, each checked as its own (`sdk_namespaces`); (5) contract tests in `tests/test_sdk_contract.py` over a shared stub, `tests/fixtures/sdk_transport.py` (`AnthropicAPIStub`); (6) the per-request assertions: namespace and `anthropic-beta` header, `fallbacks` and the task budget with their betas, non-streaming within the SDK's cap, no beta on batches and uploads, and each latch flip plus structured outputs; (7) derive from the installed SDK, with one tripwire pinning the measured facts (the cap literal 21,333); (8) batch item params are checked by the contract tests only (the SDK does not check them). Measured: production sends no request the SDK refuses (2,370 production calls into fakes over the whole suite; 475 requests through the real SDK over 21 scenarios, identical on 1.7.0 and 1.8.0). No product code, cache, key, prompt or schema moved. Tests: `tests/test_strict_fakes.py` (125), `tests/test_sdk_contract.py` (56). No pinned test re-baselined; no existing test changed outcome (instrumented). Enforced: an autouse guard (`tests/conftest.py`, `sdk_checked_guard`) fails a test in which production reaches a Messages entry point that is neither `fake_anthropic.checked_entry`'s nor the real SDK's (Codex review round 1: 21 production calls in five `**kwargs` fakes had escaped the first version's scans; converted), and structural scans forbid a fake that pops `betas`/`fallbacks`, takes a `betas` parameter, or leaves a batch `create` undecorated |
| WP-02.3 | Fidelity fixtures: nested batch errors; canceled/expired envelopes; `None` usage fields; `web_fetch_requests`; `iterations`; `cache_creation` split; `output_tokens_details`; `stop_details`; fallback blocks; serving model; SSE sequences incl. mid-stream failure and clean EOF (U26) | M | WP-02.2 | done | [PR #181](https://github.com/Abe-Borg/drawing-analyzer/pull/181), 2026-09-29. **Rules decided by the owner (seven choices, two rounds, measured first):** (1) one response vocabulary as API JSON, `tests/fixtures/sdk_responses.py`, which the stub serves and the fakes parse; the SDK's own sets (the nine batch error types) read from the installed SDK; (2) transport knobs on `tests/fixtures/sdk_transport.py`, defaults unchanged: `message_sse(cut=, end=)` (one emitter; `CUTS` x `ENDS`: a clean end, an SSE `error` event, a dropped connection), `AnthropicAPIStub(stream=, batch_result=, statuses=, order=)`, a `PENDING` item canceled after a cancel and expired otherwise, and the requested model served unless the reply names one; (3) the fakes are the installed SDK's own models (`model_construct`, same names, keywords and defaults; batch envelopes included; `batch_errored_result` nested), which closes the 41-test serialization gap; (4) `FinalMessageStream(message, cut=, end=)` fails as the SDK's stream does and exposes `current_message_snapshot`, held to the real SDK at every cut x end; (5) `FakeUsage`'s cache counters stay 0, `None` is an explicit shape; (6) a shape production mishandles is pinned by a `test_recorded_limit_*` test that asserts today's behaviour and names the slice that flips it; (7) the upload-release thread is joined at each test's teardown (autouse `background_release_joined`). Measured: none of `stop_details`, `iterations`, `fallback_credit`, `cache_creation`, `output_tokens_details`, `web_fetch_requests` or the serving model is read; every usage reader maps `None` to 0; 224 + 26 scenarios through the real SDK identical on 1.7.0 and 1.8.0. No product code, cache, key, prompt or schema moved; no existing test changed outcome; none re-baselined. Tests: `tests/test_sdk_responses.py` (99), `tests/test_response_shapes.py` (55; 21 of them recorded limits for WP-01.5, WP-01.6, WP-01.7, WP-06.3, WP-13.4, WP-14.1, WP-14.2 and WP-14.3, noted on each row). WP-02 acceptance clause this slice owns, measured by injection: see the handoff entry |
| WP-01.5 | Batch refusal recovery under the selected transport policy, retry bound shared with truncation retries, `stop_details` logged (R2) | M | WP-01.2 | done | [PR #182](https://github.com/Abe-Borg/drawing-analyzer/pull/182), 2026-09-29. Decided with the owner (D-1's WP-01.5 note): a refused batch item is retried once, as a batch item, when `ModelCapabilities.refusal_fallback_routes` routes its `stop_details.category` (Opus 5: `cyber` -> Opus 4.8; nothing else); the target is `recommended_model` when it names another registered model, else the route's; one per-sheet retry budget (`DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS`, default 4) counts every resubmission at every site; the harvest asks the same predicate (a refusal goes to its fallback or is final, a permanent error is final); under `RECOVERY_BATCH` a refusal never goes real time; a finished fallback read is cached under the requested model's key; `billing_error` is permanent; the category is named in every refused read's error and the diagnostics log carries the rest (redacted, one line, capped); an errored batch critique read keeps its type. Tests: `tests/test_batch_refusal_recovery.py` (69); the two recorded limits flipped and one approved re-baseline in `tests/test_response_shapes.py`. Critique retries moved to WP-01.8. Merged with the 5.5 defaults ([PR #183](https://github.com/Abe-Borg/drawing-analyzer/pull/183)): Opus 5.5 and Sonnet 5.5 declare no route, so a batch item refused on one is not retried; their routes are open for the owner. The notes below are the row's history. Since WP-01.2 the abandoned-batch harvest resolves only finished reads, so a refused item it reads back is resubmitted with the unresolved sheets, within the existing bounded rounds (as an empty or truncated one already was). Decide whether that resubmission is allowed and count it against the shared retry bound. Classify with `core.terminal_outcome` (D-1) From WP-01.3: the harvest now holds an unfinished read that carries prose or findings as the sheet's result (still unresolved, still resubmitted), and parks every other harvested item for its usage as before, a refusal included (a refused read ranks below a partial read and above nothing in `digest._read_rank`). A refusal retry under R2 lands through `_replace_result_with_attempt_history`, so it can only replace a held read it outranks, and the kept read's error names it when it comes back worse. The stalled path's rescue list is built from `harvest.resolved` From WP-01.4 (recorded, not done): a critique read cut off at `max_tokens` now fails and is not retried. A raised-cap retry for it is possible (`critique.DEFAULT_CRITIQUE_MAX_TOKENS` is 64,000 and `digest.MAX_TOKENS_RETRY_CEILING` 128,000; the real-time critique already streams through `digest.stream_message`), but it is not in N4's row and would need this slice's shared retry bound (plan step 5), on both critique transports (a batch item would need a resubmission). Decide it here with the digest's, or give it its own row. Only `max_tokens` could qualify (`raised_cap_may_finish`); a refused critique read is R2's policy question too From WP-02.3 (found, not fixed; pinned as recorded limits in `tests/test_response_shapes.py`, `::test_recorded_limit_a_refused_batch_item_is_not_resubmitted` and `::test_recorded_limit_a_billing_error_is_resubmitted_like_a_transient_one`, which this slice flips): through the real SDK, a batch digest refused with `stop_details` (category and `recommended_model`) is failed and not resubmitted (R2), and nothing reads its `stop_details`. `billing_error`, one of the SDK's nine batch error types, is not in `batch_digest._PERMANENT_ITEM_ERROR_TYPES`, so it is resubmitted in a follow-up batch like a transient error. Also measured: a batch critique read that comes back errored, canceled or expired fails and is never retried; its error keeps the nested message but drops the type. The shapes: `sdk_responses.errored`/`CANCELED`/`EXPIRED`/`refusal_stop_details` and `AnthropicAPIStub(batch_result=)` |
| WP-01.6 | Remaining response consumers (planner, identity, synthesis, focus, prose harvest cache writes); fallback-aware shared text join (U2; WP-09 step 6) | M | WP-01.2, WP-02.3 | done | [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184), 2026-09-29. **Rules decided by the owner (six choices, two rounds, measured first; D-1's WP-01.6 note):** (1) one text join, `core.reply_text.reply_text` (stdlib only): nothing across a `fallback` block, `"\n"` between any other two text blocks (so a reply without a fallback block reads byte-identical), `between=` for WP-12.1; `digest._message_text` is gone and its 11 importers and the digest read this (a structural test pins it); (2) the review planner, set identity, synthesis, the focus report and the prose harvest's structuring call ask `digest.unfinished_reply_error` first, and a non-finished read keeps nothing and is cached by none: planner and identity fail; synthesis and focus fail with no text and their billed reply is one FAILED usage record (`.replied`); a harvest item degrades, under either structured-outputs contract (plan WP-09 step 6); (3) verification's `_verdict_from_response` / `_degrade_kind` read the classifier: every non-FINISHED kind is no verdict under the existing `truncated` counter, the two pinned notes kept, new notes name the kind; D-2 unchanged; (4) the identity corpus skips an errored sheet's digest text (its failure line and text-layer windows stay); (5) the error wording is the digest's ladder with a noun per stage; a FINISHED reply that fails its parse keeps its wording; (6) `_SYNTHESIS_CACHE_CONTRACT`, `_FOCUS_CACHE_CONTRACT`, `_HARVEST_CACHE_CONTRACT` 1 -> 2; the planner, identity and verification keys left (recorded residuals); two migration-register rows. Tests: `tests/test_reply_text.py` (51), `tests/test_consumer_terminal_outcomes.py` (94); five recorded limits flipped in `tests/test_response_shapes.py`; one pinned value moved by the approved bump (`tests/test_prose_match_signatures.py`, `_HARVEST_CACHE_CONTRACT == 2`). Not taken here: cross-QC (WP-06.3), the investigation (WP-13.4), interrupted streams (WP-01.7). The notes below are the row's history. Also move `verify._verdict_from_response` / `_degrade_kind` onto `core.terminal_outcome` (D-1). They test `max_tokens` and `refusal` only, so an unknown stop reason or `model_context_window_exceeded` is still parsed as a verdict (WP-01.2 left verification alone: not an N4 site) From WP-01.3 (found, not fixed): `set_identity._sheet_block` puts an errored sheet's digest text into the identity corpus whenever it has any (the error line only when it has none), so a refusal's explanation or a truncated read's prose reaches the advisory identity call, while every other consumer skips that sheet (`combined_text`, cross-QC, the prose harvest, synthesis, focus, the planner; and since WP-01.3 the ledger, N15). Decide whether the corpus should skip it too (it re-keys the identity cache for such a set: the corpus is a key input) From WP-02.3 (found, not fixed; pinned as recorded limits in `tests/test_response_shapes.py`, which this slice flips): (1) synthesis and the focus report keep a refusal's explanation as their text and cache it; synthesis reads COMPLETE (`::test_recorded_limit_synthesis_and_focus_keep_and_cache_a_refusal`). (2) A stream that ends cleanly before `message_delta` (no stop reason) is kept and cached by synthesis and focus (the half-written text) and by the planner (`::test_recorded_limit_a_stream_cut_before_message_delta_is_kept_and_cached`). (3) U2 through the real SDK: `_message_text` joins across a `fallback` block with `"\n"`. Mid-word inside the digest's findings JSON it loses the sheet's finding (the block reads unparseable) and the read is cached as finished; in the prose it puts a `"\n"` inside a word (I-2) and is cached; a critique read split that way fails although it was good (`::test_recorded_limit_a_fallback_*`). The planner and identity already fail a refusal and cache nothing, but their error reads 'no parseable ... block', not the refusal |
| WP-01.7 | Interrupted-stream outcome and usage capture (`current_message_snapshot`), threaded through the digest retry loop (U1 partial-stream part; WP-14 step 7) | M | WP-01.2, WP-02.3 | done | [PR #185](https://github.com/Abe-Borg/drawing-analyzer/pull/185), 2026-09-30. **Rules decided by the owner (seven choices, two rounds and a follow-up, measured first; D-1's WP-01.7 note):** (1) the capture site is `core.api_config._dispatch_messages`: a failure while the stream is read raises `StreamInterrupted(cause, partial)` (`partial` = `current_message_snapshot`, `None` with no `message_start`); a failure before the stream exists is not wrapped; (2) retry transient interruptions through the one predicate, `digest._is_transient_error`: a dropped connection, a stream with no event (read as dropped), a timeout, and an SSE `error` event whose type stands for a status in `_TRANSIENT_STATUSES` (`_ERROR_TYPE_STATUS`), inside each stage's existing retries (2 per call; the rescue inside its budgets); (3) once they are spent the partial read is the reply, judged by D-1's classifier (UNFINISHED, each stage's N27 path; nothing unfinished cached); (4) the ladder's wording with the cause in its parentheses (`unfinished digest (stop_reason=None, interrupted='overloaded_error')`), and `stream interrupted (<type>: <message>)` / `stream interrupted (connection dropped — try again)` with nothing in hand; (5) the investigation retries its turn and never uses a partial turn; its usage is recorded; (6) every attempt's reported usage is recorded and `UsageRecord.interrupted_attempts` counts the attempts whose output was never reported (run total, manifest, a run.log line); the cost stays a number; (7) the digest keeps the best read across its attempts (`keep_digest_read`); and, asked as a follow-up, a snapshot that already got `message_delta` is the reply at once (not retried) and is admitted like its clean-end twin; nothing in the cache moved. Correction to the plan: the investigation streams too (seven streamed paths). Tests: `tests/test_interrupted_streams.py` (104); two recorded limits flipped in `tests/test_response_shapes.py` (5 test IDs). Not taken here: batch critique recovery (WP-01.8), cross-QC's terminal handling (WP-06.3), the investigation's pre-fallback tool uses and raised-cap turn retry (WP-13.4), per-attempt records and known/unknown usage (WP-14.4, WP-14.5). The notes below are the row's history. From WP-02.3 (found, not fixed; pinned by `tests/test_response_shapes.py::test_recorded_limit_an_interrupted_digest_stream_is_not_retried_and_its_usage_is_lost` and `::test_recorded_limit_an_interrupted_stream_loses_its_usage`, which this slice flips). The real SDK raises `httpx2.RemoteProtocolError` (not an `anthropic` error) for a dropped connection, and `APIStatusError` with `status_code` 200 for an SSE `error` event (`.type` is the event's, e.g. `overloaded_error`). `digest._is_transient_error` recognizes neither, so the digest retries neither, and the sheet's error for the event reads 'HTTP 200: {...}'. The attempt's usage is recorded 0/0 although `message_start` reported the input tokens. Synthesis and the focus report record no usage at all, the planner a 0-token record, the investigation 0/0. `current_message_snapshot` holds the partial read in every such case (the SDK's own `AssertionError` when no event arrived). The fixtures: `message_sse(cut=, end=)` and `AnthropicAPIStub(stream=)` through the real SDK, and `FinalMessageStream(cut=, end=)`, held to it From WP-01.6: a stream that ends cleanly before `message_delta` (no stop reason) now fails the planner, synthesis and focus (not kept, not cached, one FAILED usage record at `message_start`'s tokens); a stream that raises is unchanged (no reply, `.replied` False, no usage record), which is this slice's |
| WP-01.8 | Batch critique recovery: retry a failed batch critique read (transient errored, expired, a routed refusal on its fallback) and WP-01.4's raised-cap retry for a critique cut off at `max_tokens`, on both critique transports, inside WP-01.5's per-sheet retry budget and D-2's read tally | M | WP-01.5 | done | [PR #186](https://github.com/Abe-Borg/drawing-analyzer/pull/186), 2026-09-30. By the owner's rules (D-1's WP-01.8 note): the digest's one predicate, made slot-agnostic (`batch_digest._retry_params_for`; `_item_retry_params` is its digest wrapper, byte-identical decisions over the suite), decides each failed batch critique read: transient errored and expired items as sent, a routed refusal on its fallback once, `max_tokens` at twice the cap; follow-up critique batches (`batch_critique._recover_failed_reads`), never real time, no stall watch; WP-01.5's per-sheet budget (`_CSlot.retries`, every resubmitted read one); `critique.keep_critique_read` on both transports (a finished retry is the read; a failed chain named in the digest's words); the real-time critique's one raised-cap retry (`critique._critique_read`); cached under the requested key, no key or contract change. Tests: `tests/test_batch_critique_recovery.py` (87; 63 failed on `origin/main` on behaviour, 24 controls passed). 18 test IDs re-baselined with the owner's approval (the WP-01.8 handoff). Found, not fixed: the batch critique has no harvest (new row WP-18.6); the two WP-01.5 leftovers are noted on WP-14.1 and WP-14.3. Earlier notes: Split out of WP-01.5 by the owner (2026-09-29). Measured by WP-01.5 on SDK 1.7.0 and 1.8.0: every failed batch critique read fails and is never retried (refused, the nine errored types, canceled, expired, `max_tokens`); `batch_critique` has no follow-up batch, harvest or rescue. WP-01.5 gave an errored read its type (`_batch_item_error_text(noun="item")`) and the refused read its category. The raised cap is possible (`critique.DEFAULT_CRITIQUE_MAX_TOKENS` 64,000, `digest.MAX_TOKENS_RETRY_CEILING` 128,000; the real-time critique streams through `digest.stream_message`). Two items WP-01.5 found and left, for this row or the owner: (1) the abandoned-batch harvest resubmits a truncated digest item at the cap it was submitted with, and the raised cap follows only on the next round (one round that can only truncate again; the owner's harvest rule covered refusals and permanent errors only); (2) a real-time refusal whose server-side fallback could not run carries `stop_details.recommended_model` (the API's hint to retry there directly); the digest logs it and does not retry (R2 is the batch transport's) From WP-01.7: the batch critique's real-time fallback (`_serve_realtime`) reads through `critique._critique_read`, so an interrupted stream there is retried and its usage kept; a batch item never streams. |
| WP-05.3 | Character-stream fallback tier with a quantity-aware numeric veto (B4: `6 "`, `INCHDRAIN`, `12' - 6"`, `2 %`). Matches only contiguous source words, never a "manufactured joined string" (plan §2 rule 15) | M | WP-05.2, WP-04.1 | done | [PR #187](https://github.com/Abe-Borg/drawing-analyzer/pull/187), 2026-09-30. **Rules decided by the owner (eight choices, three rounds, measured first):** (1) **named joins only**: a number and a separated `"` `'` `%` (either side spaced), the feet-inches hyphen (`12' - 6"`, either side), letters merged by extraction (one sheet word for several quote words, each letters only); anything else refuses (not taken: unit words; two sheet words for one quote word; sheet-side spacing only); (2) **the veto** is those join rules plus the WP-04 reader `critique._quantity_tokens` reused as it is (function-local import; no move, no sibling reader), and never across a lone `.`; (3) FUZZY / **`char_stream`**, the last quote tier, **not** in `numbers_grounded` (not taken: grounding numbers; placing it second); (4) ambiguity **as EXACT** (`char_stream_ambiguous`); (5) a **sub-phrase may not end on a number the quote continues from** (flips the second recorded limit; not taken: equal WP-04 quantities, which cannot refuse `L/S`); (6) a **number split around a lone `.`** stays whole in **every tier** and cross-QC (found here: WP-05.2's fold let `SET AT 5 IN` match `SET AT . 5 IN` EXACT); (7) the **same rule on the quote**; (8) **cross-QC adopts** the tier, `_CROSS_QC_CACHE_CONTRACT` 6 → 7 (one register row); the fact-tile join keeps its folded key (a recorded limit). Measured over the suite (instrumented, `origin/main` vs branch): 0 of 1,064 anchors in 601 tests and 0 of 738 grounding verdicts in 237 tests moved; only the two recorded limits moved. Tests: `tests/test_anchor_character_stream.py` (203, 6 of them from the Codex review: a mark joins only a number, never an identifier's digits). Flipped: `tests/test_anchor_whole_words.py`'s two recorded limits (renamed `test_the_character_stream_cases_anchor_by_their_own_method` ×4, `test_a_sub_phrase_cannot_drop_a_separated_unit`). Re-pinned 6 → 7: the four cross-QC contract tripwires. No other test moved |
| WP-04.3 | Quantity roles for repeated same-kind values: the WP-04 matrix row "repeated values in different roles" (swapped: `6 in main, 4 in branch` / `4 in main, 6 in branch`; one value in two roles: `6 in supply, 6 in return` / `6 in supply, 8 in return`) | M | WP-04.2 | done | [PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188), 2026-09-30. **Rules decided by the owner (eight choices, two rounds, measured first):** roles from a closed list (`critique._ROLE_WORDS`: main, branch, riser, drop, header, supply, return, suction, discharge, inlet, outlet, upstream, downstream, entering, leaving, primary, secondary, min/max, static, residual, cold, hot), bound right after the value, in parentheses, as a label (`main: 6 in`) or with a copula (`the main is 6 in`); a bare preceding label is not read (recorded limit); compared per role and kind by inclusion on the `measurements` axis; a role on one side only never blocks (the 500/550 gpm duplicate from both reads still folds, pinned); an ambiguous role (a value list with a role list and no `respectively`; a bare role word between two values) retains against a bound one; the `x12` of a tight `24"x12"` is no longer a tag (`_TAG_RE`); critique contract 3 → 4 (fingerprint pinned under 4); A/B `RECORD_CONTRACT_VERSION` 3 → 4 (the roles are stored); WP-04's acceptance waits on WP-04.4. `critique._quantity_tokens` is unchanged (now the tokens of `_quantity_readings`, the one scanner with spans). Measured over the whole suite: of 6,596 merge decisions in the 431 shared tests, 389 prose vetoes, 1,072 anchors and 769 grounding verdicts, **0 moved**; only the 4 decisions of the two flipped recorded limits did. Tests: `tests/test_quantity_roles.py` (118), the two rows moved to `_CONFLICTS`, `tests/test_signature_compatibility.py` (9, the separator), the WP-04.3 sections of `tests/test_ab_findings_diff.py` and `tests/test_drawing_cache_identity.py` |
| WP-04.4 | Tokenizer residuals WP-04.1 reads only in part, each a demonstrated conflicting pair that still merges: a bare `12'` against `12'-6"`; `to`/`and`/`or` ranges and lists (`4 to 6 in` against `6 in`); loose-comma lists (`2, 4, 6 in` against `3, 5, 6 in`); a bare `20A` against `30A` on a shared `120V` (WP-04 acceptance) | M | WP-04.3 | done | [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189), 2026-09-30. **Rules decided by the owner (seven choices, two rounds, measured first):** a bare feet value, a pair beside the tokens: `critical_signature` gains `feet_inches` (`critique._feet_inches`, read part by part), each feet value in any spelling with the inches joined to it by spaces and at most one hyphen or dash (`12'-6"`, `12 ft 6 in` are `12ft6in`) or `0in` when bare (`12'`, `12 ft`, `12'-0"` are `12ft0in`), compared by inclusion on the `measurements` axis; the tokens are unchanged, so every `_SAFEGUARDS` row stays; spelled ranges and lists read whole (`critique._read_spelled`): `4 to 6 in`, `between 4 and 6 in` → `4..6in`; `4 and 6 in`, `4 or 6 in`, three or more numbers joined by commas → the tight list's token; two numbers and a comma alone stay prose; today's reading stands after a name or reference word, before `in` + an article or a preposition's object, for `2 and 1/2 in`, and inside a longer run; a compact `A` beside a voltage (after or before) is a current unless a name word precedes; critique contract 4 → 5 (fingerprint pinned under 5); A/B `RECORD_CONTRACT_VERSION` 4 → 5; `_CROSS_QC_CACHE_CONTRACT` 7 → 8 (a letter-merge join can change what the new guards read, so a grounding verdict can move for byte-identical inputs; constructed and pinned); the WP-01.7 tripwire re-pinned to `(10, 5)`; WP-04 done with two shapes recorded as limits (two numbers joined by a comma alone; a compact `A` with nothing electrical beside it). Measured: of 22,372 recorded merge decisions only the 10 of the five approved pairs moved (the four flips and the loose/tight list pair moved from retention to equivalence); 0 of 491 prose vetoes, 0 of 1,268 anchors, 0 of 908 grounding verdicts. Tests: `tests/test_quantity_residuals.py` (227), the four rows moved to `_CONFLICTS`, the list pair moved to `_EQUIVALENTS` and two new `_RECORDED_LIMITS` rows in `tests/test_quantity_signature.py`, the WP-04.4 sections of `tests/test_ab_findings_diff.py` and `tests/test_drawing_cache_identity.py` |
| WP-06.2 | Whole-set cross-QC on host handles (label shown beside handle), grounded against **uncapped** evidence text like the sharded path, claims rebound through handles, framing hashed into the key; decides D-8 if not yet decided (N6, U8, K2) | L | WP-05.1 | done | 2026-10-01. **Rules decided by the owner (eight choices, two rounds, measured first; every recommended option taken):** (1) both paths address sheets by the same `S###` host handles with the sheet id beside each (`===== SHEET S001 = M-101 =====`, one header helper, whole-set and map requests), the whole-set and map instructions say handles in the json and sheet ids in text (`_HANDLE_RULE`), and one resolver binds every reference on both paths (`_resolve_sheet_ref`: a handle, else an id exactly one sheet carries); (2) the whole-set path grounds through the sharded validator against the uncapped text (plan Step 6 reverses WP-03A's scope), the WP-03A scope test keeps its assertions and id, its docstrings record the reversal, and two tests beside it pin the whole-set tail grounding and that the cap is never read; (3) an id more than one sheet carries is refused and counted (`legs_ambiguous_label`, `facts_ambiguous_label` in `CrossQCDiscardCounts`), observational, one stage warning (`ambiguity_note()`), the stage keeps its status, cached with its counts (D-2 note); (4) entries sort by `(source_id, page_index)` when every entry has a source id (`_canonical_order`, natural order), so a reordered input gets the same handles, request, bindings and key; (5) the arithmetic auditor refuses a sourceless claim whose id two pages carry, before checking it (`arithmetic_ambiguous_sheet`); (6) `critique._leg_targets` names each leg's page (`SRC-0002#p1`), a sourceless leg keeps its canonical id, A/B `RECORD_CONTRACT_VERSION` 5 → 6 (merge-rule fingerprint unchanged: its corpus has no legs); (7) the prose harvest's synthesis id map sends an id two sheets carry to the set-level path, and `investigate._sheet_id_map` is noted on WP-13.1; (8) `_CROSS_QC_CACHE_CONTRACT` 8 → 9 for the binding, and the user-turn framing (K2) rides the key verbatim beside the system prompts (`CROSS_QC_USER_FRAMING_NAMES`, `cross_qc_user_framing()`): two changes, two mechanisms, two register rows (plus the A/B row). D-8 is decided. Tests: `tests/test_cross_qc_source_binding.py`, `tests/test_source_identity.py` (N6 section), `tests/test_evidence_tail.py` (Case 3), `tests/test_ab_findings_diff.py` (leg targets). Re-baselined (approved): the six contract pins, `test_cross_qc_returns_numeric_claims`, the two B6 parser-level tests (re-pointed from the removed `_validate_cross_item` to the one validator), the two WP-06.1 whole-set discards pins, two whole-set fixtures made to print their quotes, the map fake's header regex in `tests/test_cross_qc_grounding.py`, the A/B fixture's leg pages and its two contract pins. Recorded limits: a sheet whose own id reads like a handle is reachable by its handle only; a reply that echoes `S001 = M-101` as a reference is unknown |
| WP-06.3 | Cross-QC terminal honesty: `stop_reason` checked, streaming, bounded raised-cap retry, bounded partial-array salvage, fact-cap and omission counters; decision recorded for N14 (U6, U7 observability, N14) | M | WP-01.2 | todo | From WP-06.1 (found, not fixed): `_parse_facts` skips a fact that is not an object with no counter, on the same line as the 40-fact cap (`if not isinstance(item, dict) or len(out) >= DEFAULT_MAP_MAX_FACTS`); count both there. A leg in `also_on` that is not an object is skipped silently too (on the sharded path a finding it leaves under two legs is counted, `findings_dropped_under_two_legs`). WP-06.1 made refused findings observational and cached with their counts (the owner's decision, D-2 note); N14's decision (cache a degraded result with its status, or not) is still this slice's From WP-02.2: cross-QC is the largest non-streaming request (16,000 `max_tokens`, `create`); a raised-cap retry that doubles it passes the SDK's cap (21,333) and must move it to `digest.stream_message` in the same change. `tests/test_sdk_contract.py::test_every_non_streaming_stage_is_within_the_sdk_cap` and `::test_the_cap_table_matches_what_the_stages_send` fail until the table's `cross_qc` row says it streams From WP-16.2 (found, not fixed): `cross_sheet_qc` returns `CrossQCResult(error=...)` when it cannot get a client, and `complete` defaults to True, so the pipeline records the stage COMPLETE beside its error line (measured with the environment removed mid-run on a library call: `Cross-sheet QC: ANTHROPIC_API_KEY environment variable not set` with the stage COMPLETE). The GUI no longer reaches it From WP-02.3 (found, not fixed; pinned by `tests/test_response_shapes.py::test_recorded_limit_cross_qc_names_only_an_empty_refusal`): a cross-QC reply refused with an explanation reads 'response contained no parseable findings object' (the stage PARTIAL, not cached); only an empty refusal is named. A `fallback` block splitting the reply breaks its JSON the same way (WP-01.6's join) From WP-01.6: the join half is done (`core.reply_text.reply_text` reads a fallback-split reply whole, cross-QC's included); the stop reason is still this slice's (`cross_qc._call` reads none), and `digest.unfinished_reply_error` is the helper the five set-level consumers use (the ladder with a noun). Note for tests: per Anthropic's docs a non-streamed reply declined part way is `[fallback, text]` (the partial omitted), while `sdk_responses.splice_fallback` builds the streamed `[text, fallback, text]` shape for any reply From WP-01.7: cross-QC does not stream (a plain `create`); if its raised-cap retry moves it onto `digest.stream_message`, an interrupted stream reaches it as `core.stream_interruption.StreamInterrupted` (retried by `_is_transient_error`, its partial read unfinished), and `digest.stream_reply` is the one loop for a single reply. From WP-01.8: measured by WP-01.8 (the real SDK over the stub, the mini set): a cross-QC reply stopped at `max_tokens`, refused, with no stop reason or at the context window reads COMPLETE and is cached (the warm run makes no cross-QC call); this slice closes that part of WP-01's acceptance (WP-01 stays open until it lands: the plan's WP-01 Acceptance note). From WP-06.2: the whole-set path now goes through the sharded validator and records `discards` (the `findings_dropped_under_two_legs` count replaces its INFO-only line, which is kept), so an omission or salvage counter added here applies to both paths through `_one_cross_qc_call` and `_map_call`. The `[TRUNCATED N chars]` marker is in the key already (`_TRUNCATION_MARKER_TEMPLATE`, K2), so caching a degraded result (N14) needs no key change for it |
| WP-10.1 | Tile-label and display-label contract folded into the keys without invalidating unchanged entries (K1) | S | — | todo | |
| WP-10.2 | Critique contract resolved per transport at probe and store; batch runs log that the structured flag is ignored (K3) | S/M | — | todo | |
| WP-10.3 | Planner loss metadata stored with the plan; legacy entries report loss as unknown (K4) | S/M | WP-01.1 | todo | |
| WP-10.4 | Cache map with the admission predicate of every write; N4 read-side migration completed; migration register filled (N4 cache part; WP-10 steps 1, 7, 9) | S/M | WP-01.2, WP-01.4 | todo | From WP-01.4: the critique's admission is decided (D-4's WP-01.4 note): a critique entry is written only for a result whose every requested read the model finished with a valid findings object (`completed_runs == requested_runs`), and `_CRITIQUE_CACHE_CONTRACT` is 3. The three writers still spell that one predicate three ways (the real-time level-2 store in `critique_sheet_self_consistent`: `completed_runs == runs`; the batch level-2 put in `collect_critique_batch`: `error is None and completed_runs == batch.runs`; the pipeline's level-1 store in `_ingest_miss`: `error is None and runs == runs`), equivalent today because `error` is set only when fewer reads counted; the cache map should name one predicate for all three. Critique entries store no stop reasons (the owner's decision): a contract-3 entry is known-finished by the contract, so adding the field later needs no key change From WP-01.6: five more admission predicates for the map, each 'the reply finished (`unfinished_reply_error` is None) and parsed': review plan, identity, synthesis, focus, prose-harvest structuring; verification's is its `valid_model_verdict` after the classifier. Terms: synthesis, focus and harvest at 2; the planner, identity and verification keys carry no host term (recorded residuals, D-4's WP-01.6 note) From WP-06.2: K2 is closed; the cross-QC key holds the user-turn framing verbatim (`cross_qc.cross_qc_user_framing()`), and its admission predicate is unchanged (`_put_cross_qc_cache`: no error, complete, not budget-degraded) |
| WP-03.4 | Versioned `claim_id` beside the existing `id`; the inventoried consumers switched; cross-QC and prose-harvest cache restores rebound; decides D-3 (B8 identity) | L | WP-03.2 | todo | From WP-03.2: `investigate._candidates`, `annotate._severity_first_key`, `_set_findings_outline`, `_annotate_units` and `tile_artifacts._finding_sort_key` sort by `qc_id` before `id`, and every entry is numbered, so in a run they follow the numbering now; their `id` fallback is reached only by an unnumbered finding. Three orders still follow arrival: `pipeline._run_critique_stage`'s pre-ingest sort `(source_page_key, id)` keeps thread-completion order among ties, which becomes ledger order; `findings.json` and `findings.csv` are written in ledger order (`ctx.findings + ctx.reference_findings`, split from `ledger.number()`'s arrival-ordered list); and the report table sorts by severity and status only (`html_report._key`, a stable sort), so ties keep ledger order. Sorting `entries` by `qc_id` after `ledger.number()` would put every row in QC order, a visible change to decide here. From WP-03.3: `Finding.claim_discriminator` exists (arithmetic only, folded into `id`); decide whether `claim_id` builds on it (D-3 records it as an input). The A/B harness's `identity_key` hashes quote-or-text, not the discriminator, so two mismatches on one row still share an A/B identity (`scripts/ab_findings_diff.py`, in this slice's consumer inventory) |
| WP-03.5 | Lossless observations: upstream merges hand observations to the ledger; observations and alternative actions serialized (incl. critique cache); specificity-aware representative (B9, B1 rest, N29; N30's lost text) | L | WP-03.1, WP-03.4, WP-04.2 | todo | From WP-03.2 (N29): `_merge_into` compares an incoming member with the live survivor, whose severity an earlier merge may have raised, so with three or more duplicates the representative follows arrival order. Choose it from the members' own qualities (their snapshots), not the live survivor's, and flip `tests/test_qc_numbering_tiebreak.py::_N29_REPRESENTATIVE` to one representative in every order. From WP-03.1: flip `tests/test_pass_b_complete_link.py::_500_EXPORTED` ("500" leaves the exports in ABC/ACB/BAC, where the generic bridge wins A's bundle). Also hand the prose harvest's matched mirror to the ledger as an observation: `prose_harvest._process_free_pending` sets `also_on` on a live entry directly, so legs attached after that entry's first merge are in no member snapshot and Pass B's complete-link cannot see them (narrow since WP-03.1: Pass B folds such an entry only through a member anchored before ingest). From WP-03.7 (N30): the quote branch folds two different issues that share boilerplate wording ("pump P-1 impeller diameter conflicts with the curve" / "pump P-1 selected flow conflicts with the curve at 480", overlap 0.5, one quote), and the loser's text is lost; its observation is what must survive From WP-07.1 and WP-07.2: fewer arithmetic mismatches are DETERMINISTIC (only those whose operands the sheet prints where the quote anchors, as one-value tokens, in a relationship the sheet states), so `_grounding_quality`'s first rank settles fewer merged entries. When an ungrounded auditor mismatch merges with a model twin, the representative falls to quote length and severity, and a twin that wins carries its own text and verdict into the entry (the auditor's `MODEL_TRANSCRIBED` provenance stays on its member snapshot only). Present before for model-transcribed mismatches; weigh it in the specificity-aware representative From WP-06.1 (N30, measured): cross-QC now hands the ledger every conflict that is not an identical copy, and the cross-QC prompt asks each text to name the sheets, which adds the same sheet-id tokens to every conflict between one pair of sheets. On a synthetic corpus of twelve distinct P-1 issues between M-101 and E-101, all quoting `PUMP P-1`, the ledger folds 0 of 66 pairs without sheet names, 4 of 66 with them in full sentences, and 45 of 66 in one terse clause each (21 more are kept apart only by a signature conflict). The terse valve/horsepower pair is pinned as a recorded limit: `tests/test_cross_qc_validation_and_dedup.py::test_recorded_limit_n30_a_terse_same_pair_conflict_folds_in_the_ledger` (flip it). The plan's WP-06 acceptance note depends on it |
| WP-03.6 | Canonical final clustering over retained observations; per-observation anchors; idempotent reconciliation (WP-03 clustering clarification) | M/L | WP-03.5 | todo | From WP-03.1: flip `tests/test_pass_b_complete_link.py::_BRIDGE_JOINS` (which cluster the generic bridge joins follows arrival order) and `::test_recorded_limit_a_four_finding_chain_still_counts_by_arrival_order` (entry count 2 or 3 by order). From WP-03.7: the geometric recall WP-03.1 gave up does not come back. A rectangle is resolved from the quote, so it is evidence of where, never of which claim (D-3 input); per-observation anchors map evidence and must not merge two observations (`tests/test_pass_b_complete_link.py::test_a_same_spot_pair_never_folds_on_position`). Pass B now folds nothing Pass A refused, so canonical clustering may replace it rather than extend it |
| WP-06.4 | Direction-free merge for reversed cross-sheet conflicts with a stated same-claim predicate (B10) | M | WP-03.4, WP-06.1 | todo | From WP-06.1: cross-QC collapses only findings identical in every field (`_drop_exact_repeats`) and hands every other report to the ledger. So a re-report of one conflict phrased very differently (a shard and the reconciler, or two reconcile pair calls: a within-group conflict comes back from every pair its group is in) reaches the ledger twice, and stays two entries when the texts agree too little (overlap 0.118 in `tests/test_cross_qc_validation_and_dedup.py::test_n2_a_re_report_phrased_apart_reaches_the_ledger_twice`, pinned as the accepted cost). The same-claim predicate this slice states should fold it without folding the N2 pair (`test_n2_the_acceptance_pair_survives_*`, which must stay two) |
| WP-07.3 | Truthful arithmetic counters split by provenance; contradictory transcriptions of one quote flagged (N18; WP-07 step 7) | S/M | WP-07.1, WP-03.3 | todo | From WP-07.2: the matched path (`result.matched`) still checks neither provenance nor the relationship, so a claim whose operands or operation the sheet does not state still counts as "checked out OK"; and a claim with a refused term (`1e3`, `24x12`) now counts `unusable` instead of `checked`, so `arithmetic_checked` can read lower on the same claims. From WP-03.3: the "claim dedup keys move to Decimals" part of WP-07 step 7 is done (`arithmetic.claim_content_key`, shared by all three claim dedups). Since WP-03.3 two contradictory mismatch transcriptions of one quote (different terms) are two findings, where the coordinator used to keep the first one silently; a contradictory pair where one read matches and the other does not still counts one matched and one mismatched (N18 as reproduced) |
| WP-11.3 | Source revision checked on every reopen (verify, investigate, markup) (R1 revision part) | M | WP-11.1 | todo | From WP-11.1: D-8's page part names the inventory's `content_sha256` as the revision the run set out to read; binding a reopen to it is this slice's. WP-11.1 checks only the page count: a page past the source's current end is unread (`PageNotInSourceError`) and extra pages are not read, with one run error naming the source; a same-count rewrite is still read without a word until the markup's `detect_mutations` (and never on a standard run). The digest's level-1 identity already re-hashes a source whose stat drifted (`current_content_sha256`), so no stale cache hit is served. `iter_region_crops` (verify) and the investigation reopen without a revision check From WP-11.2: a digest phase stopped by an unexpected error ends the run after the phase, so no stage that reopens a source (verify, investigate, markup) runs on such a run; the revision check matters only on runs that finish the phase |

### Wave 3 — P1 evidence quality: auditors, citations, investigation

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-12.1 | Contiguous citation text assembly (no injected newlines); source trail across `pause_turn` and web fetch (C1, C5) | S | — | todo | From WP-01.6: the one join is `core.reply_text.reply_text(resp, between=...)`; pass `between=""` for citation splits (a fallback boundary is already contiguous). The default stays `"\n"` for every other caller (the owner's rule), so the citation fix stays local. The citation check is non-streaming: a declined-then-fallback reply there is `[fallback, text]` (Anthropic's docs) |
| WP-12.2 | Full evidence text and em-dash edition grammar across harvest, basis, reconcile and identity windows; identity host-contract key term (C2, C6) | M | — | todo | |
| WP-12.3 | Code-family grammar and shared alias table (ASHRAE, IECC, NEC, Title 24, ASCE, CBC) (U10 families) | M | WP-12.2 | todo | |
| WP-12.4 | Contextual code-window ranking (H4) | S | WP-12.2 | todo | |
| WP-12.5 | Mentioned vs adopted codes end to end, preserving Phase B two-tier trust (U10) | M/L | WP-12.3, WP-12.4 | todo | |
| WP-12.6 | Terminal and coverage gate before citation verdict-cache writes (WP-12 step 8) | S | WP-01.2 | todo | From WP-01.6: `digest.unfinished_reply_error(resp, text, noun=)` is the shared check the five set-level consumers adopted (the ladder with a noun); the citation check still reads only `pause_turn` and `max_tokens` From WP-01.8: measured by WP-01.8 (the real SDK over the stub, the mini set): a citation-check reply stopped at `max_tokens`, refused, with no stop reason or at the context window reads COMPLETE and is cached (the warm run makes no citation call); this slice closes that part of WP-01's acceptance (WP-01 stays open until it lands: the plan's WP-01 Acceptance note). |
| WP-13.1 | Task-budget rejection markers narrowed; `normalize_sheet_id` in `investigate`; ambiguous crop targets refused (U3, U12 ids) | S | — | todo | From WP-06.2: `investigate._sheet_id_map` is the last label map a binding is made through (D-8 names it): it maps each detected id to the first sheet that carries it (`setdefault`) and lets a later finding's id overwrite it, so a tool request naming an id two sheets carry reaches one of them silently (0 collisions in the suite's 247 maps). Refuse such an id and tell the model to use a listed one; cross-QC's `_resolve_sheet_ref` is the rule to reuse |
| WP-13.2 | Evidence finalized on every exit; saved/sent/judged states; `find_text` recorded in the trace; decides D-6 (R7) | M | — | todo | |
| WP-13.3 | Separate search and image budgets, honest tool wording, prompt version and key bumped (C4) | M | WP-13.2 | todo | |
| WP-13.4 | Raised-cap turn retry without re-running tools; fallback-boundary replay that never executes pre-fallback `tool_use` (N20, U12 truncation) | M | WP-01.2, WP-02.3 | todo | From WP-02.3 (confirmed through the real SDK; pinned by `tests/test_response_shapes.py::test_recorded_limit_the_investigation_executes_a_pre_fallback_tool_use`, which this slice flips): N20 as described. A first turn of `[tool_use (declined model), fallback, tool_use]` has both tool uses executed and answered, and the `fallback` block is echoed into the next request's assistant turn (the SDK serializes it). An investigation turn whose stream ends before `message_delta` (no stop reason) ends the loop with the finding UNCERTAIN and the stage COMPLETE, by design; a dropped stream reads PARTIAL with the turn's usage 0/0 (WP-01.7) From WP-01.6: the investigation's closing text reads through `core.reply_text.reply_text` (a fallback-split close reads whole); its tool-use filtering and terminal handling are unchanged and still this slice's From WP-01.7: an interrupted investigation turn (a dropped connection, a transient SSE `error` event) is now retried through the shared `digest._is_transient_error` (2 per turn), and once the retries are spent the finding keeps its UNCERTAIN verdict with the note `stream interrupted (…)`; the turn's reported usage (`message_start`'s) is on the finding's record with `interrupted_attempts`. The partial turn is never used, so no tool from it runs (`tests/test_interrupted_streams.py::test_an_investigation_turn_interrupted_on_every_attempt_runs_nothing_from_it`); replaying a partial or fallback-split turn is still this slice's. From WP-01.8: measured by WP-01.8 (the real SDK over the stub, the mini set): a investigation-turn reply stopped at `max_tokens`, refused, with no stop reason or at the context window reads COMPLETE (not cached); this slice closes that part of WP-01's acceptance (WP-01 stays open until it lands: the plan's WP-01 Acceptance note). |
| WP-08.1 | CSI sections need a lexical cue (fixtures move to cue forms); naming key keeps letter/digit order (A1, A2) | S/M | — | todo | |
| WP-08.2 | Inventory-scoped resolution memo on `SheetInventory`; lazy nearest match; operation-count targets (A3) | M | — | todo | |
| WP-08.3 | Reference phrase and list recall with per-target quote spans; dead `sug` removed (A4) | M | WP-08.2 | todo | |
| WP-08.4 | Label-aware own-ID ranking with surfaced ambiguity; FM handling, including references to missing FM sheets (A5, A6, N17) | M | WP-08.2 | todo | |
| WP-08.5 | Drawing-index region detection; partial-package handling in both directions (A7) | M | WP-08.4 | todo | |
| WP-09.3 | A digest heading that states something is read: a statement-versus-section-name rule for the digest channel, and which category governs the section after a statement heading (N32) | S/M | WP-09.2 | todo | Added by WP-09.2 (the owner's routing). Measured on `main` (`36dd865`): a whole-line bold or `###` heading inside a digest is a section header (`html_report.split_into_sections`), so its statement is neither an item nor counted, and it classifies the section it starts (`classify_section`): with no Coordination/Conflict keyword in it, the real bullets under it are lost too (2 of 4 layouts probed: `**The riser blocks the corridor door at grid 5.**` made the next bullet `other`, `### Duct riser blocks the corridor door.` made it `dimensions`). `prose_harvest._is_label` (the synthesis channel's test) cannot be reused as it is: 6 of the digest's 8 standard section names (`Scope / systems shown`, `Equipment & schedules`, `Plan content`, `Key dimensions, ...`, `General notes, keynotes, and callouts`, `Focus findings`) are not listed labels. Decide with the owner, measured first. Fixing it moves the ordinals of the section's items (no cache key holds one). WP-09's acceptance waits on this slice. Carried from WP-09.1/09.2 (not reached by any input measured): `prose_harvest._id_mentions` is quadratic in the number of mentions (4,000 mentions of two ids in one item take 0.8 s on `main`); bound it if a synthesis item can carry that many |

### Wave 4 — P1 lifecycle, accounting, resources, diagnostics

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-14.1 | Every non-succeeded batch envelope keeps a non-billable attempt record; the harvest counts only `succeeded` as responded (R3, incl. terminal path) | S | — | todo | From WP-02.3 (R3 confirmed through the real SDK; pinned by `tests/test_response_shapes.py::test_recorded_limit_a_recovered_item_keeps_no_record_of_its_failed_attempt`, which this slice flips): an item that comes back `errored` or `expired` and succeeds on resubmission has one ledger record, numbered attempt 2; the failed attempt left none. A permanent error or a `canceled` item keeps its one FAILED record From WP-01.8 (the owner's decision: noted here, not fixed there): the digest's abandoned-batch harvest resubmits an item it read cut off at `max_tokens` with the cap it was submitted with (`_HarvestOutcome.rescue_params` returns the submitted params for an unresolved, non-final slot), so the raised cap follows one round later; the harvest can ask `_item_retry_params` for a truncated item's raised cap and put it in `retry`, as it does for a refusal's fallback (one round saved). WP-01.8 made the predicate slot-agnostic (`_retry_params_for`). |
| WP-14.2 | TTL-split cache-write accounting from `usage.cache_creation`; per-TTL pricing; stale pricing comment fixed (C3) | S/M | WP-02.3 | todo | From WP-02.3 (C3 confirmed through the real SDK; pinned by `tests/test_response_shapes.py::test_recorded_limit_the_cache_write_ttl_split_is_priced_at_one_rate`, which this slice flips): with `cache_creation` split 300 (5-minute) and 700 (1-hour), a digest record is priced $0.011200 flat against $0.013825 by the split; the investigation's (1-hour breakpoint, two turns) $0.022000 flat against $0.019750. Identity, the planner, cross-QC, synthesis, focus, the prose harvest and verification read no cache counters at all (latent: none of them sends a cache breakpoint). On a stream the split is `message_start`'s: the SDK does not copy `cache_creation` from a `message_delta` |
| WP-14.3 | One shared response-metadata reader: serving model, `iterations`, `stop_details`, `fallback_credit`, `output_tokens_details`, `web_fetch_requests` (U1) | M | WP-02.3 | todo | From WP-02.3 (confirmed through the real SDK; pinned by `tests/test_response_shapes.py::test_recorded_limit_web_fetch_requests_are_not_counted` and `::test_recorded_limit_the_serving_model_is_not_read`, which this slice flips): nothing reads `stop_details`, `iterations`, `fallback_credit`, `output_tokens_details`, `web_fetch_requests` or the serving model (after a fallback the ledger names the requested model). The beta stream accumulator sets the message's `model` from a `fallback` block's `to.model`. Not duplicated today: the totals are the top-level usage, never plus `iterations` (asserted by `::test_iterations_and_output_details_are_not_counted_twice`). `core.api_config.extract_cache_usage` has no caller left; the shared reader can replace it From WP-01.5 (pinned by `tests/test_batch_refusal_recovery.py::test_recorded_limit_a_fallback_read_is_labelled_with_the_requested_model`, which this slice flips): a refused batch digest the host resubmits on Opus 4.8 is recorded in the ledger under the requested model (`DigestUsageAttempt` carries no model; the pipeline labels every digest attempt with the run's model). Same price today. `digest.refusal_details` now reads a refusal's `stop_details` (category, explanation, `recommended_model` on either namespace); the shared reader should adopt it rather than add a second From WP-01.8 (the owner's decision: noted here, not fixed there): a real-time refusal whose server-side fallback could not run carries `stop_details.recommended_model` (beta), which the digest and the critique log (`describe_refusal`) and do not retry; a host retry on the hint (one full-rate call, every real-time stage) would be this reader's first consumer, and is the owner's call. |
| WP-14.4 | `UsageRecord` known/unknown usage through the single `is_billable_but_unpriced` rule; `by_model` decision; pricing date on every surface; decides D-7 (WP-14 steps 4, 8) | M | WP-14.3 | todo | From WP-11.2 (found, not fixed): a real-time read whose `digest_sheet` raised after the API call returned (the paid read, then an error outside the call's own capture; its level-2 cache write is advisory since WP-11.2, so not that) leaves no usage record, since the exception carries no usage; the phase now stops and ships, so that spend is the one the run cannot report (D-7) From WP-01.7: `UsageRecord.interrupted_attempts` (additive) counts the attempts behind a record whose stream was interrupted before its final usage arrived, so their output was never reported; `RunUsage.interrupted_attempts` totals it, and run.log / the manifest say the output and cost totals are then lower bounds. WP-01.7 kept the cost a number and left `is_billable_but_unpriced` alone (the owner's choice): whether unreported output makes a total unknown is D-7's. |
| WP-14.5 | Per-attempt usage records from every stage result type (WP-14 step 3) | L | WP-14.4, WP-01.2 | todo | From WP-01.3: the real-time digest's raised-cap retry is still one usage record carrying both attempts' summed tokens (batch keeps one record per attempt). Since WP-01.3 the discarded attempt is named in the sheet's error, but it has no attempt record of its own on real time From WP-01.4: the critique's per-sheet record aggregates its reads (both reads' tokens), and since WP-01.4 its `terminal_status` is COMPLETE only when every read counted, FAILED when none did, else PARTIAL (`parse_success` only for COMPLETE). A per-read record would carry each read's own outcome (a cut-off read beside a finished one is one PARTIAL record today) From WP-01.6: a synthesis or focus reply that came back and was not used (non-finished, or empty) is now one FAILED usage record (`SynthesisResult.replied` / `FocusReportResult.replied`); a failed one recorded nothing before. The harvest's usage record keeps its stage-level status (PARTIAL only when an item is missing), so a structuring reply that degraded is billed inside a COMPLETE record From WP-01.7: the real-time stages still keep one usage record per call, which now sums every attempt's reported usage (an interrupted stream's `message_start` counters included) and counts `interrupted_attempts`; the batch direct rescue keeps one record per attempt, an interrupted one included (`_record_interrupted_rescue`: a partial read is folded like any rescue read, one that held nothing is a non-billable REAL_TIME attempt counted as interrupted). From WP-01.8: a batch critique read the follow-up critique batches retried, and a real-time critique read given its raised-cap retry, keep every attempt's tokens on the sheet's one critique record (the owner's decision), BATCH for batch retries; a per-attempt record would carry each resubmission (up to four per sheet at the default budget). |
| WP-14.6 | Serving model carried through cache payloads (additive field) and the manifest (U1 provenance) | M | WP-14.3, WP-14.4 | todo | From WP-02.3: the serving model is pinned as a recorded limit with WP-14.3 (`tests/test_response_shapes.py::test_recorded_limit_the_serving_model_is_not_read`); the stub now serves the requested model unless the reply names one |
| WP-16.3 | `_persist_key` reentrancy guard; Forget saved key; export never reloads a cleared key (U20) | S/M | WP-16.1 | todo | From WP-16.1: `_persist_key` retries a refused save (a value that is not a key) on every `<FocusOut>`/`<Return>` and logs the refusal each time, since `_persisted_key` does not move. The export loads (`gui.py` `_on_save_html`, `_export_all_worker`) call `load_api_key_from_file`, which now normalizes, may repair the keyring or migrate a file, and writes its notes to the diagnostics log on every export. A refused key file is kept by rule and named at each launch while the keyring holds no key; Forget should cover it (plan step 6: "legacy files where authorized") From WP-16.2: the exports now read `_applied_key` first (the key field; Export All takes it on the UI thread at the click) and `load_api_key_from_file()` second, unchanged, so a cleared field still reloads a saved key there (step 7 is this slice's). `<FocusOut>`/`<Return>` still fire on the locked entry (real Tk), so a key whose plaintext save was declined re-opens the consent dialog on each during a run, as when idle (the owner kept `_persist_key` unchanged for this slice). Forget should clear `_applied_key` and the field; since WP-16.2 there is no app-owned environment value to clear (an inherited one is removed at launch) |
| WP-17.1 | Cancel: cancel event, Cancel button, batch cancel and harvest with no resubmit, honest quit wording, partial export; decides D-5 (G1 core) | M/L | WP-16.2 | todo | From WP-11.2: `KeyboardInterrupt` and `SystemExit` are deliberately not contained (D-5 input note): the spool and the retained uploads are released, but a batch in flight is neither cancelled nor harvested and its uploads stay, since the submit and collect guards catch `Exception` only. Found, not fixed: `collect_drawing_batch`'s error guards (the terminal branch's and WP-11.2's) release a batch's files while a follow-up or resubmission batch that reuses them may still run, and a resubmission in flight at the error is neither cancelled nor read back From WP-16.2: the run's client is built in `gui._worker` from the key `_on_process` snapshotted (`api_key=`); a cancel path should reuse that client (never `get_client()`, which reads an environment the GUI no longer writes). A worker that dies with `KeyboardInterrupt`/`SystemExit` never reaches `_on_done`/`_on_error`, so `_busy` and every control stay locked, the key entry included (pre-existing for the other controls; D-5's) |
| WP-17.2 | Keyless atomic job record (batch ids, `custom_id` → source/page/cache key, upload ids); relaunch lists unresolved jobs and offers remote cancel (G1) | M | WP-17.1 | todo | |
| WP-17.3 | Harvest recorded jobs' results into `DigestCache` after fingerprint validation (G1) | M | WP-17.2 | todo | |
| WP-17.4 | Crash matrix, unresolved-submission reconciliation, instance lock/lease (G1) | L | WP-17.3 | todo | |
| WP-18.1 | Files-API failure never becomes full-rate work under Economy on either transport; recovery policy threaded into the submit functions (N21, U4) | M | — | todo | |
| WP-18.2 | Inline request size guard in the shared builder (authorized fallback and Fast/Hybrid) (U4) | S/M | WP-18.1 | todo | |
| WP-18.3 | Work-dir and render-spool leases so a live run is never pruned (U9) | M | — | todo | |
| WP-18.4 | Upload error classification; truthful retention text ("files persist until deleted") (N22) | S | — | todo | From WP-11.2: `help_content.py` and the README now list only the upload-release exits that are covered (a finished, a cancelled, a submit or collect stopped by an error); their "expire on Anthropic's side" / "expire server-side" wording is left for this slice. Found, not fixed: `file_upload.upload_sheet_images` calls `on_image` after an image lands, and if it raises that image's id never reaches `by_position`, so the partial-upload cleanup cannot delete it; the submit then records the callback's exception as the sheet's upload failure. With a status sink that keeps raising, every uploaded image of every sheet leaks. `ImageProgress`'s comment says the callback "never affects the upload result" |
| WP-18.5 | Durable upload ownership and bounded reclaim of provably app-owned orphans (U5) | M/L | WP-17.2, WP-14.4 | todo | |
| WP-18.6 | The batch critique harvests an abandoned batch before it degrades its sheets: a critique batch detached at the collection bound, or unpollable, is canceled and every sheet in it loses its critique, including reads the batch had finished and billed (DA-035's shape; the digest harvests since DA-035) | S/M | WP-01.8 | todo | Found by WP-01.8 (the owner's decision: a new row outside WP-01). `batch_critique.collect_critique_batch`'s non-terminal branch cancels and writes `critique batch not collected (…)` on every submitted sheet. The follow-up critique batches (`_recover_failed_reads`) could take what the harvest reads back as failed and still retryable. Also a follow-up round that ends non-terminal is canceled and ends the recovery, its reads named (WP-01.8's rule); a harvest there would keep what it had finished |
| WP-19.1 | Pair-aware chat history normalization at Stop, commit, cap exit, catch, save and restore; `pause_turn` rounds merged; transcript v1 accepted and repaired (R4) | M | — | todo | |
| WP-19.2 | Mixed client/server tool and pause semantics; replay canary written (run blocked on O-4) (R4, U2) | S/M | WP-19.1 | todo | Running the canary is O-4 |
| WP-22.1 | Linear secret redaction (incl. `RedactingFormatter`); path scrub handles URLs, doubled separators, `\\?\` and UNC (U13) | M | — | todo | From WP-11.2 (found, not fixed): sixteen stage catch-alls in `pipeline.py` append `str(exc)` to `ctx.errors` (`Critique: {exc}` among them), so a path or secret in an exception message reaches the context; the exported artifacts scrub it (`redact_for_display`), the GUI's log panel prints it as is. WP-11.2's digest-phase line names the type only From WP-16.1 (found, not fixed): the diagnostics file handler is attached only to the `drawing_analyzer.diagnostics` logger (`propagate=False`), so `core.api_config`'s and `core.tokenizer`'s `getLogger(__name__)` warnings (a model id that fell through to conservative defaults, the refusal fallback latched off, `count_tokens_via_api` failures) reach only Python's last-resort stderr handler, which a windowed build does not have, and never the diagnostics log. The key store logs to the diagnostics logger by name for that reason |
| WP-22.2 | Critique read count resolved once; `critique_N` tags counted as one family (N25, U15) | S/M | — | todo | |
| WP-22.3 | One shared `refs` coercion replacing the three that disagree (U16) | S | — | todo | |
| WP-22.4 | Supported configuration matrix; required-stage roll-up cannot report COMPLETE with missing stages (U14, U15) | M | WP-01.1 | todo | |
| WP-22.5 | Hygiene: stale descriptions, "Spec Critic" docstrings, F401/F811/F841/B017 lint step in both workflows; removal only of helpers that mislead, never incidental API removal; `count_tokens_via_api` kept (U27) | S | — | todo |From WP-09.2 (found, not fixed): F401 also finds `count_annotations` imported unused in `tests/test_drawing_acceptance.py` (the gauntlet section's imports), on `main` already, beside the ones earlier handoffs listed (`arithmetic._wtext`, `critique.DEFAULT_DIGEST_MAX_TOKENS`, `pipeline.normalize_specs_text`, `annotate.ANNOTATION_COMPONENTS`, `pathlib.Path` in `tests/test_drawing_dedup_lifecycle.py`, nine in `tests/test_evidence_visual.py`) From WP-01.3 (found, not fixed): F401 also finds `SheetDigest` imported unused in `tests/test_drawing_digest.py`, on `main` already From WP-01.4 (found, not fixed): F401 also finds `SheetRef` imported unused in `tests/test_drawing_cache_identity.py`, on `main` already; and the `critique.py` module docstring still says the self-consistency merge "deduplicates by position and text", stale since WP-03.7 removed the geometry branch (the merge reads no rectangle) |

### Wave 5 — P1/P2 report, chat, estimates, packaging, updates

| Slice | Scope (IDs closed) | Size | Depends on | Status | PR / date / notes |
|---|---|---|---|---|---|
| WP-21.1 | Markup plan rebuilt from worker receipts by `placement_id`; serial and process-pool manifests agree (R5) | S | — | todo | |
| WP-21.2 | Repeat grouping recomputed after sort; cached search text with identical results; CLAUDE.md sentence fixed (H1, U18) | S/M | — | todo | |
| WP-21.3 | Index and bookmark links go to the actual written destination (notes row rect); navigation keyed by `placement_id` (N9, B8 navigation) | M | WP-21.1 | todo | |
| WP-21.4 | One display vocabulary: sheet-level observation, no quote, quote not found, not checked, inconclusive, failed attempt (H2) | M/L | WP-05.1, WP-05.2, WP-01.1 | todo | From WP-07.1: an arithmetic mismatch checked against model-transcribed operands is built `UNCERTAIN` before any verifier looks, so on a run with no verification (standard, audit-only) the report shows "Uncertain" ("a verifier looked and could not settle") where "Not checked" is the truth (`html_report._finding_display_status` reads only the status). Present since §17.5; more common since WP-07.1, which makes every ungrounded mismatch `UNCERTAIN`, and since WP-07.2, which does the same for a mismatch whose relationship the sheet does not state. Include it in the vocabulary (the popup's trust note is already right: `annotate._trust_note` reads `operand_origin` first) From WP-05.1: a short tag read off a hybrid sheet's pasted region is now TEXT_EVIDENCE_UNAVAILABLE (it was TEXT_GROUNDED unchecked), so it too gets "No searchable text on this sheet" / `[NO TEXT TO CHECK]` while the sheet has text elsewhere; long quotes have read that way since WP-03B. The reason is chosen by `models.reduced_trust_reason`, which cannot tell a textless sheet from a pixels-only region ("no searchable text in this region" would be true for both) From WP-05.2 (found, not fixed): the README (the UNANCHORED tier under "Anchoring findings", and the gating table's "Rect-less: quote matched nothing" row) and `help_content.py` (the anchoring help text) call the unanchored label `[UNANCHORED]`, while the markup writes `[QUOTE NOT FOUND]` (`annotate._PLACE_PREFIX`). Fold into the one vocabulary |
| WP-20.1 | Exact calculator: full numeric grammar, BigInt rationals, bounds, `is_error: true`, no "guaranteed correct" wording (N7) | S/M | — | todo | |
| WP-20.2 | Chat cost readout from final cumulative usage, cache-write TTL split and web-search charges (H3) | S/M | — | todo | |
| WP-20.3 | Reader key and transcript storage policy validated in Chromium; in-memory where isolation cannot be shown (N26, U19) | S/M | — | todo | |
| WP-20.4 | Bounded report context with index and retrieval tools; 400-sheet fixture; duplicate labels (U17) | L | WP-19.1 | todo | |
| WP-20.5 | History budgeting at complete exchange boundaries (U17) | M | WP-19.1, WP-20.4 | todo | |
| WP-15.1 | Preflight runs without profiles, has no render-identity hashing and holds the lock around every PyMuPDF use; per-file source ids (\$3, N23, N24) | M | — | todo | From WP-11.1: the run's workload is now the inventory's pages (`render.inventory_sheet_refs`); the GUI's pre-run sheet count still reopens every file with `list_sheets` on the UI thread (`gui.py`, N24), which skips a file it cannot open silently, so its count can disagree with the run's for such a file. `iter_sheet_prescan` gained `expected_pages` (best effort, no raise); `profiles.preflight_scan` does not pass it, so it keeps the old contract and still wraps each file in a `try` |
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
| INT.1 | Audit the plan §6.1 regression corpus: every fixture group exists; fill the gaps | M | Waves 0–2 | todo | From WP-06.1 (found, not fixed): `tests/test_drawing_cross_qc.py::_MapReconcileClient` answers the reconcile call only "when BOTH its sheets' handles are actually present in this reconcile call", but it searches the whole request body, and the reconcile input's SHEET MANIFEST lists every handle, so the check always passes: in `test_reconcile_all_pairs_finds_conflict_across_fact_groups` the finding came back from all 36 pair calls (instrumented). The test's own claim, that only the pair uniting the two fact groups can surface the conflict, is therefore not shown. A faithful fake reads the FACTS lines |
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
| B4 | Verbatim quotes fail to anchor on punctuation/spacing variance | P0/P1 | 05.2, 05.3 | implemented+validated (punctuation part in 05.2, character-stream part in 05.3) | `tests/test_anchor_whole_words.py` (WP-05.2, [PR #166](https://github.com/Abe-Borg/drawing-analyzer/pull/166)): `RATED 175 PSI TYP` on `RATED 175 PSI, TYP.`, `NOTE 3` on `NOTE 3:`, `150 GPM 568 L/MIN` on `150 GPM (568 L/MIN)`, `P-1` on `SEE P-1, TYP` and `SEE (P-1), TYP` anchor EXACT/`exact` on the sheet's own words (`matched_text` as printed), and the quote-side forms (`P-1,`, `NOTE 3:`, `(568 L/MIN)`), lone punctuation words and `!`, `?`, `[ ]`, `{ }`; the veto reads folded words (a window over `500,`) and still refuses every substitution on punctuated text; never folded: `6"`/`6'`, `.5`/`5`, `-5`/`5`, `30`/`30%`, `<`; a folded match grounds arithmetic operands (`20 + 20 = 540` on `(20 + 20 = 540)` is DETERMINISTIC); cross-QC admits such legs and facts (one matcher); the pipeline clouds the punctuated quote and sends it to one verification call. Remaining (WP-05.3): `6 "`, `INCHDRAIN`, `12' - 6"`, `2 %`, pinned as recorded limits. `tests/test_anchor_character_stream.py` (WP-05.3, [PR #187](https://github.com/Abe-Borg/drawing-analyzer/pull/187)): the four pairs anchor FUZZY `char_stream` on the whole run (`PROVIDE 6" DRAIN` on `PROVIDE 6 " DRAIN`, `PROVIDE INCH DRAIN` on `PROVIDE INCHDRAIN`, `CLG 12'-6" AFF` on `CLG 12' - 6" AFF`, `SLOPE 2% MIN` on `SLOPE 2 % MIN`) and cross-QC grounds them; 14 more named joins (the quote spaced instead, a foot mark, feet-inches spaced one side or every side, a mixed number and a decimal with a separated inch mark, two marks, a long note, part of a line, folded punctuation); 41 negatives never anchor or ground (changed numbers, signs, units, multiplicity, joined or split numbers, embedded tags, split letters, fragments, a run ending inside a word, unit words, sizes, degrees, `20A`/`20 A`, and `.5`/`5` in every spelling); absent short tags never ground; a number split around a lone `.` is never matched in part in any tier (EXACT before: `SET AT 5 IN` on `SET AT . 5 IN`); a sub-phrase never ends on a number the quote continues from (`150 GPM 568 L/S`, flipped); ambiguity (`char_stream_ambiguous`, tile, I-7); `char_stream` grounds no arithmetic operand; verification, investigation and the pipeline (clouded, one crop call each); one agreement table of 77 rows through both matchers |
| B5 | Cross-QC quotes under 6 chars are "grounded" without a check | P0 | 05.1 | implemented+validated | `tests/test_cross_qc_grounding.py` (WP-05.1, [PR #165](https://github.com/Abe-Borg/drawing-analyzer/pull/165)): `P-1`, `AHU-1`, `M-101` on a textless sheet are TEXT_EVIDENCE_UNAVAILABLE, admitted at reduced trust, TILE-anchored (`tile_no_text_evidence`) and seen by `verify._has_anchored_legs` and `investigate._candidates`, as legs and as facts; `AHU-7` on a sheet that does not print it is NOT_MATCHED, the leg is dropped and counted as ungrounded (the conflict too when it had two legs); a layer of zero-width characters is no text; any length gets a real match (`3`, `TYP`, `q`); the sharded path end to end (counters, the fact tile); **the pipeline**: a scanned sheet's `P-1` leg gets one dual-crop verification call (2 images) and ends VERIFIED, and an `AHU-7` conflict the sheet does not print never becomes a finding. `tests/test_evidence_visual.py::test_a_recovered_finding_reaches_verification_and_investigation` extended to the short tags |
| B6 | Cross-QC prompt asks for severity `question`; the items are dropped silently | P0 | 06.1 | implemented+validated | `tests/test_cross_qc_validation_and_dedup.py` (WP-06.1, [PR #167](https://github.com/Abe-Borg/drawing-analyzer/pull/167)): the whole-set and map prompts (the shared persona) name only valid severities and categories and ask for category `question` with severity `low`, and the reconcile prompt never asked otherwise; such an item is kept on both paths and inked on both sheets on the Low layer; severity `question`, `Question`, `critical`, a missing one, an unknown category, `reference`, empty, blank or non-string text and a non-object are still refused (validation strict) and counted once under their first reason, on the whole-set, map and reconcile calls and across reconcile pair calls (the same item gives the same binding and counts on both validators); a clean empty response is not a loss; an unplaceable item is not counted as refused; the counts are cached with the result and replayed on a warm run, round-trip, carry no text and read back "not recorded" from an older entry; the log separates refused from unplaceable; through the pipeline the stage stays COMPLETE with the warning, which reaches `run.log` (stage table and STAGE_END) and `run_manifest.json` (`cross_qc_invalid`, the stage warnings) |
| B7 | Distinct same-row arithmetic mismatches: coordinator dedup, then a ledger geometry merge | P0 | 03.3 | implemented+validated | `tests/test_arithmetic_claim_discriminator.py` (WP-03.3, [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161)): the review's pair and the `[30,30]=500` pair through `run_auditors` (two findings, two ids, `arithmetic_mismatched == len(findings)`); `run_auditors` → `Ledger.add` → seal → Pass B → `number()` in both orders, anchored and on an unresolved sheet, DETERMINISTIC beside UNCERTAIN, each keeping its own id, text, verdict and number; three mismatches on one row in all six orders; the text, quote and geometry branches each refused in Pass A, and geometry in Pass B; an absorbed member's discriminator blocking a generic bridge; true duplicates still merge (a model twin, with the auditor winning the bundle; one claim read twice); Decimal claim keys in all three dedups, incl. unparseable terms |
| B8 | `Finding.id` not unique; numbering, bookmarks and index links treat it as identity | P0 | 03.2, 03.4, 21.3 | open (numbering part implemented+validated in 03.2, as K5; identity (03.4) and navigation (21.3) stay open) | `tests/test_qc_numbering_tiebreak.py` (WP-03.2, [PR #160](https://github.com/Abe-Borg/drawing-analyzer/pull/160)): the `PUMP P-1` pair gets the same numbers and evidence directories in both orders. Since WP-03.3 two arithmetic mismatches on one row get distinct ids (the claim discriminator is folded in; `tests/test_arithmetic_claim_discriminator.py`), and two id dedups are gone (`run_auditors`; `audit_titleblock` now keys on sheet and quote); model findings are unchanged. Since WP-03.7 (N28) every pair of different issues quoting one string reaches the exports as two entries; they still share one content id, so the navigation part below now applies to each such pair (numbers and evidence directories are distinct, pinned in `tests/test_position_is_not_sameness.py`). Remaining: `claim_id` (WP-03.4); bookmark dedup and `mark_page_by_finding` keyed by the content id (WP-21.3) |
| B9 | Merge discards the loser's text and recommended action | P0 | 03.5 | open | |
| B10 | A→B and B→A copies of one conflict both survive | P1 | 06.4 | open | |
| B11 | "No conflicts noted on this sheet." becomes a medium finding | P1 | 09.1 | implemented+validated | `tests/test_prose_filler_and_assurances.py` (WP-09.1, [PR #168](https://github.com/Abe-Borg/drawing-analyzer/pull/168)): the review's four strings and 21 equivalent wordings are filler (`test_b11_review_strings_are_filler`, `test_b11_equivalent_wording_is_filler`), counted in `filtered`, and make no structuring call and no ledger entry with a client, without one, or when the call fails (`test_b11_filler_*`); 45 real findings survive (`test_real_findings_survive_the_filter`), and everything the old filter dropped is still dropped (`test_the_new_filter_drops_everything_the_old_one_did`) |
| B12 | `deg`/`°` sign differently; `90 deg F` vs `90 deg C` compatible | P0 | 04.1 | implemented+validated | `tests/test_quantity_signature.py` (the B12 token table; the `B12 …` pairs, incl. no inferred scale); `tests/test_ab_findings_diff.py::test_a_changed_temperature_scale_is_never_an_exact_match` (WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157)) |
| R1 | Source unreadable after inventory aborts the whole run | P0/P1 | 11.1, 11.2, 11.3 | open (core implemented+validated in 11.1; digest-phase containment implemented+validated in 11.2; the revision check on reopen (11.3) stays open) | `tests/test_source_page_isolation.py` (WP-11.1, [PR #172](https://github.com/Abe-Borg/drawing-analyzer/pull/172)), by the owner's rules: the second, the first and every source removed after the inventory, and one locked (`PermissionError`), on real time, batch and Hybrid, cold and cached: the run returns a context and a closed journal, the surviving sheets are digested and exportable, each lost page has an `UnreadPage` and one `PAGE_UNREAD` event, one source line in `ctx.errors` and the digest stage's errors, the stage counts the inventory's pages (PARTIAL; FAILED when nothing survived), no path anywhere; a paid digest before the loss is kept (usage, export, manifest); the zero-sheet exit only for a set with nothing accepted; a page failing in the prescan (identity, word count, geometry) is read, one failing in both (page load, text) or in the render only is unread with one page line; fewer and more pages (both transports, both cache paths); a 5-page source is one line; a page neither yielded nor reported still has an outcome; a cached source that vanishes after the prescan costs nothing; the critique over a source lost after the digest (COMPLETE from the spool or retained uploads; Hybrid names each page with its reason); an unchanged set's refs equal `list_sheets` and a cached re-run renders nothing. `tests/test_digest_phase_containment.py` (WP-11.2, [PR #173](https://github.com/Abe-Borg/drawing-analyzer/pull/173)), by the owner's rules: an unexpected exception from the digest, a progress callback, the prescan, the level-1 store, the accounting, a batch submit loop, poll or results read, on real time, batch, Hybrid and Economy, cold and cached: the run returns a closed context (`RUN_END` `stopped="digest"`) and exports it; every paid digest in hand is kept (usage, `SHEET_DIGESTED`, `findings.json`), a read in flight included; each page not reached is an `UnreadPage` naming the failure with one `PAGE_UNREAD` event; one path-free line (type name only) says what was not read and what was kept; the digest stage reads FAILED; no later stage makes a call; a cached re-run reads only what was not read; a submit failure before its batch deletes every upload; a collect failure reads back what finished, cancels a running batch and releases (a batch it cannot cancel keeps its files); the spool and retained uploads are released on every exit, `KeyboardInterrupt` and an exception after the phase included, and `KeyboardInterrupt` still ends the run. Remaining: WP-11.3 (revision on reopen) |
| R2 | Refused batch item never retried or rescued | P1 | 01.5, 01.8 | implemented+validated | `tests/test_batch_refusal_recovery.py` (routes, target, budget, transport, harvest, cache, logging; real SDK over the stub) and `tests/test_response_shapes.py::test_a_refused_batch_item_is_resubmitted_on_the_fallback_model` (the flipped recorded limit, through the pipeline) (WP-01.5, [PR #182](https://github.com/Abe-Borg/drawing-analyzer/pull/182)). Acceptance "Refusal recovery preserves selected transport and bounds": `test_the_pipelines_transport_never_rescues_a_refusal_in_real_time`, `test_no_sheet_is_resubmitted_more_than_the_budget`, `test_the_budget_covers_the_direct_rescue` The batch critique's refused read (WP-01.8, [PR #186](https://github.com/Abe-Borg/drawing-analyzer/pull/186)): the same route and budget through follow-up critique batches, `tests/test_batch_critique_recovery.py::test_a_routed_refusal_is_resubmitted_on_its_fallback_and_recovered`, `::test_a_fallback_that_refuses_too_is_not_retried_again`, `::test_a_refusal_on_a_55_model_is_not_retried_and_says_so` |
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
| K2 | Cross-QC user-turn framing outside the stage key | P1 | 06.2 | implemented+validated | WP-06.2: the framing strings ride the key verbatim (`cross_qc_user_framing()`); `tests/test_cross_qc_source_binding.py::test_each_framing_string_is_model_visible_and_in_the_key` (one per string) and `::test_the_truncation_marker_is_in_the_key` |
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
| A8 | Tag/sheet-id digits count as operands; `1e3` → 1; hyphen read as minus | P0 | 07.2 | implemented+validated | `tests/test_arithmetic_tokens_and_relationships.py` (WP-07.2, [PR #164](https://github.com/Abe-Borg/drawing-analyzer/pull/164)): the review's `SEE FP101 TOTAL 540 AT 439 GPM` (`sum [101, 540] = 439` no longer trusted), `M-101 P-3 AHU-2` (no negatives, no numbers), `1e3`/`2.5e-2`/`1E+3`/`2E1` refused by the parser and the scanner (a claim with such a term is unusable), `24x12`, `2P20A`, `10A1`, `100m2`, Unicode dashes (pinned equal to the anchor's fold set), a fraction slash and a glued vulgar fraction refused, units still parsing (`20A`, `150GPM`, `0.20 gpm/ft²`, `6-INCH`), a per-token scanner/parser agreement table; the relationship: a product transcribed as a sum (`x`, `X`, `×`, `*`), a sum as a product, four role swaps, an operand left out of a correct row, a correct subtraction, no operator, an unknown symbol, a refused number between operands, mixed operators, a label's number among the operands, operands from two rows, no result marker, and an operator the quote states but the sheet does not (FUZZY); kept: 15 stated shapes incl. TOTAL rows, a running total and a tag label first, and a signed operand after a printed operator (`20 + -5`, `20 x +2`; the Codex review); ids, text and notes unchanged; verification eligibility, the trust note, `run_auditors`' tally, the critique and cross-QC dedups, a failure while checking one finding; and the pipeline sending two unstated relationships to the crop verifier while `TOTAL 100 + 250 = 375` stays DETERMINISTIC |
| H1 | Sorting never recomputes repeat grouping (CLAUDE.md claims it does) | P2 | 21.2 | open | |
| H2 | A quote-less sheet-level finding is branded "Unanchored" | P1 | 21.4 | open | |
| H3 | Chat cost ignores final usage and web-search charges | P2 | 20.2 | open | |
| H4 | ALL-CAPS notes fill the identity code windows | P1 | 12.4 | open | |
| G1 | No Cancel; quitting leaves a batch billing, nothing resumable | P1 | 17.1–17.4 | open | |
| G2 | Key entry live during a run; every stage re-reads the environment | P1 | 16.2 | implemented+validated | `tests/test_gui_lifecycle.py` WP-16.2 section (a field edit, an emptied field, the environment set to another key or removed after the digest: every later stage keeps the run's key; the run gets one real client built from the applied key; the entry locked while busy and unlocked on done and on a worker that raised; the launch key normalized and removed; no spawn or `subprocess` child inherits a key; the exports embed the applied key; no message carries the key) and `tests/test_run_scoped_client.py` (a passed real client serves every stage on Fast, Batch, Hybrid and Economy, investigation included, whatever the environment does; overlap kept) (WP-16.2, [PR #177](https://github.com/Abe-Borg/drawing-analyzer/pull/177)) |
| G3 | BOM key migrated into the keyring, legacy file deleted | P1 | 16.1 | implemented+validated | `tests/test_api_key_store.py` WP-16.1 section (p1 BOM file migrates the clean key and the next launch serves it; p3 the wire never carries the BOM, through the real SDK over `httpx2.MockTransport`; p5 a migration keeps a file holding a different key; p6, p7, p11 a file that is not a key is refused and kept; p8 UTF-16 decoded; p9 format characters at the ends stripped; p10 a keyring entry stored with a BOM is repaired; p13; save normalizes and refuses a value that is not a key; no note, log record, exception or output carries the key) and `tests/test_gui_lifecycle.py` WP-16.1 section (the field shows, applies and saves the normalized key) (WP-16.1, [PR #176](https://github.com/Abe-Borg/drawing-analyzer/pull/176)) |
| G4 | PyInstaller `collect_all` bundles stray files (key file) | P1 | 23.2 | open | |
| G5 | Release gates test a different dependency set than ships | P1 | 23.3 | open | |
| G6 | Installer hashed at download only, launched hours later | P1 | 24.1 | open | |
| N1 | One shared value (`100 psi`, `12ft`) masks conflicting measurements | P0 | 04.2 | implemented+validated | `tests/test_quantity_signature.py` (the `N1 …` rows of `_CONFLICTS`, each asserted in the critique merge and the ledger; `_CORROBORATIONS`, `_NO_SHARED_QUANTITY`, `_CONSERVATIVE_RETENTION`, `_RECORDED_LIMITS`); `tests/test_signature_compatibility.py` (tags incl. sheet, grid and detail references; the per-kind table; complete-link in the critique merge, `Ledger.add` and Pass B; the rule never merges a pair the flat rule blocked); `tests/test_ab_findings_diff.py::test_a_conflict_beside_a_shared_value_is_never_an_exact_match` and `::test_a_second_tag_that_changed_is_never_an_exact_match` (WP-04.2, [PR #158](https://github.com/Abe-Borg/drawing-analyzer/pull/158)). Closes every conflict the signature can see. Quantity roles, the matrix row "repeated values in different roles" (plan WP-04 step 4): `tests/test_quantity_roles.py` and the two role rows of `_CONFLICTS` (WP-04.3, [PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188)). A bare `12'` against `12'-6"` stays two findings since WP-04.4 (the signature's `feet_inches` pairs; `tests/test_quantity_residuals.py`, the row moved to `_CONFLICTS`), and so do WP-04.1's partial signatures (N19) (WP-04.4, [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189)) |
| N2 | Cross-QC dedup destroys distinct claims sharing sheet/quote/legs | P0 | 06.1 | implemented+validated | `tests/test_cross_qc_validation_and_dedup.py` (WP-06.1, [PR #167](https://github.com/Abe-Borg/drawing-analyzer/pull/167)): the review's valve/horsepower pair (one primary, quote and legs) survives cross-QC on the whole-set and sharded paths, and the ledger keeps both (overlap 0.273, and 0.353 when both texts name the sheets); through the pipeline on both paths each is its own `QC-###`, dual-crop verified (a call each), investigated when the crop cannot settle it, inked on both sheets with every placement proven, and exported (`findings.json`, `findings.csv`, `markup_manifest.json`); a later copy that is more severe or carries the action keeps what it adds (the ledger's merge); identical copies from a shard and the reconciler, or from reconcile pair calls, collapse to one; `test_dedup_keeps_distinct_conflicts_sharing_a_primary_quote` unchanged. The ledger's half: it still folds two different conflicts whose terse texts both name the same two sheets (N30, WP-03.5; recorded limit), and it keeps a re-report phrased apart as two entries (the accepted cost, WP-06.4) |
| N3 | Reused operand membership (and fabricated quotes) give false DETERMINISTIC | P0 | 07.1 | implemented+validated | `tests/test_arithmetic_operand_grounding.py` (WP-07.1, [PR #163](https://github.com/Abe-Borg/drawing-analyzer/pull/163)): the review's `sum [20,20,20] = 40` on `20 + 20 = 40` and on `20 20 TOTAL 40`; a fabricated (UNANCHORED) quote; a quote printed only on another sheet; an unresolved sheet (id not in the set, and no sheets); the stated result reusing a term's number; a FUZZY quote that dropped a printed operand; a quote that starts inside `2-1/2"`; verification eligibility and the trust note; the pipeline sending the N3 mismatch to the crop verifier while the grounded one stays DETERMINISTIC; failures while anchoring or deciding leave it UNCERTAIN. Kept: repeated printed values, equal values in two spellings, a result printed in its own right, `exact_ambiguous`, a vetoed FUZZY anchor. Role swap, sum versus product and A8 were closed by WP-07.2 (A8 row) |
| N4 | Refused/truncated digests and critiques accepted and cached | P0 | 01.2, 01.4, 01.6, 01.8, 10.4 | open (digest part implemented+validated in 01.2; critique part implemented+validated in 01.4, its retries (a batch read's follow-up batches, the raised cap on both transports) in 01.8; the planner, identity, synthesis, focus, harvest structuring and verification implemented+validated in 01.6; the cache map (10.4) stays open) | `tests/test_digest_terminal_outcome.py` (both transports, both cache levels, the read-side reject, the warm re-run of a refusal the old code cached, the delivery contract) and `tests/test_drawing_acceptance.py::test_a_refused_or_unfinished_digest_holds_the_run_below_complete` (WP-01.2, [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156)). Critique (WP-01.4, by the owner's rules): `tests/test_critique_terminal_outcome.py` (128): every non-finished stop reason (`max_tokens`, `model_context_window_exceeded`, `refusal`, `None`, `tool_use`, `pause_turn`, `compaction`, an unknown value) over a closed, an explicit-empty and an unclosed-but-complete findings object, and a bare structured object, is a failed read that keeps nothing and bills its tokens, on both transports (`outcome_from_message`, `_outcome_from_envelope` incl. dict shapes and a missing `stop_reason`, `critique_sheet_self_consistent`, `collect_critique_batch`), and `end_turn`/`stop_sequence` are unchanged; never cached at either level; through the pipeline on both transports: one read cut off, refused, ended early or unknown is PARTIAL (items 2 -> 1, the coverage line, the sheet named with the read's error, usage PARTIAL, no finding or arithmetic claim from the cut read, warm re-read), both cut off FAILED, the 400 gap PARTIAL, every read raising FAILED, finished reads COMPLETE and served warm (items 2 -> 2), two sheets one cut (4 -> 3), a sheet with no input skipped, and an entry stored under contract 2 missing and left on disk; `tests/test_drawing_cache_identity.py::test_wp_01_4_moves_every_critique_key_and_no_other_key` and `::test_a_critique_entry_from_wp_04_2_misses_and_is_never_deleted` (WP-01.4, [PR #171](https://github.com/Abe-Borg/drawing-analyzer/pull/171)). Remaining: the cache map and the other writers' admission predicates (WP-10.4) Set-level consumers and verification: `tests/test_consumer_terminal_outcomes.py` (every non-finished kind per consumer, not cached; the pipeline statuses; the stage terms) and `tests/test_response_shapes.py::test_a_refused_synthesis_or_focus_report_is_not_kept_or_cached` (flipped) (WP-01.6, [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184)) Critique retries (WP-01.8, [PR #186](https://github.com/Abe-Borg/drawing-analyzer/pull/186), by the owner's rules): `tests/test_batch_critique_recovery.py` (a transient, expired, routed-refused or cut batch read recovered in a follow-up batch and cached under the requested key; not a permanent, canceled, unrouted, context-window, `None`, continuation, unknown or malformed read; the per-sheet budget; the kept read's wording; a stuck round; the file release; the real-time raised cap; the pipeline on Hybrid, Economy and Fast) |
| N5 | Verification COMPLETE with no judgments or with skipped items | P0 | 01.1 | implemented+validated | `tests/test_drawing_acceptance.py::test_verification_is_complete_only_when_every_eligible_finding_was_judged` (six of the plan's seven cases, plus all-truncated and all-skipped) and `::test_a_later_investigation_never_erases_the_verification_outcome` (the seventh); `tests/test_drawing_verify.py` completeness section (WP-01.1, [PR #155](https://github.com/Abe-Borg/drawing-analyzer/pull/155)) |
| N6 | Duplicate sheet labels bind first-wins (whole-set, dedup, arithmetic, legs) | P1 | 06.2 | implemented+validated | WP-06.2: host handles and one resolver on both paths, an id two sheets carry refused and counted; claims rebound; claim dedup by page; arithmetic by-id refuses; leg targets are pages; prose synthesis map refuses (`_dedup_findings` was replaced by WP-06.1). `tests/test_cross_qc_source_binding.py::test_whole_set_binding`, `::test_an_ambiguous_reference_never_binds_the_first_source`, `::test_pipeline_a_conflict_between_two_same_label_pdfs_is_verified_and_inked_on_both`, `tests/test_source_identity.py` (WP-06.2 section). The investigation tools' id map is WP-13.1's |
| N7 | Calculator accepts malformed numbers; inexact large integers | P1 | 20.1 | open | |
| N8 | Stable publish ignores the acceptance hold (it happened for 1.7.0) | P1 | 23.1, 23.6, O-1, O-5 | open (publish gate implemented+validated in 23.1; the O-1 and O-5 parts stay open) | `tests/test_release_acceptance_gate.py` (WP-23.1, [PR #154](https://github.com/Abe-Borg/drawing-analyzer/pull/154)). Remaining: O-1 (the published v1.7.0 and its record), O-5 (protect and confirm the `release` environment and a `v*` tag ruleset), WP-23.6 (commit and artifact binding) |
| N9 | Overflow-note index/bookmark links land at the page top, not the row | P2 | 21.3 | open | |
| N10 | Prose-harvest matching ignores measurement signatures (4 in absorbed by 6 in) | P0 | 09.2 | implemented+validated | `tests/test_prose_match_signatures.py` (WP-09.2, [PR #169](https://github.com/Abe-Borg/drawing-analyzer/pull/169)): the four measured cases (4/6 inch, 165/150 psi beside a shared 175 psi, P-2/P-1, 550/500 gpm) no longer match, against a plain or a SHEET entry (`test_n10_a_distinct_claim_is_not_matched`, and the axis each is refused on), and each becomes its own entry, structured with a client and degraded without one, with the entry it used to join unchanged (`test_n10_with_a_client_*`, `test_n10_without_a_client_*`); an opposite-polarity item is refused against a plain or a degraded entry, both directions; a synthesis item is refused against a conflict with other legs; the next-best compatible candidate wins; both callers agree (two refused items run as two parallel chains, and the sequential and parallel paths build the same ledger); end to end through the pipeline (`test_pipeline_a_distinct_prose_claim_is_its_own_finding`). Kept: restatements, twins, the gauntlet (`test_gauntlet_prose_outcomes_are_exact`). Recorded limits: a SHEET absence with no absence word; a refused presence item degraded to SHEET folds into an absence entry (counted `folded`) |
| N11 | Synthesis conflict extraction is negation-blind | P1 | 09.1 | implemented+validated | `tests/test_prose_filler_and_assurances.py` (WP-09.1, [PR #168](https://github.com/Abe-Borg/drawing-analyzer/pull/168)): the two review sentences and 14 equivalents are not conflicts (`test_n11_*`), make no call and no entry, and are counted in `assurances` (`test_a_dropped_assurance_is_counted_observationally`); 30 real conflicts that carry a "no", a negated verb, a contrast or a value beside an assurance survive (`test_real_synthesis_conflicts_survive`), with their anchors, and the gauntlet's set-level conflict is unchanged; through the pipeline: `test_pipeline_filler_and_assurances_cost_nothing` |
| N12 | Matches ignore word boundaries (`VAV-2` inside `VAV-2-1`; `AHU-10` inside `AHU-101`) | P0 | 05.1, 05.2 | implemented+validated | Cross-QC part: `tests/test_cross_qc_grounding.py` (WP-05.1, [PR #165](https://github.com/Abe-Borg/drawing-analyzer/pull/165)): `AHU-10`/`AHU-101`, `VAV-2-1`/`VAV-2-10`, `VAV-2`/`VAV-2-1`, `AHU-1`/`AHU-1-2`, `P-1`/`P-10`, `P-1`/`XP-1`, `M-101`/`M-101A`, two long quotes ending inside a tag, a quote starting inside a word, and a tag inside a list written without spaces never ground; `P-1,`, `(P-1)`, `P-1.`, `P-1:`, `NOTE 3:`, `568 L/MIN` in `(568 L/MIN)` and a tag printed both alone and inside a longer one still do; the leg is dropped. Anchor part: `tests/test_anchor_whole_words.py` (WP-05.2, [PR #166](https://github.com/Abe-Borg/drawing-analyzer/pull/166)): `VAV-2` on `VAV-2-1 SERVES ROOM 12`, `AHU-1` on `SEE AHU-1-2 SCHEDULE`, `ACCESS PANEL AT VAV-2` on `…VAV-2-1 TYP` and `2-1 SERVES` on `VAV-2-1 SERVES ROOM` (EXACT before) and the 17-token note quoting `VAV-2` or `AHU-1` against one printing `VAV-2-1` or `AHU-1-2` (FUZZY before) never anchor, nor `1/2" PIPE` on `2-1/2" PIPE` or a sub-phrase starting inside a word; a tag printed both alone and inside a longer one anchors `exact` on the one alone, in both orders; WP-05.1's cut-word and whole-word tables run through the anchor; verification and investigation no longer see the N12 finding; the pipeline makes it a `[QUOTE NOT FOUND]` callout with no verification call. Recorded limit: a letter-only tag (`VAV-A` in `VAV-A-1`) inside a long window |
| N13 | Cross-QC and anchor normalizers disagree (curly quotes, `½`, `×`, `Ø`) | P1 | 05.1 | implemented+validated | `tests/test_cross_qc_grounding.py` (WP-05.1, [PR #165](https://github.com/Abe-Borg/drawing-analyzer/pull/165)): `PROVIDE 6” DRAIN`, `2½"`↔`2-1/2"` (both ways, and `2 1/2"`), `O6`↔`Ø6`, `300×200`↔`300x200`, primes, curly quotes, a fraction slash, a non-breaking hyphen, a hyphen written as a space and a zero-width space all ground; `.5`/`5`, `5`/`0.5`, `5`/`-5`, `1`/`1.5`, `12`/`12,500`, `2"`/`1/2"`, `2`/`2½"`, `12`/`12'-6"`, `30`/`30%`, a changed number and a changed unit never do; `cross_qc._norm_for_match` is `anchor._normalize`; the per-word normalization equals the whole-string one over a Unicode corpus; a reconciled leg joins its fact across a curly inch mark, and two facts spelled that way with different tiles collide and give no tile |
| N14 | Degraded cross-QC never cached: re-billed every warm run, run stays PARTIAL | P1 | 06.3, 25.4 | open | |
| N15 | Findings from errored/refused/truncated digests ingested unlabelled | P1 | 01.3 | implemented+validated | `tests/test_digest_partial_reads.py` (WP-01.3, [PR #170](https://github.com/Abe-Borg/drawing-analyzer/pull/170)), by the owner's rule (held out, listed, counted): through the pipeline, an exhaustive run with one sheet's read truncated, refused, ended early or out of context window holds its findings out of the ledger (no QC number, anchor, verification, placement; not in `findings.json`, `findings.csv` or `markup_manifest.json`; not a report finding row) while the finished sheet's finding is numbered as before (`test_n15_exhaustive_run_holds_the_findings_out`), the same on a standard run (`test_n15_standard_run_holds_the_findings_out`); the sheet's own export file lists them under FAILED and its report card lists them escaped (`test_sheet_file_lists_held_out_findings_under_failed`, `test_report_card_lists_held_out_findings_escaped`); counted in `ctx.digest_findings_held_out`, a digest-stage warning, `findings_held_out` in run.log and `digest_findings_held_out` in `run_manifest.json` (`test_run_log_sheet_line_counts_held_out_findings`, `test_manifest_held_out_summary`); a finished run holds nothing out (`test_n15_a_finished_run_holds_nothing_out`); with N16, the kept first read's findings are held out (`test_n15_and_n16_the_kept_first_read_is_held_out`) |
| N16 | A raised-cap retry can lose the first (truncated) read | P1 | 01.3 | implemented+validated | `tests/test_digest_partial_reads.py` (WP-01.3, [PR #170](https://github.com/Abe-Borg/drawing-analyzer/pull/170)), by the owner's rule (one rank, later wins ties, the discarded attempt named): real time, a retry that comes back empty, refused (with and without text) or raises keeps the first read's prose, findings and stop reason, with both attempts' usage, and names the retry (`test_rt_worse_retry_keeps_first_read`, `test_rt_raising_retry_names_the_failure`), for a closed and a salvaged unclosed block; a partial or finished retry still wins (`test_rt_partial_retry_replaces_partial_first`, `test_rt_finished_retry_wins_and_is_cached`); an empty first read takes the retry (`test_rt_empty_first_read_takes_the_retry`); never spliced (`test_rt_never_splices_two_reads`); batch, on both recovery transports, the follow-up batch and the fresh-batch rounds (`test_batch_worse_retry_keeps_first_read`, incl. an errored envelope), the direct rescue landing worse or raising (`test_direct_rescue_*`), several discarded rounds counted (`test_several_discarded_retries_are_counted`), the best read kept across rounds (`test_multiround_keeps_the_best_read_so_far`), the harvest holding a partial read against a worse or unreached rescue (`test_harvested_partial_read_survives_*`), a content-free harvested read still parked; the one helper over a 20-case table (`test_keep_digest_read_table`); nothing new cached on either transport (`test_a_kept_partial_read_is_never_cached`) |
| N17 | References to FM-numbered sheets are never reported as missing | P1 | 08.4 | open | |
| N18 | Contradictory transcriptions of one quote counted as independent checks | P1 | 07.3 | open | |
| N19 | W×H duct sizes, `20A`/`480V`, ranges and lists get no or partial signature | P0 | 04.1 | implemented+validated | `tests/test_quantity_signature.py` (the size, volt, amp, range and list tables; the negative corpus; the `N19 …` pairs; `test_a_shared_name_is_not_a_shared_quantity`) (WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157)). Covers the named forms. The partial signatures WP-04.1 left by decision are read whole since WP-04.4 (the owner's rules): `to` ranges and `between ... and`, `and`/`or` lists, loose-comma lists of three or more numbers, and a compact `A` beside a voltage (`tests/test_quantity_residuals.py`; the three rows moved from `_RECORDED_LIMITS` to `_CONFLICTS` in `tests/test_quantity_signature.py`) (WP-04.4, [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189)). Still unread by the owner's decision, recorded limits: two numbers joined by a comma alone (`2, 4 in`), a compact `A` with nothing electrical beside it (`20A circuit`). **A conflict hidden by a shared value is N1, not N19:** a pair whose differing quantities sit beside a shared one (`6 in` / `4 in` beside `100 psi`; `12'-6"` / `12'-8"`, both `12ft`) merged until WP-04.2 fixed N1 |
| N20 | Investigation executes and echoes pre-fallback `tool_use` blocks | P1 | 13.4 | open | |
| N21 | Files-API failure fallbacks send full-rate requests under Economy; inline can exceed the size limit | P1 | 18.1, 18.2 | open | |
| N22 | Code and help text claim uploads "expire server-side"; they persist until deleted | P1 | 18.4, 18.5 | open | |
| N23 | GUI cost preflight never runs in a default install (no profiles ship) | P1 | 15.1 | open | |
| N24 | `render.list_sheets` runs on the UI thread outside the preflight lock | P1 | 15.1 | open | |
| N25 | `DRAWING_ANALYZER_CRITIQUE_RUNS ≥ 3` fabricates cross-family corroboration | P1 | 22.2 | open | |
| N26 | Chat transcript kept in `localStorage` on `file://`, readable by other local files | P1 | 20.3 | open | |
| N27 | A stream that ends without `message_stop` is cached as a complete digest | P0 | 01.2 | implemented+validated | `tests/test_digest_terminal_outcome.py::test_n27_a_real_sdk_stream_that_ends_without_message_stop_is_not_a_digest` (the real SDK's stream accumulator over an in-process transport, through `digest_sheet`), plus the `stop_reason=None` cases on both transports, at both cache levels and through the pipeline (WP-01.2, [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156)) The same shape on the streamed set-level stages (planner, synthesis, focus): `tests/test_response_shapes.py::test_a_stream_cut_before_message_delta_is_not_kept_or_cached` (flipped; WP-01.6, [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184)) |
| N28 | The geometry branch folds two different issues that quote one tag once both anchor there (`PUMP P-1` voltage / impeller); the loser's text is lost | P0 | 03.7 | implemented+validated | `tests/test_position_is_not_sameness.py` (WP-03.7, [PR #162](https://github.com/Abe-Borg/drawing-analyzer/pull/162)): the pair on one rectangle, through the lifecycle in both orders with its numbers and evidence directories, through the pipeline (two digest findings quoting `VAV-3`), and between findings anchored before ingest (Pass A); the predicate reads no rectangle; Pass B adds no fold over generated sets. The recorded limit is flipped: `tests/test_pass_b_complete_link.py::test_two_issues_that_quote_one_tag_stay_apart_after_anchoring`. The pair still shares one content `id` (B8: WP-03.4, WP-21.3) |
| N29 | A merged entry's representative follows arrival order once three or more duplicates merge: an earlier merge's severity union feeds the next `_grounding_quality` comparison | P1 | 03.5 | open | Found by WP-03.2 and pinned as a recorded limit: `tests/test_qc_numbering_tiebreak.py::test_recorded_limit_a_merged_entrys_representative_follows_arrival_order` (`_N29_REPRESENTATIVE`: X's bundle in two of six orders, Z's in four; flip it) |
| N30 | The quote branch (equal quote, text overlap ≥ 0.4) folds two different issues that share boilerplate wording (`PUMP P-1` impeller / selected flow, overlap 0.5); the loser's text is lost | P1 | 03.5 | open | Found by WP-03.7 while measuring N28 (not fixed there; reproduced in its handoff). WP-03.5's lossless observations keep the loser's text; keeping the two apart needs a rule backed by labelled evidence (O-10), not a new threshold (U11). Since WP-06.1 cross-QC hands the ledger every distinct conflict, and its texts name both sheets: on a synthetic corpus the ledger folds 45 of 66 terse same-pair conflicts (4 of 66 in full sentences, 0 without sheet names); pinned: `tests/test_cross_qc_validation_and_dedup.py::test_recorded_limit_n30_a_terse_same_pair_conflict_folds_in_the_ledger` |
| N31 | A synthesis section heading joins an item: glued to the bullet above it, "**Cross-sheet / cross-discipline conflicts**" makes that bullet a conflict naming its sheets; in paragraph layouts under `###` or bold headings the whole run is one item, which no negation rule can read | P1 | 09.1 | implemented+validated | Found by WP-09.1 while measuring N11 (6 layouts; 3 affected) and fixed there ([PR #168](https://github.com/Abe-Borg/drawing-analyzer/pull/168)) by the owner's decision: synthesis items are split per section with the report's `split_into_sections` (read, not changed). `tests/test_prose_filler_and_assurances.py::test_a_section_header_never_joins_a_synthesis_item` (3 layouts), `::test_a_real_conflict_under_a_header_is_extracted_alone`, `::test_pipeline_filler_and_assurances_cost_nothing` (a glued heading, end to end), `::test_a_label_heading_is_never_a_conflict` (40 labels); a heading that states a conflict is still read (`::test_a_heading_that_states_a_conflict_is_still_read`, `::test_codex_a_whole_line_bold_conflict_is_harvested`; Codex review) |
| N32 | A digest heading that states something is never read: `split_into_sections` makes a whole-line bold sentence (or a `###` heading) inside the digest a section header, so its text is neither a prose item nor counted, and the section it starts is classified by it | P2 | 09.3 | open | Found by WP-09.1 from the Codex review of its synthesis split (P2), where the same defect was a regression and is fixed (a heading that is not a listed label is an item of its own). In the digest channel it predates WP-09.1 and is not fixed there: the digest prompt fixes the section structure, so a bold statement inside a Coordination/Conflict section is rare. `prose_harvest._LABEL_RE` / `_is_label` is the shared test to reuse; the ordinals of the section's items would move. Routed to WP-09.3 by the owner (WP-09.2): measured broader, since a statement heading with no Coordination/Conflict keyword also makes the bullets under it `other` (2 of 4 layouts), and `_is_label` does not fit the digest (6 of its 8 standard section names are not listed labels) |
| U1 | Serving model, fallback iterations and partial-stream billing unrecorded | P1 | 14.3, 14.6, 01.7 | open (the partial-stream part implemented+validated in 01.7; the serving model and fallback iterations (14.3, 14.6) stay open) | `tests/test_interrupted_streams.py` (the capture site through the real SDK at every cut x end on both namespaces and both 5.5 models; the retry predicate over every API error type; the wording; the digest, the critique, the review plan, synthesis, the focus report, the investigation, the batch direct rescue and inline fallback through the pipeline or the batch collector; the usage surfaces) and `tests/test_response_shapes.py::test_an_interrupted_digest_stream_is_retried_and_its_usage_kept`, `::test_an_interrupted_stream_is_retried_and_keeps_its_usage` (flipped; WP-01.7, [PR #185](https://github.com/Abe-Borg/drawing-analyzer/pull/185)) |
| U2 | Fallback text joins and selective history replay | P1 | 01.6, 12.1, 13.4, 19.2 | open (the fallback-aware join implemented+validated in 01.6; citation splits (12.1), the investigation's pre-fallback tool uses (13.4) and chat history replay (19.2) stay open) | `tests/test_reply_text.py` (the rule over API JSON; every fallback shape through the real SDK on both namespaces, create and stream, Opus 5.5 and Sonnet 5.5; the plain namespace's `TextBlock`; the structural pin) and `tests/test_response_shapes.py::test_a_fallback_inside_the_findings_json_keeps_the_finding`, `::test_a_fallback_in_the_prose_reads_as_the_served_text`, `::test_a_fallback_in_a_critique_is_a_good_read` (flipped); `tests/test_consumer_terminal_outcomes.py::test_a_fallback_split_stage_reply_reads_as_one_text` (WP-01.6, [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184)) |
| U3 | Generic `output_config` 400 disables task budgets process-wide | P1 | 13.1 | open | |
| U4 | Oversized inline fallback; upload quota failures (see N21) | P1 | 18.1, 18.2, 18.4 | open | |
| U5 | Remote orphan files; daemon-only cleanup (see N22) | P1 | 18.5, 17.2 | open | |
| U6 | Cross-QC output cap shared with thinking; no truncation recovery | P1 | 06.3 | open | |
| U7 | Cross-QC 4k text budget and 40-fact bottleneck | P1 | 06.3, 25.4 | open | |
| U8 | Whole-set cross-QC path does no grounding | P0/P1 | 06.2 | implemented+validated | WP-06.2: whole-set items go through the sharded validator, grounded against the uncapped text, losses counted. `tests/test_cross_qc_source_binding.py::test_a_quote_past_the_prompt_cap_grounds_on_the_whole_set_path`, `::test_short_tags_get_no_exemption`, `::test_the_same_item_binds_alike_on_the_whole_set_and_sharded_parsers`, `tests/test_evidence_tail.py::test_forty_entries_ground_the_tail_quote_on_the_whole_set_path` |
| U9 | Pruning can reap a live-but-idle run's work dir | P1 | 18.3 | open | |
| U10 | Mentioned vs adopted codes; missing edition families | P1 | 12.3, 12.5 | open | |
| U11 | Prose-match threshold and call prevalence (see N10) | P1 | 09.2 | implemented+validated | WP-09.2 ([PR #169](https://github.com/Abe-Borg/drawing-analyzer/pull/169)): instrumented (every enumerated item has one outcome with the structuring call it cost, the candidates the veto refused and whether its finding folded; `vetoed`, `folded` and the per-channel table in `run.log` and `run_manifest.json`) and labelled (`tests/test_prose_paraphrase_corpus.py`: 47 hand pairs, 22 same and 25 different, and the 45 must-keep findings pairwise, 990 different pairs; pinned at 0.5 to 0.9 with and without the veto; at 0.7 without the veto 22/22 same match and 19/25 different are absorbed, with it 18/22 and 5/25; 0/990 either way). Threshold unchanged (`test_the_match_threshold_is_unchanged`); lowering it is a later decision that must read the corpus |
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
| U26 | Test fake fidelity, no batch canary, no socket guard | P0 | 02.1–02.4 | open (socket/credential guard and `network` opt-in implemented+validated in 02.1; strict request-side fakes and real-SDK contract tests implemented+validated in 02.2; response-side fidelity fixtures implemented+validated in 02.3) | `tests/test_hermetic_guard.py` (WP-02.1, [PR #153](https://github.com/Abe-Borg/drawing-analyzer/pull/153)); `tests/test_strict_fakes.py`, `tests/test_sdk_contract.py` (WP-02.2); `tests/test_sdk_responses.py`, `tests/test_response_shapes.py` (WP-02.3, [PR #181](https://github.com/Abe-Borg/drawing-analyzer/pull/181)). Remaining: batch canary (02.4) |
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

### 2026-10-01 — WP-06.2: whole-set cross-QC on host handles, grounded, claims rebound, framing keyed (PR pending)

- **Slice and IDs:** WP-06.2. N6, U8 and K2 implemented+validated. **D-8 is
  decided** (its page part, WP-11.1's, stands unamended; this slice decides the
  binding part). D-2 and D-4 gain a note each; the migration register gains
  three rows (the cross-QC contract, the cross-QC key's framing, the A/B record
  contract). WP-06 is not done: WP-06.3 and WP-06.4 remain (WP-06.4 waits on
  WP-03.4), and the N30 note stays WP-03.5's.
- **Base.** `main` = `origin/main` = `acaa55e` (WP-04.4's merge,
  [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189)). Open PRs:
  [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot)
  and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0
  support), neither a remediation slice; nothing else in flight for WP-06.
  Baseline **5,907 passed, 2 skipped, 10 deselected** (518 s), as expected; the
  two skips are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0,
  PyMuPDF 1.28.2 (`pip install -e ".[dev,browsertest]"`, `cffi`, `ruff==0.14.5`).
  No SDK probe was needed. The container restarted once mid-session (the VM, not
  the disk): nothing was lost, and the work was committed and pushed right after.
- **The request's facts, re-verified** (all held; additions marked):
  - `_CROSS_QC_CACHE_CONTRACT` 8 (`cross_qc.py:195`), `_CRITIQUE_CACHE_CONTRACT`
    5, `_SCHEMA_VERSION` 10, the WP-01.7 tripwire `(10, 5)`, the A/B
    `RECORD_CONTRACT_VERSION` 5. **Six** tests pin cross-QC's contract, the six
    the request lists.
  - The whole-set `sheet_map` (first detection wins, a warning), `_fallback_id`
    (`stem-pN`), `===== SHEET {sheet_id} =====`, whole-set claims by
    `parse_numeric_claims(raw)` with a `sheet_id` only, `arithmetic._build_maps`
    first-wins, label-based `critique._leg_targets`, no whole-set grounding, and
    the framing outside the key: each as described.
  - **Added: two more first-wins label maps.** The prose harvest's synthesis id
    map (`prose_harvest.harvest_prose`, `if sid not in id_map`) and
    `investigate._sheet_id_map` (`setdefault`, then overwritten by findings'
    ids). And `cross_qc._dedup_claims` keyed on the id, so one row printed on two
    same-id PDFs was one claim.
  - **The consumers** of a cross-QC binding, and which read a label as identity:
    `Ledger.add` buckets by `source_page_key` (no); `annotate._units_for_finding`
    places each leg by its source (no; the leg's label is its mark's text);
    `verify._has_anchored_legs` and the dual-crop key (source key and label,
    both inputs; no); `investigate._candidates` (no), `investigate._sheet_id_map`
    (**yes**, tool addressing); `export` / `html_report` (display only);
    `run_manifest.json` (`cross_qc_discards`, `cross_qc_invalid`); the arithmetic
    auditor (**yes**, `by_id`); the prose harvest's synthesis legs (**yes**);
    `critique._leg_targets` (**yes**); the A/B harness's `identity_key` uses leg
    labels too, but its signature check now separates two same-label legs (a
    candidate, never EXACT).
  - **The unnamed consumers:** the gauntlet's whole-set `CROSS_CONFLICT`
    answers by `sheet_id` (a legacy reply, unique ids) and still grounds (its
    quotes are whole printed lines); `tests/test_drawing_acceptance.py` and the
    whole-set fixtures of `tests/test_drawing_cross_qc.py` answer by label too.
- **Measured before any code** (a scratch pytest plugin, never committed:
  every whole-set item's binding, every `classify_quote_evidence` verdict with
  its caller, every sharded item with its counter delta, every `sheet_map`
  collision, every `_build_maps` lookup, every `_is_duplicate` call on a
  leg-bearing pair, every prose and investigation id map):
  - On `origin/main` (instrumented full suite, 5,907 passed): 295 cross-QC
    calls (265 whole-set, 30 sharded), 75 whole-set items (43 through
    `cross_sheet_qc`, 32 from two B6 tests calling the validator directly), 122
    sharded items, 924 grounding verdicts, 177 arithmetic lookups (37 by id),
    50 leg-bearing merge decisions, 427 prose id maps, 247 investigation maps.
    **Replayed offline with 0 unexplained mismatches** (12 sharded records
    differ only in the counter delta: direct test calls that passed no counter).
  - **Label collisions are real in the suite:** 11 pipeline cross-QC calls had
    an id on two or three PDFs (`M-101`, `P1`, `VAV-1`), and none of their
    replies named it; 0 used fallback ids collided; 0 arithmetic by-id
    collisions; 20 prose id maps collided and 0 synthesis conflicts bound
    through one; 0 investigation map collisions. Every pipeline call was
    already in `(source_id, page)` order.
  - **The recall cost of grounding the whole-set path** (item replay, the
    §7.2 counters): of the 43 whole-set items, 29 kept, 6 already unplaceable,
    6 refused for a field (unchanged), **2 newly dropped, both because the
    fixture's sheets do not print the quote at all** (the anchor finds it
    nowhere: **0 dropped for a paraphrase**); legs 54 grounded, 10 admitted at
    reduced trust (a tile with no words), 2 ungrounded, 6 unresolved.
  - **Each option prototyped behind a scratch switch** (a worktree of
    `acaa55e`) and run over the 58 cross-QC-related test files; the full
    suite under all the recommended options moved 10 tests, each explained:

    | Option | Extra tests moved |
    |---|---|
    | All recommended (the base) | 10: 2 fixtures whose quotes their sheets do not print, 2 WP-06.1 pins of `discards is None`, the claims test, 2 map fakes reading `===== SHEET (S\d+) =====`, 2 label-fold `_leg_targets` tests, 1 A/B fixture |
    | Sort by source id (vs caller's order) | +0 |
    | Label-derived handles (`M-101`, `M-101#2`) | +18 (every sharded fixture hardcodes `S###`) |
    | No id beside the handle in shard headers | −2 (the two map fakes) |
    | `_leg_targets` by label | −3 (−1 once a sourceless leg keeps its plain label) |
    | Prose synthesis map first-wins | 0 |
    | Arithmetic: check an ambiguous claim unplaced | 0 |

  - **Constructed cases, `main` → prototype:** a reply naming `M-101` on two
    PDFs bound the first, now refused and counted; a conflict between the two
    `M-101` sheets was inexpressible, now binds both by handle; a tail quote past
    the prompt cap was kept unchecked, now TEXT_GROUNDED; an unprinted quote or
    short tag `P-1` was kept, now dropped and counted; a scanned leg had no
    evidence state, now TEXT_EVIDENCE_UNAVAILABLE with the tile fallback; an
    arithmetic claim on the shared id was checked on the first PDF, now refused.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, eight choices, measured case tables; every recommended option taken):
  - **Round 1.**
    - **Handles: `S###`, the id beside each, both paths** (one header helper;
      the instructions ask for handles in the json and ids in text; one
      resolver: a handle, else an id one sheet carries). Not taken: the id
      beside the handle on the whole-set path only; label-derived handles.
    - **Grounding: ground the whole-set path; keep the WP-03A scope test's
      assertions and id, record the reversal in its docstrings, add tests
      beside it.** Not taken: extend that test itself; keep the path
      ungrounded.
    - **Ambiguity: discards counters and a stage warning, observational**
      (`legs_ambiguous_label`, `facts_ambiguous_label`; the stage keeps its
      status; cached with the counts). Not taken: counters only; under
      `legs_unresolved_handle`; holding the stage PARTIAL.
    - **Order: sort entries by `(source_id, page)`** where source ids are
      assigned. Not taken: the caller's order.
  - **Round 2.**
    - **Arithmetic: count an ambiguous claim, don't check it**
      (`arithmetic_ambiguous_sheet`). Not taken: check it unplaced (an
      unrouted finding, a FAILED receipt); a set-level note.
    - **`_leg_targets`: source identity**, A/B 5 → 6, the A/B fixture re-pinned.
      Not taken: keep it label-based.
    - **Other maps: the prose synthesis map here, the investigation map noted**
      (on WP-13.1). Not taken: both here; neither.
    - **Contracts: 8 → 9, the framing verbatim in the key's payload, D-8
      decided, the listed re-pins.** Not taken: a hashed framing-version term;
      the bump only, K2 later.
  - **Composition, decided in the implementation within those rules** (for the
    next session): a handle always names its own sheet, even where another
    sheet's own id reads like a handle (that sheet is reachable by its handle
    only); a reply's `sheet_handle`, else `handle`, else `sheet_id` is the
    reference, on both paths; the finding carries each sheet's id from the
    manifest, never the reply's spelling; ordering applies only when every
    entry has a source id (natural order, so `SRC-9999` precedes `SRC-10000`);
    an unresolved claim keeps its reference and no source (the auditor
    decides); a fact keeps the resolved handle; the arithmetic refusal happens
    after the dedup and before the numbers are read; the prose map keeps an
    ambiguous id as a key (so the statement still counts as naming an in-set
    sheet) mapped to no sheet.
- **What changed** (production):
  - **`cross_qc.py`:** `_HANDLE_RULE` spliced into the whole-set and map
    instructions (the whole-set fields are `sheet_handle`; claims set
    `sheet_id` to the handle); the framing strings named
    (`_WHOLE_SET_HEADER_TEMPLATE`, `_MAP_HEADER_TEMPLATE`,
    `_SHEET_TITLE_TEMPLATE`, `_SHEET_BODY_TEMPLATE`, `_MAP_TASK`, the reconcile
    header, line, fact-line and task strings, `_UNKNOWN_DISCIPLINE`,
    `_TRUNCATION_MARKER_TEMPLATE`) with `CROSS_QC_USER_FRAMING_NAMES` and
    `cross_qc_user_framing()`, held by `_cross_qc_cache_key`;
    `_canonical_order`, `_natural_key`, `_SheetHandles`, `_assign_handles`,
    `_resolve_sheet_ref`; `_sheet_block` (one title-and-body helper for both
    paths); `_finding_from_handles(by_label=)` reads `sheet_id` too and counts
    `legs_ambiguous_label`; `_validate_cross_item` removed; `_parse_facts` and
    `_resolve_claim_handles` resolve through the same resolver;
    `_one_cross_qc_call(handles, counts=)` grounds through the shared validator
    and rebinds its claims; `by_label` threaded through `_map_call`,
    `_reconcile_call`, `_reconcile_facts`; `_dedup_claims` keys on the page
    first; `CrossQCDiscardCounts` gains the two counters and `ambiguity_note()`;
    `cross_sheet_qc` orders the entries, assigns the handles once, records
    `discards` on both paths and logs ambiguity once (`_log_ambiguous`);
    `_CROSS_QC_CACHE_CONTRACT` 8 → 9 with its reason; the module docstring.
  - **`critique.py`:** `_leg_targets` names `"<source>#p<page>"`, a sourceless
    leg keeping its canonical id.
  - **`auditors/arithmetic.py`:** `_AMBIGUOUS_SHEET`, `_build_maps` marks an id
    two pages carry, `_page_of`, `_by_source`, `_names_shared_id`,
    `_resolve_geometry` never returns the marker, `ArithmeticResult.ambiguous`,
    the refusal in `audit_arithmetic`. **`auditors/__init__.py`:** the
    `arithmetic_ambiguous_sheet` stat.
  - **`prose_harvest.py`:** the synthesis id map maps an id two pages carry to
    `None` (the existing set-level path).
  - **`pipeline.py`:** the ambiguity warning after the refused-item warning;
    the `cross_qc_discards` comments.
  - **`scripts/ab_findings_diff.py`:** `RECORD_CONTRACT_VERSION` 5 → 6 with its
    reason.
- **Tests:** **98 new test IDs, 2 removed (renamed), 96 net** (counts from
  `--collect-only`: 5,909 → 6,005): `tests/test_cross_qc_source_binding.py` 75
  (request format 5, the binding matrix 12 + 3, ordering 5, parser-level
  equivalence 9, whole-set grounding 9, claims 7, ambiguity 3, K2 16, the
  contract 1, the pipeline 3), `tests/test_source_identity.py` 17 (leg targets
  9, arithmetic 6, the prose synthesis map 2), `tests/test_evidence_tail.py` 2
  (beside the WP-03A test), `tests/test_ab_findings_diff.py` 4 (2 new, 2
  renamed).
  - **Classified against `origin/main`** (a worktree at `acaa55e` with its own
    `src` first on `PYTHONPATH`; a scratch shim injected the new file's
    parametrize tuple so it collects there): of the 98 new IDs, **59 fail on
    behaviour, 31 fail on a missing name** (the framing names, the handle and
    order helpers, the ambiguity counters, `ArithmeticResult.ambiguous`, the
    new stat), **8 pass** (controls: an unbound claim stays unbound on both
    sides, one claim spelled twice still collapses, a label fold still reads one
    page as one target, the ledger still folds one conflict reported twice).
  - **Re-baselined (the owner's approved re-pins)**, each failing on
    `origin/main` in its new form (28 IDs): the six contract pins (8 → 9);
    `test_cross_qc_returns_numeric_claims` (it asserted no source on a
    whole-set claim); `test_b6_each_refusal_is_counted_once_under_its_first_reason`
    (16 ids) and `test_b6_the_same_item_binds_alike_on_both_validators`,
    re-pointed from the removed `_validate_cross_item` to the one validator,
    assertions unchanged; `test_b6_a_refused_item_is_counted_on_the_whole_set_path`
    and `test_pipeline_a_refused_item_is_a_stage_warning_in_run_log_and_manifest`
    (they pinned whole-set `discards` as `None` / empty); the map fake's header
    regex in `tests/test_cross_qc_grounding.py` (2 tests). Changed and passing
    on both sides: two whole-set fixtures in `tests/test_drawing_cross_qc.py`
    now print the quotes their legs cite; the A/B fixture's legs sit on their
    own pages. The WP-03A scope test's assertions and id are unchanged (its
    docstring and the file's Case 3 text record the reversal).
- **Validation** (this container):
  - Full suite on the code before the docs: **6,003 passed, 2 skipped, 10
    deselected** (510 s). A JUnit diff against the baseline: of the 5,907
    tests in both runs, **0 changed outcome**; 2 only in the baseline (the
    renamed A/B tests) and 98 only here, all passing.
  - **The instrumented diff, `origin/main` vs this branch** (the full suite
    under the probe on both, 6,003 passed here), compared by content: whole-set
    bindings 43 / 43, **0 moved**; arithmetic lookups 177 / 177, 0 moved;
    leg-bearing merge decisions 50 / 50, 0 moved; grounding verdicts 924 →
    1,002, the 78 more being the whole-set legs now grounded (65 TEXT_GROUNDED,
    6 TEXT_EVIDENCE_UNAVAILABLE, plus the re-pointed B6 test grounding both
    sides); the only moved items are 5 sharded findings in four
    `tests/test_cross_qc_validation_and_dedup.py` fixtures whose hand-built ids
    (`SRC-m` before `SRC-e`) are now sorted, so their scripted `S001` names the
    other sheet (the approved ordering rule; the tests still pass).
  - **Speed** (a synthetic 40-sheet whole-set pass, 60 conflicts, about 5k
    characters per text layer, `source_words` cache cleared per round, best of
    3, three alternations): `main` 129–131 ms, this branch 185–186 ms. The
    difference is indexing and grounding 40 sheets, beside a model call that
    takes minutes.
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean. F401/F811/F841 on the
    touched files: 18 hits on both `origin/main` and here, none new.
    `python scripts/scan_secrets.py`: clean (233 tracked files). No key
    anywhere; every new parametrized case has `ids=`; the one invisible
    character in the tests is written `\u2011`.
  - `python scripts/run_acceptance.py`: ACCEPTANCE_RESULT_PENDING
- **Docs:** CHANGELOG (Fixed); CLAUDE.md (the finder bullet, a new paragraph
  on both paths binding through host handles, the discard and refused-item
  paragraphs, the handle-canonicalization sites, the signature's leg targets,
  the prose synthesis binding, I-6 and the arithmetic invariant); README (the
  cross-sheet QC section: handles and grounding on both paths, the ambiguity
  warning; the arithmetic claims; the cross-QC cache history);
  `docs/PERFORMANCE_AND_COST_VALIDATION.md` (A/B v6); the plan (the WP-06 Step 1
  and Step 6 notes, the WP-10 K2 note); DECISIONS (D-8 decided, the D-2 and D-4
  notes, three register rows); PROGRESS (this entry; the WP-06.2 row; WP-06's
  package row; the N6, U8, K2 rows; notes on WP-06.3, WP-10.4, WP-13.1; Next
  up). No dependency changed.
- **Not verified:**
  - Live API behaviour (no budget, O-4; this slice makes no call): whether a
    model answers with the handle, the id, or the whole `S001 = M-101` title
    (the last is unknown and drops the leg); how often real replies name an id
    two sheets carry.
  - Not measurable without real drawings (O-10): how many whole-set conflicts
    a real set loses to grounding (the suite's fixtures lost none to
    paraphrase); how often a set carries one id on two PDFs.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - **A visible behaviour change, by design:** on a set of 40 sheets or fewer,
    a conflict whose quote its sheet does not print is no longer reported; a
    scanned sheet's conflicts carry the reduced-trust caveat and go to the crop
    re-check (more verification calls); a conflict between two same-id sheets is
    now reported.
  - **One-time costs:** the first cross-sheet QC run after upgrading re-runs
    once (contract 9 and the framing key; contracts 4 to 8 are unreleased, so a
    1.7.0 user pays once). A/B arm records written before are refused.
  - **Recorded limits:** a sheet whose own id reads like a handle (`S001`) is
    reachable by its handle only; a reference written as the whole title
    (`S001 = M-101`) is unknown; the A/B harness's `identity_key` still uses leg
    labels (two same-label legs are a candidate, never EXACT, through the
    signature); a hand-built set with an entry lacking a source id keeps the
    caller's order.
- **Found, not fixed:** `investigate._sheet_id_map` addresses the
  investigation tools by sheet id, first-wins then overwritten (a note on
  WP-13.1, which already owns "ambiguous crop targets refused"). The reconcile
  prompt does not ask the model to name sheets by id in its text (unchanged:
  its manifest shows the ids; a wording change there is a prompt edit of its
  own).
- **Next:** in queue order, Wave 2 WP-06.3 (cross-QC terminal honesty; closes
  WP-01 with WP-12.6 and WP-13.4). WP-10.1 … WP-10.4, WP-03.4, WP-07.3 and
  WP-11.3 are available too. The owner question on 5.5 refusal routes
  (WP-01.5) is still open.

### 2026-09-30 — WP-04.4: the tokenizer residuals, and a feet value compared with its inches ([PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189))

- **Slice and IDs:** WP-04.4, the four demonstrated conflicting pairs WP-04.1
  read only in part (N1's bare `12'`; N19's `to`/`and`/`or` ranges and lists,
  loose-comma lists and a bare `20A`), WP-04's last slice. No `DECISIONS.md`
  contract is decided: D-3 gains an input ("as an input, not a decision", the
  WP-03.3 / WP-03.7 / WP-04.3 precedent), D-4 a note, and the migration
  register three rows (the critique contract, the cross-QC contract, the A/B
  record contract). **WP-04 is done** (the owner's decision; the plan's WP-04
  Acceptance check, below).
- **Base.** `main` = `origin/main` = `317636d` (WP-04.3's merge,
  [PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188)). Open PRs:
  [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot)
  and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0
  support), neither a remediation slice. Baseline **5,666 passed, 2 skipped,
  10 deselected** (634 s), identical to WP-04.3's final count; the two skips
  are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0, PyMuPDF
  1.28.2 (a fresh container: `pip install -e ".[dev,browsertest]"`, `cffi`,
  `ruff==0.14.5`). No probe touched the SDK (no SDK 1.8.0 venv needed).
- **The request's facts, re-verified** (all held, corrections marked):
  - `_CRITIQUE_CACHE_CONTRACT` 4, `_SCHEMA_VERSION` 10,
    `RECORD_CONTRACT_VERSION` 4 (two asserts), the WP-01.7 tripwire `(10, 4)`,
    `_CROSS_QC_CACHE_CONTRACT` 7. **Correction:** five tests pin cross-QC's 7,
    not four: the four the WP-05.3 handoff re-pinned plus WP-05.3's own
    `tests/test_anchor_character_stream.py::test_the_cross_qc_contract_moved_for_the_character_stream`.
  - `anchor._same_quantities` imports `critique._quantity_tokens`
    function-locally; it serves the anchor's `char_stream` tier and cross-QC
    grounding (`SourceWords.joined_spans`). It reads the anchor's folded words,
    so a quote's loose commas are folded away before it reads them (only a
    leading-comma spelling such as `2 ,4 ,6` keeps them).
  - `critique._quantity_roles` reads `_quantity_readings` spans; a spelled
    range or list is now one reading, so a role after it binds the whole
    quantity, as after a tight list (`2, 4, 6 in main` → `main=2,4,6in`). No
    role table moved.
  - Every consumer of the one rule: `critique._is_duplicate` (the critique's
    `_cluster`, `Ledger.add` over member snapshots, `reconcile_post_anchor`
    over member histories), `prose_harvest._veto_axes`, the A/B harness
    (`_compatible`, `_conflicting_axes` over stored records). **No other cache
    key holds a merge outcome** (re-verified): the critique cache stores
    post-merge findings; the prose harvest's structuring key hashes the item,
    the sheet's text, the source binding and the request params, never the
    match; cross-QC's `_drop_exact_repeats` is equality only.
  - The 500/550 gpm duplicate folds on main and here (pinned in both files).
  - **Correction (the measurement's scale):** this session's probe records
    every call, not distinct decisions, so its counts are larger than
    WP-04.3's (6,600 / 432 / 1,072 / 769): 22,372 merge decisions in 500
    tests (`Ledger.add` 7,878, `reconcile_post_anchor` 6,118, the fingerprint
    corpus 3,721, direct test callers 2,818, the critique's `_cluster` 1,837;
    8,982 distinct per test, caller and pair), 491 prose-veto records in 113
    tests, 1,268 anchors in 800 tests, 908 grounding verdicts in 406 tests.
  - **Found while measuring:** the anchor's sub-phrase tier places a part of
    a quote (`4 TO 6 IN`) before `char_stream` runs, on main and here, so for
    a flipped join only cross-QC's verdict moves; WP-05.3's agreement ("EXACT
    or `char_stream` exactly where cross-QC grounds") still holds (pinned).
- **Measured before any code** (a scratch pytest plugin, never committed:
  every `_is_duplicate` call with its caller, every `_veto_axes` call, pairs
  serialized through `Finding.to_dict`, every `_anchor_one` result read with
  `getattr`, every cross-QC `_grounded` verdict):
  - On `origin/main` (instrumented full suite, 5,666 passed), **replayed
    offline with 0 unexplained mismatches**: one anchor record differs
    offline, from `test_the_veto_reuses_the_wp_04_quantity_reader`, which
    monkeypatches the reader during the test.
  - Each option prototyped behind a scratch switch and replayed over those
    records (moved merge decisions; every option moved 0 of the 491 vetoes,
    1,268 anchors and 908 grounding verdicts):

    | Option | Decisions moved | Recorded texts whose tokens change (of 841) |
    |---|---|---|
    | Feet: a pair beside the tokens, marks only / every spelling | 2 (the pinned pair) | 0 (17 / 29 gain a pair) |
    | Feet: `{12ft, 0in}` tokens | 2 | 10 |
    | Feet: one token (`12ft6in`) | 2 | 8 |
    | `to` ranges (incl. `between`) | 2 | 1 |
    | `and`/`or` lists | 0 | 0 |
    | Loose lists of three or more | 4 (the pinned pair and the retention pair) | 3 |
    | Loose lists of two | 0 | 0 |
    | A voltage beside / after a compact `A` | 2 | 2 |
    | `circuit` after a compact `A` | 0 | 0 |

    Over every string constant in `tests/`, `src/` and `scripts/` (4,866
    texts) the token changes were: `to` 2, `and`/`or` 2, loose lists 6, two
    loose 1, amps 2, zero-inches token 69, one token 35 (the pair options
    change no tokens; 96 / 121 texts gain a pair).
  - Pinned rows each option moves: the zero-inches token 4 negative/safeguard
    token rows and WP-04.3's readings-equal test; one token every feet-inches
    `_SAFEGUARDS` row and the token-grammar test; loose lists the
    `_NEGATIVE_CORPUS` row and the `_CONSERVATIVE_RETENTION` pair; the pair
    options the signature key-set assertion in `tests/test_quantity_roles.py`.
  - Case tables shown to the owner per option (each residual's pinned pair,
    other spellings and kinds, equivalences, the negative corpus, the
    misreadings), and a constructed cross-QC flip per token-changing option.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, seven choices, measured case tables; every recommended option
  taken):
  - **Round 1.**
    - **Bare feet: a pair rule beside the tokens.** `critical_signature` gains
      `feet_inches`; the token model is unchanged (every `_SAFEGUARDS`
      feet-inches row stays), and the key-set assertion in
      `tests/test_quantity_roles.py` gains the key (approved). Not taken:
      `{12ft, 0in}` tokens (a `6 in` elsewhere still masked the conflict);
      feet-inches as one token (it split `12 ft 6 in` from `12'-6"`); leave it.
    - **Spelled ranges and lists: `to`, `and`, `or`.** Not taken: `to` only;
      leave both.
    - **Loose lists: three or more numbers.** The two pinned rows move
      (approved): the `_NEGATIVE_CORPUS` row reads `["2,4,6in"]` in place, and
      the retention pair `2, 4, 6 in` / `2,4,6 in` moves to `_EQUIVALENTS`.
      Not taken: two or more (`Relocate valve 4, 10 ft` read as a list);
      leave them.
    - **Bare `20A`: a voltage beside it** (after or before), a name word
      still winning. Not taken: after only; also `circuit` after (`connect to
      2A circuit 12` read 2 A); leave it.
  - **Round 2.**
    - **Feet spellings: every spelling** (`12 ft`, `12 feet`, `12 ft 6 in`),
      so `12'` and `12 ft`, one quantity, compare alike. Not taken: the foot
      mark only.
    - **Contracts: critique 4 → 5, A/B 4 → 5, cross-QC 7 → 8.** Not taken:
      critique and A/B only, recording the cross-QC flips as a limit.
    - **The WP-01.7 tripwire: re-pinned to `(10, 5)`.** Not taken: pin only
      the schema version.
    - **WP-04: done, the remaining shapes recorded as limits.** Not taken: a
      WP-04.5.
  - **Composition, decided in the implementation within those rules** (for
    the next session): the guards keep *today's* reading, never a new one: a
    name or reference word before the first number (`_REFERENCE_BEFORE_RE`,
    built on the amp rule's `_NAME_WORDS`, one list, plus page, section,
    step, item, note(s), ... with plurals), the word `in` followed by an
    article or a preposition's object (`_IN_AS_PREPOSITION_RE`), `2 and 1/2
    in`, and a run inside a longer one (`_SPELLED_WITHIN_RE`); only the first
    number may be signed and only the last carries the unit; a list keeps its
    written order (as a tight list); the feet-inches join is spaces and at
    most one hyphen or Unicode dash (`auditors.arithmetic._UNICODE_DASHES`,
    the one dash list), after an optional abbreviation period (`12 ft. 6 in.`,
    one quantity with `12'-6"` in the tokens), never a comma or a sign; the
    pairs are read part by
    part (`_sig_parts`), as roles are, so a text's last feet value never
    joins a quote's first inch value; the voltage-before check searches the
    text between bounds, not a slice (WP-04.3's lesson), so a slope's
    `3H:1V` is not a voltage.
- **What changed** (production):
  - **`critique.py`:** `_NAME_WORDS` (the name list, now shared);
    `_AMP_VOLTAGE_AFTER_RE`, `_AMP_VOLTAGE_BEFORE_RE` and the amp branch of
    `_unit_context_ok`; `_read_spelled` with `_SPELLED_JOIN_RE`,
    `_SPELLED_ELEMENT_RE`, `_SPELLED_WITHIN_RE`, `_REFERENCE_BEFORE_RE`,
    `_BETWEEN_BEFORE_RE`, `_IN_AS_PREPOSITION_RE`, called from `_read_one`
    when no unit follows a plain number; `_feet_inches` and
    `_feet_inches_of_parts` (memoized); `critical_signature` gains
    `feet_inches`; `_feet_inches_conflict`, reported on `measurements` by
    `signature_conflicts`; the tokenizer's header comment, `_quantity_tokens`'
    and `signature_conflicts`' docstrings.
  - **`digest_cache.py`:** `_CRITIQUE_CACHE_CONTRACT` 4 → 5 with its reason.
  - **`cross_qc.py`:** `_CROSS_QC_CACHE_CONTRACT` 7 → 8 with its reason.
  - **`scripts/ab_findings_diff.py`:** `RECORD_CONTRACT_VERSION` 4 → 5 with
    its reason.
- **Tests:** **248 new test IDs, 7 removed, 241 net** (counts from
  `--collect-only`): `tests/test_quantity_residuals.py` 227 (spelled
  quantities 29, the negative corpus 43, misreadings 3, the token identity 1,
  feet-inches pairs 26 + 3 structure tests, residual conflicts 15,
  equivalences 11, retention 4, the 500/550 duplicate 1, chains 4 + 72 (four
  chains × six orders × `_cluster`, `Ledger.add`, Pass B), the rule 4, the
  readings 1, a role after a spelled list 1, the prose veto 4, the anchor and
  cross-QC flips 4, the cross-QC contract 1); `tests/test_quantity_signature.py`
  11 (the four flipped rows × 2 tests, the moved equivalence, two new
  recorded limits); `tests/test_ab_findings_diff.py` 8 (4 residual pairs, the
  stored pairs, the v4 sidecar, two renamed); `tests/test_drawing_cache_identity.py`
  2.
  - **Classified against `origin/main`** (the worktree at `317636d` with its
    own `src` first on `PYTHONPATH`; no shim was needed, the only new name is
    a signature key): of the 257 new or changed IDs (248 new, 9 changed in
    place), **172 fail on behaviour, 31 fail on the missing key**
    (`KeyError: 'feet_inches'`), **54 pass** (controls: 42 of the 43
    negative-corpus rows, the 7 spellings already equal on main, the three
    structure tests that pin what does not change, and the two new recorded
    limits). Every existing test kept its outcome there.
  - **Flipped, this slice's recorded limits** (each failing on `origin/main`
    in its new form): `test_recorded_limits_still_merge[a bare feet value:
    12'-6" vs 12']`, `[a to range signs its far end: 4 to 6 in vs 6 in]`,
    `[loose-comma lists sign their last element: 2, 4, 6 in vs 3, 5, 6 in]`
    and `[a bare 20A needs electrical context: 20A vs 30A on a shared 120V]` →
    `test_conflicting_quantities_stay_two_findings[…]` and
    `test_a_quantity_conflict_is_named_as_the_measurements_axis[…]`, same ids.
  - **Moved (the owner's approved moves):** `test_pairs_kept_apart_by_design[a
    partial list signature against a full one: 2, 4, 6 in vs 2,4,6 in]` →
    `test_one_quantity_spelled_two_ways_is_one_finding[WP-04.4 a loose list =
    the tight list: 2, 4, 6 in = 2,4,6 in]`;
    `test_measurement_tokens[Provide 2, 4, 6 in drains-expected151]` re-pinned
    in place to `["2,4,6in"]` (same id).
  - **Re-pinned (the owner's approved bumps):**
    `test_records_are_written_under_the_wp_04_3_contract` →
    `..._wp_04_4_contract` (5, and it checks the stored readings and pairs);
    `test_a_v4_record_is_compared_under_the_current_rule_without_a_bump` →
    `test_a_v5_record_…` (5; its claim, that a rule-only change needs no bump,
    kept); `tests/test_interrupted_streams.py::test_no_cache_term_moved`
    (`(10, 5)`); the five cross-QC pins (8); the merge-rule fingerprint added
    under 5 (`020b7789…`) over a corpus that gained 17 rows (over it the
    contract-4 rule fingerprints as `f6116986…`, and this PR's rule before
    its review follow-up as `fa0ae134…`, both recorded in the test);
    `test_the_signature_carries_roles_as_sorted_json_safe_lists` (the key set
    gains `feet_inches`). Nothing else moved.
- **Validation** (this container):
  - **The instrumented diff, `origin/main` vs this branch** (the full suite
    under the probe, 5,895 passed, on the code before the abbreviation-period
    fix and the last test rows; the replay below covers the final code): over
    the tests both runs share, compared by content (cross-QC runs its shards
    on worker threads, so call order varies), **0 of 22,338 merge decisions,
    0 of 491 prose vetoes, 0 of 1,268 anchors and 0 of 908 grounding verdicts
    moved**; the rest of main's decisions are the five renamed or moved tests
    and the fingerprint corpus, whose pairs changed with it. And the replay of
    all 22,372 of main's recorded decisions under the final code moves
    exactly **10**: the five approved pairs × the critique's `_cluster` and
    `Ledger.add`.
  - **Speed** (a synthetic 1,800-finding, 40-sheet ledger ingest, best of 3,
    five alternating runs each, on the final code; this session's own script,
    so not comparable with WP-04.3's absolute times): plain wording 1.60–1.74 s
    → 1.73–1.81 s; wording dense with the new forms 2.35–2.53 s → 2.53–2.61 s
    (about 5 %). The new
    readers are memoized on their whole input like the rest; the cost is
    `_read_spelled` on every number with no unit after it and one more
    part-by-part read per signature.
  - Full suite on the final code, after the docs and the review follow-up
    (uninstrumented): **5,907 passed, 2 skipped, 10 deselected** (614 s), the
    baseline plus the 241, the same two environment skips. A JUnit diff against
    the baseline: of the 5,661 tests in both runs, **0 changed outcome**; 7 are
    only in the baseline (the four flipped rows, the moved retention pair and
    the two renamed A/B tests) and 248 only here, all passing.
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean. F401/F811/F841 on the
    touched files: 11 hits, all on `origin/main` too (the two the request
    names, and nine in `tests/test_evidence_visual.py`, touched only for its
    contract re-pin); none new. `python scripts/scan_secrets.py`: clean (the
    new file staged). No key anywhere, every new parametrized case has
    `ids=`, no invisible character added (the tests write the degree sign
    and the en dash as `\u00b0` and `\u2013`).
  - The browser suite was not run separately: no report or JavaScript
    changed, and its tests ran inside the full suite.
- **Docs:** CHANGELOG (Fixed); CLAUDE.md (the signature paragraph: the
  feet-inches pairs and the recorded limits; the tokenizer description: the
  spelled forms, the guards, the voltage context; the critique- and cross-QC
  contract histories; the character-stream veto's note); README (the ledger
  section's measurement passage and its limits; the critique-cache paragraph;
  the cross-QC contract history); `docs/PERFORMANCE_AND_COST_VALIDATION.md`
  (the harness compares the new readings; v5); the plan (WP-04's "Tokenizer
  residuals, done by WP-04.4" note and the Acceptance check); DECISIONS (the
  D-3 input, the D-4 note, three register rows); PROGRESS (this entry; the
  WP-04.4 row; WP-04's package row; the N1 and N19 rows; Next up). No
  dependency changed.
- **WP-04 Acceptance, checked:** demonstrated conflicting pairs never merge
  (every matrix pair and addition, the two role rows and the four residual
  pairs are in `_CONFLICTS`; each residual's other spellings and kinds in
  `_RESIDUAL_CONFLICTS`); equivalent supported spellings compare
  consistently (`_EQUIVALENTS`, with the loose and tight list;
  `_RESIDUAL_EQUIVALENTS`); the fraction, sign and unit safeguards pass
  unchanged (`_SAFEGUARDS`); conservative retention is recorded in the
  fixtures (`_CONSERVATIVE_RETENTION`, `_TAG_RETENTION`, `_ROLE_RETENTION`,
  `_RESIDUAL_RETENTION`). Two shapes the owner chose not to read stay pinned
  in `_RECORDED_LIMITS` as limits, not open defects. **WP-04 is done** (the
  owner's decision).
- **Not verified:**
  - Live API behaviour (no budget, O-4; this slice makes no call).
  - Not measurable without real drawings (O-10): how often findings write a
    bare feet value, a spelled range or list, or a compact `A` beside a
    voltage; how often the guards keep a real range unread; how often a
    name-less room label sits beside a voltage.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - **A visible behaviour change, by design:** more findings can appear as
    two; the prose harvest's veto refuses such a candidate (a paid
    structuring call instead of a free match); a loose list now merges with
    its tight twin.
  - **One-time costs:** the first exhaustive run after upgrading re-critiques
    every sheet once (contracts 1 to 5 are all unreleased, so a 1.7.0 user
    pays it once), and the first cross-sheet check re-runs once (contract 8).
  - **Retention costs, pinned:** `increase from 4 to 6 in` / `increase to
    6 in`; `4 in to 6 in` / `4 to 6 in` and `4 in and 6 in` / `4 and 6 in` (a
    unit on each element stays separate quantities, as before); `12 ft, 6 in`
    / `12'-6"`.
  - **Misreadings the owner accepted, pinned:** a name-less room or panel
    label beside a voltage (`101A 120V receptacle` reads 101 A); a feet value
    directly followed by a separate inch size (`10 ft 6 in pipe` reads as
    10'-6"); a from-to change reads as a range.
  - **Recorded limits (pinned in `_RECORDED_LIMITS`):** two numbers joined by
    a comma alone; a compact `A` with nothing electrical beside it. Not
    pinned: a Unicode dash as a range separator (`4–6 in`) and a number after
    `/` (`30A/2P/240V`) are still WP-04.1's residuals, unchanged; `4 thru 6
    in` is not read.
  - **Growth at the critique boundary** (WP-03.5's): the pairs grow with a
    survivor's supporting quotes like every axis; a representative whose
    bundle came from a pair-less member carries none in its live signature
    (the member-wise checks cover it; pinned by the chain tests).
- **Found in self-review, fixed here:** a positive (`4 or 6 in` vs `4 in`)
  already conflicted on main, so it proved nothing; it is `4 or 6 in` vs
  `6 in` now (fails on main, passes here). The feet-inches join first
  accepted only the ASCII hyphen, which split `12'–6"` (an en dash, which the
  tokens already read as feet-inches) from `12'-6"`; it takes the one dash
  list now (pinned). It also refused an abbreviation's period, which split
  `12 ft. 6 in.` from `12'-6"` (one quantity in the tokens); it allows one
  now (pinned; the replay was re-run on the final code and still moves only
  the 10 approved decisions). The pairs were first read over the joined `_sig_text`,
  which let a text ending in a feet value join a quote opening with an inch
  value; they are read part by part now (pinned).
- **Review follow-up (Codex P2 on this PR).** A number label between a name
  word and the identifier (`Room No. 101A 120V`, `Panel No. 2A 120/208V`,
  `Room Number 101A`) defeated the name guard, so the new voltage context
  read the identifier as a current, and the spelled reader read `Section No.
  4 to 6 in` as a range. The one name guard now allows an optional number
  label (`critique._NUMBER_LABEL`: `no`, `nos`, `num`, `number`, with an
  optional period) in both `_NAME_BEFORE_RE` and `_REFERENCE_BEFORE_RE`. That
  also corrects a misreading on `main` through the older device path (`Room
  No. 101A breaker` read 101 A; now none), always in the safe direction (a
  token removed). Eight rows added to the negative corpus: seven fail on
  this PR's head before the fix, one is a control. The fingerprint corpus
  gained the qualified row and contract 5's value (new in this PR) was
  re-pinned. The replay of main's 22,372 recorded decisions still moves only
  the 10 approved ones.
- **Found, not fixed:** nothing new beyond this slice's scope.
- **Next:** in queue order, Wave 2 WP-06.2 and WP-06.3 (WP-06.2 completes
  D-8). WP-10.1 … WP-10.4, WP-03.4 (now with two WP-04 D-3 inputs), WP-07.3
  and WP-11.3 are available too; WP-06.3, WP-12.6 and WP-13.4 close WP-01.
  The owner question on 5.5 refusal routes (WP-01.5) is still open.

### 2026-09-30 — WP-04.3: quantity roles in the critical signature, and a size's `x12` is not a tag ([PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188))

- **Slice and IDs:** WP-04.3, the WP-04 regression-matrix row "repeated
  values in different roles" (plan WP-04 step 4, "compare quantity roles where
  available"; the N1 register row gains it). No `DECISIONS.md` contract is
  decided: D-3 gains an input ("as an input, not a decision", the WP-03.3 /
  WP-03.7 precedent), D-4 a note, and the migration register two rows (the
  critique contract, the A/B record contract). **WP-04 is not done** (the
  owner's decision, below): WP-04.4 (M, Wave 2) is added for the four
  partial-spelling pairs still in `_RECORDED_LIMITS`.
- **Base.** `main` = `origin/main` = `021f66c` (WP-05.3's merge,
  [PR #187](https://github.com/Abe-Borg/drawing-analyzer/pull/187)). Open PRs:
  [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot)
  and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0
  support), neither a remediation slice. Baseline **5,532 passed, 2 skipped,
  10 deselected** (502 s), identical to WP-05.3's final count; the two skips
  are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0, `httpx2`
  2.13.1, PyMuPDF 1.28.2 (a fresh container: `pip install -e
  ".[dev,browsertest]"`, `cffi`, `ruff==0.14.5`).
- **The request's facts, re-verified** (all held, corrections marked):
  - **Correction: the tracker row's "critique contract 2 → 3" was stale.**
    `_CRITIQUE_CACHE_CONTRACT` was already 3 (WP-01.4); this slice takes it
    3 → 4. The plan's WP-04 note says so.
  - `test_the_critique_contract_is_pinned_to_the_merge_rule` pins one
    fingerprint per contract value; the new one is added under 4, the values
    under 1 to 3 are untouched. `_SCHEMA_VERSION` stays 10.
  - `RECORD_CONTRACT_VERSION` was 3, pinned by two asserts in
    `tests/test_ab_findings_diff.py`. **Measured which kind of change this is:**
    a record stores `critical_signature` as the arm computed it, and a role
    inside that dict is a new key a v3 record lacks. The rule reads a missing
    key as "no role", which never conflicts, so a v3 baseline against a v4
    variant would call a swapped main/branch pair EXACT: a change of what a
    record stores (plan WP-04 step 6, WP-04.2's correction), so a bump.
  - **The `X12` tag:** `Duct 24"x12" serving VAV-3` signed tags `['VAV3',
    'X12']`, measurements `['24x12in']`; beside `Duct 24x12 in … at grid
    C-4` it conflicted on `tags` only and `_is_duplicate` was False.
  - **The 500/550 duplicate:** both reads sign `['500gpm', '550gpm']` and
    `_is_duplicate` is True on main; still True here (pinned).
  - **Every consumer of the one rule:** `critique._is_duplicate` (the
    critique's `_cluster`, `Ledger.add` over member snapshots,
    `reconcile_post_anchor` over member histories); `prose_harvest._veto_axes`
    (`signature_conflicts` over `critical_signature`); the A/B harness
    (`_compatible`, `_conflicting_axes` over stored records, read by
    `ab_sweep_drawing_analyzer.load_arm_records`). `merge_finding_groups` has
    no production caller. **No other cache key holds a merge outcome:** the
    critique cache stores post-merge findings (`critique_cache_entry_from_result`);
    the prose harvest's structuring key (`stage_cache_key("prose_harvest_item")`)
    hashes the item with the sheet's text, the source binding and the request
    params, never the match (a newly refused match is a straggler: a paid
    structuring call, not a re-key); cross-QC's `_drop_exact_repeats` is
    equality only.
  - **Cross-slice:** `anchor._same_quantities` imports `critique._quantity_tokens`
    function-locally. The roles sit beside the reader: `_quantity_readings` is
    the one scanner, now with spans, and `_quantity_tokens` is its tokens (the
    same loop), so no anchor or grounding verdict moved (measured, below).
  - **Found while measuring: one more contract tripwire.**
    `tests/test_interrupted_streams.py::test_no_cache_term_moved` (WP-01.7)
    pins `(_SCHEMA_VERSION, _CRITIQUE_CACHE_CONTRACT) == (10, 3)`. Put to the
    owner (round 2).
  - **SDK 1.8.0:** not needed. The signature makes no SDK call, and no probe
    touched the SDK.
- **Measured before any code** (a scratch pytest plugin, never committed,
  recording every `_is_duplicate` call with its caller and every
  `_veto_axes` call, pair serialized through `Finding.to_dict`, plus every
  `_anchor_one` result and every cross-QC `_grounded` verdict):
  - On `origin/main`: **6,600 merge decisions in 433 tests** (the fingerprint
    corpus 2,116, `Ledger.add` 1,981, the critique's `_cluster` 1,148,
    `reconcile_post_anchor` 801, direct test callers the rest) and 432
    prose-veto records in 112 tests, **replayed offline with 0 mismatches**
    first.
  - Each option replayed over them (a scratch prototype):

    | Option | Merge/veto decisions moved |
    |---|---|
    | Closed role list (every ambiguity policy; with or without bare labels) | 4: the two recorded limits × critique and ledger |
    | Closed list + status words | 4 |
    | Any noun after the value | 12: the 4, plus 6 in `test_drawing_dedup_lifecycle.py::test_the_representative_does_not_depend_on_ingest_order` and 2 in the bare-`12'` recorded limit |
    | `X12` fix, in `_TAG_RE` or only inside a W×H token | 0 (tags changed in 10 or 8 suite texts, each losing only `X12`) |

  - Case tables shown to the owner (per option): the role pairs in every kind
    split under each closed option; status words split a real 500/550
    duplicate whose reads call different values "shown"; the open noun read
    `hall is 480V` and `plan are 6 in` as roles; the ambiguity policies
    differ only on a value list with a role list, a bare label sequence and
    "one side names roles".
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, eight choices, measured case tables; every recommended option
  taken):
  - **Round 1.**
    - **Signal: a closed role list** (`critique._ROLE_WORDS`: main, branch,
      riser, drop, header, supply, return, suction, discharge, inlet, outlet,
      upstream, downstream, entering, leaving, primary, secondary, min/max,
      static, residual, cold, hot), read right after the value (`6 in main`,
      `6 in (main)`, `6 in supply and return`), as a label (`main: 6 in`) or
      with a copula (`the main is 6 in`), compared per role per kind by
      inclusion wherever both bind the role. Not taken: plus status words;
      any noun after the value.
    - **Ambiguity: retain real ambiguity only.** A value list followed by a
      role list without `respectively`, or a role word between two values
      with nothing joining them, is ambiguous; a finding whose only roles for
      a kind are ambiguous stays apart from one that binds roles in that
      kind. A missing role never blocks. `respectively` pairs in order. Not
      taken: missing or ambiguous never blocks; broad retention (keep apart
      whenever only one side names roles).
    - **`X12`: fixed here, in `_TAG_RE`** (an `x`/`X` glued to a digit's inch
      or foot mark). Not taken: only inside a W×H token; not here.
    - **A/B record: store the roles, `RECORD_CONTRACT_VERSION` 3 → 4.** Not
      taken: keep 3 and derive the roles at comparison time from the record's
      text (a second place the signature is composed).
  - **Round 2.**
    - **WP-04: a new slice, WP-04.4, and WP-04 stays open.** Not taken: done,
      with the four pairs recorded as outside the matrix (WP-04.2's reading).
    - **Axis: `measurements`.** Not taken: a new `quantity_roles` axis.
    - **Bare preceding label (`MAIN 6"`): not read, a recorded limit.** Not
      taken: read it with a label-first / role-after run rule.
    - **The WP-01.7 tripwire: re-pinned to `(10, 4)` with a comment naming
      WP-04.3.** (The option's label read "Keep its claim, drop the pin"; its
      text said "re-pin it to (10, 4)", which is what was done.) Not taken:
      pin only the schema version.
  - **Composition, decided in the implementation within those rules**
    (stated here for the next session): a value with a label or copula role
    and a different role after it takes both; a role word followed by `:` or
    `=` labels the next value, not the one before; a parenthesized role
    attaches to its value (not "between two values"); roles are read part by
    part (`_sig_parts`: text, quote, each supporting quote) so a quote's first
    word never binds to the text's last value (measurements still read the
    joined `_sig_text`, unchanged); ambiguity is stored as tokens and its
    kinds derived at comparison time, as the measurements' are.
- **What changed** (production):
  - **`critique.py`:** `_TAG_RE` refuses a tag whose letter is an `x`/`X`
    glued to `\d["']`; `_quantity_readings` (the scanner, now with spans) and
    `_quantity_tokens` (its tokens, unchanged); the role section
    (`_ROLE_WORDS`, the binding patterns, `_role_run_after`, `_roles_before`,
    `_quantity_roles`, `_sig_parts`, `_roles_of_parts`, `_roles`, all
    memoized on their whole input); `critical_signature` gains `roles` and
    `ambiguous_roles`; `_kind_of`, `_values_by_role`, `_roles_conflict` (a
    side with no role signal skips the comparison); `signature_conflicts`
    reports a role conflict on `measurements`; its docstring's growth
    statement covers roles.
  - **`digest_cache.py`:** `_CRITIQUE_CACHE_CONTRACT` 3 → 4 with its reason.
  - **`scripts/ab_findings_diff.py`:** `RECORD_CONTRACT_VERSION` 3 → 4 with
    its reason.
- **Tests:** **138 new test IDs, 134 net** (counts from `--collect-only`):
  `tests/test_quantity_roles.py` 118 (readings 26, the negative corpus 16,
  the closed list 1, role conflicts 18 + the quote 1, compatible pairs 10 +
  the 500/550 finding 1, negative-corpus pairs 6, retention 3, recorded
  limits 7, the complete-link chain 1 + 18 (six orders × `_cluster`,
  `Ledger.add`, Pass B) + the grown survivor 1, the record and the rule 7,
  the reader 1, the prose veto 1); `tests/test_signature_compatibility.py` 9
  (the dimension separator); `tests/test_ab_findings_diff.py` 3 new + 2
  renamed; `tests/test_quantity_signature.py` the two moved rows × 2 tests;
  `tests/test_drawing_cache_identity.py` 2.
  - **Classified against `origin/main`** (the worktree at `021f66c` with its
    own `src` first on `PYTHONPATH` and a shim: `_quantity_roles` reads
    nothing, `_ROLE_WORDS` is empty, `_quantity_readings` is a copy of main's
    own scanner): of the 140 new or changed IDs, **87 fail on behaviour, 4
    fail on a missing key** (`KeyError: 'roles'`, the signature's new key),
    **49 pass** (controls: the compatible pairs incl. the 500/550 duplicate,
    the negative corpus, the recorded role limits, the readings with no role,
    the reader equality, symmetry and dominance, the three tag controls,
    and the cut-word label below, which main cannot read as a role either).
    Every existing test kept its outcome there.
  - **Flipped, this slice's recorded limits** (each failing on `origin/main`
    in its new form): `test_recorded_limits_still_merge[swapped roles: 6 in
    main, 4 in branch vs 4 in main, 6 in branch]` and `[one value in two
    roles: 6 in supply and return vs 6 in supply, 8 in return]` →
    `test_conflicting_quantities_stay_two_findings[…]` and
    `test_a_quantity_conflict_is_named_as_the_measurements_axis[…]`, same ids.
  - **Re-pinned (the owner's approved bumps):**
    `test_records_are_written_under_the_wp_04_1_contract` →
    `test_records_are_written_under_the_wp_04_3_contract` (4, and it checks
    the stored roles); `test_a_v3_record_is_compared_under_the_current_rule_without_a_bump`
    → `test_a_v4_record_…` (4; its claim, that a rule-only change needs no
    bump, kept); `tests/test_interrupted_streams.py::test_no_cache_term_moved`
    (`(10, 4)`); the merge-rule fingerprint added under 4 (`b62e9526…`),
    over a corpus that gained 15 rows (over it, the contract-3 rule
    fingerprints as `b3660a7e…`, recorded in the test). Nothing else moved.
- **Validation** (this container):
  - Full suite, instrumented, on the final code: **5,666 passed, 2 skipped,
    10 deselected** (468 s), the baseline plus the 134, the same two
    environment skips. A JUnit diff against the baseline: of the 5,530 tests
    in both runs, **0 changed outcome**; 4 are only in the baseline (the two
    flipped rows and the two renamed A/B tests) and 138 only here, all
    passing.
  - **The instrumented diff, `origin/main` vs this branch** (the tests both
    runs share): **6,596 merge decisions in 431 tests, 0 changed**; 389
    prose-veto decisions in 112 tests, 0 changed; **1,072 anchors in 800
    tests, 0 changed** (status, method, rect, matched words); 769 cross-QC
    grounding verdicts in 406 tests, 0 changed. The only merge decisions
    that moved are the 4 of the two flipped tests; the 2,233 decisions only
    the branch recorded are the fingerprint corpus's new rows.
  - **Speed** (synthetic 1,800-finding, 40-sheet ledger ingest, best of 3):
    wording with no role word 1.16–1.19 s → 1.27–1.32 s; wording full of
    role words 1.01–1.04 s → 1.27–1.29 s.
  - The final run, after the docs (uninstrumented): **5,666 passed, 2 skipped,
    10 deselected** (464 s), the same JUnit diff (0 of 5,530 shared tests
    changed outcome; 138 new, all passing).
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean. F401/F811/F841 on the
    touched files: two hits, both on `origin/main` too
    (`critique.DEFAULT_DIGEST_MAX_TOKENS`,
    `tests/test_drawing_cache_identity.py`'s `SheetRef`); none new.
    `python scripts/scan_secrets.py`: clean (the new file staged). No key
    anywhere, every new parametrized case has `ids=`, no invisible character
    added (the tests write the degree sign as the escape `\u00b0`).
  - The browser suite was not run separately: no report or JavaScript
    changed, and its tests ran inside the full suite.
- **Docs:** CHANGELOG (Fixed); CLAUDE.md (the signature paragraph: roles,
  the separator rule, the limits; the critique-contract history); README
  (the ledger section's roles and limits; the critique-cache paragraph);
  `docs/PERFORMANCE_AND_COST_VALIDATION.md` (the harness compares roles; v4);
  the plan (WP-04's "Roles, done by WP-04.3" note with the correction, the
  WP-04.4 slice line and the Acceptance check); DECISIONS (the D-3 input,
  the D-4 note, two register rows); PROGRESS (this entry; the WP-04.3 row;
  the new WP-04.4 row; WP-04's package row; the N1 row; Next up). No
  dependency changed.
- **WP-04 Acceptance, checked:** every matrix pair is pinned, and "repeated
  values in different roles" now stays two findings; equivalent spellings
  compare consistently (`_EQUIVALENTS`, unchanged); the fraction, sign and
  unit safeguards pass unchanged; conservative retention is recorded in the
  fixtures (`_CONSERVATIVE_RETENTION`, `_TAG_RETENTION`, `_ROLE_RETENTION`).
  "Demonstrated conflicting pairs never merge" still fails on four pairs
  (a bare `12'` against `12'-6"`; `4 to 6 in` against `6 in`; loose-comma
  lists; a bare `20A` on a shared `120V`), so **WP-04 stays `todo`** and
  WP-04.4 is added (the owner's decision).
- **Not verified:**
  - Live API behaviour (no budget, O-4; this slice makes no call).
  - Not measurable without real drawings (O-10): how often findings name
    roles from the list, how often two reads of one issue phrase roles
    differently (a REPRODUCED finding then reads as two SINGLETONs only
    where one read's roles are ambiguous or swapped), how often a stray
    `X12` separated two findings.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - **A visible behaviour change, by design:** findings that give the same
    values to different roles are two findings, each with its own markup,
    and the prose harvest's veto refuses such a candidate (a paid
    structuring call instead of a free match).
  - **Retention costs, pinned:** a role word before a distance (`the 6 in
    main 10 ft from the wall`) reads as ambiguous and stays apart from the
    same text that binds the role; a distributive run can over-reach
    (`6 in supply and return air is 4 in` gives the return 6 in), which can
    split a restatement (the safe direction).
  - **Recorded limits (pinned in `_ROLE_LIMITS`):** swaps around an
    unlisted word (`floor drain` / `roof drain`), between two tags, or after
    `at`; status words; both sides ambiguous; a bare label sequence swapped;
    ordinals on one role. A spaced `24" x12"` still reads as a tag (pinned in
    `tests/test_signature_compatibility.py`). Not pinned: `6 in. main` (an
    abbreviation period before the role word) reads no role, which is also
    what keeps a sentence break (`6 in. Main shall be ...`) from binding.
  - **Growth at the critique boundary** (WP-03.5's): a representative whose
    bundle came from a role-less read carries no role in its live
    signature; the ledger's member-wise checks cover members, but a
    critique representative entering the ledger carries its reads' quotes,
    not their texts.
- **Found in self-review, fixed here:** the label/copula search looked in a
  32-character slice before the value, where `\b` holds at the slice's first
  character, so a longer word cut at the window's edge read as a role
  (`domain:` + 27 spaces + `6 in` bound `main=6in`). It now searches the text
  between bounds; pinned in `_NOT_ROLES` (the case fails on the first
  implementation, passes on `origin/main` and here). Both measurements above
  were re-run on the fixed code.
- **Found, not fixed:** nothing new beyond this slice's scope (the two
  pre-existing F401 hits are WP-22.5 territory, noted by WP-04.2).
- **Next:** in queue order, WP-04.4 (Wave 2, available; WP-04's acceptance
  needs it), then WP-06.2 and WP-06.3. WP-10.1 … WP-10.4, WP-03.4 (now with
  this slice's D-3 input), WP-07.3 and WP-11.3 are available too; WP-06.3,
  WP-12.6 and WP-13.4 close WP-01. The owner question on 5.5 refusal routes
  (WP-01.5) is still open.

### 2026-09-30 — WP-05.3: the anchor's character-stream tier, and a split number stays whole ([PR #187](https://github.com/Abe-Borg/drawing-analyzer/pull/187))

- **Slice and IDs:** WP-05.3, WP-05's last slice. B4's character-stream part
  (implemented+validated; B4 is now implemented+validated in full). No
  `DECISIONS.md` contract is decided (the matching rules are none of D-1 …
  D-8, and no identity or merge input moved, so no D-3 input): the owner's
  eight choices are recorded here, in the plan's new "Step 2, done by WP-05.3"
  note under WP-05 and in CLAUDE.md. D-4 gains a WP-05.3 note and the
  migration register one row (the cross-QC contract bump). **WP-05 is done**:
  every slice is done and the plan's WP-05 Acceptance holds (checked below).
- **Base.** `main` = `origin/main` = `183e2c6` (WP-01.8's merge,
  [PR #186](https://github.com/Abe-Borg/drawing-analyzer/pull/186)). Open PRs:
  [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot)
  and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0
  support), neither a remediation slice. Baseline **5,329 passed, 2 skipped,
  10 deselected** (467 s), identical to WP-01.8's final count; the two skips
  are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0, `httpx2`
  2.13.1, PyMuPDF 1.28.2 (a fresh container: `pip install -e
  ".[dev,browsertest]"`, `cffi`, `ruff==0.14.5`).
- **The request's facts, re-verified** (a probe script per tier, word tuples
  built the way the tests build them; all held, corrections marked):
  - **Each pair, per tier, on `origin/main`:** all four UNANCHORED, and
    cross-QC NOT_MATCHED. `_Stream` holds `provide 6 " drain`, `provide
    inchdrain`, `clg 12' - 6" aff`, `slope 2 % min` as separate tokens while
    the quote tokenizes `6"`, `inch drain`, `12'-6"`, `2%`: EXACT has no run;
    every window scores at most 1/3 (the token counts differ) and its veto
    finds no `6"`, `12'-6"` or `2%` token; the sub-phrase needs at least 3
    tokens and the quote's own digit token.
  - **`_normalize` and `fold_word`:** `"` `'` `%` `-` survive both (`'` is not
    `\w`, so `12'-6"` keeps its hyphen); a lone `"` has an empty core; a lone
    `.` or `,` folds to nothing and is dropped.
  - **`critique._quantity_tokens`:** `6"`/`6 "` → `6in`, `2%`/`2 %` → `2%`,
    `12'-6"`/`12' - 6"` → `{12ft, 6in}`, `12' -6"` → `{12ft, -6in}`; `150 GPM
    568 L/S` and `150 GPM (568 L/MIN)` both read only `{150gpm}`.
    **Correction: it cannot be the veto as it is**: it returns a set, reads no
    unitless number (`ROOM 12`/`ROOM 1 2`, `VAV-21`/`VAV-2-1` read nothing on
    either side) and reads neither `L/S` nor `L/MIN`.
  - **Import layering:** `anchor.py` imports `tiling` and `models`;
    `critique.py` pulls in `digest`, `api_config` and `profiles`; neither
    imports the other at module level, `cross_qc` imports `anchor`, and the
    package `__init__` already loads `pipeline` and `render`, so a
    function-local import adds nothing at runtime and no cycle (the
    arithmetic auditor's lazy `from .. import anchor` is the precedent). I-5
    is a static scan and is unaffected.
  - **Consumers of an anchor's method and status:** `numbers_grounded` (the
    arithmetic auditor) is the only one that reads the method's meaning;
    `verify._is_verifiable` / `_has_anchored_legs` and
    `investigate._candidates` read only the rect; `annotate` reads the
    status (UNANCHORED → a `[QUOTE NOT FOUND]` callout, else a cloud); the
    report folds status and verdict into one chip; `findings.csv` /
    `findings.json` carry `anchor_status` and `anchor_method`; the
    verification keys carry status, method and rect, the investigation key
    the rect; cross-QC's `classify_quote_evidence` / `evidence_state` go
    through `_grounded`. A new FUZZY method is therefore a cloud, one crop
    call on an exhaustive run and a normal report chip, and grounds no
    arithmetic operand unless listed.
  - **Found while measuring: a leading decimal could already become `5`.**
    WP-05.2's fold drops a lone `.`, so `SET AT 5 IN` matched `SET AT . 5 IN`
    EXACT and cross-QC grounded it (and `5 IN` matched there since before
    WP-05), and the prototype tier anchored `5" GAP` on `. 5 " GAP`. Put to the
    owner (round 2 and a follow-up).
  - **SDK 1.8.0:** not needed. The anchor and cross-QC grounding make no SDK
    call, and no probe went through the SDK.
- **Measured before any code** (a scratch prototype of the tier with every
  option, and an instrumented full-suite run on `origin/main` recording every
  `_anchor_one` result and every cross-QC `_grounded` call):
  - **1,069 anchor decisions in 606 tests**, replayed offline with 0
    mismatches first. Every option moved exactly the 4 recorded-limit anchors;
    the sub-phrase "cut" rule also moved the second recorded limit; placing
    the tier second moved the same 4.
  - **738 grounding calls in 237 tests**, 138 NOT_MATCHED; the tier grounds 0
    of them.
  - **Lone marks:** 0 of the 219 recorded sheets and 0 recorded quotes have a
    lone `.` before a digit word; 31 sheets have a lone `+` or `-` before one,
    all arithmetic operators (so no rule touches them).
  - **Arithmetic** (a probe through `audit_arithmetic`): `6" + 6" = 14"` on
    `6 " + 6 " = 14 "` is UNCERTAIN outside `numbers_grounded` and
    DETERMINISTIC inside it; `2% + 3% = 6%` is UNCERTAIN either way (`%` is
    refused); placed second and not grounding, the tier would demote `FLOW
    TEST: 20 + 20 = 540` on `FLOWTEST: …` (DETERMINISTIC through the
    sub-phrase today).
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds and a follow-up, eight choices, a case table per option; every
  recommended option taken):
  - **Round 1.**
    - **Joins: named joins only** (a number and a separated `"` `'` `%`, either
      side; the feet-inches hyphen, either side; letters merged by extraction,
      one sheet word for several quote words, each letters only). Not taken:
      plus unit words (`6INCH`/`6 INCH`); plus two sheet words for one quote
      word (it joins `THE RAPIST` into `THERAPIST` and `X P-1` into `XP-1`);
      sheet-side spacing only.
    - **Veto: the join rules plus the reader as it is**, through a
      function-local import, and never across a lone `.`. Not taken: an
      ordered sequence from a new sibling reader in `critique.py`; moving the
      reader to a leaf module.
    - **Method: FUZZY `char_stream`, the last quote tier, not in
      `numbers_grounded`.** Not taken: last and grounding numbers; second
      (after EXACT) and grounding.
    - **Ambiguity: as EXACT** (the tile, else the first in reading order,
      `char_stream_ambiguous`). Not taken: refuse unless the tile settles it;
      as the window (no flag).
  - **Round 2.**
    - **Sub-phrase: it may not end on a digit-bearing token the quote
      continues from.** Not taken: equal WP-04 quantities (refuses a dropped
      `PSIG`, not `L/S`: the limit would stay); leave it.
    - **Lone `.`: fixed here, in every tier and cross-QC.** Not taken: guard
      the new tier only and add a WP-05.4 row (WP-05 would stay open).
    - **Cross-QC: adopt, contract 6 → 7.** Not taken: record each difference
      in the agreement table.
  - **Follow-up:** the **same rule on the quote** (a quote with a lone `.`
    right before a digit word matches nothing). Not taken: sheet side only
    and a new row.
- **What changed** (production):
  - **`anchor.py`** (still no PDF engine; `_normalize`, `fold_word`,
    `word_core` and the 0.85 floor untouched):
    - `_folded_words` (new): a text's folded words with their places, or `[]`
      when a lone `.` sits right before a digit word; `_fold_text` joins it.
    - `SourceWords`: `split_number` (the folded words of a number split around
      a lone `.`: the digit word after it and the digit-ending word before
      it), `covers_split_number`, and `_scan` refuses a span covering one;
      `joined_spans` (the tier: a contiguous run of whole words, the named
      joins, `_same_quantities`, the split guard, remembered per quote),
      `_joined_index`, `_joined_scan`; module-level `JOIN_MARKS`,
      `_joins_allowed`, `_same_quantities`.
    - `_Stream.covers_split_number`; the window skips a window that covers a
      split number; the sub-phrase skips one that ends on a number the quote
      continues from; `_try_char_stream` (the tier, after the sub-phrase);
      `_NUMBER_GROUNDING_METHODS` unchanged (its comment says why).
  - **`cross_qc.py`:** `_grounded` asks `joined_spans` when `contains`
    fails; `_CROSS_QC_CACHE_CONTRACT` 6 → 7 with its reason. The fact-tile
    join is unchanged.
- **Tests:** **new: 203** (197 in the first push, 6 from the Codex review,
  below), in `tests/test_anchor_character_stream.py` (counts
  from `--collect-only`): the four pairs, each anchored, grounded and not
  number-grounding (12); 14 more named joins; 8 matches the older tiers keep;
  41 negatives; 8 absent short tags; fragments out of reading order (1); the
  veto (2); the split number in every tier (12); ambiguity (2); the
  sub-phrase rule (7); cross-QC (83: an agreement table of 77 rows, a leg, a
  fact, a textless sheet, the fact-tile join limit, one implementation, the
  contract); consumers (5: arithmetic both ways, verification and
  investigation both ways, the pipeline); cost (2); a mark joined only to a
  number (6, the Codex review).
  - **Classified against `origin/main`** (a worktree at `183e2c6` with its
    own `src` first on the path and a shim giving `SourceWords.joined_spans`
    a neutral `()`): **49 fail on behaviour, 0 on a missing name, 148 pass**
    (controls: every negative, the absent tags, the older tiers' matches,
    the agreement rows, which agree EXACT-only there, the fact-tile limit).
  - **Flipped, this slice's recorded limits** (`tests/test_anchor_whole_words.py`,
    each failing on `origin/main` in its new form):
    `test_recorded_limit_the_character_stream_cases_are_wp_05_3s[inch|merged|feet|percent]`
    → `test_the_character_stream_cases_anchor_by_their_own_method[…]`
    (FUZZY `char_stream` on the whole run), and
    `test_recorded_limit_a_sub_phrase_can_drop_a_separated_unit` →
    `test_a_sub_phrase_cannot_drop_a_separated_unit` (UNANCHORED).
  - **Re-pinned 6 → 7, the contract tripwires** (the approved bump; there are
    four, not the three the plan names: WP-06.1 added one):
    `tests/test_drawing_cross_qc.py::test_cross_qc_contract_bumped_for_the_norm_id_fold`
    (it also checks the key differs from contract 6),
    `tests/test_evidence_visual.py::test_contract_counter_is_not_bumped_by_this_package`,
    `tests/test_evidence_tail.py::test_no_cross_qc_contract_bump_was_needed`,
    `tests/test_cross_qc_validation_and_dedup.py::test_the_cross_qc_contract_moved_for_the_new_host_binding`.
    Nothing else moved.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2`
  2.13.1, PyMuPDF 1.28.2):
  - Full suite on the code: **5,526 passed, 2 skipped, 10 deselected** (542 s,
    instrumented), the baseline plus the 197, the same two environment skips.
    A JUnit diff against the baseline: of the 5,326 tests in both runs, **0
    changed outcome**; 5 are only in the baseline (the flipped limits, renamed)
    and 202 only here (197 new, 5 renamed), all passing.
  - **The instrumented diff, `origin/main` vs this branch:** 1,064 anchor
    decisions in the 601 tests both runs share, **0 changed** (status, method,
    rect and matched words); the 5 renamed tests moved exactly as intended (4
    to `char_stream`, 1 to UNANCHORED). 738 grounding calls in 237 tests, **0
    changed** as multisets per test (cross-QC grounds on worker threads, so
    the call order varies).
  - **Speed** (synthetic dense sheets, 60 quotes, best of three):
    3,000 words 0.157 s → 0.162 s; 15,000 words 0.839 s → 0.814 s. A joined
    quote recurring 250,000 times inside one 750,000-character word anchors
    in linear time (pinned under 5 s).
  - The final run, after the docs (uninstrumented): **5,526 passed, 2 skipped,
    10 deselected** (547 s), the same JUnit diff.
- **Codex review (P2, fixed in this PR): "restrict mark joins to actual
  numeric tokens".** The mark join checked only that the character before the
  space was a digit, so an identifier's digits took a separated mark:
  `ROOM12% MIN` matched `ROOM12 % MIN` (and the quote-side twin), `SEE
  M-101" TYP` matched `SEE M-101 " TYP` (the infix hyphen splits off `101`),
  and `RATED AHU2" MAX` matched `RATED AHU2 " MAX`,
  and the feet-inches join did the same (`A12' - 6"`, `6A"`). The WP-04
  reader reads nothing on either side there, so the veto could not refuse
  them. Reproduced on the first push (`176a644`), all six. Root cause: the
  owner's rule names a *number*, and the join tested a character. Fixed at
  the rule: a mark and the feet-inches hyphen join only when the words on
  both sides of the space, on the side that has it, carry no letter
  (`_joins_allowed` now reads both sides' breaks with their words; the
  sheet's per-word flag is built once in `_joined_index`). Tests: 6 new
  (`test_a_mark_is_joined_only_to_a_number`), each failing on the first push;
  every earlier positive still anchors. Full suite after the fix: **5,532
  passed, 2 skipped, 10 deselected** (561 s); of the 5,326 tests shared with
  the baseline, 0 changed outcome. The fix only removes matches from the new
  tier, so no older tier's anchor can move; the suite's four fixture
  `char_stream` anchors (the flipped limits) are unchanged.
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean; F401/F811/F841 on the
    touched files: clean. `python scripts/scan_secrets.py`: clean (the new
    file staged). No key anywhere, every parametrized case has an id, no
    invisible character was added (the tests write the degree sign as the
    escape `\u00b0`).
  - The browser suite was not run separately: no report or JavaScript
    changed, and its tests ran inside the full suite.
- **Docs:** CHANGELOG (Fixed); CLAUDE.md (the grounding paragraph, the text
  normalization paragraph, the Disposition paragraph's tiers, the contract
  history); README ("Anchoring findings": the tier, the veto, the split
  number, the sub-phrase rule; the cross-sheet QC paragraph; the cache
  bullet's contract history); the plan (WP-05's "Step 2, done by WP-05.3"
  note with the corrections, and its Acceptance check); DECISIONS (the D-4
  note and one register row); PROGRESS (this entry; the WP-05.3 and B4 rows;
  WP-05's package status; Next up). No dependency changed.
- **WP-05 Acceptance, checked:** all reported spacing/punctuation examples
  anchor (B4's seven pairs: three EXACT since WP-05.2, four `char_stream`
  here); numeric substitutions do not (the window and sub-phrase vetoes,
  and here the join rules, the reader and the split-number rule: 41
  negatives); absent short tags never become TEXT_GROUNDED (WP-05.1, and
  here no tag joins: 8 cases); eligible raster evidence reaches verification
  with honest provenance (WP-05.1's tile fallback,
  `tests/test_evidence_visual.py::test_a_recovered_finding_reaches_verification_and_investigation`).
  B4, B5, N12 and N13 are implemented+validated. **WP-05 is done.**
- **Not verified:**
  - Live API behaviour (no budget, O-4; this slice makes no call).
  - Not measurable without real drawings (O-10): how often extraction
    separates a mark, merges words, splits a dimension or a decimal point;
    how many findings newly anchor (a cloud and a crop call each) and how
    many sub-phrase anchors the new rule refuses.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - **More paid calls, by design:** each newly anchored finding costs a crop
    call on an exhaustive run; each sub-phrase anchor the new rule refuses
    loses one.
  - **The sub-phrase rule reads positions, not units:** a quote whose number
    is followed by any other word (`… NOTE 4 FOR THE …`) loses its sub-phrase
    match (pinned as the accepted cost).
  - **Recorded limits:** the fact-tile join does not join across spacing;
    `12' -6"` (spaced on one side, read as a negative) does not anchor;
    WP-05.2's letter-only tag in a long window and WP-05.1's tight list stay.
  - **A lone `-` or `+` before a number** is left alone (in the suite every
    one is an arithmetic operator): `5 FT` still matches the `5` in
    `ELEV - 5 FT` as a whole word, as it always has.
  - **The report does not tell a `char_stream` anchor from another FUZZY
    one**; it is a text match, so it carries no reduced-trust caveat.
- **Found, not fixed:** nothing new beyond what this slice fixed (the lone
  `.`).
- **Next:** in queue order, WP-04.3 (Wave 2, available; WP-04's acceptance
  needs it). WP-06.2, WP-06.3, WP-10.1 … WP-10.4, WP-03.4, WP-07.3 and
  WP-11.3 are available too; WP-06.3, WP-12.6 and WP-13.4 close WP-01. The
  owner question on 5.5 refusal routes (WP-01.5) is still open.

### 2026-09-30 — WP-01.8: a failed batch critique read is retried, and a cut-off critique gets one raised cap ([PR #186](https://github.com/Abe-Borg/drawing-analyzer/pull/186))

- **Slice and IDs:** WP-01.8, WP-01's last slice. N4's critique part (its
  retries: implemented+validated; N4 stays open for WP-10.4's cache map), R2's
  batch critique part (implemented+validated), WP-01 step 5 for the critique.
  Contract: a WP-01.8 note under D-1 (amending its WP-01.4 note's "not retried
  at a raised cap" line and pointing its WP-01.5 note here), one under D-2 (the
  items stay reads) and one under D-4 (nothing moved), in `DECISIONS.md` (the
  owner's rules). No migration-register row. **WP-01 is not done** (the owner's
  decision, below): all eight slices are done; its acceptance waits on WP-06.3,
  WP-12.6 and WP-13.4. The row's acceptance holds (tests named below): a
  transiently failed, expired or routed-refused batch critique read is
  recovered inside the bound; no failed read enters a cache promising completed
  work; the D-2 tally counts a recovered read as judged and a still-failed one
  as not; no regression to ordinary successful reads (0 of the 5,244 tests in
  both runs changed outcome).
- **Base.** `main` = `origin/main` = `40b2f96` (WP-01.7's merge,
  [PR #185](https://github.com/Abe-Borg/drawing-analyzer/pull/185)). Open PRs:
  [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot)
  and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0
  support), neither a remediation slice. Baseline **5,242 passed, 2 skipped,
  10 deselected** (526 s), identical to WP-01.7's final count; the two skips
  are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0, `httpx2`
  2.13.1, PyMuPDF 1.28.2 (a fresh container: `pip install -e
  ".[dev,browsertest]"`, `cffi`, `ruff==0.14.5`).
- **The request's facts, re-verified** (all held; corrections marked):
  - **m1, the batch critique, every failed envelope** (direct submit/collect,
    the real SDK over `AnthropicAPIStub`, Opus 5.5, Sonnet 5.5 and Opus 5, 23
    shapes each: the nine SDK error types, canceled, expired, a refusal of
    every category plus `null` and no `stop_details`, `max_tokens` empty and
    with a complete-looking object, the context window, `None`,
    `pause_turn`): every read failed in one batch of 4 items, never retried,
    no real-time call; only the other sheet was cached. WP-01.5's wording held
    (an errored read names its type, a refused one its category).
  - **m2, the real-time critique** (`critique_sheet_self_consistent`, three
    models): a read cut at 64k fails in one call and is never cached; so are
    the context window and a refusal with or without `recommended_model`.
  - **m3, through the pipeline** (Hybrid, Economy, Fast; overloaded, invalid
    request, expired, canceled, a cyber refusal on Opus 5 and on Opus 5.5,
    `max_tokens`): the critique stage PARTIAL, 3 of 4 reads judged, the coverage
    line and the sheet's error as WP-01.4 left them, the sheet's usage record
    PARTIAL, the warm run 2 batch items (or 2 real-time calls) again.
  - **SDK 1.8.0** in a scratch venv (`--system-site-packages`,
    `anthropic==1.8.0 --no-deps`): m1, m2 and m3 identical, line for line.
  - **Over the whole suite** (an instrumented run): 54 failed batch critique
    reads in 48 tests and 125 failed real-time ones in 64; 18 test IDs reach a
    shape a new rule retries (the re-baselines, below).
  - **Correction: the digest's recovery could be reused, not copied** (plan
    §4.2). Its retry decision read only a slot's params and a `SheetDigest`'s
    verdict, and its budget helpers only a slot's `retries`; its rounds loop is
    bound to its harvest, abandonment records and rescue, which the critique
    has none of. So the decision and the budget are shared, and the loop is
    the critique's own.
  - The row's raised-cap facts held: `DEFAULT_CRITIQUE_MAX_TOKENS` 64,000,
    `MAX_TOKENS_RETRY_CEILING` 128,000, both 5.5 models and Opus 5 serve
    128,000; a batch item never streams, the real-time read streams (and since
    WP-01.7 retries an interruption).
- **The decision, made by the owner before any code** (AskUserQuestion, three
  rounds and a status question, nine choices, a case table per option; every
  recommended option taken):
  - **Round 1.**
    - **Which reads:** the digest's predicate in fresh critique-batch rounds
      (transient errored and expired as sent, a routed refusal on its fallback
      once, `max_tokens` at twice the cap once; not permanent, canceled,
      unrouted, context window, `None`, continuation, unknown, malformed); never
      real time. Not taken: one follow-up only; plus canceled; transient and
      expired only.
    - **Budget:** WP-01.5's per-sheet budget, the same knob, every resubmitted
      read one (2 + 4 items per sheet worst case). Not taken: per read (2 + 8);
      per sheet on its own knob; one count shared with the digest's.
    - **The read kept:** a finished retry is the read; a failed chain is named
      in the digest's words. Not taken: the latest error only; every error
      joined.
    - **Real time:** one raised-cap retry per read. Not taken: batch only;
      neither.
  - **Round 2.**
    - **Merge, tally, cache:** the recovered read is the read, cached under the
      requested key, no bump. Not taken: the same with the contract 3 -> 4;
      used and never cached.
    - **Usage:** summed on the sheet's one record. Not taken: a record per
      retried read.
    - **Re-baselines:** in place, intent kept (below). Not taken: in place with
      the fakes unchanged; per test.
    - **WP-01.5's two leftovers:** both noted on rows (the digest harvest's
      truncated cap on WP-14.1; the real-time `recommended_model` on WP-14.3).
      Not taken: (1) here; both here.
  - **Round 3.**
    - **The batch critique's missing harvest** (found while measuring): a new
      row outside WP-01, WP-18.6. Not taken: WP-01.9; in scope here.
    - **A follow-up batch that never ends:** canceled, the recovery stops, its
      reads named. Not taken: cancel and carry to the next round.
  - **WP-01's status** (after m4, below): open, waiting on three rows. Not
    taken: a WP-01.9 that takes cross-QC's and citation's terminal parts; done,
    scoped to its slices.
- **What changed** (production):
  - **`batch_digest.py`:** `_retry_params_for` (the one retry predicate,
    slot-agnostic: `result_obj`, `params`, `requested_model`, `stop_reason`,
    `failed`, `label`, `noun`, `on_not_retried`); `_item_retry_params` is now
    its digest wrapper; `_refusal_retry_params(result_obj, params, *,
    requested_model, label, noun, on_not_retried)` (the log words the noun);
    `_retry_budget_of`, and `_within_retry_budget` / `_count_retry` count a
    critique read against its sheet (the check counts the items it keeps
    within one call). Decisions byte-identical: an instrumented full run on
    `origin/main` and on this branch recorded 315 `_item_retry_params`
    decisions in 148 tests, all identical; the only other tests with
    decisions are three new Economy ones.
  - **`critique.py`:** `CritiqueRunOutcome.stop_reason`, `read_error`,
    `retries_discarded` (runtime only); `_add_attempt_usage`,
    `keep_critique_read`, `note_failed_critique_retry`;
    `outcome_from_message(..., fallback_model=)` (`refused critique on
    claude-opus-4-8 (…)`) and the stop reason on every outcome;
    `_critique_read` gives a `max_tokens` read one retry at twice the cap.
  - **`batch_critique.py`:** `_CSlot.retries`; `_CRead` (a read's custom id,
    first and latest params, outcome; `retry_budget` is its slot);
    `CritiqueBatch.reads`; `_outcome_from_envelope(fallback_model=)`;
    `_read_retry_params`, `_fold_retry`, `_recover_failed_reads` (the rounds),
    `_reads_of`; `collect_critique_batch` runs the rounds between the collect
    and the merge and releases the files only when every follow-up batch is
    terminal or canceled (`followups_safe`).
  - **`digest.py`:** docstrings only (`_name_discarded_retry` and
    `retarget_digest_request` serve the critique too).
  - `pipeline.py` is unchanged: the tally, the usage record and the level-1
    store read the final reads.
- **Tests:** **new: 87**, in `tests/test_batch_critique_recovery.py`: every
  transient type on three models (12), expired (1), permanent types (6),
  canceled (1), the shapes no retry can finish (8); a routed refusal, the hint,
  a fallback that refuses too, both 5.5 models, an unrouted category on Opus 5
  (6); `max_tokens` with text and empty on three models, cut again, expired
  then cut (8); the budget (6); the kept read's wording and tokens (3); a round
  that never ends, cannot be canceled, cannot be polled, a rejected submit, the
  uploads reused and released once (5); the cache (4); real time: the raised
  cap on three models with text and empty, cut again, a retry that raises, the
  shapes it does not retry, no headroom, an interrupted retry, both reads
  merged and cached, structured outputs, the upload-failure fallback (19);
  the pipeline on Hybrid and Economy (three shapes each), a read that stays
  failed, and Fast (8).
  - **Classified against `origin/main`** (a worktree at `40b2f96` with its own
    `src` first on the path; no shim needed, the new tests use no new name):
    **63 fail on behaviour, 0 on a missing name, 24 pass** (controls: the
    permanent types, canceled, the shapes no retry can finish, the real-time
    shapes and the no-headroom cases, a still-failed read not cached, the
    uploads reused and released once). The 18 re-baselined IDs fail there in
    their new form.
  - **Re-baselined in place, with the owner's approval** (fakes unchanged
    unless said; each failed on `origin/main` in its new form):
    - `tests/test_batch_refusal_recovery.py::test_an_errored_critique_read_keeps_its_error_type`
      (the helper answers every attempt; `[api_error]`, `[overloaded_error]`,
      `[rate_limit_error]`, `[timeout_error]` now read `<type>: the detail; 4
      retries, the last: <type>: the detail`; the five permanent IDs unchanged),
      `::test_a_canceled_or_expired_critique_read_keeps_its_text` (`[expired]`
      the same way; `[canceled]` unchanged),
      `::test_a_refused_critique_read_names_its_category` (`…; not retried: no
      fallback for category 'cyber' on claude-opus-5-5`);
    - `tests/test_response_shapes.py::test_a_failed_critique_envelope_is_a_failed_read_that_is_read_again`
      (`[errored]`, `[expired]`: COMPLETE, the read alone in a second batch,
      cached; `[canceled]` unchanged);
    - `tests/test_critique_terminal_outcome.py` (`RETRIED = {"max"}`): `test_rt_both_reads_unfinished[max]`,
      `test_rt_one_read_unfinished[max]`, `test_rt_a_finished_read_and_an_empty_cut_read`,
      `test_rt_a_single_read_run_that_is_cut_off`, `test_rt_structured_read_cut_off`,
      `test_pipeline_one_read_unfinished[max-realtime]`, `[max-batch]`,
      `test_pipeline_both_reads_unfinished[max-realtime]`, `[max-batch]` (the
      retry in the error, the calls and the tokens) and
      `test_batch_one_read_unfinished[max]` (its fake answers the follow-up
      finished: recovered, corroborated, cached).
    Nothing else moved.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2` 2.13.1,
  PyMuPDF 1.28.2):
  - Full suite on the code: **5,329 passed, 2 skipped, 10 deselected** (522 s),
    the baseline plus the 87, the same two environment skips. A JUnit diff
    against the baseline: of the 5,244 tests in both runs, **0 changed
    outcome** (the 18 re-baselined IDs pass in both, under their new
    assertions); the rest are the 87 new tests. The final run, after the
    docs: **5,329 passed, 2 skipped, 10 deselected** (524 s), the same JUnit
    diff.
  - **m1-m3 again on the final code** (SDK 1.7.0 and 1.8.0, identical): m1, 36
    of the 69 cases changed, each as the round-1 table said (a transient,
    expired or `max_tokens` read and Opus 5's cyber refusal recovered in a
    second batch of 1 item, on the fallback or at 128k, and the sheet cached;
    every named unrouted refusal gains its `not retried` note); m2, the six
    `max_tokens` cases take 3 calls (64k, 128k, 64k) and cache the sheet; m3,
    COMPLETE 4 of 4 and a warm run with no critique call for every retried
    shape on Hybrid, Economy and Fast; invalid request, canceled and the 5.5
    cyber refusal unchanged (PARTIAL), the latter with its note.
  - **m4, WP-01's acceptance** (the consumers the plan hands to other rows):
    a cross-QC and a citation-check reply stopped at `max_tokens`, refused,
    with no stop reason or at the context window read COMPLETE and are cached;
    an investigation turn so stopped reads COMPLETE (not cached). Recorded on
    WP-06.3, WP-12.6, WP-13.4 and in the plan's WP-01 Acceptance note.
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean; F401/F811/F841 on the
    touched files: clean except the pre-existing `critique.py`
    `DEFAULT_DIGEST_MAX_TOKENS` (on `origin/main`). `python scripts/scan_secrets.py`:
    clean (the new file staged). Keys are built at runtime by the stub, every
    parametrized case has an id, no invisible character was added.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:** CHANGELOG (Fixed); CLAUDE.md (a *Batch critique recovery* passage;
  the critique finder paragraph; the batch refusal passage's pointer); README
  (the critique's retries, the budget paragraph, the env table, the
  uncollected-batch sentence); the plan (the WP-01.8 note under "New step:
  batch refusals (R2)", with the correction; the WP-01 Acceptance note);
  DECISIONS (D-1's WP-01.8 note and the two amended lines, D-2's and D-4's
  notes); PROGRESS (this entry; the WP-01.8 row; WP-01's package status; the
  new WP-18.6 row and the WP-18 range; notes on WP-14.1, WP-14.3, WP-14.5,
  WP-06.3, WP-12.6 and WP-13.4; N4 and R2; Next up). No dependency changed.
- **Not verified:**
  - Live API behaviour (no budget, O-4): how often a critique batch item
    errors transiently, expires or is cut off; that a critique item at 128k is
    accepted (the digest already sends 128k batch items).
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - A sheet whose critique read keeps failing now costs up to four more batch
    reads at the default budget, and a cut-off read one more read at twice the
    cap; each round also waits for its batch (no stall watch, inside the
    collection bound), so a recovery can lengthen the critique stage.
  - Within a round the budget is spent in read order, so with one retry left a
    sheet's first read goes and its second waits (pinned).
  - A cached entry may hold a read a fallback model served or produced at
    128k, unmarked (WP-14.6's serving-model field).
  - A refused 5.5 critique read is not retried until the owner declares 5.5
    routes (the WP-01.5 question).
- **Found, not fixed** (noted on the owners' rows): the batch critique has no
  harvest of an abandoned batch (WP-18.6, new); the digest harvest's truncated
  item keeps its cap one round (WP-14.1); a real-time refusal's
  `recommended_model` is not acted on (WP-14.3); WP-01's acceptance gaps
  (WP-06.3, WP-12.6, WP-13.4).
- **Next:** in queue order, WP-05.3 (Wave 2, available). WP-11.3, WP-10.4,
  WP-06.2, WP-06.3 and WP-07.3 are available; WP-06.3, WP-12.6 and WP-13.4
  close WP-01. The owner question on 5.5 refusal routes (WP-01.5) is still open.

### 2026-09-30 — WP-01.7: an interrupted stream is retried, its partial read judged, its usage kept ([PR #185](https://github.com/Abe-Borg/drawing-analyzer/pull/185))

- **Slice and IDs:** WP-01.7. U1's partial-stream part (implemented+validated;
  the serving model and fallback iterations stay WP-14.3/14.6's), plan WP-14
  step 7, and the plan's WP-01 regression case "stream interruption before
  output, after text, and after a complete-looking JSON object". Contract: a
  WP-01.7 note under D-1 (amending its "interrupted stream" line), one under
  D-4 (nothing moved) and an input for the open D-7, in `DECISIONS.md` (the
  owner's rules). No migration-register row. **WP-01 is not done**: WP-01.8
  remains. The plan's WP-01 acceptance clauses this slice owns hold (tests
  named below): no interrupted read enters a cache promising completed work (a
  read with no stop reason is refused at every writer; the warm run re-reads
  it); the usage available from an interrupted stream is captured and its
  uncertainty is visible (`interrupted_attempts` per record, the run total, a
  run.log line); no regression to ordinary successful reads (0 of the 5,135
  tests in both runs changed outcome).
- **Base.** `main` = `origin/main` = `2ebb413` (WP-01.6's merge,
  [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184)). Open PRs:
  [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot)
  and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0
  support), neither a remediation slice. Baseline **5,138 passed, 2 skipped,
  10 deselected** (430 s), identical to WP-01.6's final count; the two skips
  are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0, `httpx2`
  2.13.1, PyMuPDF 1.28.2.
- **The request's facts, re-verified** (corrections marked):
  - **Streamed call sites.** The digest, the critique, the review plan,
    synthesis, the focus report and the batch direct-call rescue go through
    `digest.stream_message` (batch's Files-API inline fallback too, through
    `digest_sheet`). **Correction: the investigation streams too**, every
    turn (`call_with_refusal_fallback(..., method="stream")` or
    `stream_message`), a seventh path. Each had its own transient-retry loop
    on `digest._is_transient_error`, and each raised straight into it.
  - **What the SDK raises** (p1, the real SDK over `AnthropicAPIStub`, every
    `CUTS` x `ENDS`, both namespaces, Opus 5.5 and Sonnet 5.5): an SSE
    `error` event is `anthropic.APIStatusError`, `status_code` 200, the
    event's type on `.type`; a dropped connection is `httpx2.RemoteProtocolError`
    (not wrapped); a clean end with no event is the SDK's `AssertionError`
    (confirmed). `_is_transient_error` recognised none, so every stage failed
    after one request with `HTTP 200: {'type': 'error', …}` or `peer closed
    connection without sending complete message body` (confirmed).
  - **`current_message_snapshot`**: readable after the `with` exits; before
    `message_delta` no stop reason and `message_start`'s usage (input, cache
    counters, the `cache_creation` split, output 0); **after `message_delta`
    the complete read** (stop reason, final usage) even when the stream then
    drops or errors; with no `message_start`, the SDK's `AssertionError`.
    The class is `ParsedMessage` / `ParsedBetaMessage`.
  - **The SDK's own retries** re-send a request, never a started stream: 1
    request with `max_retries=2` (the stub client uses 0; production the
    SDK's default 2). So a host retry doubles no layer.
  - **The ladder and the rank** (p2): a snapshot reads `unfinished …
    (stop_reason=None)` (`empty …` before any text) through
    `digest_terminal_error` and `unfinished_reply_error`; `keep_digest_read`
    ranks one with content a partial read (2), above an empty or raised
    retry; a `before_message_stop` snapshot is finished (end_turn).
  - **Usage lost, per consumer** (m3, 66 cases): the digest recorded 0/0; the
    critique dropped the interrupted read's tokens from the sheet's record
    (400 of 800); the planner a 0-token record; synthesis and focus nothing;
    the investigation 0/0 with the stage PARTIAL. Nothing was retried.
  - **Over the whole suite** (m2, an instrumented `_dispatch_messages`): 5 of
    2,589 streamed calls raised inside `get_final_message`, all in WP-02.3's
    two recorded limits; 134 raised before the stream existed (fakes).
  - **SDK 1.8.0** in a scratch venv (`--system-site-packages`,
    `anthropic==1.8.0 --no-deps`): p1, p2 and m3 identical; the new tests,
    `test_response_shapes`, `test_sdk_responses` and `test_sdk_contract`
    (324) pass there too. m3 on Sonnet 5.5 (the digest and the critique,
    22 cases): identical to Opus 5.5.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds and a follow-up, seven choices, a case table per option; every
  recommended option taken):
  - **Round 1.**
    - **Retry:** transient interruptions, one predicate
      (`digest._is_transient_error`): a dropped connection, a stream with no
      event (read as dropped), an SSE `error` event whose type stands for a
      transient status through the existing `_TRANSIENT_STATUSES`; inside each
      stage's existing retries (2 per call; the rescue inside its per-sheet and
      collection budgets). Not taken: every interruption; a dropped connection
      only; no retry.
    - **The partial read is the reply** once the retries are spent, judged by
      D-1's classifier (each stage's N27 path). Not taken: never finished
      even after `message_delta`; discard the partial.
    - **Wording:** the ladder's with `interrupted=` in its parentheses; with
      nothing in hand `stream interrupted (<type>: <message>)` / `stream
      interrupted (connection dropped — try again)`. Not taken: the ladder
      alone; a new ladder word.
    - **The investigation:** retry and usage; a partial turn never used. Not
      taken: usage only (a second predicate); leave it to WP-13.4.
  - **Round 2.**
    - **Usage:** a counter on the record (`interrupted_attempts`), totalled
      on the run, a run.log line; terminal statuses and the cost unchanged,
      `is_billable_but_unpriced` untouched. Not taken: a terminal status only;
      the counter plus an unknown cost (D-7's); input only.
    - **The digest's read across its retries:** the best, by
      `keep_digest_read`. Not taken: the last attempt's.
    - **Cache:** admit a snapshot that got `message_delta`; nothing moves.
      Not taken: use it and never cache it.
  - **Follow-up** (found while designing: the round-1 table said "any cut",
    the round-2 usage preview showed one attempt): a snapshot that already got
    `message_delta` is the reply at once, not retried. Not taken: retry it too
    (paid for nothing on the digest).
- **What changed** (production):
  - **`core/stream_interruption.py` (new, stdlib only):** `StreamInterrupted`
    (`cause`, `partial`, `kind`, `error_type`, `error_message`, `label`) and
    `stream_snapshot`. Its own module because a reload of `api_config` (the
    report-chat tests do one) re-created the class, so `digest`'s `isinstance`
    stopped matching in every later test: measured, the five flipped tests
    failed in the first full run and passed alone; pinned by
    `test_a_reload_of_api_config_keeps_one_exception_class`.
  - **`core/api_config.py`:** `_dispatch_messages` raises
    `StreamInterrupted(exc, snapshot) from exc` for a failure while the
    stream is read, and returns a snapshot with a stop reason as the reply
    (logged). Re-exports the class.
  - **`digest.py`:** `_ERROR_TYPE_STATUS`; `_is_transient_error` /
    `_is_transient_interruption`; `_clean_error` / `_interruption_error`;
    `digest_terminal_error(..., interrupted=)` and
    `unfinished_reply_error(..., interrupted=)`; `StreamUsage`,
    `StreamedReply`, `stream_reply(..., send=)`; `SheetDigest.interrupted_attempts`;
    `digest_sheet`'s loop folds every attempt's read through
    `keep_digest_read`, names a call that ended with nothing once, and sums
    every attempt's usage.
  - **`critique.py`:** `_critique_read` captures, retries and judges the
    partial (`outcome_from_message(..., interrupted=)`), the read's usage from
    every attempt; `interrupted_attempts` on the outcome and the result.
  - **`review_planner.py`, `synthesis.py`, `focus.py`:** one loop,
    `digest.stream_reply(..., send=stream_message)`; `interrupted_attempts`
    on their results; a failure with nothing back keeps its usage.
  - **`investigate.py`:** an interrupted turn's usage is the finding's; the
    turn is retried by the shared predicate; its partial is never used.
  - **`batch_digest.py`:** `_record_interrupted_rescue` (a partial read
    folded like any rescue read; one that held nothing a non-billable
    REAL_TIME attempt parked on the slot); the rescue names a call that
    ended with nothing once; `DigestUsageAttempt.interrupted_attempts`; the
    inline fallback passes the count.
  - **`models.py`:** `UsageRecord.interrupted_attempts` (additive, in
    `to_dict`), `RunUsage.interrupted_attempts` (in `to_dict`, so in
    `run_manifest.json`'s usage block).
  - **`pipeline.py`:** `_record_usage(interrupted_attempts=)` at the digest
    (both shapes), critique, planner, synthesis, focus and investigation
    records; a synthesis or focus failure with an interrupted attempt is one
    FAILED record even when nothing came back.
  - **`run_journal.py`:** the usage section's lower-bound line.
- **Tests:** `tests/fixtures/sdk_transport.py` (the stub's `stream` knob takes
  an optional `error` body, additive). **New: 104**, in
  `tests/test_interrupted_streams.py`: the capture site at every cut before
  `message_delta` x (error event, drop) x both namespaces x both 5.5 models
  (32), after `message_delta` (4), the clean-end controls (8), no event (2),
  pre-stream failures not wrapped (2), the reload (1); the predicate over
  every API error type (10), its status table (1) and the other causes (5);
  the ladder (5); the digest through the pipeline (11, the plan's three cuts
  included); the
  critique (3); the review plan, synthesis and focus (9); the investigation
  (2); the batch rescue and inline fallback (4); the usage surfaces and the
  cache (5).
  - **Classified against `origin/main`** (a worktree at `2ebb413` with its
    own `src` first on the path, plus a shim giving it the new names with
    today's behaviour), on the first 102 new tests and the 5 flipped IDs:
    **94 fail on behaviour, 0 on a missing name, 13 pass** (controls: the
    eight clean early ends, the two pre-stream failures, a clean run's
    surfaces, the no-bump pin, the finished ladder case). The inline-fallback
    and reload tests came later: each shown failing without its fix.
  - **`tests/test_response_shapes.py`:** the two WP-01.7 recorded limits
    flipped (5 test IDs), each failing on `origin/main`:
    `test_recorded_limit_an_interrupted_digest_stream_is_not_retried_and_its_usage_is_lost`
    -> `test_an_interrupted_digest_stream_is_retried_and_its_usage_kept`;
    `test_recorded_limit_an_interrupted_stream_loses_its_usage` ->
    `test_an_interrupted_stream_is_retried_and_keeps_its_usage`. The other 50
    tests of the file pass unchanged. Nothing else was re-baselined.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2` 2.13.1,
  PyMuPDF 1.28.2):
  - Full suite on the final code: **5,242 passed, 2 skipped, 10 deselected**
    (485 s), the baseline plus the 104, the same two environment skips. A
    JUnit diff against the baseline: of the 5,135 tests in both runs, **0
    changed outcome**; the rest are the 104 new tests and the 5 flipped IDs.
  - **m3 again on the final code** (66 cases, SDK 1.7.0 and 1.8.0,
    identical): every stream interrupted before `message_delta` on its first
    attempt is retried and the stage completes and caches (the investigation
    is never cached in the mini set, as before), the record carries the
    interrupted attempt's input and `interrupted_attempts` 1; after
    `message_delta`, one request, `interrupted_attempts` 0; the clean-end
    twins unchanged.
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean; F401/F811/F841 on the
    touched files: clean except the pre-existing `critique.py`
    `DEFAULT_DIGEST_MAX_TOKENS` and `pipeline.py` `normalize_specs_text`
    (both on `origin/main`). `python scripts/scan_secrets.py`: clean (the new
    files staged). Keys are built at runtime by the stub, every parametrized
    case has an id, no invisible character was added.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:** CHANGELOG (Fixed: U1's partial-stream part); CLAUDE.md (an *An
  interrupted stream* passage; the N27 line; the usage paragraph; the `core/`
  paragraph; the stub's `stream` knob; WP-01.7 removed from the recorded-limit
  owners); README (a stream that breaks mid-reply; the usage lower-bound
  line); the plan (WP-01 "Other notes" with the correction; WP-14 step 7);
  DECISIONS (D-1's WP-01.7 note and its amended line, D-4's note, a D-7
  input); PROGRESS (this entry; the WP-01.7 row; notes on WP-01.8, WP-06.3,
  WP-13.4, WP-14.4 and WP-14.5; U1; Next up, which also records WP-01.6's
  merge as `2ebb413`). No dependency changed.
- **Not verified:**
  - Live API behaviour (no budget, O-4): how often a stream breaks mid-reply,
    which `error` event types the API actually sends mid-stream, and whether
    an interrupted attempt is billed exactly its `message_start` input (the
    API reports it; the output is unknown by construction, which is what the
    counter marks).
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - A transient interruption now costs up to two more requests per call (the
    existing bound); a digest whose every attempt breaks bills three
    `message_start` inputs, all recorded.
  - The output of an interrupted attempt is unreported: the totals are lower
    bounds, said in run.log and the manifest, and the cost stays a number
    (D-7 decides whether it should read unknown).
  - The real-time stages still keep one usage record per call, summing every
    attempt (WP-14.5's).
  - An `other` cause (a `RuntimeError` or tool-JSON `ValueError` from the
    SDK's accumulator) is judged as itself: not retried, its partial read the
    reply, worded `interrupted='RuntimeError'`.
- **Found, not fixed** (noted on the owners' rows): cross-QC does not stream,
  so a raised-cap move onto `stream_message` meets `StreamInterrupted`
  (WP-06.3); the batch critique's real-time fallback now retries an
  interruption (WP-01.8); the investigation's partial-turn replay (WP-13.4).
- **Next:** in queue order, WP-01.8 (Wave 2, available), the last of WP-01.
  WP-11.3, WP-10.4, WP-06.2, WP-06.3, WP-05.3 and WP-07.3 (Wave 2) are
  available. The owner question on 5.5 refusal routes (WP-01.5) is still open.

### 2026-09-29 — WP-01.6: one fallback-aware text join, and the remaining consumers read the stop reason first ([PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184))

- **Slice and IDs:** WP-01.6. U2 (the join part; implemented+validated),
  N4 (the planner, identity, synthesis, focus, harvest-structuring and
  verification part; implemented+validated), N27 (the same shape on the
  streamed set-level stages), plan WP-09 step 6. Inherited onto the row and
  decided here: the identity corpus reading an errored sheet's text (WP-01.3's
  note) and the planner/identity refusal wording. Contract: a WP-01.6 note
  under D-1 and one under D-4 in `DECISIONS.md` (the owner's rules), two
  migration-register rows. **WP-01 is not done**: WP-01.7 and WP-01.8 remain.
  The plan's WP-01 acceptance clauses this slice owns hold (tests named
  below): no failed terminal state enters a cache promising completed work
  (the five consumers and verification); no regression to ordinary
  successful prose output or valid uncertain findings (0 of the 4,987 tests in
  both runs changed outcome; a finished reply is used and cached as before;
  a valid NOT_VISIBLE verdict is still a judgment); a fallback-joined reply
  reads as the text the model wrote.
- **Base.** `main` = `origin/main` = `59a9f93` (WP-01.5's merge, after the
  5.5 defaults, [PR #183](https://github.com/Abe-Borg/drawing-analyzer/pull/183)).
  Open PRs: [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174)
  (dependabot) and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175)
  (SDK 1.8.0 support), neither a remediation slice. Baseline **4,993 passed,
  2 skipped, 10 deselected** (643 s), identical to WP-01.5's final count; the
  two skips are IPv6 loopback and chmod as root. Python 3.11.15, SDK 1.7.0,
  `httpx2` 2.13.1, PyMuPDF 1.28.2.
- **The request's facts, re-verified** (corrections marked):
  - **`_message_text`'s importers: 11**, as the plan says (batch_digest,
    citation_check, critique, cross_qc, focus, investigate, prose_harvest,
    review_planner, set_identity, synthesis, verify), plus the digest itself.
    **No Python module joined a reply's text any other way** (every loop over
    `content` was checked: verify's request canonicalizer, citation's source
    trail, investigate's cache breakpoints and tool requests, the request-side
    `file_upload`). The report's chat widget renders each block in its own
    element and sends no `fallbacks`, so no fallback block reaches it.
  - **The five consumers read no stop reason** (confirmed). What each caches:
    the planner `stage=review_plan` (`review_plan_cache_key`: corpus hash,
    identity hash, model, prompt version, max_tokens, effort, thinking,
    max_items; payload: the sanitized plans), identity `stage=identity`
    (`identity_cache_key`: corpus hash and request params; payload: the
    regex-unioned identity), synthesis and focus the stage cache
    (`stage_cache_key("synthesis"/"focus")` with `_SYNTHESIS_CACHE_CONTRACT` /
    `_FOCUS_CACHE_CONTRACT` = 1; payload: `text`), the harvest
    `stage_cache_key("prose_harvest_item")` with `_HARVEST_CACHE_CONTRACT` = 1
    (payload: the finding), keyed per contract (fenced or structured).
    **Stage status on `origin/main`** (measured, m2 below): every
    non-finished shape whose content parsed read COMPLETE (identity, planner,
    synthesis; the focus report's journal COMPLETE; the harvest item
    `structured`) and was cached; a refusal with an explanation failed the
    planner and identity (`… no parseable … block`), degraded the harvest
    item, and was kept by synthesis and focus as their text, COMPLETE, cached;
    a textless refusal failed synthesis and focus (`empty … result`) with no
    usage recorded.
  - **Verification** tested `max_tokens` and `refusal` only (confirmed): the
    context window, `None`, `tool_use`, `pause_turn`, `compaction` and an
    unknown reason were parsed as verdicts (COMPLETE, cached).
  - **The fallback block** (p1, through the real SDK): on both namespaces,
    create and stream, Opus 5.5 and Sonnet 5.5, the SDK keeps
    `[text, fallback, text]` in order and relabels the message with the
    serving model; the beta namespace parses a `BetaFallbackBlock` (`from_`,
    `to`), **the plain namespace a `TextBlock` (`ParsedTextBlock` from a
    stream) whose `type` is `"fallback"`** (no `from_`), so only `type` tells
    it apart. The old join gave `1\n2 inches` and `VA\nV-3` inside the JSON.
    **Where the substitute resumes** (Anthropic's refusals-and-fallback page,
    read this session): on a streamed request the declined partial stays, the
    `fallback` block marks the boundary and "the fallback model continues from
    the partial output" (only its text blocks are passed as context); on a
    **non-streamed** request "the response omits the declined model's partial
    output, and the fallback model answers from scratch", `[fallback, text]`.
    **Correction to the fixture's model, recorded not changed:**
    `sdk_responses.splice_fallback` builds the streamed shape for non-streamed
    replies too (identity, harvest, verify, cross-QC, citation are
    non-streaming); the new join reads both shapes correctly.
  - **The 5.5 defaults** (main, #183): synthesis, focus and the planner run on
    Opus 5.5, identity and the harvest on Sonnet 5.5; every real-time call to
    either carries the server-side fallback (`fallbacks: "default"`), so a
    fallback block can reach the Sonnet stages. Measured on both models.
- **Measured before any code** (scratch probes, zero API calls, the real SDK
  over `AnthropicAPIStub`; a pytest plugin for the suite-wide counts):
  - **p1:** the fallback shapes above, 5 shapes x 4 entry points x 2 models.
  - **m2:** the six consumers x 11 shapes (control, a refusal with the
    stage's content, with an explanation, empty; `max_tokens`; the context
    window; no stop reason (the streamed stages' real N27 cut, a synthetic
    `None` for the non-streamed ones); `tool_use`; `pause_turn`;
    `compaction`; an unknown reason), each through the mini set and a warm
    re-run: the table under the facts above.
  - **m3, over the whole suite:** 3,882 `_message_text` calls in 12 modules;
    6 had more than one text block, all `[text, fallback, text]` from
    WP-02.3's recorded limits; none had two ordinary text blocks. 237 identity
    corpora, 9 with an errored sheet, **7 carrying its text** (all in
    `test_digest_partial_reads.py` and `test_drawing_acceptance.py`).
  - **p1 and m2 on SDK 1.8.0** in a scratch venv (`--system-site-packages`,
    `anthropic==1.8.0 --no-deps`): identical.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, six choices, a case table per option; every recommended option
  taken):
  - **Round 1.**
    - **Join rule:** nothing across a fallback block, `"\n"` elsewhere
      (unchanged), `between=` for WP-12.1. Not taken: `""` everywhere (widens
      into WP-12.1, changes multi-block citation replies); `""` also between
      cited blocks.
    - **Consumers:** fail and keep nothing, each on its existing failure path;
      synthesis and focus ship no text and record the billed reply as a FAILED
      attempt; a harvest item degrades. Not taken: ship a cut-off
      synthesis/focus under an "incomplete" banner; use a parseable
      non-finished reply for the run without caching it.
    - **Verification:** the existing `truncated` counter, the two pinned notes
      kept, new notes naming the kind. Not taken: a fourth counter; the
      ladder's wording (re-baselines two pinned notes).
    - **Identity corpus:** skip an errored sheet's text, keep its failure line
      and text-layer windows. Not taken: keep it; skip the whole sheet.
  - **Round 2.**
    - **Wording:** the digest's ladder with a noun per stage; a FINISHED
      reply that fails its parse keeps its wording. Not taken: a stage-neutral
      sentence.
    - **Old entries:** bump the synthesis, focus and harvest terms 1 -> 2;
      leave the planner, identity and verification keys (residuals recorded).
      Not taken: bump nothing (a refused synthesis cached by 1.6/1.7 keeps
      shipping as the overview); terms everywhere (one planner and identity
      call per set, every verdict re-bought, a possible critique re-read).
- **What changed** (production):
  - **`core/reply_text.py` (new):** `reply_text(resp, *, between="\n")`,
    `FALLBACK_BLOCK_TYPE`; stdlib only, shape-tolerant, never raises.
  - **`digest.py`:** `_message_text` removed; `reply_text` everywhere;
    `unfinished_reply_error(resp, text, *, noun)` (the classifier first, the
    ladder's wording, a refusal's `stop_details` logged).
  - **The 11 importers** read `reply_text` (one import each, alphabetical).
  - **`review_planner.py`, `set_identity.py`:** the check before the parse;
    `_sheet_block` gives an errored sheet its failure line, never its text.
  - **`synthesis.py`, `focus.py`:** the check before the text is kept; a
    failed reply ships `""`; `replied` (runtime); the contract terms 2.
  - **`prose_harvest.py`:** the check before either parse (fenced or bare
    structured); a non-finished reply degrades its item and is not cached;
    `_HARVEST_CACHE_CONTRACT` 2.
  - **`verify.py`:** `_verdict_from_response` and `_degrade_kind` read
    `classify_stop_reason`; `DEGRADE_TRUNCATED`'s comment says what it now
    covers.
  - **`pipeline.py`:** a failed synthesis or focus reply that came back is one
    FAILED usage record.
- **New tests: 145**, all passing: `tests/test_reply_text.py` (51: the rule
  over API JSON (12 cases), `between`, the type test, the no-fallback
  equivalence, odd shapes, every fallback shape through the real SDK (16), the
  plain namespace's `TextBlock` (4), the structural pins (15)) and
  `tests/test_consumer_terminal_outcomes.py` (94: each of the five consumers
  under 10 non-finished kinds, not cached, with its controls; the identity
  corpus; the stage terms and a contract-1 entry that misses and stays on
  disk; the harvest under both contracts; verification's eight kinds and its
  controls; the pipeline: statuses, errors, FAILED usage, warm re-reads, the
  identity request without the refusal text, a fallback-split stage reply
  read whole).
  - **Classified against `origin/main`** (a worktree at `59a9f93` with its
    own `src` first on the path, plus a shim giving `reply_text` today's
    `"\n"` join): **106 fail on behaviour, 14 fail on structure** (the second
    join is still there: the old-join, every-reader and no-module pins),
    **5 fail only on a new name** (the kernel module's file, `.replied` on a
    finished, a finished-empty and a skipped synthesis or focus), **20 pass**
    (controls: finished replies used and cached, finished wording unchanged,
    the rule's no-fallback cases, verification's two existing notes, the
    empty harvest replies that already degraded, a clean identity corpus).
  - **`tests/test_response_shapes.py`:** the five recorded limits flipped (8
    test IDs), each shown failing in its original form against the fix first:
    `test_recorded_limit_synthesis_and_focus_keep_and_cache_a_refusal` ->
    `test_a_refused_synthesis_or_focus_report_is_not_kept_or_cached`;
    `test_recorded_limit_a_stream_cut_before_message_delta_is_kept_and_cached`
    -> `test_a_stream_cut_before_message_delta_is_not_kept_or_cached`;
    `test_recorded_limit_a_fallback_inside_the_findings_json_loses_the_finding_and_is_cached`
    -> `test_a_fallback_inside_the_findings_json_keeps_the_finding`;
    `test_recorded_limit_a_fallback_in_the_prose_splits_a_word_and_is_cached`
    -> `test_a_fallback_in_the_prose_reads_as_the_served_text`;
    `test_recorded_limit_a_fallback_in_a_critique_fails_a_good_read` ->
    `test_a_fallback_in_a_critique_is_a_good_read`. All 8 fail on
    `origin/main`; the other 47 tests of the original file pass unchanged on
    the fix.
  - **One pinned value moved by the approved bump:**
    `tests/test_prose_match_signatures.py::test_a_refused_item_keys_its_structuring_call_like_any_straggler`
    asserted `_HARVEST_CACHE_CONTRACT == 1` (WP-09.2's "no bump"); it now
    asserts 2, with a comment. The rule it pins is unchanged. Nothing else was
    re-baselined.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2` 2.13.1,
  PyMuPDF 1.28.2):
  - Baseline before any change: **4,993 passed, 2 skipped, 10 deselected**.
  - Full suite on the final code: **5,138 passed, 2 skipped, 10 deselected**
    (636 s), the baseline plus the 145, the same two environment skips. A
    JUnit diff against the baseline: of the 4,987 tests in both runs, **0
    changed outcome**; the rest are the 145 new tests and the 8 flipped IDs.
  - **Instrumented run on the final code** (a pytest plugin over the whole
    suite): `reply_text` differs from the old `"\n"` join on 0 replies outside
    the new and flipped tests. `unfinished_reply_error` fired 7 times there,
    each changing wording only: a textless `max_tokens` synthesis or focus
    reply (5, `empty synthesis (stop_reason='max_tokens')` where it read
    `empty synthesis result`; the tests assert `"empty focus report" in …` or
    nothing about the text), and the planner and identity in
    `test_a_refused_stage_is_not_complete_and_not_cached` (2: status and
    re-read unchanged, the error now names the refusal). Verification's
    no-verdict notes outside the new tests: the two existing ones, unchanged.
  - **The probes again on the final code** (SDK 1.7.0 and 1.8.0, identical):
    m2's 66 cases: every non-finished shape fails (planner, identity,
    synthesis: FAILED; the focus report: its error, no text), is re-read on
    the warm run and, for synthesis and focus, is one FAILED usage record;
    the harvest item degrades; verification is FAILED with `truncated=1`;
    the six controls are unchanged (COMPLETE, cached).
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean; F401/F811/F841 on the
    touched files: clean except the pre-existing `critique.py`
    `DEFAULT_DIGEST_MAX_TOKENS` (WP-01.5's note). `python
    scripts/scan_secrets.py`: clean (the new files staged). Keys are built at
    runtime by the stub, every parametrized case has an id, no invisible
    character was added.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:** CHANGELOG (Fixed: U2, N4, N27); CLAUDE.md (a *One text join, and
  the remaining response consumers* passage; the classifier's adopters and
  `reply_text` in the `core/` paragraph; verification's `_degrade_kind`; the
  identity corpus; WP-01.6 removed from the recorded-limit owners; the
  harvest contract's value); README (the set-level calls and verification;
  the fallback join); the plan (WP-01 steps 1–2 and "Text join (U2)" notes
  with the corrections; WP-09 step 6; the slice range); DECISIONS (D-1's and
  D-4's WP-01.6 notes; two migration-register rows); PROGRESS (this entry;
  the WP-01.6 row; notes on WP-01.7, WP-06.3, WP-10.4, WP-12.1, WP-12.6,
  WP-13.4 and WP-14.5; U2, N4, N27; Next up, which also records WP-01.5's
  merge as `59a9f93`). No dependency changed.
- **Not verified:**
  - Live API behaviour (no budget, O-4): that a streamed mid-output fallback's
    continuation never adds or drops a character at the boundary (the docs
    say it continues from the partial; the join adds nothing, so what the
    models wrote is what is read); how often a set-level stage is declined.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - The next run pays one synthesis call per set, one focus call per focus
    run, and each harvest straggler once (the three terms). No digest,
    critique, cross-QC, citation, investigation or verification key moved.
  - Recorded residuals (D-4's WP-01.6 note): a plan, identity or verdict an
    earlier version cached from a non-finished reply keeps serving until its
    inputs change; a digest an earlier version cached from a fallback-split
    reply (possible since 1.3.0, real-time Opus 5) keeps its `"\n"`.
  - A refused planner or identity now reads `refused review plan (…)` where
    it read `… no parseable … block`: the stage status and re-read are
    unchanged.
- **Found, not fixed** (noted on the owners' rows): the non-streamed fallback
  shape in the fixtures (WP-06.3, WP-12.1); the harvest's usage record keeps
  its stage-level status, so a degraded structuring call is billed inside a
  COMPLETE record (WP-14.5); five more admission predicates for the cache map
  (WP-10.4).
- **Next:** in queue order, WP-01.7 and WP-01.8 (Wave 2, both available).
  WP-11.3, WP-10.4, WP-06.2, WP-06.3, WP-05.3 and WP-07.3 (Wave 2) are
  available. The owner question on 5.5 refusal routes (WP-01.5) is still open.

### 2026-09-29 — WP-01.5: a refused batch sheet is retried on its fallback model, inside one per-sheet retry budget ([PR #182](https://github.com/Abe-Borg/drawing-analyzer/pull/182))

- **Slice and IDs:** WP-01.5. R2 (implemented+validated). Inherited onto the
  row and done here: `billing_error` classified; the batch critique's errored
  read keeps its type. Split off to a new row, **WP-01.8** (the owner's
  decision): retrying failed batch critique reads and WP-01.4's raised-cap
  question. Contract: a WP-01.5 note under D-1 in `DECISIONS.md` (the owner's
  rules). No migration-register row: no cache key, entry, prompt or schema
  moved. **WP-01 is not done**: WP-01.6, WP-01.7 and WP-01.8 remain. The
  plan's R2 acceptance, "Refusal recovery preserves selected transport and
  bounds", holds (tests named below).
- **Base.** `main` = `origin/main` = `77a3f03` (WP-02.3's merge). The local
  `origin/main` ref was stale (`614951d`, [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161)) until fetched; the branch
  was already at `77a3f03`. Open PRs: [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot) and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK
  1.8.0 support), neither a remediation slice, neither merged; no pin changed.
  Baseline **4,887 passed, 2 skipped, 10 deselected** (409 s), identical to
  WP-02.3's final count; the two skips are IPv6 loopback and chmod as root.
  Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2.
- **The request's facts, re-verified** (all held; corrections marked):
  - `batch_digest._PERMANENT_ITEM_ERROR_TYPES` held invalid_request_error,
    authentication_error, permission_error, not_found_error and
    request_too_large. The SDK's `ErrorObject` has nine types (identical on
    1.8.0); `billing_error` was missing and `request_too_large` is not one of
    the nine.
  - The seams exist as named (`RECOVERY_BATCH`/`RECOVERY_DIRECT`,
    `DEFAULT_MAX_BATCH_RESUBMIT_ROUNDS = 4` with its env override,
    `_replace_result_with_attempt_history`, `_batch_item_error_text`,
    `_item_retry_params`, `_harvest_abandoned_batch`,
    `_rescue_failed_items_sync`, `_recover_via_batch_resubmit`, `_parse_item`;
    `digest.MAX_TOKENS_RETRY_CEILING`, `keep_digest_read`,
    `digest_terminal_error`, `TerminalOutcome.raised_cap_may_finish`). The
    batch critique's equivalents: `batch_critique._outcome_from_envelope` (the
    per-read envelope) and `collect_critique_batch` (one terminal collect, no
    follow-up batch, harvest or rescue; a non-terminal batch is canceled and
    its sheets degrade).
  - The registry: only Opus 5 declares `supports_refusal_fallback`; Opus 4.8
    was named the target only in comments. **Confirmed: no named constant.**
  - `fallbacks` is rejected on the Batches API (the code's own comment and
    Anthropic's docs).
  - **`recommended_model`, measured first (p0):** the plain
    `RefusalStopDetails` declares `category`, `explanation`, `type` but has
    `extra='allow'`, so a batch result keeps `recommended_model` as a pydantic
    extra (`getattr` works, `model_extra` holds it), on SDK 1.7.0 and 1.8.0.
    **Correction to the plan step:** per the SDK's own docstring and the API
    docs, the field is set only when a server-side fallback attempt could not
    run (the fallback model rate-limited or overloaded), i.e. only on a
    request that carried `fallbacks`, which a batch item cannot. So on a batch
    refusal it is absent in practice, and the registry route is the real
    target. Batch results carry no `fallback_credit_token` either. Every
    category (cyber, bio, frontier_llm, reasoning_extraction, general_harms,
    `None`, and an unknown string) parses on the plain namespace.
- **Measured before any code** (scratch probes, zero API calls, the real SDK
  over `AnthropicAPIStub`, WP-02.3's shapes; a stub subclass stalls a named
  batch until canceled; the fake sleep drives a fake monotonic clock):
  - **m1, every shape at every site.** Digest, both recovery transports,
    sites primary / rounds (the first resubmission) / harvest / direct rescue,
    shapes: a refusal per category with and without `recommended_model`, no
    `stop_details`, a refusal with text, the nine error types, canceled,
    expired (164 cases). Today: every refusal fails with no retry at the
    primary, the rounds, the follow-up and the rescue (1 item; the rescue's
    refusal after server-side fallback likewise); nothing logs `stop_details`;
    `billing_error` is resubmitted like the four transient types; canceled is
    named and not resubmitted, expired is resubmitted; **the harvest
    resubmits every unresolved item it read, a refusal and a permanent
    `invalid_request_error` included, with identical params** (so a refusal
    was resubmitted to the same model). Critique (one site, 27 shapes plus a
    `max_tokens` read): every failed read fails and is never retried; an
    errored read's error keeps the message and drops the type (`the detail`).
  - **m2, every retry a sheet can get today.** `RECOVERY_BATCH` (the
    pipeline): 5 submissions worst case (primary + 4 rounds), shared already
    by transient, expired, raised-cap (64k -> 128k, once) and abandoned rounds;
    11 with `DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS=10`; a refusal 1.
    `RECOVERY_DIRECT`: 2 batch items + 3 real-time calls (the rescue's 1 + 2
    transient retries); a lone sheet whose batch failed server-side skips the
    follow-up (1 + 3). The real-time digest: 6 calls (2 attempts x (1 + 2
    transient)). Production's client also keeps the SDK's `max_retries=2`
    under every HTTP call.
  - **m3, a swapped model** (a prototype patch resubmitting a refused item on
    Opus 4.8): the finished read was stored under the requested model's key at
    both levels (4 puts), a warm run served it free as the Opus 5 digest, the
    ledger labelled the attempt `claude-opus-5` at $5/$25 (Opus 4.8's price
    too). The server-side fallback already behaves this way
    (`test_recorded_limit_the_serving_model_is_not_read`).
  - **m4:** p0, m1 (digest and critique), m2 and m3 on SDK 1.8.0 in a scratch
    venv (the project `--no-deps`, its other dependencies pinned as
    installed): identical, line for line.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, eight choices, a case table per option; every recommended option
  taken):
  - **Round 1.**
    - **Which refusals:** a registry route per category. Not taken: any named
      category on Opus 5; every refusal on Opus 5 (null included); Opus 5 and
      Sonnet 5 (a guessed Sonnet route).
    - **Target:** `recommended_model` if registered and not the refuser, else
      the route's; with neither, no retry. Not taken: the registry target only;
      `recommended_model` verbatim.
    - **Shared bound:** a per-sheet budget equal to the rounds (default 4, the
      existing env variable), counting every resubmission at every site; a
      refusal once; the harvest asks the same predicate. Not taken: the same
      plus the real-time digest; a refusal round outside the rounds.
    - **Cache:** the requested model's key. Not taken: the same plus a stored
      `served_model` field; the serving model's key; not cached.
  - **Round 2.**
    - **`billing_error`:** permanent; `request_too_large` kept. Not taken:
      transient within the budget; permanent and `request_too_large` dropped.
    - **Critique:** the error type here; retries on a new row. Not taken:
      everything here; the type plus the real-time raised cap.
    - **Logging:** the category in the error, the rest in the diagnostics log;
      nothing in the manifest; one approved re-baseline. Not taken: the log
      only; the log, the error and a `refusals` manifest key.
    - **Direct rescue:** `RECOVERY_DIRECT` is the full-rate policy. Not taken:
      only when passed explicitly (a sentinel default); never at full rate.
  - **One reading recorded:** the gate decides whether, the target decides
    where. The round-2 target table's "route target: any" row is read as
    "whatever the route's target is", since the round-1 choice says everything
    unrouted is not retried. It changes nothing measured (no batch refusal
    carries the hint).
- **What changed** (production):
  - **`core/api_config.py`:** `ModelCapabilities.refusal_fallback_routes`
    (pairs, hashable); Opus 5 declares `(("cyber", MODEL_OPUS_48),)`;
    `refusal_fallback_target(model, category)`; `is_registered_model(model)`.
  - **`digest.py`:** `retarget_digest_request(params, model)` (the builder's
    rules: thinking kept only where taken, effort clamped, `max_tokens` capped;
    the input untouched); `RefusalDetails`, `refusal_details(message)` (either
    namespace or a dict), `describe_refusal` (redacted, one line, explanation
    capped at `REFUSAL_EXPLANATION_MAX_CHARS` = 200);
    `digest_terminal_error(category=)` (a refusal names its category; the
    wording is unchanged without one); `SheetDigest.fallback_model` (runtime
    only); `keep_digest_read` and `note_failed_retry(model=)` name a discarded
    fallback read `; retry on <model>: …`; the real-time `_read_of` logs a
    refusal.
  - **`batch_digest.py`:** `_item_error_type` (the nested type, read once);
    `_batch_item_error_text(noun=)`; `billing_error` permanent;
    `_item_retry_params` sends a refusal to `_refusal_retry_params` (the gate,
    the target, once per sheet, the not-retried note, the log);
    `_Slot.retries` / `_Slot.last_params`, `_within_retry_budget`,
    `_count_retry`, `_fallback_model_of`; the rounds, the follow-up batch and
    the rescue check and count the budget; `_parse_item` / `_digest_from_message`
    word a fallback read with its model and log a refusal; the harvest holds a
    refusal, asks the predicate about a refusal or a permanent error
    (`_HarvestOutcome.final`, `.retry`, `.rescue_params`), and every caller
    builds its list through `rescue_params`.
  - **`critique.py`:** `outcome_from_message` passes the category and logs a
    refusal. **`batch_critique.py`:** `_outcome_from_envelope` uses
    `_batch_item_error_text(noun="item")`.
- **New tests: 67** (`tests/test_batch_refusal_recovery.py`), all passing: the
  routes, the registry and the retargeted request (9); the error types (3);
  the ladder, the reader and the log line (4); a routed refusal on both
  transports, unrouted categories, no category, the target rules, the gate
  over the hint, a fallback that refuses too, comes back worse, errors
  transiently or truncates (18); the budget (6); the selected transport (4;
  two added after the post-implementation probes, below);
  the harvest (7); the cache (2) and the WP-14.3 recorded limit (1); the
  critique's errored, canceled/expired and refused reads (12); real time (1).
  - **Classified against `origin/main`** (a worktree at `77a3f03` with its own
    `src` first on the path, then a shim giving the new names today's
    behaviour): **53 fail on behaviour**, **5 fail only on a new name** (the
    registry and retarget helpers where today's naive behaviour happens to
    match: `test_is_registered_model`,
    `test_route_categories_are_the_sdks_refusal_categories`, and the retarget
    for Opus 4.8, Sonnet 5 and Sonnet 4.6), **9 pass** (controls: the
    unchanged server-side capability, a refusal with no category, the gate
    over the hint, the default direct rescue, a harvested canceled item, an
    unfinished fallback not cached, canceled/expired critique wording).
  - **`tests/test_response_shapes.py`:** the two recorded limits flipped, each
    shown failing in its original form against the fix first:
    `test_recorded_limit_a_billing_error_is_resubmitted_like_a_transient_one`
    (`[2] == [2, 1]`) is now `test_a_billing_error_is_named_and_not_resubmitted`;
    `test_recorded_limit_a_refused_batch_item_is_not_resubmitted` (`None ==
    "refused digest …"`) is now
    `test_a_refused_batch_item_is_resubmitted_on_the_fallback_model` (two
    rounds, the second on `claude-opus-4-8`, never real time, the warm run asks
    nothing). One approved re-baseline:
    `test_a_refused_digest_fails_its_sheet_and_is_read_again`'s error now
    names `category='cyber'`. `test_every_sdk_error_type_is_classified`'s
    comment only. All three fail on behaviour against `origin/main`.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2` 2.13.1,
  PyMuPDF 1.28.2):
  - Baseline before any change: **4,887 passed, 2 skipped, 10 deselected**
    (409 s).
  - The new file and `test_response_shapes.py`: all pass; the batch,
    partial-read, terminal-outcome, critique-batch, SDK-contract,
    SDK-response and classifier files: 428 passed.
  - Full suite with the first 65 new tests, and a JUnit diff against a JUnit
    run of `origin/main` (the worktree): **4,952 passed, 2 skipped, 10
    deselected** (394 s). Of the 4,887 tests in both runs, **0 changed
    outcome**; the others are the 65 new tests and the two flipped ones
    (renamed). Full suite on the final tree (67 new): **4,954 passed, 2 skipped, 10
    deselected** (405 s), the baseline plus the 67, the same two
    environment skips.
  - **Instrumented diff** (a pytest plugin recording, per test, every
    `_item_retry_params` decision, harvest outcome, direct rescue and
    terminal-error wording; the whole suite on `origin/main` and on this
    branch): outside the new and flipped tests only two tests' events differ,
    both in wording alone (the category is named):
    `test_a_refused_digest_fails_its_sheet_and_is_read_again` (the approved
    re-baseline) and `test_a_refused_stage_is_not_complete_and_not_cached[critique]`
    (it asserts the stage status, unchanged). Every one of the 201 retry
    decisions, and every harvest and rescue, in the other tests is identical
    (their 10 refusal decisions carry no `stop_details`, so no category, and
    are not retried either way).
  - **The probes again, on the final code** (SDK 1.7.0 and 1.8.0, identical):
    m1's 164 digest cases: 116 unchanged; a cyber refusal is recovered on
    Opus 4.8 at the primary, the rounds and the harvest on both transports; an
    unrouted or category-less refusal and a permanent error the harvest reads
    are final (no longer resubmitted, or rescued at full rate under
    `RECOVERY_DIRECT`); `billing_error` is not resubmitted. One case the tests
    did not pin yet: under `RECOVERY_DIRECT` a refusal first returned by the
    follow-up batch gets its fallback in the full-rate rescue, as any item
    still failing after that batch does. It is the owner's rule ("takes any
    failed item's path"); the round-2 preview's "only if that batch cannot run
    or stalls" described a refusal from the primary. Pinned by two tests (both
    transports), and the CLAUDE.md and D-1 wording made exact. The critique:
    an errored read names its type, a refused one its category; canceled and
    expired unchanged. m2: every worst case unchanged, except a cyber refusal
    (1 -> 2 submissions).
  - `python -m compileall -q src`: clean. `python -m ruff check --select
    E9,F63,F7,F82 src tests scripts` (0.14.5): clean; F401/F811/F841 on the
    touched files: clean. (`ruff` on PATH here is 0.15.8; `python -m ruff`
    is the pinned 0.14.5.) `python scripts/scan_secrets.py`: clean (223
    files, the new file staged). Every key is built at runtime, every
    parametrized case has an id, no invisible character was added.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:** CHANGELOG (Fixed, R2); CLAUDE.md (a *Batch refusal recovery*
  passage after the batch recovery one; the harvest's hold rule; the
  refusal-fallback invariant points to the host route; the classifier's
  adopters; WP-01.5 removed from the recorded-limit owners); README (the
  refusal wording, the batch fallback, the per-sheet budget, the harvest, the
  env table); the plan (a WP-01.5 note under "New step: batch refusals (R2)",
  with the correction); DECISIONS (D-1's WP-01.5 note); PROGRESS (this entry;
  the WP-01.5, WP-01.8 (new), WP-14.3 rows; the package range; R2; Next up).
  No dependency changed.
- **Not verified:**
  - Live API behaviour (no budget, O-4): that the API never sends
    `recommended_model` on a batch refusal (documented, not observed); that
    Opus 4.8 accepts the Opus 5 digest request unchanged (the registry says
    identical shapes; WP-02.4's canary is the place); how often a real
    drawing set trips a cyber refusal.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - A cyber refusal now costs one more batch item on Opus 4.8. Its cost is
    counted (one more attempt record) at the Opus 5 label, the same price.
  - A refusal the harvest reads with no route (including `null`) is now final
    where it used to be resubmitted to the same model (m1). That follows the
    owner's gate, and it is the only place a same-model refusal retry existed.
  - The per-sheet budget equals the round ceiling, so it binds on its own only
    under `RECOVERY_DIRECT` with a low override (the follow-up batch spends the
    only retry and the rescue is skipped); pinned.
- **Found, not fixed** (noted on the owners' rows):
  - WP-14.3: a host fallback read is labelled with the requested model in the
    ledger (`test_recorded_limit_a_fallback_read_is_labelled_with_the_requested_model`).
  - WP-01.8: the harvest resubmits a truncated item at the cap it was
    submitted with (the raised cap follows only on the next round); a
    real-time refusal whose server-side fallback could not run carries a
    `recommended_model` nothing acts on.
  - Pre-existing, not this slice's: `critique.py` imports
    `DEFAULT_DIGEST_MAX_TOKENS` unused (ruff F401 outside the CI classes).
- **Merged with the 5.5 defaults** (`main` moved to `0be9ae7` while the PR was
  open: [PR #183](https://github.com/Abe-Borg/drawing-analyzer/pull/183) made
  Opus 5.5 and Sonnet 5.5 the defaults and declared `supports_refusal_fallback`
  on both). Merged, not rebased. Two text conflicts, both kept whole: the
  refusal-fallback comment in `core/api_config.py` and the refusal-fallback
  invariant in CLAUDE.md. What the merge changes for this slice:
  - **The 5.5 models declare no host route**, so on the new default a batch
    digest refused in any category fails with its category named and is not
    retried (`…; not retried: no fallback for category 'cyber' on
    claude-opus-5-5`), and the harvest holds it as final. Opus 5 keeps its
    `cyber` route. No route was added: the owner's rules named Opus 5's, and
    a route for a new model is a registry decision. **Open for the owner:**
    whether the 5.5 models get routes, and which (Anthropic documents Sonnet
    5.5's server-side fallback as `cyber` and `frontier_llm` on Sonnet 5, and
    Opus 5.5's targets as Opus 5 and Opus 4.8 per category, with
    `reasoning_extraction` never retried; the per-category split for Opus 5.5
    is not stated).
  - **Tests.** Three of this slice's failed on the merge, each from the new
    default, none from a behaviour change: `test_supports_refusal_fallback_is_unchanged`
    now names the three declaring models; the flipped
    `test_response_shapes::test_a_refused_batch_item_is_resubmitted_on_the_fallback_model`
    and the WP-14.3 recorded limit run on Opus 5 (`_run(model=)` and
    `_warm_calls(model=)`, optional, added to the shared helpers). Two new:
    `test_a_cyber_refusal_on_a_55_model_is_not_retried` (Opus 5.5 and Sonnet
    5.5), and the registry pin now lists both 5.5 models as routeless. 69 in
    the file.
  - **Docs.** README, CHANGELOG, CLAUDE.md and D-1's WP-01.5 note say the 5.5
    defaults have no route yet.
  - **Validation after the merge:** **4,993 passed, 2 skipped, 10 deselected**
    (421 s; the same two skips); compileall, ruff 0.14.5 on the CI classes
    and `scan_secrets.py` clean.
- **Next:** in queue order, WP-01.6 and WP-01.7 (Wave 2, available since
  WP-02.3 merged), then WP-01.8 (Wave 2, depends on WP-01.5). WP-11.3, WP-10.4,
  WP-06.2, WP-06.3, WP-05.3 and WP-07.3 (Wave 2) are available.

### 2026-09-29 — WP-02.3: the suite's responses are the shapes the API sends, through the real SDK ([PR #181](https://github.com/Abe-Borg/drawing-analyzer/pull/181))

- **Slice and IDs:** WP-02.3. U26 in part (the response side: nested batch
  errors, canceled/expired envelopes, `None` usage, the TTL split, `iterations`,
  `web_fetch_requests`, `output_tokens_details`, `stop_details`, fallback
  blocks, the serving model, SSE sequences with a mid-stream failure and a
  clean EOF). The batch canary stays WP-02.4's; strict release mode WP-02.5's.
  No `DECISIONS.md` contract covers test fixtures and none was opened; the
  owner's choices are recorded here as the owner's rules. No migration-register
  row: no product code, cache, key, prompt or schema moved. **WP-02 is not
  done** (02.4 and 02.5 remain). The acceptance clause this slice owns holds:
  "tests fail for missed terminal guards, realistic canceled envelopes and
  duplicated usage" (measured by injection, below).
- **Base.** `main` = `origin/main` = `85ce3e3` (WP-02.2's merge) at the start.
  Before the first push `main` had moved to `a5cb2ac` (the installer PRs
  [#179](https://github.com/Abe-Borg/drawing-analyzer/pull/179) and [#180](https://github.com/Abe-Borg/drawing-analyzer/pull/180), not remediation slices); it was merged into
  the branch (no file in common) and the affected tests re-run: 387 passed.
  Open PRs: [#174](https://github.com/Abe-Borg/drawing-analyzer/pull/174) (dependabot) and [#175](https://github.com/Abe-Borg/drawing-analyzer/pull/175) (SDK 1.8.0 support), neither a
  remediation slice, neither merged; no pin was changed. Every SDK fact below
  was measured on SDK 1.7.0 (installed; `httpx2` 2.13.1) and again in a scratch
  venv with SDK 1.8.0. Baseline **4,726 passed, 2 skipped, 10 deselected**
  (375 s), identical to WP-02.2's; the two skips are IPv6 loopback and chmod as
  root. Python 3.11.15, PyMuPDF 1.28.2, pydantic 2.13.5.
- **The request's facts, re-verified** (all held; the corrections and
  additions are marked):
  - `tests/fixtures/sdk_transport.py` served JSON and complete SSE, batches
    with every item `succeeded`, `ended` at the first retrieve, results at a
    `results_url`, `count_tokens`, uploads and deletes; no errored, canceled or
    expired item, no partial stream, no `None` counter; `message_sse` always
    ended with `message_stop`. *New:* `message_json` kept the fake's hardcoded
    `claude-opus-5`, so the stub served Opus 5 as the model for every request,
    Sonnet 5 ones included.
  - The SDK's response models: `Usage` has `cache_creation`,
    `cache_creation_input_tokens`, `cache_read_input_tokens`,
    `output_tokens_details`, `server_tool_use` (`web_search_requests`,
    `web_fetch_requests`), `service_tier`, `inference_geo`; `BetaUsage` adds
    `iterations`, `fallback_credit` and `speed`; `Message` and `BetaMessage`
    carry `stop_details` (`RefusalStopDetails`; the beta one adds
    `recommended_model`, `fallback_credit_token`, `fallback_has_prefill_claim`);
    `BetaFallbackBlock`; batch results `Succeeded`, `Errored`, `Canceled`,
    `Expired`; `ErrorObject` has nine types. **1.8.0: identical** except that
    it adds `BetaMCPToolListingBlock` to the beta content union and
    `claude-opus-5-5` to the model literal.
  - The fakes: `FakeUsage` cache fields defaulted to 0, no `iterations`,
    `cache_creation` or `output_tokens_details`; `FakeMessage.model` hardcoded,
    no `stop_details`; `FinalMessageStream` had `get_final_message()` only; the
    blocks were dataclasses and a fake echoed into a request could not be
    serialized (41 tests, reproduced exactly, below). *Also missing:*
    `container`, `citations`, `caller`, `toolset_name`, `service_tier`,
    `inference_geo`; on the stream, `current_message_snapshot`, `until_done`,
    `text_stream`, `close`, `request_id`, `response`. Nothing the fakes had was
    missing from the SDK's objects.
  - Production readers: `_dispatch_messages` returns `get_final_message()` at
    `core/api_config.py:1450`. **N27, made precise:** only a stream that ends
    before its `message_delta` returns `stop_reason=None` with the partial text;
    one missing only `message_stop` returns the complete reply, its stop reason
    included. The batch readers read the nested `error.error` tolerantly
    (`batch_critique` 456-461 keeps the message, not the type).
    `digest._message_cache_usage` is dict-tolerant;
    `core.api_config.extract_cache_usage` is attribute-only **and has no caller
    left**. `digest._message_text` is imported by 11 modules (12 with `digest`).
  - The background deletes: reproduced. The suite makes 80 upload releases (317
    file ids); 25 run on the main thread (their tests stub the seam), 55 on the
    release thread, and of those 2 (WP-02.2's idle run: 8 deletes) to 4 (this
    session, under load: 16 deletes) made their calls inside the next test:
    two batch cases in `test_digest_terminal_outcome.py`, two in
    `test_source_page_isolation.py`.
- **Measured before any code** (scratch probes and instrumented copies; nothing
  sent anywhere, every key built at runtime):
  - **s1, the readers.** Grep, then an instrumented run of the whole suite
    (every call of the shared `digest._get` accessor logged by caller, field
    and value kind; 4,726 passed with it in place):
    - no production reader of `stop_details`, `iterations`,
      `fallback_credit`, `cache_creation`, `output_tokens_details`,
      `web_fetch_requests` or `model` ran, and none exists;
    - every usage reader maps a `None` or absent counter to 0 (`int(x or 0)`:
      `_message_usage`, `_message_cache_usage`, the inline pairs in the
      digest, critique, batch digest and investigation);
      `_server_web_search_requests` maps `None` to `None` (unknown), which the
      citation check replaces with its one-per-request lower bound;
    - the suite fed a `None` cache counter in 2 tests (the N27 real-SDK tests)
      and an absent one in 8 dict-shape tests; the nested error shape and the
      SDK's `Canceled`/`Expired` results in no test (the fake error was flat:
      `FakeError` and `_Obj`, 28 reads).
  - **s2, every stage on every shape** (the gauntlet's mini set through a
    switchable shaped copy of the stub; 224 scenarios plus 14 fallback, 10
    batch-message and one investigation probe; every scenario also re-run warm
    over the same cache). What production does today is below (right) and in
    "Found, not fixed" (wrong). Nothing crashed.
    - Right: `None` counters on every stage (same totals); `iterations`,
      `fallback_credit` and `output_tokens_details` (not added to the totals);
      the nine nested error types (named `type: message`; four permanent types
      not resubmitted, four transient ones resubmitted and recovered); an
      expired item (resubmitted, recovered); a canceled item (named, not
      resubmitted); a batch polled through `in_progress` and `canceling` with
      its results reversed (COMPLETE on batch, hybrid, economy); a refusal at
      the digest, critique, verification, citation, identity and planner (not
      COMPLETE, not cached); a stream cut before `message_delta` at the digest
      and the critique (failed, not cached); a stream missing only
      `message_stop` (a complete read, as the SDK says).
  - **s3, SDK object against fake, field by field:** above. Also: the SDK's
    `Canceled`/`Expired` results have no `message` or `error` attribute at all
    (the dataclass envelope had both, as `None`); the SDK's errored result's
    `error.type` is `"error"` and the type is one level down (the fake's was
    flat); on a beta stream the accumulator sets `model` from a fallback
    block's `to.model`; neither accumulator copies `cache_creation` from a
    `message_delta`.
  - **The stream, on the real SDK** (every cut x end): a dropped connection
    raises `httpx2.RemoteProtocolError` (not an `anthropic` error); an SSE
    `error` event raises `APIStatusError`, `status_code` 200, `.type` the
    event's (never `OverloadedError`: the class follows the HTTP status); a
    clean end returns the partial read; an empty body raises the SDK's own
    `AssertionError`. `current_message_snapshot` holds the partial read in every
    raised case but the empty body.
  - **s4, SDK 1.8.0:** s2's 224 + 14 + 10 scenarios, the investigation probe,
    the control, the stream table and the field comparison: identical.
  - **s5, the serialization gap, per option** (full suite, a scratch copy of
    the fakes switched by environment variables; each fake request also built
    by the real SDK over a transport that sends nothing):
    - dataclass fakes (today): 48 fail, 41 of them "Object of type
      FakeToolUseBlock/FakeTextBlock is not JSON serializable"
      (`test_drawing_investigate.py` 18, `test_drawing_acceptance.py` 10,
      `test_run_scoped_client.py` 8, `test_drawing_qc_pipeline.py` 4,
      `test_drawing_markup_rich.py` 1); the other 7 are hand-built minimal
      requests with no `max_tokens` (WP-02.2's rule: a missing required
      argument is not checked);
    - SDK-model fakes: 7 (those same 7), 0 serialization failures;
    - without the echo check: SDK-model fakes, dataclass fakes with the missing
      fields, a `None` cache default (on either kind of fake) and a `None`
      model default each left all 4,726 unchanged.
  - **The other options:** the realistic batch default (in_progress first,
    reversed) passed all 56 contract tests, but the pipeline polls with a real
    15 s sleep and they submit 21 batches in 13 tests (~5 min unless patched);
    joining the release thread at teardown and running it inline each put all
    80 releases in their own test with no outcome change (inline takes the
    release thread out of every test).
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, seven choices, case tables per option):
  - **Round 1.**
    - **Location:** one shapes module (`tests/fixtures/sdk_responses.py`, API
      JSON) plus transport knobs on `sdk_transport.py`. Not taken: everything
      on `sdk_transport.py`; a second stub module (a second SSE emitter).
    - **Fake types:** the installed SDK's own models (`model_construct`). Not
      taken: dataclasses with the missing fields (the 41-test gap stays);
      dataclasses plus an SDK builder for new tests only.
    - **Mid-stream failure:** now, mirroring the SDK, with
      `current_message_snapshot`. Not taken: leave it to WP-01.7.
    - **Batch stub:** defaults unchanged, opt-in knobs. Not taken: a realistic
      default.
  - **Round 2.**
    - **`FakeUsage` defaults:** keep 0; `None` is an explicit shape. Not taken:
      `None` by default (0 outcomes changed either way; WP-14.4's known/unknown
      decision stays free).
    - **Pinning:** recorded-limit tests. Not taken: strict xfail; record only.
    - **Background deletes:** joined at teardown. Not taken: run inline
      everywhere; leave it.
- **What changed** (test infrastructure only; no file under `src/` moved):
  - **New `tests/fixtures/sdk_responses.py`:** `message`, `text`, `tool_use`,
    `usage` (`None` counters, `cache_split`, `server_tools`,
    `output_tokens_details`, `iterations`, `fallback_credit`), `iteration`,
    `server_tool_use`, `refusal_stop_details`, `fallback_block`,
    `splice_fallback`; `ERROR_TYPES` (from the SDK's `ErrorObject`),
    `errored`, `CANCELED`, `EXPIRED`, `PENDING`, `succeeded`, `individual`;
    `CUTS`, `ENDS`, `stream_error`, `sse_events`, `cut_events`,
    `partial_message`.
  - **`tests/fixtures/sdk_transport.py`:** `message_sse(message, cut=, end=,
    error=)` (one emitter), `sse_response` (a dropped connection raises
    `httpx2.RemoteProtocolError` after the bytes, `DROPPED`),
    `AnthropicAPIStub(stream=, batch_result=, statuses=, order=)`, a `PENDING`
    item read `canceled` after a cancel and `expired` otherwise, request counts
    from the results, `cancel_initiated_at` set after a cancel; `api_json`
    reads SDK models under the API's field names (`model_items`: an alias,
    such as a fallback block's `from`, is the wire name); `message_json` serves
    the requested model unless the reply names one. Defaults unchanged.
  - **`tests/fixtures/fake_anthropic.py`:** `FakeMessage`, `FakeUsage`,
    `FakeTextBlock`, `FakeToolUseBlock`, `FakeServerToolUse`,
    `FakeServerToolUseBlock`, `FakeWebSearchResultBlock` are constructors for
    the SDK's own models (`_sdk_model`: same keywords, same defaults, the old
    required keywords still required; `FakeServerToolUse` gains the SDK's
    required `web_fetch_requests: 0`); `FakeMessage`'s default model is not
    recorded as given. `FakeBatchResultEnvelope(type=)` returns the SDK's
    member for its type, `FakeBatchResult` a `MessageBatchIndividualResponse`,
    `batch_errored_result` the nested error. `FinalMessageStream(message,
    cut=, end=, error=, namespace=)` and `current_message_snapshot`; a stopped
    stream's read is the namespace's own type (`ParsedMessage` or
    `ParsedBetaMessage`), which `checked_entry` names for a stream it returns.
    `_to_dict` reads SDK models under the API's field names.
  - **`tests/conftest.py`:** the autouse `background_release_joined`.
- **New tests: 154**, all passing (133 in the first push, 21 from the Codex
  review, below).
  - **`tests/test_sdk_responses.py` (99):** the tripwire (the nine error
    types; the fields the fixtures build; the four batch result types); every
    shape parsed by the SDK's own model (9 errored, canceled, expired, usage,
    `stop_details` on both namespaces, the fallback splice); an SDK model
    serialized under the API's field names, and through the stub (2); the real
    SDK on every cut x end (16) and `FinalMessageStream` against it on both
    namespaces, reached through the checked entry points, read types included
    (32), and the namespace rules (3); the snapshot
    rules; the beta accumulator's serving model; every fake is the SDK's own
    model (8) and every envelope its member (4); the nested fake error; a fake
    reply echoed into a request is sent; value equality and assignment kept;
    the stub's knobs (serving model, stream, envelopes, `PENDING`, statuses,
    no results before the end, order x2, defaults unchanged); the release
    thread joined (an inner pytest session).
  - **`tests/test_response_shapes.py` (55):** the s2 matrix as tests: 34
    assert what production gets right, 21 are recorded limits (below).
  - **Classified against `origin/main`** (a worktree at `85ce3e3` with the
    new files; then a shim giving the new names today's behaviour: the stub
    ignoring its knobs, `message_sse`/`sse_response` complete,
    `FinalMessageStream` ignoring `cut`/`end` with a snapshot of the message,
    dataclass fakes, no join):
    - **70 fail on behaviour:** every fixture behaviour (the SDK on each cut x
      end 14, the fakes as SDK models 8, envelopes 4, the stub's knobs, the
      nested fake error, the echo, the join), and every production test that
      needs a shape the old stub could not serve (batch envelopes, streams, the
      status sequence);
    - **40 fail only on a new name:** the whole of `test_sdk_responses.py`
      fails to import without the shim; with it these pass, because both sides
      of the comparison fall back to today's complete stream
      (`FinalMessageStream` against the SDK 16, the builder parses, the
      tripwire), plus the stream missing only `message_stop`;
    - **23 pass:** they pin production's current behaviour with shapes the old
      stub could already serve as JSON (the refusals, the usage shapes, the
      fallback splices and the recorded limits built on them). Three recorded
      limits passed vacuously in the first version (a complete stream also
      satisfied them); they now also assert the cut reply's 0 output tokens,
      and fail on behaviour.
- **The WP-02 acceptance clause this slice owns, measured by injection**
  (production regressions switched by an environment variable in two scratch
  worktrees: `origin/main`'s tests, and this branch's; the 56 test files that
  exercise the pipeline, the batch path or the fakes, plus the two new ones;
  each control passed everything):

  | Injected regression | Clause | today | with WP-02.3 |
  |---|---|---|---|
  | J1: a stop reason of `None` read as finished (`classify_stop_reason`) | missed terminal guard | 36 | 39 (+3 new: the digest cut after text and after content, the critique cut after content, through the real SDK) |
  | J2: a `canceled` or `expired` item parsed as succeeded (`_parse_item`) | missed terminal guard, realistic canceled envelope | 0 | 1 (the canceled item's test) |
  | J3: the nested batch error read as if flat (the three batch readers) | realistic envelope | 0 | 8 (4 new: the permanent types are resubmitted; 4 existing `test_drawing_batch.py` tests, now that `batch_errored_result` is nested) |
  | J4: a reader that assumes every envelope carries `error` (`_batch_item_error_text`, `batch_critique`) | realistic canceled envelope | 0 | 4 (canceled and expired, digest and critique; the SDK's own `Canceled`/`Expired` results have no such attribute) |
  | J5: `usage.iterations` added to the top-level totals (`_message_usage`) | duplicated usage | 0 | 2 (fast and economy) |
  | J6: a batch attempt recorded twice when a read is folded in | duplicated usage | 17 | 18 (+1: the recovered item's record) |

  Each control (no injection) passed everything: 2,864 on `origin/main`'s
  tests, 2,997 on this branch's. J2 is caught only through the error text (the
  expired item is still resubmitted and recovers), and J1 mostly by WP-01.2's
  and WP-01.4's own tests; the envelope readers (J3, J4) and the per-iteration
  usage (J5) were caught by nothing before.

- **Fixture effects:** the full suite on the fixtures alone (before the new
  production tests): all 4,726 existing tests pass unchanged. No existing test
  file was edited; no assertion moved.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2` 2.13.1,
  PyMuPDF 1.28.2):

  - Baseline before any change: **4,726 passed, 2 skipped, 10 deselected**
    (375 s).
  - The two new files: 133 passed. Every touched file passes.
  - Full suite, final tree: **4,859 passed, 2 skipped, 10 deselected** (428 s),
    the baseline plus the 133 new tests, the same two environment skips.
    Diffed test by test against the baseline: all 4,728 existing results
    identical.
  - `python -m compileall -q src`: clean.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (0.14.5):
    clean. F401/F811/F841 over the new and touched fixture and test files:
    clean.
  - `python scripts/scan_secrets.py`: clean (221 tracked files, the new files
    staged). Every key is built at runtime, every parametrized case has an id,
    and the new code has no non-ASCII character.
  - The probes again, on the final tree: s3 finds no data field on the SDK's
    objects that the fakes lack, and a fake reply echoed into a request is
    sent; the stream fake still lacks `close`, `get_final_text`, `request_id`,
    `response`, `text_stream`, `until_done` and `workspace_id` (production
    uses none). s2's 224 scenarios: identical to the first run (production
    did not change).
  - The browser suite was not run: no report or JavaScript changed.

- **Codex review** (two P2 findings on `fa905d4`; both reproduced, both fixed,
  tests first; fixture-only, no production test changed outcome):
  - **A stopped `FinalMessageStream` read as `BetaMessage` on either
    namespace.** The real SDK's stream reads as `ParsedMessage` on the plain
    namespace and `ParsedBetaMessage` on the beta one (blocks likewise:
    `ParsedTextBlock`, `ParsedBetaTextBlock`), so a type or `isinstance` check
    that tells the namespaces apart could pass against the fake and fail in
    production. Now `FinalMessageStream(namespace=)` names it, `checked_entry`
    names it for a stream it returns (the outermost entry's, since a beta
    entry may forward to a plain one), and a stream reached through none reads
    as plain. A complete stream still returns the message it was given.
  - **`api_json` and `_to_dict` wrote Python field names.** The SDK's fallback
    block names its `from` field `from_` (a Python keyword) with the alias
    `from`; a route that returned a parsed `BetaMessage` sent `from_`, which the
    SDK read as no `from` at all (`content[1].from_` was `None`). One walk now
    (`sdk_transport.model_items`) writes each field under its alias when it has
    one; it is the only aliased field in any module under `anthropic.types`
    today (measured), and the round-trip test holds the rule for any other.
  - Tests: the mirror test now reaches the fake through the checked entry
    points on both namespaces and compares the read's type and its blocks'
    (16 → 32); the namespace rules (3); the alias, and through the stub (2).
    Against `fa905d4`: 27 fail on behaviour (the 24 stopped-stream mirror
    cases on both namespaces, 12 of them the existing ones strengthened; the
    stream built outside an entry point; the two alias tests), 2 fail first on
    the new `namespace=` keyword, and 8 pass (the complete stream and the three
    `empty` cuts on each namespace: no read to type).
  - Validation on the final tree (the merged base): full suite **4,887
    passed, 2 skipped, 10 deselected** (437 s): 4,859 above, plus the 7
    installer-license tests from `main`, plus these 21; the same two
    environment skips. ruff 0.14.5 (E9/F63/F7/F82; F401/F811/F841 on the
    touched files), `compileall` and `scan_secrets.py` (222 files) clean.

- **Docs:**
  - **CHANGELOG** (Changed, test infrastructure): U26 in part.
  - **CLAUDE.md:** a *Response-side fidelity* passage after the strict-fakes
    one; N27's wording made precise (before `message_delta`, not "without
    `message_stop`"); `extract_cache_usage` noted as having no caller.
  - **The plan:** a WP-02.3 note under WP-02 steps 3-5 and Step 5's N27 made
    precise; WP-14 Step 1's accumulator claim made precise (beta vs plain,
    `model` from a fallback block, no `cache_creation` from `message_delta`);
    WP-14's "needs WP-02.3's fakes" list annotated with what is now available;
    WP-01's interruption note likewise.
  - **PROGRESS:** this entry; the WP-02.3 and U26 rows; notes on the WP-01.5,
    WP-01.6, WP-01.7, WP-06.3, WP-13.4, WP-14.1, WP-14.2, WP-14.3 and WP-14.6
    rows; the Next-up line.
  - README: no user-visible change. No dependency changed (`pydantic`, which
    the fixtures now import, is already pinned as the SDK's dependency).
- **Not verified:**
  - Live API behaviour (no budget, O-4). In particular: what the API sends for
    the cache counters on an ordinary reply (0 or `null`; the fakes keep 0 by
    the owner's rule); that a canceled batch's unfinished items read `canceled`
    (the stub's `PENDING` rule follows the documented behaviour); whether the
    API accepts a `fallback` block echoed in an assistant turn (the SDK
    serializes it; WP-13.4 decides whether to echo it). WP-02.4's canary is the
    place for the batch ones.
  - Windows is covered by this PR's CI (`gates-windows`).
- **Risks and residual gaps:**
  - The fakes now follow the installed SDK's models: an SDK that renames a
    field moves the fakes with it, and the tripwire (the error types, the
    fields the fixtures build, the result types) fails for the facts pinned.
  - The fakes are built without validation (the owner's rule), so a test can
    still build a shape the API never sends; the new fidelity tests hold the
    shared builders, not every hand-built fake, to the SDK.
  - The production tests run the mini set (two sheets); the sharded cross-QC
    path and the stalled-batch harvest are exercised by the older fakes.
  - Suite time: +154 tests, about 60 s (the production tests run the whole
    stack, about 1 s each).
- **Found, not fixed** (each pinned by a recorded-limit test that the owner
  flips, and noted on the owner's row):
  - WP-01.6: synthesis and the focus report keep and cache a refusal (synthesis
    COMPLETE) and a stream cut before `message_delta`; the planner caches a cut
    plan; U2's `"\n"` join across a fallback block loses the digest's finding
    or splits a word of its prose, and the read is cached; a split critique
    read fails although good.
  - WP-01.7: a mid-stream `error` event or dropped connection is not retried by
    the digest (`_is_transient_error` knows neither class), and the attempt's
    usage is lost (0/0; synthesis and focus leave no record; the planner a
    0-token one).
  - WP-14.2: the `cache_creation` split is priced at one TTL rate.
  - WP-14.3 / WP-14.6: the serving model and `web_fetch_requests` are not read.
  - WP-13.4: N20 confirmed (the pre-fallback `tool_use` executed and the
    fallback block echoed).
  - WP-06.3: cross-QC reads a refusal with text as "no parseable findings
    object".
  - WP-14.1: R3's terminal path (a recovered item's failed attempt has no
    record).
  - WP-01.5: R2 (a refused batch item is not retried; `stop_details` unread),
    and `billing_error` is resubmitted like a transient error; a failed batch
    critique read is never retried.
  - The fixture defect found (the stub served `claude-opus-5` for every
    request) is fixed here, since it is this slice's fixture.
- **Next:** in queue order WP-01.5 (Wave 2, available). Once this PR merges,
  WP-01.6, WP-01.7, WP-13.4, WP-14.2, WP-14.3 and WP-02.4 are unblocked; each
  starts from its recorded-limit tests. WP-11.3, WP-10.4, WP-06.2, WP-06.3,
  WP-05.3 and WP-07.3 (Wave 2) are available now.

### 2026-09-29 — WP-02.2: the fakes refuse what the SDK refuses, and production's requests go through the real SDK ([PR #178](https://github.com/Abe-Borg/drawing-analyzer/pull/178))

- **Slice and IDs:** WP-02.2. U26 in part (the request side: strict fakes and
  real-SDK contract tests). The response side (nested batch errors,
  canceled/expired envelopes, `None` usage, SSE sequences) stays WP-02.3's; the
  batch canary WP-02.4's; strict release mode WP-02.5's. No `DECISIONS.md`
  contract covers test fakes and none was opened (as the request asked); the
  owner's choices are recorded here as the owner's rules. D-1 was not touched.
  No migration-register row: no product code, cache, key, prompt or schema
  moved. **WP-02 is not done** (02.3-02.5 remain). Of its acceptance, the clause
  this slice owns holds: "tests fail for invalid request namespaces" (measured
  below by injection); "missed terminal guards", canceled envelopes and
  duplicated usage are WP-02.3's.
- **Base.** `main` = `origin/main` = `6fcaa28`; no drift at the start or
  before the push. Baseline **4,545 passed, 2 skipped, 10 deselected** (429 s,
  with probes running beside it), identical to the WP-16.2 handoff; the two
  skips are IPv6 loopback and chmod as root. Python 3.11.15, PyMuPDF 1.28.2,
  SDK 1.7.0. `pip install -e ".[dev,browsertest]"` resolves `httpx2` 2.13.1
  (the pins say 2.13.0; CI installs the same way), so every SDK fact was also
  measured in a scratch venv with the locked pins (1.7.0 + `httpx2` 2.13.0) and
  in one with SDK 1.8.0 (#174/#175 are still open; no pin was changed).
- **Reproduced first** (scratch probes: fake keys built at runtime,
  `httpx2.MockTransport`, nothing sent). Every SDK fact in the request held,
  identically on 1.7.0, the locked pins and 1.8.0:
  - `client.messages.create(betas=)`, `.create(fallbacks=)`,
    `client.messages.stream(betas=)`/`(fallbacks=)` and
    `client.messages.batches.create(betas=)` raise `TypeError` with no request
    sent; so do `messages.count_tokens(betas=)` and `files.upload(betas=)`.
  - `client.beta.messages.create/stream(betas=, fallbacks=)` send to
    `/v1/messages?beta=true` with the `anthropic-beta` header;
    `client.beta.messages.batches.create(betas=)` sends
    `x-1,message-batches-2024-09-24`. A beta call with `fallbacks` and no
    `betas` is sent with no header (production always pairs them).
  - Non-streaming `create`: 21,333 is the largest `max_tokens` sent, 21,334 the
    first refused (`ValueError`, no request), for all five registered models on
    both namespaces. The rule is `anthropic/_base_client.py:762`
    `BaseClient._calculate_nonstreaming_timeout` (refuse when
    `3600*n/128000 > 600`, or above `_constants.py:14`
    `MODEL_NONSTREAMING_TOKENS`, which lists only old Opus 4 ids at 8,192).
  - **New:** the SDK skips that check when a call passes its own `timeout`, when
    the client was built with one, or through `with_options(timeout=)`.
    Production's client keeps the default (now pinned).
  - **New:** the SDK does not check batch items: an item carrying `betas` is
    sent, and so is one at 64,000 `max_tokens`. The plain batch item type
    (`MessageCreateParamsNonStreaming`) names exactly the plain `create`
    parameters.
  - A plain batch whose items reference file ids, and `files.upload`, carry no
    `anthropic-beta` header.
  - The SDK methods' signatures (names and kinds) are identical on 1.7.0 and
    1.8.0. Plain `create` takes no `temperature`/`top_p`/`top_k`; production
    sends none.
- **Facts confirmed, not assumed.**
  - **Production routing, read and measured:** `apply_refusal_fallback` (1380),
    `messages_namespace` (1408), `call_with_refusal_fallback` (1417) and
    `_dispatch_messages` (1445) in `core/api_config.py`. The non-streaming
    `create` sites are the six named (citation 877, cross-QC 1260, prose
    harvest 1095, identity 557, verify 709 and 1494). The streamed ones are
    `digest.stream_message` (809, call 833) and the investigation (322, its own
    `call_with_refusal_fallback(..., method="stream")`; 333, `stream_message`).
    The batch submits are `batch_digest` 1302, 1588, 2062 and `batch_critique`
    382, all `requests=` only. Files: `file_upload.py` 393, no beta header.
  - **The lenient fakes, counted:**
    - 16 sites in 7 files popped or stripped `betas`/`fallbacks` (15 `pop`
      calls, plus `test_drawing_batch.py:79`'s comparison helper);
    - 13 batch-create fakes accepted `betas` (the plan said seven: those are
      `test_drawing_batch.py`'s; six more are in four other files), and
      `_messages_stream(betas=)` at `test_drawing_batch.py:224`;
    - the helpers are used by 34 test files, plus the gauntlet fixture and the
      benchmark script;
    - "`.beta.messages` the same object as `.messages`": no fake shares the
      object. 9 fake client classes shared the *methods* (the same function on
      both namespaces), and 81 (by module and class) went through
      `_BetaMessagesProxy`. Either way a call
      on the wrong namespace was recorded as if right.
  - **s1, the instrumented suite** (a scratch copy of `origin/main`: same-line
    substitutions at every production call into a client, plus appended hooks,
    behind `WP022_LOG`, logged with the test id and per-hook run counts):
    - 2,370 production dispatches in 763 tests (40 files), none the real SDK
      would refuse (verdict from the installed SDK's signatures and cap):
      - no plain call carried `betas` or `fallbacks`;
      - no non-streaming `create` was above the cap (518 plain and 311 beta,
        largest 16,000);
      - 1,384 of the 1,541 streams were above it.
    - All 254 `batches.create` calls passed only `requests`, and no item carried
      `betas`/`fallbacks` (items at 16,000-128,000). All 1,225 uploads passed
      only `file`.
    - Every pop site ran (e.g. `test_source_page_isolation:157` 233 times,
      `test_critique_terminal_outcome:594` 113): "no strict failure" was a
      measured result, not a silent hook.
    - So a strict fake would fail no test for a production reason. Its only
      candidates were tests that call a fake wrongly: one test builds a rescue
      request with no `max_tokens`
      (`test_drawing_batch::test_rescue_stops_instead_of_sleeping_past_the_budget`),
      refused only if a missing required argument is checked (not taken).
    - 8 `files.delete` calls ran from the batch release thread after their test
      had ended (WP-02.3 note).
  - **s2, production builders through the real SDK** (the gauntlet's mini-set
    script behind a MockTransport "API": JSON or SSE for `/v1/messages`,
    batches, files; stages identified by system prompt):
    - 21 scenarios, 475 requests, **zero refused**, every stage COMPLETE:
      - Fast, Batch, Hybrid and Economy;
      - the refusal fallback on, off by the environment, and latched off by a
        400 mid-run;
      - the task budget, strict tools and structured outputs each rejected by a
        400;
      - structured outputs on for critique, harvest and verify, on real time
        and batch;
      - Files API 404 (inline fallback);
      - every stage on each of Sonnet 5, Opus 4.8, Sonnet 4.6 and Haiku 4.5, on
        Fast and Economy;
      - verification on Opus 5.
    - Opus 5 calls go to `?beta=true` with `server-side-fallback-2026-07-01`.
      The investigation adds `task-budgets-2026-03-13` and sends strict tools
      (not on Sonnet 4.6, which does not declare them).
    - Every latch flip re-issued a request the SDK sent. Batch submits and
      uploads carry no beta header.
  - **s3, caps:** every stage's resolved `max_tokens` through the production
    helpers, per model, against the SDK's own rule:
    - the non-streaming sites ask for at most 16,000 on every model
      (cross-QC 16,000; citation, harvest, identity, verification 8,000);
    - every site above the cap streams: digest and critique 64,000, the
      digest's raised-cap retry 128,000 (64,000 on Haiku and an unknown id),
      planner, synthesis and focus 32,000;
    - `review_max_tokens`/`cross_check_max_tokens` (128,000/96,000) have no
      caller;
    - the investigation is 16,000, streamed, and under the cap either way.
  - **s4, SDK 1.8.0:** every probe above gave the same results, and s2 sent the
    same 475 requests. Three Economy scenarios differed in order only, with the
    same multiset.
  - **Cost per fake call** on a 139 KB digest body: a signature check 0.5 µs,
    the private cap helper 1.0 µs, a request built by the real SDK 5.4 ms.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, eight choices; the per-builder assertions delegated to the session).
  Measured first:
  - a switchable scratch implementation on top of the instrumented copy, one
    environment knob per choice (rule, cap, scope, split), with five injected
    production regressions (`WP022_REGRESS`):
    - G1: critique `stream_message` → `create`;
    - G2: every streamed stage → `create`;
    - G3: `messages_namespace` always plain;
    - G4: `temperature` added to the verification request;
    - G5: `betas` on the plain batch submit;
  - run over the 40 files s1 names (2,209 tests), 39 runs in all, and diffed
    test by test.

  Without a regression, every option left all 2,208 outcomes unchanged, except
  two: "real SDK per call" (41 false failures, the fake response objects above)
  and "full bind" (1). The events differed only in which test a background
  delete landed in. Tests that fail when the regression is injected:

  | Regression | today | signature (chosen) | deny list | shared fixtures only | no split | real SDK per call |
  |---|---|---|---|---|---|---|
  | G1 critique → `create` | 4 (incidental) | 115 | — | 94 | 115 | 101* |
  | G2 every stream → `create` | 42 | 406 | — | 332 | 406 | 383* |
  | G3 betas on plain | 11 | 520 | 520 | 406 | 406 | 479* |
  | G4 unknown keyword | 0 | 77 | 0 | — | — | 57* |
  | G5 betas on a plain batch | 19 | 169 | 169 | — | — | — |

  \* beyond the 41 it already fails. A cap-only variant caught G1/G2 like the
  chosen one and G3-G5 like today; a rule-only variant the reverse. The 4
  failing today under G1 are four batch-critique tests whose fake has no beta
  `create`; the 11 under G3 are the tests that keep the namespaces apart.

  A unit-level SDK-change table: each simulated change was applied to the
  installed SDK, and each cap mechanism was asked the same question as the
  patched SDK.
  - A raised cap, a new per-model entry and a renamed private helper: deriving
    through the public `create` and asking the SDK per call followed all
    three.
  - The private helper followed the first two and raised `AttributeError` in
    every fake `create` on the rename.
  - The reimplemented formula wrongly refused 21,334-30,000 once the cap was
    raised.
  - A deny list let an unknown keyword through.

  The rules, and what was not taken:
  - **Round 1.**
    - **Rule:** the installed SDK method's signature, unknown keywords only.
      Not taken: the full bind, which re-baselines the one test above; a
      hand-written deny list, which misses G4 (0 of 77) and must be edited when
      the SDK moves a parameter; the real SDK per call, with 41 false failures
      and 5.4 ms a call.
    - **Cap:** derived through the SDK's public `create`, once per model. Not
      taken: calling the private helper (it fails loudly on a rename); the
      formula (it goes stale; the plan forbids a literal).
    - **Scope:** every fake production reaches. Not taken: the shared fixtures
      and the 13 batch fakes only (G2 332, G3 406).
    - **Split:** separate plain and beta entry points, each checked as its own
      namespace. Not taken: shared functions checked against the union (G3
      406).
  - **Round 2.**
    - **Location:** a new `tests/test_sdk_contract.py` over a shared stub,
      `tests/fixtures/sdk_transport.py`. Not taken: beside each module.
    - **Assertions:** delegated. The session took all four groups offered:
      namespace and header; the non-streaming cap, per request and as a
      per-model table; no beta on batches and uploads, with items within the
      SDK's item type; latch flips and structured outputs. Each covers a
      different refusal class.
    - **Pin:** derive from the installed SDK, with a tripwire over the measured
      facts. Not taken: an exact `anthropic==1.7.0` pin (#174/#175 would go
      red); no tripwire.
    - **Batch items:** checked by the contract tests only. Not taken: the fakes
      too (they would refuse more than the SDK); neither.
- **What changed** (test infrastructure only; no file under `src/` moved):
  - **`tests/fixtures/fake_anthropic.py`:**
    - `SDK_KEYWORDS` (the installed SDK's signatures);
    - `sdk_nonstreaming_limit(model)`, a bisection of the SDK's public
      `create` over a transport that sends nothing, cached per model, which
      also keeps the SDK's refusal message;
    - `check_sdk_request(namespace, method, kwargs)`, which raises the SDK's
      `TypeError` or `ValueError` and skips the cap when the call passes
      `timeout`, as the SDK does;
    - `checked_entry`, the entry-point wrapper (named `_checked` and private
      in the first push; public, with an `sdk_checked` marker, since review
      round 1), with a `contextvars` marker so a beta call forwarded to a
      shared `create` is not re-checked as plain;
    - `checked_batch_create` and `sdk_namespaces`;
    - `StreamingMessagesMixin` checks its `stream` and wraps a subclass's own
      `create` at class definition (`__init_subclass__`); `add_stream` checks
      both; `_BetaMessagesProxy` checks as beta, then drops `betas` (the
      header) and keeps `fallbacks` (the body). The streaming-shim comment
      names 21,333.
  - **The 7 test-local fakes** (`test_drawing_batch`, `test_drawing_batch_critique`,
    `test_source_page_isolation` (`_Pipe`, reused by
    `test_digest_phase_containment` and `test_run_scoped_client`),
    `test_digest_terminal_outcome`, `test_digest_partial_reads` ×2,
    `test_critique_terminal_outcome`):
    - they build their namespaces with `sdk_namespaces`;
    - the 16 pops are gone;
    - `_messages_stream` takes no `betas` (its record lost the unasserted
      `betas` key);
    - `_without_fallback_keys` drops only `fallbacks`;
    - the 13 batch fakes are `@checked_batch_create` with `requests` only (two
      `create_calls` records lost their unasserted `betas` key);
    - a stale comment at `test_drawing_batch.py:1263` claimed the rescue
      carries "the Files-API beta"; measured, it does not, and it is corrected.
  - **New `tests/fixtures/sdk_transport.py`:** `AnthropicAPIStub(route,
    reject=)`, the in-process API for the real SDK (see CLAUDE.md), and
    `error_400`.
- **Review round 1 (Codex, P2 on `tests/test_strict_fakes.py`): fixed in this
  PR.** The finding: a fake whose `messages` is a plain class with
  `create(**kwargs)`, not the mixin, passed both scans, so "every fake
  production reaches" did not hold (its example: the citation fake in
  `tests/test_drawing_markup_rich.py`).
  - **Measured on the PR's tree** (every production dispatch and batch submit,
    classified by the entry it reached): of 3,167 calls, 2,686 reached a
    checked fake, 458 the real SDK (the contract tests, the N27 tests) and 2 a
    deliberately missing beta namespace. **21 reached an unchecked entry**, in
    five fakes:
    - `test_refusal_fallback._FakeClient` (8);
    - the two beta-namespace wrappers in `test_drawing_investigate` (8; they
      forward to the checked proxy after their own logic);
    - the citation fake Codex named (3);
    - the benchmark script's `OfflineClient` (1);
    - this PR's own deliberate batch wrapper (1).
    No batch fake was unchecked.
  - **Fix, within the owner's scope rule** (every fake production reaches goes
    through the one check):
    - the entry wrapper is public, `fake_anthropic.checked_entry(namespace,
      method, handler, *, header=False)`, and marks each entry
      `sdk_checked = True`;
    - the five fakes route through it: `checked_entry` for the hand-built
      namespaces (the refusal-fallback fake keeps recording `betas`; the
      investigation wrappers still decide on them), `StreamingMessagesMixin`
      for the citation fake and the benchmark's `_Msgs`;
    - **an autouse guard**, `sdk_checked_guard` in `tests/conftest.py`, wraps
      `core.api_config._dispatch_messages`. It records any Messages entry
      production reaches that is neither checked nor the real SDK's, and
      fails the test at teardown. It records because a stage swallows its own
      exceptions. The list is the fixture's value, so a test doing it on
      purpose clears it, and a missing namespace stays production's
      `AttributeError`;
    - a scan: every batch-create fake (a function with a keyword-only
      `requests`) in the tests and the scripts is `@checked_batch_create`.
  - **New tests (4):**
    - the batch scan (on `origin/main` it fails on behaviour: 14 undecorated
      fakes);
    - the guard records the shape Codex found (a `**kwargs` fake taking
      `temperature`);
    - it passes a checked fake and the real SDK;
    - it leaves a missing namespace to production.
    The three guard tests need the new fixture.
  - **Validation:** the full suite, guard active in every test: **4,726
    passed, 2 skipped, 10 deselected** (378 s), the 4,722 before plus the 4
    new; no test tripped the guard. `compileall`, ruff E9/F63/F7/F82 and the
    secret scan clean. F401/F841 over the newly touched files: five
    pre-existing findings (`investigation_tools`, `order`, `executed` in
    `test_drawing_investigate.py`; `Path` in `test_drawing_markup_rich.py`;
    `n_sources` in `scripts/benchmark_drawing_analyzer.py`), all on
    `origin/main` already (WP-22.5).
- **Contracts decided:** none in `DECISIONS.md` (the owner's rules above).
- **Cache/schema effects: none.** No product code changed.
- **Re-baselined tests: none.** No existing test changed outcome (instrumented,
  below). The edits to existing test files change fakes, not assertions.
- **New tests: 177** in the first push (181 with review round 1's 4, above).
  - **`tests/test_strict_fakes.py` (121, then 125):**
    - every kind of fake entry point (the mixin's create and stream, bound and
      unbound; `add_stream`; the beta proxy; the split plain and beta entries)
      × 9 cases, each against the real SDK computed live over a transport
      that sends nothing (99, `ids=`), with the same exception type and
      message. The cases: legal; `betas`; `fallbacks`; both; `temperature`;
      at the cap; one above; 64,000; 64,000 with its own `timeout`;
    - a non-vacuity check on that table;
    - the cap per model (the five registered and an unknown id) against the
      test's own bisection, and the SDK's own refusal message;
    - `SDK_KEYWORDS` equal to the SDK's signatures;
    - a batch `create` with `betas` refused with the SDK's message;
    - each streamed stage regressed to `create` fails in the fakes (digest,
      critique, review plan, synthesis, focus), with an unregressed control;
    - `betas` on the plain namespace, an unknown keyword, and `betas` on a
      plain batch submit each fail in the fakes;
    - two structural scans: no test file pops `betas`/`fallbacks` or defines a
      `betas` parameter; a non-vacuity check on them.
  - **`tests/test_sdk_contract.py` (56):**
    - the tripwire: five plain-namespace refusals; the beta namespace's
      header and body; 21,333/21,334 for the five models on both namespaces
      (10); no beta on batches and uploads; the production client's default
      timeout;
    - every stage × 4 transports × fallback on/off (8);
    - every stage on each registered model × Fast/Economy (10);
    - each latch flip re-issued and sent (4);
    - structured outputs on their namespaces;
    - the per-model cap table (6), and the table against what the stages
      send;
    - the raised-cap retries on Fast and Batch (2);
    - `count_tokens`;
    - each streamed stage regressed to `create` refused by the real SDK before
      any request (5).

  Classified against a copy of `origin/main` from `--junitxml`, with a shim
  putting today's behaviour behind the new names (a `check_sdk_request` that
  refuses nothing; an `sdk_namespaces` that shares one unchecked function
  across both namespaces):
  - **54 fail on behaviour**, all in `test_strict_fakes.py`: the fakes accept
    what the SDK refuses (42 table rows, the cap message, the batch message);
    the five regressed stages and the three injected regressions stay green;
    the scans find 13 pops (the other two were `fake_anthropic.py`'s own) and
    14 `betas` parameters;
  - **fail only on a new name:** 29 strict-fake tests (the split entries' rows
    where both sides agree; the cap-per-model tests; the keywords test), and
    all 56 contract tests, which import `sdk_nonstreaming_limit`;
  - **pass**: 38 strict-fake tests (the rows today's fakes already get right,
    and the controls), and, with the shim, all 56 contract tests. They pin
    production's current, correct requests, which is the point: nothing in
    production had to change.
- **Fixture effects**, the instrumented fixed tree (the production hooks only;
  the test-side pop sites no longer exist) diffed test by test against the base
  run:
  - **Outcomes:** all 4,547 existing tests unchanged; 177 added, all passing.
  - **Production calls:** identical per test in operation, SDK verdict and cap
    for every existing test. What moved: 161 tests now reach a split fake where
    they reached a shared-method one (the classification column only). One
    test's count (`test_drawing_verify::test_verify_concurrent_findings_never_park_a_plain_verdict_under_a_structured_key`,
    6 → 4) varies from 4 to 6 across six reruns of the unmodified base. The
    new contract tests add 78 deletes, and background deletes land in a
    neighbouring test's window as on the base.
- **Probes on the fix:** s2 re-run over the fixed tree: the same 475 requests
  over the 21 scenarios, 0 differences. The SDK-fact probes, s3 and s4 read
  only the SDK and unchanged product code.
- **Validation** (this container: Python 3.11.15, SDK 1.7.0, `httpx2` 2.13.1,
  PyMuPDF 1.28.2):
  - Baseline before any change: **4,545 passed, 2 skipped, 10 deselected**.
  - The two new files: 177 passed. Every touched test file passes.
  - Full suite: **4,722 passed, 2 skipped, 10 deselected** (407 s), the
    baseline plus the 177 new tests, the same two environment skips.
    Instrumented run of the fix: the same counts (444 s). After review round
    1: **4,726 passed, 2 skipped, 10 deselected** (378 s).
  - `python -m compileall -q src`: clean.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` (0.14.5): clean.
    F401/F811/F841 over the touched files: two pre-existing F401s
    (`BetaClientMixin` imported unused in `test_drawing_batch.py` and
    `test_drawing_batch_critique.py`, on `origin/main` already; WP-22.5), none
    in the new code.
  - `python scripts/scan_secrets.py`: clean (218 tracked files, the new files
    staged). Every key is built at runtime, and every parametrized case has an
    id.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:**
  - **CHANGELOG** (Changed, test infrastructure): U26 in part.
  - **CLAUDE.md:** a new passage after the hermetic guard's (*Strict fakes and
    the SDK contract*), and the streaming invariant corrected: "above ~21k" →
    "above 21,333", with the measurement, the SDK's timeout escape, the
    non-streaming sites' largest cap (16,000) and how CI now catches a
    regression.
  - **The plan:** WP-02 Step 2's "bisects to 21,334" and Step 3's "the seven"
    corrected; a WP-02.2 note under the Step 1-3 notes.
  - **PROGRESS:** this entry; the WP-02.2 row; the U26 row; notes on WP-02.3
    and WP-06.3; the Next-up line.
  - README: no user-visible change.
- **Not verified:**
  - Live API behaviour (no budget, O-4; this slice makes no call). In
    particular:
    - that the API accepts `file_id` references with no `files-api-*` beta
      header (production sends none; measured on the SDK only);
    - that it rejects `fallbacks` inside a batch item (CLAUDE.md says so; the
      contract tests keep items within the SDK's item type).
    WP-02.4's canary is the place.
  - Windows is covered by this PR's CI (`gates-windows` runs the hermetic suite,
    the new tests included).
- **Risks and residual gaps:**
  - The fakes now follow the installed SDK: an SDK upgrade that drops or adds a
    keyword moves every fake with it. The tripwire tests fail if a measured
    fact moves: the refusals, 21,333, the beta header, no header on batches.
  - A missing required argument is not checked (the owner's rule), so a
    hand-built minimal request stays legal in the fakes; the real SDK would
    refuse it.
  - A fake subclass whose `create` is a `classmethod` is not wrapped by the
    mixin (none exists).
  - The contract tests run the mini set only (two sheets). The sharded cross-QC
    path (over 40 sheets), the whole direct-call rescue and the `pause_turn`
    resumes of the citation check are exercised by the strict fakes, not
    through the real SDK.
- **Found, not fixed:**
  - The fake response objects (`FakeToolUseBlock` etc.) are not SDK models;
    echoed into the next request they cannot be serialized by the real SDK
    (WP-02.3 note).
  - 8 background `files.delete` calls outlive their test (WP-02.3 note).
  - A cross-QC raised-cap retry above 21,333 must stream (WP-06.3 note; the
    contract tests will fail until the cap table's `cross_qc` row streams).
- **Next:** WP-02.3 (Wave 2), once this PR merges; then WP-01.6, WP-01.7,
  WP-13.4, WP-14.2 and WP-14.3 unblock. WP-01.5, WP-11.3, WP-10.4, WP-06.2,
  WP-06.3, WP-05.3 and WP-07.3 (Wave 2) are available now.

### 2026-09-29 — WP-16.2: a GUI run keeps the key it started with, and the key never goes to `os.environ` ([PR #177](https://github.com/Abe-Borg/drawing-analyzer/pull/177))

- **Slice and IDs:** WP-16.2. G2 (implemented+validated). No `DECISIONS.md`
  contract covers credentials, and none was opened (as the request asked); the
  owner's choices are recorded here as the owner's rules. D-5 (run lifecycle)
  is WP-17.1's and was not touched. No migration-register row: no cache, key,
  prompt or schema moved. **WP-16 is not done:** WP-16.3 remains, so there is
  no package acceptance check. The acceptance clauses this slice owns hold:
  "editing external environment state cannot break a run's later stages" (every
  transport, the environment changed or removed after the digest; a field edit
  through its handler too), and "no child command … unintentionally receives
  the key" for the app's own environment (spawn and `subprocess.run` children
  measured; `os.startfile` is Windows-only and not run). "No log" holds for this
  slice's own messages; the rest of logging is WP-22.1's.
- **Base.** `main` = `origin/main` = `93c6a99`; no drift at the start or before
  the push. Baseline **4,512 passed, 2 skipped, 10 deselected** (325 s),
  identical to the WP-16.1 handoff. The two skips are IPv6 loopback and chmod as
  root. SDK 1.7.0, PyMuPDF 1.28.2, Python 3.11.15. #175 (SDK 1.8.0) and #174
  (dependency bumps) are still open, so no probe was re-run for an SDK change.
- **Reproduced first.** Scratch probes ran as `tests/test_probe_*.py` in a
  `git archive` copy of `origin/main`, so the suite's fakes, conftest and
  hermetic guard applied. `drawing_analyzer.client.Anthropic` was replaced by a
  recording stand-in handing back the suite's fakes (the gauntlet's mini-set
  script behind `_Pipe`, which answers every stage on every transport); keys
  were built at runtime and recorded as classes only. Every fact in the request
  held:
  - **q1:** a GUI-shaped real-time exhaustive run (`client=None`, overlap off)
    called `get_client()` 14 times (per sheet in the digest, per critique read)
    with one key. The environment changed after the digest (to key B, or to a
    truncated key) sent every later stage to the new value (12 calls).
  - **q2:** removed instead: identity, review plan, critique, synthesis and
    verification FAILED, citation PARTIAL, `qc_status` PARTIAL, seven
    `…: ANTHROPIC_API_KEY environment variable not set` lines in `ctx.errors`
    (the GUI logs each). Cross-QC read COMPLETE beside its error (found, below).
  - **q1 through the GUI handler:** a Backspace (`_on_key_changed`) did the
    same as q1; an emptied field the same as q2.
  - **q3:** real time resolves a client per sheet, so the second sheet used key
    B; batch resolves one client for submit and collect (key A throughout).
  - **q4:** overlap on: one client is resolved at 4259 after the digest and
    serves every later stage (it took key B).
  - **q5:** a real `anthropic.Anthropic` passed in: 0 `get_client()` calls on
    Fast, Batch, Hybrid and Economy, with or without a key in the environment;
    with an UNCERTAIN verdict the investigation also ran on it (0 calls).
  - **q6:** `_stage_overlap_enabled`: `client=None` with a key → True; a real
    SDK client → True with or without the environment; a wrapper → False;
    `object()` → False. So a real client keeps the GUI's overlap.
  - **q7:** the busy block disables analyze, clear, HTML, reviewed, export and
    specs, never `key_entry` or `key_show_btn`.
  - **q9:** with the key in the environment (as the GUI writes it), a spawn-pool
    child and a `subprocess.run` child both see `ANTHROPIC_API_KEY`; without it,
    neither does. `os.startfile` was read, not run.
  - **q10:** a session-only key (typed, plaintext declined, nothing saved) reached
    both exports only through the environment; with the environment unwritten
    they got none.
  - **q11:** a library caller (`client=None`) reads the environment through
    `get_client()` per sheet; with no key the digest phase stops (`ValueError`).
- **Facts confirmed, not assumed.**
  - **The instrumented suite.** A scratch copy of `origin/main` added
    append-only blocks at the end of `__init__.py`, `client.py` and
    `pipeline.py`, behind `WP162_LOG`, with the test name. They logged every
    `get_client()` call (with a module-class `__setattr__` wrapping whatever a
    test monkeypatched in), every SDK client construction, every
    `os.environ` read, write and delete of the key from `drawing_analyzer`
    code, every `extract_drawing_context` call and whether it got a client,
    every overlap decision, and every child launch (spawn, `subprocess`,
    `webbrowser`) with whether the key was in its environment. Value classes
    only. Over the whole suite (4,512 passed, no outcome changed): 334 runs,
    177 overlap decisions, 96 children, 34 `get_client` calls, 9,140 key reads
    and 4,528 writes in all (nearly all the hermetic guard's own).
  - **q8, who reaches what:** the GUI's env reads and writes (`_load_api_key`
    393/398, `_on_key_changed` 1146/1153) are reached only by
    `tests/test_gui_lifecycle.py`; `gui.py` 1829 and the exports (2319, 2394)
    by no test; `client.get_client:25` 29 times, value absent, through
    `prose_harvest._client_or_none` from three direct stage tests
    (`test_drawing_ledger`, `test_prose_filler_and_assurances`,
    `test_prose_match_signatures`); `pipeline.py` 527 by none (the one run with
    `client=None` returns before the overlap decision).
  - **The pinned list.** No `get_client()` call happened inside a run. Five went
    to monkeypatched fakes: `test_drawing_batch_critique` (submit and collect),
    `test_drawing_markup_rich` (twice) and `test_drawing_investigate`. The
    patches in `test_ab_sweep`, `test_cost_confirmation_scan`,
    `test_drawing_batch_critique:622` and `test_drawing_verify` assert it is
    never called. No test passes a real SDK client to a run.
  - **"24 stage sites".** Not reproducible without a definition: an AST walk of
    `pipeline.py` finds 28 calls passing `client=` to 23 callees, 22 of them
    stage calls. The plan note now cites q5 instead. The request's "19 fallbacks
    in 15 modules" is 19 in 14 (`batch_critique` ×3, `pipeline` ×3, `verify` ×2,
    one each in `citation_check`, `critique`, `cross_qc`, `digest`, `focus`,
    `investigate`, `prose_harvest`, `review_planner`, `set_identity`,
    `synthesis`, `core/tokenizer`).
  - **Timing.** The GUI process has not imported `anthropic` when Analyze is
    clicked (`drawing_analyzer.pipeline` does not import it). Three idle runs:
    SDK import 552-624 ms, first construction 72-85 ms, later ones ~50 ms.
  - **Real Tk** (a uv-installed standalone Python 3.11.13 with Tk 8.6.14,
    threaded; the pinned customtkinter 6.0.0; Xvfb):
    - a disabled `CTkEntry` refuses typing, Backspace, `<<Paste>>`, Ctrl+V and
      `<<Cut>>`, and still shows its masked value;
    - it looks identical to an enabled one (`foreground == disabledforeground`
      = gray10; the backgrounds match);
    - `<Return>` and `<FocusOut>` still fire on it, and a click still focuses it;
    - Show still masks and unmasks it; a disabled Show button runs nothing;
    - clicking a `CTkButton` takes focus, so clicking Analyze fires the entry's
      `<FocusOut>` (the save) before the run starts;
    - `CTkLabel.cget("text")` and `cget("text_color")` return what was set.
- **The decision, made by the owner before any code** (AskUserQuestion, three
  rounds, eleven choices, each as recommended). Measured first:
  - a switchable scratch implementation, one environment knob per open choice,
    on top of the instrumented copy;
  - today, a recommended set R and 18 variants each varying one knob from R, run
    over the 15 pinned files (880 tests) with the instrumentation and diffed
    test by test against today;
  - a 21-case table (the GUI driven through the real `_on_process` → `_worker`
    → `_on_done`: edits mid-run through the field and the environment, no key, a
    typed non-key, BOM and non-key launch values, a worker that raises,
    children, the exports, a declined save during a run, a library caller, no
    key in any message) through every variant.

  **Pinned files:** every variant that stops the GUI writing the environment
  moves exactly the 4 WP-16.1 env asserts (and the env events of 6 GUI tests);
  nothing else moves in outcome or events under any variant. Turning the
  snapshot off while the env is no longer written makes every GUI run FAILED at
  the digest: the two go together. The rules, and what was not taken:
  - **Round 1.** Key read on the UI thread, client built in the worker (not
    taken: built on the UI thread, a 0.6-0.7 s freeze on the first Analyze; a
    provider object, which turns the overlap off). The applied key is the
    normalized field value only (not taken: fall back to the launch value when
    the field is emptied, which keeps a key the user deleted). An inherited
    `ANTHROPIC_API_KEY` is read at launch, then removed (not taken: left as
    launched, which children inherit, C15; as today). The exports read the
    applied key (not taken: the last run's key, C17 embeds A after the field
    moved to B and C16 finds nothing before a run; leave to WP-16.3, which
    loses a session-only key).
  - **Round 2.** The entry only is disabled (not taken: Show too, so the run's
    key cannot be checked). No lock during Export All (not taken: locked, which
    buys nothing once the key is taken at the click). `<FocusOut>`/`<Return>`
    unchanged while locked (not taken: ignored while locked, which removes C19's
    two mid-run consent dialogs but edits `_persist_key`, WP-16.3's). A status
    word (not taken: muted text; nothing).
  - **Round 3.** The launch value normalized, and a non-key used with a warning
    (not taken: normalize only, silent; refuse, which makes the saved key B
    replace the env value, C11, and ignores a future key format; neither, C10's
    BOM sent). A typed non-key still runs (not taken: refuse to start, which
    makes a future key format unusable). Re-baseline the four env asserts (not
    taken: keep them, which keeps G2).
- **What changed:**
  - **`client.py`:** `new_client(api_key)`, the one construction;
    `get_client()` builds through it and keeps its environment read and its
    message. The module docstring names the two callers.
  - **`gui.py`:**
    - `_load_api_key` pops `ANTHROPIC_API_KEY`, normalizes it
      (`normalize_api_key`), and adds a value-free `KeyNote` when it fails
      `looks_like_api_key`; it no longer writes the environment;
    - `__init__` starts `_applied_key` from the launch key;
    - `_on_key_changed` sets `_applied_key` and no longer writes or pops the
      environment;
    - `_on_process` reads `_applied_key` before the cost dialog (the "No API
      key" check included), locks the entry in the busy block and passes
      `api_key=` to the worker;
    - `_worker(*, api_key)` imports `client` lazily (so GUI startup does not
      import the SDK), builds the client and passes `client=`;
    - `_set_key_editable`: the lock, the status "locked while analyzing"
      (`_KEY_LOCKED_STATUS`), and the restore read from the label itself;
      called first thing in `_on_done` and `_on_error`;
    - the exports read `_applied_key`, then `load_api_key_from_file()` as
      before; Export All takes it on the UI thread and hands it to
      `_export_all_worker(applied_key=)`;
    - the key-row comment.
  - **`pipeline.py`:** one comment corrected (the GUI now passes a client).
  - **`help_content.py`:** the key section says the env var fills the field at
    launch, and that a run keeps its key, the field locks, and the app does not
    pass the key on to programs it starts.
- **Contracts decided:** none in `DECISIONS.md` (the owner's rules above).
- **Cache/schema effects: none.** No key, prompt, schema or manifest key moved.
- **Re-baselined tests (the owner's decision, round 3):**
  `tests/test_gui_lifecycle.py`
  `test_the_key_field_shows_applies_and_saves_the_normalized_key` (both
  parameters; 380: the applied key holds the key and `os.environ` does not),
  `test_a_field_holding_only_invisible_characters_is_no_key` (406: the applied
  key is empty and the environment is untouched), and
  `test_startup_loads_the_normalized_key_and_keeps_the_notes` (442: the load
  returns the key and writes none; its `delenv` at 446 gains `raising=False`,
  since nothing writes the value it cleared; 448 holds as written). Every other
  assert in them is unchanged.
- **New tests: 33.**
  - **`tests/test_gui_lifecycle.py`, WP-16.2 section (23):** a stub
    `DrawingAnalyzerApp` (`_App`) driven through the real handlers, mirroring
    `__init__`'s key lines, with the worker thread captured and run in order:
    - the run gets one real client built from the applied key;
    - a field Backspace, an emptied field, the environment set to key B or
      removed after the digest: every later stage keeps key A (the real
      pipeline, the gauntlet's mini set, a recording SDK stand-in);
    - the entry locked while busy (Show live, the status word) and unlocked,
      status restored, on done and on a worker that raised;
    - a keystroke while locked never reaches the field;
    - a status set during the run survives the unlock;
    - the launch key normalized and removed (BOM + CRLF, spaces + zero-width
      space, not a key with its warning, only invisible characters);
    - a launch value that is not a key is the one used (the saved key does not
      replace it);
    - no spawn-pool child and no `subprocess.run` child inherits a key, typed or
      inherited at launch;
    - both exports embed the applied key (session-only; launch env);
    - Export All embeds the key applied at the click;
    - an emptied field refuses Analyze; a typed non-key still runs;
    - `__init__` starts `_applied_key` from the launch load (structural, like
      the hooks test);
    - no dialog, status, activity-log line, log record or captured output
      carries the key or a non-key launch value, over launch, run, failure and
      export; asserted non-vacuous.
  - **`tests/test_run_scoped_client.py` (10):** a real `anthropic.Anthropic`
    (fake resources) passed to `extract_drawing_context` serves every stage on
    Fast, Batch, Hybrid and Economy, investigation included, with the
    environment set to another key or removed after the digest, and
    `get_client()` patched to fail (8); a real client keeps the overlap with no
    key in the environment, a wrapper does not (1); `new_client` is
    `get_client`'s construction and `get_client` keeps its contract (1).

  Classified against the copy of `origin/main` from `--junitxml`, and again with
  a shim putting today's behaviour behind the new names (`new_client`,
  `_applied_key`, a no-op `_set_key_editable`, an ignored `_worker(api_key=)`):
  - **17 fail on behaviour** (and so do the 4 re-baselined test ids);
  - **2 fail only on a new name** (`new_client`; the `__init__` structure);
  - **14 pass**, pinning what must not move: a passed client serves every
    stage on every transport whatever the environment does (8) and keeps the
    overlap (1); a session-only key and a launch key reach both exports (2);
    an emptied field refuses Analyze (1); a status set during the run survives
    (1); no message carries the key (1).
- **Fixture effects, instrumented over the whole fixed suite**, diffed test by
  test against the base run (sites compared by module and function):
  - **Outcomes:** all 4,514 existing tests unchanged (4,512 passed, 2 skipped);
    33 added.
  - **Events:** only 6 existing tests moved, all in `test_gui_lifecycle.py`,
    each losing a GUI env write, read or pop the fix removed. Runs, overlap
    decisions, children, SDK constructions and `get_client` calls are identical
    for every existing test.
  - **The fix's own:** the GUI's only env operations are `_load_api_key`'s read
    and pop; every GUI-driven run passes a client; no `get_client()` call
    happens inside any run; the children launched by the new tests see no key.
- **Case table on the fix:** identical to the decided variant R in every case
  except the status label: the word is "locked while analyzing" (R's knob used
  "in use by this run"), and the unlock restores what the label showed only
  while it still shows the lock word, read from the label itself (C04: a status
  written during the run stays). The first implementation read it from a record
  the case table's stub label bypassed, and was changed before the push
  (review, below).
- **Probes on the fix:** q1-q6, q9 and q11 unchanged (the library path and the
  pipeline, by design); q7 now shows `key_entry` disabled, Show untouched, and
  `api_key` passed to the worker; q10 shows both exports keep a session-only
  key with no environment. q1 through the GUI handler now shows the handler no
  longer feeds the environment: a `client=None` run beside it has no key, which
  is the library path the GUI no longer takes.
- **The real app, end to end** (the real `DrawingAnalyzerApp` under Xvfb in the
  uv Python, the update check patched out, `tkinterdnd2` removed from that venv
  because its native library aborts under Xvfb in `__init__`, before any
  WP-16.2 code; driven inside `mainloop()`):
  - launched with a BOM + CRLF key in the environment: the environment no longer
    holds it, and the field, the entry widget and the applied key hold the clean
    key; status "loaded";
  - control: with the entry focused and unlocked, a Backspace truncates the
    applied key (the environment stays empty);
  - locked: Backspace, typing, Paste and Cut leave the field and the applied key
    unchanged; Show unmasks; the status reads "locked while analyzing"; unlocked,
    the status shown before is restored;
  - Analyze: `_on_process` returns in 17-22 ms; the worker thread passes a real
    `anthropic` client built with the key; the environment holds no key during
    the run; a `subprocess` child sees none; a Backspace during the run does not
    reach the field; the entry is locked for the whole run and unlocked, status
    restored, after `_on_done`.
- **Review before push (own diff):**
  - The status restore first depended on `_set_key_status` recording what it
    showed; the case table's stub bypassed that and left the lock word after the
    run. The restore now reads the label (`cget`, measured on a real `CTkLabel`),
    so it holds whatever wrote the status.
  - `client` is imported inside `_worker`: a module-level import would move the
    SDK import (0.6 s) into GUI startup.
  - `_worker(api_key=)` is keyword-only and required, so a caller that forgets it
    fails loudly rather than falling back to the environment.
  - The first help-text draft said the key is "never handed to other programs".
    It now says the app keeps it out of its own environment, and that a key set
    system-wide is visible to every program anyway: what `os.startfile` does on
    Windows was not measured.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **4,512 passed, 2 skipped, 10 deselected**
    (325 s) on `93c6a99`.
  - The two touched test files: 53 passed (20 existing, 33 new).
  - Full suite: **4,545 passed, 2 skipped, 10 deselected** (351 s), the
    baseline plus the 33 new tests, the same two environment skips (IPv6
    loopback, chmod as root). Instrumented run: the same counts (397 s). Re-run
    on the final tree, after the review change to the status restore: the same
    counts (348 s).
  - `python -m compileall -q src`: clean.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` (0.14.5): clean.
    F401/F811/F841 over the touched files: one pre-existing F401 in
    `pipeline.py` (`normalize_specs_text`, present on `origin/main`; this
    slice's `pipeline.py` change is a comment), none in the touched lines.
  - `python scripts/scan_secrets.py`: clean (215 tracked files, the new test
    file included). The fake keys are built at runtime, every parametrized case
    has an id, and no assertion compares a key in a way that would print it.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:**
  - **CHANGELOG** (Fixed): G2.
  - **README:** the key paragraphs (the environment variable fills the field at
    launch and is normalized; a non-key launch value is used with a warning), a
    new paragraph on a run keeping its key, the lock and what children inherit,
    and the `ANTHROPIC_API_KEY` row of the environment-variable table.
  - **`help_content.py`:** the key section (above).
  - **CLAUDE.md:** the key-store passage's "the env path is not checked"
    corrected; a new passage after it (*A GUI run keeps the key it started
    with*).
  - **The plan:** a WP-16.2 note under WP-16's Step 1 / Step 2 notes, with the
    "24 stage sites" count corrected.
  - **PROGRESS:** this entry; the WP-16.2 row; the G2 row; notes on WP-16.3,
    WP-17.1 and WP-06.3; the Next-up line.
- **Not verified:**
  - live API behaviour (no budget, O-4; this slice makes no call), including
    what the API answers to a key that is not an `sk-ant-` key;
  - Windows: `os.startfile` and the update installer's launch, WER crash dumps,
    and the frozen build (O-8, WP-23.2). The claim is only that the app's own
    environment no longer holds the key; a key the user set system-wide is
    visible to every program regardless.

  Windows is covered by this PR's CI (`ci.yml`'s Windows leg runs the hermetic
  suite, the GUI tests included, on the fake toolkit).
- **Risks and residual gaps:**
  - **Visible changes, by design:**
    - the key field is locked while an analysis runs, with the status "locked
      while analyzing";
    - an `ANTHROPIC_API_KEY` exported in the shell is no longer passed on by the
      app to what it starts (a script run from the GUI's opener that relied on
      it would not see it);
    - a launch value that is not an `sk-ant-` key now gets a warning line.
  - **A worker killed by `KeyboardInterrupt`/`SystemExit`** never reaches
    `_on_done`/`_on_error`, so every control stays locked, the key entry
    included (pre-existing for the others; D-5, WP-17.1 note).
  - **`<FocusOut>`/`<Return>` still fire on the locked entry**, so a key whose
    plaintext save was declined re-opens the consent dialog during a run, as
    when idle (C19; WP-16.3 note).
  - **The exports still fall back to the saved key** when the field is empty
    (WP-16.3, step 7).
- **Found, not fixed:**
  - **Cross-QC reads COMPLETE when it could not get a client**:
    `CrossQCResult(error=...)` defaults `complete=True` (q2; WP-06.3 note). The
    GUI no longer reaches it.
  - **Clicking Analyze fires the entry's `<FocusOut>`** before the run starts
    (real Tk: a `CTkButton` takes focus), so an unsaved key is saved, or the
    consent dialog opens, at that click. Pre-existing and harmless to the run
    (the key cannot change), but it is the path WP-16.3's reentrancy guard must
    cover.
- **Next:** Wave 1 is done. WP-02.2 (Wave 2) is next in queue order. WP-17.1
  (Wave 4) is unblocked by this slice; WP-16.3 (Wave 4) is unblocked. WP-11.3
  and WP-10.4 (Wave 2) are available.

### 2026-09-28 — WP-16.1: a key file saved "UTF-8 with BOM" no longer breaks the saved key, and a migration keeps what it did not verify ([PR #176](https://github.com/Abe-Borg/drawing-analyzer/pull/176))

- **Slice and IDs:** WP-16.1. G3 (implemented+validated). No `DECISIONS.md`
  contract covers credentials, and none was opened (as the request asked); the
  owner's choices are recorded here as the owner's rules. No migration-register
  row: no cache, key, prompt or schema moved. **WP-16 is not done:** WP-16.2 and
  WP-16.3 remain, so there is no package acceptance check. The two acceptance
  clauses this slice owns hold: "BOM migration preserves the usable key" (p1,
  p13) and "failed migration preserves the original" (a store that cannot be
  verified deletes nothing; a refused file is kept).
- **Base.** `main` = `origin/main` = `b07172b`; no drift at the start or before
  the push. Baseline **4,438 passed, 2 skipped, 10 deselected**
  (313 s), identical to the WP-11.2 handoff. The two skips are IPv6 loopback
  and chmod as root. SDK 1.7.0 and httpx2 2.13.1, unchanged, so p3 stands as
  measured.
- **Reproduced first.** Scratch probes ran as a `tests/test_probe_*.py` in a
  `git archive` copy of `origin/main`, so the suite's fakes, conftest and
  hermetic guard applied. Both key locations were redirected into `tmp_path`,
  the keyring was a dict-backed stand-in for the `keyring` module (so the
  store's own `_keyring_get`, which strips, ran), and the fake key was built at
  runtime. Only each value's class was recorded. Every fact was as the request
  stated:
  - **p1:** a BOM file with a working keyring returns the BOM value (length
    102), the keyring holds it, and the file is deleted; the next load serves
    it from the keyring.
  - **p2:** with no keyring, the BOM value is returned and the file kept.
  - **p3:** `anthropic.Anthropic(api_key=BOM + key)` over
    `httpx2.MockTransport` sends an `x-api-key` of 104 bytes starting
    `ef bb bf` (the 401 is the mock's). Also measured: a two-line value
    (p7), `hello world` (p11) and a key with a zero-width space inside are
    sent as they are over the mock. What a real transport or the real API does
    with them was not measured.
  - **p4:** `save_api_key(BOM + key)` stores the BOM value.
  - **p5:** a BOM value in the config-dir file and a different valid key in the
    exe-dir file: the BOM value wins and is migrated, and both files are
    deleted.
  - **p6:** a BOM-only file returns `'\ufeff'` (truthy: "loaded"), is migrated
    and deleted.
  - **p7:** a key followed by `"\n# my work key"`: the newline is kept, the
    value migrated and the file deleted.
  - **p8:** a UTF-16 LE file: the decode error is swallowed, `""` returned, the
    file kept, and nothing is logged or printed.
  - **p9:** a zero-width space before the key and a word joiner after it are
    kept, migrated, and the file deleted.
  - **p10:** a keyring entry holding a BOM value is served as is and never
    repaired (0 writes).
  - **p11:** `hello world` is migrated as the key and the file deleted.
  - **p12:** `"\ufeff".isspace()` and `"\u200b".isspace()` are False;
    `str.strip()` strips NBSP; `utf-8-sig` removes one leading BOM only.
  - **p13:** a backend that drops the BOM on read fails the round-trip, so the
    BOM value is used for the session and the file kept.
  - **The GUI field** (the fake-toolkit harness): a paste of `BOM + key + " "`
    set the environment to the BOM value, and `_persist_key` saved it; the
    status read "set", then "saved".
- **Facts confirmed, not assumed.**
  - **Only one test file reaches the store.** An instrumented scratch copy of
    `origin/main` added an append-only wrapper block at the end of
    `core/api_key_store.py`, behind `WP161_LOG`, with the test name. It logged
    every keyring set and read, every file read, unlink and chmod on a key
    path, and every load and save outcome, with each value's class only. A
    module-class `__setattr__` wrapped whatever a test monkeypatched in. Over
    the whole suite (4,438 passed, no outcome changed): the module was
    imported once, and 44 events came from the 12 tests of
    `tests/test_api_key_store.py` and nowhere else: 11 keyring sets, 10 reads,
    3 file reads, 4 unlinks, 2 chmods, 5 loads, 9 saves.
  - **The pinned fixtures:** `key_file` (24) and `working_keyring` (41) each
    redirect one location, so nothing covered p5; `working_keyring`'s read does
    not strip. All 12 tests' fake keys match `sk-ant-[A-Za-z0-9_-]+`, the
    shortest `sk-ant-x`. `test_save_with_working_keyring_removes_stale_plaintext_file`
    (166) pins save's every-location rule. (`test_save_tightens_preexisting_loose_file`
    writes `old-key` to the file, but save overwrites it and nothing loads it.)
  - **The env path:** the hermetic guard sets
    `ANTHROPIC_API_KEY=test-key-not-real-do-not-use`, which is not a key.
  - **The field rewrite does not re-enter.** Measured with real Tk 8.6 and the
    pinned customtkinter 6.0.0 under Xvfb (a uv-installed standalone Python
    3.11.13 with tkinter; the container's Python has none): a `set` inside the
    variable's own write trace runs no trace (one callback per edit, depth 1;
    Tcl disables a variable's traces while one runs). The entry then shows the
    normalized value, with the cursor at the end after a paste, on a plain
    `tkinter.Entry` and on a `CTkEntry` alike.
  - **Layering:** `core/` imports nothing from the package top level;
    `diagnostics` already imports `core.app_paths`; the diagnostics file handler
    is attached only to the `drawing_analyzer.diagnostics` logger
    (`propagate=False`).
- **The decision, made by the owner before any code** (AskUserQuestion, three
  rounds, eleven choices, each as recommended). Measured first:
  - a switchable scratch implementation, each open choice an environment knob;
  - the base and 20 variants, each varying one knob from the recommended set,
    run over the pinned files (`tests/test_api_key_store.py`,
    `tests/test_gui_lifecycle.py`) with the instrumentation, and diffed test by
    test against the base;
  - a 27-case table (p1-p13 with variants, six save cases, the GUI field)
    through every variant.

  **No pinned test moved under any variant**, in outcome or events, except
  "equal files only, save too", which fails the pinned save test (166).
  (The first diff showed three tests moving under every variant. That was an
  artifact of the hook logging `read_text` only, while the scratch read bytes;
  with `read_bytes` logged too, nothing moved.) The case table decided:
  - **Normalizer: whitespace and Cf at both ends.** Not taken: BOM only (p9
    refused with a note; a paste starting with a zero-width space refused at
    save); Cf removed anywhere (a zero-width space inside a key loads silently,
    past the evidence).
  - **Shape: `sk-ant-` + `[A-Za-z0-9_-]+`, no floor, the redactor's pattern.**
    Not taken: charset only (one-word junk and the placeholder pass); no
    whitespace/control characters (almost any single word passes); none (p7
    and p11 migrate and their files are deleted). Accepted cost: a future key
    format without `sk-ant-` is refused at migration and at save (it is still
    applied to the session from the field).
  - **Where: migration, save and the keyring.** Not taken: migration and save
    (p11k's `hello world` served every launch); migration only (s1: `hello
    world` saved).
  - **A failing file: refused, kept, not used, named.** Not taken: used this
    session only (p7's two-line value and p11 sent to the API; p5b's junk
    config file wins over a good exe-dir key); migrated (today).
  - **Round 2.** Repair by a verified rewrite (not taken: normalize on read
    only; the BOM value stays stored for good). A failing keyring entry is
    ignored and named (not taken: served with a warning, every call then
    fails; served silently). A migration deletes only equal files, save
    unchanged (not taken: equal files for save too, which re-baselines 166;
    the source file only, which leaves a plaintext duplicate of the migrated
    key; every location, which loses p5's other key). UTF-16 is decoded (not
    taken: skipped with a diagnostic; skipped silently).
  - **Round 3.** Notes in the GUI activity log and the diagnostics log (not
    taken: diagnostics only, where the user sees "no key" with no reason). The
    status stays "loaded"/"no key" (not taken: a new "check key file"). The
    field shows the normalized value (not taken: keep what was typed, where
    Show can reveal a value that is not the one in use).
- **What changed:**
  - **`core/api_key_format.py` (new, stdlib-only leaf):** `ANTHROPIC_KEY_RE`,
    `normalize_api_key`, `looks_like_api_key`.
  - **`diagnostics.py`:** the redactor's key pattern is that constant (the same
    compiled object).
  - **`core/api_key_store.py`:**
    - `KeyNote`, `KeyLoadResult`, `load_api_key_with_notes`;
      `load_api_key_from_file` returns its key (contract unchanged);
    - `_key_from_keyring` (normalize, check, repair);
    - `_key_from_files` and `_read_key_file` (a 64 KiB bounded read, UTF-16 or
      UTF-8, every skip named);
    - `_migrate_legacy_file_key` keeps its name and now removes only the files
      holding its key (`_remove_key_files_holding`);
    - `_key_file_present` (see review below);
    - `save_api_key` normalizes and refuses a value that is not a key, with a
      value-free `ValueError`;
    - every note is logged to the diagnostics logger by name.

    Unchanged: `_keyring_get` (the backend seam: `.strip()`, which the
    verified round-trip reads and the pinned fixtures replace),
    `_keyring_set`, `_keyring_store_verified`, `_remove_key_files` (save),
    `_write_key_file`, `secure_backend_available`.
  - **`gui.py`:**
    - `_load_api_key` keeps the notes when it loads from the store (the env
      still wins, unnormalized: WP-16.2);
    - `_report_key_at_startup` holds the moved status lines and shows the
      notes first;
    - `_on_key_changed` normalizes and rewrites the field when it differs;
    - `_persist_key` normalizes;
    - the key comment (426-428) now says a plain-text file needs consent.
  - **`tests/conftest.py`:** the stale "the GUI has no unit tests" comment.
- **Contracts decided:** none in `DECISIONS.md` (the owner's rules above).
- **Cache/schema effects: none.** The key store is outside every cache; no
  key, prompt, schema or manifest key moved.
- **Re-baselined tests: none.** Every pinned test passes unchanged.
- **New tests: 74.**
  - **`tests/test_api_key_store.py`, WP-16.1 section (66):**
    - the normalizer and shape tables;
    - one test per probe the rules change (p1-p11, p13), with p5, p7, p8, p9,
      p10 and p11 in several shapes;
    - the oversized, unreadable and non-UTF file, and a store that cannot be
      verified;
    - the migration helper, and the two review cases (a presence that cannot
      be told, a file unreadable after a migration);
    - save: normalizes (keyring and consented file), refuses a value that is
      not a key, keeps its every-location rule;
    - notes reach the diagnostics log;
    - no note, log record (root and diagnostics loggers), exception message or
      captured output carries the key, over 13 scenarios; the test asserts it
      saw words and records, so it is not vacuous.

    It adds a two-location fixture and a `keyring`-module stand-in, so the
    store's own read (which strips) runs.
  - **`tests/test_gui_lifecycle.py`, WP-16.1 section (8):**
    - the field shows, applies and saves the normalized key, with a `_TclVar`
      modelling Tcl's traces and a re-entrant variant;
    - a clean key is not rewritten;
    - a field of invisible characters is "no key";
    - a refused save says so without the value;
    - the startup load keeps the notes;
    - the startup status shows them.

  Classified against the copy of `origin/main` from `--junitxml`, and again
  with a shim putting today's behaviour behind the new names, so "fails on
  behaviour" is not confused with "the name is missing":
  - **56 fail on behaviour;**
  - **16 fail only on the new API** (the normalizer and shape unit rows that
    today's `strip()` would pass, the notes-to-diagnostics test, the
    clean-entry test);
  - **2 pass**, pinning save's every-location rule and that a clean key is
    never rewritten in the field.
- **Fixture effects, instrumented over the whole fixed suite:** the same hooks, with a
  hook on `Path.open` since the store now reads bytes, diffed test by test
  against the base run:
  - **Outcomes:** all 4,512 tests pass, and the module is imported once.
  - **Which tests reach the store:** the 12 pinned tests, 36 of the new store
    tests and 2 of the new GUI tests (the startup load and the refused save),
    and nothing else.
  - **Events:** of the 12 pinned tests, 11 have identical events.
    `test_load_migrates_legacy_file_into_keyring` makes one extra read of the
    file it migrated, because the cleanup re-reads every key file to confirm it
    still holds the verified key before deleting it. That is deliberate: it
    never deletes a file that changed after it was read. Its outcome is
    unchanged.
- **Case table on the fix:** the 27 cases match the decided scratch variant in
  26. The one difference is deliberate and pinned: in p5b the refused config
  file is named once, not a second time as "left in place".
- **Probes on the fix:** p1, p2, p4-p11 and p13 and the GUI field give the
  fixed outcomes. p3 is the SDK's own behaviour with a BOM value handed to it,
  unchanged; `test_p3_the_wire_never_carries_the_bom` shows the store no longer
  hands it one.
- **Review before push (own diff):**
  - `_migrate_legacy_file_key` had become unused while still encoding the old
    every-location rule. It now takes the new rule and the load goes through
    it.
  - `Path.exists()` re-raises a permission error, so a presence check outside
    any `try` in the new post-migration cleanup could have ended a load after
    a migration that worked. `_key_file_present` treats "cannot tell" as
    present, so the read names it.
  - The empty-file note now says "or holds only spaces or invisible
    characters".

  Three tests pin these; all three fail on `origin/main` on behaviour.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **4,438 passed, 2 skipped, 10 deselected**
    (313 s) on `b07172b`.
  - The two touched test files: 98 passed (24 pinned, 74 new).
  - Full suite after the first implementation: **4,509 passed, 2 skipped, 10
    deselected** (318 s), the baseline plus the 71 tests at that point. After
    the review fixes: **4,512 passed, 2 skipped, 10 deselected** (312 s), the
    baseline plus the 74 new tests. The same two environment skips (IPv6
    loopback, chmod as root).
  - `python -m compileall -q src`: clean.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` (0.14.5): clean.
    F401/F811/F841 over the touched source and test files: clean.
  - `python scripts/scan_secrets.py`: clean (214 tracked files, the new
    module included). The fake keys are built at runtime, and no test id
    carries one (the parametrized tables have ids).
  - The probes and the case table on the final code are identical to the first
    implementation's.
  - The browser suite was not run: no report or JavaScript changed.
- **Docs:**
  - **CHANGELOG** (Fixed): G3.
  - **README:** the key paragraph (111-115: the keyring, a plain-text file only
    with consent), and a paragraph on normalization, the `sk-ant-` rule and the
    migration.
  - **`help_content.py`:** the credential bullet says a legacy key file moves
    only when it holds a key, and anything else is kept and named.
  - **CLAUDE.md:** a key-store passage after the GUI lifecycle paragraph; the
    `core/` kernel list names `api_key_format.py`.
  - **The plan:** a WP-16.1 note under WP-16's Step 3.
  - **PROGRESS:** this entry; the WP-16.1 row; the G3 row; notes on WP-16.2,
    WP-16.3 and WP-22.1; the Next-up line.
- **Not verified:**
  - live API behaviour (no budget, O-4; this slice makes no call), including
    what the real API answers to a BOM, a newline or a space in `x-api-key`;
  - what Windows Credential Manager (`WinVaultKeyring`) does with a BOM or
    other format characters: O-8's, and not claimed. The repair relies only on
    the verified round-trip, whatever the backend does;
  - the frozen build's keyring (WP-23.2).

  Windows is covered by this PR's CI (`gates-windows` is tag-only; `ci.yml`'s
  Windows leg runs the hermetic suite).
- **Risks and residual gaps:**
  - **Visible changes, by design:**
    - a key file that is not a key (p7's comment line included) is no longer
      loaded, and the user sees "no key" plus a line naming the file;
    - a keyring entry that is not a key is no longer served;
    - a value typed into the field that is not a key is applied to the session
      but not saved, and "could not be saved" is logged (the status reads
      "not saved").
  - **A future key format without `sk-ant-`** is refused at migration and at
    save (the owner's accepted cost). The diagnostics redactor would not
    recognise it either, by name or by value, unless it sits in a named field;
    one constant now governs both.
  - **The env path** is neither normalized nor checked (WP-16.2).
  - **A save still removes every key file**, a different key's included (the
    owner's rule; pinned).
  - **The store logs its notes on every load:** the launch, and each export
    reload (WP-16.3).
- **Found, not fixed:**
  - **`core.api_config`'s and `core.tokenizer`'s warnings never reach the
    diagnostics log.** They log through `getLogger(__name__)`, while the file
    handler is attached only to `drawing_analyzer.diagnostics`
    (`propagate=False`). So "a model id fell through to conservative
    defaults", "refusal fallback unavailable" and `count_tokens_via_api`
    failures reach only Python's last-resort stderr handler, which a windowed
    build does not have (WP-22.1 note).
  - **`_persist_key` retries a refused save on every focus change**, logging
    the refusal each time (WP-16.3 note).
- **Next:** WP-16.2 (Wave 1, no dependency). WP-16.3 (Wave 4) is unblocked.
  WP-11.3 and WP-10.4 (Wave 2) are available.

### 2026-09-25 — WP-11.2: an unexpected error inside the digest phase stops the phase, not the run ([PR #173](https://github.com/Abe-Borg/drawing-analyzer/pull/173))

- **Slice and IDs:** WP-11.2. R1, digest-phase containment (implemented+validated).
  R1 stays open for WP-11.3 (the revision check on reopen). No contract is
  newly decided. D-2 gains a note (a digest phase stopped by an unexpected
  error reads FAILED, whatever was read) and D-5 an input note (what
  `KeyboardInterrupt` leaves). No migration-register row: no key, prompt or
  schema moved. **WP-11 is not done:** WP-11.3 remains, so there is no package
  acceptance check.
- **Base.** `main` = `origin/main` = `0aa2758`; no drift at the start or before
  the push. Baseline **4,402 passed, 2 skipped, 10 deselected** (269 s),
  identical to the WP-11.1 handoff. The two skips are IPv6 loopback and chmod
  as root.
- **Reproduced first.** Scratch probes ran in a copy of `origin/main`, with the
  suite's fakes and the hermetic guard applying. Each fact was as the request
  stated:
  - **Real time**, three one-page sources, `digest_sheet` raising on B: the
    `RuntimeError` left `extract_drawing_context` after 1 paid read, with no
    context, journal or export. It was the same with a `DigestCache`. The
    re-run rendered all 3 pages and made 2 calls: A came from the level-2 cache
    only, since the level-1 store runs after the phase.
  - **Two workers**, with C finished when B raised: 2 reads billed, both
    discarded.
  - **A progress callback that raises** ended the run after 1 paid read.
  - **Batch submit**, the progress callback raising at B's upload: 4 uploads,
    0 deleted, no batch.
  - **Batch collect**, the progress callback raising at the poll: 6 uploads,
    0 deleted, 1 batch whose 3 reads were billed and none read back, and no
    cancel.
  - **Fast exhaustive** (render spool), the digest stage's own record raising
    (`_finish_stage`) after every read, before the critique: the spool
    directory stayed while the exception was held and went only at garbage
    collection; the critique made 0 calls (the control made 6).
  - **Economy exhaustive**, the same injection: 6 retained uploads, 0 deleted
    (the control deleted 6 of 6).
- **Facts confirmed, not assumed.** An instrumented scratch copy of
  `origin/main` added append-only wrapper blocks at the end of `pipeline.py`,
  `batch_digest.py`, `file_upload.py` and `render_spool.py`, logging the test
  name behind `WP112_LOG`. Over the whole suite (4,402 passed, no outcome
  changed):
  - **The hooks ran** 303 contexts, 247 real-time and 35 batch digest phases,
    145 submits, 139 collects, 304 sheet uploads and 164 pipeline spools.
  - **Every context returned.** The only 2 exceptions were the DA-034 direct
    tests, each raising after its cleanup:
    `test_submit_create_failure_deletes_every_uploaded_file` (a failed batch
    create, whose guard already existed; the upload loop had none) and
    `test_collect_results_error_releases_files_before_propagating`. Every
    pipeline spool was closed by the critique stage.
    So no fixture reaches the containment, and every behaviour this slice adds
    is guarded only by the new tests.
  - **The digest cache swallows its own I/O errors.** The realistic triggers
    are the caller's callbacks, an injected cache or client, and bugs; a
    keyless real-time run raises `ValueError` from inside `digest_sheet` (the
    lazy client), which containment now also catches.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, eight choices, each as recommended). Measured first:
  - one scratch implementation with each open choice switchable by
    environment variable;
  - run instrumented over the 41 test files that reach the digest phase, its
    transports or the spool (2,109 tests), diffed test by test against the
    base;
  - a 22-case table run through the base and 15 variants: real time, batch,
    Hybrid and Economy; cold and cached; a raising digest, callback, prescan,
    level-1 store, accounting, poll and results read; a read in flight;
    nothing read; `KeyboardInterrupt`; an exception after the phase; a
    callback that stays broken.

  Under every variant no pinned test moved, and the pipeline's containment
  never fired in them. The new collect guard fired once, in
  `test_collect_results_error_releases_files_before_propagating`, after that
  test's own release: one release of zero files, the only event that moved.
  Only the variant that left the collect side alone did not add it.
  The case table decided:
  - **On failure: stop after the digest phase.** All 22 cases return except
    `KeyboardInterrupt` and the two exceptions after the phase, and the
    critique makes 0 calls. Not taken:
    - continue over the read sheets: the critique also read the pages the
      digest never reached (Fast/Hybrid: 6 critique calls, 4 for pages with no
      digest; Economy: 12 uploads), and a callback that stays broken (3 cases)
      escaped outside the phase and lost the context again;
    - finalize and re-raise: no context, run.log, manifest or export.
  - **Stage status: FAILED whatever was read.** Not taken: the item rule
    capped at PARTIAL (an exhaustive run whose QC never ran reads "Completed
    with QC warnings", 5 cases); the item rule uncapped (a false COMPLETE,
    "Exhaustive QC complete", 2 Economy cases).
  - **Collect side: harvest, then release.** A poll raising on an ended batch
    reads back 3 of 3 and releases 6 of 6; on a running one the cancel is
    accepted, then 3 of 3 and 6 of 6. Not taken: release only (the 3 billed
    reads lost in all 4 collect cases); leave it to WP-17 (6 uploads leak and a
    running batch is not cancelled).
  - **Exceptions: `Exception` only.** Not taken: `BaseException` (a Ctrl+C
    mid-digest returned a context as if the run had finished normally, and a
    native panic would be continued past, which MEASUREMENT_PACKAGES §2
    forbids without a boundary analysis).
  - **Round 2.** The line gives the type name only (not taken: type and
    sanitized message; the path scrub has known gaps, U13). One run-level line,
    and each unreached page's reason names the failure (not taken: today's "no
    render outcome was recorded"; one line per page). Keep what completes in
    flight (not taken: also cancel unstarted reads, measured identical, since
    the pool never queues a read behind a busy worker). Step 7 is in the
    run-level line (not taken: a GUI-only sentence; nothing).
- **What changed:**
  - **`pipeline.py`:**
    - `extract_drawing_context` contains the digest phase (region 1: the
      prescan, tile staging, the spool, the dispatch; then the level-1 store
      over the digests in hand; region 2: the accounting in two passes).
    - `_digest_phase_line` and `_stopped_run_context` (the stop: the offline
      ledger, the roll-up, `USAGE_TOTALS`, `RUN_END` `stopped="digest"`).
    - `_UnreadPages.stop` and `not_reached`.
    - `collected=` on both transports; the real-time pool keeps what is in
      flight and closes the render stream on its own thread.
    - `@_with_run_release`, `_register_run_release` and
      `_release_retained_uploads`, which the critique's `finally` now calls too
      (same behaviour).
    - Review round 1: each page's event and each sheet's usage are recorded in
      their own `try` (`_accounting_stopped` makes the first failure the
      phase's), and the line's cache clause needs a level-1 store that did not
      fail (`cached_claim`).
  - **`batch_digest.py`:**
    - `submit_drawing_batch(slots_out=)` with the DA-034 outer guard (the
      slot in progress included);
    - `collect_drawing_batch(results_out=)` with the guard over its whole body
      and `_abandon_after_collect_error`;
    - `_digest_from_message`'s level-2 write is advisory (review round 1).
  - **`digest.py`:** `digest_sheet`'s level-2 write is advisory (review round
    1).
  - **`help_content.py`:** the upload bullet lists the exits that are covered.
  - **Not changed:** `derive_run_outcome`, the digest stage's ladder for a
    phase that did not stop, the zero-sheet and block exits, every key,
    `_SCHEMA_VERSION`, every prompt, `run_manifest.json`'s keys, the report,
    and the GUI. A stopped run returns a context, so the GUI's worker hands it
    to `_on_done`, which enables Export All unconditionally, and never to
    `_on_error` (read from `gui.py`).
- **Contracts decided:** none newly; the D-2 note and the D-5 input note.
- **Cache/schema effects: none.** No key term, contract counter or stored shape
  moved (`tests/test_drawing_cache_identity.py` unchanged). The level-1 store
  now also runs after a contained failure, over the digests in hand, under the
  same predicate (`digest_cache_admits`). `run_manifest.json` gains no key: its
  `unread_pages` lists the pages not reached. The journal gains one event type
  (`DIGEST_PHASE_STOPPED`) and a `stopped` field on `RUN_END`.
- **Re-baselined tests: none.** No existing test file was edited.
- **New tests:** `tests/test_digest_phase_containment.py` (36; 33 in the
  first push, 3 from review round 1):
  - **real time** (6): a raising digest keeps the paid read, exports (with
    `findings.json` carrying the read sheet's finding, run.log and the
    manifest), and a cached re-run renders and reads only the two pages not
    read; a read in flight is kept; a raising progress callback; nothing read
    is a FAILED run;
  - **the phase** (8): a level-1 store failure after every page was reached
    (the line makes no cache promise); a cache whose every write raises loses
    no paid read (real time, batch); an accounting failure (the second usage
    record) still closes the run with a FAILED stage while the other sheets
    keep their usage; an event failure costs only its own page's event; a
    prescan failure leaves every page unread; a cached run keeps every cached
    digest; `KeyboardInterrupt` still ends the run and the spool is removed;
  - **batch submit** (5): a loop failure deletes every upload; the resolved
    slots reach the caller; a failure between an upload and its slot deletes
    it; the upload loop through the pipeline; an inline read survives a submit
    failure;
  - **batch collect** (6): a poll failure reads back the finished batch (and
    the cache); the read-back reaches the caller; a poll failure cancels a
    running batch; a batch it cannot cancel keeps its files; a poll and a
    results failure through the pipeline;
  - **exhaustive and after the phase** (5): Fast and Hybrid stop and release
    the spool; Economy releases every upload; an exception after the phase
    still releases the spool and the retained uploads;
  - **callbacks** (2): a callback that stays broken does not lose the run
    (real time, Economy);
  - **wording and cardinality** (3): the line and the reasons are path-free
    (an exception whose message carries a folder name); one line for every page
    not read; a page that failed on its own keeps its reason;
  - **a clean run is unchanged** (1).

  Against the copy of `origin/main`, classified from `--junitxml`: **29 fail on
  behaviour, 2 only on the new API** (`slots_out`, `results_out`), and **2
  pass**, pinning what the fix keeps: a batch it cannot cancel keeps its files,
  and a clean run is unchanged.
- **Fixture effects, instrumented over the whole fixed suite** (the same hooks,
  diffed test by test against the base run; measured on the first push and
  again after review round 1, with the same result): outside the new file,
  every one of the 402 tests with a record is identical except
  `test_collect_results_error_releases_files_before_propagating`, which gains
  one release of zero files from `_abandon_after_collect_error` (its own
  cleanup already released them). All 303 contexts return with the same
  statuses, errors, unread pages, stages and usage records. Every hook, upload,
  delete, spool and exception count is unchanged. In the new file, 28 contexts
  return and 3 raise (`KeyboardInterrupt` and the two exceptions after the
  phase).
- **Downstream consumers walked:**
  - the merge and the settle; `ctx.errors` (order: the inventory's lines, the
    phase line, page lines, count notes, specification errors);
  - the digest stage (items, status, errors), `SHEET_DIGESTED` / `PAGE_UNREAD`
    / `DIGEST_PHASE_STOPPED`, `RUN_END`;
  - `roll_up_qc_status` (an exhaustive run reads FAILED, a standard run
    NOT_REQUESTED) and `derive_run_outcome` (PARTIAL, or FAILED with nothing
    read);
  - run.log (the stage table lists only the recorded stages, so the digest
    stage; the anchor pass's events stay in the trace, as on a standard run;
    the outcome line reads "PARTIAL — QC incomplete" on an exhaustive run);
    `run_manifest.json`; the export (`findings.json` whenever geometry exists);
  - the GUI (`_on_done`, the issue list); the usage ledger (every paid read
    kept keeps its record);
  - the level-1 and level-2 caches; the critique's own release (now a no-op on
    the second call).
- **Review round 1 (Codex, three findings, all verified and fixed):**
  - **P1, real time:** a level-2 cache `put` that raised inside `digest_sheet`
    after the paid read made the future raise, and the containment skipped it:
    the read and its usage were lost. Reproduced with a cache whose every
    write raises: 1 of 3 reads made and 0 kept. Fixed by making the write
    advisory (logged), as `DigestCache.put` already is.
  - **P1, batch:** the same `put` in `_digest_from_message` failed the collect,
    and the harvest re-parsed through the same cache and failed each item: 0 of
    3 billed items kept. Fixed at the same root (the write is advisory), so the
    collect and the harvest keep every item.
  - **P2, usage:** one `_record_usage` that raised abandoned the rest of the
    usage loop, so later sheets' records were missing (1 of 3 kept). Each
    sheet's usage, and each page's event, is now recorded in its own `try`; the
    first failure still stops the run after the phase.
  - Found while fixing: with a cache that fails every write, the line would
    have promised "cached, so a re-run does not pay for them again". The cache
    clause now needs a level-1 store that did not fail; the level-1 test that
    fails only level-1 writes now expects no promise (it under-claims there,
    since its level-2 writes worked, and is never false).
  - 5 tests failed before the fix for exactly these reasons (the 3 new ones,
    the accounting test's added usage assertion, and the level-1 test's line)
    and pass after it.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **4,402 passed, 2 skipped, 10 deselected**
    (269 s) on `0aa2758`.
  - The new file: 36 passed (33 in the first push). The 41 pinned files:
    2,108 passed, 1 skipped, before and after.
  - Full suite after: **4,435 passed, 2 skipped, 10 deselected** (271 s): the
    baseline plus the 33 new tests, with the same two environment skips. After
    review round 1: **4,438 passed, 2 skipped, 10 deselected** (259 s), the 3
    added tests.
  - The browser suite was not run: no report or JavaScript changed.
  - `ruff check --select E9,F63,F7,F82 src tests scripts` (pinned 0.14.5) is
    clean. F401/F811/F841 over the touched files finds one hit, on `main`
    already: `pipeline.normalize_specs_text` (WP-22.5).
  - `scan_secrets.py` is clean over the tracked files, the new one included.
    `compileall src` passes.
- **Docs:**
  - **CHANGELOG** (Fixed): R1, digest-phase containment.
  - **CLAUDE.md:** a passage after WP-11.1's (*An unexpected error inside the
    digest phase stops the phase, not the run*).
  - **README:** *Resilient inputs* gains the digest-phase paragraph. The
    Economy-mode paragraph's "released on every exit" is corrected to the exits
    that are covered; its "expire server-side" is left for WP-18.4 (N22).
  - **`help_content.py`:** the same correction to the upload bullet.
  - **The plan:** a WP-11.2 note under "Step 4: what containment must do".
  - **DECISIONS:** the D-2 note and the D-5 input note.
  - **PROGRESS:** this entry; the WP-11.2 row; the R1 row; notes on WP-11.3,
    WP-17.1, WP-18.4 and WP-22.1; the Next-up line.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Windows is covered by this PR's CI. The shapes are injected: a
  monkeypatched `digest_sheet`, callback, cache, level-1 store,
  `_record_usage`, poll and `results()`.
- **Risks and residual gaps:**
  - **Visible changes, by design.** A run that used to raise now returns a
    PARTIAL or FAILED context and exports it; the digest stage reads FAILED
    with one line; an exhaustive run's QC status is FAILED and no QC stage is
    recorded; the pages not reached are listed.
  - **A library call with no API key** used to raise `ValueError:
    ANTHROPIC_API_KEY environment variable not set` out of the run (the lazy
    client inside `digest_sheet`). It now returns a FAILED run whose line names
    `ValueError` only; the message is in the diagnostics log. The owner chose
    the type name over the message with this example in front of them. The GUI
    refuses to start a run without a key (`_on_process`), so it never gets
    here.
  - **`KeyboardInterrupt` / `SystemExit` still end the run without a context**
    (by the owner's rule; cancel is WP-17.1's, D-5). The spool and the
    retained uploads are released; a batch in flight is neither cancelled nor
    harvested, and its uploads stay.
  - **A page whose event cannot be built** has no per-page event (pinned);
    every other page keeps its own, and every read its usage.
  - **An exception after the digest phase** still propagates (as before); only
    the release of the spool and the retained uploads is new there.
- **Re-checked (U31):**
  - the critique's own release is unchanged (it now calls the shared helper,
    and a second call is a no-op);
  - the DA-034 direct tests pass unchanged, including the terminal branch's
    own guard;
  - the submit guard deletes the slot in progress, whose upload is not yet in
    `slots`;
  - `_harvest_abandoned_batch` is reused as it is (budget, cache and the N16
    replacement helper);
  - `stream.close()` runs on the rendering thread (PyMuPDF is not thread-safe).
- **Found, not fixed:**
  - **An upload's progress callback that raises loses that file's id.**
    `file_upload.upload_sheet_images` calls `on_image` after an image lands;
    if it raises, the image's id never reaches `by_position`, so the partial
    upload cleanup cannot delete it. With a status sink that keeps raising,
    each uploaded image of each sheet leaks. `ImageProgress`'s comment says the
    callback "never affects the upload result" (WP-18 note).
  - **The collect's error guards release a batch's files while a follow-up or
    resubmission batch may still use them**, and a resubmission in flight at
    the error is neither cancelled nor read back. This is the terminal branch's
    existing guard and the new one alike (WP-17.1 note).
  - **Sixteen stage catch-alls append `str(exc)` to `ctx.errors`**, the
    critique's (`Critique: {exc}`) among them. The exported artifacts scrub it
    (`redact_for_display`), and the GUI's log panel shows it as is (WP-22.1
    note).
  - **A paid read whose `digest_sheet` raised after the API call** for a reason
    other than its cache write (now advisory) leaves no usage record, since the
    exception carries no usage (D-7, WP-14.4).
  - **A stopped run with nothing read** still has a header-only
    `combined_text`, like any run with no digest.
  - **The help text's "expire on Anthropic's side"** and the README's "expire
    server-side" remain (N22, WP-18.4).
- **Next:** WP-16.1 (Wave 1, no dependency), then WP-16.2. WP-11.3 (Wave 2) is
  available and is the last of R1.

### 2026-09-24 — WP-11.1: a source or page that fails after the inventory no longer ends the run ([PR #172](https://github.com/Abe-Borg/drawing-analyzer/pull/172))

- **Slice and IDs:** WP-11.1. R1, the core (implemented+validated); R1 stays
  open for WP-11.2 (digest-phase containment) and WP-11.3 (the revision check
  on reopen). **Contract decided:** D-8's page part (narrowly; WP-06.2
  completes it). D-2 gains a note (the digest stage's eligible items are the
  inventory's pages). No migration-register row: no key, prompt or schema moved.
  **WP-11 is not done:** WP-11.2 and WP-11.3 remain, so there is no package
  acceptance check.
- **Base.** `main` = `origin/main` = `a7dd050`; no drift. Baseline **4,325
  passed, 2 skipped, 10 deselected** (279 s), identical to the WP-01.4 handoff.
  The two skips are IPv6 loopback and chmod as root.
- **Reproduced first** (scratch probes in a `git archive` copy of `origin/main`,
  the suite's fakes and hermetic guard applying; a source "vanished" by being
  unlinked, or locked by a monkeypatched `PermissionError`, inside a wrapper
  around `pipeline.inspect_inputs`), each as the request stated:
  - **Real time**, two one-page sources, the second unlinked: `FileNotFoundError`
    out of `extract_drawing_context` after one paid digest, no context, journal
    or export; with a `DigestCache` it raises before any call; the first source
    unlinked, the same with no call. A locked second source: `PermissionError`
    after two paid digests (two-page sources).
  - **Batch**, two two-page sources, the second unlinked: raises after 4
    uploads, 0 deleted, no batch created; with a cache, at the prescan with no
    upload.
  - **A page whose prescan geometry, identity, word count, page load or text
    extraction raises** (cache on): the whole run raises.
  - **The page count changed after the inventory**, both cache paths: 3 → 2
    reads COMPLETE, `sheet_count` 2, digest items (2, 2), no error line,
    labels "page k/2", the inventory still says 3; 3 → 4 digests four pages,
    COMPLETE.
  - **Every source unlinked**: the zero-sheet exit ("No readable PDF pages
    found") although the journal recorded both files as `INPUT_ACCEPTED`.
  - **The critique** (exhaustive, a source unlinked between the digest and the
    critique): with a cache the stage reads FAILED (items 0/0) through its
    catch-all and its error and `ctx.errors` carry `no such file: '<absolute
    path>'` (the exported artifacts scrub it); without one it reads PARTIAL
    with "N not accounted for", naming no sheet (measured on real time, Hybrid
    and Economy). The markup skip works.
  - **The naive fix** (catch-and-continue in both iterators, a per-page
    continue in the prescan): every abort became a silent COMPLETE (batch,
    second source gone: `sheet_count` 2, digest COMPLETE 2/2, no error, run
    COMPLETE); a failed prescan page read digest PARTIAL (3, 2) with no error
    line and a COMPLETE run.
  - **The denominator alone**: 3 → 2 reads digest PARTIAL (3, 2) with no error
    line, so the run reads COMPLETE; 3 → 4 without a cache raises
    `IndexError` in `_digest_sheets_concurrent`. **Correction to the request:**
    with a cache 3 → 4 reads items **(3, 3)**, not (3, 4): the fourth page is
    digested and billed (4 calls), then dropped by the merge, which builds
    `sheets` from the inventory refs.
  - **The bare rule**: every outcome as the request stated (batch, second gone:
    PARTIAL (4, 2), two page lines, run PARTIAL; 3 → 2 PARTIAL (3, 2) with
    `A.pdf (page 3/3): page could not be rendered (IndexError)`; 3 → 4
    COMPLETE over three pages, the added page unmentioned; every source gone:
    FAILED (2, 0), run FAILED, one line per page; the critique PARTIAL 4/2 "not
    accounted for", naming no sheet).
- **Facts confirmed, not assumed** (an instrumented scratch copy of
  `origin/main`: append-only wrapper blocks at the end of `render.py`,
  `pipeline.py` and `digest_cache.py`, logging behind `WP11_LOG` with the test
  name; the whole suite, 4,325 passed, no outcome changed):
  - **The hooks ran** 1,659 PDF opens (by caller), 395 `list_sheets` calls, 247
    render iterators, 176 prescans, 242 contexts, 239 digest totals, 153
    critique stages, 102 + 55 level-1 partitions, 111 geometry-sink appends,
    1,009 cache gets and 567 puts.
  - **The suite has only 6 page errors**, in 4 tests, all a render-time
    pathological page (`ValueError`); no prescan page failure, no source that
    fails after the inventory, no context that raised, no sink append without a
    record, and the digest's `items_in` equals `sheet_count` in every context.
    So every behaviour this slice changes is guarded only by the new tests.
  - **The render and prescan paths are exercised by 34 test files.**
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, six choices, each as recommended). Measured first: one scratch
  implementation of the core rule with each open choice switchable by
  environment variable, run instrumented over the 34 render-path files plus
  `test_run_journal`, `test_render_telemetry`, `test_drawing_export`,
  `test_drawing_html_report` and `test_drawing_usage` (2,066 tests), diffed
  test by test against the base, and a 28-case table (every required and edge
  case) run through the base, the bare rule and each option:

  | option | pinned tests failing | events moved over the suite |
  |---|---|---|
  | **typed record + a `PAGE_UNREAD` event (chosen)** | **0** | **one event in 3 tests; the critique's degraded line in 2** |
  | typed record only | 0 | the critique's degraded line in 2 |
  | placeholder `SheetDigest` | 0 | 3 tests: `ctx.sheets` +1, `combined_text` "Sheet 1/1" → "Sheet 1/2, 2/2", `SHEET_DIGESTED` +1 |
  | one line per page (vs **per source, chosen**) | 0 | none (no source failure in the suite) |
  | prescan terminal (vs **routed to render, chosen**) | 0 | none |
  | read the extra pages / fail the whole source (vs **read the inventoried pages + a line, chosen**) | 0 | none |
  | critique keeps `list_sheets` (vs **the inventory's pages, chosen**) | 0 | the degraded line reverts |

  The case table decided each choice: a lost 5-page source is 1 line (per
  source) or 5; a failed prescan identity, word count or geometry reads the
  page (COMPLETE 3/3, geometry kept) when routed and loses it (PARTIAL 3/2, no
  geometry) when terminal; 3 → 4 pages reads COMPLETE 3/3 with a run error,
  COMPLETE 4/4 with no word (extra pages billed), or FAILED 3/0 (the whole
  source); the critique over a lost source is COMPLETE 6/6 from the spool or
  retained uploads (real time, Economy) and names each page on Hybrid, or
  FAILED with a raw path / "not accounted for" with `list_sheets`.
  - **An unread page is a typed record plus one event.** Not taken: the record
    without the event; a placeholder `SheetDigest` (it claims a read; the usage
    loop, call counts and the identity corpus would need to skip it, and the
    corpus change re-keys the identity cache for such sets).
  - **One line per source** for a source-level failure. Not taken: one per page.
  - **Prescan failures route to render.** Not taken: terminal in the prescan.
  - **More pages: read the inventoried ones, one line names the source** (the
    run PARTIAL, the stage COMPLETE). Not taken: read the extra pages (the
    denominator moves after the fact); fail the whole source (revision binding
    by page count, WP-11.3's).
  - **Round 2:** D-8's page part decided narrowly (not taken: left open with a
    note); the critique takes the inventory's pages (not taken: keep
    `list_sheets`).
  - **Not asked (stated):** labels keep the inventory's count and the render
    identity the opened file's (so no key moves); a source none of whose pages
    is wanted is never opened; a page neither yielded nor reported still gets
    an `UnreadPage` ("no render outcome was recorded").
- **What changed:**
  - **`render.py`** (still the only PDF importer with `annotate.py`, I-5):
    `SourceUnreadableError` and `PageNotInSourceError` (path-free `str()`),
    `inventory_sheet_refs`, `_expected_count`, `_open_source`;
    `iter_rendered_sheets(..., expected_pages=, on_page_count_changed=)` and
    `iter_sheet_prescan(..., expected_pages=)` as above; without
    `expected_pages` both keep the old contract and raise. Docstrings of
    `list_sheets`, `_classify_input` and both iterators.
  - **`source_registry.py`:** `InputInventory.expected_page_counts()`.
  - **`models.py`:** `UnreadPage` (frozen; `display_label`, `to_dict()`, no
    path); the `SheetRef` docstring.
  - **`pipeline.py`:** the workload from `inventory_sheet_refs` (no
    `list_sheets` call); `_UnreadPages` (`page_failed`, `page_count_changed`,
    `settle`, `lines`, `notes`) and `_unread_reason`, `_page_ranges`;
    `_GeometryOmissionSink(order=)`; `expected_pages` /
    `on_page_count_changed` through `_rendered_stream` and both transports;
    `refs` / `expected_pages` on `_level1_partition`,
    `_critique_level1_partition` and `_run_critique_stage` (its unobtainable
    pages name the reason: `…: no critique input could be obtained: <reason>`);
    the per-sheet loop walks the refs and emits `PAGE_UNREAD` for a page with no
    digest; the digest stage's warnings carry the more-pages line;
    `DrawingContext.unread_pages`.
  - **`run_journal.py`:** run.log's Sheets section (`; N page(s) not read` and a
    `NOT READ` line per page, sanitized with the private roots).
  - **`export.py`:** `unread_pages` in `run_manifest.json`
    (`_unread_page_entries`, through the sanitize boundary).
  - **Not changed:** the digest stage's ladder, `derive_run_outcome`, the
    zero-sheet exit (it remains for a set with nothing accepted), the level-1
    and level-2 keys, `_SCHEMA_VERSION`, every prompt, the report and the GUI.
- **Contracts decided:** D-8's page part; a D-2 note.
- **Cache/schema effects: none.** An unchanged set's refs equal `list_sheets`
  field for field (pinned: `test_refs_equal_list_sheets`), and the render
  identity keeps the opened file's page count (pinned:
  `test_prescan_identity_uses_file_count`), so every level-1 and level-2 key is
  byte-identical: `tests/test_drawing_cache_identity.py` passes unchanged.
  `run_manifest.json` gains one additive key, `unread_pages`.
- **Re-baselined tests: none.** No existing test file was edited; the original
  files pass unchanged against the fixed tree (the full suite below).
- **New tests:** `tests/test_source_page_isolation.py` (77):
  - **the workload:** the refs equal `list_sheets` (same-basename sources, a
    rejected and a duplicate input) and are built with no open;
  - **the iterators:** a missing source reports every expected page (within
    `only`) with one shared error, path-free; a legacy call still raises; a
    source with no wanted page is never opened; fewer pages report
    `PageNotInSourceError`; more pages report the change once and read only the
    expected pages; one bad page keeps the good ones; the prescan skips what it
    cannot scan, raises without `expected_pages`, and keeps the opened file's
    count in the identity; the sink inserts a routed page in page order;
  - **a lost source:** second, first and every source, on real time, batch
    and Hybrid (exhaustive), cold and cached (18), and a locked one (6):
    context and journal, the survivors digested, a record and an event per
    lost page, one source line in `ctx.errors` and the stage's errors, the
    inventory's count, PARTIAL or FAILED, path-free; batch uploads only the
    survivors; the paid digest kept (usage, export, manifest, run.log); every
    source lost is not the zero-sheet exit, which remains for nothing accepted;
    all lost on an exhaustive Hybrid run;
  - **cardinality:** a 5-page source is one line, five records and events; a
    page failure stays per page; the partial wording (`2 of its 5 page(s)`);
    the first outcome wins; an unreached page gets one;
  - **the prescan:** identity, word count and geometry failures are read with
    their geometry; page load and text failures are one render line; a
    render-only failure; a cached source vanishing after the prescan costs
    nothing;
  - **the page count:** fewer and more, real time and batch, cold and cached;
    one line when both the prescan and the render open the source;
  - **the critique:** real time and Economy read a lost source from the
    digest's images (COMPLETE 6/6), Hybrid names each page with its reason,
    the fallback to `list_sheets` for a direct caller, and the run's critique
    never calls it;
  - **surfaces:** the record's `to_dict`, the events in page order and
    `RUN_END`, run.log's Sheets section; an unchanged set is unchanged; a
    cached re-run renders nothing.

  Against a `git archive` copy of `origin/main`, classified from `--junitxml`:
  **54 fail on behaviour, 17 only on the new API** (`expected_pages`,
  `inventory_sheet_refs`, `_UnreadPages`, `UnreadPage`, `order=`), **6 pass**,
  pinning what the fix keeps: both iterators still raise for a caller with no
  inventory, the zero-sheet exit for nothing accepted, the critique's
  `list_sheets` fallback, an unchanged set's output, and a cached re-run that
  renders nothing.
- **Fixture effects, instrumented over the whole fixed suite** (the same hooks,
  diffed test by test against the base run): outside the new file every hook
  ran exactly as often, except `list_sheets` (16 calls, from 395: the pipeline
  and the critique no longer call it) and the PDF opens (1,116, from 1,659: no
  recount; the iterators' opens are 531 against 535, the difference being the
  sources skipped because none of their pages was wanted). No status, item
  count, usage record, QC number, ledger count, cache get or put, page error or
  `ctx.errors` entry moved. What moved: one `PAGE_UNREAD` event in the 3
  fixtures with a page that does not render
  (`test_pipeline_batch_records_an_unrenderable_page`,
  `test_a_sheet_the_critique_cannot_obtain_degrades_its_stage`,
  `test_pipeline_a_sheet_with_no_input_is_skipped`), and in the last two the
  critique's degraded line gains the reason (`…: no critique input could be
  obtained: page could not be rendered (ValueError)`; both assert a
  substring). The gauntlet (`run_acceptance.py`'s oracle) is unchanged.
- **Downstream consumers walked:** `total` (progress, `_resolve_workers`,
  `miss_total`, `results` in `_digest_sheets_concurrent`, which can no longer
  overflow, the critique's `total` and tally, `_run_qc_stages`' progress,
  `sheet_count`, `RUN_END`'s `sheets_total`); the merge; `ctx.sheets`,
  `ok_sheet_count`, `cached_sheet_count` (unchanged in meaning);
  `ctx.errors`; the digest stage (items, status, errors, warnings);
  `SHEET_DIGESTED` and `PAGE_UNREAD`; `derive_run_outcome` (unchanged: an
  error line makes the run PARTIAL, no read sheet FAILED); run.log's Sheets
  section and outcome line; `run_manifest.json`; the export (`00_index.md`'s
  counts and error list, the per-sheet files for read sheets only); the
  report and the GUI (their failed count is `sheet_count - ok`, so an unread
  page counts as failed); the usage ledger (an unread page appends no record);
  the A/B harness (qualifies an arm by stage status; still counts sheets with
  `list_sheets`, unchanged); the gauntlet.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **4,325 passed, 2 skipped, 10 deselected**
    (279 s) on `a7dd050`.
  - The new file: 77 passed.
  - Full suite after: **4,402 passed, 2 skipped, 10 deselected** (310 s): the
    baseline plus the 77 new tests, with the same two environment skips.
  - Browser suite: 98 collected, 98 executed and passed;
    `check_browser_suite.py` passes.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds one hit, on
    `main` already: `pipeline.normalize_specs_text` (WP-22.5).
    `scan_secrets.py` is clean over 212 tracked files, the new one included.
    `compileall src` passes. No invisible code point in the added lines (only
    the em dash, ellipsis and section sign these files already use).
- **Docs:**
  - **CHANGELOG** (Fixed): R1 (core), with the visible effect.
  - **CLAUDE.md:** a passage beside the other `render.py` passages (*The
    inventory's pages are the workload*).
  - **README:** *Resilient inputs* gains a file that fails after it was
    accepted.
  - **The plan:** a WP-11.1 note under "Step 2: no page may vanish".
  - **DECISIONS:** D-8's page part and the D-2 note.
  - **PROGRESS:** this entry; the WP-11.1 row; the R1 row; notes on WP-11.2,
    WP-11.3, WP-06.2 and WP-15.1; the Next-up line.
  - **Docstrings:** `list_sheets`, `_classify_input`, both iterators,
    `SheetRef`, `_rendered_stream`, `_GeometryOmissionSink`, both digest
    transports, both level-1 partitions, `_run_critique_stage`.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). A real network-share drop or antivirus lock was not reproduced; the
  shapes are an unlinked file and a monkeypatched `PermissionError`. Windows is
  covered by this PR's CI (every loss happens while no document is open on it).
- **Risks and residual gaps:**
  - **Visible changes, by design.** A run that used to raise now returns a
    PARTIAL or FAILED context; a source rewritten with more pages makes the run
    PARTIAL with one line, and one with fewer pages makes it PARTIAL with the
    missing pages named; the digest stage counts the inventory's pages;
    run.log's Sheets section, the manifest and the event trace list unread
    pages; the critique names an unobtainable page's reason.
  - **Same-count rewrites are still read without a word** until WP-11.3 (the
    markup's `detect_mutations` flags them; a standard run does not).
  - **Other exceptions inside the digest phase still lose the paid results,
    uploads and spool** (WP-11.2).
  - **Two sources with one basename** give two identically named source lines
    ("M-101.pdf: …"); the records and events carry the source id. Labels were
    already ambiguous that way (N6, WP-06.2).
- **Re-checked (U31):** the pathological page keeps its behaviour (the
  iterator dimension-checks before rasterizing; pinned tests unchanged); the
  inventory's accepted ids equal `list_sheets`' (`assign_source_ids` over the
  accepted paths); the prescan's stat-gated re-hash (§10.6) and the level-1
  keys are untouched; `iter_region_crops` and `iter_sheet_cost_bases` were
  already guarded and are unchanged.
- **Found, not fixed:**
  - the GUI's pre-run sheet count still reopens every file with `list_sheets`
    on the UI thread (N24) and skips a file it cannot open silently, so it can
    disagree with the run's count for such a file (WP-15.1 note);
  - `scripts/measure_evidence_coverage.py` could pass `expected_pages` and drop
    its `list_sheets` workaround (out of scope; `test_evidence_coverage.py`
    unchanged and green).
- **Next:** WP-11.2 (Wave 1; its dependency is this slice). WP-11.3 (Wave 2) is
  now available.

### 2026-09-24 — WP-01.4: a critique read the model did not finish is not a completed read ([PR #171](https://github.com/Abe-Borg/drawing-analyzer/pull/171))

- **Slice and IDs:** WP-01.4. N4, the critique part (implemented+validated);
  N4 stays open for WP-10.4's cache map. No `DECISIONS.md` contract is newly
  decided (D-1 and D-2 were); D-1 gains a note (the critique adopts the
  classifier), D-2 a note (the critique stage adopts the item rule), D-4 a
  note and one migration-register row (`_CRITIQUE_CACHE_CONTRACT` 2 → 3), and
  D-4's "Still open, for WP-10.4" no longer names this slice. **WP-01 is not
  done:** WP-01.5, WP-01.6 and WP-01.7 remain, so there is no package
  acceptance check.
- **Base.** `main` = `origin/main` = `feb85b4`; no drift. Baseline **4,195
  passed, 2 skipped, 10 deselected** (242 s), identical to the WP-01.3 handoff.
  The two skips are IPv6 loopback and chmod as root.
- **Reproduced first** (probes in a `git archive` copy of `origin/main`, the
  suite's fakes and hermetic guard applying), each as the request stated:
  - **Real time, `runs=2`, both reads alike:** a closed findings block, an
    explicit `{"findings": []}` and an unclosed block with complete JSON are
    each COMPLETE, merged 2/2 and cached at level 2 under every stop reason
    tried: `end_turn`, `stop_sequence`, `max_tokens`,
    `model_context_window_exceeded`, `refusal`, `None`, `pause_turn`,
    `tool_use`, `compaction` and an unknown string (30 of 30).
  - **Batch:** `_outcome_from_envelope` on a `succeeded` dict-shaped message
    with a closed block is COMPLETE for `end_turn`, `max_tokens`, `refusal`,
    `None` and a missing `stop_reason` key.
  - **Through the pipeline** (exhaustive, one sheet, a shared cache): read 2
    cut off at `max_tokens` (a closed block), read 2 refused (an empty block),
    both `max_tokens`, both `None`: the critique stage and the run read
    COMPLETE, both levels are stored, and the warm run makes no critique call
    and reads COMPLETE.
  - **The gap:** read 2 raising a 400 beside a read 1 with findings: stage and
    run COMPLETE, nothing cached, the usage record COMPLETE, and the warm run
    re-critiques (two calls) and reads COMPLETE again.
- **Facts confirmed, not assumed** (an instrumented copy of `origin/main`,
  append-only wrapper blocks at the end of `critique.py`, `batch_critique.py`,
  `digest_cache.py` and `pipeline.py`, logging with the test name; the whole
  suite, 4,195 passed, no outcome changed):
  - **The hooks ran** 440 critique reads, 215 merges, 40 batch envelopes, 69
    critique cache gets and 37 puts, 195 critique usage records, 112 critique
    stage calls, 198 contexts and 2,775 stage records.
  - **No fixture has an unfinished read with content.** Of the 440 reads, 389
    finished and parsed, 48 finished and failed their parse, and 3 stopped at
    `max_tokens` with an empty body (the `_EmptyBodyClient` tests). No read is
    structured: every structured-outputs test latches off before its read
    parses, so the structured cases are new tests.
  - **Pinned tests under the bare rule:** none moves when the rule goes
    through the digest's ladder, whose order (a refusal, then an empty reply,
    then the rest) keeps `empty critique (stop_reason='max_tokens')` for the
    three empty reads. (The request measured one wording move for a rule that
    tested the stop reason before the emptiness.)
  - **Short results:** 30 over the suite, 4 of them the gap's shape (one read
    failed, the other shipped findings, `error=None`), all unit-level; no
    pipeline fixture has one, which is why no stage rule moves a pinned test.
  - **Readers of the stage's `items`:** the journal's `STAGE_END`, `run.log`'s
    stage table, the report's stage table and `run_manifest.json`; no test
    pins the critique's, and no script reads them (grep over `scripts/`).
  - **The A/B harness** buckets a usage record by `terminal_status` (PARTIAL
    and FAILED are both "failed") and qualifies an arm by `qc_status`;
    `RECORD_CONTRACT_VERSION` concerns stored signatures and stays 3.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, six choices, each as recommended). Measured first: each option
  applied in its own instrumented scratch copy over the 30 test files that
  exercise the critique (1,621 tests), diffed test by test against the base,
  and a 19-case table run through the pipeline on both transports:

  | option | pinned tests failing | events moved |
  |---|---|---|
  | the bare rule through the ladder (A) | 0 | 0 |
  | A + degrade a short sheet in `_ingest_miss` | 0 | 0 |
  | A + `CritiqueResult.error` for a short sheet | 1 (`test_one_failed_run_still_merges_the_other`) | 4 unit results gain an error |
  | **A + D-2's item rule (chosen)** | **0** | **12 all-failed critiques PARTIAL → FAILED** |
  | **+ the usage record agrees (chosen)** | **0** | **those 12 sheets' records PARTIAL → FAILED** |

  The case table: on the base every unfinished shape read COMPLETE and was
  cached (warm: 0 calls); the bare rule alone stopped the caching but left
  12 shapes of "one read finished, one failed" reading COMPLETE (9 of them new
  with the rule); the chosen rules read those PARTIAL, a sheet with no counted
  read FAILED, cache nothing and re-read once on the warm run (then COMPLETE),
  identically on both transports.
  - **A read the model did not finish keeps nothing** (like a malformed read;
    tokens billed). Not taken: held out and counted; held out, counted and
    listed (the N15 surfaces; the critique has none per sheet); merged, marked
    `NOT_ASSESSED_PARTIAL`.
  - **The stage adopts D-2's item rule.** Not taken: degrading in
    `_ingest_miss` only (all-failed stays PARTIAL); through
    `CritiqueResult.error` (moves one pinned test); today's rule.
  - **The usage record agrees.** Not taken: reading `res.error` alone.
  - **One ladder: a `noun` parameter on `digest.digest_terminal_error`.** Not
    taken: moving the ladder into `core.terminal_outcome` (the classifier
    module would read the reply's text as well as its stop reason).
  - **Round 2:** no stored per-read stop reasons (not taken: storing them
    additively); the stage's items are reads, eligible → judged (not taken:
    keeping the finding count).
  - **Not asked (conformed):** what a critique read that did not finish is
    (D-1: only `FINISHED`; the critique declares no tools, so a continuation
    is not finished either); the bump itself (the row and D-4 had chosen it).
- **What changed:**
  - **`digest.py`:** `digest_terminal_error(raw_text, stop_reason, *,
    noun="digest")`; the digest's calls and wording are unchanged.
  - **`critique.py`** (still imports no PDF engine; the critique emits no
    prose, so `combined_text` cannot move, I-2): `outcome_from_message` asks
    the ladder first, with `noun="critique"`, and a read it fails keeps no
    findings and no claims; `CritiqueResult.read_errors` (runtime-only),
    filled by `result_from_outcomes`; `critique_shortfall` (new: the result's
    `error` when set, else `<n> of <m> critique read(s) finished: <errors>`);
    docstrings (the module, `CritiqueRunOutcome`, `CritiqueResult`,
    `critique_cache_entry_from_result`, `outcome_from_message`,
    `result_from_outcomes`, the level-2 store comment).
  - **`batch_critique.py`:** docstring of `_outcome_from_envelope` and the
    cache-put comment (no code change: the envelope already hands a
    `succeeded` message to the shared parser).
  - **`digest_cache.py`:** `_CRITIQUE_CACHE_CONTRACT` 2 → 3 with its history
    entry; the contract comment and both builders' docstrings name the
    admission as part of what the term versions.
  - **`pipeline.py`:** `_CritiqueReadTally` (new; judged, failed, skipped,
    eligible, `coverage_note`); `_run_critique_stage` takes a `read_tally`
    sink, counts every sheet (hits, ingested results, raised calls, sheets
    with no input), and degrades a short sheet through `critique_shortfall`;
    `_record_critique`'s `terminal_status`/`parse_success` follow the same
    rule; the critique stage (recorded in `extract_drawing_context`, with the
    other pre-ledger stages; the session request placed it in
    `_run_qc_stages`) applies `item_coverage_status`, sets items to reads, and
    leads its warnings with the coverage line (a stand-in stage with no counts
    keeps the old rule).
  - **Not changed:** `models.FINDINGS_PARSE_OK`, `_SCHEMA_VERSION` (10), the
    merge rule (fingerprint `63dbfe17…`), the three cache writers' code, the
    critique prompt and its structured-outputs contract, the batch
    transport's `structured=False`, `core.terminal_outcome`.
- **Contracts decided:** none newly; notes on D-1, D-2 and D-4.
- **Cache/schema effects:** `_CRITIQUE_CACHE_CONTRACT` 2 → 3, one
  migration-register row. Every critique entry written under 2 misses once
  and stays on disk; the next exhaustive run re-critiques each sheet once
  (no release shipped contract 1 or 2, so a 1.7.0 install pays one cold pass
  for all three bumps). Digest, identity, review-plan, citation and
  investigation keys are byte-identical (pinned, with the contract-2 critique
  keys). The entry's shape is unchanged. The merge-rule fingerprint is pinned
  under 3, unchanged.
- **Re-baselined tests: none.** The one edit to a pinned file adds a data row:
  `_MERGE_RULE_BY_CRITIQUE_CONTRACT[3]` in `tests/test_drawing_cache_identity.py`
  (the unchanged fingerprint), without which
  `test_the_critique_contract_is_pinned_to_the_merge_rule` fails, as designed.
  Checked both ways:
  - the original test files of `origin/main`, unedited, against the fixed
    source: **1 failed, 4,194 passed, 2 skipped**, the one failure being that
    ratchet test;
  - the new tests against a `git archive` copy of `origin/main`, classified
    from `--junitxml`: of the 128 in the new file, **101 failed on
    behaviour, 11 only on the new API** (the ladder's `noun` in its 9 unit
    tests; `read_errors` in a keeps-test), **16 passed**; the two new
    cache-identity tests failed on behaviour. The passes pin what the fix
    keeps: a finished read on both stop reasons and all three bodies, fenced
    and structured, a finished malformed read still failing its parse, a
    finished `{"findings": []}` still a clean read on real time, batch and
    through the pipeline, and the digest's wording.
- **Fixture effects, instrumented over the whole fixed suite** (the same hooks,
  diffed test by test against the base run, multisets per test since the
  pools finish in thread order): outside the new tests every hook ran exactly
  as often (440, 215, 40, 69, 37, 195, 112, 198, 2,775), and no read outcome,
  merge, claim, cache get or put, `qc_status`, ledger count, QC number,
  `ctx.errors` entry or other stage moved. What moved, all by the owner's
  rules: the critique stage's items in 107 records (now reads), 12 all-failed
  critiques PARTIAL → FAILED (fakes whose critique reply has no findings
  object, or raises), those 12 tests' usage records PARTIAL → FAILED, and the
  coverage line on 14 records (those 12, the gauntlet's `critique_read2` and
  the sheet with no input, both PARTIAL before and after). The gauntlet
  (`run_acceptance.py`'s oracle) keeps every status.
- **New tests:** `tests/test_critique_terminal_outcome.py` (128) and two in
  `tests/test_drawing_cache_identity.py`:
  - **The ladder:** the critique's wording for every non-finished kind, the
    order (a refusal named when empty, an empty reply still `empty
    critique`), the digest's wording unchanged.
  - **One read** (`outcome_from_message`): every non-finished stop reason ×
    three bodies fails, keeps nothing and bills its tokens and cache tokens;
    the structured bare object likewise; a dict reply with no stop reason; the
    finished reads unchanged.
  - **Real time:** both reads cut (not cached, tokens summed), one read cut
    (the survivor `NOT_ASSESSED_PARTIAL`, `read_errors`, no claim, not
    cached), a finished empty read beside a cut one, a single-read run, the
    structured contract (the schema sent, the cut read failed), finished reads
    merging, caching and served, finished empty reads a clean sheet.
  - **Batch:** the envelope for every kind, dict shapes and a missing key,
    one read cut through `collect_critique_batch`, both cut, finished reads
    cached and served.
  - **The pipeline, both transports:** one read cut, refused, ended early or
    unknown (PARTIAL, items 2 → 1, the coverage line, the sheet named with
    the read's error, the `ctx.errors` summary, no finding or arithmetic claim
    from the cut read, the survivor partial, the usage record PARTIAL with
    both reads billed, nothing cached, the warm run reading both again and
    COMPLETE), both cut (FAILED, 2 → 0), the 400 gap, every read raising,
    finished reads (COMPLETE, 2 → 2, both levels cached, the warm run served
    from the cache with its reads counted), finished empty reads, two sheets
    with one cut (4 → 3), a sheet with no input (skipped), and an entry stored
    under contract 2 (missed, re-read, left on disk).
  - **The cache identity:** every critique key moves off contract 2 and no
    other key moves; a contract-2 entry misses and is never deleted.
- **Downstream consumers walked:**
  - **`result_from_outcomes`:** merges only the counted reads; the survivor's
    findings are `NOT_ASSESSED_PARTIAL`; `error` keeps its meaning (none
    counted, or none found anything); `read_errors` is new.
  - **Both cache levels, both transports:** the real-time level-2 store, the
    batch level-2 put and the level-1 store-under-both keep their conditions,
    which now exclude a result with an unfinished read (pinned per level).
  - **`_ingest_miss`'s degraded list, the stage's status, items, warnings and
    errors, `ctx.errors`:** as decided; the summary line is unchanged.
  - **`_record_critique`:** agrees with the stage.
  - **The claims and the arithmetic auditor:** a failed read's claims never
    reach it (pinned end to end with a mismatching claim in the cut read).
  - **The ledger ingest:** only the counted reads' merged findings.
  - **`run.log`, the report's stage table, `run_manifest.json`:** the items
    (reads) and the coverage line, through the stage record; no renderer
    changed.
  - **The A/B harness** and **the gauntlet:** above; unchanged in behaviour.
  - **`critique_sheet`** (the 5-tuple shim): its `err` now names an
    unfinished read.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **4,195 passed, 2 skipped, 10 deselected**
    (242 s) on `feb85b4`.
  - The new tests and the cache-identity file: 160 passed; the 30
    critique-exercising files: 1,623 passed, 1 skipped.
  - Full suite after: **4,325 passed, 2 skipped, 10 deselected** (252 s): the
    baseline plus the 130 new tests, with the same two environment skips.
  - Browser suite: 98 collected, 98 executed and passed;
    `check_browser_suite.py` passes.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds three hits,
    all on `main` already: `critique.DEFAULT_DIGEST_MAX_TOKENS` and
    `pipeline.normalize_specs_text` (listed on WP-22.5) and `SheetRef` in
    `tests/test_drawing_cache_identity.py` (new to the list, added to WP-22.5).
    `scan_secrets.py` is clean over the tracked files, the new one included.
    `compileall src` passes. No invisible code point in the added lines (only
    the em dash, ellipsis, arrow, section sign and × these files already use).
- **Docs:**
  - **CHANGELOG** (Fixed): N4, critique part, with the visible effect (what a
    cut-off or refused read reports, the stage's reads, the one re-critique
    per sheet on the next exhaustive run).
  - **CLAUDE.md:** the item-coverage sentence (the critique is the second
    stage on it), the *Finders* passage on `critique.py`, the contract value
    ("3 since remediation WP-01.4"), I-6, and the `core/` paragraph (the
    classifier's adopters).
  - **README:** the QC-status overview, a pointer from *A reply the model did
    not finish*, the critique's *Self-consistency* paragraph, a new *The
    critique stage counts reads*, and the cache paragraph (the third one-time
    re-critique).
  - **The plan:** a WP-01.4 note under "Step 4: critique" (the term existed;
    the gap as a consumer the step did not name; the owner's rules).
  - **DECISIONS:** the D-1, D-2 and D-4 notes, "Still open, for WP-10.4", and
    the register row.
  - **PROGRESS:** this entry; the WP-01.4 row; the N4 row; notes on WP-01.5,
    WP-10.4, WP-14.5 and WP-22.5; the Next-up line.
  - **Docstrings and comments:** as listed under "What changed", and the
    `_CRITIQUE_CACHE_CONTRACT` history ("3 (remediation WP-01.4, N4): …").
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). How often a real critique read is cut off, refused or ends early is
  not measurable without real sets (O-10); the shapes are the suite's fakes.
  Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **Visible changes, by design.** A sheet whose critique read was cut off,
    refused or ended early (or whose read failed outright beside a finished
    one) holds the critique stage and the run's QC status below COMPLETE, and
    is read again, and billed, on each run until a run finishes both reads. A
    critique in which no read counted reads FAILED, not PARTIAL. The stage's
    items count reads, not findings. The first exhaustive run after upgrading
    re-critiques every sheet once.
  - **A cut-off read's findings are dropped** (the owner's rule), where a
    listing would have kept them visible; the finished read's findings still
    ship, marked partial.
  - **No raised-cap retry for a cut-off critique read** (not in the row;
    recorded on WP-01.5).
  - **The three critique cache writers spell one admission predicate three
    ways** (equivalent today; recorded on WP-10.4).
- **Re-checked (U31):** "the single fix site is `outcome_from_message`; real
  time, batch, L1 and L2 all flow through it" holds (the upload-failure
  fallback is `critique_sheet_self_consistent`, the real-time path); "do not
  change `FINDINGS_PARSE_OK`" holds (a finished critique read can still be
  salvaged as `PARSED_UNCLOSED`, pinned); "critique entries carry no
  `stop_reason`" holds, so the term, not a read-side reject; D-1's classifier,
  the digest's ladder wording and admission, the merge rule and
  `_SCHEMA_VERSION` are untouched.
- **Found, not fixed:**
  - F401: `SheetRef` imported unused in `tests/test_drawing_cache_identity.py`,
    on `main` already (WP-22.5 note);
  - the `critique.py` module docstring still says the merge "deduplicates by
    position and text", stale since WP-03.7 (WP-22.5 note);
  - the three spellings of the critique's admission predicate (WP-10.4 note).
- **Next:** WP-11.1 (Wave 1; no dependency). WP-10.4 (Wave 2) is now
  available.

### 2026-09-24 — WP-01.3: a retry never loses a better read; an unfinished read's findings stay out of the review ([PR #170](https://github.com/Abe-Borg/drawing-analyzer/pull/170))

- **Slice and IDs:** WP-01.3. N16 and N15 (implemented+validated). No
  `DECISIONS.md` contract is decided (none of D-1 … D-8); D-1 gains a note (the
  rule on which read a sheet keeps extends the digest's handling) and D-2 a
  note (the held-out count is observational). No migration-register row: no
  cache contract, key, prompt or schema moved. **WP-01 is not done:** WP-01.4
  … WP-01.7 remain, so there is no package acceptance check.
- **Base.** `main` = `origin/main` = `b4d275f`; no drift. Baseline **4,120
  passed, 2 skipped, 10 deselected** (253 s), identical to the WP-09.2 handoff.
  The two skips are IPv6 loopback and chmod as root.
- **Reproduced first** (a probe on `b4d275f` with the suite's fakes), each as the
  request stated, and two more batch losses:
  - **N16, real time.** A first read cut off at `max_tokens` with prose and a
    findings block (closed, or unclosed and salvaged as `PARSED_UNCLOSED`),
    then a retry that returns empty, refused (with or without text),
    unfinished (`None`), truncated again or an unknown stop: the sheet carries
    the retry's text, findings, stop reason and error, and the first read is
    gone although both were billed (tokens 400/80 summed). A retry that raises
    keeps the first read (the pinned test).
  - **N16, batch.** Through `collect_drawing_batch` on both recovery transports,
    the direct rescue and `_recover_via_batch_resubmit`: every returned read
    replaced the first read wholesale (the usage attempts were kept). **Not in
    the request:** a resubmission that comes back as an *errored envelope*
    (`invalid_request_error`) replaced it too, where real time keeps the first
    read on a raise; and the abandoned-batch harvest read a stalled item back
    cut off with prose, parked only its usage and dropped the read, so a rescue
    that came back worse lost it, and one that raised left "drawing batch not
    collected (stalled)". Multi-round (primary `api_error`, round 1 cut off with
    prose, round 2 refused, empty or errored) lost round 1's prose.
  - **N15.** The gauntlet mini set with M-102's digest ending `max_tokens`,
    `refusal`, `None` or `model_context_window_exceeded` after a complete
    findings block: on an exhaustive run its finding became `QC-004`, anchored
    EXACT, VERIFIED and clouded; on a standard run `QC-002`, in `findings.json`.
  - **Correction to the session request.** Line 1566 of `batch_digest.py` is not
    the inline fallback: it is `_resubmit_failed_items`' follow-up-batch loop.
    The inline fallback (`submit_drawing_batch._serve_inline`) calls
    `digest_sheet`, so the real-time fix covers it.
- **Facts confirmed, not assumed** (an instrumented scratch copy of
  `origin/main`, the whole suite, with the test name; 4,120 passed, the
  instrumentation changed no outcome):
  - **The hooks ran** 333 `digest_sheet` results, 8 real-time raised-cap
    retries (7 tests), 141 batch replacements (primary collect 93, direct
    rescue 21, fresh-batch rounds 16, harvest 6, follow-up batch 5), 133 batch
    parses, 1 parked harvest (content-free), 101 collects, 189 ingests, 262
    numberings, 189 digest-stage records and 189 contexts.
  - **No fixture has two reads that differ.** All 8 real-time retries return
    the same content twice; of the 141 replacements, a rule could change the
    choice only in 5 follow-up-batch events (empty after empty, errored after
    errored), and only a rule that keeps the earlier read on a tie does.
  - **No fixture ingests an errored digest's findings:** 0 of 189 ingests
    (12 had an errored sheet, all with 0 findings).
  - **Caches.** An errored digest is never cached at either level
    (`digest_cache_admits` requires no error and a finished stop reason), and
    `cache_entry_from_digest` serves only finished reads; so neither fix needs
    a key, contract or `_SCHEMA_VERSION` change. Pinned for both transports
    (`test_a_kept_partial_read_is_never_cached`).
  - **Readers of `SheetDigest.findings`:** the ingest, `cache_entry_from_digest`
    (finished reads only) and the `SHEET_DIGESTED` journal count. Every other
    consumer that turns a digest into review content skips an errored sheet:
    `_combine`, cross-QC, the prose harvest, synthesis, focus, the review
    planner. The exception is the advisory set-identity corpus (below).
  - **Nothing parses the digest error strings** (grep over `src`), so naming a
    discarded attempt in them is safe for code; only tests pin them.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, with measured options). Chosen, each as recommended:
  - **Which read a sheet keeps: one rank, the later read wins a tie.**
    Measured with each rule applied over the 25 digest-exercising test files
    (1,405 tests):

    | rule | pinned tests failing | downstream events moved |
    |---|---|---|
    | finished only (A) | 1 (`test_rescue_skipped_when_followup_rejects_permanently`) | 0 |
    | first wins ties (A2, the literal reading) | 0 | 0 |
    | **rank, later wins ties (B, chosen)** | **0** | **0** |
    | rank, first wins ties (C) | 1 (the same) | 0 |
    | the request's literal order (P) | 0 | 0 |
    | hold N15 out | 0 | 0 |

    Through the 18-case table: A loses the retry's content whenever the first
    read was empty (4 cases); A2 and C keep the smaller-cap read of two
    partials; P lets an empty read replace an unfinished read with prose. Not
    taken: A, A2. Not offered: a union of both reads' findings (two
    transcriptions of one sheet beside prose that describes only one).
  - **The error names both** (`; retry: <its error>`; `; retry failed:
    <error>` for a raise). Not taken: the kept read's own error with the retry
    only in the diagnostics log (on real time the retry would then appear
    nowhere in the export). One pinned test re-baselined, approved.
  - **The harvest holds a partial read.** Not taken: deferring it to WP-01.5.
  - **N15: hold out, listed in the sheet's file.** Not taken: hold out and
    count only; label them (a new `Finding` field, a markup prefix, a report
    note, a CSV column that re-baselines
    `test_findings_csv_provenance_columns_appended_at_tail`, a ledger merge
    rule for the label, and the prose harvest's skip left disagreeing); split
    by kind.
  - **Round 2:** the count is an observational warning (not taken: the
    manifest and sheet line only); the findings are listed in the sheet file
    **and** its report card (not taken: the sheet file only); several
    discarded attempts read `; N retries, the last: …` (not taken: every one,
    which grows with `DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS`; only the
    latest).
- **What changed:**
  - **`digest.py`** (still imports no PDF engine; the prose is never spliced,
    I-2): `_read_rank` and its four ranks, `_name_discarded_retry`,
    `keep_digest_read` (the one helper), `is_partial_read`,
    `note_failed_retry`; `SheetDigest.read_error` and `retries_discarded`
    (runtime only); `digest_sheet` builds each reply as a read (`_read_of`)
    and keeps the better one, names a raised retry, sums both attempts' usage
    onto the kept read, and admits to the cache only a finished kept read.
  - **`batch_digest.py`:** `_replace_result_with_attempt_history(...,
    served_by=)` keeps the better read (merging every attempt record onto it)
    and sets `served_by` only for the kept read; its five callers pass
    `served_by` instead of setting it first; the direct rescue names a rescue
    call that raised on the read it keeps; the harvest holds a partial read
    through the helper and parks the rest; the stalled path's rescue list comes
    from `harvest.resolved`. Docstrings of the helper, the rescue, the harvest,
    `_park_usage_attempts` and `_resubmit_failed_items`.
  - **`models.py`:** `review_findings` / `held_out_findings` (duck-typed, one
    split on `sd.error`).
  - **`pipeline.py`:** the ingest takes `review_findings`;
    `DrawingContext.digest_findings_held_out`; the per-sheet loop adds
    `findings_held_out` to `SHEET_DIGESTED` and fills the count; the digest
    stage's warning; the `_run_qc_stages` docstring.
  - **`export.py`:** `_sheet_document` lists held-out findings after the prose
    (`_held_out_line`); `run_manifest.json` gains `digest_findings_held_out`
    (`_held_out_summary`: `{"total", "by_sheet"}`, portable keys, counts only).
  - **`html_report.py`:** `_held_out_block` on the sheet card (escaped,
    `data-category="other"`). **`run_journal.py`:** the *Sheets* line says
    "N finding(s) held out of the review".
- **Contracts decided:** none of D-1 … D-8; a D-1 note and a D-2 note.
- **Cache/schema effects: none.** Admission is unchanged: only a finished read
  is stored, at either level, whichever read a sheet keeps (pinned on both
  transports). The new `SheetDigest` fields are never serialized.
  `run_manifest.json` gains one additive key; `findings.json` and
  `findings.csv` are unchanged in shape.
- **Re-baselined tests: one**, approved:
  `tests/test_drawing_digest.py::test_a_failed_retry_keeps_the_truncated_first_read`
  (its expected error gains `; retry failed: permanent 400 on the raised cap`;
  every other assertion is unchanged). Checked both ways:
  - the original pinned files, unedited, against the fixed tree (the 25 files
    that exercise the digest, plus `test_drawing_usage`, `test_run_journal`,
    `test_drawing_export`, `test_drawing_html_report`): **1 failed, 1,659
    passed, 1 skipped**, the one failure being that test;
  - the new file against a `git archive` copy of `origin/main`, classified from
    `--junitxml`: **33 failed on behaviour, 28 only on the new API**
    (`keep_digest_read`, `ctx.digest_findings_held_out`,
    `html_report._held_out_block`, `export._held_out_summary`), **14 passed**.
    The passes pin what the fix keeps: a later partial read still replaces a
    partial one (real time ×4, batch ×2), a finished retry wins and is cached
    (×3), an empty first read takes the retry (×3), the fresher error of two
    content-free reads, and a content-free harvested read still parked.
- **Fixture effects, instrumented over the whole fixed suite** (the same hooks
  as wrappers at each module's end, diffed test by test against the base run):
  outside the new file, events moved in **two tests**:
  `test_a_failed_retry_keeps_the_truncated_first_read` (re-baselined) and
  `tests/test_drawing_batch.py::test_rescue_failure_keeps_the_batch_error`,
  whose kept batch error now reads `api_error: Internal Server Error; retry
  failed: still broken` (it asserts a substring, unchanged). A third,
  `test_rescue_stops_instead_of_sleeping_past_the_budget`, calls the rescue
  directly: sheet 0's error now names the budget-stopped rescue (`; retry
  failed: 503 service unavailable (…)`); it asserts object identity, which
  holds. No ledger count, QC number, digest-stage status, ok-sheet count,
  error list or usage record moved anywhere else; every hook ran as often as in
  the base run (333, 262, 189, 189, 189, 133, 101), and all **148 read choices
  outside the new file keep the later read, as before**. The gauntlet
  (`run_acceptance.py`'s oracle) is unchanged.
- **New tests:** `tests/test_digest_partial_reads.py` (75):
  - **N16, real time:** a worse retry (empty, refused with and without text)
    keeps the first read, whole, named, both attempts billed, for a closed and
    a salvaged block; a raise is named; partial retries (truncated again,
    ended early, unknown, context window) and a finished retry win; an empty
    first read takes the retry; never spliced.
  - **N16, batch:** on both recovery transports, a worse follow-up or
    fresh-batch round (empty, refused, an errored envelope) keeps the first
    read with every attempt; a partial or finished round wins (cached); the
    direct rescue landing worse or raising; two discarded rounds counted; the
    best read kept across rounds; the fresher error of two content-free reads;
    the harvest holding a partial read against a worse rescue (four variants)
    and an unreached one, and parking a content-free one.
  - **The helper:** a 20-case table, and a finished read never named.
  - **N15, through the pipeline:** an exhaustive run with each of four
    unfinished stops (held out of the ledger, markups, `findings.json`,
    `findings.csv`, `markup_manifest.json` and the report's rows; listed in the
    sheet file and report card; counted in ctx, the stage warning, run.log and
    the manifest); a standard run; a finished run holds nothing out; with N16,
    the kept first read's findings held out.
  - **Units:** the report card escapes, the sheet file's layout, the run.log
    line, the manifest summary (five shapes).
  - **Caches:** a kept partial read is never cached, real time and batch.
- **Downstream consumers walked:**
  - **The digest stage** (status, `items_out`, errors): unchanged in status
    (a kept partial read is still a failed sheet); its errors carry the named
    attempt; one new warning when findings were held out.
  - **`ok_sheet_count`, `ctx.errors`:** counts unchanged; an error string can
    carry a named attempt.
  - **`combined_text` (`_combine`):** unchanged (the failure line quotes the
    error, which may now name the retry).
  - **The per-sheet export (`_sheet_document`):** the kept read's prose, the
    named error, and the held-out list.
  - **The report:** the sheet card's Failed badge and prose as before, plus the
    held-out block; the findings table never includes them.
  - **The usage ledger and its attempts:** real time sums both attempts onto
    the kept read (one record, as before); batch merges every attempt record
    onto the kept read (pinned: `BATCH` / `BATCH` / `REAL_TIME` in order).
  - **The level-1 store:** unchanged predicate; a kept partial read is not
    stored.
  - **The ledger ingest, QC numbering, markups, exports:** an errored sheet
    contributes no findings; nothing else moves (instrumented).
  - **`run.log`, `run_manifest.json`:** the error, the `SHEET_DIGESTED`
    field, the *Sheets* line, the stage warning, the manifest key.
  - **The gauntlet:** no digest sabotage in it; unchanged.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **4,120 passed, 2 skipped, 10 deselected**
    (253 s) on `b4d275f`.
  - The new file: 75 passed.
  - Full suite after: **4,195 passed, 2 skipped, 10 deselected** (254 s): the
    baseline plus the 75 new tests, with the same two environment skips.
  - Browser suite (the report card changed): 98 collected, 98 executed and
    passed; `check_browser_suite.py` passes.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds only two
    hits, both on `main` already: `pipeline.normalize_specs_text` (listed on
    WP-22.5) and `SheetDigest` in `tests/test_drawing_digest.py` (new to the
    list, added to WP-22.5). `scan_secrets.py` is clean over 210 tracked files,
    the new one included. `compileall src` passes. No invisible code point in
    the added lines (only the em dash, ellipsis and middle dot these modules
    already use).
- **Docs:**
  - **CHANGELOG** (Fixed): N16 and N15, with the visible effect, the rule, the
    named error, the harvest, the listing and counts, and no cache effect.
  - **CLAUDE.md:** the digest-path passage (the retry sentence is replaced by
    the rank rule) and the harvest sentence; the ledger passage (the N15
    ingest rule); the N16 entry removed from "Known-inaccurate statements".
  - **README:** "A reply the model did not finish" gains *A retry never costs a
    sheet a better read* and *The findings of an unfinished read are held out
    of the review*; "Stuck batches" says a cut-off read with content is kept
    for its sheet.
  - **The plan:** WP-01.3 notes under the N15 bullet of "Step 3" and under
    "Step 5: retries (N16)" (the two extra batch losses; the requirement as
    decided).
  - **DECISIONS:** the D-1 note and the D-2 note.
  - **PROGRESS:** this entry; the WP-01.3 row; the N15 and N16 rows; notes on
    WP-01.5, WP-01.6, WP-14.5 and WP-22.5; the Next-up line.
  - **Docstrings:** `digest_sheet`, `keep_digest_read` and its helpers,
    `_replace_result_with_attempt_history`, `_rescue_failed_items_sync`,
    `_harvest_abandoned_batch`, `_park_usage_attempts`,
    `_resubmit_failed_items`, `_run_qc_stages`, `review_findings`,
    `held_out_findings`, `_sheet_document`, `_held_out_block`.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). A real refusal or truncation mid-findings-block was not observed; the
  shapes are the suite's fakes. How often a real raised-cap retry lands worse
  than the first read is not measurable without real drawings (O-10). Windows
  is covered by this PR's CI.
- **Risks and residual gaps:**
  - **Visible changes, by design.** A sheet's error can now carry `; retry: …`,
    `; retry failed: …` or `; N retries, the last: …` (in `ctx.errors`,
    `run.log`, the report's stage table and the sheet's file). A sheet with a
    held partial read whose rescue never landed reports the read's own error
    instead of "drawing batch not collected (…)". An unfinished read's findings
    leave `findings.json`, `findings.csv`, the markups and the report's table
    and appear only in the sheet's file and card, so an exhaustive run can show
    fewer findings than before when a sheet's read did not finish.
  - **Real time keeps one usage record per sheet**, summing both attempts:
    the discarded attempt is named in the error but has no record of its own
    (noted on WP-14.5).
  - **Two partial reads:** the later is kept, so the first read's prose is
    replaced when the raised-cap read is itself cut off (the owner's
    tie-break; pinned).
  - **A refused harvested read is parked**, not held (a partial read outranks
    a refusal, and R2 decides refusal retries: WP-01.5 note).
- **Re-checked (U31):** D-1's classifier and ladder (`classify_stop_reason`,
  `digest_terminal_error`), the admission predicate and the loader, the retry
  predicates (`raised_cap_may_finish`, `_item_retry_params`), the abandoned
  markers (`_mark_batch_abandoned` still skips a responded slot), the
  `_combine` delivery contract and `models.FINDINGS_PARSE_OK` are untouched;
  the prose harvest's skip of an errored sheet (1567) is unchanged and now
  agrees with the ledger (the owner's hold-out rule is the same rule, so it
  needs no change).
- **Found, not fixed:**
  - `set_identity._sheet_block` puts an errored sheet's text (a refusal's
    explanation, a truncated read's prose) into the advisory identity corpus
    whenever it has any; every other consumer skips that sheet (WP-01.6 note);
  - F401: `SheetDigest` imported unused in `tests/test_drawing_digest.py`, on
    `main` already (WP-22.5 note).
- **Next:** WP-01.4 (Wave 1; its dependency WP-01.2 is done).

### 2026-09-24 — WP-09.2: a prose item joins a finding only when they make the same claim ([PR #169](https://github.com/Abe-Borg/drawing-analyzer/pull/169))

- **Slice and IDs:** WP-09.2. N10 and U11 (implemented+validated). N32 is
  routed to a new slice, WP-09.3, by the owner (below); it is not fixed here.
  No `DECISIONS.md` contract is decided (none of D-1 … D-8); D-2 gains a note
  (the owner's decision: the per-item outcomes and the new counts are
  observational). No migration-register row: no cache contract, key, prompt or
  schema moved. **WP-09 is not done:** WP-09.3 (N32) remains (acceptance check
  below).
- **Base.** `main` = `origin/main` = `36dd865`; no drift. Baseline **3,994
  passed, 2 skipped, 10 deselected** (262 s), identical to the WP-09.1 handoff.
  The two skips are IPv6 loopback and chmod as root.
- **Reproduced first** (a probe on `36dd865`), each as the request stated:
  - **N10.** `_match_entry` returns the entry for all four cases, and
    `signature_conflicts` over a text-only item names the axis: 4/6 inch
    (0.857, `measurements`), 165/150 psi beside a shared 175 psi (0.818,
    `measurements`), P-2/P-1 (0.750, `tags`), 550/500 gpm (0.818,
    `measurements`). The paraphrase "6 inch drain required at column line 4."
    (0.750) has no conflict.
  - **SHEET.** "Duct riser blocks the corridor door." against an identical
    SHEET entry scores 1.0 and conflicts on `absence_polarity` when the item is
    signed as text alone.
  - **N32** (for the routing question): a statement heading inside a digest
    section is lost, and with no Coordination/Conflict keyword it also makes
    the bullets under it `other` (`**The riser blocks the corridor door at
    grid 5.**`) or `dimensions` (`### Duct riser blocks the corridor door.`),
    so they are lost too: 2 of 4 layouts probed. And `_is_label` returns False
    for 6 of the digest's 8 standard section names (`Scope / systems shown`,
    `Equipment & schedules`, `Plan content`, `Key dimensions, ...`, `General
    notes, keynotes, and callouts`, `Focus findings`).
  - **A miscount found while designing the record:** an item whose ledger
    ingest raised was counted `structured` (before the add) and then
    `degraded` (by the reconcile that recovered it): `items 1`, `structured
    1`, `degraded 1`. Fixed here (below).
- **Facts confirmed, not assumed** (an instrumented scratch copy of
  `origin/main`, the whole suite, with the test name):
  - **The hooks ran 131 harvests, 165 `_match_entry` calls from 55 tests (90
    on the free path, 75 in `active_chain_count`), 77 structuring calls, 73
    ingests, 261 numberings and 188 prose-harvest stage records.** 17
    free-path matches in 8 tests; no call had two candidates at 0.7 or above
    (so "the best is refused, a lower one is compatible" is never exercised
    by a fixture); no candidate had absorbed a member (history length 1
    everywhere).
  - **Suite totals:** items 100, matched 17, structured 53, degraded 20,
    set-level 10, excluded focus 2, filtered 24, assurances 10, missing 0.
  - **Duplicate outcomes:** 1 of 53 structured ingests folded (in
    `test_no_structuring_cache_key_holds_a_prose_item_id`); none of the 20
    degraded ones.
  - **Caches.** The structuring key (`_structure_item._cache_key`) holds the
    user text (the item, its section hint, the sheet id, the capped text
    layer), the source binding, the contract and the request parameters, never
    a match decision, so an item the veto sends to structuring is an ordinary
    miss, never a stale hit (pinned:
    `test_a_refused_item_keys_its_structuring_call_like_any_straggler`).
    `_HARVEST_CACHE_CONTRACT` stays 1. No other cache stores a match outcome:
    the critique and cross-QC entries are written before the harvest runs; the
    investigation key reads the finding's id, text, quote, category,
    severity, rect, prior verification note and the set fingerprint, and the
    verification keys hash named finding fields, none of them `sources`,
    `prose_item_ids` or a match. A newly separate finding is new paid work
    downstream (a verification crop, a citation check of its refs), not a
    re-key.
  - **Consumers of `prose_accounting`:** only `run_journal._prose_lines`
    (which printed any extra key as `f"{k} {acc[k]}"`, so a nested table would
    have printed its repr) and `export.build_run_manifest` (copies the dict).
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, with measured options). Chosen, each as recommended:
  - **Signing: "text against text", with legs.** The item is signed from its
    text and its synthesis legs; the candidate from its text, quote,
    supporting quotes and legs, with its `anchor_hint` set aside, since
    `critique._is_absence` reads SHEET as an absence and a placement is not a
    claim. Measured, with the veto actually applied, over the 15 test files
    that run a harvest (1,095 tests) and a 24-case table:

    | option | suite: matches refused | pinned tests failing | extra calls | case table |
    |---|---|---|---|---|
    | text only (A) | 5 of 17 (quote-less twins, `absence_polarity`) | 2 | 5 | 18/24 |
    | candidate's placement (B) | 0 | 0 | 0 | 18/24 |
    | B + legs (D) | 0 | 0 | 0 | 19/24 |
    | text against text (E) | 0 | 0 | 0 | 20/24 |
    | **E + legs (F, chosen)** | **0** | **0** | **0** | **21/24** |
    | item as SHEET (C, not offered) | 8 of 17; 6 of 10 chain matches flip | 3 | 4 (+2 entries, 2 tests renumbered) | 17/24 |

    B misses an opposite-polarity item against a degraded or quote-less entry
    in both directions (the axis can never fire against SHEET); E and F read
    them from the texts. Every option but A misses a presence item against a
    SHEET absence written with no absence word, and A refuses five true
    restatements. The legs (D, F) are what refuse a synthesis item against a
    conflict with other legs (C refuses it too, but only through its SHEET
    absence).
  - **The best candidate refused: the next-best compatible one wins** (the veto
    only removes incompatible entries from the pool). Not taken: none (any
    refusal makes a straggler). In the table each policy gets one of the two
    configurations right, and the one "none" gets right is the threshold's own
    weakness (a compatible other claim at 0.714 is absorbed with no veto
    involved).
  - **A refused item with no compatible candidate is a straggler; the calls
    are accepted.** Not taken: a degraded entry without a call.
  - **N32: its own slice, WP-09.3.** Not taken: in this PR.
  - **The record: both, observational.** One `ProseItemOutcome` per
    enumerated item in `HarvestResult.outcomes` (channel, outcome, call,
    folded, refused); `vetoed`, `folded`, `filtered_focus` and the per-channel
    table `by_channel` in `prose_accounting`. Not taken: per-channel counts
    only; the per-item records in `run_manifest.json` too.
  - **Suppressed items: counts per channel, focus always.** Not taken: focus
    filler counted only when focus is harvested; ids from a separate id space.
  - **Duplicate outcomes: `folded`, per item and counted**, the item keeping
    its outcome. Not taken: a separate `folded` outcome.
  - **The corpus: pairs plus the sweep, pinned.** Not taken: pinned at 0.7
    only.
  - **Not asked (stated):** the veto compares the item with the live candidate
    (the plan's literal rule), not with each member of the candidate's
    `Ledger.member_history`. Measured: it changes nothing in the suite, since
    no candidate had absorbed a member. A matched item changes no claim of the
    entry (it adds provenance), so asking whether the item agrees with what
    the entry states, its grown signature included, is the question.
- **What changed:**
  - **`prose_harvest.py`** (it still imports no PDF engine, and the prose
    digest is untouched, I-2):
    - `_match_score` (new; the old score) and `_veto_axes` (new; the signing
      above, over `critique.signature_conflicts` and
      `critique.critical_signature`, the one rule).
    - `_match_entry(item, entries, *, also_on=(), refused=None)`: candidates
      at or above `_MATCH_OVERLAP`, best score first and ties in ledger order,
      the first compatible one wins; only candidates are signed (plan section
      2 rule 14; pinned by `test_bounded_work_only_candidates_are_signed`).
      Both callers pass the item's legs; the free path passes a `refused`
      sink, `active_chain_count` does not.
    - `PROSE_OUTCOMES`, `ProseItemOutcome` (new) and `_record_outcome`, the
      only place an outcome counter moves, called once the ledger holds the
      finding; `_add_to_ledger` (a fold is an add that left the entry count
      unchanged, exact before the seal) and `_call_of`. `_Pending` gains
      `refused` and `call` (the call a reconciled item cost is kept).
    - `HarvestResult` gains `filtered_focus`, `vetoed`, `folded`, `outcomes`,
      `suppressed` and `by_channel()`; `accounting()` exports the three counts
      and `by_channel`.
    - `_filtered_prose_lines_by_channel` (new; `count_filtered_prose_lines` is
      its sum, unchanged), `_focus_split` (new; `extract_focus_items` and the
      new public `count_filtered_focus_lines` share it), and
      `_enumerate_pending` fills the per-channel suppressed counts.
    - The reconcile and `missing` record outcomes; the summary log line names
      `filtered-focus`, `vetoed` and `folded`.
    - Docstrings: the module docstring (mechanism 2, the outcome record), the
      `_MATCH_OVERLAP` comment (U11), `_match_entry`, `_veto_axes`,
      `HarvestResult`, `accounting()`, `count_filtered_focus_lines`.
  - **`run_journal.py`:** `_prose_lines` keeps `by_channel` out of the generic
    extras and renders it through `_prose_channel_lines`, one line per channel
    ("digest coordination: matched 2 · structured 1"); a malformed table
    renders what it can and never raises.
  - **Not changed:** `_MATCH_OVERLAP` (0.7), `signature_conflicts`,
    `_is_absence`, the tokenizer, the ledger and `_is_duplicate`, the
    structuring prompt and its structured-outputs gate, the filler and
    assurance vocabulary, the pipeline's usage records (D-7), the report.
- **Contracts decided:** none of D-1 … D-8; a D-2 note.
- **Cache/schema effects: none.** No key, contract, prompt version or schema
  moved (`_HARVEST_CACHE_CONTRACT` stays 1); the new `HarvestResult` fields are
  run-local and never cached. `prose_accounting` gains three counts and a
  nested table (`run.log`, `run_manifest.json`), additive. No prose item id
  moved: the enumeration and its ordinals are unchanged.
- **Re-baselined tests: none.** Checked both ways:
  - the 12 pinned files (`test_drawing_ledger`, `test_drawing_acceptance`,
    `test_prose_filler_and_assurances`, `test_drawing_qc_pipeline`,
    `test_drawing_export`, `test_run_journal`, `test_structured_outputs`,
    `test_drawing_usage`, `test_pipeline_stage_overlap`,
    `test_qc_numbering_tiebreak`, `test_drawing_synthesis`,
    `test_drawing_html_report`) against the fixed tree: **734 passed**. The
    only edit to them is one new test in `test_drawing_acceptance.py`
    (`test_gauntlet_prose_outcomes_are_exact`); no existing test changed;
  - the new tests against a `git archive` copy of `origin/main`, classified
    from `--junitxml`: **28 failed on behaviour, 81 only on the new API**
    (`_veto_axes`, `_match_score`, the `also_on`/`refused` keywords,
    `HarvestResult.outcomes`/`vetoed`/`folded`/`filtered_focus`,
    `count_filtered_focus_lines`, the new accounting keys), **17 passed**. The
    passes pin what the fix keeps: the seven restatements (a paraphrase
    against a plain and against a degraded entry, a degraded twin, an absence
    twin, a critique absence, the gauntlet's, the five-item test's), a free
    match with no call, the entry a match leaves unchanged but for its
    provenance, legs lent to an entry without legs, ties in ledger order, a
    malformed channel table, the recorded limit, the threshold and the
    corpus's shape.
- **Fixture effects, instrumented over the whole fixed suite** (the same hooks,
  diffed test by test against the base run): **outside the new tests nothing
  moves.** The same 131 harvest results (every count, call, cache hit and
  miss, token count, entry, text, prose id, source and hint), 261 numberings
  (entry counts, QC numbers, texts, prose ids, sources), 188 prose-harvest
  stage records (status, warnings, errors, items), 73 ingests, 77 structuring
  calls and 165 match results. Over those harvests: `vetoed` 0, `folded` 1 (the
  fold above), `filtered_focus` 2 (`test_b11_filler_in_a_focus_section_is_not_harvested`,
  twice). Every harvest's outcomes add up to its counters (164 of 164,
  new tests included). The gauntlet (`run_acceptance.py`'s oracle) is
  unchanged: 4 items, 1 matched, 1 structured, 1 degraded, 1 set-level, 2
  calls, pinned exactly now.
- **New tests** (126):
  - `tests/test_prose_match_signatures.py` (67): **N10** the four cases
    against a plain and a SHEET entry, with the axis each is refused on; each
    becomes its own entry with a client (one call, structured) and without
    one (degraded), the entry it used to join untouched. **Kept:** seven
    restatements, and a free match with no call. **Polarity:** an
    opposite-polarity item refused against a plain entry and against a
    degraded one, both directions; the recorded limit. **Legs:** a synthesis
    item refused against a conflict with other legs, still matching (and
    lending its leg to) an entry without legs, and the veto reading the legs.
    **Candidates:** the next-best compatible one wins, the refused ones are
    reported, none when all are refused, ties in ledger order, a next-best
    match records its refusal. **Both callers:** two refused items on two
    pages run as two parallel chains, and the sequential and parallel paths
    build the same ledger and the same outcomes. **Outcomes:** one per item,
    adding up to the counters; channel, call, fold and refusals; a structured
    straggler the ledger folds is counted `folded`; the recorded limit of a
    refused presence item degraded into an absence entry (vetoed, degraded,
    folded); an item whose ingest failed counted once, keeping its live
    call; a cache hit; the `missing` outcome. **Suppressed:** per channel,
    focus filler counted with the focus harvest on and off, the focus counter
    and the extractor agreeing; the table adds up; the new counts are
    observational. **run.log** renders the table one line per channel, and a
    malformed table never sinks the log. **Cache:** a refused item keys its
    structuring call like any straggler. **End to end** through the pipeline:
    two QC findings, one harvest call, `vetoed 1`, the stage COMPLETE,
    `run_manifest.json` equal to the context's accounting, `run.log`'s channel
    line. **Bounded work:** of 201 entries only the one candidate is signed.
  - `tests/test_prose_paraphrase_corpus.py` (58): the labelled corpus (47 hand
    pairs: 22 same, 25 different; the 45 must-keep findings pairwise, 990
    different), `_MATCH_OVERLAP == 0.7`, the sweep pinned at 0.5 to 0.9 with
    and without the veto, the five near misses the veto lets through and the
    four restatements it refuses (each set pinned exactly, as recorded
    limits), and `_match_entry` agreeing with the score and the veto on every
    pair.
  - `tests/test_drawing_acceptance.py::test_gauntlet_prose_outcomes_are_exact`
    (1).
- **The corpus's numbers** (U11; the evidence for a later threshold decision,
  O-10 for real drawings):

  | threshold | same matched, no veto | different absorbed, no veto | same matched, veto | different absorbed, veto | must-keep absorbed (no veto / veto) |
  |---|---|---|---|---|---|
  | 0.5 | 22/22 | 25/25 | 18/22 | 8/25 | 3 / 1 of 990 |
  | 0.6 | 22/22 | 24/25 | 18/22 | 7/25 | 0 / 0 |
  | **0.7** | **22/22** | **19/25** | **18/22** | **5/25** | **0 / 0** |
  | 0.8 | 18/22 | 8/25 | 15/22 | 1/25 | 0 / 0 |
  | 0.9 | 15/22 | 4/25 | 14/22 | 1/25 | 0 / 0 |

  Let through at 0.7 (no signal the signature reads): a fire vs a smoke
  damper, a 2-hour vs a 1-hour wall (`hour` is not a unit the tokenizer
  reads), a drain vs a vent of one size, "piped" vs "not piped" (not an
  absence phrase `_ABSENCE_RE` reads), and one side naming an extra sheet (tag
  inclusion). Refused restatements (a structuring call each, the safe
  direction): "does not show" vs "not shown", "has no clearance" vs "No
  clearance is shown", "No sprinkler heads are shown" vs "are not shown", "has
  no fire wrap" vs "is missing" (`_ABSENCE_RE` reads one wording and not the
  other). The hand pairs are synthetic; real rates need O-10.
- **Downstream consumers walked:**
  - **Both `_match_entry` callers:** one function, legs passed by both;
    pinned by the parallel-chain test.
  - **`matched` and the new counters:** from `_record_outcome` only.
  - **The matched entry:** a match still adds only `sources`, `prose_item_ids`
    and legs it lacked (pinned); a refused item adds nothing to it.
  - **The reconcile:** records its outcome; unchanged otherwise.
  - **The ledger's Pass A fold of a straggler:** a refused item's structured
    finding stays separate when its signature conflicts; a quote-less or
    degraded one is SHEET-placed, which the ledger reads as an absence (the
    recorded limit; counted `folded`).
  - **QC numbering:** a newly separate finding takes a positional number; no
    fixture numbering moved.
  - **Margin callouts and `Drawing_Set_Review_Notes.pdf`:** a refused item
    degraded without a client is a margin callout like any degraded item;
    set-level items are not matched, so the notes PDF is unchanged.
  - **`run.log`, `run_manifest.json`:** the channel table and three counts
    (pinned end to end); the exports and the report list each finding as
    before (a newly separate one is one more row).
  - **The gauntlet:** unchanged (above).
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **3,994 passed, 2 skipped, 10 deselected**
    (262 s) on `36dd865`.
  - The new files: 67 + 58 passed; the 12 pinned files: 734 passed.
  - Full suite after: **4,120 passed, 2 skipped, 10 deselected** (250 s):
    the baseline plus the 126 new tests, with the same two environment skips.
  - Browser suite: not run separately. No report JS, HTML or chat code
    changed, and the browser tests ran inside the full suite.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds only
    `count_annotations` in `tests/test_drawing_acceptance.py`, on `main` already
    (noted on WP-22.5). `scan_secrets.py` is clean over 209 tracked files, the
    two new ones included. `compileall src` passes.
- **Docs:**
  - **CHANGELOG** (Fixed): N10 and U11, with the visible effect, the calls,
    the new counts, the corpus numbers, the limits, and no id or cache effect.
  - **CLAUDE.md:** the `prose_harvest.py` passage (the signature veto, the
    one-copy rule it reuses, the outcome record, the limits).
  - **README:** "Prose harvest — the legacy channel's guarantee": mechanism
    (2) needs the same claim, and two paragraphs on the veto and on the
    recorded outcomes.
  - **The plan:** a WP-09.2 note under "Step 5 (N10)"; N32 routed to WP-09.3
    (the WP-09 slice list, §3 and §7.2, with the measured facts); the U11 row.
  - **DECISIONS:** the D-2 note.
  - **PROGRESS:** this entry; the WP-09.2 row; the new WP-09.3 row (Wave 3);
    the WP-09 package row (slices 09.1–09.3); the N10, U11 and N32 rows; the
    Next-up line.
- **WP-09 acceptance check (README step 7.3).** "boilerplate creates neither a
  finding nor a paid structuring request; meaningful absences survive;
  degraded entries retain useful provenance; structured/plain cache separation
  remains correct; a measured threshold change cannot suppress distinct
  issues."
  - Boilerplate and meaningful absences: hold (WP-09.1's tests, unchanged).
  - Degraded entries retain useful provenance: hold. A degraded entry carries
    the item verbatim, its channel as `sources`, its `prose_item_id`, the
    sheet binding and a verification note, and now its outcome record says
    why (the call it cost: none, or a live call whose reply was unusable).
  - Structured/plain cache separation: holds (`tests/test_structured_outputs.py`'s
    harvest tests pass unchanged; no key moved).
  - A measured threshold change cannot suppress distinct issues: no change
    was made; the corpus is the measurement any change must read, and the
    veto refuses every signature-distinct candidate at any threshold. It
    cannot refuse what the signature does not read (the five pinned limits).
  - **But WP-09 covers N32, which is WP-09.3's**, so **WP-09 stays `todo`**
    until that slice lands. Step 6 is WP-01.6's (plan).
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Not measurable without real drawings (O-10): how often a real prose
  item is refused (each is a structuring call), how often a refused item's
  finding folds in the ledger anyway, and the corpus's rates on real prose.
  Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **More paid calls, by design:** one Sonnet structuring call per refused
    item on an exhaustive run (none in the fixtures).
  - **The SHEET reading, recorded:** the ledger's `_is_absence` reads a SHEET
    placement as an absence, so a refused presence item that becomes a
    quote-less or degraded finding can still fold into an absence entry
    (counted `folded`, pinned). Changing that reading is not this slice's: the
    ledger's merges read it too.
  - **Signature-blind near misses** still join at 0.7 (the five pinned).
  - **Absence wording:** `_ABSENCE_RE` reads some negations and not others, so
    a restatement across two wordings costs a call (four pinned), and a
    "not piped" / "piped" pair is not refused.
- **Re-checked (U31):** the structuring prompt, the structured-outputs gate
  and cache fold-in, the filler and assurance vocabulary and its recorded
  limits, `signature_conflicts`, `_is_absence`, the tokenizer, the ledger and
  the report's section grammar are untouched.
- **Found, not fixed:** nothing new beyond N32's measured scope (WP-09.3's
  row) and the recorded limits above. `_id_mentions` stays quadratic in the
  number of mentions (the WP-09.1 note). This slice did not touch it and
  measured no input that reaches it, so it is left, and the note moves to
  WP-09.3's row, the next slice in `prose_harvest.py`.
- **Next:** WP-01.3 (Wave 1; its dependency WP-01.2 is done).

### 2026-09-24 — WP-09.1: section filler and synthesis assurances are not findings ([PR #168](https://github.com/Abe-Borg/drawing-analyzer/pull/168))

- **Slice and IDs:** WP-09.1. B11 and N11 (implemented+validated), and N31
  (found while measuring N11, fixed here by the owner's decision, added to
  plan §3 and §7.2). No `DECISIONS.md` contract is decided (none of D-1 …
  D-8); D-2 gains a note (the owner's decision: the dropped synthesis
  assurances are counted observationally). No migration-register row: no cache
  contract, key, prompt or schema moved. WP-09 is not done (WP-09.2 remains),
  so there is no package acceptance check.
- **Base.** `main` = `origin/main` = `2be7034`; no drift. Baseline **3,787
  passed, 2 skipped, 10 deselected** (261 s), identical to the WP-06.1 handoff.
  The two skips are IPv6 loopback and chmod as root.
- **Reproduced first** (a probe on `2be7034` with the fixtures of
  `tests/test_drawing_ledger.py`), each as the request stated:
  - **B11.** All four review strings pass `_TRIVIAL_RE` and survive
    `extract_prose_items`; `harvest_prose(client=None)` turns each into a
    degraded entry: medium, coordination, `anchor_hint` SHEET.
  - **N11.** "No conflicts were found between M-101 and P-101." is a
    dual-anchored item (M-101, P-101); "The mechanical and plumbing sheets are
    consistent; no conflicts were identified at this time." is a medium
    set-level conflict.
  - **Kept today:** "No isolation valve is shown.", the P8 item 6 corpus, the
    terse corpus, the gauntlet's `PROSE_DEGRADED`; the two must-survive
    synthesis sentences are extracted (the gauntlet's set-level one; "No
    conflicts were resolved…" dual-anchored).
  - **Ordinals.** With "No conflicts noted on this sheet." before "Duct riser
    blocks the corridor door." both are kept (ordinals 0 and 1).
- **Facts confirmed, not assumed:**
  - **One filter site for section bodies.** `_split_items` is called by the
    digest, focus and synthesis extractors and by `count_filtered_prose_lines`,
    and by nothing outside `prose_harvest.py` (grep over `src`, `tests`,
    `scripts`).
  - **The synthesis text is the raw model Markdown** (`pipeline.py`:
    `synthesis_text = result.text`), and the synthesis prompt asks for "short
    subsections / bullets". `_split_items` ran over the whole text, so a
    heading joined an item (N31, below).
  - **No cache key holds a `prose_item_id`.** The structuring key hashes the
    prompt, the item, the category hint, the sheet id, the capped text layer,
    the source binding and the request shape; the verification keys hash
    named finding fields (text, quote, category, severity, sheet and source
    ids, page, computation); the investigation key reads `id`, text, quote and
    the source fingerprint; `compute_finding_id` hashes sheet, category and
    quote-or-text. So `_HARVEST_CACHE_CONTRACT` stays 1 (pinned:
    `test_no_structuring_cache_key_holds_a_prose_item_id`).
  - **Readers of `prose_item_ids`:** `findings.json` and the per-sheet JSON
    (`Finding.to_dict`), the harvest's in-run reconciliation, the ledger's
    union on merge, QC numbering's last tie-break (`_qc_content_key`, reached
    only by entries tied on position, `id` and text), and the report's
    `prose×N` chip (a count, no id). No script reads them.
  - **`Drawing_Set_Review_Notes.pdf`** is written only when set-level findings
    exist (`pipeline.py`, markup stage), so an assurance that was its only
    content no longer produces it.
  - **A run with no enumerated item** reads prose harvest `SKIPPED_VALID`, and
    the roll-up treats it like COMPLETE (`models.roll_up_qc_status`).
  - **`run.log`** renders every accounting key outside its fixed list, so
    `assurances` appears without a renderer change.
- **The decision, made by the owner before any code** (AskUserQuestion, two
  rounds, with measured options). Chosen, each as recommended:
  - **Filler: a closed vocabulary.** The whole item must be `none` / `n/a` /
    `nothing [further]`, or `no` + up to two listed modifiers + a listed noun,
    with an optional listed label ("Coordination items:") and up to four listed
    qualifiers in any order. Not taken: repeatable qualifiers only (misses
    review string 4 and 14 of 16 equivalents measured then; it needs a
    modifier slot); an open modifier slot (also drops "No P-1 issues noted.",
    "No sprinkler items noted on this sheet.", "No fire-rated items noted on
    this sheet.": a content guess).
  - **One vocabulary, two anchored forms** (plan §4.2). Not taken: two
    independent regexes (two authors for one word list); one predicate per
    clause (measured: fails the first N11 sentence, since "between M-101 and
    P-101" is not filler vocabulary).
  - **Assurance: spans plus a contrast guard** (the guard became a closed list
    of frame words after the Codex review, below). Not taken: the minimal form
    only ("no <noun> [were] <detected>"; drops 8 of 22 edge cases against 13);
    also negated verbs ("does not conflict with"; loses the elliptical real
    conflict "The pump on M-101 does not conflict with P-101; the valve on
    E-201 does."). Measured before asking: without the contrast guard 3 real
    conflicts are lost ("No conflicts were found, but M-101 shows 500 gpm and
    P-101 shows 550 gpm."); without the head-noun check 3 more ("No conflict
    resolution is shown…"); with an open phrase before the verb, one more ("No
    conflicts between M-101 and P-101 resolve the pump question and none were
    found on E-201.").
  - **Headings: split the synthesis per section here** (N31). Not taken:
    recording it for a later slice (the N11 fix would then hold only for
    heading-free synthesis).
  - **Counting: a count of its own**, `HarvestResult.assurances`,
    observational. Not taken: folding it into `filtered` (which would stop
    meaning only digest lines); not counting (not auditable from the
    manifest).
  - **Ordinals: accept the one-time shift.** Not taken: ordinals over every
    split item (a wider one-time shift, and `ordinal` changes meaning).
- **Measured first**, as the request asked:
  - **A case table** of 76 digest items (the 4 review strings, 16 equivalents,
    the 12 existing boilerplate strings, 44 real findings, 31 of them with
    no/not/none/without elsewhere) and 45 synthesis sentences (the 2 N11
    sentences, 21 that must survive, 22 edge cases) through every option, plus
    6 synthesis layouts. The chosen rule drops every required case, keeps
    every must-keep case, drops 13 of the 22 edge cases and keeps 9 (recorded
    limits, below).
  - **An instrumented run** of a scratch copy of `origin/main` logging every
    split item (raw and kept, by caller), every synthesis extraction, every
    harvest result (accounting, calls, cache hits, entries with texts and
    `prose_item_ids`), every structuring call, every numbering (count, QC
    numbers, texts, prose ids) and every prose-harvest stage record, with the
    test name. The hooks ran **258 splits, 244 synthesis extractions, 116
    harvests, 72 structuring calls, 259 numberings and 186 stage records**.
    Evaluated offline under every option: **no fixture item changes decision**
    (144 digest/focus split events, 46 distinct items in 52 tests; 244
    synthesis extractions in 107 tests, 116 of them with text), the evaluator
    reproducing the base filter exactly. So no option could move a pinned test; the case table
    decided.
- **What changed** (`prose_harvest.py` only; it still imports no PDF engine,
  and the prose digest is untouched, I-2):
  - **The vocabulary** (new): `_DASH` (written as `\u` escapes),
    `_FILLER_MODIFIERS`, `_CONFLICT_NOUNS`, `_CONFLICT_ADJECTIVES`,
    `_FILLER_NOUNS`, `_AUXILIARIES`, `_DETECTED`, `_DISCIPLINES`,
    `_DOCUMENTS`, `_PLACES`, `_ID`, `_FRAME_WORDS`, the label words
    (`_LABEL_ADJECTIVES`, `_LABEL_NOUNS`, `_LABEL_KINDS`), and the builders
    `_alt`, `_MODIFIERS`, `_no_phrase`.
  - **`_TRIVIAL_RE`** rebuilt from it (the whole-item filler form). Pinned: it
    drops everything the old one dropped (`test_the_new_filter_drops_everything_the_old_one_did`).
  - **`_ASSURANCE_RE`** (new; the synthesis spans), `_FRAME_TOKEN_RE`,
    `_WORD_RE`, `_signal_spans`, `_has_conflict_signal`, `_is_assurance`
    (linear: spans are looked up by `bisect`), `_LABEL_RE` and `_is_label`.
  - **`_split_items`** returns the removed items instead of their count (its
    only callers are in the module); `count_filtered_prose_lines` takes their
    length.
  - **`_synthesis_statements`** (new): per section (`split_into_sections`),
    through `_split_items`, keeping signal-bearing statements that are not
    assurances and counting the rest; a heading that is not a label is an item
    of its own, before its section's items. Both extractors and
    `count_synthesis_assurances` (new, public) go through it.
  - **`HarvestResult.assurances`**, in `accounting()`; `_enumerate_pending`
    adds `count_synthesis_assurances(synthesis_text)`; the summary log line
    names it.
  - Docstrings: the module docstring, the vocabulary comment (replacing the
    `_TRIVIAL_RE` comment), `_split_items`, `count_filtered_prose_lines`, both
    extractors, `HarvestResult.assurances`.
- **Codex review (P1, P2), both fixed in this PR** (reviewed commit
  `d867de2`; the fix and its tests in the follow-up push):
  - **P1: "Recognize additional contrast conjunctions before dropping
    assurances."** Reproduced: "No conflicts were found, yet M-101 lists 500
    gpm and P-101 lists 550 gpm." was dropped whole, and so were the
    `nevertheless`, `nonetheless` and contrastive `while` forms. **Root cause,
    not only the example:** no list of contrast words is complete, and a
    statement with no connective at all ("No conflicts were found; no valve is
    shown on P-101.", "..., and M-101 lists 500 gpm while ...") was dropped the
    same way. **Fix:** the contrast list is gone; outside its assurance spans
    a statement may carry only listed frame words (`_FRAME_WORDS`: sheet ids,
    discipline, document and place names, a few function words, "are
    consistent", "at this time"). Any other word (a contrast, a value, a
    component, a "not") keeps it. This narrows the owner's rule in the safe
    direction and keeps its intent (a qualification keeps the statement);
    measured, it changes nothing on the 45-sentence case table or the six
    layouts, and every dropped case above still drops.
  - **P2: "Preserve conflict-bearing bold lines when splitting sections."**
    Reproduced: `**M-101 conflicts with P-101.**` was harvested on `main` in a
    paragraph layout and lost after the per-section split (in a bulleted
    layout `main` lost it too). **Fix:** a heading that is not a listed label
    is an item of its own. A label (`_LABEL_RE`) is the filler noun phrase
    without its "no" (listed modifiers, adjectives and nouns, "Summary of
    ...", "... review"), after an optional pair of sheet ids (or a single one
    with no "with" after it), before listed qualifiers or sheet ids. So
    "Cross-sheet / cross-discipline conflicts", "Conflicts between M-101 and
    P-101" and "FP-101 conflicts" stay labels, while "M-101 conflicts with
    P-101", "VAV-7 capacity mismatch (M-101 vs E-201)" and "Pump rating
    discrepancy between FP-101 and M-101" are read. Losing a conflict is worse
    than noise, so an unlisted label is read as an item (noise, the recorded
    limit below); probing 13 unusual labels found 7 such leaks, and the
    listed words now cover them. The same defect in the digest channel predates
    WP-09.1 and is recorded as N32, not fixed here.
  - **Found while timing the P2 fix, fixed before pushing:** the first label
    grammar used an ambiguous id pattern (`[a-z][\w./-]*\d[\w./-]*`, which can
    split one id several ways) inside a repeated group, and a heading repeating
    "M-101 / " backtracked exponentially (minutes for one heading). Every
    digit-bearing word is now read one way only and possessively
    (`_DIGIT_WORD`, `_ID`; Python 3.11 is the floor), the id lists are
    possessive, and the speed test carries those headings. Measured linear on
    twelve adversarial shapes (doubling the input doubles the time), except
    one that `_id_mentions` makes quadratic; that is pre-existing (4,000
    mentions of two ids take 0.8 s on `main` too) and noted on WP-09.2.
  - **Failing first:** the new tests against the reviewed commit fail exactly
    where the fix acts: **20 on behaviour** (9 missed-contrast statements, 9
    statement headings, Codex's example, a heading that is an assurance), 187
    pass (every label and every earlier test).
- **Contracts decided:** none of D-1 … D-8; a D-2 note.
- **Cache/schema effects: none.** The structuring cache key of every surviving
  item is unchanged (pinned), so no stored structuring result is re-billed and
  `_HARVEST_CACHE_CONTRACT` stays 1. No prompt, `Finding` field, key or schema
  changed. One additive accounting key, `assurances`, in `prose_accounting`
  (`run.log`, `run_manifest.json`). Fewer calls: one Sonnet structuring call
  saved per filler line, and per synthesis assurance that names a sheet, on
  each exhaustive run.
- **Ids.** A dropped item before a real one moves that item's ordinal and
  `prose_item_id` once (the owner's choice; pinned for a digest item and a
  synthesis conflict). Measured over the suite: no fixture's id moved (every
  harvest's entry ids are identical in the fixed run).
- **Re-baselined tests: none.** Checked both ways:
  - the 11 pinned files the request named (`test_drawing_ledger`,
    `test_drawing_acceptance`, `test_drawing_qc_pipeline`,
    `test_drawing_usage`, `test_structured_outputs`, `test_drawing_synthesis`,
    `test_pipeline_stage_overlap`, `test_qc_numbering_tiebreak`,
    `test_drawing_export`, `test_run_journal`, `test_drawing_html_report`),
    unedited, against the fixed tree: **526 passed**;
  - the new file against a `git archive` copy of `origin/main`, classified
    from `--junitxml`: **108 failed on behaviour, 5 only on the new API**
    (`count_synthesis_assurances`, `_CONFLICT_NOUNS`, the `assurances` key),
    **94 passed**. The passes pin what the fix keeps: the 45 real findings,
    the 5 filler limits, the old filter's language, the real synthesis
    conflicts, the assurance limits, the anchors, the gauntlet, the cache key
    and the speed bound.
- **Fixture effects, instrumented over the whole fixed suite** (the same hooks,
  diffed test by test against the base run): **outside the new file nothing
  moves.** The same 116 harvest results (every count, call, cache hit, entry,
  entry text and `prose_item_ids`), 72 structuring calls, 259 numberings (entry
  counts, QC numbers, texts, prose ids), 186 prose-harvest stage records
  (status, warnings, errors, items) and 244 synthesis extractions; `assurances`
  is 0 in every harvest. Re-run on the final code (after the Codex fixes):
  the same result, and 3,994 passed (the baseline plus the 207 new tests).
  The gauntlet (`run_acceptance.py`'s oracle) is unchanged: its prose, its
  synthesis and its one set-level entry.
- **New tests:** `tests/test_prose_filler_and_assurances.py` (207):
  - **B11:** the four strings and 21 equivalent wordings are filler and
    counted in `filtered`; no structuring call with a client, no entry without
    one, and no degraded entry when the call fails; focus filler is not
    harvested; everything the old filter dropped is still dropped.
  - **Kept:** 45 real findings (the P8 item 6 and terse corpora, the
    gauntlet's prose, 33 findings with no/not/none/without/nothing); 5 filler
    wordings outside the lists (recorded limits).
  - **N11:** the two review sentences and 14 equivalents are not conflicts;
    no call and no entry; a real conflict beside an assurance is still
    harvested with its leg; 30 real conflicts survive (9 added by the Codex
    review: a contrast, a value or a second clause); 9 assurance wordings
    outside the grammar stay conflicts (recorded limits); the anchors of "No
    conflicts were resolved…" and the gauntlet's synthesis are unchanged.
  - **N31:** three heading layouts (glued bullet, `###` paragraphs, bold
    paragraphs) yield no conflict; a real conflict under a heading is
    extracted alone; a plain label line of listed words belongs to the
    assurance after it, and one with a sheet id keeps the statement; 40 label
    headings are never conflicts, 9 statement headings are read in three
    layouts, a heading that is an assurance is counted (Codex review); the
    value sentence after an assurance, split off at "; M", is a recorded
    limit.
  - **Counting:** `assurances` counts assurances and conflict-naming filler
    in synthesis, is observational, and is apart from `filtered`.
  - **Ordinals:** the survivor's ordinal and id (digest and synthesis); no
    structuring cache key holds an id.
  - **One vocabulary:** every noun-form conflict signal has an assurance noun,
    every assurance noun carries a signal, and the signal list is pinned.
  - **Bounded work:** adversarial inputs of 20,000 repeats run well inside a
    time bound; measured linear (doubling the input doubles the time) on ten
    adversarial shapes.
  - **Pipeline:** filler on both sheets and a synthesis of assurances under a
    glued heading: no harvest call, no prose finding, no notes PDF, the stage
    `SKIPPED_VALID`, `filtered` 4 and `assurances` 2 in the context,
    `run_manifest.json` and `run.log`; with a real set-level conflict added,
    exactly that one set-level entry and the notes PDF.
- **Downstream consumers walked:**
  - **Structuring calls and their cache:** a dropped item never reaches
    `_structure_item`; a surviving item's key is unchanged.
  - **The ledger:** no entry for a dropped item; nothing else moves (QC
    numbers follow position, and no fixture numbering changed).
  - **Degraded margin callouts and `Drawing_Set_Review_Notes.pdf`:** none for
    filler or an assurance (pinned end to end).
  - **The stage record, `run.log`, `run_manifest.json`:** `items_in` counts
    fewer items; a run with none reads `SKIPPED_VALID`; `prose_accounting`
    gains `assurances` (pinned).
  - **Exports and the report:** fewer prose entries; the report's `prose×N`
    chip counts ids, never reads one.
  - **The gauntlet** (`run_acceptance.py`): unchanged (above).
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **3,787 passed, 2 skipped, 10 deselected**
    (261 s) on `2be7034`.
  - The new file: 207 passed; the 11 pinned files: 526 passed.
  - Full suite after: **3,994 passed, 2 skipped, 10 deselected** (260 s):
    the baseline plus the 207 new tests, with the same two environment skips.
  - CI on the first push (`1be03d0`) was green on every job: tests on Linux
    (3.11, 3.12) and Windows (3.11), the headless-Chromium report suite, the
    secret scan and static analysis, the build. The push with the Codex fixes
    re-runs it.
  - Browser suite: not run separately. No report JS, HTML or chat code
    changed, and the browser tests ran inside the full suite.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean; F401/F811/F841 over the two touched Python files is
    clean. `scan_secrets.py` is clean over 207 tracked files, the new one
    included. `compileall src` passes.
- **Docs:**
  - **CHANGELOG** (Fixed): B11, N11 and N31, with the visible effect, the calls
    saved, the accepted limits and the id/cache note.
  - **CLAUDE.md:** the `prose_harvest.py` passage.
  - **README:** "Prose harvest — the legacy channel's guarantee" (a paragraph
    on filler and assurances).
  - **The plan:** N31 in §3 and §7.2, WP-09's "Covers" line, and a WP-09.1
    note under "Steps 1–3" (a repeatable qualifier alone was not enough; the
    synthesis channel needed negation awareness and a per-section split).
  - **DECISIONS:** the D-2 note.
  - **PROGRESS:** this entry; the WP-09.1, B11, N11 and new N31 rows; a note
    on WP-09.2; the Next-up line.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Not measurable without real drawings (O-10): how often the digest and
  synthesis models write filler or assurances outside the vocabulary (each is
  a paid structuring call, as before), and how often a real finding is written
  entirely in listed words. Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **A real finding written entirely in listed words is dropped** (the
    owner's definition of filler: every word listed). None was found in the
    corpora; the lists hold no content nouns, and any tag, number or sheet id
    keeps an item.
  - **Recorded limits (kept, a paid call as before):** filler with an
    unlisted word ("No duct conflicts noted.", "No items requiring
    coordination.", "No coordination required.", "No action required.", "No
    conflicts noted on this sheet or with other disciplines."); assurances
    outside the grammar ("M-101 does not conflict with P-101.", "No duct
    conflicts were found…", "No apparent conflicts between M-101 and P-101.",
    "No conflicts shown between…", "Checked M-101 against P-101 for
    conflicts; none were found.", "Previously reported conflicts … were not
    found in this revision.", "M-101 and P-101 were reviewed for conflicts and
    none were identified.", "No stale references were found on M-101.", "No
    conflicts between the pump schedule on M-101 and P-101 were found.").
  - **An unlisted label heading is read as an item** (Codex review: losing a
    conflict is worse than noise). A label outside the listed words that
    carries a conflict word becomes a set-level note, or a source-scoped item
    if it names a sheet. The listed words cover every label probed (40,
    pinned).
  - **A value sentence split off after an assurance** ("No conflicts were
    found; M-101 lists 500 gpm and P-101 lists 550 gpm.": the splitter ends a
    sentence at "; M") carries no conflict word, so it is not harvested, as on
    `main` (pinned as a recorded limit; `main` also made the assurance half a
    set-level note).
  - **A plain label line** (not a Markdown heading) still joins the next
    sentence. Made of listed words ("Cross-sheet conflicts:") it belongs to
    the assurance after it, like an inline bold label; with any other word
    ("Conflicts on M-101:", then "None identified.") its conflict word keeps
    the statement a conflict, the safe direction (pinned:
    `test_a_label_line_before_an_assurance`).
- **Re-checked (U31):** the structuring prompt, the structured-outputs gate,
  `_match_entry` and `_MATCH_OVERLAP` (WP-09.2's), the degraded and set-level
  entries, the report's section grammar and "Issues only" keywords, and the
  ledger are untouched.
- **Found, not fixed:**
  - focus-section filler is counted nowhere (with the focus harvest on, it is
    dropped silently, as "None noted." always was); a note on WP-09.2, whose
    per-item outcome counters cover it;
  - **N32** (new, P2): a digest heading that states something is never read
    (`split_into_sections` makes it a section header); the synthesis channel's
    fix (`_is_label`) is the test to reuse. Added to the register, plan §3 and
    §7.2, and noted on WP-09.2.
- **Next:** WP-09.2 (Wave 1; its dependencies WP-04.2 and WP-09.1 are done).

### 2026-09-24 — WP-06.1: an uncertain conflict is a low question, refused items are counted, distinct conflicts reach the ledger ([PR #167](https://github.com/Abe-Borg/drawing-analyzer/pull/167))

- **Slice and IDs:** WP-06.1. B6 and N2 (implemented+validated). N2's ledger
  half is not this slice's: the ledger still folds two different conflicts whose
  terse texts both name the same two sheets (N30, WP-03.5; measured and pinned
  as a recorded limit, below). The WP-05.1 note on this row (the whitespace-only
  fact quote) is resolved. No `DECISIONS.md` contract is decided (none of D-1 …
  D-8); D-2 gains a note (the owner's decision: cross-QC's refused items are
  observational), and D-4 gains a note and the migration register one row (the
  contract bump). WP-06 is not done (WP-06.2, WP-06.3 and WP-06.4 remain), so
  there is no package acceptance check; the plan's acceptance line gains a note
  on its N30 dependency.
- **Base.** `main` = `origin/main` = `742d628`; no drift. Baseline **3,731
  passed, 2 skipped, 10 deselected** (207 s), identical to the WP-05.2 handoff.
- **Reproduced first** (a probe on `742d628` with the suite's fakes, built as
  `tests/test_drawing_cross_qc.py` builds them), each as the request stated:
  - **B6, whole-set.** `severity: "question"` gives 0 findings, `complete=True`,
    `error=None`, `discards=None`, and is cached: the warm run hits, 1 call in
    total. `"Question"` and an unknown category behave the same.
    `category: "question"` with `severity: "low"` is kept.
  - **B6, sharded.** `_finding_from_handles` returns `None` for severity
    `question` and no counter moves; `question`/`low` is kept.
  - **N2.** The review's valve/horsepower pair (primary `M-101` quoting
    `PUMP P-1`, one leg on `E-101` quoting `PUMP P-1`, category `conflict`):
    overlap 0.273, `_dedup_findings` keeps 1, `Ledger.add` keeps 2.
  - **The whitespace-only fact quote** is admitted, TEXT_EVIDENCE_UNAVAILABLE,
    and counted `facts_admitted_no_text_evidence`.
  - **Caches.** Editing the persona sentence changes `_cross_qc_cache_key`.
- **Facts confirmed, not assumed:**
  - **Naming the sheets.** The request's 0.333 depends on phrasing: naming
    both sheets adds the tokens `m`, `101` and `e` to both texts. A
    full-sentence version of the pair measures 0.353 (the ledger keeps 2); the
    terse pair measures 0.462 (the ledger folds it: N30).
  - **A re-report of one conflict.** Phrased apart (0.118): `_dedup_findings`
    kept 1 and the ledger keeps 2. Phrased close: the ledger keeps 1.
  - **Only the persona has the B6 slip** (a grep over `src/`). The reconcile
    prompt does not carry the persona and never had the sentence.
  - **The fakes** route cross-QC calls by the prompt constants, so the edit
    keeps them in step; so does `scripts/benchmark_drawing_analyzer.py`'s fake.
  - **`Finding.to_dict()` serializes every field** (`citation` and
    `claim_discriminator` only when set), so "identical in every field" is the
    equality of the serialized dict.
  - **No test calls `_dedup_findings`.** The new optional `invalid` parameters
    keep every existing caller of the validators and call helpers working,
    including the two tests that monkeypatch `_map_call` and `_reconcile_call`.
- **The decision, made by the owner before any code** (AskUserQuestion with
  measured options). Chosen, each as recommended:
  - **Effect of a refused item: observational.** A counter and a stage
    warning, placed after the warnings that decide the status (they lead, as
    verification's coverage note does); the stage keeps its status and the
    result is cached with its counts, so a warm run shows the same warning.
    Not taken: PARTIAL and not cached (every warm run re-bills the Opus call
    and stays PARTIAL for a stable reply, N14's shape); PARTIAL and cached as
    PARTIAL (WP-06.3's N14 decision).
  - **Where: a separate record**, `CrossQCInvalidCounts` on
    `CrossQCResult.invalid`, filled on both paths, so `discards is None` keeps
    meaning "grounding not measured" on the whole-set path until WP-06.2.
    `run_manifest.json` gets `cross_qc_invalid` beside `cross_qc_discards`.
    Not taken: `discards` non-`None` on the whole-set path (the plan note's
    literal reading; its grounding counters would read 0 where nothing was
    measured); a marker flag every consumer must honour.
  - **Counting: per reason, once.** `cross_qc._invalid_field`, the one field
    check both validators now apply: not an object, then the category, the
    severity, the text; each refused item counts under the first check it
    fails (`findings_not_object`, `findings_invalid_category`,
    `findings_invalid_severity`, `findings_invalid_text`), so the counts sum
    to the items lost. Run-level only. A whitespace-only fact quote is dropped
    and counted `facts_no_quote`, like an empty one. Not taken: per field
    (counts stop summing to items lost); one counter; keeping the whitespace
    fact's admission.
  - **N2: (b) exact repeats only.** `_drop_exact_repeats` keeps the first of
    findings whose whole `to_dict()` is equal and hands every other report to
    the ledger. Not taken: (a) dropping the dedup (the same ledger outcome,
    since the ledger folds identical copies anyway, but the stage's
    `items_out` and the cache count every repeat, and the pair fan-out test
    sees 36 findings); (c) the ledger's predicate inside cross-QC (the same
    folds, but it keeps the first member, losing a later copy's higher
    severity or action that the ledger's merge keeps).
  - **Not asked (stated):** the contract bump beside the prompt edit (below).
- **Measured first**, as the request asked:
  - **Four full instrumented runs** of a scratch copy of `origin/main`, one per
    N2 option plus the base, logging every cross-QC result (counts, dedup
    keys, texts, discards, `complete`, cache hits), every refused item and
    whitespace fact, every ledger numbering (entry count, QC numbers, texts),
    every cross-QC stage record (status, warnings, `items_out`) and every
    `qc_status`, with the test name. The hooks ran **126 `cross_sheet_qc`
    calls in 115 tests (74 results: 53 whole-set, 21 sharded; 3 cache hits),
    84 validator calls, 51 fact parses, 179 numberings and 97 cross-QC stage
    records.**
    - **0 refused items and 0 whitespace-only fact quotes** in the fixtures,
      so no stage status, warning or cache admission could move under either
      stage option.
    - **One dedup site removed anything:** the pair fan-out test
      (`test_reconcile_all_pairs_finds_conflict_across_fact_groups`), 36
      identical copies to 1; the ledger keeps 1 under every option.
    - Under (a) that one test fails (36 findings); under (b) and (c) nothing
      changes: no ledger count, QC number, stage status or `qc_status` moved
      under any option.
  - **A case table** through every option (cross-QC result → ledger entries):

    | case | today | (a) | (b) | (c) |
    |---|---|---|---|---|
    | valve/HP pair (0.273) | 1→1 | 2→2 | 2→2 | 2→2 |
    | the pair naming both sheets (0.353) | 1→1 | 2→2 | 2→2 | 2→2 |
    | N30 terse pair (0.462) | 1→1 | 2→1 | 2→1 | 1→1 |
    | re-report phrased apart (0.118) | 1→1 | 2→2 | 2→2 | 2→2 |
    | re-report phrased close | 1→1 | 2→1 | 2→1 | 1→1 |
    | identical copy ×4 | 1→1 | 4→1 | 1→1 | 1→1 |
    | same text, later copy more severe | keeps low | ledger keeps high | ledger keeps high | keeps low |
    | same text, later copy has the action | loses it | ledger keeps it | ledger keeps it | loses it |
    | different legs (the pinned test) | 2→2 | 2→2 | 2→2 | 2→2 |

  - **How far naming the sheets pushes distinct conflicts toward 0.4** (the
    request's question; synthetic, since real rates need O-10): twelve
    distinct P-1 issues between M-101 and E-101, all quoting `PUMP P-1`, 66
    pairs. Without sheet names the mean overlap is 0.175 and 0 pairs fold;
    naming both sheets in full sentences, 0.316 and 4 fold (6%); in one terse
    clause each, 0.523 and 45 fold (68%; 21 more reach 0.4 but a signature
    conflict keeps them apart). Recorded on N30 and WP-03.5, not fixed: the
    ledger's predicate is WP-03.5's.
- **What changed:**
  - **`cross_qc.py`** (it still imports no PDF engine):
    - The persona sentence: "when you are not certain two sheets truly
      conflict, report it with category `question` and severity `low`". The
      whole-set and map prompts both start with it.
    - `CrossQCInvalidCounts` (new): four counters, `bump`, `merge`, `total`,
      `note()` (the stage warning, e.g. "2 returned item(s) refused for an
      invalid field (severity 2)"), `to_dict`, `from_dict`.
      `CrossQCResult.invalid` (`None` = not recorded).
    - `_invalid_field` (new), applied first by `_validate_cross_item` and
      `_finding_from_handles`, which take an optional `invalid` record. The
      accepted set is unchanged.
    - The counts are threaded through `_one_cross_qc_call`, `_map_call`,
      `_reconcile_call` and `_reconcile_facts` (per-shard and per-pair local
      records folded in input order, as the discards are), and `cross_sheet_qc`
      logs a run's refused items once, at WARNING (`_log_refused`), on both
      paths. The whole-set INFO line now counts only the unplaceable items.
    - `_drop_exact_repeats` replaces `_dedup_findings` on both paths.
    - `_findings_array` (new): items are read only from a `findings` list.
      Found in review: a `findings` string beside a map call's facts would
      otherwise be iterated per character, and each character counted as a
      refused item (U16's shape). A value that is not a list was always read as
      no findings, and still is.
    - `_parse_facts` treats a whitespace-only quote as no quote.
    - The cache payload stores `invalid`, and `_cross_qc_from_cache` restores
      it.
    - `_CROSS_QC_CACHE_CONTRACT` 5 → 6 with its reason.
    - Docstrings: the module docstring (a paragraph on refused items and
      repeats; **corrected** its "balanced reduction tree", since
      `_reconcile_facts` reconciles every pair of half-cap groups, and the
      same slip in the `MAX_FACTS_PER_RECONCILE` comment), `CrossQCResult`,
      `_validate_cross_item`, `_finding_from_handles`, `_parse_facts`,
      `_reconcile_facts`.
  - **`pipeline.py`:** `DrawingContext.cross_qc_invalid`; the cross-QC stage
    keeps `cross_res.invalid` and appends its `note()` as a warning after the
    budget and reconciliation warnings.
  - **`export.py`:** `run_manifest.json` gains `cross_qc_invalid` (empty when
    the stage made no call, all zeros when it refused nothing).
- **Contracts decided:** none of D-1 … D-8; a D-2 note and a D-4 note.
- **Cache/schema effects:**
  - The persona edit re-keys every cross-QC entry through the prompt text the
    key already holds, and the host-side binding change bumps
    `_CROSS_QC_CACHE_CONTRACT` 5 → 6: two changes, two mechanisms (D-4 note;
    not "a bump and a key term for one change"). One register row. Every
    cross-QC entry misses once: one paid cross-QC pass per set on the next
    run. No release shipped contracts 4 or 5, so a user upgrading from 1.7.0
    pays one miss for all three bumps.
  - One additive serialized field, `invalid` (an older entry reads back as
    "not recorded").
  - A newly kept conflict is new paid work downstream (a dual-crop
    verification call, and an investigation if the crop cannot settle it),
    not a re-key.
  - Every other key is byte-identical: `tests/test_drawing_cache_identity.py`
    and `tests/test_source_identity.py` pass unchanged. The A/B
    `RECORD_CONTRACT_VERSION` stays 3 (`tests/test_ab_findings_diff.py`
    unchanged).
- **Re-baselined tests: the three contract tripwires** (5 → 6, with the
  reason recorded in each):
  `tests/test_drawing_cross_qc.py::test_cross_qc_contract_bumped_for_the_norm_id_fold`
  (which now also checks the key differs from contract 5),
  `tests/test_evidence_tail.py::test_no_cross_qc_contract_bump_was_needed` and
  `tests/test_evidence_visual.py::test_contract_counter_is_not_bumped_by_this_package`.
  Checked both ways:
  - `origin/main`'s versions of the 16 pinned files the request named, run
    against the fixed tree: **3 failed (exactly the tripwires), 853 passed**;
  - the three edited files run against the base: 3 failed (the tripwires), 95
    passed.

  `test_dedup_keeps_distinct_conflicts_sharing_a_primary_quote` passes
  unchanged.
- **Fixture effects, instrumented over the whole fixed suite** (a scratch copy
  of the fixed tree with the same hooks, diffed test by test against the base
  run): **outside the new file nothing moves.** The same 74 cross-QC results
  (counts, `complete`, `error`), 179 numberings (entry counts, QC numbers,
  texts), 97 stage records (status, warnings, `items_out`), 179 `qc_status`
  values, 3 cache hits and 59 cache admissions; 0 refused items, 0
  whitespace-only facts, and all 74 dedup sites keep what the old key kept.
  The gauntlet's `CROSS_CONFLICT` (whole-set, a valid severity) is unchanged,
  with no warning. In the new file: 112 validator calls with 67 refusals
  (severity 31, category 13, text 13, not an object 10), 4 whitespace facts,
  and 10 dedup sites where the new rule keeps more than the old key did.
- **New tests:** `tests/test_cross_qc_validation_and_dedup.py` (56):
  - **B6.** The whole-set and map prompts name only valid severities and
    categories, and ask for category `question` with severity `low`; the
    reconcile prompt never asked otherwise. A `question`/`low` conflict is kept
    on both paths. Sixteen items through both validators, each refused and
    counted once under its first reason, or kept (validation strict). The same
    item binds alike on both validators (parser-level equivalence; the
    evidence state is WP-06.2's). Counts on the whole-set, map and reconcile
    calls and folded across reconcile pair calls. A clean empty response is
    not a loss; an unplaceable item is not counted as refused. Observational
    and cached with the result, replayed on a warm run. The record round-trips,
    carries no text, and reads back "not recorded" from an older entry. The
    log separates refused from unplaceable. A `findings` value that is not a
    list is no items (not one refused item per character; below).
  - **N2.** The valve/horsepower pair survives on both paths and in the
    ledger, and naming the sheets does not change that. Identical copies from
    a shard and the reconciler, or from pair calls, collapse. A re-report
    phrased apart reaches the ledger twice (the accepted cost); phrased close,
    it folds. A later copy keeps the severity and action it adds. Only
    identical findings collapse, the first kept, in order.
  - **Recorded limit:** the terse N30 pair (`test_recorded_limit_n30_…`).
  - **The whitespace-only fact quote** (spaces, tab and newline, a no-break
    space) is `facts_no_quote` and never reaches the reconciler.
  - **The contract** (6, and the key differs from 5).
  - **The pipeline:**
    - a refused item is a COMPLETE stage's warning in `run.log` (stage table
      and STAGE_END) and `run_manifest.json` (`cross_qc_invalid`, the stage
      warnings); a clean run records zeros and no warning; a run without
      cross-QC records nothing;
    - the valve/HP pair on **both paths**: two `QC-###`, a dual-crop call each
      (`verify_images == [2, 2]`), both VERIFIED, inked on both sheets, every
      placement proven (coverage COMPLETE, WRITTEN receipts), exported to
      `findings.json`, `findings.csv` and `markup_manifest.json`;
    - with a verdict the crop cannot settle, both are investigated;
    - a `question`/`low` conflict inks on both sheets on the Low layer.

  **Failing first:** run in a `git archive` copy of `origin/main` and
  classified from `--junitxml`: **21 failed on behaviour, 29 only on the new
  API** (`CrossQCInvalidCounts`, `CrossQCResult.invalid`,
  `_drop_exact_repeats`, `ctx.cross_qc_invalid`), **6 passed**. The passes pin
  what the fix keeps: the reconcile prompt, `question`/`low` kept on both paths
  and inked on the Low layer, and identical copies collapsing to one.
- **Downstream consumers walked:**
  - **The ledger.** A newly kept conflict is an entry of its own unless the
    ledger's predicate folds it (same primary, compatible signatures with
    equal legs, text overlap ≥ 0.7, or an equal quote and ≥ 0.4). Both
    members are `cross_qc` (family `cross`), so a fold raises neither
    `reproduced` nor `confidence`. QC numbers follow position, with ties
    broken by content (WP-03.2): the pair gets two numbers and two evidence
    directories (pinned).
  - **Verification and investigation.** Each kept conflict with anchored legs
    is a dual-crop call on an exhaustive run (`_has_anchored_legs`), and an
    investigation candidate when the crop leaves it UNCERTAIN (pinned: two
    calls, two `investigation.json`).
  - **Markup.** A cloud and a tag on both sheets for each; a `question`/`low`
    conflict on the Low layer (pinned); the markup manifest's placements and
    receipts follow (pinned).
  - **Exports and report.** `findings.json`, `findings.csv` and the report
    list each kept conflict. The stage record's warning reaches `run.log`'s
    stage table (the first note; "(+N more)" when a status-deciding warning
    leads), the report's stage table (the first note), the journal's
    STAGE_END and `run_manifest.json` (all warnings and `cross_qc_invalid`).
  - **`scripts/measure_evidence_coverage.py`** reads `cross_qc_discards` only.
    Unchanged: `discards` keeps its meaning, and the new key is separate.
  - **The gauntlet** (`run_acceptance.py`): unchanged (above).
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2,
  Playwright 1.63.0):
  - Baseline before any change: **3,731 passed, 2 skipped, 10 deselected**
    (207 s) on `742d628`.
  - The 16 pinned files plus the new file after the change: 912 passed.
  - Full suite after: **3,787 passed, 2 skipped, 10 deselected** (242 s): the
    baseline plus the 56 new tests, with the same two environment skips (IPv6
    loopback; chmod as root). The instrumented fixed run above was at 55 new
    tests (3,786 passed); the 56th (the list-only guard) touches no fixture.
  - Browser suite: not run separately. No report JS, HTML or chat code
    changed, and the browser tests ran inside the full suite.
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds only
    `pipeline.normalize_specs_text`, on `main` already (WP-22.5).
    `scan_secrets.py` is clean over 206 tracked files, the new one included.
    `compileall src` passes.
- **Docs:**
  - **CHANGELOG** (Fixed): B6 and N2, with the visible effect, the extra
    verification calls, the accepted limits and the cache note.
  - **CLAUDE.md:** the finder bullet, the counters paragraph (refused items on
    both paths; only identical findings collapse; the whitespace fact) and the
    two contract-history sentences.
  - **README:** "Cross-sheet QC" (a paragraph on uncertain conflicts, refused
    items and repeats) and the cache bullet's contract history.
  - **The plan:** the WP-06 Step 4 and Step 5 notes, and an acceptance note
    (N30 dependency; the criterion is unchanged).
  - **DECISIONS:** the D-2 note, the D-4 note and one register row.
  - **PROGRESS:** this entry; the WP-06.1, B6, N2 and N30 rows; notes on
    WP-06.2, WP-06.3, WP-06.4, WP-03.5 and INT.1.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Not measurable without real drawings (O-10): how often the model
  returns an invalid item now that the prompt is fixed; how many conflicts
  share one quote on one pair of sheets (each kept one is a new verification
  call); how often a re-report is phrased apart (a kept duplicate); how often
  N30 folds two real conflicts. Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **More paid calls, by design:** each distinct conflict that used to vanish
    is now a dual-crop call on an exhaustive run, plus an investigation if the
    crop cannot settle it.
  - **Kept duplicates, the accepted cost:** a re-report phrased apart stays two
    findings, clouded twice on each sheet (WP-06.4's same-claim predicate).
  - **N30:** terse same-pair conflicts can still fold in the ledger (WP-03.5).
  - **A refused item is a warning, not a status** (the owner's decision), so a
    run that lost items can still read COMPLETE; the warning says how many.
- **Re-checked (U31):** validation's accepted set is unchanged (the
  sixteen-item table runs through both validators); the grounding path,
  `fact_tile_lookup`, the discard counters and the reconcile prompt are
  untouched; `critique._is_duplicate` and the ledger are untouched (the merge
  rule's pinned fingerprint holds).
- **Found, not fixed:**
  - `_parse_facts` skips a fact that is not an object, and the validators a
    leg that is not an object, with no counter (on the same line as the 40-fact
    cap; note on WP-06.3).
  - The whole-set path still drops an item it cannot place on two sheets
    uncounted (an INFO line); note on WP-06.2.
  - The pair fan-out fixture's presence check is vacuous:
    `tests/test_drawing_cross_qc.py::_MapReconcileClient` answers only "when
    BOTH its sheets' handles are actually present in this reconcile call", but
    it searches the whole request body, and the reconcile input's SHEET
    MANIFEST lists every handle. So the finding came back from all 36 pair
    calls (instrumented), and `test_reconcile_all_pairs_finds_conflict_across_fact_groups`
    cannot show that only the pair uniting the two groups found it. A faithful
    check reads the FACTS lines. Note on INT.1.
- **Next:** WP-09.1 (Wave 1, no dependencies; the next `todo` row). WP-06.4
  still waits on WP-03.4.

### 2026-09-24 — WP-05.2: the anchor matches whole source words, punctuation folded ([PR #166](https://github.com/Abe-Borg/drawing-analyzer/pull/166))

- **Slice and IDs:** WP-05.2. N12 (implemented+validated: its anchor part
  here, its cross-QC part in WP-05.1). B4's punctuation part
  (implemented+validated; its character-stream part stays open for WP-05.3).
  No `DECISIONS.md` contract is decided: the matching rules are none of D-1 …
  D-8. The owner's four choices are recorded here, in the plan's WP-05 step 1,
  2 and 3 notes and in CLAUDE.md. D-4 gains a WP-05.2 note, and the migration
  register gains one row (the cross-QC contract bump). WP-05 is not done
  (WP-05.3 remains), so there is no package acceptance check.
- **Base.** `main` = `origin/main` = `1ef1a92`; no drift. Baseline
  **3,524 passed, 2 skipped, 10 deselected** (227 s), identical to the
  WP-05.1 handoff.
- **Reproduced first** (a probe script on `1ef1a92`, with word tuples built the
  way `tests/test_drawing_anchor.py` builds them), each as the request stated:
  - **N12.** These four were EXACT/`exact` on the longer tag:
    - `VAV-2` on `VAV-2-1 SERVES ROOM 12`;
    - `AHU-1` on `SEE AHU-1-2 SCHEDULE`;
    - `ACCESS PANEL AT VAV-2` on `…VAV-2-1 TYP`;
    - `2-1 SERVES` on `VAV-2-1 SERVES ROOM`.

    The 17-token note quoting `VAV-2` was FUZZY/`fuzzy_window` on the note
    printing `VAV-2-1`: the window left out `PROVIDE` and took in the `1`.
  - **B4.** `RATED 175 PSI TYP`, `NOTE 3`, `150 GPM 568 L/MIN`, and `P-1` on
    `SEE P-1, TYP` and on `SEE (P-1), TYP` were UNANCHORED. Cross-QC grounded
    `NOTE 3` and both `P-1`s (the WP-05.1 disagreement), but not the other
    two.
  - **Right already, and kept:** `6"`/`6'`, `AHU-10`/`AHU-101`, `5`/`.5`,
    `P-1 SERVES`/`XP-1 SERVES` and `-5`/`5` were all UNANCHORED.
- **Facts confirmed, not assumed:**
  - **The 17-token window's edges are whole words** (`ACCESS` … `4`), so a
    boundary on the window's edges alone does not refuse it; the `1` sits
    inside.
  - **A boundary on EXACT alone only moves the problem.** Every N12 match
    that EXACT refuses falls through to the window at 100% overlap (`VAV-2`
    becomes FUZZY on `VAV-2-1`). Measured in the option table and in the suite
    (`1/2" + 2 1/2" = 4"` became a full-overlap window).
  - **`_Stream.find_subsequences`** served EXACT and the sub-phrase tier. Both
    now match through `SourceWords`, and it is gone (private, no other caller).
  - **The veto compares tokens for equality**, so the fold has to be in the
    tokens both sides see. `word_core`'s own sets would fold `"` and `'`, which
    makes `6"` equal `6'`, hence a narrower fold set.
  - **`numbers_grounded` lists methods.** A folded match keeps `exact`, so it
    grounds (the owner's choice).
  - **Caches.**
    - The anchor stage is not cached (pipeline 1933–1963).
    - The verification keys carry the anchor's status, method and rect, and
      the investigation key carries its rect. So a moved anchor re-keys that
      finding's entries: a paid re-check, by design.
    - The critique cache stores findings before anchoring, and its merge rule
      reads no rectangle (WP-03.7). The merge-rule fingerprint and the
      critique contract are unchanged.
    - `_CROSS_QC_CACHE_CONTRACT` goes 4 → 5 because the owner chose one
      matcher.
    - The A/B `RECORD_CONTRACT_VERSION` stays 3: a record stores the anchor as
      an arm output whose shape and meaning are unchanged, as for WP-05.1.
  - **Tests import** only these from `anchor.py`: `_normalize`, `_CHAR_FOLD`,
    `_FUZZY_WINDOW_MIN_OVERLAP`, `_fuzzy_window_slack`, `_base_cell`,
    `numbers_grounded`, `SourceWords`, `source_words`, `word_core` and the two
    resolvers. So `_Stream` and the span helpers could be rebuilt.
  - **A word's text can contain a space** in fixtures (`"SCALE 1/8"`,
    `tests/test_evidence_visual.py`). So `SourceWords` splits each sheet word's
    text into source words that keep that word's index, as the token stream
    did.
- **The decision, made by the owner before any code** (AskUserQuestion with
  measured options). Chosen, each as recommended:
  - **Boundary: all three tiers plus a word veto.**
    - EXACT and the sub-phrase tier match only whole words.
    - A window must start on a word's first token and end on one's last.
    - Inside a window, a quote's measurement may not match part of a sheet
      word: every digit-bearing token of a word a measurement aligned to must
      be aligned too.

    Not taken:
    - a veto refusing any digit the window adds. It also refused a window
      whose sheet prints a number the quote left out (a `(689 KPA)`
      conversion), and it moved two fixture windows to the sub-phrase tier,
      breaking the pinned `test_fuzzy_window_on_token_off`;
    - EXACT (and sub-phrase) only: this fails every required N12 case.
  - **Fold: sentence punctuation and brackets.** Leading `( [ {` and trailing
    `) ] } , ; : . ! ?`, on the sheet's words and the quote's alike. Never
    folded: `"` `'` (inch and foot marks), `<` `>`, `%`, `/`, `-`, a leading
    `.`. At a match's two ends, `word_core` still leaves the sheet's `"` `'`
    `<` `>` outside it, as cross-QC does.

    Not taken: also folding `<` and `>` (the request's example, word_core's
    sets minus `"` and `'`). It makes a comparison sign cosmetic inside a
    span, so `SET 5 PSI MAX` would be EXACT on `SET <5 PSI MAX`.
  - **Cross-QC: one matcher**, with `_CROSS_QC_CACHE_CONTRACT` 4 → 5. Not
    taken: keeping WP-05.1's rule with the disagreements recorded.
  - **Method: a folded match keeps EXACT/`exact`.** Not taken: a method of its
    own (`exact_folded`). Measured: the pinned `FLOW TEST: 20 20 20 TOTAL
    540 …` claim, trusted through a FUZZY window, would have lost its trust.
  - **Measured first**, as the request asked. A scratch copy of `origin/main`
    logged, per finding with the test name, today's anchor (recomputed by the
    probe, and equal to the real one on all 422) beside 7 option combinations
    (boundary tiers × window veto × fold set × method).
    - The hooks ran **314 `resolve_anchors` calls (422 findings and legs), 145
      `audit_arithmetic` calls (168 findings), 18,148 `assign_qc_ids` calls
      (113 with recorded anchors) and 571 cross-QC `_grounded` calls**. There
      were 2 probe errors, both from tests that monkeypatch a provenance
      helper to raise.
    - Under the chosen rule, 4 anchors changed, all in
      `tests/test_arithmetic_operand_grounding.py`. No arithmetic promotion,
      QC number or cross-QC verdict changed. A method of its own would have
      demoted one promotion.
    - The fixtures did not decide; a table of 48 required and edge cases
      through every option did.
- **What changed:**
  - **`anchor.py`** (it still imports no PDF engine; `_normalize` is
    untouched):
    - `WORD_LEADING_FOLD`, `WORD_TRAILING_FOLD` and `fold_word` (new, next to
      `word_core`), and `_fold_text`. `_tokenize` now folds word by word.
    - `SourceWords` is built from a string or from `words=`. It gains `folded`,
      `index`, `spans()`, and `find()` (remembered per query), and `contains()`
      matches the folded words. `normalized` is unchanged (still exactly
      `_normalize(text)`, pinned), so `_sheet_is_textless` is too.
    - `_Stream` is built on `SourceWords` (tokens from the folded words), with
      `covered`, `span_words`, `on_word_edges` and `word_tokens`.
      `find_subsequences`, `positions` and `subsequence_cache` are removed.
    - EXACT and the sub-phrase tier go through `SourceWords`. The window
      qualifies only on whole-word edges, and `_measurements_whole` runs
      after `_numbers_aligned` (which now returns the span positions it used).
    - The span helpers work on word sets (`_words_rect`, `_words_text`,
      `_tile_preferred`), and `_anchor_one` returns the matched words.
    - Docstrings: the module docstring (the tiers, and its false "folds most
      of them"), `_NUMBER_GROUNDING_METHODS`, `resolve_anchors`.
  - **`cross_qc.py`:** `_CROSS_QC_CACHE_CONTRACT` 4 → 5 with its reason, and
    the `_grounded` docstring (`_grounded` already called
    `source_words(text).contains(quote)`, so grounding needed no code change).
    The fact-tile join keys on the same folded form (`_norm_for_match` is
    `anchor._fold_text`), and a quote that folds to nothing joins nothing:
    the Codex review, below.
  - **Codex review, P2, fixed in this PR** ("use the folded form for cross-QC
    fact tile joins"). The first push kept `_norm_for_match` (the join key) on
    `_normalize` alone. So a leg that grounded only through the fold (the fact
    recorded `RATED 175 PSI, TYP.`, the reconcile call quoted `RATED 175 PSI
    TYP`) lost its fact's tile, which on a scanned sheet is its only location:
    UNANCHORED, and no crop check. And two facts spelled apart only by that
    punctuation, in different tiles, did not collide, so a leg took one tile
    by guess. Both reproduced on the first push (`7e2f4c4`). Root cause, not
    only the example: the join key is the matcher's own form, so the two can
    never again disagree on what is "the same text"; a quote that folds to
    nothing (a comma, brackets, blanks) names no text and joins nothing, which
    also closes a join WP-05.1 left open (a blank leg quote inherited a
    whitespace-only fact's tile). Instrumented over the whole suite: 69 lookup
    builds and 14 lookup sites (legs without a model tile label), of which 5
    builds and 1 site change, all in the new tests. Re-baselined:
    `tests/test_cross_qc_grounding.py::test_n13_cross_qc_matches_with_the_anchors_normalizer`,
    which pinned the join key as `_normalize` alone; it now reads the rule
    directly (the inline `_fold`), and still checks the N13 folds.
- **Speed.** Measured on synthetic dense sheets with 60 quotes each:
  - 3,000 words: 0.05 s, against 0.07 s on `origin/main`;
  - 15,000 words: 0.23 s, against 0.35 s.

  A quote recurring 250,000 times inside one 1,000,000-character word anchors
  in about 0.1 s, the stream included. The scan keeps WP-05.1's skip to the
  next word.
- **Contracts decided:** none of D-1 … D-8; a D-4 note.
- **Cache/schema effects:**
  - `_CROSS_QC_CACHE_CONTRACT` 4 → 5 (one register row): every cross-QC entry
    misses once. No release has shipped contract 4, so a user upgrading from
    1.7.0 pays one miss for both bumps.
  - **The fold only adds matches, with one exception:** a quote made only of
    brackets and sentence punctuation (`,`, `(`, `.`) folds to nothing. It now
    matches nothing, where it used to ground on a lone punctuation word.
    Measured over 20,057 pairs: 174 matches gained, and every one of the
    1,146 lost was such a quote (pinned).
  - A finding whose anchor moved re-keys its verification and investigation
    entries through their own inputs: new paid work, not a register row.
  - No other key, prompt version, schema or finding id changed.
    `tests/test_drawing_cache_identity.py`, `tests/test_source_identity.py` and
    `tests/test_ab_findings_diff.py` pass unchanged.
- **Re-baselined tests (8)**, each with its reason recorded in the test:
  - **Arithmetic, each given the case it models under the new rule:**
    - `tests/test_arithmetic_operand_grounding.py::test_a_fuzzy_anchor_with_the_numeric_veto_grounds_its_operands`:
      its one differing token was `TEST:`, which now folds and so no longer
      differs. It is now `TESTS`.
    - `::test_the_sheet_must_print_the_operand_the_quote_reads`: its quote
      started inside `2-1/2"` and no longer anchors. The case is now a quote
      that anchors whole-word (`2-1/2"` against a printed `2½"`) but reads a
      number the sheet's words do not print as one value. The old quote is
      kept, asserted UNANCHORED and still transcribed.
    - `::test_resolve_anchors_reports_the_sheet_words_each_quote_matched`: its
      quote now spells `2 1/2"`, so the sheet's words (`2-1/2"`) are reported
      as printed.
  - **The three contract tripwires**, 4 → 5 (`tests/test_drawing_cross_qc.py`
    also checks the key differs from contract 4).
  - **`tests/test_cross_qc_grounding.py::test_the_matcher_gives_the_rules_answer_everywhere`:**
    its reference matcher, `_reference_contains` ("the rule read directly"),
    gains the fold. It is written out inline, so the base can still import it.
  - **`tests/test_cross_qc_grounding.py::test_n13_cross_qc_matches_with_the_anchors_normalizer`**
    (with the Codex fix): the join key is the folded form, read inline the same
    way.

  **Checked both ways:**
  - `origin/main`'s versions of the five edited files, run against the fixed
    tree, fail exactly these 8; the other 253 pass, including all of
    `tests/test_drawing_anchor.py`, unchanged.
  - The edited files, run against the base, fail 6 (the tripwires, the
    reference matcher, the join-key test, the `2-1/2"` case). The other 219
    pass, including the two arithmetic re-baselines, whose new constructions
    hold on both trees.
- **Fixture effects, instrumented over the whole fixed suite** (at 197 new
  tests, before the five punctuation-only cases). A scratch copy loaded
  `origin/main`'s `anchor.py` beside the new one.
  - The hooks ran **517 `resolve_anchors` calls (626 findings and legs), 148
    `audit_arithmetic` calls (171 findings), 18,149 numberings (114 with
    recorded anchors) and 677 grounding calls**, with the same 2 probe errors.
  - **87 anchors change**; 86 are in the new file. The only other is the
    re-baselined `2-1/2"` sub-case.
  - 10 grounding verdicts, 1 arithmetic promotion and 1 renumbering change,
    all in the new file.
- **New tests:** `tests/test_anchor_whole_words.py` (207 tests):
  - **B4:** the three pairs and the tag forms, with the span as printed;
    quote-side punctuation; `"` `'` `<` `>` left outside a match's ends; a lone
    punctuation word; verbatim quotes unchanged; the veto over a punctuated
    window; every veto substitution on punctuated text; 17 negatives.
  - **N12:** the four cases, the two 17-token windows, `1/2"` in `2-1/2"`, a
    sub-phrase starting inside a word, a tag printed alone and inside a longer
    one (both orders), `PRE-ACTION`, six whole-word matches kept, and
    WP-05.1's cut-word and whole-word tables through the anchor.
  - **Recorded limits:** the letter-only tag, the four WP-05.3 cases, and the
    separated unit.
  - **Agreement:** one table of 102 rows through both matchers (EXACT exactly
    where cross-QC grounds); cross-QC admits such legs and facts; the WP-05.1
    `P-1,` disagreement is closed; a punctuation-only quote matches nothing;
    the tile join (a reconciled leg inherits its fact's tile across folded
    punctuation and is then crop-verifiable; two such spellings in different
    tiles collide; a quote that folds to nothing locates nothing).
  - **The rule is defined once** (the fold sets pinned against word_core's).
  - **Consumers:** arithmetic both ways; verification and investigation both
    ways; the pipeline.
  - **Cost:** the anchor over one long run.

  **Failing first:** run in a `git archive` copy of `origin/main` and
  classified from `--junitxml`: **86 failed on behaviour, 2 only on the new API**
  (`WORD_LEADING_FOLD`, `SourceWords(words=)`), **119 passed**. The passes pin
  what the fix keeps: the negatives, the whole-word matches, the recorded
  limits, the agreement rows that already agreed, and the cost guard.
- **Downstream consumers walked:**
  - **Verification** (`_is_verifiable`, `_has_anchored_legs`) **and
    investigation** (`_candidates`, `_payload_hash`):
    - a newly anchored finding or leg becomes eligible: one crop call on an
      exhaustive run, plus an investigation if the crop cannot settle it;
    - an N12 finding that no longer anchors loses both, and the call.

    Pinned, including through the pipeline (`verify_calls == 1`).
  - **Arithmetic.** `numbers_grounded` is true for a folded EXACT (`exact`).
    `matched_text` is the sheet's words as printed, with their punctuation.
    `_operands_grounded` scans `540.` and `(540)` as 540 (the tail rule needs a
    digit after a `.` or `,`). `_relationship_grounded` treats `, ; : . ( ) [ ]`
    as filler; `{ } ! ?` between two numbers make a relationship unreadable
    (the safe direction), and a leading or trailing one is never read. Pinned:
    `20 + 20 = 540` on `(20 + 20 = 540)` is DETERMINISTIC; a quote starting
    inside `2-1/2"` stays model-transcribed. The one fixture promotion the
    probe saw is that test.
  - **Markup, manifest and numbering.**
    - A newly anchored finding gets a cloud (`CLOUD`) instead of a
      `[QUOTE NOT FOUND]` margin callout (`MARGIN`); an N12 finding gets the
      reverse.
    - The markup manifest's placements and receipts follow.
    - QC numbers follow position (the pipeline test's two findings swap
      numbers).
    - Pinned through the pipeline (`ctx.markup_run.placements`).
  - **Cross-QC legs** (`resolve_conflict_legs`) go through the same resolver:
    a leg quoting `P-1` on `SEE P-1, TYP` is now EXACT, and `_has_anchored_legs`
    sees it (pinned). The tile fallback is untouched: it is still for
    TEXT_EVIDENCE_UNAVAILABLE only, and its tests pass unchanged.
  - **Exports and report.** `findings.csv`'s anchor columns and
    `findings.json`'s anchor follow. The report chip moves between "Unanchored"
    and the verification state. The A/B record stores the same anchor shape.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - Baseline before any change: **3,524 passed, 2 skipped, 10 deselected**
    (227 s) on `1ef1a92`.
  - Every pinned file the request named, plus the new file: **1,091 passed**
    (at 197 new tests).
  - The full suite after the change:
    - **3,721 passed, 2 skipped, 10 deselected** (222 s), with 197 new tests;
    - **3,726 passed, 2 skipped, 10 deselected** after the five
      punctuation-only cases (203 s; the first push);
    - **3,731 passed, 2 skipped, 10 deselected** with the Codex fix's five
      join tests (213 s; the final count).

    The same two environment skips (IPv6 loopback; chmod as root).
  - Browser suite: not run separately. No report JS, HTML or chat code
    changed, and the browser tests ran inside the full suite.
  - Lint and scans: see the PR body.
- **Docs:**
  - **CHANGELOG** (Fixed): B4's punctuation part and N12's anchor part, with
    the visible effect, the new and lost verification calls, the accepted
    limits and the cache note. The WP-05.1 entry's "not in this change" now
    points to it.
  - **CLAUDE.md:** the grounding paragraph (one matcher, the fold, contract
    5), the text-normalization paragraph, and the Disposition paragraph's
    anchor tiers.
  - **README:** "Anchoring findings" (whole words; the fold; the false
    "folds most of them" replaced), the cross-sheet QC paragraph, and the
    cache bullet's contract history.
  - **The plan:** WP-05 step 1, 2 and 3 notes and the cache note (with the
    correction that a boundary on EXACT alone does nothing).
  - **DECISIONS:** the D-4 note and one register row.
  - **PROGRESS:** this entry; the WP-05.2, B4 and N12 rows; notes on WP-05.3
    and WP-21.4.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Not measurable without real drawings (O-10):
  - how many real findings differ from their sheet only in punctuation, and so
    newly anchor, get a cloud and get a crop call;
  - how many quote a tag printed only inside a longer one, and so lose their
    (wrong) cloud and their crop call;
  - how often the recorded limits occur.

  Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **More paid calls, and fewer**, by design: each newly anchored finding
    costs a crop call on an exhaustive run; each N12 finding no longer gets
    one.
  - **Recall costs the owner accepted, and recorded limits:**
    - a quote that cut the start of a hyphenated word (`ACTION` in
      `PRE-ACTION`) no longer anchors EXACT on it. It anchors on the words it
      covers whole, or not at all;
    - a letter-only tag (`VAV-A` in `VAV-A-1`) inside a long window still
      anchors;
    - a sub-phrase can drop a unit printed as its own word (WP-05.3);
    - the four character-stream cases (WP-05.3);
    - a tight list (`P-1,P-2`) is one source word (as in WP-05.1).
  - **The word veto checks the numeric veto's greedy alignment.** A number
    that could align either inside a longer tag or to a standalone copy within
    the slack may be refused (UNANCHORED, the safe direction, never a wrong
    cloud).
  - **At a match's end, the owner's WP-05.1 `word_core` leaves a sheet's `"`
    or `<` outside it.** So a quote `PROVIDE 6` anchors EXACT on `PROVIDE 6"`,
    and `5 PSI` on `<5 PSI`. Cross-QC has grounded these since WP-05.1; the
    anchor now agrees.
- **Re-checked (U31):**
  - `anchor._normalize` is byte-identical: the `_UNICODE_DASHES` pin and every
    test in `tests/test_drawing_anchor.py` pass unchanged, the 0.85 assertion
    included;
  - the tile fallback and `reduced_trust_reason` are untouched;
  - `SourceWords.normalized` still equals `_normalize(text)` (pinned).
- **Found, not fixed:** README and `help_content.py` call the unanchored label
  `[UNANCHORED]` while the markup writes `[QUOTE NOT FOUND]` (note on WP-21.4).
- **Next:** WP-06.1 (Wave 1, no dependencies). WP-05.3 (Wave 2) is now
  available; WP-05 is done only when it lands and the Acceptance paragraph
  holds.

### 2026-09-23 — WP-05.1: cross-QC grounding is a real, whole-word match on the anchor's normalizer ([PR #165](https://github.com/Abe-Borg/drawing-analyzer/pull/165))

- **Slice and IDs:** WP-05.1. B5 and N13 (implemented+validated); N12's
  cross-QC part (implemented+validated; its anchor part stays open for
  WP-05.2). No `DECISIONS.md` contract is decided: the grounding rules are none
  of D-1 … D-8. The owner's four choices are recorded here, in the plan's WP-05
  step 1 and step 3 notes, and in CLAUDE.md. D-4 gains a WP-05.1 note, and the
  migration register gains one row (the contract bump). WP-05 is not done
  (WP-05.2 and WP-05.3 remain), so there is no package acceptance check.
- **Base.** `main` = `origin/main` = `d75e39c`; no drift since the request was
  written. Baseline identical to the WP-07.2 handoff (below).
- **Reproduced first** by the new tests on a `git archive` copy of
  `d75e39c`:
  - B5: `P-1`, `AHU-1` and `M-101` on a textless sheet, and `AHU-7` on a sheet
    that does not print it, are all TEXT_GROUNDED. The `AHU-7` leg is kept and
    counted as grounded; the textless leg is UNANCHORED and invisible to
    `_has_anchored_legs`.
  - N12: `AHU-10` grounds inside `AHU-101`, and so does a long quote ending
    inside a tag.
  - N13: `PROVIDE 6” DRAIN`, `2½"`↔`2-1/2"`, `O6`/`Ø6`, `300×200`, primes,
    curly quotes and a fraction slash are NOT_MATCHED.
  - Through the pipeline: a scanned sheet's `P-1` conflict gets no verification
    call, and an `AHU-7` conflict survives.
- **Facts confirmed, not assumed:**
  - **What cross-QC grounds against.** A string (`sheet_evidence_text(geom)`,
    the uncapped `full_sheet_text`), not word tuples. So "word boundary" is
    defined on the string's whitespace-delimited source words.
  - **Why the boundaries need source words.** `anchor._normalize` turns an
    infix hyphen into a space (`VAV-2-1` is `vav 2 1`), and a token-boundary
    match on the normalized string still finds `vav 2`. So the boundary is
    checked against source words that are normalized one at a time.
  - **Per-word normalization is exact.** Joining the per-word results gives
    exactly `_normalize(text)`:
    - whitespace survives the normalizer: NFKC maps whitespace to whitespace,
      and `_CHAR_FOLD` touches none (the invisibles it strips are not
      `isspace()`);
    - nothing it changes reaches across a space (NFKC composition, the `''`
      pairing, the infix-hyphen lookarounds, final-sigma lowercasing);
    - confirmed on all 464 evidence strings the suite passes to the classifier
      (probe), and pinned over a Unicode corpus.
  - **The order.** With a real match, testing the match after the no-text
    test changes nothing for a non-empty quote on empty evidence, because it
    cannot match. Two deliberate edges are pinned:
    - "no usable text" is now "the normalizer leaves nothing", so a layer of
      zero-width characters is textless (UNAVAILABLE);
    - a quote made only of invisibles matches nothing (NOT_MATCHED on a
      text-bearing sheet, where the shortcut used to ground it). The blank-quote
      test is unchanged (`.strip()`), so it still agrees with the counters and
      `reduced_trust_reason`.
  - **The consumers of the verdict:** leg admission (`_finding_from_handles`),
    fact admission (`_parse_facts`), the `CrossQCDiscardCounts` counters, the
    stored `evidence_state`, and the anchor's tile fallback. `fact_tile_lookup`'s
    join key goes through the same normalizer. Only the sharded path grounds:
    `_validate_cross_item` (whole-set) grounds nothing (U8, WP-06.2).
    Instrumented: the gauntlet and `tests/test_drawing_qc_pipeline.py` never
    reach the classifier, so the gauntlet's whole-set `CROSS_CONFLICT` cannot
    move.
  - **Other keys.** Only `_CROSS_QC_CACHE_CONTRACT` moves (3 → 4).
    `tests/test_drawing_cache_identity.py` and `tests/test_source_identity.py`
    pass unchanged.
  - **`verify.py` needs no edit** (TILE anchors pass `_is_verifiable` and
    `_has_anchored_legs`).
  - **`arithmetic._UNICODE_DASHES`** is still equal to the anchor's fold set,
    which is untouched; its pin passes.
- **The decision, made by the owner before any code** (AskUserQuestion with
  measured options). Chosen, each as recommended:
  - **Boundary: whole source words.** A match may start and end only on a
    source word's core (`anchor.word_core`): the whitespace-delimited word
    without leading `( [ { < " '` or trailing `) ] } > , ; : . ! ? " '`.
    Not taken:
    - a character-context rule (the character just outside is not a letter or
      digit, not a space the fold put inside a word, not `-`/`.` attached to
      an alphanumeric, not `,` `/` `:` between digits). It grounds a tag in a
      tight list, which the anchor then cannot place.
    - the request's example rule as stated (not a letter or digit, not a
      hyphen or dot followed by an alphanumeric). Measured: it grounds `12` and
      `500` in `12,500`, `2"` in `1/2"`, `1` in `1/2`, and `12` in `12'-6"`.
  - **Sharing: defined once in `anchor.py`.** The anchor's tiers do not use it
    yet; WP-05.2 applies it to `_Stream`'s words (its row). Not taken: keeping
    it in `cross_qc.py`.
  - **Normalizer: `anchor._normalize` per source word** (`anchor.SourceWords`),
    unchanged. Not taken: factoring out a fold without the infix-hyphen step;
    lowercasing before or after that step differs on rare Unicode (`İ-5`).
  - **Short quotes: a real match at any length.** Not taken: a floor under two
    letters or digits. It makes such a quote UNAVAILABLE even on a
    text-bearing sheet: admitted at reduced trust, a paid crop check, a false
    "No searchable text on this sheet", and the short negatives (`5` in `-5`,
    `1` in `1.5`) admitted instead of dropped.
  - **Measured first**, as the request asked. A scratch copy of `origin/main`
    logged, per call with the test name, today's verdict next to 10 option
    combinations (normalizer × boundary rule × length floor × order), plus the
    old and new tile-join keys and the tile at every lookup site.
    - The hooks ran **464 classify calls in 36 tests** (344 from `_parse_facts`,
      112 from `_finding_from_handles`, 8 direct), 57 findings, 56 lookup
      builds and 99 lookup sites, with 0 probe errors. Today's verdict,
      recomputed by the probe, matched the real one every time.
    - **Every option moved the same single verdict:** a filler leg quoting `q`
      in `tests/test_drawing_acceptance.py::test_acceptance_failed_shard_holds_cross_qc_partial`.
      It went G→N under a real match and G→U under a floor; its finding has
      `also_on: []` and is dropped either way.
    - No finding admission and no tile changed, so the fixtures did not
      decide. A second table of 48 required and edge cases through all 10
      combinations did.
- **What changed:**
  - **`anchor.py`** gained a new pure section (no PDF engine):
    - `WORD_LEADING_PUNCTUATION`, `WORD_TRAILING_PUNCTUATION` and `word_core`;
    - `SourceWords`, which holds the per-word normalized text, the word
      starts and each word's core offsets. `contains` tries every occurrence
      that could start a word and checks both edges against those cores (the
      Codex item below);
    - `source_words(text)`, an `lru_cache` of 128.

    `_normalize`, `_Stream` and every tier are untouched, so no anchor can
    move. Every test in `tests/test_drawing_anchor.py` passes unchanged,
    including the 0.85 assertion.
  - **`cross_qc.py`:**
    - `_norm_for_match` is `_normalize`;
    - `_grounded` is `source_words(text).contains(quote)`, with no length
      shortcut;
    - `_sheet_is_textless` asks the normalizer, and `classify_quote_evidence`
      now asks it;
    - `classify_quote_evidence` runs in the plan's order: no quote, no usable
      text, the match, the word-free tile, then NOT_MATCHED;
    - `fact_tile_lookup` code is unchanged (docstring updated), and the
      `fold_text` import is dropped;
    - `_CROSS_QC_CACHE_CONTRACT` 3 → 4, with its reason.
  - **Speed.** Indexing a 15,000-character sheet (2,500 words) takes 3 ms, and
    a 40,000-word one 48 ms, once per distinct text. A match takes 0.1–1.4 ms
    per quote. The old check re-normalized the whole sheet text on every call.
  - **Codex review, P2, fixed in this PR** ("cache word-core offsets instead of
    slicing per occurrence"). `SourceWords.contains` re-derived a word's core
    from a slice of that word at every occurrence of the quote, so a quote
    recurring inside one long whitespace-free run (a garbled or per-glyph text
    layer) cost time quadratic in the run's length. Measured on the first push
    (`7b4ee53`), with the run between real words: 0.02 s, 0.08 s and 0.28 s for
    runs of 50,000, 100,000 and 200,000 characters, and 10.0 s and 11.2 s for a
    1,000,000-character run. (A run that is the whole text looked fast, because
    CPython returns a full-length slice without copying.) Root cause, not only
    the slice:
    - each word's core offsets are computed once, when the text is indexed;
    - an occurrence that starts inside a word's core skips to the next word,
      since no match can start there, so the scan is bounded by the number of
      words, not by how often the quote recurs inside one.

    The same 1,000,000-character run now matches in 0.6 ms. No answer changes:
    pinned against a direct reading of the rule over every table in the test
    file and 600 generated pairs.
- **Contracts decided:** none of D-1 … D-8. D-4 gains a note: the cross-QC
  contract term covers host-side grounding and is not split by path.
- **Cache/schema effects:**
  - `_CROSS_QC_CACHE_CONTRACT` 3 → 4 (one register row). Every cross-QC entry
    misses once, on both paths: a set of 40 sheets or fewer is one Opus call,
    a larger one its map and reconcile calls.
  - It retires the WP-03.3 and WP-07.2 stored-claims residuals.
  - No other key, prompt version, schema or finding id changed.
  - The A/B `RECORD_CONTRACT_VERSION` stays 3. A record stores
    `evidence_state` as an arm output whose shape and meaning are unchanged, so
    a delta between arms run before and after is the code change it is (as for
    WP-07.1).
- **Re-baselined tests: the three contract tripwires**, value 3 → 4 with the
  reason recorded in each:
  - `tests/test_drawing_cross_qc.py::test_cross_qc_contract_bumped_for_the_norm_id_fold`,
    which now also checks the key differs from contracts 2 and 3;
  - `tests/test_evidence_visual.py::test_contract_counter_is_not_bumped_by_this_package`;
  - `tests/test_evidence_tail.py::test_no_cross_qc_contract_bump_was_needed`.

  Checked both ways:
  - the original pinned files run against the fixed tree fail exactly these
    three, and the other 322 pass;
  - the edited files run against the base fail these three and the three new
    short-tag cases below, and the other 92 pass.

  **Extended, not re-baselined:**
  `tests/test_evidence_visual.py::test_a_recovered_finding_reaches_verification_and_investigation`
  is parametrized over `SCANNED_QUOTE`, `P-1`, `AHU-1` and `M-101`, with each
  state taken from the real classifier (the plan's instruction, rather than
  editing `verify.py`). Its original case passes on both trees; the three
  short tags fail on the base ("the dual-crop check cannot see it").
- **Fixture effects, instrumented over the whole fixed suite.** A scratch copy
  of the fixed tree logged origin/main's rule, recomputed, beside the real new
  outcome for every verdict, finding and tile join.
  - The hooks ran **585 classify calls in 119 tests** (357 from `_parse_facts`,
    135 from `_finding_from_handles`, 93 direct), 68 findings, 63 lookup builds
    and 109 lookup sites, with 0 probe errors.
  - **77 verdicts change** (G→N 41, G→U 21, N→G 14, U→G 1). 70 are in the new
    file. Outside it there are only two: the `q` filler leg above (no assertion
    reads it), and the six short-tag verdicts of the extended test.
  - 5 finding admissions change, 2 lookup sites change tile, and 2 lookup
    builds change tiles: all in the new file.
  - 22 lookup sites change only the key's spelling (`pre-action` becomes
    `pre action`) and join the same tile (`tests/test_evidence_tail.py`,
    `tests/test_evidence_visual.py`, the new file).
  - Only the three sharded-path acceptance tests reach the classifier.
- **New tests:** `tests/test_cross_qc_grounding.py` (96):
  - **B5.** Short tags on a textless sheet are unavailable; printed, they
    ground; absent, they are NOT_MATCHED, the leg is dropped and counted, and a
    conflict left with one leg is dropped. The textless leg is TILE-anchored
    and verification- and investigation-eligible. Facts both ways. A
    zero-width text layer is no text, a zero-width quote matches nothing,
    blanks are unchanged, and any length gets a real match (6 rows).
  - **N12.** 12 cut-a-word cases (long quotes, a first letter cut, tight
    lists), 12 whole-word cases, and a dropped leg.
  - **N13.** 15 fold cases and 18 changed-number or changed-unit cases.
    `_norm_for_match` is `_normalize`, and per-word normalization equals the
    whole-string one over 20 texts (NFKC-made spaces, whitespace variants,
    words of invisibles, `''`, final sigma, a dotted capital I, a ligature,
    fullwidth).
  - **The shared rule** (`word_core` and the two punctuation sets).
  - **The tile join**: a reconciled leg joins its fact across a curly inch
    mark, and two facts spelled that way collide.
  - **The sharded path end to end**, both directions, with the counters.
  - **The pipeline**: a scanned sheet's `P-1` conflict gets one dual-crop call
    with two images and ends VERIFIED, while an `AHU-7` conflict the sheet
    does not print never becomes a finding and gets no call.
  - **Cost (the Codex review).** The matcher agrees with a direct reading of
    the rule on every table and 600 generated pairs; a match never re-derives
    a word's core; a quote recurring 250,000 times inside a 1,000,000-character
    run matches in under a second (two shapes). On `7b4ee53` the last three
    failed (10.0 s and 11.2 s) and the agreement test passed, as it should.
- **Downstream consumers walked:**
  - **Admission and counters.** A made-up short-tag leg or fact is dropped and
    counted `*_ungrounded_quote_text_bearing_sheet`; it used to be counted
    grounded. A short tag on a textless sheet is admitted and counted
    `*_admitted_no_text_evidence`, also formerly counted grounded. The N13 legs
    that used to be dropped are kept.
  - **`evidence_state` and `reduced_trust_reason`** (untouched). A textless
    short-tag leg shows `[NO TEXT TO CHECK]` / "No searchable text on this
    sheet" on the drawing and the report's quote-cell note, which is true
    there. On a hybrid sheet's pixels-only region the same words appear
    although the sheet has text elsewhere (note on WP-21.4).
  - **Tile fallback, verification, investigation.** A newly UNAVAILABLE leg
    with a tile is TILE-anchored (`tile_no_text_evidence`), reaches
    `verify_cross_findings`, and costs one dual-crop call: new paid work, by
    design. It goes on to investigation if the crop leaves it UNCERTAIN. A
    dropped leg removes work and ink. A newly grounded N13 leg anchors through
    the anchor's own tiers, which already fold those forms.
  - **The tile join and reconcile.** A leg quoting a curly inch mark inherits
    its fact's tile. Two facts that normalize alike with different tiles now
    collide and give none (the existing ambiguity rule).
  - **Exports and report.** `findings.json` carries `evidence_state`;
    `findings.csv` reads TILE instead of UNANCHORED for a recovered leg; the
    markup manifest's placements follow; a dropped conflict leaves every
    artifact. The report carries the reduced-trust quote-cell note.
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2):
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,425 passed, 2 skipped, 10 deselected** (218 s) on `d75e39c`,
    identical to the WP-07.2 handoff.
  - **Failing first.** The new file was run in a `git archive` copy of
    `origin/main` (`d75e39c`), classified from `--junitxml`:
    - **67 failed on behaviour**;
    - **2 failed only on the new API** (`source_words`,
      `WORD_LEADING_PUNCTUATION`);
    - **23 passed**. They pin what the fix keeps: whole-word quotes still
      ground, a changed long phrase stays NOT_MATCHED, blanks stay
      unavailable, and `fold_text` already folded the non-breaking hyphen and
      the zero-width space.
  - **After:** full suite **3,520 passed, 2 skipped, 10 deselected** (212 s): the baseline plus 95 (92 new tests
    and three new cases of the extended test), with the same two environment
    skips (IPv6 loopback; chmod as root).
  - **After the Codex P2 fix:** full suite **3,524 passed, 2 skipped, 10
    deselected** (216 s): the 3,520 above plus the 4 cost tests.
  - **Windows CI, fixed in this PR.** On `cc03bff` the Windows leg errored in
    setup and teardown of both long-run cost cases. Their parameter was the
    1,000,000-character run itself, and pytest names a test after a string
    parameter. Windows refuses a `PYTEST_CURRENT_TEST` longer than 32,767
    characters (`ValueError`). Each error report then printed the
    million-character name, and the job log shows about seven minutes between
    those lines, so the job crawled instead of failing. The parameter is now the
    four-character unit and the run is built inside the test; the longest test
    id in the suite is 216 characters. Reproduced here with a scratch plugin
    that gives `os.putenv` Windows' limit: 4 errors before, 2 passed after.
    Full suite after: **3,524 passed, 2 skipped, 10 deselected** (224 s),
    unchanged, and the same under the plugin (216 s).
  - **Browser suite:** not run separately. No report JS, HTML or chat code
    changed, and the browser tests ran inside the full suite.
  - **Lint and scans:**
    - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
      0.14.5) is clean;
    - F401/F811/F841 over the touched source files and the new test file is
      clean;
    - `tests/test_evidence_visual.py` has nine unused imports on `origin/main`
      already, on lines this change does not touch (WP-22.5);
    - `scan_secrets.py` is clean over 204 tracked files, the new one included,
      and `compileall src` passes.
- **Docs:**
  - **CHANGELOG** (Fixed): B5, N12's cross-QC part and N13, with the visible
    effect, the extra verification calls, the accepted cost and the cache
    note.
  - **CLAUDE.md:** the grounding paragraph (the rule, the order,
    `SourceWords`, the contract value; the P8 item 11 sentence notes 4) and the
    text-normalization paragraph (`_normalize` is the one matching normalizer;
    `anchor.py` holds the rule, which the anchor does not apply yet).
  - **README:** the cross-sheet QC section, the evidence-trust section, the
    "recovered evidence costs more" bullet, and the cache bullet, whose stale
    "`_CROSS_QC_CACHE_CONTRACT` sits at 2" (it was 3 since P8) now gives 4 and
    the history.
  - **DECISIONS:** the D-4 note and one register row.
  - **The plan:** WP-05 step 1 and step 3 notes, with the decisions and the
    correction that cross-QC's source words come from the evidence string, not
    `_Stream.word_of`.
  - **PROGRESS:** this entry; the WP-05.1, B5, N12 and N13 rows; notes on
    WP-05.2, WP-06.1, WP-06.2 and WP-21.4.
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: how many cross-QC legs are short tags, how many of
  those sit on scanned sheets (the new dual-crop calls), how many are dropped
  as tags the sheet does not print, and how often a tag sits in a tight list
  (O-10). Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **More paid calls, by design:** each short-tag conflict on a scanned sheet
    costs one dual-crop call, plus an investigation if the crop cannot settle
    it.
  - **Recall costs the owner accepted:**
    - a tag inside a list written without spaces (`P-1,P-2`, `M-101/M-102`);
    - a quote after a bullet dash glued to it (`-PROVIDE`) or a glued sentence
      (`NOTES.PROVIDE`);
    - a short quote carrying edge punctuation the sheet lacks (`P-1,` against
      `P-1`). The shortcut used to ground it; long quotes never did.

    A leg dropped this way can take its conflict with it.
  - **Not a quantity check:** `1/2" PIPE` still grounds in `2 1/2" PIPE`,
    because two source words each match whole. The anchor has the same gap
    today (WP-05.3's quantity-aware veto).
  - **A bare number or letter** (`3`, `A`) grounds wherever it is printed as a
    word: a real but weak match, by the owner's choice.
  - **Punctuation inside a span** (`175 PSI, TYP.`) matches in neither cross-QC
    nor the anchor (B4, WP-05.2).
  - **The anchor** still EXACT-matches `VAV-2` inside `VAV-2-1` (WP-05.2).
  - **The hybrid wording** (WP-21.4 note).
- **Re-checked (U31):** the whole-set path grounds nothing (instrumented);
  `anchor._normalize` is byte-identical (every anchor test and the
  `_UNICODE_DASHES` pin pass unchanged); `reduced_trust_reason` is untouched.
- **Found, not fixed:** `_parse_facts` admits a fact whose `exact_quote` is
  only whitespace, and counts it as a no-text admission (note on WP-06.1).
- **Next:** WP-05.2 (Wave 1, no dependencies). WP-06.2 (Wave 2) no longer
  waits on WP-05.1.

### 2026-09-23 — WP-07.2: strict numeric tokens and a relationship the sheet states ([PR #164](https://github.com/Abe-Borg/drawing-analyzer/pull/164))

- **Slice and IDs:** WP-07.2. A8 (implemented+validated); the N3 row now points
  here for role swap and sum versus product. No `DECISIONS.md` contract is
  decided (the arithmetic rules are none of D-1 … D-8); the owner's three
  choices are recorded here, in the plan's WP-07 step 4 and step 5 notes and in
  CLAUDE.md. D-4 gains a WP-07.2 note and the migration register one row (a
  stored-claims residual, below). WP-07 is not done (WP-07.3 remains), so there
  is no package acceptance check.
- **Base.** `main` moved to `3e7fd78` after the request was written: the
  Dependabot PRs #136 (CI actions) and #148 (`pydantic_core` 2.49.0,
  `playwright` 1.63.0) merged. Neither touches product code; the baseline was
  identical (below), and the browser tests ran under Playwright 1.63.0 inside
  the full suite.
- **Reproduced first** on `3e7fd78` (scratch script, the real auditor), each
  DETERMINISTIC / TEXT_EXTRACTED with an EXACT anchor: `sum [101, 540] = 439`
  on `SEE FP101 TOTAL 540 AT 439 GPM` (scan `[101, 540, 439]`);
  `parse_number("1e3") == 1`, `"2.5e-2"` → 2.5, and `sum ["1e3", 500] = 1600`
  on `1e3 + 500 = 1600` as "the sum of 1, 500 is 501" (scan `[1, 3, 500,
  1600]`); `M-101 P-3 AHU-2` scanned as `[-101, -3, -2]`; `sum [20, 2] = 40` on
  `20 x 2 = 40`; `sum [100, 375] = 250` on `A 100 B 250 TOTAL 375`. One more,
  from step 5's shape: `sum [-3, 100, 100] = 200` on `VAV-3 100 + 100 = 200`
  (the tag's `-3` grounded an operand).
- **Facts confirmed, not assumed:**
  - The scanner feeds both sides of `_operands_grounded` (the quote and the
    matched sheet words), so the stricter `_numbers_in_text` applies to both.
    The new relationship reader uses the same scanner (`_scan_numbers`) on
    both.
  - `parse_number` feeds `claim_value_key`, hence every claim dedup, the
    discriminator and each arithmetic finding's `id`. Under the chosen rules
    every change only **refuses**: a parse becomes `None` or stays exactly what
    it was (the parser gained tail binders only; the head rule is scan-only).
    So a term whose parse changes makes its claim unusable, and no finding that
    is still produced changes its text, discriminator or id. The
    investigation key (`investigate._payload_hash`: id, text, quote, category,
    severity, rect, prior note, source) is therefore unchanged for every
    finding that stays model-transcribed; a finding the relationship check
    newly leaves model-transcribed was DETERMINISTIC before, which neither
    verification nor investigation takes, so it has no stored entry to miss.
    **No investigation re-key; no register row for it.**
  - Critique and cross-QC caches store raw claims (`critique._dedup_claims`,
    `cross_qc._dedup_claims` run before the store) and the auditor re-parses
    them on every read, so the new rules apply to warm entries with no key
    change. The one effect: both dedups key on `claim_content_key`, so an
    entry stored before WP-07.2 may have kept only one of two transcriptions
    of one quote that differed only by a now-refused spelling (`"1e3"` and
    `1` both keyed `1`). Recorded in the register as an accepted narrow
    residual (re-billing every critique and cross-QC call for it is not
    proportionate).
  - The merge-rule fingerprint (`tests/test_drawing_cache_identity.py`) does
    not move: its corpus has no arithmetic and `_is_duplicate` is untouched.
  - `test_parse_number_table` passes unchanged (`20A`, `150GPM`, `165 psi`,
    `0.20 gpm/ft²`, `2-1/2"`, `1,200`, `12' clear`), and `12,5`, `12'-6"`,
    `1.2.3` and `30%` stay refused.
  - No role or operator field is added: the claims contract in
    `critique._CRITIQUE_FINDINGS_INSTRUCTION` and `cross_qc.CROSS_QC_SYSTEM_PROMPT`
    is untouched, so `CRITIQUE_PROMPT_VERSION` and `_CROSS_QC_CACHE_CONTRACT`
    do not move.
- **The decision, made by the owner before any code** (AskUserQuestion with
  measured options). Chosen, each as recommended:
  - **Scientific notation: rejected.** `1e3`, `2.5e-2`, `1E+3`, `2E1` are not
    one value to the parser or the scanner; a term spelled that way makes its
    claim unusable. Not taken: reading `1e3` as 1000 (a panel tag `2E1` would
    then print a 20, and a term that parsed as 1 would parse as 1000, moving
    that finding's text, discriminator and id).
  - **Tag digits:** digits glued after a letter, with or without a hyphen,
    are a tag's or sheet id's (`FP101`, `M-101`, `AHU-2`, `A1.01`), and a
    hyphen after a letter is never a minus sign; letters after a number are
    its unit unless digits follow them directly (`24x12`, `2P20A`, `10A1`,
    `100m2`, `1e3` are not one value). Not taken: refusing only exponent and
    size forms after a number (`100m2` would read 100, `10A1` 10, `2P20A` 2).
  - **Relationship: an operator or TOTAL, exact roles.** The quote AND the
    sheet's words under the span each print the claim as one equation: the
    result is the first number after `=` or TOTAL/SUBTOTAL, the operands are
    exactly the terms (a multiset), and every join is `+` (sum) or
    `x`/`×`/`*` (product, factor); an operator-less list is a sum only with
    TOTAL. Anything else is not established and stays MODEL_TRANSCRIBED /
    UNCERTAIN (plan step 4). Not taken: requiring an explicit operator (a
    TOTAL-only row such as `20 20 20 TOTAL 540` would lose trust). Reading
    the relationship from both sides conforms to WP-07.1's evidence rule and
    was stated, not asked: a FUZZY window can differ from the sheet in one
    non-numeric token, and that token can be the operator (pinned).
  - **Measured first**, as the request asked: a scratch copy of
    `origin/main` whose `audit_arithmetic` logged, for every claim with the
    test name, today's outcome and the outcome under 35 option combinations
    (tokens today / broad / narrow × scientific notation rejected / read ×
    relationship none / quote / span / both × TOTAL a sum or not). The hooks
    ran **93 `audit_arithmetic` calls over 145 claims** (40 trusted, 77
    model-transcribed mismatches, 6 matched, 9 unusable, 10 dedup-skipped).
    **No token or scientific-notation option moved any fixture** (no parse
    changed; one scan changed: the pipeline's `VAV-3`, from `[-3]` to `[]`,
    MODEL_TRANSCRIBED either way). The TOTAL-as-sum relationship moved none;
    the explicit-operator one moved **24 claims in 24 tests** to UNCERTAIN (20
    in `tests/test_arithmetic_claim_discriminator.py`, incl. `_det()`; 2 in
    `tests/test_arithmetic_operand_grounding.py`; 1 each in
    `tests/test_drawing_auditors.py` and `tests/test_position_is_not_sameness.py`).
    The gauntlet's `TOTAL 100 + 250 = 375` stayed trusted under every option.
    A second table ran the A8 shapes and 25 edge cases through every option.
- **What changed** (`auditors/arithmetic.py` only; no other product file):
  - `_NUMERIC_TAIL_RE` (parser and scanner) refuses a number followed
    directly by letters and a digit, an exponent sign, `×` or a fraction slash
    and a digit, a glued vulgar fraction, and a Unicode dash wherever `-`
    already bound. `_head_denies` (scanner) refuses a number glued after a
    letter (a `+` glued to a letter stays an operator, `250GPM+100GPM`, except
    as an exponent's sign, `1E+3`), after a Unicode dash (incl. `−5`, whose
    sign `[-+]` cannot read), after a fraction slash, and after `×` preceded
    by a digit. `_UNICODE_DASHES` is pinned equal to the dashes
    `anchor._normalize` folds (`anchor.py` is untouched).
  - **Codex review, P2, fixed in this PR** ("preserve unary signs after
    explicit operators"). `_equations` read a sign glued to an operand as a
    second operator even when the gap already printed one, so `20 + -5 = 15`
    joined `{+, other}` and `20 x +2 = 40` joined `{x, +}`, and both stated
    equations were refused (UNCERTAIN, a paid crop check, and no ink in
    verified-only mode). Root cause, not only the two examples: a glued sign
    is the operator only when nothing is printed between the two numbers
    (`20 +30` adds, `20 -5` subtracts); after a printed operator it is the
    operand's own sign, already in its value. The safe direction was never
    at stake (a refusal is not a false trust), and `20 - -5` still reads as
    a subtraction.
  - `_scan_numbers` returns each number's span and matched text;
    `_numbers_in_text` keeps its signature and returns the values.
  - The relationship reader: `_gap_marks` (what the text between two numbers
    says: `=`, `total`, `+`, `x`, or `other` for a subtraction or division, an
    unknown symbol, or a digit, i.e. a refused number), `_equations` (results,
    operands since the previous result, running totals, a glued sign as the
    operator), `_relationship_stated`, and `_relationship_grounded` (both
    sides). It is one more conjunct in the promotion after the anchoring pass,
    inside the existing per-finding `try`, so a failure leaves only that
    finding UNCERTAIN (pinned). `pending` carries the claim kind.
  - Module, `parse_number`, `_head_denies` and `audit_arithmetic` docstrings
    updated. The verification note keeps its exact wording for each
    provenance (pinned).
- **Contracts decided:** none of D-1 … D-8 (the rules are the owner's, above).
- **Cache/schema effects:** no key, prompt version, contract term or schema
  changed, and no finding id moved (above). One migration-register row: the
  critique and cross-QC stored-claims dedup residual. The A/B
  `RECORD_CONTRACT_VERSION` stays 3 (a record's shape and meaning are
  unchanged; a status delta between arms run before and after is the code
  change it is, as for WP-07.1).
- **Re-baselined tests: none.** Every pinned test passes unchanged:
  `tests/test_drawing_auditors.py` (the parser table, rejects, percent,
  comma list, the scanner/parser agreement test, no-eval, the arithmetic block,
  `run_auditors`), all of `tests/test_arithmetic_operand_grounding.py` (incl.
  the FUZZY quote ending `RISER 3`, the `2-1/2"` case, the note wording and
  the pipeline test), all of `tests/test_arithmetic_claim_discriminator.py`
  (`ROW = "20 20 20 TOTAL 540"` stays DETERMINISTIC), the gauntlet's
  `test_gauntlet_deterministic_auditors_fired`, the pipeline's
  `test_arithmetic_auditor_flags_bad_claim_end_to_end` (MODEL_TRANSCRIBED),
  `tests/test_drawing_models.py`, `tests/test_source_identity.py`,
  `tests/test_drawing_cache_identity.py`. Since no existing test file was
  edited, the fixed-tree full suite is also the run of the original pinned
  files against the fix.
- **Fixture effects, instrumented over the whole fixed suite** (a scratch copy
  whose `audit_arithmetic` compared, per claim with the test name, the old
  rule recomputed with `origin/main`'s parser and scanner against the real new
  outcome, and logged every parse, scan, provenance or status change). The
  hooks ran **142 `audit_arithmetic` calls over 199 claims**: TE→TE 59, MT→MT
  76, matched 6, unusable 9, dedup-skipped 10, **TE→MT 30, mismatch→unusable
  6, MT→TE 0**. Every change is in the new test file except: the pipeline's
  `VAV-3` scan (`[-3]` → `[]`, MT→MT), and the two tests that monkeypatch a
  provenance helper to raise (a probe artifact: the old-rule recomputation
  does not see the monkeypatch; both findings are MT in the real run, as the
  tests assert).
- **New tests:** `tests/test_arithmetic_tokens_and_relationships.py` (136):
  tag and sheet-id digits (10 texts) and hyphens (6); units that still parse,
  in the parser and the scanner (12); tokens that are not one value, refused
  by both (15); the safeguards kept; a per-token scanner/parser agreement
  table (17); the dash set pinned to the anchor's; refused spellings keyed
  apart; the auditor on the A8 shapes (`FP101`, `VAV-3`, five refused terms
  → unusable); the relationship: a product as a sum (4 operator spellings), a
  sum as a product, four role swaps, an omitted operand of a correct row, a
  correct subtraction, nine unstated shapes, fifteen stated shapes kept, and
  the FUZZY case where only the quote states the operator; a signed operand
  after a printed operator still trusted (3, the Codex review below); the
  finding's id, discriminator and note unchanged; the reader (20 rows) and the
  both-sides rule; a failure while checking one finding; `run_auditors`' tally;
  verification eligibility and the trust note; the critique and cross-QC
  dedups; and **the pipeline**: on an exhaustive run `20 x 2 = 40` (as a sum)
  and `SEE FP101 TOTAL 540 AT 439 GPM` are each crop-verified once and keep
  their MODEL_TRANSCRIBED caveat, while `TOTAL 100 + 250 = 375` stays
  DETERMINISTIC and is never re-checked.
- **Downstream consumers walked:**
  - Verification (`_is_verifiable`) and investigation (`_candidates`): an
    anchored mismatch the rules no longer trust is eligible (one crop call
    each on exhaustive runs; an investigation if the crop cannot settle it).
    A claim that becomes unusable produces no finding and no call.
  - Markups: `annotate._trust_note` reads `operand_origin` first (the
    "re-check the math" caveat before and after a verdict); the verified-only
    gate (`_TRUSTED = {VERIFIED, DETERMINISTIC}`) no longer inks such a
    mismatch unless the verifier confirms it; the index says "Check" instead
    of "Computed". Anchors, placement, severity layer and stamping unchanged.
  - Report chip (`html_report._finding_display_status`): "Deterministic"
    becomes the verifier's verdict, or "Uncertain" where no verifier ran
    (WP-21.4's note, extended). `_audit_checks_line` ("M of N numeric
    relationships checked out") reads a lower N when a term is refused.
  - Exports: `findings.csv` `verification_status` / `verification_note` and
    `markup_manifest.json` dispositions follow the status; `findings.json`
    gains no field; ids unchanged.
  - Ledger: fewer entries rank first in `_grounding_quality` (WP-03.5's note,
    extended).
  - Claim dedups and ids: a refused spelling keys `raw:…` and no longer
    collapses into the number it used to parse as (pinned in all three).
- **Validation** (this container, Python 3.11.15, SDK 1.7.0, PyMuPDF 1.28.2,
  Playwright 1.63.0):
  - **Baseline before any change:** `python -m pytest -q -m "not network"`
    gave **3,289 passed, 2 skipped, 10 deselected** (211 s) on `3e7fd78`,
    identical to the WP-07.1 handoff.
  - **Failing first.** The new file was run in a `git archive` copy of
    `origin/main` (`3e7fd78`) with only that file added, classified from
    `--junitxml`: **74 failed on behaviour, 17 failed only on the new API**
    (`_relationship_stated` ×14, `_relationship_grounded` ×2 incl. the
    monkeypatch, `_UNICODE_DASHES`), **36 passed** (they pin what the fix
    keeps: units, the safeguards, agreement on tokens both trees read alike,
    and the fifteen stated shapes).
  - **After:** full suite **3,416 passed, 2 skipped, 10 deselected** (204 s):
    the baseline plus 127, with the same two environment skips (IPv6
    loopback; chmod as root).
  - **After the Codex P2 fix:** full suite **3,425 passed, 2 skipped, 10
    deselected** (203 s): the 3,416 above plus the 9 signed-operand tests. Those 9 were
    first run on the PR head before the fix (`5d9287a`): 7 failed on
    behaviour; the `20 + +5` row passed (a `+` beside a `+` was already one
    operator).
  - **Browser suite:** not run separately; no report JS, HTML or chat code
    changed (the browser tests ran inside the full suite).
  - `python -m ruff check --select E9,F63,F7,F82 src tests scripts` (pinned
    0.14.5) is clean. F401/F811/F841 over the touched files finds one unused
    import, on `origin/main` already and on a line this change does not touch
    (`arithmetic._wtext`; WP-22.5). `scan_secrets.py` is clean over 203
    tracked files, the new one included. `compileall src` passes.
- **Docs:** CHANGELOG (Fixed, A8, with the visible effect, the extra
  verification calls, the unusable count and the cache note; the WP-07.1
  entry's "not in this change" now points to it); CLAUDE.md (the "model never
  calculates" invariant: the token rules and the relationship check; its
  "not checked yet (WP-07.2)" sentence is replaced; the anchor paragraph is
  unchanged, since `anchor.py` is untouched); README (the verification status
  table and the numeric-claims contract, whose "next remediation slice"
  sentence now describes what is checked); DECISIONS (D-4 note, one register
  row); the plan (WP-07 step 2, 4 and 5 notes); PROGRESS (this entry, the
  WP-07.2, A8 and N3 rows, notes on WP-07.3, WP-21.4 and WP-03.5).
- **Not verified:** live API behaviour (no budget, O-4; this slice makes no
  call). Real drawings: how many real mismatches the relationship rule leaves
  UNCERTAIN, so how many verification calls it adds per run, is unmeasured
  (O-10). Windows is covered by this PR's CI.
- **Risks and residual gaps:**
  - **More paid calls, by design, and recall costs the owner accepted:** a
    label's number among the operands (`RISER 3: 20 20 20 TOTAL 540`), an
    operation written with a symbol the host does not read as one
    (`3 @ 250 CFM = 800 CFM`), a list with `=` but no operator
    (`1500 SF 1.3 = 2000`), a multiplier glued to `x` (`x1.3`, read as a
    tag), a tight `20+30=60` (the `+30` was already refused as bound to the
    digit before it), an ASCII-squared `100m2`, and a diameter `Ø6"` (Ø is a
    letter) are not trusted and cost a crop check each. All are the safe
    direction.
  - **The matched path is unchanged** (WP-07.3): a claim that "checks out"
    is counted without checking provenance or the relationship.
  - **Stored-claims residual** (register row): warm critique and cross-QC
    entries stored before WP-07.2 may hold one of two transcriptions that
    differed only by a now-refused spelling.
  - "Uncertain" in the report on a run with no verifier (WP-21.4 note).
- **Re-checked (U31):** a non-finite JSON number (`NaN`, `Infinity`; Python's
  `json` accepts both) already made its claim unusable through the per-claim
  guard (the tolerance comparison raises), so the tally stays consistent; not
  changed. `anchor.py` and the claims contract are untouched; the three claim
  dedups still share `claim_content_key`.
- **Next:** WP-05.1 (Wave 1, no dependencies). WP-07.3 (Wave 2) is now
  available; WP-07 is done only when it lands and the Acceptance paragraph
  holds.

### 2026-09-23 — WP-07.1: arithmetic operands are trusted only where the sheet prints them ([PR #163](https://github.com/Abe-Borg/drawing-analyzer/pull/163))

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
