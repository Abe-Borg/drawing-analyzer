"""Phase C — the agentic investigation loop (`investigate.py`).

Hermetic (I-4): scripted fake clients, an injectable render_fn (no PyMuPDF),
tmp_path evidence dirs. Covers the deterministic tool executor, the multi-turn
loop discipline (commit-before-answer, one user turn per tool round, the
forced no-tools close at the budget), and the outcome rules (budget-capped or
garbled stays UNCERTAIN — never REJECTED).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from drawing_analyzer.investigate import (
    INVESTIGATE_SYSTEM_PROMPT,
    _ToolExecutor,
    find_text_matches,
    investigate_findings,
    investigation_max_findings,
    investigation_max_rounds,
    investigation_model,
    investigation_tools,
)
from drawing_analyzer.models import (
    Anchor,
    Finding,
    SheetRef,
    Verification,
    source_page_key,
)
from tests.fixtures.fake_anthropic import (
    FakeMessage,
    FakeTextBlock,
    FakeToolUseBlock,
    FakeUsage,
)

PAGE_W, PAGE_H = 800.0, 600.0


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


@dataclass
class _Geom:
    ref: SheetRef
    page_width_pt: float = PAGE_W
    page_height_pt: float = PAGE_H
    words: list = field(default_factory=list)
    sheet_text: str = ""


def _ref(name="fp.pdf", page=0, source_id="SRC-0001"):
    return SheetRef(pdf_path=Path(f"/tmp/{name}"), page_index=page,
                    source_name=name, page_count=2, source_id=source_id)


def _word(x0, y0, x1, y1, text, block=0, line=0, word_no=0):
    return (x0, y0, x1, y1, text, block, line, word_no)


def _finding(text="valve rating unclear", *, sev="high", quote="RATED 175 PSI",
             rect=(100.0, 100.0, 160.0, 114.0), status="UNCERTAIN",
             qc_id="QC-001", name="fp.pdf", note="depends on the pump schedule"):
    f = Finding(
        sheet_id="FP-101", source_name=name, source_id="SRC-0001", page_index=0,
        category="coordination", severity=sev, text=text, source_quote=quote,
        anchor=Anchor(status="EXACT", rect_pdf=list(rect) if rect else None,
                      method="exact"),
    )
    f.qc_id = qc_id
    f.verification = Verification(status=status, note=note)
    return f


def _render_fn(pdf_path, page_index, rect, dpi):
    return b"PNG|%s|p%d|%s|%d" % (
        str(pdf_path).encode(), page_index,
        ",".join(f"{v:.1f}" for v in rect).encode(), dpi,
    )


def _executor(tmp_path=None, sheet=None, sheet_id_map=None, finding=None,
              all_sheets=None):
    sheet = sheet or _Geom(_ref())
    finding = finding or _finding()
    id_map = sheet_id_map if sheet_id_map is not None else {"FP-101": sheet}
    return _ToolExecutor(
        finding=finding, sheet=sheet, sheet_id_map=id_map,
        evidence_dir=tmp_path, dir_name="QC-001", next_leg_index=0,
        render_fn=_render_fn,
        all_sheets=all_sheets if all_sheets is not None else list(id_map.values()),
    )


class _LoopClient:
    """create() delegates to ``responder(kw, call_no)``; captures every request."""

    def __init__(self, responder):
        self.calls: list[dict] = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.calls.append(kw)
                return responder(kw, len(outer.calls))

        self.messages = _Msgs()


def _tool_use(name="crop_region", tool_input=None, block_id="toolu_1"):
    return FakeMessage(
        content=[FakeToolUseBlock(
            name=name, input=tool_input or {"rect": [10, 10, 300, 200]}, id=block_id,
        )],
        stop_reason="tool_use",
        usage=FakeUsage(input_tokens=100, output_tokens=20),
    )


def _verdict(verdict="CONFIRMED", note="pump schedule confirms 175 PSI"):
    import json

    return FakeMessage(
        content=[FakeTextBlock(text=json.dumps({"verdict": verdict, "note": note}))],
        stop_reason="end_turn",
        usage=FakeUsage(input_tokens=80, output_tokens=15),
    )


def _tool_result_turns(kw):
    """Count user messages in the request that answer tools."""
    n = 0
    for m in kw["messages"]:
        if m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        if any(isinstance(b, dict) and b.get("type") == "tool_result"
               for b in m["content"]):
            n += 1
    return n


def _run_one(client, *, finding=None, max_rounds=6, evidence_dir=None):
    finding = finding or _finding()
    res = investigate_findings(
        [finding], [_Geom(_ref())], client=client, max_rounds=max_rounds,
        evidence_dir=evidence_dir, sleep=lambda *_: None, render_fn=_render_fn,
    )
    return res, finding


# --------------------------------------------------------------------------- #
# Tool executor
# --------------------------------------------------------------------------- #


def test_crop_region_clamps_to_the_page_and_returns_an_image(tmp_path):
    ex = _executor(tmp_path)
    content, is_error = ex.execute("crop_region", {"rect": [-50, -50, 9000, 9000]})
    assert not is_error
    assert content[0]["type"] == "text" and content[1]["type"] == "image"
    # Clamped to the page, traced with a sha, and saved before send (§16.6).
    (trace,) = ex.tool_trace
    assert trace["rect"] == [0.0, 0.0, PAGE_W, PAGE_H]
    assert trace["sha256"] and len(ex.artifacts) == 1
    saved = tmp_path / "QC-001" / ex.artifacts[0].relative_path.split("/")[-1]
    assert saved.read_bytes().startswith(b"PNG|")


def test_crop_region_rejects_malformed_and_offsheet_rects():
    ex = _executor()
    for bad in ({"rect": [1, 2, 3]}, {"rect": "nope"}, {},
                {"rect": [100, 100, 101, 101]},          # degenerate
                {"rect": [9000, 9000, 9500, 9500]}):     # fully off-sheet
        content, is_error = ex.execute("crop_region", bad)
        assert is_error, bad
    assert ex.tool_trace == []


def test_crop_region_clamps_dpi():
    ex = _executor()
    ex.execute("crop_region", {"rect": [10, 10, 300, 200], "dpi": 999})
    ex.execute("crop_region", {"rect": [10, 10, 300, 200], "dpi": 10})
    assert [t["dpi"] for t in ex.tool_trace] == [300, 72]


def test_unknown_sheet_id_errors_and_lists_known_sheets():
    ex = _executor()
    content, is_error = ex.execute("crop_region", {"rect": [10, 10, 300, 200],
                                                   "sheet_id": "Z-999"})
    assert is_error and "FP-101" in content


def test_unknown_tool_errors():
    content, is_error = _executor().execute("teleport", {})
    assert is_error and "unknown tool" in content


def test_find_text_matches_phrases_across_words_deterministically():
    words = [
        _word(10, 10, 40, 20, "FIRE", 0, 0, 0),
        _word(42, 10, 80, 20, "PUMP", 0, 0, 1),
        _word(82, 10, 120, 20, "SCHEDULE", 0, 0, 2),
        _word(10, 30, 60, 40, "PUMPHOUSE", 0, 1, 0),
    ]
    sheet = _Geom(_ref(), words=words)
    first = find_text_matches(sheet, "fire pump")
    assert first == find_text_matches(sheet, "fire pump")     # deterministic
    (m,) = first
    assert m["rect"] == [10.0, 10.0, 80.0, 20.0]              # union of both words
    assert m["line"] == "FIRE PUMP SCHEDULE"
    # Single-word substring matches inside a longer word too.
    assert len(find_text_matches(sheet, "PUMP")) == 2


def test_find_text_caps_matches_and_handles_raster_sheets():
    words = [_word(i * 10, 10, i * 10 + 8, 20, "RISER", 0, i, 0) for i in range(30)]
    matches = find_text_matches(_Geom(_ref(), words=words), "RISER")
    assert len(matches) <= 21
    ex = _executor(sheet=_Geom(_ref(), words=[]))
    content, is_error = ex.execute("find_text", {"query": "RISER"})
    assert not is_error and "no text layer" in content[0]["text"]
    assert _executor().execute("find_text", {"query": "x"})[1] is True  # too short


def test_view_sheet_resolves_by_id_and_by_source_page(tmp_path):
    other = _Geom(_ref("mech.pdf", 1, "SRC-0002"))
    ex = _executor(tmp_path, sheet_id_map={"FP-101": _Geom(_ref()), "M-101": other})
    content, is_error = ex.execute("view_sheet", {"sheet_id": "m-101"})
    assert not is_error and ex.tool_trace[-1]["dpi"] == 150
    content, is_error = ex.execute("view_sheet", {"source_name": "mech.pdf",
                                                  "page_number": 2})
    assert not is_error
    assert ex.execute("view_sheet", {})[1] is True             # names nothing
    assert ex.execute("view_sheet", {"source_name": "mech.pdf",
                                     "page_number": 9})[1] is True


def test_view_sheet_by_source_page_reaches_idless_sheets(tmp_path):
    # A sheet with NO detectable title-block ID (e.g. raster) is absent from
    # sheet_id_map but must stay reachable by source + page — that address
    # form exists precisely for it.
    own = _Geom(_ref())
    idless = _Geom(_ref("scan.pdf", 0, "SRC-0003"))
    ex = _executor(tmp_path, sheet=own, sheet_id_map={"FP-101": own},
                   all_sheets=[own, idless])
    content, is_error = ex.execute("view_sheet", {"source_name": "scan.pdf",
                                                  "page_number": 1})
    assert not is_error
    assert ex.tool_trace[-1]["source_page_key"] == list(source_page_key(idless.ref))


def test_partial_source_page_address_errors_instead_of_wrong_sheet():
    # source_name without page_number (or the reverse) must be an error — a
    # silent fallback to the finding's own sheet would hand the model an
    # overview of the WRONG sheet and a verdict could rest on it.
    ex = _executor()
    content, is_error = ex.execute("view_sheet", {"source_name": "mech.pdf"})
    assert is_error and "page_number" in content
    content, is_error = ex.execute("crop_region",
                                   {"rect": [10, 10, 300, 200],
                                    "source_name": "mech.pdf"})
    assert is_error and "page_number" in content
    assert ex.tool_trace == []                     # nothing was ever rendered


def test_garbage_page_number_is_an_error_not_an_exception():
    ex = _executor()
    content, is_error = ex.execute("view_sheet", {"source_name": "fp.pdf",
                                                  "page_number": "abc"})
    assert is_error and "1-based integer" in content


def test_save_failure_blocks_the_image(tmp_path):
    blocked = tmp_path / "evfile"
    blocked.write_text("not a directory")
    ex = _executor(blocked)
    content, is_error = ex.execute("crop_region", {"rect": [10, 10, 300, 200]})
    assert is_error and "evidence could not be saved" in content


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


def test_investigation_upgrades_uncertain_to_verified(tmp_path):
    def responder(kw, _n):
        return _verdict() if _tool_result_turns(kw) else _tool_use()

    client = _LoopClient(responder)
    res, f = _run_one(client, evidence_dir=tmp_path)
    v = f.verification
    assert v.status == "VERIFIED"
    assert v.note.startswith("investigated: ")
    assert v.investigated is True and v.investigation_rounds == 1
    assert len(v.evidence) == 2                    # initial crop + the tool crop
    assert res.verified == 1 and res.investigated == 1
    assert res.input_tokens == 180 and res.output_tokens == 35   # both turns summed
    # The tool_result answered the exact tool_use id, image inside its content.
    final_kw = client.calls[-1]
    tool_turn = final_kw["messages"][-1]
    (block,) = [b for b in tool_turn["content"] if b.get("type") == "tool_result"]
    assert block["tool_use_id"] == "toolu_1"
    assert any(b.get("type") == "image" for b in block["content"])
    # Assistant tool turn was committed before its answer.
    assert final_kw["messages"][-2]["role"] == "assistant"
    assert (tmp_path / "QC-001" / "investigation.json").exists()


def test_multiple_tool_uses_in_one_turn_are_all_answered_together():
    def responder(kw, _n):
        if _tool_result_turns(kw):
            return _verdict("CONTRADICTED", "schedule shows 200 PSI")
        return FakeMessage(
            content=[
                FakeToolUseBlock(name="find_text", input={"query": "PUMP"}, id="t1"),
                FakeToolUseBlock(name="crop_region",
                                 input={"rect": [10, 10, 300, 200]}, id="t2"),
            ],
            stop_reason="tool_use", usage=FakeUsage(),
        )

    client = _LoopClient(responder)
    res, f = _run_one(client)
    assert f.verification.status == "REJECTED" and res.rejected == 1
    answered = [b["tool_use_id"]
                for b in client.calls[-1]["messages"][-1]["content"]
                if isinstance(b, dict) and b.get("type") == "tool_result"]
    assert answered == ["t1", "t2"]                # one user turn, both ids
    assert f.verification.investigation_rounds == 1


def test_budget_cap_forces_a_no_tools_close_and_stays_uncertain():
    def responder(kw, _n):
        if "tools" in kw:
            return _tool_use(block_id=f"toolu_{_n}")
        return FakeMessage(content=[FakeTextBlock(text="I still cannot decide")],
                           stop_reason="end_turn", usage=FakeUsage())

    client = _LoopClient(responder)
    res, f = _run_one(client, max_rounds=2)
    v = f.verification
    assert v.status == "UNCERTAIN"                 # never REJECTED on a cap
    assert "investigated 2 round(s) without conclusion" in v.note
    assert v.investigated is True and v.investigation_rounds == 2
    assert res.budget_capped == 1 and res.still_uncertain == 1
    final_kw = client.calls[-1]
    assert "tools" not in final_kw                 # the forced text-only close
    budget_turn = final_kw["messages"][-1]["content"]
    assert any(isinstance(b, dict) and b.get("type") == "text"
               and "budget exhausted" in b["text"].lower() for b in budget_turn)


def test_garbled_verdict_stays_uncertain_never_rejected():
    client = _LoopClient(lambda kw, n: FakeMessage(
        content=[FakeTextBlock(text="no json at all")], stop_reason="end_turn",
        usage=FakeUsage()))
    res, f = _run_one(client)
    assert f.verification.status == "UNCERTAIN"
    assert f.verification.investigated is True
    assert res.still_uncertain == 1 and res.verified == 0 and res.rejected == 0


def test_genuine_not_visible_conclusion_is_recorded_as_investigated():
    client = _LoopClient(lambda kw, n: _verdict("NOT_VISIBLE", "detail sheet missing"))
    res, f = _run_one(client)
    assert f.verification.status == "UNCERTAIN"
    assert f.verification.note == "investigated: detail sheet missing"
    assert res.still_uncertain == 1


def test_pause_turn_is_resumed():
    def responder(kw, n):
        if n == 1:
            return FakeMessage(content=[FakeTextBlock(text="thinking...")],
                               stop_reason="pause_turn", usage=FakeUsage())
        return _verdict()

    client = _LoopClient(responder)
    res, f = _run_one(client)
    assert f.verification.status == "VERIFIED"
    assert len(client.calls) == 2
    # The partial assistant turn was appended before the resume.
    assert client.calls[-1]["messages"][-1]["role"] == "assistant"


def test_transient_error_is_retried_then_succeeds():
    class _Status429(Exception):
        status_code = 429

    state = {"raised": False}

    def responder(kw, _n):
        if not state["raised"]:
            state["raised"] = True
            raise _Status429("rate limited")
        return _verdict()

    client = _LoopClient(responder)
    res, f = _run_one(client)
    assert f.verification.status == "VERIFIED"
    assert len(client.calls) == 2


def test_fatal_auth_error_stops_the_pass_and_leaves_findings_untouched():
    class _Status401(Exception):
        status_code = 401

    def responder(kw, _n):
        raise _Status401("bad key")

    f1, f2 = _finding(qc_id="QC-001"), _finding(text="other issue", qc_id="QC-002")
    res = investigate_findings(
        [f1, f2], [_Geom(_ref())], client=_LoopClient(responder),
        sleep=lambda *_: None, render_fn=_render_fn,
    )
    assert res.fatal and res.errors
    # Both keep their valid UNCERTAIN verdicts; the second was never attempted.
    assert f1.verification.status == "UNCERTAIN" and not f1.verification.investigated
    assert f2.verification.status == "UNCERTAIN" and not f2.verification.investigated


def test_client_unavailable_leaves_verdicts_untouched(monkeypatch):
    def _boom():
        raise RuntimeError("no API key configured")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _boom)
    f = _finding()
    res = investigate_findings([f], [_Geom(_ref())], client=None,
                               sleep=lambda *_: None, render_fn=_render_fn)
    assert res.errors and res.investigated == 0
    assert f.verification.status == "UNCERTAIN" and not f.verification.investigated


# --------------------------------------------------------------------------- #
# Candidate selection / budgets / config
# --------------------------------------------------------------------------- #


def test_only_anchored_uncertain_findings_are_candidates():
    calls = []

    def responder(kw, n):
        calls.append(kw)
        return _verdict()

    picked = _finding(qc_id="QC-001")
    unanchored = _finding(text="no rect", qc_id="QC-002", rect=None)
    verified = _finding(text="already fine", qc_id="QC-003", status="VERIFIED")
    deterministic = _finding(text="auditor", qc_id="QC-004", status="DETERMINISTIC")
    rejected = _finding(text="was wrong", qc_id="QC-005", status="REJECTED")
    res = investigate_findings(
        [picked, unanchored, verified, deterministic, rejected], [_Geom(_ref())],
        client=_LoopClient(responder), sleep=lambda *_: None, render_fn=_render_fn,
    )
    assert res.investigated == 1 and len(res.per_finding) == 1
    assert res.per_finding[0].qc_id == "QC-001"
    for untouched in (unanchored, verified, deterministic, rejected):
        assert not untouched.verification.investigated


def test_per_run_budget_is_severity_first_and_counts_the_skipped():
    order = []

    def responder(kw, n):
        return _verdict()

    low = _finding(text="minor", sev="low", qc_id="QC-010")
    high = _finding(text="major", sev="high", qc_id="QC-011")
    med = _finding(text="middling", sev="medium", qc_id="QC-012")
    res = investigate_findings(
        [low, high, med], [_Geom(_ref())], client=_LoopClient(responder),
        max_investigations=2, sleep=lambda *_: None, render_fn=_render_fn,
    )
    assert res.investigated == 2 and res.skipped_over_budget == 1
    assert [r.qc_id for r in res.per_finding] == ["QC-011", "QC-012"]
    assert not low.verification.investigated


def test_budget_env_overrides(monkeypatch):
    assert investigation_max_rounds() == 6
    assert investigation_max_findings() == 10
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS", "3")
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_FINDINGS", "1")
    assert investigation_max_rounds() == 3
    assert investigation_max_findings() == 1
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS", "0")
    assert investigation_max_rounds() == 1            # min 1
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS", "junk")
    assert investigation_max_rounds() == 6            # invalid -> default


def test_investigation_model_env_override(monkeypatch):
    assert investigation_model() == "claude-opus-4-8"  # the escalation tier
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MODEL", "claude-sonnet-4-6")
    assert investigation_model() == "claude-sonnet-4-6"


def test_system_prompt_and_tools_ride_every_request():
    def responder(kw, _n):
        return _verdict() if _tool_result_turns(kw) else _tool_use()

    client = _LoopClient(responder)
    _run_one(client)
    for kw in client.calls:
        system = kw["system"]
        text = system if isinstance(system, str) else system[0]["text"]
        assert text == INVESTIGATE_SYSTEM_PROMPT
    names = [t["name"] for t in client.calls[0]["tools"]]
    assert names == ["crop_region", "find_text", "view_sheet"]


def test_verification_serialization_roundtrips_the_new_fields():
    v = Verification(status="VERIFIED", note="investigated: ok",
                     investigated=True, investigation_rounds=3)
    d = v.to_dict()
    assert d["investigated"] is True and d["investigation_rounds"] == 3
    back = Verification.from_dict(d)
    assert back.investigated is True and back.investigation_rounds == 3
    # Old payloads without the keys deserialize to the defaults (additive rule).
    legacy = Verification.from_dict({"status": "UNCERTAIN"})
    assert legacy.investigated is False and legacy.investigation_rounds == 0


# --------------------------------------------------------------------------- #
# Phase C4 — the verdict cache (complete-only admission, deterministic replay)
# --------------------------------------------------------------------------- #


def _confirm_responder(kw, _n):
    return _verdict() if _tool_result_turns(kw) else _tool_use()


def _cached_run(client, cache, tmp_path, *, fingerprint="fp1", max_rounds=6,
                model=None, render_fn=_render_fn):
    f = _finding()
    res = investigate_findings(
        [f], [_Geom(_ref())], client=client, cache=cache, model=model,
        set_fingerprint=fingerprint, max_rounds=max_rounds,
        evidence_dir=tmp_path, sleep=lambda *_: None, render_fn=render_fn,
    )
    return res, f


def test_cache_warm_hit_replays_without_any_api_call(tmp_path):
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    cold_dir, warm_dir = tmp_path / "cold", tmp_path / "warm"
    r1, f1 = _cached_run(_LoopClient(_confirm_responder), cache, cold_dir)
    assert r1.cache_hits == 0 and f1.verification.status == "VERIFIED"

    def _explode(kw, n):
        raise AssertionError("warm run must not call the API")

    r2, f2 = _cached_run(_LoopClient(_explode), cache, warm_dir)
    assert r2.cache_hits == 1 and r2.investigated == 1 and r2.verified == 1
    assert r2.per_finding[0].cached is True
    assert r2.input_tokens == 0 and r2.output_tokens == 0
    # The verdict is byte-identical and the evidence bytes were re-created.
    assert (f2.verification.status, f2.verification.note) == \
        (f1.verification.status, f1.verification.note)
    assert f2.verification.investigated and f2.verification.investigation_rounds == 1
    cold_pngs = sorted(p.read_bytes() for p in cold_dir.rglob("leg-*.png"))
    warm_pngs = sorted(p.read_bytes() for p in warm_dir.rglob("leg-*.png"))
    assert cold_pngs == warm_pngs
    assert [p.name for p in sorted(cold_dir.rglob("leg-*.png"))] == \
        [p.name for p in sorted(warm_dir.rglob("leg-*.png"))]
    assert (warm_dir / "QC-001" / "investigation.json").exists()


def test_cache_never_admits_capped_or_garbled_outcomes(tmp_path):
    from drawing_analyzer.digest_cache import DigestCache

    def _never(kw, _n):
        if "tools" in kw:
            return _tool_use()
        return FakeMessage(content=[FakeTextBlock(text="still unsure")],
                           stop_reason="end_turn", usage=FakeUsage())

    cache = DigestCache(None, persist=False)
    _cached_run(_LoopClient(_never), cache, tmp_path / "a", max_rounds=1)
    assert cache.stats()["size"] == 0                # budget-capped: not stored

    garbled = _LoopClient(lambda kw, n: FakeMessage(
        content=[FakeTextBlock(text="prose only")], stop_reason="end_turn",
        usage=FakeUsage()))
    _cached_run(garbled, cache, tmp_path / "b")
    assert cache.stats()["size"] == 0                # garbled: not stored


def test_cache_sha_mismatch_falls_back_to_a_live_run(tmp_path):
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    _cached_run(_LoopClient(_confirm_responder), cache, tmp_path / "cold")
    # The source "changed" under the same fingerprint (hostile case): the
    # re-render no longer matches the recorded sha → live investigation.
    drifted = lambda pdf_path, page_index, rect, dpi: b"DIFFERENT" + _render_fn(
        pdf_path, page_index, rect, dpi)  # noqa: E731
    live = _LoopClient(_confirm_responder)
    r2, f2 = _cached_run(live, cache, tmp_path / "warm", render_fn=drifted)
    assert r2.cache_hits == 0 and len(live.calls) >= 1
    assert f2.verification.status == "VERIFIED"      # the live run still ran


def test_cache_key_sensitivity(tmp_path):
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    _cached_run(_LoopClient(_confirm_responder), cache, tmp_path / "a")

    def _live_ran(**kw):
        client = _LoopClient(_confirm_responder)
        res, _f = _cached_run(client, cache, tmp_path / "x", **kw)
        return len(client.calls) > 0

    assert not _live_ran()                                   # identical → hit
    assert _live_ran(fingerprint="fp2")                      # set content changed
    assert _live_ran(max_rounds=3)                           # budget rides the key
    assert _live_ran(model="claude-sonnet-4-6")              # model rides the key


def test_cache_disabled_without_a_fingerprint(tmp_path):
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    client = _LoopClient(_confirm_responder)
    _cached_run(client, cache, tmp_path, fingerprint="")
    assert cache.stats()["size"] == 0 and len(client.calls) >= 1


def test_set_content_fingerprint_contract():
    from drawing_analyzer.investigate import set_content_fingerprint

    @dataclass
    class _Doc:
        source_id: str
        content_sha256: str

    a = [_Doc("SRC-0001", "aa"), _Doc("SRC-0002", "bb")]
    fp = set_content_fingerprint(a)
    assert fp and fp == set_content_fingerprint(list(reversed(a)))   # order-free
    assert fp != set_content_fingerprint([_Doc("SRC-0001", "aa"),
                                          _Doc("SRC-0002", "CHANGED")])
    # Unknown content hashes (or no documents) disable caching entirely.
    assert set_content_fingerprint([]) == ""
    assert set_content_fingerprint([_Doc("SRC-0001", "")]) == ""


def test_investigate_findings_never_raises_on_hostile_inputs():
    # No candidates at all; empty sheets; a candidate whose sheet is missing.
    assert investigate_findings([], [], client=None).investigated == 0
    lost = _finding(name="ghost.pdf")
    lost.source_id = "SRC-9999"      # keys on source_id — truly unresolvable
    res = investigate_findings(
        [lost], [_Geom(_ref())], client=_LoopClient(lambda kw, n: _verdict()),
        sleep=lambda *_: None, render_fn=_render_fn,
    )
    assert res.investigated == 0 and res.errors
