"""Prose harvest (Part III, §17) — the legacy channel's carry-through guarantee.

The digest's prose **Coordination** and **Conflict** sections (and the
cross-sheet **synthesis** prose) predate the structured-findings contract, and a
downstream consumer already relies on them (I-2). Part III's directive is that
nothing QC-flavored may live *only* in prose — every prose item must reach the
findings ledger and therefore the reviewed PDF. Three layered mechanisms:

1. **Prompt coupling** (in :mod:`digest`): the findings instruction tells the
   model every Coordination/Conflict prose item must also appear in the JSON
   block. Soft guarantee only — hence 2 and 3.
2. **Deterministic split + match** (free): the prose sections are split into
   discrete items and fuzzy-matched (token overlap ≥ 0.7) against the same-sheet
   ledger entries. A match tags the existing entry with the prose provenance.
3. **Structuring fallback** (one small model call per straggler): an unmatched
   item plus the sheet's text layer → one §4.1 finding (verbatim
   ``source_quote`` or ``""``). If even that fails, a **degraded entry** is
   ingested — the prose item verbatim, ``anchor_hint="SHEET"`` — which still
   reaches the PDF as a margin callout.

**Invariant: no prose QC item may fail to produce a ledger entry.**

Synthesis prose is harvested for **conflict statements only**: items naming at
least one in-set sheet, anchored on the first named sheet and dual-anchored
(``also_on``) when a second sheet is named. Per-sheet **Focus findings** sections
are harvested only behind ``focus_findings_to_markups`` (default OFF — a focus
is often not QC).

The prose itself is never modified — it is *mirrored* into the ledger, not
moved (I-2). PDF-engine-free (I-5); real-time only (stragglers are few).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .core.api_config import REVIEW_MODEL_DEFAULT
from .critique import _token_overlap
from .diagnostics import get_logger
from .digest import (
    _clean_error,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    _tolerant_json_object,
    _validate_finding_item,
    scan_structured_blocks,
)
from .html_report import classify_section, split_into_sections
from .ledger import Ledger
from .models import (
    ConflictLeg,
    Finding,
    ProseItem,
    SheetRef,
    Verification,
    compute_prose_item_id,
    source_page_key,
)

# The sheet_id label a set-level synthesis conflict carries (it belongs to no
# single source sheet). Kept short for the review-notes row / report section.
SET_LEVEL_SHEET_LABEL = "(set-level)"

_log = get_logger()

# Mechanism 2's match threshold (§17): token overlap ≥ 0.7 against a same-sheet
# ledger entry's text or quote.
_MATCH_OVERLAP = 0.7
# The structuring call (mechanism 3): small, thinking off, tolerant-parsed.
DEFAULT_HARVEST_MAX_TOKENS = 800
DEFAULT_HARVEST_MAX_RETRIES = 2
# The sheet text layer sent with a structuring call (a straggler needs context,
# not the whole sheet).
_HARVEST_TEXT_CAP = 6_000

_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+•]|\d+[.)])\s+(.*)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9(])")
# Items that are section boilerplate, not findings ("None noted.", "N/A").
_TRIVIAL_RE = re.compile(
    r"^\W*(none|n/?a|no (conflicts?|issues?|items?|discrepanc)|nothing)\b", re.I
)
_MIN_ITEM_CHARS = 20

# Synthesis harvest keeps conflict statements only (§17): an item must carry one
# of these signals (mirrors the report's conflict classification keywords).
_CONFLICT_SIGNALS = (
    "conflict", "contradic", "disagree", "mismatch", "discrepan", "inconsist",
    "differs", "diverg", "does not match", "doesn't match", "stale",
)


def harvest_model() -> str:
    """The structuring-call model (``DRAWING_ANALYZER_HARVEST_MODEL``, else Opus)."""
    return os.environ.get("DRAWING_ANALYZER_HARVEST_MODEL") or REVIEW_MODEL_DEFAULT


# --------------------------------------------------------------------------- #
# Item extraction (pure)
# --------------------------------------------------------------------------- #


def _split_items(body: str) -> list[str]:
    """Discrete items from one section body: list markers, else sentences."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    items: list[str] = []
    current: list[str] = []
    saw_marker = False
    for line in lines:
        m = _LIST_ITEM_RE.match(line)
        if m:
            saw_marker = True
            if current:
                items.append(" ".join(current).strip())
            current = [m.group(2).strip()]
        elif line.strip() and current:
            current.append(line.strip())      # continuation of the current item
        elif not line.strip() and current:
            items.append(" ".join(current).strip())
            current = []
    if current:
        items.append(" ".join(current).strip())
    if not saw_marker:
        text = " ".join(l.strip() for l in lines if l.strip())
        items = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return [i for i in items if len(i) >= _MIN_ITEM_CHARS and not _TRIVIAL_RE.match(i)]


def extract_prose_items(digest_text: str) -> list[tuple[str, str]]:
    """The digest's Coordination/Conflict prose items → ``(source_tag, item)``.

    Sections are located with the **same** splitter and classifier the HTML
    report's "⚠ Issues only" filter uses, so the harvest covers exactly the
    prose the report already treats as QC.
    """
    out: list[tuple[str, str]] = []
    for header, body in split_into_sections(digest_text or ""):
        category = classify_section(header)
        if category not in ("coordination", "conflict"):
            continue
        tag = f"digest_prose_{category}"
        out.extend((tag, item) for item in _split_items(body))
    return out


def extract_focus_items(digest_text: str) -> list[str]:
    """The digest's per-sheet Focus-findings prose items (opt-in harvest)."""
    out: list[str] = []
    for header, body in split_into_sections(digest_text or ""):
        if classify_section(header) != "focus":
            continue
        if "nothing relevant to the focus" in (body or "").lower():
            continue
        out.extend(_split_items(body))
    return out


def extract_synthesis_conflicts(
    synthesis_text: str, sheet_ids: Iterable[str]
) -> list[tuple[str, list[str]]]:
    """Conflict statements from the synthesis prose → ``(item, named_sheet_ids)``.

    Keeps only items that carry a conflict signal AND name at least one in-set
    sheet id (order of ids = order of first mention, so the first is the
    primary anchor sheet and the second becomes the ``also_on`` leg). Items
    naming no resolvable sheet are skipped (logged by the caller) — a synthesis
    conflict with no sheet has nowhere on the PDF to live.
    """
    ids = sorted({s.upper() for s in sheet_ids if s}, key=lambda s: (-len(s), s))
    if not ids or not (synthesis_text or "").strip():
        return []
    out: list[tuple[str, list[str]]] = []
    for item in _split_items(synthesis_text):
        low = item.lower()
        if not any(sig in low for sig in _CONFLICT_SIGNALS):
            continue
        mentioned = _id_mentions(item.upper(), ids)
        if not mentioned:
            continue
        out.append((item, [sid for _pos, sid in sorted(mentioned)]))
    return out


def extract_set_level_synthesis_conflicts(
    synthesis_text: str, sheet_ids: Iterable[str]
) -> list[str]:
    """Synthesis conflict statements that name **no** resolvable in-set sheet (§14.8).

    The complement of :func:`extract_synthesis_conflicts`: same conflict-signal
    filter, but these items reference no sheet the set contains, so they belong to
    no single source. Instead of being dropped (the old behavior — a real conflict
    silently lost), they become **set-level** findings written to the deterministic
    ``Drawing_Set_Review_Notes.pdf``. Returns the verbatim items.
    """
    ids = sorted({s.upper() for s in sheet_ids if s}, key=lambda s: (-len(s), s))
    if not (synthesis_text or "").strip():
        return []
    out: list[str] = []
    for item in _split_items(synthesis_text):
        low = item.lower()
        if not any(sig in low for sig in _CONFLICT_SIGNALS):
            continue
        if ids and _id_mentions(item.upper(), ids):
            continue                 # names an in-set sheet → handled as SOURCE-scoped
        out.append(item)
    return out


# Characters that can continue a drawing id past a candidate match: "A-1"
# followed by ".1" is detail id A-1.1, not sheet A-1. A slash is deliberately
# NOT here — "P-1/P-2" names both sheets and detail-style "5/A-3" genuinely
# lives on sheet A-3.
_ID_CONNECTORS = ".-"


def _extends_id(text: str, index: int, step: int) -> bool:
    """Whether ``text[index]`` continues a larger id in direction ``step`` —
    alphanumeric, or a ``.``/``-`` connector with an alphanumeric beyond it
    (``A-1.1``, ``A-1-1``). A connector with nothing alphanumeric past it is
    sentence punctuation, not a continuation (``"… conflict on A-1."``)."""
    if index < 0 or index >= len(text):
        return False
    ch = text[index]
    if ch.isalnum():
        return True
    if ch in _ID_CONNECTORS:
        far = index + step
        return 0 <= far < len(text) and text[far].isalnum()
    return False


def _bounded_occurrences(text: str, sid: str) -> list[int]:
    """Start offsets where ``sid`` occurs as a whole id — ``A-1`` matches in
    ``"SEE A-1."`` but not inside ``A-10``, ``A-1.1``, or ``2A-15``."""
    out: list[int] = []
    start = 0
    while (pos := text.find(sid, start)) >= 0:
        if not _extends_id(text, pos - 1, -1) and not _extends_id(
            text, pos + len(sid), 1
        ):
            out.append(pos)
        start = pos + 1
    return out


def _id_mentions(text: str, ids: list[str]) -> list[tuple[int, str]]:
    """First genuine mention of each in-set sheet id, as ``(offset, id)``.

    Boundary-aware (``_extends_id``), and a shorter id additionally never
    counts inside a longer in-set id's mention: longer ids — ``ids`` arrives
    longest-first — claim their spans and shorter ids only match outside
    them. The claim pass backs up the boundary check for id alphabets the
    connector list doesn't cover (say a set holding both ``A-1`` and
    ``A-1 EAST``). Without all this, a set holding both ``A-1`` and ``A-10``
    would read a mention of ``A-10`` as naming ``A-1`` too and cloud a sheet
    the prose never named.
    """
    claimed: list[tuple[int, int]] = []
    mentioned: list[tuple[int, str]] = []
    for sid in ids:
        occurrences = _bounded_occurrences(text, sid)
        free = [
            p for p in occurrences
            if not any(c0 <= p and p + len(sid) <= c1 for c0, c1 in claimed)
        ]
        if free:
            mentioned.append((free[0], sid))
        claimed.extend((p, p + len(sid)) for p in occurrences)
    return mentioned


# --------------------------------------------------------------------------- #
# Mechanism 2 — match against the ledger (free)
# --------------------------------------------------------------------------- #


def _match_entry(item: str, entries: list[Finding]) -> Finding | None:
    """The same-sheet ledger entry the prose item restates, if any."""
    best: Finding | None = None
    best_score = 0.0
    for entry in entries:
        score = max(
            _token_overlap(item, entry.text),
            _token_overlap(item, entry.source_quote or ""),
        )
        if score >= _MATCH_OVERLAP and score > best_score:
            best, best_score = entry, score
    return best


# --------------------------------------------------------------------------- #
# Mechanism 3 — the structuring call, with the degraded fallback
# --------------------------------------------------------------------------- #

HARVEST_SYSTEM_PROMPT = """\
You convert ONE prose item from a construction-drawing QC review into exactly \
one machine-readable finding. You are given the item and the sheet's verbatim \
text layer. Output ONLY a fenced code block labeled json containing a single \
object with: sheet_id; category (one of code, conflict, coordination, \
question); severity (one of high, medium, low); text (the finding, at most two \
sentences); source_quote (COPY VERBATIM a supporting string from the SHEET TEXT \
LAYER — exact characters — or "" if no on-sheet string supports it); tile \
(null); refs (an array, usually empty). Never invent quotes, tags, or values."""


def _structure_item(
    item: str,
    category_hint: str,
    sheet_text: str,
    ref: SheetRef,
    sheet_id: str,
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
) -> tuple[Finding | None, int, int]:
    """One structuring call → ``(finding_or_None, in_tok, out_tok)``. Never raises."""
    text = (sheet_text or "")[:_HARVEST_TEXT_CAP]
    user = (
        f"PROSE QC ITEM (from the sheet's {category_hint} section):\n{item}\n\n"
        f"SHEET ID: {sheet_id}\n\n"
        f"SHEET TEXT LAYER (verbatim):\n{text or '[none]'}\n\n"
        "Convert the item into the single finding object now."
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": DEFAULT_HARVEST_MAX_TOKENS,
        "system": HARVEST_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user}],
    }
    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            _log.warning("prose-harvest structuring call failed: %s", _clean_error(exc))
            return None, 0, 0

    in_tok, out_tok = _message_usage(resp)
    raw = _message_text(resp)
    obj: dict | None = None
    for c in scan_structured_blocks(raw or ""):
        candidate = _tolerant_json_object(c.body)
        if isinstance(candidate, dict):
            obj = candidate
    if obj is None:
        return None, in_tok, out_tok
    if isinstance(obj.get("findings"), list) and obj["findings"]:
        obj = obj["findings"][0] if isinstance(obj["findings"][0], dict) else None
    finding = _validate_finding_item(obj, ref) if isinstance(obj, dict) else None
    return finding, in_tok, out_tok


def _degraded_entry(
    item: str, category_hint: str, ref: SheetRef, sheet_id: str
) -> Finding:
    """The §17 last-resort entry: the prose item verbatim, placed sheet-level.

    Still reaches the PDF as a margin callout — the invariant is that no prose
    QC item fails to produce a ledger entry.
    """
    return Finding(
        sheet_id=sheet_id,
        source_name=ref.source_name,
        source_id=ref.source_id,
        page_index=ref.page_index,
        category=category_hint if category_hint in ("conflict", "coordination", "question") else "coordination",
        severity="medium",
        text=item.strip(),
        source_quote="",
        anchor_hint="SHEET",
        verification=Verification(status="SKIPPED", note="degraded prose-harvest entry"),
    )


def _set_level_entry(item: str) -> Finding:
    """A **set-level** finding for a synthesis conflict naming no in-set sheet (§14.8).

    ``source_id`` is empty and ``anchor_hint`` is ``"SET_INDEX"`` (so ``_scope_of``
    treats it as SET), ``page_index`` is ``-1``. It belongs to no source sheet and is
    written to the dedicated ``Drawing_Set_Review_Notes.pdf`` — never pinned onto an
    arbitrary drawing. The verbatim statement stays intact (I-2 — mirrored, not moved).
    """
    return Finding(
        sheet_id=SET_LEVEL_SHEET_LABEL,
        source_name="",
        source_id="",
        page_index=-1,
        category="conflict",
        severity="medium",
        text=item.strip(),
        source_quote="",
        anchor_hint="SET_INDEX",
        verification=Verification(status="SKIPPED", note="set-level synthesis conflict"),
    )


# --------------------------------------------------------------------------- #
# The harvest pass
# --------------------------------------------------------------------------- #


@dataclass
class HarvestResult:
    """Telemetry + carry-through accounting for one run's prose harvest (§14.9).

    Every enumerated prose item has a stable ``prose_item_id``; the harvest
    reconciles the ``expected_ids`` (all enumerated) against the ``accounted_ids``
    (attached to a ledger entry) and degrades — never silently drops — any
    straggler. ``missing`` is the count still unaccounted after the final degraded
    attempt: it must be ``0`` for a complete exhaustive harvest.
    """

    items: int = 0            # prose items considered
    matched: int = 0          # mechanism 2 — tagged an existing entry
    structured: int = 0       # mechanism 3 — model structured a straggler
    degraded: int = 0         # last resort — verbatim SHEET entry
    set_level: int = 0        # synthesis conflicts placed in the set-level artifact
    excluded_focus: int = 0   # focus items present but intentionally not harvested
    skipped: int = 0          # retained for back-compat (nothing is dropped now)
    missing: int = 0          # enumerated items with NO ledger entry after reconcile
    input_tokens: int = 0
    output_tokens: int = 0
    expected_ids: list[str] = field(default_factory=list)
    accounted_ids: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when every enumerated prose item reached a ledger entry."""
        return self.missing == 0


@dataclass
class _Pending:
    """One enumerated prose item plus everything needed to ingest it."""

    item: ProseItem
    ref: SheetRef | None            # None for a set-level item
    sheet_id: str
    sheet_text: str
    tag: str
    hint: str
    also_on: list[ConflictLeg]

    @property
    def pid(self) -> str:
        return self.item.prose_item_id


def _client_or_none(client: Any) -> Any:
    if client is not None:
        return client
    try:
        from .client import get_client as _get_client

        return _get_client()
    except Exception as exc:  # noqa: BLE001 - no key → structuring degrades
        _log.warning("prose harvest: no client (%s); stragglers degrade", _clean_error(exc))
        return None


def _process_pending(
    ledger: Ledger,
    p: _Pending,
    result: HarvestResult,
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
) -> None:
    """Mechanisms 2 → 3 → degraded for one prose item; attach its ``prose_item_id``.

    A set-level item (a synthesis conflict naming no in-set sheet) has no sheet to
    match or structure against, so it degrades directly to a set-level ledger entry.
    """
    pid = p.pid
    if p.ref is None:                       # set-level: nowhere to match/structure
        finding = _set_level_entry(p.item.verbatim_text)
        finding.prose_item_ids = [pid]
        ledger.add([finding], p.tag)
        result.set_level += 1
        return

    match = _match_entry(p.item.verbatim_text, ledger.entries_for(p.ref))
    if match is not None:
        if p.tag not in match.sources:
            match.sources.append(p.tag)
        if p.also_on and not match.also_on:
            match.also_on = list(p.also_on)
        if pid not in match.prose_item_ids:
            match.prose_item_ids.append(pid)
        result.matched += 1
        return

    finding: Finding | None = None
    if client is not None:
        finding, in_tok, out_tok = _structure_item(
            p.item.verbatim_text, p.hint, p.sheet_text, p.ref, p.sheet_id,
            client=client, model=model, max_retries=max_retries, sleep=sleep,
        )
        result.input_tokens += in_tok
        result.output_tokens += out_tok
    if finding is not None:
        if not finding.source_quote.strip() and not finding.anchor_hint:
            finding.anchor_hint = "SHEET"      # nothing to anchor on → margin callout
        result.structured += 1
    else:
        finding = _degraded_entry(p.item.verbatim_text, p.hint, p.ref, p.sheet_id)
        result.degraded += 1
    if p.also_on:
        finding.also_on = list(p.also_on)
    finding.prose_item_ids = [pid]
    ledger.add([finding], p.tag)


def _accounted_ids(ledger: Ledger) -> set[str]:
    """The set of prose-item ids currently attached to any ledger entry."""
    acc: set[str] = set()
    for e in ledger.entries:
        acc.update(e.prose_item_ids)
    return acc


def _enumerate_pending(
    sheets: list[Any],
    synthesis_text: str,
    id_map: dict[str, Any],
    *,
    focus_findings_to_markups: bool,
    sheet_text_of: Any,
    display_id_of: Any,
    result: HarvestResult,
) -> list[_Pending]:
    """Enumerate every candidate prose item into a stable-id ``_Pending`` (§14.6).

    Nothing is dropped here: a synthesis conflict naming no resolvable in-set sheet
    becomes a **set-level** pending item rather than being discarded.
    """
    pending: list[_Pending] = []

    # --- per-sheet digest prose (Coordination / Conflict; Focus when opted in) --
    for sd in sheets or []:
        if getattr(sd, "error", None) or not (getattr(sd, "text", "") or "").strip():
            continue
        ref = sd.ref
        sid_label = display_id_of(ref)
        sheet_text = sheet_text_of(ref)
        counters: dict[str, int] = {}
        for tag, item in extract_prose_items(sd.text):
            ordinal = counters.get(tag, 0)
            counters[tag] = ordinal + 1
            hint = "conflict" if tag.endswith("conflict") else "coordination"
            pi = ProseItem(
                prose_item_id=compute_prose_item_id(
                    tag, ref.source_id, tag, ordinal, item, page_index=ref.page_index),
                channel=tag, scope="SOURCE", source_id=ref.source_id,
                section=tag, ordinal=ordinal, verbatim_text=item,
            )
            pending.append(_Pending(pi, ref, sid_label, sheet_text, tag, hint, []))
        focus_items = extract_focus_items(sd.text)
        if focus_findings_to_markups:
            for ordinal, item in enumerate(focus_items):
                pi = ProseItem(
                    prose_item_id=compute_prose_item_id(
                        "focus_prose", ref.source_id, "focus", ordinal, item,
                        page_index=ref.page_index),
                    channel="focus_prose", scope="SOURCE", source_id=ref.source_id,
                    section="focus", ordinal=ordinal, verbatim_text=item,
                )
                pending.append(_Pending(pi, ref, sid_label, sheet_text, "focus_prose", "question", []))
        else:
            result.excluded_focus += len(focus_items)   # present, intentionally not harvested

    # --- synthesis conflicts naming an in-set sheet (SOURCE-scoped; dual-anchored) --
    for ordinal, (item, sids) in enumerate(
        extract_synthesis_conflicts(synthesis_text, id_map.keys())
    ):
        primary = id_map.get(sids[0])
        if primary is None:
            # Named an in-set id we cannot map to a geometry — a detect/normalize
            # disagreement. Don't drop it: keep it as set-level (§14.8).
            pi = ProseItem(
                prose_item_id=compute_prose_item_id("synthesis_prose", "", "synthesis", ordinal, item),
                channel="synthesis_prose", scope="SET", source_id=None,
                section="synthesis", ordinal=ordinal, verbatim_text=item,
                mentioned_sheet_ids=list(sids),
            )
            pending.append(_Pending(pi, None, SET_LEVEL_SHEET_LABEL, "", "synthesis_prose", "conflict", []))
            continue
        legs: list[ConflictLeg] = []
        for other in sids[1:2]:                 # dual-anchor: the second named sheet
            geom = id_map.get(other)
            if geom is not None:
                legs.append(ConflictLeg(
                    sheet_id=other,
                    source_name=geom.ref.source_name,
                    source_id=geom.ref.source_id,
                    page_index=geom.ref.page_index,
                ))
        pi = ProseItem(
            prose_item_id=compute_prose_item_id(
                "synthesis_prose", primary.ref.source_id, "synthesis", ordinal, item,
                page_index=primary.ref.page_index),
            channel="synthesis_prose", scope="SOURCE", source_id=primary.ref.source_id,
            section="synthesis", ordinal=ordinal, verbatim_text=item,
            mentioned_sheet_ids=list(sids),
        )
        pending.append(_Pending(
            pi, primary.ref, sids[0], getattr(primary, "sheet_text", "") or "",
            "synthesis_prose", "conflict", legs,
        ))

    # --- synthesis conflicts naming NO in-set sheet at all → set-level (§14.8) ---
    for ordinal, item in enumerate(
        extract_set_level_synthesis_conflicts(synthesis_text, id_map.keys())
    ):
        pi = ProseItem(
            prose_item_id=compute_prose_item_id("synthesis_prose", "", "synthesis_set", ordinal, item),
            channel="synthesis_prose", scope="SET", source_id=None,
            section="synthesis_set", ordinal=ordinal, verbatim_text=item,
        )
        pending.append(_Pending(pi, None, SET_LEVEL_SHEET_LABEL, "", "synthesis_prose", "conflict", []))

    return pending


def harvest_prose(
    ledger: Ledger,
    sheets: list[Any],
    geometries: list[Any],
    *,
    client: Any = None,
    synthesis_text: str = "",
    focus_findings_to_markups: bool = False,
    model: str | None = None,
    max_retries: int = DEFAULT_HARVEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    progress: Any = None,
) -> HarvestResult:
    """Mirror every prose QC item into the ledger (§17/§14). Never raises.

    Runs after the digest/critique/cross/auditor ingest and **before** the ledger
    seals. Every candidate item is first enumerated into a stable ``prose_item_id``
    (§14.6); each is then processed under its own try/except (a failure in one item
    can never abandon the rest) — matched items tag an existing entry, stragglers are
    structured by one small model call, and anything else degrades to a verbatim
    entry. A synthesis conflict naming no resolvable in-set sheet becomes a
    **set-level** finding rather than being dropped (§14.8). Finally the harvest
    reconciles the enumerated ids against the ledger and makes one last degraded
    attempt for any straggler, so nothing enumerated is silently lost (§14.9).
    ``synthesis_text`` contributes its conflict statements (dual-anchored when two
    sheets are named); per-sheet Focus sections are harvested only when
    ``focus_findings_to_markups`` is on.
    """
    result = HarvestResult()
    model = model or harvest_model()
    client = _client_or_none(client)

    geom_by_key = {
        source_page_key(g.ref): g
        for g in geometries or []
        if getattr(g, "ref", None) is not None
    }
    # The set's sheet-id map, for synthesis anchoring.
    from .auditors.references import detect_sheet_id

    id_map: dict[str, Any] = {}
    for geom in geometries or []:
        sid = detect_sheet_id(geom)
        if sid and sid not in id_map:
            id_map[sid] = geom

    def _sheet_text(ref: SheetRef) -> str:
        geom = geom_by_key.get(source_page_key(ref))
        return getattr(geom, "sheet_text", "") or "" if geom is not None else ""

    def _display_id(ref: SheetRef) -> str:
        geom = geom_by_key.get(source_page_key(ref))
        return (detect_sheet_id(geom) if geom is not None else None) or ref.source_name

    pending = _enumerate_pending(
        sheets, synthesis_text, id_map,
        focus_findings_to_markups=focus_findings_to_markups,
        sheet_text_of=_sheet_text, display_id_of=_display_id, result=result,
    )
    result.items = len(pending)

    # --- process each item under its own guard (a raise can't abandon the rest) --
    for done, p in enumerate(pending, start=1):
        try:
            _process_pending(
                ledger, p, result,
                client=client, model=model, max_retries=max_retries, sleep=sleep,
            )
        except Exception as exc:  # noqa: BLE001 - one item's failure is reconciled below
            _log.warning(
                "prose harvest: item %s failed (%s); will reconcile",
                p.pid, _clean_error(exc),
            )
        if progress is not None:
            progress(done, len(pending), "Harvesting prose findings")

    # --- reconcile: every enumerated id must have reached a ledger entry (§14.9) --
    expected = {p.pid for p in pending}
    accounted = _accounted_ids(ledger)
    missing = expected - accounted
    if missing:
        by_id = {p.pid: p for p in pending}
        for pid in sorted(missing):
            p = by_id[pid]
            try:
                if p.ref is None:
                    finding = _set_level_entry(p.item.verbatim_text)
                    finding.prose_item_ids = [pid]
                    ledger.add([finding], p.tag)
                    result.set_level += 1        # mirror the main-loop set-level tally
                else:
                    finding = _degraded_entry(p.item.verbatim_text, p.hint, p.ref, p.sheet_id)
                    finding.prose_item_ids = [pid]
                    ledger.add([finding], p.tag)
                    result.degraded += 1
            except Exception as exc:  # noqa: BLE001 - genuinely unrecoverable → reported
                _log.warning("prose harvest: could not recover item %s: %s", pid, _clean_error(exc))
        accounted = _accounted_ids(ledger)

    result.expected_ids = sorted(expected)
    result.accounted_ids = sorted(accounted & expected)
    result.missing = len(expected - accounted)

    _log.info(
        "prose harvest: %d item(s) — %d matched, %d structured, %d degraded, "
        "%d set-level, %d excluded-focus, %d MISSING",
        result.items, result.matched, result.structured, result.degraded,
        result.set_level, result.excluded_focus, result.missing,
    )
    return result
