"""Deterministic arithmetic auditor (Phase 14) — zero API, host does the math.

A vision model reading a drawing is at its worst doing mental arithmetic on a
table it just transcribed: the prototype watched one misread a flow-test total
(``540`` became ``660``) and, separately, miss a ``+30%`` design-area increase on
one dry-pipe row while its siblings had it. Both are *arithmetic* errors, and the
fix is to never trust the model's math.

So the reviewer (critique / cross-sheet QC) does not calculate — it only
**transcribes**: it reports the numbers it read and how they are supposed to
relate ("these terms should ``sum`` to this total"; "base area × 1.3 should equal
the stated design area") as :class:`~drawing_analyzer.models.NumericClaim` objects.
This module then **computes the relationship itself** — parsing every term to an
exact :class:`~decimal.Decimal` and adding / multiplying with the standard library,
never :func:`eval`, never the model's answer — and raises a
:class:`~drawing_analyzer.models.Finding` only when the numbers genuinely don't
add up. Relationships that check out are counted (surfaced in the report as
"N numeric relationships checked ✓").

The *operation* is always host-deterministic, but the numbers it operated on may
have been misread. Phase 25 §17.5 makes that distinction explicit: a mismatch is
trusted (``verification.status="DETERMINISTIC"``, ``operand_origin=TEXT_EXTRACTED``)
only when the claim's own verbatim quote independently carries every operand;
otherwise the terms were model-transcribed (``operand_origin=MODEL_TRANSCRIBED``)
and the mismatch stays ``UNCERTAIN`` so the crop verifier confirms the numbers
before it inks as ground truth. ``computation_method`` is always
``HOST_DETERMINISTIC``. Every finding is anchored on the sheet via the claim's
verbatim quote.

PDF-engine-free (I-5): it reuses the pure anchor resolver and word helpers; the
pipeline owns rendering.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any, Iterable

from ..models import (
    HOST_DETERMINISTIC,
    MODEL_TRANSCRIBED,
    TEXT_EXTRACTED,
    Finding,
    NumericClaim,
    Verification,
    source_page_key,
)
from .references import detect_sheet_id, _wtext

# --------------------------------------------------------------------------- #
# Number parsing — tolerant of how numbers appear on drawings, with NO eval.
# --------------------------------------------------------------------------- #

# A US thousands separator: a comma between a digit and a 3-digit group (so
# "1,200" and "1,200,000" lose their commas, but "1,20" — never a thousands
# grouping — is left alone rather than silently mangled). Applied before parsing.
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")

# A mixed number: whole and fraction separated by whitespace OR a hyphen — the two
# ways "two and a half inches" is written on a drawing ("2 1/2\"" and "2-1/2\"").
# The sign is captured on its own so "-2-1/2" negates the whole magnitude. The
# hyphen separator is only read as a mixed-number join here (between a whole and a
# ``d/d`` fraction); a leading "-1/2" has no whole part and falls through to the
# simple-fraction rule as negative one-half.
_MIXED_FRACTION_RE = re.compile(r"^([-+]?)(\d+)[\s\-]+(\d+)\s*/\s*(\d+)")
_SIMPLE_FRACTION_RE = re.compile(r"^([-+]?)(\d+)\s*/\s*(\d+)")
# A plain integer or decimal at the start of the token ("165 psi" → 165,
# "0.20 gpm/ft²" → 0.20). Units, symbols, and trailing text are ignored.
_PLAIN_NUMBER_RE = re.compile(r"^[-+]?(?:\d+(?:\.\d+)?|\.\d+)")


def parse_number(value: Any) -> Decimal | None:
    """Parse one raw term into an exact :class:`~decimal.Decimal`, or ``None``.

    Accepts JSON numbers directly and strings the way a drawing writes them:
    thousands commas (``"1,950"``), units and symbols (``"165 psi"``,
    ``"0.20 gpm/ft²"``), and fractions (``"1/2"``, ``"2 1/2"``, ``"2-1/2\\""``).
    Booleans are rejected (``True`` is not the number 1 here). Returns ``None`` for
    anything with no leading number — the claim it belongs to is then skipped, not
    guessed at. Never evaluates the string as code.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Via ``str`` so 0.1 parses as exactly 0.1, not its binary-float shadow.
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        return None
    return _parse_number_str(value)


def _parse_number_str(raw: str) -> Decimal | None:
    s = _THOUSANDS_RE.sub("", raw.strip())
    if not s:
        return None
    try:
        m = _MIXED_FRACTION_RE.match(s)
        if m:
            sign, whole, num, den = m.group(1), m.group(2), m.group(3), m.group(4)
            if int(den) == 0:
                return None
            val = Decimal(whole) + Decimal(num) / Decimal(den)
            return -val if sign == "-" else val
        m = _SIMPLE_FRACTION_RE.match(s)
        if m:
            sign, num, den = m.group(1), m.group(2), m.group(3)
            if int(den) == 0:
                return None
            val = Decimal(num) / Decimal(den)
            return -val if sign == "-" else val
        m = _PLAIN_NUMBER_RE.match(s)
        if m:
            return Decimal(m.group(0))
    except (InvalidOperation, DivisionByZero, ValueError):
        return None
    return None


# --------------------------------------------------------------------------- #
# Tolerance + severity — a match allows for the rounding a drawing prints.
# --------------------------------------------------------------------------- #

# A claim "matches" within a **relative** slack of the computed value — drawings
# round (a design area may print 1,950 for a 1,948.5 computation). The relative
# rule is magnitude-aware by construction, so it never hides a meaningful small-
# value difference the way a blanket absolute tolerance did (§17.5): under the old
# ``abs <= 0.5`` rule a density ``0.2 + 0.2`` printed as ``0.5`` (actual 0.4, a 20%
# error) falsely matched. A tiny absolute floor is retained only to absorb exact-
# value rounding of a near-zero computed result (and the ``expected == 0`` case
# where a relative error is undefined) — far too small to swallow a real gap.
_DEFAULT_REL_TOL = Decimal("0.01")   # 1%
_ABS_FLOOR = Decimal("0.01")
# Relative-error thresholds that grade a mismatch's severity.
_SEVERITY_HIGH_REL = Decimal("0.10")
_SEVERITY_MEDIUM_REL = Decimal("0.03")


def _rel_tolerance() -> Decimal:
    """The relative match tolerance (``DRAWING_ANALYZER_ARITHMETIC_REL_TOL``)."""
    raw = os.environ.get("DRAWING_ANALYZER_ARITHMETIC_REL_TOL")
    if raw and raw.strip():
        try:
            v = Decimal(raw.strip())
            if v >= 0:
                return v
        except InvalidOperation:
            pass
    return _DEFAULT_REL_TOL


def _relative_error(actual: Decimal, expected: Decimal) -> Decimal:
    denom = max(abs(actual), abs(expected))
    if denom == 0:
        return Decimal(0)
    return abs(actual - expected) / denom


def _is_match(actual: Decimal, expected: Decimal) -> bool:
    if abs(actual - expected) <= _ABS_FLOOR:
        return True
    return _relative_error(actual, expected) <= _rel_tolerance()


# --------------------------------------------------------------------------- #
# Operand provenance (§17.5) — did the numbers come off the sheet, or the model?
# --------------------------------------------------------------------------- #

# Number-shaped substrings in a quote, tokenized the SAME way :func:`parse_number`
# reads an operand so the two never disagree (§17.5): a **mixed** number
# (``2 1/2`` / ``2-1/2``) first, then a **simple** fraction (``1/2``), then a plain
# integer/decimal with optional thousands commas. Alternation is longest-first so
# ``2 1/2`` is one token (2.5), not ``2`` and ``1/2``. Each match is handed to
# :func:`parse_number` for the exact-decimal compare.
_NUM_IN_TEXT_RE = re.compile(
    r"[-+]?\d+[\s-]+\d+\s*/\s*\d+"      # mixed number: 2 1/2, 2-1/2
    r"|[-+]?\d+\s*/\s*\d+"             # simple fraction: 1/2
    r"|[-+]?\d[\d,]*(?:\.\d+)?"        # plain / decimal / thousands: 1,200  0.20
)


def _numbers_in_text(text: str) -> list[Decimal]:
    out: list[Decimal] = []
    for m in _NUM_IN_TEXT_RE.finditer(str(text or "")):
        v = parse_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _operands_supported(terms: list[Decimal], expected: Decimal, quote: str) -> bool:
    """True when EVERY operand (terms + expected) appears in the claim's quote.

    The independent-validation test for :data:`TEXT_EXTRACTED` provenance (§17.5):
    the model's own verbatim quote must literally carry each number the host
    computed with. A column-sum whose addends live in a table the quote only
    summarizes fails this — correctly — and stays model-transcribed / UNCERTAIN,
    so a misread term is caught by the crop verifier rather than trusted.
    """
    present = _numbers_in_text(quote)
    if not present:
        return False
    for n in [*terms, expected]:
        if not any(p == n for p in present):
            return False
    return True


def _severity_for(actual: Decimal, expected: Decimal) -> str:
    rel = _relative_error(actual, expected)
    if rel >= _SEVERITY_HIGH_REL:
        return "high"
    if rel >= _SEVERITY_MEDIUM_REL:
        return "medium"
    return "low"


def _compute(kind: str, terms: list[Decimal]) -> Decimal | None:
    """Combine ``terms`` per ``kind``; ``None`` if there aren't enough of them.

    ``sum`` needs at least one term; ``product`` / ``factor`` need at least two (a
    factor is a product where one term is the multiplier, e.g. area × 1.3).
    """
    if kind == "sum":
        if not terms:
            return None
        total = Decimal(0)
        for t in terms:
            total += t
        return total
    if kind in ("product", "factor"):
        if len(terms) < 2:
            return None
        prod = Decimal(1)
        for t in terms:
            prod *= t
        return prod
    return None


def _fmt(value: Decimal) -> str:
    """Human-readable decimal: trims a trailing ``.0`` / exponent noise."""
    v = value.normalize()
    # ``normalize`` can yield exponent form (e.g. 1.95E+3); expand it back.
    if v == v.to_integral_value():
        return str(v.quantize(Decimal(1)))
    return str(v)


# --------------------------------------------------------------------------- #
# Auditing
# --------------------------------------------------------------------------- #


@dataclass
class ArithmeticResult:
    """The arithmetic auditor's output: findings plus the checked/passed tally."""

    findings: list[Finding] = field(default_factory=list)
    checked: int = 0       # claims the host could actually compute
    matched: int = 0       # of those, the ones that added up
    mismatched: int = 0    # of those, the ones that did not (== len(findings))
    unusable: int = 0      # claims dropped (bad kind / unparseable numbers)


def _claim_dedup_key(claim: NumericClaim) -> tuple:
    # source_page_key (not bare source_name) so two identical claims from
    # different same-basename inputs are NOT merged into one (DA-001).
    return (
        source_page_key(claim),
        (claim.sheet_id or "").strip().upper(),
        (claim.kind or "").strip().lower(),
        (claim.quote or "").strip(),
        tuple(str(t) for t in claim.terms),
        str(claim.expected),
    )


def _build_maps(rendered_sheets: list[Any]) -> tuple[dict, dict]:
    """``(by_key, by_id)`` maps: ``source_page_key`` → geom and id → geom."""
    by_key: dict[tuple, Any] = {}
    by_id: dict[str, Any] = {}
    for geom in rendered_sheets:
        ref = getattr(geom, "ref", None)
        if ref is not None:
            by_key[source_page_key(ref)] = geom
        sid = detect_sheet_id(geom)
        if sid and sid not in by_id:
            by_id[sid] = geom
    return by_key, by_id


def _resolve_geometry(claim: NumericClaim, by_key: dict, by_id: dict) -> Any:
    """The sheet a claim belongs to: the emitting sheet when known, else by id."""
    if claim.source_id or claim.source_name:
        geom = by_key.get(source_page_key(claim))
        if geom is not None:
            return geom
    return by_id.get((claim.sheet_id or "").strip().upper())


def audit_arithmetic(
    claims: Iterable[NumericClaim], rendered_sheets: Iterable[Any]
) -> ArithmeticResult:
    """Check every numeric claim's arithmetic; return findings + the tally.

    Deterministic and side-effect-free. Each mismatch becomes a
    ``DETERMINISTIC``-verified :class:`~drawing_analyzer.models.Finding`
    (``category="conflict"``) anchored on its sheet via the claim's verbatim quote
    (the pure anchor resolver — ``UNANCHORED`` if the quote isn't on the sheet,
    the honest signal). Claims whose numbers can't be parsed, or whose kind is
    unknown, are counted ``unusable`` and dropped — never guessed at. Duplicate
    claims (the critique runs twice) are collapsed before checking so the tally
    isn't double-counted.
    """
    sheets = list(rendered_sheets)
    by_key, by_id = _build_maps(sheets)

    result = ArithmeticResult()
    seen: set[tuple] = set()
    to_anchor: dict[tuple, list[Finding]] = {}

    for claim in claims:
        if (claim.kind or "").strip().lower() not in ("sum", "product", "factor"):
            result.unusable += 1
            continue
        key = _claim_dedup_key(claim)
        if key in seen:
            continue
        seen.add(key)

        kind = claim.kind.strip().lower()
        terms = [parse_number(t) for t in claim.terms]
        expected = parse_number(claim.expected)
        if expected is None or any(t is None for t in terms):
            result.unusable += 1
            continue
        actual = _compute(kind, terms)  # type: ignore[arg-type]
        if actual is None:
            result.unusable += 1
            continue

        result.checked += 1
        if _is_match(actual, expected):
            result.matched += 1
            continue

        result.mismatched += 1
        geom = _resolve_geometry(claim, by_key, by_id)
        ref = getattr(geom, "ref", None)
        source_name = ref.source_name if ref is not None else (claim.source_name or "")
        source_id = ref.source_id if ref is not None else (claim.source_id or "")
        page_index = ref.page_index if ref is not None else int(claim.page_index or 0)
        sheet_id = claim.sheet_id or (detect_sheet_id(geom) if geom is not None else "") or source_name

        op = "sum of" if kind == "sum" else "product of"
        term_str = ", ".join(_fmt(t) for t in terms)  # type: ignore[arg-type]
        note_tail = f" {claim.note.strip()}" if claim.note.strip() else ""

        # Operand provenance (§17.5): the host *operation* is always deterministic,
        # but the numbers it used are trusted only when the sheet's own quoted text
        # independently carries every one of them (TEXT_EXTRACTED). Otherwise the
        # terms were model-transcribed, so the mismatch stays UNCERTAIN and is
        # crop-verified — a misread term must never ink as trusted ground truth.
        text_extracted = _operands_supported(
            terms, expected, claim.quote or ""  # type: ignore[arg-type]
        )
        origin = TEXT_EXTRACTED if text_extracted else MODEL_TRANSCRIBED
        status = "DETERMINISTIC" if text_extracted else "UNCERTAIN"
        provenance = (
            "operands text-extracted from the sheet quote"
            if text_extracted
            else "host-computed from model-transcribed terms — verify against the sheet"
        )
        finding = Finding(
            sheet_id=sheet_id,
            source_name=source_name,
            source_id=source_id,
            page_index=page_index,
            category="conflict",
            severity=_severity_for(actual, expected),
            text=(
                f"Arithmetic does not check out: the {op} {term_str} is "
                f"{_fmt(actual)}, but the sheet states {_fmt(expected)}.{note_tail}"
            ).strip(),
            source_quote=claim.quote or "",
            refs=[],
            verification=Verification(
                status=status,
                note=f"computed {op} terms = {_fmt(actual)}; stated = {_fmt(expected)} "
                     f"({provenance})",
                computation_method=HOST_DETERMINISTIC,
                operand_origin=origin,
            ),
            sources=["auditor_arithmetic"],
        )
        result.findings.append(finding)
        if geom is not None and (claim.quote or "").strip():
            to_anchor.setdefault(source_page_key(finding), []).append(finding)

    # Anchor the mismatch findings via their quotes, grouped per sheet. Reuses the
    # pure resolver (EXACT/FUZZY/TILE/UNANCHORED) exactly like model findings.
    if to_anchor:
        from ..anchor import resolve_anchors

        geom_by_key = {source_page_key(g.ref): g for g in sheets if getattr(g, "ref", None)}
        for key, group in to_anchor.items():
            geom = geom_by_key.get(key)
            if geom is not None:
                resolve_anchors(group, geom)
    return result
