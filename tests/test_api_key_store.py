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


# =========================================================================== #
# WP-16.1 (G3): a key file saved "UTF-8 with BOM" was loaded with the BOM,
# migrated into the keyring (which passed the verified round-trip) and every
# legacy file deleted, so every call failed authentication from then on and the
# keyring served the broken value on every launch. The owner's rules:
#
# - one normalizer (`normalize_api_key`): whitespace and Unicode format
#   characters (category Cf: the BOM, a zero-width space, a word joiner) are
#   stripped from both ends; it serves the file load, save, the value served
#   from the keyring and the GUI field;
# - one shape check (`looks_like_api_key`): the whole value matches the
#   redactor's own `sk-ant-[A-Za-z0-9_-]+`, no length floor, applied to
#   migration, save and the keyring;
# - a file that fails it is not migrated, not used and kept, and named;
# - a keyring entry stored un-normalized is rewritten through the verified
#   round-trip; one that fails the check is not served;
# - a migration deletes only the files that hold the key it just verified;
# - a UTF-16 file is decoded; any other unreadable file is named;
# - every note names the file and the reason, never the value.
#
# These tests reach the real `_keyring_get` / `_keyring_set` through a fake
# `keyring` module, so the store's own read (which strips, like the real one)
# is what runs. Fake keys are built at runtime: a literal `sk-ant-` followed by
# 30 key characters is what scripts/scan_secrets.py (run by CI) refuses.
# =========================================================================== #

import logging
import types

BOM = "\ufeff"
KEY = "sk-ant-api03-" + "A" * 86 + "AA"
OTHER = "sk-ant-api03-" + "B" * 86 + "BB"
# What a leak of either key would contain, whatever surrounds it.
_KEY_FRAGMENTS = ("A" * 20, "B" * 20)


class _FakeKeyringModule:
    """A dict-backed stand-in for the ``keyring`` package.

    ``on_read`` transforms a stored value on its way out (a backend that
    changes what it hands back); ``fail_set`` makes every write raise (a locked
    or read-only store).
    """

    def __init__(self, *, on_read=None, fail_set=False):
        self.data: dict = {}
        self.on_read = on_read
        self.fail_set = fail_set
        self.sets = 0

    def get_password(self, service, username):
        value = self.data.get((service, username))
        if value is not None and self.on_read is not None:
            return self.on_read(value)
        return value

    def set_password(self, service, username, value):
        self.sets += 1
        if self.fail_set:
            raise RuntimeError("the credential store is locked")
        self.data[(service, username)] = value

    @property
    def held(self):
        return self.data.get(
            (api_key_store._KEYRING_SERVICE, api_key_store._KEYRING_USERNAME)
        )

    def put(self, value):
        self.data[
            (api_key_store._KEYRING_SERVICE, api_key_store._KEYRING_USERNAME)
        ] = value


@pytest.fixture
def locations(tmp_path, monkeypatch):
    """Both key locations, in the store's priority order: config dir, exe dir.

    The single-path fixtures above cannot show what a migration does to the
    *other* location (p5), so this redirects both.
    """
    config = tmp_path / "config" / "drawing_analyzer_api_key.txt"
    exe = tmp_path / "exe" / "drawing_analyzer_api_key.txt"
    config.parent.mkdir()
    exe.parent.mkdir()
    monkeypatch.setattr(api_key_store, "api_key_paths", lambda: [config, exe])
    return types.SimpleNamespace(config=config, exe=exe)


@pytest.fixture
def backend(monkeypatch):
    """Install a keyring backend; ``backend()`` or ``backend(None)`` for none."""

    def install(fake=...):
        if fake is ...:
            fake = _FakeKeyringModule()
        monkeypatch.setattr(api_key_store, "_KEYRING_AVAILABLE", fake is not None)
        monkeypatch.setattr(api_key_store, "_keyring", fake)
        return fake

    return install


def _notes():
    return api_key_store.load_api_key_with_notes()


# --------------------------------------------------------------------------- #
# The normalizer and the shape check
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        BOM + KEY,
        BOM + BOM + KEY,                       # utf-8-sig would leave the second
        KEY + BOM,
        "  " + BOM + " " + KEY + "\r\n",
        "\u200b" + KEY + "\u2060",             # zero-width space, word joiner
        "\u00a0" + KEY + "\u00a0",             # NBSP is whitespace to str.strip
        "\u200e" + KEY + "\u00ad",             # LRM, soft hyphen (both Cf)
        KEY,
    ],
    ids=["bom", "two-boms", "trailing-bom", "spaces-bom-crlf", "zwsp-wj", "nbsp",
         "lrm-shy", "clean"],
)
def test_normalize_strips_whitespace_and_format_characters_at_both_ends(raw):
    assert api_key_store.normalize_api_key(raw) == KEY


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        (BOM, ""),
        (" \t\n" + BOM + "\u200b", ""),
        # Only the ends: a format character inside the value stays, so the
        # shape check refuses it rather than the normalizer quietly editing it.
        (KEY[:20] + "\u200b" + KEY[20:], KEY[:20] + "\u200b" + KEY[20:]),
        (KEY + "\n# my work key", KEY + "\n# my work key"),
    ],
    ids=["none", "empty", "bom-only", "invisible-only", "zwsp-inside", "comment-line"],
)
def test_normalize_touches_only_the_ends(raw, expected):
    assert api_key_store.normalize_api_key(raw) == expected


def test_normalize_is_idempotent():
    for raw in (BOM + KEY + " ", "\u200b x \u2060", "", KEY):
        once = api_key_store.normalize_api_key(raw)
        assert api_key_store.normalize_api_key(once) == once


@pytest.mark.parametrize(
    "value",
    # Every fake key the pinned tests above use, and no length floor.
    [KEY, "sk-ant-x", "sk-ant-secure", "sk-ant-test-123", "sk-ant-api03-a_b-C9"],
    ids=["full-length", "x", "secure", "test-123", "mixed"],
)
def test_the_shape_check_accepts_sk_ant_keys_of_any_length(value):
    assert api_key_store.looks_like_api_key(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "sk-ant-",                             # a prefix alone is not a key
        "hello world",
        KEY + "\n# my work key",
        BOM + KEY,                             # the check runs AFTER normalizing
        KEY[:20] + "\u200b" + KEY[20:],
        "test-key-not-real-do-not-use",        # the hermetic guard's placeholder
        "Bearer " + KEY,
        KEY + " ",
    ],
    ids=["empty", "prefix-only", "hello-world", "comment-line", "bom",
         "zwsp-inside", "placeholder", "bearer", "trailing-space"],
)
def test_the_shape_check_refuses_anything_else(value):
    assert not api_key_store.looks_like_api_key(value)


def test_the_shape_check_is_the_redactors_pattern():
    """One pattern: what the store accepts is exactly what diagnostics redacts."""
    from drawing_analyzer import diagnostics
    from drawing_analyzer.core import api_key_format

    assert api_key_store.looks_like_api_key is api_key_format.looks_like_api_key
    assert any(
        pattern is api_key_format.ANTHROPIC_KEY_RE
        for pattern, _ in diagnostics._SECRET_PATTERNS
    )
    assert "sk-ant-" + "[REDACTED]" in diagnostics.redact_secrets(f"key={KEY}")
    assert KEY not in diagnostics.redact_secrets(KEY)


# --------------------------------------------------------------------------- #
# Loading a legacy key file (p1, p2, p5-p9, p11, p13)
# --------------------------------------------------------------------------- #


def test_p1_a_bom_file_migrates_the_clean_key_and_the_next_launch_serves_it(
    locations, backend
):
    fake = backend()
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())

    assert api_key_store.load_api_key_from_file() == KEY
    assert fake.held == KEY
    assert not locations.config.exists()
    assert api_key_store.load_api_key_from_file() == KEY      # the next launch


def test_p2_a_bom_file_with_no_keyring_is_served_clean_and_kept(locations, backend):
    backend(None)
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())

    assert api_key_store.load_api_key_from_file() == KEY
    assert locations.config.exists()


def test_p3_the_wire_never_carries_the_bom(locations, backend):
    """G3's symptom, end to end through the real SDK over an in-process transport."""
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    backend()
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())
    sent: list[bytes] = []

    def handler(request):
        headers = {name.lower(): value for name, value in request.headers.raw}
        sent.append(headers[b"x-api-key"])
        return httpx2.Response(
            401, json={"type": "error", "error": {"type": "authentication_error",
                                                  "message": "mock"}},
        )

    client = anthropic.Anthropic(
        api_key=api_key_store.load_api_key_from_file(),
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    with pytest.raises(anthropic.AuthenticationError):
        client.messages.create(
            model="claude-opus-5", max_tokens=1,
            messages=[{"role": "user", "content": "x"}],
        )
    assert sent == [KEY.encode("ascii")]


def test_p5_a_migration_keeps_a_file_holding_a_different_key(locations, backend):
    fake = backend()
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())
    locations.exe.write_text(OTHER, encoding="utf-8")

    result = _notes()

    assert result.key == KEY and fake.held == KEY
    assert not locations.config.exists()
    assert locations.exe.read_text(encoding="utf-8") == OTHER   # the only copy
    assert [n.warning for n in result.notes] == [True]
    assert str(locations.exe) in result.notes[0].text


def test_p5_a_migration_deletes_a_duplicate_of_the_key_it_verified(locations, backend):
    backend()
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())
    locations.exe.write_text(KEY + "\r\n", encoding="utf-8")

    result = _notes()

    assert result.key == KEY and result.notes == ()
    assert not locations.config.exists() and not locations.exe.exists()


def test_p5_a_refused_file_gives_way_to_a_key_in_the_next_location(locations, backend):
    fake = backend()
    locations.config.write_text("hello world", encoding="utf-8")
    locations.exe.write_text(KEY, encoding="utf-8")

    result = _notes()

    assert result.key == KEY and fake.held == KEY
    assert not locations.exe.exists()
    assert locations.config.read_text(encoding="utf-8") == "hello world"
    # Named once, as not a key: not a second time as "left in place".
    assert len(result.notes) == 1
    assert str(locations.config) in result.notes[0].text


def test_p6_a_bom_only_file_is_empty_not_a_key(locations, backend):
    fake = backend()
    locations.config.write_bytes(b"\xef\xbb\xbf")

    result = _notes()

    assert result.key == ""
    assert fake.held is None and fake.sets == 0
    assert locations.config.exists()
    assert len(result.notes) == 1 and result.notes[0].warning
    assert "empty" in result.notes[0].text
    assert str(locations.config) in result.notes[0].text


def test_p7_a_key_followed_by_a_comment_line_is_refused_and_kept(locations, backend):
    fake = backend()
    locations.config.write_text(KEY + "\n# my work key", encoding="utf-8")

    assert api_key_store.load_api_key_from_file() == ""
    assert fake.held is None and fake.sets == 0
    assert locations.config.read_text(encoding="utf-8") == KEY + "\n# my work key"


def test_p7_refused_with_no_keyring_too(locations, backend):
    backend(None)
    locations.config.write_text(KEY + "\n# my work key", encoding="utf-8")

    assert api_key_store.load_api_key_from_file() == ""
    assert locations.config.exists()


@pytest.mark.parametrize("codec", ["utf-16-le", "utf-16-be"])
def test_p8_a_utf16_file_is_decoded(locations, backend, codec):
    fake = backend()
    bom = b"\xff\xfe" if codec.endswith("le") else b"\xfe\xff"
    locations.config.write_bytes(bom + (KEY + "\r\n").encode(codec))

    assert api_key_store.load_api_key_from_file() == KEY
    assert fake.held == KEY
    assert not locations.config.exists()


def test_p8_a_file_that_is_neither_utf8_nor_utf16_is_named(locations, backend):
    fake = backend()
    locations.config.write_bytes(KEY.encode() + b"\xe9\xff")

    result = _notes()

    assert result.key == "" and fake.sets == 0
    assert locations.config.exists()
    assert len(result.notes) == 1 and str(locations.config) in result.notes[0].text


def test_p9_format_characters_at_either_end_are_stripped(locations, backend):
    fake = backend()
    locations.config.write_text("\u200b" + KEY + "\u2060", encoding="utf-8")

    assert api_key_store.load_api_key_from_file() == KEY
    assert fake.held == KEY
    assert not locations.config.exists()


def test_p9_a_format_character_inside_the_key_is_refused(locations, backend):
    fake = backend()
    locations.config.write_text(KEY[:20] + "\u200b" + KEY[20:], encoding="utf-8")

    assert api_key_store.load_api_key_from_file() == ""
    assert fake.sets == 0 and locations.config.exists()


def test_p11_junk_in_a_key_file_is_refused_and_kept(locations, backend):
    fake = backend()
    locations.config.write_text("hello world", encoding="utf-8")

    result = _notes()

    assert result.key == "" and fake.sets == 0
    assert locations.config.exists()
    assert len(result.notes) == 1 and "sk-ant-" in result.notes[0].text


def test_p13_a_backend_that_drops_the_bom_on_read_verifies_the_clean_key(
    locations, backend
):
    fake = backend(_FakeKeyringModule(on_read=lambda v: v.lstrip(BOM)))
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())

    assert api_key_store.load_api_key_from_file() == KEY
    assert fake.held == KEY
    assert not locations.config.exists()


def test_an_oversized_key_file_is_named_not_read_whole(locations, backend):
    fake = backend()
    locations.config.write_bytes(b"sk-ant-" + b"A" * (64 * 1024))

    result = _notes()

    assert result.key == "" and fake.sets == 0
    assert locations.config.exists()
    assert len(result.notes) == 1 and str(locations.config) in result.notes[0].text


def test_an_unreadable_key_file_is_named(locations, backend, monkeypatch):
    backend()
    locations.config.write_text(KEY, encoding="utf-8")
    real_open = type(locations.config).open

    def deny(self, *a, **k):
        if self == locations.config:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *a, **k)

    monkeypatch.setattr(type(locations.config), "open", deny)

    result = _notes()

    assert result.key == ""
    assert locations.config.exists()
    assert len(result.notes) == 1
    assert str(locations.config) in result.notes[0].text
    assert "PermissionError" in result.notes[0].text


def test_a_migration_that_cannot_be_verified_keeps_every_file(locations, backend):
    """Unchanged: no verified keyring copy, no deletion (DA-032)."""
    backend(_FakeKeyringModule(fail_set=True))
    locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())
    locations.exe.write_text(OTHER, encoding="utf-8")

    assert api_key_store.load_api_key_from_file() == KEY
    assert locations.config.exists() and locations.exe.exists()


def test_the_migration_helper_deletes_only_the_files_holding_its_key(
    locations, backend
):
    fake = backend()
    locations.config.write_text(KEY, encoding="utf-8")
    locations.exe.write_text(OTHER, encoding="utf-8")

    assert api_key_store._migrate_legacy_file_key(KEY) is True

    assert fake.held == KEY
    assert not locations.config.exists()
    assert locations.exe.read_text(encoding="utf-8") == OTHER


def test_a_file_whose_presence_cannot_be_told_does_not_end_the_load(
    locations, backend, monkeypatch
):
    """``Path.exists()`` re-raises a permission error: after a migration that
    worked, the cleanup must not turn that into a failed load."""
    fake = backend()
    locations.config.write_text(KEY, encoding="utf-8")
    locations.exe.write_text(OTHER, encoding="utf-8")
    real_exists = type(locations.exe).exists

    def exists(self):
        if self == locations.exe:
            raise PermissionError(13, "Permission denied")
        return real_exists(self)

    monkeypatch.setattr(type(locations.exe), "exists", exists)

    result = _notes()

    assert result.key == KEY and fake.held == KEY
    assert not locations.config.exists()
    with open(locations.exe, encoding="utf-8") as fh:      # not Path.exists
        assert fh.read() == OTHER
    assert len(result.notes) == 1 and str(locations.exe) in result.notes[0].text


def test_a_file_that_cannot_be_read_after_a_migration_is_kept_and_named(
    locations, backend, monkeypatch
):
    fake = backend()
    locations.config.write_text(KEY, encoding="utf-8")
    locations.exe.write_text(OTHER, encoding="utf-8")
    real_open = type(locations.exe).open

    def deny(self, *a, **k):
        if self == locations.exe:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *a, **k)

    monkeypatch.setattr(type(locations.exe), "open", deny)

    result = _notes()

    assert result.key == KEY and fake.held == KEY
    with open(locations.exe, encoding="utf-8") as fh:      # not Path.open
        assert fh.read() == OTHER
    assert len(result.notes) == 1
    assert str(locations.exe) in result.notes[0].text
    assert "could not be read" in result.notes[0].text


# --------------------------------------------------------------------------- #
# The keyring entry itself (p10, p11k)
# --------------------------------------------------------------------------- #


def test_p10_a_keyring_entry_stored_with_a_bom_is_repaired(locations, backend):
    fake = backend()
    fake.put(BOM + KEY)

    result = _notes()

    assert result.key == KEY
    assert fake.held == KEY
    assert len(result.notes) == 1 and not result.notes[0].warning
    assert api_key_store.load_api_key_from_file() == KEY
    assert fake.sets == 1                                   # repaired once


def test_p10_a_repair_that_fails_leaves_the_entry_and_serves_the_clean_key(
    locations, backend
):
    fake = backend(_FakeKeyringModule(fail_set=True))
    fake.put(BOM + KEY)

    result = _notes()

    assert result.key == KEY
    assert fake.held == BOM + KEY
    assert len(result.notes) == 1 and result.notes[0].warning


def test_p11_a_keyring_entry_that_is_not_a_key_is_not_served(locations, backend):
    fake = backend()
    fake.put("hello world")

    result = _notes()

    assert result.key == ""
    assert fake.held == "hello world"                       # not deleted
    assert len(result.notes) == 1 and result.notes[0].warning


def test_p11_a_bad_keyring_entry_gives_way_to_a_key_file(locations, backend):
    fake = backend()
    fake.put("hello world")
    locations.config.write_text(KEY, encoding="utf-8")

    assert api_key_store.load_api_key_from_file() == KEY
    assert fake.held == KEY
    assert not locations.config.exists()


def test_a_clean_keyring_entry_is_served_without_a_write(locations, backend):
    fake = backend()
    fake.put(KEY)

    result = _notes()

    assert result.key == KEY and result.notes == () and fake.sets == 0


# --------------------------------------------------------------------------- #
# Saving (p4 and the shape check at save)
# --------------------------------------------------------------------------- #


def test_p4_save_normalizes_before_storing(locations, backend):
    fake = backend()
    assert api_key_store.save_api_key(BOM + KEY + "\n") is None
    assert fake.held == KEY


def test_save_normalizes_the_consented_plaintext_file_too(locations, backend):
    backend(None)
    path = api_key_store.save_api_key(
        "\u200b" + KEY, allow_plaintext_fallback=True
    )
    assert path == locations.config
    assert locations.config.read_text(encoding="utf-8") == KEY


@pytest.mark.parametrize(
    "value",
    ["hello world", KEY + "\n# my work key", "test-key-not-real-do-not-use"],
    ids=["hello-world", "comment-line", "placeholder"],
)
def test_save_refuses_a_value_that_is_not_a_key(locations, backend, value):
    fake = backend()
    locations.exe.write_text(OTHER, encoding="utf-8")

    with pytest.raises(ValueError) as refused:
        api_key_store.save_api_key(value, allow_plaintext_fallback=True)

    assert fake.sets == 0
    assert not locations.config.exists()
    assert locations.exe.exists()                  # a refusal deletes nothing
    assert value not in str(refused.value)
    assert "sk-ant-" in str(refused.value)


def test_save_keeps_its_every_location_rule(locations, backend):
    """The owner's rule: save still removes every plaintext copy (pinned above)."""
    fake = backend()
    locations.config.write_text(KEY, encoding="utf-8")
    locations.exe.write_text(OTHER, encoding="utf-8")

    api_key_store.save_api_key(OTHER)

    assert fake.held == OTHER
    assert not locations.config.exists() and not locations.exe.exists()


# --------------------------------------------------------------------------- #
# Notes: the diagnostics log, and never the value
# --------------------------------------------------------------------------- #


def test_load_api_key_from_file_keeps_its_contract(locations, backend):
    backend()
    locations.config.write_text("hello world", encoding="utf-8")
    value = api_key_store.load_api_key_from_file()
    assert isinstance(value, str) and value == ""


def test_notes_reach_the_diagnostics_log(locations, backend):
    from drawing_analyzer import diagnostics

    backend()
    locations.config.write_text("hello world", encoding="utf-8")
    locations.exe.write_bytes(b"\xef\xbb\xbf")
    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Keep(level=logging.DEBUG)
    logger = diagnostics.get_logger()
    logger.addHandler(handler)
    try:
        result = _notes()
    finally:
        logger.removeHandler(handler)

    assert [r.getMessage() for r in records] == [n.text for n in result.notes]
    assert all(r.levelno == logging.WARNING for r in records)


def _every_scenario(locations, backend):
    """Drive every path that can say something about a key. Yields its words."""
    words: list[str] = []

    def load():
        result = _notes()
        words.extend(n.text for n in result.notes)
        return result

    def reset(fake=...):
        for p in (locations.config, locations.exe):
            p.unlink(missing_ok=True)
        return backend(fake)

    reset(); locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode()); load()
    reset(); locations.config.write_bytes(b"\xef\xbb\xbf" + KEY.encode())
    locations.exe.write_text(OTHER, encoding="utf-8"); load()
    reset(); locations.config.write_text(KEY + "\n# my work key", encoding="utf-8"); load()
    reset(); locations.config.write_text("hello world " + KEY, encoding="utf-8"); load()
    reset(); locations.config.write_bytes(KEY.encode() + b"\xe9\xff"); load()
    reset(); locations.config.write_bytes(b"sk-ant-" + b"A" * (64 * 1024)); load()
    fake = reset(); fake.put(BOM + KEY); load()
    fake = reset(_FakeKeyringModule(fail_set=True)); fake.put(BOM + KEY); load()
    fake = reset(); fake.put("junk " + KEY); load()
    for bad in ("hello world " + KEY, KEY + "\n# my work key", ""):
        reset()
        try:
            api_key_store.save_api_key(bad)
        except Exception as exc:  # noqa: BLE001 - the message is what is checked
            words.append(str(exc))
    reset(None)
    try:
        api_key_store.save_api_key(KEY)
    except Exception as exc:  # noqa: BLE001
        words.append(str(exc))
    return words


def test_no_note_log_record_exception_or_output_carries_the_key(
    locations, backend, capsys
):
    from drawing_analyzer import diagnostics

    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Keep(level=logging.DEBUG)
    watched = [logging.getLogger(), diagnostics.get_logger()]
    for logger in watched:
        logger.addHandler(handler)
    try:
        words = _every_scenario(locations, backend)
    finally:
        for logger in watched:
            logger.removeHandler(handler)
    captured = capsys.readouterr()

    assert words, "the scenarios said nothing: the check below would be vacuous"
    assert records, "nothing was logged: the check below would be vacuous"
    corpus = "\n".join(
        [*words, *(r.getMessage() for r in records), captured.out, captured.err]
    )
    for fragment in _KEY_FRAGMENTS:
        assert fragment not in corpus
    assert "hello world" not in corpus and "my work key" not in corpus
