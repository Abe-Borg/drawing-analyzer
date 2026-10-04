"""Phase A §20.2 — the model-authored review plan (`review_planner.py`).

Hermetic unit tests (I-4): sanitation bounds, profile-object construction, the
render contract the critique checklist relies on, snapshot vocabulary, cache
stability, and the degradation matrix. No PyMuPDF, no network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.digest_cache import DigestCache
import pytest

from drawing_analyzer.models import AdoptedCode, SetIdentity, SheetRef
from drawing_analyzer.profiles import build_checklist_prompt, profiles_cache_fragment
from drawing_analyzer.review_planner import (
    PLANNER_PROMPT_VERSION,
    PLANNER_SYSTEM_PROMPT,
    PlanItem,
    author_review_plan,
    build_planner_user_text,
    max_plan_items,
    parse_planner_text,
    plan_snapshots,
    profiles_from_plans,
    render_item,
    sanitize_plans,
)
from tests.fixtures.fake_anthropic import BetaClientMixin, StreamingMessagesMixin, FakeMessage, FakeTextBlock, FakeUsage


def _ref(i: int) -> SheetRef:
    return SheetRef(
        pdf_path=Path("/tmp/set.pdf"), page_index=i, source_name="set.pdf",
        page_count=9, source_id="SRC-0001",
    )


def _sheet(i: int, text: str = "Sheet FP-101 - Fire Protection - Plan\nnotes") -> SheetDigest:
    return SheetDigest(ref=_ref(i), text=text)


_IDENTITY = SetIdentity(
    disciplines=("fire protection",),
    jurisdiction="California, United States",
    language="en", units="imperial", confidence="high",
)

_PLANS_PAYLOAD = {
    "plans": [
        {
            "discipline": "Mechanical",
            "title": "Mechanical QC",
            "items": [
                {"text": "Flag a scheduled tag never drawn on a plan.",
                 "severity": "medium", "refs": []},
            ],
        },
        {
            "discipline": "Fire Protection",
            "title": "FP — NFPA 13 (2016) QC",
            "items": [
                {"text": "Flag a dry-system row with no +30% remote-area increase.",
                 "severity": "HIGH", "refs": ["NFPA 13 2016 §19.2.3.2.5"]},
                {"text": "Expected an ITV on every dry system; flag when not found.",
                 "severity": "weird", "refs": ["NFPA 13 2016"]},
            ],
        },
    ]
}


def _reply(payload: dict | None = None) -> str:
    return "```json\n" + json.dumps(payload or _PLANS_PAYLOAD) + "\n```"


class _FakeClient(BetaClientMixin):
    def __init__(self, reply_text: str):
        self.calls: list[dict] = []
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(_self, **kw):
                outer.calls.append(kw)
                return FakeMessage(
                    content=[FakeTextBlock(text=reply_text)],
                    usage=FakeUsage(input_tokens=200, output_tokens=90),
                )

        self.messages = _Msgs()


# --------------------------------------------------------------------------- #
# Rendering + sanitation
# --------------------------------------------------------------------------- #


def test_render_item_matches_profile_convention():
    assert render_item(PlanItem(text="Flag X when Y.", severity="high",
                                refs=("NFPA 13 2016 §8.1.2",))) == \
        "Flag X when Y. [high] (NFPA 13 2016 §8.1.2)"
    assert render_item(PlanItem(text="Flag X.", severity="low")) == "Flag X. [low]"


def test_sanitize_sorts_plans_and_normalizes():
    plans, dropped = sanitize_plans(_PLANS_PAYLOAD)
    # Sorted by discipline slug (I-7): fire-protection before mechanical.
    assert [p.slug for p in plans] == ["fire-protection", "mechanical"]
    fp = plans[0]
    assert fp.items[0].severity == "high"            # case-folded
    assert fp.items[1].severity == "medium"          # unknown -> medium
    assert dropped == 0


def test_sanitize_drops_overlong_duplicate_and_malformed_items():
    payload = {"plans": [{
        "discipline": "electrical",
        "items": [
            {"text": "Flag a panel schedule with no AIC rating.", "severity": "high"},
            {"text": "Flag a panel schedule with no AIC rating.", "severity": "low"},  # dup
            {"text": "x" * 400},                                     # overlong -> dropped
            "not a dict",                                            # malformed
            {"text": ""},                                            # empty
        ],
    }]}
    plans, dropped = sanitize_plans(payload)
    assert len(plans) == 1 and len(plans[0].items) == 1
    assert dropped == 4
    # Never truncated: the surviving item is byte-identical to its input.
    assert plans[0].items[0].text == "Flag a panel schedule with no AIC rating."


def test_sanitize_enforces_total_cap(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_PLAN_ITEMS", "3")
    assert max_plan_items() == 3
    payload = {"plans": [
        {"discipline": "a", "items": [{"text": f"Flag a{i}."} for i in range(4)]},
        {"discipline": "b", "items": [{"text": f"Flag b{i}."} for i in range(4)]},
    ]}
    plans, dropped = sanitize_plans(payload)
    assert sum(len(p.items) for p in plans) == 3
    assert dropped == 5
    # The overage is SHARED, not spent on the alphabetically-last plan (N5).
    # This assertion previously read "the FIRST plan keeps its items; the tail
    # plan absorbs cuts" — which is the behaviour N5 exists to remove: with plans
    # sorted by slug, tail-trimming deleted whole disciplines in alphabetical
    # order, so `mechanical` and `plumbing` were dropped outright while
    # `architectural` kept everything.
    assert {p.slug for p in plans} == {"a", "b"}, "a discipline was deleted whole"
    assert all(p.items for p in plans), "a discipline was emptied"
    # No plan gives up items while another still holds two more than it.
    counts = sorted(len(p.items) for p in plans)
    assert counts[-1] - counts[0] <= 1, f"the trim was not shared: {counts}"


def test_sanitize_caps_refs_and_plan_count():
    payload = {"plans": [
        {"discipline": f"d{i}", "items": [{"text": "Flag x.",
                                           "refs": [f"R{j}" for j in range(10)]}]}
        for i in range(12)
    ]}
    plans, _ = sanitize_plans(payload)
    assert len(plans) <= 8
    assert all(len(it.refs) <= 3 for p in plans for it in p.items)


def test_sanitize_counts_plans_discarded_by_the_plan_cap():
    # Codex review (PR #70): plans past _MAX_PLANS are discarded WHOLE — their
    # items must be counted as dropped so the stage honestly reports PARTIAL
    # instead of silently losing entire discipline checklists.
    payload = {"plans": [
        {"discipline": f"d{i}", "items": [{"text": f"Flag {i}-{j}."} for j in range(3)]}
        for i in range(10)                       # 2 plans past the cap of 8
    ]}
    plans, dropped = sanitize_plans(payload)
    assert len(plans) == 8
    assert dropped == 6                          # 2 discarded plans × 3 items
    # A malformed overflow entry still counts (as one drop): past-cap is now
    # d8 (3 items) + d9 (3 items) + the string (1).
    payload["plans"].append("not a dict")
    _, dropped2 = sanitize_plans(payload)
    assert dropped2 == 7


def test_sanitize_counts_items_past_the_scan_window():
    n = 25 * 2 + 5                               # 5 items past the 2×cap scan slice
    payload = {"plans": [{
        "discipline": "electrical",
        "items": [{"text": f"Flag item {i}."} for i in range(n)],
    }]}
    plans, dropped = sanitize_plans(payload)
    assert len(plans[0].items) == 25
    # 25 counted inside the scan window (past the per-plan cap) + 5 unseen.
    assert dropped == 30


def test_parse_planner_text_tolerates_prose_and_rejects_junk():
    assert parse_planner_text("prose\n" + _reply()) is not None
    assert parse_planner_text("no fences at all") is None
    assert parse_planner_text('```json\n{"not_plans": 1}\n```') is None


# --------------------------------------------------------------------------- #
# Profile objects + snapshots + cache fragment
# --------------------------------------------------------------------------- #


def test_profiles_from_plans_shape_and_determinism():
    plans, _ = sanitize_plans(_PLANS_PAYLOAD)
    profs = profiles_from_plans(plans)
    assert [p.name for p in profs] == ["model-plan-fire-protection", "model-plan-mechanical"]
    assert all(p.author == "model" and p.date == "" and p.source_path is None
               for p in profs)
    assert all(p.content_hash for p in profs)
    # The rendered items flow through the standard checklist builder.
    prompt = build_checklist_prompt([it for p in profs for it in p.items])
    assert "APPLY THIS REVIEW CHECKLIST" in prompt
    assert "NFPA 13 2016 §19.2.3.2.5" in prompt


def test_plan_snapshots_are_model_source():
    plans, _ = sanitize_plans(_PLANS_PAYLOAD)
    snaps = plan_snapshots(profiles_from_plans(plans))
    assert all(s.source == "model" for s in snaps)
    assert snaps[0].name == "model-plan-fire-protection" and snaps[0].content_hash


def test_cache_fragment_stable_for_same_plan_and_differs_across_plans():
    plans, _ = sanitize_plans(_PLANS_PAYLOAD)
    profs = profiles_from_plans(plans)
    frag1 = profiles_cache_fragment(profs)
    frag2 = profiles_cache_fragment(profiles_from_plans(sanitize_plans(_PLANS_PAYLOAD)[0]))
    assert frag1 == frag2                      # same plan -> byte-identical key input
    other = {"plans": [{"discipline": "mechanical",
                        "items": [{"text": "Flag something else entirely."}]}]}
    frag3 = profiles_cache_fragment(profiles_from_plans(sanitize_plans(other)[0]))
    assert frag3 != frag1                      # a different plan re-keys the critique


# --------------------------------------------------------------------------- #
# author_review_plan — call + degradation + cache
# --------------------------------------------------------------------------- #


def test_author_review_plan_happy_path():
    client = _FakeClient(_reply())
    res = author_review_plan(_IDENTITY, [_sheet(0)], client=client)
    assert res.ok and not res.cached
    assert res.item_count == 3 and len(res.profiles) == 2
    assert "# Model-authored review plan" in res.markdown
    assert "NFPA 13 2016 §19.2.3.2.5" in res.markdown
    # The identity context led the user turn; the system prompt is verbatim.
    assert client.calls[0]["system"] == PLANNER_SYSTEM_PROMPT
    user_text = client.calls[0]["messages"][0]["content"]
    assert user_text.startswith("SET IDENTITY (model-detected):")
    assert "California, United States" in user_text


def test_author_review_plan_without_identity_still_runs():
    client = _FakeClient(_reply())
    res = author_review_plan(None, [_sheet(0)], client=client)
    assert res.ok
    assert "SET IDENTITY: unavailable" in client.calls[0]["messages"][0]["content"]


def test_author_review_plan_malformed_reply_is_failed():
    res = author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient("bullet list, no json"))
    assert not res.ok and "no parseable plans block" in (res.error or "")


def test_author_review_plan_empty_plans_is_failed():
    res = author_review_plan(
        _IDENTITY, [_sheet(0)],
        client=_FakeClient('```json\n{"plans": []}\n```'),
    )
    assert not res.ok and "no usable plan items" in (res.error or "")


def test_author_review_plan_counts_dropped_items():
    payload = {"plans": [{
        "discipline": "civil",
        "items": [{"text": "Flag a swale with no invert elevation."},
                  {"text": "y" * 400}],
    }]}
    res = author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply(payload)))
    assert res.ok and res.dropped_items == 1 and res.item_count == 1


def test_author_review_plan_never_raises():
    class _Boom(BetaClientMixin):
        class messages(StreamingMessagesMixin):  # noqa: N801 - fake namespace
            @staticmethod
            def create(**kw):
                raise RuntimeError("permanent")

    res = author_review_plan(_IDENTITY, [_sheet(0)], client=_Boom())
    assert not res.ok and "permanent" in (res.error or "")
    assert author_review_plan(_IDENTITY, [], client=_Boom()).error


def test_author_review_plan_cache_round_trip_rebuilds_identical_profiles():
    cache = DigestCache(None, persist=False)
    first = author_review_plan(_IDENTITY, [_sheet(0)],
                               client=_FakeClient(_reply()), cache=cache)
    assert first.ok and not first.cached

    client2 = _FakeClient(_reply())
    second = author_review_plan(_IDENTITY, [_sheet(0)], client=client2, cache=cache)
    assert second.ok and second.cached and client2.calls == []
    # Byte-identical rebuild -> the critique profiles_key stays stable (R1).
    assert profiles_cache_fragment(second.profiles) == profiles_cache_fragment(first.profiles)
    assert [p.items for p in second.profiles] == [p.items for p in first.profiles]


def test_author_review_plan_cache_misses_on_different_identity():
    cache = DigestCache(None, persist=False)
    author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    other_identity = SetIdentity(disciplines=("electrical",), jurisdiction="Berlin, Germany")
    client2 = _FakeClient(_reply())
    res = author_review_plan(other_identity, [_sheet(0)], client=client2, cache=cache)
    assert not res.cached and len(client2.calls) == 1   # identity re-keys the plan


@pytest.mark.parametrize("change", ["rename", "add", "remove", "revise", "recover"])
def test_revision_retains_the_checklist(change):
    cache = DigestCache(None, persist=False)
    sheets = [_sheet(i, f"Sheet FP-10{i} - Fire Protection - Plan\nunique notes {i}")
              for i in range(3)]
    if change == "recover":
        sheets[2] = replace(sheets[2], text="", error="temporary digest failure")
    first = author_review_plan(_IDENTITY, sheets, client=_FakeClient(_reply()), cache=cache)
    revised = list(sheets)
    if change == "rename":
        revised = [replace(sd, ref=replace(sd.ref, source_name="reissued.pdf",
                                          pdf_path=Path("/tmp/reissued.pdf"))) for sd in sheets]
    elif change == "add":
        revised.append(_sheet(3, "Sheet FP-103 - Fire Protection - New Plan"))
    elif change == "remove":
        revised.pop(1)
    elif change == "revise":
        revised[1] = _sheet(1, "Sheet FP-101 - Fire Protection - Revised layout")
    else:
        revised[2] = _sheet(2, "Sheet FP-102 - Fire Protection - Recovered Plan")
    # Re-authoring would return different checklist text and evict all critiques.
    changed_plan = {"plans": [{"discipline": "fire protection", "items": [
        {"text": "Flag missing sprinkler coverage in occupied spaces."}]}]}
    client = _FakeClient(_reply(changed_plan))
    second = author_review_plan(_IDENTITY, revised, client=client, cache=cache)
    assert second.ok and second.cached and second.reused
    assert client.calls == []
    assert second.input_tokens == second.output_tokens == 0
    assert profiles_cache_fragment(second.profiles) == profiles_cache_fragment(first.profiles)


def test_revision_ignores_identity_provenance_and_normalizes_scope():
    cache = DigestCache(None, persist=False)
    code = AdoptedCode("NFPA 13", "2016", quote="per NFPA 13 2016", source_sheet="old.pdf")
    identity = replace(_IDENTITY, adopted_codes=(code,))
    first = author_review_plan(identity, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    revised_identity = replace(
        identity, disciplines=(" Fire Protection ",), units="IMPERIAL",
        sheet_disciplines=(("FP-101", "fire protection"), ("FP-102", "fire protection")),
        confidence="medium", evidence=("new evidence",), notes="Different detection prose",
        adopted_codes=(replace(code, code="nfpa 13", quote="new quote",
                               source_sheet="new.pdf", origin="regex"), code),
    )
    client = _FakeClient(_reply())
    second = author_review_plan(revised_identity, [_sheet(0), _sheet(1)], client=client, cache=cache)
    assert second.reused and client.calls == []
    assert profiles_cache_fragment(first.profiles) == profiles_cache_fragment(second.profiles)


@pytest.mark.parametrize("scope_change", [
    {"disciplines": ("electrical",)}, {"project_type": "hospital"},
    {"set_type": "construction"}, {"jurisdiction": "Berlin, Germany"},
    {"country": "Germany"}, {"region": "Berlin"}, {"language": "de"},
    {"units": "metric"}, {"adopted_codes": (AdoptedCode("NFPA 13", "2019"),)},
    {"adopted_codes": (AdoptedCode("NFPA 13", "2016", amendment_note="local amendment"),)},
])
def test_revision_replans_when_review_requirements_change(scope_change):
    cache = DigestCache(None, persist=False)
    identity = replace(_IDENTITY, adopted_codes=(AdoptedCode("NFPA 13", "2016"),))
    author_review_plan(identity, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    client = _FakeClient(_reply())
    result = author_review_plan(replace(identity, **scope_change), [_sheet(0), _sheet(1)],
                                client=client, cache=cache)
    assert result.ok and not result.cached and len(client.calls) == 1


@pytest.mark.parametrize("setting", ["model", "max_tokens", "effort", "thinking", "cap", "prompt"])
def test_revision_replans_when_planner_settings_change(setting, monkeypatch):
    cache = DigestCache(None, persist=False)
    author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    kwargs = {}
    if setting == "cap":
        monkeypatch.setenv("DRAWING_ANALYZER_MAX_PLAN_ITEMS", "40")
    elif setting == "prompt":
        monkeypatch.setattr("drawing_analyzer.review_planner.PLANNER_PROMPT_VERSION", "new-prompt")
    else:
        kwargs = {"model": "other-model", "max_tokens": 8000, "effort": "low",
                  "use_thinking": False}
        kwargs = {("use_thinking" if setting == "thinking" else setting):
                  kwargs["use_thinking" if setting == "thinking" else setting]}
    client = _FakeClient(_reply())
    result = author_review_plan(_IDENTITY, [_sheet(0), _sheet(1)], client=client, cache=cache, **kwargs)
    assert result.ok and not result.cached and len(client.calls) == 1


def test_no_overlap_and_unknown_scope_do_not_share_plans():
    cache = DigestCache(None, persist=False)
    author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    client = _FakeClient(_reply())
    assert not author_review_plan(_IDENTITY, [_sheet(1, "Unrelated set")],
                                  client=client, cache=cache).cached
    assert len(client.calls) == 1
    author_review_plan(None, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    client = _FakeClient(_reply())
    assert not author_review_plan(None, [_sheet(0), _sheet(1)], client=client, cache=cache).cached
    assert len(client.calls) == 1


def test_conflicting_snapshots_require_a_new_plan():
    cache = DigestCache(None, persist=False)
    a, b = _sheet(0, "First project"), _sheet(1, "Second project")
    for sd in (a, b):
        author_review_plan(_IDENTITY, [sd], client=_FakeClient(_reply()), cache=cache)
    client = _FakeClient(_reply())
    result = author_review_plan(_IDENTITY, [a, b], client=client, cache=cache)
    assert result.ok and not result.cached and len(client.calls) == 1


def test_revision_bindings_survive_restart_and_extend_to_new_sheets(tmp_path):
    path = tmp_path / "plans.sqlite"
    cache = DigestCache(path)
    first = author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    cache.close()
    cache = DigestCache(path)
    client = _FakeClient(_reply())
    added = _sheet(1, "New sheet FP-102")
    second = author_review_plan(_IDENTITY, [_sheet(0), added], client=client, cache=cache)
    assert second.reused and client.calls == []
    # Remove the original anchor: the new sheet now retains the same snapshot.
    third = author_review_plan(_IDENTITY, [added], client=client, cache=cache)
    assert third.reused and client.calls == []
    assert profiles_cache_fragment(third.profiles) == profiles_cache_fragment(first.profiles)
    cache.close()


def test_empty_cached_plan_is_reauthored():
    cache = DigestCache(None, persist=False)
    author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    for entry in cache._entries.values():
        if "plans" in entry:
            entry["plans"] = []
    client = _FakeClient(_reply())
    result = author_review_plan(_IDENTITY, [_sheet(0), _sheet(1)], client=client, cache=cache)
    assert result.ok and not result.cached and len(client.calls) == 1


def test_legacy_exact_entry_seeds_revision_bindings_without_authoring():
    cache = DigestCache(None, persist=False)
    first = author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply()), cache=cache)
    cache._entries = {key: entry for key, entry in cache._entries.items()
                      if not key.startswith("stage:review_plan_binding:")}
    client = _FakeClient(_reply())
    warm = author_review_plan(_IDENTITY, [_sheet(0)], client=client, cache=cache)
    revision = author_review_plan(_IDENTITY, [_sheet(0), _sheet(1)], client=client, cache=cache)
    assert warm.cached and not warm.reused and revision.reused and client.calls == []
    assert profiles_cache_fragment(revision.profiles) == profiles_cache_fragment(first.profiles)


def test_dropped_item_accounting_survives_exact_and_revision_hits():
    cache = DigestCache(None, persist=False)
    payload = {"plans": [{"discipline": "civil", "items": [
        {"text": "Flag a swale with no invert elevation."}, {"text": "x" * 400}]}]}
    first = author_review_plan(_IDENTITY, [_sheet(0)], client=_FakeClient(_reply(payload)), cache=cache)
    client = _FakeClient(_reply())
    warm = author_review_plan(_IDENTITY, [_sheet(0)], client=client, cache=cache)
    revision = author_review_plan(_IDENTITY, [_sheet(0), _sheet(1)], client=client, cache=cache)
    assert first.dropped_items == warm.dropped_items == revision.dropped_items == 1
    assert revision.reused and client.calls == []


def test_prompt_version_is_a_content_hash():
    assert len(PLANNER_PROMPT_VERSION) == 16


# --------------------------------------------------------------------------- #
# The total-cap trim is shared, not spent alphabetically (N5)
# --------------------------------------------------------------------------- #

_FIVE_DISCIPLINES = ["architectural", "electrical", "fire protection",
                     "mechanical", "plumbing"]


def _plans_payload(per_discipline: int):
    return {"plans": [
        {"discipline": d, "title": d.title(), "items": [
            {"text": f"{d} check {i} with enough words to clear the length floor",
             "severity": "high", "refs": []} for i in range(per_discipline)]}
        for d in _FIVE_DISCIPLINES]}


def test_no_discipline_is_deleted_to_satisfy_the_cap(monkeypatch):
    # Plans sort by slug, and the trim used to eat the LAST plan's tail until the
    # plan was gone. Measured with five disciplines of 20 items against the
    # 60-item cap: `mechanical` and `plumbing` were removed outright while
    # `architectural`, `electrical` and `fire protection` kept all 20. On a
    # mechanical / fire-protection review that deletes the checklist that mattered.
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_PLAN_ITEMS", "60")
    plans, dropped = sanitize_plans(_plans_payload(20))

    kept = {p.discipline: len(p.items) for p in plans}
    assert set(kept) == set(_FIVE_DISCIPLINES), f"a discipline was deleted: {kept}"
    assert all(n > 0 for n in kept.values()), f"a discipline was emptied: {kept}"
    assert sum(kept.values()) == 60
    assert dropped == 40
    # The loss is shared to within one item per discipline.
    assert max(kept.values()) - min(kept.values()) <= 1, kept


def test_trim_is_deterministic_regardless_of_input_order(monkeypatch):
    # I-7: the same plans in any order must trim identically, since the trim
    # picks the longest plan and ties resolve by slug.
    import random

    monkeypatch.setenv("DRAWING_ANALYZER_MAX_PLAN_ITEMS", "23")
    payload = _plans_payload(9)
    baseline = [(p.slug, len(p.items)) for p in sanitize_plans(payload)[0]]
    for seed in range(4):
        shuffled = {"plans": list(payload["plans"])}
        random.Random(seed).shuffle(shuffled["plans"])
        assert [(p.slug, len(p.items)) for p in sanitize_plans(shuffled)[0]] == baseline


def test_cap_below_the_discipline_count_still_terminates(monkeypatch):
    # Only when every plan is down to a single item may a whole plan go — and the
    # loop must not spin.
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_PLAN_ITEMS", "3")
    plans, dropped = sanitize_plans(_plans_payload(1))
    assert sum(len(p.items) for p in plans) == 3
    assert len(plans) == 3
    assert dropped == 2


def test_planner_refs_given_as_a_string_are_not_split_per_character():
    # P8 item 9 on the money-losing path: each unique ref is one web_search +
    # web_fetch in the citation check, so "NFPA 13 2016 §8.17" arriving as a bare
    # string used to buy three live searches for the letters N, F and P.
    payload = {"plans": [{"discipline": "fire protection", "title": "FP", "items": [
        {"text": "Verify sprinkler spacing against the adopted edition for the hazard",
         "severity": "high", "refs": "NFPA 13 2016 §8.17"}]}]}
    plans, _dropped = sanitize_plans(payload)
    assert plans and plans[0].items
    assert plans[0].items[0].refs == ("NFPA 13 2016 §8.17",)


def test_planner_malformed_items_and_refs_never_raise():
    # sanitize_plans is documented as never raising; the stage treats an exception
    # as a stage failure.
    for refs in ({"code": "NFPA 13"}, 13, None):
        payload = {"plans": [{"discipline": "fire protection", "title": "FP", "items": [
            {"text": "Verify sprinkler spacing against the adopted edition here",
             "severity": "high", "refs": refs}]}]}
        plans, _dropped = sanitize_plans(payload)
        assert plans[0].items[0].refs == ()
    for items in ("not a list", {"a": 1}, 5):
        plans, dropped = sanitize_plans(
            {"plans": [{"discipline": "fire protection", "title": "FP", "items": items}]}
        )
        assert dropped >= 1          # counted, never silently absent
