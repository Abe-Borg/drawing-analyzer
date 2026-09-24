"""Remediation WP-09.2 (N10, U11): a prose item joins an existing ledger entry
only when their critical signatures agree, and every enumerated item's outcome
is recorded.

The owner's rules (2026-09-24, measured first; ``_plans/PROGRESS.md``):

1. **The veto reuses the one rule.** ``_match_entry`` refuses a candidate at or
   above ``_MATCH_OVERLAP`` whose critical signature conflicts with the item's:
   ``critique.signature_conflicts`` over ``critique.critical_signature``, never
   a second copy. The item is signed from its text and its synthesis legs; the
   candidate from its text, quote and legs with its sheet-level placement
   (``anchor_hint``) set aside, so polarity is read from both texts ("text
   against text": a placement says where a mark goes, not what it claims, and
   a prose item has none).
2. **The next-best compatible candidate wins** when the best is refused: the
   veto only removes incompatible entries from the pool.
3. **A refused item is a straggler**: one structuring call (or a cache hit),
   or a degraded entry with no client. The ledger's own rule then decides
   whether its finding folds.
4. **Every enumerated item has exactly one outcome** (``HarvestResult.outcomes``:
   its channel, its outcome, the structuring call it cost, whether its finding
   folded, how many candidates the veto refused), and the run-level counts add
   up to them. ``vetoed``, ``folded``, ``filtered_focus`` and a per-channel
   table reach ``prose_accounting`` (``run.log``, ``run_manifest.json``). All
   of it is observational: only ``missing`` decides the stage.
5. **Suppressed items are counted per channel**, never given ids: digest filler
   (``filtered``), synthesis assurances (``assurances``) and focus filler
   (``filtered_focus``, counted whether or not focus is harvested).
6. The threshold stays 0.7 (U11). ``tests/test_prose_paraphrase_corpus.py``
   holds the labelled evidence for any later change.
"""
from __future__ import annotations

import collections
import json
import threading
import time

import pytest

from drawing_analyzer.critique import _token_overlap
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import ConflictLeg, Finding
from drawing_analyzer.prose_harvest import (
    HARVEST_SYSTEM_PROMPT,
    HarvestResult,
    _MATCH_OVERLAP,
    _match_entry,
    harvest_prose,
)
from tests.fixtures import gauntlet as G
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)
from tests.test_drawing_ledger import (
    _Digest,
    _f,
    _finding_block,
    _Geom,
    _structuring_client,
    _titleblock_word,
)

_OUTCOME_WORDS = ("matched", "structured", "degraded", "set_level", "missing")


def _entry(text, *, hint="", quote="", legs=(), cat="coordination", source="a.pdf", page=0):
    return Finding(
        sheet_id="F-D-01-1", source_name=source, page_index=page, category=cat,
        severity="medium", text=text, source_quote=quote, anchor_hint=hint,
        also_on=[
            ConflictLeg(sheet_id=sid, source_name=src, page_index=0)
            for sid, src in legs
        ],
    )


def _no_sleep(*_args):
    return None


def _geom(page=0):
    return _Geom(page=page, words=[_titleblock_word("F-D-01-1")])


def _coordination(*items, page=0):
    body = "".join(f"- {item}\n" for item in items)
    return _Digest(f"**Coordination items**\n{body}", page=page)


# --------------------------------------------------------------------------- #
# N10: a distinct claim is no longer absorbed
# --------------------------------------------------------------------------- #

# The request's four measured cases: each matched on main, and each names the
# axis the veto refuses it on.
_N10 = [
    ("Provide 4 inch drain at column line 4.",
     "Provide 6 inch drain at column line 4.", "measurements"),
    ("Fire pump relief valve set at 165 psi; pump rated 175 psi at churn.",
     "Fire pump relief valve set at 150 psi; pump rated 175 psi at churn.",
     "measurements"),
    ("Pump P-2 discharge valve is not shown on the riser diagram.",
     "Pump P-1 discharge valve is not shown on the riser diagram.", "tags"),
    ("Fire pump P-1 rated flow 550 gpm per schedule.",
     "Fire pump P-1 rated flow 500 gpm per schedule.", "measurements"),
]
_N10_IDS = ["drain", "psi", "tag", "gpm"]


@pytest.mark.parametrize("hint", ["", "SHEET"], ids=["plain", "sheet"])
@pytest.mark.parametrize("item,existing,axis", _N10, ids=_N10_IDS)
def test_n10_a_distinct_claim_is_not_matched(item, existing, axis, hint):
    entry = _entry(existing, hint=hint)
    # The text alone still clears the threshold: the veto is what refuses it.
    assert _token_overlap(item, existing) >= _MATCH_OVERLAP
    assert _match_entry(item, [entry]) is None


@pytest.mark.parametrize("hint", ["", "SHEET"], ids=["plain", "sheet"])
@pytest.mark.parametrize("item,existing,axis", _N10, ids=_N10_IDS)
def test_n10_the_veto_names_the_axis(item, existing, axis, hint):
    from drawing_analyzer.prose_harvest import _veto_axes

    assert axis in _veto_axes(item, _entry(existing, hint=hint))


@pytest.mark.parametrize("item,existing,axis", _N10, ids=_N10_IDS)
def test_n10_with_a_client_the_item_is_structured_into_its_own_entry(item, existing, axis):
    ledger = Ledger()
    kept = _f(existing, cat="coordination")
    ledger.add([kept], "digest_json")
    client = _structuring_client([_finding_block(item)])

    res = harvest_prose(ledger, [_coordination(item)], [_geom()],
                        client=client, sleep=_no_sleep)

    assert client.calls == res.api_calls == 1
    assert (res.items, res.matched, res.structured, res.degraded, res.missing) == (1, 0, 1, 0, 0)
    assert len(ledger) == 2
    first, second = ledger.entries
    # The entry it used to join is untouched.
    assert first is kept and first.text == existing
    assert first.sources == ["digest_json"]
    assert first.prose_item_ids == [] and first.also_on == []
    assert second.text == item
    assert second.sources == ["digest_prose_coordination"]
    assert second.prose_item_ids == res.expected_ids


@pytest.mark.parametrize("item,existing,axis", _N10, ids=_N10_IDS)
def test_n10_without_a_client_the_item_is_degraded_into_its_own_entry(item, existing, axis):
    ledger = Ledger()
    kept = _f(existing, cat="coordination")
    ledger.add([kept], "digest_json")

    res = harvest_prose(ledger, [_coordination(item)], [_geom()],
                        client=None, sleep=_no_sleep)

    assert (res.items, res.matched, res.structured, res.degraded, res.missing) == (1, 0, 0, 1, 0)
    assert len(ledger) == 2
    first, second = ledger.entries
    assert first is kept and first.text == existing
    assert first.sources == ["digest_json"] and first.prose_item_ids == []
    assert second.text == item and second.anchor_hint == "SHEET"
    assert second.prose_item_ids == res.expected_ids


# --------------------------------------------------------------------------- #
# Kept: a restatement still matches, free
# --------------------------------------------------------------------------- #

_KEPT = [
    ("paraphrase", "6 inch drain required at column line 4.",
     "Provide 6 inch drain at column line 4.", "", ""),
    ("paraphrase-of-degraded", "6 inch drain required at column line 4.",
     "Provide 6 inch drain at column line 4.", "SHEET", ""),
    # Its own degraded (or quote-less structured) twin: identical text, placed
    # sheet-level. Text against text reads both as the same presence claim.
    ("degraded-twin", "Duct riser blocks the corridor door.",
     "Duct riser blocks the corridor door.", "SHEET", ""),
    ("absence-twin", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve is not shown at the pump discharge.", "SHEET", ""),
    ("critique-absence", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve not found at the pump discharge.", "SHEET", ""),
    ("gauntlet", G.PROSE_MATCHED, "Duct liner omitted at the riser.", "", G.Q_F2),
    ("five-item", "Note 7 says relief at 175 psi but the schedule row shows 165 psi.",
     "Note 7 says relief at 175 psi but the schedule row shows 165 psi", "", ""),
]


@pytest.mark.parametrize(
    "item,existing,hint,quote", [c[1:] for c in _KEPT], ids=[c[0] for c in _KEPT]
)
def test_a_restatement_still_matches(item, existing, hint, quote):
    entry = _entry(existing, hint=hint, quote=quote)
    assert _match_entry(item, [entry]) is entry


def test_a_restatement_matches_free_with_no_call():
    ledger = Ledger()
    kept = _f("Provide 6 inch drain at column line 4.", cat="coordination")
    ledger.add([kept], "digest_json")
    client = _structuring_client([_finding_block("never asked")])

    res = harvest_prose(ledger, [_coordination("6 inch drain required at column line 4.")],
                        [_geom()], client=client, sleep=_no_sleep)

    assert client.calls == 0 and res.api_calls == 0
    assert res.matched == 1 and len(ledger) == 1
    assert kept.sources == ["digest_json", "digest_prose_coordination"]
    assert kept.prose_item_ids == res.expected_ids


# --------------------------------------------------------------------------- #
# Polarity: text against text (the owner's signing rule)
# --------------------------------------------------------------------------- #

_POLARITY = [
    ("absence-vs-presence", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve is shown at the pump discharge.", ""),
    # Against a degraded entry (the prose verbatim, placed sheet-level) the
    # placement is not a claim: the candidate's own text says what it claims.
    ("presence-vs-degraded-absence", "Isolation valve is shown at the pump discharge.",
     "Isolation valve is not shown at the pump discharge.", "SHEET"),
    ("absence-vs-degraded-presence", "Isolation valve is not shown at the pump discharge.",
     "Isolation valve is shown at the pump discharge.", "SHEET"),
]


@pytest.mark.parametrize(
    "item,existing,hint", [c[1:] for c in _POLARITY], ids=[c[0] for c in _POLARITY]
)
def test_an_opposite_polarity_item_is_not_matched(item, existing, hint):
    assert _token_overlap(item, existing) >= _MATCH_OVERLAP
    assert _match_entry(item, [_entry(existing, hint=hint)]) is None


def test_recorded_limit_a_presence_item_joins_a_sheet_absence_with_no_absence_word():
    # The candidate is an absence only by its SHEET placement (the critique's
    # "sheet-level or absence" hint), and its text carries no absence word, so
    # text against text reads both as presence. Signing the item with the
    # candidate's placement would miss it too; only a text-only item against
    # the placement-aware candidate refuses it, and that option refused 5 true
    # restatements in the suite (their quote-less twins). Recorded, not fixed.
    entry = _entry("Isolation valve at the pump discharge.", hint="SHEET")
    assert _match_entry("Isolation valve at the pump discharge is shown.", [entry]) is entry


# --------------------------------------------------------------------------- #
# Synthesis legs are part of the item's signature
# --------------------------------------------------------------------------- #


def _three_sheet_geoms():
    return [
        _Geom("a.pdf", 0, words=[_titleblock_word("M-101")]),
        _Geom("b.pdf", 0, words=[_titleblock_word("P-101")]),
        _Geom("c.pdf", 0, words=[_titleblock_word("E-201")]),
    ]


_SYNTHESIS_CONFLICT = "The riser on M-101 conflicts with the duct on P-101."


def test_a_synthesis_item_does_not_join_a_conflict_with_other_legs():
    ledger = Ledger()
    existing = _entry("The riser on M-101 conflicts with the duct.",
                      legs=[("E-201", "c.pdf")], cat="conflict")
    ledger.add([existing], "cross_qc")

    res = harvest_prose(ledger, [], _three_sheet_geoms(), client=None,
                        synthesis_text=_SYNTHESIS_CONFLICT, sleep=_no_sleep)

    assert (res.items, res.matched, res.degraded, res.missing) == (1, 0, 1, 0)
    assert len(ledger) == 2
    first, second = ledger.entries
    assert first is existing
    assert [leg.sheet_id for leg in first.also_on] == ["E-201"]
    assert first.prose_item_ids == [] and first.sources == ["cross_qc"]
    assert second.text == _SYNTHESIS_CONFLICT
    assert [leg.sheet_id for leg in second.also_on] == ["P-101"]


def test_a_synthesis_item_still_matches_an_entry_without_legs_and_lends_its_leg():
    ledger = Ledger()
    existing = _entry("The riser on M-101 conflicts with the duct.", cat="conflict")
    ledger.add([existing], "cross_qc")

    res = harvest_prose(ledger, [], _three_sheet_geoms(), client=None,
                        synthesis_text=_SYNTHESIS_CONFLICT, sleep=_no_sleep)

    assert res.matched == 1 and len(ledger) == 1
    assert [leg.sheet_id for leg in existing.also_on] == ["P-101"]
    assert existing.prose_item_ids == res.expected_ids


def test_the_veto_reads_the_items_legs():
    from drawing_analyzer.prose_harvest import _veto_axes

    existing = _entry("The riser on M-101 conflicts with the duct.",
                      legs=[("E-201", "c.pdf")], cat="conflict")
    legs = [ConflictLeg(sheet_id="P-101", source_name="b.pdf", page_index=0)]
    assert _veto_axes(_SYNTHESIS_CONFLICT, existing) == []
    assert _veto_axes(_SYNTHESIS_CONFLICT, existing, legs) == ["cross_sheet_legs"]
    assert _match_entry(_SYNTHESIS_CONFLICT, [existing], also_on=legs) is None
    assert _match_entry(_SYNTHESIS_CONFLICT, [existing]) is existing


# --------------------------------------------------------------------------- #
# Which candidate wins (the owner's rule: the next-best compatible one)
# --------------------------------------------------------------------------- #

_FOUR_INCH = "Provide 4 inch drain at column line 4."


def test_the_next_best_compatible_candidate_wins_when_the_best_is_refused():
    six = _entry("Provide 6 inch drain at column line 4.")          # 0.857, refused
    four = _entry("Provide 4 inch drain at column line 4 per plan.")  # 0.75, compatible
    assert _token_overlap(_FOUR_INCH, six.text) > _token_overlap(_FOUR_INCH, four.text)
    assert _token_overlap(_FOUR_INCH, four.text) >= _MATCH_OVERLAP
    assert _match_entry(_FOUR_INCH, [six, four]) is four
    assert _match_entry(_FOUR_INCH, [four, six]) is four


def test_a_refused_candidate_is_reported_to_the_caller():
    six = _entry("Provide 6 inch drain at column line 4.")
    four = _entry("Provide 4 inch drain at column line 4 per plan.")
    refused = []
    assert _match_entry(_FOUR_INCH, [six, four], refused=refused) is four
    assert refused == [six]


def test_when_every_candidate_is_refused_nothing_matches():
    six = _entry("Provide 6 inch drain at column line 4.")
    eight = _entry("Provide 8 inch drain at column line 4.")
    refused = []
    assert _match_entry(_FOUR_INCH, [six, eight]) is None
    assert _match_entry(_FOUR_INCH, [six, eight], refused=refused) is None
    assert refused == [six, eight]


def test_equal_scores_keep_ledger_order():
    first = _entry("Provide 6 inch drain at column line 4.")
    second = _entry("Provide 6 inch drain at column line 4.", quote="6 INCH DRAIN")
    item = "Provide 6 inch drain at column line 4."
    assert _match_entry(item, [first, second]) is first
    assert _match_entry(item, [second, first]) is second


def test_a_next_best_match_in_the_harvest_records_the_refusal():
    ledger = Ledger()
    six = _f("Provide 6 inch drain at column line 4.", cat="coordination")
    four = _f("Provide 4 inch drain at column line 4 per plan.", cat="coordination")
    ledger.add([six], "digest_json")
    ledger.add([four], "critique_1")

    res = harvest_prose(ledger, [_coordination(_FOUR_INCH)], [_geom()],
                        client=None, sleep=_no_sleep)

    assert res.matched == 1 and len(ledger) == 2
    assert six.prose_item_ids == [] and four.prose_item_ids == res.expected_ids
    (outcome,) = res.outcomes.values()
    assert (outcome.outcome, outcome.refused) == ("matched", 1)
    assert res.vetoed == 1


# --------------------------------------------------------------------------- #
# Both callers agree: the parallel path's chain count reads the same rule
# --------------------------------------------------------------------------- #


def _two_page_ledger():
    ledger = Ledger()
    ledger.add([_f("Provide 6 inch drain at column line 4.", cat="coordination", page=0)],
               "digest_json")
    ledger.add([_f("Fire pump P-1 rated flow 500 gpm per schedule.", cat="coordination",
                   page=1)], "digest_json")
    return ledger


_PAGE_ITEMS = ("Provide 4 inch drain at column line 4.",
               "Fire pump P-1 rated flow 550 gpm per schedule.")


class _TwoPageClient(BetaClientMixin):
    """Structures each page's item; with ``barrier`` both calls must overlap."""

    def __init__(self, *, barrier=None):
        self.calls: list[str] = []
        self.max_active = 0
        active = 0
        lock = threading.Lock()
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(_self, **kw):  # noqa: ANN001, ANN202
                nonlocal active
                user = kw["messages"][0]["content"]
                text = _PAGE_ITEMS[0] if _PAGE_ITEMS[0] in user else _PAGE_ITEMS[1]
                with lock:
                    active += 1
                    outer.max_active = max(outer.max_active, active)
                if barrier is not None:
                    barrier.wait(timeout=5)
                with lock:
                    active -= 1
                    outer.calls.append(text)
                return FakeMessage(
                    content=[FakeTextBlock(text=_finding_block(text))],
                    usage=FakeUsage(input_tokens=90, output_tokens=30),
                )

        self.messages = _Msgs()


def test_refused_items_on_two_pages_are_two_parallel_chains():
    digests = [_coordination(_PAGE_ITEMS[0], page=0), _coordination(_PAGE_ITEMS[1], page=1)]
    geoms = [_geom(0), _geom(1)]

    parallel_ledger = _two_page_ledger()
    parallel_client = _TwoPageClient(barrier=threading.Barrier(2))
    parallel = harvest_prose(parallel_ledger, digests, geoms, client=parallel_client,
                             max_workers=2, sleep=_no_sleep)

    # Both chains hold a straggler once the veto refuses the initial matches,
    # so the calls run side by side (active_chain_count reads _match_entry).
    assert parallel_client.max_active == 2 and parallel.api_calls == 2
    assert parallel.structured == 2 and parallel.matched == 0
    assert len(parallel_ledger) == 4

    sequential_ledger = _two_page_ledger()
    sequential = harvest_prose(sequential_ledger, digests, geoms, client=_TwoPageClient(),
                               max_workers=1, sleep=_no_sleep)
    assert parallel == sequential
    assert [e.to_dict() for e in parallel_ledger.entries] == [
        e.to_dict() for e in sequential_ledger.entries
    ]


# --------------------------------------------------------------------------- #
# Per-item outcomes (plan step 4) and duplicate outcomes (step 5)
# --------------------------------------------------------------------------- #

_FIVE_ITEM_DIGEST = """Sheet F-D-01-1 - Fire Protection - Demand

**Coordination / cross-discipline items**
- Penetration at grid C-4 must be sleeved by structural.
- FP riser shares a chase with the plumbing vent; verify the access panel.
- Equipment pad for the fire pump is shown by another discipline.

**Conflicts / discrepancies**
- Note 7 says relief at 175 psi but the schedule row shows 165 psi.
- The riser diagram shows a check valve the plan never draws.
"""


def _five_item_run(*, synthesis=""):
    ledger = Ledger()
    ledger.add([
        _f("Penetration at grid C-4 must be sleeved by structural", cat="coordination"),
        _f("FP riser shares a chase with the plumbing vent; verify the access panel",
           cat="coordination"),
        _f("Note 7 says relief at 175 psi but the schedule row shows 165 psi",
           cat="conflict"),
    ], "digest_json")
    client = _structuring_client([
        _finding_block("Fire pump equipment pad is shown by another discipline."),
        _finding_block("Riser diagram shows a check valve the plan never draws.",
                       quote="CHECK VALVE"),
    ])
    res = harvest_prose(
        ledger, [_Digest(_FIVE_ITEM_DIGEST)],
        [_Geom(sheet_text="CHECK VALVE AT RISER", words=[_titleblock_word("F-D-01-1")])],
        client=client, synthesis_text=synthesis, sleep=_no_sleep,
    )
    return res, ledger


def test_every_enumerated_item_has_exactly_one_outcome():
    synthesis = G.SET_LEVEL_CONFLICT_SENTENCE
    res, _ledger = _five_item_run(synthesis=synthesis)

    assert set(res.outcomes) == set(res.expected_ids)
    counts = collections.Counter(o.outcome for o in res.outcomes.values())
    assert counts == {"matched": 3, "structured": 2, "set_level": 1}
    for word in _OUTCOME_WORDS:
        assert counts.get(word, 0) == getattr(res, word)
    assert sum(counts.values()) == res.items == 6


def test_the_outcome_record_carries_channel_call_fold_and_refusals():
    res, ledger = _five_item_run()
    by_text = {}
    for entry in ledger.entries:
        for pid in entry.prose_item_ids:
            by_text[entry.text] = res.outcomes[pid]

    matched = by_text["Penetration at grid C-4 must be sleeved by structural"]
    assert (matched.channel, matched.outcome, matched.call, matched.folded,
            matched.refused) == ("digest_prose_coordination", "matched", "none", False, 0)
    structured = by_text["Riser diagram shows a check valve the plan never draws."]
    assert (structured.channel, structured.outcome, structured.call) == (
        "digest_prose_conflict", "structured", "live")
    assert structured.prose_item_id in res.expected_ids


def test_a_structured_straggler_the_ledger_folds_is_counted_folded():
    ledger = Ledger()
    kept = _f("Duct riser blocks the corridor door at grid 5", quote="DUCT RISER",
              cat="coordination")
    ledger.add([kept], "digest_json")
    item = "The corridor door is blocked by the duct riser near grid five."
    assert _token_overlap(item, kept.text) < _MATCH_OVERLAP     # not a free match
    client = _structuring_client([
        _finding_block("Duct riser blocks the corridor door at grid 5", quote="DUCT RISER"),
    ])

    res = harvest_prose(ledger, [_coordination(item)],
                        [_Geom(sheet_text="DUCT RISER", words=[_titleblock_word("F-D-01-1")])],
                        client=client, sleep=_no_sleep)

    assert (res.structured, res.folded, len(ledger)) == (1, 1, 1)
    assert kept.prose_item_ids == res.expected_ids
    (outcome,) = res.outcomes.values()
    assert (outcome.outcome, outcome.folded, outcome.call) == ("structured", True, "live")


def test_recorded_limit_a_refused_presence_item_degraded_folds_into_the_absence():
    # The veto reads polarity from both texts and refuses the match. The item
    # then degrades (no client) into a SHEET-placed entry, and the LEDGER reads
    # SHEET as an absence (critique._is_absence, which its merges share), so
    # the presence claim folds into the absence entry after all. Out of scope
    # here (the ledger's reading is not this slice's to change); the per-item
    # record makes it visible: vetoed, degraded, folded.
    ledger = Ledger()
    absent = _f("Isolation valve is not shown at the pump discharge.", cat="coordination")
    ledger.add([absent], "digest_json")

    res = harvest_prose(ledger, [_coordination("Isolation valve is shown at the pump discharge.")],
                        [_geom()], client=None, sleep=_no_sleep)

    assert (res.vetoed, res.degraded, res.folded, len(ledger)) == (1, 1, 1, 1)
    (outcome,) = res.outcomes.values()
    assert (outcome.outcome, outcome.folded, outcome.refused) == ("degraded", True, 1)


class _FlakyLedger(Ledger):
    """Refuses the first structured finding once, as a transient failure would."""

    def __init__(self):
        super().__init__()
        self.failed = False

    def add(self, findings, source=""):
        findings = list(findings)
        if not self.failed and any("structured version" in f.text for f in findings):
            self.failed = True
            raise RuntimeError("transient ledger failure")
        return super().add(findings, source)


def test_an_item_whose_ingest_failed_is_counted_once():
    # On main the item was counted structured (before the ledger took it) AND
    # degraded (by the reconcile that recovered it): two outcomes for one item.
    ledger = _FlakyLedger()
    client = _structuring_client([_finding_block("structured version of the item")])
    res = harvest_prose(ledger, [_coordination(
        "Shared chase clearances must be coordinated with the electrical layout.")],
        [_geom()], client=client, sleep=_no_sleep)

    assert res.items == 1 and res.missing == 0 and len(ledger) == 1
    assert (res.structured, res.degraded) == (0, 1)
    assert res.matched + res.structured + res.degraded + res.set_level == res.items


def test_a_recovered_item_keeps_the_call_it_cost():
    ledger = _FlakyLedger()
    client = _structuring_client([_finding_block("structured version of the item")])
    res = harvest_prose(ledger, [_coordination(
        "Shared chase clearances must be coordinated with the electrical layout.")],
        [_geom()], client=client, sleep=_no_sleep)

    (outcome,) = res.outcomes.values()
    assert (outcome.outcome, outcome.call) == ("degraded", "live")
    assert res.api_calls == 1


def test_the_call_field_records_a_cache_hit():
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    client = _structuring_client([_finding_block("Structured cached coordination item.")])
    digest = _coordination("Shared chase clearances must be coordinated with the electrical layout.")
    first = harvest_prose(Ledger(), [digest], [_geom()], client=client, cache=cache,
                          sleep=_no_sleep)
    second = harvest_prose(Ledger(), [digest], [_geom()], client=client, cache=cache,
                           sleep=_no_sleep)

    assert [o.call for o in first.outcomes.values()] == ["live"]
    assert [o.call for o in second.outcomes.values()] == ["cache"]


def test_a_missing_item_has_the_missing_outcome(monkeypatch):
    import drawing_analyzer.prose_harvest as PH

    def _boom(*_args, **_kwargs):
        raise RuntimeError("unrecoverable")

    monkeypatch.setattr(PH, "_process_pending", _boom)
    monkeypatch.setattr(PH, "_degraded_entry", _boom)
    res = harvest_prose(Ledger(), [_coordination(
        "Shared chase clearances must be coordinated with the electrical layout.")],
        [_geom()], client=None, sleep=_no_sleep)

    assert res.missing == 1 and res.complete is False
    assert [o.outcome for o in res.outcomes.values()] == ["missing"]


# --------------------------------------------------------------------------- #
# Suppressed items: counted per channel, focus included
# --------------------------------------------------------------------------- #

_SUPPRESSED_DIGEST = (
    "Sheet F-D-01-1 - Fire Protection - Plan\n\n"
    "**Coordination / cross-discipline items**\n"
    "- No cross-discipline items noted for this sheet.\n"
    "- None noted.\n"
    "- Penetration at grid C-4 must be sleeved by structural.\n\n"
    "**Conflicts / discrepancies**\n"
    "- No conflicts noted on this sheet.\n\n"
    "**Focus findings**\n"
    "- None noted.\n"
    "- Room 120 has two floor sinks near the east wall.\n"
)
_NOTHING_RELEVANT_DIGEST = (
    "Sheet F-D-01-1 - Fire Protection - Plan\n\n"
    "**Focus findings**\n"
    "Nothing relevant to the focus on this sheet.\n"
)
_ASSURANCES = (
    "No conflicts were found between F-D-01-1 and F-A-01-1. "
    "The sheets are consistent; no conflicts were identified at this time."
)


def _suppressed_run(*, focus):
    return harvest_prose(
        Ledger(),
        [_Digest(_SUPPRESSED_DIGEST, page=0), _Digest(_NOTHING_RELEVANT_DIGEST, page=1)],
        [_geom(0), _geom(1)], client=None, synthesis_text=_ASSURANCES,
        focus_findings_to_markups=focus, sleep=_no_sleep,
    )


@pytest.mark.parametrize("focus", [False, True], ids=["focus-off", "focus-on"])
def test_suppressed_items_are_counted_per_channel(focus):
    res = _suppressed_run(focus=focus)
    acc = res.accounting()

    assert acc["filtered"] == 3                   # digest lines only, as before
    assert acc["assurances"] == 2
    assert acc["filtered_focus"] == 2             # "None noted." + a "nothing relevant" body
    table = acc["by_channel"]
    assert table["digest_prose_coordination"]["suppressed"] == 2
    assert table["digest_prose_conflict"]["suppressed"] == 1
    assert table["focus_prose"]["suppressed"] == 2
    assert table["synthesis_prose"]["suppressed"] == 2
    if focus:
        assert acc["excluded_focus"] == 0
        assert table["focus_prose"]["degraded"] == 1
    else:
        assert acc["excluded_focus"] == 1
        assert table["focus_prose"]["degraded"] == 0


def test_count_filtered_focus_lines_matches_the_extractor():
    from drawing_analyzer.prose_harvest import count_filtered_focus_lines, extract_focus_items

    assert count_filtered_focus_lines(_SUPPRESSED_DIGEST) == 1
    assert extract_focus_items(_SUPPRESSED_DIGEST) == [
        "Room 120 has two floor sinks near the east wall."
    ]
    assert count_filtered_focus_lines(_NOTHING_RELEVANT_DIGEST) == 1
    assert extract_focus_items(_NOTHING_RELEVANT_DIGEST) == []
    # Coordination filler is not focus filler.
    assert count_filtered_focus_lines("**Coordination**\n- None noted.") == 0


def test_the_channel_table_adds_up():
    res, _ledger = _five_item_run(synthesis=G.SET_LEVEL_CONFLICT_SENTENCE)
    acc = res.accounting()
    table = acc["by_channel"]

    for row in table.values():
        assert set(row) == set(_OUTCOME_WORDS) | {"suppressed"}
    for word in _OUTCOME_WORDS:
        assert sum(row[word] for row in table.values()) == acc[word]
    assert list(table) == sorted(table)
    assert table["digest_prose_coordination"] == {
        "matched": 2, "structured": 1, "degraded": 0, "set_level": 0, "missing": 0,
        "suppressed": 0,
    }
    assert table["digest_prose_conflict"] == {
        "matched": 1, "structured": 1, "degraded": 0, "set_level": 0, "missing": 0,
        "suppressed": 0,
    }
    assert table["synthesis_prose"]["set_level"] == 1


def test_the_new_counts_are_observational():
    result = HarvestResult()
    result.vetoed = 3
    result.folded = 2
    result.filtered_focus = 4
    assert result.missing == 0 and result.complete is True
    acc = result.accounting()
    assert (acc["vetoed"], acc["folded"], acc["filtered_focus"]) == (3, 2, 4)
    assert acc["complete"] is True
    assert acc["by_channel"] == {}


def test_parallel_and_sequential_record_the_same_outcomes():
    # The same two pages as the chain test: the outcome records (refusals
    # included) do not depend on which path ran.
    digests = [_coordination(_PAGE_ITEMS[0], page=0), _coordination(_PAGE_ITEMS[1], page=1)]
    geoms = [_geom(0), _geom(1)]
    parallel = harvest_prose(_two_page_ledger(), digests, geoms,
                             client=_TwoPageClient(barrier=threading.Barrier(2)),
                             max_workers=2, sleep=_no_sleep)
    sequential = harvest_prose(_two_page_ledger(), digests, geoms, client=_TwoPageClient(),
                               max_workers=1, sleep=_no_sleep)

    assert parallel.outcomes == sequential.outcomes
    assert [(o.outcome, o.refused, o.call) for o in parallel.outcomes.values()] == [
        ("structured", 1, "live"), ("structured", 1, "live"),
    ]
    assert parallel.vetoed == sequential.vetoed == 2


# --------------------------------------------------------------------------- #
# The record reaches run.log and run_manifest.json
# --------------------------------------------------------------------------- #


class _LogCtx:
    qc_status = "COMPLETE"
    coverage_status = "NOT_REQUESTED"
    sheet_count = 1
    errors: list = []
    sheets: list = []


def _prose_section(text):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Prose carry-through"))
    body = []
    for line in lines[start + 2:]:
        if not line.strip():
            break
        body.append(line)
    return "\n".join(body)


def test_run_log_renders_the_channel_table_readably():
    from drawing_analyzer.run_journal import render_run_log

    res, _ledger = _five_item_run(synthesis=G.SET_LEVEL_CONFLICT_SENTENCE)
    ctx = _LogCtx()
    ctx.prose_accounting = res.accounting()
    section = _prose_section(render_run_log(ctx))

    assert "vetoed 0" in section and "folded 0" in section
    assert "filtered_focus 0" in section
    assert "digest coordination: matched 2 · structured 1" in section
    assert "digest conflict: matched 1 · structured 1" in section
    assert "synthesis: set level 1" in section
    assert "{" not in section and "by_channel" not in section


@pytest.mark.parametrize(
    "table", ["garbage", {"digest_prose_coordination": "x"},
              {"digest_prose_conflict": {"matched": object()}}],
    ids=["not-a-dict", "row-not-a-dict", "unformattable-count"],
)
def test_a_malformed_channel_table_never_sinks_the_log(table):
    from drawing_analyzer.run_journal import render_run_log

    ctx = _LogCtx()
    ctx.prose_accounting = {"items": 2, "matched": 1, "by_channel": table}
    text = render_run_log(ctx)
    assert "Drawing Analyzer" in text and "Final status:" in text
    assert "items 2" in text


# --------------------------------------------------------------------------- #
# Caches: the veto moves no key
# --------------------------------------------------------------------------- #


class _RecordingCache:
    def __init__(self):
        self.store: dict[str, object] = {}
        self.keys: list[str] = []

    def get(self, key):
        self.keys.append(key)
        return self.store.get(key)

    def put(self, key, entry):
        self.store[key] = entry


def test_a_refused_item_keys_its_structuring_call_like_any_straggler():
    from drawing_analyzer.prose_harvest import _HARVEST_CACHE_CONTRACT

    assert _HARVEST_CACHE_CONTRACT == 1
    refused_cache, plain_cache = _RecordingCache(), _RecordingCache()
    ledger = Ledger()
    ledger.add([_f("Provide 6 inch drain at column line 4.", cat="coordination")],
               "digest_json")
    harvest_prose(ledger, [_coordination(_FOUR_INCH)], [_geom()],
                  client=_structuring_client([_finding_block(_FOUR_INCH)]),
                  cache=refused_cache, sleep=_no_sleep)
    harvest_prose(Ledger(), [_coordination(_FOUR_INCH)], [_geom()],
                  client=_structuring_client([_finding_block(_FOUR_INCH)]),
                  cache=plain_cache, sleep=_no_sleep)

    assert len(refused_cache.keys) == 1
    assert refused_cache.keys == plain_cache.keys


# --------------------------------------------------------------------------- #
# End to end
# --------------------------------------------------------------------------- #

_PIPELINE_DIGEST = (
    "Sheet M-101 - Fire Protection - Plan\nEquipment schedule shown.\n\n"
    "**Coordination / cross-discipline items**\n"
    f"- {_FOUR_INCH}\n\n"
)


def _pipeline_client():
    from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT
    from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT
    from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT

    finding = {
        "sheet_id": "M-101", "category": "coordination", "severity": "medium",
        "text": "Provide 6 inch drain at column line 4.",
        "source_quote": "EQUIPMENT SCHEDULE - SEE PLAN", "tile_label": "r1c1", "refs": [],
    }
    digest_text = (_PIPELINE_DIGEST + "```json\n" + json.dumps({"findings": [finding]})
                   + "\n```")
    critique_text = "```json\n" + json.dumps({"findings": [], "claims": []}) + "\n```"

    class _Client(BetaClientMixin):
        def __init__(self):
            self.harvest_calls = 0
            outer = self

            class _Msgs(StreamingMessagesMixin):
                def create(_self, **kw):  # noqa: ANN001, ANN202
                    system = kw.get("system", "")
                    if isinstance(system, list):
                        system = "".join(b.get("text", "") for b in system)
                    if system == HARVEST_SYSTEM_PROMPT:
                        outer.harvest_calls += 1
                        return FakeMessage(
                            content=[FakeTextBlock(text=_finding_block(_FOUR_INCH))],
                            usage=FakeUsage(input_tokens=90, output_tokens=30))
                    if system == VERIFY_SYSTEM_PROMPT:
                        return FakeMessage(
                            content=[FakeTextBlock(text='{"verdict":"CONFIRMED","note":"x"}')],
                            usage=FakeUsage(input_tokens=40, output_tokens=8))
                    if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                        return FakeMessage(content=[FakeTextBlock(text=critique_text)],
                                           usage=FakeUsage(input_tokens=500, output_tokens=80))
                    if system.startswith(DIGEST_SYSTEM_PROMPT):
                        return FakeMessage(content=[FakeTextBlock(text=digest_text)],
                                           usage=FakeUsage(input_tokens=500, output_tokens=80))
                    return FakeMessage(content=[FakeTextBlock(text="ok")])

            self.messages = _Msgs()

    return _Client()


def test_pipeline_a_distinct_prose_claim_is_its_own_finding(tmp_path):
    pytest.importorskip("pymupdf")
    from drawing_analyzer.export import write_drawing_export
    from drawing_analyzer.pipeline import extract_drawing_context
    from tests.test_drawing_qc_pipeline import _make_clean_pdf

    src = _make_clean_pdf(tmp_path / "M-101.pdf", "M-101")
    client = _pipeline_client()
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, reference_audit=True, qc_markups=True,
        markup_verified_only=False, qc_work_dir=tmp_path / "qc",
    )

    assert client.harvest_calls == 1
    texts = sorted(f.text for f in ctx.all_findings if f.source_id)
    assert "Provide 6 inch drain at column line 4." in texts
    assert _FOUR_INCH in texts
    six = next(f for f in ctx.all_findings if f.text.startswith("Provide 6 inch"))
    four = next(f for f in ctx.all_findings if f.text == _FOUR_INCH)
    assert six.prose_item_ids == [] and "digest_prose_coordination" not in six.sources
    assert four.sources == ["digest_prose_coordination"] and four.qc_id != six.qc_id
    acc = ctx.prose_accounting
    assert (acc["items"], acc["matched"], acc["structured"], acc["vetoed"]) == (1, 0, 1, 1)
    (stage,) = [s for s in ctx.stage_results if s.stage == "prose_harvest"]
    assert stage.status == "COMPLETE"

    folder = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101.pdf"])
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["prose_accounting"] == json.loads(json.dumps(acc))
    assert manifest["prose_accounting"]["by_channel"]["digest_prose_coordination"][
        "structured"] == 1
    log = (folder / "run.log").read_text(encoding="utf-8")
    assert "vetoed 1" in log
    assert "digest coordination: structured 1" in log


def test_bounded_work_only_candidates_are_signed(monkeypatch):
    # Plan section 2 rule 14: the common path pays nothing for the veto. An
    # entry below the threshold is never signed.
    import drawing_analyzer.prose_harvest as PH

    signed = []
    real = PH._veto_axes

    def _counting(item, entry, also_on=()):
        signed.append(entry.text)
        return real(item, entry, also_on)

    monkeypatch.setattr(PH, "_veto_axes", _counting)
    entries = [_entry(f"Unrelated sprinkler note number {i} for the east wing.")
               for i in range(200)]
    entries.append(_entry("Provide 6 inch drain at column line 4."))
    start = time.perf_counter()
    assert PH._match_entry(_FOUR_INCH, entries) is None
    assert signed == ["Provide 6 inch drain at column line 4."]
    assert time.perf_counter() - start < 2.0


def test_the_matched_items_path_leaves_the_entry_as_it_was():
    # A restatement adds provenance and nothing else (unchanged behaviour).
    ledger = Ledger()
    kept = _f("Provide 6 inch drain at column line 4.", cat="coordination",
              quote="6 INCH DRAIN")
    ledger.add([kept], "digest_json")
    before = kept.to_dict()

    res = harvest_prose(ledger, [_coordination("6 inch drain required at column line 4.")],
                        [_geom()], client=None, sleep=_no_sleep)

    after = kept.to_dict()
    assert res.matched == 1
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {"sources", "prose_item_ids"}

