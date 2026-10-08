"""Pricing + drawing cost-estimate tests (Workstream 4). Hermetic — pure math."""
from __future__ import annotations

import pathlib

import pytest

from drawing_analyzer.core.pricing import (
    BATCH_DISCOUNT,
    MODEL_PRICING,
    estimate_request_cost,
    friendly_model_name,
    price_for,
)
from drawing_analyzer.cost import (
    _ASSUMED_FOCUS_OUTPUT_TOKENS as FOCUS_OUT,
    _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET as FOCUS_PER_SHEET,
    _ASSUMED_DIGEST_TEXT_TOKENS_PER_SHEET as TEXT_PER_SHEET,
    _ASSUMED_PROMPT_TOKENS_PER_SHEET as PROMPT_PER_SHEET,
    _ASSUMED_SYNTHESIS_OUTPUT_TOKENS as SYNTH_OUT,
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
    format_drawing_cost_prompt,
    format_exhaustive_cost_prompt,
)

OPUS = "claude-opus-5-5"
OUT_PER_SHEET = 64_000


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #


def test_price_for_exact_and_unknown():
    assert price_for(OPUS) == MODEL_PRICING[OPUS]
    # Sonnet 5 is $2/$10 — the launch "introductory" rate that Anthropic made
    # standard; the scheduled 2026-09-01 rise to $3/$15 was canceled. Sonnet 4.6
    # keeps the older $3/$15, so the two must not be asserted together.
    assert price_for("claude-sonnet-5").input_per_mtok == 2.0
    assert price_for("claude-sonnet-5").output_per_mtok == 10.0
    assert price_for("claude-sonnet-4-6").input_per_mtok == 3.0
    assert price_for("claude-haiku-4-5").output_per_mtok == 5.0
    assert price_for("totally-made-up") is None
    assert price_for("") is None


def test_price_for_resolves_suffixed_variant():
    # Dated / fast variants (delimited by "-") resolve to the base model's price.
    assert price_for("claude-haiku-4-5-20251001") == MODEL_PRICING["claude-haiku-4-5"]
    assert price_for("claude-opus-5-5-fast") == MODEL_PRICING[OPUS]
    assert price_for("claude-opus-5-fast") == MODEL_PRICING["claude-opus-5"]
    assert price_for("claude-opus-4-8-fast") == MODEL_PRICING["claude-opus-4-8"]


def test_price_for_requires_delimiter_not_bare_prefix():
    # A different model that merely starts with a known id must NOT inherit its
    # price — only a "-"-delimited variant resolves (Codex P2).
    assert price_for("claude-opus-4-80") is None
    assert price_for("claude-opus-4-8x") is None
    assert price_for("claude-opus-50") is None
    assert price_for("claude-sonnet-51") is None


def test_friendly_model_name():
    assert friendly_model_name(OPUS) == "Opus 5.5"
    assert friendly_model_name("claude-opus-5") == "Opus 5"
    assert friendly_model_name("claude-sonnet-5-5") == "Sonnet 5.5"
    assert friendly_model_name("claude-sonnet-5") == "Sonnet 5"
    assert friendly_model_name("claude-sonnet-4-6") == "Sonnet 4.6"
    assert friendly_model_name("mystery") == "mystery"  # falls back to the id


def test_estimate_request_cost_opus():
    # Opus 5.5: 1M in + 1M out = $4 + $20 = $24.
    assert estimate_request_cost(1_000_000, 1_000_000, model=OPUS) == pytest.approx(24.0)
    # 200k in / 50k out = 0.2*4 + 0.05*20 = 0.8 + 1.0 = 1.8.
    assert estimate_request_cost(200_000, 50_000, model=OPUS) == pytest.approx(1.8)
    # Opus 5 keeps its own $5 / $25 rate.
    assert estimate_request_cost(1_000_000, 1_000_000, model="claude-opus-5") == pytest.approx(30.0)


def test_estimate_request_cost_batch_is_half():
    full = estimate_request_cost(1_000_000, 1_000_000, model=OPUS)
    batch = estimate_request_cost(1_000_000, 1_000_000, model=OPUS, batch=True)
    assert batch == pytest.approx(full * BATCH_DISCOUNT)
    assert batch == pytest.approx(12.0)


def test_estimate_request_cost_unknown_model_is_none():
    assert estimate_request_cost(1_000, 1_000, model="nope") is None


@pytest.mark.parametrize("input_tokens,output_tokens,expected", [
    (100_000, 2_000, 0.011),
    (100_001, 2_000, 0.0550005),
    (1_000, 128_000, 0.0641),  # output size never selects the tier
])
@pytest.mark.parametrize("batch", [False, True])
def test_haiku_request_tier_prices_all_tokens_at_the_prompt_boundary(input_tokens, output_tokens, expected, batch):
    assert estimate_request_cost(
        input_tokens, output_tokens, model="claude-haiku-5-5-20261007", batch=batch,
    ) == pytest.approx(expected * (0.5 if batch else 1))


@pytest.mark.parametrize("model,reuse,no_reuse", [
    ("claude-opus-5-5", 5.20, 10.00),
    ("claude-sonnet-5-5", 2.70, 5.00),
    ("claude-haiku-5-5", 0.675, 1.25),
    ("claude-opus-5", 6.75, 12.50),
])
def test_estimator_uses_each_models_cache_read_rate(model, reuse, no_reuse):
    from drawing_analyzer.cost import _critique_prefix_costs, _specs_cost_contribution

    assert _critique_prefix_costs(
        sheet_count=1, prefix_tokens=1_000_000, output_tokens=0,
        model=model, batch=False, runs=2,
    ) == pytest.approx((reuse, no_reuse))
    tokens, spec_cost = _specs_cost_contribution(
        spec_chars=4_000_000, sheet_count=2, model=model, batch=False,
    )
    assert tokens == 2_000_000
    assert spec_cost == pytest.approx(reuse)


@pytest.mark.parametrize("prefix,expected_reuse,expected_misses,expected_batch", [
    (100_000, 0.0155, 0.027, 0.011),
    (100_001, 0.077500675, 0.13500125, 0.0550005),
])
def test_haiku_critique_output_and_cache_use_the_complete_request_tier(
    prefix, expected_reuse, expected_misses, expected_batch,
):
    from drawing_analyzer.cost import _critique_prefix_costs

    assert _critique_prefix_costs(
        prefix_tokens=prefix, output_tokens=2_000, sheet_count=4, runs=2,
        model="claude-haiku-5-5", batch=False,
    ) == pytest.approx((expected_reuse * 4, expected_misses * 4))
    assert _critique_prefix_costs(
        prefix_tokens=prefix, output_tokens=2_000, sheet_count=4, runs=2,
        model="claude-haiku-5-5", batch=True,
    ) == pytest.approx((expected_batch * 4, expected_batch * 4))


# --------------------------------------------------------------------------- #
# drawing-set estimate
# --------------------------------------------------------------------------- #


def test_drawing_estimate_no_synthesis_token_math():
    est = estimate_drawing_set_cost(10, file_count=2, model=OPUS, synthesize=False)
    assert est.sheet_count == 10 and est.file_count == 2
    assert est.image_tokens > 0
    assert est.input_tokens == est.image_tokens + 10 * PROMPT_PER_SHEET
    assert est.output_tokens == 10 * OUT_PER_SHEET
    assert est.total_cost == pytest.approx(
        estimate_request_cost(est.input_tokens, est.output_tokens, model=OPUS)
    )
    assert est.total_cost > 0


def test_drawing_estimate_synthesis_adds_a_pass():
    base = estimate_drawing_set_cost(10, model=OPUS, synthesize=False)
    synth = estimate_drawing_set_cost(10, model=OPUS, synthesize=True)
    # Synthesis re-reads the digests (10*OUT) + one prompt overhead as input,
    # and emits the overview as output.
    assert synth.output_tokens == base.output_tokens + SYNTH_OUT
    assert synth.input_tokens == base.input_tokens + 10 * TEXT_PER_SHEET + PROMPT_PER_SHEET
    assert synth.total_cost > base.total_cost


def test_drawing_estimate_single_sheet_skips_synthesis():
    one = estimate_drawing_set_cost(1, model=OPUS, synthesize=True)
    assert one.output_tokens == 1 * OUT_PER_SHEET  # no synthesis component
    assert one.input_tokens == one.image_tokens + 1 * PROMPT_PER_SHEET


@pytest.mark.parametrize("sheet_inputs,spec_tokens", [
    ([60_000, 60_000], 0),  # sum exceeds threshold; neither request does
    ([60_000, 140_000], 0),  # averaging must not hide a long request
    ([99_999, 100_000, 100_001], 0),
    ([96_000, 96_000], 4_000),  # complete prompt equals the threshold
    ([96_000, 96_000], 4_001),  # cached specifications push both over it
])
@pytest.mark.parametrize("batch", [False, True])
def test_digest_previews_choose_tiers_per_complete_sheet_request(monkeypatch, sheet_inputs, spec_tokens, batch):
    from drawing_analyzer import cost as cost_module

    monkeypatch.setattr(cost_module, "_image_token_requests_for", lambda *args, **kwargs: (
        tuple(tokens - PROMPT_PER_SHEET for tokens in sheet_inputs), True, 0,
    ))
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_RUNS", "2")
    standard = estimate_drawing_set_cost(
        len(sheet_inputs), model="claude-haiku-5-5", batch=batch,
        synthesize=False, spec_chars=spec_tokens * 4,
    )
    exhaustive = estimate_exhaustive_run_cost(
        len(sheet_inputs), model="claude-haiku-5-5", batch=batch, spec_chars=spec_tokens * 4,
    )
    digest = next(c for c in exhaustive.components if c.stage == "Digest")
    for estimate in (standard, digest):
        for low in (False, True):
            output_per_sheet = (
                estimate.output_tokens_low if low else estimate.output_tokens
            ) // len(sheet_inputs)
            expected = 0
            for index, tokens in enumerate(sheet_inputs):
                tier = 5 if tokens + spec_tokens > 100_000 else 1
                cache_multiplier = 1 if batch else (1.25 if index == 0 else 0.1)
                expected += tier * (
                    (tokens + spec_tokens * cache_multiplier) * 0.1
                    + output_per_sheet * 0.5
                ) / 1_000_000 * (0.5 if batch else 1)
            actual = estimate.low_cost if low else (
                estimate.total_cost if hasattr(estimate, "total_cost") else estimate.cost
            )
            assert actual == pytest.approx(expected)
    critique = next(c for c in exhaustive.components if c.stage.startswith("Critique"))
    for low in (False, True):
        output_per_read = (critique.output_tokens_low if low else critique.output_tokens) // (2 * len(sheet_inputs))
        prefix_multiplier = 2 if batch else (1.35 if low else 2.5)
        expected = sum(
            (5 if tokens > 100_000 else 1)
            * (tokens * prefix_multiplier * 0.1 + 2 * output_per_read * 0.5)
            / 1_000_000 * (0.5 if batch else 1)
            for tokens in sheet_inputs
        )
        assert (critique.low_cost if low else critique.cost) == pytest.approx(expected)


# spec_chars=0 is the regression case: a naive `(total_cost or 0.0) + spec_cost`
# guarded only on spec_chars > 0 would leave it correctly None too, but a guard
# that forgot to also check `total_cost is None` would coerce it to 0.0.
@pytest.mark.parametrize("spec_chars", [0, 40_000])
def test_drawing_estimate_unknown_model_keeps_scale_drops_cost(spec_chars):
    est = estimate_drawing_set_cost(5, model="mystery-model", spec_chars=spec_chars)
    assert est.image_tokens > 0  # tokenizer still estimates image size
    assert est.total_cost is None  # but no dollar figure for an unpriced model


def test_drawing_estimate_focus_adds_sections_and_a_pass():
    base = estimate_drawing_set_cost(10, model=OPUS, synthesize=False)
    focused = estimate_drawing_set_cost(10, model=OPUS, synthesize=False, focus=True)
    digest_out = 10 * OUT_PER_SHEET
    digest_text = 10 * (TEXT_PER_SHEET + FOCUS_PER_SHEET)
    # Each sheet's digest grows by its focus-findings section, and the focus
    # report re-reads the (grown) digests + one prompt overhead as input.
    assert focused.output_tokens == digest_out + FOCUS_OUT
    assert focused.input_tokens == base.input_tokens + digest_text + PROMPT_PER_SHEET
    assert focused.total_cost > base.total_cost


def test_drawing_estimate_batch_halves_digest_cost_only():
    full = estimate_drawing_set_cost(
        10, file_count=2, model=OPUS, batch=False, synthesize=False
    )
    batch = estimate_drawing_set_cost(
        10, file_count=2, model=OPUS, batch=True, synthesize=False
    )
    # With no synchronous text pass, only the digest remains and halves exactly.
    assert batch.input_tokens == full.input_tokens
    assert batch.output_tokens == full.output_tokens
    assert batch.batch is True and full.batch is False
    assert batch.total_cost == pytest.approx(full.total_cost * BATCH_DISCOUNT)


def test_drawing_estimate_batch_keeps_synthesis_at_realtime_rate():
    without = estimate_drawing_set_cost(
        10, model=OPUS, batch=True, synthesize=False
    )
    with_synthesis = estimate_drawing_set_cost(
        10, model=OPUS, batch=True, synthesize=True
    )
    synth_input = 10 * TEXT_PER_SHEET + PROMPT_PER_SHEET
    expected_delta = estimate_request_cost(
        synth_input, SYNTH_OUT, model=OPUS, batch=False
    )
    assert with_synthesis.total_cost - without.total_cost == pytest.approx(expected_delta)


def test_drawing_estimate_batch_keeps_focus_report_at_realtime_rate():
    # Compare against a digest-only estimate whose output includes the same
    # focus sections; the remaining delta is the synchronous focus report.
    focused = estimate_drawing_set_cost(
        10, model=OPUS, batch=True, synthesize=False, focus=True
    )
    digest_input = focused.image_tokens + 10 * PROMPT_PER_SHEET
    digest_output = 10 * OUT_PER_SHEET
    digest_cost = estimate_request_cost(
        digest_input, digest_output, model=OPUS, batch=True
    )
    focus_input = 10 * (TEXT_PER_SHEET + FOCUS_PER_SHEET) + PROMPT_PER_SHEET
    focus_cost = estimate_request_cost(
        focus_input, FOCUS_OUT, model=OPUS, batch=False
    )
    assert focused.total_cost == pytest.approx(digest_cost + focus_cost)


def test_image_token_estimate_uses_the_raster_upper_bound():
    # A sheet's rasterness is unknown before rendering, and raster sheets render
    # at the higher target — so the pre-render budget preview must bound a
    # scanned sheet's render, not only a vector one's, at any page shape. The
    # 17.9x10 in page renders 2576x1440 images at 1x1, which cost the full
    # per-image cap although a 2576 px square resizes to fewer tokens.
    from drawing_analyzer import tiling
    from drawing_analyzer.core.tokenizer import estimate_image_tokens_total
    from drawing_analyzer.pipeline import estimate_image_tokens_for_set

    for rows, cols in ((6, 6), (1, 1)):
        est = estimate_image_tokens_for_set(3, rows=rows, cols=cols, model=OPUS)
        for w, h in ((34, 44), (44, 34), (30, 30), (8.5, 11), (17.9, 10)):
            for raster in (True, False):
                sizes = tiling.image_pixel_sizes(w * 72, h * 72, rows=rows, cols=cols,
                                                 is_raster=raster)
                measured = 3 * estimate_image_tokens_total(sizes, model=OPUS)
                assert measured <= est, (rows, cols, w, h, raster)


def test_exhaustive_estimate_carries_transport_and_prompt_reflects_it():
    """ExhaustiveCostEstimate.batch propagates; the dialog's timing note matches it."""
    batch_est = estimate_exhaustive_run_cost(6, file_count=2, model=OPUS, batch=True)
    rt_est = estimate_exhaustive_run_cost(6, file_count=2, model=OPUS, batch=False)
    assert batch_est.batch is True and rt_est.batch is False

    batch_msg = format_exhaustive_cost_prompt(batch_est)
    assert "queue" in batch_msg.lower()
    assert "overnight" in batch_msg.lower() or "8+ hours" in batch_msg

    rt_msg = format_exhaustive_cost_prompt(rt_est)
    assert "4–6 minutes per sheet" in rt_msg
    assert "no queue" in rt_msg.lower()


def test_exhaustive_estimate_shows_realtime_synthesis_and_focus():
    est = estimate_exhaustive_run_cost(6, model=OPUS, batch=True, focus=True)
    by_stage = {c.stage: c for c in est.components}
    assert by_stage["Digest"].transport == "batch"
    assert by_stage["Synthesis"].transport == "real-time"
    assert by_stage["Focus report"].transport == "real-time"


def test_exhaustive_hybrid_prices_digest_realtime_and_critique_batch():
    hybrid = estimate_exhaustive_run_cost(
        6, model=OPUS, batch=False, critique_batch=True,
    )
    by_stage = {c.stage: c for c in hybrid.components}
    assert by_stage["Digest"].transport == "real-time"
    assert by_stage["Critique ×2 (per sheet)"].transport == "batch"
    assert hybrid.batch is False and hybrid.critique_batch is True
    assert "Hybrid mode" in format_exhaustive_cost_prompt(hybrid)


def test_exhaustive_legacy_transport_argument_still_controls_both_reads():
    economy = estimate_exhaustive_run_cost(2, model=OPUS, batch=True)
    fast = estimate_exhaustive_run_cost(2, model=OPUS, batch=False)
    assert economy.critique_batch is True
    assert fast.critique_batch is False


@pytest.mark.parametrize("model,label", [("claude-sonnet-5", "Sonnet 5"), ("claude-haiku-5-5", "Haiku 5.5")])
def test_exhaustive_estimate_prices_actual_verification_model(model, label):
    est = estimate_exhaustive_run_cost(
        10, model=OPUS, verification_model=model
    )
    verify = {c.stage: c for c in est.components}["Verification"]
    expected = 200 * estimate_request_cost(
        1_500, 1_400, model=model, batch=False
    )
    assert verify.cost == pytest.approx(expected)
    assert label in verify.note


@pytest.mark.parametrize("refs", [3, 30])
@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-haiku-5-5"])
def test_citation_estimate_uses_runtime_ref_cap_and_clause_fetch_limit(monkeypatch, refs, model):
    from drawing_analyzer.citation_check import citation_tools
    from drawing_analyzer.core.pricing import WEB_SEARCH_COST_PER_USE

    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MODEL", model)
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", str(refs))
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_MAX_USES", "1")
    est = estimate_exhaustive_run_cost(100)
    row = next(c for c in est.components if c.stage == "Citation checks")
    fetch = next(t for t in citation_tools(est.stage_models.citation) if t["name"] == "web_fetch")
    assert fetch["max_content_tokens"] == 4_000
    assert row.input_tokens == refs * (2_000 + 4_000)
    assert row.output_tokens == refs * 1_400
    # Each reference uses a short request, even when the stage exceeds 100k.
    expected = refs * estimate_request_cost(6_000, 1_400, model=model, batch=False)
    assert row.cost == pytest.approx(expected + refs * float(WEB_SEARCH_COST_PER_USE))
    assert f"{refs} eligible normalized ref(s), per-run cap {refs}" in row.note
    assert "1 searches/ref" in row.note
    assert "4,000 tokens" in row.note
    assert "claim chunks/resumes can cost more" in row.note


def test_zero_citation_cap_quotes_no_citation_spend(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "0")
    est = estimate_exhaustive_run_cost(100)
    row = next(c for c in est.components if c.stage == "Citation checks")
    assert row.cost == row.input_tokens == row.output_tokens == 0
    assert "per-run cap 0" in row.note


def test_search_only_citation_model_quotes_no_fetch_input(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MODEL", "claude-opus-5")
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "2")
    est = estimate_exhaustive_run_cost(100)
    row = next(c for c in est.components if c.stage == "Citation checks")
    assert row.input_tokens == 2 * 2_000
    assert "fetch" not in row.note


def test_exhaustive_estimate_prices_actual_critique_model(monkeypatch):
    """Critique is the largest component; it must be priced at its own model.

    The estimate used to price nine of eleven components at the single ``model``
    argument, so a critique routed to Sonnet 5 was quoted at Opus 5 rates — an
    over-quote on the biggest line in the dialog.
    """
    sonnet = "claude-sonnet-5"
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_MODEL", sonnet)
    est = estimate_exhaustive_run_cost(10, model=OPUS)
    crit = {c.stage: c for c in est.components}["Critique ×2 (per sheet)"]
    expected = estimate_request_cost(
        crit.input_tokens, crit.output_tokens, model=sonnet, batch=est.critique_batch
    )
    assert crit.cost == pytest.approx(expected)
    # And the quote is genuinely cheaper than the same run on the review model.
    monkeypatch.delenv("DRAWING_ANALYZER_CRITIQUE_MODEL")
    on_opus = {c.stage: c for c in estimate_exhaustive_run_cost(10, model=OPUS).components}
    assert crit.cost < on_opus["Critique ×2 (per sheet)"].cost


def test_stage_models_resolve_through_the_runtime_resolvers(monkeypatch):
    """A ``DRAWING_ANALYZER_*_MODEL`` override reaches the estimate."""
    from drawing_analyzer.cost import resolve_stage_models

    monkeypatch.setenv("DRAWING_ANALYZER_SYNTHESIS_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("DRAWING_ANALYZER_CROSS_QC_MODEL", "claude-sonnet-5")
    models = resolve_stage_models(model=OPUS)
    assert models.synthesis == "claude-haiku-4-5"
    assert models.cross_qc == "claude-sonnet-5"
    assert models.digest == OPUS  # the threaded review model stands in for digest
    # ``distinct`` is first-appearance order with no repeats — it drives the
    # header sentence, so a duplicate would read as a stutter.
    assert len(models.distinct) == len(set(models.distinct))
    assert models.distinct[0] == OPUS


def test_exhaustive_total_is_none_when_any_stage_is_unpriced(monkeypatch):
    """An unpriced stage must void the total, never quietly drop out of it.

    Dropping it publishes the sum of the *remaining* stages as if it were the
    run's cost. The stage most likely to be unpriced is the one behind
    ``DRAWING_ANALYZER_CRITIQUE_MODEL`` — both the advertised cost lever and the
    largest single component — so the failure mode is a confident, badly
    under-stated number on exactly the configuration a user is experimenting
    with. Measured before the fix: ~$21 quoted for a 40-sheet run whose critique
    line alone is ~$37. Same rule as ``estimate_drawing_set_cost`` and
    ``RunUsage.total_estimated_cost``.
    """
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_MODEL", "claude-some-future-model")
    est = estimate_exhaustive_run_cost(40, model=OPUS)

    crit = {c.stage: c for c in est.components}["Critique ×2 (per sheet)"]
    assert crit.cost is None                 # the component itself is unpriced
    assert crit.input_tokens > 0             # ...but its token scale still shows
    assert est.low_cost is None and est.high_cost is None

    # And the message names which stage, so the reader is not sent looking at
    # the review model when an env var redirected some other stage.
    msg = format_exhaustive_cost_prompt(est)
    assert "unavailable" in msg
    assert "Critique ×2 (per sheet)" in msg


# --------------------------------------------------------------------------- #
# spec_chars pricing — the specs block's transport-dependent cost
# --------------------------------------------------------------------------- #


def test_spec_chars_batch_path_never_gets_the_cache_discount():
    # The real batch-item build (batch_digest.py) always passes
    # cache_specs=False — a parallel batch has no reader for a cache write —
    # so the batch estimate must price specs as flat, uncached, per-sheet
    # input at the batch discount rate, NOT the write-once/read-many model.
    no_specs = estimate_drawing_set_cost(10, model=OPUS, batch=True, spec_chars=0)
    with_specs = estimate_drawing_set_cost(10, model=OPUS, batch=True, spec_chars=40_000)
    delta = with_specs.total_cost - no_specs.total_cost
    spec_tokens = 40_000 // 4  # _SPEC_CHARS_PER_TOKEN_ESTIMATE
    price = MODEL_PRICING[OPUS]
    expected = (spec_tokens * 10 / 1_000_000) * price.input_per_mtok * BATCH_DISCOUNT
    assert delta == pytest.approx(expected)


def test_spec_chars_real_time_path_uses_cache_write_once_read_many():
    no_specs = estimate_drawing_set_cost(10, model=OPUS, batch=False, spec_chars=0)
    with_specs = estimate_drawing_set_cost(10, model=OPUS, batch=False, spec_chars=40_000)
    delta = with_specs.total_cost - no_specs.total_cost
    spec_tokens = 40_000 // 4
    price = MODEL_PRICING[OPUS]
    write = (spec_tokens / 1_000_000) * price.input_per_mtok * 1.25
    read = (spec_tokens / 1_000_000) * price.input_per_mtok * price.cache_read_multiplier
    expected = write + read * 9  # 1 write + 9 reads across 10 sheets
    assert delta == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# WP-04 §9.2 — the dialog copy must describe the transport it is pricing
# --------------------------------------------------------------------------- #
#
# The arithmetic was already right: ``_specs_cost_contribution`` prices the
# batch branch as ordinary batch input and says so in its own docstring. Only
# the operator-facing sentence was wrong — it promised a ~0.1x prompt-cache read
# on every transport — and it was wrong in the operator's favour, which is the
# direction that gets noticed on the invoice rather than in review. So these
# tests pin the copy AND pin that the priced totals did not move: a "fix" that
# changed a number here would be correcting arithmetic the plan established is
# already correct.


def _dialog(*, batch: bool, spec_chars: int = 40_000) -> str:
    return format_drawing_cost_prompt(
        estimate_drawing_set_cost(10, file_count=1, model=OPUS, batch=batch,
                                  spec_chars=spec_chars)
    )


def _exhaustive_dialog(*, batch: bool, critique_batch: bool,
                       spec_chars: int = 40_000) -> str:
    return format_exhaustive_cost_prompt(
        estimate_exhaustive_run_cost(10, file_count=1, model=OPUS, batch=batch,
                                     critique_batch=critique_batch,
                                     spec_chars=spec_chars)
    )


# Wording every dialog carries: the estimate is not a ceiling, and caching is per
# stage, so a digest hit implies nothing about the set-level passes.
_EVERY_DIALOG = ("not a cap", "caches separately", "whole set")


@pytest.mark.parametrize("text_fn,present,absent", [
    pytest.param(lambda: _dialog(batch=False), [
        "10 drawing sheet(s)", "from 1 file(s)", "Opus 5", "$",
        "4–6 minutes per sheet", "Nothing is sent until you confirm.",
        # Parallel workers and expiry can both force additional writes: the
        # discount is real, but not guaranteed, and the exception is named.
        "0.1x", "usually cached", "write rate",
        "local result cache", *_EVERY_DIALOG,
    ], [], id="real-time"),
    pytest.param(lambda: _dialog(batch=True), [
        "10 drawing sheet(s)", "Batch", "synchronous text passes are full rate",
        "queue", "overnight", "Nothing is sent until you confirm",
        # §9.3 case 8: the batch path sets no breakpoint, so nothing is cached.
        "ordinary batch input",
        "adaptive thinking, which is billed as output", "No real run usage records",
        "local result cache", *_EVERY_DIALOG,
    ], ["0.1x", "cached after the first"], id="batch"),
    pytest.param(lambda: format_drawing_cost_prompt(
        estimate_drawing_set_cost(4, model="mystery-model")),
        ["unavailable"], [], id="unpriced-model"),
    # The transport branch must not leak into a run that uploaded no specs.
    pytest.param(lambda: _dialog(batch=False, spec_chars=0), [],
                 ["Project specifications", "ordinary batch input"], id="real-time-no-specs"),
    pytest.param(lambda: _dialog(batch=True, spec_chars=0), [],
                 ["Project specifications", "ordinary batch input"], id="batch-no-specs"),
])
def test_drawing_dialog_copy(text_fn, present, absent):
    text = text_fn()
    for phrase in present:
        assert phrase in text, phrase
    for phrase in absent:
        assert phrase not in text, phrase
    # §9.2: keep the existing pre-send confirmation behavior.
    assert text.rstrip().endswith("Proceed with the analysis?")


@pytest.mark.parametrize("batch,critique_batch,present,absent", [
    pytest.param(True, True, [
        "ordinary batch input",
        "adaptive thinking, which is billed as output", "No real run usage records",
    ], [], id="economy"),
    # Hybrid is the mode where digest and critique transport disagree, and a
    # naive implementation keyed on the wrong one is only visible here.
    pytest.param(False, True, ["usually cached", "Hybrid mode"], ["ordinary batch input"],
                 id="hybrid"),
    pytest.param(False, False, ["usually cached"], ["ordinary batch input"], id="fast"),
])
def test_exhaustive_dialog_copy_follows_the_digest_transport(batch, critique_batch, present, absent):
    """Specifications ride the DIGEST prompt only, so the sentence must follow
    ``batch``, not ``critique_batch``."""
    text = _exhaustive_dialog(batch=batch, critique_batch=critique_batch)
    # The header must not claim one model does all the work.
    header = text.splitlines()[0]
    assert "Opus 5" in header
    assert "Sonnet 5" in header  # identity / harvest / citation / verification
    for phrase in (*present, *_EVERY_DIALOG):
        assert phrase in text, phrase
    for phrase in absent:
        assert phrase not in text, phrase
    assert text.rstrip().endswith("Proceed with the exhaustive review?")


def test_specifications_add_the_same_charge_to_both_band_ends():
    """Thinking bands must preserve transport-specific specification pricing."""
    for estimator in (estimate_drawing_set_cost, estimate_exhaustive_run_cost):
        for batch in (True, False):
            plain = estimator(10, model=OPUS, batch=batch)
            specs = estimator(10, model=OPUS, batch=batch, spec_chars=40_000)
            expected = 0.20 if batch else 0.068
            assert specs.low_cost - plain.low_cost == pytest.approx(expected)
            assert specs.high_cost - plain.high_cost == pytest.approx(expected)


# --------------------------------------------------------------------------- #
# 14c: what the app promises about waiting must follow what the engine does.
#
# The cost dialog, the GUI and the help content all told the user a batch run
# "can run overnight (8+ hours)" while the collector detached at four. The
# wording was not wrong about the queue — it was wrong about us.
# --------------------------------------------------------------------------- #


def test_the_wait_sentence_is_derived_from_the_engine_bound(monkeypatch):
    from drawing_analyzer import batch_digest, cost as cost_mod

    assert "24 hours" in cost_mod._batch_wait_sentence()
    monkeypatch.setenv("DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS", "6")
    assert "6 hours" in cost_mod._batch_wait_sentence()
    # A fractional override is quoted as itself, not rounded to a lie.
    monkeypatch.setenv("DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS", "1.5")
    assert "1.5 hours" in cost_mod._batch_wait_sentence()
    assert batch_digest._batch_max_elapsed_seconds() == 5400.0


def test_no_user_facing_string_promises_a_longer_wait_than_the_engine_allows():
    # The drift guard. Several strings claim "(8+ hours)"; that is only honest
    # while the bound is at least 8. Lower the bound without moving the prose
    # and this fails, which is the point — the two must move together.
    import re

    import drawing_analyzer
    from drawing_analyzer import batch_digest

    bound_hours = batch_digest._batch_max_elapsed_seconds() / 3600.0
    claim = re.compile(r"(\d+)\+?\s*hours")
    # Read by path, not by import: gui.py needs tkinter, which neither this
    # container nor the Linux CI job has.
    pkg = pathlib.Path(drawing_analyzer.__file__).parent
    sources = [
        (pkg / name).read_text(encoding="utf-8")
        for name in ("cost.py", "gui.py", "help_content.py", "pipeline.py")
    ]

    promised = {int(m) for src in sources for m in claim.findall(src)}
    assert promised, "expected at least one hour claim to guard"
    assert max(promised) <= bound_hours, (
        f"user-facing text promises up to {max(promised)}h but the engine "
        f"waits {bound_hours}h"
    )


@pytest.mark.parametrize("batch", [False, True])
def test_standard_band_prices_thinking_as_output_at_both_ends(batch):
    est = estimate_drawing_set_cost(1, model=OPUS, batch=batch)
    assert est.output_tokens_low == 4_000
    assert est.output_tokens == 64_000
    # Opus 5.5 bills $20/M output ($10/M in Batch). The input is identical
    # at both ends; none of this output allowance receives an input-cache rate.
    rate = 10 if batch else 20
    assert est.high_cost - est.low_cost == pytest.approx(60_000 / 1_000_000 * rate)
    observed = estimate_request_cost(est.input_tokens, 16_000 + 2_000, model=OPUS, batch=batch)
    assert est.low_cost < observed < est.high_cost
    assert est.total_cost == est.high_cost  # compatibility field is the upper end


def test_thinking_is_not_sent_back_as_synthesis_or_focus_input():
    est = estimate_drawing_set_cost(2, model=OPUS, focus=True)
    assert est.input_tokens - est.image_tokens == 2 * 800 + 2 * (2 * 2_500 + 800)
    assert est.output_tokens_low == 2 * 4_500 + 2_000 + 2_000
    assert est.output_tokens == 2 * 64_000 + 2_000 + 2_000


def test_read_bands_obey_model_output_ceiling(monkeypatch):
    from dataclasses import replace
    from drawing_analyzer.core import api_config

    caps = api_config.model_capabilities(OPUS)
    monkeypatch.setitem(api_config._MODEL_CAPABILITIES, OPUS, replace(caps, max_output_tokens=8_000))
    est = estimate_drawing_set_cost(1, model=OPUS)
    assert est.output_tokens == 8_000
    full = estimate_exhaustive_run_cost(1, model=OPUS)
    critique = next(c for c in full.components if c.stage.startswith("Critique"))
    assert critique.output_tokens == 2 * 8_000


@pytest.mark.parametrize("batch,critique_batch", [(True, True), (False, False), (False, True)])
def test_exhaustive_band_sums_each_stage_once(batch, critique_batch):
    est = estimate_exhaustive_run_cost(39, model=OPUS, batch=batch, critique_batch=critique_batch)
    digest, critique = est.components[0], next(c for c in est.components if c.stage.startswith("Critique"))
    assert (digest.output_tokens_low, digest.output_tokens) == (39 * 4_000, 39 * 64_000)
    assert (critique.output_tokens_low, critique.output_tokens) == (2 * 39 * 4_000, 2 * 39 * 64_000)
    assert est.low_cost == pytest.approx(sum(c.low_cost for c in est.components))
    assert est.high_cost == pytest.approx(sum(c.cost for c in est.components))
    assert est.low_cost < est.high_cost


def test_findings_band_includes_recorded_standard_volume_and_exhaustive_growth():
    est = estimate_exhaustive_run_cost(39, model=OPUS)
    verify = next(c for c in est.components if c.stage == "Verification")
    assert verify.output_tokens_low == 39 * 8 * 1_400
    assert verify.output_tokens == 39 * 20 * 1_400
    assert 287 < verify.output_tokens_low / 1_400
    assert "8–20 findings per sheet" in format_exhaustive_cost_prompt(est)


@pytest.mark.parametrize("investigation_model", [OPUS, "claude-haiku-5-5"])
def test_investigation_prices_six_evidence_requests_and_the_closing_call(monkeypatch, investigation_model):
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_FINDINGS", "1")
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MODEL", investigation_model)
    est = estimate_exhaustive_run_cost(39, model=OPUS)
    inv = next(c for c in est.components if c.stage == "Investigation")
    assert inv.output_tokens_low == 4 * 1_500
    assert inv.output_tokens == 7 * 16_000
    assert inv.input_tokens_low == 4 * 6_000
    assert inv.input_tokens == 7 * 6_000 + 21 * (4_000 + 16_000)
    if investigation_model == "claude-haiku-5-5":
        # The first five prompts are 6k..86k; only the 106k and 126k closing
        # prompts use the higher tier. Their output takes that tier too.
        assert inv.cost == pytest.approx(0.259)
        assert inv.low_cost == pytest.approx(0.0054)
    assert "6 evidence requests + closing verdict" in inv.note


def test_investigation_honors_round_budget_and_resolved_model(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_ROUNDS", "2")
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MAX_FINDINGS", "1")
    monkeypatch.setenv("DRAWING_ANALYZER_INVESTIGATION_MODEL", "claude-sonnet-5")
    inv = next(c for c in estimate_exhaustive_run_cost(39, model=OPUS).components if c.stage == "Investigation")
    assert inv.output_tokens == 3 * 16_000
    assert inv.output_tokens_low == 3 * 1_500
    assert inv.cost == pytest.approx(estimate_request_cost(inv.input_tokens, inv.output_tokens, model="claude-sonnet-5"))


@pytest.mark.parametrize("cross_model", [OPUS, "claude-haiku-5-5"])
@pytest.mark.parametrize("sheets,min_calls", [(40, 1), (41, 3), (81, 4)])
def test_cross_qc_accounts_for_shards_and_reconciliation(monkeypatch, sheets, min_calls, cross_model):
    monkeypatch.setenv("DRAWING_ANALYZER_CROSS_QC_MODEL", cross_model)
    cross = next(c for c in estimate_exhaustive_run_cost(sheets, model=OPUS).components if c.stage == "Cross-sheet QC")
    assert cross.output_tokens_low == min_calls * 2_000
    assert cross.output_tokens >= min_calls * 16_000
    if sheets > 40:
        assert "discipline shard(s)" in cross.note
        assert "reconciliation call(s)" in cross.note
        assert cross.input_tokens > cross.input_tokens_low
    if cross_model == "claude-haiku-5-5":
        if sheets == 40:
            # One 120.8k prompt is long; its entire output costs 5x too.
            assert cross.cost == pytest.approx(0.1004)
        if sheets == 41:
            # High: 41 short 3.8k maps + 36 short 62.03k reconciliations.
            # Low: one long 120.8k map, a short 3.8k tail and a 14.03k reconcile.
            assert cross.cost == pytest.approx(0.854888)
            assert cross.low_cost == pytest.approx(0.069183)


def test_unknown_standard_stage_voids_both_band_ends(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_SYNTHESIS_MODEL", "unknown-price")
    est = estimate_drawing_set_cost(2, model=OPUS)
    assert est.low_cost is None and est.high_cost is None
