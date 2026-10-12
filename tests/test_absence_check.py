"""The absence cross-check (`absence_check.py`).

Hermetic (I-4) and PyMuPDF-free: synthetic ``SheetGeometry`` word tuples give
each sheet its title-block id, and fake clients from ``fake_anthropic`` answer
the text-only call. The host's grounding rule is the subject: a FOUND moves a
finding only when its quote is on the named sheet.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from drawing_analyzer import absence_check as A
from drawing_analyzer.absence_check import check_absences, is_sheet_absence
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import ConflictLeg, Finding, SheetGeometry, SheetRef
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)

W, H = 792.0, 612.0
_NOOP = lambda *_a, **_k: None  # noqa: E731

PLAN_TEXT = "LEVEL 2 SPRINKLER PLAN\nWET SYSTEM ZONE 3\nMAIN 4 IN"
NOTES_TEXT = (
    "GENERAL NOTES\n"
    "1. PROVIDE INSPECTOR'S TEST CONN. AT REMOTE END OF EACH SYSTEM.\n"
    "2. SEISMIC BRACING PER NFPA 13."
)


def _geom(source: str, sid: str, text: str, *, full: str | None = None) -> SheetGeometry:
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source,
                   page_count=1, source_id=f"SRC-{source}")
    return SheetGeometry(
        ref=ref, page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=[(W - 300, H - 160, W - 240, H - 148, sid, 0, 0, 0)],
        sheet_text=text, full_sheet_text=full,
    )


def _set() -> list[SheetGeometry]:
    # S001 = FP-101 (the plan the absence is reported on), S002 = FP-001 (notes).
    return [_geom("plan.pdf", "FP-101", PLAN_TEXT), _geom("notes.pdf", "FP-001", NOTES_TEXT)]


def _absence(text: str = "Inspector's test connection not shown on this sheet.",
             severity: str = "medium", **kw) -> Finding:
    base = dict(
        sheet_id="FP-101", source_name="plan.pdf", page_index=0, category="code",
        severity=severity, text=text, source_id="SRC-plan.pdf", anchor_hint="SHEET",
    )
    base.update(kw)
    return Finding(**base)


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


class _Raising(BetaClientMixin):
    def __init__(self):
        self.calls = 0
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(_self, **kw):
                outer.calls += 1
                raise RuntimeError("permanent failure")

        self.messages = _Msgs()


def _handles(text: str) -> list[str]:
    return re.findall(r"^\[(A\d+)\] ", text, re.MULTILINE)


def _all(verdict: str, sheet: str = "", quote: str = ""):
    return lambda text: _reply([
        {"absence": h, "verdict": verdict, "sheet": sheet, "quote": quote}
        for h in _handles(text)
    ])


# --------------------------------------------------------------------------- #
# Which findings are checked
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("finding, expected", [
    (_absence(), True),
    # A rect-anchored finding is not an absence; the crop verifier owns it.
    (_absence(anchor_hint=""), False),
    # A sheet-level finding that does not read as an absence.
    (_absence(text="Riser diagram conflicts with the plan."), False),
    # Cross-sheet conflicts and set-level findings are out of scope.
    (_absence(also_on=[ConflictLeg(sheet_id="FP-001", source_quote="X")]), False),
    (_absence(source_id="", source_name=""), False),
])
def test_only_single_sheet_absences_are_checked(finding, expected):
    assert is_sheet_absence(finding) is expected
    client = _Client(_all("NOT_FOUND"))
    res = check_absences([finding], _set(), client=client, sleep=_NOOP)
    assert (len(client.requests) == 1) is expected
    assert res.checked == (1 if expected else 0)


# --------------------------------------------------------------------------- #
# The host's grounding rule
# --------------------------------------------------------------------------- #

_ITC = "PROVIDE INSPECTOR'S TEST CONN. AT REMOTE END OF EACH SYSTEM."


@pytest.mark.parametrize("severity, sheet, quote, located_on, lowered_from", [
    # Shown on the notes sheet: recorded there and lowered to low.
    ("high", "S002", _ITC, "FP-001", "high"),
    ("medium", "S002", _ITC, "FP-001", "medium"),
    # Whitespace and case differences in the quote still re-find it.
    ("medium", "s002", "provide  inspector's test conn.", "FP-001", "medium"),
    # Already low: recorded, nothing to lower.
    ("low", "S002", _ITC, "FP-001", ""),
    # Shown on the very sheet it was reported missing from.
    ("high", "S001", "WET SYSTEM ZONE 3", "FP-101", "high"),
    # The quote is on S002, but the model named S001: not grounded.
    ("high", "S001", _ITC, None, ""),
    # A handle the corpus never had.
    ("high", "S099", _ITC, None, ""),
    # Invented text.
    ("high", "S002", "ITC VALVE AT RISER ROOM", None, ""),
    # Too short to show where anything is.
    ("high", "S002", "CONN.", None, ""),
    # One word is too generic, however long: it is on the sheet named.
    ("high", "S001", "SPRINKLER", None, ""),
])
def test_found_moves_a_finding_only_when_its_quote_is_on_the_named_sheet(
    severity, sheet, quote, located_on, lowered_from,
):
    f = _absence(severity=severity)
    client = _Client(_all("FOUND", sheet, quote))
    res = check_absences([f], _set(), client=client, sleep=_NOOP)
    assert not res.partial and res.error is None
    if located_on is None:
        assert f.located_elsewhere is None and f.severity == severity
        assert (res.located, res.not_located, res.ungrounded) == (0, 1, 1)
        return
    loc = f.located_elsewhere
    assert loc is not None and loc.sheet_id == located_on
    assert loc.quote == " ".join(quote.split()) and loc.demoted_from == lowered_from
    assert loc.same_sheet is (located_on == "FP-101")
    assert f.severity == "low"
    assert (res.located, res.demoted) == (1, 1 if lowered_from else 0)


def test_grounding_reads_the_full_text_not_the_capped_one():
    # The model sees the capped text; the host re-checks the uncapped evidence.
    notes = _geom("notes.pdf", "FP-001", "GENERAL NOTES", full=NOTES_TEXT)
    f = _absence()
    check_absences([f], [_set()[0], notes], client=_Client(_all("FOUND", "S002", _ITC)),
                   sleep=_NOOP)
    assert f.located_elsewhere is not None and f.located_elsewhere.sheet_id == "FP-001"


def test_not_found_changes_nothing():
    f = _absence(severity="high")
    res = check_absences([f], _set(), client=_Client(_all("NOT_FOUND")), sleep=_NOOP)
    assert f.located_elsewhere is None and f.severity == "high"
    assert (res.checked, res.located, res.not_located, res.unchecked) == (1, 0, 1, 0)
    assert not res.partial


# --------------------------------------------------------------------------- #
# Failures leave findings unchecked, never moved
# --------------------------------------------------------------------------- #


def _first_only(text: str) -> str:
    return _reply([{"absence": "A1", "verdict": "NOT_FOUND", "sheet": "", "quote": ""}])


@pytest.mark.parametrize("client_factory, unchecked, failed_requests", [
    (lambda: _Client(lambda _t: "I could not find a results object."), 2, 0),
    (lambda: _Client(_all("FOUND", "S002", _ITC), stop_reason="max_tokens"), 2, 0),
    (lambda: _Client(_first_only), 1, 0),
    (_Raising, 2, 1),
])
def test_an_unusable_reply_leaves_absences_unchecked(client_factory, unchecked,
                                                      failed_requests):
    findings = [_absence(severity="high"), _absence("Riser sign is missing.", "high")]
    res = check_absences(findings, _set(), client=client_factory(), sleep=_NOOP)
    assert res.partial and res.unchecked == unchecked
    assert res.failed_requests == failed_requests
    assert all(f.located_elsewhere is None and f.severity == "high" for f in findings)
    if unchecked == 2:
        assert res.error


def test_absences_are_sent_in_chunks_with_their_own_handles():
    findings = [_absence(f"Sign {i} is missing.") for i in range(A._MAX_ABSENCES_PER_REQUEST + 1)]
    client = _Client(_all("NOT_FOUND"))
    res = check_absences(findings, _set(), client=client, sleep=_NOOP)
    texts = [kw["messages"][0]["content"] for kw in client.requests]
    assert [len(_handles(t)) for t in texts] == [A._MAX_ABSENCES_PER_REQUEST, 1]
    assert "Sign 25 is missing." in texts[1]
    assert (res.checked, res.not_located, res.unchecked) == (len(findings), len(findings), 0)


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


def test_a_complete_reply_is_cached_and_replayed_without_a_call():
    cache = DigestCache(None, persist=False)
    first = _absence(severity="high")
    live = check_absences([first], _set(), client=_Client(_all("FOUND", "S002", _ITC)),
                          cache=cache, sleep=_NOOP)
    assert live.requests == 1 and live.cached_requests == 0

    again = _absence(severity="high")
    offline = _Raising()
    warm = check_absences([again], _set(), client=offline, cache=cache, sleep=_NOOP)
    assert offline.calls == 0 and warm.cached_requests == 1 and warm.requests == 0
    assert again.located_elsewhere == first.located_elsewhere
    assert again.severity == "low"


@pytest.mark.parametrize("answer, stop_reason", [
    (_first_only, "end_turn"),                         # one handle missing
    (_all("FOUND", "S002", _ITC), "max_tokens"),       # cut off
])
def test_an_incomplete_reply_is_not_cached(answer, stop_reason):
    cache = DigestCache(None, persist=False)
    findings = [_absence(), _absence("Riser sign is missing.")]
    check_absences(findings, _set(), client=_Client(answer, stop_reason=stop_reason),
                   cache=cache, sleep=_NOOP)
    client = _Client(_all("NOT_FOUND"))
    res = check_absences([_absence(), _absence("Riser sign is missing.")], _set(),
                         client=client, cache=cache, sleep=_NOOP)
    assert len(client.requests) == 1 and res.cached_requests == 0


# --------------------------------------------------------------------------- #
# Corpus budget
# --------------------------------------------------------------------------- #


def test_corpus_budget_keeps_short_sheets_whole_and_counts_the_cut():
    geoms = [
        _geom("a.pdf", "FP-001", "#" * 10),
        _geom("b.pdf", "FP-101", "@" * 1000),
        _geom("c.pdf", "FP-102", "%" * 1000),
    ]
    corpus = A._build_corpus(geoms, budget=410)
    assert corpus.text.count("#") == 10
    assert corpus.text.count("@") == corpus.text.count("%") == 200
    assert corpus.omitted_chars == 1600
