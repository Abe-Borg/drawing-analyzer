"""WP-01 — the acceptance runner can never reach the paid API.

``scripts/run_acceptance.py`` is the one-command release gate. Its hermetic
gate used to spawn a bare ``pytest -q``; ``pyproject.toml`` sets no default
marker exclusion, and ``tests/conftest.py`` skips ``network`` tests *only when
no real key is set*. So running the acceptance script on a machine with a real
``ANTHROPIC_API_KEY`` exported turned a release check into a billed live-canary
run.

The fix is marker deselection in the child the script spawns — not an unset
key, which is an environment accident a future gate could lose. These tests
pin that property three ways:

1. every gate's constructed argv deselects ``network`` (no suite is run here);
2. the deselection survives a real-looking key in the environment;
3. the marker expression is *actually valid pytest syntax that deselects* —
   an argv assertion alone would pass a typo like ``"not netwrok"``, which
   silently matches nothing and would run the canary. This one narrow
   ``--collect-only`` on the canary file is hermetic: collection imports the
   module but makes no API call.

Plus a structural regression: a bare ``"pytest"`` argv literal anywhere outside
the command builder fails the suite, so a future gate cannot reintroduce the
hole by not using the helper.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_acceptance.py"
# Obvious sentinel: never a usable credential, and clearly fake in any log.
_FAKE_KEY = "sk-ant-FAKE-not-a-real-key-do-not-use"


def _load_script():
    """Import the acceptance script by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_run_acceptance", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


@pytest.fixture
def recorded(script, monkeypatch):
    """Capture the argv each gate would spawn, without spawning anything."""
    calls: list[list[str]] = []

    def _fake_run(cmd, **kw):
        calls.append(list(cmd))
        return 0

    monkeypatch.setattr(script, "_run", _fake_run)
    return calls


def _marker_expr(cmd: list[str]) -> str:
    """The value of the child's ``-m`` selection, or ``''`` when absent."""
    return cmd[cmd.index("-m", cmd.index("pytest")) + 1] if "-m" in cmd else ""


# --------------------------------------------------------------------------- #
# 1. Every pytest gate deselects the network marker
# --------------------------------------------------------------------------- #


def test_hermetic_suite_gate_deselects_network(script, recorded):
    assert script.gate_hermetic_suite() == "PASS"
    assert len(recorded) == 1
    assert _marker_expr(recorded[0]) == "not network"


def test_import_isolation_gate_deselects_network(script, recorded):
    assert script.gate_import_isolation() == "PASS"
    assert len(recorded) == 1
    cmd = recorded[0]
    assert _marker_expr(cmd) == "not network"
    # Still targets its own file — the deselection is additive, not a rewrite.
    assert cmd[-1] == "tests/test_import_isolation.py"


def test_browser_gate_still_selects_browser_and_adds_deselection(script, recorded):
    if importlib.util.find_spec("playwright") is None:
        pytest.skip("browser gate short-circuits to SKIP without playwright")
    assert script.gate_browser_security() == "PASS"
    assert _marker_expr(recorded[0]) == "(browser) and not network"


def test_browser_gate_marker_is_built_by_the_helper(script):
    """Playwright-independent form of the assertion above."""
    assert script._pytest_cmd(select="browser")[-1] != "browser"
    assert _marker_expr(script._pytest_cmd(select="browser")) == "(browser) and not network"


def test_every_gate_that_spawns_pytest_deselects_network(script, recorded):
    """Sweep all gates; any that shells out to pytest must carry the marker."""
    for _name, gate, _optional in script.GATES:
        recorded.clear()
        try:
            gate()
        except Exception:  # noqa: BLE001 - build gate may bail without tooling
            continue
        for cmd in recorded:
            if "pytest" in cmd:
                assert "not network" in _marker_expr(cmd), cmd


# --------------------------------------------------------------------------- #
# 2. A real-looking key in the environment changes nothing
# --------------------------------------------------------------------------- #


def test_deselection_survives_a_key_in_the_environment(script, recorded, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", _FAKE_KEY)
    assert script.gate_hermetic_suite() == "PASS"
    assert _marker_expr(recorded[0]) == "not network"


def test_no_gate_depends_on_unsetting_the_key(script, recorded, monkeypatch):
    """The key is never popped: marker exclusion is the mechanism, not luck."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", _FAKE_KEY)
    script.gate_hermetic_suite()
    script.gate_import_isolation()
    import os

    assert os.environ.get("ANTHROPIC_API_KEY") == _FAKE_KEY
    for cmd in recorded:
        assert "not network" in _marker_expr(cmd)


# --------------------------------------------------------------------------- #
# 3. The marker expression really deselects (guards a typo'd expression)
# --------------------------------------------------------------------------- #


def test_marker_expression_actually_deselects_the_canary(script):
    """Collect-only on the canary file must yield zero tests.

    ``--strict-markers`` validates *registered* markers, not ``-m``
    expressions: an unknown name in ``-m`` matches nothing, so a typo would
    deselect nothing and run the canary. Only executing the expression proves
    it. Collection makes no API call.
    """
    canary = _REPO_ROOT / "tests" / "test_live_api_canary.py"
    assert canary.exists(), "canary file moved; update this test's target"
    cmd = script._pytest_cmd("--collect-only", str(canary), "-p", "no:cacheprovider")
    proc = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True)
    combined = proc.stdout + proc.stderr
    assert "no tests collected" in combined or "no tests ran" in combined, combined
    # Sanity: without the deselection the same file *does* collect, so the
    # assertion above is testing the marker and not an empty/missing file.
    plain = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", str(canary),
         "-p", "no:cacheprovider"],
        cwd=_REPO_ROOT, capture_output=True, text=True,
    )
    assert "tests collected" in (plain.stdout + plain.stderr)


# --------------------------------------------------------------------------- #
# 4. Structural regression: no bare pytest invocation may reappear
# --------------------------------------------------------------------------- #


def test_no_pytest_argv_literal_outside_the_command_builder():
    """A future gate must not hand-roll its own pytest argv.

    AST-based so the module docstring's prose (``pytest -m network …``) is not
    mistaken for a command literal.
    """
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    helper = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_pytest_cmd"
    )
    allowed = range(helper.lineno, (helper.end_lineno or helper.lineno) + 1)
    offenders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and node.value == "pytest"
        and node.lineno not in allowed
    ]
    assert not offenders, (
        f"{_SCRIPT.name} builds a pytest command outside _pytest_cmd at line(s) "
        f"{offenders}. Route it through _pytest_cmd() so the network "
        f"deselection cannot be forgotten (WP-01)."
    )


def test_command_builder_is_the_only_source_of_the_deselection(script):
    """The deselection is a named constant, not a scattered string literal."""
    assert script._NETWORK_DESELECT == "not network"
    assert _marker_expr(script._pytest_cmd()) == script._NETWORK_DESELECT
