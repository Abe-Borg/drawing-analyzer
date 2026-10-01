"""Phase 23B — the append-only usage ledger, per-record pricing, cost preview.

Pure, hermetic unit tests over ``UsageRecord`` / ``RunUsage`` (§6.3),
``core.pricing.usage_record_cost`` (§15.7), and the exhaustive cost estimate
(``cost.estimate_exhaustive_run_cost``). No PyMuPDF, no client, no network — the
usage model and pricing are dependency-free so their arithmetic is unit-testable.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from drawing_analyzer.core.pricing import (
    BATCH_DISCOUNT,
    PRICING_EFFECTIVE_DATE,
    WEB_SEARCH_COST_PER_USE,
    usage_record_cost,
)
from drawing_analyzer.cost import (
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
    format_exhaustive_cost_prompt,
)
from drawing_analyzer.models import RunUsage, UsageRecord

_OPUS = "claude-opus-5"


# --------------------------------------------------------------------------- #
# RunUsage — append-only, derived totals (§6.3 / §15.6)
# --------------------------------------------------------------------------- #


def _rec(family, instance, i, o, **kw):
    # ``model`` defaults to Opus but is overridable, so a test can build the
    # mixed-model ledger a real run produces (verification on Sonnet, the prose
    # harvest on Haiku, ...) rather than a single-model fiction.
    model = kw.pop("model", _OPUS)
    return UsageRecord(
        stage_family=family, stage_instance=instance, model=model,
        input_tokens=i, output_tokens=o,
        estimated_cost=usage_record_cost(
            model=model, input_tokens=i, output_tokens=o,
            billable_tool_uses=kw.get("billable_tool_uses"),
            batch=(kw.get("transport") == "BATCH"),
        ),
        **kw,
    )


def test_run_totals_equal_the_exact_sum_of_records():
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 500, 80))
    ru.add(_rec("critique", "critique_1", 600, 40))
    ru.add(_rec("harvest", "prose_harvest", 200, 20))
    ru.add(_rec("verify", "verify", 40, 8))
    assert ru.total_input_tokens == 500 + 600 + 200 + 40
    assert ru.total_output_tokens == 80 + 40 + 20 + 8
    # The grand cost equals the sum of the per-record costs (Decimal, exact).
    assert ru.total_estimated_cost == sum(
        (r.estimated_cost for r in ru.records), Decimal("0")
    )


def test_no_stage_overwrites_anothers_counters():
    # The regression the append-only model fixes: the old QC pipeline did
    # ``v_in, v_out = vres…`` (``=`` not ``+=``), silently dropping the prose-harvest
    # tokens when verification ran. Independent records make that impossible.
    ru = RunUsage()
    ru.add(_rec("harvest", "prose_harvest", 200, 20))
    ru.add(_rec("verify", "verify", 40, 8))
    families = {r.stage_family for r in ru.records}
    assert {"harvest", "verify"} <= families
    # Both stages' tokens survive in the total — neither clobbered the other.
    assert ru.total_input_tokens == 240 and ru.total_output_tokens == 28


def test_cache_hit_contributes_zero_billed_tokens_but_records_metadata():
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 500, 80))
    ru.add(UsageRecord(
        stage_family="digest", stage_instance="digest_2", model=_OPUS,
        transport="CACHE", cache_hit=True, input_tokens=0, output_tokens=0,
        estimated_cost=Decimal("0"),
    ))
    assert ru.total_input_tokens == 500          # the cache hit adds zero
    assert ru.cache_hits == 1
    assert ru.by_family()["digest"]["calls"] == 2
    assert ru.by_family()["digest"]["cache_hits"] == 1


def test_parse_failed_response_still_billable():
    # A response that consumed tokens but failed to parse is still billed (§15.6).
    r = _rec("digest", "digest_1", 500, 80, parse_success=False, terminal_status="FAILED")
    ru = RunUsage()
    ru.add(r)
    assert ru.total_input_tokens == 500 and not r.parse_success


def test_run_usage_to_dict_round_trips_totals():
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 500, 80))
    d = ru.to_dict()
    assert d["total_input_tokens"] == 500 and d["total_output_tokens"] == 80
    assert "digest" in d["by_family"] and len(d["records"]) == 1
    assert _OPUS in d["by_model"]


# --------------------------------------------------------------------------- #
# Per-model rollup
# --------------------------------------------------------------------------- #


def test_by_model_separates_stages_that_share_a_family_name():
    """The axis a model-routing comparison needs.

    Two runs differing only in ``DRAWING_ANALYZER_CRITIQUE_MODEL`` are
    indistinguishable in a family rollup — the family names are identical in
    both — so the per-record model had to be aggregated somewhere.
    """
    sonnet = "claude-sonnet-5"
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 1000, 100))                    # Opus
    ru.add(_rec("critique", "critique_1", 2000, 200, model=sonnet))
    ru.add(_rec("critique", "critique_2", 2000, 200, model=sonnet))

    by_model = ru.by_model()
    assert set(by_model) == {_OPUS, sonnet}
    assert by_model[_OPUS]["input_tokens"] == 1000
    assert by_model[_OPUS]["calls"] == 1
    assert by_model[sonnet]["input_tokens"] == 4000
    assert by_model[sonnet]["calls"] == 2
    # Sonnet 5 input is $2/MTok against Opus 5's $5, so 4x the tokens still
    # costs less than 2x here — the whole point of being able to see this.
    assert by_model[sonnet]["estimated_cost"] < by_model[_OPUS]["estimated_cost"] * 3


def test_by_model_and_by_family_agree_on_call_count():
    """Both rollups partition the same records — neither may drop any."""
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 100, 10))
    ru.add(_rec("critique", "critique_1", 200, 20, model="claude-sonnet-5"))
    ru.add(_rec("verify", "verify_1", 50, 5, model="claude-sonnet-5"))

    fam_calls = sum(g["calls"] for g in ru.by_family().values())
    model_calls = sum(g["calls"] for g in ru.by_model().values())
    assert fam_calls == model_calls == len(ru.records) == 3


def test_by_model_groups_a_modelless_record_rather_than_dropping_it():
    """A record with no model must still be counted, or the rollup won't reconcile."""
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 100, 10))
    ru.add(UsageRecord(
        stage_family="digest", stage_instance="digest_2", model="",
        transport="CACHE", cache_hit=True, estimated_cost=Decimal("0"),
    ))
    by_model = ru.by_model()
    assert "" in by_model
    assert by_model[""]["calls"] == 1 and by_model[""]["cache_hits"] == 1
    assert sum(g["calls"] for g in by_model.values()) == len(ru.records)


def test_by_model_inherits_the_unpriced_rule():
    """An unpriced billable record makes its model's cost None, not a partial sum."""
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 500, 80))
    ru.add(UsageRecord(
        stage_family="critique", stage_instance="critique_1",
        model="some-new-unpriced-model", input_tokens=300, output_tokens=20,
        estimated_cost=None,
    ))
    by_model = ru.by_model()
    assert by_model["some-new-unpriced-model"]["estimated_cost"] is None
    assert by_model[_OPUS]["estimated_cost"] is not None


def test_total_is_none_when_a_billable_record_is_unpriced():
    # A run that mixes a priced record (Opus) with a billable record whose model
    # is not in the pricing table must NOT show a concrete total that silently
    # omits the unpriced usage — the aggregate is unknowable, so None.
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 500, 80))                 # priced (Opus)
    ru.add(UsageRecord(
        stage_family="critique", stage_instance="critique_1",
        model="some-new-unpriced-model", input_tokens=300, output_tokens=20,
        estimated_cost=None,                                    # unknown model → unpriced
    ))
    assert ru.total_estimated_cost is None
    # The affected family's cost is None too; the priced family keeps its cost.
    fam = ru.by_family()
    assert fam["critique"]["estimated_cost"] is None
    assert fam["digest"]["estimated_cost"] is not None
    # Tokens still tally exactly regardless of pricing.
    assert ru.total_input_tokens == 800


def test_zero_token_unpriced_cache_hit_does_not_poison_the_total():
    # A cache hit under an unknown model has zero billed tokens — it is not
    # billable, so it must not turn the whole total unavailable.
    ru = RunUsage()
    ru.add(_rec("digest", "digest_1", 500, 80))                 # priced
    ru.add(UsageRecord(
        stage_family="digest", stage_instance="digest_2",
        model="some-new-unpriced-model", transport="CACHE", cache_hit=True,
        input_tokens=0, output_tokens=0, estimated_cost=None,
    ))
    assert ru.total_estimated_cost is not None                  # still priceable


# --------------------------------------------------------------------------- #
# Per-record pricing (§15.7)
# --------------------------------------------------------------------------- #


def test_real_time_vs_batch_rate_per_record():
    rt = usage_record_cost(model=_OPUS, input_tokens=1_000_000, output_tokens=1_000_000)
    bt = usage_record_cost(model=_OPUS, input_tokens=1_000_000, output_tokens=1_000_000, batch=True)
    assert rt == Decimal("30")                       # 5 + 25 per Mtok
    assert bt == rt * Decimal(str(BATCH_DISCOUNT))   # batch is half


def test_cache_read_write_and_web_search_pricing():
    # cache read = 0.1x input, default (5-minute) cache write = 1.25x input.
    cr = usage_record_cost(model=_OPUS, cache_read_tokens=1_000_000)
    cw = usage_record_cost(model=_OPUS, cache_write_tokens=1_000_000)
    assert cr == Decimal("0.5") and cw == Decimal("6.25")
    # web search billed per use, NOT batch-discounted.
    ws = usage_record_cost(model=_OPUS, billable_tool_uses={"web_search": 4}, batch=True)
    assert ws == Decimal("4") * WEB_SEARCH_COST_PER_USE


def test_one_hour_cache_write_is_priced_at_2x_not_1_25x():
    """A ``ttl: "1h"`` breakpoint costs 2x base input, not the 5-minute 1.25x.

    ``api_config._cache_control_block`` requests the 1-hour TTL, so any stage
    routed through its breakpoint helpers (today the investigation loop) writes
    at 2x. Pricing every write at 1.25x under-reported those records by 60%.
    """
    five_min = usage_record_cost(model=_OPUS, cache_write_tokens=1_000_000)
    one_hour = usage_record_cost(
        model=_OPUS, cache_write_tokens=1_000_000, cache_write_ttl="1h"
    )
    assert five_min == Decimal("6.25")   # 5.00 x 1.25
    assert one_hour == Decimal("10.00")  # 5.00 x 2.00
    # An unset or unrecognized ttl resolves to the conservative 5-minute rate
    # rather than silently inheriting 2x.
    assert usage_record_cost(
        model=_OPUS, cache_write_tokens=1_000_000, cache_write_ttl=None
    ) == five_min
    assert usage_record_cost(
        model=_OPUS, cache_write_tokens=1_000_000, cache_write_ttl="30m"
    ) == five_min
    # The batch discount stacks on top of the TTL multiplier.
    assert usage_record_cost(
        model=_OPUS, cache_write_tokens=1_000_000, cache_write_ttl="1h", batch=True
    ) == Decimal("5.00")


def test_cache_write_ttl_comes_from_the_policy_that_builds_the_breakpoint(monkeypatch):
    """The ledger's TTL is read from the same policy the request builder uses.

    Every registered phase currently caches, so all of them write at the 1-hour
    rate. The ``None`` branch is still live for a phase whose policy disables
    caching — it must report "no cache written" rather than a rate, or the
    pricer would invent a write cost for a request that never made one.
    """
    from drawing_analyzer.core import api_config as api

    assert api.cache_write_ttl_for(api.PHASE_INVESTIGATION) == "1h"
    assert api.cache_write_ttl_for(api.PHASE_HARVEST) == "1h"

    monkeypatch.setitem(
        api._PHASE_CACHE_POLICY, "uncached_phase",
        api.CachePolicy(cache_system=False, cache_tools=False),
    )
    assert api.cache_write_ttl_for("uncached_phase") is None


def test_a_five_minute_breakpoint_stage_is_not_priced_at_the_one_hour_rate():
    """digest/critique attach a plain ``{"type": "ephemeral"}`` — 5 minutes.

    They pass no ``cache_write_ttl`` at all, so the default must land on the
    1.25x rate. Getting this backwards would over-report the two stages that
    dominate the bill.
    """
    plain = usage_record_cost(model=_OPUS, cache_write_tokens=1_000_000)
    assert plain == Decimal("6.25")  # 5.00 x 1.25, not x 2.00


def test_unknown_model_returns_none_but_keeps_tool_charge():
    assert usage_record_cost(model="mystery-9", input_tokens=1000, output_tokens=1000) is None
    assert usage_record_cost(model="mystery-9", billable_tool_uses={"web_search": 2}) == Decimal("0.02")


def test_effective_date_is_stamped():
    assert PRICING_EFFECTIVE_DATE  # a non-empty verified-effective-date string


def test_rescued_batch_digest_is_priced_real_time():
    # A sheet rescued/inlined out of a batch is a full-rate real-time call, not the
    # 50% batch rate — even on a use_batch run (the transport helper enforces this).
    from drawing_analyzer.pipeline import _digest_transport

    assert _digest_transport(cached=False, rescued=True, use_batch=True) == "REAL_TIME"
    assert _digest_transport(cached=False, rescued=False, use_batch=True) == "BATCH"
    assert _digest_transport(cached=False, rescued=False, use_batch=False) == "REAL_TIME"
    # A cache hit always wins (zero billed tokens) regardless of the other flags.
    assert _digest_transport(cached=True, rescued=True, use_batch=True) == "CACHE"


def test_abandoned_attempt_records_are_free():
    # A batch abandoned mid-flight is recorded (§15.6 wants every attempt) but
    # answered nothing: zero tokens in, zero dollars out. The record exists to
    # explain the wall clock, never to move a total.
    from drawing_analyzer.batch_digest import DigestUsageAttempt

    abandoned = DigestUsageAttempt(
        transport="BATCH", terminal_status="ABANDONED_STALLED", billable=False,
    )
    assert abandoned.billable is False
    assert (abandoned.input_tokens, abandoned.output_tokens) == (0, 0)
    assert DigestUsageAttempt().billable is True  # responses stay billable

    usage = RunUsage()
    usage.add(UsageRecord(
        stage_family="digest", stage_instance="digest:SRC-0001:p0", model=_OPUS,
        transport="BATCH", terminal_status="ABANDONED_STALLED",
        estimated_cost=usage_record_cost(
            model=_OPUS, input_tokens=0, output_tokens=0, batch=True,
        ),
    ))
    assert usage.total_input_tokens == 0
    assert usage.total_estimated_cost == Decimal("0")


def test_image_estimate_counts_only_answered_attempts():
    # The image estimate is charged per *response-bearing* attempt. Counting an
    # abandoned round would invent image tokens nobody was billed for — the
    # 39-sheet run that burned two abandoned batches would have tripled its
    # reported image tokens.
    from drawing_analyzer.batch_digest import DigestUsageAttempt

    attempts = [
        DigestUsageAttempt(transport="BATCH", billable=False,
                           terminal_status="ABANDONED_STALLED"),
        DigestUsageAttempt(transport="BATCH", billable=False,
                           terminal_status="ABANDONED_STALLED"),
        DigestUsageAttempt(transport="BATCH", input_tokens=90, output_tokens=25),
    ]
    billable = sum(1 for a in attempts if getattr(a, "billable", True))
    assert billable == 1
    assert 1_000 * billable == 1_000  # one sheet's images, billed once


# --------------------------------------------------------------------------- #
# Exhaustive cost preview (§15.7)
# --------------------------------------------------------------------------- #


def test_exhaustive_estimate_exceeds_digest_only_and_lists_all_paid_stages():
    est = estimate_exhaustive_run_cost(10, file_count=2, batch=True)
    digest_only = estimate_drawing_set_cost(10, file_count=2, batch=True)
    assert est.high_cost is not None and digest_only.total_cost is not None
    # The exhaustive run is meaningfully pricier than the digest alone.
    assert est.high_cost > digest_only.total_cost
    assert est.low_cost <= est.high_cost
    stages = " ".join(c.stage for c in est.components)
    for needle in ("Digest", "Set identity", "Model review plan", "Critique",
                   "Cross-sheet QC", "Verification", "Investigation", "Citation"):
        assert needle in stages, needle
    # Phase 23C: the digest AND the two critique reads ride batch; cross/verify/
    # citation are still real-time.
    by_stage = {c.stage: c for c in est.components}
    assert by_stage["Critique ×2 (per sheet)"].transport == "batch"
    assert by_stage["Cross-sheet QC"].transport == "real-time"
    assert est.verified_effective_date == PRICING_EFFECTIVE_DATE


def _critique_component(est):
    return next(c for c in est.components if c.stage.startswith("Critique"))


def test_exhaustive_estimate_critique_batch_is_half_the_real_time_token_rate(monkeypatch):
    """Phase 23C: the critique component is batch-priced when ``batch=True``.

    Asserted at **one** read per sheet, which is where the claim is exactly
    testable. WP-05 §10.2 gave the real-time path its true rate class: at
    ``runs >= 2`` ``critique_sheet_self_consistent`` sets a prompt-cache
    breakpoint, so the real-time side pays a 1.25x write on the shared image
    prefix that the batch side (no breakpoint — parallel submission cannot read
    a cache still being written) never pays.

    This test previously asserted exact halving at the shipping two reads. That
    held only because the estimator billed every real-time read at a flat 1x,
    which was the defect §10.2 identifies — so the assertion was true *because
    of* the bug it could not see. At ``runs=1`` neither path has a breakpoint,
    both are flat, and the 50% discount is isolated and exact.
    """
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_RUNS", "1")
    b = _critique_component(estimate_exhaustive_run_cost(10, file_count=2, batch=True))
    r = _critique_component(estimate_exhaustive_run_cost(10, file_count=2, batch=False))
    assert b.transport == "batch" and r.transport == "real-time"
    assert b.input_tokens == r.input_tokens and b.output_tokens == r.output_tokens
    assert b.cost is not None and r.cost is not None
    assert b.cost == pytest.approx(r.cost * BATCH_DISCOUNT)


def test_exhaustive_estimate_batch_critique_beats_half_once_a_prefix_is_cached(monkeypatch):
    """At the shipping two reads, batch is better than half — and that is real.

    The real-time side writes the ~90k-token image prefix at 1.25x on the read
    the displayed (pessimistic) figure assumes misses; the batch side has no
    breakpoint to write. So the ratio drops below ``BATCH_DISCOUNT`` rather than
    sitting on it, and a test pinning it *at* 0.5 would now be pinning the old
    flat-rate defect.
    """
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_RUNS", "2")
    b = _critique_component(estimate_exhaustive_run_cost(10, file_count=2, batch=True))
    r = _critique_component(estimate_exhaustive_run_cost(10, file_count=2, batch=False))
    assert b.input_tokens == r.input_tokens          # same work, different rates
    assert b.cost < r.cost * BATCH_DISCOUNT
    assert 0.35 < b.cost / r.cost < 0.45


def test_exhaustive_prompt_is_labeled_an_estimate_and_names_stages():
    prompt = format_exhaustive_cost_prompt(estimate_exhaustive_run_cost(5, file_count=1))
    assert "exhaustive" in prompt.lower()
    assert "Critique" in prompt and "Citation" in prompt
    assert "rough" in prompt.lower() and PRICING_EFFECTIVE_DATE in prompt
    # Phase A: the pre-run dialog discloses the two planning calls.
    assert "Set identity" in prompt and "Model review plan" in prompt


def test_exhaustive_estimate_planning_stages_are_realtime_and_scale_gently():
    # Phase A: identity + plan are one text-only real-time call each; their
    # input grows with the sheet count (bigger corpus) but stays small next to
    # the per-sheet vision stages.
    small = {c.stage: c for c in estimate_exhaustive_run_cost(2).components}
    large = {c.stage: c for c in estimate_exhaustive_run_cost(50).components}
    for stage in ("Set identity", "Model review plan"):
        assert small[stage].transport == "real-time"
        assert large[stage].input_tokens > small[stage].input_tokens
        assert small[stage].cost is not None and small[stage].cost > 0
    assert large["Set identity"].cost < large["Critique ×2 (per sheet)"].cost


def test_exhaustive_estimate_investigation_band_is_capped_and_realtime():
    # Phase C: the investigation band scales with the finding volume but never
    # quotes past the stage's own per-run budget — which itself now scales with
    # the set, so a flat quote would under-state a large set several-fold.
    from drawing_analyzer.investigate import investigation_max_findings

    small = {c.stage: c for c in estimate_exhaustive_run_cost(2).components}
    large = {c.stage: c for c in estimate_exhaustive_run_cost(500).components}
    inv_small, inv_large = small["Investigation"], large["Investigation"]
    assert inv_small.transport == "real-time" and inv_large.transport == "real-time"
    assert inv_large.input_tokens >= inv_small.input_tokens
    # Capped at the stage's own ceiling for a set that large.
    assert f"~{investigation_max_findings(500)} uncertain finding(s)" in inv_large.note
    assert "~40 uncertain finding(s)" in inv_large.note      # the hard ceiling
    # It rides the low/high totals: an estimate without it would be smaller.
    est = estimate_exhaustive_run_cost(10)
    assert est.low_cost is not None and est.low_cost <= est.high_cost


# --------------------------------------------------------------------------- #
# 20a: a zero-count tool entry is not usage.
#
# ``billable_tool_uses`` is truthy on its KEYS, so a citation run whose every
# reference came warm from the verdict cache wrote {"web_search": 0} — which
# read as billable usage and turned a whole run's total into "unknown" when
# nothing unpriceable had happened. Both ends are guarded here, because either
# alone leaves the other free to reintroduce it.
# --------------------------------------------------------------------------- #

_UNPRICEABLE = "some-unregistered-model"


def _tool_rec(tools):
    return UsageRecord(
        stage_family="citation", stage_instance="citation", model=_UNPRICEABLE,
        transport="REAL_TIME", billable_tool_uses=tools, estimated_cost=None,
    )


@pytest.mark.parametrize(
    "tools,expected",
    [
        ({"web_search": 0}, False),          # the bug: a count of zero
        ({}, False),
        ({"web_search": 0, "other": 0}, False),
        ({"web_search": 3}, True),           # a real use still poisons the total
        ({"web_search": 0, "other": 2}, True),
        ({"web_search": None}, False),       # server field absent, not a use
        ({"web_search": "x"}, False),        # unparseable, never a raise
    ],
)
def test_only_a_positive_tool_count_is_billable_usage(tools, expected):
    assert RunUsage.is_billable_but_unpriced(_tool_rec(tools)) is expected


def test_a_zero_search_citation_record_does_not_unknown_the_run_total():
    # The consequence, end to end: one priced digest beside a citation stage
    # that made no searches must still report a total, not "unknown".
    usage = RunUsage()
    usage.records.append(UsageRecord(
        stage_family="digest", stage_instance="digest:SRC-0001:p0", model=_OPUS,
        transport="REAL_TIME", input_tokens=1000, output_tokens=1000,
        estimated_cost=Decimal("5.00"),
    ))
    usage.records.append(_tool_rec({"web_search": 0}))
    assert usage.total_estimated_cost == Decimal("5.00")

    # ...while a run that genuinely searched under an unpriceable model still
    # refuses to report a number. Losing that would be the worse bug.
    poisoned = RunUsage()
    poisoned.records.append(usage.records[0])
    poisoned.records.append(_tool_rec({"web_search": 2}))
    assert poisoned.total_estimated_cost is None


def test_record_usage_never_stores_a_zero_count_tool_entry():
    # The writer half. Storing the key at all is what made the predicate's job
    # impossible, so the record must not carry it in the first place.
    from drawing_analyzer.pipeline import _record_usage

    usage = RunUsage()
    rec = _record_usage(
        usage, family="citation", instance="citation", model=_OPUS,
        billable_tool_uses={"web_search": 0},
    )
    assert rec.billable_tool_uses == {}

    kept = _record_usage(
        usage, family="citation", instance="citation2", model=_OPUS,
        billable_tool_uses={"web_search": 4, "unused": 0},
    )
    assert kept.billable_tool_uses == {"web_search": 4}


# --------------------------------------------------------------------------- #
# The citation stage records the cache tokens it is billed for.
#
# It attaches a cache breakpoint to its tool schemas, so on every request after
# the first most of the input is billed as a cache READ and ``input_tokens``
# reports only the remainder. Reading just the latter reported a fraction of
# what the stage cost — and a cache-heavy record under an unpriceable model
# passed as "no usage" entirely.
# --------------------------------------------------------------------------- #


def test_citation_outcome_carries_the_prompt_cache_split():
    from drawing_analyzer.citation_check import CitationCheckResult, _CheckOutcome

    outcome = _CheckOutcome()
    assert outcome.cache_read_tokens == 0 and outcome.cache_write_tokens == 0
    result = CitationCheckResult()
    assert result.cache_read_tokens == 0 and result.cache_write_tokens == 0


def test_message_cache_usage_reads_dict_and_object_shaped_usage():
    from drawing_analyzer.digest import _message_cache_usage

    class _Usage:
        cache_read_input_tokens = 700
        cache_creation_input_tokens = 900

    class _Resp:
        usage = _Usage()

    assert _message_cache_usage(_Resp()) == (700, 900)
    # A dict-shaped usage (raw-REST client, batch result, dict fixtures) must be
    # counted, not silently zeroed — that undercounts rather than failing.
    assert _message_cache_usage(
        {"usage": {"cache_read_input_tokens": 5, "cache_creation_input_tokens": 6}}
    ) == (5, 6)
    assert _message_cache_usage({"usage": None}) == (0, 0)
    assert _message_cache_usage({}) == (0, 0)


def test_citation_cache_tokens_make_a_record_billable():
    # The reason this matters: a cache-heavy citation record under a model the
    # table cannot price is real spend, and must not read as "no usage".
    rec = UsageRecord(
        stage_family="citation", stage_instance="citation", model=_UNPRICEABLE,
        transport="REAL_TIME", input_tokens=0, output_tokens=0,
        cache_read_tokens=180_000, estimated_cost=None,
    )
    assert RunUsage.is_billable_but_unpriced(rec) is True
