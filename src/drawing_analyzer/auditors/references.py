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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..models import Anchor, Finding, Verification
from . import sheet_ids as _S

# The reference auditor's grammar, normalization, and resolution now delegate to
# the shared :mod:`.sheet_ids` foundation (Phase 25 §17.2) — the single host-owned
# module every auditor (reference / sheet-index / naming / title-block) and the
# profile / cross-sheet resolvers share. These module-level aliases keep the
# historical private names working for the sibling auditors and the back-compat
# ``reference_audit`` shim that import them from here.

# Text folding (NFKC + Unicode-dash / zero-width normalization) — the same fold
# the shared module applies, so a title-block ID drawn with a non-breaking hyphen
# still matches an ASCII-hyphen reference to it (the "don't fabricate a missing
# sheet" cardinal sin). Applied to every extracted word before matching.
_normalize_text = _S.fold_text

# Resolution outcomes for one harvested reference (re-exported from the shared
# foundation). ``_SKIP`` is the historical spelling of the shared ``IGNORE`` —
# kept so older call sites / tests comparing against ``"SKIP"`` still read.
RESOLVED_IN_SET = _S.RESOLVED_IN_SET
MISSING_FROM_SET = _S.MISSING_FROM_SET
MALFORMED = _S.MALFORMED
_SKIP = "SKIP"

_SUGGEST_MAX_DIST = _S.SUGGEST_MAX_DIST
_MALFORMED_MAX_DIST = 2

# A looser capture used *inside* trigger phrases / detail bubbles: a token that
# may be hyphenated (M-101, F-D-01-1), compact (FP101), or dotted (M1.01).
# Captured tokens are validated with the shared lexer + learned grammar before
# being adjudicated, so the looseness here never produces a finding on its own.
_ID_CAPTURE = r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*"

# Reference trigger phrases. Each rule is (compiled regex, id-group index, anchor
# method, strength). The whole match (group 0) becomes the finding's verbatim
# source_quote and its anchored rectangle; the id group is the referenced sheet.
# ``strength`` gates a low-confidence set (one sheet, or no learned grammar) to
# only the STRONG triggers (§17.3) so a thin grammar can't fabricate references.
STRONG, MEDIUM = "strong", "medium"
_PHRASE_RULES: list[tuple[re.Pattern[str], int, str, str]] = [
    (re.compile(r"\bSEE\s+DRAWINGS?\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase", STRONG),
    (re.compile(r"\bSEE\s+SHEETS?\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase", STRONG),
    (re.compile(r"\bREFER\s+TO\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase", STRONG),
    (re.compile(r"\bSEE\s+(" + _ID_CAPTURE + r")\s+FOR\b", re.I), 1, "reference_phrase", MEDIUM),
    (re.compile(r"\bON\s+DRAWINGS?\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase", MEDIUM),
    (re.compile(r"\bPER\s+(" + _ID_CAPTURE + r")", re.I), 1, "reference_phrase", MEDIUM),
    # Detail bubble: NN / <sheet-id>, e.g. "04/F-G-02-0" (detail 04 on that sheet).
    (re.compile(r"(?<![A-Za-z0-9])\d{1,3}\s*/\s*(" + _ID_CAPTURE + r")"), 1, "detail_bubble", STRONG),
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
    """Broad shape screen — hyphenated / compact / dotted (shared lexer, §17.2)."""
    return _S.looks_like_sheet_id(token)


def _normalize_id(token: str) -> str:
    """Canonicalize an ID for comparison / indexing (shared normalization)."""
    return _S.normalize_sheet_id(token)


def _segment_shape(sheet_id: str) -> tuple | None:
    """A sheet ID's structural signature, or ``None`` (shared foundation, §17.3).

    Delegates to :func:`sheet_ids.id_signature`: alpha runs → ``("A", len)``,
    digit runs → ``("D",)`` (length-agnostic), and the literal ``-`` / ``.``
    separators between them. So ``F-D-01-1`` and ``F-D-02-0`` share a signature,
    ``NFPA-13`` never matches an ``M-101`` set, and compact/dotted families
    (``FP101``, ``M1.01``) each get their own grammar.
    """
    return _S.id_signature(sheet_id)


def _learn_grammar(ids: Iterable[str]) -> frozenset:
    """The set of ID signatures present in the set (its learned ID grammar)."""
    return _S.learn_grammar(ids)


# Edit distance (shared foundation) — re-exported private name for the sibling
# auditors (naming / title-block) that import it from here.
_levenshtein = _S.levenshtein


@dataclass
class SheetInventory:
    """The set's known sheet IDs and their learned ID grammar (shared, §17.2)."""

    ids: frozenset[str] = field(default_factory=frozenset)
    grammar: frozenset = field(default_factory=frozenset)

    def matches_grammar(self, target: str) -> bool:
        return _S.matches_grammar(target, self.grammar)

    def closest(self, target: str) -> tuple[str | None, int | None]:
        """Nearest in-set ID by edit distance (``(None, None)`` if empty).

        Deterministic tie-break to the lexicographically smallest so finding text
        (and so :func:`audit_references`) is reproducible run to run (I-7).
        """
        return _S.closest_in_set(target, self.ids)

    @property
    def low_confidence(self) -> bool:
        """A grammar too thin to trust MISSING/MALFORMED (§17.3).

        A one-sheet set — or one whose title-block IDs never resolved to a learned
        grammar — restricts adjudication to exact in-set matches under strong
        triggers only, so a thin convention can't fabricate references.
        """
        return len(self.ids) < 2 or not self.grammar


def _merge_adjacent_id_words(words: list[Any]) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Reconstruct sheet IDs split across adjacent same-line words (§17.3).

    A CAD export can break a sheet number into two or three words — ``"F-D-"``
    ``"01-1"`` or ``"M-"`` ``"101"`` — that only read as one ID when rejoined.
    Scans runs of words on the same text line (close ``y`` centers) with a small
    horizontal gap and yields each *maximal* rejoined run whose combined text
    :func:`_looks_like_sheet_id`, together with its union rectangle. Single words
    are handled by the caller; this returns only the **multi-word** merges, so a
    split title-block ID is still detected and a split reference still resolves.
    """
    merges: list[tuple[str, tuple[float, float, float, float]]] = []
    n = len(words)
    for i in range(n):
        xi0, yi0, xi1, yi1 = _wrect(words[i])
        h = max(1.0, yi1 - yi0)
        text = _wtext(words[i])
        rects = [_wrect(words[i])]
        prev_x1, prev_yc = xi1, (yi0 + yi1) / 2.0
        j = i + 1
        while j < n:
            xj0, yj0, xj1, yj1 = _wrect(words[j])
            yc = (yj0 + yj1) / 2.0
            gap = xj0 - prev_x1
            # Same line (center within half a line height) and a tight gap (an
            # ID break, not a word space) — 0.6× the token height is generous
            # enough for kerned splits yet well under a real inter-word space.
            if abs(yc - prev_yc) > 0.5 * h or gap < -1.0 or gap > 0.6 * h:
                break
            text += _wtext(words[j])
            rects.append(_wrect(words[j]))
            prev_x1, prev_yc = xj1, yc
            if len(text) > 1 and _looks_like_sheet_id(text):
                merges.append((text, tuple(_rect_union(rects))))  # maximal run so far
            j += 1
    return merges


def detect_sheet_id_word(sheet: Any) -> Any | None:
    """The title-block sheet-ID **word tuple** (so callers get its rect), or ``None``.

    Scans the ID-shaped word tokens and prefers the one nearest the **bottom-
    right** of the sheet — where the title-block sheet number lives — over stray
    ID-shaped tokens elsewhere (e.g. an ``NFPA-13`` in the general notes). Also
    considers IDs **split across adjacent words** (§17.3): a rejoined ``"M-"``
    ``"101"`` competes as a synthetic word so a split sheet number is not missed.
    A raster sheet (no words) yields ``None``.
    """
    words = list(getattr(sheet, "words", []) or [])
    candidates: list[Any] = [w for w in words if _looks_like_sheet_id(_wtext(w))]
    # Synthetic word tuples for split-across-words IDs — shaped like a get_text
    # word (x0,y0,x1,y1,text,…) so _wtext/_wrect read them uniformly.
    for text, (x0, y0, x1, y1) in _merge_adjacent_id_words(words):
        candidates.append((x0, y0, x1, y1, text, -1, -1, -1))
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
    word's text. A raster sheet (no words) yields ``None``.
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
    """Classify a referenced ID against the inventory (shared policy, §17.3).

    Returns ``(status, closest_id, distance)``. A target present in the set
    resolves; one that matches the learned grammar but is absent is ``MISSING``;
    a grammar-mismatching token that is a near-typo of a real sheet is
    ``MALFORMED``; a known non-sheet token (code/tag/voltage/RFI/dimension —
    §17.3 negative corpus) or any other out-of-grammar token is ``_SKIP`` (the
    historical spelling of the shared ``IGNORE``). Under a low-confidence
    inventory only exact matches resolve.
    """
    r = _S.classify_reference(
        target, inventory.ids, inventory.grammar,
        low_confidence=inventory.low_confidence,
    )
    status = _SKIP if r.status == _S.IGNORE else r.status
    return status, r.closest, r.distance


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
        source_id=sheet.ref.source_id,
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

    # Trigger phrases + detail bubbles. Under a low-confidence inventory (one
    # sheet, or no learned grammar) only the STRONG triggers run (§17.3), so a
    # thin grammar can't turn a stray token into a fabricated reference.
    low_conf = inventory.low_confidence
    for pattern, id_group, method, strength in _PHRASE_RULES:
        if low_conf and strength != STRONG:
            continue
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
            # On a low-confidence set the convention was learned from very few
            # (often one) sheet ids; report that limitation on the finding so the
            # reviewer weighs it accordingly (§17.3), rather than silently dropping
            # a genuine strong-trigger miss.
            conf_note = (
                " (single-sheet set — sheet-ID convention learned from limited data)"
                if low_conf else ""
            )
            if status == MISSING_FROM_SET:
                findings.append(_make_finding(
                    sheet, display_id, quote=quote, rect=rect, severity="medium",
                    text=f"References {target}; not present in the provided set"
                         f"{_suggestion(closest, dist)}.{conf_note}",
                    method=method,
                    note="referenced sheet not present in the provided set"
                         + (" (low-confidence grammar)" if low_conf else ""),
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
