# Release acceptance record — 1.6.0

Copy of `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` for this candidate.

> **Status: INCOMPLETE — do not tag yet.**
> Every automated gate that has been run is green, but §1 is not yet complete
> (Windows `run_acceptance.py`, CI on the release commit, and branch-protection
> evidence are outstanding), and §§2–6 are the manual/billable gates and are
> **unstarted**: they need a real API key, a Windows machine, Bluebeam Revu,
> Excel, and an owner's eyes. §19 Definition of done: *"A release may be cut
> only when every automated gate passes and every manual section is recorded —
> passing the hermetic suite alone is not acceptance."*
>
> Every unchecked box below is a real gate, not a formality. This file is the
> permanent attestation for 1.6.0: if a box is ticked here, someone is saying
> it ran.

## 0. Release candidate identification

| Field | Value |
|---|---|
| Version (`pyproject.toml` / `drawing_analyzer.__version__`) | `1.6.0` / `1.6.0` (guard: `check_release_version.py --tag v1.6.0` OK) |
| Git commit (full SHA) | _fill at tag time — the merge commit of the release-prep PR_ |
| Date / release owner | 2026-09-15 / Abe Borg |
| Built artifacts (wheel + sdist) sha256 | wheel `e71e106fc0449e5cfe16d3fb1675295973bd2e60aa390d8f7dfaca925d26bc99`<br>sdist `22ef2f8bedcbcf6ee27c5291fa8b32b0b495e87567d5ed5622d801a35d2000f9`<br>**(built from the prep branch; rebuild and re-record from the tagged commit)** |
| Dependency lock used (`requirements-release.lock` at this commit) | **Regenerated for this release.** Blob `a38f5865c9fc934c0d5e31fcfacce96e909b259a`, file sha256 `d1d3fd739e2cbcc39ba82195fd227ca7d9f33d526fd07a41a21f32e660e4baa9`, last written by `dde7ac2` ("Bump the anthropic SDK to 1.5.0"). Diff vs `v1.5.0`: `anthropic` 1.4.0→1.5.0 plus the transitive `jiter` 0.16.0→0.17.0, `platformdirs` 4.11.7→4.11.8, `pypdf` 6.18.0→6.18.1, `regex` 2026.9.3→2026.9.10. |
| Inno Setup compiler version (the tool whose output IS the shipped installer) | **6.7.1** — observed on the prep PR's own `Build Windows installer` run ([run 34988104155](https://github.com/Abe-Borg/drawing-analyzer/actions/runs/34988104155), step "Compile installer (Inno Setup 6.7.1)"). `release.yml`'s `build` job is not tag-gated, so the installer path was exercised end to end on this tree without tagging: PyInstaller one-folder build, frozen-exe self-check, ISCC compile, `latest.json`, artifact upload — all green; the tag-gated `gates`, `gates-windows` and `publish` jobs correctly skipped. **Re-confirm on the tag run**: that build ran the version guard as `skipped` (tag-only), and a later runner image can ship a different ISCC. |
| Python / PyMuPDF / MuPDF / Anthropic SDK versions | Python 3.11.15 / PyMuPDF 1.28.2 / MuPDF 1.28.2 / anthropic 1.5.0 |
| Model ids exercised (digest / critique / verify / citation) | `claude-opus-5` / `claude-opus-5` / `claude-sonnet-5` / `claude-sonnet-5` (escalation `claude-opus-5`) |
| Web-search tool type observed by the live canary | configured `web_search_20260209` — **observed value pending §2** |

## 1. Automated gates — ⚠️ INCOMPLETE (every gate run is green; three required evidence items are missing)

> Not "COMPLETE": the template requires `run_acceptance.py` on Linux **and**
> Windows plus CI **on the release commit**, and a branch-protection check that
> needs the admin console. What is recorded below is Linux-only, CI on the
> parent commit `28a6cf9`, and no branch-protection evidence. Every gate that
> did run passed — but a section marked complete while its own boxes are open is
> how a permanent record ends up attesting to checks that never ran, so it stays
> open until the three items below have evidence.

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

- [~] Hermetic suite green on Windows (py3.11) and Linux (py3.11 + py3.12) — CI `test` matrix, run `34925367466`, **on parent commit `28a6cf9`**. Re-confirm on the release commit (the prep PR's own CI run covers the prep branch; the tag run covers the tagged commit).
- [ ] **`python scripts/run_acceptance.py` on Windows.** Only the Linux run is recorded below. The Windows leg is not redundant: path length and case handling, the `\\?\` long-path form, `os.utime`, and Credential Manager key storage are Windows-only behaviours, which is exactly why `release.yml` carries a separate `gates-windows` job.
- [x] Trust gauntlet (§19.1) green — included in the hermetic suite gate above.
- [x] Large-set cross-shard acceptance (§19.2) green — same.
- [x] PyMuPDF import isolation (I-5) green.
- [x] Headless-Chromium report exploit suite green — CI `browser-security`, and locally with the executed-test floor enforced (`check_browser_suite.py`; a skip is not a pass).
- [x] Secret scan clean (`scripts/scan_secrets.py`).
- [x] Static analysis (correctness classes) clean — `ruff check --select E9,F63,F7,F82 src tests scripts`.
- [x] Dependency vulnerability audit clean — **verified against CI, not locally.** A local `pip-audit` in a fresh venv reported `setuptools 79.0.1 / PYSEC-2026-3447`; `setuptools` is **not in `requirements-release.lock`** (it is a `build-system.requires` entry), so that finding is the audit venv's own ambient setuptools, not the shipped dependency set. The authoritative run is CI's `security-gates` step "Dependency vulnerability audit (pip-audit)" on `28a6cf9`, which installs `-c requirements-release.lock ".[dev]"` first and **passed**. No `--ignore-vuln` exception is needed or added.
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
Automated gates:   INCOMPLETE       (Linux run_acceptance.py 6/6 green, no skips;
                                     Windows run + CI-on-release-commit +
                                     branch-protection evidence outstanding)
Live canary:       NOT RUN
Manual sections:   INCOMPLETE       (§§2-6 unstarted)

Release decision:  HOLD

Owner signature: ______________________  Date: __________
```
