"""Per-run findings collection with conservative ingest-time deduplication.

All finding channels feed this ledger. Merges require compatible signatures and
text agreement; position alone never establishes identity. Each merged entry
keeps one coherent text/quote/anchor/verdict bundle and unions provenance.

Lifecycle: ingest while OPEN, seal, anchor, then number by visual position.
Post-seal ingestion is counted as an orchestration failure. This module has
no PDF-engine dependency.
"""
from __future__ import annotations

import copy
from typing import Any, Iterable

from .critique import (
    _is_duplicate,
    _most_severe,
    _normalize,
    _norm_tokens,
    _severity_rank,
)
from .diagnostics import get_logger
from .models import (
    CONFIDENCE_NOT_APPLICABLE,
    CONFIDENCE_NOT_ASSESSED_PARTIAL,
    CONFIDENCE_REPRODUCED,
    CONFIDENCE_SINGLETON,
    Finding,
    assign_qc_ids,
    source_page_key,
)

_log = get_logger()

# Keep the strongest critique confidence; an unset value is weakest.
_CONFIDENCE_RANK = {
    "": 0,
    CONFIDENCE_NOT_APPLICABLE: 1,
    CONFIDENCE_NOT_ASSESSED_PARTIAL: 2,
    CONFIDENCE_SINGLETON: 3,
    CONFIDENCE_REPRODUCED: 4,
}

# Ingest while OPEN; anchor while SEALED; verify/export after NUMBERED.
OPEN, SEALED, NUMBERED = "OPEN", "SEALED", "NUMBERED"

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
    """Per-run findings with complete-link duplicate merging.

    Seal before anchoring and number afterward. Post-seal additions are recorded
    as orchestration failures so exhaustive QC cannot claim completeness.
    """

    def __init__(self) -> None:
        self._entries: list[Finding] = []
        self._by_sheet: dict[tuple[str, int], list[Finding]] = {}
        # Keep original member snapshots so a generic representative cannot hide
        # a conflicting quantity, tag or cross-sheet leg during complete-link merging.
        self._members: dict[int, list[Finding]] = {}
        # Every accepted duplicate shares a content token or normalized quote.
        # Index all members' signals, not just the current representative's.
        self._token_index: dict[tuple[str, int], dict[str, set[int]]] = {}
        self._quote_index: dict[tuple[str, int], dict[str, set[int]]] = {}
        self._state = OPEN
        self.post_seal_adds = 0
        self.merge_trace: list[dict] = []   # debug/run-metadata merge record (§12.2)

    @property
    def state(self) -> str:
        return self._state

    @property
    def sealed(self) -> bool:
        return self._state in (SEALED, NUMBERED)

    @property
    def entries(self) -> list[Finding]:
        return list(self._entries)

    def entries_for(self, sheet: Any) -> list[Finding]:
        """Return the source/page match pool; display sheet labels are not identity."""
        return list(self._by_sheet.get(source_page_key(sheet), []))

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------ add

    @staticmethod
    def _candidate_signals(finding: Finding) -> tuple[set[str], str]:
        tokens = _norm_tokens(finding.text or "") | _norm_tokens(
            finding.source_quote or ""
        )
        return tokens, _normalize(finding.source_quote or "")

    def _candidate_entries(
        self, key: tuple[str, int], finding: Finding, bucket: list[Finding]
    ) -> list[Finding]:
        tokens, quote = self._candidate_signals(finding)
        if not tokens and not quote:
            return bucket
        ids: set[int] = set()
        token_index = self._token_index.get(key, {})
        for token in tokens:
            ids.update(token_index.get(token, ()))
        if quote:
            ids.update(self._quote_index.get(key, {}).get(quote, ()))
        # Preserve historical bucket order: the first complete-link match still
        # wins, independent of dict/set ordering (I-7).
        return [entry for entry in bucket if id(entry) in ids]

    def _index_member(
        self, key: tuple[str, int], survivor: Finding, member: Finding
    ) -> None:
        tokens, quote = self._candidate_signals(member)
        sid = id(survivor)
        token_index = self._token_index.setdefault(key, {})
        for token in tokens:
            token_index.setdefault(token, set()).add(sid)
        if quote:
            self._quote_index.setdefault(key, {}).setdefault(quote, set()).add(sid)

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
            key = source_page_key(finding)
            bucket = self._by_sheet.setdefault(key, [])
            # Complete-link: merge only into an entry whose EVERY folded member is a
            # duplicate of ``finding`` (not merely the representative).
            existing = next(
                (
                    e for e in self._candidate_entries(key, finding, bucket)
                    if all(_is_duplicate(finding, m) for m in self._members.get(id(e), (e,)))
                ),
                None,
            )
            if self.sealed:
                # Post-seal input violates the lifecycle. Count it for the stage roll-up;
                # drop a duplicate rather than mutate already-numbered content.
                self.post_seal_adds += 1
                _log.error(
                    "ledger: finding %s after seal (%s: %s) — QC marked incomplete",
                    "merged" if existing is not None else "added",
                    finding.source_name, finding.text[:60],
                )
                if existing is not None:
                    continue
            elif existing is not None:
                # Snapshot both members before the merge changes the representative.
                self._freeze_history_head(existing)
                self._members.setdefault(id(existing), []).append(copy.deepcopy(finding))
                self._index_member(key, existing, finding)
                _merge_into(existing, finding, self.merge_trace)
                continue
            self._entries.append(finding)
            bucket.append(finding)
            # The entry is its own first member, held LIVE — see _freeze_history_head.
            self._members[id(finding)] = [finding]
            self._index_member(key, finding, finding)

    # --------------------------------------------------------- seal / number

    def seal(self) -> list[Finding]:
        """Close ingestion and return unnumbered entries; anchoring may now proceed."""
        self._state = SEALED
        return self.entries

    def number(self) -> list[Finding]:
        """Assign positional QC numbers after anchoring, then mark NUMBERED.

        Content breaks position ties, independent of arrival order. Repeating the
        call with unchanged findings produces the same numbers.
        """
        assign_qc_ids(self._entries)
        self._state = NUMBERED
        return self.entries

    def freeze(self) -> list[Finding]:
        """Seal and number together for callers that do not resolve anchors."""
        self.seal()
        return self.number()

    def member_history(self, entry: Finding) -> list[Finding]:
        """Return the members used to enforce complete-link merging.

        Merged members are snapshots from before the representative changed. An
        unmerged head remains live; unknown entries fall back to their own record.
        """
        return list(self._members.get(id(entry), (entry,)))

    def _freeze_history_head(self, entry: Finding) -> None:
        """Snapshot the original head before a merge changes its grounded bundle.

        Until then it remains live so added cross-sheet legs can block later merges.
        An already-frozen head is never replaced with a subsequent merge result.
        """
        history = self._members.get(id(entry))
        if history and history[0] is entry:
            history[0] = copy.deepcopy(entry)


def _grounding_quality(f: Finding) -> tuple:
    """Rank representatives by host-computed provenance, quote length, severity,
    id and text. Compare before mutating any ranked field. A deterministic verdict
    must remain attached to the host-computed text and quote.
    """
    return (
        1 if _deterministic(f) else 0,
        len((f.source_quote or "").strip()),
        _severity_rank(f.severity),
        f.id,
        f.text or "",
    )


def _placement_compatible(a: Finding, b: Finding) -> bool:
    """Whether ``b``'s rectangle may place ``a`` without cross-grounding (§12.2).

    A rect is resolved from its finding's quote, so adopting ``b``'s rect onto ``a``
    is coherent only when they anchor the *same* string — equal quotes, or one side
    has no quote to contradict. Two *different* quotes must never share a rectangle.
    """
    qa = _normalize(a.source_quote or "")
    qb = _normalize(b.source_quote or "")
    return not qa or not qb or qa == qb


def _add_supporting(existing: Finding, quote: str) -> None:
    q = (quote or "").strip()
    if not q:
        return
    if _normalize(q) == _normalize(existing.source_quote or ""):
        return
    if q not in existing.supporting_quotes:
        existing.supporting_quotes.append(q)


def _merge_into(existing: Finding, incoming: Finding, trace: list | None = None) -> Finding:
    """Merge provenance while retaining one coherent grounded bundle.

    The better representative supplies text, quote, tile, evidence and verdict
    together. Keep other quotes as support, union provenance/references/prose IDs,
    and retain the strongest severity and corroboration. An anchor can transfer
    only when it places the same quote; a verdict never transfers on its own.
    """
    # Choose before unioning severity or other fields used by the ranking.
    incoming_wins = _grounding_quality(incoming) > _grounding_quality(existing)

    if trace is not None:
        trace.append({
            "survivor": existing.id, "merged": incoming.id,
            "quote_switch": incoming_wins,
        })

    for tag in incoming.sources:
        if tag not in existing.sources:
            existing.sources.append(tag)
    existing.severity = _most_severe([existing, incoming])
    for r in incoming.refs:
        if r not in existing.refs:
            existing.refs.append(r)
    for q in incoming.supporting_quotes:
        _add_supporting(existing, q)
    # Retain prose IDs so harvest coverage cannot mistake a merged item for loss.
    for pid in incoming.prose_item_ids:
        if pid not in existing.prose_item_ids:
            existing.prose_item_ids.append(pid)
    # Keep the strongest self-consistency verdict either member carried (§14.4).
    if _CONFIDENCE_RANK.get(incoming.confidence, 0) > _CONFIDENCE_RANK.get(existing.confidence, 0):
        existing.confidence = incoming.confidence

    # Move the complete grounded bundle when the incoming representative wins.
    if incoming_wins:
        loser_quote = existing.source_quote
        loser_action = existing.recommended_action
        # Check placement compatibility before overwriting the old quote.
        existing_rect_places_winner = (
            existing.anchor is not None
            and existing.anchor.rect_pdf is not None
            and _placement_compatible(incoming, existing)
        )
        existing.sheet_id = incoming.sheet_id
        existing.category = incoming.category
        existing.text = incoming.text
        existing.source_quote = incoming.source_quote
        # The action belongs to the text it was written for — it rides the
        # bundle; the loser's action only backfills an empty winner (below).
        existing.recommended_action = incoming.recommended_action
        existing.tile = incoming.tile
        existing.anchor_hint = incoming.anchor_hint
        # Keep an existing rectangle only if it also places the winning quote.
        incoming_places = (
            incoming.anchor is not None and incoming.anchor.rect_pdf is not None
        )
        if incoming_places or not existing_rect_places_winner:
            existing.anchor = incoming.anchor
        # Evidence state belongs to the winning quote and moves with it.
        existing.evidence_state = incoming.evidence_state
        # A verdict belongs to the claim it checked; never lend it to different text.
        existing.verification = incoming.verification
        existing.id = incoming.id
        # The discriminator identifies the winning claim and moves with its text/id.
        existing.claim_discriminator = incoming.claim_discriminator
        _add_supporting(existing, loser_quote)
        if not existing.recommended_action:
            existing.recommended_action = loser_action
        # Do not backfill the losing claim's verdict onto an unverified winner.
    else:
        _add_supporting(existing, incoming.source_quote)
        if not existing.recommended_action:
            existing.recommended_action = incoming.recommended_action

    if not existing.also_on and incoming.also_on:
        existing.also_on = list(incoming.also_on)
    if existing.citation is None and incoming.citation is not None:
        existing.citation = incoming.citation

    # An incoming rectangle may place an unanchored survivor only for the same quote.
    existing_anchored = existing.anchor is not None and existing.anchor.rect_pdf is not None
    incoming_anchored = incoming.anchor is not None and incoming.anchor.rect_pdf is not None
    if incoming_anchored and not existing_anchored and _placement_compatible(existing, incoming):
        existing.anchor = incoming.anchor


    spans_families = len(_families(existing.sources)) >= 2
    existing.reproduced = (
        existing.reproduced
        or incoming.reproduced
        or spans_families
    )
    # Cross-family corroboration upgrades confidence to agree with reproduced.
    if spans_families:
        existing.confidence = CONFIDENCE_REPRODUCED
    return existing


def _deterministic(finding: Finding) -> bool:
    return (
        finding.verification is not None
        and finding.verification.status == "DETERMINISTIC"
    )
