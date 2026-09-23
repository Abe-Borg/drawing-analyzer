"""WP-02.1 (U26): the hermetic boundary every non-``network`` test runs inside.

``tests/fixtures/hermetic_guard.py`` (registered by ``tests/conftest.py``) makes
the suite's hermeticity a property the harness *enforces* instead of one the
tests merely promise. These tests pin each part of it:

* **Sockets.** ``socket.socket.connect`` / ``connect_ex`` and the forward name
  lookups refuse any destination that is not loopback or ``AF_UNIX``. That is
  the layer every HTTP client this project uses goes through — the SDK's
  ``httpx2`` sync transport and ``urllib`` both call
  ``socket.create_connection`` — while asyncio's self-pipe and Playwright's
  pipes, which the browser suite needs, stay usable.
* **A swallowed attempt still fails the test.** The I-3 stage guards catch
  their own exceptions by design, so a raise alone would let a pipeline test
  that tried to reach the API stay green. Every blocked attempt is recorded and
  turns the test's teardown into an error.
* **Ambient configuration is removed.** A loopback proxy is allowed by the
  socket rule, so traffic escaped through an exported ``HTTPS_PROXY`` when only
  sockets were guarded. And a zero-arg ``Anthropic()`` resolves far more than
  ``ANTHROPIC_API_KEY``: an auth token, a named profile, workload-identity
  federation, custom headers, or an ``ant auth login`` profile on disk.
* **The whole run is covered, not only test bodies.** The gauntlet's
  module-scoped ``oracle`` fixture runs the entire exhaustive pipeline before
  any function-scoped fixture exists.
* **``network`` is an explicit opt-in.** An exported real key no longer runs
  the live canary by itself: the ``-m`` expression has to select the test
  because of its ``network`` marker.

The addresses probed are reserved and can never be a real service:
``192.0.2.1`` is RFC 5737 TEST-NET-1 and ``.invalid`` is an RFC 6761 name that
never resolves.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import re
import socket
import sys
import tempfile
import textwrap
import urllib.request
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GUARD_MODULE = "tests.fixtures.hermetic_guard"
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

_EXTERNAL_IP = "192.0.2.1"
_EXTERNAL_NAME = "hermetic-guard-probe.invalid"

# The collection-time placeholder documented in the guard. Kept as a literal
# here (and cross-checked in-process) so the subprocess sessions below can be
# run against a checkout that predates the guard.
_PLACEHOLDER = "test-key-not-real-do-not-use"
# Deliberately not credential-shaped: ``scripts/scan_secrets.py`` flags
# ``sk-ant-`` followed by 30+ characters (see ``tests/test_run_acceptance.py``).
_INNER_KEY = "not-a-real-key-hermetic-inner"


def _guard():
    """Import the guard lazily, so each test fails on its own without it."""
    return importlib.import_module(_GUARD_MODULE)


def _drained(request) -> list[tuple[str, str]]:
    """Consume this test's recorded attempts (so teardown does not flag them)."""
    attempts = _guard().drain_blocked_attempts(request.config)
    assert all(a.during == request.node.nodeid for a in attempts), attempts
    return [(a.operation, a.destination) for a in attempts]


# --------------------------------------------------------------------------- #
# 1. Sockets: external destinations are refused and recorded
# --------------------------------------------------------------------------- #


def test_the_suite_runs_inside_the_guard(request):
    guard = _guard()
    assert request.config.pluginmanager.has_plugin(_GUARD_MODULE)
    assert guard.PLACEHOLDER_KEY == _PLACEHOLDER


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_an_external_tcp_connect_is_refused_and_recorded(request, method):
    guard = _guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(guard.ExternalNetworkBlocked, match=re.escape(_EXTERNAL_IP)):
            getattr(sock, method)((_EXTERNAL_IP, 443))
    finally:
        sock.close()
    assert _drained(request) == [(method, f"{_EXTERNAL_IP}:443")]


def test_external_name_resolution_is_refused_and_recorded(request):
    guard = _guard()
    with pytest.raises(guard.ExternalNetworkBlocked):
        socket.getaddrinfo(_EXTERNAL_NAME, 443)
    with pytest.raises(guard.ExternalNetworkBlocked):
        socket.gethostbyname(_EXTERNAL_NAME)
    with pytest.raises(guard.ExternalNetworkBlocked):
        socket.gethostbyname_ex(_EXTERNAL_NAME)
    assert _drained(request) == [
        ("getaddrinfo", f"{_EXTERNAL_NAME}:443"),
        ("gethostbyname", _EXTERNAL_NAME),
        ("gethostbyname_ex", _EXTERNAL_NAME),
    ]


def test_a_swallowed_attempt_is_still_recorded(request):
    """The I-3 shape: a stage catches ``Exception`` and carries on."""
    _guard()
    try:
        socket.create_connection((_EXTERNAL_IP, 443), timeout=1)
    except Exception:  # noqa: BLE001 - the point: the caller swallows it
        pass
    assert _drained(request) == [("getaddrinfo", f"{_EXTERNAL_IP}:443")]


def test_the_sdk_transport_cannot_leave_the_machine(request):
    """A real SDK request is refused at the socket layer, never sent."""
    guard = _guard()
    import anthropic

    client = anthropic.Anthropic(api_key=_INNER_KEY, max_retries=0)
    with pytest.raises(anthropic.APIConnectionError) as info:
        client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1,
            messages=[{"role": "user", "content": "x"}],
        )
    assert isinstance(info.value.__cause__, guard.ExternalNetworkBlocked)
    assert _drained(request) == [("getaddrinfo", "api.anthropic.com:443")]


def test_urllib_cannot_leave_the_machine(request):
    """The updater's transport (``core/updates.py``) is covered too."""
    guard = _guard()
    with pytest.raises(guard.ExternalNetworkBlocked):
        urllib.request.urlopen(f"https://{_EXTERNAL_NAME}/", timeout=1)
    assert _drained(request) == [("getaddrinfo", f"{_EXTERNAL_NAME}:443")]


# --------------------------------------------------------------------------- #
# 2. Local traffic keeps working (the browser suite and asyncio depend on it)
# --------------------------------------------------------------------------- #


def test_loopback_tcp_and_socketpair_still_work():
    _guard()
    with socket.create_server(("127.0.0.1", 0)) as server:
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            conn, _ = server.accept()
            with conn:
                client.sendall(b"ping")
                assert conn.recv(4) == b"ping"
        assert socket.getaddrinfo("localhost", port, type=socket.SOCK_STREAM)
    left, right = socket.socketpair()  # asyncio's self-pipe; loopback TCP on Windows
    with left, right:
        left.sendall(b"x")
        assert right.recv(1) == b"x"


def test_ipv6_loopback_still_works():
    _guard()
    if not socket.has_ipv6:
        pytest.skip("no IPv6 support in this Python build")
    try:
        server = socket.create_server(("::1", 0), family=socket.AF_INET6)
    except OSError as exc:
        pytest.skip(f"IPv6 loopback unavailable here: {exc}")
    with server:
        port = server.getsockname()[1]
        with socket.create_connection(("::1", port), timeout=5):
            server.accept()[0].close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX on this platform")
def test_unix_domain_sockets_still_work():
    _guard()
    # A short directory: AF_UNIX paths are capped near 100 bytes.
    with tempfile.TemporaryDirectory(prefix="hg") as tmp:
        path = os.path.join(tmp, "s")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(path)
            server.listen(1)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(path)
                server.accept()[0].close()


def test_asyncio_loopback_still_works():
    """Playwright's sync API runs on an asyncio loop inside the test process."""
    _guard()

    async def _roundtrip() -> bytes:
        async def _echo(reader, writer):
            writer.write(await reader.read(4))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(_echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            reader, writer = await asyncio.open_connection("localhost", port)
            writer.write(b"pong")
            await writer.drain()
            data = await reader.read(4)
            writer.close()
            await writer.wait_closed()
            return data

    assert asyncio.run(_roundtrip()) == b"pong"


@pytest.mark.parametrize(
    ("host", "local"),
    [
        (None, True),
        ("", True),
        ("localhost", True),
        ("LocalHost", True),
        ("localhost.", True),
        (b"localhost", True),
        ("127.0.0.1", True),
        ("127.8.9.10", True),
        ("::1", True),
        ("[::1]", True),
        ("::ffff:127.0.0.1", True),
        ("0.0.0.0", True),
        ("::", True),
        (_EXTERNAL_IP, False),
        ("10.0.0.1", False),
        ("192.168.1.10", False),
        ("::ffff:192.0.2.1", False),
        ("api.anthropic.com", False),
        ("localhost.example.com", False),
        ("127.0.0.1.nip.io", False),
        (_EXTERNAL_NAME, False),
        (12345, False),
    ],
)
def test_local_host_classification(host, local):
    assert _guard().is_local_host(host) is local


# --------------------------------------------------------------------------- #
# 3. Ambient configuration is gone inside a hermetic test
# --------------------------------------------------------------------------- #


def test_no_proxy_configuration_survives():
    _guard()
    leftovers = sorted(
        name for name in os.environ
        if name.lower().endswith("_proxy") and name.lower() != "no_proxy"
    )
    assert leftovers == []
    assert os.environ.get("NO_PROXY") == "*"
    # ``getproxies`` is what both urllib and httpx2 consult. A non-empty
    # ``no_proxy`` also stops its fallback to the Windows registry / macOS
    # system configuration, which an environment scrub alone would not reach.
    assert not {"http", "https", "all"} & set(urllib.request.getproxies())


def test_no_ambient_anthropic_credentials_survive():
    _guard()
    import anthropic

    ambient = sorted(
        name for name in os.environ
        if name.upper().startswith("ANTHROPIC_") and name.upper() != "ANTHROPIC_CONFIG_DIR"
    )
    assert ambient == []
    config_dir = Path(os.environ["ANTHROPIC_CONFIG_DIR"])
    assert config_dir.is_dir() and not any(config_dir.iterdir())
    # Fail closed: with an explicit, empty config dir the SDK refuses to build a
    # zero-arg client at all, so no ambient profile can be picked up.
    with pytest.raises(anthropic.CredentialsError):
        anthropic.Anthropic()


# --------------------------------------------------------------------------- #
# 4. The network opt-in rule
# --------------------------------------------------------------------------- #


_NET = pytest.mark.network.mark
_BROWSER = pytest.mark.browser.mark


@pytest.mark.parametrize(
    ("markexpr", "marks", "selected"),
    [
        ("network", [_NET], True),
        ("(network)", [_NET], True),
        ("network and not browser", [_NET], True),
        ("not not network", [_NET], True),
        # Not selected *because of* the network marker (or not at all): no opt-in.
        ("", [_NET], False),
        ("not browser", [_NET], False),
        ("network or not network", [_NET], False),
        ("browser", [_NET, _BROWSER], False),
        ("network or browser", [_NET, _BROWSER], False),
        ("not network", [_NET], False),
    ],
)
def test_network_needs_an_explicit_marker_selection(markexpr, marks, selected):
    assert _guard().network_selected_explicitly(markexpr, marks) is selected


# --------------------------------------------------------------------------- #
# 5. Whole-run behaviour, proven in a fresh pytest session
# --------------------------------------------------------------------------- #
#
# These run the repository's real ``tests/conftest.py`` in a subprocess against
# small synthetic test files, with the ambient environment a developer's shell
# might carry injected into it. A subprocess is the only honest way to test what
# happens at collection, in module-scoped fixtures and across a whole run.

_INNER_ENV_FILE = """
import os
from pathlib import Path

import pytest

AT_IMPORT = os.environ.get("ANTHROPIC_API_KEY")


def test_collection_saw_only_the_placeholder_key():
    assert AT_IMPORT == {placeholder!r}


def test_no_key_inside_a_hermetic_test():
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_no_ambient_proxy():
    import urllib.request

    leftovers = sorted(
        n for n in os.environ if n.lower().endswith("_proxy") and n.lower() != "no_proxy"
    )
    assert leftovers == []
    assert not {{"http", "https", "all"}} & set(urllib.request.getproxies())


def test_no_ambient_anthropic_configuration():
    ambient = sorted(
        n for n in os.environ
        if n.upper().startswith("ANTHROPIC_") and n.upper() != "ANTHROPIC_CONFIG_DIR"
    )
    assert ambient == []
    config_dir = Path(os.environ["ANTHROPIC_CONFIG_DIR"])
    assert config_dir != Path({ambient_config_dir!r})
    assert config_dir.is_dir() and not any(config_dir.iterdir())


def test_zero_arg_client_resolves_nothing():
    import anthropic

    with pytest.raises(anthropic.CredentialsError):
        anthropic.Anthropic()
"""

_INNER_NETWORK_FILE = """
import os
import socket

import pytest


@pytest.mark.network
def test_live_canary_stand_in():
    # Reached only when opted in: the caller's own environment is back and the
    # socket guard is lifted (a numeric lookup sends nothing, but the guard
    # would refuse it).
    assert os.environ.get("ANTHROPIC_API_KEY") == {key!r}
    assert os.environ.get("HTTPS_PROXY") == {proxy!r}
    socket.getaddrinfo("192.0.2.1", 443, type=socket.SOCK_STREAM)
"""

_INNER_SWALLOW_FILE = """
import socket

import pytest


@pytest.fixture(scope="module")
def leaky():
    # A module-scoped fixture runs before any function-scoped one exists.
    try:
        socket.create_connection(("192.0.2.1", 443), timeout=0.2)
    except Exception:
        pass
    return 1


def test_uses_a_leaky_module_fixture(leaky):
    assert leaky == 1


def test_swallows_an_attempt_in_its_body():
    try:
        socket.getaddrinfo("hermetic-guard-probe.invalid", 443)
    except Exception:
        pass


@pytest.fixture
def breaks_on_teardown():
    yield
    try:
        socket.getaddrinfo("teardown-probe.invalid", 443)
    except Exception:
        pass
    raise RuntimeError("the fixture's own teardown failure")


def test_a_teardown_that_already_failed(breaks_on_teardown):
    pass
"""

_INNER_PROXY_FILE = """
import anthropic
import pytest


def test_sdk_request_does_not_take_the_ambient_proxy():
    client = anthropic.Anthropic(api_key={key!r}, max_retries=0, timeout=2.0)
    with pytest.raises(anthropic.APIConnectionError):
        client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1,
            messages=[{{"role": "user", "content": "x"}}],
        )
"""


def _pending_connections(server: socket.socket) -> int:
    """How many clients connected to ``server`` (accepted and closed here)."""
    server.setblocking(False)
    count = 0
    while True:
        try:
            conn, _ = server.accept()
        except (BlockingIOError, InterruptedError):
            return count
        conn.close()
        count += 1


@pytest.fixture
def fake_proxy():
    """A loopback listener standing in for a developer's local proxy.

    It never answers, so nothing that reaches it can go further. A connection
    arriving here is the escape the plan's verification reproduced: with only
    the sockets guarded, loopback is allowed and the SDK's traffic left through
    an exported ``HTTPS_PROXY``.
    """
    with socket.create_server(("127.0.0.1", 0)) as server:
        yield server


def _inner_session(pytester, monkeypatch, tmp_path, proxy_port, *args, with_key=True):
    """Run the real ``tests/conftest.py`` in a fresh subprocess session."""
    ambient_config = tmp_path / "ambient-anthropic-config"
    (ambient_config / "configs").mkdir(parents=True)
    (ambient_config / "configs" / "default.json").write_text("{}", encoding="utf-8")
    proxy = f"http://127.0.0.1:{proxy_port}"

    pytester.makeconftest((_REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    pytester.makeini("[pytest]\nmarkers =\n    network: live API access\n")
    pytester.makepyfile(
        test_a_env=_INNER_ENV_FILE.format(
            placeholder=_PLACEHOLDER, ambient_config_dir=str(ambient_config)
        ),
        test_b_network=_INNER_NETWORK_FILE.format(key=_INNER_KEY, proxy=proxy),
        test_c_swallow=_INNER_SWALLOW_FILE,
        test_d_proxy=_INNER_PROXY_FILE.format(key=_INNER_KEY),
    )

    # Start from nothing ambient, then inject what a developer's shell might
    # carry: a proxy, a key, and every other credential source the SDK reads.
    for name in list(os.environ):
        if name.lower().endswith("_proxy") or name.upper().startswith("ANTHROPIC_"):
            monkeypatch.delenv(name, raising=False)
    injected = {
        "HTTPS_PROXY": proxy,
        "HTTP_PROXY": proxy,
        "ALL_PROXY": proxy,
        "ANTHROPIC_AUTH_TOKEN": "not-a-real-token-hermetic-inner",
        "ANTHROPIC_PROFILE": "hermetic-inner-profile",
        "ANTHROPIC_BASE_URL": "https://anthropic-base-url.invalid",
        "ANTHROPIC_CUSTOM_HEADERS": "x-hermetic-probe: 1",
        "ANTHROPIC_IDENTITY_TOKEN": "not-a-real-identity-token",
        "ANTHROPIC_FEDERATION_RULE_ID": "not-a-real-rule",
        "ANTHROPIC_ORGANIZATION_ID": "not-a-real-org",
        "ANTHROPIC_CONFIG_DIR": str(ambient_config),
    }
    if sys.platform != "win32":  # one variable per name on Windows
        injected.update({"https_proxy": proxy, "http_proxy": proxy, "all_proxy": proxy})
    if with_key:
        injected["ANTHROPIC_API_KEY"] = _INNER_KEY
    for name, value in injected.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(filter(None, [str(_REPO_ROOT), os.environ.get("PYTHONPATH")])),
    )
    return pytester.runpytest_subprocess("-p", "no:cacheprovider", "-rA", *args, timeout=300)


def test_a_default_run_is_hermetic_end_to_end(pytester, monkeypatch, tmp_path, fake_proxy):
    """No ``-m``, a real-looking key and a full ambient credential set exported."""
    port = fake_proxy.getsockname()[1]
    result = _inner_session(pytester, monkeypatch, tmp_path, port)
    out = result.stdout.str()

    # 5 environment checks, 3 swallowers and the proxy check pass their bodies;
    # the network test is skipped; the four attempts become teardown errors.
    result.assert_outcomes(passed=9, skipped=1, errors=4)
    assert "network tests are opt-in" in out
    # Named precisely, with the test that made the attempt.
    assert (
        "getaddrinfo 192.0.2.1:443 (during test_c_swallow.py::test_uses_a_leaky_module_fixture)"
        in out
    )  # the module-scoped fixture
    assert f"getaddrinfo {_EXTERNAL_NAME}:443" in out
    assert "getaddrinfo api.anthropic.com:443" in out  # BASE_URL was scrubbed too
    # A teardown that failed on its own keeps its error and gains the guard's.
    assert "the fixture's own teardown failure" in out
    assert "getaddrinfo teardown-probe.invalid:443" in out
    # And the SDK never reached the loopback proxy it would otherwise have used.
    assert _pending_connections(fake_proxy) == 0, out


def test_an_attempt_no_test_owns_fails_the_session(pytester, monkeypatch):
    """An import-time attempt is reported even when no test runs at all."""
    pytester.makeconftest((_REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    pytester.makepyfile(
        test_import_time="""
        import socket

        try:
            socket.getaddrinfo("import-time-probe.invalid", 443)
        except Exception:
            pass


        def test_nothing():
            pass
        """
    )
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join(filter(None, [str(_REPO_ROOT), os.environ.get("PYTHONPATH")])),
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "--collect-only", timeout=300)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    assert "getaddrinfo import-time-probe.invalid:443 (during outside any test)" in (
        result.stdout.str()
    )


def test_an_explicit_network_run_gets_the_callers_environment(
    pytester, monkeypatch, tmp_path, fake_proxy
):
    port = fake_proxy.getsockname()[1]
    result = _inner_session(pytester, monkeypatch, tmp_path, port, "-m", "network")
    result.assert_outcomes(passed=1, deselected=9)


def test_an_explicit_network_run_without_a_key_still_skips(
    pytester, monkeypatch, tmp_path, fake_proxy
):
    port = fake_proxy.getsockname()[1]
    result = _inner_session(
        pytester, monkeypatch, tmp_path, port, "-m", "network", with_key=False
    )
    result.assert_outcomes(skipped=1, deselected=9)
    assert "ANTHROPIC_API_KEY not set" in result.stdout.str()


# --------------------------------------------------------------------------- #
# 6. CI never depends on the opt-in alone
# --------------------------------------------------------------------------- #


def _pytest_invocations(text: str):
    """Yield ``(line_number, command)`` for every pytest command in a workflow."""
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line.startswith("run:"):
            line = line[len("run:"):].strip()
        if line.startswith("#"):
            continue
        if re.match(r"(?:python[\d.]*\s+-m\s+)?pytest\b", line):
            yield number, line


def _marker_expression(command: str) -> str:
    rest = re.split(r"\bpytest\b", command, maxsplit=1)[1]
    found = re.search(r"(?:^|\s)-m\s+(\"[^\"]*\"|'[^']*'|\S+)", rest)
    return found.group(1).strip("\"'") if found else ""


def test_every_workflow_pytest_command_deselects_network():
    """Belt and braces with the opt-in rule, as ``run_acceptance.py`` already is.

    Parsed as text on purpose, like ``tests/test_browser_suite_gate.py``: PyYAML
    is not a dependency, and a structural guard that silently skips is the
    failure it exists to prevent.
    """
    found, offenders = 0, []
    for workflow in sorted(_WORKFLOWS.glob("*.yml")):
        for number, command in _pytest_invocations(workflow.read_text(encoding="utf-8")):
            found += 1
            if not re.search(r"\bnot network\b", _marker_expression(command)):
                offenders.append(f"{workflow.name}:{number}: {command}")
    assert found >= 5, "the workflow scan found too few pytest commands to be trusted"
    assert offenders == [], "pytest commands without -m '... not network':\n" + "\n".join(
        offenders
    )


def test_the_marker_scanner_reads_quoted_and_bare_expressions():
    assert _marker_expression('python -m pytest -q -m "not network" tests/x.py') == "not network"
    assert _marker_expression("python -m pytest -q -m browser --junitxml=a.xml") == "browser"
    assert _marker_expression("python -m pytest -q") == ""
    assert _marker_expression("pytest -m 'a and not network'") == "a and not network"
    assert list(_pytest_invocations(textwrap.dedent("""\
        - name: x
          run: python -m pytest -q
        # python -m pytest in a comment
          run: |
            python -m playwright install chromium
            python -m pytest -q -m "not network"
    """))) == [(2, "python -m pytest -q"), (6, 'python -m pytest -q -m "not network"')]
