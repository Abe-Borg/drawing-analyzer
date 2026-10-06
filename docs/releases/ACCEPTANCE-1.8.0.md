# Release validation record — 1.8.0

Release requested by Abe Borg on 2026-10-05 to make the latest progress
available to installed users. This record separates automated evidence from
checks that require a live API account or desktop applications; an unrun check
is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.8.0` in both `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `bd555fa7d58d389fcfa9549d7bb0eed2d32e0ba2` (main, including #216) |
| Release preparation | [#217](https://github.com/Abe-Borg/drawing-analyzer/pull/217) |
| Previous stable release | [v1.7.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.7.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock`, including Anthropic 1.11.0 and PyMuPDF 1.28.2 |
| Default models | `claude-opus-5-5` for review and escalation; `claude-sonnet-5-5` for verification and supporting stages |

## Automated validation

Local validation uses Linux, Python 3.12.14, and the release-constrained
dependencies. Every pytest invocation deselects the `network` marker.

| Check | Result |
|---|---|
| Dependency consistency (`pip check`) | PASS |
| Tag/version guard (`check_release_version.py --tag v1.8.0`) | PASS |
| Static analysis (`ruff check --select E9,F63,F7,F82 src tests scripts`) | PASS |
| License / AGPL-notice audit (`scripts/check_licenses.py`) | PASS |
| Local byte-compile and import isolation | PASS (2 isolation tests) |
| Local hermetic suite / trust gauntlet / large-set tests | PASS: 2858 passed, 106 browser tests skipped, 10 network tests deselected |
| Local secret scan | PASS (182 tracked files, including this record) |
| Local wheel/sdist build and clean-install smoke | PASS; installed version `1.8.0`, profile mechanism verified |
| Local browser gate | BLOCKED; see environment limitation below |
| Hosted Linux 3.11/3.12 CI | PASS on `4356a7ad5bfd53cf3cc5bf8268e78beb0d698674`, [CI run 37412782109](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/37412782109) |
| Hosted browser security | PASS: 106 collected and 106 executed, [job 112104705430](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/37412782109/job/112104705430) |
| Hosted static analysis, secret scan, license and vulnerability audits | PASS, [job 112104705399](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/37412782109/job/112104705399) |
| Hosted Windows 3.11 CI | PASS on the same preparation commit, [job 112104705396](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/37412782109/job/112104705396) |
| Hosted Windows installer build and frozen-exe self-check | PASS, [run 37412782091](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/37412782091); Inno Setup 6.7.1 |

The local acceptance script passed every gate except the browser gate, which
initially skipped because Playwright's Chromium was absent. Downloading that
browser was denied by the environment's network policy. A diagnostic rerun
using preinstalled Chromium 151 failed before loading each report with
`net::ERR_BLOCKED_BY_ADMINISTRATOR` on `file://` URLs. No browser policy was
changed. The successful hosted browser job above is the browser evidence;
the local run is not represented as a full acceptance PASS.

The stable tag's `release.yml` repeats the full Linux acceptance, browser
execution check, static analysis, license and vulnerability audits, and the
Windows hermetic suite. Its `publish` job depends on those gates and the
installer build. Publication and artifact hashes are evidenced by that tag
run and the resulting release assets, rather than by a prep-branch installer.

## Live and manual checks

| Section | Result / limitation |
|---|---|
| Live API canaries and batch lifecycle | NOT RUN: this environment has no configured live API credential |
| Windows path/input matrix and interactive install/update | NOT RUN: no interactive Windows desktop is available |
| Bluebeam Revu / Acrobat PDF acceptance | NOT RUN: those desktop applications are unavailable |
| Excel / Notepad output acceptance | NOT RUN: those desktop applications are unavailable |
| Representative real/redacted and large-set performance/cost qualification | NOT RUN: no approved drawing set or live account was supplied |
| Branch protection | `main` reported `protected: false`; repository settings were not changed |

The automated trust gauntlet and large-set tests are synthetic and cannot
establish live model quality, real-set cost, or desktop viewer acceptance.
This record does not assert completion or owner sign-off for the unrun checks.

## Compatibility and release mechanics

- The [1.8.0 changelog](../../CHANGELOG.md) describes the shipped features,
  fixes, behavior changes, and cache implications; `[Unreleased]` remains as
  the staging area for later work.
- The 5.5 default models require access on the user's Anthropic account.
  Previous 5-generation models remain supported through the documented model
  environment overrides. A model change requires fresh digest/critique reads.
- Page grid changes also require fresh reads. ANSI E and ARCH E1 keep their
  previous grids; `DRAWING_ANALYZER_FIXED_GRID=1` restores fixed 6×6 tiling.
- Structured-output options remain opt-in. No live canary was used to justify
  enabling them by default.
- The Windows app remains unsigned. The release notes retain the existing
  SmartScreen installation guidance.
- Users can select **Check for Updates**, or wait for the daily update check.
  The updater verifies the downloaded installer against the SHA-256 recorded
  in `latest.json` before launching it.
