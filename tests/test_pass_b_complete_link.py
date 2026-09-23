"""Remediation WP-03.1: Pass B's complete-link is symmetric (review B1, count part).

Pure and hermetic: synthetic findings, no PyMuPDF, no network.

Pass B (``ledger.reconcile_post_anchor``) folds an entry ``e`` into a survivor
``s`` only when EVERY member of ``e``'s history duplicates EVERY member of
``s``'s history (``critique._is_duplicate``, the relation Pass A uses, each
member compared as it arrived). It used to compare only the live ``e`` with
``s``'s members, so nothing ``e`` had absorbed in Pass A was ever checked. When
``e``'s bundle had passed to a generic member, the live ``e`` no longer said
"500 gpm", so it folded into a "550 gpm" survivor that Pass A had refused; and
whether it did depended on which of the two sorted first.

Pinned here:

* the B1 case in all six ingest orders, with severity and quote-length
  variants that change which entry sorts first and which member wins a bundle:
  two entries every time, no history holding two members that are not
  duplicates (the WP-03 acceptance "no incompatible members share a merged
  finding"), and a second pass that folds nothing (idempotence);
* the geometry decision, and what replaced it. WP-03.1 recorded that a Pass A
  snapshot carries no rectangle, so ``_is_duplicate``'s geometry branch folded
  only two entries that absorbed nothing, and it did not lend the rect to
  snapshots. WP-03.7 (N28) removed the branch: a rectangle is resolved from
  the quote, so it is no evidence that two findings make one claim, and a
  same-spot pair now stays two entries in every configuration (see
  ``test_a_same_spot_pair_never_folds_on_position``);
* the candidate index only speeds up discovery: the partition equals the one
  found by comparing every entry with every earlier survivor;
* recorded limits that later slices flip deliberately: which cluster the
  generic bridge joins and a longer chain's entry count (WP-03.6), and whether
  "500" reaches the exports (WP-03.5). The N28 limit is flipped:
  ``test_two_issues_that_quote_one_tag_stay_apart_after_anchoring``.
"""
from __future__ import annotations

import itertools
import random

import pytest

from drawing_analyzer.critique import _is_duplicate
from drawing_analyzer.ledger import Ledger, _grounding_quality, reconcile_post_anchor
from drawing_analyzer.models import Anchor, Finding, source_page_key

_ORDERS = ["".join(p) for p in itertools.permutations("ABC")]


def _f(text: str, quote: str, *, sev: str = "medium", cat: str = "coordination",
       label: str = "") -> Finding:
    # Unanchored, as model findings arrive: tests anchor live entries after
    # the seal, the way the pipeline's anchor stage does.
    finding = Finding(
        sheet_id="M-101", source_name="M-101.pdf", source_id="SRC-0001",
        page_index=0, category=cat, severity=sev, text=text, source_quote=quote,
    )
    if label:
        # A member label for partition checks. ``_merge_into`` unions this
        # field, and nothing the merge rule or the quality rank reads uses it.
        finding.prose_item_ids = [label]
    return finding


def _history_is_a_clique(ledger: Ledger) -> bool:
    """The WP-03 acceptance: every pair in every entry's history duplicates."""
    return all(
        _is_duplicate(a, b)
        for entry in ledger.entries
        for a, b in itertools.combinations(ledger.member_history(entry), 2)
    )


def _state(ledger: Ledger) -> list[tuple]:
    return [
        (e.id, e.text, e.source_quote, tuple(e.sources), tuple(e.supporting_quotes),
         len(ledger.member_history(e)))
        for e in ledger.entries
    ]


def _exported(entry: Finding) -> str:
    """The text fields an export carries (``to_dict`` / the CSV row)."""
    return " ".join([entry.text, entry.source_quote, entry.recommended_action,
                     *entry.supporting_quotes])


# --------------------------------------------------------------------------- #
# B1: 500 gpm / generic bridge / 550 gpm
# --------------------------------------------------------------------------- #

_TEXT = {
    "A": "riser pump flow is 500 gpm per riser schedule",
    "B": "riser pump flow per riser schedule",
    "C": "riser pump flow is 550 gpm per riser schedule",
}
_SOURCE = {"A": "digest_json", "B": "critique_1", "C": "cross_qc"}

# (quote, severity) per finding. Each variant changes which entry sorts first in
# Pass B (quote length, then severity) or which member wins a Pass A bundle.
_VARIANTS = {
    # The reproduction on 321cb8e: the generic bridge wins A's bundle and
    # loses C's, and "550" carries the longest quote, so an entry that absorbed
    # A sorts second. Three of six orders folded on the old rule.
    "b1": {"A": ("RISER", "medium"), "B": ("RISER PUMP FLOW", "medium"),
           "C": ("RISER PUMP FLOW SCHEDULE", "medium")},
    # The review's construction as written (B quotes nothing, C quotes RISER).
    # A keeps its own bundle, so the entry that absorbed the bridge still says
    # "500" and the old rule held: B1 needs the absorbing entry to lose its
    # measurement from the live bundle AND sort second.
    "review-as-written": {"A": ("RISER", "medium"), "B": ("", "medium"),
                          "C": ("RISER", "medium")},
    # The bridge carries the longest quote, so the entry holding it always
    # sorts first and the incoming entry is a singleton (the old rule held).
    "bridge-quote-longest": {
        "A": ("RISER", "medium"),
        "B": ("RISER PUMP FLOW PER RISER SCHEDULE AND COORDINATION DETAILS", "medium"),
        "C": ("RISER PUMP", "medium")},
    # The mirror image: the bridge wins C's bundle and "550" leaves the text,
    # while "500" carries the longest quote and sorts first.
    "mirror": {"A": ("RISER PUMP FLOW SCHEDULE", "medium"), "B": ("RISER PUMP FLOW", "medium"),
               "C": ("RISER", "medium")},
    # Equal quote lengths: severity decides both the bundles and the sort.
    "500-most-severe": {"A": ("RISER PUMP FLOW", "high"), "B": ("PUMP FLOW RISER", "medium"),
                        "C": ("FLOW RISER PUMP", "low")},
    "550-most-severe": {"A": ("RISER PUMP FLOW", "low"), "B": ("PUMP FLOW RISER", "medium"),
                        "C": ("FLOW RISER PUMP", "high")},
    "bridge-most-severe": {"A": ("RISER PUMP FLOW", "medium"), "B": ("PUMP FLOW RISER", "high"),
                           "C": ("FLOW RISER PUMP", "medium")},
}


def _b1(variant: str, order: str) -> tuple[Ledger, int]:
    """Ingest the three findings in ``order``; return the SEALED ledger and the
    entry count Pass A left. Pass B has not run."""
    ledger = Ledger()
    for key in order:
        quote, sev = _VARIANTS[variant][key]
        ledger.add([_f(_TEXT[key], quote, sev=sev, label=key)], _SOURCE[key])
    after_pass_a = len(ledger)
    ledger.seal()
    return ledger, after_pass_a


def _cluster_of(ledger: Ledger, label: str) -> frozenset[str]:
    for entry in ledger.entries:
        labels = {l for m in ledger.member_history(entry) for l in m.prose_item_ids}
        if label in labels:
            return frozenset(labels)
    raise AssertionError(f"{label} is in no member history")


def _merged_entry_sorts_second(variant: str, order: str) -> bool:
    """Whether the entry that absorbed the bridge sorts second in Pass B, i.e.
    is the incoming side the old rule never looked inside."""
    ledger, _ = _b1(variant, order)
    ranked = sorted(ledger.entries, key=_grounding_quality, reverse=True)
    return len(ledger.member_history(ranked[1])) > 1


@pytest.mark.parametrize("order", _ORDERS)
@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_b1_keeps_the_conflicting_measurements_apart_in_every_order(variant, order):
    ledger, after_pass_a = _b1(variant, order)
    assert after_pass_a == 2                       # Pass A refused the 500/550 fold
    reconcile_post_anchor(ledger)
    assert len(ledger) == 2, [e.text for e in ledger.entries]
    # No merged finding holds members that are not duplicates of each other.
    assert _history_is_a_clique(ledger)
    assert _cluster_of(ledger, "A") != _cluster_of(ledger, "C")
    # Neither measurement is destroyed: each still lives in a member history.
    runtime = [" ".join(m.text for m in ledger.member_history(e)) for e in ledger.entries]
    assert any("500 gpm" in t for t in runtime) and any("550 gpm" in t for t in runtime)


@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_b1_entry_count_does_not_depend_on_ingest_order(variant):
    counts = {}
    for order in _ORDERS:
        ledger, _ = _b1(variant, order)
        reconcile_post_anchor(ledger)
        counts[order] = len(ledger)
    assert set(counts.values()) == {2}, counts


@pytest.mark.parametrize("order", _ORDERS)
@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_a_second_pass_b_folds_nothing(variant, order):
    ledger, _ = _b1(variant, order)
    reconcile_post_anchor(ledger)
    before = _state(ledger)
    assert reconcile_post_anchor(ledger) == 0
    assert _state(ledger) == before


def test_the_variants_cover_both_roles_and_both_bundle_winners():
    """The matrix is only as good as its spread: some cases must put the
    absorbing entry on the incoming side (the side the old rule never looked
    inside), some must not, and the generic bridge must both win and lose a
    measured member's bundle."""
    roles = {_merged_entry_sorts_second(v, o) for v in _VARIANTS for o in _ORDERS}
    assert roles == {True, False}
    bridge_texts = set()
    for variant in _VARIANTS:
        for order in _ORDERS:
            ledger, _ = _b1(variant, order)
            bridge_texts.update(
                e.text for e in ledger.entries if len(ledger.member_history(e)) > 1
            )
    assert _TEXT["B"] in bridge_texts                 # the bridge won a bundle
    assert bridge_texts - {_TEXT["B"]}                # and lost one


# --------------------------------------------------------------------------- #
# Recorded limits (WP-03.5, WP-03.6): flip these deliberately
# --------------------------------------------------------------------------- #

# Which cluster the generic bridge joins still depends on arrival order: Pass A
# attaches it to whichever measurement arrived first. Final clustering over the
# retained observations in a canonical order is WP-03.6 (plan WP-03, "Required
# clustering clarification").
_BRIDGE_JOINS = {"ABC": "A", "ACB": "A", "BAC": "A", "BCA": "C", "CAB": "C", "CBA": "C"}

# Whether "500" reaches the exports. It is lost in the three orders where the
# generic bridge wins A's bundle in Pass A (its quote is longer): A's text is
# overwritten, only A's quote "RISER" rides into ``supporting_quotes``, and
# "500 gpm" lives on only in the runtime member history. Serializing
# observations and a specificity-aware representative is WP-03.5 (B9).
_500_EXPORTED = {"ABC": False, "ACB": False, "BAC": False, "BCA": True, "CAB": True, "CBA": True}


@pytest.mark.parametrize("order", _ORDERS)
def test_recorded_limit_the_bridge_joins_the_measurement_that_arrived_first(order):
    ledger, _ = _b1("b1", order)
    reconcile_post_anchor(ledger)
    assert _cluster_of(ledger, "B") == frozenset({"B", _BRIDGE_JOINS[order]})


@pytest.mark.parametrize("order", _ORDERS)
def test_recorded_limit_500_reaches_the_exports_only_where_it_kept_its_bundle(order):
    ledger, _ = _b1("b1", order)
    reconcile_post_anchor(ledger)
    exported = " ".join(_exported(e) for e in ledger.entries)
    assert ("500 gpm" in exported) is _500_EXPORTED[order]
    assert "550 gpm" in exported                      # C always keeps its own bundle


# A longer nontransitive chain: A-B, B-C and C-D are duplicates and every other
# pair conflicts (500/550, P-1/P-2). Pass A's greedy clustering then ends with
# two or three entries depending on arrival order, and Pass B, which folds only
# what every member agrees on, cannot repair that. Only the count for the
# three-finding case is order-independent now (WP-03.6).
_PATH = {
    "A": "riser pump flow is 500 gpm per riser schedule at P-1",
    "B": "riser pump flow per riser schedule at P-1",
    "C": "riser pump flow is 550 gpm per riser schedule",
    "D": "riser pump flow is 550 gpm per riser schedule at P-2",
}


def test_recorded_limit_a_four_finding_chain_still_counts_by_arrival_order():
    findings = {k: _f(t, "RISER PUMP FLOW", label=k) for k, t in _PATH.items()}
    dup = {frozenset(p) for p in ("AB", "BC", "CD")}
    for a, b in itertools.combinations("ABCD", 2):
        assert _is_duplicate(findings[a], findings[b]) is (frozenset((a, b)) in dup), (a, b)

    counts = set()
    for order in itertools.permutations("ABCD"):
        ledger = Ledger()
        for key in order:
            ledger.add([_f(_PATH[key], "RISER PUMP FLOW", label=key)], "digest_json")
        ledger.seal()
        reconcile_post_anchor(ledger)
        assert _history_is_a_clique(ledger)
        assert reconcile_post_anchor(ledger) == 0
        counts.add(len(ledger))
    assert counts == {2, 3}


# --------------------------------------------------------------------------- #
# The geometry decision: position is not evidence of sameness (WP-03.7, N28)
# --------------------------------------------------------------------------- #

_X = ("cleanout required at the base of the soil stack per code",
      "cleanout required at base of the soil stack per the code")
_Y = ("provide a cleanout fitting shown on the plumbing detail",
      "provide the cleanout fitting shown on plumbing detail")
_RECT = [10.0, 20.0, 60.0, 42.0]


@pytest.mark.parametrize("first", ["X", "Y"])
@pytest.mark.parametrize("x_absorbed", [False, True])
@pytest.mark.parametrize("y_absorbed", [False, True])
def test_a_same_spot_pair_never_folds_on_position(first, x_absorbed, y_absorbed):
    """X and Y quote one string and anchor to one rectangle, but their texts
    share too little for Pass A (the shape the geometry branch folded). Each
    side has either absorbed a text duplicate in Pass A or not; ``first``
    decides, by severity, which side sorts first in Pass B.

    Re-baselined by WP-03.7 (N28). WP-03.1 pinned that the pair folded only
    when neither side had absorbed a member: a snapshot is frozen before
    anchoring, so it has no rectangle, and the geometry branch needed one on
    both sides. The branch is gone. The anchor stage resolves each rectangle
    from the finding's own quote, so an equal quote on an equal rectangle is
    the quote alone, which Pass A already refuses without text agreement. The
    pair stays two entries in all eight configurations, and the live pair is
    no longer a duplicate. The cost is recall on a same-spot paraphrase
    (decided; ``tests/test_position_is_not_sameness.py``).
    """
    x_sev, y_sev = ("high", "low") if first == "X" else ("low", "high")
    ledger = Ledger()
    for text in _X[: 2 if x_absorbed else 1]:
        ledger.add([_f(text, "CO-1", sev=x_sev)], "digest_json")
    for text in _Y[: 2 if y_absorbed else 1]:
        ledger.add([_f(text, "CO-1", sev=y_sev)], "cross_qc")
    assert len(ledger) == 2                            # Pass A: too little shared text
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = Anchor(status="EXACT", rect_pdf=list(_RECT), method="exact")
    x_entry, y_entry = sorted(ledger.entries, key=lambda e: e.text not in _X)
    assert not _is_duplicate(x_entry, y_entry)         # one rectangle is not one issue

    assert reconcile_post_anchor(ledger) == 0
    assert len(ledger) == 2
    assert _history_is_a_clique(ledger)


def test_two_issues_that_quote_one_tag_stay_apart_after_anchoring():
    """N28, flipped by WP-03.7 (it was this file's recorded limit). Two
    different issues about one pump quote its tag, which is the norm, and
    share too few words for Pass A: its text check keeps them apart on
    purpose. Once both anchored to the tag, the geometry branch folded them
    (same quote, rectangles overlapping, no text check), and the impeller
    issue was gone: its text overwritten, its quote equal to the survivor's.
    The branch is gone, so both issues survive, each with its own text."""
    voltage = _f("pump P-1 voltage listed as 480 should be 208", "PUMP P-1")
    impeller = _f("pump P-1 impeller diameter conflicts with the curve", "PUMP P-1")
    ledger = Ledger()
    ledger.add([voltage], "digest_json")
    ledger.add([impeller], "critique_1")
    assert len(ledger) == 2                            # Pass A: the quote alone is not enough
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = Anchor(status="EXACT", rect_pdf=list(_RECT), method="exact")
    assert reconcile_post_anchor(ledger) == 0
    assert len(ledger) == 2
    exported = " ".join(_exported(e) for e in ledger.entries)
    assert "impeller" in exported and "480" in exported


# --------------------------------------------------------------------------- #
# Property check over generated same-sheet sets
# --------------------------------------------------------------------------- #

_MEASURES = ("", " is 500 gpm", " is 550 gpm")
_TAGS = ("", " at P-1", " at P-2")
_QUOTES = ("RISER", "RISER PUMP", "RISER PUMP FLOW", "RISER PUMP FLOW SCHEDULE")
# Where the anchor stage places each quote (``None``: not found). Two quotes
# share a place: the shape the geometry branch folded until WP-03.7, kept so
# the property below still meets it.
_PLACES = {"RISER": _RECT, "RISER PUMP": [11.0, 21.0, 61.0, 43.0],
           "RISER PUMP FLOW": _RECT, "RISER PUMP FLOW SCHEDULE": None}


def _generated(rng: random.Random, size: int) -> list[tuple]:
    specs = []
    for index in range(size):
        measure, tag = rng.choice(_MEASURES), rng.choice(_TAGS)
        text = (f"riser pump flow{measure} per riser schedule{tag}" if rng.random() < 0.7
                else f"coordinate pump{tag} with the riser{measure}")
        specs.append((text, rng.choice(_QUOTES), rng.choice(("low", "medium", "high")),
                      rng.choice(("coordination", "coordination", "question")),
                      rng.choice(("digest_json", "critique_1", "cross_qc")), f"#{index}"))
    return specs


def _ingest(specs: list[tuple], order: tuple[int, ...]) -> Ledger:
    """Pass A in ``order``, seal, then anchor each LIVE entry by its quote, as
    the pipeline's anchor stage does. Snapshots stay as Pass A froze them."""
    ledger = Ledger()
    for index in order:
        text, quote, sev, cat, source, label = specs[index]
        ledger.add([_f(text, quote, sev=sev, cat=cat, label=label)], source)
    ledger.seal()
    for entry in ledger.entries:
        place = _PLACES[entry.source_quote]
        if place is not None:
            entry.anchor = Anchor(status="EXACT", rect_pdf=list(place), method="exact")
    return ledger


def _partition(ledger: Ledger) -> set[frozenset[str]]:
    return {
        frozenset(l for m in ledger.member_history(e) for l in m.prose_item_ids)
        for e in ledger.entries
    }


def _reference_partition(ledger: Ledger) -> set[frozenset[str]]:
    """What the symmetric predicate implies, found WITHOUT the candidate index:
    every entry is compared with every earlier survivor, best-first, and joins
    the first whose members all duplicate all of its own. Read-only, so run it
    before Pass B mutates anything."""
    by_sheet: dict[tuple, list[Finding]] = {}
    for entry in ledger.entries:
        by_sheet.setdefault(source_page_key(entry), []).append(entry)
    groups: list[list[Finding]] = []
    for key in sorted(by_sheet):
        survivors: list[list[Finding]] = []
        for entry in sorted(by_sheet[key], key=_grounding_quality, reverse=True):
            mine = ledger.member_history(entry)
            for members in survivors:
                if all(_is_duplicate(a, b) for a in mine for b in members):
                    members.extend(mine)
                    break
            else:
                survivors.append(list(mine))
        groups.extend(survivors)
    return {frozenset(l for m in g for l in m.prose_item_ids) for g in groups}


def test_generated_sets_keep_the_invariants_in_every_order():
    """Seeded and bounded: 40 three-finding sets (all 6 orders) and 20
    four-finding sets (all 24 orders). In every run:

    * every entry's history is a clique of duplicates, and a second Pass B
      folds nothing;
    * the candidate index misses nothing: the partition equals the one found
      by comparing every entry with every earlier survivor. Every accepting
      branch of ``_is_duplicate`` needs a shared text token or an equal quote,
      and the pair made of the two entries' own representatives (the members
      carrying each live text and quote) is always among the pairs checked,
      so a survivor the index skips shares nothing with that pair and would
      fail the predicate anyway;
    * no Pass B fold involves an entry that absorbed a member in Pass A (none
      of these findings is anchored before ingest). Two entries Pass A kept
      apart hold a pair of members Pass A did not find to be duplicates; the
      only evidence Pass B adds is a rectangle, and a snapshot has none.

    For three findings the entry count is the same in every order (the B1
    shape, generalized). Four can differ: see the recorded limit above.
    """
    rng = random.Random(20260923)
    for size, count in ((3, 40), (4, 20)):
        for _ in range(count):
            specs = _generated(rng, size)
            entry_counts = set()
            for order in itertools.permutations(range(size)):
                ledger = _ingest(specs, order)
                reference = _reference_partition(ledger)
                absorbed = {
                    frozenset(l for m in ledger.member_history(e) for l in m.prose_item_ids)
                    for e in ledger.entries if len(ledger.member_history(e)) > 1
                }
                reconcile_post_anchor(ledger)
                assert _partition(ledger) == reference, (specs, order)
                assert _history_is_a_clique(ledger), (specs, order)
                assert absorbed <= _partition(ledger), (specs, order)
                before = _state(ledger)
                assert reconcile_post_anchor(ledger) == 0, (specs, order)
                assert _state(ledger) == before
                entry_counts.add(len(ledger))
            if size == 3:
                assert len(entry_counts) == 1, (specs, entry_counts)
