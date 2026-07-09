"""Backward-compatibility shim for the reference auditor.

Phase 14 grew the single reference-audit module into an :mod:`~drawing_analyzer.
auditors` package; the reference auditor's canonical home is now
:mod:`drawing_analyzer.auditors.references`. This module re-exports its public
surface (and the handful of private helpers older call sites and tests reference)
so existing imports — ``from drawing_analyzer.reference_audit import
audit_references`` — keep working unchanged. New code should import from
:mod:`drawing_analyzer.auditors` (which also exposes :func:`run_auditors`, the
whole-set deterministic-auditor orchestrator).
"""
from __future__ import annotations

from .auditors.references import (  # noqa: F401 - re-exported for back-compat
    MALFORMED,
    MISSING_FROM_SET,
    RESOLVED_IN_SET,
    SheetInventory,
    _levenshtein,
    _looks_like_sheet_id,
    _normalize_id,
    _normalize_text,
    _resolve,
    _segment_shape,
    audit_references,
    build_inventory,
    detect_sheet_id,
)

__all__ = [
    "MALFORMED",
    "MISSING_FROM_SET",
    "RESOLVED_IN_SET",
    "SheetInventory",
    "audit_references",
    "build_inventory",
    "detect_sheet_id",
]
