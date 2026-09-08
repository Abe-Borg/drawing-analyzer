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
        "by_family": {
            fam: {"input": g["input_tokens"], "output": g["output_tokens"],
                  "calls": g["calls"]}
            for fam, g in (ru.by_family() if ru else {}).items()
        },
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


def _run_arm_in_process(pdfs: list[Path], out_path: Path, *, exhaustive: bool) -> None:
    """Execute one arm and write its summary. Runs inside the child process."""
    from drawing_analyzer.client import get_client
    from drawing_analyzer.cost import resolve_stage_models
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT
    from drawing_analyzer.digest_cache import DigestCache
    from drawing_analyzer.pipeline import extract_drawing_context

    use_batch, critique_use_batch = resolve_transport()

    with TemporaryDirectory(prefix="da-ab-arm-") as tmp:
        # A private cache per arm. Both arms are therefore cold, which is the
        # whole point: every cache key folds the model, so the arms could not
        # contaminate each other anyway — but a warm arm compared against a cold
        # one measures nothing.
        cache = DigestCache(Path(tmp) / "cache.json")
        ctx = extract_drawing_context(
            pdfs,
            client=get_client(),
            cache=cache,
            qc_markups=exhaustive,
            reference_audit=exhaustive,
            # Passed explicitly, at the value the runtime would have resolved
            # anyway, so the summary can record the transport it was actually
            # billed at and the estimate can be checked against it.
            use_batch=use_batch,
            critique_use_batch=critique_use_batch,
        )
        summary = summarize_run(ctx)

    summary["stage_models"] = vars(resolve_stage_models(model=REVIEW_MODEL_DEFAULT))
    summary["tile_target_px"] = os.environ.get("DRAWING_ANALYZER_TILE_TARGET_PX", "")
    summary["transport"] = {
        "digest_batch": use_batch, "critique_batch": critique_use_batch,
    }
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def run_arm(
    label: str, env: dict[str, str], pdfs: list[Path], out_dir: Path,
    *, exhaustive: bool,
) -> dict:
    """Run one arm in a subprocess and return its summary."""
    out_path = out_dir / f"arm_{label}.json"
    child_env = {**os.environ, **env}
    cmd = [
        sys.executable, str(Path(__file__).resolve()),
        "--_arm", str(out_path), "--exhaustive" if exhaustive else "--no-exhaustive",
        *[a for p in pdfs for a in ("--pdf", str(p))],
    ]
    print(f"[{label}] {' '.join(f'{k}={v}' for k, v in env.items()) or '(defaults)'}")
    proc = subprocess.run(cmd, env=child_env)
    if proc.returncode != 0:
        raise SystemExit(f"arm {label!r} failed with exit code {proc.returncode}")
    return json.loads(out_path.read_text(encoding="utf-8"))


def _estimate(pdfs: list[Path], arms: list[tuple[str, dict]], *, exhaustive: bool) -> None:
    """Price both arms before spending anything."""
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT
    from drawing_analyzer.cost import (
        estimate_drawing_set_cost,
        estimate_exhaustive_run_cost,
    )
    from drawing_analyzer.render import list_sheets

    sheets = len(list_sheets(pdfs))
    print(f"\n{sheets} sheet(s) across {len(pdfs)} file(s). Estimated per arm:\n")
    saved = dict(os.environ)
    try:
        for label, env in arms:
            os.environ.clear()
            os.environ.update({**saved, **env})
            # The transport the arm will actually run on, not the estimator's
            # default. Both default to real-time; quoting the batch rate here
            # would halve the two stages that dominate the bill.
            use_batch, critique_batch = resolve_transport()
            transport = "batch" if use_batch else "real-time"
            if exhaustive:
                est = estimate_exhaustive_run_cost(
                    sheets, file_count=len(pdfs), model=REVIEW_MODEL_DEFAULT,
                    batch=use_batch, critique_batch=critique_batch,
                )
                lo, hi = est.low_cost, est.high_cost
                money = "unavailable" if lo is None else f"${lo:,.2f} – ${hi:,.2f}"
            else:
                est = estimate_drawing_set_cost(
                    sheets, file_count=len(pdfs), model=REVIEW_MODEL_DEFAULT,
                    batch=use_batch,
                )
                money = ("unavailable" if est.total_cost is None
                         else f"${est.total_cost:,.2f}")
            print(f"  {label:<10}{money:<24}({transport})")
    finally:
        os.environ.clear()
        os.environ.update(saved)
    print("\nBoth arms run cold, so this is what each will actually cost.\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", action="append", type=Path, default=[],
                    help="a source PDF (repeatable)")
    ap.add_argument("--baseline", default="",
                    help="baseline arm env, NAME=VALUE[,NAME=VALUE] ('' = defaults)")
    ap.add_argument("--variant", default="",
                    help="variant arm env, NAME=VALUE[,NAME=VALUE]")
    ap.add_argument("--out", type=Path, default=Path("ab_out"))
    ap.add_argument("--exhaustive", action="store_true", default=True,
                    help="run the full QC stack (default)")
    ap.add_argument("--no-exhaustive", dest="exhaustive", action="store_false")
    ap.add_argument("--estimate", action="store_true",
                    help="price both arms and exit without spending anything")
    ap.add_argument("--_arm", type=Path, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if not args.pdf:
        ap.error("--pdf is required (at least one)")

    # Child mode: run one arm and write its summary.
    if args._arm is not None:
        _run_arm_in_process(args.pdf, args._arm, exhaustive=args.exhaustive)
        return 0

    base_env = _parse_env(args.baseline)
    var_env = _parse_env(args.variant)
    # Compare the effective environments, not just "is the variant non-empty".
    # ``--baseline X=1 --variant X=1`` is two identical billable runs, and an
    # empty variant is only the most obvious way to ask for one. What decides
    # the arms is the env each process ends up with, so that is what is checked.
    if {**os.environ, **base_env} == {**os.environ, **var_env}:
        ap.error("--baseline and --variant resolve to the same environment, so "
                 "both arms would run identically and the comparison would "
                 "measure nothing. Change at least one variable in --variant.")

    missing = [p for p in args.pdf if not p.exists()]
    if missing:
        ap.error("no such file: " + ", ".join(str(p) for p in missing))

    if args.estimate:
        _estimate(args.pdf, [("baseline", base_env), ("variant", var_env)],
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
    base = run_arm("baseline", base_env, args.pdf, args.out, exhaustive=args.exhaustive)
    var = run_arm("variant", var_env, args.pdf, args.out, exhaustive=args.exhaustive)

    diff = diff_summaries(base, var)
    base_label = ", ".join(f"{k}={v}" for k, v in base_env.items()) or "defaults"
    var_label = ", ".join(f"{k}={v}" for k, v in var_env.items())
    report = render_diff(diff, base_label=base_label, var_label=var_label)
    print("\n" + report)

    (args.out / "diff.json").write_text(json.dumps(diff, indent=2), encoding="utf-8")
    (args.out / "diff.txt").write_text(report + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}/diff.json, diff.txt, arm_baseline.json, arm_variant.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
