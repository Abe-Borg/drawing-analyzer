#!/usr/bin/env python3
"""Compare a baseline export with a prompt-experiment export (F2 / F3).

The prompt experiments in ``src/drawing_analyzer/prompt_experiments.py`` are
adopted only if, on the same drawings, the variant shows **fewer unanchored or
malformed findings without a rise in total findings**. This reads two export
folders (``write_drawing_export`` output, QC on) and prints those numbers side
by side:

- total findings, and findings per channel (digest, critique, cross-QC, ...);
- anchor outcome: EXACT / FUZZY / TILE / UNANCHORED, and the share of findings
  that **carry a quote** yet anchored nowhere (the hallucinated-quote signal);
- digest findings-block drift: sheets whose parser note reports a problem, and
  findings the parser dropped as invalid (from ``diagnostics/events.csv``).

Both exports must come from the same inputs; it refuses otherwise. The arms
can share a digest cache: an arm re-keys exactly the stages its prompts change,
so neither replays the other's results, and a stage it leaves alone (the digest
under the critique example alone) is reused, which keeps the difference to
what the experiment changed.

    python scripts/compare_prompt_experiment.py BASELINE_DIR VARIANT_DIR
    python scripts/compare_prompt_experiment.py BASELINE_DIR VARIANT_DIR --json

Zero API calls; reads JSON and CSV only.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ANCHOR_STATUSES = ("EXACT", "FUZZY", "TILE", "UNANCHORED")
_DROPPED_RE = re.compile(r"dropped (\d+) invalid finding")
_RUN_SUFFIX_RE = re.compile(r"_\d+$")


def _channel(tag: str) -> str:
    """``critique_2`` and ``critique_1`` are one channel; other tags as written."""
    return _RUN_SUFFIX_RE.sub("", tag) or "unknown"


def _sources(manifest: dict) -> list[tuple]:
    return sorted(
        (s.get("display_name", ""), s.get("page_count", 0), s.get("byte_size", 0))
        for s in manifest.get("sources") or []
    )


def _digest_drift(folder: Path) -> tuple[int, int]:
    """``(sheets with a findings-parser note, findings dropped as invalid)``."""
    path = folder / "diagnostics" / "events.csv"
    if not path.is_file():
        return 0, 0
    sheets = dropped = 0
    with open(path, encoding="utf-8-sig", newline="") as fp:
        for row in csv.DictReader(fp):
            if row.get("event_code") != "SHEET_DIGESTED":
                continue
            fields = row.get("fields") or ""
            if "parser_note=" not in fields:
                continue
            sheets += 1
            dropped += sum(int(n) for n in _DROPPED_RE.findall(fields))
    return sheets, dropped


def load_arm(folder: Path) -> dict:
    """The comparison metrics for one export folder."""
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    findings_path = folder / "findings.json"
    if not findings_path.is_file():
        raise SystemExit(f"{folder}: no findings.json — export a run with QC enabled")
    findings = json.loads(findings_path.read_text(encoding="utf-8")).get("findings") or []
    environment = (manifest.get("run") or {}).get("environment") or {}
    anchors = Counter()
    channels = Counter()
    quoted = quoted_unanchored = 0
    for f in findings:
        status = str(((f.get("anchor") or {}).get("status")) or "UNANCHORED")
        anchors[status] += 1
        if (f.get("source_quote") or "").strip():
            quoted += 1
            quoted_unanchored += status == "UNANCHORED"
        for tag in {_channel(str(t)) for t in f.get("sources") or []} or {"unknown"}:
            channels[tag] += 1
    drift_sheets, dropped = _digest_drift(folder)
    return {
        "folder": str(folder),
        "experiments": environment.get("prompt_experiments", "none"),
        "sources": _sources(manifest),
        "findings": len(findings),
        "channels": dict(sorted(channels.items())),
        "anchors": {s: anchors.get(s, 0) for s in ANCHOR_STATUSES},
        "quoted": quoted,
        "quoted_unanchored": quoted_unanchored,
        "quoted_unanchored_rate": (quoted_unanchored / quoted) if quoted else 0.0,
        "digest_drift_sheets": drift_sheets,
        "digest_dropped_invalid": dropped,
    }


def verdict(base: dict, variant: dict) -> tuple[str, list[str]]:
    """The adoption rule, read literally: fewer unanchored or malformed, no more findings."""
    reasons: list[str] = []
    if variant["findings"] > base["findings"]:
        reasons.append(f"total findings rose ({base['findings']} -> {variant['findings']})")
    fewer_unanchored = variant["quoted_unanchored_rate"] < base["quoted_unanchored_rate"]
    fewer_malformed = variant["digest_dropped_invalid"] < base["digest_dropped_invalid"]
    if not (fewer_unanchored or fewer_malformed):
        reasons.append("neither the unanchored-quote rate nor the dropped count fell")
    worse = [
        name for name, b, v in (
            ("unanchored-quote rate", base["quoted_unanchored_rate"],
             variant["quoted_unanchored_rate"]),
            ("dropped invalid findings", base["digest_dropped_invalid"],
             variant["digest_dropped_invalid"]),
        ) if v > b
    ]
    reasons += [f"{name} got worse" for name in worse]
    return ("ADOPT" if not reasons else "KEEP BASELINE"), reasons


def _render(base: dict, variant: dict) -> str:
    def row(label: str, b, v) -> str:
        return f"  {label:<34} {b!s:>12} {v!s:>12}"

    lines = [
        f"Baseline: {base['folder']}  (experiments: {base['experiments']})",
        f"Variant:  {variant['folder']}  (experiments: {variant['experiments']})",
        "",
        row("", "baseline", "variant"),
        row("findings", base["findings"], variant["findings"]),
    ]
    for ch in sorted(set(base["channels"]) | set(variant["channels"])):
        lines.append(row(f"  from {ch}", base["channels"].get(ch, 0),
                         variant["channels"].get(ch, 0)))
    for status in ANCHOR_STATUSES:
        lines.append(row(f"anchor {status}", base["anchors"][status],
                         variant["anchors"][status]))
    lines += [
        row("quoted findings", base["quoted"], variant["quoted"]),
        row("  quoted but UNANCHORED", base["quoted_unanchored"],
            variant["quoted_unanchored"]),
        row("  unanchored-quote rate", f"{base['quoted_unanchored_rate']:.1%}",
            f"{variant['quoted_unanchored_rate']:.1%}"),
        row("digest sheets with parser notes", base["digest_drift_sheets"],
            variant["digest_drift_sheets"]),
        row("digest findings dropped invalid", base["digest_dropped_invalid"],
            variant["digest_dropped_invalid"]),
    ]
    decision, reasons = verdict(base, variant)
    lines += ["", f"Adoption rule: {decision}"]
    lines += [f"  - {r}" for r in reasons]
    lines.append(
        "  (one set is an anecdote: repeat on several sets before changing a default)"
    )
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("baseline", type=Path, help="export folder of the baseline run")
    parser.add_argument("variant", type=Path, help="export folder of the experiment run")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)
    base, variant = load_arm(args.baseline), load_arm(args.variant)
    if base["sources"] != variant["sources"]:
        print("The two exports were run on different inputs; nothing to compare.",
              file=sys.stderr)
        return 2
    if args.json:
        decision, reasons = verdict(base, variant)
        print(json.dumps({"baseline": base, "variant": variant,
                          "decision": decision, "reasons": reasons}, indent=2))
    else:
        print(_render(base, variant))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
