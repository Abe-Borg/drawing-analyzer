"""Set identity: what IS this drawing set? (Phase A, universal reviewer §20.1)

The "which specialist am I?" pass. One **text-only** call reads a budgeted
corpus of every sheet's digest head plus the early sheets' verbatim text layers
(cover sheet / index / general notes live there) and returns a structured
:class:`~drawing_analyzer.models.SetIdentity`: the disciplines present, a sheet
→ discipline map, where the project sits (jurisdiction / country / region), its
language and units, and — most importantly — the codes the set says it adopts,
each with a verbatim evidence quote.

Containment contract: after parsing, the deterministic
:func:`~drawing_analyzer.citation_check.harvest_code_editions` regex hits are
**unioned** into ``adopted_codes`` (``origin="regex"``), so a code edition the
text plainly states can never be hallucinated away — and, conversely, the model
extraction reaches the worldwide codes the US-centric regex whitelist can never
match (Eurocodes, BS, DIN, AS/NZS, GB, …).

The identity is **advisory**: every consumer (the review planner, the citation
check, cross-sheet QC) accepts ``SetIdentity | None`` and behaves exactly as
before when it is ``None``. A misdetection can steer emphasis but can never
gate or suppress a finding.

Like ``synthesis.py`` this module reuses the SDK-shape-tolerant parsing, error
sanitization, and transient retry from ``digest.py`` — an identity failure
degrades gracefully (I-3) and never sinks the run. PDF-engine-free (I-5).
"""
from __future__ import annotations

import hashlib
import os
import re
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
    _tolerant_json_object,
    scan_structured_blocks,
)
from .models import AdoptedCode, SetIdentity, source_page_key

# Extraction/classification, not deep reasoning — cheaper than synthesis's "high".
DEFAULT_IDENTITY_MAX_TOKENS = 4_000
DEFAULT_IDENTITY_EFFORT = "medium"

# Corpus budget (chars). Every sheet contributes its digest head (the set-wide
# discipline map); the first sheets — where cover sheets, sheet indexes, and
# general notes overwhelmingly live — additionally contribute a deep digest
# slice and a verbatim text-layer slice; and EVERY sheet contributes verbatim
# ±window slices around each code-edition mention, so an adopted-codes block on
# sheet 47 still reaches the prompt. Overflow drops content deterministically
# (later sheets first) and is counted, never silent (loss-aware, cf. DA-028).
_HEADER_SLICE = 400
_FULL_SLICE_SHEETS = 8
_FULL_DIGEST_SLICE = 2_000
_FULL_TEXT_SLICE = 4_000          # matches cross_qc's per-sheet text budget
_EDITION_WINDOW = 120             # chars either side of an edition mention
_MAX_WINDOWS_PER_SHEET = 3
_TOTAL_BUDGET = 200_000

# Host-side caps on the parsed payload — the model's output is never trusted
# to be bounded (§17-style hygiene). Oversize entries are trimmed/dropped.
_MAX_DISCIPLINES = 12
_MAX_SHEET_DISCIPLINES = 500
_MAX_ADOPTED_CODES = 40
_MAX_EVIDENCE = 5
_QUOTE_CAP = 200
_NOTES_CAP = 400

_CONFIDENCE_LEVELS = ("high", "medium", "low")


def default_identity_model() -> str:
    """Model for the identity pass — the review model by default, overridable
    via ``DRAWING_ANALYZER_IDENTITY_MODEL``."""
    override = os.environ.get("DRAWING_ANALYZER_IDENTITY_MODEL")
    if override and override.strip():
        return override.strip()
    return REVIEW_MODEL_DEFAULT


IDENTITY_SYSTEM_PROMPT = """\
You are the intake specialist for a worldwide construction-drawing review \
service. Drawing sets arrive from ANY discipline (architectural, structural, \
mechanical, electrical, plumbing, fire protection, civil, telecom, process, \
marine, …), ANY jurisdiction, and ANY language. You are given a budgeted text \
corpus for one set: a short digest head for every sheet, deeper digest + \
verbatim text-layer slices for the earliest sheets (where cover sheets, sheet \
indexes, and general notes usually live), and verbatim windows around every \
code-edition mention found anywhere in the set. Identify what this set IS.

Rules:
- Report only what the corpus supports. NEVER invent a code, edition, \
jurisdiction, or discipline; a field you cannot support is the empty string "".
- For every adopted code you report, carry a short VERBATIM quote from the \
corpus as evidence and name the sheet it came from. Codes may be from any \
country's system (NFPA, IBC, Eurocode/EN, BS, DIN, AS/NZS, SANS, GB, NBC, …).
- "Adopted" means the set states it governs the work (general notes, code \
summary, title block) — not merely a passing reference on a detail.
- disciplines are lower-case English discipline names (e.g. "fire protection", \
"electrical") even when the set is in another language; language is the set's \
primary language as a lower-case tag (e.g. "en", "de", "es"); units is one of \
"imperial", "metric", or "mixed".
- sheet_disciplines maps each sheet id you can classify to one discipline; \
skip sheets you cannot classify.
- confidence is your overall detection confidence: "high", "medium", or "low".

Output a SINGLE fenced code block labeled json and nothing after it, containing \
exactly: {"disciplines": [...], "sheet_disciplines": [{"sheet_id": "...", \
"discipline": "..."}], "project_type": "...", "set_type": "...", \
"jurisdiction": "...", "country": "...", "region": "...", "language": "...", \
"units": "...", "adopted_codes": [{"code": "...", "edition": "...", \
"amendment_note": "...", "quote": "...", "source_sheet": "..."}], \
"confidence": "...", "evidence": ["..."], "notes": "..."}"""


_IDENTITY_TASK_INSTRUCTION = (
    "Above is the corpus for the set. Identify the set per your instructions "
    "and answer in the single required json block."
)

# Content hash of the static prompt pieces: an edit re-keys the identity cache
# automatically (I-6). Dynamic user text is content-addressed separately.
IDENTITY_PROMPT_VERSION = hashlib.sha256(
    (IDENTITY_SYSTEM_PROMPT + "\x00" + _IDENTITY_TASK_INSTRUCTION).encode("utf-8")
).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Corpus assembly (pure; deterministic — I-7)
# --------------------------------------------------------------------------- #


@dataclass
class IdentityBudget:
    """Loss accounting for the corpus assembly (never silent truncation)."""

    total_chars: int = 0
    included_chars: int = 0
    omitted_chars: int = 0

    @property
    def degraded(self) -> bool:
        return self.omitted_chars > 0


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


# Window-selection pattern for NON-US code designations. Deliberately broader
# and looser than ``citation_check._CODE_TOKEN`` (which stays conservative — it
# CREATES ``adopted_codes`` entries; this only chooses which verbatim snippets
# ride the identity prompt as context, capped per sheet, so a false positive
# costs a few tokens, while a miss can hide the governing code of a non-US set
# whose adopted-codes note sits past the deep-sliced early sheets). Covers the
# common national/international families: EN and its national adoptions
# (DIN/BS/NF/UNE/SS/NEN/PN EN, optionally EN ISO), ISO/IEC, bare DIN/BS,
# AS/NZS (and bare AS/NZS), SANS, GB(/T), JIS, IS, SNiP/SP, NBC, Eurocode.
# Year adjacency is optional — "designed to BS 9251" is evidence even
# unyeared, and EN sets write editions colon-joined ("EN 12845:2020").
_INTL_CODE_WINDOW_RE = re.compile(
    r"\b(?:"
    r"(?:DIN|BS|NF|UNE|SS|SFS|NEN|PN|CSN|ONORM|OENORM)[ -]?EN(?:[ -]?ISO)?[ ]?\d{2,6}"
    r"|EN(?:[ -]?ISO)?[ ]?\d{3,6}"
    r"|ISO[ ]?\d{3,6}"
    r"|IEC[ ]?\d{3,6}"
    r"|DIN[ ]?\d{3,6}"
    r"|BS[ ]?\d{3,6}"
    r"|AS[ ]?/[ ]?NZS[ ]?\d{3,6}"
    r"|AS[ ]?\d{4,6}"
    r"|NZS[ ]?\d{3,6}"
    r"|SANS[ ]?\d{3,6}"
    r"|GB(?:[ ]?/[ ]?T)?[ ]?\d{3,6}"
    r"|JIS[ ]?[A-Z][ ]?\d{3,6}"
    r"|IS[ ]?\d{3,6}"
    r"|SNIP[ ]?[\d.-]{2,12}"
    r"|SP[ ]?\d{1,4}\.\d{5}"
    r"|NBC[ ]?(?:19|20)\d{2}"
    r"|EUROCODE[ ]?\d?"
    r")\b(?:[:\s,()–-]{0,3}(?:19|20)\d{2})?",
    re.IGNORECASE,
)


def _edition_windows(sheet_text: str) -> list[str]:
    """Verbatim ±window slices around each code-edition mention on one sheet.

    Two selectors feed the windows: the conservative US code+year pattern the
    citation check harvests with, and the broader international designation
    pattern above — so a Eurocode/BS/DIN/AS-NZS/GB adopted-codes note reaches
    the prompt verbatim even when it sits on a late sheet (the finding a
    US-only selector would silently miss). Overlaps merge; capped per sheet.
    """
    from .citation_check import _EDITION_RE

    text = sheet_text or ""
    spans = sorted(
        {m.span() for m in _EDITION_RE.finditer(text)}
        | {m.span() for m in _INTL_CODE_WINDOW_RE.finditer(text)}
    )
    out: list[str] = []
    last_end = -1
    for start, end in spans:
        if len(out) >= _MAX_WINDOWS_PER_SHEET:
            break
        w_start = max(0, start - _EDITION_WINDOW)
        w_end = min(len(text), end + _EDITION_WINDOW)
        if w_start < last_end:  # overlapping mention → already covered
            continue
        out.append(_one_line(text[w_start:w_end]))
        last_end = w_end
    return out


def _sheet_block(
    index: int, total: int, sd: SheetDigest, geom: Any, *, deep: bool
) -> str:
    """One sheet's corpus block. ``deep`` sheets carry digest + text-layer slices."""
    lines = [f"===== Sheet {index}/{total}: {sd.ref.display_label} ====="]
    digest_text = (sd.text or "").strip()
    if digest_text:
        cap = _FULL_DIGEST_SLICE if deep else _HEADER_SLICE
        lines.append(digest_text[:cap])
    elif sd.error:
        lines.append(f"[digest failed: {_one_line(sd.error)[:120]}]")
    else:
        lines.append("[no digest text]")
    sheet_text = (getattr(geom, "sheet_text", "") or "") if geom is not None else ""
    if deep and sheet_text.strip():
        lines.append(f"TEXT LAYER (verbatim, first {_FULL_TEXT_SLICE} chars):")
        lines.append(sheet_text[:_FULL_TEXT_SLICE])
    windows = _edition_windows(sheet_text)
    if windows:
        lines.append("EDITION MENTIONS (verbatim windows):")
        lines.extend(f'- "{w}"' for w in windows)
    return "\n".join(lines)


def build_identity_user_text(
    sheet_digests: list[SheetDigest], geometries: list[Any]
) -> tuple[str, IdentityBudget]:
    """Assemble the identity corpus: page-ordered, budgeted, loss-aware.

    Every sheet gets a block; the first :data:`_FULL_SLICE_SHEETS` get the deep
    slices. When the running total would exceed :data:`_TOTAL_BUDGET`, a later
    sheet's block falls back to its header-only form, and if even that does not
    fit it is omitted — with every dropped character counted in the returned
    :class:`IdentityBudget` (deterministic: page order, later sheets lose first).
    """
    from .citation_check import harvest_code_editions

    geom_by_key = {source_page_key(g.ref): g for g in geometries or []}
    total = len(sheet_digests)
    budget = IdentityBudget()
    parts: list[str] = [f"DRAWING SET — {total} sheet(s). Corpus follows.", ""]
    used = sum(len(p) for p in parts)
    for i, sd in enumerate(sheet_digests, start=1):
        geom = geom_by_key.get(source_page_key(sd.ref))
        block = _sheet_block(i, total, sd, geom, deep=(i <= _FULL_SLICE_SHEETS))
        budget.total_chars += len(block)
        if used + len(block) <= _TOTAL_BUDGET:
            parts.append(block)
            parts.append("")
            used += len(block) + 1
            budget.included_chars += len(block)
            continue
        # Over budget: try the header-only form before dropping the sheet.
        fallback = _sheet_block(i, total, sd, geom=None, deep=False)
        if used + len(fallback) <= _TOTAL_BUDGET:
            parts.append(fallback)
            parts.append("")
            used += len(fallback) + 1
            budget.included_chars += len(fallback)
            budget.omitted_chars += len(block) - len(fallback)
        else:
            budget.omitted_chars += len(block)
    hints = harvest_code_editions(geometries or [])
    if hints:
        parts.append("REGEX-HARVESTED EDITION HINTS: " + "; ".join(hints))
        parts.append("")
    parts.append(_IDENTITY_TASK_INSTRUCTION)
    return "\n".join(parts), budget


# --------------------------------------------------------------------------- #
# Payload sanitation + regex union (host-side; the model's output is bounded here)
# --------------------------------------------------------------------------- #


def _cap(value: Any, limit: int) -> str:
    return _one_line(str(value or ""))[:limit]


def _sanitize_payload(obj: dict) -> dict:
    """Bound every field of the model's identity payload before it becomes data."""
    disciplines = [
        _cap(d, 40).lower() for d in (obj.get("disciplines") or []) if _cap(d, 40)
    ]
    pairs = []
    for entry in (obj.get("sheet_disciplines") or [])[:_MAX_SHEET_DISCIPLINES]:
        if isinstance(entry, dict):
            sheet, disc = entry.get("sheet_id", ""), entry.get("discipline", "")
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            sheet, disc = entry[0], entry[1]
        else:
            continue
        sheet, disc = _cap(sheet, 60), _cap(disc, 40).lower()
        if sheet and disc:
            pairs.append([sheet, disc])
    codes = []
    for entry in (obj.get("adopted_codes") or [])[:_MAX_ADOPTED_CODES]:
        if not isinstance(entry, dict):
            continue
        code = _cap(entry.get("code"), 60)
        if not code:
            continue
        codes.append({
            "code": code,
            "edition": _cap(entry.get("edition"), 40),
            "amendment_note": _cap(entry.get("amendment_note"), 120),
            "quote": _cap(entry.get("quote"), _QUOTE_CAP),
            "source_sheet": _cap(entry.get("source_sheet"), 60),
            "origin": "model",
        })
    confidence = _cap(obj.get("confidence"), 10).lower()
    if confidence not in _CONFIDENCE_LEVELS:
        confidence = ""
    return {
        "disciplines": sorted(set(disciplines))[:_MAX_DISCIPLINES],
        "sheet_disciplines": pairs,
        "project_type": _cap(obj.get("project_type"), 120),
        "set_type": _cap(obj.get("set_type"), 80),
        "jurisdiction": _cap(obj.get("jurisdiction"), 160),
        "country": _cap(obj.get("country"), 80),
        "region": _cap(obj.get("region"), 80),
        "language": _cap(obj.get("language"), 40).lower(),
        "units": _cap(obj.get("units"), 20).lower(),
        "adopted_codes": codes,
        "confidence": confidence,
        "evidence": [
            _cap(e, _QUOTE_CAP) for e in (obj.get("evidence") or [])[:_MAX_EVIDENCE]
            if _cap(e, _QUOTE_CAP)
        ],
        "notes": _cap(obj.get("notes"), _NOTES_CAP),
    }


def parse_identity_text(raw_text: str) -> SetIdentity | None:
    """Parse the model's reply into a bounded :class:`SetIdentity` (or ``None``).

    Tolerant: takes the LAST fenced block that parses to a JSON object carrying
    at least one known identity key (models sometimes emit prose first).
    """
    known = (
        "disciplines", "sheet_disciplines", "adopted_codes", "jurisdiction",
        "country", "language", "units", "project_type", "set_type",
    )
    for block in reversed(scan_structured_blocks(raw_text or "")):
        obj = _tolerant_json_object(block.body)
        if obj is not None and any(k in obj for k in known):
            return SetIdentity.from_dict(_sanitize_payload(obj))
    return None


def _norm_code_display(display: str) -> str:
    return " ".join(display.split()).upper()


def union_regex_editions(identity: SetIdentity, geometries: list[Any]) -> SetIdentity:
    """Union the deterministic regex edition harvest into ``adopted_codes``.

    The model's entries win on a ``CODE EDITION`` collision (they carry quotes
    and amendment notes); a regex-only hit is appended with ``origin="regex"``
    so the containment backstop is visible in the record. Returns a new,
    re-sorted :class:`SetIdentity` (frozen dataclasses are never mutated).
    """
    from .citation_check import harvest_code_editions

    have = {_norm_code_display(c.display) for c in identity.adopted_codes}
    extras = []
    for claim in harvest_code_editions(geometries or []):
        if _norm_code_display(claim) in have:
            continue
        code, _, year = claim.rpartition(" ")
        if not code:  # a bare token with no year — keep it whole as the code
            code, year = claim, ""
        extras.append(AdoptedCode(code=code, edition=year, origin="regex"))
    if not extras:
        return identity
    data = identity.to_dict()
    data["adopted_codes"] = [c.to_dict() for c in identity.adopted_codes] + [
        c.to_dict() for c in extras
    ]
    return SetIdentity.from_dict(data)


# --------------------------------------------------------------------------- #
# The stage call
# --------------------------------------------------------------------------- #


@dataclass
class IdentityResult:
    """Result of the set-identity pass."""

    identity: SetIdentity | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    error: str | None = None
    omitted_chars: int = 0          # corpus chars dropped by the budget (loss-aware)
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and self.identity is not None


def identify_set(
    sheet_digests: list[SheetDigest],
    geometries: list[Any],
    *,
    client: Any = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_IDENTITY_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_IDENTITY_EFFORT,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    cache: Any = None,
) -> IdentityResult:
    """Identify the set in one text-only call (never raises — I-3).

    With a ``cache``, the finished identity is stored content-addressed on the
    exact corpus + request params (:func:`digest_cache.identity_cache_key`), so
    a warm re-run serves it without an API call — which also keeps the
    downstream review plan (and therefore the critique ``profiles_key``) stable
    across warm runs.
    """
    model = model or default_identity_model()
    ok_count = sum(1 for sd in sheet_digests if sd.ok)
    if not sheet_digests or ok_count == 0:
        return IdentityResult(model_used=model, error="no readable sheets to identify")

    user_text, budget = build_identity_user_text(sheet_digests, geometries)

    cache_key = None
    if cache is not None:
        from .digest_cache import identity_cache_key

        cache_key = identity_cache_key(
            hashlib.sha256(user_text.encode("utf-8")).hexdigest(),
            model=model,
            prompt_version=IDENTITY_PROMPT_VERSION,
            max_tokens=max_tokens,
            effort=effort,
            use_thinking=use_thinking,
        )
        entry = cache.get(cache_key)
        if entry is not None and isinstance(entry.get("identity"), dict):
            return IdentityResult(
                identity=SetIdentity.from_dict(entry["identity"]),
                model_used=str(entry.get("model", model)),
                omitted_chars=budget.omitted_chars,
                cached=True,
            )

    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": IDENTITY_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
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
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return IdentityResult(
                model_used=model, error=_clean_error(exc),
                omitted_chars=budget.omitted_chars,
            )

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    identity = parse_identity_text(text)
    if identity is None:
        return IdentityResult(
            input_tokens=in_tok, output_tokens=out_tok, model_used=model,
            error="identity reply carried no parseable identity block",
            omitted_chars=budget.omitted_chars,
        )
    identity = union_regex_editions(identity, geometries)
    result = IdentityResult(
        identity=identity, input_tokens=in_tok, output_tokens=out_tok,
        model_used=model, omitted_chars=budget.omitted_chars,
    )
    if cache is not None and cache_key is not None:
        # Store the finished (sanitized + regex-unioned) record — what a warm
        # run must reproduce byte-for-byte.
        cache.put(cache_key, {
            "identity": identity.to_dict(),
            "model": model,
            "prompt_version": IDENTITY_PROMPT_VERSION,
        })
    return result
