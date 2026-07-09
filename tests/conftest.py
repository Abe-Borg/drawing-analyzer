"""Shared pytest configuration for the drawing-analyzer test suite.

Keep tests hermetic by default.

- Tests must never need a real ``ANTHROPIC_API_KEY``. The client cache reads the
  env var lazily, so we set a sentinel value before collection. Any test that
  needs a real network call should opt in via ``@pytest.mark.network`` and be
  skipped unless ``ANTHROPIC_API_KEY`` is set.
- ``fake_anthropic`` is exposed as a top-level fixture so request-shape and
  parser tests can build response objects without instantiating the real SDK.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Put the repo root on sys.path so ``tests.fixtures.fake_anthropic`` imports.
# The package itself is importable via ``[tool.pytest.ini_options] pythonpath``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Obvious-fake key injected for hermetic collection so import-time helpers that
# call ``client.get_client`` never raise. It is never used for a real call: the
# autouse fixture below strips the key from every non-``network`` test.
_PLACEHOLDER_KEY = "test-key-not-real-do-not-use"


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


def pytest_configure(config: pytest.Config) -> None:
    """Inject a placeholder API key so import-time helpers never raise.

    ``client.get_client`` raises if ``ANTHROPIC_API_KEY`` is missing. The
    placeholder is obviously fake so any accidental real call will 401 instead
    of silently charging a different account.
    """
    os.environ.setdefault("ANTHROPIC_API_KEY", _PLACEHOLDER_KEY)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip ``@pytest.mark.network`` tests unless a real API key is set."""
    real_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if real_key and real_key != _PLACEHOLDER_KEY:
        return
    skip_marker = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set; skipping network test")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _enforce_hermetic_api_key(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I-4: no non-``network`` test may reach the API.

    The pipeline and several QC stages (e.g. ``prose_harvest``) fall back to
    ``client.get_client`` when no client is passed, and that reads a *real*
    ``ANTHROPIC_API_KEY`` straight from the developer's environment. Setting a
    key locally (a normal thing to do) would otherwise turn hermetic tests into
    real, billable calls. Strip the key for every hermetic test so the fallback
    raises — exercising the genuine no-client path — instead of building a live
    client. Tests marked ``@pytest.mark.network`` opt out and keep the key.
    """
    if request.node.get_closest_marker("network") is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


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
