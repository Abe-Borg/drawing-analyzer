"""Capability-registry tests for the Opus 5 / Sonnet 5 generation.

``_MODEL_CAPABILITIES`` is the single source of truth for the three request-
shape decisions that used to be keyed off Opus family membership: the output
ceiling, the ``output_config.effort`` level, and the high-resolution vision
tier. Sonnet 5 is the model that broke the family shortcut — it matches Opus
on all three while Sonnet 4.6 matches on none — so these tests pin the
distinction rather than the family.
"""
from __future__ import annotations

import pytest

from drawing_analyzer.core import api_config as api
from drawing_analyzer.core.pricing import MODEL_PRICING
from drawing_analyzer.core.tokenizer import _LOCAL_SAFETY_FACTORS

OPUS_5 = "claude-opus-5"
OPUS_5_5 = "claude-opus-5-5"
SONNET_5_5 = "claude-sonnet-5-5"
HAIKU_5_5 = "claude-haiku-5-5"
SONNET_5 = "claude-sonnet-5"
OPUS_48 = "claude-opus-4-8"
SONNET_46 = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5"


# --------------------------------------------------------------------------- #
# defaults
# --------------------------------------------------------------------------- #


def test_stage_defaults_keep_review_judgment_separate_from_extraction():
    """Haiku handles bounded extraction; reviewers keep their judgment models."""
    from drawing_analyzer.citation_check import citation_model
    from drawing_analyzer.prose_harvest import harvest_model
    from drawing_analyzer.set_identity import default_identity_model

    # Citation is a CAPABILITY choice, not a cost one: web_fetch does not exist
    # on Opus 5, so an Opus citation check can only read search snippets.
    assert citation_model() == SONNET_5_5
    assert api.model_capabilities(SONNET_5_5).supports_web_fetch is True
    assert api.model_capabilities(OPUS_5_5).supports_web_fetch is True
    assert api.model_capabilities(OPUS_5).supports_web_fetch is False
    # Advisory-only, with a deterministic regex backstop.
    assert default_identity_model() == HAIKU_5_5
    # Pure structuring of one prose item.
    assert harvest_model() == HAIKU_5_5
    assert api.REVIEW_MODEL_DEFAULT == OPUS_5_5
    assert api.VERIFICATION_MODEL_DEFAULT == SONNET_5_5
    assert api.CHAT_MODEL_DEFAULT == SONNET_5_5


@pytest.mark.parametrize("model", [OPUS_5_5, SONNET_5_5, HAIKU_5_5])
def test_5_5_documented_capabilities(model):
    # Verified against each model's own migration/feature docs (2026-10-05),
    # not equality with a predecessor: web fetch and refusal fallback differ.
    assert api.model_capabilities(model) == api.ModelCapabilities(
        supports_adaptive_thinking=True,
        max_output_tokens=128_000,
        supports_extended_output_beta=True,
        context_window=1_000_000,
        supported_effort_levels=frozenset({"low", "medium", "high", "xhigh", "max"}),
        supports_hires_vision=True,
        supports_web_fetch=True,
        supports_web_search=True,
        supports_refusal_fallback=model != HAIKU_5_5,
        supports_structured_outputs=True,
    )
    assert api.effort_config_for(model=model, phase=api.PHASE_REVIEW) == {"effort": "high"}
    assert api.thinking_config_for(model=model, phase=api.PHASE_REVIEW) == {"type": "adaptive"}
    assert api.effort_config_for(model=model, phase=api.PHASE_CROSS_CHECK) == {"effort": "xhigh"}
    assert (model in api.OPUS_MODELS) == (model == OPUS_5_5)


@pytest.mark.parametrize("model", [OPUS_5_5, SONNET_5_5, HAIKU_5_5])
def test_5_5_hires_vision_estimate_and_batch_ceiling(model):
    from drawing_analyzer.core.tokenizer import estimate_image_tokens

    assert estimate_image_tokens(3840, 2160, model=model) == 4784
    assert api.review_max_tokens(model=model) == 128_000
    with pytest.raises(ValueError, match=api.BATCH_OUTPUT_BETA):
        api.assert_extended_output_allowed(max_tokens=300_000, betas=[], model=model)
    api.assert_extended_output_allowed(
        max_tokens=300_000, betas=[api.BATCH_OUTPUT_BETA], model=model
    )


def test_previous_generation_stays_registered_as_a_valid_override():
    # Pinning Opus 4.8 / Sonnet 4.6 must keep full capabilities rather than
    # falling through to the conservative unknown-model defaults.
    for model in (OPUS_48, SONNET_46):
        caps = api.model_capabilities(model)
        assert caps is not api._DEFAULT_CAPABILITIES
        assert caps.supports_adaptive_thinking is True


# --------------------------------------------------------------------------- #
# output ceiling
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model", [OPUS_5, SONNET_5, OPUS_48, SONNET_46, HAIKU_5_5])
def test_current_models_share_the_128k_output_ceiling(model):
    # Sonnet 5 must not inherit a 64k cap from a family-shaped check.
    assert api.phase_output_cap(api.PHASE_REVIEW, model=model) == 128_000


def test_haiku_keeps_the_64k_ceiling():
    assert api.output_cap_for_model(HAIKU, requested=128_000) == 64_000


def test_unknown_model_stays_at_the_conservative_ceiling():
    # The unknown fallback must not drift upward when a registered tier rises.
    assert api.output_cap_for_model("some-future-model", requested=999_999) == 64_000
    assert api._DEFAULT_CAPABILITIES.max_output_tokens == api.MAX_OUTPUT_TOKENS_UNKNOWN


# --------------------------------------------------------------------------- #
# effort levels
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model", [OPUS_5, SONNET_5, OPUS_48])
def test_xhigh_survives_on_models_that_accept_it(model):
    assert api.effort_config_for(model=model, phase=api.PHASE_CROSS_CHECK) == {
        "effort": "xhigh"
    }


def test_xhigh_still_clamps_on_sonnet_46():
    # Sonnet 4.6 accepts `max` but rejects `xhigh` with a 400, so the clamp
    # must still fire for it even though it no longer fires for Sonnet 5.
    assert api.effort_config_for(model=SONNET_46, phase=api.PHASE_CROSS_CHECK) == {
        "effort": "high"
    }
    assert "xhigh" not in api.model_capabilities(SONNET_46).supported_effort_levels
    assert "max" in api.model_capabilities(SONNET_46).supported_effort_levels


def test_effort_is_omitted_entirely_for_models_without_support():
    # An empty roster means "omit output_config", not "send a default level".
    assert api.model_supports_effort(HAIKU) is False
    assert api.effort_config_for(model=HAIKU, phase=api.PHASE_REVIEW) is None
    assert api.effort_config_for(model="some-future-model", phase=api.PHASE_REVIEW) is None


def test_opus_is_the_verification_escalation_tier():
    # Escalation is a routing decision and stays keyed on family membership.
    assert api.effort_config_for(model=OPUS_5, phase=api.PHASE_VERIFICATION) == {
        "effort": "high"
    }
    assert api.effort_config_for(model=SONNET_5, phase=api.PHASE_VERIFICATION) == {
        "effort": "medium"
    }


def test_haiku_harvest_starts_at_medium_without_retuning_existing_models():
    assert api.effort_config_for(model=HAIKU_5_5, phase=api.PHASE_HARVEST) == {
        "effort": "medium"
    }
    assert api.effort_config_for(model=SONNET_5_5, phase=api.PHASE_HARVEST) == {
        "effort": "low"
    }


def test_every_emitted_effort_level_is_one_the_model_accepts():
    # The clamp is the only thing standing between a phase default and a 400.
    phases = [
        api.PHASE_REVIEW,
        api.PHASE_CROSS_CHECK,
        api.PHASE_VERIFICATION,
        api.PHASE_VERIFICATION_RETRY,
        api.PHASE_VERIFICATION_CONTINUATION,
        api.PHASE_INVESTIGATION,
        api.PHASE_HARVEST,
        api.PHASE_CITATION,
    ]
    for model, caps in api._MODEL_CAPABILITIES.items():
        for phase in phases:
            config = api.effort_config_for(model=model, phase=phase)
            if config is None:
                continue
            assert config["effort"] in caps.supported_effort_levels, (
                f"{model} would receive an unsupported effort level on {phase}"
            )


# --------------------------------------------------------------------------- #
# extended output beta
# --------------------------------------------------------------------------- #


def test_extended_output_guard_uses_the_selected_models_ceiling():
    # Above the ceiling without the beta header -> refuse before submitting.
    with pytest.raises(ValueError, match=api.BATCH_OUTPUT_BETA):
        api.assert_extended_output_allowed(
            max_tokens=300_000, betas=None, model=SONNET_5
        )
    # With the header, it is allowed.
    api.assert_extended_output_allowed(
        max_tokens=300_000, betas=[api.BATCH_OUTPUT_BETA], model=SONNET_5
    )
    # At or below the ceiling, no header needed.
    api.assert_extended_output_allowed(max_tokens=128_000, betas=None, model=SONNET_5)


# --------------------------------------------------------------------------- #
# per-model roster: 300k batch beta, web fetch, hi-res vision
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "model, batch_beta, web_fetch, hires_vision",
    [
        # Web fetch is Opus 5's one capability regression vs Opus 4.8 (the
        # migration guide's other parity exception is Priority Tier). Web
        # *search* is still supported, so this cannot be inferred from
        # generation or from web-search support.
        (OPUS_5, True, False, True),
        (SONNET_5, True, True, True),
        (OPUS_48, True, True, None),
        # The hi-res roster does not follow family lines.
        (SONNET_46, True, True, False),
        (HAIKU, False, False, False),
        (HAIKU_5_5, True, True, True),
        # Sending an unsupported server tool is a 400 that fails the whole
        # request, so the unknown-model fallback must be "don't send it".
        ("some-future-model", False, False, None),
    ],
)
def test_capability_roster(model, batch_beta, web_fetch, hires_vision):
    caps = api.model_capabilities(model)
    assert api.model_supports_extended_output_beta(model) is batch_beta
    assert caps.supports_web_fetch is web_fetch
    if hires_vision is not None:
        assert caps.supports_hires_vision is hires_vision


# --------------------------------------------------------------------------- #
# registry drift
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("model", sorted(api._MODEL_CAPABILITIES))
def test_every_capable_model_is_priced_and_has_a_safety_factor(model):
    """A selectable model must be complete across all three registries.

    These three tables are maintained by hand and had already drifted apart
    (Opus 4.7 / 4.6 were priced but absent from the capability whitelist and
    the tokenizer's safety factors) with nothing to catch it. A model the app
    can fully drive but cannot price shows the user a run with no dollar
    figure; one with no safety factor silently gets the widest fallback pad.
    """
    assert model in MODEL_PRICING, f"{model} is capability-registered but unpriced"
    assert model in _LOCAL_SAFETY_FACTORS, f"{model} has no local safety factor"
