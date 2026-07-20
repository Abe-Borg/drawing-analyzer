"""Pricing + drawing cost-estimate tests (Workstream 4). Hermetic — pure math."""
from __future__ import annotations

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
    _ASSUMED_OUTPUT_TOKENS_PER_SHEET as OUT_PER_SHEET,
    _ASSUMED_PROMPT_TOKENS_PER_SHEET as PROMPT_PER_SHEET,
    _ASSUMED_SYNTHESIS_OUTPUT_TOKENS as SYNTH_OUT,
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
    format_drawing_cost_prompt,
    format_exhaustive_cost_prompt,
)

OPUS = "claude-opus-4-8"


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #


def test_price_for_exact_and_unknown():
    assert price_for(OPUS) == MODEL_PRICING[OPUS]
    assert price_for("claude-sonnet-4-6").input_per_mtok == 3.0
    assert price_for("claude-haiku-4-5").output_per_mtok == 5.0
    assert price_for("totally-made-up") is None
    assert price_for("") is None


def test_price_for_resolves_suffixed_variant():
    # Dated / fast variants (delimited by "-") resolve to the base model's price.
    assert price_for("claude-haiku-4-5-20251001") == MODEL_PRICING["claude-haiku-4-5"]
    assert price_for("claude-opus-4-8-fast") == MODEL_PRICING[OPUS]


def test_price_for_requires_delimiter_not_bare_prefix():
    # A different model that merely starts with a known id must NOT inherit its
    # price — only a "-"-delimited variant resolves (Codex P2).
    assert price_for("claude-opus-4-80") is None
    assert price_for("claude-opus-4-8x") is None


def test_friendly_model_name():
    assert friendly_model_name(OPUS) == "Opus 4.8"
    assert friendly_model_name("claude-sonnet-4-6") == "Sonnet 4.6"
    assert friendly_model_name("mystery") == "mystery"  # falls back to the id


def test_estimate_request_cost_opus():
    # 1M in + 1M out = $5 + $25 = $30.
    assert estimate_request_cost(1_000_000, 1_000_000, model=OPUS) == pytest.approx(30.0)
    # 200k in / 50k out = 0.2*5 + 0.05*25 = 1.0 + 1.25 = 2.25.
    assert estimate_request_cost(200_000, 50_000, model=OPUS) == pytest.approx(2.25)


def test_estimate_request_cost_batch_is_half():
    full = estimate_request_cost(1_000_000, 1_000_000, model=OPUS)
    batch = estimate_request_cost(1_000_000, 1_000_000, model=OPUS, batch=True)
    assert batch == pytest.approx(full * BATCH_DISCOUNT)
    assert batch == pytest.approx(15.0)


def test_estimate_request_cost_unknown_model_is_none():
    assert estimate_request_cost(1_000, 1_000, model="nope") is None


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
    assert synth.input_tokens == base.input_tokens + 10 * OUT_PER_SHEET + PROMPT_PER_SHEET
    assert synth.total_cost > base.total_cost


def test_drawing_estimate_single_sheet_skips_synthesis():
    one = estimate_drawing_set_cost(1, model=OPUS, synthesize=True)
    assert one.output_tokens == 1 * OUT_PER_SHEET  # no synthesis component
    assert one.input_tokens == one.image_tokens + 1 * PROMPT_PER_SHEET


def test_drawing_estimate_unknown_model_keeps_scale_drops_cost():
    est = estimate_drawing_set_cost(5, model="mystery-model", synthesize=False)
    assert est.image_tokens > 0  # tokenizer still estimates image size
    assert est.total_cost is None  # but no dollar figure for an unpriced model


def test_format_prompt_includes_scale_cost_and_proceed():
    est = estimate_drawing_set_cost(8, file_count=3, model=OPUS)
    msg = format_drawing_cost_prompt(est)
    assert "8 drawing sheet(s)" in msg
    assert "from 3 file(s)" in msg
    assert "Opus 4.8" in msg
    assert "$" in msg
    assert "Proceed" in msg


def test_format_prompt_unknown_model_says_unavailable():
    est = estimate_drawing_set_cost(4, model="mystery-model")
    msg = format_drawing_cost_prompt(est)
    assert "unavailable" in msg
    assert "Proceed" in msg


def test_drawing_estimate_focus_adds_sections_and_a_pass():
    base = estimate_drawing_set_cost(10, model=OPUS, synthesize=False)
    focused = estimate_drawing_set_cost(10, model=OPUS, synthesize=False, focus=True)
    digest_out = 10 * (OUT_PER_SHEET + FOCUS_PER_SHEET)
    # Each sheet's digest grows by its focus-findings section, and the focus
    # report re-reads the (grown) digests + one prompt overhead as input.
    assert focused.output_tokens == digest_out + FOCUS_OUT
    assert focused.input_tokens == base.input_tokens + digest_out + PROMPT_PER_SHEET
    assert focused.total_cost > base.total_cost


def test_drawing_estimate_no_focus_is_unchanged():
    # focus=False is the default and must not perturb the existing math.
    assert estimate_drawing_set_cost(10, model=OPUS) == estimate_drawing_set_cost(
        10, model=OPUS, focus=False
    )


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
    synth_input = 10 * OUT_PER_SHEET + PROMPT_PER_SHEET
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
    digest_output = 10 * (OUT_PER_SHEET + FOCUS_PER_SHEET)
    digest_cost = estimate_request_cost(
        digest_input, digest_output, model=OPUS, batch=True
    )
    focus_input = digest_output + PROMPT_PER_SHEET
    focus_cost = estimate_request_cost(
        focus_input, FOCUS_OUT, model=OPUS, batch=False
    )
    assert focused.total_cost == pytest.approx(digest_cost + focus_cost)


def test_image_token_estimate_uses_the_raster_upper_bound():
    # A sheet's rasterness is unknown before rendering, and raster sheets render
    # at the higher target — so the pre-render budget preview must quote the
    # raster target or it would under-quote a scanned-sheet run. It equals the
    # raster-target computation and is >= the reduced vector default.
    from drawing_analyzer import tiling
    from drawing_analyzer.core.tokenizer import estimate_image_tokens
    from drawing_analyzer.pipeline import estimate_image_tokens_for_set

    images_per_sheet = tiling.total_images_for_grid(6, 6)  # 37 -> many-image regime
    raster_edge = tiling.TARGET_LONG_EDGE_PX_RASTER
    vector_edge = tiling.TARGET_LONG_EDGE_PX_DEFAULT
    expected = 3 * images_per_sheet * estimate_image_tokens(raster_edge, raster_edge, model=OPUS)
    vector_bound = 3 * images_per_sheet * estimate_image_tokens(vector_edge, vector_edge, model=OPUS)

    est = estimate_image_tokens_for_set(3, rows=6, cols=6, model=OPUS)
    assert est == expected
    assert est >= vector_bound  # never under-quotes the vector render


def test_format_prompt_batch_mode_notes_batch_and_latency():
    est = estimate_drawing_set_cost(8, file_count=3, model=OPUS, batch=True)
    msg = format_drawing_cost_prompt(est)
    assert "8 drawing sheet(s)" in msg
    assert "Batch" in msg  # names the batch submission + rate
    assert "synchronous text passes are full rate" in msg
    assert "Nothing is sent until you confirm" in msg
    assert "Proceed" in msg


def test_format_prompt_batch_mode_explains_the_shared_queue():
    """The batch dialog teaches the queue mechanic + the overnight worst case."""
    msg = format_drawing_cost_prompt(
        estimate_drawing_set_cost(8, model=OPUS, batch=True)
    )
    low = msg.lower()
    assert "queue" in low
    assert "overnight" in low or "8+ hours" in msg


def test_format_prompt_realtime_mode_gives_per_sheet_time():
    """The real-time dialog sets a per-sheet time expectation and skips the queue talk."""
    msg = format_drawing_cost_prompt(
        estimate_drawing_set_cost(8, model=OPUS, batch=False)
    )
    assert "4–6 minutes per sheet" in msg
    assert "Nothing is sent until you confirm" in msg


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


def test_exhaustive_estimate_prices_actual_verification_model():
    sonnet = "claude-sonnet-4-6"
    est = estimate_exhaustive_run_cost(
        10, model=OPUS, verification_model=sonnet
    )
    verify = {c.stage: c for c in est.components}["Verification"]
    expected = estimate_request_cost(
        verify.input_tokens, verify.output_tokens, model=sonnet, batch=False
    )
    assert verify.cost == pytest.approx(expected)
    assert "Sonnet 4.6" in verify.note


# --------------------------------------------------------------------------- #
# spec_chars pricing — the specs block's transport-dependent cost
# --------------------------------------------------------------------------- #


def test_spec_chars_zero_matches_baseline():
    base = estimate_drawing_set_cost(10, model=OPUS, batch=True, spec_chars=0)
    explicit = estimate_drawing_set_cost(10, model=OPUS, batch=True)
    assert base.total_cost == explicit.total_cost
    assert base.input_tokens == explicit.input_tokens


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
    read = (spec_tokens / 1_000_000) * price.input_per_mtok * 0.10
    expected = write + read * 9  # 1 write + 9 reads across 10 sheets
    assert delta == pytest.approx(expected)


def test_spec_chars_batch_path_costs_more_than_real_time_for_the_same_specs():
    # The whole point of the fix: batch never caches the specs block, so it
    # must never look cheaper than the cached real-time path for the same
    # upload — the confirmation dialog must not under-quote the common case.
    batch = estimate_drawing_set_cost(10, model=OPUS, batch=True, spec_chars=40_000)
    realtime = estimate_drawing_set_cost(10, model=OPUS, batch=False, spec_chars=40_000)
    batch_specs_delta = batch.total_cost - estimate_drawing_set_cost(10, model=OPUS, batch=True).total_cost
    realtime_specs_delta = realtime.total_cost - estimate_drawing_set_cost(10, model=OPUS, batch=False).total_cost
    assert batch_specs_delta > realtime_specs_delta


def test_spec_chars_unknown_model_keeps_total_cost_none():
    est = estimate_drawing_set_cost(5, model="mystery-model", spec_chars=40_000)
    assert est.total_cost is None


def test_spec_chars_unknown_model_with_zero_spec_chars_stays_none():
    # Regression: a naive `(total_cost or 0.0) + spec_cost` guarded only on
    # spec_chars > 0 would leave this case correctly None too, but a guard
    # that forgot to also check `total_cost is None` would coerce it to 0.0.
    est = estimate_drawing_set_cost(5, model="mystery-model", spec_chars=0)
    assert est.total_cost is None
