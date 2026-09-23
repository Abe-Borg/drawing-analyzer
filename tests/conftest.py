"""Shared pytest configuration for the drawing-analyzer test suite.

Keep tests hermetic by default. The boundary is enforced, not merely intended:
``tests/fixtures/hermetic_guard.py`` (registered below, WP-02.1) refuses every
non-local socket connection and name lookup, fails any test that attempted one
(even when the code under test swallowed the error), removes ambient proxy and
``ANTHROPIC_*`` credential variables, and makes the ``network`` marker an
explicit opt-in. Read its docstring before changing any of that.

- Tests must never need a real ``ANTHROPIC_API_KEY``. Collection sees an
  obvious placeholder, so import-time helpers that call ``client.get_client``
  never raise; every hermetic test sees no key at all. A test that needs real
  API access is marked ``@pytest.mark.network`` and runs only when selected with
  ``-m network`` and a real key is exported.
- ``fake_anthropic`` is exposed as a top-level fixture so request-shape and
  parser tests can build response objects without instantiating the real SDK.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Put the repo root on sys.path so ``tests.fixtures.*`` imports — including the
# guard plugin below. The package itself is importable via
# ``[tool.pytest.ini_options] pythonpath``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pytest_plugins = ["tests.fixtures.hermetic_guard"]


def _tkinter_available() -> bool:
    return importlib.util.find_spec("tkinter") is not None


# Test files that import the GUI (customtkinter / tkinter) at module scope are
# skipped at collection time when ``tkinter`` is missing (common in CI without
# the python3-tk system package). None today — the GUI has no unit tests — but
# the hook stays so adding one is a one-line change here.
_GUI_DEPENDENT_TESTS: set[str] = set()


def pytest_ignore_collect(collection_path, config):
    if not _tkinter_available() and collection_path.name in _GUI_DEPENDENT_TESTS:
        return True
    return None


# ---------------------------------------------------------------------------
# Fake Anthropic response fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_anthropic():
    """Expose the ``fake_anthropic`` helper module as a fixture.

    Tests can ``request.getfixturevalue("fake_anthropic")`` or take
    ``fake_anthropic`` as an argument and use the builders directly.
    """
    from tests.fixtures import fake_anthropic as module

    return module
