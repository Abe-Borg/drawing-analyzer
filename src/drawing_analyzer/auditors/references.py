"""Deterministic, zero-API cross-reference audit over sheet text layers.

Construction drawings constantly point at each other — "SEE DRAWING F-D-01-1",
detail bubbles like ``04/F-G-02-0``, spec citations like ``23 21 13``. When a
sheet is revised, those pointers go stale: a note still says ``F-D-01-0`` after
the sheet was reissued as ``F-D-01-1``, or a callout sends the reader to a sheet
that isn't in the package. On a real 8-sheet fire-protection set this exact
check caught three coordination errors (two stale ``F-D-01-0`` pointers and one
cross-reference to the wrong sheet).

The audit is **offline and free**: it reads only the sheets' extracted vector
text layers (``RenderedSheet.words`` — ``get_text("words")`` tuples with
coordinates), never the API. It:

1. builds the set's **sheet inventory** by detecting each sheet's own ID from its
   title block (bottom-right), and **learns the set's ID grammar** from that
   harvest rather than hardcoding one office's numbering convention;
2. **harvests references** from every sheet (trigger phrases, detail bubbles,
   CSI spec sections);
3. **resolves** each against the inventory — present (no finding), absent but
   well-formed (``MISSING``, with the closest in-set ID suggested by edit
   distance), or malformed;
4. **anchors** every finding to the reference's own word rectangle, for free —
   so reference findings ship with ``anchor.status="EXACT"`` and
   ``verification.status="DETERMINISTIC"`` and never touch a model.

Never claims a referenced sheet *doesn't exist* — only that it "is not present
in the provided set", because a partial set legitimately omits sheets.

This module imports **no PDF engine** (I-5): it works purely on the plain-tuple
word lists ``render.py`` extracted, so it stays unit-testable without PyMuPDF.

Its canonical home is :mod:`drawing_analyzer.auditors.references` (Phase 14 moved
it here from the flat ``reference_audit`` module, which now re-exports it for
backward compatibility). The word-tuple helpers it defines (``_wtext``,
``_wrect``, ``_rect_union``, ``_joined_stream``, ``_normalize_text``,
``detect_sheet_id``, ``build_inventory`` / :class:`SheetInventory`) are the shared
substrate the sibling auditors (``arithmetic``, ``naming``, ``titleblock``,
``sheet_index``) build on.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..models import Anchor, Finding, Verification

# Text normalization applied to every extracted word before matching. PDF/CAD
# exports routinely render a sheet-ID hyphen as a *non-ASCII* dash (non-breaking
# hyphen U+2011, en/em dash, fullwidth or minus sign); left as-is, an ID with a
# Unicode hyphen never matches the ASCII-hyphen regexes, so its sheet drops out
# of the inventory and any ASCII-hyphen reference to it is falsely flagged
# MISSING — the "don't fabricate a missing sheet" cardinal sin. NFKC folds
# compatibility forms; the table then maps the remaining dash variants to a plain
# ASCII "-" and strips zero-width / soft-hyphen artifacts that split tokens.
_DASHES = "‐‑‒–—―−﹘﹣－"
_STRIP = "­​‌‍﻿"  # soft hyphen, ZWSP/ZWNJ/ZWJ, BOM
_TEXT_TRANSLATION = {ord(c): "-" for c in _DASHES}
_TEXT_TRANSLATION.update({ord(c): "" for c in _STRIP})


def _normalize_text(text: str) -> str:
    """NFKC-normalize and fold Unicode dashes/invisibles for robust matching."""
    return unicodedata.normalize("NFKC", text).translate(_TEXT_TRANSLATION)

# Resolution outcomes for one harvested reference.
RESOLVED_IN_SET = "RESOLVED_IN_SET"
MISSING_FROM_SET = "MISSING_FROM_SET"
MALFORMED = "MALFORMED"
_SKIP = "SKIP"  # captured token that isn't a sheet reference in this set's grammar

# A referenced ID is suggested as the "closest in set" only within this edit
# distance (sheet IDs are short; a stale-revision pointer like F-D-01-0 vs
# F-D-01-1 is distance 1). Beyond it, we report the miss without a misleading
# suggestion.
_SUGGEST_MAX_DIST = 3
# A trigger-captured token that fails the set's grammar but sits this close to a
# real sheet ID is treated as a malformed reference (a likely typo of a real
# sheet) rather than silently skipped.
_MALFORMED_MAX_DIST = 2

# A single sheet-ID *token*: a discipline-letter prefix, then hyphen-joined
# alphanumeric groups (e.g. M-101, F-D-01-1, AVC10-F-D-01-1). Requires at least
# one hyphen group and — enforced separately — at least one digit, so plain
# words never qualify.
_SHEET_ID_TOKEN = re.compile(r"^[A-Za-z]{1,6}[0-9]{0,3}(?:-[A-Za-z0-9]{1,5}){1,6}$")

# A looser capture used *inside* trigger phrases / detail bubbles: any
# hyphen-joined alphanumeric run. Captured tokens are validated with
# :func:`_looks_like_sheet_id` and the learned grammar before being adjudicated,
# so the looseness here never produces a finding on its own.
_ID_CAPTURE = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+){1,6}"

# Reference trigger phrases. Each rule is (compiled regex, id-group index,
# anchor method). The whole match (group 0) becomes the finding's verbatim
# source_quote and its anchored rectangle; the id group is the referenced sheet.
_PHRASE_RULES: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"\bSEE\s+DRAWINGS?\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase"),
    (re.compile(r"\bSEE\s+SHEETS?\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase"),
    (re.compile(r"\bSEE\s+(" + _ID_CAPTURE + r")\s+FOR\b", re.I), 1, "reference_phrase"),
    (re.compile(r"\bREFER\s+TO\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase"),
    (re.compile(r"\bPER\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase"),
    (re.compile(r"\bON\s+DRAWINGS?\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase"),
    # Detail bubble: NN / <sheet-id>, e.g. "04/F-G-02-0" (detail 04 on that sheet).
    (re.compile(r"(?<![A-Za-z0-9])\d{1,3}\s*/\s*(" + _ID_CAPTURE + r")"), 1, "detail_bubble"),
]


# ---------------------------------------------------------------------------
# Word-tuple helpers (plain tuples from ``get_text("words")``; no PyMuPDF).
# ---------------------------------------------------------------------------


def _wtext(word: Any) -> str:
    # Normalize at the source so detection, the joined stream, matching, and the
    # inventory all operate on the same folded text — keeping the joined-string
    # offsets and word rects consistent.
    return _normalize_text(str(word[4]))


def _wrect(word: Any) -> tuple[float, float, float, float]:
    return (float(word[0]), float(word[1]), float(word[2]), float(word[3]))


def _rect_union(rects: list[tuple[float, float, float, float]]) -> list[float]:
    return [
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    ]


def _joined_stream(words: list[Any]) -> tuple[str, list[tuple[int, int]]]:
    """Single-space-join the words and record each word's ``[start, end)`` span.

    Matching phrases over the joined stream (rather than per word) is what lets a
    reference that spans several words — "SEE DRAWING F-D-01-0" — be found *and*
    mapped back to the exact words (hence rectangles) it covers.
    """
    parts: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    for i, w in enumerate(words):
        t = _wtext(w)
        if i:
            pos += 1  # the single joining space
        spans.append((pos, pos + len(t)))
        parts.append(t)
        pos += len(t)
    return " ".join(parts), spans


def _words_in_span(spans: list[tuple[int, int]], start: int, end: int) -> list[int]:
    """Indices of words whose char-span overlaps ``[start, end)``."""
    return [i for i, (s, e) in enumerate(spans) if s < end and e > start]


# ---------------------------------------------------------------------------
# Sheet-ID detection, grammar learning, and the inventory.
# ---------------------------------------------------------------------------


def _looks_like_sheet_id(token: str) -> bool:
    t = token.strip()
    return bool(_SHEET_ID_TOKEN.match(t)) and any(ch.isdigit() for ch in t)


def _normalize_id(token: str) -> str:
    return token.strip().upper()


def _segment_shape(sheet_id: str) -> tuple | None:
    """A sheet ID's structural shape, or ``None`` if it can't be a clean ID.

    Each hyphen-separated segment is classified: alpha → ``("A", len)``, mixed →
    ``("X", len)``, pure digit → ``("D",)`` (length-agnostic, since sheet numbers
    vary 1-3 digits within one convention). So ``F-D-01-1`` and ``F-D-01-0`` and
    ``F-D-02-0`` share a shape (revision/number differences don't change it),
    while ``NFPA-13`` (``("A", 4), ("D",)``) doesn't match an ``M-101``-style set
    (``("A", 1), ("D",)``).
    """
    segs = sheet_id.split("-")
    shape: list[tuple] = []
    for s in segs:
        if not s:
            return None  # leading / trailing / doubled hyphen — not a clean ID
        if s.isdigit():
            shape.append(("D",))
        elif s.isalpha():
            shape.append(("A", len(s)))
        else:
            shape.append(("X", len(s)))
    return tuple(shape)


def _learn_grammar(ids: Iterable[str]) -> frozenset:
    """The set of ID shapes present in the set (its learned ID grammar)."""
    return frozenset(
        shape for shape in (_segment_shape(i) for i in ids) if shape is not None
    )


def _levenshtein(a: str, b: str) -> int:
    """Plain iterative edit distance (no deps); short strings, so O(len^2) is fine."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(
                min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            )
        prev = cur
    return prev[-1]


@dataclass
class SheetInventory:
    """The set's known sheet IDs and their learned ID grammar."""

    ids: frozenset[str] = field(default_factory=frozenset)
    grammar: frozenset = field(default_factory=frozenset)

    def matches_grammar(self, target: str) -> bool:
        shape = _segment_shape(target)
        return shape is not None and shape in self.grammar

    def closest(self, target: str) -> tuple[str | None, int | None]:
        """Nearest in-set ID by edit distance (``(None, None)`` if empty).

        Iterates in sorted order so a tie (the common case for short sheet IDs —
        e.g. both ``M-101`` and ``M-102`` are distance 1 from ``M-103``) resolves
        deterministically to the lexicographically smallest, not to whatever
        ``frozenset`` iteration order a given ``PYTHONHASHSEED`` happens to
        produce. Determinism here is what keeps the finding text (and so
        :func:`audit_references`) reproducible run to run (I-7).
        """
        best: str | None = None
        best_d: int | None = None
        for sid in sorted(self.ids):
            d = _levenshtein(target, sid)
            if best_d is None or d < best_d:
                best, best_d = sid, d
        return best, best_d


def detect_sheet_id_word(sheet: Any) -> Any | None:
    """The title-block sheet-ID **word tuple** (so callers get its rect), or ``None``.

    Scans the ID-shaped word tokens and prefers the one nearest the **bottom-
    right** of the sheet — where the title-block sheet number lives — over stray
    ID-shaped tokens elsewhere (e.g. an ``NFPA-13`` in the general notes). A
    raster sheet (no words) yields ``None``. The title-block auditor uses the
    returned word's rectangle to learn each sheet's title-block x-band.
    """
    words = list(getattr(sheet, "words", []) or [])
    candidates = [w for w in words if _looks_like_sheet_id(_wtext(w))]
    if not candidates:
        return None
    w_pt = float(getattr(sheet, "page_width_pt", 0.0) or 0.0)
    h_pt = float(getattr(sheet, "page_height_pt", 0.0) or 0.0)

    def score(word: Any) -> float:
        x0, y0, x1, y1 = _wrect(word)
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        # PyMuPDF y grows downward, so the title block is at large x AND large y;
        # normalizing keeps the two axes comparable across sheet sizes.
        return (cx / w_pt if w_pt else 0.0) + (cy / h_pt if h_pt else 0.0)

    return max(candidates, key=score)


def detect_sheet_id(sheet: Any) -> str | None:
    """The sheet's own ID string, harvested from its title block, or ``None``.

    Thin wrapper over :func:`detect_sheet_id_word` that normalizes the winning
    word's text (upper-cased). A raster sheet (no words) yields ``None``.
    """
    best = detect_sheet_id_word(sheet)
    return _normalize_id(_wtext(best)) if best is not None else None


def build_inventory(rendered_sheets: Iterable[Any]) -> SheetInventory:
    """Detect each sheet's ID and learn the set's grammar from the harvest."""
    ids = {sid for sid in (detect_sheet_id(s) for s in rendered_sheets) if sid}
    return SheetInventory(ids=frozenset(ids), grammar=_learn_grammar(ids))


# ---------------------------------------------------------------------------
# Reference resolution + finding construction.
# ---------------------------------------------------------------------------


def _resolve(target: str, inventory: SheetInventory) -> tuple[str, str | None, int | None]:
    """Classify a referenced ID against the inventory.

    Returns ``(status, closest_id, distance)``. A target present in the set
    resolves; one that matches the set's grammar but is absent is ``MISSING``; a
    grammar-mismatching token that is nonetheless a near-typo of a real sheet is
    ``MALFORMED``; anything else (a code/standard token that merely followed a
    trigger word) is skipped — not flagged.
    """
    t = _normalize_id(target)
    if t in inventory.ids:
        return RESOLVED_IN_SET, None, None
    closest, dist = inventory.closest(t)
    if inventory.matches_grammar(t):
        return MISSING_FROM_SET, closest, dist
    if closest is not None and dist is not None and dist <= _MALFORMED_MAX_DIST:
        return MALFORMED, closest, dist
    return _SKIP, None, None


def _suggestion(closest: str | None, dist: int | None) -> str:
    if closest and dist is not None and dist <= _SUGGEST_MAX_DIST:
        return f" (closest in set: {closest})"
    return ""


def _fallback_sheet_id(sheet: Any) -> str:
    ref = sheet.ref
    return f"{Path(ref.source_name).stem}-p{ref.page_index + 1}"


def _make_finding(
    sheet: Any,
    display_id: str,
    *,
    quote: str,
    rect: list[float] | None,
    severity: str,
    text: str,
    method: str,
    note: str,
) -> Finding:
    anchor = (
        Anchor(status="EXACT", rect_pdf=rect, method=method)
        if rect is not None
        else Anchor(status="UNANCHORED", rect_pdf=None, method=method)
    )
    return Finding(
        sheet_id=display_id,
        source_name=sheet.ref.source_name,
        page_index=sheet.ref.page_index,
        category="reference",
        severity=severity,
        text=text,
        source_quote=quote,
        tile=None,
        refs=[],
        anchor=anchor,
        verification=Verification(status="DETERMINISTIC", note=note),
        sources=["auditor_reference"],
    )


def _audit_sheet(
    sheet: Any, display_id: str, inventory: SheetInventory,
    stats: dict | None = None,
) -> list[Finding]:
    words = list(getattr(sheet, "words", []) or [])
    if not words:
        return []
    joined, spans = _joined_stream(words)
    findings: list[Finding] = []
    seen: set[str] = set()  # verbatim source_quotes already emitted for this sheet

    def anchor_rect(idxs: list[int]) -> list[float] | None:
        if not idxs:
            return None
        return _rect_union([_wrect(words[i]) for i in idxs])

    # Trigger phrases + detail bubbles.
    for pattern, id_group, method in _PHRASE_RULES:
        for m in pattern.finditer(joined):
            raw = m.group(id_group)
            if not _looks_like_sheet_id(raw):
                continue
            target = _normalize_id(raw)
            status, closest, dist = _resolve(target, inventory)
            if status == RESOLVED_IN_SET:
                # No finding — but the plan says count it: resolved references are
                # the review's balance column ("N references resolved in set").
                if stats is not None:
                    stats["references_resolved"] = stats.get("references_resolved", 0) + 1
                continue
            if status == _SKIP:
                continue
            quote = m.group(0)
            # Dedup on the verbatim quote — which, with the (constant) sheet_id
            # and category, *is* what Finding.id hashes. Keying on it guarantees
            # every emitted finding on this sheet has a distinct id (no id
            # collision downstream) and collapses a reference repeated verbatim on
            # one sheet to a single finding — exactly what the ledger's later
            # text-overlap merge would do anyway.
            if quote in seen:
                continue
            seen.add(quote)
            rect = anchor_rect(_words_in_span(spans, *m.span(0)))
            if status == MISSING_FROM_SET:
                findings.append(_make_finding(
                    sheet, display_id, quote=quote, rect=rect, severity="medium",
                    text=f"References {target}; not present in the provided set"
                         f"{_suggestion(closest, dist)}.",
                    method=method,
                    note="referenced sheet not present in the provided set",
                ))
            else:  # MALFORMED
                sug = _suggestion(closest, dist).strip()
                findings.append(_make_finding(
                    sheet, display_id, quote=quote, rect=rect, severity="low",
                    text=f"Reference to {target} does not match this set's "
                         f"sheet-ID convention{('; did you mean ' + closest + '?') if closest and dist is not None and dist <= _SUGGEST_MAX_DIST else '.'}",
                    method=method,
                    note="malformed sheet reference (does not match the set's ID convention)",
                ))

    findings.extend(_audit_spec_sections(sheet, display_id, words, seen))
    return findings


def _audit_spec_sections(
    sheet: Any, display_id: str, words: list[Any], seen: set[str]
) -> list[Finding]:
    """Collect CSI MasterFormat section citations (``NN NN NN``) as informational.

    Emitted at ``severity="low"`` with a ``DETERMINISTIC`` note that the spec set
    isn't available to confirm them — the drawing set can't validate a spec
    reference, so these are surfaced, not judged.

    A CSI section is exactly three space-separated 2-digit groups. We therefore
    scan **maximal runs** of consecutive standalone 2-digit tokens and treat a run
    as a citation only when it is *exactly* three tokens long (first a plausible
    division, 00-49). A longer run is a numeric table (dimensions, schedule
    values), not a citation, and is skipped whole — this is deliberately
    conservative: it avoids both the overlapping-window duplicates a sliding
    3-wide scan produced and false positives on dense numeric rows, at the cost of
    missing a spec embedded mid-run (acceptable for an informational check).
    """
    findings: list[Finding] = []
    n = len(words)
    i = 0
    while i < n:
        if not _two_digit(_wtext(words[i])):
            i += 1
            continue
        j = i
        while j < n and _two_digit(_wtext(words[j])):
            j += 1
        # words[i:j] is a maximal run of 2-digit tokens.
        if j - i == 3 and 0 <= int(_wtext(words[i])) <= 49:
            spec = f"{_wtext(words[i])} {_wtext(words[i + 1])} {_wtext(words[i + 2])}"
            if spec not in seen:
                seen.add(spec)
                rect = _rect_union([_wrect(words[k]) for k in (i, i + 1, i + 2)])
                findings.append(_make_finding(
                    sheet, display_id, quote=spec, rect=rect, severity="low",
                    text=f"Cites specification section {spec}; the specification "
                         f"set is not available to verify this reference.",
                    method="spec_section",
                    note="specification set not available to verify",
                ))
        i = j  # skip past the whole run — never re-scan overlapping windows
    return findings


def _two_digit(token: str) -> bool:
    return len(token) == 2 and token.isdigit()


def audit_references(
    rendered_sheets: Iterable[Any], *, stats: dict | None = None
) -> list[Finding]:
    """Audit cross-references across a rendered set; return reference findings.

    Standalone and side-effect-free (wired into the pipeline in a later phase).
    Every returned :class:`~drawing_analyzer.models.Finding` has
    ``category="reference"``, an ``EXACT`` anchor on the reference's own words,
    and ``verification.status="DETERMINISTIC"`` — it never calls the API. A
    raster sheet (no text layer) contributes nothing. ``stats``, when given, is
    incremented with ``references_resolved`` — the pointers that *did* resolve in
    the set (no finding, but counted for the review's balance column).
    """
    sheets = list(rendered_sheets)
    inventory = build_inventory(sheets)
    findings: list[Finding] = []
    for sheet in sheets:
        display_id = detect_sheet_id(sheet) or _fallback_sheet_id(sheet)
        findings.extend(_audit_sheet(sheet, display_id, inventory, stats))
    return findings
