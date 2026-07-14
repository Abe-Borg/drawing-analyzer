#!/usr/bin/env python3
"""Dependency-license / distribution audit — a §19.8 release gate.

Walks every distribution installed in the current environment, prints a
license table, and fails when:

- any distribution exposes no license metadata at all (UNKNOWN), or
- the project's own AGPL obligations are not visibly met (a LICENSE file at
  the repo root and an AGPL licensing note in README.md — PyMuPDF is AGPL,
  and the README's licensing story depends on the I-5 isolation).

Pure stdlib (``importlib.metadata``); run it inside the environment whose
dependency set you are auditing (CI runs it in the job venv):

    python scripts/check_licenses.py
"""
from __future__ import annotations

import sys
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Environment/tooling distributions that are not part of the shipped
# dependency tree (present in CI job venvs).
_IGNORED = {"pip", "setuptools", "wheel", "build", "pyproject_hooks", "twine"}


def _license_of(dist: metadata.Distribution) -> str:
    md = dist.metadata
    for key in ("License-Expression", "License"):
        value = (md.get(key) or "").strip()
        # Some projects stuff the whole license text into License; keep it short.
        if value and value.upper() != "UNKNOWN" and len(value) < 120:
            return value
    classifiers = [
        c.split("::")[-1].strip()
        for c in md.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    if classifiers:
        return "; ".join(sorted(set(classifiers)))
    value = (md.get("License") or "").strip()
    if value and value.upper() != "UNKNOWN":
        return value.splitlines()[0][:80] + "…"
    return "UNKNOWN"


def main() -> int:
    rows: list[tuple[str, str, str]] = []
    unknown: list[str] = []
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").strip()
        if not name or name.lower().replace("-", "_") in {
            i.replace("-", "_") for i in _IGNORED
        }:
            continue
        lic = _license_of(dist)
        rows.append((name, dist.version, lic))
        if lic == "UNKNOWN":
            unknown.append(name)

    rows.sort(key=lambda r: r[0].lower())
    width = max((len(r[0]) for r in rows), default=10)
    print(f"{'distribution'.ljust(width)}  version      license")
    for name, version, lic in rows:
        print(f"{name.ljust(width)}  {version.ljust(11)}  {lic}")

    failures: list[str] = []
    if unknown:
        failures.append(f"distributions without license metadata: {', '.join(unknown)}")
    if not (REPO_ROOT / "LICENSE").is_file():
        failures.append("repo LICENSE file is missing")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    if "AGPL" not in readme:
        failures.append("README.md no longer documents the AGPL licensing obligations")

    if failures:
        print("\nlicense audit: FAILED")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nlicense audit: clean ({len(rows)} distributions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
