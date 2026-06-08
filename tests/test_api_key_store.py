"""Tests for the Anthropic API key store (save/load round-trip).

Hermetic: the OS keyring is forced off (or stubbed) and the plaintext file
fallback is redirected into a tmp dir via the ``api_key_paths`` seam, so
nothing here touches the real keychain or the user's config directory.
"""
from __future__ import annotations

import os
import stat

import pytest

from drawing_analyzer.core import api_key_store


@pytest.fixture
def key_file(tmp_path, monkeypatch):
    """Redirect the key file into ``tmp_path`` and force the keyring off.

    Returns the path the store will read/write so tests can assert on it.
    Forcing ``_keyring_set``/``_keyring_get`` keeps the file-fallback tests
    deterministic even on a machine where the ``keyring`` package is present.
    """
    path = tmp_path / "drawing_analyzer_api_key.txt"
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [path])
    monkeypatch.setattr(api_key_store, "_keyring_set", lambda key: False)
    monkeypatch.setattr(api_key_store, "_keyring_get", lambda: "")
    return path


def test_save_then_load_round_trips_through_file(key_file):
    returned = api_key_store.save_api_key("sk-ant-test-123")
    assert returned == key_file
    assert key_file.read_text(encoding="utf-8") == "sk-ant-test-123"
    assert api_key_store.load_api_key_from_file() == "sk-ant-test-123"


def test_save_strips_surrounding_whitespace(key_file):
    api_key_store.save_api_key("  sk-ant-padded  \n")
    assert key_file.read_text(encoding="utf-8") == "sk-ant-padded"
    assert api_key_store.load_api_key_from_file() == "sk-ant-padded"


def test_save_empty_key_raises_and_writes_nothing(key_file):
    with pytest.raises(ValueError):
        api_key_store.save_api_key("   ")
    assert not key_file.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-mode semantics only")
def test_saved_file_is_owner_only(key_file):
    api_key_store.save_api_key("sk-ant-secret")
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

    api_key_store.save_api_key("sk-ant-new")

    assert key_file.read_text(encoding="utf-8") == "sk-ant-new"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_keyring_success_skips_file(tmp_path, monkeypatch):
    """When the keyring accepts the key, no plaintext file is written."""
    path = tmp_path / "drawing_analyzer_api_key.txt"
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [path])
    captured: list[str] = []

    def fake_set(key: str) -> bool:
        captured.append(key)
        return True

    monkeypatch.setattr(api_key_store, "_keyring_set", fake_set)

    returned = api_key_store.save_api_key("sk-ant-keyring")

    assert returned is None
    assert captured == ["sk-ant-keyring"]
    assert not path.exists()


def test_load_prefers_keyring_over_file(key_file, monkeypatch):
    """A keyring value wins over a present fallback file (loader priority)."""
    key_file.write_text("sk-ant-from-file", encoding="utf-8")
    monkeypatch.setattr(
        api_key_store, "_keyring_get", lambda: "sk-ant-from-keyring"
    )
    assert api_key_store.load_api_key_from_file() == "sk-ant-from-keyring"
