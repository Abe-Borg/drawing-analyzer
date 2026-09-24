"""Remediation WP-06.1: an uncertain conflict is a low question, a refused item
is counted, and distinct conflicts that quote one string reach the ledger (B6, N2).

**B6.** The cross-QC persona prompt told the model, when unsure that two sheets
conflict, to "lower the severity to `question`". ``question`` is a category;
severity is ``high``, ``medium`` or ``low``, and both validators refuse anything
else. So exactly the items that sentence targeted were dropped, with no counter,
in a stage that read COMPLETE and was cached. The prompt now asks for category
``question`` with severity ``low``. Validation stays strict (plan §7, B6), and
every refused item is counted once, under the first check that refused it, on
both paths (``CrossQCResult.invalid``). The counts are observational: the stage
stays COMPLETE, gains a warning, and the cached result carries them (the owner's
decisions).

**N2.** ``_dedup_findings`` keyed on (primary sheet, category, primary quote,
sorted legs), with no text, so two different conflicts quoting the same strings
on the same sheets became one before the ledger saw them. Now only findings
identical in every field collapse; the ledger decides the rest (the owner's
decision). A re-report phrased apart therefore reaches the ledger twice: the
recorded cost.

Also: a fact whose ``exact_quote`` is only whitespace is dropped and counted
``facts_no_quote``, like an empty one (found by WP-05.1).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from drawing_analyzer import cross_qc as X
from drawing_analyzer.cross_qc import cross_sheet_qc
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import (
    EVIDENCE_TEXT_GROUNDED,
    ConflictLeg,
    Finding,
    SheetGeometry,
    SheetRef,
)
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)

_NOOP = lambda *_a, **_k: None  # noqa: E731
W, H = 792.0, 612.0

# The review's pair (B8, N2): two different issues about one pump, each quoting
# one string on each sheet. Text overlap 0.273, so the ledger keeps them apart.
VALVE = "pump P-1 has no isolation valve on the suction side"
HORSEPOWER = "motor horsepower for P-1 disagrees with the pump schedule"
QUOTE = "PUMP P-1"
M_TEXT = "PUMP P-1 SUCTION PIPING AND VALVES"
E_TEXT = "PUMP P-1 FEEDER 480V"


def _w(x, y, text, w=60, h=12):
    return (float(x), float(y), float(x + w), float(y + h), text, 0, 0, 0)


def _geom(source, sid, body):
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source,
                   page_count=1, source_id=f"SRC-{Path(source).stem}")
    return SheetGeometry(
        ref=ref, page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=[_w(W - 300, H - 160, sid)], sheet_text=f"{sid} {body}",
    )


def _digest(source):
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source,
                   page_count=1, source_id=f"SRC-{Path(source).stem}")
    return SheetDigest(ref=ref, text="Sheet - Plan\nPump room.")


def _pair_set():
    """Two sheets, M-101 then E-101, both printing ``PUMP P-1``."""
    return ([_digest("m.pdf"), _digest("e.pdf")],
            [_geom("m.pdf", "M-101", M_TEXT), _geom("e.pdf", "E-101", E_TEXT)])


def _item(text=VALVE, *, severity="high", category="conflict", handles=False,
          quote=QUOTE, leg_quote=QUOTE, **extra):
    """One cross-QC item, by sheet id (whole-set) or by handle (map/reconcile)."""
    key = "sheet_handle" if handles else "sheet_id"
    primary, leg = ("S001", "S002") if handles else ("M-101", "E-101")
    return {key: primary, "category": category, "severity": severity, "text": text,
            "source_quote": quote, "also_on": [{key: leg, "source_quote": leg_quote}],
            **extra}


def _fenced(obj):
    return "```json\n" + json.dumps(obj) + "\n```"


class _Cross(BetaClientMixin):
    """Routes cross-QC calls by their own system prompts: whole-set, map, reconcile.

    Each script is a findings list, a response object, or a callable of the
    request body. The routing reads the module's prompts, so a prompt edit keeps
    this fake in step (never a hardcoded sentence).
    """

    def __init__(self, *, whole=None, map_=None, reconcile=None):
        self.scripts = {"whole": whole, "map": map_, "reconcile": reconcile}
        self.calls = {"whole": 0, "map": 0, "reconcile": 0}
        self.bodies = {"whole": [], "map": [], "reconcile": []}
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                body = kw["messages"][0]["content"][0]["text"]
                if system == X.CROSS_QC_RECONCILE_SYSTEM_PROMPT:
                    kind = "reconcile"
                elif system == X.cross_qc_map_system_prompt():
                    kind = "map"
                elif system == X.cross_qc_system_prompt():
                    kind = "whole"
                else:
                    raise AssertionError(f"unexpected system prompt {system[:50]!r}")
                outer.calls[kind] += 1
                outer.bodies[kind].append(body)
                script = outer.scripts[kind]
                if callable(script):
                    script = script(body)
                if script is None:
                    script = []
                obj = script if isinstance(script, dict) else {"findings": script}
                return FakeMessage(
                    content=[FakeTextBlock(text=_fenced({"claims": [], **obj}))],
                    usage=FakeUsage(input_tokens=100, output_tokens=20),
                )

        self.messages = _Msgs()


def _facts_for_every_handle(quote=QUOTE):
    """A map script: one grounded fact per sheet handle in the shard."""
    def script(body):
        return {"findings": [], "facts": [
            {"sheet_handle": h, "entity_or_tag": "P-1", "attribute": "pump",
             "value": "v", "exact_quote": quote}
            for h in re.findall(r"SHEET (S\d+)", body)
        ]}
    return script


def _whole(findings, *, cache=None, sets=None):
    sheets, geoms = sets or _pair_set()
    client = _Cross(whole=findings)
    res = cross_sheet_qc(sheets, geoms, client=client, cache=cache,
                         max_retries=0, sleep=_NOOP)
    return res, client


def _sharded(monkeypatch, *, reconcile=None, map_=None, sets=None, cache=None):
    """The map → reconcile path on the two-sheet set (one sheet per shard)."""
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
    sheets, geoms = sets or _pair_set()
    client = _Cross(map_=map_ or _facts_for_every_handle(), reconcile=reconcile)
    res = cross_sheet_qc(sheets, geoms, client=client, cache=cache,
                         max_retries=0, sleep=_NOOP)
    return res, client


def _ledger_entries(findings):
    ledger = Ledger()
    ledger.add(copy.deepcopy(findings), "cross_qc")
    return ledger.entries


# --------------------------------------------------------------------------- #
# B6: the prompt asks for a category and a severity the validators accept
# --------------------------------------------------------------------------- #


def _backticked_after(word: str, text: str) -> list[str]:
    """Every backticked value the prompt pairs with ``word`` ("severity to `x`")."""
    flat = " ".join(text.split())
    return re.findall(rf"\b{word}\b(?:\s+(?:to|of|is|as))?\s+`([^`]+)`", flat)


@pytest.mark.parametrize("which", ["whole", "map"])
def test_b6_the_persona_names_only_valid_severities_and_categories(which):
    prompt = (X.cross_qc_system_prompt() if which == "whole"
              else X.cross_qc_map_system_prompt())
    from drawing_analyzer.digest import _FINDING_SEVERITIES, _MODEL_FINDING_CATEGORIES

    severities = _backticked_after("severity", prompt)
    categories = _backticked_after("category", prompt)
    assert severities, "the uncertain-conflict sentence names a severity"
    assert set(severities) <= _FINDING_SEVERITIES, severities
    assert set(categories) <= _MODEL_FINDING_CATEGORIES, categories


@pytest.mark.parametrize("which", ["whole", "map"])
def test_b6_an_uncertain_conflict_is_a_low_question(which):
    # One edit to the shared persona fixes both prompts that carry it.
    prompt = " ".join((X.cross_qc_system_prompt() if which == "whole"
                       else X.cross_qc_map_system_prompt()).split())
    assert "category `question` and severity `low`" in prompt
    assert "severity to `question`" not in prompt


def test_b6_the_reconcile_prompt_never_asked_for_an_invalid_severity():
    # It does not carry the persona, and it never had the sentence.
    from drawing_analyzer.digest import _FINDING_SEVERITIES

    sev = _backticked_after("severity", X.CROSS_QC_RECONCILE_SYSTEM_PROMPT)
    assert set(sev) <= _FINDING_SEVERITIES


# --------------------------------------------------------------------------- #
# B6: strict validation, every refusal counted once, on both paths
# --------------------------------------------------------------------------- #

# (id, item overrides or a non-object, the reason it is refused or "" if kept)
_ITEMS = [
    ("valid", {}, ""),
    ("question-low", {"category": "question", "severity": "low"}, ""),
    ("QUESTION-Low", {"category": "QUESTION", "severity": "Low"}, ""),
    ("sev-question", {"severity": "question"}, "findings_invalid_severity"),
    ("sev-Question", {"severity": "Question"}, "findings_invalid_severity"),
    ("sev-critical", {"severity": "critical"}, "findings_invalid_severity"),
    ("sev-missing", {"severity": None}, "findings_invalid_severity"),
    ("cat-clash", {"category": "clash"}, "findings_invalid_category"),
    ("cat-reference", {"category": "reference"}, "findings_invalid_category"),
    ("cat-and-sev", {"category": "clash", "severity": "question"},
     "findings_invalid_category"),
    ("text-empty", {"text": ""}, "findings_invalid_text"),
    ("text-blank", {"text": "  \n\t "}, "findings_invalid_text"),
    ("text-number", {"text": 42}, "findings_invalid_text"),
    ("text-and-sev", {"text": "", "severity": "question"}, "findings_invalid_severity"),
    ("not-object", "a string where an object belongs", "findings_not_object"),
    ("list", ["M-101", "E-101"], "findings_not_object"),
]


def _build(overrides, *, handles):
    if not isinstance(overrides, dict):
        return copy.deepcopy(overrides)
    item = _item(handles=handles)
    for k, v in overrides.items():
        if v is None:
            item.pop(k, None)
        else:
            item[k] = v
    return item


def _validators():
    sheets, geoms = _pair_set()
    gm, ge = geoms
    sheet_map = {X._norm_id("M-101"): gm, X._norm_id("E-101"): ge}
    entry_by_handle = {"S001": ("M-101", gm), "S002": ("E-101", ge)}
    return sheet_map, entry_by_handle


@pytest.mark.parametrize("overrides,reason", [(o, r) for _i, o, r in _ITEMS],
                         ids=[i for i, _o, _r in _ITEMS])
def test_b6_each_refusal_is_counted_once_under_its_first_reason(overrides, reason):
    sheet_map, entry_by_handle = _validators()
    whole = X.CrossQCInvalidCounts()
    sharded = X.CrossQCInvalidCounts()

    kept_whole = X._validate_cross_item(_build(overrides, handles=False), sheet_map, whole)
    kept_sharded = X._finding_from_handles(
        _build(overrides, handles=True), entry_by_handle, X.CrossQCDiscardCounts(),
        invalid=sharded)

    assert X._invalid_field(_build(overrides, handles=False)) == reason
    for counts, kept in ((whole, kept_whole), (sharded, kept_sharded)):
        if reason:
            assert kept is None, "validation stays strict"
            assert counts.to_dict() == {
                name: int(name == reason) for name in counts.to_dict()}
            assert counts.total == 1, "one refused item, counted once"
        else:
            assert kept is not None
            assert counts.total == 0


def test_b6_the_same_item_binds_alike_on_both_validators():
    # Whole-set / sharded equivalence is testable only at parser level (plan
    # WP-06 notes): the same item gives the same binding and the same counts.
    # The evidence state is not compared: the whole-set path grounds nothing
    # yet (U8), which is WP-06.2's.
    sheet_map, entry_by_handle = _validators()

    def _bound(f):
        return (f.source_name, f.page_index, f.sheet_id, f.category, f.severity,
                f.text, f.source_quote, f.recommended_action, f.refs, f.tile,
                [(l.source_name, l.sheet_id, l.source_quote, l.tile) for l in f.also_on])

    for _id, overrides, reason in _ITEMS:
        extra = {"recommended_action": "Confirm the pump.", "refs": ["NEC 430"],
                 "tile_label": "r1c2"}
        whole_item = _build(overrides, handles=False)
        shard_item = _build(overrides, handles=True)
        if isinstance(whole_item, dict):
            whole_item.update(extra)
            shard_item.update(extra)
        a_counts, b_counts = X.CrossQCInvalidCounts(), X.CrossQCInvalidCounts()
        a = X._validate_cross_item(whole_item, sheet_map, a_counts)
        b = X._finding_from_handles(shard_item, entry_by_handle, None, invalid=b_counts)
        assert (a is None) == (b is None) == bool(reason), _id
        assert a_counts.to_dict() == b_counts.to_dict(), _id
        if a is not None:
            assert _bound(a) == _bound(b), _id


def test_b6_an_uncertain_conflict_is_kept_on_the_whole_set_path():
    res, client = _whole([_item(category="question", severity="low")])
    assert client.calls["whole"] == 1
    assert len(res.findings) == 1
    f = res.findings[0]
    assert (f.category, f.severity) == ("question", "low")
    assert [leg.sheet_id for leg in f.also_on] == ["E-101"]


def test_b6_an_uncertain_conflict_is_kept_on_the_sharded_path(monkeypatch):
    res, client = _sharded(
        monkeypatch, reconcile=[_item(category="question", severity="low", handles=True)])
    assert client.calls == {"whole": 0, "map": 2, "reconcile": 1}
    assert len(res.findings) == 1
    assert (res.findings[0].category, res.findings[0].severity) == ("question", "low")


def test_b6_a_refused_item_is_counted_on_the_whole_set_path():
    res, _ = _whole([_item(severity="question"), _item(HORSEPOWER, category="clash")])
    assert res.findings == []
    assert res.invalid is not None, "recorded on the whole-set path too"
    assert res.invalid.findings_invalid_severity == 1
    assert res.invalid.findings_invalid_category == 1
    assert res.invalid.total == 2
    # Observational (the owner's decision): the stage's own completeness is
    # unchanged, and the grounding counters keep their meaning ("not measured").
    assert res.complete is True and res.error is None
    assert res.discards is None


def test_b6_refusals_are_counted_on_the_map_and_reconcile_calls(monkeypatch):
    def map_script(body):
        obj = _facts_for_every_handle()(body)
        obj["findings"] = [_item(severity="question", handles=True), "junk"]
        return obj

    res, client = _sharded(
        monkeypatch, map_=map_script,
        reconcile=[_item(severity="question", handles=True),
                   _item("", handles=True)])
    assert client.calls["map"] == 2 and client.calls["reconcile"] == 1
    # Two shards x (one bad severity + one non-object), plus the reconcile call.
    assert res.invalid.to_dict() == {
        "findings_not_object": 2,
        "findings_invalid_category": 0,
        "findings_invalid_severity": 3,
        "findings_invalid_text": 1,
    }
    assert res.findings == []
    assert res.complete is True
    assert res.discards is not None      # the sharded path still measures grounding


def test_b6_reconcile_pair_calls_fold_their_counts(monkeypatch):
    # Facts past one reconcile call are compared over every pair of half-cap
    # groups; each pair call's counts fold into the run total.
    monkeypatch.setattr(X, "MAX_FACTS_PER_RECONCILE", 2)      # half = 1 fact a group
    sheets, geoms = _pair_set()
    sheets.append(_digest("f.pdf"))
    geoms.append(_geom("f.pdf", "FP-101", "PUMP P-1 FIRE PUMP"))
    res, client = _sharded(
        monkeypatch, sets=(sheets, geoms),
        reconcile=[_item(severity="question", handles=True)])
    assert client.calls["reconcile"] == 3                      # C(3, 2)
    assert res.invalid.findings_invalid_severity == 3
    assert res.invalid.total == 3


def test_b6_a_findings_value_that_is_no_list_is_not_counted_per_character(monkeypatch):
    # A map call that answers "findings": "none" beside its facts has no
    # items. Iterating the string would count four refused "items".
    def map_script(body):
        obj = _facts_for_every_handle()(body)
        obj["findings"] = "none"
        return obj

    res, _ = _sharded(monkeypatch, map_=map_script, reconcile=[])
    assert res.invalid.total == 0
    assert res.facts_collected == 2


def test_b6_a_clean_empty_response_is_not_a_validation_loss():
    empty, _ = _whole([])
    lossy, _ = _whole([_item(severity="question")])
    assert empty.findings == [] == lossy.findings
    assert empty.invalid.total == 0 and empty.invalid.note() == ""
    assert lossy.invalid.total == 1 and lossy.invalid.note() != ""


def test_b6_an_unplaceable_item_is_not_an_invalid_one():
    # Valid fields, but only one sheet resolves: dropped as before (binding is
    # WP-06.2's), never counted as a validation loss.
    res, _ = _whole([_item(also_on=[{"sheet_id": "Z-999", "source_quote": "x"}])])
    assert res.findings == []
    assert res.invalid.total == 0


def test_b6_the_counts_are_observational_and_cached_with_the_result():
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    cold, client = _whole([_item(severity="question"), _item(HORSEPOWER)], cache=cache)
    sheets, geoms = _pair_set()
    warm = cross_sheet_qc(sheets, geoms, client=client, cache=cache,
                          max_retries=0, sleep=_NOOP)
    assert cold.complete and cold.cached is False
    assert warm.cached is True and client.calls["whole"] == 1
    assert warm.invalid is not None
    assert warm.invalid.to_dict() == cold.invalid.to_dict()
    assert warm.invalid.findings_invalid_severity == 1
    assert [f.text for f in warm.findings] == [HORSEPOWER]


def test_b6_an_older_cached_result_reads_back_as_not_recorded():
    # Additive serialization: an entry without the field is "not recorded",
    # never an all-zero "nothing was refused".
    payload = {"findings": [], "claims": [], "complete": True}
    res = X._cross_qc_from_cache(payload)
    assert res is not None and res.invalid is None


def test_b6_the_counts_round_trip_and_carry_no_text():
    counts = X.CrossQCInvalidCounts()
    counts.bump("findings_invalid_severity")
    counts.bump("findings_invalid_severity")
    other = X.CrossQCInvalidCounts(findings_not_object=1)
    counts.merge(other)
    payload = counts.to_dict()
    assert all(isinstance(v, int) for v in payload.values())
    assert X.CrossQCInvalidCounts.from_dict(payload) == counts
    assert X.CrossQCInvalidCounts.from_dict({"gone": 3, "findings_not_object": 2}) \
        == X.CrossQCInvalidCounts(findings_not_object=2)
    assert counts.total == 3
    note = counts.note()
    assert "invalid field" in note and "severity 2" in note and "not an object 1" in note


def test_b6_the_log_separates_refused_from_unplaceable_items(caplog):
    from drawing_analyzer import diagnostics

    with caplog.at_level("INFO", logger=diagnostics.LOGGER_NAME):
        _whole([_item(severity="question"),
                _item(also_on=[{"sheet_id": "Z-999", "source_quote": "x"}])])
    text = "\n".join(caplog.messages)
    assert "refused" in text and "invalid field" in text
    assert "unplaceable" in text


# --------------------------------------------------------------------------- #
# N2: only identical findings collapse; the ledger decides the rest
# --------------------------------------------------------------------------- #


def test_n2_the_acceptance_pair_survives_the_whole_set_path():
    res, _ = _whole([_item(VALVE), _item(HORSEPOWER)])
    assert [f.text for f in res.findings] == [VALVE, HORSEPOWER]
    entries = _ledger_entries(res.findings)
    assert sorted(e.text for e in entries) == sorted([VALVE, HORSEPOWER])


def test_n2_the_acceptance_pair_survives_the_sharded_path(monkeypatch):
    res, _ = _sharded(monkeypatch, reconcile=[_item(VALVE, handles=True),
                                             _item(HORSEPOWER, handles=True)])
    assert [f.text for f in res.findings] == [VALVE, HORSEPOWER]
    assert all(f.evidence_state == EVIDENCE_TEXT_GROUNDED for f in res.findings)
    assert len(_ledger_entries(res.findings)) == 2


def test_n2_the_pair_survives_when_both_texts_name_the_sheets():
    # The prompt asks every text to name the sheets (overlap 0.353 here).
    valve = "M-101 shows pump P-1 with no isolation valve on the suction side; E-101 assumes one."
    hp = "Motor horsepower for P-1 on E-101 disagrees with the pump schedule on M-101."
    res, _ = _whole([_item(valve), _item(hp)])
    assert len(res.findings) == 2
    assert len(_ledger_entries(res.findings)) == 2


def test_n2_a_shard_and_the_reconciler_reporting_one_finding_collapse(monkeypatch):
    # One conflict reported identically by a shard and by the reconciler: the
    # copies are identical in every field, so they are one finding.
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 2)
    sheets, geoms = _pair_set()
    sheets.insert(1, _digest("m2.pdf"))
    geoms.insert(1, _geom("m2.pdf", "M-102", "PUMP P-1 DISCHARGE"))
    within = _item(VALVE, handles=True)              # S001 = M-101, S002 = M-102

    def map_script(body):
        obj = _facts_for_every_handle()(body)
        obj["findings"] = [within] if "SHEET S001" in body else []
        return obj

    client = _Cross(map_=map_script, reconcile=[within])
    res = cross_sheet_qc(sheets, geoms, client=client, max_retries=0, sleep=_NOOP)
    assert client.calls["map"] == 2 and client.calls["reconcile"] == 1
    assert [f.text for f in res.findings] == [VALVE]
    assert len(_ledger_entries(res.findings)) == 1


def test_n2_pair_calls_reporting_one_finding_identically_collapse(monkeypatch):
    monkeypatch.setattr(X, "MAX_FACTS_PER_RECONCILE", 2)
    sheets, geoms = _pair_set()
    sheets.append(_digest("f.pdf"))
    geoms.append(_geom("f.pdf", "FP-101", "PUMP P-1 FIRE PUMP"))
    res, client = _sharded(monkeypatch, sets=(sheets, geoms),
                           reconcile=[_item(HORSEPOWER, handles=True)])
    assert client.calls["reconcile"] == 3
    assert [f.text for f in res.findings] == [HORSEPOWER]


def test_n2_a_re_report_phrased_apart_reaches_the_ledger_twice(monkeypatch):
    # The recorded cost of handing the ledger what it must judge: a re-report
    # of one conflict in other words (overlap 0.118) is not identical, and the
    # ledger's text rule keeps it apart. Destroying it would need a same-claim
    # predicate, which no host-side rule has (WP-06.4, U11).
    terse = "Pump P-1 motor is 10 HP on M-101 but 15 HP on E-101."
    apart = "Horsepower mismatch between the mechanical schedule and the electrical feeder for P-1."
    res, _ = _whole([_item(terse), _item(apart)])
    assert len(res.findings) == 2
    assert len(_ledger_entries(res.findings)) == 2


def test_n2_a_re_report_phrased_close_folds_in_the_ledger():
    terse = "Pump P-1 motor is 10 HP on M-101 but 15 HP on E-101."
    close = "Pump P-1 motor is 10 HP on M-101 while E-101 shows 15 HP."
    res, _ = _whole([_item(terse), _item(close)])
    assert len(res.findings) == 2
    assert len(_ledger_entries(res.findings)) == 1


def test_n2_a_later_copy_that_differs_keeps_what_it_adds():
    # Same text, but the second report is more severe and carries the action.
    # Today's key kept the first and destroyed both; the ledger's merge keeps
    # the most severe severity and the representative's action.
    first = _item(HORSEPOWER, severity="low")
    second = _item(HORSEPOWER, severity="high", recommended_action="Confirm the motor size.")
    res, _ = _whole([first, second])
    assert len(res.findings) == 2, "not identical, so not collapsed"
    (entry,) = _ledger_entries(res.findings)
    assert entry.severity == "high"
    assert entry.recommended_action == "Confirm the motor size."


def test_n2_only_findings_identical_in_every_field_collapse():
    def f(**kw):
        base = dict(sheet_id="M-101", source_name="m.pdf", page_index=0,
                    category="conflict", severity="high", text=HORSEPOWER,
                    source_quote=QUOTE,
                    also_on=[ConflictLeg(sheet_id="E-101", source_name="e.pdf",
                                         page_index=0, source_quote=QUOTE)])
        base.update(kw)
        return Finding(**base)

    same = [f(), f(), f()]
    assert len(X._drop_exact_repeats(same)) == 1
    variants = [f(), f(tile=[0, 1]), f(refs=["NEC"]), f(severity="low"),
                f(recommended_action="Fix."), f(text=VALVE),
                f(also_on=[ConflictLeg(sheet_id="E-101", source_name="e.pdf",
                                       page_index=0, source_quote="PUMP P-1 FEEDER")])]
    kept = X._drop_exact_repeats(variants)
    assert kept == variants, "every differing report reaches the ledger, in order"
    # The first of each identical run is the one kept (deterministic, I-7).
    mixed = [variants[0], variants[1], same[1], variants[1]]
    assert X._drop_exact_repeats(mixed) == [variants[0], variants[1]]
    assert X._drop_exact_repeats(mixed)[0] is variants[0]


def test_recorded_limit_n30_a_terse_same_pair_conflict_folds_in_the_ledger():
    """N30 (WP-03.5): the ledger's quote branch folds two different issues.

    Cross-QC now hands both to the ledger (N2's half is fixed here). But two
    terse texts that each name both sheets share the pump and sheet tokens
    (overlap 0.462), and with one quote the ledger folds them: the isolation
    valve issue is lost. Measured on a synthetic corpus of twelve distinct
    P-1 issues between M-101 and E-101: 0 of 66 pairs fold without sheet names,
    4 of 66 with them in full sentences, and 45 of 66 in one terse clause each.
    WP-03.5 keeps the loser's text as an observation; flip this then.
    """
    valve = "Pump P-1 has an isolation valve on M-101 that E-101 omits."
    hp = "Pump P-1 motor is 10 HP on M-101 but 15 HP on E-101."
    res, _ = _whole([_item(valve), _item(hp)])
    assert len(res.findings) == 2, "cross-QC keeps both (N2)"
    assert len(_ledger_entries(res.findings)) == 1, "the ledger folds them (N30)"


# --------------------------------------------------------------------------- #
# The whitespace-only fact quote (found by WP-05.1)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("blank", ["   ", "\t\n", "\u00a0 "], ids=["spaces", "tab-nl", "nbsp"])
def test_a_whitespace_only_fact_quote_is_no_quote(blank):
    _sheet_map, entry_by_handle = _validators()
    counts = X.CrossQCDiscardCounts()
    facts = X._parse_facts({"facts": [
        {"sheet_handle": "S001", "exact_quote": blank, "tile_label": "r1c1"},
        {"sheet_handle": "S002", "exact_quote": QUOTE},
    ]}, entry_by_handle, {}, counts)
    assert [f.sheet_handle for f in facts] == ["S002"]
    assert counts.facts_no_quote == 1
    assert counts.facts_admitted_no_text_evidence == 0
    assert counts.facts_accepted == 1


def test_a_whitespace_only_fact_never_reaches_the_reconciler(monkeypatch):
    def map_script(body):
        (handle,) = re.findall(r"SHEET (S\d+)", body)
        quote = "   " if handle == "S001" else QUOTE
        return {"findings": [], "facts": [
            {"sheet_handle": handle, "entity_or_tag": "P-1", "attribute": "pump",
             "value": "v", "exact_quote": quote}]}

    res, client = _sharded(monkeypatch, map_=map_script, reconcile=[])
    assert client.calls["reconcile"] == 1
    (body,) = client.bodies["reconcile"]
    assert "S001 |" not in body and "S002 |" in body
    assert res.facts_collected == 1
    assert res.discards.facts_no_quote == 1


# --------------------------------------------------------------------------- #
# Cache contract
# --------------------------------------------------------------------------- #


def test_the_cross_qc_contract_moved_for_the_new_host_binding():
    # Remediation WP-06.1 changes what is stored for byte-identical request
    # inputs: distinct conflicts that share a quote are no longer destroyed,
    # a whitespace-only fact quote is no longer sent to the reconciler, and the
    # result carries its refused-item counts. The persona edit re-keys every
    # entry through the prompt text as well; that is a second change with its
    # own mechanism, not a bump and a key term for one change (plan §2 rule 15).
    assert X._CROSS_QC_CACHE_CONTRACT == 6
    _sheets, geoms = _pair_set()
    entries = [("M-101", "digest", "text", geoms[0])]
    current = X._cross_qc_cache_key(entries, model="claude-opus-5", preamble="")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(X, "_CROSS_QC_CACHE_CONTRACT", 5)
        previous = X._cross_qc_cache_key(entries, model="claude-opus-5", preamble="")
    assert current != previous


# --------------------------------------------------------------------------- #
# Through the pipeline: the stage record, the exports, verification, markup
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import _SEVERITY_LAYER_NAMES  # noqa: E402
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.export import write_drawing_export  # noqa: E402
from drawing_analyzer.investigate import INVESTIGATE_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402


def _mkpdf(path, body, sid):
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((80, 120), body)
    page.insert_text((650, 560), sid)
    doc.save(str(path))
    doc.close()
    return path


class _Pipeline(BetaClientMixin):
    """Digest + cross-QC (whole-set or sharded) + dual-crop verify."""

    def __init__(self, *, cross=None, reconcile=None, verdict="CONFIRMED"):
        self.cross = cross or []
        self.reconcile = reconcile or []
        self.verdict = verdict
        self.cross_calls = 0
        self.verify_images = []
        self.investigate_calls = 0
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                if isinstance(system, list):         # content blocks (cache_control)
                    system = "".join(b.get("text", "") for b in system
                                     if isinstance(b, dict))
                body = kw["messages"][0]["content"]
                if system == VERIFY_SYSTEM_PROMPT:
                    outer.verify_images.append(sum(
                        1 for b in body if isinstance(b, dict) and b.get("type") == "image"))
                    text = '{"verdict":"%s","note":"x"}' % outer.verdict
                elif system == INVESTIGATE_SYSTEM_PROMPT:
                    outer.investigate_calls += 1
                    text = '{"verdict":"NOT_VISIBLE","note":"cannot settle"}'
                elif system == X.CROSS_QC_RECONCILE_SYSTEM_PROMPT:
                    outer.cross_calls += 1
                    text = _fenced({"findings": outer.reconcile, "claims": []})
                elif system == X.cross_qc_map_system_prompt():
                    outer.cross_calls += 1
                    text = _fenced(_facts_for_every_handle()(body[0]["text"]))
                elif system.startswith(X.CROSS_QC_SYSTEM_PROMPT):
                    outer.cross_calls += 1
                    text = _fenced({"findings": outer.cross, "claims": []})
                elif system.startswith(DIGEST_SYSTEM_PROMPT):
                    text = "Sheet - Plan\nPump room.\n\n" + _fenced({"findings": []})
                else:
                    text = "ok"
                return FakeMessage(content=[FakeTextBlock(text=text)],
                                   usage=FakeUsage(input_tokens=100, output_tokens=20))

        self.messages = _Msgs()


def _pdfs(tmp_path):
    return [_mkpdf(tmp_path / "M-101.pdf", M_TEXT, "M-101"),
            _mkpdf(tmp_path / "E-101.pdf", E_TEXT, "E-101")]


def _cross_stage(ctx):
    (stage,) = [s for s in ctx.stage_results if s.stage == "cross_qc"]
    return stage


def test_pipeline_a_refused_item_is_a_stage_warning_in_run_log_and_manifest(tmp_path):
    client = _Pipeline(cross=[_item(severity="question"), _item(HORSEPOWER)])
    ctx = extract_drawing_context(
        _pdfs(tmp_path), client=client, rows=2, cols=2, cross_qc=True,
        qc_work_dir=tmp_path / "qc")
    stage = _cross_stage(ctx)
    assert stage.status == "COMPLETE", "observational: the loss holds nothing back"
    assert stage.items_out == 1
    (warning,) = stage.warnings
    assert "invalid field" in warning and "severity 1" in warning
    assert ctx.cross_qc_invalid["findings_invalid_severity"] == 1
    assert ctx.cross_qc_discards == {}, "the whole-set path measures no grounding"

    export = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101", "E-101"])
    log = (export / "run.log").read_text(encoding="utf-8")
    manifest = json.loads((export / "run_manifest.json").read_text(encoding="utf-8"))
    # The stage table's row (its note is the warning) and the STAGE_END event.
    (row,) = [line for line in log.splitlines() if line.split()[:2] == ["cross_qc", "COMPLETE"]]
    assert "invalid field" in row
    (end,) = [line for line in log.splitlines() if "STAGE_END" in line and "cross_qc" in line]
    assert "invalid field" in end
    assert manifest["cross_qc_invalid"]["findings_invalid_severity"] == 1
    (m_stage,) = [s for s in manifest["stages"] if s["stage"] == "cross_qc"]
    assert m_stage["status"] == "COMPLETE" and m_stage["warnings"] == [warning]


def test_pipeline_a_clean_run_records_no_loss_and_no_warning(tmp_path):
    client = _Pipeline(cross=[_item(HORSEPOWER)])
    ctx = extract_drawing_context(
        _pdfs(tmp_path), client=client, rows=2, cols=2, cross_qc=True,
        qc_work_dir=tmp_path / "qc")
    assert _cross_stage(ctx).warnings == []
    assert ctx.cross_qc_invalid and sum(ctx.cross_qc_invalid.values()) == 0


def test_pipeline_without_cross_qc_records_nothing(tmp_path):
    ctx = extract_drawing_context(
        _pdfs(tmp_path), client=_Pipeline(), rows=2, cols=2, cross_qc=False,
        qc_work_dir=tmp_path / "qc")
    assert ctx.cross_qc_invalid == {}, "not recorded, never a zeroed record"


def _cross_entries(ctx):
    return [f for f in ctx.findings if f.also_on]


@pytest.mark.parametrize("path", ["whole", "sharded"])
def test_pipeline_the_acceptance_pair_reaches_verification_markup_and_exports(
        tmp_path, monkeypatch, path):
    if path == "sharded":
        monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
        client = _Pipeline(reconcile=[_item(VALVE, handles=True),
                                      _item(HORSEPOWER, handles=True)])
    else:
        client = _Pipeline(cross=[_item(VALVE), _item(HORSEPOWER)])
    ctx = extract_drawing_context(
        _pdfs(tmp_path), client=client, rows=2, cols=2, cross_qc=True,
        qc_markups=True, qc_work_dir=tmp_path / "qc")

    entries = _cross_entries(ctx)
    assert sorted(f.text for f in entries) == sorted([VALVE, HORSEPOWER])
    assert len({f.qc_id for f in entries}) == 2
    # Each is its own dual-crop verification call (a crop per sheet): new paid
    # work on an exhaustive run, by design.
    assert client.verify_images == [2, 2]
    assert all(f.verification.status == "VERIFIED" for f in entries)
    # Both are inked on both sheets: two clouds, each with its QC tag.
    assert {p.name for p in ctx.reviewed_pdf_paths} == {
        "M-101_reviewed.pdf", "E-101_reviewed.pdf"}
    for pdf in ctx.reviewed_pdf_paths:
        doc = pymupdf.open(str(pdf))
        try:
            contents = [a.info.get("content", "") for page in doc for a in page.annots()]
        finally:
            doc.close()
        assert any("isolation valve" in c for c in contents), pdf.name
        assert any("horsepower" in c for c in contents), pdf.name
    # The markup plan has a placement per finding per sheet, and every one of
    # them is proven in the saved files (DA-007 receipts).
    run = ctx.markup_run
    assert run is not None and run.coverage_status == "COMPLETE"
    ours = {f.qc_id for f in entries}
    legs = {}
    for p in run.placements:
        if p.qc_id in ours:
            legs.setdefault(p.qc_id, set()).add(p.source_name)
    assert legs == {q: {"M-101.pdf", "E-101.pdf"} for q in ours}
    assert all(r.status == "WRITTEN" for r in run.receipts if r.placement.qc_id in ours)

    export = write_drawing_export(ctx, tmp_path / "out", source_names=["M-101", "E-101"])
    markup_manifest = (export / "markup_manifest.json").read_text(encoding="utf-8")
    assert all(q in markup_manifest for q in ours)
    exported = json.loads((export / "findings.json").read_text(encoding="utf-8"))
    rows = exported if isinstance(exported, list) else exported.get("findings", [])
    assert {VALVE, HORSEPOWER} <= {r.get("text") for r in rows}
    csv_text = (export / "findings.csv").read_text(encoding="utf-8-sig")
    assert VALVE in csv_text and HORSEPOWER in csv_text


def test_pipeline_each_kept_conflict_the_crop_cannot_settle_is_investigated(tmp_path):
    # The other consumer that costs money: an anchored finding the dual crop
    # leaves UNCERTAIN goes on to investigation. Both conflicts of the pair
    # now exist, so both do.
    client = _Pipeline(cross=[_item(VALVE), _item(HORSEPOWER)], verdict="NOT_VISIBLE")
    work = tmp_path / "qc"
    ctx = extract_drawing_context(
        _pdfs(tmp_path), client=client, rows=2, cols=2, cross_qc=True,
        qc_markups=True, markup_verified_only=False, qc_work_dir=work)
    entries = _cross_entries(ctx)
    assert len(entries) == 2 and client.verify_images == [2, 2]
    assert client.investigate_calls >= 2
    for f in entries:
        assert (work / "evidence" / f.qc_id / "investigation.json").exists(), f.qc_id


def test_pipeline_an_uncertain_conflict_is_a_low_question_on_both_sheets(tmp_path):
    client = _Pipeline(cross=[_item(category="question", severity="low")])
    ctx = extract_drawing_context(
        _pdfs(tmp_path), client=client, rows=2, cols=2, cross_qc=True,
        qc_markups=True, qc_work_dir=tmp_path / "qc")
    (entry,) = _cross_entries(ctx)
    assert (entry.category, entry.severity) == ("question", "low")
    assert client.verify_images == [2]
    low = _SEVERITY_LAYER_NAMES["low"]
    for pdf in ctx.reviewed_pdf_paths:
        doc = pymupdf.open(str(pdf))
        try:
            names = {x: info["name"] for x, info in doc.get_ocgs().items()}
            layers = {names.get(a.get_oc()) for page in doc for a in page.annots()
                      if a.type[1] == "Square"}
        finally:
            doc.close()
        assert layers == {low}, (pdf.name, layers)
