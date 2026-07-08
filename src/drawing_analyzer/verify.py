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
:func:`render.iter_region_crops` (I-5).
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .core.api_config import REVIEW_MODEL_DEFAULT
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
from .models import Finding, Verification

_log = get_logger()

# Small classification call: one crop image + a short prompt.
DEFAULT_VERIFY_MAX_TOKENS = 1_000

# Context window around the anchor rect: grown to ~1.75x its size but never
# smaller than this, so a tight single-word anchor still shows its surroundings.
_CONTEXT_SCALE = 1.75
_CONTEXT_MIN_W_PT = 350.0
_CONTEXT_MIN_H_PT = 250.0

# Verifications that never happen here (already trusted / nothing to look at).
_TERMINAL_STATUSES = frozenset({"DETERMINISTIC"})

_VERDICT_MAP = {
    "CONFIRMED": "VERIFIED",
    "CONTRADICTED": "REJECTED",
    "NOT_VISIBLE": "UNCERTAIN",
}

# HTTP statuses that mean the whole pass is doomed (bad/again missing key): mark
# the rest SKIPPED rather than burning a doomed call on every finding.
_FATAL_STATUSES = frozenset({401, 403})


def default_verify_model() -> str:
    """Model for the verification pass — Opus 4.8 by default (owner preference),
    overridable via ``DRAWING_ANALYZER_VERIFY_MODEL``."""
    override = os.environ.get("DRAWING_ANALYZER_VERIFY_MODEL")
    if override and override.strip():
        return override.strip()
    return REVIEW_MODEL_DEFAULT


VERIFY_SYSTEM_PROMPT = """\
You are a senior MEP (mechanical / plumbing / fire-protection) engineer doing a \
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


def _is_verifiable(finding: Finding) -> bool:
    """A finding this pass should re-check: anchored (has a rect) and not already
    trusted by a deterministic auditor."""
    v = finding.verification
    if v is not None and v.status in _TERMINAL_STATUSES:
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


def parse_verdict(text: str) -> tuple[str, str]:
    """Map a model verdict response to ``(verification_status, note)``.

    Tolerant of fences/prose around the JSON. An unrecognized or unparseable
    verdict degrades to ``UNCERTAIN`` (never ``REJECTED`` — we must not cloud a
    finding as wrong on a garbled answer) and is logged by the caller.
    """
    obj = _tolerant_json_object(text)
    if not isinstance(obj, dict):
        return "UNCERTAIN", "unparseable verdict"
    raw = str(obj.get("verdict", "")).strip().upper()
    note = str(obj.get("note", "")).strip()[:200]
    mapped = _VERDICT_MAP.get(raw)
    if mapped is None:
        return "UNCERTAIN", note or f"unrecognized verdict {raw!r}"
    return mapped, note


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


CropRenderer = Callable[
    [list], Iterator[tuple]
]  # items: list[(finding, sheet, rect, dpi)] -> yields (finding, png|None)


def _default_crop_renderer(items: list) -> Iterator[tuple]:
    """Render crops via :mod:`render`, grouping by PDF so each opens once."""
    from . import render

    by_pdf: dict[Any, list] = {}
    by_id: dict[str, Finding] = {}
    for finding, sheet, rect, dpi in items:
        by_pdf.setdefault(sheet.ref.pdf_path, []).append(
            (finding.id, sheet.ref.page_index, rect, dpi)
        )
        by_id[finding.id] = finding
    for pdf_path, requests in by_pdf.items():
        for key, png in render.iter_region_crops(pdf_path, requests):
            yield by_id[key], png


def _sheet_lookup(sheets: Iterable[Any]) -> dict[tuple, Any]:
    out: dict[tuple, Any] = {}
    for s in sheets:
        ref = getattr(s, "ref", None)
        if ref is not None:
            out[(ref.source_name, ref.page_index)] = s
    return out


def _save_evidence(evidence_dir: Path | None, finding_id: str, png: bytes) -> str:
    """Write the crop to ``evidence/<id>.png``; return the run-relative path.

    Best-effort — a write failure must not sink verification (the verdict still
    stands), so it just drops the evidence path.
    """
    if evidence_dir is None:
        return ""
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / f"{finding_id}.png").write_bytes(png)
        return f"evidence/{finding_id}.png"
    except OSError:
        _log.warning("could not write evidence for finding %s", finding_id)
        return ""


def _verify_one(
    finding: Finding,
    crop_png: bytes,
    evidence_png: str,
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
    fatal: threading.Event,
) -> tuple[Verification, int, int]:
    """One verify call (runs on the pool). Never raises.

    Always returns ``(verification, input_tokens, output_tokens)`` — tokens are 0
    on a failure path.
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
                return Verification(status="SKIPPED", note=note, evidence_png=evidence_png), 0, 0
            # Permanent, non-fatal (e.g. 400): keep the finding but stay uncertain.
            _log.warning("verify finding %s failed: %s", finding.id, note)
            return Verification(status="UNCERTAIN", note=note, evidence_png=evidence_png), 0, 0

    status, note = parse_verdict(_message_text(resp))
    in_tok, out_tok = _message_usage(resp)
    if note == "unparseable verdict" or note.startswith("unrecognized verdict"):
        _log.info("verify finding %s: %s", finding.id, note)
    return Verification(status=status, note=note, evidence_png=evidence_png), in_tok, out_tok


class VerifyResult:
    """Lightweight tally of a verification pass."""

    __slots__ = ("verified", "rejected", "uncertain", "skipped", "input_tokens", "output_tokens")

    def __init__(self) -> None:
        self.verified = 0
        self.rejected = 0
        self.uncertain = 0
        self.skipped = 0
        self.input_tokens = 0
        self.output_tokens = 0

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

    lookup = _sheet_lookup(sheets)

    # Build the crop work-list; a finding with no matching sheet can't be cropped.
    items: list = []
    for f in verifiable:
        sheet = lookup.get((f.source_name, f.page_index))
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

    if client is None:
        try:
            from .client import get_client as _get_client

            client = _get_client()
        except Exception as exc:  # noqa: BLE001 - no key etc. -> skip the whole pass
            note = _clean_error(exc)
            for f, _s, _r, _d in items:
                f.verification = Verification(status="SKIPPED", note=note)
                result._count("SKIPPED")
            _log.warning("verification skipped (client unavailable): %s", note)
            return result

    renderer = crop_renderer or _default_crop_renderer
    workers = _resolve_workers(max_workers, len(items))
    fatal = threading.Event()
    total = len(items)
    done = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        in_flight: dict = {}

        def _collect_one() -> None:
            nonlocal done
            finished, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for fut in finished:
                finding = in_flight.pop(fut)
                verification, in_tok, out_tok = fut.result()
                finding.verification = verification
                result._count(verification.status)
                result.input_tokens += in_tok
                result.output_tokens += out_tok
                done += 1
                if progress is not None:
                    progress(done, total, f"Verifying finding {done}/{total}")

        for finding, crop_png in renderer(items):
            if fatal.is_set():
                # A fatal failure already surfaced: skip the rest without calling.
                finding.verification = Verification(
                    status="SKIPPED", note="verification aborted (auth failure)"
                )
                result._count("SKIPPED")
                done += 1
                continue
            if crop_png is None:
                finding.verification = Verification(
                    status="SKIPPED", note="crop render failed"
                )
                result._count("SKIPPED")
                done += 1
                continue
            evidence_png = _save_evidence(evidence_dir, finding.id, crop_png)
            fut = executor.submit(
                _verify_one, finding, crop_png, evidence_png,
                client=client, model=model, max_retries=max_retries,
                sleep=sleep, fatal=fatal,
            )
            in_flight[fut] = finding
            while len(in_flight) >= workers:
                _collect_one()
        while in_flight:
            _collect_one()

    _log.info(
        "verification: %d verified, %d rejected, %d uncertain, %d skipped "
        "(input=%d output=%d tok)",
        result.verified, result.rejected, result.uncertain, result.skipped,
        result.input_tokens, result.output_tokens,
    )
    return result
