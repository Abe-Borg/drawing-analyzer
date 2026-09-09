#!/usr/bin/env python3
"""WP-05 §10.3 Step 1 — how long does the confirmation-time cost scan take?

The plan is explicit that this is a *measurement* step, and that the number
already in `render.py` — "0.32 s / 8 sheets / 6,636 words" — is one reading on
unknown content and not a bound for arbitrary sets. Dense schedule sheets scale
with word count, and a hyperscale data-centre fire-protection set is mostly
dense schedule sheets.

Three quantities decide the design, and only the first is obvious:

1. **Scan duration** — `page.rect` + `len(page.get_text("words"))` per page,
   no rasterization. This is what a synchronous scan at the Analyze click costs.
2. **Lock wait** — `gui.py` already runs a profile preflight that holds
   `_preflight_lock` for the *whole set* while it walks every page through
   `render.iter_sheet_prescan`. A confirmation-time scan that wants PyMuPDF must
   wait for that. The wait is not a small addition to (1): the preflight also
   computes each page's **render identity**, which hashes the page's dependency
   graph, so it is the more expensive of the two by construction.
3. **Marginal cost of reuse** — §10.3 item 3 prefers *reusing* the preflight's
   results over adding a second PDF owner. `preflight_sheet_ids` already builds a
   full `SheetGeometry` per page and then keeps only `detect_sheet_id(geometry)`;
   everything a `SheetCostBasis` needs is in the object it discards. If (3) is
   ~0, the design question mostly answers itself.

Zero API calls, no network, no rasterization. Nothing here costs money.

Usage
-----
    # Measure your own sets (what the plan actually asks for)
    python scripts/measure_scan_time.py --pdf setA.pdf --pdf setB.pdf

    # Synthetic sweep, when no real set is at hand. Clearly labelled as such:
    # synthetic pages are uniform, and a real set's variance is the thing that
    # decides whether a synchronous scan is acceptable.
    python scripts/measure_scan_time.py --synthetic

    # Sweep shape explicitly
    python scripts/measure_scan_time.py --synthetic --sheets 8,39,120 --words 500,4000
"""
from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))


def _fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:,.1f} ms"


def make_synthetic_set(directory: Path, *, sheets: int, words_per_sheet: int) -> Path:
    """A PDF of ``sheets`` E-size pages carrying ``words_per_sheet`` words each.

    Uniform by construction, which is exactly the limitation to keep in mind: a
    real set mixes a dense schedule sheet against a mostly-empty detail sheet,
    and it is the slowest page that decides whether a synchronous scan feels
    broken, not the mean.
    """
    import pymupdf

    path = directory / f"synthetic_{sheets}x{words_per_sheet}.pdf"
    # Build ONE page's text, then copy it. Laying out every word on every page
    # is O(sheets x words) ``insert_text`` calls and made this tool slower to set
    # up than to measure — 39 x 4,000 took minutes. Copying is O(words), and the
    # extracted word list is identical either way, which is all the scan reads.
    template = pymupdf.open()
    page = template.new_page(width=34 * 72, height=44 * 72)
    per_row, rows = 12, 170
    for i in range(words_per_sheet):
        x = 36 + (i % per_row) * 190
        y = 40 + ((i // per_row) % rows) * 18
        page.insert_text((x, y), f"FP-{i:05d}", fontsize=7)

    doc = pymupdf.open()
    for _ in range(sheets):
        doc.insert_pdf(template, from_page=0, to_page=0)
    doc.save(str(path))
    doc.close()
    template.close()
    return path


def measure(pdfs: list[Path]) -> dict:
    """Time the three quantities over ``pdfs``. Returns a plain dict."""
    from drawing_analyzer import render
    from drawing_analyzer.auditors.references import detect_sheet_id
    from drawing_analyzer.models import sheet_cost_basis

    # (1) the cost scan alone
    t0 = time.perf_counter()
    bases = list(render.iter_sheet_cost_bases(pdfs))
    scan_s = time.perf_counter() - t0

    # (2) the preflight — the lock holder a confirmation-time scan waits behind
    t0 = time.perf_counter()
    geoms = []
    for _ref, _identity, geometry in render.iter_sheet_prescan(pdfs):
        detect_sheet_id(geometry)
        geoms.append(geometry)
    preflight_s = time.perf_counter() - t0

    # (3) marginal cost of emitting bases from geometry the preflight already has
    t0 = time.perf_counter()
    reused = [sheet_cost_basis(g) for g in geoms]
    reuse_s = time.perf_counter() - t0

    words = sum(len(getattr(g, "words", []) or []) for g in geoms)
    return {
        "pages": len(bases),
        "words": words,
        "scan_s": scan_s,
        "preflight_s": preflight_s,
        "reuse_s": reuse_s,
        "bases": bases,
        "reused": reused,
    }


def _report(label: str, m: dict) -> None:
    pages = max(1, m["pages"])
    print(f"  {label:<22} {m['pages']:>4} pages  {m['words']:>7,} words")
    print(f"    {'cost scan':<20} {_fmt_ms(m['scan_s']):>12}"
          f"   ({_fmt_ms(m['scan_s'] / pages)}/page)")
    print(f"    {'preflight (lock)':<20} {_fmt_ms(m['preflight_s']):>12}"
          f"   ({_fmt_ms(m['preflight_s'] / pages)}/page)")
    print(f"    {'reuse from preflight':<20} {_fmt_ms(m['reuse_s']):>12}"
          f"   ({m['reuse_s'] / max(m['scan_s'], 1e-9) * 100:.2f}% of a fresh scan)")
    if m["words"]:
        print(f"    {'per 1k words':<20} "
              f"{_fmt_ms(m['scan_s'] / (m['words'] / 1000)):>12}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pdf", action="append", type=Path, default=[],
                    help="a real source PDF (repeatable) — what the plan asks for")
    ap.add_argument("--synthetic", action="store_true",
                    help="sweep generated sets instead (clearly labelled)")
    ap.add_argument("--sheets", default="8,39,120",
                    help="synthetic sheet counts, comma-separated")
    ap.add_argument("--words", default="500,4000",
                    help="synthetic words per sheet, comma-separated")
    ap.add_argument("--repeats", type=int, default=3,
                    help="timed repeats; the median is reported")
    args = ap.parse_args(argv)

    if not args.pdf and not args.synthetic:
        ap.error("give --pdf (preferred) or --synthetic")

    if args.pdf:
        missing = [p for p in args.pdf if not p.exists()]
        if missing:
            ap.error("no such file: " + ", ".join(str(p) for p in missing))
        print(f"\nReal set: {len(args.pdf)} file(s)\n")
        runs = [measure(args.pdf) for _ in range(args.repeats)]
        best = min(runs, key=lambda m: m["scan_s"])
        best["scan_s"] = statistics.median(r["scan_s"] for r in runs)
        best["preflight_s"] = statistics.median(r["preflight_s"] for r in runs)
        best["reuse_s"] = statistics.median(r["reuse_s"] for r in runs)
        _report("measured", best)
        _verdict(best)
        return 0

    print("\nSYNTHETIC sets — uniform pages, generated here. Real sets vary far")
    print("more per page, and it is the slowest page that decides whether a")
    print("synchronous scan feels broken. Treat these as a floor.\n")
    sheet_counts = [int(s) for s in args.sheets.split(",") if s.strip()]
    word_counts = [int(w) for w in args.words.split(",") if w.strip()]
    worst = None
    with tempfile.TemporaryDirectory(prefix="da-scan-") as tmp:
        for words in word_counts:
            for sheets in sheet_counts:
                path = make_synthetic_set(Path(tmp), sheets=sheets, words_per_sheet=words)
                runs = [measure([path]) for _ in range(args.repeats)]
                m = min(runs, key=lambda r: r["scan_s"])
                m["scan_s"] = statistics.median(r["scan_s"] for r in runs)
                m["preflight_s"] = statistics.median(r["preflight_s"] for r in runs)
                m["reuse_s"] = statistics.median(r["reuse_s"] for r in runs)
                _report(f"{sheets} sheets x {words}w", m)
                if worst is None or m["scan_s"] > worst["scan_s"]:
                    worst = m
                print()
    if worst is not None:
        _verdict(worst)
    return 0


def _verdict(m: dict) -> None:
    """State what the numbers imply, without deciding for the reader."""
    print("\n  ---")
    scan, pre, reuse = m["scan_s"], m["preflight_s"], m["reuse_s"]
    print(f"  A synchronous scan at the Analyze click costs {_fmt_ms(scan)} here.")
    print(f"  Worst-case wait behind a running preflight adds {_fmt_ms(pre)},")
    print(f"  for {_fmt_ms(scan + pre)} total — the preflight is the larger term.")
    print(f"  Reusing the preflight's own geometry instead costs {_fmt_ms(reuse)},")
    ratio = reuse / max(scan, 1e-9)
    print(f"  which is {ratio * 100:.2f}% of a fresh scan and needs no lock at all.")
    print("  ---\n")


if __name__ == "__main__":
    raise SystemExit(main())
