"""Ephemeral, exact-byte handoff of rendered sheets between pipeline stages.

The digest and critique stages intentionally show the model the same overview,
tiles, text layer, and geometry.  Historically the digest discarded those PNGs
before the critique began, forcing a second PDF extraction/rasterization pass.
This module keeps the handoff bounded in memory by spooling the already-compressed
PNG bytes to a private temporary directory.  Loading reconstructs the same
``RenderedSheet`` byte-for-byte; no image is resized, recompressed, or filtered.

This is a run-local performance cache, not a durable analysis cache.  A failed
spool write simply leaves the key absent so the caller can render normally.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Hashable

from .models import ImageTile, RenderedSheet


@dataclass(frozen=True)
class _TileRecord:
    path: Path
    width_px: int
    height_px: int
    kind: str
    row: int
    col: int
    label: str

    @classmethod
    def write(cls, tile: ImageTile, path: Path) -> "_TileRecord":
        path.write_bytes(tile.png_bytes)
        return cls(
            path=path,
            width_px=int(tile.width_px),
            height_px=int(tile.height_px),
            kind=str(tile.kind),
            row=int(tile.row),
            col=int(tile.col),
            label=str(tile.label),
        )

    def load(self) -> ImageTile:
        return ImageTile(
            png_bytes=self.path.read_bytes(),
            width_px=self.width_px,
            height_px=self.height_px,
            kind=self.kind,
            row=self.row,
            col=self.col,
            label=self.label,
        )


@dataclass(frozen=True)
class _SheetRecord:
    ref: Any
    overview: _TileRecord
    tiles: tuple[_TileRecord, ...]
    page_width_pt: float
    page_height_pt: float
    rows: int
    cols: int
    sheet_text: str
    words: tuple[Any, ...]
    is_raster: bool
    omitted_tiles: tuple[tuple[int, int], ...]
    overlap_frac: float
    geometry: Any
    directory: Path

    def load(self) -> RenderedSheet:
        return RenderedSheet(
            ref=self.ref,
            overview=self.overview.load(),
            tiles=[record.load() for record in self.tiles],
            page_width_pt=self.page_width_pt,
            page_height_pt=self.page_height_pt,
            rows=self.rows,
            cols=self.cols,
            sheet_text=self.sheet_text,
            words=list(self.words),
            is_raster=self.is_raster,
            omitted_tiles=list(self.omitted_tiles),
            overlap_frac=self.overlap_frac,
            geometry=self.geometry,
        )


class RenderedSheetSpool:
    """Private run-local store for exact rendered-sheet assets.

    ``put`` and ``pop`` are thread-safe.  ``pop`` removes the on-disk entry only
    after every PNG has been read successfully; on a read failure it returns
    ``None`` and removes the broken entry so the caller can safely re-render.
    ``close`` is idempotent and recursively removes only the private directory
    created by this instance.
    """

    def __init__(self, *, parent: Path | None = None) -> None:
        base = str(parent) if parent is not None else None
        self._root = Path(tempfile.mkdtemp(prefix="drawing_render_reuse_", dir=base))
        self._records: dict[Hashable, _SheetRecord] = {}
        self._counter = 0
        self._closed = False
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._records

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def keys(self) -> set[Hashable]:
        with self._lock:
            return set(self._records)

    def put(self, key: Hashable, sheet: RenderedSheet) -> bool:
        """Store ``sheet`` under ``key``; return ``False`` on local I/O failure."""
        with self._lock:
            if self._closed:
                return False
            self._counter += 1
            directory = self._root / f"sheet_{self._counter:06d}"
            try:
                directory.mkdir(parents=False, exist_ok=False)
                overview = _TileRecord.write(sheet.overview, directory / "overview.png")
                tiles = tuple(
                    _TileRecord.write(tile, directory / f"tile_{i:03d}.png")
                    for i, tile in enumerate(sheet.tiles)
                )
                record = _SheetRecord(
                    ref=sheet.ref,
                    overview=overview,
                    tiles=tiles,
                    page_width_pt=float(sheet.page_width_pt),
                    page_height_pt=float(sheet.page_height_pt),
                    rows=int(sheet.rows),
                    cols=int(sheet.cols),
                    sheet_text=str(sheet.sheet_text),
                    words=tuple(sheet.words),
                    is_raster=bool(sheet.is_raster),
                    omitted_tiles=tuple(tuple(v) for v in sheet.omitted_tiles),
                    overlap_frac=float(sheet.overlap_frac),
                    geometry=sheet.geometry,
                    directory=directory,
                )
            except OSError:
                shutil.rmtree(directory, ignore_errors=True)
                return False

            previous = self._records.pop(key, None)
            self._records[key] = record
            if previous is not None:
                shutil.rmtree(previous.directory, ignore_errors=True)
            return True

    def pop(self, key: Hashable) -> RenderedSheet | None:
        """Load and consume one sheet, returning ``None`` if absent or damaged."""
        with self._lock:
            record = self._records.pop(key, None)
            if record is None:
                return None
            try:
                sheet = record.load()
            except OSError:
                sheet = None
            shutil.rmtree(record.directory, ignore_errors=True)
            return sheet

    def discard(self, key: Hashable) -> None:
        with self._lock:
            record = self._records.pop(key, None)
            if record is not None:
                shutil.rmtree(record.directory, ignore_errors=True)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._records.clear()
            shutil.rmtree(self._root, ignore_errors=True)

    def __enter__(self) -> "RenderedSheetSpool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - defensive process-exit cleanup
        try:
            self.close()
        except Exception:
            pass
