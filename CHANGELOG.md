# Changelog

User-visible changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Detailed implementation and review history lives in commits and pull requests;
earlier release notes remain in [GitHub releases](https://github.com/Abe-Borg/drawing-analyzer/releases)
and git history. Release acceptance records are separate evidence.

## [Unreleased]

### Fixed

- Economy submission leaves image-upload failures as sheet errors instead of
  silently switching digest or critique reads to full-price real-time calls.
- Digest and critique cache keys now include sheet, grid, tile and omission
  labels sent to the model at both cache levels. Old unlabeled entries miss
  once; other stages' caches and existing cache files are retained.
- Unfinished, refused or failed model reads no longer masquerade as completed
  work in the stages repaired so far. Retries preserve better reads, interrupted
  streams retain available usage, and cross-sheet QC exposes partial results.
- Findings are less likely to merge across incompatible tags, quantities,
  quantity roles, feet-and-inches values or source sheets. Grounding and anchors
  match whole source tokens; arithmetic checks require drawing-grounded operands
  and relationships before making a deterministic claim.
- Invalid, missing or unreadable sources/pages are isolated more reliably so
  other sheets and paid results survive. Some recovery and cleanup work remains.
- GUI runs retain their starting API key without passing it through the process
  environment. Saved/legacy keys handle BOMs and invisible characters; migration
  preserves files whose contents were not verified as the migrated key.
- Offline tests block network access and exercise request/response shapes through
  the real SDK. Scripted replies establish code behavior, not live review quality.

### Changed

- Prompt source blocks distinguish drawing content from instructions. Relevant
  cache keys cover their framing; cache contracts also changed for repaired
  critique and cross-sheet behavior. Affected stages may need paid rereads on
  upgrade. Existing cache files are retained; do not delete them as a migration.
- Review/chat defaults moved to Opus 5.5/Sonnet 5.5, with capability-based request
  handling and serving-model alternatives. Changing models also changes cache
  identity. These changes have not established lower cost or better findings on
  real drawings; use a budgeted comparison before making that claim.
- Trust help now describes actual key, network, retention, spending and review
  limits instead of blanket correctness or losslessness promises.
- The Windows installer displays the AGPL license and requires acceptance.
- Documentation and the agent queue are being reduced to current user behavior,
  essential guarantees and explicitly approved work. Past decision transcripts
  and implementation narratives remain recoverable from git history.

### Known limits

- Displayed costs are estimates. Fallback/interrupt/tool accounting has remaining
  gaps; compare it with provider usage. Chat charges are outside analysis totals.
- Model-quality, prompt and cost improvements since 1.7.0 remain unverified live.
  Structured-output experiments remain opt-in. No live spending budget is implied.
- A completed run or saved-markup receipt proves execution/placement coverage,
  not that the model found every engineering defect.

## [1.7.0] - 2026-09-21

### Added

- Verification distinguishes malformed, truncated and failed verdict calls in
  its diagnostics, helping explain findings that received no model judgment.
- Opt-in structured outputs for prose harvesting and crop verification, with
  separate cache identities and fallback to the ordinary response contract.
- Report chat wraps the report as source material for the model.

### Changed

- Anthropic SDK updated to 1.7.0.
- Removed unused `tiktoken` helpers/dependency and its first-use encoding download.

The published release's acceptance evidence is preserved in
[ACCEPTANCE-1.7.0](docs/releases/ACCEPTANCE-1.7.0.md); publication does not alter
that record's HOLD or unstarted manual/live checks.

## [1.6.0] - 2026-09-15

### Added

- Opt-in structured critique responses, separate cache identities and a
  capability-rejection fallback; batch critique uses the ordinary contract.
- Strict investigation tool schemas with host-side bounds retained.

### Changed

- Digest/critique reasoning effort resolves through the shared phase registry,
  preserving the existing high-effort requests.
- Structured-output support is selected by model capabilities.
- Anthropic SDK updated to 1.5.0.

Historical evidence is in
[ACCEPTANCE-1.6.0](docs/releases/ACCEPTANCE-1.6.0.md). These notes do not change
sign-offs, waivers or the release decision.
