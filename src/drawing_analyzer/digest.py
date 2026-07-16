"""Per-sheet vision digest: one rendered drawing sheet -> structured text.

Each sheet is sent to Claude Opus 4.8 in a *single* request carrying the
overview image plus all grid tiles, so the model reads the whole sheet at once.
The model auto-detects the sheet number and discipline from the title block and
emits a structured text digest suitable for splicing into the spec reviewer's
Project Context. Output is plain text (markdown) — no tool schema — because the
digest is reference prose for a downstream text-only pipeline.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .core.api_config import (
    REVIEW_MODEL_DEFAULT,
    model_supports_adaptive_thinking,
    model_supports_effort,
)
from .core.tokenizer import estimate_image_tokens_total
from .diagnostics import get_logger
from .digest_cache import digest_cache_key
from .models import (
    CLAIM_KINDS,
    FINDINGS_ABSENT,
    FINDINGS_MALFORMED_CLOSED,
    FINDINGS_MALFORMED_UNCLOSED,
    FINDINGS_PARSED_CLOSED,
    FINDINGS_PARSED_UNCLOSED,
    FINDINGS_TRUNCATED,
    Finding,
    ImageTile,
    NumericClaim,
    RenderedSheet,
    SheetRef,
    compute_finding_id,
)
from .tiling import parse_tile_label

_log = get_logger()

# Room for adaptive thinking plus a thorough per-sheet digest; stays at/under the
# ~16k non-streaming-safe ceiling so a single sheet completes well within the
# SDK request timeout.
DEFAULT_DIGEST_MAX_TOKENS = 16_000

# Effort for the read. "high" is intelligence-appropriate for dense drawings and
# is accepted by both Opus and Sonnet (so a model override never 400s on it).
DEFAULT_DIGEST_EFFORT = "high"

# App-level retries layered ON TOP of the Anthropic SDK's own per-call retries.
# A drawing run is a long sequence of large vision requests; a transient blip
# (502/503/connection) on one sheet shouldn't permanently doom that sheet for
# the whole run, so a failed transient call is re-attempted after a short
# backoff. Kept small so a genuine outage still ends quickly with a clean error.
DEFAULT_DIGEST_MAX_RETRIES = 2

# HTTP statuses worth re-attempting: rate limit (429), Anthropic "overloaded"
# (529), and the 5xx gateway/upstream family that surfaced as the cloudflare
# "502 Bad Gateway" pages. 4xx other than 429 are caller errors — never retried.
_TRANSIENT_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

# Short, human-readable phrases for the statuses we surface. The raw exception
# string for a 5xx is the upstream's full HTML error page (the cloudflare 502
# body the operator saw dumped into the dialog), so we render a canonical
# message from the status code instead and discard the HTML entirely.
_STATUS_PHRASES = {
    408: "request timeout",
    409: "conflict",
    429: "rate limited",
    500: "internal server error",
    502: "bad gateway",
    503: "service unavailable",
    504: "gateway timeout",
    529: "overloaded",
}

# Connection / timeout SDK error classes (matched by name so this module needs
# no hard import of the anthropic exception types and stays trivially testable).
_CONNECTION_ERROR_NAMES = frozenset({"APIConnectionError", "ConnectionError"})
_TIMEOUT_ERROR_NAMES = frozenset({"APITimeoutError", "Timeout", "ReadTimeout"})

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _error_status(exc: Exception) -> int | None:
    """Return the HTTP status carried by an SDK error, if any (duck-typed)."""
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def _is_transient_status_error(exc: Exception) -> bool:
    """True when ``exc`` carries a retry-worthy transient HTTP *status*.

    A status response in :data:`_TRANSIENT_STATUSES` (429 / 5xx / 529) is a
    *definitive* server rejection — the request was not processed — so
    re-issuing it is safe even for a non-idempotent create. This is the narrower
    predicate the Files-API upload retry uses: unlike :func:`_is_transient_error`
    it deliberately excludes the connection / timeout classes, which are
    *ambiguous* (the server may have already accepted the upload before the
    response was lost) and so must not be blindly re-issued as a fresh upload —
    that would orphan the first, accepted file. The SDK retries those connection
    / timeout cases internally with a reused idempotency key instead.
    """
    status = _error_status(exc)
    return status is not None and status in _TRANSIENT_STATUSES


def _is_transient_error(exc: Exception) -> bool:
    """True when ``exc`` is a retry-worthy transient failure.

    Recognizes both an HTTP status in :data:`_TRANSIENT_STATUSES` (via
    :func:`_is_transient_status_error`) and the connection / timeout SDK error
    classes by name. A plain ``RuntimeError`` (what the hermetic tests raise) is
    *not* transient, so the existing capture-without-retry behavior is preserved
    and tests never sleep.
    """
    if _is_transient_status_error(exc):
        return True
    name = type(exc).__name__
    return name in _CONNECTION_ERROR_NAMES or name in _TIMEOUT_ERROR_NAMES


def _error_detail_text(exc: Exception) -> str:
    """Cleaned, HTML-free, truncated message body for an exception.

    Prefers the SDK error's ``.message`` (the API's ``invalid_request_error``
    text — e.g. *"...prompt is too long..."* or the 32 MB request-size message)
    over the noisier ``str(exc)`` repr, then tag-strips, whitespace-collapses,
    and truncates so a wall of HTML never reaches the UI.
    """
    msg = getattr(exc, "message", None)
    text = msg if isinstance(msg, str) and msg.strip() else str(exc)
    return " ".join(_HTML_TAG_RE.sub(" ", text).split())[:300]


def _clean_error(exc: Exception) -> str:
    """Render a concise, HTML-free error string for ``SheetDigest.error``.

    A 5xx surfaces as the upstream's full HTML page; we map the status to a
    canonical phrase and drop the body so the dialog (and the failure blockquote
    inside ``combined_text``) shows ``502 bad gateway (server temporarily
    unavailable — try again)`` rather than a wall of ``<html>…cloudflare…``.
    A 4xx with no canonical phrase (400/413/…) keeps its API message appended —
    ``HTTP 400: ...prompt is too long...`` — because a client error is permanent
    and the *reason* is the actionable part (collapsing it to a bare ``HTTP 400``
    is exactly what hid the 32 MB request-size failure). Connection / timeout
    errors get a fixed message; anything else is tag-stripped and truncated.
    """
    status = _error_status(exc)
    if status is not None:
        phrase = _STATUS_PHRASES.get(status)
        if phrase is None:
            base = f"HTTP {status}"
            detail = _error_detail_text(exc)
            return f"{base}: {detail}" if detail and detail != base else base
        if status >= 500 or status == 429:
            return f"{status} {phrase} (server temporarily unavailable — try again)"
        return f"{status} {phrase}"
    name = type(exc).__name__
    if name in _CONNECTION_ERROR_NAMES:
        return "connection error (network/API unreachable — try again)"
    if name in _TIMEOUT_ERROR_NAMES:
        return "request timed out — try again"
    text = _error_detail_text(exc)
    return text[:200] if text else name


def _retry_backoff_seconds(attempt: int) -> float:
    """Exponential backoff before retry ``attempt`` (0-based): 2s, 4s, 8s…"""
    return 2.0 * (2 ** attempt)


DIGEST_SYSTEM_PROMPT = """\
You are a senior design professional reading construction drawings. Your job is to \
produce a precise, factual TEXT digest of ONE drawing sheet so that a separate \
specification reviewer — who will NOT see the drawings — can check written specs \
against what the drawings actually show.

You are given that single sheet as:
  1. an OVERVIEW image (the entire sheet at lower resolution, for global layout \
and match-lines), followed by
  2. a grid of high-resolution TILES that together cover the same sheet, with \
slight overlap. Each tile is labeled with its grid position.

The tiles and overview are the SAME sheet — synthesize them into one coherent \
understanding. Do not describe them tile-by-tile or repeat content that appears \
in overlapping tiles.

Extract, in this order, only what you can actually read on the sheet:

- **Header line**: `Sheet <number> - <discipline> - <title>` from the title \
block (discipline = the sheet's own discipline as shown, e.g. Architectural / \
Structural / Civil / Mechanical / Electrical / Plumbing / Fire Protection). If a \
field is illegible, say so rather than guessing.
- **Scope / systems shown** on this sheet.
- **Equipment & schedules**: transcribe schedule rows that matter — tag/mark, \
type, capacity/size, model or basis-of-design, and any noted standard. Keep tags \
verbatim (e.g. `A-1`, `S-2`, `VAV-3`, `P-4`).
- **Plan content**: spaces/rooms shown and what equipment, elements, or systems \
serve them; use the sheet's own column grid bubbles / match-lines / detail \
callouts as the spatial reference frame where possible.
- **Key dimensions, elevations, clearances, slopes, and component sizes** \
(structural members, pipes, ducts, conduits, etc.) that a spec would need to be \
consistent with.
- **General notes, keynotes, and callouts** (transcribe the substantive ones).
- **Coordination / cross-discipline items**: penetrations, shared chases, \
equipment served by another discipline, anything that must agree across trades \
or with the specifications.

Rules:
- Report only what is legible on THIS sheet. Never invent values, tags, models, \
or code citations. If something is cut off or unreadable, write \
`[illegible]` / `[partially legible]` rather than guessing.
- Be concise but complete — favor transcribed tags/values over prose.
- Output Markdown. Begin with the header line, then the sections above as they \
apply. Omit a section if the sheet has nothing for it."""


_DIGEST_TASK_INSTRUCTION = (
    "Now produce the structured text digest of this single sheet, following the "
    "format in your instructions. Begin with the `Sheet <number> - <discipline> "
    "- <title>` header line."
)

# The verbatim vector text layer is spliced into the user turn *before* the
# images so the model treats it as the source of truth for exact strings (a
# real flow-test table OCR'd "540" as "660" from a low-res raster in the
# prototype; the vector text can't make that class of error). The header framing
# is a fixed template; a raster sheet with no text layer gets the placeholder
# instead — the explicit "rely on the images" disclosure.
_SHEET_TEXT_LAYER_HEADER = (
    "SHEET TEXT LAYER (machine-extracted, verbatim, in reading order — use it "
    "for exact strings such as tags, schedule values, note numbers, and sheet "
    "references; it may be empty for scanned sheets):"
)
_SHEET_TEXT_LAYER_RASTER_PLACEHOLDER = (
    "[none — this sheet is raster-only; rely on the images]"
)

# Appended to the *end* of the effective system prompt (after any focus
# addendum) so the model emits a machine-readable findings block as the very
# last thing in its output. The prose digest is unchanged and sacred (I-2); the
# parser (:func:`parse_findings`) strips this block back off before the prose
# reaches ``combined_text``. Categories deliberately exclude "reference" — that
# belongs to the deterministic reference auditor, not the model's own read.
_FINDINGS_INSTRUCTION = """\


FINDINGS (final section, machine-read):
After the digest — after every prose section above, including any Focus \
findings section — output a single fenced code block labeled json containing \
{"findings": [ ... ]}. Each finding is an object with: sheet_id; category (one \
of code, conflict, coordination, question); severity (one of high, medium, \
low); text (the finding, at most two sentences); recommended_action (one \
sentence, imperative: what the reviewer should DO about it - e.g. "Confirm the \
relief-valve setpoint with the mechanical engineer and revise the schedule"); \
source_quote (COPY VERBATIM \
from the SHEET TEXT LAYER above — exact characters — or "" ONLY if the issue is \
purely graphical with no supporting text); tile_label (the label printed on the \
tile where you saw it, exactly as shown — e.g. "r1c1" — or omit it for a \
whole-sheet finding); refs (an array of any code or spec references you believe apply — \
cite conservatively). Every item you report under a Coordination or Conflict \
prose section MUST also appear as an entry in this findings block — the block is \
the machine-read mirror of those sections. Emit at most 40 findings, most \
important first; emit {"findings": []} if there are none. Put nothing but the \
JSON object inside the block, and write no prose after it."""

# Folded into the digest cache key so any edit to the prompt, the task
# instruction, the text-layer framing, or the findings instruction re-digests
# rather than serving a cached read produced under the old prompt.
DIGEST_PROMPT_VERSION = hashlib.sha256(
    (
        DIGEST_SYSTEM_PROMPT
        + "\x00"
        + _DIGEST_TASK_INSTRUCTION
        + "\x00"
        + _SHEET_TEXT_LAYER_HEADER
        + "\x00"
        + _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER
        + "\x00"
        + _FINDINGS_INSTRUCTION
    ).encode("utf-8")
).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Optional per-run focus.
#
# The operator may supply a free-text focus for one run (e.g. "I am
# particularly interested in the rooms, and what types of plumbing fixtures
# each has"). The focus NEVER replaces or shrinks the standard digest — it is
# appended to the system prompt as an addendum asking for one extra, final
# `**Focus findings**` section per sheet, so the model reads the drawings with
# the operator's question in mind while the default deliverable stays intact.
# The set-level answer is then assembled by :mod:`drawing_analyzer.focus`.
# ---------------------------------------------------------------------------

# The exact section header the addendum asks for. Downstream consumers (the
# HTML report's category filter, the focus-report pass) key off it.
FOCUS_SECTION_HEADER = "Focus findings"

_FOCUS_ADDENDUM_TEMPLATE = """\


ADDITIONAL PER-RUN FOCUS — the operator running this analysis is particularly \
interested in the following:

<operator_focus>
{focus}
</operator_focus>

Produce the standard digest in full first, exactly as instructed above — the \
focus must not shrink or displace it. Then add ONE extra FINAL section headed \
`**{header}**` reporting everything legible on THIS sheet that bears on the \
operator's focus: transcribe the relevant rooms/spaces, tags, fixture or \
equipment types, sizes, and notes verbatim, and say where on the sheet each \
appears. The same rules apply — never invent or guess. If the sheet shows \
nothing relevant to the focus, the section body should be exactly \
`Nothing relevant to the focus on this sheet.`"""


def normalize_focus(focus: Any) -> str | None:
    """Normalize an operator-supplied per-run focus: stripped text, or ``None``.

    ``None`` / empty / whitespace-only all mean "no focus" — the single
    normalization every entry point (pipeline, digest, batch) applies so the
    no-focus request and cache key stay byte-identical to a run that never
    heard of the feature.
    """
    if focus is None:
        return None
    text = str(focus).strip()
    return text or None


def build_focus_addendum(focus: str) -> str:
    """Render the system-prompt addendum for a (normalized, non-empty) focus."""
    return _FOCUS_ADDENDUM_TEMPLATE.format(focus=focus, header=FOCUS_SECTION_HEADER)


def digest_system_prompt(
    focus: str | None = None,
    specs_text: str | None = None,
    *,
    cache_specs: bool = True,
) -> "str | list[dict]":
    """The effective system prompt: the standard digest prompt, an optional
    project-specifications block, an optional focus addendum, then the
    findings-block instruction.

    The findings instruction is appended **last** (after any focus addendum) so
    the machine-read JSON block is emitted after every prose section — including
    the optional ``Focus findings`` section — which is what keeps the parser's
    "last fenced block" rule unambiguous.

    ``specs_text`` (optional uploaded project specifications, see
    :mod:`drawing_analyzer.spec_documents`) is spliced in as its own
    ``<project_specifications>`` block, placed BEFORE the focus addendum so
    the (large, run-constant) base-prompt+specs prefix can be prompt-cached
    independent of whatever focus is set this run — see ``cache_specs``.

    ``cache_specs`` (default ``True``) attaches an Anthropic ``cache_control``
    breakpoint to the base-prompt+specs block when specs are present, so
    sheets after the first serve that (potentially tens-of-thousands-of-token)
    block at the ~0.1x cache-read rate instead of full price. The real-time
    digest path leaves this on; the Message-Batches path (batch_digest.py)
    passes ``False`` — batch items submit in parallel, so a cache breakpoint
    there would only add the 1.25x write cost to every item with nothing to
    read yet (mirrors critique.py's ``cache_prefix`` rationale,
    critique.py's ``build_critique_request_params``). When ``False``, or when
    there is no ``specs_text``, the return value is a single plain string —
    no shape change from before this feature (verified against
    ``tests/test_drawing_focus.py``'s no-specs prompt assertions).
    """
    focus = normalize_focus(focus)
    specs_text = normalize_specs_text(specs_text)
    tail = (build_focus_addendum(focus) if focus is not None else "") + _FINDINGS_INSTRUCTION
    if specs_text is None:
        return DIGEST_SYSTEM_PROMPT + tail
    head = DIGEST_SYSTEM_PROMPT + build_specs_addendum(specs_text)
    if not cache_specs:
        return head + tail
    return [
        {"type": "text", "text": head, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": tail},
    ]


def focus_cache_fragment(focus: Any) -> str | None:
    """The digest-cache-key component for a per-run focus (``None`` disables it).

    Hashes the *rendered* addendum — instruction template + operator text — so a
    cached digest is reused only when both the focus and the way it is spliced
    into the prompt are unchanged (the same rationale as
    :data:`DIGEST_PROMPT_VERSION` for the static prompt). ``None`` (no focus)
    leaves the key byte-identical to a pre-focus key, so existing cached
    digests stay valid and a later no-focus re-run still hits them.
    """
    focus = normalize_focus(focus)
    return build_focus_addendum(focus) if focus is not None else None


# ---------------------------------------------------------------------------
# Optional project specifications (uploaded spec documents, see
# :mod:`drawing_analyzer.spec_documents`).
#
# Distinct from ``focus`` above (an operator's ad-hoc question about this run)
# and from the unrelated, pre-existing "Project Context" concept
# (:data:`core.tokenizer.PROJECT_CONTEXT_MAX_TOKENS` — an external, sibling
# spec-review tool this repo's ``combined_text`` is manually pasted into): this
# is ground-truth written spec text the operator uploaded for THIS run. Unlike
# ``focus``, it does NOT create a new prose section — conflicts between the
# specs and what's on the sheet are folded into the ORDINARY findings block
# (the same ledger -> anchor -> verify -> markup pipeline every other finding
# uses), so there is zero new downstream plumbing.
# ---------------------------------------------------------------------------

_SPECS_ADDENDUM_TEMPLATE = """\


PROJECT SPECIFICATIONS (ground truth) — the operator has supplied the \
following written project specifications for this run. They are NOT part of \
the drawing set; treat them as the authoritative written requirements the \
drawings must be consistent with.

<project_specifications>
{specs}
</project_specifications>

When something on THIS sheet conflicts with, is missing per, or is otherwise \
inconsistent with the specifications above, report it as an ORDINARY finding \
in the FINDINGS block below — category "conflict" or "code" as appropriate, \
quoting the drawing text (not the spec text) in source_quote as usual, and \
naming the specific spec requirement in the finding's text. Do NOT add a \
separate prose section for this — the specifications are reference material \
to check against, not something to summarize or transcribe. If nothing on \
this sheet conflicts with them, do not mention them at all."""


def normalize_specs_text(specs_text: Any) -> str | None:
    """Normalize uploaded project-specifications text: stripped, or ``None``
    when empty — mirrors :func:`normalize_focus`."""
    if specs_text is None:
        return None
    text = str(specs_text).strip()
    return text or None


def build_specs_addendum(specs_text: str) -> str:
    """Render the system-prompt addendum for (normalized, non-empty) spec text."""
    return _SPECS_ADDENDUM_TEMPLATE.format(specs=specs_text)


def specs_cache_fragment(specs_text: Any) -> str | None:
    """Digest-cache-key component for uploaded spec text (mirrors
    :func:`focus_cache_fragment`): hashes the *rendered* addendum, folded in
    only when non-empty, so a no-specs key is byte-identical to a pre-feature
    key and existing cache entries stay valid."""
    specs_text = normalize_specs_text(specs_text)
    return build_specs_addendum(specs_text) if specs_text is not None else None


def _image_block(png_bytes: bytes) -> dict:
    """A base64 PNG image content block."""
    data = base64.standard_b64encode(png_bytes).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": data,
        },
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def _sheet_text_layer_block(sheet: RenderedSheet) -> dict:
    """The verbatim-text-layer text block for one sheet.

    Renders the extracted ``sheet_text`` under the fixed header, or the
    raster-only placeholder when the sheet has no usable text layer (empty
    ``sheet_text`` — a scanned / pasted-raster sheet). Placed before the images
    so the model reads the exact strings first.
    """
    body = sheet.sheet_text if sheet.sheet_text.strip() else _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER
    return _text_block(f"{_SHEET_TEXT_LAYER_HEADER}\n{body}")


def build_user_content_blocks(
    sheet: RenderedSheet,
    image_block: "Callable[[ImageTile], dict]",
    *,
    task_instruction: str = _DIGEST_TASK_INSTRUCTION,
) -> list[dict]:
    """Assemble the user-turn content blocks for one sheet.

    Order: framing text -> overview image -> (label + tile image) per tile ->
    final task instruction. Keeping the task instruction last places the bulk of
    the imagery before the question, per the vision/PDF best practice, while the
    per-tile labels give the model a coarse placement frame for each crop.

    ``image_block`` builds the content block for one :class:`ImageTile`, so the
    inline-base64 transport (the real-time digest) and the Files-API transport
    (the batch digest, which references each uploaded image by ``file_id`` to
    keep the request body under the 32 MB Messages-API limit) share one
    byte-stable prompt shape — only the image source differs.

    ``task_instruction`` is the final text block (default: the digest task). The
    critique pass reuses this identical imagery + text-layer framing but passes
    its own closing instruction, so the two vision reads see the same sheet
    presentation and differ only in what they are asked to produce.

    The sheet's verbatim text layer is inserted right after the framing text and
    before any image, so both transports carry the exact-strings grounding the
    resolution drop relies on (a raster sheet gets the "rely on the images"
    placeholder instead).
    """
    framing = (
        f"You are given ONE construction drawing sheet "
        f"({sheet.ref.display_label}), rendered as a low-resolution overview "
        f"followed by a {sheet.rows}x{sheet.cols} grid of overlapping "
        f"high-resolution tiles. Read them together as a single sheet."
    )
    # Blank-tile suppression drops pixel-uniform tiles before upload; tell the
    # model which grid positions are absent because they were empty (1-based
    # (row, col), matching the per-tile labels below) so a missing tile reads as
    # "nothing there", not "withheld".
    if getattr(sheet, "omitted_tiles", None):
        positions = ", ".join(f"(r{r + 1}c{c + 1})" for r, c in sheet.omitted_tiles)
        framing += (
            f" Tiles omitted as completely blank (no content): {positions}."
        )
    blocks: list[dict] = [
        _text_block(framing),
        _sheet_text_layer_block(sheet),
        _text_block("OVERVIEW (entire sheet):"),
        image_block(sheet.overview),
    ]
    for tile in sheet.tiles:
        blocks.append(
            _text_block(
                f"Tile r{tile.row + 1}c{tile.col + 1} of "
                f"{sheet.rows}x{sheet.cols} ({tile.label}):"
            )
        )
        blocks.append(image_block(tile))
    blocks.append(_text_block(task_instruction))
    return blocks


def build_user_content(
    sheet: RenderedSheet, *, task_instruction: str = _DIGEST_TASK_INSTRUCTION
) -> list[dict]:
    """Inline-base64 user content for one sheet (the real-time digest transport).

    Thin wrapper over :func:`build_user_content_blocks` that inlines each image
    as base64. The batch path uses the same builder with a ``file_id`` image
    block (see :mod:`drawing_analyzer.file_upload`). ``task_instruction`` overrides
    the closing instruction (the critique pass passes its own).
    """
    return build_user_content_blocks(
        sheet, lambda t: _image_block(t.png_bytes), task_instruction=task_instruction
    )


def build_digest_request_params(
    content: list[dict],
    *,
    model: str = REVIEW_MODEL_DEFAULT,
    max_tokens: int = DEFAULT_DIGEST_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_DIGEST_EFFORT,
    focus: str | None = None,
    specs_text: str | None = None,
    cache_specs: bool = True,
) -> dict[str, Any]:
    """Build the Messages-API request body for one sheet digest.

    The single source of truth for the digest request shape — used by both the
    real-time path (:func:`digest_sheet`) and the batch path
    (:mod:`drawing_analyzer.batch_digest`), so the two can't drift on model /
    thinking / effort. ``thinking`` and ``output_config`` are attached only when
    the model supports them (Opus 4.8 supports both; an unknown override
    silently omits them, never producing an API-rejected request). ``focus``
    (an optional per-run operator focus) and ``specs_text`` (optional uploaded
    project specifications) ride only on the system prompt, so the user
    content — including the batch path's uploaded images — is identical
    regardless of either. See :func:`digest_system_prompt` for ``cache_specs``.
    """
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": digest_system_prompt(focus, specs_text, cache_specs=cache_specs),
        "messages": [{"role": "user", "content": content}],
    }
    if use_thinking and model_supports_adaptive_thinking(model):
        params["thinking"] = {"type": "adaptive"}
    if effort and model_supports_effort(model):
        params["output_config"] = {"effort": effort}
    return params


@dataclass
class SheetDigest:
    """Result of digesting one sheet."""

    ref: SheetRef
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    image_token_estimate: int = 0
    stop_reason: str | None = None
    error: str | None = None
    # True when the text was served from the digest cache (no API call). The
    # token counts on a cache hit are the originally-recorded usage; no new
    # tokens were billed.
    cached: bool = False
    # True when this sheet was digested via a synchronous real-time *rescue* call
    # after failing inside a Message Batch (:func:`batch_digest._rescue_failed_items_sync`)
    # — it did NOT ride the Batches API, so it is billed at the full real-time rate,
    # not the 50% batch discount. The usage ledger prices it REAL_TIME (Phase 23B).
    rescued: bool = False
    # Structured findings parsed out of the raw response (empty when the model
    # emitted none or the block failed to parse). ``text`` is the prose with the
    # findings block already stripped (I-2), so ``findings`` and ``text`` never
    # overlap. ``findings_note`` is error-adjacent telemetry (dropped/capped/
    # malformed) that NEVER marks the sheet failed — the prose digest still
    # shipped, so a findings-parse problem must not touch ``error`` or ``ok``.
    findings: list[Finding] = field(default_factory=list)
    findings_note: str = ""
    # Prompt-cache telemetry for the read/write of the (optional) cached
    # project-specifications system-prompt block. Runtime-only — a digest
    # cache *hit* made no API call this run, so it correctly reports 0/0
    # (mirrors input_tokens/output_tokens on a hit).
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text.strip())


# ---------------------------------------------------------------------------
# SDK-shape-tolerant accessors (mirror the reviewer/verifier parsers: handle
# both attribute-style SDK objects and plain dicts).
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _message_text(resp: Any) -> str:
    content = _get(resp, "content", []) or []
    parts: list[str] = []
    for block in content:
        if _get(block, "type") == "text":
            text = _get(block, "text", "") or ""
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _message_usage(resp: Any) -> tuple[int, int]:
    usage = _get(resp, "usage")
    if usage is None:
        return 0, 0
    return (
        int(_get(usage, "input_tokens", 0) or 0),
        int(_get(usage, "output_tokens", 0) or 0),
    )


# ---------------------------------------------------------------------------
# Structured findings parsing.
#
# The model appends a fenced ``json`` block ({"findings": [...]}) after the
# prose digest. The parser pulls that block out, validates each item, and hands
# back the prose with the block removed — so the sacred prose digest (I-2) is
# byte-identical to a pre-feature response when no block is present, and the
# structured findings live only in their own artifacts.
# ---------------------------------------------------------------------------

# At most this many findings per sheet are kept (the instruction asks the model
# for the same cap; anything beyond is truncated, most-important-first).
MAX_FINDINGS_PER_SHEET = 40

# At most this many numeric claims (Phase 14) parsed from one response — the same
# tolerant "last fenced json block" the findings come from also carries a "claims"
# array the arithmetic auditor checks. Capped, most-important-first, like findings.
MAX_CLAIMS_PER_SHEET = 40

# Categories the *model* may emit. "reference" is intentionally excluded — that
# category belongs to the deterministic reference auditor, not the vision read.
_MODEL_FINDING_CATEGORIES = frozenset({"code", "conflict", "coordination", "question"})
_FINDING_SEVERITIES = frozenset({"high", "medium", "low"})

# A fenced code block: optional language label, then body up to the closing
# fence. DOTALL so the body spans lines; non-greedy so blocks don't merge.
# Retained for back-compat imports; the truncation-safe path uses
# :func:`scan_structured_blocks` (which also recognises an *unclosed* fence).
_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)

# The opening line of a fenced block anchored at a given offset: ``` + optional
# language label + optional trailing spaces + newline. An unclosed (truncated)
# block matches this opener even with no closing ``` — the whole point of the
# line-aware scanner (DA-009).
_OPEN_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n")
# A structurally plausible top-level key. Used to decide whether an *unparseable*
# fenced block was nonetheless a findings/claims *attempt* (so it is stripped from
# the sacred prose and recorded as drift) — never triggered by ordinary prose that
# merely contains the English word "findings" (§14.1).
_FINDINGS_KEY_RE = re.compile(r'"findings"\s*:')
_CLAIMS_KEY_RE = re.compile(r'"claims"\s*:')
# A fence line that was itself truncated — ``` + an optional language label and
# nothing else to end-of-string (the model was cut off *on the opener line*, before
# its newline). Recognised so a dangling machine-block opener is still stripped from
# the sacred prose (DA-009), not misread as ordinary text.
_DANGLING_FENCE_RE = re.compile(r"[ \t]*([A-Za-z0-9_+-]*)[ \t]*\Z")


@dataclass
class StructuredBlockCandidate:
    """One fenced block the scanner found — closed OR unclosed (§14.1).

    ``opening_offset`` is the index of the opening ``` fence; ``ending_offset`` is
    just past the closing fence, or ``len(raw)`` when the block was never closed
    (truncated output). ``closed`` distinguishes the two. ``looks_like_findings`` /
    ``looks_like_claims`` mark a json-labeled block carrying the corresponding
    top-level key — a high-confidence *attempt* even if the body will not parse.
    """

    opening_offset: int
    body_offset: int
    ending_offset: int
    language: str
    body: str
    closed: bool
    looks_like_findings: bool
    looks_like_claims: bool


def scan_structured_blocks(raw_text: str) -> list[StructuredBlockCandidate]:
    """Line-aware scan for fenced code blocks, including *unclosed* ones (§14.1).

    Unlike :data:`_FENCE_RE` (which requires a closing ```` ``` ````), this
    recognises an opening fence with no close — the truncated-output case that let
    a partial machine block leak into the sacred prose (DA-009). Closed-block
    behaviour is byte-compatible with the old scanner: the body runs to the first
    subsequent ```` ``` ```` (non-greedy), so adjacent blocks never merge.
    """
    out: list[StructuredBlockCandidate] = []
    i = 0
    n = len(raw_text)
    while i < n:
        open_idx = raw_text.find("```", i)
        if open_idx == -1:
            break
        m = _OPEN_FENCE_RE.match(raw_text, open_idx)
        if m is None:
            # No trailing newline after the fence. If the REST of the string is only
            # an (optional) language label, the fence line was itself truncated
            # (max_tokens cut before the newline) — a dangling machine-block opener
            # that must still be stripped from the prose (DA-009). Emit it as an
            # unclosed, empty-body block. Otherwise it's an inline ``` — skip it.
            dangling = _DANGLING_FENCE_RE.match(raw_text, open_idx + 3)
            if dangling is not None and dangling.end() == n:
                # A fence line at EOF with nothing after it but a (possibly partial)
                # label is unambiguously a truncated machine-block opener — the label
                # may itself be cut mid-word ("```jso"), so it is stripped regardless
                # of whether it spells "json" yet (DA-009).
                language = (dangling.group(1) or "").strip().lower()
                out.append(StructuredBlockCandidate(
                    opening_offset=open_idx, body_offset=n, ending_offset=n,
                    language=language, body="", closed=False,
                    looks_like_findings=True,
                    looks_like_claims=False,
                ))
                break
            i = open_idx + 3
            continue
        language = (m.group(1) or "").strip().lower()
        body_start = m.end()
        close_idx = raw_text.find("```", body_start)
        if close_idx == -1:
            body = raw_text[body_start:]
            ending, closed = n, False
        else:
            body = raw_text[body_start:close_idx]
            ending, closed = close_idx + 3, True
        is_json = language in ("json", "")
        # An UNCLOSED json/empty fence is a truncated machine-block fragment — the
        # findings block being cut off (the model emits it last). Treat it as a
        # findings *attempt* even before the ``"findings":`` key was emitted, so a
        # cut *before the colon* (or before any key) is still stripped, not leaked.
        out.append(StructuredBlockCandidate(
            opening_offset=open_idx,
            body_offset=body_start,
            ending_offset=ending,
            language=language,
            body=body,
            closed=closed,
            looks_like_findings=bool(is_json and (_FINDINGS_KEY_RE.search(body) or not closed)),
            looks_like_claims=bool(is_json and _CLAIMS_KEY_RE.search(body)),
        ))
        i = ending if closed else n
    return out


def _strip_trailing_commas(s: str) -> str:
    """Drop commas that sit (ignoring whitespace) right before a ``}`` or ``]``.

    **String-aware**: a comma inside a JSON string literal is never touched, so a
    verbatim ``source_quote`` like ``"KEYNOTES 3,]"`` survives intact. Only used
    as a repair pass on JSON that already failed to parse as-is.
    """
    out: list[str] = []
    in_str = False
    escaped = False
    n = len(s)
    for i, ch in enumerate(s):
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            continue
        if ch == ",":
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j < n and s[j] in "}]":
                continue  # structural trailing comma → drop it
        out.append(ch)
    return "".join(out)


def _tolerant_json_object(block_body: str) -> dict | None:
    """Best-effort parse of a JSON object from a fenced block body.

    Tolerant of the small ways models drift: surrounding prose (trim to the
    outermost ``{...}``) and a trailing comma before a closing brace/bracket.
    Well-formed JSON is parsed **as-is and never mutated**, so a verbatim
    ``source_quote`` is preserved exactly; the trailing-comma repair (itself
    string-aware) runs only when the raw candidate fails to parse. Returns the
    dict, or ``None`` if it can't be parsed into one.
    """
    s = block_body.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    candidate = s[start : end + 1]
    try:
        obj = json.loads(candidate)
    except (ValueError, TypeError):
        try:
            obj = json.loads(_strip_trailing_commas(candidate))
        except (ValueError, TypeError):
            return None
    return obj if isinstance(obj, dict) else None


def _coerce_tile(value: Any) -> list[int] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return [int(value[0]), int(value[1])]
        except (TypeError, ValueError):
            return None
    return None


def _coerce_legacy_tile(value: Any, rows: int, cols: int) -> list[int] | None:
    """A legacy ``tile: [row, col]`` array — accepted EXPLICITLY as zero-based.

    Phase 25 §17.1: the current contract is ``tile_label`` (``"r1c1"``); a bare
    array is only honored for backward compatibility, read as **zero-based** and
    bounds-checked, and NEVER guessed to be 1-based (so ``[1, 1]`` is cell
    ``(1, 1)``, not ``r1c1``). Out-of-range or non-integer arrays are dropped.
    """
    tile = _coerce_tile(value)
    if tile is None:
        return None
    r, c = tile
    if r < 0 or c < 0:
        return None
    if (rows > 0 and r >= rows) or (cols > 0 and c >= cols):
        return None
    _log.debug("finding used the legacy zero-based tile array [%d,%d] (no tile_label)", r, c)
    return tile


def _resolve_tile(item: dict, rows: int, cols: int) -> list[int] | None:
    """The zero-based ``[row, col]`` for a finding item (Phase 25 §17.1).

    Prefers the ``tile_label`` contract (``"r1c1"`` → ``[0, 0]``, self-describing
    so never base-ambiguous); falls back to a legacy zero-based ``tile`` array for
    older/hand-built payloads. Both are bounds-checked against the grid when its
    dimensions are known.
    """
    label = item.get("tile_label")
    if isinstance(label, str) and label.strip():
        return parse_tile_label(label, rows, cols)
    return _coerce_legacy_tile(item.get("tile"), rows, cols)


def _coerce_refs(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float))][:20]
    return []


def _fallback_sheet_id(ref: SheetRef) -> str:
    return f"{Path(ref.source_name).stem}-p{ref.page_index + 1}"


def _validate_finding_item(
    item: Any, ref: SheetRef, rows: int = 0, cols: int = 0
) -> Finding | None:
    """Build a validated :class:`Finding` from one model item, or drop it (None).

    Required: a recognized ``category`` and ``severity`` and a non-empty ``text``.
    A missing/blank ``sheet_id`` falls back to the source stem + page. Quotes are
    kept **verbatim** — a non-empty ``source_quote`` that later fails anchoring is
    the hallucination signal the resolver reports; we never "fix" it here. The
    tile is read from the ``tile_label`` contract, bounds-checked against
    ``rows``/``cols`` when known (Phase 25 §17.1).
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
    quote = item.get("source_quote", "")
    if not isinstance(quote, str):
        quote = ""
    sheet_id = str(item.get("sheet_id", "")).strip() or _fallback_sheet_id(ref)
    # ``anchor_hint`` is optional and only the critique pass emits it ("SHEET" for
    # a sheet-level / absence finding). The digest never asks for it, so a digest
    # item simply leaves it "" — the shared parser stays byte-compatible for
    # digests while carrying the hint through for critique findings.
    anchor_hint = str(item.get("anchor_hint", "")).strip().upper()
    if anchor_hint != "SHEET":
        anchor_hint = ""
    # ``recommended_action`` is optional and tolerant: absent / non-string → "";
    # capped so a runaway paragraph can't bloat the popup or the CSV.
    action = item.get("recommended_action", "")
    if not isinstance(action, str):
        action = ""
    return Finding(
        sheet_id=sheet_id,
        source_name=ref.source_name,
        source_id=ref.source_id,
        page_index=ref.page_index,
        category=category,
        severity=severity,
        text=text.strip(),
        source_quote=quote,
        recommended_action=action.strip()[:300],
        tile=_resolve_tile(item, rows, cols),
        refs=_coerce_refs(item.get("refs")),
        anchor_hint=anchor_hint,
    )


@dataclass
class FindingsParse:
    """The full result of parsing a model response's findings block (§14.2).

    ``prose`` is the sacred prose with any machine block removed — cut at the
    opener of the first findings *attempt*, so a truncated/unclosed block can never
    reach ``combined_text`` (DA-009). ``status`` is one of the ``FINDINGS_*`` parse
    states; only ``PARSED_CLOSED`` / ``PARSED_UNCLOSED`` carry a valid schema (an
    explicit empty list is a valid schema). ``note`` is human telemetry; it never
    marks a sheet failed — the prose digest ships regardless.
    """

    prose: str
    findings: list[Finding]
    status: str
    note: str
    # How many items the parsed ``findings`` array held *before* validation. A
    # ``PARSED_*`` read with ``raw_item_count > 0`` but ``findings == []`` means the
    # model reported issues that all failed validation (e.g. a category outside the
    # enum) — content-bearing, NOT a clean empty result (§14.2 INVALID_ITEMS_DROPPED).
    raw_item_count: int = 0


def parse_findings_detailed(
    raw_text: str, ref: SheetRef, rows: int = 0, cols: int = 0
) -> FindingsParse:
    """Parse the findings block with a full :class:`FindingsParse` (§14.2).

    Extraction uses the **last** fenced block whose body parses to a
    ``{"findings": [...]}`` object (models sometimes emit a corrected second
    block); prose is cut at the **first** findings *presence* (a parseable block
    or a json-labeled ``"findings":`` attempt), so neither a duplicate block nor a
    truncated/unclosed one ever leaks into the prose. When there is no findings
    presence at all the prose is returned **byte-for-byte unchanged** (I-2).
    """
    candidates = scan_structured_blocks(raw_text)
    parsed = [(_tolerant_json_object(c.body), c) for c in candidates]
    findings_blocks = [
        (obj, c) for obj, c in parsed
        if isinstance(obj, dict) and isinstance(obj.get("findings"), list)
    ]
    attempts = [c for c in candidates if c.looks_like_findings]

    # "Presence" = anything we must cut the prose before: a real findings block or
    # a json-labeled findings attempt that will not parse.
    presence_offsets = (
        [c.opening_offset for _, c in findings_blocks]
        + [c.opening_offset for c in attempts]
    )
    if not presence_offsets:
        # No findings attempt whatsoever — plain prose, returned untouched (I-2).
        return FindingsParse(raw_text, [], FINDINGS_ABSENT, "")

    prose = raw_text[: min(presence_offsets)].rstrip()

    if not findings_blocks:
        # A findings attempt was made but nothing parsed — classify why, strip it
        # from the prose, and record typed telemetry. Never contaminates prose.
        c = attempts[0]
        if c.closed:
            status = FINDINGS_MALFORMED_CLOSED
            note = "findings block present but unparseable"
        elif "}" not in c.body:
            status = FINDINGS_TRUNCATED
            note = "findings block truncated (unclosed fence, no complete object)"
        else:
            status = FINDINGS_MALFORMED_UNCLOSED
            note = "findings block present but unparseable (unclosed fence)"
        _log.warning("findings parse: %s (%s)", note, ref.display_label)
        return FindingsParse(prose, [], status, note)

    obj, block = findings_blocks[-1]
    status = FINDINGS_PARSED_CLOSED if block.closed else FINDINGS_PARSED_UNCLOSED
    raw_items = obj.get("findings") or []
    raw_item_count = len(raw_items) if isinstance(raw_items, list) else 0

    findings: list[Finding] = []
    dropped = 0
    capped = False
    for item in raw_items:
        if len(findings) >= MAX_FINDINGS_PER_SHEET:
            capped = True
            break
        finding = _validate_finding_item(item, ref, rows, cols)
        if finding is None:
            dropped += 1
            continue
        findings.append(finding)

    notes: list[str] = []
    if status == FINDINGS_PARSED_UNCLOSED:
        notes.append("recovered from an unclosed (truncated) fence")
    if len(findings_blocks) > 1:
        notes.append(f"multiple findings blocks ({len(findings_blocks)}) — used the last")
    if dropped:
        notes.append(f"dropped {dropped} invalid finding(s)")
    if capped:
        notes.append(f"capped at {MAX_FINDINGS_PER_SHEET}")
    note = "; ".join(notes)
    if note:
        _log.info("findings parse: %s (%s)", note, ref.display_label)
    return FindingsParse(prose, findings, status, note, raw_item_count=raw_item_count)


def parse_findings(
    raw_text: str, ref: SheetRef, rows: int = 0, cols: int = 0
) -> tuple[str, list[Finding], str]:
    """Back-compat wrapper: ``(prose, findings, telemetry_note)`` (§14.2).

    Thin shim over :func:`parse_findings_detailed` for the digest / batch paths
    that only need the prose + findings + note; the critique inspects the richer
    ``status`` to tell a valid empty schema from a parse failure (DA-008).
    """
    r = parse_findings_detailed(raw_text, ref, rows, cols)
    return r.prose, r.findings, r.note


def _rebind_cached_finding(f: Finding, ref: SheetRef) -> Finding:
    """Rebind a cache-loaded finding to the CURRENT run's source identity (§10.3).

    A cache entry is sheet-local model data, not run provenance: its key is
    content-only, so a hit can carry a *former* run's source identity (e.g. a
    different input whose rendered pixels happened to match). We overwrite
    ``source_name`` / ``source_id`` / ``page_index`` with the current ref,
    recompute a *source-derived* fallback ``sheet_id`` (a real model id like
    ``"M-101"`` is preserved — only the ``"{stem}-p{n}"`` fallback is rebuilt),
    and recompute the content ``id`` so two different sources can never share one
    artifact/evidence id (DA-001). ``also_on`` legs are left untouched — they
    intentionally point at *other* sheets and are empty for digest findings.
    """
    old_fallback = f"{Path(f.source_name).stem}-p{int(f.page_index or 0) + 1}"
    was_fallback = f.sheet_id == old_fallback
    f.source_name = ref.source_name
    f.source_id = ref.source_id
    f.page_index = ref.page_index
    if was_fallback:
        f.sheet_id = _fallback_sheet_id(ref)
    f.id = compute_finding_id(
        f.sheet_id, f.category, f.source_quote or f.text, f.source_id
    )
    return f


def findings_from_cache(hit: dict, ref: SheetRef) -> list[Finding]:
    """Reconstruct cached findings for a cache hit, rebound to ``ref`` (§10.3)."""
    raw = hit.get("findings")
    if not isinstance(raw, list):
        return []
    out: list[Finding] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(_rebind_cached_finding(Finding.from_dict(item), ref))
            except Exception:  # noqa: BLE001 - a bad cached row must never sink a run
                continue
    return out


def _scalar(value: Any) -> bool:
    """A claim term/expected is a JSON scalar (number or string), not a container.

    ``bool`` is a JSON-``true``/``false``, not a number the arithmetic auditor
    should treat as ``1``/``0`` — reject it so a stray boolean never becomes a term.
    """
    return isinstance(value, (int, float, str)) and not isinstance(value, bool)


def _validate_claim_item(item: Any, ref: SheetRef | None) -> NumericClaim | None:
    """Build a validated :class:`NumericClaim` from one model item, or drop it.

    Requires a recognized ``kind``, a non-empty ``terms`` list of scalars, and a
    scalar ``expected``. Numbers are kept **raw** (the auditor parses them); the
    emitting sheet's ``ref`` (when known — a per-sheet critique) fills in
    ``source_name`` / ``page_index`` so the claim anchors on that exact sheet.
    """
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind", "")).strip().lower()
    if kind not in CLAIM_KINDS:
        return None
    terms = item.get("terms")
    if not isinstance(terms, list) or not terms or not all(_scalar(t) for t in terms):
        return None
    if "expected" not in item or not _scalar(item.get("expected")):
        return None
    quote = item.get("quote", "")
    if not isinstance(quote, str):
        quote = ""
    sheet_id = str(item.get("sheet_id", "")).strip()
    if not sheet_id and ref is not None:
        sheet_id = _fallback_sheet_id(ref)
    return NumericClaim(
        sheet_id=sheet_id,
        quote=quote,
        kind=kind,
        terms=list(terms),
        expected=item.get("expected"),
        note=str(item.get("note", "")).strip(),
        source_name=ref.source_name if ref is not None else "",
        source_id=ref.source_id if ref is not None else "",
        page_index=ref.page_index if ref is not None else 0,
    )


def parse_numeric_claims(raw_text: str, ref: SheetRef | None = None) -> list[NumericClaim]:
    """Extract the numeric ``claims`` array from a model response (Phase 14).

    Reads the same **last** fenced json block the findings come from (models emit
    ``{"findings": [...], "claims": [...]}``), so it is transport-agnostic and
    tolerant of the block drift :func:`parse_findings` already handles. Invalid
    items are dropped and the list is capped at :data:`MAX_CLAIMS_PER_SHEET`. A
    response with no claims array yields ``[]``. Never raises — claims are additive
    telemetry for the deterministic auditor, never load-bearing for the digest.
    """
    last_obj: dict | None = None
    for c in scan_structured_blocks(raw_text):
        obj = _tolerant_json_object(c.body)
        if isinstance(obj, dict) and isinstance(obj.get("claims"), list):
            last_obj = obj
    if last_obj is None:
        return []
    claims: list[NumericClaim] = []
    for item in last_obj.get("claims") or []:
        if len(claims) >= MAX_CLAIMS_PER_SHEET:
            break
        claim = _validate_claim_item(item, ref)
        if claim is not None:
            claims.append(claim)
    return claims


def claims_from_cache(hit: dict, ref: SheetRef | None = None) -> list[NumericClaim]:
    """Reconstruct cached numeric claims, rebound to ``ref`` when given (§10.3).

    Like :func:`findings_from_cache`, a critique cache hit is content-keyed, so
    its claims may carry a former run's source identity; when the current
    ``ref`` is supplied the emitting-sheet fields are rebound to it so the
    arithmetic auditor resolves the claim against the right sheet.
    """
    raw = hit.get("claims")
    if not isinstance(raw, list):
        return []
    out: list[NumericClaim] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                claim = NumericClaim.from_dict(item)
            except Exception:  # noqa: BLE001 - a bad cached row must never sink a run
                continue
            if ref is not None:
                # Rebuild a source-derived fallback sheet_id before overwriting
                # the source fields (mirrors _rebind_cached_finding): a claim
                # whose sheet_id was "{old_stem}-pN" would otherwise show the old
                # source's label in the CSV/report/markup, since audit_arithmetic
                # prefers claim.sheet_id. A real model id is preserved.
                old_fallback = f"{Path(claim.source_name).stem}-p{int(claim.page_index or 0) + 1}"
                if claim.sheet_id == old_fallback:
                    claim.sheet_id = _fallback_sheet_id(ref)
                claim.source_name = ref.source_name
                claim.source_id = ref.source_id
                claim.page_index = ref.page_index
            out.append(claim)
    return out


def sheet_digest_from_cache_entry(entry: dict, ref: SheetRef) -> SheetDigest:
    """Build a cached :class:`SheetDigest` from a digest-cache ``entry`` + ``ref``.

    Used by the pipeline's level-1 (pre-render) cache hit — the sheet was never
    rasterized, so there are no image sizes to estimate from and
    ``image_token_estimate`` is 0 (nothing was sent). Otherwise byte-for-byte the
    same cached shape :func:`digest_sheet` returns on a level-2 hit (``cached``
    True, original token counts, findings rehydrated), so downstream can't tell
    which cache tier served it.
    """
    return SheetDigest(
        ref=ref,
        text=entry.get("text", ""),
        input_tokens=int(entry.get("input_tokens", 0) or 0),
        output_tokens=int(entry.get("output_tokens", 0) or 0),
        image_token_estimate=0,
        stop_reason=entry.get("stop_reason"),
        error=None,
        cached=True,
        findings=findings_from_cache(entry, ref),
    )


def cache_entry_from_digest(sd: SheetDigest) -> dict:
    """The digest-cache entry for a computed/served :class:`SheetDigest`.

    Mirrors the dict :func:`digest_sheet` writes on a fresh digest, so the
    pipeline can store a miss's result under its level-1 key too (store-under-both
    continuity). ``created_ts`` is stamped here; callers persist it verbatim.
    """
    return {
        "text": sd.text,
        "input_tokens": int(sd.input_tokens or 0),
        "output_tokens": int(sd.output_tokens or 0),
        "stop_reason": sd.stop_reason,
        "findings": [f.to_dict() for f in (sd.findings or [])],
        "created_ts": time.time(),
    }


def digest_sheet(
    sheet: RenderedSheet,
    *,
    client: Any = None,
    model: str = REVIEW_MODEL_DEFAULT,
    max_tokens: int = DEFAULT_DIGEST_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_DIGEST_EFFORT,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    cache: Any = None,
    focus: str | None = None,
    specs_text: str | None = None,
) -> SheetDigest:
    """Run a single vision request for one sheet and return its text digest.

    ``client`` is injectable for tests; when ``None`` the shared Anthropic client
    factory is used. Any API/parse failure is captured on ``SheetDigest.error``
    (never raised) so a set keeps processing the remaining sheets — the message
    is sanitized by :func:`_clean_error` so an upstream HTML error page never
    reaches the UI. A *transient* failure (:func:`_is_transient_error`) is
    re-attempted up to ``max_retries`` times with exponential backoff (``sleep``
    is injectable so tests don't wait); a permanent failure returns immediately.

    ``cache`` (a :class:`~drawing_analyzer.digest_cache.DigestCache`, or ``None`` to
    disable) is consulted before the API call and written only on a successful,
    non-empty digest — so an unchanged sheet on a re-run is served from cache
    with ``cached=True`` and no token cost. The key folds in the rendered images,
    the model, the prompt fingerprint, and the output-shaping params.

    ``focus`` (an optional per-run operator focus — see :func:`normalize_focus`)
    asks for one extra ``**Focus findings**`` section after the standard digest.
    It is folded into the cache key, so a focused run never reuses a digest
    produced without (or under a different) focus, while a no-focus run keeps
    hitting pre-existing cache entries.

    ``specs_text`` (optional uploaded project specifications — see
    :func:`normalize_specs_text`) grounds the read against ground-truth spec
    text; conflicts fold into the ordinary findings block, not a new section.
    Folded into the cache key like ``focus``, and prompt-cached across sheets
    (see :func:`digest_system_prompt`).
    """
    focus = normalize_focus(focus)
    specs_text = normalize_specs_text(specs_text)
    image_est = estimate_image_tokens_total(sheet.image_sizes, model=model)

    cache_key: str | None = None
    if cache is not None:
        cache_key = digest_cache_key(
            sheet,
            model=model,
            prompt_version=DIGEST_PROMPT_VERSION,
            max_tokens=max_tokens,
            effort=effort,
            use_thinking=use_thinking,
            focus=focus_cache_fragment(focus),
            specs=specs_cache_fragment(specs_text),
            sheet_text=sheet.sheet_text,
        )
        hit = cache.get(cache_key)
        if hit is not None:
            return SheetDigest(
                ref=sheet.ref,
                text=hit.get("text", ""),
                input_tokens=int(hit.get("input_tokens", 0) or 0),
                output_tokens=int(hit.get("output_tokens", 0) or 0),
                image_token_estimate=image_est,
                stop_reason=hit.get("stop_reason"),
                error=None,
                cached=True,
                findings=findings_from_cache(hit, sheet.ref),
            )

    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    kwargs = build_digest_request_params(
        build_user_content(sheet),
        model=model,
        max_tokens=max_tokens,
        use_thinking=use_thinking,
        effort=effort,
        focus=focus,
        specs_text=specs_text,
    )

    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - report, don't sink the whole set
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return SheetDigest(
                ref=sheet.ref,
                text="",
                image_token_estimate=image_est,
                error=_clean_error(exc),
            )

    raw_text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    _usage = _get(resp, "usage")
    cache_read_tok = int(_get(_usage, "cache_read_input_tokens", 0) or 0)
    cache_write_tok = int(_get(_usage, "cache_creation_input_tokens", 0) or 0)
    stop = _get(resp, "stop_reason")

    error: str | None = None
    if not raw_text:
        error = f"empty digest (stop_reason={stop!r})"

    # Split the findings block off the prose. ``text`` is the prose only, so
    # ``combined_text`` never sees the JSON (I-2); ``findings`` and the telemetry
    # note ride separately. A parse problem never marks the sheet failed.
    text, findings, findings_note = parse_findings(
        raw_text, sheet.ref, sheet.rows, sheet.cols
    )

    # Cache only a real, successful digest — never an empty/error result (those
    # are transient and a re-run should re-attempt them).
    if cache is not None and cache_key is not None and error is None and raw_text:
        cache.put(
            cache_key,
            {
                "text": text,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "stop_reason": stop,
                "findings": [f.to_dict() for f in findings],
                "created_ts": time.time(),
            },
        )

    return SheetDigest(
        ref=sheet.ref,
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        image_token_estimate=image_est,
        stop_reason=stop,
        error=error,
        findings=findings,
        findings_note=findings_note,
        cache_read_tokens=cache_read_tok,
        cache_write_tokens=cache_write_tok,
    )
