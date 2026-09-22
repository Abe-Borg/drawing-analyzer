# Drawing Analyzer: remediation and improvement implementation plan

Prepared: September 22, 2026  
Reviewed baseline: `da8f810add59d2c2731e92034efd5d671d7497ee` (`1.7.0`)  
Original report baseline: `f5284ac` (`1.6.0`)  
Repository: `drawing-analyzer`

## 1. Purpose and completion standard

This document is an execution plan for coding agents implementing the corrections identified in the September 2026 review and its reassessment against 1.7.0. It includes required behavior, implementation boundaries, dependencies, cache and data migrations, regression scenarios, rollout gates, and a traceability register.

The plan is not an instruction to apply every suggestion from the original report literally. Confirmed correctness and integrity defects are mandatory. Conditional defects require a bounded validation step and a recorded outcome. Changes to model selection, prompt structure, image resolution, context allocation, and cache policy require evaluation before becoming defaults.

Success means that the application retains distinct findings, attributes them to the correct physical evidence, reports incomplete work honestly, recovers completed paid work, and exports consistent review artifacts. A green unit suite alone is not sufficient. Each package has behavior-level acceptance criteria, and the release requires integrated evidence plus the applicable live-service and desktop-viewer checks.

This plan does not implement application changes. The implementation agent must recheck the current checkout before starting: later commits may already address an item. Reuse sound existing mechanisms instead of adding parallel implementations. When an item is already fixed, demonstrate that with current code and regression evidence and mark it complete; do not redo it.

### 1.1 Source material and reference conventions

- Read the repository's current `CLAUDE.md`, any applicable `AGENTS.md`, and relevant release/acceptance documentation before editing.
- Repository-relative paths in this document are navigation aids. Line numbers from the review are intentionally not treated as stable implementation anchors; locate the named symbols in the implementation checkout.
- IDs `B*`, `R*`, `C*`, `$*`, `K*`, `A*`, and `H*` refer to the original report. `G*` refers to its application/packaging findings.
- `N1` through `N9` identify additional findings from the reassessment, defined in section 3.
- Preserve the distinction between a reproduced defect, a traced failure path, and an unmeasured performance or compatibility risk in all completion reports.

### 1.2 Changes already present; do not undo or duplicate

The 1.7.0 baseline already removes `tiktoken`, adds optional structured outputs to verification and prose harvesting, shares structured-output gating, records verification parse-loss counters, and wraps report content for the chat prompt. Preserve those improvements.

Dependabot already manages Python and GitHub Actions dependencies. Do not add a duplicate configuration. Some helpers described as having no callers in the old report have test callers; distinguish production-orphaned code from entirely unused code before removing anything.

The acceptance record currently places stable 1.7.0 publication on hold pending required evidence or recorded waivers. Do not treat a version literal or successful CI run as permission to publish a stable release.

## 2. Binding implementation rules

1. **Whole-sheet coverage:** keep the overview and all content-bearing tiles. No optimization may silently discard drawing content. Pixel-uniform blank suppression is not permission to infer blankness from missing text.
2. **Preserve digest prose:** retain the existing I-2 contract. Finding corrections, provenance, and failure annotations belong in their dedicated structures; do not rewrite valid digest prose or silently alter `combined_text` to repair a finding.
3. **Additive fault handling:** a failed optional/QC stage must preserve completed standard deliverables and explain incomplete work. A failed digest phase must also return the completed work it has collected where recovery is possible.
4. **PDF isolation:** only `render.py` and `annotate.py` may import PyMuPDF. Other modules receive extracted geometry and serializable evidence.
5. **Deterministic assembly:** equivalent inputs and collected outcomes produce equivalent findings, stable numbering, ordering, and destinations regardless of worker completion order. Transport IDs and timestamps may differ; semantic assembly may not.
6. **Cache correctness:** cache keys must describe the actual request and the host interpretation contract. Never cache an unsuccessful attempt as completed work. Version affected namespaces instead of deleting unrelated user caches.
7. **Truthful evidence:** distinguish host calculation, model transcription, text matching, image evidence, and a model judgment. One does not establish the others automatically.
8. **Truthful usage:** preserve every logical attempt and known charge. Missing usage is unknown, not zero. Do not double-count aggregate and per-iteration values.
9. **Immutable run configuration:** resolve effective model, transport, read counts, retry policy, schemas, and credentials once for a run. Deliberate per-request fallback is recorded explicitly.
10. **Respect the selected cost/transport policy:** Economy recovery must not silently become full-rate real-time work. Retry limits apply across the complete recovery chain.
11. **Credential and document privacy:** no API keys in job manifests, logs, caches, tests, or exported reports unless the user explicitly selected the existing key-embedding feature. Private source paths and drawing content require deliberate storage boundaries.
12. **Hermetic defaults:** ordinary tests must deny external network access. Live API calls use an explicit opt-in marker and a bounded cost budget. Browser and manual viewer validation are distinct from pure unit tests.
13. **No fabricated evidence or acceptance:** do not manufacture tool results, successful verdicts, missing receipts, benchmark results, release approvals, or compatibility evidence.
14. **Bounded work:** new retries, retrieval, orphan scans, history repair, parsers, and cross-sheet grouping must have explicit work limits and observable limit outcomes.

### 2.1 Handling uncertainty and implementation choices

The implementing agents may choose helper names and internal representations that fit the repository. They may not weaken the acceptance criteria to make a preferred implementation pass. Prefer conservative retention of separate findings over unproven merging. Prefer an explicit uncertain or incomplete outcome over confidently binding evidence to the wrong source.

If a proposed change conflicts with a documented invariant, resolve the contract before implementation and record the decision. Routine reversible implementation choices do not need repeated user approval. Stable publishing, live-service expenditure beyond the authorized budget, signing-key custody, and manual release waivers remain explicit operational decisions.

## 3. Additional finding IDs

| ID | Problem | Priority |
|---|---|---|
| N1 | A shared measurement such as `100 psi` masks a conflicting `6 in` versus `4 in` measurement during deduplication. | P0 |
| N2 | Cross-QC removes distinct claims that share the same sheet/quote/leg key. | P0 |
| N3 | Reused operand membership turns a duplicated model operand into a false DETERMINISTIC arithmetic finding. | P0 |
| N4 | Nonempty digest refusals and parseable incomplete critique responses can be accepted and cached. | P0 |
| N5 | Verification can report COMPLETE when required calls produced no usable judgment, or when some eligible items were skipped. | P0 |
| N6 | Small-set cross-QC binds duplicate sheet labels using a first-wins map instead of physical source/page identity. | P1 |
| N7 | The report calculator accepts malformed numbers and promises more numerical precision than it provides. | P1 |
| N8 | Stable publication does not enforce the documented manual acceptance hold. | P1 |
| N9 | Overflow-note navigation can use coordinates from the original drawing on a different destination page. Viewer effect needs validation. | P2, conditional |

Priority meanings: P0 protects result correctness or truthful completion; P1 protects recoverability, evidence, accounting, or release integrity; P2 improves robustness, performance, and interoperability after the relevant correctness contracts are stable.

## 4. Execution organization and shared contracts

### 4.1 Establish these contracts before dependent edits

Create a short implementation decision record covering the following. It should state the selected design, rejected unsafe shortcuts, version changes, and consumers affected. This is not permission for a prolonged redesign exercise; resolve the narrow contracts and proceed.

| Contract | Required decision |
|---|---|
| Finding identity | Separate physical evidence identity, reviewable claim identity, producer observation/provenance, and display QC number. |
| Response outcome | Distinguish finished response, refusal, truncation, interrupted stream, transport failure, malformed result, and valid inconclusive judgment. |
| Stage accounting | Define eligible, judged, failed, skipped, deferred/canceled, and recovered work independently of display labels. |
| Cache contract | Identify actual request format, host validator/normalizer version, completeness metadata, and compatibility rules. |
| Run lifecycle | Define active, cancel requested, draining/collecting, resumable, complete, partial, failed, and unresolved submission states. |
| Evidence ownership | Distinguish an artifact saved, an artifact sent to the model, and an artifact used in a completed judgment. |
| Usage | Separate requested model, serving model, logical attempts, server iterations, known tokens, unknown usage, and cache TTLs. |
| Source identity | Resolve every sheet and evidence leg to one physical input revision and page, never merely a human sheet label. |

### 4.2 Parallel work and shared-file ownership

Use isolated branches/worktrees for independent implementation work. Give one integration owner responsibility for changes in `models.py`, `pipeline.py`, `core/api_config.py`, `ledger.py`, and `html_report.py`; these are collision points. Other agents should propose interface changes to that owner before making incompatible edits.

Each agent handoff must include: addressed issue IDs; files changed; selected contracts; cache/schema effects; focused validation and results; unresolved risks; and exact follow-up dependencies. Do not let every workstream add its own normalization, completion, or deduplication helper.

| Wave | Work that can proceed together | Integration condition |
|---|---|---|
| 0 | Baseline/contract inventory; WP-02 test infrastructure; WP-23 release-hold enforcement design. | Shared contracts and owner assignments agreed. |
| 1 | WP-01 terminal/status behavior; WP-03 identity/merging; WP-04 quantities; WP-07 arithmetic trust; WP-16 credential snapshot. | Regression failures demonstrated and shared APIs stable. |
| 2 | WP-05 anchors; WP-06 cross-QC; WP-08 other auditors; WP-09 prose; WP-10 cache migration; WP-11 source isolation; WP-12 editions/citations. | Integrate against the same identity/outcome versions. |
| 3 | WP-13 investigation; WP-14 usage; WP-17 cancel/resume; WP-18 file ownership; WP-19 chat repair; WP-22 diagnostics/configuration. | Attempt, evidence, and lifecycle contracts implemented. |
| 4 | WP-15 estimator; WP-20 bounded assistant/calculator; WP-21 report/PDF presentation; WP-23 packaging; WP-24 updater. | Required dependencies pass focused checks. |
| 5 | Integrated acceptance; WP-25 bounded experiments; manual/live checks; release decision. | No P0 defect open; all mandatory packages accepted or explicitly scoped into a documented follow-up release. |

This is a dependency schedule, not a requirement to serialize an entire wave. For example, redaction fixes, pure auditor parsing, and updater tests can develop earlier in parallel when their interfaces are independent. Keep experiments out of the critical correctness patch series.

## 5. Work packages

### WP-01 — Response terminal states and truthful stage completeness

**Priority:** P0. **Covers:** N4, N5; cross-QC/investigation truncation limits; part of R2.  
**Primary files:** `digest.py`, `critique.py`, `batch_digest.py`, `batch_critique.py`, `cross_qc.py`, `verify.py`, `investigate.py`, `pipeline.py`, `models.py`.  
**Dependencies:** agreed outcome contract; coordinate with WP-02, WP-10, and WP-14.

Implementation:

1. Define a reusable terminal-outcome classification policy, with explicit per-stage handling for tool continuations. A successful HTTP envelope or parseable JSON object must not override a refusal, truncation, or interrupted response.
2. Audit every response consumer, including less-visible planner, identity, harvest, citation, and recovery paths. Do not fix only the top-level digest function.
3. A nonempty refusal is incomplete work. Preserve useful text for diagnostics/partial delivery, but do not call it a successful sheet digest or admit it to a completed-result cache.
4. A critique stopped at `max_tokens` does not count as a completed independent read even if a JSON object has closed. The same principle applies to cross-QC results and claim coverage.
5. Where a bounded raised-cap retry is justified, route large real-time requests through the existing streaming abstraction. Account for both attempts. Batch requests retain their own transport-specific request shape. Limit retries across truncation, transient-error, and fallback recovery together.
6. Separate valid inconclusive judgments from attempts that obtained no judgment. Use existing new verification degradation counters rather than inventing a second incompatible classification.
7. Define completeness from required item coverage. Zero eligible work is `SKIPPED_VALID`; all required items judged can be `COMPLETE`, including valid inconclusive judgments; any unjudged required items make the stage `PARTIAL` or `FAILED` under a documented all-failed rule. A mixed set of success and skipped eligible findings cannot be COMPLETE.
8. Retain original stage outcomes if later investigation recovers an item; expose recovery separately. If the product chooses a final coverage rollup that recognizes recovery, derive it explicitly from item outcomes and retain the original failure history. Do not let execution order erase failures.

Regression cases:

- Empty/nonempty refusal on real-time and batch digest; explanatory refusal text must not cache.
- Parseable empty and nonempty findings objects with `max_tokens`, `refusal`, unknown terminal reason, normal completion, and supported continuation reasons.
- Stream interruption before output, after text, and after a complete-looking JSON object.
- Verification: all malformed, all HTTP failures, all valid NOT_VISIBLE, some valid/some failed, some valid/some skipped, no eligible findings, and successful later investigation.
- Partial work remains exportable; failed attempts remain observable; repeated cold runs do not turn a failure into a warm clean result.

**Acceptance:** completion flags reflect obtained judgments and finished reads; no failed terminal state enters a cache promising completed work; no regression to ordinary successful prose output or valid uncertain findings.

### WP-02 — Faithful SDK, streaming, batch, and network test boundaries

**Priority:** P0 enabling work. **Covers:** original test-infrastructure gaps.  
**Primary files:** `tests/fixtures/fake_anthropic.py`, `tests/conftest.py`, batch/streaming/API tests, `tests/test_live_api_canary.py`.

Implementation:

1. Keep lightweight fakes for business logic, but add contract tests using the installed pinned SDK with a mocked HTTP transport. Do not require a real key or live service for these tests.
2. Model namespace and argument restrictions accurately: plain versus beta messages, batches, Files API, strict tools, structured outputs, fallback headers, and output caps. Match the installed SDK, not an unverified hardcoded historic cap threshold.
3. Use realistic nested batch error objects and emit explicit canceled/expired envelopes for unfinished items.
4. Add nullable cache usage, fetch/search counters, serving models, `stop_details`, fallback content blocks, and per-iteration usage fixtures.
5. Exercise actual event sequences: message start, partial text/tool JSON, content stop, final cumulative usage, refusal, pause, and interrupted connection. A fake returning only a complete final object cannot validate partial-stream recovery.
6. Deny external networking for non-network tests at a boundary that covers all used HTTP clients. Preserve deliberately local browser-test servers and test harness communication; do not disable the browser suite accidentally. Remove ambient key/token/profile access as defense in depth.
7. Add a minimal explicitly opted-in batch canary: upload, submit, collect, verify transport attribution, and clean up; cancellation behavior requires its own bounded fixture/canary. Every canary reports its IDs and cleanup result without secrets.
8. Keep source tests resilient to unavailable optional document dependencies. A broken binary dependency is an environment failure to diagnose, not an excuse to broadly catch `BaseException` in production.

**Acceptance:** tests fail for invalid request namespaces, missed terminal guards, realistic canceled envelopes, duplicated usage, and attempted external network access. Default acceptance scripts explicitly deselect network tests. A skipped browser/live gate is recorded as skipped, never passed.

### WP-03 — Durable finding identity and lossless, symmetric merging

**Priority:** P0. **Covers:** B1, B7, B8, B9, K5.  
**Primary files:** `models.py`, `ledger.py`, `critique.py`, `auditors/__init__.py`, serialization/export consumers.  
**Dependencies:** quantity predicate from WP-04; downstream WP-06/WP-21 depend on identity.

Implementation:

1. Inventory every `Finding.id` consumer: candidate deduplication, cache rebinding, numbering, verification/evidence paths, placements, bookmarks, HTML tools, CSV/JSON, and external comparison scripts.
2. Introduce or adopt a versioned claim identity distinct from a quote/evidence fingerprint and from `QC-###`. Include physical source/page and claim-discriminating content; account for cross-sheet evidence legs. Severity, verdict, arrival index, mutable representative choice, and display numbering must not accidentally determine identity.
3. Preserve producer observations separately when identical claims arrive from several reads. Reproduced confidence requires traceable independent reads/families under the existing policy, not duplicated copies of one observation.
4. Choose a deterministic identity lifecycle consistent with current stage order. Freeze identities before evidence filenames and final markup references are created. If post-merge aliases are necessary, serialize and resolve them explicitly. Never silently change identity beneath existing evidence.
5. Remove the auditor coordinator's destructive quote-ID-only deduplication. Let the shared claim-aware policy adjudicate true duplicates; retain two distinct mismatches on the same row.
6. Correct Pass B to require every original member of the incoming group to be compatible with every original member of the survivor group. Keep immutable member snapshots through all representative changes. Candidate indexing may accelerate discovery but cannot weaken this final predicate.
7. Deterministically select a coherent representative bundle: text, quote, action, anchor, and verification provenance must refer to compatible evidence. Do not borrow a losing member's verdict merely because it is stronger.
8. Serialize meaningful alternative actions and member provenance. Ordinary paraphrases may remain collapsed, but a distinct corrective action must be recoverable in exports. Do not fabricate a new quote by concatenating alternatives.
9. Define deterministic tie-breakers that distinguish otherwise same-quote findings and survive reordered/concurrent ingestion.

**Required clustering clarification:** complete-link matching and deterministic representative selection do not by themselves make cluster membership independent of arrival. If A matches B, B matches C, and A conflicts with C, different arrival orders can attach the generic bridge B to different clusters while still retaining two findings. Perform final clustering over retained original observations in a canonical order, or demonstrate an equivalent canonical-ingestion policy. Online merges may be provisional but must not irreversibly discard the observations needed for final assembly. The goal is deterministic, conservative clustering, not an optimal clique-partition algorithm. Preserve observation-to-anchor/evidence mappings when rebuilding clusters; do not attach a representative's rectangle to unrelated member text.

Regression cases:

- 500-gpm / generic bridge / 550-gpm in all permutations, with differing severity and quote-length rankings; both measurements survive.
- Conflict contained only in absorbed text, supporting quotes, or a non-representative member; anchoring after ingest cannot erase it.
- Two `PUMP P-1` issues retain separate identities, numbers, evidence, bookmarks, and index destinations.
- Same claim/different producer, same label/different physical source, same primary/different legs, and repeated reconciliation.
- Distinct recommended actions survive serialization and export; cold/warm assembly is equivalent.
- Nontransitive A/B/C permutations retain identical cluster membership, provenance, alternatives, and actions—not merely the same finding count or QC numbering.

**Migration:** read old payloads safely, but never reinterpret a legacy quote hash as a unique new claim ID. Rebind only when unambiguous; otherwise invalidate the affected derived cache. Historical exported artifacts remain readable and untouched.

**Acceptance:** no incompatible members share a merged finding; every retained claim has coherent ownership; ordering is independent of arrival order; repeated reconciliation is idempotent.

### WP-04 — Engineering quantity and tag comparison

**Priority:** P0. **Covers:** B2, B3, B12, N1.  
**Primary files:** `critique.py` signature helpers, any shared comparison consumers.

Implementation:

1. Normalize supported numeric/unit spellings into an exact, structured representation. Support valid thousands separators, hyphenated alpha units, decimals, signs, simple/mixed fractions, and existing feet/inches syntax.
2. Reject malformed number groupings as whole tokens. Never extract a valid-looking trailing fragment from a malformed or larger quantity.
3. Normalize temperature spellings without losing scale; preserve meaningful unit distinctions such as Fahrenheit/Celsius and psi/psig. Only add unit conversions with explicit semantics and fixtures.
4. Replace the disjoint-flat-set rule. A shared pressure must not mask incompatible diameters. Compare quantity roles where available, and retain separate claims when role ambiguity prevents safe compatibility.
5. Apply equivalent conservatism to partially overlapping equipment-tag sets. Do not require blanket equality that prevents legitimate multi-evidence corroboration, but do not let one shared tag automatically excuse another conflicting target.
6. Preserve the shared predicate used by the ledger and comparison/evaluation harnesses; do not create another implementation in a reporting script.

Regression matrix: `6-inch/4-inch`; `12,500/1,500`; `12,500/12500`; invalid grouping; `1/2"/2"`; `2 1/2"/2.5"`; signs; `12'-6"/12'-8"`; `90 deg F/90°F/90°C`; shared `100 psi` with conflicting diameters; repeated values in different roles; overlapping tags with conflicting subjects.

**Acceptance:** demonstrated conflicting pairs never merge, equivalent supported spelling compares consistently, and existing fraction/sign/unit safeguards remain intact. Record any deliberate conservative duplicate retention in the evaluation fixtures.

### WP-05 — Robust anchoring and consistent quote evidence

**Priority:** P0/P1. **Covers:** B4, B5 and the grounding portion of B6.  
**Primary files:** `anchor.py`, `cross_qc.py`, `verify.py`, evidence-state consumers.  
**Dependencies:** WP-04 numeric semantics; coordinate with WP-06.

Implementation:

1. Define one normalization policy for matching quoted text to extracted words, retaining a mapping to the original word rectangles. Fold ordinary sentence punctuation and extraction spacing without erasing engineering distinctions.
2. Add any character-stream fallback only with recovered word spans, ambiguity handling, and numeric/unit validation. Blind whitespace removal is not an adequate grounding rule.
3. Require exact or otherwise conservatively validated matching for every nonempty short tag. `P-1` must not match inside a different longer identifier.
4. Establish classification order: blank quote is unavailable evidence; no usable text is unavailable evidence; a real supported match is text-grounded; a failed quote against available evidence remains unmatched. For hybrid sheets, use existing region/coverage evidence where available; title-block text alone must not pretend the raster body was checked.
5. Retain appropriately qualified tile/image fallback when text evidence is unavailable. Do not label that fallback as exact text grounding; permit later image verification.
6. Preserve the difference between a sheet-level absence observation, no quote provided, and a supplied quote not found. Feed that distinction to WP-21's display vocabulary and counts.

Required positives: `PSI,` versus `PSI`; separated inch marks; extraction-merged words; `NOTE 3:`; parenthesized metric conversions; split feet/inches; separated percent marks.

Required negatives: changed numbers, signs, units, operand multiplicity, embedded short tags, adjacent unrelated words, and ambiguous repeated labels. Test rotated/page-view rectangles only where new mapping logic touches them; keep PyMuPDF out of this module.

**Acceptance:** all reported legitimate spacing/punctuation examples anchor; numeric substitutions do not; absent short tags never become TEXT_GROUNDED; eligible raster evidence reaches verification with honest provenance.

### WP-06 — Source-safe cross-QC and claim-preserving deduplication

**Priority:** P0/P1. **Covers:** B6, B10, N2, N6; whole-set grounding and truncation gaps.  
**Primary files:** `cross_qc.py`, relevant request/cache schemas.  
**Dependencies:** WP-01, WP-03, WP-05; cache work in WP-10.

Implementation:

1. Use host-generated unambiguous sheet handles in both small-set and sharded requests. A handle resolves to one physical source revision/page. Human sheet IDs remain display metadata.
2. Remove first-wins binding of duplicate sheet IDs. If a legacy response cannot be uniquely resolved, retain explicit ambiguity/loss accounting rather than attaching it to the first source.
3. Canonicalize conflict direction using an unordered collection of source/page-plus-associated-quote legs, while retaining substantive claim identity. A reversed duplicate collapses; two different issues on the same equipment do not.
4. Reuse the ledger's conservative semantic comparison where practical. Avoid an earlier destructive shortcut that discards claims before the ledger can examine them.
5. Correct the uncertain-conflict instruction to category `question`, severity `low`; retain strict host validation. Record validation losses distinctly from a clean empty response.
6. Apply the same grounding/evidence-state policy to whole-set and sharded results. Invalid or invented handles cannot bind, and short tags receive no exemption.
7. Apply WP-01 terminal-state validation and bounded recovery. Preserve partial findings and their incompleteness, without caching them as complete.
8. Make text omission and fact-selection limitations visible. Redesigning budgets/grouping is evaluated in WP-25; do not silently stop reporting degradation to improve completion rates.

Regression matrix: A-to-B/B-to-A same claim; same legs/different claims; three-leg permutations; duplicate human sheet labels in separate PDFs; input reorder; invalid handle; ambiguous legacy response; same tag on different pages; whole-set/sharded equivalence; question-category handling; parseable truncation.

**Acceptance:** valve and horsepower issues both survive; reversed duplicates produce one finding with complete leg coverage; no source is selected merely because its label appeared first; validation loss and omitted evidence remain observable.

### WP-07 — Arithmetic operand trust and strict numeric parsing

**Priority:** P0. **Covers:** A8, N3; coordinates with B7.  
**Primary files:** `auditors/arithmetic.py`, `models.py` numeric provenance, verifier eligibility.

Implementation:

1. Keep Decimal-based host calculation. Independently establish whether the operands and their relationship are supported by source evidence.
2. Replace reusable numeric membership with occurrence-aware support. One printed `20` cannot establish arbitrarily many model-transcribed `20` operands. Account for the expected/result value separately.
3. Ground against actual extracted source text/geometry, not only the model's asserted quotation. An exact quotation is necessary evidence in many cases, but is not proof that the model selected the right operation or operands.
4. Validate explicit simple relationships where supported. `20 + 20 = 40` cannot support `[20,20,20]`; `20 × 2 = 40` requires its own supported relationship. If layout or operand roles cannot be established, keep the finding MODEL_TRANSCRIBED/UNCERTAIN for verification.
5. Exclude digits embedded in sheet IDs, equipment tags, and compound expressions. Deliberately support scientific notation with complete-token semantics or reject it; `1e3` must never become `1`.
6. Preserve valid fractions, thousands grouping, repeated legitimate values, and current percentage/dimension safeguards. Host computation provenance must not imply independently validated operand provenance.
7. Reconcile arithmetic counters with retained distinct findings and explicit unusable/uncertain classifications.

Regression cases: correct `20 + 20 = 40` with duplicated model operand; genuinely repeated terms; absent/fabricated quote; same number used as both term/result; digits in `FP101`; scientific notation; malformed decimal/grouping; percent factors; table operands outside a short quote; sum versus product confusion.

**Acceptance:** the reported correct equation never receives a false DETERMINISTIC finding; unsupported transcription cannot bypass verification; actual deterministic mismatches still work; one bad claim cannot remove neighboring findings or corrupt counts.

### WP-08 — Reference, naming, sheet-ID, and drawing-index auditors

**Priority:** P1. **Covers:** A1–A7.  
**Primary files:** `auditors/references.py`, `auditors/sheet_ids.py`, `auditors/naming.py`, `auditors/sheet_index.py`, title-block consumers.

Implementation:

1. Require lexical or layout evidence before treating three two-digit values as a specification reference. A plausible MasterFormat division by itself is insufficient.
2. Apply tag arrangement/meaning checks even when a frequency winner exists. Popularity must not convert breaker `3P` into the preferred spelling of pump `P-3`.
3. Extend bounded reference parsing for DWG/DWG., REF., SHEET NO., detail-on-sheet phrasing, and multi-target lists. Keep a negative corpus so additional recall does not classify arbitrary prose as missing sheets.
4. Rank own-sheet IDs using nearby SHEET/DRAWING labels and negative PROJECT/JOB/SIZE context. Retain the existing positional signal as one input, not an absolute decision. Surface genuine ambiguity instead of confidently selecting a distractor.
5. Correct contextual handling of FM sheet IDs. Preserve the working FM-only fallback while preventing unrelated tokens from displacing a well-supported FM title-block label.
6. Recognize a real drawing-index heading/table region and harvest entries from that region. A sentence referring the reader to another index must not establish an authoritative index here.
7. Distinguish incomplete/partial-set context before producing hundreds of present-but-not-listed findings. Any output cap must disclose counts and retained detail; it must not silently erase auditor results.
8. Normalize the inventory once, scope memoization to that inventory/grammar, cache repeated target resolution, and perform nearest-match work only when needed. Never reuse a cached answer across an inventory change.

Regression matrix: the two numeric-row false positives and genuine CSI references; P-3/3P with either frequency winner; every reported reference phrase/list; title block with project ID, paper size, revision strip, and nearby labels; FM-only/FM-with-distractor; real index versus prose mention; partial packages; changed inventory and cached resolution.

**Acceptance:** demonstrated false positives disappear without losing the positive fixtures; ambiguous IDs are observable; operation counts show expensive repeated normalization/nearest searches have been removed. Record elapsed-time comparisons on the same representative fixture rather than promising the old report's benchmark numbers.

### WP-09 — Prose harvesting without empty findings or unnecessary duplication

**Priority:** P1. **Covers:** B11; prose-match threshold concern.  
**Primary files:** `prose_harvest.py`, ledger ingestion; existing harvest tests.  
**Dependencies:** WP-01/WP-03; preserve the new structured-output gate.

Implementation:

1. Recognize negative boilerplate with repeated qualifiers, including “No conflicts noted on this sheet,” “No conflicts identified at this time,” “None apparent on this sheet,” and equivalent cross-discipline wording.
2. Use a narrowly bounded phrase/content policy, not a regex that suppresses substantive findings containing the word “no.” “No isolation valve is shown” is a real absence finding and must survive.
3. Apply the same trivial-content safeguard before a model call and before constructing a degraded fallback entry. A failed structuring call must not turn an empty assurance into a medium finding.
4. Preserve all meaningful unmatched prose through existing additive fallback behavior. Record whether it was matched, structured, degraded, or suppressed as trivial.
5. Instrument straggler counts, cache hits, per-item calls, and duplicate outcomes. Evaluate the Jaccard threshold with labeled paraphrase/nonduplicate cases before changing it. Do not lower the threshold solely to reduce calls.
6. Cache only a completed, valid structuring response under the effective contract. A schema option does not override terminal-state validation.

**Acceptance:** boilerplate creates neither a finding nor a paid structuring request; meaningful absences survive; degraded entries retain useful provenance; structured/plain cache separation remains correct; a measured threshold change cannot suppress distinct issues.

### WP-10 — Complete cache keys, faithful metadata, and targeted migration

**Priority:** P0/P1. **Covers:** K1–K4; N4 unsafe cache admission; identity/normalizer migrations.  
**Primary files:** `digest_cache.py`, `stage_cache.py`, request builders in `digest.py`/`critique.py`/`cross_qc.py`, `render.py`, `review_planner.py`, `pipeline.py`.

Implementation:

1. Map both cache levels and every stage cache. For each, document what can be restored without rendering or validation; include shortcuts capable of bypassing a newly fixed lower-level check.
2. Include model-visible tile placement wording and its generating contract in render/request identity. Include all cross-QC user framing, task strings, truncation markers, and request schema versions.
3. Prefer centralized immutable framing definitions or a canonical effective-request fingerprint. Exclude volatile request IDs, timestamps, secrets, and random upload IDs when they do not alter semantic content; include the underlying image/content identity instead.
4. Carry the effective output format with each request and result. Batch/plain/structured keys must describe the actual contract sent, never a later environment or global-latch read.
5. Define aggregate self-consistency cache identity for mixed contracts after a latch changes. Either represent the per-read contract vector or decline aggregate cache admission; do not label mixed reads as all structured or all plain by convenience.
6. Store planner loss metadata alongside sanitized plans: authored/retained counts, dropped counts, and reasons. Warm loading must not infer original loss by re-sanitizing an already-trimmed list. Distinguish configured valid limits from actual omitted authored content.
7. Version affected result schemas and host normalization/validation contracts. Reject old entries that could contain refusal success, incomplete critique success, ambiguous IDs, wrong source binding, or missing completeness metadata.
8. Preserve reusable successful raw content only where enough information remains to safely recompute new derived results. Do not claim all old caches are reusable if they lack required original response or completeness data.
9. Document a migration table for every changed namespace: old version, new version, readable fields, reusable content, invalidation reason, and scope. Never erase historical exports or perform a blanket cache-directory deletion as migration.

Regression matrix: changing a placement label or cross-QC framing causes a miss; unrelated presentation text does not; L1 cannot bypass a L2/schema change; concurrent latch changes preserve request/result identity; mixed-format reads follow the declared policy; 100 authored planner items produce the same 40-item loss cold and warm; old unsafe entries miss safely; compatible entries still hit.

**Acceptance:** equivalent cold/warm runs have the same semantic findings, numbering, stage status, warnings, and coverage. Transport/timestamp/usage differences remain intentionally distinguishable. Every cache write has a documented admission predicate.

### WP-11 — Inventory-driven source and page fault isolation

**Priority:** P0/P1. **Covers:** R1; source mutation consistency.  
**Primary files:** `render.py`, `source_registry.py`, `pipeline.py`, input inventory/status tests.  
**Dependencies:** WP-01 outcomes; coordinate with lifecycle work in WP-17.

Implementation:

1. Treat accepted inventory pages as the authoritative expected workload. Reopening, prescanning, or filtering paths must not silently reduce that denominator.
2. Catch source-open errors in rendered-sheet and prescan iterators. Emit attributable failures for the expected pages of that source and continue to the next source.
3. Isolate page load, geometry/text extraction, dependency hashing, and rasterization failures where possible. One malformed page must not remove good pages in the same document.
4. Add an outer digest-phase containment/finalization path so unexpected errors retain completed digests, usage, journal events, and a partial context that the normal exporter can publish.
5. Check source revision consistently when reopening for digest, verification, investigation, and markup. Do not combine text from one revision with a crop from a later overwritten PDF without marking the evidence invalid/incomplete.
6. Keep per-page/source failure cardinality controlled. Avoid one giant exception becoming duplicate errors at every layer, while still giving every expected page a terminal or unresolved outcome.
7. Preserve the existing persistent cache of completed successful reads. Explain in user-facing failure results what is exportable and what may be reusable on retry.

Regression cases: second source removed/locked after inventory; corrupt middle page; page count changed; source overwritten between digest and verification; geometry failure; hashing failure; cached prescan and uncached render; real-time, batch, and hybrid; all sources failing; failures after at least one completed paid read.

**Acceptance:** surviving sheets remain exportable; expected pages never disappear from accounting; journal/run status closes coherently; failed sources do not bind evidence from a different revision; zero-sheet and all-failed cases remain explicit.

### WP-12 — Citation parsing, full-text editions, and honest adoption evidence

**Priority:** P1. **Covers:** C1, C2, C5, C6, H4; edition-vocabulary/adoption inconsistency.  
**Primary files:** `citation_check.py`, `set_identity.py`, `models.py`, planner/cross-QC context renderers.  
**Dependencies:** WP-01/WP-10; usage pricing belongs to WP-14.

Implementation:

1. Assemble citation-bearing text blocks according to their contiguous text semantics. Do not inject newlines into JSON string content. Keep response text assembly separate from human presentation formatting; do not globally rewrite successful digest prose to fix citation parsing.
2. Collect source provenance across every response/continuation, including search and fetch results. Associate sources with claim assessments when information is available, rather than presenting an undifferentiated list as proof for every claim.
3. Use the full host evidence text for edition harvesting and corroboration. The model's budgeted prompt slice is not the authoritative limit for host-side evidence checks.
4. Expand edition parsing with bounded explicit fixtures for em/en dashes, year-first forms, ASHRAE, IECC, NEC, Title 24, ASCE shorthand, and jurisdiction-specific code titles. Preserve distinctions between a family name, section number, and edition year; ambiguous shorthand remains ambiguous rather than guessed.
5. Separate observed code references from declared adopted codes in the model and in every rendered context. Retain origin, quotation, source/page, and corroboration state. A regex match alone proves a mention, not adoption.
6. Rank code-selection windows using contextual evidence. The all-caps phrases containing `IS 1000` or `AS 2019` must not displace a later explicit declaration. Keep legitimate international code designations; do not solve the problem with an indiscriminate US-only whitelist.
7. Ensure planner, cross-QC, citation checking, and report identity use the same distinction. Update model-visible framing/cache versions accordingly.
8. Apply terminal and coverage validation before caching assessments. Preserve partial checked claims and explicitly mark missing verdicts.

Regression matrix: JSON split inside a cited string; citation/fetch-only output; multiple `pause_turn` responses; adoption after 15,000 characters; mentioned old edition beside an explicit adopted edition; punctuation variants; international standards; uppercase ordinary notes; conflicting declarations; no adoption declaration; warm/cold equivalence.

**Acceptance:** split citation text parses without invented whitespace; source trails contain all observed relevant evidence; late text is checked; incidental/historic citations are not promoted to adopted requirements.

### WP-13 — Investigation budgets, replay, and evidence finalization

**Priority:** P1. **Covers:** R7, C4; truncation, fallback replay, sheet-ID normalization, broad task-budget latch.  
**Primary files:** `investigate.py`, verification/evidence serialization; coordinate with WP-19 replay fixtures.

Implementation:

1. Give cheap host text search and image/crop requests separate finite budgets plus an overall turn/cost bound. Describe those limits accurately to the model. “No additional host API call” does not mean the model round trip is free.
2. Consider including a bounded host pre-search in the first turn. Treat this as evidence location, not an answer or guaranteed match. Include full-text matches only from the correct physical source/page.
3. Use shared sheet-ID normalization and unambiguous source handles. Reject ambiguous crop targets instead of selecting one by display label.
4. Narrow task-budget capability-rejection detection to errors actually naming the relevant unsupported feature. A generic effort/schema `output_config` error must not disable task budgets process-wide.
5. Finalize evidence on every return/exception path. Attach successfully saved artifacts even after an API failure, but distinguish saved-only, sent, and judged evidence. Record failed crop attempts without inventing files.
6. Preserve an ordered investigation record for partial/canceled outcomes. A record-write failure must not prevent the finding from retaining successfully produced evidence metadata.
7. Add bounded truncation continuation/recovery only with valid conversation replay and tool execution idempotency. Avoid rerunning a crop/search solely because an answer stream was interrupted.
8. Implement provider-specific fallback replay rules by block type. Preserve required fallback boundaries and completed results; do not indiscriminately delete pre-fallback text or retain incompatible signed thinking.
9. Evaluate forced-close cache behavior separately in WP-25. Preserve an actual host-side execution budget regardless of what the prompt tells the model.

**Acceptance:** search-heavy cases retain a useful crop allowance; Unicode IDs resolve correctly; out-of-budget tools are refused before execution; API failure after a crop does not orphan its evidence; continuation cannot duplicate tool actions; unrelated 400 responses cannot change the task-budget capability latch.

### WP-14 — Attempt-level provenance, usage, and pricing

**Priority:** P1. **Covers:** R3, C3; fallback provenance/billing; server iteration and nullable telemetry gaps.  
**Primary files:** `models.py` usage records, `core/pricing.py`, `pipeline.py`, response readers, batch collection.  
**Dependencies:** WP-01/WP-02; coordinate with WP-17 durability.

Implementation:

1. Record requested and serving model separately. A fallback-permitted request may remain cached under its requested contract, but the manifest must name the actual serving model and fallback attempts.
2. Read per-iteration usage where provided. Follow current provider billing rules: do not add top-level returning-attempt totals to the same attempt in `iterations`; do not bill a pre-output refusal merely because token counts were reported.
3. Record logical attempt IDs and retry-parent relationships, batch/custom IDs, terminal outcome, transport, parse/completeness status, and usage availability. Use these identifiers for idempotent aggregation.
4. Separate “envelope received,” “usable result,” and “usage known.” Canceled/expired/error envelopes must not disappear from the attempt history. Unknown tokens or billing remain unknown rather than zero.
5. Price cache writes by reported TTL breakdown when available. Otherwise derive TTL from the actual sent request/phase policy. Mixed TTLs must not be flattened into a false exact total. Fix citation's one-hour-write omission.
6. Preserve search/fetch counters and final cumulative server-loop input/cache usage across continuations. Distinguish no telemetry from an explicit zero. Fetch may have no separate per-use fee while its tokens remain billable.
7. Capture available usage from interrupted streams and mark remaining uncertainty. Retain the existing billable-but-unpriced behavior for unknown model rates.
8. Make actual pricing effective dates visible. Tests should use explicit rates and independently calculated expectations instead of reproducing the implementation's arithmetic.

Regression matrix: no fallback; pre-output refusal; partial-output fallback; multiple models/rates; final serving attempt also present in iterations; mixed TTLs; null token fields; canceled/expired batch items; duplicate harvest; cache-only run; zero tool uses; partial-stream usage; batch discount; unknown model.

**Acceptance:** every submitted attempt has one attributable outcome or unresolved record; totals do not omit or duplicate billable work; unknown usage never yields a misleading complete-looking price; citation writes use the correct rate class.

### WP-15 — Calibrated estimates and preflight efficiency

**Priority:** P1/P2. **Covers:** $1–$3; estimator scaling omitted by the original report.  
**Primary files:** `cost.py`, `profiles.py`, `render.py`, GUI cost confirmation, benchmark/calibration tooling.  
**Dependencies:** reliable usage from WP-14 and configuration from WP-16/WP-22.

Implementation:

1. Price the actual resolved models, transports, critique-read count, fallback/retry policy, schema mode, and image tier. Reuse the current geometry-aware estimates rather than reintroducing square-sheet assumptions.
2. Include measured capped text length plus prompt/framing/tile-label overhead. Use `SheetCostBasis.text_chars` where available, and a declared conservative fallback when it is not.
3. Calibrate total output-token distributions, including reasoning, separately by stage, model, effort, and useful workload features. Use representative p50/high-percentile bands with sample counts and uncertainty; do not turn the report's hypothetical 39-sheet cost into a fixed expected bill.
4. Scale prose harvesting with observed straggler volume and cross-QC with its actual map/reconcile call plan. A constant one-call allowance must not represent arbitrary set sizes.
5. Model cache hit/miss uncertainty, TTLs, batch pricing, retries, searches, and investigation volume. Distinguish a forecast band from a hard spend ceiling. Explain that resumable/canceled jobs may have pending charges.
6. Keep calibration imports privacy-conscious: prefer sanitized run-manifest numeric records, not full drawing text or credentials. Provide a reproducible small calibration corpus or aggregate fixture for tests.
7. Avoid a second GUI scan. Refactor the preflight's underlying read to collect sheet IDs and cost bases without unnecessary full-file/dependency hashing when those identities are not consumed. The lighter cost-only iterator cannot replace sheet-ID extraction by itself.
8. Fix hybrid render reuse: either make batch critique consume the existing spool correctly or avoid creating a spool it cannot use. Preserve exact image bytes and page binding. Measure disk writes and rerender count.
9. An optional API token-count sample is a separate latency/network decision; do not make the formerly offline cost dialog depend unconditionally on it.

**Acceptance:** estimates respond to text density, stage call count, reasoning-inclusive observations, configured reads, and transport; unknown coverage is labeled honestly; no duplicate scan is introduced; hybrid reuse reduces measured waste without altering evidence.

### WP-16 — Run-scoped clients and credential lifecycle

**Priority:** P1. **Covers:** G2, G3; save reentrancy, forgotten-key and export fallback concerns.  
**Primary files:** `gui.py`, `client.py`, `core/api_key_store.py`, configuration entry points.  
**Dependencies:** share immutable run context with WP-17.

Implementation:

1. Snapshot the selected credential into an explicit run-scoped client/client provider at Analyze time. Pass it through all stages and recovery paths. Later environment edits cannot redirect an active run.
2. Disable key editing during active work as a usability safeguard, but do not rely on widget state for correctness. Avoid propagating the key to child process environments where it is unnecessary, including PDF workers and launched viewers/installers.
3. Load legacy files using BOM-aware UTF-8 normalization. Apply conservative local shape/control-character validation before migration; do not perform a paid validation call during credential loading or reject future supported formats solely by an overly narrow length rule.
4. Remove legacy plaintext only after a normalized value is successfully stored and read back. Preserve useful diagnostic errors without ever logging the credential.
5. Add a reentrancy guard around persistence/consent handling, with cleanup in all exits. Focus changes caused by a dialog must not open recursive consent dialogs.
6. Provide an explicit Forget saved key action that clears the configured local store, legacy files where authorized, in-memory/UI state, and the app-owned environment value. Explain that forgetting a local credential does not revoke it at the provider.
7. Export must not reload a previously forgotten/cleared saved key behind the user's visible selection. When key embedding is off, avoid unnecessary credential loading/migration entirely. When on, use the intended current credential and preserve explicit embedding warnings.
8. Test the frozen secure backend as functional capability, not merely an import. Distinguish backend unavailable, persistence failed, and round-trip succeeded.

**Acceptance:** editing external environment state cannot break a run's later stages; BOM migration preserves the usable key; failed migration preserves the original; Forget and export agree; persistence cannot reenter; no child command or log unintentionally receives the key.

### WP-17 — Cancellation, durable job records, and safe resumption

**Priority:** P1, substantial feature. **Covers:** G1, R2; crash recovery and transport policy.  
**Primary files:** `gui.py`, `pipeline.py`, `batch_digest.py`, `batch_critique.py`, durable app-state module as appropriate.  
**Dependencies:** WP-01/WP-11/WP-14/WP-16; jointly design ownership with WP-18.

Implementation:

1. Add a run cancellation signal and explicit lifecycle states. Cancel stops new scheduling, cancels pending local work where possible, requests cancellation of active batches, and drains/collects completed results within a bounded policy.
2. Keep completed work exportable. Distinguish cancel requested, remote cancellation pending, canceled with partial results, and safely detached/resumable. Closing must not falsely promise that all billing stopped.
3. Persist atomic run/job records in the application state area independently of final export. Include schema version, nonsecret run ID, source revision fingerprints, effective configuration/contracts, logical request/custom IDs, batch IDs, collection cursor/state, upload ownership, and completed outcomes or durable references.
4. Do not store API keys. Store only necessary private source mappings in an appropriately restricted local record, separate from sanitized portable exports. A restart must establish an authorized usable credential rather than assuming the same process environment survived.
5. Persist submission intent before the network call and acknowledge accepted batch IDs immediately afterward. Do not invent provider idempotency. A request accepted remotely but missing a durable acknowledgement is an unresolved submission until safely reconciled.
6. Use supported bounded remote inspection and recorded provenance to reconcile ambiguous submissions where possible. If the service cannot establish whether it accepted a job, show an unresolved job and require a deliberate retry choice instead of silently rebilling it.
7. Make collection idempotent by logical attempt/custom ID. A crash after result persistence but before cursor advance must not duplicate findings or usage. Resume cleanup without resubmitting already completed work.
8. Handle batch refusals separately from envelope success. Use a bounded, capability-compatible fallback batch when permitted. Direct rescue is allowed only under an explicitly selected full-rate recovery policy. Record refusal details without secrets.
9. Validate source revisions, contract versions, available remote results, and account access before rebinding resumed results. A changed local PDF cannot receive the previous revision's evidence silently.
10. Coordinate concurrent app instances with job ownership/locking or leases. Repeated Cancel/Resume/Close operations must be safe and observable.

Crash matrix:

| Interruption point | Required restart behavior |
|---|---|
| Before remote submission | Resume pending local work once. |
| Submission accepted, response lost | Mark ambiguous and reconcile; no automatic blind resubmission. |
| Batch ID received before durable acknowledgement | Minimize and test the window; reconcile where supported, otherwise expose unresolved state. |
| Some results collected | Retain completed results and collect the remainder idempotently. |
| Results committed, cleanup pending | Cleanup resumes; model work is not repeated. |
| Remote results expired | Explain unavailable results and any known prior spend; do not represent it as a cache miss with zero prior cost. |
| Source files changed | Refuse incompatible rebinding and preserve the original job record. |

**Acceptance:** restart/cancel cannot silently lose completed work or automatically rebill it; every submitted attempt remains attributable; Economy remains on its chosen cost policy; closing during cancellation leaves either collected output or a durable honest recovery record.

### WP-18 — Remote upload and local work-directory ownership

**Priority:** P1/P2. **Covers:** Files API cleanup/storage/inline limits; stale-directory risk; related R6/R7 cleanup.  
**Primary files:** `file_upload.py`, batch modules, `render_spool.py`, pipeline work-dir lifecycle.  
**Dependencies:** WP-17 ownership and WP-14 usage.

Implementation:

1. Track which run/jobs reference each uploaded object and local evidence/spool directory. Keep resources alive while referenced by active or resumable work.
2. Make ordinary cleanup durable/retryable rather than depending solely on a best-effort daemon at shutdown. Store pending cleanup separately from analysis completion.
3. Add bounded orphan detection only for provably app-owned resources. Filename patterns and age alone are insufficient if another instance or live batch can still use them. Never sweep unrelated organization uploads.
4. Add explicit storage-quota failure classification and a useful recovery outcome. Reclaim safe app-owned orphans where possible; otherwise fail the affected operation clearly.
5. Before Files-API failure falls back to inline real-time requests, enforce the selected transport/cost policy: `_serve_inline` is full-rate ordinary Messages work and is allowed only when direct recovery is authorized. Otherwise retain an explicit failed/deferred/resumable sheet with an explanation. For an authorized fallback, measure actual encoded request size against the relevant transport limit. Do not assume the larger batch envelope applies. Do not silently lower resolution or drop tiles to make a request fit.
6. Protect local work directories with positive run liveness/ownership information. Include process-instance identity and lease semantics robust to PID reuse; age of a directory or its descendants alone is not proof of abandonment.
7. Preserve export ownership after analysis returns. Evidence must not be deleted before the caller exports it. Uncertain ownership, unreadable records, and exhausted scan budgets must fail safe by retaining resources.
8. On Windows, resolve and verify deletion targets against the app-owned root before recursive deletion. Test cleanup only with synthetic fixtures inside a test-owned directory.

**Acceptance:** old-but-live runs survive pruning; completed or abandoned app-owned resources can be reclaimed; resumable batches retain uploads; a Files API failure in Economy mode never silently triggers full-rate inline work; oversized authorized inline fallback fails honestly; unrelated files/uploads are untouched; cleanup failure does not discard completed findings.

### WP-19 — Valid report-chat history after every termination path

**Priority:** P1. **Covers:** R4; server/client tool and fallback replay integrity.  
**Primary files:** embedded JavaScript in `html_report.py`, report-chat/browser fixtures.  
**Dependencies:** shared replay requirements from WP-01/WP-13; no need to wait for bounded retrieval.

Implementation:

1. Represent pending/completed tool relationships by ID and block type. Client and server tools have different response/replay semantics; use an explicit turn state rather than testing only `type === 'tool_use'`.
2. During a legitimate mixed-tool continuation, preserve the deferred server call needed by the service when client results return. Do not remove every unmatched server block indiscriminately before normal continuation.
3. When a turn is abandoned by Stop, refusal, stream failure, or continuation-cap exhaustion, normalize it into safe reusable history. Remove unresolved tool requests while retaining completed tool/result pairs and useful visible text. Do not fabricate success results for tools that never executed.
4. Use the same normalization contract at live commit, storage save, and storage load. Version stored transcripts and repair legacy poisoned tails idempotently while preserving usable conversation content.
5. Preserve provider-required fallback boundaries, selective replay rules, and valid signed thinking. Maintain fixtures for pre/post-fallback block types and paired/unpaired server results.
6. Keep generation guards so an older asynchronous request cannot commit after New chat, transcript replacement, or reload. Stop must remain effective during client-tool execution as well as network streaming.
7. Show a concise explicit message when a continuation cap ends a response. Permit the next ordinary question only after the stored/request history is coherent.

Regression matrix: mixed client/server parallel calls; Stop before/during/after each phase; multiple IDs; partially streamed tool JSON; paired server result versus deferred server call; repeated pause turns; limit reached; refusal; fallback; reload; conversation replacement while work is active.

**Acceptance:** a new question after each interrupted scenario uses valid history; saved/reloaded conversations behave the same; completed evidence is retained; no fictitious tool action appears. Confirm representative replay with real-SDK schema tests and a separately budgeted live canary.

### WP-20 — Bounded assistant context, accurate chat costs, and calculator input

**Priority:** P1/P2. **Covers:** unbounded context, H3, N7, reader-key storage risk.  
**Primary files:** `html_report.py`, browser fixtures.  
**Dependencies:** WP-03 identity, WP-14 accounting semantics, WP-19 transcript integrity.

Implementation:

1. Replace the unconditional full-report system block with bounded report/run context and an index. Keep full content available locally through retrieval tools that fetch sheet digests, findings, and search snippets by stable source/page or claim identity.
2. Define explicit pre-request budgets for system context, index, retrieval results, result count, history, and output/continuation reserve. A large index must page or summarize with access to omitted entries; silently dropping late sheets is unacceptable.
3. Return bounded retrieval responses with source identifiers, truncation indicators, and stable pagination. Duplicate human sheet labels require disambiguation. Missing/failed content must differ from a search with no match.
4. Trim/summarize history only at complete exchange boundaries. Preserve current evidence, disclose summarization, and keep the assistant's source limitations clear. The report wrapper remains a useful data boundary but is not a context budget or a security sandbox.
5. Reconcile cumulative usage updates instead of adding message-start and final totals twice. Include final input/cache counters, server iterations where exposed, and chargeable search counts. Distinguish estimates, measured tokens, and incomplete billing. Keep rate effective dates.
6. Require a full numeric grammar in the calculator. Reject malformed decimals/exponents and adjacent whitespace-separated numbers. Bound expression length, nesting, exponent size, and computational work; use no `eval` or remote execution.
7. Select a declared arithmetic precision policy. If promising exact supported decimal/rational arithmetic, use a vetted local implementation or bounded exact representation with explicit division rounding. Otherwise state supported numerical limits and reject values whose precision cannot be honored. Do not silently return zero for distinct large integers.
8. Remove the unconditional “guaranteed correct” tool wording. Return validation/range errors as tool results, not plausible-looking arithmetic answers.
9. Validate local-file reader-key storage with disposable dummy keys in supported browsers: same-tab navigation, other tabs, reload, Forget, and unavailable storage. Do not claim universal file-origin isolation.
10. Prefer in-memory credential retention where persistent session isolation cannot be established. Preserve explicitly selected embedded-key behavior and sharing warnings; do not introduce background persistence or load unrelated saved credentials.

Acceptance fixtures:

- A synthetic 400-sheet report answers targeted questions about first/last/duplicate-labeled sheets without embedding the entire corpus.
- Retrieval pagination and history trimming cannot split tool exchanges or hide that content was omitted.
- Equivalent cumulative usage event sequences yield identical totals, including search charges.
- Reject `1.2.3 + 1`, `1e+ + 2`, and `1 2 + 3`; compute the large-integer subtraction correctly or reject it explicitly; ordinary supported calculations remain useful.
- Dummy-key browser tests establish the actual storage boundary; mitigation and documentation reflect the measured result.

### WP-21 — Report vocabulary, grouping, PDF plans, and destinations

**Priority:** P1/P2. **Covers:** H1, H2, R5, B8 consumers, N9; report search efficiency.  
**Primary files:** `html_report.py`, `annotate.py`, markup manifests/receipts.  
**Dependencies:** WP-03 identities, WP-05 evidence states.

Implementation:

1. Derive one display vocabulary that distinguishes sheet-level observation, no quote supplied, quote not found, not checked, valid inconclusive judgment, and failed verification attempt. Keep anchor placement separate from verdict status.
2. Apply this vocabulary consistently to HTML rows, filters, counts, assistant data/tools, starter questions, PDF labels, and exported fields. Do not count an intentional quote-less observation as a hallucinated quotation.
3. Recompute repeat grouping after every sort/filter using the current visible row order. Preserve expansion preferences where possible; a hidden former representative cannot orphan visible followers.
4. Cache normalized searchable content for immutable report blocks. Preserve the existing debounce unless measurements justify a change; keep search semantics identical and exclude transient controls/highlights from the index.
5. Return finalized worker placements with receipts. Merge them into the parent by unique placement identity before emitting the markup plan. Missing/conflicting worker outcomes are explicit errors, not a reason to fall back silently to the original intention.
6. Use the new finding identity for artifact ownership and bookmark uniqueness, with separate placement and leg identities. QC numbers remain display labels.
7. Record actual written destinations, including the bounding rectangle of each overflow-note row. Build index/bookmark links from the actual destination page/coordinates, and retain a separate backlink to original drawing evidence.
8. Compare serial and process-worker semantic output. Do not require random transport/run stamps to match; do require disposition, ordering, destinations, and coverage conclusions to match.

**Acceptance:** same-quote distinct findings have distinct bookmarks and correct index destinations; every placement agrees with its receipt; forced overflow navigates to the correct notes row; grouping remains correct after sort/filter; no-quote states are described honestly; search results are unchanged by indexing.

**Validation:** multi-source forced-overflow fixtures, duplicate basenames/labels/quotes, cross-sheet legs, relevant rotated/CropBox cases, and saved-PDF link inspection. Establish N9's actual viewer effect before claiming a visible fix. Native annotation grouping/named destinations are gated separately in WP-25.

### WP-22 — Diagnostics, configuration fidelity, and defensive deserialization

**Priority:** P1/P2. **Covers:** secret-redaction performance, path gaps, run-configuration/status boundary cases, string refs.  
**Primary files:** `diagnostics.py`, `run_journal.py`, `models.py`, `pipeline.py`, configuration tests.

Implementation:

1. Replace pathological secret-field matching with bounded/linear behavior while preserving credential coverage. Redact before persistence; truncating first must not expose an otherwise recognizable secret prefix.
2. Give registered private-root matching valid boundaries on both sides and protect unrelated URLs. Handle quoted paths, spaces, doubled separators, UNC/extended-length Windows forms, and ordinary POSIX paths deliberately.
3. Keep useful basenames where allowed, but remove private directory components. Apply sanitization consistently to host-generated errors/status in every exported artifact. Do not blanket-redact drawing prose such as `TOKEN: 12` as if it were host credential output.
4. Resolve the actual critique-read count once and use it in configuration, execution, keys, estimates, and manifests. Audit other flags that are represented as enabled but ignored outside markup.
5. Publish an explicit supported configuration matrix. For expert verification/investigation requests outside markup, either honor the request or reject/resolve it visibly before paid work; do not report a stage as enabled while silently skipping it.
6. Strengthen required-stage rollup so missing required stage records cannot yield COMPLETE. Keep genuinely nonrequired stages out of the required denominator. Test malformed input state separately from reachable normal execution.
7. Normalize string `refs` to one reference through a shared coercion helper; handle null/list/malformed mixed inputs explicitly. Keep additive serialization compatibility and normal list round-trips.
8. Update stale descriptions only after behavior is established. Remove truly unused production helpers when their deletion is safe and reduces conflicting policy; preserve tested compatibility shims unless deliberately deprecated.

**Acceptance:** adversarial redaction input does not exhibit quadratic growth; supported secrets/private path forms do not leak; URLs are not corrupted by root replacement; manifests describe actual effective settings; absent required outcomes cannot imply completion; string references no longer split into characters.

### WP-23 — Reproducible packaging and enforceable release acceptance

**Priority:** P1. **Covers:** G4, G5, N8; installer upgrade hygiene, self-check, license/audit gaps.  
**Primary files:** `packaging/windows/*`, dependency constraints, `.github/workflows/*`, acceptance scripts/docs.

Implementation:

1. Replace broad collection of the application package's arbitrary data with an explicit data allowlist plus deliberate dynamic imports. Preserve required GUI theme/native assets; distinguish application data from third-party package-specific collection.
2. Add packaging checks that fail on prohibited key files or credential patterns in the built bundle. Use dummy secret fixtures and sanitized failures; never echo a real key if one is found. Clean-checkout CI is useful but does not protect local builds by itself.
3. Constrain the tested runtime and shipped runtime consistently, including GUI dependencies and transitive platform packages. Pin build-tool dependencies including PyInstaller hooks. Document platform-specific constraint files if one universal lock is inaccurate.
4. Run release acceptance under those constraints. Keep dev/browser tools separate where necessary, but make the runtime dependency set match the installer. Verify the frozen dependency inventory against the declared constraints.
5. Make the frozen self-check test the intended credential backend's functional availability without persisting a real credential. A temporary dummy round-trip must clean itself up and fail clearly if the backend cannot work.
6. Verify architecture declarations against the actual built interpreter and supported Windows targets. Evaluate `x64compatible` installation mode with the supported platforms; do not promise native ARM support from an x64 build.
7. Make upgrades replace the managed runtime tree so removed packages do not remain in `_internal`. Stop the running application first and limit cleanup to verified installer-owned paths. Preserve user configuration, keys, reports, and user profiles; test interrupted upgrades and uninstall policy.
8. Extend the license gate from “metadata exists” to an explicit maintained allowlist/review policy with actionable unknown/restricted results. Do not let an automated agent invent legal compatibility judgments for unfamiliar licenses. Keep required AGPL notices and distribution obligations documented.
9. Add machine-enforced stable-release acceptance. Prefer a release-run attestation bound to the tested candidate commit and built artifact hashes, plus a protected approval boundary. Validate required manual sections or explicit owner waivers with scope, justification, approver, and expiry.
10. Avoid a self-referential requirement that a tracked approval file contain its own future commit hash. An external attestation can bind the exact candidate; a repository-record approach must define a code-tree fingerprint and strictly limit allowed evidence-only changes after testing.
11. Gate `publish`, not merely an advisory check. A matching version/tag and green automated suite are necessary but insufficient. RC publication remains clearly marked prerelease and must not become the updater's stable latest release.
12. Test missing, stale, expired, wrong-commit, wrong-artifact, and valid acceptance records. Validate any existing repository/environment protection separately; YAML alone cannot prove administrators configured it.

**Acceptance:** a deliberately injected dummy key file cannot ship; tested/frozen runtime inventories match; upgrades remove retired runtime packages without deleting user data; no stable release can pass the defined publication boundary while required acceptance is incomplete. Agents may prepare the gate and evidence but may not self-approve human acceptance.

### WP-24 — Update authenticity, download constraints, and launch verification

**Priority:** P1/P2. **Covers:** G6 and update-channel hardening.  
**Primary files:** `core/updates.py`, GUI update flow, manifest generator, release workflow/docs.  
**Dependencies:** WP-23 release integrity; coordinate signing-key ownership with the maintainer.

Implementation:

1. Enforce HTTPS through the redirect chain, not only on the original URL. Apply explicit manifest/download host policy including the legitimate release-asset redirect hosts; self-hosted forks require a deliberate configuration path, not arbitrary manifest-supplied trust.
2. Bound installer size before and during streaming; treat Content-Length as advisory and enforce the byte counter. Reject excessive, malformed, or unsupported responses and clean partial downloads safely.
3. Authenticate the manifest with a maintained signature implementation and an embedded trusted public key/key set. Sign the fields governing version, platform/architecture, URL, hash, size, and schema under a documented canonical encoding; reject ambiguous serialization and unknown required schema versions.
4. Define key custody, key IDs, rotation, revocation, and bootstrap compatibility. Never put a signing private key in the repository. A signing key controlled by the same unreviewed release-write path does not provide the independent protection the design claims.
5. Publish compatible signed manifests before enforcing signatures in new clients; older clients may ignore additive fields. Do not silently fall back from a failed signature to trusting an unsigned manifest. Any transitional unsigned mode must be explicit, bounded, and documented.
6. Reverify the downloaded artifact immediately before launch, after the confirmation wait. Validate its expected signer as well when OS signing is available. Minimize the local substitution window using suitable file/path ownership controls; a last-moment hash alone does not eliminate every same-user race.
7. Preserve downgrade protection and RC exclusion. Avoid surprise update prompts over active cost/file dialogs; defer presentation until the application is in a suitable idle state.
8. Evaluate Authenticode as a separately provisioned build capability. Add a tested signing/verification hook when credentials are available; do not promise that signing always eliminates reputation warnings or that unsigned execution is merely cosmetic.
9. Correct documentation: checksums are integrity checks, not signatures; the application contacts GitHub/update hosts as well as Anthropic; describe local-state/uninstall retention honestly.

Regression matrix: non-HTTPS redirect, unapproved host, legitimate release redirect, oversized transfer with false/absent length, changed file after download, invalid/missing signature, unknown/rotated key, wrong platform, downgrade, prerelease, interrupted download, repeated update action, missing signing credentials.

**Acceptance:** unauthenticated or substituted update content cannot pass the selected trust policy; no fallback silently weakens it; error/partial-file handling is bounded; operational signing setup and any remaining external dependency are explicitly recorded before secure-update defaults are claimed complete.

### WP-25 — Measured optimizations and viewer compatibility experiments

**Priority:** P2; decision-gated. **Covers:** original API cost levers and proposals 4–7, 13–14 where not already mandatory.

Do not mix these experiments with the correctness baseline. Each experiment requires: hypothesis; implementation flag; fixed comparison corpus; expected cost/latency/quality measures; maximum live spend; cache-contract changes; acceptance threshold chosen before examining results; rollback behavior; and a recorded adopt/reject/defer decision.

| Experiment | Required evaluation and safeguards |
|---|---|
| Shared digest/critique vision prefix and per-sheet scheduling | Compare actual request prefixes and cache hits; preserve stage-specific instructions, whole-sheet coverage, and digest prose. Measure quality, throughput, and image/input charges. Account for memory/worker pressure and cross-stage dependencies. This is an architectural/prompt change, not merely a hash bump. |
| Batch prompt caching | Test a one-hour cache on repeated specifications/prefixes behind a flag. Measure reads/writes across real batch scheduling and include the zero-hit premium. Keep ordinary batch discount and request limits correct. |
| Critique cache TTL | Compare actual inter-read start times and hit rates. Use the correct model-specific multipliers; select policy from measured reuse rather than assuming five minutes or one hour always wins. |
| Cross-QC text allocation and cross-shard recall | Compare a token-budgeted allocation with the 4,000-character baseline. Evaluate grouping/retrieval that exposes planted cross-shard conflicts, late schedules, and large-set cases. Bound call count and output needs; complete pair co-presence may be too costly. Do not relabel omitted evidence as complete. |
| Structured outputs for identity/planner/cross-QC | Prove request compatibility and host semantic coverage first. Reuse stage-local latches/effective-contract keys; retain refusal/truncation handling. Citation-producing output remains subject to current citation/format incompatibility. |
| Diverse second critique model or reduced read count | Compare recall, precision, repeated-error correlation, and total cost on the existing A/B harness. Record actual model provenance. A different model name is not proof of independent correctness. |
| Smaller overlap, adaptive tile resolution, smaller overview | Preserve all content-bearing tiles and test tiny text, dense schedules, dimension strings, match lines, rotated/raster sheets, and boundary-straddling objects. Measure visual/read quality, not only bytes. No default change without non-regression evidence. |
| Verifier text alongside crops and initial investigation pre-search | Bind extracted words to the exact crop/source revision; compare numerical-reading accuracy and call count. Text supplements image evidence and must not silently override it. |
| Investigation forced-close/tool-choice cache policy and shorter TTLs | Measure actual cache charges; retain host execution limits and valid tool histories. Do not rely only on a prompt to enforce budget. |
| Batch verification | Preserve verdict identity, per-item completeness, cancellation, evidence ownership, and result collection; measure latency/price tradeoff. |
| New web-tool variants | Check current official support and actual capability, then exercise a canary. Response-inclusion controls can omit data needed for source trails/replay; prove compatibility. Do not enable an uncertain model/tool combination globally. |
| Native PDF grouping and named destinations | Test Acrobat, Bluebeam, and supported browser viewers. Use unique annotation `/NM` values per component and valid same-page `/IRT`/`/RT /Group` relationships. Preserve layers, printing, moving/selecting groups, receipts, and comment exports. Keep navigation fallback. Do not promise one Markups List row without viewer evidence. |

**Acceptance:** every experiment ends in a supported decision. A rejected optimization is a valid outcome. Features without evidence remain off by default and cannot be advertised as delivered savings or compatibility.

## 6. Regression corpus and integrated acceptance

### 6.1 Minimum shared regression corpus

Build small, deterministic fixtures that capture the review's failure mechanisms. Prefer synthetic drawings/text with explicit expected findings; do not require private project drawings in public CI. A representative private evaluation corpus may supplement the synthetic corpus under the existing privacy policy.

| Fixture group | Required content |
|---|---|
| Merge/signature | Bridge findings at 500/550 gpm; 6-inch/4-inch; 12,500/1,500 CFM; shared 100 psi; temperature variants; distinct same-quote actions. |
| Anchor/grounding | All seven punctuation/spacing examples plus numeric/sign/unit counterexamples, repeated labels, short tags, textless and hybrid pages. |
| Arithmetic | Correct repeated-operand equation; duplicated model operand; tag-contained digits; invalid/scientific forms; genuine sum/product mismatch. |
| Cross-source | Two PDFs with the same sheet ID and similar tags; reversed conflict direction; two distinct issues sharing the same two quotes; three-leg conflict. |
| Auditor precision | Numeric row versus CSI reference; pump/breaker notation; reference phrase variants; labeled sheet ID with distractors; FM cases; real versus prose-only index. |
| API outcomes | Empty/nonempty refusal; parseable truncation; partial stream; fallback blocks/iterations; canceled/expired/errored batch envelopes; malformed and valid inconclusive verdicts. |
| Source/lifecycle | Missing source after inventory; corrupt page; changed revision; lost submission acknowledgement; partial collection; expired remote result; active-but-idle work directory. |
| Citation/identity | Split cited JSON string; fetch-only and multi-continuation sources; late adoption text; incidental versus adopted editions; international/all-caps counterexamples. |
| Browser/report | Mixed pending tools; interrupted/reloaded conversation; oversized report; duplicate labels; grouping after sorting; malformed calculator; cumulative usage events. |
| PDF/output | Same-quote distinct findings, forced notes overflow, multiple sources/workers, relevant rotation/CropBox combinations, actual link destinations and receipts. |
| Packaging/update | Dummy key in package data, stale runtime files on upgrade, incomplete acceptance, invalid signature, redirect downgrade, oversized/changed installer. |

### 6.2 Cross-product checks without an impractical combinatorial suite

Choose pairwise coverage for the following dimensions, then add explicit cases where a defect requires a particular combination:

- Real-time, batch, hybrid; initial submission and recovery transport.
- Cold cache, compatible warm cache, old invalidated cache, mixed per-sheet cache hits.
- Plain, structured, rejected-then-plain, and concurrent capability-latch change.
- Single/multiple source PDFs; duplicate labels/basenames; normal/rotated/raster/hybrid evidence.
- One/multiple workers; reordered result arrival.
- Success, partial source failure, model failure, cancellation, restart/resume, interrupted export.

Use semantic comparisons for findings/stages/plans while explicitly excluding expected run IDs, timestamps, remote IDs, and measured usage differences. Do not hide a nondeterministic QC number under an overbroad comparison exclusion.

### 6.3 Required end-to-end assertions

1. Expected pages equal completed, failed, canceled/deferred, or explicitly unresolved pages; no page silently disappears.
2. Distinct expected findings and cross-sheet legs survive every producer, merge, verification, cache, and export boundary.
3. Every deterministic arithmetic result has independently established operand evidence or is downgraded honestly.
4. Every completed stage satisfies its declared required-work coverage, and no syntactically valid refusal/truncation qualifies as a finished read.
5. Every billable/logical attempt is represented once; partial unknown spend is visibly incomplete.
6. Cold/warm and serial/parallel runs agree on semantic findings, status, numbering, final placements, and navigation.
7. Partial/canceled/recovered runs can export retained work with correct status, journal, manifest, and evidence.
8. Saved/reloaded chat can ask the next question after any supported interruption without an invalid history.
9. No secret or unintended private path appears in logs, reports, manifests, test artifacts, or the distributable.
10. The stable publish job is blocked when required acceptance is missing or stale.

### 6.4 Validation order

For each package: demonstrate a focused failing regression, implement the correction, run the meaningful targeted suite, and inspect affected artifacts. Avoid tests that merely duplicate implementation details or snapshot unstable output without validating behavior.

After integration: run the full hermetic acceptance process with network tests explicitly deselected, including browser execution checks and applicable packaging smoke tests. Then run separately budgeted live canaries, Windows credential/installer/path checks, representative real-drawing comparisons, and supported PDF-viewer checks. Record failures and limitations rather than converting unavailable infrastructure into a pass.

Do not repeatedly run an expensive full suite without new edits or unresolved failures that justify it. Use focused tests during development and broaden at defined integration boundaries.

## 7. Traceability register

### 7.1 Every numbered finding in the original report

| Finding | Required package(s) | Completion nuance |
|---|---|---|
| B1 | WP-03, WP-04 | Symmetric full-member comparison; ranking/order variants tested. |
| B2 | WP-04 | Hyphenated units without weakening tag parsing. |
| B3 | WP-04 | Whole-number grouping and no trailing fragment. |
| B4 | WP-05 | Positive extraction variants plus numeric false-match vetoes. |
| B5 | WP-05, WP-06 | Short tags require evidence; textless fallback remains honest. |
| B6 | WP-06 | Fix prompt field, keep validation strict. |
| B7 | WP-03, WP-07 | Distinct arithmetic findings survive the coordinator. |
| B8 | WP-03, WP-21 | Claim identity, numbering, bookmarks, evidence, destinations. |
| B9 | WP-03 | Preserve meaningful actions/provenance, not every paraphrase as a separate issue. |
| B10 | WP-06 | Canonical evidence legs plus claim identity, not a sheet-set-only key. |
| B11 | WP-09 | Boilerplate rejected before both model call and degraded finding. |
| B12 | WP-04 | Equivalent notation without collapsing temperature scales. |
| R1 | WP-11 | Isolate opens/pages; retain context and completed paid work. |
| R2 | WP-01, WP-17 | Refusal recovery preserves selected transport and bounds. |
| R3 | WP-14, WP-17 | Canceled envelopes still have attempt provenance. |
| R4 | WP-19 | Pending server tools, Stop/caps, save/load, next-question validity. |
| R5 | WP-21 | Parent uses finalized worker placements. |
| R6 | WP-15, WP-18 | Reuse hybrid spool or avoid unused creation. |
| R7 | WP-13, WP-18 | Finalize successfully saved evidence on error paths. |
| C1 | WP-12 | Contiguous cited text; no inserted JSON newlines. |
| C2 | WP-12 | Full host evidence text, including late adoption notes. |
| C3 | WP-14 | Actual one-hour/mixed TTL pricing. |
| C4 | WP-13 | Separate bounded search/evidence allowances and honest wording. |
| C5 | WP-12, WP-14 | Sources/usage across search, fetch, and continuations. |
| C6 | WP-12 | Em dash and deliberate edition grammar. |
| $1 | WP-15 | Calibrated reasoning-inclusive output distribution. |
| $2 | WP-15 | Drawing text and framing overhead affect estimate. |
| $3 | WP-15 | Avoid unnecessary hashing/duplicate scans and hybrid writes. |
| K1 | WP-10 | Tile-label wording participates in effective identity. |
| K2 | WP-10 | Cross-QC user framing participates in effective identity. |
| K3 | WP-10 | Cache actual batch/plain/structured contract. |
| K4 | WP-10 | Cache original planner loss metadata. |
| K5 | WP-03 | Same claims receive same QC ordering regardless of ingestion. |
| A1 | WP-08 | Contextual spec-reference evidence. |
| A2 | WP-08 | Arrangement matters even with a frequency winner. |
| A3 | WP-08 | Inventory-scoped memoization and lazy nearest matching. |
| A4 | WP-08 | Phrase/list recall with a negative corpus. |
| A5 | WP-08 | Label/context ranking and explicit ambiguity. |
| A6 | WP-08 | Correct conditional FM displacement; preserve FM-only behavior. |
| A7 | WP-08 | Actual index region and partial-package handling. |
| A8 | WP-07 | No tag-contained operands or silently truncated scientific numbers. |
| H1 | WP-21 | Regroup current visible order after sort/filter. |
| H2 | WP-05, WP-21 | Separate no quote, sheet scope, unmatched quote, and verdict. |
| H3 | WP-20 | Final cumulative token/tool usage in chat cost. |
| H4 | WP-12 | Contextual international/code-window ranking. |
| G1 | WP-17 | Cancellation plus durable resumption, not merely a quit warning. |
| G2 | WP-16 | Immutable run client and disabled edit UI. |
| G3 | WP-16 | BOM normalization and verified safe migration. |
| G4 | WP-23 | Explicit app data plus distributable secret checks. |
| G5 | WP-23 | Same constrained runtime in tests and installer, pinned hooks. |
| G6 | WP-24 | Reverify after confirmation and before launch. |

### 7.2 Additional findings and unnumbered concerns

| Concern | Package/disposition |
|---|---|
| N1 shared measurement masking | WP-04; mandatory. |
| N2 distinct cross-QC claim loss | WP-03/WP-06; mandatory. |
| N3 repeated-operand false certainty | WP-07; mandatory. |
| N4 terminal-state success/cache errors | WP-01/WP-10; mandatory. |
| N5 verification false completeness | WP-01; mandatory. |
| N6 duplicate-source cross-QC binding | WP-06; mandatory. |
| N7 calculator grammar/precision | WP-20; mandatory. |
| N8 acceptance hold not enforced | WP-23; mandatory. |
| N9 overflow destination coordinates | WP-21; validate and correct the traced mismatch. |
| Actual serving model, fallback iterations, partial-stream billing | WP-14; mandatory. |
| Fallback text joins and selective history replay | WP-01/WP-12/WP-13/WP-19; preserve contiguous text and required block semantics. |
| Generic output-config rejection disables task budget | WP-13; mandatory. |
| Oversized inline fallback and upload quota failures | WP-18; mandatory explicit handling. |
| Remote orphan files; daemon-only cleanup | WP-17/WP-18; owned durable cleanup, not a blind org-wide sweep. |
| Cross-QC output cap/recovery | WP-01/WP-06; mandatory terminal honesty; cap tuning evaluated. |
| Cross-QC text truncation and 40-fact bottleneck | WP-06 observability; WP-25 quality/cost redesign. |
| Whole-set grounding absent | WP-05/WP-06; mandatory. |
| Live but idle work-directory pruning | WP-18; validate with synthetic liveness fixtures. |
| Mentioned versus adopted codes; limited edition families | WP-12; mandatory distinction and bounded grammar coverage. |
| Prose match threshold/call prevalence | WP-09 instrumentation; change only with labeled evidence. |
| Investigation truncation, Unicode IDs | WP-13; mandatory handling and bounded recovery. |
| Quadratic redaction and path-scrub gaps | WP-22; mandatory. |
| Empty required-stage/status cases | WP-22; defensive hardening, separately labeled from N5. |
| Resolved configuration versus execution | WP-16/WP-22; mandatory truthful effective configuration. |
| String references split into characters | WP-22; input-boundary correction. |
| Unbounded report/history context | WP-20; mandatory budgeting/retrieval. |
| Search rescans large report | WP-21; measure and preserve results. |
| Local-file sessionStorage exposure | WP-20; browser-specific validation and appropriate credential policy. |
| Persistence reentrancy, cleared key reloaded during export, no Forget | WP-16; mandatory. |
| Frozen keyring functionality | WP-16/WP-23; functional acceptance. |
| Update dialogs interrupt another modal workflow | WP-24; defer presentation safely. |
| Uninstall state retention | WP-23 documentation and explicit policy; do not silently delete user data. |
| License script checks only metadata | WP-23 reviewed license policy. |
| Network-description and checksum/signature documentation | WP-24; correct concrete claims. |
| Test fake fidelity, missing batch canary, no socket guard | WP-02; mandatory. |
| Narrow lint classes and dead code | WP-22/WP-23; selectively enable useful F/B rules after triage; avoid mass unrelated formatting. |
| Broken cryptography wheel on the original review machine | Environment diagnosis only; do not label as a current app bug without reproduction. |
| Remove tiktoken | Already done; preserve. |
| Add Dependabot | Already present at original baseline; no duplicate work. |
| Broad “everything sound” assertions in original report | Revalidate touched areas; WP-01 explicitly corrects the overbroad truncation claim. |

### 7.3 Original ranked proposals

| Proposal | Planned disposition |
|---|---|
| 1. Symmetric merge, identity, provenance | WP-03/WP-04. |
| 2. Anchor robustness | WP-05, with false-grounding counterexamples. |
| 3. Digest fault isolation | WP-11. |
| 4. Shared vision prefix/pipelining | WP-25 measured experiment. |
| 5. Full-text cross-QC/grouping | WP-06 correctness, WP-25 bounded allocation/recall experiment. |
| 6. More structured-output stages | Preserve existing gates; WP-25 compatibility/quality gate. |
| 7. Ensemble diversity/read-count change | WP-25 evaluation; no automatic claim of independence. |
| 8. Host pre-search/crop text | WP-13 useful bounded pre-search; WP-25 measured quality benefit. |
| 9. Estimate calibration | WP-14/WP-15. |
| 10. Bounded report assistant | WP-20, including history as well as initial context. |
| 11. Auditor precision | WP-07/WP-08. |
| 12. Ledger provenance | WP-03/WP-14. |
| 13. Native PDF grouping/deep links | WP-21 correct destinations; WP-25 viewer-gated grouping. |
| 14. Files hygiene | WP-17/WP-18 with ownership/liveness controls. |
| 15. Cancellation/resumability | WP-17. |
| 16. Key handling | WP-16. |
| 17. Update channel | WP-24 plus release trust in WP-23. |
| 18. Packaging/CI | WP-23; tiktoken removal and Dependabot already satisfied. |

## 8. Cache, artifact, and compatibility release checklist

- [ ] Every changed request/normalization/identity contract has a version or fingerprint change at every shortcut capable of restoring its output.
- [ ] Unsafe old refusal/truncation/identity/structured-result entries are rejected; compatible successful content is reused only with sufficient evidence to do so safely.
- [ ] Legacy findings and exports remain readable; identity aliases/rebinding are explicit and unambiguous.
- [ ] New serialized fields have safe defaults; missing required completeness metadata cannot default to success.
- [ ] Evidence files, placement IDs, bookmarks, QC labels, HTML tools, and comparison scripts agree on the new identity contract.
- [ ] Planner loss, source ambiguity, omitted evidence, and partial outcomes survive cache round-trips.
- [ ] Transcript migration is versioned, idempotent, and retains valid content while repairing invalid tails.
- [ ] Durable jobs cannot resume against changed source revisions or incompatible contracts without an explicit safe transition.
- [ ] No migration deletes historical exported reports or arbitrary user/cache directories.
- [ ] Documentation and help describe the resulting behavior and actual limitations, including cost forecasts, cancellation, keys, and update trust.

## 9. Release sequencing and rollback

Prefer reviewable vertical changes over one giant patch. A practical sequence is:

1. Test-contract improvements plus terminal/status corrections and their narrow cache invalidation.
2. Identity/merge/quantity/arithmetic corrections with end-to-end findings and export regression coverage.
3. Anchoring, cross-source evidence, auditor, citation/adoption, and prose corrections.
4. Run isolation, credentials, accounting, cancellation/resumption, and resource lifecycle.
5. Chat/report/PDF behavior, diagnostics, calibrated estimates, packaging, and update hardening.
6. Separately flagged evaluated optimizations.

Adapt boundaries to actual code ownership, but never ship a consumer expecting a new identity/status schema before the producer/migration is present. Temporary compatibility adapters must be documented and tested, with an explicit removal criterion.

Rollback must preserve already-created reports and durable job records. A rollback may stop reading newer caches rather than reinterpret them incorrectly. Never resume a newer-format pending job through an older implementation unless compatibility is demonstrated. New performance features must have a flag or equivalent reversible rollout path. Correctness fixes should not silently revert to unsafe behavior when an optional capability fails.

Operational dependencies that may require maintainer action include signing-key provisioning, protected release-environment setup, live API budget, supported PDF viewers, and Windows credential/installer acceptance. Complete all code, fixtures, dry-run checks, and reviewable configuration first; record the remaining external gate precisely instead of calling the entire package complete.

## 10. Final deliverables from the implementation agents

For each completed package, deliver:

1. A concise behavior change description tied to the issue IDs.
2. The selected data/request/identity contracts and any deviations from this plan, with reasons.
3. Meaningful regression tests and the validation actually executed.
4. Cache/schema migration notes, compatibility behavior, and rollback limitations.
5. Representative exported evidence where the change affects HTML, PDFs, manifests, or job recovery.
6. Known limitations and conditional findings that were disproved, deferred, or still need external validation.

The integrated release report must include the traceability register with every item assigned **implemented and validated**, **already satisfied**, **disproved with evidence**, **experiment rejected/deferred with rationale**, or **blocked on a named external gate**. An unresolved mandatory correctness item is not converted into “optional” simply because it is difficult.

Final release approval requires: no unaddressed P0 defects; coherent source/finding/evidence identity; truthful completeness and usage; recoverable paid work; successful relevant browser/PDF/Windows checks; and enforced, explicitly approved stable-release acceptance. Do not reuse historical passing test counts as evidence for the new candidate.

## 11. Authoritative technical references to verify at implementation time

Provider/SDK details can change. Check the installed SDK and current primary documentation before finalizing request shapes, supported tools/models, pricing, replay rules, and operational limits.

- [Anthropic refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback): response terminal state, per-attempt usage, serving model, batch refusal behavior, and selective replay.
- [Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching): prefix ordering, TTL timing, multipliers, and cache invalidation.
- [Anthropic batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing): submission/result/cancellation lifecycle and batch caching.
- [Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs): supported request format and incompatibilities.
- [Anthropic citations](https://platform.claude.com/docs/en/build-with-claude/citations): citation-bearing text blocks and structured-output constraints.
- [Anthropic web fetch](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-fetch-tool): deferred mixed-tool behavior, sources, current variants, and response-inclusion limitations.
- [MDN sessionStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage): origin/tab storage behavior and invalid-origin restrictions; supplement with actual supported-browser tests.
- [Adobe PDF 1.5 reference](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/pdfreference1.5_v6.pdf) and [PDF 1.6 reference](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/pdfreference1.6.pdf): annotation names, reply/group relationships, and destinations; validate practical behavior in supported viewers.
- [Python urllib.request](https://docs.python.org/3/library/urllib.request.html): redirect behavior; test the app's explicit HTTPS/host policy rather than relying on the initial URL check.

Repository execution entry points include `scripts/run_acceptance.py`, existing focused tests under `tests/`, the A/B and benchmark scripts under `scripts/`, `docs/WINDOWS_MANUAL_ACCEPTANCE.md`, `docs/RELEASE_WINDOWS.md`, and the release-specific acceptance record. Use their current contents rather than assuming their commands or coverage stayed unchanged after this baseline.
