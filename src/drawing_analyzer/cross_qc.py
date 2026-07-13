"""Cross-sheet QC pass (Phase 13 / Phase 24) — a deliberate conflict hunt across the set.

Distinct from the prose ``synthesis`` (which stays exactly as-is): this pass has
one job — find **conflicts between sheets**. It is a *text-reasoning* task, so it
sends the per-sheet digests plus the verbatim text layers and **no images**.

Its findings carry **dual anchors**: a primary anchor on one sheet plus one or
more ``also_on`` legs on the other sheets in the conflict, so the markup writer can
cloud *both* sheets. The prose ``combined_text`` is never touched (I-2) — cross-QC
findings live only in the findings artifacts.

**Whole-set at every size (Phase 24, DA-015).** For sets up to
``MAX_SHEETS_SINGLE_CALL`` it is one Opus call over the whole set. Above that it
uses a **map → reconcile** architecture: it shards by discipline (same-series
sheets, where conflicts cluster, stay together); each shard call returns its local
conflicts **and** a set of compact grounded ``CrossQCFact`` s (the comparable data
points another shard might contradict); then a final **reconciliation** call
compares the facts across *all* shards, so a conflict whose two sheets fall in
different shards is still found (the old "shard and union" silently missed those).
If the facts exceed one call, a balanced reduction tree carries them forward.

**Opaque handles (§16.1).** Source identity stays host-owned: in the sharded path
the model sees a request-local opaque ``sheet_handle`` (``S001`` …), never a
``source_id``. Every returned handle is validated against the request manifest and
translated to a real sheet on the host; an unknown handle leaves the item unbound.
Every fact's ``exact_quote`` (and every reconciliation quote) is validated against
the retained source text before it is trusted — an ungrounded quote never becomes a
trusted dual-anchor finding.

**Loss-aware budgeting (§16.2, DA-028).** Each sheet's text layer is capped, but the
omission is *counted and surfaced* (``text_chars_omitted`` / ``budget_degraded``),
never a silent slice.

Additive and non-fatal (I-3): a failure is recorded and the standard deliverable
ships. PDF-engine-free (I-5) — it reads the already-extracted geometry/text.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.api_config import REVIEW_MODEL_DEFAULT, model_supports_adaptive_thinking
from .diagnostics import get_logger
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    _FINDING_SEVERITIES,
    _MODEL_FINDING_CATEGORIES,
    _clean_error,
    _coerce_refs,
    _coerce_tile,
    _get,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    _tolerant_json_object,
    parse_numeric_claims,
    scan_structured_blocks,
)
from .models import ConflictLeg, Finding, NumericClaim, source_page_key
from .auditors.references import detect_sheet_id
from .auditors.sheet_ids import fold_text

_log = get_logger()

# One Opus call up to this many sheets; above it, shard by discipline + reconcile.
MAX_SHEETS_SINGLE_CALL = 40
# Nothing to compare across with fewer than two readable sheets.
MIN_SHEETS_FOR_CROSS_QC = 2
DEFAULT_CROSS_QC_MAX_TOKENS = 16_000
DEFAULT_CROSS_QC_MAX_FINDINGS = 60
# Per-shard cap on the compact facts a map call emits (bounds the reconcile input).
DEFAULT_MAP_MAX_FACTS = 40
# Facts one reconciliation call compares at once; above it, a balanced tree reduces.
MAX_FACTS_PER_RECONCILE = 400
# Cap each sheet's text layer in the prompt (the digest already summarizes it). The
# omitted characters are counted and surfaced (DA-028) — never silently dropped.
_TEXT_LAYER_BUDGET = 4_000


def cross_qc_model() -> str:
    """The cross-sheet QC model (``DRAWING_ANALYZER_CROSS_QC_MODEL``, else Opus)."""
    return os.environ.get("DRAWING_ANALYZER_CROSS_QC_MODEL") or REVIEW_MODEL_DEFAULT


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #

CROSS_QC_SYSTEM_PROMPT = """\
You are a senior engineer performing a CROSS-SHEET back-check of a construction \
drawing set before it is issued. You are given, per sheet, its structured digest \
and its verbatim text layer — NO images. Your one job is to find conflicts and \
inconsistencies BETWEEN sheets (never within a single sheet — that is a different \
reviewer's job):

- the same tag, equipment, room, or schedule value stated differently on two \
sheets;
- "twin" notes (a standard note repeated on sibling sheets) that have diverged;
- a note on one sheet contradicted by another sheet;
- phasing or scope that disagrees between a plan and a schedule;
- a cross-reference whose TARGET content does not match what the pointer claims \
(e.g. "see X for location" where sheet X disclaims locations);
- terminology or ID drift — the same thing named two different ways across the set.

Ground every conflict in the actual text: quote the exact conflicting string from \
EACH sheet involved. Report only conflicts you can substantiate from the provided \
text; when you are not certain two sheets truly conflict, lower the severity to \
`question`. Judge across sheets only — a single-sheet issue is out of scope."""

_CROSS_QC_TASK = (
    "Now report the cross-sheet conflicts in this set, following the FINDINGS "
    "format in your instructions. Output only the fenced json findings block."
)

_CROSS_QC_FINDINGS_INSTRUCTION = """\


FINDINGS (machine-read — the ONLY thing you output):
Output a SINGLE fenced code block labeled json and nothing else — no prose — \
containing {"findings": [ ... ], "claims": [ ... ]}. Each finding is a \
CROSS-SHEET conflict with: sheet_id (the PRIMARY sheet, one of the sheets \
involved); category (one of code, conflict, coordination, question); severity \
(one of high, medium, low); text (the conflict in <= 2 sentences, naming the \
sheets); source_quote (COPY VERBATIM the conflicting string from the PRIMARY \
sheet's text layer); tile ([row, col] on the primary sheet, or omit); also_on (an \
array of the OTHER sheets in the conflict, each an object {"sheet_id", \
"source_quote" (verbatim from THAT sheet), "tile"}); refs (optional array of \
codes/specs). Every finding MUST list at least one also_on sheet — a conflict is \
between sheets. Emit at most 60 findings, most important first; emit \
"findings": [] if there are no cross-sheet conflicts.

Also include a "claims" array in the SAME object for numeric relationships a \
reviewer should verify by CALCULATION (you only transcribe the numbers — never do \
the arithmetic). Each claim: sheet_id (the sheet the numbers are on); quote (COPY \
VERBATIM the on-sheet text); kind (one of sum, product, factor); terms (the \
numbers as printed); expected (the stated result they should combine to); note (a \
short phrase naming the relationship). Emit "claims": [] if there are none."""

# Map instruction (sharded path): handle-based findings + comparable facts. The
# model NEVER sees source identity — only opaque per-request handles (S001 …).
_CROSS_QC_MAP_INSTRUCTION = """\


This is ONE SHARD of a larger set. Each sheet is labeled with an opaque HANDLE \
(e.g. S001). Refer to sheets ONLY by their handle.

Output a SINGLE fenced code block labeled json and nothing else, containing \
{"findings": [ ... ], "claims": [ ... ], "facts": [ ... ]}.

- Each finding is a WITHIN-shard cross-sheet conflict: sheet_handle (the PRIMARY \
sheet's handle); category (code, conflict, coordination, question); severity \
(high, medium, low); text (<= 2 sentences); source_quote (VERBATIM from the \
primary sheet); also_on (array of {"sheet_handle", "source_quote" verbatim from \
that sheet}); refs (optional). Every finding lists >= 1 also_on. Emit [] if none.
- Each fact is one comparable data point another shard could contradict: \
sheet_handle; entity_or_tag (the tag / equipment / room / schedule key); attribute \
(what about it); value (as printed); exact_quote (VERBATIM on-sheet string); \
context (<= 12 words). Emit facts for values likely to be REPEATED or REFERENCED \
elsewhere (equipment tags and capacities, shared/general notes, schedule values, \
code editions, phasing) so a reconciler can compare them across shards. Emit at \
most 40 facts.
- Each claim (numeric relationship to verify by calculation — you only transcribe): \
sheet_handle; quote (VERBATIM); kind (sum, product, factor); terms; expected; note. \
Emit [] if none."""

CROSS_QC_RECONCILE_SYSTEM_PROMPT = """\
You are reconciling a large construction drawing set that was reviewed in shards. \
You are given a SHEET MANIFEST (each line: handle = sheet-id (discipline)) and a \
list of FACTS extracted from every sheet — each fact is (sheet_handle, \
entity_or_tag, attribute, value, exact_quote). Your one job is to find CONFLICTS \
BETWEEN sheets that a per-shard review could not see: the same tag / equipment / \
room / schedule value / shared note stated differently on two sheets that were \
reviewed in different shards. Compare the facts across the WHOLE manifest.

Refer to sheets ONLY by their handle. Ground every conflict in the provided \
exact_quotes — never invent a quote.

Output a SINGLE fenced code block labeled json and nothing else, containing \
{"findings": [ ... ], "claims": [ ... ]}. Each finding: sheet_handle (the PRIMARY \
sheet's handle); category (code, conflict, coordination, question); severity \
(high, medium, low); text (<= 2 sentences naming the conflict); source_quote (COPY \
the exact_quote of the primary fact); also_on (array of {"sheet_handle", \
"source_quote" = the other fact's exact_quote}); refs (optional). Every finding \
lists >= 1 also_on and both quotes must come verbatim from the facts. Emit \
"findings": [] if you find no cross-sheet conflict; "claims": [] likewise."""


def cross_qc_system_prompt() -> str:
    """The effective whole-set cross-QC system prompt: persona + findings instruction."""
    return CROSS_QC_SYSTEM_PROMPT + _CROSS_QC_FINDINGS_INSTRUCTION


def cross_qc_map_system_prompt() -> str:
    """The shard-map system prompt: persona + handle-based findings/facts instruction."""
    return CROSS_QC_SYSTEM_PROMPT + _CROSS_QC_MAP_INSTRUCTION


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


@dataclass
class CrossQCFact:
    """One comparable, grounded data point a shard emits for cross-shard reconcile.

    ``sheet_handle`` is the request-local opaque handle the model used; the host
    fills ``sheet_id`` / ``discipline`` from the manifest. ``exact_quote`` is
    validated against the sheet's retained text before the fact is trusted (§16.1).
    """

    sheet_handle: str
    sheet_id: str
    discipline: str
    entity_or_tag: str
    attribute: str
    value: str
    exact_quote: str
    context: str = ""


@dataclass
class CrossQCResult:
    """The outcome of the cross-sheet QC pass.

    ``claims`` are numeric relationships the pass transcribed (Phase 14) for the
    deterministic arithmetic auditor. The Phase-24 fields report the sharded path's
    completeness (§16.3): how many shards ran, whether a reconciliation was required
    and completed, and whether the text budget was degraded (§16.2). ``complete`` is
    False when any shard or the reconciliation failed, or the budget was degraded —
    the pipeline then holds the stage at PARTIAL while still using the findings.
    """

    findings: list[Finding] = field(default_factory=list)
    claims: list[NumericClaim] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    skipped: bool = False        # too few readable sheets — a non-error no-op
    # §16.3 shard / reconciliation completeness.
    shards_planned: int = 0
    shards_completed: int = 0
    reconciliation_required: bool = False
    reconciliation_completed: bool = False
    facts_collected: int = 0
    complete: bool = True
    # §16.2 loss-aware text budgeting telemetry.
    text_chars_total: int = 0
    text_chars_included: int = 0
    text_chars_omitted: int = 0
    budget_degraded: bool = False


# --------------------------------------------------------------------------- #
# Resolution + grounding helpers
# --------------------------------------------------------------------------- #


def _norm_id(sheet_id: str) -> str:
    return (sheet_id or "").strip().upper()


def _fallback_id(ref: Any) -> str:
    return f"{Path(getattr(ref, 'source_name', 'sheet')).stem}-p{int(getattr(ref, 'page_index', 0) or 0) + 1}"


def _norm_for_match(text: str) -> str:
    """Fold text for a lenient grounded-quote check (dashes, case, whitespace)."""
    return " ".join(fold_text(text or "").split()).casefold()


def _grounded(quote: str, sheet_text: str) -> bool:
    """True when ``quote`` (non-trivial) actually appears in the sheet's text layer.

    A short/blank quote can't be meaningfully grounded, so it is accepted (the
    downstream anchor pass still tiers it). Longer quotes must appear verbatim
    (modulo whitespace/dash/case folding) — an ungrounded quote is a hallucination
    signal and must not become a trusted dual-anchor leg (§16.1).
    """
    q = _norm_for_match(quote)
    if len(q) < 6:
        return True
    return q in _norm_for_match(sheet_text)


def _quote(v: Any) -> str:
    return v if isinstance(v, str) else ""


def _validate_cross_item(item: Any, sheet_map: dict[str, Any]) -> Finding | None:
    """Build a dual-anchored :class:`Finding` from one whole-set cross-QC item.

    Requires a recognized category/severity, non-empty text, and at least **two**
    of the item's referenced sheet ids (primary + ``also_on``) that resolve in the
    set. The first resolvable ref becomes the primary; the rest become ``also_on``
    legs. An item that can't be placed on two real sheets is dropped.
    """
    if not isinstance(item, dict):
        return None
    category = str(item.get("category", "")).strip().lower()
    severity = str(item.get("severity", "")).strip().lower()
    text = item.get("text", "")
    if category not in _MODEL_FINDING_CATEGORIES or severity not in _FINDING_SEVERITIES:
        return None
    if not isinstance(text, str) or not text.strip():
        return None

    refs_raw = [{
        "sheet_id": str(item.get("sheet_id", "")).strip(),
        "source_quote": _quote(item.get("source_quote", "")),
        "tile": _coerce_tile(item.get("tile")),
    }]
    for leg in item.get("also_on") or []:
        if isinstance(leg, dict):
            refs_raw.append({
                "sheet_id": str(leg.get("sheet_id", "")).strip(),
                "source_quote": _quote(leg.get("source_quote", "")),
                "tile": _coerce_tile(leg.get("tile")),
            })

    resolved = []
    seen_sheets: set[tuple] = set()
    for r in refs_raw:
        geom = sheet_map.get(_norm_id(r["sheet_id"]))
        if geom is None:
            continue
        sheet_key = source_page_key(geom.ref)
        if sheet_key in seen_sheets:
            continue
        seen_sheets.add(sheet_key)
        resolved.append((r, geom))
    if len(resolved) < 2:
        return None

    (pr, pgeom), *legs = resolved
    return Finding(
        sheet_id=pr["sheet_id"],
        source_name=pgeom.ref.source_name,
        source_id=pgeom.ref.source_id,
        page_index=pgeom.ref.page_index,
        category=category,
        severity=severity,
        text=text.strip(),
        source_quote=pr["source_quote"],
        tile=pr["tile"],
        refs=_coerce_refs(item.get("refs")),
        also_on=[
            ConflictLeg(
                sheet_id=r["sheet_id"],
                source_name=g.ref.source_name,
                source_id=g.ref.source_id,
                page_index=g.ref.page_index,
                source_quote=r["source_quote"],
                tile=r["tile"],
            )
            for r, g in legs
        ],
    )


def _finding_from_handles(item: Any, entry_by_handle: dict[str, tuple]) -> Finding | None:
    """Build a dual-anchored :class:`Finding` from a handle-keyed item (map/reconcile).

    Resolves each opaque ``sheet_handle`` against the request manifest (an unknown
    handle is dropped — never authority) and **validates the quote is grounded** in
    the referenced sheet's text before trusting the leg (§16.1). Needs >= 2 distinct
    grounded sheets or it is dropped.
    """
    if not isinstance(item, dict):
        return None
    category = str(item.get("category", "")).strip().lower()
    severity = str(item.get("severity", "")).strip().lower()
    text = item.get("text", "")
    if category not in _MODEL_FINDING_CATEGORIES or severity not in _FINDING_SEVERITIES:
        return None
    if not isinstance(text, str) or not text.strip():
        return None

    def _handle(d: dict) -> str:
        return str(d.get("sheet_handle", "") or d.get("handle", "")).strip()

    refs_raw = [(_handle(item), _quote(item.get("source_quote", "")))]
    for leg in item.get("also_on") or []:
        if isinstance(leg, dict):
            refs_raw.append((_handle(leg), _quote(leg.get("source_quote", ""))))

    resolved = []
    seen_sheets: set[tuple] = set()
    for handle, quote in refs_raw:
        entry = entry_by_handle.get(handle)
        if entry is None:                    # unknown handle → unbound
            continue
        sheet_id, geom = entry
        key = source_page_key(geom.ref)
        if key in seen_sheets:
            continue
        if quote and not _grounded(quote, getattr(geom, "sheet_text", "") or ""):
            continue                         # ungrounded quote → not a trusted leg
        seen_sheets.add(key)
        resolved.append((sheet_id, quote, geom))
    if len(resolved) < 2:
        return None

    (p_sid, p_quote, pgeom), *legs = resolved
    return Finding(
        sheet_id=p_sid,
        source_name=pgeom.ref.source_name,
        source_id=pgeom.ref.source_id,
        page_index=pgeom.ref.page_index,
        category=category,
        severity=severity,
        text=text.strip(),
        source_quote=p_quote,
        tile=None,
        refs=_coerce_refs(item.get("refs")),
        also_on=[
            ConflictLeg(
                sheet_id=sid,
                source_name=g.ref.source_name,
                source_id=g.ref.source_id,
                page_index=g.ref.page_index,
                source_quote=q,
                tile=None,
            )
            for sid, q, g in legs
        ],
    )


def _last_json_object(raw_text: str) -> dict | None:
    blocks = [
        obj
        for c in scan_structured_blocks(raw_text)
        if isinstance((obj := _tolerant_json_object(c.body)), dict)
        and (isinstance(obj.get("findings"), list) or isinstance(obj.get("facts"), list))
    ]
    return blocks[-1] if blocks else None


def _resolve_claim_handles(
    claims: list[NumericClaim], entry_by_handle: dict[str, tuple]
) -> list[NumericClaim]:
    """Translate handle-keyed claims (``sheet_id`` carries the handle) to real sheets.

    A claim whose handle is unknown is kept but left with its (handle) id so the
    arithmetic auditor can still try to resolve it by id; a resolvable handle is
    rebound to the real sheet id / source identity.
    """
    for c in claims:
        entry = entry_by_handle.get(_norm_id(c.sheet_id)) or entry_by_handle.get(c.sheet_id.strip() if c.sheet_id else "")
        if entry is not None:
            sheet_id, geom = entry
            c.sheet_id = sheet_id
            c.source_name = geom.ref.source_name
            c.source_id = geom.ref.source_id
            c.page_index = geom.ref.page_index
    return claims


# --------------------------------------------------------------------------- #
# Input assembly + budgeting
# --------------------------------------------------------------------------- #


@dataclass
class _Budget:
    total: int = 0
    included: int = 0
    omitted: int = 0

    @property
    def degraded(self) -> bool:
        return self.omitted > 0


def _budgeted_text_layer(text_layer: str, budget: _Budget) -> str:
    """Return the (capped) text layer, accumulating included/omitted char counts."""
    text_layer = text_layer or ""
    budget.total += len(text_layer)
    if len(text_layer) <= _TEXT_LAYER_BUDGET:
        budget.included += len(text_layer)
        return text_layer
    budget.included += _TEXT_LAYER_BUDGET
    budget.omitted += len(text_layer) - _TEXT_LAYER_BUDGET
    kept = text_layer[:_TEXT_LAYER_BUDGET]
    return kept + f"\n[TRUNCATED {len(text_layer) - _TEXT_LAYER_BUDGET} chars]"


def _build_whole_set_input(entries: list[tuple], budget: _Budget) -> str:
    """The whole-set user text: each sheet's id, digest, and budgeted text layer."""
    parts = [
        f"DRAWING SET — {len(entries)} sheet(s). For each sheet you get its "
        f"structured digest and its verbatim text layer.\n"
    ]
    for sheet_id, digest_text, text_layer, _geom in entries:
        tl = _budgeted_text_layer(text_layer, budget)
        parts.append(
            f"===== SHEET {sheet_id} =====\n"
            f"DIGEST:\n{(digest_text or '').strip()}\n\n"
            f"TEXT LAYER:\n{tl}\n"
        )
    parts.append("\n" + _CROSS_QC_TASK)
    return "\n".join(parts)


def _build_map_input(shard: list[tuple], handle_by_key: dict, budget: _Budget) -> str:
    """One shard's user text, sheets labeled by opaque handle (never source id)."""
    parts = [
        f"DRAWING SET SHARD — {len(shard)} sheet(s), each labeled with an opaque "
        f"HANDLE. Refer to sheets only by handle.\n"
    ]
    for sheet_id, digest_text, text_layer, geom in shard:
        handle = handle_by_key[source_page_key(geom.ref)]
        tl = _budgeted_text_layer(text_layer, budget)
        parts.append(
            f"===== SHEET {handle} =====\n"
            f"DIGEST:\n{(digest_text or '').strip()}\n\n"
            f"TEXT LAYER:\n{tl}\n"
        )
    parts.append(
        "\nReport this shard's within-shard conflicts, comparable facts, and claims "
        "in the required json block."
    )
    return "\n".join(parts)


def _build_reconcile_input(
    manifest: list[tuple], facts: list[CrossQCFact]
) -> str:
    """The reconciliation user text: the full handle manifest + every collected fact."""
    lines = ["SHEET MANIFEST (handle = sheet-id (discipline)):"]
    for handle, sheet_id, discipline in manifest:
        lines.append(f"  {handle} = {sheet_id} ({discipline or '?'})")
    lines.append("\nFACTS (sheet_handle | entity_or_tag | attribute | value | exact_quote):")
    for f in facts:
        lines.append(
            f"  {f.sheet_handle} | {f.entity_or_tag} | {f.attribute} | {f.value} | "
            f'"{f.exact_quote}"'
        )
    lines.append(
        "\nCompare the facts across the whole manifest and report cross-sheet "
        "conflicts in the required json block."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Model calls
# --------------------------------------------------------------------------- #


def _call(
    *, client: Any, model: str, system: str, user_text: str,
    max_retries: int, sleep: Any,
) -> tuple[str | None, int, int, str | None]:
    """One cross-QC model call → ``(raw_text, in, out, error)``. Never raises."""
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": DEFAULT_CROSS_QC_MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": [{"type": "text", "text": user_text}]}],
    }
    if model_supports_adaptive_thinking(model):
        kwargs["thinking"] = {"type": "adaptive"}

    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - report, don't sink the run
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return None, 0, 0, _clean_error(exc)

    raw = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    if not raw:
        return None, in_tok, out_tok, f"empty cross-qc (stop_reason={_get(resp, 'stop_reason')!r})"
    return raw, in_tok, out_tok, None


def _one_cross_qc_call(
    entries: list[tuple], sheet_map: dict[str, Any], *,
    client: Any, model: str, max_retries: int, sleep: Any, budget: _Budget,
) -> tuple[list[Finding], list[NumericClaim], int, int, str | None]:
    """Whole-set cross-QC call over ``entries`` → ``(findings, claims, in, out, err)``."""
    raw, in_tok, out_tok, err = _call(
        client=client, model=model, system=cross_qc_system_prompt(),
        user_text=_build_whole_set_input(entries, budget),
        max_retries=max_retries, sleep=sleep,
    )
    if err is not None or raw is None:
        return [], [], in_tok, out_tok, err
    obj = _last_json_object(raw)
    findings: list[Finding] = []
    if obj is not None:
        dropped = 0
        for item in obj.get("findings") or []:
            if len(findings) >= DEFAULT_CROSS_QC_MAX_FINDINGS:
                break
            f = _validate_cross_item(item, sheet_map)
            if f is None:
                dropped += 1
                continue
            findings.append(f)
        if dropped:
            _log.info("cross-qc parse: dropped %d unplaceable/invalid finding(s)", dropped)
    return findings, parse_numeric_claims(raw), in_tok, out_tok, None


def _map_call(
    shard: list[tuple], entry_by_handle: dict, handle_by_key: dict,
    discipline_by_handle: dict, *,
    client: Any, model: str, max_retries: int, sleep: Any, budget: _Budget,
) -> tuple[list[Finding], list[NumericClaim], list[CrossQCFact], int, int, str | None]:
    """One shard-map call → local findings + claims + grounded facts (handle-keyed)."""
    raw, in_tok, out_tok, err = _call(
        client=client, model=model, system=cross_qc_map_system_prompt(),
        user_text=_build_map_input(shard, handle_by_key, budget),
        max_retries=max_retries, sleep=sleep,
    )
    if err is not None or raw is None:
        return [], [], [], in_tok, out_tok, err
    obj = _last_json_object(raw) or {}
    findings = [
        f for item in (obj.get("findings") or [])
        if (f := _finding_from_handles(item, entry_by_handle)) is not None
    ][:DEFAULT_CROSS_QC_MAX_FINDINGS]
    claims = _resolve_claim_handles(parse_numeric_claims(raw), entry_by_handle)
    facts = _parse_facts(obj, entry_by_handle, discipline_by_handle)
    return findings, claims, facts, in_tok, out_tok, None


def _parse_facts(
    obj: dict, entry_by_handle: dict, discipline_by_handle: dict
) -> list[CrossQCFact]:
    """Validate + build :class:`CrossQCFact` s from a map response's ``facts`` array.

    Each fact's handle must resolve in the request manifest and its ``exact_quote``
    must be grounded in that sheet's retained text (§16.1) — an ungrounded or
    unresolvable fact is dropped so the reconciler only compares trusted data.
    """
    out: list[CrossQCFact] = []
    for item in (obj.get("facts") or []):
        if not isinstance(item, dict) or len(out) >= DEFAULT_MAP_MAX_FACTS:
            continue
        handle = str(item.get("sheet_handle", "") or "").strip()
        entry = entry_by_handle.get(handle)
        if entry is None:
            continue
        sheet_id, geom = entry
        exact_quote = _quote(item.get("exact_quote", ""))
        if not exact_quote or not _grounded(exact_quote, getattr(geom, "sheet_text", "") or ""):
            continue
        out.append(CrossQCFact(
            sheet_handle=handle,
            sheet_id=sheet_id,
            discipline=discipline_by_handle.get(handle, ""),
            entity_or_tag=str(item.get("entity_or_tag", "") or "").strip()[:120],
            attribute=str(item.get("attribute", "") or "").strip()[:120],
            value=str(item.get("value", "") or "").strip()[:120],
            exact_quote=exact_quote,
            context=str(item.get("context", "") or "").strip()[:160],
        ))
    return out


def _reconcile_call(
    manifest: list[tuple], facts: list[CrossQCFact], entry_by_handle: dict, *,
    client: Any, model: str, max_retries: int, sleep: Any,
) -> tuple[list[Finding], list[NumericClaim], int, int, str | None]:
    """One reconciliation call comparing ``facts`` across the whole manifest."""
    raw, in_tok, out_tok, err = _call(
        client=client, model=model, system=CROSS_QC_RECONCILE_SYSTEM_PROMPT,
        user_text=_build_reconcile_input(manifest, facts),
        max_retries=max_retries, sleep=sleep,
    )
    if err is not None or raw is None:
        return [], [], in_tok, out_tok, err
    obj = _last_json_object(raw) or {}
    findings = [
        f for item in (obj.get("findings") or [])
        if (f := _finding_from_handles(item, entry_by_handle)) is not None
    ][:DEFAULT_CROSS_QC_MAX_FINDINGS]
    claims = _resolve_claim_handles(parse_numeric_claims(raw), entry_by_handle)
    return findings, claims, in_tok, out_tok, None


def _reconcile_facts(
    manifest: list[tuple], facts: list[CrossQCFact], entry_by_handle: dict, *,
    client: Any, model: str, max_retries: int, sleep: Any,
) -> tuple[list[Finding], list[NumericClaim], int, int, bool]:
    """Reconcile all facts, using a balanced reduction tree when they overflow.

    Returns ``(findings, claims, in, out, completed)``. When the facts fit in one
    call it is a single reconciliation. Otherwise the facts are split into
    balanced groups and reduced pairwise up a tree — every reducer compares its two
    children and carries the (capped) union forward, so every sheet stays connected
    to the final comparison (§16.1). ``completed`` is False if any reducer failed.
    """
    if not facts:
        return [], [], 0, 0, True
    if len(facts) <= MAX_FACTS_PER_RECONCILE:
        f, c, i, o, err = _reconcile_call(
            manifest, facts, entry_by_handle,
            client=client, model=model, max_retries=max_retries, sleep=sleep,
        )
        return f, c, i, o, err is None

    # Balanced reduction: split into groups of the reconcile cap, then pair up.
    groups = [facts[i:i + MAX_FACTS_PER_RECONCILE] for i in range(0, len(facts), MAX_FACTS_PER_RECONCILE)]
    all_f: list[Finding] = []
    all_c: list[NumericClaim] = []
    tot_in = tot_out = 0
    completed = True
    while len(groups) > 1:
        next_groups: list[list[CrossQCFact]] = []
        for i in range(0, len(groups), 2):
            pair = groups[i:i + 2]
            merged = [f for g in pair for f in g]
            capped = merged[:MAX_FACTS_PER_RECONCILE]
            if len(capped) < len(merged):
                # A node had to drop facts to fit — the comparison at (and above)
                # this node is no longer exhaustive, so the reconciliation is not
                # complete (honest degradation, not a silent loss).
                completed = False
                _log.warning(
                    "cross-qc reduction: dropped %d fact(s) at a tree node "
                    "(over the %d-fact reconcile cap)",
                    len(merged) - len(capped), MAX_FACTS_PER_RECONCILE,
                )
            f, c, in_t, out_t, err = _reconcile_call(
                manifest, capped, entry_by_handle,
                client=client, model=model, max_retries=max_retries, sleep=sleep,
            )
            tot_in += in_t
            tot_out += out_t
            if err is not None:
                completed = False
            all_f.extend(f)
            all_c.extend(c)
            next_groups.append(capped)
        groups = next_groups
    return all_f, all_c, tot_in, tot_out, completed


# --------------------------------------------------------------------------- #
# Sharding
# --------------------------------------------------------------------------- #


def _shard_by_discipline(entries: list[tuple]) -> list[list[tuple]]:
    """Group sheets by discipline (sheet-id prefix); chunk any group still over
    the single-call cap. Same-series sheets — where conflicts cluster — stay
    together."""
    from .auditors.sheet_ids import discipline_token

    groups: dict[str, list[tuple]] = {}
    for e in entries:
        groups.setdefault(discipline_token(e[0]) or "?", []).append(e)
    shards: list[list[tuple]] = []
    for _disc, group in sorted(groups.items()):
        for i in range(0, len(group), MAX_SHEETS_SINGLE_CALL):
            shards.append(group[i:i + MAX_SHEETS_SINGLE_CALL])
    return shards


def _dedup_findings(findings: list[Finding]) -> list[Finding]:
    """De-duplicate by the FULL conflict (primary + legs), normalized.

    Keying on ``Finding.id`` alone would collapse two distinct conflicts sharing a
    primary quote; keying on the full leg set keeps them apart while merging the
    same conflict reported by two shards (or a shard + the reconciler)."""
    def _key(f: Finding) -> tuple:
        legs = tuple(sorted(
            (_norm_id(l.sheet_id), (l.source_quote or "").strip().lower())
            for l in f.also_on
        ))
        return (_norm_id(f.sheet_id), f.category, (f.source_quote or "").strip().lower(), legs)

    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = _key(f)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _dedup_claims(claims: list[NumericClaim]) -> list[NumericClaim]:
    """De-duplicate transcribed claims across shards + reducers (source/quote aware)."""
    seen: set[tuple] = set()
    out: list[NumericClaim] = []
    for c in claims:
        key = (_norm_id(c.sheet_id), c.kind, (c.quote or "").strip().lower(),
               tuple(str(t) for t in c.terms), str(c.expected))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def cross_sheet_qc(
    sheets: list[Any],
    geometries: list[Any],
    *,
    client: Any = None,
    model: str | None = None,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
) -> CrossQCResult:
    """Hunt cross-sheet conflicts over the set's digests + text layers.

    For sets up to :data:`MAX_SHEETS_SINGLE_CALL` it is one whole-set call. Larger
    sets shard by discipline; each shard emits local conflicts + grounded facts, and
    a final reconciliation compares the facts across all shards so a cross-shard
    conflict is still found (DA-015). Returns a :class:`CrossQCResult`; empty +
    ``skipped`` for fewer than two readable sheets. Never raises (I-3).
    """
    model = model or cross_qc_model()
    geom_by_key = {source_page_key(g.ref): g for g in geometries}

    entries: list[tuple] = []          # (sheet_id, digest_text, text_layer, geom)
    for sd in sheets:
        geom = geom_by_key.get(source_page_key(sd.ref))
        if geom is None:
            continue
        if getattr(sd, "error", None) or not (sd.text or "").strip():
            continue                   # nothing to compare from a failed/empty digest
        sheet_id = detect_sheet_id(geom) or _fallback_id(sd.ref)
        entries.append((sheet_id, sd.text, getattr(geom, "sheet_text", "") or "", geom))

    if len(entries) < MIN_SHEETS_FOR_CROSS_QC:
        return CrossQCResult(skipped=True)

    # Whole-set sheet-id map (first detection wins on a collision; warn).
    sheet_map: dict[str, Any] = {}
    for sheet_id, _t, _tl, geom in entries:
        key = _norm_id(sheet_id)
        if not key:
            continue
        if key in sheet_map:
            _log.warning(
                "cross-qc: duplicate sheet id %r (%s shadows %s); the shadowed "
                "sheet won't resolve by id", sheet_id,
                sheet_map[key].ref.source_name, geom.ref.source_name,
            )
            continue
        sheet_map[key] = geom

    if client is None:
        try:
            from .client import get_client as _get_client

            client = _get_client()
        except Exception as exc:  # noqa: BLE001 - no key etc. → skip the pass
            return CrossQCResult(error=_clean_error(exc))

    budget = _Budget()

    # ---- Small set: one whole-set call (unchanged, complete). ----
    if len(entries) <= MAX_SHEETS_SINGLE_CALL:
        findings, claims, in_tok, out_tok, err = _one_cross_qc_call(
            entries, sheet_map, client=client, model=model,
            max_retries=max_retries, sleep=sleep, budget=budget,
        )
        deduped = _dedup_findings(findings)
        _log.info(
            "cross-qc: %d conflict finding(s) across %d sheet(s), 1 call",
            len(deduped), len(entries),
        )
        return CrossQCResult(
            findings=deduped, claims=_dedup_claims(claims),
            input_tokens=in_tok, output_tokens=out_tok, error=err,
            shards_planned=1, shards_completed=0 if err else 1,
            complete=err is None and not budget.degraded,
            text_chars_total=budget.total, text_chars_included=budget.included,
            text_chars_omitted=budget.omitted, budget_degraded=budget.degraded,
        )

    # ---- Large set: map → reconcile. ----
    shards = _shard_by_discipline(entries)

    # Assign opaque, request-local handles to every entry (S001 …) + the manifest.
    entry_by_handle: dict[str, tuple] = {}      # handle -> (sheet_id, geom)
    handle_by_key: dict[tuple, str] = {}
    discipline_by_handle: dict[str, str] = {}
    manifest: list[tuple] = []                  # (handle, sheet_id, discipline)
    from .auditors.sheet_ids import discipline_token
    for i, (sheet_id, _t, _tl, geom) in enumerate(entries, start=1):
        handle = f"S{i:03d}"
        key = source_page_key(geom.ref)
        entry_by_handle[handle] = (sheet_id, geom)
        handle_by_key[key] = handle
        disc = discipline_token(sheet_id)
        discipline_by_handle[handle] = disc
        manifest.append((handle, sheet_id, disc))

    all_findings: list[Finding] = []
    all_claims: list[NumericClaim] = []
    all_facts: list[CrossQCFact] = []
    total_in = total_out = 0
    errors: list[str] = []
    shards_completed = 0
    for shard in shards:
        f, c, facts, in_tok, out_tok, err = _map_call(
            shard, entry_by_handle, handle_by_key, discipline_by_handle,
            client=client, model=model, max_retries=max_retries, sleep=sleep, budget=budget,
        )
        total_in += in_tok
        total_out += out_tok
        if err is not None:
            errors.append(err)
            continue
        shards_completed += 1
        all_findings.extend(f)
        all_claims.extend(c)
        all_facts.extend(facts)

    # Reconcile the collected facts across all shards. When the shards produced no
    # comparable facts there is nothing to reconcile (vacuously complete), but that
    # is logged — a sharded set that yields no facts is unusual.
    reconciliation_required = len(shards) > 1
    reconciliation_completed = True
    if all_facts:
        r_find, r_claims, r_in, r_out, completed = _reconcile_facts(
            manifest, all_facts, entry_by_handle,
            client=client, model=model, max_retries=max_retries, sleep=sleep,
        )
        total_in += r_in
        total_out += r_out
        all_findings.extend(r_find)
        all_claims.extend(r_claims)
        reconciliation_completed = completed
        if not completed:
            errors.append("cross-qc reconciliation incomplete")
    elif reconciliation_required:
        _log.warning(
            "cross-qc: sharded set produced no comparable facts; cross-shard "
            "reconciliation had nothing to compare"
        )

    deduped = _dedup_findings(all_findings)
    complete = (
        shards_completed == len(shards)
        and reconciliation_completed
        and not budget.degraded
    )
    _log.info(
        "cross-qc: %d conflict finding(s) across %d sheet(s), %d/%d shard(s) + "
        "reconcile(%s) over %d fact(s)%s",
        len(deduped), len(entries), shards_completed, len(shards),
        "ok" if reconciliation_completed else "incomplete", len(all_facts),
        "" if not budget.degraded else f"; budget degraded ({budget.omitted} chars omitted)",
    )
    return CrossQCResult(
        findings=deduped,
        claims=_dedup_claims(all_claims),
        input_tokens=total_in,
        output_tokens=total_out,
        error="; ".join(errors) or None,
        shards_planned=len(shards),
        shards_completed=shards_completed,
        reconciliation_required=reconciliation_required,
        reconciliation_completed=reconciliation_completed,
        facts_collected=len(all_facts),
        complete=complete,
        text_chars_total=budget.total,
        text_chars_included=budget.included,
        text_chars_omitted=budget.omitted,
        budget_degraded=budget.degraded,
    )
