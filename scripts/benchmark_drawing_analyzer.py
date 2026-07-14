#!/usr/bin/env python3
"""Performance / memory / cost qualification harness (Phase 27, §19.7).

Measures the scenarios the release gate cares about and writes a
machine-readable ``benchmark_report.json`` plus a human ``benchmark_report.md``
into ``--out``. Repeated runs report **medians** (§19.7's regression tolerance
is judged on medians, never single runs).

Two modes:

**Offline (default; hermetic, free).** Builds a synthetic vector set and
answers every model call with a scripted in-process fake, so what is measured
is the analyzer itself: rendering, caching, anchoring, ledger, markup writing,
export. Scenarios: ``standard-cold``, ``standard-warm``, ``one-source-changed``,
``exhaustive-cold``, ``corrupt-partial``. With ``--check`` it enforces the
mechanical §19.7 gates:

- a warm unchanged run makes **zero** digest/critique API calls and performs
  **zero** full-sheet rasterizations;
- source hashing happens **once per source per run**, never once per page; and
- usage totals reconcile exactly to the per-record ledger.

**Live (``--live``, needs ``ANTHROPIC_API_KEY``; billable).** Runs the same
standard cold/warm pair — plus ``--exhaustive`` if asked — over the PDFs you
supply with ``--pdf``, recording real tokens by stage and the priced estimate.
Wall time is recorded descriptively (no latency gate, §19.7). Batch-transport
economics are validated separately by the live canary / a real batch run —
this harness does not wait out a Message Batch.

    python scripts/benchmark_drawing_analyzer.py --check
    python scripts/benchmark_drawing_analyzer.py --sheets 12 --repeats 5
    python scripts/benchmark_drawing_analyzer.py --live --pdf a.pdf --pdf b.pdf
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

_PAGE_W, _PAGE_H = 792.0, 612.0


# --------------------------------------------------------------------------- #
# Peak-RSS sampling (best effort per platform; process-wide high-water mark)
# --------------------------------------------------------------------------- #


def _peak_rss_mb() -> float | None:
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB; macOS reports bytes.
        return round(peak / 1024.0, 1) if sys.platform != "darwin" else round(peak / (1024.0 * 1024.0), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil  # type: ignore[import-not-found]

        return round(psutil.Process().memory_info().rss / (1024.0 * 1024.0), 1)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Offline fixtures: synthetic set + scripted client
# --------------------------------------------------------------------------- #


def _build_offline_set(root: Path, sheets: int) -> list[Path]:
    import pymupdf

    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i in range(sheets):
        doc = pymupdf.open()
        page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
        page.insert_text((72, 100), f"EQUIPMENT TAG EQ-{i:03d} SERVES ZONE {i}")
        page.insert_text((72, 128), "GENERAL NOTES AND SCHEDULE")
        page.insert_text((_PAGE_W - 150, _PAGE_H - 60), f"M-{100 + i}", fontsize=12)
        path = root / f"M-{100 + i}.pdf"
        doc.save(str(path))
        doc.close()
        paths.append(path)
    return paths


class _Blocks:
    """Minimal SDK-shaped response objects (attribute access only)."""

    class Text:
        type = "text"

        def __init__(self, text: str) -> None:
            self.text = text

    class Usage:
        def __init__(self, i: int, o: int) -> None:
            self.input_tokens = i
            self.output_tokens = o
            self.cache_creation_input_tokens = 0
            self.cache_read_input_tokens = 0

    class Message:
        stop_reason = "end_turn"
        model = "claude-opus-4-8"

        def __init__(self, text: str, i: int, o: int) -> None:
            self.content = [_Blocks.Text(text)]
            self.usage = _Blocks.Usage(i, o)


class OfflineClient:
    """Answers every stage with small valid output; counts digest/critique calls."""

    def __init__(self) -> None:
        self.digest_calls = 0
        self.critique_calls = 0
        outer = self

        class _Msgs:
            def create(_self, **kw):  # noqa: ANN001, ANN202
                from drawing_analyzer.citation_check import CITATION_SYSTEM_PROMPT
                from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT
                from drawing_analyzer.cross_qc import CROSS_QC_SYSTEM_PROMPT
                from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT
                from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT

                system = str(kw.get("system", ""))
                if system == VERIFY_SYSTEM_PROMPT:
                    return _Blocks.Message('{"verdict":"CONFIRMED","note":"x"}', 40, 8)
                if system.startswith(CRITIQUE_SYSTEM_PROMPT):
                    outer.critique_calls += 1
                    return _Blocks.Message('```json\n{"findings":[]}\n```', 400, 20)
                if system.startswith(CROSS_QC_SYSTEM_PROMPT):
                    return _Blocks.Message('```json\n{"findings":[],"claims":[]}\n```', 800, 20)
                if system.startswith(CITATION_SYSTEM_PROMPT):
                    return _Blocks.Message(
                        '```json\n{"status":"CHECKED_SUPPORTS","note":"n","edition_notes":"e"}\n```',
                        20, 8,
                    )
                if system.startswith(DIGEST_SYSTEM_PROMPT):
                    outer.digest_calls += 1
                    body = (
                        "Sheet - Mechanical - Plan\nEquipment schedule reviewed."
                        '\n\n```json\n{"findings":[]}\n```'
                    )
                    return _Blocks.Message(body, 500, 90)
                return _Blocks.Message("Overview.", 100, 20)   # synthesis / focus

        self.messages = _Msgs()


class _Instrumentation:
    """Counts full-sheet rasterizations and per-source content hashes."""

    def __init__(self) -> None:
        self.renders = 0
        self.hash_calls: list[str] = []

    def __enter__(self) -> "_Instrumentation":
        import drawing_analyzer.render as render_mod
        import drawing_analyzer.source_registry as sr_mod

        self._render_mod, self._sr_mod = render_mod, sr_mod
        self._real_render = render_mod.render_sheet
        self._real_hash = sr_mod.content_sha256

        def _render(*a, **k):
            self.renders += 1
            return self._real_render(*a, **k)

        def _hash(path, *a, **k):
            self.hash_calls.append(str(path))
            return self._real_hash(path, *a, **k)

        render_mod.render_sheet = _render
        sr_mod.content_sha256 = _hash
        return self

    def __exit__(self, *exc) -> None:
        self._render_mod.render_sheet = self._real_render
        self._sr_mod.content_sha256 = self._real_hash


# --------------------------------------------------------------------------- #
# Scenario runner
# --------------------------------------------------------------------------- #


def _usage_summary(ctx) -> dict:
    ru = ctx.run_usage
    fams = {
        fam: {"input": g["input_tokens"], "output": g["output_tokens"]}
        for fam, g in (ru.by_family() if ru else {}).items()
    }
    cost = ctx.total_estimated_cost
    return {
        "families": fams,
        "total_input_tokens": ctx.total_input_tokens,
        "total_output_tokens": ctx.total_output_tokens,
        "cache_hits": ru.cache_hits if ru else 0,
        "estimated_cost_usd": None if cost is None else float(cost),
        "ledger_reconciles": (
            ctx.total_input_tokens == sum(r.input_tokens for r in ru.records)
            and ctx.total_output_tokens == sum(r.output_tokens for r in ru.records)
        ) if ru else None,
    }


def _run_scenario(name: str, fn, repeats: int) -> dict:
    walls: list[float] = []
    detail: dict = {}
    for i in range(repeats):
        t0 = time.perf_counter()
        detail = fn(i)
        walls.append(round(time.perf_counter() - t0, 3))
    return {
        "scenario": name,
        "repeats": repeats,
        "wall_s": walls,
        "wall_median_s": round(statistics.median(walls), 3),
        "peak_rss_mb": _peak_rss_mb(),
        **detail,
    }


def _offline_scenarios(sheets: int, repeats: int, check: bool) -> tuple[list[dict], list[str]]:
    from drawing_analyzer.digest_cache import DigestCache
    from drawing_analyzer.pipeline import extract_drawing_context

    failures: list[str] = []
    results: list[dict] = []

    with TemporaryDirectory(prefix="da-bench-") as tmp_s:
        tmp = Path(tmp_s)
        paths = _build_offline_set(tmp / "set", sheets)
        n_sources = len(paths)

        def _standard(client, cache, tag):
            with _Instrumentation() as inst:
                ctx = extract_drawing_context(paths, client=client, rows=2, cols=2,
                                              cache=cache)
            per_source = {}
            for p in inst.hash_calls:
                per_source[p] = per_source.get(p, 0) + 1
            return ctx, inst, per_source

        # 1. standard cold (fresh cache each repeat)
        def _cold(_i):
            client = OfflineClient()
            ctx, inst, per_source = _standard(client, DigestCache(None, persist=False), "cold")
            if check and per_source and max(per_source.values()) > 1:
                failures.append("standard-cold: a source was content-hashed more than once")
            return {"digest_api_calls": client.digest_calls, "renders": inst.renders,
                    "usage": _usage_summary(ctx)}

        results.append(_run_scenario("standard-cold", _cold, repeats))

        # 2. warm unchanged (persistent cache, shared across repeats)
        warm_cache = DigestCache(tmp / "bench_cache.json")
        seed_client = OfflineClient()
        _standard(seed_client, warm_cache, "seed")

        def _warm(_i):
            client = OfflineClient()
            ctx, inst, _ = _standard(client, warm_cache, "warm")
            if check:
                if client.digest_calls or client.critique_calls:
                    failures.append("standard-warm: cached run still made API calls")
                if inst.renders:
                    failures.append("standard-warm: cached run still rasterized")
            return {"digest_api_calls": client.digest_calls, "renders": inst.renders,
                    "cache_hits": ctx.run_usage.cache_hits if ctx.run_usage else 0,
                    "usage": _usage_summary(ctx)}

        results.append(_run_scenario("standard-warm", _warm, repeats))

        # 3. one source changed in a warm set
        def _mutated(i):
            import pymupdf

            doc = pymupdf.open()
            page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
            page.insert_text((72, 100), f"REVISED CONTENT PASS {i}")
            page.insert_text((_PAGE_W - 150, _PAGE_H - 60), "M-100", fontsize=12)
            doc.save(str(paths[0]))
            doc.close()
            client = OfflineClient()
            ctx, inst, _ = _standard(client, warm_cache, "mutated")
            if check and client.digest_calls != 1:
                failures.append(
                    f"one-source-changed: expected exactly 1 digest call, got {client.digest_calls}"
                )
            return {"digest_api_calls": client.digest_calls, "renders": inst.renders,
                    "usage": _usage_summary(ctx)}

        results.append(_run_scenario("one-source-changed", _mutated, repeats))

        # 4. full exhaustive QC, cold (markups + evidence under a work dir)
        def _exhaustive(i):
            client = OfflineClient()
            with _Instrumentation() as inst:
                ctx = extract_drawing_context(
                    paths, client=client, rows=2, cols=2,
                    reference_audit=True, qc_markups=True,
                    qc_work_dir=tmp / f"qc{i}",
                )
            summary = _usage_summary(ctx)
            if check and summary["ledger_reconciles"] is False:
                failures.append("exhaustive-cold: usage totals do not reconcile to records")
            return {"qc_status": ctx.qc_status, "coverage": ctx.coverage_status,
                    "findings": ctx.finding_count, "renders": inst.renders,
                    "usage": summary}

        results.append(_run_scenario("exhaustive-cold", _exhaustive, repeats))

        # 5. partial set with a corrupt file (resilience cost)
        corrupt = tmp / "set" / "corrupt.pdf"
        corrupt.write_bytes(b"%PDF-1.7 not a pdf")

        def _partial(_i):
            client = OfflineClient()
            ctx = extract_drawing_context([*paths, corrupt], client=client, rows=2, cols=2)
            return {"ok_sheets": ctx.ok_sheet_count, "errors": len(ctx.errors),
                    "usage": _usage_summary(ctx)}

        results.append(_run_scenario("corrupt-partial", _partial, repeats))

    return results, failures


def _live_scenarios(pdfs: list[Path], repeats: int, exhaustive: bool) -> list[dict]:
    from drawing_analyzer.client import get_client
    from drawing_analyzer.digest_cache import DigestCache
    from drawing_analyzer.pipeline import extract_drawing_context

    client = get_client()
    results: list[dict] = []
    with TemporaryDirectory(prefix="da-bench-live-") as tmp_s:
        tmp = Path(tmp_s)
        cache = DigestCache(tmp / "live_cache.json")

        def _std(_i):
            ctx = extract_drawing_context(pdfs, client=client, cache=cache)
            return {"ok_sheets": ctx.ok_sheet_count, "usage": _usage_summary(ctx)}

        results.append(_run_scenario("live-standard-cold", _std, 1))
        results.append(_run_scenario("live-standard-warm", _std, repeats))
        if exhaustive:
            def _exh(_i):
                ctx = extract_drawing_context(
                    pdfs, client=client, cache=cache,
                    reference_audit=True, qc_markups=True, qc_work_dir=tmp / "qc",
                )
                return {"qc_status": ctx.qc_status, "findings": ctx.finding_count,
                        "usage": _usage_summary(ctx)}

            results.append(_run_scenario("live-exhaustive", _exh, 1))
    return results


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def _environment() -> dict:
    from drawing_analyzer.run_journal import collect_environment

    env = dict(collect_environment())
    env.update({
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    })
    return env


def _render_md(report: dict) -> str:
    lines = [
        "# Drawing Analyzer benchmark report",
        "",
        f"Generated: {report['generated_at']}  |  mode: {report['mode']}",
        "",
        "Environment: " + ", ".join(f"{k}={v}" for k, v in sorted(report["environment"].items())),
        "",
        "| scenario | median wall (s) | walls (s) | notes |",
        "|---|---:|---|---|",
    ]
    for s in report["scenarios"]:
        notes = []
        for key in ("digest_api_calls", "renders", "cache_hits", "qc_status",
                    "coverage", "findings", "ok_sheets", "errors"):
            if key in s:
                notes.append(f"{key}={s[key]}")
        usage = s.get("usage") or {}
        if usage.get("estimated_cost_usd") is not None:
            notes.append(f"cost≈${usage['estimated_cost_usd']:.4f}")
        notes.append(f"tok={usage.get('total_input_tokens', 0)}/{usage.get('total_output_tokens', 0)}")
        lines.append(
            f"| {s['scenario']} | {s['wall_median_s']} | "
            f"{', '.join(str(w) for w in s['wall_s'])} | {'; '.join(notes)} |"
        )
    lines += ["", f"Peak RSS (process high-water mark): {report['peak_rss_mb']} MB", ""]
    if report["gate_failures"]:
        lines += ["## GATE FAILURES", ""] + [f"- {f}" for f in report["gate_failures"]]
    else:
        lines += ["Mechanical gates: PASS (or not requested — see `--check`)."]
    lines += [
        "",
        "Record these numbers (medians) in docs/PERFORMANCE_AND_COST_VALIDATION.md "
        "against the owner-approved regression tolerance.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="§19.7 benchmark harness")
    parser.add_argument("--sheets", type=int, default=8, help="offline synthetic sheet count")
    parser.add_argument("--repeats", type=int, default=3, help="repeats per scenario (medians)")
    parser.add_argument("--check", action="store_true", help="enforce the mechanical gates")
    parser.add_argument("--live", action="store_true", help="run live scenarios (billable)")
    parser.add_argument("--exhaustive", action="store_true",
                        help="with --live: also run one exhaustive QC pass")
    parser.add_argument("--pdf", action="append", type=Path, default=[],
                        help="with --live: input PDF (repeatable)")
    parser.add_argument("--out", type=Path, default=Path("benchmark_out"))
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if args.live:
        if not args.pdf:
            parser.error("--live needs at least one --pdf")
        scenarios = _live_scenarios(args.pdf, args.repeats, args.exhaustive)
        failures: list[str] = []
        mode = "live"
    else:
        scenarios, failures = _offline_scenarios(args.sheets, args.repeats, args.check)
        mode = "offline"

    report = {
        "generated_at": started,
        "mode": mode,
        "environment": _environment(),
        "scenarios": scenarios,
        "peak_rss_mb": _peak_rss_mb(),
        "gate_failures": failures,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "benchmark_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    (args.out / "benchmark_report.md").write_text(_render_md(report), encoding="utf-8")
    print(_render_md(report))
    print(f"Wrote {args.out / 'benchmark_report.json'} and .md")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
