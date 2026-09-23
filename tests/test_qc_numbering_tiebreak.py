"""Remediation WP-03.2: QC numbers do not depend on arrival order (review K5).

Pure and hermetic: synthetic findings, no PyMuPDF, no network.

``models.assign_qc_ids`` numbers a run's findings by position: set-level
findings last, then source input order, page, anchored before unanchored, top,
left. Position alone leaves ties (two findings on one sheet with no rectangle,
two anchored to one rectangle, two set-level findings), and the tie-break was
the content ``id``. ``compute_finding_id`` hashes the quote, not the text, so
two different issues that quote one tag (``PUMP P-1``) share an id (review
B8). Python's sort is stable, so such a pair was numbered in the order it
arrived: ``[X, Y]`` gave X ``QC-001`` and ``[Y, X]`` gave Y ``QC-001``, against
the docstring's promise.

The tie-break is now a total order over the finding's own content: the id
(kept first, so every pair whose ids differ keeps its number), then the text,
then everything else the finding carries, with the lists whose order records
only arrival compared as sorted collections.

Pinned here:

* the K5 pair in both orders, unanchored and on one shared rectangle, directly
  and through the ledger, and the evidence directories named after the numbers;
* ledger entries that share text, quote, category and id: two that Pass A kept
  apart through conflicting absorbed members, and three that differ only in
  their cross-sheet legs;
* rect-less findings on one sheet, and set-level findings, among themselves;
* permutation properties over generated same-sheet sets;
* numbering twice gives the same numbers, and every pair the old key already
  ordered keeps its order;
* the content key reads every field but the number, sorts exactly the lists
  that record arrival, and never raises;
* a recorded limit for WP-03.5 (N29): a merged entry's representative can
  still depend on arrival order, and numbering follows the content it is given.

New helpers are imported inside the tests that use them, so on a base without
them only those tests fail on import (the remediation method).
"""
from __future__ import annotations

import dataclasses
import itertools
import json
import random

import pytest

from drawing_analyzer.ledger import Ledger, reconcile_post_anchor
from drawing_analyzer.models import (
    Anchor,
    CitationAssessment,
    ConflictLeg,
    Finding,
    Verification,
    assign_qc_ids,
    source_page_key,
)

_RECT = [100.0, 200.0, 160.0, 212.0]
_SET_LABEL = "(set-level)"      # prose_harvest.SET_LEVEL_SHEET_LABEL

_PUMP = "pump P-1 has no isolation valve on the suction side"
_MOTOR = "motor horsepower for P-1 disagrees with the pump schedule"


def _f(text: str, quote: str = "", *, sid: str = "SRC-0001", source: str = "M-101.pdf",
       page: int = 0, sheet: str = "M-101", cat: str = "coordination", sev: str = "medium",
       rect: list[float] | None = None, hint: str = "", legs=(), supp=()) -> Finding:
    return Finding(
        sheet_id=sheet, source_name=source, source_id=sid, page_index=page,
        category=cat, severity=sev, text=text, source_quote=quote, anchor_hint=hint,
        anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="exact") if rect else Anchor(),
        also_on=list(legs), supporting_quotes=list(supp),
    )


def _set_level(text: str, quote: str = "") -> Finding:
    """A set-level synthesis conflict, built as ``prose_harvest._set_level_entry``
    builds one (no source, ``SET_INDEX``, page -1)."""
    return Finding(
        sheet_id=_SET_LABEL, source_name="", source_id="", page_index=-1,
        category="conflict", severity="medium", text=text, source_quote=quote,
        anchor_hint="SET_INDEX",
        verification=Verification(status="SKIPPED", note="set-level synthesis conflict"),
    )


def _k5_pair(rect: list[float] | None = None) -> dict[str, Finding]:
    """Review K5's reproduction: one sheet, page, source, category and severity,
    both quoting the pump's tag, two different issues."""
    return {"X": _f(_PUMP, "PUMP P-1", rect=rect), "Y": _f(_MOTOR, "PUMP P-1", rect=rect)}


def _numbers(findings) -> dict[str, str]:
    return {f.text: f.qc_id for f in findings}


def _old_key(f: Finding) -> tuple:
    """The 1.7.0 numbering key, restated as a reference: position, then ``id``."""
    set_level = (f.anchor_hint or "").upper() in {"SET", "SET_INDEX"} and not f.source_id
    rect = f.anchor.rect_pdf if f.anchor is not None else None
    pos = (0, float(rect[1]), float(rect[0])) if rect else (1, 0.0, 0.0)
    return (1 if set_level else 0, source_page_key(f), pos, f.id)


# --------------------------------------------------------------------------- #
# The K5 pair
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rect", [None, _RECT], ids=["unanchored", "one-rectangle"])
def test_the_k5_pair_ties_on_everything_the_old_key_compared(rect):
    """The precondition: the pair reaches the tie-break."""
    pair = _k5_pair(rect)
    assert _old_key(pair["X"]) == _old_key(pair["Y"])    # the id hashes the quote (B8)


@pytest.mark.parametrize("rect", [None, _RECT], ids=["unanchored", "one-rectangle"])
def test_the_k5_pair_gets_the_same_numbers_in_both_orders(rect):
    numbered = []
    for order in ("XY", "YX"):
        pair = _k5_pair(rect)
        assign_qc_ids([pair[key] for key in order])
        numbered.append(_numbers(pair.values()))
    assert numbered[0] == numbered[1]
    # The text breaks an id tie, as in ``ledger._grounding_quality``.
    assert numbered[0] == {_MOTOR: "QC-001", _PUMP: "QC-002"}


def _k5_through_the_ledger(order: str, *, rect: list[float] | None = None,
                           pass_b: bool = True) -> list[Finding]:
    """Ingest in ``order``, seal, anchor every live entry as the anchor stage
    does (``rect=None``: the quote was not found), Pass B, number."""
    pair = _k5_pair()
    sources = {"X": "digest_json", "Y": "critique_1"}
    ledger = Ledger()
    for key in order:
        ledger.add([pair[key]], sources[key])
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = (
            Anchor(status="EXACT", rect_pdf=list(rect), method="exact") if rect
            else Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
        )
    if pass_b:
        reconcile_post_anchor(ledger)
    return ledger.number()


def test_the_k5_pair_through_the_ledger_unanchored():
    """The realistic pipeline case: a quote the anchor stage could not find
    leaves both entries rect-less on one sheet."""
    numbered = [_numbers(_k5_through_the_ledger(order)) for order in ("XY", "YX")]
    assert numbered[0] == numbered[1] == {_MOTOR: "QC-001", _PUMP: "QC-002"}


def test_the_k5_pair_through_the_ledger_on_one_rectangle_without_the_fold():
    """Both anchored to the tag and numbered with no Pass B fold between (the
    pipeline numbers anyway when Pass B raises, I-3)."""
    numbered = [
        _numbers(_k5_through_the_ledger(order, rect=_RECT, pass_b=False))
        for order in ("XY", "YX")
    ]
    assert numbered[0] == numbered[1] == {_MOTOR: "QC-001", _PUMP: "QC-002"}


def test_the_k5_pair_through_the_whole_lifecycle_on_one_rectangle():
    """Whatever Pass B decides, the numbers do not follow arrival. Until
    WP-03.7 it folded the pair (N28) and kept the same survivor in both orders.
    Now Pass B keeps them apart (a rectangle resolved from one quote is not
    evidence of one issue), so the tie-break above numbers them."""
    numbered = [_numbers(_k5_through_the_ledger(order, rect=_RECT)) for order in ("XY", "YX")]
    assert numbered[0] == numbered[1]
    assert numbered[0] == {_MOTOR: "QC-001", _PUMP: "QC-002"}


def test_the_evidence_directories_follow_the_numbers_not_the_arrival_order():
    """Verification names each finding's evidence directory after its number
    (``verify._reserve_evidence_dir``), so the pair's evidence must not swap
    directories with the arrival order either."""
    from drawing_analyzer.verify import _reserve_evidence_dir

    names = []
    for order in ("XY", "YX"):
        used: set[str] = set()
        names.append({e.text: _reserve_evidence_dir(e, used) for e in _k5_through_the_ledger(order)})
    assert names[0] == names[1] == {_MOTOR: "QC-001", _PUMP: "QC-002"}


# --------------------------------------------------------------------------- #
# Entries that share text, quote, category and id
# --------------------------------------------------------------------------- #

_GENERIC = "riser pump flow per riser schedule"
_LONG = "RISER PUMP FLOW PER RISER SCHEDULE"


def _absorbed_conflict() -> dict[str, tuple[Finding, str]]:
    """Two critique representatives with one text and one quote whose absorbed
    reads disagree (500 against 550 gpm, carried in their supporting quotes),
    and a digest finding for each measurement. Every order ends with the same
    two entries: each representative wins its entry's bundle (the longer
    quote) and absorbs the digest finding that agrees with it, and Pass A keeps
    the two entries apart through those members."""
    return {
        "R1": (_f(_GENERIC, _LONG, supp=["RISER PUMP 500 GPM"]), "critique_1"),
        "R2": (_f(_GENERIC, _LONG, supp=["RISER PUMP 550 GPM"]), "critique_1"),
        "A": (_f("riser pump flow is 500 gpm per riser schedule", "RISER"), "digest_json"),
        "C": (_f("riser pump flow is 550 gpm per riser schedule", "RISER"), "digest_json"),
    }


def test_entries_sharing_text_quote_and_category_are_ordered_by_what_they_absorbed():
    """Text and quote are not enough: these two entries share both, and the
    category and id with them. What tells them apart is what they absorbed,
    which reaches the live entry as its supporting quotes."""
    numberings = set()
    for order in itertools.permutations(["R1", "R2", "A", "C"]):
        items = _absorbed_conflict()
        ledger = Ledger()
        for key in order:
            finding, tag = items[key]
            ledger.add([finding], tag)
        ledger.seal()
        for entry in ledger.entries:
            entry.anchor = Anchor(status="UNANCHORED", rect_pdf=None, method="quote_not_found")
        reconcile_post_anchor(ledger)
        entries = ledger.number()
        assert len(entries) == 2, order
        one, two = entries
        # Everything the old key and the text compare is equal...
        assert _old_key(one) == _old_key(two), order
        assert (one.text, one.source_quote, one.category) == (two.text, two.source_quote, two.category)
        # ...and so is everything else but the supporting quotes.
        assert sorted(one.sources) == sorted(two.sources)
        assert (one.severity, one.reproduced, one.confidence) == (two.severity, two.reproduced, two.confidence)
        assert sorted(one.supporting_quotes) != sorted(two.supporting_quotes)
        numberings.add(frozenset((tuple(sorted(e.supporting_quotes)), e.qc_id) for e in entries))
    assert len(numberings) == 1, numberings


def test_entries_that_differ_only_in_their_legs_are_ordered_by_them():
    """One text and one quote, three different cross-sheet claims: two sets of
    legs that both exist and differ keep findings apart in the ledger
    (``critique.signature_conflicts``), and the legs order them. (A finding
    with no legs is compatible with any, so it would join whichever of these
    arrived first: the generic-bridge limit WP-03.6 owns.)"""
    def build() -> list[tuple[Finding, str]]:
        text, quote = "4 inch main conflicts with the riser size", "4 INCH MAIN"
        return [
            (_f(text, quote, legs=[ConflictLeg(sheet_id="E-201")]), "cross_qc"),
            (_f(text, quote, legs=[ConflictLeg(sheet_id="P-301")]), "cross_qc"),
            (_f(text, quote, legs=[ConflictLeg(sheet_id="A-501")]), "cross_qc"),
        ]

    numberings = set()
    for order in itertools.permutations(range(3)):
        items = build()
        ledger = Ledger()
        for index in order:
            finding, tag = items[index]
            ledger.add([finding], tag)
        ledger.seal()
        entries = ledger.number()
        assert len(entries) == 3
        assert len({_old_key(e) for e in entries}) == 1
        numberings.add(frozenset(
            (tuple(leg.sheet_id for leg in e.also_on), e.qc_id) for e in entries
        ))
    assert len(numberings) == 1, numberings


# --------------------------------------------------------------------------- #
# Rect-less and set-level findings among themselves
# --------------------------------------------------------------------------- #


def test_rect_less_findings_on_one_sheet_are_numbered_by_content_in_every_order():
    def build() -> list[Finding]:
        return [
            _f("the anchored finding at the top", "VAV-3", rect=[10.0, 40.0, 60.0, 52.0]),
            _f("no seismic bracing detail is provided", hint="SHEET"),
            _f("pump schedule lists no NPSH required", "PUMP SCHEDULE", hint="SHEET"),
            _f("pump schedule omits the motor voltage", "PUMP SCHEDULE", hint="SHEET"),
            _f(_PUMP, "PUMP P-1"),                    # unanchored: quote not found
            _f(_MOTOR, "PUMP P-1"),
        ]

    reference = None
    for order in itertools.permutations(range(6)):
        items = build()
        assign_qc_ids([items[i] for i in order])
        numbers = _numbers(items)
        if reference is None:
            reference = numbers
        assert numbers == reference, order
    # Position still comes first: the one anchored finding leads its sheet.
    assert reference["the anchored finding at the top"] == "QC-001"


def test_set_level_findings_are_numbered_by_content_after_every_sheet():
    def build() -> list[Finding]:
        return [
            _set_level("M-101 and P-101 disagree on the riser size", "RISER"),
            _set_level("the riser schedule contradicts the plumbing plan", "RISER"),
            _set_level("no sheet names the fire pump controller"),
            _f("a sheet finding", "VAV-3", rect=[10.0, 40.0, 60.0, 52.0]),
            _f("a finding on the second source", sid="SRC-0002", source="E-201.pdf",
               sheet="E-201", hint="SHEET"),
        ]

    probe = build()
    assert probe[0].id == probe[1].id           # the two quoting RISER tie on id
    reference = None
    for order in itertools.permutations(range(5)):
        items = build()
        assign_qc_ids([items[i] for i in order])
        numbers = _numbers(items)
        if reference is None:
            reference = numbers
        assert numbers == reference, order
    # Set-level findings still come after every source-scoped finding.
    assert {reference["a sheet finding"], reference["a finding on the second source"]} == {
        "QC-001", "QC-002"}


# --------------------------------------------------------------------------- #
# Generated sets
# --------------------------------------------------------------------------- #

_PHRASES = (
    "pump P-1 has no isolation valve", "motor horsepower disagrees with the schedule",
    "no seismic bracing detail", "riser size conflicts with the plan",
    "VAV-3 clearance is not shown", "valve tag is missing", "drain size differs",
    "the schedule omits the voltage", "flow is 500 gpm", "flow is 550 gpm",
)
_QUOTES = ("PUMP P-1", "PUMP P-1", "VAV-3", "")
# Two rectangles share a top-left corner, so anchored findings tie too.
_PLACES = (None, None, [10.0, 40.0, 60.0, 52.0], [10.0, 40.0, 70.0, 60.0],
           [30.0, 90.0, 80.0, 102.0])


def _generated(rng: random.Random, size: int, *, unique_text: bool,
               phrases: tuple[str, ...] = _PHRASES,
               categories: tuple[str, ...] = ("coordination", "conflict")) -> list[dict]:
    specs: list[dict] = []
    texts: set[str] = set()
    while len(specs) < size:
        text = rng.choice(phrases)
        if unique_text:
            text = f"{text} ({rng.randrange(10**6)})"
            if text in texts:
                continue
            texts.add(text)
        specs.append({
            "text": text, "quote": rng.choice(_QUOTES), "rect": rng.choice(_PLACES),
            "hint": rng.choice(("", "", "SHEET")), "cat": rng.choice(categories),
            "sev": rng.choice(("low", "medium", "high")),
            "legs": rng.choice(((), (), ("E-201",), ("P-301",))),
            "sources": rng.choice(((), ("digest_json", "critique_1"), ("critique_1", "digest_json"))),
            "supp": rng.choice(((), ("A", "B"), ("B", "A"))),
            "action": rng.choice(("", "", "confirm with the engineer")),
        })
    return specs


def _build(spec: dict) -> Finding:
    finding = _f(spec["text"], spec["quote"], cat=spec["cat"], sev=spec["sev"],
                 rect=spec["rect"], hint=spec["hint"],
                 legs=[ConflictLeg(sheet_id=s) for s in spec["legs"]], supp=spec["supp"])
    finding.sources = list(spec["sources"])
    finding.recommended_action = spec["action"]
    return finding


def _claim(finding: Finding) -> str:
    """The claim a finding makes, restated independently of the code under
    test: every serialized field but the number, with the lists that record
    only arrival order compared as sets."""
    data = finding.to_dict()
    data.pop("qc_id")
    for name in ("sources", "refs", "supporting_quotes", "prose_item_ids"):
        data[name] = sorted(data[name])
    data["citations"] = sorted(json.dumps(c, sort_keys=True) for c in data["citations"])
    return json.dumps(data, sort_keys=True)


def test_every_order_of_a_generated_same_sheet_set_gives_the_same_numbers():
    """Seeded and bounded: 60 five-finding sets with distinct texts, all 120
    orders each. Every order gives the same text -> number map."""
    rng = random.Random(20260923)
    tied_sets = 0
    for _ in range(60):
        specs = _generated(rng, 5, unique_text=True)
        probe = [_build(spec) for spec in specs]
        if len({_old_key(f) for f in probe}) < len(probe):
            tied_sets += 1
        reference = None
        for order in itertools.permutations(range(5)):
            findings = [_build(spec) for spec in specs]
            assign_qc_ids([findings[i] for i in order])
            numbers = _numbers(findings)
            if reference is None:
                reference = numbers
            assert numbers == reference, (specs, order)
    assert tied_sets >= 15        # not vacuous: 25 of the 60 seeded sets tie somewhere


def test_every_order_numbers_the_same_claims_the_same_way_when_texts_repeat():
    """Texts drawn from a small pool, so findings tie on id AND text and differ
    only in what else they carry (severity, legs, provenance, supporting quotes,
    action, placement), or in the order of the lists that record arrival. The
    claims (``_claim``) receive the same numbers in every order: two findings
    that make the same claim are interchangeable."""
    rng = random.Random(3)
    deep_ties = 0
    for _ in range(80):
        specs = _generated(rng, 5, unique_text=False, phrases=_PHRASES[:3],
                           categories=("coordination",))
        probe = [_build(spec) for spec in specs]
        keys = [(_old_key(f), f.text) for f in probe]
        if len(set(keys)) < len(keys):
            deep_ties += 1
        reference = None
        for order in itertools.permutations(range(5)):
            findings = [_build(spec) for spec in specs]
            assign_qc_ids([findings[i] for i in order])
            numbers = sorted((_claim(f), f.qc_id) for f in findings)
            if reference is None:
                reference = numbers
            assert numbers == reference, (specs, order)
    assert deep_ties >= 15        # 29 of the 80 seeded sets tie on id AND text


# --------------------------------------------------------------------------- #
# Idempotence and what does not change
# --------------------------------------------------------------------------- #


def test_numbering_twice_gives_the_same_numbers():
    items = _absorbed_conflict()
    ledger = Ledger()
    for finding, tag in items.values():
        ledger.add([finding], tag)
    for finding in _k5_pair().values():
        ledger.add([finding], "digest_json")
    ledger.seal()
    first = {id(e): e.qc_id for e in ledger.number()}
    assert len(set(first.values())) == len(first) == 4
    second = {id(e): e.qc_id for e in ledger.number()}
    assert second == first


def test_every_pair_the_old_key_ordered_keeps_its_order():
    """Only ties change. Wherever the 1.7.0 key (position, then id) already
    told two findings apart, they keep the order it gave them, across sources,
    pages, anchored and rect-less findings and set-level findings."""
    rng = random.Random(7)
    for _ in range(200):
        findings = []
        for _ in range(rng.randrange(2, 9)):
            spec = _generated(rng, 1, unique_text=False)[0]
            if rng.random() < 0.2:
                finding = _set_level(spec["text"], spec["quote"])
            else:
                finding = _build(spec)
                finding.source_id = rng.choice(("SRC-0001", "SRC-0002"))
                finding.page_index = rng.choice((0, 1))
            findings.append(finding)
        rng.shuffle(findings)
        assign_qc_ids(findings)
        for a, b in itertools.combinations(findings, 2):
            if _old_key(a) != _old_key(b):
                assert (_old_key(a) < _old_key(b)) == (a.qc_id < b.qc_id), (a, b)


# --------------------------------------------------------------------------- #
# The content key
# --------------------------------------------------------------------------- #


def test_the_content_key_reads_every_field_but_the_number():
    """A field left out of the key can tie two different findings again, and a
    field added to ``Finding`` later is covered without being listed."""
    from drawing_analyzer.models import _qc_content_key

    content = json.loads(_qc_content_key(_f("text", "QUOTE")))
    assert set(content) == {fld.name for fld in dataclasses.fields(Finding)} - {"qc_id"}


def _two(kind: str) -> list:
    if kind == "citations":
        return [CitationAssessment(reference="NFPA 13 2025"),
                CitationAssessment(reference="NFPA 20 2025")]
    if kind == "also_on":
        return [ConflictLeg(sheet_id="E-201"), ConflictLeg(sheet_id="P-301")]
    if kind == "tile":
        return [1, 2]
    return ["a", "b"]


def test_only_the_lists_that_record_arrival_are_compared_as_sets():
    """Every list field is classified. The ledger unions ``sources``, ``refs``,
    ``supporting_quotes`` and ``prose_item_ids`` member by member in arrival
    order, and the citation stage writes ``citations`` in ``refs`` order, so
    their order says nothing about the claim. ``tile`` is ``[row, col]`` and
    ``also_on`` is one producer's legs in the order its evidence is numbered."""
    from drawing_analyzer.models import _ARRIVAL_ORDERED_FIELDS, _qc_content_key

    list_fields = {
        fld.name for fld in dataclasses.fields(Finding) if "list[" in str(fld.type)
    }
    ordered_by_meaning = {"tile", "also_on"}
    assert set(_ARRIVAL_ORDERED_FIELDS) | ordered_by_meaning == list_fields
    assert not set(_ARRIVAL_ORDERED_FIELDS) & ordered_by_meaning
    for name in sorted(list_fields):
        forward, backward = _f("text", "QUOTE"), _f("text", "QUOTE")
        setattr(forward, name, _two(name))
        setattr(backward, name, list(reversed(_two(name))))
        same = _qc_content_key(forward) == _qc_content_key(backward)
        assert same == (name in _ARRIVAL_ORDERED_FIELDS), name


def test_the_content_key_never_raises():
    """Numbering is not wrapped by the pipeline, so the key must accept any
    finding a stage can hold: missing sub-objects and odd list contents."""
    from drawing_analyzer.models import _qc_content_key

    odd = _f("text", "QUOTE")
    odd.anchor = None
    odd.verification = None
    odd.refs = ["NFPA 13", 13, None]
    odd.tile = None
    assert isinstance(_qc_content_key(odd), str)
    twin = _f("text", "QUOTE")
    twin.anchor = None
    assign_qc_ids([odd, twin])
    assert {odd.qc_id, twin.qc_id} == {"QC-001", "QC-002"}


# --------------------------------------------------------------------------- #
# Recorded limit (WP-03.5 flips it)
# --------------------------------------------------------------------------- #

# N29: which member represents a merged entry, by arrival order. X and Z tie
# on quote length and Y has the shorter quote but the higher severity. When Y
# merges first, the severity union raises the survivor to ``high`` before the
# X/Z comparison, which ``_grounding_quality`` then decides on that borrowed
# severity instead of the members' own.
_N29_REPRESENTATIVE = {
    "XYZ": "RISER PUMP SCHEDULE AA", "YXZ": "RISER PUMP SCHEDULE AA",
    "XZY": "RISER PUMP SCHEDULE ZZ", "YZX": "RISER PUMP SCHEDULE ZZ",
    "ZXY": "RISER PUMP SCHEDULE ZZ", "ZYX": "RISER PUMP SCHEDULE ZZ",
}


@pytest.mark.parametrize("order", sorted(_N29_REPRESENTATIVE))
def test_recorded_limit_a_merged_entrys_representative_follows_arrival_order(order):
    """Numbering follows the content it is given; the ledger can still give it
    different content in different orders (N29, found by WP-03.2, owned by
    WP-03.5). Three duplicates of one issue merge into one entry in every
    order, but its text, quote and id come from X in two orders and from Z in
    four. ``test_the_representative_does_not_depend_on_ingest_order`` pins the
    two-member case, where no earlier merge has raised the severity yet."""
    members = {
        "X": _f("riser pump flow is shown on the riser schedule",
                "RISER PUMP SCHEDULE AA", sev="low"),
        "Y": _f("riser pump flow is shown on the riser schedule here", "RISER PUMP",
                sev="high"),
        "Z": _f("riser pump flow is shown on riser schedule",
                "RISER PUMP SCHEDULE ZZ", sev="medium"),
    }
    ledger = Ledger()
    for key in order:
        ledger.add([members[key]], "digest_json")
    assert len(ledger) == 1
    assert ledger.entries[0].source_quote == _N29_REPRESENTATIVE[order]
