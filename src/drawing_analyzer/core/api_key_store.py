"""Loading and storing the Anthropic API key.

The key is searched for in the platform config directory first, then in the
executable/source-parent fallback. Returns an empty string for any
missing/unreadable file so the caller can decide how to surface that to
the user. :func:`save_api_key` is the write-side counterpart used by the GUI
key field — it persists with the same keyring-then-file priority the loader
reads back.

OS keyring (optional)
---------------------
When the ``keyring`` package is installed and a working backend is available,
the keyring is consulted *first* — keychain / credential-manager / kwallet
secrets are at least as safe as a plaintext file and survive a stray
``cat`` / scp of the config directory. The plaintext file remains a
fallback so the legacy "drop a key file next to the exe" workflow keeps
working unchanged and existing users are never locked out of their saved
key when they upgrade.

File permissions
----------------
On POSIX, :func:`load_api_key_from_file` lazily tightens the permissions of
any fallback file it can read to ``0600`` (owner read+write only) so an
in-place upgrade improves the existing key file's posture without
requiring the user to re-enter the key.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from .app_paths import api_key_paths

# Keyring is optional. The package isn't pinned in requirements.txt, and on
# headless CI / minimal Linux installs the import or the first ``get_password``
# call can fail. We swallow every failure so the file fallback always works.
try:  # pragma: no cover - import path depends on optional dependency
    import keyring as _keyring  # type: ignore

    _KEYRING_AVAILABLE = True
except Exception:  # pragma: no cover - keyring not installed
    _keyring = None
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "DrawingAnalyzer"
_KEYRING_USERNAME = "anthropic_api_key"


def _keyring_get() -> str:
    if not _KEYRING_AVAILABLE or _keyring is None:
        return ""
    try:
        value = _keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        return ""
    return (value or "").strip()


def _keyring_set(key: str) -> bool:
    """Best-effort store of ``key`` in the OS keyring. Returns success.

    Mirrors :func:`_keyring_get`'s defensiveness: a missing package or any
    backend failure (locked keychain, no backend on headless Linux) is
    swallowed and reported as ``False`` so the caller can fall back to the
    plaintext file rather than crash.
    """
    if not _KEYRING_AVAILABLE or _keyring is None:
        return False
    try:
        _keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key)
    except Exception:
        return False
    return True


def _restrict_permissions(path: Path) -> None:
    """Best-effort tighten of file permissions to owner-only (0600).

    POSIX-only; on Windows ``os.chmod`` only toggles the read-only bit so
    we skip it there. Failures are swallowed because the key is still
    readable — we'd rather load the key on a quirky filesystem than fail
    the whole run over a permission tweak.
    """
    if os.name != "posix":
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def load_api_key_from_file() -> str:
    """Resolve the Anthropic API key from keyring or the fallback file.

    Keyring is preferred when available; the file is searched only when the
    keyring returns nothing. Any fallback file we successfully read is
    chmod-tightened in-place so a stale 0644 key file from before this
    hardening lands at 0600 after first load.
    """
    from_keyring = _keyring_get()
    if from_keyring:
        return from_keyring
    for path in api_key_paths():
        if not path.exists():
            continue
        try:
            value = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if value:
            _restrict_permissions(path)
            return value
    return ""


def save_api_key(key: str) -> Path | None:
    """Persist the Anthropic API key for future sessions.

    Storage prefers the OS keyring (the same backend
    :func:`load_api_key_from_file` consults first); when keyring is
    unavailable or fails, the key is written to the plaintext file in the
    platform config dir and chmod-tightened to ``0600`` on POSIX.

    Returns the file :class:`~pathlib.Path` when the key was written to a
    file, or ``None`` when it was stored in the keyring (which has no
    user-facing path). Raises :class:`ValueError` for an empty key and
    propagates the underlying :class:`OSError` if the file write fails so a
    failure to persist is never silent.
    """
    key = (key or "").strip()
    if not key:
        raise ValueError("Refusing to save an empty API key.")
    if _keyring_set(key):
        return None
    # Keyring unavailable / failed — fall back to the plaintext file in the
    # canonical (writable) config dir, which is api_key_paths()[0].
    path = api_key_paths()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    _restrict_permissions(path)
    return path

