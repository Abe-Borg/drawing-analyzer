"""The findings ledger (Part III, §16) — one collection, nothing escapes it.

Every QC item from **every** channel — the digest's JSON findings, its prose
Coordination/Conflict items (harvested), the critique reads, the cross-sheet QC
pass, the synthesis prose, the deterministic auditors, opted-in focus items —
becomes a ledger entry. Downstream, the anchor resolver, the verification pass,
the citation check, the markup writer, the CSV/JSON exports, the HTML findings
table, and the index page consume the ledger and nothing else: **if an item is
not in the ledger it does not exist; if it is, the run-end coverage assertion
guarantees it is accounted for on the PDF** (clouded, margin callout, or listed
in the rejected index).

Ingest-time merge uses Phase 11's dedupe rule (same sheet AND anchor-rect
IoU > 0.5, same reported tile, OR normalized text overlap > 0.7): merging
**unions ``sources``**, keeps the most severe severity, prefers the longest
``source_quote`` (the best anchoring hook), and preserves the best anchor /
verification either member carries — an auditor's pre-anchored duplicate
upgrades a model entry rather than being lost, and a DETERMINISTIC verdict
survives the merge even when the auditor member has no rectangle (a rect-less
arithmetic mismatch is still host-computed ground truth). Multi-source
provenance doubles as a confidence signal, surfaced as chips
(``prose+json+critique×2``).

``freeze()`` assigns the run's sequential ``QC-###`` numbers (Phase 15's
numbering now lives here) ordered sheet → position. The ledger is append-only;
a post-freeze add is a programming error, but per I-3 it degrades (logged,
visibly numbered ``QC-XTRA-…``) rather than sinking the run.

PDF-engine-free (I-5): pure over :class:`~drawing_analyzer.models.Finding`.
"""
from __future__ import annotations

from typing import Iterable

from .critique import _is_duplicate, _most_severe
from .diagnostics import get_logger
from .models import Finding, assign_qc_ids

_log = get_logger()

# Provenance families — corroboration across *families* marks an entry
# ``reproduced`` (the same model restating itself within one read does not).
_FAMILIES = {
    "digest_json": "digest",
    "digest_prose_coordination": "digest",
    "digest_prose_conflict": "digest",
    "focus_prose": "digest",
    "critique_1": "critique",
    "critique_2": "critique",
    "cross_qc": "cross",
    "synthesis_prose": "synthesis",
    "auditor_reference": "auditor",
    "auditor_arithmetic": "auditor",
    "auditor_naming": "auditor",
    "auditor_titleblock": "auditor",
    "auditor_sheet_index": "auditor",
}

# Chip display order + labels for :func:`provenance_label`.
_CHIP_ORDER = ("prose", "json", "critique", "cross", "synthesis", "auditor", "focus")


def provenance_label(sources: Iterable[str]) -> str:
    """Compact provenance chip text, e.g. ``prose+json+critique×2``.

    Deterministic display order; the two critique reads collapse to
    ``critique×2`` (the self-consistency signal), a single read to ``critique``.
    Unknown tags are shown verbatim (better loud than lost).
    """
    tags = list(dict.fromkeys(sources or []))
    chips: dict[str, str] = {}
    extras: list[str] = []
    critique_reads = sum(1 for t in tags if t in ("critique_1", "critique_2"))
    for tag in tags:
        if tag in ("critique_1", "critique_2"):
            chips["critique"] = "critique×2" if critique_reads >= 2 else "critique"
        elif tag == "digest_json":
            chips["json"] = "json"
        elif tag in ("digest_prose_coordination", "digest_prose_conflict"):
            chips["prose"] = "prose"
        elif tag == "cross_qc":
            chips["cross"] = "cross"
        elif tag == "synthesis_prose":
            chips["synthesis"] = "synthesis"
        elif tag == "focus_prose":
            chips["focus"] = "focus"
        elif tag.startswith("auditor_"):
            chips["auditor"] = "auditor"
        else:
            extras.append(tag)
    ordered = [chips[k] for k in _CHIP_ORDER if k in chips]
    return "+".join(ordered + extras)


def _families(sources: Iterable[str]) -> set[str]:
    return {_FAMILIES.get(t, t) for t in (sources or [])}


class Ledger:
    """Append-only per-run findings collection with ingest-time dedup merge."""

    def __init__(self) -> None:
        self._entries: list[Finding] = []
        self._by_sheet: dict[tuple[str, int], list[Finding]] = {}
        self._frozen = False
        self._post_freeze_adds = 0

    @property
    def entries(self) -> list[Finding]:
        return list(self._entries)

    def entries_for(self, source_name: str, page_index: int) -> list[Finding]:
        """The ledger's entries for one sheet (the prose harvester's match pool)."""
        return list(self._by_sheet.get((source_name, int(page_index or 0)), []))

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------ add

    def add(self, findings: Iterable[Finding], source: str = "") -> None:
        """Ingest ``findings``, tagging provenance and merging duplicates.

        ``source`` is the default provenance tag for findings that don't already
        carry their own ``sources`` (the auditors stamp theirs at creation).
        Each finding is matched against the same-sheet entries already in the
        ledger; a duplicate merges (see :func:`_merge_into`), a fresh issue
        appends. Batch-internal duplicates merge too, since earlier items of the
        batch are already ledger entries by the time later ones arrive.
        """
        for finding in findings:
            if not finding.sources and source:
                finding.sources = [source]
            key = (finding.source_name, int(finding.page_index or 0))
            bucket = self._by_sheet.setdefault(key, [])
            existing = next(
                (e for e in bucket if _is_duplicate(finding, e)), None
            )
            if existing is not None:
                _merge_into(existing, finding)
                continue
            if self._frozen:
                # Programming error — everything should be ingested before the
                # freeze — but never sink a run over it (I-3): number it loudly
                # so the coverage tally and the report make the bug visible.
                self._post_freeze_adds += 1
                finding.qc_id = f"QC-XTRA-{self._post_freeze_adds}"
                _log.error(
                    "ledger: entry added after freeze (%s: %s) — numbered %s",
                    finding.source_name, finding.text[:60], finding.qc_id,
                )
            self._entries.append(finding)
            bucket.append(finding)

    # --------------------------------------------------------------- freeze

    def freeze(self) -> list[Finding]:
        """Assign the run's sequential ``QC-###`` numbers; return the entries.

        Idempotent: a second freeze re-derives the same numbers (the ordering is
        deterministic — I-7).
        """
        assign_qc_ids(self._entries)
        self._frozen = True
        return self.entries


def _merge_into(existing: Finding, incoming: Finding) -> Finding:
    """Fold a duplicate ``incoming`` into the ledger's ``existing`` entry.

    Field policy (§16): union ``sources`` (order-stable) and ``refs``; keep the
    most severe severity; prefer the **longest** ``source_quote`` (the best
    anchoring hook — adopting its ``tile`` alongside so tile-preference
    disambiguation still matches the quote); keep the first non-empty
    ``anchor_hint`` / ``also_on`` / ``citation``; and preserve the **best**
    anchor + verification — an entry that already carries a rectangle (an
    auditor's EXACT anchor and DETERMINISTIC verdict) upgrades an unanchored
    model entry, never the reverse, and a ``DETERMINISTIC`` verdict is kept
    regardless of rectangles (a rect-less auditor duplicate — say an arithmetic
    mismatch whose quote didn't resolve — must not lose its host-computed
    verdict to a model member). ``reproduced`` upgrades when the merged
    provenance spans two source *families* (cross-channel corroboration) or
    either member already was. The existing entry's ``id`` and ``text`` are kept
    (first-seen wins), so merged entries stay stable across runs.
    """
    for tag in incoming.sources:
        if tag not in existing.sources:
            existing.sources.append(tag)
    existing.severity = _most_severe([existing, incoming])
    if len(incoming.source_quote or "") > len(existing.source_quote or ""):
        existing.source_quote = incoming.source_quote
        if incoming.tile is not None:
            existing.tile = incoming.tile
    if existing.tile is None and incoming.tile is not None:
        existing.tile = incoming.tile
    for r in incoming.refs:
        if r not in existing.refs:
            existing.refs.append(r)
    if not existing.anchor_hint and incoming.anchor_hint:
        existing.anchor_hint = incoming.anchor_hint
    if not existing.also_on and incoming.also_on:
        existing.also_on = list(incoming.also_on)
    if existing.citation is None and incoming.citation is not None:
        existing.citation = incoming.citation

    existing_anchored = existing.anchor is not None and existing.anchor.rect_pdf is not None
    incoming_anchored = incoming.anchor is not None and incoming.anchor.rect_pdf is not None
    if incoming_anchored and not existing_anchored:
        existing.anchor = incoming.anchor
        if not _deterministic(existing):
            existing.verification = incoming.verification
    # A DETERMINISTIC verdict is host-computed ground truth: it survives the
    # merge no matter which member carries the rectangle.
    if _deterministic(incoming) and not _deterministic(existing):
        existing.verification = incoming.verification

    existing.reproduced = (
        existing.reproduced
        or incoming.reproduced
        or len(_families(existing.sources)) >= 2
    )
    return existing


def _deterministic(finding: Finding) -> bool:
    return (
        finding.verification is not None
        and finding.verification.status == "DETERMINISTIC"
    )
