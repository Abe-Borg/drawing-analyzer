"""Phase 27 — release-metadata consistency (§19.9 release mechanics).

The version literal lives in two places (``pyproject.toml`` and
``drawing_analyzer.__version__``); ``run.log``/``run_manifest.json`` report a
third (installed distribution metadata). These must agree at release time —
this test pins the two source-tree literals together so they cannot drift, and
the release checklist covers the installed-metadata leg via the built wheel.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

import drawing_analyzer

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_runtime_and_release_shared_dependency_pins_match():
    """Release builds and requirements installs must exercise the same pins.

    GUI-only and dev-only dependencies may differ, but shared dependencies
    must not silently keep the release on an older SDK or transport stack.
    Actual resolver compatibility is checked by CI's requirements install.
    """
    def pins(filename):
        result = {}
        for line in (_REPO_ROOT / filename).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                requirement = Requirement(line)
                name = canonicalize_name(requirement.name)
                result[name] = str(requirement.specifier)
        return result

    runtime = pins("requirements.txt")
    release = pins("requirements-release.lock")
    shared = runtime.keys() & release.keys()
    assert shared, "runtime and release files have no shared dependency pins"
    drift = {
        name: (runtime[name], release[name])
        for name in shared if runtime[name] != release[name]
    }
    assert not drift, f"runtime/release dependency pin drift: {drift}"


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert drawing_analyzer.__version__ == pyproject["project"]["version"]


def test_version_is_pep440ish_release_candidate_or_final():
    # Guard against placeholder versions reaching a release branch.
    import re

    assert re.fullmatch(r"\d+\.\d+\.\d+(rc\d+)?", drawing_analyzer.__version__), (
        drawing_analyzer.__version__
    )


def _changelog_headings() -> list[str]:
    """Every ``## [...]`` heading in CHANGELOG.md, in file order."""
    import re

    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"^## \[.*$", text, re.MULTILINE)


def test_changelog_keeps_an_unreleased_staging_area():
    """The first version heading must be ``[Unreleased]`` (Codex review, 1.5.0).

    Every corrective package appends its bullets under the *topmost* ``### Fixed``.
    Without an empty ``[Unreleased]`` above the newest dated release, the next
    package's work lands inside a section describing a version that already
    shipped — and `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` says to *move* the
    contents under the tagged version, not the heading. This repository has paid
    for changelog-structure drift twice already (orphaned ``### Fixed`` headings
    before 1.4.0, then this), so it is pinned rather than remembered.
    """
    headings = _changelog_headings()
    assert headings, "CHANGELOG.md has no version headings"
    assert headings[0] == "## [Unreleased]", headings[:2]


def test_the_newest_dated_release_is_the_current_version():
    """``__version__`` and the top dated section must name the same release.

    True continuously, not only at release time: a cut promotes ``[Unreleased]``
    and bumps both literals together, and nothing between releases touches
    either. So a half-finished cut — literals bumped without the changelog, or
    the reverse — fails here.
    """
    import re

    dated = [h for h in _changelog_headings() if h != "## [Unreleased]"]
    assert dated, "CHANGELOG.md has no dated release section"
    match = re.match(r"^## \[([^\]]+)\] - \d{4}-\d{2}-\d{2}$", dated[0])
    assert match, f"the newest release heading is malformed: {dated[0]!r}"
    assert match.group(1) == drawing_analyzer.__version__, (
        f"changelog names {match.group(1)}, __version__ is "
        f"{drawing_analyzer.__version__}"
    )
