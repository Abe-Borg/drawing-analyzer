"""AHJ Atlas Input: an Excel workbook of adopted code editions → governing editions.

The loader has no fixed template, so these build each recognized layout and
check that it yields the editions the pipeline's ``governing_editions`` will
apply — normalized to the designations the identity stage detects — and that a
workbook it cannot read is a captured error, never an exception (I-3).
"""
from __future__ import annotations

import pytest

from drawing_analyzer.ahj_atlas import entries_for, load_ahj_atlas
from drawing_analyzer.models import apply_governing_editions, parse_governing_editions

openpyxl = pytest.importorskip("openpyxl")


def _book(path, sheets: dict[str, list[list]]):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
    wb.save(path)
    return path


def _codes(jurisdiction) -> list[tuple[str, str]]:
    return [(c.code, c.edition) for c in jurisdiction.codes]


LONG = {"Adoptions": [
    ["AHJ Atlas — adopted codes"],
    [],
    ["Jurisdiction", "Code Type", "Adopted Code", "Edition", "Amendments"],
    ["Loudoun County, VA", "Building", "International Building Code (IBC)", 2021, "VA USBC (state)"],
    [None, "Fire", "International Fire Code", "2021 Edition", ""],
    [None, "Sprinkler", "nfpa-13", 2022, ""],
    ["Maricopa County, AZ", "Building", "IBC", 2024, ""],
    [None, "Sprinkler", "NFPA 13", 2025, ""],
]}
WIDE = {"Atlas": [
    ["AHJ", "IBC", "IFC", "NFPA 13", "NFPA 72", "Notes"],
    ["Maricopa County, AZ", 2024, "2024 w/ local amendments", 2025, 2025, "row note"],
    ["Loudoun County, VA", 2021, 2021, 2022, 2022, ""],
]}
TABS = {
    "Loudoun County, VA": [["Code", "Edition"], ["IBC", 2021], ["NFPA 13", 2022]],
    "Maricopa County, AZ": [["Code", "Edition"], ["IBC", 2024], ["NFPA 13", 2025]],
}
FREE = {"Notes": [["Project codes: NFPA 13 2025", None], [None, "2024 IBC"], ["Updated 2025", "misc"]]}


@pytest.mark.parametrize("sheets, expected", [
    (LONG, {"Loudoun County, VA": [("IBC", "2021"), ("IFC", "2021"), ("NFPA 13", "2022")],
            "Maricopa County, AZ": [("IBC", "2024"), ("NFPA 13", "2025")]}),
    (WIDE, {"Loudoun County, VA": [("IBC", "2021"), ("IFC", "2021"), ("NFPA 13", "2022"),
                                   ("NFPA 72", "2022")],
            "Maricopa County, AZ": [("IBC", "2024"), ("IFC", "2024"), ("NFPA 13", "2025"),
                                    ("NFPA 72", "2025")]}),
    (TABS, {"Loudoun County, VA": [("IBC", "2021"), ("NFPA 13", "2022")],
            "Maricopa County, AZ": [("IBC", "2024"), ("NFPA 13", "2025")]}),
    # Free text: only cells naming a known code WITH a year; "Updated 2025" is
    # not a code.
    (FREE, {"": [("IBC", "2024"), ("NFPA 13", "2025")]}),
], ids=["long", "wide", "one-tab-per-ahj", "free-text"])
def test_each_layout_yields_every_jurisdictions_editions(tmp_path, sheets, expected):
    atlas = load_ahj_atlas(_book(tmp_path / "atlas.xlsx", sheets))
    assert atlas.ok, atlas.error
    assert {j.name: _codes(j) for j in atlas.jurisdictions} == expected


def test_amendments_ride_as_the_editions_note_and_reach_the_identity(tmp_path):
    atlas = load_ahj_atlas(_book(tmp_path / "atlas.xlsx", LONG))
    loudoun = next(j for j in atlas.jurisdictions if j.name.startswith("Loudoun"))
    codes, rejected = parse_governing_editions(entries_for([loudoun]))
    assert rejected == ()
    ibc = next(c for c in codes if c.code == "IBC")
    # The parenthesized amendment survives the round trip through the entry
    # string without ending the note early.
    assert "VA USBC" in ibc.amendment_note and "state" in ibc.amendment_note
    identity = apply_governing_editions(None, codes)
    assert {(c.code, c.edition) for c in identity.adopted_codes} == set(_codes(loudoun))


def test_a_wide_rows_note_column_is_not_stamped_on_every_code(tmp_path):
    atlas = load_ahj_atlas(_book(tmp_path / "atlas.xlsx", WIDE))
    maricopa = next(j for j in atlas.jurisdictions if j.name.startswith("Maricopa"))
    notes = {c.code: c.amendment_note for c in maricopa.codes}
    assert notes["IFC"] == "w/ local amendments"
    assert notes["IBC"] == ""


def test_a_code_with_no_year_is_skipped_with_a_warning(tmp_path):
    sheets = {"A": [["Code", "Edition"], ["IBC", 2024], ["NFPA 72", None]]}
    atlas = load_ahj_atlas(_book(tmp_path / "atlas.xlsx", sheets))
    (only,) = atlas.jurisdictions
    assert _codes(only) == [("IBC", "2024")]
    assert any("NFPA 72" in w for w in atlas.warnings)


def test_a_csv_atlas_reads_like_a_workbook(tmp_path):
    path = tmp_path / "atlas.csv"
    path.write_text("Code,Edition\nNFPA 13,2025\nInternational Fire Code,2024\n", encoding="utf-8")
    atlas = load_ahj_atlas(path)
    assert [_codes(j) for j in atlas.jurisdictions] == [[("IFC", "2024"), ("NFPA 13", "2025")]]


@pytest.mark.parametrize("name, content, needle", [
    ("atlas.xls", b"\xd0\xcf\x11\xe0", "Unsupported file type"),
    ("atlas.xlsx", b"not a zip", "Could not read"),
    ("atlas.csv", b"Owner,Phone\nACME,555-0100\n", "No code editions"),
])
def test_an_unreadable_atlas_is_a_captured_error(tmp_path, name, content, needle):
    path = tmp_path / name
    path.write_bytes(content)
    atlas = load_ahj_atlas(path)
    assert not atlas.ok
    assert needle in atlas.error
    assert atlas.jurisdictions == []
