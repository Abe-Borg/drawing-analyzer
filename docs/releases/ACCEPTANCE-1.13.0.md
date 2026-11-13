# Release validation record — 1.13.0

Release requested by Abe Borg on 2026-11-13 to ship the latest code.
An unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.13.0` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `640ef0742a1a754cc4904d1fce86e72db939c2bb` (main, including #259) |
| Previous stable release | [v1.12.1](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.12.1), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock`, including openpyxl 3.1.5 and et_xmlfile 2.0.0 |

## Automated validation

The application base passed CI in
[run 43500763636](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/43500763636).
Local Python 3.12.14 validation passed the 12 release-metadata/acceptance-runner
tests, tag/version guard, dependency consistency, correctness-class static
analysis, and dependency license audit. Local pytest invocations deselect
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
| Live API canaries, XFast service support, and batch lifecycle | NOT RUN: no configured live API credential |
| Windows input/path matrix and interactive install/update | NOT RUN: no interactive Windows desktop |
| Bluebeam Revu / Acrobat PDF acceptance | NOT RUN: those applications are unavailable |
| Excel / Notepad output acceptance | NOT RUN: those applications are unavailable |
| Representative real/redacted and large-set performance/cost qualification | NOT RUN: no approved drawing set or live account supplied |

Automated tests do not establish live model quality, real-set costs, or desktop
viewer acceptance. This record does not assert completion or owner sign-off for
the unrun checks.

## Compatibility and release mechanics

- The 1.13.0 changelog separates changes since v1.12.1 from that release's
  historical notes. `[Unreleased]` remains for later work.
- Includes the Loaded files panel, additional context documents, uploaded
  checklists, AHJ Atlas Input, XFast, and the save-tile-images control.
- AHJ Atlas replaces the GUI's typed governing-editions field; the library's
  `governing_editions=` remains available. Context-free runs preserve existing
  digest-cache keys. Runs with context incorporate that input in their keys.
- XFast carries a higher per-token price and falls back to standard speed when
  the service rejects the speed parameter. The cost preview records the choice.
- The app remains unsigned. The updater verifies the installer SHA-256 before
  running it. The prior stable release remains available for rollback.
