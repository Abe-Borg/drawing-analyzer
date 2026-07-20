"""Cross-sheet synthesis: per-sheet digests -> one set-level overview.

Each sheet is digested in isolation (``digest.py``), so relationships that only
emerge *across* sheets — equipment shown on a plan sheet and detailed in a
schedule on another, risers continued across match-lines, a tag scheduled but
never drawn — are invisible in the per-sheet text. This module runs ONE extra,
**text-only** call (no images, so cheap relative to the vision passes) that
reads every per-sheet digest and reconciles them into a concise "Drawing Set
Overview", which the pipeline prepends to the combined digest.

It reuses the SDK-shape-tolerant parsing, error sanitization, and transient
retry from ``digest.py`` so a synthesis failure degrades gracefully (the
per-sheet digests still ship) and never dumps a raw HTML error page.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from .core.api_config import (
    REVIEW_MODEL_DEFAULT,
    model_supports_adaptive_thinking,
    model_supports_effort,
)
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    SheetDigest,
    _clean_error,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
)
from .stage_cache import (
    get_stage_cache_entry,
    put_stage_cache_entry,
    stage_cache_key,
)

# A concise overview needs far less room than a per-sheet transcription.
DEFAULT_SYNTHESIS_MAX_TOKENS = 8_000
# Deep reconciliation reasoning; "high" is accepted by Opus and Sonnet alike.
DEFAULT_SYNTHESIS_EFFORT = "high"
# Fewer than this many readable sheets and there is nothing to reconcile.
MIN_SHEETS_FOR_SYNTHESIS = 2
_SYNTHESIS_CACHE_CONTRACT = 1


def default_synthesis_model() -> str:
    """Model for the synthesis pass — Opus 4.8 by default (best coordination
    reasoning), overridable via ``DRAWING_ANALYZER_SYNTHESIS_MODEL``."""
    override = os.environ.get("DRAWING_ANALYZER_SYNTHESIS_MODEL")
    if override and override.strip():
        return override.strip()
    return REVIEW_MODEL_DEFAULT


SYNTHESIS_SYSTEM_PROMPT = """\
You are a senior design professional reviewing a complete SET of construction \
drawings. You are given the per-sheet TEXT digests of every sheet in the set (each already \
extracted from the drawings). Produce a concise SET-LEVEL overview that a \
specification reviewer — who will NOT see the drawings — can use to understand \
the set as a whole and check the written specs against it.

Concentrate on what only emerges ACROSS sheets (not a re-transcription of each \
sheet):

- **Systems spanning sheets**: equipment shown on a plan sheet and detailed in a \
schedule on another; risers / mains / distribution continued across match-lines.
- **Tag cross-references**: where the same tag appears on multiple sheets (e.g. \
the same equipment or device tag on a plan sheet and in a schedule on another \
sheet), reconcile them and name the authoritative source.
- **Cross-sheet / cross-discipline conflicts**: a tag scheduled but never drawn \
(or vice-versa), conflicting capacities or sizes, mismatched detail references, \
disagreements between disciplines — flag these explicitly; they are the highest- \
value output.
- **Set-wide scope**: which disciplines are present, roughly how many sheets per \
discipline, and any general notes that apply set-wide.

Rules:
- Use ONLY the provided digests. Never invent tags, values, models, code \
citations, or sheets. If the digests disagree or a digest is missing/failed, say \
so rather than guessing.
- Be concise — this is an overview, not a transcription. Don't repeat every \
schedule row; point to the sheet that carries it.
- Output Markdown. Do NOT emit a top-level title or heading — the caller adds the \
section header. Use short subsections / bullets."""


_SYNTHESIS_TASK_INSTRUCTION = (
    "Above are the per-sheet digests for the entire set. Now produce the "
    "set-level overview per your instructions — emphasize cross-sheet "
    "references and any conflicts, and cite the sheet numbers involved."
)


def build_synthesis_user_text(ok_sheets: list[SheetDigest]) -> str:
    """Assemble the user-turn text: every readable sheet's digest, then the task.

    Only ``ok`` sheets are included (a failed sheet has no text); each is fenced
    with its sheet label so the model can cite sheet numbers in conflicts.
    """
    parts: list[str] = [
        "Per-sheet digests for the set follow (one block per sheet):",
        "",
    ]
    total = len(ok_sheets)
    for i, sd in enumerate(ok_sheets, start=1):
        parts.append(f"===== Sheet {i}/{total}: {sd.ref.display_label} =====")
        parts.append(sd.text.strip())
        parts.append("")
    parts.append(_SYNTHESIS_TASK_INSTRUCTION)
    return "\n".join(parts)


@dataclass
class SynthesisResult:
    """Result of the cross-sheet synthesis pass."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    error: str | None = None
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


def synthesize_drawing_set(
    sheet_digests: list[SheetDigest],
    *,
    client: Any = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_SYNTHESIS_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_SYNTHESIS_EFFORT,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    cache: Any = None,
) -> SynthesisResult:
    """Reconcile per-sheet digests into one set-level overview (text-only call).

    Returns an empty, ``error``-stamped result (never raises) when there are
    fewer than :data:`MIN_SHEETS_FOR_SYNTHESIS` readable sheets, or when the call
    fails — so the caller can fall back to the plain per-sheet digests. Transient
    failures are retried with backoff like the per-sheet digest.
    """
    model = model or default_synthesis_model()
    ok_sheets = [sd for sd in sheet_digests if sd.ok]
    if len(ok_sheets) < MIN_SHEETS_FOR_SYNTHESIS:
        return SynthesisResult(
            text="", model_used=model,
            error=f"insufficient readable sheets for synthesis ({len(ok_sheets)})",
        )

    user_text = build_synthesis_user_text(ok_sheets)
    thinking_enabled = bool(
        use_thinking and model_supports_adaptive_thinking(model)
    )
    effective_effort = effort if effort and model_supports_effort(model) else None
    cache_key = stage_cache_key(
        "synthesis",
        model=model,
        prompt=SYNTHESIS_SYSTEM_PROMPT,
        inputs={"user_text": user_text},
        params={
            "contract": _SYNTHESIS_CACHE_CONTRACT,
            "max_tokens": int(max_tokens),
            "thinking": thinking_enabled,
            "effort": effective_effort or "",
        },
    )
    cached_entry = get_stage_cache_entry(cache, cache_key, stage="synthesis")
    if cached_entry is not None:
        cached_text = cached_entry.get("text")
        if isinstance(cached_text, str) and cached_text.strip():
            return SynthesisResult(
                text=cached_text,
                model_used=model,
                cached=True,
            )

    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": SYNTHESIS_SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_text}
        ],
    }
    if thinking_enabled:
        kwargs["thinking"] = {"type": "adaptive"}
    if effective_effort:
        kwargs["output_config"] = {"effort": effective_effort}

    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - report, fall back to per-sheet
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return SynthesisResult(text="", model_used=model, error=_clean_error(exc))

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    error = None if text else "empty synthesis result"
    result = SynthesisResult(
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model_used=model,
        error=error,
    )
    if result.ok:
        put_stage_cache_entry(
            cache,
            cache_key,
            stage="synthesis",
            payload={"text": result.text},
        )
    return result
