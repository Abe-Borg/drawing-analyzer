"""Namespace invalidation, paid v10 compatibility, and bounded cache cleanup."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from drawing_analyzer import digest_cache as cache_module
from drawing_analyzer.digest import digest_sheet
from drawing_analyzer.digest_cache import DigestCache
from tests.test_drawing_digest_cache import _CountingClient, _ok_response, _sheet, OPUS


NAMESPACES = ("digest", "critique", "identity", "review_plan", "citation", "investigation")


def _keys(populated=False):
    sheet = SimpleNamespace(
        overview=SimpleNamespace(png_bytes=b"OVERVIEW"),
        tiles=[
            SimpleNamespace(png_bytes=b"T0", row=0, col=0, label="r0c0"),
            SimpleNamespace(png_bytes=b"T1", row=1, col=0, label="r1c0"),
        ],
        rows=2 if populated else 6, cols=1 if populated else 6, omitted_tiles=[],
    )
    params = dict(model=OPUS, prompt_version="cache-key-regression", max_tokens=16000,
                  effort="high", use_thinking=True)
    digest_opts = dict(focus="rooms and fixtures", specs="project specification") if populated else {}
    critique_opts = dict(profiles_key="fp@1@hash", structured_key="structured-v1") if populated else {}
    text = dict(sheet_text="VAV-3 serves Rm 120") if populated else {}
    return dict(
        digest=cache_module.digest_cache_key(sheet, **params, **digest_opts, **text),
        digest_level1=cache_module.digest_cache_key_level1(
            "render-identity-v4|page=abc", **params, **digest_opts),
        critique=cache_module.critique_cache_key(sheet, runs=2, **params, **critique_opts, **text),
        critique_level1=cache_module.critique_cache_key_level1(
            "render-identity-v4|page=abc", runs=2, **params, **critique_opts),
        identity=cache_module.identity_cache_key("corpus-hash", **params),
        review_plan=cache_module.review_plan_cache_key("scope-hash", max_items=60, **params),
        citation=cache_module.citation_cache_key(
            "payload-hash", model=params["model"], prompt_version=params["prompt_version"],
            request_shape={"tools": ["web_search", "web_fetch"], "max_uses": 3}),
        investigation=cache_module.investigation_cache_key(
            "payload-hash", model=params["model"], prompt_version=params["prompt_version"],
            max_rounds=6, task_budget=16000),
    )


# Captured from the original global-v10 implementation, before changing it.
V10_KEYS = {
    "digest": "d2bfd6684cbe125668aebbec488e97cfb0793df4d996f94de2dd4e14b0baf6d0",
    "digest_level1": "8805f62a2ebc8fc000da74c5b834be21580f913c0a74cb0a4413382ba813f06d",
    "critique": "64deca8fafa02a75aefc18420f07b3f167009fda1cededb42d5aa45c9910930c",
    "critique_level1": "934445f0e30e425aa9c00680145663a75263f0c89bfb5ceb576d406b1eb16257",
    "identity": "8fc4abc25ef083b6cb1072caea174c9146195680bc8dd1c872e384692b10f551",
    "review_plan": "90ad012574b16e27c40104452055d13ff223b385f328e27fe9b8be3bc0ba4bdf",
    "citation": "9645cbb1866221c769c51ce7289c21e06eff1108223cdc8d13ed72625a7f36c1",
    "investigation": "0d180976531276dbb2cb498df5f40622d60cf0116d899b86f0869b3c42d7ad45",
}
V10_POPULATED_KEYS = {
    **V10_KEYS,
    "digest": "8025af31a1598166506b73c97c6b6840d9e7ea0eeea2631331c42610a0346e15",
    "digest_level1": "31d0bb7f93fec559f07057cef69f182810dd57f7fc42299802935643d9ebc95c",
    "critique": "30962e7a003f353f920b6e8875885c5653074ae5ddcc42a755662d32e06955d8",
    "critique_level1": "83a7155019a59af2e237cf1abafbd1f866ae12213bd57a5cd1e0c295e23e95c0",
}


@pytest.mark.parametrize("populated", [False, True])
def test_existing_v10_keys_are_byte_identical(populated):
    assert all(cache_module.cache_schema_version(stage) == 10 for stage in NAMESPACES)
    assert _keys(populated) == (V10_POPULATED_KEYS if populated else V10_KEYS)


@pytest.mark.parametrize("namespace", NAMESPACES)
@pytest.mark.parametrize("persistent", [False, True])
def test_schema_bump_misses_only_its_namespace(namespace, persistent, tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite3" if persistent else None
    cache = DigestCache(path)
    before = _keys(populated=True)
    for name, key in before.items():
        cache.put(key, {"name": name})
    monkeypatch.setattr(cache_module, f"_{namespace.upper()}_SCHEMA_VERSION", 11)
    if persistent:
        cache.close()
        cache = DigestCache(path)
    try:
        after = _keys(populated=True)
        for name, key in after.items():
            changed = name in (namespace, f"{namespace}_level1")
            assert (key != before[name]) == changed
            assert cache.get(key) == (None if changed else {"name": name})
            # Invalidation does not delete the old paid rows.
            assert cache.get(before[name]) == {"name": name}
        assert cache.stats()["size"] == len(before)
    finally:
        cache.close()


def test_critique_bump_keeps_real_digest_hit_without_new_call(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite3"
    client = _CountingClient(_ok_response)
    cache = DigestCache(path)
    first = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    assert first.ok and not first.cached and client.calls == 1
    cache.close()
    monkeypatch.setattr(cache_module, "_CRITIQUE_SCHEMA_VERSION", 11)
    cache = DigestCache(path)
    try:
        warm = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
        assert warm.ok and warm.cached and warm.text == first.text
        assert client.calls == 1
    finally:
        cache.close()


@pytest.mark.parametrize("legacy_format", ["json", "sqlite"])
def test_v10_migration_after_critique_bump_preserves_all_paid_rows(
    legacy_format, tmp_path, monkeypatch,
):
    path = tmp_path / "cache.json"
    entries = {key: {"name": name, "created_ts": 1} for name, key in V10_KEYS.items()}
    if legacy_format == "json":
        path.write_text(json.dumps({"_schema_version": 10, "entries": entries}), encoding="utf-8")
    else:
        with sqlite3.connect(path) as raw:
            raw.execute("CREATE TABLE cache_entries (cache_key TEXT PRIMARY KEY, "
                        "value_json TEXT NOT NULL) WITHOUT ROWID")
            raw.executemany("INSERT INTO cache_entries VALUES (?, ?)",
                            [(key, json.dumps(entry)) for key, entry in entries.items()])
            raw.execute("CREATE TABLE cache_metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            raw.execute("INSERT INTO cache_metadata VALUES ('cache_schema_version', '10')")
            raw.execute("CREATE TABLE pending_batches (batch_id TEXT PRIMARY KEY, value_json TEXT NOT NULL)")
            raw.execute("INSERT INTO pending_batches VALUES ('paid-batch', '{}')")
            raw.execute("PRAGMA user_version=1")
    monkeypatch.setattr(cache_module, "_CRITIQUE_SCHEMA_VERSION", 11)
    monkeypatch.setattr(cache_module.time, "time", lambda: 100_000_000.0)
    cache = DigestCache(path)
    try:
        assert cache._connection is not None
        assert cache._connection.execute("PRAGMA user_version").fetchone()[0] == cache_module._DB_FORMAT_VERSION
        assert cache.collect_garbage() == 0  # Even very old payloads get a full window.
        assert cache.stats()["size"] == len(entries)
        for name, key in _keys().items():
            assert cache.get(key) == (None if name.startswith("critique") else entries[key])
        for key, entry in entries.items():
            assert cache.get(key) == entry
        if legacy_format == "sqlite":
            assert cache.pending_batches() == [{}]
    finally:
        cache.close()
    cache = DigestCache(path)
    try:
        assert cache.get(V10_KEYS["digest"]) == entries[V10_KEYS["digest"]]
        assert cache.stats()["size"] == len(entries)
    finally:
        cache.close()


def test_garbage_collection_is_bounded_and_keeps_current_and_refreshed_rows(tmp_path, monkeypatch):
    now = 100_000_000.0
    monkeypatch.setattr(cache_module.time, "time", lambda: now)
    cache = DigestCache(tmp_path / "cache.sqlite3")
    try:
        old_key = _keys()["critique"]
        monkeypatch.setattr(cache_module, "_CRITIQUE_SCHEMA_VERSION", 11)
        current_key = _keys()["critique"]
        cache.put(old_key, {"name": "old critique"})
        cache.put(current_key, {"name": "current critique"})
        cache.put("warm-digest", {"text": "still used"})
        cache.put("boundary", {"text": "exactly at cap"})
        stale_at = now - cache_module._CACHE_MAX_IDLE_SECONDS - 1
        stale_keys = [old_key, "warm-digest"] + [f"stale-{i}" for i in range(cache_module._GC_BATCH_SIZE + 2)]
        cache._connection.executemany(
            "INSERT INTO cache_entries(cache_key, value_json, last_used_at) VALUES (?, '{}', ?) "
            "ON CONFLICT(cache_key) DO UPDATE SET last_used_at=excluded.last_used_at",
            [(key, stale_at) for key in stale_keys],
        )
        cache._connection.execute("UPDATE cache_entries SET last_used_at=? WHERE cache_key='boundary'",
                                  (stale_at + 1,))
        # Hit the old digest before sweeping: its idle clock must refresh.
        assert cache.get("warm-digest") == {"text": "still used"}
        cache.record_batch({"batch_id": "paid-batch"})
        assert cache.collect_garbage(now=now) == cache_module._GC_BATCH_SIZE
        assert cache.stats()["size"] == 6  # Three stale, three retained.
        assert cache.collect_garbage(now=now) == 3
        assert cache.get(old_key) is None
        assert cache.get(current_key) == {"name": "current critique"}
        assert cache.get("warm-digest") == {"text": "still used"}
        assert cache.get("boundary") == {"text": "exactly at cap"}
        assert cache.pending_batches() == [{"batch_id": "paid-batch"}]
        assert cache.collect_garbage(now=now) == 0
    finally:
        cache.close()


@pytest.mark.parametrize("trigger", ["open", "write"])
def test_idle_garbage_collection_runs_automatically(trigger, tmp_path, monkeypatch):
    now = 100_000_000.0
    monkeypatch.setattr(cache_module.time, "time", lambda: now)
    path = tmp_path / "cache.sqlite3"
    cache = DigestCache(path)
    cache.put("stale", {"text": "expired"})
    cache.put("current", {"text": "paid"})
    cache._connection.execute("UPDATE cache_entries SET last_used_at=0 WHERE cache_key='stale'")
    if trigger == "open":
        cache.close()
        cache = DigestCache(path)
    else:
        cache._next_gc_at = 0
        cache.put("next", {"text": "new"})
    try:
        assert cache.get("stale") is None
        assert cache.get("current") == {"text": "paid"}
    finally:
        cache.close()


def test_cleanup_failure_does_not_hide_durable_entries(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite3"
    cache = DigestCache(path)
    cache.put("paid", {"text": "digest"})
    cache.close()

    def fail_cleanup(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cache_module, "_collect_database_garbage", fail_cleanup)
    cache = DigestCache(path)
    try:
        assert cache.get("paid") == {"text": "digest"}
        assert cache.collect_garbage() == 0
        cache._next_gc_at = 0
        cache.put("next", {"text": "new"})
        assert cache.batch_entries_persisted(["paid", "next"])
    finally:
        cache.close()
