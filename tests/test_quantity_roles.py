"""Quantity roles for repeated same-kind values (remediation WP-04.3).

The critical signature records a finding's quantities as a set. Two findings
that assign the same values to different roles therefore carry the same
tokens, and the same words, and folded into one:

* swapped roles: ``6 in main and 4 in branch`` / ``4 in main and 6 in branch``
  both sign ``{4in, 6in}``;
* one value in two roles: ``6 in supply and 6 in return`` signs ``{6in}``,
  which ``{6in, 8in}`` (``6 in supply and 8 in return``) includes.

WP-04.3 reads a quantity's role (``critique._quantity_roles``) and the rule
(``critique.signature_conflicts``) compares it. The owner's rules:

* **The signal** is a closed list of role words (``critique._ROLE_WORDS``:
  main, branch, riser, drop, header, supply, return, suction, discharge,
  inlet, outlet, upstream, downstream, entering, leaving, primary, secondary,
  min/max, static, residual, cold, hot). A role is read right after the value
  (``6 in main``, ``6 in (main)``, ``6 in supply and return``), as a label
  (``main: 6 in``, ``main = 6 in``) or with a copula (``the main is 6 in``).
  A bare preceding word (``MAIN 6"``) is not read. Status words (shown,
  required, ...) are not roles, nor is any word off the list: a location, a
  tag, a word after ``at``/``per``/``for``/``with``, an ordinal.
* **The comparison** is per role per quantity kind, by inclusion (WP-04.2's
  rule), only where both findings bind the same role, and it reports the
  ``measurements`` axis.
* **Ambiguity** retains: a value list followed by a role list without
  ``respectively`` (``6 in and 4 in main and branch``), or a role word
  between two values with nothing joining them (``MAIN 6" BRANCH 4"``), is
  ambiguous. A finding whose only roles for a kind are ambiguous stays apart
  from one that binds roles in that kind. A missing role never blocks.
  ``respectively`` pairs values and roles in order.

The hard constraint: the commonest duplicate there is, the same "500 gpm
shown, 550 gpm required" from both critique reads, carries two values of one
kind on both sides and must still fold. It binds no role, so it does.

Every pair shares enough prose (``_token_overlap`` at or above the 0.7
duplicate threshold) that the text alone would merge it, so the signature is
what decides, in the critique's two-read merge and in the ledger.

New names are imported inside the tests that need them, so that on a tree
without them only those tests fail and the rest still say what they check.

Hermetic (I-4): pure data, no client, no PDF.
"""
from __future__ import annotations

import itertools
import json

import pytest

from drawing_analyzer.critique import (
    _TEXT_DUP_THRESHOLD,
    _is_duplicate,
    _token_overlap,
    critical_signature,
    merge_self_consistency,
    signatures_compatible,
)
from drawing_analyzer.ledger import Ledger, reconcile_post_anchor
from drawing_analyzer.models import Anchor, Finding

DEG = "\u00b0"


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


def _measurements_alone_conflict(text_a: str, text_b: str) -> bool:
    """What WP-04.2's rule says about the two texts' quantity SETS alone."""
    from drawing_analyzer.critique import signature_conflicts

    sa, sb = critical_signature(_finding(text_a)), critical_signature(_finding(text_b))
    return bool(signature_conflicts(
        {"measurements": sa["measurements"]}, {"measurements": sb["measurements"]},
    ))


def _roles(text: str) -> tuple[list[str], list[str]]:
    from drawing_analyzer.critique import _quantity_roles

    bound, ambiguous = _quantity_roles(text)
    return sorted(bound), sorted(ambiguous)


# --------------------------------------------------------------------------- #
# The reader: which role each quantity takes
# --------------------------------------------------------------------------- #

_READINGS = [
    ("after the value", "Provide 6 in main and 4 in branch at the riser",
     ["branch=4in", "main=6in"], []),
    ("one value in two roles", "Provide 6 in supply and 6 in return at the riser",
     ["return=6in", "supply=6in"], []),
    ("parenthesized", "Sizes are 6 in (main) and 4 in (branch)",
     ["branch=4in", "main=6in"], []),
    ("label with a colon", "Riser sizes: main: 6 in, branch: 4 in",
     ["branch=4in", "main=6in"], []),
    ("label with an equals sign", "Riser sizes main = 6 in and branch = 4 in",
     ["branch=4in", "main=6in"], []),
    ("copula", "At the riser the main is 6 in and the branch is 4 in",
     ["branch=4in", "main=6in"], []),
    ("plural copula", "At the riser the mains are 6 in",
     ["main=6in"], []),
    ("distributive roles", "Provide 6 in supply and return at the riser",
     ["return=6in", "supply=6in"], []),
    ("distributive with a slash", "Provide 6 in supply/return at the riser",
     ["return=6in", "supply=6in"], []),
    ("respectively pairs in order",
     "Provide 6 in and 4 in main and branch respectively at the riser",
     ["branch=4in", "main=6in"], []),
    ("plural folds", "Provide 6 in mains and 4 in branches at the riser",
     ["branch=4in", "main=6in"], []),
    ("min and max fold", "Maintain 4 in minimum and 6 in max clearance",
     ["max=6in", "min=4in"], []),
    ("pressure", "PRV-1 is set at 100 psi inlet and 80 psi outlet",
     ["inlet=100psi", "outlet=80psi"], []),
    ("flow", "Pumps run 500 gpm primary and 400 gpm secondary",
     ["primary=500gpm", "secondary=400gpm"], []),
    ("compact volts", "Transformer T-1 is 480V primary and 208V secondary",
     ["primary=480volt", "secondary=208volt"], []),
    ("a W x H size", "Duct 24x12 supply and 24x10 return at the air handler",
     ["return=24x10", "supply=24x12"], []),
    ("fire flow test", "Hydrant H-1 reads 65 psi static and 45 psi residual",
     ["residual=45psi", "static=65psi"], []),
    ("temperatures", f"Coil water is 44{DEG}F entering and 54{DEG}F leaving",
     [f"entering=44{DEG}f", f"leaving=54{DEG}f"], []),
    ("case does not matter", 'MAIN: 6" BRANCH: 4"',
     ["branch=4in", "main=6in"], []),
    ("a copula role and a different role after take both",
     "At the riser the main is 6 in (branch)", ["branch=6in", "main=6in"], []),
    # Ambiguous (the owner's rule): the text states roles, but not which
    # value takes which.
    ("a value list, then a role list",
     "Provide 6 in and 4 in main and branch at the riser", [], ["4in", "6in"]),
    ("a value list, then one role", "Provide 6 in and 4 in mains at the riser",
     [], ["4in", "6in"]),
    ("a role word between two values",
     'MAIN 6" BRANCH 4" at the riser', [], ["6in"]),
    ("a role word between two values, the next with its own role",
     "Provide 6 in main 4 in branch at the riser", ["branch=4in"], ["6in"]),
    # No role at all.
    ("no role word", "Pump P-1 shows 500 gpm but the schedule requires 550 gpm", [], []),
    ("a quantity with no unit", "Provide 6 main and 4 branch at the riser", [], []),
]


@pytest.mark.parametrize(
    "text, bound, ambiguous", [case[1:] for case in _READINGS],
    ids=[case[0] for case in _READINGS],
)
def test_the_role_each_quantity_takes(text, bound, ambiguous):
    assert _roles(text) == (bound, ambiguous)


# Nouns and wording that are not a role (the negative corpus). Each text reads
# no role at all.
_NOT_ROLES = [
    ("a location", "Provide 6 in drain at grid C and 4 in drain at grid D"),
    ("a role word after at", "Provide 6 in drain at the main and 4 in drain at the branch"),
    ("per", "Provide 6 in per branch and 4 in per main at the riser"),
    ("for", "Provide 6 in for the supply and 4 in for the return at the riser"),
    ("with", "Provide 6 in with a branch and 4 in with a main at the riser"),
    ("to", "Reduce 6 in to the main and 4 in to the branch at the riser"),
    ("an ordinal", "Provide 6 in first and 4 in second at the riser"),
    ("a tag", "Pump P-1 is 500 gpm and pump P-2 is 400 gpm per the schedule"),
    ("a tag after the value", "Provide 500 gpm P-1 and 400 gpm P-2 per the schedule"),
    ("a status word", "Pump P-1 has 500 gpm shown and 550 gpm required"),
    ("an unlisted noun", "Provide 6 in floor drain and 4 in roof drain"),
    ("a role word inside a longer word",
     "Provide 6 in mainline and 4 in returns and 2 in maintenance access"),
    ("a bare preceding role word", "Main 6 in, branch 4 in at the riser"),
    ("a role word before at", "The main at 6 in and the branch at 4 in"),
    ("list wording, respectively without roles", "Provide 6 in and 4 in respectively"),
    # The label is looked for in a bounded window before the value; a longer
    # word cut at the window's edge must not read as a role (``domain:`` is
    # not ``main:``).
    ("a role word inside a longer label word", "domain:" + " " * 27 + "6 in"),
]


@pytest.mark.parametrize("text", [c[1] for c in _NOT_ROLES], ids=[c[0] for c in _NOT_ROLES])
def test_a_noun_that_is_not_a_role_reads_no_role(text):
    assert _roles(text) == ([], [])


def test_the_role_list_is_closed_and_canonical():
    from drawing_analyzer.critique import _ROLE_WORDS

    canonical = set(_ROLE_WORDS.values())
    assert canonical == {
        "main", "branch", "riser", "drop", "header", "supply", "return",
        "suction", "discharge", "inlet", "outlet", "upstream", "downstream",
        "entering", "leaving", "primary", "secondary", "min", "max",
        "static", "residual", "cold", "hot",
    }
    # Status words are not roles (the owner's rule): "shown" sits on whichever
    # value a read happened to describe as shown, so two reads of one
    # 500/550 conflict would split on it.
    for word in ("shown", "required", "scheduled", "specified", "provided",
                 "design", "existing", "new", "proposed"):
        assert word not in _ROLE_WORDS


# --------------------------------------------------------------------------- #
# The merges: a role conflict keeps two findings apart
# --------------------------------------------------------------------------- #

_ROLE_CONFLICTS = {
    "swapped main and branch": (
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
        "Provide 4 in main and 6 in branch at the riser serving the east data hall",
    ),
    "one value in two roles": (
        "Provide 6 in supply and 6 in return at the riser serving the east data hall",
        "Provide 6 in supply and 8 in return at the riser serving the east data hall",
    ),
    "psi: inlet and outlet swapped": (
        "Pressure reducing valve PRV-1 is set at 100 psi inlet and 80 psi outlet per the valve schedule",
        "Pressure reducing valve PRV-1 is set at 80 psi inlet and 100 psi outlet per the valve schedule",
    ),
    "psi: one value in two roles": (
        "Pressure reducing valve PRV-1 is set at 100 psi inlet and 100 psi outlet per the valve schedule",
        "Pressure reducing valve PRV-1 is set at 100 psi inlet and 80 psi outlet per the valve schedule",
    ),
    "psi: static and residual swapped": (
        "Fire flow test at hydrant H-1 reads 65 psi static and 45 psi residual per the water supply data",
        "Fire flow test at hydrant H-1 reads 45 psi static and 65 psi residual per the water supply data",
    ),
    "gpm: primary and secondary swapped": (
        "Chilled water pumps serving the east data hall run 500 gpm primary and 400 gpm "
        "secondary per the pump schedule",
        "Chilled water pumps serving the east data hall run 400 gpm primary and 500 gpm "
        "secondary per the pump schedule",
    ),
    "volts: primary and secondary swapped": (
        "Transformer T-1 serving the east data hall is 480V primary and 208V secondary per the one-line diagram",
        "Transformer T-1 serving the east data hall is 208V primary and 480V secondary per the one-line diagram",
    ),
    "W x H: supply and return swapped": (
        "Duct 24x12 supply and 24x10 return at the air handler serving the east data hall conflict with the beam",
        "Duct 24x10 supply and 24x12 return at the air handler serving the east data hall conflict with the beam",
    ),
    "degrees: entering and leaving swapped": (
        f"Chilled water at the coil of AHU-1 is 44{DEG}F entering and 54{DEG}F leaving per the coil schedule",
        f"Chilled water at the coil of AHU-1 is 54{DEG}F entering and 44{DEG}F leaving per the coil schedule",
    ),
    "suction and discharge swapped": (
        "Pump P-1 is 8 in suction and 6 in discharge per the pump schedule for the east data hall",
        "Pump P-1 is 6 in suction and 8 in discharge per the pump schedule for the east data hall",
    ),
    "min and max swapped": (
        "Maintain 4 in min and 6 in max clearance at the base of pump P-1 per the detail",
        "Maintain 6 in min and 4 in max clearance at the base of pump P-1 per the detail",
    ),
    "cold and hot swapped": (
        "Provide 1 in cold and 3/4 in hot water to the lavatory in the east data hall restroom",
        "Provide 3/4 in cold and 1 in hot water to the lavatory in the east data hall restroom",
    ),
    "a label: main: 6 in": (
        "Riser sizes at the east data hall per the plumbing plan: main: 6 in, branch: 4 in",
        "Riser sizes at the east data hall per the plumbing plan: main: 4 in, branch: 6 in",
    ),
    "a parenthesis: 6 in (main)": (
        "Riser sizes at the east data hall per the plumbing plan are 6 in (main) and 4 in (branch)",
        "Riser sizes at the east data hall per the plumbing plan are 4 in (main) and 6 in (branch)",
    ),
    "a copula: the main is 6 in": (
        "At the riser serving the east data hall the main is 6 in and the branch is 4 in per the plumbing plan",
        "At the riser serving the east data hall the main is 4 in and the branch is 6 in per the plumbing plan",
    ),
    "one side adds a role the other contradicts": (
        "Provide 6 in main at the riser serving the east data hall per the plumbing plan",
        "Provide 4 in main and 6 in branch at the riser serving the east data hall per the plumbing plan",
    ),
    "distributive roles: 6 in supply and return": (
        "Provide 6 in supply and return at the riser serving the east data hall",
        "Provide 6 in supply and 8 in return at the riser serving the east data hall",
    ),
    "respectively against the swap": (
        "Provide 6 in and 4 in main and branch respectively at the riser serving the east data hall",
        "Provide 4 in main and 6 in branch at the riser serving the east data hall",
    ),
}


@pytest.mark.parametrize(
    "pair", sorted(_ROLE_CONFLICTS), ids=sorted(_ROLE_CONFLICTS),
)
def test_a_role_conflict_stays_two_findings(pair):
    from drawing_analyzer.critique import signature_conflicts

    a, b = _ROLE_CONFLICTS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD, "the prose alone would merge these"
    # The quantity sets alone are compatible: the role is what decides.
    assert not _measurements_alone_conflict(a, b)
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert signature_conflicts(sa, sb) == ["measurements"]
    assert _surviving(a, b) == (2, 2)


def test_roles_read_from_the_quote_decide_too():
    text = "Riser sizes at the east data hall are shown on the plumbing plan"
    a = _finding(text, quote='MAIN: 6" BRANCH: 4"')
    b = _finding(text, quote='MAIN: 4" BRANCH: 6"')
    assert not signatures_compatible(critical_signature(a), critical_signature(b))
    assert len(merge_self_consistency([[a], [b]])) == 2


# --------------------------------------------------------------------------- #
# The merges: what still folds
# --------------------------------------------------------------------------- #

_THE_500_550_DUPLICATE = "Pump P-1 shows 500 gpm but the pump schedule requires 550 gpm at the design point"

_ROLE_COMPATIBLE = {
    # The tracker's hard constraint, measured on main: both reads sign
    # ['500gpm', '550gpm'] and _is_duplicate is True.
    "the 500/550 gpm duplicate from both reads": (_THE_500_550_DUPLICATE, _THE_500_550_DUPLICATE),
    "the 500/550 gpm duplicate phrased two ways": (
        _THE_500_550_DUPLICATE,
        "Pump P-1 is shown at 500 gpm but the pump schedule requires 550 gpm at the design point",
    ),
    "the 500/550 gpm duplicate, shown on different values": (
        "Pump P-1 has 500 gpm shown on the plan but 550 gpm on the pump schedule for the design point",
        "Pump P-1 has 550 gpm shown on the pump schedule but 500 gpm on the plan for the design point",
    ),
    "the same roles in another order": (
        "Provide 4 in branch, 6 in main at the riser serving the east data hall",
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
    ),
    "one side names roles, the other does not": (
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
        "Provide 6 in and 4 in piping at the riser serving the east data hall",
    ),
    "respectively against the same roles": (
        "Provide 6 in and 4 in main and branch respectively at the riser serving the east data hall",
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
    ),
    "a role one side adds detail to": (
        "The 6 in main serving the east data hall is undersized for the design demand",
        "The 6 in main serving the east data hall is undersized for the design demand; provide 8 in main",
    ),
    "a role word between two values, the text binding the rest": (
        "Provide 6 in main 4 in branch at the riser serving the east data hall",
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
    ),
    "the text names roles and the quote is a label sequence": (
        'Provide 6 in main and 4 in branch at the riser serving the east data hall MAIN 6" BRANCH 4"',
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
    ),
    "different roles, no role shared": (
        "Provide 6 in main at the riser serving the east data hall",
        "Provide 6 in supply at the riser serving the east data hall",
    ),
}


@pytest.mark.parametrize(
    "pair", sorted(_ROLE_COMPATIBLE), ids=sorted(_ROLE_COMPATIBLE),
)
def test_findings_whose_roles_agree_still_merge(pair):
    a, b = _ROLE_COMPATIBLE[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    assert signatures_compatible(critical_signature(_finding(a)), critical_signature(_finding(b)))
    assert _surviving(a, b) == (1, 1)


def test_the_500_550_duplicate_is_one_reproduced_finding():
    """The commonest duplicate there is: two values of one kind on both sides,
    from both critique reads. Keeping apart every such pair would split it."""
    sig = critical_signature(_finding(_THE_500_550_DUPLICATE))
    assert sig["measurements"] == ["500gpm", "550gpm"]
    assert sig["roles"] == [] and sig["ambiguous_roles"] == []
    assert _is_duplicate(_finding(_THE_500_550_DUPLICATE), _finding(_THE_500_550_DUPLICATE))
    (merged,) = merge_self_consistency(
        [[_finding(_THE_500_550_DUPLICATE)], [_finding(_THE_500_550_DUPLICATE)]]
    )
    assert merged.reproduced is True and merged.confidence == "REPRODUCED"


# The negative corpus as pairs: each swaps its values around words that are
# not roles, and must still merge, since no role was read to conflict.
_NOT_ROLE_PAIRS = {
    "a location": (
        "Provide 6 in drain at grid C and 4 in drain at grid D in the east data hall",
        "Provide 4 in drain at grid C and 6 in drain at grid D in the east data hall",
    ),
    "per": (
        "Provide 6 in per branch and 4 in per main at the riser serving the east data hall",
        "Provide 4 in per branch and 6 in per main at the riser serving the east data hall",
    ),
    "for": (
        "Provide 6 in for the supply and 4 in for the return at the riser serving the east data hall",
        "Provide 4 in for the supply and 6 in for the return at the riser serving the east data hall",
    ),
    "with": (
        "Provide 6 in with a branch and 4 in with a main at the riser serving the east data hall",
        "Provide 4 in with a branch and 6 in with a main at the riser serving the east data hall",
    ),
    "an ordinal": (
        "Provide 6 in first and 4 in second at the riser serving the east data hall",
        "Provide 4 in first and 6 in second at the riser serving the east data hall",
    ),
    "list wording": (
        "Provide 6 in and 4 in mains at the riser serving the east data hall",
        "Provide 4 in and 6 in mains at the riser serving the east data hall",
    ),
}


@pytest.mark.parametrize("pair", sorted(_NOT_ROLE_PAIRS), ids=sorted(_NOT_ROLE_PAIRS))
def test_a_noun_that_is_not_a_role_creates_no_role_conflict(pair):
    a, b = _NOT_ROLE_PAIRS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    assert _roles(a)[0] == [] and _roles(b)[0] == []
    assert _surviving(a, b) == (1, 1)


# --------------------------------------------------------------------------- #
# Conservative retention (the owner's ambiguity rule; plan WP-04 step 4:
# "retain separate claims when role ambiguity prevents safe compatibility")
# --------------------------------------------------------------------------- #

_ROLE_RETENTION = {
    "a value list then a role list, against explicit roles": (
        "Provide 6 in and 4 in main and branch at the riser serving the east data hall",
        "Provide 6 in main and 4 in branch at the riser serving the east data hall",
    ),
    "a label sequence with no other roles, against explicit roles": (
        'MAIN 6" BRANCH 4" at the riser serving the east data hall per the plumbing plan',
        "6 in main and 4 in branch at the riser serving the east data hall per the plumbing plan",
    ),
    # The rule's cost: a role word between two values reads as ambiguous even
    # where the second value is a distance, so this likely restatement stays
    # two findings when the text binds no other length role.
    "a role word before a distance, against the same role bound": (
        "The 6 in main 10 ft from the east wall of the data hall conflicts with the duct",
        "The 6 in main located 10 ft from the east wall of the data hall conflicts with the duct",
    ),
}


@pytest.mark.parametrize("pair", sorted(_ROLE_RETENTION), ids=sorted(_ROLE_RETENTION))
def test_an_ambiguous_role_is_kept_apart_by_design(pair):
    from drawing_analyzer.critique import signature_conflicts

    a, b = _ROLE_RETENTION[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    assert not _measurements_alone_conflict(a, b)
    sa, sb = critical_signature(_finding(a)), critical_signature(_finding(b))
    assert signature_conflicts(sa, sb) == ["measurements"]
    assert _surviving(a, b) == (2, 2)


# --------------------------------------------------------------------------- #
# Recorded limits: role conflicts that still merge
# --------------------------------------------------------------------------- #

_ROLE_LIMITS = {
    # Status words are not roles (the owner's rule), so a swapped shown and
    # required value is the same set of tokens with no role.
    "shown and required swapped": (
        "Pump P-1 has 500 gpm shown and 550 gpm required at the design point on the pump schedule",
        "Pump P-1 has 550 gpm shown and 500 gpm required at the design point on the pump schedule",
    ),
    "floor drain and roof drain swapped (not a listed role)": (
        "Provide 6 in floor drain and 4 in roof drain at the east data hall",
        "Provide 4 in floor drain and 6 in roof drain at the east data hall",
    ),
    "values swapped between two tags (a tag is not a role)": (
        "Pump P-1 is 500 gpm and pump P-2 is 400 gpm per the schedule for the east data hall",
        "Pump P-1 is 400 gpm and pump P-2 is 500 gpm per the schedule for the east data hall",
    ),
    "a role after at": (
        "Set 100 psi at the inlet and 80 psi at the outlet of PRV-1 per the valve schedule",
        "Set 80 psi at the inlet and 100 psi at the outlet of PRV-1 per the valve schedule",
    ),
    "both sides ambiguous": (
        "Provide 6 in and 4 in main and branch at the riser serving the east data hall",
        "Provide 4 in and 6 in main and branch at the riser serving the east data hall",
    ),
    "a bare label sequence swapped (not read)": (
        'MAIN 6" BRANCH 4" at the riser serving the east data hall per the plumbing plan',
        'MAIN 4" BRANCH 6" at the riser serving the east data hall per the plumbing plan',
    ),
    "ordinals on one role": (
        "At the riser the first main is 6 in and the second main is 4 in per the plumbing plan",
        "At the riser the first main is 4 in and the second main is 6 in per the plumbing plan",
    ),
}


@pytest.mark.parametrize("pair", sorted(_ROLE_LIMITS), ids=sorted(_ROLE_LIMITS))
def test_recorded_role_limits_still_merge(pair):
    a, b = _ROLE_LIMITS[pair]
    assert _token_overlap(a, b) >= _TEXT_DUP_THRESHOLD
    assert signatures_compatible(critical_signature(_finding(a)), critical_signature(_finding(b)))
    assert _surviving(a, b) == (1, 1)


# --------------------------------------------------------------------------- #
# Complete-link: roles that disagree only through different members
# --------------------------------------------------------------------------- #
#
# A names roles, C names the opposite roles, and B, the bridge, names none: A
# and B fold, B and C fold, A and C conflict. A survivor's signature grows as
# it absorbs supporting quotes, and when the bundle passes to the bridge the
# live survivor may carry no role at all, so every complete-link check must
# compare members as they arrived: the critique's _cluster, Ledger.add's
# member snapshots, and Pass B's member histories on both sides.

_A = "Provide 6 in main and 4 in branch at the riser serving the east data hall"
_B = "Provide 6 in and 4 in piping at the riser serving the east data hall"
_C = "Provide 4 in main and 6 in branch at the riser serving the east data hall"
_CHAIN = {"A": _A, "B": _B, "C": _C}


def test_the_chain_is_a_bridge():
    assert _is_duplicate(_finding(_A), _finding(_B))
    assert _is_duplicate(_finding(_B), _finding(_C))
    assert not _is_duplicate(_finding(_A), _finding(_C))


@pytest.mark.parametrize(
    "order", list(itertools.permutations("ABC")),
    ids=["".join(p) for p in itertools.permutations("ABC")],
)
def test_the_critique_merge_never_folds_the_chain(order):
    merged = merge_self_consistency([[_finding(_CHAIN[k])] for k in order])
    assert len(merged) == 2


@pytest.mark.parametrize(
    "order", list(itertools.permutations("ABC")),
    ids=["".join(p) for p in itertools.permutations("ABC")],
)
def test_the_ledger_never_folds_the_chain(order):
    ledger = Ledger()
    for key in order:
        ledger.add([_finding(_CHAIN[key])], source=f"read_{key}")
    assert len(ledger) == 2
    for entry in ledger.entries:
        texts = {m.text for m in ledger.member_history(entry)}
        assert not {_A, _C} <= texts


@pytest.mark.parametrize(
    "order", list(itertools.permutations("ABC")),
    ids=["".join(p) for p in itertools.permutations("ABC")],
)
def test_pass_b_never_folds_the_chain(order):
    ledger = Ledger()
    for key in order:
        ledger.add([_finding(_CHAIN[key], quote="RISER")], source=f"read_{key}")
    assert len(ledger) == 2
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = Anchor(status="EXACT", rect_pdf=[10.0, 20.0, 200.0, 40.0], method="exact")
    reconcile_post_anchor(ledger)
    assert len(ledger) == 2


def test_a_grown_survivor_without_roles_does_not_admit_the_conflict():
    """The growth statement, pinned: a survivor whose bundle passed to the
    bridge carries no role in its live signature, so a check against the live
    object would admit C. The member snapshots refuse it."""
    ledger = Ledger()
    ledger.add([_finding(_A)], source="digest")
    ledger.add([_finding(_B)], source="critique_1")
    (survivor,) = ledger.entries
    # The bridge won the bundle: the live survivor names no role, so the live
    # object alone would admit C.
    assert survivor.text == _B and critical_signature(survivor)["roles"] == []
    assert _is_duplicate(_finding(_C), survivor)
    ledger.add([_finding(_C)], source="critique_2")
    assert len(ledger) == 2
    assert survivor in ledger.entries


# --------------------------------------------------------------------------- #
# The signature record and the one rule
# --------------------------------------------------------------------------- #

def test_the_signature_carries_roles_as_sorted_json_safe_lists():
    sig = critical_signature(_finding(_A, quote='MAIN 6" BRANCH 4"'))
    assert sig["roles"] == ["branch=4in", "main=6in"]
    assert sig["ambiguous_roles"] == ["6in"]
    assert json.loads(json.dumps(sig)) == sig
    # Remediation WP-04.4 added ``feet_inches`` (the owner's approved re-pin).
    assert set(sig) == {"tags", "measurements", "roles", "ambiguous_roles", "feet_inches",
                        "absence", "leg_targets"}


def test_roles_are_read_part_by_part():
    """A role word that opens the quote never binds to a value that ends the
    text: ``_sig_text`` joins them with a space, and read joined, ``6 in`` +
    ``MAIN ...`` would read as ``6 in main``."""
    sig = critical_signature(_finding("Provide the drain sized 6 in", quote="MAIN LEVEL PLAN"))
    assert sig["measurements"] == ["6in"]
    assert sig["roles"] == [] and sig["ambiguous_roles"] == []
    assert _roles("Provide the drain sized 6 in MAIN LEVEL PLAN") == (["main=6in"], [])


def test_a_role_on_one_side_only_never_conflicts():
    from drawing_analyzer.critique import signature_conflicts

    roles = {"measurements": ["4in", "6in"], "roles": ["branch=4in", "main=6in"]}
    bare = {"measurements": ["4in", "6in"]}
    assert signature_conflicts(roles, bare) == []
    assert signature_conflicts(bare, roles) == []
    # A stored record can carry None; it may not raise.
    assert signature_conflicts({"roles": None, "ambiguous_roles": None}, roles) == []


def test_roles_compare_per_kind_and_never_convert():
    from drawing_analyzer.critique import signature_conflicts

    def sig(roles):
        return {"measurements": sorted({r.split("=", 1)[1] for r in roles}), "roles": roles}

    # One role, two kinds: a pressure beside a size is not a size conflict.
    assert signature_conflicts(sig(["main=6in"]), sig(["main=100psi", "main=6in"])) == []
    # 12 in is never 1 ft: the role's values differ.
    assert signature_conflicts(sig(["main=12in"]), sig(["main=1ft"])) == ["measurements"]
    # Units of one kind compare together.
    assert signature_conflicts(sig(["main=6in"]), sig(["main=150mm", "main=6in"])) == []
    assert signature_conflicts(sig(["main=6in", "branch=4in"]),
                               sig(["main=150mm", "branch=4in"])) == ["measurements"]


def test_an_ambiguous_kind_retains_only_against_bound_roles_in_that_kind():
    from drawing_analyzer.critique import signature_conflicts

    ambiguous = {"measurements": ["4in", "6in"], "ambiguous_roles": ["4in", "6in"]}
    bound = {"measurements": ["4in", "6in"], "roles": ["branch=4in", "main=6in"]}
    unbound = {"measurements": ["4in", "6in"]}
    other_kind = {"measurements": ["4in", "6in", "500gpm"], "roles": ["primary=500gpm"]}
    assert signature_conflicts(ambiguous, bound) == ["measurements"]
    assert signature_conflicts(bound, ambiguous) == ["measurements"]
    assert signature_conflicts(ambiguous, unbound) == []
    assert signature_conflicts(ambiguous, ambiguous) == []
    assert signature_conflicts(ambiguous, other_kind) == []
    # A side that also binds a role in the kind is not "only ambiguous".
    both = dict(bound, ambiguous_roles=["8in"])
    assert signature_conflicts(both, bound) == []


def _corpus() -> list[dict]:
    texts = [
        text
        for table in (_ROLE_CONFLICTS, _ROLE_COMPATIBLE, _NOT_ROLE_PAIRS, _ROLE_RETENTION, _ROLE_LIMITS)
        for pair in table.values() for text in pair
    ]
    return [critical_signature(_finding(t)) for t in texts]


def test_the_rule_is_symmetric_and_compatible_is_its_negation():
    from drawing_analyzer.critique import signature_conflicts

    for a, b in itertools.product(_corpus(), repeat=2):
        assert signature_conflicts(a, b) == signature_conflicts(b, a), (a, b)
        assert signatures_compatible(a, b) is (not signature_conflicts(a, b)), (a, b)


def test_roles_only_ever_block_more():
    """WP-04.3 never merges a pair WP-04.2's rule kept apart: the same rule
    over the same signatures with the role keys removed is the oracle."""
    from drawing_analyzer.critique import signature_conflicts

    def without_roles(sig):
        return {k: v for k, v in sig.items() if k not in ("roles", "ambiguous_roles")}

    blocked = 0
    for a, b in itertools.product(_corpus(), repeat=2):
        if signature_conflicts(without_roles(a), without_roles(b)):
            blocked += 1
            assert signature_conflicts(a, b), (a, b)
    assert blocked > 0


# --------------------------------------------------------------------------- #
# The quantity reader itself is unchanged (the anchor reuses it)
# --------------------------------------------------------------------------- #

def test_the_quantity_tokens_are_the_readings_tokens():
    """``anchor._same_quantities`` (WP-05.3) reuses ``_quantity_tokens`` as it
    is, so the roles sit beside the reader and never change its tokens."""
    from drawing_analyzer.critique import _quantity_readings, _quantity_tokens

    texts = [
        text
        for table in (_ROLE_CONFLICTS, _ROLE_COMPATIBLE, _NOT_ROLE_PAIRS, _ROLE_RETENTION, _ROLE_LIMITS)
        for pair in table.values() for text in pair
    ] + [c[1] for c in _READINGS] + [c[1] for c in _NOT_ROLES] + [
        "Provide 6-inch drain at 12,500 cfm", '24"x12" duct', "4-6 in", "2,4,6 in",
        "120/208V", "1,2,500 cfm", "12'-6\"", "4x25 gpm", '6"x12\'', "90 deg F",
    ]
    for text in texts:
        readings = _quantity_readings(text)
        assert _quantity_tokens(text) == frozenset(token for token, _s, _e in readings)
        for token, start, end in readings:
            assert 0 <= start < end <= len(text)


# --------------------------------------------------------------------------- #
# The prose harvest's veto reads the same rule (WP-09.2)
# --------------------------------------------------------------------------- #

def _prose_entry(text: str) -> Finding:
    return Finding(
        sheet_id="P-101", source_name="a.pdf", page_index=0,
        category="coordination", severity="medium", text=text,
    )


def test_the_prose_veto_refuses_a_swapped_role_candidate():
    from drawing_analyzer.prose_harvest import _match_entry, _veto_axes

    item = "Provide 4 in main and 6 in branch at the riser serving the east data hall."
    swapped = _prose_entry("Provide 6 in main and 4 in branch at the riser serving the east data hall.")
    assert _veto_axes(item, swapped) == ["measurements"]
    assert _match_entry(item, [swapped]) is None
    same = _prose_entry("Provide 4 in main and 6 in branch at the riser serving the east data hall.")
    assert _match_entry(item, [swapped, same]) is same
