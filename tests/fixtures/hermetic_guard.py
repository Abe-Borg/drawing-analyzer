"""The hermetic boundary around every test not marked ``network`` (WP-02.1, U26).

Registered by ``tests/conftest.py``. Invariant I-4 says no test may hit the
network or need a key; this plugin enforces it for the whole process instead of
relying on each test to use the fakes:

1. **Sockets.** ``socket.socket.connect`` / ``connect_ex`` and the forward
   lookups (``getaddrinfo``, ``gethostbyname``, ``gethostbyname_ex``) refuse any
   destination that is not loopback (or unspecified) and any socket family
   other than ``AF_UNIX``/``AF_INET``/``AF_INET6``. Every HTTP client this
   project uses reaches the network through that layer: the SDK's ``httpx2``
   sync transport (``httpcore2``) and ``urllib`` both call
   ``socket.create_connection``. Sockets are guarded where they *connect*, not
   where they are created: asyncio's self-pipe is a socket pair, loopback TCP
   on Windows, and Playwright's sync API runs on asyncio, so blocking creation
   would take the browser suite down with it.
2. **Every refusal is recorded and fails the test at teardown.** The QC stages
   catch their own exceptions by design (I-3), so a raise alone would let a
   pipeline test that tried to reach the API stay green. The recorded attempt
   turns the test's teardown into an error that names the destination; an
   attempt made outside any test (at import, say) fails the session.
3. **Ambient configuration is removed.** A loopback proxy is allowed by rule 1,
   so every ``*_proxy`` variable goes (traffic escaped through an exported
   ``HTTPS_PROXY`` when only sockets were guarded), and ``NO_PROXY=*`` stops
   ``urllib.request.getproxies`` falling back to the Windows registry or macOS
   system configuration, which no environment scrub reaches. Every
   ``ANTHROPIC_*`` variable goes too: a zero-arg ``Anthropic()`` resolves an
   auth token, a named profile, workload-identity federation and custom
   headers, not only the key, and the SDK adds sources over time under that
   prefix, so the rule is the prefix rather than a list. ``ANTHROPIC_CONFIG_DIR``
   then points at an empty directory, which makes the SDK refuse to build a
   zero-arg client at all instead of finding an ``ant auth login`` profile.
4. **The scope is the whole run.** The guard goes up at configure time and comes
   down only inside an opted-in ``network`` test, so collection and fixtures of
   every scope are covered. A function-scoped fixture only ever covered test
   bodies, while the gauntlet's module-scoped ``oracle`` fixture runs the whole
   exhaustive pipeline before any function-scoped fixture exists. And no fixture
   crosses the boundary: where an opted-in ``network`` test and a hermetic one
   are neighbours, the whole fixture stack is torn down between them, so each
   side makes, caches and finalizes its own (``pytest_runtest_teardown``).
5. **``network`` is an explicit opt-in.** An exported real key used to run the
   live canary under a bare ``pytest``. Now a ``network`` test runs only when
   the ``-m`` expression selects it *because of* that marker and a real key is
   set; it then gets the caller's own environment back, unguarded.

The key itself follows the pre-existing contract: collection sees an obvious
placeholder (so an import-time ``client.get_client`` never raises) and every
hermetic test sees no key at all, so the no-client fallbacks exercise their
genuine error path.

Not covered, deliberately: child processes inherit the scrubbed environment (no
key, no proxy, no credentials) but not the socket patch; UDP ``sendto``, which
no HTTP client here uses; asyncio's Windows proactor, which connects a literal
IP address below the Python socket API (the SDK's sync transport and ``urllib``
are covered); and the OS keyring, which the key-store tests stub through their
own seams.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

import pytest

# Obvious-fake key visible during collection only. It is never used for a real
# call: hermetic tests run with no key, and the sockets are guarded anyway.
PLACEHOLDER_KEY = "test-key-not-real-do-not-use"

NETWORK_OPT_IN_REASON = (
    "network tests are opt-in: select them explicitly with -m network "
    "(an exported ANTHROPIC_API_KEY alone does not run them)"
)
NO_KEY_REASON = "ANTHROPIC_API_KEY not set; skipping network test"

_OUTSIDE_ANY_TEST = "outside any test"
_AF_UNIX = getattr(socket, "AF_UNIX", None)
_INET_FAMILIES = (socket.AF_INET, socket.AF_INET6)


class ExternalNetworkBlocked(RuntimeError):
    """A test not marked ``network`` tried to reach a non-local destination.

    A ``RuntimeError`` (as in pytest-socket) so that an ``except OSError``
    written for a real network failure cannot mistake it for one and retry or
    degrade quietly. ``except Exception`` can still swallow it, which is why
    every attempt is also recorded.
    """


@dataclass(frozen=True)
class BlockedAttempt:
    operation: str  # "connect", "connect_ex", "getaddrinfo", ...
    destination: str  # "192.0.2.1:443", "api.anthropic.com:443", ...
    during: str  # the node id of the test running, or "outside any test"

    def __str__(self) -> str:
        return f"{self.operation} {self.destination} (during {self.during})"


@dataclass
class _GuardState:
    real_key: str
    config_dir: str
    patch: pytest.MonkeyPatch = field(default_factory=pytest.MonkeyPatch)
    current: str = _OUTSIDE_ANY_TEST
    attempts: list[BlockedAttempt] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, operation: str, destination: str) -> BlockedAttempt:
        attempt = BlockedAttempt(operation, destination, self.current)
        with self.lock:
            self.attempts.append(attempt)
        return attempt

    def drain(self, during: str | None = None) -> list[BlockedAttempt]:
        """Remove and return the attempts made during ``during`` (all if None)."""
        taken: list[BlockedAttempt] = []
        kept: list[BlockedAttempt] = []
        with self.lock:
            for attempt in self.attempts:
                (taken if during is None or attempt.during == during else kept).append(attempt)
            self.attempts = kept
        return taken


_STATE = pytest.StashKey[_GuardState]()
_RELEASED = pytest.StashKey[bool]()


def drain_blocked_attempts(config: pytest.Config) -> list[BlockedAttempt]:
    """Consume the running test's recorded attempts (for the guard's own tests)."""
    state = config.stash[_STATE]
    return state.drain(state.current)


def _released(item: pytest.Item) -> bool:
    """Is this an opted-in ``network`` test (run unguarded, with the caller's env)?"""
    return item.stash.get(_RELEASED, False)


# --------------------------------------------------------------------------- #
# What counts as local
# --------------------------------------------------------------------------- #


def is_local_host(host: Any) -> bool:
    """True only for a host that cannot name another machine.

    Loopback addresses (all of ``127.0.0.0/8``, ``::1``, and their IPv4-mapped
    forms, which Python 3.11 does not count as loopback on its own), the
    unspecified addresses, the name ``localhost``, and a missing or empty host
    (a passive, bind-side lookup). Every other name is refused *before* it is
    resolved, because the lookup itself is external traffic.
    """
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        try:
            host = bytes(host).decode("ascii")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    name = host.strip()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    if not name:
        return True
    if name.rstrip(".").lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(name.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified


def _destination(host: Any, port: Any = None) -> str:
    if isinstance(host, (bytes, bytearray)):
        text = bytes(host).decode("ascii", "replace")
    else:
        text = str(host)
    if port is None:
        return text
    if ":" in text and not text.startswith("["):
        text = f"[{text}]"
    return f"{text}:{port}"


# --------------------------------------------------------------------------- #
# The opt-in rule
# --------------------------------------------------------------------------- #


def network_selected_explicitly(markexpr: str, marks: Iterable[pytest.Mark]) -> bool:
    """Does the ``-m`` expression select this test *because of* ``network``?

    True when the expression selects the test and would not select it without
    its ``network`` marker. ``-m network`` and ``-m "network and not slow"``
    opt in; no ``-m``, ``-m "not browser"`` and ``-m "network or not network"``
    do not. A test carrying a second marker that also satisfies the expression
    (``-m "network or browser"`` on a test marked both) is not opted in: every
    miss here errs toward skipping a billable test, never toward running one.

    Evaluated with pytest's own marker-expression engine, so the rule cannot
    disagree with pytest about what an expression means. That engine is not
    public API: if a pytest upgrade moves it, this answers False (the canary is
    skipped, never run by accident) and ``tests/test_hermetic_guard.py`` fails.
    """
    if not markexpr.strip():
        return False
    marks = list(marks)
    try:
        from _pytest.mark import MarkMatcher
        from _pytest.mark.expression import Expression

        expression = Expression.compile(markexpr)
        with_network = expression.evaluate(MarkMatcher.from_markers(marks))
        without = expression.evaluate(
            MarkMatcher.from_markers([m for m in marks if m.name != "network"])
        )
    except Exception:  # noqa: BLE001 - fail closed: an opt-in must be certain
        return False
    return bool(with_network) and not without


# --------------------------------------------------------------------------- #
# Installing the boundary
# --------------------------------------------------------------------------- #


def _scrub_environment(patch: pytest.MonkeyPatch, config_dir: str) -> None:
    for name in list(os.environ):
        upper = name.upper()
        if upper.endswith("_PROXY") or upper.startswith("ANTHROPIC_"):
            patch.delenv(name, raising=False)
    for name in ("NO_PROXY", "no_proxy"):  # one variable on Windows; harmless
        patch.setenv(name, "*")
    patch.setenv("ANTHROPIC_CONFIG_DIR", config_dir)
    patch.setenv("ANTHROPIC_API_KEY", PLACEHOLDER_KEY)


def _guard_sockets(patch: pytest.MonkeyPatch, state: _GuardState) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname
    real_gethostbyname_ex = socket.gethostbyname_ex

    def refuse(operation: str, destination: str) -> None:
        attempt = state.record(operation, destination)
        raise ExternalNetworkBlocked(
            f"a test not marked 'network' tried to reach {destination} "
            f"({operation}, during {attempt.during}). Hermetic tests may use only "
            "loopback and AF_UNIX sockets: see tests/fixtures/hermetic_guard.py."
        )

    def check_address(operation: str, family: Any, address: Any) -> None:
        if _AF_UNIX is not None and family == _AF_UNIX:
            return
        if family in _INET_FAMILIES:
            if not isinstance(address, tuple) or len(address) < 2:
                return  # malformed: the real call raises its own error
            if not is_local_host(address[0]):
                refuse(operation, _destination(address[0], address[1]))
            return
        refuse(operation, f"{family!r} {address!r}")

    def check_host(operation: str, host: Any, port: Any = None) -> None:
        if host is not None and not isinstance(host, (str, bytes, bytearray)):
            return  # malformed: the real call raises TypeError
        if not is_local_host(host):
            refuse(operation, _destination(host, port))

    def connect(self, address):
        check_address("connect", self.family, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        check_address("connect_ex", self.family, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002 - socket's names
        check_host("getaddrinfo", host, port)
        return real_getaddrinfo(host, port, family, type, proto, flags)

    def gethostbyname(hostname):
        check_host("gethostbyname", hostname)
        return real_gethostbyname(hostname)

    def gethostbyname_ex(hostname):
        check_host("gethostbyname_ex", hostname)
        return real_gethostbyname_ex(hostname)

    patch.setattr(socket.socket, "connect", connect)
    patch.setattr(socket.socket, "connect_ex", connect_ex)
    patch.setattr(socket, "getaddrinfo", getaddrinfo)
    patch.setattr(socket, "gethostbyname", gethostbyname)
    patch.setattr(socket, "gethostbyname_ex", gethostbyname_ex)


def _install(state: _GuardState) -> None:
    _scrub_environment(state.patch, state.config_dir)
    _guard_sockets(state.patch, state)


def _describe(attempts: list[BlockedAttempt]) -> str:
    return "\n".join(
        [f"{len(attempts)} external network attempt(s) blocked by the hermetic guard:"]
        + [f"  {attempt}" for attempt in attempts]
        + [
            "Tests not marked 'network' may use only loopback and AF_UNIX sockets. "
            "A live test is marked @pytest.mark.network and run with -m network; "
            "see tests/fixtures/hermetic_guard.py."
        ]
    )


# --------------------------------------------------------------------------- #
# Hooks
# --------------------------------------------------------------------------- #


def pytest_configure(config: pytest.Config) -> None:
    state = _GuardState(
        real_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        config_dir=tempfile.mkdtemp(prefix="da-hermetic-anthropic-config-"),
    )
    config.stash[_STATE] = state
    _install(state)


def pytest_unconfigure(config: pytest.Config) -> None:
    state = config.stash.get(_STATE, None)
    if state is None:
        return
    state.patch.undo()
    shutil.rmtree(state.config_dir, ignore_errors=True)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    state = config.stash[_STATE]
    markexpr = config.getoption("markexpr", "") or ""
    has_real_key = bool(state.real_key) and state.real_key != PLACEHOLDER_KEY
    for item in items:
        if item.get_closest_marker("network") is None:
            continue
        if not network_selected_explicitly(markexpr, item.iter_markers()):
            item.add_marker(pytest.mark.skip(reason=NETWORK_OPT_IN_REASON))
        elif not has_real_key:
            item.add_marker(pytest.mark.skip(reason=NO_KEY_REASON))
        else:
            item.stash[_RELEASED] = True


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None):
    """Scope the guard to the item being run: setup, call and teardown.

    Fixtures of every scope are set up and torn down inside some item's
    protocol, so this is what covers a module-scoped fixture. An opted-in
    ``network`` test gets the caller's environment and the real sockets back
    for exactly its own protocol; everything else runs with no key at all.
    """
    state = item.config.stash[_STATE]
    state.current = item.nodeid
    try:
        if _released(item):
            state.patch.undo()
            try:
                return (yield)
            finally:
                _install(state)
        with pytest.MonkeyPatch.context() as patch:
            patch.delenv("ANTHROPIC_API_KEY", raising=False)
            return (yield)
    finally:
        state.current = _OUTSIDE_ANY_TEST


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    """Keep every fixture on one side of the network boundary.

    pytest caches a module- or session-scoped fixture for every later test that
    asks for it, so across the boundary a credential-bearing object made in an
    opted-in test reached a hermetic one, its finalizer (a canary's remote
    cleanup, say) ran under the guard and was refused, and a network test got a
    fixture built without credentials. So when the next item is on the other
    side, the whole fixture stack comes down now, inside this item's protocol:
    every finalizer runs where its fixture was made, and the next item rebuilds
    what it needs on its own side. Only a session mixing both sides pays for it.

    ``teardown_exact(None)`` is what pytest runs after its last item: it pops the
    whole stack even when a finalizer raises, so pytest's own teardown, which
    runs next, finds nothing left. ``_setupstate`` is not public API; if a pytest
    upgrade moves it, this raises in exactly the sessions it protects and
    ``test_a_fixture_never_crosses_the_network_boundary`` fails.
    """
    if nextitem is not None and _released(item) != _released(nextitem):
        item.session._setupstate.teardown_exact(None)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    if call.when == "teardown":
        attempts = item.config.stash[_STATE].drain(item.nodeid)
        if attempts:
            message = _describe(attempts)
            if report.failed:  # keep the teardown's own error; add ours beside it
                report.sections.append(("hermetic guard", message))
            else:
                report.outcome = "failed"
                report.longrepr = message
    return report


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run for attempts no test owned (at import time, for instance)."""
    state = session.config.stash.get(_STATE, None)
    attempts = state.drain() if state is not None else []
    if not attempts:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "hermetic guard", red=True)
        reporter.write_line(_describe(attempts))
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
