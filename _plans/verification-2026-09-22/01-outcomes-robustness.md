> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-01, WP-10 (K1, K3, N4 cache), WP-11, WP-18. The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# FINAL REPORT (complete; supersedes line anchors in the checkpoint notes above where they differ)

## 1. Verdicts (HEAD = 1.7.0; scratch repros in scratchpad/verify/outcomes-robustness/)

| ID | Verdict | Current anchors | Evidence | Plan correction |
|---|---|---|---|---|
| N4 | STILL PRESENT (reproduced) | `digest.py::digest_sheet` (1530; ladder 1684-1695; put 1710); `batch_digest.py::_digest_from_message` (2099; 2119-2129; put 2136); `critique.py::outcome_from_message` (1163; stop_reason read only for empty body, 1206); `models.py` FINDINGS_PARSE_OK (817, includes PARSED_UNCLOSED) | Refusal+text → ok, cached L2 and L1 (`pipeline.py` 3103), warm rerun clean; batch identical. Critique max_tokens (unclosed or closed-then-cut) and refusal → COMPLETE, 2/2 reads, cached (critique 1531; batch_critique 566-570; L1 `_ingest_miss`) | §2 WP-01/WP-10 |
| N5 | STILL PRESENT (reproduced end-to-end via `extract_drawing_context`) | `pipeline.py::_run_qc_stages` ladder 2093-2124 (`judged = verified + rejected + uncertain`, 2097); `verify.py::VerifyResult` (757; `not_judged` 809; `degradation_note` 813) | All-malformed, all-HTTP-failed, 1 verified + 4 skipped → verification COMPLETE and run qc_status COMPLETE; degradation is only a warning | — |
| R1 | STILL PRESENT (reproduced) | `render.py::list_sheets` (128; skip 150-153); `::iter_rendered_sheets` (901; open 932); `::iter_sheet_prescan` (1083; open 1122; per-page 1124-1143 unguarded, no error callback); `pipeline.py::extract_drawing_context` 2894-3106 no try | Second PDF unlinked after `inspect_inputs` → FileNotFoundError aborts run (1 paid digest discarded; cache/prescan path too). Batch: `submit_drawing_batch` propagates with 5 uploads, 0 deleted | WP-11 |
| R2 | STILL PRESENT (reproduced) | `batch_digest.py::_item_retry_params` (595; refusal falls to `return None` 647); `pipeline.py::_digest_sheets_via_batch` `recovery_transport=RECOVERY_BATCH` (1027) | Empty refusal envelope → failed sheet, 1 submit, 0 rescues under both RECOVERY_BATCH/DIRECT | Move from WP-17 s8 to WP-01 |
| R3 | STILL PRESENT (reproduced), broader than stated | `batch_digest.py::_harvest_abandoned_batch` (803; `responded.add` 896); `::_parse_item` (2173); exclusions 1243-1245 / 1520-1522 / 2429-2431 | Canceled envelope → responded, nothing parked, ledger `[(2,BATCH,COMPLETE)]`. Terminal path too: errored primary → resubmit OK → attempt 1 absent | Fix in `_parse_item` (non-billable attempt per non-succeeded envelope), not only "responded = succeeded" |
| R6 | STILL PRESENT (reproduced, component) | `pipeline.py` spool 3055-3070; `_run_critique_stage._rendered_for_critique` batch branch 1549-1566 | Hybrid call shape: 0 spool pops, every page re-rendered | — (WP-15 s8) |
| K1 | STILL PRESENT (reproduced) | `render.py` 870; `tiling.py::position_label` (313); `digest.py::build_user_content_blocks` 631-640; `digest_cache.py::digest_cache_key` (131); `render.py::sheet_render_identity` parts 656-676 | Reworded label changed request text; L1 and L2 keys unchanged. Comment `digest.py` 332-334 falsely says covered | WP-10 s2 |
| K3 | STILL PRESENT (reproduced) | `pipeline.py::_run_critique_stage._ingest_miss` (1424; key 1448-1463); `::_critique_level1_partition` probe 1260-1276; `batch_critique.py` `structured=False` 358, L2 key 240-250 | Env flag on + batch → fenced merge stored only under STRUCTURED L1 key | WP-10 s4/s7 |
| `_message_text` "\n" join | STILL PRESENT (reproduced) | `digest.py::_message_text` 753-761 (imported by 11 modules) | `[text, fallback, text]` → "12\n inches"; boundary inside findings JSON → MALFORMED_CLOSED, 0 findings (unsplit: 1) | WP-01 must own it |
| `response.model`/`usage.iterations` unread | STILL PRESENT (traced) | zero reads (grep); `core/api_config.py` comment 1317; cache entries store no serving model | Docs: top-level usage = returning attempt only; `iterations` is billing truth → mid-stream-declined partial uncounted | — (WP-14) |
| `stop_details` unread | STILL PRESENT (traced) | zero reads in src/ | — | Log in R2 slice |
| 404 inline fallback past size limit | STILL PRESENT (traced); Economy reachability reproduced | `batch_digest.py::submit_drawing_batch._serve_inline` (1656; calls 1747-1748, 1797-1803) → `digest_sheet`/`build_user_content`, no size check anywhere | RECOVERY_BATCH shape: 3 real-time calls, 0 batches, transport REAL_TIME. Code itself says inline > 32 MB on dense sheets (file_upload.py 1-12; pipeline.py 2605-2609); measured (inline_size.py): synthetic dense 42×30 in vector sheet → 37 images, 38.1 MB PNG, 50.8 MB inline request JSON | WP-18 s5 |
| Upload hygiene | STILL PRESENT (traced) | `batch_digest.py::_release_uploaded_files` (271; daemon `_run_in_background` 266; callers pipeline 1025/1607/3664); `file_upload.py::delete_files` (486, swallows all); `RUN_FATAL_UPLOAD_STATUSES` 90 / `INLINE_FALLBACK_UPLOAD_STATUSES` 99; no `files.list` | Files API docs: persist until deleted, 100 GB/org — code/help claim "expire server-side" | WP-18 |
| Prune reaps live dir | STILL PRESENT (reproduced) | `pipeline.py::_prune_stale_work_dirs` (177; call 2771); `_tree_is_recent` (135) | Peer run's `drawing_qc_*` idle >25 h → deleted | WP-18 s6 |

## 2. Plan-text corrections

**WP-01**
- s1/s2: reuse `verify.py::_verdict_from_response`/`_degrade_kind` (257/301), already stop-reason-first; verify is not an N4 site. Consumers with zero `stop_reason` reads, several caching: `review_planner.py` (put 543), `set_identity.py` (put 586), `synthesis.py`, `focus.py`, `prose_harvest.py`; `cross_qc.py` checks only empty (1053).
- s3: fix sites are `digest_sheet` (also behind `_serve_inline`) and `_digest_from_message` (also behind `_rescue_failed_items_sync`); the L1 put (`pipeline.py` 3103) is covered only if the fix sets `error`. Unnamed consumer: `_run_qc_stages` 1734-1735 ingests findings from errored digests, so truncated/refused partial findings reach the ledger and ink unlabeled. State the existing delivery contract: `_combine` (740) drops errored prose from `combined_text`; `export._sheet_document` (120) keeps it under FAILED.
- s4: single fix site `outcome_from_message` (RT, batch, L1, L2 all flow through it). Do not change `FINDINGS_PARSE_OK`; the digest legitimately salvages PARSED_UNCLOSED at `end_turn`.
- s5: add "a retry never loses the first read": RT falls back only when the retry raises (1644-1658); batch `_replace_result_with_attempt_history` (362) replaces wholesale. Repro: retry landing empty/refused discarded the partial prose on both transports, contradicting CLAUDE.md.
- s6/s7 are implementable with existing counters: verify's `skipped` counts only eligible-but-unjudged items (`_is_verifiable` exclusions are never counted), so COMPLETE ⇔ counted>0 ∧ skipped=0 ∧ not_judged=0 over both `vres` and `cres`.
- `_message_text` joins are assigned to WP-01 in §7.2, but WP-01 never mentions them and WP-12 s1 covers only citations. One shared helper must handle `fallback` boundaries and citation splits.
- Regressions: "stream interruption after text/complete JSON" cannot be written before WP-02 s5; `stream_message` uses `get_final_message()`, so an interruption is an exception and the partial is lost. N5 pipeline tests belong in `tests/test_drawing_acceptance.py` beside `test_a_cross_verifier_crash_is_not_a_valid_skip` (monkeypatch a `VerifyResult` tally).
- R2 lives concretely only in WP-17 s8 (a large durable-jobs feature) but is a small independent change to `_item_retry_params`/`_recover_via_batch_resubmit`; move it to WP-01. Specify gating on `stop_details.category` (null = ordinary model refusal), target model (registry fallback target; `recommended_model` when present), a retry bound shared with truncation, and cache admission for a host-swapped model (WP-14 s1 covers only server-side fallback).

**WP-10**
- s7: `digest_cache._SCHEMA_VERSION` (87) feeds all seven key builders (digest L1/L2, critique L1/L2, identity, review_plan, citation: 173/229/295/369/420/457/507); a bump discards every paid digest. Digest entries already store `stop_reason` (`cache_entry_from_digest` 1513), so migrate N4 with a read-side reject at the three loaders that force `error=None`: `digest.py` 1589-1602, `batch_digest.py` 1724-1736, `sheet_digest_from_cache_entry` 1490. That also stops L1 bypass. Critique entries (`critique_cache_entry_from_result` 1140) carry no stop_reason/contract: add a critique-only contract term (`stage=` tag precedent) or record the residual.
- s2 (K1): hash a label-format constant through `SHARED_USER_FRAMING_STRINGS`; `prompt_version` is in all four digest/critique keys. Fold it only when non-default (the `structured_key` precedent) so nothing is invalidated. Also decide `{label}` = `SheetRef.display_label` (the source filename, models.py 37-38), which is model-visible and in no key. Fix the comment at 332-334.
- s4 (K3): name `_critique_level1_partition` and `_ingest_miss`. Resolve the contract per transport (batch ⇒ fenced) for both probe and store, carry it on `CritiqueResult`, and log that the env flag is ignored on batch. Retire only structured-keyed critique entries; the flag is opt-in, so no global bump.

**WP-11**
- s2: the prescan has no error callback. A skipped prescan page leaves `miss_only` and therefore `iter_rendered_sheets(only=)`, so it vanishes silently. Require routing it to render or to a terminal per-page failure. Take the denominator from `inventory.accepted_documents[].page_count`, since `list_sheets` reopens and skips. Model the fix on `iter_region_crops` (711).
- s4: containment must (a) return the paid `results` of `_digest_sheets_concurrent`; (b) add the DA-034 outer cleanup guard missing from `submit_drawing_batch` (present in `submit_critique_batch` 417-424); (c) close `RenderedSheetSpool` (closed only at 3641) and release retained `reusable_uploads`. `help_content.py`'s "released on every exit path" is currently false.

**WP-18**
- s5: (a) the submit functions take no recovery policy (it lives on `collect_drawing_batch`), so it must be threaded from `_digest_sheets_via_batch` and `_run_critique_stage`; (b) the critique twin `batch_critique.py::_serve_realtime` (199; 288-289, 316) runs full-rate 2-read critiques on ANY upload error; (c) the existing tests that assert the fallback must flip: `test_drawing_batch.py` 914/1038/1071 and `test_drawing_batch_critique.py` 510/550; (d) the size guard belongs in the shared inline builder path, because Fast/Hybrid real-time digests and critiques send the same unguarded payload.
- s2/s3: per the Files API docs, uploads persist until deleted (100 GB/org). Correct "expire server-side" (`batch_critique.py` 27/489/616/625; `help_content.py` 1097) and "files cost nothing to store" (`_release_uploaded_files`). Every detach path is a permanent leak until a durable cleanup record exists. The quota-rejection status is undocumented; confirm it before classifying.
- s1: name the ownership hand-off `_finish_digest_uploads` (519) → sink → critique `finally` (3645-3672).
- s6: the prune matches only `drawing_qc_*`; `drawing_render_reuse_*` (`render_spool.py` 113) needs the same lease.

## 3. Missing items
- `investigate.py` echoes whole `resp.content` (1012-1030) and executes every `tool_use` in it. After a mid-output fallback the docs require omitting pre-fallback thinking and `tool_use` blocks (traced) → WP-01/WP-13.
- R3 terminal-path attempt loss, the retry-loses-first-read case and errored-digest findings ingestion (above) are not in the plan.
- R3 (WP-14) should be its own early slice: `_parse_item` emits a non-billable attempt for every non-succeeded envelope and the harvest counts `responded` only for `succeeded`. Tests: `test_drawing_batch.py`, `test_drawing_usage.py`. No dependencies.

## 4. Session slicing

**WP-01 (≈5-6 sessions)**
1. Verification completeness — N5 — `pipeline.py`, `verify.py` — tests: `test_drawing_acceptance.py`, `test_drawing_verify.py` — deps: none.
2. Terminal helper + digest admission — N4-digest, retry keeps better read, errored-digest findings, cached-refusal read filter — `digest.py`, `batch_digest.py`, `pipeline.py` — tests: `test_drawing_digest.py`, `test_drawing_findings.py`, `test_drawing_batch.py`, `test_drawing_digest_cache.py` — deps: none.
3. Critique/cross-QC terminal honesty — N4-critique — `critique.py`, `batch_critique.py`, `cross_qc.py`, `digest_cache.py` — tests: `test_drawing_critique.py`, `test_drawing_batch_critique.py`, `test_drawing_cross_qc.py` — deps: 2.
4. Batch refusal recovery under policy — R2, `stop_details` — `batch_digest.py` — tests: `test_drawing_batch.py`, `test_refusal_fallback.py` — deps: 2 (coordinate WP-14 s1).
5. Remaining consumers + fallback-aware text join — §3.2 join, investigate echo — `digest.py`, `review_planner.py`, `set_identity.py`, `synthesis.py`, `focus.py`, `prose_harvest.py`, `investigate.py` — tests: `test_review_planner.py`, `test_set_identity.py`, `test_drawing_synthesis.py`, `test_drawing_focus.py`, `test_drawing_investigate.py` — deps: 2, WP-02 s4.
6. Interrupted-stream outcomes — `digest.py` — deps: WP-02 s5.

**WP-10, owned parts (≈2-3 sessions)**
1. K3 transport-resolved critique contract + narrow migration — `pipeline.py`, `critique.py` — tests: `test_structured_outputs.py`, `test_drawing_batch_critique.py` — deps: none.
2. K1 label contract (zero-invalidation fold) — `tiling.py`, `digest.py`, `digest_cache.py` — tests: `test_drawing_cache_identity.py`, `test_drawing_digest_cache.py` — deps: none (coordinate K2 owner).
3. Admission-predicate map + migration table (s1/s7/s9) — `digest_cache.py`, docs — tests: `test_drawing_digest_cache.py`, `test_drawing_stage_cache.py` — deps: WP-01 2-3.

**WP-11 (≈3 sessions)**
1. Per-source/page isolation in iterators — R1 core — `render.py`, `pipeline.py` — tests: `test_drawing_render.py`, `test_input_inventory.py`, `test_source_mutation.py`, `test_drawing_acceptance.py` — deps: none.
2. Digest-phase containment — R1 residue, upload/spool leaks — `pipeline.py`, `batch_digest.py` — tests: `test_drawing_acceptance.py`, `test_drawing_batch.py`, `test_run_journal.py` — deps: 1 (soft).
3. Revision-checked reopen (verify/investigate/markup) — `verify.py`, `investigate.py`, `pipeline.py` — tests: `test_source_mutation.py`, `test_drawing_verify.py` — deps: 1.

**WP-18 (≈5 sessions)**
1. Economy upload-failure policy — §3.2 inline + critique twin — `batch_digest.py`, `batch_critique.py`, `pipeline.py` — tests: `test_drawing_batch.py`, `test_drawing_batch_critique.py` — deps: none.
2. Inline size guard — `digest.py`, `file_upload.py` — tests: `test_drawing_digest.py`, `test_drawing_batch.py` — deps: 1.
3. Work-dir/spool leases (+ R6 via WP-15 s8 if convenient) — `pipeline.py`, `render_spool.py` — tests: `test_work_dir_hygiene.py`, `test_render_spool.py`, `test_critique_input_order.py` — deps: none.
4. Upload error classification + truthful retention text — `file_upload.py`, batch modules, `help_content.py` — tests: `test_drawing_batch.py`, `test_help_content.py` — deps: none.
5. Durable upload ownership + bounded app-owned orphan reclaim (`files.list`) — deps: WP-17, WP-14.
