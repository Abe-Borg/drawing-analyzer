"""Render telemetry: per-sheet image count, PNG byte spread, long edge.

The numbers exist to make two levers measurable instead of guessed — the
near-blank suppression byte threshold (``DRAWING_ANALYZER_NEAR_BLANK_MAX_BYTES``,
default 3072, chosen without data) and any change to the render target. Nothing
logged tile byte sizes before this: the render path logged only the suppressed
count, and byte sizes appeared solely on Files-API retry paths.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from drawing_analyzer.models import ImageTile, RenderedSheet, RenderTelemetry, SheetRef


def _sheet(
    tmp_path: Path,
    *,
    tile_bytes: list[int],
    omitted: list[tuple[int, int]] | None = None,
    is_raster: bool = False,
) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=tmp_path / "set.pdf",
        source_name="set.pdf",
        page_index=0,
        page_count=1,
        source_id="SRC-0001",
    )
    return RenderedSheet(
        ref=ref,
        overview=ImageTile(b"o" * 500, 1560, 1205, "overview"),
        tiles=[
            ImageTile(b"t" * n, 1205, 1560, "tile", row=i, col=0, label=f"r{i}")
            for i, n in enumerate(tile_bytes)
        ],
        page_width_pt=2448.0,
        page_height_pt=3168.0,
        rows=len(tile_bytes),
        cols=1,
        is_raster=is_raster,
        omitted_tiles=list(omitted or []),
    )


def test_telemetry_counts_sent_images_and_total_bytes(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path, tile_bytes=[1000, 2000, 3000])
    t = sheet.render_telemetry()

    assert t.images_sent == 4                       # 1 overview + 3 tiles
    assert t.overview_png_bytes == 500
    assert t.tile_png_bytes == [1000, 2000, 3000]   # grid order, not sorted
    assert t.png_bytes_total == 500 + 6000
    assert t.max_long_edge_px == 1560
    assert t.is_raster is False


def test_suppressed_tiles_are_absent_from_the_byte_list_not_zero(tmp_path: Path) -> None:
    """A pixel-uniform tile has NO byte size — it never reaches ``tobytes("png")``.

    Recording it as zero would drag the distribution down exactly where a
    near-blank threshold gets read off it, which is the whole point of the
    measurement. It is reported only as a count.
    """
    sheet = _sheet(tmp_path, tile_bytes=[4000, 5000], omitted=[(0, 1), (1, 1), (2, 1)])
    t = sheet.render_telemetry()

    assert t.tiles_omitted == 3
    assert t.tile_png_bytes == [4000, 5000]
    assert 0 not in t.tile_png_bytes
    # Sent-image count covers only what was actually sent.
    assert t.images_sent == 3


def test_byte_spread_is_min_median_max(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path, tile_bytes=[100, 900, 200, 50_000, 300])
    assert sheet.render_telemetry().tile_byte_spread == (100, 300, 50_000)


def test_byte_spread_uses_median_not_mean(tmp_path: Path) -> None:
    """The distribution is right-skewed; a mean would sit above nearly every tile.

    One dense schedule tile among mostly-empty plan tiles is the normal shape of
    a drawing sheet, and a threshold read off a mean would suppress almost
    everything.
    """
    sheet = _sheet(tmp_path, tile_bytes=[100, 120, 140, 160, 1_000_000])
    spread = sheet.render_telemetry().tile_byte_spread
    assert spread is not None
    _lo, median, _hi = spread
    mean = (100 + 120 + 140 + 160 + 1_000_000) / 5
    assert median == 140
    assert median < mean


def test_byte_spread_is_none_when_every_tile_was_suppressed(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path, tile_bytes=[], omitted=[(0, 0), (0, 1)])
    t = sheet.render_telemetry()
    assert t.tile_byte_spread is None
    assert t.to_dict()["tile_bytes_median"] is None
    assert t.images_sent == 1  # the overview is never suppressed


def test_to_dict_is_journal_shaped_and_omits_the_per_tile_list(tmp_path: Path) -> None:
    sheet = _sheet(tmp_path, tile_bytes=[10, 20, 30], is_raster=True)
    d = sheet.render_telemetry().to_dict()

    assert d["layer"] == "raster"
    assert d["images_sent"] == 4
    assert d["png_bytes_total"] == 560
    assert d["tile_bytes_min"] == 10 and d["tile_bytes_max"] == 30
    # The full list stays on the object for a caller building a real histogram,
    # but must not widen the journal line.
    assert "tile_png_bytes" not in d
    assert all(isinstance(v, (int, str, type(None))) for v in d.values())


def test_telemetry_is_pure_data_and_holds_no_images(tmp_path: Path) -> None:
    """Safe to journal and aggregate: it must not retain the PNG bytes."""
    sheet = _sheet(tmp_path, tile_bytes=[10, 20])
    t = sheet.render_telemetry()
    assert isinstance(t, RenderTelemetry)
    with pytest.raises(Exception):
        t.png_bytes_total = 1  # frozen dataclass


# --------------------------------------------------------------------------- #
# Emission through the render stream
# --------------------------------------------------------------------------- #


class _RecordingJournal:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def emit(self, code: str, **fields):  # noqa: ANN003
        self.events.append((code, fields))


class _ExplodingJournal:
    def emit(self, code: str, **fields):  # noqa: ANN003
        raise RuntimeError("journal is down")


def _stream(monkeypatch, sheets, journal):
    """Drive ``_rendered_stream`` over canned sheets (no PyMuPDF, no I/O)."""
    from drawing_analyzer import pipeline

    monkeypatch.setattr(
        pipeline, "iter_rendered_sheets", lambda *a, **k: iter(sheets)
    )
    return list(
        pipeline._rendered_stream(
            [], rows=1, cols=1, overlap_frac=0.08,
            geometry_sink=None, journal=journal,
        )
    )


def test_render_stream_emits_one_event_per_sheet(tmp_path: Path, monkeypatch) -> None:
    sheets = [
        _sheet(tmp_path, tile_bytes=[1000, 2000]),
        _sheet(tmp_path, tile_bytes=[7000], omitted=[(0, 1)]),
    ]
    journal = _RecordingJournal()
    out = _stream(monkeypatch, sheets, journal)

    assert len(out) == 2  # the stream still yields every sheet
    codes = [c for c, _ in journal.events]
    assert codes == ["SHEET_RENDERED", "SHEET_RENDERED"]
    first = journal.events[0][1]
    assert first["sheet"] == "set.pdf (page 1/1)"
    assert first["png_bytes_total"] == 3500
    assert journal.events[1][1]["tiles_omitted"] == 1


def test_render_stream_survives_a_failing_journal(tmp_path: Path, monkeypatch) -> None:
    """Telemetry is observability — it must never sink a render (I-3)."""
    sheets = [_sheet(tmp_path, tile_bytes=[100])]
    out = _stream(monkeypatch, sheets, _ExplodingJournal())
    assert len(out) == 1
    assert out[0].tiles[0].png_bytes == b"t" * 100


def test_render_stream_without_a_journal_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    sheets = [_sheet(tmp_path, tile_bytes=[100, 200])]
    out = _stream(monkeypatch, sheets, None)
    assert len(out) == 1
