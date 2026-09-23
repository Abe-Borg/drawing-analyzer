# Drawing Analyzer: remediation and improvement implementation plan

Prepared: September 22, 2026  
Reviewed baseline: `da8f810add59d2c2731e92034efd5d671d7497ee` (`1.7.0`)  
Original report baseline: `f5284ac` (`1.6.0`)  
Repository: `drawing-analyzer`  
Re-verified: September 22, 2026, against `8521366`, whose code is identical to `da8f810` (see §1.3)

> **How this plan is executed.** This is a multi-session program.
> - [`README.md`](README.md): the session protocol every coding session follows.
> - [`PROGRESS.md`](PROGRESS.md): the slice queue, statuses, finding dispositions,
>   owner actions and handoff log. It is authoritative for *status and order*;
>   this plan is authoritative for *requirements*.
> - [`DECISIONS.md`](DECISIONS.md): the §4.1 contract decisions and the cache
>   migration register.
>
> Each work package ends with *Verification notes (2026-09-22)*. Read them before
> implementing: they correct several steps below.

## 1. Purpose and completion standard

This document is an execution plan for coding agents implementing the corrections identified in the September 2026 review and its reassessment against 1.7.0. It includes required behavior, implementation boundaries, dependencies, cache and data migrations, regression scenarios, rollout gates, and a traceability register.

The plan is not an instruction to apply every suggestion from the original report literally. Confirmed correctness and integrity defects are mandatory. Conditional defects require a bounded validation step and a recorded outcome. Changes to model selection, prompt structure, image resolution, context allocation, and cache policy require evaluation before becoming defaults.

Success means that the application retains distinct findings, attributes them to the correct physical evidence, reports incomplete work honestly, recovers completed paid work, and exports consistent review artifacts. A green unit suite alone is not sufficient. Each package has behavior-level acceptance criteria, and the release requires integrated evidence plus the applicable live-service and desktop-viewer checks.

This plan does not implement application changes. The implementation agent must recheck the current checkout before starting: later commits may already address an item. Reuse sound existing mechanisms instead of adding parallel implementations. When an item is already fixed, demonstrate that with current code and regression evidence and mark it complete; do not redo it.

### 1.1 Source material and reference conventions

- Read the repository's current `CLAUDE.md`, any applicable `AGENTS.md`, and relevant release/acceptance documentation before editing.
- Also read `docs/MEASUREMENT_PACKAGES.md`. Its §2 standing prohibitions bind this plan (§2 rule 15). Its measurement packages R-01 … R-06 overlap WP-25 and define the experiment protocol WP-25 must follow.
- **Naming collisions to keep straight.** `CLAUDE.md` and `docs/` cite an earlier, completed plan: packages WP-00 … WP-08, WP-03A/WP-03B, and references such as "WP-02 §7.1", "WP-05 §10.1" and "WP-07 §12.13". Those are **not** this plan's work packages. This plan's slices are always written `WP-nn.m`. The review's findings R1 … R7 are also unrelated to the measurement packages R-01 … R-06.
- Repository-relative paths in this document are navigation aids. Line numbers from the review are intentionally not treated as stable implementation anchors; locate the named symbols in the implementation checkout.
- IDs `B*`, `R*`, `C*`, `$*`, `K*`, `A*`, and `H*` refer to the original report. `G*` refers to its application/packaging findings. The original report is kept, unchanged, at [`DEEP_REVIEW_2026-09.md`](DEEP_REVIEW_2026-09.md). Its line numbers are against `f5284ac`.
- `N1` through `N9` identify additional findings from the reassessment. `N10` through `N27` are defects found when the plan was re-verified (§1.3). All are defined in section 3.
- `U1` through `U32` identify the unnumbered concerns in §7.2, so that the tracker can refer to them.
- Evidence behind the 2026-09-22 re-verification is in [`verification-2026-09-22/`](verification-2026-09-22/): per-area reports with current anchors, reproductions, and the pinned tests each change must re-baseline.
- Preserve the distinction between a reproduced defect, a traced failure path, and an unmeasured performance or compatibility risk in all completion reports.

### 1.2 Changes already present; do not undo or duplicate

The 1.7.0 baseline already removes `tiktoken`, adds optional structured outputs to verification and prose harvesting, shares structured-output gating, records verification parse-loss counters, and wraps report content for the chat prompt. Preserve those improvements.

Dependabot already manages Python and GitHub Actions dependencies. Do not add a duplicate configuration. Some helpers described as having no callers in the old report have test callers; distinguish production-orphaned code from entirely unused code before removing anything.
- **Test callers only:** `cross_qc._sheet_is_textless`, `annotate._expand_for_markup`, `PHASE_CROSS_CHECK`.
- **No callers anywhere:**
  - in `core/api_config.py`: `batch_service_tier`, `token_count_preflight_enabled`, `web_search_max_uses_for_severity`, `cross_check_max_tokens`, `verification_max_tokens`, `cache_diagnostics_params`, `extract_cache_diagnostics`;
  - also `core/tokenizer.count_tokens_via_api` and `verify._verify_cross_one`.

`tiktoken` is gone. The "Spec Critic" docstrings are still present (`core/api_config.py`, `core/app_paths.py`).

**Stable 1.7.0 has already shipped (N8 occurred).** `docs/releases/ACCEPTANCE-1.7.0.md` placed stable publication on hold pending the §§2–6 evidence or recorded waivers. Even so, tag `v1.7.0` was pushed at `da8f810`, and GitHub published "Drawing Analyzer v1.7.0" as a full (non-prerelease) release at 2026-09-21 22:13 UTC. That was about eight minutes after the hold record merged. It is the `latest` release that every install is offered.
- The acceptance record still reads "NOT YET TAGGED" / HOLD.
- Remediation therefore lands in a later release.
- What to do about the published 1.7.0 is an owner decision (`PROGRESS.md` O-1).

Do not treat a version literal or a successful CI run as permission to publish a stable release. WP-23.1 moves the minimal publish gate to the front of the queue for exactly this reason.

### 1.3 Re-verification against 1.7.0 (2026-09-22)

The plan was re-checked against the code before any implementation started.
- **Scope.** Eight verification agents covered every numbered finding, every §7.2 concern, and every work package's text. They ran the real functions with hermetic fakes (no API calls) and wrote short reproductions. Their reports, with current `path::symbol (line)` anchors, are in [`verification-2026-09-22/`](verification-2026-09-22/).
- **No code change since the plan was written.** `main` at `8521366` has the same code as `da8f810`.

Results:

- **Nothing had been fixed.** Every B, R, C, $, K, A, H and G finding, N1–N9, and every §7.2 concern (except the three recorded as satisfied) is still present. Most were reproduced; a few were traced. `tiktoken` removal and Dependabot are satisfied. The broken `cryptography` wheel is a container defect that `pip install cffi` resolves.
- **Five descriptions were wrong or incomplete, and are corrected in §3 and §7:**
  - **N9.** An overflow note never has a rect. Its index and bookmark links land at the top of the notes page instead of on its row. The "original rect" variant is a B8 identity-collision effect.
  - **A6.** The stated consequence is inaccurate. The real FM defect is N17.
  - **R3.** The attempt record is also lost on the terminal (non-harvest) path.
  - **B7.** Removing the coordinator's dedup is not enough: the ledger's geometry branch then merges the two mismatches.
  - **H2.** The PDF prints `[SHEET-WIDE]` for SHEET-hint findings; `[NO QUOTE TO CHECK]` applies only to the others.
- **Several steps would fail or cause damage if implemented as written.** The work packages' *Verification notes* correct them. The most consequential:
  - **WP-03 step 5 / B7:** the second arithmetic mismatch needs a claim discriminator.
  - **WP-04:** the critique cache stores post-merge findings, so a rule change needs a critique-scoped key term. It must never bump the global `digest_cache._SCHEMA_VERSION`, which would discard every paid digest.
  - **WP-06 step 4:** it cannot fix B10, because the ledger never compares A→B with B→A.
  - **WP-08 steps 1–2:** as written they break pinned tests and the CLAUDE.md naming rule.
  - **WP-12 step 5:** read literally, it breaks the Phase B two-tier trust contract.
  - **WP-14 step 5:** citation calls are mixed-TTL.
  - **WP-19 step 4:** a transcript schema bump would delete every saved conversation.
  - **WP-22 step 2:** a left path boundary would *reduce* scrubbing.
- **Eighteen new defects (N10–N27) were found and reproduced or traced.** They are listed in §3 and routed to work packages.
- **Scale.** 104 session-sized slices, excluding the 12 WP-25 experiments. The P0 core (Waves 0–2 in `PROGRESS.md`) is 40 slices. Adjacent S-sized slices can share a session. Several slices need owner actions: live budget, signing key, repository protection, Windows and PDF viewer checks.
- **Environment.** In the cloud container, `pip install -e ".[dev,browsertest]"` plus `pip install cffi` gives a clean baseline: 2,450 passed, 11 skipped. The browser suite runs 98/98 with the pre-installed Chromium.

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
15. **Standing prohibitions** *(added 2026-09-22)*. The rejected shortcuts in `docs/MEASUREMENT_PACKAGES.md` §2 remain in force. Where a step here seems to require one, stop and record a decision (§2.1). The ones that bear directly on this plan:
    - No quote found only in model output, another sheet, or a manufactured joined string is **text-grounded**. See WP-05.3.
    - No capped-text grounding check on the ≤40-entry whole-set path; ground against uncapped evidence text. See WP-06.2.
    - Never bump a cache contract counter *and* add a new hashed key term for the same change: either alone invalidates. Pick one, and record it in the migration register.
    - Never weaken fuzzy anchoring thresholds or remove cross-QC grounding checks.
    - No incidental removal of unused compatibility APIs. See WP-22.5. `count_tokens_via_api` is kept as the documented exact-count path.
    - Never turn two identical critique reads into digest-plus-critique while keeping the same confidence-label semantics. See WP-25.6.
    - No unmeasured overview shrink or output-cap reduction.
    - Reuse the existing A/B, benchmark and telemetry tools rather than building a parallel evaluation framework. See WP-09.2, WP-15.4 and WP-25.
    - No global schema-version, prompt-hash, model-default or pricing-date change without a specific changed contract.

### 2.1 Handling uncertainty and implementation choices

The implementing agents may choose helper names and internal representations that fit the repository. They may not weaken the acceptance criteria to make a preferred implementation pass. Prefer conservative retention of separate findings over unproven merging. Prefer an explicit uncertain or incomplete outcome over confidently binding evidence to the wrong source.

If a proposed change conflicts with a documented invariant, resolve the contract before implementation and record the decision. Routine reversible implementation choices do not need repeated user approval. Stable publishing, live-service expenditure beyond the authorized budget, signing-key custody, and manual release waivers remain explicit operational decisions.

## 3. Additional finding IDs

| ID | Problem | Priority |
|---|---|---|
| N1 | A shared measurement such as `100 psi` masks a conflicting `6 in` versus `4 in` measurement during deduplication. The same happens with a shared `12ft` in `12'-6"` vs `12'-8"`, and with partially overlapping tags (`P-1 + V-3` vs `P-1 + V-4`). | P0 |
| N2 | Cross-QC removes distinct claims that share the same sheet/quote/leg key. | P0 |
| N3 | Reused operand membership turns a duplicated model operand into a false DETERMINISTIC arithmetic finding. Also: a fabricated quote (UNANCHORED) or a claim resolving to no sheet is still DETERMINISTIC, skips verification, and inks as "math checked by computer from the sheet's own printed numbers". | P0 |
| N4 | Nonempty digest refusals and parseable incomplete critique responses can be accepted and cached. The digest caches at both levels, on both transports. Critique refusal and `max_tokens` reads count as completed reads. | P0 |
| N5 | Verification can report COMPLETE when required calls produced no usable judgment, or when some eligible items were skipped. Reproduced end to end: all-malformed, all-failed, and 1-verified-4-skipped runs report both the stage and the run COMPLETE. | P0 |
| N6 | Small-set cross-QC binds duplicate sheet labels using a first-wins map instead of physical source/page identity. Label-keyed binding also exists in:<br>• `cross_qc._dedup_findings` (both paths);<br>• `auditors.arithmetic._build_maps` (sourceless whole-set claims);<br>• `critique._leg_targets`;<br>• colliding `stem-pN` fallback ids for same-basename PDFs.<br>A conflict between two same-label sheets cannot be expressed at all. | P1 |
| N7 | The report calculator accepts malformed numbers and promises more numerical precision than it provides. | P1 |
| N8 | Stable publication does not enforce the documented manual acceptance hold. **This has already happened:** v1.7.0 was published as the stable `latest` release despite the HOLD in `ACCEPTANCE-1.7.0.md` (§1.2). | P1 |
| N9 | Overflow-note navigation does not reach the note. Overflow notes never carry a rect: every index link lands at (36, 36) and every bookmark at (0, 0) on the notes page, while the rows sit lower on it. The "original drawing coordinates" variant happens only through a `Finding.id` collision (a B8 consumer): a TILE cloud sharing an id with an overflowed note sends its index row to the notes page at the cloud's coordinates, and its bookmark is dropped. Viewer effect still needs validation. | P2 |
| N10 | Prose-harvest matching (`_match_entry`, Jaccard ≥ 0.7) never consults critical signatures. "Provide 4 inch drain…" is absorbed into "…6 inch…" (0.857), and the distinct claim gets no ledger entry. | P0 |
| N11 | Synthesis conflict extraction is negation-blind. "No conflicts were found between M-101 and P-101." becomes a paid structuring item and a conflict finding. | P1 |
| N12 | Matching ignores word boundaries. `anchor.py` folds infix hyphens, so `VAV-2` EXACT-matches inside `VAV-2-1` and the wrong equipment is clouded. Cross-QC `_grounded` is a plain substring test at every length, so `AHU-10` grounds inside `AHU-101`. | P0 |
| N13 | Cross-QC grounding (`_norm_for_match`) and `anchor._normalize` disagree on curly quotes, primes, `½`, `×`, `Ø` and infix hyphens. Valid legs are dropped as NOT_MATCHED. | P1 |
| N14 | A cross-QC run with any sheet over the 4,000-character text budget is "degraded": never cached, re-billed on every warm run, and the run's `qc_status` is held at PARTIAL permanently. | P1 |
| N15 | Findings from an errored (refused or truncated) digest are still ingested into the ledger unlabelled, so a partial read inks as ordinary findings. | P1 |
| N16 | A raised-cap truncation retry can lose the first read. Real-time keeps it only when the retry *raises*. Batch `_replace_result_with_attempt_history` replaces the result wholesale. This contradicts CLAUDE.md's "can only improve on that read". | P1 |
| N17 | References to FM-numbered sheets are always treated as non-sheet references (`is_non_sheet_reference("FM-109")` is True). A missing FM sheet is never reported, even in an FM-numbered set. | P1 |
| N18 | Contradictory transcriptions of one quote (`[20,20]=40` and `[20,20,20]=40`) are counted as two checks: one "OK" beside a DETERMINISTIC mismatch. | P1 |
| N19 | W×H duct sizes (`24x12`), compact electrical units (`20A`, `480V`) and ranges/lists (`4-6 in`, `2,4,6 in`) get no signature or only a partial one, so conflicting values merge. | P0 |
| N20 | After a mid-output refusal fallback, the investigation loop echoes **and executes** pre-fallback `tool_use` blocks: they are charged to the budget, answered and replayed. | P1 |
| N21 | Files-API failure fallbacks ignore the Economy policy on both transports. Digest `_serve_inline` and critique `_serve_realtime` (on any upload error) send full-rate real-time requests. The inline request is unguarded: a dense sheet measured 50.8 MB of request JSON. | P1 |
| N22 | Code and help text say uploaded files "expire server-side" and "cost nothing to store". Per the Files API documentation they persist until deleted, against an organization quota, so every detach or crash path leaks them permanently. | P1 |
| N23 | The GUI cost preflight never runs in a default install. It starts only when a user review profile exists, and none ship. So both cost dialogs always use the conservative allowance, and the geometry-aware estimate never applies. | P1 |
| N24 | `render.list_sheets` runs on the UI thread outside `_preflight_lock` while the preflight worker walks pages: concurrent PyMuPDF use. It is latent while N23 holds and becomes the default path once N23 is fixed. | P1 |
| N25 | `DRAWING_ANALYZER_CRITIQUE_RUNS ≥ 3` fabricates corroboration. `critique_3` is in neither `SOURCE_TAGS` nor `ledger._FAMILIES`, so merging a `critique_1` finding with a `critique_3` finding reads as a cross-family REPRODUCED. | P1 |
| N26 | The chat transcript (up to 500k characters) is saved in `localStorage` on the `file://` origin, where any other local HTML file can read it. | P1 |
| N27 | A stream that ends without `message_stop` yields `stop_reason=None` and partial text, with no exception. The digest caches it as complete. | P0 |

Priority meanings: P0 protects result correctness or truthful completion; P1 protects recoverability, evidence, accounting, or release integrity; P2 improves robustness, performance, and interoperability after the relevant correctness contracts are stable.

## 4. Execution organization and shared contracts

### 4.1 Establish these contracts before dependent edits

Create a short implementation decision record covering the following. It should state the selected design, rejected unsafe shortcuts, version changes, and consumers affected. This is not permission for a prolonged redesign exercise; resolve the narrow contracts and proceed.

The record is [`DECISIONS.md`](DECISIONS.md), entries D-1 … D-8. Each contract is decided by the **first slice that needs it**, narrowly, in the same PR:
- D-1 response outcome: WP-01.2
- D-2 stage accounting: WP-01.1
- D-3 finding identity: WP-03.4
- D-4 cache contract: started by WP-01.2, completed by WP-10.4
- D-5 run lifecycle: WP-17.1
- D-6 evidence ownership: WP-13.2
- D-7 usage: WP-14.4
- D-8 source identity: WP-06.2 or WP-11.1, whichever lands first

Later slices conform to a decision or amend it explicitly there.

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

**How this works in practice (added 2026-09-22).** The program runs as a sequence of coding sessions: one session, one slice (occasionally two or three small adjacent ones), one PR. The protocol is in [`README.md`](README.md).
- **There is no standing integration owner.** Each session owns the integration of its own slice. It changes a collision-point file's shared contract only in conformance with `DECISIONS.md`, or by recording an amendment there.
- **In-flight work is visible only as open PRs** (titles start with `Remediation`). A session checks them before picking a slice, so two sessions do not take the same one.
- **A later PR merges the base first** if two open PRs touch the same collision file.

Each agent handoff must include: addressed issue IDs; files changed; selected contracts; cache/schema effects; focused validation and results; unresolved risks; and exact follow-up dependencies. The handoff is written in two places, in the same PR: the handoff log in `PROGRESS.md` and the PR description. Do not let every workstream add its own normalization, completion, or deduplication helper.

The wave table below is the original dependency schedule. **The slice queue in [`PROGRESS.md`](PROGRESS.md) refines it and wins where they differ.** Its dependencies were checked against the code on 2026-09-22. As a result, several independent P0 fixes (B5, B6, N2, N3) moved earlier, and the minimal WP-23 publish gate moved to Wave 0.

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

**Priority:** P0. **Covers:** N4, N5, N15, N16, N27, R2 (moved here from WP-17 step 8), the `_message_text` join (U2); cross-QC/investigation truncation limits.  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/01-outcomes-robustness.md`](verification-2026-09-22/01-outcomes-robustness.md).
- **Status.** N4 and N5 reproduced; N5 end to end through `extract_drawing_context`.
- **Scope added.** This package now also covers:
  - N15, N16 and N27;
  - R2, moved here from WP-17 step 8 because it is a small, independent change;
  - the `_message_text` join (U2).

**Steps 1–2: terminal-state checks**
- Reuse `verify._verdict_from_response` and `_degrade_kind`. They already check `stop_reason` first; verify is not an N4 site.
- These consumers never read `stop_reason`, and they cache:
  - `review_planner.py`, `set_identity.py`, `synthesis.py`, `focus.py`, `prose_harvest.py`;
  - `cross_qc._call`, which checks only for an empty reply.
- Treat `stop_reason=None` as "not finished" (N27). That is what the real SDK returns for a stream that ended without `message_stop`.

**Step 3: digest fix sites and migration**
- Fix sites:
  - `digest.digest_sheet`, which also serves batch `_serve_inline`;
  - `batch_digest._digest_from_message`, which also serves `_rescue_failed_items_sync`.
- The level-1 cache put in `pipeline.py` is covered only if the fix sets `error`.
- Migrate with a read-side reject at the three loaders that force `error=None`: `digest.py` ~1589–1602, `batch_digest.py` ~1724–1736, and `sheet_digest_from_cache_entry`. Digest entries already store `stop_reason`, so this works.
- **Do not bump `digest_cache._SCHEMA_VERSION`.** It feeds all seven key builders, so a bump would discard every paid digest.
- The delivery contract is unchanged; state it in tests. `pipeline._combine` drops errored prose from `combined_text`, and `export._sheet_document` keeps it under a FAILED status.
- N15: `_run_qc_stages` (~1734) ingests findings from errored digests. Label them, or hold them out of the ledger.

**Step 4: critique**
- The single fix site is `critique.outcome_from_message`. Real-time, batch, L1 and L2 all flow through it.
- Do **not** change `FINDINGS_PARSE_OK`. The digest legitimately salvages `PARSED_UNCLOSED` at `end_turn`.
- Critique cache entries carry no `stop_reason`, so add a critique-only contract term.

**Step 5: retries (N16)**
- Add the requirement "a retry never loses the first read".
- Today, real-time falls back to the first read only when the retry *raises* (~1644–1658).
- Batch `_replace_result_with_attempt_history` replaces the result wholesale.

**Steps 6–7: completeness rule**
- This is implementable with the existing counters: verification is COMPLETE ⇔ eligible > 0 ∧ `skipped` = 0 ∧ `not_judged` = 0, over both the single and the cross result (`vres`, `cres`).
- Zero eligible items is `SKIPPED_VALID`.
- Pipeline-level tests belong in `tests/test_drawing_acceptance.py`, beside `test_a_cross_verifier_crash_is_not_a_valid_skip`.

**New step: batch refusals (R2)**
- Retry a refused batch item on the selected transport: a batch resubmit to the registry's fallback target, or to `stop_details.recommended_model` when present.
- Gate the retry on `stop_details.category`.
- Share one retry bound with the truncation retries.
- Log `stop_details`.
- Decide cache admission for a digest served by a host-swapped model. WP-14 covers only server-side fallback.

**Text join (U2)**
- `digest._message_text`, imported by 11 modules, joins blocks with `"\n"`.
- `[text, fallback, text]` therefore yields "12\n inches". A boundary inside the findings JSON makes it MALFORMED.
- One shared helper must handle fallback boundaries. WP-12.1's citation splits use it too.

**Other notes**
- The regression "stream interruption before output / after text / after complete JSON" needs WP-02.3's SSE fixtures.
  - `stream_message` uses `get_final_message()`, so today an interruption raises and the partial read is lost.
  - Capturing it is WP-01.7, together with WP-14 step 7.
- Cross-QC terminal handling is implemented in WP-06.3, on this package's helper.

Slices: WP-01.1 … WP-01.7 in [`PROGRESS.md`](PROGRESS.md).

### WP-02 — Faithful SDK, streaming, batch, and network test boundaries

**Priority:** P0 enabling work. **Covers:** original test-infrastructure gaps (U26).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/08-shell-release-testinfra.md`](verification-2026-09-22/08-shell-release-testinfra.md).
- **Status.** Every §5 test-infrastructure gap in the original review was reproduced or traced.

**Step 1.** The SDK 1.7.0 transport is `httpx2`; plain `httpx` is not installed. `httpx2.MockTransport` works, including for SSE.

**Step 2.** Derive the non-streaming threshold from the SDK, not from a literal. The SDK raises `ValueError` before sending anything; the limit bisects to 21,334 for Opus 5, Sonnet 5 and Opus 4.8.

**Step 3.** Production already tolerates both batch error shapes. The work is making the fakes strict:
- the seven `_FakeBatches.create` copies and `_messages_stream(betas=)` in `tests/test_drawing_batch.py`;
- `_BetaMessagesProxy`, which silently pops `betas`.

**Step 5.** Add a stream that ends without `message_stop`. The real SDK returns `stop_reason=None` with partial text and raises nothing, and the digest caches it (N27, fixed in WP-01.2).

**Step 6: the network guard**
- Guard `connect`, `connect_ex` and `getaddrinfo`, allowing `AF_UNIX` and loopback.
  - Blocking at socket creation breaks asyncio, and therefore Playwright.
  - On Windows, `socketpair` uses loopback.
- Also delete the proxy variables. With `HTTPS_PROXY` pointing at a loopback proxy, traffic escaped through it.
- Delete the credential variables that a zero-arg `Anthropic()` resolves: `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_PROFILE`, `ANTHROPIC_IDENTITY_TOKEN*`, `ANTHROPIC_FEDERATION_RULE_ID`, `ANTHROPIC_ORGANIZATION_ID` and `ANTHROPIC_BASE_URL`. Point `ANTHROPIC_CONFIG_DIR` at a temp dir.
- The browser suite uses `file://` and pipes, not a server. 65 browser tests passed under the probe guard.
- Make `network` an explicit opt-in. Today `conftest` runs the live canary whenever a real key is exported.
- Add `-m "not network"` to `ci.yml` (~99).
- *Correction (WP-02.1, 2026-09-23).* The variable list above is incomplete for SDK 1.7.0. The SDK also reads `ANTHROPIC_CUSTOM_HEADERS`, which can carry an auth header, and `ANTHROPIC_SERVICE_ACCOUNT_ID`, `ANTHROPIC_WORKSPACE_ID` and `ANTHROPIC_SCOPE`. So the guard removes every `ANTHROPIC_*` variable. Three further facts shaped the guard:
  - With `ANTHROPIC_CONFIG_DIR` set, profile selection is *explicit*, so a zero-arg client raises `CredentialsError`: the guard fails closed.
  - Deleting the proxy variables is not enough on Windows or macOS. When no `*_proxy` variable is set, `urllib.request.getproxies` (which `httpx2` calls) falls back to the registry or system configuration. `NO_PROXY=*` closes that.
  - A function-scoped fixture does not cover module-scoped fixtures. The gauntlet's `oracle` runs the whole pipeline in one. The guard spans the run and lifts only inside an opted-in test.

**Step 7.** An agent can write the canaries but can run them only with an owner budget (O-4). Bound the wait, then cancel, harvest and report.

**Acceptance.** `run_acceptance.py` reports SKIP gates yet prints an overall PASS (~186–211). Add a strict release mode (WP-02.5).

Slices: WP-02.1 … WP-02.5.

### WP-03 — Durable finding identity and lossless, symmetric merging

**Priority:** P0. **Covers:** B1, B7, B8, B9, K5; the ledger half of N2.  
**Primary files:** `models.py`, `ledger.py`, `critique.py`, `auditors/__init__.py`, serialization/export consumers.  
**Dependencies:** quantity predicate from WP-04; downstream WP-06/WP-21 depend on identity.

Implementation:

1. Inventory every `Finding.id` consumer: candidate deduplication, cache rebinding, numbering, verification/evidence paths, placements, bookmarks, HTML tools, CSV/JSON, and external comparison scripts.
2. Introduce or adopt a versioned claim identity distinct from a quote/evidence fingerprint and from `QC-###`. Include physical source/page and claim-discriminating content; account for cross-sheet evidence legs. Severity, verdict, arrival index, mutable representative choice, and display numbering must not accidentally determine identity.
3. Preserve producer observations separately when identical claims arrive from several reads. Reproduced confidence requires traceable independent reads/families under the existing policy, not duplicated copies of one observation.
4. Choose a deterministic identity lifecycle consistent with current stage order. Freeze identities before evidence filenames and final markup references are created. If post-merge aliases are necessary, serialize and resolve them explicitly. Never silently change identity beneath existing evidence.
5. Remove the auditor coordinator's destructive quote-ID-only deduplication. Let the shared claim-aware policy adjudicate true duplicates; retain two distinct mismatches on the same row. *(Corrected 2026-09-22: removing the dedup is not sufficient by itself. The ledger's geometry branch then merges the two mismatches, so an arithmetic claim discriminator is also required; see the Verification notes.)*
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/02-ledger-identity.md`](verification-2026-09-22/02-ledger-identity.md); for B7, [`verification-2026-09-22/04-auditors-arithmetic.md`](verification-2026-09-22/04-auditors-arithmetic.md).
- **Status.** B1, B8, B9 and K5 reproduced. B1 was reproduced in all six orders of the 500 gpm / generic / 550 gpm case: three orders end with one entry and no "500".
- **Header.** This package also carries N2's ledger half. WP-06.1 hands cross-QC's duplicates to the ledger instead of destroying them.
- **Dependencies.** Only this package's *acceptance* needs WP-04. The Pass B fix (WP-03.1), the numbering tie-break (WP-03.2) and the auditor discriminator (WP-03.3) do not.

**Step 1: the `Finding.id` consumer inventory** (1.7.0 line numbers):
- **Derive and serialize.**
  - `models.compute_finding_id` (~820) hashes sheet + category + quote-or-text + `source_id`. It includes no page, no text when a quote exists, and no legs.
  - `Finding.__post_init__`, `to_dict`, and `from_dict` (which keeps the stored id).
- **Cache rebinding.**
  - `digest._rebind_cached_finding`, via `findings_from_cache`, recomputes the id. It is used by `digest`, `batch_digest` and `critique.critique_result_from_entry`.
  - **Two restore paths keep the stored id verbatim, with no rebinding:** `cross_qc._cross_qc_from_cache` and `prose_harvest._structure_item`.
- **Merge and dedup.**
  - `ledger._grounding_quality`; `ledger._merge_into` (the id moves with the winning bundle); `critique._representative`.
  - `auditors.run_auditors` (id dedup); `auditors.titleblock.audit_titleblock` (id dedup, first wins).
  - `auditors.references._audit_sheet` (quote dedup, equivalent to the id); `cross_qc._dedup_findings` (an id-equivalent key).
- **Ordering tie-breaks.** `models.assign_qc_ids`; `pipeline._run_critique_stage` (sort before ingest); `investigate._candidates`; `annotate._severity_first_key`; `annotate._annotate_units`; `annotate._set_findings_outline`; `tile_artifacts._finding_sort_key`.
- **Navigation.** Bookmark dedup in `_set_findings_outline`; `mark_page_by_finding`, written in `_annotate_units` and read in `_insert_index_pages`.
- **Placement and manifest.** `annotate._make_placement`; `_units_for_finding` (synthetic leg findings compute their own id); `annotate_pdf`; `write_set_review_notes_pdf`; `MarkupPlacement.finding_id`, which lands in `markup_manifest.json`.
- **Evidence and cache.**
  - `verify._reserve_evidence_dir` (fallback only); `verify._write_evidence_request`; `investigate._write_investigation_json`.
  - `investigate._payload_hash`: the id is part of the `stage=investigation` key.
  - `citation_check.check_citations`, into `CitationAssessment.claim_finding_ids`.
- **Export.** `export._finding_row` and the CSV `id` column; `findings.json` and the per-sheet JSON; `tile_artifacts._finding_summary` and `_finding_note_lines`.
- **A/B harness.** `scripts/ab_findings_diff.finding_record`, its sorts, and a separate `identity_key`.
- **HTML.** None: the report's id is `qc_id`, and deep links key on `qc_id`. Evidence directories are already unique (`qc_id` plus a `-N` suffix).

**Step 2: add a new field.**
- Add a new, versioned `claim_id`; do not redefine `id`. The `id` is pinned by `tests/test_drawing_models.py` and `tests/test_source_identity.py`, it is exported, and it is recomputed on every cache hit.
- Add "same source, different page, same label" to the regressions; it collides today.

**Steps 3 and 6: the critique boundary.**
- `merge_self_consistency` folds a "500 gpm" read into a generic read and marks it REPRODUCED. Pass A then merges that into the digest's "550 gpm" finding.
- A symmetric Pass B cannot see this. Members merged upstream (`critique._cluster` / `_representative`, `cross_qc._dedup_findings`) never reach `Ledger._members`.
- Step 6 must therefore make the upstream merges hand their observations to the ledger.

**Steps 3 and 8: cold and warm runs.** `critique_cache_entry_from_result` stores only post-merge findings. Serialize the observations into the critique cache entry under a critique-scoped version, or warm and cold runs will diverge.

**Step 5 (B7): the coordinator dedup is not the only problem.**
- `audit_arithmetic` anchors its own findings. `_is_duplicate`'s geometry branch (IoU > 0.5 plus an equal quote, no text check) then merges two same-row mismatches in both arrival orders. Unitless numbers give an empty signature, so nothing blocks the merge.
- Add a claim discriminator: kind + Decimal-canonical terms + expected value.
  - It must block the merge in both Pass A and Pass B.
  - Fold it into the arithmetic finding's id.
  - Scope it to `auditor_arithmetic` findings, because the same predicate drives the cached self-consistency merges.
- Also key `critique._dedup_claims` and `arithmetic._claim_dedup_key` on parsed Decimals; `20` and `"20.0"` count twice today.
- Regression path: `run_auditors` → `Ledger.add` → `reconcile_post_anchor` → `number()`, in both orders.

**Step 6: snapshots and compatibility.**
- Member snapshots are taken before anchoring, so `_is_duplicate`'s geometry branch never fires against them, and the symmetric patch widens that recall loss.
- Choose one of: propagate the resolved anchor to same-quote snapshots; anchor each observation; or record the loss.
- Define "compatible" as Pass A's all-pairs `_is_duplicate`, not signature compatibility alone.

**Step 7: specificity.**
- Coherent bundles, and the rule against borrowing the loser's verdict, already exist with tests.
- What is missing is specificity: a generic member with a longer quote wins and erases the measurement from the exported text.
- The regression "both measurements survive" must say where they survive (text or serialized observations). Step 6 alone cannot make it pass.

**Migration.**
- Name the two no-rebind restore paths.
- Changing the identity inside `investigate._payload_hash` re-keys every `stage=investigation` entry, which means paid re-runs. Record it in the migration register.

**Navigation.** Keying bookmarks and index destinations by `placement_id` needs no identity work; it is done in WP-21.3.

Slices: WP-03.1 … WP-03.6.

### WP-04 — Engineering quantity and tag comparison

**Priority:** P0. **Covers:** B2, B3, B12, N1, N19.  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/02-ledger-identity.md`](verification-2026-09-22/02-ledger-identity.md).
- **Status.** B2, B3, B12 and N1 reproduced. The package also covers N19.
- **Anchors.** In `critique.py`:
  - `_MEAS_RE` (~628; allows only `\s*` between a number and an alpha unit);
  - `_ALPHA_UNIT` (~595), `_SYM_UNIT`, `_UNIT_SYNONYM`, `_meas_value` (~681);
  - `signatures_compatible` (~777; the disjoint-set tests are at ~790 and ~793).

**Step 2: keep malformed tokens.** "Reject malformed groupings as whole tokens" must keep an **opaque raw quantity**. An absent signal never blocks a merge, so dropping the token makes merging *more* permissive.

**Step 3: degrees.**
- Bare `deg` and `°` are also angles (a 45° elbow).
- Map `deg` to `°`, and `deg F` / `degrees F` to `°F`. Never infer a temperature scale.
- Today `90 deg F` and `90 deg C` both sign as `90deg` and are compatible, so an F/C conflict is hidden.

**Step 4: the compatibility rule.**
- Quantity roles are not extracted anywhere.
- The minimum rule is to compare value sets **per unit**. That blocks both the psi/diameter case and `12'-6"` vs `12'-8"`, which currently merges because both share `12ft`.
- A survivor's `_sig_text` accumulates supporting quotes, so its value sets grow. State how that is handled.

**Step 6: one copy of the rule.**
- A restated copy of the disjoint rule exists in `scripts/ab_findings_diff.py::_signature_conflicts`. After the fix it would disagree.
- Replace it with the shared helper in `critique`, and bump the script's `RECORD_CONTRACT_VERSION`. Tests: `test_ab_findings_diff.py`, `test_ab_sweep.py`.

**Cache (missing from the plan).**
- The critique cache stores post-merge findings, so any rule change must invalidate it.
- Do that with a **critique-scoped term in both `critique_cache_key` and `critique_cache_key_level1`**.
- Never bump the global `digest_cache._SCHEMA_VERSION`. The v10 precedent re-billed every digest and conflicts with §2 rule 6.

**Matrix additions.**
- W×H duct sizes: `24x12` vs `24x10`. (`24"x12"` is blocked today only because `x12` parses as a tag.)
- Compact electrical units: `20A`/`30A` and `480V`/`208V`, with a negative corpus (room `101A`, grid `2A`).
- Ranges and lists: `4-6 in`; `2,4,6 in` (keeps only `6in` today).
- Also `1,500.5` and `1,2,500`.

**CLAUDE.md.** Its statement that keeping both halves of `12'-6"` prevents the `12'-6"`/`12'-8"` merge is false (N1). Correct it in WP-04.2.

Slices: WP-04.1, WP-04.2.

### WP-05 — Robust anchoring and consistent quote evidence

**Priority:** P0/P1. **Covers:** B4, B5, N12, N13. (The whole-set grounding gap, U8, is implemented in WP-06; B6 has no grounding part.)  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/03-anchor-crossqc.md`](verification-2026-09-22/03-anchor-crossqc.md).
- **Status.** B4 reproduced (all seven pairs end UNANCHORED) and B5 reproduced. The package also covers N12 and N13.

**Step 1: one normalizer, not two.**
- `anchor._normalize` and `cross_qc._norm_for_match` disagree. The latter is `fold_text` only: it does not fold curly quotes, primes, `½`, `×`, `Ø` or infix hyphens.
- So `PROVIDE 6” DRAIN`, `2½"`↔`2-1/2"`, `Ø6` and `300×200` are NOT_MATCHED in cross-QC, and the leg is dropped (N13).
- `cross_qc.fact_tile_lookup` also joins on `_norm_for_match`.
- Use one policy for both.

**Step 2: the numeric veto.**
- The existing veto compares exact whitespace tokens. After a character-stream match it would reject three of the seven required positives: `6"` vs `6`+`"`, `2%` vs `2`+`%`, and `12'-6"` vs `12'`,`-`,`6"`.
- It must compare canonical number+unit quantities (from WP-04), not raw tokens.
- Do **not** lower `_FUZZY_WINDOW_MIN_OVERLAP`. The 0.85 value is asserted in `tests/test_drawing_anchor.py` and is a standing prohibition in CLAUDE.md.

**Step 3: word boundaries at every length.**
- This is not only about short quotes. Cross-QC `_grounded` is a substring test with no word boundaries at any length: `AHU-10` grounds in `AHU-101`.
- `anchor.py`'s infix-hyphen folding lets `VAV-2` EXACT-match inside `VAV-2-1`, and `AHU-1` inside `AHU-1-2` (N12).
- Require matched spans to start and end on source-word boundaries; `_Stream.word_of` makes this possible.

**Negatives.** Add a leading decimal: `.5` must not become `5`.

**Cache.**
- B5 changes the stored `evidence_state`, and which legs are admitted, for byte-identical inputs. Bump `_CROSS_QC_CACHE_CONTRACT` from 3 to 4 (the P8 item 11 precedent).
- Three tripwire tests assert `== 3`. Update them with the recorded reason:
  - `test_drawing_cross_qc.py::test_cross_qc_contract_bumped_for_the_norm_id_fold`
  - `test_evidence_visual.py::test_contract_counter_is_not_bumped_by_this_package`
  - `test_evidence_tail.py::test_no_cross_qc_contract_bump_was_needed`

**`verify.py` needs no edit.** TILE anchors already pass `_is_verifiable` and `_has_anchored_legs`. Extend `test_evidence_visual.py::test_a_recovered_finding_reaches_verification_and_investigation` to the short-tag case instead.

**Standing prohibition (§2 rule 15).** The character-stream tier (step 2, WP-05.3) must not become a "manufactured joined string".
- It may match only a **contiguous run of source words in reading order, on one sheet**.
- It is recorded as its own anchor method, not as EXACT.
- It must pass the quantity-aware veto.
- A match assembled from non-adjacent fragments is never text-grounded.

Slices: WP-05.1 (cross-QC), WP-05.2 (anchor folding and boundaries), WP-05.3 (character-stream tier; needs WP-04.1).

### WP-06 — Source-safe cross-QC and claim-preserving deduplication

**Priority:** P0/P1. **Covers:** B6, B10, N2, N6, N14, K2; whole-set grounding (U8) and truncation gaps (U6, U7).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/03-anchor-crossqc.md`](verification-2026-09-22/03-anchor-crossqc.md).
- **Status.** B6, B10, N2, N6 and K2 reproduced, as were the review's §4 cross-QC items.

**Step 1 / N6: every label-keyed binding site.** Besides the first-wins `sheet_map` in `cross_sheet_qc` (~1537–1550):
1. `_dedup_findings` keys on labels on both paths (reproduced on the sharded path).
2. Whole-set claims carry no source (asserted by `test_cross_qc_returns_numeric_claims`), and `auditors.arithmetic._build_maps` is first-wins by id. Rebind them through `_resolve_claim_handles`, and make an ambiguous id lookup refuse rather than pick the first.
3. `critique._leg_targets`, which drives ledger merges, is label-based.
4. `_fallback_id` (`stem-pN`) collides for same-basename PDFs.
5. A conflict between two same-label sheets cannot be expressed at all.

Keep the human id visible beside each handle (`S001 = M-101`, as the reconcile manifest does). Cross-reference conflicts ("see M-501") need it.

**Step 4 cannot fix B10 as written.**
- `Ledger.add` buckets entries by primary `source_page_key`, and `_is_duplicate` requires the same primary sheet and equal `leg_targets`. So A→B and B→A are never compared.
- B10 needs either a predicate that treats the leg set symmetrically, or a symmetric merge inside cross-QC that unions legs and quotes.
- For N2 alone, handing duplicates to the ledger instead of the destructive dedup is enough.
- The acceptance line "reversed duplicates produce one finding" needs a stated same-claim predicate. The shard and the reconciler phrase the same conflict differently.

**Step 5: invisible loss.**
- Today the loss is invisible: the stage reads COMPLETE, there is only an INFO log line, and the result is cached.
- `_finding_from_handles` rejects invalid fields without any counter. Add an invalid-field counter to `CrossQCDiscardCounts` on both paths.
- One prompt edit fixes both the whole-set and the map prompts, and the prompt hash invalidates the cache.

**Step 6 reverses a recorded decision.**
- WP-03A scoped the whole-set path out of grounding (`test_evidence_tail.py::test_forty_entries_take_the_whole_set_path_unchanged`).
- Ground through `classify_quote_evidence` against `sheet_evidence_text` (the uncapped text), never the 4k prompt text.
- `discards` becomes non-None on the whole-set path. Update the comments in `pipeline.py` (~603, ~3681), in `cross_qc.py` (~1605), and in CLAUDE.md.
- Paraphrased quotes will lose recall; measure it with the §7.2 counters.
- This is required by a standing prohibition (§2 rule 15): a capped-text grounding check on this path would import the truncation defect into the common case.

**Step 7: truncation.**
- `cross_qc._call` is the one text stage still on plain `create`: a 16k cap with adaptive thinking, and `stop_reason` read only when the text is empty. It is missing from CLAUDE.md's streaming list.
- Any cap raise above ~21k must move it to `digest.stream_message` in the same change.
- A `max_tokens` reply with a closed object but no closing fence is `complete=True` and cached today.
- "Preserve partial findings" needs a new bounded salvage parser, because `_tolerant_json_object` is all-or-nothing.

**Step 8: facts and N14.**
- Text omission is already counted (`text_chars_omitted`, a stage warning). What is invisible is `_parse_facts` silently dropping facts past 40. Add that counter.
- N14 (degraded results are never cached, so they are re-billed and PARTIAL forever) needs a decision recorded in WP-06.3. Either cache the degraded result together with its PARTIAL status (the `[TRUNCATED N chars]` marker then becomes load-bearing in the key), or leave it to WP-25.4.

**Migration.** Every change to host-side binding needs a `_CROSS_QC_CACHE_CONTRACT` bump. Cached entries store already-bound findings with no raw reply, so step 2's "legacy response" handling cannot apply to them.

**Unnamed consumers.**
- `tests/fixtures/gauntlet.py` `CROSS_CONFLICT`: whole-set `sheet_id` items that underpin `run_acceptance.py`.
- `tests/test_drawing_acceptance.py`, and the whole-set fixtures in `tests/test_drawing_cross_qc.py`.
- `tests/test_source_identity.py` is the natural home for N6 tests.

**Dependencies and testing.** B6 and N2 need neither WP-01 nor WP-03. "Whole-set/sharded equivalence" is testable only at parser level: the same item gives the same binding, evidence state and counters.

Slices: WP-06.1 … WP-06.4.

### WP-07 — Arithmetic operand trust and strict numeric parsing

**Priority:** P0. **Covers:** A8, N3, N18; coordinates with B7.  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/04-auditors-arithmetic.md`](verification-2026-09-22/04-auditors-arithmetic.md).
- **Status.** N3 and A8 reproduced. N3 is broader than stated (§3). The package also covers N18.

**Step 2.** A multiset-only fix closes the duplicated-operand case, but role swap, sum/product confusion and A8 stay DETERMINISTIC. Steps 2, 4 and 5 are all required.

**Step 3: decide provenance after anchoring.**
- Today provenance is decided in `audit_arithmetic` (~479–483) **before anchoring**. It never looks at the anchor, or at whether the sheet resolved.
- Decide it after anchoring. Require a resolved sheet plus an EXACT (or numeric-vetoed FUZZY) quote anchor.
- Re-baseline these pinned tests; do not delete them:
  - `tests/test_drawing_auditors.py::test_a_comma_separated_operand_list_stays_text_extracted`, `::test_arithmetic_text_extracted_operands_stay_deterministic` and `::test_arithmetic_mixed_fraction_operand_is_text_extracted`. They call `audit_arithmetic(..., [])` and assert DETERMINISTIC; give them sheet words.
  - `::test_arithmetic_unresolved_sheet_still_records_finding_unanchored` keeps its finding, which becomes UNCERTAIN.
- `tests/test_drawing_acceptance.py::test_gauntlet_deterministic_auditors_fired` must stay DETERMINISTIC; its quote is on the sheet.

**Step 4: keep relationship checks host-side.** Adding role or operator fields to the claims contract (`critique._CRITIQUE_FINDINGS_INSTRUCTION`, which is hashed into `CRITIQUE_PROMPT_VERSION`, and its cross-QC twin) would re-key every critique and cross-QC cache entry.

**Step 5: hyphens.**
- `_NUM_IN_TEXT_RE`'s `[-+]?` reads a hyphen after a letter as a minus sign: `M-101 P-3 AHU-2` gives `[-101, -3, -2]`.
- Keep the scanner/parser agreement test.
- Trailing letters are units (`20A`, `150GPM`) and must still parse.

**Step 7: counters.**
- The matched path never checks provenance, so ungrounded operands still count as "checked out OK".
- Counter consumers: `annotate._insert_appendix_page`, `html_report._audit_checks_line`, `gui.py` (~2197), `run_journal.py` (~821).
- Contradictory transcriptions of one quote must be flagged or downgraded (N18).
- Claim dedup keys move to Decimals (with WP-03.3).

Slices: WP-07.1 … WP-07.3.

### WP-08 — Reference, naming, sheet-ID, and drawing-index auditors

**Priority:** P1. **Covers:** A1–A7, N17.  
**Primary files:** `auditors/references.py`, `auditors/sheet_ids.py`, `auditors/naming.py`, `auditors/sheet_index.py`, title-block consumers.

Implementation:

1. Require lexical or layout evidence before treating three two-digit values as a specification reference. A plausible MasterFormat division by itself is insufficient.
2. Make tags of different arrangement never cluster: add letter/digit kind order to the naming cluster key, so the check holds even when a frequency winner exists. Popularity must not convert breaker `3P` into the preferred spelling of pump `P-3`. *(Corrected 2026-09-22: do not demote an established frequency winner on structural doubt alone. CLAUDE.md and two pinned tests require the winner to outrank structural doubt; see the Verification notes.)*
3. Extend bounded reference parsing for DWG/DWG., REF., SHEET NO., detail-on-sheet phrasing, and multi-target lists. Keep a negative corpus so additional recall does not classify arbitrary prose as missing sheets.
4. Rank own-sheet IDs using nearby SHEET/DRAWING labels and negative PROJECT/JOB/SIZE context. Retain the existing positional signal as one input, not an absolute decision. Surface genuine ambiguity instead of confidently selecting a distractor.
5. Correct contextual handling of FM sheet IDs. Preserve the working FM-only fallback while preventing unrelated tokens from displacing a well-supported FM title-block label.
6. Recognize a real drawing-index heading/table region and harvest entries from that region. A sentence referring the reader to another index must not establish an authoritative index here.
7. Distinguish incomplete/partial-set context before producing hundreds of findings. *(Corrected 2026-09-22: the partial-package flood is the "listed in the index but not present in the set" direction, at medium severity. The present-but-not-listed direction is A7, handled by step 6.)* Any output cap must disclose counts and retained detail; it must not silently erase auditor results.
8. Normalize the inventory once, scope memoization to that inventory/grammar, cache repeated target resolution, and perform nearest-match work only when needed. Never reuse a cached answer across an inventory change.

Regression matrix: the two numeric-row false positives and genuine CSI references; P-3/3P with either frequency winner; every reported reference phrase/list; title block with project ID, paper size, revision strip, and nearby labels; FM-only/FM-with-distractor; real index versus prose mention; partial packages; changed inventory and cached resolution.

**Acceptance:** demonstrated false positives disappear without losing the positive fixtures; ambiguous IDs are observable; operation counts show expensive repeated normalization/nearest searches have been removed. Record elapsed-time comparisons on the same representative fixture rather than promising the old report's benchmark numbers.

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/04-auditors-arithmetic.md`](verification-2026-09-22/04-auditors-arithmetic.md).
- **Status.** A1–A7 reproduced, and A3 measured. A6's stated consequence was inaccurate; the real FM defect is N17.

**Step 1 vs acceptance: the CSI fixtures move.**
- The existing positive CSI fixtures are bare number triples with no cue word: `tests/test_drawing_reference_audit.py::_fp_set`, and the `23 21 13` / `26 05 00` test.
- Word spacing cannot separate them from `20 20 20`. A "real MasterFormat division" rule would not stop `CFM 10 15 25` either, because Division 10 exists.
- So these fixtures move to cue-bearing forms (SECTION, SPEC, DIV, § or a following title), and a bare triple is no longer reported.

**Step 2 (corrected above).**
- Read literally, it fails `test_drawing_auditors.py::test_an_established_convention_outranks_structural_doubt` and `::test_naming_still_flags_pure_format_drift_same_digits`. It also contradicts CLAUDE.md ("an established winner still outranks structural doubt").
- Instead, add kind order (letters-first vs digits-first, separators ignored) to `naming._cluster_key`.
- Simulated: all 9 naming tests pass, and `3P`/`P-3`, `1A`/`A1` and `2P`/`P-2` stop clustering.

**Step 3: one quote per target.**
- `_audit_sheet` dedups on the verbatim quote (equivalent to `Finding.id`). A list rule that emits targets 2..n with the same quote would silently drop them, so each target needs its own quote span and rect.
- `test_audit_various_trigger_phrases` pins the exact quotes `SEE SHEET M-999`, `ON DRAWING M-998` and `SEE M-997 FOR`. New rules must not widen them.
- The dead `sug = _suggestion(...)` (`references.py` ~550, ruff F841) goes in the same slice.

**Step 4: own-ID ranking.**
- Reuse titleblock's label helpers (`_FIELD_LABELS`, `_group_lines`, `_extract_labeled_fields`) by moving them into `sheet_ids.py`. Titleblock imports references, so importing back would create a cycle.
- `titleblock._sheet_band` derives its band from the chosen id word, so a ranking change also moves that auditor's band.
- Surface ambiguity without changing `detect_sheet_id`'s `str | None` return; it has 14 call sites.
- Never drop an ambiguous sheet from `build_inventory`.
- Name the observable: an `audit_stats` key (`run_journal` prints every key).

**Step 5 / N17: FM references.**
- References to FM sheets are always treated as non-sheet (`is_non_sheet_reference("FM-109")` is True), so a missing FM sheet is never reported.
- Add set-aware handling in `classify_reference`, not in `is_non_sheet_reference`, which is documented as never consulting the set.

**Step 7 (corrected above).** The partial-package flood is **direction 1**, at medium severity. An index listing 50 ids with 5 sheets submitted gave 45 "The drawing index lists M-1xx, which is not present in the provided set" findings. Direction 2 ("present but not listed") is A7's case, which step 6 fixes.

**Step 8: where the memo lives, and the targets.**
- `sheet_index.py` (~182) calls `classify_reference` directly, bypassing `references._resolve`. So the memo belongs on `SheetInventory`, where both paths use it.
- Targets, on a seeded fixture of 200 sheets × 2,000 words × 40 refs:

  | Measure | Today | Target |
  |---|---|---|
  | `normalize_sheet_id` calls during classification | 4.03M | ≤ N + distinct targets |
  | Levenshtein calls | 399,200 | ≤ distinct unresolved targets × N |
  | Warm `audit_references` time | ~6 s | ≤ ~1.2 s, and ≤ ~2.2× when sheets double |

- A simulated fix gave identical findings at 0.49 s / 0.97 s for 100 / 200 sheets.
- Cold sheet-id detection (~50% of the cost, linear) is out of scope.

Slices: WP-08.1 … WP-08.5.

### WP-09 — Prose harvesting without empty findings or unnecessary duplication

**Priority:** P1 (N10 is P0). **Covers:** B11, N10, N11; prose-match threshold concern (U11).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/05-citation-planner-prose-investigation.md`](verification-2026-09-22/05-citation-planner-prose-investigation.md).
- **Status.** B11 reproduced: all four boilerplate strings pass the filter, and with no client they become medium SHEET entries. "No isolation valve is shown" survives.
- **Scope added.** N10 and N11.

**Steps 1–3: one filter site.**
- `prose_harvest._split_items` already filters before both the model call and the degraded entry, so only one filter site (`_TRIVIAL_RE`) changes. A regex with a repeatable qualifier passed a 7-boilerplate / 7-real test corpus.
- The synthesis channel is negation-blind (N11): `extract_synthesis_conflicts` and `extract_set_level_synthesis_conflicts` substring-match `_CONFLICT_SIGNALS`.

**Step 5 (N10): the threshold already suppresses distinct issues.**
- `_match_entry` never checks critical signatures.
  - "4 inch" is absorbed into "6 inch" (Jaccard 0.857).
  - "165 psi" is absorbed into "150 psi", because a shared "175 psi" masks the difference (that is N1).
- `_match_entry` must reject candidates that fail `critique.signatures_compatible(critical_signature(…))`, reusing the shared rule.
- Depends on WP-04.2.

**Step 6** is implemented with WP-01.6.

Slices: WP-09.1, WP-09.2.

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

**Verification notes (2026-09-22).** Evidence: [`01-outcomes-robustness.md`](verification-2026-09-22/01-outcomes-robustness.md) (K1, K3, N4 cache), [`03-anchor-crossqc.md`](verification-2026-09-22/03-anchor-crossqc.md) (K2), [`05-citation-planner-prose-investigation.md`](verification-2026-09-22/05-citation-planner-prose-investigation.md) (K4).
- **Status.** K1–K4 reproduced.

**Step 2, K1: tile and display labels.**
- Rewording the tile label changes the request while every key stays the same. The comment at `digest.py` (~332–334) wrongly says it is covered.
- Hash a label-format constant through `digest.SHARED_USER_FRAMING_STRINGS`. The prompt version is in all four digest and critique keys.
- Fold it in only when it is non-default (the `structured_key` precedent), so nothing is invalidated.
- Also decide about `{label}` = `SheetRef.display_label`, which is the **source filename**. It is model-visible and in no key.

**Step 2, K2: cross-QC framing.**
- A pre-call fingerprint of the effective request cannot cover reconcile requests, because they depend on the map outputs.
- Hash the framing constants instead, the way `SHARED_USER_FRAMING_STRINGS` does: `_CROSS_QC_TASK`, the whole-set/map/reconcile framing, and the truncation marker.
- The `[TRUNCATED N chars]` marker never reaches a cached entry today, because degraded results are never admitted. Test only that it is in the key.
- Implemented in WP-06.2.

**Steps 4–5, K3: critique contract per transport.**
- Name `pipeline._critique_level1_partition` and `_ingest_miss`.
- Resolve the contract per transport (batch ⇒ fenced) for both the probe and the store, and carry it on `CritiqueResult`.
- Log that the environment flag is ignored on batch.
- Retire only structured-keyed critique entries. The flag is opt-in, so no global bump is needed.

**Step 6, K4: planner loss metadata.**
- Entries without loss metadata must stay servable, with loss reported as unknown.
- Invalidating `stage=review_plan` entries would make the model re-author the plans. That changes `profiles_key`, so the critique cache misses at both levels on every sheet.
- The review's root-cause fix (stating the 60-item total in `PLANNER_SYSTEM_PROMPT`) re-keys `PLANNER_PROMPT_VERSION` and triggers the same cascade. Bundle it with another planner re-key, and record it.
- `sanitize_plans` returns one int, so per-reason loss counts need a signature change.
- Whether cap trimming counts as PARTIAL is a D-2 decision.

**Step 7: never the global schema version.**
- `digest_cache._SCHEMA_VERSION` feeds all seven key builders: digest L1/L2, critique L1/L2, identity, review plan and citation. A bump discards every paid digest.
- Use read-side rejects where the stored data allows it: digest entries already store `stop_reason`.
- Use narrow contract terms where it does not: critique entries carry no `stop_reason` and no contract.

**N14.** Record the decision on caching degraded cross-QC results (WP-06.3).

Slices: WP-10.1 (K1), WP-10.2 (K3), WP-10.3 (K4), WP-10.4 (cache map, admission predicates, migration register). K2 is in WP-06.2.

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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/01-outcomes-robustness.md`](verification-2026-09-22/01-outcomes-robustness.md).
- **Status.** R1 reproduced on the real-time, cached/prescan and batch paths. The batch path propagated the error while holding 5 uploads, none of them deleted.

**Step 2: no page may vanish.**
- The prescan has no error callback. A page it skips drops out of `miss_only`, and therefore out of `iter_rendered_sheets(only=)`, so it silently vanishes.
- Route such a page to render, or give it a terminal per-page failure.
- Take the denominator from `inventory.accepted_documents[].page_count`, because `list_sheets` reopens files and skips failures.
- Model the fix on `render.iter_region_crops`, which is already guarded.

**Step 4: what containment must do.**
1. Return the already-paid results of `_digest_sheets_concurrent`.
2. Add the DA-034 outer cleanup guard that `submit_drawing_batch` lacks; `submit_critique_batch` already has one.
3. Close `RenderedSheetSpool` and release the retained reusable uploads.

The help text's "released on every exit path" is false today.

Slices: WP-11.1 … WP-11.3.

### WP-12 — Citation parsing, full-text editions, and honest adoption evidence

**Priority:** P1. **Covers:** C1, C2, C5, C6, H4; edition-vocabulary/adoption inconsistency.  
**Primary files:** `citation_check.py`, `set_identity.py`, `models.py`, planner/cross-QC context renderers.  
**Dependencies:** WP-01/WP-10; usage pricing belongs to WP-14.

Implementation:

1. Assemble citation-bearing text blocks according to their contiguous text semantics. Do not inject newlines into JSON string content. Keep response text assembly separate from human presentation formatting; do not globally rewrite successful digest prose to fix citation parsing.
2. Collect source provenance across every response/continuation, including search and fetch results. Associate sources with claim assessments when information is available, rather than presenting an undifferentiated list as proof for every claim.
3. Use the full host evidence text for edition harvesting and corroboration. The model's budgeted prompt slice is not the authoritative limit for host-side evidence checks.
4. Expand edition parsing with bounded explicit fixtures for em/en dashes, year-first forms, ASHRAE, IECC, NEC, Title 24, ASCE shorthand, and jurisdiction-specific code titles. Preserve distinctions between a family name, section number, and edition year; ambiguous shorthand remains ambiguous rather than guessed.
5. Separate observed code references from declared adopted codes in the model and in every rendered context. Retain origin, quotation, source/page, and corroboration state. A regex match alone proves a mention, not adoption. *(Clarified 2026-09-22: adoption statements that pass the citation-shape filter and are re-found in sheet text, i.e. the Phase B `_basis_edition_claims` basis, remain valid adoption evidence. Only the loose, citation-shaped harvest is relabelled as a mention; see the Verification notes.)*
6. Rank code-selection windows using contextual evidence. The all-caps phrases containing `IS 1000` or `AS 2019` must not displace a later explicit declaration. Keep legitimate international code designations; do not solve the problem with an indiscriminate US-only whitelist.
7. Ensure planner, cross-QC, citation checking, and report identity use the same distinction. Update model-visible framing/cache versions accordingly.
8. Apply terminal and coverage validation before caching assessments. Preserve partial checked claims and explicitly mark missing verdicts.

Regression matrix: JSON split inside a cited string; citation/fetch-only output; multiple `pause_turn` responses; adoption after 15,000 characters; mentioned old edition beside an explicit adopted edition; punctuation variants; international standards; uppercase ordinary notes; conflicting declarations; no adoption declaration; warm/cold equivalence.

**Acceptance:** split citation text parses without invented whitespace; source trails contain all observed relevant evidence; late text is checked; incidental/historic citations are not promoted to adopted requirements.

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/05-citation-planner-prose-investigation.md`](verification-2026-09-22/05-citation-planner-prose-investigation.md).
- **Status.** C1, C2, C5, C6 and H4 reproduced. The regex-shown-as-adopted and `_CODE_TOKEN` gaps also reproduced.

**Step 1.** Keep the fix local to citation parsing (`citation_check._check_one` → `digest._message_text`). Joining with `""` does not break fence detection on that path. The general, fallback-aware join is WP-01.6.

**Step 3: identity sites.**
- Also name these sites:
  - `set_identity._sheet_block`, whose windows are built from the capped text;
  - the hints in `build_identity_user_text`;
  - the union in `identify_set`;
  - the cited-side span in `reconcile_cited_editions`.
- `identity_cache_key` has no host-contract term, yet it stores the regex-unioned record. Host-only harvest or union changes therefore need such a term, or warm runs replay the stale union (I-7).

**Step 4: an alias table.**
- Add a code-family alias table shared by `_EDITION_RE`, `_basis_edition_claims` and `_family_year_re` (CBC ≡ CALIFORNIA BUILDING CODE, T24 ≡ TITLE 24). Without it, `2022 CALIFORNIA BUILDING CODE` never matches `CBC 2019 §1004`.
- Every grammar change is model-visible (the identity windows and hints, and the editions line inside `_citation_payload_hash`). It re-keys the identity, planner and citation caches for the affected sets.

**Step 5 (clarified above).**
- Read literally, "a regex match proves only a mention" would break two things: the Phase B two-tier trust contract in CLAUDE.md, and the zero-API auditor battery, which runs without an identity.
- The citation-shape-filtered adoption statements from `_basis_edition_claims` are legitimately text-grounded and stay as basis.
- Only the loose, citation-shaped harvest (split with `_SECTION_AFTER_RE`) is labelled "mentioned", in the union, the context block and the editions line.

**Step 7: missed consumers and the cascade.**
- Step 7 misses two consumers:
  - `pipeline._combine(identity=…)`: the identity section of `combined_text`, which is exported and saved by the GUI;
  - `CitationAssessment.adopted_edition`: filled from `merged_editions`, and shown as "adopted" in the HTML report and the findings CSV.
- Any new field in `SetIdentity` / `AdoptedCode.to_dict()` changes `review_planner._identity_hash`. That re-keys the planner and cascades into the critique, even for cached identities.
- Either fold new fields into the hash only when non-default (the `profiles_key` precedent), or budget for one full critique re-read.

Slices: WP-12.1 … WP-12.6.

### WP-13 — Investigation budgets, replay, and evidence finalization

**Priority:** P1. **Covers:** R7, C4, N20; truncation, fallback replay, sheet-ID normalization, broad task-budget latch (U3, U12).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/05-citation-planner-prose-investigation.md`](verification-2026-09-22/05-citation-planner-prose-investigation.md).
- **Status.** R7, C4, the task-budget marker and `_norm_id` reproduced. Truncation and the fallback echo were traced.
- **Scope added.** N20.

**Steps 1, 3, 7 and 8: the prompt version and key.**
- `INVESTIGATE_PROMPT_VERSION = "investigate-v3"` is a manual literal, pinned by `test_the_budget_change_bumped_the_investigation_prompt_version`.
- The tool descriptions, the initial-content text and the budget strings are not hashed. `investigation_cache_key` uses only schema, model, prompt version, max rounds, task budget and payload.
- Bump the literal (or convert it to a content hash), and add the new search budget to the key.

**Step 3: ambiguous ids.** `_sheet_id_map` binds duplicate detected sheet ids first-wins (`setdefault`). Refuse ambiguous targets instead.

**Step 4: the latch markers.** Narrow `_TASK_BUDGET_REJECTION_MARKERS` to `task_budget`. The existing test's error message contains `task_budget`, so it stays green.

**Steps 5–6: recording `find_text`.**
- Recording `find_text` (or any other non-render step) in `tool_trace` requires two changes:
  - `_replay_cached` must skip such steps, because it demands a sha on every step;
  - the investigation cache contract must be bumped.
- The initial-crop failure path saves nothing, so it only needs the failed attempt recorded.
- The export already copies the whole `evidence/` tree, so crops from an API-failure path ship unreferenced rather than being lost.

**Step 8 (N20).** Filter pre-fallback blocks **before** building the tool requests. A declined model's `tool_use` must not be executed, charged, answered or echoed. Text before the boundary stays.

**Acceptance.** "Out-of-budget tools are refused before execution" already holds (`test_a_parallel_turn_past_the_budget_is_refused_not_rendered`, `test_a_refused_request_renders_no_evidence`). Preserve it; do not re-implement it.

Slices: WP-13.1 … WP-13.4.

### WP-14 — Attempt-level provenance, usage, and pricing

**Priority:** P1. **Covers:** R3, C3; fallback provenance/billing; server iteration and nullable telemetry gaps (U1).  
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

**Verification notes (2026-09-22).** Evidence: [`06-cost-usage-config.md`](verification-2026-09-22/06-cost-usage-config.md), [`01-outcomes-robustness.md`](verification-2026-09-22/01-outcomes-robustness.md) (R3), [`05-citation-planner-prose-investigation.md`](verification-2026-09-22/05-citation-planner-prose-investigation.md) (C3).
- **Status.** C3 and R3 confirmed. Nothing reads `response.model`, `usage.iterations`, `stop_details`, `fallback_credit`, `cache_creation` or `output_tokens_details`. `web_fetch_requests` is never counted anywhere.

**Primary files are incomplete.**
- Per-attempt detail is lost inside the stage result types, before the pipeline ever sees it:
  - verify writes one record per stage;
  - cross-QC writes one record for all shards;
  - citation writes one record per stage, and `check_citations` mixes exact search counts with a 1-per-request lower bound;
  - critique sums the N reads per sheet;
  - prose harvest also sums.
- Steps 3–4 therefore need per-attempt usage lists from `verify.py`, `cross_qc.py`, `citation_check.py`, `critique.py` and `prose_harvest.py`, and also from identity, planner, synthesis and focus.

**Step 1: reading the metadata.**
- The SDK 1.7.0 stream accumulator already copies `stop_details`, `iterations`, `fallback_credit` and `output_tokens_details` into `get_final_message()`.
- The GA `Usage` type has no `iterations`; only beta-namespace calls carry it.
- Add one reader beside `digest._message_usage`, which has 13 callers.
- Store the serving model in cache payloads as an additive field, where absent means unknown. Do **not** bump `_SCHEMA_VERSION` for it; record that decision.

**Step 3 / R3.**
- Fix it in `batch_digest._parse_item`: emit a non-billable attempt for every non-succeeded envelope.
- Count `responded` only for `succeeded`.
- The attempt is also lost on the terminal path: when an errored primary is followed by a successful resubmission, attempt 1 is absent.

**Step 4: unknown usage.**
- Express unknown usage by extending the single rule `RunUsage.is_billable_but_unpriced`. CLAUDE.md forbids restating it.
- Token fields default to 0 and the readers turn `None` into 0, so a "known" flag is needed.
- Decide whether `by_model` groups by serving or by requested model; the A/B harness uses it.

**Step 5: TTL split.**
- The API reports `usage.cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`.
- Citation is inherently mixed-TTL (the API adds 5-minute writes after server-tool results), so deriving the TTL from the phase policy over-prices it.
- Read the split in `digest._message_cache_usage` and its inline copies.
- Split the `UsageRecord` fields additively, and price per TTL in `usage_record_cost`.
- Fix the stale comment in `core/pricing.py`.
- Of the 18 `_record_usage` call sites, only investigation passes `cache_write_ttl` today.

**Step 7: partial streams.** The site is `core.api_config._dispatch_messages` (`with stream: return get_final_message()`). Capture `current_message_snapshot` when the stream raises, and thread it through `digest_sheet`'s retry loop. Implemented with WP-01.7.

**Step 8 is mostly done.** The manifest writes `pricing_effective_date`, and the exhaustive dialog shows it. It is still missing from the standard dialog, the report's usage table and `run.log`.

**The regression matrix needs WP-02.3's fakes.**
- `FakeUsage` cache fields default to 0, not `None`.
- It has no `iterations`, `cache_creation` or `output_tokens_details`.
- `FakeMessage.model` is hardcoded, and there is no `stop_details`.
- `FinalMessageStream` cannot fail mid-stream.

Slices: WP-14.1 … WP-14.6. Partial-stream capture is WP-01.7.

### WP-15 — Calibrated estimates and preflight efficiency

**Priority:** P1/P2. **Covers:** $1–$3, R6, N23, N24; estimator scaling omitted by the original report.  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/06-cost-usage-config.md`](verification-2026-09-22/06-cost-usage-config.md).
- **Status.** $1, $2 and $3 confirmed. On 2 × 20 dense pages, the preflight took 5,323 ms against 1,374 ms for a hash-free walk producing identical ids and bases. R6 reproduced.
- **Scope added.** N23 and N24.

**N23: the preflight never runs by default.**
- In a default install the preflight never runs. `gui._refresh_profile_suggestions` returns early when `_profile_vars` is empty, which it always is because no profiles ship.
- `_apply_profile_suggestions` is the only writer of the cost bases.
- So both cost dialogs always price at the conservative allowance, and `text_chars` is never available.
- Fixing this makes N24 (unlocked `render.list_sheets` on the UI thread) the default path, so both land together in WP-15.1.

**Step 1 is largely done:** per-stage models via `resolve_stage_models`, transports, `critique_runs()`, and per-model image caps. Retry policy and schema mode remain.

**Step 3: calibration data.**
- Manifests sum the N reads per sheet and hardcode `critique_reads=2`, so per-read calibration depends on WP-22.2 as well as WP-14.
- SDK 1.7.0 reports `usage.output_tokens_details.thinking_tokens`, which nothing reads. Use it.

**Step 5.** "A forecast is not a cap" is already asserted in `tests/test_cost.py`. Retries and pending charges (WP-17) remain.

**Step 7 and CLAUDE.md's measured decision.**
- Step 7 does **not** conflict with CLAUDE.md's measured "no second scan" decision, as long as one walk is kept and only the render-identity hashing is dropped (the preflight discards that result anyway).
- The review's literal fix, switching the GUI to `iter_sheet_cost_bases`, would conflict: that iterator yields no words, so it cannot produce sheet ids.
- To reconcile:
  - add an identity-free iterator, with per-file fault isolation and `assign_source_ids` over the whole file list;
  - keep `iter_sheet_prescan` for the pipeline's level-1 cache;
  - re-measure with `scripts/measure_scan_time.py`, and update the CLAUDE.md figures.
- Latent bug: the per-file call gives every cost basis the source id `SRC-0001`.

**Dependencies.** Steps 2, 7 and 8 depend on nothing. WP-16 is not an estimator dependency.

Slices: WP-15.1 … WP-15.5.

### WP-16 — Run-scoped clients and credential lifecycle

**Priority:** P1. **Covers:** G2, G3; save reentrancy, forgotten-key and export fallback concerns (U20).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/08-shell-release-testinfra.md`](verification-2026-09-22/08-shell-release-testinfra.md).
- **Status.**
  - G3 reproduced: the keyring holds the BOM-prefixed key, the file is deleted, the wire carries `EF BB BF`, and every call gets a 401.
  - G2 traced.
  - `_persist_key` re-entry and the embed fallback reproduced at handler level.

**Step 1.** `client=` is already threaded to all 24 stage sites; only `gui._worker` needs to pass it. Pass a real `anthropic.Anthropic`: a wrapper class silently disables stage overlap (`_stage_overlap_enabled`).

**Step 2.** `os.startfile` and the annotation spawn pool cannot take a scrubbed environment. So the key must stop being written to `os.environ` (`gui.py` ~388/1114/1121; the check at ~1797 also reads it).

**Step 3.**
- Also repair entries that are already corrupted. The legacy file is gone, and `_keyring_get` serves the BOM value first.
- Normalize the GUI field and `save_api_key` too.

**Step 8 (with WP-23.2).**
- The self-check must use a throwaway service name. Using the real `DrawingAnalyzer/anthropic_api_key` entry would clobber a user's saved key.
- Assert `WinVaultKeyring` explicitly, because import errors are swallowed.

**Tests.** They go in `tests/test_gui_lifecycle.py`, which already has a fake-toolkit harness. The `conftest.py` comment saying the GUI has no unit tests is stale.

Slices: WP-16.1 … WP-16.3.

### WP-17 — Cancellation, durable job records, and safe resumption

**Priority:** P1, substantial feature. **Covers:** G1; crash recovery and transport policy. (R2 moved to WP-01.5.)  
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
8. *(Moved to WP-01.5 on 2026-09-22; kept here for context.)* Handle batch refusals separately from envelope success. Use a bounded, capability-compatible fallback batch when permitted. Direct rescue is allowed only under an explicitly selected full-rate recovery policy. Record refusal details without secrets.
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/08-shell-release-testinfra.md`](verification-2026-09-22/08-shell-release-testinfra.md).
- **Status.** G1 traced: there is no cancel argument anywhere, and the batch id reaches disk only as a log line.

**Implementation facts.**
- Batch `custom_id`s are positional (`sheet__{index}`). The job record must map each one to a source fingerprint, a page and a cache key.
- `batch_digest._poll_until_terminal` and `_cancel_batch` are shared with `batch_critique`, so they are the natural cancel hook. Add a "canceled" sentinel that cancels, then harvests with `_harvest_abandoned_batch`, and does not resubmit.
- There is no CANCELED status in `models.py`. Start with PARTIAL plus a reason.
- Step 8 (batch refusals) moved to WP-01.5.

**Size.** Realistically 5–7 sessions. WP-17.1 (cancel plus honest quit wording) delivers user value before any durable-resumption work.

Slices: WP-17.1 … WP-17.4.

### WP-18 — Remote upload and local work-directory ownership

**Priority:** P1/P2. **Covers:** N21, N22; Files API cleanup/storage/inline limits (U4, U5); stale-directory risk (U9); related R6/R7 cleanup.  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/01-outcomes-robustness.md`](verification-2026-09-22/01-outcomes-robustness.md).
- **Status.**
  - The Economy bypass reproduced: 3 real-time calls and 0 batches under `RECOVERY_BATCH`.
  - A synthetic dense 42 × 30 in vector sheet produced 37 images and a 50.8 MB inline request.
  - The live-directory prune reproduced.
- **Scope added.** N21 and N22.

**Step 5: four parts.**
1. The submit functions take no recovery policy; it exists only on `collect_drawing_batch`. Thread it from `_digest_sheets_via_batch` and `_run_critique_stage`.
2. The critique twin, `batch_critique._serve_realtime`, runs full-rate two-read critiques on **any** upload error.
3. Existing tests assert the fallback and must flip: 3 in `tests/test_drawing_batch.py` and 2 in `tests/test_drawing_batch_critique.py`.
4. The size guard belongs in the shared inline builder, because Fast/Hybrid real-time digests and critiques send the same unguarded payload.

**Steps 2–3: files persist.**
- Per the Files API documentation, uploads persist until deleted, against an organization quota.
- Correct "expire server-side" (`batch_critique.py`, `help_content.py`) and "files cost nothing to store" (`_release_uploaded_files`) (N22).
- Until a durable cleanup record exists, every detach path is a permanent leak.
- The status code for a storage-quota rejection is undocumented; confirm it before classifying.

**Step 1.** Name the ownership hand-off: `_finish_digest_uploads` → the sink → the critique stage's `finally`.

**Step 6.** The prune matches only `drawing_qc_*`. The render spool's `drawing_render_reuse_*` directories need the same lease.

Slices: WP-18.1 … WP-18.5.

### WP-19 — Valid report-chat history after every termination path

**Priority:** P1. **Covers:** R4; server/client tool and fallback replay integrity.  
**Primary files:** embedded JavaScript in `html_report.py`, report-chat/browser fixtures.  
**Dependencies:** shared replay requirements from WP-01/WP-13; no need to wait for bounded retrieval.

Implementation:

1. Represent pending/completed tool relationships by ID and block type. Client and server tools have different response/replay semantics; use an explicit turn state rather than testing only `type === 'tool_use'`.
2. During a legitimate mixed-tool continuation, preserve the deferred server call needed by the service when client results return. Do not remove every unmatched server block indiscriminately before normal continuation.
3. When a turn is abandoned by Stop, refusal, stream failure, or continuation-cap exhaustion, normalize it into safe reusable history. Remove unresolved tool requests while retaining completed tool/result pairs and useful visible text. Do not fabricate success results for tools that never executed.
4. Use the same normalization contract at live commit, storage save, and storage load. Repair legacy poisoned tails idempotently while preserving usable conversation content. *(Corrected 2026-09-22: do not bump the stored transcript version. Today any non-v1 schema makes `restoreFromStorage` delete the saved transcript. Keep v1 readable, repair on load, and version only additively.)*
5. Preserve provider-required fallback boundaries, selective replay rules, and valid signed thinking. Maintain fixtures for pre/post-fallback block types and paired/unpaired server results.
6. Keep generation guards so an older asynchronous request cannot commit after New chat, transcript replacement, or reload. Stop must remain effective during client-tool execution as well as network streaming.
7. Show a concise explicit message when a continuation cap ends a response. Permit the next ordinary question only after the stored/request history is coherent.

Regression matrix: mixed client/server parallel calls; Stop before/during/after each phase; multiple IDs; partially streamed tool JSON; paired server result versus deferred server call; repeated pause turns; limit reached; refusal; fallback; reload; conversation replacement while work is active.

**Acceptance:** a new question after each interrupted scenario uses valid history; saved/reloaded conversations behave the same; completed evidence is retained; no fictitious tool action appears. Confirm representative replay with real-SDK schema tests and a separately budgeted live canary.

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/07-report-markup.md`](verification-2026-09-22/07-report-markup.md).
- **Status.** R4 reproduced in all four scenarios, and it survives reload:
  - Stop after a `pause_turn`;
  - Stop in a mixed group;
  - the continuation cap;
  - `max_tokens` in the middle of a server tool.
- A fifth path was found: an abort or stream failure after a `pause_turn` round was already committed.

**Steps 1 and 4: pairing across rounds.**
- Each `pause_turn` round is stored as a separate assistant entry, and the resumed round begins with the previous round's `*_tool_result`.
- So a per-message pairing check would strip the earlier server calls and orphan their results.
- Check pairing over the run of consecutive assistant entries, as the API merges them, or merge the rounds on commit.

**Step 2.**
- "Deferred server call" is not a documented mechanism. The code already commits all blocks when a client `tool_use` is present.
- Settle mixed-group behavior in the live canary.
- The docs do confirm that a paused turn may end in a trailing `server_tool_use`, which is resumed with no new user message.

**Step 4 (corrected above).** `TX_SCHEMA = 1` and `transcriptProblem` reject any other version, after which `restoreFromStorage` calls `dropStoredTranscript()`. A version bump would therefore **delete every saved conversation**. Accept v1 and repair on load.

**Step 5 and the "fallback" matrix entry.** The widget sends no `fallbacks` parameter or beta header, and it defaults to Sonnet 5. Make both conditional on the configured model.

**Step 6 already exists** (generation guards, the `stopRequested` latch, and a test). Treat it as regression-only.

**Acceptance.** The widget is raw-fetch JavaScript, and pairing is a server-side rule, so real-SDK schema tests cannot catch R4. Use one history validator, shared by commit, save and load, plus the live canary (O-4).

Slices: WP-19.1, WP-19.2.

### WP-20 — Bounded assistant context, accurate chat costs, and calculator input

**Priority:** P1/P2. **Covers:** unbounded context (U17), H3, N7, N26, reader-key storage risk (U19).  
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
8. Remove the unconditional “guaranteed correct” tool wording. Return validation/range errors as tool results with `is_error: true`, not plausible-looking arithmetic answers. Bound the expression echoed back in an error.
9. Validate local-file reader-key storage with disposable dummy keys in supported browsers: same-tab navigation, other tabs, reload, Forget, and unavailable storage. Do not claim universal file-origin isolation.
10. Prefer in-memory credential retention where persistent session isolation cannot be established. Preserve explicitly selected embedded-key behavior and sharing warnings; do not introduce background persistence or load unrelated saved credentials.

Acceptance fixtures:

- A synthetic 400-sheet report answers targeted questions about first/last/duplicate-labeled sheets without embedding the entire corpus.
- Retrieval pagination and history trimming cannot split tool exchanges or hide that content was omitted.
- Equivalent cumulative usage event sequences yield identical totals, including search charges.
- Reject `1.2.3 + 1`, `1e+ + 2`, and `1 2 + 3`; compute the large-integer subtraction correctly or reject it explicitly; ordinary supported calculations remain useful.
- Dummy-key browser tests establish the actual storage boundary; mitigation and documentation reflect the measured result.

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/07-report-markup.md`](verification-2026-09-22/07-report-markup.md).
- **Status.** N7 reproduced under node:
  - `1.2.3 + 1` gives 2.2;
  - `1e+ + 2` gives 3;
  - `1 2 + 3` gives 15;
  - `9007199254740993 − 9007199254740992` gives 0.
- The unbounded context, the per-keystroke search cost and the `file://` key exposure were reproduced or sized.
- **Scope added.** N26.

**Step 1: tests, text and retrieval.**
- Rewrite `tests/test_report_chat_tools.py::test_report_block_uses_one_hour_ttl` and `::test_system_blocks_are_byte_stable_across_turns`.
- Update the preamble ("The next system block is the complete report text") and the CLAUDE.md wrapper paragraph.
- The verbatim text exists only in `#raw-md`, so per-sheet retrieval needs a host-side offsets map keyed by sheet, source and page. The section headers are host-generated (`pipeline._sheet_header`); do not parse model prose in JavaScript.

**Step 2.** An "output/continuation reserve" conflicts with the documented rule never to lower `max_tokens` below the model ceiling. Record the decision.

**Step 3: substring matching.** Existing label consumers resolve by substring:
- `toolScroll` takes the first substring match (`M-10` hits `M-101`; with duplicates, the first wins);
- the `query_findings` sheet filter is a substring match too.

**Step 7.** The CSP allows only hash-pinned inline scripts, so no CDN library. Native `BigInt` rationals give exact results with explicit division rounding.

**Step 8.**
- `toolCalculate` returns error strings, and `runTool` sets `is_error` only when a tool throws. Return errors with `is_error: true`.
- Bound the expression echoed back in error messages: a 20k-deep expression echoes 40k characters.

**N26 (missing from the plan).** `saveTranscript` writes up to 500k characters to `localStorage` on the `file://` origin, where any other local HTML file can read it. Steps 9–10 cover only the key.

**Acceptance.** The stubbed harness can check the request shape and the retrieval results. Answer quality on the 400-sheet fixture needs a live or manual check.

**Dependencies.** Steps 5–10 (H3, N7, storage) need none of WP-03, WP-14 or WP-19; they are scheduled independently.

Slices: WP-20.1 … WP-20.5.

### WP-21 — Report vocabulary, grouping, PDF plans, and destinations

**Priority:** P1/P2. **Covers:** H1, H2, R5, B8 navigation consumers, N9; report search efficiency (U18).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/07-report-markup.md`](verification-2026-09-22/07-report-markup.md).
- **Status.** H1, H2, R5 and N9 reproduced (N9 is re-described in §3).
- **Search cost measured** on 400 sheets: 18–20 ms per keystroke at normal CPU, 148–165 ms at 6× throttle.

**Steps 1–2: the display vocabulary.**
- A "failed verification attempt" cannot be represented per finding today. `verify.py` stores UNCERTAIN or SKIPPED, with the error only in `note`, and the `DEGRADE_*` kinds exist only as stage counters. So this depends on WP-01.1.
- The PDF index merges SKIPPED and UNCERTAIN into "Check".
- New states must also update:
  - `_FINDING_STATUS_CHIP`;
  - the integer `_STATUS_RANK`, which the browser sorts through `parseInt`;
  - `_UNCONFIRMED_STATUSES` and the `.fchip-*` CSS;
  - the `query_findings` status text and `toolSummary`.
- The CSV already has `anchor_status` and `anchor_method`. Add a column rather than rewriting them.
- H2 detail: the PDF prints `[SHEET-WIDE]` for a SHEET-hint finding; `[NO QUOTE TO CHECK]` applies to the others.

**Step 3.**
- The existing browser test (`tests/test_report_browser_security.py`, grouping after sort) passes on the bug, because it checks counts only. Strengthen it.
- CLAUDE.md's "recomputes after every sort/filter" is false for sort. Fix it in WP-21.2.

**Step 4: search semantics.**
- "Keep search semantics identical" contradicts "exclude transient controls". Today `row.textContent` includes the repeat-toggle label, so searching "more sheet" matches only the group lead.
- Highlights use the CSS Highlight API and add no DOM text.
- Compare against a reference that excludes control text, with a measured time budget.
- The text scan is not the dominant cost: clearing the search is mostly layout.

**Step 5 (R5).** The child's final placements already come back in `outcome.receipts[i].placement`. Rebuild the plan from the receipts by `placement_id`; no new outcome field is needed.

**Steps 6–7.**
- Two sites are keyed by `finding.id`: `mark_page_by_finding`, and the outline's `seen` set.
- Keying both by `placement_id` fixes the misrouting and the dropped bookmarks without waiting for WP-03.
- `MarkupReceipt` has no rect, so recording a row destination needs an additive field and a manifest change.

Slices: WP-21.1 … WP-21.4.

### WP-22 — Diagnostics, configuration fidelity, and defensive deserialization

**Priority:** P1/P2. **Covers:** N25; secret-redaction performance and path gaps (U13), run-configuration/status boundary cases (U14, U15), string refs (U16), lint and dead code (U27).  
**Primary files:** `diagnostics.py`, `run_journal.py`, `models.py`, `pipeline.py`, configuration tests.

Implementation:

1. Replace pathological secret-field matching with bounded/linear behavior while preserving credential coverage. Redact before persistence; truncating first must not expose an otherwise recognizable secret prefix.
2. Keep the right-side component boundary on registered private-root matching and protect unrelated URLs by masking them before the root pass. *(Corrected 2026-09-22: do not add a left boundary. Its absence is what fully scrubs a root embedded under another path.)* Handle quoted paths, spaces, doubled separators, UNC/extended-length Windows forms, and ordinary POSIX paths deliberately.
3. Keep useful basenames where allowed, but remove private directory components. Apply sanitization consistently to host-generated errors/status in every exported artifact. Do not blanket-redact drawing prose such as `TOKEN: 12` as if it were host credential output.
4. Resolve the actual critique-read count once and use it in configuration, execution, keys, estimates, and manifests. Audit other flags that are represented as enabled but ignored outside markup.
5. Publish an explicit supported configuration matrix. For expert verification/investigation requests outside markup, either honor the request or reject/resolve it visibly before paid work; do not report a stage as enabled while silently skipping it.
6. Strengthen required-stage rollup so missing required stage records cannot yield COMPLETE. Keep genuinely nonrequired stages out of the required denominator. Test malformed input state separately from reachable normal execution.
7. Normalize string `refs` to one reference through a shared coercion helper; handle null/list/malformed mixed inputs explicitly. Keep additive serialization compatibility and normal list round-trips.
8. Update stale descriptions only after behavior is established. Remove truly unused production helpers when their deletion is safe and reduces conflicting policy; preserve tested compatibility shims unless deliberately deprecated.

**Acceptance:** adversarial redaction input does not exhibit quadratic growth; supported secrets/private path forms do not leak; URLs are not corrupted by root replacement; manifests describe actual effective settings; absent required outcomes cannot imply completion; string references no longer split into characters.

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/06-cost-usage-config.md`](verification-2026-09-22/06-cost-usage-config.md).
- **Status.** All reproduced:
  - the quadratic redaction (`"a_" × n`: 4k in 385 ms, 8k in 1.54 s, 16k in 5.88 s);
  - the path-scrub gaps;
  - the roll-up holes;
  - the configuration mismatch;
  - the `refs` split.
- **Scope added.** N25.

**Step 1: redaction.**
- Also cover `RedactingFormatter`: elide → redact → truncate at 64k, about 90 s per record by extrapolation.
- A possessive `*+` stays quadratic and loses the `ANTHROPIC_API_KEY` match. A `{0,8}` prefix bound is linear, with the same coverage on the test samples.
- Write the acceptance test as an absolute bound (for example, a 64k adversarial chain redacts in under 0.5 s), not a growth ratio.

**Step 2 (corrected above): no left boundary.**
- "Boundaries on both sides" is wrong for the left side. The missing left boundary is what fully scrubs `/mnt/backup/home/abe/Client Jobs/x.pdf` when the root is `/home/abe/Client Jobs`.
- The visible harms are:
  - corrupted URLs and relative paths. With root `/tmp`, `https://example.com/tmp/g.html` becomes `…com.../g.html` and `docs/tmp/n` becomes `docs.../n`;
  - an unquoted doubled-backslash Windows path, which leaks even with its root registered;
  - `\\?\UNC\srv\share\…`, which leaks outright.
- The fix:
  - mask URLs before the root pass;
  - allow `[\\/]+` between root components;
  - add `\\?\` and `\\?\UNC\` branches, because `?` is excluded from `_WIN_PATH_RE`'s component class.

**Step 4: read counts and families (N25).**
- Execution already uses `critique_runs()`. The configuration value reaches only the journal and the manifest.
- Also update `models.SOURCE_TAGS`, `ledger._FAMILIES`, `ledger._families` and `ledger.provenance_label`. With three or more runs, `critique_3` fabricates cross-family corroboration.

**Step 5: expert stages outside markup.** Honoring verification or investigation outside markup breaks DA-013 unless they are added to `any_paid_expert`. Two tests lock today's behavior:
- `test_explicit_investigate_true_is_honored_and_keeps_the_free_battery`
- `test_expert_stage_without_qc_markups_runs_but_stays_non_exhaustive`

**Step 6: required stages.**
- The roll-up needs a map from `RunConfiguration` to the required stage names: digest, identity, review_plan, profiles, critique, cross_qc, synthesis, auditors, prose_harvest, edition_audit, verification, investigation, citation, markup.
- Two tests pass partial stage lists and must be rewritten: `test_rollup_clean_run_is_gated_to_partial_when_gate_closed` and `test_rollup_debug_override_is_partial_even_when_clean`.
- Coordinate with WP-01.1.

**Step 7: three coercions disagree today.**
- `digest._coerce_refs` (the live model path for digest, critique, prose harvest and cross-QC) **drops** a bare-string ref.
- `set_identity._as_list` keeps it as one element.
- `Finding.from_dict` splits it into characters.
- Put the shared helper in `models.py`; set_identity imports models, so the reverse would cycle.
- Stored parsed findings will change, so add a migration note.

**Step 8: stale items and lint.**
- `cost.py` and `critique.py` comments still say "16k".
- The `token_count_preflight_enabled` docstring is stale.
- `count_tokens_via_api` has no callers, though CLAUDE.md names it.
- The production-orphaned helpers listed in §1.2, and the "Spec Critic" docstrings.
  - Remove a helper only deliberately, where its presence misleads. For example, `web_search_max_uses_for_severity` references a `GRIPES` severity that does not exist.
  - `docs/MEASUREMENT_PACKAGES.md` §2 prohibits removing unused compatibility APIs as incidental cleanup.
  - Keep `count_tokens_via_api`: it is the documented exact-count path, and the candidate for WP-15 step 9. Just stop CLAUDE.md implying that it has callers.
- Add the lint step here: F401/F811/F841/B017 in both `ci.yml` and `release.yml`.
  - An F,B run gives 95 hits: 9 `src` F401s, the F841 `sug`, and 3 B017s.
  - The 6 B023s in `ledger.py` are false positives, so do not enable B023 or B905.

Slices: WP-22.1 … WP-22.5.

### WP-23 — Reproducible packaging and enforceable release acceptance

**Priority:** P1. **Covers:** G4, G5, N8; installer upgrade hygiene (U23), self-check (U21), license/audit gaps (U24).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/08-shell-release-testinfra.md`](verification-2026-09-22/08-shell-release-testinfra.md).
- **Status.** G4, G5, the frozen keyring self-check, the uninstall residue and the license gap confirmed. **N8 occurred** (§1.2).

**N8 is an incident.**
- Ship the minimal gate (WP-23.1) first, before any 1.7.x tag: a non-RC `publish` fails unless the acceptance record reads SHIP or lists unexpired waivers.
- A tag runs the workflow file from the tagged commit, so a YAML check only stops accidents. The independent boundary is a protected Environment or tag ruleset configured by an admin (O-5).
- An `environment:` name that is not configured is auto-created with no protection. Verify through the API.
- Update `tests/test_browser_suite_gate.py`. It pins the exact `needs:` string and the Inno Setup "6.2.2" fallback.

**The rule WP-23.1 enforces (clarified 2026-09-23).** "Reads SHIP or lists unexpired waivers" is ambiguous. Read as a plain OR, one waiver would publish a HOLD record, which breaks this package's acceptance criterion and the records' own policy: `ACCEPTANCE-1.7.0.md` keeps the stable tag on HOLD until the sections are recorded or waived *and* "the Release decision line in the sign-off reads SHIP". So the gate requires both:
- the Sign-off's single `Release decision:` line starts with the word `SHIP` and does not also say `HOLD` (`SHIPPED`, as in the 1.6.0 record, and the template's unfilled `SHIP / HOLD` both refuse);
- every waiver the record lists is complete (item, scope, justification, owner approval, `Expiry` as `YYYY-MM-DD`) and unexpired, valid through its expiry day in UTC.

This is stricter than either reading, never weaker. Waivers stand in for sections, not for the decision. An expired waiver refuses even under SHIP. `publish` checks the earliest expiry twice: before uploading, because an environment approval can come days later, and again after uploading into a draft, just before one final call makes it public.

**What WP-23.1 leaves of steps 9–12 (now WP-23.6):**
- the release-run attestation that binds the record to the tested candidate (step 10: a code-tree fingerprint with a strict allowlist of evidence-only changes, such as the version literals, the CHANGELOG heading and `docs/releases/`) and to the built artifact hashes;
- per-section validation: every §§2–6 item recorded or covered by a named waiver;
- the stale, wrong-commit and wrong-artifact record tests of step 12;
- optionally, a check through the API that the `release` environment really is protected. That check needs O-5 first, and it runs from the tagged commit's workflow, so it is evidence, not a boundary.

**Step 1.** The package has no data files (there is no `profiles/` directory, and only `.py` is tracked). Replace `collect_all` with `collect_submodules`. The review's spec line number is stale; the spec lost 5 lines in 1.7.0.

**Step 2.**
- Scan `dist/DrawingAnalyzer/` before ISCC. `Setup.exe` is LZMA2 solid-compressed, so a scan of the installer cannot see a key.
- `scripts/scan_secrets.py` scans only git-tracked files, and it echoes 24 characters of each match. Redact the output.

**Step 3.**
- `requirements.txt` already has marker-qualified GUI pins.
- `requirements-release.lock` has no GUI or keyring pins.
- `pyinstaller-hooks-contrib` is unpinned.

**Step 4.** The frozen tree has dist-info for only three distributions, so diff the build venv's `pip freeze` instead. `gates-windows` and `ci.yml` are also unconstrained.

**Step 6.** `ArchitecturesInstallIn64BitMode=x64compatible` needs Inno Setup ≥ 6.3 (verify), but the fallback installer is pinned to 6.2.2.

**Step 8.** The license check and pip-audit run only in the Linux `.[dev]` environment, so the shipped Windows GUI dependencies are never audited.

Slices: WP-23.1 … WP-23.6.

### WP-24 — Update authenticity, download constraints, and launch verification

**Priority:** P1/P2. **Covers:** G6 and update-channel hardening; update dialog over modals (U22); network and checksum documentation (U25).  
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

**Verification notes (2026-09-22).** Evidence: [`verification-2026-09-22/08-shell-release-testinfra.md`](verification-2026-09-22/08-shell-release-testinfra.md).
- **Status.**
  - G6 reproduced: a file rewritten during the "Install update?" prompt was launched.
  - The dialog-over-modal case reproduced at handler level.

**Step 1.** `fetch_manifest` has no opener seam, and the stdlib redirect handler follows https→http and https→ftp. Use one shared opener for the manifest and the download.

**Step 6.** `_on_update_download_done` receives only the path. Thread `info.sha256` through, and reuse `updates.verify_sha256`; today its only caller is a test.

**Step 7.** There are about 30 native modal sites, and none is visible to a Tk grab, so a busy/modal flag is needed. `_start_update_download` already refuses while busy.

**Steps 3–5.**
- A signature library is a new Windows native dependency: `cryptography` is pinned Linux-only in `requirements.txt`.
- That ties it to WP-23's locks and license review.
- Key custody is human-only (O-6).

**Step 9.** Correct `README.md` line ~74 ("talks only to the Anthropic API") and `docs/RELEASE_WINDOWS.md` (~131–135). The later README network section is already accurate.

Slices: WP-24.1 … WP-24.3.

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

**Verification notes (2026-09-22).**
- Each experiment is a row in [`PROGRESS.md`](PROGRESS.md) (WP-25.1 … WP-25.12).
- All are blocked on a live budget (O-4), and on the evaluation corpus (O-10) where quality is judged. A session may prepare the flag and the harness beforehand.
- Two additions:
  - the cross-QC text-allocation experiment must also decide N14 (degraded results are never cached);
  - the web-tool row includes settling web fetch on Opus 5 (review §3.4, U32) with one canary call.
- **Use the existing measurement packages; do not duplicate them.** `docs/MEASUREMENT_PACKAGES.md` already defines several of these experiments, with a common 11-step protocol that every WP-25 experiment follows:
  - R-06: shared prefix (WP-25.1);
  - R-02 and R-03: overlap/target and adaptive grids (WP-25.7);
  - R-05: batch verification (WP-25.10);
  - R-04: text budget and evidence coverage (WP-25.4).
- R-01 (Sonnet digest with Opus critique) remains an open measurement package outside this plan.
- **Expected savings are disputed.** R-06 estimates a much smaller advantage for the shared prefix (about 6.4% of the image component over the current successful-cache case) than the review's 2.35× → 1.45× (~38%). Measure; assume neither.
- WP-25.6 must respect the standing prohibition on changing the critique read composition while keeping the confidence-label semantics.

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

**Environment (verified 2026-09-22).**
- Setup: `pip install -e ".[dev,browsertest]"`, then `pip install cffi`. In the cloud container the system `cryptography` lacks `_cffi_backend`, which is an environment defect, not an app bug.
- Always pass `-m "not network"`: `conftest` runs the live canary whenever a real key is exported.
- Chromium is pre-installed: never run `playwright install`.
- Baseline at `8521366`: 2,450 passed, 11 skipped, 0 failed. The browser suite executes 98/98.
- The exact commands are in [`README.md`](README.md) steps 2 and 5.

## 7. Traceability register

### 7.1 Every numbered finding in the original report

The current disposition of every ID below, of N1–N27 and of U1–U32 is kept in the register in [`PROGRESS.md`](PROGRESS.md). This section records where each item is addressed.

| Finding | Required package(s) | Completion nuance |
|---|---|---|
| B1 | WP-03, WP-04 | Symmetric full-member comparison; ranking/order variants tested. |
| B2 | WP-04 | Hyphenated units without weakening tag parsing. |
| B3 | WP-04 | Whole-number grouping and no trailing fragment. |
| B4 | WP-05 | Positive extraction variants plus numeric false-match vetoes. |
| B5 | WP-05, WP-06 | Short tags require evidence; textless fallback remains honest. |
| B6 | WP-06 | Fix prompt field, keep validation strict. |
| B7 | WP-03, WP-07 | Distinct arithmetic findings survive the coordinator **and the ledger** (arithmetic claim discriminator; WP-03.3). |
| B8 | WP-03, WP-21 | Claim identity, numbering, bookmarks, destinations. Evidence directories are already unique; navigation keys on `placement_id` (WP-21.3). |
| B9 | WP-03 | Preserve meaningful actions/provenance, not every paraphrase as a separate issue. |
| B10 | WP-06 | Canonical evidence legs plus claim identity, not a sheet-set-only key. |
| B11 | WP-09 | Boilerplate rejected before both model call and degraded finding. |
| B12 | WP-04 | Equivalent notation without collapsing temperature scales. |
| R1 | WP-11 | Isolate opens/pages; retain context and completed paid work. |
| R2 | WP-01 (WP-01.5; moved from WP-17) | Refusal recovery preserves selected transport and bounds. |
| R3 | WP-14 (WP-14.1), WP-17 | Canceled and errored envelopes keep attempt provenance, on the harvest path and the terminal path. |
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
| K2 | WP-10 (implemented in WP-06.2) | Cross-QC user framing participates in effective identity. |
| K3 | WP-10 | Cache actual batch/plain/structured contract. |
| K4 | WP-10 | Cache original planner loss metadata. |
| K5 | WP-03 | Same claims receive same QC ordering regardless of ingestion. |
| A1 | WP-08 | Contextual spec-reference evidence. |
| A2 | WP-08 | Arrangement matters even with a frequency winner. |
| A3 | WP-08 | Inventory-scoped memoization and lazy nearest matching. |
| A4 | WP-08 | Phrase/list recall with a negative corpus. |
| A5 | WP-08 | Label/context ranking and explicit ambiguity. |
| A6 | WP-08 | Correct conditional FM displacement; preserve FM-only behavior. References to missing FM sheets are reported (N17). |
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

Stable IDs `U1`–`U32` were added on 2026-09-22 so that [`PROGRESS.md`](PROGRESS.md) can track each concern. The current disposition of every row is in its register.

| ID | Concern | Package/disposition |
|---|---|---|
| N1 | N1 shared measurement masking | WP-04; mandatory. |
| N2 | N2 distinct cross-QC claim loss | WP-03/WP-06; mandatory. |
| N3 | N3 repeated-operand false certainty | WP-07; mandatory. |
| N4 | N4 terminal-state success/cache errors | WP-01/WP-10; mandatory. |
| N5 | N5 verification false completeness | WP-01; mandatory. |
| N6 | N6 duplicate-source cross-QC binding | WP-06; mandatory. |
| N7 | N7 calculator grammar/precision | WP-20; mandatory. |
| N8 | N8 acceptance hold not enforced | WP-23; mandatory. |
| N9 | N9 overflow destination coordinates | WP-21; validate and correct the traced mismatch. |
| N10 | Prose match ignores measurement signatures | WP-09 (WP-09.2); mandatory. |
| N11 | Negation-blind synthesis conflict extraction | WP-09 (WP-09.1); mandatory. |
| N12 | Matches ignore word boundaries (anchor and cross-QC) | WP-05 (WP-05.1, WP-05.2); mandatory. |
| N13 | Cross-QC and anchor normalizers disagree | WP-05 (WP-05.1); mandatory. |
| N14 | Degraded cross-QC never cached; permanent PARTIAL and re-billing | WP-06.3 records a decision; WP-25.4 evaluates the budget. |
| N15 | Errored-digest findings ingested unlabelled | WP-01 (WP-01.3); mandatory. |
| N16 | Truncation retry can lose the first read | WP-01 (WP-01.3); mandatory. |
| N17 | Missing FM sheets never reported | WP-08 (WP-08.4); mandatory. |
| N18 | Contradictory transcriptions counted as independent checks | WP-07 (WP-07.3); mandatory. |
| N19 | W×H, compact electrical units, ranges/lists lack signatures | WP-04 (WP-04.1); mandatory. |
| N20 | Investigation executes pre-fallback tool_use blocks | WP-13 (WP-13.4); mandatory. |
| N21 | Files-API failure fallbacks bypass Economy; inline oversize | WP-18 (WP-18.1, WP-18.2); mandatory. |
| N22 | Uploads described as expiring; they persist until deleted | WP-18 (WP-18.4, WP-18.5); mandatory. |
| N23 | GUI cost preflight never runs in a default install | WP-15 (WP-15.1); mandatory. |
| N24 | Unlocked PyMuPDF use on the UI thread during preflight | WP-15 (WP-15.1); mandatory with N23. |
| N25 | Critique runs ≥ 3 fabricate corroboration | WP-22 (WP-22.2); mandatory. |
| N26 | Chat transcript readable by other local files | WP-20 (WP-20.3); mandatory. |
| N27 | Clean-EOF stream cached as a complete digest | WP-01 (WP-01.2); mandatory. |
| U1 | Actual serving model, fallback iterations, partial-stream billing | WP-14; mandatory. |
| U2 | Fallback text joins and selective history replay | WP-01/WP-12/WP-13/WP-19; preserve contiguous text and required block semantics. |
| U3 | Generic output-config rejection disables task budget | WP-13; mandatory. |
| U4 | Oversized inline fallback and upload quota failures | WP-18; mandatory explicit handling (see N21). |
| U5 | Remote orphan files; daemon-only cleanup | WP-17/WP-18; owned durable cleanup, not a blind org-wide sweep (see N22). |
| U6 | Cross-QC output cap/recovery | WP-01/WP-06; mandatory terminal honesty; cap tuning evaluated. |
| U7 | Cross-QC text truncation and 40-fact bottleneck | WP-06 observability; WP-25 quality/cost redesign. |
| U8 | Whole-set grounding absent | WP-05/WP-06; mandatory. |
| U9 | Live but idle work-directory pruning | WP-18; validate with synthetic liveness fixtures. |
| U10 | Mentioned versus adopted codes; limited edition families | WP-12; mandatory distinction and bounded grammar coverage. |
| U11 | Prose match threshold/call prevalence | WP-09 instrumentation; change the threshold only with labeled evidence. The signature check on the match itself is mandatory (N10). |
| U12 | Investigation truncation, Unicode IDs | WP-13; mandatory handling and bounded recovery. Duplicate detected ids must not bind first-wins. |
| U13 | Quadratic redaction and path-scrub gaps | WP-22; mandatory. |
| U14 | Empty required-stage/status cases | WP-22; defensive hardening, separately labeled from N5. |
| U15 | Resolved configuration versus execution | WP-16/WP-22; mandatory truthful effective configuration. |
| U16 | String references split into characters | WP-22; input-boundary correction. |
| U17 | Unbounded report/history context | WP-20; mandatory budgeting/retrieval. |
| U18 | Search rescans large report | WP-21; measure and preserve results. |
| U19 | Local-file sessionStorage exposure | WP-20; browser-specific validation and appropriate credential policy (see N26 for the transcript). |
| U20 | Persistence reentrancy, cleared key reloaded during export, no Forget | WP-16; mandatory. |
| U21 | Frozen keyring functionality | WP-16/WP-23; functional acceptance. |
| U22 | Update dialogs interrupt another modal workflow | WP-24; defer presentation safely. |
| U23 | Uninstall state retention | WP-23 documentation and explicit policy; do not silently delete user data. |
| U24 | License script checks only metadata | WP-23 reviewed license policy. |
| U25 | Network-description and checksum/signature documentation | WP-24; correct concrete claims. |
| U26 | Test fake fidelity, missing batch canary, no socket guard | WP-02; mandatory. |
| U27 | Narrow lint classes and dead code | WP-22 (WP-22.5); selectively enable F401/F811/F841/B017 after triage (not B023/B905); avoid mass unrelated formatting. |
| U28 | Broken cryptography wheel on the original review machine | Environment only, confirmed 2026-09-22: reproduced in the cloud container, where `pip install cffi` resolves it. Not an app bug; plan WP-02 step 8 still forbids broad `BaseException` catches. |
| U29 | Remove tiktoken | Already done; preserve. |
| U30 | Add Dependabot | Already present at original baseline; no duplicate work. |
| U31 | Broad “everything sound” assertions in original report | Revalidate touched areas; WP-01 explicitly corrects the overbroad truncation claim. |
| U32 | Web fetch on Opus 5 unsettled (review §3.4) | WP-25 (WP-25.11): settle with one canary call; keep the conservative capability gate until then. |

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

The traceability register with dispositions is maintained continuously in [`PROGRESS.md`](PROGRESS.md) (slice INT.3 completes it). The integrated release report must include the traceability register with every item assigned **implemented and validated**, **already satisfied**, **disproved with evidence**, **experiment rejected/deferred with rationale**, or **blocked on a named external gate**. An unresolved mandatory correctness item is not converted into “optional” simply because it is difficult.

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
