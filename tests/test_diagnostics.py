"""Tests for the run-diagnostics module.

Covers the duck-typed locator extractors (status / request-id / exception
summary) that turn a transient SDK failure into an attributable log line, and
the best-effort file-logging configuration (idempotent, disable-able, advisory).
"""
from __future__ import annotations

import pytest

from drawing_analyzer import diagnostics


@pytest.fixture(autouse=True)
def _reset_diag():
    """Each test starts and ends with no file handler configured."""
    diagnostics.reset_for_tests()
    yield
    diagnostics.reset_for_tests()


# --------------------------------------------------------------------------- #
# Locator extraction
# --------------------------------------------------------------------------- #


class _Headers:
    def __init__(self, mapping):
        self._m = mapping

    def get(self, key, default=None):
        return self._m.get(key, default)


def _obj(**attrs):
    return type("_Fake", (), attrs)()


def test_status_of_reads_status_code_then_status():
    assert diagnostics.status_of(_obj(status_code=503)) == 503
    assert diagnostics.status_of(_obj(status=500)) == 500
    assert diagnostics.status_of(RuntimeError("no status")) is None


def test_request_id_prefers_public_then_private_then_headers():
    assert diagnostics.request_id_of(_obj(request_id="req_public")) == "req_public"
    assert diagnostics.request_id_of(_obj(_request_id="req_private")) == "req_private"
    from_headers = _obj(response=_obj(headers=_Headers({"request-id": "req_hdr"})))
    assert diagnostics.request_id_of(from_headers) == "req_hdr"
    assert diagnostics.request_id_of(RuntimeError("nothing")) is None


def test_summarize_exc_captures_locators_and_strips_html():
    class Boom(Exception):
        status_code = 503
        request_id = "req_abc123"
        message = "<html><body>503 Service <b>Unavailable</b></body></html>"

    summary = diagnostics.summarize_exc(Boom("ignored repr"))
    assert "Boom" in summary
    assert "status=503" in summary
    assert "request_id=req_abc123" in summary
    # The HTML error page is reduced to readable text, never dumped verbatim.
    assert "<html>" not in summary and "<b>" not in summary
    assert "503 Service Unavailable" in summary


def test_summarize_exc_plain_exception():
    summary = diagnostics.summarize_exc(RuntimeError("boom upload"))
    assert summary.startswith("RuntimeError")
    assert "boom upload" in summary
    assert "status=" not in summary and "request_id=" not in summary


# --------------------------------------------------------------------------- #
# File logging
# --------------------------------------------------------------------------- #


def test_configure_writes_detailed_lines(tmp_path):
    path = tmp_path / "diag.log"
    assert diagnostics.configure_file_logging(path) == path
    assert diagnostics.configured_log_path() == path

    log = diagnostics.get_logger()
    log.warning("files-api upload FAILED status=503 request_id=req_xyz")
    log.info("batch submitted: id=batch_42 items=8")

    text = path.read_text(encoding="utf-8")
    assert "req_xyz" in text and "status=503" in text
    assert "batch_42" in text


def test_configure_is_idempotent(tmp_path):
    first = diagnostics.configure_file_logging(tmp_path / "a.log")
    second = diagnostics.configure_file_logging(tmp_path / "b.log")
    assert first == second == (tmp_path / "a.log")  # second call no-ops


def test_disabled_via_env_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(diagnostics.ENV_DIAGNOSTICS, "0")
    assert diagnostics.configure_file_logging(tmp_path / "x.log") is None
    assert diagnostics.configured_log_path() is None
    # The logger stays usable (NullHandler); it just produces no file.
    diagnostics.get_logger().info("dropped on the floor")
    assert not (tmp_path / "x.log").exists()


def test_logging_failure_is_swallowed(tmp_path):
    # Point the log at a path whose parent is a *file*, so handler creation
    # raises — diagnostics must degrade to a no-op, never propagate.
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    assert diagnostics.configure_file_logging(blocker / "diag.log") is None
    assert diagnostics.configured_log_path() is None
