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
only when the sheet independently prints every operand; otherwise the terms were
model-transcribed (``operand_origin=MODEL_TRANSCRIBED``) and the mismatch stays
``UNCERTAIN`` so the crop verifier confirms the numbers before it inks as ground
truth. ``computation_method`` is always ``HOST_DETERMINISTIC``. Every finding is
anchored on the sheet via the claim's verbatim quote.

"Prints every operand" is decided **after** that anchoring (remediation WP-07.1,
review N3): the claim must resolve to a sheet, its quote must anchor there EXACT
or FUZZY by a numerically vetoed method (:func:`~drawing_analyzer.anchor.numbers_grounded`),
and the terms and the stated value together must fit the numbers that both the
quote and the sheet's own words under the matched span print, one occurrence
each (:func:`_operands_grounded`). It used to be decided from the quote string
alone, before anchoring, by membership: one printed ``20`` supported any number
of transcribed ``20`` operands, and a quote the sheet does not carry, or a claim
on no sheet at all, was trusted as readily as one the sheet prints.

Two more conditions since remediation WP-07.2 (review A8), each decided with
the owner:

* **Only a token that is one value is a number** (:func:`parse_number`,
  :func:`_numbers_in_text`). The digits of a tag or sheet id (``FP101``,
  ``M-101``, ``AHU-2``) are never a number, and a hyphen after a letter is
  never a minus sign. Letters after a number are its unit (``20A``,
  ``150GPM``) unless digits follow them directly (``24x12``, ``2P20A``,
  ``1e3``): scientific notation is rejected, never truncated, so a term
  spelled ``1e3`` makes its claim unusable.
* **The relationship is stated on the sheet** (:func:`_relationship_grounded`).
  The quote and the sheet's words under the span must each print the claim as
  one equation: its operation (``+`` for a sum, ``x``/``×``/``*`` for a
  product), its terms as the operands and its stated value as the result. A
  sum transcribed from a product, or a total put among the terms, prints every
  operand and was trusted anyway.

A mismatch that fails any condition stays model-transcribed and ``UNCERTAIN``.
The host never learns roles from the model: the claims contract is unchanged
(plan WP-07 step 4).

PDF-engine-free (I-5): it reuses the pure anchor resolver and word helpers; the
pipeline owns rendering.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import MAX_EMAX, MIN_EMIN, Context, Decimal, DivisionByZero, InvalidOperation
from typing import Any, Iterable

from .sheet_ids import normalize_sheet_id
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

# What a parsed number may be FOLLOWED by and still be the whole quantity: a unit,
# a symbol, punctuation, whitespace and another number, nothing. What it may not
# be followed by is a **binder** — a separator that joins another digit to the one
# just read, meaning the token was never a single value and taking the leading run
# silently mangles it.
#
# A binder must be **tight**: no whitespace on either side of it. Whitespace is
# what separates two quantities from one malformed quantity, and both halves of
# that matter. ``20  20  20  TOTAL 540`` is a column of four numbers, and denying
# the first would gut the flow-test case the auditor exists for; ``0.5, 1.5,
# TOTAL 2.0`` and ``10 , 20 , 30`` are ordinary comma-separated operand lists, and
# an earlier draft of this rule allowed whitespace around the separator and so
# dropped their leading operands — which does not produce a wrong answer, but
# downgrades a text-extracted mismatch to MODEL_TRANSCRIBED / UNCERTAIN and sends
# it to the crop verifier for nothing.
#
# ``_THOUSANDS_RE`` above already declines to strip a comma that is not a
# thousands grouping, precisely so ``"1,20"`` is "left alone rather than silently
# mangled" — and then ``_PLAIN_NUMBER_RE`` truncated it to 1 anyway, mangling it.
# Same class: ``12'-6"`` is twelve feet six, not 12, and the old parse fed 12 to a
# host computation that then inked its result as ground truth.
#
# ``%`` is rejected outright (§17.5, item 25d). A percent is a *ratio*, not the
# quantity, so ``1500 SF + 30% = 1950 SF`` is not "the sum of 1500 and 30". Worse,
# the bare ``30`` appearing literally in the quote is what let such a claim clear
# :func:`_operands_supported` and ink as DETERMINISTIC / TEXT_EXTRACTED. Rejecting
# it makes the claim *unusable* — reported as unchecked, never as a mismatch.
#
# Letters glued after the number are its unit (``20A``, ``150GPM``, ``12IN``)
# unless more digits follow them directly (remediation WP-07.2, review A8): then
# the token is one identifier or compound, never the number it starts with.
# ``1e3`` is not 1 (scientific notation is rejected, not read: on a drawing
# ``2E1`` is as likely a panel as an exponent), ``24x12`` is a duct size, not 24,
# ``2P20A`` a breaker, ``10A1`` a tag. Accepted cost: an ASCII-squared ``100m2``
# is refused too (``100 m²`` and ``100 m2`` still read 100). The same holds for
# ``×`` and the fraction slash between digits, a Unicode dash anywhere ``-``
# binds (``12'–6"``), and a vulgar fraction glued on (``2½"`` is not 2).
#
# No ``^``: this is applied with ``.match(s, pos)``, which already anchors at
# ``pos`` — while ``^`` would keep anchoring to the real start of the string and
# so never fire on a tail at all.
_NUMERIC_TAIL_RE = re.compile(
    r"""(?:
          ['"]? [,.\-\u2010-\u2015\u2212\ufe58\ufe63\uff0d] \d
                              # 12,5 · 1.2.3 · 12'-6" · 12-6 · 12–6 (tight only)
        | \s* %               # 30% · 30 %   — a ratio however it is spaced
        | [^\W\d_]+ \d        # 1e3 · 24x12 · 2P20A · 10A1 · 100m2
        | [eE] [-+] \d        # 2.5e-2 · 1E+3 — an exponent
        | [\u00d7\u2044\u2215] \d   # 24×12 · 1⁄2 (a size; a fraction slash)
        | [\u00bc-\u00be\u2150-\u215e]  # 2½ — a vulgar fraction glued on
    )""",
    re.VERBOSE,
)

# The Unicode dashes ``anchor._normalize`` folds to ``-`` (its ``_CHAR_FOLD``):
# a hyphen, never a sign this scanner can read (``[-+]`` is ASCII only).
_UNICODE_DASHES = frozenset("\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d")


def _tail_denies(s: str, end: int) -> bool:
    """Whether what follows the match at ``end`` disqualifies the parse."""
    return _NUMERIC_TAIL_RE.match(s, end) is not None


def _head_denies(s: str, start: int) -> bool:
    """Whether the character immediately BEFORE a match binds it to a number.

    The mirror of :func:`_tail_denies`, and needed for the same reason. Scanning
    ``12'-6"`` linearly, the tail rule correctly refuses ``12`` — and the scan
    then resumes past it and offers ``-6`` as a free-standing number. It is not
    one; it is the inches half of a single dimension, and admitting it would put
    a quantity in the "present in the quote" set that the quote never states.
    That set is exactly what promotes a claim to TEXT_EXTRACTED / DETERMINISTIC,
    so a phantom entry in it launders model arithmetic into ground truth.

    A letter glued before the match makes it a tag's or sheet id's digits
    (remediation WP-07.2, review A8): ``FP101``, ``A1.01``, and ``M-101`` /
    ``AHU-2``, where the hyphen after a letter joins the tag and is never a
    minus sign (``M-101 P-3 AHU-2`` scanned as -101, -3 and -2). A ``+`` glued
    to a letter stays an operator (``250GPM+100GPM`` still reads 100), except
    as an exponent's sign (``1E+3``). A Unicode dash binds too (``M–101``, and
    ``−5``, whose sign the ASCII ``[-+]`` cannot read), as do a fraction slash
    and a ``×`` with a digit before it (``24×12``).

    Deliberately does NOT skip whitespace: a separating space means the two are
    different quantities, so ``PIPE 2" 150 PSI`` still yields 150, and
    ``RISER 3`` reads 3 (a label's number is still a number; the relationship
    check decides whether it is an operand).
    """
    if start <= 0:
        return False
    prev = s[start - 1]
    if prev in "'\",." or prev.isdigit():
        return True
    if prev.isalpha():
        exponent = prev in "eE" and start >= 2 and s[start - 2].isdigit()
        return s[start] != "+" or exponent
    if prev in _UNICODE_DASHES or prev in "\u2044\u2215":
        return True
    return prev == "\u00d7" and start >= 2 and s[start - 2].isdigit()


def parse_number(value: Any) -> Decimal | None:
    """Parse one raw term into an exact :class:`~decimal.Decimal`, or ``None``.

    Accepts JSON numbers directly and strings the way a drawing writes them:
    thousands commas (``"1,950"``), units and symbols (``"165 psi"``,
    ``"0.20 gpm/ft²"``, ``"20A"``), and fractions (``"1/2"``, ``"2 1/2"``,
    ``"2-1/2\\""``). Booleans are rejected (``True`` is not the number 1 here).
    Returns ``None`` for anything with no leading number, and for a leading
    number that is not the whole value (``_NUMERIC_TAIL_RE``: ``"12'-6\\""``,
    ``"30%"``, and since remediation WP-07.2 ``"1e3"``, ``"24x12"``,
    ``"2P20A"``) — the claim it belongs to is then skipped, not guessed at.
    Never evaluates the string as code.
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
            if _tail_denies(s, m.end()):
                return None
            sign, whole, num, den = m.group(1), m.group(2), m.group(3), m.group(4)
            if int(den) == 0:
                return None
            val = Decimal(whole) + Decimal(num) / Decimal(den)
            return -val if sign == "-" else val
        m = _SIMPLE_FRACTION_RE.match(s)
        if m:
            if _tail_denies(s, m.end()):
                return None
            sign, num, den = m.group(1), m.group(2), m.group(3)
            if int(den) == 0:
                return None
            val = Decimal(num) / Decimal(den)
            return -val if sign == "-" else val
        m = _PLAIN_NUMBER_RE.match(s)
        if m:
            if _tail_denies(s, m.end()):
                return None
            return Decimal(m.group(0))
    except (InvalidOperation, DivisionByZero, ValueError):
        return None
    return None


# --------------------------------------------------------------------------- #
# Claim identity — what "the same claim" means (remediation WP-03.3, review B7)
# --------------------------------------------------------------------------- #

# The operation the host performs for each claim kind (see :func:`_compute`):
# a ``factor`` is a product whose second term is the multiplier, and the finding
# text says "product of" for both.
_CLAIM_OPERATION = {"sum": "sum", "product": "product", "factor": "product"}

# The scheme of :func:`arithmetic_claim_discriminator`. Versioned so a later
# change to the canonical form, or a second producer of discriminators, can
# never read an arithmetic one as its own.
ARITHMETIC_CLAIM_SCHEME = "arithmetic/1"


def claim_operation(kind: Any) -> str:
    """The host operation a claim ``kind`` names; an unknown kind, lowercased."""
    k = str(kind or "").strip().lower()
    return _CLAIM_OPERATION.get(k, k)


def canonical_decimal(value: Decimal) -> str:
    """One spelling per value: ``20``, ``20.0`` and ``2E+1`` all read ``"20"``.

    Exact. Trailing zeros are stripped at the value's own precision, never
    rounded at the decimal context's 28 digits, so two different long numbers
    stay different. Zero has one spelling whatever its sign. Never raises: the
    exponent range is unbounded, because two of the dedups that use this have
    no per-claim guard.
    """
    if not value.is_finite():
        return str(value)
    if value.is_zero():
        return "0"
    digits = len(value.as_tuple().digits)
    exact = Context(prec=digits, Emax=MAX_EMAX, Emin=MIN_EMIN)
    return format(value.normalize(exact), "f")


def claim_value_key(value: Any) -> str:
    """One raw claim term, or a stated value, as it counts for "the same claim".

    Parsed with :func:`parse_number`, so ``20``, ``"20.0"``, the JSON float
    ``20.0`` and ``"1,200"`` against ``1200`` agree, and spelled by
    :func:`canonical_decimal`. A value that does not parse keeps its raw
    spelling behind a ``raw:`` tag, which no parsed value can carry: an
    unparseable term never collapses two different claims, and never equals a
    number. (Before WP-03.3 every claim dedup keyed on ``str(term)``, so
    ``20`` and ``"20.0"`` were two claims, checked and counted twice.)
    """
    parsed = parse_number(value)
    if parsed is None:
        return "raw:" + str(value)
    return canonical_decimal(parsed)


def claim_content_key(kind: Any, terms: Any, expected: Any) -> tuple:
    """What a claim asserts: ``(operation, terms, stated value)``, canonical.

    The terms are a sorted multiset: both operations the host performs commute,
    so two reads that transcribe one row in a different order make one claim.
    The one canonical form behind every claim dedup (this module's
    ``_claim_dedup_key``, ``critique._dedup_claims``, ``cross_qc._dedup_claims``)
    and behind :func:`arithmetic_claim_discriminator`, so the dedups and the
    ledger can never disagree about which values are the same claim.
    """
    return (
        claim_operation(kind),
        tuple(sorted(claim_value_key(t) for t in list(terms or []))),
        claim_value_key(expected),
    )


def arithmetic_claim_discriminator(kind: Any, terms: Any, expected: Any) -> str:
    """The :attr:`~drawing_analyzer.models.Finding.claim_discriminator` of a
    mismatch: ``"arithmetic/1:sum:20,20,20=540"``.

    The scheme, then :func:`claim_content_key`. Only ever built for a claim the
    host could compute, whose every value parsed, so no part holds a separator.
    Two mismatches on one table row quote the same string; this is what tells
    them apart, in the ledger's merge (``critique._is_duplicate``) and in the
    finding's id (review B7).
    """
    operation, term_keys, stated = claim_content_key(kind, terms, expected)
    return f"{ARITHMETIC_CLAIM_SCHEME}:{operation}:{','.join(term_keys)}={stated}"


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


def _scan_numbers(text: str) -> list[tuple[int, int, Decimal, str]]:
    """Every number ``text`` prints: ``(start, end, value, matched text)``.

    The head/tail rules are applied HERE, against the surrounding text, rather
    than left to ``parse_number`` — which is handed the matched substring alone
    and so cannot see what bound it. Without this the two disagree in exactly
    the direction that matters: ``parse_number("30%")`` refuses, while the
    scanner still reported a bare 30 as "present in the quote", which is the
    whole basis of the TEXT_EXTRACTED promotion. The same goes for a tag's
    digits (``FP101``), which only the text before them can reveal.
    """
    s = str(text or "")
    out: list[tuple[int, int, Decimal, str]] = []
    for m in _NUM_IN_TEXT_RE.finditer(s):
        if _head_denies(s, m.start()) or _tail_denies(s, m.end()):
            continue
        v = parse_number(m.group(0))
        if v is not None:
            out.append((m.start(), m.end(), v, m.group(0)))
    return out


def _numbers_in_text(text: str) -> list[Decimal]:
    """The values of :func:`_scan_numbers`, in reading order."""
    return [value for _start, _end, value, _raw in _scan_numbers(text)]


def _operands_supported(
    terms: list[Decimal], expected: Decimal, printed: Counter
) -> bool:
    """True when every operand has its **own** printed occurrence.

    ``printed`` counts the printed numbers by value (``20`` and ``20.0`` are one
    value). The terms and the stated value are counted together, so each one
    uses up an occurrence: one printed ``20`` supports one ``20`` operand, not
    three (remediation WP-07.1, review N3: ``sum [20, 20, 20] = 40`` over
    ``20 + 20 = 40`` was trusted), and the stated value cannot reuse a term's
    number (``20 + 30`` states no total of 20). Genuinely repeated values are
    fine: ``20 20 20 TOTAL 540`` prints three.

    A column sum whose addends live in a table the quote only summarizes fails
    this, correctly, and stays model-transcribed / UNCERTAIN, so a misread term
    is caught by the crop verifier rather than trusted.
    """
    if not printed:
        return False
    need = Counter([*terms, expected])
    return all(printed[value] >= count for value, count in need.items())


def _operands_grounded(
    terms: list[Decimal], expected: Decimal, quote: str, matched_text: str
) -> bool:
    """Whether the sheet's own text, where the quote anchored, prints every operand.

    ``matched_text`` is the sheet's words under the span the quote matched
    (:func:`~drawing_analyzer.anchor.resolve_anchors`). An operand counts where
    **both** the quote and those words print it, per value the smaller count:
    the model's quote is its stated evidence, and the words are what the sheet
    prints there. Either alone trusts too much. The quote alone takes the
    model's spelling (a quote that starts inside ``2-1/2"`` reads a ``1/2`` the
    sheet never printed); the words alone read numbers the quote left out, and
    read the sheet's non-ASCII forms with ASCII rules (an en-dash ``12'–6"``
    becomes a ``12`` and a ``6``).
    """
    printed = Counter(_numbers_in_text(quote)) & Counter(_numbers_in_text(matched_text))
    return _operands_supported(terms, expected, printed)


# --------------------------------------------------------------------------- #
# The relationship (remediation WP-07.2, review A8): does the sheet print the
# claim's operation, with its terms as the operands and its value as the result?
# --------------------------------------------------------------------------- #

# The word that marks a result: TOTAL, TOTALS, SUBTOTAL; a whole word.
_TOTAL_RE = re.compile(r"(?<![^\W\d_])(?:SUB)?TOTALS?(?![^\W\d_])", re.IGNORECASE)
# What may sit between two numbers without saying anything about how they
# relate: letters (units, labels), whitespace, and this punctuation.
_GAP_FILLER = frozenset(
    ",;:.'\"()[]#/-_\u00b2\u00b3\u00b0\u2018\u2019\u201c\u201d\u2032\u2033"
)
# A whitespace-separated token that is an operation the claims contract cannot
# express: a subtraction or a division.
_OTHER_OPERATOR_TOKENS = frozenset({"-", "/", *_UNICODE_DASHES})
_DIGIT_RE = re.compile(r"\d")
_PLUS, _TIMES, _OTHER = "+", "x", "other"


def _gap_marks(gap: str) -> frozenset:
    """What the text between two numbers says about how they relate.

    ``=`` and ``total`` mark the next number as a result. ``+`` and ``x``
    (``x``, ``×`` or ``*``) are the two operations the host computes. ``other``
    is anything that leaves the relationship unreadable: a subtraction or a
    division, a symbol this reader does not know (``@``, ``$``), or a digit,
    which is a number the scan refused (``FP101``, ``30%``, ``1e3``) and so an
    operand the host cannot read.
    """
    marks: set[str] = set()
    if "=" in gap:
        marks.add("=")
    if _TOTAL_RE.search(gap):
        marks.add("total")
    if "+" in gap:
        marks.add(_PLUS)
    if "\u00d7" in gap or "*" in gap:
        marks.add(_TIMES)
    for token in gap.split():
        if token in ("x", "X"):
            marks.add(_TIMES)
        elif token in _OTHER_OPERATOR_TOKENS:
            marks.add(_OTHER)
    if _DIGIT_RE.search(gap) or any(
        not (ch.isalpha() or ch.isspace() or ch in _GAP_FILLER or ch in "+=*\u00d7")
        for ch in gap
    ):
        marks.add(_OTHER)
    return frozenset(marks)


@dataclass(frozen=True)
class _Equation:
    """One ``operands → result`` run a text prints, and what joins it."""

    operands: tuple[Decimal, ...]
    joins: tuple[frozenset, ...]    # the marks between consecutive operands
    result: Decimal
    total: bool                     # TOTAL labels or marks it
    readable: bool                  # nothing but a marker before the result


def _equations(text: str) -> list[_Equation]:
    """Every equation ``text`` prints, left to right.

    A result is the first number after ``=`` or TOTAL that follows at least one
    operand; its operands are every number since the previous result (or the
    start). So in ``TOTAL 100 + 250 = 375`` the leading TOTAL only labels the
    row, and ``20 20 TOTAL 40 30 30 TOTAL 70`` is two equations. A result
    followed by an operator is the next equation's first operand (a running
    total: ``0.2 x 1500 = 300 + 250 = 550``). A sign glued to an operand after
    the first is its operator: ``20 +30`` adds, ``20 -5`` subtracts.
    """
    s = str(text or "")
    out: list[_Equation] = []
    operands: list[Decimal] = []
    joins: list[frozenset] = []
    total = False
    carried: Decimal | None = None
    prev_end = 0
    for start, end, value, raw in _scan_numbers(s):
        marks = _gap_marks(s[prev_end:start])
        prev_end = end
        if operands and ("=" in marks or "total" in marks):
            out.append(_Equation(
                operands=tuple(operands), joins=tuple(joins), result=value,
                total=total or "total" in marks,
                readable=not (marks & {_PLUS, _TIMES, _OTHER}),
            ))
            operands, joins, total, carried = [], [], False, value
            continue
        if "total" in marks:
            total = True
        ops = set(marks & {_PLUS, _TIMES, _OTHER})
        if raw[:1] == "+":
            ops.add(_PLUS)
        elif raw[:1] == "-" and (operands or carried is not None):
            ops.add(_OTHER)
        if operands:
            joins.append(frozenset(ops))
        elif carried is not None and ops:
            operands, joins = [carried], [frozenset(ops)]
        operands.append(value)
        carried = None
    return out


def _relationship_stated(
    kind: str, terms: list[Decimal], expected: Decimal, text: str
) -> bool:
    """Whether ``text`` prints the claim as one of its equations.

    The equation's result is the stated value, its operands are exactly the
    terms (a multiset: an operand the claim leaves out, or one it adds, is a
    different relationship), and every join is the claim's operation: ``+`` for
    a sum, ``x``/``×``/``*`` for a product or factor. A list with no operator
    at all is a sum only when TOTAL labels or marks it (``20 20 20 TOTAL
    540``); with only ``=`` the operation is not on the sheet. Decided with the
    owner (remediation WP-07.2, review A8): anything else is not established,
    and the mismatch stays model-transcribed for the crop verifier.
    """
    operation = claim_operation(kind)
    need = Counter(terms)
    for eq in _equations(text):
        if not eq.readable or len(eq.operands) < 2:
            continue
        if eq.result != expected or Counter(eq.operands) != need:
            continue
        if operation == "sum" and (
            all(j == {_PLUS} for j in eq.joins) or (eq.total and not any(eq.joins))
        ):
            return True
        if operation == "product" and all(j == {_TIMES} for j in eq.joins):
            return True
    return False


def _relationship_grounded(
    kind: str, terms: list[Decimal], expected: Decimal, quote: str, matched_text: str
) -> bool:
    """Whether the quote AND the sheet's words under its span state the claim.

    Both, as for the operands (:func:`_operands_grounded`): the quote is the
    model's stated evidence, and the words are what the sheet prints there. A
    FUZZY match may differ from the sheet in one non-numeric token, and that
    token can be the operator: a quote reading ``20 + 2 = 40`` over a sheet
    printing ``20 x 2 = 40`` states a sum the sheet does not.
    """
    return (
        _relationship_stated(kind, terms, expected, quote)
        and _relationship_stated(kind, terms, expected, matched_text)
    )


def _arithmetic_verification(
    op: str, actual: Decimal, expected: Decimal, origin: str
) -> Verification:
    """The verdict a mismatch carries: trusted only for :data:`TEXT_EXTRACTED`.

    The note's wording is part of the investigation cache key
    (``investigate._payload_hash`` reads the prior note), so it is the same for
    every finding of one origin, whatever made the operands model-transcribed.
    """
    text_extracted = origin == TEXT_EXTRACTED
    provenance = (
        "operands text-extracted from the sheet quote"
        if text_extracted
        else "host-computed from model-transcribed terms — verify against the sheet"
    )
    return Verification(
        status="DETERMINISTIC" if text_extracted else "UNCERTAIN",
        note=f"computed {op} terms = {_fmt(actual)}; stated = {_fmt(expected)} "
             f"({provenance})",
        computation_method=HOST_DETERMINISTIC,
        operand_origin=TEXT_EXTRACTED if text_extracted else MODEL_TRANSCRIBED,
    )


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
    """Human-readable decimal: trims a trailing ``.0`` / exponent noise.

    ``normalize`` can yield exponent form (e.g. 1.95E+3), which must be expanded
    back for a reviewer. It is expanded with ``format(v, "f")``, **not**
    ``quantize(Decimal(1))``: quantize raises ``InvalidOperation`` as soon as the
    expanded result needs more digits than the decimal context allows (28 by
    default), and that is reachable from ordinary string terms — a claim whose
    product is 1e29 is arithmetic the host can do and cannot print. It raised
    inside the ``Finding(...)`` constructor expression, so there was not even a
    partially-built finding to recover.
    """
    v = value.normalize()
    if v == v.to_integral_value():
        return format(v, "f")
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
        normalize_sheet_id(claim.sheet_id),   # same canonical form (item 11 twin)
        (claim.quote or "").strip(),
        # Exact decimals, terms as a multiset (WP-03.3): the last dedup before
        # any count or finding, so it decides what "checked" counts.
        *claim_content_key(claim.kind, claim.terms, claim.expected),
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
    # ``by_id`` is keyed by ``detect_sheet_id``, which returns
    # ``normalize_sheet_id`` — so the lookup has to use the same canonical form
    # (P8 item 11's twin). A bare ``.strip().upper()`` missed a model-supplied
    # handle carrying a Unicode dash or fullwidth digits against a correctly-keyed
    # map, and the claim then resolved to no sheet at all.
    return by_id.get(normalize_sheet_id(claim.sheet_id))


def audit_arithmetic(
    claims: Iterable[NumericClaim], rendered_sheets: Iterable[Any]
) -> ArithmeticResult:
    """Check every numeric claim's arithmetic; return findings + the tally.

    Deterministic and side-effect-free. Each mismatch becomes a
    :class:`~drawing_analyzer.models.Finding` (``category="conflict"``) anchored
    on its sheet via the claim's verbatim quote (the pure anchor resolver —
    ``UNANCHORED`` if the quote isn't on the sheet, the honest signal). It is
    ``DETERMINISTIC`` only when that anchoring shows the sheet prints every
    operand (module docstring; remediation WP-07.1, N3) and states the claim's
    relationship (WP-07.2, A8), and ``UNCERTAIN`` otherwise. Claims whose
    numbers can't be parsed (including a term that is not one value, such as
    ``"1e3"``), or whose kind is unknown, are counted ``unusable`` and dropped —
    never guessed at. Duplicate
    claims (the critique runs twice) are collapsed before checking so the tally
    isn't double-counted: the same sheet, quote and :func:`claim_content_key`
    (exact decimals, terms as a multiset), so ``20`` and ``"20.0"`` are one
    claim. Every finding carries its claim's
    :func:`arithmetic_claim_discriminator`, so two different mismatches on one
    row keep different ids and are never merged (remediation WP-03.3, B7).
    """
    sheets = list(rendered_sheets)
    by_key, by_id = _build_maps(sheets)

    result = ArithmeticResult()
    seen: set[tuple] = set()
    to_anchor: dict[tuple, list[Finding]] = {}
    # Every mismatch starts model-transcribed; its operands are judged after the
    # anchoring pass below (remediation WP-07.1, N3). Kept beside the findings,
    # and rolled back with them, so the two lists always correspond.
    pending: list[tuple[Finding, list[Decimal], Decimal, Decimal, Any, str, str]] = []

    for claim in claims:
        # Per-CLAIM isolation (item 10b). The orchestrator wraps this whole
        # function in one try, so a single bad claim aborted the loop, the
        # caller discarded ``result``, and the run lost every arithmetic
        # finding it had already produced AND all four ``arithmetic_*`` stat
        # keys — after which the summary line reads ``arith=0/0`` via
        # ``stats.get(..., 0)``, i.e. the failure renders as "nothing to
        # check", indistinguishable from a set with no claims. Silent.
        #
        # The sibling auditors are each wrapped by ``_run``; arithmetic is the
        # only one hand-rolled outside it, and even ``_run`` is per-auditor.
        snapshot = (result.checked, result.matched, result.mismatched,
                    len(result.findings), len(pending))
        try:
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
            # but the numbers it used are trusted only when the sheet independently
            # prints every one of them (TEXT_EXTRACTED). That needs the anchor, so
            # every mismatch starts MODEL_TRANSCRIBED / UNCERTAIN and is promoted
            # after the anchoring pass below, or never: a misread term must never
            # ink as trusted ground truth.
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
                recommended_action=(
                    f"Re-check the math: the {op} the printed values is "
                    f"{_fmt(actual)}, not the stated {_fmt(expected)} - correct "
                    "whichever is wrong."
                ),
                refs=[],
                verification=_arithmetic_verification(
                    op, actual, expected, MODEL_TRANSCRIBED,  # type: ignore[arg-type]
                ),
                sources=["auditor_arithmetic"],
                # Two mismatches on one row share this quote, and so shared an
                # id and were merged by the ledger (review B7). The
                # discriminator keeps them apart there, and is folded into id.
                claim_discriminator=arithmetic_claim_discriminator(
                    claim.kind, claim.terms, claim.expected
                ),
            )
            result.findings.append(finding)
            pending.append((finding, terms, expected, actual, geom, op, kind))  # type: ignore[arg-type]
            if geom is not None and (claim.quote or "").strip():
                to_anchor.setdefault(source_page_key(finding), []).append(finding)
        except Exception as exc:  # noqa: BLE001 - one claim never sinks the rest
            # Roll the tally back to before this claim and count it unusable, so
            # ``mismatched == len(findings)`` still holds (it is incremented
            # before the Finding is built, and _fmt used to raise inside the
            # constructor expression — leaving a counted mismatch with no
            # finding behind it).
            (result.checked, result.matched, result.mismatched, kept, kept_pending) = snapshot
            del result.findings[kept:]
            del pending[kept_pending:]
            result.unusable += 1
            from ..diagnostics import get_logger
            get_logger().warning(
                "arithmetic auditor: claim skipped (%s %s): %s",
                getattr(claim, "sheet_id", "") or "?", getattr(claim, "kind", "") or "?",
                exc,
            )

    # Anchor the mismatch findings via their quotes, grouped per sheet. Reuses the
    # pure resolver (EXACT/FUZZY/TILE/UNANCHORED) exactly like model findings,
    # and keeps the sheet words each quote matched for the operand check below.
    from .. import anchor

    matched: dict[int, str] = {}
    geom_by_key = {source_page_key(g.ref): g for g in sheets if getattr(g, "ref", None)}
    for key, group in to_anchor.items():
        geom = geom_by_key.get(key)
        if geom is None:
            continue
        try:
            anchor.resolve_anchors(group, geom, matched_text=matched)
        except Exception as exc:  # noqa: BLE001 - one sheet never sinks the rest
            # Its findings keep no anchor, so they stay model-transcribed.
            _log_warning("arithmetic auditor: anchoring failed for %s: %s", key, exc)

    # Operand provenance, now that the anchors exist (remediation WP-07.1, N3):
    # trusted only when the claim resolved to a sheet, its quote anchored there
    # by a numerically vetoed match, the numbers printed there carry every
    # operand once per use, and both the quote and those words state the claim's
    # relationship (WP-07.2, A8). Anything else, including a failure here,
    # leaves the finding model-transcribed, the safe direction.
    for finding, terms, expected, actual, geom, op, kind in pending:
        text = matched.get(id(finding))
        try:
            if (
                geom is not None and text is not None
                and anchor.numbers_grounded(finding.anchor)
                and _operands_grounded(terms, expected, finding.source_quote, text)
                and _relationship_grounded(kind, terms, expected, finding.source_quote, text)
            ):
                finding.verification = _arithmetic_verification(
                    op, actual, expected, TEXT_EXTRACTED,
                )
        except Exception as exc:  # noqa: BLE001 - stays UNCERTAIN, never trusted
            _log_warning(
                "arithmetic auditor: operand provenance undecided for %s: %s",
                finding.sheet_id or "?", exc,
            )
    return result


def _log_warning(msg: str, *args: Any) -> None:
    from ..diagnostics import get_logger

    get_logger().warning(msg, *args)
