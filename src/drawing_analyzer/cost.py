"""Pre-run cost estimate for a drawing set (feeds the cost-confirm dialog).

Reading drawings is the app's most expensive action — one Opus 5 vision call
per sheet, each carrying the overview image plus every grid tile. This estimates
the spend *before* the run so the GUI can surface it and let the operator
confirm or cancel. It is deliberately a rough, slightly-high estimate (the image
-token figure is the per-model worst case, and per-sheet output/prompt sizes are
fixed assumptions) — the goal is an honest order-of-magnitude heads-up, not an
invoice. Pure + hermetic (no PyMuPDF, no network): the caller supplies the sheet
count (cheap to obtain via ``render.list_sheets``).
"""
from __future__ import annotations

from dataclasses import dataclass
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
)
from . import tiling
from .pipeline import estimate_image_tokens_for_set

# Per-sheet text overhead of the digest prompt (system + user instruction); the
# images dominate, so a fixed estimate is fine.
_ASSUMED_PROMPT_TOKENS_PER_SHEET = 800
# Typical structured digest output per sheet — well under the 16k cap; real
# digests rarely approach it, so using the cap would wildly overstate cost.
_ASSUMED_OUTPUT_TOKENS_PER_SHEET = 2_000
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


def _specs_cost_contribution(
    spec_chars: int, sheet_count: int, *, model: str, batch: bool,
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
      less, so it's a genuine (if usually small) understatement rather than
      the "slightly high" bias the rest of this module aims for.
    """
    if spec_chars <= 0 or sheet_count <= 0:
        return 0, 0.0
    from .core.pricing import usage_record_cost

    spec_tokens = max(1, spec_chars // _SPEC_CHARS_PER_TOKEN_ESTIMATE)
    display_tokens = spec_tokens * sheet_count
    if batch:
        cost = usage_record_cost(model=model, input_tokens=display_tokens, batch=True)
        return display_tokens, None if cost is None else float(cost)
    write_cost = usage_record_cost(model=model, cache_write_tokens=spec_tokens, batch=False)
    read_cost = usage_record_cost(model=model, cache_read_tokens=spec_tokens, batch=False)
    if write_cost is None or read_cost is None:
        return display_tokens, None
    total = float(write_cost) + float(read_cost) * max(0, sheet_count - 1)
    return display_tokens, total


@dataclass(frozen=True)
class ImageTokenEstimate:
    """A geometry-aware image-token estimate, with the assumptions it rests on.

    ``tokens`` is the planning number. ``conservative_tokens`` is what the legacy
    allowance (:func:`pipeline.estimate_image_tokens_for_set`) would have quoted
    for the same pages, kept beside it so a caller can show both and a test can
    assert the direction of the correction rather than a magic constant.
    """

    tokens: int
    conservative_tokens: int
    #: Pages counted by how their render target was decided.
    vector_pages: int = 0
    raster_pages: int = 0
    #: Pages that could not be classified, or could not be measured, and were
    #: therefore priced at the conservative allowance. Never dropped, never
    #: quietly treated as vector.
    unknown_pages: int = 0
    unmeasured_pages: int = 0

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
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    overlap_frac: float = tiling.DEFAULT_OVERLAP_FRAC,
    model: str = REVIEW_MODEL_DEFAULT,
) -> ImageTokenEstimate:
    """Image tokens for one vision read of these pages, from their real shapes.

    WP-05 §10.1. The shipped allowance
    (:func:`pipeline.estimate_image_tokens_for_set`) assumes every image is a
    square at the *raster* target and lands at the model's token cap — a true
    upper bound, and about 1.9x the actual cost of a vector E-size sheet (§2.6).
    Two facts per page close most of that gap, and both come from a scan that
    never rasterizes: the aspect ratio, and whether the page has words.

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

    A page classified ``unknown``, or one that could not be measured, falls back
    to the conservative per-sheet allowance and is counted separately. It is
    never assumed vector: vector is the *cheaper* target, so guessing it would
    quote low on precisely the pages least understood.
    """
    from .pipeline import estimate_image_tokens_for_set

    conservative_per_sheet = estimate_image_tokens_for_set(
        1, rows=rows, cols=cols, model=model
    )
    total = 0
    vector = raster = unknown = unmeasured = 0
    for basis in bases or []:
        classification = str(getattr(basis, "classification", "") or "")
        width = float(getattr(basis, "width_pt", 0.0) or 0.0)
        height = float(getattr(basis, "height_pt", 0.0) or 0.0)
        measurable = (
            bool(getattr(basis, "geometry_ok", False)) and width > 0 and height > 0
        )
        if not measurable:
            unmeasured += 1
        if not measurable or classification not in (
            CLASSIFICATION_VECTOR, CLASSIFICATION_RASTER
        ):
            unknown += 1
            total += conservative_per_sheet
            continue
        if classification == CLASSIFICATION_RASTER:
            raster += 1
        else:
            vector += 1
        sizes = tiling.image_pixel_sizes(
            width, height, rows=rows, cols=cols, overlap_frac=overlap_frac,
            is_raster=classification == CLASSIFICATION_RASTER,
        )
        total += estimate_image_tokens_total(sizes, model=model)
    return ImageTokenEstimate(
        tokens=total,
        conservative_tokens=conservative_per_sheet * (vector + raster + unknown),
        vector_pages=vector,
        raster_pages=raster,
        unknown_pages=unknown,
        unmeasured_pages=unmeasured,
    )


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


def estimate_drawing_set_cost(
    sheet_count: int,
    *,
    file_count: int = 0,
    model: str = REVIEW_MODEL_DEFAULT,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    synthesize: bool = True,
    batch: bool = False,
    focus: bool = False,
    spec_chars: int = 0,
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
    none) is priced separately at the cache-aware rate (see
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
    image_tokens = estimate_image_tokens_for_set(
        sheet_count, rows=rows, cols=cols, model=model
    )
    digest_output = sheet_count * _ASSUMED_OUTPUT_TOKENS_PER_SHEET
    if focus:
        digest_output += sheet_count * _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET
    digest_input = image_tokens + sheet_count * _ASSUMED_PROMPT_TOKENS_PER_SHEET
    input_tokens = digest_input
    output_tokens = digest_output
    stage_costs: list[float | None] = [
        estimate_request_cost(
            digest_input, digest_output, model=model, batch=batch
        )
    ]

    if synthesize and sheet_count >= 2:
        # Synthesis re-reads the per-sheet digests (≈ digest_output) as text.
        synth_input = digest_output + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        input_tokens += synth_input
        output_tokens += _ASSUMED_SYNTHESIS_OUTPUT_TOKENS
        stage_costs.append(estimate_request_cost(
            synth_input, _ASSUMED_SYNTHESIS_OUTPUT_TOKENS,
            model=stage_models.synthesis, batch=False,
        ))

    if focus and sheet_count >= 1:
        # The focus report likewise re-reads the per-sheet digests as text.
        focus_input = digest_output + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        input_tokens += focus_input
        output_tokens += _ASSUMED_FOCUS_OUTPUT_TOKENS
        stage_costs.append(estimate_request_cost(
            focus_input, _ASSUMED_FOCUS_OUTPUT_TOKENS,
            model=stage_models.focus, batch=False,
        ))

    total_cost = None if any(c is None for c in stage_costs) else sum(
        c for c in stage_costs if c is not None
    )
    spec_display_tokens, spec_cost = _specs_cost_contribution(
        spec_chars, sheet_count, model=model, batch=batch
    )
    # ``spec_cost`` is 0.0 (never None) whenever spec_chars <= 0 (see
    # _specs_cost_contribution's early return), so this is a no-op add in
    # that case. Propagates an unknown-priced model's ``None`` from either
    # side, rather than coercing it into a bogus, spec-cost-only total.
    total_cost = None if total_cost is None or spec_cost is None else total_cost + spec_cost
    input_tokens += spec_display_tokens
    return DrawingCostEstimate(
        sheet_count=sheet_count,
        file_count=file_count,
        model=model,
        image_tokens=image_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        batch=batch,
        spec_chars=spec_chars,
    )


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
        f"(~{est.image_tokens:,} from images) / ~{est.output_tokens:,} output.",
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
            f"Estimated cost: ~${est.total_cost:,.2f}{batch_note} — a rough "
            "estimate, not a cap. The image allowance is a per-model worst "
            "case, but the text riding with each sheet is not bounded by it, so "
            "a text-heavy set can land above this figure. Every stage caches "
            "separately: a sheet already in the local result cache skips its "
            "own call, but that does not mean the set-level passes are free — "
            "and because they key on the whole set, adding or changing one "
            "sheet re-runs them in full."
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
# per paid QC stage and a total **range** — verification and citation scale with
# the finding / unique-claim count, which isn't known until the digests complete,
# so they are quoted as a per-sheet low–high band rather than a single number.

# Per-read critique output. Each of the two reads bills the sheet's image input
# again (its input ≈ the digest images) — but in a ``use_batch`` run both reads
# ride one Message Batch referencing a single shared upload (Phase 23C), so the
# rate is halved and the sheet is uploaded once, not re-rendered per read.
_ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ = 1_500
_ASSUMED_CROSS_QC_OUTPUT_TOKENS = 2_000
_ASSUMED_PROSE_STRAGGLER_INPUT_TOKENS = 1_500     # one small structuring allowance
_ASSUMED_PROSE_STRAGGLER_OUTPUT_TOKENS = 500
_ASSUMED_VERIFY_INPUT_TOKENS_PER_FINDING = 1_500  # a high-DPI crop + prompt
# The verdict itself is ~150 tokens, but verification now runs adaptive thinking
# at medium effort and thinking bills at the OUTPUT rate — so an estimate built
# on the visible answer alone under-states this stage several-fold.
_ASSUMED_VERIFY_OUTPUT_TOKENS_PER_FINDING = 1_400
_ASSUMED_CITATION_INPUT_TOKENS_PER_CLAIM = 2_000  # web-search prompt + tool results
# The citation check can now open a cited section with web_fetch, not just read
# search snippets. Fetched page text lands in the request as ordinary input
# tokens (web_fetch itself carries no per-use surcharge), and a code-publisher
# page is large — so the input side is no longer dominated by the prompt. An
# allowance for roughly one fetched page per claim; the tool's own
# max_content_tokens caps the worst case well above this.
_ASSUMED_CITATION_FETCH_TOKENS_PER_CLAIM = 8_000
_ASSUMED_CITATION_OUTPUT_TOKENS_PER_CLAIM = 400
_ASSUMED_WEB_SEARCHES_PER_CLAIM = 2
# Phase A planning stages — one text-only call each. Identity reads a budgeted
# corpus (digest heads + early text layers, scaling gently with the set);
# the planner reads the identity + per-sheet digest heads.
_ASSUMED_IDENTITY_INPUT_TOKENS_BASE = 2_000
_ASSUMED_IDENTITY_INPUT_TOKENS_PER_SHEET = 400
_ASSUMED_IDENTITY_OUTPUT_TOKENS = 1_200
_ASSUMED_PLAN_INPUT_TOKENS_BASE = 2_000
_ASSUMED_PLAN_INPUT_TOKENS_PER_SHEET = 250
_ASSUMED_PLAN_OUTPUT_TOKENS = 2_500
# Finding / unique-claim counts are unknown pre-run — a per-sheet low–high band.
_FINDINGS_PER_SHEET_LOW = 0.5
_FINDINGS_PER_SHEET_HIGH = 3.0
_CLAIMS_PER_SHEET_LOW = 0.1
_CLAIMS_PER_SHEET_HIGH = 1.0
# Phase C investigation — a multi-turn escalation of the findings that stay
# UNCERTAIN after verification, on the (Opus) escalation model. Each turn
# re-sends the conversation, so the per-round input allowance dominates
# (history replay + one new crop per turn). Capped at the per-run default
# budget — the cap the stage itself enforces, which scales with the set.
_UNCERTAIN_FINDINGS_FRACTION = 0.2
_ASSUMED_INVESTIGATE_ROUNDS = 3
_ASSUMED_INVESTIGATE_INPUT_TOKENS_PER_ROUND = 6_000
_ASSUMED_INVESTIGATE_OUTPUT_TOKENS_PER_ROUND = 300


@dataclass(frozen=True)
class CostComponent:
    """One paid stage's contribution to the exhaustive-run estimate."""

    stage: str
    input_tokens: int
    output_tokens: int
    cost: float | None       # None when the model's price is unknown
    transport: str           # "batch" | "real-time"
    note: str = ""


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
) -> CostComponent:
    base = estimate_request_cost(input_tokens, output_tokens, model=model, batch=batch)
    cost = None if base is None else base + extra_cost
    if primary_model is not None:
        note = _stage_note(note, stage_model=model, primary=primary_model)
    return CostComponent(
        stage=stage, input_tokens=input_tokens, output_tokens=output_tokens,
        cost=cost, transport="batch" if batch else "real-time", note=note,
    )


def estimate_exhaustive_run_cost(
    sheet_count: int,
    *,
    file_count: int = 0,
    model: str = REVIEW_MODEL_DEFAULT,
    rows: int = tiling.DEFAULT_GRID_ROWS,
    cols: int = tiling.DEFAULT_GRID_COLS,
    batch: bool = True,
    critique_batch: bool | None = None,
    focus: bool = False,
    spec_chars: int = 0,
    verification_model: str | None = None,
) -> ExhaustiveCostEstimate:
    """Estimate an **exhaustive QC** run's cost, component by component (§15.7).

    ``batch`` selects digest transport. ``critique_batch`` independently selects
    the two critique reads and defaults to ``batch`` for legacy callers. This
    prices Economy (both batch), Hybrid (real-time digest/batch critique), and
    Fast (both real-time) without changing any model or review contract.
    Synthesis, focus, cross-QC,
    verification, and citation still run real-time. Verification and citation
    are quoted as a low–high band because their volume tracks the finding /
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

    per_sheet_images = estimate_image_tokens_for_set(1, rows=rows, cols=cols, model=model)
    components: list[CostComponent] = []

    # Digest vision calls use the selected transport. The later synthesis and
    # focus report are synchronous calls even when digest/critique use Batch, so
    # show and price them independently rather than discounting them by mistake.
    digest_input = sheet_count * per_sheet_images + (
        sheet_count * _ASSUMED_PROMPT_TOKENS_PER_SHEET
    )
    digest_output = sheet_count * _ASSUMED_OUTPUT_TOKENS_PER_SHEET
    if focus:
        digest_output += sheet_count * _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET
    spec_display_tokens, spec_cost = _specs_cost_contribution(
        spec_chars, sheet_count, model=model, batch=batch,
    )
    digest_cost = estimate_request_cost(
        digest_input, digest_output, model=model, batch=batch,
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
        transport="batch" if batch else "real-time",
        note="one vision call per sheet",
    ))
    if sheet_count >= 2:
        synth_input = digest_output + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        components.append(_component(
            "Synthesis", synth_input, _ASSUMED_SYNTHESIS_OUTPUT_TOKENS,
            model=stage_models.synthesis, batch=False,
            note="one text-only set overview", primary_model=model,
        ))
    if focus and sheet_count >= 1:
        focus_input = digest_output + _ASSUMED_PROMPT_TOKENS_PER_SHEET
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
    # ``estimate_image_tokens`` clamps at a per-model cap — 4784 on a
    # hi-resolution model, 1568 on a standard-tier one — so reusing the digest's
    # count for a critique pointed at a standard-tier model is a ~3x error
    # (§2.4). Latent today, since Opus 5 and Sonnet 5 share the tier, and
    # reachable through one env var.
    from .critique import critique_runs

    runs = critique_runs()
    crit_per_sheet_images = estimate_image_tokens_for_set(
        1, rows=rows, cols=cols, model=stage_models.critique
    )
    crit_in = runs * sheet_count * (
        crit_per_sheet_images + _ASSUMED_PROMPT_TOKENS_PER_SHEET
    )
    crit_out = runs * sheet_count * _ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ
    components.append(_component(
        f"Critique ×{runs} (per sheet)", crit_in, crit_out,
        model=stage_models.critique, batch=critique_batch,
        note=f"{runs} full read(s) per sheet"
        + (" — one shared upload, Batch rate" if critique_batch else " — real-time"),
        primary_model=model,
    ))

    # Cross-sheet QC — one (or a few sharded) text passes over all the digests.
    if sheet_count >= 2:
        cross_in = sheet_count * _ASSUMED_OUTPUT_TOKENS_PER_SHEET + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        components.append(_component(
            "Cross-sheet QC", cross_in, _ASSUMED_CROSS_QC_OUTPUT_TOKENS,
            model=stage_models.cross_qc, batch=False,
            note="text-only whole-set pass", primary_model=model,
        ))

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
            note=(f"~{n} finding(s) × one crop re-check with "
                  f"{friendly_model_name(verification_model)}"),
        )

    def _citation(claims: float) -> CostComponent:
        n = max(0, round(claims))
        from .core.pricing import WEB_SEARCH_COST_PER_USE
        search_cost = float(WEB_SEARCH_COST_PER_USE) * n * _ASSUMED_WEB_SEARCHES_PER_CLAIM
        return _component(
            "Citation checks",
            n * (_ASSUMED_CITATION_INPUT_TOKENS_PER_CLAIM
                 + _ASSUMED_CITATION_FETCH_TOKENS_PER_CLAIM),
            n * _ASSUMED_CITATION_OUTPUT_TOKENS_PER_CLAIM,
            model=citation_model, batch=False,
            extra_cost=search_cost,
            note=(f"~{n} unique claim(s) × web search + page fetch with "
                  f"{friendly_model_name(citation_model)}"),
        )

    def _investigate(findings: float) -> CostComponent:
        from .core.api_config import VERIFICATION_ESCALATION_MODEL

        # The stage's own per-run cap, which scales with the set — quoting a
        # flat 10 here under-stated a large set several-fold.
        from .investigate import investigation_max_findings

        n = min(max(0, round(findings * _UNCERTAIN_FINDINGS_FRACTION)),
                investigation_max_findings(sheet_count))
        rounds = n * _ASSUMED_INVESTIGATE_ROUNDS
        # The escalation tier resolves through ``investigation_model()``, which
        # honours DRAWING_ANALYZER_INVESTIGATION_MODEL before falling back to
        # the escalation constant this used to read directly.
        return _component(
            "Investigation",
            rounds * _ASSUMED_INVESTIGATE_INPUT_TOKENS_PER_ROUND,
            rounds * _ASSUMED_INVESTIGATE_OUTPUT_TOKENS_PER_ROUND,
            model=stage_models.investigation, batch=False,
            note=f"~{n} uncertain finding(s) × ~{_ASSUMED_INVESTIGATE_ROUNDS}-turn "
                 f"evidence loop with "
                 f"{friendly_model_name(stage_models.investigation)}",
        )

    low_verify = _verify(sheet_count * _FINDINGS_PER_SHEET_LOW)
    high_verify = _verify(sheet_count * _FINDINGS_PER_SHEET_HIGH)
    low_citation = _citation(sheet_count * _CLAIMS_PER_SHEET_LOW)
    high_citation = _citation(sheet_count * _CLAIMS_PER_SHEET_HIGH)
    low_investigate = _investigate(sheet_count * _FINDINGS_PER_SHEET_LOW)
    high_investigate = _investigate(sheet_count * _FINDINGS_PER_SHEET_HIGH)

    # ``components`` (for display) so far holds the fixed stages; the high band is
    # shown as the representative verification/citation rows. The low/high totals
    # sum the *fixed* stages once and swap in the low vs high volume variants — so
    # the band is exactly the finding/citation-count spread and low_cost <= high_cost.
    def _total(variants: list[CostComponent]) -> float | None:
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
        priced = [c.cost for c in components + variants]
        return None if any(c is None for c in priced) else sum(priced)

    low_cost = _total([low_verify, low_investigate, low_citation])
    high_cost = _total([high_verify, high_investigate, high_citation])
    components = components + [high_verify, high_investigate, high_citation]
    return ExhaustiveCostEstimate(
        sheet_count=sheet_count, file_count=file_count, model=model,
        components=components, low_cost=low_cost, high_cost=high_cost,
        batch=batch, critique_batch=critique_batch, spec_chars=spec_chars,
        critique_runs=runs,
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
        "model review plan, two critique reads per sheet, cross-sheet QC, "
        "deterministic auditors, prose harvest, verification, the uncertain-"
        "finding investigation loop, and citation checks.",
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
        money = f"~${c.cost:,.2f}" if c.cost is not None else "n/a"
        lines.append(f"  • {c.stage}: {money} ({c.transport}) — {c.note}")
    if est.low_cost is not None and est.high_cost is not None:
        lines += [
            "",
            f"Estimated total: ${est.low_cost:,.2f} – ${est.high_cost:,.2f} — a rough "
            "range, not a cap (verification and citation scale with how many "
            "findings and code citations turn up, and the text riding with each "
            "sheet is not bounded by the image allowance). Pricing verified "
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
