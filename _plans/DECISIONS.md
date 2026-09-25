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

The slice named in each heading is the one `PROGRESS.md` (authoritative for
order) and plan §4.1 assign. WP-01.1 corrected the headings of D-1, D-2, D-3,
D-4 and D-7, which named other slices.

Status values: `open` (not decided yet), `decided`, `amended` (decided, then
changed; keep the history).

---

## D-1 Response outcome — `decided` (WP-01.2, [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156))

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

- **Decision.**
  - **One classifier.** `core.terminal_outcome.classify_stop_reason(stop_reason)`
    returns a `TerminalOutcome(kind, stop_reason)`. It reads the stop reason
    and nothing else, and a stage asks it **first**, before it looks at text or
    JSON. So a successful envelope, nonempty text or a parseable object never
    overrides it. This is `verify._verdict_from_response`'s stop-reason-first
    precedent, generalised. Callers read the raw value with their own
    shape-tolerant accessor (`digest._get`), so SDK objects and plain dicts
    classify alike.
  - **The kinds.** The vocabulary is SDK 1.7.0's `anthropic.types.StopReason`
    plus `BetaStopReason`'s `compaction`. The beta vocabulary counts because
    every call carrying the refusal-fallback beta travels
    `client.beta.messages`.

    | Kind | `stop_reason` | Meaning |
    |---|---|---|
    | `FINISHED` | `end_turn`, `stop_sequence` | The only kind a stage may treat as a completed read or admit to a cache. |
    | `TRUNCATED` | `max_tokens`, `model_context_window_exceeded` | Output was cut off. Only `max_tokens` has `raised_cap_may_finish`. |
    | `REFUSED` | `refusal` | Declined, with or without text. |
    | `UNFINISHED` | `None` | The reply never said how it ended: the SDK's result for a stream that ends without `message_stop` (N27). Non-streaming replies always carry a stop reason. |
    | `CONTINUATION` | `tool_use`, `pause_turn`, `compaction` | The turn handed control back. Each stage decides what that means. |
    | `UNKNOWN` | anything else: a future value, `""`, a non-string | Never finished. |

  - **Pinned to the SDK.** `tests/test_terminal_outcome.py` asserts that the
    table's keys equal `StopReason` ∪ `BetaStopReason`. An SDK upgrade that adds
    a reason fails there until it is classified; meanwhile it is `UNKNOWN`,
    which is the safe answer. Matching is strict equality: a near-miss spelling
    is `UNKNOWN`.
  - **`model_context_window_exceeded` is not retryable by a raised cap.** The
    limit it hit is the context window, not `max_tokens`, and a larger cap
    cannot make room. It is `TRUNCATED` (the output was cut off, so it is never
    admitted) with `raised_cap_may_finish` false.
  - **Distinctions that are not stop reasons** stay with each stage, and apply
    only to a `FINISHED` reply:
    - *transport failure*: the call raised, so there is no reply to classify
      (the digest's `call_error` path; verify's `DEGRADE_FAILED`);
    - *interrupted stream*: when the SDK returns, it is `UNFINISHED` (N27).
      When the stream raises, it is a transport failure, and the partial read
      is lost today; capturing it is WP-01.7;
    - *malformed result*: a finished reply the stage cannot parse (verify's
      `DEGRADE_MALFORMED`; the digest's findings-block `MALFORMED_*`
      telemetry, which never fails a sheet, because the prose is the
      deliverable);
    - *valid inconclusive judgment*: a finished reply that parses and says it
      cannot tell (verify's valid `NOT_VISIBLE`, judged under D-2).
  - **Continuations are per stage.** The digest declares no tools and never
    resumes a paused turn, so for it `CONTINUATION` is not finished. When
    investigation (`tool_use` continues its loop) and the citation check
    (`pause_turn` resumes) adopt the helper, they decide their own.
  - **How the digest applies it (WP-01.2).**
    - One ladder, `digest.digest_terminal_error(raw_text, stop_reason)`, used
      by `digest_sheet` (also behind batch's Files-API inline fallback) and by
      `batch_digest._digest_from_message` (also behind the direct-call
      rescue):
      - `REFUSED`: `refused digest (stop_reason='refusal')`, even when empty;
      - empty text: `empty digest (stop_reason=…)`, unchanged;
      - `FINISHED`: no error;
      - `TRUNCATED`: `truncated digest (stop_reason=…)`, unchanged for
        `max_tokens`;
      - `UNFINISHED`, `CONTINUATION`, `UNKNOWN`:
        `unfinished digest (stop_reason=…)`.

      The reply's text stays on the sheet for the per-sheet export; the error
      keeps it out of `combined_text` and out of both caches.
    - The raised-cap retry predicate on both transports (`digest_sheet`'s
      loop, `batch_digest._item_retry_params`) reads `raised_cap_may_finish`.
      The behaviour is unchanged: only `max_tokens` is retried.
    - Cache admission and the read side: D-4.
- **Rejected shortcuts.**
  - Treating nonempty text, or a parsed findings block, as proof of
    completion. That was the 1.7.0 ladder.
  - Treating `None` as "probably fine". It is exactly what the SDK returns for
    a stream that ended before `message_stop`.
  - Mapping an unrecognised stop reason to finished, or normalising spellings.
  - Retrying a context-window stop at a raised cap.
  - A refusal retry, or reading `stop_details`, in this slice. That is R2
    (WP-01.5), which needs the transport policy and a retry bound shared with
    the truncation retries.
  - Changing `models.FINDINGS_PARSE_OK`. The digest legitimately salvages
    `PARSED_UNCLOSED` at `end_turn`, and the classifier never looks at content.
  - Moving verification onto the helper in this slice. Verification is not an
    N4 site. Its `_verdict_from_response` / `_degrade_kind` test `max_tokens`
    and `refusal` only, which agrees with the helper on both, but they do not
    yet treat `None`, an unknown reason or `model_context_window_exceeded` as
    unjudged. Recorded on WP-01.6.
- **Version / cache changes:** see D-4 and the migration register. No prompt,
  key or schema changed.
- **Consumers affected.**
  - `digest.digest_sheet`, `batch_digest._digest_from_message`,
    `_item_retry_params` and `_parse_item`'s log line; through them the
    Files-API inline fallback and the direct-call rescue.
  - Downstream of the sheet's error: the digest stage's status and
    `items_out`, `ok_sheet_count`, `ctx.errors`, the `combined_text` failure
    note, the export's per-sheet `FAILED` status, the report's *Failed*
    badge, `run.log`, the usage ledger (the attempt is recorded `FAILED`), and,
    through `roll_up_qc_status`, the run's `qc_status`.
  - The abandoned-batch harvest resolves successes only, so a refused item it
    reads back is now resubmitted with the unresolved sheets, within the
    existing bounded rounds, as empty and truncated items already were.
  - Later adopters, which conform or amend here: the critique (WP-01.4), R2
    (WP-01.5), the remaining consumers and verification (WP-01.6),
    interrupted streams (WP-01.7), cross-QC (WP-06.3), the citation cache gate
    (WP-12.6), investigation (WP-13.4).

Added by WP-01.3: **which read a sheet keeps, when a later attempt lands**
(N16; the owner's rule, decided with measured options). It extends the digest's
handling above and restates none of it.
- **One helper, both transports.** `digest.keep_digest_read(kept, later)`
  returns the read the sheet keeps. The real-time raised-cap retry in
  `digest_sheet` calls it with the two reads, and so does every batch site that
  folds a new read into a sheet's result, through
  `batch_digest._replace_result_with_attempt_history`: the primary collect, the
  follow-up batch, the fresh-batch rounds, the direct-call rescue and the
  abandoned-batch harvest.
- **The order** (`digest._read_rank`, over the verdicts that already exist):
  finished (the ladder set no error) > a partial read with content (prose or
  findings; any non-finished kind but `REFUSED`: truncated, unfinished,
  unknown, continuation) > refused (with or without text) > nothing (an empty
  reply, an errored batch envelope, a transport failure). The later read wins
  when it ranks at least as high: of two partial reads the raised-cap one (twice
  the room), of two content-free reads the fresher error (it says why recovery
  stopped).
- **Never mixed (I-2).** The kept read's text, findings, findings note, stop
  reason and error move together. Usage is not the read's: real time sums
  every attempt onto the kept read, batch merges every attempt record onto it.
- **The kept read names what it outlived.** `_name_discarded_retry` appends to
  its error `"; retry: <the discarded read's error>"`, or `"; retry failed:
  <cleaned error>"` for a call that raised (`note_failed_retry`: the real-time
  retry and the batch direct rescue), and `"; N retries, the last: …"` for
  several (bounded however many resubmission rounds an override allows).
  `SheetDigest.read_error` keeps the read's own error and `retries_discarded`
  the count; both are runtime-only. A finished read is never given a suffix.
- **Retry decisions still read the latest attempt.** `_item_retry_params` is
  handed each round's own digest, so a discarded empty `max_tokens` read still
  earns the next raised cap. `served_by` names the batch that returned the read
  kept.
- **The harvest holds a partial read.** An abandoned batch's item that did not
  finish but carries content (`digest.is_partial_read`) becomes the sheet's
  result through the same helper while the sheet stays unresolved, so the
  rescue can only improve on it; the stalled path's rescue list comes from
  `harvest.resolved`. A content-free item is parked for its usage as before.
- **Measured before deciding** (the WP-01.3 handoff): the options were "finished
  only" (fails `test_rescue_skipped_when_followup_rejects_permanently` and lets
  an empty first read beat a retry with prose), "the first read wins ties"
  (the literal reading; drops the raised-cap read of two partials), the chosen
  order, and the session request's literal order (truncated with text above
  "the rest", which lets an empty read replace an unfinished read with prose).
  Over the whole suite the chosen order changed no read choice: every one of
  the 148 decisions outside the new tests keeps the later read, as before.
- **Rejected:** a union of both reads' findings (two transcriptions of one sheet
  beside prose that describes only one); choosing by text length (a content
  heuristic); keeping the first read unless the retry finished (above).
- **Version / cache changes:** none. Admission is unchanged
  (`digest_cache_admits`): only a finished read is stored, at either level,
  whichever read a sheet keeps, so no key, contract or schema moved and there
  is no migration-register row.
- **Consumers affected:** the sheet's `error` (so `ctx.errors`, `run.log`, the
  digest stage's errors, the report's stage table and the per-sheet export
  status), its text and findings (the per-sheet export, the report card, and
  through D-2's WP-01.3 note the held-out count), and `served_by` in the batch
  collect log.

Added by WP-01.4: **the critique adopts the classifier** (N4, critique part;
the owner's rules, decided with measured options). It conforms to the decision
above and restates none of it.
- **One site.** `critique.outcome_from_message` judges every critique read:
  the real-time `_critique_read` (so also batch's upload-failure fallback,
  `_serve_realtime`) and `batch_critique._outcome_from_envelope` for a
  `succeeded` envelope. Both cache levels on both transports follow from it,
  since each stores only a result whose every read counted.
- **The stop reason first, through the digest's ladder.**
  `digest.digest_terminal_error` gained a `noun` parameter (default
  `"digest"`, so the digest's wording is unchanged), and the critique calls it
  with `noun="critique"` before it parses anything. One ladder, not a copy.
- **What each kind means for a critique read:**
  - `FINISHED`: the read may count; the critique's own parse then decides
    (a valid findings schema, an explicit `{"findings": []}` included, is a
    judged read; a malformed body or one whose every item failed validation
    is a failed read, DA-008);
  - `TRUNCATED`: failed, `truncated critique (stop_reason=…)`. Not retried at
    a raised cap: that is not in N4's row (a note on WP-01.5 records the
    option and the shared retry bound it would need);
  - `REFUSED`: failed, `refused critique (stop_reason='refusal')`, named even
    when the reply is empty;
  - `UNFINISHED` (`None`, N27): failed, `unfinished critique (stop_reason=None)`;
  - `CONTINUATION`: failed. The critique declares no tools and never resumes
    a paused turn, like the digest, so `tool_use`, `pause_turn` and
    `compaction` read `unfinished critique (…)`;
  - `UNKNOWN`: failed, `unfinished critique (…)`.
  An empty reply reads `empty critique (stop_reason=…)`, the critique's old
  wording, unless it is a refusal.
- **A failed read keeps nothing** (the owner's decision): no findings and no
  claims, exactly like a malformed read, so nothing of it reaches the merge
  or the arithmetic auditor. Its tokens stay on its outcome and are billed
  on the sheet's record. `CritiqueResult.read_errors` (runtime-only) keeps
  every failed read's error so the stage can name it
  (`critique.critique_shortfall`, D-2's WP-01.4 note).
  - Considered and not taken: holding the read's findings and claims out
    and counting them (a stage warning and a manifest key, like N15's
    digest count); the same plus listing them in the sheet's export file and
    report card (the critique has no per-sheet surface, so the stage would
    carry them to the export); merging them marked `NOT_ASSESSED_PARTIAL`
    (it treats unfinished output as usable, against N15, and at
    `DRAWING_ANALYZER_CRITIQUE_RUNS=1` the merge stamps `NOT_APPLICABLE`
    with `reproduced=True`, so it would need a new mark).
- **Distinctions that are not stop reasons**, as above, for the critique: a
  transport failure is a call that raised (`_critique_read`'s cleaned error)
  or a batch item that did not succeed; a malformed result is a finished read
  with no valid schema or with every item invalid; a finished
  `{"findings": []}` is a valid clean read.
- **Unchanged:** `models.FINDINGS_PARSE_OK` (a finished critique read may
  still be salvaged as `PARSED_UNCLOSED`, as a finished digest may); the
  merge rule; the critique prompt and its structured-outputs contract (a
  structured read is judged by the same ladder, before the bare-JSON parse).
- **Measured before deciding** (an instrumented copy of `origin/main`, the
  whole suite): 440 critique reads, of which 389 finished and parsed, 48
  finished and failed their parse, and 3 stopped at `max_tokens` with an
  empty body. No fixture has an unfinished read with content, so the rule
  moves no pinned test: the three empty reads keep `empty critique`.
- **Version / cache changes:** D-4's WP-01.4 note and one migration-register
  row (`_CRITIQUE_CACHE_CONTRACT` 2 → 3).
- **Consumers affected:** a failed read's error (the critique stage's errors,
  `ctx.errors`, `run.log`, the report's stage table), the merge (the
  surviving read's findings are `NOT_ASSESSED_PARTIAL`), the claims, both
  cache levels on both transports, the stage status and the per-sheet usage
  record (D-2's WP-01.4 note).

## D-2 Stage accounting — `decided` (WP-01.1, [PR #155](https://github.com/Abe-Borg/drawing-analyzer/pull/155))

**Required decision:** define eligible, judged, failed, skipped,
deferred/canceled and recovered work independently of display labels. Zero
eligible work is `SKIPPED_VALID`. Any unjudged required item keeps a stage off
`COMPLETE`. Recovery by a later stage is exposed separately and never erases
the original failure (WP-01 steps 7–8, WP-22 step 6).

**Existing mechanisms:** `models.StageResult` (`expected`, one `STAGE_END` per
stage), `models.roll_up_qc_status` and the "failure flag before counts" rule in
`CLAUDE.md`, Phase 21 `coverage_status`, `CrossQCDiscardCounts` (count-only,
observational), `VerifyResult.degradation_note()`.

- **Decision.** WP-01.1 applies it to verification (N5). Other stages keep
  their own ladders until their slices adopt it or amend it here.
  - **Terms.**
    - *Eligible*: what a stage must judge, fixed by its eligibility rule
      before any call. For verification, every finding `_is_verifiable`
      admits plus every finding `_has_anchored_legs` admits.
      `VerifyResult.eligible` is set from those filters and never reads below
      the tally, so a finding that escapes the tally still counts against
      completeness.
    - *Judged*: an eligible item with a real judgment. For verification, a
      settled verdict, live or cached: VERIFIED, REJECTED, or a valid
      NOT_VISIBLE (UNCERTAIN). A valid inconclusive result is judged.
    - *Failed*: attempted, with no judgment. For verification, the calls
      `_degrade_kind` classifies malformed, truncated or failed, summed as
      `VerifyResult.not_judged`. That remains the only classifier.
    - *Skipped*: no judgment obtained, and no failed attempt counted. For
      verification: no sheet or crop, ambiguous sheet, evidence not saved, no
      client, or a pass stopped by an auth failure (`VerifyResult.skipped`).
    - *Deferred / canceled*: none exist yet. When WP-17.1 (D-5) adds
      cancellation, a canceled item is unjudged, in its own counted bucket.
    - *Recovered*: an item one stage left unjudged that a later stage judged.
  - **Status rule.** One helper, `models.item_coverage_status(eligible,
    judged)`, applied only after the stage's own failure flags. For
    verification those are unchanged: a single-crop pass that raised is
    FAILED, a cross pass that raised is PARTIAL.
    - eligible = 0: `SKIPPED_VALID`;
    - judged = eligible: `COMPLETE`;
    - judged = 0: `FAILED`. This is the all-failed rule: no eligible item
      obtained a judgment, whatever the mix of skips and failures;
    - otherwise `PARTIAL`.
  - **Surfacing.** `items_in` is eligible and `items_out` is judged. The first
    warning is `VerifyResult.coverage_note()`, which counts skips and failed
    attempts separately; each pass's `degradation_note()` follows with its
    malformed/truncated/failed breakdown.
  - **Recovery.** A stage's record is final once `_finish_stage` records it,
    and no later stage mutates it. The recovering stage reports the recovery
    on its own record. Investigation adds `recovered N of M finding(s) whose
    verification call returned no judgment; the verification stage keeps its
    <status> status`, computed from `VerifyResult.not_judged_ids` and its own
    concluded outcomes. The roll-up does not recognise recovery: a PARTIAL or
    FAILED verification keeps `qc_status` off COMPLETE even when investigation
    concluded every item. A recovery-aware roll-up is not adopted. If one is
    ever wanted, it must be derived from item outcomes and keep the original
    failure history (plan WP-01 step 8).
- **Rejected shortcuts.**
  - Counting every UNCERTAIN as judged (the 1.7.0 ladder), or counting a
    skipped item as work done.
  - Taking the denominator from the tally alone: an item that escaped the
    tally would drop out of it, and the stage could read COMPLETE.
  - A second outcome classifier beside `_degrade_kind`.
  - Rewriting verification's status after investigation. Execution order
    would then erase the failure.
  - Treating an all-skipped pass as `SKIPPED_VALID`: eligible work existed.
- **Version / cache changes:** none. No key, prompt or schema changed, and
  verification's cache admission is unchanged: only settled verdicts are
  stored, so a cache hit is always a judgment. No migration-register row.
- **Consumers affected.**
  - `pipeline._run_qc_stages`: the verification status, `items_in`/`items_out`
    and warnings; the investigation stage's recovery warning.
  - Through `roll_up_qc_status`: `qc_status`, the GUI completion line, the
    report banner and stage table, `run.log` and `run_manifest.json`.
  - `scripts/ab_sweep_drawing_analyzer.py` now qualifies such an arm as
    PARTIAL.
  - One test pinned COMPLETE on a pass whose only call was malformed; it is
    re-baselined (see the WP-01.1 handoff).

Added by WP-06.1: **cross-QC's refused items stay observational** (the owner's
decision; B6). The cross-QC ladder is unchanged. `CrossQCInvalidCounts`
(`CrossQCResult.invalid`) counts the returned items the host refused for an
invalid field, once each under the first check that refused them, on both
paths, and is count-only like `CrossQCDiscardCounts`: nothing in it feeds
`complete` or `budget_degraded`. A non-zero total becomes a cross-QC stage
warning, placed after the warnings that decide the status (they lead, as
verification's coverage note does), and the result is still cached with its
counts, so a warm run shows the same warning.
- Why not D-2's item rule: the refused items are the model's malformed output,
  not required inputs left unjudged. Every sheet was sent and read; what was
  lost is part of a reply, which the counts and the warning make visible
  (plan WP-06 step 5: "record validation losses distinctly from a clean empty
  response").
- Considered and not taken:
  - holding the stage at PARTIAL without caching: every warm run would
    re-bill the Opus call and stay PARTIAL for a stable reply, N14's shape;
  - holding it at PARTIAL with the result cached as PARTIAL: that needs a
    contract for caching a result with its status, which is WP-06.3's N14
    decision.
- Measured before deciding: the suite's fixtures produce no refused item (84
  validator calls), so no pinned status moved under either option.

Added by WP-09.1: **the prose harvest's dropped synthesis assurances are
counted observationally** (the owner's decision; N11). The harvest's ladder is
unchanged: `missing` (an enumerated item that reached no ledger entry) alone
holds the stage at PARTIAL. `HarvestResult.assurances` counts the synthesis
statements that carry a conflict signal only inside an assurance ("No
conflicts were found between M-101 and P-101.", "No conflicts noted."), which
the harvest does not take as conflicts. It has the contract of `filtered`
(P8 item 6): it reaches `prose_accounting` in `run.log` and `run_manifest.json`
and feeds neither `missing` nor `complete`.
- Why not D-2's item rule: an assurance is not an item the stage was required
  to carry through. It is never enumerated, like filler, so it is outside the
  denominator; the count exists so a rule that drops a real conflict is
  visible in the manifest.
- `filtered` keeps its meaning (the digest's Coordination/Conflict lines the
  filter removed). Since WP-09.1 it also counts filler with repeated
  qualifiers or a listed modifier (B11), which used to pass the filter.
- Considered and not taken: folding the assurances into `filtered` (one
  number, but `filtered` would stop meaning only digest lines); not counting
  them (a log line only, so a misfiring rule could not be audited from the
  manifest).
- A run whose only prose items were filler or assurances enumerates nothing,
  so its prose-harvest stage reads `SKIPPED_VALID`, as any run with no prose
  items did before.

Added by WP-09.2: **the prose harvest's per-item outcomes and its new counts
are observational** (the owner's decision; N10, plan WP-09 steps 4 and 5). The
harvest's ladder is unchanged: `missing` alone holds the stage at PARTIAL.
- **The record.** Every enumerated item gets exactly one `ProseItemOutcome` in
  `HarvestResult.outcomes`: its channel, its outcome (`matched`, `structured`,
  `degraded`, `set_level` or `missing`, `PROSE_OUTCOMES`), the structuring
  call it cost (`none`, `cache` or `live`, kept when the item later degrades),
  whether its finding folded into an entry the ledger already held, and how
  many match candidates the signature veto refused. The counters of the same
  names are the number of items with each outcome: `_record_outcome` is the
  only place they move, and it runs once the ledger holds the item's finding
  (an ingest that raised used to count one item `structured` and then
  `degraded`).
- **What is exported.** `vetoed` (items with at least one refused candidate),
  `folded`, `filtered_focus` (Focus-findings filler, counted whether or not
  focus items are harvested; counted nowhere before) and `by_channel` (per
  channel: each outcome, and `suppressed`) reach `prose_accounting`, so
  `run.log` (one line per channel) and `run_manifest.json`. The per-item
  records stay internal, as `expected_ids` does.
- **Suppressed items have no id.** Filler, synthesis assurances and focus
  filler are never enumerated, so they are counted per channel, not given ids
  from a second id space; a kept item's ordinal does not move again.
- Why not D-2's item rule: nothing in the new counts is an eligible item left
  unjudged. A vetoed item still becomes a finding (a straggler), a folded one
  still reaches the ledger through the fold (its id rides the survivor), and a
  suppressed line was never enumerated, so it is outside the denominator. The
  counts exist so the veto's cost (a structuring call per refused item) and
  the ledger's folds can be read from the manifest.
- Considered and not taken: per-channel counts only; the per-item records in
  `run_manifest.json` too; ids for suppressed items; a separate `folded`
  outcome instead of a flag (then `structured` would stop counting every item
  a call structured); focus filler counted only when focus is harvested.
- No cache or key change (no migration-register row): the structuring key
  holds the item, its section hint, the sheet id, the capped text layer, the
  source binding and the contract, never a match decision, so an item the
  veto sends to structuring is an ordinary miss.

Added by WP-01.3: **the findings held out of an unfinished read are counted
observationally** (N15; the owner's decision). A read the model did not finish
(any sheet whose digest carries an error) hands the review none of its findings
(`models.review_findings` / `held_out_findings`, the one split); they are
listed in the sheet's own export file and its report card. The count is
`DrawingContext.digest_findings_held_out` (portable sheet key → count), a
digest-stage warning placed after the stage's errors, a `findings_held_out`
field on the sheet's `SHEET_DIGESTED` event (and its *Sheets* line in
`run.log`), and `digest_findings_held_out` (`{"total", "by_sheet"}`) in
`run_manifest.json`.
- Why not D-2's item rule: every held-out finding sits on a sheet the digest
  stage already counts as failed (`items_out` excludes it; the stage is PARTIAL
  or FAILED), so no status could move; and the findings are not items the
  digest stage was required to judge.
- Considered and not taken: the count without the stage warning (manifest and
  sheet line only); listing the findings in the sheet file only (the report
  card lists them too, so the two agree); labelling them and ingesting them (a
  new `Finding` field through the ledger, the markup, the report and the CSV,
  with a merge rule for the label, and the prose harvest's skip of the same
  sheet left disagreeing); holding out only a refusal's.
- No cache or key change: the level-1 and level-2 digest caches store only
  finished reads (D-4), which hold nothing out.

Added by WP-01.4: **the critique stage adopts the item rule** (the owner's
decision; N4, critique part). It is the second stage on `item_coverage_status`,
after verification.
- **Terms for the critique.** Its items are **reads**: every sheet the run set
  out to read is critiqued `runs` times (`critique.critique_runs()`, 2 by
  default).
  - *Eligible*: `runs` × the sheets the run set out to read (`total`, the
    `list_sheets` count), never below what the stage tallied.
  - *Judged*: a read the model finished (D-1) that returned a valid findings
    object, an explicit `{"findings": []}` included. A cache hit counts all
    its reads, since only complete results are stored.
  - *Failed*: attempted, no judgment: not finished, malformed, every item
    invalid, the call raised, an errored or uncollected batch item, a batch
    submit that failed, a retained upload that was no longer available.
  - *Skipped*: no attempt, because no critique input could be obtained for
    the sheet.
- **Status.** `item_coverage_status(eligible, judged)`, after the stage's own
  failure flag (the stage raised: FAILED, unchanged). A sheet named in the
  degraded list never leaves the stage COMPLETE. So one finished read of two is
  PARTIAL, and a stage with no judged read is FAILED (the all-failed rule; it
  read PARTIAL).
- **Surfacing** (the owner's decision): `items_in` is eligible reads and
  `items_out` judged reads, as verification shows eligible → judged and the
  digest sheets set out → read (the critique showed `0 →` its finding count).
  The first warning is the coverage line, `critique: 3 of 4 requested read(s)
  judged; 0 skipped, 1 returned no judgment` (`pipeline._CritiqueReadTally`,
  the twin of `VerifyResult.coverage_note`, with `N not accounted for` when a
  sheet the run set out to read never reached the stage). The errors name each
  short sheet through `critique.critique_shortfall`: the result's own `error`
  when it has one (no read counted, or none found anything: the wording the
  stage always showed), else `<n> of <m> critique read(s) finished: <each
  failed read's error>`. The `ctx.errors` summary line is unchanged.
- **The gap this closes.** `result_from_outcomes` keeps `error=None` for a
  sheet whose surviving read shipped findings (they carry
  `NOT_ASSESSED_PARTIAL` instead), and `_ingest_miss` degraded a sheet on
  `error` alone, so a sheet with one read failed read COMPLETE, cached nothing,
  and was critiqued and billed again on every warm run, reading COMPLETE each
  time. D-1's WP-01.4 note makes that shape common (a cut-off second read), so
  the rule had to move with it.
- **The per-sheet usage record agrees** (the owner's decision):
  `terminal_status` is COMPLETE only when every requested read counted, FAILED
  when none did, else PARTIAL, and `parse_success` is true only for COMPLETE.
  It used to read `error` alone (COMPLETE with one failed read beside findings,
  PARTIAL with none). Per-read records stay WP-14.5's.
- **A stand-in stage that reports no counts** (tests replace
  `_run_critique_stage` with a function returning the 3-tuple) keeps the
  degraded-list rule: the counts ride a `read_tally` sink, not the return
  value, so the 3-tuple and its callers are unchanged.
- **Considered and not taken:** degrading a short sheet in `_ingest_miss` only
  (the critique keeping its own ladder, all-failed PARTIAL); setting
  `CritiqueResult.error` for every short sheet (the same statuses, but it moves
  `test_one_failed_run_still_merges_the_other`, which pins `error is None`, and
  changes `error`'s meaning for four unit results); keeping today's rule and
  recording the gap on a later slice.
- **Measured before deciding** (each rule applied in an instrumented scratch
  copy over the 30 test files that exercise the critique, 1,621 tests): no
  pinned test moves under the chosen rule; 12 fixture runs whose every
  critique read fails (fakes whose critique reply has no findings object, or
  raises) read FAILED instead of PARTIAL, their `qc_status` unchanged
  (PARTIAL), and their usage records FAILED instead of PARTIAL.
- **No cache or key change** from the rule itself (D-4's WP-01.4 note covers
  the admission change).

Added by WP-11.1 ([PR #172](https://github.com/Abe-Borg/drawing-analyzer/pull/172)): **the digest stage's eligible items are the inventory's
pages** (the owner's decisions; R1). The digest stage already had D-2's shape
(`items_in` the sheets the run set out to read, `items_out` the sheets read;
COMPLETE when every one was read, FAILED when none was, else PARTIAL), and its
ladder is unchanged. What changed is the count behind `items_in`: it is the
inventory's pages (D-8's page part), no longer a recount by reopening the files
that silently skipped one it could not open, so a source lost after the
inventory used to be on neither side of the ratio, and a source rewritten with
fewer pages read COMPLETE.
- **Terms for the digest.** *Eligible*: every page of every accepted inventory
  document. *Judged*: a page with a digest that read (`SheetDigest.ok`).
  *Failed*: a page whose read errored or came back empty (a `SheetDigest` with
  an error). An **unread page** (no digest at all: its source could not be
  opened again, it is past its source's current end, it would not load or
  render, or no outcome was recorded) is an eligible item with no judgment and
  no read, so it counts against completeness like a failed read; it is surfaced
  as a `models.UnreadPage` (`ctx.unread_pages`, `unread_pages` in
  `run_manifest.json`, a `NOT READ` line in run.log's Sheets section) and one
  `PAGE_UNREAD` journal event, never as a `SheetDigest` (which claims a read).
- **One line per source** for a source-level failure in `ctx.errors` and the
  stage's errors (sorted and bounded, as before); the per-page detail rides the
  records and events.
- **A source with more pages than the inventory counted** is observational for
  the stage (one warning; every page the run owed was read, so it stays
  COMPLETE) and one run error, so the run reads PARTIAL.
- **The critique** (WP-01.4's note) counts `runs` x the inventory's pages as its
  eligible reads, as before through `total`; since it now takes the same pages,
  a page it cannot obtain is *skipped* and named in its errors with the reason,
  where a source it could not reopen used to be "not accounted for".
- Measured before deciding: under every option offered, no pinned test moved;
  the chosen shape adds one `PAGE_UNREAD` event in the 3 fixtures with a page
  that does not render.

Added by WP-11.2 ([PR #173](https://github.com/Abe-Borg/drawing-analyzer/pull/173)): **a digest phase stopped by an unexpected error reads FAILED,
whatever was read** (the owner's decision; R1). D-2 tests a stage's own failure
flag before its counts, and a contained failure in the digest phase is that
flag. It covers anything but a source or page failure: the prescan, either
transport, a caller's callback, the cache, the level-1 store, the accounting.
- **Items keep their meaning.** `items_in` is the inventory's pages and
  `items_out` the pages read. The failure is the stage's first error, the same
  line `ctx.errors` carries once (the exception's type name only).
- **Unreached pages.** A page the phase never reached is an unread page whose
  reason names the failure (`not read: the digest phase stopped early
  (<Type>)`). It has no per-page line: the one run-level line counts it. A page
  that failed on its own keeps its own reason and line.
- **Why FAILED even when every page was read.** In 5 of the 22 cases measured
  every page was read before the failure (a level-1 store, a batch poll, a
  cached run). The run stops after the phase with no QC stage recorded, so the
  digest stage alone decides an exhaustive run's QC status. Under the item rule
  capped at PARTIAL, such a run reads QC PARTIAL ("Completed with QC
  warnings"). Uncapped, 2 Economy cases where no QC stage ran read COMPLETE
  ("Exhaustive QC complete"). FAILED reads QC FAILED. The run outcome is
  unchanged in kind: PARTIAL when a page was read, FAILED when none was.
- **Considered and not taken:** the item rule capped at PARTIAL; the item rule
  uncapped (a false COMPLETE).
- **Measured before deciding:** no pinned test moved under any option (2,109
  tests in the 41 files that reach the digest phase, its transports or the
  spool); the containment never fires in them.
- **No cache, key, prompt or schema change.** `run_manifest.json` gains no
  key: its `unread_pages` lists the pages not reached, and the journal gains one
  event type (`DIGEST_PHASE_STOPPED`) and a `stopped` field on `RUN_END`. No
  migration-register row.

## D-3 Finding identity — `open` (to be decided by WP-03.4)

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

Added by WP-03.3 ([PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161)), as an input, not a decision:
`Finding.claim_discriminator`, a canonical statement of what a finding asserts,
set only by a producer that can state it exactly. Today only the arithmetic
auditor sets one (`auditors.arithmetic.arithmetic_claim_discriminator`: the host
operation, the terms as a multiset of exact decimals, the stated value, under the
versioned scheme `arithmetic/1`). Two findings that both carry one and disagree
are never duplicates (`critique._claims_differ`, in both ledger passes); one on a
single side never blocks. It is folded into `id` (`compute_finding_id`'s last
argument, only when non-empty, so every other id is unchanged), rides the
representative's bundle, and is serialized only when set. Whether `claim_id`
builds on it is WP-03.4's call; WP-03.7 (N28) may give model findings one.

Added by WP-03.7, as an input, not a decision: **what may fold two findings.**
Position is not evidence that two findings make one claim. The merge predicate
(`critique._is_duplicate`, both ledger passes and the critique's `_cluster`)
reads no anchor rectangle: its geometry branch (IoU > 0.5 plus an equal quote,
no text check) is removed. The anchor stage resolves each rectangle from the
finding's own quote (and its tile, to choose among repeated occurrences), so two
findings quoting one string share a rectangle by construction, and the branch
was the quote-alone rule the quote branch refuses on purpose. It folded two
different issues that quote one tag (`PUMP P-1` voltage / impeller) once both
anchored. An equal quote therefore needs at least moderate text agreement (0.4)
before and after anchoring, and a same-spot paraphrase with less (the `CO-1`
pair, 1 of 11 content words) stays two findings: the decided cost (plan §2.1).
Since nothing the remaining branches read changes with anchoring, Pass B folds
nothing Pass A refused.
- Considered and not taken, with the owner's choice recorded in the WP-03.7
  handoff: a claim discriminator for model findings (the host cannot derive one
  that separates the pair, since both sign as `{tags: [P1]}`; a model-emitted
  one needs digest and critique prompt changes that re-bill every cached read);
  a geometry branch that needs one content word shared outside the quote (a
  threshold at one word; two different pump issues sharing "conflicts" still
  folded); geometry only between findings anchored before ingest (keeps N28
  between auditors).
- For WP-03.4 and WP-03.6: an anchor rectangle is evidence of *where*, never of
  *which claim*. Per-observation anchors (WP-03.6) map evidence; they do not
  make two observations one.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-4 Cache contract — `open`: started by WP-01.2 ([PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156)), completed by WP-10.4

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

- **Decision, WP-01.2's part: digest cache admission and the N4 read side.**
  - **Admission.** A digest is written to either level only when
    `digest.digest_cache_admits(error, text, stop_reason)` holds: no error,
    nonempty text, and a `FINISHED` stop reason (D-1). Users: the level-2
    writers of both transports (`digest_sheet`, `_digest_from_message`) and the
    pipeline's level-1 store-under-both. The stop reason is tested directly,
    not only through `error`, so the write rule and the read rule are one rule.
  - **Read side.** All three digest loaders go through
    `digest.sheet_digest_from_cache_entry`, which returns `None` (a miss)
    unless the entry's stored `stop_reason` is `FINISHED`. The three are level 2
    in `digest_sheet`, level 2 in `batch_digest.submit_drawing_batch`, and
    level 1 in `pipeline._level1_partition`. Before WP-01.2, all three forced
    `error=None` on whatever they read.
  - **A stored `null` and a missing key are both misses.**
    - `"stop_reason": null` is the N27 shape. Every digest writer stores the
      key, so `null` means the read never reported how it ended.
    - No key at all was written by nothing in this repository's history.
      Checked with `git log -S` over the full history (464 commits; root
      `87326ce`, 2026-06-07, the extraction from Spec Critic):
      - both level-2 writers have stored `"stop_reason": stop` since the root
        commit;
      - `cache_entry_from_digest` has stored `sd.stop_reason` since level 1
        was added (`53ab354`, 2026-07-09);
      - every key folds `_SCHEMA_VERSION`, which has been 10 since `b8399f4`
        (2026-09-10), so a reachable entry was written by code from that
        commit on;
      - the legacy-JSON importer admits only entries at the current schema,
        and the JSON store was retired at `f4a7dd6` (2026-07-20), at schema 8;
      - the Spec Critic predecessor used another state directory.

      So serving a keyless entry would be the one fail-open hole in a
      fail-closed rule, and rejecting it discards no digest this application
      paid for.
    - The session request called `2d176bb` the import commit. It is a
      2026-09-04 commit ("Address Codex review: three cache and accounting
      gaps"); the root is `87326ce`. Both predate schema 10, so the
      conclusion does not change.
  - **What the reject can discard.** The truncation guard (`f56796b`, schema
    9) landed before schema 10 (`b8399f4`), on the same day, so no entry a
    released version wrote under schema 10 (1.6.0, 1.7.0) holds a nonempty
    `max_tokens` read. The entries now rejected can only be shapes 1.6.0 and
    1.7.0 admitted wrongly: a refusal that carried text, a `null` (N27), or
    another non-finished stop reason. Each is read again on the next run, and
    a finished read overwrites it. Every `end_turn` / `stop_sequence` entry is
    still served.
  - **Rejected entries stay on disk.** Nothing is deleted (plan §2 rule 6). A
    sheet that keeps failing keeps missing, and is re-read each run.
  - **No `_SCHEMA_VERSION` bump and no new key term.** The bump feeds all seven
    key builders and would discard every paid digest. A key term would orphan
    every finished entry as well. The stored data already carries what the
    read side needs, so the read-side reject is the one mechanism.
- **Still open, for WP-10.4:** the cache map with the admission predicate of
  every write (critique, identity, review plan, citation, investigation, the
  stage caches) and the rest of the register. The critique's admission change
  is WP-01.4's, below.
- **Added by WP-04.1: the critique namespace has its own contract term.**
  `digest_cache._CRITIQUE_CACHE_CONTRACT` (1 since WP-04.1) is folded inside
  both critique key builders and nothing else, from the module rather than by
  callers, so the pre-render probe and the store cannot disagree. A critique
  entry stores post-merge findings, so the host merge rule is part of its
  meaning, and a change to that rule (WP-04.2) or to what a critique entry
  admits (WP-01.4) **bumps this term**. It never adds a second one, and never
  bumps `_SCHEMA_VERSION` (plan §2 rules 6 and 15: one mechanism per change,
  and no global schema change without a changed contract).
  `tests/test_drawing_cache_identity.py` pins the merge rule's fingerprint per
  contract value, so a rule change that forgets the bump fails.
  WP-04.2 bumped it to 2 for the compatibility rule (N1); see the migration
  register.
- **Added by WP-01.4: the critique's admission, and the same term, 2 → 3**
  (N4, critique part). A critique entry is written, at either level and on
  either transport, only for a result whose every requested read the model
  finished with a valid findings object (`completed_runs == requested_runs`).
  The three writers keep their existing conditions (the real-time level-2
  store in `critique_sheet_self_consistent`, the batch level-2 put in
  `collect_critique_batch`, the pipeline's level-1 store-under-both in
  `_ingest_miss`); what changed is what `completed_runs` counts (D-1's WP-01.4
  note), so no writer's code moved. Folding the three spellings into one
  predicate is WP-10.4's cache map.
  - **Why the term and not a read-side reject.** A critique entry stores no
    stop reason, so an entry written under contract 2 cannot be checked on the
    way out, and it may hold a cut-off, refused or unfinished read merged as a
    complete, corroborating one. The bump retires every such entry; a
    read-side reject beside it would be dead code and a second mechanism for
    one change (plan §2 rule 15). Never `_SCHEMA_VERSION`.
  - **No stored stop reasons** (the owner's decision). Every read an entry
    holds finished, by the admission above, so a stored per-read stop reason
    would always be `end_turn` or `stop_sequence` and carry nothing the term
    does not. WP-10.4 can still add one without a key change: a contract-3
    entry that lacks it is known-finished by the contract.
  - **The merge rule is unchanged**, so its fingerprint is pinned under 3 as it
    was under 2 (`63dbfe17…`); a rule change that forgets the next bump still
    fails there.
  - **The migration.** Every critique entry written under 2 misses once and is
    re-critiqued (one cold critique pass on the next exhaustive run); it is
    left on disk. No release shipped contract 1 or 2, so a user upgrading from
    1.7.0 pays one miss per sheet for all three bumps. Digest, identity,
    review-plan, citation and investigation keys are byte-identical (pinned).
- **Added by WP-03.3: stored claims and a changed claim dedup.** Critique and
  cross-QC entries store numeric claims already de-duplicated, and WP-03.3
  changed that de-duplication (exact decimals, terms as a multiset,
  `arithmetic.claim_content_key`). No term is bumped for it: claims have one
  consumer, the arithmetic auditor, whose own dedup (the last before any count
  or finding) applies the same canonical form, so a warm entry holding two
  spellings of one claim yields what a cold run yields. The one exception is
  recorded in the migration register (cross-QC dedups on a lowercased quote,
  the auditor on the quote as written). The critique merge rule did not change
  (`_is_duplicate` gained a gate that only fires on two findings that both
  carry a claim discriminator, and no critique finding carries one), so the
  pinned fingerprint holds and the critique term stays at 2. The arithmetic
  findings' new ids re-key `stage=investigation`: that is the key's own
  mechanism (the id is one of its inputs), so no term is added there either.
- **Added by WP-07.2: a stricter number parser under stored claims.**
  `arithmetic.parse_number` and the quote/span scanner now refuse a token that
  is not one value (`1e3`, `24x12`, a tag's digits), which feeds
  `claim_content_key` and so the claim dedups. No term is bumped: every change
  only turns a parse into `None` (a claim becomes unusable) or leaves it as it
  was, so no finding that is still produced changes its text, discriminator or
  id, and stored claims are re-parsed by the auditor on every read. The one
  effect on stored entries is a dedup residual, recorded in the migration
  register. The relationship check reads the quote and the sheet's words, not
  the claims contract, which is unchanged (plan WP-07 step 4).
- **Added by WP-05.1: the cross-QC contract term for host-side grounding.**
  `cross_qc._CROSS_QC_CACHE_CONTRACT` covers the host binding that no key input
  covers: which legs and facts the validators admit, the `evidence_state` each
  stores, and the fact a reconciled leg takes its tile from. WP-05.1 changed
  all of them for byte-identical inputs (a real, whole-word match at any length
  on the anchor's normalizer; B5, N12, N13), so it **bumps this term** 3 → 4,
  the P8 item 11 precedent. No key term was added beside it (plan §2 rule 15),
  and it is not split by path: the whole-set path grounds nothing yet, so its
  entries' content would be unchanged, but the two paths share one contract,
  and a path-conditional term would be a second mechanism for one change.
  WP-06.2's whole-set grounding changes what that path admits, and bumps the
  same term.
- **Added by WP-05.2: the same term again, 4 → 5.** Cross-QC and the anchor now
  match through one matcher (`anchor.SourceWords`), which folds the brackets
  and sentence punctuation off every word of the text and the quote (B4; the
  owner's decision), so cross-QC admits legs and facts it used to drop, for
  byte-identical inputs, and the fact-tile join keys on the same folded form.
  One mechanism again: the term, no key term. The anchor
  stage has no cache; the verification and investigation keys carry each
  finding's anchor, so a moved anchor re-keys those entries through the keys'
  own inputs (new paid work, not a contract change).
- **Added by WP-06.1: the same term, 5 → 6, beside a prompt edit.** Two
  changes, each with its own mechanism. The persona sentence changed (B6: an
  uncertain conflict is category `question` with severity `low`), and the
  three prompts are key inputs verbatim, so that edit re-keys every entry
  through the key's own mechanism. Separately, the host-side binding changed
  for byte-identical inputs: `_drop_exact_repeats` keeps every finding that is
  not identical in every field, where `_dedup_findings` folded two different
  conflicts sharing a primary sheet, category, quote and legs (N2); a fact
  whose quote is only whitespace is no longer sent to the reconciler; and the
  stored result carries its refused-item counts. That is what the contract
  term exists for, so it is bumped. This is not "a bump and a key term for one
  change" (plan §2 rule 15): each mechanism covers its own change, and if the
  prompt edit were ever reverted the bump would still keep a warm entry from
  serving a finding set the host no longer produces. No key term was added.
- **Rejected shortcuts.**
  - A `_SCHEMA_VERSION` bump: it discards every paid digest.
  - A new key term for the same change, and a bump and a term together.
  - Treating a missing `stop_reason` key as legacy and servable.
  - Deleting a rejected entry.
- **Version / cache changes:** see the migration register below.
- **Consumers affected.** The three digest loaders. A rejected entry is a
  miss, so it no longer counts in the level-1 prescan hits (`CACHE_PRESCAN`)
  or `ctx.cached_sheet_count`, and on a warm run that sheet renders and is
  read again.

## D-5 Run lifecycle — `open` (to be decided by WP-17.1)

**Required decision:** active, cancel requested, draining/collecting,
resumable, complete, partial, failed, and unresolved-submission states. Closing
the app must never falsely promise that billing stopped (WP-17).

**Existing mechanisms:** `run_journal.RunJournal` (RUN_START … RUN_END),
`qc_status`, the batch `DETACHED` / `DETACHED_MOVING` / `ABANDONED_*`
dispositions, `_harvest_abandoned_batch`, the GUI's `_on_close_request`.

**Input from WP-11.2** ([PR #173](https://github.com/Abe-Borg/drawing-analyzer/pull/173); not a decision of this contract). A digest phase
stopped by an unexpected `Exception` ends the run after the phase, with a
closed journal (`RUN_END` `stopped="digest"`) and an exportable partial
context. `KeyboardInterrupt` and `SystemExit` are deliberately not contained,
since cancel is this contract's. On such an exit:
- no context or journal is returned;
- `@_with_run_release` still removes the render spool and releases the
  retained digest uploads;
- the real-time digest waits for its reads in flight before propagating, as
  the pool's exit always did;
- a batch in flight is neither cancelled nor harvested, and its uploads stay:
  the submit and collect guards catch `Exception` only.

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

## D-7 Usage — `open` (to be decided by WP-14.4)

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

## D-8 Source identity — `open`: the page part decided by WP-11.1 ([PR #172](https://github.com/Abe-Borg/drawing-analyzer/pull/172)), completed by WP-06.2

**Required decision:** resolve every sheet and every evidence leg to exactly
one physical input revision and page, never merely a human sheet label (N6).
Human sheet IDs stay display metadata.

**Existing mechanisms:** `source_registry` (`SRC-0001` ids,
`sources_fingerprint`: path + size + mtime), the portable `stage_instance`
labels (`digest:SRC-0001:p0`), sharded cross-QC handles,
`auditors.sheet_ids.normalize_sheet_id` (the canonical form that all four
handle-comparison sites use), Phase 18C source-mutation detection on the
markup reopen.

- **Decision, WP-11.1's part: the pages a run owes** (the owner's decision,
  asked before any code, measured first; R1). WP-11.1 landed before WP-06.2, so
  it decides the part it implements, narrowly.
  - **A sheet the run owes is one page `(source_id, page_index)` of an ACCEPTED
    inventory document**, keyed by `models.source_page_key` (its `source_id` is
    the inventory's `SRC-####`). The pipeline's run-local merge key
    (`_refkey`: `(str(path), page_index)`) names the same page.
  - **The pages a run owes are exactly the inventory's.**
    `render.inventory_sheet_refs(inventory)` builds them from the accepted
    documents' page counts, in input order, **without reopening a file**, and
    both page iterators take `InputInventory.expected_page_counts()`. No stage
    recounts by reopening: the pipeline no longer calls `list_sheets` (it
    skipped a file it could not open), and the critique takes the same refs
    (`list_sheets` stays only as its fallback for a direct caller).
  - **The inventory's `content_sha256` (with `byte_size` and
    `initial_mtime_ns`) is the revision the run set out to read.** This slice
    does not bind a reopen to it (WP-11.3). What it does bind: a page past the
    source's current end is unread (`render.PageNotInSourceError`), extra pages
    are not read and one run error names the source, and the level-1 render
    identity keeps hashing the bytes on disk at prescan time with the opened
    file's own page count (unchanged, §10.6), so no key moves.
  - **Human sheet ids and the `page k/N` label stay display metadata.**
    `SheetRef.page_count` is the inventory's count, so the label follows the
    revision the run set out to read; it is model-visible and in no key (K1,
    WP-10.1).
  - **Every page the run owes ends with an outcome**: a digest, or a
    `models.UnreadPage` with a path-free reason (D-2's WP-11.1 note).
- **Still open, for WP-06.2 (and named):** binding every evidence leg and the
  whole-set cross-QC's handles to this identity instead of a human label
  (first-wins label maps, N6); the colliding `stem-pN` fallback ids. Revision
  binding on every reopen (verify, investigate, markup) is WP-11.3's, under
  this decision's revision clause.
- **Rejected shortcuts** (each measured on `a7dd050`):
  - catching the open in both iterators and continuing, with the denominator
    from `list_sheets`: every abort became a silent `COMPLETE` (batch, second
    source gone: 2 of 4 pages, digest COMPLETE 2/2, no error line);
  - the inventory denominator with the iterators unchanged: a source rewritten
    with fewer pages read digest PARTIAL with no error line and a COMPLETE run;
    with more pages the real-time path raised `IndexError` without a cache,
    and with one the extra page was digested, billed and dropped by the merge;
  - reading a changed source's extra pages: the denominator moves after the
    fact, and pages the inventory never counted are billed;
  - failing a whole source on a page-count change: revision binding by page
    count alone, while a same-count rewrite is still read until WP-11.3.
- **Version / cache changes:** none. For an unchanged set the refs equal
  `list_sheets` field for field, and the render identity keeps the opened
  file's count, so every level-1 and level-2 key is byte-identical
  (`tests/test_drawing_cache_identity.py` passes unchanged). No
  migration-register row. `run_manifest.json` gains one additive key,
  `unread_pages`.
- **Consumers affected:** the pipeline's `total` and everything built on it
  (the digest stage's `items_in`, `ctx.sheet_count`, `RUN_END`'s
  `sheets_total`, the critique's eligible reads, progress), the two iterators
  (`expected_pages`), `_level1_partition` and `_critique_level1_partition`
  (an expected page they could not scan is a miss), `_GeometryOmissionSink`
  (inserts a routed page's geometry in page order), `ctx.unread_pages`,
  run.log's Sheets section, `run_manifest.json`, and the failed count of the GUI
  and the report (`sheet_count - ok_sheet_count`).

---

## Cache / schema migration register (plan WP-10 step 9)

Every slice that changes a cache namespace, key term, or serialized schema
adds one row. Never delete a cache directory or a historical export as a
migration.

| Namespace / schema | Old version | New version | Readable fields kept | Reusable content | Invalidation reason and scope | Slice / PR |
|---|---|---|---|---|---|---|
| Digest cache, level 1 and level 2 (`digest_cache_key_level1`, `digest_cache_key`) | schema 10 | schema 10 (no version, key or term change) | Every field | Every entry whose stored `stop_reason` is `end_turn` or `stop_sequence` | Read-side reject (N4, N27; D-4). An entry that records `refusal`, `max_tokens`, `model_context_window_exceeded`, `tool_use`, `pause_turn`, `compaction`, `null`, any other value, or no `stop_reason` key is a miss. Only those entries are affected. They stay on disk, and a finished re-read overwrites them. Released 1.6.0 and 1.7.0 could have written the refusal and `null` shapes | WP-01.2, [PR #156](https://github.com/Abe-Borg/drawing-analyzer/pull/156) |
| Critique cache, level 1 and level 2 (`critique_cache_key_level1`, `critique_cache_key`) | schema 10, no critique term | schema 10, `critique_contract=1` (`digest_cache._CRITIQUE_CACHE_CONTRACT`) | Every field; the entry shape is unchanged | None: every critique entry written before WP-04.1 misses once | The quantity tokenizer behind `critique.critical_signature` changed (B2, B3, B12, N19), and a critique entry stores post-merge findings, so an old entry holds merges the new rule would not make. One mechanism: a new critique-scoped term folded inside both critique builders, never `_SCHEMA_VERSION`, which feeds every builder (the v10 bump did this for a signature change and re-billed every digest). Digest, identity, review-plan, citation and investigation keys are byte-identical, pinned by `tests/test_drawing_cache_identity.py`. Old entries stay on disk; the next exhaustive run re-critiques each sheet once. A later change to the merge rule bumps the same term (WP-04.2, WP-01.4) | WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157) |
| A/B harness arm records (`scripts/ab_findings_diff.RECORD_CONTRACT_VERSION`) | 2 | 3 | Every field | None: `load_arm_records` refuses a v2 sidecar (`RECORDS_STALE_CONTRACT`) rather than compare it | A record stores `critical_signature` computed when its arm ran, so a v2 record carries the old tokens and would report a tokenizer change as a model difference. Refused, never deleted: re-run the arm | WP-04.1, [PR #157](https://github.com/Abe-Borg/drawing-analyzer/pull/157) |
| Critique cache, level 1 and level 2 (`critique_cache_key_level1`, `critique_cache_key`) | schema 10, `critique_contract=1` | schema 10, `critique_contract=2` | Every field; the entry shape is unchanged | None: every critique entry written under contract 1 misses once | The compatibility rule behind `critique.signatures_compatible` changed (N1): `critique.signature_conflicts` compares quantities per kind and tags by inclusion, so one shared value or tag no longer makes two findings compatible. A critique entry stores post-merge findings, so an entry stored under contract 1 can hold a merge the new rule refuses (`6 in` and `4 in` beside a shared `100 psi`). One mechanism: the existing critique-scoped term, bumped; never `_SCHEMA_VERSION` and never a second term. Digest, identity, review-plan, citation and investigation keys are byte-identical, pinned by `tests/test_drawing_cache_identity.py` (`test_wp_04_2_moves_every_critique_key_and_no_other_key`); the merge-rule fingerprint is pinned under the new value. Old entries stay on disk; the next exhaustive run re-critiques each sheet once. The A/B record contract is not bumped: a record stores the signature's tokens, which did not change, and the rule is re-applied when two records are compared | WP-04.2, [PR #158](https://github.com/Abe-Borg/drawing-analyzer/pull/158) |
| Investigation cache (`stage=investigation`, `investigate._payload_hash`) | key over the finding's content `id` (sheet, category, quote, source) | the same key; an arithmetic finding's `id` now also folds its `claim_discriminator` | Every field; the entry shape is unchanged | Every entry except those for an arithmetic finding, or for a merged entry whose representative is one | The `id` is one of the key's inputs, and every arithmetic finding's `id` changed so that two mismatches on one table row no longer share one (B7). Only a mismatch checked against model-transcribed numbers is ever investigated (it starts UNCERTAIN; investigation takes it only if it is anchored and verification leaves it UNCERTAIN), so only those entries miss once and are investigated again (a paid call per finding, exhaustive runs only). One mechanism: the id change itself; no key term added, no `_SCHEMA_VERSION` bump. Every other finding's `id` is byte-identical (`compute_finding_id` appends the discriminator only when non-empty; pinned by `tests/test_drawing_models.py`, `tests/test_source_identity.py`). Old entries stay on disk | WP-03.3, [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161) |
| Critique cache, level 1 and level 2 (stored `claims`) | schema 10, `critique_contract=2` | schema 10, `critique_contract=2` (no version, key or term change) | Every field | Every entry | `critique._dedup_claims` now keys on exact decimals with the terms as a multiset (`arithmetic.claim_content_key`), so an entry stored before WP-03.3 can hold two spellings of one claim (`20` and `"20.0"`). Harmless: the arithmetic auditor, the only consumer of claims, applies the same canonical form, and one critique entry holds one sheet's claims, so its dedup collapses them exactly as a cold run would. The merge rule is unchanged (its pinned fingerprint holds), and critique findings carry no discriminator, so stored findings are byte-identical. Only the log line's claim count can differ | WP-03.3, [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161) |
| Cross-QC cache (`_cross_qc_cache_key`, stored `claims`) | `_CROSS_QC_CACHE_CONTRACT=3` | `_CROSS_QC_CACHE_CONTRACT=3` (no version, key or term change) | Every field | Every entry | `cross_qc._dedup_claims` now keys on exact decimals with the terms as a multiset, so an entry stored before WP-03.3 can hold two spellings of one claim, which the arithmetic auditor counts once. Narrow residual, accepted rather than re-billing every cross-QC call: this dedup compares the quote lowercased and the auditor's does not, so two transcriptions whose quotes differ in letter case AND whose numbers are spelled differently are counted twice from a stored entry and once cold (the `arithmetic_checked`/`arithmetic_mismatched` tally only: their two findings carry one discriminator and still merge in the ledger). WP-05.1's planned contract bump (3 → 4) retires those entries | WP-03.3, [PR #161](https://github.com/Abe-Borg/drawing-analyzer/pull/161) |
| Critique cache, level 1 and level 2, and cross-QC cache (stored `claims`) | schema 10, `critique_contract=2`; `_CROSS_QC_CACHE_CONTRACT=3` | unchanged (no version, key or term change) | Every field | Every entry | `arithmetic.parse_number` now refuses a term that is not one value (`"1e3"`, `"2.5e-2"`, `"24x12"`, `"2P20A"`, a number glued to a Unicode dash, a fraction slash or a vulgar fraction), where it used to read the leading run (`1`, `2.5`, `24`, `2`). Such a claim is now unusable, so no finding that is still produced changes: a parse only becomes `None` or stays what it was, which leaves every surviving finding's text, severity, discriminator and id byte-identical. Of the `stage=investigation` key's inputs only the prior verification note can change, and only for a mismatch the relationship check now leaves model-transcribed: it was DETERMINISTIC before, which investigation never takes, so it has no stored entry to miss (new work, not a re-key). The auditor re-parses stored claims on every read, so the new rule applies to warm entries with no key change. Narrow residual, accepted rather than re-billing every critique or cross-QC call: both dedups key on `claim_content_key`, so an entry stored before WP-07.2 may have kept only one of two transcriptions of one quote that differed only by a now-refused spelling (`"1e3"` and `1` both keyed as `1`). A warm run checks the one stored; a cold run keeps both (one unusable, one checked). Needs two reads of one quote to write one value both ways. Not affected: the merge-rule fingerprint (`tests/test_drawing_cache_identity.py` passes unchanged), every prompt version, the digest and verify keys | WP-07.2 |
| Cross-QC cache (`_cross_qc_cache_key`), both paths | `_CROSS_QC_CACHE_CONTRACT=3` | `_CROSS_QC_CACHE_CONTRACT=4` | Every field; the entry shape is unchanged | None: every cross-QC entry written under contract 3 misses once, on the whole-set path too | Host-side grounding changed (B5, N12, N13): `classify_quote_evidence` gives every non-empty quote a real match at any length (a quote under six folded characters was grounded without a check, and before the no-text test), the match must cover whole source words (`anchor.SourceWords`, `anchor.word_core`), and it folds with the anchor's `_normalize`, as does `fact_tile_lookup`'s join. For byte-identical request inputs that changes which legs and facts are admitted, the `evidence_state` stored on each, the discard counters and the fact a reconciled leg takes its tile from, none of which a key input covers. One mechanism: the existing contract term, bumped (the P8 item 11 precedent); no key term, no `_SCHEMA_VERSION` bump. The whole-set path grounds nothing yet (U8, WP-06.2), so its entries' content would be unchanged, but it shares the contract (a path-conditional term would be a second mechanism) and re-runs once: one Opus call per set. **Retires the WP-03.3 and WP-07.2 stored-claims residuals** (the WP-03.3 cross-QC row and the WP-07.2 row above): an entry whose claims were de-duplicated under the old dedup is re-run, so a warm run now keeps what a cold run keeps. Digest, critique, identity, review-plan, citation, verification and investigation keys are byte-identical (`tests/test_drawing_cache_identity.py` and `tests/test_source_identity.py` pass unchanged). Old entries stay on disk | WP-05.1, [PR #165](https://github.com/Abe-Borg/drawing-analyzer/pull/165) |
| Cross-QC cache (`_cross_qc_cache_key`), both paths | `_CROSS_QC_CACHE_CONTRACT=4` | `_CROSS_QC_CACHE_CONTRACT=5` | Every field; the entry shape is unchanged | None: every cross-QC entry written under contract 4 misses once, on the whole-set path too | Host-side grounding changed again (B4, N12; the owner's decisions): cross-QC now grounds through the anchor's own whole-word matcher (`anchor.SourceWords`), which folds the brackets and sentence punctuation off every word of the evidence and of the quote (`anchor.fold_word`; never `"` `'` `<` `>`). For byte-identical request inputs that admits legs and facts the old match dropped (`RATED 175 PSI TYP` against `RATED 175 PSI, TYP.`, a quote-side `P-1,` against `P-1`), and changes the counters and the `evidence_state` stored on each; the fact-tile join keys on the same folded form (the Codex review of this slice), so such a leg also inherits its fact's tile, and two facts spelled apart only by that punctuation in different tiles collide and give none; no key input covers any of it. The fold only adds matches, with one exception: a quote made only of brackets and sentence punctuation (`,`, `(`, `.`) folds to nothing and now matches nothing, where it used to ground on a lone punctuation word (measured over 20,057 pairs: 174 gained, and every one of the 1,146 lost was such a quote). One mechanism: the existing contract term, bumped; no key term, no `_SCHEMA_VERSION` bump. No release has shipped contract 4 (WP-05.1 is unreleased), so a user upgrading from 1.7.0 pays one miss for both bumps. The anchor stage is not cached; a finding whose anchor moved re-keys its verification and investigation entries through their own inputs (the anchor is one), which is new paid work by design, not a register row. Digest, critique, identity, review-plan and citation keys are byte-identical (`tests/test_drawing_cache_identity.py` and `tests/test_source_identity.py` pass unchanged), and the A/B `RECORD_CONTRACT_VERSION` stays 3. Old entries stay on disk | WP-05.2, [PR #166](https://github.com/Abe-Borg/drawing-analyzer/pull/166) |
| Cross-QC cache (`_cross_qc_cache_key`), both paths | `_CROSS_QC_CACHE_CONTRACT=5`; the persona asked for severity `question` | `_CROSS_QC_CACHE_CONTRACT=6`; the persona asks for category `question` with severity `low` | Every field; one additive field, `invalid` (the refused-item counts), which an entry written without it reads back as "not recorded" | None: every cross-QC entry misses once, on both paths | Two changes, two mechanisms (D-4 note). **The prompt (B6):** the persona sentence changed, and the three prompts ride the key verbatim, so every entry re-keys through the key's own mechanism. **Host-side binding (N2 and the WP-05.1 note):** for byte-identical request inputs, `_drop_exact_repeats` keeps every finding that is not identical in every field, where `_dedup_findings` folded two different conflicts sharing a primary sheet, category, quote and legs; a fact whose quote is only whitespace is no longer admitted and sent to the reconciler; and the stored result carries its refused-item counts, which a warm run shows as the same stage warning. The existing term is bumped for it; no key term, no `_SCHEMA_VERSION` bump. No release shipped contract 4 or 5 (WP-05.1 and WP-05.2 are unreleased), so a user upgrading from 1.7.0 pays one miss for all three bumps: one paid cross-QC pass per set (one Opus call for 40 sheets or fewer; the map and reconcile calls above). A newly kept conflict is new paid work downstream (a dual-crop verification call, and an investigation if the crop cannot settle it), not a re-key: the verification and investigation keys are unchanged, and a conflict kept before keeps its entries. Digest, critique, identity, review-plan and citation keys are byte-identical (`tests/test_drawing_cache_identity.py` and `tests/test_source_identity.py` pass unchanged), and the A/B `RECORD_CONTRACT_VERSION` stays 3 (a record's shape and meaning are unchanged; more findings in an arm run after this is the behaviour change it is). Old entries stay on disk | WP-06.1, [PR #167](https://github.com/Abe-Borg/drawing-analyzer/pull/167) |
| Critique cache, level 1 and level 2 (`critique_cache_key_level1`, `critique_cache_key`) | schema 10, `critique_contract=2` | schema 10, `critique_contract=3` | Every field; the entry shape is unchanged (no stop reasons are stored) | None: every critique entry written under contract 2 misses once | A critique read the model did not finish no longer counts as a completed read (N4, critique part; D-1's WP-01.4 note): before, a read cut off at `max_tokens` or the context window, a refusal, a stream that ended without a stop reason, a `tool_use`/`pause_turn`/`compaction` continuation or an unknown stop counted whenever its findings object parsed, was merged as corroboration and was stored at both levels on both transports. A critique entry stores no stop reason, so an entry written under 2 cannot be checked on the way out; the existing critique-only term is bumped (no read-side reject beside it, no key term, never `_SCHEMA_VERSION`). The merge rule is unchanged: its fingerprint is pinned under 3 as under 2 (`63dbfe17…`). Digest, identity, review-plan, citation and investigation keys are byte-identical (`tests/test_drawing_cache_identity.py::test_wp_01_4_moves_every_critique_key_and_no_other_key`, with the contract-2 keys pinned). Old entries stay on disk (`test_a_critique_entry_from_wp_04_2_misses_and_is_never_deleted`); the next exhaustive run re-critiques each sheet once. No release shipped contract 1 or 2 (WP-04.1 and WP-04.2 are unreleased), so a user upgrading from 1.7.0 pays one miss per sheet for all three bumps. The A/B `RECORD_CONTRACT_VERSION` stays 3 (a record stores signatures, which did not change) | WP-01.4, [PR #171](https://github.com/Abe-Borg/drawing-analyzer/pull/171) |
