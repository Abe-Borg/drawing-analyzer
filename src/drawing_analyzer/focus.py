"""Set-level focus report: per-sheet digests + an operator focus -> one answer.

When the operator supplies a per-run focus (e.g. *"I am particularly interested
in the rooms, and what types of plumbing fixtures each has"*), each sheet's
vision digest already appends a per-sheet ``**Focus findings**`` section (see
:mod:`drawing_analyzer.digest`). But the operator's question is usually a
*set-level* one — rooms appear on several plan sheets and their fixtures on
schedules elsewhere — so this module runs ONE extra, **text-only** call (no
images, so cheap relative to the vision passes) that reads every readable
sheet's digest and assembles the direct, cross-sheet answer: the **Focus
Report**, the run's additional deliverable.

The standard deliverable is untouched: the focus report is generated *in
addition to* the per-sheet digests and the optional cross-sheet synthesis, and a
failure here degrades gracefully (the digests still ship; the error is
recorded). Reuses the SDK-shape-tolerant parsing, error sanitization, and
transient retry from ``digest.py``, mirroring :mod:`drawing_analyzer.synthesis`.
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
    FOCUS_SECTION_HEADER,
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

# A focused answer needs less room than a full per-sheet transcription, but can
# legitimately be long (e.g. a room-by-room fixture table for a large campus).
DEFAULT_FOCUS_MAX_TOKENS = 32_000
# Deep cross-sheet assembly reasoning; "high" is accepted by Opus and Sonnet.
DEFAULT_FOCUS_EFFORT = "high"
# Unlike synthesis (which reconciles ACROSS sheets and needs >=2), a focus
# question is answerable from a single readable sheet.
MIN_SHEETS_FOR_FOCUS = 1
_FOCUS_CACHE_CONTRACT = 1


def default_focus_model() -> str:
    """Model for the focus-report pass — Opus 5 by default, overridable via
    ``DRAWING_ANALYZER_FOCUS_MODEL``."""
    override = os.environ.get("DRAWING_ANALYZER_FOCUS_MODEL")
    if override and override.strip():
        return override.strip()
    return REVIEW_MODEL_DEFAULT


FOCUS_REPORT_SYSTEM_PROMPT = """\
You are a senior design professional who has just read a complete SET of \
construction drawings. The operator running the analysis asked a specific FOCUS \
question \
about this set. You are given (1) that focus and (2) the per-sheet TEXT digests \
of every readable sheet (each already extracted from the drawings; each may end \
with a per-sheet "{focus_header}" section gathered with the focus in mind). \
Produce the FOCUS REPORT: a direct, set-level answer to the operator's focus, \
assembled across all sheets.

Guidelines:

- **Answer the focus directly**, organized by whatever structure the focus \
implies — e.g. a focus on "the rooms and what each contains" is best answered \
room-by-room, listing each room's items/tags and counts.
- **Cite the sheet** (number/label) carrying each fact, so the operator can \
verify it on the drawings.
- **Assemble across sheets**: combine what plans, schedules, risers, details, \
and notes each contribute to the answer; reconcile them when they overlap.
- Use ONLY the provided digests. Never invent rooms, tags, fixtures, values, or \
sheets. Where the digests are silent, partial, or conflicting on something the \
focus asks about, say so explicitly — gaps and conflicts are part of the answer.
- Be complete on the focus, and do not re-summarize the set beyond what the \
focus needs.
- Output Markdown. Do NOT emit a top-level title or heading — the caller adds \
the section header. Use short subsections / bullets / tables as fits the focus.\
""".format(focus_header=FOCUS_SECTION_HEADER)


# Corpus budget (chars) for the per-sheet digests in the user turn. Same
# derivation and rationale as synthesis.py: this stage sends the actual
# deliverable input rather than a sampled corpus, so the budget is a safety
# rail against pathological input, sized from the tokenizer's single-call
# headroom (context window - output reserve - overhead), not set_identity's
# slice budget. Overflow drops a contiguous tail, is counted, and is disclosed
# both in the prompt and on the result (DA-028).
_CHARS_PER_TOKEN = 3      # conservative: digest text tokenizes denser than prose
_TOTAL_BUDGET = CROSS_CHECK_RECOMMENDED_MAX * _CHARS_PER_TOKEN

_FOCUS_TASK_INSTRUCTION = (
    "Above are the operator's focus and the per-sheet digests for the entire "
    "set. Now produce the focus report per your instructions — answer the "
    "focus directly, organized as the focus implies, citing the sheet for "
    "each fact."
)


@dataclass(frozen=True)
class FocusPrompt:
    """The assembled user turn plus what the budget had to leave out."""

    text: str
    sheets_omitted: int = 0
    chars_omitted: int = 0


def build_focus_user_text(focus: str, ok_sheets: list[SheetDigest]) -> FocusPrompt:
    """Assemble the user turn: the focus, every readable digest, then the task.

    Only ``ok`` sheets are included (a failed sheet has no text); each is fenced
    with its sheet label so the report can cite sheets. The focus appears first
    (framing) and is restated by the task instruction last, so the bulk of the
    digests sits between question framing and the ask.

    Overflow past :data:`_TOTAL_BUDGET` drops a contiguous tail of sheets and
    counts what it dropped — loss-aware, never a silent slice (cf. DA-028).
    The omission is also disclosed in the prompt itself, because a focus
    report that silently answers from part of the set reads exactly like one
    that answered from all of it.
    """
    parts: list[str] = [
        "The operator's focus for this run:",
        "",
        f"<operator_focus>\n{focus}\n</operator_focus>",
        "",
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
            # after it, so what reaches the model is a contiguous prefix rather
            # than whichever later sheets happened to be small enough.
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
            f"this prompt for length. Say so in the report if the focus asks "
            f"about coverage those sheets could have carried.]"
        )
        parts.append("")
    parts.append(_FOCUS_TASK_INSTRUCTION)
    return FocusPrompt(
        text="\n".join(parts),
        sheets_omitted=sheets_omitted,
        chars_omitted=chars_omitted,
    )


@dataclass
class FocusReportResult:
    """Result of the set-level focus-report pass."""

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


def generate_focus_report(
    sheet_digests: list[SheetDigest],
    focus: str,
    *,
    client: Any = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_FOCUS_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_FOCUS_EFFORT,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    cache: Any = None,
) -> FocusReportResult:
    """Answer the operator's focus across the set (one text-only call).

    Returns an empty, ``error``-stamped result (never raises) when there are
    fewer than :data:`MIN_SHEETS_FOR_FOCUS` readable sheets, or when the call
    fails — so the caller ships the per-sheet digests regardless. Transient
    failures are retried with backoff like the per-sheet digest.
    """
    model = model or default_focus_model()
    ok_sheets = [sd for sd in sheet_digests if sd.ok]
    if len(ok_sheets) < MIN_SHEETS_FOR_FOCUS:
        return FocusReportResult(
            text="", model_used=model,
            error=f"insufficient readable sheets for focus report ({len(ok_sheets)})",
        )

    prompt = build_focus_user_text(focus, ok_sheets)
    user_text = prompt.text
    thinking_enabled = bool(
        use_thinking and model_supports_adaptive_thinking(model)
    )
    effective_effort = effort if effort and model_supports_effort(model) else None
    cache_key = stage_cache_key(
        "focus",
        model=model,
        prompt=FOCUS_REPORT_SYSTEM_PROMPT,
        inputs={"user_text": user_text},
        params={
            "contract": _FOCUS_CACHE_CONTRACT,
            "max_tokens": int(max_tokens),
            "thinking": thinking_enabled,
            "effort": effective_effort or "",
        },
    )
    cached_entry = get_stage_cache_entry(cache, cache_key, stage="focus")
    if cached_entry is not None:
        cached_text = cached_entry.get("text")
        if isinstance(cached_text, str) and cached_text.strip():
            return FocusReportResult(
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
        "system": FOCUS_REPORT_SYSTEM_PROMPT,
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
        except Exception as exc:  # noqa: BLE001 - report, ship the digests anyway
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return FocusReportResult(
                text="", model_used=model, error=_clean_error(exc),
                sheets_omitted=prompt.sheets_omitted,
                chars_omitted=prompt.chars_omitted,
            )

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    error = None if text else "empty focus report"
    result = FocusReportResult(
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
            stage="focus",
            payload={"text": result.text},
        )
    return result
