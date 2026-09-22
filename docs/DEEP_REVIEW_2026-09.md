# Deep review — drawing-analyzer 1.6.0 (September 2026)

A read-through of the whole engine (`src/drawing_analyzer`, ~52k lines), the
test fixtures, packaging and CI, looking for logic errors, bugs, poor use of the
Claude API, cost waste, and material design improvements. Nothing in the source
was changed by this review; every claim below was either **reproduced** with a
scratch script against the real functions, or **traced** through the code with
certainty. Items marked *plausible* were traced but not fully proven.

**Baseline.** The hermetic suite passes (2,297 passed, 5 skipped, 9 deselected);
the three failures in `tests/test_spec_documents.py` on the review box are an
environment defect (a broken system `cryptography` wheel panicking inside pypdf's
import), not project code.

**How to read the line references.** `file:line` numbers are against commit
`f5284ac` (the 1.6.0 release + record). Severity is about the effect on a real
review, not code aesthetics: HIGH = wrong or lost findings / a lost paid run,
MEDIUM = wrong numbers, wrong labels, or silent degradation, LOW = hygiene.

---

## 1. Executive summary — the ten things worth fixing first

| # | Finding | Where | Severity |
|---|---------|-------|----------|
| 1 | Post-anchor reconcile (Pass B) is complete-link in one direction only, so a finding saying **500 gpm** is folded into one saying **550 gpm** and the 500 value vanishes from every export | `ledger.py:688-703` | HIGH |
| 2 | Hyphenated units (`6-inch`) and thousands separators (`12,500 CFM`) get no or wrong measurement signature, so different pipe/duct sizes merge into one "reproduced" finding | `critique.py:647-653` | HIGH |
| 3 | A source PDF that becomes unreadable *after* the inventory aborts the **entire run** with an uncaught exception, discarding paid digests and writing no run.log / manifest | `render.py:932`, `render.py:1122` | HIGH |
| 4 | Verbatim quotes fail to anchor on ordinary punctuation/tokenization variance (`PSI,` vs `PSI`, `6 "`, `NOTE 3:`), so correct findings are branded `[QUOTE NOT FOUND]` — the hallucination flag — and skip verification | `anchor.py:104-151, 311-483` | HIGH |
| 5 | Cross-QC treats any quote shorter than six characters (`P-1`, `AHU-7`, `M-101`) as text-grounded without looking, even on a sheet with no text | `cross_qc.py:487-498` | HIGH |
| 6 | The cross-QC prompt tells the model to "lower the severity to `question`", but `question` is a category; every such item fails validation and is silently dropped | `cross_qc.py:171-173` | HIGH |
| 7 | A batch item the model **refuses** (`stop_reason="refusal"`) is never retried or rescued on either recovery transport; the refusal fallback only exists on the real-time path the GUI does not use by default | `batch_digest.py:628-647, 2119-2129` | MEDIUM |
| 8 | The report's chat widget commits an unrun `server_tool_use` to history (Stop during a mixed turn, continuation cap, refusal), after which every question 400s until "New chat"; the poisoned transcript is persisted and restored on reload | `html_report.py` chat JS 5447-5524 | MEDIUM-HIGH |
| 9 | The pre-run cost estimate ignores thinking tokens on the three vision reads per sheet and under-counts the text side; a dense 39-sheet real-time run can land ~$95–100 against a displayed $49–74 | `cost.py:51-56, 511` | MEDIUM |
| 10 | Two cache-correctness gaps (I-6): the per-tile placement label and the whole cross-QC user-turn framing are model-visible but outside every cache key | `render.py:870`, `cross_qc.py:1348-1410` | MEDIUM |
| 11 | There is no Cancel; quitting mid-run leaves a submitted Message Batch billing to completion with nothing collected, cached or resumable (no batch id is persisted) | `gui.py:1907-1913, 2906-2931` | MEDIUM |
| 12 | The API-key entry stays live during a run and rewrites `os.environ` on every keystroke; every later stage builds its client from that environment, so a Backspace mid-run 401s the verification/citation stages after the paid reads | `gui.py:1112-1123, 1851-1859`, `client.py:25-31` | MEDIUM |

The Claude API usage is, overall, careful and current (adaptive thinking stated
explicitly everywhere, effort in `output_config`, streaming above ~21k tokens,
strict tools, refusal fallback with a self-healing latch, correct batch and
Files API namespaces). The material API-side opportunities are cost, not
correctness: the ~90k-token image prefix of every sheet is billed 2.35× per
exhaustive real-time run when 1.45× is achievable, and the batch path never uses
prompt caching at all. Details in §3.

---

## 2. Confirmed bugs

### 2.1 Findings correctness (ledger, dedup, anchoring, grounding)

**B1. Pass B merges findings with conflicting measurements (HIGH).**
`ledger.py:688-694` matches a survivor `s` for entry `e` with
`all(_is_duplicate(e, m) for m in members[id(s)])` — only the *live* `e` is
compared against the survivor's members. The members `e` absorbed in Pass A
(`ledger.member_history(e)`) are never compared against `s`, and
`adopt_members` (`:703`) then carries them under the survivor. Pass A had refused
exactly that fold. Reproduced in the pipeline's own ingest order
(digest → critique → cross_qc): A `digest_json` "riser pump flow is **500** gpm
per riser schedule" (quote `RISER`), B `critique_1` "riser pump flow per riser
schedule", C `cross_qc` "riser pump flow is **550** gpm…". Pass A → two entries
(A+B; C kept apart by the 500 vs 550 signature). `seal(); reconcile_post_anchor()`
→ one entry "…550 gpm…" with sources `[cross_qc, digest_json, critique_1]`; the
string "500 gpm" no longer exists in text, quote or `supporting_quotes`. Order
C,A,B keeps both, so the outcome depends on which side is `e` — an I-7 violation
as well. The existing test `test_pass_b_keeps_a_conflict_carried_in_text_not_the_quote`
covers only the direction where the conflict is `e`.
*Fix:* require symmetric complete-link —
`all(_is_duplicate(me, ms) for me in member_history(e) for ms in members[id(s)])`
— and add the reverse-order twin of that test.

**B2. Hyphenated units carry no measurement signature (HIGH).**
`critique.py:647-653` `_MEAS_RE` allows only `\s*` between the number and an
alpha unit, so `6-inch` / `4-inch` (normal drawing phrasing) yield
`measurements == []`; `signatures_compatible` cannot block and `_is_duplicate`
merges on text overlap. Reproduced: "Provide 6-inch drain at column line 4" vs
"Provide 4-inch drain at column line 4" → Jaccard 0.857, `_is_duplicate=True`,
`merge_self_consistency` → ONE finding, text "Provide 4-inch drain…",
`confidence=REPRODUCED`. The same predicate drives `Ledger.add`
(`ledger.py:253`), so digest-vs-critique merges lose it too. This is the exact
class the `1/2"` fix closed, one spelling over. *Fix:* allow `[\s-]*` between the
number and an alpha unit (the tag lookbehind already excludes `M-101`).

**B3. Thousands separators split the number (HIGH).** The lookbehind at
`critique.py:648` excludes `.` and `/` but not `,`, so `12,500 CFM` signs as
`500cfm`. Reproduced: `12,500 CFM` and `1,500 CFM` get the identical signature
(so they can merge whenever the surrounding text overlaps enough), while
`12,500 CFM` vs `12500 CFM` get disjoint signatures and are *blocked* from
merging (duplicate singletons). *Fix:* add `,` to the lookbehind, accept
`\d{1,3}(?:,\d{3})+`, strip commas in `_meas_value`.

**B4. Verbatim quotes fail to anchor on routine tokenization variance (HIGH).**
`anchor.py:104-120` folds only whitespace, case and dashes; tokens are
whitespace-split PDF words (`:141-151`); the fuzzy window needs ≥85% bag overlap
(`:367-437`); the numeric veto requires exact token equality (`:311-353`).
Reproduced with quotes that are verbatim on-sheet text:

| on the sheet | model quote | result |
|---|---|---|
| `RATED 175 PSI, TYP.` | `RATED 175 PSI TYP` | UNANCHORED |
| `PROVIDE 6 " DRAIN` (inch mark extracted as its own word) | `PROVIDE 6" DRAIN` | UNANCHORED (veto fires on `6"` ≠ `6`) |
| `INCHDRAIN` (words merged by extraction) | `INCH DRAIN` | UNANCHORED |
| `NOTE 3:` | `NOTE 3` | UNANCHORED |
| `150 GPM (568 L/MIN)` | `150 GPM 568 L/MIN` | UNANCHORED |
| `12' - 6"` | `12'-6"` | UNANCHORED |
| `2 %` | `2%` | UNANCHORED |

UNANCHORED excludes the finding from `verify._is_verifiable` (`verify.py:166-175`)
and `investigate._candidates` (`investigate.py:1325-1335`), inks it as a margin
callout labelled `[QUOTE NOT FOUND]`, and counts it as a hallucination. The
docstring (`anchor.py:17-18`) says normalization "folds most" punctuation
artifacts; it folds none of the above. *Fix:* strip leading/trailing sentence
punctuation per token (keep `"`, `'`, `/`, `%`, `-` inside numeric tokens), and
add a final character-stream tier before UNANCHORED (concatenate normalized words
with a char→word index, search the quote with spaces removed, map the span back
to word rects, run `_numbers_agree` on the recovered span so the veto holds).

**B5. Cross-QC short quotes are "grounded" without a check (HIGH).**
`cross_qc.py:487-498` `_grounded`: `if len(q) < 6: return True`, consulted by
`classify_quote_evidence` before the no-text branch. Reproduced: a textless
geometry with quote `P-1` / `AHU-1` / `M-101` → `TEXT_GROUNDED`; a text-bearing
sheet that lacks `AHU-7` with quote `AHU-7` → `TEXT_GROUNDED`. Consequences: a
hallucinated tag-quote leg is accepted and counted as grounded (the WP-02
counters are wrong for the most common quote form), and on a scanned/hybrid sheet
the §8.4 tile fallback (`anchor.py:526`, only for `EVIDENCE_UNAVAILABLE`) never
fires for a short quote, so equipment tags and sheet ids — exactly what cross-QC
quotes — go UNANCHORED and never reach verification. *Fix:* return
`EVIDENCE_UNAVAILABLE` when the sheet has no evidence text regardless of quote
length, and run the real substring test for any non-empty quote.

**B6. Cross-QC prompt/validator contradiction drops uncertain conflicts (HIGH).**
`cross_qc.py:171-173` instructs "when you are not certain two sheets truly
conflict, lower the severity to `question`"; `question` is a *category* and
`severity` must be in `{high, medium, low}` (`_validate_cross_item` `:601`,
`_finding_from_handles` `:736`). Reproduced: an item with `severity: "question"`
→ `None` → dropped with an INFO-level "unplaceable/invalid" count. The items the
sentence targets are exactly the ones lost. The critique prompt
(`critique.py:182-183`) already words this correctly. *Fix:* "set `category` to
`question` and `severity` to `low`".

**B7. `run_auditors` id-dedup silently drops a distinct arithmetic mismatch (MEDIUM).**
`auditors/__init__.py:119-127` dedups by `f.id`; `arithmetic.py:489-515` builds
every finding with `category="conflict"` and `source_quote=claim.quote`, so two
claims quoting the same row share an id (`compute_finding_id` hashes
sheet/category/quote only, `models.py:820-845`). Reproduced: claims
`sum [20,20,20] = 540` and `factor [1500, "1.3"] = 2000` on the same quote →
`audit_arithmetic` returns two findings with one id; `run_auditors` keeps one
while `stats["arithmetic_mismatched"] == 2`. *Fix:* drop the content-id dedup
there (the ledger already merges true duplicates) or key on `(id, text)`.

**B8. `Finding.id` is not unique across distinct findings, and four consumers treat it as identity (MEDIUM).**
Two different issues quoting the same on-sheet string — the exact case
`_is_duplicate` keeps apart — share an id (`models.py:1258-1263`). Traced
consequences: `assign_qc_ids` (`models.py:1433-1437`) tie-breaks on `f.id`, so
**QC numbering depends on ingest order** (reproduced: X "pump P-1 has no
isolation valve…" and Y "motor horsepower for P-1 disagrees…", both quoting
`PUMP P-1`: order XY → X=QC-001, YX → Y=QC-001, contrary to the docstring);
`annotate.py:2424-2428` `mark_page_by_finding[_f.id]` is last-write-wins, so when
one of the two overflowed to the notes page the other's index row links to the
wrong page; `annotate.py:2242-2253` bookmark dedup gives the second no outline
entry; the auditor dedup above. *Fix:* fold a text hash into the id (keep a
quote-only `content_key` for cache rebinding) or assign a run-local uid at ledger
ingest.

**B9. Merge is not lossless (MEDIUM).** `ledger.py:513-576` discards the loser's
`text` and `recommended_action` (only its quote survives into
`supporting_quotes`). Reproduced with two BFP-1 findings carrying different
actions: the loser's action is gone from every export.

**B10. Same cross-sheet conflict with primary/leg swapped survives twice (MEDIUM).**
`cross_qc.py:1310-1331` `_dedup_findings` keys on (primary, category, quote,
legs); a shard reporting A→B and the reconciler reporting B→A are different keys,
and the ledger cannot merge them (`_same_sheet`, `critique.py:593`). Both sheets
get clouded twice. *Fix:* key on the unordered set {primary} ∪ legs.

**B11. Boilerplate "No conflicts noted on this sheet." becomes a medium SHEET-level finding (MEDIUM).**
`prose_harvest.py:139-146` `_TRIVIAL_RE` allows exactly one trailing qualifier,
so "No conflicts noted on this sheet.", "No conflicts identified at this time.",
"None apparent on this sheet.", "No cross-discipline items noted for this sheet."
all survive the filter. Each costs a Sonnet structuring call, and when that call
fails `_degraded_entry` (`:512-531`) ingests the boilerplate verbatim — reproduced
end to end with `harvest_prose(client=None)`: a ledger entry with
`severity='medium'`, `category='coordination'`, `anchor_hint='SHEET'`, i.e. a
margin callout announcing that nothing is wrong. *Fix:* make the qualifier group
repeatable and add a content-token allowlist test.

**B12. `deg` and `°` sign differently (LOW).** `critique.py:614-618, 659-662`:
`90 deg F` vs `90°F` → `{'90deg'}` vs `{'90°f'}` → incompatible → the same
setpoint issue from two reads never merges.

### 2.2 Run robustness

**R1. A source that becomes unreadable after the inventory aborts the whole run (HIGH).**
`render.py:932` (`iter_rendered_sheets`: `pymupdf.open(str(path))` unguarded)
and `render.py:1122` (`iter_sheet_prescan`). `list_sheets` (`render.py:150-153`)
silently *skips* an unopenable file, so `refs`/`total` omit it while `paths`
(`pipeline.py:2883`) still carries it into `_level1_partition` (`:2968`) and
`_rendered_stream` (`:785`). Nothing between `pipeline.py:2883` and `:3086`
catches; `extract_drawing_context` propagates. Reproduced: two 1-page PDFs, fake
client, the second file unlinked after `inspect_inputs` accepted it → `RUN
ABORTED: FileNotFoundError` on both the no-cache render-stream path (one paid
digest already made, discarded) and the DigestCache/prescan path; the batch path
fails identically after uploading earlier sheets' images. No `DrawingContext`,
no `run.log`, no `run_manifest.json`, no export; the GUI worker
(`gui.py:1949-1950`) shows a generic error dialog. Realistic triggers: a
network-share hiccup, a Windows AV/backup lock, a user re-exporting a set over the
same filenames mid-run — the situation Phase 18C mutation detection was built for,
but that detection only guards the *markup* reopen (`pipeline.py:2331-2347`). The
critique stage (`pipeline.py:3590-3630`) and `iter_region_crops`
(`render.py:711-740`) *are* guarded. *Fix:* wrap `pymupdf.open` in both
iterators, report one `on_page_error(ref, exc)` per page from the inventory's
page count and `continue`; wrap the digest phase so the journal and context
always ship (digest `StageResult` FAILED/PARTIAL).

**R2. A refused batch item is silently lost (MEDIUM).**
`batch_digest.py:2119-2129` classifies `stop_reason="refusal"` as
`error="empty digest (stop_reason='refusal')"`; `_item_retry_params`
(`:628-647`) retries only `errored`/`expired` envelopes or a succeeded item with
`stop_reason == "max_tokens"`, so a refusal returns `None`. The GUI's default is
the batch transport (`use_batch=True`) with `RECOVERY_BATCH`
(`pipeline.py:1019-1028`), where `fallbacks` is rejected by the API
(`api_config.py:1321-1327`) — so the one place a refusal can occur unrecovered is
the one place with no handling. Reproduced: a succeeded envelope with
`stop_reason="refusal"`, `content=[]` → sheet `ok=False`, zero resubmissions,
zero direct-rescue calls under both `RECOVERY_BATCH` and `RECOVERY_DIRECT`.
`stop_details` (category/explanation) is never read anywhere. *Fix:* treat
refusal as retryable on a transport where the fallback applies — resubmit the
identical params as a batch item with `model=claude-opus-4-8` (the code's own
argument at `api_config.py:1314-1319`), or route it through
`_rescue_failed_items_sync`, whose `stream_message` attaches `fallbacks:"default"`;
log `stop_details`.

**R3. Harvest of an abandoned batch drops the ledger record for canceled items (LOW).**
`_harvest_abandoned_batch` (`batch_digest.py:884-903`) counts every slot with
*any* envelope as `responded`, and `_mark_batch_abandoned` is then called with
`responded` excluded (`:1243-1247`, `:1520-1524`, `:2429-2433`). The real Batches
API returns `result.type == "canceled"` envelopes for a canceled batch's
unfinished items; `_parse_item` turns those into error digests with no
`usage_attempts`, so the primary attempt leaves no record at all — contradicting
the contract at `:408-425`. Reproduced with the real envelope shape: a sheet's
ledger reads `[(2, BATCH, COMPLETE)]` with attempt 1 missing; with the test
helper's fake (which yields *no* envelope for unfinished items,
`tests/test_drawing_batch.py:2585-2594`) it reads correctly, which is why the
existing test passes. *Fix:* count a slot as responded only when
`result.type == "succeeded"`.

**R4. The report chat widget poisons its own history (MEDIUM-HIGH).**
`html_report.py` chat JS: `stripDanglingToolUse` (5447-5449) filters only
`type === 'tool_use'`; the Stop branch (5492-5507), the `pause_turn` commit
(5515-5521) and the `MAX_CONTINUATIONS` exit (5522-5524) can all commit an
assistant turn holding a `server_tool_use` (web search/fetch) that never ran;
`hasToolUse`/`dropUnansweredTail` (5323-5342) also test only `tool_use`, so a
saved transcript ending in such a turn is restored intact. Per the server-tools
docs, a user text turn after an assistant turn holding a `server_tool_use` with no
result block is a 400 ("…found without a corresponding web_fetch_tool_result
block"). Scenario: the reader asks the shipped starter "Do the cited code sections
check out?", the model calls `query_findings` and `web_search` in one parallel
group, the reader presses Stop; the client tool is stripped, the unrun web search
is committed, and every subsequent question fails until "New chat"; F5 restores
the poisoned thread. *Fix:* treat a `server_tool_use` whose id has no
`*_tool_result` in the same message as dangling everywhere the client kind is,
and strip + note on continuation-cap exhaustion.

**R5. Process-pool markup path loses the MARGIN → REVIEW_NOTES reroute in the plan (LOW-MEDIUM, I-7).**
`annotate.py:1963-1964` mutates `placement.expected`/`required_components` in
place; with ≥2 sources and ≥2 workers (default `DEFAULT_ANNOTATE_WORKERS = 2`,
spawn context at `:2587`) the mutation happens on the child's pickled copies;
receipts return with the child's rerouted placements while `write_reviewed_pdfs`
builds `all_placements` from the parent's untouched units (`:2795-2818, :2939`).
Result: `markup_manifest.json`'s `placements[i].expected == "MARGIN"` disagrees
with `receipts[j].placement.expected == "REVIEW_NOTES"` for the same
`placement_id`, and the manifest differs between `DRAWING_ANALYZER_ANNOTATE_WORKERS=1`
and 2. Coverage status is receipt-derived and unaffected. *Fix:* return the
mutated placements in `_ReviewedPdfOutcome` and overwrite by `placement_id`.

**R6. Hybrid mode spools every render to disk and never reads it (LOW).**
`pipeline.py:3045-3060` creates `RenderedSheetSpool` whenever
`run_critique and not use_batch`, but `_rendered_for_critique` takes the batch
branch when `critique_use_batch` is true (`:1549-1566`) and returns before the
spool branch. Effect: 3–8 MB of PNG writes per sheet for nothing plus a full
second rasterization for the critique upload.

**R7. Investigation error paths orphan evidence (LOW).** `investigate.py:997-1001`
(API failure) and `:942-944` (initial crop failure) return before the common
tail at `:1128`, so crops already saved by `_ToolExecutor` are attached to neither
`finding.verification.evidence` nor `investigation.json`.

### 2.3 Citation and edition checks

**C1. A citation reply split across citation text blocks is glued with `\n` and becomes unparseable (HIGH-MEDIUM).**
`citation_check.py:913` builds `raw_text = _message_text(resp)`;
`digest.py:753-761` joins text blocks with `"\n"`. Citations are always on for
web search and enabled explicitly on fetch (`api_config.py:1181`), and the API
returns each cited span as its **own** text block. When the model cites a fetched
sentence inside a `"note"` string the JSON acquires a raw newline; `json.loads`
rejects the control character; `_tolerant_json_object` fails for both attempts in
`_parse_assessments` (`:736-750`). Reproduced: `JSONDecodeError: Invalid control
character`, `parsed=False`; the identical blocks joined with `""` parse to
`CHECKED_SUPPORTS`. Every claim in that chunk becomes `UNCHECKED "no verdict"`,
`result.partial=True` holds the citation stage (and via §8 the run) at PARTIAL,
and the chunk is never cached (`:1278-1281`), so the web searches are re-billed
on every warm run. *Fix:* join with `""` for the citation parse (a citation split
is contiguous text, not a paragraph break); structured outputs are not an
alternative here because `output_config.format` is incompatible with citations.

**C2. The edition audit reads the capped `sheet_text` (MEDIUM).**
`citation_check.py:343-368, 417-418, 496-500` and `harvest_code_editions`
(`:268`) read `geom.sheet_text` rather than `models.sheet_evidence_text()` — the
helper WP-03A introduced for exactly this. Reproduced: a 16.5k-char general-notes
sheet whose last line is `CODES: NFPA 13, 2019 EDITION.` → the basis is empty →
a ref `NFPA 13-2016 §8.15.1` yields no divergence finding; with an identity entry
carrying the quote, corroboration fails and the finding degrades to
low/advisory instead of medium/DETERMINISTIC. Code-summary sheets are precisely
the sheets that exceed 15k characters.

**C3. Citation cache writes are priced at the 5-minute rate although the request asked for 1 hour (LOW-MEDIUM, ledger accuracy).**
`citation_check.py:855-865` uses `system_prompt_with_cache`/`tools_with_cache`
with `PHASE_CITATION`, which is absent from `_PHASE_CACHE_POLICY`
(`api_config.py:884-894`) → default policy → `ttl: "1h"`.
`pipeline.py:2264-2280` records the citation usage with `cache_write_tokens` but
no `cache_write_ttl`, so `usage_record_cost` prices those writes at 1.25× instead
of 2× — a 37.5% under-report on those records. Only the investigation record
passes the TTL (`pipeline.py:2185`). This is the defect `pricing.py:35-39` says
was fixed; it was fixed for one stage. *Fix:* derive `cache_write_ttl` inside
`_record_usage` from the phase policy so the next stage cannot forget it.

**C4. `find_text` is described to the model as "Free and instant" but charged against the six-request evidence budget (MEDIUM).**
`investigate.py:414-420` vs `:1048-1071` (`tool_round += len(granted)` for every
granted block). A model that runs three `find_text` calls to locate a schedule
row has three crops left, or exhausts the budget searching and is forced into
`_BUDGET_EXHAUSTED_TEXT` → UNCERTAIN without having looked. *Fix:* exempt
`find_text` from `tool_round` (or give it its own cap) and reword `:835-838`.

**C5. Sources dropped from the citation evidence trail (LOW).**
`citation_check.py:781-791` scans only the final response; after a `pause_turn`
the earlier responses' `web_search_tool_result` blocks are never scanned, and
`web_fetch_tool_result` blocks are never read at all.

**C6. Em dash is not an edition separator (LOW).** `citation_check.py:252-253,
328` accept the en dash but not U+2014; `NFPA 13 — 2019 EDITION` harvests
nothing. CAD title blocks use em dashes routinely.

### 2.4 Cost estimate and ledger accuracy

**$1. The estimator ignores thinking tokens on the three vision reads per sheet (MEDIUM).**
`cost.py:54-56` (`_ASSUMED_OUTPUT_TOKENS_PER_SHEET = 2_000`, comment "well under
the 16k cap" — the cap is now 64k, `digest.py:63`) and `cost.py:511`
(`_ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ = 1_500`) model visible output only,
while both reads run adaptive thinking at effort `high` and thinking bills at
the output rate. The verification constant was corrected for exactly this
(`cost.py:516-519`); the two highest-volume stages were not. Worked example (39
sheets, ARCH E 36×48 vector, exhaustive): +6,000 output tokens per read adds
**+$17.55** to a FAST run whose displayed high band is $73.94 (~24% under-quote).

**$2. `_ASSUMED_PROMPT_TOKENS_PER_SHEET = 800` is 2–8× low (LOW-MEDIUM).**
`cost.py:51-53`; `SheetCostBasis.text_chars` (`models.py:472-474`) is carried
precisely for this and never read by `estimate_image_tokens_for_bases`
(`cost.py:158-233`). Measured: digest system ≈ 926 tokens, critique system ≈ 967,
per-sheet framing + 36 tile labels ≈ 733, capped text layer up to ≈ 3,750–5,000.
Real text side ≈ 1.7k (sparse) to 6.7k (dense) per read.

**Worked example, for calibration.** Per sheet at the 6×6 grid / 1560 px vector
target: overview 1560×1170; interior tile 1561×1171 (1.83 MP, 2,438 tokens,
168 DPI); **90,276 image tokens per sheet** (measured), 177,008 under the
conservative allowance (1.96×). 39 sheets: FAST $48.64–$73.94, ECONOMY
$31.11–$35.98, HYBRID $40.96–$45.84 as displayed; the arithmetic, batch factor,
cache multipliers and per-stage model resolution all cross-check exactly against
`core/pricing.py`. Adding the missing terms ($1, $2, and the critique cache-miss
case in §3.3) a dense 39-sheet FAST run can land ~$95–100.

**$3. Hybrid/preflight waste.** See R6; also the GUI profile preflight
(`profiles.py:309` → `render.iter_sheet_prescan`) hashes every file's full bytes
and walks every page's object graph just to get sheet ids and cost bases; the
hash-free `render.iter_sheet_cost_bases` (`render.py:1006-1080`) exists and is
unused by the GUI. Measured on a 40-page 2.6 MB PDF: 333 ms vs 1,330 ms.

### 2.5 Cache correctness (I-6) and determinism (I-7)

**K1. The per-tile placement label is outside every key (MEDIUM).**
`render.py:870` sets `tile.label = tiling.position_label(...)` ("upper-left;
~0-20% across, ~0-17% down"); `digest.py:631-640` interpolates it into the
user turn. The prompt-version hashes cover the *template* only
(`digest.py:335-360`), the level-2 keys hash PNG bytes + `sheet_text`, and the
level-1 render identity (`render.py:658-676`) carries no label format.
Rewording the label changes the request bytes with every key unchanged.

**K2. Cross-QC user-turn framing is outside the stage cache key (MEDIUM).**
`cross_qc.py:1348-1410` hashes the three *system* prompts but not
`_CROSS_QC_TASK` (`:175-178`), the whole-set/map/reconcile framing
(`:951-966, :969-990, :993-1010`), or the `[TRUNCATED N chars]` marker (`:897`).
Every other text stage hashes its rendered user text.

**K3. Structured flag + batch transport mislabels level-1 entries (LOW).**
`batch_critique.py:341-362` pins `structured=False` and its level-2 key omits
`structured_key`, but `pipeline.py:1445-1463` (`_ingest_miss`) rebuilds the
level-1 key with `critique_structured_outputs_enabled(model)` (still True — the
batch never trips the latch), parking a fenced-produced merge exactly where the
next real-time structured run looks. The env flag is also a silent no-op on batch
runs.

**K4. Review-plan stage flips PARTIAL (cold) → COMPLETE (warm) on identical inputs (MEDIUM, I-7).**
`review_planner.py:307-326` counts total-cap trimming as `dropped`;
`pipeline.py:3480-3489` maps `dropped_items > 0` → PARTIAL → the run rolls up
PARTIAL. The cache stores the already-trimmed plan and the warm path re-sanitizes
it (`:475-488`) → `dropped=0` → COMPLETE. Reproduced: 5 disciplines × 20 items,
cap 60 → cold `dropped=40`, warm `dropped=0`. Root cause: `PLANNER_SYSTEM_PROMPT`
(`:122-125`) states "at most 25 items per plan" but never the 60-item total, so
any ≥3-discipline set overruns by construction.

**K5. QC numbering depends on ingest order** — see B8.

### 2.6 Deterministic auditors (false positives that ink as DETERMINISTIC)

**A1. Any row of three 2-digit numbers becomes a "CSI spec citation" finding (MEDIUM).**
`references.py:583-609`. Reproduced: `FLOW TEST 20 20 20 TOTAL 540` → low
DETERMINISTIC "Cites specification section 20 20 20…"; `CFM 10 15 25` → another.
That is the flow-test row the arithmetic auditor exists for. *Fix:* require a
lexical cue (SECTION/SPEC/DIV/§) or a real MasterFormat division.

**A2. Naming auditor reports `P-3` (pump) as a misspelling of `3P` (breaker poles) (MEDIUM).**
`naming.py:74-89` `_cluster_key` = (letters in order, digits concatenated),
ignoring interleaving; the has-winner branch (`:217-222`) never consults
`_arrangement`. Reproduced on E-401 `20A 3P 20A 3P 30A 3P 15A 1P` + M-401
`PUMP P-3` → DETERMINISTIC drift finding. Same collision for 1A/A1, 2P/P-2.

**A3. Reference auditor is O(references × sheets) with a heavy constant (MEDIUM).**
`sheet_ids.py:470-476` `classify_reference` rebuilds the normalized id set and
runs `closest_in_set` (normalize + sort + Levenshtein against every id) on EVERY
unresolved reference before the cheap gates. Measured on a synthetic 400-sheet ×
10k-word set: `audit_references` **213 s** (naming 6.3 s, titleblock 5.9 s,
sheet_index 2.3 s); cProfile on 40 sheets: 304,680 Levenshtein calls, 2.34M
`normalize_sheet_id` calls. The "free" battery is minutes on a data-center set.
*Fix:* cache the normalized id set on `SheetInventory`, memoize per normalized
target, compute `closest_in_set` lazily only for MISSING/MALFORMED.

**A4. Reference trigger vocabulary misses common phrasings (MEDIUM, false negatives).**
Measured no-harvest for `SEE DWG M-501`, `SEE DWG. M-501`, `REFER TO SHEET
M-501`, `SEE SHEET NO. M-501`, `REF. M-501`, `SEE DETAIL 3 ON M-501`,
`SEE M-501 AND M-502 FOR`; only the first target of `SEE DRAWINGS M-501, M-502`
(`references.py:116-125`).

**A5. Sheet-id detection picks the extreme bottom-right id-shaped token (PLAUSIBLE, layout-dependent).**
`references.py:381-393`. Reproduced mechanism: `M-101` with a project number
`A23-101` to its right → `A23-101`; a paper-size `E1` below it → `E1`;
`M-101-REV2` in the CAD strip → `M-101-REV2`. A mis-detected sheet vanishes from
the inventory under its real name, every reference to it becomes
MISSING_FROM_SET, and a foreign grammar is learned. *Fix:* prefer a token
adjacent to a SHEET / SHEET NO / DWG NO label; penalize PROJECT / JOB / SIZE
neighbours.

**A6. `FM` in `_STANDARD_BODIES` (`sheet_ids.py:312-316`)** makes
`never_a_sheets_own_id("FM-101")` True, so an FM-* sheet's real title-block id
is removed from the preferred pool in `detect_sheet_id_word`
(`references.py:381-384`). The sheet is not lost outright: `pool = preferred or
candidates` keeps `FM-101` when it is the only id-shaped token on the page. But
any other non-vetoed id-shaped token — a `SEE M-101` in a note, which most real
sheets carry — then wins regardless of position, and the sheet is inventoried
under that wrong name while every reference to `FM-101` becomes MISSING_FROM_SET.

**A7. A prose sheet can be read as THE drawing index** (`sheet_index.py:86-143`:
header phrase anywhere + ≥3 grammar-valid ids anywhere). A notes sheet reading
"REFER TO THE DRAWING INDEX ON THE COVER SHEET / SEE SHEETS M-101 M-102 M-103"
on a 7-sheet set → three "present but not listed" findings; on a 400-sheet
partial package, 397.

**A8. `_numbers_in_text` counts digits inside sheet ids/tags as present**
(`arithmetic.py:253-275`): `SEE FP101 TOTAL 540 AT 439 GPM` lets a claim whose
term is really the sheet number promote to TEXT_EXTRACTED / DETERMINISTIC ink.
Also `parse_number("1e3")` → 1 (silent truncation).

### 2.7 Report and markup

**H1. Sorting the findings table never recomputes the repeat grouping (LOW).**
`html_report.py` `sortBy` (2397-2418) never calls `apply()`; hidden followers can
move above their visible lead after a sort. CLAUDE.md states the opposite.

**H2. A quote-less sheet-level finding is branded "Unanchored" in the report (LOW).**
`_finding_display_status` (706-718) maps every UNANCHORED to the chip;
`anchor.py:492` returns `method="no_quote_no_tile"` for a SHEET absence finding
that never had a quote, which the PDF correctly labels `[NO QUOTE TO CHECK]`.
The mislabel also feeds `#da-findings`, the `query_findings` tool description
and the starter "Which findings could not be verified…".

**H3. Chat cost readout ignores web-search billing and server-loop input (LOW).**
`renderUsage` (4244-4279) prices tokens only; `usage.server_tool_use.web_search_requests`
is never read ($10 per 1,000 searches); the final `message_delta.usage` is read
only for output tokens.

**H4. Set identity regex still fires on ALL-CAPS notes (LOW-MEDIUM).**
`set_identity.py:202-222`: `WHERE CLEARANCE IS 1000 MM MINIMUM` → `IS 1000`,
`INSTALL AS 2019 DRAWINGS SHOW` → `AS 2019`. With `_MAX_WINDOWS_PER_SHEET = 3`
these displace real edition mentions and invite fabricated adopted codes.

### 2.8 App shell, key handling, updater, packaging, CI

**G1. Quitting is the only "cancel" and it does not stop API spend (MEDIUM).**
`gui.py:2906-2931` (`_on_close_request` → `destroy()`), `gui.py:1907-1913`
(daemon worker, no cancellation handle), no Cancel button anywhere in the GUI,
and the pipeline exposes no cancel event; `batches.cancel` exists only in the
stall-recovery path (`batch_digest.py:699`). Scenario: a 39-sheet Economy run
submitted as one Message Batch; the user clicks X and confirms; the process
exits, the batch continues server-side and bills all 39 sheets; nothing is
collected, cached or resumable because no batch id is persisted, so the next run
pays again. The quit prompt ("the API calls already made are still billed")
understates the loss for batch mode. *Fix:* thread a `threading.Event` through
`extract_drawing_context`; on quit (and a new Cancel button) cancel any in-flight
batch, or persist the batch id under the config dir and harvest it on relaunch —
`_harvest_abandoned_batch` already exists for exactly that shape.

**G2. The API-key field stays live during a run (MEDIUM).**
`gui.py:1112-1123` (`_on_key_changed` sets/pops `ANTHROPIC_API_KEY` per edit);
`gui.py:1851-1859` disables analyze/clear/html/reviewed/export/focus/specs but
never the key entry; `client.py:25-31` rebuilds the cached client whenever the
env value changes; every stage resolves its client lazily. Scenario: two hours
into an exhaustive run the user opens the key section and presses Backspace →
the next stage's `get_client()` builds a client with the truncated key → 401s →
verification/citation/investigation go FAILED/PARTIAL after the paid digest and
critique stages; an emptied field makes `get_client()` raise mid-run. *Fix:*
disable the entry while busy and pass an explicit client built from a key
snapshot at Analyze time instead of routing the key through the process
environment (which is also inherited by every child: `os.startfile` targets,
`xdg-open`, the annotation process pool, and WER crash dumps).

**G3. A UTF-8-BOM key file is loaded with the BOM, migrated into the keyring, and the plaintext file deleted (MEDIUM).**
`api_key_store.py:226` (`read_text(encoding="utf-8").strip()` — U+FEFF is not
whitespace), `:230-231` migration, `:159` removal; no key-shape validation
anywhere. Reproduced with the real module: the keyring now holds `'﻿sk-ant-…'`
and the legacy file is gone. Scenario: the user creates the documented legacy key
file with Notepad's "UTF-8 with BOM" → every call 401s with no diagnostic, the
original file is deleted, and the broken value is what the keyring serves on
every launch. *Fix:* `encoding="utf-8-sig"`, loose `sk-ant-` shape validation
before migrating, never delete the legacy file unless the migrated value passes.

**G4. The PyInstaller spec bundles every stray file under the package dir, including the documented legacy key-file location (LOW-MEDIUM, local-build foot-gun).**
`packaging/windows/drawing-analyzer.spec:35` `collect_all("drawing_analyzer")`
(default excludes are only `*.py/*.pyc/__pycache__/*.dist-info`);
`core/app_paths.py:31-33` makes `src/drawing_analyzer/drawing_analyzer_api_key.txt`
a real key location for source installs. A maintainer building the installer on
a machine that used that file ships the key inside `DrawingAnalyzerSetup.exe`.
CI builds are clean checkouts. *Fix:* explicit `datas` plus a build step that
fails on any `sk-ant-` string under `dist/`.

**G5. Release gates test one dependency set, the installer ships another (LOW-MEDIUM).**
`release.yml:267-275` runs `run_acceptance.py` after an unconstrained
`pip install -e ".[dev,browsertest]"`; the lock is installed only afterwards
(`:282`) for the license audit; the installer is built with the lock (`:118`)
but `requirements-release.lock` contains no GUI dependency (customtkinter,
tkinterdnd2, keyring, pywin32-ctypes float) and `pyinstaller-hooks-contrib`,
which supplies the keyring/tiktoken hooks, is unpinned (`:119`). *Fix:* install
under the constraints in `test`/`gates`, extend the lock to `[gui]`, pin the
hooks package.

**G6. The installer is hashed at download time only (LOW).** `updates.py:416-424`
verifies during download; `verify_sha256` (`:332-348`) is never called by the
GUI; `gui.py:2813-2824` can sit at the "Install?" prompt for hours before
`spawn_installer` runs a file in user-writable `%LOCALAPPDATA%`. Re-hash
immediately before `os.startfile`.

**Security posture of the update channel.** Integrity in transit, not
authenticity: the sha256 lives in `latest.json` served from the same origin as
the binary (`updates.py:97-106`), the manifest `url` may be any https host
(`:254`), there is no signature and no host pin, and every install auto-checks
daily. Any principal with release-write (a maintainer account, or the
`contents: write` token the `publish` job holds, `release.yml:337-339`) can ship
code that every install offers within 24 h; `docs/RELEASE_WINDOWS.md:133-135`
overstates the protection. https is enforced only on the first hop
(`updates.py:278-289, 392-393`; the stdlib redirect handler follows a `Location`
to http). The auto-downloaded installer carries no Mark-of-the-Web, so
SmartScreen is bypassed and the sha256 is the only gate; `installer.iss:40`
allows an all-users install that UAC-elevates the unsigned binary from a
swappable path. Downgrade is correctly impossible and rc tags never reach
`releases/latest`. *Recommend:* sign the manifest (ed25519/minisign-style, public
key embedded in the app), pin download hosts, cap the download size (the
manifest is capped at 64 KiB, the installer is not), reject non-https redirects,
re-verify before launch, and consider free OSS Authenticode so Windows itself
verifies the installer.

**Other shell items.** `_persist_key` can re-enter itself through `<FocusOut>`
when the consent dialog steals focus on machines without a secure backend
(`gui.py:453, 1145`); the frozen build never verifies that the keyring backend
resolved to `WinVaultKeyring` (the spec swallows a `copy_metadata` failure at
`:53-59`, and `--selfcheck` only imports modules); the update dialog can land on
top of the cost-confirm or file dialogs (`gui.py:2598-2611`); "Embed API key"
falls back to `load_api_key_from_file()` after the user cleared the field
(`gui.py:2287, 2362`); uninstall leaves `%LOCALAPPDATA%\DrawingAnalyzer` (key
file, logs, installers) behind and there is no "forget saved key" action;
`check_licenses.py` fails only on *missing* metadata and never evaluates
compatibility; README:74 ("talks only to the Anthropic API") is contradicted by
the daily GitHub manifest fetch.

**CI/release gating is otherwise sound:** `publish` genuinely needs
`build`+`gates`+`gates-windows` with `--verify-tag`; the write token exists only
in `publish`; build/gates use `persist-credentials: false`; actions are
SHA-pinned (Dependabot for actions is still the open "NOTE TO MAINTAINER");
`run_acceptance.py` deselects `network` in every child. A positive result worth
recording: the full oracle gauntlet (`qc_markups=True, reference_audit=True`)
run through a recording client produced 34 requests that validate recursively
against the SDK 1.5 request TypedDicts with no unknown keys.

---

## 3. Claude API usage — assessment

### 3.1 What is right (verified against the current API and SDK 1.5.0)

Driving the app's real request builders through the real SDK over a mock
transport accepted every production shape byte-for-byte: Opus 5 streamed via
`client.beta.messages` with `fallbacks: "default"` and the
`server-side-fallback-2026-07-01` beta; `thinking: {"type": "adaptive"}` and
`output_config.effort` everywhere (never `budget_tokens`, never `disabled`, no
prefill, no sampling params); Sonnet 5 on the plain namespace; batch item params
with thinking/effort/string system/file-id images; `client.files.upload/delete`
(GA namespace); `batches.retrieve/cancel/results`; strict tools with
`additionalProperties:false` + `required` and none of the rejected keywords;
every `tool_use` id answered once in one user message with `is_error` refusals;
the assistant turn committed with thinking blocks intact; only
`tool_choice: none` ever sent (safe on Fable 5.1 too); `task_budget` inside
`output_config` at ≥20,000 on the beta streaming namespace with `remaining`
unset; `pause_turn` resumed by appending the full assistant content, capped;
streaming for every ≥21k cap; truncation retried at a raised cap and never
cached; four investigation breakpoints ordered longest-TTL first.

### 3.2 Where it is wrong

- The citation text-block join (C1) — an API-shape misunderstanding.
- The batch refusal hole (R2) and unread `stop_details`.
- Fallback provenance: nothing reads `response.model` or `usage.iterations`, so
  a digest served by Opus 4.8 after a fallback is cached under the
  `model=claude-opus-5` key (`digest.py:1709-1720`) and the manifest attributes
  it to Opus 5; a mid-stream refusal's billed partial output is never counted.
  Same price today, wrong provenance forever.
- `_message_text` joins text blocks with `"\n"` (`digest.py:753-761`); a
  mid-stream fallback response `[text(partial), fallback, text(continuation)]`
  gets a newline mid-sentence, and if the boundary falls inside the findings JSON
  the block becomes MALFORMED.
- Over-broad self-healing markers: `investigate.py:217` includes the generic
  `"output_config"` in `_TASK_BUDGET_REJECTION_MARKERS`, so an unrelated
  `output_config.effort` 400 latches task budgets off for the process (changing
  every later cache key) and then re-raises the same 400. Match on `task_budget`.
- The Files-API-404 inline fallback (`batch_digest.py:1656-1702`) inlines the
  ~37 base64 images that `file_upload.py:1-12` documents as exceeding the 32 MB
  request limit, so on a Files API outage dense sheets fail with HTTP 400
  unrecovered.
- Uploaded-file hygiene: cleanup is best-effort on a daemon thread
  (`batch_digest.py:271-304`); a GUI close or crash after collect leaks a run's
  ~1 GB of PNGs against the org's file-storage quota; `client.files.list()` is
  never called; a storage-limit rejection is neither run-fatal
  (`RUN_FATAL_UPLOAD_STATUSES = {401,403,404}`, `file_upload.py:90`) nor
  inline-eligible.

### 3.3 Cost levers (ranked by dollars on the exhaustive stack)

1. **Share the ~90k-token image prefix between the digest and both critique
   reads (real-time path).** The digest and critique reuse the identical user
   turn (`build_user_content_blocks`) but different `system` prompts, and the
   cache is a prefix over tools → system → messages, so today the prefix is
   billed 1.0 (digest) + 1.25 (critique read 1 write) + 0.1 (read 2) = **2.35×**.
   The pipeline also digests every sheet before critiquing any, so even with a
   shared prompt the 5-minute entry would be gone. With one shared system prompt,
   the stage task in the final user block (which the builder already isolates,
   `digest.py:641`), and the three reads pipelined per sheet, it becomes
   1.25 + 0.1 + 0.1 = **1.45×** — ~38% of vision input on FAST runs, roughly
   $0.40 per sheet at Opus 5 rates. Cost is one prompt-hash re-key.
2. **Critique read 2 may miss the cache whenever read 1 exceeds five minutes.**
   `critique.py:447-520` uses a plain 5-minute breakpoint; the TTL runs from the
   start of the writing request; `cost.py:491` itself says a read takes "roughly
   4–6 minutes per sheet". A miss re-writes at 1.25× — the estimator's `no_reuse`
   band, $1.21 vs $0.69 per sheet. The ledger already carries the signature
   (critique record with `cache_read_tokens == 0`); surface the hit rate in
   run.log and decide 5 m vs 1 h from data (1 h only pays if misses exceed ~65%).
3. **The batch path never uses prompt caching** (`cache_specs=False`,
   `batch_digest.py:1885-1894`) on the assertion that parallel items "have
   nothing to read yet". The Batches docs describe caching across batch items as
   best-effort with high typical hit rates. For a 40k-token specs block × 40
   sheets: uncached 1.6M tokens; with `ttl:"1h"` at a 70% hit rate ≈ 1.07M
   token-equivalents (~33% less); worst case (0% hits) costs +100% on that block
   only. Enable behind a flag and assert on `cache_read_input_tokens` in the
   collected results.
4. **Overlap is 22% duplicated pixels.** 0.08 per side makes tile area 1.284×
   the page (~20k of 90k tokens per sheet, on three reads). 0.05 → 1.21× saves
   ~9% of image tokens at a narrower straddle margin (5.8 mm vs 9.6 mm on an
   ARCH E cell). Worth an eval, not a blind change.
5. **Density-adaptive tile resolution.** Tokens scale with pixel area; a
   low-ink tile rendered at half the long edge costs a quarter. The
   `RenderTelemetry` byte spread exists precisely to pick such a threshold.
6. **The overview is rendered at the full tile target** (`render.py:837-839`)
   — a full tile's tokens for an image whose stated purpose ("global layout and
   match-lines") needs ~1000 px.
7. **The investigation's forced close changes `tool_choice`**
   (`investigate.py:980-981`), which invalidates the messages-tier cache on the
   largest turn (initial 300-DPI crop + up to six evidence images) — written at
   the 1-hour 2× rate instead of read at 0.1×, roughly $0.15–0.25 per
   investigation on Opus 5. `_BUDGET_EXHAUSTED_TEXT` already instructs the close
   and past-budget blocks are refused at zero cost, so `tool_choice` can stay
   unchanged.
8. **1-hour TTL on citation/investigation breakpoints** where calls are seconds
   apart buys nothing over 5 minutes (2× vs 1.25× write). Small dollars, but it
   is also what made C3 cost real money to get wrong; the citation breakpoints
   (~330 + ~700 tokens) may also sit below Sonnet 5's 1,024-token minimum, in
   which case the ledger prices writes that never happen.
9. **Verification could ride the Batches API** on large non-interactive runs:
   the single-crop calls are independent, the verdict cache key is
   transport-neutral, and Sonnet needs no fallback beta — half the stage cost.
10. **Web-tool variants.** A live fetch of the web-fetch doc during this review
    listed a newer `web_fetch_20260318` variant adding `response_inclusion:
    "excluded"` (drops echoed fetched-page blocks — direct output-token savings
    on the citation stage). Verify before changing the pinned type.

### 3.4 Unsettled: web fetch on Opus 5

`api_config.py:420-425` and `citation_check.py:134-144` state web fetch is not
available on Opus 5. The bundled API reference lists `web_fetch_20260209` on
Opus 5; a live fetch of the web-fetch doc during this review showed Opus 5 absent
from the dynamic-filtering model list. The code's conservative gate is the safe
default (sending an unsupported tool is a 400 that kills the request). Settle it
with one `network`-marked canary call, or read `client.models.retrieve(id)`
capabilities at startup instead of a hand-maintained registry.

---

## 4. Plausible issues (traced, not fully proven)

- **Cross-QC output cap (16k, `api_config.py:162`) is shared with adaptive thinking
  and has no truncation recovery** (`cross_qc.py:1018-1054`): a truncated array
  fails `_tolerant_json_object` → every finding of that call lost, stage PARTIAL,
  never cached. The call uses non-streaming `create`, so raising the cap above
  ~21,333 is a client-side `ValueError` before any HTTP call — the streaming rule
  in CLAUDE.md lists every stage but this one.
- **`_TEXT_LAYER_BUDGET = 4_000` chars per sheet** (`cross_qc.py:112`) makes every
  dense set's cross-QC `degraded` → `complete=False` → PARTIAL and un-cacheable
  (`:1450-1453, 1578, 1679-1683`), and blinds the conflict hunt to schedules past
  4k characters. 40 sheets × 15k chars ≈ 150k tokens fits the window.
- **Cross-shard recall collapses above 40 sheets**: `DEFAULT_MAP_MAX_FACTS = 40`
  per shard (`:107`); a 41-sheet set shards [40, 1] (`:1294-1307`) and a conflict
  across shards is found only if both shards independently chose the same entity
  among their 40 facts. The ≤40-sheet whole-set path (`_validate_cross_item`
  `:588-662`) does no quote grounding and sets no `evidence_state`.
- **`_prune_stale_work_dirs` can reap another live run's work dir**
  (`pipeline.py:177-234`): `keep` covers only this run; a run whose dir was
  created early (tile artifacts) and then waits >24 h on batches has nothing newer
  than the cutoff inside it. A heartbeat or PID lock file fixes it.
- **Regex-harvested editions are presented as ADOPTED codes** to the planner and
  cross-QC (`set_identity.py:439-464`; `NFPA 13 2013 §8.15.1` harvests as
  adopted), while the edition audit deliberately ignores regex-origin entries
  (`citation_check.py:443-449`) — two consumers see different truths.
- **`_CODE_TOKEN` (`citation_check.py:249`) misses** `ASHRAE 90.1-2019`,
  `IECC 2021`, `NEC 2020`, `TITLE 24 2022`, `ASCE 7-16`, `2022 CALIFORNIA
  BUILDING CODE`; `sheet_ids._STANDARD_BODIES` already lists several of them.
- **Prose-harvest match threshold (Jaccard ≥ 0.7, `prose_harvest.py:89,
  377-388`)** makes most prose items stragglers → a duplicate ledger entry plus
  one Sonnet call each (3–8 per sheet).
- **Investigation `max_tokens` stop ends with no raised-cap retry**
  (`investigate.py:1105-1107`) inside a 16k envelope shared with thinking.
- **Mid-output refusal-fallback turns are echoed verbatim**
  (`investigate.py:1019, 1030`); the docs say blocks before the `fallback` block
  must be omitted on replay.
- **`_norm_id` in investigate (`:494-495`)** folds only case/whitespace, not
  `normalize_sheet_id`, so a Unicode-dash sheet id fails `crop_region` with
  "unknown sheet_id".
- **Quadratic regex in `redact_secrets`** (`diagnostics.py:110-114`): 4k chars
  373 ms, 8k 1.4 s, 16k 5.5 s; `run_journal.sanitize_text` runs it on the
  untruncated value.
- **Path-scrub gaps** (`run_journal.py:98-102, 153-183`): an unquoted
  doubled-backslash Windows path passes verbatim; `\\?\` long paths outside a
  registered root scrub partially; no left boundary on private roots (`/tmp`
  rewrites `/var/tmp/x.pdf`).
- **`roll_up_qc_status` truth-table holes** (`models.py:2269-2282`): empty
  `stage_results` → COMPLETE; only `expected=False` stages all FAILED →
  COMPLETE; the pipeline avoids these today by construction.
- **`resolve_run_configuration` disagrees with the pipeline**
  (`models.py:2144-2159, 2184-2187, 2212` vs `pipeline.py:1987-1989`), and
  `critique_reads=2` is hardcoded while `critique_runs()` honours
  `DRAWING_ANALYZER_CRITIQUE_RUNS`.
- **`Finding.from_dict`** turns `"refs": "NFPA 13"` into per-character refs
  (`models.py:1326-1332`) — the same bug CLAUDE.md records for
  `set_identity._as_list`; share the coercion.
- **Report assistant context is unbounded**: the whole report text goes into the
  system prompt on every question (`html_report.py` 3313). A 400-sheet combined
  digest (~0.5–1.2M tokens) exceeds even the 1M window, so the first question
  400s; when it fits, every question re-reads the whole report and the 1-hour
  cache write is 2× of it (~$5 for 500k tokens on Opus 5).
- **Report search rescans the whole set per keystroke** (`apply()` 2304-2317
  lowercases every block's `textContent` including the 15k-char raw text
  `<pre>`s): ~6 MB per keystroke on 400 sheets.
- **Reader API key in `sessionStorage` on a `file://` document**: Chromium
  shares one file:// origin across local files, so any other local HTML opened in
  that tab can read it (the footer warns).

---

## 5. Test-infrastructure fidelity gaps

The hermetic suite is large and well-targeted, but the fakes accept shapes the
real SDK rejects, so a class of API misuse cannot be caught in CI:

- `client.messages.stream(fallbacks=…)` / `.stream(betas=…)` on the non-beta
  namespace raise `TypeError` in SDK 1.5.0; every fake `create(**kwargs)` and
  `_BetaMessagesProxy` (`fake_anthropic.py:452-471`, which silently pops
  `betas`) accept them; `_FakeBatches.create(*, requests, betas=None)`
  (`test_drawing_batch.py:144-149`) accepts a `betas` the real non-beta
  `batches.create` rejects.
- The ≥21,334-token non-streaming guard is never modelled: real
  `messages.create(max_tokens=64000)` raises before any HTTP call; a stage that
  regresses from `stream_message` to `create` is green in CI.
- `batch_errored_result` (`fake_anthropic.py:337-347`) puts `type` directly on
  `error`; the real object is `result.error.error.type`.
- `_StallThenSettleWithCompletedItems.results()` omits envelopes for unfinished
  items (`test_drawing_batch.py:2585-2594`); the API returns `canceled`
  envelopes — this is what hides R3.
- No fixture carries `usage.iterations`, `fallback_credit`, `stop_details`, or a
  `fallback` content block, so refusal-fallback billing/provenance/text-join paths
  have no hermetic coverage.
- No live canary touches the batch transport.
- `tests/test_spec_documents.py` depends on pypdf importing `cryptography`;
  on a box with a broken system `cryptography` the panic is a `BaseException`
  and escapes the module's `except Exception` capture (environment-only today).
- `FakeUsage` (`fake_anthropic.py:50-57`) defaults the cache-token fields to `0`
  where the real SDK returns `None` when absent, and its `FakeServerToolUse`
  carries only `web_search_requests` (the real `ServerToolUsage` also has
  `web_fetch_requests`), so the suite cannot prove fetch requests are counted or
  that every reader is `None`-tolerant.
- `FinalMessageStream` (`fake_anthropic.py:392-405`) returns a complete message
  only; the "truncated read → retry at the raised cap" logic is never exercised
  with a stream that dies after partial output.
- No socket guard: `conftest.py:73-88` deletes the key so `get_client()` raises,
  but a zero-arg `Anthropic()` would still resolve `ANTHROPIC_AUTH_TOKEN` or an
  `ant auth login` profile. An autouse monkeypatch (or pytest-socket) for
  non-`network` tests closes it.
- CI runs ruff on correctness classes only (E9, F63, F7, F82). A broad pass
  found no hidden logic bug, but adding `F` and `B` (F401/F811/F841/B023/B905)
  would catch the dead `sug = _suggestion(...)` at `references.py:550` (the
  MALFORMED branch re-derives the suggestion inline with different wording),
  nine unused `src` imports, and three blind `pytest.raises(Exception)`.

---

## 6. Material improvement proposals (ranked)

1. **Symmetric complete-link in Pass B + unique finding identity** (B1, B8, B9).
   The ledger is "the exclusive findings container"; today it can destroy a
   conflicting measurement and number findings by arrival order.
2. **Anchor robustness** (B4): punctuation-insensitive tokens plus a
   character-stream tier turn a class of false `[QUOTE NOT FOUND]` flags into
   verified, clouded findings at zero API cost — the highest-leverage change in
   the disposition path.
3. **Digest-phase fault isolation** (R1): per-source open failures become
   per-page errors and a PARTIAL digest stage; the journal and manifest always
   ship.
4. **Shared vision prefix + per-sheet pipelining** (§3.3 #1): ~38% of vision
   input on real-time exhaustive runs.
5. **Cross-QC on full text layers with pairwise sheet groups**: raise the 4k text
   budget to the 15k cap and budget by tokens; above one call, shard into groups
   whose every pair is co-present in one call (the pattern `_reconcile_facts`
   already uses for facts) instead of the 40-fact reconcile bottleneck. Add the
   three-state grounding to the ≤40-sheet path.
6. **Structured outputs for the pure-JSON stages** (identity, planner; cross-QC
   via a `record_findings` strict tool once the live canary passes). Every one
   of these has a "no parseable block" failure path that schema decoding removes;
   the critique stays opt-in as designed; the citation check cannot (citations).
7. **Ensemble diversity for the second critique read.** A same-model resample at
   the same prompt and effort mostly certifies sampling stability; running read 2
   on Sonnet 5 at `xhigh` (comparable cost to a cached Opus read) would make
   `reproduced` mean independent agreement. Measure with the existing A/B harness
   before switching. `DRAWING_ANALYZER_CRITIQUE_RUNS=1` is already a knob worth an
   eval too, since digest-vs-critique cross-family merges already raise
   `reproduced`.
8. **Host-side pre-search before the first investigation turn**: run
   `find_text_matches` on the quote's distinctive tokens and include the rects
   and line context in the initial user turn; saves a round trip per
   investigation and makes the free tool actually free (C4). Also give the
   verifier the words inside the crop as a text block (~50 tokens) so Sonnet
   reads `1/2"` vs `1/8"` from vector text instead of pixels.
9. **Calibrate the estimator from the ledgers the app already writes** ($1, $2):
   p50/p90 `output_tokens` per digest/critique read and text-side input from
   exported `run_manifest.json` files; add `text_chars`; quote output as a band.
   Optionally one free `messages.count_tokens` call on the first rendered sheet
   (the helper at `core/tokenizer.py:259-299` exists and has no caller).
10. **Bound the report assistant's context**: synthesis + sheet index +
    findings as the system block, plus `get_sheet_digest` / `search_report`
    client tools that read the digest text already in the DOM; per-question cost
    becomes O(question) and 400-sheet sets become usable.
11. **Auditor precision**: lexical cue for spec sections (A1), interleaving in the
    naming key (A2), memoized/lazy reference classification (A3), wider trigger
    vocabulary (A4), label-adjacent sheet-id detection (A5), per-auditor caps and a
    partial-set summary mode (A7).
12. **Ledger provenance**: store `response.model` and per-iteration usage on
    every real-time record; derive `cache_write_ttl` inside `_record_usage`.
13. **PDF-native markup structure**: tie each finding's cloud/tag/leader/callout
    with `/IRT` + `/RT /Group` (Bluebeam and Acrobat then show one Markups-List
    row per finding), set `/NM` to the QC id so third-party tools can join
    annotations to `findings.csv`, and add named destinations so the HTML deep
    link can use `#nameddest=QC-014`.
14. **Files API hygiene**: a start-of-run orphan sweep keyed on the app's
    filename pattern and age; treat a storage-limit rejection as inline-eligible
    or run-fatal with a hint.
15. **Cancellation and resumability** (G1): a cancel event through the pipeline,
    `batches.cancel` on quit, persisted batch ids harvested on relaunch, and quit
    wording that is honest per transport.
16. **Key handling** (G2, G3): snapshot the key into an explicit client at
    Analyze time instead of the process environment; disable the entry while
    busy; `utf-8-sig` plus loose shape validation on load and save; a "forget
    saved key" action.
17. **Update channel** (§2.8): sign the manifest, pin hosts, cap the download,
    reject non-https redirects, re-verify before launch, Authenticode.
18. **Packaging and CI**: explicit `datas` instead of `collect_all`; pin
    `pyinstaller-hooks-contrib`; extend the lock to `[gui]` and run `test`/`gates`
    under it; `ArchitecturesInstallIn64BitMode=x64compatible` and an
    `[InstallDelete]` for `{app}\_internal` in `installer.iss`; make `--selfcheck`
    assert the keyring backend; drop `tiktoken` (which also removes `requests`
    and `regex` from the bundle); Dependabot for action SHAs; an allowlist in
    `check_licenses.py`.

Considered and rejected: sending vector sheets as PDF `document` blocks (the API
rasterizes a page to ≤1568 px, ~49 DPI on an E-size sheet — the tile design is
right); caching the digest system prompt across sheets without specs (~926
tokens, ≈$0.004 per sheet); `web_search` inside the investigation (verdicts must
rest on drawing evidence only).

---

## 7. Hygiene: dead code inherited from the Spec Critic lineage

No callers anywhere in `src/`, `tests/` or `scripts/`: `batch_service_tier`,
`token_count_preflight_enabled` ("Always True" — but `count_tokens_via_api` is
never called), `web_search_max_uses_for_severity` (with a `GRIPES` severity that
does not exist here), `cross_check_max_tokens`, `verification_max_tokens`,
`cache_diagnostics_params` / `extract_cache_diagnostics`, `PHASE_CROSS_CHECK`
(documented as orphaned), `verify._verify_cross_one`, `cross_qc._sheet_is_textless`,
`annotate._expand_for_markup`. `tiktoken` is a hard dependency
(`pyproject.toml:15`) with zero callers — dead weight in the frozen Windows
build. The module docstring of `core/api_config.py` still says "for Spec Critic".
None of these are bugs; they invite misuse and mislead a reader tuning behaviour
that does not exist.

---

## 8. What was checked and found sound

Request shapes and namespaces (above); every ≥21k path streams; truncation
retry doubles → clamps → accumulates usage → never caches a truncated read;
cache keys cover model, prompt hash (including `SHARED_USER_FRAMING_STRINGS`),
max_tokens, effort, thinking, focus, specs, capped text and PNG bytes; the
findings-block parser (line-anchored fences, matched closers, dangling fences,
last-block-wins, string-aware trailing-comma repair); batch poll/stall/harvest/
resubmit bounds; Files API upload retry taxonomy; pricing multipliers against
current published rates; the image-token formula and hi-res/standard tiers; the
tile grid partitions the page exactly and every tile sits under the 2000 px
many-image cap and the hi-res limits (nothing is downscaled server-side);
blank-tile suppression is strict pixel-uniform; text extraction without
annotations and the PAGE_VIEW_V2 conversion; `_page_dependency_sha256`
coverage and the N23 opaque-page rule; annotate coordinate spaces verified in
all 16 rotation × CropBox × MediaBox-origin cases including GOTO destinations
via both `insert_link` and `set_toc`; OCG layer order; placement stamps and
receipt reconciliation; export atomic publish, `long_path`, casefold dedupe,
sorted manifest hashing; HTML report escaping at every interpolation site (no
XSS found), CSP, transcript scrubbing; run-journal sanitization and the
AST-enforced coverage; `RunUsage` derived totals and `is_billable_but_unpriced`;
`roll_up_qc_status` for every path the pipeline actually takes; provenance
restorer at every verify exit; investigation budget enforced before execution;
warm-hit replay with sha-compare; the citation TTL carve-out to I-7; the
edition regexes on `NFPA 13-2022 §9.2`, `2021 IBC`, `NFPA 13 (2025 edition)`,
`IFC 2021 Section 903`, `NFPA 13D`; the numeric veto; PyMuPDF never crossing
threads in the pipeline; GUI callbacks marshalled through `after()`.

Scratch reproductions (outside the repo, under the session scratchpad):
`repro_batch.py` (R2, R3), `repro_vanish.py` (R1), `sdk_smoke.py` (real-SDK
request-shape smoke), `passb_probe.py` / `ledger_probe.py` (B1, B8, B9),
`auditor_probe.py` (B7, A1, A2, A4–A6), `anchor_probe.py` (B4),
`citation_probe.py` (C1), `edition_probe.py` (C2), `exp1–4.py` (B2, B3, B5, B6,
B10, B11, K1, K2, K4), `cost_example.py` ($1, $2, worked example),
`geom_check.py` / `geom_check2.py` (annotate spaces), `perf_probe.py` (A3),
`preflight_perf.py` ($3), `journal_edge.py` (path scrubbing),
`repro_bom_key.py` (G3), `shape_harness.py` / `tdcheck.py` (the 34-request
TypedDict validation).
