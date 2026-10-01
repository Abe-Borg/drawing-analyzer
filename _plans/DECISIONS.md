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
      is lost today; capturing it is WP-01.7; *(amended by WP-01.7: the
      stream's partial read is captured, `core.stream_interruption.StreamInterrupted`,
      and once the transient retries are spent it is the reply, judged by this
      classifier like any reply; see the WP-01.7 note below)*
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
    option and the shared retry bound it would need); *(amended by WP-01.8: a
    `max_tokens` read gets one retry at twice the cap on both transports
    first, and fails only if that retry fails too; see the WP-01.8 note
    below)*
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

Added by WP-01.5: **a refused batch item is recovered under the selected
transport, inside one per-sheet retry budget** (R2; the owner's rules, decided
in two rounds with measured options and a case table per option). It conforms
to the decision above and restates none of it: a `REFUSED` read is still a
failed read, and `stop_details` is still informational, never the verdict.
- **Measured first** (zero API calls, the real SDK over `AnthropicAPIStub`, SDK
  1.7.0 and again 1.8.0 in a scratch venv, identical):
  - the plain `RefusalStopDetails` declares only `category`, `explanation` and
    `type`, but allows extras, so `recommended_model` survives on a batch
    result as a pydantic extra. The API sets it only when a server-side
    fallback attempt could not run (the SDK's own docstring), and a batch item
    cannot carry `fallbacks`, so in practice it is absent on a batch refusal;
  - a refusal was failed and never retried at the primary collect, the
    fresh-batch rounds, the follow-up batch and the direct rescue, whatever its
    category; the abandoned-batch harvest resubmitted it to the same model;
    nothing read `stop_details`;
  - retries per sheet, worst case: 5 submissions on `RECOVERY_BATCH` (primary
    + 4 rounds, already shared by transient, expired, raised-cap and abandoned
    rounds), 2 batch items + 3 real-time calls on `RECOVERY_DIRECT`, 6 calls on
    the real-time digest (2 attempts × (1 + 2 transient));
  - a prototype swap stored the fallback read under the requested model's key
    at both levels, a warm run served it free, and the ledger labelled it with
    the requested model (same price for Opus 4.8).
- **The gate: a registry route per category.**
  `ModelCapabilities.refusal_fallback_routes` (pairs of category and target;
  `api_config.refusal_fallback_target`). Opus 5 declares `cyber` → Opus 4.8,
  Anthropic's server-side route for Opus 5's cyber-only classifiers. Nothing
  else is retried: another category, `null` (the model's own decline), no
  `stop_details`, a model without a route (Sonnet 5 included). A named
  unrouted category is said in the error: `…; not retried: no fallback for
  category 'bio' on claude-opus-5`. `supports_refusal_fallback` (the
  server-side opt-in) is a separate capability and is unchanged. The Opus 5.5
  and Sonnet 5.5 defaults, registered after this decision (merged into the
  slice's PR), declare no route: a batch item refused on one is not retried.
  Whether they get routes, and which, is open for the owner (Sonnet 5.5's
  server-side fallback retries `cyber` and `frontier_llm` on Sonnet 5;
  Opus 5.5's targets are Opus 5 and Opus 4.8, per category).
- **The target:** `recommended_model` when it names a registered model other
  than the refuser, else the route's; the request is rebuilt for it
  (`digest.retarget_digest_request`, the builder's rules). **The gate decides
  whether, the target decides where**: a registered hint does not open an
  unrouted category. (The round-2 preview's "route target: any" row read as
  "whatever the route's target is"; the owner's gate choice says everything
  unrouted is not retried, so the gate applies first. No batch refusal
  carries the hint in practice, so this changes nothing measured.)
- **Once per sheet.** A refusal from an item already sent to a fallback ends
  it (`refused digest on claude-opus-4-8 (…)`); the chain refused.
- **One per-sheet retry budget** (`_Slot.retries`, `_within_retry_budget`,
  `_count_retry`): every resubmission of a sheet, whatever the reason and at
  every site, counts one; the direct rescue counts once per sheet. The budget
  is `DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS` (default 4, no new knob), so
  the pipeline's worst case is unchanged. The real-time digest keeps its own
  retries (the server-side fallback covers its refusals).
- **The harvest asks the same predicate.** A refusal it reads is held (it ranks
  above nothing, so a fallback that comes back worse or never lands leaves it
  named) and goes to its fallback, or is final. A permanent error it reads is
  final (held, not resubmitted; it was resubmitted once). An item the
  harvest's own cancel stopped (`canceled`), a transient or expired item and a
  truncated one are resubmitted as they were submitted, as before.
  `_HarvestOutcome.final`, `.retry`, `.rescue_params`. This amends WP-01.3's
  "a content-free item is parked": a refusal is now held.
- **The selected transport.** `RECOVERY_BATCH` (the pipeline): a refused sheet
  is only ever a batch item. `RECOVERY_DIRECT` is the full-rate policy a caller
  selects: a refused sheet takes any failed item's path. A refusal from the
  primary gets its fallback item in the follow-up batch; the rescue takes, on
  its fallback, whatever still fails after that batch, including a refusal the
  follow-up itself returned, and everything when the follow-up cannot run or
  stalls. (The round-2 preview said "only if that batch cannot run or stalls";
  the follow-up-refusal case is the same rule, measured after implementation
  and pinned.)
- **Cache admission:** a finished fallback read is admitted under the requested
  model's key, like the server-side fallback's. No key, entry or schema
  changed, so no migration-register row. The ledger still labels the attempt
  with the requested model: a recorded limit for WP-14.3.
- **`billing_error` is permanent**; `request_too_large` (the API's 413 type, not
  an SDK batch type) stays permanent.
- **Logged, no secrets.** The ladder takes `category=` and a refusal's error
  names it on both digest transports and the critique; the diagnostics log
  carries category, hint, target and explanation (`redact_secrets`, one line,
  200 characters). Nothing new in the manifest.
- **The batch critique:** an errored read keeps its type through the digest's
  one helper (`_batch_item_error_text(noun="item")`). Retrying failed batch
  critique reads, and WP-01.4's raised-cap question, is a new row, WP-01.8.
  *(Done by WP-01.8: the note below.)*
- **Rejected:** retrying every refusal (a model's own decline re-read
  elsewhere); a guessed Sonnet 5 route; sending `recommended_model` verbatim
  (an unregistered id may 400); a refusal round outside the budget; storing
  under the serving model's key or not caching (a refusal plus a fallback paid
  on every run); a `served_model` field in the entry (it changes what is
  stored; WP-14.3's); `billing_error` transient; the explanation in the error or
  the manifest; direct rescue only when passed explicitly (a sentinel default).
- **Consumers affected:** the refused sheet's error (its category, and the
  fallback's naming), `ctx.errors`, `run.log`, the report and the per-sheet
  export through it; the digest stage's status (a recovered sheet is no longer
  a failure); both cache levels (a finished fallback read is stored); the usage
  ledger (one more attempt record, labelled with the requested model); the
  critique's failed-read errors (the type).

Added by WP-01.6 ([PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184)): **the remaining response consumers and one text join** (N4
for the set-level stages, N27, U2, plan WP-09 step 6; the owner's rules,
decided in two rounds with measured options and a case table per option). It
conforms to the decision above and restates none of it.
- **Measured first** (zero API calls, the real SDK over `AnthropicAPIStub`, SDK
  1.7.0 and again 1.8.0 in a scratch venv, identical):
  - **The five consumers** (the review planner, set identity, synthesis, the
    focus report, the prose harvest's structuring call) read no stop reason.
    Under `max_tokens`, `model_context_window_exceeded`, `None` (the planner,
    synthesis and focus stream, so the real N27 shape, a stream cut before
    `message_delta`), `tool_use`, `pause_turn`, `compaction` and an unknown
    reason, every one kept its reply, read COMPLETE and cached it whenever its
    content parsed. A refusal whose content parsed did too. A refusal with an
    explanation failed the planner and identity (`no parseable … block`, not
    cached) and degraded the harvest item, but synthesis and the focus report
    kept the explanation as their text, COMPLETE, cached. A textless refusal
    failed synthesis and focus (`empty … result`) and recorded no usage.
  - **Verification** already failed `max_tokens` and `refusal`; the six other
    shapes were parsed as verdicts, the stage read COMPLETE, and the verdict
    was cached.
  - **The fallback block.** A streamed reply declined part way is
    `[text, fallback, text]`, and the second text *continues* the first
    (Anthropic's refusals-and-fallback page: "The fallback model continues
    from the partial output"); a non-streamed one omits the partial and starts
    over, `[fallback, text]`. On both namespaces, create and stream, Opus 5.5
    and Sonnet 5.5, the SDK keeps the order; the beta namespace parses the
    block as `BetaFallbackBlock`, the plain one as a `TextBlock` (or
    `ParsedTextBlock`) whose `type` is `"fallback"`. The `"\n"` join put a
    newline inside a word, broke the digest's findings JSON (the finding lost,
    the read cached as finished) and failed a good critique read.
  - **Over the whole suite** (an instrumented run, 3,882 joins in 12 modules):
    6 replies had more than one text block, all `[text, fallback, text]` from
    WP-02.3's recorded limits; none had two ordinary text blocks. 7 of the 237
    identity corpora carried an errored sheet's digest text.
- **The join** (`core.reply_text.reply_text`, stdlib only, the one reader of a
  reply's text blocks): two text blocks with a `fallback` block anywhere
  between them join with nothing; any other two with `between`, default
  `"\n"`, as before. A reply without a fallback block therefore reads
  byte-identical, and no stored text changes except a fallback-split reply's.
  A block is known by `type`, never class. `digest._message_text` is gone; its
  11 importers and the digest read this. WP-12.1 passes `between=""` for
  citation splits.
- **The consumers** each ask `digest.unfinished_reply_error(resp, text, noun=)`
  first: `None` for `FINISHED` (the stage's own parse then decides, in its own
  wording: `planner reply carried no parseable plans block`, `empty synthesis
  result`, …), else `digest_terminal_error` with the stage's noun (`review
  plan`, `identity`, `synthesis`, `focus report`, `harvest structuring
  reply`), a refusal naming its category, its `stop_details` logged. What each
  does with a non-finished read (keep nothing, cache nothing):
  - the planner and identity fail their stage (the critique runs without plan
    profiles, as on any planner failure);
  - synthesis and the focus report fail and ship no text (the export's "no
    overview produced" path), so the harvest mirrors nothing from them; their
    billed reply is recorded as one FAILED usage attempt
    (`SynthesisResult.replied` / `FocusReportResult.replied`; a failed one
    recorded nothing before, which the planner and identity already did);
  - a harvest item takes its degraded verbatim entry (`call="live"`), under
    either structured-outputs contract: a schema never overrides the stop
    reason (plan WP-09 step 6).
- **Verification** reads the classifier in `_verdict_from_response` and
  `_degrade_kind`: every kind but `FINISHED` is "no verdict", UNCERTAIN, never
  cached, counted under the existing `truncated` counter, whose meaning widens
  to "did not finish" (no new field; WP-01.1's counters and D-2 unchanged).
  The notes `no verdict (truncated at max_tokens)` and `no verdict (declined by
  the model)` keep their wording; new: `no verdict (context window exceeded)`,
  `no verdict (unfinished: stop_reason=…)`.
- **The identity corpus** skips an errored sheet's digest text: the sheet
  gives its `[digest failed: …]` line (what it gave with no text) and keeps its
  text-layer slice and edition windows (the PDF's words, not the model's). It
  re-keys the identity cache only for a set with such a sheet.
- **Not in this note:** cross-QC's terminal handling (WP-06.3; its replies
  already read through the join), the citation cache gate (WP-12.6), the
  investigation (WP-13.4), interrupted-stream capture (WP-01.7).
- **Rejected:** "" between every text block (widens into WP-12.1 and changes
  multi-block replies); "" also between cited blocks (part of WP-12.1 here);
  shipping a cut-off synthesis or focus report under an "incomplete" banner;
  using a parseable non-finished reply for the run without caching it (D-1 and
  N15 rule unfinished output out); a fourth verification counter; the ladder's
  wording for verification (re-baselines two pinned notes); keeping the
  identity corpus as it was; dropping the errored sheet's text-layer windows
  too; a stage-neutral error sentence (a second wording).
- **Version / cache changes:** D-4's WP-01.6 note and two migration-register
  rows.
- **Consumers affected:** the five stages' results, errors and stage statuses
  (`ctx.errors`, `run.log`, the report's stage table), `ctx.synthesis_text` and
  `ctx.focus_report_text` (empty on a non-finished reply) and through them the
  exports and the prose harvest's synthesis channel; the planner's profiles and
  so the critique's `profiles_key`; the usage ledger (a FAILED synthesis or
  focus record); verification's counters, notes, stage status and cache; the
  identity corpus and its key; every reply read through the join (the digest,
  its batch transport, the critique, cross-QC, citation, investigation).

Added by WP-01.7 ([PR #185](https://github.com/Abe-Borg/drawing-analyzer/pull/185)): **an interrupted stream's partial read, its retry
and its usage** (U1's partial-stream part, plan WP-14 step 7; the owner's rules,
decided in two rounds and one follow-up with measured options and a case table
per option). It amends the "interrupted stream" line above: a stream that
raises is no longer a transport failure whose read is lost. It conforms to the
classifier and restates none of it.
- **Measured first** (zero API calls, the real SDK over `AnthropicAPIStub`,
  every `CUTS` x `ENDS`, both namespaces, Opus 5.5 and Sonnet 5.5, SDK 1.7.0 and
  again 1.8.0 in a scratch venv, identical):
  - the SDK raises the transport's own `httpx2.RemoteProtocolError` for a
    dropped connection (not wrapped), `APIStatusError` with `status_code` 200
    and the event's type on `.type` for an SSE `error` event, and its own
    `AssertionError` for a clean end with no event;
    `digest._is_transient_error` recognised none, so every streamed stage failed
    after one request (`HTTP 200: {'type': 'error', …}`, `peer closed
    connection without sending complete message body`);
  - the SDK's `max_retries` re-sends a request, never a started stream (1
    request with `max_retries=2`), so a host retry doubles no layer;
  - `current_message_snapshot` stays readable after the `with` exits: before
    `message_delta`, no stop reason and `message_start`'s usage (input, cache
    counters, the `cache_creation` split; output 0); after it, the complete
    read (stop reason, final usage) even when the stream then drops; no
    `message_start`, the SDK's `AssertionError`;
  - the ladder and `unfinished_reply_error` read a snapshot as `unfinished …
    (stop_reason=None)` (`empty …` with no text); `keep_digest_read` ranks one
    with content a partial read, above an empty or raised retry;
  - today, per consumer (m3, 66 cases, both SDKs): the digest failed with 0/0
    recorded; the critique read failed and its tokens were dropped from the
    sheet's record; the planner failed with a 0-token record; synthesis and
    focus recorded nothing; the investigation's turn failed 0/0, the stage
    PARTIAL. Nothing retried. Over the whole suite, 5 of 2,589 streamed calls
    raised inside `get_final_message`, all in WP-02.3's recorded limits.
  - **The investigation streams too** (every turn), a seventh streamed path
    the request's list did not name.
- **The capture site** is `core.api_config._dispatch_messages`: a failure
  inside `get_final_message()` raises `StreamInterrupted(cause, partial)` from
  its cause (the class in its own stdlib-only module,
  `core/stream_interruption.py`, so a reload of `api_config`, which the
  report-chat tests do, cannot make two classes: measured, it did in the full
  suite before the move) (`kind`: `error_event`, `connection`, `timeout`, `no_event`,
  `other`; `error_type` / `error_message` from the event). A failure before the
  stream exists is not wrapped (the latches read it). **A snapshot that
  already got `message_delta` is the reply at once** (the follow-up question:
  the round-1 retry table said "any cut", the round-2 usage preview showed one
  attempt; the owner chose one attempt): nothing retried, judged by its stop
  reason, cached when finished, as its clean-end twin always was.
- **Retry: transient ones, one predicate.** `_is_transient_error` learns the
  interruption: `connection`, `no_event` (read as dropped) and `timeout` are
  transient; an `error_event` is transient exactly when its type stands for a
  status in `_TRANSIENT_STATUSES` (`digest._ERROR_TYPE_STATUS`, pinned to the
  SDK's `ErrorObject` types plus `request_too_large`): `overloaded_error`,
  `api_error`, `rate_limit_error`, `timeout_error`; `other` is judged as its
  cause. Inside each stage's existing transient retries (2 per call; the batch
  rescue also inside its per-sheet and collection budgets): no bound moved.
  Not taken: every interruption (re-sends an `invalid_request_error` twice); a
  dropped connection only (an `overloaded_error` mid-stream reported, not
  retried); no retry.
- **The partial read is the reply** once the retries are spent (or at once for
  a permanent cause), judged by this classifier: no stop reason is
  `UNFINISHED`, so each stage takes its N27 path. The digest keeps its text
  under an error (the per-sheet export shows it), holds its findings out (N15),
  caches nothing, and folds every attempt's read through `keep_digest_read`
  (N16, the owner's second-round choice): a partial read with content
  outranks a later empty or raised attempt, a finished retry wins with no
  suffix, and a call that ended with nothing in hand is named once (`"; retry
  failed: stream interrupted (…)"`), as a raised-cap retry that raised always
  was. The critique fails the read and keeps nothing (WP-01.4). The review
  plan, synthesis and the focus report keep nothing (WP-01.6), through one
  loop, `digest.stream_reply`. The batch direct rescue folds the partial read
  like any rescue read. The investigation retries its turn and never uses a
  partial turn (no tool from it runs). Not taken: never finished even after
  `message_delta` (a complete read failed and re-read); discarding the partial
  (the digest's export loses billed text); the last attempt's read for the
  digest (a drop mid-text then two with no event would lose the text).
- **The wording** is the ladder's with the cause in its parentheses, as a
  refusal carries `category=` (`digest_terminal_error(…, interrupted=)`):
  `unfinished digest (stop_reason=None, interrupted='overloaded_error')`,
  `empty synthesis (stop_reason=None, interrupted='connection dropped')`. With
  nothing in hand (`_clean_error`): `stream interrupted (<type>: <message>)`,
  `stream interrupted (connection dropped — try again)` (a stream with no
  event reads the same), `stream interrupted (timed out — try again)`; an
  `other` cause keeps its own wording. Unchanged without an interruption. Not
  taken: the ladder alone (a partial read indistinguishable from a clean early
  end); a new ladder word `interrupted`.
- **The usage** (plan WP-14 step 7): every attempt's reported usage is the
  stage's (`digest.StreamUsage`), an interrupted one's being `message_start`'s,
  and `UsageRecord.interrupted_attempts` (additive, default 0) counts the
  attempts whose final usage never arrived. `RunUsage.interrupted_attempts`
  totals it (`usage.interrupted_attempts` in `run_manifest.json`, schema v1
  additive), and run.log's usage section says the output and cost totals are
  then lower bounds. Each record keeps its stage's terminal status; the cost
  stays a number and `is_billable_but_unpriced` is unchanged: D-7 (WP-14.4)
  decides whether unreported output makes a total unknown, WP-14.5 per-attempt
  records. A synthesis or focus call that got nothing back but was interrupted
  is one FAILED record. Not taken: a terminal status `INTERRUPTED` only (a
  recovered interruption leaves no mark); the counter plus an unknown cost
  (moves into D-7); input only, no mark.
- **Version / cache changes:** none (D-4's WP-01.7 note); no migration-register
  row.
- **Consumers affected:** every streamed stage's retries, errors and usage
  records (`ctx.errors`, the stage tables, `run.log`, `run_manifest.json`); the
  digest's kept read, its export and its held-out count; the critique's read
  tally (an interrupted read that was retried to a finish is judged; one that
  was not is "returned no judgment"); the investigation's per-finding record;
  the batch rescue's attempt records; the SDK-contract test's patch point
  (each set-level stage passes its own `stream_message` to `stream_reply`).

Added by WP-01.8 ([PR #186](https://github.com/Abe-Borg/drawing-analyzer/pull/186)): **a failed batch critique read is retried, and a critique
cut off at `max_tokens` gets one raised-cap retry, on both transports** (N4's
critique part, R2, WP-01 step 5; the owner's rules, decided in three rounds with
measured options and a case table per option). It conforms to the classifier
and the WP-01.4 and WP-01.5 notes above, and restates none of them: a read that
is not `FINISHED` is still a failed read that keeps nothing; a retry happens
before the read is judged failed.
- **Measured first** (zero API calls, the real SDK over `AnthropicAPIStub`,
  Opus 5.5, Sonnet 5.5 and Opus 5, SDK 1.7.0 and again 1.8.0 in a scratch
  venv, identical):
  - every failed batch critique read failed in one batch and was never
    retried: the nine SDK error types, `request_too_large`, canceled, expired,
    a refusal of every category with and without `stop_details`, `max_tokens`
    (empty, or with a complete-looking object), the context window, `None`,
    `pause_turn`, an unknown stop, a malformed read;
  - through the pipeline (Hybrid and Economy) the critique stage read PARTIAL,
    3 of 4 reads judged, the sheet's usage record PARTIAL, and the warm run
    read the sheet again (2 batch items); on Fast a real-time read cut at
    64k failed in one call, and the warm run read it again;
  - the digest's recovery could be reused, not copied: its retry decision read
    only a slot's params and its `SheetDigest`'s verdict, and its budget
    helpers only a slot's `retries`; its rounds loop is bound to its harvest,
    abandonment records and rescue, so the critique keeps its own loop.
- **Which reads** (round 1): **the digest's one predicate**,
  `batch_digest._retry_params_for` (slot-agnostic; `_item_retry_params` is its
  digest wrapper, byte-identical decisions): a transient errored item
  (`api_error`, `overloaded_error`, `rate_limit_error`, `timeout_error`) and an
  expired one as they were sent; a refusal on its registry route
  (`refusal_fallback_routes`), once, the gate and target rules of the WP-01.5
  note unchanged; a `max_tokens` stop at twice the cap, up to
  `MAX_TOKENS_RETRY_CEILING`, clamped to the model's cap. Not retried: a
  permanent error, `canceled` (as the digest's primary collect), an unrouted
  or category-less refusal (a named category says so: `…; not retried: no
  fallback for category 'cyber' on claude-opus-5-5`, the digest's words), the
  context window, `None`, a continuation, an unknown stop, a malformed read.
  `CritiqueRunOutcome.stop_reason` (runtime only) is what the predicate reads.
  Not taken: the same with one follow-up batch only; the same plus canceled;
  transient and expired only.
- **Where:** fresh critique batches (`batch_critique._recover_failed_reads`),
  between the primary collect and the merge, up to
  `_max_batch_resubmit_rounds()` rounds (a rejected submit counts a round,
  spends no retry, backs off), inside the remaining collection bound. Never
  full-rate real time. No stall watch, like the primary critique poll.
- **The budget** (round 1): **WP-01.5's per-sheet budget**, the same knob
  (`DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS`, default 4): `_CSlot.retries`
  counts every resubmitted read of the sheet; `_within_retry_budget` and
  `_count_retry` read it through `_CRead.retry_budget`, and the check counts
  the reads it keeps within one call (two reads of one sheet in one round
  spend two). Worst case per sheet: 2 + 4 items. Not taken: per read (2 + 8);
  per sheet on its own knob; one count shared with the digest's.
- **The read kept** (round 1): **a finished retry is the read; a failed chain is
  named.** A failed read keeps nothing (WP-01.4), so `critique.keep_critique_read`
  (both transports) makes a finished retry the read (same `run_id`, so the
  merge's provenance is unchanged) and names a failed one in the read's error
  with the digest's one wording (`digest._name_discarded_retry`): `; retry: …`,
  `; N retries, the last: …`, `; retry on <model>: …`; `note_failed_critique_retry`
  names a call that raised (`; retry failed: …`). A fallback read is worded
  with its model (`refused critique on claude-opus-4-8 (…)`). Every attempt's
  usage is the read's. Not taken: the latest attempt's error only (the
  digest's equal-rank rule taken literally); every error joined.
- **Real time** (round 1): **one raised-cap retry per read** in
  `critique._critique_read` (so also batch's upload-failure fallback),
  streamed, the read's own retry outside the batch budget, as the real-time
  digest's. Not taken: batch only; neither.
- **Merge, tally, cache** (round 2): **the recovered read is the read; no
  bump.** It merges as any read, is judged in D-2's tally (the D-2 WP-01.8
  note), and a sheet whose every read finished is stored at both levels
  under the requested key (requested model, requested cap), as the WP-01.5
  digest fallback read is. Not taken: the same with `_CRITIQUE_CACHE_CONTRACT`
  3 -> 4; used this run and never cached.
- **Usage** (round 2): **summed on the sheet's one critique record**, BATCH for
  batch retries; per-attempt records stay WP-14.5's. Not taken: a record per
  retried read.
- **A follow-up batch that never ends** (round 3): **canceled, the recovery
  stops, its reads named** `; retry: critique batch not collected (<status>);
  remote batch id=… was canceled` (`may still be running` when the cancel
  failed, and then the files are kept). A read a round returned no envelope
  for goes again as it was sent. The files are released only once every
  batch that references them is terminal or canceled. Not taken: cancel and
  carry the reads to the next round (pays a canceled round's finished items
  again, with no harvest to read them back).
- **Left on other rows** (round 2 and 3): the digest harvest's truncated item
  keeps its cap one round (WP-14.1); a real-time refusal's `recommended_model`
  is logged, not retried (WP-14.3); the batch critique has no harvest of an
  abandoned batch (a new row, WP-18.6). WP-01 stays open: its acceptance waits
  on WP-06.3, WP-12.6 and WP-13.4 (the plan's WP-01 Acceptance note).
- **Version / cache changes:** none (D-4's WP-01.8 note); no migration-register
  row.
- **Consumers affected:** the batch critique's reads, errors, merge and cache
  (both levels, through the pipeline's `_ingest_miss`); the critique stage's
  status, items, coverage line and errors (`critique_shortfall`), `ctx.errors`,
  `run.log` and the report's stage table through them; the sheet's critique
  usage record (tokens, terminal status); the real-time critique's calls; the
  digest's retry decision and budget helpers (refactored, byte-identical); the
  WP-01.5 and WP-01.4 tests re-baselined with the owner's approval.

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

Added by WP-06.2 ([PR #191](https://github.com/Abe-Borg/drawing-analyzer/pull/191)): **cross-QC's refused ambiguous references stay observational**
(the owner's decision; N6, D-8). A reply that names a sheet id more than one
sheet of the set carries binds none of them; the reference is counted in
`CrossQCDiscardCounts` (`legs_ambiguous_label`, `facts_ambiguous_label`), and a
non-zero count becomes one cross-QC stage warning
(`CrossQCDiscardCounts.ambiguity_note()`), placed after the refused-item
warning. The stage keeps its status and the result is cached with its counts,
so a warm run shows the same warning. The whole-set path's grounding discards
(U8) are observational too, as the sharded path's always were: no stage
warning, `run_manifest.json` only.
- Why not D-2's item rule: as for refused items, what was lost is part of the
  model's reply, not a required input left unjudged; every sheet was sent and
  each stays addressable by its handle.
- Considered and not taken: the counters with no warning (the loss would be
  visible in the manifest only); counting under `legs_unresolved_handle` (an
  ambiguous id and an unknown one would read alike); holding the stage
  PARTIAL (a stable reply would read PARTIAL on every warm run, N14's shape,
  WP-06.3's decision).
- Measured before deciding: 11 of the suite's 295 cross-QC calls had an id two
  or three PDFs carry, and none of their replies named it, so no pinned
  status moved.

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

Added by WP-01.8: **a recovered critique read is judged; the items stay
reads** (the owner's decision; D-1's WP-01.8 note). The critique's terms from
WP-01.4's note are unchanged. A read the batch follow-up rounds or the
real-time raised-cap retry recover is the read, so it is *judged* (it finished
with a valid findings object) and the sheet's `completed_runs` counts it; a read
still failing after its retries is *failed* ("returned no judgment"), its error
naming the retries. *Eligible* stays `runs` x the sheets the run set out to
read: a retry is an attempt, never an item, so it adds nothing to either side
of the ratio. The coverage line, `items_in` / `items_out` and the usage record's
terminal status read the final reads. Measured: under the chosen rules no
pinned status moved outside the re-baselined tests; a transient or expired read
answered once, a routed refusal and a `max_tokens` read whose retry finishes
now read COMPLETE (4 of 4) where they read PARTIAL (3 of 4). No cache or key
change.

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

Added by WP-04.3 ([PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188)), as an input, not a decision: **a quantity's
role is part of what a finding claims.** Two findings that give the same values
to different roles (`6 in main and 4 in branch` / `4 in main and 6 in branch`),
or one value to two roles (`6 in supply and 6 in return` / `6 in supply and 8 in
return`), make different claims although their quantity sets agree. The merge
predicate (`critique._is_duplicate` through `critique.signature_conflicts`, in
the critique's `_cluster`, both ledger passes and the prose harvest's veto) now
refuses such a pair: `critical_signature` carries `roles` (`"main=6in"`, read by
`critique._quantity_roles` from a closed list of role words) and
`ambiguous_roles`, compared per role and kind by inclusion on the
`measurements` axis. The owner's rules, recorded in the WP-04.3 handoff: a role
on one side only never blocks (so the same "500 gpm shown, 550 gpm required"
from both critique reads, which names no role, stays one claim); a finding whose
only roles for a kind are ambiguous (a value list with a role list and no
`respectively`; a bare role word between two values) is kept apart from one
that binds a role in that kind, the plan's "retain separate claims when role
ambiguity prevents safe compatibility"; status words (shown, required) are not
roles. For WP-03.4: a role binding is a structured, host-derived part of a
claim, like `claim_discriminator`, but it is read from prose by a closed
vocabulary, so it is evidence of *which claim* only where it is read; its
absence says nothing (one-sided, never blocking). A `claim_id` built on
signatures would inherit that asymmetry. For WP-03.5: roles grow with a
survivor's supporting quotes like every signature axis, and the member-wise
checks cover them; a representative whose bundle came from a role-less member
carries no role in its live signature (pinned in `tests/test_quantity_roles.py`).
- Considered and not taken, with the owner's choice recorded in the handoff:
  status words as roles; an open vocabulary (any noun after the value; it read
  noise such as `hall is 480V` and moved 8 suite decisions outside the two
  flips); retaining every pair where one side names roles and the other does
  not; reading a bare preceding label (`MAIN 6"`).

Added by WP-04.4 ([PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189)), as an input, not a decision: **a spelled range
or list is one quantity, and a feet value's inches are part of its claim.** The
quantity reader (`critique._quantity_tokens`) signed only the part of four
spellings it could read, so four pairs of different claims agreed and merged:
a bare `12'` against `12'-6"`, `4 to 6 in` against `6 in`, `2, 4, 6 in` against
`3, 5, 6 in`, and `20A 120V` against `30A 120V`. The owner's rules, recorded in
the WP-04.4 handoff: `4 to 6 in` and `between 4 and 6 in` claim the range
`4..6in` (the token `4-6 in` already signs), and `4 and 6 in`, `4 or 6 in` and a
loose list of three or more numbers claim the list, as their tight spellings
do; a compact `A` beside a voltage is a current; and `critical_signature` gains
`feet_inches`, each feet value with its inches (`12ft6in`, `12ft0in` when bare,
any spelling of feet), compared by inclusion on the `measurements` axis beside
the tokens, never in them. For WP-03.4: a from-to change now claims a range
(`increase from 4 to 6 in` stays apart from `increase to 6 in`), and a
two-number comma list still claims only its last number (a recorded limit);
the feet-inches pair, like a role, is host-derived and one-sided (a finding
with no feet value never conflicts on it), so a `claim_id` built on signatures
would inherit that asymmetry too. For WP-03.5: the pairs are read part by part
and grow with a survivor's supporting quotes like every signature axis; the
member-wise checks cover them (pinned in `tests/test_quantity_residuals.py`).
- Considered and not taken, with the owner's choice recorded in the handoff: a
  bare feet value as `{12ft, 0in}` tokens (a `6 in` elsewhere in the text
  still masked it); feet-inches as one token (it split `12 ft 6 in` from
  `12'-6"`); the foot mark only; `to` ranges without `and`/`or` lists; loose
  lists of two numbers (`Relocate valve 4, 10 ft` read as a list); `circuit`
  after a compact `A` as context (`connect to 2A circuit 12` names a panel).

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
  register. WP-04.3 bumped it to 4 for quantity roles and the
  dimension-separator tag rule (the merge rule, so its fingerprint is pinned
  under 4); see the migration register. WP-04.4 bumped it to 5 for the
  tokenizer residuals and the feet-inches pairs (fingerprint pinned under 5);
  the same change moved `cross_qc._CROSS_QC_CACHE_CONTRACT` 7 → 8, because
  cross-QC grounding reuses the quantity reader, and the A/B
  `RECORD_CONTRACT_VERSION` 4 → 5; see the migration register.
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
- **Added by WP-05.3 ([PR #187](https://github.com/Abe-Borg/drawing-analyzer/pull/187)): the same term, 6 → 7** (the owner's decision: one
  matcher). Cross-QC grounds through the anchor's character-stream tier too
  (`anchor.SourceWords.joined_spans`: a quote that differs from the text only
  by the named spacing joins), and no quote or text with a number split around
  a lone `.` grounds any longer (B4). For byte-identical inputs that changes
  which legs and facts are admitted and the `evidence_state` stored on each,
  and a fact whose quote splits a number joins no leg (its folded form is
  `""`); no key input covers any of it. One mechanism: the term, no key term,
  never `_SCHEMA_VERSION`. The fact-tile join keeps its folded key (a recorded
  limit, the owner's choice). The anchor stage has no cache; a newly anchored
  finding gets new verification and investigation entries (their keys carry
  the anchor: status, method and rect), which is new paid work, not a
  contract change; an anchor that loses its rect (the sub-phrase rule, the
  split-number rule) leaves its old entries unread. Measured over the suite:
  0 of 1,064 recorded anchors and 0 of 738 grounding verdicts moved outside
  the new tests, so no stored fixture entry changes meaning. The critique
  contract (3), its merge-rule fingerprint, and the A/B
  `RECORD_CONTRACT_VERSION` (3) are unchanged: the merge rule reads no
  rectangle (WP-03.7) and the quantity reader is reused as it is.
- **Added by WP-01.6 ([PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184)): three stage terms for three admission changes** (the
  owner's decision). Synthesis, the focus report and the prose harvest's
  structuring call now store only a reply the model finished, and none of
  their entries stores a stop reason, so an entry written before cannot be
  checked on the way out: a 1.5.0-1.7.0 entry may hold a refusal's explanation
  served as the overview or a finding from a cut-off structuring reply. Each
  stage's existing term is bumped, 1 -> 2 (`_SYNTHESIS_CACHE_CONTRACT`,
  `_FOCUS_CACHE_CONTRACT`, `_HARVEST_CACHE_CONTRACT`; the WP-01.4 precedent: a
  change to what an entry admits bumps its term). No key term, no read-side
  reject, never `_SCHEMA_VERSION`.
  - **Left, recorded residuals.** The planner, identity and verification keys
    have no host-contract term, and adding one would be the only mechanism: a
    re-keyed planner or identity that comes back different re-keys the
    critique (`profiles_key`), a full critique re-read. So an entry an earlier
    version stored from a non-finished plan, identity or verdict keeps serving
    until its inputs change. The plan and identity must still have parsed and
    sanitized, and a verdict's non-finished shapes (context window, `None`, a
    continuation, unknown) are rare on a non-streaming verify call.
  - **The join moves no key.** A reply without a fallback block reads
    byte-identical. A digest an earlier version cached from a fallback-split
    reply (possible since the fallback shipped in 1.3.0, on real-time Opus 5
    digests) keeps its `"\n"` and whatever findings it lost: no digest-only
    term exists and `_SCHEMA_VERSION` is barred. A critique split that way
    failed and was never cached.
  - **The identity corpus** re-keys through the key's own input (the corpus
    hash): only a set with an errored sheet that carried text.
- **Added by WP-01.7 (D-1's WP-01.7 note): nothing moved.** An interrupted
  stream's partial read has no stop reason, so `digest_cache_admits`, the
  critique's all-reads-counted admission and the set-level stages'
  `unfinished_reply_error` refuse it at every writer, and no loader changes. A
  snapshot that already got `message_delta` is stored like any finished reply,
  the same payload under the same key (the owner's choice; its clean-end twin
  was always admitted). No stored entry ever held an interrupted read (the
  stream raised and nothing was stored), so nothing needs to miss. No key,
  contract or `_SCHEMA_VERSION` change, and no migration-register row. The new
  `UsageRecord.interrupted_attempts` is a run artifact field (manifest schema
  v1, additive), not a cache payload. The digest's level-2 entry's
  `input_tokens` / `output_tokens` now sum an interrupted attempt too when a
  retry finished; they are informational (a hit bills nothing) and every
  previously possible read stores the same values.
- **Added by WP-01.8 (D-1's WP-01.8 note): nothing moved, the owner's choice.** A
  critique result whose every read finished, one of them on a retry (a raised
  cap, a refusal fallback, a resubmitted transient or expired item), is stored
  at both levels under the requested key (requested model, requested cap),
  with the same payload shape and admission rule (`completed_runs ==
  requested_runs`). No key, `_CRITIQUE_CACHE_CONTRACT` (3) or `_SCHEMA_VERSION`
  change: a contract-3 entry was written only when both reads finished on
  their first attempt, which is exactly what the new code stores for the same
  inputs, so nothing needs to miss; a retry happens only where nothing was
  stored. An entry may now hold a read served by a fallback model or produced
  at 128k, and nothing marks it (the serving model in a payload is WP-14.6's).
  `CritiqueRunOutcome.stop_reason`, `read_error` and `retries_discarded` are
  runtime-only; no stored field changed. No migration-register row.
- **Added by WP-06.2 ([PR #191](https://github.com/Abe-Borg/drawing-analyzer/pull/191)): the cross-QC term 8 → 9, beside the user-turn framing
  joining the key** (the owner's decision; N6, U8, K2). Two changes, each with
  its own mechanism. The host-side binding changed for byte-identical inputs
  (the whole-set path binds through handles and the one resolver, refuses an
  id two sheets carry, grounds and counts what it keeps, rebinds its claims;
  the sharded path reads a reply's `sheet_id` through the same resolver; the
  claim dedup keys on the page; entries sort by source), which is what the
  term exists for, so it is bumped. Separately, the framing strings the
  builders put around the sheets now ride the key verbatim beside the three
  system prompts (`cross_qc_user_framing()`, K2), so a framing edit re-keys
  through the key's own inputs, as a prompt edit does. Not "a bump and a key
  term for one change" (plan §2 rule 15): if the framing ever moved back out
  of the key, the bump would still keep a warm entry from serving a binding
  the host no longer makes. The critique contract (5), its merge-rule
  fingerprint and `_SCHEMA_VERSION` are unchanged: `critique._leg_targets`
  now names pages, but no critique finding carries a leg, so no stored
  critique holds a merge it decided (the fingerprint corpus has no legs and
  measured unchanged). The A/B record contract moves (5 → 6): a record stores
  the leg targets.
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
(drops zero tool-use counts). Since WP-01.7: `digest.StreamUsage` (every
attempt's reported usage, an interrupted stream's `message_start` counters
included) and `UsageRecord.interrupted_attempts` / `RunUsage.interrupted_attempts`
(attempts whose output was never reported). WP-01.7 kept the cost a number
and left `is_billable_but_unpriced` alone: whether an interrupted attempt's
unreported output makes a total unknown is this decision's.

- Decision: —
- Rejected shortcuts: —
- Version / cache changes: —
- Consumers affected: —

## D-8 Source identity — `decided`: the page part by WP-11.1 ([PR #172](https://github.com/Abe-Borg/drawing-analyzer/pull/172)), the binding part by WP-06.2 ([PR #191](https://github.com/Abe-Borg/drawing-analyzer/pull/191))

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
- **Decision, WP-06.2's part: every evidence leg and every handle is a page**
  (the owner's rules, eight choices over two rounds, measured first; N6, U8).
  The page part above stands unamended.
  - **Cross-QC addresses sheets by host handles on both paths.** One
    assignment (`cross_qc._assign_handles`): `S001` … over the entries in
    source order (`_canonical_order`: `(source_id, page_index)`, natural order,
    when every entry has a source id; input order otherwise), so a reordered
    input is sent, keyed and bound identically. A handle names one page, and
    no handle is a sheet id of the set (`_handle_prefix`, Codex review: `S`
    unless one of the set's ids is one of its handles, then `H`, `K`, …), so a
    reference is a handle or an id, never both. The
    human sheet id is shown beside each handle (`===== SHEET S001 = M-101
    =====`, whole-set and map requests; the reconcile manifest already did) as
    display metadata, for cross-references and for the text a reviewer reads.
  - **One resolver binds every reference** (`_resolve_sheet_ref`): a handle
    names its own page; else a sheet id binds when exactly one page of
    the set carries it. An id more than one page carries is refused and
    counted, never bound to the first (D-2's WP-06.2 note). One validator
    serves both paths (`_finding_from_handles`), so the whole-set path grounds
    against the uncapped text like the sharded path (U8; plan WP-06 Step 6
    reverses WP-03A's scope). Claims are rebound through the same resolver
    (`_resolve_claim_handles`) and de-duplicated by page first.
  - **No first-wins label map anywhere a binding is made.** The arithmetic
    auditor's `_build_maps` maps an id two pages carry to no sheet, and such a
    claim is refused before it is checked (`arithmetic_ambiguous_sheet`). The
    prose harvest's synthesis id map does the same, so a statement whose
    primary is such an id goes set-level and such a second sheet is no leg.
  - **A cross-sheet leg is its page in the merge gate**:
    `critique._leg_targets` names `"<source>#p<page>"` (`SRC-0002#p1`); a leg
    with no source keeps its canonical id.
  - **Fallback ids stay display labels.** `cross_qc._fallback_id` is still
    `<stem>-p<n>`; two same-basename PDFs share it, which no longer matters to
    binding (handles), and a reply that names a shared one is ambiguous.
  - **Not decided here, named:** `investigate._sheet_id_map` still addresses
    the investigation tools by sheet id, a later finding overwriting an
    earlier id (0 collisions in the suite's 247 maps): the tool contract is
    WP-13's (a note on its row). Revision binding on every reopen (verify,
    investigate, markup) is WP-11.3's, under this decision's revision clause.
  - **Rejected shortcuts** (each measured on `acaa55e`): label-derived handles
    (`M-101`, `M-101#2`: +18 tests, every sharded fixture hardcodes `S###`, and
    a bare shared id stays ambiguous); keeping the caller's order (a reordered
    input gets new handles and a new key); keeping `_leg_targets` label-based
    (two legs to two same-id PDFs read as one target); checking an ambiguous
    claim unplaced (an unrouted finding and a FAILED receipt) or as a
    set-level note.
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
- **Version / cache changes:** none for WP-11.1's part. For an unchanged set
  the refs equal `list_sheets` field for field, and the render identity keeps
  the opened file's count, so every level-1 and level-2 key is byte-identical
  (`tests/test_drawing_cache_identity.py` passes unchanged). No
  migration-register row. `run_manifest.json` gains one additive key,
  `unread_pages`. WP-06.2's part: `_CROSS_QC_CACHE_CONTRACT` 8 → 9, the
  cross-QC user framing into its key (K2), the A/B `RECORD_CONTRACT_VERSION`
  5 → 6 (three register rows); digest, critique, identity, review-plan and
  citation keys byte-identical. `run_manifest.json`'s `cross_qc_discards` is
  filled on the whole-set path too and gains two additive counters
  (`legs_ambiguous_label`, `facts_ambiguous_label`); the audit stats gain
  `arithmetic_ambiguous_sheet`.
- **Consumers affected:** the pipeline's `total` and everything built on it
  (the digest stage's `items_in`, `ctx.sheet_count`, `RUN_END`'s
  `sheets_total`, the critique's eligible reads, progress), the two iterators
  (`expected_pages`), `_level1_partition` and `_critique_level1_partition`
  (an expected page they could not scan is a miss), `_GeometryOmissionSink`
  (inserts a routed page's geometry in page order), `ctx.unread_pages`,
  run.log's Sheets section, `run_manifest.json`, and the failed count of the GUI
  and the report (`sheet_count - ok_sheet_count`). WP-06.2's part: the
  cross-QC request builders and parsers, the cross-QC stage record (a
  warning), `run_manifest.json` (`cross_qc_discards`), the arithmetic
  auditor and its stats, the prose harvest's synthesis binding, the ledger's
  merge gate and the A/B harness (both through `critical_signature`), the
  markup and verification of whole-set conflicts (now grounded, with an
  evidence state on each leg), and `scripts/measure_evidence_coverage.py`
  (reads `cross_qc_discards`, unchanged code).

---

## Cache / schema migration register (plan WP-10 step 9)

Every slice that changes a cache namespace, key term, or serialized schema
adds one row. Never delete a cache directory or a historical export as a
migration.

| Namespace / schema | Old version | New version | Readable fields kept | Reusable content | Invalidation reason and scope | Slice / PR |
|---|---|---|---|---|---|---|
| Identity and review-plan caches (`identity_cache_key`, `review_plan_cache_key`) | Identity prompt `0659a7cd5e585485`; planner prompt `c14096d79af181a3` | Identity prompt `30cccf5dd7e52cb3`; planner prompt `20d583285e09dddb` | Every field; response and entry schemas are unchanged | Entries under the new source-framing contract replay normally; old entries remain on disk | Prompt optimization PO-01 adds shared source-data instructions and escaped typed blocks to these two requests. The existing prompt hashes and exact assembled-corpus hashes cover the changed content; no new key term or global schema bump. Both set-level stages miss under the old contract. A recomputed plan can change downstream critique profile keys through existing machinery; no digest/critique contract is changed here. `tests/test_intake_prompt_boundaries.py::test_old_prompt_cache_misses_and_new_prompt_replays` covers both stages | PO-01, [PR #192](https://github.com/Abe-Borg/drawing-analyzer/pull/192); `_plans/prompt-optimization.md` |
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
| Synthesis, focus report and prose-harvest structuring stage caches (`stage_cache_key("synthesis" / "focus" / "prose_harvest_item")`) | `_SYNTHESIS_CACHE_CONTRACT=1`, `_FOCUS_CACHE_CONTRACT=1`, `_HARVEST_CACHE_CONTRACT=1` | each 2 | Every field; the payloads are unchanged (`text`, `text`, `finding`) | None: every entry written under 1 misses once | An entry is now written only for a reply the model finished (D-1's WP-01.6 note): before, a reply cut off at `max_tokens` or the context window, one with no stop reason, a continuation or an unknown reason was stored whenever it parsed, and synthesis and the focus report stored a refusal's explanation as their text (served as the overview on every warm run). None stores a stop reason, so no read-side reject is possible; each stage's existing term is bumped (the WP-01.4 precedent), no key term, never `_SCHEMA_VERSION`. The next run pays one synthesis call per set (Opus 5.5), one focus call per focus run, and each harvest straggler once (Sonnet 5.5, low effort). Recorded residuals, left by the owner's decision: the review-plan, identity and verification keys have no term, so an entry an earlier version stored from a non-finished plan, identity or verdict keeps serving until its inputs change (a new term there could re-key the critique through `profiles_key`). Digest, critique, cross-QC, citation and investigation keys are byte-identical (`tests/test_drawing_cache_identity.py` passes unchanged). Old entries stay on disk (`tests/test_consumer_terminal_outcomes.py::test_an_entry_written_under_contract_1_misses_and_stays_on_disk`) | WP-01.6, [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184) |
| Identity cache (`identity_cache_key`, its corpus hash) and every reply's text (`core.reply_text.reply_text`) | corpus: an errored sheet's digest text; join: `"\n"` between every text block | corpus: its `[digest failed: …]` line; join: nothing across a `fallback` block | Every field | Identity: every entry for a set with no errored sheet carrying text. Every other namespace: every entry | Two changes, no term and no version. **The identity corpus** skips an errored sheet's digest text (a refusal's explanation, a cut-off read's prose); the corpus is a key input, so only a set with such a sheet re-keys (the key's own mechanism): one identity call, and the planner and critique re-key only if the new identity differs. **The join** moves no key: a reply without a fallback block reads byte-identical. Residual, recorded: a digest an earlier version cached from a fallback-split reply (possible since 1.3.0, real-time Opus 5) keeps its `"\n"` inside a word and any findings the broken JSON lost; no digest-only term exists and `_SCHEMA_VERSION` is barred. A critique split that way failed and was never cached | WP-01.6, [PR #184](https://github.com/Abe-Borg/drawing-analyzer/pull/184) |
| Cross-QC cache (`_cross_qc_cache_key`), both paths | `_CROSS_QC_CACHE_CONTRACT=6` | `_CROSS_QC_CACHE_CONTRACT=7` | Every field; the entry shape is unchanged | None: every cross-QC entry written under contract 6 misses once, on the whole-set path too | Host-side grounding changed again (B4; the owner's decisions): cross-QC grounds through the anchor's character-stream tier too (`anchor.SourceWords.joined_spans`), so for byte-identical request inputs a leg or fact whose quote differs from the sheet's text only by the named spacing joins (a number and a separated `"` `'` `%`, the feet-inches hyphen, letters merged by extraction; the quantity-aware veto through `critique._quantity_tokens`) is now admitted as TEXT_GROUNDED; and a quote or text with a number split around a lone `.` no longer grounds (`SET AT 5 IN` grounded on `SET AT . 5 IN`), and such a fact's quote joins no leg (its folded form is `""`). No key input covers any of it. One mechanism: the existing contract term, bumped; no key term, no `_SCHEMA_VERSION` bump. No release shipped contracts 4 to 6 (WP-05.1, WP-05.2 and WP-06.1 are unreleased), so a user upgrading from 1.7.0 pays one miss for all four bumps: one paid cross-QC pass per set. Measured over the suite: 0 of 738 grounding verdicts changed outside the new tests. The anchor stage is not cached; a newly anchored finding gets new verification and investigation entries through their own inputs (new paid work, by design, not a register row). Digest, critique, identity, review-plan and citation keys are byte-identical (`tests/test_drawing_cache_identity.py` and `tests/test_source_identity.py` pass unchanged; the critique merge-rule fingerprint and `_CRITIQUE_CACHE_CONTRACT=3` are unchanged, since the quantity reader is reused as it is), and the A/B `RECORD_CONTRACT_VERSION` stays 3 (a record stores the anchor as an arm output whose shape and meaning are unchanged). Old entries stay on disk | WP-05.3, [PR #187](https://github.com/Abe-Borg/drawing-analyzer/pull/187) |
| Critique cache, level 1 and level 2 (`critique_cache_key_level1`, `critique_cache_key`) | schema 10, `critique_contract=3` | schema 10, `critique_contract=4` | Every field; the entry shape is unchanged | None: every critique entry written under contract 3 misses once | The merge rule behind the stored post-merge findings changed (remediation WP-04.3, the owner's rules): `critique.critical_signature` carries quantity roles (`roles`, `ambiguous_roles`, read by `critique._quantity_roles`) and `critique.signature_conflicts` compares them, so two findings that give the same values to different roles, or one value to two roles, no longer merge, and an ambiguous role is kept apart from a bound one; and `critique._TAG_RE` no longer reads the `x12` of a tight `24"x12"` as a tag, so a pair it kept apart through that stray tag can now merge. An entry stored under 3 can hold either kind of merge the new rule would not make. One mechanism: the existing critique-only term, bumped (the WP-04.2 precedent); no key term, never `_SCHEMA_VERSION`. The merge-rule fingerprint is pinned under 4 (`b62e9526…`), computed over a corpus that gained 15 role and separator rows; over the extended corpus the contract-3 rule fingerprints as `b3660a7e…` (recorded in the test), and the values under 1 to 3 are untouched. Digest, identity, review-plan, citation and investigation keys are byte-identical (`tests/test_drawing_cache_identity.py::test_wp_04_3_moves_every_critique_key_and_no_other_key`, with the contract-3 keys pinned). Old entries stay on disk (`test_a_critique_entry_from_wp_01_4_misses_and_is_never_deleted`); the next exhaustive run re-critiques each sheet once. No release shipped contracts 1 to 3 (WP-04.1, WP-04.2 and WP-01.4 are unreleased), so a user upgrading from 1.7.0 pays one miss per sheet for all four bumps. The quantity reader's tokens are unchanged (`_quantity_tokens` is `_quantity_readings`' tokens), so no anchor and no cross-QC grounding verdict moved (measured: 0 of 1,072 and 0 of 769 in the suite) and the cross-QC contract stays 7. The prose harvest's structuring key hashes the item and the sheet, never the match, so no stage cache holds a merge outcome besides the critique's | WP-04.3, [PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188) |
| A/B harness arm records (`scripts/ab_findings_diff.RECORD_CONTRACT_VERSION`) | 3 | 4 | Every field; `critical_signature` gains `roles` and `ambiguous_roles` | None: `load_arm_records` refuses a v3 sidecar (`RECORDS_STALE_CONTRACT`) rather than compare it | A record stores `critical_signature` computed when its arm ran, and a v3 record has no role keys, which the rule reads as "no role" (a one-sided signal never conflicts), so a v3 baseline against a v4 variant would call a swapped `6 in main, 4 in branch` / `4 in main, 6 in branch` pair EXACT: the silent failure the version exists for (the owner's decision: store the roles and bump, rather than derive them at comparison time from the record's text). Refused, never deleted: re-run the arm | WP-04.3, [PR #188](https://github.com/Abe-Borg/drawing-analyzer/pull/188) |
| Critique cache, level 1 and level 2 (`critique_cache_key_level1`, `critique_cache_key`) | schema 10, `critique_contract=4` | schema 10, `critique_contract=5` | Every field; the entry shape is unchanged | None: every critique entry written under contract 4 misses once | The merge rule behind the stored post-merge findings changed (remediation WP-04.4, the owner's rules): the quantity reader behind `critique.critical_signature` reads a spelled range or list whole (`4 to 6 in`, `between 4 and 6 in`, `4 and 6 in`, `4 or 6 in`, and three or more numbers joined by commas, `critique._read_spelled`) and a compact `A` beside a voltage (`20A 120V`), and the signature carries `feet_inches` (`critique._feet_inches`: `12'` is `12ft0in`, `12'-6"` is `12ft6in`), which `critique.signature_conflicts` compares. An entry stored under 4 can hold a merge the new rule refuses (`4 to 6 in` folded into `6 in`), or a loose list kept apart from its tight twin, which now merge. One mechanism: the existing critique-only term, bumped (the WP-04.2 precedent); no key term, never `_SCHEMA_VERSION`. The merge-rule fingerprint is pinned under 5 (`020b7789…`), computed over a corpus that gained 17 residual rows; over the extended corpus the contract-4 rule fingerprints as `f6116986…` (recorded in the test), and the values under 1 to 4 are untouched. Digest, identity, review-plan, citation and investigation keys are byte-identical (`tests/test_drawing_cache_identity.py::test_wp_04_4_moves_every_critique_key_and_no_other_key`, with the contract-4 keys pinned). Old entries stay on disk (`test_a_critique_entry_from_wp_04_3_misses_and_is_never_deleted`); the next exhaustive run re-critiques each sheet once. No release shipped contracts 1 to 4 (WP-04.1, WP-04.2, WP-01.4 and WP-04.3 are unreleased), so a user upgrading from 1.7.0 pays one miss per sheet for all five bumps. The prose harvest's structuring key hashes the item and the sheet, never the match, so no stage cache holds a merge outcome besides the critique's (re-verified) | WP-04.4, [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189) |
| Cross-QC cache (`_cross_qc_cache_key`), both paths | `_CROSS_QC_CACHE_CONTRACT=7` | `_CROSS_QC_CACHE_CONTRACT=8` | Every field; the entry shape is unchanged | None: every cross-QC entry written under contract 7 misses once, on the whole-set path too | Host-side grounding changed for byte-identical request inputs (remediation WP-04.4, the owner's decision): the character-stream tier's quantity veto (`anchor._same_quantities`) reuses `critique._quantity_tokens`, whose new readings are guarded by the word after `in` and the word before the number, and a named letter-merge join can change those words. So a leg quoting `4 TO 6 IN A CLEAR` against a sheet printing `4 TO 6 IN ACLEAR`, or `ELEC ROOM 101A 120V` against `ELECROOM 101A 120V`, grounded before and does not now (constructed and pinned in `tests/test_quantity_residuals.py`); none of the suite's 908 grounding verdicts moved. One mechanism: the existing contract term, bumped; no key term. The five tripwires that pinned 7 are re-pinned to 8 (the approved bump) | WP-04.4, [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189) |
| A/B harness arm records (`scripts/ab_findings_diff.RECORD_CONTRACT_VERSION`) | 4 | 5 | Every field; `critical_signature` gains `feet_inches` | None: `load_arm_records` refuses a v4 sidecar (`RECORDS_STALE_CONTRACT`) rather than compare it | A record stores `critical_signature` computed when its arm ran: a v4 record holds the partial readings (`4 to 6 in` as `6in`, `2, 4, 6 in` as `6in`, no `20amp` beside `120V`) and no feet-inches pairs, which the rule reads as agreeing, so a v4 baseline against a v5 variant would call `12'` / `12'-6"` or `4 to 6 in` / `6 in` EXACT: the silent failure the version exists for. Refused, never deleted: re-run the arm | WP-04.4, [PR #189](https://github.com/Abe-Borg/drawing-analyzer/pull/189) |
| Cross-QC cache (`_cross_qc_cache_key`), both paths | `_CROSS_QC_CACHE_CONTRACT=8` | `_CROSS_QC_CACHE_CONTRACT=9` | Every field; `discards` gains two additive counters (`legs_ambiguous_label`, `facts_ambiguous_label`), which an older entry reads back as 0 | None: every cross-QC entry written under contract 8 misses once, on both paths | Host-side binding changed for byte-identical request inputs (remediation WP-06.2; N6, U8; the owner's rules): the whole-set path addresses sheets by host handles and binds every reply through the one resolver (a handle, else an id exactly one sheet carries; an id two sheets carry is refused where the first detection used to win), grounds every quote against the uncapped text and counts what it drops (`discards` is recorded there now), and rebinds its claims to their pages; the sharded path reads a reply's `sheet_id` through the same resolver; `_dedup_claims` keys on the page first; entries are ordered by source id and page (a no-op for every pipeline call, measured). No key input covers any of it. One mechanism: the existing term, bumped; no key term for it, never `_SCHEMA_VERSION`. The six tripwires that pinned 8 are re-pinned to 9 (the approved bump). No release shipped contracts 4 to 8, so a user upgrading from 1.7.0 pays one miss for all of them: one paid cross-QC pass per set. A conflict between two same-id sheets is new paid work downstream (a dual-crop verification call), and a whole-set conflict whose quote its sheet does not print is no longer reported; the verification and investigation keys are unchanged, and a conflict kept before keeps its entries. Digest, critique, identity, review-plan and citation keys are byte-identical (`tests/test_drawing_cache_identity.py` and `tests/test_source_identity.py` pass with new tests only). Old entries stay on disk | WP-06.2, [PR #191](https://github.com/Abe-Borg/drawing-analyzer/pull/191) |
| Cross-QC cache (`_cross_qc_cache_key`), its `prompt` payload | the three system prompts | the three system prompts and the user-turn framing (`user_framing`: `cross_qc_user_framing()`, the strings in `CROSS_QC_USER_FRAMING_NAMES`, verbatim) | Every field; the entry shape is unchanged | None, once: every cross-QC key changes (in the same release as the contract row above, so the same one miss) | K2 (remediation WP-06.2; the owner's rule): the task line, the set and shard headers, the sheet title and body, the shard task, the reconcile manifest and fact lines and task, the unknown-discipline mark and the `[TRUNCATED N chars]` marker were inline literals outside the key, so editing one changed the request while every key stayed the same. They are named module strings now, held verbatim beside the prompts, so a later edit re-keys through the key's own inputs (the `digest.SHARED_USER_FRAMING_STRINGS` precedent). The truncation marker never reaches a stored entry (a degraded result is never admitted); it is keyed so it need not be remembered when WP-06.3 decides N14. A separate change with its own mechanism, beside the contract bump for the binding: not a bump and a term for one change | WP-06.2, [PR #191](https://github.com/Abe-Borg/drawing-analyzer/pull/191) |
| A/B harness arm records (`scripts/ab_findings_diff.RECORD_CONTRACT_VERSION`) | 5 | 6 | Every field; `critical_signature["leg_targets"]` names pages (`SRC-0002#p1`) instead of sheet ids | None: `load_arm_records` refuses a v5 sidecar (`RECORDS_STALE_CONTRACT`) rather than compare it | A record stores `critical_signature` computed when its arm ran, and `critique._leg_targets` now names each leg's page (remediation WP-06.2, N6). A v5 record holds sheet ids there, which never equal a page, so a v5 baseline against a v6 variant would report every unchanged cross-sheet conflict as one with different legs, and a conflict whose leg moved to another PDF carrying the same id would have matched EXACT under v5. Refused, never deleted: re-run the arm | WP-06.2, [PR #191](https://github.com/Abe-Borg/drawing-analyzer/pull/191) |
