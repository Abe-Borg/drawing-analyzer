"""Shared host-owned sheet-ID normalization, discipline detection, and the
inventory / ambiguity model (Phase 24 §16.0).

Several subsystems reason about drawing-sheet identifiers: profile auto-suggest
picks a discipline from them, cross-sheet QC resolves a model-reported leg to a
real source by them, and (from Phase 25) the reference / sheet-index / naming /
title-block auditors will all lean on the same grammar. Historically each grew
its own ad-hoc parser — ``profiles.discipline_hint`` took the leading 1-3 letters
(so a *project-prefixed* id like ``AVC10-F-D-01-1`` yielded the project code
``AVC`` instead of the fire-protection discipline ``F``), while
``cross_qc``/``references`` each normalized ids their own way. This module is the
**single** host-owned foundation those callers share.

It is pure and PDF-engine-free (I-5): it works only on strings, so it stays
unit-testable without PyMuPDF and never leaves the coordinate/render boundary.

Scope grew across two phases. Phase 24 (§16.0): normalization, project-prefix-
aware discipline detection, a broad candidate lexer for the common id families
(hyphenated, compact, dotted, detail-bubble), and the inventory/ambiguity
resolver used to bind a model-reported id to exactly one source (or leave it
explicitly unbound / ambiguous — never "ink every candidate"). Phase 25 (§17.2 /
§17.3) added the learned **ID-grammar signatures** (:func:`id_signature` /
:func:`learn_grammar`), the reference **resolution policy**
(:func:`classify_reference` — RESOLVED_IN_SET / MISSING_FROM_SET / MALFORMED /
IGNORE), and the **negative corpus** (:func:`is_non_sheet_reference`) that keeps
equipment tags, code/standard citations, voltages, transmittal numbers, and
dimensions from ever becoming sheet findings. The reference / sheet-index /
naming / title-block auditors now all route their grammar through this module
(``auditors.references`` delegates to it and re-exports the historical private
names for the sibling auditors and the ``reference_audit`` shim).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #

# CAD/PDF exports routinely render a sheet-ID hyphen as a *non-ASCII* dash
# (non-breaking hyphen U+2011, en/em dash, minus sign, fullwidth hyphen); left
# as-is, an id with a Unicode hyphen never matches the ASCII-hyphen forms below,
# so its sheet silently drops out of the inventory. NFKC folds compatibility
# forms; the table then maps the remaining dash variants to a plain ASCII "-" and
# strips the zero-width / soft-hyphen artifacts that split tokens. Phase 25
# unified the two normalizers: ``auditors.references._normalize_text`` is now an
# alias of :func:`fold_text`, so every auditor folds text identically.
_DASHES = "‐‑‒–—―−﹘﹣－"
_STRIP = "­​‌‍﻿"  # soft hyphen, ZWSP/ZWNJ/ZWJ, BOM
_TEXT_TRANSLATION = {ord(c): "-" for c in _DASHES}
_TEXT_TRANSLATION.update({ord(c): "" for c in _STRIP})

# Surrounding punctuation trimmed off a captured id before it is adjudicated.
# Internal ``-`` and ``.`` are meaningful (they separate id segments) and are
# never stripped; only the *edges* are cleaned.
_EDGE_PUNCT = " \t\r\n\"'`.,;:()[]{}<>#/\\|*"


def fold_text(text: str) -> str:
    """NFKC-normalize and fold Unicode dashes / invisibles for robust matching.

    Never swaps ``O/0`` or ``I/1`` (a real numbering distinction a naive
    "cleanup" would destroy) — only dash variants and zero-width artifacts.
    """
    return unicodedata.normalize("NFKC", text or "").translate(_TEXT_TRANSLATION)


def normalize_sheet_id(raw: Any) -> str:
    """Canonicalize a sheet-ID string for comparison / indexing.

    Folds Unicode dashes, trims surrounding punctuation and whitespace, and
    upper-cases — preserving the meaningful internal ``-`` and ``.`` separators
    and never exchanging visually-similar characters. ``""`` for empty input.
    """
    s = fold_text(str(raw or "")).strip().strip(_EDGE_PUNCT).strip()
    return s.upper()


# --------------------------------------------------------------------------- #
# Discipline detection (project-prefix aware) — DA-018
# --------------------------------------------------------------------------- #

# Leading run of ASCII letters at the very start of a segment.
_LEADING_ALPHA = re.compile(r"^[A-Za-z]+")
# A sheet id is segmented on hyphens *and* dots for the purpose of finding its
# discipline field (NCS uses hyphens, some offices use dots).
_SEGMENT_SPLIT = re.compile(r"[-.]")
# Discipline tokens are short — cap what we return so a stray long word can never
# masquerade as a discipline tag (matches the historical 1-3 letter behavior).
_MAX_DISCIPLINE_LEN = 3


def _leading_letters(segment: str) -> str:
    m = _LEADING_ALPHA.match(segment or "")
    return m.group(0) if m else ""


def _looks_like_project_prefix(segment: str) -> bool:
    """True when a leading segment is a *project code* to skip, not a discipline.

    A discipline designator is a short **1-2 letter** field (``F``, ``M``, ``FP``,
    ``FA``, ``CE``). A project code — the thing that must be skipped so
    ``AVC10-F-...`` detects fire protection — is a **3+ letter** alpha run followed
    by digits within the same segment (``AVC10``, ``PROJ2``). The ``>= 3``
    leading-letters guard is what distinguishes the two: it keeps a *compact*
    discipline+number field like ``M1`` / ``E2`` **and** a two-letter compact
    discipline like ``FP101`` / ``FA101`` / ``CE201`` (whose discipline is the
    leading ``FP`` / ``FA`` / ``CE``, not a following suffix segment) from being
    misread as a project code — the regression the earlier ``>= 2`` guard caused.
    """
    lead = _leading_letters(segment)
    if len(lead) < 3:
        return False
    return any(ch.isdigit() for ch in segment)


def discipline_token(sheet_id: Any) -> str:
    """The discipline field of a sheet id, lower-cased (``""`` if none).

    Project-prefix aware (DA-018): ``AVC10-F-D-01-1`` → ``"f"`` (the meaningful
    discipline segment), not ``"avc"``. Plain forms are unchanged —
    ``F-D-01-1`` → ``"f"``, ``FP-101`` / ``FP101`` → ``"fp"``, ``M-101`` /
    ``M101`` / ``M1`` → ``"m"``, ``E1.01`` → ``"e"``. A leading number or empty
    id yields ``""``.
    """
    norm = normalize_sheet_id(sheet_id)
    if not norm:
        return ""
    segments = [s for s in _SEGMENT_SPLIT.split(norm) if s]
    if not segments:
        return ""
    seg0 = segments[0]
    # Skip a leading project code only when a real discipline segment follows it.
    if len(segments) > 1 and _looks_like_project_prefix(seg0):
        lead1 = _leading_letters(segments[1])
        if lead1:
            return lead1.lower()[:_MAX_DISCIPLINE_LEN]
    return _leading_letters(seg0).lower()[:_MAX_DISCIPLINE_LEN]


def discipline_tokens(sheet_ids: Iterable[Any]) -> set[str]:
    """The distinct non-empty discipline tokens across a set of sheet ids."""
    out = {discipline_token(s) for s in (sheet_ids or [])}
    out.discard("")
    return out


# --------------------------------------------------------------------------- #
# Candidate lexer — the common id families (broad; never a finding by itself)
# --------------------------------------------------------------------------- #

# Hyphenated NCS-style: a discipline prefix then hyphen-joined alnum groups
# (M-101, F-D-01-1, AVC10-F-D-01-1). Requires >=1 hyphen group.
_HYPHENATED = re.compile(r"^[A-Za-z]{1,6}[0-9]{0,3}(?:-[A-Za-z0-9]{1,6}){1,6}$")
# Compact: letters run straight into digits (M101, FP101, A001), no separators.
_COMPACT = re.compile(r"^[A-Za-z]{1,3}[0-9]{1,4}$")
# Dotted: a compact head then a dotted tail (M1.01, E2.1).
_DOTTED = re.compile(r"^[A-Za-z]{1,3}[0-9]{1,3}(?:\.[0-9]{1,3})+$")
# Detail bubble: NN / <sheet-id>, e.g. "5/FP101" or "04/F-D-01-1".
_BUBBLE = re.compile(r"^\d{1,3}\s*/\s*(?P<id>[A-Za-z0-9][A-Za-z0-9.\-]*)$")


def bubble_target(token: Any) -> str | None:
    """If ``token`` is a detail bubble (``NN/<id>``), the referenced id; else None."""
    m = _BUBBLE.match(str(token or "").strip())
    if m is None:
        return None
    target = m.group("id")
    return target if looks_like_sheet_id(target) else None


def looks_like_sheet_id(token: Any) -> bool:
    """True when a token *could* be a sheet id in one of the known families.

    A broad screen only — it recognizes the shape (hyphenated / compact /
    dotted), never adjudicates whether the id belongs to a set. It requires at
    least one digit so a plain word never qualifies.
    """
    t = normalize_sheet_id(token)
    if not t or not any(ch.isdigit() for ch in t):
        return False
    return bool(_HYPHENATED.match(t) or _COMPACT.match(t) or _DOTTED.match(t))


# --------------------------------------------------------------------------- #
# Learned ID grammar — signatures over alpha / digit / separator runs (§17.3)
# --------------------------------------------------------------------------- #
#
# A set's numbering *convention* is learned from the ids it actually contains,
# rather than hardcoding one office's scheme. Each trusted id is reduced to a
# structural **signature** — the sequence of its alpha / digit runs and the
# literal ``-`` / ``.`` separators between them — so a reference that matches the
# learned signature but is absent from the set reads as a real missing sheet,
# while a code/tag/dimension that merely followed a trigger word (a different
# signature) is ignored. Digit runs are length-agnostic (``M-1`` / ``M-101`` are
# one convention — "sheet numbers vary 1-3 digits"); alpha-run lengths and the
# separators are kept (so ``NFPA-13`` never matches an ``M-101`` set, and a dotted
# ``M1.01`` grammar is distinct from a hyphenated ``M-1-01``).

# A run of letters, a run of digits, or a single ``-`` / ``.`` separator. Anything
# else in a normalized candidate makes it un-signable (returns ``None``).
_RUN_RE = re.compile(r"[A-Za-z]+|[0-9]+|[-.]")


def id_signature(sheet_id: Any) -> tuple | None:
    """The structural signature of a sheet id, or ``None`` if it can't be one.

    Tokenizes the normalized id into maximal alpha / digit runs and the literal
    ``-`` / ``.`` separators between them: an alpha run → ``("A", len)``, a digit
    run → ``("D",)`` (length-agnostic), a separator → the character itself. So
    ``F-D-01-1`` and ``F-D-02-0`` share a signature (revision/number differences
    don't change it) while ``NFPA-13`` (``("A", 4), "-", ("D",)``) does not match
    an ``M-101`` set (``("A", 1), "-", ("D",)``); ``FP101`` → ``("A", 2), ("D",)``
    and ``M1.01`` → ``("A", 1), ("D",), ".", ("D",)`` are each their own grammar.
    ``None`` for a doubled / edge separator, an empty id, or any other character
    (a token that is not a clean id shape).
    """
    norm = normalize_sheet_id(sheet_id)
    if not norm:
        return None
    tokens: list[tuple | str] = []
    pos = 0
    prev_sep = True  # a leading separator is a doubled/edge separator → malformed
    has_alnum = False
    for m in _RUN_RE.finditer(norm):
        if m.start() != pos:
            return None  # a stray character (space, slash, …) — not a clean id
        pos = m.end()
        run = m.group(0)
        if run in "-.":
            if prev_sep:
                return None  # leading or doubled separator
            tokens.append(run)
            prev_sep = True
        else:
            prev_sep = False
            has_alnum = True
            if run[0].isdigit():
                tokens.append(("D",))
            else:
                tokens.append(("A", len(run)))
    if pos != len(norm) or prev_sep or not has_alnum:
        return None  # trailing separator / stray tail / no alnum content
    return tuple(tokens)


def learn_grammar(ids: Iterable[Any]) -> frozenset:
    """The set of ID signatures present in a set — its learned numbering grammar."""
    return frozenset(
        sig for sig in (id_signature(i) for i in (ids or [])) if sig is not None
    )


def matches_grammar(target: Any, grammar: frozenset) -> bool:
    """True when ``target``'s signature is one the set actually uses."""
    sig = id_signature(target)
    return sig is not None and sig in grammar


def levenshtein(a: str, b: str) -> int:
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
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def closest_in_set(target: Any, ids: Iterable[Any]) -> tuple[str | None, int | None]:
    """Nearest in-set id to ``target`` by edit distance (``(None, None)`` if empty).

    Iterates in sorted order so a tie (the common case for short ids — both
    ``M-101`` and ``M-102`` are distance 1 from ``M-103``) resolves
    deterministically to the lexicographically smallest, keeping finding text
    reproducible run to run (I-7).
    """
    t = normalize_sheet_id(target)
    best: str | None = None
    best_d: int | None = None
    for sid in sorted({normalize_sheet_id(i) for i in (ids or []) if normalize_sheet_id(i)}):
        d = levenshtein(t, sid)
        if best_d is None or d < best_d:
            best, best_d = sid, d
    return best, best_d


# --------------------------------------------------------------------------- #
# Negative corpus — tokens that must NEVER become sheet-reference findings (§17.3)
# --------------------------------------------------------------------------- #
#
# A candidate can be *shaped* like a sheet id yet be something else entirely: an
# equipment tag, a code/standard citation, a voltage, an RFI/submittal number, a
# project number, a dimension. These guards force such a token to IGNORE even when
# it happens to sit close to a real sheet id (the MALFORMED near-typo path), so a
# ``RFI-101`` is never "did you mean FP-101?". Belt-and-suspenders on top of the
# grammar gate: the grammar already rejects most, but a same-shape false friend
# needs an explicit veto.

# Code / standard bodies whose citations look like ids (NFPA 13, IBC-202, UL-300).
_STANDARD_BODIES = frozenset({
    "NFPA", "IBC", "IFC", "IRC", "IPC", "IMC", "IECC", "IFGC", "ASHRAE", "ASME",
    "ASTM", "ANSI", "UL", "FM", "IEEE", "NEC", "NEMA", "SMACNA", "AWWA", "AISC",
    "ACI", "AWS", "OSHA", "ADA", "ICC", "CBC", "CFC", "CMC", "CPC", "T24", "TITLE24",
})
# Transmittal / change-order / submittal prefixes (RFI-12, ASI-3, PR-04, CO-2).
_TRANSMITTAL_PREFIXES = frozenset({
    "RFI", "ASI", "PR", "CO", "CCD", "SK", "SI", "PCO", "COR", "SUB", "ADD", "BUL",
})
# A voltage (``480V`` / ``120/208V``) — a compact digits-then-letter shape.
_VOLTAGE_RE = re.compile(r"^\d{2,4}(?:/\d{2,4})?V$")
# A pure dimension token (``12'-6``, ``3/4"``) — starts with a digit, no letters.
_DIMENSION_RE = re.compile(r"^\d")


def is_non_sheet_reference(token: Any) -> bool:
    """True when a token is a known *non-sheet* reference (§17.3 negative corpus).

    Recognizes standard/code citations, transmittal numbers, voltages, and bare
    dimensions/room numbers so they can never be adjudicated as a stale or
    malformed sheet reference — even when their shape or edit distance would
    otherwise let them through. Purely structural; it never consults the set.
    """
    norm = normalize_sheet_id(token)
    if not norm:
        return True
    lead = _leading_letters(norm).upper()
    if lead and lead in _STANDARD_BODIES:
        return True
    # A hyphenated head whose first segment is a transmittal/standard prefix.
    head = norm.split("-", 1)[0].split(".", 1)[0]
    if head.upper() in _TRANSMITTAL_PREFIXES or head.upper() in _STANDARD_BODIES:
        return True
    if _VOLTAGE_RE.match(norm):
        return True
    # A token with no leading letter is a number/dimension/room — never a sheet id
    # in the strong-context adjudication (a bare "101" or "12-6" is not a sheet).
    if not lead and _DIMENSION_RE.match(norm):
        return True
    return False


# --------------------------------------------------------------------------- #
# Reference resolution policy (§17.3) — classify one harvested reference.
# --------------------------------------------------------------------------- #

# Resolution outcomes for one harvested reference against the set's inventory.
RESOLVED_IN_SET = "RESOLVED_IN_SET"    # target is a real sheet in the set
MISSING_FROM_SET = "MISSING_FROM_SET"  # matches the learned grammar but absent
MALFORMED = "MALFORMED"                # a near-typo of a real sheet id
IGNORE = "IGNORE"                      # not a sheet reference in this set's grammar

# A grammar-mismatching token this close to a real sheet id is treated as a
# malformed reference (a likely typo) rather than silently ignored.
_MALFORMED_MAX_DIST = 2
# A "closest in set" suggestion is only offered within this edit distance.
SUGGEST_MAX_DIST = 3


@dataclass(frozen=True)
class ReferenceResolution:
    """The outcome of classifying one harvested reference target (§17.3)."""

    status: str
    normalized: str
    closest: str | None = None
    distance: int | None = None

    @property
    def suggestion(self) -> str:
        """The parenthetical "(closest in set: …)" clause, or ``""``."""
        if self.closest and self.distance is not None and self.distance <= SUGGEST_MAX_DIST:
            return f" (closest in set: {self.closest})"
        return ""


def classify_reference(
    target: Any, ids: Iterable[Any], grammar: frozenset,
    *, low_confidence: bool = False,
) -> ReferenceResolution:
    """Classify a referenced id against the set's inventory + learned grammar.

    * present in the set → ``RESOLVED_IN_SET``;
    * matches the learned grammar but absent → ``MISSING_FROM_SET`` (with the
      closest in-set id when one is near);
    * a near-typo (edit distance ≤ 2) of a real sheet id → ``MALFORMED``;
    * anything else — a code token, tag, dimension, or an out-of-grammar token
      that is not a near-typo → ``IGNORE`` (never flagged).

    A known non-sheet token (:func:`is_non_sheet_reference`) is always
    ``IGNORE``, even when it is coincidentally close to a real sheet id, so the
    negative corpus can never become a finding. When ``low_confidence`` (a
    one-sheet set, or a set whose grammar could not be learned), the fuzzy
    ``MALFORMED`` near-typo path is suppressed — a thin grammar can't reliably
    guess that an out-of-grammar token is a typo of a real sheet — but a
    well-formed reference that matches the (single) learned convention and is
    absent is still ``MISSING_FROM_SET`` (its caller reports the confidence
    limitation on the finding). Exact matches always ``RESOLVED_IN_SET``.
    """
    norm = normalize_sheet_id(target)
    id_set = {normalize_sheet_id(i) for i in (ids or []) if normalize_sheet_id(i)}
    if norm in id_set:
        return ReferenceResolution(RESOLVED_IN_SET, norm)
    if is_non_sheet_reference(norm):
        return ReferenceResolution(IGNORE, norm)
    closest, dist = closest_in_set(norm, id_set)
    if matches_grammar(norm, grammar):
        return ReferenceResolution(MISSING_FROM_SET, norm, closest, dist)
    if low_confidence:
        # Too thin a grammar to trust a near-typo guess — leave an out-of-grammar
        # token alone rather than call it MALFORMED against a one-id convention.
        return ReferenceResolution(IGNORE, norm, closest, dist)
    if closest is not None and dist is not None and dist <= _MALFORMED_MAX_DIST:
        return ReferenceResolution(MALFORMED, norm, closest, dist)
    return ReferenceResolution(IGNORE, norm, closest, dist)


# --------------------------------------------------------------------------- #
# Inventory / ambiguity model — bind a reported id to exactly one source
# --------------------------------------------------------------------------- #

# Resolution outcomes for a model-reported sheet id against the set's inventory.
RESOLVED = "RESOLVED"      # exactly one in-set candidate — safe to bind
UNBOUND = "UNBOUND"        # zero candidates — leave it unplaced
AMBIGUOUS = "AMBIGUOUS"    # >1 distinct candidate — never ink every one


@dataclass(frozen=True)
class SheetIdResolution:
    """The outcome of resolving one reported id against a :class:`SheetIdIndex`.

    ``value`` is the single bound payload only when ``status == RESOLVED``;
    ``candidates`` carries every payload the (normalized) id mapped to, so an
    ambiguous resolution can be reported precisely rather than silently guessed.
    """

    status: str
    normalized: str
    value: Any = None
    candidates: tuple = ()


class SheetIdIndex:
    """A ``normalized-sheet-id → [payload]`` inventory with safe resolution.

    Built from ``(sheet_id, payload)`` pairs (the payload is whatever the caller
    needs bound back — a ``SheetGeometry``, a ``SheetRef``, a source id). Two
    different sources that normalize to the *same* id both land under that key, so
    :meth:`resolve` can report the collision as ``AMBIGUOUS`` instead of letting
    a first-wins map silently shadow one of them (§10.4 / §16.1). Identical
    payloads under one key collapse (a source listed twice is not ambiguous).
    """

    def __init__(self, entries: Iterable[tuple[Any, Any]] = ()) -> None:
        self._by_id: dict[str, list] = {}
        for sheet_id, payload in entries:
            self.add(sheet_id, payload)

    def add(self, sheet_id: Any, payload: Any) -> str:
        """Register one ``(sheet_id, payload)``; returns the normalized key.

        A blank/normalization-empty id is ignored (returns ``""``). A payload
        already present under the key is not duplicated (so re-adding the same
        source is idempotent and does not fabricate ambiguity).
        """
        key = normalize_sheet_id(sheet_id)
        if not key:
            return ""
        bucket = self._by_id.setdefault(key, [])
        if not any(existing is payload or existing == payload for existing in bucket):
            bucket.append(payload)
        return key

    @property
    def ids(self) -> frozenset[str]:
        """Every normalized id in the inventory."""
        return frozenset(self._by_id)

    def is_ambiguous(self, sheet_id: Any) -> bool:
        return len(self._by_id.get(normalize_sheet_id(sheet_id), ())) > 1

    def resolve(self, reported_id: Any) -> SheetIdResolution:
        """Resolve a model-reported id to exactly one payload, or explain why not.

        ``RESOLVED`` with the single ``value`` when the normalized id maps to one
        distinct payload; ``UNBOUND`` when it maps to none; ``AMBIGUOUS`` (with
        the full ``candidates``) when it maps to more than one. The caller never
        gets a silently-chosen winner for an ambiguous id.
        """
        key = normalize_sheet_id(reported_id)
        bucket = tuple(self._by_id.get(key, ()))
        if len(bucket) == 1:
            return SheetIdResolution(RESOLVED, key, value=bucket[0], candidates=bucket)
        if not bucket:
            return SheetIdResolution(UNBOUND, key, candidates=())
        return SheetIdResolution(AMBIGUOUS, key, candidates=bucket)
