"""Pure (tkinter-free) export of a drawing digest to a folder of Markdown files.

The "Analyze Drawings…" flow turns a construction-drawing set into a
``DrawingContext`` — one vision digest per sheet plus an optional cross-sheet
synthesis. This module serializes that result to disk so the operator can keep
and review every piece: one ``.md`` per sheet (failed sheets included, carrying
their error), the synthesis on its own, the full combined digest, and an
``index`` summarizing the run. Nothing here touches Project Context — analyzing
drawings and feeding the spec review are deliberately decoupled (the drawings
flow saves to disk only).

Kept tkinter-free and duck-typed on the context — it reads only the attributes
below, never the drawing engine itself — so it unit-tests without the GUI stack,
PyMuPDF, or a network, mirroring :mod:`context_attachment`.

Read surface (duck-typed):
- ``ctx.sheets``      — list of per-sheet digests, each with ``.ref``
  (``source_name`` / ``page_index`` / ``page_count`` / ``display_label``),
  ``.text``, ``.error``, ``.cached``, ``.input_tokens`` / ``.output_tokens``.
- ``ctx.synthesis_text`` / ``ctx.combined_text`` — the set-level documents.
- ``ctx.focus`` / ``ctx.focus_report_text`` — the optional per-run focus and
  its set-level report (``00_focus.md`` is written only when a focus was set).
- ``ctx.ok_sheet_count`` / ``ctx.sheet_count`` / ``ctx.file_count`` /
  ``ctx.cached_sheet_count`` / ``ctx.total_input_tokens`` /
  ``ctx.total_output_tokens`` / ``ctx.errors`` — run-level summary fields.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .html_report import build_html_report

_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


def _slug(text: str, *, max_len: int = 48) -> str:
    """Filesystem-safe slug: non-alphanumeric runs collapse to a single ``_``."""
    s = _SLUG_RE.sub("_", text or "").strip("_")
    return s[:max_len].strip("_") or "drawings"


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d_%H%M%S")


def export_folder_name(source_names: list[str], *, now: datetime) -> str:
    """Folder name for one export: ``<first-source-stem>_drawings_<timestamp>``.

    Uses the first source file's stem for a recognizable name; the index lists
    every source file, so a multi-file set is still fully described inside. With
    no source names it falls back to ``drawings_<timestamp>``.
    """
    ts = _timestamp(now)
    if not source_names:
        return f"drawings_{ts}"
    return f"{_slug(Path(source_names[0]).stem)}_drawings_{ts}"


def _ref_of(sheet: Any) -> Any:
    return getattr(sheet, "ref", None)


def _sheet_filename(index: int, sheet: Any) -> str:
    """``NN_<source-stem>_p<page>.md`` — globally unique via the ``NN`` prefix."""
    ref = _ref_of(sheet)
    source = getattr(ref, "source_name", "") or "sheet"
    page = int(getattr(ref, "page_index", index - 1) or 0) + 1
    return f"{index:02d}_{_slug(Path(source).stem, max_len=40)}_p{page}.md"


def _sheet_status(sheet: Any) -> str:
    error = getattr(sheet, "error", None)
    if error:
        return f"FAILED — {error}"
    if getattr(sheet, "cached", False):
        return "OK (served from cache)"
    return "OK"


def _sheet_document(index: int, total: int, sheet: Any) -> str:
    """One sheet's Markdown file: heading, status/token line, then digest text.

    A failed sheet has no digest text, so its error is rendered as the body — the
    operator gets one file per sheet either way (nothing silently dropped).
    """
    ref = _ref_of(sheet)
    label = getattr(ref, "display_label", None) or f"Sheet {index}/{total}"
    text = (getattr(sheet, "text", "") or "").strip()
    error = getattr(sheet, "error", None)
    in_tok = int(getattr(sheet, "input_tokens", 0) or 0)
    out_tok = int(getattr(sheet, "output_tokens", 0) or 0)

    lines = [f"# {label}", "", f"**Status:** {_sheet_status(sheet)}"]
    if in_tok or out_tok:
        lines.append(f"**Tokens:** {in_tok:,} in / {out_tok:,} out")
    lines += ["", ""]
    if text:
        lines.append(text)
    elif error:
        lines.append(f"> This sheet could not be analyzed: {error}")
    else:
        lines.append("> (empty digest)")
    lines.append("")
    return "\n".join(lines)


def _synthesis_document(ctx: Any) -> str:
    synthesis = (getattr(ctx, "synthesis_text", "") or "").strip()
    if synthesis:
        return synthesis + "\n"
    return (
        "# Drawing Set Overview (cross-sheet synthesis)\n\n"
        "_No cross-sheet synthesis was produced. Synthesis is skipped for fewer "
        "than two readable sheets and falls back silently on error — see "
        "`00_index.md` for any run errors._\n"
    )


def _focus_value(ctx: Any) -> str:
    return (getattr(ctx, "focus", "") or "").strip()


def _focus_document(ctx: Any) -> str:
    """The focus report file (written only when a per-run focus was set).

    The operator's question is quoted first so the file is self-describing,
    then the set-level report. A focus whose report pass failed still gets the
    file — with a pointer to the run errors — so the requested deliverable is
    never silently absent.
    """
    focus = _focus_value(ctx)
    report = (getattr(ctx, "focus_report_text", "") or "").strip()
    lines = [
        "# Focus Report (operator-requested)",
        "",
        f"**Operator focus for this run:** {focus}",
        "",
    ]
    if report:
        lines.append(report)
    else:
        lines.append(
            "> No focus report was produced for this run — see `00_index.md` "
            "for the error. The per-sheet files still carry any per-sheet "
            "*Focus findings* sections."
        )
    lines.append("")
    return "\n".join(lines)


def _index_document(
    ctx: Any,
    *,
    source_names: list[str],
    now: datetime,
    sheet_files: list[tuple[int, Any, str]],
) -> str:
    """The run summary: sources, counts, a per-sheet status table, errors, files."""
    ok = int(getattr(ctx, "ok_sheet_count", 0) or 0)
    total = int(getattr(ctx, "sheet_count", len(sheet_files)) or len(sheet_files))
    cached = int(getattr(ctx, "cached_sheet_count", 0) or 0)
    in_tok = int(getattr(ctx, "total_input_tokens", 0) or 0)
    out_tok = int(getattr(ctx, "total_output_tokens", 0) or 0)
    errors = list(getattr(ctx, "errors", None) or [])

    lines = [
        "# Drawing Digest Export",
        "",
        f"_Generated {now.strftime('%Y-%m-%d %H:%M:%S')}._",
        "",
        "> **Tip:** open **`report.html`** in any web browser for a navigable,"
        " searchable view — jump between sheets and filter to just the"
        " coordination items or the conflicts the model flagged. The Markdown"
        " files below carry the same content for downstream use.",
        "",
        f"- **Source file(s):** {len(source_names)}",
    ]
    for name in source_names:
        lines.append(f"  - {name}")
    focus = _focus_value(ctx)
    if focus:
        lines.append(f"- **Per-run focus:** {focus} (see `00_focus.md`)")
    lines += [
        f"- **Sheets analyzed:** {ok}/{total}"
        + (f" ({cached} from cache)" if cached else ""),
        f"- **Tokens billed:** {in_tok:,} in / {out_tok:,} out",
        "",
        "## Sheets",
        "",
        "| # | Sheet | Status | File |",
        "| --- | --- | --- | --- |",
    ]
    for index, sheet, fname in sheet_files:
        ref = _ref_of(sheet)
        label = getattr(ref, "display_label", None) or f"Sheet {index}/{total}"
        lines.append(f"| {index} | {label} | {_sheet_status(sheet)} | `{fname}` |")
    lines.append("")

    if errors:
        lines += ["## Errors", ""]
        lines += [f"- {e}" for e in errors]
        lines.append("")

    lines += [
        "## Files in this export",
        "",
        "- `report.html` — navigable, searchable browser view (start here)",
        "- `00_index.md` — this summary",
        "- `00_synthesis.md` — cross-sheet overview",
    ]
    if focus:
        lines.append("- `00_focus.md` — the focus report for this run's focus")
    for _, _, fname in sheet_files:
        lines.append(f"- `{fname}` — one sheet")
    lines.append("- `combined.md` — every sheet + the synthesis in one document")
    lines.append("")
    return "\n".join(lines)


def build_export_documents(
    ctx: Any, *, source_names: list[str], now: datetime, api_key: str | None = None
) -> list[tuple[str, str]]:
    """Build the ordered ``(filename, content)`` list for an export folder.

    Order: ``report.html`` (the navigable browser view) → ``00_index.md`` →
    ``00_synthesis.md`` → ``00_focus.md`` (only when a per-run focus was set) →
    one file per sheet (page order) → ``combined.md``. The HTML report is a
    self-contained, lossless re-presentation of the same content (see
    :mod:`drawing_analyzer.html_report`); the Markdown files remain for
    downstream/text use. Pure: no I/O, so it is the unit-testable core of
    :func:`write_drawing_export`.

    ``api_key`` is forwarded to :func:`build_html_report`: when given, the HTML
    report embeds the in-page Q&A assistant **and the key itself** (see the
    security note there). Default ``None`` keeps the report key-free.
    """
    sheets = list(getattr(ctx, "sheets", None) or [])
    total = len(sheets)
    sheet_files = [
        (i, sheet, _sheet_filename(i, sheet)) for i, sheet in enumerate(sheets, start=1)
    ]

    docs: list[tuple[str, str]] = [
        ("report.html",
         build_html_report(ctx, source_names=source_names, now=now, api_key=api_key)),
        ("00_index.md", _index_document(ctx, source_names=source_names, now=now, sheet_files=sheet_files)),
        ("00_synthesis.md", _synthesis_document(ctx)),
    ]
    if _focus_value(ctx):
        docs.append(("00_focus.md", _focus_document(ctx)))
    for index, sheet, fname in sheet_files:
        docs.append((fname, _sheet_document(index, total, sheet)))

    combined = (getattr(ctx, "combined_text", "") or "").strip()
    docs.append(("combined.md", combined + "\n" if combined else "(no combined digest produced)\n"))
    return docs


def _unique_dir(path: Path) -> Path:
    """``path`` if free, else ``path_2`` / ``path_3`` / … (collision-safe)."""
    if not path.exists():
        return path
    for n in range(2, 1000):
        cand = path.with_name(f"{path.name}_{n}")
        if not cand.exists():
            return cand
    return path  # give up; mkdir(exist_ok=False) will raise and the caller surfaces it


# ---------------------------------------------------------------------------
# Findings CSV (the QC-markup deliverable's flat, Excel-friendly export).
#
# Duck-typed on the §4.1 Finding shape so it stays PyMuPDF-free and testable:
# one row per finding, every field flattened. Written UTF-8 with a BOM and CRLF
# line endings so Excel on Windows (the owner's platform) opens it cleanly with
# unicode intact.
# ---------------------------------------------------------------------------

FINDINGS_CSV_HEADER = [
    "id", "sheet_id", "source_name", "page", "category", "severity",
    "text", "source_quote", "tile", "refs",
    "anchor_status", "anchor_method", "rect_pdf",
    "verification_status", "verification_note", "evidence_png",
]


def _fmt_tile(tile: Any) -> str:
    if isinstance(tile, (list, tuple)) and len(tile) == 2:
        return f"{tile[0]},{tile[1]}"
    return ""


def _fmt_rect(rect: Any) -> str:
    if isinstance(rect, (list, tuple)) and len(rect) == 4:
        return ", ".join(f"{float(v):.1f}" for v in rect)
    return ""


def _finding_row(finding: Any) -> list[str]:
    anchor = getattr(finding, "anchor", None)
    verification = getattr(finding, "verification", None)
    refs = list(getattr(finding, "refs", None) or [])
    page_index = int(getattr(finding, "page_index", 0) or 0)
    return [
        str(getattr(finding, "id", "")),
        str(getattr(finding, "sheet_id", "")),
        str(getattr(finding, "source_name", "")),
        str(page_index + 1),                       # 1-based page, for the reader
        str(getattr(finding, "category", "")),
        str(getattr(finding, "severity", "")),
        str(getattr(finding, "text", "")),
        str(getattr(finding, "source_quote", "")),
        _fmt_tile(getattr(finding, "tile", None)),
        "; ".join(str(r) for r in refs),
        str(getattr(anchor, "status", "")) if anchor is not None else "",
        str(getattr(anchor, "method", "")) if anchor is not None else "",
        _fmt_rect(getattr(anchor, "rect_pdf", None)) if anchor is not None else "",
        str(getattr(verification, "status", "")) if verification is not None else "",
        str(getattr(verification, "note", "")) if verification is not None else "",
        str(getattr(verification, "evidence_png", "")) if verification is not None else "",
    ]


def build_findings_csv(findings: list[Any]) -> str:
    """The findings CSV as a string (header + one row per finding), CRLF-terminated.

    Pure — no I/O — so it is the unit-testable core of :func:`write_findings_csv`.
    The returned text carries no BOM; the writer adds it at encode time.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(FINDINGS_CSV_HEADER)
    for finding in findings:
        writer.writerow(_finding_row(finding))
    return buf.getvalue()


def write_findings_csv(findings: list[Any], path: Any) -> Path:
    """Write ``findings.csv`` to ``path`` (UTF-8 **with BOM**, CRLF), return it.

    ``newline=""`` keeps the CSV module's ``\\r\\n`` terminators intact (no OS
    translation); ``utf-8-sig`` prepends the BOM Excel wants to detect UTF-8.
    """
    path = Path(path)
    with open(path, "w", encoding="utf-8-sig", newline="") as fp:
        fp.write(build_findings_csv(findings))
    return path


def write_drawing_export(
    ctx: Any,
    parent_dir: Any,
    *,
    source_names: list[str],
    now: datetime | None = None,
    api_key: str | None = None,
) -> Path:
    """Create a named subfolder under ``parent_dir`` and write the export to it.

    Returns the created folder ``Path``. The operator picks ``parent_dir``; the
    subfolder is named deterministically (:func:`export_folder_name`) and made
    unique so a re-run never clobbers a prior export. ``api_key`` is forwarded
    to the HTML report (see :func:`build_export_documents`).
    """
    now = now or datetime.now()
    folder = _unique_dir(Path(parent_dir) / export_folder_name(source_names, now=now))
    folder.mkdir(parents=True, exist_ok=False)
    for name, content in build_export_documents(
        ctx, source_names=source_names, now=now, api_key=api_key
    ):
        (folder / name).write_text(content, encoding="utf-8")
    return folder
