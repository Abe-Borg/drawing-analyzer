"""Phase 23B — the append-only usage ledger, per-record pricing, cost preview.

Pure, hermetic unit tests over ``UsageRecord`` / ``RunUsage`` (§6.3),
``core.pricing.usage_record_cost`` (§15.7), and the exhaustive cost estimate
(``cost.estimate_exhaustive_run_cost``). No PyMuPDF, no client, no network — the
usage model and pricing are dependency-free so their arithmetic is unit-testable.
"""
from __future__ import annotations

from decimal import Decimal

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

_OPUS = "claude-opus-4-8"


# --------------------------------------------------------------------------- #
# RunUsage — append-only, derived totals (§6.3 / §15.6)
# --------------------------------------------------------------------------- #


def _rec(family, instance, i, o, **kw):
    return UsageRecord(
        stage_family=family, stage_instance=instance, model=_OPUS,
        input_tokens=i, output_tokens=o,
        estimated_cost=usage_record_cost(
            model=_OPUS, input_tokens=i, output_tokens=o,
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


# --------------------------------------------------------------------------- #
# Per-record pricing (§15.7)
# --------------------------------------------------------------------------- #


def test_real_time_vs_batch_rate_per_record():
    rt = usage_record_cost(model=_OPUS, input_tokens=1_000_000, output_tokens=1_000_000)
    bt = usage_record_cost(model=_OPUS, input_tokens=1_000_000, output_tokens=1_000_000, batch=True)
    assert rt == Decimal("30")                       # 5 + 25 per Mtok
    assert bt == rt * Decimal(str(BATCH_DISCOUNT))   # batch is half


def test_cache_read_write_and_web_search_pricing():
    # cache read = 0.1x input, cache write = 1.25x input (per Mtok).
    cr = usage_record_cost(model=_OPUS, cache_read_tokens=1_000_000)
    cw = usage_record_cost(model=_OPUS, cache_write_tokens=1_000_000)
    assert cr == Decimal("0.5") and cw == Decimal("6.25")
    # web search billed per use, NOT batch-discounted.
    ws = usage_record_cost(model=_OPUS, billable_tool_uses={"web_search": 4}, batch=True)
    assert ws == Decimal("4") * WEB_SEARCH_COST_PER_USE


def test_unknown_model_returns_none_but_keeps_tool_charge():
    assert usage_record_cost(model="mystery-9", input_tokens=1000, output_tokens=1000) is None
    assert usage_record_cost(model="mystery-9", billable_tool_uses={"web_search": 2}) == Decimal("0.02")


def test_effective_date_is_stamped():
    assert PRICING_EFFECTIVE_DATE  # a non-empty verified-effective-date string


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
    for needle in ("Digest", "Critique", "Cross-sheet QC", "Verification", "Citation"):
        assert needle in stages, needle
    # Critique/cross/verify/citation are real-time; the digest rides batch.
    by_stage = {c.stage: c for c in est.components}
    assert by_stage["Critique ×2 (per sheet)"].transport == "real-time"
    assert est.verified_effective_date == PRICING_EFFECTIVE_DATE


def test_exhaustive_prompt_is_labeled_an_estimate_and_names_stages():
    prompt = format_exhaustive_cost_prompt(estimate_exhaustive_run_cost(5, file_count=1))
    assert "exhaustive" in prompt.lower()
    assert "Critique" in prompt and "Citation" in prompt
    assert "rough" in prompt.lower() and PRICING_EFFECTIVE_DATE in prompt
