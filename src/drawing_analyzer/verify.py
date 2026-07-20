"""Verification pass: a surgical, high-DPI re-look at each anchored finding.

The digest proposes findings; this pass disposes of them before any is clouded
onto an issued drawing. For each **anchored, non-deterministic** finding it
renders a small high-resolution crop around the finding's anchor rectangle and
asks one *small* model call whether the finding actually holds **in that crop**:

    {"verdict": "CONFIRMED" | "CONTRADICTED" | "NOT_VISIBLE", "note": "..."}

mapped to ``VERIFIED`` / ``REJECTED`` / ``UNCERTAIN``. ``NOT_VISIBLE`` is a fine
outcome (a cross-sheet conflict can't be confirmed from one crop) and maps to
``UNCERTAIN``, not ``REJECTED``. The crop the verifier saw is written to
``evidence/<finding_id>.png`` regardless of verdict — the audit trail is the
whole point.

Design mirrors the digest pipeline: crops render sequentially on the calling
thread (PyMuPDF is not thread-safe and lives only in :mod:`render`), while the
small verify calls run concurrently on a bounded pool. Transient errors reuse
:mod:`digest`'s retry/backoff. The pass is additive and non-fatal (I-3): a
per-finding failure degrades that finding to ``UNCERTAIN``; a fatal failure
(no key / auth) marks the remaining findings ``SKIPPED`` and the run continues.

This module imports **no PDF engine** — crops are rendered through
:func:`render.iter_region_crops` (I-5). Anchor rectangles are in the canonical
**PAGE_VIEW_V2** space, which is exactly the space ``get_pixmap(clip=...)`` wants,
so a crop lands on the anchored region at every page rotation (Phase 19, DA-003)
without any transform in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .core.api_config import VERIFICATION_MODEL_DEFAULT
from .diagnostics import get_logger
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    _clean_error,
    _error_status,
    _image_block,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    _tolerant_json_object,
)
from .models import EvidenceArtifact, Finding, Verification, source_page_key
from .stage_cache import (
    get_stage_cache_entry,
    put_stage_cache_entry,
    stage_cache_key,
)

_log = get_logger()

# Small classification call: one crop image + a short prompt.
DEFAULT_VERIFY_MAX_TOKENS = 1_000

# Stamped into every evidence request.json so a saved trail is attributable to the
# prompt/model that produced its verdict (bump on any verify-prompt change).
VERIFY_PROMPT_VERSION = "verify-v2"

# Context window around the anchor rect: grown to ~1.75x its size but never
# smaller than this, so a tight single-word anchor still shows its surroundings.
_CONTEXT_SCALE = 1.75
_CONTEXT_MIN_W_PT = 350.0
_CONTEXT_MIN_H_PT = 250.0

# Verifications that never happen here (already trusted / nothing to look at).
_TERMINAL_STATUSES = frozenset({"DETERMINISTIC"})
_CACHEABLE_MODEL_STATUSES = frozenset({"VERIFIED", "REJECTED", "UNCERTAIN"})
_VERIFY_CACHE_STAGE = "verify_single"
_VERIFY_CROSS_CACHE_STAGE = "verify_cross"

_VERDICT_MAP = {
    "CONFIRMED": "VERIFIED",
    "CONTRADICTED": "REJECTED",
    "NOT_VISIBLE": "UNCERTAIN",
}

# HTTP statuses that mean the whole pass is doomed (bad/again missing key): mark
# the rest SKIPPED rather than burning a doomed call on every finding.
_FATAL_STATUSES = frozenset({401, 403})


def default_verify_model() -> str:
    """Resolve the model used by the crop-verification pass.

    ``VERIFICATION_MODEL_DEFAULT`` is the centralized Sonnet-first policy and
    honors ``DRAWING_ANALYZER_VERIFICATION_MODEL`` when configuration is loaded.
    ``DRAWING_ANALYZER_VERIFY_MODEL`` predates that centralized name; keep it as
    a higher-precedence compatibility alias so existing deployments do not
    silently change models.
    """
    legacy_override = os.environ.get("DRAWING_ANALYZER_VERIFY_MODEL")
    if legacy_override and legacy_override.strip():
        return legacy_override.strip()
    return VERIFICATION_MODEL_DEFAULT


VERIFY_SYSTEM_PROMPT = """\
You are a senior design professional doing a \
back-check before a construction drawing set is issued. You are shown a SINGLE \
cropped region of ONE drawing sheet and one FINDING a prior reviewer flagged \
about it. Judge ONLY what is visible in this crop — do not re-argue the whole \
issue and do not infer beyond the image. Decide one of:

- CONFIRMED: what is visible in the crop shows the finding is correct.
- CONTRADICTED: what is visible in the crop shows the finding is wrong.
- NOT_VISIBLE: the crop does not contain enough to decide — e.g. the finding \
depends on another sheet, a schedule, or content outside this crop. This is a \
perfectly acceptable answer; do not guess.

Respond with ONLY a JSON object and nothing else:
{"verdict": "CONFIRMED" | "CONTRADICTED" | "NOT_VISIBLE", "note": "<= 25 words \
on what you actually see"}"""


def _has_anchored_legs(finding: Finding) -> bool:
    """True when a cross-sheet finding has an anchored primary *and* at least one
    anchored ``also_on`` leg — the shape the dual-crop pass can actually check."""
    legs = getattr(finding, "also_on", None)
    if not legs:
        return False
    if finding.anchor is None or finding.anchor.rect_pdf is None:
        return False
    return any(l.anchor is not None and l.anchor.rect_pdf is not None for l in legs)


def _is_verifiable(finding: Finding) -> bool:
    """A finding the single-crop pass should re-check: anchored (has a rect), not
    already trusted by a deterministic auditor, and not a dual-anchored cross-sheet
    finding (:func:`verify_cross_findings` handles those with one crop per leg)."""
    v = finding.verification
    if v is not None and v.status in _TERMINAL_STATUSES:
        return False
    if _has_anchored_legs(finding):
        return False
    return finding.anchor is not None and finding.anchor.rect_pdf is not None


def context_rect(
    rect_pdf: list[float], page_w: float, page_h: float
) -> list[float]:
    """Grow an anchor rect to a legible context window, clamped to the page.

    Centered on the anchor, sized to ``max(_CONTEXT_SCALE * dim, min dim)`` so a
    one-word anchor still carries its surroundings while a large (tile) anchor is
    barely grown. Clamped so the crop never runs off the sheet.
    """
    x0, y0, x1, y1 = rect_pdf
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    half_w = max((x1 - x0) * _CONTEXT_SCALE, _CONTEXT_MIN_W_PT) / 2.0
    half_h = max((y1 - y0) * _CONTEXT_SCALE, _CONTEXT_MIN_H_PT) / 2.0
    nx0 = max(0.0, cx - half_w)
    ny0 = max(0.0, cy - half_h)
    nx1 = min(page_w, cx + half_w) if page_w > 0 else cx + half_w
    ny1 = min(page_h, cy + half_h) if page_h > 0 else cy + half_h
    return [nx0, ny0, nx1, ny1]


def _parse_verdict_with_validity(text: str) -> tuple[str, str, bool]:
    """Return ``(status, note, valid_model_verdict)``.

    The public parser intentionally degrades malformed output to ``UNCERTAIN``.
    Caching must distinguish that failure from a valid ``NOT_VISIBLE`` verdict,
    because only the latter is a complete reusable result.
    """
    obj = _tolerant_json_object(text)
    if not isinstance(obj, dict):
        return "UNCERTAIN", "unparseable verdict", False
    raw = str(obj.get("verdict", "")).strip().upper()
    note = str(obj.get("note", "")).strip()[:200]
    mapped = _VERDICT_MAP.get(raw)
    if mapped is None:
        return "UNCERTAIN", note or f"unrecognized verdict {raw!r}", False
    return mapped, note, True


def parse_verdict(text: str) -> tuple[str, str]:
    """Map a model verdict response to ``(verification_status, note)``.

    Tolerant of fences/prose around the JSON. An unrecognized or unparseable
    verdict degrades to ``UNCERTAIN`` (never ``REJECTED`` — we must not cloud a
    finding as wrong on a garbled answer) and is logged by the caller.
    """
    status, note, _valid = _parse_verdict_with_validity(text)
    return status, note


def _build_request(finding: Finding, crop_png: bytes, model: str) -> dict[str, Any]:
    quote = finding.source_quote.strip()
    finding_text = (
        f"FINDING to check (category={finding.category}, "
        f"severity={finding.severity}):\n{finding.text.strip()}"
    )
    if quote:
        finding_text += f'\nText the reviewer quoted from the sheet: "{quote}"'
    content = [
        {"type": "text", "text": finding_text},
        {"type": "text", "text": "The cropped region of the sheet follows:"},
        _image_block(crop_png),
        {"type": "text", "text": (
            "Judge ONLY what is visible in the crop above. Respond with the JSON "
            "verdict object only."
        )},
    ]
    return {
        "model": model,
        "max_tokens": DEFAULT_VERIFY_MAX_TOKENS,
        "system": VERIFY_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }


def _cacheable_request_content(
    request: dict[str, Any], crop_sha256s: list[str],
) -> list[dict[str, Any]]:
    """Canonicalize the exact model-visible content without persisting images."""
    content = ((request.get("messages") or [{}])[0].get("content") or [])
    out: list[dict[str, Any]] = []
    image_index = 0
    for block in content:
        if not isinstance(block, dict):
            # Current request builders emit dictionaries only. Keeping an
            # explicit marker makes a future unexpected shape miss safely.
            out.append({"type": "unsupported", "python_type": type(block).__name__})
            continue
        if block.get("type") == "image":
            sha = crop_sha256s[image_index] if image_index < len(crop_sha256s) else ""
            source = block.get("source") if isinstance(block.get("source"), dict) else {}
            out.append({
                "type": "image",
                "media_type": source.get("media_type", "image/png"),
                "sha256": sha,
            })
            image_index += 1
        else:
            # Text blocks are already JSON-shaped and small; retain every field
            # so a wording or future request-shape change invalidates the entry.
            out.append(dict(block))
    return out


def _computation_cache_metadata(finding: Finding) -> dict[str, Any]:
    verification = finding.verification
    return {
        "computation_method": str(
            getattr(verification, "computation_method", "") or ""
        ),
        "operand_origin": str(getattr(verification, "operand_origin", "") or ""),
    }


def _single_verify_cache_key(
    finding: Finding,
    sheet: Any,
    crop_png: bytes,
    crop_rect: list[float] | None,
    *,
    dpi: int,
    model: str,
) -> str:
    """Key every model-visible and source/geometry-shaping single-crop input."""
    crop_sha = hashlib.sha256(crop_png).hexdigest()
    request = _build_request(finding, crop_png, model)
    sheet_ref = getattr(sheet, "ref", None)
    anchor = finding.anchor
    return stage_cache_key(
        _VERIFY_CACHE_STAGE,
        model=model,
        prompt={"version": VERIFY_PROMPT_VERSION, "system": VERIFY_SYSTEM_PROMPT},
        inputs={
            "request_content": _cacheable_request_content(request, [crop_sha]),
            "finding": {
                "text": finding.text,
                "source_quote": finding.source_quote,
                "category": finding.category,
                "severity": finding.severity,
                "sheet_id": finding.sheet_id,
                "source_id": finding.source_id,
                "source_name": finding.source_name,
                "page_index": int(finding.page_index),
                "source_page_key": list(source_page_key(finding)),
                "anchor_status": getattr(anchor, "status", ""),
                "anchor_method": getattr(anchor, "method", ""),
                "anchor_rect": list(anchor.rect_pdf) if anchor and anchor.rect_pdf else None,
                "computation": _computation_cache_metadata(finding),
            },
            "resolved_sheet": {
                "source_id": getattr(sheet_ref, "source_id", "") or "",
                "source_name": getattr(sheet_ref, "source_name", "") or "",
                "page_index": int(getattr(sheet_ref, "page_index", 0) or 0),
                "page_count": int(getattr(sheet_ref, "page_count", 0) or 0),
            },
            "crop_rect": list(crop_rect) if crop_rect is not None else None,
            "dpi": int(dpi),
            "crop_sha256": crop_sha,
        },
        params={
            "max_tokens": DEFAULT_VERIFY_MAX_TOKENS,
            "verdict_map": dict(sorted(_VERDICT_MAP.items())),
        },
    )


def _verification_from_cache_payload(
    payload: dict | None,
    artifacts: list[EvidenceArtifact],
) -> Verification | None:
    """Strictly admit only complete terminal model verdict payloads."""
    if not isinstance(payload, dict) or payload.get("valid_model_verdict") is not True:
        return None
    status = str(payload.get("status", "") or "")
    note = payload.get("note", "")
    if status not in _CACHEABLE_MODEL_STATUSES or not isinstance(note, str):
        return None
    return Verification(status=status, note=note[:200], evidence=list(artifacts))


def _cache_verification(
    cache: Any,
    key: str,
    *,
    stage: str,
    verification: Verification,
) -> None:
    """Persist only a valid terminal model verdict, never evidence paths."""
    if verification.status not in _CACHEABLE_MODEL_STATUSES:
        return
    put_stage_cache_entry(
        cache,
        key,
        stage=stage,
        payload={
            "valid_model_verdict": True,
            "status": verification.status,
            "note": verification.note,
        },
    )


CropRenderer = Callable[
    [list], Iterator[tuple]
]  # items: list[(finding, sheet, rect, dpi)] -> yields (finding, png|None)


def _default_crop_renderer(items: list) -> Iterator[tuple]:
    """Render crops via :mod:`render`, grouping by PDF so each opens once.

    Work items are keyed by their **position** in ``items``, not by
    ``finding.id`` — two distinct findings can share a content-derived id (same
    sheet / category / quote), and keying by id would drop one and render the
    other twice. The positional key is unique per item.
    """
    from . import render

    by_pdf: dict[Any, list] = {}
    by_key: dict[int, Finding] = {}
    for i, (finding, sheet, rect, dpi) in enumerate(items):
        by_pdf.setdefault(sheet.ref.pdf_path, []).append(
            (i, sheet.ref.page_index, rect, dpi)
        )
        by_key[i] = finding
    for pdf_path, requests in by_pdf.items():
        for key, png in render.iter_region_crops(pdf_path, requests):
            yield by_key[key], png


def _sheet_lookup(sheets: Iterable[Any]) -> tuple[dict[tuple, Any], set[tuple]]:
    """Map ``source_page_key(ref) -> sheet``, plus any residual *ambiguous* keys.

    With the host-owned ``source_id`` (DA-001) two input PDFs that share a
    basename get distinct keys, so a finding is always cropped against the drawing
    it actually came from. The ``ambiguous`` set is now only a *fallback* safety
    net: it still fires for legacy/hand-built refs that carry no ``source_id``
    (the key falls back to the basename), where guessing the wrong PDF would
    reject a valid finding or save evidence from another sheet — those are skipped
    rather than verified wrongly.
    """
    out: dict[tuple, Any] = {}
    ambiguous: set[tuple] = set()
    for s in sheets:
        ref = getattr(s, "ref", None)
        if ref is None:
            continue
        key = source_page_key(ref)
        prev = out.get(key)
        if prev is not None:
            prev_path = getattr(getattr(prev, "ref", None), "pdf_path", None)
            if prev_path != getattr(ref, "pdf_path", None):
                ambiguous.add(key)   # same key, different file → no source_id to split them
        out[key] = s
    return out, ambiguous


_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_component(text: str, fallback: str = "sheet") -> str:
    """A filesystem-safe path component from a sheet id / key (bounded length)."""
    cleaned = _UNSAFE_NAME.sub("_", (text or "").strip()).strip("._-")
    return cleaned[:40] or fallback


def _reserve_evidence_dir(finding: Finding, used: set[str]) -> str:
    """A unique per-finding evidence sub-directory name (``QC-041`` / a fallback).

    Prefers the finding's ``qc_id`` (assigned before verification in a real run);
    falls back to the content id for a directly-invoked test finding. Two distinct
    findings that share a content id (same sheet / category / quote) get a ``-N``
    suffix so their evidence never collides (DA-016).
    """
    base = _safe_component(finding.qc_id or finding.id or "finding", "finding")
    name = base
    n = 1
    while name in used:
        n += 1
        name = f"{base}-{n}"
    used.add(name)
    return name


def _save_crop(
    evidence_dir: Path | None,
    dir_name: str,
    png: bytes,
    *,
    qc_id: str,
    leg_index: int,
    sheet_id: str,
    source_id: str,
    source_name: str,
    page_index: int,
    anchor_rect: list[float] | None,
    crop_rect: list[float] | None,
    dpi: int,
) -> EvidenceArtifact | None:
    """Save one crop's exact bytes under ``evidence/<dir_name>/`` and hash them.

    Returns an :class:`EvidenceArtifact` (path + sha256 of the bytes on disk, which
    are the *same* bytes sent to the model) or ``None`` if the crop could not be
    durably saved — in which case the caller must NOT send it (§16.6: a verdict may
    not rest on an image absent from the evidence trail). ``None`` evidence_dir
    means evidence was not requested (returns ``None``, caller sends without a trail).
    """
    if evidence_dir is None:
        return None
    fname = f"leg-{leg_index:02d}__{_safe_component(sheet_id)}_p{int(page_index) + 1}.png"
    subdir = evidence_dir / dir_name
    try:
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / fname).write_bytes(png)
    except OSError:
        _log.warning("could not write evidence crop for %s (leg %d)", qc_id or dir_name, leg_index)
        return None
    return EvidenceArtifact(
        evidence_id=f"{dir_name}#{leg_index:02d}",
        qc_id=qc_id,
        leg_index=leg_index,
        source_id=source_id,
        source_name=source_name,
        page_index=int(page_index),
        canonical_anchor_rect=list(anchor_rect) if anchor_rect else None,
        crop_rect=list(crop_rect) if crop_rect else None,
        dpi=int(dpi),
        request_order=leg_index + 1,
        relative_path=f"evidence/{dir_name}/{fname}",
        sha256=hashlib.sha256(png).hexdigest(),
    )


def _write_evidence_request(
    evidence_dir: Path | None, dir_name: str, finding: Finding,
    verification: Verification, model: str,
) -> None:
    """Write ``evidence/<dir_name>/request.json`` — the ordered artifact metadata,
    model / prompt version, and verdict for this finding. Best-effort; never
    contains an API key or unrelated drawing text (only the finding's own fields)."""
    if evidence_dir is None or not verification.evidence:
        return
    payload = {
        "qc_id": finding.qc_id,
        "finding_id": finding.id,
        "category": finding.category,
        "severity": finding.severity,
        "text": finding.text,
        "source_quote": finding.source_quote,
        "model": model,
        "prompt_version": VERIFY_PROMPT_VERSION,
        "verdict": verification.status,
        "note": verification.note,
        "artifacts": [a.to_dict() for a in verification.evidence],
    }
    try:
        (evidence_dir / dir_name / "request.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError:
        _log.warning("could not write evidence request.json for %s", finding.qc_id or dir_name)


def _verify_one(
    finding: Finding,
    crop_png: bytes,
    artifacts: list[EvidenceArtifact],
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
    fatal: threading.Event,
) -> tuple[Verification, int, int, bool]:
    """One verify call (runs on the pool). Never raises.

    Always returns ``(verification, input_tokens, output_tokens, cacheable)``.
    Tokens are 0 and ``cacheable`` is false on a failure path. The verdict carries
    the exact evidence ``artifacts`` that were sent (the crop it judged), so the
    saved trail matches the request.
    """
    kwargs = _build_request(finding, crop_png, model)
    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - degrade the finding, never raise
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            note = _clean_error(exc)
            if _error_status(exc) in _FATAL_STATUSES:
                fatal.set()
                return Verification(status="SKIPPED", note=note, evidence=list(artifacts)), 0, 0, False
            # Permanent, non-fatal (e.g. 400): keep the finding but stay uncertain.
            _log.warning("verify finding %s failed: %s", finding.id, note)
            return Verification(status="UNCERTAIN", note=note, evidence=list(artifacts)), 0, 0, False

    status, note, valid_model_verdict = _parse_verdict_with_validity(_message_text(resp))
    in_tok, out_tok = _message_usage(resp)
    if note == "unparseable verdict" or note.startswith("unrecognized verdict"):
        _log.info("verify finding %s: %s", finding.id, note)
    return (
        Verification(status=status, note=note, evidence=list(artifacts)),
        in_tok,
        out_tok,
        valid_model_verdict,
    )


class VerifyResult:
    """Lightweight tally of a verification pass."""

    __slots__ = (
        "verified", "rejected", "uncertain", "skipped",
        "input_tokens", "output_tokens", "cache_hits", "cache_misses", "api_calls",
    )

    def __init__(self) -> None:
        self.verified = 0
        self.rejected = 0
        self.uncertain = 0
        self.skipped = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.api_calls = 0

    def _count(self, status: str) -> None:
        attr = {
            "VERIFIED": "verified", "REJECTED": "rejected",
            "UNCERTAIN": "uncertain", "SKIPPED": "skipped",
        }.get(status)
        if attr:
            setattr(self, attr, getattr(self, attr) + 1)


def _resolve_workers(max_workers: int | None, total: int) -> int:
    if max_workers is None:
        env = os.environ.get("DRAWING_ANALYZER_MAX_WORKERS")
        if env and env.strip():
            try:
                max_workers = int(env.strip())
            except ValueError:
                max_workers = 4
        else:
            max_workers = 4
    return min(max(1, int(max_workers)), max(1, total))


def verify_findings(
    findings: Iterable[Finding],
    sheets: Iterable[Any],
    *,
    client: Any = None,
    model: str | None = None,
    evidence_dir: Path | None = None,
    dpi: int = 300,
    max_workers: int | None = None,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    progress: Callable[[int, int, str], None] | None = None,
    crop_renderer: CropRenderer | None = None,
    cache: Any = None,
) -> VerifyResult:
    """Verify each anchored, non-deterministic finding (mutates ``verification``).

    ``sheets`` provide per-finding geometry (page size) and the source PDF (via
    ``.ref``); a finding whose sheet isn't found, or whose crop fails to render,
    is left ``SKIPPED``. Crops render sequentially (grouped per PDF) while the
    small verify calls run on a bounded pool. Never raises: a fatal auth failure
    marks the remaining findings ``SKIPPED``; the run continues (I-3). Returns a
    :class:`VerifyResult` tally.
    """
    findings = list(findings)
    model = model or default_verify_model()
    result = VerifyResult()

    verifiable = [f for f in findings if _is_verifiable(f)]
    if not verifiable:
        return result

    lookup, ambiguous = _sheet_lookup(sheets)

    # Build the crop work-list; a finding with no matching sheet — or one whose
    # sheet key is ambiguous (two input PDFs share a basename) — can't be cropped
    # against the right drawing, so it is skipped rather than verified wrongly.
    items: list = []
    for f in verifiable:
        key = source_page_key(f)
        if key in ambiguous:
            f.verification = Verification(
                status="SKIPPED", note="ambiguous sheet (duplicate file basename)"
            )
            result._count("SKIPPED")
            continue
        sheet = lookup.get(key)
        if sheet is None:
            f.verification = Verification(status="SKIPPED", note="sheet not available for crop")
            result._count("SKIPPED")
            continue
        page_w = float(getattr(sheet, "page_width_pt", 0.0) or 0.0)
        page_h = float(getattr(sheet, "page_height_pt", 0.0) or 0.0)
        rect = context_rect(f.anchor.rect_pdf, page_w, page_h)
        items.append((f, sheet, rect, dpi))

    if not items:
        return result

    renderer = crop_renderer or _default_crop_renderer
    workers = _resolve_workers(max_workers, len(items))
    fatal = threading.Event()
    total = len(items)
    done = 0
    used_evidence_names: set[str] = set()
    resolved_client = client
    client_resolution_attempted = client is not None
    client_unavailable_note = ""
    # id(finding) -> (sheet, crop_rect, dpi) so the yielded crop can be tagged with
    # the geometry it came from when its EvidenceArtifact is built.
    meta = {id(f): (sheet, rect, dpi) for (f, sheet, rect, dpi) in items}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight: dict = {}

        def _collect_one() -> None:
            nonlocal done
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in finished:
                finding, dir_name, cache_key = in_flight.pop(fut)
                verification, in_tok, out_tok, cacheable = fut.result()
                finding.verification = verification
                if cacheable and cache_key:
                    _cache_verification(
                        cache, cache_key, stage=_VERIFY_CACHE_STAGE,
                        verification=verification,
                    )
                # Save the audit trail (request.json) once the verdict is known.
                _write_evidence_request(evidence_dir, dir_name, finding, verification, model)
                result._count(verification.status)
                result.input_tokens += in_tok
                result.output_tokens += out_tok
                done += 1
                if progress is not None:
                    progress(done, total, f"Verifying finding {done}/{total}")

        handled: set[int] = set()
        try:
            for finding, crop_png in renderer(items):
                handled.add(id(finding))
                if crop_png is None:
                    finding.verification = Verification(
                        status="SKIPPED", note="crop render failed"
                    )
                    result._count("SKIPPED")
                    done += 1
                    continue
                sheet, crop_rect, dpi_used = meta.get(id(finding), (None, None, dpi))
                dir_name = _reserve_evidence_dir(finding, used_evidence_names)
                artifact = _save_crop(
                    evidence_dir, dir_name, crop_png,
                    qc_id=finding.qc_id, leg_index=0, sheet_id=finding.sheet_id,
                    source_id=finding.source_id, source_name=finding.source_name,
                    page_index=finding.page_index,
                    anchor_rect=finding.anchor.rect_pdf if finding.anchor else None,
                    crop_rect=crop_rect, dpi=dpi_used,
                )
                if evidence_dir is not None and artifact is None:
                    # Evidence was requested but the crop could not be durably saved:
                    # a verdict may not rest on an image absent from the trail (§16.6).
                    finding.verification = Verification(
                        status="SKIPPED",
                        note="verification evidence could not be saved (crop not verified)",
                    )
                    result._count("SKIPPED")
                    done += 1
                    continue
                artifacts = [artifact] if artifact is not None else []
                cache_key = ""
                if cache is not None:
                    cache_key = _single_verify_cache_key(
                        finding, sheet, crop_png, crop_rect,
                        dpi=dpi_used, model=model,
                    )
                    payload = get_stage_cache_entry(
                        cache, cache_key, stage=_VERIFY_CACHE_STAGE,
                    )
                    cached = _verification_from_cache_payload(payload, artifacts)
                    if cached is not None:
                        finding.verification = cached
                        _write_evidence_request(
                            evidence_dir, dir_name, finding, cached, model,
                        )
                        result._count(cached.status)
                        result.cache_hits += 1
                        done += 1
                        if progress is not None:
                            progress(done, total, f"Verifying finding {done}/{total}")
                        continue
                    result.cache_misses += 1

                # A cached verdict remains usable after an auth failure, but an
                # uncached request must not be submitted once the pass is doomed.
                if fatal.is_set():
                    finding.verification = Verification(
                        status="SKIPPED", note="verification aborted (auth failure)",
                        evidence=artifacts,
                    )
                    result._count("SKIPPED")
                    done += 1
                    continue

                if resolved_client is None and not client_resolution_attempted:
                    client_resolution_attempted = True
                    try:
                        from .client import get_client as _get_client

                        resolved_client = _get_client()
                    except Exception as exc:  # noqa: BLE001 - no key etc. -> skip misses
                        client_unavailable_note = _clean_error(exc)
                        _log.warning(
                            "verification skipped (client unavailable): %s",
                            client_unavailable_note,
                        )
                if resolved_client is None:
                    finding.verification = Verification(
                        status="SKIPPED",
                        note=client_unavailable_note or "verification client unavailable",
                        evidence=artifacts,
                    )
                    result._count("SKIPPED")
                    done += 1
                    continue
                fut = executor.submit(
                    _verify_one, finding, crop_png,
                    artifacts,
                    client=resolved_client, model=model, max_retries=max_retries,
                    sleep=sleep, fatal=fatal,
                )
                result.api_calls += 1
                in_flight[fut] = (finding, dir_name, cache_key)
                while len(in_flight) >= workers:
                    _collect_one()
        except Exception as exc:  # noqa: BLE001 - a renderer error must not sink the pass (I-3)
            _log.warning("verification crop rendering failed: %s", _clean_error(exc))
        while in_flight:
            _collect_one()
        # Any item the renderer never yielded (it raised before reaching it) is
        # left SKIPPED and counted, so the tally always accounts for every item.
        for finding, _sheet, _rect, _dpi in items:
            if id(finding) not in handled:
                finding.verification = Verification(
                    status="SKIPPED", note="verification incomplete (crop rendering failed)"
                )
                result._count("SKIPPED")

    _log.info(
        "verification: %d verified, %d rejected, %d uncertain, %d skipped "
        "(input=%d output=%d tok)",
        result.verified, result.rejected, result.uncertain, result.skipped,
        result.input_tokens, result.output_tokens,
    )
    return result


# --------------------------------------------------------------------------- #
# Cross-sheet (dual-anchor) verification — Phase 13
# --------------------------------------------------------------------------- #


def _render_leg_crops(reqs: list, dpi: int) -> list:
    """Render one crop per ``(pdf_path, page_index, rect)`` request, in order.

    Grouped per PDF (each opens once); a failed render leaves that slot ``None``.
    Stays PyMuPDF-free — crops come from :func:`render.iter_region_crops` (I-5).
    """
    from . import render

    crops: list = [None] * len(reqs)
    by_pdf: dict = {}
    for i, (pdf_path, page_index, rect) in enumerate(reqs):
        by_pdf.setdefault(pdf_path, []).append((i, page_index, rect, dpi))
    for pdf_path, requests in by_pdf.items():
        try:
            for key, png in render.iter_region_crops(pdf_path, requests):
                crops[key] = png
        except Exception as exc:  # noqa: BLE001 - a bad crop leaves its slot None
            _log.warning("cross-verify crop render failed for %s: %s", pdf_path, _clean_error(exc))
    return crops


def _build_dual_request(finding: Finding, labeled_crops: list, model: str) -> dict[str, Any]:
    """A verify request carrying one crop per sheet, so the model can compare them."""
    header = (
        f"CROSS-SHEET FINDING to check (category={finding.category}, "
        f"severity={finding.severity}):\n{finding.text.strip()}\n"
        "This finding claims the sheets below CONFLICT. Using ONLY the crops, "
        "judge whether they actually conflict."
    )
    content: list[Any] = [{"type": "text", "text": header}]
    for label, png in labeled_crops:
        content.append({"type": "text", "text": label})
        content.append(_image_block(png))
    content.append({"type": "text", "text": (
        "Respond with the JSON verdict object only: CONFIRMED if the sheets "
        "conflict as described, CONTRADICTED if they are actually consistent, "
        "NOT_VISIBLE if the crops don't show enough to tell."
    )})
    return {
        "model": model,
        "max_tokens": DEFAULT_VERIFY_MAX_TOKENS,
        "system": VERIFY_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }


def _cross_verify_cache_key(
    finding: Finding,
    request: dict[str, Any],
    legs: list[dict[str, Any]],
    *,
    model: str,
) -> str:
    """Key the exact ordered dual-crop request and every source/geometry input."""
    crop_hashes = [str(leg.get("crop_sha256", "")) for leg in legs]
    return stage_cache_key(
        _VERIFY_CROSS_CACHE_STAGE,
        model=model,
        prompt={"version": VERIFY_PROMPT_VERSION, "system": VERIFY_SYSTEM_PROMPT},
        inputs={
            "request_content": _cacheable_request_content(request, crop_hashes),
            "finding": {
                "text": finding.text,
                "source_quote": finding.source_quote,
                "category": finding.category,
                "severity": finding.severity,
                "sheet_id": finding.sheet_id,
                "source_id": finding.source_id,
                "source_name": finding.source_name,
                "page_index": int(finding.page_index),
                "computation": _computation_cache_metadata(finding),
            },
            # Ordered exactly as images appear in the model request.
            "legs": legs,
        },
        params={
            "max_tokens": DEFAULT_VERIFY_MAX_TOKENS,
            "verdict_map": dict(sorted(_VERDICT_MAP.items())),
        },
    )


@dataclass
class _PreparedCrossVerification:
    """Fully rendered/saved cross-finding request, safe for a model worker."""

    finding: Finding
    kwargs: dict[str, Any]
    artifacts: list[EvidenceArtifact]
    dir_name: str
    cache_key: str


def _prepare_cross_one(
    finding: Finding, lookup: dict, ambiguous: set, *,
    model: str, evidence_dir: Path | None, dpi: int, used: set,
) -> tuple[Verification | None, _PreparedCrossVerification | None]:
    """Sequentially render and save every leg before any worker call begins.

    DA-016: every leg crop is saved and hashed *before* it is sent, and only saved
    crops are sent — so the evidence trail (one PNG per leg + ``request.json``)
    contains exactly the images the verifier judged, in order. If fewer than two
    legs can be rendered-and-saved the conflict is NOT decided from a single crop —
    the finding degrades to ``SKIPPED`` with a precise missing-leg reason (§16.6).
    """
    dir_name = _reserve_evidence_dir(finding, used)
    # (leg_index, source_page_key, page_index, anchor_rect, sheet_id, quote,
    #  source_id, source_name, anchor_status, anchor_method)
    legs: list[tuple] = [(
        0, source_page_key(finding), finding.page_index, finding.anchor.rect_pdf,
        finding.sheet_id, finding.source_quote, finding.source_id, finding.source_name,
        finding.anchor.status, finding.anchor.method,
    )]
    li = 1
    for leg in finding.also_on:
        if leg.anchor is not None and leg.anchor.rect_pdf is not None:
            legs.append((
                li, source_page_key(leg), leg.page_index, leg.anchor.rect_pdf,
                leg.sheet_id, leg.source_quote, leg.source_id, leg.source_name,
                leg.anchor.status, leg.anchor.method,
            ))
            li += 1

    missing: list[str] = []
    plans: list[tuple] = []
    for (
        leg_index, key, page_index, rect, sid, quote, src_id, src_name,
        anchor_status, anchor_method,
    ) in legs:
        if key in ambiguous:
            missing.append(f"{sid} (ambiguous)")
            continue
        sheet = lookup.get(key)
        if sheet is None:
            missing.append(sid)
            continue
        pw = float(getattr(sheet, "page_width_pt", 0.0) or 0.0)
        ph = float(getattr(sheet, "page_height_pt", 0.0) or 0.0)
        crop_rect = context_rect(rect, pw, ph)
        plans.append((
            leg_index, sheet, page_index, rect, crop_rect, sid, quote,
            src_id, src_name, key, anchor_status, anchor_method,
        ))

    if len(plans) < 2:
        note = f"cross-sheet crops unavailable (resolved {len(plans)} of {len(legs)} legs)"
        if missing:
            note += " (missing: " + ", ".join(missing) + ")"
        return Verification(status="SKIPPED", note=note), None

    crops = _render_leg_crops([(p[1].ref.pdf_path, p[2], p[4]) for p in plans], dpi)

    kept: list[tuple] = []    # (label, crop_png, artifact_or_None, cache_leg)
    for i, plan in enumerate(plans):
        (
            leg_index, sheet, page_index, anchor_rect, crop_rect, sid, quote,
            src_id, src_name, key, anchor_status, anchor_method,
        ) = plan
        crop = crops[i]
        label = f"Sheet {sid} crop" + (f' (quoted "{quote.strip()}")' if quote.strip() else "") + ":"
        if crop is None:
            missing.append(f"{sid} (crop render failed)")
            continue
        artifact = _save_crop(
            evidence_dir, dir_name, crop, qc_id=finding.qc_id, leg_index=leg_index,
            sheet_id=sid, source_id=src_id, source_name=src_name, page_index=page_index,
            anchor_rect=anchor_rect, crop_rect=crop_rect, dpi=dpi,
        )
        if evidence_dir is not None and artifact is None:
            # Requested but not durably saved — don't send this leg (§16.6).
            missing.append(f"{sid} (evidence not saved)")
            continue
        sheet_ref = getattr(sheet, "ref", None)
        cache_leg = {
            "leg_index": int(leg_index),
            "label": label,
            "sheet_id": sid,
            "source_id": src_id,
            "source_name": src_name,
            "page_index": int(page_index),
            "source_page_key": list(key),
            "anchor_status": anchor_status,
            "anchor_method": anchor_method,
            "anchor_rect": list(anchor_rect) if anchor_rect else None,
            "crop_rect": list(crop_rect) if crop_rect else None,
            "dpi": int(dpi),
            "crop_sha256": hashlib.sha256(crop).hexdigest(),
            "resolved_sheet": {
                "source_id": getattr(sheet_ref, "source_id", "") or "",
                "source_name": getattr(sheet_ref, "source_name", "") or "",
                "page_index": int(getattr(sheet_ref, "page_index", 0) or 0),
                "page_count": int(getattr(sheet_ref, "page_count", 0) or 0),
            },
        }
        kept.append((label, crop, artifact, cache_leg))

    if len(kept) < 2:
        note = f"cross-sheet evidence incomplete: {len(kept)} crop(s) available; need >=2"
        if missing:
            note += " (missing: " + ", ".join(missing) + ")"
        return Verification(status="SKIPPED", note=note), None

    artifacts = [a for (_l, _c, a, _leg) in kept if a is not None]
    for order, art in enumerate(artifacts, 1):
        art.request_order = order   # position in the request actually sent

    labeled = [(label, crop) for (label, crop, _a, _leg) in kept]
    kwargs = _build_dual_request(finding, labeled, model)
    cache_key = _cross_verify_cache_key(
        finding, kwargs, [leg for (_l, _c, _a, leg) in kept], model=model,
    )
    return None, _PreparedCrossVerification(
        finding=finding, kwargs=kwargs, artifacts=artifacts, dir_name=dir_name,
        cache_key=cache_key,
    )


def _call_prepared_cross(
    prepared: _PreparedCrossVerification, *,
    client: Any, max_retries: int, sleep: Any,
) -> tuple[Verification, int, int, bool]:
    """Run only the independent model call; rendering has already completed."""
    attempt = 0
    while True:
        try:
            resp = client.messages.create(**prepared.kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            note = _clean_error(exc)
            _log.warning(
                "cross-verify finding %s failed: %s", prepared.finding.id, note
            )
            v = Verification(
                status="UNCERTAIN", note=note, evidence=prepared.artifacts
            )
            return v, 0, 0, False

    status, note, valid_model_verdict = _parse_verdict_with_validity(_message_text(resp))
    in_tok, out_tok = _message_usage(resp)
    v = Verification(status=status, note=note, evidence=prepared.artifacts)
    return v, in_tok, out_tok, valid_model_verdict


def _verify_cross_one(
    finding: Finding, lookup: dict, ambiguous: set, *,
    client: Any, model: str, evidence_dir: Path | None, dpi: int,
    max_retries: int, sleep: Any, used: set,
) -> tuple[Verification, int, int]:
    """Compatibility wrapper for a single sequential cross verification."""
    immediate, prepared = _prepare_cross_one(
        finding, lookup, ambiguous, model=model, evidence_dir=evidence_dir,
        dpi=dpi, used=used,
    )
    if immediate is not None:
        return immediate, 0, 0
    assert prepared is not None
    verification, in_tok, out_tok, _cacheable = _call_prepared_cross(
        prepared, client=client, max_retries=max_retries, sleep=sleep,
    )
    _write_evidence_request(
        evidence_dir, prepared.dir_name, finding, verification, model,
    )
    return verification, in_tok, out_tok


def verify_cross_findings(
    findings: Iterable[Finding],
    sheets: Iterable[Any],
    *,
    client: Any = None,
    model: str | None = None,
    evidence_dir: Path | None = None,
    dpi: int = 300,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    max_workers: int | None = None,
    sleep: Any = time.sleep,
    progress: Callable[[int, int, str], None] | None = None,
    cache: Any = None,
) -> VerifyResult:
    """Verify cross-sheet findings with **one crop per leg in a single call** (Phase
    13), so the verifier sees every side and can actually judge the conflict —
    unlike the single-crop pass, which for a cross-sheet claim can only say
    NOT_VISIBLE. Only findings with an anchored primary *and* >=1 anchored leg are
    handled (the rest fall to the single-crop pass or stay SKIPPED). Crop
    rendering and evidence persistence remain sequential; only the independent
    model calls use the existing bounded worker policy. Results are attached and
    progress emitted in input order, independent of completion order. Never
    raises (I-3)."""
    result = VerifyResult()
    dual = [f for f in findings if _has_anchored_legs(f)]
    if not dual:
        return result
    model = model or default_verify_model()
    lookup, ambiguous = _sheet_lookup(sheets)

    total = len(dual)
    used: set = set()
    outcomes: list[tuple[Verification, int, int] | None] = [None] * total
    all_prepared: dict[int, _PreparedCrossVerification] = {}
    misses_by_index: dict[int, _PreparedCrossVerification] = {}

    # PyMuPDF-backed crop rendering stays on the calling thread, in deterministic
    # finding order. Only after every request's exact evidence is stable do model
    # calls enter the worker pool.
    for index, finding in enumerate(dual):
        immediate, prepared = _prepare_cross_one(
            finding, lookup, ambiguous, model=model,
            evidence_dir=evidence_dir, dpi=dpi, used=used,
        )
        if immediate is not None:
            outcomes[index] = (immediate, 0, 0)
        elif prepared is not None:
            all_prepared[index] = prepared
            cached: Verification | None = None
            if cache is not None:
                payload = get_stage_cache_entry(
                    cache, prepared.cache_key, stage=_VERIFY_CROSS_CACHE_STAGE,
                )
                cached = _verification_from_cache_payload(
                    payload, prepared.artifacts,
                )
                if cached is not None:
                    result.cache_hits += 1
                else:
                    result.cache_misses += 1
            if cached is not None:
                outcomes[index] = (cached, 0, 0)
            else:
                misses_by_index[index] = prepared

    resolved_client = client
    if misses_by_index and resolved_client is None:
        try:
            from .client import get_client as _get_client

            resolved_client = _get_client()
        except Exception as exc:  # noqa: BLE001 - cache hits remain usable
            note = _clean_error(exc)
            _log.warning("cross-verification skipped (client unavailable): %s", note)
            for index, prepared in misses_by_index.items():
                outcomes[index] = (
                    Verification(
                        status="SKIPPED", note=note,
                        evidence=prepared.artifacts,
                    ),
                    0,
                    0,
                )

    workers = _resolve_workers(max_workers, max(1, len(misses_by_index)))
    if misses_by_index and resolved_client is not None:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            submitted = [
                (
                    index,
                    prepared,
                    executor.submit(
                        _call_prepared_cross, prepared, client=resolved_client,
                        max_retries=max_retries, sleep=sleep,
                    ),
                )
                for index, prepared in misses_by_index.items()
            ]
            result.api_calls += len(submitted)
            # Futures are resolved in input order for deterministic attachment;
            # they were all submitted first, so their API calls still overlap.
            for index, prepared, future in submitted:
                try:
                    verification, in_tok, out_tok, cacheable = future.result()
                    outcomes[index] = (verification, in_tok, out_tok)
                    if cacheable:
                        _cache_verification(
                            cache, prepared.cache_key,
                            stage=_VERIFY_CROSS_CACHE_STAGE,
                            verification=verification,
                        )
                except Exception as exc:  # noqa: BLE001 - defensive, never sink QC
                    note = _clean_error(exc)
                    _log.warning(
                        "cross-verify finding %s worker failed: %s",
                        prepared.finding.id, note,
                    )
                    outcomes[index] = (
                        Verification(
                            status="UNCERTAIN", note=note,
                            evidence=prepared.artifacts,
                        ),
                        0,
                        0,
                    )

    for index, f in enumerate(dual):
        outcome = outcomes[index]
        if outcome is None:  # defensive: preparation should always resolve one path
            outcome = (Verification(status="SKIPPED", note="cross verification unavailable"), 0, 0)
        verification, in_tok, out_tok = outcome
        prepared = all_prepared.get(index)
        if prepared is not None:
            _write_evidence_request(
                evidence_dir, prepared.dir_name, f, verification, model,
            )
        f.verification = verification
        result._count(verification.status)
        result.input_tokens += in_tok
        result.output_tokens += out_tok
        if progress is not None:
            progress(index + 1, total, f"Verifying conflict {index + 1}/{total}")

    _log.info(
        "cross-verification: %d verified, %d rejected, %d uncertain, %d skipped",
        result.verified, result.rejected, result.uncertain, result.skipped,
    )
    return result
