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

What a key is (WP-16.1, G3)
---------------------------
A key file saved "UTF-8 with BOM" used to be loaded with the BOM, migrated
into the keyring (the round-trip cannot tell), and every legacy file deleted:
every call then failed authentication, and the keyring served the broken
value on every launch. Every value that enters here now goes through the one
normalizer and the one shape check in :mod:`.api_key_format` (the owner's
rules):

- **Normalized:** whitespace and Unicode format characters (the BOM, a
  zero-width space, a word joiner) are stripped from both ends, in a key file,
  a keyring entry, and a value passed to :func:`save_api_key`. A UTF-16 file
  (it starts with a UTF-16 BOM) is decoded; any other file is read as UTF-8.
- **Checked:** the normalized value must be ``sk-ant-`` followed by key
  characters, the redactor's own pattern, with no length floor. A key file
  that fails is not used, not migrated and left in place; a keyring entry that
  fails is not served (the key files are tried next) and not deleted;
  :func:`save_api_key` refuses it.
- **Repaired:** a keyring entry that normalizes to a different value is
  rewritten through the verified round-trip; if that fails, the entry is left
  and the normalized key is used for this session.
- **Migrated safely:** a migration deletes only the key files that hold the
  key it just verified in the keyring. A file holding anything else is kept.
  :func:`save_api_key` still removes every key file: the user explicitly
  replaced the key.

Whatever the store refused, repaired, kept or skipped is reported as a
:class:`KeyNote` by :func:`load_api_key_with_notes` and written to the
diagnostics log. A note names the file (or the keyring) and the reason, never
the value, and so does every exception message raised here.

File permissions
----------------
On POSIX, :func:`load_api_key_from_file` lazily tightens the permissions of
any fallback file it can read to ``0600`` (owner read+write only) so an
in-place upgrade improves the existing key file's posture without
requiring the user to re-enter the key.
"""
from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .api_key_format import looks_like_api_key, normalize_api_key
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

# The diagnostics logger, by name. ``core`` imports nothing from the package top
# level, and ``diagnostics`` attaches its file handler to exactly this logger
# with ``propagate=False``, so a ``getLogger(__name__)`` here would never reach
# the file.
_diag = logging.getLogger("drawing_analyzer.diagnostics")

#: A key file larger than this is not read (bounded work, plan §2 rule 14). A
#: key is about a hundred bytes; the cap only stops a wrong file being read
#: whole at every launch.
_MAX_KEY_FILE_BYTES = 64 * 1024

_KEY_SHAPE_HINT = "expected a single key that starts with 'sk-ant-'"


@dataclass(frozen=True)
class KeyNote:
    """One thing the store has to tell the user about the key it loaded.

    ``text`` names the file (or the OS keyring) and the reason, and never
    carries the value. ``warning`` is False only for a repair that worked.
    """

    text: str
    warning: bool = True


@dataclass(frozen=True)
class KeyLoadResult:
    """The key :func:`load_api_key_with_notes` resolved (``""`` for none)."""

    key: str
    notes: tuple[KeyNote, ...] = ()


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


def _migrate_legacy_file_key(
    key: str,
    notes: list[KeyNote] | None = None,
    named: frozenset[Path] | set[Path] = frozenset(),
) -> bool:
    """Move a key found in a plaintext file into the OS keyring.

    Returns ``True`` when the keyring verifiably holds the key and the legacy
    files that hold that key were (best-effort) removed; a file holding
    anything else is kept and named in ``notes`` (WP-16.1: it used to remove
    every location, the only copy of a different key included). ``False``
    leaves every file untouched so the legacy workflow keeps working where no
    secure backend exists.
    """
    if not _keyring_store_verified(key):
        return False
    _remove_key_files_holding(key, notes if notes is not None else [], named)
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


def _key_file_present(path: Path) -> bool:
    """Does ``path`` exist? ``True`` when that cannot even be told.

    ``Path.exists()`` re-raises a permission error. A file whose presence cannot
    be told is treated as present, so reading it names the failure instead of
    the error ending the load (or the cleanup after a migration that worked).
    """
    try:
        return path.exists()
    except OSError:
        return True


def _read_key_file(path: Path, notes: list[KeyNote]) -> str | None:
    """The text of one key file, or ``None`` (with a note) when it has none.

    A file that starts with a UTF-16 BOM (Notepad's "UTF-16 LE") is decoded as
    UTF-16; any other file as UTF-8, whose BOM the normalizer then strips.
    """
    try:
        with path.open("rb") as fh:
            data = fh.read(_MAX_KEY_FILE_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 - skipped as before, now named
        notes.append(KeyNote(
            f"Key file not used: {path} could not be read "
            f"({type(exc).__name__}). It was left in place."
        ))
        return None
    if len(data) > _MAX_KEY_FILE_BYTES:
        notes.append(KeyNote(
            f"Key file not used: {path} is larger than "
            f"{_MAX_KEY_FILE_BYTES // 1024} KiB, too large to be a key file. "
            "It was left in place."
        ))
        return None
    codec = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
    try:
        return data.decode(codec)
    except UnicodeDecodeError:
        notes.append(KeyNote(
            f"Key file not used: {path} is not UTF-8 or UTF-16 text. "
            "It was left in place."
        ))
        return None


def _remove_key_files_holding(
    key: str, notes: list[KeyNote], named: set[Path]
) -> None:
    """Delete the key files that hold ``key``; keep, and name, any other.

    Called only after ``key`` has verifiably landed in the keyring. A file
    holding anything else may be the only copy of another key, so a migration
    never deletes it (G3). A file already named in this load's notes is not
    named twice. Deletion stays best-effort, as in :func:`_remove_key_files`.
    """
    for path in api_key_paths():
        if not _key_file_present(path):
            continue
        problems: list[KeyNote] = []
        text = _read_key_file(path, problems)
        if text is not None and normalize_api_key(text) == key:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if path in named:
            continue
        # Unreadable: its own reason ("could not be read ... left in place").
        notes.extend(problems or [KeyNote(
            "Another key file was left in place because it does not hold the "
            f"key now saved in the OS keyring: {path}. Delete it if you no "
            "longer need it."
        )])


def _key_from_keyring(notes: list[KeyNote]) -> str:
    """The keyring's key, normalized (and repaired), or ``""`` for none."""
    stored = _keyring_get()
    if not stored:
        return ""
    key = normalize_api_key(stored)
    if not looks_like_api_key(key):
        notes.append(KeyNote(
            "The API key saved in the OS keyring does not look like an "
            f"Anthropic API key ({_KEY_SHAPE_HINT}), so it was not used."
        ))
        return ""
    if key != stored:
        if _keyring_store_verified(key):
            notes.append(KeyNote(
                "The API key saved in the OS keyring had invisible characters "
                "at its start or end (such as a byte-order mark). They were "
                "removed and the key was saved again.",
                warning=False,
            ))
        else:
            notes.append(KeyNote(
                "The API key saved in the OS keyring has invisible characters "
                "at its start or end (such as a byte-order mark) and could not "
                "be saved again. The cleaned key is used for this session."
            ))
    return key


def _key_from_files(notes: list[KeyNote]) -> str:
    """The first key file that holds a key, migrated when a keyring works."""
    named: set[Path] = set()
    for path in api_key_paths():
        if not _key_file_present(path):
            continue
        text = _read_key_file(path, notes)
        if text is None:
            named.add(path)
            continue
        key = normalize_api_key(text)
        if not key:
            notes.append(KeyNote(
                f"Key file ignored: {path} is empty (or holds only spaces or "
                "invisible characters)."
            ))
            named.add(path)
            continue
        if not looks_like_api_key(key):
            notes.append(KeyNote(
                f"Key file not used: {path} does not hold an Anthropic API key "
                f"({_KEY_SHAPE_HINT}). It was left in place."
            ))
            named.add(path)
            continue
        if _migrate_legacy_file_key(key, notes, named):
            return key
        _restrict_permissions(path)
        return key
    return ""


def load_api_key_with_notes() -> KeyLoadResult:
    """Resolve the API key, and say what was refused, repaired or kept.

    The keyring is preferred; the key files are searched when it holds no
    usable key. A file key found while a secure backend is working is migrated
    into the keyring (verified read-back), and the files that hold that key are
    removed (DA-032's legacy-file migration). Where no secure backend exists,
    the file the key came from is chmod-tightened in place so a stale 0644 key
    file from before that hardening lands at 0600 after first load.

    Every note is also written to the diagnostics log. See the module
    docstring for the rules (WP-16.1).
    """
    notes: list[KeyNote] = []
    key = _key_from_keyring(notes) or _key_from_files(notes)
    for note in notes:
        _diag.log(logging.WARNING if note.warning else logging.INFO, note.text)
    return KeyLoadResult(key, tuple(notes))


def load_api_key_from_file() -> str:
    """Resolve the Anthropic API key from keyring or the fallback file.

    :func:`load_api_key_with_notes` without the notes (they still reach the
    diagnostics log). Returns ``""`` when no usable key was found.
    """
    return load_api_key_with_notes().key


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
    user-facing path). Raises :class:`ValueError` for a key that is empty, or
    that does not look like an Anthropic API key, once normalized (WP-16.1;
    the message never carries the value), and propagates the underlying
    :class:`OSError` if the file write fails so a failure to persist is never
    silent.
    """
    key = normalize_api_key(key)
    if not key:
        raise ValueError("Refusing to save an empty API key.")
    if not looks_like_api_key(key):
        raise ValueError(
            "Refusing to save a value that does not look like an Anthropic API "
            f"key ({_KEY_SHAPE_HINT})."
        )
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
