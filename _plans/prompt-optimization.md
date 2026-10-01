# Prompt optimization follow-up

The owner authorized this work after reviewing the attached **LLM Prompt
Optimization Review** and the code-based assessment in the Codex chat. This is a
separate queue from the remediation slices: the owner asked for one manageable
chunk per PR, then a pause for review and merge. Do not start the next chunk
before the preceding PR merges and the owner asks to continue.

## Queue

| Chunk | Scope | Status / gate |
|---|---|---|
| PO-01 | Shared escaped source blocks; apply to identity and review planning; stage-specific cache invalidation and offline regressions | [PR #192](https://github.com/Abe-Borg/drawing-analyzer/pull/192) open; awaiting owner review and merge |
| PO-02 | Extend source framing to synthesis and focus, preserving bounded corpora and exact retained prose | After PO-01 merges |
| PO-03 | Extend framing to cross-sheet QC and investigation tool results; cover request framing and investigation's manual prompt version in cache identity | After preceding chunks merge; first reconcile with remediation PR #191 and any newer cross-QC/investigation work |
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
- Next: review/merge PO-01, then start PO-02 when requested. Keep live cache and
  effort experiments gated on representative drawings and a budget.
