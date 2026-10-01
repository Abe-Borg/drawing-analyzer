"""The remaining response consumers read the stop reason first (remediation WP-01.6, D-1).

Before WP-01.6 the review planner, set identity, synthesis, the focus report and
the prose harvest's structuring call never read ``stop_reason``: a reply that
was cut off, refused, ended without a stop reason (N27), handed back a
continuation or named an unknown reason was used and cached whenever its
content parsed (synthesis and the focus report even kept a refusal's
explanation as their text, cached). Verification read only ``max_tokens`` and
``refusal``, so a context-window stop, ``None``, a continuation or an unknown
reason was parsed as a verdict and cached. Measured through the real SDK over
the stub on SDK 1.7.0 and 1.8.0 (identical): the WP-01.6 handoff entry.

The owner's rules (D-1's WP-01.6 note):

- **Every consumer asks** ``core.terminal_outcome.classify_stop_reason``
  **first**, never a second table. A read that is not ``FINISHED`` fails, is
  named, and is cached by none.
- **Each takes its existing failure path, keeping nothing:** the planner and
  identity fail (the critique runs without plan profiles); synthesis and the
  focus report fail with no text shipped and nothing harvested from it, and the
  billed reply is recorded as a FAILED usage attempt (as the planner and
  identity already record theirs); a harvest item takes its degraded verbatim
  entry. A structured-outputs schema never overrides it (plan WP-09 step 6).
- **The wording is the digest's one ladder** (``digest.digest_terminal_error``)
  with a noun per stage; a FINISHED reply that fails its parse keeps each
  stage's own wording.
- **Verification** counts every non-FINISHED kind as "no verdict" under its
  existing ``truncated`` counter; the two pinned notes stay, new notes name the
  kind; D-2 unchanged.
- **The identity corpus** skips an errored sheet's digest text (its
  ``[digest failed: …]`` line and its text-layer windows stay).
- **Old entries:** the synthesis, focus and harvest terms move 1 -> 2; the
  planner, identity and verification keys have no term and are left (recorded
  residuals).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from drawing_analyzer import focus as focus_mod
from drawing_analyzer import prose_harvest as harvest_mod
from drawing_analyzer import synthesis as synthesis_mod
from drawing_analyzer import verify as verify_mod
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import SheetRef
from drawing_analyzer.review_planner import author_review_plan
from drawing_analyzer.set_identity import build_identity_user_text, identify_set
from tests.fixtures import sdk_responses as R
from tests.fixtures.sdk_transport import AnthropicAPIStub

# --------------------------------------------------------------------------- #
# The stop kinds every consumer is held to
# --------------------------------------------------------------------------- #

# name -> (stop_reason, keep the stage's normal content?, the ladder's word)
_NOT_FINISHED = {
    "refusal": ("refusal", True, "refused"),
    "refusal-empty": ("refusal", False, "refused"),
    "max_tokens": ("max_tokens", True, "truncated"),
    "max_tokens-empty": ("max_tokens", False, "empty"),
    "context-window": ("model_context_window_exceeded", True, "truncated"),
    "no-stop-reason": (None, True, "unfinished"),
    "tool_use": ("tool_use", True, "unfinished"),
    "pause_turn": ("pause_turn", True, "unfinished"),
    "compaction": ("compaction", True, "unfinished"),
    "unknown": ("a_reason_no_sdk_names", True, "unfinished"),
}
_KINDS = sorted(_NOT_FINISHED)


def _expected(noun: str, kind: str) -> str:
    stop, _keep, word = _NOT_FINISHED[kind]
    category = ", category='cyber'" if stop == "refusal" else ""
    return f"{word} {noun} (stop_reason={stop!r}{category})"


def _reply(body: str, stop, *, usage: tuple[int, int] = (300, 60)) -> dict:
    """A reply carrying ``body`` (or nothing) that stopped for ``stop``."""
    msg = R.message([R.text(body)] if body else [], stop_reason=stop,
                    usage_=R.usage(input_tokens=usage[0], output_tokens=usage[1]))
    if stop == "refusal":
        msg["stop_details"] = R.refusal_stop_details("cyber", explanation="declined")
    return msg


def _kind_reply(kind: str, body: str) -> dict:
    stop, keep, _word = _NOT_FINISHED[kind]
    return _reply(body if keep else "", stop)


class _Stub:
    """One reply for every request; counts the requests."""

    def __init__(self, reply: dict):
        self.api = AnthropicAPIStub(lambda params: reply)
        self.client = self.api.client()

    @property
    def calls(self) -> int:
        return len(self.api.messages())


def _ref(i: int) -> SheetRef:
    return SheetRef(pdf_path=Path("/tmp/set.pdf"), page_index=i, source_name="set.pdf",
                    page_count=9, source_id="SRC-0001")


def _sheet(i: int, text: str, *, error: str | None = None) -> SheetDigest:
    return SheetDigest(ref=_ref(i), text=text, error=error)


@dataclass
class _Geom:
    ref: SheetRef
    sheet_text: str = ""


_SHEETS = [_sheet(0, "Sheet FP-101 - Fire Protection - Plan\nnotes"),
           _sheet(1, "Sheet M-101 - Mechanical - Plan\nVAV-3 notes")]
_GEOMS = [_Geom(ref=s.ref, sheet_text="PER NFPA 13 2016") for s in _SHEETS]


# --------------------------------------------------------------------------- #
# The review planner
# --------------------------------------------------------------------------- #

_PLANS = "```json\n" + json.dumps({"plans": [{
    "discipline": "Mechanical", "title": "Mechanical QC",
    "items": [{"text": "Flag a scheduled tag never drawn on a plan.", "severity": "medium",
               "refs": []}],
}]}) + "\n```"


def _plan(stub: _Stub, tmp_path: Path):
    return author_review_plan(None, _SHEETS, client=stub.client,
                              cache=DigestCache(tmp_path / "cache.sqlite"))


@pytest.mark.parametrize("kind", _KINDS, ids=_KINDS)
def test_a_plan_the_model_did_not_finish_fails_and_is_not_cached(tmp_path, kind):
    stub = _Stub(_kind_reply(kind, _PLANS))

    res = _plan(stub, tmp_path)

    assert not res.ok and not res.profiles
    assert res.error == _expected("review plan", kind)
    assert (res.input_tokens, res.output_tokens) == (300, 60)      # billed, reported
    _plan(stub, tmp_path)
    assert stub.calls == 2                                          # nothing cached


def test_a_finished_plan_is_used_and_cached(tmp_path):
    stub = _Stub(_reply(_PLANS, "end_turn"))

    assert _plan(stub, tmp_path).ok
    assert _plan(stub, tmp_path).cached and stub.calls == 1


def test_a_finished_unparseable_plan_keeps_its_wording(tmp_path):
    res = _plan(_Stub(_reply("bullet list, no json", "end_turn")), tmp_path)

    assert res.error == "planner reply carried no parseable plans block"


# --------------------------------------------------------------------------- #
# Set identity
# --------------------------------------------------------------------------- #

_IDENTITY = "```json\n" + json.dumps({
    "disciplines": ["Fire Protection"], "jurisdiction": "California, United States",
    "language": "en", "units": "imperial", "confidence": "high",
    "adopted_codes": [], "evidence": [],
}) + "\n```"


def _identify(stub: _Stub, tmp_path: Path):
    return identify_set(_SHEETS, _GEOMS, client=stub.client,
                        cache=DigestCache(tmp_path / "cache.sqlite"))


@pytest.mark.parametrize("kind", _KINDS, ids=_KINDS)
def test_an_identity_the_model_did_not_finish_fails_and_is_not_cached(tmp_path, kind):
    stub = _Stub(_kind_reply(kind, _IDENTITY))

    res = _identify(stub, tmp_path)

    assert not res.ok and res.identity is None
    assert res.error == _expected("identity", kind)
    assert (res.input_tokens, res.output_tokens) == (300, 60)
    _identify(stub, tmp_path)
    assert stub.calls == 2


def test_a_finished_identity_is_used_and_cached(tmp_path):
    stub = _Stub(_reply(_IDENTITY, "end_turn"))

    assert _identify(stub, tmp_path).ok
    assert _identify(stub, tmp_path).cached and stub.calls == 1


def test_a_finished_unparseable_identity_keeps_its_wording(tmp_path):
    res = _identify(_Stub(_reply("total nonsense", "end_turn")), tmp_path)

    assert res.error == "identity reply carried no parseable identity block"


# --------------------------------------------------------------------------- #
# The identity corpus skips an errored sheet's text (the owner's rule)
# --------------------------------------------------------------------------- #

_REFUSAL_TEXT = "I can't help with that request."
_TRUNCATED_PROSE = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves the corri"


@pytest.mark.parametrize("error, text", [
    ("refused digest (stop_reason='refusal', category='cyber')", _REFUSAL_TEXT),
    ("truncated digest (stop_reason='max_tokens')", _TRUNCATED_PROSE),
    ("unfinished digest (stop_reason=None)", _TRUNCATED_PROSE),
], ids=["refused", "truncated", "unfinished"])
def test_the_identity_corpus_skips_an_errored_sheets_text(error, text):
    sheets = [_SHEETS[0], _sheet(1, text, error=error)]
    geoms = [_Geom(ref=sheets[0].ref), _Geom(ref=sheets[1].ref,
                                              sheet_text="M-101 PER NFPA 13 2016 EDITION")]

    corpus, _budget = build_identity_user_text(sheets, geoms)

    assert text not in corpus
    assert f"[digest failed: {error}]" in corpus
    # The PDF's own words are host evidence, not the model's read: they stay.
    assert "TEXT LAYER (verbatim" in corpus and "M-101 PER NFPA 13 2016 EDITION" in corpus
    assert "NFPA 13 2016" in corpus


def test_the_identity_corpus_of_a_clean_set_is_unchanged():
    """PO-01 changes framing and cache identity, while clean source content
    remains exact after decoding its source blocks once."""
    corpus, _budget = build_identity_user_text(_SHEETS, _GEOMS)
    root = ET.fromstring(f"<corpus>{corpus}</corpus>")
    digests = root.findall("sheet_digest")
    metadata = root.findall("sheet_metadata")
    layers = [element.text[1:-1] for element in root.findall("sheet_text_layer")]

    for i, sd in enumerate(_SHEETS, start=1):
        assert metadata[i - 1].text[1:-1] == f"===== Sheet {i}/2: {sd.ref.display_label} ====="
        assert digests[i - 1].text[1:-1] == sd.text.strip()
        assert _GEOMS[i - 1].sheet_text in layers


# --------------------------------------------------------------------------- #
# Synthesis and the focus report
# --------------------------------------------------------------------------- #

_OVERVIEW = "Drawing Set Overview\n\nThe two sheets agree on VAV-3."


def _synthesize(stub: _Stub, tmp_path: Path):
    return synthesis_mod.synthesize_drawing_set(
        _SHEETS, client=stub.client, cache=DigestCache(tmp_path / "cache.sqlite"))


def _focus(stub: _Stub, tmp_path: Path):
    return focus_mod.generate_focus_report(
        _SHEETS, "equipment coordination", client=stub.client,
        cache=DigestCache(tmp_path / "cache.sqlite"))


_PROSE_STAGES = {"synthesis": (_synthesize, "synthesis"),
                 "focus": (_focus, "focus report")}


@pytest.mark.parametrize("kind", _KINDS, ids=_KINDS)
@pytest.mark.parametrize("stage", sorted(_PROSE_STAGES), ids=sorted(_PROSE_STAGES))
def test_prose_the_model_did_not_finish_is_not_kept_or_cached(tmp_path, stage, kind):
    run, noun = _PROSE_STAGES[stage]
    stub = _Stub(_kind_reply(kind, _OVERVIEW))

    res = run(stub, tmp_path)

    assert not res.ok and res.text == ""                          # nothing shipped
    assert res.error == _expected(noun, kind)
    assert (res.input_tokens, res.output_tokens) == (300, 60)
    assert res.replied                                             # billed: a usage attempt
    run(stub, tmp_path)
    assert stub.calls == 2


@pytest.mark.parametrize("stage", sorted(_PROSE_STAGES), ids=sorted(_PROSE_STAGES))
def test_finished_prose_is_kept_and_cached(tmp_path, stage):
    run, _noun = _PROSE_STAGES[stage]
    stub = _Stub(_reply(_OVERVIEW, "end_turn"))

    first = run(stub, tmp_path)
    assert first.ok and first.text == _OVERVIEW and first.replied
    second = run(stub, tmp_path)
    assert second.cached and not second.replied and stub.calls == 1


def test_a_finished_empty_synthesis_keeps_its_wording(tmp_path):
    res = _synthesize(_Stub(_reply("", "end_turn")), tmp_path)

    assert res.error == "empty synthesis result" and res.replied


def test_a_skipped_synthesis_placed_no_call(tmp_path):
    res = synthesis_mod.synthesize_drawing_set([_SHEETS[0]], client=_Stub(_reply("x", "end_turn")).client)

    assert not res.ok and not res.replied


@pytest.mark.parametrize("module, name", [
    (synthesis_mod, "_SYNTHESIS_CACHE_CONTRACT"),
    (focus_mod, "_FOCUS_CACHE_CONTRACT"),
    (harvest_mod, "_HARVEST_CACHE_CONTRACT"),
], ids=["synthesis", "focus", "harvest"])
def test_the_stage_terms_moved_for_the_new_admission(module, name):
    """What an entry may hold changed (a finished read only), and none stores a
    stop reason, so the stage's own term moves (the WP-01.4 precedent; the
    owner's decision): every entry written under 1 misses once."""
    assert getattr(module, name) == 2


class _KeyedCache:
    """A real cache that remembers the keys it stored."""

    def __init__(self, path: Path):
        self.inner = DigestCache(path)
        self.stored: list[str] = []

    def get(self, key):
        return self.inner.get(key)

    def put(self, key, value):
        self.stored.append(key)
        self.inner.put(key, value)


@pytest.mark.parametrize("stage", sorted(_PROSE_STAGES), ids=sorted(_PROSE_STAGES))
def test_an_entry_written_under_contract_1_misses_and_stays_on_disk(tmp_path, stage, monkeypatch):
    module, name = ((synthesis_mod, "_SYNTHESIS_CACHE_CONTRACT") if stage == "synthesis"
                    else (focus_mod, "_FOCUS_CACHE_CONTRACT"))
    call = (synthesis_mod.synthesize_drawing_set if stage == "synthesis"
            else lambda sheets, **kw: focus_mod.generate_focus_report(sheets, "equipment", **kw))
    cache = _KeyedCache(tmp_path / "cache.sqlite")
    # A 1.7.0-era entry: a refusal's explanation, kept and stored under 1.
    with monkeypatch.context() as m:
        m.setattr(module, name, 1)
        old = call(_SHEETS, client=_Stub(_reply(_REFUSAL_TEXT, "end_turn")).client, cache=cache)
    assert old.text == _REFUSAL_TEXT
    [old_key] = cache.stored

    new = _Stub(_reply(_OVERVIEW, "end_turn"))
    res = call(_SHEETS, client=new.client, cache=cache)

    assert new.calls == 1 and res.text == _OVERVIEW and not res.cached
    assert cache.stored[-1] != old_key
    assert cache.get(old_key) is not None                          # never deleted


# --------------------------------------------------------------------------- #
# The prose harvest's structuring call (plan WP-09 step 6)
# --------------------------------------------------------------------------- #


class _Digest:
    def __init__(self, text: str):
        self.ref = SheetRef(pdf_path=Path("/tmp/a.pdf"), page_index=0, source_name="a.pdf",
                            page_count=1)
        self.text = text
        self.error = None


class _HGeom:
    def __init__(self):
        self.ref = SheetRef(pdf_path=Path("/tmp/a.pdf"), page_index=0, source_name="a.pdf",
                            page_count=1)
        self.sheet_text = "DUCT RISER"
        self.words = []
        self.page_width_pt, self.page_height_pt = 3168.0, 2448.0
        self.rows = self.cols = 2
        self.overlap_frac = 0.08


_ITEM = "Duct riser blocks the corridor door."
_FINDING = {"sheet_id": "M-101", "category": "coordination", "severity": "low",
            "text": _ITEM, "source_quote": "", "tile": None, "refs": []}
_FENCED = "```json\n" + json.dumps(_FINDING) + "\n```"
_BARE = json.dumps(_FINDING)


def _harvest(stub: _Stub, tmp_path: Path):
    return harvest_mod.harvest_prose(
        Ledger(), [_Digest(f"**Coordination items**\n- {_ITEM}\n")], [_HGeom()],
        client=stub.client, cache=DigestCache(tmp_path / "cache.sqlite"),
        sleep=lambda *_: None)


@pytest.mark.parametrize("kind", _KINDS, ids=_KINDS)
def test_a_structuring_reply_the_model_did_not_finish_degrades_and_is_not_cached(tmp_path, kind):
    stub = _Stub(_kind_reply(kind, _FENCED))

    res = _harvest(stub, tmp_path)

    assert (res.structured, res.degraded, res.missing) == (0, 1, 0)
    [outcome] = res.outcomes.values()
    assert (outcome.outcome, outcome.call) == ("degraded", "live")
    assert (res.input_tokens, res.output_tokens) == (300, 60)
    _harvest(stub, tmp_path)
    assert stub.calls == 2


@pytest.mark.parametrize("kind", ["max_tokens", "no-stop-reason", "refusal"],
                         ids=["max_tokens", "no-stop-reason", "refusal"])
def test_a_schema_never_overrides_the_stop_reason(tmp_path, kind, monkeypatch):
    """Plan WP-09 step 6: under the structured-outputs contract the reply is
    bare JSON, and it still degrades when the model did not finish."""
    monkeypatch.setenv("DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS", "1")
    monkeypatch.setattr(harvest_mod.STRUCTURED_OUTPUTS, "available", True)
    stub = _Stub(_kind_reply(kind, _BARE))

    res = _harvest(stub, tmp_path)

    body = stub.api.messages()[0]["body"]
    assert "format" in body["output_config"]                       # the schema was sent
    assert (res.structured, res.degraded) == (0, 1)
    _harvest(stub, tmp_path)
    assert stub.calls == 2


@pytest.mark.parametrize("structured", [False, True], ids=["fenced", "structured"])
def test_a_finished_structuring_reply_is_structured_and_cached(tmp_path, structured, monkeypatch):
    if structured:
        monkeypatch.setenv("DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS", "1")
        monkeypatch.setattr(harvest_mod.STRUCTURED_OUTPUTS, "available", True)
    stub = _Stub(_reply(_BARE if structured else _FENCED, "end_turn"))

    assert _harvest(stub, tmp_path).structured == 1
    res = _harvest(stub, tmp_path)
    assert res.structured == 1 and stub.calls == 1


# --------------------------------------------------------------------------- #
# Verification: every kind, onto the classifier, WP-01.1's counters kept
# --------------------------------------------------------------------------- #

_GOOD_VERDICT = json.dumps({"verdict": "CONFIRMED", "note": "seen on the sheet"})

# stop_reason -> the note (the two pinned ones unchanged; the owner's table)
_VERIFY_NOTES = {
    "max_tokens": "no verdict (truncated at max_tokens)",
    "refusal": "no verdict (declined by the model)",
    "model_context_window_exceeded": "no verdict (context window exceeded)",
    None: "no verdict (unfinished: stop_reason=None)",
    "tool_use": "no verdict (unfinished: stop_reason='tool_use')",
    "pause_turn": "no verdict (unfinished: stop_reason='pause_turn')",
    "compaction": "no verdict (unfinished: stop_reason='compaction')",
    "a_reason_no_sdk_names": "no verdict (unfinished: stop_reason='a_reason_no_sdk_names')",
}
_VERIFY_STOPS = list(_VERIFY_NOTES)
_VERIFY_IDS = [str(s) for s in _VERIFY_STOPS]


@pytest.mark.parametrize("stop", _VERIFY_STOPS, ids=_VERIFY_IDS)
def test_a_verdict_the_model_did_not_finish_is_no_verdict(stop):
    resp = _reply(_GOOD_VERDICT, stop)

    assert verify_mod._verdict_from_response(resp) == ("UNCERTAIN", _VERIFY_NOTES[stop], False)
    assert verify_mod._degrade_kind(resp, False) == verify_mod.DEGRADE_TRUNCATED


@pytest.mark.parametrize("stop", ["end_turn", "stop_sequence"], ids=["end_turn", "stop_sequence"])
def test_a_finished_verdict_is_parsed_and_a_garbled_one_is_malformed(stop):
    assert verify_mod._verdict_from_response(_reply(_GOOD_VERDICT, stop)) == (
        "VERIFIED", "seen on the sheet", True)
    garbled = _reply("I think maybe?", stop)
    assert verify_mod._verdict_from_response(garbled) == ("UNCERTAIN", "unparseable verdict", False)
    assert verify_mod._degrade_kind(garbled, False) == verify_mod.DEGRADE_MALFORMED
    assert verify_mod._degrade_kind(_reply(_GOOD_VERDICT, stop), True) is None


# --------------------------------------------------------------------------- #
# End to end: the gauntlet's mini set through the real SDK over the stub
# --------------------------------------------------------------------------- #

pytest.importorskip("pymupdf")

from tests.test_response_shapes import (  # noqa: E402
    _about_m101, _first, _records, _run, _shaped, _statuses, _warm_calls)
from tests.test_sdk_contract import _script, stage_of  # noqa: E402
# The contract tests' autouse fixture: every self-healing latch starts on.
from tests.test_sdk_contract import _fresh_latches  # noqa: E402,F401


def _cut_off(body: dict, params: dict) -> dict:
    """The stage's own reply, cut off at ``max_tokens`` (its content parses)."""
    body["stop_reason"] = "max_tokens"
    return body


# stage -> (the StageResult status, the ctx.errors prefix, the noun, the usage family)
_PIPELINE = {
    "identity": ("FAILED", "Set identity: ", "identity", "identity"),
    "review_plan": ("FAILED", "Review plan: ", "review plan", "review_plan"),
    "synthesis": ("FAILED", "Cross-sheet synthesis: ", "synthesis", "synthesis"),
    "focus": (None, "Focus report: ", "focus report", "focus"),
}


@pytest.mark.parametrize("stage", sorted(_PIPELINE), ids=sorted(_PIPELINE))
def test_a_stage_reply_cut_off_fails_the_stage_and_is_read_again(tmp_path, stage):
    stub = AnthropicAPIStub(_shaped(_script(), _cut_off, stages={stage}))

    ctx = _run(tmp_path, stub)

    status, prefix, noun, family = _PIPELINE[stage]
    if status is not None:
        assert _statuses(ctx)[stage] == status
    assert f"{prefix}truncated {noun} (stop_reason='max_tokens')" in ctx.errors
    # The billed reply is one FAILED usage attempt (synthesis and the focus
    # report recorded nothing for a failed reply before).
    [record] = _records(ctx, family)
    assert record.terminal_status == "FAILED" and record.output_tokens > 0
    if stage == "synthesis":
        assert ctx.synthesis_text == ""
    if stage == "focus":
        assert ctx.focus_report_text == ""
    assert _warm_calls(tmp_path).get(stage, 0) == 1


def test_a_structuring_reply_cut_off_degrades_its_item_and_is_read_again(tmp_path):
    stub = AnthropicAPIStub(_shaped(_script(), _cut_off, stages={"prose_harvest"}))

    ctx = _run(tmp_path, stub)

    assert _statuses(ctx)["prose_harvest"] == "COMPLETE"            # every item accounted for
    assert (ctx.prose_accounting["structured"], ctx.prose_accounting["degraded"]) == (0, 1)
    assert _warm_calls(tmp_path).get("prose_harvest", 0) == 1


@pytest.mark.parametrize("stop", ["model_context_window_exceeded", "tool_use",
                                  "a_reason_no_sdk_names"],
                         ids=["context-window", "tool_use", "unknown"])
def test_a_verdict_reply_that_did_not_finish_is_not_a_judgment(tmp_path, stop):
    """Measured on ``origin/main``: each of these was parsed as a verdict,
    the stage read COMPLETE and the verdict was cached."""
    def shape(body: dict, params: dict) -> dict:
        body["stop_reason"] = stop
        return body

    stub = AnthropicAPIStub(_shaped(_script(), shape, stages={"verification"}))

    ctx = _run(tmp_path, stub)

    [stage] = [s for s in ctx.stage_results if s.stage == "verification"]
    assert stage.status == "FAILED"
    assert "truncated=1" in " ".join(stage.warnings)
    assert _warm_calls(tmp_path).get("verification", 0) == 1


def _refused_m101(body: dict, params: dict) -> dict:
    body["content"] = [R.text(_REFUSAL_TEXT)]
    body["stop_reason"] = "refusal"
    body["stop_details"] = R.refusal_stop_details("cyber", explanation="declined")
    return body


def test_the_identity_request_carries_no_refusal_text(tmp_path):
    stub = AnthropicAPIStub(_shaped(_script(), _refused_m101, stages={"digest"}, when=_about_m101))

    _run(tmp_path, stub)

    [request] = [r["body"] for r in stub.messages() if stage_of(r["body"]) == "identity"]
    corpus = json.dumps(request["messages"])
    assert _REFUSAL_TEXT not in corpus
    assert "[digest failed: refused digest (stop_reason='refusal', category='cyber')]" in corpus


@pytest.mark.parametrize("stage", ["synthesis", "focus", "review_plan"],
                         ids=["synthesis", "focus", "review_plan"])
def test_a_fallback_split_stage_reply_reads_as_one_text(tmp_path, stage):
    """U2 on the streamed set-level stages: a reply split mid-word by a
    ``fallback`` block reads as the text the two models wrote, and is used and
    cached like any finished reply."""
    def split(body: dict, params: dict) -> dict:
        whole = "".join(b["text"] for b in body["content"] if b.get("type") == "text")
        return R.splice_fallback(body, len(whole) // 2, to_model="claude-opus-4-8")

    control = tmp_path / "control"
    control.mkdir()
    served = _run(control, AnthropicAPIStub(_script()._route))
    stub = AnthropicAPIStub(_shaped(_script(), split, stages={stage},
                                    when=_first(lambda p: stage_of(p) == stage)))

    ctx = _run(tmp_path, stub)

    assert _statuses(ctx).get(stage, "COMPLETE") == "COMPLETE"
    assert ctx.synthesis_text == served.synthesis_text
    assert ctx.focus_report_text == served.focus_report_text
    if stage == "review_plan":
        assert ctx.review_plan_markdown == served.review_plan_markdown
    assert _warm_calls(tmp_path).get(stage, 0) == 0
