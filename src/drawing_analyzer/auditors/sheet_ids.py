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

Scope for Phase 24 (§16.0): normalization, project-prefix-aware discipline
detection, a broad candidate lexer for the common id families (hyphenated,
compact, dotted, detail-bubble), and the inventory/ambiguity resolver used to
bind a model-reported id to exactly one source (or leave it explicitly unbound /
ambiguous — never "ink every candidate"). Phase 25 (§17.2) expands this into the
full reference grammar and negative corpus and routes every auditor through it;
this module is deliberately shaped so that expansion is additive.
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
# strips the zero-width / soft-hyphen artifacts that split tokens. (Mirrors
# ``auditors.references._normalize_text``; Phase 25 unifies the two.)
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
