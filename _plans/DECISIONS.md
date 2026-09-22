# Remediation decision record

Plan §4.1 requires a short decision record for the shared contracts before any
edits that depend on them. This is that record. The plan does not ask for a
separate design phase: **each contract is decided by the first slice that
needs it**, narrowly, and written down here in the same PR. Later slices
conform to it or amend it here explicitly. Any amendment is recorded in the
handoff log and names every consumer it affects.

Every entry lists the existing mechanisms to build on, because plan §1 says to
reuse sound mechanisms rather than add parallel ones. Check them against the
current code before you rely on them.

Status values: `open` (not decided yet), `decided`, `amended` (decided, then
changed; keep the history).

---

## D-1 Response outcome — `open` (to be decided by WP-01.1)

**Required decision (plan §4.1):** tell apart a finished response, a refusal, a
truncation, an interrupted stream, a transport failure, a malformed result, and
a valid inconclusive judgment. A successful HTTP envelope or parseable JSON
must never override a refusal, truncation or interruption (WP-01 step 1).

**Existing mechanisms to build on:** `digest.MAX_TOKENS_RETRY_CEILING` and the
truncation retry in both digest transports; `digest.stream_message` (streaming
is mandatory above ~21k `max_tokens`); `core.api_config.call_with_refusal_fallback`
and its `_refusal_fallback_available` latch; `verify._degrade_kind` and the
1.7.0 `VerifyResult.malformed/truncated/failed` counters;
`batch_digest.DigestUsageAttempt.terminal_status`, `ABANDONED_*` and
`DETACHED*`; `investigate`'s forced close.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-2 Stage accounting — `open` (to be decided by WP-01.3)

**Required decision:** define eligible, judged, failed, skipped,
deferred/canceled and recovered work independently of display labels. Zero
eligible work is `SKIPPED_VALID`. Any unjudged required item keeps a stage off
`COMPLETE`. Recovery by a later stage is exposed separately and never erases
the original failure (WP-01 steps 7–8, WP-22 step 6).

**Existing mechanisms:** `models.StageResult` (`expected`, one `STAGE_END` per
stage), `models.roll_up_qc_status` and the "failure flag before counts" rule in
`CLAUDE.md`, Phase 21 `coverage_status`, `CrossQCDiscardCounts` (count-only,
observational), `VerifyResult.degradation_note()`.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-3 Finding identity — `open` (to be decided by WP-03.2)

**Required decision:** keep four things separate: physical evidence identity,
reviewable claim identity, producer observation/provenance, and the display
`QC-###` number. Severity, verdict, arrival index, the mutable choice of
representative, and display numbering must not determine identity. Freeze
identities before evidence filenames and markup references exist (WP-03
steps 2–4).

**Existing mechanisms:** `models.compute_finding_id` (hashes sheet, category
and quote, so it is **not unique**: review B8), `models.assign_qc_ids`,
`Ledger.member_history`, `critique.critical_signature` /
`signatures_compatible` (shared with the A/B harness; never restate it),
`Ledger.seal()` → anchor → `reconcile_post_anchor` → `number()`. The full
consumer inventory is in plan WP-03.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-4 Cache contract — `open` (first decided by WP-01.1, completed by WP-10)

**Required decision:** every cache key names the request format actually sent,
the host validator/normalizer version, and the completeness metadata, with
explicit compatibility rules. No unsuccessful attempt is ever cached as
completed work. Affected namespaces get new versions; unrelated user caches are
never deleted (plan §2 rule 6, WP-10).

**Existing mechanisms:** content-hashed `DIGEST_PROMPT_VERSION` /
`CRITIQUE_PROMPT_VERSION`; `digest.SHARED_USER_FRAMING_STRINGS`;
`digest_cache._SCHEMA_VERSION` (manual); `render._RENDER_IDENTITY_SCHEME`;
`cross_qc._CROSS_QC_CACHE_CONTRACT`; the structured-outputs key terms
(`structured_key`, `HARVEST_STRUCTURED_PROMPT_VERSION`, verify's
`_request_shape_params`); `DigestCache` stage namespaces (`stage=identity`,
`stage=review_plan`, `stage=investigation`); `stage_cache.py`.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: see the migration register below
- Consumers affected: —

## D-5 Run lifecycle — `open` (to be decided by WP-17.1)

**Required decision:** active, cancel requested, draining/collecting,
resumable, complete, partial, failed, and unresolved-submission states. Closing
the app must never falsely promise that billing stopped (WP-17).

**Existing mechanisms:** `run_journal.RunJournal` (RUN_START … RUN_END),
`qc_status`, the batch `DETACHED` / `DETACHED_MOVING` / `ABANDONED_*`
dispositions, `_harvest_abandoned_batch`, the GUI's `_on_close_request`.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-6 Evidence ownership — `open` (to be decided by WP-13.2)

**Required decision:** distinguish an artifact that was saved, one that was
sent to the model, and one that was used in a completed judgment. Evidence
must never be deleted before the caller exports it (WP-13 step 5, WP-18
step 7).

**Existing mechanisms:** the evidence dirs (`evidence/<QC-###>/<leg>.png`),
`investigation.json`, save-before-send in `investigate.py`, the DA-033 export
copy, `pipeline._prune_stale_work_dirs` / `_tree_is_recent` (fail-safe keep).

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-7 Usage — `open` (to be decided by WP-14.1)

**Required decision:** separate the requested model, the serving model,
logical attempts, server iterations, known tokens, unknown usage, and cache
TTLs. Missing usage is unknown, never zero, and nothing is counted twice
(plan §2 rule 8, WP-14).

**Existing mechanisms:** the append-only `RunUsage` ledger of `UsageRecord`s
(derived totals), `DigestUsageAttempt` (`billable`, `terminal_status`),
`core.pricing.usage_record_cost`, `PRICING_EFFECTIVE_DATE`,
`RunUsage.is_billable_but_unpriced` (the single rule; never restate it),
`digest._message_cache_usage` (the dict-tolerant reader), `_record_usage`
(drops zero tool-use counts).

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-8 Source identity — `open` (to be decided by WP-06.2 or WP-11.1, whichever lands first)

**Required decision:** resolve every sheet and every evidence leg to exactly
one physical input revision and page, never merely a human sheet label (N6).
Human sheet IDs stay display metadata.

**Existing mechanisms:** `source_registry` (`SRC-0001` ids,
`sources_fingerprint`: path + size + mtime), the portable `stage_instance`
labels (`digest:SRC-0001:p0`), sharded cross-QC handles,
`auditors.sheet_ids.normalize_sheet_id` (the canonical form that all four
handle-comparison sites use), Phase 18C source-mutation detection on the
markup reopen.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

---

## Cache / schema migration register (plan WP-10 step 9)

Every slice that changes a cache namespace, key term, or serialized schema
adds one row. Never delete a cache directory or a historical export as a
migration.

| Namespace / schema | Old version | New version | Readable fields kept | Reusable content | Invalidation reason and scope | Slice / PR |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |
