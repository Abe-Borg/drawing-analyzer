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
SONNET_5 = "claude-sonnet-5"
OPUS_48 = "claude-opus-4-8"
SONNET_46 = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5"


# --------------------------------------------------------------------------- #
# defaults
# --------------------------------------------------------------------------- #


def test_pipeline_defaults_are_the_current_generation():
    assert api.REVIEW_MODEL_DEFAULT == OPUS_5
    assert api.VERIFICATION_ESCALATION_MODEL == OPUS_5
    assert api.CROSS_CHECK_MODEL_DEFAULT == SONNET_5
    assert api.VERIFICATION_MODEL_DEFAULT == SONNET_5
    # Chat is deliberately NOT Opus 5 — see the web-fetch tests below.
    assert api.CHAT_MODEL_DEFAULT == SONNET_5


def test_stages_that_deliberately_run_on_sonnet():
    """Three stages are Sonnet-by-default, each for a stated reason. Pin them so
    a well-meaning "upgrade everything to the flagship" cannot silently regress
    the citation check's capabilities."""
    from drawing_analyzer.citation_check import citation_model
    from drawing_analyzer.prose_harvest import harvest_model
    from drawing_analyzer.set_identity import default_identity_model

    # Citation is a CAPABILITY choice, not a cost one: web_fetch does not exist
    # on Opus 5, so an Opus citation check can only read search snippets.
    assert citation_model() == SONNET_5
    assert api.model_capabilities(SONNET_5).supports_web_fetch is True
    assert api.model_capabilities(OPUS_5).supports_web_fetch is False
    # Advisory-only, with a deterministic regex backstop.
    assert default_identity_model() == SONNET_5
    # Pure structuring of one prose item.
    assert harvest_model() == SONNET_5


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


@pytest.mark.parametrize("model", [OPUS_5, SONNET_5, OPUS_48, SONNET_46])
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


@pytest.mark.parametrize("model", [OPUS_5, SONNET_5, OPUS_48, SONNET_46])
def test_current_models_support_the_300k_batch_beta(model):
    assert api.model_supports_extended_output_beta(model) is True


def test_haiku_and_unknown_models_do_not_claim_the_beta():
    assert api.model_supports_extended_output_beta(HAIKU) is False
    assert api.model_supports_extended_output_beta("some-future-model") is False


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
# hi-res vision
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# web fetch
# --------------------------------------------------------------------------- #


def test_opus_5_does_not_support_web_fetch():
    """Opus 5's one capability regression vs Opus 4.8.

    Anthropic's Opus 5 migration guide lists web fetch as one of exactly two
    exceptions to Opus 4.8 feature parity (the other is Priority Tier). Web
    *search* is still supported — only fetch is excluded — so this cannot be
    inferred from generation or from web-search support.
    """
    assert api.model_capabilities(OPUS_5).supports_web_fetch is False
    assert api.model_capabilities(SONNET_5).supports_web_fetch is True
    assert api.model_capabilities(OPUS_48).supports_web_fetch is True
    assert api.model_capabilities(SONNET_46).supports_web_fetch is True


def test_unknown_model_never_claims_web_fetch():
    # Sending an unsupported server tool is a 400 that fails the whole request,
    # so the fallback must be "don't send it".
    assert api.model_capabilities("some-future-model").supports_web_fetch is False
    assert api.model_capabilities(HAIKU).supports_web_fetch is False


def test_chat_default_can_use_web_fetch():
    # api_config documents that the in-report assistant needs web fetch. This is
    # the guard that keeps that prose true.
    assert api.model_capabilities(api.CHAT_MODEL_DEFAULT).supports_web_fetch is True
    assert api.model_capabilities(api.CHAT_MODEL_DEFAULT).supports_adaptive_thinking


def test_hires_vision_roster_does_not_follow_family_lines():
    assert api.model_capabilities(SONNET_5).supports_hires_vision is True
    assert api.model_capabilities(SONNET_46).supports_hires_vision is False
    assert api.model_capabilities(OPUS_5).supports_hires_vision is True
    assert api.model_capabilities(HAIKU).supports_hires_vision is False


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
