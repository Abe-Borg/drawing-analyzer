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


# --------------------------------------------------------------------------- #
# Field-class label detection (§17.4) — HIGH-confidence extraction.
# --------------------------------------------------------------------------- #
#
# The recurrence heuristic below is quiet but only catches short single-token
# edit-distance variants. Phase 25 also compares actual field CLASSES located by
# their labels, so a *substantially* different value (a wholly different project
# number, a different package NAME — possibly multiword) is caught, and a
# label-less lone token stays telemetry rather than a false deterministic markup.

# Ordered specific → general (first match on a line wins) so "PROJECT NO." is a
# project_number, "PROJECT NAME"/"PROJECT" a project_name.
_FIELD_LABELS: list[tuple[re.Pattern[str], str, bool]] = [
    # (label regex over an upper-cased line prefix, field_class, multiword_value)
    (re.compile(r"^(?:PROJECT|PROJ\.?|JOB|COMM(?:ISSION)?)\s*(?:NO|NUMBER|#)\b\.?\s*:?\s*"), "project_number", False),
    (re.compile(r"^PROJECT\s*NAME\b\.?\s*:?\s*"), "project_name", True),
    (re.compile(r"^PACKAGE(?:\s*NAME)?\b\.?\s*:?\s*"), "package", True),
    (re.compile(r"^(?:ISSUE\s+)?DATE(?:D)?\b\.?\s*:?\s*"), "date", False),
    (re.compile(r"^PROJECT\b\.?\s*:?\s*"), "project_name", True),
]
_DATE_VALUE_RE = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}$")
_NUMBER_VALUE_RE = re.compile(r"^[A-Z0-9]{2,}(?:[-.][A-Z0-9]+)*$")


def _group_lines(words: list[Any]) -> list[list[Any]]:
    """Group band words into text lines (close ``y`` centers), each sorted by x."""
    items = sorted(
        words, key=lambda w: ((_wrect(w)[1] + _wrect(w)[3]) / 2.0, _wrect(w)[0])
    )
    lines: list[list[Any]] = []
    for w in items:
        yc = (_wrect(w)[1] + _wrect(w)[3]) / 2.0
        h = max(1.0, _wrect(w)[3] - _wrect(w)[1])
        if lines and abs(yc - _line_yc(lines[-1])) <= 0.6 * h:
            lines[-1].append(w)
        else:
            lines.append([w])
    for ln in lines:
        ln.sort(key=lambda w: _wrect(w)[0])
    return lines


def _line_yc(line: list[Any]) -> float:
    ys = [(_wrect(w)[1] + _wrect(w)[3]) / 2.0 for w in line]
    return sum(ys) / len(ys)


def _normalize_field_value(field_class: str, value: str) -> str:
    """Canonical comparison form for a field value by class (§17.4)."""
    v = " ".join(value.upper().split())
    if field_class in ("project_number", "date"):
        return v.replace(" ", "")
    return v  # package / project_name keep word breaks (multiword names)


def _extract_labeled_fields(lines: list[list[Any]]) -> dict[str, tuple[str, list[float]]]:
    """``field_class -> (value_string, value_rect)`` from labelled lines.

    For each line, matches the first field label at its start and takes the value
    as the remaining words on that line (a single token for number/date, the
    whole remainder for a multiword name). A label with no value is missingness —
    recorded by omission (telemetry), never a finding.
    """
    out: dict[str, tuple[str, list[float]]] = {}
    for line in lines:
        text = " ".join(_wtext(w) for w in line).upper()
        for pattern, field_class, multiword in _FIELD_LABELS:
            m = pattern.match(text)
            if m is None:
                continue
            tail = text[m.end():].strip()
            if not tail:
                break  # label present but no value → missingness (telemetry)
            value = tail if multiword else tail.split()[0]
            if field_class == "date" and not _DATE_VALUE_RE.match(value):
                break
            if field_class == "project_number" and not _NUMBER_VALUE_RE.match(value):
                break
            # Rect: the value words on this line (those whose text is in the tail).
            val_words = [w for w in line if _wtext(w).upper() and _wtext(w).upper() in tail]
            rect = list(_rect_union([_wrect(w) for w in val_words])) if val_words else list(_wrect(line[-1]))
            out.setdefault(field_class, (value, rect))
            break
    return out


def _rect_union(rects: list[tuple[float, float, float, float]]) -> list[float]:
    return [min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects)]


@dataclass
class _SheetBand:
    geom: Any
    own_id: str
    # normalized field token -> its first word rect on this sheet
    fields: dict = field(default_factory=dict)
    # field_class -> (raw value string, value rect) from label→value pairing
    labeled: dict = field(default_factory=dict)


def _sheet_band(geom: Any) -> _SheetBand | None:
    """The title-block-band field tokens + labelled fields for one sheet, or ``None``."""
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
    band_words = [
        w for w in (getattr(geom, "words", []) or [])
        if (_wrect(w)[0] + _wrect(w)[2]) / 2.0 >= band_left
    ]
    for w in band_words:
        raw = _wtext(w)
        if not _is_field_value(raw):
            continue
        tok = raw.strip().upper()
        if tok == own_id:            # the sheet number itself varies by design
            continue
        band.fields.setdefault(tok, list(_wrect(w)))
    band.labeled = _extract_labeled_fields(_group_lines(band_words))
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


# A labelled field must appear on at least this many sheets before its majority
# value is trusted as the set-wide norm (a real consensus, not a coincidence).
_MIN_LABELED_SHEETS = 3
_FIELD_CLASS_LABEL = {
    "project_number": "project number",
    "project_name": "project name",
    "package": "package name",
    "date": "date",
}


def _make_tb_finding(
    band: "_SheetBand", *, quote: str, rect: list[float], text: str, note: str,
) -> Finding:
    ref = band.geom.ref
    return Finding(
        sheet_id=band.own_id or f"{_stem(ref.source_name)}-p{ref.page_index + 1}",
        source_name=ref.source_name,
        source_id=ref.source_id,
        page_index=ref.page_index,
        category="coordination",
        severity="low",
        text=text,
        source_quote=quote,
        refs=[],
        anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="titleblock"),
        verification=Verification(status="DETERMINISTIC", note=note),
        sources=["auditor_titleblock"],
    )


def _audit_labeled_fields(bands: list[_SheetBand]) -> list[Finding]:
    """HIGH-confidence field-class drift: a labelled field whose value differs
    from the set-wide consensus for that field (any distance, incl. multiword).

    The label anchors the field's *identity*, so — unlike the recurrence path —
    this catches a wholly different project number or a different package NAME,
    not just a one-character neighbor. A field present on too few sheets, or with
    no clear majority, is treated as telemetry (no finding); mere absence on a
    sheet is never flagged.
    """
    findings: list[Finding] = []
    # field_class -> [(norm_value, raw_value, rect, band), …]
    by_class: dict[str, list[tuple]] = defaultdict(list)
    for band in bands:
        for fc, (val, rect) in band.labeled.items():
            by_class[fc].append((_normalize_field_value(fc, val), val, rect, band))

    for fc, rows in sorted(by_class.items()):
        if len(rows) < _MIN_LABELED_SHEETS:
            continue
        counts: dict[str, int] = defaultdict(int)
        for norm, *_ in rows:
            counts[norm] += 1
        consensus_norm = max(sorted(counts), key=lambda n: counts[n])
        threshold = max(2, int(round(_SHARE_FRAC * len(rows))))
        if counts[consensus_norm] < threshold:
            continue  # no clear majority → not a trustworthy norm
        consensus_raw = next(raw for norm, raw, _r, _b in rows if norm == consensus_norm)
        label = _FIELD_CLASS_LABEL.get(fc, fc)
        for norm, raw, rect, band in rows:
            if norm == consensus_norm:
                continue
            findings.append(_make_tb_finding(
                band, quote=raw, rect=rect,
                text=(f"Title-block {label} '{raw}' differs from '{consensus_raw}', "
                      f"shown on the rest of the set. Confirm the correct value on this sheet."),
                note=f"title-block {label} '{raw}' vs set norm '{consensus_raw}'",
            ))
    return findings


def audit_titleblock(rendered_sheets: Iterable[Any]) -> list[Finding]:
    """Flag title-block field values that drift from the set-wide norm.

    Two complementary paths, both ``DETERMINISTIC`` coordination findings anchored
    ``EXACT`` at the drifting value: a **high-confidence** field-class path
    (:func:`_audit_labeled_fields` — a labelled project number / package name /
    date whose value differs from the set consensus, catching substantially
    different and multiword values), and the conservative **recurrence** path (a
    single token that recurs identically across most of the set with a close
    variant on one sheet). Quiet by design — it never flags mere absence, and a
    label-less lone token is telemetry, not a finding. Empty for small sets
    (< ``_MIN_SHEETS`` with a readable band).
    """
    bands = [b for b in (_sheet_band(g) for g in rendered_sheets) if b is not None]
    if len(bands) < _MIN_SHEETS:
        return []

    findings: list[Finding] = list(_audit_labeled_fields(bands))

    shared = _shared_fields(bands)
    for band in bands:
        for tok, rect in sorted(band.fields.items()):
            if tok in shared:
                continue
            match = next((s for s in sorted(shared) if _is_variant(tok, s)), None)
            if match is None:
                continue
            findings.append(_make_tb_finding(
                band, quote=tok, rect=list(rect),
                text=(f"Title-block value '{tok}' differs from '{match}', shown on the "
                      f"rest of the set. Confirm the correct project/field value on this sheet."),
                note=f"title-block field '{tok}' vs set norm '{match}'",
            ))

    # Dedup by content id: a near-variant token can be caught by BOTH paths on the
    # same sheet (same quote → same Finding.id) — keep one, first-wins order (I-7).
    seen: set[str] = set()
    deduped: list[Finding] = []
    for f in findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        deduped.append(f)
    return deduped


def _stem(source_name: str) -> str:
    from pathlib import Path

    return Path(source_name).stem
