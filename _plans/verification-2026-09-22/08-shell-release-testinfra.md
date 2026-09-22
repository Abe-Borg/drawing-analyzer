> **Evidence snapshot, 2026-09-22.** Written by a verification agent during the plan
> review, against code identical to 1.7.0 (`da8f810`); line numbers are against that
> code. Covers: WP-02, WP-16, WP-17, WP-23, WP-24, N8, dead code. The scratch reproduction scripts it cites were **not**
> committed (several held dummy key strings the secret scan would flag); the
> reproductions are described here so a session can rebuild them as tests. Where this
> file and the plan or `PROGRESS.md` disagree, the plan and `PROGRESS.md` win.

# FINAL REPORT (complete; identical to the handback message)

Legend: SP(r) = STILL PRESENT (reproduced), SP(t) = STILL PRESENT (traced). Probes: scratchpad/verify/shell-release-testinfra/ (the 6 earlier scripts were re-run and confirmed). No repo files were modified (the ignored .pytest_cache/ predates the restart). Disclosure: one probe likely sent a GET to github.com/x/y through the local proxy (no credentials).

### 1. Verdicts

| ID | Verdict | Anchor(s) | Evidence / plan correction |
|---|---|---|---|
| G1 | SP(t) | gui.py::_on_close_request (2906-2931); ::_on_process thread (1907-1913); pipeline.py::extract_drawing_context (2528); batch_digest.py::_cancel_batch (685) | No cancel argument. The batch id reaches disk only as a diagnostics log line (batch_digest.py:1928); no job record. |
| G2 | SP(t) | gui.py::_on_key_changed (1101-1123); busy block (1851-1859); client.py::get_client (18-31); gui.py::_worker (1933-1948) | key_entry is never disabled; every stage re-reads the env. See WP-16.1. |
| G3 | SP(r) | core/api_key_store.py::load_api_key_from_file (226), ::_migrate_legacy_file_key (149-160), ::_keyring_store_verified (96-106) | Real module plus an in-memory keyring: the keyring holds the BOM-prefixed key, the file is deleted, and the next launch serves the BOM. The wire carries b'\xef\xbb\xbf…', which returns a 401. |
| G4 | SP(t) | drawing-analyzer.spec (58) collect_all("drawing_analyzer"); core/app_paths.py::executable_dir (31-33) | The review's line ":35" is wrong (the spec lost 5 lines in 1.7.0). |
| G5 | SP(t) | release.yml gates (267-275, lock only at 282); build (118-119) | requirements-release.lock has no gui/keyring pins. The tiktoken part is obsolete. |
| G6 | SP(r) | gui.py::_on_update_download_done (2800-2837); updates.py::verify_sha256 (332; its only caller is tests/test_updates.py:302) | A file rewritten during the "Install update" prompt was launched. |
| _persist_key re-entry | SP(r), handler level | gui.py::_persist_key (1125-1189); binds (453-454) | A simulated FocusOut during the modal opened 2 consent dialogs (real Tk delivery traced only). |
| Frozen keyring | SP(t) | app_entry.py::_selfcheck (46-58); spec (48-54); api_key_store (47-53) | --selfcheck passes even when keyring is absent. |
| Update dialog over modals | SP(r), handler level | gui.py::_on_update_check_done (2591-2611); auto-check (375) | The dialog is shown while _busy=True. |
| Embed fallback | SP(r) | gui.py::_on_save_html (2287), ::_export_all_worker (2362) | With the field cleared and embed on, the saved key is exported. |
| Uninstall residue / no Forget | SP(t) | installer.iss has no [InstallDelete]/[UninstallDelete]; app_config_dir() holds the key file, logs/, updates/ | — |
| check_licenses | SP(t) | scripts/check_licenses.py::main (50-86) | Checks only for UNKNOWN licenses and runs in the Linux `.[dev]` env (release.yml:282), so shipped GUI deps are never audited (same gap for pip-audit). |
| README network claim | SP(t) | README.md:74; docs/RELEASE_WINDOWS.md:131-135 | README 86-96 is already correct. |
| N8 | SP(t), and it occurred | release.yml::publish (329-375): needs build/gates/gates-windows, tag-only, no `environment:`, --latest (368) | Nothing reads docs/releases/ACCEPTANCE-*. |
| §5 betas/fallbacks | SP(r) | fake_anthropic.py::_BetaMessagesProxy (452-471); test_drawing_batch.py::_FakeBatches.create (150 +6 copies), ::_messages_stream(betas=) (224) | SDK 1.7.0 raises TypeError in all three cases; the fakes accept them. |
| §5 21,334 guard | SP(r) | no test | Bisected to 21334 for opus-5, sonnet-5 and opus-4-8; 0 requests sent. |
| §5 errored shape | SP(r) | fake_anthropic.py::batch_errored_result (337-347) | Real SDK: `.error.type=='error'`, kind in `.error.error.type`. Production tolerates both (batch_digest.py:566/624): fixture-only. |
| §5 canceled envelopes | SP(t) | test_drawing_batch.py::_StallThenSettleWithCompletedItems.results (2587-2594) | — |
| §5 iterations/fallback_credit/stop_details/fallback block | SP(t) | 0 hits in tests/ | src also never reads web_fetch_requests (goes to WP-14). |
| §5 FakeUsage 0-vs-None | SP(t) | fake_anthropic.py (43-57) | — |
| §5 FinalMessageStream | SP(r) | fake_anthropic.py (392-405) | Real SDK over an httpx2 SSE mock: a body ending without message_stop yields stop_reason=None and partial text, with no exception. digest.py (1684-1703) caches it as complete. |
| §5 batch canary | SP(t) | test_live_api_canary.py (10 tests, none batch) | — |
| §5 spec_documents panic | SP(r), env-only | spec_documents.py::_extract_pdf_text (55); except (176-177) | 3 PanicException failures here until cffi was installed. |
| §5 socket guard | SP(t) | tests/conftest.py (73-88); pytest-socket absent | A zero-arg Anthropic() resolves AUTH_TOKEN, PROFILE and ~/.config/anthropic (SDK _client.py 186-225). |
| network marker + real key | SP(r) | conftest.py (60-70); ci.yml:99 | Any exported real key makes plain `pytest` run the live canary. |
| CI ruff classes | SP(t) | ci.yml:144, release.yml:279 (E9,F63,F7,F82; clean) | An F,B run gives 95 hits: 9 src F401s, F841 `sug` at references.py:550, 3 B017, and 6 B023 at ledger.py 667-680 (false positives). |
| §7 no callers | SP(t) | api_config.py: batch_service_tier 987, token_count_preflight_enabled 1000, web_search_max_uses_for_severity 1077, cross_check_max_tokens 246, verification_max_tokens 250, cache_diagnostics_params 1255, extract_cache_diagnostics 1276; tokenizer.py::count_tokens_via_api 247 (named in CLAUDE.md:848); verify.py::_verify_cross_one 1436 | — |
| §7 test-only | CLAIM INACCURATE | cross_qc.py::_sheet_is_textless 405; annotate.py::_expand_for_markup 2710; PHASE_CROSS_CHECK 172 (test_model_capabilities.py, CLAUDE.md:936) | Plan §1.2 is right that these have test callers. |
| tiktoken | FIXED | — | The "Spec Critic" docstrings are still present: api_config.py:1, 920; app_paths.py:3. |

### 2. Plan-text corrections

**§1.2, paragraph 3 is stale**
- v1.7.0 (da8f810) is already the stable `latest` release and is offered to every install daily. The hold was bypassed, as happened with 1.6.0.
- Owner decision now (needs admin rights): demote it to prerelease (`latest` reverts to 1.6.0; 1.7.0 installs cannot downgrade), or retro-record/waive §§2–6.
- Either way, fix ACCEPTANCE-1.7.0.md (still says NOT YET TAGGED/HOLD): fill in the commit, the published-asset sha256s and the Inno version.

**WP-23 §9–12**
- Treat N8 as an incident, not a hypothetical. Ship the minimal gate in Wave 0/1, before any 1.7.x tag: a non-rc publish fails unless the record says SHIP or lists unexpired waivers.
- A tag runs the workflow file from the tagged commit, so a YAML check only stops accidents. A protected Environment or tag ruleset is the independent boundary.
- An unconfigured `environment:` is auto-created with no protection, so verify it via the API.
- Update tests/test_browser_suite_gate.py:258 (exact `needs:` string) and :231 (the "6.2.2" pin).

**WP-02**
- Step 1: the transport is `httpx2`, not `httpx` (which is not installed). SSE over httpx2.MockTransport works.
- Step 2: derive the non-streaming threshold from the SDK (ValueError, zero requests sent), not from a literal.
- Step 3: production already tolerates both error shapes. The real work is making the fakes strict: 7 `_FakeBatches.create` copies plus `_messages_stream`.
- Step 5: add a fixture for a stream that ends without message_stop (the fix itself belongs to WP-01).
- Step 6: guard `connect`/`connect_ex`/`getaddrinfo`, allowing AF_UNIX and loopback.
  - Blocking at socket creation breaks asyncio and therefore Playwright; Windows socketpair uses AF_INET loopback.
  - Delenv the proxy variables. Reproduced here: with HTTPS_PROXY=127.0.0.1:33081, loopback was allowed and traffic escaped through the proxy.
  - Delenv ANTHROPIC_AUTH_TOKEN, PROFILE, IDENTITY_TOKEN*, FEDERATION_RULE_ID, ORGANIZATION_ID and BASE_URL, and point ANTHROPIC_CONFIG_DIR at a temp dir.
  - The browser suite uses file:// and pipes with no server; 65 browser tests passed under the probe guard.
  - Make `network` an explicit opt-in and add `-m "not network"` at ci.yml:99.
- Step 7: the batch canary is not agent-runnable. Batch latency is unbounded, so the canary must bound its wait, then cancel, harvest and report.
- Acceptance: run_acceptance.py reports SKIP gates but still says overall PASS (186-211). Add a strict release mode.

**WP-16**
- Step 1: `client=` is already threaded to all 24 stage sites; only gui._worker needs to pass it. Pass a real `anthropic.Anthropic`, because a wrapper class silently disables overlap (_stage_overlap_enabled 438-440).
- Step 2: `os.startfile` (gui.py:2469, updates.py:464) and the annotation spawn pool (annotate.py:2587) cannot take a scrubbed env. The key must stop being written to os.environ (gui.py:388/1114/1121); the check at 1797 also reads it.
- Step 3: add repair of keyring entries already corrupted. The legacy file is gone and _keyring_get (69-76) serves the BOM value first. Also normalize the GUI field (1112) and save_api_key (258).
- Step 8 / WP-23.5: the self-check must use a throwaway service name; the real `DrawingAnalyzer/anthropic_api_key` entry would clobber a user's saved key. Assert WinVaultKeyring explicitly, because import errors are swallowed.
- Regressions go in tests/test_gui_lifecycle.py, which already has a fake-toolkit/stub-self harness (the conftest.py:39 comment is stale).

**WP-17**
- custom_ids are positional (`sheet__{index}`, batch_digest.py:1874). The record must map them to fingerprint, page and cache key.
- `_poll_until_terminal` and `_cancel_batch` are shared with batch_critique (53-60) and are the natural cancel hook.
- There is no CANCELED status (models.py:1722). Start with PARTIAL plus a reason.

**WP-23**
- Step 1: the package has no data files (no profiles/ dir, only .py tracked). Replace the collect_all with collect_submodules.
- Step 2: scan dist/DrawingAnalyzer/ before ISCC. Setup.exe is LZMA2 solid-compressed (installer.iss:43-44), so a scan of the installer cannot see the key. scan_secrets.py only scans git-tracked files and echoes 24 characters of each match (line 84).
- Step 3: requirements.txt (36-60) already has marker-qualified GUI pins.
- Step 4: the frozen tree has dist-info for only 3 dists, so diff the build venv's `pip freeze` instead. gates-windows (323) and ci.yml (93) are also unconstrained.
- Step 6: `x64compatible` needs Inno ≥6.3 (verify), but the fallback is pinned to 6.2.2 (release.yml:75).
- Add the missing lint step: F401/F811/F841/B017 at both ci.yml:144 and release.yml:279, and not B023/B905.

**WP-24**
- Step 1: fetch_manifest has no opener seam, and the stdlib redirect handler follows https→http and https→ftp. Use one shared opener.
- Step 6: _on_update_download_done receives only `path` (2783), so thread info.sha256 through and reuse verify_sha256.
- Step 7: there are 30 native modal sites and none is visible to a Tk grab, so a busy/modal flag is needed. `_start_update_download` already refuses while busy (2746).
- Steps 3–5: a signature library is a new Windows native dependency (cryptography is pinned Linux-only at requirements.txt:51), which ties into WP-23 locks and licensing. Key custody is human-only.

### 3. Missing items
1. N8 incident response and correcting the 1.7.0 record.
2. Repairing BOM values already in the keyring.
3. Clean-EOF streams are cached as complete.
4. web_fetch_requests is never counted.
5. License and pip-audit never run on the shipped Windows env.
6. No WP owns the lint step.

### 4. Slicing (1 session ≈ 1 PR)

**WP-02, 3–4 sessions**
- 02a: network/credential guard, network opt-in, ci `-m`. Files: conftest.py. Tests: new test_hermetic_guard.py plus a browser-suite run.
- 02b: real-SDK contract tests over httpx2, and strict fakes. Tests: test_drawing_batch.py, fake_anthropic.py. Depends on 02a.
- 02c: fidelity fixtures (nested errors, canceled envelopes, None usage, web_fetch, iterations, SSE sequences). Tests exposing WP-01/WP-14 defects land as strict xfail or with the fixes. Depends on 02b.
- 02d: batch and cancel canaries. An agent can write them but not run them (live key and budget).

**WP-16, 3 sessions**
- 16a: G3 BOM, keyring repair, shape check. Files: api_key_store.py. Tests: test_api_key_store.py.
- 16b: G2 snapshot client, entry disabled while busy, no os.environ key. Files: gui.py, client.py, pipeline.py. Tests: test_gui_lifecycle.py plus a pipeline env test.
- 16c: _persist_key guard, Forget, embed fix. Tests: test_gui_lifecycle.py, test_api_key_store.py. Depends on 16a.

**WP-17, 5–7 sessions**
- 17a (first user value): cancel_event on extract_drawing_context; a "canceled" sentinel in _poll_until_terminal that calls _cancel_batch then _harvest_abandoned_batch with no resubmit; stage checks; a Cancel button; honest batch quit wording. Closes the core of G1. Tests: test_drawing_batch.py, test_drawing_batch_critique.py, test_drawing_qc_pipeline.py, test_gui_lifecycle.py (update the close-prompt test). Soft dependency on 16b.
- 17b: keyless atomic job record (batch ids, custom_id→source/page/cache-key map, upload ids). On relaunch, list unresolved jobs and offer remote cancel.
- 17c: harvest collected results into DigestCache so a re-run is warm; validate fingerprints first.
- 17d: crash matrix, reconciliation of unresolved submissions, instance lock.
- 17e: batch refusal handling (R2). Depends on WP-01.

**WP-23, 5 sessions**
- 23a: spec allowlist, dist secret scan with redacted output, hooks pin (G4). Validated by the PR's Windows release.yml run.
- 23b: gui lock with markers, constrained gates, freeze diff, functional keyring self-check (G5). Tests: test_windows_app_entry.py.
- 23c: installer [InstallDelete] and architecture declarations. Needs manual Windows upgrade/uninstall testing.
- 23d: license allowlist run on the Windows env. Needs human approval.
- 23e: N8 gate plus `environment:`. Tests: test_browser_suite_gate.py. Needs an admin to configure protection. Wave 0.
- Lint rides with 23a or WP-22.

**WP-24, 2–3 sessions**
- 24a: redirect/host policy, size cap, re-hash before launch, dialog deferral, docs (G6 and the shell items). Tests: test_updates.py, test_gui_lifecycle.py. Fully agent-doable.
- 24b: signed manifest with a test keypair. The production key and secret are human-only. Depends on 23b.
- 24c: Authenticode (needs a certificate).
