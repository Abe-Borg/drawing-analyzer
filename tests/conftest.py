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
- Two autouse fixtures below keep per-test attribution honest:
  ``sdk_checked_guard`` (WP-02.2) fails a test in which production reached an
  unchecked fake Messages entry point, and ``background_release_joined``
  (WP-02.3) joins the upload-release threads a test starts at its teardown.
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
# the python3-tk system package). None today: the GUI's unit tests
# (``tests/test_gui_lifecycle.py``) inject a fake toolkit instead of importing
# the real one, so they run without tkinter. The hook stays so adding a test
# that does import it is a one-line change here.
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


# ---------------------------------------------------------------------------
# Every Messages entry point production reaches is SDK-checked (WP-02.2)
# ---------------------------------------------------------------------------


def _sdk_checked(entry) -> bool:
    """A fake entry point behind ``fake_anthropic.checked_entry``, or the real
    SDK's own method. (``is True``: a ``MagicMock`` answers any attribute.)"""
    if getattr(entry, "sdk_checked", False) is True:
        return True
    owner = getattr(entry, "__self__", None)
    return owner is not None and type(owner).__module__.startswith("anthropic.")


@pytest.fixture(autouse=True)
def sdk_checked_guard(monkeypatch):
    """Fail a test in which production reached an unchecked fake.

    Remediation WP-02.2 (the owner's rule: every fake production reaches goes
    through the shared SDK check in ``fake_anthropic``). A fake whose
    ``create``/``stream`` takes ``**kwargs`` without it accepts what the real
    SDK refuses, and a stage catches its own exceptions (I-3), so a raise here
    would be swallowed: the entry is recorded instead and fails the test at
    teardown, naming it. Every real-time request goes through
    ``core.api_config._dispatch_messages``, so that is where it is looked at,
    before it is sent. A namespace the fake does not have is production's own
    ``AttributeError``, not a finding. The list is the fixture's value: a test
    that reaches an unchecked fake on purpose clears it.
    """
    import drawing_analyzer.core.api_config as api

    unchecked: list[str] = []
    real = api._dispatch_messages

    def _dispatch(client, kwargs, method):
        try:
            entry = getattr(api.messages_namespace(client, kwargs), method)
        except AttributeError:
            entry = None
        if entry is not None and not _sdk_checked(entry):
            namespace = "beta" if kwargs.get("betas") else "plain"
            unchecked.append(
                f"{namespace}.{method} -> {getattr(entry, '__qualname__', type(entry).__qualname__)}"
            )
        return real(client, kwargs, method)

    monkeypatch.setattr(api, "_dispatch_messages", _dispatch)
    yield unchecked
    assert not unchecked, (
        "production reached a fake Messages entry point that is not SDK-checked "
        "(wrap it with tests.fixtures.fake_anthropic.checked_entry, or build the "
        f"fake on StreamingMessagesMixin / sdk_namespaces): {sorted(set(unchecked))}"
    )


# ---------------------------------------------------------------------------
# A background upload release finishes inside the test that started it (WP-02.3)
# ---------------------------------------------------------------------------

# How long a test's teardown waits for each release thread it started. A fake
# client's delete returns at once, so a release still running after this is a
# hang, and it fails the test rather than leaking into the next one.
_RELEASE_JOIN_SECONDS = 60


@pytest.fixture(autouse=True)
def background_release_joined(monkeypatch):
    """Join, at teardown, every upload release a test starts on a background thread.

    Remediation WP-02.3 (the owner's rule). ``batch_digest._release_uploaded_files``
    deletes a collected batch's uploaded files on a fire-and-forget daemon
    thread (``_run_in_background``) so the digests return before the cleanup.
    In a test that does not stub that seam, the thread could outlive its test
    and make its ``files.delete`` calls inside the next one: measured, 2 to 4
    of the suite's 80 releases (55 on the thread), depending on load, so
    per-test attribution of those calls was wrong. Production is unchanged
    (still a daemon thread, so the background path is still exercised); a
    test that stubs the seam itself keeps its own stub. The list of threads
    started is the fixture's value.
    """
    import threading

    import drawing_analyzer.batch_digest as batch_digest

    started: list[threading.Thread] = []

    def run_in_background(fn):
        thread = threading.Thread(target=fn, daemon=True)
        started.append(thread)
        thread.start()

    monkeypatch.setattr(batch_digest, "_run_in_background", run_in_background)
    yield started
    for thread in started:
        thread.join(timeout=_RELEASE_JOIN_SECONDS)
    running = [t.name for t in started if t.is_alive()]
    assert not running, (
        f"an upload release started by this test was still running after "
        f"{_RELEASE_JOIN_SECONDS}s: {running}"
    )
