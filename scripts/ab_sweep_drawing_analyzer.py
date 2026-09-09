#!/usr/bin/env python3
"""A/B a cost lever against quality, on a real drawing set.

Two levers are worth pulling in this app — the critique model and the render
target — and neither can be evaluated by the hermetic suite. The §19.1 trust
gauntlet routes canned responses by system-prompt string identity and never
reads ``kw["model"]``, so a model swap changes nothing it returns: it answers
"did this break the contract", not "did this hurt findings quality".

This runs the same sheet set twice, cold on both arms, with one variable
changed, and reports what moved.

Why a fixed oracle is not required
----------------------------------
There is usually no ground-truth finding list for a real permit set. But three
signals already in the pipeline need no oracle, and together they catch the
failure modes a cost lever actually causes:

  anchor tier mix        ``anchor.py`` EXACT/FUZZY/TILE/UNANCHORED. UNANCHORED is
                         the documented hallucination signal — a quote the model
                         produced that is not on the sheet. If it climbs, the
                         cheaper configuration is inventing more.
  verification mix       ``verify.py`` VERIFIED/REJECTED/UNCERTAIN per finding.
                         REJECTED climbing means more false positives; the count
                         dropping while the VERIFIED *share* holds means real
                         defects went unseen.
  self-consistency mix   The critique already runs twice and records
                         REPRODUCED / SINGLETON per finding. The reproduced rate
                         is an agreement score, and it is also how you A/B two
                         models directly: put read 1 on one and read 2 on the
                         other.

None of these is a quality oracle. A lever that holds all three flat at
materially lower cost is defensible; one that moves any of them the wrong way is
a reject. That is a decision procedure, which is what was missing.

Usage
-----
    python scripts/ab_sweep_drawing_analyzer.py \\
        --pdf setA/M-101.pdf --pdf setA/E-201.pdf \\
        --baseline "" \\
        --variant DRAWING_ANALYZER_CRITIQUE_MODEL=claude-sonnet-5 \\
        --out ab_out

    # the render-target sweep
    --variant DRAWING_ANALYZER_TILE_TARGET_PX=1240

Each arm runs in a **subprocess**. That is not tidiness: ``REVIEW_MODEL_DEFAULT``
is an ``os.environ.get`` evaluated at *module scope* in ``core.api_config``, and
fourteen modules bind it as a second name via ``from ... import``. Setting
``DRAWING_ANALYZER_MODEL`` after import does nothing, and monkeypatching the
``api_config`` attribute does not change what ``critique_model()`` returns. A
subprocess sidesteps the whole class of problem, and also guarantees the second
arm cannot inherit warm module state from the first.

Every run costs real money. Nothing here is hermetic, and there is no
``--dry-run`` that would pretend otherwise — but ``--estimate`` prices the two
arms before you commit.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))


# --------------------------------------------------------------------------- #
# Summary (pure — builds the comparable record from a finished run)
# --------------------------------------------------------------------------- #

# Ordered so a rendered table always lists tiers/verdicts in the same order,
# whether or not a given arm produced any of each (I-7 in spirit: same inputs,
# same ordering).
ANCHOR_TIERS = ("EXACT", "FUZZY", "TILE", "UNANCHORED")
VERIFY_STATUSES = ("VERIFIED", "REJECTED", "UNCERTAIN", "DETERMINISTIC", "SKIPPED")
CONFIDENCE_LEVELS = (
    "REPRODUCED", "SINGLETON", "NOT_ASSESSED_PARTIAL", "NOT_APPLICABLE",
)
SEVERITIES = ("high", "medium", "low")


def _tally(values, keys) -> dict[str, int]:
    """Count ``values`` into ``keys`` order, with an ``other`` bucket.

    Never drops a value: an unrecognized one lands in ``other`` so the tally
    always sums to the population it describes. A silently-dropped verdict would
    make one arm look better than it is.
    """
    out = {k: 0 for k in keys}
    out["other"] = 0
    for v in values:
        key = str(v or "")
        out[key if key in out else "other"] += 1
    return out


#: Outcome buckets for a usage record, in report order. These are NOT
#: interchangeable and must never be folded into one "paid calls" number:
#: a served cache hit costs nothing, an abandoned batch attempt costs nothing
#: *and* produced no response, and a failed-parse call consumed real tokens.
#: Collapsing them lets an arm that abandoned half its batches look cheap.
_OUTCOMES = ("served", "cache_hit", "abandoned", "parse_failed", "failed")


def _record_outcome(r) -> str:
    """Which bucket one :class:`UsageRecord` belongs in.

    ``parse_failed`` is reserved for a response that *arrived and could not be
    used* — tokens were spent on something unusable. A request that raised before
    any response also carries ``parse_success=False`` (there was nothing to
    parse), and the pipeline pairs it with ``terminal_status="FAILED"`` and zero
    tokens. Checking ``parse_success`` first swept those into ``parse_failed``
    and emptied the ``failed`` bucket — which inverts the one question these
    buckets exist to answer: did this arm get unusable answers, or get no answers
    at all? Those call for opposite responses.
    """
    status = str(getattr(r, "terminal_status", "") or "")
    if getattr(r, "cache_hit", False):
        return "cache_hit"
    if status.startswith("ABANDONED"):
        return "abandoned"
    if status in ("FAILED", "PARTIAL"):
        return "failed"
    # Response-bearing only: no tokens means no response to have failed on.
    if not getattr(r, "parse_success", True) and (
        getattr(r, "input_tokens", 0) or getattr(r, "output_tokens", 0)
    ):
        return "parse_failed"
    if not getattr(r, "parse_success", True):
        return "failed"
    return "served"


def usage_breakdown(run_usage) -> dict:
    """The axes ``by_family``/``by_model`` do not carry (WP-06 §11.1).

    Derived from the same append-only records the run priced itself with — this
    is a *view*, never a second billing calculator. Every dollar figure here comes
    from ``UsageRecord.estimated_cost``, which the run computed at its own rate
    class; nothing is re-priced.

    Three axes the existing rollups drop, each of which can move between two arms
    that look identical in a family rollup:

    - **transport** — REAL_TIME / BATCH / CACHE. A variant that shifts work to the
      batch queue halves its rate without changing a single token count.
    - **cache tokens** — read and write are separately priced multipliers, and the
      requested write TTL decides which (1.25x for 5-minute, 2x for one hour).
      Summing them into "input" makes a prompt-cache experiment unmeasurable.
    - **outcome** — see :data:`_OUTCOMES`.

    ``unpriced_records`` is the honest companion to a ``None`` cost: it says how
    many records could not be priced, so a reader can tell "no model price" from
    "no usage". It calls ``RunUsage.is_billable_but_unpriced`` rather than
    restating the rule — the first version of this function reimplemented it and
    immediately drifted, missing cache tokens, which is how two views of the same
    ledger start disagreeing about what was spent.

    **Granularity is labelled, not assumed.** The pipeline aggregates some
    verification work into a single usage record, so ``calls`` is a record count
    and not universally an API-call count. ``record_granularity`` says so in the
    output rather than letting a reader infer call counts from it.
    """
    from drawing_analyzer.models import RunUsage

    records = list(getattr(run_usage, "records", None) or [])
    if not records:
        return {"records": 0, "record_granularity": "one record per API call or attempt,"
                " except verification which the pipeline aggregates"}

    def _bucket() -> dict:
        return {"records": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "cache_write_tokens": 0}

    by_transport: dict[str, dict] = {}
    outcomes = {k: 0 for k in _OUTCOMES}
    write_ttls: dict[str, int] = {}
    unpriced = 0
    cache_read = cache_write = 0
    for r in records:
        g = by_transport.setdefault(str(getattr(r, "transport", "") or ""), _bucket())
        g["records"] += 1
        g["input_tokens"] += getattr(r, "input_tokens", 0)
        g["output_tokens"] += getattr(r, "output_tokens", 0)
        g["cache_read_tokens"] += getattr(r, "cache_read_tokens", 0)
        g["cache_write_tokens"] += getattr(r, "cache_write_tokens", 0)
        cache_read += getattr(r, "cache_read_tokens", 0)
        cache_write += getattr(r, "cache_write_tokens", 0)
        outcomes[_record_outcome(r)] += 1
        if getattr(r, "cache_write_tokens", 0):
            ttl = str(getattr(r, "cache_write_ttl", None) or "5m")
            write_ttls[ttl] = write_ttls.get(ttl, 0) + getattr(r, "cache_write_tokens", 0)
        if RunUsage.is_billable_but_unpriced(r):
            unpriced += 1
    return {
        "records": len(records),
        "record_granularity": "one record per API call or attempt, except"
                              " verification which the pipeline aggregates",
        "by_transport": dict(sorted(by_transport.items())),
        "by_outcome": outcomes,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cache_write_tokens_by_ttl": dict(sorted(write_ttls.items())),
        "unpriced_records": unpriced,
    }


def summarize_run(ctx) -> dict:
    """Everything the comparison needs from a finished ``DrawingContext``."""
    findings = list(ctx.all_findings)
    ru = ctx.run_usage
    cost = ctx.total_estimated_cost

    sources: dict[str, int] = {}
    for f in findings:
        for tag in (f.sources or ["(untagged)"]):
            sources[tag] = sources.get(tag, 0) + 1

    return {
        "sheets": ctx.sheet_count,
        "ok_sheets": ctx.ok_sheet_count,
        "errors": len(ctx.errors),
        "qc_status": ctx.qc_status,
        "coverage_status": ctx.coverage_status,
        "findings_total": len(findings),
        "findings_by_severity": _tally((f.severity for f in findings), SEVERITIES),
        "findings_by_source": dict(sorted(sources.items())),
        # --- the three ground-truth-free quality signals ---
        "anchor_tiers": _tally((f.anchor.status for f in findings), ANCHOR_TIERS),
        "verification": _tally(
            (f.verification.status for f in findings), VERIFY_STATUSES
        ),
        "confidence": _tally((f.confidence for f in findings), CONFIDENCE_LEVELS),
        # --- cost ---
        "input_tokens": ctx.total_input_tokens,
        "output_tokens": ctx.total_output_tokens,
        "image_token_estimate": ctx.total_image_token_estimate,
        "estimated_cost_usd": None if cost is None else float(cost),
        # Per-family COST, not just tokens. ``_rollup`` already computes it with
        # the run's own pricing — this line simply stopped dropping it. Without
        # it, "the critique got cheaper" could not be told from "the critique did
        # less work", which is the whole question a model-swap arm is asking.
        "by_family": {
            fam: {"input": g["input_tokens"], "output": g["output_tokens"],
                  "calls": g["calls"], "cache_hits": g["cache_hits"],
                  "cost": None if g["estimated_cost"] is None
                          else float(g["estimated_cost"])}
            for fam, g in (ru.by_family() if ru else {}).items()
        },
        "usage_axes": usage_breakdown(ru),
        "by_model": {
            m: {"input": g["input_tokens"], "output": g["output_tokens"],
                "calls": g["calls"],
                "cost": None if g["estimated_cost"] is None
                        else float(g["estimated_cost"])}
            for m, g in (ru.by_model() if ru else {}).items()
        },
    }


# --------------------------------------------------------------------------- #
# Diff + render (pure)
# --------------------------------------------------------------------------- #

def _pct_delta(base: float | int | None, var: float | int | None) -> float | None:
    """Percent change from ``base`` to ``var``; ``None`` when undefined.

    Undefined rather than infinite when the baseline is zero — a bare "+inf%"
    in a decision table is worse than an honest blank.
    """
    if base is None or var is None or base == 0:
        return None
    return (var - base) / base * 100.0


def diff_summaries(base: dict, var: dict) -> dict:
    """Compare two arm summaries. Pure; the renderer does the judging."""
    def delta_map(key: str) -> dict:
        b, v = base.get(key, {}), var.get(key, {})
        return {
            k: {"base": b.get(k, 0), "variant": v.get(k, 0),
                "delta": v.get(k, 0) - b.get(k, 0)}
            for k in sorted(set(b) | set(v))
        }

    return {
        "cost": {
            "base": base.get("estimated_cost_usd"),
            "variant": var.get("estimated_cost_usd"),
            "pct": _pct_delta(base.get("estimated_cost_usd"),
                              var.get("estimated_cost_usd")),
        },
        "input_tokens": {
            "base": base.get("input_tokens"), "variant": var.get("input_tokens"),
            "pct": _pct_delta(base.get("input_tokens"), var.get("input_tokens")),
        },
        "findings_total": {
            "base": base.get("findings_total"), "variant": var.get("findings_total"),
            "pct": _pct_delta(base.get("findings_total"), var.get("findings_total")),
        },
        "findings_by_severity": delta_map("findings_by_severity"),
        "anchor_tiers": delta_map("anchor_tiers"),
        "verification": delta_map("verification"),
        "confidence": delta_map("confidence"),
        "by_model": {
            "base": base.get("by_model", {}), "variant": var.get("by_model", {}),
        },
        "verdict": _verdict(base, var),
    }


def _rate(tally: dict, key: str) -> float | None:
    """``key``'s share of a tally, or ``None`` when the tally is empty."""
    total = sum(v for v in tally.values())
    return None if total == 0 else tally.get(key, 0) / total


# A signal must move by more than this (in percentage points of its share) to
# count as a regression. Runs are not deterministic at the model level, so a
# hair-trigger would reject every variant on noise; this is a coarse screen, and
# the numbers above it are what an operator actually judges on.
_RATE_TOLERANCE = 0.05


def _verdict(base: dict, var: dict) -> dict:
    """Screen the three quality signals. Advisory — never the final word.

    Deliberately conservative in one direction: it reports a concern when a
    signal degrades, and stays silent otherwise. It does NOT bless a variant;
    "no concern raised" means the screen found nothing, not that the change is
    safe. One run of one set cannot establish that.
    """
    concerns: list[str] = []

    unanchored_b = _rate(base.get("anchor_tiers", {}), "UNANCHORED")
    unanchored_v = _rate(var.get("anchor_tiers", {}), "UNANCHORED")
    if unanchored_b is not None and unanchored_v is not None:
        if unanchored_v - unanchored_b > _RATE_TOLERANCE:
            concerns.append(
                f"UNANCHORED share rose {unanchored_b:.1%} → {unanchored_v:.1%} "
                "— the hallucination signal; the variant is grounding fewer "
                "findings in text that is actually on the sheet"
            )

    rejected_b = _rate(base.get("verification", {}), "REJECTED")
    rejected_v = _rate(var.get("verification", {}), "REJECTED")
    if rejected_b is not None and rejected_v is not None:
        if rejected_v - rejected_b > _RATE_TOLERANCE:
            concerns.append(
                f"REJECTED share rose {rejected_b:.1%} → {rejected_v:.1%} "
                "— more findings failed their crop re-check (false positives)"
            )

    repro_b = _rate(base.get("confidence", {}), "REPRODUCED")
    repro_v = _rate(var.get("confidence", {}), "REPRODUCED")
    if repro_b is not None and repro_v is not None:
        if repro_b - repro_v > _RATE_TOLERANCE:
            concerns.append(
                f"REPRODUCED share fell {repro_b:.1%} → {repro_v:.1%} "
                "— the two independent reads agree less often"
            )

    # A large drop in finding count with the verified share flat is the quiet
    # failure: the variant is not producing worse findings, it is producing
    # fewer of them. That reads as "cheaper AND cleaner" on every other line.
    fb, fv = base.get("findings_total", 0), var.get("findings_total", 0)
    if fb and (fb - fv) / fb > 0.20:
        concerns.append(
            f"finding count fell {fb} → {fv} ({(fv - fb) / fb:+.0%}) — check "
            "whether real defects went unseen; a drop with the VERIFIED share "
            "flat means missed findings, not cleaner ones"
        )

    return {"concerns": concerns, "clean_screen": not concerns}


def _fmt_delta_rows(title: str, m: dict) -> list[str]:
    rows = [f"  {title}", f"    {'':<22}{'base':>8}{'variant':>10}{'delta':>8}"]
    for k, d in m.items():
        if d["base"] == 0 and d["variant"] == 0:
            continue
        rows.append(
            f"    {k:<22}{d['base']:>8}{d['variant']:>10}{d['delta']:>+8}"
        )
    return rows


def render_diff(diff: dict, *, base_label: str, var_label: str) -> str:
    lines = [
        "=" * 72,
        f"A/B sweep: {base_label}  vs  {var_label}",
        "=" * 72,
        "",
        "  COST",
    ]
    for key, label, unit in (
        ("cost", "estimated USD", "$"),
        ("input_tokens", "input tokens", ""),
        ("findings_total", "findings", ""),
    ):
        d = diff[key]
        b, v, p = d["base"], d["variant"], d["pct"]
        bs = "n/a" if b is None else (f"${b:,.2f}" if unit else f"{b:,}")
        vs = "n/a" if v is None else (f"${v:,.2f}" if unit else f"{v:,}")
        ps = "" if p is None else f"  ({p:+.1f}%)"
        lines.append(f"    {label:<22}{bs:>10}{vs:>12}{ps}")

    lines += ["", "  QUALITY SIGNALS (no ground truth needed)"]
    lines += _fmt_delta_rows("anchor tier", diff["anchor_tiers"])
    lines += _fmt_delta_rows("verification verdict", diff["verification"])
    lines += _fmt_delta_rows("self-consistency", diff["confidence"])
    lines += _fmt_delta_rows("severity", diff["findings_by_severity"])

    lines += ["", "  SPEND BY MODEL"]
    for arm, key in (("base", "base"), ("variant", "variant")):
        for model, g in sorted(diff["by_model"][key].items()):
            money = "n/a" if g.get("cost") is None else f"${g['cost']:,.2f}"
            lines.append(
                f"    {arm:<10}{model:<24}{g['calls']:>5} calls{money:>12}"
            )

    verdict = diff["verdict"]
    lines += ["", "  SCREEN"]
    if verdict["clean_screen"]:
        lines += [
            "    No quality signal degraded beyond tolerance.",
            "    This is NOT an approval — it means the screen found nothing.",
            "    One run of one set cannot establish that a change is safe.",
        ]
    else:
        for c in verdict["concerns"]:
            lines.append(f"    [CONCERN] {c}")
    lines += ["", "=" * 72]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Arm execution (subprocess)
# --------------------------------------------------------------------------- #

def _parse_env(spec: str) -> dict[str, str]:
    """``"A=1,B=2"`` → ``{"A": "1", "B": "2"}``. Empty string → ``{}``."""
    out: dict[str, str] = {}
    for pair in (spec or "").split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"expected NAME=VALUE, got {pair!r}")
        name, _, value = pair.partition("=")
        out[name.strip()] = value.strip()
    return out


# --------------------------------------------------------------------------- #
# Typed per-arm geometry (WP-06 §11.4)
# --------------------------------------------------------------------------- #

#: The render identity serializes overlap as ``f"overlap={overlap_frac:.4f}"``
#: (``render.py``), so 0.08001 and 0.08002 produce the SAME level-1 cache key
#: while rendering different pixels. An experiment sweeping finer than that would
#: silently compare one arm against the other's cached renders. Rejecting the
#: value is the honest response; silently rounding it would run an experiment the
#: operator did not ask for and report it under the label they typed.
_OVERLAP_DECIMALS = 4
#: Below zero is meaningless; at 0.5 an interior tile has grown by its own width
#: on each side and the "grid" no longer partitions anything. Neither bound is a
#: quality opinion — they exist to catch a fat-fingered value before it reaches
#: tiling or a cache key.
_OVERLAP_MIN, _OVERLAP_MAX = 0.0, 0.5


def parse_overlap(raw: str | None, *, label: str) -> float | None:
    """Validate one ``--*-overlap`` value. ``None`` when unset (keep the default).

    Rejects NaN and infinity explicitly: both survive ``float()``, both would
    reach ``tile_rects`` and the render identity, and ``f"{float('nan'):.4f}"``
    is ``"nan"`` — a perfectly stable cache key for a geometry that cannot be
    rendered. Range and precision are checked here, before anything costly, so a
    bad value fails in milliseconds rather than after two arms have been priced.
    """
    import math

    if raw is None or str(raw).strip() == "":
        return None
    text = str(raw).strip()
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{label}: expected a number, got {text!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{label}: {text!r} is not a finite number")
    if not (_OVERLAP_MIN <= value <= _OVERLAP_MAX):
        raise ValueError(
            f"{label}: {value} is outside the supported range "
            f"[{_OVERLAP_MIN}, {_OVERLAP_MAX}]"
        )
    if round(value, _OVERLAP_DECIMALS) != value:
        raise ValueError(
            f"{label}: {text} has more than {_OVERLAP_DECIMALS} decimal places. "
            f"The render identity records overlap to {_OVERLAP_DECIMALS} places, "
            f"so finer values would share a cache key while rendering "
            f"differently — the arms would compare against each other's caches."
        )
    return value


@dataclass(frozen=True)
class ArmSpec:
    """One arm's reviewed parameters — the experiment's identity (§11.4).

    The same-configuration guard used to compare whole environment dictionaries,
    which fails in both directions: an irrelevant variable differing between two
    shells defeated it, and an overlap-only change could not be expressed at all
    because overlap was not an environment variable. What decides whether two
    arms are an experiment is the set of things the harness actually varies, and
    that is exactly this.
    """

    env: dict
    overlap_frac: float | None = None

    @property
    def resolved_overlap(self) -> float:
        """What the arm will actually render at — omitted means the default."""
        from drawing_analyzer import tiling

        return (
            tiling.DEFAULT_OVERLAP_FRAC if self.overlap_frac is None
            else self.overlap_frac
        )

    def identity(self) -> tuple:
        """**Resolved** settings, not the spelling that produced them.

        Comparing the raw options reintroduces the very bug this guard exists to
        prevent, in a new dress: an omitted ``--baseline-overlap`` and an explicit
        ``--variant-overlap 0.08`` are ``None`` and ``0.08``, which differ — while
        both render at the shipping 0.08. The guard would wave through two
        identical billable runs.

        The typed ``env`` entries stay part of the identity even if the pipeline
        happens to ignore one. That is deliberate: what the operator typed is
        their statement of intent, and the alternative — an allowlist of
        recognised variables — would silently drop a knob added to the pipeline
        later, turning a real experiment into a rejected one. Erring toward
        "these arms differ" costs a run the operator asked for; erring the other
        way costs a run they did not.
        """
        return (tuple(sorted(self.env.items())), self.resolved_overlap)

    def label(self) -> str:
        parts = [env_label(self.env)] if self.env else []
        if self.overlap_frac is not None:
            parts.append(f"overlap={self.overlap_frac}")
        return ", ".join(parts) or "defaults"


def resolve_transport() -> tuple[bool, bool]:
    """``(digest_batch, critique_batch)`` for the *current* environment.

    Resolved through the pipeline's own helper rather than restated, so the
    estimate and the run can never disagree about which rate applies. That
    disagreement is not hypothetical: quoting the estimator's ``batch=True``
    default against a run that resolves to real-time under-states the two
    stages that dominate the bill by half, which is the opposite of what a
    pre-spend check is for.

    Both default to real-time; ``DRAWING_ANALYZER_USE_BATCH`` opts in, and
    critique follows the digest transport unless a caller splits them (the GUI's
    Hybrid mode), which this harness does not.
    """
    from drawing_analyzer.pipeline import _resolve_use_batch

    use_batch = _resolve_use_batch(None)
    return use_batch, use_batch


def resolve_arm_configuration(
    *, exhaustive: bool, overlap_frac: float | None = None,
) -> dict:
    """Everything about THIS process's configuration that moves the bill.

    One resolver, called by both children (WP-04 §9.1). Estimation and execution
    used to describe the arm separately, and the way that fails is quiet: the two
    descriptions drift, and the estimate you approved stops being a description
    of the run you paid for. Every value here is read through the function the
    runtime itself calls, never restated.

    Deliberately excludes anything secret-valued — this record is printed and
    saved. It reports the tile-target *override* the operator set, which is the
    lever, not the resolved per-request target, which also depends on each
    sheet's own raster/vector classification and so is not a per-arm constant.
    """
    from drawing_analyzer import tiling
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT
    from drawing_analyzer.cost import resolve_stage_models

    use_batch, critique_batch = resolve_transport()
    return {
        "model": REVIEW_MODEL_DEFAULT,
        # Every stage, resolved by the functions the runtime calls. This is what
        # makes a global-model change legible: six of these move with it.
        "stage_models": vars(resolve_stage_models(model=REVIEW_MODEL_DEFAULT)),
        "transport": {"digest_batch": use_batch, "critique_batch": critique_batch},
        "grid": [tiling.DEFAULT_GRID_ROWS, tiling.DEFAULT_GRID_COLS],
        # The value the arm will actually render at, not the command-line
        # spelling: an omitted option resolves to the shipping default here, so
        # the record says what happened rather than what was typed (§11.4).
        "overlap_frac": (
            tiling.DEFAULT_OVERLAP_FRAC if overlap_frac is None else overlap_frac
        ),
        "overlap_overridden": overlap_frac is not None,
        # The raw setting and what the clamp made of it: a fat-fingered value is
        # silently clamped, and an arm priced at the clamped target while the
        # operator believes the typed one is a comparison of the wrong thing.
        "tile_target_px": os.environ.get(tiling.TILE_TARGET_PX_ENV, ""),
        "tile_target_effective": tiling._vector_target_override(),
        "tile_target_default": tiling.TARGET_LONG_EDGE_PX_DEFAULT,
        "exhaustive": bool(exhaustive),
    }


def _run_arm_in_process(
    pdfs: list[Path], out_path: Path, *, exhaustive: bool,
    overlap_frac: float | None = None,
) -> None:
    """Execute one arm and write its summary. Runs inside the child process."""
    from drawing_analyzer.client import get_client
    from drawing_analyzer.digest_cache import DigestCache
    from drawing_analyzer.pipeline import extract_drawing_context

    use_batch, critique_use_batch = resolve_transport()

    with TemporaryDirectory(prefix="da-ab-arm-") as tmp:
        # A private cache per arm. Both arms are therefore cold, which is the
        # whole point: every cache key folds the model, so the arms could not
        # contaminate each other anyway — but a warm arm compared against a cold
        # one measures nothing.
        cache = DigestCache(Path(tmp) / "cache.json")
        # Forwarded as the pipeline's own ``overlap_frac`` kwarg — the same
        # parameter the estimate child resolves — so the arm renders the geometry
        # it was priced at. Omitted means the shipping default, untouched.
        geometry_kwargs = (
            {} if overlap_frac is None else {"overlap_frac": overlap_frac}
        )
        ctx = extract_drawing_context(
            pdfs,
            client=get_client(),
            cache=cache,
            **geometry_kwargs,
            qc_markups=exhaustive,
            reference_audit=exhaustive,
            # Passed explicitly, at the value the runtime would have resolved
            # anyway, so the summary can record the transport it was actually
            # billed at and the estimate can be checked against it.
            use_batch=use_batch,
            critique_use_batch=critique_use_batch,
        )
        summary = summarize_run(ctx)

    # The same record the estimate child emits, so an arm's summary and the
    # quote that authorized it are directly comparable field by field.
    summary["configuration"] = resolve_arm_configuration(
        exhaustive=exhaustive, overlap_frac=overlap_frac
    )
    summary.update(summary["configuration"])
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def run_arm(
    label: str, env: dict[str, str], pdfs: list[Path], out_dir: Path,
    *, exhaustive: bool, overlap_frac: float | None = None,
) -> dict:
    """Run one arm in a subprocess and return its summary."""
    out_path = out_dir / f"arm_{label}.json"
    child_env = {**os.environ, **env}
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--_arm", str(out_path), "--exhaustive" if exhaustive else "--no-exhaustive",
        *([] if overlap_frac is None else ["--overlap", repr(overlap_frac)]),
        *[a for p in pdfs for a in ("--pdf", str(p))],
    ]
    print(f"[{label}] {env_label(env)}")
    proc = subprocess.run(cmd, env=child_env)
    if proc.returncode != 0:
        raise SystemExit(f"arm {label!r} failed with exit code {proc.returncode}")
    return json.loads(out_path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Estimation (subprocess, same configuration boundary as a real arm)
# --------------------------------------------------------------------------- #
#
# WP-04 §9.1. The estimate must cross the SAME process boundary an arm does, for
# the same reason the arms do: ``REVIEW_MODEL_DEFAULT`` is an ``os.environ.get``
# evaluated at *module scope* in ``core.api_config``, and five stage resolvers
# fall back to it by value —
#
#     critique.critique_model()                  cross_qc.cross_qc_model()
#     synthesis.default_synthesis_model()        focus.default_focus_model()
#     review_planner.default_review_plan_model()
#
# each of them ``os.environ.get(<its own var>) or REVIEW_MODEL_DEFAULT``. Setting
# ``DRAWING_ANALYZER_MODEL`` in the parent after import moves none of them.
#
# The in-process alternative — re-reading the environment for the model inside
# the arm loop — was evaluated during review and REJECTED. It fixes the digest,
# whose model is a threaded parameter, and silently leaves those five stages
# quoted at the parent's model while execution resolves all five correctly. An
# estimator that is right about the one stage you were not changing and wrong
# about the five you were is worse than no estimator, because it looks right.
# Do not "simplify" this back into the parent process.
#
# The child protocol is deliberately small: an argument vector in, one JSON
# object on stdout, an exit code. No RPC layer, no shared state.

#: Environment names whose VALUE must never reach a printed label, a saved
#: report, or the effective-configuration record. Substring match, upper-cased:
#: the environment legitimately carries an API key during a sweep even though
#: estimation needs none, and ``--variant ANTHROPIC_API_KEY=...`` is a thing a
#: user can type. Matching the *name* rather than sniffing the value is the
#: reliable direction — a key that does not look like one still must not print.
_SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


def _is_secret_env(name: str) -> bool:
    return any(marker in (name or "").upper() for marker in _SECRET_ENV_MARKERS)


def env_label(env: dict[str, str]) -> str:
    """``{"A": "1"}`` → ``"A=1"``, with secret-valued names shown redacted.

    Used for every human-facing label and for ``diff.txt``, which is saved. The
    redaction is by variable NAME, so a credential that does not look like one
    is still covered.
    """
    if not env:
        return "defaults"
    return ", ".join(
        f"{k}=[REDACTED]" if _is_secret_env(k) else f"{k}={v}"
        for k, v in env.items()
    )


def _estimate_in_process(
    sheets: int, file_count: int, *, exhaustive: bool,
    overlap_frac: float | None = None,
) -> dict:
    """Resolve this process's configuration and price it. Runs in the child.

    Local inspection only — no client is constructed, nothing is uploaded, no
    batch is created, no analysis cache is touched, and no provider token-count
    call is made. The imports are inside the function so they bind AFTER the
    child's environment is in place, which is the entire point of the boundary.
    """
    from drawing_analyzer.cost import (
        estimate_drawing_set_cost,
        estimate_exhaustive_run_cost,
    )

    config = resolve_arm_configuration(
        exhaustive=exhaustive, overlap_frac=overlap_frac
    )
    model = config["model"]
    use_batch = config["transport"]["digest_batch"]
    out: dict = {"sheets": sheets, "file_count": file_count, **config}
    if exhaustive:
        est = estimate_exhaustive_run_cost(
            sheets, file_count=file_count, model=model, batch=use_batch,
            critique_batch=config["transport"]["critique_batch"],
        )
        out["low_cost"], out["high_cost"] = est.low_cost, est.high_cost
    else:
        est = estimate_drawing_set_cost(
            sheets, file_count=file_count, model=model, batch=use_batch,
        )
        out["low_cost"] = out["high_cost"] = est.total_cost
    return out


def estimate_arm(
    label: str, env: dict[str, str], sheets: int, file_count: int, *,
    exhaustive: bool, overlap_frac: float | None = None,
) -> dict:
    """Price one arm in a fresh child process. Returns the child's JSON.

    The parent's own environment is never modified — not cleared, not rebuilt.
    The arm's settings are layered onto a *copy* handed to the child, so an
    interrupted or failing estimate cannot leave the parent holding an arm's
    configuration.
    """
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--_estimate-arm", "--sheets", str(sheets),
        "--file-count", str(file_count),
        "--exhaustive" if exhaustive else "--no-exhaustive",
        *([] if overlap_frac is None else ["--overlap", repr(overlap_frac)]),
    ]
    proc = subprocess.run(
        cmd, env={**os.environ, **env}, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        # Never a zero-cost arm. A failed estimate that prints "$0.00" is an
        # invitation to spend, which is the one thing this mode exists to
        # prevent. stderr is relayed because the child's traceback is the only
        # diagnosis available up here.
        raise SystemExit(
            f"estimate for arm {label!r} failed with exit code "
            f"{proc.returncode}\n{(proc.stderr or '').strip()}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"estimate for arm {label!r} returned unreadable output: {exc}\n"
            f"{(proc.stdout or '').strip()[:2000]}"
        ) from exc


def _money(est: dict) -> str:
    lo, hi = est.get("low_cost"), est.get("high_cost")
    if lo is None or hi is None:
        return "unavailable"
    return f"${lo:,.2f}" if lo == hi else f"${lo:,.2f} - ${hi:,.2f}"


def _model_rows(results: list[tuple[str, dict]]) -> list[str]:
    """Per-stage model lines, showing only the stages the arms disagree on.

    The point of printing these at all is the fallback effect: changing
    ``DRAWING_ANALYZER_MODEL`` alone moves five stages, and an operator pricing
    that change needs to see which. Stages both arms agree on are noise.
    """
    if len(results) < 2:
        return []
    stages = sorted({s for _, r in results for s in (r.get("stage_models") or {})})
    rows = []
    for stage in stages:
        values = [(r.get("stage_models") or {}).get(stage) for _, r in results]
        if len(set(values)) > 1:
            rows.append(f"  {stage:<14}" + "".join(f"{v or '?':<28}" for v in values))
    if not rows:
        return []
    header = "  " + f"{'stage':<14}" + "".join(f"{lbl:<28}" for lbl, _ in results)
    return ["", "Stage models that differ between the arms:", header, *rows]


def _estimate(pdfs: list[Path], arms: "list[tuple[str, ArmSpec]]", *, exhaustive: bool) -> None:
    """Price both arms before spending anything.

    Sheet counting happens once, here: no environment variable changes how many
    pages a PDF has, and counting once means the two arms are provably pricing
    the same set rather than two independent scans that could disagree.
    """
    from drawing_analyzer.render import list_sheets

    sheets = len(list_sheets(pdfs))
    print(f"\n{sheets} sheet(s) across {len(pdfs)} file(s). Estimated per arm:\n")
    results = [
        (label, estimate_arm(label, spec.env, sheets, len(pdfs),
                             exhaustive=exhaustive, overlap_frac=spec.overlap_frac))
        for label, spec in arms
    ]
    for (label, est), (_, spec) in zip(results, arms):
        transport = "batch" if est["transport"]["digest_batch"] else "real-time"
        print(f"  {label:<10}{_money(est):<26}({transport})  {spec.label()}")
    for line in _model_rows(results):
        print(line)
    # An overlap-only experiment quotes both arms identically, and a reader could
    # easily take that for "overlap costs nothing". It does not: the estimate
    # child has no page shapes, so it prices from the conservative allowance —
    # sheets x images-per-grid x a square at the target — and every one of those
    # terms is overlap-invariant. Overlap changes the *rendered rectangle*, which
    # only the shape-aware path (WP-05) can see. Saying so is the difference
    # between a limitation and a wrong number.
    overlaps = {spec.overlap_frac for _, spec in arms}
    if len(overlaps) > 1:
        print(
            "\n  Note: overlap does not move these figures. The estimate prices "
            "the conservative\n  allowance, which depends on grid and target "
            "only — the overlap difference shows\n  up in the run's actual image "
            "tokens, not here."
        )
    print(
        "\nBoth arms run cold, so neither is discounted by a warm cache. These "
        "are estimates, not quotes: sheet complexity, how many findings turn up, "
        "and retries all move the real invoice.\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", action="append", type=Path, default=[],
                    help="a source PDF (repeatable)")
    ap.add_argument("--baseline", default="",
                    help="baseline arm env, NAME=VALUE[,NAME=VALUE] ('' = defaults)")
    ap.add_argument("--variant", default="",
                    help="variant arm env, NAME=VALUE[,NAME=VALUE]")
    ap.add_argument("--baseline-overlap", dest="baseline_overlap", default=None,
                    help=f"baseline tile overlap fraction "
                         f"[{_OVERLAP_MIN}, {_OVERLAP_MAX}], <= {_OVERLAP_DECIMALS} "
                         f"decimals (default: the shipping value)")
    ap.add_argument("--variant-overlap", dest="variant_overlap", default=None,
                    help="variant tile overlap fraction (same rules)")
    ap.add_argument("--out", type=Path, default=Path("ab_out"))
    ap.add_argument("--exhaustive", action="store_true", default=True,
                    help="run the full QC stack (default)")
    ap.add_argument("--no-exhaustive", dest="exhaustive", action="store_false")
    ap.add_argument("--estimate", action="store_true",
                    help="price both arms and exit without spending anything")
    ap.add_argument("--_arm", type=Path, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--_estimate-arm", dest="_estimate_arm", action="store_true",
                    help=argparse.SUPPRESS)
    ap.add_argument("--sheets", type=int, default=0, help=argparse.SUPPRESS)
    ap.add_argument("--file-count", dest="file_count", type=int, default=0,
                    help=argparse.SUPPRESS)
    ap.add_argument("--overlap", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    # Estimate-child mode: price this process's resolved configuration and emit
    # one JSON object. Handled before the ``--pdf`` requirement because the
    # child is given a sheet count, not paths — the parent counted the pages
    # once, and no environment variable can change that number.
    # Validated in the child too, not just the parent: the child is spawned with
    # an argument vector, and a value that reached it unvalidated would land in
    # tiling and the cache key.
    try:
        child_overlap = parse_overlap(args.overlap, label="--overlap")
    except ValueError as exc:
        ap.error(str(exc))

    if args._estimate_arm:
        json.dump(
            _estimate_in_process(args.sheets, args.file_count,
                                 exhaustive=args.exhaustive,
                                 overlap_frac=child_overlap),
            sys.stdout,
        )
        return 0

    if not args.pdf:
        ap.error("--pdf is required (at least one)")

    # Child mode: run one arm and write its summary.
    if args._arm is not None:
        _run_arm_in_process(args.pdf, args._arm, exhaustive=args.exhaustive,
                            overlap_frac=child_overlap)
        return 0

    base_env = _parse_env(args.baseline)
    var_env = _parse_env(args.variant)
    try:
        base_overlap = parse_overlap(args.baseline_overlap, label="--baseline-overlap")
        var_overlap = parse_overlap(args.variant_overlap, label="--variant-overlap")
    except ValueError as exc:
        ap.error(str(exc))
    baseline = ArmSpec(env=base_env, overlap_frac=base_overlap)
    variant = ArmSpec(env=var_env, overlap_frac=var_overlap)

    # WP-06 §11.4. The guard used to compare whole environment dictionaries,
    # which fails in both directions: an irrelevant variable differing between
    # two shells defeated it, and an overlap-only experiment could not be
    # expressed at all, because overlap is not an environment variable. What
    # decides whether two arms are an experiment is the set of parameters this
    # harness actually varies — which is what ArmSpec.identity() is.
    if baseline.identity() == variant.identity():
        ap.error("--baseline and --variant resolve to the same reviewed "
                 "configuration, so both arms would run identically and the "
                 "comparison would measure nothing. Change a variable in "
                 "--variant, or give the arms different --*-overlap values.")

    missing = [p for p in args.pdf if not p.exists()]
    if missing:
        ap.error("no such file: " + ", ".join(str(p) for p in missing))

    if args.estimate:
        _estimate(args.pdf, [("baseline", baseline), ("variant", variant)],
                  exhaustive=args.exhaustive)
        return 0

    # Check before spawning. Both arms would otherwise die on the same
    # predictable, user-fixable condition after the parent has already printed
    # an arm header, which reads like the sweep itself broke.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set. This harness makes real API calls on "
            "real drawings — run with --estimate first to price both arms.",
            file=sys.stderr,
        )
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    base = run_arm("baseline", baseline.env, args.pdf, args.out,
                   exhaustive=args.exhaustive, overlap_frac=baseline.overlap_frac)
    var = run_arm("variant", variant.env, args.pdf, args.out,
                  exhaustive=args.exhaustive, overlap_frac=variant.overlap_frac)

    diff = diff_summaries(base, var)
    # Redacted: ``diff.txt`` is written to disk and shared, and the arm env is
    # whatever the user typed on the command line — which can include a key.
    # ``ArmSpec.label`` names the overlap too, so a geometry-only experiment is
    # not labelled "defaults" in the saved report.
    base_label = baseline.label()
    var_label = variant.label()
    report = render_diff(diff, base_label=base_label, var_label=var_label)
    print("\n" + report)

    (args.out / "diff.json").write_text(json.dumps(diff, indent=2), encoding="utf-8")
    (args.out / "diff.txt").write_text(report + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}/diff.json, diff.txt, arm_baseline.json, arm_variant.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
