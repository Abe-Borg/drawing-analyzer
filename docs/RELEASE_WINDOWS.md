# Releasing the Windows desktop app

This is the runbook for packaging Drawing Analyzer as a downloadable Windows app
and shipping updates to installed users. It is written to be followed
step-by-step; you don't need to remember any of it between releases.

## The big picture (no server required)

Drawing Analyzer is a **desktop app**, like VS Code. It runs entirely on the
user's PC and talks only to the Anthropic API with the user's own key. There is
**no backend to host** — no DigitalOcean droplet, no always-on service, nothing
to pay for month to month.

Two free pieces of GitHub infrastructure do all the work:

- **GitHub Actions** builds the Windows installer (you don't need a Windows
  machine).
- **GitHub Releases** hosts the installer file *and* a tiny `latest.json`
  manifest that installed apps read to discover updates.

```
  You: git tag v1.2.3 && git push origin v1.2.3
        │
        ▼
  GitHub Actions (windows runner)
    • PyInstaller  → dist/DrawingAnalyzer/  (the frozen app)
    • self-check   → prove the exe actually runs
    • Inno Setup   → DrawingAnalyzerSetup.exe
    • make_manifest→ latest.json  (version + download URL + sha256)
    • gates        → the full automated suite, Linux and Windows
    • acceptance   → docs/releases/ACCEPTANCE-1.2.3.md must say SHIP
                     (stable tags only; an rcN tag publishes as a pre-release)
        │
        ▼
  GitHub Release  v1.2.3
    • DrawingAnalyzerSetup.exe   ← users download this
    • latest.json                ← installed apps poll this
        │
        ▼
  Installed apps  →  fetch releases/latest/download/latest.json  →
                     "v1.2.3 is available"  →  download + verify sha256  →  run installer
```

## Cutting a release

1. **Bump the version in both places** (a test keeps them in lockstep, so a
   mismatch fails CI):
   - `pyproject.toml` → `project.version`
   - `src/drawing_analyzer/__init__.py` → `__version__`

   Versions are `MAJOR.MINOR.PATCH` with an optional `rcN` suffix (e.g. `1.0.0`
   or `1.0.0rc2`). A final release always supersedes its own release
   candidates.

2. **Commit** the bump on `main` (via a normal PR).

3. **A stable version needs its acceptance record to say SHIP.** Before you tag
   `v1.2.3`, the commit you tag must carry `docs/releases/ACCEPTANCE-1.2.3.md`
   (a copy of `docs/RELEASE_ACCEPTANCE_TEMPLATE.md`, titled
   `# Release acceptance record — 1.2.3`) that meets both of these:
   - its Sign-off's `Release decision:` reads `SHIP`;
   - every row of its *Deferrals / waivers* table is complete, with an `Expiry`
     date (`YYYY-MM-DD`) that has not passed.

   Otherwise the workflow's `acceptance` job fails and **nothing is
   published**. Check it before tagging:
   ```bash
   python scripts/check_release_acceptance.py --tag v1.2.3
   ```
   A release candidate (`v1.2.3rc1`) needs no record; see the note below.

4. **Tag and push:**
   ```bash
   git tag v1.2.3
   git push origin v1.2.3
   ```
   The tag must be `v` + the exact version (`v1.2.3` for version `1.2.3`). The
   workflow refuses to publish if the tag and `pyproject.toml` disagree.

5. **Wait for the `Release (Windows installer)` workflow** to finish. Once the
   repository's `release` environment has required reviewers (see
   [The publish boundary](#the-publish-boundary)), the `publish` job waits for a
   reviewer to approve the deployment. Approval is the last human check before
   installed copies are offered the release. The job creates the GitHub Release
   with `DrawingAnalyzerSetup.exe` and `latest.json` attached. That's it —
   installed apps will offer the update within a day, or immediately when a user
   clicks **Check for Updates**.

6. **(Recommended) Edit the release notes** on GitHub to describe what changed.
   The `notes` string in `latest.json` is what shows in the app's update dialog;
   by default it points users to the release page.

> **Release candidates are handled for you.** A tag with an `rcN` suffix
> (`v1.0.0rc1`) is published as a GitHub **pre-release** automatically, so GitHub
> never marks it "latest". The updater reads
> `releases/latest/download/latest.json`, which always resolves to the newest
> **full** release — so stable installs are never auto-offered a release
> candidate. Testers can still install an RC by downloading it from its release
> page directly. An RC tag needs no acceptance record, which makes it the way to
> get a build to testers while the stable record still says HOLD. Set both
> version literals to `1.2.3rc1` for it: the tag must match them.

## The publish boundary

A stable release goes to every installed copy within a day, so it is gated on
the acceptance record rather than on a green test run. This matters: 1.6.0
shipped ahead of its record, and 1.7.0 was published about eight minutes after
its record merged saying HOLD (remediation finding N8). `release.yml` now has
two layers:

- **The `acceptance` job** reads `docs/releases/ACCEPTANCE-<version>.md` from
  the tagged commit through `scripts/check_release_acceptance.py`, and decides
  the channel once. An RC tag publishes as a pre-release. A stable tag publishes
  as `latest` only if the record says SHIP with no expired or incomplete waiver.
  `publish` needs this job, and it takes the channel from the job's output
  instead of re-deriving it from the tag. `publish` uploads the installer into
  a **draft** release, which nobody outside the repository can see, and makes
  it public in one final step. It checks the earliest waiver expiry before the
  upload and again just before that final step, since an approval can come
  days later. If a run fails partway, re-running it finishes the draft.
- **The `release` environment** on the `publish` job. A tag runs the workflow
  file *from the tagged commit*, so the first layer only stops accidents: a
  commit could change the workflow itself. What a tag cannot change is the
  environment's protection, which lives in the repository settings: required
  reviewers, and a deployment rule that allows only `v*` tags. A tag ruleset
  that restricts who may create, move or delete `v*` tags closes the rest,
  including a tag pushed at an older commit whose workflow predates both
  layers.

**The `environment:` line proves nothing on its own.** GitHub creates an
environment the first time a workflow names it, *with no protection*. The
protection has to be configured by a repository admin and confirmed through
the API (for example `GET /repos/{owner}/{repo}/environments/release`, whose
`protection_rules` must list the required reviewers). Until that is done, the
acceptance job is the only gate.

## What CI validates on every PR (before you ever tag)

The same workflow runs on pull requests that touch packaging files
(`packaging/windows/**`, `release.yml`, `updates.py`, `pyproject.toml`). On a PR
the read-only `build` job builds and self-checks the app and compiles the
installer **without publishing** (only the tag-gated `publish` job can write to
the repo), and it uploads the installer as a downloadable artifact. So you can:

- confirm the Windows build still works before merging, and
- download and hand-test the actual installer from the PR's workflow run.

The self-check step runs the frozen `DrawingAnalyzer.exe --selfcheck`, which
imports the engine, the GUI toolkit, and the updater inside the frozen app. This
catches the #1 PyInstaller failure mode — a dependency that imports fine from
source but was never bundled into the exe.

## Building locally (optional)

You need a Windows machine with Python 3.11+.

```powershell
pip install -e ".[gui]" pyinstaller
pyinstaller packaging/windows/drawing-analyzer.spec --noconfirm --clean
dist\DrawingAnalyzer\DrawingAnalyzer.exe --selfcheck   # sanity check

# Then build the installer (install Inno Setup 6 first: https://jrsoftware.org/):
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.2.3 packaging\windows\installer.iss
# → dist\installer\DrawingAnalyzerSetup.exe
```

## The pieces (what each file does)

| File | Role |
|---|---|
| `packaging/windows/app_entry.py` | The frozen app's entry point; adds `--version` / `--selfcheck` flags for CI. |
| `packaging/windows/drawing-analyzer.spec` | PyInstaller recipe. Bundles customtkinter/tkinterdnd2 assets and keyring's Windows backend (the imports PyInstaller can't discover on its own). |
| `packaging/windows/installer.iss` | Inno Setup script → `DrawingAnalyzerSetup.exe`. Per-user install (no admin), Start-menu shortcut, clean uninstaller, closes a running instance on update. |
| `packaging/windows/make_manifest.py` | Writes `latest.json` (version, download URL, sha256). Round-tripped against the app's parser in `tests/test_updates.py`. |
| `src/drawing_analyzer/core/updates.py` | The in-app updater: fetch manifest → compare → download → verify sha256 → launch installer. Fully unit-tested, no network in tests. |
| `.github/workflows/release.yml` | Ties it together: a read-only `build` job (every relevant PR + tag), the tag-only `gates`, `gates-windows` and `acceptance` jobs, and a write-scoped, tag-only `publish` job that needs all four and deploys to the `release` environment. RC tags publish as pre-releases. |
| `scripts/check_release_acceptance.py` | The publish gate the `acceptance` job runs. It decides the channel from the tag and reads the stable tag's `docs/releases/ACCEPTANCE-<version>.md` (the Sign-off decision and the waiver table). Standard library only; unit-tested in `tests/test_release_acceptance_gate.py`. |

## The code-signing situation (why users see a SmartScreen warning)

The app is shipped **unsigned** — there is no paid OS code-signing certificate.
The consequence, and *only* the consequence, is cosmetic: Windows SmartScreen
shows a **"Windows protected your PC / unrecognized app"** notice on the first
install and on each update. Users click **More info → Run anyway**. It does not
block anything.

This is a deliberate, documented trade-off, not a security hole. Note the two
*different* things both called "signing":

- **OS code-signing (skipped, the paid one)** — a certificate that makes the
  SmartScreen notice go away. ~$200–400/yr for Windows. Not used.
- **Update-integrity signing (used, free)** — the SHA-256 in `latest.json`,
  which the app verifies before running any downloaded installer. This is what
  actually protects users from a tampered download, and it costs nothing.

### If you later want to remove the SmartScreen warning

Buy an OV/EV code-signing certificate, then add a signing step to
`release.yml` after the Inno Setup compile (sign both `DrawingAnalyzer.exe`
inside the bundle and the final `DrawingAnalyzerSetup.exe` with `signtool`).
Nothing else about this pipeline has to change.

## Moving the repository

If the repo ever moves, update the owner/name in **one** place —
`GITHUB_OWNER` / `GITHUB_REPO` in `src/drawing_analyzer/core/updates.py` — and
the manifest and releases-page URLs follow. (The workflow derives URLs from
`${{ github.repository }}` automatically.)
