"""Checklist results roll-up: per-sheet answers + final findings → one report.

Pure module, so these build the three inputs by hand: a ``ChecklistPlan``, the
per-sheet answers the critique stage collects, and ledger-shaped findings.
"""
from __future__ import annotations

import csv
import io

import pytest

from drawing_analyzer import checklist_matrix as CM
from drawing_analyzer import profiles as P
from drawing_analyzer.models import Finding, Verification

_SHEETS = [
    CM.ChecklistSheet(key=("SRC-0001", 0), ref_key=("a.pdf", 0), label="FP-101"),
    CM.ChecklistSheet(key=("SRC-0001", 1), ref_key=("a.pdf", 1), label="FP-102"),
    CM.ChecklistSheet(key=("SRC-0002", 0), ref_key=("b.pdf", 0), label="E-201"),
]


def _plan():
    fp = P.Profile(name="fp", title="Sprinkler QC", disciplines=("fp",),
                   items=("Relief valve setpoint", "=FDC sign names the area"))
    return P.ChecklistPlan([fp], {
        ("a.pdf", 0): P.SheetScope(token="fp"),
        ("a.pdf", 1): P.SheetScope(token="fp"),
        ("b.pdf", 0): P.SheetScope(token="e"),
    })


def _finding(item_ids, *, page=0, qc="QC-007", status="VERIFIED"):
    f = Finding(sheet_id="FP-101", source_name="a.pdf", source_id="SRC-0001",
                page_index=page, category="code", severity="high", text="t",
                verification=Verification(status=status), qc_id=qc)
    f.checklist_items = list(item_ids)
    return f


@pytest.mark.parametrize("reads, findings, cell, qc_ids", [
    # A standing finding is what makes a violation, whatever the reads listed.
    (["MET", "MET"], [_finding(["U1.1"])], CM.CELL_VIOLATED, ["QC-007"]),
    (["VIOLATED", "MET"], [_finding(["U1.1"], qc="QC-010"), _finding(["U1.1"], qc="QC-002")],
     CM.CELL_VIOLATED, ["QC-002", "QC-010"]),
    # Every finding against it was rejected on verification: not a violation.
    (["VIOLATED", "VIOLATED"], [_finding(["U1.1"], status="REJECTED")],
     CM.CELL_REJECTED, ["QC-007"]),
    # One rejected and one standing: the standing one decides, and is the one shown.
    (["VIOLATED"], [_finding(["U1.1"], status="REJECTED", qc="QC-001"),
                    _finding(["U1.1"], qc="QC-002")], CM.CELL_VIOLATED, ["QC-002"]),
    # Called violated but no finding reached the ledger: nothing to stand behind.
    (["VIOLATED", "MET"], [], CM.CELL_VIOLATED_NO_FINDING, []),
    # A finding on ANOTHER sheet does not make this sheet's item violated.
    (["MET", "MET"], [_finding(["U1.1"], page=1)], CM.CELL_MET, []),
    (["MET", "UNDETERMINED"], [], CM.CELL_UNDETERMINED, []),
    (["MET", "NOT_APPLICABLE"], [], CM.CELL_MET, []),
    (["NOT_APPLICABLE", "UNANSWERED"], [], CM.CELL_NOT_APPLICABLE, []),
    (["UNANSWERED", "UNANSWERED"], [], CM.CELL_UNANSWERED, []),
    ([], [], CM.CELL_NOT_REVIEWED, []),            # the sheet had no valid read
])
def test_one_item_on_one_sheet(reads, findings, cell, qc_ids):
    answers = {("SRC-0001", 0): {"U1.1": reads, "U1.2": ["MET"] * len(reads)}}
    report = CM.build_checklist_report(_plan(), _SHEETS, answers, findings)
    first = report.rows[0].cells[0]
    assert (first.status, first.qc_ids) == (cell, qc_ids)


def test_set_level_result_counts_and_csv():
    answers = {
        ("SRC-0001", 0): {"U1.1": ["MET", "MET"], "U1.2": ["MET", "NOT_APPLICABLE"]},
        # FP-102 was never reached by the critique → absent → not reviewed.
        ("SRC-0002", 0): {},
    }
    report = CM.build_checklist_report(
        _plan(), _SHEETS, answers, [_finding(["U1.1"])],
    )
    row = report.rows[0]
    # One sheet violated, one never reviewed, one outside the checklist's scope.
    assert row.status == CM.CELL_VIOLATED and row.qc_ids == ["QC-007"]
    assert (row.counts[CM.CELL_VIOLATED], row.counts[CM.CELL_NOT_REVIEWED],
            row.counts[CM.CELL_OUT_OF_SCOPE]) == (1, 1, 1)
    # Met on one sheet, unreviewed on another: the unreviewed sheet decides.
    assert report.rows[1].status == CM.CELL_NOT_REVIEWED
    assert report.cell_total(CM.CELL_NOT_REVIEWED) == 2
    data = report.to_dict()
    assert data["totals"] == {CM.CELL_VIOLATED: 1, CM.CELL_NOT_REVIEWED: 1}
    assert data["rows"][0]["findings"] == ["QC-007"]

    grid = list(csv.reader(io.StringIO(CM.build_checklist_csv(
        report, excel_safe=lambda v: "'" + v if str(v).startswith("=") else v,
    ))))
    header, first, second = grid
    cells = dict(zip(header, first))
    assert cells["Result"] == "Violated" and cells["Findings"] == "QC-007"
    assert (cells["FP-101"], cells["FP-102"], cells["E-201"]) == (
        "Violated (QC-007)", "Not reviewed", "Out of scope",
    )
    # A split between the reads is disclosed on the cell; a formula-shaped
    # item is neutralized for Excel.
    assert dict(zip(header, second))["FP-101"] == "Reported met [reads differed]"
    assert dict(zip(header, second))["Check"].startswith("'=")


def test_no_checklist_builds_an_empty_report():
    report = CM.build_checklist_report(P.ChecklistPlan([]), _SHEETS, {}, [])
    assert not report and report.to_dict()["items"] == 0
