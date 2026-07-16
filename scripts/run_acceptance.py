#!/usr/bin/env python3
"""Run the Phase 27 automated release gates locally and print a gate summary.

This is the one-command counterpart to CI for a release candidate: it runs
every *automated* gate from §19.8 in order and reports PASS/FAIL/SKIP per
gate. It does not replace the manual acceptance records
(``docs/WINDOWS_ACCEPTANCE.md``, ``docs/RELEASE_ACCEPTANCE_TEMPLATE.md``) or
the opt-in live canary (``pytest -m network tests/test_live_api_canary.py``).

    python scripts/run_acceptance.py            # all automated gates
    python scripts/run_acceptance.py --fast     # skip build + browser gates

Gates (in order):
  1. byte-compile        python -m compileall -q src
  2. import isolation    pytest tests/test_import_isolation.py   (I-5)
  3. hermetic suite      pytest  (includes the §19.1/§19.2 trust gauntlet)
  4. secret scan         scripts/scan_secrets.py                 (§19.8)
  5. browser security    pytest -m browser   (SKIP if Playwright absent)
  6. build + install     wheel/sdist build, clean-venv install, import +
                         packaged-profiles smoke  (SKIP with --fast)

Exit code 0 only when every non-skipped gate passes. Pure stdlib,
Windows-safe (pathlib + sys.executable, no shell utilities).
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], **kw) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, cwd=REPO_ROOT, **kw).returncode


def gate_compileall() -> str:
    return "PASS" if _run([sys.executable, "-m", "compileall", "-q", "src"]) == 0 else "FAIL"


def gate_import_isolation() -> str:
    rc = _run([sys.executable, "-m", "pytest", "-q", "tests/test_import_isolation.py"])
    return "PASS" if rc == 0 else "FAIL"


def gate_hermetic_suite() -> str:
    return "PASS" if _run([sys.executable, "-m", "pytest", "-q"]) == 0 else "FAIL"


def gate_secret_scan() -> str:
    rc = _run([sys.executable, str(REPO_ROOT / "scripts" / "scan_secrets.py")])
    return "PASS" if rc == 0 else "FAIL"


def gate_browser_security() -> str:
    if importlib.util.find_spec("playwright") is None:
        return "SKIP (playwright not installed; pip install -e '.[browsertest]' " \
               "&& python -m playwright install chromium)"
    rc = _run([sys.executable, "-m", "pytest", "-q", "-m", "browser"])
    return "PASS" if rc == 0 else "FAIL"


def gate_build_and_install_smoke() -> str:
    if importlib.util.find_spec("build") is None:
        return "SKIP (python -m pip install build)"
    with tempfile.TemporaryDirectory(prefix="da-accept-") as tmp:
        dist = Path(tmp) / "dist"
        if _run([sys.executable, "-m", "build", "--outdir", str(dist)]) != 0:
            return "FAIL (build)"
        wheels = sorted(dist.glob("*.whl"))
        sdists = sorted(dist.glob("*.tar.gz"))
        if not wheels or not sdists:
            return "FAIL (missing wheel or sdist)"
        env_dir = Path(tmp) / "venv"
        venv.create(env_dir, with_pip=True)
        bin_dir = "Scripts" if sys.platform == "win32" else "bin"
        py = env_dir / bin_dir / ("python.exe" if sys.platform == "win32" else "python")
        if _run([str(py), "-m", "pip", "install", "--quiet", str(wheels[0])]) != 0:
            return "FAIL (wheel install)"
        # No built-in profiles ship (review plans are model-authored per set —
        # Phase A), so the smoke proves the profile MECHANISM in the installed
        # wheel instead: the loader tolerates the absent builtin dir, and the
        # parser round-trips a checklist item.
        smoke = (
            "import drawing_analyzer; "
            "from drawing_analyzer import profiles as P; "
            "assert isinstance(P.load_profiles(), dict); "
            "p = P.parse_profile('---\\nname: x\\n---\\n- item\\n'); "
            "assert p.items == ('item',), p.items; "
            "print('installed', drawing_analyzer.__version__, '| profile mechanism ok')"
        )
        if _run([str(py), "-c", smoke]) != 0:
            return "FAIL (install smoke: import/profile mechanism)"
    return "PASS"


GATES = [
    ("byte-compile", gate_compileall, False),
    ("import isolation (I-5)", gate_import_isolation, False),
    ("hermetic suite + trust gauntlet", gate_hermetic_suite, False),
    ("secret scan", gate_secret_scan, False),
    ("browser security", gate_browser_security, True),
    ("build + clean-install smoke", gate_build_and_install_smoke, True),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fast", action="store_true",
                        help="skip the slow optional gates (browser, build)")
    args = parser.parse_args()

    results: list[tuple[str, str]] = []
    for name, gate, optional in GATES:
        if args.fast and optional:
            results.append((name, "SKIP (--fast)"))
            continue
        print(f"\n=== gate: {name} " + "=" * max(0, 58 - len(name)))
        try:
            results.append((name, gate()))
        except Exception as exc:  # noqa: BLE001 - a crashed gate is a failed gate
            results.append((name, f"FAIL (gate crashed: {exc})"))

    width = max(len(n) for n, _ in results)
    print("\n" + "=" * 72)
    print("Automated release gates (§19.8) — manual gates are recorded separately")
    print("=" * 72)
    failed = False
    for name, status in results:
        print(f"  {name.ljust(width)}  {status}")
        failed = failed or status.startswith("FAIL")
    print("=" * 72)
    if failed:
        print("RESULT: FAIL — do not cut a release from this commit.")
        return 1
    print("RESULT: automated gates PASS. Complete the manual acceptance records")
    print("(docs/WINDOWS_ACCEPTANCE.md, docs/RELEASE_ACCEPTANCE_TEMPLATE.md) and")
    print("the live canary (pytest -m network) before tagging.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
