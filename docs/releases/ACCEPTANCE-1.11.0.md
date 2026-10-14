# Release validation record — 1.11.0

Release requested by Abe Borg on 2026-10-13 to ship the latest code.
Automated evidence and checks requiring a live account or desktop applications
are recorded separately; an unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.11.0` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `4d79784f6429020fd942375ae3104dc2ddad4448` (main, including #240) |
| Previous stable release | [v1.10.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.10.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | `requirements-release.lock` at this commit, including Anthropic 1.13.0 and PyMuPDF 1.28.2 |

## Automated validation

The application base passed all six checks in
[CI run 38417324875](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/38417324875):
Linux Python 3.11/3.12 and Windows Python 3.11 suites, headless-Chromium report
security, secret scan/static analysis/dependency audits, and wheel/sdist build
with clean-install smoke.

Local preparation uses Linux and Python 3.12.14 with the release-constrained
dependencies. Dependency consistency (`pip check`), the `v1.11.0` tag/version
guard, correctness-class static analysis, and the license/AGPL-notice audit
passed. Every pytest invocation deselects the `network` marker.

The pinned local browser download was blocked by the environment's network
policy (`403 Domain forbidden`). Hosted Chromium checks supply the pinned
browser-security evidence.

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
| Branch protection | `main` reported `protected: false`; repository settings unchanged |

Synthetic automated tests do not establish live model quality, real-set costs,
or desktop viewer acceptance. This record does not assert completion or owner
sign-off for the unrun checks.

## Compatibility and release mechanics

- The [1.11.0 changelog](../../CHANGELOG.md) documents all changes since
  v1.10.0. `[Unreleased]` remains for later work.
- Governing code editions can be supplied by the reviewer and replace the
  detected governing basis for the named codes throughout QC. Unreadable
  entries stop the run before API calls; changes re-plan and re-critique.
- Sheet-level absence findings are cross-checked against the set's source text.
  Grounded hits lower severity and add location fields to the report, markup
  popup and three trailing `findings.csv` columns.
- Citation checks can conclude `UNRESOLVABLE`; support requires an HTTPS
  evidence URL. Unconfirmed references remain visible as unconfirmed.
- Identity schema 11, verification prompt `verify-v3`, and the edited stage
  prompts invalidate their affected caches. Critique, synthesis, identity,
  review-plan, cross-sheet QC, harvest, verification and citation stages may
  re-run once; the changelog describes the individual changes and costs.
- Digest and verification default to six real-time workers; critique remains
  at four. Explicit arguments and the shared environment override still apply.
- The release ships Anthropic SDK 1.13.0; no live canary is claimed.
- The Windows app remains unsigned, with the existing SmartScreen guidance.
  Installed users can select **Check for Updates** or wait for the daily check;
  the updater verifies the installer SHA-256 before launching it.
