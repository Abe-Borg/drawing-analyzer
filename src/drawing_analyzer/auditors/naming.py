"""Naming-consistency auditor (Phase 14) — zero API, catches tag drift.

Across a set, one physical thing should carry one tag. Copy-paste, hand edits,
and multiple authors erode that: a riser is ``C1-R`` on one sheet and ``C1R`` on
another; a zone printed ``A2`` everywhere shows up once as ``A1-2``. Each is a
low-severity *question* — probably the same thing named two ways — worth a mark
so the engineer can reconcile it before issue.

The auditor harvests the set's tag lexicon from the text layers, clusters tags
that share an **alphabet shape** (their letters, in order) and sit within a small
edit distance, and inside each cluster flags the *rare* spellings against the
*established* one. The established-vs-rare test is what keeps a legitimately
distinct vocabulary (``A1`` / ``A2`` / ``A3``, each used many times) from being
flagged, while still catching the one-off ``A1-2`` that drifts from it. Every
flagged occurrence is anchored on its sheet (``EXACT``, ``DETERMINISTIC``).

PDF-engine-free (I-5): pure over the extracted word tuples.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..models import Anchor, Finding, Verification, source_page_key
from .references import (
    SheetInventory,
    _levenshtein,
    _wrect,
    _wtext,
    build_inventory,
)

# A tag candidate: an alphanumeric token (internal ``-`` / ``/`` allowed) that
# carries BOTH a letter and a digit — the shape of a zone/equipment/system tag,
# which excludes bare words and bare numbers. Length-bounded so prose and long
# codes don't flood the lexicon.
_TAG_RE = re.compile(r"^[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*$")
_TAG_MIN_LEN = 2
_TAG_MAX_LEN = 12

# Clustering thresholds.
_EDIT_DISTANCE_MAX = 2          # tags within this edit distance may be the same thing
# A tag with at least this many occurrences is "established" vocabulary; a cluster
# needs an established member before its rarer siblings are called drift.
_DOMINANT_MIN_FREQ_DEFAULT = 2
# A tag is only ever flagged as drift when it is this rare (a frequent tag is its
# own convention, even if a more frequent sibling exists).
_DRIFT_MAX_FREQ_DEFAULT = 2
# Backstop so a pathological set can't emit unbounded naming findings.
_MAX_FINDINGS = 200


def _dominant_min_freq() -> int:
    return _env_int("DRAWING_ANALYZER_NAMING_DOMINANT_MIN_FREQ", _DOMINANT_MIN_FREQ_DEFAULT)


def _drift_max_freq() -> int:
    return _env_int("DRAWING_ANALYZER_NAMING_DRIFT_MAX_FREQ", _DRIFT_MAX_FREQ_DEFAULT)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw and raw.strip():
        try:
            return max(1, int(raw.strip()))
        except ValueError:
            pass
    return default


def _cluster_key(tag: str) -> tuple[tuple[str, ...], str]:
    """The tag's (letters, digits) identity — its meaning-preserving cluster key.

    Two tags cluster only when BOTH their letters (in order) AND their digit
    content match, so a cluster contains spellings of *one* thing that differ
    only in separators / formatting: ``C1R`` and ``C1-R`` share
    ``(("C", "R"), "1")`` and cluster, while ``A1-2`` (``(("A",), "12")``) and
    ``A2`` (``(("A",), "2")``) differ in digit content and do NOT merge — a
    changed number is meaning-bearing, not a spelling drift (§17.4). ``C1R``
    never merges with ``D1R`` (different letters) either. Digits are compared as a
    single concatenated sequence so ``A1-2`` still matches ``A12`` (same digits,
    a real formatting drift) but never ``A2``.
    """
    letters = tuple(ch.upper() for ch in tag if ch.isalpha())
    digits = "".join(ch for ch in tag if ch.isdigit())
    return (letters, digits)


def _looks_like_tag(token: str) -> bool:
    t = token.strip()
    if not (_TAG_MIN_LEN <= len(t) <= _TAG_MAX_LEN):
        return False
    if not _TAG_RE.match(t):
        return False
    return any(c.isalpha() for c in t) and any(c.isdigit() for c in t)


@dataclass
class _TagOccurrences:
    total: int = 0
    # source_page_key(ref) -> (geom, first_rect, count_on_sheet)
    by_sheet: dict = field(default_factory=dict)


def _harvest(sheets: list[Any], inventory: SheetInventory) -> dict[str, _TagOccurrences]:
    """Collect every tag token's occurrences across the set (sheet IDs excluded)."""
    lexicon: dict[str, _TagOccurrences] = defaultdict(_TagOccurrences)
    for geom in sheets:
        ref = getattr(geom, "ref", None)
        if ref is None:
            continue
        key = source_page_key(ref)
        for w in getattr(geom, "words", []) or []:
            raw = _wtext(w)
            if not _looks_like_tag(raw):
                continue
            tag = raw.strip().upper()
            if tag in inventory.ids:      # a sheet's own id — references/index own those
                continue
            occ = lexicon[tag]
            occ.total += 1
            if key not in occ.by_sheet:
                occ.by_sheet[key] = [geom, _wrect(w), 1]
            else:
                occ.by_sheet[key][2] += 1
    return lexicon


def _cluster_tags(tags: list[str]) -> list[list[str]]:
    """Group tags that share a (letters, digits) key — i.e. one thing spelled
    several ways, differing only in separators / formatting (§17.4).

    Same key means identical letters AND identical digit content, so no
    edit-distance clustering is needed (or wanted): a difference in the digits
    themselves — ``A1-2`` vs ``A2`` — lands in *different* keys and is never
    merged. Groups are returned sorted for deterministic assembly (I-7).
    """
    by_key: dict[tuple, list[str]] = defaultdict(list)
    for t in tags:
        by_key[_cluster_key(t)].append(t)
    clusters = [sorted(members) for members in by_key.values() if len(members) > 1]
    return sorted(clusters, key=lambda c: c[0])


def _drift_pairs(
    cluster: list[str], counts: dict[str, int]
) -> list[tuple[str, str]]:
    """``(drift_tag, canonical_tag)`` pairs within one cluster.

    A clear winner (a member at/above the dominant-min frequency) makes every
    rare-enough sibling drift; with no clear winner (all spellings rare) the
    lexicographically-first spelling is the reference and the rest are drift. The
    suggested canonical for a drift tag is the established spelling closest to it
    by edit distance (ties → more frequent, then lexicographic).
    """
    if len(cluster) < 2:
        return []
    dominant = max(counts[t] for t in cluster)
    dominant_min = _dominant_min_freq()
    drift_max = _drift_max_freq()
    established = [t for t in cluster if counts[t] >= dominant_min] or [
        min(cluster)  # no clear winner — the first spelling anchors the cluster
    ]
    established_set = set(established)

    def suggest(drift: str) -> str:
        return min(
            established,
            key=lambda e: (_levenshtein(drift, e), -counts[e], e),
        )

    pairs: list[tuple[str, str]] = []
    for tag in sorted(cluster):
        if tag in established_set:
            continue
        if dominant >= dominant_min:
            if counts[tag] < dominant and counts[tag] <= drift_max:
                pairs.append((tag, suggest(tag)))
        else:
            # all rare: every non-reference spelling is a drift candidate
            pairs.append((tag, suggest(tag)))
    return pairs


def audit_naming(rendered_sheets: Iterable[Any]) -> list[Finding]:
    """Flag tag-naming drift across the set; return low-severity question findings.

    One finding per (drift tag, sheet), anchored ``EXACT`` at the tag's first
    occurrence on that sheet and verified ``DETERMINISTIC``. Deterministic and
    side-effect-free; a raster sheet (no words) contributes nothing.
    """
    sheets = list(rendered_sheets)
    inventory = build_inventory(sheets)
    lexicon = _harvest(sheets, inventory)
    if len(lexicon) < 2:
        return []
    counts = {tag: occ.total for tag, occ in lexicon.items()}

    findings: list[Finding] = []
    truncated = False
    for cluster in _cluster_tags(list(lexicon.keys())):
        for drift, canonical in _drift_pairs(cluster, counts):
            occ = lexicon[drift]
            for _key, (geom, rect, count_on_sheet) in sorted(
                occ.by_sheet.items()
            ):
                if len(findings) >= _MAX_FINDINGS:
                    truncated = True
                    break
                ref = geom.ref
                sheet_id_disp = _sheet_display_id(geom, inventory)
                here = f" (used {count_on_sheet}× here)" if count_on_sheet > 1 else ""
                findings.append(Finding(
                    sheet_id=sheet_id_disp,
                    source_name=ref.source_name,
                    source_id=ref.source_id,
                    page_index=ref.page_index,
                    category="question",
                    severity="low",
                    text=(
                        f"Tag '{drift}' may be an inconsistent spelling of '{canonical}', "
                        f"used elsewhere in the set{here}. Confirm they refer to the "
                        f"same item and standardize the label."
                    ),
                    source_quote=drift,
                    recommended_action="Confirm both spellings refer to the "
                                       "same item and standardize the tag.",
                    refs=[],
                    anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="naming"),
                    verification=Verification(
                        status="DETERMINISTIC",
                        note=f"naming drift: '{drift}' vs established '{canonical}'",
                    ),
                    sources=["auditor_naming"],
                ))
            if truncated:
                break
        if truncated:
            break
    if truncated:
        from ..diagnostics import get_logger

        get_logger().info("naming auditor: capped at %d finding(s)", _MAX_FINDINGS)
    return findings


def _sheet_display_id(geom: Any, inventory: SheetInventory) -> str:
    from .references import detect_sheet_id

    ref = geom.ref
    return detect_sheet_id(geom) or f"{_stem(ref.source_name)}-p{ref.page_index + 1}"


def _stem(source_name: str) -> str:
    from pathlib import Path

    return Path(source_name).stem
