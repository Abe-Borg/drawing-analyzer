"""Citation check (Phase 15) — verify cited code sections with server-side web search.

Findings often carry code refs ("NFPA 13 §19.2.3.2.5", "Table 13.2.1"). Those
citations have a failure mode of their own: a drawing citing **2016-era numbering
under a 2019 basis** (the prototype found exactly that — Table 13.2.1 became
§4.3.1.7 in the 2019 renumbering). The drawing set can't validate its own
citations, so this pass asks the model to check each **unique** citation using the
API's server-side **web search tool**: does this section — in the edition the set
adopts *and* in the current edition — actually support the finding citing it?

The verdict is informational: ``CHECKED_MISMATCH`` downgrades nothing
automatically (sometimes the stale citation *is* the finding); it is appended to
the markup popup and the report for the engineer. Failures degrade to
``UNCHECKED`` — the run never dies (I-3).

The set's **adopted editions** are harvested offline from the sheet text layers
(general-notes sheets state them: "NFPA 13, 2016 EDITION") and included in the
prompt so the model can judge both the adopted and the current edition.

Tool type: ``web_search_20260209`` — the current server-side web-search variant
for Opus 4.8 (verified against the API docs at implementation time; the basic
``web_search_20250305`` serves older models). Overridable via
``DRAWING_ANALYZER_WEB_SEARCH_TOOL_TYPE`` so an API rename never needs a code
change. Server-tool turns can stop with ``pause_turn`` (the server-side loop hit
its iteration cap); the call is resumed a bounded number of times.

PDF-engine-free (I-5); real-time only (citation checks are few and interactive —
they don't batch).
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Iterable

from .core.api_config import REVIEW_MODEL_DEFAULT
from .diagnostics import get_logger
from .digest import (
    _FENCE_RE,
    _clean_error,
    _get,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    _tolerant_json_object,
)
from .models import Citation, Finding

_log = get_logger()

DEFAULT_CITATION_MAX_TOKENS = 4_000
DEFAULT_CITATION_MAX_RETRIES = 2
# The server-side loop can stop with pause_turn; resume at most this many times.
_MAX_PAUSE_RESUMES = 3
# Bound the web searches one citation check may run.
_WEB_SEARCH_MAX_USES = 5
# Bounded concurrency — citation checks are few but each runs server-side searches.
_MAX_WORKERS = 4

_DEFAULT_WEB_SEARCH_TOOL_TYPE = "web_search_20260209"


def citation_model() -> str:
    """The citation-check model (``DRAWING_ANALYZER_CITATION_MODEL``, else Opus)."""
    return os.environ.get("DRAWING_ANALYZER_CITATION_MODEL") or REVIEW_MODEL_DEFAULT


def web_search_tool() -> dict:
    """The server-side web-search tool definition for the citation call."""
    tool_type = (
        os.environ.get("DRAWING_ANALYZER_WEB_SEARCH_TOOL_TYPE")
        or _DEFAULT_WEB_SEARCH_TOOL_TYPE
    )
    return {"type": tool_type, "name": "web_search", "max_uses": _WEB_SEARCH_MAX_USES}


# --------------------------------------------------------------------------- #
# Edition harvest (offline, from the sheet text layers)
# --------------------------------------------------------------------------- #

# A code/standard token adjacent to a 4-digit year: "NFPA 13, 2016", "NFPA 13-2019",
# "2022 CBC", "IBC 2021 EDITION". Both orders are matched; the harvested claim is
# normalized to "<CODE> <YEAR>".
_CODE_TOKEN = r"(?:NFPA\s*\d+[A-Z]?|CBC|CFC|CMC|CPC|CEC|IBC|IFC|IMC|IPC|UPC|UMC|ASCE\s*\d+|ASME\s*[A-Z]?[\d.]+|UL\s*\d+|FM\s*\d+)"
_YEAR = r"(?:19|20)\d{2}"
_EDITION_RE = re.compile(
    rf"\b(?P<code>{_CODE_TOKEN})[\s,()–-]{{0,4}}(?P<year>{_YEAR})\b"
    rf"|\b(?P<year2>{_YEAR})[\s,()–-]{{0,4}}(?P<code2>{_CODE_TOKEN})\b",
    re.IGNORECASE,
)


def harvest_code_editions(geometries: Iterable[Any]) -> list[str]:
    """The set's adopted code-edition claims, harvested from the text layers.

    Returns deterministic, de-duplicated ``"<CODE> <YEAR>"`` strings (e.g.
    ``"NFPA 13 2016"``) in first-seen order. Empty when no sheet states an
    edition — the citation prompt then says the basis is unknown.
    """
    out: list[str] = []
    seen: set[str] = set()
    for geom in geometries:
        text = getattr(geom, "sheet_text", "") or ""
        for m in _EDITION_RE.finditer(text):
            code = re.sub(r"\s+", " ", (m.group("code") or m.group("code2") or "").upper()).strip()
            year = m.group("year") or m.group("year2") or ""
            claim = (code + " " + year).strip()
            if claim and claim not in seen:
                seen.add(claim)
                out.append(claim)
    return out


# --------------------------------------------------------------------------- #
# Prompt + parsing
# --------------------------------------------------------------------------- #

CITATION_SYSTEM_PROMPT = """\
You are a code-compliance reference checker for construction-drawing review. You \
are given ONE citation (a code/standard section reference) that appeared on a \
drawing set, the code editions the set says it adopts, and the finding(s) citing \
it. Using web search, check whether that section — in the ADOPTED edition (if \
stated) and in the CURRENT edition — exists and actually supports the finding(s). \
Watch for renumbering between editions (a section number valid in one edition may \
have moved in a later one). Be conservative: report a mismatch only when you \
found concrete evidence of one.

After searching, output a SINGLE fenced code block labeled json and nothing after \
it, containing exactly: {"status": "CHECKED_SUPPORTS" or "CHECKED_MISMATCH", \
"note": "<= 40 words on whether the section supports the finding(s)", \
"edition_notes": "<= 40 words on edition/renumbering differences, or \\"\\""}."""


def _build_citation_prompt(ref: str, editions: list[str], finding_texts: list[str]) -> str:
    ed = "; ".join(editions) if editions else "not stated on the drawings"
    lines = [
        f"CITATION TO CHECK: {ref}",
        f"CODE EDITIONS THE SET ADOPTS: {ed}",
        "FINDING(S) CITING IT:",
    ]
    lines += [f"- {t}" for t in finding_texts[:3]]
    lines.append(
        "Check the citation with web search and answer in the required json block."
    )
    return "\n".join(lines)


def _parse_verdict(raw_text: str) -> Citation:
    """The last parseable json block → :class:`Citation`; anything else UNCHECKED."""
    verdict: dict | None = None
    for m in _FENCE_RE.finditer(raw_text):
        obj = _tolerant_json_object(m.group(2))
        if isinstance(obj, dict) and "status" in obj:
            verdict = obj
    if verdict is None:
        return Citation(status="UNCHECKED", note="no parseable verdict")
    status = str(verdict.get("status", "")).strip().upper()
    if status not in ("CHECKED_SUPPORTS", "CHECKED_MISMATCH"):
        return Citation(status="UNCHECKED", note="unrecognized verdict")
    return Citation(
        status=status,
        note=str(verdict.get("note", "") or "").strip()[:300],
        edition_notes=str(verdict.get("edition_notes", "") or "").strip()[:300],
    )


# --------------------------------------------------------------------------- #
# The per-citation call (with pause_turn resumption)
# --------------------------------------------------------------------------- #


def _check_one(
    ref: str,
    editions: list[str],
    finding_texts: list[str],
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
) -> tuple[Citation, int, int]:
    """One citation check → ``(citation, in_tok, out_tok)``. Never raises."""
    user_text = _build_citation_prompt(ref, editions, finding_texts)
    messages: list[dict] = [{"role": "user", "content": user_text}]
    total_in = total_out = 0

    for _resume in range(_MAX_PAUSE_RESUMES + 1):
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": DEFAULT_CITATION_MAX_TOKENS,
            "system": CITATION_SYSTEM_PROMPT,
            "messages": messages,
            "tools": [web_search_tool()],
        }
        attempt = 0
        while True:
            try:
                resp = client.messages.create(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - degrade, never raise
                if _is_transient_error(exc) and attempt < max_retries:
                    sleep(_retry_backoff_seconds(attempt))
                    attempt += 1
                    continue
                return (
                    Citation(status="UNCHECKED", note=f"check failed: {_clean_error(exc)}"),
                    total_in, total_out,
                )
        in_tok, out_tok = _message_usage(resp)
        total_in += in_tok
        total_out += out_tok
        if _get(resp, "stop_reason") == "pause_turn":
            # The server-side search loop paused; re-send with the partial
            # assistant turn appended — the server resumes where it left off.
            content = _get(resp, "content")
            messages = [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": content},
            ]
            continue
        return _parse_verdict(_message_text(resp)), total_in, total_out

    return (
        Citation(status="UNCHECKED", note="check did not finish (still paused)"),
        total_in, total_out,
    )


# --------------------------------------------------------------------------- #
# Pass over a run's findings
# --------------------------------------------------------------------------- #


@dataclass
class CitationCheckResult:
    """The citation pass outcome: per-ref verdicts + token cost."""

    checked: int = 0                 # unique citations checked
    supports: int = 0
    mismatches: int = 0
    unchecked: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    by_ref: dict = field(default_factory=dict)   # ref -> Citation


def _combined_citation(refs: list[str], by_ref: dict) -> Citation | None:
    """One :class:`Citation` for a finding from its refs' verdicts.

    A single mismatch dominates (that's the signal worth ink); else a support;
    else unchecked. Notes are prefixed with their ref when a finding cites more
    than one, so the popup stays attributable.
    """
    verdicts = [(r, by_ref[r]) for r in refs if r in by_ref]
    if not verdicts:
        return None

    def _fmt(items: list[tuple[str, Citation]], field_name: str) -> str:
        parts = []
        for r, c in items:
            v = getattr(c, field_name).strip()
            if v:
                parts.append(f"{r}: {v}" if len(verdicts) > 1 else v)
        return " | ".join(parts)[:400]

    for wanted in ("CHECKED_MISMATCH", "CHECKED_SUPPORTS", "UNCHECKED"):
        hits = [(r, c) for r, c in verdicts if c.status == wanted]
        if hits:
            return Citation(
                status=wanted,
                note=_fmt(hits, "note"),
                edition_notes=_fmt(hits, "edition_notes"),
            )
    return None


def check_citations(
    findings: Iterable[Finding],
    geometries: Iterable[Any],
    *,
    client: Any = None,
    model: str | None = None,
    max_retries: int = DEFAULT_CITATION_MAX_RETRIES,
    sleep: Any = time.sleep,
    progress: Any = None,
) -> CitationCheckResult:
    """Check every **unique** citation across ``findings``; attach verdicts.

    One web-search-backed Messages call per unique ref; the resulting
    :class:`~drawing_analyzer.models.Citation` is attached to every finding citing
    it (``finding.citation``). Deterministic findings' refs (rare) are checked the
    same way. Additive and non-fatal (I-3): a failure marks the affected refs
    ``UNCHECKED`` and the run continues. ``progress(done, total, label)`` mirrors
    the verify pass's callback shape.
    """
    findings = [f for f in findings if getattr(f, "refs", None)]
    unique: list[str] = []
    seen: set[str] = set()
    texts_by_ref: dict[str, list[str]] = {}
    for f in findings:
        for r in f.refs:
            ref = str(r).strip()
            if not ref:
                continue
            if ref not in seen:
                seen.add(ref)
                unique.append(ref)
            texts_by_ref.setdefault(ref, []).append(f.text)

    result = CitationCheckResult()
    if not unique:
        return result

    if client is None:
        try:
            from .client import get_client as _get_client

            client = _get_client()
        except Exception as exc:  # noqa: BLE001 - no key etc. → skip the pass
            result.error = _clean_error(exc)
            result.unchecked = len(unique)
            return result

    model = model or citation_model()
    editions = harvest_code_editions(geometries)
    done = 0

    def _run(ref: str) -> tuple[str, Citation, int, int]:
        citation, in_tok, out_tok = _check_one(
            ref, editions, texts_by_ref[ref],
            client=client, model=model, max_retries=max_retries, sleep=sleep,
        )
        return ref, citation, in_tok, out_tok

    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(unique))) as pool:
        for ref, citation, in_tok, out_tok in pool.map(_run, unique):
            done += 1
            result.by_ref[ref] = citation
            result.input_tokens += in_tok
            result.output_tokens += out_tok
            result.checked += 1
            if citation.status == "CHECKED_SUPPORTS":
                result.supports += 1
            elif citation.status == "CHECKED_MISMATCH":
                result.mismatches += 1
            else:
                result.unchecked += 1
            if progress is not None:
                progress(done, len(unique), f"Checking citation {done}/{len(unique)}")

    for f in findings:
        combined = _combined_citation([str(r).strip() for r in f.refs], result.by_ref)
        if combined is not None:
            f.citation = combined

    _log.info(
        "citation check: %d unique ref(s) — %d support, %d mismatch, %d unchecked",
        result.checked, result.supports, result.mismatches, result.unchecked,
    )
    return result
