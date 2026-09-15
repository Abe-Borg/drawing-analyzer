# Release acceptance record — 1.6.0

Copy of `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` for this candidate.

> **Status: `v1.6.0` IS PUBLISHED. Acceptance is NOT complete.**
> The re-cut tag run ([35000474766](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766))
> went green on all four jobs and
> [the release](https://github.com/Abe-Borg/drawing-analyzer/releases/tag/v1.6.0)
> is live, marked `latest`, with `DrawingAnalyzerSetup.exe` and `latest.json`
> attached — so the installer is downloadable now and existing installs will be
> offered the update automatically.
>
> That is worth stating plainly rather than softening: **the artifact shipped
> ahead of its own acceptance.** §1 still lacks `run_acceptance.py` on Windows
> and branch-protection evidence, and §§2–6 — the live API canary, Bluebeam Revu,
> Acrobat/Chromium, Excel, and performance/cost — are **unstarted**. They need a
> real API key, a Windows machine, licensed desktop software and an owner's eyes.
> §19 Definition of done: *"A release may be cut only when every automated gate
> passes and every manual section is recorded — passing the hermetic suite alone
> is not acceptance."* By that standard this release is out ahead of its record,
> and the remaining sections are now catch-up rather than gating.
>
> Every unchecked box below is a real gate, not a formality. This file is the
> permanent attestation for 1.6.0: if a box is ticked here, someone is saying
> it ran.

## 0. Release candidate identification

| Field | Value |
|---|---|
| Version (`pyproject.toml` / `drawing_analyzer.__version__`) | `1.6.0` / `1.6.0` (guard: `check_release_version.py --tag v1.6.0` OK) |
| Git commit (full SHA) | `05cc332eb74cdabc2e1ed833229900ae14f7f414` — the merge of #144 (the pip-audit gate fix), and `main`'s head. **Not** `2058975`, which the first `v1.6.0` tag pointed at and which failed to publish; the tag was moved after nothing had ever been released from it. |
| Date / release owner | 2026-09-15 / Abe Borg |
| Built artifacts sha256 | **Shipped installer** (the artifact users actually receive), from the published release: `DrawingAnalyzerSetup.exe` sha256 `d69d57de97831b5ff35fd60cb74677da756d63e91c5636313ae95cab4bf1a685` (39,999,657 bytes); `latest.json` sha256 `8f3c594af8873a96648f914cfadbdc7d02dfc7801954d65e80666c7264cca707`.<br>Wheel/sdist recorded earlier (`e71e106f…` / `22ef2f8b…`) were built from the prep branch and are **not** the released artifacts — kept only as a provenance note. |
| Dependency lock used (`requirements-release.lock` at this commit) | **Regenerated for this release.** Blob `a38f5865c9fc934c0d5e31fcfacce96e909b259a`, file sha256 `d1d3fd739e2cbcc39ba82195fd227ca7d9f33d526fd07a41a21f32e660e4baa9`, last written by `dde7ac2` ("Bump the anthropic SDK to 1.5.0"). Diff vs `v1.5.0`: `anthropic` 1.4.0→1.5.0 plus the transitive `jiter` 0.16.0→0.17.0, `platformdirs` 4.11.7→4.11.8, `pypdf` 6.18.0→6.18.1, `regex` 2026.9.3→2026.9.10. |
| Inno Setup compiler version (the tool whose output IS the shipped installer) | **6.7.1 — confirmed on the publishing tag run** ([35000474766](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766), step "Compile installer (Inno Setup 6.7.1)"), same as first observed on the prep PR's own `Build Windows installer` run ([run 34988104155](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/34988104155), step "Compile installer (Inno Setup 6.7.1)"). `release.yml`'s `build` job is not tag-gated, so the installer path was exercised end to end on this tree without tagging: PyInstaller one-folder build, frozen-exe self-check, ISCC compile, `latest.json`, artifact upload — all green; the tag-gated `gates`, `gates-windows` and `publish` jobs correctly skipped. Both caveats that made the prep run insufficient on its own are now closed by the tag run: that build ran the version guard as `skipped` (tag-only) and a later runner image can ship a different ISCC, whereas on `05cc332` the guard **passed** and ISCC was still 6.7.1. |
| Python / PyMuPDF / MuPDF / Anthropic SDK versions | Python 3.11.15 / PyMuPDF 1.28.2 / MuPDF 1.28.2 / anthropic 1.5.0 |
| Model ids exercised (digest / critique / verify / citation) | `claude-opus-5` / `claude-opus-5` / `claude-sonnet-5` / `claude-sonnet-5` (escalation `claude-opus-5`) |
| Web-search tool type observed by the live canary | configured `web_search_20260209` — **observed value pending §2** |

## 1. Automated gates — ⚠️ PARTIAL (all CI gates green on the released commit; two items have no CI coverage)

> Every automated gate now passes on the released commit `05cc332`, including
> the dependency vulnerability audit that failed the first tag attempt. That is
> what let `publish` run.
>
> Two items remain and neither is a CI failure — they are things CI does not
> cover at all: `run_acceptance.py` on **Windows** (no job runs it; the
> `gates-windows` job runs the hermetic suite, which is a different thing) and
> branch-protection evidence, which needs the admin console.
>
> History worth keeping, because both errors ran the same direction: this
> section once read "COMPLETE" while its own boxes were open, and later "every
> gate run is green" after one had failed. An attestation that overstates is
> worse than none, and this release is a live case of why — the record said the
> audit was clean for hours before the gate proved it was not.

`python scripts/run_acceptance.py` on Linux, all six gates PASS with **no skips**
(Chromium and the build tooling were installed so the browser and build gates
executed rather than short-circuiting):

```
  byte-compile                     PASS
  import isolation (I-5)           PASS
  hermetic suite + trust gauntlet  PASS
  secret scan                      PASS
  browser security                 PASS
  build + clean-install smoke      PASS
```

That transcript is the **local** Linux run from the prep branch, so it carries no
commit of its own. The same script passed in CI on the released commit: `release.yml`
run [35000474766](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766),
job [`Release gates (full automated suite)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766/job/104487333669),
step "Phase 27 release gates (all of them)" — with Chromium installed there too, so the
browser gate could not short-circuit. That job is the one whose green run let `publish`
proceed.

- [x] Hermetic suite green on Windows (py3.11) and Linux (py3.11 + py3.12) — evidenced **on the released commit `05cc332`** by the tag's own `ci.yml` run, [35000474696](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474696): all six jobs green, including [`tests (ubuntu-latest, py3.12)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474696/job/104487333998), [`tests (ubuntu-latest, py3.11)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474696/job/104487333932) and [`tests (windows-latest, py3.11)`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474696/job/104487333788). Cited deliberately rather than `release.yml`'s `gates`, which pins `python-version: "3.11"` and so cannot evidence py3.12 at all. `release.yml`'s `gates-windows` separately passed the Windows hermetic suite + I-5 on the same commit ([job](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766/job/104487333896), steps "PyMuPDF import isolation (I-5)" and "Hermetic test suite").

  Two drafts got this row wrong in the same spot, and both are worth keeping. The first credited `release.yml`'s `gates` with the py3.12 leg it cannot run. The second fixed that but cited run [34995155028](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/34995155028) on **`2058975`** — real evidence of the wrong commit. `2058975` was the first `v1.6.0` tag target, which never published; citing it here had the box attesting full-matrix coverage of the shipped build from a run of a superseded one. The matrix genuinely did run on `05cc332`, so the box stays ticked — against the run that actually tested what shipped.
- [x] Windows installer path green **on the released commit `05cc332`** — `release.yml` run [35000474766](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766), job [`Build Windows installer`](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766/job/104487333780): the version guard (tag vs both literals) **passed** — not skipped — then PyInstaller build, frozen-exe self-check, Inno Setup **6.7.1** compile, `latest.json`, artifact upload. This row previously read "same run" and so inherited the row above's citation of `2058975`, which is both the wrong commit and the attempt whose `gates` job failed.
- [ ] **`python scripts/run_acceptance.py` on Windows.** Only the Linux run is recorded above. The Windows leg is not redundant: path length and case handling, the `\\?\` long-path form, `os.utime`, and Credential Manager key storage are Windows-only behaviours, which is exactly why `release.yml` carries a separate `gates-windows` job.
- [x] Trust gauntlet (§19.1) green — included in the hermetic suite gate above.
- [x] Large-set cross-shard acceptance (§19.2) green — same.
- [x] PyMuPDF import isolation (I-5) green.
- [x] Headless-Chromium report exploit suite green — CI `browser-security`, and locally with the executed-test floor enforced (`check_browser_suite.py`; a skip is not a pass).
- [x] Secret scan clean (`scripts/scan_secrets.py`).
- [x] Static analysis (correctness classes) clean — `ruff check --select E9,F63,F7,F82 src tests scripts`.
- [x] **Dependency vulnerability audit clean on the released commit** — green in `release.yml`'s `gates` job, step "Dependency vulnerability audit (pip-audit)", on `05cc332` ([run 35000474766](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/35000474766)).

  It got here the hard way, and the history belongs in the record. `setuptools 79.0.1 / PYSEC-2026-3447` (fix: 83.0.0) **failed** the first tag attempt on `2058975` ([run 34995154773](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/34995154773)), so `publish` was skipped and nothing shipped. An earlier draft of this record had dismissed the identical finding as "the audit venv's own ambient setuptools, not the shipped dependency set" — the premise was right and the conclusion did not follow. `setuptools` genuinely is absent from `requirements-release.lock` (`pip freeze` excludes it by default), but `pip-audit --skip-editable` skips the **editable install** — this package — and audits every other installed distribution, ambient ones included. An unpinned setuptools was always in scope and really is part of the release toolchain.

  Fixed by upgrading rather than excepting (#144): both audit jobs now `pip install "setuptools==84.0.0"` before auditing, pinned exactly like every other CI tool in `ci.yml` rather than a `>=` floor that would resolve to whatever is newest at run time. No `--ignore-vuln` exception was added and none is needed under `ci.yml`'s header policy.

- [x] Dependency license / AGPL-notice audit clean — `scripts/check_licenses.py`, 70 distributions.
- [x] Wheel/sdist build + twine check + clean-venv install smoke green — locally and CI `build`.
- [ ] **Branch protection names `test`, `browser-security`, `security-gates`, `build` as required checks** (admin console — record who verified). *Not verifiable from here; needs the repo admin UI.*
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

**New in 1.6.0 — two canaries added this release, and both gate a default:**

- [ ] `-k output_config_format` — does `output_config.format` hold on a **vision**
      request? Anthropic documents citations and prefill as the only
      incompatibilities and says nothing either way about image inputs, while
      every critique request carries an overview plus a full tile grid. This is
      the single claim in 1.6.0 resting on undocumented behaviour. **Until it
      passes, `DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS` must stay off by
      default** (it is). A failure here is not a release blocker — the latch
      degrades to the fenced contract — but it does pin the default.
- [ ] `-k strict` — are the rewritten strict tool schemas accepted? A failure
      costs one wasted round trip per run via the latch, not correctness.

## 3. Windows & path acceptance (§19.4) — ⬜ NOT RUN

- [ ] `docs/WINDOWS_ACCEPTANCE.md` completed on a real Windows machine against the built wheel.

## 4. Bluebeam Revu & Acrobat/Chromium acceptance (§19.5) — ⬜ NOT RUN

Use the synthetic oracle set (exportable via `tests/fixtures/gauntlet.py`) **and**
a representative approved real/redacted set. Open every `*_reviewed.pdf` and
`Drawing_Set_Review_Notes.pdf`.

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
- [ ] `run.log` and the Markdown exports open readably in Notepad (UTF-8, CRLF for run.log); no secret or absolute private path anywhere.

## 6. Performance & cost qualification (§19.7) — ⬜ NOT RUN

- [ ] `docs/PERFORMANCE_AND_COST_VALIDATION.md` record completed and attached (`benchmark_report.json` + live batch manifest).
- [ ] Regressions within owner-approved tolerance; README/UI cost claims verified.

## 7. Release checklist (§19.9) — ⚠️ PARTIAL

Kept item-by-item, verbatim from the template. An earlier draft of this record
collapsed most of it into a summary sentence; that removes the very fields a
completed record exists to carry — the representative real set, the >40-sheet
run, the security-documentation review, the product invariants — so that once
the status flips to SHIP nothing could show which of them actually passed.

### Code and correctness
- [ ] Every P0/P1 item in the plan's §5 is closed or explicitly owner-deferred in writing (list deferrals below).
- [ ] Full offline suite passes on Windows and Linux.
- [x] Trust gauntlet passes cold, warm, and mutated runs — hermetic suite gate.
- [x] Cross-shard conflict acceptance passes — hermetic suite gate.
- [ ] No basename-only trust key remains.
- [x] Coordinate and cache schema versions are current — `_RENDER_IDENTITY_SCHEME` v4, `_SCHEMA_VERSION` 10, `_CROSS_QC_CACHE_CONTRACT` 3; none moved in 1.6.0.
- [ ] No machine block leaks into sacred prose.
- [ ] Every markup tally is receipt-derived.

### Security
- [ ] Dynamic assistant content uses safe DOM construction.
- [ ] External URL protocols are allowlisted.
- [x] Browser exploit test passes — CI `browser-security` and locally, with the executed-test floor enforced.
- [ ] Default report contains no key.
- [x] Reports, logs, diagnostics, CI, and snapshots pass secret scans — `scripts/scan_secrets.py` clean; GitGuardian green.
- [ ] Security documentation (SECURITY.md) is current.
- [ ] No unresolved high/critical dependency issue lacks a time-limited documented exception.

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
- [ ] This record identifies the exact commit and application/dependency versions (§0).

### Release mechanics
- [x] Version bumped and CHANGELOG finalized — both literals to 1.6.0; `[Unreleased]` promoted under `## [1.6.0] - 2026-09-15` with a fresh empty staging area (`tests/test_release_metadata.py` pins all three properties).
- [x] Cache invalidation/compatibility changes documented — **there are none.** `DIGEST_PROMPT_VERSION` and `CRITIQUE_PROMPT_VERSION` are byte-identical to 1.5.0, `digest_cache._SCHEMA_VERSION` stays at 10, and the new `structured_key` folds into the critique keys only when the opt-in flag is set. A 1.5.0 cache is fully warm on 1.6.0.
- [ ] Clean artifacts built from the approved commit; hashes recorded in §0.
- [x] Known-good prior release retained for rollback — 1.5.0 (`v1.5.0`).
- [ ] Release notes distinguish fixed defects, behavior changes, known limitations, and any deferred P2 items.

## Deferrals / waivers (owner-approved, in writing)

| Item | Scope | Justification | Owner approval / date | Expiry |
|---|---|---|---|---|
| | | | | |

## Sign-off

```
Automated gates:   PASS on the released commit 05cc332 (all four tag-run jobs
                   green, incl. the pip-audit step that failed the first attempt).
                   run_acceptance.py on Windows + branch-protection evidence have
                   no CI coverage and are still unrecorded.
Live canary:       NOT RUN
Manual sections:   INCOMPLETE       (§§2-6 unstarted)

Release decision:  SHIPPED 2026-09-15 17:23:55Z, ahead of §§2-6.
                   Complete them as catch-up; they no longer gate.

Owner signature: ______________________  Date: __________
```
