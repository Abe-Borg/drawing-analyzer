"""The tokenizer residuals WP-04.1 read only in part (remediation WP-04.4).

Four demonstrated conflicting pairs still folded into one finding, each a
spelling the quantity reader signed only in part, so the two findings'
signatures agreed:

* **a bare feet value**: ``12'`` signs ``{12ft}``, which ``12'-6"``
  (``{12ft, 6in}``, feet-inches is two tokens) includes;
* **a ``to`` range**: the ``4`` of ``4 to 6 in`` has no unit, so the range
  signed its far end, ``6in``; ``4 and 6 in`` and ``4 or 6 in`` did the same;
* **a loose-comma list**: ``2, 4, 6 in`` signed only its last element;
* **a bare ``20A``**: a compact ``A`` needs electrical context, so neither
  ``20A`` nor ``30A`` signed and the shared ``120V`` made them compatible.

The owner's rules (decided before any code, measured over the whole suite):

* **Feet-inches, a pair beside the tokens.** The token model is unchanged
  (feet-inches stays two tokens). The signature gains ``feet_inches``: every
  feet value, in any spelling (``12'``, ``12 ft``, ``12 feet``, ``10-foot``),
  signs with the inches half joined to it (``12'-6"``, ``12' 6"``,
  ``12' - 6"``, ``12'\u20136"``, ``12 ft 6 in`` are ``12ft6in``) or with zero
  inches when bare (``12'`` and ``12'-0"`` are both ``12ft0in``). Compared by
  inclusion on the ``measurements`` axis, so it can only ever block a merge.
* **Spelled ranges and lists.** ``4 to 6 in`` and ``between 4 and 6 in`` are
  the range ``4..6in`` (the token ``4-6 in`` already signs); ``4 and 6 in``
  and ``4 or 6 in`` are the list ``4,6in`` (the tight ``4,6 in``'s token).
* **Loose-comma lists of three or more numbers** (``2, 4, 6 in``,
  ``2, 4 and 6 in``, ``2, 4, and 6 in``, ``2, 4 or 6 in``) are the tight
  list's token, ``2,4,6in``. Two numbers joined by a comma alone stay prose
  (``at column 4, 10 ft`` is ``10ft``), a recorded limit.
* **Guards, the new forms only, so nothing is widened:** today's reading
  stands when a name or reference word precedes the first number (``grid``,
  ``notes``, ``pages``, ...), when the unit is the word ``in`` followed by an
  article or a preposition's object (``in the manual``, ``in plan``), for
  ``2 and 1/2 in`` (a mixed number), and for a run inside a longer list.
* **A bare ``20A`` beside a voltage** (right after it, ``20A 120V``,
  ``20A, 120V``, ``20A @ 480V``, or right before it, ``120V 20A``) is a
  current, unless a name word precedes the number: ``Room 101A 120V`` and
  ``Panel 2A 120/208V`` stay names.

Every pair shares enough prose that the text alone would merge it, so the
signature is what decides, in the critique's two-read merge and the ledger.

New names are imported inside the tests that need them, so that on a tree
without them only those tests fail and the rest still say what they check.
The degree sign and the en dash are written as escapes.

Hermetic (I-4): pure data, no client, no PDF.
"""
from __future__ import annotations

import itertools
import json

import pytest

from drawing_analyzer.critique import (
    _TEXT_DUP_THRESHOLD,
    _is_duplicate,
    _quantity_tokens,
    _token_overlap,
    critical_signature,
    merge_self_consistency,
    signature_conflicts,
    signatures_compatible,
)
from drawing_analyzer.ledger import Ledger, reconcile_post_anchor
from drawing_analyzer.models import Anchor, Finding


def _finding(text: str, quote: str = "") -> Finding:
    return Finding(
        sheet_id="M-101", source_name="mech.pdf", page_index=0,
        category="coordination", severity="medium", text=text, source_quote=quote,
    )


def _tokens(text: str) -> list[str]:
    return sorted(_quantity_tokens(text))


def _pairs(text: str, quote: str = "") -> list[str]:
    return critical_signature(_finding(text, quote))["feet_inches"]


def _surviving(text_a: str, text_b: str) -> tuple[int, int]:
    """How many findings survive the critique merge and the ledger merge."""
    critique = merge_self_consistency([[_finding(text_a)], [_finding(text_b)]])
    ledger = Ledger()
    ledger.add([_finding(text_a)], source="digest")
    ledger.add([_finding(text_b)], source="critique_1")
    return len(critique), len(ledger)


# --------------------------------------------------------------------------- #
# The tokens
# --------------------------------------------------------------------------- #

_SPELLED_RANGES = [
    ("Maintain 4 to 6 in clearance", ["4..6in"]),
    ("Maintain 6 to 4 in clearance", ["4..6in"]),
    ("Maintain from 4 to 6 in clearance", ["4..6in"]),
    ("Maintain between 4 and 6 in clearance", ["4..6in"]),
    ("Maintain 4 to 6-inch clearance", ["4..6in"]),
    ("Provide 2 to 4 gpm makeup", ["2..4gpm"]),
    ("Setpoint band 65 to 75\u00b0F", ["65..75\u00b0f"]),
    ("Flow 1,000 to 2,000 cfm", ["1000..2000cfm"]),
    ("Pipe 1 1/2 to 2 in", ["1.5..2in"]),
    ("Motor 208 to 230V", ["208..230volt"]),
    ("Outside air 10 to 20%", ["10..20%"]),
]

_SPELLED_LISTS = [
    ("Provide 4 and 6 in drains", ["4,6in"]),
    ("Provide 4 or 6 in drains", ["4,6in"]),
    ("Provide 6 and 4 in drains", ["6,4in"]),        # written order, as a tight list
    ("Provide 2, 4, 6 in drains", ["2,4,6in"]),
    ("Provide 2, 4 and 6 in drains", ["2,4,6in"]),
    ("Provide 2, 4, and 6 in drains", ["2,4,6in"]),
    ("Provide 2, 4 or 6 in drains", ["2,4,6in"]),
    ("Provide 2, 4, 6, 8 in drains", ["2,4,6,8in"]),
    ("Supply 1,500, 2,000 and 3,000 cfm", ["1500,2000,3000cfm"]),
    ("Provide 1/2 and 3/4 in pipe", ["0.5,0.75in"]),
    ("Provide 2, 4, 6 in drains at 100 psi", ["100psi", "2,4,6in"]),
]

_AMPS_BESIDE_A_VOLTAGE = [
    ("Provide 20A 120V circuit", ["120volt", "20amp"]),
    ("Provide 20A, 120V circuit", ["120volt", "20amp"]),
    ("Provide 20A @ 480V circuit", ["20amp", "480volt"]),
    ("Provide 20A 120/208V circuit", ["120/208volt", "20amp"]),
    ("Provide 20A 24VAC relay", ["20amp", "24vac"]),
    ("Provide 120V 20A circuit", ["120volt", "20amp"]),
    ("Provide 120V, 20A circuit", ["120volt", "20amp"]),
]

# Shapes the new forms must NOT read: each keeps exactly today's tokens. The
# ``in`` preposition is the tokenizer's oldest false positive (``6 in the
# manual``); a spelled range or list must not widen it.
_RESIDUAL_NEGATIVE_CORPUS = [
    ("pages 4 to 6 in the manual", ["6in"]),
    ("from 4 to 6 in the afternoon", ["6in"]),
    ("see steps 4 to 6 in this section", ["6in"]),
    ("grid 4 to 6 in", ["6in"]),
    ("Level 2 to 4 ft", ["4ft"]),
    ("grids 4 and 6 in", ["6in"]),
    ("notes 1 and 2 in plan", ["2in"]),
    ("keynotes 3 and 4 in each room", ["4in"]),
    ("Provide 2 and 1/2 in pipe", ["0.5in"]),          # a mixed number, not a list
    ("Provide 2, 4, 6 in the corridor", ["6in"]),
    ("columns 2, 4, 6 in plan", ["6in"]),
    ("sheets 1, 2, 3 in the set", ["3in"]),
    ("at column 4, 10 ft from the wall", ["10ft"]),
    ("Provide 2, 4 in drains", ["4in"]),                # two numbers, a comma alone: prose
    ("Provide 2 and 4 and 6 in drains", ["6in"]),       # not one list
    ("Provide 2,4, 6 in drains", ["6in"]),              # a tight run, then a loose element
    ("Maintain 4 in to 6 in", ["4in", "6in"]),           # a unit on each end: two tokens
    ("Increase the 8 in main to 6 in", ["6in", "8in"]),
    ("Maintain 4 to -6 in", ["-6in"]),
    ("ratio 3 to 1", []),
    ("between grids 2A and 3", []),
    ("Room 101A 120V receptacle", ["120volt"]),
    ("RM 101A 120V", ["120volt"]),
    ("Panel 2A 120/208V", ["120/208volt"]),
    ("Panel 2A, 120/208V", ["120/208volt"]),
    ("Level 1A 480V", ["480volt"]),
    ("grid 2A 480V", ["480volt"]),
    ("keynote 3A 120V", ["120volt"]),
    ("Type 2A 277V fixture", ["277volt"]),
    ("panel LP-2A 120/208V", ["120/208volt"]),
    ("EF-1A 120V", ["120volt"]),
    ("AHU-2A 460V", ["460volt"]),
    ("Circuit LP-1-20A 120V", ["120volt"]),
    # A name word with a number label between it and the identifier is still a
    # name (Codex review): the qualifier is part of the one name guard.
    ("Room No. 101A 120V receptacle", ["120volt"]),
    ("Panel No. 2A 120/208V", ["120/208volt"]),
    ("Room Number 101A 120V", ["120volt"]),
    ("Rm. No. 101A 120V", ["120volt"]),
    ("Room No 101A 120V", ["120volt"]),
    ("Room No. 101A breaker", []),
    ("Section No. 4 to 6 in", ["6in"]),
    ("Notes Nos. 1 and 2 in plan", ["2in"]),
    ("3H:1V 2A", []),
    ("Provide 20A circuit", []),                         # no voltage, no device: a recorded limit
]

# Misreadings the owner accepted with the rules (measured before any code).
# Pinned so that a change to them is deliberate.
_RECORDED_MISREADINGS = [
    # A room or panel name with no name word before it, beside a voltage.
    ("101A 120V receptacle", ["101amp", "120volt"]),
    ("fed from 2A 120/208V", ["120/208volt", "2amp"]),
    # A from-to change reads as a range.
    ("Increase the drain from 4 to 6 in", ["4..6in"]),
]


@pytest.mark.parametrize(
    "text,expected",
    _SPELLED_RANGES + _SPELLED_LISTS + _AMPS_BESIDE_A_VOLTAGE,
    ids=[t for t, _ in _SPELLED_RANGES + _SPELLED_LISTS + _AMPS_BESIDE_A_VOLTAGE],
)
def test_a_spelled_quantity_is_read_whole(text, expected):
    assert _tokens(text) == sorted(expected)


@pytest.mark.parametrize(
    "text,expected", _RESIDUAL_NEGATIVE_CORPUS, ids=[t for t, _ in _RESIDUAL_NEGATIVE_CORPUS],
)
def test_the_new_forms_widen_nothing(text, expected):
    assert _tokens(text) == sorted(expected)


@pytest.mark.parametrize(
    "text,expected", _RECORDED_MISREADINGS, ids=[t for t, _ in _RECORDED_MISREADINGS],
)
def test_recorded_misreadings(text, expected):
    assert _tokens(text) == sorted(expected)


def test_a_spelled_range_is_the_dash_range_token_and_a_list_the_tight_list_token():
    assert _quantity_tokens("Maintain 4 to 6 in") == _quantity_tokens("Maintain 4-6 in")
    assert _quantity_tokens("Maintain between 4 and 6 in") == _quantity_tokens("Maintain 4-6 in")
    assert _quantity_tokens("Provide 4 or 6 in") == _quantity_tokens("Provide 4,6 in")
    assert _quantity_tokens("Provide 2, 4 and 6 in") == _quantity_tokens("Provide 2,4,6 in")
    assert _quantity_tokens("Flow 1,000 to 2,000 cfm") == _quantity_tokens("Flow 1,000-2,000 cfm")


# --------------------------------------------------------------------------- #
# The feet-inches pairs
# --------------------------------------------------------------------------- #

_FEET_INCHES = [
    ("Maintain 12' clear", ["12ft0in"]),
    ("Maintain 12'-0\" clear", ["12ft0in"]),
    ("Maintain 12'-6\" clear", ["12ft6in"]),
    ("Maintain 12' 6\" clear", ["12ft6in"]),
    ("Maintain 12'6\" clear", ["12ft6in"]),
    ("Maintain 12' - 6\" clear", ["12ft6in"]),
    ("Maintain 12'\u20136\" clear", ["12ft6in"]),
    ("Maintain 12'-6 1/2\" clear", ["12ft6.5in"]),
    # A sign after a space is a negative six inches, not a join (WP-05.3).
    ("Maintain 12' -6\" clear", ["12ft0in"]),
    ("Maintain 12 ft clear", ["12ft0in"]),
    ("Maintain 12 feet clear", ["12ft0in"]),
    ("Maintain a 10-foot clearance", ["10ft0in"]),
    ("Maintain 12 ft 6 in clear", ["12ft6in"]),
    ("Maintain 12 FT - 6 IN clear", ["12ft6in"]),
    ("Maintain 12 feet 6 inches clear", ["12ft6in"]),
    ("Maintain 12 ft. 6 in. clear", ["12ft6in"]),        # an abbreviation's period
    ("Maintain 12 ft. clear", ["12ft0in"]),
    ("Maintain 10 ft, 6 in from the main", ["10ft0in"]),   # a comma is not a join
    ("elevation 10'-6\" x 12'-0\"", ["10ft6in", "12ft0in"]),
    ("room is 10'x12'-6\"", ["10ft0in", "12ft6in"]),
    ("Board 6\" x 12'", ["12ft0in"]),
    ("Room is 10'x12'", []),                               # a size, one token
    ("Maintain 4-6 ft clear", []),                         # a range, one token
    ("Provide 6 in drain", []),
    ("Maintain 12'-6\" clear, 10' from the wall", ["10ft0in", "12ft6in"]),
    # A recorded misreading the owner accepted: a feet value directly followed
    # by a separate inch size reads as feet-inches (it can only keep two
    # findings apart).
    ("Relocate the 10 ft 6 in pipe", ["10ft6in"]),
]


@pytest.mark.parametrize("text,expected", _FEET_INCHES, ids=[t for t, _ in _FEET_INCHES])
def test_the_feet_inches_pair(text, expected):
    assert _pairs(text) == expected


def test_the_pair_leaves_the_tokens_alone():
    """The token model is unchanged: feet-inches is still two tokens, so every
    _SAFEGUARDS row stays and the anchor's quantity veto, which reuses the
    reader, cannot move."""
    assert _tokens("maintain 12'-6\" clear") == ["12ft", "6in"]
    assert _tokens("Maintain 12' clear") == ["12ft"]
    assert _tokens("Maintain 12 ft 6 in clear") == ["12ft", "6in"]


def test_pairs_are_read_part_by_part():
    """Text, quote and supporting quotes are read apart, as roles are: a text
    ending in a feet value and a quote opening with an inch value must not
    read as feet-inches."""
    sig = critical_signature(_finding("Maintain the clearance of 12 ft", quote="6 IN MAIN"))
    assert sig["feet_inches"] == ["12ft0in"]
    assert sig["measurements"] == ["12ft", "6in"]


def test_the_signature_carries_feet_inches_as_a_sorted_json_safe_list():
    sig = critical_signature(_finding("Maintain 12'-6\" clear, 10' from the wall"))
    assert sig["feet_inches"] == ["10ft0in", "12ft6in"]
    assert json.loads(json.dumps(sig)) == sig


# --------------------------------------------------------------------------- #
# The merges
# --------------------------------------------------------------------------- #

_H = " clear headroom under the main duct at the M-101 riser serving the east data hall"
_C = " clearance around the base of pump P-1 on the plan for the east data hall"
_D = " floor drains along the east wall of the main mechanical room per the plumbing plan"
_E = " circuit for exhaust fan EF-1 on panel LP-1 per the electrical schedule"
_G = " makeup flow at pump P-1 per the pump schedule for the east data hall"

# Each residual's conflict in other kinds and spellings (the pinned pairs
# themselves are in tests/test_quantity_signature.py::_CONFLICTS).
_RESIDUAL_CONFLICTS = {
    "feet: 10'-4\" vs 10'": ("Maintain 10'-4\"" + _H, "Maintain 10'" + _H),
    "feet: 12'-6\" vs 12 ft": ("Maintain 12'-6\"" + _H, "Maintain 12 ft" + _H),
    "feet: 12 ft 6 in vs 12'": ("Maintain 12 ft 6 in" + _H, "Maintain 12'" + _H),
    "feet: 12' above a 6 in main vs 12'-6\"": (
        "Maintain 12' clear above the 6 in main at the M-101 riser serving the east data hall",
        "Maintain 12'-6\" clear above the main at the M-101 riser serving the east data hall",
    ),
    "to: 2 to 4 gpm vs 4 gpm": ("Provide 2 to 4 gpm" + _G, "Provide 4 gpm" + _G),
    "to: 65 to 75\u00b0F vs 75\u00b0F": (
        "Setpoint 65 to 75\u00b0F for RTU-2 serving the lab in the sequence of operations",
        "Setpoint 75\u00b0F for RTU-2 serving the lab in the sequence of operations",
    ),
    "to: 4 to 6 in vs 2 to 6 in": ("Maintain 4 to 6 in" + _C, "Maintain 2 to 6 in" + _C),
    "between: between 4 and 6 in vs 6 in": ("Maintain between 4 and 6 in" + _C, "Maintain 6 in" + _C),
    "and: 4 and 6 in vs 6 in": ("Maintain 4 and 6 in" + _C, "Maintain 6 in" + _C),
    "or: 4 or 6 in vs 6 in": ("Provide 4 or 6 in" + _D, "Provide 6 in" + _D),
    "loose: 2, 4 and 6 in vs 3, 5 and 6 in": ("Provide 2, 4 and 6 in" + _D, "Provide 3, 5 and 6 in" + _D),
    "loose: 2, 4, 6 gpm vs 1, 3, 6 gpm": ("Provide 2, 4, 6 gpm" + _G, "Provide 1, 3, 6 gpm" + _G),
    "amp: 20A 208V vs 30A 208V": ("Provide 20A 208V" + _E, "Provide 30A 208V" + _E),
    "amp: 120V 20A vs 120V 30A": ("Provide 120V 20A" + _E, "Provide 120V 30A" + _E),
    "amp: 20A 120/208V vs 30A 120/208V": ("Provide 20A 120/208V" + _E, "Provide 30A 120/208V" + _E),
}


@pytest.mark.parametrize("pair", sorted(_RESIDUAL_CONFLICTS), ids=sorted(_RESIDUAL_CONFLICTS))
def test_a_residual_conflict_stays_two_findings(pair):
    a, b = _RESIDUAL_CONFLICTS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD, "the prose alone would merge these"
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert signature_conflicts(sa, sb) == ["measurements"]
    assert _surviving(a, b) == (2, 2)


# One quantity spelled two ways: still one finding.
_RESIDUAL_EQUIVALENTS = {
    "feet: 12' = 12'-0\"": ("Maintain 12'" + _H, "Maintain 12'-0\"" + _H),
    "feet: 12' = 12 ft": ("Maintain 12'" + _H, "Maintain 12 ft" + _H),
    "feet: 12'-6\" = 12' - 6\"": ("Maintain 12'-6\"" + _H, "Maintain 12' - 6\"" + _H),
    "feet: 12'-6\" = 12'\u20136\"": ("Maintain 12'-6\"" + _H, "Maintain 12'\u20136\"" + _H),
    "feet: 12'-6\" = 12 ft 6 in": ("Maintain 12'-6\"" + _H, "Maintain 12 ft 6 in" + _H),
    "feet: 12'-6\" = 12 ft. 6 in.": ("Maintain 12'-6\"" + _H, "Maintain 12 ft. 6 in." + _H),
    "to: 4 to 6 in = 4-6 in": ("Maintain 4 to 6 in" + _C, "Maintain 4-6 in" + _C),
    "between: between 4 and 6 in = 4-6 in": ("Maintain between 4 and 6 in" + _C, "Maintain 4-6 in" + _C),
    "or: 4 or 6 in = 4,6 in": ("Provide 4 or 6 in" + _D, "Provide 4,6 in" + _D),
    "loose: 2, 4 and 6 in = 2,4,6 in": ("Provide 2, 4 and 6 in" + _D, "Provide 2,4,6 in" + _D),
    "amp: 20A 120V = 20 amp 120V": ("Provide 20A 120V" + _E, "Provide 20 amp 120V" + _E),
}


@pytest.mark.parametrize("pair", sorted(_RESIDUAL_EQUIVALENTS), ids=sorted(_RESIDUAL_EQUIVALENTS))
def test_a_residual_spelled_two_ways_is_one_finding(pair):
    a, b = _RESIDUAL_EQUIVALENTS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert signatures_compatible(sa, sb)
    assert _surviving(a, b) == (1, 1)


# Deliberate conservative retention the owner accepted with the rules: each
# pair may be one issue, but the signatures now differ, so it stays two.
_RESIDUAL_RETENTION = {
    "a from-to change against its end: increase from 4 to 6 in vs increase to 6 in": (
        "Increase from 4 to 6 in" + _C, "Increase to 6 in" + _C,
    ),
    "a unit on each end against a spelled range: 4 in to 6 in vs 4 to 6 in": (
        "Maintain 4 in to 6 in" + _C, "Maintain 4 to 6 in" + _C,
    ),
    "a unit on each element against a spelled list: 4 in and 6 in vs 4 and 6 in": (
        "Maintain 4 in and 6 in" + _C, "Maintain 4 and 6 in" + _C,
    ),
    "feet-inches with a comma: 12 ft, 6 in vs 12'-6\"": (
        "Maintain 12 ft, 6 in" + _H, "Maintain 12'-6\"" + _H,
    ),
}


@pytest.mark.parametrize("pair", sorted(_RESIDUAL_RETENTION), ids=sorted(_RESIDUAL_RETENTION))
def test_residual_retention_is_by_design(pair):
    a, b = _RESIDUAL_RETENTION[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert not signatures_compatible(sa, sb)
    assert _surviving(a, b) == (2, 2)


def test_the_500_550_duplicate_still_folds():
    """The commonest duplicate: both critique reads write the same shown and
    required pair. Nothing here reads it differently."""
    text = "Pump P-1 shows 500 gpm but the pump schedule requires 550 gpm at the design point"
    sig = critical_signature(_finding(text, quote="P-1 500 GPM"))
    assert sig["measurements"] == ["500gpm", "550gpm"] and sig["feet_inches"] == []
    (merged,) = merge_self_consistency(
        [[_finding(text, quote="P-1 500 GPM")], [_finding(text, quote="P-1 500 GPM")]]
    )
    assert merged.reproduced is True and merged.confidence == "REPRODUCED"


# --------------------------------------------------------------------------- #
# Complete-link: a bridge that names neither side's quantity
# --------------------------------------------------------------------------- #
#
# A and C conflict only through a new signal; B, the bridge, is compatible
# with both. A survivor whose bundle passes to B carries none of A's signal in
# its live signature (A has no quote, so nothing of it is a supporting quote),
# so every complete-link check must compare members as they arrived.

_CHAINS = {
    "feet": (
        "Maintain 12'-6\"" + _H,
        "Maintain the" + _H,
        "Maintain 12'" + _H,
    ),
    "to": (
        "Maintain 4 to 6 in" + _C,
        "Maintain the" + _C,
        "Maintain 6 in" + _C,
    ),
    "loose": (
        "Provide 2, 4, 6 in" + _D,
        "Provide the" + _D,
        "Provide 3, 5, 6 in" + _D,
    ),
    # A shared quantity is the bridge here: before WP-04.4 all three signed
    # {120volt} and folded into one.
    "amp": (
        "Provide 20A 120V" + _E,
        "Provide 120V" + _E,
        "Provide 30A 120V" + _E,
    ),
}
_ORDERS = [
    (chain, order) for chain in sorted(_CHAINS) for order in itertools.permutations("ABC")
]
_ORDER_IDS = [f"{chain}-{''.join(order)}" for chain, order in _ORDERS]


def _chain(chain: str) -> dict[str, str]:
    return dict(zip("ABC", _CHAINS[chain]))


@pytest.mark.parametrize("chain", sorted(_CHAINS), ids=sorted(_CHAINS))
def test_the_chain_is_a_bridge(chain):
    a, b, c = _CHAINS[chain]
    assert _is_duplicate(_finding(a), _finding(b))
    assert _is_duplicate(_finding(b), _finding(c))
    assert not _is_duplicate(_finding(a), _finding(c))


@pytest.mark.parametrize("chain,order", _ORDERS, ids=_ORDER_IDS)
def test_the_critique_merge_never_folds_the_chain(chain, order):
    texts = _chain(chain)
    merged = merge_self_consistency([[_finding(texts[k])] for k in order])
    assert len(merged) == 2


@pytest.mark.parametrize("chain,order", _ORDERS, ids=_ORDER_IDS)
def test_the_ledger_never_folds_the_chain(chain, order):
    texts = _chain(chain)
    ledger = Ledger()
    for key in order:
        ledger.add([_finding(texts[key])], source=f"read_{key}")
    assert len(ledger) == 2
    for entry in ledger.entries:
        members = {m.text for m in ledger.member_history(entry)}
        assert not {texts["A"], texts["C"]} <= members


@pytest.mark.parametrize("chain,order", _ORDERS, ids=_ORDER_IDS)
def test_pass_b_never_folds_the_chain(chain, order):
    texts = _chain(chain)
    ledger = Ledger()
    for key in order:
        ledger.add([_finding(texts[key], quote="RISER")], source=f"read_{key}")
    assert len(ledger) == 2
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = Anchor(status="EXACT", rect_pdf=[10.0, 20.0, 200.0, 40.0], method="exact")
    reconcile_post_anchor(ledger)
    assert len(ledger) == 2
    for entry in ledger.entries:
        members = {m.text for m in ledger.member_history(entry)}
        assert not {texts["A"], texts["C"]} <= members


# --------------------------------------------------------------------------- #
# The one rule
# --------------------------------------------------------------------------- #

def test_a_pair_conflict_is_the_measurements_axis_and_symmetric():
    a = critical_signature(_finding("Maintain 12'-6\"" + _H))
    b = critical_signature(_finding("Maintain 12'" + _H))
    assert a["measurements"] == ["12ft", "6in"] and b["measurements"] == ["12ft"]
    assert signature_conflicts(a, b) == signature_conflicts(b, a) == ["measurements"]
    assert signatures_compatible(a, b) is signatures_compatible(b, a) is False


def test_a_pair_on_one_side_only_never_conflicts():
    a = critical_signature(_finding("Maintain 12'-6\"" + _H))
    b = critical_signature(_finding("Maintain the" + _H))
    assert b["feet_inches"] == []
    assert signature_conflicts(a, b) == []


def test_pairs_compare_by_inclusion():
    a = critical_signature(_finding("Maintain 12'-6\"" + _H))
    b = critical_signature(_finding("Maintain 12'-6\"" + _H + ", 10' from the wall"))
    assert a["feet_inches"] == ["12ft6in"] and b["feet_inches"] == ["10ft0in", "12ft6in"]
    assert signature_conflicts(a, b) == []


def test_the_pair_only_ever_blocks_more():
    """The pairs add a conflict and never remove one: over a corpus, every pair
    of signatures the rule blocks without ``feet_inches`` is still blocked
    with it."""
    corpus = [text for pair in _RESIDUAL_CONFLICTS.values() for text in pair] + [
        text for pair in _RESIDUAL_EQUIVALENTS.values() for text in pair
    ] + [text for pair in _RESIDUAL_RETENTION.values() for text in pair]
    sigs = [critical_signature(_finding(t)) for t in corpus]
    blocked = 0
    for a in sigs:
        for b in sigs:
            bare_a = {k: v for k, v in a.items() if k != "feet_inches"}
            bare_b = {k: v for k, v in b.items() if k != "feet_inches"}
            if signature_conflicts(bare_a, bare_b):
                blocked += 1
                assert signature_conflicts(a, b)
    assert blocked > 0


def test_the_quantity_tokens_are_still_the_readings_tokens():
    from drawing_analyzer.critique import _quantity_readings

    texts = [t for t, _ in _SPELLED_RANGES + _SPELLED_LISTS + _AMPS_BESIDE_A_VOLTAGE
             + _RESIDUAL_NEGATIVE_CORPUS + _FEET_INCHES]
    for text in texts:
        readings = _quantity_readings(text)
        assert _quantity_tokens(text) == frozenset(token for token, _s, _e in readings)
        for _token, start, end in readings:
            assert 0 <= start < end <= len(text)


def test_a_role_after_a_spelled_list_binds_like_a_tight_list():
    """A spelled list or range is one reading, as a tight one is, so a role
    after it binds the whole quantity (WP-04.3's rules are unchanged)."""
    loose = critical_signature(_finding("Provide 2, 4, 6 in main at the riser"))
    tight = critical_signature(_finding("Provide 2,4,6 in main at the riser"))
    assert loose["roles"] == tight["roles"] == ["main=2,4,6in"]
    ranged = critical_signature(_finding("Provide 4 to 6 in main at the riser"))
    assert ranged["roles"] == ["main=4..6in"]


# --------------------------------------------------------------------------- #
# The prose harvest's veto reads the same rule (WP-09.2)
# --------------------------------------------------------------------------- #

_VETO_CASES = {
    "feet": ("Maintain 12' clear headroom under the main duct at the M-101 riser.",
             "Maintain 12'-6\" clear headroom under the main duct at the M-101 riser."),
    "to": ("Maintain 6 in clearance around the base of pump P-1 on the plan.",
           "Maintain 4 to 6 in clearance around the base of pump P-1 on the plan."),
    "loose": ("Provide 3, 5, 6 in floor drains along the east wall of the mechanical room.",
              "Provide 2, 4, 6 in floor drains along the east wall of the mechanical room."),
    "amp": ("Provide 30A 120V circuit for exhaust fan EF-1 on panel LP-1.",
            "Provide 20A 120V circuit for exhaust fan EF-1 on panel LP-1."),
}


@pytest.mark.parametrize("case", sorted(_VETO_CASES), ids=sorted(_VETO_CASES))
def test_the_prose_veto_refuses_a_residual_candidate(case):
    from drawing_analyzer.prose_harvest import _match_entry, _veto_axes

    item, other = _VETO_CASES[case]
    entry = Finding(sheet_id="P-101", source_name="a.pdf", page_index=0,
                    category="coordination", severity="medium", text=other)
    same = Finding(sheet_id="P-101", source_name="a.pdf", page_index=0,
                   category="coordination", severity="medium", text=item)
    assert _veto_axes(item, entry) == ["measurements"]
    assert _match_entry(item, [entry]) is None
    assert _match_entry(item, [entry, same]) is same


# --------------------------------------------------------------------------- #
# The anchor and cross-QC read the same quantities (WP-05.3)
# --------------------------------------------------------------------------- #
#
# ``anchor._same_quantities`` reuses ``_quantity_tokens``. Its tokens changed
# for the new forms, and so, through the new guards, did whether two
# spellings a named letter-merge join relates read alike: a quote with ``IN A``
# against a sheet printing ``IN ACLEAR`` (the article ``a`` keeps today's
# reading; ``aclear`` is not an article). That is host-side binding for
# byte-identical inputs, so ``_CROSS_QC_CACHE_CONTRACT`` 7 -> 8 (the owner's
# decision). Measured: none of the suite's grounding verdicts or anchors moved.

_JOIN_FLIPS = {
    "to, an article merged into the next word": ("4 TO 6 IN A CLEAR SPACE", "PROVIDE 4 TO 6 IN ACLEAR SPACE"),
    "and, an article merged into the next word": ("4 AND 6 IN A ROW", "PROVIDE 4 AND 6 IN AROW"),
    "a loose list with leading commas": ("2 ,4 ,6 IN A ROW", "PROVIDE 2 ,4 ,6 IN AROW"),
    "a name word merged into the word before it": ("ELEC ROOM 101A 120V", "SEE ELECROOM 101A 120V"),
}


@pytest.mark.parametrize("case", sorted(_JOIN_FLIPS), ids=sorted(_JOIN_FLIPS))
def test_the_anchor_and_cross_qc_refuse_a_join_that_reads_differently(case):
    """Both matchers still agree (one matcher, WP-05.3: the anchor places EXACT
    or ``char_stream`` exactly where cross-QC grounds): each refuses the join,
    since the two sides no longer read the same quantities. The anchor's
    sub-phrase tier may still place a part of the quote (``4 TO 6 IN``), on
    ``main`` as here."""
    from drawing_analyzer import cross_qc
    from tests.test_anchor_whole_words import _line, _place

    quote, sheet = _JOIN_FLIPS[case]
    assert cross_qc._grounded(quote, sheet) is False
    anchor, _matched = _place(quote, _line(sheet))
    assert anchor.method not in ("exact", "char_stream")


def test_the_cross_qc_contract_moved_for_the_quantity_reader():
    from drawing_analyzer import cross_qc as X

    assert X._CROSS_QC_CACHE_CONTRACT == 8
