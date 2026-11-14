"""Checklist results: every item, on every sheet it was applied to, accounted for.

The critique asks the reviewer to answer each checklist item per sheet
(:mod:`drawing_analyzer.profiles` builds the block, :mod:`drawing_analyzer.critique`
validates the answers). This module is the roll-up: it joins those per-sheet
answers to the run's **final** findings — numbered, merged and verified — and
states, for each item and sheet, what the run can actually stand behind.

The distinction it exists to keep honest:

* a **violation** is backed by a finding that went through anchoring and
  verification like any other, and is shown with that finding's ``QC-###``;
* **met** is the reviewer's own report and nothing checked it, so it is worded
  "reported met", never "pass";
* an item the reviewer did not account for is **not answered**, never assumed
  met; a sheet with no valid critique read is **not reviewed**.

Pure and deterministic (I-7): no model call, no I/O, no clock. Sheets keep the
order they are given in; items keep checklist order.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import Any, Iterable

from .models import (
    CHECK_MET,
    CHECK_NOT_APPLICABLE,
    CHECK_UNANSWERED,
    CHECK_UNDETERMINED,
    CHECK_VIOLATED,
    merged_check_status,
    source_page_key,
)

# What one item came to on one sheet, after the findings are final.
CELL_VIOLATED = "VIOLATED"                      # a finding stands against it
CELL_VIOLATED_NO_FINDING = "VIOLATED_NO_FINDING"  # called violated, no finding to show
CELL_UNDETERMINED = "UNDETERMINED"              # this sheet alone could not settle it
CELL_REJECTED = "REJECTED"                      # every finding against it was rejected
CELL_UNANSWERED = "UNANSWERED"                  # the reviewer did not account for it
CELL_NOT_REVIEWED = "NOT_REVIEWED"              # the sheet has no valid critique read
CELL_MET = "MET"                                # reported met (unverified)
CELL_NOT_APPLICABLE = "NOT_APPLICABLE"
CELL_OUT_OF_SCOPE = "OUT_OF_SCOPE"              # the sheet was never given the item

# Which sheet decides an item's set-level result: the one a reviewer most needs
# to look at. A sheet nobody answered outranks a sheet that reported it met.
CELL_PRECEDENCE: tuple[str, ...] = (
    CELL_VIOLATED, CELL_VIOLATED_NO_FINDING, CELL_UNDETERMINED, CELL_REJECTED,
    CELL_UNANSWERED, CELL_NOT_REVIEWED, CELL_MET, CELL_NOT_APPLICABLE,
    CELL_OUT_OF_SCOPE,
)

CELL_LABELS: dict[str, str] = {
    CELL_VIOLATED: "Violated",
    CELL_VIOLATED_NO_FINDING: "Flagged, no finding",
    CELL_UNDETERMINED: "Undetermined",
    CELL_REJECTED: "Flagged, rejected on verification",
    CELL_UNANSWERED: "Not answered",
    CELL_NOT_REVIEWED: "Not reviewed",
    CELL_MET: "Reported met",
    CELL_NOT_APPLICABLE: "Not applicable",
    CELL_OUT_OF_SCOPE: "Out of scope",
}

_READ_TO_CELL = {
    CHECK_UNDETERMINED: CELL_UNDETERMINED,
    CHECK_MET: CELL_MET,
    CHECK_NOT_APPLICABLE: CELL_NOT_APPLICABLE,
    CHECK_UNANSWERED: CELL_UNANSWERED,
}


@dataclass(frozen=True)
class ChecklistSheet:
    """One sheet of the run as the matrix needs it."""

    key: tuple          # ``models.source_page_key`` — joins answers and findings
    ref_key: tuple      # ``models.sheet_ref_key`` — joins the checklist plan's scope
    label: str


@dataclass
class ChecklistCell:
    status: str
    qc_ids: list[str] = field(default_factory=list)
    # False when the sheet's valid reads gave different answers.
    reads_agree: bool = True


@dataclass
class ChecklistRow:
    """One checklist item across the whole set."""

    id: str
    text: str
    checklist: str      # the owning checklist's title
    origin: str         # "user" | "model"
    status: str = CELL_OUT_OF_SCOPE
    counts: dict[str, int] = field(default_factory=dict)
    qc_ids: list[str] = field(default_factory=list)
    cells: list[ChecklistCell] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "checklist": self.checklist,
            "origin": self.origin,
            "status": self.status,
            "counts": {k: self.counts[k] for k in CELL_PRECEDENCE if self.counts.get(k)},
            "findings": list(self.qc_ids),
        }


@dataclass
class ChecklistReport:
    """The checklist results of one run (``ctx.checklist_report``)."""

    rows: list[ChecklistRow] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.rows)

    def totals(self, origin: str | None = None) -> dict[str, int]:
        """How many items ended at each set-level result."""
        out = {status: 0 for status in CELL_PRECEDENCE}
        for row in self.rows:
            if origin is None or row.origin == origin:
                out[row.status] += 1
        return out

    def cell_total(self, status: str) -> int:
        """How many item-on-sheet checks ended at ``status`` across the set."""
        return sum(row.counts.get(status, 0) for row in self.rows)

    def to_dict(self) -> dict:
        """The manifest/JSON form: results and counts, never a per-sheet grid
        (that is ``checklist_matrix.csv``)."""
        return {
            "items": len(self.rows),
            "sheets": len(self.sheets),
            "totals": {k: v for k, v in self.totals().items() if v},
            "user_totals": {k: v for k, v in self.totals("user").items() if v},
            "model_totals": {k: v for k, v in self.totals("model").items() if v},
            "unanswered_checks": self.cell_total(CELL_UNANSWERED),
            "not_reviewed_checks": self.cell_total(CELL_NOT_REVIEWED),
            "rows": [row.to_dict() for row in self.rows],
        }


def summary_line(report: ChecklistReport) -> str:
    """One sentence for a log or status line: how the checklist came out."""
    totals = report.totals()
    parts = [
        f"{totals[status]} {CELL_LABELS[status].lower()}"
        for status in CELL_PRECEDENCE if totals.get(status)
    ]
    line = f"Checklist: {len(report.rows)} item(s) - " + ", ".join(parts)
    unanswered = report.cell_total(CELL_UNANSWERED) + report.cell_total(CELL_NOT_REVIEWED)
    if unanswered:
        line += f"; {unanswered} item-on-sheet check(s) not answered"
    return line + "."


def _is_rejected(finding: Any) -> bool:
    verification = getattr(finding, "verification", None)
    return str(getattr(verification, "status", "") or "") == "REJECTED"


def _qc_sort_key(qc_id: str) -> tuple:
    digits = "".join(ch for ch in qc_id if ch.isdigit())
    return (int(digits) if digits else 0, qc_id)


def build_checklist_report(
    plan: Any,
    sheets: Iterable[ChecklistSheet],
    answers: dict | None,
    findings: Iterable[Any],
) -> ChecklistReport:
    """Roll one run's checklist answers and final findings into a report.

    ``plan`` is the run's :class:`~drawing_analyzer.profiles.ChecklistPlan`;
    ``answers`` maps a sheet's ``source_page_key`` to ``{item id: [one answer
    per valid read]}`` (a sheet the critique never reached is simply absent);
    ``findings`` are the ledger's entries after verification.
    """
    sheets = list(sheets)
    answers = answers or {}
    # item id → sheet key → the findings standing against it there.
    cited: dict[str, dict[tuple, list[Any]]] = {}
    for finding in findings or []:
        item_ids = getattr(finding, "checklist_items", None) or ()
        if not item_ids:
            continue
        key = tuple(source_page_key(finding))
        for item_id in item_ids:
            cited.setdefault(item_id, {}).setdefault(key, []).append(finding)

    report = ChecklistReport(sheets=[s.label for s in sheets])
    in_scope = {s.ref_key: set(plan.for_key(s.ref_key).ids) for s in sheets}
    for item in plan.items:
        row = ChecklistRow(
            id=item.id, text=item.text, checklist=item.title, origin=item.origin,
            counts={status: 0 for status in CELL_PRECEDENCE},
        )
        for sheet in sheets:
            cell = _cell(item.id, sheet, in_scope, answers, cited.get(item.id, {}))
            row.cells.append(cell)
            row.counts[cell.status] += 1
            for qc_id in cell.qc_ids:
                if qc_id not in row.qc_ids:
                    row.qc_ids.append(qc_id)
        row.qc_ids.sort(key=_qc_sort_key)
        row.status = next(
            (status for status in CELL_PRECEDENCE if row.counts[status]),
            CELL_OUT_OF_SCOPE,
        )
        report.rows.append(row)
    return report


def _cell(
    item_id: str, sheet: ChecklistSheet, in_scope: dict, answers: dict, cited: dict,
) -> ChecklistCell:
    if item_id not in in_scope.get(sheet.ref_key, ()):
        return ChecklistCell(CELL_OUT_OF_SCOPE)
    sheet_answers = answers.get(tuple(sheet.key))
    reads = list((sheet_answers or {}).get(item_id) or [])
    against = cited.get(tuple(sheet.key), [])
    if against:
        # A finding is the evidence; it outranks whatever list the item sat in.
        standing = [f for f in against if not _is_rejected(f)]
        shown = standing or against
        qc_ids = sorted(
            {str(getattr(f, "qc_id", "") or "") for f in shown} - {""}, key=_qc_sort_key,
        )
        return ChecklistCell(
            CELL_VIOLATED if standing else CELL_REJECTED, qc_ids=qc_ids,
            reads_agree=len(set(reads)) <= 1,
        )
    if not reads:
        return ChecklistCell(CELL_NOT_REVIEWED)
    merged = merged_check_status(reads)
    if merged == CHECK_VIOLATED:
        # Called violated, but no finding reached the ledger (dropped as
        # invalid, past the cap, or never written): nothing to stand behind.
        return ChecklistCell(CELL_VIOLATED_NO_FINDING, reads_agree=len(set(reads)) <= 1)
    return ChecklistCell(_READ_TO_CELL[merged], reads_agree=len(set(reads)) <= 1)


# --------------------------------------------------------------------------- #
# checklist_matrix.csv
# --------------------------------------------------------------------------- #

_COUNT_COLUMNS: tuple[str, ...] = (
    CELL_VIOLATED, CELL_VIOLATED_NO_FINDING, CELL_UNDETERMINED, CELL_REJECTED,
    CELL_UNANSWERED, CELL_NOT_REVIEWED, CELL_MET, CELL_NOT_APPLICABLE,
    CELL_OUT_OF_SCOPE,
)


def build_checklist_csv(report: ChecklistReport, *, excel_safe: Any = None) -> str:
    """The item × sheet grid as CSV text (CRLF; the caller adds the BOM).

    One row per item: its result, how many sheets ended at each result, the
    findings against it, then one column per sheet. ``excel_safe`` neutralizes a
    cell Excel would read as a formula (the export passes its own).
    """
    safe = excel_safe or (lambda value: value)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(
        ["Item", "Checklist", "Source", "Check", "Result"]
        + [CELL_LABELS[c] for c in _COUNT_COLUMNS]
        + ["Findings"]
        + [safe(label) for label in report.sheets]
    )
    for row in report.rows:
        cells = []
        for cell in row.cells:
            text = CELL_LABELS[cell.status]
            if cell.qc_ids:
                text += " (" + ", ".join(cell.qc_ids) + ")"
            if not cell.reads_agree:
                text += " [reads differed]"
            cells.append(text)
        writer.writerow(
            [row.id, safe(row.checklist),
             "Model plan" if row.origin == "model" else "Your checklist",
             safe(row.text), CELL_LABELS[row.status]]
            + [row.counts.get(c, 0) for c in _COUNT_COLUMNS]
            + [", ".join(row.qc_ids)]
            + cells
        )
    return buf.getvalue()
