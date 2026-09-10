"""Tests for the run-diagnostics module.

Covers the duck-typed locator extractors (status / request-id / exception
summary) that turn a transient SDK failure into an attributable log line, and
the best-effort file-logging configuration (idempotent, disable-able, advisory).
"""
from __future__ import annotations

import logging

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


def test_configure_keeps_only_the_latest_run(tmp_path):
    # A prior session's log (and a stale rotation backup) must not survive: the
    # file holds only the latest run. Simulate two launches at the same path.
    path = tmp_path / "diag.log"
    path.write_text("SESSION-ONE line that must be gone\n", encoding="utf-8")
    stale_backup = tmp_path / "diag.log.1"
    stale_backup.write_text("SESSION-ONE rotated overflow\n", encoding="utf-8")

    assert diagnostics.configure_file_logging(path) == path
    diagnostics.get_logger().info("SESSION-TWO fresh line")

    text = path.read_text(encoding="utf-8")
    assert "SESSION-ONE" not in text          # prior session truncated away
    assert "SESSION-TWO fresh line" in text    # current session captured
    assert not stale_backup.exists()           # stale rotation backup removed


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


# --------------------------------------------------------------------------- #
# Secret redaction (Phase 17) — the shared pre-serialization boundary.
# --------------------------------------------------------------------------- #


# These fixtures assemble their secret-SHAPED values at runtime from fragments
# so the SOURCE never contains a contiguous token that pattern-matches a live
# credential (keeps secret scanners quiet). Nothing here is a real key; the
# whole point is to prove the redactor masks such shapes in logs.
_ANT = "sk-" + "ant-"            # the Anthropic key prefix, never a whole token


def _fake_key(tag: str) -> str:
    return _ANT + tag


def test_redact_secrets_masks_anthropic_key_anywhere():
    key = _fake_key("api03-AbC_12-xyz")
    out = diagnostics.redact_secrets(f"using key {key} now")
    assert key not in out
    assert "sk-ant-[REDACTED]" in out


def test_redact_secrets_masks_named_fields_and_bearer():
    secret = _fake_key("secret")
    assert secret not in diagnostics.redact_secrets("x-api-key: " + secret)
    bearer = "abc" + ".def.ghi"
    assert diagnostics.redact_secrets("Authorization: Bearer " + bearer).endswith(
        "[REDACTED]"
    )
    top = "top" + "secret"
    assert top not in diagnostics.redact_secrets('{"api_key": "' + top + '"}')
    pw = "hunter" + "2"
    assert pw not in diagnostics.redact_secrets("password=" + pw + "&next=1")


def test_redact_secrets_preserves_token_counts():
    # `token` is word-bounded, so a token COUNT is never mistaken for a secret.
    text = "usage input_tokens=1234 output_tokens=56"
    assert diagnostics.redact_secrets(text) == text


def test_redacting_formatter_masks_message_args_and_exceptions(tmp_path):
    path = tmp_path / "diag.log"
    assert diagnostics.configure_file_logging(path) == path
    log = diagnostics.get_logger()

    arg_key = _fake_key("arg-3xampl3")
    exc_key = _fake_key("in-exc-9")
    log.info("key via arg: %s", arg_key)
    try:
        raise RuntimeError("boom with x-api-key: " + exc_key)
    except RuntimeError:
        log.exception("request failed")

    text = path.read_text(encoding="utf-8")
    assert arg_key not in text
    assert exc_key not in text
    assert "sk-ant-[REDACTED]" in text
    # Non-secret content still lands so the log stays useful.
    assert "request failed" in text


def test_nested_dict_repr_secrets_are_redacted():
    nested = _fake_key("nested-key")
    payload = {"headers": {"x-api-key": nested, "accept": "json"}}
    out = diagnostics.redact_secrets(str(payload))
    assert nested not in out
    assert "accept" in out            # unrelated fields survive


# --------------------------------------------------------------------------- #
# N18: a base64-heavy SDK record must not flush the diagnostics ring.
#
# The ring is _MAX_BYTES x _BACKUP_COUNT and one sheet's base64 request body
# measures ~3 MB against a 2 MB rotation cap, so in DEBUG mode a SINGLE sheet
# rotated the ring and six flushed every backup: the trace was destroyed by its
# own payload, exactly when it was being collected to explain a failure.
# --------------------------------------------------------------------------- #


def _b64_blob(n_chars: int) -> str:
    import base64
    import os

    raw = base64.b64encode(os.urandom(n_chars)).decode()
    return raw[:n_chars]


def test_a_long_base64_blob_is_elided_with_its_size():
    blob = _b64_blob(80_000)
    out = diagnostics.elide_blobs(f'{{"type":"image","source":{{"data":"{blob}"}}}}')
    assert blob not in out
    assert "80000 chars elided" in out
    # The request SHAPE survives — that is the whole point of wire capture.
    assert '"type":"image"' in out and '"source"' in out


def test_short_identifiers_are_never_elided():
    # A request id, a file id, a sha256 — all identifier-shaped and all far
    # below the threshold. Eliding these would gut the trace to fix the payload.
    sha = "a" * 64
    text = f"request_id=req_011CQ file_id=file_0123456789 sha256={sha}"
    assert diagnostics.elide_blobs(text) == text


def test_one_sheet_of_base64_no_longer_rotates_the_ring(tmp_path):
    import logging

    path = tmp_path / "diag.log"
    assert diagnostics.configure_file_logging(path, capture_sdk=True) == path
    log = diagnostics.get_logger()
    for i in range(12):
        log.info("run marker %d", i)

    # Ten sheets' worth of DEBUG request bodies, each ~3 MB of base64.
    body = "".join(
        f'{{"type":"image","source":{{"data":"{_b64_blob(80_000)}"}}}},'
        for _ in range(37)
    )
    assert len(body) > diagnostics._MAX_BYTES      # one record exceeds the cap
    sdk = logging.getLogger("anthropic")
    for _ in range(10):
        sdk.debug("Request options: %s", body)

    # Nothing rotated: no backup files, and every marker still readable.
    assert sorted(p.name for p in tmp_path.iterdir()) == ["diag.log"]
    text = path.read_text(encoding="utf-8", errors="replace")
    assert text.count("run marker") == 12
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) < diagnostics._MAX_BYTES


def test_a_huge_non_base64_record_is_truncated_and_says_so():
    # The backstop: a record can be enormous without being base64 (a giant
    # traceback, an HTML error page), and the ring still cannot defend itself.
    formatter = diagnostics.RedactingFormatter("%(message)s")
    record = logging.LogRecord(
        "anthropic", logging.DEBUG, __file__, 1,
        "x y " * diagnostics._MAX_RECORD_CHARS, (), None,
    )
    out = formatter.format(record)
    assert len(out) < diagnostics._MAX_RECORD_CHARS + 200
    assert "more chars truncated" in out


def test_secrets_are_still_redacted_after_eliding(tmp_path):
    # Elision is a volume control, never a secret control: the mandatory
    # boundary must still hold on whatever survives it.
    key = _fake_key("after-elide")
    text = f'{{"data":"{_b64_blob(80_000)}","x-api-key":"{key}"}}'
    formatter = diagnostics.RedactingFormatter("%(message)s")
    record = logging.LogRecord("anthropic", logging.DEBUG, __file__, 1, text, (), None)
    out = formatter.format(record)
    assert key not in out
    assert "chars elided" in out


# --------------------------------------------------------------------------- #
# Prefixed secret field names redact (N10)
# --------------------------------------------------------------------------- #


def test_prefixed_env_var_names_are_redacted():
    # A leading \\b cannot match inside ANTHROPIC_API_KEY: the character before
    # API is "_", itself a word character, so the NAME rule never fired on the
    # commonest spelling of all. It only looked covered because the sk-ant- VALUE
    # pattern caught real Anthropic keys — a credential of any other shape went to
    # disk in full.
    from drawing_analyzer.diagnostics import redact_secrets

    secret = "zzzzzzzzzzzzzzzzzzzzzzzzzzzz"
    for line in (
        f"ANTHROPIC_API_KEY={secret}",
        f"ANTHROPIC_AUTH_TOKEN={secret}",
        f"MY_ANTHROPIC_AUTH_TOKEN={secret}",
        f"DRAWING_ANALYZER_ANTHROPIC_API_KEY={secret}",
        f"export SOME_DEEP_PREFIX_ACCESS_TOKEN={secret}",
        f"'anthropic_api_key': '{secret}'",
    ):
        out = redact_secrets(line)
        assert secret not in out, f"leaked: {out}"


def test_redaction_keeps_the_variable_name_it_redacted():
    # Consuming the prefix unnamed would rewrite ANTHROPIC_API_KEY=… as
    # API_KEY=[REDACTED] and lose which variable it was — the log line has to stay
    # diagnosable.
    from drawing_analyzer.diagnostics import redact_secrets

    out = redact_secrets("DRAWING_ANALYZER_ANTHROPIC_API_KEY=zzzzzzzzzzzzzzzz")
    assert out.startswith("DRAWING_ANALYZER_ANTHROPIC_API_KEY=")
    assert "[REDACTED]" in out


def test_token_counts_are_not_mistaken_for_credentials():
    # The non-regression that matters: `token` is word-bounded so a count survives.
    from drawing_analyzer.diagnostics import redact_secrets

    assert redact_secrets("input_tokens=1234") == "input_tokens=1234"
    assert redact_secrets("output_tokens=99, cache_read_input_tokens=5") == (
        "output_tokens=99, cache_read_input_tokens=5"
    )
