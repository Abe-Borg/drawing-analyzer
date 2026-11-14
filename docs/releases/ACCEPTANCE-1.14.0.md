# Release validation record — 1.14.0

Release requested by Abe Borg on 2026-11-13 to ship the latest code.
An unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.14.0` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `dac5d2c979a9dec5e2ce4cce7ffb61d7d8449827` (main, including #264) |
| Previous stable release | [v1.13.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.13.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock`, unchanged from v1.13.0 |

## Automated validation

Local Python 3.12.14 validation passed byte compilation, the tag/version guard,
dependency consistency, the repository secret scan, correctness-class static
analysis, and the dependency license audit. Local pytest invocations deselect
`network`. The pinned Chromium download is blocked locally with
`403 Domain forbidden`; hosted browser checks must provide that evidence.

The preparation PR runs the Linux Python 3.11/3.12 and Windows Python 3.11
matrix, browser security, dependency audits, package build, and Windows installer
build. Publication requires the tag workflow's full Linux acceptance and audits,
Windows suite, and installer build to pass on the tagged commit. Workflow records
identify the exact commit, compiler and artifacts; `latest.json` records the
installer SHA-256. No audit exception or validation gate is weakened.

## Live and manual checks

| Section | Result / limitation |
|---|---|
| Live API canaries and batch lifecycle | NOT RUN: no configured live API credential |
| Windows input/path matrix, Live view, live spend controls, and interactive install/update | NOT RUN: no interactive Windows desktop |
| Bluebeam Revu / Acrobat PDF acceptance | NOT RUN: those applications are unavailable |
| Excel / Notepad output acceptance | NOT RUN: those applications are unavailable |
| Representative real/redacted and large-set performance/cost qualification | NOT RUN: no approved drawing set or live account supplied |

Automated tests do not establish live model quality, real-set costs, or desktop
viewer acceptance. This record does not assert completion or owner sign-off for
the unrun checks.

## Compatibility and release mechanics

- The 1.14.0 changelog promotes the changes since v1.13.0 and retains an empty
  `[Unreleased]` section for later work.
- Includes the animated Live view, live billed/in-flight/projected spend,
  editable budget cap, and remembered full-QC cost-confirmation preference.
- Live view is advisory: disabling it does not change the run. Spend figures
  are estimates from the application's price table and reported usage; the
  final display reconciles to the usage ledger. A budget stop cannot undo
  already-submitted work, which can leave final charges above the cap.
- No dependency-lock, cache-schema, or cache-key change is introduced by the
  release preparation.
- The app remains unsigned. The updater verifies the installer SHA-256 before
  running it. The prior stable release remains available for rollback.
