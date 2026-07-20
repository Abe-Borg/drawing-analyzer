"""Hermetic tests for the shared post-digest stage-cache contract."""
from __future__ import annotations

from drawing_analyzer.stage_cache import (
    get_stage_cache_entry,
    put_stage_cache_entry,
    stage_cache_key,
)


class _MemoryCache:
    def __init__(self):
        self.entries = {}

    def get(self, key):
        return self.entries.get(key)

    def put(self, key, value):
        self.entries[key] = value


def _key(**changes):
    args = {
        "stage": "synthesis",
        "model": "claude-opus-4-8",
        "prompt": {"system": "review"},
        "inputs": {"sheets": ["A", "B"]},
        "params": {"max_tokens": 8000},
    }
    args.update(changes)
    return stage_cache_key(**args)


def test_stage_key_is_canonical_and_invalidates_every_contract_axis():
    baseline = _key()
    assert baseline == _key(
        prompt={"system": "review"},
        inputs={"sheets": ["A", "B"]},
        params={"max_tokens": 8000},
    )
    assert baseline != _key(model="claude-sonnet-4-6")
    assert baseline != _key(prompt={"system": "revised review"})
    assert baseline != _key(inputs={"sheets": ["A", "C"]})
    assert baseline != _key(params={"max_tokens": 4000})


def test_stage_entry_is_namespaced_validated_and_defensively_copied():
    cache = _MemoryCache()
    key = _key()
    put_stage_cache_entry(
        cache, key, stage="synthesis", payload={"nested": {"value": 1}}
    )

    first = get_stage_cache_entry(cache, key, stage="synthesis")
    assert first == {"nested": {"value": 1}}
    first["nested"]["value"] = 99
    assert get_stage_cache_entry(cache, key, stage="synthesis") == {
        "nested": {"value": 1}
    }
    assert get_stage_cache_entry(cache, key, stage="cross_qc") is None

