"""Loading and storing the Anthropic API key.

The key is searched for in the OS keyring first, then the platform config
directory, then the executable/source-parent fallback file. Returns an empty
string for any missing/unreadable source so the caller can decide how to
surface that to the user. :func:`save_api_key` is the write-side counterpart
used by the GUI key field.

Credential-safe persistence (Phase 17, DA-032)
----------------------------------------------
Persistent storage must go through an OS-secured credential store — Windows
Credential Manager, macOS Keychain, or Secret Service/kwallet — via the
optional ``keyring`` package. A backend is trusted only after a **verified
round-trip** (``set_password`` followed by a matching ``get_password``), so a
broken or volatile backend can never swallow the key while reporting success.

When no secure backend is available, :func:`save_api_key` **refuses** to write
the plaintext fallback file unless the caller passes
``allow_plaintext_fallback=True``. The GUI translates that refusal
(:class:`SecureKeyStorageUnavailable`) into an explicit informed-consent
prompt; declining keeps the key session-only. Silent plaintext persistence is
gone — it was the DA-032 defect.

Legacy plaintext key files are migrated: whenever a file key is loaded (or a
new key is saved) and a secure backend verifiably stores it, the key moves
into the keyring and the plaintext file(s) are deleted. The key value itself
is never logged, and migration never copies it anywhere except the keyring.

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

# Keyring is optional. On headless CI / minimal Linux installs the import or
# the first ``get_password`` call can fail. We swallow every failure so the
# caller can fall back (with consent) rather than crash.
try:  # pragma: no cover - import path depends on optional dependency
    import keyring as _keyring  # type: ignore

    _KEYRING_AVAILABLE = True
except Exception:  # pragma: no cover - keyring not installed
    _keyring = None
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "DrawingAnalyzer"
_KEYRING_USERNAME = "anthropic_api_key"


class SecureKeyStorageUnavailable(RuntimeError):
    """No OS-secured credential store accepted the key.

    Raised by :func:`save_api_key` instead of silently writing a plaintext
    file. Callers that want the plaintext fallback must obtain the user's
    informed consent and retry with ``allow_plaintext_fallback=True``, or
    keep the key session-only.
    """


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
    swallowed and reported as ``False`` so the caller can decide what to do
    rather than crash.
    """
    if not _KEYRING_AVAILABLE or _keyring is None:
        return False
    try:
        _keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key)
    except Exception:
        return False
    return True


def _keyring_store_verified(key: str) -> bool:
    """Store ``key`` and prove it by reading it back.

    Only a verified round-trip counts as secure persistence: some keyring
    backends accept ``set_password`` and then lose the value (volatile or
    misconfigured backends), which would strand the user with no saved key
    while the app reports success.
    """
    if not _keyring_set(key):
        return False
    return _keyring_get() == key


def secure_backend_available() -> bool:
    """Advisory probe: does a non-fail keyring backend appear to exist?

    Ground truth for persistence is always the verified round-trip in
    :func:`_keyring_store_verified`; this probe exists so UIs can warn ahead
    of time. It deliberately errs on the side of ``False``.
    """
    if not _KEYRING_AVAILABLE or _keyring is None:
        return False
    try:
        backend = _keyring.get_keyring()
        qualname = f"{type(backend).__module__}.{type(backend).__qualname__}"
        priority = getattr(backend, "priority", 1)
    except Exception:
        return False
    if ".fail." in qualname:
        return False
    try:
        if float(priority) <= 0:
            return False
    except Exception:
        return False
    return True


def _remove_key_files() -> None:
    """Best-effort deletion of every plaintext key file location.

    Called only after the key has verifiably landed in the OS keyring, so a
    failure here (locked file, read-only medium) leaves a redundant copy but
    never loses the key. Errors are swallowed and the key value is never
    logged.
    """
    for path in api_key_paths():
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _migrate_legacy_file_key(key: str) -> bool:
    """Move a key found in a plaintext file into the OS keyring.

    Returns ``True`` when the keyring verifiably holds the key and the
    legacy file(s) were (best-effort) removed; ``False`` leaves the file
    untouched so the legacy workflow keeps working where no secure backend
    exists.
    """
    if not _keyring_store_verified(key):
        return False
    _remove_key_files()
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


def _write_key_file(path: Path, key: str) -> None:
    """Write ``key`` to ``path`` without ever exposing it group/other-readable.

    On POSIX the file is opened with ``O_CREAT`` mode ``0o600`` and is
    ``fchmod``'d to owner-only *before* the secret is written. This closes the
    brief window a plain ``write_text`` + post-hoc ``chmod`` leaves under a
    typical ``022`` umask, where a freshly-created file — or a pre-existing
    ``0644`` one — is readable by other users while it already holds the key.
    On Windows, where ``os.chmod`` only toggles the read-only bit and access is
    governed by ACLs rather than mode bits, we fall back to a plain text write
    (reachable only through the explicit plaintext-consent path).
    """
    if os.name != "posix":
        path.write_text(key, encoding="utf-8")
        return
    # A new file is created at 0o600 (umask only clears bits, and 0o600 has no
    # group/other bits to clear). O_CREAT's mode is ignored for an *existing*
    # file, so fchmod before writing also tightens a legacy 0o644 key file
    # before the secret bytes land rather than after.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        os.close(fd)
        raise
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key)


def load_api_key_from_file() -> str:
    """Resolve the Anthropic API key from keyring or the fallback file.

    Keyring is preferred when available; the file is searched only when the
    keyring returns nothing. A file key found while a secure backend is
    working is migrated into the keyring (verified read-back) and the
    plaintext file is removed — DA-032's legacy-file migration. Where no
    secure backend exists, any fallback file we successfully read is
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
            if _migrate_legacy_file_key(value):
                return value
            _restrict_permissions(path)
            return value
    return ""


def save_api_key(key: str, *, allow_plaintext_fallback: bool = False) -> Path | None:
    """Persist the Anthropic API key for future sessions.

    Storage prefers the OS keyring (the same backend
    :func:`load_api_key_from_file` consults first) and trusts it only after a
    verified read-back; on success any legacy plaintext key file is removed.

    When no secure backend works, the plaintext fallback file is written
    **only** with ``allow_plaintext_fallback=True`` — the caller's assertion
    that the user gave informed consent. Without it,
    :class:`SecureKeyStorageUnavailable` is raised so the key can stay
    session-only instead of silently landing on disk in clear text (DA-032).
    The consented file is created owner-only (``0600``) from the start on
    POSIX (see :func:`_write_key_file`).

    Returns the file :class:`~pathlib.Path` when the key was written to a
    file, or ``None`` when it was stored in the keyring (which has no
    user-facing path). Raises :class:`ValueError` for an empty key and
    propagates the underlying :class:`OSError` if the file write fails so a
    failure to persist is never silent.
    """
    key = (key or "").strip()
    if not key:
        raise ValueError("Refusing to save an empty API key.")
    if _keyring_store_verified(key):
        _remove_key_files()
        return None
    if not allow_plaintext_fallback:
        raise SecureKeyStorageUnavailable(
            "No OS-secured credential store (Windows Credential Manager / "
            "keychain / Secret Service) is available to hold the API key. "
            "Keep the key session-only, or retry with "
            "allow_plaintext_fallback=True after obtaining explicit consent "
            "to store it as a plaintext file."
        )
    # Explicitly-consented fallback — the plaintext file in the canonical
    # (writable) config dir, which is api_key_paths()[0]. The file is created
    # owner-only from the start (see _write_key_file) so the key is never
    # momentarily exposed to other users on a shared machine.
    path = api_key_paths()[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_key_file(path, key)
    return path
