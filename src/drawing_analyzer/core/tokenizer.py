"""
Token counting and limit management for Claude API calls.

Local estimates here are conservative guardrails, never exact billing; the
authoritative number is Anthropic's ``count_tokens`` endpoint
(:func:`count_tokens_via_api`).

Token limits (v2.3.0):
    - Claude Opus 5 context window: 1,000,000 tokens
    - Opus 5 max output: 128,000 tokens
    - Sonnet 5 max output: 128,000 tokens
    - Per-spec recommended input limit: 500,000 tokens
      (practical limit — individual specs are reviewed one at a time)
    - Cross-check recommended input limit: ~822,000 tokens
      (1,000,000 context - 128,000 output reserve - 50,000 overhead)

The per-spec limit (RECOMMENDED_MAX) is intentionally conservative
relative to the 1M context window. Per-spec review calls send a single
spec at a time, and the token gauge in the GUI displays the largest
spec's call size against this limit.

The cross-check limit (CROSS_CHECK_RECOMMENDED_MAX) is much higher
because the cross-checker sends ALL spec content in a single call.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model limits
# ---------------------------------------------------------------------------

# Claude Opus 5 context window (1M tokens, no beta header required).
MAX_CONTEXT_TOKENS = 1_000_000


# ---------------------------------------------------------------------------
# Per-spec review limits (used by GUI token gauge and per-spec pipeline)
# ---------------------------------------------------------------------------

# Practical per-call input limit for per-spec reviews.
# Individual specs are reviewed one at a time — this is the budget for a
# single (system prompt + project context + spec content) API call.
# Conservative relative to the 1M window and intended as a practical guardrail.
RECOMMENDED_MAX = 500_000

# Hard cap on the Project Context block. The context is sent on every per-spec
# review call, every cross-check call, and every verification call, so it
# multiplies cost quickly. 100K tokens leaves ~400K of the per-spec budget for
# the spec itself.
PROJECT_CONTEXT_MAX_TOKENS = 100_000


# ---------------------------------------------------------------------------
# Cross-check limits (v2.2.0)
# ---------------------------------------------------------------------------

# Cross-check uses Sonnet 5 with full spec content and adaptive thinking.
# With thinking enabled, thinking tokens + text output share the max_tokens budget.
# We keep a 128K output reserve (matches the api_config cross-check cap before
# the per-model clamp) so the input budget stays stable across model changes.
# Budget: 1M context - 128K output reserve - 50K overhead = 822K
CROSS_CHECK_OVERHEAD = 50_000
CROSS_CHECK_OUTPUT_BUDGET = 128_000
CROSS_CHECK_RECOMMENDED_MAX = (
    MAX_CONTEXT_TOKENS - CROSS_CHECK_OUTPUT_BUDGET - CROSS_CHECK_OVERHEAD
)


def exceeds_per_call_limit(spec_tokens: int, overhead_tokens: int) -> bool:
    """Check if a single spec would exceed the per-call token limit.

    Backward-compatible wrapper: no safety factor applied. New code that
    needs model-aware behavior should call
    :func:`exceeds_per_call_limit_for_model` instead.
    """
    return (overhead_tokens + spec_tokens) > RECOMMENDED_MAX


# ---------------------------------------------------------------------------
# Model-specific safety multipliers for the local cl100k_base estimate
# ---------------------------------------------------------------------------
#
# cl100k_base is OpenAI's tokenizer and does not exactly match Claude's
# tokenization. The undercount is usually modest for English prose
# (≤10%) but can be larger for structured spec text full of section
# numbers, table cells, and unicode punctuation. Without a safety factor
# the local estimate looks reassuring even when the real Claude count
# would breach the per-call budget — the goal is that local tokenizer
# estimates no longer create false confidence.
#
# The multipliers below are intentionally conservative. They are only
# consulted on the fallback path when the Anthropic ``count_tokens``
# endpoint is unavailable; once we have an exact count, that becomes
# the authoritative gate (directive 3).
_DEFAULT_LOCAL_SAFETY_FACTOR = 1.20  # unknown models — widest margin
_LOCAL_SAFETY_FACTORS: dict[str, float] = {
    # Opus / Sonnet share Claude's main tokenizer; the cl100k_base
    # undercount is small but non-zero.
    #
    # Opus 5 and Sonnet 5 both use the tokenizer introduced with Opus 4.7,
    # the same one Opus 4.8 uses, so they carry Opus 4.8's factor. Note this
    # pads the *ratio* to cl100k, not the absolute count: for identical text
    # Sonnet 5 emits roughly 30% more Claude tokens than Sonnet 4.6 because
    # of that tokenizer change, which is exactly why its budget must not be
    # estimated with a Sonnet-4.6-era assumption. The authoritative number
    # remains the ``count_tokens`` preflight; this table is the fallback gate.
    "claude-opus-5-5": 1.10,
    "claude-sonnet-5-5": 1.10,
    "claude-haiku-5-5": 1.10,
    "claude-opus-5": 1.10,
    "claude-sonnet-5": 1.10,
    "claude-opus-4-8": 1.10,
    "claude-sonnet-4-6": 1.10,
    # Haiku 4.5 tokenization tends to undercount cl100k a bit more on
    # structured construction-spec text in practice. Pad more.
    "claude-haiku-4-5": 1.15,
}


def local_estimate_safety_factor(model: str | None) -> float:
    """Return the cl100k→Claude safety multiplier for ``model``.

    The factor is a conservative multiplier ≥ 1.0 applied to the local
    cl100k_base count whenever it is used as a budget gate. Unknown
    models fall back to ``_DEFAULT_LOCAL_SAFETY_FACTOR`` (the widest
    margin) so a future model never silently sails through a budget
    check that would have been blocked under a known model.

    The ``≥ 1.0`` floor is *enforced*, not merely assumed: a sub-1.0 entry
    slipping into ``_LOCAL_SAFETY_FACTORS`` (a typo, or a misguided attempt
    to trim the margin) would turn the safety pad into a *danger pad* — it
    would shrink the estimate below the raw local count, undercount the
    Claude token total, and let an over-budget spec sail through the
    fallback gate. Clamping here honors the contract for every caller, not
    just :func:`safe_local_estimate`.
    """
    factor = _LOCAL_SAFETY_FACTORS.get(model or "", _DEFAULT_LOCAL_SAFETY_FACTOR)
    return max(1.0, factor)


def safe_local_estimate(local_tokens: int, *, model: str | None) -> int:
    """Return ``local_tokens`` padded by the model-specific safety factor."""
    factor = local_estimate_safety_factor(model)
    # Round up — the factor is a safety margin, not a midpoint estimate.
    return math.ceil(local_tokens * factor)


def exceeds_per_call_limit_for_model(
    spec_tokens: int,
    overhead_tokens: int,
    *,
    model: str | None,
) -> bool:
    """Model-aware version of :func:`exceeds_per_call_limit`.

    Applies the model-specific safety factor to ``spec_tokens + overhead``
    before comparing against ``RECOMMENDED_MAX``. Use this when the local
    cl100k_base count is the only signal available (e.g. the API preflight
    failed or was disabled). When an exact Anthropic count is available,
    bypass this helper and compare the exact count directly to
    ``RECOMMENDED_MAX`` — the exact number is authoritative (directive 3).
    """
    padded = safe_local_estimate(overhead_tokens + spec_tokens, model=model)
    return padded > RECOMMENDED_MAX


# ---------------------------------------------------------------------------
# Image / vision token estimation
# ---------------------------------------------------------------------------
#
# Claude bills an image at approximately ``width * height / 750`` tokens (per
# the vision docs), after any resize down to the model's native resolution, and
# clamped to a per-model token cap. The published cost tables match
# ``ceil(w*h/750)`` with no extra padding, so we mirror that exactly:
#
#   * High-resolution tier: up to 4784 tokens, long edge <= 2576 px.
#   * Standard tier (Sonnet 4.6 / Haiku 4.5 / unknown): up to 1568 tokens,
#     long edge <= 1568 px.
#
# Which models are high-resolution is a moving roster that no longer follows
# family lines — Sonnet 5 reads at the hi-res tier while Sonnet 4.6 does not.
# ``_image_caps_for_model`` therefore reads the per-model
# ``supports_hires_vision`` flag from the api_config capability registry
# rather than testing Opus membership, which would under-estimate every
# Sonnet 5 image by a factor of ~3. An unregistered model falls to the
# standard tier — a safe under-estimate, never an over-run of the request.
# These are local *estimates* for budgeting (mirroring the documented
# formula); the authoritative number is still Anthropic's ``count_tokens``
# endpoint, which accepts image/document blocks like any other content.

_IMAGE_TOKEN_DIVISOR = 750

_IMAGE_TOKEN_CAP_HIRES = 4784      # Opus 5 / Sonnet 5 / Opus 4.8 / Opus 4.7
_IMAGE_LONG_EDGE_HIRES = 2576
_IMAGE_TOKEN_CAP_DEFAULT = 1568    # Sonnet 4.6 / Haiku 4.5 / unknown
_IMAGE_LONG_EDGE_DEFAULT = 1568


def _image_caps_for_model(model: str | None) -> tuple[int, int]:
    """Return ``(token_cap, long_edge_cap_px)`` for ``model``.

    Reads the per-model high-resolution flag from the api_config capability
    registry so the capability source of truth stays single. Imported lazily
    to avoid any import-order coupling at module load.
    """
    try:
        from .api_config import model_capabilities

        if model and model_capabilities(model).supports_hires_vision:
            return _IMAGE_TOKEN_CAP_HIRES, _IMAGE_LONG_EDGE_HIRES
    except Exception:  # pragma: no cover - defensive; fall back to safe default
        pass
    return _IMAGE_TOKEN_CAP_DEFAULT, _IMAGE_LONG_EDGE_DEFAULT


# The API reads an image as 28x28-pixel patches, one visual token each, and the
# tier's token limit counts those patches.
_IMAGE_PATCH_PX = 28


def _patches(px: int) -> int:
    """Patches along one image edge: ``ceil(px / 28)``."""
    return -(-px // _IMAGE_PATCH_PX)


def resized_image_size(width_px: int, height_px: int, *, model: str | None) -> tuple[int, int]:
    """The size the API downscales an image to before ``model`` reads it.

    Mirrors the vision docs' reference implementation ("How Claude resizes and
    pads images"): the largest aspect-preserving size whose patch-padded edges
    fit the tier's long-edge limit and whose ``ceil(w/28) * ceil(h/28)`` patch
    count fits its token limit, searched along the long edge with the short
    edge rounded half to even. An image within both limits comes back
    unchanged; non-positive sizes come back as ``(0, 0)``.

    The limits are the model's tier caps, as in :func:`estimate_image_tokens`.
    Pricing needs nothing more than the token cap, because a downscaled image
    costs at most the cap. Resolution does: a near-square 2576 px image on the
    high-resolution tier reaches the model at roughly three quarters of its
    rendered size per edge, which ``tiling.effective_tile_dpi`` must count.
    """
    if width_px <= 0 or height_px <= 0:
        return 0, 0
    token_cap, long_edge_cap = _image_caps_for_model(model)

    def fits(w: int, h: int) -> bool:
        return (_patches(w) * _IMAGE_PATCH_PX <= long_edge_cap
                and _patches(h) * _IMAGE_PATCH_PX <= long_edge_cap
                and _patches(w) * _patches(h) <= token_cap)

    if fits(width_px, height_px):
        return width_px, height_px
    long_px = max(width_px, height_px)
    aspect = long_px / min(width_px, height_px)
    lo, hi = 1, long_px  # lo always fits; hi never does
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        # round() is half-to-even, the tie rule the live API uses.
        if fits(mid, max(round(mid / aspect), 1)):
            lo = mid
        else:
            hi = mid
    short = max(round(lo / aspect), 1)
    return (lo, short) if width_px >= height_px else (short, lo)


def estimate_image_tokens(width_px: int, height_px: int, *, model: str | None) -> int:
    """Estimate the billed token cost of one image of ``width_px x height_px``.

    Mirrors the documented vision pricing: resize down so the long edge fits the
    model's native resolution (preserving aspect ratio), then ``ceil(w*h/750)``,
    clamped to the per-model token cap. Returns an integer >= 0.
    """
    if width_px <= 0 or height_px <= 0:
        return 0
    token_cap, long_edge_cap = _image_caps_for_model(model)
    w = float(width_px)
    h = float(height_px)
    longest = max(w, h)
    if longest > long_edge_cap:
        scale = long_edge_cap / longest
        w *= scale
        h *= scale
    tokens = math.ceil((w * h) / _IMAGE_TOKEN_DIVISOR)
    return min(token_cap, tokens)


def estimate_image_tokens_total(
    sizes: list[tuple[int, int]], *, model: str | None
) -> int:
    """Sum :func:`estimate_image_tokens` over a list of ``(width, height)`` sizes."""
    return sum(estimate_image_tokens(w, h, model=model) for w, h in sizes)


def count_tokens_via_api(
    *,
    model: str,
    system: Any,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    client: Any = None,
) -> Optional[int]:
    """Exact token count via Anthropic's count_tokens endpoint.

    Returns the input-token total for the given request shape, or ``None`` on
    failure (network error, missing API key, SDK version mismatch). Callers
    should treat ``None`` as "preflight unavailable" and fall back to the
    local estimate rather than blocking submission.

    Plan section 6.3: keep the local estimate for UI responsiveness, use this
    helper before batch submission when exact routing/guardrail decisions
    matter.
    """
    if client is None:
        try:
            from ..client import get_client as _get_client
            client = _get_client()
        except Exception as exc:  # pragma: no cover - exercised via tests
            _log.warning("count_tokens_via_api: no client available (%s)", exc)
            return None
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if system is not None:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        result = client.messages.count_tokens(**kwargs)
        # MessageTokensCount has an input_tokens attribute.
        return int(getattr(result, "input_tokens", 0) or 0)
    except Exception as exc:
        _log.warning("count_tokens_via_api failed: %s", exc)
        return None
