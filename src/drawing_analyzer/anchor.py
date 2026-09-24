"""Offline anchor resolver: place each finding's ``source_quote`` on its page.

A finding parsed from the digest carries a ``source_quote`` copied verbatim from
the sheet's text layer, plus the ``tile`` the model saw it in. This module maps
that quote back to a **rectangle on the page** — in the canonical **PAGE_VIEW_V2**
space (top-left origin, post-CropBox, post-rotation), the frame the model saw and
the frame :mod:`render` transforms its word rects into, so anchoring, the tile
grid, and verification crops all agree — using a tiered strategy and recording
which tier fired:

1. **EXACT** — the (normalized) quote matches a run of whole words verbatim.
   When the quote appears more than once (the "BATTERY ROOM in two schedule
   rows" trap), the hit inside the model's reported tile is preferred; if that
   still doesn't settle it, the first is taken and flagged ``exact_ambiguous``.
2. **FUZZY** — no exact run, but a sliding window of whole words overlaps the
   quote's tokens ≥ 85%, or the longest distinctive sub-phrase (≥ 3 tokens) of
   the quote appears verbatim, as whole words; both carry the numeric veto.
3. **TILE** — a graphics-only finding (empty quote) is anchored to its reported
   tile's rectangle: coarse, but honest.
4. **UNANCHORED** — a *non-empty* quote that matches nothing anywhere. This is
   the hallucination signal; the finding is kept and flagged loudly, never
   clouded by default.

Every tier matches **whole source words** (remediation WP-05.2, N12, the
owner's rule, ``word_core``): ``VAV-2`` never matches inside ``VAV-2-1``, in any
tier. And every word, of the sheet and of the quote alike, is normalized
(:func:`_normalize`: whitespace, case, Unicode dashes, quotes, primes and
fractions, infix hyphens) and then loses the brackets and sentence punctuation
at its edges (:func:`fold_word`, B4): ``RATED 175 PSI TYP`` matches ``RATED 175
PSI, TYP.`` and ``150 GPM 568 L/MIN`` matches ``150 GPM (568 L/MIN)``. What the
fold does not cover is a character-stream difference: an inch mark or percent
extracted as its own word (``6 "``, ``2 %``), words merged by extraction
(``INCHDRAIN``), and a split dimension (``12' - 6"``) (remediation WP-05.3).

Like :mod:`tiling`, this module imports **no PDF engine** — it works purely on
the plain (already view-space) word tuples ``render.py`` extracted and the
dependency-free tile geometry, so it is unit-testable without PyMuPDF.
"""
from __future__ import annotations

import math
import re
import unicodedata
from array import array
from bisect import bisect_left, bisect_right
from collections import Counter
from functools import lru_cache
from typing import Any, Iterable

from . import tiling
from .models import EVIDENCE_UNAVAILABLE, Anchor, Finding, source_page_key

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

# A token that carries a digit is a *measurement* for veto purposes (P7 item 30):
# ``6``, ``1/2"``, ``12'-6"``, ``101``, ``30%``.
_DIGIT_RE = re.compile(r"\d")

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
for _c in "\u2044\u2215":  # FRACTION SLASH, DIVISION SLASH -> plain "/" (N7)
    _CHAR_FOLD[ord(_c)] = "/"
_CHAR_FOLD[0x00D7] = "x"     # MULTIPLICATION SIGN, as in 300 x 200 duct (N7)
# Invisibles: soft hyphen, the three zero-width joiners/spaces, and the BOM.
# Written as ESCAPES, not literals (N8) — as literal characters they are
# invisible in every editor and diff, so a maintainer cannot see them, and an
# ordinary edit can delete or duplicate one silently.
for _c in (
    "\u00ad"    # SOFT HYPHEN
    "\u200b"    # ZERO WIDTH SPACE
    "\u200c"    # ZERO WIDTH NON-JOINER
    "\u200d"    # ZERO WIDTH JOINER
    "\ufeff"    # ZERO WIDTH NO-BREAK SPACE / BOM
):
    _CHAR_FOLD[ord(_c)] = ""

# Vulgar fractions, rewritten BEFORE NFKC (N7). NFKC turns "½" into "1⁄2" with no
# separating space, so a quote written `2½"` became `21⁄2"` — twenty-one halves —
# and could never match a sheet reading `2-1/2"`, which normalizes to `2 1/2"`.
# Rewriting to " 1/2" first puts the space in; the collapse at the end of
# _normalize tidies any doubled space.
_VULGAR_FRACTIONS = {
    "\u00bc": " 1/4", "\u00bd": " 1/2", "\u00be": " 3/4",
    "\u2150": " 1/7", "\u2151": " 1/9", "\u2152": " 1/10",
    "\u2153": " 1/3", "\u2154": " 2/3", "\u2155": " 1/5",
    "\u2156": " 2/5", "\u2157": " 3/5", "\u2158": " 4/5",
    "\u2159": " 1/6", "\u215a": " 5/6", "\u215b": " 1/8",
    "\u215c": " 3/8", "\u215d": " 5/8", "\u215e": " 7/8",
}
_VULGAR_FRACTION_TABLE = {ord(k): v for k, v in _VULGAR_FRACTIONS.items()}


def _normalize(text: str) -> str:
    """Fold ``text`` to a canonical matching form.

    Vulgar fractions are rewritten first (N7), then NFKC, then map Unicode
    punctuation to ASCII, treat an *infix* hyphen as a space (so ``2-1/2"`` and
    ``2 1/2"`` compare equal) while preserving a leading/sign hyphen (so ``-5``
    does not collapse onto ``5``), lowercase, and collapse all whitespace to
    single spaces (the prototype's misses were whitespace/linebreak artifacts).
    """
    # Vulgar fractions first — NFKC would otherwise glue "2½" into "21⁄2".
    pre = (text or "").translate(_VULGAR_FRACTION_TABLE)
    t = unicodedata.normalize("NFKC", pre).translate(_CHAR_FOLD)
    # NFKC decomposes the double-prime inch mark (″) into two primes, which the
    # fold turns into '' — canonicalize that (and a literal '') to a plain " so
    # inches written as ", ″, or '' all compare equal.
    t = _INFIX_HYPHEN_RE.sub(" ", t.replace("''", '"')).lower()
    return " ".join(t.split())


def _fold_text(text: str) -> str:
    """``text``'s words, each normalized and folded (:func:`fold_word`), joined
    by single spaces; a word that folds to nothing is dropped.

    The form a quote is matched in, by every tier: word by word, exactly as the
    sheet's words are folded, so the two compare whichever side carries the
    punctuation.
    """
    parts = []
    for word in (text or "").split():
        folded = fold_word(_normalize(word))
        if folded:
            parts.append(folded)
    return " ".join(parts)


def _tokenize(text: str) -> list[str]:
    return _fold_text(text).split()


# --------------------------------------------------------------------------- #
# Whole source words (remediation WP-05.1 and WP-05.2; the owner's rules, B4,
# B5 and N12)
#
# A quote matches a text only where it covers whole source words. A source word
# is a whitespace-delimited run of the text; a match may leave out the
# punctuation around a word, and may never start or end inside what the word
# says. So ``P-1`` is in ``P-1,`` and ``(P-1)``, while ``VAV-2`` is not in
# ``VAV-2-1``, ``AHU-10`` is not in ``AHU-101``, ``5`` is not in ``.5`` or
# ``-5``, and ``12`` is not in ``12,500`` or ``12'-6"``. Accepted cost: a tag
# inside a list written without spaces (``P-1,P-2``, ``M-101/M-102``) is
# inside one source word and does not match.
#
# Before words compare, every word (of the text and of the quote alike) loses
# the brackets and sentence punctuation at its edges (:func:`fold_word`,
# WP-05.2, B4), so ``RATED 175 PSI TYP`` is in ``RATED 175 PSI, TYP.`` and
# ``150 GPM 568 L/MIN`` is in ``150 GPM (568 L/MIN)``. A quote mark (``"``
# ``'``, which is also an inch or foot mark) and a comparison (``<`` ``>``)
# never fold: inside a match they must agree, so ``6"`` never matches ``6'``.
# At a match's two ends :func:`word_core` still lets the text's own marks stay
# outside it (``P-1`` in ``"P-1"``).
#
# One matcher, :class:`SourceWords`, serves both callers. Cross-sheet QC
# grounds a quote against a string, the sheet's uncapped text layer; the
# anchor's EXACT and sub-phrase tiers match against the sheet's words, and its
# window tier keeps to whole words too (``_try_fuzzy_window``).
# --------------------------------------------------------------------------- #

#: Punctuation a source word may carry before what it says. Not ``-`` or
#: ``.``: before a digit they are a sign and a decimal point (``-5``, ``.5``).
WORD_LEADING_PUNCTUATION = frozenset("([{<\"'")
#: Punctuation a source word may carry after what it says. Not ``%``: ``30%``
#: is a ratio, not the number 30.
WORD_TRAILING_PUNCTUATION = frozenset(")]}>,;:.!?\"'")


def word_core(word: str) -> tuple[int, int]:
    """``[start, end)`` of what a normalized source word says.

    ``word`` without its leading and trailing edge punctuation. A word made of
    nothing but edge punctuation has an empty core at its end.
    """
    start, end = 0, len(word)
    while start < end and word[start] in WORD_LEADING_PUNCTUATION:
        start += 1
    while end > start and word[end - 1] in WORD_TRAILING_PUNCTUATION:
        end -= 1
    return start, end


#: Punctuation folded off the start of every word before words compare
#: (remediation WP-05.2, B4): the brackets of :data:`WORD_LEADING_PUNCTUATION`.
#: Not ``<`` (a comparison: ``<5 PSI``), and not ``"`` or ``'`` (a quote mark,
#: or an inch or foot mark).
WORD_LEADING_FOLD = frozenset("([{")
#: Punctuation folded off the end of every word: the brackets and sentence
#: punctuation of :data:`WORD_TRAILING_PUNCTUATION`. Not ``>``, ``"`` or ``'``.
WORD_TRAILING_FOLD = frozenset(")]},;:.!?")


def fold_word(word: str) -> str:
    """A normalized word without the brackets and sentence punctuation at its edges.

    ``(p 1),`` becomes ``p 1``, ``psi,`` ``psi``, ``3:`` ``3`` and ``(568``
    ``568``, while ``6"),`` keeps its inch mark (``6"``), and ``.5``, ``-5``,
    ``30%`` and ``<5`` are unchanged. A word of nothing else (a lone comma)
    folds to ``""``. Applied to a sheet's words and a quote's alike, so the two
    compare whichever side carries the punctuation, and the numeric veto reads
    ``175`` on both.
    """
    start, end = 0, len(word)
    while start < end and word[start] in WORD_LEADING_FOLD:
        start += 1
    while end > start and word[end - 1] in WORD_TRAILING_FOLD:
        end -= 1
    if start == 0 and end == len(word):
        return word
    # Tidy: a vulgar fraction's rewrite puts a space inside a word ("( 1/2)").
    return " ".join(word[start:end].split())


class SourceWords:
    """A text's source words, normalized and folded, for whole-word matching.

    Built from a string (``SourceWords(text)``: cross-sheet QC's evidence text,
    split on whitespace) or from a sheet's words (``SourceWords(words=...)``:
    the anchor; each word's text split the same way, every piece keeping the
    index of the word it came from). Each source word is normalized on its own
    with :func:`_normalize`, then folded (:func:`fold_word`).

    ``normalized`` is the source words normalized and joined with single
    spaces: exactly ``_normalize(text)``, because whitespace survives the
    normalizer and nothing it changes reaches across a space. Matching runs
    over the folded words (``folded``), and keeps where each word starts,
    which the boundary rule needs, because the normalizer puts spaces *inside*
    a word (``VAV-2-1`` becomes ``vav 2 1``, and a vulgar fraction gains a
    space before it), so the string alone cannot tell ``vav 2`` from a whole
    word. A word that normalizes or folds to nothing (a word of invisibles, a
    lone comma) says nothing and takes no part in a match.
    """

    __slots__ = ("normalized", "folded", "index", "_parts", "_starts",
                 "_core_starts", "_core_ends", "_found")

    def __init__(self, text: str = "", *, words: "Iterable[Any] | None" = None) -> None:
        if words is None:
            pieces = enumerate((text or "").split())
        else:
            pieces = ((i, piece) for i, word in enumerate(words) for piece in str(word).split())
        normalized: list[str] = []
        parts: list[str] = []
        index = array("l")
        starts, core_starts, core_ends = array("l"), array("l"), array("l")
        at = 0
        for i, piece in pieces:
            norm = _normalize(piece)
            if not norm:
                continue                    # a word of invisibles says nothing
            normalized.append(norm)
            folded = fold_word(norm)
            if not folded:
                continue                    # nor does a lone comma or bracket
            if parts:
                at += 1                     # the joining space
            core_start, core_end = word_core(folded)
            index.append(i)
            starts.append(at)
            core_starts.append(at + core_start)
            core_ends.append(at + core_end)
            parts.append(folded)
            at += len(folded)
        self.normalized = " ".join(normalized)
        self.folded = " ".join(parts)
        #: For each folded word, the index of the word it came from: its place
        #: in ``text.split()``, or in the ``words`` given.
        self.index = index
        self._parts = parts
        # Each word's core is found once, here, never per occurrence: a quote
        # can recur thousands of times inside one long whitespace-free run (a
        # garbled or per-glyph text layer), and re-deriving the core from a
        # slice of that word at every occurrence was quadratic in its length
        # (Codex review).
        self._starts = starts
        self._core_starts = core_starts
        self._core_ends = core_ends
        self._found: dict[str, tuple[tuple[int, int], ...]] = {}

    def contains(self, quote: str) -> bool:
        """Whether ``quote`` occurs here covering whole source words.

        Every occurrence that could start a word is tried, so a quote printed
        both inside a longer identifier and on its own still matches. A quote
        that normalizes or folds to nothing matches nothing.
        """
        query = _fold_text(quote)
        found = self._found.get(query)
        if found is not None:
            return bool(found)
        return bool(self._scan(query, first=True))

    def spans(self, quote: str) -> tuple[tuple[int, int], ...]:
        """Every place ``quote`` covers whole source words, in reading order.

        Each is ``(first, last)``: the :attr:`index` of the first and last word
        the match covers.
        """
        return self.find(_fold_text(quote))

    def find(self, query: str) -> tuple[tuple[int, int], ...]:
        """:meth:`spans` for a query already folded (folded words, or their
        tokens, joined by single spaces). Remembered per query: the anchor asks
        a sheet for the same sub-phrases across many findings."""
        found = self._found.get(query)
        if found is None:
            found = self._found[query] = tuple(self._scan(query, first=False))
        return found

    def _scan(self, query: str, *, first: bool) -> list[tuple[int, int]]:
        """The whole-word occurrences of ``query``; with ``first``, at most one.

        An occurrence may start anywhere up to its word's core (leaving the
        word's leading marks outside it) and must end at or after the core of
        the word it ends in. One that starts inside a word's core rules out the
        rest of that word, so the scan moves to the next word: the work is
        bounded by the number of words, not by how often the query recurs
        inside one.
        """
        found: list[tuple[int, int]] = []
        if not query:
            return found
        text, starts = self.folded, self._starts
        at = text.find(query)
        while at != -1:
            i = bisect_right(starts, at) - 1
            if at > self._core_starts[i]:
                if i + 1 == len(starts):
                    break
                at = text.find(query, starts[i + 1])
                continue
            end = at + len(query)
            j = bisect_right(starts, end - 1) - 1
            if end >= self._core_ends[j]:
                span = (self.index[i], self.index[j])
                if first:
                    return [span]
                if not found or found[-1] != span:
                    found.append(span)
            at = text.find(query, at + 1)
        return found


@lru_cache(maxsize=128)
def source_words(text: str) -> SourceWords:
    """:class:`SourceWords` for ``text``, built once per distinct text.

    A sheet's text is matched once per leg and fact that quotes it; normalizing
    a dense sheet one word at a time takes tens of milliseconds.
    """
    return SourceWords(text)


def _word_rect(word: Any) -> tuple[float, float, float, float]:
    return (float(word[0]), float(word[1]), float(word[2]), float(word[3]))


class _Stream:
    """The sheet's words as a flat stream of folded tokens keyed to word rects.

    Built on the sheet's :class:`SourceWords` (``source``), through which the
    EXACT and sub-phrase tiers match whole words; the window tier reads the
    tokens. Each *token* (a word may fold to several: ``2-1/2"`` is ``2`` and
    ``1/2"``) records the index of the sheet word it came from (``word_of``),
    so a matched span maps straight back to the original word rectangles, and
    the token range of its source word, for the window's word rules.
    """

    __slots__ = ("source", "tokens", "word_of", "freq", "_word_start", "_word_end", "_bearing")

    def __init__(self, words: list[Any]) -> None:
        self.source = SourceWords(words=[str(w[4]) for w in words])
        self.tokens: list[str] = []
        self.word_of: list[int] = []
        self._word_start: list[int] = []     # per token: its source word's first token
        self._word_end: list[int] = []       # per token: one past its source word's last
        for part, i in zip(self.source._parts, self.source.index):
            start = len(self.tokens)
            pieces = part.split()
            self.tokens.extend(pieces)
            self.word_of.extend([i] * len(pieces))
            self._word_start.extend([start] * len(pieces))
            self._word_end.extend([start + len(pieces)] * len(pieces))
        self.freq = Counter(self.tokens)
        # The sheet words that carry a token, in reading order: what a match
        # from one word to another covers (a lone comma between them does not).
        self._bearing = sorted(set(self.word_of))

    def covered(self, first: int, last: int) -> tuple[int, ...]:
        """The sheet words a whole-word match from word ``first`` to ``last`` covers."""
        bearing = self._bearing
        return tuple(bearing[bisect_left(bearing, first):bisect_right(bearing, last)])

    def span_words(self, start: int, length: int) -> tuple[int, ...]:
        """The sheet words a token span covers, in reading order, each once."""
        return tuple(sorted(set(self.word_of[start:start + length])))

    def on_word_edges(self, start: int, length: int) -> bool:
        """Whether a token span starts on a source word's first token and ends
        on one's last: it covers whole words (remediation WP-05.2, N12)."""
        return (self._word_start[start] == start
                and self._word_end[start + length - 1] == start + length)

    def word_tokens(self, pos: int) -> range:
        """The token positions of the source word token ``pos`` belongs to."""
        return range(self._word_start[pos], self._word_end[pos])


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


def _words_rect(words: list[Any], idxs: "Iterable[int]") -> list[float] | None:
    """Union rect (top-left-origin points) of the given sheet words."""
    rects = [_word_rect(words[i]) for i in idxs if 0 <= i < len(words)]
    return _rect_union(rects) if rects else None


def _words_text(words: list[Any], idxs: "Iterable[int]") -> str:
    """The given sheet words, as printed, joined by single spaces.

    Whole words, as the sheet prints them: ``RATED 175 PSI, TYP.`` for a quote
    reading ``RATED 175 PSI TYP``, and ``2-1/2"`` for one reading ``2 1/2"``.
    """
    return " ".join(str(words[i][4]) for i in idxs if 0 <= i < len(words))


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


def _tile_preferred(
    candidates: list[tuple[int, ...]], words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> tuple[tuple[int, ...], bool]:
    """Pick the candidate (a match's sheet words) whose rect center falls in
    ``tile``; else the first.

    Returns ``(chosen, disambiguated)`` — ``disambiguated`` is True only when
    tile preference narrowed multiple candidates down to exactly one.
    """
    if len(candidates) == 1:
        return candidates[0], True
    if tile is not None:
        in_tile = []
        for c in candidates:
            rect = _words_rect(words, c)
            if rect is None:
                continue
            cx, cy = _rect_center(rect)
            if _base_cell(cx, cy, w, h, rows, cols) == tile:
                in_tile.append(c)
        if len(in_tile) == 1:
            return in_tile[0], True
        if in_tile:
            return in_tile[0], False
    return candidates[0], False


# What each quote tier returns on a hit: the anchor, and the sheet words the
# match covers, so a caller can read the sheet's own words there
# (:func:`resolve_anchors`' ``matched_text``).
_QuoteMatch = tuple[Anchor, tuple[int, ...]]


def _try_exact(
    finding: Finding, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> _QuoteMatch | None:
    """The quote's words, whole, verbatim apart from folded punctuation.

    Matched through the sheet's :class:`SourceWords`, the matcher cross-sheet
    QC grounds through, so the two agree (remediation WP-05.2): a match covers
    whole source words (``VAV-2`` never matches inside ``VAV-2-1``, N12), and
    the brackets and sentence punctuation at a word's edges fold on both sides
    (``RATED 175 PSI TYP`` matches ``RATED 175 PSI, TYP.``, B4). Still
    ``exact``: the fold never removes a digit, sign, decimal point, unit mark
    or ``%``, so every number the quote states is a whole word the sheet
    prints there (:func:`numbers_grounded`).
    """
    spans = stream.source.spans(finding.source_quote)
    if not spans:
        return None
    candidates = [stream.covered(first, last) for first, last in spans]
    chosen, disambiguated = _tile_preferred(candidates, words, tile, w, h, rows, cols)
    rect = _words_rect(words, chosen)
    if rect is None:
        return None
    method = "exact" if (len(candidates) == 1 or disambiguated) else "exact_ambiguous"
    return Anchor(status="EXACT", rect_pdf=_padded(rect, w, h), method=method), chosen


def _numeric_tokens(tokens: "Iterable[str]") -> Counter:
    """The multiset of digit-bearing tokens in ``tokens``."""
    return Counter(tok for tok in tokens if _DIGIT_RE.search(tok))


def _numbers_agree(query: list[str], span: list[str]) -> bool:
    """Whether quote and span carry the **same** measurements (multiset, both ways).

    Part of the **numeric veto** (P7 item 30). Fuzzy matching scores bag-of-token
    overlap, which is blind to exactly the substitution that matters most on a
    drawing: swap one digit and the score barely moves. Measured on
    ``PROVIDE 6 INCH DRAIN AT COLUMN LINE 4``, every one-number substitution
    tried — ``4``, ``12``, ``2-1/2``, and a changed column line — cleared the 0.85
    floor at 6/7 = 0.857 and clouded onto the real text, while a wholly invented
    sentence correctly went UNANCHORED. The hallucination signal was blind
    precisely where a wrong number is least cosmetic: a fire-sprinkler drain size
    clouded onto a sheet that says something else.

    Counted as a **multiset**, not by set membership: quoting
    ``PROVIDE 4 INCH DRAIN AT COLUMN LINE 4`` against a sheet reading
    ``... 6 INCH ... LINE 4`` needs two ``4``s while the span has one, and
    membership sees a ``4`` and waves it through.

    This is the veto for the **sub-phrase** path, where the matched span is the
    slice verbatim, so the failure mode is not a substitution but *dropping*: a
    3–8 token sub-phrase that omits the measurement anchors a numeric claim to
    text that never carried the number. The sliding-window path needs a
    positional rule instead — see :func:`_numbers_aligned`.

    A quote carrying no digits is unaffected — prose findings anchor exactly as
    before.
    """
    return _numeric_tokens(query) == _numeric_tokens(span)


def _numbers_aligned(query: list[str], span: list[str], slack: int) -> set[int] | None:
    """Where each measurement sits at its **own position** in the span, or ``None``.

    The other half of the veto, and the half that actually closes the hole.
    Multiset agreement alone is satisfied by a *sliding* window: dropping
    ``PROVIDE`` from the front let the window pick up the trailing ``4`` of
    ``COLUMN LINE 4`` — the quote's ``4`` was "found", playing a different role,
    on text still reading ``6 INCH`` — and sliding one further borrowed it from
    the *next line of the sheet* while shedding the unexplained ``6``. Presence
    anywhere in the span is not evidence; presence where the quote puts it is.

    ``slack`` bounds the positional drift, because a fuzzy window is the same
    length as the query and drift can only come from a token the overlap floor
    already permits to differ. The caller derives it from that floor rather than
    picking a constant, so the two can never disagree.

    Each span position is **consumed once**, so a repeated measurement needs a
    distinct occurrence per mention: a drawing note reading ``4 4-INCH DRAINS``
    against a sheet reading ``4 6-INCH DRAINS`` cannot satisfy both of the
    quote's ``4``s from the sheet's single one. Presence anywhere in the window is
    not evidence; presence where the quote puts it, once per claim, is.

    This makes the positional rule the whole numeric veto for the window path —
    it subsumes the multiset check there, which would otherwise also refuse a
    legitimate match whose *non*-numeric garbled token happens to sit where the
    sheet carries an unrelated number (``…AND XXX`` against ``…AND 100``, whose
    own ``500`` is correctly located). :func:`_measurements_whole` then checks
    the span positions it used (``None`` when a measurement has none).
    """
    if slack < 0:
        slack = 0
    used: set[int] = set()
    for i, token in enumerate(query):
        if not _DIGIT_RE.search(token):
            continue
        lo = max(0, i - slack)
        hi = min(len(span), i + slack + 1)
        for j in range(lo, hi):
            if j not in used and span[j] == token:
                used.add(j)
                break
        else:
            return None
    return used


def _measurements_whole(stream: _Stream, start: int, length: int, used: set[int]) -> bool:
    """Whether no quote measurement matches only part of a sheet word.

    Remediation WP-05.2 (N12), decided by the owner. For every window position
    a measurement aligned to (``used``, offsets into the window), each
    digit-bearing token of that position's source word must be aligned too.
    The window's edges are whole words (``_Stream.on_word_edges``), but a
    window may still leave out a quote word and take in a longer tag's extra
    number inside it: ``PROVIDE ACCESS PANEL AT VAV-2 FOR SERVICE …`` against a
    note printing ``VAV-2-1``, whose ``2`` aligns and whose ``1`` does not, or
    ``1/2" PIPE`` against ``2-1/2" PIPE``. A number the sheet prints as its own
    word, which the quote left out (a ``(689 KPA)`` conversion), is no part of
    any aligned word and does not refuse the window. Accepted limit: the rule
    reads numbers, so a letter-only tag (``VAV-A`` inside ``VAV-A-1``) is not
    refused.
    """
    for j in used:
        for p in stream.word_tokens(start + j):
            if _DIGIT_RE.search(stream.tokens[p]) and (
                not start <= p < start + length or p - start not in used
            ):
                return False
    return True


def _fuzzy_window_slack(m: int) -> int:
    """How far a measurement may drift inside a fuzzy window of ``m`` tokens.

    At most the number of tokens the overlap floor lets differ — one for a
    7-token quote, three for a 20-token one — so a legitimate match whose sheet
    text carries an inserted word still aligns, while a substitution cannot.
    """
    allowed_mismatches = m - math.ceil(m * _FUZZY_WINDOW_MIN_OVERLAP)
    return max(1, allowed_mismatches)


def _try_fuzzy_window(
    finding: Finding, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> _QuoteMatch | None:
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
    # EVERY window that clears the floor is kept, not just the best-scoring ones,
    # because the numeric veto is applied before the ranking below. Filtering only
    # the best set discards a legitimate match whenever a higher-scoring
    # wrong-number occurrence exists elsewhere on the sheet: a 20-token quote
    # whose sheet carries one copy differing only by 500 -> 600 (19/20 = 0.95, the
    # sole best) and one correct copy with two OCR word errors (18/20 = 0.90) went
    # UNANCHORED — the wrong-number window was vetoed and the correct one was never
    # considered. ``matched`` is kept as the raw int rather than the ratio so ties
    # are exact by construction.
    #
    # A window covers whole source words (remediation WP-05.2, N12): it starts
    # on a word's first token and ends on one's last. Without that, a match
    # the EXACT tier refuses for cutting a word (``VAV-2`` inside ``VAV-2-1``)
    # would qualify here at 100% overlap.
    qualifying: list[tuple[int, int]] = []       # (matched tokens, window start)
    window = Counter(stream.tokens[:m])
    matched = sum(min(count, window.get(token, 0)) for token, count in qcount.items())
    for k in range(n - m + 1):
        if matched / m >= _FUZZY_WINDOW_MIN_OVERLAP and stream.on_word_edges(k, m):
            qualifying.append((matched, k))
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
    if not qualifying:
        return None
    # The numeric veto runs across every above-threshold candidate FIRST, so a
    # span that accounts for the quote's measurements can win over a better-scoring
    # one that does not. Only then is the survivor set ranked by overlap and handed
    # to tile preference — the previous order let one vetoed top scorer sink an
    # otherwise good match.
    slack = _fuzzy_window_slack(m)
    vetted = []
    for score, k in qualifying:
        used = _numbers_aligned(query, stream.tokens[k : k + m], slack)
        if used is not None and _measurements_whole(stream, k, m, used):
            vetted.append((score, k))
    if not vetted:
        return None
    best_score = max(score for score, _ in vetted)
    best = [stream.span_words(k, m) for score, k in vetted if score == best_score]
    chosen, _ = _tile_preferred(best, words, tile, w, h, rows, cols)
    rect = _words_rect(words, chosen)
    if rect is None:
        return None
    return Anchor(status="FUZZY", rect_pdf=_padded(rect, w, h), method="fuzzy_window"), chosen


def _try_fuzzy_subphrase(
    finding: Finding, stream: _Stream, words: list[Any],
    tile: tuple[int, int] | None, w: float, h: float, rows: int, cols: int,
) -> _QuoteMatch | None:
    query = _tokenize(finding.source_quote)
    m = len(query)
    if m < _FUZZY_MIN_SUBPHRASE_TOKENS:
        return None
    max_len = min(m - 1, _FUZZY_MAX_SUBPHRASE_TOKENS, len(stream.tokens))
    for length in range(max_len, _FUZZY_MIN_SUBPHRASE_TOKENS - 1, -1):
        candidates: list[tuple[int, list[int]]] = []  # (distinctiveness, starts)
        for s in range(0, m - length + 1):
            sub = query[s : s + length]
            # A sub-phrase that drops one of the quote's measurements anchors a
            # numeric claim to text that never carried the number — the same
            # defect as above, reached by discarding the digit instead of
            # mismatching it.
            # The span matched is `sub` verbatim (a contiguous run of whole
            # source words, through the matcher the EXACT tier uses), so no
            # positional drift is possible here and the multiset check is the
            # whole veto: it refuses a sub-phrase that drops one of the quote's
            # measurements, which anchors a numeric claim to text that never
            # carried the number.
            if not _numbers_agree(query, sub):
                continue
            spans = stream.source.find(" ".join(sub))
            if not spans:
                continue
            # Distinctiveness = rarity of the sub-phrase's rarest token in the
            # sheet (lower = rarer = more trustworthy). Prefer distinctive matches
            # over ones built from common words.
            distinct = min(stream.freq.get(tok, 0) or 1 for tok in sub)
            candidates.append((distinct, spans))
        if candidates:
            candidates.sort(key=lambda c: c[0])
            _, spans = candidates[0]
            chosen, _ = _tile_preferred(
                [stream.covered(first, last) for first, last in spans],
                words, tile, w, h, rows, cols,
            )
            rect = _words_rect(words, chosen)
            if rect is not None:
                return (
                    Anchor(status="FUZZY", rect_pdf=_padded(rect, w, h),
                           method="fuzzy_subphrase"),
                    chosen,
                )
    return None


# Anchor methods whose match puts every digit-bearing token of the quote on its
# own token of the sheet, once per mention: EXACT is the quote's words verbatim,
# apart from the brackets and sentence punctuation folded off a word's edges,
# which never include a digit, sign, decimal point, unit mark or ``%``
# (remediation WP-05.2, decided by the owner: a folded match stays ``exact``);
# the window tier aligns each measurement at its position (``_numbers_aligned``);
# the sub-phrase tier matches a verbatim run holding the quote's whole digit
# multiset (``_numbers_agree``). A method not listed here does not ground a
# number until it carries the veto, so a new tier fails closed.
_NUMBER_GROUNDING_METHODS = {
    "EXACT": frozenset({"exact", "exact_ambiguous"}),
    "FUZZY": frozenset({"fuzzy_window", "fuzzy_subphrase"}),
}


def numbers_grounded(anchor: Anchor | None) -> bool:
    """Whether ``anchor`` shows the quote's numbers are printed on the sheet.

    True for an EXACT anchor and for a FUZZY one by a numerically vetoed method
    (P7 item 30); never for TILE (a location, not a text match) or UNANCHORED
    (the hallucination signal). The arithmetic auditor trusts a claim's operands
    only through such an anchor (remediation WP-07.1, N3).
    """
    if anchor is None:
        return False
    return anchor.method in _NUMBER_GROUNDING_METHODS.get(anchor.status, frozenset())


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
) -> tuple[Anchor, tuple[int, ...] | None]:
    """The finding's anchor, and the sheet words its quote matched (``None`` for
    a TILE or UNANCHORED anchor: nothing on the sheet matched the quote)."""
    tile = _reported_tile(finding, rows, cols)

    if not finding.source_quote.strip():
        # Graphics-only finding: anchor to its tile (coarse but honest), or leave
        # it unanchored if no usable tile was reported.
        return _tile_anchor(tile, tile_rects, method="tile"), None

    for attempt in (_try_exact, _try_fuzzy_window, _try_fuzzy_subphrase):
        hit = attempt(finding, stream, words, tile, w, h, rows, cols)
        if hit is not None:
            return hit

    # A non-empty quote that matches nothing is normally the hallucination
    # signal — keep the finding but flag it; never cloud it by default.
    #
    # WP-03B §8.4 Part 3, the one exception: when the host recorded that NO
    # textual check was possible for this leg (a scanned sheet, or the pasted
    # raster region of a hybrid one), an unmatched quote is not evidence of
    # fabrication — there was nothing to match against. Such a leg falls back to
    # the tile the model reported, at the coarse-but-honest TILE tier, so it can
    # reach the crop check and the investigation loop instead of dying
    # UNANCHORED where nothing downstream can look at it.
    #
    # Deliberately NOT a general relaxation: EVIDENCE_NOT_MATCHED (text existed
    # and the quote should have been findable) still returns quote_not_found, and
    # so does every finding that carries no evidence state at all — the digest,
    # critique and whole-set cross-QC paths are untouched.
    if getattr(finding, "evidence_state", "") == EVIDENCE_UNAVAILABLE:
        return _tile_anchor(tile, tile_rects, method="tile_no_text_evidence"), None
    return Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found"), None


def resolve_anchors(
    findings: Iterable[Finding],
    rendered_sheet: Any,
    *,
    matched_text: dict[int, str] | None = None,
) -> list[Finding]:
    """Anchor each finding to a rectangle on ``rendered_sheet`` (in place).

    Pure function over the sheet's word tuples and tile geometry — no PDF engine.
    Findings that are **already anchored** (a non-``UNANCHORED`` status with a
    rect, e.g. the deterministic reference-audit findings) are left untouched;
    every other finding gets an :class:`~drawing_analyzer.models.Anchor` filling
    its ``anchor`` field. The same list is returned for chaining.

    ``findings`` are assumed to belong to ``rendered_sheet``; the caller groups
    them by sheet before calling.

    ``matched_text``, when given, receives ``id(finding) →`` the sheet's own
    words the finding's quote matched, whole and as printed (:func:`_words_text`:
    ``RATED 175 PSI, TYP.`` for a quote reading ``RATED 175 PSI TYP``), for
    every finding this call anchors EXACT or FUZZY; nothing for a TILE or
    UNANCHORED anchor, or for a finding left untouched. It changes no anchor.
    The arithmetic auditor reads it to count the numbers the sheet prints
    there, not only the ones the model's quote says it prints (remediation
    WP-07.1, N3).
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
        anchor, matched = _anchor_one(finding, stream, words, tile_rects, w, h, rows, cols)
        finding.anchor = anchor
        if matched_text is not None and matched is not None:
            matched_text[id(finding)] = _words_text(words, matched)
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
