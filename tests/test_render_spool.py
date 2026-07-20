from __future__ import annotations

from pathlib import Path

from drawing_analyzer.models import ImageTile, PageGeometry, RenderedSheet, SheetRef
from drawing_analyzer.render_spool import RenderedSheetSpool


def _sheet(tmp_path: Path) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=tmp_path / "set.pdf",
        source_name="set.pdf",
        page_index=2,
        page_count=3,
        source_id="SRC-0007",
    )
    return RenderedSheet(
        ref=ref,
        overview=ImageTile(b"overview-png", 120, 80, "overview"),
        tiles=[
            ImageTile(b"tile-one", 64, 64, "tile", row=0, col=0, label="upper left"),
            ImageTile(b"tile-two", 63, 62, "tile", row=0, col=1, label="upper right"),
        ],
        page_width_pt=612.0,
        page_height_pt=792.0,
        rows=1,
        cols=2,
        sheet_text="EXACT TEXT LAYER",
        words=[(1.0, 2.0, 3.0, 4.0, "EXACT", 0, 0, 0)],
        is_raster=False,
        omitted_tiles=[(1, 0)],
        overlap_frac=0.125,
        geometry=PageGeometry(view_width_pt=612.0, view_height_pt=792.0),
    )


def test_round_trip_preserves_exact_images_and_metadata(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path)
    spool = RenderedSheetSpool(parent=tmp_path)
    root = spool.root

    assert spool.put(("source", 2), sheet)
    restored = spool.pop(("source", 2))

    assert restored is not None
    assert restored.ref is sheet.ref
    assert restored.overview.png_bytes == sheet.overview.png_bytes
    assert [tile.png_bytes for tile in restored.tiles] == [b"tile-one", b"tile-two"]
    assert restored.image_sizes == sheet.image_sizes
    assert restored.sheet_text == sheet.sheet_text
    assert restored.words == sheet.words
    assert restored.omitted_tiles == sheet.omitted_tiles
    assert restored.geometry == sheet.geometry
    assert ("source", 2) not in spool
    spool.close()
    assert not root.exists()


def test_replacement_and_close_remove_private_files(tmp_path: Path) -> None:
    spool = RenderedSheetSpool(parent=tmp_path)
    root = spool.root
    assert spool.put("same", _sheet(tmp_path))
    first_dirs = list(root.iterdir())
    assert len(first_dirs) == 1

    replacement = _sheet(tmp_path)
    replacement.overview.png_bytes = b"replacement"
    assert spool.put("same", replacement)
    assert not first_dirs[0].exists()
    assert len(spool) == 1

    spool.close()
    spool.close()
    assert not root.exists()


def test_missing_key_is_a_clean_cache_miss(tmp_path: Path) -> None:
    with RenderedSheetSpool(parent=tmp_path) as spool:
        assert spool.pop("absent") is None
