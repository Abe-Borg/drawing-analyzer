#!/usr/bin/env python3
"""Repo secret scan — a §19.8 release gate (also wired into CI).

Scans every *tracked* text file for credential-shaped strings: real-looking
Anthropic keys (``sk-ant-`` + a long tail — the short obviously-fake fixtures
used by the redaction tests do not match), cloud/provider token shapes, and
long literal assignments to credential-named variables. Exit code 0 = clean,
1 = findings (printed with file:line), 2 = could not scan.

Pure stdlib and Windows-safe; runs identically in CI, in
``scripts/run_acceptance.py``, and by hand:

    python scripts/scan_secrets.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Credential shapes. Length floors keep deliberately-fake test fixtures
# (e.g. ``sk-ant-secure``) out while any real key still matches.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{30,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "literal credential assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|auth[_-]?token|client[_-]?secret|password)\b"
            r"""\s*[:=]\s*["'][A-Za-z0-9+/_\-]{32,}["']"""
        ),
    ),
]

# Exact strings that are documented, deliberate fakes (add sparingly; every
# entry needs an obvious in-repo justification).
ALLOWLIST: frozenset[str] = frozenset()

_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".woff", ".woff2",
    ".ttf", ".zip", ".whl", ".gz", ".pyc",
}


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    )
    return [
        REPO_ROOT / name
        for name in out.stdout.decode("utf-8", "replace").split("\0")
        if name
    ]


def main() -> int:
    try:
        files = _tracked_files()
    except Exception as exc:  # noqa: BLE001
        print(f"secret scan: could not list tracked files: {exc}", file=sys.stderr)
        return 2

    findings: list[str] = []
    for path in files:
        if path.suffix.lower() in _BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"secret scan: unreadable {path}: {exc}", file=sys.stderr)
            return 2
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                for match in pattern.finditer(line):
                    if match.group(0) in ALLOWLIST:
                        continue
                    rel = path.relative_to(REPO_ROOT)
                    findings.append(f"{rel}:{lineno}: {label}: {match.group(0)[:24]}…")

    if findings:
        print("secret scan: FAILED — credential-shaped strings found:")
        for f in findings:
            print(f"  {f}")
        return 1
    print(f"secret scan: clean ({len(files)} tracked files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
