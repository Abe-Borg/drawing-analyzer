"""Deterministic auditors (Phase 14) — zero-API, high-precision QC checks.

The digest and critique passes *propose* findings a model saw; these auditors
*dispose* of a different class of defect entirely — the ones a model is unreliable
at but code is exact at:

* :mod:`.references` — stale / missing cross-sheet pointers (Phase 2, moved here);
* :mod:`.arithmetic` — numbers that don't add up (the host does the math on the
  claims the reviewer transcribed — no ``eval``, no trust in the model's math);
* :mod:`.naming` — the same thing tagged two ways across the set;
* :mod:`.titleblock` — a project/date field that drifts on one sheet;
* :mod:`.sheet_index` — a drawing index that disagrees with the actual set.

Every finding they emit is ``verification.status="DETERMINISTIC"`` — trusted
without a model re-check because the host computed it — and self-anchored (or, for
the arithmetic auditor, anchored via the pure resolver on the claim's quote).

:func:`run_auditors` runs the whole battery over a rendered set and returns the
combined findings plus a small stats tally (checks run / passed) for the report.
Each auditor is isolated so one raising never loses the others (I-3). The package
imports **no PDF engine** (I-5) — it works on the extracted word tuples.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..models import Finding, NumericClaim
from .arithmetic import audit_arithmetic
from .naming import audit_naming
from .references import SheetInventory, audit_references, build_inventory, detect_sheet_id
from .sheet_index import audit_sheet_index
from .titleblock import audit_titleblock

__all__ = [
    "AuditorResults",
    "run_auditors",
    "audit_references",
    "audit_arithmetic",
    "audit_naming",
    "audit_titleblock",
    "audit_sheet_index",
    "build_inventory",
    "detect_sheet_id",
    "SheetInventory",
]


@dataclass
class AuditorResults:
    """The deterministic-auditor battery's output: findings + a checks tally.

    ``findings`` are all ``DETERMINISTIC`` and (where a quote exists) anchored.
    ``stats`` counts what ran for the report — e.g. ``arithmetic_checked`` /
    ``arithmetic_matched`` back the "N numeric relationships checked ✓" line.
    """

    findings: list[Finding] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def run_auditors(
    rendered_sheets: Iterable[Any],
    *,
    claims: Iterable[NumericClaim] | None = None,
) -> AuditorResults:
    """Run every deterministic auditor over the set; combine findings + stats.

    ``claims`` (from the critique / cross-sheet QC passes) feed the arithmetic
    auditor; omit them and arithmetic simply contributes nothing. Each auditor runs
    inside its own guard so a single failure degrades to "that auditor found
    nothing" rather than sinking the battery (I-3). Findings are de-duplicated by
    content id (two auditors can't emit the same reference twice).
    """
    from ..diagnostics import get_logger

    log = get_logger()
    sheets = list(rendered_sheets)
    findings: list[Finding] = []
    stats: dict[str, int] = {}

    def _run(name: str, fn) -> list[Finding]:
        try:
            return list(fn())
        except Exception as exc:  # noqa: BLE001 - one auditor never sinks the rest
            log.warning("%s auditor failed: %s", name, exc)
            return []

    ref_findings = _run("reference", lambda: audit_references(sheets, stats=stats))
    stats["reference_findings"] = len(ref_findings)
    findings.extend(ref_findings)

    claim_list = list(claims or [])
    if claim_list:
        try:
            ares = audit_arithmetic(claim_list, sheets)
            findings.extend(ares.findings)
            stats.update({
                "arithmetic_checked": ares.checked,
                "arithmetic_matched": ares.matched,
                "arithmetic_mismatched": ares.mismatched,
                "arithmetic_unusable": ares.unusable,
            })
        except Exception as exc:  # noqa: BLE001
            log.warning("arithmetic auditor failed: %s", exc)

    naming_findings = _run("naming", lambda: audit_naming(sheets))
    stats["naming_findings"] = len(naming_findings)
    findings.extend(naming_findings)

    tb_findings = _run("titleblock", lambda: audit_titleblock(sheets))
    stats["titleblock_findings"] = len(tb_findings)
    findings.extend(tb_findings)

    idx_findings = _run("sheet_index", lambda: audit_sheet_index(sheets))
    stats["sheet_index_findings"] = len(idx_findings)
    findings.extend(idx_findings)

    # Collapse any exact-duplicate finding (same sheet + category + quote → same id)
    # two auditors might both surface — deterministic, first-wins order.
    seen: set[str] = set()
    deduped: list[Finding] = []
    for f in findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        deduped.append(f)

    log.info(
        "auditors: %d finding(s) [ref=%d arith=%d/%d naming=%d titleblock=%d index=%d]",
        len(deduped), stats.get("reference_findings", 0),
        stats.get("arithmetic_matched", 0), stats.get("arithmetic_checked", 0),
        stats.get("naming_findings", 0), stats.get("titleblock_findings", 0),
        stats.get("sheet_index_findings", 0),
    )
    return AuditorResults(findings=deduped, stats=stats)
