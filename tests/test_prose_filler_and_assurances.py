"""Remediation WP-09.1 (B11, N11): section filler never becomes a finding or a
paid call, and a synthesis assurance never becomes a conflict.

The owner's rules (2026-09-24, measured first; ``_plans/PROGRESS.md``):

1. **Filler is a closed vocabulary.** A prose item is dropped as section
   boilerplate only when the WHOLE item is listed words: ``none`` / ``n/a`` /
   ``nothing [further]`` / ``no`` + up to two listed modifiers + a listed noun,
   an optional listed label (``Coordination items:``), then up to four listed
   qualifiers in any order. An unlisted word (a tag, a number, a content noun)
   keeps the item. ``_split_items`` stays the one filter site, so a dropped item
   reaches neither the structuring call nor the degraded entry.
2. **One vocabulary, two forms.** The same word lists build the whole-item
   test and the synthesis assurance spans.
3. **A synthesis statement is an assurance** only when every conflict signal
   it carries sits inside an assurance span and it carries no contrast word
   (``but``, ``however``, ``except``, ``other than`` ...). The conflict noun must
   be the head: ``no conflict resolution is shown`` is not an assurance.
4. **Synthesis items are split per section** (the report's
   ``split_into_sections``), so a header never joins an item.
5. **A dropped assurance is counted** in ``HarvestResult.assurances``,
   observationally (it feeds neither ``missing`` nor ``complete``); B11 filler
   counts in ``filtered`` as before.
6. **Ordinals count the kept items**: filtering an item before a real one moves
   that item's ``prose_item_id`` once. No cache key holds one.
"""
from __future__ import annotations

import json
import time

import pytest

from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import compute_prose_item_id
from drawing_analyzer.prose_harvest import (
    HARVEST_SYSTEM_PROMPT,
    HarvestResult,
    _enumerate_pending,
    count_filtered_prose_lines,
    extract_focus_items,
    extract_prose_items,
    extract_set_level_synthesis_conflicts,
    extract_synthesis_conflicts,
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
    _REAL_FINDINGS_THAT_OPEN_LIKE_BOILERPLATE,
    _TERSE_REAL_FINDINGS,
    _Digest,
    _finding_block,
    _Geom,
    _titleblock_word,
)

# --------------------------------------------------------------------------- #
# The corpora
# --------------------------------------------------------------------------- #

# The review's four strings (B11): each passed the old filter.
_B11 = [
    "No conflicts noted on this sheet.",
    "No conflicts identified at this time.",
    "None apparent on this sheet.",
    "No cross-discipline items noted for this sheet.",
]

# Equivalent wording, cross-discipline included (plan WP-09 step 1).
_EQUIVALENT = [
    "No cross-discipline conflicts noted.",
    "No cross discipline items noted.",
    "No cross\u2013discipline items noted for this sheet.",
    "No coordination items identified on this sheet.",
    "No cross-discipline coordination items noted for this sheet.",
    "No interdisciplinary conflicts were identified.",
    "No coordination issues with other disciplines noted.",
    "None identified for this sheet.",
    "No other issues noted at this time.",
    "Nothing further to report.",
    "No cross-sheet conflicts were found on this sheet.",
    "No conflicts with the architectural drawings noted.",
    "No conflicts or discrepancies noted.",
    "No conflicts were noted on this sheet.",
    "None noted at this time.",
    "No new conflicts identified.",
    "Conflicts: none noted.",
    "**Coordination items:** None.",
    "Cross-sheet / cross-discipline conflicts: None noted.",
    "No conflicts remain.",
    "No conflicts could be identified on this sheet.",
]

# Real findings that carry no/not/none/without/nothing somewhere (the plan's
# "No isolation valve is shown" first). Every one must survive the filter.
_NEGATION_FINDINGS = [
    "No isolation valve is shown.",
    "No isolation valve is shown on the fire pump discharge.",
    "No drain is shown at the low point of the dry pipe system.",
    "No access panel is provided for the fire damper above the ceiling.",
    "No sleeve is detailed where the 6 inch main penetrates the rated wall.",
    "No FDC location is indicated on the site plan.",
    "No seismic bracing is shown for the 4 inch cross main.",
    "No inspector's test connection is shown.",
    "No clearance is dimensioned between the sprinkler deflector and the duct.",
    "No conflict resolution is shown for the pump flow on M-101.",
    "No notes address the required 1-hour rating of the shaft.",
    "No findings from the review were incorporated.",
    "No issues with the pump; verify the jockey pump controller voltage on E-201.",
    "No items noted except the relocated riser at grid 5.",
    "None noted; however, the FP riser at grid 5 conflicts with the duct.",
    "Sprinkler heads are not shown under the 48 inch duct.",
    "The riser is not coordinated with the structural beam at grid C-4.",
    "Duct runs without a fire damper at the rated corridor wall.",
    "The pump schedule lists none of the required jockey pump data.",
    "Hangers are shown without seismic restraint.",
    "The drain valve does not match the size shown in the riser diagram.",
    "The FDC doesn't match the civil plan location.",
    "Nothing indicates the design density for the storage area.",
    "None of the standpipes show pressure-reducing valves.",
    "There is no fire alarm connection shown for the flow switch.",
    "VAV-3 has no clearance.",
    "No drain shown",
    "No FDC shown",
    "No P-1 issues noted.",
    "No sprinkler items noted on this sheet.",
    "No fire-rated items noted on this sheet.",
    "No conflicts noted with the 6 inch main on M-101.",
    "No other coordination required beyond the sleeve at grid C-4.",
]

# Filler-like wording the closed vocabulary does not list: kept, a
# structuring call as before (the safe direction; plan section 2.1).
_FILLER_KEPT_AS_BEFORE = [
    "No duct conflicts noted.",
    "No items requiring coordination.",
    "No coordination required.",
    "No action required.",
    "No conflicts noted on this sheet or with other disciplines.",
]

_MUST_KEEP = (
    _NEGATION_FINDINGS
    + list(_REAL_FINDINGS_THAT_OPEN_LIKE_BOILERPLATE)
    + list(_TERSE_REAL_FINDINGS)
    + [G.PROSE_MATCHED, G.PROSE_STRUCTURED, G.PROSE_DEGRADED]
)

# N11: the review's two synthesis sentences.
_N11 = [
    "No conflicts were found between M-101 and P-101.",
    "The mechanical and plumbing sheets are consistent; no conflicts were "
    "identified at this time.",
]

# Equivalent synthesis assurances the rule drops.
_ASSURANCES = [
    "There are no conflicts between M-101 and P-101.",
    "No conflicts between M-101 and P-101 were found.",
    "No conflicts between the fire protection and mechanical sheets were identified.",
    "Review of M-101 and P-101 found no conflicts.",
    "Nothing inconsistent was found between M-101 and P-101.",
    "No discrepancies noted between M-101 and P-101.",
    "No mismatches were found between the schedules on M-101 and P-101.",
    "No conflicts exist between M-101 and P-101.",
    "No conflicts remain between M-101 and P-101.",
    "**Cross-sheet conflicts:** No conflicts were found between M-101 and P-101.",
    "**Cross-sheet conflicts:** None identified.",
    "No cross-sheet conflicts were identified.",
    "No conflicts noted on this sheet.",
    "No conflicts could be identified between M-101 and P-101.",
]

# Real synthesis conflicts that carry a "no", a negated verb or an
# assurance beside the conflict. Every one must still be extracted.
_SYNTHESIS_CONFLICTS = [
    G.SET_LEVEL_CONFLICT_SENTENCE,
    "No conflicts were resolved between M-101 and FP-101; both remain open",
    "The pump flow on M-101 conflicts with P-101; no other conflicts were found.",
    "The pump schedule on M-101 does not match P-101.",
    "The FDC on FP-101 doesn't match the civil plan.",
    "No conflict resolution is shown for the pump flow on M-101 and P-101.",
    "No conflicts were found by the prior review, but M-101 and P-101 still "
    "disagree on the pump flow.",
    "No conflicts between M-101 and P-101 were resolved.",
    "No conflicts were found, but M-101 shows 500 gpm and P-101 shows 550 gpm.",
    "There is no conflict between M-101 and P-101 other than the pump flow.",
    "No conflicts identified, though M-101 lists 500 gpm and P-101 lists 550 gpm.",
    "The pump on M-101 does not conflict with P-101, but the valve does.",
    "The pump on M-101 does not conflict with P-101; the valve on E-201 does.",
    "No conflicts between M-101 and P-101 were resolved and conflicts were "
    "noted on E-201.",
    "The pump schedule shows no conflict resolution for M-101 and P-101.",
    "There is no conflict resolution shown for M-101 and P-101.",
    "Conflicts: none of the valves on M-101 match P-101.",
    "**Conflicts:** The pump flow on M-101 is 500 gpm while P-101 shows 550 gpm.",
    "Conflicts: No conflicts were resolved between M-101 and FP-101; both remain open",
    "No conflicts between M-101 and P-101 resolve the pump question and none "
    "were found on E-201.",
    "No conflicts could be resolved between M-101 and P-101.",
]

# Assurance-like wording outside the closed grammar: still a conflict item
# (a paid call, as before). Recorded limits, not goals.
_ASSURANCES_KEPT_AS_BEFORE = [
    "M-101 does not conflict with P-101.",
    "No duct conflicts were found between M-101 and P-101.",
    "Checked M-101 against P-101 for conflicts; none were found.",
    "Previously reported conflicts between M-101 and P-101 were not found in "
    "this revision.",
    "M-101 and P-101 were reviewed for conflicts and none were identified.",
    "No stale references were found on M-101.",
    "No apparent conflicts between M-101 and P-101.",
    "No conflicts shown between M-101 and P-101.",
    "No conflicts between the pump schedule on M-101 and P-101 were found.",
]

_IDS = ["M-101", "P-101", "FP-101", "E-201"]


def _ids(prefix, items):
    return [f"{prefix}{i:02d}" for i in range(len(items))]


def _extracted(sentence):
    return (extract_synthesis_conflicts(sentence, _IDS)
            + [(s, []) for s in extract_set_level_synthesis_conflicts(sentence, _IDS)])


class _CountingClient(BetaClientMixin):
    """A structuring client that counts calls and returns one finding each."""

    def __init__(self, *, fail=False):
        self.calls: list[str] = []
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.calls.append(kw["messages"][0]["content"])
                if fail:
                    raise RuntimeError("structuring call failed")
                return FakeMessage(
                    content=[FakeTextBlock(text=_finding_block("structured item"))],
                    usage=FakeUsage(input_tokens=90, output_tokens=30),
                )

        self.messages = _Msgs()


# --------------------------------------------------------------------------- #
# B11: filler is dropped before the structuring call and the degraded entry
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("item", _B11, ids=_ids("b11-", _B11))
def test_b11_review_strings_are_filler(item):
    assert extract_prose_items(f"**Coordination**\n- {item}") == []
    assert count_filtered_prose_lines(f"**Coordination**\n- {item}") == 1


@pytest.mark.parametrize("item", _EQUIVALENT, ids=_ids("eq-", _EQUIVALENT))
def test_b11_equivalent_wording_is_filler(item):
    assert extract_prose_items(f"**Conflicts / discrepancies**\n- {item}") == []


@pytest.mark.parametrize("item", _MUST_KEEP, ids=_ids("keep-", _MUST_KEEP))
def test_real_findings_survive_the_filter(item):
    items = extract_prose_items(f"**Coordination**\n- {item}")
    assert [i for _tag, i in items] == [item]


@pytest.mark.parametrize("item", _FILLER_KEPT_AS_BEFORE,
                         ids=_ids("limit-", _FILLER_KEPT_AS_BEFORE))
def test_recorded_limit_unlisted_filler_is_kept(item):
    items = extract_prose_items(f"**Coordination**\n- {item}")
    assert [i for _tag, i in items] == [item]


def test_the_new_filter_drops_everything_the_old_one_did():
    # Built from the old grammar's own words: every item it dropped, the new
    # one drops too, so no filler comes back as a finding.
    subjects = ["none", "n/a", "na", "nothing"] + [
        f"no {noun}" for noun in (
            "conflict", "conflicts", "issue", "issues", "item", "items",
            "discrepancy", "discrepancies", "note", "notes", "finding", "findings",
        )
    ]
    qualifiers = ["", " noted", " found", " reported", " identified", " observed",
                  " apparent", " to report", " at this time", " on this sheet"]
    for subject in subjects:
        for qualifier in qualifiers:
            for text in (f"{subject}{qualifier}", f"{subject.capitalize()}{qualifier}."):
                if len(text) < 8:
                    continue
                assert extract_prose_items(f"**Coordination**\n- {text}") == [], text


def _b11_digest():
    return _Digest(
        "**Coordination / cross-discipline items**\n"
        + "".join(f"- {s}\n" for s in _B11)
        + "- Duct riser blocks the corridor door.\n"
    )


def test_b11_filler_creates_no_entry_without_a_client():
    ledger = Ledger()
    res = harvest_prose(ledger, [_b11_digest()], [_Geom()], client=None,
                        sleep=lambda *_: None)
    assert [e.text for e in ledger.entries] == ["Duct riser blocks the corridor door."]
    assert res.items == 1 and res.degraded == 1 and res.missing == 0
    assert res.filtered == 4


def test_b11_filler_makes_no_structuring_call():
    client = _CountingClient()
    ledger = Ledger()
    res = harvest_prose(ledger, [_b11_digest()],
                        [_Geom(words=[_titleblock_word("M-101")])],
                        client=client, sleep=lambda *_: None)
    assert len(client.calls) == res.api_calls == 1
    assert "Duct riser blocks the corridor door." in client.calls[0]
    assert all(s not in client.calls[0] for s in _B11)
    assert res.structured == 1 and len(ledger) == 1


def test_b11_filler_never_degrades_when_the_call_fails():
    client = _CountingClient(fail=True)
    ledger = Ledger()
    res = harvest_prose(ledger, [_b11_digest()], [_Geom()], client=client,
                        max_retries=0, sleep=lambda *_: None)
    assert len(client.calls) == 1
    assert res.degraded == 1
    assert [e.text for e in ledger.entries] == ["Duct riser blocks the corridor door."]


def test_b11_filler_in_a_focus_section_is_not_harvested():
    digest = _Digest("**Focus findings**\n- None apparent on this sheet.\n")
    assert extract_focus_items(digest.text) == []
    on = Ledger()
    res = harvest_prose(on, [digest], [_Geom()], client=None,
                        focus_findings_to_markups=True, sleep=lambda *_: None)
    assert len(on) == 0 and res.items == 0
    off = harvest_prose(Ledger(), [digest], [_Geom()], client=None,
                        sleep=lambda *_: None)
    assert off.excluded_focus == 0


# --------------------------------------------------------------------------- #
# N11: a synthesis assurance is not a conflict
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sentence", _N11, ids=["n11-found", "n11-consistent"])
def test_n11_review_sentences_are_not_conflicts(sentence):
    assert extract_synthesis_conflicts(sentence, _IDS) == []
    assert extract_set_level_synthesis_conflicts(sentence, _IDS) == []


@pytest.mark.parametrize("sentence", _ASSURANCES, ids=_ids("assure-", _ASSURANCES))
def test_n11_equivalent_assurances_are_not_conflicts(sentence):
    assert _extracted(sentence) == []


@pytest.mark.parametrize("sentence", _SYNTHESIS_CONFLICTS,
                         ids=_ids("conflict-", _SYNTHESIS_CONFLICTS))
def test_real_synthesis_conflicts_survive(sentence):
    assert [item for item, _ids_ in _extracted(sentence)] == [sentence]


@pytest.mark.parametrize("sentence", _ASSURANCES_KEPT_AS_BEFORE,
                         ids=_ids("limit-", _ASSURANCES_KEPT_AS_BEFORE))
def test_recorded_limit_unlisted_assurances_stay_conflicts(sentence):
    assert [item for item, _ids_ in _extracted(sentence)] == [sentence]


def test_a_label_line_before_an_assurance():
    # A plain label line (not a Markdown heading) joins the next sentence.
    # Made of listed words, it belongs to the assurance after it; with any
    # other word (a sheet id) it keeps the statement a conflict, as before.
    assert _extracted(
        "Cross-sheet conflicts:\nNo conflicts were found between M-101 and P-101."
    ) == []
    assert [item for item, _ids_ in _extracted("Conflicts on M-101:\nNone identified.")] == [
        "Conflicts on M-101: None identified."
    ]


def test_the_must_survive_sentences_keep_their_anchors():
    assert extract_synthesis_conflicts(
        "No conflicts were resolved between M-101 and FP-101; both remain open", _IDS,
    ) == [("No conflicts were resolved between M-101 and FP-101; both remain open",
           ["M-101", "FP-101"])]
    assert extract_set_level_synthesis_conflicts(G.SYNTHESIS_TEXT, _IDS) == [
        G.SET_LEVEL_CONFLICT_SENTENCE
    ]
    assert extract_synthesis_conflicts(G.SYNTHESIS_TEXT, _IDS) == []


def _two_sheet_geoms():
    return [
        _Geom("m.pdf", 0, words=[_titleblock_word("M-101")]),
        _Geom("p.pdf", 0, words=[_titleblock_word("P-101")]),
    ]


def test_n11_assurances_make_no_call_and_no_entry():
    client = _CountingClient()
    ledger = Ledger()
    res = harvest_prose(ledger, [], _two_sheet_geoms(), client=client,
                        synthesis_text=" ".join(_N11), sleep=lambda *_: None)
    assert client.calls == [] and res.api_calls == 0
    assert len(ledger) == 0
    assert res.items == 0 and res.set_level == 0 and res.degraded == 0


def test_n11_a_real_conflict_beside_an_assurance_is_still_harvested():
    ledger = Ledger()
    synthesis = (
        "No conflicts were found between M-101 and P-101. "
        "The riser on M-101 contradicts the plumbing riser on P-101."
    )
    res = harvest_prose(ledger, [], _two_sheet_geoms(), client=None,
                        synthesis_text=synthesis, sleep=lambda *_: None)
    assert res.items == 1 and len(ledger) == 1
    entry = ledger.entries[0]
    assert entry.text == "The riser on M-101 contradicts the plumbing riser on P-101."
    assert [leg.sheet_id for leg in entry.also_on] == ["P-101"]


def test_gauntlet_synthesis_is_unchanged():
    ledger = Ledger()
    res = harvest_prose(ledger, [], [_Geom()], client=None,
                        synthesis_text=G.SYNTHESIS_TEXT, sleep=lambda *_: None)
    assert res.set_level == 1 and len(ledger) == 1
    assert ledger.entries[0].text == G.SET_LEVEL_CONFLICT_SENTENCE


# --------------------------------------------------------------------------- #
# Section headers never join a synthesis item
# --------------------------------------------------------------------------- #

_GLUED_BULLET = (
    "**Systems spanning sheets**\n"
    "- Chilled water from M-101 continues on P-101.\n"
    "**Cross-sheet / cross-discipline conflicts**\n"
    "- No conflicts were found between M-101 and P-101.\n"
)
_HASH_PARAGRAPHS = (
    "### Systems spanning sheets\n"
    "Chilled water from M-101 continues on P-101.\n\n"
    "### Cross-sheet conflicts\n"
    "No conflicts were found between M-101 and P-101.\n"
)
_BOLD_PARAGRAPHS = (
    "**Systems spanning sheets**\n"
    "Chilled water from M-101 continues on P-101.\n\n"
    "**Cross-sheet / cross-discipline conflicts**\n"
    "No conflicts were found between M-101 and P-101.\n"
)


@pytest.mark.parametrize(
    "text", [_GLUED_BULLET, _HASH_PARAGRAPHS, _BOLD_PARAGRAPHS],
    ids=["glued-bullet", "hash-paragraphs", "bold-paragraphs"],
)
def test_a_section_header_never_joins_a_synthesis_item(text):
    assert extract_synthesis_conflicts(text, _IDS) == []
    assert extract_set_level_synthesis_conflicts(text, _IDS) == []


def test_a_real_conflict_under_a_header_is_extracted_alone():
    text = (
        "### Cross-sheet conflicts\n"
        "The pump flow on M-101 conflicts with P-101.\n"
        "### Set-wide scope\n"
        "Mechanical M-101; plumbing P-101.\n"
    )
    assert extract_synthesis_conflicts(text, _IDS) == [
        ("The pump flow on M-101 conflicts with P-101.", ["M-101", "P-101"])
    ]


# --------------------------------------------------------------------------- #
# Counting: observational, like ``filtered``
# --------------------------------------------------------------------------- #


def test_a_dropped_assurance_is_counted_observationally():
    from drawing_analyzer.prose_harvest import count_synthesis_assurances

    ledger = Ledger()
    synthesis = (
        "Overall the set is coherent.\n\n"
        "- No conflicts were found between M-101 and P-101.\n"
        "- No conflicts noted.\n"
        "- The mechanical and plumbing sheets are consistent; no conflicts were "
        "identified at this time.\n"
        "- The riser on M-101 contradicts the plumbing riser on P-101.\n"
    )
    # Two assurances and one boilerplate line with a conflict signal. The
    # opening sentence carries no signal and the real conflict is harvested,
    # so neither is counted.
    assert count_synthesis_assurances(synthesis) == 3
    res = harvest_prose(ledger, [], _two_sheet_geoms(), client=None,
                        synthesis_text=synthesis, sleep=lambda *_: None)
    assert res.assurances == 3
    assert res.items == 1 and res.missing == 0 and res.complete is True
    assert res.filtered == 0                    # digest lines only
    assert res.accounting()["assurances"] == 3


def test_the_assurance_count_does_not_feed_completeness():
    result = HarvestResult()
    result.assurances = 4
    assert result.missing == 0 and result.complete is True
    assert result.accounting()["assurances"] == 4


def test_filler_counts_in_filtered_and_not_in_assurances():
    res = harvest_prose(Ledger(), [_b11_digest()], [_Geom()], client=None,
                        sleep=lambda *_: None)
    assert res.filtered == 4
    assert res.assurances == 0


# --------------------------------------------------------------------------- #
# Ordinals: the survivor's id moves once; no cache key holds an id
# --------------------------------------------------------------------------- #


def test_the_survivors_ordinal_moves_once():
    digest = _Digest(
        "**Coordination items**\n"
        "- No conflicts noted on this sheet.\n"
        "- Duct riser blocks the corridor door.\n"
    )
    pending = _enumerate_pending(
        [digest], "", {}, focus_findings_to_markups=False,
        sheet_text_of=lambda ref: "", display_id_of=lambda ref: "M-101",
        result=HarvestResult(),
    )
    (p,) = pending
    item = "Duct riser blocks the corridor door."
    tag = "digest_prose_coordination"
    assert p.item.ordinal == 0
    assert p.pid == compute_prose_item_id(tag, p.ref.source_id, tag, 0, item,
                                          page_index=p.ref.page_index)
    # The id the item had while the filler was still kept (ordinal 1).
    assert p.pid != compute_prose_item_id(tag, p.ref.source_id, tag, 1, item,
                                          page_index=p.ref.page_index)


def test_a_synthesis_conflicts_ordinal_counts_kept_items():
    geoms = _two_sheet_geoms()
    id_map = {"M-101": geoms[0], "P-101": geoms[1]}
    synthesis = (
        "No conflicts were found between M-101 and P-101. "
        "The riser on M-101 contradicts the plumbing riser on P-101."
    )
    pending = _enumerate_pending(
        [], synthesis, id_map, focus_findings_to_markups=False,
        sheet_text_of=lambda ref: "", display_id_of=lambda ref: "M-101",
        result=HarvestResult(),
    )
    (p,) = pending
    assert p.item.ordinal == 0
    assert p.item.verbatim_text == (
        "The riser on M-101 contradicts the plumbing riser on P-101."
    )


class _RecordingCache:
    def __init__(self):
        self.store: dict[str, object] = {}
        self.keys: list[str] = []

    def get(self, key):
        self.keys.append(key)
        return self.store.get(key)

    def put(self, key, entry):
        self.store[key] = entry


def test_no_structuring_cache_key_holds_a_prose_item_id():
    # The survivor keeps its structuring cache key when filler before it is
    # dropped, so no stored structuring result is re-billed and
    # _HARVEST_CACHE_CONTRACT does not move.
    item = "Duct riser blocks the corridor door."
    keys = []
    for body in (f"- {item}\n", f"- No isolation valve is shown.\n- {item}\n"):
        cache = _RecordingCache()
        harvest_prose(Ledger(), [_Digest(f"**Coordination items**\n{body}")],
                      [_Geom(sheet_text="DUCT RISER")], client=_CountingClient(),
                      cache=cache, sleep=lambda *_: None)
        keys.append(cache.keys[-1])
    assert keys[0] == keys[1]


# --------------------------------------------------------------------------- #
# One vocabulary: the assurance nouns follow the conflict signals
# --------------------------------------------------------------------------- #


def test_every_noun_signal_has_an_assurance_noun():
    from drawing_analyzer.prose_harvest import _CONFLICT_SIGNALS

    nouns = {
        "conflict": "conflicts", "contradic": "contradictions",
        "disagree": "disagreements", "mismatch": "mismatches",
        "discrepan": "discrepancies", "inconsist": "inconsistencies",
        "diverg": "divergences",
    }
    verb_only = {"differs", "does not match", "doesn't match", "stale"}
    assert set(_CONFLICT_SIGNALS) == set(nouns) | verb_only
    for stem, noun in nouns.items():
        sentence = f"No {noun} were found between M-101 and P-101."
        assert _extracted(sentence) == [], stem


def test_every_assurance_noun_carries_a_signal():
    import re

    from drawing_analyzer.prose_harvest import _CONFLICT_NOUNS, _CONFLICT_SIGNALS

    words = [
        "conflict", "conflicts", "contradiction", "contradictions",
        "disagreement", "disagreements", "mismatch", "mismatches",
        "discrepancy", "discrepancies", "inconsistency", "inconsistencies",
        "divergence", "divergences",
    ]
    for pattern in _CONFLICT_NOUNS:
        matched = [w for w in words if re.fullmatch(pattern, w)]
        assert matched, pattern
        for word in matched:
            assert any(sig in word for sig in _CONFLICT_SIGNALS), (pattern, word)


# --------------------------------------------------------------------------- #
# Bounded work
# --------------------------------------------------------------------------- #


def test_the_grammar_is_fast_on_long_adversarial_input():
    long_items = [
        "No " + "other " * 20_000 + "conflicts noted x",
        "No conflicts" + " noted" * 20_000 + " x",
        "No conflicts between " + "M-101 and " * 20_000 + "P-101 were found.",
        "no conflicts " * 20_000,
        "Nothing " + "inconsistent " * 20_000,
    ]
    start = time.perf_counter()
    for item in long_items:
        extract_prose_items(f"**Coordination**\n- {item}")
        extract_synthesis_conflicts(item, _IDS)
        extract_set_level_synthesis_conflicts(item, _IDS)
    assert time.perf_counter() - start < 5.0


# --------------------------------------------------------------------------- #
# End to end: no structuring call, no ledger entry, no notes PDF
# --------------------------------------------------------------------------- #

_FILLER_DIGEST = (
    "Sheet - Mechanical - Plan\nEquipment schedule shown.\n\n"
    "**Coordination / cross-discipline items**\n"
    "- No cross-discipline items noted for this sheet.\n\n"
    "**Conflicts / discrepancies**\n"
    "- No conflicts noted on this sheet.\n\n"
)
_ASSURANCE_SYNTHESIS = (
    "**Systems spanning sheets**\n"
    "- Equipment on M-101 continues on M-102.\n"
    "**Cross-sheet / cross-discipline conflicts**\n"
    "- No conflicts were found between M-101 and M-102.\n"
    "- The mechanical sheets are consistent; no conflicts were identified at "
    "this time.\n"
)


def _pipeline_client(synthesis_text):
    from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT
    from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT
    from drawing_analyzer.synthesis import SYNTHESIS_SYSTEM_PROMPT
    from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT

    digest_text = _FILLER_DIGEST + "```json\n" + json.dumps({"findings": []}) + "\n```"
    critique_text = "```json\n" + json.dumps({"findings": [], "claims": []}) + "\n```"

    class _Client(BetaClientMixin):
        def __init__(self):
            self.harvest_calls = 0
            outer = self

            class _Msgs(StreamingMessagesMixin):
                def create(_self, **kw):
                    system = kw.get("system", "")
                    if isinstance(system, list):
                        system = "".join(b.get("text", "") for b in system)
                    if system == HARVEST_SYSTEM_PROMPT:
                        outer.harvest_calls += 1
                        return FakeMessage(content=[FakeTextBlock(text="unparseable")])
                    if system == SYNTHESIS_SYSTEM_PROMPT:
                        return FakeMessage(content=[FakeTextBlock(text=synthesis_text)],
                                           usage=FakeUsage(input_tokens=300, output_tokens=60))
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


def _run(tmp_path, synthesis_text):
    pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context
    from tests.test_drawing_qc_pipeline import _make_clean_pdf

    srcs = [_make_clean_pdf(tmp_path / "M-101.pdf", "M-101"),
            _make_clean_pdf(tmp_path / "M-102.pdf", "M-102")]
    client = _pipeline_client(synthesis_text)
    ctx = extract_drawing_context(
        srcs, client=client, rows=2, cols=2,
        reference_audit=True, qc_markups=True, markup_verified_only=False,
        synthesize=True, qc_work_dir=tmp_path / "qc",
    )
    return ctx, client


def test_pipeline_filler_and_assurances_cost_nothing(tmp_path):
    ctx, client = _run(tmp_path, _ASSURANCE_SYNTHESIS)

    assert client.harvest_calls == 0
    assert not [f for f in ctx.all_findings if "prose" in " ".join(f.sources)]
    assert "Drawing_Set_Review_Notes.pdf" not in {p.name for p in ctx.reviewed_pdf_paths}
    acc = ctx.prose_accounting
    assert acc["items"] == 0 and acc["missing"] == 0
    assert acc["filtered"] == 4            # two filler lines on each of two sheets
    assert acc["assurances"] == 2
    (stage,) = [s for s in ctx.stage_results if s.stage == "prose_harvest"]
    assert stage.status == "SKIPPED_VALID"

    from drawing_analyzer.export import write_drawing_export

    folder = write_drawing_export(ctx, tmp_path / "out",
                                  source_names=["M-101.pdf", "M-102.pdf"])
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["prose_accounting"]["assurances"] == 2
    assert manifest["prose_accounting"]["filtered"] == 4
    assert "assurances 2" in (folder / "run.log").read_text(encoding="utf-8")


def test_pipeline_a_real_set_level_conflict_beside_assurances_is_kept(tmp_path):
    synthesis = _ASSURANCE_SYNTHESIS + f"- {G.SET_LEVEL_CONFLICT_SENTENCE}\n"
    ctx, client = _run(tmp_path, synthesis)

    assert client.harvest_calls == 0
    set_level = [f for f in ctx.all_findings
                 if (f.anchor_hint or "").upper() == "SET_INDEX" and not f.source_id]
    assert [f.text for f in set_level] == [G.SET_LEVEL_CONFLICT_SENTENCE]
    assert "Drawing_Set_Review_Notes.pdf" in {p.name for p in ctx.reviewed_pdf_paths}
    assert ctx.prose_accounting["assurances"] == 2
    assert ctx.prose_accounting["set_level"] == 1
