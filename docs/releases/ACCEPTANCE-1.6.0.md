# Release acceptance record — 1.6.0

Copy of `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` for this candidate.

> **Status: INCOMPLETE — do not tag yet.**
> Section 1 is complete and green. Sections 2–6 are the manual/billable gates
> and are **unstarted**: they need a real API key, a Windows machine, Bluebeam
> Revu, Excel, and an owner's eyes. §19 Definition of done: *"A release may be
> cut only when every automated gate passes and every manual section is
> recorded — passing the hermetic suite alone is not acceptance."*

## 0. Release candidate identification

| Field | Value |
|---|---|
| Version (`pyproject.toml` / `drawing_analyzer.__version__`) | `1.6.0` / `1.6.0` (guard: `check_release_version.py --tag v1.6.0` OK) |
| Git commit (full SHA) | _fill at tag time — the merge commit of the release-prep PR_ |
| Date / release owner | 2026-09-15 / Abe Borg |
| Built artifacts (wheel + sdist) sha256 | wheel `e71e106fc0449e5cfe16d3fb1675295973bd2e60aa390d8f7dfaca925d26bc99`<br>sdist `22ef2f8bedcbcf6ee27c5291fa8b32b0b495e87567d5ed5622d801a35d2000f9`<br>**(built from the prep branch; rebuild and re-record from the tagged commit)** |
| Dependency lock used (`requirements-release.lock` at this commit) | ☑ unchanged since 1.5.0; clean resolve verified |
| Inno Setup compiler version | _fill from the `build` job summary on the tag run_ |
| Python / PyMuPDF / MuPDF / Anthropic SDK versions | Python 3.11.15 / PyMuPDF 1.28.2 / MuPDF 1.28.2 / anthropic 1.5.0 |
| Model ids exercised (digest / critique / verify / citation) | `claude-opus-5` / `claude-opus-5` / `claude-sonnet-5` / `claude-sonnet-5` (escalation `claude-opus-5`) |
| Web-search tool type observed by the live canary | configured `web_search_20260209` — **observed value pending §2** |

## 1. Automated gates — ✅ COMPLETE

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

- [x] Hermetic suite green on Windows (py3.11) and Linux (py3.11 + py3.12) — CI `test` matrix, run `34925367466` on `28a6cf9`.
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

Requires licensed desktop software and human inspection of the reviewed PDFs.
See the template for the full item list.

## 5. Excel & text-output acceptance (§19.6) — ⬜ NOT RUN

## 6. Performance & cost qualification (§19.7) — ⬜ NOT RUN

- [ ] `docs/PERFORMANCE_AND_COST_VALIDATION.md` record completed and attached.

## 7. Release checklist (§19.9)

### Release mechanics
- [x] Version bumped (both literals) and CHANGELOG finalized — `[Unreleased]` promoted under `## [1.6.0] - 2026-09-15`, with a fresh empty staging area above it (`tests/test_release_metadata.py` pins all three properties).
- [x] Cache invalidation/compatibility changes documented — **there are none.** 1.6.0 invalidates no cache: `DIGEST_PROMPT_VERSION` and `CRITIQUE_PROMPT_VERSION` are byte-identical to 1.5.0, `digest_cache._SCHEMA_VERSION` stays at 10, and the new `structured_key` folds into the critique keys only when the opt-in flag is set. A 1.5.0 cache is fully warm on 1.6.0.
- [x] Clean artifacts built; hashes recorded in §0 (rebuild from the tagged commit).
- [x] Known-good prior release retained for rollback — 1.5.0.
- [ ] Release notes distinguish fixed defects, behavior changes, known limitations, and deferred items — CHANGELOG entry written; confirm at tag time.

### Everything else in §7
Sections covering manual production acceptance mirror §§3–6 and are equally
unstarted. The code/correctness and security subsections are covered by §1
above except where they name an admin-console or human-inspection step.

## Deferrals / waivers (owner-approved, in writing)

| Item | Scope | Justification | Owner approval / date | Expiry |
|---|---|---|---|---|
| | | | | |

## Sign-off

```
Automated gates:   PASS             (run_acceptance.py, 6/6, no skips)
Live canary:       NOT RUN
Manual sections:   INCOMPLETE       (§§2-6 unstarted)

Release decision:  HOLD

Owner signature: ______________________  Date: __________
```
