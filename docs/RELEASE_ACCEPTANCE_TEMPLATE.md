# Release acceptance record (Phase 27, §19.9)

Copy this file per release candidate, fill it in completely, and keep the
completed copy with the release. **A release may be cut only when every
automated gate passes and every manual section is recorded** — passing the
hermetic suite alone is not acceptance (§19 Definition of done).

## 0. Release candidate identification

| Field | Value |
|---|---|
| Version (`pyproject.toml` / `drawing_analyzer.__version__`) | |
| Git commit (full SHA) | |
| Date / release owner | |
| Built artifacts (wheel + sdist) sha256 | |
| Dependency lock used (`requirements-release.lock` at this commit) | ☐ |
| Python / PyMuPDF / MuPDF / Anthropic SDK versions | |
| Model ids exercised (digest / critique / verify / citation) | |
| Web-search tool type observed by the live canary | |

## 1. Automated gates

Run `python scripts/run_acceptance.py` on Linux **and** Windows, plus CI on
the release commit. All must pass.

- [ ] Hermetic suite green on Windows (py3.11) and Linux (py3.11 + py3.12) — CI `test` matrix.
- [ ] Trust gauntlet (§19.1) green: cold assertions 1–15, warm-cache run, mutation run, per-stage failure injection, review-notes overflow (`tests/test_drawing_acceptance.py -k gauntlet`).
- [ ] Large-set cross-shard acceptance (§19.2) green (44-sheet reconciliation, 84-sheet reduction, failed-shard PARTIAL).
- [ ] PyMuPDF import isolation (I-5) green.
- [ ] Headless-Chromium report exploit suite green — CI `browser-security`.
- [ ] Secret scan clean (`scripts/scan_secrets.py`) — repo, reports, logs, snapshots.
- [ ] Static analysis (correctness classes) clean.
- [ ] Dependency vulnerability audit clean, or every finding carries a dated, owner-approved, time-limited `--ignore-vuln` exception in `ci.yml`.
- [ ] Dependency license / AGPL-notice audit clean (`scripts/check_licenses.py`).
- [ ] Wheel/sdist build + twine check + clean-venv install smoke green (packaged profiles present; installed version == `__version__`) — CI `build`.
- [ ] Branch protection names `test`, `browser-security`, `security-gates`, `build` as required checks (admin console — record who verified).

## 2. Live API canary (§19.3 — opt-in, billable)

`ANTHROPIC_API_KEY=... python -m pytest -m network -rs -s tests/test_live_api_canary.py`

- [ ] Digest request schema + structured findings parse against the live service.
- [ ] Critique completes both self-consistency reads with parse-valid output.
- [ ] Pinned web-search tool type accepted; citation parsing handles a real tool-result stream; assessments are claim-complete.
- [ ] Files API upload → delete lifecycle verified (deleted ids unretrievable).
- [ ] Exported `run.log` / `run_manifest.json` / `report.html` from the live run contain no key.
- [ ] Batch transport: one real `use_batch=True` run collected; usage records priced `BATCH`; remote files cleaned up (attach `run_manifest.json`).
- [ ] Observed model/tool versions recorded in §0.

## 3. Windows & path acceptance (§19.4)

- [ ] `docs/WINDOWS_ACCEPTANCE.md` completed on a real Windows machine against the built wheel. Attach the completed copy.

## 4. Bluebeam Revu & Acrobat/Chromium acceptance (§19.5)

Use the synthetic oracle set (exportable via `tests/fixtures/gauntlet.py`) **and**
a representative approved real/redacted set. Open every `*_reviewed.pdf` and
`Drawing_Set_Review_Notes.pdf`.

In **Bluebeam Revu**:

- [ ] Markups List rows match the successful receipts in `markup_manifest.json` — not the ledger's intentions; failed/gated items appear only per their receipts.
- [ ] Every cloud/callout/tag shows the correct QC id and source sheet.
- [ ] Author, subject, contents (severity, quote, verification status, citation notes, provenance, evidence references) survive in the popup.
- [ ] Exact anchors sit on the intended text — including the rotated (90/180/270), cropped, and repeated-text sheets from the oracle set.
- [ ] Every cross-sheet leg appears only on its intended source; the duplicate-basename pair shows zero cross-contamination.
- [ ] Rejected findings appear in the index section, not inked (unless the grey opt-in was used); UNCERTAIN styling is visually distinct.
- [ ] Index rows and review-notes GOTO links navigate to the right page/region.
- [ ] Pre-existing (non-analyzer) annotations remain unchanged.
- [ ] Unicode content displays correctly.
- [ ] Save → close → reopen preserves appearance and metadata.
- [ ] Revu can filter, sort, reply to, and export the analyzer markups.

In **Acrobat** and **Chromium**:

- [ ] Appearance streams render (nothing blank): clouds, tags, callouts, leaders, links.
- [ ] Colors/severity styling match configuration; page count and original content intact.
- [ ] No annotation exists only in the Markups List but invisibly on the page, or visibly on the page but absent from receipts.

## 5. Excel & text-output acceptance (§19.6)

- [ ] `findings.csv` opens in Excel: BOM/UTF-8 honored, CRLF rows, quoting/embedded commas and newlines intact, page values and source disambiguation correct, QC ids/citation/evidence columns populated, no row corruption.
- [ ] Formula-injection payloads (`=HYPERLINK`, `+`, `-`, `@`, DDE-style) render inert (leading apostrophe), while ordinary negative numbers in numeric columns stay numeric.
- [ ] `run.log` and the Markdown exports open readably in Notepad (UTF-8, CRLF for run.log); no secret or absolute private path anywhere.

## 6. Performance & cost qualification (§19.7)

- [ ] `docs/PERFORMANCE_AND_COST_VALIDATION.md` record completed and attached (`benchmark_report.json` + live batch manifest).
- [ ] Regressions within owner-approved tolerance; README/UI cost claims verified.

## 7. Release checklist (§19.9)

### Code and correctness
- [ ] Every P0/P1 item in the plan's §5 is closed or explicitly owner-deferred in writing (list deferrals below).
- [ ] Full offline suite passes on Windows and Linux.
- [ ] Trust gauntlet passes cold, warm, and mutated runs.
- [ ] Cross-shard conflict acceptance passes.
- [ ] No basename-only trust key remains.
- [ ] Coordinate and cache schema versions are current.
- [ ] No machine block leaks into sacred prose.
- [ ] Every markup tally is receipt-derived.

### Security
- [ ] Dynamic assistant content uses safe DOM construction.
- [ ] External URL protocols are allowlisted.
- [ ] Browser exploit test passes.
- [ ] Default report contains no key.
- [ ] Reports, logs, diagnostics, CI, and snapshots pass secret scans.
- [ ] Security documentation (SECURITY.md) is current.
- [ ] No unresolved high/critical dependency issue lacks a time-limited documented exception.

### Product-plan completion
- [ ] QC Markups alone invokes the full exhaustive stack.
- [ ] Profiles are visible, selectable, auto-suggested, snapshotted, and cache-sensitive.
- [ ] Deterministic auditors always run in exhaustive QC.
- [ ] Standard runs retain findings and sheet text.
- [ ] Large sets receive final reconciliation.
- [ ] Every prose item and verifier crop is accounted.
- [ ] Citation verdicts are claim-complete.
- [ ] High-severity report and severity-first index controls exist.
- [ ] `run.log` and run/markup manifests are exported.

### Manual production acceptance
- [ ] Windows path/input matrix completed (§3 above).
- [ ] Bluebeam Revu acceptance completed (§4).
- [ ] Acrobat/Chromium acceptance completed (§4).
- [ ] Excel/Notepad acceptance completed (§5).
- [ ] Synthetic oracle: 100% expected placement coverage; zero wrong-source ink.
- [ ] Representative real/redacted set passed.
- [ ] >40-sheet set passed.
- [ ] This record identifies the exact commit and application/dependency versions (§0).

### Release mechanics
- [ ] Version bumped and CHANGELOG finalized (move `[Unreleased]` under the tagged version).
- [ ] Cache invalidation/compatibility changes documented.
- [ ] Clean artifacts built from the approved commit; hashes recorded in §0.
- [ ] Known-good prior release retained for rollback.
- [ ] Release notes distinguish fixed defects, behavior changes, known limitations, and any deferred P2 items.

## Deferrals / waivers (owner-approved, in writing)

| Item | Scope | Justification | Owner approval / date | Expiry |
|---|---|---|---|---|
| | | | | |

## Sign-off

```
Automated gates:   PASS / FAIL      (attach run_acceptance output)
Live canary:       PASS / FAIL / WAIVED
Manual sections:   COMPLETE / INCOMPLETE

Release decision:  SHIP / HOLD

Owner signature: ______________________  Date: __________
```
