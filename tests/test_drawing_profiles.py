"""Tests for review profiles (Phase 12) — the loader, discovery, discipline
auto-suggest, cache fragment, and prompt assembly. Pure and hermetic (no model,
no PyMuPDF); the user profiles dir is pinned to a tmp dir via the env override so
the suite never depends on the machine's real ``~/.drawing_analyzer``.
"""
from __future__ import annotations

import pytest

from drawing_analyzer import profiles as P


@pytest.fixture(autouse=True)
def _empty_user_dir(tmp_path, monkeypatch):
    """Point the user profiles dir at an empty tmp dir by default (hermetic)."""
    d = tmp_path / "user_profiles"
    d.mkdir()
    monkeypatch.setenv("DRAWING_ANALYZER_PROFILES_DIR", str(d))
    return d


_SAMPLE = """\
---
name: demo
title: Demo Discipline QC
disciplines: X, XY ; Z
version: 3
author: Tester
date: 2026-07-09
---

# Checklist

Some intro prose that is not a bullet and is ignored.

- First check: flag the wrong thing. [high]
* Second check (asterisk bullet).
- Third check with a code ref (NFPA 13 §1.2.3).
"""


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parse_profile_reads_frontmatter_and_items():
    p = P.parse_profile(_SAMPLE, source_path="demo.md", fallback_name="demo")
    assert p.name == "demo"
    assert p.title == "Demo Discipline QC"
    assert p.disciplines == ("x", "xy", "z")     # comma + semicolon, lower-cased
    assert p.version == "3" and p.author == "Tester" and p.date == "2026-07-09"
    assert len(p.items) == 3                       # both - and * bullets, prose ignored
    assert p.items[0].startswith("First check")
    assert p.items[1].startswith("Second check")
    assert len(p.content_hash) == 16


def test_parse_profile_without_frontmatter_falls_back():
    p = P.parse_profile("- only an item\n- and another", fallback_name="bare")
    assert p.name == "bare" and p.title == "bare"
    assert p.disciplines == () and p.items == ("only an item", "and another")


def test_content_hash_changes_on_any_edit():
    a = P.parse_profile(_SAMPLE, fallback_name="demo")
    b = P.parse_profile(_SAMPLE.replace("First check", "First CHECK"), fallback_name="demo")
    assert a.content_hash != b.content_hash


# --------------------------------------------------------------------------- #
# Discovery + user-dir override
# --------------------------------------------------------------------------- #


def test_builtin_fire_protection_profile_ships_and_loads():
    profs = P.load_profiles()
    assert "fire-protection" in profs
    fp = profs["fire-protection"]
    assert fp.items and any("K-8.0" in it for it in fp.items)
    assert "f" in fp.disciplines


def test_user_dir_adds_and_wins_on_name_collision(_empty_user_dir):
    # A user profile with a fresh name is added...
    (_empty_user_dir / "mine.md").write_text(
        "---\nname: my-mechanical\ndisciplines: M\n---\n- check ducts\n",
        encoding="utf-8",
    )
    # ...and one reusing a built-in name shadows the built-in.
    (_empty_user_dir / "fp.md").write_text(
        "---\nname: fire-protection\ntitle: OVERRIDDEN\nversion: 99\n---\n- my own check\n",
        encoding="utf-8",
    )
    profs = P.load_profiles()
    assert "my-mechanical" in profs
    assert profs["fire-protection"].title == "OVERRIDDEN"      # user wins
    assert profs["fire-protection"].version == "99"


def test_get_and_resolve_profiles():
    fp = P.get_profile("fire-protection")
    assert fp is not None
    resolved = P.resolve_profiles(["fire-protection", "does-not-exist", fp])
    # unknown dropped; the name and the passed-through object both resolve
    assert [r.name for r in resolved] == ["fire-protection", "fire-protection"]
    assert P.resolve_profiles(None) == [] and P.resolve_profiles([]) == []


# --------------------------------------------------------------------------- #
# Discipline auto-suggest
# --------------------------------------------------------------------------- #


def test_discipline_hint():
    assert P.discipline_hint("F-D-01-1") == "f"
    assert P.discipline_hint("FP-101") == "fp"
    assert P.discipline_hint("M-101") == "m"
    assert P.discipline_hint("") == ""


def test_suggest_profiles_by_discipline():
    assert [p.name for p in P.suggest_profiles(["F-D-01-1", "F-G-02-0"])] == ["fire-protection"]
    assert P.suggest_profiles(["M-101", "E-201"]) == []       # no mechanical/electrical profile
    assert P.suggest_profiles([]) == []


# --------------------------------------------------------------------------- #
# Cache fragment + prompt assembly + chunking
# --------------------------------------------------------------------------- #


def test_cache_fragment_is_order_independent_and_edit_sensitive():
    a = P.parse_profile(_SAMPLE, fallback_name="a")
    b = P.parse_profile(_SAMPLE.replace("name: demo", "name: other"), fallback_name="b")
    assert P.profiles_cache_fragment([]) is None
    # order-independent
    assert P.profiles_cache_fragment([a, b]) == P.profiles_cache_fragment([b, a])
    # sensitive to an edit (content_hash) ...
    a2 = P.parse_profile(_SAMPLE.replace("First check", "First CHECK"), fallback_name="a")
    assert P.profiles_cache_fragment([a]) != P.profiles_cache_fragment([a2])
    # ... and includes name + version + hash
    frag = P.profiles_cache_fragment([a])
    assert a.name in frag and a.version in frag and a.content_hash in frag


def test_build_checklist_prompt():
    fp = P.get_profile("fire-protection")
    items = P.flatten_items([fp])
    block = P.build_checklist_prompt(items)
    assert "APPLY THIS REVIEW CHECKLIST" in block
    assert all(f"- {it}" in block for it in items)
    assert P.build_checklist_prompt([]) == ""
    assert P.build_checklist_prompt(["  ", ""]) == ""       # blank items → empty


def test_chunk_items_splits_evenly_and_losslessly():
    items = [f"item {i}" for i in range(9)]
    chunks = P.chunk_items(items, 2)
    assert len(chunks) == 2
    assert [len(c) for c in chunks] == [5, 4]
    assert [it for c in chunks for it in c] == items          # union = all, in order
    # more chunks than items → some empty, still exactly n, still lossless
    chunks3 = P.chunk_items(["a", "b"], 4)
    assert len(chunks3) == 4 and sum(len(c) for c in chunks3) == 2
