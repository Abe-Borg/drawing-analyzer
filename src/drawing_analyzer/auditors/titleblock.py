"""Title-block consistency auditor (Phase 14) — zero API.

Every sheet in a set carries the same title block: one project number, one
project/package name, one issue date. When a sheet is spun off or hand-edited,
one of those fields can drift — a transposed project-number digit, a stale date on
a single sheet. That is a real coordination defect and a cheap one to catch.

The check is deliberately conservative to stay quiet on a busy sheet. It learns
each sheet's title-block **x-band** from where that sheet's own ID sits (title
blocks are the right-edge strip that ends in the sheet number), harvests the
field-value tokens in that band, and finds the tokens that recur — *identically* —
across most of the set. Those are the shared title-block fields. It then flags
only a sheet that shows a near-**variant** of a shared field (same letters, an
edit or two apart) rather than the shared value — the transposed-digit signal —
and never merely-absent fields, which are usually just band-detection gaps.

Limitation (documented, per the plan's stated model): fields are read from the
sheet-ID x-band, so a value printed in a bottom strip to the *left* of that band
isn't seen. PDF-engine-free (I-5).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..models import Anchor, Finding, Verification
from .references import _levenshtein, _wrect, _wtext, detect_sheet_id, detect_sheet_id_word

# The band extends this fraction of the page width to the LEFT of the sheet-ID
# word, plus everything to its right — the right-edge title-block strip.
_BAND_LEFT_FRAC = 0.18
# Need a real set before a "most sheets agree" signal means anything.
_MIN_SHEETS = 4
# A token counts as a shared field when it appears (identically) in at least this
# fraction of the sheets that have a detectable band.
_SHARE_FRAC = 0.8
# A variant is 1–2 edits from the shared value and no more than one char longer /
# shorter (a changed/added digit, not an unrelated token that happens to be close).
_VARIANT_MIN_DIST = 1
_VARIANT_MAX_DIST = 2
_VARIANT_MAX_LEN_DELTA = 1

# A title-block field value: an identifier-ish token with a digit (project number,
# package code, single-token numeric date). Bare words and short tokens are out.
_FIELD_RE = re.compile(r"^[A-Za-z0-9]+(?:[-/.][A-Za-z0-9]+)*$")
_FIELD_MIN_LEN = 3


def _alphabet_shape(token: str) -> tuple[str, ...]:
    return tuple(ch.upper() for ch in token if ch.isalpha())


def _is_field_value(token: str) -> bool:
    t = token.strip()
    if len(t) < _FIELD_MIN_LEN:
        return False
    if not _FIELD_RE.match(t):
        return False
    return any(c.isdigit() for c in t)


@dataclass
class _SheetBand:
    geom: Any
    own_id: str
    # normalized field token -> its first word rect on this sheet
    fields: dict = field(default_factory=dict)


def _sheet_band(geom: Any) -> _SheetBand | None:
    """The title-block-band field tokens (+ rects) for one sheet, or ``None``."""
    sid_word = detect_sheet_id_word(geom)
    if sid_word is None:
        return None
    page_w = float(getattr(geom, "page_width_pt", 0.0) or 0.0)
    if page_w <= 0:
        return None
    sid_x0 = _wrect(sid_word)[0]
    band_left = sid_x0 - _BAND_LEFT_FRAC * page_w
    own_id = (detect_sheet_id(geom) or "").upper()
    band = _SheetBand(geom=geom, own_id=own_id)
    for w in getattr(geom, "words", []) or []:
        x0, _y0, x1, _y1 = _wrect(w)
        if (x0 + x1) / 2.0 < band_left:
            continue
        raw = _wtext(w)
        if not _is_field_value(raw):
            continue
        tok = raw.strip().upper()
        if tok == own_id:            # the sheet number itself varies by design
            continue
        band.fields.setdefault(tok, list(_wrect(w)))
    return band


def _shared_fields(bands: list[_SheetBand]) -> set[str]:
    """Field tokens present (identically) in at least ``_SHARE_FRAC`` of sheets."""
    counts: dict[str, int] = defaultdict(int)
    for b in bands:
        for tok in b.fields:
            counts[tok] += 1
    threshold = max(2, int(round(_SHARE_FRAC * len(bands))))
    return {tok for tok, c in counts.items() if c >= threshold}


def _is_variant(candidate: str, shared: str) -> bool:
    if candidate == shared:
        return False
    if _alphabet_shape(candidate) != _alphabet_shape(shared):
        return False
    if abs(len(candidate) - len(shared)) > _VARIANT_MAX_LEN_DELTA:
        return False
    return _VARIANT_MIN_DIST <= _levenshtein(candidate, shared) <= _VARIANT_MAX_DIST


def audit_titleblock(rendered_sheets: Iterable[Any]) -> list[Finding]:
    """Flag title-block field values that drift from the set-wide norm.

    Returns low-severity ``DETERMINISTIC`` coordination findings, one per drifting
    field per sheet, anchored ``EXACT`` at the variant token. Quiet by design: it
    fires only when most of the set agrees on a value and one sheet shows a close
    variant of it, and never on mere absence. Empty for small sets (< ``_MIN_SHEETS``
    with a readable band).
    """
    bands = [b for b in (_sheet_band(g) for g in rendered_sheets) if b is not None]
    if len(bands) < _MIN_SHEETS:
        return []
    shared = _shared_fields(bands)
    if not shared:
        return []

    findings: list[Finding] = []
    for band in bands:
        for tok, rect in sorted(band.fields.items()):
            if tok in shared:
                continue
            match = next(
                (s for s in sorted(shared) if _is_variant(tok, s)), None
            )
            if match is None:
                continue
            ref = band.geom.ref
            findings.append(Finding(
                sheet_id=band.own_id or f"{_stem(ref.source_name)}-p{ref.page_index + 1}",
                source_name=ref.source_name,
                page_index=ref.page_index,
                category="coordination",
                severity="low",
                text=(
                    f"Title-block value '{tok}' differs from '{match}', shown on the "
                    f"rest of the set. Confirm the correct project/field value on this sheet."
                ),
                source_quote=tok,
                refs=[],
                anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="titleblock"),
                verification=Verification(
                    status="DETERMINISTIC",
                    note=f"title-block field '{tok}' vs set norm '{match}'",
                ),
            ))
    return findings


def _stem(source_name: str) -> str:
    from pathlib import Path

    return Path(source_name).stem
