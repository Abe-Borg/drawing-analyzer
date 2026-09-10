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

# Strength order for merging two findings' self-consistency verdicts — the merged
# entry keeps the strongest corroboration either member carried (§14.4). "" (unset,
# non-critique channels) is weakest.
_CONFIDENCE_RANK = {
    "": 0,
    CONFIDENCE_NOT_APPLICABLE: 1,
    CONFIDENCE_NOT_ASSESSED_PARTIAL: 2,
    CONFIDENCE_SINGLETON: 3,
    CONFIDENCE_REPRODUCED: 4,
}

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
        # with C. Stored as **immutable snapshots** (deep copies) taken at ingest,
        # because ``_merge_into`` mutates the live survivor when a higher-quality
        # member wins — the live object would otherwise erase the earlier member's
        # signature from this history. Runtime-only; never serialized.
        self._members: dict[int, list[Finding]] = {}
        # Conservative per-sheet candidate indexes.  Every duplicate accepted by
        # ``_is_duplicate`` either shares at least one normalized content token
        # (its text-overlap branches) or the exact normalized source quote (its
        # geometry branch).  Indexing those signals avoids comparing a new item
        # with every unrelated finding while the unchanged final predicate below
        # remains the authority.  Indexes retain every folded member's signals so
        # complete-link history cannot become undiscoverable after a representative
        # bundle changes.
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
                # Orchestration invariant failure (§12.3): everything must be
                # ingested before the seal. Never sink a run over it (I-3), but do
                # NOT fabricate a QC-XTRA number that reads like ordinary output —
                # count it so the roll-up marks exhaustive QC incomplete.
                #
                # A post-seal DUPLICATE is the same violation and the more
                # damaging half of it, and it used to reach neither this counter
                # nor this log: the merge branch above returned first, so the
                # guard was reachable only for a *fresh* finding. The merge then
                # rewrote text, quote, content id, severity, sources and anchor
                # underneath a QC-### that numbering had already assigned — and
                # that a reviewed PDF, an index row and an evidence directory
                # (both derived from ``qc_id``/``id``) may already point at. The
                # number is a promise about specific content, so a post-seal
                # duplicate is counted and DROPPED rather than folded in.
                self.post_seal_adds += 1
                _log.error(
                    "ledger: finding %s after seal (%s: %s) — QC marked incomplete",
                    "merged" if existing is not None else "added",
                    finding.source_name, finding.text[:60],
                )
                if existing is not None:
                    continue
            elif existing is not None:
                # Freeze the survivor as it stands and snapshot the incoming member,
                # both BEFORE the merge mutates anything, so the complete-link history
                # keeps every member's original signature.
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

    def member_history(self, entry: Finding) -> list[Finding]:
        """Every member ``entry`` absorbed, plus ``entry``'s own record of itself.

        The complete-link guarantee (§12.1) is evaluated against what each
        member looked like when it arrived, because ``_merge_into`` mutates the
        survivor whenever a higher-quality member wins the bundle. Folded
        members are therefore immutable snapshots; the head is ``entry`` itself,
        live until a merge is about to change it (see
        :meth:`_freeze_history_head`). Falls back to the live entry alone for a
        finding this ledger never ingested.
        """
        return list(self._members.get(id(entry), (entry,)))

    def _freeze_history_head(self, entry: Finding) -> None:
        """Replace a live self-reference in ``entry``'s history with a snapshot.

        An entry is its own first member, and it is held **live** until a merge
        is about to mutate it. Copying it eagerly at ingest looks equivalent and
        is not, in a way only Pass B can see: anchors are resolved *after*
        ingest, so an eager copy is a permanently **unanchored** twin of a live,
        anchored entry — and ``_is_duplicate``'s geometry branch, which needs a
        rectangle on both sides, could then never fire against it. Pass B
        stopped folding rect-overlap duplicates entirely.

        Frozen here instead: at the one moment the live object stops being an
        accurate record of what it was, which is exactly the reason the
        snapshots exist (``_merge_into`` hands the whole grounded bundle to a
        higher-quality member). Idempotent — a head already frozen stays frozen,
        so a second merge cannot capture the first merge's result as history.
        """
        history = self._members.get(id(entry))
        if history and history[0] is entry:
            history[0] = copy.deepcopy(entry)

    def adopt_members(self, survivor: Finding, folded: Finding) -> None:
        """Re-parent ``folded``'s ingest history onto ``survivor`` before a drop.

        Post-anchor reconciliation folds an entry the ingest pass could not, so
        the survivor inherits responsibility for everything the loser had
        absorbed. Without this the history is silently narrowed by the very pass
        that widened the cluster. Call it BEFORE the merge: it freezes the
        survivor's own head for the same reason the ingest path does.
        """
        if survivor is folded:
            return
        self._freeze_history_head(survivor)
        history = self._members.setdefault(id(survivor), [copy.deepcopy(survivor)])
        for member in self._members.get(id(folded), (folded,)):
            history.append(copy.deepcopy(member))

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
    selection.

    Ranked, most significant first:

    1. **Host-computed provenance.** A ``DETERMINISTIC`` member's text states the
       result of a host computation over its own quote (§17.5, "the model never
       calculates"). It must win the representative, because the whole bundle —
       text, quote, rect and verdict — moves together below, and a verdict that
       says "computed by the host" is only true of the text the host computed.
       This element is what the paragraph at the merge site has always claimed
       and never had: the auditor typically holds the *shorter* quote (it quotes
       only the term it computed over, while the model quotes a whole schedule
       line), so on quote length alone it loses, and the model's arithmetic
       inherited the DETERMINISTIC label.
    2. A longer quote anchors better.
    3. More severe wins ties.
    4. Then the stable id and finally the text — a **total** order even when two
       duplicates share a quote-derived id (``compute_finding_id`` hashes the
       quote, not the text, so same-quote duplicates collide), so the same
       cluster picks the same representative regardless of ingest order for a
       *fixed* set of members (§12.4).

    "For a fixed set of members" is load-bearing: the caller must not mutate a
    field this reads between constructing the two tuples it compares.
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
    # Decide the representative BEFORE anything below mutates a field
    # ``_grounding_quality`` reads. The severity union used to run first and
    # raise ``existing.severity`` to the max, erasing the very difference the
    # comparison was about: order A saw ranks (3, 2) and order B saw (3, 3), so
    # the same two findings produced different survivors depending only on which
    # arrived first, and the tiebreak fell through to raw text — where "…560…"
    # sorts above "…540…", handing the entry to the model's arithmetic.
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
    # Union the enumerated prose-item ids (§14.6/§14.9): a merge must never drop an
    # item's provenance, or the harvest's expected-vs-accounted reconciliation would
    # think it was lost and re-degrade it into a duplicate.
    for pid in incoming.prose_item_ids:
        if pid not in existing.prose_item_ids:
            existing.prose_item_ids.append(pid)
    # Keep the strongest self-consistency verdict either member carried (§14.4).
    if _CONFIDENCE_RANK.get(incoming.confidence, 0) > _CONFIDENCE_RANK.get(existing.confidence, 0):
        existing.confidence = incoming.confidence

    # Coherent grounding: if ``incoming`` is the better representative, adopt its
    # WHOLE bundle atomically — text, category, quote, tile, anchor_hint, id, AND
    # the **anchor** (the rect belongs to the quote it was resolved from; keeping
    # one member's quote with another's rectangle is the cross-grounding §12.2
    # forbids). A deterministic auditor sorts first in _grounding_quality, so its
    # authoritative quote+rect wins the representative and its exact anchor is kept.
    if incoming_wins:
        loser_quote = existing.source_quote
        loser_action = existing.recommended_action
        # Decided BEFORE the bundle overwrites ``source_quote``: once it is the
        # incoming quote, comparing the two always says "compatible" and the
        # survivor's rect would be kept for a string it never anchored.
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
        # Adopt the winner's anchor, but never let an UNANCHORED winner erase a
        # rect the survivor already had: the upgrade below cannot restore it
        # (it only fires when the *incoming* member is the anchored one), so the
        # exact rectangle was simply destroyed in one of the two ingest orders.
        # A kept rect stays coherent because ``_placement_compatible`` gates it
        # against the new quote just as the upgrade does.
        incoming_places = (
            incoming.anchor is not None and incoming.anchor.rect_pdf is not None
        )
        if incoming_places or not existing_rect_places_winner:
            existing.anchor = incoming.anchor
        # else: the survivor's rect anchors the same string as the new
        # representative's quote, so it legitimately places it — keep it.
        # The evidence state is a property OF THE QUOTE — it records whether
        # *that* string was re-found in *that* sheet's text (WP-03B §8.3). It
        # must ride the bundle: keeping the loser's trust label beside the
        # winner's quote is the same cross-grounding §12.2 forbids for rects,
        # and would let a reduced-trust claim inherit a "text-grounded" label.
        existing.evidence_state = incoming.evidence_state
        # The VERDICT rides the bundle too, for the same reason the rect and the
        # evidence state do. A verdict is a statement about one specific text:
        # DETERMINISTIC means "a host computed this result from this quote", and
        # VERIFIED means "a verifier looked at this claim". Deciding it
        # separately from the text let a DETERMINISTIC label land on the model's
        # own arithmetic — which then skipped the crop check
        # (``verify._TERMINAL_STATUSES``) and inked as "an exact text check, not
        # an AI judgment". The losing member's quote still rides into
        # ``supporting_quotes`` below, so its value is preserved; only its
        # verdict stops travelling to text it did not produce.
        existing.verification = incoming.verification
        existing.id = incoming.id
        _add_supporting(existing, loser_quote)
        if not existing.recommended_action:
            existing.recommended_action = loser_action
        # Deliberately NO backfill of the loser's verdict onto an empty winner.
        # It reads like a harmless default and is the same defect in reverse: a
        # verifier looked at the LOSER's text, so lending that verdict to the
        # winner's different text asserts something nobody checked. With
        # provenance ranked first in _grounding_quality, a DETERMINISTIC member
        # cannot be the loser here unless both members are deterministic.
    else:
        _add_supporting(existing, incoming.source_quote)
        if not existing.recommended_action:
            existing.recommended_action = incoming.recommended_action

    if not existing.also_on and incoming.also_on:
        existing.also_on = list(incoming.also_on)
    if existing.citation is None and incoming.citation is not None:
        existing.citation = incoming.citation

    # Anchor upgrade: an incoming member that carries a rectangle can place an
    # unanchored survivor (e.g. an anchored model member placing a rect-less
    # deterministic auditor entry) — but ONLY when their quotes are placement-
    # compatible, so a different quote's rect is never grafted on (§12.2 / C-2).
    existing_anchored = existing.anchor is not None and existing.anchor.rect_pdf is not None
    incoming_anchored = incoming.anchor is not None and incoming.anchor.rect_pdf is not None
    if incoming_anchored and not existing_anchored and _placement_compatible(existing, incoming):
        existing.anchor = incoming.anchor

    # NOTE: there is deliberately no verdict adoption here any more. It used to
    # read "a DETERMINISTIC verdict survives the merge regardless of which member
    # became the representative bundle", which is exactly how the model's own
    # arithmetic came to be labelled host-computed. The verdict now rides the
    # bundle above, and _grounding_quality ranks a deterministic member first so
    # the bundle it rides with is the one the host actually computed.

    spans_families = len(_families(existing.sources)) >= 2
    existing.reproduced = (
        existing.reproduced
        or incoming.reproduced
        or spans_families
    )
    # ``confidence`` must agree with ``reproduced`` (§14.4). The rank upgrade
    # above can only ever be raised by another *critique* member, because every
    # non-critique channel carries "" (rank 0) — so a critique SINGLETON merged
    # with a digest or auditor finding kept saying "only one of the two reads
    # saw it" while the very same merge unioned a second family into ``sources``
    # and flipped ``reproduced`` to True. The entry then claimed corroboration
    # and its absence at once. ``critique.merge_finding_groups`` already settles
    # this the coherent way — two channels independently raising an issue IS
    # corroboration — and the ledger implemented only the ``reproduced`` half of
    # that rule. REPRODUCED is the top rank, so this is an upgrade, never a
    # downgrade of a verdict a second critique read earned on its own.
    if spans_families:
        existing.confidence = CONFIDENCE_REPRODUCED
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
    if ledger.state != SEALED:          # SEALED only — never re-dedup a NUMBERED ledger
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
        members: dict[int, list[Finding]] = {}
        token_index: dict[str, set[int]] = {}
        quote_index: dict[str, set[int]] = {}

        def _signals(finding: Finding) -> tuple[set[str], str]:
            return (
                _norm_tokens(finding.text or "")
                | _norm_tokens(finding.source_quote or ""),
                _normalize(finding.source_quote or ""),
            )

        def _index(survivor: Finding, member: Finding) -> None:
            tokens, quote = _signals(member)
            sid = id(survivor)
            for token in tokens:
                token_index.setdefault(token, set()).add(sid)
            if quote:
                quote_index.setdefault(quote, set()).add(sid)

        def _candidates(finding: Finding) -> list[Finding]:
            tokens, quote = _signals(finding)
            if not tokens and not quote:
                return survivors
            ids: set[int] = set()
            for token in tokens:
                ids.update(token_index.get(token, ()))
            if quote:
                ids.update(quote_index.get(quote, ()))
            return [survivor for survivor in survivors if id(survivor) in ids]

        for e in group:
            # Complete-link, like the ingest pass (§12.1): fold only into a survivor
            # whose EVERY already-folded member duplicates ``e``, so a signature-less
            # bridge can't collapse a conflicting A+B+C chain (e.g. M-101 + generic +
            # M-102). ``e`` is worse-or-equal (best-first sort), so ``_merge_into``
            # keeps the survivor's bundle and never mutates its recorded members.
            match = next(
                (
                    s for s in _candidates(e)
                    if all(_is_duplicate(e, m) for m in members[id(s)])
                ),
                None,
            )
            if match is not None:
                # Carry the folded entry's WHOLE ingest history onto the
                # survivor, not just the live object: everything it absorbed in
                # Pass A must keep blocking a later fold too. ``adopt_members``
                # also freezes the survivor's own head, so re-seed the local map
                # from the ledger afterwards rather than extending it — the copy
                # it just took is the accurate record of the survivor, and the
                # merge below is about to mutate the live object.
                ledger.adopt_members(match, e)
                members[id(match)] = ledger.member_history(match)
                _index(match, e)
                _merge_into(match, e, ledger.merge_trace)
                ledger.drop_entry(e)
                folded += 1
            else:
                survivors.append(e)
                # Seed from the ledger's ingest SNAPSHOTS, never the live entry.
                # ``_merge_into`` mutates a survivor whenever a higher-quality
                # member wins, so by now the live object may no longer carry the
                # signature of what it absorbed — a conflicting measurement
                # lives in ``text``, which the winning bundle overwrote. Pass A
                # refuses those folds using exactly these snapshots; rebuilding
                # the history from the mutated survivor let Pass B undo that
                # refusal and destroy the conflicting value outright.
                members[id(e)] = ledger.member_history(e)
                _index(e, e)
    if folded:
        _log.info("post-anchor reconciliation folded %d duplicate finding(s)", folded)
    return folded
