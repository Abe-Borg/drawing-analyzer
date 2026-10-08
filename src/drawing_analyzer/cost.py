"""Pre-run cost estimate for a drawing set (feeds the cost-confirm dialog).

Reading drawings is the app's most expensive action — one Opus 5.5 vision call
per sheet, each carrying the overview image plus every grid tile. This estimates
the spend *before* the run so the GUI can surface it and let the operator
confirm or cancel. Image inputs use measured geometry when available; billed
output includes adaptive thinking and is quoted as a planning band. Without
real usage records these are assumptions, not an invoice or a spending cap.
Pure + hermetic (no PyMuPDF, no network).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Sequence

from .core.api_config import REVIEW_MODEL_DEFAULT
from .models import (
    CLASSIFICATION_RASTER,
    CLASSIFICATION_VECTOR,
)
from .core.tokenizer import estimate_image_tokens_total
from .core.pricing import (
    PRICING_EFFECTIVE_DATE,
    estimate_request_cost,
    friendly_model_name,
    usage_record_cost,
)
from . import tiling
from .batch_digest import _batch_max_elapsed_seconds
from .pipeline import estimate_image_tokens_for_set


def _batch_wait_sentence() -> str:
    """How long a batch run will actually wait, in the dialog's own words.

    Derived from the engine's bound rather than written beside it. The app used
    to promise runs that "can run overnight (8+ hours)" while the collector gave
    up at four — the wording was not wrong about the queue, it was wrong about
    US. Reading the resolved value means an operator who sets
    ``DRAWING_ANALYZER_BATCH_MAX_ELAPSED_HOURS`` is quoted their own number, and
    a future change to the bound cannot leave this text behind.
    """
    hours = _batch_max_elapsed_seconds() / 3600.0
    shown = f"{hours:.0f}" if abs(hours - round(hours)) < 0.05 else f"{hours:.1f}"
    return (
        f"This run waits up to {shown} hours for the queue before it stops "
        "waiting and reports what it collected."
    )

# Per-sheet text overhead of the digest prompt (system + user instruction); the
# images dominate, so a fixed estimate is fine.
_ASSUMED_PROMPT_TOKENS_PER_SHEET = 800
# Visible digest text, used only when a later stage reads the digest. Thinking
# is billed as output but never passed to synthesis, focus or cross-sheet QC.
_ASSUMED_DIGEST_TEXT_TOKENS_PER_SHEET = 2_000
# No real run manifests are available for calibration. A 4k lower planning
# allowance includes modest thinking; the upper end uses the runtime's full
# read envelope. The recorded 16k-thinking reads fit inside this band.
_ASSUMED_READ_OUTPUT_TOKENS_LOW = 4_000
# The synthesis pass emits one set-level overview.
_ASSUMED_SYNTHESIS_OUTPUT_TOKENS = 2_000
# A per-run focus adds one per-sheet "Focus findings" section to each digest
# and one set-level focus-report pass (text-only, like synthesis).
_ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET = 500
_ASSUMED_FOCUS_OUTPUT_TOKENS = 2_000

# ~4 chars/token for English technical prose — the same rough heuristic
# implicit elsewhere in this module's assumed-token constants — used to turn
# an uploaded project-specifications char count into a display token count.
_SPEC_CHARS_PER_TOKEN_ESTIMATE = 4


def _read_output_band(*, model: str, critique: bool = False, focus: bool = False) -> tuple[int, int]:
    from .core.api_config import output_cap_for_model
    from .critique import DEFAULT_CRITIQUE_MAX_TOKENS
    from .digest import DEFAULT_DIGEST_MAX_TOKENS

    high = output_cap_for_model(
        model, requested=DEFAULT_CRITIQUE_MAX_TOKENS if critique else DEFAULT_DIGEST_MAX_TOKENS
    )
    low = _ASSUMED_READ_OUTPUT_TOKENS_LOW
    if focus and not critique:
        low += _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET
    return min(low, high), high


def _sum_costs(costs: Sequence[float | None]) -> float | None:
    return None if any(c is None for c in costs) else sum(c for c in costs if c is not None)


def _specs_cost_contribution(
    spec_chars: int, sheet_count: int, *, model: str, batch: bool,
    request_input_tokens: Sequence[int] | None = None,
) -> tuple[int, float | None]:
    """``(display_tokens, usd_cost)`` for an uploaded project-specifications
    block across the whole run.

    Must mirror how ``digest.py``/``batch_digest.py`` actually issue the
    requests, which differs by transport:

    - ``batch=True`` (the Message-Batches path, and the GUI's default): the
      actual per-sheet batch-item build ALWAYS passes ``cache_specs=False``
      (parallel submission means a cache breakpoint would only add the
      write-cost premium with nothing yet written to read — see
      ``batch_digest.submit_drawing_batch``'s docstring). So every sheet
      bills the specs block as ordinary, uncached input at the batch
      discount rate — no cache multiplier applies here at all.
    - ``batch=False`` (the real-time path): the specs block rides the digest
      system prompt behind a ``cache_control`` breakpoint by default (see
      ``digest_system_prompt``), so the first sheet(s) pay the cache-WRITE
      multiplier and every subsequent sheet pays the cheap cache-READ
      multiplier. This is optimistic when ``max_workers > 1`` (a real run
      may have up to ``min(workers, sheet_count)`` sheets in flight before
      the first response lands and the cache becomes readable, so more than
      one sheet may pay the write price) — that multi-writer case makes the
      real number *more* expensive than this single-write estimate, not
      less, so it is a genuine (if usually small) understatement.

    WP-07 §12.6: the last clause used to appeal to "the 'slightly high' bias
    the rest of this module aims for". There is no such module-wide bias to
    appeal to, and describing one invited the reader to treat every figure here
    as a ceiling. What this module has is two explicitly-labelled bases, and
    which one produced a number is stated in the output
    (:data:`_BASIS_MEASURED` / :data:`_BASIS_CONSERVATIVE`): the conservative
    allowance IS deliberately high — every image a square at the raster target,
    at the model cap — while the shape-aware path prices each page from its
    measured geometry and aims at the real figure, not above it. Neither is a
    guaranteed maximum. Assumed-token constants, retries, how many findings a
    set turns out to have, and this function's own single-write assumption all
    move the invoice in both directions.
    """
    if spec_chars <= 0 or sheet_count <= 0:
        return 0, 0.0
    spec_tokens = max(1, spec_chars // _SPEC_CHARS_PER_TOKEN_ESTIMATE)
    display_tokens = spec_tokens * sheet_count
    # The block can move a request across a long-context threshold; its tier
    # must include the images and other prompt text, even though this helper
    # prices only the specifications contribution.
    inputs = request_input_tokens if request_input_tokens is not None else [0] * sheet_count
    costs = []
    for index, ordinary_input in enumerate(inputs):
        cost = usage_record_cost(
            model=model, batch=batch, prompt_tokens=ordinary_input + spec_tokens,
            input_tokens=spec_tokens if batch else 0,
            cache_write_tokens=spec_tokens if not batch and index == 0 else 0,
            cache_read_tokens=spec_tokens if not batch and index > 0 else 0,
        )
        costs.append(None if cost is None else float(cost))
    return display_tokens, _sum_costs(costs)


def _request_costs(
    inputs: Sequence[int], output_per_request: int, *, model: str, batch: bool,
    shared_prompt_tokens: int = 0,
) -> float | None:
    """Sum requests after selecting each request's own token-rate tier."""
    if not inputs:
        return estimate_request_cost(0, 0, model=model, batch=batch)
    return _sum_costs([
        estimate_request_cost(
            tokens, output_per_request, model=model, batch=batch,
            prompt_tokens=tokens + shared_prompt_tokens,
        )
        for tokens in inputs
    ])


@dataclass(frozen=True)
class ImageTokenEstimate:
    """A geometry-aware image-token estimate, with the assumptions it rests on.

    ``tokens`` is the planning number. ``conservative_tokens`` is what the size-free
    allowance (:func:`pipeline.estimate_image_tokens_for_set`) would have quoted
    for the same pages, kept beside it so a caller can show both and a test can
    assert the direction of the correction rather than a magic constant.
    """

    tokens: int
    conservative_tokens: int
    #: Pages counted by how their render target was decided.
    vector_pages: int = 0
    raster_pages: int = 0
    #: Pages that could not be classified, measured, or assigned a feasible grid
    #: and were therefore priced at the conservative allowance. Never dropped, never
    #: quietly treated as vector.
    unknown_pages: int = 0
    unmeasured_pages: int = 0
    #: Per-page counts retained so long-context tiers never use a set average.
    per_sheet_tokens: tuple[int, ...] = ()

    @property
    def pages(self) -> int:
        return self.vector_pages + self.raster_pages + self.unknown_pages

    @property
    def fully_measured(self) -> bool:
        """True when every page contributed real geometry."""
        return self.pages > 0 and self.unknown_pages == 0 and self.unmeasured_pages == 0


def estimate_image_tokens_for_bases(
    bases: "Sequence[Any]",
    *,
    rows: int | None = None,
    cols: int | None = None,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    model: str = REVIEW_MODEL_DEFAULT,
) -> ImageTokenEstimate:
    """Image tokens for one vision read of these pages, from their real shapes.

    The size-free allowance (:func:`pipeline.estimate_image_tokens_for_set`)
    bounds the full adaptive image budget. Measured pages use their displayed
    physical size and word presence to choose the same grid as the renderer,
    then price its exact image geometry. Explicit rows/cols retain fixed grids.

    The per-page walk mirrors the renderer exactly rather than approximating it:
    :func:`tiling.image_pixel_sizes` resolves the target through the same
    :func:`~drawing_analyzer.tiling.target_long_edge_px` policy (so the
    <=20-image branch and the vector-target override behave identically) and
    reproduces PyMuPDF's ``irect`` pixel sizing, which is position-dependent and
    not reproducible from dimensions alone. Measured against real renders it is
    pixel-exact on 18 of 20 page-shape/grid combinations and within 0.0035% of
    token count on the other two.

    Tokens are estimated for **this** ``model``. The same PNG dimensions price
    differently across model tiers — a hi-resolution model caps at 4784 tokens
    per image and a standard-tier one at 1568 — so digest and critique imagery
    must be estimated with their own resolved models, never counted once and
    reused (§2.4).

    A page classified ``unknown``, one that could not be measured, or one with
    no feasible adaptive grid falls back to the conservative per-sheet allowance
    and is counted separately. It is
    never assumed vector: vector is the *cheaper* target, so guessing it would
    quote low on precisely the pages least understood.
    """
    from .pipeline import estimate_image_tokens_for_set

    conservative_per_sheet = estimate_image_tokens_for_set(
        1, rows=rows, cols=cols, model=model
    )
    total = 0
    per_sheet_tokens = []
    vector = raster = unknown = unmeasured = 0
    for basis in bases or []:
        classification = str(getattr(basis, "classification", "") or "")
        width = float(getattr(basis, "width_pt", 0.0) or 0.0)
        height = float(getattr(basis, "height_pt", 0.0) or 0.0)
        measurable = (
            bool(getattr(basis, "geometry_ok", False))
            and all(math.isfinite(v) and v > 0 for v in (width, height))
        )
        if not measurable:
            unmeasured += 1
        if not measurable or classification not in (
            CLASSIFICATION_VECTOR, CLASSIFICATION_RASTER
        ):
            unknown += 1
            total += conservative_per_sheet
            per_sheet_tokens.append(conservative_per_sheet)
            continue
        try:
            sizes = tiling.image_pixel_sizes(
                width, height, rows=rows, cols=cols, overlap_frac=overlap_frac,
                is_raster=classification == CLASSIFICATION_RASTER,
            )
        except tiling.InfeasibleGridError:
            # Retain this page in the budget, without claiming a measured grid.
            # Rendering will report its failure; the confirmation must still open.
            unknown += 1
            total += conservative_per_sheet
            per_sheet_tokens.append(conservative_per_sheet)
            continue
        if classification == CLASSIFICATION_RASTER:
            raster += 1
        else:
            vector += 1
        page_tokens = estimate_image_tokens_total(sizes, model=model)
        total += page_tokens
        per_sheet_tokens.append(page_tokens)
    return ImageTokenEstimate(
        tokens=total,
        conservative_tokens=conservative_per_sheet * (vector + raster + unknown),
        vector_pages=vector,
        raster_pages=raster,
        unknown_pages=unknown,
        unmeasured_pages=unmeasured,
        per_sheet_tokens=tuple(per_sheet_tokens),
    )


def _image_token_requests_for(
    sheet_count: int, bases, *, rows: int | None, cols: int | None, model: str,
) -> tuple[tuple[int, ...], bool, int]:
    """``(tokens_per_sheet, shape_aware, unmeasured_pages)`` from each sheet.

    One resolver so the standard and exhaustive estimators cannot disagree about
    when the geometry-aware number applies. ``bases`` is used only when it covers
    **every** sheet being priced: a partial *list* mixed with a conservative
    remainder would be neither figure, and which sheets were missing would not be
    visible in the total.

    Covering every sheet is not the same as measuring every sheet.
    :func:`estimate_image_tokens_for_bases` already substitutes the conservative
    allowance for a page it could not classify or could not measure — which is
    right, and strictly better than discarding the whole scan over one bad page.
    But the resulting number is then only *partly* measured, and
    ``shape_aware`` must say so: it is the flag both dialogs use to claim
    "based on each page's measured size", and that claim would be false for the
    page that fell back. ``ImageTokenEstimate.fully_measured`` is the honest
    predicate, and the count of pages that fell back rides along so the dialog
    can name it rather than silently downgrading a nearly-complete scan.
    """
    if bases and len(bases) == sheet_count and sheet_count > 0:
        est = estimate_image_tokens_for_bases(
            bases, rows=rows, cols=cols, model=model
        )
        return est.per_sheet_tokens, est.fully_measured, est.unknown_pages
    per_sheet = estimate_image_tokens_for_set(1, rows=rows, cols=cols, model=model)
    return (per_sheet,) * sheet_count, False, 0


@dataclass(frozen=True)
class DrawingCostEstimate:
    sheet_count: int
    file_count: int
    model: str
    image_tokens: int
    input_tokens: int
    output_tokens: int
    total_cost: float | None  # None when the model's pricing is unknown
    batch: bool = False  # estimate reflects the 50% Batch-API discount
    spec_chars: int = 0  # uploaded project-specifications char count, if any
    #: True only when EVERY page's image tokens came from its measured shape.
    #: Additive and defaulted, so an older caller's construction still loads.
    shape_aware: bool = False
    #: Pages that fell back to the conservative allowance inside an otherwise
    #: measured set (unreadable, or unclassifiable). 0 on a fully conservative
    #: estimate too — read it together with ``shape_aware``.
    unmeasured_pages: int = 0
    #: The legacy output_tokens/total_cost fields carry the upper planning end.
    output_tokens_low: int | None = None
    low_cost: float | None = None

    @property
    def high_cost(self) -> float | None:
        return self.total_cost


def estimate_drawing_set_cost(
    sheet_count: int,
    *,
    file_count: int = 0,
    model: str = REVIEW_MODEL_DEFAULT,
    rows: int | None = None,
    cols: int | None = None,
    synthesize: bool = True,
    batch: bool = False,
    focus: bool = False,
    spec_chars: int = 0,
    bases: "Sequence[Any] | None" = None,
) -> DrawingCostEstimate:
    """Estimate the cost of digesting ``sheet_count`` sheets.

    ``synthesize`` mirrors the run: when on (and ≥2 sheets) it adds the
    text-only cross-sheet pass, whose input is roughly the per-sheet digests fed
    back in. Image tokens are folded into ``input_tokens`` (vision is billed as
    input). ``batch=True`` applies the 50% Message Batches discount only to the
    per-sheet digest spend; synthesis and the optional focus report are issued
    synchronously and are therefore priced at the full real-time rate.
    ``focus`` mirrors a per-run focus: each sheet's digest grows by a
    focus-findings section, and one more text-only pass re-reads the digests.

    ``spec_chars`` (uploaded project-specifications character count, 0 when
    none) is priced separately at the cache-aware rate using each complete
    request's pricing tier (see
    :func:`_specs_cost_contribution`) rather than folded into the flat 1x
    ``input_tokens`` sum above — it rides a system-prompt block that is
    cache-written once and cache-read (~0.1x) on every sheet after, so pricing
    it at the flat rate would overstate what it actually costs.
    """
    # WP-05 §10.2. Synthesis and the focus report have their own runtime
    # resolvers (``DRAWING_ANALYZER_SYNTHESIS_MODEL`` / ``…_FOCUS_MODEL``), and
    # this path priced both at the digest ``model``. The exhaustive estimator
    # already resolved them correctly, so a Sonnet digest with an Opus synthesis
    # was quoted right in one mode and wrong in the other — the mode a standard
    # run actually uses being the wrong one.
    stage_models = resolve_stage_models(model=model)
    image_requests, shape_aware, unmeasured = _image_token_requests_for(
        sheet_count, bases, rows=rows, cols=cols, model=model
    )
    image_tokens = sum(image_requests)
    read_low, read_high = _read_output_band(model=model, focus=focus)
    digest_output = sheet_count * read_high
    digest_output_low = sheet_count * read_low
    digest_text = sheet_count * _ASSUMED_DIGEST_TEXT_TOKENS_PER_SHEET
    if focus:
        digest_text += sheet_count * _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET
    digest_input = image_tokens + sheet_count * _ASSUMED_PROMPT_TOKENS_PER_SHEET
    digest_requests = [tokens + _ASSUMED_PROMPT_TOKENS_PER_SHEET for tokens in image_requests]
    spec_tokens = max(1, spec_chars // _SPEC_CHARS_PER_TOKEN_ESTIMATE) if spec_chars > 0 else 0
    input_tokens = digest_input
    output_tokens = digest_output
    output_tokens_low = digest_output_low
    stage_costs: list[float | None] = [
        _request_costs(
            digest_requests, read_high, model=model, batch=batch,
            shared_prompt_tokens=spec_tokens,
        )
    ]

    if synthesize and sheet_count >= 2:
        synth_input = digest_text + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        input_tokens += synth_input
        output_tokens += _ASSUMED_SYNTHESIS_OUTPUT_TOKENS
        output_tokens_low += _ASSUMED_SYNTHESIS_OUTPUT_TOKENS
        stage_costs.append(estimate_request_cost(
            synth_input, _ASSUMED_SYNTHESIS_OUTPUT_TOKENS,
            model=stage_models.synthesis, batch=False,
        ))

    if focus and sheet_count >= 1:
        # The focus report likewise re-reads the per-sheet digests as text.
        focus_input = digest_text + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        input_tokens += focus_input
        output_tokens += _ASSUMED_FOCUS_OUTPUT_TOKENS
        output_tokens_low += _ASSUMED_FOCUS_OUTPUT_TOKENS
        stage_costs.append(estimate_request_cost(
            focus_input, _ASSUMED_FOCUS_OUTPUT_TOKENS,
            model=stage_models.focus, batch=False,
        ))

    low_cost = _sum_costs([_request_costs(
        digest_requests, read_low, model=model, batch=batch,
        shared_prompt_tokens=spec_tokens,
    ), *stage_costs[1:]])
    total_cost = _sum_costs(stage_costs)
    spec_display_tokens, spec_cost = _specs_cost_contribution(
        spec_chars, sheet_count, model=model, batch=batch,
        request_input_tokens=digest_requests,
    )
    # ``spec_cost`` is 0.0 (never None) whenever spec_chars <= 0 (see
    # _specs_cost_contribution's early return), so this is a no-op add in
    # that case. Propagates an unknown-priced model's ``None`` from either
    # side, rather than coercing it into a bogus, spec-cost-only total.
    total_cost = None if total_cost is None or spec_cost is None else total_cost + spec_cost
    low_cost = None if low_cost is None or spec_cost is None else low_cost + spec_cost
    input_tokens += spec_display_tokens
    return DrawingCostEstimate(
        sheet_count=sheet_count,
        file_count=file_count,
        model=model,
        image_tokens=image_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        output_tokens_low=output_tokens_low,
        total_cost=total_cost,
        low_cost=low_cost,
        batch=batch,
        spec_chars=spec_chars,
        shape_aware=shape_aware,
        unmeasured_pages=unmeasured,
    )


#: §10.4. Plain language, and the distinction a reviewer can act on: whether the
#: figure came from the pages in front of them or from a deliberately high
#: stand-in. Neither is called a confidence interval or a guaranteed maximum,
#: because it is neither.
_BASIS_MEASURED = (
    "Based on each page's measured size and text layer."
)
_BASIS_CONSERVATIVE = (
    "Conservative planning estimate — the pages have not been measured yet, so "
    "the image allowance assumes the most expensive shape."
)

_OUTPUT_BAND_NOTE = (
    "Output ranges include adaptive thinking, which is billed as output. "
    "No real run usage records were supplied for calibration; the read ranges "
    "allow modest thinking through the full per-read output envelope. "
    "Retries and unusually large text inputs can add cost."
)


#: The middle case: the scan covered the set, but some pages could not be read
#: or classified and took the conservative allowance. Saying "measured" would be
#: false for those pages; saying "not measured yet" would throw away a nearly
#: complete scan and quote much higher than the evidence supports.
_BASIS_PARTLY_MEASURED = (
    "Based on each page's measured size and text layer, except {n} page(s) that "
    "could not be read — those use the conservative allowance."
)


def _basis_line(shape_aware: bool, unmeasured: int = 0) -> str:
    if shape_aware:
        return _BASIS_MEASURED
    if unmeasured > 0:
        return _BASIS_PARTLY_MEASURED.format(n=unmeasured)
    return _BASIS_CONSERVATIVE


def format_drawing_cost_prompt(est: DrawingCostEstimate) -> str:
    """Human-readable confirmation message for the cost-confirm dialog."""
    where = f" from {est.file_count} file(s)" if est.file_count else ""
    how = (
        "submitted as one Message Batch (≈50% cheaper than real-time)"
        if est.batch
        else "one vision call per sheet"
    )
    lines = [
        f"About to analyze {est.sheet_count} drawing sheet(s){where} with "
        f"{friendly_model_name(est.model)} vision — {how}.",
        "",
        f"Estimated usage: ~{est.input_tokens:,} input tokens "
        f"(~{est.image_tokens:,} from images) / "
        f"{est.output_tokens_low if est.output_tokens_low is not None else est.output_tokens:,}"
        f"–{est.output_tokens:,} output.",
        _basis_line(est.shape_aware, est.unmeasured_pages),
        _OUTPUT_BAND_NOTE,
    ]
    if est.spec_chars:
        # WP-04 §9.2. The old line promised a ~0.1x prompt-cache read on BOTH
        # transports. On the batch path there is no cache breakpoint at all —
        # ``batch_digest.submit_drawing_batch`` always passes
        # ``cache_specs=False``, because parallel submission means a breakpoint
        # would only buy the write premium with nothing yet written to read — so
        # every sheet bills the block as ordinary batch input. The arithmetic in
        # ``_specs_cost_contribution`` already prices it that way; only this
        # sentence was wrong, and it was wrong in the operator's favour, which is
        # the direction that gets noticed on the invoice.
        lines.append(
            f"Project specifications: ~{est.spec_chars:,} chars attached — "
            + ("billed as ordinary batch input on every sheet (the batch path "
               "sets no prompt-cache breakpoint)."
               if est.batch else
               "usually cached after the first sheet(s) (~0.1x rate); sheets "
               "sent before the first response lands, and any sheet after the "
               "cache expires, pay the write rate instead.")
        )
    if est.total_cost is not None:
        batch_note = (
            " (Batch digest rate; synchronous text passes are full rate)"
            if est.batch else ""
        )
        lines.append(
            "Estimated cost: "
            + (f"${est.low_cost:,.2f} – ${est.high_cost:,.2f}" if est.low_cost is not None
               else f"~${est.total_cost:,.2f}")
            + f"{batch_note} — a rough "
            "estimate, not a cap. "
            + ("The image figure now comes from the pages themselves, but the "
               "text riding with each sheet is not bounded by it, so a "
               "text-heavy set can still land above this."
               if est.shape_aware else
               "The image allowance is a per-model worst case, but the text "
               "riding with each sheet is not bounded by it, so a text-heavy "
               "set can land above this figure.")
            + " Every stage caches separately: a sheet already in the local "
            "result cache skips its own call, but that does not mean the "
            "set-level passes are free — and because they key on the whole "
            "set, adding or changing one sheet re-runs them in full."
        )
    else:
        lines.append("Estimated cost: unavailable for this model.")
    if est.batch:
        lines += [
            "",
            "Nothing is sent until you confirm. Batch mode puts your sheets in "
            "Anthropic's shared queue: they are processed when they reach the "
            "front, so this can finish in a few minutes, take a few hours, or "
            "run overnight (8+ hours) depending on how busy the queue is. Best "
            "left running when you're not in a rush.",
            _batch_wait_sentence(),
        ]
    else:
        lines += [
            "",
            "Nothing is sent until you confirm. Real-time mode skips the queue — "
            "expect roughly 4–6 minutes per sheet, with results as they finish.",
        ]
    lines += ["", "Proceed with the analysis?"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Exhaustive-QC cost preview (Phase 23B, §15.7)
# --------------------------------------------------------------------------- #
#
# When QC Markups is on the run is the full exhaustive stack (DA-010), so the
# digest-only figure above badly under-states it. This preview adds a component
# per paid QC stage and a total range: billed thinking, finding/claim volume,
# investigation rounds, prefix reuse and discipline sharding vary pre-run.

# Per-read critique output. Each of the two reads bills the sheet's image input
# again (its input ≈ the digest images) — but in a ``use_batch`` run both reads
# ride one Message Batch referencing a single shared upload (Phase 23C), so the
# rate is halved and the sheet is uploaded once, not re-rendered per read.
_ASSUMED_CROSS_QC_OUTPUT_TOKENS = 2_000
_ASSUMED_PROSE_STRAGGLER_INPUT_TOKENS = 1_500     # one small structuring allowance
_ASSUMED_PROSE_STRAGGLER_OUTPUT_TOKENS = 500
_ASSUMED_VERIFY_INPUT_TOKENS_PER_FINDING = 1_500  # a high-DPI crop + prompt
# The verdict itself is ~150 tokens, but verification now runs adaptive thinking
# at medium effort and thinking bills at the OUTPUT rate — so an estimate built
# on the visible answer alone under-states this stage several-fold.
_ASSUMED_VERIFY_OUTPUT_TOKENS_PER_FINDING = 1_400
_ASSUMED_CITATION_INPUT_TOKENS_PER_REF = 2_000  # prompt + search snippets
# Price roughly one clause-page fetch per normalized ref at the tool's actual
# content ceiling below. Multiple fetches, claim chunks and pause resumes can
# cost more; this is a cold-run volume estimate, not a dollar-spend ceiling.
# Adaptive reasoning shares the output bill with the short visible verdict.
_ASSUMED_CITATION_OUTPUT_TOKENS_PER_REF = 1_400
_ASSUMED_WEB_SEARCHES_PER_REF = 2
# Phase A planning stages — one text-only call each. Identity reads a budgeted
# corpus (digest heads + early text layers, scaling gently with the set);
# the planner reads the identity + per-sheet digest heads.
_ASSUMED_IDENTITY_INPUT_TOKENS_BASE = 2_000
_ASSUMED_IDENTITY_INPUT_TOKENS_PER_SHEET = 400
_ASSUMED_IDENTITY_OUTPUT_TOKENS = 1_200
_ASSUMED_PLAN_INPUT_TOKENS_BASE = 2_000
_ASSUMED_PLAN_INPUT_TOKENS_PER_SHEET = 250
_ASSUMED_PLAN_OUTPUT_TOKENS = 2_500
# A recorded standard run had 287 / 39 = 7.36 findings per sheet. Exhaustive
# mode adds critique, cross-QC and auditor findings. This 8–20 planning band
# allows that growth; it is an assumption, not a measured distribution.
_FINDINGS_PER_SHEET_LOW = 8.0
_FINDINGS_PER_SHEET_HIGH = 20.0
# Eligible normalized-ref counts are unknown pre-run — a low–high band.
_REFS_PER_SHEET_LOW = 0.1
_REFS_PER_SHEET_HIGH = 1.0
# Phase C investigation — a multi-turn escalation of the findings that stay
# UNCERTAIN after verification, on the (Opus) escalation model. Each turn
# re-sends the conversation, so the per-round input allowance dominates
# (history replay + one new crop per turn). Capped at the per-run default
# budget — the cap the stage itself enforces, which scales with the set.
_UNCERTAIN_FINDINGS_FRACTION = 0.2
_ASSUMED_INVESTIGATE_ROUNDS_LOW = 3
_ASSUMED_INVESTIGATE_INPUT_TOKENS_PER_ROUND = 6_000
_ASSUMED_INVESTIGATE_EVIDENCE_TOKENS_PER_ROUND = 4_000
_ASSUMED_INVESTIGATE_OUTPUT_TOKENS_PER_ROUND_LOW = 1_500


@dataclass(frozen=True)
class CostComponent:
    """One paid stage's contribution to the exhaustive-run estimate."""

    stage: str
    input_tokens: int
    output_tokens: int
    cost: float | None       # None when the model's price is unknown
    transport: str           # "batch" | "real-time"
    note: str = ""
    low_cost: float | None = None
    output_tokens_low: int | None = None
    input_tokens_low: int | None = None


@dataclass(frozen=True)
class ExhaustiveCostEstimate:
    sheet_count: int
    file_count: int
    model: str
    components: list[CostComponent]
    low_cost: float | None
    high_cost: float | None
    batch: bool = True  # estimate reflects the 50% Batch-API discount / queue transport
    critique_batch: bool = True
    verified_effective_date: str = PRICING_EFFECTIVE_DATE
    spec_chars: int = 0  # uploaded project-specifications char count, if any
    # Which model each stage resolved to. ``None`` only for an estimate built by
    # an older caller; the field is additive and defaulted so stored payloads and
    # third-party constructions keep loading.
    stage_models: "StageModels | None" = None
    #: Critique reads per sheet, as the runtime resolver reported them (§10.2).
    #: Defaulted to the shipping value so an older caller's construction loads.
    critique_runs: int = 2
    #: True only when EVERY page's image tokens came from its measured shape.
    shape_aware: bool = False
    #: Pages that fell back to the conservative allowance inside a measured set.
    unmeasured_pages: int = 0


@dataclass(frozen=True)
class StageModels:
    """The model each priced stage will actually run on.

    Resolved through the *same* functions the runtime uses (``critique_model()``,
    ``harvest_model()``, ...), so a ``DRAWING_ANALYZER_*_MODEL`` override — or a
    stage whose default simply is not the review model, as the prose harvest's is
    not — is priced at the rate that will really be billed. Before this existed
    the estimate priced nine of eleven components at one ``model`` argument, so
    moving any stage off the review model silently over- or under-quoted the
    pre-run dialog by that stage's whole share.
    """

    digest: str
    critique: str
    identity: str
    review_plan: str
    synthesis: str
    focus: str
    cross_qc: str
    harvest: str
    citation: str
    verification: str
    investigation: str

    @property
    def distinct(self) -> list[str]:
        """Every model this run will touch, in first-appearance order."""
        seen: list[str] = []
        for m in (
            self.digest, self.critique, self.identity, self.review_plan,
            self.synthesis, self.focus, self.cross_qc, self.harvest,
            self.citation, self.verification, self.investigation,
        ):
            if m and m not in seen:
                seen.append(m)
        return seen


def resolve_stage_models(
    *, model: str, verification_model: str | None = None,
) -> StageModels:
    """Resolve every stage's model the way the pipeline will at run time.

    Imports are deferred to call time for two reasons: the resolvers read the
    environment on every call (so resolving at import would freeze a stale
    answer), and it keeps this module's import graph shallow — the same reason
    the verification model was already resolved lazily here.

    ``model`` is the review model the caller supplies (the GUI passes
    ``REVIEW_MODEL_DEFAULT``) and stands in for the digest, whose model is a
    threaded parameter rather than an env-var resolver.
    """
    from .citation_check import citation_model
    from .critique import critique_model
    from .cross_qc import cross_qc_model
    from .focus import default_focus_model
    from .investigate import investigation_model
    from .prose_harvest import harvest_model
    from .review_planner import default_review_plan_model
    from .set_identity import default_identity_model
    from .synthesis import default_synthesis_model
    from .verify import default_verify_model

    return StageModels(
        digest=model,
        critique=critique_model(),
        identity=default_identity_model(),
        review_plan=default_review_plan_model(),
        synthesis=default_synthesis_model(),
        focus=default_focus_model(),
        cross_qc=cross_qc_model(),
        harvest=harvest_model(),
        citation=citation_model(),
        verification=verification_model or default_verify_model(),
        investigation=investigation_model(),
    )


def _stage_note(note: str, *, stage_model: str, primary: str) -> str:
    """Append the stage's model to its note when it diverges from ``primary``.

    Mirrors how the Verification row has always named its model, so a reader of
    the cost dialog can see *why* one line is cheaper than its token count
    suggests. A stage on the primary model reads unchanged.
    """
    if not stage_model or stage_model == primary:
        return note
    label = friendly_model_name(stage_model)
    return f"{note} — on {label}" if note else f"on {label}"


def _component(
    stage: str, input_tokens: int, output_tokens: int, *, model: str, batch: bool,
    extra_cost: float = 0.0, note: str = "", primary_model: str | None = None,
    input_tokens_low: int | None = None, output_tokens_low: int | None = None,
    request_inputs: Sequence[int] | None = None,
    request_inputs_low: Sequence[int] | None = None,
) -> CostComponent:
    def price(inputs: Sequence[int] | None, inp: int, out: int) -> float | None:
        if inputs is None:
            return estimate_request_cost(inp, out, model=model, batch=batch)
        return _request_costs(inputs, out // len(inputs) if inputs else 0, model=model, batch=batch)

    base = price(request_inputs, input_tokens, output_tokens)
    cost = None if base is None else base + extra_cost
    low_base = price(
        request_inputs if request_inputs_low is None else request_inputs_low,
        input_tokens if input_tokens_low is None else input_tokens_low,
        output_tokens if output_tokens_low is None else output_tokens_low,
    )
    if primary_model is not None:
        note = _stage_note(note, stage_model=model, primary=primary_model)
    return CostComponent(
        stage=stage, input_tokens=input_tokens, output_tokens=output_tokens,
        cost=cost, transport="batch" if batch else "real-time", note=note,
        low_cost=None if low_base is None else low_base + extra_cost,
        input_tokens_low=input_tokens_low, output_tokens_low=output_tokens_low,
    )


def _critique_prefix_costs(
    *, prefix_tokens: int, output_tokens: int, sheet_count: int, runs: int,
    model: str, batch: bool,
) -> tuple[float | None, float | None]:
    """``(reuse, no_reuse)`` cost of the critique reads, by their real rate class.

    WP-05 §10.2. ``critique_sheet_self_consistent`` sets ``cache_prefix = runs >= 2``
    (``critique.py``), which attaches an ephemeral breakpoint to the shared image
    prefix on the **real-time** path. So read 1 cache-*writes* that ~90k-token
    prefix at 1.25x and reads 2..N serve it at 0.1x — while this estimator was
    billing all N at the ordinary 1x rate.

    The error runs in both directions, which is why it needs a band rather than a
    correction. For ``runs=2`` the multipliers are:

    ===============  ==========================
    scenario          prefix read-equivalents
    ===============  ==========================
    flat (old)        2.00
    reuse (Opus 5.5)  1.25 + 0.05 = 1.30
    reuse (others)    1.25 + 0.10 = 1.35
    no reuse          1.25 x 2    = 2.50
    ===============  ==========================

    The flat number over-quotes successful reuse and under-quotes a total
    miss, on the single largest QC line. §10.2 asks for the two
    scenarios rather than an invented hit probability, and that is what this
    returns: the low end assumes every repeat read hits, the high end assumes
    every breakpoint misses and re-writes.

    Neither multiplier touches **output**, which is billed at the output rate per
    read in both scenarios — discounting output with an input-cache multiplier is
    explicitly called out in §10.2.

    Batch items carry no breakpoint (``submit_critique_batch`` never sets one, and
    parallel submission could not read a cache still being written), and a single
    read gets no breakpoint either. Both collapse to ordinary input, so both
    scenarios return the same figure.
    """
    if batch or runs < 2:
        flat = usage_record_cost(
            model=model, input_tokens=prefix_tokens, output_tokens=output_tokens, batch=batch
        )
        if flat is None:
            return None, None
        total = flat * runs * sheet_count
        return float(total), float(total)

    write = usage_record_cost(
        model=model, cache_write_tokens=prefix_tokens, output_tokens=output_tokens, batch=False
    )
    read = usage_record_cost(
        model=model, cache_read_tokens=prefix_tokens, output_tokens=output_tokens, batch=False
    )
    if write is None or read is None:
        return None, None
    reuse = (write + read * (runs - 1)) * sheet_count
    no_reuse = (write * runs) * sheet_count
    return float(reuse), float(no_reuse)


def _cross_qc_component(sheet_count: int, digest_text: int, *, model: str,
                        primary_model: str) -> CostComponent:
    """Price map/reconcile work without pretending we know discipline groups.

    With only a sheet count, ceil(n/40) is the fewest shards, and n is the
    most (one discipline per sheet). Carry both scenarios rather than quote
    the minimum as if it were the actual shard count. Reconciliation uses the
    runtime's fact limits and pair-call backstop; actual facts can cost less.
    """
    from math import ceil
    from .core.api_config import PHASE_CROSS_QC, phase_output_cap
    from .cross_qc import (
        DEFAULT_MAP_MAX_FACTS, MAX_FACTS_PER_RECONCILE,
        MAX_SHEETS_SINGLE_CALL, _MAX_RECONCILE_PAIR_CALLS,
    )

    sharded = sheet_count > MAX_SHEETS_SINGLE_CALL
    maps_low = ceil(sheet_count / MAX_SHEETS_SINGLE_CALL) if sharded else 1
    maps_high = sheet_count if sharded else 1

    def reconcile_calls(maps: int) -> int:
        if not sharded:
            return 0
        facts = maps * DEFAULT_MAP_MAX_FACTS
        if facts <= MAX_FACTS_PER_RECONCILE:
            return 1
        groups = ceil(facts / max(1, MAX_FACTS_PER_RECONCILE // 2))
        return min(groups * (groups - 1) // 2, _MAX_RECONCILE_PAIR_CALLS)

    rec_low, rec_high = reconcile_calls(maps_low), reconcile_calls(maps_high)
    # Cross-QC also reads up to 4k characters of text layer per sheet. Compact
    # map facts are assumed to occupy 150 tokens each, plus the sheet manifest.
    def inputs(maps: int, recs: int) -> list[int]:
        fact_tokens = min(maps * DEFAULT_MAP_MAX_FACTS, MAX_FACTS_PER_RECONCILE) * 150
        # Fill each shard up to the runtime's sheet limit while reserving one
        # sheet for each remaining shard. The fewest-shards scenario therefore
        # uses full 40-sheet chunks plus a tail, and the most-shards scenario
        # one sheet per call. Averaging chunks could hide a long-context tier.
        text_per_sheet = digest_text // sheet_count if sheet_count else 0
        counts = []
        remaining = sheet_count
        for index in range(maps):
            count = min(MAX_SHEETS_SINGLE_CALL, remaining - (maps - index - 1))
            counts.append(count)
            remaining -= count
        return [
            count * (text_per_sheet + 1_000) + _ASSUMED_PROMPT_TOKENS_PER_SHEET
            for count in counts
        ] + [fact_tokens + sheet_count * 30 + _ASSUMED_PROMPT_TOKENS_PER_SHEET] * recs

    high_out = phase_output_cap(PHASE_CROSS_QC, model=model)
    note = (f"{maps_low}–{maps_high} discipline shard(s) + {rec_low}–{rec_high} "
            "reconciliation call(s); discipline grouping and fact volume unknown"
            if sharded else "one text-only whole-set pass")
    high_inputs, low_inputs = inputs(maps_high, rec_high), inputs(maps_low, rec_low)
    return _component(
        "Cross-sheet QC", sum(high_inputs), (maps_high + rec_high) * high_out,
        input_tokens_low=sum(low_inputs),
        output_tokens_low=(maps_low + rec_low) * min(_ASSUMED_CROSS_QC_OUTPUT_TOKENS, high_out),
        request_inputs=high_inputs, request_inputs_low=low_inputs,
        model=model, batch=False, note=note + "; thinking included", primary_model=primary_model,
    )


def estimate_exhaustive_run_cost(
    sheet_count: int,
    *,
    file_count: int = 0,
    model: str = REVIEW_MODEL_DEFAULT,
    rows: int | None = None,
    cols: int | None = None,
    batch: bool = True,
    critique_batch: bool | None = None,
    focus: bool = False,
    spec_chars: int = 0,
    verification_model: str | None = None,
    bases: "Sequence[Any] | None" = None,
) -> ExhaustiveCostEstimate:
    """Estimate an **exhaustive QC** run's cost, component by component (§15.7).

    ``batch`` selects digest transport. ``critique_batch`` independently selects
    the two critique reads and defaults to ``batch`` for legacy callers. This
    prices Economy (both batch), Hybrid (real-time digest/batch critique), and
    Fast (both real-time) without changing any model or review contract.
    Synthesis, focus, cross-QC,
    verification, and citation still run real-time. Output includes thinking
    in a low–high band. Verification and citation also vary with the finding /
    unique-claim count. Verification is priced with the same independently
    configurable model the runtime verifier resolves.
    A component whose model price is unknown carries ``cost=None`` and makes
    ``low_cost``/``high_cost`` ``None`` too — the caller then shows token scale
    without a dollar figure. It must NOT be dropped from the sum: publishing the
    remaining stages as the run's total under-quotes it while looking complete.

    ``spec_chars`` (uploaded project specifications) only affects the Digest
    component — the specs block is digest-only (see ``digest.py``), never sent
    to critique/cross-QC/verification/citation.
    """
    if critique_batch is None:
        critique_batch = batch
    # Every stage's model, resolved through the functions the runtime itself
    # calls — including the verifier's legacy compatibility override. ``model``
    # stands in for the digest, whose model is a threaded parameter rather than
    # an env-var resolver. An explicit ``verification_model`` still wins, which
    # is what the existing callers and tests pass.
    #
    # This supersedes resolving three stages inline: identity, harvest and
    # citation are the ones that deliberately differ today, but critique,
    # cross-QC, synthesis and the review plan are all independently overridable
    # too, and pricing those at ``model`` mis-quotes the moment one moves.
    stage_models = resolve_stage_models(
        model=model, verification_model=verification_model,
    )
    verification_model = stage_models.verification
    identity_model = stage_models.identity
    harvest_model = stage_models.harvest
    citation_model = stage_models.citation

    # Set totals, priced with each stage's own model — the same PNG dimensions
    # clamp at a different per-model cap, so one count cannot serve both (§2.4).
    digest_image_requests, shape_aware, unmeasured = _image_token_requests_for(
        sheet_count, bases, rows=rows, cols=cols, model=model
    )
    crit_image_requests, _, _ = _image_token_requests_for(
        sheet_count, bases, rows=rows, cols=cols, model=stage_models.critique
    )
    components: list[CostComponent] = []
    digest_set_images = sum(digest_image_requests)

    # Digest vision calls use the selected transport. The later synthesis and
    # focus report are synchronous calls even when digest/critique use Batch, so
    # show and price them independently rather than discounting them by mistake.
    digest_input = digest_set_images + sheet_count * _ASSUMED_PROMPT_TOKENS_PER_SHEET
    digest_requests = [tokens + _ASSUMED_PROMPT_TOKENS_PER_SHEET for tokens in digest_image_requests]
    spec_tokens = max(1, spec_chars // _SPEC_CHARS_PER_TOKEN_ESTIMATE) if spec_chars > 0 else 0
    read_low, read_high = _read_output_band(model=model, focus=focus)
    digest_output = sheet_count * read_high
    digest_output_low = sheet_count * read_low
    digest_text = sheet_count * _ASSUMED_DIGEST_TEXT_TOKENS_PER_SHEET
    if focus:
        digest_text += sheet_count * _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET
    spec_display_tokens, spec_cost = _specs_cost_contribution(
        spec_chars, sheet_count, model=model, batch=batch,
        request_input_tokens=digest_requests,
    )
    digest_cost = _request_costs(
        digest_requests, read_high, model=model, batch=batch,
        shared_prompt_tokens=spec_tokens,
    )
    digest_low_cost = _request_costs(
        digest_requests, read_low, model=model, batch=batch,
        shared_prompt_tokens=spec_tokens,
    )
    if digest_cost is None or spec_cost is None:
        digest_total_cost = None
    else:
        digest_total_cost = digest_cost + spec_cost
    components.append(CostComponent(
        stage="Digest",
        input_tokens=digest_input + spec_display_tokens,
        output_tokens=digest_output,
        cost=digest_total_cost,
        low_cost=_sum_costs([digest_low_cost, spec_cost]),
        output_tokens_low=digest_output_low,
        transport="batch" if batch else "real-time",
        note=f"one vision call per sheet; {read_low:,}–{read_high:,} output tokens/read, including thinking",
    ))
    if sheet_count >= 2:
        synth_input = digest_text + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        components.append(_component(
            "Synthesis", synth_input, _ASSUMED_SYNTHESIS_OUTPUT_TOKENS,
            model=stage_models.synthesis, batch=False,
            note="one text-only set overview", primary_model=model,
        ))
    if focus and sheet_count >= 1:
        focus_input = digest_text + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        components.append(_component(
            "Focus report", focus_input, _ASSUMED_FOCUS_OUTPUT_TOKENS,
            model=stage_models.focus, batch=False,
            note="one text-only focused summary", primary_model=model,
        ))

    # Phase A planning stages — one text-only real-time call each: the set
    # identity (disciplines/jurisdiction/adopted codes) and the model-authored
    # review plan the critique applies as its checklist.
    components.append(_component(
        "Set identity",
        _ASSUMED_IDENTITY_INPUT_TOKENS_BASE
        + sheet_count * _ASSUMED_IDENTITY_INPUT_TOKENS_PER_SHEET,
        _ASSUMED_IDENTITY_OUTPUT_TOKENS, model=identity_model, batch=False,
        note=f"one text call with {friendly_model_name(identity_model)} — "
             "disciplines/jurisdiction/adopted codes",
    ))
    components.append(_component(
        "Model review plan",
        _ASSUMED_PLAN_INPUT_TOKENS_BASE
        + sheet_count * _ASSUMED_PLAN_INPUT_TOKENS_PER_SHEET,
        _ASSUMED_PLAN_OUTPUT_TOKENS, model=stage_models.review_plan, batch=False,
        note="one text call — the authored review checklist",
        primary_model=model,
    ))

    # Critique — N adversarial reads per sheet. In a ``use_batch`` run they ride
    # one Message Batch referencing a single shared per-sheet upload (Phase 23C),
    # so they are batch-priced; otherwise real-time.
    #
    # WP-05 §10.2: the count comes from the runtime's own resolver, not a
    # hardcoded 2. ``DRAWING_ANALYZER_CRITIQUE_RUNS`` moves it, and a preview
    # that keeps quoting two reads while the run makes four understates the
    # single largest QC line by half.
    #
    # The images are priced with the CRITIQUE model, not the digest's.
    # ``estimate_image_tokens`` is capped per model — 4784 on a
    # hi-resolution model, 1568 on a standard-tier one — so reusing the digest's
    # count for a critique pointed at a standard-tier model is a ~3x error
    # (§2.4). Latent today, since Opus 5 and Sonnet 5 share the tier, and
    # reachable through one env var.
    from .critique import critique_runs

    runs = critique_runs()
    # A shared image prefix belongs to one sheet. Retain that sheet's geometry
    # because averaging prefixes can hide a long-context pricing threshold.
    crit_prefixes = [tokens + _ASSUMED_PROMPT_TOKENS_PER_SHEET for tokens in crit_image_requests]
    crit_in = runs * sum(crit_prefixes)
    crit_read_low, crit_read_high = _read_output_band(model=stage_models.critique, critique=True)
    crit_out = runs * sheet_count * crit_read_high
    def critique_cost(output_per_read: int, scenario: int) -> float | None:
        if not crit_prefixes:
            return estimate_request_cost(0, 0, model=stage_models.critique, batch=critique_batch)
        return _sum_costs([
            _critique_prefix_costs(
                prefix_tokens=prefix, output_tokens=output_per_read,
                sheet_count=1, runs=runs,
                model=stage_models.critique, batch=critique_batch,
            )[scenario]
            for prefix in crit_prefixes
        ])

    crit_low = critique_cost(crit_read_low, 0)
    crit_high = critique_cost(crit_read_high, 1)
    transport_note = (
        " — one shared upload, Batch rate" if critique_batch
        else (" — real-time, shared image prefix prompt-cached" if runs >= 2
              else " — real-time")
    )
    components.append(CostComponent(
        stage=f"Critique ×{runs} (per sheet)",
        input_tokens=crit_in, output_tokens=crit_out,
        # The representative row shows the pessimistic end, matching how
        # verification and citation are displayed; the band carries both.
        cost=crit_high,
        low_cost=crit_low,
        output_tokens_low=runs * sheet_count * crit_read_low,
        transport="batch" if critique_batch else "real-time",
        note=_stage_note(
            f"{runs} full read(s) per sheet{transport_note}; "
            f"{crit_read_low:,}–{crit_read_high:,} output tokens/read, including thinking",
            stage_model=stage_models.critique, primary=model,
        ),
    ))

    # Cross-sheet QC — one (or a few sharded) text passes over all the digests.
    if sheet_count >= 2:
        components.append(_cross_qc_component(sheet_count, digest_text, model=stage_models.cross_qc,
                                              primary_model=model))

    # Prose harvest — a small straggler-structuring allowance.
    components.append(_component(
        "Prose harvest", _ASSUMED_PROSE_STRAGGLER_INPUT_TOKENS,
        _ASSUMED_PROSE_STRAGGLER_OUTPUT_TOKENS, model=harvest_model, batch=False,
        note=f"occasional straggler structuring with "
             f"{friendly_model_name(harvest_model)}",
    ))

    # Verification & citation scale with volume — quoted as a low–high band below.
    def _verify(findings: float) -> CostComponent:
        n = max(0, round(findings))
        return _component(
            "Verification", n * _ASSUMED_VERIFY_INPUT_TOKENS_PER_FINDING,
            n * _ASSUMED_VERIFY_OUTPUT_TOKENS_PER_FINDING,
            model=verification_model, batch=False,
            request_inputs=[_ASSUMED_VERIFY_INPUT_TOKENS_PER_FINDING] * n,
            note=(f"~{n} finding(s) × one crop re-check with "
                  f"{friendly_model_name(verification_model)}"),
        )

    def _citation(refs: float) -> CostComponent:
        from .citation_check import citation_max_refs, citation_tools
        from .core.pricing import WEB_SEARCH_COST_PER_USE

        budget = citation_max_refs()
        n = min(max(0, round(refs)), budget)
        resolved_tools = {t["name"]: t for t in citation_tools(citation_model)}
        fetch_tokens = resolved_tools.get("web_fetch", {}).get("max_content_tokens", 0)
        searches = min(_ASSUMED_WEB_SEARCHES_PER_REF,
                       resolved_tools["web_search"]["max_uses"])
        search_cost = float(WEB_SEARCH_COST_PER_USE) * n * searches
        return _component(
            "Citation checks",
            n * (_ASSUMED_CITATION_INPUT_TOKENS_PER_REF + fetch_tokens),
            n * _ASSUMED_CITATION_OUTPUT_TOKENS_PER_REF,
            model=citation_model, batch=False,
            request_inputs=[_ASSUMED_CITATION_INPUT_TOKENS_PER_REF + fetch_tokens] * n,
            extra_cost=search_cost,
            note=(f"~{n} eligible normalized ref(s), per-run cap {budget}, "
                  f"~{searches} searches/ref"
                  + (f" + one clause fetch (≤{fetch_tokens:,} tokens)" if fetch_tokens else "")
                  + f" with {friendly_model_name(citation_model)}; "
                  "extra claim chunks/resumes can cost more"),
        )

    def _investigate(findings: float, *, high: bool) -> CostComponent:
        from .core.api_config import PHASE_INVESTIGATION, phase_output_cap

        # The stage's own per-run cap, which scales with the set — quoting a
        # flat 10 here under-stated a large set several-fold.
        from .investigate import investigation_max_findings, investigation_max_rounds

        n = min(max(0, round(findings * _UNCERTAIN_FINDINGS_FRACTION)),
                investigation_max_findings(sheet_count))
        evidence_rounds = investigation_max_rounds()
        if not high:
            evidence_rounds = min(evidence_rounds, _ASSUMED_INVESTIGATE_ROUNDS_LOW)
        # One initial/evidence call per request plus the forced closing verdict.
        calls = evidence_rounds + 1
        per_call_out = phase_output_cap(PHASE_INVESTIGATION, model=stage_models.investigation)
        if not high:
            per_call_out = min(per_call_out, _ASSUMED_INVESTIGATE_OUTPUT_TOKENS_PER_ROUND_LOW)
        per_call_inputs = [_ASSUMED_INVESTIGATE_INPUT_TOKENS_PER_ROUND] * calls
        if high:
            # The tool loop replays complete assistant content (thinking blocks
            # included) along with accumulated crops/tool results. Allow full
            # prior replies at the input rate; prompt-cache reuse can lower it.
            per_call_inputs = [
                tokens + index * (_ASSUMED_INVESTIGATE_EVIDENCE_TOKENS_PER_ROUND + per_call_out)
                for index, tokens in enumerate(per_call_inputs)
            ]
        # The escalation tier resolves through ``investigation_model()``, which
        # honours DRAWING_ANALYZER_INVESTIGATION_MODEL before falling back to
        # the escalation constant this used to read directly.
        return _component(
            "Investigation",
            n * sum(per_call_inputs),
            n * calls * per_call_out,
            model=stage_models.investigation, batch=False,
            request_inputs=per_call_inputs * n,
            note=f"~{n} uncertain finding(s) × up to {evidence_rounds} evidence requests "
                 f"+ closing verdict; thinking and history replay included, with "
                 f"{friendly_model_name(stage_models.investigation)}",
        )

    low_verify = _verify(sheet_count * _FINDINGS_PER_SHEET_LOW)
    high_verify = _verify(sheet_count * _FINDINGS_PER_SHEET_HIGH)
    low_citation = _citation(sheet_count * _REFS_PER_SHEET_LOW)
    high_citation = _citation(sheet_count * _REFS_PER_SHEET_HIGH)
    low_investigate = _investigate(sheet_count * _FINDINGS_PER_SHEET_LOW, high=False)
    high_investigate = _investigate(sheet_count * _FINDINGS_PER_SHEET_HIGH, high=True)

    # Sum each stage at its own band end once, including the volume variants.
    # Keep the per-stage low ends for a dialog whose rows add up to its totals.
    def _total(variants: list[CostComponent], *, low: bool = False) -> float | None:
        """Sum every component, or ``None`` if any one of them is unpriced.

        An unpriced component must make the whole total unavailable, not drop
        out of it. Dropping it publishes the sum of the *remaining* stages as if
        it were the run's cost — and the stage most likely to be unpriced is the
        one behind ``DRAWING_ANALYZER_CRITIQUE_MODEL``, which is both the
        advertised cost lever and the single largest component. Pointing that at
        a model this table does not know quoted ~$21 for a 40-sheet run whose
        critique line alone is ~$37, with nothing in the output to say the
        figure was partial.

        This matches ``estimate_drawing_set_cost`` above and
        ``RunUsage.total_estimated_cost``: an unknown price means "no dollar
        figure", never "a smaller dollar figure".
        """
        return _sum_costs([
            c.low_cost if low and c.low_cost is not None else c.cost
            for c in components + variants
        ])

    low_cost = _total([low_verify, low_investigate, low_citation], low=True)
    high_cost = _total([high_verify, high_investigate, high_citation])
    components += [replace(hi, low_cost=lo.cost, input_tokens_low=lo.input_tokens,
                           output_tokens_low=lo.output_tokens)
                   for lo, hi in ((low_verify, high_verify), (low_investigate, high_investigate),
                                  (low_citation, high_citation))]
    return ExhaustiveCostEstimate(
        sheet_count=sheet_count, file_count=file_count, model=model,
        components=components, low_cost=low_cost, high_cost=high_cost,
        batch=batch, critique_batch=critique_batch, spec_chars=spec_chars,
        critique_runs=runs,
        shape_aware=shape_aware,
        unmeasured_pages=unmeasured,
        stage_models=stage_models,
    )


def format_exhaustive_cost_prompt(est: ExhaustiveCostEstimate) -> str:
    """Human-readable confirmation for an exhaustive QC run (§15.7)."""
    where = f" from {est.file_count} file(s)" if est.file_count else ""
    # Name every model the run will touch, not just the review model. Stages do
    # not all share one model (verification and the report chat sit on Sonnet,
    # the prose harvest on Haiku), so a single-model sentence here misattributed
    # work the per-stage rows below already price correctly.
    if est.stage_models is not None:
        used = [friendly_model_name(m) for m in est.stage_models.distinct]
    else:
        used = [friendly_model_name(est.model)]
    if len(used) == 1:
        with_models = used[0]
    else:
        with_models = f"{', '.join(used[:-1])} and {used[-1]} (per stage, below)"
    lines = [
        f"About to run the FULL exhaustive QC review on {est.sheet_count} sheet(s)"
        f"{where} with {with_models} — digest, set identity + "
        f"model review plan, {est.critique_runs} critique read(s) per sheet, "
        "cross-sheet QC, "
        "deterministic auditors, prose harvest, verification, the uncertain-"
        "finding investigation loop, and citation checks.",
        "",
        _basis_line(est.shape_aware, est.unmeasured_pages),
        _OUTPUT_BAND_NOTE,
        f"Finding volume assumes {_FINDINGS_PER_SHEET_LOW:g}–{_FINDINGS_PER_SHEET_HIGH:g} "
        "findings per sheet, allowing for critique, cross-QC and auditors beyond "
        "the recorded standard run's 287 findings on 39 sheets (~7.4 per sheet).",
        "",
        "Estimated cost by stage:",
    ]
    if est.spec_chars:
        # Same §9.2 correction as the standard dialog, and it matters more here:
        # this run is longer, so an operator reading "cached" budgets for one
        # copy of the specs and is billed for one per sheet.
        lines.append(
            f"  (Digest includes ~{est.spec_chars:,} chars of uploaded project "
            + ("specifications, billed as ordinary batch input on every sheet.)"
               if est.batch else
               "specifications, usually cached after the first sheet(s); sheets "
               "in flight before the cache is readable pay the write rate.)")
        )
    for c in est.components:
        money = (f"${c.low_cost:,.2f}–${c.cost:,.2f}"
                 if c.cost is not None and c.low_cost is not None and c.low_cost != c.cost
                 else f"~${c.cost:,.2f}" if c.cost is not None else "n/a")
        lines.append(f"  • {c.stage}: {money} ({c.transport}) — {c.note}")
    if est.low_cost is not None and est.high_cost is not None:
        lines += [
            "",
            f"Estimated total: ${est.low_cost:,.2f} – ${est.high_cost:,.2f} — a rough "
            "range, not a cap on spending (output includes thinking; "
            "verification scales with finding count; "
            "citation refs are capped but extra claim chunks/resumes can cost more, "
            "and the text riding with each "
            "sheet is not bounded by the image "
            + ("figure" if est.shape_aware else "allowance")
            + "). Pricing verified "
            f"{est.verified_effective_date}. Every stage caches separately, so a "
            "re-run is cheaper but rarely free: a digest hit does not imply a "
            "hit on the stages below, and identity, the review plan, synthesis "
            "and cross-sheet QC key on the whole set — adding or changing one "
            "sheet re-runs each of them in full.",
        ]
    else:
        # Name the stages whose model this table cannot price. The old wording
        # ("unavailable for this model") pointed at the review model even when
        # the unpriced stage was one an env var had redirected elsewhere, which
        # sent the reader looking in the wrong place.
        unpriced = [c.stage for c in est.components if c.cost is None]
        which = f" ({', '.join(unpriced)})" if unpriced else ""
        lines += [
            "",
            f"Estimated total: unavailable — no published price for the model "
            f"behind {'these stages' if len(unpriced) > 1 else 'this stage'}"
            f"{which}. The per-stage rows above still show the token scale.",
        ]
    if est.batch and est.critique_batch:
        lines += [
            "",
            "Economy mode: digest and critique reads go into Anthropic's shared "
            "queue and are processed "
            "when they reach the front — often a few hours, sometimes overnight "
            "(8+ hours). Cheapest option; best left running when you're not in a rush.",
            _batch_wait_sentence(),
        ]
    elif not est.batch and est.critique_batch:
        lines += [
            "",
            "Hybrid mode: digest reads run immediately; the two exhaustive-QC "
            "critique reads use the half-rate shared queue and can still take hours.",
        ]
    elif est.batch and not est.critique_batch:
        lines += [
            "",
            "Custom transport: digest reads use the Batch queue; critique reads run "
            "at the full real-time rate after the digest batch completes.",
        ]
    else:
        lines += [
            "",
            "Fast mode: no queue — expect roughly 4–6 minutes per sheet, at the "
            "full (un-discounted) API rate. Choose this when you need results now.",
        ]
    lines += ["", "Proceed with the exhaustive review?"]
    return "\n".join(lines)
