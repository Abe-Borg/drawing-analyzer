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
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .core.api_config import (
    REVIEW_MODEL_DEFAULT,
    model_supports_adaptive_thinking,
    model_supports_effort,
)
from .core.tokenizer import estimate_image_tokens_total
from .digest_cache import digest_cache_key
from .models import ImageTile, RenderedSheet, SheetRef

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
You are a senior MEP (mechanical / plumbing / fire-protection) engineer reading \
California K-12 / community-college DSA construction drawings. Your job is to \
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
block (discipline = Mechanical / Plumbing / Fire Protection / Plumbing-Fire / \
Controls / etc.). If a field is illegible, say so rather than guessing.
- **Scope / systems shown** on this sheet.
- **Equipment & schedules**: transcribe schedule rows that matter — tag/mark, \
type, capacity/size, model or basis-of-design, and any noted standard. Keep tags \
verbatim (e.g. `VAV-3`, `WH-1`, `FP-2`).
- **Plan content**: spaces/rooms shown and what equipment, routing, or risers \
serve them; use the sheet's own column grid bubbles / match-lines / detail \
callouts as the spatial reference frame where possible.
- **Key dimensions, elevations, clearances, slopes, pipe/duct sizes** that a \
spec would need to be consistent with.
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

# Folded into the digest cache key so any edit to the prompt, the task
# instruction, or the text-layer framing re-digests rather than serving a cached
# read produced under the old prompt.
DIGEST_PROMPT_VERSION = hashlib.sha256(
    (
        DIGEST_SYSTEM_PROMPT
        + "\x00"
        + _DIGEST_TASK_INSTRUCTION
        + "\x00"
        + _SHEET_TEXT_LAYER_HEADER
        + "\x00"
        + _SHEET_TEXT_LAYER_RASTER_PLACEHOLDER
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


def digest_system_prompt(focus: str | None = None) -> str:
    """The effective system prompt: the standard digest prompt, plus the focus
    addendum when a per-run focus is set."""
    focus = normalize_focus(focus)
    if focus is None:
        return DIGEST_SYSTEM_PROMPT
    return DIGEST_SYSTEM_PROMPT + build_focus_addendum(focus)


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
    sheet: RenderedSheet, image_block: "Callable[[ImageTile], dict]"
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

    The sheet's verbatim text layer is inserted right after the framing text and
    before any image, so both transports carry the exact-strings grounding the
    resolution drop relies on (a raster sheet gets the "rely on the images"
    placeholder instead).
    """
    blocks: list[dict] = [
        _text_block(
            f"You are given ONE construction drawing sheet "
            f"({sheet.ref.display_label}), rendered as a low-resolution overview "
            f"followed by a {sheet.rows}x{sheet.cols} grid of overlapping "
            f"high-resolution tiles. Read them together as a single sheet."
        ),
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
    blocks.append(_text_block(_DIGEST_TASK_INSTRUCTION))
    return blocks


def build_user_content(sheet: RenderedSheet) -> list[dict]:
    """Inline-base64 user content for one sheet (the real-time digest transport).

    Thin wrapper over :func:`build_user_content_blocks` that inlines each image
    as base64. The batch path uses the same builder with a ``file_id`` image
    block (see :mod:`drawing_analyzer.file_upload`).
    """
    return build_user_content_blocks(sheet, lambda t: _image_block(t.png_bytes))


def build_digest_request_params(
    content: list[dict],
    *,
    model: str = REVIEW_MODEL_DEFAULT,
    max_tokens: int = DEFAULT_DIGEST_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_DIGEST_EFFORT,
    focus: str | None = None,
) -> dict[str, Any]:
    """Build the Messages-API request body for one sheet digest.

    The single source of truth for the digest request shape — used by both the
    real-time path (:func:`digest_sheet`) and the batch path
    (:mod:`drawing_analyzer.batch_digest`), so the two can't drift on model /
    thinking / effort. ``thinking`` and ``output_config`` are attached only when
    the model supports them (Opus 4.8 supports both; an unknown override
    silently omits them, never producing an API-rejected request). ``focus``
    (an optional per-run operator focus) rides only on the system prompt, so
    the user content — including the batch path's uploaded images — is
    identical with or without it.
    """
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": digest_system_prompt(focus),
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
    """
    focus = normalize_focus(focus)
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

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    stop = _get(resp, "stop_reason")

    error: str | None = None
    if not text:
        error = f"empty digest (stop_reason={stop!r})"

    # Cache only a real, successful digest — never an empty/error result (those
    # are transient and a re-run should re-attempt them).
    if cache is not None and cache_key is not None and error is None and text:
        cache.put(
            cache_key,
            {
                "text": text,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "stop_reason": stop,
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
    )
