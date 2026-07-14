# Windows & path acceptance — manual checklist (Phase 27, §19.4)

This is the recordable manual acceptance script for Windows. Automated
cross-platform tests inject permission, lock, zero-page, long-path, and disk
failures through controlled seams (see `tests/test_input_inventory.py`,
`tests/test_source_mutation.py`, `tests/test_drawing_acceptance.py`); **real**
platform behavior is verified here, on a real Windows machine, against the
exact release candidate. Do not substitute POSIX `chmod`/lock simulations for
this checklist.

A release candidate cannot ship until every row below is recorded as
**PASS**, **N/A** (with a reason), or **WAIVED** (with a written owner
waiver). Keep the completed copy with the release record
(`docs/RELEASE_ACCEPTANCE_TEMPLATE.md`).

## Release candidate identification

| Field | Value |
|---|---|
| Date of acceptance | |
| Tester | |
| Git commit (full SHA) | |
| Package version (`pip show drawing-analyzer`) | |
| Windows edition + build (`winver`) | |
| Python version | |
| PyMuPDF / MuPDF versions | |
| Anthropic SDK version | |
| Install method (wheel / sdist / editable) | |

Install from the built release artifacts (`pip install dist/*.whl`), never
from a developer checkout, so the packaged profiles and entry points are what
is actually being accepted.

## 1. Path and input matrix

For each row: run an analysis (standard unless stated), confirm the run
completes or fails *visibly and usefully*, and confirm `run.log` +
`run_manifest.json` record the input with no absolute private path in the
portable export.

| # | Case | How to test | Expected | Result / notes |
|---|---|---|---|---|
| 1.1 | Path with spaces | `C:\Users\...\My Drawings\M-101.pdf` | Completes normally | |
| 1.2 | Unicode path | Folder named `Проект-Ü東京` | Completes normally | |
| 1.3 | Apostrophe + parentheses | `O'Brien (Rev 2)\M-101.pdf` | Completes normally | |
| 1.4 | `#` and `&` in path | `Bid #4 & Alt\M-101.pdf` | Completes normally | |
| 1.5 | Duplicate basenames in nested dirs | `areaA\M-101.pdf` + `areaB\M-101.pdf` in one run | Both analyzed; distinct source IDs; reviewed PDFs disambiguated (`M-101__SRC-0001_reviewed.pdf`, …); no cross-contaminated markup | |
| 1.6 | Long path (within supported policy) | Path near the effective limit (260 chars without LongPathsEnabled; document registry state) | Completes, or fails with a clear path-length error — never a partial silent export | |
| 1.7 | Read-only input file | Set file read-only | Analysis completes (input is only read) | |
| 1.8 | Unwritable export destination | Export to a read-only folder | Visible error; no half-written unlabeled folder (a `.partial`/`_INCOMPLETE` staging dir is acceptable) | |
| 1.9 | Input locked by another program | Open the PDF in Acrobat with an exclusive lock while analyzing | Per-file visible error; other inputs complete | |
| 1.10 | OneDrive / synced folder (if used in production) | Input + export under OneDrive | Completes; no sync-placeholder failures; note any latency | |
| 1.11 | UNC / network path (if used in production) | `\\server\share\M-101.pdf` | Completes or clear error; no hang | |
| 1.12 | Password-protected PDF | Any encrypted PDF | Recorded as ENCRYPTED in inventory; run continues for other files | |
| 1.13 | Corrupt PDF | Truncated/garbage `.pdf` | Recorded as UNREADABLE; run continues; error visible in GUI summary + `run.log` | |
| 1.14 | Zero-page PDF | Valid PDF with 0 pages | Recorded as EMPTY; run continues | |
| 1.15 | Same file supplied twice | Select the identical path twice | Deduplicated as DUPLICATE; processed once | |
| 1.16 | Disk-full behavior (work/export drive) | Analyze onto a nearly-full volume (or quota-limited) | Visible failure before/at export; no folder that looks complete | |

## 2. Page/content matrix

Use a set containing all of the following (the synthetic acceptance set from
`tests/fixtures/gauntlet.py` can be exported to disk for this purpose, plus a
representative real/redacted set):

| # | Case | Expected | Result / notes |
|---|---|---|---|
| 2.1 | Vector, raster (scanned), and hybrid pages | All analyzed; raster badge in report; raster render target used | |
| 2.2 | Portrait + landscape | Correct rendering and anchors | |
| 2.3 | Rotations 0°/90°/180°/270° | Anchors + clouds land on the intended text in every viewer | |
| 2.4 | Non-default CropBox | Anchors + clouds land correctly; no content outside crop | |
| 2.5 | Pre-existing annotations in inputs | Originals untouched; pre-existing marks survive in the reviewed copy; coverage reconciliation ignores them | |

## 3. GUI behavior

| # | Case | Expected | Result / notes |
|---|---|---|---|
| 3.1 | Responsiveness during preflight + analysis | Window remains responsive (no "Not Responding"); progress labels advance through digest, critique ×2, cross-QC, auditors, prose harvest, anchoring, verification, citations, markup writing, coverage reconciliation | |
| 3.2 | Completion dialog states | Distinguishes **Completed**, **Completed with QC warnings**, **QC incomplete**; matches `run.log` and the report header | |
| 3.3 | Useful errors | Each rejected input appears in the completion summary with a per-file reason | |
| 3.4 | Recovery without restart | After a failed run, a second run works in the same session | |
| 3.5 | API-key storage | Key persisted via Windows Credential Manager (keyring); session-only fallback when unavailable; no plaintext file without explicit consent | |
| 3.6 | Cost preview | Exhaustive-run estimate appears before submission and lists paid stages | |

## 4. Output encoding spot checks (see also §19.6 script in RELEASE_ACCEPTANCE_TEMPLATE)

| # | Case | Expected | Result / notes |
|---|---|---|---|
| 4.1 | `findings.csv` in Excel | UTF-8 BOM honored, CRLF rows, no formula executes (`=`, `+`, `-`, `@` payloads inert), embedded commas/newlines survive | |
| 4.2 | `run.log` in Notepad | Readable UTF-8, CRLF line endings, no API key, no absolute private path | |
| 4.3 | Markdown exports in Notepad | Readable UTF-8 | |

## Sign-off

```
All rows recorded. Failures and waivers listed below.

Failures: <none | list>
Waivers:  <none | list with owner approval reference>

Tester signature: ______________________  Date: __________
```
