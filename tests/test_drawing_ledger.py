"""Part III tests: the findings ledger, the prose harvest, and coverage (§16–19).

Pure and hermetic — synthetic findings/digests, a scripted fake client for the
structuring calls, no network, no PyMuPDF (the PDF-facing gating matrix lives in
``test_drawing_markup_rich.py``; the end-to-end coverage assertion in
``test_drawing_qc_pipeline.py``).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from drawing_analyzer.ledger import Ledger, provenance_label
from drawing_analyzer.models import (
    Anchor,
    ConflictLeg,
    Finding,
    SheetRef,
    Verification,
)
from drawing_analyzer.prose_harvest import (
    HarvestResult,
    extract_focus_items,
    extract_prose_items,
    extract_set_level_synthesis_conflicts,
    extract_synthesis_conflicts,
    harvest_prose,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage


def _ref(source="a.pdf", page=0):
    return SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)


def _f(text, *, source="a.pdf", page=0, quote="", sev="medium", cat="code",
       rect=None, status="SKIPPED", tile=None, sources=None, reproduced=True):
    anchor = Anchor(status="EXACT", rect_pdf=list(rect), method="t") if rect else Anchor()
    return Finding(
        sheet_id="S-1", source_name=source, page_index=page, category=cat,
        severity=sev, text=text, source_quote=quote, tile=tile,
        anchor=anchor, verification=Verification(status=status),
        sources=list(sources or []), reproduced=reproduced,
    )


# --------------------------------------------------------------------------- #
# Ledger merge matrix (§16)
# --------------------------------------------------------------------------- #


def test_ledger_merges_duplicates_and_unions_sources():
    ledger = Ledger()
    ledger.add([_f("VAV-3 has no clearance to the wall", quote="VAV-3")], "digest_json")
    # The critique restates the same issue with a longer quote and higher severity.
    dup = _f("VAV-3 has no clearance to the wall", quote="VAV-3 SERVES ROOM 120",
             sev="high", sources=["critique_1", "critique_2"])
    ledger.add([dup])
    assert len(ledger) == 1
    entry = ledger.entries[0]
    assert entry.sources == ["digest_json", "critique_1", "critique_2"]
    assert entry.severity == "high"                       # most severe wins
    assert entry.source_quote == "VAV-3 SERVES ROOM 120"  # longest quote wins
    assert entry.reproduced is True                       # cross-family corroboration


def test_ledger_merge_adopts_auditor_anchor_and_verification():
    ledger = Ledger()
    ledger.add([_f("References X-9; not present in the set", cat="reference",
                   quote="SEE DRAWING X-9")], "digest_json")
    auditor = _f("References X-9; not present in the provided set", cat="reference",
                 quote="SEE DRAWING X-9", rect=[10, 10, 60, 24],
                 status="DETERMINISTIC", sources=["auditor_reference"])
    ledger.add([auditor])
    assert len(ledger) == 1
    entry = ledger.entries[0]
    # The pre-anchored, host-computed member upgrades the model entry.
    assert entry.anchor.rect_pdf == [10, 10, 60, 24]
    assert entry.verification.status == "DETERMINISTIC"
    assert set(entry.sources) == {"digest_json", "auditor_reference"}


def test_ledger_merge_preserves_deterministic_verdict_without_rect():
    # A rect-less auditor duplicate (say an arithmetic mismatch whose quote
    # didn't resolve) must not lose its host-computed verdict to the model
    # member it merges into.
    ledger = Ledger()
    ledger.add([_f("column loads sum to 480 kips, schedule says 470",
                   quote="480 KIPS")], "digest_json")
    ledger.add([_f("column loads sum to 480 kips, schedule says 470",
                   status="DETERMINISTIC", sources=["auditor_arithmetic"])])
    assert len(ledger) == 1
    assert ledger.entries[0].verification.status == "DETERMINISTIC"
    # And the reverse: a later anchored model member contributes its rect but
    # cannot downgrade the deterministic verdict.
    ledger.add([_f("column loads sum to 480 kips, schedule says 470",
                   rect=[10, 10, 60, 24], sources=["critique_1"])])
    assert len(ledger) == 1
    entry = ledger.entries[0]
    assert entry.anchor.rect_pdf == [10, 10, 60, 24]
    assert entry.verification.status == "DETERMINISTIC"


def test_ledger_keeps_distinct_findings_and_cross_sheet_apart():
    ledger = Ledger()
    ledger.add([_f("relief valve set at 165 psi, should be 175")], "digest_json")
    ledger.add([_f("no low-point drain shown on the dry system")], "digest_json")
    # Same text on a DIFFERENT sheet is a different issue.
    ledger.add([_f("relief valve set at 165 psi, should be 175", source="b.pdf")], "cross_qc")
    assert len(ledger) == 3


def test_ledger_merge_preserves_also_on_and_citation():
    leg = ConflictLeg(sheet_id="F-2", source_name="b.pdf", page_index=0)
    a = _f("COLO 5 note contradicts the twin note", quote="COLO 5")
    a.also_on = [leg]
    ledger = Ledger()
    ledger.add([a], "cross_qc")
    ledger.add([_f("COLO 5 note contradicts the twin note", quote="COLO 5")], "digest_json")
    assert len(ledger) == 1
    assert ledger.entries[0].also_on and ledger.entries[0].also_on[0].sheet_id == "F-2"


def test_ledger_freeze_assigns_stable_qc_ids():
    ledger = Ledger()
    ledger.add([
        _f("second", rect=[10, 400, 60, 420]),
        _f("first", rect=[10, 20, 60, 40]),
    ], "digest_json")
    entries = ledger.freeze()
    by_text = {e.text: e.qc_id for e in entries}
    assert by_text == {"first": "QC-001", "second": "QC-002"}
    # Idempotent: a second freeze re-derives the same numbers (I-7).
    ledger.freeze()
    assert {e.text: e.qc_id for e in ledger.entries} == by_text


def test_ledger_post_seal_add_marks_incomplete_not_fatal():
    # A post-seal add is an orchestration invariant failure (§12.3): the entry is
    # kept (I-3) but the run is flagged incomplete — never fabricated a QC-XTRA
    # number that reads like ordinary output.
    ledger = Ledger()
    ledger.add([_f("first", rect=[10, 20, 60, 40])], "digest_json")
    ledger.seal()
    assert ledger.sealed
    ledger.add([_f("straggler after seal")], "digest_json")
    assert len(ledger) == 2                       # the entry is kept
    assert ledger.post_seal_adds == 1             # ...but the invariant failure is recorded
    late = next(e for e in ledger.entries if e.text == "straggler after seal")
    assert not late.qc_id.startswith("QC-XTRA-")  # no fabricated masquerade number
    ledger.number()
    assert ledger.state == "NUMBERED"


def test_provenance_label_compresses_chips():
    assert provenance_label(
        ["digest_prose_conflict", "digest_json", "critique_1", "critique_2"]
    ) == "prose+json+critique×2"
    assert provenance_label(["critique_1"]) == "critique"
    assert provenance_label(["auditor_reference"]) == "auditor"
    assert provenance_label(["synthesis_prose", "cross_qc"]) == "cross+synthesis"
    assert provenance_label([]) == ""


# --------------------------------------------------------------------------- #
# Prose harvest (§17)
# --------------------------------------------------------------------------- #


class _Digest:
    def __init__(self, text, source="a.pdf", page=0):
        self.ref = _ref(source, page)
        self.text = text
        self.error = None


class _Geom:
    def __init__(self, source="a.pdf", page=0, sheet_text="", words=None):
        self.ref = _ref(source, page)
        self.sheet_text = sheet_text
        self.words = list(words or [])
        self.page_width_pt = 3168.0
        self.page_height_pt = 2448.0
        self.rows = 2
        self.cols = 2
        self.overlap_frac = 0.08


def _titleblock_word(sheet_id):
    return (2868.0, 2288.0, 2932.0, 2302.0, sheet_id, 0, 0, 0)


_FIVE_ITEM_DIGEST = """Sheet F-D-01-1 - Fire Protection - Demand

**Coordination / cross-discipline items**
- Penetration at grid C-4 must be sleeved by structural.
- FP riser shares a chase with the plumbing vent; verify the access panel.
- Equipment pad for the fire pump is shown by another discipline.

**Conflicts / discrepancies**
- Note 7 says relief at 175 psi but the schedule row shows 165 psi.
- The riser diagram shows a check valve the plan never draws.
"""


def _structuring_client(reply_texts):
    """Scripted client for the harvest's structuring calls."""

    class _Client:
        def __init__(self):
            self.calls = 0
            outer = self

            class _Msgs:
                def create(self, **kw):  # noqa: ANN001, ANN202
                    i = min(outer.calls, len(reply_texts) - 1)
                    outer.calls += 1
                    return FakeMessage(
                        content=[FakeTextBlock(text=reply_texts[i])],
                        usage=FakeUsage(input_tokens=90, output_tokens=30),
                    )

            self.messages = _Msgs()

    return _Client()


def _finding_block(text, quote=""):
    return "```json\n" + json.dumps({
        "sheet_id": "F-D-01-1", "category": "coordination", "severity": "low",
        "text": text, "source_quote": quote, "tile": None, "refs": [],
    }) + "\n```"


def test_harvest_five_prose_items_three_matched_two_structured():
    # §19's seeded case: the prose lists 5 items while the JSON block carried 3
    # → exactly 2 structuring calls → 5 ledger entries with correct provenance.
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
        client=client, sleep=lambda *_: None,
    )
    assert client.calls == 2                       # only the two stragglers
    assert res.items == 5 and res.matched == 3 and res.structured == 2
    assert res.degraded == 0
    assert len(ledger) == 5
    # Matched entries gained the prose provenance tag alongside digest_json.
    tagged = [e for e in ledger.entries if "digest_json" in e.sources]
    assert len(tagged) == 3
    assert all(
        any(s.startswith("digest_prose_") for s in e.sources) for e in tagged
    )
    # Structured stragglers carry only the prose tag.
    stragglers = [e for e in ledger.entries if "digest_json" not in e.sources]
    assert len(stragglers) == 2
    assert {s for e in stragglers for s in e.sources} <= {
        "digest_prose_coordination", "digest_prose_conflict"
    }


def test_harvest_structuring_failure_degrades_to_sheet_entry():
    # §17's invariant: even a garbled structuring reply produces a ledger entry —
    # the prose item verbatim, sheet-level, reaching the PDF as a margin callout.
    ledger = Ledger()
    client = _structuring_client(["no json here at all"])
    digest = _Digest(
        "**Conflicts**\n- The schedule flow total disagrees with the riser demand values shown."
    )
    res = harvest_prose(ledger, [digest], [_Geom()], client=client, sleep=lambda *_: None)
    assert res.items == 1 and res.degraded == 1
    assert len(ledger) == 1
    entry = ledger.entries[0]
    assert entry.anchor_hint == "SHEET"
    assert entry.sources == ["digest_prose_conflict"]
    assert "schedule flow total disagrees" in entry.text


def test_harvest_warm_item_cache_skips_structuring_call():
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    client = _structuring_client([
        _finding_block("Structured cached coordination item.")
    ])
    digest = _Digest(
        "**Coordination items**\n"
        "- Shared chase clearances must be coordinated with the electrical layout."
    )
    geom = _Geom(words=[_titleblock_word("F-D-01-1")])

    first_ledger = Ledger()
    first = harvest_prose(
        first_ledger, [digest], [geom], client=client, cache=cache,
        sleep=lambda *_: None,
    )
    second_ledger = Ledger()
    second = harvest_prose(
        second_ledger, [digest], [geom], client=client, cache=cache,
        sleep=lambda *_: None,
    )

    assert first.api_calls == 1 and first.cache_misses == 1
    assert second.api_calls == 0 and second.cache_hits == 1
    assert second.input_tokens == 0 and second.output_tokens == 0
    assert client.calls == 1
    assert second_ledger.entries[0].text == first_ledger.entries[0].text


def test_harvest_structuring_overlaps_across_pages_and_ingests_in_item_order():
    barrier = threading.Barrier(2)
    active = 0
    max_active = 0
    lock = threading.Lock()

    class _ParallelClient:
        def __init__(self):
            outer = self

            class _Msgs:
                def create(self, **kw):  # noqa: ANN001, ANN202
                    nonlocal active, max_active
                    user = kw["messages"][0]["content"]
                    first = "First independent" in user
                    with lock:
                        active += 1
                        max_active = max(max_active, active)
                    barrier.wait(timeout=5)
                    if first:
                        time.sleep(0.04)  # complete second item first
                    with lock:
                        active -= 1
                    text = "structured first" if first else "structured second"
                    return FakeMessage(
                        content=[FakeTextBlock(text=_finding_block(text))],
                        usage=FakeUsage(input_tokens=90, output_tokens=30),
                    )

            self.messages = _Msgs()

    first_digest = _Digest(
        "**Coordination items**\n"
        "- First independent coordination issue needs discipline review.",
        page=0,
    )
    second_digest = _Digest(
        "**Coordination items**\n"
        "- Second independent coordination issue needs discipline review.",
        page=1,
    )
    ledger = Ledger()
    result = harvest_prose(
        ledger,
        [first_digest, second_digest],
        [
            _Geom(page=0, words=[_titleblock_word("F-D-01-1")]),
            _Geom(page=1, words=[_titleblock_word("F-D-01-1")]),
        ],
        client=_ParallelClient(), max_workers=2, sleep=lambda *_: None,
    )

    assert max_active == 2 and result.api_calls == 2
    assert [entry.text for entry in ledger.entries] == [
        "structured first", "structured second",
    ]


def test_harvest_same_page_chain_skips_later_duplicate_call():
    first_item = (
        "The fire pump equipment pad shown by structural requires confirmation."
    )
    duplicate_item = (
        "The fire pump equipment pad shown by structural requires coordination."
    )
    client = _structuring_client([_finding_block(duplicate_item)])
    digest = _Digest(
        "**Coordination items**\n"
        f"- {first_item}\n"
        f"- {duplicate_item}"
    )
    ledger = Ledger()

    result = harvest_prose(
        ledger,
        [digest],
        [_Geom(words=[_titleblock_word("F-D-01-1")])],
        client=client,
        max_workers=4,
        sleep=lambda *_: None,
    )

    # The first result makes item 2 a free same-page match. The sequential
    # algorithm makes one request, so concurrency must never speculate a second.
    assert client.calls == result.api_calls == 1
    assert result.structured == 1 and result.matched == 1
    assert len(ledger.entries) == 1
    assert len(ledger.entries[0].prose_item_ids) == 2


def test_harvest_parallel_page_chains_match_sequential_results_and_order():
    page_zero_first = "Page-zero first coordination condition needs review."
    page_zero_duplicate = "Page-zero resulting coordination condition needs review."
    page_one_first = "Page-one first coordination condition needs review."
    page_one_duplicate = "Page-one resulting coordination condition needs review."
    sheets = [
        _Digest(
            "**Coordination items**\n"
            f"- {page_zero_first}\n"
            f"- {page_zero_duplicate}",
            page=0,
        ),
        _Digest(
            "**Coordination items**\n"
            f"- {page_one_first}\n"
            f"- {page_one_duplicate}",
            page=1,
        ),
    ]
    geometries = [
        _Geom(page=0, words=[_titleblock_word("F-D-01-1")]),
        _Geom(page=1, words=[_titleblock_word("F-D-01-1")]),
    ]

    class _PromptClient:
        def __init__(self, *, delay_page_zero=False):
            self.calls: list[str] = []
            self.barrier = threading.Barrier(2) if delay_page_zero else None
            outer = self

            class _Msgs:
                def create(self, **kw):  # noqa: ANN001, ANN202
                    user = kw["messages"][0]["content"]
                    if page_zero_first in user:
                        marker, text = "page-zero", page_zero_duplicate
                    else:
                        marker, text = "page-one", page_one_duplicate
                    if outer.barrier is not None:
                        outer.barrier.wait(timeout=5)
                    if delay_page_zero and marker == "page-zero":
                        time.sleep(0.04)  # page one completes first
                    outer.calls.append(marker)
                    return FakeMessage(
                        content=[FakeTextBlock(text=_finding_block(text))],
                        usage=FakeUsage(input_tokens=90, output_tokens=30),
                    )

            self.messages = _Msgs()

    sequential_ledger = Ledger()
    sequential_client = _PromptClient()
    sequential = harvest_prose(
        sequential_ledger,
        sheets,
        geometries,
        client=sequential_client,
        max_workers=1,
        sleep=lambda *_: None,
    )

    parallel_ledger = Ledger()
    parallel_client = _PromptClient(delay_page_zero=True)
    parallel = harvest_prose(
        parallel_ledger,
        sheets,
        geometries,
        client=parallel_client,
        max_workers=2,
        sleep=lambda *_: None,
    )

    assert parallel == sequential
    assert [entry.to_dict() for entry in parallel_ledger.entries] == [
        entry.to_dict() for entry in sequential_ledger.entries
    ]
    assert sequential_client.calls == ["page-zero", "page-one"]
    assert parallel_client.calls == ["page-one", "page-zero"]
    assert parallel.api_calls == 2  # one necessary request per page, never four


def test_harvest_without_client_still_upholds_the_invariant():
    ledger = Ledger()
    res = harvest_prose(
        ledger,
        [_Digest("**Coordination items**\n- Shared chase with electrical must be coordinated on site.")],
        [], client=None, sleep=lambda *_: None,
    )
    # No client to structure with → straight to the degraded entry.
    assert res.degraded == 1 and len(ledger) == 1


def test_harvest_synthesis_conflict_dual_anchors():
    ledger = Ledger()
    geoms = [
        _Geom("a.pdf", 0, words=[_titleblock_word("F-D-01-1")]),
        _Geom("b.pdf", 0, words=[_titleblock_word("F-A-01-1")]),
    ]
    synthesis = (
        "Overall the set is coherent. The COLO 5 note on F-D-01-1 contradicts "
        "the twin note on F-A-01-1; reconcile before issue."
    )
    res = harvest_prose(
        ledger, [], geoms, client=None, synthesis_text=synthesis, sleep=lambda *_: None,
    )
    assert res.items == 1
    assert len(ledger) == 1
    entry = ledger.entries[0]
    assert entry.sources == ["synthesis_prose"]
    assert entry.source_name == "a.pdf"            # primary = first named sheet
    assert len(entry.also_on) == 1
    assert entry.also_on[0].sheet_id == "F-A-01-1"
    assert entry.also_on[0].source_name == "b.pdf"


def test_focus_items_harvested_only_behind_the_toggle():
    digest = _Digest(
        "**Focus findings**\n- Room 120 has two floor sinks near the east wall area."
    )
    off = Ledger()
    harvest_prose(off, [digest], [_Geom()], client=None, sleep=lambda *_: None)
    assert len(off) == 0                           # default OFF: focus is not QC

    on = Ledger()
    res = harvest_prose(
        on, [digest], [_Geom()], client=None,
        focus_findings_to_markups=True, sleep=lambda *_: None,
    )
    assert res.items == 1 and len(on) == 1
    assert on.entries[0].sources == ["focus_prose"]


def test_extract_helpers_filter_trivia():
    assert extract_prose_items("**Conflicts**\nNone noted.") == []
    assert extract_focus_items(
        "**Focus findings**\nNothing relevant to the focus on this sheet."
    ) == []
    # A conflict statement naming no in-set sheet never surfaces.
    assert extract_synthesis_conflicts(
        "There is a mismatch somewhere in the set.", ["F-D-01-1"]
    ) == []


def test_synthesis_sheet_id_matching_is_boundary_aware():
    ids = ["A-1", "A-10"]
    # A mention of A-10 is NOT a mention of its prefix A-1 — the old substring
    # check made A-1 the primary sheet and A-10 a bogus also_on leg.
    assert extract_synthesis_conflicts(
        "The grid on A-10 conflicts with the foundation plan.", ids
    ) == [("The grid on A-10 conflicts with the foundation plan.", ["A-10"])]
    # When both are genuinely named, order still follows first mention.
    assert extract_synthesis_conflicts(
        "The door on A-1 conflicts with the frame type on A-10.", ids
    ) == [("The door on A-1 conflicts with the frame type on A-10.", ["A-1", "A-10"])]
    # An out-of-set longer id (a detail reference, not a sheet) is not a
    # boundary match for the in-set prefix either.
    assert extract_synthesis_conflicts(
        "Detail A-101 conflicts with the finish schedule.", ["A-1"]
    ) == []
    # Nor is a dotted continuation: naming detail A-1.1 does not name sheet
    # A-1, even when A-1.1 itself is not in the set.
    assert extract_synthesis_conflicts(
        "Section A-1.1 conflicts with the enlarged plan.", ["A-1"]
    ) == []
    # Sentence punctuation is still a boundary — the id itself matches.
    assert extract_synthesis_conflicts(
        "There is a conflict on A-1.", ["A-1"]
    ) == [("There is a conflict on A-1.", ["A-1"])]
    # A slash is a boundary too: "P-1/P-2" names both sheets.
    assert extract_synthesis_conflicts(
        "The riser diagram on P-1/P-2 is inconsistent with the plan.",
        ["P-1", "P-2"],
    ) == [(
        "The riser diagram on P-1/P-2 is inconsistent with the plan.",
        ["P-1", "P-2"],
    )]


# --------------------------------------------------------------------------- #
# Phase 22 — prose-item id reconciliation (§14.6/§14.9) and set-level (§14.8)
# --------------------------------------------------------------------------- #


def test_harvest_reconciles_every_enumerated_item():
    # §14.9: every enumerated prose item must reach a ledger entry — the expected
    # id set equals the accounted id set and nothing is missing.
    ledger = Ledger()
    ledger.add([
        _f("Penetration at grid C-4 must be sleeved by structural", cat="coordination"),
        _f("FP riser shares a chase with the plumbing vent; verify the access panel",
           cat="coordination"),
        _f("Note 7 says relief at 175 psi but the schedule row shows 165 psi", cat="conflict"),
    ], "digest_json")
    client = _structuring_client([
        _finding_block("Fire pump equipment pad is shown by another discipline."),
        _finding_block("Riser diagram shows a check valve the plan never draws."),
    ])
    res = harvest_prose(
        ledger, [_Digest(_FIVE_ITEM_DIGEST)],
        [_Geom(sheet_text="CHECK VALVE AT RISER", words=[_titleblock_word("F-D-01-1")])],
        client=client, sleep=lambda *_: None,
    )
    assert res.items == 5 and res.missing == 0 and res.complete is True
    assert set(res.expected_ids) == set(res.accounted_ids)
    # Every enumerated id is attached to exactly one ledger entry.
    attached = [pid for e in ledger.entries for pid in e.prose_item_ids]
    assert sorted(attached) == sorted(res.expected_ids)


def test_harvest_per_item_failure_is_isolated_and_recovered():
    # A failure inside processing one item must not abandon the others, and the
    # reconciliation's final degraded attempt recovers the straggler (§14.7/§14.9).
    ledger = Ledger()
    digest = _Digest(
        "**Conflicts / discrepancies**\n"
        "- The schedule flow total disagrees with the riser demand values shown.\n"
        "- Note 4 calls out a device the legend never defines on this sheet."
    )
    # No client → both stragglers degrade; both must still be accounted.
    res = harvest_prose(ledger, [digest], [_Geom()], client=None, sleep=lambda *_: None)
    assert res.items == 2 and res.missing == 0
    assert len(ledger) == 2
    assert all(e.prose_item_ids for e in ledger.entries)


def test_extract_set_level_synthesis_conflicts_are_the_complement():
    # §14.8: a conflict statement naming NO in-set sheet is the complement of
    # extract_synthesis_conflicts (which keeps only the resolvable ones).
    text = "There is a mismatch between the pump spec and the schedule across the set."
    assert extract_synthesis_conflicts(text, ["F-D-01-1"]) == []
    assert extract_set_level_synthesis_conflicts(text, ["F-D-01-1"]) == [text]
    # A statement that DOES name an in-set sheet is not set-level.
    named = "The note on F-D-01-1 contradicts the schedule."
    assert extract_set_level_synthesis_conflicts(named, ["F-D-01-1"]) == []


def test_set_level_recovered_in_reconciliation_is_tallied_set_level(monkeypatch):
    # Review finding: a set-level item recovered by the final §14.9 reconciliation
    # (its main-loop processing raised) must be tallied as `set_level`, not `degraded`
    # — the recovery path mirrors the main-loop branch on `p.ref is None`.
    import drawing_analyzer.prose_harvest as PH

    real = PH._process_pending

    def _boom(ledger, p, result, **kw):
        if p.ref is None:                 # only the set-level item's first pass fails
            raise RuntimeError("transient")
        return real(ledger, p, result, **kw)

    monkeypatch.setattr(PH, "_process_pending", _boom)
    ledger = Ledger()
    synthesis = (
        "The specified fire pump conflicts with the schedule, and no single sheet "
        "in the set resolves which governs."
    )
    res = harvest_prose(ledger, [], [_Geom()], client=None,
                        synthesis_text=synthesis, sleep=lambda *_: None)
    assert res.missing == 0 and len(ledger) == 1
    assert res.set_level == 1 and res.degraded == 0        # counted as set-level, not degraded


def test_harvest_unresolvable_synthesis_conflict_becomes_set_level():
    # §14.8: a synthesis conflict naming no in-set sheet is no longer dropped — it
    # becomes a set-level ledger entry (source-less, anchor_hint SET_INDEX) bound
    # for Drawing_Set_Review_Notes.pdf.
    ledger = Ledger()
    synthesis = (
        "The specified fire pump conflicts with the schedule, and no single sheet "
        "in the set resolves which governs."
    )
    res = harvest_prose(
        ledger, [], [_Geom()], client=None, synthesis_text=synthesis, sleep=lambda *_: None,
    )
    assert res.set_level == 1 and res.missing == 0 and len(ledger) == 1
    e = ledger.entries[0]
    assert e.anchor_hint == "SET_INDEX" and e.source_id == "" and e.page_index == -1
    assert e.prose_item_ids and "conflicts with the schedule" in e.text


def test_focus_off_counts_intentional_exclusion():
    # §14.9: focus items present but not harvested (toggle off) are counted as an
    # explicit intentional exclusion, not silently ignored.
    digest = _Digest(
        "**Focus findings**\n- Room 120 has two floor sinks near the east wall area."
    )
    res = harvest_prose(Ledger(), [digest], [_Geom()], client=None, sleep=lambda *_: None)
    assert res.excluded_focus == 1 and res.items == 0


def test_identical_note_on_two_pages_of_one_source_stays_two_items():
    # Review finding: prose_item_id must fold page_index, or an identical boilerplate
    # note (same source_id, same per-page ordinal, same text) on two pages of ONE
    # multi-page PDF collides to one id and defeats the §14.9 no-drop reconciliation.
    from drawing_analyzer.prose_harvest import _enumerate_pending, HarvestResult

    note = "**Coordination items**\n- Coordinate all penetrations with the structural drawings."
    p0 = _Digest(note, source="M.pdf", page=0)
    p1 = _Digest(note, source="M.pdf", page=1)     # same source file, different page
    pending = _enumerate_pending(
        [p0, p1], "", {}, focus_findings_to_markups=False,
        sheet_text_of=lambda ref: "", display_id_of=lambda ref: "M-1",
        result=HarvestResult(),
    )
    ids = [p.pid for p in pending]
    assert len(pending) == 2 and len(set(ids)) == 2      # two DISTINCT ids, no collision

    # End-to-end: both pages' items reach the ledger and reconcile with 0 missing.
    ledger = Ledger()
    res = harvest_prose(ledger, [p0, p1], [_Geom("M.pdf", 0), _Geom("M.pdf", 1)],
                        client=None, sleep=lambda *_: None)
    assert res.items == 2 and res.missing == 0 and len(ledger) == 2
