"""Tests for the Anthropic API key store (save/load round-trip).

Hermetic: the OS keyring is stubbed (either off, or an in-memory fake) and the
plaintext file fallback is redirected into a tmp dir via the ``api_key_paths``
seam, so nothing here touches the real keychain or the user's config directory.

Phase 17 / DA-032: persistence is credential-safe. A secure backend is trusted
only after a verified round-trip; with no secure backend the plaintext file is
written **only** with explicit ``allow_plaintext_fallback=True`` (else
:class:`SecureKeyStorageUnavailable` is raised), and legacy plaintext key files
are migrated into the keyring on load/save.
"""
from __future__ import annotations

import os
import stat

import pytest

from drawing_analyzer.core import api_key_store
from drawing_analyzer.core.api_key_store import SecureKeyStorageUnavailable


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    """Redirect the key file into ``tmp_path`` and force the keyring OFF.

    Returns the path the store will read/write so tests can assert on it.
    Forcing ``_keyring_set``/``_keyring_get`` keeps the file-fallback tests
    deterministic even on a machine where the ``keyring`` package is present.
    With the keyring off, secure persistence always fails, so this is the
    "no secure backend available" world.
    """
    path = tmp_path / "drawing_analyzer_api_key.txt"
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [path])
    monkeypatch.setattr(api_key_store, "_keyring_set", lambda key: False)
    monkeypatch.setattr(api_key_store, "_keyring_get", lambda: "")
    return path


@pytest.fixture
def working_keyring(tmp_path, monkeypatch):
    """Redirect the key file AND install an in-memory secure keyring.

    The fake keyring round-trips (set then get returns the same value), so
    :func:`_keyring_store_verified` succeeds — the "secure backend available"
    world. Returns ``(path, store)`` where ``store`` is the backing dict.
    """
    path = tmp_path / "drawing_analyzer_api_key.txt"
    store: dict[str, str] = {}
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [path])
    monkeypatch.setattr(
        api_key_store, "_keyring_set",
        lambda key: (store.__setitem__("k", key) or True),
    )
    monkeypatch.setattr(api_key_store, "_keyring_get", lambda: store.get("k", ""))
    return path, store


# --------------------------------------------------------------------------- #
# Secure backend available — keyring is the store, no plaintext file (DA-032)
# --------------------------------------------------------------------------- #


def test_secure_backend_saves_to_keyring_not_file(working_keyring):
    path, store = working_keyring
    returned = api_key_store.save_api_key("sk-ant-secure")
    assert returned is None                      # keyring path → no file path
    assert store["k"] == "sk-ant-secure"
    assert not path.exists()
    assert api_key_store.load_api_key_from_file() == "sk-ant-secure"


def test_save_strips_surrounding_whitespace(working_keyring):
    _path, store = working_keyring
    api_key_store.save_api_key("  sk-ant-padded  \n")
    assert store["k"] == "sk-ant-padded"


def test_broken_backend_that_forgets_is_not_trusted(tmp_path, monkeypatch):
    """A backend that accepts set() but loses the value must NOT be trusted.

    Only a verified read-back counts as secure persistence — otherwise the
    user is stranded with no saved key while the app claims success. Here
    set() succeeds but get() returns nothing, so the save must fall through to
    the (refused-by-default) plaintext path.
    """
    path = tmp_path / "k.txt"
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [path])
    monkeypatch.setattr(api_key_store, "_keyring_set", lambda key: True)
    monkeypatch.setattr(api_key_store, "_keyring_get", lambda: "")   # forgets
    with pytest.raises(SecureKeyStorageUnavailable):
        api_key_store.save_api_key("sk-ant-x")


# --------------------------------------------------------------------------- #
# No secure backend — refuse plaintext unless the caller consents (DA-032)
# --------------------------------------------------------------------------- #


def test_no_secure_backend_refuses_plaintext_by_default(key_file):
    with pytest.raises(SecureKeyStorageUnavailable):
        api_key_store.save_api_key("sk-ant-test-123")
    assert not key_file.exists()                 # nothing written on refusal


def test_consented_plaintext_fallback_writes_file(key_file):
    returned = api_key_store.save_api_key(
        "sk-ant-test-123", allow_plaintext_fallback=True
    )
    assert returned == key_file
    assert key_file.read_text(encoding="utf-8") == "sk-ant-test-123"
    assert api_key_store.load_api_key_from_file() == "sk-ant-test-123"


def test_save_empty_key_raises_and_writes_nothing(key_file):
    with pytest.raises(ValueError):
        api_key_store.save_api_key("   ", allow_plaintext_fallback=True)
    assert not key_file.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-mode semantics only")
def test_consented_file_is_owner_only(key_file):
    api_key_store.save_api_key("sk-ant-secret", allow_plaintext_fallback=True)
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-mode semantics only")
def test_save_tightens_preexisting_loose_file(key_file):
    """A legacy world/group-readable key file lands at 0600 after a re-save.

    Exercises the existing-file branch where ``O_CREAT``'s mode is ignored, so
    the explicit ``fchmod`` before the write is what closes the exposure window.
    """
    key_file.write_text("old-key", encoding="utf-8")
    key_file.chmod(0o644)

    api_key_store.save_api_key("sk-ant-new", allow_plaintext_fallback=True)

    assert key_file.read_text(encoding="utf-8") == "sk-ant-new"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


# --------------------------------------------------------------------------- #
# Legacy plaintext migration into the keyring (DA-032)
# --------------------------------------------------------------------------- #


def test_load_migrates_legacy_file_into_keyring(working_keyring):
    """A plaintext key loaded while a secure backend works moves to the keyring.

    The legacy file is deleted (best-effort) and the key never leaves for
    anywhere but the keyring — the migration path the plan requires.
    """
    path, store = working_keyring
    path.write_text("sk-ant-legacy", encoding="utf-8")

    value = api_key_store.load_api_key_from_file()

    assert value == "sk-ant-legacy"
    assert store["k"] == "sk-ant-legacy"         # now in the keyring
    assert not path.exists()                     # legacy file removed


def test_save_with_working_keyring_removes_stale_plaintext_file(working_keyring):
    """Saving to the keyring also cleans up a pre-existing plaintext file."""
    path, store = working_keyring
    path.write_text("sk-ant-old-plain", encoding="utf-8")

    api_key_store.save_api_key("sk-ant-fresh")

    assert store["k"] == "sk-ant-fresh"
    assert not path.exists()


def test_no_backend_keeps_legacy_file_readable(key_file):
    """With no secure backend, a legacy file still loads (and isn't destroyed)."""
    key_file.write_text("sk-ant-from-file", encoding="utf-8")
    assert api_key_store.load_api_key_from_file() == "sk-ant-from-file"
    assert key_file.exists()


def test_load_prefers_keyring_over_file(key_file, monkeypatch):
    """A keyring value wins over a present fallback file (loader priority)."""
    key_file.write_text("sk-ant-from-file", encoding="utf-8")
    monkeypatch.setattr(
        api_key_store, "_keyring_get", lambda: "sk-ant-from-keyring"
    )
    assert api_key_store.load_api_key_from_file() == "sk-ant-from-keyring"
