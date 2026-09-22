> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-14, WP-15, WP-22. The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

## FINAL REPORT — cost-usage-config (HEAD = 1.7.0 code)

Method: re-ran the prior scratch scripts and added path_scrub2.py and critique_tag3.py; the rest was traced.

### 1. Verdicts

| ID | Verdict | Current anchor(s) | Evidence | Plan correction |
|---|---|---|---|---|
| $1 | STILL PRESENT (traced) | cost.py::_ASSUMED_OUTPUT_TOKENS_PER_SHEET (line 56, comment still says "16k cap"), ::_ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ (511); digest.py::DEFAULT_DIGEST_MAX_TOKENS (63), ::build_digest_request_params (690); critique.py::DEFAULT_CRITIQUE_MAX_TOKENS (122) | Both reads run adaptive thinking at effort high with 64k caps, but the constants count visible output only (2,000 / 1,500). The verify constant (519) already includes thinking. | SDK 1.7.0 reports `usage.output_tokens_details.thinking_tokens` (nothing reads it); use it for calibration. |
| $2 | STILL PRESENT (traced; sizes measured) | cost.py::_ASSUMED_PROMPT_TOKENS_PER_SHEET (53; used at 332/832/914/943); models.py::SheetCostBasis.text_chars (474) | Digest system 3,704 chars (~926 tok), critique system 3,870 (~967), framing + 36 labels 1,264 chars, text cap 15,000. text_chars is written (render.py 1066, models.py 534) but never read by cost.py or pricing. | Text also sits in the critique's cached prefix (914), not only in digest input. |
| $3 (+R6) | STILL PRESENT (reproduced) | profiles.py::preflight_scan (291 → iter_sheet_prescan at 309); render.py::iter_sheet_prescan (1083), ::iter_sheet_cost_bases (1006, no production caller) | 2×20 dense pages, 12.4 MB: preflight 5,323 ms; a hash-free walk producing identical ids and bases 1,374 ms; cost-only 798 ms. R6 (traced): the spool is created at pipeline.py 3055, Hybrid takes the batch branch (1548), re-renders, and closes the spool unread (3642). | — |
| §3.2 fallback provenance | STILL PRESENT (traced) | digest.py::_message_usage (763), ::_message_cache_usage (774), ::digest_sheet cache.put (1710); models.py::UsageRecord (2306); api_config.py 1317 comment | Nothing reads .model, iterations, stop_details, fallback_credit or cache_creation. Cache payloads and usage records carry only the requested model. Refused-partial billing: CANNOT DETERMINE offline. | — |
| §4 redact_secrets | STILL PRESENT (reproduced) | diagnostics.py::_SECRET_PATTERNS (110-113), ::redact_secrets (120); run_journal.py::sanitize_text (186) | "a_"×n: 4k 385 ms, 8k 1.54 s, 16k 5.88 s. RedactingFormatter also redacts up to 64k before truncating (~90 s per record, extrapolated). | A possessive `*+` stays quadratic and loses ANTHROPIC_API_KEY; a `{0,8}` prefix is linear (3.5→14 ms) with equal sample coverage. |
| §4 path-scrub | STILL PRESENT (reproduced) | run_journal.py::_WIN_PATH_RE (98), ::scrub_paths (117), ::_private_root_re (154), ::redact_for_display (222) | An unquoted `C:\\Users\\…` leaks even with the root registered. `\\?\UNC\srv\share\…` leaks without any spaces. `\\?\D:\…` becomes `\\?\.../x`. With root /tmp, `/var/tmp/x.pdf` becomes `.../x.pdf`, the same as with no root. The real harm is URL/relative-path corruption: `https://example.com/tmp/g.html` → `…com.../g.html`, `docs/tmp/n` → `docs.../n`. | The review's /var/tmp example is not a visible leak. |
| §4 roll_up_qc_status | STILL PRESENT (reproduced) | models.py::roll_up_qc_status (2242) | An exhaustive config with `[]` → COMPLETE. Only expected=False stages, all FAILED → COMPLETE. Critique record missing → COMPLETE. Unreachable today (the pipeline always creates every record). | — |
| §4 config vs pipeline / critique_reads | STILL PRESENT (reproduced) | models.py::resolve_run_configuration (2104; critique_reads=2 at 2212); pipeline.py 1986-9, 2135-8; critique.py::critique_runs (137) | verify/investigate=True without markup resolves True, but the pipeline skips both stages silently. With CRITIQUE_RUNS=4, critique_runs() returns 4 and the config still says 2. The config value reaches only the journal (3598) and the manifest; execution, keys and the estimate call critique_runs() (1346, batch_critique 180, critique 1462, cost 906). | — |
| §4 Finding.from_dict refs | STILL PRESENT (reproduced) | models.py::Finding.from_dict (1309; refs at 1327) | "NFPA 13" → 7 characters; a dict → its keys; an int → TypeError. Only cache round-trips reach it (digest 1364, prose_harvest 549, cross_qc 1420). | See WP-22 step 7. |
| C3 (in WP-14) | STILL PRESENT (traced) | pipeline.py citation record (2274); citation_check.py::_check_one (855/865 send ttl 1h) | Of the 18 `_record_usage` sites, only investigate (2195) passes cache_write_ttl. | Make this the first slice. |

### 2. Plan-text corrections

**WP-14**
- Primary files: per-attempt detail is already lost inside the stage result types, before the pipeline sees it:
  - verify (one record, pipeline 2020);
  - cross-QC (one record for all shards, 3713);
  - citation (one record per stage; citation_check.py::check_citations ~1225 mixes exact search counts with a 1-per-request lower bound);
  - critique (N reads summed per sheet, 1392);
  - prose harvest.
  Steps 3–4 require per-attempt usage lists from these modules.
- Step 1: the SDK 1.7.0 stream accumulator already copies stop_details, iterations, fallback_credit and output_tokens_details into get_final_message(). GA `Usage` has no `iterations`; only calls on the beta namespace (fallback attached) do.
  - Add one reader beside `_message_usage`, which has 13 callers.
  - Store the serving model in cache payloads (digest.py 1710, critique.py 1535, batch_digest.py 2136) as an additive field where absent means unknown, with no `_SCHEMA_VERSION` bump. Record this as a decision: I-6's wording would force a bump that discards every paid entry.
- Step 4: express "unknown" by extending the single rule `RunUsage.is_billable_but_unpriced`; CLAUDE.md forbids restating it. Token fields default to 0 and the readers turn None into 0, so a nullable/known flag is needed. Decide how `by_model` groups (serving vs requested); the A/B harness consumes it.
- Step 5: `usage.cache_creation.ephemeral_5m/1h_input_tokens` exists. UsageRecord and `usage_record_cost` hold one TTL and one write count, so they need splitting. No request mixes TTLs today (investigation 1h; digest/critique 5m).
- Step 7: the site is core/api_config.py::_dispatch_messages (`with stream: return get_final_message()`). Capture `current_message_snapshot` on the exception and thread it through digest_sheet's retry loop (~1633-52), which currently keeps only earlier attempts' usage.
- Step 8 is mostly done (manifest `pricing_effective_date` at export.py 614; exhaustive dialog at cost.py 1111). Still missing from the standard dialog, the report usage table and run.log.
- The regression matrix needs WP-02 fakes:
  - FakeUsage cache fields default to **0, not None**, and it has no iterations, cache_creation or output_tokens_details.
  - FakeMessage.model is hardcoded "claude-opus-5" and there is no stop_details.
  - FinalMessageStream cannot fail mid-stream.

**WP-15**
- Step 7 is consistent with CLAUDE.md's measured "no second scan" decision: one walk, dropping only the render identity the preflight discards anyway. The review's literal fix (use iter_sheet_cost_bases) would conflict, because it has no words and so cannot produce sheet ids. To reconcile:
  - Add an identity-free iterator (`_sheet_geometry_no_render`, per-file fault isolation, `assign_source_ids` over the whole list).
  - Keep iter_sheet_prescan for the L1 cache.
  - Re-measure scripts/measure_scan_time.py and update the CLAUDE.md numbers.
  - The current per-path call gives every basis SRC-0001 (latent bug).
- Step 1 is largely done: resolve_stage_models (631), the transports, critique_runs() (906) and per-model image caps. Only retry policy and schema mode remain.
- Step 3: manifests sum N reads per sheet and hardcode critique_reads=2, so per-read calibration depends on WP-22 step 4 as well as WP-14.
- Step 5: "not a cap" is already asserted in tests/test_cost.py. Retries and pending charges (WP-17) remain.
- Steps 2, 7 and 8 have no dependencies; schedule them early. WP-16 is not an estimator dependency.

**WP-22**
- Step 1: the fix must also cover RedactingFormatter (elide → redact → truncate at 64k). Write the acceptance test as an absolute bound (a 64k chain in under 0.5 s), not a growth ratio.
- Step 2: "boundaries on both sides" is wrong for the left side. The missing left boundary is exactly what fully scrubs `/mnt/backup/home/abe/Client Jobs/x.pdf` with root `/home/abe/Client Jobs` (→ `.../x.pdf`; with no root, `.../Client Jobs/x.pdf`). Instead:
  - Mask URLs before the root pass (it currently runs before scrub_paths masks them).
  - Allow `[\\/]+` between root components.
  - Add `\\?\` and `\\?\UNC\` branches; `?` is excluded from `_WIN_PATH_RE`'s component class.
- Step 4: execution already uses critique_runs(). Name the consumers the plan misses: models.SOURCE_TAGS (750), ledger._FAMILIES (82) / _families (134) / provenance_label (100).
- Step 5: honoring verification or investigation outside markup breaks DA-013 unless they join `any_paid_expert` (models.py ~2195). Two tests lock today's behavior: test_explicit_investigate_true_is_honored_and_keeps_the_free_battery and test_expert_stage_without_qc_markups_runs_but_stays_non_exhaustive.
- Step 6: needs a map from RunConfiguration to required stage names (digest, identity, review_plan, profiles, critique, cross_qc, synthesis, auditors, prose_harvest, edition_audit, verification, investigation, citation, markup). test_rollup_clean_run_is_gated_to_partial_when_gate_closed and test_rollup_debug_override_is_partial_even_when_clean pass partial lists and must be rewritten. Coordinate with WP-01 (N5).
- Step 7: the live model path is digest.py::_coerce_refs (1114), used by digest, critique and harvest via `_validate_finding_item`, and by cross_qc (650/809). It **drops** a bare-string ref. set_identity._as_list (334, also review_planner 287) keeps it as one element, and from_dict splits it: three coercions that disagree. Put the shared helper in models.py (set_identity imports models, so the reverse would cycle). Stored parsed findings change, so add a WP-10 migration note.
- Step 8 stale items: cost.py 54-55 and critique.py 118 ("16k"), the token_count_preflight_enabled docstring, and count_tokens_via_api (no callers).

### 3. Missing items
1. **The GUI preflight never runs in a default install** (traced; empty HOME). gui.py::_refresh_profile_suggestions (1458) returns early when `_profile_vars` is empty (1466). That dict is filled only from list_profiles(), which returns [] because no profiles ship. _apply_profile_suggestions (1511) is the only writer of the bases. So both dialogs (1755, 1828) always price conservatively and text_chars is never available. Add to WP-15 step 7.
2. **DRAWING_ANALYZER_CRITIQUE_RUNS≥3 fabricates corroboration** (reproduced). The `critique_3` tag (critique.py 1505, batch_critique.py 362) is in neither SOURCE_TAGS nor _FAMILIES. Merging critique_1 with critique_3 in the ledger gives reproduced=True, REPRODUCED and "critique+critique_3"; critique_1 with critique_2 stays SINGLETON. Add to WP-22 step 4.
3. **Unlocked concurrent PyMuPDF use** (traced). render.list_sheets runs on the UI thread (gui 1745, 1822) outside `_preflight_lock` while the preflight worker walks pages. Fixing item 1 makes this the default path.

### 4. Session slicing

**WP-22 (≈4 sessions)**
1. Redaction + path scrub. Closes: §4 redact, path. Files: diagnostics.py, run_journal.py. Tests: test_diagnostics.py, test_run_journal.py. Depends on: none.
2. Critique read count resolved once + critique_N families. Closes: critique_reads, missing item 2. Files: models.py, pipeline.py, critique.py, batch_critique.py, ledger.py, cost.py. Tests: test_run_configuration.py, test_drawing_ledger.py, test_cost.py. Depends on: none (coordinate with WP-03 on ledger).
3. Shared refs coercion. Closes: from_dict, the `_coerce_refs` drop. Files: models.py, digest.py, set_identity.py, review_planner.py. Tests: test_drawing_models.py, test_drawing_findings.py, test_set_identity.py. Depends on: WP-10 note.
4. Configuration matrix + required-stage roll-up. Closes: config vs pipeline, rollup holes. Files: models.py, pipeline.py. Tests: test_run_configuration.py, test_drawing_acceptance.py. Depends on: WP-01.

**WP-14 (≈6 sessions)**
1. Citation TTL, derived inside `_record_usage`. Closes: C3. Files: pipeline.py, core/api_config.py. Tests: test_drawing_usage.py. Depends on: none.
2. Shared response-metadata reader + fakes. Files: digest.py and its 13 callers, fixtures/fake_anthropic.py. Tests: test_drawing_usage.py. Depends on: WP-02.
3. UsageRecord v2 + pricing + unknown-usage rule + manifest/report/run.log. Files: models.py, core/pricing.py, pipeline.py, export.py, html_report.py. Tests: test_drawing_usage.py, test_run_journal.py. Depends on: slice 2.
4. Per-attempt records from stage result types. Files: verify, cross_qc, citation_check, critique, prose_harvest, identity/planner/synthesis/focus. Tests: test_drawing_usage.py plus each stage's tests. Depends on: slice 3, WP-01.
5. Batch canceled envelopes + partial-stream usage. Closes: R3, step 7. Files: batch_digest.py, batch_critique.py, api_config.py. Tests: test_drawing_batch.py, test_drawing_batch_critique.py. Depends on: slice 3, WP-02, WP-17.
6. Serving model through caches and manifest. Closes: §3.2. Files: digest.py, critique.py, batch_digest.py. Tests: test_drawing_usage.py. Depends on: slices 2–3, WP-10.

**WP-15 (≈5 sessions)**
1. Hash-free, profile-independent, lock-safe preflight. Closes: $3, missing items 1 and 3. Files: profiles.py, render.py, gui.py, measure_scan_time.py, CLAUDE.md. Tests: test_cost_confirmation_scan.py, test_drawing_profiles.py. Depends on: none.
2. Hybrid spool. Closes: R6. Files: pipeline.py. Tests: test_render_spool.py, test_critique_input_order.py. Depends on: none.
3. Text and prompt overhead per stage. Closes: $2. Files: cost.py. Tests: test_cost.py, test_cost_geometry.py. Depends on: slice 1.
4. Reasoning-inclusive output bands + calibration script/fixture. Closes: $1. Files: cost.py, scripts/. Tests: test_cost.py. Depends on: WP-14 slices 3–4, WP-22 slice 2.
5. Call-plan scaling (cross-QC shards, stragglers, retries, investigation) + pending-charge wording. Files: cost.py, gui.py. Tests: test_cost.py. Depends on: slice 4, WP-17.
