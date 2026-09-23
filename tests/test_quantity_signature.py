"""The quantity tokenizer behind the critical signature (remediation WP-04.1).

Findings B2 (hyphenated units), B3 (thousands groups), B12 (degrees) and N19
(W×H sizes, compact volts and amps, ranges and lists). A measurement in the
critical signature is what keeps "6 in drain" and "4 in drain" two findings
when the prose around them is otherwise the same, so every spelling the
tokenizer could not read was a merge nobody asked for.

Each case is asserted twice: the tokens ``critical_signature`` records, and
the merge a user sees. That is the critique's two-read self-consistency merge
and the ledger's ingest merge, both through ``critique._is_duplicate``. A
signature that is right on paper and still lets two pipe sizes collapse has
fixed nothing. Every pair shares enough prose (``_token_overlap`` at or above
the 0.7 duplicate threshold) that the text alone *would* merge it, so the
signature is what decides.

The tables from WP-04.1 hold pairs that differ in every quantity they carry.
Remediation WP-04.2 (N1) replaced the compatibility rule behind them, so the
tables now also hold pairs whose conflict sits beside a shared value
(``6 in`` / ``4 in`` beside a shared ``100 psi``; ``12'-6"`` / ``12'-8"``, both
``12 ft``): the "N1" rows, and the corroboration, retention and recorded-limit
tables at the end. The rule itself, and the tag half of it, is pinned in
``tests/test_signature_compatibility.py``.

Hermetic (I-4): pure data, no client, no PDF.
"""
from __future__ import annotations

import re

import pytest

from drawing_analyzer.critique import (
    _TEXT_DUP_THRESHOLD,
    _token_overlap,
    critical_signature,
    merge_self_consistency,
    signatures_compatible,
)
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import Finding


def _finding(text: str, quote: str = "") -> Finding:
    return Finding(
        sheet_id="M-101", source_name="mech.pdf", page_index=0,
        category="coordination", severity="medium", text=text, source_quote=quote,
    )


def _tokens(text: str) -> list[str]:
    return critical_signature(_finding(text))["measurements"]


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

_B2_HYPHENATED_UNITS = [
    ("Provide 6-inch drain", ["6in"]),
    ("Provide 6-INCH drain", ["6in"]),
    ("Provide 6-in drain", ["6in"]),
    ("Provide 6-in. drain", ["6in"]),
    ("Provide 6 - inch drain", ["6in"]),
    ("Provide 6 in drain", ["6in"]),
    ("Provide 2-1/2-inch pipe", ["2.5in"]),
    # "Foot" and "gallon" were missing outright, and the hyphenated adjective
    # ("a 10-foot clearance", "a 100-gallon heater") is how they are written.
    ("Maintain a 10-foot clearance", ["10ft"]),
    ("Provide a 100-gallon water heater", ["100gal"]),
    ("Provide 20-amp breaker", ["20amp"]),
    ("Feed at 480-volt", ["480volt"]),
]

_B3_THOUSANDS_GROUPS = [
    ("Supply 12,500 cfm", ["12500cfm"]),
    ("Supply 12500 cfm", ["12500cfm"]),
    ("Supply 12,500cfm", ["12500cfm"]),
    ("Supply 1,500 cfm", ["1500cfm"]),
    # The old lookbehind let a match start after the comma, so "15,000" signed
    # as "000" -- the value zero.
    ("Supply 15,000 cfm", ["15000cfm"]),
    ("Flow 1,500.5 gpm", ["1500.5gpm"]),
    ("Flow -12,500 cfm", ["-12500cfm"]),
    # A grouping that is not a valid thousands number is kept whole: never
    # the trailing fragment "500", and never guessed to be 12,500 either.
    ("Flow 1,2,500 cfm", ["1,2,500cfm"]),
    ("Flow 1,2500 cfm", ["1,2500cfm"]),
    ("Flow 12,5 mm", ["12,5mm"]),
]

_B12_DEGREES = [
    ("Setpoint 90 deg F", ["90°f"]),
    ("Setpoint 90 DEG F", ["90°f"]),
    ("Setpoint 90 deg. F", ["90°f"]),
    ("Setpoint 90 degree F", ["90°f"]),
    ("Setpoint 90 degrees F", ["90°f"]),
    ("Setpoint 90 degF", ["90°f"]),
    ("Setpoint 90 degrees Fahrenheit", ["90°f"]),
    ("Setpoint 90°F", ["90°f"]),
    ("Setpoint 90 °F", ["90°f"]),
    ("Setpoint 90° F", ["90°f"]),
    ("Setpoint 32 deg C", ["32°c"]),
    ("Setpoint 32 degC", ["32°c"]),
    ("Setpoint 32°C", ["32°c"]),
    ("Setpoint 32 degrees Celsius", ["32°c"]),
    # Compact schedule forms keep the scale, as "°F" always did.
    ("EAT 80°FDB", ["80°f"]),
    # An angle: the degree mark with no scale.
    ("Provide a 45 deg elbow", ["45°"]),
    ("Provide a 45 degree elbow", ["45°"]),
    ("Provide a 45-degree elbow", ["45°"]),
    ("Provide a 45° elbow", ["45°"]),
    ("Provide a 45° Flange", ["45°"]),
    ("Rotate the 90 deg flange", ["90°"]),
    ("Rotate 90 deg F-1 fan", ["90°"]),
    # A scale is never inferred: a bare 90° is not 90°F.
    ("Setpoint 90°", ["90°"]),
]

_N19_SIZES = [
    ("Duct 24x12", ["24x12"]),
    ("Duct 24 x 12", ["24x12"]),
    ("Duct 24X12", ["24x12"]),
    ("Duct 24\u00d712", ["24x12"]),  # the multiplication sign
    ('Duct 24"x12"', ["24x12in"]),
    ('Duct 24" x 12"', ["24x12in"]),
    ('Duct 24"x12', ["24x12in"]),
    ("Duct 24x12 in", ["24x12in"]),
    ("A 24x12-inch duct", ["24x12in"]),
    ("Duct 24-in x 12-in", ["24x12in"]),
    ("Duct 600x300 mm", ["600x300mm"]),
    ("Duct 1,200x600 mm", ["1200x600mm"]),
    ('Conduit box 1-1/2" x 1-1/2"', ["1.5x1.5in"]),
    ("Plenum 24x12x6", ["24x12x6"]),
    ("Room is 10'x12'", ["10x12ft"]),
    ("2x4 lay-in fixture", ["2x4"]),
]

_N19_VOLTS = [
    ("RTU-1 at 480V", ["480volt"]),
    ("RTU-1 at 480v", ["480volt"]),
    ("RTU-1 at 480 volts", ["480volt"]),
    ("Feed 480V/3PH/60HZ", ["480volt"]),
    ("Controls at 24VAC", ["24vac"]),
    ("Controls at 24VDC", ["24vdc"]),
    # A voltage pair is one system, low first. "120/208 volts" used to read as
    # the fraction 120/208 -- about 0.58 volts.
    ("Panel is 120/208V", ["120/208volt"]),
    ("Panel is 208Y/120V", ["120/208volt"]),
    ("Panel is 120/208 volts", ["120/208volt"]),
    ("Panel is 480Y/277V", ["277/480volt"]),
    ("Motor 208-230V", ["208..230volt"]),
    # Units that already signed are unchanged.
    ("Transformer 500VA", ["500va"]),
    ("Feeder 15kV", ["15kv"]),
]

_N19_AMPS = [
    ("Provide 20A/1P breaker", ["20amp"]),
    ("Provide 20A-2P breaker", ["20amp"]),
    ("Provide 20A 3P breaker", ["20amp"]),
    ("Provide 20A 1-POLE breaker", ["20amp"]),
    ("Provide 20A breaker", ["20amp"]),
    ("Provide 30A fused disconnect", ["30amp"]),
    ("Provide 200A MLO panelboard", ["200amp"]),
    ("MCA 18.2A MOCP 25A", ["18.2amp", "25amp"]),
    ("MOCP: 25A", ["25amp"]),
    ("BREAKER: 20A", ["20amp"]),
    ("Room 101A 20A/1P breaker", ["20amp"]),
    ("Provide 20 amp breaker", ["20amp"]),
]

_N19_RANGES_AND_LISTS = [
    ("Maintain 4-6 in clearance", ["4..6in"]),
    ("Maintain 4 - 6 in clearance", ["4..6in"]),
    ("Maintain 4-6-inch clearance", ["4..6in"]),
    ("Maintain 6-4 in clearance", ["4..6in"]),
    ("Setpoint band 65-75°F", ["65..75°f"]),
    ("Flow 1,000-2,000 cfm", ["1000..2000cfm"]),
    ("Outside air 10-20%", ["10..20%"]),
    ("Provide 2,4,6 in drains", ["2,4,6in"]),
]

# Behaviour item 23 (and the tag rule) established; it must not move.
_SAFEGUARDS = [
    ('Provide 1/2" drain', ["0.5in"]),
    ('Provide 2" drain', ["2in"]),
    ('2 1/2" pipe', ["2.5in"]),
    ('2-1/2" pipe', ["2.5in"]),
    ('2.5" pipe', ["2.5in"]),
    ("Provide 2-1/2 in pipe", ["2.5in"]),           # a mixed number, not a range
    ("invert set -6 in below datum", ["-6in"]),
    ('drop -2-1/2" from datum', ["-2.5in"]),
    ("Maintain 4 -6 in", ["-6in"]),                  # a lopsided hyphen is a sign
    ('the note says "6 in clear"', ["6in"]),
    ("maintain 12'-6\" clear", ["12ft", "6in"]),     # feet-inches stays two tokens
    ("maintain 12'-8\" clear", ["12ft", "8in"]),
    # A feet-inches W×H is not a size this form can hold: its halves sign alone.
    ("elevation 10'-6\" x 12'-0\"", ["0in", "10ft", "12ft", "6in"]),
    ("elevation 12' - 6\" x 10'", ["10ft", "12ft", "6in"]),
    ("elevation 12'-6\"x10'-0\"", ["0in", "10ft", "12ft", "6in"]),
    ("room is 10'x12'-6\"", ["10ft", "12ft", "6in"]),
    ("relief set at 20 psig", ["20psig"]),           # psig is not folded into psi
    ("relief set at 20 psi", ["20psi"]),
    ("pump P-1 draws 6 amps", ["6amp"]),              # plurals fold
    ("pump P-1 draws 6 amp", ["6amp"]),
    ("route clearance to M-101 in the room", []),
    ("pump P-1 voltage rating is 480 at panel", []),
    ("Zone A/2 in the north wing", []),
    ("see detail 3/A4 in the corner", []),
    # A sign is refused right after a unit mark, where the hyphen is a join.
    ("Setpoint band 90°-95°F", ["90°", "95°f"]),
    ("Outside air 10%-20%", ["10%", "20%"]),
]

# Shapes a quantity rule must NOT read: room, grid and panel names, keynotes,
# equipment tags, slope ratios, multiplication, and prose commas.
_NEGATIVE_CORPUS = [
    ("Room 101A", []),
    ("RM 101A", []),
    ("Corridor 101A", []),
    ("Electrical room 101A", []),
    ("Panel 2A", []),
    ("PANEL 2A BKR 12", []),
    ("Panel 15A breaker 3", []),
    ("circuit 2A breaker", []),
    ("grid 2A", []),
    ("column line 2A", []),
    ("between grids 2A and 3", []),
    ("at 2A/C", []),
    ("keynote 3A", []),
    ("note 3a breaker", []),
    ("detail 4A", []),
    ("Type 2A fixture", []),
    ("Level 1A", []),
    ("panel LP-2A", []),
    ("AHU-2A", []),
    ("LP2A", []),
    ("EF-1A", []),
    ("Circuit LP-1-20A", []),
    ("VAV-2V", []),
    ("3H:1V slope", []),
    ("slope 1V:3H", []),
    ("W12x26 beam", []),
    ("L4x4x1/4 angle", []),
    ("Provide 4 x 25 gpm pumps", ["25gpm"]),
    ('Board 6" x 12\'', ["12ft", "6in"]),
    # A rejected size keeps its second dimension, tight or spaced: it follows
    # an "x" that a number may not otherwise start after (Codex review, P1).
    ("Provide 4x25 gpm pumps", ["25gpm"]),
    ('Board 6"x12\' cut to length', ["12ft", "6in"]),
    ("at column 4, 10 ft from the wall", ["10ft"]),
    # Loose commas are prose punctuation as often as list separators, so they
    # never join numbers into a list ("column 4, 10 ft" above). Only a tight
    # run is one token; a spaced list keeps what it always had.
    ("Provide 2, 4, 6 in drains", ["6in"]),
]


@pytest.mark.parametrize(
    "text,expected",
    _B2_HYPHENATED_UNITS + _B3_THOUSANDS_GROUPS + _B12_DEGREES + _N19_SIZES
    + _N19_VOLTS + _N19_AMPS + _N19_RANGES_AND_LISTS + _SAFEGUARDS + _NEGATIVE_CORPUS,
)
def test_measurement_tokens(text, expected):
    assert _tokens(text) == sorted(expected)


# Every token is ``<value><unit>``. ``<value>`` is one number, or ONE composite
# quantity: a list (``,``), a range (``..``), a size (``x``) or a voltage pair
# (``/``). This is the representation WP-04.2's per-unit comparison consumes.
_VALUE = r"-?\d+(?:\.\d+)?"
_TOKEN_GRAMMAR = re.compile(
    rf"(?P<value>{_VALUE}(?:(?:,{_VALUE})+|\.\.{_VALUE}|(?:x{_VALUE}){{1,2}}|/\d+)?)"
    r"(?P<unit>[a-z%°]*)"
)


def test_every_token_is_a_value_followed_by_a_unit():
    corpus = (
        _B2_HYPHENATED_UNITS + _B3_THOUSANDS_GROUPS + _B12_DEGREES + _N19_SIZES
        + _N19_VOLTS + _N19_AMPS + _N19_RANGES_AND_LISTS + _SAFEGUARDS + _NEGATIVE_CORPUS
    )
    for text, _expected in corpus:
        for token in _tokens(text):
            assert _TOKEN_GRAMMAR.fullmatch(token), (text, token)


# --------------------------------------------------------------------------- #
# The merges: conflicting quantities stay two findings
# --------------------------------------------------------------------------- #

_CONFLICTS = {
    "B2 6-inch vs 4-inch": (
        "Provide 6-inch drain at column line 4",
        "Provide 4-inch drain at column line 4",
    ),
    "B2 6-in vs 4-in": (
        "Provide 6-in drain at column line 4",
        "Provide 4-in drain at column line 4",
    ),
    "B2 6-in. vs 4-in.": (
        "Provide 6-in. drain at column line 4",
        "Provide 4-in. drain at column line 4",
    ),
    "B3 12,500 vs 1,500": (
        "Supply air to AHU-1 serving the east data hall is 12,500 cfm per the mechanical schedule",
        "Supply air to AHU-1 serving the east data hall is 1,500 cfm per the mechanical schedule",
    ),
    "B3 15,000 vs 10,000": (
        "Supply air to AHU-3 serving the north data hall is 15,000 cfm per the mechanical schedule",
        "Supply air to AHU-3 serving the north data hall is 10,000 cfm per the mechanical schedule",
    ),
    "B3 1,2,500 vs 500": (
        "Return air at RTU-2 serving the west data hall reads 1,2,500 cfm on the mechanical schedule",
        "Return air at RTU-2 serving the west data hall reads 500 cfm on the mechanical schedule",
    ),
    "B3 1,2,500 vs 12,500": (
        "Return air at RTU-2 serving the west data hall reads 1,2,500 cfm on the mechanical schedule",
        "Return air at RTU-2 serving the west data hall reads 12,500 cfm on the mechanical schedule",
    ),
    "B12 90 deg F vs 90 deg C": (
        "Supply air setpoint for RTU-2 serving the lab is 90 deg F in the sequence of operations",
        "Supply air setpoint for RTU-2 serving the lab is 90 deg C in the sequence of operations",
    ),
    "B12 90 degrees F vs 90 degrees C": (
        "Supply air setpoint for RTU-2 serving the lab is 90 degrees F in the sequence of operations",
        "Supply air setpoint for RTU-2 serving the lab is 90 degrees C in the sequence of operations",
    ),
    "B12 90°F vs 90°C": (
        "Supply air setpoint for RTU-2 serving the lab is 90°F in the sequence of operations",
        "Supply air setpoint for RTU-2 serving the lab is 90°C in the sequence of operations",
    ),
    "B12 no scale is inferred: 90° vs 90°F": (
        "Supply air setpoint for RTU-2 serving the lab is 90° in the sequence of operations",
        "Supply air setpoint for RTU-2 serving the lab is 90°F in the sequence of operations",
    ),
    "N19 24x12 vs 24x10": (
        "Duct 24x12 serving VAV-3 conflicts with the steel beam at grid C",
        "Duct 24x10 serving VAV-3 conflicts with the steel beam at grid C",
    ),
    'N19 24" x 12" vs 24" x 10"': (
        'Duct 24" x 12" serving VAV-3 conflicts with the steel beam at grid C',
        'Duct 24" x 10" serving VAV-3 conflicts with the steel beam at grid C',
    ),
    "N19 24x12x6 vs 24x12x8": (
        "Plenum box 24x12x6 above the ceiling conflicts with the sprinkler main",
        "Plenum box 24x12x8 above the ceiling conflicts with the sprinkler main",
    ),
    # Spaced, so no stray "x12" tag separates them by accident: before WP-04.1
    # both signed {10ft, ...} and the shared 10ft let them merge.
    "N19 10' x 12' vs 10' x 14'": (
        "Electrical room is 10' x 12' which is short of the working clearance required",
        "Electrical room is 10' x 14' which is short of the working clearance required",
    ),
    "N19 20A vs 30A": (
        "Provide 20A breaker for exhaust fan EF-1 on panel LP-1",
        "Provide 30A breaker for exhaust fan EF-1 on panel LP-1",
    ),
    "N19 20A/1P vs 30A/1P": (
        "Provide 20A/1P breaker for exhaust fan EF-1 on panel LP-1",
        "Provide 30A/1P breaker for exhaust fan EF-1 on panel LP-1",
    ),
    "N19 480V vs 208V": (
        "RTU-1 is scheduled at 480V but is fed from panel HP-1 on this sheet",
        "RTU-1 is scheduled at 208V but is fed from panel HP-1 on this sheet",
    ),
    "N19 120/208V vs 120/240V": (
        "Panel LP-2 is 120/208V but the transformer secondary on this sheet is shown differently",
        "Panel LP-2 is 120/240V but the transformer secondary on this sheet is shown differently",
    ),
    "N19 24VAC vs 24VDC": (
        "Controls transformer is 24VAC for the damper actuators on this floor",
        "Controls transformer is 24VDC for the damper actuators on this floor",
    ),
    "N19 4-6 in vs 4-8 in": (
        "Maintain 4-6 in clearance around the base of pump P-1",
        "Maintain 4-8 in clearance around the base of pump P-1",
    ),
    "N19 a range is one quantity: 4-6 in vs 6 in": (
        "Maintain 4-6 in clearance around the base of pump P-1",
        "Maintain 6 in clearance around the base of pump P-1",
    ),
    "N19 2,4,6 in vs 3,5,6 in": (
        "Provide 2,4,6 in floor drains along the east wall of the main mechanical room per the plumbing plan",
        "Provide 3,5,6 in floor drains along the east wall of the main mechanical room per the plumbing plan",
    ),
    "N19 2,4,6 in vs 2,4,8 in": (
        "Provide 2,4,6 in floor drains along the east wall of the main mechanical room per the plumbing plan",
        "Provide 2,4,8 in floor drains along the east wall of the main mechanical room per the plumbing plan",
    ),
    "N19 a rejected tight size keeps its tail: 4x25 gpm vs 4x30 gpm": (
        "Provide 4x25 gpm circulating pumps along the east wall of the central plant",
        "Provide 4x30 gpm circulating pumps along the east wall of the central plant",
    ),
    'item 23: 1/2" vs 2"': (
        'Provide 1/2" drain at the low point of the loop',
        'Provide 2" drain at the low point of the loop',
    ),
    "item 23: -6 in vs 6 in": (
        "Set the invert -6 in below the datum at the cleanout",
        "Set the invert 6 in below the datum at the cleanout",
    ),
    # N1 (WP-04.2): one shared value no longer excuses a conflicting one. Each
    # pair below shares a quantity and merged before WP-04.2.
    "N1 12'-6\" vs 12'-8\" (both 12 ft)": (
        "Maintain 12'-6\" clear headroom under the main duct at the M-101 riser",
        "Maintain 12'-8\" clear headroom under the main duct at the M-101 riser",
    ),
    "N1 6 in vs 4 in beside a shared 100 psi": (
        "Pump P-1 discharge pipe is 6 in at 100 psi per the pump schedule",
        "Pump P-1 discharge pipe is 4 in at 100 psi per the pump schedule",
    ),
    "N1 500 gpm vs 550 gpm beside a shared 100 psi": (
        "Pump P-1 is scheduled at 500 gpm at 100 psi on the pump schedule for the east data hall",
        "Pump P-1 is scheduled at 550 gpm at 100 psi on the pump schedule for the east data hall",
    ),
    'N1 6" x 12\' vs 6" x 14\' (both 6 in)': (
        'Board 6" x 12\' at the east wall is cut from the wrong stock per the framing detail',
        'Board 6" x 14\' at the east wall is cut from the wrong stock per the framing detail',
    ),
    # Within one unit: a list written with a unit on every element, and a
    # shown/required pair, each sharing one value.
    "N1 2 in, 4 in and 6 in vs 3 in, 5 in and 6 in (one shared size)": (
        "Provide 2 in, 4 in and 6 in floor drains along the east wall of the main "
        "mechanical room per the plumbing plan",
        "Provide 3 in, 5 in and 6 in floor drains along the east wall of the main "
        "mechanical room per the plumbing plan",
    ),
    "N1 500 gpm shown vs 550 or 600 gpm required": (
        "Pump P-1 shows 500 gpm but the pump schedule requires 550 gpm at the design point",
        "Pump P-1 shows 500 gpm but the pump schedule requires 600 gpm at the design point",
    ),
    # Units the tokenizer keeps apart but that measure one kind of quantity:
    # a value shared elsewhere must not hide their conflict either.
    "N1 90°F vs 90°C beside a shared 6 in": (
        "Supply air setpoint for AHU-2 is 90°F at the 6 in duct heater per the sequence",
        "Supply air setpoint for AHU-2 is 90°C at the 6 in duct heater per the sequence",
    ),
    "N1 20 psig vs 20 psi beside a shared 6 in": (
        "Relief valve RV-1 on the 6 in main is set at 20 psig per the valve schedule",
        "Relief valve RV-1 on the 6 in main is set at 20 psi per the valve schedule",
    ),
    "N1 120V vs 24VAC controls beside a shared 480V": (
        "Motor for RTU-1 is 480V with 120V controls per the electrical schedule",
        "Motor for RTU-1 is 480V with 24VAC controls per the electrical schedule",
    ),
    "N1 6 in vs 100 mm beside a shared 100 psi": (
        "Pump P-1 discharge pipe is 6 in at 100 psi per the pump schedule",
        "Pump P-1 discharge pipe is 100 mm at 100 psi per the pump schedule",
    ),
    "N1 10 ft vs 12 in clearance beside a shared 6 in": (
        "The 6 in sprinkler main needs 10 ft clearance from the duct per the coordination plan",
        "The 6 in sprinkler main needs 12 in clearance from the duct per the coordination plan",
    ),
    # Codex review, P1 on PR #158: a flow or a power written in another unit
    # of the same quantity was a kind of its own, so a shared value hid it.
    "N1 500 gpm vs 12,000 gph beside a shared 100 psi": (
        "Pump P-1 is scheduled at 500 gpm at 100 psi on the pump schedule for the east "
        "data hall chilled water loop",
        "Pump P-1 is scheduled at 12,000 gph at 100 psi on the pump schedule for the east "
        "data hall chilled water loop",
    ),
    "N1 5 hp vs 7.5 kW beside a shared 480V": (
        "Fan EF-1 motor is 5 hp at 480V per the fan schedule for the east data hall",
        "Fan EF-1 motor is 7.5 kW at 480V per the fan schedule for the east data hall",
    ),
    "N1 500 VA vs 1 kVA beside a shared 120V": (
        "Transformer T-1 is 500 VA at 120V per the control panel schedule for the east data hall",
        "Transformer T-1 is 1 kVA at 120V per the control panel schedule for the east data hall",
    ),
    "N1 24x12 vs 24x10 in beside a shared 1,200 cfm": (
        "Duct 24x12 at 1,200 cfm conflicts with the steel beam at grid C near VAV-3",
        "Duct 24x10 in at 1,200 cfm conflicts with the steel beam at grid C near VAV-3",
    ),
}


@pytest.mark.parametrize("pair", sorted(_CONFLICTS))
def test_conflicting_quantities_stay_two_findings(pair):
    a, b = _CONFLICTS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD, "the prose alone would merge these"
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert sa["measurements"] and sb["measurements"], (sa, sb)
    assert not signatures_compatible(sa, sb)
    assert _surviving(a, b) == (2, 2)


@pytest.mark.parametrize("pair", sorted(_CONFLICTS))
def test_a_quantity_conflict_is_named_as_the_measurements_axis(pair):
    # WP-04.2: the axes come from the rule itself (critique.signature_conflicts),
    # which the A/B harness now reports instead of restating the rule.
    from drawing_analyzer.critique import signature_conflicts

    a, b = _CONFLICTS[pair]
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert "measurements" in signature_conflicts(sa, sb)


# --------------------------------------------------------------------------- #
# The merges: one quantity spelled two ways is one finding
# --------------------------------------------------------------------------- #

_EQUIVALENTS = {
    "B2 6-inch = 6 in": (
        "Provide 6-inch drain at column line 4",
        "Provide 6 in drain at column line 4",
    ),
    "B3 12,500 = 12500": (
        "Supply air to AHU-1 serving the east data hall is 12,500 cfm per the mechanical schedule",
        "Supply air to AHU-1 serving the east data hall is 12500 cfm per the mechanical schedule",
    ),
    "B3 1,500.5 = 1500.5": (
        "Flow at the riser serving the east data hall is 1,500.5 gpm per the fire protection schedule",
        "Flow at the riser serving the east data hall is 1500.5 gpm per the fire protection schedule",
    ),
    "B12 90 deg F = 90°F": (
        "Supply air setpoint for RTU-2 serving the lab is 90 deg F in the sequence of operations",
        "Supply air setpoint for RTU-2 serving the lab is 90°F in the sequence of operations",
    ),
    "B12 90 degrees F = 90 degF": (
        "Supply air setpoint for RTU-2 serving the lab is 90 degrees F in the sequence of operations",
        "Supply air setpoint for RTU-2 serving the lab is 90 degF in the sequence of operations",
    ),
    "B12 45 deg = 45°": (
        "Provide 45 deg elbow at the riser offset near grid B",
        "Provide 45° elbow at the riser offset near grid B",
    ),
    'N19 24" x 12" = 24x12 in': (
        'Duct 24" x 12" serving VAV-3 conflicts with the steel beam at grid C on the level 2 plan',
        "Duct 24x12 in serving VAV-3 conflicts with the steel beam at grid C on the level 2 plan",
    ),
    "N19 480V = 480 volts": (
        "Rooftop unit RTU-1 is scheduled at 480V but is fed from panel HP-1 on this sheet",
        "Rooftop unit RTU-1 is scheduled at 480 volts but is fed from panel HP-1 on this sheet",
    ),
    "N19 20A/1P = 20 amp": (
        "Provide 20A/1P breaker for exhaust fan EF-1 on panel LP-1 per the electrical schedule",
        "Provide 20 amp breaker for exhaust fan EF-1 on panel LP-1 per the electrical schedule",
    ),
    'item 23: 2 1/2" = 2.5"': (
        'Provide 2 1/2" pipe at the riser offset near grid B',
        'Provide 2.5" pipe at the riser offset near grid B',
    ),
    "N1 6-inch = 6 in beside a shared 100 psi": (
        "Pump P-1 discharge pipe is 6-inch at 100 psi per the pump schedule",
        "Pump P-1 discharge pipe is 6 in at 100 psi per the pump schedule",
    ),
}


@pytest.mark.parametrize("pair", sorted(_EQUIVALENTS))
def test_one_quantity_spelled_two_ways_is_one_finding(pair):
    a, b = _EQUIVALENTS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD, "the prose alone would merge these"
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert sa["measurements"] and sa["measurements"] == sb["measurements"], (sa, sb)
    assert _surviving(a, b) == (1, 1)


# --------------------------------------------------------------------------- #
# A name read as a quantity would hide a real conflict (N1's mechanism)
# --------------------------------------------------------------------------- #

_SHARED_NAME_CONFLICTS = {
    "room 101A": (
        "Room 101A: provide 6 in floor drain at the sink near the east wall",
        "Room 101A: provide 4 in floor drain at the sink near the east wall",
    ),
    "grid 2A": (
        "At grid 2A provide 6 in floor drain at the sink near the east wall",
        "At grid 2A provide 4 in floor drain at the sink near the east wall",
    ),
    "panel 2A": (
        "Panel 2A breaker feeds a 6 in duct heater near the east wall",
        "Panel 2A breaker feeds a 4 in duct heater near the east wall",
    ),
}


@pytest.mark.parametrize("name", sorted(_SHARED_NAME_CONFLICTS))
def test_a_shared_name_is_not_a_shared_quantity(name):
    """A compact-amp rule that read "101A" as 101 amperes would put the same
    token in both findings. Under the disjoint-set rule WP-04.1 shipped with,
    that one shared value made them compatible and merged a 6 in drain into a
    4 in one (N1). WP-04.2's rule would still keep this pair apart, but a name
    must not become a quantity whatever the rule: it contributes nothing, and
    the pair stays two findings."""
    a, b = _SHARED_NAME_CONFLICTS[name]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    assert _tokens(a) == ["6in"] and _tokens(b) == ["4in"]
    assert _surviving(a, b) == (2, 2)


# --------------------------------------------------------------------------- #
# The compatibility rule (remediation WP-04.2, N1): what still merges
# --------------------------------------------------------------------------- #

# One finding adds detail the other lacks: another quantity, a second value in
# the same unit, or another length. That is corroboration with more evidence,
# and it must keep merging.
_CORROBORATIONS = {
    "another unit added: 500 gpm vs 500 gpm at 100 psi": (
        "Pump P-1 is scheduled at 500 gpm on the pump schedule for the east data hall",
        "Pump P-1 is scheduled at 500 gpm at 100 psi on the pump schedule for the east data hall",
    ),
    "a value added in the same unit: 6 in vs 6 in, provide 8 in": (
        "The 6 in main serving the east data hall is undersized for the design demand",
        "The 6 in main serving the east data hall is undersized for the design demand; provide 8 in",
    ),
    "another length added: 12'-6\" vs 12'-6\", 10' from the wall": (
        "Maintain 12'-6\" clear headroom under the main duct at the M-101 riser",
        "Maintain 12'-6\" clear headroom under the main duct at the M-101 riser, 10' from the wall",
    ),
}


@pytest.mark.parametrize("pair", sorted(_CORROBORATIONS))
def test_a_quantity_one_side_adds_still_merges(pair):
    a, b = _CORROBORATIONS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert set(sa["measurements"]) < set(sb["measurements"]), (sa, sb)
    assert signatures_compatible(sa, sb)
    assert _surviving(a, b) == (1, 1)


# Two findings that share no quantity at all conflict whatever their units, as
# they did before WP-04.2. A rule that compared only the units both sides
# carry would have started merging these.
_NO_SHARED_QUANTITY = {
    "6 in vs 150 mm": (
        "Pump P-1 discharge pipe is 6 in per the pump schedule for the east data hall",
        "Pump P-1 discharge pipe is 150 mm per the pump schedule for the east data hall",
    ),
    "24x12 vs 24x10 in (no unit vs in)": (
        "Duct 24x12 serving VAV-3 conflicts with the steel beam at grid C",
        "Duct 24x10 in serving VAV-3 conflicts with the steel beam at grid C",
    ),
}


@pytest.mark.parametrize("pair", sorted(_NO_SHARED_QUANTITY))
def test_findings_that_share_no_quantity_stay_two(pair):
    a, b = _NO_SHARED_QUANTITY[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert sa["measurements"] and sb["measurements"]
    assert set(sa["measurements"]).isdisjoint(sb["measurements"])
    assert not signatures_compatible(sa, sb)
    assert _surviving(a, b) == (2, 2)


# Deliberate conservative duplicate retention (plan WP-04 acceptance). These
# pairs may be one issue, but the signature cannot show it, so they stay two
# findings. The safe error: a reviewer sees both rather than one that hides a
# disagreement.
_CONSERVATIVE_RETENTION = {
    # NPS 6 is DN 150, but no value is converted between units (plan WP-04
    # step 3): a length on each side that the other lacks conflicts.
    "one pipe in two unit systems: 6 in vs 150 mm beside a shared 100 psi": (
        "Pump P-1 discharge pipe is 6 in at 100 psi per the pump schedule",
        "Pump P-1 discharge pipe is 150 mm at 100 psi per the pump schedule",
    ),
    "one clearance in two units: 3 ft vs 36 in beside a shared 6 in": (
        "The 6 in sprinkler main needs 3 ft clearance from the duct per the coordination plan",
        "The 6 in sprinkler main needs 36 in clearance from the duct per the coordination plan",
    ),
    # A loose-comma list signs only its last element (WP-04.1, by decision),
    # so it cannot be told from the tight list that names the same sizes.
    "a partial list signature against a full one: 2, 4, 6 in vs 2,4,6 in": (
        "Provide 2, 4, 6 in floor drains at 100 psi test along the east wall of the mechanical room",
        "Provide 2,4,6 in floor drains at 100 psi test along the east wall of the mechanical room",
    ),
}


@pytest.mark.parametrize("pair", sorted(_CONSERVATIVE_RETENTION))
def test_pairs_kept_apart_by_design(pair):
    a, b = _CONSERVATIVE_RETENTION[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert not signatures_compatible(sa, sb)
    assert _surviving(a, b) == (2, 2)


# Recorded limits: pairs that still merge although they may be two issues.
# Each pins today's outcome so that a change to it is deliberate: a slice that
# closes one flips its row into _CONFLICTS.
_RECORDED_LIMITS = {
    # Quantity roles are not extracted anywhere. Both findings carry {4in, 6in}
    # and the same words, so nothing in the signature or the prose separates
    # them (WP-04.3).
    "swapped roles: 6 in main, 4 in branch vs 4 in main, 6 in branch": (
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
        "Provide 4 in main and 6 in branch at the riser serving the east data hall",
    ),
    # A set holds a value once, so a value repeated in two roles reads as one
    # value, and {6in} is included in {6in, 8in} (WP-04.3).
    "one value in two roles: 6 in supply and return vs 6 in supply, 8 in return": (
        "Provide 6 in supply and 6 in return at the riser serving the east data hall",
        "Provide 6 in supply and 8 in return at the riser serving the east data hall",
    ),
    # Feet-inches is two tokens (WP-04.1, by decision), so a bare 12' reads as
    # the feet half with no inches given, not as 12'-0".
    "a bare feet value: 12'-6\" vs 12'": (
        "Maintain 12'-6\" clear headroom under the main duct at the M-101 riser",
        "Maintain 12' clear headroom under the main duct at the M-101 riser",
    ),
    # WP-04.1's partial signatures, left by decision: each side signs only the
    # quantity the tokenizer can read, and those agree.
    "a to range signs its far end: 4 to 6 in vs 6 in": (
        "Maintain 4 to 6 in clearance around the base of pump P-1 on the plan",
        "Maintain 6 in clearance around the base of pump P-1 on the plan",
    ),
    "loose-comma lists sign their last element: 2, 4, 6 in vs 3, 5, 6 in": (
        "Provide 2, 4, 6 in floor drains along the east wall of the main mechanical room",
        "Provide 3, 5, 6 in floor drains along the east wall of the main mechanical room",
    ),
    "a bare 20A needs electrical context: 20A vs 30A on a shared 120V": (
        "Provide 20A 120V circuit for exhaust fan EF-1 on panel LP-1",
        "Provide 30A 120V circuit for exhaust fan EF-1 on panel LP-1",
    ),
}


@pytest.mark.parametrize("pair", sorted(_RECORDED_LIMITS))
def test_recorded_limits_still_merge(pair):
    a, b = _RECORDED_LIMITS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert signatures_compatible(sa, sb)
    assert _surviving(a, b) == (1, 1)
