"""WP-05 §10.1/§10.2 — a cost preview built from each page's real shape.

`docs/REVIEW_IMPLEMENTATION_PLAN.md` §2.6: the shipped preview assumes every
image is a square at the *raster* target and lands at the model's token cap.
That is a true upper bound and about **1.9x** the real cost of a vector E-size
sheet. Two facts per page close most of the gap, and both come from a scan that
never rasterizes — the aspect ratio, and whether the page has words.

The tests here are mostly *dimensional and arithmetic invariants* rather than
string snapshots (§10.5), plus a handful of hand-checked values from §2.5/§2.6
so the implementation is not merely self-consistent.

**On the reference values.** §2.5's figures were derived with whole-pixel
dimension rounding — ``round((x1-x0) * zoom)``. The renderer does not do that:
``get_pixmap`` sizes the pixmap from ``(rect * matrix).irect``, the smallest
integer rect containing the *transformed* rect, which expands to contain and so
runs systematically higher. A vector E-size sheet is 92,871 tokens by the plan's
rule and 93,013 by the renderer's — 0.15%. §2.5 says its values are "arithmetic
cross-checks, not production regression fixtures requiring exact agreement with
rasterizer rounding", which is exactly this. The rendered-fixture tests below
assert against the **renderer**; the plan's numbers are asserted only within a
documented tolerance.
"""
from __future__ import annotations

import pytest

from drawing_analyzer import tiling
from drawing_analyzer.cost import (
    estimate_drawing_set_cost,
    estimate_exhaustive_run_cost,
    estimate_image_tokens_for_bases,
)
from drawing_analyzer.core.tokenizer import estimate_image_tokens
from drawing_analyzer.models import (
    CLASSIFICATION_RASTER,
    CLASSIFICATION_UNKNOWN,
    CLASSIFICATION_VECTOR,
    SheetCostBasis,
)
from drawing_analyzer.pipeline import estimate_image_tokens_for_set

OPUS = "claude-opus-5"
SONNET = "claude-sonnet-5"
#: A standard-tier model: 1568-token image cap instead of 4784.
HAIKU = "claude-haiku-4-5-20251001"

# Sheet shapes, in inches. ANSI E / ARCH D / ANSI B / letter are the four §2.5
# resolves to; the square is §2.6's aspect-extreme.
E, D, B, LETTER, SQUARE = (34, 44), (24, 36), (11, 17), (8.5, 11), (30, 30)


def basis(shape, classification=CLASSIFICATION_VECTOR, **kw) -> SheetCostBasis:
    w, h = shape
    return SheetCostBasis(
        source_name="set.pdf", page_index=0,
        width_pt=w * 72.0, height_pt=h * 72.0,
        classification=classification, **kw,
    )


def tokens(shape, *, classification=CLASSIFICATION_VECTOR, model=OPUS, **kw) -> int:
    return estimate_image_tokens_for_bases(
        [basis(shape, classification)], model=model, **kw
    ).tokens


# --------------------------------------------------------------------------- #
# §2.6 — scale invariance holds in BOTH regimes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("grid,label", [(6, "6x6 @1560"), (3, "3x3 @2576")])
def test_image_tokens_are_scale_invariant_in_both_regimes(grid, label):
    """``zoom_for_rect`` normalizes the long edge, so physical size never enters.

    ANSI E 34x44 and US letter 8.5x11 share an aspect ratio and 16x the area.
    The plan is emphatic that this holds in the <=20-image branch too — do not
    assert that branch is scale-sensitive, it is not.
    """
    assert tokens(E, rows=grid, cols=grid) == tokens(LETTER, rows=grid, cols=grid)


def test_scale_invariance_survives_a_raster_classification():
    assert (tokens(E, classification=CLASSIFICATION_RASTER)
            == tokens(LETTER, classification=CLASSIFICATION_RASTER))


# --------------------------------------------------------------------------- #
# §2.6 — aspect sensitivity DIFFERS by regime, because of cap clamping
# --------------------------------------------------------------------------- #


def test_aspect_ratio_drives_cost_in_the_shipping_many_image_regime():
    """At 6x6 / 1560 nothing clamps: the largest image is 3,245 < the 4,784 cap.

    The plan measures the 34x44-vs-square spread at 20.27% of the larger.
    """
    tall, square = tokens(E), tokens(SQUARE)
    assert tall < square
    spread = (square - tall) / square
    assert 0.19 < spread < 0.22, spread


def test_aspect_ratio_washes_out_entirely_in_the_few_image_regime():
    """At 3x3 / 2576 essentially every image hits the cap, so only count matters.

    This is the half that is easy to get backwards: the <=20-image branch is not
    "more precise", it is *insensitive* — an E-size sheet and a square cost the
    same because both saturate.
    """
    assert tokens(E, rows=3, cols=3) == tokens(SQUARE, rows=3, cols=3)
    images = tiling.total_images_for_grid(3, 3)
    cap = estimate_image_tokens(9999, 9999, model=OPUS)
    assert tokens(E, rows=3, cols=3) == images * cap == 47_840


def test_the_few_image_branch_holds_for_every_small_grid():
    """3x3 (10 images) and 2x2 (5) are both under the 20-image threshold."""
    assert tokens(E, rows=2, cols=2) == 5 * 4_784 == 23_920
    assert tokens(E, rows=3, cols=3) == 10 * 4_784


# --------------------------------------------------------------------------- #
# The geometry helper reproduces the renderer, not merely itself
# --------------------------------------------------------------------------- #


def _rendered_sizes(pymupdf, w_in, h_in, *, rows, cols, raster=False):
    """Actually rasterize, and report each image's true pixel dimensions."""
    W, H = w_in * 72.0, h_in * 72.0
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    if not raster:
        page.insert_text((72, 72), "FP-101 PRE-ACTION VALVE SCHEDULE")
    target = tiling.target_long_edge_px(
        tiling.total_images_for_grid(rows, cols), is_raster=raster
    )
    rects = [(0.0, 0.0, W, H)] + [
        (t.x0, t.y0, t.x1, t.y1)
        for t in tiling.tile_rects(W, H, rows=rows, cols=cols)
    ]
    out = []
    for (x0, y0, x1, y1) in rects:
        zoom = tiling.zoom_for_rect(x1 - x0, y1 - y0, target)
        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(zoom, zoom),
            clip=pymupdf.Rect(x0, y0, x1, y1), alpha=False,
        )
        out.append((pix.width, pix.height))
    doc.close()
    return out


@pytest.mark.parametrize("shape", [E, D, B, LETTER, SQUARE])
@pytest.mark.parametrize("grid", [6, 5, 3, 2])
def test_predicted_pixel_sizes_match_a_real_render(shape, grid):
    """§10.1 step 4 — the rounding assumption, checked against the rasterizer.

    ``get_pixmap`` sizes from ``(rect * matrix).irect``, which depends on where
    the rect sits, not only how big it is: on a 34x44 sheet at 6x6, ``r0c1`` and
    ``r0c2`` are both 473.280 pt wide and render 1296 and 1295 px. No
    dimension-only rule reproduces that, which is why the helper mirrors
    ``irect`` instead of rounding.

    Tolerance is set from measurement, not taste: exact on 18 of these 20
    combinations, and at most one pixel out on a float boundary otherwise.
    """
    pymupdf = pytest.importorskip("pymupdf")
    w_in, h_in = shape
    actual = _rendered_sizes(pymupdf, w_in, h_in, rows=grid, cols=grid)
    predicted = tiling.image_pixel_sizes(
        w_in * 72.0, h_in * 72.0, rows=grid, cols=grid
    )
    assert len(predicted) == len(actual)
    for (pw, ph), (aw, ah) in zip(predicted, actual):
        assert abs(pw - aw) <= 1 and abs(ph - ah) <= 1, (predicted, actual)


@pytest.mark.parametrize("shape", [E, D, B, LETTER, SQUARE])
def test_predicted_token_count_matches_a_real_render_within_a_tight_bound(shape):
    """The number that is actually quoted, against the number actually rendered."""
    pymupdf = pytest.importorskip("pymupdf")
    w_in, h_in = shape
    actual = sum(
        estimate_image_tokens(w, h, model=OPUS)
        for w, h in _rendered_sizes(pymupdf, w_in, h_in, rows=6, cols=6)
    )
    predicted = tokens(shape)
    assert abs(predicted - actual) / actual < 0.0001, (predicted, actual)


def test_a_rotated_page_is_measured_in_the_space_the_model_sees():
    """Displayed dimensions, post-rotation — the PAGE_VIEW_V2 space (§10.1).

    A 90-degree rotated 11x17 page presents as 17x11. Quoting its unrotated
    shape would price a different sheet; here the ratio is what matters, and a
    rotation inverts it.
    """
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import iter_sheet_cost_bases

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rot.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=11 * 72, height=17 * 72)
        page.insert_text((72, 72), "E-201")
        page.set_rotation(90)
        doc.save(str(path))
        doc.close()
        (b,) = list(iter_sheet_cost_bases([path]))

    assert b.width_pt == pytest.approx(17 * 72.0)
    assert b.height_pt == pytest.approx(11 * 72.0)
    assert b.classification == CLASSIFICATION_VECTOR


# --------------------------------------------------------------------------- #
# Classification: raster, unknown, and the direction of every guess
# --------------------------------------------------------------------------- #


def test_a_raster_page_is_quoted_at_the_larger_raster_target():
    """No text layer means the pixels are the only channel, so it renders bigger."""
    assert tokens(E, classification=CLASSIFICATION_RASTER) > tokens(E)


def test_an_unknown_page_is_never_assumed_vector():
    """§10.1 item 7. Vector is the *cheaper* target; guessing it quotes low.

    An unknown page falls back to the conservative allowance — deliberately the
    most expensive answer, because it is the one that cannot mislead a spend
    decision downward.
    """
    unknown = estimate_image_tokens_for_bases(
        [basis(E, CLASSIFICATION_UNKNOWN)], model=OPUS
    )
    assert unknown.tokens == estimate_image_tokens_for_set(1, model=OPUS)
    assert unknown.tokens > tokens(E)
    assert unknown.tokens > tokens(E, classification=CLASSIFICATION_RASTER)
    assert unknown.unknown_pages == 1
    assert unknown.fully_measured is False


def test_an_unmeasurable_page_is_quoted_not_dropped():
    """§10.1 item 8. A silently dropped page under-quotes the whole set."""
    bad = SheetCostBasis(
        source_name="broken.pdf", page_index=0, width_pt=0.0, height_pt=0.0,
        classification=CLASSIFICATION_UNKNOWN, geometry_ok=False,
        error="could not open source: FileDataError",
    )
    est = estimate_image_tokens_for_bases([bad], model=OPUS)
    assert est.tokens > 0
    assert est.unmeasured_pages == 1 and est.unknown_pages == 1
    assert est.pages == 1


def test_a_page_claiming_vector_with_no_area_still_falls_back():
    """`geometry_ok` and a positive area are both required, not either."""
    liar = SheetCostBasis(
        source_name="s.pdf", page_index=0, width_pt=0.0, height_pt=0.0,
        classification=CLASSIFICATION_VECTOR, geometry_ok=True,
    )
    est = estimate_image_tokens_for_bases([liar], model=OPUS)
    assert est.unknown_pages == 1
    assert est.tokens == estimate_image_tokens_for_set(1, model=OPUS)


def test_mixed_classifications_are_counted_separately():
    est = estimate_image_tokens_for_bases(
        [basis(E), basis(D, CLASSIFICATION_RASTER), basis(B, CLASSIFICATION_UNKNOWN)],
        model=OPUS,
    )
    assert (est.vector_pages, est.raster_pages, est.unknown_pages) == (1, 1, 1)
    assert est.pages == 3
    assert est.fully_measured is False


def test_an_empty_set_is_zero_not_an_error():
    est = estimate_image_tokens_for_bases([], model=OPUS)
    assert est.tokens == 0 and est.pages == 0 and est.fully_measured is False


# --------------------------------------------------------------------------- #
# The correction, against §2.5 / §2.6's hand-derived values
# --------------------------------------------------------------------------- #


def test_the_conservative_allowance_is_unchanged():
    """§10.1: do not silently redefine the legacy allowance's public meaning."""
    assert estimate_image_tokens_for_set(1, model=OPUS) == 177_008


def test_a_vector_e_size_sheet_costs_about_half_the_conservative_allowance():
    """§2.6 decomposes the overstatement as ~1.9x. Asserted as a ratio."""
    ratio = estimate_image_tokens_for_set(1, model=OPUS) / tokens(E)
    assert 1.85 < ratio < 1.95, ratio


def test_the_plan_reference_value_is_reproduced_within_the_rounding_delta():
    """92,871 (round-the-dimension) vs 93,013 (the renderer's irect). 0.15%."""
    assert tokens(E) == pytest.approx(92_871, rel=0.003)
    assert tokens(SQUARE) == pytest.approx(116_481, rel=0.003)
    # ...and the renderer's own value exactly, which is what actually bills.
    assert tokens(E) == 93_013


def test_the_mixed_set_total_matches_the_plans_independent_derivation():
    """§2.5's 20 E + 8 D + 6 B + 2 letter set: the plan derives 3,150,948."""
    bases = ([basis(E)] * 20 + [basis(D)] * 8 + [basis(B)] * 6 + [basis(LETTER)] * 2)
    est = estimate_image_tokens_for_bases(bases, model=OPUS)
    assert est.tokens == pytest.approx(3_150_948, rel=0.003)
    assert est.vector_pages == 36 and est.fully_measured
    # The shipped allowance quotes this set at roughly twice that.
    assert est.conservative_tokens / est.tokens > 1.9


# --------------------------------------------------------------------------- #
# Model tier: the same pixels price differently (§2.4)
# --------------------------------------------------------------------------- #


def test_the_same_page_costs_differently_on_a_standard_tier_model():
    """4,784 vs 1,568 per image. Counting once and reusing is a ~3x error."""
    hi = tokens(E, model=OPUS)
    lo = tokens(E, model=HAIKU)
    assert lo < hi
    assert hi / lo > 1.5


def test_hi_res_models_agree_with_each_other():
    """Opus 5 and Sonnet 5 share the tier, which is why §2.4 calls it latent."""
    assert tokens(E, model=OPUS) == tokens(E, model=SONNET)


# --------------------------------------------------------------------------- #
# Grid, overlap and target-override coverage (§10.5)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("grid", [6, 5, 3, 2])
def test_image_count_is_the_grid_plus_one_overview(grid):
    sizes = tiling.image_pixel_sizes(34 * 72.0, 44 * 72.0, rows=grid, cols=grid)
    assert len(sizes) == grid * grid + 1 == tiling.total_images_for_grid(grid, grid)


@pytest.mark.parametrize("overlap", [0.0, tiling.DEFAULT_OVERLAP_FRAC, 0.20])
def test_more_overlap_never_reduces_the_estimate(overlap):
    """Overlap enlarges every interior tile, so tokens rise monotonically."""
    zero = tokens(E, overlap_frac=0.0)
    assert tokens(E, overlap_frac=overlap) >= zero


def test_overlap_actually_moves_the_number():
    """Guards the test above against passing on an ignored parameter."""
    assert tokens(E, overlap_frac=0.20) > tokens(E, overlap_frac=0.0)


def test_the_vector_target_override_changes_a_vector_page(monkeypatch):
    """A lower long-edge target renders smaller tiles, so a vector page costs less."""
    default = tokens(E)
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1240")
    lowered = tokens(E)
    assert lowered < default


def test_the_vector_target_override_does_not_touch_raster_or_few_image(monkeypatch):
    """Deliberate policy (§2.5): on a textless page the pixels are the only
    channel, and the <=20-image branch is not where the payload problem lives."""
    raster_before = tokens(E, classification=CLASSIFICATION_RASTER)
    few_before = tokens(E, rows=3, cols=3)
    monkeypatch.setenv(tiling.TILE_TARGET_PX_ENV, "1240")
    assert tokens(E, classification=CLASSIFICATION_RASTER) == raster_before
    assert tokens(E, rows=3, cols=3) == few_before


def test_every_tile_is_counted_even_though_the_renderer_may_drop_blank_ones():
    """§10.1 item 6. Blank suppression is decided from rendered pixels.

    Predicting it from word absence would quote low — a vector sheet's words sit
    in the title block while the drawing body is lines, so "no words here" says
    nothing about "nothing here".
    """
    sizes = tiling.image_pixel_sizes(34 * 72.0, 44 * 72.0)
    assert len(sizes) == 37
    assert all(w > 0 and h > 0 for w, h in sizes)


# --------------------------------------------------------------------------- #
# §10.2 — stage resolvers in the STANDARD estimate, and the critique run count
# --------------------------------------------------------------------------- #


def test_standard_estimate_prices_synthesis_with_its_own_resolved_model(monkeypatch):
    """It priced synthesis at the digest ``model``; synthesis has its own resolver.

    With a Sonnet digest the default resolution is Opus (synthesis falls back to
    ``REVIEW_MODEL_DEFAULT``), so the old code under-quoted that stage 2.5x on
    the configuration a cost-conscious operator is most likely to pick.
    """
    monkeypatch.setenv("DRAWING_ANALYZER_SYNTHESIS_MODEL", SONNET)
    cheap = estimate_drawing_set_cost(10, model=SONNET, synthesize=True).total_cost
    monkeypatch.setenv("DRAWING_ANALYZER_SYNTHESIS_MODEL", OPUS)
    dear = estimate_drawing_set_cost(10, model=SONNET, synthesize=True).total_cost
    assert dear > cheap


def test_standard_estimate_prices_focus_with_its_own_resolved_model(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_FOCUS_MODEL", SONNET)
    cheap = estimate_drawing_set_cost(4, model=SONNET, focus=True).total_cost
    monkeypatch.setenv("DRAWING_ANALYZER_FOCUS_MODEL", OPUS)
    dear = estimate_drawing_set_cost(4, model=SONNET, focus=True).total_cost
    assert dear > cheap


def test_an_unknown_priced_active_stage_voids_the_standard_total(monkeypatch):
    """Same rule the exhaustive path already had: no partial sum as the whole."""
    monkeypatch.setenv("DRAWING_ANALYZER_SYNTHESIS_MODEL", "claude-not-real-wp05")
    assert estimate_drawing_set_cost(
        10, model=SONNET, synthesize=True
    ).total_cost is None


def test_an_unknown_priced_INACTIVE_stage_does_not_void_the_total(monkeypatch):
    """§10.2: do not apply charges for an optional stage that will not execute.

    Synthesis needs >= 2 sheets. On a single sheet it never runs, so its model's
    price is irrelevant and the total must still be available.
    """
    monkeypatch.setenv("DRAWING_ANALYZER_SYNTHESIS_MODEL", "claude-not-real-wp05")
    est = estimate_drawing_set_cost(1, model=SONNET, synthesize=True)
    assert est.total_cost is not None and est.total_cost > 0


def test_critique_run_count_comes_from_the_runtime_resolver(monkeypatch):
    """A preview fixed at two reads under-quotes a four-read run by half."""
    def cost_at(runs: str | None) -> float:
        if runs is None:
            monkeypatch.delenv("DRAWING_ANALYZER_CRITIQUE_RUNS", raising=False)
        else:
            monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_RUNS", runs)
        est = estimate_exhaustive_run_cost(10, model=OPUS, batch=False)
        component = next(c for c in est.components if c.stage.startswith("Critique"))
        return component.cost

    two, one, four = cost_at(None), cost_at("1"), cost_at("4")
    assert one == pytest.approx(two / 2, rel=0.001)
    assert four == pytest.approx(two * 2, rel=0.001)


def test_the_resolved_critique_run_count_rides_the_estimate(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_RUNS", "3")
    est = estimate_exhaustive_run_cost(10, model=OPUS, batch=False)
    assert est.critique_runs == 3
    assert "×3" in next(c.stage for c in est.components if c.stage.startswith("Critique"))


def test_critique_imagery_is_priced_with_the_critique_model(monkeypatch):
    """§2.4: the same PNG dimensions price differently by model tier.

    Counting the images once with the digest model and reusing that for a
    standard-tier critique is a ~3x error. Latent while Opus 5 and Sonnet 5
    share the hi-resolution tier; reachable through one environment variable.
    """
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_MODEL", HAIKU)
    lo = next(c for c in estimate_exhaustive_run_cost(10, model=OPUS, batch=False).components
              if c.stage.startswith("Critique"))
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_MODEL", OPUS)
    hi = next(c for c in estimate_exhaustive_run_cost(10, model=OPUS, batch=False).components
              if c.stage.startswith("Critique"))
    assert lo.input_tokens < hi.input_tokens, (
        "critique image tokens must be counted with the critique model's own cap"
    )
