"""The action-plan pass (`action_plan.py`) and the rule for on-sheet instructions.

Hermetic (I-4) and PyMuPDF-free: fake clients from ``fake_anthropic`` answer
the text-only call. The subject is what the host does with the model's answer:
which findings are sent, what happens to an instruction that fails a check,
what a finding gets when the pass does not answer for it, and which
instructions may be drawn on a sheet.
"""
from __future__ import annotations

import json
import re

import pytest

from drawing_analyzer.action_plan import apply_severity_fallback, plan_actions
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import (
    ActionItem,
    Anchor,
    Citation,
    ConflictLeg,
    Finding,
    LocatedElsewhere,
    Verification,
    action_bucket,
    bucket_is_ranked,
    on_sheet_instruction,
)
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)


def _finding(text="Total demand does not equal the sum (1150 + 250 = 1400).", *,
             severity="medium", status="DETERMINISTIC", category="coordination",
             quote="TOTAL DEMAND 1250 GPM", anchor="EXACT", **kw) -> Finding:
    f = Finding(
        sheet_id="FP-101", source_name="set.pdf", source_id="SRC-0001", page_index=0,
        category=category, severity=severity, text=text, source_quote=quote, **kw,
    )
    f.anchor = Anchor(
        status=anchor, rect_pdf=None if anchor == "UNANCHORED" else [10, 10, 60, 30],
        method="t",
    )
    f.verification = Verification(status=status)
    return f


def _reply(results: list[dict]) -> str:
    return "```json\n" + json.dumps({"results": results}) + "\n```"


class _Client(BetaClientMixin):
    """Answers each request through ``answer(request_text)``; records requests."""

    def __init__(self, answer, *, stop_reason: str = "end_turn"):
        self.requests: list[dict] = []
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(_self, **kw):
                outer.requests.append(kw)
                text = kw["messages"][0]["content"]
                return FakeMessage(
                    content=[FakeTextBlock(text=answer(text))],
                    stop_reason=stop_reason,
                    usage=FakeUsage(input_tokens=900, output_tokens=60),
                )

        self.messages = _Msgs()


def _handles(text: str) -> list[str]:
    return re.findall(r"^\[(F\d+)\] ", text, re.MULTILINE)


def _all(bucket="FIRST", instruction="Correct the total demand to 1400 GPM", clear=True):
    return lambda text: _reply([
        {"finding": h, "bucket": bucket, "instruction": instruction, "clear_fix": clear}
        for h in _handles(text)
    ])


# --------------------------------------------------------------------------- #
# What the host keeps of the model's answer
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("instruction, clear_in, kept, clear_out", [
    # Every number in it is in the finding: kept, and its clear claim stands.
    ("Correct the total demand to 1400 GPM", True, True, True),
    # 1,400 and 1400 are the same number; a trailing period is not part of it.
    ("Correct the total demand to 1,400 GPM.", True, True, True),
    # The model never supplies a number: 1500 is nowhere in the finding.
    ("Correct the total demand to 1500 GPM", True, False, False),
    # A sheet id the finding never mentions is an invented number too.
    ("Move the note to FP-502", True, False, False),
    # A hedged line is kept as text but can never be "clear".
    ("Confirm the total demand with the engineer", True, True, False),
    ("Correct the total, then check the riser", True, True, False),
    # ...while a noun that happens to be a hedging verb does not hedge.
    ("Add a check valve at the FDC", True, True, True),
    # Not one line: dropped rather than cut into something the model did not say.
    ("Correct " + "the total demand shown on this sheet " * 4, True, False, False),
    # The model's own "not clear" is never upgraded.
    ("Correct the total demand to 1400 GPM", False, True, False),
])
def test_an_instruction_is_kept_only_if_it_passes_the_host_checks(
        instruction, clear_in, kept, clear_out):
    f = _finding()
    res = plan_actions([f], client=_Client(_all(instruction=instruction, clear=clear_in)))
    assert f.action.bucket == "FIRST" and bucket_is_ranked(f)   # the bucket always stands
    assert bool(f.action.instruction) is kept
    assert f.action.clear_fix is clear_out
    assert res.dropped_instructions == (0 if kept else 1)
    assert not res.partial


def test_a_number_from_the_quote_the_legs_or_the_refs_is_not_invented():
    f = _finding("Main size disagrees between the plan and the riser.",
                 quote='6" FIRE MAIN', refs=["NFPA 13 2025"])
    f.also_on = [ConflictLeg(sheet_id="FP-601", source_name="set.pdf", page_index=1,
                             source_quote='4" FIRE MAIN')]
    line = "Match the 6 in. main on FP-101 to the 4 in. on FP-601 per NFPA 13"
    plan_actions([f], client=_Client(_all(instruction=line)))
    assert f.action.instruction == line


def test_a_ruled_out_finding_is_not_sent_and_gets_no_group():
    live, gone = _finding(), _finding("Riser tag duplicated.", status="REJECTED")
    client = _Client(_all())
    res = plan_actions([gone, live], client=client)
    assert res.findings == 1 and len(_handles(client.requests[0]["messages"][0]["content"])) == 1
    assert "Riser tag duplicated" not in client.requests[0]["messages"][0]["content"]
    assert gone.action is None and live.action is not None
    assert apply_severity_fallback([gone, live]) == 0 and gone.action is None


def test_the_request_tells_the_model_what_the_recheck_found():
    confirmed = _finding()
    unsure = _finding("Valve may not match its zone.", status="UNCERTAIN")
    code = _finding("Spacing exceeds the maximum.", status="VERIFIED", category="code",
                    refs=["NFPA 13"])
    code.citation = Citation(status="UNRESOLVABLE")
    client = _Client(_all())
    plan_actions([confirmed, unsure, code], client=client)
    blocks = client.requests[0]["messages"][0]["content"].split("\n\n")
    by_handle = {h: b for b in blocks for h in _handles(b)}
    assert "confirmed by re-check: yes" in by_handle["F1"]
    assert "confirmed by re-check: no" in by_handle["F2"]
    # A verified code finding is a confirmed drawing fact, not a confirmed
    # violation, until its reference checks out.
    assert "confirmed by re-check: no" in by_handle["F3"]
    assert "could not be confirmed" in by_handle["F3"]


# --------------------------------------------------------------------------- #
# What a finding gets when the pass does not answer for it
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("answer, stop_reason", [
    (lambda text: "I would rather not.", "end_turn"),                 # no results block
    (lambda text: _reply([{"finding": "F1", "bucket": "FIRST",
                           "instruction": "x", "clear_fix": True}]), "max_tokens"),
    (lambda text: _reply([{"finding": "F1", "bucket": "URGENT",       # not a bucket
                           "instruction": "x", "clear_fix": True}]), "end_turn"),
    (lambda text: _reply([{"finding": "F9", "bucket": "FIRST",        # not its handle
                           "instruction": "x", "clear_fix": True}]), "end_turn"),
], ids=["no_block", "cut_off", "unknown_bucket", "unknown_handle"])
def test_an_unusable_answer_leaves_the_finding_to_the_severity_fallback(answer, stop_reason):
    high, low = _finding(severity="high"), _finding("Tag style differs.", severity="low")
    res = plan_actions([high], client=_Client(answer, stop_reason=stop_reason))
    assert res.partial and res.unranked == 1 and high.action is None
    assert apply_severity_fallback([high, low]) == 2
    assert (action_bucket(high), action_bucket(low)) == ("FIRST", "IF_TIME")
    assert not bucket_is_ranked(high)
    # A fallback group never carries an instruction onto the sheet.
    assert on_sheet_instruction(high) == ""


def test_one_missing_answer_does_not_cost_the_others():
    a, b = _finding(), _finding("Detail 5 is referenced but not in the set.")
    res = plan_actions([a, b], client=_Client(lambda text: _reply([
        {"finding": "F2", "bucket": "LATER", "instruction": "Add the detail",
         "clear_fix": True},
    ])))
    assert (res.ranked, res.unranked, res.partial) == (1, 1, True)
    assert a.action is None and b.action.bucket == "LATER"


def test_a_complete_answer_is_cached_and_replayed_through_the_same_checks(monkeypatch):
    cache = DigestCache(None)
    client = _Client(_all(instruction="Correct the total demand to 1500 GPM"))
    first = _finding()
    plan_actions([first], client=client, cache=cache)
    assert len(client.requests) == 1 and first.action.instruction == ""

    again = _finding()
    res = plan_actions([again], client=client, cache=cache)
    assert len(client.requests) == 1 and res.cached_requests == 1
    # The cached line still names a number the finding does not: still dropped.
    assert again.action.bucket == "FIRST" and again.action.instruction == ""

    # A different finding list is a different request, never a stale hit.
    plan_actions([_finding("Something else entirely.")], client=client, cache=cache)
    assert len(client.requests) == 2


def test_a_partial_answer_is_not_cached():
    cache = DigestCache(None)
    calls = {"n": 0}

    def answer(text):
        calls["n"] += 1
        handles = _handles(text)[:1] if calls["n"] == 1 else _handles(text)
        return _reply([{"finding": h, "bucket": "LATER", "instruction": "Add a note",
                        "clear_fix": False} for h in handles])

    findings = [_finding(), _finding("Second finding.")]
    assert plan_actions(findings, client=_Client(answer), cache=cache).partial
    for f in findings:
        f.action = None
    res = plan_actions(findings, client=_Client(answer), cache=cache)
    assert res.cached_requests == 0 and not res.partial


# --------------------------------------------------------------------------- #
# Which instructions may be drawn on a sheet
# --------------------------------------------------------------------------- #


def _clear(finding: Finding) -> Finding:
    finding.action = ActionItem(bucket="FIRST", instruction="Correct the total", clear_fix=True)
    return finding


@pytest.mark.parametrize("build, shown", [
    (lambda: _clear(_finding()), True),
    (lambda: _clear(_finding(status="VERIFIED", category="conflict")), True),
    # The model's claim alone is never enough: the host must have confirmed it.
    (lambda: _clear(_finding(status="UNCERTAIN")), False),
    (lambda: _clear(_finding(status="SKIPPED")), False),
    (lambda: _clear(_finding(status="REJECTED")), False),
    # A code finding needs its reference to check out as well.
    (lambda: _clear(_finding(status="VERIFIED", category="code")), False),
    # A question is never an instruction.
    (lambda: _clear(_finding(status="VERIFIED", category="question")), False),
    # Placed by a tile guess, not by its own quote found in the sheet's text.
    (lambda: _clear(_finding(anchor="TILE")), False),
    (lambda: _clear(_finding(anchor="UNANCHORED")), False),
], ids=["computed", "verified", "uncertain", "skipped", "rejected", "code_unchecked",
        "question", "tile_placed", "unanchored"])
def test_on_sheet_instruction_needs_the_hosts_confirmation(build, shown):
    assert bool(on_sheet_instruction(build())) is shown


def test_on_sheet_instruction_also_needs_the_models_claim_and_a_checked_code_ref():
    code = _clear(_finding(status="VERIFIED", category="code"))
    code.citation = Citation(status="CHECKED_SUPPORTS")
    assert on_sheet_instruction(code) == "Correct the total"

    unsure = _finding()
    unsure.action = ActionItem(bucket="FIRST", instruction="Correct the total", clear_fix=False)
    assert on_sheet_instruction(unsure) == ""

    located = _clear(_finding())
    located.located_elsewhere = LocatedElsewhere("FP-001", quote="SEE GENERAL NOTES")
    assert on_sheet_instruction(located) == ""


def test_action_round_trips_and_an_older_payload_still_loads():
    f = _clear(_finding())
    back = Finding.from_dict(f.to_dict())
    assert back.action == f.action
    bare = _finding()
    assert "action" not in bare.to_dict()            # stored form unchanged until ranked
    assert Finding.from_dict(bare.to_dict()).action is None
