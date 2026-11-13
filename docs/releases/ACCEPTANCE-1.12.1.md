# Release validation record — 1.12.1

Release requested by Abe Borg on 2026-11-13 to ship the latest code.
This supersedes the unpublished v1.12.0 candidate; its tag and failed workflow
remain available as evidence. An unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.12.1` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `860be7cd649daf6f41e0ad7e4a233c136151dcfe` (main, including #257) |
| Previous stable release | [v1.11.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.11.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock`, including Anthropic 1.13.0, PyMuPDF 1.28.2, and pypdf 6.21.4 |

## Automated validation

The application base passed the full Linux/Windows CI matrix, browser security,
dependency audits, and package build in
[CI run 43493527349](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/43493527349).
The v1.12.0 tag's installer build and Windows release suite also passed.

The v1.12.0 release's Linux validation initially installed unconstrained
dependencies, including PyMuPDF 2.1 and companion packages. Its subsequent
locked install downgraded PyMuPDF but left companion packages with missing
license metadata. The license audit correctly failed and prevented publication.
Linux/Windows release validation and browser CI now use the release constraints
from their first installation. The acceptance runner's clean-wheel install
uses the same constraints, and all changed installations run `pip check`.
No dependency pin or audit exception is changed.

The preparation PR runs the full Linux Python 3.11/3.12 and Windows Python 3.11
matrix, browser-security suite, dependency audits, package build, and Windows
installer build. The stable tag repeats Linux acceptance and audits and the
Windows suite before publication. The workflow records provide exact commit,
compiler, and artifact evidence; `latest.json` records the installer SHA-256.

Local Python is 3.12.14. Local pytest invocations deselect `network`. The pinned
Chromium download is policy-blocked locally (`403 Domain forbidden`); hosted
Chromium checks provide browser-security evidence.

Local validation passed the 12 release-metadata/acceptance-runner tests, the
tag/version guard, dependency consistency, correctness-class static analysis,
and the secret scan. The changed clean-install gate built wheel and sdist,
installed the wheel in a fresh venv under the release constraints, passed
`pip check`, and verified version 1.12.1 and the installed profile mechanism.

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

- The [1.12.1 changelog](../../CHANGELOG.md) includes all changes since v1.11.0;
  v1.12.0 was not published. `[Unreleased]` remains for later work.
- Ask AI artifacts and the Files panel, spend-limit handling, browser policy
  error reporting, text-prompt fencing, security dependency updates, and the
  installer license changes are included unchanged from the v1.12.0 candidate.
- Saved chat transcripts use `request_prefix_version: 2`. Affected text-only
  stage caches refresh once; identity changes may refresh review and critique.
- The app remains unsigned. Installed users can check for updates; the updater
  verifies the installer SHA-256 before running it.
