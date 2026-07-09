"""Tests for the critique pass — "the reviewer" (Phase 11).

Two layers, most hermetic and PyMuPDF-free:

- the pure merge/dedupe logic and the prompt/request shape (a hand-built
  ``RenderedSheet`` needs no rasterizer), driven by a fake client;
- one end-to-end pipeline test (needs PyMuPDF, since the critique stage
  re-renders) that a critique run pools + deduplicates with the digest.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer import profiles as P
from drawing_analyzer.critique import (
    CRITIQUE_PROMPT_VERSION,
    CRITIQUE_SYSTEM_PROMPT,
    CritiqueResult,
    _CRITIQUE_TASK_INSTRUCTION,
    _is_duplicate,
    _rect_iou,
    _run_checklists,
    _token_overlap,
    build_critique_request_params,
    critique_runs,
    critique_sheet,
    critique_sheet_self_consistent,
    critique_system_prompt,
    merge_finding_groups,
    merge_self_consistency,
)
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import Anchor, Finding, ImageTile, RenderedSheet, SheetRef
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

_NOOP = lambda *_a, **_k: None  # noqa: E731 - injectable no-op sleep


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _finding(text, *, quote="", tile=None, sev="medium", cat="code",
             source="s.pdf", page=0, rect=None, reproduced=True, hint=""):
    f = Finding(
        sheet_id="F-D-01-1", source_name=source, page_index=page, category=cat,
        severity=sev, text=text, source_quote=quote, tile=tile,
        anchor_hint=hint, reproduced=reproduced,
    )
    if rect is not None:
        f.anchor = Anchor(status="EXACT", rect_pdf=list(rect), method="test")
    return f


def _rendered(*, source="s.pdf", page=0, sheet_text="VAV-3 SERVES ROOM 120"):
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)
    ov = ImageTile(png_bytes=b"OVERVIEW", width_px=100, height_px=80, kind="overview")
    tile = ImageTile(png_bytes=b"TILE00", width_px=50, height_px=40, kind="tile",
                     row=0, col=0, label="top-left")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[tile], page_width_pt=792, page_height_pt=612,
        rows=1, cols=1, sheet_text=sheet_text,
    )


def _block(findings):
    return "```json\n" + json.dumps({"findings": findings}) + "\n```"


class _StatusError(Exception):
    """Duck-typed anthropic.APIStatusError (carries status_code)."""

    def __init__(self, status_code, message=""):
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


class _CritiqueClient:
    """Scripted critique client. ``script`` items are findings-lists (success)
    or Exception instances (raised). Indexed by *attempt* so a raised item is
    consumed like a real failed call."""

    def __init__(self, script):
        self._script = list(script)
        self.attempts = 0
        self.calls = 0            # successful returns
        self.captured = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                idx = outer.attempts
                outer.attempts += 1
                item = outer._script[idx] if idx < len(outer._script) else []
                if isinstance(item, Exception):
                    raise item
                outer.captured.append(kw)
                outer.calls += 1
                text = _block(item)
                return FakeMessage(
                    content=[FakeTextBlock(text=text)],
                    usage=FakeUsage(input_tokens=100, output_tokens=20),
                )

        self.messages = _Msgs()


# --------------------------------------------------------------------------- #
# Prompt / request shape
# --------------------------------------------------------------------------- #


def test_prompt_version_stable_and_system_prompt_has_findings():
    assert isinstance(CRITIQUE_PROMPT_VERSION, str) and len(CRITIQUE_PROMPT_VERSION) == 16
    sysp = critique_system_prompt()
    assert sysp.startswith(CRITIQUE_SYSTEM_PROMPT)
    assert "FINDINGS" in sysp and "absence" in sysp.lower()


def test_request_uses_critique_system_and_task_instruction():
    rendered = _rendered()
    client = _CritiqueClient([[]])
    critique_sheet(rendered, client=client, max_retries=0, sleep=_NOOP)
    kw = client.captured[0]
    assert kw["system"] == critique_system_prompt()
    # The closing user block is the critique task, NOT the digest's.
    text_blocks = [b["text"] for b in kw["messages"][0]["content"] if b.get("type") == "text"]
    assert text_blocks[-1] == _CRITIQUE_TASK_INSTRUCTION
    # The sheet text layer still rides in the request (grounding preserved).
    assert any("VAV-3 SERVES ROOM 120" in t for t in text_blocks)


def test_build_request_params_attaches_thinking_and_effort_for_opus():
    params = build_critique_request_params([], model="claude-opus-4-8")
    assert params["system"] == critique_system_prompt()
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "high"}


# --------------------------------------------------------------------------- #
# Parsing (via the shared parser): anchor_hint + absences
# --------------------------------------------------------------------------- #


def test_absence_finding_carries_sheet_anchor_hint():
    rendered = _rendered()
    absence = {
        "sheet_id": "F-D-01-1", "category": "coordination", "severity": "medium",
        "text": "Expected low-point drain; not found on this sheet.",
        "source_quote": "", "anchor_hint": "SHEET",
    }
    findings, _claims, _in, _out, err = critique_sheet(
        rendered, client=_CritiqueClient([[absence]]), max_retries=0, sleep=_NOOP
    )
    assert err is None and len(findings) == 1
    assert findings[0].anchor_hint == "SHEET"
    assert findings[0].source_quote == ""


def test_bogus_anchor_hint_is_dropped_to_empty():
    rendered = _rendered()
    item = {"sheet_id": "X", "category": "code", "severity": "low",
            "text": "t", "anchor_hint": "somewhere-vague"}
    findings, *_ = critique_sheet(
        rendered, client=_CritiqueClient([[item]]), max_retries=0, sleep=_NOOP
    )
    assert findings[0].anchor_hint == ""   # only "SHEET" survives


# --------------------------------------------------------------------------- #
# Dedupe primitives (the matrix)
# --------------------------------------------------------------------------- #


def test_token_overlap_and_iou():
    assert _token_overlap("VAV-3 has no clearance", "VAV-3 has no clearance") == 1.0
    assert _token_overlap("alpha beta gamma", "delta epsilon zeta") == 0.0
    assert _rect_iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert _rect_iou([0, 0, 10, 10], [100, 100, 110, 110]) == 0.0


def test_duplicate_matrix():
    a = _finding("VAV-3 has no shown clearance to the wall", quote="VAV-3", tile=[0, 0])
    # text-only: same text, different tile
    b_text = _finding("VAV-3 has no shown clearance to the wall", tile=[2, 2])
    # tile-only: same tile, unrelated text
    b_tile = _finding("Completely unrelated note about piping", tile=[0, 0])
    # neither
    b_none = _finding("Completely unrelated note about piping", tile=[3, 3])
    assert _is_duplicate(a, b_text) is True     # text overlap > 0.7
    assert _is_duplicate(a, b_tile) is True      # same tile
    assert _is_duplicate(a, b_none) is False
    # IoU path: two anchored findings whose rects overlap heavily
    r1 = _finding("x", rect=[0, 0, 10, 10], tile=None)
    r2 = _finding("y", rect=[1, 1, 10, 10], tile=None)
    r3 = _finding("z", rect=[0, 0, 4, 4], tile=None)     # IoU with r1 = 16/100 < 0.5
    assert _is_duplicate(r1, r2) is True
    assert _is_duplicate(r1, r3) is False
    # different sheet is never a duplicate
    other = _finding("VAV-3 has no shown clearance to the wall", quote="VAV-3",
                     tile=[0, 0], source="other.pdf")
    assert _is_duplicate(a, other) is False


# --------------------------------------------------------------------------- #
# Merge semantics
# --------------------------------------------------------------------------- #


def test_self_consistency_marks_reproduced():
    a = _finding("VAV-3 has no shown clearance", quote="VAV-3", tile=[0, 0])
    a2 = _finding("VAV-3 has no shown clearance", quote="VAV-3", tile=[0, 0])
    only1 = _finding("Relief valve set 165 psi too high", quote="165 PSI", tile=[1, 1])
    merged = merge_self_consistency([[a, only1], [a2]])
    by_tile = {tuple(f.tile): f for f in merged}
    assert by_tile[(0, 0)].reproduced is True     # seen in both runs
    assert by_tile[(1, 1)].reproduced is False     # singleton
    assert len(merged) == 2


def test_single_run_leaves_everything_reproduced():
    merged = merge_self_consistency([[_finding("a", tile=[0, 0]), _finding("b", tile=[1, 1])]])
    assert all(f.reproduced for f in merged)       # no second read to disagree


def test_merge_keeps_most_severe_and_longest_quote_and_union_refs():
    a = _finding("Same issue", quote="VAV", tile=[0, 0], sev="low")
    a.refs = ["NFPA 13"]
    b = _finding("Same issue phrased alike", quote="VAV-3 SCHEDULE", tile=[0, 0], sev="high")
    b.refs = ["CMC 310"]
    merged = merge_self_consistency([[a], [b]])
    assert len(merged) == 1
    m = merged[0]
    assert m.severity == "high"                    # most severe wins
    assert m.source_quote == "VAV-3 SCHEDULE"       # longest quote wins
    assert set(m.refs) == {"NFPA 13", "CMC 310"}    # refs unioned


def test_pool_upgrades_reproduced_on_cross_source_agreement():
    # A critique singleton (reproduced False) that the digest independently
    # raised is upgraded to reproduced True; an unmatched singleton stays False.
    digest = _finding("Missing low-point drain shown", tile=[2, 2])
    crit_match = _finding("Missing low-point drain", tile=[2, 2], reproduced=False)
    crit_alone = _finding("Odd symbol near riser", tile=[4, 4], reproduced=False)
    pooled = merge_finding_groups([[digest], [crit_match, crit_alone]])
    by_tile = {tuple(f.tile): f for f in pooled}
    assert by_tile[(2, 2)].reproduced is True      # corroborated by digest
    assert by_tile[(4, 4)].reproduced is False     # critique-only singleton
    assert len(pooled) == 2


def test_pool_is_per_sheet_only():
    # Same text/tile but different sheets must never merge.
    a = _finding("identical text here", tile=[0, 0], source="a.pdf")
    b = _finding("identical text here", tile=[0, 0], source="b.pdf")
    pooled = merge_finding_groups([[a], [b]])
    assert len(pooled) == 2


# --------------------------------------------------------------------------- #
# Self-consistent runner + caching + failure
# --------------------------------------------------------------------------- #


def test_self_consistent_runs_twice_and_merges():
    rendered = _rendered()
    a = {"sheet_id": "F", "category": "code", "severity": "high",
         "text": "VAV-3 has no shown clearance", "source_quote": "VAV-3", "tile": [0, 0]}
    b = {"sheet_id": "F", "category": "code", "severity": "low",
         "text": "Relief valve set 165 psi too high", "source_quote": "165 PSI", "tile": [1, 1]}
    client = _CritiqueClient([[a, b], [a]])   # run1: a,b   run2: a
    res = critique_sheet_self_consistent(rendered, client=client, runs=2,
                                         max_retries=0, sleep=_NOOP)
    assert client.calls == 2 and res.runs == 2
    assert res.input_tokens == 200 and res.output_tokens == 40
    by_tile = {tuple(f.tile): f for f in res.findings}
    assert by_tile[(0, 0)].reproduced is True
    assert by_tile[(1, 1)].reproduced is False


def test_self_consistent_cached_second_time():
    rendered = _rendered()
    a = {"sheet_id": "F", "category": "code", "severity": "high",
         "text": "t", "source_quote": "VAV-3", "tile": [0, 0]}
    cache = DigestCache(None, persist=False)
    client = _CritiqueClient([[a], [a], [a], [a]])
    r1 = critique_sheet_self_consistent(rendered, client=client, cache=cache, runs=2,
                                        max_retries=0, sleep=_NOOP)
    assert client.calls == 2 and r1.cached is False
    r2 = critique_sheet_self_consistent(rendered, client=client, cache=cache, runs=2,
                                        max_retries=0, sleep=_NOOP)
    assert client.calls == 2          # served from cache — no new model calls
    assert r2.cached is True
    assert [f.to_dict() for f in r2.findings] == [f.to_dict() for f in r1.findings]


# --- Numeric claims (Phase 14) ---------------------------------------------- #


class _ClaimsClient:
    """Returns a fixed findings+claims block for every critique call."""

    def __init__(self, claims):
        import json as _json

        self._text = "```json\n" + _json.dumps({"findings": [], "claims": claims}) + "\n```"
        self.calls = 0
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.calls += 1
                return FakeMessage(
                    content=[FakeTextBlock(text=outer._text)],
                    usage=FakeUsage(input_tokens=100, output_tokens=20),
                )

        self.messages = _Msgs()


def test_critique_sheet_parses_numeric_claims():
    claim = {"sheet_id": "F-D-01-1", "quote": "TOTAL 540", "kind": "sum",
             "terms": [180, 180, 180], "expected": 540, "note": "flow total"}
    findings, claims, _in, _out, err = critique_sheet(
        _rendered(), client=_ClaimsClient([claim]), max_retries=0, sleep=_NOOP
    )
    assert err is None
    assert len(claims) == 1
    c = claims[0]
    assert c.kind == "sum" and c.terms == [180, 180, 180] and c.expected == 540
    # The emitting sheet is stamped on the claim so it anchors on that sheet.
    assert c.source_name == "s.pdf" and c.page_index == 0


def test_self_consistent_dedups_and_caches_claims():
    claim = {"sheet_id": "F-D-01-1", "quote": "TOTAL 540", "kind": "sum",
             "terms": [180, 180, 180], "expected": 540}
    cache = DigestCache(None, persist=False)
    client = _ClaimsClient([claim])
    r1 = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                        runs=2, max_retries=0, sleep=_NOOP)
    # Both runs transcribed the same relationship → deduped to one claim.
    assert len(r1.claims) == 1 and client.calls == 2
    # Served from cache the second time, claims survive the round-trip.
    r2 = critique_sheet_self_consistent(_rendered(), client=client, cache=cache,
                                        runs=2, max_retries=0, sleep=_NOOP)
    assert r2.cached is True and client.calls == 2
    assert [c.to_dict() for c in r2.claims] == [c.to_dict() for c in r1.claims]


def test_transient_error_is_retried_then_succeeds():
    rendered = _rendered()
    ok = {"sheet_id": "F", "category": "code", "severity": "low", "text": "t"}
    client = _CritiqueClient([_StatusError(503), [ok]])   # first attempt 503, then ok
    findings, _claims, _in, _out, err = critique_sheet(
        rendered, client=client, max_retries=2, sleep=_NOOP
    )
    assert err is None and len(findings) == 1
    assert client.attempts == 2


def test_all_runs_failing_degrades_to_empty_with_error():
    rendered = _rendered()
    client = _CritiqueClient([_StatusError(400), _StatusError(400)])   # permanent
    res = critique_sheet_self_consistent(rendered, client=client, runs=2,
                                         max_retries=0, sleep=_NOOP)
    assert res.findings == [] and res.runs == 0 and res.error


def test_one_failed_run_still_merges_the_other():
    rendered = _rendered()
    ok = {"sheet_id": "F", "category": "code", "severity": "low",
          "text": "still found this", "tile": [0, 0]}
    client = _CritiqueClient([_StatusError(400), [ok]])   # run1 fails, run2 ok
    res = critique_sheet_self_consistent(rendered, client=client, runs=2,
                                         max_retries=0, sleep=_NOOP)
    assert res.runs == 1 and len(res.findings) == 1 and res.error is None


# --- Review fixes: distinct absences, empty bodies, partial-run caching ------ #


def test_distinct_absences_do_not_over_merge_on_boilerplate():
    # Absences carry no tile and no quote, so they can only dedupe on text. Two
    # different missing items share only the mandated "…; not found on this sheet"
    # boilerplate — they must NOT collapse (which would drop one and falsely mark
    # the survivor reproduced).
    a1 = _finding("expected cleanout; not found on this sheet", hint="SHEET")
    a2 = _finding("expected backflow preventer; not found on this sheet", hint="SHEET")
    merged = merge_self_consistency([[a1], [a2]])
    assert len(merged) == 2
    assert all(f.reproduced is False for f in merged)
    # A genuine repeat of the SAME absence still merges and reproduces.
    b1 = _finding("expected cleanout; not found on this sheet", hint="SHEET")
    b2 = _finding("expected cleanout; not found on this sheet", hint="SHEET")
    dup = merge_self_consistency([[b1], [b2]])
    assert len(dup) == 1 and dup[0].reproduced is True


class _EmptyBodyClient:
    """Every critique call returns an empty body (e.g. thinking ate the budget)."""

    def __init__(self):
        self.calls = 0
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.calls += 1
                return FakeMessage(
                    content=[FakeTextBlock(text="")],
                    usage=FakeUsage(input_tokens=500, output_tokens=0),
                    stop_reason="max_tokens",
                )

        self.messages = _Msgs()


def test_empty_body_is_error_not_a_clean_sheet():
    # An empty response is a failed read, not "reviewed, nothing found".
    findings, _claims, _in, _out, err = critique_sheet(
        _rendered(), client=_EmptyBodyClient(), max_retries=0, sleep=_NOOP
    )
    assert findings == [] and err is not None and "empty" in err.lower()


def test_empty_runs_are_not_frozen_as_clean_in_cache():
    cache = DigestCache(None, persist=False)
    res = critique_sheet_self_consistent(
        _rendered(), client=_EmptyBodyClient(), cache=cache, runs=2,
        max_retries=0, sleep=_NOOP,
    )
    assert res.runs == 0 and res.error and res.findings == []
    assert cache.stats()["size"] == 0     # nothing cached → a re-run re-attempts


def test_partial_run_is_returned_but_not_cached():
    # runs=2 but one run fails → the surviving run's findings are returned, but
    # the (1-of-2, all-reproduced) result is NOT frozen under the runs=2 key.
    cache = DigestCache(None, persist=False)
    ok = {"sheet_id": "F", "category": "code", "severity": "low",
          "text": "found this", "tile": [0, 0]}
    client = _CritiqueClient([_StatusError(400), [ok]])
    res = critique_sheet_self_consistent(
        _rendered(), client=client, cache=cache, runs=2, max_retries=0, sleep=_NOOP
    )
    assert res.runs == 1 and len(res.findings) == 1
    assert cache.stats()["size"] == 0


# --- Review profiles (Phase 12): injection, cache key, chunking -------------- #


def test_checklist_injected_before_findings_instruction():
    fp = P.get_profile("fire-protection")
    checklist = _run_checklists([fp], 1)[0]
    client = _CritiqueClient([[]])
    critique_sheet(_rendered(), client=client, max_retries=0, sleep=_NOOP, checklist=checklist)
    sysp = client.captured[0]["system"]
    assert "APPLY THIS REVIEW CHECKLIST" in sysp
    assert "K-8.0" in sysp                                     # a profile item rode in
    # The findings instruction stays LAST (the parser's last-fenced-block rule).
    assert sysp.index("APPLY THIS REVIEW") < sysp.index("FINDINGS (machine-read")


def test_no_profiles_reproduces_plain_prompt():
    client = _CritiqueClient([[]])
    critique_sheet(_rendered(), client=client, max_retries=0, sleep=_NOOP)   # no checklist
    assert client.captured[0]["system"] == critique_system_prompt()
    assert "APPLY THIS REVIEW CHECKLIST" not in client.captured[0]["system"]


def test_profiles_change_the_critique_cache_key():
    fp = P.get_profile("fire-protection")
    a = {"sheet_id": "F", "category": "code", "severity": "low", "text": "t"}
    c_plain = DigestCache(None, persist=False)
    c_prof = DigestCache(None, persist=False)
    critique_sheet_self_consistent(_rendered(), client=_CritiqueClient([[a]]),
                                   cache=c_plain, runs=1, max_retries=0, sleep=_NOOP)
    critique_sheet_self_consistent(_rendered(), client=_CritiqueClient([[a]]),
                                   cache=c_prof, runs=1, max_retries=0, sleep=_NOOP,
                                   profiles=[fp])
    assert next(iter(c_plain._entries)) != next(iter(c_prof._entries))


def test_long_profile_chunks_across_runs_short_does_not():
    fp = P.get_profile("fire-protection")
    short = _run_checklists([fp], 2)               # shipped profile is short
    assert short[0] == short[1] and "APPLY" in short[0]
    big = P.Profile(
        name="big", title="big", version="1", content_hash="h",
        items=tuple(f"lengthy checklist item {i} describing a distinct check" for i in range(400)),
    )
    full_len = len(P.build_checklist_prompt(P.flatten_items([big])))
    chunked = _run_checklists([big], 2)
    assert len(chunked) == 2 and chunked[0] != chunked[1]
    assert all(len(c) < full_len for c in chunked)   # each run a slice, not the whole


# --------------------------------------------------------------------------- #
# Pipeline integration (needs PyMuPDF — the critique stage re-renders)
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402


def _make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "VAV-3 SERVES ROOM 120")
    page.insert_text((80, 200), "RELIEF VALVE SET AT 165 PSI")
    page.insert_text((650, 560), "F-D-01-1")
    doc.save(str(path))
    doc.close()
    return path


_D = {"sheet_id": "F-D-01-1", "category": "code", "severity": "high",
      "text": "VAV-3 has no shown clearance to the wall.",
      "source_quote": "VAV-3", "tile": [0, 0]}
_C2 = {"sheet_id": "F-D-01-1", "category": "code", "severity": "medium",
       "text": "Relief valve set at 165 PSI exceeds the maximum.",
       "source_quote": "165 PSI", "tile": [1, 1]}


class _PipelineClient:
    """Routes digest / critique / verify. Critique run 1 = [D, C2], run 2 = [D],
    so D is reproduced (and also raised by the digest) while C2 is a singleton."""

    def __init__(self, *, critique_raises=False):
        self.digest_calls = 0
        self.critique_calls = 0
        self.verify_calls = 0
        self.critique_had_checklist = False
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                if system == VERIFY_SYSTEM_PROMPT:
                    outer.verify_calls += 1
                    return FakeMessage(
                        content=[FakeTextBlock(text='{"verdict":"CONFIRMED","note":"seen"}')],
                        usage=FakeUsage(input_tokens=40, output_tokens=8))
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    outer.critique_calls += 1
                    if "APPLY THIS REVIEW CHECKLIST" in system:
                        outer.critique_had_checklist = True
                    if critique_raises:
                        raise _StatusError(400)   # permanent → degrades to empty
                    findings = [_D, _C2] if outer.critique_calls == 1 else [_D]
                    return FakeMessage(content=[FakeTextBlock(text=_block(findings))],
                                       usage=FakeUsage(input_tokens=100, output_tokens=20))
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    outer.digest_calls += 1
                    prose = "Sheet F-D-01-1 - Fire Protection - Plan\nVAV-3 serves the room."
                    return FakeMessage(
                        content=[FakeTextBlock(text=prose + "\n\n" + _block([_D]))],
                        usage=FakeUsage(input_tokens=500, output_tokens=80))
                return FakeMessage(content=[FakeTextBlock(text="ok")])

        self.messages = _Msgs()


def test_pipeline_critique_pools_and_marks_reproduced(tmp_path):
    src = _make_pdf(tmp_path / "F-D-01-1.pdf")
    client = _PipelineClient()
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        qc_markups=True, critique=True, qc_work_dir=tmp_path / "qc",
    )
    assert client.digest_calls == 1
    assert client.critique_calls == 2                    # self-consistency: 2 runs
    # Pooled: the VAV-3 issue (digest + both critique runs) + the singleton C2.
    assert len(ctx.findings) == 2
    by_quote = {f.source_quote: f for f in ctx.findings}
    assert by_quote["VAV-3"].reproduced is True          # corroborated
    assert by_quote["165 PSI"].reproduced is False        # critique singleton
    # I-2: findings never leak into the prose.
    assert "```json" not in ctx.combined_text
    assert '"findings"' not in ctx.combined_text


def test_pipeline_without_critique_is_unchanged(tmp_path):
    src = _make_pdf(tmp_path / "F-D-01-1.pdf")
    client = _PipelineClient()
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        qc_markups=True, critique=False, qc_work_dir=tmp_path / "qc",
    )
    assert client.critique_calls == 0
    assert len(ctx.findings) == 1                         # digest finding only
    assert ctx.findings[0].reproduced is True             # default, not flagged


def test_pipeline_critique_failure_is_non_fatal(tmp_path):
    src = _make_pdf(tmp_path / "F-D-01-1.pdf")
    client = _PipelineClient(critique_raises=True)
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2,
        qc_markups=True, critique=True, qc_work_dir=tmp_path / "qc",
    )
    # Critique degraded to nothing; the digest finding still ships, run completes.
    assert len(ctx.findings) == 1
    assert ctx.findings[0].source_quote == "VAV-3"


def test_pipeline_cached_critique_rerun_adds_no_tokens(tmp_path):
    # A fully-cached re-run must report ~0 new tokens — the cached critique's
    # original cost is not re-counted. (verify off so the only possible tokens
    # would be the cached digest + critique.)
    src = _make_pdf(tmp_path / "F-D-01-1.pdf")
    cache = DigestCache(None, persist=False)
    extract_drawing_context(
        [src], client=_PipelineClient(), rows=2, cols=2, critique=True,
        qc_markups=True, verify_findings=False, cache=cache, qc_work_dir=tmp_path / "q1",
    )
    client2 = _PipelineClient()
    ctx2 = extract_drawing_context(
        [src], client=client2, rows=2, cols=2, critique=True,
        qc_markups=True, verify_findings=False, cache=cache, qc_work_dir=tmp_path / "q2",
    )
    assert client2.digest_calls == 0 and client2.critique_calls == 0   # all cached
    assert ctx2.total_input_tokens == 0 and ctx2.total_output_tokens == 0


def test_pipeline_critique_applies_selected_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_PROFILES_DIR", str(tmp_path / "no_user"))  # builtins only
    src = _make_pdf(tmp_path / "F-D-01-1.pdf")
    client = _PipelineClient()
    extract_drawing_context(
        [src], client=client, rows=2, cols=2, critique=True, qc_markups=True,
        profiles=["fire-protection"], qc_work_dir=tmp_path / "qc",
    )
    assert client.critique_calls == 2                 # self-consistency still runs twice
    assert client.critique_had_checklist is True       # the FP checklist rode into the prompt


def test_pipeline_profiles_ignored_without_critique(tmp_path):
    src = _make_pdf(tmp_path / "F-D-01-1.pdf")
    client = _PipelineClient()
    extract_drawing_context(
        [src], client=client, rows=2, cols=2, critique=False, qc_markups=True,
        profiles=["fire-protection"], qc_work_dir=tmp_path / "qc",
    )
    assert client.critique_calls == 0 and client.critique_had_checklist is False
