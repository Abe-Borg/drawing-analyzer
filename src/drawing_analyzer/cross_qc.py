"""Cross-sheet QC pass (Phase 13) — a deliberate conflict hunt across the set.

Distinct from the prose ``synthesis`` (which stays exactly as-is): this pass has
one job — find **conflicts between sheets**. It is a *text-reasoning* task, so it
sends the per-sheet digests plus the verbatim text layers and **no images**.

Its findings carry **dual anchors**: a primary anchor on one sheet plus one or
more ``also_on`` legs on the other sheets in the conflict, each resolved from the
set's sheet-id map so the markup writer can cloud *both* sheets. The prose
``combined_text`` is never touched (I-2) — cross-QC findings live only in the
findings artifacts.

For sets up to ``MAX_SHEETS_SINGLE_CALL`` it is one Opus call (adaptive thinking);
above that it shards by discipline (same-series sheets, where conflicts cluster,
stay together) and unions the shard findings. The whole-set sheet-id map is
shared across shards, so a leg can still resolve to a sheet in another shard.

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
    _FENCE_RE,
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
)
from .models import ConflictLeg, Finding
from .reference_audit import detect_sheet_id

_log = get_logger()

# One Opus call up to this many sheets; above it, shard by discipline.
MAX_SHEETS_SINGLE_CALL = 40
# Nothing to compare across with fewer than two readable sheets.
MIN_SHEETS_FOR_CROSS_QC = 2
DEFAULT_CROSS_QC_MAX_TOKENS = 16_000
DEFAULT_CROSS_QC_MAX_FINDINGS = 60
# Cap each sheet's text layer in the prompt (the digest already summarizes it);
# a rare over-long layer is truncated with a marker, never silently.
_TEXT_LAYER_CAP = 4_000


def cross_qc_model() -> str:
    """The cross-sheet QC model (``DRAWING_ANALYZER_CROSS_QC_MODEL``, else Opus)."""
    return os.environ.get("DRAWING_ANALYZER_CROSS_QC_MODEL") or REVIEW_MODEL_DEFAULT


# --------------------------------------------------------------------------- #
# Prompt
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
containing {"findings": [ ... ]}. Each finding is a CROSS-SHEET conflict with: \
sheet_id (the PRIMARY sheet, one of the sheets involved); category (one of code, \
conflict, coordination, question); severity (one of high, medium, low); text (the \
conflict in <= 2 sentences, naming the sheets); source_quote (COPY VERBATIM the \
conflicting string from the PRIMARY sheet's text layer); tile ([row, col] on the \
primary sheet, or omit); also_on (an array of the OTHER sheets in the conflict, \
each an object {"sheet_id", "source_quote" (verbatim from THAT sheet), "tile"}); \
refs (optional array of codes/specs). Every finding MUST list at least one \
also_on sheet — a conflict is between sheets. Emit at most 60 findings, most \
important first; emit {"findings": []} if there are no cross-sheet conflicts."""


def cross_qc_system_prompt() -> str:
    """The effective cross-QC system prompt: persona + findings instruction."""
    return CROSS_QC_SYSTEM_PROMPT + _CROSS_QC_FINDINGS_INSTRUCTION


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #


@dataclass
class CrossQCResult:
    """The outcome of the cross-sheet QC pass."""

    findings: list[Finding] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    skipped: bool = False        # too few readable sheets — a non-error no-op


# --------------------------------------------------------------------------- #
# Sheet-id resolution + parsing
# --------------------------------------------------------------------------- #


def _norm_id(sheet_id: str) -> str:
    return (sheet_id or "").strip().upper()


def _fallback_id(ref: Any) -> str:
    return f"{Path(getattr(ref, 'source_name', 'sheet')).stem}-p{int(getattr(ref, 'page_index', 0) or 0) + 1}"


def _validate_cross_item(item: Any, sheet_map: dict[str, Any]) -> Finding | None:
    """Build a dual-anchored :class:`Finding` from one cross-QC item, or drop it.

    Requires a recognized category/severity, non-empty text, and — since a
    cross-sheet conflict is *between* sheets — at least **two** of the item's
    referenced sheet ids (primary + ``also_on``) that resolve in the set. The
    first resolvable ref becomes the primary; the rest become ``also_on`` legs.
    An item that can't be placed on two real sheets is dropped (counted, logged).
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

    def _quote(v: Any) -> str:
        return v if isinstance(v, str) else ""

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

    resolved = [(r, sheet_map[_norm_id(r["sheet_id"])])
                for r in refs_raw if _norm_id(r["sheet_id"]) in sheet_map]
    if len(resolved) < 2:
        return None

    (pr, pgeom), *legs = resolved
    return Finding(
        sheet_id=pr["sheet_id"],
        source_name=pgeom.ref.source_name,
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
                page_index=g.ref.page_index,
                source_quote=r["source_quote"],
                tile=r["tile"],
            )
            for r, g in legs
        ],
    )


def _parse_cross_findings(raw_text: str, sheet_map: dict[str, Any]) -> list[Finding]:
    """Parse the cross-QC findings block (the last fenced json block), placing
    each finding via ``sheet_map``. Tolerant — a bad item is dropped, not fatal."""
    blocks = [
        obj
        for m in _FENCE_RE.finditer(raw_text)
        if isinstance((obj := _tolerant_json_object(m.group(2))), dict)
        and isinstance(obj.get("findings"), list)
    ]
    if not blocks:
        return []
    out: list[Finding] = []
    dropped = 0
    for item in blocks[-1].get("findings") or []:
        if len(out) >= DEFAULT_CROSS_QC_MAX_FINDINGS:
            break
        finding = _validate_cross_item(item, sheet_map)
        if finding is None:
            dropped += 1
            continue
        out.append(finding)
    if dropped:
        _log.info("cross-qc parse: dropped %d unplaceable/invalid finding(s)", dropped)
    return out


# --------------------------------------------------------------------------- #
# Input assembly + model call
# --------------------------------------------------------------------------- #


def _build_input(entries: list[tuple]) -> str:
    """The user text: each sheet's id, digest, and (capped) text layer."""
    parts = [
        f"DRAWING SET — {len(entries)} sheet(s). For each sheet you get its "
        f"structured digest and its verbatim text layer.\n"
    ]
    for sheet_id, digest_text, text_layer, _geom in entries:
        tl = text_layer[:_TEXT_LAYER_CAP]
        if len(text_layer) > _TEXT_LAYER_CAP:
            tl += "\n[TRUNCATED]"
        parts.append(
            f"===== SHEET {sheet_id} =====\n"
            f"DIGEST:\n{(digest_text or '').strip()}\n\n"
            f"TEXT LAYER:\n{tl}\n"
        )
    parts.append("\n" + _CROSS_QC_TASK)
    return "\n".join(parts)


def _one_cross_qc_call(
    entries: list[tuple],
    sheet_map: dict[str, Any],
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
) -> tuple[list[Finding], int, int, str | None]:
    """One cross-QC model call over ``entries`` → ``(findings, in, out, err)``."""
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": DEFAULT_CROSS_QC_MAX_TOKENS,
        "system": cross_qc_system_prompt(),
        "messages": [{"role": "user", "content": [{"type": "text", "text": _build_input(entries)}]}],
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
            return [], 0, 0, _clean_error(exc)

    raw = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    if not raw:
        return [], in_tok, out_tok, f"empty cross-qc (stop_reason={_get(resp, 'stop_reason')!r})"
    return _parse_cross_findings(raw, sheet_map), in_tok, out_tok, None


def _shard_by_discipline(entries: list[tuple]) -> list[list[tuple]]:
    """Group sheets by discipline (sheet-id prefix); chunk any group still over
    the single-call cap. Same-series sheets — where conflicts cluster — stay
    together."""
    from .profiles import discipline_hint

    groups: dict[str, list[tuple]] = {}
    for e in entries:
        groups.setdefault(discipline_hint(e[0]) or "?", []).append(e)
    shards: list[list[tuple]] = []
    for group in groups.values():
        for i in range(0, len(group), MAX_SHEETS_SINGLE_CALL):
            shards.append(group[i:i + MAX_SHEETS_SINGLE_CALL])
    return shards


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

    Pairs each :class:`~drawing_analyzer.digest.SheetDigest` with its geometry
    (by source/page), detects each sheet's id for the map, and runs one call
    (or shards for a large set). Returns a :class:`CrossQCResult`; empty +
    ``skipped`` for fewer than two readable sheets. Never raises.
    """
    model = model or cross_qc_model()
    geom_by_key = {(g.ref.source_name, g.ref.page_index): g for g in geometries}

    entries: list[tuple] = []          # (sheet_id, digest_text, text_layer, geom)
    for sd in sheets:
        geom = geom_by_key.get((sd.ref.source_name, sd.ref.page_index))
        if geom is None:
            continue
        if getattr(sd, "error", None) or not (sd.text or "").strip():
            continue                   # nothing to compare from a failed/empty digest
        sheet_id = detect_sheet_id(geom) or _fallback_id(sd.ref)
        entries.append((sheet_id, sd.text, getattr(geom, "sheet_text", "") or "", geom))

    if len(entries) < MIN_SHEETS_FOR_CROSS_QC:
        return CrossQCResult(skipped=True)

    # Whole-set sheet-id map (shared across shards so a leg can resolve anywhere).
    sheet_map: dict[str, Any] = {}
    for sheet_id, _t, _tl, geom in entries:
        sheet_map.setdefault(_norm_id(sheet_id), geom)

    if client is None:
        try:
            from .client import get_client as _get_client

            client = _get_client()
        except Exception as exc:  # noqa: BLE001 - no key etc. → skip the pass
            return CrossQCResult(error=_clean_error(exc))

    shards = [entries] if len(entries) <= MAX_SHEETS_SINGLE_CALL else _shard_by_discipline(entries)
    all_findings: list[Finding] = []
    total_in = total_out = 0
    errors: list[str] = []
    for shard in shards:
        findings, in_tok, out_tok, err = _one_cross_qc_call(
            shard, sheet_map, client=client, model=model,
            max_retries=max_retries, sleep=sleep,
        )
        total_in += in_tok
        total_out += out_tok
        if err is not None:
            errors.append(err)
            continue
        all_findings.extend(findings)

    # Union across shards, de-duplicated by content id.
    seen: set[str] = set()
    deduped: list[Finding] = []
    for f in all_findings:
        if f.id in seen:
            continue
        seen.add(f.id)
        deduped.append(f)

    _log.info(
        "cross-qc: %d conflict finding(s) across %d sheet(s), %d shard(s)",
        len(deduped), len(entries), len(shards),
    )
    return CrossQCResult(
        findings=deduped,
        input_tokens=total_in,
        output_tokens=total_out,
        error="; ".join(errors) or None,
    )
