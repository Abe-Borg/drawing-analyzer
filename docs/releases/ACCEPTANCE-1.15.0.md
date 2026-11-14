# Release validation record — 1.15.0

Release requested by Abe Borg on 2026-11-13 to ship the latest code.
An unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.15.0` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `e9310a9ff30eac4e951c67e359ac552e7bc06cd1` (main, including #266 and #267) |
| Previous stable release | [v1.14.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.14.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock`, unchanged from v1.14.0 |

## Automated validation

Local Python 3.12 validation passed byte compilation, the tag/version guard,
dependency consistency, the repository secret scan, correctness-class static
analysis, the dependency license audit, release metadata tests (5 passed),
import isolation (2 passed), and a wheel/sdist build with a clean-venv install
smoke test reporting version 1.15.0. The full hermetic suite is also run locally;
its result is reported in the preparation PR. Pytest invocations deselect
`network`.

The pinned Chromium download is blocked locally with `403 Domain forbidden`;
hosted browser checks must provide that evidence. The preparation PR runs the
Linux Python 3.11/3.12 and Windows Python 3.11 matrix, browser security,
dependency audits, package build, and Windows installer build. Publication
requires the tag workflow's full Linux acceptance and audits, Windows suite,
and installer build to pass on the tagged commit. Workflow records identify
the exact commit, compiler and artifacts; `latest.json` records the installer
SHA-256. No audit exception or validation gate is weakened.

## Live and manual checks

| Section | Result / limitation |
|---|---|
| Live API canaries, reasoning-summary support and batch lifecycle | NOT RUN: no configured live API credential |
| Windows input/path matrix, Live view tabs, checklist Scope controls, and interactive install/update | NOT RUN: no interactive Windows desktop |
| Bluebeam Revu / Acrobat PDF acceptance | NOT RUN: those applications are unavailable |
| Excel / Notepad output acceptance | NOT RUN: those applications are unavailable |
| Representative real/redacted and large-set performance/cost qualification | NOT RUN: no approved drawing set or live account supplied |

Automated tests do not establish live model quality, real-set costs, or desktop
viewer acceptance. This record does not assert completion or owner sign-off for
the unrun checks.

## Compatibility and release mechanics

- The 1.15.0 changelog promotes the changes since v1.14.0 and retains an empty
  `[Unreleased]` section for later work.
- Includes checklist item ids, per-sheet scope and the exported results matrix;
  independent scoping of same-named checklists; the Story, Thinking, Plan and
  Findings tabs; and reasoning-summary rejection and cross-run display fixes.
- Checklist edits re-key critique only for sheets receiving the edited block.
  The checklist answer contract changes those sheets' critique keys once;
  no cache schema migration is introduced. Reasoning summaries remain in memory
  and do not affect cache keys.
- The release preparation changes no runtime code, dependency lock or workflow.
- The app remains unsigned. The updater verifies the installer SHA-256 before
  running it. The prior stable release remains available for rollback.
