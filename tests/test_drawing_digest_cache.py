"""Digest-cache tests (Workstream 1).

Hermetic: builds a fake ``RenderedSheet`` and a fake Anthropic client, so no
PyMuPDF, no network, no on-disk default cache (tests inject their own
``DigestCache`` — in-memory or pointed at ``tmp_path``).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from pathlib import Path

import drawing_analyzer.digest_cache as digest_cache_module
from drawing_analyzer.digest import DIGEST_PROMPT_VERSION, digest_sheet
from drawing_analyzer.digest_cache import (
    _DB_FORMAT_VERSION,
    _SCHEMA_VERSION,
    DigestCache,
    critique_cache_key,
    default_cache_path,
    digest_cache_key,
    digest_cache_key_level1,
    persistence_enabled,
)
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

OPUS = "claude-opus-4-8"


def _sheet(
    overview: bytes = b"OVERVIEW", tiles=(b"T0", b"T1"), sheet_text: str = ""
) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=Path("M-101.pdf"), page_index=0, source_name="M-101.pdf", page_count=1
    )
    ov = ImageTile(png_bytes=overview, width_px=100, height_px=80, kind="overview")
    tl = [
        ImageTile(png_bytes=b, width_px=100, height_px=80, kind="tile", row=i, col=0, label=f"r{i}c0")
        for i, b in enumerate(tiles)
    ]
    return RenderedSheet(
        ref=ref, overview=ov, tiles=tl, page_width_pt=100, page_height_pt=80,
        rows=len(tl), cols=1, sheet_text=sheet_text,
    )


class _CountingClient:
    def __init__(self, responder):
        self.calls = 0
        self._responder = responder

        class _Msgs:
            def create(_self, **kw):
                self.calls += 1
                return self._responder(kw)

        self.messages = _Msgs()


def _ok_response(_kw):
    return FakeMessage(
        content=[FakeTextBlock(text="VAV-3 serves Rm 120")],
        usage=FakeUsage(input_tokens=500, output_tokens=80),
    )


# --------------------------------------------------------------------------- #
# Key
# --------------------------------------------------------------------------- #


def _key(sheet, **over):
    base = dict(
        model=OPUS, prompt_version=DIGEST_PROMPT_VERSION,
        max_tokens=16000, effort="high", use_thinking=True,
    )
    base.update(over)
    return digest_cache_key(sheet, **base)


def test_key_stable_for_same_inputs():
    assert _key(_sheet()) == _key(_sheet())


def test_key_changes_with_content_model_and_params():
    base = _key(_sheet())
    assert _key(_sheet(overview=b"DIFFERENT")) != base       # page content
    assert _key(_sheet(tiles=(b"T0", b"T9"))) != base        # a tile changed
    assert _key(_sheet(), model="claude-sonnet-4-6") != base  # model swap
    assert _key(_sheet(), prompt_version="other") != base     # prompt edit
    assert _key(_sheet(), max_tokens=8000) != base
    assert _key(_sheet(), effort="low") != base
    assert _key(_sheet(), use_thinking=False) != base


def test_key_folds_in_sheet_text():
    base = _key(_sheet())  # no sheet_text -> not folded
    # Same rendered pixels, different text layer (the corrected-OCR case, where
    # a hidden text layer changes without re-rendering) must yield a new key.
    assert _key(_sheet(), sheet_text="flow test 540") != _key(
        _sheet(), sheet_text="flow test 660"
    )
    # Adding text where there was none also changes the key.
    assert _key(_sheet(), sheet_text="VAV-3") != base
    # Empty / absent text leaves the key byte-identical: a raster sheet keys on
    # its pixels, and empty text implies the (different) raster render target.
    assert _key(_sheet(), sheet_text="") == base
    assert _key(_sheet(), sheet_text=None) == base


# --------------------------------------------------------------------------- #
# Level-1 (pre-render) key
# --------------------------------------------------------------------------- #


def _l1(identity="pymupdf=1.28.0|rows=6|cols=6|page=abc", **over):
    base = dict(
        model=OPUS, prompt_version=DIGEST_PROMPT_VERSION,
        max_tokens=16000, effort="high", use_thinking=True,
    )
    base.update(over)
    return digest_cache_key_level1(identity, **base)


def test_level1_key_stable_for_same_identity_and_params():
    assert _l1() == _l1()


def test_level1_key_changes_with_render_identity_and_params():
    base = _l1()
    # The render identity carries the PyMuPDF version, render target, and the
    # page-content fingerprint; any change re-keys (and so re-renders).
    assert _l1(identity="pymupdf=1.28.0|rows=6|cols=6|page=XYZ") != base  # page content
    assert _l1(identity="pymupdf=1.29.0|rows=6|cols=6|page=abc") != base  # engine ver
    assert _l1(identity="pymupdf=1.28.0|rows=2|cols=2|page=abc") != base  # grid/target
    # The same request params as the level-2 key re-key it too.
    assert _l1(model="claude-sonnet-4-6") != base
    assert _l1(prompt_version="other") != base
    assert _l1(max_tokens=8000) != base
    assert _l1(effort="low") != base
    assert _l1(use_thinking=False) != base


def test_level1_key_folds_in_focus_only_when_present():
    base = _l1()
    assert _l1(focus=None) == base                 # no focus == pre-focus key
    assert _l1(focus="rooms and fixtures") != base  # a focus re-keys


def test_level1_key_never_collides_with_level2_key():
    # Different namespaces (level=1 tag vs the PNG-bytes hash), so a pre-render key
    # can never accidentally match a rendered-bytes key.
    sheet = _sheet()
    l2 = _key(sheet)
    l1 = _l1()
    assert l1 != l2


# --------------------------------------------------------------------------- #
# DigestCache store/persistence
# --------------------------------------------------------------------------- #


def test_cache_in_memory_get_put():
    c = DigestCache(None, persist=False)
    assert c.get("k") is None
    c.put("k", {"text": "hi"})
    assert c.get("k") == {"text": "hi"}
    assert c.stats()["size"] == 1


def test_cache_persists_and_reloads(tmp_path):
    path = tmp_path / "dc.json"
    c1 = DigestCache(path, persist=True)
    c1.put("k", {"text": "persisted"})
    assert path.exists()
    # A fresh instance loads the entry from disk.
    c2 = DigestCache(path, persist=True)
    assert c2.get("k") == {"text": "persisted"}


def test_cache_persist_false_writes_no_file(tmp_path):
    path = tmp_path / "dc.json"
    c = DigestCache(path, persist=False)
    c.put("k", {"text": "x"})
    assert not path.exists()


def test_cache_corrupt_file_loads_empty(tmp_path):
    path = tmp_path / "dc.json"
    path.write_text("not json {", encoding="utf-8")
    c = DigestCache(path, persist=True)  # must not raise
    assert c.get("k") is None


def test_cache_wrong_schema_ignored(tmp_path):
    path = tmp_path / "dc.json"
    path.write_text(json.dumps({"_schema_version": 999, "entries": {"k": {"text": "x"}}}), encoding="utf-8")
    c = DigestCache(path, persist=True)
    assert c.get("k") is None


def test_default_cache_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DRAWING_ANALYZER_CACHE_PATH", str(tmp_path / "custom.json"))
    assert default_cache_path() == tmp_path / "custom.json"


def test_persistence_toggle(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CACHE_PERSIST", "off")
    assert persistence_enabled() is False
    monkeypatch.setenv("DRAWING_ANALYZER_CACHE_PERSIST", "1")
    assert persistence_enabled() is True


def test_legacy_json_migrates_in_place_without_losing_current_schema_entries(tmp_path):
    path = tmp_path / "legacy-cache.json"
    path.write_text(
        json.dumps(
            {
                "_schema_version": _SCHEMA_VERSION,
                "entries": {
                    "digest-key": {"text": "legacy digest", "findings": []},
                    "critique-key": {"text": "legacy critique", "completed_runs": 2},
                    "invalid-row": ["not", "a", "dict"],
                },
            }
        ),
        encoding="utf-8",
    )

    cache = DigestCache(path, persist=True)
    try:
        assert cache.get("digest-key") == {"text": "legacy digest", "findings": []}
        assert cache.get("critique-key") == {
            "text": "legacy critique",
            "completed_runs": 2,
        }
        assert cache.get("invalid-row") is None
        assert cache.stats()["size"] == 2
        assert cache._connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        cache.close()

    # The configured filename is preserved even when it still ends in .json;
    # its contents are now the scalable SQLite store.
    assert path.read_bytes().startswith(b"SQLite format 3\x00")
    reopened = DigestCache(path, persist=True)
    try:
        assert reopened.get("digest-key")["text"] == "legacy digest"
    finally:
        reopened.close()


def test_failed_legacy_migration_is_atomic_and_serves_original_in_memory(
    tmp_path, monkeypatch
):
    path = tmp_path / "legacy-cache.json"
    path.write_text(
        json.dumps(
            {
                "_schema_version": _SCHEMA_VERSION,
                "entries": {"k": {"text": "still available"}},
            }
        ),
        encoding="utf-8",
    )
    original = path.read_bytes()

    def _fail_replace(_source, _target):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(digest_cache_module.os, "replace", _fail_replace)
    cache = DigestCache(path, persist=True)  # migration failure must not escape
    try:
        assert cache.get("k") == {"text": "still available"}
    finally:
        cache.close()

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".drawing_digest_cache.*.sqlite3.tmp")) == []
    assert list(tmp_path.glob(".*.migration.lock")) == []


def test_concurrent_instances_migrate_once_and_do_not_lose_writes(tmp_path):
    path = tmp_path / "shared-cache.json"
    path.write_text(
        json.dumps(
            {
                "_schema_version": _SCHEMA_VERSION,
                "entries": {"legacy": {"text": "seed"}},
            }
        ),
        encoding="utf-8",
    )

    workers = 8
    writes_per_worker = 20

    def _write(worker: int) -> bool:
        cache = DigestCache(path, persist=True)
        try:
            saw_seed = cache.get("legacy") == {"text": "seed"}
            for item in range(writes_per_worker):
                cache.put(
                    f"worker-{worker}:{item}",
                    {"worker": worker, "item": item},
                )
            return saw_seed
        finally:
            cache.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        assert all(pool.map(_write, range(workers)))

    reopened = DigestCache(path, persist=True)
    try:
        assert reopened.stats()["size"] == 1 + workers * writes_per_worker
        for worker in range(workers):
            for item in range(writes_per_worker):
                assert reopened.get(f"worker-{worker}:{item}") == {
                    "worker": worker,
                    "item": item,
                }
    finally:
        reopened.close()


def test_failed_row_serialization_does_not_replace_durable_value(tmp_path):
    path = tmp_path / "cache.json"
    cache = DigestCache(path, persist=True)
    sentinel = object()
    try:
        cache.put("k", {"version": "durable"})
        cache.put("k", {"version": sentinel})  # JSON serialization fails

        # The current run retains its newly computed result in the fallback
        # overlay, but the committed SQLite row remains intact and parseable.
        assert cache.get("k")["version"] is sentinel
        assert cache.stats()["size"] == 1

        reader = DigestCache(path, persist=True)
        try:
            assert reader.get("k") == {"version": "durable"}
        finally:
            reader.close()
    finally:
        cache.close()


def test_transient_write_failure_is_retried_by_next_successful_put(tmp_path):
    path = tmp_path / "cache.json"
    cache = DigestCache(path, persist=True)
    blocker = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        # Force this cache instance's first transaction to fail immediately
        # instead of waiting for the normal 30-second busy timeout.
        cache._connection.execute("PRAGMA busy_timeout=1")
        blocker.execute("BEGIN IMMEDIATE")
        cache.put("held-back", {"text": "computed while busy"})
        assert cache.get("held-back") == {"text": "computed while busy"}

        blocker.rollback()
        cache.put("next", {"text": "flush trigger"})
    finally:
        try:
            blocker.rollback()
        except sqlite3.Error:
            pass
        blocker.close()
        cache.close()

    reopened = DigestCache(path, persist=True)
    try:
        assert reopened.get("held-back") == {"text": "computed while busy"}
        assert reopened.get("next") == {"text": "flush trigger"}
    finally:
        reopened.close()


def test_storage_or_content_schema_mismatch_invalidates_all_rows(tmp_path):
    for mismatch in ("storage", "content"):
        path = tmp_path / f"{mismatch}.json"
        cache = DigestCache(path, persist=True)
        cache.put("digest", {"text": "stale"})
        cache.put("critique", {"text": "also stale"})
        cache.close()

        with sqlite3.connect(path) as raw:
            if mismatch == "storage":
                raw.execute(f"PRAGMA user_version={_DB_FORMAT_VERSION + 1}")
            else:
                raw.execute(
                    "UPDATE cache_metadata SET value = ? WHERE name = ?",
                    (str(_SCHEMA_VERSION - 1), "cache_schema_version"),
                )

        reopened = DigestCache(path, persist=True)
        try:
            assert reopened.get("digest") is None
            assert reopened.get("critique") is None
            assert reopened.stats()["size"] == 0
            assert (
                reopened._connection.execute("PRAGMA user_version").fetchone()[0]
                == _DB_FORMAT_VERSION
            )
            assert reopened._connection.execute(
                "SELECT value FROM cache_metadata WHERE name = ?",
                ("cache_schema_version",),
            ).fetchone() == (str(_SCHEMA_VERSION),)
        finally:
            reopened.close()


def test_digest_and_critique_namespaces_coexist_in_persistent_store(tmp_path):
    sheet = _sheet()
    digest_key = _key(sheet)
    critique_key = critique_cache_key(
        sheet,
        model=OPUS,
        prompt_version="critique-v1",
        max_tokens=16000,
        effort="high",
        use_thinking=True,
        runs=2,
    )
    assert digest_key != critique_key

    path = tmp_path / "cache.json"
    cache = DigestCache(path, persist=True)
    cache.put(digest_key, {"stage": "digest"})
    cache.put(critique_key, {"stage": "critique"})
    cache.close()

    reopened = DigestCache(path, persist=True)
    try:
        assert reopened.get(digest_key) == {"stage": "digest"}
        assert reopened.get(critique_key) == {"stage": "critique"}
        assert reopened.stats()["size"] == 2
    finally:
        reopened.close()


def test_one_corrupt_sqlite_row_is_a_miss_without_poisoning_other_rows(tmp_path):
    path = tmp_path / "cache.json"
    cache = DigestCache(path, persist=True)
    cache.put("good", {"text": "valid"})
    cache.close()

    with sqlite3.connect(path) as raw:
        raw.execute(
            "INSERT INTO cache_entries(cache_key, value_json) VALUES (?, ?)",
            ("bad", "{not valid json"),
        )

    reopened = DigestCache(path, persist=True)
    try:
        assert reopened.get("bad") is None
        assert reopened.get("good") == {"text": "valid"}
        assert reopened.stats()["size"] == 1  # corrupt row was removed
    finally:
        reopened.close()


# --------------------------------------------------------------------------- #
# digest_sheet ↔ cache integration
# --------------------------------------------------------------------------- #


def test_digest_sheet_stores_then_serves_from_cache():
    cache = DigestCache(None, persist=False)
    client = _CountingClient(_ok_response)

    first = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    assert first.ok and first.cached is False
    assert client.calls == 1

    second = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    assert second.ok and second.cached is True
    assert second.text == "VAV-3 serves Rm 120"
    assert second.input_tokens == 500 and second.output_tokens == 80
    assert client.calls == 1  # no second API call — served from cache


def test_digest_sheet_cache_miss_on_model_change():
    cache = DigestCache(None, persist=False)
    client = _CountingClient(_ok_response)

    digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    # Different model → different key → another API call.
    sd = digest_sheet(_sheet(), client=client, model="claude-sonnet-4-6", cache=cache)
    assert sd.cached is False
    assert client.calls == 2


def test_digest_sheet_cache_miss_on_sheet_text_change():
    cache = DigestCache(None, persist=False)
    client = _CountingClient(_ok_response)

    digest_sheet(_sheet(sheet_text="flow test 540"), client=client, model=OPUS, cache=cache)
    assert client.calls == 1
    # Identical rendered pixels but a corrected text layer (hidden-OCR fix) →
    # different key → re-digest rather than serving the stale digest.
    sd = digest_sheet(_sheet(sheet_text="flow test 660"), client=client, model=OPUS, cache=cache)
    assert sd.cached is False
    assert client.calls == 2
    # Re-running the corrected sheet is now served from cache.
    again = digest_sheet(_sheet(sheet_text="flow test 660"), client=client, model=OPUS, cache=cache)
    assert again.cached is True
    assert client.calls == 2


def test_digest_sheet_does_not_cache_empty_result():
    cache = DigestCache(None, persist=False)
    client = _CountingClient(lambda kw: FakeMessage(content=[], stop_reason="max_tokens"))

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    assert not sd.ok
    assert cache.stats()["size"] == 0  # empty/error digests are never cached


def test_digest_sheet_no_cache_when_none():
    client = _CountingClient(_ok_response)
    sd = digest_sheet(_sheet(), client=client, model=OPUS)  # cache=None
    assert sd.ok and sd.cached is False
    assert client.calls == 1
