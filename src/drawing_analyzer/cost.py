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
    input). ``batch=True`` applies the 50% Message Batches discount to the
    per-sheet digest spend (the dominant cost); the synthesis pass runs
    synchronously, but folding it in at the batch rate too keeps the estimate
    deliberately slightly-high rather than under-stated. ``focus`` mirrors a
    per-run focus: each sheet's digest grows by a focus-findings section, and
    one more text-only pass (the focus report) re-reads the digests.

    ``spec_chars`` (uploaded project-specifications character count, 0 when
    none) is priced separately at the cache-aware rate (see
    :func:`_specs_cost_contribution`) rather than folded into the flat 1x
    ``input_tokens`` sum above — it rides a system-prompt block that is
    cache-written once and cache-read (~0.1x) on every sheet after, so pricing
    it at the flat rate would overstate what it actually costs.
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
        lines.append(
            f"Project specifications: ~{est.spec_chars:,} chars attached — "
            "cached after the first sheet(s) (~0.1x rate)."
        )
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
_ASSUMED_VERIFY_OUTPUT_TOKENS_PER_FINDING = 150
_ASSUMED_CITATION_INPUT_TOKENS_PER_CLAIM = 2_000  # web-search prompt + tool results
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
# budget (10 findings) — the cap the stage itself enforces.
_UNCERTAIN_FINDINGS_FRACTION = 0.2
_ASSUMED_INVESTIGATE_ROUNDS = 3
_ASSUMED_INVESTIGATE_INPUT_TOKENS_PER_ROUND = 6_000
_ASSUMED_INVESTIGATE_OUTPUT_TOKENS_PER_ROUND = 300
_INVESTIGATE_MAX_FINDINGS_QUOTED = 10


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
    verified_effective_date: str = PRICING_EFFECTIVE_DATE
    spec_chars: int = 0  # uploaded project-specifications char count, if any


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
    spec_chars: int = 0,
) -> ExhaustiveCostEstimate:
    """Estimate an **exhaustive QC** run's cost, component by component (§15.7).

    The digest (and synthesis / focus) and the two critique reads ride the Batch
    path when ``batch`` is set (Phase 23C routed critique through Batches); cross-QC,
    verification, and citation still run real-time. Verification and citation are
    quoted as a low–high band because their volume tracks the finding / unique-claim
    count.
    A component whose model price is unknown contributes ``None`` and drops out of
    the numeric total (the caller shows scale without a dollar figure).

    ``spec_chars`` (uploaded project specifications) only affects the Digest
    component — the specs block is digest-only (see ``digest.py``), never sent
    to critique/cross-QC/verification/citation.
    """
    per_sheet_images = estimate_image_tokens_for_set(1, rows=rows, cols=cols, model=model)
    components: list[CostComponent] = []

    # Digest (+ synthesis + focus + specs) — the existing digest-path estimate,
    # batch-priced.
    digest_est = estimate_drawing_set_cost(
        sheet_count, file_count=file_count, model=model, rows=rows, cols=cols,
        synthesize=True, batch=batch, focus=focus, spec_chars=spec_chars,
    )
    components.append(CostComponent(
        stage="Digest + synthesis" + (" + focus" if focus else ""),
        input_tokens=digest_est.input_tokens, output_tokens=digest_est.output_tokens,
        cost=digest_est.total_cost, transport="batch" if batch else "real-time",
        note="one vision call per sheet" + (" + text passes" if sheet_count >= 2 else ""),
    ))

    # Phase A planning stages — one text-only real-time call each: the set
    # identity (disciplines/jurisdiction/adopted codes) and the model-authored
    # review plan the critique applies as its checklist.
    components.append(_component(
        "Set identity",
        _ASSUMED_IDENTITY_INPUT_TOKENS_BASE
        + sheet_count * _ASSUMED_IDENTITY_INPUT_TOKENS_PER_SHEET,
        _ASSUMED_IDENTITY_OUTPUT_TOKENS, model=model, batch=False,
        note="one text call — disciplines/jurisdiction/adopted codes",
    ))
    components.append(_component(
        "Model review plan",
        _ASSUMED_PLAN_INPUT_TOKENS_BASE
        + sheet_count * _ASSUMED_PLAN_INPUT_TOKENS_PER_SHEET,
        _ASSUMED_PLAN_OUTPUT_TOKENS, model=model, batch=False,
        note="one text call — the authored review checklist",
    ))

    # Critique — two adversarial reads per sheet. In a ``use_batch`` run both reads
    # ride one Message Batch referencing a single shared per-sheet upload (Phase
    # 23C), so they are batch-priced; otherwise real-time.
    crit_in = 2 * sheet_count * (per_sheet_images + _ASSUMED_PROMPT_TOKENS_PER_SHEET)
    crit_out = 2 * sheet_count * _ASSUMED_CRITIQUE_OUTPUT_TOKENS_PER_READ
    components.append(_component(
        "Critique ×2 (per sheet)", crit_in, crit_out, model=model, batch=batch,
        note="two full reads per sheet"
        + (" — one shared upload, Batch rate" if batch else " — real-time"),
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

    def _investigate(findings: float) -> CostComponent:
        from .core.api_config import VERIFICATION_ESCALATION_MODEL

        n = min(max(0, round(findings * _UNCERTAIN_FINDINGS_FRACTION)),
                _INVESTIGATE_MAX_FINDINGS_QUOTED)
        rounds = n * _ASSUMED_INVESTIGATE_ROUNDS
        return _component(
            "Investigation",
            rounds * _ASSUMED_INVESTIGATE_INPUT_TOKENS_PER_ROUND,
            rounds * _ASSUMED_INVESTIGATE_OUTPUT_TOKENS_PER_ROUND,
            model=VERIFICATION_ESCALATION_MODEL, batch=False,
            note=f"~{n} uncertain finding(s) × ~{_ASSUMED_INVESTIGATE_ROUNDS}-turn "
                 "evidence loop",
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
        known = [c.cost for c in components + variants if c.cost is not None]
        return sum(known) if known else None

    low_cost = _total([low_verify, low_investigate, low_citation])
    high_cost = _total([high_verify, high_investigate, high_citation])
    components = components + [high_verify, high_investigate, high_citation]
    return ExhaustiveCostEstimate(
        sheet_count=sheet_count, file_count=file_count, model=model,
        components=components, low_cost=low_cost, high_cost=high_cost,
        batch=batch, spec_chars=spec_chars,
    )


def format_exhaustive_cost_prompt(est: ExhaustiveCostEstimate) -> str:
    """Human-readable confirmation for an exhaustive QC run (§15.7)."""
    where = f" from {est.file_count} file(s)" if est.file_count else ""
    lines = [
        f"About to run the FULL exhaustive QC review on {est.sheet_count} sheet(s)"
        f"{where} with {friendly_model_name(est.model)} — digest, set identity + "
        "model review plan, two critique reads per sheet, cross-sheet QC, "
        "deterministic auditors, prose harvest, verification, the uncertain-"
        "finding investigation loop, and citation checks.",
        "",
        "Estimated cost by stage:",
    ]
    if est.spec_chars:
        lines.append(
            f"  (Digest includes ~{est.spec_chars:,} chars of uploaded project "
            "specifications, cached after the first sheet(s).)"
        )
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
    if est.batch:
        lines += [
            "",
            "Batch mode: sheets go into Anthropic's shared queue and are processed "
            "when they reach the front — often a few hours, sometimes overnight "
            "(8+ hours). Cheapest option; best left running when you're not in a rush.",
        ]
    else:
        lines += [
            "",
            "Real-time mode: no queue — expect roughly 4–6 minutes per sheet, at the "
            "full (un-discounted) API rate. Choose this when you need results now.",
        ]
    lines += ["", "Proceed with the exhaustive review?"]
    return "\n".join(lines)
