# Remediation program: start here

This folder holds a multi-session remediation program for Drawing Analyzer.
No single session will finish it. Every session does one slice of work, ships it
as one PR, and records its progress **in the same PR**, so the next session can
see from `main` alone what is done and where to continue.

| File | What it is | Who edits it |
|---|---|---|
| [`drawing-analyzer-remediation-plan.md`](drawing-analyzer-remediation-plan.md) | **The plan**: what to fix, why, required behavior, regression cases and acceptance criteria for work packages WP-01 … WP-25. Authoritative for *requirements*. | Rarely. Only to correct it (see step 7). |
| [`PROGRESS.md`](PROGRESS.md) | **The tracker**: every work package split into session-sized slices, in queue order, with status; the per-finding disposition register; owner-only actions; the handoff log. Authoritative for *status and order*. | Every session, in its PR. |
| [`DECISIONS.md`](DECISIONS.md) | The shared-contract decision record (plan §4.1) and the cache/schema migration register (plan WP-10 step 9). | The session that decides a contract or changes a cache/schema version. |
| [`DEEP_REVIEW_2026-09.md`](DEEP_REVIEW_2026-09.md) | The original September 2026 review the plan is built on: the concrete reproductions and suggested fixes behind IDs `B*`, `R*`, `C*`, `$*`, `K*`, `A*`, `H*`, `G*`. **Frozen reference.** Its line numbers are against 1.6.0 (`f5284ac`), so locate code by symbol. | Nobody. |

## Session protocol

Every coding session working on this program follows these steps. If the user's
request for the session conflicts with them, the user's request wins. Say so in
the handoff entry.

### 1. Orient (read before you touch code)

1. Read `CLAUDE.md` (auto-loaded), this file, and `PROGRESS.md` from top to
   bottom: the legend, the queue, owner actions, and at least the three newest
   handoff entries.
2. **Find the work already in flight.** List the repository's open pull
   requests (GitHub MCP `list_pull_requests`; there is no `gh` CLI). An open PR
   whose title starts with `Remediation` claims the slice IDs in its title. Do
   not start those slices. A slice whose PR was closed without merging goes back
   to `todo`; mention that in your handoff entry.
3. **Pick your slice.** If the user named one, do that. Otherwise take the first
   `todo` row in queue order whose `Depends on` slices are all `done`. A slice
   whose dependency is only in an open PR is not available: pick another, or
   tell the user the queue is waiting on that PR. Never pick a `blocked` row.
   You may take two or three adjacent **S**-sized slices in the same area if the
   combined PR stays reviewable (about 1,500 changed lines, excluding fixtures).
4. Read the slice's work package in the plan **in full** (not only the step the
   slice names), the review entries for its IDs in `DEEP_REVIEW_2026-09.md`, any
   `DECISIONS.md` contract the slice touches, and the parts of `CLAUDE.md` that
   document the code you will change.

### 2. Set up and record a baseline

```bash
pip install -e ".[dev,browsertest]"
pip install cffi   # see note below
python -m pytest -q   # compare the counts with the newest handoff entry
```

- **`cffi`:** in the cloud container, the system `cryptography` package is
  missing `_cffi_backend`. Without `cffi`, three tests in
  `tests/test_spec_documents.py` die with a `pyo3_runtime.PanicException`. This
  is an environment defect. Never "fix" it in product code; plan WP-02 step 8
  forbids broad `BaseException` catches.
- Chromium is pre-installed (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`).
  **Never run `playwright install`.** With the pinned Playwright the browser
  suite runs normally.
- A difference from the recorded baseline that your slice did not cause is
  a finding: record it in the handoff entry. Do not paper over it.

### 3. Re-verify before you change anything

The plan and the review were written against 1.7.0. `main` moves. For every
defect in your slice, first confirm it still exists: write the focused
regression test and watch it fail. If it is already fixed, do not redo it.
Record `n/a` with evidence (the commit, or the passing test) as plan §1
requires. If the plan's description is wrong, see step 7.

### 4. Implement

- Write the failing regression first, then the fix, then run the targeted test
  files (plan §6.4).
- The invariants in `CLAUDE.md` (I-1 … I-7, the streaming rule, the explicit
  thinking rule, PyMuPDF isolation) and the rules in plan §2 bind every change.
- Use one shared helper per concern. Do not add a parallel normalizer,
  dedup rule, completeness rule or terminal-state classifier (plan §4.2). If a
  `DECISIONS.md` contract covers what you are touching, conform to it. If the
  contract is still `open` and your slice is the one that has to decide it,
  decide it narrowly and record it there.
- **Cache and serialization:** if what is sent, stored or interpreted changes,
  the key must change: a content-hashed prompt version, a new key term, or a
  namespace/`_SCHEMA_VERSION` bump (I-6, WP-10). New serialized fields default
  safely in `from_dict`. Add a row to the migration register in `DECISIONS.md`.
- **Stay in scope.** If you find something outside your slice, add it to
  `PROGRESS.md` as a new row or a note on the owning slice. Do not widen the PR.

### 5. Validate before you push

```bash
python -m compileall -q src
python -m pytest -q
python -m pytest -q -m browser --junitxml=/tmp/browser-results.xml \
  && python scripts/check_browser_suite.py /tmp/browser-results.xml   # if report JS/HTML/chat behavior changed
pip install "ruff==0.14.5" && ruff check --select E9,F63,F7,F82 src tests scripts
python scripts/scan_secrets.py
```

- **No live API calls.** Tests marked `network` stay deselected unless the user
  explicitly authorized a live budget in the session request. Never put a real
  key anywhere.
- Re-read your own diff as a reviewer would before you push (see the system
  guidance on pushes).

### 6. Update the documents your change affects (same PR)

- `CHANGELOG.md`: an entry under `## [Unreleased]` naming the finding IDs.
- `CLAUDE.md`: when a behavior, contract or gotcha it documents changes.
  Remove or correct any text your change made false.
- `README.md`: when user-visible behavior changes. Do not shorten it.
- `requirements.txt` / `pyproject.toml`: when dependencies change. Touch
  `requirements-release.lock` only through its documented procedure.

### 7. Record progress (same PR — this is how the next session knows where to continue)

In `PROGRESS.md`:

1. Set your slice row's status: `done`, or `partial` with what remains, or
   `n/a` with evidence, or `blocked: <named external gate>`. Fill in the date.
   After the PR exists, push a one-line follow-up commit that adds its number.
2. Update the disposition register for every finding ID the slice touched
   (`implemented+validated`, `already satisfied`, `disproved`,
   `deferred (reason)`, `blocked (gate)`), with the test that proves it.
3. When the last slice of a work package lands, check that package's
   **Acceptance** paragraph in the plan. Mark the package `done` in the
   package table only if every criterion holds. Otherwise add the missing
   work as a new slice.
4. Add a handoff entry at the **top** of the log. It must contain: slices and
   finding IDs, what changed, contracts decided, cache/schema effects,
   validation actually run (with counts), what you could not verify, risks,
   and concrete next steps (plan §4.2 and §10).
5. Update the `Next up` line at the top of `PROGRESS.md`.

If you learn that the plan is wrong (a mechanism that does not exist, an
impossible acceptance criterion, a missing consumer), correct the plan text in
the same PR, say what you changed and why in the handoff entry, and never
weaken an acceptance criterion just so your implementation passes (plan §2.1).

**Running out of room?** Stop starting new work. Commit what is coherent and
tested, mark the slice `partial` with a precise list of what remains (files,
functions, failing test names), push, and open the PR. Uncommitted work is lost
when the container is reclaimed.

### 8. Open the PR

- Push to the branch the session was assigned.
- Title: `Remediation <slice IDs>: <one-line summary>`, for example
  `Remediation WP-04.1: quantity-aware measurement signatures (B2, B3, B12, N1)`.
- Body: the handoff entry, plus the exact validation commands and results.

## Things a coding session must never do

- Tag, publish or approve a release. Fill in a manual acceptance record, sign-off
  or waiver on the owner's behalf. Mark an owner action in `PROGRESS.md` as done.
- Spend live API money beyond a budget the user stated for that session.
- Mark a slice `done` without a regression test that failed before the fix and
  passes after it, or mark a package `done` while its acceptance criteria do not
  hold.
- Skip, disable or weaken a test to get green. Turn an unavailable gate
  (browser, Windows, live canary) into a pass. A skip is recorded as a skip.
- Delete user caches or historical exports as a "migration" (plan §2 rule 6,
  WP-10 step 9).
- Rewrite `DEEP_REVIEW_2026-09.md`.
