"""Pre-run cost estimate for a drawing set (feeds the cost-confirm dialog).

Reading drawings is the app's most expensive action — one Opus 4.8 vision call
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

from .core.api_config import REVIEW_MODEL_DEFAULT
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
) -> DrawingCostEstimate:
    """Estimate the cost of digesting ``sheet_count`` sheets.

    ``synthesize`` mirrors the run: when on (and ≥2 sheets) it adds the
    text-only cross-sheet pass, whose input is roughly the per-sheet digests fed
    back in. Image tokens are folded into ``input_tokens`` (vision is billed as
    input). ``batch=True`` applies the 50% Message Batches discount to the
    per-sheet digest spend (the dominant cost); the synthesis pass runs
    synchronously, but folding it in at the batch rate too keeps the estimate
    deliberately slightly-high rather than under-stated. ``focus`` mirrors a
    per-run focus: each sheet's digest grows by a focus-findings section, and
    one more text-only pass (the focus report) re-reads the digests.
    """
    image_tokens = estimate_image_tokens_for_set(
        sheet_count, rows=rows, cols=cols, model=model
    )
    digest_output = sheet_count * _ASSUMED_OUTPUT_TOKENS_PER_SHEET
    if focus:
        digest_output += sheet_count * _ASSUMED_FOCUS_SECTION_TOKENS_PER_SHEET
    input_tokens = image_tokens + sheet_count * _ASSUMED_PROMPT_TOKENS_PER_SHEET
    output_tokens = digest_output

    if synthesize and sheet_count >= 2:
        # Synthesis re-reads the per-sheet digests (≈ digest_output) as text.
        input_tokens += digest_output + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        output_tokens += _ASSUMED_SYNTHESIS_OUTPUT_TOKENS

    if focus and sheet_count >= 1:
        # The focus report likewise re-reads the per-sheet digests as text.
        input_tokens += digest_output + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        output_tokens += _ASSUMED_FOCUS_OUTPUT_TOKENS

    total_cost = estimate_request_cost(
        input_tokens, output_tokens, model=model, batch=batch
    )
    return DrawingCostEstimate(
        sheet_count=sheet_count,
        file_count=file_count,
        model=model,
        image_tokens=image_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_cost=total_cost,
        batch=batch,
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
    if est.total_cost is not None:
        batch_note = " (Batch rate)" if est.batch else ""
        lines.append(
            f"Estimated cost: ~${est.total_cost:,.2f}{batch_note} — a rough, "
            "slightly-high estimate; actual cost varies with sheet complexity, "
            "and cached sheets cost nothing."
        )
    else:
        lines.append("Estimated cost: unavailable for this model.")
    if est.batch:
        lines += [
            "",
            "Nothing is sent until you confirm. The batch runs in the "
            "background — usually a few minutes, but it can take up to an hour "
            "(occasionally longer) before the digest is ready to attach.",
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

# Per-read critique output; each read re-renders the sheet (its input ≈ the digest
# images again) — the dominant critique cost.
_ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ = 1_500
_ASSUMED_CROSS_QC_OUTPUT_TOKENS = 2_000
_ASSUMED_PROSE_STRAGGLER_INPUT_TOKENS = 1_500     # one small structuring allowance
_ASSUMED_PROSE_STRAGGLER_OUTPUT_TOKENS = 500
_ASSUMED_VERIFY_INPUT_TOKENS_PER_FINDING = 1_500  # a high-DPI crop + prompt
_ASSUMED_VERIFY_OUTPUT_TOKENS_PER_FINDING = 150
_ASSUMED_CITATION_INPUT_TOKENS_PER_CLAIM = 2_000  # web-search prompt + tool results
_ASSUMED_CITATION_OUTPUT_TOKENS_PER_CLAIM = 400
_ASSUMED_WEB_SEARCHES_PER_CLAIM = 2
# Finding / unique-claim counts are unknown pre-run — a per-sheet low–high band.
_FINDINGS_PER_SHEET_LOW = 0.5
_FINDINGS_PER_SHEET_HIGH = 3.0
_CLAIMS_PER_SHEET_LOW = 0.1
_CLAIMS_PER_SHEET_HIGH = 1.0


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
    verified_effective_date: str = PRICING_EFFECTIVE_DATE


def _component(
    stage: str, input_tokens: int, output_tokens: int, *, model: str, batch: bool,
    extra_cost: float = 0.0, note: str = "",
) -> CostComponent:
    base = estimate_request_cost(input_tokens, output_tokens, model=model, batch=batch)
    cost = None if base is None else base + extra_cost
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
    focus: bool = False,
) -> ExhaustiveCostEstimate:
    """Estimate an **exhaustive QC** run's cost, component by component (§15.7).

    The digest (and synthesis / focus) ride the Batch path when ``batch`` is set;
    critique, cross-QC, verification, and citation run real-time (until Phase 23C
    routes critique through Batches). Verification and citation are quoted as a
    low–high band because their volume tracks the finding / unique-claim count.
    A component whose model price is unknown contributes ``None`` and drops out of
    the numeric total (the caller shows scale without a dollar figure).
    """
    per_sheet_images = estimate_image_tokens_for_set(1, rows=rows, cols=cols, model=model)
    components: list[CostComponent] = []

    # Digest (+ synthesis + focus) — the existing digest-path estimate, batch-priced.
    digest_est = estimate_drawing_set_cost(
        sheet_count, file_count=file_count, model=model, rows=rows, cols=cols,
        synthesize=True, batch=batch, focus=focus,
    )
    components.append(CostComponent(
        stage="Digest + synthesis" + (" + focus" if focus else ""),
        input_tokens=digest_est.input_tokens, output_tokens=digest_est.output_tokens,
        cost=digest_est.total_cost, transport="batch" if batch else "real-time",
        note="one vision call per sheet" + (" + text passes" if sheet_count >= 2 else ""),
    ))

    # Critique — two adversarial reads per sheet, each re-rendering the sheet.
    crit_in = 2 * sheet_count * (per_sheet_images + _ASSUMED_PROMPT_TOKENS_PER_SHEET)
    crit_out = 2 * sheet_count * _ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ
    components.append(_component(
        "Critique ×2 (per sheet)", crit_in, crit_out, model=model, batch=False,
        note="two full re-reads per sheet — real-time",
    ))

    # Cross-sheet QC — one (or a few sharded) text passes over all the digests.
    if sheet_count >= 2:
        cross_in = sheet_count * _ASSUMED_OUTPUT_TOKENS_PER_SHEET + _ASSUMED_PROMPT_TOKENS_PER_SHEET
        components.append(_component(
            "Cross-sheet QC", cross_in, _ASSUMED_CROSS_QC_OUTPUT_TOKENS,
            model=model, batch=False, note="text-only whole-set pass",
        ))

    # Prose harvest — a small straggler-structuring allowance.
    components.append(_component(
        "Prose harvest", _ASSUMED_PROSE_STRAGGLER_INPUT_TOKENS,
        _ASSUMED_PROSE_STRAGGLER_OUTPUT_TOKENS, model=model, batch=False,
        note="occasional straggler structuring",
    ))

    # Verification & citation scale with volume — quoted as a low–high band below.
    def _verify(findings: float) -> CostComponent:
        n = max(0, round(findings))
        return _component(
            "Verification", n * _ASSUMED_VERIFY_INPUT_TOKENS_PER_FINDING,
            n * _ASSUMED_VERIFY_OUTPUT_TOKENS_PER_FINDING, model=model, batch=False,
            note=f"~{n} finding(s) × one crop re-check",
        )

    def _citation(claims: float) -> CostComponent:
        n = max(0, round(claims))
        from .core.pricing import WEB_SEARCH_COST_PER_USE
        search_cost = float(WEB_SEARCH_COST_PER_USE) * n * _ASSUMED_WEB_SEARCHES_PER_CLAIM
        return _component(
            "Citation checks", n * _ASSUMED_CITATION_INPUT_TOKENS_PER_CLAIM,
            n * _ASSUMED_CITATION_OUTPUT_TOKENS_PER_CLAIM, model=model, batch=False,
            extra_cost=search_cost, note=f"~{n} unique claim(s) × web search",
        )

    low_verify = _verify(sheet_count * _FINDINGS_PER_SHEET_LOW)
    high_verify = _verify(sheet_count * _FINDINGS_PER_SHEET_HIGH)
    low_citation = _citation(sheet_count * _CLAIMS_PER_SHEET_LOW)
    high_citation = _citation(sheet_count * _CLAIMS_PER_SHEET_HIGH)

    # ``components`` (for display) so far holds the fixed stages; the high band is
    # shown as the representative verification/citation rows. The low/high totals
    # sum the *fixed* stages once and swap in the low vs high volume variants — so
    # the band is exactly the finding/citation-count spread and low_cost <= high_cost.
    def _total(variants: list[CostComponent]) -> float | None:
        known = [c.cost for c in components + variants if c.cost is not None]
        return sum(known) if known else None

    low_cost = _total([low_verify, low_citation])
    high_cost = _total([high_verify, high_citation])
    components = components + [high_verify, high_citation]
    return ExhaustiveCostEstimate(
        sheet_count=sheet_count, file_count=file_count, model=model,
        components=components, low_cost=low_cost, high_cost=high_cost,
    )


def format_exhaustive_cost_prompt(est: ExhaustiveCostEstimate) -> str:
    """Human-readable confirmation for an exhaustive QC run (§15.7)."""
    where = f" from {est.file_count} file(s)" if est.file_count else ""
    lines = [
        f"About to run the FULL exhaustive QC review on {est.sheet_count} sheet(s)"
        f"{where} with {friendly_model_name(est.model)} — digest, two critique reads "
        "per sheet, cross-sheet QC, deterministic auditors, prose harvest, "
        "verification, and citation checks.",
        "",
        "Estimated cost by stage:",
    ]
    for c in est.components:
        money = f"~${c.cost:,.2f}" if c.cost is not None else "n/a"
        lines.append(f"  • {c.stage}: {money} ({c.transport}) — {c.note}")
    if est.low_cost is not None and est.high_cost is not None:
        lines += [
            "",
            f"Estimated total: ${est.low_cost:,.2f} – ${est.high_cost:,.2f} — a rough "
            "range (verification and citation scale with how many findings and code "
            f"citations turn up). Pricing verified {est.verified_effective_date}; "
            "cached sheets cost nothing.",
        ]
    else:
        lines += ["", "Estimated total: unavailable for this model."]
    lines += ["", "Proceed with the exhaustive review?"]
    return "\n".join(lines)
