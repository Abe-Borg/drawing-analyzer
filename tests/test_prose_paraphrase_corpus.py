"""Remediation WP-09.2 (U11): a labelled paraphrase corpus for the prose match.

``prose_harvest._MATCH_OVERLAP`` (token overlap 0.7 against a same-sheet
entry's text or quote) was never evaluated against labelled data. This table is
the evidence for any later change. The threshold itself is NOT changed here
(plan WP-09 step 5: evaluate before changing it, and never lower it only to save
structuring calls).

Two corpora, each pair labelled by hand:

* ``_PAIRS``: a prose item and an existing ledger entry (its text and its
  placement). "same" when the item restates the entry's claim, "different"
  when it states another. Sources: the N10 cases, what the harvest and
  gauntlet fixtures match, hand-written paraphrases, and near misses around
  0.7.
* ``_MUST_KEEP`` pairwise: the 45 real findings WP-09.1 pinned
  (``tests/test_prose_filler_and_assurances.py``). Every pair is
  "different": each was written as a separate finding.

Every pair goes through the production rule: ``prose_harvest._match_score``
against a threshold, and ``prose_harvest._veto_axes`` for the signature veto
(the text-against-text signing the owner chose). Pinned, at 0.5 to 0.9 and with
and without the veto: how many "same" pairs match (a miss costs a structuring
call) and how many "different" pairs are absorbed (the N10 harm: a distinct
claim that reaches no ledger entry of its own).

Read at 0.7: without the veto 19 of the 25 near misses were absorbed; with it
5 are, and 4 of the 22 restatements cost a structuring call instead of a free
match. The 5 it lets through carry no signal the signature reads (a component
kind, a unit it does not read, an unlisted negation, one side naming an extra
sheet). With the veto, lowering the threshold to 0.5 would absorb 3 more near
misses (8) and 1 of the 990 real-finding pairs (3 without the veto); raising
it to 0.8 would cost 3 more restatements a call and keep 4 more near misses
apart.
"""
from __future__ import annotations

import itertools

import pytest

from drawing_analyzer.models import Finding
from drawing_analyzer.prose_harvest import _MATCH_OVERLAP, _match_entry
from tests.fixtures import gauntlet as G
from tests.test_prose_filler_and_assurances import _MUST_KEEP

SAME, DIFFERENT = "same", "different"

# (pair id, prose item, existing entry text, existing entry placement, label)
_PAIRS = [
    # --- N10: the review's and the request's measured cases -------------------
    ("n10-drain", "Provide 4 inch drain at column line 4.",
     "Provide 6 inch drain at column line 4.", "", DIFFERENT),
    ("n10-psi", "Fire pump relief valve set at 165 psi; pump rated 175 psi at churn.",
     "Fire pump relief valve set at 150 psi; pump rated 175 psi at churn.", "", DIFFERENT),
    ("n10-tag", "Pump P-2 discharge valve is not shown on the riser diagram.",
     "Pump P-1 discharge valve is not shown on the riser diagram.", "", DIFFERENT),
    ("n10-gpm", "Fire pump P-1 rated flow 550 gpm per schedule.",
     "Fire pump P-1 rated flow 500 gpm per schedule.", "", DIFFERENT),
    # --- what the harvest and gauntlet fixtures match -------------------------
    ("five-penetration", "Penetration at grid C-4 must be sleeved by structural.",
     "Penetration at grid C-4 must be sleeved by structural", "", SAME),
    ("five-chase", "FP riser shares a chase with the plumbing vent; verify the access panel.",
     "FP riser shares a chase with the plumbing vent; verify the access panel", "", SAME),
    ("five-note-7", "Note 7 says relief at 175 psi but the schedule row shows 165 psi.",
     "Note 7 says relief at 175 psi but the schedule row shows 165 psi", "", SAME),
    ("chain-twin", "The fire pump equipment pad shown by structural requires coordination.",
     "The fire pump equipment pad shown by structural requires coordination.", "SHEET", SAME),
    ("chain-pair", "The fire pump equipment pad shown by structural requires coordination.",
     "The fire pump equipment pad shown by structural requires confirmation.", "", SAME),
    ("parallel-twin", "Page-zero resulting coordination condition needs review.",
     "Page-zero resulting coordination condition needs review.", "SHEET", SAME),
    ("gauntlet", G.PROSE_MATCHED, "Duct liner omitted at the riser.", "", SAME),
    ("pipeline-vav", "VAV-3 has no clearance.", "VAV-3 has no shown clearance.", "", SAME),
    # --- hand-written paraphrases: the same claim -----------------------------
    ("drain-required", "6 inch drain required at column line 4.",
     "Provide 6 inch drain at column line 4.", "", SAME),
    ("drain-article", "Provide a 6 inch drain at column line 4.",
     "Provide 6 inch drain at column line 4.", "", SAME),
    ("relief-reworded",
     "Relief valve on the fire pump is set at 165 psi; the pump is rated 175 psi at churn.",
     "Fire pump relief valve set at 165 psi; pump rated 175 psi at churn.", "", SAME),
    ("riser-does-not-show", "The riser diagram does not show the discharge valve for pump P-1.",
     "Pump P-1 discharge valve is not shown on the riser diagram.", "", SAME),
    ("vav-no-clearance", "No clearance is shown between VAV-3 and the wall.",
     "VAV-3 has no clearance to the wall.", "", SAME),
    ("heads-no", "No sprinkler heads are shown under the 48 inch duct.",
     "Sprinkler heads are not shown under the 48 inch duct.", "", SAME),
    ("pump-per-schedule", "Per the schedule, fire pump P-1 is rated at 500 gpm.",
     "Fire pump P-1 rated flow 500 gpm per schedule.", "", SAME),
    ("shaft-panels", "The shaft access panels are not scheduled.",
     "Access panels are not scheduled at the shaft.", "", SAME),
    ("hood-wrap", "The kitchen hood exhaust duct has no fire wrap.",
     "Kitchen hood exhaust duct is missing its fire wrap.", "", SAME),
    ("main-duct", "Sprinkler main must be coordinated with the 24x12 duct at grid B-3.",
     "Coordinate the sprinkler main with the 24x12 duct at grid B-3.", "", SAME),
    ("relief-piped", "Relief valve discharge not piped to a drain.",
     "Relief valve discharge is not piped to drain.", "", SAME),
    ("degraded-twin", "Duct riser blocks the corridor door.",
     "Duct riser blocks the corridor door.", "SHEET", SAME),
    ("critique-absence", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve not found at the pump discharge.", "SHEET", SAME),
    ("synthesis-connective",
     "No conflicts were found, yet M-101 lists 500 gpm and P-101 lists 550 gpm.",
     "No conflicts were found; nevertheless M-101 lists 500 gpm and P-101 lists 550 gpm.",
     "", SAME),
    # --- hand-written near misses: another claim ------------------------------
    ("valve-polarity", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve is shown at the pump discharge.", "", DIFFERENT),
    ("valve-polarity-degraded", "Isolation valve is shown at the pump discharge.",
     "Isolation valve is not shown at the pump discharge.", "SHEET", DIFFERENT),
    ("valve-polarity-degraded-2", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve is shown at the pump discharge.", "SHEET", DIFFERENT),
    ("drain-hyphenated", "Provide 4 inch drain at column line 4.",
     "Provide 6-inch drain at column line 4.", "", DIFFERENT),
    ("vav-tag", "VAV-3 has no clearance to the wall.",
     "VAV-4 has no clearance to the wall.", "", DIFFERENT),
    ("duct-size", "Sprinkler heads are not shown under the 48 inch duct.",
     "Sprinkler heads are not shown under the 36 inch duct.", "", DIFFERENT),
    ("psi-psig", "Relief valve set at 165 psi.", "Relief valve set at 165 psig.", "", DIFFERENT),
    ("gpm-beside-psi", "Pump P-1 rated 500 gpm at 100 psi.",
     "Pump P-1 rated 550 gpm at 100 psi.", "", DIFFERENT),
    ("duct-24x10", "Coordinate the sprinkler main with the 24x12 duct at grid B-3.",
     "Coordinate the sprinkler main with the 24x10 duct at grid B-3.", "", DIFFERENT),
    ("facp-tag", "Fire alarm panel FACP-1 is not shown on the electrical plan.",
     "Fire alarm panel FACP-2 is not shown on the electrical plan.", "", DIFFERENT),
    ("cross-main-size", "Hangers are shown without seismic restraint at the 4 inch cross main.",
     "Hangers are shown without seismic restraint at the 6 inch cross main.", "", DIFFERENT),
    ("riser-sheet", "The riser on M-101 conflicts with the duct on P-101.",
     "The riser on M-101 conflicts with the duct on E-201.", "", DIFFERENT),
    ("pump-valve-contrast", "The pump on M-101 does not conflict with P-101, but the valve does.",
     "The pump on M-101 does not conflict with P-101; the valve on E-201 does.", "", DIFFERENT),
    ("liner-polarity", "Duct liner is shown at the riser.",
     "Duct liner omitted at the riser.", "", DIFFERENT),
    # The signature has no signal for these: recorded limits at 0.7.
    ("damper-kind", "Provide access panel for the fire damper above the ceiling.",
     "Provide access panel for the smoke damper above the ceiling.", "", DIFFERENT),
    ("wall-rating", "Provide a 2-hour rated wall at the stair.",
     "Provide a 1-hour rated wall at the stair.", "", DIFFERENT),
    ("drain-vs-vent", "Provide 4 inch drain at column line 4.",
     "Provide 4 inch vent at column line 4.", "", DIFFERENT),
    ("relief-piped-polarity", "Relief valve discharge is piped to drain.",
     "Relief valve discharge is not piped to drain.", "", DIFFERENT),
    ("drain-vs-sink", "Provide a floor drain in the mechanical room.",
     "Provide a floor sink in the mechanical room.", "", DIFFERENT),
    ("fan-room", "Exhaust fan EF-1 serves the toilet room.",
     "Exhaust fan EF-1 serves the janitor closet.", "", DIFFERENT),
    ("door-number", "Door 101 swings into the corridor.",
     "Door 102 swings into the corridor.", "", DIFFERENT),
]

_MUST_KEEP_PAIRS = [
    (f"mk{i}-{j}", a, b, "", DIFFERENT)
    for (i, a), (j, b) in itertools.combinations(enumerate(_MUST_KEEP), 2)
]

# The different claims the veto still lets through at 0.7: the signature reads
# no signal in them. Recorded limits, not goals.
_ABSORBED_WITH_THE_VETO = {
    "pump-valve-contrast",     # one side names an extra sheet (tag inclusion)
    "damper-kind",             # fire vs smoke damper: no tag, value or polarity
    "wall-rating",             # "2-hour" / "1-hour": not a unit the tokenizer reads
    "drain-vs-vent",           # same value, another component
    "relief-piped-polarity",   # "not piped" is not an absence phrase the regex reads
}
# The restatements the veto refuses at 0.7: each costs a structuring call (the
# safe direction). critique._ABSENCE_RE reads one wording as an absence and
# the other not ("does not show", "has no", "No X are shown"); not changed here.
_REFUSED_RESTATEMENTS = {
    "riser-does-not-show", "vav-no-clearance", "heads-no", "hood-wrap",
}

# threshold -> ((same matched, different absorbed) without the veto, (...) with it)
_HAND_SWEEP = {
    0.5: ((22, 25), (18, 8)),
    0.6: ((22, 24), (18, 7)),
    0.7: ((22, 19), (18, 5)),
    0.8: ((18, 8), (15, 1)),
    0.9: ((15, 4), (14, 1)),
}
_MUST_KEEP_SWEEP = {
    0.5: (3, 1),
    0.6: (0, 0),
    0.7: (0, 0),
    0.8: (0, 0),
    0.9: (0, 0),
}


def _entry(text, hint=""):
    return Finding(
        sheet_id="M-101", source_name="a.pdf", page_index=0, category="coordination",
        severity="medium", text=text, source_quote="", anchor_hint=hint,
    )


def _matches(item, existing, hint, threshold, veto):
    from drawing_analyzer.prose_harvest import _match_score, _veto_axes

    entry = _entry(existing, hint)
    if _match_score(item, entry) < threshold:
        return False
    return not (veto and _veto_axes(item, entry))


def _tally(pairs, threshold, veto):
    same = sum(1 for _pid, item, existing, hint, label in pairs
               if label == SAME and _matches(item, existing, hint, threshold, veto))
    different = sum(1 for _pid, item, existing, hint, label in pairs
                    if label == DIFFERENT and _matches(item, existing, hint, threshold, veto))
    return same, different


def test_the_match_threshold_is_unchanged():
    # U11: no change without labelled evidence, and not in this slice.
    assert _MATCH_OVERLAP == 0.7


def test_the_corpus_is_well_formed():
    ids = [pair[0] for pair in _PAIRS]
    assert len(ids) == len(set(ids))
    assert {pair[4] for pair in _PAIRS} == {SAME, DIFFERENT}
    assert (sum(p[4] == SAME for p in _PAIRS), sum(p[4] == DIFFERENT for p in _PAIRS)) == (22, 25)
    assert len(_MUST_KEEP_PAIRS) == 990
    assert G.PROSE_MATCHED in {p[1] for p in _PAIRS}


def test_the_corpus_at_the_current_threshold():
    assert _tally(_PAIRS, _MATCH_OVERLAP, veto=False) == (22, 19)
    assert _tally(_PAIRS, _MATCH_OVERLAP, veto=True) == (18, 5)
    assert _tally(_MUST_KEEP_PAIRS, _MATCH_OVERLAP, veto=False) == (0, 0)
    assert _tally(_MUST_KEEP_PAIRS, _MATCH_OVERLAP, veto=True) == (0, 0)


@pytest.mark.parametrize("threshold", sorted(_HAND_SWEEP))
def test_the_threshold_sweep(threshold):
    without, with_veto = _HAND_SWEEP[threshold]
    assert _tally(_PAIRS, threshold, veto=False) == without
    assert _tally(_PAIRS, threshold, veto=True) == with_veto
    assert _tally(_MUST_KEEP_PAIRS, threshold, veto=False)[1] == _MUST_KEEP_SWEEP[threshold][0]
    assert _tally(_MUST_KEEP_PAIRS, threshold, veto=True)[1] == _MUST_KEEP_SWEEP[threshold][1]


def test_what_the_veto_lets_through_are_the_recorded_limits():
    absorbed = {pid for pid, item, existing, hint, label in _PAIRS
                if label == DIFFERENT and _matches(item, existing, hint, _MATCH_OVERLAP, True)}
    assert absorbed == _ABSORBED_WITH_THE_VETO


def test_what_the_veto_refuses_among_restatements_are_the_recorded_limits():
    refused = {pid for pid, item, existing, hint, label in _PAIRS
               if label == SAME and not _matches(item, existing, hint, _MATCH_OVERLAP, True)}
    assert refused == _REFUSED_RESTATEMENTS


def test_every_restatement_clears_the_threshold_on_text():
    assert all(_matches(item, existing, hint, _MATCH_OVERLAP, False)
               for _pid, item, existing, hint, label in _PAIRS if label == SAME)


@pytest.mark.parametrize("pair", _PAIRS, ids=[p[0] for p in _PAIRS])
def test_match_entry_is_the_score_and_the_veto(pair):
    # The corpus measures the production matcher, not a copy of it.
    _pid, item, existing, hint, _label = pair
    entry = _entry(existing, hint)
    expected = _matches(item, existing, hint, _MATCH_OVERLAP, True)
    assert (_match_entry(item, [entry]) is entry) is expected
