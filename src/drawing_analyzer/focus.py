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
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    FOCUS_SECTION_HEADER,
    SheetDigest,
    _clean_error,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
)

# A focused answer needs less room than a full per-sheet transcription, but can
# legitimately be long (e.g. a room-by-room fixture table for a large campus).
DEFAULT_FOCUS_MAX_TOKENS = 8_000
# Deep cross-sheet assembly reasoning; "high" is accepted by Opus and Sonnet.
DEFAULT_FOCUS_EFFORT = "high"
# Unlike synthesis (which reconciles ACROSS sheets and needs >=2), a focus
# question is answerable from a single readable sheet.
MIN_SHEETS_FOR_FOCUS = 1


def default_focus_model() -> str:
    """Model for the focus-report pass — Opus 4.8 by default, overridable via
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


_FOCUS_TASK_INSTRUCTION = (
    "Above are the operator's focus and the per-sheet digests for the entire "
    "set. Now produce the focus report per your instructions — answer the "
    "focus directly, organized as the focus implies, citing the sheet for "
    "each fact."
)


def build_focus_user_text(focus: str, ok_sheets: list[SheetDigest]) -> str:
    """Assemble the user turn: the focus, every readable digest, then the task.

    Only ``ok`` sheets are included (a failed sheet has no text); each is fenced
    with its sheet label so the report can cite sheets. The focus appears first
    (framing) and is restated by the task instruction last, so the bulk of the
    digests sits between question framing and the ask.
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
    for i, sd in enumerate(ok_sheets, start=1):
        parts.append(f"===== Sheet {i}/{total}: {sd.ref.display_label} =====")
        parts.append(sd.text.strip())
        parts.append("")
    parts.append(_FOCUS_TASK_INSTRUCTION)
    return "\n".join(parts)


@dataclass
class FocusReportResult:
    """Result of the set-level focus-report pass."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    error: str | None = None

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

    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": FOCUS_REPORT_SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": build_focus_user_text(focus, ok_sheets)}
        ],
    }
    if use_thinking and model_supports_adaptive_thinking(model):
        kwargs["thinking"] = {"type": "adaptive"}
    if effort and model_supports_effort(model):
        kwargs["output_config"] = {"effort": effort}

    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - report, ship the digests anyway
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return FocusReportResult(text="", model_used=model, error=_clean_error(exc))

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    error = None if text else "empty focus report"
    return FocusReportResult(
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model_used=model,
        error=error,
    )
