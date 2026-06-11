"""Headless runner for the drawing analyzer — no GUI / tkinter required.

The packaged ``python -m drawing_analyzer`` launches the CustomTkinter GUI, which
needs ``tkinter`` + the ``[gui]`` extra. When those aren't available (locked-down
environment, headless server), use this instead: it drives the same engine
through the public library API and writes a folder export (HTML report + Markdown).

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python run_headless.py DRAWINGS.pdf [MORE.pdf ...] [-o OUTPUT_DIR] [--focus "..."]

Output: a timestamped subfolder under OUTPUT_DIR (default: ./drawing-output)
containing report.html, combined.md, one .md per sheet, and (if --focus is set)
00_focus.md.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from drawing_analyzer.export import write_drawing_export
from drawing_analyzer.pipeline import extract_drawing_context


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze drawing PDFs (headless).")
    parser.add_argument("pdfs", nargs="+", type=Path, help="Drawing PDF file(s).")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("drawing-output"),
        help="Parent directory for the export folder (default: ./drawing-output).",
    )
    parser.add_argument(
        "--focus", default=None,
        help='Optional per-run focus, e.g. "the rooms, and what plumbing '
             'fixtures each has". Adds a Focus Report on top of the standard digest.',
    )
    parser.add_argument(
        "--no-synthesis", action="store_true",
        help="Skip the cross-sheet synthesis overview pass.",
    )
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    missing = [str(p) for p in args.pdfs if not p.is_file()]
    if missing:
        print(f"error: file(s) not found: {', '.join(missing)}", file=sys.stderr)
        return 2

    def progress(done: int, total: int, label: str) -> None:
        print(f"[{done}/{total}] {label}")

    print(f"Analyzing {len(args.pdfs)} file(s)…")
    ctx = extract_drawing_context(
        args.pdfs,
        use_batch=True,
        use_cache=True,
        synthesize=not args.no_synthesis,
        focus=args.focus,
        progress=progress,
        on_log=lambda msg, level="info": print(f"  {level}: {msg}"),
    )

    args.output.mkdir(parents=True, exist_ok=True)
    folder = write_drawing_export(
        ctx, args.output, source_names=[p.name for p in args.pdfs]
    )

    print(
        f"\nDone — {ctx.ok_sheet_count}/{ctx.sheet_count} sheet(s) analyzed"
        f"{f', {ctx.cached_sheet_count} from cache' if ctx.cached_sheet_count else ''}."
    )
    print(f"Output written to: {folder}")
    print(f"Open in a browser: {folder / 'report.html'}")
    if ctx.errors:
        print(f"\n{len(ctx.errors)} issue(s):", file=sys.stderr)
        for err in ctx.errors:
            print(f"  - {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
