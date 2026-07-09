"""Part III tests: the findings ledger, the prose harvest, and coverage (§16–19).

Pure and hermetic — synthetic findings/digests, a scripted fake client for the
structuring calls, no network, no PyMuPDF (the PDF-facing gating matrix lives in
``test_drawing_markup_rich.py``; the end-to-end coverage assertion in
``test_drawing_qc_pipeline.py``).
"""
from __future__ import annotations

import json
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


def test_ledger_post_freeze_add_is_loud_but_non_fatal():
    ledger = Ledger()
    ledger.add([_f("first", rect=[10, 20, 60, 40])], "digest_json")
    ledger.freeze()
    ledger.add([_f("straggler after freeze")], "digest_json")
    assert len(ledger) == 2
    late = next(e for e in ledger.entries if e.text == "straggler after freeze")
    assert late.qc_id.startswith("QC-XTRA-")     # visibly numbered as a bug signal


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
