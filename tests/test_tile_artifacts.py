"""Tile-artifact staging + note builders (save_tile_artifacts).

Pure, hermetic unit tests over :mod:`drawing_analyzer.tile_artifacts` — no
PyMuPDF, no client, no network (I-4). Tiles are hand-built ``ImageTile``s with
fake PNG bytes; the builders take constructed ``Finding``s.
"""
from __future__ import annotations

import json
from pathlib import Path

from drawing_analyzer.models import Finding, ImageTile, RenderedSheet, SheetRef
from drawing_analyzer.tile_artifacts import (
    TILE_INDEX_SCHEMA_VERSION,
    TILES_INVENTORY_NAME,
    build_tile_index,
    build_tile_note_markdown,
    build_tiles_root_index,
    findings_for_sheet,
    sheet_tile_dirname,
    stage_rendered_sheet,
)


def _ref(name: str = "M-101.pdf", page: int = 0, source_id: str = "SRC-0001") -> SheetRef:
    return SheetRef(
        pdf_path=Path(name), page_index=page, source_name=name, page_count=3,
        source_id=source_id,
    )


def _tile(row: int, col: int) -> ImageTile:
    return ImageTile(
        png_bytes=b"\x89PNGfake-" + f"r{row}c{col}".encode(),
        width_px=100, height_px=80, kind="tile", row=row, col=col,
        label=f"pos-{row}-{col}",
    )


def _sheet(ref: SheetRef | None = None) -> RenderedSheet:
    return RenderedSheet(
        ref=ref or _ref(),
        overview=ImageTile(
            png_bytes=b"\x89PNGfake-overview", width_px=200, height_px=160,
            kind="overview",
        ),
        # Deliberately unsorted; staging must order by (row, col) (I-7).
        tiles=[_tile(1, 1), _tile(0, 0), _tile(0, 1)],
        page_width_pt=612.0,
        page_height_pt=792.0,
        rows=2,
        cols=2,
        omitted_tiles=[(1, 0)],
    )


def _finding(**kw) -> Finding:
    base = dict(
        sheet_id="M-101", source_name="M-101.pdf", source_id="SRC-0001",
        page_index=0, category="coordination", severity="high",
        text="Duct clashes with beam.", source_quote="24x12 SA duct",
    )
    base.update(kw)
    return Finding(**base)


# --------------------------------------------------------------------------- #
# stage_rendered_sheet
# --------------------------------------------------------------------------- #


def test_sheet_tile_dirname_is_deterministic_and_collision_free():
    assert sheet_tile_dirname(_ref()) == "SRC-0001_p1_m-101"
    assert sheet_tile_dirname(_ref(page=2)) == "SRC-0001_p3_m-101"
    # Two inputs sharing a basename differ by source_id.
    assert sheet_tile_dirname(_ref(source_id="SRC-0002")) != sheet_tile_dirname(_ref())
    # A blank source_id still yields a usable name.
    assert sheet_tile_dirname(_ref(source_id="")).startswith("SRC-0000_p1_")


def test_stage_rendered_sheet_writes_pngs_and_inventory(tmp_path):
    sheet = _sheet()
    written = stage_rendered_sheet(sheet, tmp_path)
    sheet_dir = tmp_path / "SRC-0001_p1_m-101"
    # overview + 3 tiles + tiles.json
    assert written == 5
    assert (sheet_dir / "overview.png").read_bytes() == b"\x89PNGfake-overview"
    # Files are named by the 1-based visible label, not the coarse position hint.
    assert (sheet_dir / "r1c1.png").read_bytes() == b"\x89PNGfake-r0c0"
    assert (sheet_dir / "r2c2.png").read_bytes() == b"\x89PNGfake-r1c1"

    inv = json.loads((sheet_dir / TILES_INVENTORY_NAME).read_text(encoding="utf-8"))
    assert inv["schema_version"] == TILE_INDEX_SCHEMA_VERSION
    assert inv["sheet"] == {
        "source_id": "SRC-0001",
        "source_name": "M-101.pdf",
        "page_index": 0,
        "display_label": "M-101.pdf (page 1/3)",
    }
    assert inv["rows"] == 2 and inv["cols"] == 2
    # Sorted by (row, col) regardless of input order.
    assert [t["tile_label"] for t in inv["tiles"]] == ["r1c1", "r1c2", "r2c2"]
    assert inv["tiles"][0] == {
        "file": "r1c1.png", "tile_label": "r1c1", "row": 0, "col": 0,
        "width_px": 100, "height_px": 80, "position_hint": "pos-0-0",
    }
    assert inv["omitted_tiles"] == [
        {"tile_label": "r2c1", "row": 1, "col": 0, "reason": "blank_suppressed"},
    ]


def test_stage_rendered_sheet_is_idempotent(tmp_path):
    sheet = _sheet()
    stage_rendered_sheet(sheet, tmp_path)
    stage_rendered_sheet(sheet, tmp_path)  # re-stage must not raise or duplicate
    files = sorted(p.name for p in (tmp_path / "SRC-0001_p1_m-101").iterdir())
    assert files == ["overview.png", "r1c1.png", "r1c2.png", "r2c2.png", "tiles.json"]


# --------------------------------------------------------------------------- #
# note builders
# --------------------------------------------------------------------------- #


def _inventory(tmp_path) -> dict:
    stage_rendered_sheet(_sheet(), tmp_path)
    return json.loads(
        (tmp_path / "SRC-0001_p1_m-101" / TILES_INVENTORY_NAME).read_text(
            encoding="utf-8"
        )
    )


def test_findings_for_sheet_joins_on_source_identity(tmp_path):
    inv = _inventory(tmp_path)
    mine = _finding(qc_id="QC-002")
    sheet_level = _finding(text="Missing legend.", source_quote="", qc_id="QC-001")
    other_page = _finding(page_index=1)
    other_source = _finding(source_id="SRC-0009")
    got = findings_for_sheet([mine, sheet_level, other_page, other_source], inv)
    # Only this sheet's findings, ordered by QC number.
    assert got == [sheet_level, mine]


def test_build_tile_index_groups_findings_and_reserves_model_notes(tmp_path):
    inv = _inventory(tmp_path)
    tagged = _finding(tile=[0, 0], qc_id="QC-001")
    sheet_level = _finding(text="Missing legend.", source_quote="", qc_id="QC-002")
    index = build_tile_index(inv, [tagged, sheet_level])
    assert index["schema_version"] == TILE_INDEX_SCHEMA_VERSION
    assert index["reserved"] == {}
    by_label = {t["tile_label"]: t for t in index["tiles"]}
    assert set(by_label) == {"r1c1", "r1c2", "r2c2"}
    # Every tile carries the reserved slot for future model-written notes.
    assert all(t["model_notes"] is None for t in index["tiles"])
    assert [f["qc_id"] for f in by_label["r1c1"]["findings"]] == ["QC-001"]
    assert by_label["r1c2"]["findings"] == []
    assert [f["qc_id"] for f in index["sheet_level_findings"]] == ["QC-002"]
    summary = by_label["r1c1"]["findings"][0]
    assert summary["severity"] == "high" and summary["category"] == "coordination"
    assert summary["verification_status"] == "SKIPPED"


def test_build_tile_note_markdown_with_and_without_findings(tmp_path):
    inv = _inventory(tmp_path)
    tile_entry = inv["tiles"][0]
    f = _finding(tile=[0, 0], qc_id="QC-001", recommended_action="Reroute the duct.")
    md = build_tile_note_markdown(tile_entry, inv, [f])
    assert md.startswith("# Tile r1c1 — M-101.pdf (page 1/3)")
    assert "### QC-001 — high / coordination" in md
    assert "Duct clashes with beam." in md
    assert "> 24x12 SA duct" in md
    assert "Recommended action: Reroute the duct." in md
    assert "Verification: SKIPPED" in md

    empty = build_tile_note_markdown(tile_entry, inv, [])
    assert "No findings were tagged to this tile." in empty


def test_build_tiles_root_index_sorts_by_dir():
    idx = build_tiles_root_index([{"dir": "b"}, {"dir": "a"}])
    assert [e["dir"] for e in idx["sheets"]] == ["a", "b"]
    assert idx["schema_version"] == TILE_INDEX_SCHEMA_VERSION
