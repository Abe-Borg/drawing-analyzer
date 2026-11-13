# Release validation record — 1.12.0

Release requested by Abe Borg on 2026-11-13 to ship the latest code.
Automated evidence and checks requiring a live account or desktop applications
are recorded separately; an unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.12.0` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `fa50dc97f29546f7c9a9f6744df5bf5df125069d` (main, including #256) |
| Previous stable release | [v1.11.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.11.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock` at this commit, including Anthropic 1.13.0, PyMuPDF 1.28.2, and pypdf 6.21.4 |

## Automated validation

The application base passed all six checks in
[CI run 42684032112](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/42684032112):
Linux Python 3.11/3.12 and Windows Python 3.11 suites, headless-Chromium report
security, secret scan/static analysis/dependency audits, and wheel/sdist build
with clean-install smoke.

Local preparation uses Linux and Python 3.12.14 with the release-constrained
dependencies. Dependency consistency (`pip check`), the `v1.12.0` tag/version
guard, correctness-class static analysis, and the license/AGPL-notice audit
passed. Wheel and sdist builds, `twine check`, and a clean-venv installation
under the release constraints passed; installed distribution and package
versions both report 1.12.0, and the installed profile mechanism works.
Every local pytest invocation deselects the `network` marker.

The pinned local Chromium download was blocked by the environment's network
policy (`403 Domain forbidden`); this is not a browser-security pass. Hosted
Chromium checks supply the pinned browser-security evidence.

The preparation PR runs the full CI matrix and Windows installer build. The
stable tag's `release.yml` then repeats the full Linux acceptance, browser
execution check, static analysis, license and vulnerability audits, and Windows
hermetic suite on the release commit. Publication depends on all those gates
and the frozen-exe self-check/installer build passing. Their workflow records
are the evidence for the exact preparation and release commits, compiler
version, and artifacts. `latest.json` records the installer SHA-256.

## Live and manual checks

| Section | Result / limitation |
|---|---|
| Live API canaries and batch lifecycle | NOT RUN: no configured live API credential |
| Windows path/input matrix and interactive install/update | NOT RUN: no interactive Windows desktop |
| Bluebeam Revu / Acrobat PDF acceptance | NOT RUN: those applications are unavailable |
| Excel / Notepad output acceptance | NOT RUN: those applications are unavailable |
| Representative real/redacted and large-set performance/cost qualification | NOT RUN: no approved drawing set or live account supplied |

Synthetic automated tests do not establish live model quality, real-set costs,
or desktop viewer acceptance. This record does not assert completion or owner
sign-off for the unrun checks.

## Compatibility and release mechanics

- The [1.12.0 changelog](../../CHANGELOG.md) documents the changes since
  v1.11.0. `[Unreleased]` remains for later work.
- Ask AI can create downloadable charts, sortable tables, and Markdown memos;
  its Files panel lists artifacts and exported files and supports ZIP downloads.
- Saved chat transcripts use `request_prefix_version: 2`; older transcripts
  retain their text and tool history, with earlier reasoning reset.
- Drawing text is fenced in every text-only prompt. Affected cross-QC,
  synthesis, focus, identity, absence-check and harvest caches refresh once;
  review plans and critiques refresh if the resulting identity changes.
- Reaching an API spend limit stops further paid work while preserving
  completed results and collecting accepted batches. Chat preserves the key
  when an organization's policy blocks browser API calls.
- Dependency updates include pypdf 6.21.4 and audit-toolchain setuptools 84.1.0.
- The Windows installer displays and installs the license and copyright;
  updates use the full wizard. The app remains unsigned, with the existing
  SmartScreen guidance. The updater verifies the installer SHA-256.
