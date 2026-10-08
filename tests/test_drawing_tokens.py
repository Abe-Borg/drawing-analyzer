"""Image-token estimator tests.

Locks the estimator to Anthropic's published vision cost table: tokens =
ceil(w/28) * ceil(h/28), counted after the API resizes the image to fit the
model's tier. Also locks that resized size, which the tile DPI floor is
measured at.
"""
from __future__ import annotations

import pytest

from drawing_analyzer.core.tokenizer import (
    estimate_image_tokens,
    estimate_image_tokens_total,
    resized_image_size,
)

OPUS = "claude-opus-5"
SONNET = "claude-sonnet-4-6"
SONNET_5 = "claude-sonnet-5"


def test_opus_matches_published_cost_table():
    # Values from the vision docs' cost table, high-resolution tier.
    assert estimate_image_tokens(200, 200, model=OPUS) == 64
    assert estimate_image_tokens(1000, 1000, model=OPUS) == 1296
    assert estimate_image_tokens(1920, 1080, model=OPUS) == 2691
    assert estimate_image_tokens(2000, 1500, model=OPUS) == 3888


def test_opus_caps_at_4784():
    # An image above native resolution is resized to fit the cap: the docs'
    # 4K frame lands on it exactly, and no size goes over.
    assert estimate_image_tokens(3840, 2160, model=OPUS) == 4784
    assert estimate_image_tokens(8000, 8000, model=OPUS) <= 4784


def test_sonnet_caps_at_1568():
    # Sonnet 4.6 resizes to fit the standard tier's 1568 px and 1568 tokens.
    assert estimate_image_tokens(2000, 1500, model=SONNET) == 1564
    # Within both limits, no resize: the raw patch count.
    assert estimate_image_tokens(1000, 1000, model=SONNET) == 1296


def test_sonnet_5_reads_at_the_high_resolution_tier():
    # Sonnet 5 is the first Sonnet-tier model on the hi-res tier, so it must
    # NOT inherit Sonnet 4.6's 1568 cap. Gating this on Opus family membership
    # (the old behavior) under-estimated every Sonnet 5 image ~3x.
    assert estimate_image_tokens(2000, 1500, model=SONNET_5) == 3888
    assert estimate_image_tokens(3840, 2160, model=SONNET_5) == 4784
    assert estimate_image_tokens(2000, 1500, model=SONNET_5) == estimate_image_tokens(
        2000, 1500, model=OPUS
    )


def test_unknown_model_uses_conservative_default_caps():
    # Unknown / None models fall back to the default (Sonnet-tier) caps.
    assert estimate_image_tokens(2000, 1500, model=None) == 1564
    assert estimate_image_tokens(2000, 1500, model="some-future-model") == 1564


def test_nonpositive_sizes_are_zero():
    assert estimate_image_tokens(0, 0, model=OPUS) == 0
    assert estimate_image_tokens(-5, 100, model=OPUS) == 0


def test_total_sums_each_image():
    sizes = [(1000, 1000), (200, 200)]
    assert estimate_image_tokens_total(sizes, model=OPUS) == 1296 + 64


@pytest.mark.parametrize("model,size,read", [
    # The vision docs' resize examples. On the standard tier the token limit
    # binds before the 1568 px edge does.
    (SONNET, (1075, 1520), (924, 1307)),
    (SONNET, (1920, 1080), (1456, 819)),
    # High-resolution tier: both fit unchanged; a 4K frame stops at the edge.
    (OPUS, (1075, 1520), (1075, 1520)),
    (OPUS, (1920, 1080), (1920, 1080)),
    (OPUS, (3840, 2160), (2576, 1449)),
    (OPUS, (2160, 3840), (1449, 2576)),
    # A square at the 2576 px edge exceeds 4784 patches and shrinks to fit:
    # the downscale the tile DPI floor has to count.
    (OPUS, (2576, 2576), (1932, 1932)),
])
def test_resized_image_size_follows_the_documented_downscale(model, size, read):
    assert resized_image_size(*size, model=model) == read
