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

OPUS = "claude-opus-5"


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
    assert price_for("claude-opus-5-fast") == MODEL_PRICING[OPUS]
    assert price_for("claude-opus-4-8-fast") == MODEL_PRICING["claude-opus-4-8"]


def test_price_for_requires_delimiter_not_bare_prefix():
    # A different model that merely starts with a known id must NOT inherit its
    # price — only a "-"-delimited variant resolves (Codex P2).
    assert price_for("claude-opus-4-80") is None
    assert price_for("claude-opus-4-8x") is None
    assert price_for("claude-opus-50") is None
    assert price_for("claude-sonnet-51") is None


def test_friendly_model_name():
    assert friendly_model_name(OPUS) == "Opus 5"
    assert friendly_model_name("claude-sonnet-5") == "Sonnet 5"
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
    assert "Opus 5" in msg
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
    sonnet = "claude-sonnet-5"
    est = estimate_exhaustive_run_cost(
        10, model=OPUS, verification_model=sonnet
    )
    verify = {c.stage: c for c in est.components}["Verification"]
    expected = estimate_request_cost(
        verify.input_tokens, verify.output_tokens, model=sonnet, batch=False
    )
    assert verify.cost == pytest.approx(expected)
    assert "Sonnet 5" in verify.note


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


def test_exhaustive_prompt_names_every_model_the_run_touches():
    """The header must not claim one model does all the work."""
    est = estimate_exhaustive_run_cost(10, model=OPUS)
    header = format_exhaustive_cost_prompt(est).splitlines()[0]
    assert "Opus 5" in header
    assert "Sonnet 5" in header  # identity / harvest / citation / verification


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


def test_exhaustive_total_survives_when_every_stage_is_priced():
    """The guard must not void a perfectly normal estimate."""
    est = estimate_exhaustive_run_cost(40, model=OPUS)
    assert all(c.cost is not None for c in est.components)
    assert est.low_cost is not None and est.low_cost > 0
    assert est.low_cost <= est.high_cost


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


def test_batch_dialog_does_not_promise_a_cache_discount_on_specifications():
    """§9.3 case 8. The batch path sets no breakpoint, so nothing is cached."""
    text = _dialog(batch=True)
    assert "ordinary batch input" in text
    assert "0.1x" not in text
    assert "cached after the first" not in text


def test_real_time_dialog_describes_specification_caching_as_conditional():
    """Parallel workers and expiry can both force additional writes."""
    text = _dialog(batch=False)
    assert "0.1x" in text                      # the discount is still real
    assert "usually cached" in text            # ...but not guaranteed
    assert "write rate" in text                # and the exception is named


def test_exhaustive_dialog_matches_the_digest_transport_in_every_mode():
    """Including Hybrid, where the digest is real-time and critique is batched.

    Specifications ride the DIGEST prompt only, so the sentence must follow
    ``batch``, not ``critique_batch``. Hybrid is the mode where those disagree,
    and a naive implementation keyed on the wrong one is only visible here.
    """
    economy = _exhaustive_dialog(batch=True, critique_batch=True)
    hybrid = _exhaustive_dialog(batch=False, critique_batch=True)
    fast = _exhaustive_dialog(batch=False, critique_batch=False)

    assert "ordinary batch input" in economy
    for text in (hybrid, fast):
        assert "usually cached" in text
        assert "ordinary batch input" not in text
    # Hybrid still describes its own critique transport correctly.
    assert "Hybrid mode" in hybrid


def test_no_dialog_claims_the_image_allowance_bounds_the_invoice():
    """The image figure is a per-model worst case; the text riding with it isn't.

    ``_ASSUMED_PROMPT_TOKENS_PER_SHEET`` is a flat 800/sheet, so a text-heavy
    set is under-counted on the one axis the image worst case does not cover.
    "Slightly-high estimate" read as a ceiling, which it never was.
    """
    for text in (_dialog(batch=True), _dialog(batch=False),
                 _exhaustive_dialog(batch=True, critique_batch=True),
                 _exhaustive_dialog(batch=False, critique_batch=False)):
        assert "slightly-high" not in text
        assert "not a cap" in text


def test_dialogs_distinguish_a_local_cache_hit_from_a_provider_cache_read():
    """"Cached sheets cost nothing" was two different caches in one sentence.

    A local ``DigestCache`` hit skips that sheet's own model call. It does not
    make the run free: on an exhaustive run, cross-QC, verification, citation
    and the rest still bill in full.
    """
    for text in (_dialog(batch=True), _dialog(batch=False)):
        assert "cost nothing" not in text
        assert "local result cache" in text
    exhaustive = _exhaustive_dialog(batch=False, critique_batch=False)
    assert "cost nothing" not in exhaustive


def test_no_dialog_claims_the_qc_stages_always_bill():
    """A warm re-run is cheaper but rarely free — and never "every stage bills".

    Every QC stage caches independently and returns without a provider call on a
    hit: identity (``set_identity`` ~483), review plan (~459), cross-QC (~1505),
    synthesis, focus, critique and per-finding verification. Saying they all
    still bill overstates a warm re-run as badly as "cached sheets cost nothing"
    understated it — the first version of this fix traded one false claim for
    its mirror image.

    What is actually true, and what a reviewer needs: the caches are per stage,
    so a digest hit implies nothing about the rest; and the set-level stages key
    on the WHOLE set, so the common case — one sheet added to a set reviewed
    last week — hits the digest cache for every old sheet and still re-runs
    identity, the review plan, synthesis and cross-sheet QC in full.
    """
    for text in (_dialog(batch=True), _dialog(batch=False),
                 _exhaustive_dialog(batch=True, critique_batch=True),
                 _exhaustive_dialog(batch=False, critique_batch=False)):
        assert "still bills normally" not in text
        assert "still run and still bill" not in text
        assert "caches separately" in text
        assert "whole set" in text


def test_the_copy_fix_moved_no_price():
    """§9.3 case 8, second half. Wording only — every total is unchanged.

    Values captured from the estimator before the copy edit. If one of these
    moves, someone "corrected" arithmetic the plan established is already
    correct (§2.4), and the batch/real-time relationship below is the property
    that would silently invert.
    """
    assert estimate_drawing_set_cost(
        10, file_count=1, model=OPUS, batch=True, spec_chars=40_000
    ).total_cost == pytest.approx(5.10, abs=0.005)
    assert estimate_drawing_set_cost(
        10, file_count=1, model=OPUS, batch=False, spec_chars=40_000
    ).total_cost == pytest.approx(9.65, abs=0.005)

    ex = estimate_exhaustive_run_cost(10, file_count=1, model=OPUS, batch=True,
                                      critique_batch=True, spec_chars=40_000)
    assert ex.low_cost == pytest.approx(14.88, abs=0.005)
    assert ex.high_cost == pytest.approx(16.26, abs=0.005)


def test_a_dialog_without_specifications_says_nothing_about_them():
    """The transport branch must not leak into a run that uploaded no specs."""
    for batch in (True, False):
        text = _dialog(batch=batch, spec_chars=0)
        assert "Project specifications" not in text
        assert "ordinary batch input" not in text


def test_the_confirmation_question_is_unchanged():
    """§9.2: keep the existing pre-send confirmation behavior."""
    assert _dialog(batch=True).rstrip().endswith("Proceed with the analysis?")
    assert _exhaustive_dialog(batch=True, critique_batch=True).rstrip().endswith(
        "Proceed with the exhaustive review?"
    )
    assert "Nothing is sent until you confirm." in _dialog(batch=False)
