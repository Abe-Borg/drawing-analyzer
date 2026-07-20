"""Offline anchor resolver: place each finding's ``source_quote`` on its page.

A finding parsed from the digest carries a ``source_quote`` copied verbatim from
the sheet's text layer, plus the ``tile`` the model saw it in. This module maps
that quote back to a **rectangle on the page** — in the canonical **PAGE_VIEW_V2**
space (top-left origin, post-CropBox, post-rotation), the frame the model saw and
the frame :mod:`render` transforms its word rects into, so anchoring, the tile
grid, and verification crops all agree — using a tiered strategy and recording
which tier fired:

1. **EXACT** — the (normalized) quote matches a run of words verbatim. When the
   quote appears more than once (the "BATTERY ROOM in two schedule rows" trap),
   the hit inside the model's reported tile is preferred; if that still doesn't
   settle it, the first is taken and flagged ``exact_ambiguous``.
2. **FUZZY** — no exact run, but a sliding window of words overlaps the quote's
   tokens ≥ 85%, or the longest distinctive sub-phrase (≥ 3 tokens) of the quote
   appears verbatim. Whitespace/linebreak artifacts and Unicode punctuation are
   the usual reason exact fails; normalization folds most of them.
3. **TILE** — a graphics-only finding (empty quote) is anchored to its reported
   tile's rectangle: coarse, but honest.
4. **UNANCHORED** — a *non-empty* quote that matches nothing anywhere. This is
   the hallucination signal; the finding is kept and flagged loudly, never
   clouded by default.

Like :mod:`tiling`, this module imports **no PDF engine** — it works purely on
the plain (already view-space) word tuples ``render.py`` extracted and the
dependency-free tile geometry, so it is unit-testable without PyMuPDF.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any, Iterable

from . import tiling
from .models import Anchor, Finding, source_page_key

# A hyphen to fold to a space: only one sitting *between* two word characters
# (``2-1/2"`` → ``2 1/2"``, ``VAV-3`` → ``VAV 3``). A leading/sign hyphen is
# preserved so a signed value (``-5``) does not collapse onto its unsigned twin.
_INFIX_HYPHEN_RE = re.compile(r"(?<=\w)-(?=\w)")

# Padding added around a matched word-rect union so the cloud has a little air
# (PyMuPDF points). Tile rects are already coarse and are not padded.
_PAD_PT = 8.0

# Minimum token overlap for a fuzzy sliding-window match.
_FUZZY_WINDOW_MIN_OVERLAP = 0.85
# Shortest distinctive sub-phrase (in tokens) accepted by the fuzzy fallback.
_FUZZY_MIN_SUBPHRASE_TOKENS = 3
# Cap the sub-phrase search length so a pathological quote can't blow up cost.
_FUZZY_MAX_SUBPHRASE_TOKENS = 8

# Character folding applied (after NFKC) before matching, so the model's quote
# and the extracted words compare equal despite cosmetic differences: Unicode
# dashes/quotes/primes → ASCII, the diameter symbol → ``o``, invisibles removed.
_CHAR_FOLD: dict[int, str] = {}
for _c in "‐‑‒–—―−﹘﹣－":
    _CHAR_FOLD[ord(_c)] = "-"
for _c in "‘’‚‛′":  # single quotes, prime
    _CHAR_FOLD[ord(_c)] = "'"
for _c in "“”„‟″":  # double quotes, double prime
    _CHAR_FOLD[ord(_c)] = '"'
for _c in "Øø":  # Ø ø diameter symbol
    _CHAR_FOLD[ord(_c)] = "o"
for _c in "­​‌‍﻿":  # soft hyphen, zero-widths, BOM
    _CHAR_FOLD[ord(_c)] = ""


def _normalize(text: str) -> str:
    """Fold ``text`` to a canonical matching form.

    NFKC, then map Unicode punctuation to ASCII, treat an *infix* hyphen as a
    space (so ``2-1/2"`` and ``2 1/2"`` compare equal) while preserving a
    leading/sign hyphen (so ``-5`` does not collapse onto ``5``), lowercase, and
    collapse all whitespace to single spaces (the prototype's misses were
    whitespace/linebreak artifacts).
    """
    t = unicodedata.normalize("NFKC", text).translate(_CHAR_FOLD)
    # NFKC decomposes the double-prime inch mark (″) into two primes, which the
    # fold turns into '' — canonicalize that (and a literal '') to a plain " so
    # inches written as ", ″, or '' all compare equal.
    t = _INFIX_HYPHEN_RE.sub(" ", t.replace("''", '"')).lower()
    return " ".join(t.split())


def _tokenize(text: str) -> list[str]:
    return _normalize(text).split()


def _word_rect(word: Any) -> tuple[float, float, float, float]:
    return (float(word[0]), float(word[1]), float(word[2]), float(word[3]))


class _Stream:
    """The sheet's words as a flat, normalized token stream keyed to word rects.

    Each *token* (a word may normalize to several — e.g. ``2-1/2"`` → ``2`` +
    ``1/2"``) records the index of the source word it came from, so a matched
    token span maps straight back to the original word rectangles.
    """

    __slots__ = ("tokens", "word_of", "freq", "positions", "subsequence_cache")

    def __init__(self, words: list[Any]) -> None:
        self.tokens: list[str] = []
        self.word_of: list[int] = []
        for i, w in enumerate(words):
            for tok in _tokenize(str(w[4])):
                self.tokens.append(tok)
                self.word_of.append(i)
        self.freq = Counter(self.tokens)
        self.positions: dict[str, list[int]] = {}
        for pos, token in enumerate(self.tokens):
            self.positions.setdefault(token, []).append(pos)
        # Exact and fuzzy-subphrase anchoring repeatedly ask for the same token
        # sequences across findings.  Cache the immutable start-index result for
        # this one sheet; it never crosses a source or survives the run.
        self.subsequence_cache: dict[tuple[str, ...], tuple[int, ...]] = {}

    def find_subsequences(self, query: list[str]) -> list[int]:
        key = tuple(query)
        cached = self.subsequence_cache.get(key)
        if cached is not None:
            return list(cached)
        m = len(query)
        n = len(self.tokens)
        if m == 0 or m > n:
            starts: tuple[int, ...] = ()
        else:
            # Probe only positions carrying the first token instead of slicing
            # at every word on the sheet.  The final equality predicate is the
            # historical exact check, so matching semantics do not change.
            starts = tuple(
                pos for pos in self.positions.get(query[0], ())
                if pos + m <= n and self.tokens[pos : pos + m] == query
            )
        self.subsequence_cache[key] = starts
        return list(starts)


def _rect_union(rects: list[tuple[float, float, float, float]]) -> list[float]:
    return [
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    ]


def _padded(rect: list[float], w_pt: float, h_pt: float) -> list[float]:
    return [
        max(0.0, rect[0] - _PAD_PT),
        max(0.0, rect[1] - _PAD_PT),
        min(w_pt, rect[2] + _PAD_PT),
        min(h_pt, rect[3] + _PAD_PT),
    ]


def _span_rect(
    stream: _Stream, words: list[Any], start: int, length: int
) -> list[float] | None:
    """Union rect (top-left-origin points) of the words a token span covers."""
    word_idxs = sorted({stream.word_of[k] for k in range(start, start + length)})
    rects = [_word_rect(words[i]) for i in word_idxs if 0 <= i < len(words)]
    return _rect_union(rects) if rects else None


def _rect_center(rect: list[float]) -> tuple[float, float]:
    return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)


def _base_cell(cx: float, cy: float, w: float, h: float, rows: int, cols: int) -> tuple[int, int]:
    """The (row, col) base-grid cell a point falls in (overlap-independent)."""
    col = min(cols - 1, max(0, int(cx / (w / cols)))) if w > 0 and cols > 0 else 0
    row = min(rows - 1, max(0, int(cy / (h / rows)))) if h > 0 and rows > 0 else 0
    return (row, col)


def _reported_tile(finding: Finding, rows: int, cols: int) -> tuple[int, int] | None:
    t = finding.tile
    if not (isinstance(t, (list, tuple)) and len(t) == 2):
        return None
    try:
        r, c = int(t[0]), int(t[1])
    except (TypeError, ValueError):
        return None
    if 0 <= r < rows and 0 <= c < cols:
        return (r, c)
    return None


def _tile_preferred_start(
    starts: list[int], length: int, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> tuple[int, bool]:
    """Pick the start whose rect center falls in ``tile``; else the first.

    Returns ``(chosen_start, disambiguated)`` — ``disambiguated`` is True only
    when tile preference narrowed multiple candidates down to exactly one.
    """
    if len(starts) == 1:
        return starts[0], True
    if tile is not None:
        in_tile = []
        for s in starts:
            rect = _span_rect(stream, words, s, length)
            if rect is None:
                continue
            cx, cy = _rect_center(rect)
            if _base_cell(cx, cy, w, h, rows, cols) == tile:
                in_tile.append(s)
        if len(in_tile) == 1:
            return in_tile[0], True
        if in_tile:
            return in_tile[0], False
    return starts[0], False


def _try_exact(
    finding: Finding, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> Anchor | None:
    query = _tokenize(finding.source_quote)
    if not query:
        return None
    starts = stream.find_subsequences(query)
    if not starts:
        return None
    start, disambiguated = _tile_preferred_start(
        starts, len(query), stream, words, tile, w, h, rows, cols
    )
    rect = _span_rect(stream, words, start, len(query))
    if rect is None:
        return None
    method = "exact" if (len(starts) == 1 or disambiguated) else "exact_ambiguous"
    return Anchor(status="EXACT", rect_pdf=_padded(rect, w, h), method=method)


def _try_fuzzy_window(
    finding: Finding, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> Anchor | None:
    query = _tokenize(finding.source_quote)
    m = len(query)
    n = len(stream.tokens)
    if m == 0 or m > n:
        return None
    # Multiset (bag) overlap: how many of the query's m tokens, counting
    # repeats, are present in the window — divided by m. A plain set overlap
    # would dedupe repeats and let a window that merely contains the *distinct*
    # query tokens (scattered among unrelated words) score 100%, spuriously
    # anchoring a phrase that isn't there and defeating the UNANCHORED signal.
    qcount = Counter(query)
    best_overlap = 0.0
    best_starts: list[int] = []
    window = Counter(stream.tokens[:m])
    matched = sum(min(count, window.get(token, 0)) for token, count in qcount.items())
    for k in range(n - m + 1):
        overlap = matched / m
        if overlap < _FUZZY_WINDOW_MIN_OVERLAP:
            pass
        elif overlap > best_overlap:
            best_overlap, best_starts = overlap, [k]
        elif overlap == best_overlap:
            best_starts.append(k)
        if k + m >= n:
            continue
        outgoing = stream.tokens[k]
        incoming = stream.tokens[k + m]
        if outgoing in qcount:
            before = min(qcount[outgoing], window[outgoing])
            window[outgoing] -= 1
            after = min(qcount[outgoing], window[outgoing])
            matched += after - before
        else:
            window[outgoing] -= 1
        if window[outgoing] <= 0:
            del window[outgoing]
        if incoming in qcount:
            before = min(qcount[incoming], window.get(incoming, 0))
            window[incoming] += 1
            after = min(qcount[incoming], window[incoming])
            matched += after - before
        else:
            window[incoming] += 1
    if not best_starts:
        return None
    start, _ = _tile_preferred_start(best_starts, m, stream, words, tile, w, h, rows, cols)
    rect = _span_rect(stream, words, start, m)
    if rect is None:
        return None
    return Anchor(status="FUZZY", rect_pdf=_padded(rect, w, h), method="fuzzy_window")


def _try_fuzzy_subphrase(
    finding: Finding, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> Anchor | None:
    query = _tokenize(finding.source_quote)
    m = len(query)
    if m < _FUZZY_MIN_SUBPHRASE_TOKENS:
        return None
    max_len = min(m - 1, _FUZZY_MAX_SUBPHRASE_TOKENS, len(stream.tokens))
    for length in range(max_len, _FUZZY_MIN_SUBPHRASE_TOKENS - 1, -1):
        candidates: list[tuple[int, list[int]]] = []  # (distinctiveness, starts)
        for s in range(0, m - length + 1):
            sub = query[s : s + length]
            starts = stream.find_subsequences(sub)
            if not starts:
                continue
            # Distinctiveness = rarity of the sub-phrase's rarest token in the
            # sheet (lower = rarer = more trustworthy). Prefer distinctive matches
            # over ones built from common words.
            distinct = min(stream.freq.get(tok, 0) or 1 for tok in sub)
            candidates.append((distinct, starts))
        if candidates:
            candidates.sort(key=lambda c: c[0])
            _, starts = candidates[0]
            start, _ = _tile_preferred_start(
                starts, length, stream, words, tile, w, h, rows, cols
            )
            rect = _span_rect(stream, words, start, length)
            if rect is not None:
                return Anchor(
                    status="FUZZY", rect_pdf=_padded(rect, w, h), method="fuzzy_subphrase"
                )
    return None


def _tile_anchor(
    tile: tuple[int, int] | None, tile_rects: dict, method: str
) -> Anchor:
    if tile is not None and tile in tile_rects:
        tr = tile_rects[tile]
        return Anchor(status="TILE", rect_pdf=[tr.x0, tr.y0, tr.x1, tr.y1], method=method)
    return Anchor(status="UNANCHORED", rect_pdf=None, method="no_quote_no_tile")


def _anchor_one(
    finding: Finding, stream: _Stream, words: list[Any], tile_rects: dict,
    w: float, h: float, rows: int, cols: int,
) -> Anchor:
    tile = _reported_tile(finding, rows, cols)

    if not finding.source_quote.strip():
        # Graphics-only finding: anchor to its tile (coarse but honest), or leave
        # it unanchored if no usable tile was reported.
        return _tile_anchor(tile, tile_rects, method="tile")

    for attempt in (_try_exact, _try_fuzzy_window, _try_fuzzy_subphrase):
        anchor = attempt(finding, stream, words, tile, w, h, rows, cols)
        if anchor is not None:
            return anchor

    # A non-empty quote that matches nothing is the hallucination signal — keep
    # the finding but flag it; never cloud it by default.
    return Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")


def resolve_anchors(findings: Iterable[Finding], rendered_sheet: Any) -> list[Finding]:
    """Anchor each finding to a rectangle on ``rendered_sheet`` (in place).

    Pure function over the sheet's word tuples and tile geometry — no PDF engine.
    Findings that are **already anchored** (a non-``UNANCHORED`` status with a
    rect, e.g. the deterministic reference-audit findings) are left untouched;
    every other finding gets an :class:`~drawing_analyzer.models.Anchor` filling
    its ``anchor`` field. The same list is returned for chaining.

    ``findings`` are assumed to belong to ``rendered_sheet``; the caller groups
    them by sheet before calling.
    """
    findings = list(findings)
    words = list(getattr(rendered_sheet, "words", []) or [])
    w = float(getattr(rendered_sheet, "page_width_pt", 0.0) or 0.0)
    h = float(getattr(rendered_sheet, "page_height_pt", 0.0) or 0.0)
    rows = int(getattr(rendered_sheet, "rows", 1) or 1)
    cols = int(getattr(rendered_sheet, "cols", 1) or 1)
    overlap = float(getattr(rendered_sheet, "overlap_frac", tiling.DEFAULT_OVERLAP_FRAC))

    stream = _Stream(words)
    tile_rects: dict = {}
    if w > 0 and h > 0:
        tile_rects = {
            (tr.row, tr.col): tr
            for tr in tiling.tile_rects(w, h, rows=rows, cols=cols, overlap_frac=overlap)
        }

    for finding in findings:
        already = finding.anchor
        if already is not None and already.status != "UNANCHORED" and already.rect_pdf is not None:
            continue
        finding.anchor = _anchor_one(finding, stream, words, tile_rects, w, h, rows, cols)
    return findings


def resolve_conflict_legs(findings: Iterable[Finding], geom_by_key: dict) -> list[Finding]:
    """Anchor the ``also_on`` legs of cross-sheet findings, each on its own sheet.

    A :class:`~drawing_analyzer.models.ConflictLeg` duck-types as a finding for the
    resolver (it has ``source_quote`` / ``tile`` / ``anchor``), so legs are grouped
    by their sheet's :func:`source_page_key` and run through
    :func:`resolve_anchors` against that sheet's geometry. ``geom_by_key`` maps
    ``source_page_key`` → geometry; a leg whose sheet is absent is left
    ``UNANCHORED`` (it simply won't be clouded). Returns ``findings`` for chaining.
    """
    findings = list(findings)
    by_sheet: dict[tuple, list] = {}
    for f in findings:
        for leg in getattr(f, "also_on", None) or []:
            by_sheet.setdefault(source_page_key(leg), []).append(leg)
    for key, legs in by_sheet.items():
        geometry = geom_by_key.get(key)
        if geometry is not None:
            resolve_anchors(legs, geometry)
    return findings
