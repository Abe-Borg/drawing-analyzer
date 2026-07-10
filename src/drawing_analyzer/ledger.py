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

Ingest-time merge (Pass A, §12.1) is **conservative and lossless**: two findings
merge only when they are semantically the same *and* their critical signatures are
compatible — a tile is a search hint, never identity, and geometric overlap alone
is never sufficient (see :func:`~drawing_analyzer.critique._is_duplicate`).
Conflicting signatures — ``500 gpm`` vs ``550 gpm``, ``M-101`` vs ``M-102``,
``shown`` vs ``not shown``, or different cross-sheet legs — block the merge even
when the prose is similar. Merging keeps **coherent grounding** (§12.2): the
grounded bundle (``text`` / ``category`` / ``source_quote`` / ``tile`` / ``anchor``)
comes from one representative atomically — never one finding's text paired with
another's quote — while the loser's quote is preserved in ``supporting_quotes``.
It **unions ``sources``** / ``refs``, keeps the most severe severity, and preserves
the best anchor / DETERMINISTIC verdict either member carries. Multi-source
provenance doubles as a confidence signal, surfaced as chips
(``prose+json+critique×2``).

**Lifecycle** (§12.3/§12.4): ``OPEN`` while every channel ingests →
:meth:`Ledger.seal` (``SEALED``: no new entries; anchoring + a cautious
:func:`reconcile_post_anchor` Pass B may run) → :meth:`Ledger.number` (``NUMBERED``:
the run's positional ``QC-###`` ids, assigned **after** anchoring so they follow
visual order). A post-seal add is an orchestration invariant failure — recorded on
:attr:`Ledger.post_seal_adds` and marking exhaustive QC incomplete, never a
fabricated ``QC-XTRA`` masquerade. (:meth:`Ledger.freeze` seals + numbers in one
call for simple callers that don't anchor.)

PDF-engine-free (I-5): pure over :class:`~drawing_analyzer.models.Finding`.
"""
from __future__ import annotations

from typing import Any, Iterable

from .critique import _is_duplicate, _most_severe, _normalize, _severity_rank
from .diagnostics import get_logger
from .models import Finding, assign_qc_ids, source_page_key

_log = get_logger()

# The ledger's lifecycle (§12.3). Ingestion happens while OPEN; SEALED permits
# anchoring + post-anchor reconciliation but no new entries; NUMBERED means the
# run's QC-### ids are assigned and verification / citation / writing may proceed.
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
    """Append-only per-run findings collection with ingest-time dedup merge.

    Lifecycle (§12.3): ``OPEN`` (ingesting) → ``seal()`` → ``SEALED`` (anchor +
    reconcile) → ``number()`` → ``NUMBERED`` (QC ids assigned). A post-seal add is
    an orchestration invariant failure — it is recorded on :attr:`post_seal_adds`
    and marks exhaustive QC incomplete, never silently numbered as ordinary output.
    """

    def __init__(self) -> None:
        self._entries: list[Finding] = []
        self._by_sheet: dict[tuple[str, int], list[Finding]] = {}
        # Folded members per surviving entry (keyed by object identity), so a new
        # candidate must be a duplicate of EVERY member — complete-link (§12.1) —
        # not just the representative, blocking an A+B+C collapse where A conflicts
        # with C. Runtime-only; never serialized.
        self._members: dict[int, list[Finding]] = {}
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
        """The ledger's entries for one sheet (the prose harvester's match pool).

        Keyed collision-safely on ``source_page_key`` — pass any source-scoped
        object (a ``SheetRef``, a geometry with ``.ref``, or a ``Finding``); two
        same-basename sheets from different inputs never share a match pool
        (DA-001).
        """
        return list(self._by_sheet.get(source_page_key(sheet), []))

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
            key = source_page_key(finding)
            bucket = self._by_sheet.setdefault(key, [])
            # Complete-link: merge only into an entry whose EVERY folded member is a
            # duplicate of ``finding`` (not merely the representative).
            existing = next(
                (
                    e for e in bucket
                    if all(_is_duplicate(finding, m) for m in self._members.get(id(e), (e,)))
                ),
                None,
            )
            if existing is not None:
                _merge_into(existing, finding, self.merge_trace)
                self._members.setdefault(id(existing), [existing]).append(finding)
                continue
            if self.sealed:
                # Orchestration invariant failure (§12.3): everything must be
                # ingested before the seal. Never sink a run over it (I-3), but do
                # NOT fabricate a QC-XTRA number that reads like ordinary output —
                # count it so the roll-up marks exhaustive QC incomplete.
                self.post_seal_adds += 1
                _log.error(
                    "ledger: entry added after seal (%s: %s) — QC marked incomplete",
                    finding.source_name, finding.text[:60],
                )
            self._entries.append(finding)
            bucket.append(finding)
            self._members[id(finding)] = [finding]

    # --------------------------------------------------------- seal / number

    def seal(self) -> list[Finding]:
        """Close ingestion (§12.3): OPEN → SEALED. Anchoring and post-anchor
        reconciliation are permitted after this; new entries are an invariant
        failure. Returns the entries (unnumbered). Idempotent."""
        self._state = SEALED
        return self.entries

    def number(self) -> list[Finding]:
        """Assign the run's sequential ``QC-###`` numbers (§12.4): SEALED → NUMBERED.

        Must be called **after** anchoring so the ordering is *positional* (source
        input order → page → anchored-before-unanchored → top → left → stable id).
        Idempotent: a second call re-derives the same numbers (deterministic — I-7).
        """
        assign_qc_ids(self._entries)
        self._state = NUMBERED
        return self.entries

    def freeze(self) -> list[Finding]:
        """Back-compat: seal **and** number in one call (pre-Phase-20 callers).

        The pipeline now seals, anchors, reconciles, then numbers separately so QC
        ids are positional. Tests and simple callers that don't anchor can still
        ``freeze()`` to get numbered entries in one step.
        """
        self.seal()
        return self.number()

    def drop_entry(self, entry: Finding) -> None:
        """Remove one entry (post-anchor reconciliation folds a duplicate away).

        Only valid while SEALED and before numbering — a reconciliation pass merges
        two entries the ingest pass couldn't (it lacked anchors) and drops the
        loser. Numbering then sees the reduced set.
        """
        try:
            self._entries.remove(entry)
        except ValueError:
            return
        key = source_page_key(entry)
        bucket = self._by_sheet.get(key)
        if bucket and entry in bucket:
            bucket.remove(entry)
        self._members.pop(id(entry), None)


def _grounding_quality(f: Finding) -> tuple:
    """Deterministic quality of a finding's grounded bundle, for representative
    selection: a longer quote anchors better; more severe wins ties; then the stable
    id and finally the text — a **total** order even when two duplicates share a
    quote-derived id, so the same cluster picks the same representative regardless of
    ingest order (§12.4 test 6)."""
    return (len((f.source_quote or "").strip()), _severity_rank(f.severity), f.id, f.text or "")


def _add_supporting(existing: Finding, quote: str) -> None:
    q = (quote or "").strip()
    if not q:
        return
    if _normalize(q) == _normalize(existing.source_quote or ""):
        return
    if q not in existing.supporting_quotes:
        existing.supporting_quotes.append(q)


def _merge_into(existing: Finding, incoming: Finding, trace: list | None = None) -> Finding:
    """Fold a duplicate ``incoming`` into the ledger's ``existing`` entry (§12.2).

    **Coherent grounding.** The grounded fields — ``text`` / ``category`` /
    ``source_quote`` / ``tile`` / ``anchor_hint`` / ``id`` — move together as an
    **atomic bundle** from whichever member is the better representative (by
    :func:`_grounding_quality`); a merge never pairs one finding's text with a
    *different* finding's quote. The loser's distinct quote is kept in
    ``supporting_quotes``, never spliced onto the survivor's text. Because the
    winner is chosen by a total quality order (not first-seen), the final entry — and
    its id — is the same regardless of ingest order.

    Field policy (§16): union ``sources`` (order-stable), ``refs``, and
    ``supporting_quotes``; keep the most severe severity; keep the first non-empty
    ``also_on`` / ``citation``; and preserve the **best** anchor + verification — an
    entry that already carries a rectangle (an auditor's EXACT anchor and
    DETERMINISTIC verdict) upgrades an unanchored model entry, never the reverse,
    and a ``DETERMINISTIC`` verdict is kept regardless of rectangles. ``reproduced``
    upgrades when the merged provenance spans two source *families* or either member
    already was.
    """
    if trace is not None:
        trace.append({
            "survivor": existing.id, "merged": incoming.id,
            "quote_switch": _grounding_quality(incoming) > _grounding_quality(existing),
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

    # Coherent grounding: if ``incoming`` is the better representative, adopt its
    # WHOLE bundle atomically; either way the loser's quote becomes support.
    if _grounding_quality(incoming) > _grounding_quality(existing):
        loser_quote = existing.source_quote
        existing.sheet_id = incoming.sheet_id
        existing.category = incoming.category
        existing.text = incoming.text
        existing.source_quote = incoming.source_quote
        existing.tile = incoming.tile
        existing.anchor_hint = incoming.anchor_hint
        existing.id = incoming.id
        _add_supporting(existing, loser_quote)
    else:
        _add_supporting(existing, incoming.source_quote)

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


def reconcile_post_anchor(ledger: "Ledger") -> int:
    """Pass B (§12.1): with anchors resolved, fold any newly-evident duplicates.

    The ingest pass (Pass A) runs *before* anchoring, so it can only use quote/text.
    Now that entries carry rectangles, two entries on the same sheet whose rects
    overlap **and** which agree on text/quote and critical signatures can be seen as
    one issue the digest and critique reported at slightly different phrasings.
    Geometry is only *supporting* evidence (see :func:`_is_duplicate`), so unrelated
    findings sharing a table cell are never collapsed. The lower-quality member is
    merged into the survivor and dropped; deterministic (best-quality survivor,
    fixed order). Returns the number of entries folded. Only runs while SEALED.
    """
    if not ledger.sealed:
        return 0
    by_sheet: dict[tuple, list[Finding]] = {}
    for e in ledger.entries:
        by_sheet.setdefault(source_page_key(e), []).append(e)

    folded = 0
    for _key, group in sorted(by_sheet.items()):
        # Best-first, stable — so the survivor is the highest-quality member and the
        # merge keeps its (better) grounding bundle.
        group.sort(key=_grounding_quality, reverse=True)
        survivors: list[Finding] = []
        for e in group:
            match = next((s for s in survivors if _is_duplicate(e, s)), None)
            if match is not None:
                _merge_into(match, e, ledger.merge_trace)
                ledger.drop_entry(e)
                folded += 1
            else:
                survivors.append(e)
    if folded:
        _log.info("post-anchor reconciliation folded %d duplicate finding(s)", folded)
    return folded
