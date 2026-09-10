#!/usr/bin/env python3
"""Fail when the mandatory browser exploit suite verified nothing (P9 item 42).

CI runs ``pytest -m browser`` as a required check, and the repo's own CI comment
calls it "the mandatory headless-Chromium report exploit suite" because a DOM
emulator cannot prove CSP, ``file://`` behaviour, or real event execution. But
every one of those tests skips itself when the browser will not start:

    with sync_playwright() as p:
        try:
            b = _launch(p)
        except Exception as exc:
            pytest.skip(f"headless Chromium unavailable: {exc}")

Measured on this repository, same commit, same machine, one environment variable
apart: a working run reports ``98 passed`` and an unlaunchable one
``98 skipped, 2180 deselected`` — and **both exit 0**. The second is a green
required check over a suite that executed nothing. (Playwright missing entirely
is not the dangerous case: the module-scope ``importorskip`` means nothing is
collected, pytest exits 5, and the job fails loudly. CI always installs
Playwright, so the launch failure is the case that actually happens.)

This reads the JUnit XML pytest just wrote and fails unless a floor of tests
genuinely *executed* — not collected, not skipped. Run it as a separate step so
the failure names the real problem instead of surfacing as a mysterious pass.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def suite_counts(xml_path: Path) -> tuple[int, int]:
    """``(collected, executed)`` across every ``<testsuite>`` in ``xml_path``.

    "Executed" is collected minus skipped minus errored. A **failure** counts as
    executed — the test body ran and reported on the report's behaviour, which is
    exactly the evidence this guard is looking for, and pytest's own non-zero exit
    already fails the job. An **error** does not: a setup or collection error
    means the body never ran, so it is no more evidence than a skip. The one
    question this answers is "did anything actually execute?".
    """
    root = ET.parse(xml_path).getroot()
    # ``iter`` and not ``findall``: it yields the root itself when the root *is*
    # a ``<testsuite>``, which is what an older ``junit_family`` writes. A
    # ``root.tag == "testsuite"`` fallback beside it was dead code.
    suites = root.iter("testsuite")
    collected = executed = 0
    for suite in suites:
        total = int(suite.get("tests") or 0)
        skipped = int(suite.get("skipped") or 0)
        errors = int(suite.get("errors") or 0)
        collected += total
        executed += max(0, total - skipped - errors)
    return collected, executed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml", type=Path, help="the JUnit XML pytest wrote")
    parser.add_argument(
        "--min-executed", type=int, default=20,
        help="fail below this many executed tests (default 20; the suite has ~98)",
    )
    args = parser.parse_args(argv)

    if not args.xml.is_file():
        print(f"browser suite check: {args.xml} was never written", file=sys.stderr)
        return 1
    try:
        collected, executed = suite_counts(args.xml)
    except ET.ParseError as exc:
        print(f"browser suite check: could not parse {args.xml}: {exc}", file=sys.stderr)
        return 1

    print(f"browser suite: {collected} collected, {executed} executed")
    if executed < args.min_executed:
        print(
            f"browser suite check FAILED: only {executed} test(s) executed "
            f"(floor {args.min_executed}). The exploit suite skipped itself — "
            f"almost certainly headless Chromium failed to launch — so this check "
            f"proved nothing about CSP, file:// handling or event execution. "
            f"A skip is not a pass.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
