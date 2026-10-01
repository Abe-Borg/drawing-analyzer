# Trust claims ledger

Discovery completed before replacement copy was drafted. Scope: the shipped
desktop GUI and the HTML report it generates; public library differences are
called out where relevant. Reader: an AEC professional responsible for checking
and signing the review. Code, not the existing help/README, is the authority.

Counts use workflow action families: aliases share a card, with every trigger
named. Related compose/send and transport/model controls state their conditional
effects in the five rows. There are **41 user action families**, **19
automatic behavior families**, **6 destination classes** (some deliberately
open-ended), **2 default model IDs**, and **7 registered model IDs**, including
fallbacks and configurable alternatives. These are inventory counts, not caps.
Each U/A row has its own runtime card. Ordinary text editing/undo and native
file-picker Cancel are included in the relevant editing/import/export rows.
Removed Markdown/CSV buttons have dormant handlers, not shipped GUI actions.
Maintenance tools in `scripts/` are not application menu commands.

## User actions

All paths below are relative to `src/drawing_analyzer/` unless otherwise stated.
Verification: `test_runtime_inventory_is_complete` checks coverage and source
symbols; native/browser behavior is additionally tested or manually inspected.

| ID | Trigger family (all aliases) | Code: file and symbol |
| --- | --- | --- |
| U01 | Browse drawing PDFs; drop files | `gui.py: _on_browse, _on_drop, _add_pdfs, _parse_paths` |
| U02 | Edit/paste Anthropic API Key; Return; leave field; consent/decline plaintext storage | `gui.py: _on_key_changed, _persist_key`; `core/api_key_store.py: save_api_key` |
| U03 | Desktop Show / Hide key | `gui.py: _on_toggle_key` |
| U04 | Get an API key; open help/vendor/repository links | `gui.py: _render_help_body, _build_ui`; `help_content.py: GET_API_KEY` |
| U05 | Edit Per-run focus; pop out; close/Escape editor; ordinary editing/undo | `gui.py: _open_focus_popout, _sync_focus_boxes, _current_focus, _close_focus_popout` |
| U06 | Upload spec documents; accept warning; cancel picker | `gui.py: _on_upload_specs, _extract_specs_worker`; `spec_documents.py: extract_spec_documents, build_specs_text` |
| U07 | QC Markups | `gui.py: _on_qc_toggle`; `models.py: resolve_run_configuration` |
| U08 | Verified & deterministic only | `gui.py: _qc_verified_only_var, _on_process`; `models.py: resolve_run_configuration` |
| U09 | Include rejected (grey) | `gui.py: _ink_rejected_var, _on_process`; `annotate.py: write_reviewed_pdfs` |
| U10 | Reference audit | `gui.py: _reference_audit_var, _on_process`; `models.py: resolve_run_configuration` |
| U11 | Economy / Hybrid / Fast | `help_content.py: processing_transports`; `gui.py: _on_transport_toggle, _on_process` |
| U12 | Save tile images + per-tile notes | `gui.py: _save_tiles_var, _on_process`; `tile_artifacts.py` |
| U13 | Select/deselect review profiles | `gui.py: _on_profile_toggle, _selected_profiles`; `profiles.py: resolve_profile_selection` |
| U14 | Embed API key in HTML report | `gui.py: _embed_key_var, _on_save_html`; `html_report.py: _chat_bootstrap_html` |
| U15 | Clear | `gui.py: _on_clear` |
| U16 | Analyze Drawings; accept/decline cost dialog | `gui.py: _on_process, _worker`; `pipeline.py: extract_drawing_context` |
| U17 | Save HTML Report; cancel/overwrite file picker | `gui.py: _on_save_html`; `html_report.py: build_html_report` |
| U18 | Save Reviewed PDF(s); cancel folder picker | `gui.py: _on_save_reviewed` |
| U19 | Export All; cancel folder picker | `gui.py: _on_export_all, _export_all_worker`; `export.py: write_drawing_export` |
| U20 | Open Diagnostics Log | `gui.py: _on_open_log, _open_in_os` |
| U21 | Check for Updates | `gui.py: _on_check_for_updates_clicked`; `core/updates.py: check_for_update` |
| U22 | Download & Install; final install confirmation | `gui.py: _start_update_download, _on_update_download_done`; `core/updates.py: download_installer, spawn_installer` |
| U23 | Later | `gui.py: _close_update_dialog` |
| U24 | Skip this Version | `gui.py: _skip_update_version` |
| U25 | Close update window during download | `gui.py: _close_update_dialog, _on_update_download_done` |
| U26 | Help header topics; Why trust it; dossier; contents; Close/Escape | `gui.py: _build_help_buttons, _open_help_modal, _close_help_modal` |
| U27 | Collapse/expand desktop sections | `gui.py: CollapsibleSection.toggle` |
| U28 | Quit/close main app; decline/accept busy warning | `gui.py: _on_close_request` |
| U29 | Report search/category/high severity; quote groups/repeat toggles; sort; contents/sheet/evidence/PDF links; expand/collapse | `html_report.py: _JS, _finding_row_html, _sheet_card, _findings_card` |
| U30 | Report Copy all | `html_report.py: _JS` |
| U31 | Report Ask AI; close/reopen panel | `html_report.py: _CHAT_JS (fab, closeBtn handlers)` |
| U32 | Report Save key / Return; Change key; Use the report's key | `html_report.py: _CHAT_JS (saveKeyFromInput, keyAuthor handler)` |
| U33 | Report Forget key | `html_report.py: _CHAT_JS (forgetKey, forgetBtn handler)` |
| U34 | Report Show / Hide key | `html_report.py: _CHAT_JS (keyToggle handler)` |
| U35 | Send / Enter; starter question; Ask AI about selected text; dismiss excerpt | `html_report.py: _CHAT_JS (send, runTurn, onAskSelection)` |
| U36 | Report Stop | `html_report.py: _CHAT_JS (stopBtn handler, streamOnce, runTurn)` |
| U37 | Report New chat | `html_report.py: _CHAT_JS (clearBtn handler, dropStoredTranscript)` |
| U38 | Report Save conversation | `html_report.py: _CHAT_JS (saveTranscriptFile, serializeTranscript)` |
| U39 | Report Load conversation; cancel picker | `html_report.py: _CHAT_JS (loadInput handler, importTranscript)` |
| U40 | Report PDF (chat print dialog); browser print/cancel | `html_report.py: _CHAT_JS (exportBtn handler)` |
| U41 | Report move/resize panel; expand/resize composer; double-click reset | `html_report.py: _CHAT_JS (startGesture, paintCompose, saveGeo)` |

## Automatic behaviors

These include consequences of an earlier click, not merely launch-time work.
Verification: `test_runtime_inventory_is_complete`; named regression tests in
the final copy map below; manual source inspection for uncapped/provider effects.

| ID | Trigger and mechanism | Code: file and symbol |
| --- | --- | --- |
| A01 | Launch: load/migrate/normalize keys; discover profiles; reset diagnostic logs | `gui.py: __init__, _load_api_key, main`; `core/api_key_store.py: load_api_key_with_notes`; `profiles.py: load_profiles`; `diagnostics.py: configure_file_logging` |
| A02 | Launch timer: throttled update check and JSON state write | `gui.py: _maybe_auto_check_for_updates, _update_check_worker`; `core/updates.py: should_auto_check` |
| A03 | File selection: local sheet counting/estimate; profile preflight only when profiles exist | `gui.py: _refresh_summary, _refresh_profile_suggestions, _apply_profile_suggestions` |
| A04 | Analyze: inventory, source hashes, cache lookups, sequential rendering, local input guards | `pipeline.py: extract_drawing_context`; `render.py: inspect_inputs`; `render.py: iter_rendered_sheets` |
| A05 | Batch transport: parallel uploads, polling, stalled/retry/refusal follow-up batches, cancellation, background remote deletion | `batch_digest.py: submit_drawing_batch, collect_drawing_batch, _poll_until_terminal, _release_uploaded_files`; `file_upload.py: upload_sheet_images, delete_files`; `batch_critique.py: submit_critique_batch, collect_critique_batch` |
| A06 | Digest: model sheet reads and transient/output retries | `digest.py: digest_sheet, build_digest_request_params, parse_findings`; `batch_digest.py: collect_drawing_batch` |
| A07 | Set synthesis and optional focus: independent stages overlap other QC network work | `pipeline.py: extract_drawing_context`; `synthesis.py: synthesize_drawing_set`; `focus.py: generate_focus_report` |
| A08 | QC identity then review plan | `set_identity.py: identify_set`; `review_planner.py: author_review_plan`; `pipeline.py: extract_drawing_context` |
| A09 | QC critique: repeated sheet reads, merge and optional batch recovery | `critique.py: critique_sheet, critique_runs`; `batch_critique.py: submit_critique_batch, collect_critique_batch` |
| A10 | Cross-QC: small-set call or shard calls + bounded pair reconciliation | `cross_qc.py: cross_sheet_qc, _reconcile_facts` |
| A11 | Local auditors, Decimal arithmetic, anchoring, ledger merge/numbering | `pipeline.py: _run_qc_stages`; `auditors/*.py`; `anchor.py: resolve_anchors`; `ledger.py: Ledger` |
| A12 | QC prose harvest: local filtering/matching, optional model structuring of residuals | `prose_harvest.py: harvest_prose, _structure_item` |
| A13 | QC verification: saved/hashed crops, cached/model verdicts, transient retries/schema fallback | `verify.py: verify_findings, verify_cross_findings, _verify_one` |
| A14 | QC investigation: permitted local tools, saved evidence, bounded follow-up model turns, task-budget/strict-schema fallback | `investigate.py: investigate_findings, _investigate_one, _ToolExecutor` |
| A15 | QC citations: claim chunks, server search/fetch, retries/resumes, verdict cache | `citation_check.py: check_citations, _check_one, citation_tools` |
| A16 | QC reviewed copies: annotations, reopen/reconcile receipts, incomplete naming | `annotate.py: write_reviewed_pdfs, _reconcile_pdf`; `pipeline.py: _run_qc_stages` |
| A17 | Report startup/turn completion: restore/save transcript and geometry; local animation/search timers | `html_report.py: _CHAT_JS (restoreTranscript, saveTranscript, loadGeo), _JS` |
| A18 | Sent chat question: server pause resumes, parallel local tools, new API rounds; no independent question generation | `html_report.py: _CHAT_JS (buildRequest, runTurn, runTool)` |
| A19 | Run startup prunes old temp work; run exit removes spool and releases retained remote uploads | `pipeline.py: _prune_stale_work_dirs, _with_run_release`; `render_spool.py`; `batch_digest.py: _release_uploaded_files` |

## Network boundary (exhaustive route classes)

| ID | Destination / classification | Trigger, payload, authentication | Source / verification |
| --- | --- | --- | --- |
| N01 | `api.anthropic.com`; only after approved analysis or sent report question | PNG overviews/tiles/crops, bounded sheet/spec text, focus, filenames/page labels, checklists, model results, citation claims; chat sends full report and growing history/tool results. SDK key via `x-api-key`; browser direct key + `anthropic-dangerous-direct-browser-access`. `ANTHROPIC_BASE_URL` can redirect desktop SDK; proxy env/system configuration changes transport. | `client.py: new_client`; every dispatch through `core/api_config.py: _dispatch_messages`; `html_report.py: _CHAT_JS / API_URL`; `test_sdk_contract.py`, `test_trust_facts` |
| N02 | `github.com/abe-borg/drawing-analyzer/releases/latest/download/latest.json` and redirect targets; routine startup/manual check | GET with updater User-Agent and JSON Accept, network metadata/IP; no drawings/key in app-built request; no app authentication. `DRAWING_ANALYZER_UPDATE_URL` allows a different HTTPS source. Redirect hosts are not allowlisted in code. | `core/updates.py: _DEFAULT_MANIFEST_URL, fetch_manifest, manifest_url`; `test_updates.py`, `test_trust_facts` |
| N03 | Installer HTTPS URL from manifest and redirects; only Download & Install | GET installer; no project payload/key in app-built request. Expected SHA-256 comes from the same manifest; host not restricted, size/total elapsed not capped. Common GitHub release redirects may use `release-assets.githubusercontent.com`, but code does not guarantee this hostname. | `core/updates.py: parse_manifest, download_installer, _open_url`; `test_updates.py`; manual |
| N04 | SDK batch `results_url`; only batch collection/harvest | Download JSONL results through SDK; server supplies URL, not a fixed app allowlist. Same client handles authentication. Its target is a provider/SDK contract rather than a hardcoded additional app hostname. | `batch_digest.py: collect_drawing_batch, _harvest_abandoned_batch`; installed SDK `messages.batches.results`; `test_sdk_contract.py`; manual |
| N05 | Websites selected by Anthropic's server search/fetch; only citations or a sent chat question | Provider receives citation claims/context or full chat context; model chooses search queries/URLs. Source-quality blocked domains do not enforce confidentiality or an allowlist. Network work happens at provider, not a Python/browser fetch to those sites. | `citation_check.py: citation_tools, _build_citation_prompt`; `core/api_config.py: build_web_search_tool, build_web_fetch_tool`; `html_report.py: _CHAT_JS / buildRequest`; manual |
| N06 | Explicit external help, citation, README, vendor, author, release links; optional click | Built-in help hosts: `github.com`, `console.anthropic.com`, `privacy.anthropic.com`, `trust.anthropic.com`, `www.anthropic.com`, `www.gnu.org`, `www.linkedin.com`; browser redirects/navigation can change host. OS browser request to link target; browser cookies/authentication governed by browser. App does not append project/key. User-authored/model-generated links may encode project information; HTTPS validation is not a privacy promise. Further-reading links in trust UI are the only external references there. | `help_content.py: link blocks`; `gui.py: _render_help_body, _open_releases_page`; `html_report.py: _finding_row_html, _CHAT_JS / safeUrl, linkEl`; `test_report_browser_security.py`; manual |

No application socket listener, analytics SDK, crash uploader, CDN font/script,
or independent background AI job found in the runtime sources or dependency
entry points examined. This does not describe the OS, browser extensions,
corporate proxies, configured custom providers, or installed keyring backends.
The token-count helper has **no production caller** in this app. Its public
library function can send system/messages/tools to N01 if explicitly called;
it does not make GUI cost estimates exact.

## Model/settings facts

Temperature is absent from production requests; provider defaults apply. Adaptive
thinking is explicit for supported default models (reasoning tokens share output
caps). Effort means how much reasoning the request asks for. Caps are per request,
not run spend ceilings. All values must be read from source or pinned in
`test_trust_facts`; active overrides must be distinguished from shipping defaults.

| Claim/fact | Default source (file: symbol) | Verification |
| --- | --- | --- |
| Registered IDs: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-opus-5`, `claude-sonnet-5`, `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` | `core/api_config.py: _MODEL_CAPABILITIES` | `test_trust_facts` |
| Digest: Opus default, high effort, 64,000 output; output retry ceiling 128,000; 2 app retries | `core/api_config.py: REVIEW_MODEL_DEFAULT, _PHASE_DEFAULT_EFFORT`; `digest.py: DEFAULT_DIGEST_MAX_TOKENS, MAX_TOKENS_RETRY_CEILING, DEFAULT_DIGEST_MAX_RETRIES` | `test_trust_facts`, `test_sdk_contract.py` |
| Critique: review model default; high; 64,000 output; 2 reads; configurable runs/model | `critique.py: DEFAULT_CRITIQUE_MAX_TOKENS, DEFAULT_CRITIQUE_RUNS, critique_model, critique_runs` | `test_trust_facts`, `test_drawing_critique.py` |
| Identity: Sonnet default; medium; 8,000 output | `set_identity.py: default_identity_model, DEFAULT_IDENTITY_EFFORT, DEFAULT_IDENTITY_MAX_TOKENS` | `test_trust_facts` |
| Plan/synthesis/focus: review default; high; 32,000 each | respective modules: `default_*_model, DEFAULT_*_MAX_TOKENS, DEFAULT_*_EFFORT` | `test_trust_facts` |
| Cross-QC: review default; high; 16,000; small-set threshold 40; prompt sheet text 4,000; max findings 60; map facts 40; reconcile facts 400; pair calls 64 | `cross_qc.py: cross_qc_model, DEFAULT_CROSS_QC_MAX_TOKENS, MAX_SHEETS_SINGLE_CALL, _TEXT_LAYER_BUDGET, DEFAULT_CROSS_QC_MAX_FINDINGS, DEFAULT_MAP_MAX_FACTS, MAX_FACTS_PER_RECONCILE, _MAX_RECONCILE_PAIR_CALLS`; `core/api_config.py: PHASE_CROSS_QC` | `test_trust_facts`, `test_cross_qc_grounding.py` |
| Harvest: Sonnet default; low; 8,000; source text cap 6,000 | `prose_harvest.py: harvest_model, DEFAULT_HARVEST_MAX_TOKENS, _HARVEST_TEXT_CAP`; `core/api_config.py: PHASE_HARVEST` | `test_trust_facts` |
| Verification: Sonnet default; medium; 8,000; crops 300 DPI; worker fallback 4 | `verify.py: default_verify_model, DEFAULT_VERIFY_MAX_TOKENS, verify_findings, _resolve_workers`; `core/api_config.py: PHASE_VERIFICATION` | `test_trust_facts`, `test_drawing_verify.py` |
| Investigation: Opus default; high; 16,000; 6 evidence requests; 3 pause resumes; 40,000 advisory task tokens; run count min(10 + floor(sheets/4), 40) | `investigate.py: investigation_model, _DEFAULT_MAX_ROUNDS, _MAX_PAUSE_RESUMES, _DEFAULT_TASK_BUDGET_TOKENS, _DEFAULT_MAX_INVESTIGATIONS, _INVESTIGATION_SHEETS_PER_EXTRA, _MAX_INVESTIGATIONS_CEILING`; `core/api_config.py: PHASE_INVESTIGATION` | `test_trust_facts`, `test_drawing_investigate.py` |
| Investigation crops: 72–300 DPI; overview 150 DPI; text matches 20; index 60 | `investigate.py: _MIN_CROP_DPI, _MAX_CROP_DPI, _VIEW_SHEET_DPI, _MAX_FIND_TEXT_MATCHES, _MAX_SHEET_INDEX_ENTRIES` | `test_trust_facts` |
| Citation: Sonnet default; medium; 8,000; 10 searches/4 fetches per request; fetched text 40,000 tokens; 8 claims/request; 3 pause resumes; 30-day verdict TTL | `citation_check.py: citation_model, DEFAULT_CITATION_MAX_TOKENS, _WEB_SEARCH_MAX_USES, _WEB_FETCH_MAX_USES, _WEB_FETCH_MAX_CONTENT_TOKENS, _MAX_CLAIMS_PER_REQUEST, _MAX_PAUSE_RESUMES, _DEFAULT_CITATION_TTL_DAYS` | `test_trust_facts`, `test_edition_audit.py` |
| Chat: Sonnet default; high; model output cap 128,000; context from capabilities; 8 server continuations; tool close starts only when rounds >10; 8 searches, 4 fetches, 40,000 fetched tokens PER REQUEST | `html_report.py: _chat_bootstrap_html, _CHAT_JS / buildRequest, runTurn`; `core/api_config.py: CHAT_MODEL_DEFAULT, _MODEL_CAPABILITIES` | `test_trust_facts`, `test_report_chat_tools.py` |
| No desktop/chat temperature override; no chat refusal fallback/SDK retry; browser fetch has no app elapsed timeout | request builders and `_CHAT_JS / streamOnce` | `test_trust_facts`; manual |
| SDK default host and retries 2; connect timeout 5 seconds; read/write/pool 600 seconds | `client.py: new_client`; installed Anthropic SDK defaults (release constrained by `requirements-release.lock`) | `test_trust_facts`, `test_sdk_contract.py` |

## Other numerical, storage, deterministic and audit facts

| Fact | Code: file and symbol | Verification |
| --- | --- | --- |
| Grid 6×6, overlap 8%; sheet prompt text 15,000 chars; up to 40 parsed findings and 40 numeric claims per sheet | `tiling.py: DEFAULT_GRID_ROWS, DEFAULT_GRID_COLS, DEFAULT_OVERLAP_FRAC`; `render.py: SHEET_TEXT_MAX_CHARS`; `digest.py: MAX_FINDINGS_PER_SHEET, MAX_CLAIMS_PER_SHEET` | `test_trust_facts`, render/tiling/findings suites |
| Spec extensions PDF/DOCX/TXT/MD; per-file and total text budgets 400,000 chars | `spec_documents.py: SPEC_FILE_EXTENSIONS, SPEC_FILE_CHAR_BUDGET, SPEC_TOTAL_CHAR_BUDGET` | `test_trust_facts`, `test_spec_documents.py` |
| Input guards 500 files / 2,000 sheets; GUI does not pass `confirm_large_set=True` | `source_registry.py: DEFAULT_MAX_FILES, DEFAULT_MAX_SHEETS, check_set_limits`; `gui.py: _worker` | `test_trust_facts`, `test_input_inventory.py` |
| Default digest workers 4; upload workers 6 and app status retries 4; cross-QC workers 3; citation workers 4 | `pipeline.py: DEFAULT_DIGEST_WORKERS`; `file_upload.py: DEFAULT_UPLOAD_WORKERS, DEFAULT_UPLOAD_MAX_RETRIES`; `cross_qc.py: DEFAULT_CROSS_QC_WORKERS`; `citation_check.py: _MAX_WORKERS` | `test_trust_facts` |
| Batch elapsed 24 hours; poll 15→120 sec after 300 sec; stop after 10 consecutive poll errors; initial stall 25 min/later 60 min; max follow-up rounds 4; harvest budget 300 sec | `batch_digest.py: DEFAULT_BATCH_MAX_ELAPSED_HOURS, DEFAULT_POLL_INTERVAL_SECONDS, DEFAULT_POLL_MAX_INTERVAL_SECONDS, DEFAULT_POLL_BACKOFF_AFTER_SECONDS, DEFAULT_MAX_CONSECUTIVE_POLL_ERRORS, DEFAULT_FIRST_BATCH_STALL_TIMEOUT_SECONDS, DEFAULT_BATCH_STALL_TIMEOUT_SECONDS, DEFAULT_MAX_BATCH_RESUBMIT_ROUNDS, DEFAULT_HARVEST_BUDGET_SECONDS` | `test_trust_facts`, batch lifecycle suites |
| Update check interval 1 day; manifest timeout 8 sec/max 65,536 bytes; download socket timeout 60 sec | `core/updates.py: DEFAULT_MIN_INTERVAL_DAYS, DEFAULT_MANIFEST_TIMEOUT, MAX_MANIFEST_BYTES, DEFAULT_DOWNLOAD_TIMEOUT`; GUI launch delay 1,500ms | `test_trust_facts`, `test_updates.py` |
| OS credential store; plaintext filename `drawing_analyzer_api_key.txt`, config then executable dir; POSIX mode 0600; verified migration may delete matching legacy files | `core/api_key_store.py: save_api_key, _restrict_permissions, _migrate_legacy_file_key`; `core/app_paths.py: API_KEY_FILENAME, api_key_paths` | `test_api_key_store.py`, `test_trust_facts` |
| Config directory platform-derived `DrawingAnalyzer`; log `logs/drawing_analyzer.log`, reset on next launch, 2,000,000-byte rotation and 5 backups | `core/app_paths.py: app_config_dir`; `diagnostics.py: log_dir, LOG_FILENAME, configure_file_logging, _MAX_BYTES, _BACKUP_COUNT` | `test_trust_facts`, `test_diagnostics.py` |
| Cache defaults `~/.drawing_analyzer/drawing_digest_cache.json`, SQLite despite suffix; persistent by default, no automatic content expiry/deletion; citation TTL is reuse validity, not erasure | `digest_cache.py: default_cache_path, persistence_enabled, DigestCache`; `stage_cache.py`; `citation_check.py: citation_ttl_days` | `test_drawing_digest_cache.py`; manual |
| User profiles `~/.drawing_analyzer/profiles`, Markdown; no built-in profiles shipped by default | `profiles.py: user_profiles_dir, builtin_profiles_dir, load_profiles`; package-data configuration and directory inventory | `test_drawing_profiles.py`; manual |
| Temp `drawing_qc_*`: later run prunes trees older than 24 hours; 0 disables; not erased on close; run spool removed on exit | `pipeline.py: _prune_stale_work_dirs, _WORKDIR_MAX_AGE_HOURS, _with_run_release`; `render_spool.py` | `test_work_dir_hygiene.py`, `test_render_spool.py` |
| Update JSON `update_check.json` and cached installers `updates/` under config; no installer retention limit | `core/updates.py: STATE_FILENAME, default_state_path`; `gui.py: _update_download_worker` | `test_updates.py`; manual |
| Chat key in memory/sessionStorage `da-api-key`; transcript localStorage `da-chat-tx-<reportId>` cap 500,000 serialized chars, no expiry; Save `chat_history.json` uncapped; geometry/browser-profile controlled | `html_report.py: _CHAT_JS / KEY_STORE, TX_KEY, TX_MAX_CHARS, TX_NAME, serializeTranscript, saveTranscript, saveGeo` | `test_trust_facts`, report chat/security suites |
| Price table date 2026-09-29; Opus default $4/$20; Sonnet $2/$10 per million input/output; batch multiplier 0.5; cache write 1.25/2; reads Opus 0.05/Sonnet 0.1; web search $0.01 | `core/pricing.py: PRICING_EFFECTIVE_DATE, MODEL_PRICING, BATCH_DISCOUNT, CACHE_WRITE_MULTIPLIER_5M, CACHE_WRITE_MULTIPLIER_1H, WEB_SEARCH_COST_PER_USE` | `test_trust_facts`, `test_drawing_usage.py` |
| Provider fallback Opus targets $5/$25; app ledger prices requested model; interrupted output can be unreported; chat meter omits search surcharge and is outside run ledger | `core/api_config.py: _MODEL_CAPABILITIES`; `core/pricing.py: MODEL_PRICING`; `pipeline.py: _record_usage`; `models.py: RunUsage`; `html_report.py: _CHAT_JS / renderUsage` | `test_response_shapes.py`, `test_interrupted_streams.py`; manual |
| Decimal arithmetic checks operation AND anchored operands/relationship; extracted provenance or model transcription kept | `auditors/arithmetic.py: audit_arithmetic, _operands_grounded, _relationship_grounded`; `models.py: NumericClaim, Verification` | arithmetic grounding/relationship suites |
| Anchors exact/fuzzy/character stream/tile/unanchored; numeric veto; visual fallback not exact text proof | `anchor.py: resolve_anchors, numbers_grounded`; `cross_qc.py: classify_quote_evidence` | `test_anchor_character_stream.py`, `test_cross_qc_grounding.py` |
| Origin tags and conservative dedup; findings kept apart from model prose; partial/refused read exclusion and recorded discards are limits on completeness | `ledger.py: Ledger`; `models.py: Finding, StageResult`; `digest.py: parse_findings, is_partial_read, keep_digest_read`; `prose_harvest.py` | ledger/terminal outcome/prose suites |
| VERIFIED/REJECTED are model crop verdicts; UNCERTAIN/UNVERIFIED/UNANCHORED have different meanings; COMPLETE measures configured stages, not engineering correctness | `verify.py: _parse_verdict_with_validity, _is_verifiable`; `models.py: roll_up_qc_status, item_coverage_status`; `html_report.py: _finding_display_status` | verification/run configuration/terminal suites |
| Artifact-backed coverage: stamped annotations reopened; receipts/INCOMPLETE filenames; not a proof that defect coverage is complete | `annotate.py: write_reviewed_pdfs, _reconcile_pdf`; `models.py: MarkupReceipt`; `pipeline.py: _run_qc_stages` | `test_drawing_markup_coverage.py` |
| Export: Markdown, findings JSON/CSV, sheet_text, evidence PNG/request/investigation records, profiles/plan, run.log/manifest, markup manifest, reviewed PDFs, optional tiles | `export.py: write_drawing_export`; `run_journal.py: RunJournal, render_run_log` | export/run journal suites |
| Export staging/rollback protects folder publish; individual Save HTML/Reviewed can overwrite; source inputs are read but choosing their path as export can overwrite them | `export.py: write_drawing_export`; `gui.py: _on_save_html, _on_save_reviewed`; `annotate.py: write_reviewed_pdfs` | export suite; manual |
| Model data HTML escaped/safe DOM/HTTPS links/CSP; imported transcripts do not replay tools; prompt tags do not prevent reasoning manipulation | `html_report.py: _esc_attr, _CHAT_JS / replayAssistant, safeUrl, linkEl, runTool`; `digest.py: build_digest_request_params` | `test_report_browser_security.py`, `test_report_chat_tools.py` |
| Log secret-pattern redaction and basename journal scrub; drawing content/cache/artifacts not generally anonymized/encrypted | `diagnostics.py: RedactingFormatter, redact_secrets`; `run_journal.py: redact_for_display`; `digest_cache.py`; `export.py` | diagnostics/journal/browser security suites; manual |
| Local deterministic work: import, estimation, rendering, source hashes, cache keys, auditors, anchoring, merging, numbering, annotations, receipt checks, exports, report navigation/transcript replay; reusable cached model results still have model origin | modules above | corresponding existing regression suites; manual |

## Findings and consistency decisions (behavior left unchanged)

- Existing trust help said vector text prevents misreading digits, that every
  quote anchors, and nothing is dropped. Extraction is not semantic validation;
  model reads/parsers/filters/caps can omit content. Replace with narrower claims.
- Existing help said originals cannot be overwritten. The pipeline writes
  copies, but export/file picker destinations are user-controlled and lack an
  exhaustive source-path exclusion. Describe default output, not an absolute.
- Existing help said there is one project-data destination and search never
  includes drawing content. Citation user text includes claims/quotes; provider
  search and chat are model-directed. Name server web tools and overrides.
- Existing help's stage table fixed investigation at 10/run and implied one
  cross-QC/verification call. Investigation scales, cross-QC shards and model
  calls retry/resume. Remove fixed-total claims.
- Analysis has no Stop, save/load project, or application-level undo. Closing
  loses in-memory outputs and does not guarantee remote batch cancellation.
- Updater HTTPS is not a host allowlist or signature check; expected hash comes
  from manifest; redirects can change host. Download has no size/total time cap;
  dismissing its dialog does not abort its worker.
- SDK layered retries and refusal fallbacks can increase work; task-budget
  rejection removes an advisory budget; no global dollar limit exists.
- Remote deletion is best effort and exceptions are swallowed. Failed cancel
  can retain files/batches. No promise of immediate provider erasure.
- Cache persists without expiry; temporary evidence survives close until a later
  prune; chat persists until New chat/browser deletion. Clear does not erase them.
- `file://` browser storage is not per-file isolation; Forget falls back to an
  embedded author key. Browser session storage is not a guaranteed disk-free vault.
- App estimates are not bills: requested-model fallback pricing can understate
  spend; incomplete stream usage and chat web-search fees can be absent.
- `core/tokenizer.py`/`api_config.py` comments promise a token-count preflight,
  but the helper has no production caller. GUI estimates stay local estimates.
- Default profiles directory ships empty; profile preflight therefore does not
  normally sharpen geometry pricing. Existing CLAUDE.md already records this.
- SECURITY.md's absolute transcript-key guarantee is broader than its `sk-ant-`
  pattern scrub; revise the prose to name that pattern and provider-key exception.
- Report transcript replay and DOM rendering are guarded; security does not
  establish correct engineering advice or block prompt injection at the model.
- Chat's local tool limit compares `toolRound > MAX_TOOL_ROUNDS`, allowing an
  extra tool-bearing round; search/fetch ceilings restart for every request.
- README's grouping claim agrees with an HTML comment but not the sort handler:
  `_JS / sortBy` does not recompute repeat groups. Copy must name the exception.
- Attached specifications have an audit gap: `gui.py: _extract_specs_worker`
  extracts text; `pipeline.py: extract_drawing_context` receives that text, not
  original spec-file fingerprints. `export.py: build_export_documents,
  write_drawing_export` does not archive original specs or a separate spec-text
  artifact. The provenance table distinguishes drawing hashes from these inputs.
  Verification: manual exporter/worker inspection; `test_generated_docs_match_content_and_ledger`.
- Batch submission is not wholly non-AI work: upload/poll/cancel/delete do not
  request a model answer, but submit/recovery items start digest/critique models.
  A05 explicitly separates those branches; U35 separates local composition from
  sending a question. Sources: A05/U35 above; verification: `test_runtime_inventory_is_complete`; manual.

## Copy-to-source map

Added after discovery as copy is implemented. Every authored paragraph/table row
and runtime card must identify ledger IDs above. Numerical facts are resolved
from the source symbols above or pinned to literal request code by
`test_trust_facts`. SVG coordinate numbers and UI layout dimensions are visual
geometry, not behavioral promises.

<!-- BEGIN GENERATED TRUST COPY MAP -->
Every statement below maps to the file/symbol evidence in its inventory rows above. Verification: `test_runtime_inventory_is_complete`, `test_trust_facts`, `test_generated_docs_match_content_and_ledger`; non-numerical mechanism claims also require manual source inspection. Generated with `scripts/write_trust_docs.py`.

| Copy ID | Factual copy (including each table row) | Source ledger IDs |
| --- | --- | --- |
| S00 | The design assumes you check the review, so it records origins, uncertainty and evidence instead of treating a model's answer as approval. | A06, A11, A13, A16 |
| S01 | You can separate findings from their origins: Prose is model-authored. Findings keep origin tags, quotes, locations and check results in the ledger — the exported list you can inspect. An origin tag is not proof. | A06, A11, A12 |
| S02 | Local checks support specific claims with evidence: Text checks and quote matching run locally. Decimal (base-ten) arithmetic checks transcribed equations; DETERMINISTIC status requires matching the numbers and relationship to the drawing. Models can still misread or miss content. | A10, A11 |
| S03 | Uncertainty and rejected findings have separate labels: Model crop checks label findings VERIFIED, REJECTED or UNCERTAIN; missing locations are UNANCHORED. An inconclusive check does not prove a finding false. Rejected findings remain in the ledger/index. | A13, A16 |
| S04 | Saved annotations are checked against the plan: The writer stamps required marks, reopens the PDFs and compares receipts with the plan. Missing required marks make coverage INCOMPLETE; this checks saved marks, not whether every defect was found. | A16 |
| S05 | Approved work can continue without another click: Launch loads keys/profiles/logs and may check GitHub for updates; that check can be disabled. Selection helpers and chat autosave also run automatically. Approved reviews and sent questions start automatic calls, retries, tools and cleanup; analysis has no Stop button. | A01, A02, A05, A07, A17, A18 |
| S06 | You control the key and export choices: Keys prefer your operating system's tested credential store; a readable-file fallback needs consent. HTML omits the key by default; embedding puts it in the file. Browser storage and private project files need your care. | U02, U14, U32, U33 |
| S07 | Project data and automatic connections are described: Approved review and sent chat context go to Anthropic by default; web tools may research project-derived claims. The dossier names endpoint/proxy overrides, update redirects, installer URLs and clicked links. | N01, N02, N03, N04, N05, N06 |
| S08 | You can inspect evidence and estimated spending: Export All writes findings, source text, evidence, receipts and file fingerprints. Costs are estimates: interrupted usage, fallback pricing and chat search charges can be missing. Check claims against drawings and spending against your provider. | U19, U20, A11, A13, A18 |
| answer.1.1 | Your sources and the model's proposals are different | A06, A11, A12 |
| answer.1.2 | You supply drawings, specifications and optional focus/checklists. A model is the provider's AI system; it authors report prose. Findings record origin tags and evidence/status separately. A tag tells you which channel supplied a finding, not whether it is right. | A06, A11, A12 |
| answer.2.1 | Approving work starts automatic follow-ups | A01, A02, A05, A18 |
| answer.2.2 | No independent AI review starts at launch. Update checks and local startup work do. Once you approve Analyze or send a chat question, model calls, retries, tool rounds and cleanup can continue without another click; the runtime cards name them. | A01, A02, A05, A18 |
| answer.3.1 | You can inspect the evidence, not rederive every judgment | A11, A13, A16, U19 |
| answer.3.2 | Local arithmetic, anchors and receipt counts can be checked against source text/images and exports. Model judgments are probabilistic: you can review their evidence, but repeating the request need not reproduce the judgment. Human sign-off remains your job. | A11, A13, A16, U19 |
| origins.1.1 | A hash is a fingerprint of saved file bytes, not a truth certificate. JSON is a structured text format you can open in a text editor; Markdown is readable text with heading/list notation. Decimal means base-ten arithmetic. SQLite is the local database format used by the cache, which stores results for reuse. | A04, A11, U19 |
| origins.2.1 | Origin · What it actually is · How you can tell | A04, A06, A08, A11, A13, A15, A18, U19 |
| origins.2.2 | You · Selected drawings/specs; typed focus; selected Markdown profiles. · Drawing inventory/hashes, focus/configuration, profile snapshots and sheet_text files in Export All. Attached specifications are not archived as separate source files/text with original-file hashes; keep your own copies. | A04, A06, A08, A11, A13, A15, A18, U19 |
| origins.2.3 | Built-in rules · Text auditors, grounded Decimal arithmetic, location/merge/numbering rules and annotation templates. · Finding origin tags, operand_origin/computation_method, anchor and markup receipt fields; source code. | A04, A06, A08, A11, A13, A15, A18, U19 |
| origins.2.4 | Model proposal · Sheet prose, findings, identity, authored review plan, summary/focus, crop/citation judgments and chat answers. · Prose sections, finding sources, review_plan.md/profile source, verification/citation fields and Ask-AI labels. | A04, A06, A08, A11, A13, A15, A18, U19 |
| origins.2.5 | Retrieved web material · Search snippets/fetched pages selected by server tools; relevance/edition may be wrong. · Citation assessments/evidence URLs and chat citation/tool chips; not every intermediate provider step is logged. | A04, A06, A08, A11, A13, A15, A18, U19 |
| origins.2.6 | Local cache · A prior result whose cache identity/reuse rules match; origin remains its original channel. · Cache-hit/transport records in run usage; cache SQLite payloads. A cache hit is not a new independent review. | A04, A06, A08, A11, A13, A15, A18, U19 |
| origins.3.1 | Things that are not happening | N01, N05, A06 |
| origins.3.2 | The code does not add a private drawing corpus, a shared app account, an app-hosted cloud workspace, or a training job. It does supply built-in prompts/rules, and models bring their pretrained knowledge; optional web tools add outside material. Provider retention/training policy cannot be verified or enforced by this desktop code. Read your provider agreement before sending restricted work. | N01, N05, A06 |
| engine.1.1 | Shipping model defaults are claude-opus-5-5 for review work and claude-sonnet-5-5 for identity, harvest, crop verification, citations and report chat. The table shows the models resolved in this process; environment variables can change them. A token is a unit the provider uses to count text/image processing. Output caps include reasoning, not just visible words. | A06, A07, A08, A09, A10, A12, A13, A14, A15, A18 |
| engine.2.1 | Job · Model or component · Why | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.2 | Sheet digest · claude-opus-5-5; high reasoning; up to 64,000 output tokens · Read page pictures and selectable text; runs at Anthropic. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.3 | Critique · claude-opus-5-5; high reasoning; up to 64,000 output tokens · Look again for problems at Anthropic; repeated reads are compared. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.4 | Identity · claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens · Suggest discipline and governing context from bounded text; advisory. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.5 | Review plan · claude-opus-5-5; high reasoning; up to 32,000 output tokens · Propose this set's checklist at Anthropic; code bounds its structure. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.6 | Set overview · claude-opus-5-5; high reasoning; up to 32,000 output tokens · Summarize sheet digests at Anthropic, rather than reread source PDFs. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.7 | Focus report · claude-opus-5-5; high reasoning; up to 32,000 output tokens · Answer your focus from digests at Anthropic. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.8 | Cross-sheet QC · claude-opus-5-5; high reasoning; up to 16,000 output tokens · Compare sheet accounts at Anthropic; larger sets are split and reconciled. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.9 | Prose harvest · claude-sonnet-5-5; low reasoning; up to 8,000 output tokens · Turn unmatched prose items into structured findings at Anthropic. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.10 | Crop verification · claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens · Judge visible evidence at Anthropic; a crop verdict is still a model judgment. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.11 | Investigation · claude-opus-5-5; high reasoning; up to 16,000 output tokens · Ask for bounded extra drawing evidence at Anthropic. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.12 | Citation check · claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens · Research claims with Anthropic's server web tools. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.13 | Report Ask-AI · claude-sonnet-5-5; high (when supported) reasoning; up to 128,000 output tokens · Answer from the full report, history and tools at Anthropic; requests leave your browser. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.2.14 | Local machinery · Python, PDF readers, Decimal arithmetic, browser tools; no model · Render, search, compare, label and export on your computer. | A06, A07, A08, A09, A10, A11, A12, A13, A14, A15, A18 |
| engine.3.1 | Supported default models use adaptive thinking: the provider chooses reasoning length within the request cap. Requests do not set temperature, a control some models use for sampling variation. Overrides can remove unsupported thinking/effort/web tools and clamp output budgets; the table states requested stage caps, not a promise of usable output. The desktop SDK (the provider's Python client) uses its configured endpoint; the report always targets the fixed Anthropic API, its request service. | N01, A06, A18 |
| engine.4.1 | Automatic fallback is part of the engine | A05, A06, A18 |
| engine.4.2 | Supported desktop real-time requests ask for a server refusal fallback by default. The registered alternatives include claude-opus-5, claude-opus-4-8 and claude-sonnet-5; batch recovery uses declared routes too. DRAWING_ANALYZER_REFUSAL_FALLBACK=0 disables the real-time feature. The ledger may price the requested model even when a fallback served the request. The report chat does not request that feature. | A05, A06, A18 |
| boundary.1.1 | Your computer reads selected drawings and specifications, renders images, and writes local review files. Approved analysis and sent chat questions connect to Anthropic; its optional server web tools reach other websites. A dashed automatic update connection reaches GitHub and redirects. A dashed optional installer connection reaches the HTTPS host named by the manifest. Explicit further-reading links open in your browser. Batch results use a provider-supplied results URL. Desktop provider and proxy settings can change the route. | N01, N02, N03, N04, N05, N06 |
| boundary.2.1 | Leaves your machine: Approved analysis sends page PNGs (image files), bounded source/spec text, bare filenames/page labels, focus/checklists and later findings/evidence to api.anthropic.com. Report Send transmits the full report and accumulated history, with the active key in request headers. Desktop ANTHROPIC_BASE_URL and proxy configuration can change the route. Batch collection downloads the SDK's provider-supplied results_url. Citation/chat server web tools may send project-derived queries to other websites. Updates request https://github.com/abe-borg/drawing-analyzer/releases/latest/download/latest.json plus redirect targets. Download uses the manifest's arbitrary HTTPS installer URL and redirects. Explicit external links open via your browser with its own cookies and network metadata. | N01, N02, N03, N04, N05, N06, A04, U02, U19, A17 |
| boundary.2.2 | Stays on your machine: The originals remain local during normal pipeline processing; their content travels as images/text. Rendering, source hashes, local auditors, arithmetic, anchoring, merging, annotations and exports run locally. Keys are loaded/stored locally but sent to authenticate the API. Cache/log/export/evidence/transcript files stay local unless you share/sync them or software outside this app does. Folder paths are not deliberately added as API metadata, but private details present in drawing/spec text or filenames travel with that content. | N01, N02, N03, N04, N05, N06, A04, U02, U19, A17 |
| boundary.3.1 | Routes are not a closed hostname list | N01, N02, N03, N04, N05, N06 |
| boundary.3.2 | GitHub redirects, manifest-selected installer URLs, SDK results URLs, custom endpoints/proxies and provider web tools make a finite guaranteed hostname list impossible. No analytics/crash uploader, application server listener or external font/script fetch was found in the runtime code. This claim does not cover your OS, browser extensions or configured third-party integrations. The trust views themselves use local text, inline styles/code and an inline SVG. | N01, N02, N03, N04, N05, N06 |
| boundary.4.1 | Clicked built-in help links can reach github.com, console.anthropic.com, privacy.anthropic.com, trust.anthropic.com, www.anthropic.com, www.gnu.org and www.linkedin.com. Citation/source links can reach other HTTPS websites. Your browser controls cookies, authentication, redirects and subsequent navigation. | N06 |
| runtime.1.1 | Each card has the same rows. User cards name aliases that share the same effects; automatic cards describe work an earlier click or launch starts. ‘Nothing’ describes the app's own outbound payload for that step, not your OS/browser's independent activity. ‘None’ means that step does not generate a model request. API costs already incurred are not refunded by local failure, Clear or closing a window. | U15, U28, U36, A01, A05 |
| runtime.2.1 | U01 · Add drawings | U01 |
| runtime.2.2 | You do: Browse for PDFs or drop files. | U01 |
| runtime.2.3 | What runs: Filter extensions, deduplicate path strings, count readable pages and refresh the estimate; profile suggestions may run locally. | U01 |
| runtime.2.4 | What is sent: Nothing. | U01 |
| runtime.2.5 | AI involved: None. | U01 |
| runtime.2.6 | Bounded by: Unreadable PDFs can be absent from the preview count; the actual run inventories rejections. Picker Cancel keeps the selection. | U01 |
| runtime.3.1 | U02 · Set your desktop key | U02 |
| runtime.3.2 | You do: Type/paste a key; press Return or leave the field. | U02 |
| runtime.3.3 | What runs: Normalize the value in memory. On finishing an edit, save to a tested OS credential store; ask before a plaintext fallback. Analyze snapshots its own key. | U02 |
| runtime.3.4 | What is sent: Nothing. | U02 |
| runtime.3.5 | AI involved: None. | U02 |
| runtime.3.6 | Bounded by: Declining plaintext storage leaves a session key. Clearing the field does not delete a previously saved credential. Local storage has no API charge. | U02 |
| runtime.4.1 | U03 · Show the desktop key | U03 |
| runtime.4.2 | You do: Show / Hide beside the key. | U03 |
| runtime.4.3 | What runs: Change field masking; no validation request. | U03 |
| runtime.4.4 | What is sent: Nothing. | U03 |
| runtime.4.5 | AI involved: None. | U03 |
| runtime.4.6 | Bounded by: Local state only; no API charge. | U03 |
| runtime.5.1 | U04 · Open a reference | U04 |
| runtime.5.2 | You do: Get an API key, or an external help link. | U04 |
| runtime.5.3 | What runs: Open built-in help or ask your OS browser to follow the selected link. | U04 |
| runtime.5.4 | What is sent: For a link, its URL goes to your browser and the destination; the app does not append your project or key. | U04 |
| runtime.5.5 | AI involved: None. | U04 |
| runtime.5.6 | Bounded by: Browser privacy, cookies and further navigation are outside the app; no AI request is initiated by the link handler. | U04 |
| runtime.6.1 | U05 · Write your focus | U05 |
| runtime.6.2 | You do: Edit Per-run focus; open/close its larger editor, including Escape. | U05 |
| runtime.6.3 | What runs: Synchronize the text boxes; update the local estimate. Ordinary text editing and available editor undo operate on this text. | U05 |
| runtime.6.4 | What is sent: Nothing. | U05 |
| runtime.6.5 | AI involved: None. | U05 |
| runtime.6.6 | Bounded by: Edits alone do not send text. Analyze snapshots the text; there is no undo of an analysis or project save/load. | U05 |
| runtime.7.1 | U06 · Attach specifications | U06 |
| runtime.7.2 | You do: Upload spec documents…; accept the warning and choose files. | U06 |
| runtime.7.3 | What runs: Extract text locally from PDF, DOCX, TXT or MD on a worker. Replace the loaded spec context and report errors/truncation. | U06 |
| runtime.7.4 | What is sent: Nothing. | U06 |
| runtime.7.5 | AI involved: None. | U06 |
| runtime.7.6 | Bounded by: Per-file and combined prompt budget: 400,000 / 400,000 characters. No OCR for scanned spec PDFs. Cancel keeps existing context; extraction is not a currency/completeness check. | U06 |
| runtime.8.1 | U07 · Choose QC Markups | U07 |
| runtime.8.2 | You do: Toggle QC Markups. | U07 |
| runtime.8.3 | What runs: Select the exhaustive stack for your next run and enable its sub-options; update a local cost estimate. | U07 |
| runtime.8.4 | What is sent: Nothing. | U07 |
| runtime.8.5 | AI involved: None. | U07 |
| runtime.8.6 | Bounded by: Off by default. It starts paid QC only after Analyze and cost confirmation; failures can leave partial output. | U07 |
| runtime.9.1 | U08 · Restrict the ink | U08 |
| runtime.9.2 | You do: Verified & deterministic only. | U08 |
| runtime.9.3 | What runs: Select which statuses may be drawn in the next QC run. | U08 |
| runtime.9.4 | What is sent: Nothing. | U08 |
| runtime.9.5 | AI involved: None. | U08 |
| runtime.9.6 | Bounded by: Off by default. It filters ink, not the ledger, and does not certify the allowed findings as correct. | U08 |
| runtime.10.1 | U09 · Include rejected findings | U09 |
| runtime.10.2 | You do: Include rejected (grey). | U09 |
| runtime.10.3 | What runs: Select whether rejected findings appear as grey/struck annotations in the next QC run. | U09 |
| runtime.10.4 | What is sent: Nothing. | U09 |
| runtime.10.5 | AI involved: None. | U09 |
| runtime.10.6 | Bounded by: Off by default. A rejected model verdict is not a human decision; the index keeps its accounting. | U09 |
| runtime.11.1 | U10 · Choose the local audit | U10 |
| runtime.11.2 | You do: Reference audit. | U10 |
| runtime.11.3 | What runs: Enable text auditors for the next analysis. QC Markups includes them already. | U10 |
| runtime.11.4 | What is sent: Nothing. | U10 |
| runtime.11.5 | AI involved: None. | U10 |
| runtime.11.6 | Bounded by: The auditors add zero API calls. Analyze still runs a paid digest; this checkbox is not an offline analysis mode. | U10 |
| runtime.12.1 | U11 · Choose the queue | U11 |
| runtime.12.2 | You do: Economy, Hybrid or Fast. | U11 |
| runtime.12.3 | What runs: Economy batches digest and critique; Hybrid sends digest now and batches critique; Fast sends both now. Recalculate the estimate locally. | U11 |
| runtime.12.4 | What is sent: Nothing. | U11 |
| runtime.12.5 | AI involved: None. | U11 |
| runtime.12.6 | Bounded by: Economy is the GUI default. Other QC stages still use real-time calls; the transport choice is not a run spending cap. | U11 |
| runtime.13.1 | U12 · Keep tile images | U12 |
| runtime.13.2 | You do: Save tile images + per-tile notes. | U12 |
| runtime.13.3 | What runs: Tell the next run to retain rendered tiles for Export All, including rerendering warm cached sheets. | U12 |
| runtime.13.4 | What is sent: Nothing. | U12 |
| runtime.13.5 | AI involved: None. | U12 |
| runtime.13.6 | Bounded by: Off by default. Rerendering adds local work and disk use; it alone does not make an extra model call. | U12 |
| runtime.14.1 | U13 · Choose a checklist | U13 |
| runtime.14.2 | You do: Select/deselect a review profile. | U13 |
| runtime.14.3 | What runs: Record your manual choice, which takes precedence over local auto-suggestions; snapshot profiles for the next critique. | U13 |
| runtime.14.4 | What is sent: Nothing. | U13 |
| runtime.14.5 | AI involved: None. | U13 |
| runtime.14.6 | Bounded by: No built-in profiles ship by default. User Markdown profiles change model instructions when the next QC run is approved. | U13 |
| runtime.15.1 | U14 · Choose key embedding | U14 |
| runtime.15.2 | You do: Embed API key in HTML report. | U14 |
| runtime.15.3 | What runs: Set the export option that writes the key literally into generated HTML. | U14 |
| runtime.15.4 | What is sent: Nothing. | U14 |
| runtime.15.5 | AI involved: None. | U14 |
| runtime.15.6 | Bounded by: Off by default. The exported file becomes a credential if enabled; Forget key cannot remove that literal. Ask-AI still requires network access. | U14 |
| runtime.16.1 | U15 · Clear the desktop session | U15 |
| runtime.16.2 | You do: Clear. | U15 |
| runtime.16.3 | What runs: Reset selected drawings, specs, context, profile choices and activity display. | U15 |
| runtime.16.4 | What is sent: Nothing. | U15 |
| runtime.16.5 | AI involved: None. | U15 |
| runtime.16.6 | Bounded by: Disabled while analyzing. It does not erase the saved key, cache, diagnostic file, browser chat, old exports or temp evidence. | U15 |
| runtime.17.1 | U16 · Start the review | U16 |
| runtime.17.2 | You do: Analyze Drawings, then confirm the cost dialog. | U16 |
| runtime.17.3 | What runs: Snapshot key/files/focus/specs/options; start a daemon worker. The automatic cards below describe inventory through exportable results, with overlapping independent work. | U16 |
| runtime.17.4 | What is sent: Approved work sends page images/text, optional specs/focus/checklists, filenames/page labels and subsequent findings to Anthropic (or a configured desktop SDK endpoint). | U16 |
| runtime.17.5 | AI involved: Sheet digest: claude-opus-5-5; high reasoning; up to 64,000 output tokens; Set overview: claude-opus-5-5; high reasoning; up to 32,000 output tokens; Focus report: claude-opus-5-5; high reasoning; up to 32,000 output tokens; Identity: claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens; Review plan: claude-opus-5-5; high reasoning; up to 32,000 output tokens; Critique: claude-opus-5-5; high reasoning; up to 64,000 output tokens; Cross-sheet QC: claude-opus-5-5; high reasoning; up to 16,000 output tokens; Prose harvest: claude-sonnet-5-5; low reasoning; up to 8,000 output tokens; Crop verification: claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens; Investigation: claude-opus-5-5; high reasoning; up to 16,000 output tokens; Citation check: claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | U16 |
| runtime.17.6 | Bounded by: Declining sends no analysis request. Estimates are local approximations. There is no desktop Stop button or global spend cap; quitting is not guaranteed remote cancellation. | U16 |
| runtime.18.1 | U17 · Save an HTML report | U17 |
| runtime.18.2 | You do: Save HTML Report…; choose a filename. | U17 |
| runtime.18.3 | What runs: Build an HTML file with inline code/styles, findings and report text, optionally an embedded key; open it with your OS browser. | U17 |
| runtime.18.4 | What is sent: Nothing. | U17 |
| runtime.18.5 | AI involved: None. | U17 |
| runtime.18.6 | Bounded by: Cancel writes nothing. A selected existing destination can be overwritten; export does not undo paid analysis. Opening the report does not send an AI question. | U17 |
| runtime.19.1 | U18 · Save reviewed PDFs | U18 |
| runtime.19.2 | You do: Save Reviewed PDF(s)…; choose a folder. | U18 |
| runtime.19.3 | What runs: Copy reviewed files from temporary work to the selected folder; report missing files and per-file copy failures. | U18 |
| runtime.19.4 | What is sent: Nothing. | U18 |
| runtime.19.5 | AI involved: None. | U18 |
| runtime.19.6 | Bounded by: Cancel writes nothing. A selected existing destination can be overwritten; export does not undo paid analysis. Earlier successful copies remain if a later copy fails. | U18 |
| runtime.20.1 | U19 · Export the audit record | U19 |
| runtime.20.2 | You do: Export All…; choose a folder. | U19 |
| runtime.20.3 | What runs: Stage report, Markdown, findings, source text, evidence, reviewed PDFs, optional tiles, logs and manifests on a worker; hash artifacts and publish the folder; open the folder. | U19 |
| runtime.20.4 | What is sent: Nothing. | U19 |
| runtime.20.5 | AI involved: None. | U19 |
| runtime.20.6 | Bounded by: Staging/publish errors use export rollback. This does not roll back API spending. Keep the exported folder because temp evidence may later be pruned. | U19 |
| runtime.21.1 | U20 · Read diagnostics | U20 |
| runtime.21.2 | You do: Open Diagnostics Log. | U20 |
| runtime.21.3 | What runs: Open the file/folder in your OS viewer or show its path if opening fails. | U20 |
| runtime.21.4 | What is sent: Nothing. | U20 |
| runtime.21.5 | AI involved: None. | U20 |
| runtime.21.6 | Bounded by: Logs are local and pattern-redacted, not generally anonymized. File logging can be disabled by DRAWING_ANALYZER_DIAGNOSTICS. | U20 |
| runtime.22.1 | U21 · Check for updates | U21 |
| runtime.22.2 | You do: Check for Updates. | U21 |
| runtime.22.3 | What runs: GET the version manifest, compare versions and record the check time in local JSON. Show the result; do not install yet. | U21 |
| runtime.22.4 | What is sent: Updater User-Agent/Accept and ordinary connection metadata go to GitHub/redirects, or DRAWING_ANALYZER_UPDATE_URL. No app-built project/key payload. | U21 |
| runtime.22.5 | AI involved: None. | U21 |
| runtime.22.6 | Bounded by: Manifest limit 65,536 bytes; socket timeout 8 seconds. DRAWING_ANALYZER_DISABLE_UPDATE_CHECK also disables manual checks. | U21 |
| runtime.23.1 | U22 · Download and install | U22 |
| runtime.23.2 | You do: Download & Install, then accept Install update. | U22 |
| runtime.23.3 | What runs: Download to a partial file, compute SHA-256 (a file fingerprint), compare with the manifest, rename on success. Ask again before starting the installer and quitting. | U22 |
| runtime.23.4 | What is sent: GET to the manifest's HTTPS installer URL and redirect hosts; app sends no drawings or API key. | U22 |
| runtime.23.5 | AI involved: None. | U22 |
| runtime.23.6 | Bounded by: Socket timeout 60 seconds, with no total-time or byte ceiling. Failure removes the partial file. A hash from the same manifest is not an independent publisher signature. Analysis blocks the download trigger. | U22 |
| runtime.24.1 | U23 · Defer an update | U23 |
| runtime.24.2 | You do: Later. | U23 |
| runtime.24.3 | What runs: Close the update offer. | U23 |
| runtime.24.4 | What is sent: Nothing. | U23 |
| runtime.24.5 | AI involved: None. | U23 |
| runtime.24.6 | Bounded by: Local state only; no API charge. No installer starts. | U23 |
| runtime.25.1 | U24 · Skip an update | U24 |
| runtime.25.2 | You do: Skip this Version. | U24 |
| runtime.25.3 | What runs: Write the skipped version into update_check.json and close the offer. | U24 |
| runtime.25.4 | What is sent: Nothing. | U24 |
| runtime.25.5 | AI involved: None. | U24 |
| runtime.25.6 | Bounded by: Automatic offers suppress that version; manual checks can show it again. No install or API charge. | U24 |
| runtime.26.1 | U25 · Dismiss a downloading update | U25 |
| runtime.26.2 | You do: Close the update window during download. | U25 |
| runtime.26.3 | What runs: Mark completion as dismissed and destroy the window; the download worker continues. | U25 |
| runtime.26.4 | What is sent: The already-started GET to the installer host can continue. | U25 |
| runtime.26.5 | AI involved: None. | U25 |
| runtime.26.6 | Bounded by: This does not abort the transfer. A verified installer can remain cached; completion will not start it or show an install prompt. | U25 |
| runtime.27.1 | U26 · Read help and the dossier | U26 |
| runtime.27.2 | You do: How to use / How it works / Why trust it? / About; dossier button; contents; Close or Escape. | U26 |
| runtime.27.3 | What runs: Render local content. The dossier stacks over Why trust it; contents move within the same document. Closing returns focus to its opener. | U26 |
| runtime.27.4 | What is sent: Nothing. | U26 |
| runtime.27.5 | AI involved: None. | U26 |
| runtime.27.6 | Bounded by: The trust surfaces load no external assets. One Escape closes the top trust dialog; the lower topic stays open. | U26 |
| runtime.28.1 | U27 · Expand a desktop section | U27 |
| runtime.28.2 | You do: Click a section's caret/header. | U27 |
| runtime.28.3 | What runs: Show/hide the same local controls and refresh their summaries. | U27 |
| runtime.28.4 | What is sent: Nothing. | U27 |
| runtime.28.5 | AI involved: None. | U27 |
| runtime.28.6 | Bounded by: Local state only; no API charge. | U27 |
| runtime.29.1 | U28 · Quit the desktop app | U28 |
| runtime.29.2 | You do: Close the main window; confirm Quit anyway if busy. | U28 |
| runtime.29.3 | What runs: Destroy the window and end daemon work when the process exits; reject the prompt to keep working. | U28 |
| runtime.29.4 | What is sent: Nothing. | U28 |
| runtime.29.5 | AI involved: None. | U28 |
| runtime.29.6 | Bounded by: In-memory results can be lost. Already accepted API work can remain billed/running; quitting does not promise batch cancellation or deletion of temporary evidence. | U28 |
| runtime.30.1 | U29 · Browse the report | U29 |
| runtime.30.2 | You do: Search/filter/sort; group repeats; contents/sheet/evidence/PDF links; expand/collapse. | U29 |
| runtime.30.3 | What runs: Search report text, filter rows, sort and navigate locally. Evidence/PDF links open referenced files; external citation links open websites. | U29 |
| runtime.30.4 | What is sent: Nothing for local browsing. A clicked external citation URL goes to that website via your browser. | U29 |
| runtime.30.5 | AI involved: None. | U29 |
| runtime.30.6 | Bounded by: Filters can hide findings without removing them. PDF/evidence links need the adjacent files and a viewer; HTTPS links are not authority/privacy checks. | U29 |
| runtime.31.1 | U30 · Copy report text | U30 |
| runtime.31.2 | You do: Copy all. | U30 |
| runtime.31.3 | What runs: Copy raw report Markdown to the clipboard, with a local fallback if the clipboard API fails. | U30 |
| runtime.31.4 | What is sent: Nothing. | U30 |
| runtime.31.5 | AI involved: None. | U30 |
| runtime.31.6 | Bounded by: No API call. Clipboard contents can be read by your other software or OS clipboard sync. | U30 |
| runtime.32.1 | U31 · Open or close Ask-AI | U31 |
| runtime.32.2 | You do: Ask AI; panel ×; reopen. | U31 |
| runtime.32.3 | What runs: Show/hide the report's chat panel and restore available local state. | U31 |
| runtime.32.4 | What is sent: Nothing. | U31 |
| runtime.32.5 | AI involved: None. | U31 |
| runtime.32.6 | Bounded by: Closing the panel is not Stop. It can leave a sent question running. | U31 |
| runtime.33.1 | U32 · Choose the report's key | U32 |
| runtime.33.2 | You do: Save key / Return; Change key; Use the report's key. | U32 |
| runtime.33.3 | What runs: Keep your entered key in memory and best-effort sessionStorage (tab-scoped browser storage). Your entered key takes precedence over an embedded key. | U32 |
| runtime.33.4 | What is sent: Nothing. | U32 |
| runtime.33.5 | AI involved: None. | U32 |
| runtime.33.6 | Bounded by: No authentication request until Send. Local HTML files in the same tab can share sessionStorage; browser recovery may persist tabs. Use a trusted tab or a separate HTTPS origin. | U32 |
| runtime.34.1 | U33 · Forget the report key | U33 |
| runtime.34.2 | You do: Forget key. | U33 |
| runtime.34.3 | What runs: Remove the entered key from memory and sessionStorage; fall back to an embedded author key if the file has one. | U33 |
| runtime.34.4 | What is sent: Nothing. | U33 |
| runtime.34.5 | AI involved: None. | U33 |
| runtime.34.6 | Bounded by: An embedded key remains in HTML. Remove it by regenerating/deleting the file, and revoke it with its provider if exposed. This does not erase transcripts. | U33 |
| runtime.35.1 | U34 · Show the report key | U34 |
| runtime.35.2 | You do: Show / Hide in the chat key form. | U34 |
| runtime.35.3 | What runs: Change the field's masking locally. | U34 |
| runtime.35.4 | What is sent: Nothing. | U34 |
| runtime.35.5 | AI involved: None. | U34 |
| runtime.35.6 | Bounded by: Local state only; no API charge. | U34 |
| runtime.36.1 | U35 · Ask a question | U35 |
| runtime.36.2 | You do: Send / Enter; starter question; select text and Ask AI about this; remove excerpt chip. | U35 |
| runtime.36.3 | What runs: Stage typed/selected text locally; sending streams an answer and may automatically run the tools and follow-ups in A18. Dismissing the chip only clears pending selection. | U35 |
| runtime.36.4 | What is sent: Nothing while composing/selecting/dismissing an excerpt. On Send, full report context, source labels, question/excerpt, conversation and tool results go to api.anthropic.com with the active tab/embedded key. | U35 |
| runtime.36.5 | AI involved: Composing/selecting/dismissing: None. Sent questions: Report Ask-AI: claude-sonnet-5-5; high (when supported) reasoning; up to 128,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | U35 |
| runtime.36.6 | Bounded by: No per-question cost confirmation or dollar ceiling. The full report and growing history are resent; no automatic history trimming. Provider context/output limits can cut off an answer. | U35 |
| runtime.37.1 | U36 · Stop a chat answer | U36 |
| runtime.37.2 | You do: Stop. | U36 |
| runtime.37.3 | What runs: Latch a turn stop, abort the current browser fetch, flush received text, and prevent new follow-up requests after the handler checks the stop. | U36 |
| runtime.37.4 | What is sent: No new request from Stop; the accepted remote request may still run. | U36 |
| runtime.37.5 | AI involved: None. | U36 |
| runtime.37.6 | Bounded by: Work accepted by Anthropic remains potentially billed; abort is not server-side rollback. Local tools already running may finish; interrupted usage can be incomplete. | U36 |
| runtime.38.1 | U37 · Start a new chat | U37 |
| runtime.38.2 | You do: New chat. | U37 |
| runtime.38.3 | What runs: Abort the current fetch, invalidate its late callbacks, clear history/display and erase the stored transcript for this report. | U37 |
| runtime.38.4 | What is sent: Nothing. | U37 |
| runtime.38.5 | AI involved: None. | U37 |
| runtime.38.6 | Bounded by: New chat erases the stored browser copy; it does not delete saved JSON/PDF copies or reverse spend. The key can remain. | U37 |
| runtime.39.1 | U38 · Save a conversation | U38 |
| runtime.39.2 | You do: Save in Ask-AI. | U38 |
| runtime.39.3 | What runs: Serialize conversation and tool results to chat_history.json for browser download; scrub recognized sk-ant- key patterns. | U38 |
| runtime.39.4 | What is sent: Nothing. | U38 |
| runtime.39.5 | AI involved: None. | U38 |
| runtime.39.6 | Bounded by: The saved file is not capped by the browser autosave limit. It contains project text; it is outside the sealed run manifest. Pattern scrubbing is not general secret detection. | U38 |
| runtime.40.1 | U39 · Load a conversation | U39 |
| runtime.40.2 | You do: Load; choose a saved JSON file. | U39 |
| runtime.40.3 | What runs: Read and validate transcript structure/report identity, normalize unfinished exchanges, replace history, render with safe text nodes and save local state. Recorded tools are displayed, not reexecuted. | U39 |
| runtime.40.4 | What is sent: Nothing. | U39 |
| runtime.40.5 | AI involved: None. | U39 |
| runtime.40.6 | Bounded by: Cancel keeps history. A loaded transcript can be false or malicious text and will be included in a later sent question; validation does not authenticate its claims. | U39 |
| runtime.41.1 | U40 · Print a conversation | U40 |
| runtime.41.2 | You do: PDF in Ask-AI; choose print/save or Cancel. | U40 |
| runtime.41.3 | What runs: Temporarily prepare the chat view for the browser print dialog, then restore display. | U40 |
| runtime.41.4 | What is sent: Nothing. | U40 |
| runtime.41.5 | AI involved: None. | U40 |
| runtime.41.6 | Bounded by: Local browser/OS print rules apply, including any remote printer or sync you configured. The app does not issue a model request. | U40 |
| runtime.42.1 | U41 · Arrange the chat panel | U41 |
| runtime.42.2 | You do: Drag/resize panel or message box; expand composer; double-click to reset. | U41 |
| runtime.42.3 | What runs: Change layout and save geometry in browser local storage. | U41 |
| runtime.42.4 | What is sent: Nothing. | U41 |
| runtime.42.5 | AI involved: None. | U41 |
| runtime.42.6 | Bounded by: Local storage has no app expiry. Browser policy controls retention; layout does not change model settings. | U41 |
| runtime.43.1 | A01 · Local work at startup | A01 |
| runtime.43.2 | You do: You launch the app; no extra click. | A01 |
| runtime.43.3 | What runs: Start/reset pattern-redacted diagnostics; load an environment key once and remove that variable from this process; otherwise read/repair keyring or migrate matching legacy key files; discover Markdown profiles. | A01 |
| runtime.43.4 | What is sent: Nothing. | A01 |
| runtime.43.5 | AI involved: None. | A01 |
| runtime.43.6 | Bounded by: Logs rotate at 2,000,000 bytes with 5 backups and reset next launch. Key migration can delete matching plaintext files; unrelated files remain. No model runs. | A01 |
| runtime.44.1 | A02 · Automatic update check | A02 |
| runtime.44.2 | You do: The startup timer runs without a click. | A02 |
| runtime.44.3 | What runs: If enabled and the local throttle allows, perform the same manifest check as U21; record successes or failures and show an available unskipped update. | A02 |
| runtime.44.4 | What is sent: Same GitHub/redirect or overridden HTTPS manifest route as U21; no project/key in the app-built request. | A02 |
| runtime.44.5 | AI involved: None. | A02 |
| runtime.44.6 | Bounded by: Default throttle 1 day(s). Set DRAWING_ANALYZER_DISABLE_UPDATE_CHECK=1 to disable. No automatic download/install. | A02 |
| runtime.45.1 | A03 · Local selection helpers | A03 |
| runtime.45.2 | You do: You change files/options or finish spec extraction. | A03 |
| runtime.45.3 | What runs: Count pages and estimate costs locally. When user profiles exist, a serialized background text scan suggests checklists and captures geometry for a sharper estimate; stale scans are ignored. | A03 |
| runtime.45.4 | What is sent: Nothing. | A03 |
| runtime.45.5 | AI involved: None. | A03 |
| runtime.45.6 | Bounded by: Default install has no profiles, so this profile preflight normally does not run. An estimate is not an exact token count or a file-validity guarantee. | A03 |
| runtime.46.1 | A04 · Inventory, cache and rendering | A04 |
| runtime.46.2 | You do: An approved analysis worker starts. | A04 |
| runtime.46.3 | What runs: Inventory selected sources and errors, assign identities/hash bytes, look up persistent caches; render misses sequentially and extract selectable text without existing annotations. Library token-count helper is not called by this pipeline. | A04 |
| runtime.46.4 | What is sent: Nothing. | A04 |
| runtime.46.5 | AI involved: None. | A04 |
| runtime.46.6 | Bounded by: Configured input guards: 500 files / 2,000 sheets (DRAWING_ANALYZER_MAX_FILES / DRAWING_ANALYZER_MAX_SHEETS). Default grid 6×6, 8% overlap; prompt text cap 15,000 characters with truncation disclosure. Near-blank suppression is opt-in, not default. | A04 |
| runtime.47.1 | A05 · Uploads, queue and recovery | A05 |
| runtime.47.2 | You do: An approved Economy/Hybrid run needs batch images/results. | A05 |
| runtime.47.3 | What runs: Upload images on a bounded pool; share uploaded IDs for repeated reads; submit Message Batches, poll progress, harvest finished reads, attempt cancellations and submit recoverable follow-ups. Delete released image IDs best effort, sometimes in a background thread. | A05 |
| runtime.47.4 | What is sent: PNG bytes and bare image filenames, request context and file IDs to the desktop provider; polling/cancel/delete IDs to it; results downloaded from its supplied results_url. | A05 |
| runtime.47.5 | AI involved: Uploads, polling, cancel and delete: None. Submitted/recovered items run Sheet digest: claude-opus-5-5; high reasoning; up to 64,000 output tokens; Critique: claude-opus-5-5; high reasoning; up to 64,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A05 |
| runtime.47.6 | Bounded by: Upload workers 6, status retries 4; batch elapsed 24 hours, resubmit rounds 4. Poll 15–120 seconds; consecutive-error bound 10; initial/later stall 25/60 minutes. DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS, DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS and DRAWING_ANALYZER_BATCH_STALL_TIMEOUT_MIN change these. Expiry is not a guaranteed erasure; failed cancel/delete can leave provider work/files. No silent switch to full-rate recovery. | A05 |
| runtime.48.1 | A06 · Read each sheet | A06 |
| runtime.48.2 | You do: The analysis has a sheet cache miss or a recoverable read. | A06 |
| runtime.48.3 | What runs: Send overview/tiles and bounded text plus prompt/focus/specs; parse finished findings/claims apart from prose. Transient errors/output limits may retry; supported real-time models request a server refusal fallback. | A06 |
| runtime.48.4 | What is sent: Page PNGs or file references, bounded text, filename/page label, focus/spec context to the desktop provider. Prompt tags separate input from instructions but do not guarantee immunity to malicious input. | A06 |
| runtime.48.5 | AI involved: Sheet digest: claude-opus-5-5; high reasoning; up to 64,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A06 |
| runtime.48.6 | Bounded by: Up to 40 parsed findings and 40 numeric claims per sheet. Output retry ceiling 128,000 tokens, model-clamped. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. DRAWING_ANALYZER_MODEL changes the default model; DRAWING_ANALYZER_REFUSAL_FALLBACK=0 disables fallback. A fallback-specific rejection retries without that feature. | A06 |
| runtime.49.1 | A07 · Summarize the set and your focus | A07 |
| runtime.49.2 | You do: Enough readable sheets exist; your focus is nonempty for a focus report. | A07 |
| runtime.49.3 | What runs: Send budgeted digests for synthesis and/or focus. These independent calls can overlap identity/planning/critique; assembly records results in a stable order. | A07 |
| runtime.49.4 | What is sent: Budgeted model-authored sheet digests and focus, to the desktop provider. | A07 |
| runtime.49.5 | AI involved: Set overview: claude-opus-5-5; high reasoning; up to 32,000 output tokens; Focus report: claude-opus-5-5; high reasoning; up to 32,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A07 |
| runtime.49.6 | Bounded by: Synthesis requires 2 readable sheets; focus requires 1. Budgeted input can omit tails; failures preserve sheet output and report errors. DRAWING_ANALYZER_SYNTHESIS_MODEL and DRAWING_ANALYZER_FOCUS_MODEL override routing. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A07 |
| runtime.50.1 | A08 · Identify the set and draft a plan | A08 |
| runtime.50.2 | You do: QC Markups starts its identity/planning stages. | A08 |
| runtime.50.3 | What runs: Build a bounded text corpus, infer set context, union locally harvested adopted editions, then ask for specialist checklists; sanitize fields and convert plans to profiles. | A08 |
| runtime.50.4 | What is sent: Digest heads, bounded extracted-text/edition windows, inferred set identity, to the desktop provider. | A08 |
| runtime.50.5 | AI involved: Identity: claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens; Review plan: claude-opus-5-5; high reasoning; up to 32,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A08 |
| runtime.50.6 | Bounded by: Plan items bounded by DRAWING_ANALYZER_MAX_PLAN_ITEMS (default 60). Advisory context can be wrong; failures do not suppress the whole review. DRAWING_ANALYZER_IDENTITY_MODEL and DRAWING_ANALYZER_REVIEW_PLAN_MODEL override models. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A08 |
| runtime.51.1 | A09 · Critique the sheets | A09 |
| runtime.51.2 | You do: QC Markups enables critique. | A09 |
| runtime.51.3 | What runs: Read each sheet again with selected/model-authored profiles; reuse pixels/uploads where valid, rerender otherwise. Compare repeated findings and retain valid completed reads; recover eligible batch failures. | A09 |
| runtime.51.4 | What is sent: Page images/text, focus/spec context and checklist instructions, to the desktop provider. | A09 |
| runtime.51.5 | AI involved: Critique: claude-opus-5-5; high reasoning; up to 64,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A09 |
| runtime.51.6 | Bounded by: Default repeated reads 2; DRAWING_ANALYZER_CRITIQUE_RUNS and DRAWING_ANALYZER_CRITIQUE_MODEL change them. Agreement is repeatability, not independent proof. Invalid/unfinished reads do not enter trusted results. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A09 |
| runtime.52.1 | A10 · Compare across sheets | A10 |
| runtime.52.2 | You do: QC Markups has enough readable sheets. | A10 |
| runtime.52.3 | What runs: Compare digest/text accounts in one request for small sets; split larger sets, validate shard evidence against source text, and reconcile compact facts. The small-set path relies on later anchoring rather than that shard admission gate. | A10 |
| runtime.52.4 | What is sent: Digests, bounded sheet text, source handles, inferred context and then compact facts, to the desktop provider. | A10 |
| runtime.52.5 | AI involved: Cross-sheet QC: claude-opus-5-5; high reasoning; up to 16,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A10 |
| runtime.52.6 | Bounded by: Small-set threshold 40; per-sheet prompt text 4,000 characters. Findings cap 60, map facts 40, reconcile fact budget 400, pair-call ceiling 64. Omitted/refused items are limits on coverage. DRAWING_ANALYZER_CROSS_QC_MODEL changes routing. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A10 |
| runtime.53.1 | A11 · Local checks and finding assembly | A11 |
| runtime.53.2 | You do: Your selected audit/QC stages reach the ledger. | A11 |
| runtime.53.3 | What runs: Check references, naming, title blocks, sheet indexes and editions; check transcribed numeric claims using Decimal, an arithmetic component that avoids binary rounding. Ground operands AND the stated relationship before deterministic arithmetic status; anchor quotes, merge conservatively and assign QC numbers. | A11 |
| runtime.53.4 | What is sent: Nothing. | A11 |
| runtime.53.5 | AI involved: None. | A11 |
| runtime.53.6 | Bounded by: Host checks can be wrong if extraction/identity is wrong or a rule does not fit the drawing. Tile/unanchored locations are not exact text matches. Model-origin operands that fail grounding remain uncertain; not every possible equation is discovered. | A11 |
| runtime.54.1 | A12 · Mirror prose into findings | A12 |
| runtime.54.2 | You do: QC stages examine digest, synthesis and focus prose. | A12 |
| runtime.54.3 | What runs: Filter non-findings locally, match existing ledger entries; ask a model to structure residual items. Unstructured/degraded items and accounting remain visible where supported. | A12 |
| runtime.54.4 | What is sent: Residual item and bounded on-sheet text/context to the desktop provider. | A12 |
| runtime.54.5 | AI involved: Prose harvest: claude-sonnet-5-5; low reasoning; up to 8,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A12 |
| runtime.54.6 | Bounded by: Source-text cap 6,000 characters. Filtering/matching can miss or misclassify prose; this is not a completeness guarantee. DRAWING_ANALYZER_HARVEST_MODEL changes the model. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A12 |
| runtime.55.1 | A13 · Recheck visible evidence | A13 |
| runtime.55.2 | You do: QC reaches an eligible anchored finding. | A13 |
| runtime.55.3 | What runs: Render crops, save and hash evidence before requesting a verdict; replay eligible cached verdicts or send the crop(s)/claim. Validate status; schema rejection can fall back to ordinary JSON parsing. | A13 |
| runtime.55.4 | What is sent: Saved crop image(s), finding text/quote and framing to the desktop provider. | A13 |
| runtime.55.5 | AI involved: Crop verification: claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A13 |
| runtime.55.6 | Bounded by: Default crops 300 DPI (dots per inch). DETERMINISTIC entries skip model verification; unlocatable findings cannot get ordinary crop confirmation. CONFIRMED becomes VERIFIED, CONTRADICTED becomes REJECTED, NOT_VISIBLE/invalid/failed stays UNCERTAIN. DRAWING_ANALYZER_VERIFICATION_MODEL (legacy DRAWING_ANALYZER_VERIFY_MODEL) changes routing. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A13 |
| runtime.56.1 | A14 · Investigate uncertain findings | A14 |
| runtime.56.2 | You do: QC has eligible uncertain findings and remaining investigation slots. | A14 |
| runtime.56.3 | What runs: Ask for extra crops/text searches/overviews from loaded sheets. Validate inputs, save/hash images and append tool results to follow-up requests. Replayed cached investigations must reproduce evidence hashes. Withdraw tool permission at the evidence limit. | A14 |
| runtime.56.4 | What is sent: Finding, initial saved crop, bounded loaded-sheet index, requested local evidence and accumulated tool conversation to the desktop provider. | A14 |
| runtime.56.5 | AI involved: Investigation: claude-opus-5-5; high reasoning; up to 16,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A14 |
| runtime.56.6 | Bounded by: Default evidence requests 6; pause resumes 3; advisory task budget 40,000 tokens. Default run slots min(10 + floor(sheets/4), 40). DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS, DRAWING_ANALYZER_INVESTIGATION_MAX_FINDINGS and DRAWING_ANALYZER_INVESTIGATION_TASK_BUDGET override these; the findings override can exceed the default ceiling. Budget rejection removes the advisory token budget, but host evidence/iteration limits remain. Failure/exhaustion does not mean rejected. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A14 |
| runtime.57.1 | A15 · Check cited sources | A15 |
| runtime.57.2 | You do: QC has unique cited references or plan references to check. | A15 |
| runtime.57.3 | What runs: Split distinct claims into complete chunks; ask server-side web_search/web_fetch to examine adopted/current editions; parse assessments, require claim coverage and cache verdicts with a reuse TTL (validity period). | A15 |
| runtime.57.4 | What is sent: Code references, claims/quotes and edition context to the desktop provider; model-selected queries/URLs to websites via provider tools. Queries are not guaranteed free of project information. | A15 |
| runtime.57.5 | AI involved: Citation check: claude-sonnet-5-5; medium reasoning; up to 8,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A15 |
| runtime.57.6 | Bounded by: Claims/request 8; searches/fetches per request 10/4; fetched text 40,000 tokens; pause resumes 3; cache validity 30 days. DRAWING_ANALYZER_CITATION_MODEL, DRAWING_ANALYZER_WEB_SEARCH_MAX_USES, DRAWING_ANALYZER_WEB_FETCH_MAX_USES and DRAWING_ANALYZER_CITATION_TTL_DAYS tune these. Limits refresh per request/resume; not a whole-run search ceiling. Paywalls/incorrect editions can leave uncertain checks. Transient app retries: 2 beyond the first attempt; the SDK also retries. Failed attempts may be billed; no dollar ceiling. | A15 |
| runtime.58.1 | A16 · Write and check the annotations | A16 |
| runtime.58.2 | You do: QC Markups reaches the output stage. | A16 |
| runtime.58.3 | What runs: Write new reviewed PDFs in temporary work; draw according to status/options and plan index entries. Stamp mandatory annotation components, reopen PDFs and reconcile saved receipts with the plan. | A16 |
| runtime.58.4 | What is sent: Nothing. | A16 |
| runtime.58.5 | AI involved: None. | A16 |
| runtime.58.6 | Bounded by: Missing/failed/duplicate/unexpected required marks make coverage INCOMPLETE, reflected in naming/report. This proves planned marks were found, not that every engineering problem was found or every annotation is visually ideal. | A16 |
| runtime.59.1 | A17 · Remember the report session | A17 |
| runtime.59.2 | You do: You open a report or a chat turn completes/stops/fails. | A17 |
| runtime.59.3 | What runs: Restore locally saved history and layout; save updated transcript after settled turns, stripping recognized sk-ant- key patterns. Replay uses safe display paths and does not rerun past tools. Local timers animate/search the interface. | A17 |
| runtime.59.4 | What is sent: Nothing. | A17 |
| runtime.59.5 | AI involved: None. | A17 |
| runtime.59.6 | Bounded by: Browser autosave ceiling 500,000 serialized characters; failure warns to Save. Browser local storage has no app expiry and local HTML files can share its origin. New chat clears this report's stored copy; file copies remain. | A17 |
| runtime.60.1 | A18 · Automatic chat follow-ups | A18 |
| runtime.60.2 | You do: Your sent question returns tool requests or a paused server turn. | A18 |
| runtime.60.3 | What runs: Anthropic can search/fetch websites. Browser tools read findings/summary, navigate/filter/highlight and calculate; requested tools run in parallel, then results go back for a new streamed answer. Received/model text is displayed as data. | A18 |
| runtime.60.4 | What is sent: Full report, question/history and tool results to api.anthropic.com; provider tools can send model-chosen queries/URLs to other sites. | A18 |
| runtime.60.5 | AI involved: Report Ask-AI: claude-sonnet-5-5; high (when supported) reasoning; up to 128,000 output tokens. Adaptive thinking on supported models; temperature unspecified. | A18 |
| runtime.60.6 | Bounded by: Server continuation limit 8; forced text close starts when local tool rounds exceed 10 (the comparison allows an extra tool-bearing round). Search/fetch budget 8/4 and fetch-text cap 40,000 tokens reset on each request. No app fetch timeout, dollar ceiling, automatic history truncation, SDK retry or refusal-fallback parameter. Stop prevents later follow-ups after its checks; tools already started may finish. | A18 |
| runtime.61.1 | A19 · Clean up run work | A19 |
| runtime.61.2 | You do: A later analysis starts; a run exits normally or through cleanup. | A19 |
| runtime.61.3 | What runs: Prune stale drawing_qc_* temp trees at run entry; keep recent/uncertain trees. Remove this run's render spool on exit and release retained uploaded image IDs best effort. | A19 |
| runtime.61.4 | What is sent: Released file IDs for deletion to the desktop provider. Local pruning sends nothing. | A19 |
| runtime.61.5 | AI involved: None. | A19 |
| runtime.61.6 | Bounded by: Default stale age 24 hours; DRAWING_ANALYZER_WORKDIR_MAX_AGE_HOURS=0 disables pruning. Temp evidence is not erased on close; export promptly. Remote deletion failures are swallowed, and files still needed by uncanceled batches may be kept. | A19 |
| runtime.62.1 | Layered bounds, not a run budget | N01, A05, A06, A07, A13, A18 |
| runtime.62.2 | The release SDK retries up to 2 times per request by default, beneath application retries. Default SDK timeouts are 5 seconds for connect and 600 seconds for read/write/pool operations; they are not a run elapsed ceiling. A batch bound applies to its collection/recovery phase, not the entire review. Set-level and QC calls can overlap on worker pools; repeated errors or provider latency still lengthen a run. No application dollar cutoff exists. | N01, A05, A06, A07, A13, A18 |
| tools.1.1 | Tool or capability · What it can do · Constraint | A06, A08, A11, A14, A15, A18 |
| tools.1.2 | Digest / critique / summary / plan · Propose text, structured findings and numeric claims. · Code parses allowed fields/categories, bounds lists and binds references; it does not execute proposed code. Structure validation is not truth validation. | A06, A08, A11, A14, A15, A18 |
| tools.1.3 | crop_region · Request a rectangle on a loaded drawing. · Loaded-sheet lookup, finite/bounded rectangle and 72–300 DPI; evidence saved/hashed before sending. | A06, A08, A11, A14, A15, A18 |
| tools.1.4 | find_text · Search extracted words on loaded sheets. · Literal local text search; at most 20 matches; no arbitrary file path or shell command. | A06, A08, A11, A14, A15, A18 |
| tools.1.5 | view_sheet · Request a loaded sheet overview. · Known sheet lookup; overview at 150 DPI. Bounded visible index 60; allowed lookup still stays within loaded sheets. | A06, A08, A11, A14, A15, A18 |
| tools.1.6 | web_search / web_fetch · Research model-selected websites at Anthropic. · Per-request use/content bounds and source-quality blocked domains; no promise queries exclude project information or sources are correct. | A06, A08, A11, A14, A15, A18 |
| tools.1.7 | scroll_to_report / filter_report / highlight_term · Move, reveal, filter or highlight this report in your browser. · Fixed dispatch functions and report DOM (page elements); no arbitrary script evaluator. A tool can change what you see without changing finding truth. | A06, A08, A11, A14, A15, A18 |
| tools.1.8 | query_findings / get_report_summary · Read embedded structured records and run accounting. · Local report data; bounded query return list. Returned content is sent in later tool rounds. | A06, A08, A11, A14, A15, A18 |
| tools.1.9 | calculate · Evaluate an arithmetic expression in report chat. · Restricted parser for numbers/operators, not eval. Browser floating-point arithmetic differs from the review's Decimal checks and is not engineering validation. | A06, A08, A11, A14, A15, A18 |
| tools.2.1 | These declared tools cannot run a shell (a system command interpreter), execute model-written code, choose arbitrary desktop files, or rewrite your input PDFs. Their evidence/rendering handlers do write local evidence and their report handlers can change your view. Network research is available through the named provider web tools; prompts alone are not a sandbox against misleading instructions in a drawing or transcript. | A14, A15, A18 |
| terms.1.1 | Grounded — the exact claim | A10, A11 |
| terms.1.2 | A reported quote has passed a supported match/location rule against the relevant source text; the anchor records exact, fuzzy or character-stream matching, or reduced-trust tile fallback. It does not establish that the model's interpretation, code edition or missing-item allegation is correct. | A10, A11 |
| terms.2.1 | DETERMINISTIC — the exact claim | A11 |
| terms.2.2 | A host rule produced the finding; arithmetic gains this status only after operand and relationship grounding. It does not mean the input text is accurate, every numeric relationship was checked, or a heuristic rule applies to your project. | A11 |
| terms.3.1 | VERIFIED / REJECTED — the exact claim | A13, A16 |
| terms.3.2 | A completed model crop verdict confirmed/contradicted the particular finding. Rejected findings remain accounted for in the ledger/index. Neither status is professional approval, independent proof, or a full-sheet inspection by a person. | A13, A16 |
| terms.4.1 | UNCERTAIN / UNVERIFIED / UNANCHORED — the exact claim | A11, A13 |
| terms.4.2 | UNCERTAIN means a check did not settle the claim; UNVERIFIED means no verification result ran for it; UNANCHORED describes missing supported location. These are different gaps, not synonyms for false. A quote/location failure does not necessarily mean deliberate hallucination. | A11, A13 |
| terms.5.1 | COMPLETE / INCOMPLETE — the exact claim | A04, A10, A13, A16 |
| terms.5.2 | COMPLETE is the roll-up of expected configured stage outcomes. Markup coverage counts required saved components found after reopening, and INCOMPLETE names missing/failed receipt coverage. Neither means every defect was found, every mark is readable, or the set is safe to issue. | A04, A10, A13, A16 |
| terms.6.1 | Secure — the exact claim | U02, U14, A17, A18, N01 |
| terms.6.2 | Keys prefer a tested OS credential store; consent gates plaintext fallback. HTML uses escaping, safe text nodes, an HTTPS link policy and a Content Security Policy (browser rules restricting scripts/connections). This does not encrypt project artifacts/cache, certify vendor security, or prevent a model being misled. | U02, U14, A17, A18, N01 |
| local.1.1 | Choosing files, local spec extraction and cost estimation. | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.1.2 | PDF rendering/text extraction, source fingerprints, cache identity checks and local cache reads. | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.1.3 | Reference, naming, title-block, sheet-index and edition text rules; arithmetic once claims are supplied. | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.1.4 | Quote matching, conservative merging, QC numbering and local status/usage arithmetic. | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.1.5 | Annotation layout, reopen/receipt reconciliation, staging, hashes and exports. | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.1.6 | Report search/filter/sort/navigation, clipboard copy, transcript import/replay, layout and printing. | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.1.7 | Help, update version comparison and installer hashing (update fetch/download themselves need network). | U01, U06, U19, U26, U29, U30, U39, U40, A04, A11, A16 |
| local.2.1 | What works disconnected | U10, U14, U26, U29, A04, A06, A18 |
| local.2.2 | You can read help and saved reports/PDFs, browse/filter their embedded content, extract local specs, inspect cache/exports, copy and print. There is no fully offline mode for a fresh model review: a missing cached result needs the provider. A warm cache can skip some calls, but is not an air-gapped guarantee. Reference audit inside Analyze still accompanies a digest. Ask-AI needs the API even if a key is embedded. | U10, U14, U26, U29, A04, A06, A18 |
| privacy.1.1 | Concern · How it is handled | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.2 | Desktop credential · Environment key loaded once and removed from this process environment; run snapshots its own client. OS keyring is preferred after verified readback. Plaintext fallback requires consent; POSIX owner permissions are tightened. Clearing the input is not deleting the store. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.3 | Files at rest · Config uses the platform's DrawingAnalyzer directory: drawing_analyzer_api_key.txt fallback (also read beside executable), logs/drawing_analyzer.log, update_check.json and updates/ installers. No app retention limit on installed credential/state/cached installers; inspect permissions and delete/revoke when appropriate. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.4 | Review cache · ~/.drawing_analyzer/drawing_digest_cache.json is SQLite despite its suffix. It holds project-derived results in readable payloads; no general expiry/encryption. DRAWING_ANALYZER_CACHE_PATH changes its location; DRAWING_ANALYZER_CACHE_PERSIST=0 disables default persistence. Citation TTL controls reuse, not erasure. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.5 | Profiles, specifications and temporary work · User Markdown profiles live in ~/.drawing_analyzer/profiles (DRAWING_ANALYZER_PROFILES_DIR override). Attached spec text is kept in the desktop context and sent with approved work; Export All does not archive the original specifications as separate source artifacts. drawing_qc_* trees in system temp hold evidence/reviewed output and survive close until later pruning. Render spool is removed on run exit. Exported copies persist where you put them. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.6 | Browser credential and transcript · Entered key: memory plus best-effort sessionStorage da-api-key. Transcript: local storage da-chat-tx-<reportId>; geometry too. Browser controls disk/profile recovery and same-origin exposure. Local HTML files can share storage. Forget key can fall back to an embedded author key; New chat erases the stored transcript, not saved files. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.7 | Logs and exports · Diagnostics redacts recognized key/secret patterns; DRAWING_ANALYZER_DEBUG adds SDK detail. Run journal/export status strings scrub recognized secrets and private paths. Drawing/model content is not generally scrubbed; exports, cache, transcripts and evidence contain private project data. No app crash-upload path was found. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.8 | Remote file lifecycle · Uploaded images are reused, then best-effort deleted after safe release; some failed cancellations retain files for still-running batches. Provider retention/backup/training handling is its contract, not a local guarantee. Check provider file/batch state when work is interrupted. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.9 | Untrusted input · Model/file strings are escaped into HTML; streamed and loaded chat use text-node construction. Unsafe link schemes degrade to inert text; CSP restricts report connections/scripts. Imported tools do not replay. Prompt separation reduces ambiguity but does not prove resistance to prompt injection or certify suggestions. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| privacy.1.10 | Local exposure and updates · No app HTTP server/listener is started. SDK/environment proxy settings can route traffic differently. Updater requires HTTPS and a matching manifest hash, but not a fixed host or independent signature; an untrusted custom manifest is an installer trust decision. | U02, U14, U15, U22, U32, U33, U37, U39, A01, A04, A05, A17, A19, N01, N03 |
| money.1.1 | Anthropic bills the account for the active key; the app has no separate charge code. Desktop estimates use local page/image/text allowances and a price table. Report chat uses the reader's entered key, falling back to an embedded author key. Its spend is outside the analysis run ledger. Configured custom providers can have different terms. | U16, U32, A06, A18, N01 |
| money.2.1 | Figure · What it means | A04, A05, A06, A15, A18, U36 |
| money.2.2 | Price table · Effective 2026-09-29; claude-opus-5-5: $4 input / $20 output; claude-sonnet-5-5: $2 / $10, per million tokens. The table is not live billing. | A04, A05, A06, A15, A18, U36 |
| money.2.3 | Batch / provider prompt cache · Eligible batch rates multiply by 0.5. Cache writes multiply base input by 1.25 for 5m or 2 for 1h; default-model read multipliers 0.05 / 0.1. Local result reuse is separate from paid provider prompt caching. | A04, A05, A06, A15, A18, U36 |
| money.2.4 | Search surcharge · Table adds $0.01 per server search to analysis usage where reported. Chat's displayed estimate omits this surcharge; fetch content still consumes tokens. | A04, A05, A06, A15, A18, U36 |
| money.2.5 | Run usage · Append-only records carry reported tokens, transport/model and calculated cost. Interrupted output can be unreported, so totals can be lower bounds. Failed attempts with missing usage are not a reliable zero-cost record. | A04, A05, A06, A15, A18, U36 |
| money.2.6 | Fallback discrepancy · Some fallback models cost more than the requested default, but run pricing uses the requested model; an apparently precise total can understate the provider bill. | A04, A05, A06, A15, A18, U36 |
| money.2.7 | Estimate versus exact · Provider-reported counts are exact for the usage fields actually received; locally estimated images/tokens and calculated dollar figures are estimates. The provider console/invoice settles money, including failed/stopped/remote-running work. | A04, A05, A06, A15, A18, U36 |
| money.3.1 | A confirmation is not a spending stop | U16, U28, U35, U36, A05, A14, A15, A18 |
| money.3.2 | Analyze asks before work begins. It does not enforce the estimate as a cap. Retries, repeated reads, citations and investigations can add spend automatically; chat has no cost-confirmation dialog. Quitting, Stop or an export failure does not roll back provider charges. | U16, U28, U35, U36, A05, A14, A15, A18 |
| limits.1.1 | It does not certify code compliance, safety, design adequacy or a complete defect list. A fluent model can quote accurately and interpret incorrectly; compare the actual drawing and governing specification/code. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.2 | It does not prove the specifications you attach are complete, current or applicable. The warning asks you to judge that; extracted text/truncation records cannot establish it. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.3 | A wrong PDF text layer, raster-only page, faint linework or ambiguous quote can produce confident errors. Crops and location/status fields help you inspect them; extraction is not a guarantee against a wrong digit. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.4 | Parsers, list/text caps, shard reconciliation limits and prose filtering can omit items. Partial/discard accounting explains recorded losses; it cannot count defects the model never proposed. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.5 | Agreement between repeated reads is not independent validation. Crop/citation checks are also model judgments; missing context, paywalls and edition confusion can produce a confident wrong verdict. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.6 | There is no desktop analysis Stop, resumable project save/load, application undo of a paid run, universal request transcript, or global dollar ceiling. Chat Stop and transcript Save/Load have narrower effects. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.7 | Hashes prove saved bytes match a record, not that the claim is true or the record is authentic. COMPLETE and receipt coverage describe completed work, not professional sign-off. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| limits.1.8 | No warranty of correctness follows from this help or from the source license. Provider guarantees and data handling are matters for your own account/contract. | U06, U28, U36, U38, U39, A04, A06, A09, A10, A11, A12, A13, A15, A16 |
| audit.1.1 | Read Why trust it and this dossier without a connection: they remain local. In the saved report, show all findings and inspect origin/status, quote, location and rejected/index rows against the drawings. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.2 | Click Open Diagnostics Log. You will see the local session trace; it resets at the next launch. For SDK request/retry details enable DRAWING_ANALYZER_DEBUG before launch, recognizing that debug detail is still private project data and may not be a complete request transcript. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.3 | Use Export All, including for a failed run that returned a context. Open run.log and run_manifest.json: inspect input rejection/unread-page accounting, resolved configuration/models, stage outcomes, usage/transport, profile snapshots and artifact hashes. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.4 | Open findings.json and markup_manifest.json in a text editor. Compare source tags, anchors, operand provenance, crop/citation verdicts and saved annotation receipts with the reviewed PDF. Open evidence PNGs and their request/investigation records: you can see the pixels/tools the recorded checks used. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.5 | Save chat with Save and read chat_history.json. It contains questions, answers and tool results; it is not covered by the earlier run manifest. Inspect browser storage for persisted transcript/key/layout, then use New chat / Forget key and verify which copies remain. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.6 | Compare usage with your provider console/invoice; inspect its batches/files if interrupted. You may see spend absent from a stopped stream's local record or from chat's search estimate. Recompute Decimal arithmetic from the printed equation rather than trusting a verdict. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.7 | Disconnect the network and browse saved artifacts. Fresh misses and sent chat questions fail; local report navigation, copies, help and inspections work. Do not start a paid review just to test that a cached review might need the network. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.1.8 | Inspect the source and claims ledger; compare your firewall/proxy log or browser Network panel during work you intended to run. Expect the API, automatic GitHub/redirect checks, optional installer URLs and explicit clicked links; provider web research is visible at the provider side, not as direct local connections to every website. | U19, U20, U29, U33, U37, U38, A05, A11, A13, A14, A15, A18, N01, N02, N03, N04, N05, N06 |
| audit.2.1 | Anthropic privacy policy and privacy center | N06 |
| audit.2.2 | Anthropic trust center | N06 |
| audit.2.3 | Anthropic commercial terms | N06 |
| audit.2.4 | Anthropic usage console | N06 |
| audit.2.5 | Application docs and source | N06 |
| audit.2.6 | Security mechanisms | N06 |
| audit.2.7 | Claims ledger | N06 |
| audit.2.8 | Release page | N06 |
| audit.3.1 | Still not convinced? | U16, U35, A13, N01, N05 |
| audit.3.2 | Good. Use the output as a set of leads you can check. Read the source/evidence, keep uncertain items visible, verify significant claims yourself, and keep your own review record. If your project cannot be sent to your configured provider or its tools, do not approve the analysis or send chat questions. | U16, U35, A13, N01, N05 |

| Interpolated value | Source file and exact symbol | Verification |
| --- | --- | --- |
| `24` | `src/drawing_analyzer/batch_digest.py: DEFAULT_BATCH_MAX_ELAPSED_HOURS` | `test_trust_facts`; direct source read |
| `3600` | `src/drawing_analyzer/batch_digest.py: DEFAULT_BATCH_STALL_TIMEOUT_SECONDS` | `test_trust_facts`; direct source read |
| `1500` | `src/drawing_analyzer/batch_digest.py: DEFAULT_FIRST_BATCH_STALL_TIMEOUT_SECONDS` | `test_trust_facts`; direct source read |
| `4` | `src/drawing_analyzer/batch_digest.py: DEFAULT_MAX_BATCH_RESUBMIT_ROUNDS` | `test_trust_facts`; direct source read |
| `10` | `src/drawing_analyzer/batch_digest.py: DEFAULT_MAX_CONSECUTIVE_POLL_ERRORS` | `test_trust_facts`; direct source read |
| `15` | `src/drawing_analyzer/batch_digest.py: DEFAULT_POLL_INTERVAL_SECONDS` | `test_trust_facts`; direct source read |
| `120` | `src/drawing_analyzer/batch_digest.py: DEFAULT_POLL_MAX_INTERVAL_SECONDS` | `test_trust_facts`; direct source read |
| `8000` | `src/drawing_analyzer/citation_check.py: DEFAULT_CITATION_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `30` | `src/drawing_analyzer/citation_check.py: _DEFAULT_CITATION_TTL_DAYS` | `test_trust_facts`; direct source read |
| `8` | `src/drawing_analyzer/citation_check.py: _MAX_CLAIMS_PER_REQUEST` | `test_trust_facts`; direct source read |
| `3` | `src/drawing_analyzer/citation_check.py: _MAX_PAUSE_RESUMES` | `test_trust_facts`; direct source read |
| `40000` | `src/drawing_analyzer/citation_check.py: _WEB_FETCH_MAX_CONTENT_TOKENS` | `test_trust_facts`; direct source read |
| `4` | `src/drawing_analyzer/citation_check.py: _WEB_FETCH_MAX_USES` | `test_trust_facts`; direct source read |
| `10` | `src/drawing_analyzer/citation_check.py: _WEB_SEARCH_MAX_USES` | `test_trust_facts`; direct source read |
| `16000` | `src/drawing_analyzer/core/api_config.py: INVESTIGATION_OUTPUT_CAP` | `test_trust_facts`; direct source read |
| `0.5` | `src/drawing_analyzer/core/pricing.py: BATCH_DISCOUNT` | `test_trust_facts`; direct source read |
| `1h` | `src/drawing_analyzer/core/pricing.py: CACHE_TTL_1H` | `test_trust_facts`; direct source read |
| `5m` | `src/drawing_analyzer/core/pricing.py: CACHE_TTL_5M` | `test_trust_facts`; direct source read |
| `2.0` | `src/drawing_analyzer/core/pricing.py: CACHE_WRITE_MULTIPLIER_1H` | `test_trust_facts`; direct source read |
| `1.25` | `src/drawing_analyzer/core/pricing.py: CACHE_WRITE_MULTIPLIER_5M` | `test_trust_facts`; direct source read |
| `2026-09-29` | `src/drawing_analyzer/core/pricing.py: PRICING_EFFECTIVE_DATE` | `test_trust_facts`; direct source read |
| `0.01` | `src/drawing_analyzer/core/pricing.py: WEB_SEARCH_COST_PER_USE` | `test_trust_facts`; direct source read |
| `60.0` | `src/drawing_analyzer/core/updates.py: DEFAULT_DOWNLOAD_TIMEOUT` | `test_trust_facts`; direct source read |
| `8.0` | `src/drawing_analyzer/core/updates.py: DEFAULT_MANIFEST_TIMEOUT` | `test_trust_facts`; direct source read |
| `1` | `src/drawing_analyzer/core/updates.py: DEFAULT_MIN_INTERVAL_DAYS` | `test_trust_facts`; direct source read |
| `65536` | `src/drawing_analyzer/core/updates.py: MAX_MANIFEST_BYTES` | `test_trust_facts`; direct source read |
| `high` | `src/drawing_analyzer/critique.py: DEFAULT_CRITIQUE_EFFORT` | `test_trust_facts`; direct source read |
| `64000` | `src/drawing_analyzer/critique.py: DEFAULT_CRITIQUE_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `2` | `src/drawing_analyzer/critique.py: DEFAULT_CRITIQUE_RUNS` | `test_trust_facts`; direct source read |
| `60` | `src/drawing_analyzer/cross_qc.py: DEFAULT_CROSS_QC_MAX_FINDINGS` | `test_trust_facts`; direct source read |
| `16000` | `src/drawing_analyzer/cross_qc.py: DEFAULT_CROSS_QC_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `40` | `src/drawing_analyzer/cross_qc.py: DEFAULT_MAP_MAX_FACTS` | `test_trust_facts`; direct source read |
| `400` | `src/drawing_analyzer/cross_qc.py: MAX_FACTS_PER_RECONCILE` | `test_trust_facts`; direct source read |
| `40` | `src/drawing_analyzer/cross_qc.py: MAX_SHEETS_SINGLE_CALL` | `test_trust_facts`; direct source read |
| `64` | `src/drawing_analyzer/cross_qc.py: _MAX_RECONCILE_PAIR_CALLS` | `test_trust_facts`; direct source read |
| `4000` | `src/drawing_analyzer/cross_qc.py: _TEXT_LAYER_BUDGET` | `test_trust_facts`; direct source read |
| `5` | `src/drawing_analyzer/diagnostics.py: _BACKUP_COUNT` | `test_trust_facts`; direct source read |
| `2000000` | `src/drawing_analyzer/diagnostics.py: _MAX_BYTES` | `test_trust_facts`; direct source read |
| `high` | `src/drawing_analyzer/digest.py: DEFAULT_DIGEST_EFFORT` | `test_trust_facts`; direct source read |
| `2` | `src/drawing_analyzer/digest.py: DEFAULT_DIGEST_MAX_RETRIES` | `test_trust_facts`; direct source read |
| `64000` | `src/drawing_analyzer/digest.py: DEFAULT_DIGEST_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `40` | `src/drawing_analyzer/digest.py: MAX_CLAIMS_PER_SHEET` | `test_trust_facts`; direct source read |
| `40` | `src/drawing_analyzer/digest.py: MAX_FINDINGS_PER_SHEET` | `test_trust_facts`; direct source read |
| `128000` | `src/drawing_analyzer/digest.py: MAX_TOKENS_RETRY_CEILING` | `test_trust_facts`; direct source read |
| `4` | `src/drawing_analyzer/file_upload.py: DEFAULT_UPLOAD_MAX_RETRIES` | `test_trust_facts`; direct source read |
| `6` | `src/drawing_analyzer/file_upload.py: DEFAULT_UPLOAD_WORKERS` | `test_trust_facts`; direct source read |
| `high` | `src/drawing_analyzer/focus.py: DEFAULT_FOCUS_EFFORT` | `test_trust_facts`; direct source read |
| `32000` | `src/drawing_analyzer/focus.py: DEFAULT_FOCUS_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `1` | `src/drawing_analyzer/focus.py: MIN_SHEETS_FOR_FOCUS` | `test_trust_facts`; direct source read |
| `10` | `src/drawing_analyzer/investigate.py: _DEFAULT_MAX_INVESTIGATIONS` | `test_trust_facts`; direct source read |
| `6` | `src/drawing_analyzer/investigate.py: _DEFAULT_MAX_ROUNDS` | `test_trust_facts`; direct source read |
| `40000` | `src/drawing_analyzer/investigate.py: _DEFAULT_TASK_BUDGET_TOKENS` | `test_trust_facts`; direct source read |
| `4` | `src/drawing_analyzer/investigate.py: _INVESTIGATION_SHEETS_PER_EXTRA` | `test_trust_facts`; direct source read |
| `300` | `src/drawing_analyzer/investigate.py: _MAX_CROP_DPI` | `test_trust_facts`; direct source read |
| `20` | `src/drawing_analyzer/investigate.py: _MAX_FIND_TEXT_MATCHES` | `test_trust_facts`; direct source read |
| `40` | `src/drawing_analyzer/investigate.py: _MAX_INVESTIGATIONS_CEILING` | `test_trust_facts`; direct source read |
| `3` | `src/drawing_analyzer/investigate.py: _MAX_PAUSE_RESUMES` | `test_trust_facts`; direct source read |
| `60` | `src/drawing_analyzer/investigate.py: _MAX_SHEET_INDEX_ENTRIES` | `test_trust_facts`; direct source read |
| `72` | `src/drawing_analyzer/investigate.py: _MIN_CROP_DPI` | `test_trust_facts`; direct source read |
| `150` | `src/drawing_analyzer/investigate.py: _VIEW_SHEET_DPI` | `test_trust_facts`; direct source read |
| `24.0` | `src/drawing_analyzer/pipeline.py: _WORKDIR_MAX_AGE_HOURS` | `test_trust_facts`; direct source read |
| `8000` | `src/drawing_analyzer/prose_harvest.py: DEFAULT_HARVEST_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `6000` | `src/drawing_analyzer/prose_harvest.py: _HARVEST_TEXT_CAP` | `test_trust_facts`; direct source read |
| `15000` | `src/drawing_analyzer/render.py: SHEET_TEXT_MAX_CHARS` | `test_trust_facts`; direct source read |
| `high` | `src/drawing_analyzer/review_planner.py: DEFAULT_PLAN_EFFORT` | `test_trust_facts`; direct source read |
| `32000` | `src/drawing_analyzer/review_planner.py: DEFAULT_PLAN_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `60` | `src/drawing_analyzer/review_planner.py: _DEFAULT_MAX_PLAN_ITEMS` | `test_trust_facts`; direct source read |
| `medium` | `src/drawing_analyzer/set_identity.py: DEFAULT_IDENTITY_EFFORT` | `test_trust_facts`; direct source read |
| `8000` | `src/drawing_analyzer/set_identity.py: DEFAULT_IDENTITY_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `500` | `src/drawing_analyzer/source_registry.py: DEFAULT_MAX_FILES` | `test_trust_facts`; direct source read |
| `2000` | `src/drawing_analyzer/source_registry.py: DEFAULT_MAX_SHEETS` | `test_trust_facts`; direct source read |
| `400000` | `src/drawing_analyzer/spec_documents.py: SPEC_FILE_CHAR_BUDGET` | `test_trust_facts`; direct source read |
| `400000` | `src/drawing_analyzer/spec_documents.py: SPEC_TOTAL_CHAR_BUDGET` | `test_trust_facts`; direct source read |
| `high` | `src/drawing_analyzer/synthesis.py: DEFAULT_SYNTHESIS_EFFORT` | `test_trust_facts`; direct source read |
| `32000` | `src/drawing_analyzer/synthesis.py: DEFAULT_SYNTHESIS_MAX_TOKENS` | `test_trust_facts`; direct source read |
| `2` | `src/drawing_analyzer/synthesis.py: MIN_SHEETS_FOR_SYNTHESIS` | `test_trust_facts`; direct source read |
| `6` | `src/drawing_analyzer/tiling.py: DEFAULT_GRID_COLS` | `test_trust_facts`; direct source read |
| `6` | `src/drawing_analyzer/tiling.py: DEFAULT_GRID_ROWS` | `test_trust_facts`; direct source read |
| `0.08` | `src/drawing_analyzer/tiling.py: DEFAULT_OVERLAP_FRAC` | `test_trust_facts`; direct source read |
| `8000` | `src/drawing_analyzer/verify.py: DEFAULT_VERIFY_MAX_TOKENS` | `test_trust_facts`; direct source read |

Non-exported literals (`PINNED_FACTS`) are asserted against production JavaScript, verification function defaults and the installed SDK in `test_trust_facts`. Disable-switch values, the unused token-count path, model IDs and hostname routes are tested separately in this file. Percent/minute notation derives from the source overlap/stall constants. SHA-256 is the hash algorithm invoked by `hashlib.sha256` in `source_registry.py`, `run_journal.py`, `verify.py` and `core/updates.py`. SVG coordinates and document section/card ordinals are presentation, not app limits.
<!-- END GENERATED TRUST COPY MAP -->
