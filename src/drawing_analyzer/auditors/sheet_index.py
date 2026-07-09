"""Sheet-index auditor (Phase 14) — zero API.

Many sets carry a drawing index (a "SHEET INDEX" / "LIST OF DRAWINGS" table) that
lists every sheet in the package. When the set changes, the index goes stale: it
lists a sheet that was cut, or omits one that was added. Both are cheap to catch
by diffing the index against the set's own inventory, in both directions.

The auditor finds a sheet whose text carries an index header and enough sheet-ID
entries to be a real list, collects those entries, and compares them with the set
inventory (learned by :mod:`.references`):

* an index entry **not present in the provided set** → a medium finding anchored on
  the entry (worded "provided set", never "does not exist" — a partial package
  legitimately omits sheets);
* a set sheet **not listed in the index** → a low finding anchored on the index
  header (the omission has no row of its own to point at).

PDF-engine-free (I-5): pure over the extracted word tuples.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..models import Anchor, Finding, Verification
from .references import (
    SheetInventory,
    _joined_stream,
    _looks_like_sheet_id,
    _normalize_id,
    _rect_union,
    _words_in_span,
    _wrect,
    _wtext,
    build_inventory,
    detect_sheet_id,
)

# Header phrases that mark a drawing-index / sheet-list block.
_INDEX_HEADERS = (
    "DRAWING INDEX",
    "SHEET INDEX",
    "INDEX OF DRAWINGS",
    "LIST OF DRAWINGS",
    "DRAWING LIST",
    "SHEET LIST",
    "DRAWING SCHEDULE",
    "INDEX OF SHEETS",
)
# A sheet needs at least this many ID-shaped entries (beyond a header) to be read
# as an index — so a general-notes sheet that merely references a few drawings is
# not mistaken for one.
_MIN_INDEX_ENTRIES = 3


@dataclass
class _IndexSheet:
    geom: Any
    display_id: str
    header_rect: list[float] | None
    # normalized entry id -> its first word rect on the index sheet
    entries: dict


def _find_header_rect(words: list[Any]) -> list[float] | None:
    """The union rect of the first index-header phrase on the sheet, or ``None``."""
    if not words:
        return None
    joined, spans = _joined_stream(words)
    upper = joined.upper()
    best: tuple[int, int] | None = None
    for header in _INDEX_HEADERS:
        pos = upper.find(header)
        if pos != -1 and (best is None or pos < best[0]):
            best = (pos, pos + len(header))
    if best is None:
        return None
    idxs = _words_in_span(spans, best[0], best[1])
    if not idxs:
        return None
    return _rect_union([_wrect(words[i]) for i in idxs])


def _as_index_sheet(geom: Any, inventory: SheetInventory) -> _IndexSheet | None:
    """Read ``geom`` as a drawing-index sheet, or ``None`` if it isn't one."""
    words = list(getattr(geom, "words", []) or [])
    header_rect = _find_header_rect(words)
    if header_rect is None:
        return None
    own_id = detect_sheet_id(geom) or ""
    entries: dict[str, list[float]] = {}
    for w in words:
        raw = _wtext(w)
        if not _looks_like_sheet_id(raw):
            continue
        tok = _normalize_id(raw)
        if not inventory.matches_grammar(tok):
            continue
        entries.setdefault(tok, list(_wrect(w)))
    if len(entries) < _MIN_INDEX_ENTRIES:
        return None
    ref = geom.ref
    return _IndexSheet(
        geom=geom,
        display_id=own_id or f"{Path(ref.source_name).stem}-p{ref.page_index + 1}",
        header_rect=header_rect,
        entries=entries,
    )


def audit_sheet_index(rendered_sheets: Iterable[Any]) -> list[Finding]:
    """Diff the set's drawing index against the set inventory, both directions.

    Returns ``DETERMINISTIC`` reference findings. Empty when the set has no
    detectable index sheet. Side-effect-free.

    A set's index legitimately spans **several sheets** — a multi-page index or
    per-discipline cover sheets. Direction 1 (a listed entry not in the set) is
    checked per index sheet and anchored on the entry where it appears. Direction 2
    (a set sheet the index omits) is checked against the **union** of every detected
    index sheet's entries, so a sheet listed on *another* index page is not falsely
    reported as missing here; omissions are reported once, anchored on the first
    index sheet's header.
    """
    sheets = list(rendered_sheets)
    inventory = build_inventory(sheets)
    if not inventory.ids:
        return []

    index_sheets = [
        idx for idx in (_as_index_sheet(g, inventory) for g in sheets) if idx is not None
    ]
    if not index_sheets:
        return []

    findings: list[Finding] = []

    # Direction 1: entries listed in an index but not present in the set — checked
    # per index sheet, anchored on the entry's own words.
    for index in index_sheets:
        ref = index.geom.ref
        for entry, rect in sorted(index.entries.items()):
            if entry in inventory.ids:
                continue
            findings.append(Finding(
                sheet_id=index.display_id,
                source_name=ref.source_name,
                page_index=ref.page_index,
                category="reference",
                severity="medium",
                text=(
                    f"The drawing index lists {entry}, which is not present in the "
                    f"provided set."
                ),
                source_quote=entry,
                refs=[],
                anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="sheet_index_entry"),
                verification=Verification(
                    status="DETERMINISTIC",
                    note="index entry not present in the provided set",
                ),
            ))

    # Direction 2: set sheets listed in NO index page (union across all of them),
    # reported once and anchored on the first index sheet's header.
    all_listed: set[str] = set()
    for index in index_sheets:
        all_listed |= set(index.entries.keys())
    primary = index_sheets[0]
    pref = primary.geom.ref
    anchor = (
        Anchor(status="EXACT", rect_pdf=list(primary.header_rect), method="sheet_index_header")
        if primary.header_rect is not None
        else Anchor(status="UNANCHORED", method="sheet_index_header")
    )
    for sid in sorted(inventory.ids):
        if sid in all_listed:
            continue
        findings.append(Finding(
            sheet_id=primary.display_id,
            source_name=pref.source_name,
            page_index=pref.page_index,
            category="reference",
            severity="low",
            text=(
                f"Sheet {sid} is present in the set but not listed in the drawing index."
            ),
            source_quote="",
            refs=[],
            anchor=anchor,
            verification=Verification(
                status="DETERMINISTIC",
                note="set sheet missing from the drawing index",
            ),
        ))
    return findings
