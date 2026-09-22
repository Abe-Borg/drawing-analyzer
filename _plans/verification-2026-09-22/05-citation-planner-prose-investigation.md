> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-09, WP-10 (K4), WP-12, WP-13, WP-14 step 5 (C3). The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# citation-planner-prose-investigation — final report (HEAD = 1.7.0 code)

Hermetic repro scripts: scratchpad `verify/citation-planner-prose-investigation/`.

## 1. Verdicts

| ID | Verdict | Current anchor(s) | Evidence | Plan correction |
|---|---|---|---|---|
| B11 | STILL PRESENT (reproduced) | `prose_harvest.py::_TRIVIAL_RE (144)`, `::_split_items (181)`, `::_degraded_entry (643)` | All 4 strings pass; `harvest_prose(client=None)` → medium SHEET entries. "No isolation valve is shown" survives; a repeatable-qualifier regex passes a 7+7 corpus. | Add synthesis negation (§2) |
| R7 | STILL PRESENT (reproduced) | `investigate.py::_investigate_one` API-error return (993–1001), initial-crop return (942), tail (1111–1128) | 400 after a crop: 2 PNGs on disk, `evidence=[]`, `investigated=False`, no investigation.json. Initial-crop path saves nothing. Export copies all of `evidence/` (`export.py:1310`): files ship unreferenced. | — |
| C1 | STILL PRESENT (reproduced) | `citation_check.py::_check_one (828; raw_text 913)` → `digest.py::_message_text (753)` | Cited middle block → `"\n"` inside `note` → parsed=False (`""` join parses); `check_citations` partial=True, UNCHECKED, not cached. | — |
| C2 | STILL PRESENT (reproduced) | `citation_check.py::harvest_code_editions (268)`, `::_basis_edition_claims (356)`, `::_adopted_basis_map (418)`, `::reconcile_cited_editions (497)`; `set_identity.py::_sheet_block (268)` | Adoption at char 16.4k: no basis/finding. Identity quote past 15k: low/SKIPPED (full text → medium/DETERMINISTIC). Late stale citation loses tier 1. Capped union made early "NFPA 13-2016 SEC 8.15.1" the adopted edition. | Name identity sites (§2) |
| C3 | STILL PRESENT (traced; pricing computed) | `pipeline.py` citation `_record_usage` (2274–2290); `core/api_config.py::_PHASE_CACHE_POLICY (884)`, `::cache_write_ttl_for (929)` | PHASE_CITATION absent → default → "1h" sent; record omits TTL: 1M writes on Sonnet 5 priced $2.50, not $4.00. Only investigate passes TTL (2195). | Citation is mixed-TTL (§2) |
| C4 | STILL PRESENT (reproduced) | `investigate.py::investigation_tools (418)`, `::_build_initial_content (836)`, `::_investigate_one (1071)` | 6 `find_text` → rounds=6, forced close, 0 crops. `find_text` never enters `tool_trace`/investigation.json. | — |
| C5 | STILL PRESENT (reproduced) | `citation_check.py::_extract_web_sources (781)`; call at 914 | pause_turn search URL + `web_fetch_tool_result` URL → `sources=()`. | — |
| C6 | STILL PRESENT (reproduced) | `citation_check.py::_EDITION_RE (251)`, `::_EDITION_SEP (328)` via `::_family_year_re (379)` | "NFPA 13 — 2019 EDITION" / "2019 — NFPA 13" harvest nothing; ref "NFPA 13—2016 §8.15.1" yields no divergence. | Regression must cover refs too |
| K4 | STILL PRESENT (reproduced) | `review_planner.py::sanitize_plans (228; cap loop 308)`, `::author_review_plan` warm re-sanitize (477), prompt (96–125); `pipeline.py` review_plan status (~3490) | 5×20 items: cold kept 60/dropped 40 → PARTIAL; warm dropped 0 → COMPLETE. The prompt still says only "at most 25 items per plan". | Migration cascade (§2) |
| H4 | STILL PRESENT (reproduced) | `set_identity.py::_INTL_CODE_WINDOW_RE (202)`, `::_edition_windows (225)`, `_MAX_WINDOWS_PER_SHEET=3 (74)` | ALL-CAPS "IS 1000 MM", "AS 2019 DRAWINGS", "IS 2000 MM" fill all 3 windows; the BS 9251/EN 12845 window is dropped. Case-sensitivity (P8 item 12) cannot help on uppercase CAD text. | — |
| §3.2 `output_config` marker | STILL PRESENT (reproduced) | `investigate.py::_TASK_BUDGET_REJECTION_MARKERS (217)`, `::_investigation_message_turn (300)` | `output_config.effort` 400 → latch off, `effective_task_budget()` 40000→0 (a key term, 1426); the plain resend carries the same bad effort. The existing test's message contains `task_budget`, so narrowing keeps it green. | — |
| §4 regex = ADOPTED | STILL PRESENT (reproduced) | `set_identity.py::union_regex_editions (439)`; `models.py::SetIdentity.context_block (1904)`; `citation_check.py::merged_editions (279)`, audit skip (443–449) | "NFPA 13 2013 §8.15.1" renders under "SET IDENTITY (model-detected): Adopted codes"; editions line "NFPA 13 2013; NFPA 13 2019"; audit basis {2019}. | Step 5 conflict (§2) |
| §4 `_CODE_TOKEN` | STILL PRESENT (reproduced) | `citation_check.py::_CODE_TOKEN (249)` | ASHRAE 90.1-2019, IECC 2021, NEC 2020, TITLE 24 2022, ASCE 7-16/7-22, 2022 CALIFORNIA BUILDING CODE → []. `auditors/sheet_ids.py::_STANDARD_BODIES (312)` confirmed. | Alias table (§2) |
| §4 Jaccard ≥0.7 | STILL PRESENT (traced) plus a correctness defect (reproduced) | `prose_harvest.py::_match_entry (382)`, `_MATCH_OVERLAP (94)` | No signature check. "Provide 4 inch drain…" is absorbed into "…6 inch…" (0.857; signatures incompatible but not consulted). "…165 psi" is absorbed into "…150 psi" (0.82; shared 175 psi = N1). The distinct claim gets no ledger entry. | Mandatory fix (§2) |
| §4 investigation `max_tokens` | STILL PRESENT (traced) | `investigate.py::_investigate_one (1105–1107)`; `INVESTIGATION_OUTPUT_CAP=16_000` | `max_tokens` → not_concluded, with no retry. Already streams, so a raised cap is legal. | — |
| §4 fallback echo | STILL PRESENT (traced); review over-broad | `investigate.py::_investigate_one (1019, 1030)` | Doc rule: omit thinking/redacted_thinking/tool_use (plus unpaired server_tool_use) **before** the final `fallback` block; text echoes. The loop echoes verbatim and would **execute** pre-fallback `tool_use` blocks (1023). Live: the default is Opus 5, streaming. | Add execution filter (§2) |
| §4 `_norm_id` | STILL PRESENT (reproduced) | `investigate.py::_norm_id (494)`, `::_sheet_id_map (498)`, `_ToolExecutor._resolve_sheet (~633)` | U+2011, en dash and fullwidth "Ｐ-201" → "unknown sheet_id"; `normalize_sheet_id` maps all three to P-201. Duplicate detected ids bind first-wins (`setdefault`). | — |

## 2. Plan-text corrections

- **WP-09 step 5 and acceptance:** the current threshold already suppresses distinct issues. `_match_entry` must reject a candidate that fails `critique.signatures_compatible(critical_signature(…))`, reusing the shared rule rather than restating it. Add WP-04 (N1) to the dependencies: the psi case passes only after N1.
- **WP-09 steps 1–3:** `_split_items` already filters before both the model call and the degraded entry. The **synthesis channel is negation-blind**: `extract_synthesis_conflicts (263)` and `extract_set_level_synthesis_conflicts (289)` substring-match `_CONFLICT_SIGNALS`. Reproduced: "No conflicts were found between M-101 and P-101." becomes a paid, dual-anchored structuring item, and "…consistent; no conflicts were identified at this time." becomes a medium set-level conflict.
- **WP-10 steps 6, 7 and 9:** entries lacking loss metadata must stay servable (loss = unknown). Invalidating `stage=review_plan` re-authors plans → new `profiles_key` → critique L1+L2 misses on every sheet. The review's root-cause fix (state the 60-item total in `PLANNER_SYSTEM_PROMPT`) re-keys `PLANNER_PROMPT_VERSION` with the same cascade: bundle it and record it in the migration table. `sanitize_plans` returns one int; per-reason counts need a signature change.
- **WP-12 step 3:** also name `set_identity._sheet_block (268)` (windows are built from capped text), the hints in `build_identity_user_text (317)`, the union at `identify_set (578)`, and the cited-side span in `reconcile_cited_editions (497)`. `identity_cache_key` has no host-contract term yet stores the regex-unioned record, so host-only harvest/union changes need one or warm runs replay the stale union (I-7).
- **WP-12 step 5** conflicts with the Phase B two-tier trust documented in CLAUDE.md and with the zero-API auditor battery, which runs without an identity. The citation-shape-filtered `_basis_edition_claims` adoption statements are legitimately text-grounded. Label only the loose, citation-shaped harvest as "mentioned" (split by `_SECTION_AFTER_RE`) in the union, context block and editions line; do not declare every regex hit a non-adoption.
- **WP-12 step 7 misses these consumers:**
  - `pipeline._combine(identity=…)` (~3989): the combined_text section, which is exported and saved by the GUI.
  - `CitationAssessment.adopted_edition` (`models.py:1136`, filled from `merged_editions` at `citation_check.py:1198/1218/1268`), labelled "adopted" in `html_report.py:934` and in the findings CSV (`export.py:972/1083`).

  Any new `SetIdentity`/`AdoptedCode.to_dict()` field changes `review_planner._identity_hash`. That re-keys the planner and cascades into the critique, even for cached identities. Fold new fields only when non-default (the `profiles_key` precedent), or budget one critique re-read.
- **WP-12 step 4:** add a family alias table shared by `_EDITION_RE`, `_basis_edition_claims` and `_family_year_re` (CBC ≡ CALIFORNIA BUILDING CODE, T24 ≡ TITLE 24). Without it, "2022 CALIFORNIA BUILDING CODE" never matches a ref "CBC 2019 §1004". Every grammar change is model-visible (identity windows and hints, and the editions line inside `_citation_payload_hash`), so it re-keys identity, planner and citation for the affected sets.
- **WP-12 step 1:** keep the fix citation-local; `digest._FENCE_RE (881)` is not line-anchored, so a `""` join keeps fence detection.
- **WP-13 steps 1, 3, 7 and 8:** `INVESTIGATE_PROMPT_VERSION="investigate-v3"` (line 95) is a **manual** literal, pinned by `test_the_budget_change_bumped_the_investigation_prompt_version`. Tool descriptions, initial-content text and budget strings are not hashed (`investigation_cache_key` uses schema/model/prompt/max_rounds/task_budget/payload). Bump the literal or convert it to a content hash, and put the new search budget in the key.
- **WP-13 acceptance:** "out-of-budget tools are refused before execution" **already holds** (`test_a_parallel_turn_past_the_budget_is_refused_not_rendered`, `test_a_refused_request_renders_no_evidence`). Preserve it; do not re-implement it.
- **WP-13 step 8:** filter pre-fallback blocks **before** building `requests` (1023). A declined model's `tool_use` must be neither executed, charged, answered nor echoed. Text before the boundary stays.
- **WP-13 steps 5–6:** adding `find_text` or other non-render steps to `tool_trace` requires `_replay_cached (1215)` to skip them (it demands a sha on every step) plus a cache-contract bump. R7's initial-crop half only needs the failed attempt recorded.
- **WP-14 step 5:** citation is inherently mixed-TTL, because the API adds 5-minute writes after server-tool results. The phase-policy fallback therefore over-prices citation. Require:
  - `usage.cache_creation.ephemeral_5m/1h_input_tokens` read in `digest._message_cache_usage (774)` and its inline copies (digest, critique, batch_digest, investigate);
  - split, additive `UsageRecord` fields and matching per-TTL pricing in `usage_record_cost`;
  - `FakeUsage.cache_creation` (WP-02).

  Fix the stale `core/pricing.py:35–39` comment.

## 3. Missing items to add

- The synthesis negation defect and the prose-match signature veto from §2 (both reproduced; neither is in the plan).
- `investigate._sheet_id_map (498)` first-wins binding of duplicate detected ids (traced).
- `find_text` calls are absent from investigation.json.

## 4. Session slicing (reproduced defects first)

**WP-09 (~2.5 sessions)**
- 9.1 S, boilerplate plus synthesis-negation filter (B11). Files: `prose_harvest.py`. Tests: `tests/test_drawing_ledger.py`. Depends on: none.
- 9.2 M, signature-aware match, per-item outcome counters and a labelled paraphrase corpus, with no threshold change (§4 Jaccard). Files: `prose_harvest.py`, manifest accounting. Tests: `test_drawing_ledger.py`, `test_drawing_usage.py`. Depends on: WP-04 N1 slice, 9.1.
- 9.3 S, terminal-state gate on structuring cache writes (step 6). Tests: `test_structured_outputs.py`. Depends on: WP-01 outcome classifier.

**WP-10 step 6 (1 session, S)**
- Planner loss metadata, with no invalidation (K4). Files: `review_planner.py`, `pipeline.py`. Tests: `tests/test_review_planner.py`, `test_drawing_qc_pipeline.py`. Depends on: the WP-01 stage-accounting decision (whether cap-trim counts as PARTIAL).

**WP-12 (~5 sessions)**
- 12.1 S, contiguous citation assembly and source trail (C1, C5). Files: `citation_check.py`. Tests: `tests/test_drawing_markup_rich.py`. Depends on: none (local fetch-block fixture).
- 12.2 M, evidence text and em dash across harvest, basis, reconcile and identity windows, plus the identity contract term (C2, C6). Files: `citation_check.py`, `set_identity.py`, `digest_cache.py`. Tests: `tests/test_edition_audit.py`, `tests/test_set_identity.py`. Depends on: a DECISIONS migration row.
- 12.3 M, code-family grammar and alias table (§4 `_CODE_TOKEN`). Same tests. Depends on: 12.2.
- 12.4 S, contextual window ranking (H4). Tests: `test_set_identity.py`. Depends on: 12.2.
- 12.5 M/L, mentioned versus adopted end-to-end (§4 regex-as-adopted). Files: `models.py`, `set_identity.py`, `citation_check.py`, context renderers, `pipeline._combine`, `html_report.py`, `export.py`. Tests: `test_set_identity.py`, `test_edition_audit.py`, `test_drawing_html_report.py`, `test_drawing_export.py`. Depends on: 12.2–12.4, the WP-10 migration register and the integration owner.
- 12.6 S, terminal and coverage gate before verdict-cache writes (step 8). Tests: `test_drawing_markup_rich.py`. Depends on: WP-01.

**WP-13 (~4 sessions)**
- 13.1 S, narrow the latch markers, canonical sheet ids and ambiguity rejection (§3.2, `_norm_id`). Files: `investigate.py`. Tests: `tests/test_drawing_investigate.py`. Depends on: none (bump the prompt version if index text changes).
- 13.2 M, evidence finalization on every exit, saved/sent/judged states, and `find_text` in the trace (R7). Files: `investigate.py`, `models.py` (additive `Verification` fields). Same tests. Depends on: the DECISIONS evidence-ownership contract.
- 13.3 M, separate search and image budgets, honest wording, key and version bump (C4). Files: `investigate.py`, `digest_cache.py`. Same tests. Depends on: 13.2.
- 13.4 M, `max_tokens` raised-cap turn retry without re-executing tools, and the fallback-boundary replay and execution filter (§4 items). Same tests. Depends on: WP-01 and a WP-02 fallback-block fixture.

**WP-14 step 5 (1 session, S/M)**
- TTL-split cache-write accounting (C3). Files: `digest.py`, `citation_check.py`, `investigate.py`, `pipeline.py`, `models.py` (`UsageRecord`), `core/pricing.py`. Tests: `tests/test_drawing_usage.py`, `test_drawing_markup_rich.py`. Depends on: `FakeUsage.cache_creation` from WP-02.
