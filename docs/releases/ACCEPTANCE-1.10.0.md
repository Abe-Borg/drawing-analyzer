# Release validation record — 1.10.0

Release requested by Abe Borg on 2026-10-08 to ship the latest changes.
Automated evidence and checks requiring a live account or desktop applications
are recorded separately; an unrun check is not a pass.

## Candidate

| Field | Value |
|---|---|
| Version | `1.10.0` in `pyproject.toml` and `drawing_analyzer.__version__` |
| Application base | `1272cb41e164a655be73b74ce92fa09e4ce23a2d` (main, including #228) |
| Previous stable release | [v1.9.0](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.9.0), retained for rollback |
| Release artifacts | `DrawingAnalyzerSetup.exe` and `latest.json`, built by the tag workflow |
| Dependency constraints | Unchanged `requirements-release.lock`, including Anthropic 1.11.0 and PyMuPDF 1.28.2 |

## Automated validation

The application base passed all six checks in
[CI run 37840950342](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/37840950342):
Linux Python 3.11/3.12 and Windows Python 3.11 suites, headless-Chromium report
security, secret scan/static analysis/dependency audits, and wheel/sdist build
with clean-install smoke.

Local preparation uses Linux and Python 3.12.14 with the release-constrained
dependencies. Dependency consistency (`pip check`), the `v1.10.0` tag/version
guard, correctness-class static analysis, and the license/AGPL-notice audit
passed. Every pytest invocation deselects the `network` marker.

The local browser download was blocked by the environment's network policy
(`403 Domain forbidden`); this is not a browser-security pass. Hosted Chromium
checks supply that evidence.

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

- The [1.10.0 changelog](../../CHANGELOG.md) describes the diagnostics bundle
  and corrected headroom classification. `[Unreleased]` remains for later work.
- No dependency, model default, prompt, grid, or cache schema changes are part
  of this release. Diagnostics describe calls already made by the pipeline.
- Every export now includes `diagnostics/`, with redacted per-call records,
  headroom, retries, host samples, and events; the run manifest hashes them.
- Request provisioning for batches submitted in an earlier run is unknown;
  their headroom is `NOT_ASSESSED` rather than asserted to be adequate.
- The Windows app remains unsigned, with the existing SmartScreen guidance.
  Installed users can select **Check for Updates** or wait for the daily check;
  the updater verifies the installer SHA-256 before launching it.
