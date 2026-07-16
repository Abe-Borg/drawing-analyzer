"""Phase A §20.2 — the model-authored review plan (`review_planner.py`).

Hermetic unit tests (I-4): sanitation bounds, profile-object construction, the
render contract the critique checklist relies on, snapshot vocabulary, cache
stability, and the degradation matrix. No PyMuPDF, no network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import SetIdentity, SheetRef
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
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage


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


class _FakeClient:
    def __init__(self, reply_text: str):
        self.calls: list[dict] = []
        outer = self

        class _Msgs:
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
    # The FIRST plan (slug order) keeps its items; the tail plan absorbs cuts.
    assert len(plans[0].items) == 3 or (len(plans) == 1 and plans[0].slug == "a")


def test_sanitize_caps_refs_and_plan_count():
    payload = {"plans": [
        {"discipline": f"d{i}", "items": [{"text": "Flag x.",
                                           "refs": [f"R{j}" for j in range(10)]}]}
        for i in range(12)
    ]}
    plans, _ = sanitize_plans(payload)
    assert len(plans) <= 8
    assert all(len(it.refs) <= 3 for p in plans for it in p.items)


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
    class _Boom:
        class messages:  # noqa: N801 - fake namespace
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


def test_prompt_version_is_a_content_hash():
    assert len(PLANNER_PROMPT_VERSION) == 16
