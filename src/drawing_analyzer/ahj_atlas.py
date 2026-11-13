"""Read an AHJ Atlas spreadsheet into the governing code editions for a run.

The *AHJ Atlas Input* is an Excel workbook (``.xlsx`` / ``.xlsm``; ``.csv``
also reads) recording which code editions an Authority Having Jurisdiction has
adopted. Its editions replace the ones detected on the drawings for every code
it names — exactly what the old typed "Governing code editions" field did
(:func:`drawing_analyzer.models.parse_governing_editions` /
:func:`~drawing_analyzer.models.apply_governing_editions`). The loader only
turns the workbook into those entries; the pipeline contract is unchanged.

There is no fixed template, so three layouts are recognized, per worksheet:

* **Long** — a header row with an edition column (``Edition`` / ``Year`` /
  ``Version`` / ``Adopted``) and a column of code names, one code per row::

      Jurisdiction | Code                             | Edition | Amendments
      Loudoun Co.  | International Building Code (IBC) | 2021    | VA USBC
                   | NFPA 13                          | 2022    |

  Optional ``Jurisdiction``/``AHJ``/``City``/``County`` and
  ``Amendments``/``Notes`` columns are honored; a blank jurisdiction cell
  continues the one above (merged cells read that way).

* **Wide** — one row per jurisdiction, one column per code, editions in the
  cells::

      AHJ          | IBC  | IFC  | NFPA 13 | NFPA 72
      Loudoun Co.  | 2021 | 2021 | 2022    | 2022

* **Free text** — no recognizable header: any cell that names a known code
  with a year ("NFPA 13 2025", "2024 IBC") is taken.

Code names are normalized to their usual designation ("International Building
Code" → ``IBC``) so they line up with the editions the identity stage detects.
A workbook that covers several jurisdictions returns each separately; the
caller picks one. Pure and zero-API (no PyMuPDF, no network); every failure is
captured on the result, never raised (I-3).
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import AdoptedCode, parse_governing_editions

ATLAS_FILE_EXTENSIONS = frozenset({".xlsx", ".xlsm", ".csv"})

# Bounds on what is read: an atlas is a small table, and a workbook that is
# not one should fail fast instead of being walked cell by cell.
_MAX_ROWS = 20_000
_MAX_COLS = 60
_HEADER_SCAN_ROWS = 25
_MAX_NOTE_CHARS = 160

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# Code designations, most specific first. Case-insensitive: an atlas is typed
# by people, and "nfpa 13" in a code column means NFPA 13.
_DESIGNATION_RE = re.compile(
    r"\b("
    r"NFPA[ -]?\d{1,4}[A-Z]?"
    r"|ASCE[ -]?\d{1,2}"
    r"|ASHRAE[ -]?\d{1,3}(?:\.\d{1,2})?"
    r"|ASME[ -]?[A-Z]\d{1,3}(?:\.\d{1,3})*"
    r"|ICC[ -]?A117\.1"
    r"|ANSI[ -]?A117\.1"
    r"|UL[ -]?\d{2,5}[A-Z]?"
    r"|FM[ -]?\d{4}"
    r"|IBC|IFC|IMC|IPC|IFGC|IECC|IEBC|IRC|IPMC|IWUIC|ISPSC|IGCC|IPSDC|IZC"
    r"|NEC|UPC|UMC|USBC|SFPC"
    r"|CBC|CFC|CMC|CPC|CEC|CALGREEN|CGBSC"
    r"|FBC|FFPC|NYCBC|NYCFC|OBC|OFC|WSBC|WSFC|MSBC|TBC"
    r")\b",
    re.IGNORECASE,
)

# Spelled-out names, matched case-insensitively as substrings. The more
# specific phrase comes first ("Existing Building" before "Building").
_NAMED_CODES: tuple[tuple[str, str], ...] = (
    ("international existing building code", "IEBC"),
    ("international building code", "IBC"),
    ("international fire code", "IFC"),
    ("international mechanical code", "IMC"),
    ("international plumbing code", "IPC"),
    ("international fuel gas code", "IFGC"),
    ("international energy conservation code", "IECC"),
    ("international residential code", "IRC"),
    ("international property maintenance code", "IPMC"),
    ("international wildland-urban interface code", "IWUIC"),
    ("international wildland urban interface code", "IWUIC"),
    ("international swimming pool and spa code", "ISPSC"),
    ("international green construction code", "IGCC"),
    ("national electrical code", "NFPA 70"),
    ("life safety code", "NFPA 101"),
    ("uniform plumbing code", "UPC"),
    ("uniform mechanical code", "UMC"),
    ("uniform statewide building code", "USBC"),
    ("statewide fire prevention code", "SFPC"),
    ("california existing building code", "CEBC"),
    ("california building code", "CBC"),
    ("california fire code", "CFC"),
    ("california mechanical code", "CMC"),
    ("california plumbing code", "CPC"),
    ("california electrical code", "CEC"),
    ("california green building", "CALGREEN"),
    ("florida building code", "FBC"),
    ("florida fire prevention code", "FFPC"),
    ("standard for the installation of sprinkler systems", "NFPA 13"),
    ("national fire alarm and signaling code", "NFPA 72"),
    ("fire alarm and signaling code", "NFPA 72"),
)

_EDITION_HEADER_RE = re.compile(r"\b(edition|year|version|adopted|cycle)\b", re.IGNORECASE)
_CODE_HEADER_RE = re.compile(r"\b(code|standard|document|publication|reference)s?\b", re.IGNORECASE)
_JURISDICTION_HEADER_RE = re.compile(
    r"\b(ahj|jurisdiction|authority|city|county|municipality|township|town|"
    r"borough|parish|state|location|agency|site|project)\b",
    re.IGNORECASE,
)
_NOTE_HEADER_RE = re.compile(
    r"\b(amend\w*|notes?|comments?|remarks?|local|modif\w*|exceptions?)\b", re.IGNORECASE,
)


@dataclass(frozen=True)
class AtlasJurisdiction:
    """One jurisdiction's adopted editions, as the pipeline will receive them.

    ``entries`` are governing-edition strings (``"NFPA 13 2025 (note)"``) in
    the form :func:`~drawing_analyzer.models.parse_governing_editions` reads;
    ``codes`` are those entries parsed. ``name`` is ``""`` when the workbook
    names no jurisdiction.
    """

    name: str
    entries: tuple[str, ...]
    codes: tuple[AdoptedCode, ...]

    @property
    def label(self) -> str:
        return self.name or "(no jurisdiction named)"

    def summary(self) -> str:
        """``"NFPA 13 2025; IBC 2024"`` — what the GUI shows for this choice."""
        return "; ".join(c.display for c in self.codes)


@dataclass
class AhjAtlas:
    """A loaded atlas: every jurisdiction found, plus what could not be read."""

    path: Path
    display_name: str
    jurisdictions: list[AtlasJurisdiction] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.jurisdictions)


# --------------------------------------------------------------------------- #
# Cell helpers
# --------------------------------------------------------------------------- #


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return str(value.year)
    return " ".join(str(value).split())


def _year(text: str) -> str | None:
    m = _YEAR_RE.search(text or "")
    return m.group(1) if m else None


def designation(text: str) -> str | None:
    """The code designation a cell names (``"IBC"``, ``"NFPA 13"``), or ``None``."""
    text = _cell_text(text)
    if not text:
        return None
    m = _DESIGNATION_RE.search(text)
    if m:
        # "NFPA13" / "nfpa-13" → "NFPA 13"; "ASME B31.9" and "IBC" unchanged.
        raw = m.group(1).upper().replace("-", " ")
        return " ".join(re.sub(r"^([A-Z]+)\s*(?=\d)", r"\1 ", raw).split())
    low = text.lower()
    for phrase, code in _NAMED_CODES:
        if phrase in low:
            return code
    return None


def _clean_note(text: str) -> str:
    # Parentheses would end the note early when the entry is re-parsed.
    note = " ".join(text.replace("(", "[").replace(")", "]").split())
    return note if len(note) <= _MAX_NOTE_CHARS else note[: _MAX_NOTE_CHARS - 1] + "…"


def _entry(code: str, year: str, note: str = "") -> str:
    note = _clean_note(note)
    return f"{code} {year}" + (f" ({note})" if note else "")


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def _read_rows(path: Path) -> list[tuple[str, list[list[str]]]]:
    """``[(sheet title, rows of cell text)]`` for every worksheet."""
    if path.suffix.lower() == ".csv":
        from .spec_documents import _decode_text_bytes

        text = _decode_text_bytes(path.read_bytes())
        rows = [
            [_cell_text(c) for c in row[:_MAX_COLS]]
            for _, row in zip(range(_MAX_ROWS), csv.reader(text.splitlines()))
        ]
        return [(path.stem, rows)]

    import openpyxl  # lazy: only an atlas load needs it

    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        sheets: list[tuple[str, list[list[str]]]] = []
        for ws in book.worksheets:
            rows: list[list[str]] = []
            for row in ws.iter_rows(max_col=_MAX_COLS, values_only=True):
                rows.append([_cell_text(c) for c in row])
                if len(rows) >= _MAX_ROWS:
                    break
            sheets.append((str(ws.title), rows))
        return sheets
    finally:
        book.close()


def _col(row: list[str], i: int | None) -> str:
    return row[i] if i is not None and i < len(row) else ""


def _find_layout(rows: list[list[str]]) -> tuple[str, int, dict[str, Any]] | None:
    """Locate the header row and classify the layout, or ``None`` (free text)."""
    for h, header in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if sum(1 for c in header if c) < 2:
            continue
        body = rows[h + 1:]
        edition_cols = [
            i for i, c in enumerate(header)
            if c and _EDITION_HEADER_RE.search(c) and designation(c) is None
        ]
        juris = next((i for i, c in enumerate(header) if c and _JURISDICTION_HEADER_RE.search(c)), None)
        notes = next((i for i, c in enumerate(header) if c and _NOTE_HEADER_RE.search(c)), None)
        if edition_cols:
            # "Adopted Code" reads as an edition header too; the edition column
            # is the one whose cells actually carry years.
            edition = max(edition_cols, key=lambda i: sum(1 for r in body if _year(_col(r, i))))
            # The code column: whichever other column names the most codes.
            scores = {
                i: sum(1 for r in body if designation(_col(r, i)))
                for i in range(len(header)) if i not in (edition, juris, notes)
            }
            code = max(scores, key=lambda i: (scores[i], bool(_CODE_HEADER_RE.search(header[i] or ""))),
                       default=None)
            if code is not None and scores[code] > 0:
                return "long", h, {"code": code, "edition": edition,
                                   "jurisdiction": juris, "notes": notes}
        code_cols = [
            i for i, c in enumerate(header)
            if c and designation(c) is not None and _year(c) is None and i != juris
        ]
        if code_cols:
            if juris is None:
                juris = next(
                    (i for i in range(len(header))
                     if i not in code_cols and any(_col(r, i) and not _year(_col(r, i)) for r in body)),
                    None,
                )
            return "wide", h, {"codes": code_cols, "jurisdiction": juris, "notes": notes}
    return None


def _parse_sheet(
    title: str, rows: list[list[str]], warnings: list[str],
) -> dict[str, list[str]]:
    """``{jurisdiction name: [entries]}`` for one worksheet."""
    found: dict[str, list[str]] = {}
    layout = _find_layout(rows)
    if layout is None:
        for row in rows:
            for cell in row:
                code, year = designation(cell), _year(cell)
                if code and year:
                    found.setdefault("", []).append(_entry(code, year))
        return found

    kind, h, cols = layout
    header, body = rows[h], rows[h + 1:]
    current = ""
    for n, row in enumerate(body, start=h + 2):
        if not any(row):
            continue
        name = _col(row, cols["jurisdiction"])
        if name:
            current = name
        note = _col(row, cols["notes"])
        if kind == "long":
            code_cell = _col(row, cols["code"])
            code = designation(code_cell)
            year = _year(_col(row, cols["edition"])) or _year(code_cell)
            if code is None and code_cell and len(code_cell) <= 40:
                code = code_cell  # the operator's own name for it
            if code and year:
                found.setdefault(current, []).append(_entry(code, year, note))
            elif code_cell:
                warnings.append(f"{title} row {n}: no edition year for {code_cell!r}")
        else:
            for i in cols["codes"]:
                cell = _col(row, i)
                year = _year(cell)
                if year:
                    # Only the cell's own words ("2021 w/ local amendments")
                    # ride as the note: a row-level note column describes the
                    # jurisdiction, not each code in it.
                    extra = _YEAR_RE.sub("", cell, count=1).strip(" ,;-–")
                    found.setdefault(current, []).append(
                        _entry(designation(header[i]) or header[i], year, extra)
                    )
    return found


def load_ahj_atlas(path: Any) -> AhjAtlas:
    """Read ``path`` into an :class:`AhjAtlas`. Never raises (I-3)."""
    path = Path(path)
    atlas = AhjAtlas(path=path, display_name=path.name)
    if path.suffix.lower() not in ATLAS_FILE_EXTENSIONS:
        atlas.error = (
            f"Unsupported file type {path.suffix or '(none)'} — save the atlas as "
            "an Excel workbook (.xlsx)."
        )
        return atlas
    try:
        sheets = _read_rows(path)
    except Exception as exc:  # noqa: BLE001 - any unreadable workbook is a captured error
        atlas.error = f"Could not read the workbook: {exc}"
        return atlas

    per_sheet = [(title, _parse_sheet(title, rows, atlas.warnings)) for title, rows in sheets]
    productive = [(t, f) for t, f in per_sheet if f]
    merged: dict[str, list[str]] = {}
    for title, found in productive:
        for name, entries in found.items():
            # A sheet with no jurisdiction column is named by its tab when the
            # workbook has several productive tabs (one tab per AHJ).
            key = name or (title if len(productive) > 1 else "")
            merged.setdefault(key, []).extend(entries)

    for name in sorted(merged, key=lambda n: (n == "", n.casefold())):
        codes, rejected = parse_governing_editions(merged[name])
        for r in rejected:
            atlas.warnings.append(f"{name or path.name}: could not read {r!r}")
        if codes:
            atlas.jurisdictions.append(AtlasJurisdiction(
                name=name,
                entries=tuple(_entry_for(c) for c in codes),
                codes=codes,
            ))
    if not atlas.jurisdictions:
        atlas.error = (
            "No code editions found. Expected a table with a code column and an "
            "edition/year column (or one column per code with the edition years "
            "in the cells)."
        )
    return atlas


def _entry_for(code: AdoptedCode) -> str:
    return _entry(code.code, code.edition, code.amendment_note or "")


def entries_for(jurisdictions: Iterable[AtlasJurisdiction]) -> list[str]:
    """Governing-edition entries to pass as ``governing_editions=``."""
    return [e for j in jurisdictions for e in j.entries]
