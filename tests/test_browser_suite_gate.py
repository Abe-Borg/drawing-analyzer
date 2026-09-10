"""P9 item 42 — the mandatory browser exploit suite cannot pass by skipping.

``.github/workflows/ci.yml`` runs ``pytest -m browser`` as the one gate that
proves CSP enforcement, ``file://`` behaviour and real event dispatch in an
actual browser. Every test in that suite skips itself when Chromium will not
launch, and pytest exits **0** on an all-skipped run — so the gate was green
over a suite that executed nothing. Measured on this repository, one environment
variable apart: ``98 passed`` (working) and ``98 skipped, 2180 deselected``
(``PLAYWRIGHT_BROWSERS_PATH`` pointed at an empty dir), *both* exit 0.

``scripts/check_browser_suite.py`` reads the JUnit XML and fails below a floor of
genuinely executed tests. These tests pin three things:

1. the arithmetic — skips and setup errors are not execution, failures are;
2. the failure paths (missing file, unparsable XML) fail closed, not open;
3. **the workflow actually calls it**, on the same file pytest was told to write.

(3) is the load-bearing one: without it the script can keep passing its own unit
tests while nothing in CI runs it, which is the exact shape of the bug it fixes.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_browser_suite.py"
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_script():
    """Import the checker by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_check_browser_suite", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


def _xml(tmp_path: Path, *, tests: int, skipped: int = 0, errors: int = 0,
         failures: int = 0, name: str = "results.xml") -> Path:
    """A minimal xunit2 document in the shape pytest's ``--junitxml`` writes."""
    path = tmp_path / name
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        f'<testsuite name="pytest" errors="{errors}" failures="{failures}"'
        f' skipped="{skipped}" tests="{tests}" time="1.0"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    return path


# --- the arithmetic ---------------------------------------------------------

def test_all_skipped_counts_as_nothing_executed(script, tmp_path):
    """The measured hole: 98 collected, 98 skipped, pytest exit 0."""
    assert script.suite_counts(_xml(tmp_path, tests=98, skipped=98)) == (98, 0)


def test_a_working_run_counts_every_test(script, tmp_path):
    assert script.suite_counts(_xml(tmp_path, tests=98)) == (98, 98)


def test_a_failure_counts_as_executed(script, tmp_path):
    """A failing test ran and reported on the report — that is the evidence."""
    assert script.suite_counts(_xml(tmp_path, tests=98, failures=3)) == (98, 98)


def test_a_setup_error_does_not_count_as_executed(script, tmp_path):
    """A collection/setup error never reached the body, so it is not execution."""
    assert script.suite_counts(_xml(tmp_path, tests=98, errors=98)) == (98, 0)


def test_counts_sum_across_multiple_testsuites(script, tmp_path):
    path = tmp_path / "multi.xml"
    path.write_text(
        '<testsuites>'
        '<testsuite name="a" tests="5" skipped="5" errors="0" failures="0"/>'
        '<testsuite name="b" tests="7" skipped="0" errors="0" failures="0"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    assert script.suite_counts(path) == (12, 7)


def test_a_bare_testsuite_root_is_read_too(script, tmp_path):
    """Older ``junit_family`` settings put ``<testsuite>`` at the root."""
    path = tmp_path / "bare.xml"
    path.write_text(
        '<testsuite name="pytest" tests="30" skipped="0" errors="0" failures="0"/>',
        encoding="utf-8",
    )
    assert script.suite_counts(path) == (30, 30)


# --- the gate ---------------------------------------------------------------

def test_main_fails_the_all_skipped_run(script, tmp_path, capsys):
    rc = script.main([str(_xml(tmp_path, tests=98, skipped=98))])
    assert rc == 1
    err = capsys.readouterr().err
    assert "A skip is not a pass." in err
    # The message must name the real cause, or the CI log sends the reader
    # hunting for a report bug that does not exist.
    assert "Chromium" in err


def test_main_passes_the_working_run(script, tmp_path, capsys):
    assert script.main([str(_xml(tmp_path, tests=98))]) == 0
    assert "98 executed" in capsys.readouterr().out


def test_main_fails_when_the_floor_is_not_met(script, tmp_path):
    """Half a suite skipping is still a suite that mostly did not run."""
    assert script.main([str(_xml(tmp_path, tests=98, skipped=90))]) == 1
    assert script.main([str(_xml(tmp_path, tests=98, skipped=90)),
                        "--min-executed", "8"]) == 0


def test_main_fails_when_pytest_wrote_no_xml(script, tmp_path, capsys):
    """Fail closed: a missing report is not evidence of a passing suite."""
    assert script.main([str(tmp_path / "never-written.xml")]) == 1
    assert "never written" in capsys.readouterr().err


def test_main_fails_on_an_unparsable_xml(script, tmp_path, capsys):
    path = tmp_path / "truncated.xml"
    path.write_text('<testsuites><testsuite tests="98"', encoding="utf-8")
    assert script.main([str(path)]) == 1
    assert "could not parse" in capsys.readouterr().err


def _browser_marked_functions() -> int:
    """Browser-marked test functions, counted from the sources.

    Static on purpose: a test that needed Playwright to check the browser gate
    would skip in exactly the environment the gate exists for. Parameterisation
    only raises the collected count above this (93 functions -> 98 collected at
    the time of writing), so it is a floor on the floor.
    """
    marked = 0
    for path in sorted((_REPO_ROOT / "tests").glob("test_*.py")):
        src = path.read_text(encoding="utf-8")
        if "pytestmark = pytest.mark.browser" not in src:
            continue
        marked += sum(
            1 for node in ast.parse(src).body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
    return marked


def test_the_default_floor_is_reachable_by_the_real_suite(script, tmp_path):
    """A default floor above the suite's own size would fail every green run."""
    marked = _browser_marked_functions()
    assert marked >= 20, f"only {marked} browser-marked test functions remain"
    # The real suite, fully executed, must clear the default floor.
    assert script.main([str(_xml(tmp_path, tests=marked))]) == 0


# --- the wiring (the part that makes the rest matter) ----------------------

def _browser_job_steps() -> list[dict]:
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(_CI.read_text(encoding="utf-8"))
    return workflow["jobs"]["browser-security"]["steps"]


def test_ci_runs_the_guard_on_the_xml_pytest_writes():
    """The pytest step and the guard must agree on one filename, in one job.

    A ``--junitxml`` pointing at one path and a guard reading another is a guard
    that always fails; the same drift the other way (guard dropped, junitxml
    kept) is a guard that never runs. Both are silent, so they are asserted
    together against the workflow itself.
    """
    steps = _browser_job_steps()
    pytest_runs = [s["run"] for s in steps if "run" in s and "-m browser" in s["run"]]
    guard_runs = [s["run"] for s in steps
                  if "run" in s and "check_browser_suite.py" in s["run"]]
    assert len(pytest_runs) == 1, pytest_runs
    assert len(guard_runs) == 1, guard_runs

    marker = "--junitxml="
    assert marker in pytest_runs[0], pytest_runs[0]
    written = pytest_runs[0].split(marker, 1)[1].split()[0].strip("'\"")
    assert written, pytest_runs[0]
    assert written in guard_runs[0], (written, guard_runs[0])
    # And in that order: a guard that runs first reads the *previous* run's file.
    assert steps.index(next(s for s in steps if s.get("run") == pytest_runs[0])) < \
        steps.index(next(s for s in steps if s.get("run") == guard_runs[0]))


def test_release_publish_needs_the_release_gates():
    """P9 item 42a: a tag cannot publish an installer past a failing suite.

    Branch protection does not apply to tag pushes, so ``publish`` needing only
    ``build`` meant a release was gated on the installer *compiling*.
    """
    yaml = pytest.importorskip("yaml")
    release = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    )
    jobs = release["jobs"]
    assert "gates" in jobs, "the tag-gated release-gates job is gone"
    needs = jobs["publish"]["needs"]
    needs = [needs] if isinstance(needs, str) else list(needs)
    assert "gates" in needs, needs
    assert "run_acceptance.py" in " ".join(
        s.get("run", "") for s in jobs["gates"]["steps"]
    )
