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

import math
import re
import unicodedata
from collections import Counter
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


def _numbers_aligned(query: list[str], span: list[str], slack: int) -> bool:
    """Whether each measurement sits at its **own position** in the span.

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

    This makes the positional rule the whole veto for the window path — it
    subsumes the multiset check there, which would otherwise also refuse a
    legitimate match whose *non*-numeric garbled token happens to sit where the
    sheet carries an unrelated number (``…AND XXX`` against ``…AND 100``, whose
    own ``500`` is correctly located).
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
    # EVERY window that clears the floor is kept, not just the best-scoring ones,
    # because the numeric veto is applied before the ranking below. Filtering only
    # the best set discards a legitimate match whenever a higher-scoring
    # wrong-number occurrence exists elsewhere on the sheet: a 20-token quote
    # whose sheet carries one copy differing only by 500 -> 600 (19/20 = 0.95, the
    # sole best) and one correct copy with two OCR word errors (18/20 = 0.90) went
    # UNANCHORED — the wrong-number window was vetoed and the correct one was never
    # considered. ``matched`` is kept as the raw int rather than the ratio so ties
    # are exact by construction.
    qualifying: list[tuple[int, int]] = []       # (matched tokens, window start)
    window = Counter(stream.tokens[:m])
    matched = sum(min(count, window.get(token, 0)) for token, count in qcount.items())
    for k in range(n - m + 1):
        if matched / m >= _FUZZY_WINDOW_MIN_OVERLAP:
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
    vetted = [
        (score, k) for score, k in qualifying
        if _numbers_aligned(query, stream.tokens[k : k + m], slack)
    ]
    if not vetted:
        return None
    best_score = max(score for score, _ in vetted)
    best_starts = [k for score, k in vetted if score == best_score]
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
            # A sub-phrase that drops one of the quote's measurements anchors a
            # numeric claim to text that never carried the number — the same
            # defect as above, reached by discarding the digit instead of
            # mismatching it.
            # The span matched is `sub` verbatim (find_subsequences requires a
            # contiguous exact run), so no positional drift is possible here and
            # the multiset check is the whole veto: it refuses a sub-phrase that
            # drops one of the quote's measurements, which anchors a numeric
            # claim to text that never carried the number.
            if not _numbers_agree(query, sub):
                continue
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
        return _tile_anchor(tile, tile_rects, method="tile_no_text_evidence")
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
