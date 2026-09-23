"""The compatibility rule behind the critical signature (remediation WP-04.2, N1).

A critical signature lists what a finding asserts: its tags, its quantities,
its absence polarity and its cross-sheet legs (``critique.critical_signature``).
Two findings whose prose reads alike merge only when their signatures are
compatible. Until WP-04.2 "compatible" meant "not disjoint", so one shared
value excused everything else: ``6 in … 100 psi`` and ``4 in … 100 psi`` merged
on the pressure, ``12'-6"`` and ``12'-8"`` on the ``12 ft``, and ``P-1 + V-3``
and ``P-1 + V-4`` on the pump (N1).

The rule now (``critique.signature_conflicts``, whose negation is
``signatures_compatible``):

* **Quantities**, compared per kind. A kind is one unit, or a group of units
  that measure one kind of quantity: lengths (``in``, ``ft``, ``mm``, ``cm``,
  and a W×H size written without a unit), degrees (``°``, ``°f``, ``°c``),
  pressures (``psi``, ``psig``), voltages (``volt``, ``vac``, ``vdc``,
  ``kv``), liquid flow (``gpm``, ``gph``, ``gpd``), real power (``hp``,
  ``kw``) and apparent power (``va``, ``kva``). For every kind both findings
  carry, one finding's tokens of that kind must include the other's. Tokens
  compare whole: nothing is converted (``12 in`` never equals ``1 ft``) and a
  composite is never split. Two findings that share no token at all still
  conflict, as they always did.
* **Tags**: one finding's tags must include the other's.
* Absence polarity and cross-sheet legs are unchanged.

So one side may add detail (another quantity, a value in the same unit, a
reference the other omits) and still merge, but a value or tag on EACH side
that the other lacks keeps the two apart. The rule only ever blocks more than
the old one; it never merges a pair the old rule kept apart.

Every pair here is asserted three ways: the axes ``signature_conflicts``
names, and the merge a user sees in the critique's two-read merge and in the
ledger. Every pair shares enough prose (``_token_overlap`` at or above the 0.7
duplicate threshold) that the text alone would merge it, so the signature is
what decides. Quantity pairs live beside the tokenizer's in
``tests/test_quantity_signature.py``.

``signature_conflicts`` is imported inside the tests that need it, so that on
a tree without it only those tests fail and the rest still say what they
check.

Hermetic (I-4): pure data, no client, no PDF.
"""
from __future__ import annotations

import itertools

import pytest

from drawing_analyzer.critique import (
    _TEXT_DUP_THRESHOLD,
    _token_overlap,
    critical_signature,
    merge_self_consistency,
    signatures_compatible,
)
from drawing_analyzer.ledger import Ledger, reconcile_post_anchor
from drawing_analyzer.models import Anchor, Finding


def _finding(text: str, quote: str = "") -> Finding:
    return Finding(
        sheet_id="M-101", source_name="mech.pdf", page_index=0,
        category="coordination", severity="medium", text=text, source_quote=quote,
    )


def _surviving(text_a: str, text_b: str) -> tuple[int, int]:
    """How many findings survive the critique merge and the ledger merge."""
    critique = merge_self_consistency([[_finding(text_a)], [_finding(text_b)]])
    ledger = Ledger()
    ledger.add([_finding(text_a)], source="digest")
    ledger.add([_finding(text_b)], source="critique_1")
    return len(critique), len(ledger)


def _conflicts(text_a: str, text_b: str) -> list[str]:
    from drawing_analyzer.critique import signature_conflicts

    return signature_conflicts(
        critical_signature(_finding(text_a)), critical_signature(_finding(text_b))
    )


# --------------------------------------------------------------------------- #
# Tags: one shared tag no longer excuses another
# --------------------------------------------------------------------------- #

# Each side names a target of the same role that the other does not. The tag
# prefix is not trusted to tell roles apart: LP-1 and HP-1 are both panels.
_TAG_CONFLICTS = {
    "P-1 + V-3 vs P-1 + V-4 (the shared pump excused the valve)": (
        "Pump P-1 suction valve V-3 conflicts with the strainer at the base of the riser",
        "Pump P-1 suction valve V-4 conflicts with the strainer at the base of the riser",
    ),
    "EF-1 on LP-1 vs EF-1 on HP-1 (two prefixes, one role)": (
        "Exhaust fan EF-1 is fed from panel LP-1 but the schedule lists a different circuit",
        "Exhaust fan EF-1 is fed from panel HP-1 but the schedule lists a different circuit",
    ),
    "sheet ids: P-1 on M-501 vs P-1 on M-502": (
        "Pump P-1 is detailed on sheet M-501 but the tag on this plan does not match",
        "Pump P-1 is detailed on sheet M-502 but the tag on this plan does not match",
    ),
    "grid references: VAV-3 at C-4 vs VAV-3 at C-5": (
        "VAV-3 at grid C-4 has no access clearance to the beam flange above the corridor",
        "VAV-3 at grid C-5 has no access clearance to the beam flange above the corridor",
    ),
    "detail references: P-1 per 5/M-501 vs P-1 per 5/M-502": (
        "Pump P-1 base per 5/M-501 conflicts with the housekeeping pad dimensions "
        "along the east wall of the central plant",
        "Pump P-1 base per 5/M-502 conflicts with the housekeeping pad dimensions "
        "along the east wall of the central plant",
    ),
    "two tag lists sharing one: VAV-3, VAV-4 vs VAV-3, VAV-5": (
        "Boxes VAV-3 and VAV-4 have no access clearance to the beam flange above the corridor",
        "Boxes VAV-3 and VAV-5 have no access clearance to the beam flange above the corridor",
    ),
}


@pytest.mark.parametrize("pair", sorted(_TAG_CONFLICTS))
def test_a_shared_tag_does_not_excuse_a_conflicting_one(pair):
    a, b = _TAG_CONFLICTS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD, "the prose alone would merge these"
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert set(sa["tags"]) & set(sb["tags"]), "the pair shares a tag"
    assert not signatures_compatible(sa, sb)
    assert _surviving(a, b) == (2, 2)


@pytest.mark.parametrize("pair", sorted(_TAG_CONFLICTS))
def test_the_tag_conflict_is_named_as_the_tags_axis(pair):
    assert _conflicts(*_TAG_CONFLICTS[pair]) == ["tags"]


# One finding names a reference the other omits: corroboration with more
# evidence, which must keep merging (blanket equality would split it).
_TAG_CORROBORATIONS = {
    "a valve named on one side: P-1 vs P-1 + V-3": (
        "Pump P-1 suction valve conflicts with the strainer at the base of the riser",
        "Pump P-1 suction valve V-3 conflicts with the strainer at the base of the riser",
    ),
    "a sheet reference on one side: VAV-3 vs VAV-3 per M-501": (
        "VAV-3 has no access clearance to the beam flange above the corridor ceiling",
        "VAV-3 has no access clearance to the beam flange above the corridor ceiling per M-501",
    ),
    "a grid reference on one side: VAV-3 vs VAV-3 at C-4": (
        "VAV-3 has no access clearance to the beam flange above the corridor ceiling",
        "VAV-3 at grid C-4 has no access clearance to the beam flange above the corridor ceiling",
    ),
    "a detail reference on one side: P-1 vs P-1 per 5/M-501": (
        "Pump P-1 base conflicts with the housekeeping pad dimensions "
        "along the east wall of the central plant",
        "Pump P-1 base per 5/M-501 conflicts with the housekeeping pad dimensions "
        "along the east wall of the central plant",
    ),
}


@pytest.mark.parametrize("pair", sorted(_TAG_CORROBORATIONS))
def test_a_reference_one_side_omits_still_merges(pair):
    a, b = _TAG_CORROBORATIONS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert sa["tags"] != sb["tags"] and set(sa["tags"]) < set(sb["tags"])
    assert signatures_compatible(sa, sb)
    assert _surviving(a, b) == (1, 1)
    assert _conflicts(a, b) == []


# Deliberate conservative duplicate retention (plan WP-04 acceptance): each
# side names a different extra reference. The two may well be one issue, but
# nothing in a signature says a valve and a sheet are not competing targets,
# so they are kept apart. The safe error: a reviewer sees two findings rather
# than one that hides a disagreement.
_TAG_RETENTION = {
    "each names a different extra reference: P-1 + V-3 vs P-1 per M-501": (
        "Pump P-1 suction valve V-3 conflicts with the strainer at the base of the riser "
        "along the east wall of the chilled water plant room",
        "Pump P-1 suction valve conflicts with the strainer at the base of the riser "
        "along the east wall of the chilled water plant room per M-501",
    ),
}


@pytest.mark.parametrize("pair", sorted(_TAG_RETENTION))
def test_different_extra_references_are_kept_apart_by_design(pair):
    a, b = _TAG_RETENTION[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    assert _surviving(a, b) == (2, 2)
    assert _conflicts(a, b) == ["tags"]


# --------------------------------------------------------------------------- #
# The shared helper: one copy of the rule, and the axes it names
# --------------------------------------------------------------------------- #

def _sig(tags=(), measurements=(), absence=False, legs=()) -> dict:
    return {
        "tags": sorted(tags), "measurements": sorted(measurements),
        "absence": absence, "leg_targets": sorted(legs),
    }


def test_signature_conflicts_names_every_conflicting_axis_in_a_fixed_order():
    from drawing_analyzer.critique import signature_conflicts

    a = _sig(["P1", "V3"], ["6in"], True, ["M201"])
    b = _sig(["P1", "V4"], ["4in"], False, ["M301"])
    assert signature_conflicts(a, b) == [
        "tags", "measurements", "absence_polarity", "cross_sheet_legs",
    ]
    assert signature_conflicts(b, a) == signature_conflicts(a, b)
    assert signatures_compatible(a, b) is False


def test_a_signal_only_one_side_carries_never_conflicts():
    from drawing_analyzer.critique import signature_conflicts

    assert signature_conflicts({}, {}) == []
    assert signature_conflicts(_sig(["P1"], ["6in"], legs=["M201"]), _sig()) == []
    # A stored record can carry None or omit a key; neither may raise.
    assert signature_conflicts({"tags": None, "measurements": None}, _sig(["P1"])) == []


# Measurements per kind, with hand-built signatures: the kind table's explicit
# semantics, one fixture per kind (plan WP-04 step 3: relate units only with
# explicit semantics and fixtures). None of these converts a value.
_KIND_CASES = [
    # (a, b, conflicts?) -- a note on why follows each group.
    # One unit: one side may add a value, but not each side one of its own.
    (["12ft", "6in"], ["12ft", "8in"], True),
    (["6in", "100psi"], ["4in", "100psi"], True),
    (["2in", "4in", "6in"], ["3in", "5in", "6in"], True),
    (["500gpm", "550gpm"], ["500gpm", "600gpm"], True),
    (["6in"], ["6in", "8in"], False),
    (["500gpm"], ["500gpm", "100psi"], False),
    # A composite is one member, compared whole, never split into its parts.
    (["4..6in"], ["6in"], True),
    (["2,4,6in"], ["3,5,6in"], True),
    (["24x12in", "6in"], ["24x12in"], False),
    # Lengths are one kind: a length on each side that the other lacks
    # conflicts even when the units differ, and 12 in is never 1 ft.
    (["12in"], ["1ft"], True),
    (["6in", "10ft"], ["6in", "12in"], True),
    (["6in", "100psi"], ["100mm", "100psi"], True),
    (["6in"], ["6in", "10ft"], False),
    # A W×H size written without a unit is a length too.
    (["24x12", "1200cfm"], ["24x10in", "1200cfm"], True),
    # Degrees are one kind: a scale is never inferred and never dropped.
    (["90°f", "6in"], ["90°c", "6in"], True),
    (["90°", "6in"], ["90°f", "6in"], True),
    (["45°"], ["45°", "180°f"], False),
    # Gauge and absolute pressure are one kind of quantity, never one unit.
    (["20psig", "6in"], ["20psi", "6in"], True),
    # Voltages are one kind: a system voltage and control voltages.
    (["480volt", "120volt"], ["480volt", "24vac"], True),
    (["120/208volt"], ["120/208volt", "24vac"], False),
    # Liquid flow is one kind (Codex review, P1 on PR #158): 500 gpm is not
    # 12,000 gph, and no rate is converted, so 30,000 gph is not 500 gpm either.
    (["500gpm", "100psi"], ["12000gph", "100psi"], True),
    (["500gpm", "100psi"], ["30000gph", "100psi"], True),
    (["500gpm"], ["500gpm", "30000gph"], False),
    # Real power (hp, kW) is one kind, and apparent power (VA, kVA) another.
    (["5hp", "480volt"], ["7.5kw", "480volt"], True),
    (["500va", "120volt"], ["1kva", "120volt"], True),
    # A transformer's kVA rating and a load's kW are different quantities, not
    # two spellings of one, so a value shared elsewhere decides nothing about them.
    (["75kva", "480volt"], ["60kw", "480volt"], False),
    # Every other unit is its own kind, so a shared value in another kind
    # decides nothing about it. Air flow is one: a coil's water flow and its
    # air flow are different quantities...
    (["500gpm", "6in"], ["500cfm", "6in"], False),
    (["500gpm", "45°f"], ["12000cfm", "45°f"], False),
    # ...but two findings that share no token at all still conflict.
    (["6in"], ["100psi"], True),
    (["6in"], ["150mm"], True),
]


@pytest.mark.parametrize("a,b,conflicts", _KIND_CASES)
def test_quantities_compare_whole_tokens_per_kind(a, b, conflicts):
    sa, sb = _sig(measurements=a), _sig(measurements=b)
    assert signatures_compatible(sa, sb) is (not conflicts)
    assert signatures_compatible(sb, sa) is (not conflicts)

    from drawing_analyzer.critique import signature_conflicts

    expected = ["measurements"] if conflicts else []
    assert signature_conflicts(sa, sb) == expected
    assert signature_conflicts(sb, sa) == expected


def test_a_token_that_is_not_value_then_unit_is_compared_whole():
    # A stored signature is data from disk (the A/B harness reads records
    # back). A token with no digits, or in an unexpected case, must neither
    # raise nor be read as some other quantity.
    from drawing_analyzer.critique import signature_conflicts

    assert signature_conflicts(_sig(measurements=["in"]), _sig(measurements=["in"])) == []
    assert signature_conflicts(
        _sig(measurements=["6IN"]), _sig(measurements=["6in"])) == ["measurements"]


def _corpus_signatures() -> list[dict]:
    texts = [
        text for table in (_TAG_CONFLICTS, _TAG_CORROBORATIONS, _TAG_RETENTION)
        for pair in table.values() for text in pair
    ]
    sigs = [critical_signature(_finding(t)) for t in texts]
    sigs += [_sig(measurements=a) for a, _b, _c in _KIND_CASES]
    sigs += [_sig(measurements=b) for _a, b, _c in _KIND_CASES]
    sigs += [
        _sig(["P1"], absence=True), _sig(legs=["M201"]), _sig(legs=["M201", "M301"]),
        _sig(), _sig(["P1", "V3"], ["6in", "100psi"]),
    ]
    return sigs


def test_signatures_compatible_is_the_negation_of_signature_conflicts():
    from drawing_analyzer.critique import signature_conflicts

    for a, b in itertools.product(_corpus_signatures(), repeat=2):
        assert signatures_compatible(a, b) is (not signature_conflicts(a, b)), (a, b)
        assert signature_conflicts(a, b) == signature_conflicts(b, a), (a, b)


def test_the_rule_blocks_every_pair_the_flat_rule_blocked():
    """WP-04.2 only ever keeps more findings apart; it never merges a pair
    the old rule refused. The old rule, as it read before WP-04.2, is restated
    here as the reference it must dominate -- a test oracle, not a second
    production copy."""
    def flat_rule_conflicts(a, b):
        ta, tb = set(a.get("tags") or ()), set(b.get("tags") or ())
        ma, mb = set(a.get("measurements") or ()), set(b.get("measurements") or ())
        la, lb = set(a.get("leg_targets") or ()), set(b.get("leg_targets") or ())
        return (
            (ta and tb and ta.isdisjoint(tb))
            or (ma and mb and ma.isdisjoint(mb))
            or bool(a.get("absence")) != bool(b.get("absence"))
            or (la and lb and la != lb)
        )

    blocked_before = 0
    for a, b in itertools.product(_corpus_signatures(), repeat=2):
        if flat_rule_conflicts(a, b):
            blocked_before += 1
            assert not signatures_compatible(a, b), (a, b)
    assert blocked_before > 50  # the corpus does exercise the old rule


# --------------------------------------------------------------------------- #
# Growing signatures: complete-link compares each member as it arrived
# --------------------------------------------------------------------------- #
#
# A survivor's signature includes its supporting quotes (``critique._sig_text``),
# so its sets grow as it absorbs members. The complete-link checks compare a
# newcomer with every member instead of with the grown survivor: the critique's
# ``_cluster``, the ledger's ``Ledger.add`` (member snapshots) and Pass B's
# survivor side (``Ledger.member_history``).

_P1 = "Pump P-1 suction valve conflicts with the strainer at the base of the riser"
_P1_V3 = "Pump P-1 suction valve V-3 conflicts with the strainer at the base of the riser"
_P1_V4 = "Pump P-1 suction valve V-4 conflicts with the strainer at the base of the riser"


def test_the_critique_merge_checks_a_read_against_every_member():
    # P-1 and P-1 + V-3 merge; P-1 + V-4 agrees with the first and conflicts
    # with the second, so it starts its own cluster. Before WP-04.2 all three
    # shared P-1 and collapsed into one finding.
    merged = merge_self_consistency(
        [[_finding(_P1)], [_finding(_P1_V3)], [_finding(_P1_V4)]]
    )
    assert len(merged) == 2
    by_text = {m.text: m for m in merged}
    assert _P1_V4 in by_text and by_text[_P1_V4].reproduced is False
    (pair,) = [m for m in merged if m.text != _P1_V4]
    assert pair.text in (_P1, _P1_V3) and pair.reproduced is True


def test_the_ledger_checks_a_newcomer_against_every_member_it_absorbed():
    ledger = Ledger()
    ledger.add([_finding(_P1)], source="digest")
    ledger.add([_finding(_P1_V3)], source="critique_1")
    assert len(ledger) == 1
    ledger.add([_finding(_P1_V4)], source="critique_2")
    assert len(ledger) == 2
    # A newcomer that every member includes still folds in.
    ledger.add([_finding(_P1)], source="auditor")
    assert len(ledger) == 2


def test_a_critique_representative_brings_its_members_quotes_into_the_ledger():
    """The critique merges its reads before the ledger sees them, so the ledger
    compares a digest finding with the merged representative, not with each
    read. The representative's signature holds the other reads' quotes
    (``supporting_quotes``), which is what still blocks a conflict with a read
    whose tag lives only in its quote."""
    short_quote = _finding(_P1_V3, quote="V-3")
    long_quote = _finding(_P1, quote="PUMP P-1 SUCTION")
    merged = merge_self_consistency([[short_quote], [long_quote]])
    assert len(merged) == 1
    rep = merged[0]
    assert rep.source_quote == "PUMP P-1 SUCTION" and rep.supporting_quotes == ["V-3"]
    assert critical_signature(rep)["tags"] == ["P1", "V3"]

    ledger = Ledger()
    ledger.add(merged, source="critique_1")
    ledger.add([_finding(_P1_V4)], source="digest")
    assert len(ledger) == 2


def _pass_b(text_a: str, text_b: str, quote: str) -> tuple[int, int]:
    """Entries after ingest (Pass A) and after Pass B, in the pipeline's order:
    ingest, seal, anchor, reconcile. Both findings anchor to one rectangle."""
    assert _token_overlap(text_a, text_b) < 0.4  # too little prose for Pass A
    ledger = Ledger()
    ledger.add([_finding(text_a, quote=quote)], source="digest")
    ledger.add([_finding(text_b, quote=quote)], source="critique_1")
    after_ingest = len(ledger)
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = Anchor(status="EXACT", rect_pdf=[10.0, 20.0, 200.0, 40.0],
                              method="exact")
    reconcile_post_anchor(ledger)
    return after_ingest, len(ledger)


def test_pass_b_refuses_a_conflicting_tag_behind_one_shared_tag():
    # Same quote, same rectangle: Pass B folds such a pair on geometry. The
    # second valve differs, so it must not.
    assert _pass_b(
        "Pump P-1 suction valve V-3 conflicts with the strainer",
        "Relocate V-4 at the P-1 inlet",
        "PUMP P-1 SUCTION",
    ) == (2, 2)


def test_pass_b_still_folds_a_reference_one_side_omits():
    assert _pass_b(
        "Pump P-1 suction valve V-3 conflicts with the strainer",
        "Relocate the P-1 inlet strainer",
        "PUMP P-1 SUCTION",
    ) == (2, 1)
