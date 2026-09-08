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
from .core.tokenizer import CROSS_CHECK_RECOMMENDED_MAX
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    SheetDigest,
    _clean_error,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    stream_message,
)
from .stage_cache import (
    get_stage_cache_entry,
    put_stage_cache_entry,
    stage_cache_key,
)

# A concise overview needs far less room than a per-sheet transcription.
DEFAULT_SYNTHESIS_MAX_TOKENS = 32_000
# Deep reconciliation reasoning; "high" is accepted by Opus and Sonnet alike.
DEFAULT_SYNTHESIS_EFFORT = "high"
# Fewer than this many readable sheets and there is nothing to reconcile.
MIN_SHEETS_FOR_SYNTHESIS = 2
_SYNTHESIS_CACHE_CONTRACT = 1


def default_synthesis_model() -> str:
    """Model for the synthesis pass — Opus 5 by default (best coordination
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


# Corpus budget (chars) for the per-sheet digests in the user turn.
#
# Deliberately NOT set_identity's 200k slice budget. That stage samples the set
# (digest heads + windows), so a dropped slice degrades its answer gracefully.
# This stage sends the actual deliverable input: a sheet dropped here is a sheet
# the cross-sheet read cannot reason about at all, so every omission is a hole
# in the overview. The budget is therefore a safety rail against pathological
# input, not a routine limiter — sized from the tokenizer's own single-call
# headroom (context window - output reserve - overhead), the same derivation
# that governs the other "send everything in one call" shape in this codebase.
# Overflow drops a contiguous tail and is counted and surfaced, never silent
# (DA-028); the pipeline holds the stage at PARTIAL when it bites.
_CHARS_PER_TOKEN = 3      # conservative: digest text (tags, numbers, schedule
                          # values) tokenizes denser than English prose (~4)
_TOTAL_BUDGET = CROSS_CHECK_RECOMMENDED_MAX * _CHARS_PER_TOKEN

_SYNTHESIS_TASK_INSTRUCTION = (
    "Above are the per-sheet digests for the entire set. Now produce the "
    "set-level overview per your instructions — emphasize cross-sheet "
    "references and any conflicts, and cite the sheet numbers involved."
)


@dataclass(frozen=True)
class SynthesisPrompt:
    """The assembled user turn plus what the budget had to leave out."""

    text: str
    sheets_omitted: int = 0
    chars_omitted: int = 0


def build_synthesis_user_text(ok_sheets: list[SheetDigest]) -> SynthesisPrompt:
    """Assemble the user-turn text: every readable sheet's digest, then the task.

    Only ``ok`` sheets are included (a failed sheet has no text); each is fenced
    with its sheet label so the model can cite sheet numbers in conflicts.

    Overflow past :data:`_TOTAL_BUDGET` drops a contiguous tail of sheets and
    counts what it dropped — loss-aware, never a silent slice (cf. DA-028), and
    the same discipline set_identity / review_planner / cross_qc already apply.
    A sheet is kept or dropped whole: half a digest would invite conflicts
    against text the model cannot see.
    """
    parts: list[str] = [
        "Per-sheet digests for the set follow (one block per sheet):",
        "",
    ]
    total = len(ok_sheets)
    used = 0
    sheets_omitted = 0
    chars_omitted = 0

    def _block(index: int, sd: SheetDigest) -> tuple[str, str]:
        return f"===== Sheet {index}/{total}: {sd.ref.display_label} =====", sd.text.strip()

    for i, sd in enumerate(ok_sheets, start=1):
        header, body = _block(i, sd)
        cost = len(header) + len(body)
        if used + cost > _TOTAL_BUDGET and used > 0:
            # Stop at the first sheet that does not fit, and drop everything
            # after it. Skipping this one to squeeze in a later, smaller sheet
            # would quietly reprioritize the set and leave the notice below
            # describing a corpus with holes in it.
            for j, dropped in enumerate(ok_sheets[i - 1:], start=i):
                d_header, d_body = _block(j, dropped)
                sheets_omitted += 1
                chars_omitted += len(d_header) + len(d_body)
            break
        used += cost
        parts.append(header)
        parts.append(body)
        parts.append("")
    if sheets_omitted:
        parts.append(
            f"[The last {sheets_omitted} sheet(s) of the set were omitted from "
            f"this prompt for length; the overview below covers only the "
            f"sheets shown above.]"
        )
        parts.append("")
    parts.append(_SYNTHESIS_TASK_INSTRUCTION)
    return SynthesisPrompt(
        text="\n".join(parts),
        sheets_omitted=sheets_omitted,
        chars_omitted=chars_omitted,
    )


@dataclass
class SynthesisResult:
    """Result of the cross-sheet synthesis pass."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    error: str | None = None
    cached: bool = False
    # Loss accounting for the prompt budget (DA-028): how many sheets the
    # user turn could not carry, and how many characters that cost.
    sheets_omitted: int = 0
    chars_omitted: int = 0

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

    prompt = build_synthesis_user_text(ok_sheets)
    user_text = prompt.text
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
                sheets_omitted=prompt.sheets_omitted,
                chars_omitted=prompt.chars_omitted,
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
            resp = stream_message(client, kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - report, fall back to per-sheet
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return SynthesisResult(
                text="", model_used=model, error=_clean_error(exc),
                sheets_omitted=prompt.sheets_omitted,
                chars_omitted=prompt.chars_omitted,
            )

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    error = None if text else "empty synthesis result"
    result = SynthesisResult(
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model_used=model,
        error=error,
        sheets_omitted=prompt.sheets_omitted,
        chars_omitted=prompt.chars_omitted,
    )
    if result.ok:
        put_stage_cache_entry(
            cache,
            cache_key,
            stage="synthesis",
            payload={"text": result.text},
        )
    return result
