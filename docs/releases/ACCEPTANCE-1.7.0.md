# Release acceptance record — 1.7.0

Copy of `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` for this candidate.

> **Status: NOT YET TAGGED.** This record was written *with* the version-bump
> PR, ahead of the tag, so that — unlike 1.6.0, whose artifact shipped before its
> record existed — the attestation precedes the artifact.
>
> What that means for the evidence below: every automated gate is evidenced on
> the code **as merged** (`1649ba7`, the head of
> [#149](https://github.com/Abe-Borg/drawing-analyzer/pull/149), merged as
> `7de9332`). The release commit itself adds only the two version literals, the
> CHANGELOG promotion and this file, and the tag run re-executes every gate on
> it (`release.yml`: `build`, then the tag-gated `gates`, `gates-windows` and
> `publish`). The ⬜ fields in §0 are the ones only the tag run can supply.
>
> Everything that needs a real key, a Windows machine, licensed desktop software
> or an owner's eyes (§§2–6) is **unstarted** and marked so. §19 Definition of
> done still applies: *"A release may be cut only when every automated gate
> passes and every manual section is recorded — passing the hermetic suite alone
> is not acceptance."*
>
> **So the stable `v1.7.0` tag is on HOLD** until every §§2–6 section is
> recorded, or explicitly waived by the owner in the *Deferrals / waivers*
> table below (item, justification, approval, expiry), and the *Release
> decision* line in the sign-off reads SHIP. This is not a formality:
> `release.yml` publishes whatever `v1.7.0` points at as the **latest**
> release, and every installed copy is offered it within a day
> (`docs/RELEASE_WINDOWS.md`), so a stable tag ahead of acceptance ships an
> unaccepted build to every existing install. 1.6.0 did exactly that; its
> record documents it as the failure it was, not as precedent.
>
> The sanctioned way to get this build into testers' hands *before* §§2–6 are
> done is a **release candidate**: set both version literals to `1.7.0rc1`,
> promote the CHANGELOG heading to match (`tests/test_release_metadata.py`
> pins the two together), and tag `v1.7.0rc1`. `release.yml` publishes an
> `rcN` tag as a GitHub **pre-release**, which the updater never auto-offers
> (`latest.json` resolves to the newest full release), so existing installs
> are untouched while the RC is exercised through §§2–6.

## 0. Release candidate identification

| Field | Value |
|---|---|
| Version (`pyproject.toml` / `drawing_analyzer.__version__`) | `1.7.0` / `1.7.0` (guard: `check_release_version.py --tag v1.7.0` OK; `tests/test_release_metadata.py` green) |
| Git commit (full SHA) | ⬜ **Fill before tagging** with the merge commit of the release-prep PR on `main` — the tag must point at it, and `release.yml` refuses to publish if the tag and `pyproject.toml` disagree. Code content = `7de9332` (merge of #149) + that PR (version literals, CHANGELOG, this record). |
| Date / release owner | 2026-09-21 / Abe Borg |
| Built artifacts sha256 | ⬜ From the tag run's `Build Windows installer` job: the printed `latest.json` carries the installer's sha256; record it and the `latest.json` sha256 here from the published release assets, not from a prep-branch build (see the 1.6.0 record for why). |
| Dependency lock used (`requirements-release.lock` at this commit) | Blob `faabc85b3530c1012288def5a1ee85ed04bbb159`, file sha256 `bfe63d9ddbe4ec387c450007de23efb6c91b0f7175580a7523f305087e48ae94`, last written by `6dad8bf`. Diff vs `v1.6.0`: `anthropic` 1.5.0→1.7.0 with the transitive bumps recorded in the 1.7.0 CHANGELOG entry (#147), and `tiktoken` **removed** together with the five pins only it pulled in (`certifi`, `charset-normalizer`, `regex`, `requests`, `urllib3`). |
| Inno Setup compiler version (the tool whose output IS the shipped installer) | ⬜ From the tag run's `Build Windows installer` job — the step name carries it ("Compile installer (Inno Setup X.Y.Z)"). 6.7.1 on `v1.6.0`; the same path ran green on #149's own build run ([35654462485](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462485), job [106514510949](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462485/job/106514510949)), where the version guard was correctly `skipped` (tag-only). |
| Python / PyMuPDF / MuPDF / Anthropic SDK versions | Python 3.11.9 (the hosted-toolcache interpreter the installer freezes; 3.11.15 locally) / PyMuPDF 1.28.2 / MuPDF 1.28.2 / anthropic 1.7.0 |
| Model ids exercised (digest / critique / verify / citation) | `claude-opus-5` / `claude-opus-5` / `claude-sonnet-5` / `claude-sonnet-5` (escalation `claude-opus-5`) — unchanged from 1.6.0 |
| Web-search tool type observed by the live canary | configured `web_search_20260209` — **observed value pending §2** |

## 1. Automated gates — ✅ PASS on the merged code (`1649ba7`); ⬜ re-evidence on the tagged commit

`python scripts/run_acceptance.py` on Linux, on `1649ba7`:

```
  byte-compile                     PASS
  import isolation (I-5)           PASS
  hermetic suite + trust gauntlet  PASS   (2450 passed, 1 skipped, 10 network deselected)
  secret scan                      PASS   (174 tracked files)
  browser security                 PASS   (98 collected, 98 executed)
  build + clean-install smoke      SKIP   (`build` not installed in the sandbox — covered by CI `build`, below)
```

That is a local run and carries no commit of its own; the same gates passed in
CI on the same commit, `ci.yml` run
[35654462327](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327).
The tag run will execute the whole script again as `release.yml`'s `gates` job
(Chromium installed, so the browser gate cannot short-circuit) — cite that job
here once it exists, since it is the one whose green run lets `publish` proceed.

- [x] Hermetic suite green on Windows (py3.11) and Linux (py3.11 + py3.12) — `ci.yml` run 35654462327 on `1649ba7`: [`tests (ubuntu-latest, py3.11)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327/job/106514507848), [`tests (ubuntu-latest, py3.12)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327/job/106514507615), [`tests (windows-latest, py3.11)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327/job/106514507798). ⬜ Re-cite from the tag's own `ci.yml` run once tagged (py3.12 is evidenced only there — `release.yml`'s `gates` pins 3.11).
- [x] Windows installer path green — `release.yml` run [35654462485](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462485), job [`Build Windows installer`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462485/job/106514510949): PyInstaller build, frozen-exe self-check, Inno Setup compile, `latest.json`, artifact upload. The version guard was `skipped` there (tag-only) — it runs for real on the tag.
- [ ] **`python scripts/run_acceptance.py` on Windows.** No CI job runs it (`gates-windows` runs the hermetic suite, a different thing); Windows-only behaviours (path length, `\\?\` long paths, `os.utime`, Credential Manager) are why it is a separate leg.
- [x] Trust gauntlet (§19.1) green — included in the hermetic suite gate above.
- [x] Large-set cross-shard acceptance (§19.2) green — same.
- [x] PyMuPDF import isolation (I-5) green.
- [x] Headless-Chromium report exploit suite green — CI [`headless-chromium report security (linux)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327/job/106514507830), and locally with the executed-test floor enforced (`check_browser_suite.py`: 98 executed; a skip is not a pass).
- [x] Secret scan clean (`scripts/scan_secrets.py`, 174 tracked files); GitGuardian green on the PR.
- [x] Static analysis (correctness classes) clean — `ruff check --select E9,F63,F7,F82 src tests scripts`, locally and in CI.
- [x] Dependency vulnerability audit clean — CI [`secret scan · static analysis · dependency audits (linux)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327/job/106514507285) green on `1649ba7`; no `--ignore-vuln` exception added this release. The dependency set *shrank* (tiktoken and five transitive pins gone).
- [x] Dependency license / AGPL-notice audit clean — same job (`scripts/check_licenses.py`).
- [x] Wheel/sdist build + twine check + clean-venv install smoke green — CI [`wheel/sdist build + clean-install smoke (linux)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35654462327/job/106514507722).
- [ ] **Branch protection names `test`, `browser-security`, `security-gates`, `build` as required checks** (admin console — record who verified). *Not verifiable from here.*
- [x] Acceptance run was hermetic: every pytest gate deselected the `network` marker (`tests/test_run_acceptance.py` pins this), so §1 billed no live canary call.

## 2. Live API canary (§19.3 — opt-in, billable) — ⬜ NOT RUN

```bash
ANTHROPIC_API_KEY=... python -m pytest -m network -rs -s tests/test_live_api_canary.py
```

- [ ] Digest request schema + structured findings parse against the live service.
- [ ] Critique completes both self-consistency reads with parse-valid output.
- [ ] Pinned web-search tool type accepted; citation parsing handles a real tool-result stream; assessments are claim-complete.
- [ ] Files API upload → delete lifecycle verified.
- [ ] Exported `run.log` / `run_manifest.json` / `report.html` from the live run contain no key.
- [ ] Batch transport: one real `use_batch=True` run collected; usage priced `BATCH`; remote files cleaned up.
- [ ] Observed model/tool versions recorded in §0.

**Structured-output canaries — three now, one per stage gate, and each pins a
default** (`-k output_config_format`):

- [ ] `test_live_critique_under_output_config_format` — carried from 1.6.0, still unrun. Pins `DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS` off.
- [ ] `test_live_harvest_under_output_config_format` — **new in 1.7.0**, text-only (Sonnet 5, one flat finding object). Pins `DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS` off. The lowest-risk one to run first.
- [ ] `test_live_verify_under_output_config_format` — **new in 1.7.0**, a one-crop vision request. Pins `DRAWING_ANALYZER_VERIFY_STRUCTURED_OUTPUTS` off. Whether the flag is *worth* flipping after it passes is answered by the verification stage's new parse-loss line on a real set, not by the canary.
- [ ] `-k strict` — strict tool schemas accepted (carried from 1.6.0).

A failure on any of the three is not a release blocker — each stage's latch
degrades to the plain/fenced contract — but it keeps that default off.

## 3. Windows & path acceptance (§19.4) — ⬜ NOT RUN

- [ ] `docs/WINDOWS_ACCEPTANCE.md` completed on a real Windows machine against the built wheel. Attach the completed copy.

## 4. Bluebeam Revu & Acrobat/Chromium acceptance (§19.5) — ⬜ NOT RUN

Nothing in 1.7.0 touches the markup writer, the PDF coordinate spaces or the
receipts; the 1.6.0 record's §4 was also unrun, so there is no prior pass to
inherit. Item-by-item from the template:

In **Bluebeam Revu**:

- [ ] Markups List rows match the successful receipts in `markup_manifest.json` — not the ledger's intentions; failed/gated items appear only per their receipts.
- [ ] Every cloud/callout/tag shows the correct QC id and source sheet.
- [ ] Author, subject, contents (severity, quote, verification status, citation notes, provenance, evidence references) survive in the popup.
- [ ] Exact anchors sit on the intended text — including the rotated (90/180/270), cropped, and repeated-text sheets from the oracle set.
- [ ] Every cross-sheet leg appears only on its intended source; the duplicate-basename pair shows zero cross-contamination.
- [ ] Rejected findings appear in the index section, not inked (unless the grey opt-in was used); UNCERTAIN styling is visually distinct.
- [ ] Index rows and review-notes GOTO links navigate to the right page/region.
- [ ] Pre-existing (non-analyzer) annotations remain unchanged.
- [ ] Unicode content displays correctly.
- [ ] Save → close → reopen preserves appearance and metadata.
- [ ] Revu can filter, sort, reply to, and export the analyzer markups.

In **Acrobat** and **Chromium**:

- [ ] Appearance streams render (nothing blank): clouds, tags, callouts, leaders, links.
- [ ] Colors/severity styling match configuration; page count and original content intact.
- [ ] No annotation exists only in the Markups List but invisibly on the page, or visibly on the page but absent from receipts.

## 5. Excel & text-output acceptance (§19.6) — ⬜ NOT RUN

- [ ] `findings.csv` opens in Excel: BOM/UTF-8 honored, CRLF rows, quoting/embedded commas and newlines intact, page values and source disambiguation correct, QC ids/citation/evidence columns populated, no row corruption.
- [ ] Formula-injection payloads (`=HYPERLINK`, `+`, `-`, `@`, DDE-style) render inert (leading apostrophe), while ordinary negative numbers in numeric columns stay numeric.
- [ ] `run.log` and the Markdown exports open readably in Notepad (UTF-8, CRLF for run.log); no secret or absolute private path anywhere. **New this release:** when any verify call returned no judgment, `run.log`'s stage table and `run_manifest.json` carry the `verification: N of M live verdict calls returned no judgment (...)` warning — confirm it reads sensibly on a real set.

## 6. Performance & cost qualification (§19.7) — ⬜ NOT RUN

- [ ] `docs/PERFORMANCE_AND_COST_VALIDATION.md` record completed and attached (`benchmark_report.json` + live batch manifest).
- [ ] Regressions within owner-approved tolerance; README/UI cost claims verified. (1.7.0 changes no request that is on by default: the digest, critique, cross-QC, citation and investigation requests are byte-identical to 1.6.0, and both new structured-output paths are opt-in.)

## 7. Release checklist (§19.9) — ⚠️ PARTIAL

Kept item-by-item, verbatim from the template, as the 1.6.0 record was. Ticks
carried from 1.6.0 are marked so; nothing is ticked here that was open there
unless 1.7.0 itself produced the evidence.

### Code and correctness
- [ ] Every P0/P1 item in the plan's §5 is closed or explicitly owner-deferred in writing (list deferrals below).
- [x] Full offline suite passes on Windows and Linux — `ci.yml` run 35654462327 on `1649ba7` (all three test-matrix jobs); ⬜ re-cite on the tagged commit.
- [x] Trust gauntlet passes cold, warm, and mutated runs — hermetic suite gate.
- [x] Cross-shard conflict acceptance passes — hermetic suite gate.
- [ ] No basename-only trust key remains.
- [x] Coordinate and cache schema versions are current — `_RENDER_IDENTITY_SCHEME` v4, `_SCHEMA_VERSION` 10, `_CROSS_QC_CACHE_CONTRACT` 3, `VERIFY_PROMPT_VERSION` verify-v2, `_HARVEST_CACHE_CONTRACT` 1; none moved in 1.7.0 (checked by importing both trees, see *Release mechanics*).
- [ ] No machine block leaks into sacred prose.
- [ ] Every markup tally is receipt-derived.

### Security
- [ ] Dynamic assistant content uses safe DOM construction.
- [ ] External URL protocols are allowlisted.
- [x] Browser exploit test passes — CI `browser-security` and locally, with the executed-test floor enforced.
- [ ] Default report contains no key.
- [x] Reports, logs, diagnostics, CI, and snapshots pass secret scans — `scripts/scan_secrets.py` clean; GitGuardian green.
- [ ] Security documentation (SECURITY.md) is current.
- [x] No unresolved high/critical dependency issue lacks a time-limited documented exception — pip-audit green on `1649ba7` with no exceptions in `ci.yml`.

### Product-plan completion
- [ ] QC Markups alone invokes the full exhaustive stack.
- [ ] Profiles are visible, selectable, auto-suggested, snapshotted, and cache-sensitive.
- [ ] Deterministic auditors always run in exhaustive QC.
- [ ] Standard runs retain findings and sheet text.
- [ ] Large sets receive final reconciliation.
- [ ] Every prose item and verifier crop is accounted.
- [ ] Citation verdicts are claim-complete.
- [ ] High-severity report and severity-first index controls exist.
- [ ] `run.log` and run/markup manifests are exported.

### Manual production acceptance
- [ ] Windows path/input matrix completed (§3 above).
- [ ] Bluebeam Revu acceptance completed (§4).
- [ ] Acrobat/Chromium acceptance completed (§4).
- [ ] Excel/Notepad acceptance completed (§5).
- [ ] Synthetic oracle: 100% expected placement coverage; zero wrong-source ink.
- [ ] Representative real/redacted set passed.
- [ ] >40-sheet set passed.
- [ ] This record identifies the exact commit and application/dependency versions (§0) — ⬜ the commit SHA is the one field still open.

### Release mechanics
- [x] Version bumped and CHANGELOG finalized — both literals to 1.7.0; `[Unreleased]` promoted under `## [1.7.0] - 2026-09-21` with a fresh empty staging area (`tests/test_release_metadata.py` pins all three properties).
- [x] Cache invalidation/compatibility changes documented — **there are none for any default configuration.** Verified by importing both trees side by side (`v1.6.0` in a worktree vs this head): `DIGEST_PROMPT_VERSION` `c32a2b47…`, `CRITIQUE_PROMPT_VERSION` `4d42ab95…`, `PLANNER_PROMPT_VERSION` `c14096d7…`, `digest_cache._SCHEMA_VERSION` 10, `_CROSS_QC_CACHE_CONTRACT` 3, `_RENDER_IDENTITY_SCHEME` v4, `VERIFY_PROMPT_VERSION` verify-v2, `investigate-v3`, `_HARVEST_CACHE_CONTRACT` 1 — all byte-identical. The two new structured-output keys (`HARVEST_STRUCTURED_PROMPT_VERSION`, the verifier's `output_config.format` block) fold into their stage keys **only** when the opt-in flag is set. A 1.6.0 cache is fully warm on 1.7.0.
- [ ] Clean artifacts built from the approved commit; hashes recorded in §0.
- [x] Known-good prior release retained for rollback — 1.6.0 (`v1.6.0`, `910a8e0`).
- [ ] Release notes distinguish fixed defects, behavior changes, known limitations, and any deferred P2 items — draft in the CHANGELOG's 1.7.0 entry; ⬜ paste into the GitHub release after `publish` creates it.

## Deferrals / waivers (owner-approved, in writing)

| Item | Scope | Justification | Owner approval / date | Expiry |
|---|---|---|---|---|
| | | | | |

## Sign-off

```
Automated gates:   PASS on the merged code 1649ba7 (local run_acceptance.py,
                   build gate deferred to CI; ci.yml run 35654462327 all green).
                   Re-cite the tag run's `gates` / `gates-windows` jobs once tagged.
                   run_acceptance.py on Windows + branch-protection evidence have
                   no CI coverage and are unrecorded.
Live canary:       NOT RUN
Manual sections:   INCOMPLETE       (§§2-6 unstarted)

Stable tag:        HOLD — §§2-6 unrecorded and no waivers filed; an RC tag
                   (1.7.0rc1) is the sanctioned interim.

Release decision:  HOLD   (owner flips to SHIP once §§2-6 are recorded or
                   waived in the table above)

Owner signature: ______________________  Date: __________
```
