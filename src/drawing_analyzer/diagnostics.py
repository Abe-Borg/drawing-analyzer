"""Persistent, request-level run diagnostics for the drawing analyzer.

The GUI activity log is live and summary-level: it scrolls away and never
records the detail needed to explain a *partial* run after the fact — which
image upload 503'd, the Anthropic ``request-id`` to quote in a support ticket,
the batch id to look up in the console, the per-item ``custom_id`` → sheet map.
This module writes a verbose, timestamped trace to a rotating file under the app
config dir so a flaky run is fully reconstructable later.

Design (standard "library" logging pattern):

- A single named logger (:data:`LOGGER_NAME`) carries a :class:`NullHandler` and
  ``propagate=False``, so importing this module (and the modules that log to it)
  is side-effect-free — nothing is written until the *application* opts in via
  :func:`configure_file_logging`. Hermetic tests that never call it produce no
  file and no stderr noise.
- The GUI calls :func:`configure_file_logging` once at startup. With
  ``DRAWING_ANALYZER_DEBUG`` truthy it also attaches the same handler to the
  ``anthropic`` / ``httpx`` loggers at DEBUG, so the file additionally captures
  the SDK's wire-level request/response lines — the real status codes,
  request-ids, and retry attempts behind a 503/500.

Nothing here ever raises into the pipeline: diagnostics are advisory, so a
logging-setup failure (read-only disk, etc.) is swallowed and can never turn a
working run into a failed one.
"""
from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .core.app_paths import app_config_dir

LOGGER_NAME = "drawing_analyzer.diagnostics"
LOG_FILENAME = "drawing_analyzer.log"

# Off-switch (parity with the disable-token convention used elsewhere in the
# app): file logging is ON by default and only suppressed when this is set to a
# disable token. ``DRAWING_ANALYZER_DEBUG`` additionally routes the Anthropic
# SDK's own loggers into the same file.
ENV_DIAGNOSTICS = "DRAWING_ANALYZER_DIAGNOSTICS"
ENV_DEBUG = "DRAWING_ANALYZER_DEBUG"

_DISABLE_TOKENS = frozenset({"", "0", "false", "no", "off"})

# Bounded on-disk footprint: 2 MB × 5 rotations. A run emits a few hundred short
# lines, so this holds many runs' worth of history without unbounded growth.
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 5

_HTML_TAG_RE = re.compile(r"<[^>]+>")

_logger = logging.getLogger(LOGGER_NAME)
_logger.addHandler(logging.NullHandler())  # silent until the app configures a file
_logger.propagate = False
_logger.setLevel(logging.DEBUG)

# Loggers the SDK emits under; we attach our file handler to these only in debug
# mode so the trace can include raw HTTP attempts/retries behind a transient 5xx.
_SDK_LOGGER_NAMES = ("anthropic", "httpx", "httpcore")

_configured = False
_log_path: Path | None = None


def get_logger() -> logging.Logger:
    """Return the shared diagnostics logger (safe to call at import time)."""
    return _logger


def _truthy(raw: str | None) -> bool:
    return raw is not None and raw.strip().lower() not in _DISABLE_TOKENS


def diagnostics_enabled() -> bool:
    """File logging is on unless ``DRAWING_ANALYZER_DIAGNOSTICS`` disables it."""
    raw = os.environ.get(ENV_DIAGNOSTICS)
    if raw is None:
        return True
    return raw.strip().lower() not in _DISABLE_TOKENS


def log_dir() -> Path:
    """The directory diagnostics files live in (created on demand)."""
    d = app_config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_log_path() -> Path:
    """The default diagnostics log path under the app config dir."""
    return log_dir() / LOG_FILENAME


def configured_log_path() -> Path | None:
    """Where file logging is currently writing, or ``None`` if not configured."""
    return _log_path


def configure_file_logging(
    path: str | os.PathLike[str] | None = None,
    *,
    capture_sdk: bool | None = None,
) -> Path | None:
    """Attach a rotating file handler so a run leaves a detailed on-disk trace.

    Idempotent and best-effort: a second call is a no-op, and any setup failure
    (read-only disk, etc.) is swallowed — diagnostics must never turn a working
    run into a failed one. Returns the active log path, or ``None`` when disabled
    via :func:`diagnostics_enabled` or when setup failed.

    ``path`` defaults to :func:`default_log_path`. ``capture_sdk`` defaults to
    the ``DRAWING_ANALYZER_DEBUG`` env: when true, the same handler is attached
    to the ``anthropic`` / ``httpx`` loggers at DEBUG so the file also captures
    the SDK's wire-level request/response lines (status codes, request-ids, and
    the retry attempts behind a 503/500).
    """
    global _configured, _log_path
    if _configured:
        return _log_path
    if not diagnostics_enabled():
        _configured = True
        return None
    try:
        target = Path(path) if path is not None else default_log_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            target, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        handler.setLevel(logging.DEBUG)
        _logger.addHandler(handler)

        if capture_sdk is None:
            capture_sdk = _truthy(os.environ.get(ENV_DEBUG))
        if capture_sdk:
            for name in _SDK_LOGGER_NAMES:
                sdk_logger = logging.getLogger(name)
                sdk_logger.addHandler(handler)
                if sdk_logger.level == logging.NOTSET or sdk_logger.level > logging.DEBUG:
                    sdk_logger.setLevel(logging.DEBUG)

        _log_path = target
        _configured = True
        _logger.info(
            "diagnostics file logging started (sdk_wire_logs=%s)", bool(capture_sdk)
        )
        return target
    except Exception:  # noqa: BLE001 - diagnostics are advisory, never fatal
        _configured = True
        _log_path = None
        return None


def reset_for_tests() -> None:
    """Drop the file handler(s) and allow reconfiguration. Test hook only."""
    global _configured, _log_path
    for handler in list(_logger.handlers):
        if not isinstance(handler, logging.NullHandler):
            _logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
    _configured = False
    _log_path = None


# ---------------------------------------------------------------------------
# Duck-typed extractors for the locators that matter when reporting a failure.
# Matched defensively so this module needs no hard import of the anthropic
# exception types and works on plain-dict / fake shapes in tests.
# ---------------------------------------------------------------------------


def status_of(obj: Any) -> int | None:
    """Best-effort HTTP status carried by an SDK response or error."""
    for attr in ("status_code", "status"):
        val = getattr(obj, attr, None)
        if isinstance(val, int):
            return val
    return None


def request_id_of(obj: Any) -> str | None:
    """Best-effort Anthropic ``request-id`` from an SDK response or error.

    The SDK exposes ``request_id`` on ``APIError`` and ``_request_id`` on
    response models (populated from the ``request-id`` header); we also peek at a
    ``.response`` headers map. Batch-result messages and plain-dict shapes may
    carry none — returns ``None`` then, and the batch id + ``custom_id`` are the
    locators instead.
    """
    for attr in ("request_id", "_request_id"):
        val = getattr(obj, attr, None)
        if isinstance(val, str) and val:
            return val
    headers = getattr(getattr(obj, "response", None), "headers", None)
    if headers is not None:
        try:
            rid = headers.get("request-id") or headers.get("x-request-id")
        except Exception:  # noqa: BLE001
            rid = None
        if isinstance(rid, str) and rid:
            return rid
    return None


def _short(text: str, limit: int = 400) -> str:
    """Tag-strip, whitespace-collapse and truncate so an HTML 5xx page can't
    flood the log."""
    return " ".join(_HTML_TAG_RE.sub(" ", text).split())[:limit]


def summarize_exc(exc: BaseException) -> str:
    """One-line ``Type status=… request_id=… detail=…`` summary of an exception.

    Captures the locators an Anthropic support ticket needs and strips any HTML
    error-page body, so the diagnostics file records the cause of a transient
    failure precisely rather than dumping a wall of markup.
    """
    parts = [type(exc).__name__]
    status = status_of(exc)
    if status is not None:
        parts.append(f"status={status}")
    rid = request_id_of(exc)
    if rid:
        parts.append(f"request_id={rid}")
    msg = getattr(exc, "message", None)
    if not (isinstance(msg, str) and msg.strip()):
        msg = str(exc)
    msg = _short(msg)
    if msg:
        parts.append(f"detail={msg}")
    return " ".join(parts)
