"""Keeping checks from a run's checklist as the user's own checklist files."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from drawing_analyzer import checklist_save as cs
from drawing_analyzer import profiles as P

DAY = date(2026, 11, 14)
PLAN_LINE = ("Double-interlock preaction remote areas carry the design-area increase "
             "[high] (NFPA 13 2025)")


def _checks(*pairs):
    return [cs.PickedCheck(id=i, text=t) for i, t in pairs]


def test_a_new_checklist_loads_as_a_profile_and_never_overwrites_another(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_PROFILES_DIR", str(tmp_path))
    picked = _checks(
        ("M1.1", "Each data hall states its preaction type"),
        ("M1.2", PLAN_LINE),
        ("M1.3", "  dry / preaction systems show ITV,   air supply and gauges. "),
        ("M1.4", "each DATA hall states its preaction type."),
    )
    known = [("U1.2", "Dry / preaction systems show ITV, air supply and gauges")]
    first = cs.save_new("Data center FP: preaction", picked, disciplines="FP, f; ??, fp",
                        known=known, today=DAY)

    # Text already kept (in the reader's own checklist, or earlier in the same
    # pick) is skipped and says where it is; case, spacing and a trailing stop
    # do not make a different check.
    assert [c.id for c in first.adding] == ["M1.1", "M1.2"]
    assert [(c.id, where) for c, where in first.skipped] == [("M1.3", "U1.2"), ("M1.4", "M1.1")]
    loaded = P.load_profiles()[first.name]
    assert loaded.title == "Data center FP: preaction"
    assert loaded.items == ("Each data hall states its preaction type", PLAN_LINE)
    assert loaded.disciplines == ("fp", "f")          # junk dropped, repeats folded
    # It is suggested for a set whose sheet numbers carry its prefixes.
    assert [p.name for p in P.suggest_profiles(["FP-101"])] == [first.name]

    # The same title again takes the next free name; the first file is untouched.
    before = first.path.read_bytes()
    second = cs.save_new("Data center FP: preaction", picked[:1], today=DAY)
    assert second.path != first.path and second.name != first.name
    assert first.path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [first.path.name, second.path.name])          # no temp files left behind

    # Nothing new to keep: refused, nothing written.
    with pytest.raises(ValueError):
        cs.save_new("Again", picked[2:3], known=known, directory=tmp_path, today=DAY)
    assert len(list(tmp_path.iterdir())) == 2

    # Another window saves the same name at the very instant this file lands:
    # the write refuses that file and the save lands on the next free name.
    raced = tmp_path / "raced.md"

    def lands_after_the_other_window(real):
        def call(src, dst, *args, **kwargs):
            if Path(dst) == raced and not raced.exists():
                raced.write_text("the other window's checklist\n", encoding="utf-8")
            return real(src, dst, *args, **kwargs)
        return call

    monkeypatch.setattr(cs.os, "link", lands_after_the_other_window(os.link))
    monkeypatch.setattr(cs.os, "replace", lands_after_the_other_window(os.replace))
    third = cs.save_new("Raced", picked[:1], directory=tmp_path, today=DAY)
    assert raced.read_text(encoding="utf-8") == "the other window's checklist\n"
    assert third.path == tmp_path / "raced-2.md" and third.path.exists()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".saving-")]


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_adding_to_a_checklist_keeps_its_lines_and_skips_what_it_holds(tmp_path, newline):
    original = newline.join([
        "---", "name: office-fp", "title: Office FP", "disciplines: FP", "version: 3",
        "author: me", "date: 2025-01-02", "---", "", "# Office FP", "",
        "- FDC signage names the area it serves", "", "A closing note the reviewer wrote.",
    ]) + newline
    path = tmp_path / "office-fp.md"
    path.write_bytes(original.encode("utf-8"))
    target = cs.saved_checklists(tmp_path)[0]
    picked = _checks(("M1.6", "FDC signage names the area it serves."), ("M1.7", PLAN_LINE))

    plan = cs.save_append(target, picked, today=DAY)

    assert [c.id for c in plan.adding] == ["M1.7"]
    assert [(c.id, where) for c, where in plan.skipped] == [("M1.6", "item 1")]
    written = path.read_bytes().decode("utf-8")
    assert written.startswith(original.replace("version: 3", "version: 4")
                              .replace("date: 2025-01-02", "date: 2026-11-14").rstrip())
    assert written.endswith(newline + newline + f"- {PLAN_LINE}" + newline)
    # The file's own line ending, throughout.
    assert written.count("\r\n") == (written.count("\n") if newline == "\r\n" else 0)
    assert P.parse_profile(written).items == ("FDC signage names the area it serves", PLAN_LINE)

    # Saving the same check again finds it in the file and writes nothing.
    with pytest.raises(ValueError):
        cs.save_append(path, picked[1:], today=DAY)
    assert path.read_bytes().decode("utf-8") == written


@pytest.mark.parametrize("raw, prefixes", [
    ("FP, f; FP", ("fp", "f")),
    (["E", " m ", "f-1", "-x", "x" * 17, ""], ("e", "m", "f-1")),
    ("", ()),
])
def test_only_sheet_prefixes_are_kept_as_where_a_checklist_applies(raw, prefixes):
    assert cs.clean_prefixes(raw) == prefixes
