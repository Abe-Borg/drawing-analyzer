# Prompt optimization follow-up

The owner authorized this work after reviewing the attached **LLM Prompt
Optimization Review** and the code-based assessment in the Codex chat. This is a
separate queue from the remediation slices: the owner asked for one manageable
chunk per PR, then a pause for review and merge. Do not start the next chunk
before the preceding PR merges and the owner asks to continue.

## Queue

| Chunk | Scope | Status / gate |
|---|---|---|
| PO-01 | Shared escaped source blocks; apply to identity and review planning; stage-specific cache invalidation and offline regressions | [PR #192](https://github.com/Abe-Borg/drawing-analyzer/pull/192) merged |
| PO-02 | Extend source framing to synthesis and focus, preserving bounded corpora and exact retained prose | [PR #193](https://github.com/Abe-Borg/drawing-analyzer/pull/193) merged |
| PO-03 | Extend framing to cross-sheet QC and investigation tool results; cover request framing and investigation's manual prompt version in cache identity | Implemented and validated; opening one PR for owner review |
| PO-04 | Carry API cache-read/write usage through cross-QC and both verification paths into accurately priced usage records | After preceding chunks merge |
| PO-05 | Measure prefix token counts, current model cache minimums and reuse; enable eligible caching through the existing policy helper | Requires approved drawings and an intended live measurement budget before billable work |
| PO-06 | Evaluate digest and critique effort separately against human-labeled findings; record precision/recall, important-defect retention, cost and latency | Requires approved dataset and budget; keep current defaults until an evidence-backed decision |

Check the repository's open PRs and latest main before each chunk. Caching
benefits are conditional: the verifier's system prompt is 833 characters, and
the cross-QC prefixes are also modest. Never pad a prompt merely to reach the
provider's cache minimum. Reuse existing benchmark/A/B tools and pricing policy.

## PO-01 contract

- One helper wraps source text in host-selected tags and XML-escapes `&`, `<`
  and `>`; quotes stay literal. Decode entities once to recover source spelling,
  including text that originally contains an entity such as `&lt;`.
- Identity wraps digests, raw text slices, edition windows, sheet labels and
  failed-read diagnostics. Planning wraps digest heads, sheet labels and the
  model-derived identity. Explicit host task instructions stay outside.
- Slice source content before wrapping it. Existing corpus caps account for
  the full rendered blocks; only complete blocks are retained or omitted.
  Escape/wrapper overhead can trigger earlier fallback or omission near a cap,
  and the existing loss counters record it. No content cap is increased.
- Only the model-visible copies change. Retained evidence, parsed response
  schemas, output prose, model/effort settings and quote-validation rules stay
  unchanged. Delimiters supplement host validation; they do not guarantee a
  live model will ignore hostile instructions.
- The shared system rule is included in both existing prompt hashes. Both
  stage keys already hash the exact assembled user corpus, covering wrapper
  and escaping changes. No global schema or unrelated stage key is changed.
- Offline checks verify structure and literal source recovery, clipping and
  whole-block budgeting, old-contract cache misses and new-contract replay.
  No live API calls were authorized for this chunk.

## PO-01 handoff

- Base: `3f702d1` (main after SDK 1.8.0 support merged).
- Open cross-QC PR #191 was inspected; its files and binding contracts are
  outside this chunk. The owner-selected prompt work takes precedence over
  `_plans/README.md`'s default remediation queue order; no remediation slice is
  marked completed by this work.
- Fourteen new regressions failed before the implementation. Two existing
  framing checks are updated: the planner's bare identity prefix becomes a
  tagged prefix, and the clean identity corpus compares decoded source blocks
  instead of its old unwrapped layout. Result/schema assertions remain intact.
- Prompt hashes: identity `0659a7cd5e585485` → `30cccf5dd7e52cb3`; review plan
  `c14096d79af181a3` → `20d583285e09dddb`. Entries under old contracts remain on
  disk, but the next eligible run recomputes these two set-level stages. A new
  plan can change downstream critique profile keys through the existing plan
  machinery; stored digest and critique contracts are not bumped here.
- Validation (Python 3.12, Anthropic SDK 1.7.0, supported by the current
  `>=1.7,<1.9` dependency range):
  - Fourteen new regressions failed before the fix; 107 focused tests passed
    afterward. Expanded stage/SDK/pipeline/cache checks: **333 passed**.
  - Full baseline, in an independent checkout of `3f702d1`:
    **5,804 passed, 105 skipped, 10 deselected**.
  - Full final suite: **5,818 passed, 105 skipped, 10 deselected**.
    JUnit comparison: 14 added tests, all passed; no removed tests and **zero
    changed existing outcomes**. The same 105 report/browser tests skip because
    the Chromium executable is unavailable; report HTML/JS is outside PO-01.
  - `compileall`, correctness-class ruff (0.14.5), `git diff --check` and the
    secret scan (235 tracked files, including the new files): clean.
  - The default executor sandbox prevents socket creation, including loopback,
    so the first full-suite attempts were interrupted after reproducing this
    on unchanged main. Final baseline and final runs allow the local sockets
    the suite needs; its own hermetic guard stays enabled and all 52 guard
    tests pass. All pytest commands explicitly deselect `network`.
  - No live model calls or paid experiments. These checks verify request
    structure and host behavior, not model quality or injection resistance.
- PO-01 merged as `358dafe`; the owner requested the next chunk. PO-02 starts
  from the newer main below. Live cache and effort experiments remain gated on
  representative drawings and a budget.

## PO-02 contract

- Reuse `source_content_block` and the unchanged `SOURCE_CONTENT_RULE` for
  complete digests and sheet labels in synthesis and focus. Escape only their
  model-visible copies. Preserve existing `.strip()` at the request/reply
  boundaries; retained digests and output prose are not rewritten or decoded.
- Escape `<operator_focus>` text separately. Its explicit system instruction
  preserves the operator's question as the task, distinct from source data.
  Task instructions and loss disclosures stay outside source blocks.
- Keep existing budgets and whole-sheet selection. Count complete rendered
  source blocks, including escaping, wrappers and the three separator characters
  per sheet. At overflow, drop the entire contiguous tail and count its rendered
  characters; preserve the existing omission disclosure and first-sheet
  exception (the first sheet remains whole even if it alone exceeds the cap).
- Each existing stage key hashes its entire system and assembled user prompt.
  These changes invalidate only synthesis/focus request contracts, without
  adding a key term or bumping the stage/global cache schema. A newly generated
  report can change downstream prose-harvest input keys through existing
  machinery; stored digest, critique, identity and planner contracts stay put.
- Offline checks cover literal source recovery, hostile closing tags in
  labels/digests/focus, escaping/wrapper budget overhead, complete blocks,
  contiguous-tail loss counts, the oversized first sheet, both request-key
  inputs and exact retained response replay. No live model calls or paid
  experiments; this does not measure model quality or injection resistance.

## PO-02 handoff

- [PR #193](https://github.com/Abe-Borg/drawing-analyzer/pull/193) merged as
  `c791e44`; the owner requested the next chunk, PO-03.
- Base: `aa0bfe1` (main with PO-01 PR #192 and cross-QC remediation PR #191
  merged). Open-PR check found only dependency PR #190; no overlapping work.
- Seventeen new regressions: **15 failed, 2 passed** before implementation.
  The passing cases already confirmed the assembled corpus participates in
  the cache key; the failures reproduce missing source boundaries, unsafe
  literal focus framing, uncounted wrapper/escape overhead and unchanged
  system contracts. No existing test expectations are rebaselined.
- System hashes: synthesis `96fa274271e0d6a1` → `423c896b3e102583`; focus
  `c63fb4f0dcd9a208` → `2f243b214b327325`. Old entries remain on disk and miss
  on the next eligible synthesis/focus request. The shared helper/rule itself
  is unchanged, so PO-01's identity/planner prompt hashes stay unchanged.
- Focused boundaries/stage/terminal-outcome tests: **151 passed**.
- Expanded SDK/cache/stream/pipeline checks: **402 passed**.
- Validation environment: Python 3.12.14, Anthropic SDK 1.7.0 (supported by the
  current `>=1.7,<1.9` dependency range).
- Full baseline in an independent checkout of `aa0bfe1`: **5,920 passed,
  105 skipped, 10 deselected**. Full final: **5,937 passed, 105 skipped,
  10 deselected**. JUnit comparison: 17 added tests, all passed; no removed
  tests and **zero changed existing outcomes**. The same 105 report/browser
  tests skip because Chromium is unavailable; report HTML/JS is outside PO-02.
- `compileall`, correctness-class ruff, diff checks and the secret scan
  (237 tracked files, including the new tests): clean. All pytest commands
  explicitly deselect `network`; the hermetic guard remains enabled. Full
  suites allow the local sockets required by the guard's own tests, as in
  PO-01. No live model calls or paid experiments.
- PO-03 proceeds from `c791e44` under the owner's follow-up below, retaining
  PR #191's merged cross-QC binding and framing-key contracts.

## PO-03 contract

- Reuse the existing source rule/renderer on whole-set, map and reconcile
  cross-QC requests: digest, original text slice, handle/label metadata,
  detected identity, manifest entries and model-derived fact lines. Extend only
  the helper's allowed tag names; its escaping behavior and shared rule stay
  unchanged. Quote checks continue against original, uncapped host evidence.
- Preserve opaque handles, source ordering, duplicate-label refusal and all
  grounding/claim/parse policies from PR #191. The original text-layer cap and
  counters stay at 4,000 source characters per sheet; slice before wrapping.
  XML escaping adds bounded wire overhead (up to five characters per source
  character, plus tags), not additional source coverage or a new total request
  cap. Host truncation notices and task instructions stay outside source data.
  Fact, finding, pair-call and tool budgets are unchanged.
- Cross-QC's existing request hash retains K2's named host framing and adds
  source-block signatures rendered by the same helper, covering delimiter and
  XML-special-character encoding changes alongside the system prompts. Keep
  host binding/grounding contract 9 and the global schema unchanged.
- Investigation wraps initial finding/prior-review text and the sheet index.
  Frame tool text only at the send boundary, including search JSON, image
  labels and errors that echo source/model text. Preserve raw executor outputs,
  images, saved traces, SHA replay, error flags and budget/forced-close messages.
  Bump only its existing manual prompt version, `investigate-v3` → `v4`.
- Retained prose/evidence, model/effort settings, tool schemas, response parsing
  and other stages' prompt contracts stay unchanged. No live model calls or
  paid experiments; offline structure/host checks do not establish model
  quality or injection resistance.

## PO-03 handoff

- Base: `c791e44`, main after PO-02 PR #193 merged. Open-PR check found only
  dependency PR #190. Read PR #191's D-8 binding decision and K2 framing-key
  contracts before implementation; no remediation slice is marked complete.
- Nineteen new regressions fail against baseline code and pass after the fix.
  They cover all request paths, literal/hostile source recovery, original
  slicing/loss counters, wrapper-key sensitivity, original-quote grounding,
  model-visible tool text/errors/images, forced close and exact evidence replay.
- Six existing test files adapt to the intended framing/version changes:
  the reconcile-layout and identity-preamble checks compare decoded blocks;
  the raster pipeline's fake client reads the decoded text layer to distinguish
  scanned sheets, keeping all grounding/anchor/verification assertions intact;
  the investigation's manual-version pin moves to v4; the acceptance test
  checks the decoded identity preamble; the response-join structural guard
  exempts only the outgoing tool formatter, retaining coverage of investigation
  reply readers. Test IDs stay unchanged.
- System hashes, whole/map/reconcile: `cb02462b66d993c7` / `6bebddaf21bee920` /
  `6d90d100ce95347f` → `5004a634214d665a` / `551a72ef1446af1e` /
  `a90a63aed3d3e9b8`. Investigation system: `11b8cd450ce11bcb` →
  `693d1b3ee38efe0d`, with manual version v4. Cross-QC host contract 9 and
  global schema 10 are unchanged; digest/critique/identity/planner/synthesis/
  focus system hashes are unchanged. Older affected entries remain on disk.
- Focused cross-QC/investigation/identity checks: **373 passed**. Expanded
  SDK/stream/cache/pipeline checks: **592 passed**.
- The first full run exposed two additional test-side framing assumptions:
  the acceptance test's bare identity prefix and the structural response-join
  guard matching the outgoing tool formatter. The narrow updates above retain
  all pipeline/verdict assertions and response-reader coverage. Additional
  acceptance/response-join/new-regression checks: **136 passed**. The first full
  run had **5,954 passed, 2 failed, 105 skipped, 10 deselected**, with only those
  two checks failing. The fresh full suite passes after these adjustments.
- Full baseline in an independent checkout of `c791e44`: **5,937 passed,
  105 skipped, 10 deselected**. Final suite: **5,956 passed, 105 skipped,
  10 deselected**. JUnit comparison: 19 added tests pass, no removed tests and
  no changes to existing outcomes. Browser skips match baseline (Chromium is
  unavailable here). Validation used Python 3.12.14 and supported Anthropic
  SDK 1.7.0; no Chromium installation or unguarded model access.
- `compileall`, correctness-class ruff, diff checks and the secret scan
  (238 tracked files, including the new tests): clean. All pytest commands
  explicitly deselect `network`; the hermetic guard remains enabled.
- Next: pause for owner review and merge of PO-03. Start PO-04 (accurate API
  cache-token usage/pricing in cross-QC and both verification paths) only when
  asked. Live caching/effort experiments remain gated on drawings and budget.
