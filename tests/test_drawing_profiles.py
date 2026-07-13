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


def test_numbered_and_plus_bullets_parse_as_items():
    p = P.parse_profile(
        "---\nname: n\n---\n1. first\n2) second\n+ third\n- fourth\n", fallback_name="n"
    )
    assert p.items == ("first", "second", "third", "fourth")
    # a decimal in prose is not a list item
    q = P.parse_profile("---\nname: n\n---\n3.5 gpm density note\n", fallback_name="n")
    assert q.items == ()


def test_unclosed_frontmatter_still_parses_items():
    # A missing closing '---' must not swallow the checklist into a zero-item
    # profile; the bullets are still parsed (name falls back to the stem).
    p = P.parse_profile("---\nname: n\ndisciplines: f\n- real item\n", fallback_name="stem")
    assert p.items == ("real item",)
    assert p.name == "stem"


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


def test_bad_encoding_file_does_not_sink_discovery(_empty_user_dir):
    # A non-UTF-8 .md (UnicodeDecodeError is a ValueError, not OSError) must not
    # crash discovery or lose the valid profiles alongside it.
    (_empty_user_dir / "good.md").write_text(
        "---\nname: good\n---\n- a check\n", encoding="utf-8"
    )
    (_empty_user_dir / "bad.md").write_bytes("---\nname: bad\n- x\n".encode("utf-16"))
    profs = P.load_profiles()          # must not raise
    assert "good" in profs and "fire-protection" in profs
    assert "bad" not in profs
    assert P.list_profiles()           # must not raise
    # resolving only Profile objects must not even read the (poisoned) dir.
    assert P.resolve_profiles([profs["good"]]) == [profs["good"]]


# --------------------------------------------------------------------------- #
# Discipline auto-suggest
# --------------------------------------------------------------------------- #


def test_discipline_hint():
    # hyphenated (NCS) form
    assert P.discipline_hint("F-D-01-1") == "f"
    assert P.discipline_hint("FP-101") == "fp"
    assert P.discipline_hint("M-101") == "m"
    # concatenated form (letters run straight into digits — no word boundary)
    assert P.discipline_hint("F101") == "f"
    assert P.discipline_hint("FP201") == "fp"
    assert P.discipline_hint("M1") == "m"
    assert P.discipline_hint("E1.01") == "e"
    # no leading letters / empty
    assert P.discipline_hint("101") == "" and P.discipline_hint("") == ""


def test_discipline_hint_is_project_prefix_aware():
    # DA-018: a project-coded id must yield the discipline segment (F), not the
    # leading project code (AVC). Regression for the exact defect.
    assert P.discipline_hint("AVC10-F-D-01-1") == "f"
    assert P.discipline_hint("FP101") == "fp"


def test_suggest_profiles_by_discipline():
    assert [p.name for p in P.suggest_profiles(["F-D-01-1", "F-G-02-0"])] == ["fire-protection"]
    assert [p.name for p in P.suggest_profiles(["F101", "FP201"])] == ["fire-protection"]
    # DA-018: FP101, F-D-01-1, and AVC10-F-D-01-1 all suggest fire protection.
    assert [p.name for p in P.suggest_profiles(["FP101"])] == ["fire-protection"]
    assert [p.name for p in P.suggest_profiles(["AVC10-F-D-01-1"])] == ["fire-protection"]
    assert P.suggest_profiles(["M-101", "E-201"]) == []       # no mechanical/electrical profile
    assert P.suggest_profiles([]) == []


# --------------------------------------------------------------------------- #
# Cache fragment + prompt assembly + chunking
# --------------------------------------------------------------------------- #


def test_cache_fragment_fingerprints_the_actual_checklist():
    assert P.profiles_cache_fragment([]) is None
    # A profile that injects nothing (no items) has no key effect.
    assert P.profiles_cache_fragment([P.Profile(name="empty", title="e", version="1")]) is None
    # Different items collide-proof even when content_hash is left empty (the
    # power-user path of hand-built Profile objects) — the fragment is derived
    # from the items, not the possibly-blank hash.
    p1 = P.Profile(name="x", title="x", version="1", items=("check A",))
    p2 = P.Profile(name="x", title="x", version="1", items=("check B",))
    assert p1.content_hash == "" and p2.content_hash == ""
    assert P.profiles_cache_fragment([p1]) != P.profiles_cache_fragment([p2])
    # Editing an item re-keys.
    a = P.parse_profile(_SAMPLE, fallback_name="a")
    a2 = P.parse_profile(_SAMPLE.replace("First check", "First CHECK"), fallback_name="a")
    assert P.profiles_cache_fragment([a]) != P.profiles_cache_fragment([a2])


def test_build_checklist_prompt():
    fp = P.get_profile("fire-protection")
    items = P.flatten_items([fp])
    block = P.build_checklist_prompt(items)
    assert "APPLY THIS REVIEW CHECKLIST" in block
    assert all(f"- {it}" in block for it in items)
    assert P.build_checklist_prompt([]) == ""
    assert P.build_checklist_prompt(["  ", ""]) == ""       # blank items → empty


# --------------------------------------------------------------------------- #
# Selection resolution + snapshots (Phase 24 §16.4)
# --------------------------------------------------------------------------- #


def test_resolve_profile_selection_manual_choice_wins():
    # Applicable suggestions are on by default...
    assert P.resolve_profile_selection(["fire-protection"]) == ["fire-protection"]
    # ...a deselected suggestion stays off even when re-suggested (survives refresh)...
    assert P.resolve_profile_selection(
        ["fire-protection"], user_deselected=["fire-protection"]
    ) == []
    # ...and an explicit selection adds a profile the preflight did not suggest.
    assert P.resolve_profile_selection(
        ["fire-protection"], user_selected=["mechanical"]
    ) == ["fire-protection", "mechanical"]
    # No duplicates when a name is both suggested and selected.
    assert P.resolve_profile_selection(
        ["fire-protection"], user_selected=["fire-protection"]
    ) == ["fire-protection"]


def test_snapshot_profiles_captures_version_hash_and_source():
    fp = P.get_profile("fire-protection")
    (snap,) = P.snapshot_profiles([fp])
    assert snap.name == "fire-protection" and snap.version == fp.version
    assert snap.content_hash == fp.content_hash and len(snap.content_hash) == 16
    assert snap.source == "builtin"          # ships inside the package
    assert "f" in snap.disciplines


def test_snapshot_marks_user_profiles(_empty_user_dir):
    (_empty_user_dir / "mine.md").write_text(
        "---\nname: my-mech\nversion: 2\ndisciplines: M\n---\n- check\n", encoding="utf-8"
    )
    prof = P.get_profile("my-mech")
    (snap,) = P.snapshot_profiles([prof])
    assert snap.source == "user" and snap.version == "2"


def test_preflight_suggests_profiles_without_rasterizing(tmp_path):
    # §16.4: a cheap text-only preflight detects the title-block sheet id and
    # auto-suggests a profile — no overview/tile rasterization needed.
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "F-D-01-1.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "SPRINKLER PLAN")
    page.insert_text((650, 560), "F-D-01-1")          # title-block sheet id (bottom-right)
    doc.save(str(path))
    doc.close()
    assert P.preflight_sheet_ids([path]) == ["F-D-01-1"]
    assert [p.name for p in P.suggest_profiles_for_paths([path])] == ["fire-protection"]


def test_chunk_items_splits_evenly_and_losslessly():
    items = [f"item {i}" for i in range(9)]
    chunks = P.chunk_items(items, 2)
    assert len(chunks) == 2
    assert [len(c) for c in chunks] == [5, 4]
    assert [it for c in chunks for it in c] == items          # union = all, in order
    # more chunks than items → some empty, still exactly n, still lossless
    chunks3 = P.chunk_items(["a", "b"], 4)
    assert len(chunks3) == 4 and sum(len(c) for c in chunks3) == 2
