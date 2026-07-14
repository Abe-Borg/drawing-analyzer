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
import hashlib
import io
import json
import re
import shutil
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
    if has_qc_outputs(ctx):
        findings = _qc_findings(ctx)
        reviewed = list(getattr(ctx, "reviewed_pdf_paths", None) or [])
        coverage = getattr(ctx, "coverage_status", "NOT_REQUESTED") or "NOT_REQUESTED"
        # DA-012 (§15.2): a standard run now retains + exports its digest findings
        # and sheet text, so this block renders for *every* run — but a plain
        # standard run did no QC, so it must not be mislabeled "QC review". The
        # heading (and the status line) are mode-aware off the run's QC status.
        exhaustive = getattr(
            getattr(ctx, "run_configuration", None), "exhaustive_qc", False
        )
        qc_ran = exhaustive or bool(getattr(ctx, "reference_findings", None)) or bool(reviewed)
        heading = "QC review" if qc_ran else "Findings & sheet text"
        lines += ["", f"### {heading}", ""]
        qc_status = getattr(ctx, "qc_status", "NOT_REQUESTED") or "NOT_REQUESTED"
        if exhaustive:
            label = getattr(ctx, "qc_status_label", qc_status)
            lines.append(f"- **QC status:** {qc_status} — {label}")
        lines.append(
            f"- **Findings:** {len(findings)}"
            + (f" · **reviewed PDF(s):** {len(reviewed)}" if reviewed else "")
        )
        if coverage in ("COMPLETE", "INCOMPLETE"):
            tally = getattr(ctx, "ledger_tally_line", "") or ""
            note = (
                "every planned markup was found again in the saved PDFs"
                if coverage == "COMPLETE"
                else "**some planned markups are missing or failed — see the "
                "`_INCOMPLETE` PDF(s), `run` errors, and `markup_manifest.json`**"
            )
            lines.append(f"- **Markup coverage:** {coverage} — {note}")
            if tally:
                lines.append(f"  - {tally}")
        lines.append("- `findings.json` / `findings.csv` — every finding, all fields")
        for pdf in reviewed:
            label = (
                " — **incomplete markup** (labeled)"
                if "_INCOMPLETE" in Path(pdf).name
                else " — the marked-up drawing"
            )
            lines.append(f"- `{Path(pdf).name}`{label}")
        lines.append("- `sheet_text/` — each sheet's extracted text layer")
        if has_markup_manifest(ctx):
            lines.append(
                "- `markup_manifest.json` — every planned placement + its "
                "artifact-backed receipt (coverage proof)"
            )
        if getattr(ctx, "qc_work_dir", None) is not None:
            lines.append("- `evidence/` — the crop the verifier saw for each finding")
    lines.append("")
    return "\n".join(lines)


def build_export_documents(
    ctx: Any, *, source_names: list[str], now: datetime, api_key: str | None = None,
    embed_api_key: bool = False, include_chat: bool = True,
) -> list[tuple[str, str]]:
    """Build the ordered ``(filename, content)`` list for an export folder.

    Order: ``report.html`` (the navigable browser view) → ``00_index.md`` →
    ``00_synthesis.md`` → ``00_focus.md`` (only when a per-run focus was set) →
    one file per sheet (page order) → ``combined.md``. The HTML report is a
    self-contained, lossless re-presentation of the same content (see
    :mod:`drawing_analyzer.html_report`); the Markdown files remain for
    downstream/text use. Pure: no I/O, so it is the unit-testable core of
    :func:`write_drawing_export`.

    The report's Ask-AI assistant is included by default and prompts for a key
    on first use; **no key is written into the file** unless
    ``embed_api_key=True`` (see the security note in
    :func:`~drawing_analyzer.html_report.build_html_report`). Pass
    ``include_chat=False`` for a report with no assistant at all. The folder
    report links the verifier's evidence crops (copied alongside by
    :func:`write_qc_outputs`).
    """
    sheets = list(getattr(ctx, "sheets", None) or [])
    total = len(sheets)
    sheet_files = [
        (i, sheet, _sheet_filename(i, sheet)) for i, sheet in enumerate(sheets, start=1)
    ]

    docs: list[tuple[str, str]] = [
        ("report.html",
         build_html_report(ctx, source_names=source_names, now=now, api_key=api_key,
                           embed_api_key=embed_api_key, link_evidence=True,
                           include_chat=include_chat)),
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
    "qc_id", "id", "sheet_id", "source_id", "source_name", "page", "category",
    "severity", "text", "source_quote", "tile", "refs", "also_on", "sources",
    "anchor_status", "anchor_method", "rect_pdf",
    "verification_status", "verification_note", "evidence_png",
    "citation_status", "citation_note",
    # Phase 22 additions (appended so existing column positions are unchanged):
    # ``scope`` distinguishes a set-level finding (belongs to no source sheet) and
    # ``confidence`` surfaces the critique self-consistency verdict.
    "scope", "confidence",
    # Phase 25 §17.1: the human 1-based tile label ("r1c1") alongside the internal
    # zero-based ``tile`` column — appended so existing positions are unchanged.
    "tile_label",
]


def _finding_scope(finding: Any) -> str:
    """``SET`` for a set-level finding (no source, ``SET_INDEX`` hint), else ``SOURCE``."""
    hint = str(getattr(finding, "anchor_hint", "") or "").upper()
    if hint in {"SET", "SET_INDEX"} and not getattr(finding, "source_id", ""):
        return "SET"
    return "SOURCE"


def _fmt_also_on(legs: Any) -> str:
    """Flatten a cross-sheet finding's ``also_on`` legs for the CSV, so a conflict's
    other sheet(s) aren't hidden inside the free-text column."""
    out = []
    for leg in legs or []:
        sid = str(getattr(leg, "sheet_id", "")).strip()
        quote = str(getattr(leg, "source_quote", "")).strip()
        out.append(f'{sid}: "{quote}"' if quote else sid)
    return "; ".join(p for p in out if p)


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
    citation = getattr(finding, "citation", None)
    refs = list(getattr(finding, "refs", None) or [])
    page_index = int(getattr(finding, "page_index", 0) or 0)
    scope = _finding_scope(finding)
    return [
        str(getattr(finding, "qc_id", "") or ""),
        str(getattr(finding, "id", "")),
        str(getattr(finding, "sheet_id", "")),
        str(getattr(finding, "source_id", "") or ""),
        str(getattr(finding, "source_name", "")),
        "" if scope == "SET" else str(page_index + 1),   # 1-based page; blank for set-level
        str(getattr(finding, "category", "")),
        str(getattr(finding, "severity", "")),
        str(getattr(finding, "text", "")),
        str(getattr(finding, "source_quote", "")),
        _fmt_tile(getattr(finding, "tile", None)),
        "; ".join(str(r) for r in refs),
        _fmt_also_on(getattr(finding, "also_on", None)),
        "; ".join(str(s) for s in (getattr(finding, "sources", None) or [])),
        str(getattr(anchor, "status", "")) if anchor is not None else "",
        str(getattr(anchor, "method", "")) if anchor is not None else "",
        _fmt_rect(getattr(anchor, "rect_pdf", None)) if anchor is not None else "",
        str(getattr(verification, "status", "")) if verification is not None else "",
        str(getattr(verification, "note", "")) if verification is not None else "",
        str(getattr(verification, "evidence_png", "")) if verification is not None else "",
        str(getattr(citation, "status", "")) if citation is not None else "",
        str(getattr(citation, "note", "")) if citation is not None else "",
        scope,
        str(getattr(finding, "confidence", "") or ""),
        str(getattr(finding, "tile_label", "") or ""),
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


# ---------------------------------------------------------------------------
# QC review inventory (§4.5): findings.json / findings.csv, the per-sheet text
# layers, the reviewed PDFs, and the verifier's evidence crops. All duck-typed
# on the context so this stays PyMuPDF-free — the binaries were produced upstream
# (annotate.py / verify.py) and are only *copied* here.
# ---------------------------------------------------------------------------


def _qc_findings(ctx: Any) -> list[Any]:
    return list(getattr(ctx, "findings", None) or []) + list(
        getattr(ctx, "reference_findings", None) or []
    )


def has_qc_outputs(ctx: Any) -> bool:
    return bool(
        _qc_findings(ctx)
        or getattr(ctx, "reviewed_pdf_paths", None)
        or getattr(ctx, "sheet_geometries", None)
    )


def _sheet_text_name(ref: Any, used: set[str]) -> str:
    stem = _slug(Path(getattr(ref, "source_name", "sheet")).stem, max_len=40)
    page = int(getattr(ref, "page_index", 0) or 0) + 1
    name = f"{stem}_p{page}.txt"
    n = 1
    while name in used:
        n += 1
        name = f"{stem}_p{page}_{n}.txt"
    used.add(name)
    return name


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def has_markup_manifest(ctx: Any) -> bool:
    """True when a markup run happened (so a coverage manifest should be written)."""
    return getattr(ctx, "markup_run", None) is not None or bool(
        getattr(ctx, "reviewed_pdf_paths", None)
    )


def build_markup_manifest(ctx: Any, *, folder: Path | None = None) -> dict:
    """The machine-readable markup-coverage manifest (§13.7).

    Carries the run's coverage status, the receipt-derived tally, every planned
    placement, every terminal receipt, and — when ``folder`` is given — the
    sha256 of each reviewed PDF as it actually landed on disk. It contains **no
    API key and no absolute path** (receipts reference basenames only), so it is
    portable. The receipts are the artifact-backed proof that each expected
    placement exists in the saved PDF (or an explicit failure).
    """
    run = getattr(ctx, "markup_run", None)
    manifest: dict = {
        "schema_version": 1,
        "coverage_status": getattr(ctx, "coverage_status", "NOT_REQUESTED") or "NOT_REQUESTED",
        "tally": dict(getattr(ctx, "ledger_tally", None) or {}),
        "mutated_sources": list(getattr(ctx, "mutated_sources", None) or []),
        "placements": [],
        "receipts": [],
        "outputs": [],
    }
    if run is not None and hasattr(run, "to_dict"):
        run_dict = run.to_dict()
        manifest["placements"] = run_dict.get("placements", [])
        manifest["receipts"] = run_dict.get("receipts", [])
    # Hash the reviewed PDFs as they actually exist in the export folder — the
    # concrete artifacts the receipts describe.
    if folder is not None:
        names = sorted(
            {
                str(r.get("output_pdf") or "")
                for r in manifest["receipts"]
                if r.get("output_pdf")
            }
            | {Path(p).name for p in (getattr(ctx, "reviewed_pdf_paths", None) or [])}
        )
        for name in names:
            out = Path(folder) / name
            if out.exists():
                manifest["outputs"].append(
                    {"name": name, "sha256": _sha256(out), "bytes": out.stat().st_size}
                )
    return manifest


def write_qc_outputs(ctx: Any, folder: Path) -> list[str]:
    """Write the QC inventory into ``folder``; return the relative names written.

    Idempotent and defensive: a missing reviewed PDF / evidence file is skipped
    rather than sinking the export. Writes nothing when the run had no QC stage.
    """
    if not has_qc_outputs(ctx):
        return []

    findings = _qc_findings(ctx)
    geometries = list(getattr(ctx, "sheet_geometries", None) or [])
    reviewed = list(getattr(ctx, "reviewed_pdf_paths", None) or [])
    work_dir = getattr(ctx, "qc_work_dir", None)
    written: list[str] = []

    # Findings inventory — written whenever a QC stage ran, even when it found
    # nothing, so the files the index advertises always exist on disk. A clean
    # run is a valid result: a header-only CSV and ``{"findings": []}`` JSON.
    (folder / "findings.json").write_text(
        json.dumps({"findings": [f.to_dict() for f in findings]}, indent=2),
        encoding="utf-8",
    )
    write_findings_csv(findings, folder / "findings.csv")
    written += ["findings.json", "findings.csv"]

    if geometries:
        st_dir = folder / "sheet_text"
        st_dir.mkdir(parents=True, exist_ok=True)
        used: set[str] = set()
        for geometry in geometries:
            name = _sheet_text_name(getattr(geometry, "ref", None), used)
            (st_dir / name).write_text(getattr(geometry, "sheet_text", "") or "", encoding="utf-8")
        written.append("sheet_text/")

    for pdf in reviewed:
        pdf = Path(pdf)
        if pdf.exists():
            shutil.copy2(pdf, folder / pdf.name)
            written.append(pdf.name)

    if work_dir is not None:
        evidence = Path(work_dir) / "evidence"
        if evidence.is_dir():
            dest = folder / "evidence"
            # Copy the COMPLETE nested tree (DA-016): per-QC-ID subdirs, every leg
            # crop, and each request.json — not just the top-level PNGs. A shallow
            # ``glob("*.png")`` silently dropped the per-leg subdirectories.
            copied = 0
            for src in sorted(evidence.rglob("*")):
                if src.is_dir():
                    continue
                target = dest / src.relative_to(evidence)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
                copied += 1
            if copied:
                written.append("evidence/")

    # Markup coverage manifest (§13.7) — written after the reviewed PDFs are on
    # disk so its output hashes describe the concrete files. Only when a markup
    # run happened (a reference-audit-only run has no placements to account).
    if has_markup_manifest(ctx):
        (folder / "markup_manifest.json").write_text(
            json.dumps(build_markup_manifest(ctx, folder=folder), indent=2),
            encoding="utf-8",
        )
        written.append("markup_manifest.json")

    return written


def write_drawing_export(
    ctx: Any,
    parent_dir: Any,
    *,
    source_names: list[str],
    now: datetime | None = None,
    api_key: str | None = None,
    embed_api_key: bool = False,
    include_chat: bool = True,
) -> Path:
    """Create a named subfolder under ``parent_dir`` and write the export to it.

    Returns the created folder ``Path``. The operator picks ``parent_dir``; the
    subfolder is named deterministically (:func:`export_folder_name`) and made
    unique so a re-run never clobbers a prior export. ``api_key`` /
    ``embed_api_key`` / ``include_chat`` are forwarded to the HTML report (see
    :func:`build_export_documents`).
    """
    now = now or datetime.now()
    folder = _unique_dir(Path(parent_dir) / export_folder_name(source_names, now=now))
    folder.mkdir(parents=True, exist_ok=False)
    for name, content in build_export_documents(
        ctx, source_names=source_names, now=now, api_key=api_key,
        embed_api_key=embed_api_key, include_chat=include_chat,
    ):
        (folder / name).write_text(content, encoding="utf-8")
    # QC review inventory (findings.json/csv, sheet_text/, reviewed PDFs,
    # evidence/) — only written when the run ran a QC stage.
    write_qc_outputs(ctx, folder)
    return folder
