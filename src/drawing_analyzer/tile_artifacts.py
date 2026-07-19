"""Opt-in tile artifact dump: staged tile PNGs + mirrored per-tile notes.

When ``save_tile_artifacts`` is on, the pipeline stages every rendered image
(the sheet overview + each grid tile) into ``<qc_work_dir>/tiles/<sheet>/`` at
render time — the only moment the PNG bytes exist (the batch path discards each
:class:`~drawing_analyzer.models.RenderedSheet` after upload, and the level-1
digest cache skips rendering entirely on warm runs, which the pipeline bypasses
for these runs). At export time :func:`drawing_analyzer.export.write_tile_artifacts`
copies the staged tree into the export's ``tiles/`` folder and adds the notes —
a *mirror* of existing output (the sheet digest prose, the sheet's final ledger
findings, and a per-tile sidecar listing the findings tagged to that tile).
No model call produces per-tile prose today; ``tile_index.json`` reserves a
``model_notes`` slot per tile so a future contract change can fill it in
without reshaping the folder.

This module is PyMuPDF-free (I-5): staging writes bytes the renderer already
produced. Staging failures are the caller's to absorb (I-3 — the pipeline wraps
the sink so a failed save never aborts the digest), and a run aborted mid-set
legitimately leaves a partially staged tree; the export copies what exists.
All output is deterministically ordered (I-7).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Finding, RenderedSheet, SheetRef, source_page_key
from .tiling import tile_label_for

TILES_DIRNAME = "tiles"
TILES_INVENTORY_NAME = "tiles.json"
TILE_INDEX_SCHEMA_VERSION = 1

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text: str, *, max_len: int = 40) -> str:
    """A conservative filesystem-safe slug for a display stem (never empty)."""
    out = _SLUG_RE.sub("-", (text or "").strip()).strip("-.")
    return (out[:max_len] or "sheet").lower()


def sheet_tile_dirname(ref: SheetRef) -> str:
    """Deterministic, collision-free directory name for one sheet's tiles.

    ``source_id`` + page make the name unique per accepted input (DA-001); the
    slugged stem is display sugar only. The export copy re-sanitizes every
    component, so this need only be deterministic, not adversarially safe.
    """
    sid = (ref.source_id or "").strip() or "SRC-0000"
    return f"{sid}_p{ref.page_index + 1}_{_slug(Path(ref.source_name).stem)}"


def stage_rendered_sheet(rendered: RenderedSheet, tiles_root: Path) -> int:
    """Write one sheet's overview + tile PNGs and its inventory; return file count.

    Layout: ``tiles_root/<sheet_tile_dirname>/{overview.png, r1c1.png, …,
    tiles.json}``. ``tiles.json`` carries the sheet identity (``source_id`` /
    ``page_index``) so the export-time notes writer joins on it and never parses
    directory names. Tiles are written and listed sorted by ``(row, col)`` (I-7).
    """
    sheet_dir = tiles_root / sheet_tile_dirname(rendered.ref)
    sheet_dir.mkdir(parents=True, exist_ok=True)
    written = 0

    (sheet_dir / "overview.png").write_bytes(rendered.overview.png_bytes)
    written += 1

    tile_entries: list[dict] = []
    for tile in sorted(rendered.tiles, key=lambda t: (t.row, t.col)):
        label = tile_label_for(tile.row, tile.col)
        (sheet_dir / f"{label}.png").write_bytes(tile.png_bytes)
        written += 1
        tile_entries.append({
            "file": f"{label}.png",
            "tile_label": label,
            "row": tile.row,
            "col": tile.col,
            "width_px": tile.width_px,
            "height_px": tile.height_px,
            "position_hint": tile.label,
        })

    inventory = {
        "schema_version": TILE_INDEX_SCHEMA_VERSION,
        "sheet": {
            "source_id": rendered.ref.source_id,
            "source_name": rendered.ref.source_name,
            "page_index": rendered.ref.page_index,
            "display_label": rendered.ref.display_label,
        },
        "rows": rendered.rows,
        "cols": rendered.cols,
        "overlap_frac": rendered.overlap_frac,
        "is_raster": rendered.is_raster,
        "overview": {
            "file": "overview.png",
            "width_px": rendered.overview.width_px,
            "height_px": rendered.overview.height_px,
        },
        "tiles": tile_entries,
        "omitted_tiles": [
            {
                "tile_label": tile_label_for(row, col),
                "row": row,
                "col": col,
                "reason": "blank_suppressed",
            }
            for row, col in sorted(rendered.omitted_tiles or [])
        ],
    }
    (sheet_dir / TILES_INVENTORY_NAME).write_text(
        json.dumps(inventory, indent=2), encoding="utf-8"
    )
    written += 1
    return written


# ---------------------------------------------------------------------------
# Export-time pure builders (consumed by export.write_tile_artifacts). These
# take the staged inventory + the sheet's final ledger findings and produce the
# notes payloads; they touch no filesystem and place no calls.
# ---------------------------------------------------------------------------


def _finding_sort_key(f: Finding) -> tuple[str, str]:
    # Numbered findings first in QC order; unnumbered ones after, by stable id.
    return (f.qc_id or "~", f.id)


def findings_for_sheet(findings: list[Finding], inventory: dict) -> list[Finding]:
    """The findings belonging to the staged sheet, via the collision-safe key."""
    sheet = inventory.get("sheet") or {}
    want = (
        (sheet.get("source_id") or "").strip() or (sheet.get("source_name") or ""),
        int(sheet.get("page_index", -1)),
    )
    out = [f for f in findings if source_page_key(f) == want]
    out.sort(key=_finding_sort_key)
    return out


def _finding_summary(f: Finding) -> dict:
    return {
        "qc_id": f.qc_id,
        "id": f.id,
        "severity": f.severity,
        "category": f.category,
        "verification_status": f.verification.status,
    }


def build_tile_index(inventory: dict, sheet_findings: list[Finding]) -> dict:
    """The canonical per-sheet machine record (``tile_index.json``).

    Merges the render-time inventory with the sheet's final ledger findings:
    each tile lists the findings tagged to it (by zero-based ``[row, col]``) and
    carries the reserved ``model_notes`` slot for future model-written per-tile
    notes; findings with no tile appear under ``sheet_level_findings``.
    """
    by_tile: dict[tuple[int, int], list[Finding]] = {}
    sheet_level: list[Finding] = []
    for f in sheet_findings:
        if f.tile is not None and len(f.tile) == 2:
            by_tile.setdefault((int(f.tile[0]), int(f.tile[1])), []).append(f)
        else:
            sheet_level.append(f)

    tiles = []
    for entry in inventory.get("tiles") or []:
        pos = (int(entry.get("row", -1)), int(entry.get("col", -1)))
        tiles.append({
            "file": entry.get("file", ""),
            "tile_label": entry.get("tile_label", ""),
            "row": pos[0],
            "col": pos[1],
            "findings": [_finding_summary(f) for f in by_tile.get(pos, [])],
            "model_notes": None,
        })

    return {
        "schema_version": TILE_INDEX_SCHEMA_VERSION,
        "sheet": dict(inventory.get("sheet") or {}),
        "rows": inventory.get("rows"),
        "cols": inventory.get("cols"),
        "overview": dict(inventory.get("overview") or {}),
        "tiles": tiles,
        "omitted_tiles": list(inventory.get("omitted_tiles") or []),
        "sheet_level_findings": [_finding_summary(f) for f in sheet_level],
        "reserved": {},
    }


def _finding_note_lines(f: Finding) -> list[str]:
    head = f.qc_id or f.id[:12]
    lines = [f"### {head} — {f.severity} / {f.category}", "", f.text.strip()]
    if f.source_quote:
        lines += ["", f"> {f.source_quote.strip()}"]
    if f.recommended_action:
        lines += ["", f"Recommended action: {f.recommended_action.strip()}"]
    status_bits = [f"Verification: {f.verification.status}"]
    if f.verification.note:
        status_bits.append(f.verification.note.strip())
    if f.citation is not None:
        status_bits.append(f"Citation: {f.citation.status}")
    if f.sources:
        status_bits.append(f"Sources: {'+'.join(f.sources)}")
    lines += ["", " | ".join(status_bits)]
    return lines


def build_tile_note_markdown(
    tile_entry: dict, inventory: dict, findings: list[Finding]
) -> str:
    """The human per-tile sidecar (``rNcN.md``) — findings tagged to this tile."""
    sheet = inventory.get("sheet") or {}
    label = tile_entry.get("tile_label", "")
    lines = [
        f"# Tile {label} — {sheet.get('display_label', sheet.get('source_name', ''))}",
        "",
        f"Position: {tile_entry.get('position_hint') or 'n/a'}",
        f"Image: {tile_entry.get('file', '')}",
        "",
    ]
    if not findings:
        lines.append("No findings were tagged to this tile.")
    else:
        for f in sorted(findings, key=_finding_sort_key):
            lines.extend(_finding_note_lines(f))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_tiles_root_index(sheet_entries: list[dict]) -> dict:
    """The top-level ``tiles/index.json`` over every exported sheet folder."""
    return {
        "schema_version": TILE_INDEX_SCHEMA_VERSION,
        "sheets": sorted(sheet_entries, key=lambda e: e.get("dir", "")),
    }
