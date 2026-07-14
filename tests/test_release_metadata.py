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

import drawing_analyzer

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert drawing_analyzer.__version__ == pyproject["project"]["version"]


def test_version_is_pep440ish_release_candidate_or_final():
    # Guard against placeholder versions reaching a release branch.
    import re

    assert re.fullmatch(r"\d+\.\d+\.\d+(rc\d+)?", drawing_analyzer.__version__), (
        drawing_analyzer.__version__
    )
