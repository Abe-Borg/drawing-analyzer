#!/usr/bin/env python3
"""WP-02 §7.1 — measure evidence coverage over a drawing set. Zero API calls.

Sizes the three grounding failures of `docs/REVIEW_IMPLEMENTATION_PLAN.md` §2.1
before anything is engineered against them, using only PDFs on disk and (when
given) artifacts a run already exported. No model call, no key, no budget
approval, no rasterization: the page scan is the existing pre-render pass
(`render.iter_sheet_prescan`), which lifts the text layer and page size from
page-object access alone.

    python scripts/measure_evidence_coverage.py --pdf SET.pdf
    python scripts/measure_evidence_coverage.py --pdf a.pdf --pdf b.pdf \\
        --export-dir path/to/export --json coverage.json

What it answers, and what it deliberately does not:

- **Trigger 1 (text past the cap)** — exactly, per sheet. `text_chars_total`
  carries the pre-cap length, so a 15,100-character sheet is distinguishable
  from a 60,000-character one.
- **Trigger 2 (text absent from the layer)** — the textless population exactly,
  and the *hybrid* population approximately: see `classify_sheet`.
- **Trigger 3 (no quote at all)** — **not measurable here.** It is a property of
  what a model returned, not of the source. §7.2's counters measure it, and
  that needs one budgeted run.
- **Discard rate** — likewise not measurable here. What this script reports from
  an export is the anchor-tier spread over findings that *survived*; the ones
  the host dropped left no trace. Never read the former as the latter (§7.3).

Every number is a count or a dimension. No source text, no absolute path, and
no credential ever reaches the output.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from drawing_analyzer import tiling  # noqa: E402
from drawing_analyzer.auditors.references import detect_sheet_id  # noqa: E402
from drawing_analyzer.cross_qc import (  # noqa: E402
    MAX_SHEETS_SINGLE_CALL,
    _TEXT_LAYER_BUDGET,
)
from drawing_analyzer.render import SHEET_TEXT_MAX_CHARS  # noqa: E402

# A sheet with words is called *hybrid* when at least this fraction of its grid
# tiles contain no extractable word at all. Deliberately crude and stated in the
# output: a sparsely-labelled plan view scores like a pasted raster detail, and
# only pixels can tell them apart. The per-sheet ``word_free_tiles`` is reported
# raw so a reader can re-threshold without re-running.
HYBRID_WORD_FREE_TILE_FRACTION = 0.5


@dataclass
class SheetCoverage:
    """Per-sheet evidence facts. Counts and dimensions only."""

    source_id: str
    page_index: int
    sheet_id: str
    width_pt: float
    height_pt: float
    word_count: int
    text_chars_total: int
    text_chars_in_prompt: int
    truncated: bool
    chars_past_cap: int
    total_tiles: int
    word_free_tiles: int
    word_free_fraction: float
    classification: str
    over_cross_qc_budget: bool
    cross_qc_chars_omitted: int


@dataclass
class SetCoverage:
    """Set roll-up plus the per-sheet rows it was derived from."""

    sheets: list[SheetCoverage] = field(default_factory=list)
    grid_rows: int = tiling.DEFAULT_GRID_ROWS
    grid_cols: int = tiling.DEFAULT_GRID_COLS
    sheet_text_cap: int = SHEET_TEXT_MAX_CHARS
    cross_qc_text_budget: int = _TEXT_LAYER_BUDGET
    shard_threshold: int = MAX_SHEETS_SINGLE_CALL
    hybrid_word_free_tile_fraction: float = HYBRID_WORD_FREE_TILE_FRACTION
    unreadable_sources: list[str] = field(default_factory=list)

    # ---- roll-ups (derived; see ``summarize``) ----

    @property
    def classification_counts(self) -> dict[str, int]:
        return dict(Counter(s.classification for s in self.sheets))

    @property
    def truncated_sheets(self) -> int:
        return sum(1 for s in self.sheets if s.truncated)

    @property
    def chars_past_cap(self) -> int:
        return sum(s.chars_past_cap for s in self.sheets)

    @property
    def sheets_over_cross_qc_budget(self) -> int:
        return sum(1 for s in self.sheets if s.over_cross_qc_budget)

    @property
    def cross_qc_chars_offered(self) -> int:
        return sum(s.text_chars_in_prompt for s in self.sheets)

    @property
    def cross_qc_chars_omitted(self) -> int:
        return sum(s.cross_qc_chars_omitted for s in self.sheets)

    @property
    def word_free_fraction_deciles(self) -> dict[str, int]:
        """How many sheets fall in each 10% band of word-free tiles.

        The honest form of the hybrid question: a threshold picks one cut
        through this distribution, and a reader can pick a different one
        without re-running the scan.
        """
        bands: Counter = Counter()
        for s in self.sheets:
            lo = min(9, int(s.word_free_fraction * 10))
            bands[f"{lo * 10}-{lo * 10 + 10}%"] += 1
        return {k: bands[k] for k in sorted(bands, key=lambda b: int(b.split("-")[0]))}

    @property
    def takes_sharded_path(self) -> bool:
        """Upper-bound answer: a failed or empty digest reduces the real count.

        ``cross_sheet_qc`` shards on *retained readable entries* — sheets whose
        digest succeeded and returned non-empty text. That is unknowable before
        a run, so this uses the page count as the ceiling and says so.
        """
        return len(self.sheets) > self.shard_threshold


def _tile_rects(width_pt: float, height_pt: float, rows: int, cols: int, overlap: float):
    try:
        return tiling.tile_rects(
            width_pt, height_pt, rows=rows, cols=cols, overlap_frac=overlap
        )
    except ValueError:          # degenerate page size — no grid to speak of
        return []


def count_word_free_tiles(geom) -> tuple[int, int]:
    """``(word_free_tiles, total_tiles)`` for one sheet's grid.

    A tile counts as word-free when no extracted word rectangle intersects it.
    Tiles overlap, so a word can belong to several; that only makes this a
    *conservative* count of the regions where the model has nothing but pixels.
    """
    rows = int(getattr(geom, "rows", 0) or 0)
    cols = int(getattr(geom, "cols", 0) or 0)
    rects = _tile_rects(
        float(getattr(geom, "page_width_pt", 0.0) or 0.0),
        float(getattr(geom, "page_height_pt", 0.0) or 0.0),
        rows or tiling.DEFAULT_GRID_ROWS,
        cols or tiling.DEFAULT_GRID_COLS,
        float(getattr(geom, "overlap_frac", tiling.DEFAULT_OVERLAP_FRAC)),
    )
    if not rects:
        return 0, 0
    words = list(getattr(geom, "words", []) or [])
    boxes = []
    for w in words:
        try:
            boxes.append((float(w[0]), float(w[1]), float(w[2]), float(w[3])))
        except (TypeError, ValueError, IndexError):
            continue            # a malformed word tuple is simply not counted
    free = 0
    for tr in rects:
        if not any(
            x0 < tr.x1 and x1 > tr.x0 and y0 < tr.y1 and y1 > tr.y0
            for (x0, y0, x1, y1) in boxes
        ):
            free += 1
    return free, len(rects)


def classify_sheet(
    word_count: int, word_free_tiles: int, total_tiles: int,
    hybrid_threshold: float = HYBRID_WORD_FREE_TILE_FRACTION,
) -> str:
    """``"textless"`` / ``"hybrid"`` / ``"vector"`` — approximate, by design.

    ``textless`` is exact and decidable. ``hybrid`` is a **judgement call on a
    threshold**: a plan view whose labels cluster in the title block and notes
    column scores like a sheet with a pasted raster detail, because from the
    text layer alone they are the same thing. Do not lean on this bucket
    without looking at ``word_free_fraction_deciles`` in the same report, which
    shows the whole distribution and makes the cutoff re-choosable after the
    fact (or pass ``--hybrid-threshold``).

    ``is_raster`` alone cannot answer any of this (§2.1): a hybrid sheet has
    words, so it is not raster, and its pasted detail is still invisible to a
    text check.
    """
    if word_count == 0:
        return "textless"
    if total_tiles and word_free_tiles / total_tiles >= hybrid_threshold:
        return "hybrid"
    return "vector"


def scan_sheets(
    pdf_paths: list[Path],
    hybrid_threshold: float = HYBRID_WORD_FREE_TILE_FRACTION,
) -> SetCoverage:
    """Walk every page with the existing no-render prescan. Never rasterizes."""
    from drawing_analyzer.render import iter_sheet_prescan

    out = SetCoverage(hybrid_word_free_tile_fraction=hybrid_threshold)
    try:
        scanned = list(iter_sheet_prescan(pdf_paths))
    except Exception as exc:    # noqa: BLE001 - report, never crash the measurement
        out.unreadable_sources.append(f"{type(exc).__name__}: {exc}")
        return out

    for ref, _identity, geom in scanned:
        total_chars = getattr(geom, "text_chars_total", None)
        prompt_chars = len(getattr(geom, "sheet_text", "") or "")
        if total_chars is None:  # older geometry: fall back, and do not invent
            total_chars = prompt_chars
        words = list(getattr(geom, "words", []) or [])
        free, total_tiles = count_word_free_tiles(geom)
        offered = min(prompt_chars, total_chars)
        out.sheets.append(SheetCoverage(
            source_id=str(getattr(ref, "source_id", "") or ""),
            page_index=int(getattr(ref, "page_index", 0) or 0),
            sheet_id=detect_sheet_id(geom) or "",
            width_pt=round(float(getattr(geom, "page_width_pt", 0.0) or 0.0), 2),
            height_pt=round(float(getattr(geom, "page_height_pt", 0.0) or 0.0), 2),
            word_count=len(words),
            text_chars_total=int(total_chars),
            text_chars_in_prompt=prompt_chars,
            truncated=total_chars > SHEET_TEXT_MAX_CHARS,
            chars_past_cap=max(0, int(total_chars) - SHEET_TEXT_MAX_CHARS),
            total_tiles=total_tiles,
            word_free_tiles=free,
            word_free_fraction=round(free / total_tiles, 3) if total_tiles else 0.0,
            classification=classify_sheet(
                len(words), free, total_tiles, hybrid_threshold),
            over_cross_qc_budget=offered > _TEXT_LAYER_BUDGET,
            cross_qc_chars_omitted=max(0, offered - _TEXT_LAYER_BUDGET),
        ))
    return out


# --------------------------------------------------------------------------- #
# Optional: surviving-finding locatability from a run that already happened
# --------------------------------------------------------------------------- #


def read_surviving_findings(export_dir: Path) -> dict:
    """Anchor-tier spread over *kept* cross-sheet findings (§7.1 item 5).

    This is **not** the discard rate. Findings the host dropped for failing
    grounding never reached ``findings.json``; only §7.2's counters see them.
    """
    result: dict = {
        "available": False,
        "note": "anchor tiers over findings that SURVIVED; not a discard rate",
    }
    findings_path = Path(export_dir) / "findings.json"
    if not findings_path.is_file():
        result["error"] = "findings.json not found in export dir"
        return result
    try:
        rows = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if not isinstance(rows, list):
        result["error"] = "findings.json is not a list"
        return result

    primary_tiers: Counter = Counter()
    leg_tiers: Counter = Counter()
    with_quote = without_quote = legs = 0
    cross_sheet = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        also_on = row.get("also_on") or []
        is_cross = bool(also_on) or "cross_qc" in (row.get("sources") or [])
        if not is_cross:
            continue
        cross_sheet += 1
        anchor = row.get("anchor") or {}
        primary_tiers[str(anchor.get("status", "UNANCHORED"))] += 1
        if str(row.get("source_quote", "") or "").strip():
            with_quote += 1
        else:
            without_quote += 1
        for leg in also_on:
            if not isinstance(leg, dict):
                continue
            legs += 1
            leg_anchor = leg.get("anchor") or {}
            leg_tiers[str(leg_anchor.get("status", "UNANCHORED"))] += 1

    result.update({
        "available": True,
        "cross_sheet_findings": cross_sheet,
        "primary_anchor_tiers": dict(primary_tiers),
        "leg_anchor_tiers": dict(leg_tiers),
        "legs": legs,
        "with_source_quote": with_quote,
        "without_source_quote": without_quote,
    })
    return result


def read_run_completeness(export_dir: Path) -> dict:
    """The §7.1 item 6 fields a run already recorded, if the manifest is there."""
    manifest = Path(export_dir) / "run_manifest.json"
    if not manifest.is_file():
        return {"available": False, "error": "run_manifest.json not found"}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    keep = ("status", "qc_status", "coverage_status")
    out = {"available": True}
    out.update({k: payload.get(k) for k in keep if k in payload})
    stages = payload.get("stages")
    if isinstance(stages, dict) and "cross_qc" in stages:
        out["cross_qc_stage"] = stages["cross_qc"]
    elif isinstance(stages, list):
        out["cross_qc_stage"] = next(
            (s for s in stages
             if isinstance(s, dict) and s.get("name") == "cross_qc"),
            None,
        )
    return out


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def summarize(cov: SetCoverage, findings: dict | None, completeness: dict | None) -> dict:
    return {
        "tier": "7.1 zero-call",
        "constants": {
            "sheet_text_cap": cov.sheet_text_cap,
            "cross_qc_text_budget": cov.cross_qc_text_budget,
            "shard_threshold": cov.shard_threshold,
            "grid": f"{cov.grid_rows}x{cov.grid_cols}",
            "hybrid_word_free_tile_fraction": cov.hybrid_word_free_tile_fraction,
        },
        "set": {
            "pages": len(cov.sheets),
            "classification": cov.classification_counts,
            "word_free_fraction_deciles": cov.word_free_fraction_deciles,
            "truncated_sheets": cov.truncated_sheets,
            "chars_past_cap": cov.chars_past_cap,
            "sheets_over_cross_qc_budget": cov.sheets_over_cross_qc_budget,
            "cross_qc_chars_offered": cov.cross_qc_chars_offered,
            "cross_qc_chars_omitted": cov.cross_qc_chars_omitted,
            "takes_sharded_path_upper_bound": cov.takes_sharded_path,
            "unreadable_sources": cov.unreadable_sources,
        },
        "sheets": [asdict(s) for s in cov.sheets],
        "surviving_findings": findings or {"available": False},
        "run_completeness": completeness or {"available": False},
        "not_measured_here": {
            "discard_rate": (
                "requires WP-02 §7.2 counters plus one budgeted sharded run; "
                "dropped legs and facts leave no trace in any stored artifact"
            ),
            "trigger_3_no_quote_legs": (
                "a property of model output, not of the source; §7.2 only"
            ),
        },
    }


def render_text(report: dict) -> str:
    s, c = report["set"], report["constants"]
    lines = [
        "WP-02 §7.1 evidence coverage (zero-call)",
        "=" * 58,
        f"pages scanned            {s['pages']}",
        f"classification           {s['classification'] or '{}'}",
        f"  (hybrid = >= {c['hybrid_word_free_tile_fraction']:.0%} of {c['grid']} tiles hold no word;",
        "   a threshold, not a fact — see the distribution below)",
        f"word-free tiles per sheet {s['word_free_fraction_deciles'] or '{}'}",
        "",
        f"trigger 1 — text past the {c['sheet_text_cap']:,}-char cap",
        f"  sheets truncated       {s['truncated_sheets']}",
        f"  characters past cap    {s['chars_past_cap']:,}",
        "",
        f"cross-QC {c['cross_qc_text_budget']:,}-char per-sheet text budget",
        f"  sheets over budget     {s['sheets_over_cross_qc_budget']}",
        f"  chars offered          {s['cross_qc_chars_offered']:,}",
        f"  chars omitted          {s['cross_qc_chars_omitted']:,}",
        "",
        f"sharded path (> {c['shard_threshold']} retained entries)",
        f"  page-count upper bound {s['takes_sharded_path_upper_bound']}"
        "   (a failed/empty digest lowers the real count)",
    ]
    if s["unreadable_sources"]:
        lines += ["", "unreadable sources:"] + [f"  {e}" for e in s["unreadable_sources"]]

    f = report["surviving_findings"]
    lines += ["", "surviving cross-sheet findings (from --export-dir)"]
    if not f.get("available"):
        lines.append(f"  unavailable: {f.get('error', 'no export dir given')}")
    else:
        lines += [
            f"  cross-sheet findings   {f['cross_sheet_findings']}",
            f"  primary anchor tiers   {f['primary_anchor_tiers']}",
            f"  leg anchor tiers       {f['leg_anchor_tiers']} over {f['legs']} leg(s)",
            f"  with / without quote   {f['with_source_quote']} / {f['without_source_quote']}",
            "  NOTE: survivors only — this is not the discard rate.",
        ]
    lines += [
        "",
        "not measured here (needs §7.2: counters + one budgeted run):",
        "  - grounding discard rate (legs/facts the host dropped)",
        "  - trigger 3, legs accepted with no quote at all",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pdf", action="append", type=Path, default=[],
                    help="a source PDF (repeatable)")
    ap.add_argument("--export-dir", type=Path, default=None,
                    help="an existing run's export folder (findings.json, "
                         "run_manifest.json) for the survivor roll-up")
    ap.add_argument("--hybrid-threshold", type=float,
                    default=HYBRID_WORD_FREE_TILE_FRACTION,
                    help="fraction of word-free tiles at which a sheet with "
                         f"words is called hybrid (default "
                         f"{HYBRID_WORD_FREE_TILE_FRACTION})")
    ap.add_argument("--json", type=Path, default=None,
                    help="also write the full report as JSON here")
    args = ap.parse_args(argv)

    if not args.pdf:
        ap.error("at least one --pdf is required")

    if not 0.0 <= args.hybrid_threshold <= 1.0:
        ap.error("--hybrid-threshold must be between 0.0 and 1.0")
    cov = scan_sheets([Path(p) for p in args.pdf], args.hybrid_threshold)
    findings = read_surviving_findings(args.export_dir) if args.export_dir else None
    completeness = read_run_completeness(args.export_dir) if args.export_dir else None
    report = summarize(cov, findings, completeness)

    print(render_text(report))
    if args.json:
        args.json.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nJSON report: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
