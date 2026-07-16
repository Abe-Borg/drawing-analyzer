"""Citation check (Phase 15 / Phase 24) — verify cited code sections with web search.

Findings often carry code refs ("NFPA 13 §19.2.3.2.5", "Table 13.2.1"). Those
citations have a failure mode of their own: a drawing citing **2016-era numbering
under a 2019 basis** (the prototype found exactly that — Table 13.2.1 became
§4.3.1.7 in the 2019 renumbering). The drawing set can't validate its own
citations, so this pass asks the model to check each **unique** citation using the
API's server-side **web search tool**: does this section — in the edition the set
adopts *and* in the current edition — actually support the finding(s) citing it?

**Claim-completeness (Phase 24 §16.5, DA-017).** A citation verdict may attach to a
finding ONLY if that finding's claim was included in the request that produced it.
The old pass sent just the first three finding texts per reference and then pinned
that single verdict onto *every* finding citing the reference — logically invalid
when the same section is invoked for different claims. Now every distinct claim for
a reference is checked (chunked into claim-complete requests when there are many),
the model returns a **per-claim** verdict keyed by a request-local opaque handle,
and each resulting :class:`~drawing_analyzer.models.CitationAssessment` is attached
only to the findings whose claim it covered. A finding with several references keeps
one assessment *per reference*.

The verdict is informational: ``CHECKED_MISMATCH`` downgrades nothing
automatically (sometimes the stale citation *is* the finding); it is surfaced to
the engineer. Failures degrade to ``UNCHECKED`` and make the stage PARTIAL — the
run never dies (I-3) and the engineering finding is never suppressed.

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

**Per-request verdict cache with a TTL (Phase B).** Complete, fully-parsed
verdicts are cached content-addressed in the run's ``DigestCache`` (namespace
``stage=citation``) keyed on the exact ref + claim texts + editions/jurisdiction
context + model + prompt version + search budget — so a warm re-run serves the
same verdicts without re-paying for web searches. Web truth drifts, so entries
expire: ``DRAWING_ANALYZER_CITATION_TTL_DAYS`` (default 30; ``0`` disables the
cache entirely, no read and no write). A chunk with ANY unchecked claim, parse
failure, or error is **never cached**, so a cache hit can never mask the §8
unchecked-claim PARTIAL gate. I-7 carve-out: the TTL clock governs cache
admission/refresh only — whether an API call is made — never QC numbering,
index ordering, or merged-output assembly; a warm run's assembled output is
byte-identical to the run that populated the cache.
"""
from __future__ import annotations

import hashlib
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
    _server_web_search_requests,
    _tolerant_json_object,
)
from .models import Citation, CitationAssessment, Finding

_log = get_logger()

DEFAULT_CITATION_MAX_TOKENS = 4_000
DEFAULT_CITATION_MAX_RETRIES = 2
# The server-side loop can stop with pause_turn; resume at most this many times.
_MAX_PAUSE_RESUMES = 3
# Bound the web searches one citation check may run.
_WEB_SEARCH_MAX_USES = 5
# Bounded concurrency — citation checks are few but each runs server-side searches.
_MAX_WORKERS = 4
# Claims per request. A reference with more distinct claims is split into this many
# **claim-complete** chunks so EVERY claim is checked — never the old silent
# ``finding_texts[:3]`` truncation that dropped the 4th+ claim from the request.
_MAX_CLAIMS_PER_REQUEST = 8

_DEFAULT_WEB_SEARCH_TOOL_TYPE = "web_search_20260209"

_VALID_VERDICTS = frozenset({"CHECKED_SUPPORTS", "CHECKED_MISMATCH"})


def citation_model() -> str:
    """The citation-check model (``DRAWING_ANALYZER_CITATION_MODEL``, else Opus)."""
    return os.environ.get("DRAWING_ANALYZER_CITATION_MODEL") or REVIEW_MODEL_DEFAULT


def web_search_max_uses() -> int:
    """Per-request web-search bound (``DRAWING_ANALYZER_WEB_SEARCH_MAX_USES``).

    Defaults to :data:`_WEB_SEARCH_MAX_USES`; invalid or sub-1 values fall back
    to the default. The bound rides the citation cache key (Phase B), so
    changing it re-checks rather than serving verdicts searched under a
    different budget.
    """
    raw = os.environ.get("DRAWING_ANALYZER_WEB_SEARCH_MAX_USES", "")
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        return _WEB_SEARCH_MAX_USES
    return value if value >= 1 else _WEB_SEARCH_MAX_USES


def web_search_tool() -> dict:
    """The server-side web-search tool definition for the citation call."""
    tool_type = (
        os.environ.get("DRAWING_ANALYZER_WEB_SEARCH_TOOL_TYPE")
        or _DEFAULT_WEB_SEARCH_TOOL_TYPE
    )
    return {"type": tool_type, "name": "web_search", "max_uses": web_search_max_uses()}


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


def merged_editions(identity: Any, geometries: Iterable[Any]) -> str:
    """The editions line: model-detected adopted codes ∪ the regex harvest.

    The identity's entries lead (sorted; they carry amendments and reach the
    worldwide codes the US-centric ``_CODE_TOKEN`` whitelist can never match);
    regex-only extras follow in first-seen order as the deterministic backstop
    — a code the text plainly states can never be argued away by the model.
    With no identity this is byte-identical to the pre-Phase-A line.
    """
    regex_claims = harvest_code_editions(geometries)
    identity_claims: list[str] = []
    seen: set[str] = set()          # bare CODE EDITION, without amendment notes
    for code in getattr(identity, "adopted_codes", ()) or ():
        display = getattr(code, "display", "") or ""
        note = getattr(code, "amendment_note", "") or ""
        if display:
            identity_claims.append(f"{display} ({note})" if note else display)
            seen.add(" ".join(display.split()).upper())
    if not identity_claims:
        return "; ".join(regex_claims)
    extras = [c for c in regex_claims if " ".join(c.split()).upper() not in seen]
    return "; ".join(identity_claims + extras)


# --------------------------------------------------------------------------- #
# Prompt + parsing
# --------------------------------------------------------------------------- #

CITATION_SYSTEM_PROMPT = """\
You are a code-compliance reference checker for construction-drawing review. You \
are given ONE citation (a code/standard section reference) that appeared on a \
drawing set, the code editions the set says it adopts, and a numbered list of the \
distinct CLAIMS on the drawings that cite it. Using web search, check whether that \
section — in the ADOPTED edition (if stated) and in the CURRENT edition — exists \
and actually supports EACH claim. Watch for renumbering between editions (a section \
number valid in one edition may have moved in a later one). Be conservative: report \
a mismatch only when you found concrete evidence of one. Judge each claim on its own \
— different claims citing the same section can have different verdicts.

When a PROJECT JURISDICTION/LOCALE line is given, use it to resolve WHICH code, \
edition, or local amendment applies, and search in the set's language when that \
helps. The locale is model-detected from the drawings, not ground truth: when \
your search evidence contradicts it, follow the evidence and say so in the note.

After searching, output a SINGLE fenced code block labeled json and nothing after \
it, containing exactly: {"assessments": [{"claim": "<the claim's handle, e.g. C1>", \
"status": "CHECKED_SUPPORTS" or "CHECKED_MISMATCH", "note": "<= 30 words on whether \
the section supports THIS claim", "checked_edition": "<the code edition you \
actually verified this claim against, e.g. NFPA 13 2016, or \\"\\" if unclear>", \
"current_edition": "<the current published edition you found while searching, or \
\\"\\">", "evidence_url": "<the single best https URL supporting THIS verdict, or \
\\"\\">"}], "edition_notes": "<= 40 words on edition/renumbering differences, or \
\\"\\""}. Include exactly one entry per claim handle."""


_CITATION_TASK_INSTRUCTION = (
    "Check the citation with web search and answer in the required json block, "
    "with one assessment per claim handle above."
)

# Content hash of the static prompt pieces (I-6): a prompt edit re-keys the
# per-request verdict cache automatically. Dynamic request text (ref, claims,
# editions, jurisdiction) is content-addressed separately in the cache key.
CITATION_PROMPT_VERSION = hashlib.sha256(
    (CITATION_SYSTEM_PROMPT + "\x00" + _CITATION_TASK_INSTRUCTION).encode("utf-8")
).hexdigest()[:16]

_DEFAULT_CITATION_TTL_DAYS = 30


def citation_ttl_days() -> int:
    """Verdict-cache TTL in days (``DRAWING_ANALYZER_CITATION_TTL_DAYS``).

    Default 30. ``0`` disables the citation cache entirely — no read, no write
    (one knob: no TTL means no cache). Invalid/negative values fall back to the
    default.
    """
    raw = os.environ.get("DRAWING_ANALYZER_CITATION_TTL_DAYS", "")
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        return _DEFAULT_CITATION_TTL_DAYS
    if value == 0:
        return 0
    return value if value > 0 else _DEFAULT_CITATION_TTL_DAYS


def _normalize_claim(text: str) -> str:
    """Fold a claim (a finding's text) for grouping identical claims."""
    return " ".join((text or "").split()).lower()


def _build_citation_prompt(
    ref: str, editions_line: str, handled_claims: list[tuple[str, str]],
    jurisdiction_line: str = "",
) -> str:
    ed = editions_line or "not stated on the drawings"
    lines = [f"CITATION TO CHECK: {ref}"]
    if jurisdiction_line:
        lines.append(f"PROJECT JURISDICTION/LOCALE: {jurisdiction_line}")
    lines += [
        f"CODE EDITIONS THE SET ADOPTS: {ed}",
        "CLAIMS CITING IT (verify each; echo its handle):",
    ]
    lines += [f"[{handle}] {text}" for handle, text in handled_claims]
    lines.append(_CITATION_TASK_INSTRUCTION)
    return "\n".join(lines)


def _norm_status(raw: Any) -> str | None:
    s = str(raw or "").strip().upper()
    return s if s in _VALID_VERDICTS else None


def _norm_handle(raw: Any) -> str:
    """Fold a claim handle for tolerant matching: strip brackets/punctuation, upper.

    So a model that echoes ``C1`` as ``[C1]`` / ``c1`` / ``C1.`` still matches the
    request-local handle instead of being silently dropped to UNCHECKED.
    """
    return str(raw or "").strip().strip("[](){}. ").upper()


# Host-side caps on verdict fields (the model's output is never trusted bounded).
_NOTE_CAP = 300
_EDITION_FIELD_CAP = 80
_EVIDENCE_URL_CAP = 500


def _norm_edition_field(raw: Any) -> str:
    return " ".join(str(raw or "").split())[:_EDITION_FIELD_CAP]


def _norm_evidence_url(raw: Any) -> str:
    """A single https URL or ``""`` — a non-https value never reaches a link.

    Mirrors the HTML report's https-only link policy at the parse boundary, so
    a hallucinated ``javascript:``/``http:`` value is dropped before it can be
    stored, exported, or rendered anywhere.
    """
    url = str(raw or "").strip()
    if not url.lower().startswith("https://") or any(c.isspace() for c in url):
        return ""
    return url[:_EVIDENCE_URL_CAP]


def _verdict_fields(a: dict, status: str) -> dict:
    """One claim's bounded verdict record (Phase B structured provenance)."""
    return {
        "status": status,
        "note": str(a.get("note", "") or "").strip()[:_NOTE_CAP],
        "checked_edition": _norm_edition_field(a.get("checked_edition")),
        "current_edition": _norm_edition_field(a.get("current_edition")),
        "evidence_url": _norm_evidence_url(a.get("evidence_url")),
    }


def _parse_assessments(
    raw_text: str, handles: list[str]
) -> tuple[dict[str, dict], str, bool]:
    """Parse a citation response into ``{handle: verdict-fields}`` + edition notes.

    Each handle's value is the bounded dict :func:`_verdict_fields` builds
    (``status``/``note`` plus the Phase B provenance: ``checked_edition``,
    ``current_edition``, ``evidence_url`` — every new key optional, so an
    old-shape reply parses unchanged with ``""`` defaults). Accepts the
    per-claim ``{"assessments": [...]}`` shape (validating every returned
    handle against ``handles`` — an unknown handle is ignored, never trusted)
    and, for back-compat, a single ``{"status", "note", "edition_notes"}``
    verdict applied to every handle in the request. Returns ``parsed=False``
    when no verdict block is present (→ every claim UNCHECKED).
    """
    verdict: dict | None = None
    for m in _FENCE_RE.finditer(raw_text):
        obj = _tolerant_json_object(m.group(2))
        if isinstance(obj, dict) and ("assessments" in obj or "status" in obj):
            verdict = obj
    if verdict is None:
        return {}, "", False

    edition_notes = str(verdict.get("edition_notes", "") or "").strip()[:_NOTE_CAP]
    per: dict[str, dict] = {}
    assessments = verdict.get("assessments")
    if isinstance(assessments, list):
        # Validate every returned handle against the request manifest, tolerant of
        # bracket/case reformatting (§16.1): unknown handles are ignored, never trusted.
        norm_to_orig = {_norm_handle(h): h for h in handles}
        for a in assessments:
            if not isinstance(a, dict):
                continue
            orig = norm_to_orig.get(_norm_handle(a.get("claim", "")))
            if orig is None:                  # opaque-handle validation
                continue
            status = _norm_status(a.get("status"))
            if status is None:
                continue
            per[orig] = _verdict_fields(a, status)
        return per, edition_notes, True

    # Back-compat: one verdict for the whole request → applies to every claim in it.
    status = _norm_status(verdict.get("status"))
    if status is None:
        return {}, edition_notes, False
    fields = _verdict_fields(verdict, status)
    for h in handles:
        per[h] = dict(fields)
    return per, edition_notes, True


def _extract_web_sources(resp: Any) -> list[str]:
    """The URLs the server-side web search returned (for the assessment's trail)."""
    urls: list[str] = []
    for block in (_get(resp, "content") or []):
        if _get(block, "type") != "web_search_tool_result":
            continue
        for item in (_get(block, "content") or []):
            url = _get(item, "url")
            if url:
                urls.append(str(url))
    return urls[:10]


# --------------------------------------------------------------------------- #
# The per-request call (with pause_turn resumption)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _CheckOutcome:
    """One citation request's outcome (replaces the old 5-tuple).

    ``web_search_requests`` is the server-reported search count summed across
    the pause_turn resumes — ``None`` when no response in the loop carried the
    field, so the caller can fall back to its per-request approximation only
    when the count is genuinely unknown (Phase B exact billing).
    """

    raw_text: str | None = None
    sources: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    web_search_requests: int | None = None
    error: str | None = None


def _check_one(
    ref: str,
    editions_line: str,
    handled_claims: list[tuple[str, str]],
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
    jurisdiction_line: str = "",
) -> _CheckOutcome:
    """One citation request → :class:`_CheckOutcome`.

    Never raises. ``raw_text`` is ``None`` on a hard failure (``error`` set).
    """
    user_text = _build_citation_prompt(
        ref, editions_line, handled_claims, jurisdiction_line
    )
    messages: list[dict] = [{"role": "user", "content": user_text}]
    total_in = total_out = 0
    searches: int | None = None

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
                return _CheckOutcome(
                    input_tokens=total_in, output_tokens=total_out,
                    web_search_requests=searches, error=_clean_error(exc),
                )
        in_tok, out_tok = _message_usage(resp)
        total_in += in_tok
        total_out += out_tok
        # Sum server-reported search counts across resumes exactly like tokens;
        # stay None only while NO response has carried the field.
        reported = _server_web_search_requests(resp)
        if reported is not None:
            searches = (searches or 0) + reported
        if _get(resp, "stop_reason") == "pause_turn":
            # The server-side search loop paused; re-send with the partial
            # assistant turn appended — the server resumes where it left off.
            content = _get(resp, "content")
            messages = [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": content},
            ]
            continue
        return _CheckOutcome(
            raw_text=_message_text(resp),
            sources=tuple(_extract_web_sources(resp)),
            input_tokens=total_in, output_tokens=total_out,
            web_search_requests=searches,
        )

    return _CheckOutcome(
        input_tokens=total_in, output_tokens=total_out,
        web_search_requests=searches,
        error="check did not finish (still paused)",
    )


# --------------------------------------------------------------------------- #
# Pass over a run's findings
# --------------------------------------------------------------------------- #


@dataclass
class CitationCheckResult:
    """The citation pass outcome: per-reference verdicts + token cost.

    ``supports`` / ``mismatches`` / ``unchecked`` / ``unresolvable`` count **unique
    references** by their dominant verdict (a mismatch on any of a reference's
    claims dominates). ``assessments`` is the flat list of per-claim
    :class:`~drawing_analyzer.models.CitationAssessment` records, each bound to the
    exact findings whose claim it covered (DA-017). ``partial`` is True when any
    claim was left UNCHECKED / UNRESOLVABLE (a request/parser/tool failure) so the
    pipeline can mark the stage PARTIAL, never a clean COMPLETE.
    """

    checked: int = 0                 # unique references a request was sent for
    requests: int = 0                # claim-complete requests actually issued
    cached_requests: int = 0         # request chunks served from the verdict cache
    supports: int = 0
    mismatches: int = 0
    unchecked: int = 0
    unresolvable: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # Billable web searches: the server-reported count summed where responses
    # carried it, plus 1 per request whose responses did not (the pre-Phase-B
    # lower-bound approximation, kept as the per-request fallback).
    web_search_requests: int = 0
    error: str | None = None
    partial: bool = False
    assessments: list[CitationAssessment] = field(default_factory=list)
    by_ref: dict = field(default_factory=dict)   # ref -> dominant Citation (compat)


def _combine_finding_citation(assessments: list[CitationAssessment]) -> Citation | None:
    """One back-compat :class:`Citation` for a finding from its per-ref assessments.

    A single mismatch dominates (that's the signal worth ink); else a support; else
    unchecked. Notes are prefixed with their reference when a finding cites more than
    one, so the popup stays attributable.
    """
    if not assessments:
        return None
    multi = len(assessments) > 1

    def _fmt(items: list[CitationAssessment], field_name: str) -> str:
        parts = []
        for a in items:
            v = str(getattr(a, field_name, "") or "").strip()
            if v:
                parts.append(f"{a.reference}: {v}" if multi else v)
        return " | ".join(parts)[:400]

    for wanted in ("CHECKED_MISMATCH", "CHECKED_SUPPORTS", "UNRESOLVABLE", "UNCHECKED"):
        hits = [a for a in assessments if a.status == wanted]
        if hits:
            status = wanted if wanted in _VALID_VERDICTS else "UNCHECKED"
            return Citation(
                status=status,
                note=_fmt(hits, "note"),
                edition_notes=_fmt(hits, "edition_notes"),
            )
    return None


def _citation_payload_hash(
    ref: str, claim_texts: list[str], editions_line: str, jurisdiction_line: str
) -> str:
    """Content hash of one request chunk's exact payload (cache key input)."""
    joined = "\x1f".join([ref, *claim_texts, editions_line, jurisdiction_line])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def check_citations(
    findings: Iterable[Finding],
    geometries: Iterable[Any],
    *,
    client: Any = None,
    model: str | None = None,
    max_retries: int = DEFAULT_CITATION_MAX_RETRIES,
    sleep: Any = time.sleep,
    progress: Any = None,
    identity: Any = None,
    cache: Any = None,
    now: Any = time.time,
) -> CitationCheckResult:
    """Check every reference against the exact claims citing it; attach assessments.

    Each distinct claim (a finding's ``text``) for a reference is checked; a
    reference with many claims is split into claim-complete chunks so none is
    dropped (DA-017). Each :class:`~drawing_analyzer.models.CitationAssessment` is
    attached (``finding.citations``) only to the findings whose claim it covered,
    and the derived back-compat ``finding.citation`` summarizes a finding's per-ref
    assessments. Additive and non-fatal (I-3): a failure leaves the affected claims
    UNCHECKED and marks the stage PARTIAL. ``progress(done, total, label)`` mirrors
    the verify pass's callback.

    ``identity`` (Phase A §20.1, a :class:`~drawing_analyzer.models.SetIdentity`
    or ``None``) enriches the prompt only: its adopted codes merge ahead of the
    regex edition harvest and its locale rides a JURISDICTION line. ``None``
    reproduces the pre-identity behavior byte-for-byte.

    ``cache`` (Phase B, a :class:`~drawing_analyzer.digest_cache.DigestCache`
    or ``None``) enables the per-request verdict cache; ``now`` is the
    injectable clock its TTL comparison uses (tests stay deterministic, I-4).
    Only COMPLETE chunks are ever cached — see the module docstring.
    """
    findings = [f for f in findings if getattr(f, "refs", None)]

    # ref -> ordered distinct claims; each claim -> the findings sharing that text.
    ref_order: list[str] = []
    ref_claims: dict[str, dict[str, dict]] = {}
    for f in findings:
        for r in f.refs:
            ref = str(r).strip()
            if not ref:
                continue
            if ref not in ref_claims:
                ref_claims[ref] = {}
                ref_order.append(ref)
            key = _normalize_claim(f.text)
            claim = ref_claims[ref].setdefault(key, {"text": f.text, "finding_ids": []})
            if f.id not in claim["finding_ids"]:
                claim["finding_ids"].append(f.id)

    result = CitationCheckResult()
    if not ref_order:
        return result

    if client is None:
        try:
            from .client import get_client as _get_client

            client = _get_client()
        except Exception as exc:  # noqa: BLE001 - no key etc. → skip the pass
            result.error = _clean_error(exc)
            result.unchecked = len(ref_order)
            result.partial = True
            _attach_unchecked(findings, ref_claims, result, note="citation client unavailable")
            return result

    model = model or citation_model()
    editions_line = merged_editions(identity, geometries)
    jurisdiction_line = (
        identity.citation_context_line()
        if identity is not None and hasattr(identity, "citation_context_line")
        else ""
    )

    # Build the claim-complete request work-list.
    # request = (ref, request_id, [(handle, claim_dict)])
    requests: list[tuple[str, str, list[tuple[str, dict]]]] = []
    for ri, ref in enumerate(ref_order):
        claims = list(ref_claims[ref].values())
        chunks = [
            claims[i:i + _MAX_CLAIMS_PER_REQUEST]
            for i in range(0, len(claims), _MAX_CLAIMS_PER_REQUEST)
        ] or [[]]
        for ci, chunk in enumerate(chunks):
            handled = [(f"C{j + 1}", c) for j, c in enumerate(chunk)]
            requests.append((ref, f"cite-{ri:02d}-{ci:02d}", handled))

    # ref -> per-claim CitationAssessment (keyed by normalized claim text).
    claim_assessments: dict[tuple[str, str], CitationAssessment] = {}
    total = len(requests)
    done = 0

    # Phase B verdict cache: content-addressed per request chunk; TTL compared
    # here with the injectable clock (DigestCache itself stays time-blind).
    ttl_days = citation_ttl_days()
    use_cache = cache is not None and ttl_days > 0
    ttl_seconds = float(ttl_days) * 86400.0

    def _cache_key_for(ref: str, handled: list) -> str:
        from .digest_cache import citation_cache_key

        return citation_cache_key(
            _citation_payload_hash(
                ref, [_normalize_claim(c["text"]) for _h, c in handled],
                editions_line, jurisdiction_line,
            ),
            model=model,
            prompt_version=CITATION_PROMPT_VERSION,
            max_uses=web_search_max_uses(),
        )

    def _fresh_cached_entry(key: str, handled: list) -> dict | None:
        entry = cache.get(key)
        if entry is None or not isinstance(entry.get("per_claim"), dict):
            return None
        try:
            checked_at = float(entry.get("checked_at", 0) or 0)
        except (TypeError, ValueError):
            return None
        if not (float(now()) - checked_at < ttl_seconds):
            return None                       # expired -> miss (fresh re-check)
        per_claim = entry["per_claim"]
        # Complete-only admission makes this redundant in practice, but a
        # cache file is external input: verify every claim is covered by a
        # valid verdict before serving (an incomplete entry can never mask
        # the §8 unchecked-claim gate).
        for _h, claim in handled:
            fields = per_claim.get(_normalize_claim(claim["text"]))
            if not isinstance(fields, dict) or fields.get("status") not in _VALID_VERDICTS:
                return None
        return entry

    def _run(req: tuple) -> tuple:
        ref, rid, handled = req
        key = _cache_key_for(ref, handled) if use_cache else None
        if key is not None:
            entry = _fresh_cached_entry(key, handled)
            if entry is not None:
                return ref, rid, handled, None, entry, key
        outcome = _check_one(
            ref, editions_line, [(h, c["text"]) for h, c in handled],
            client=client, model=model, max_retries=max_retries, sleep=sleep,
            jurisdiction_line=jurisdiction_line,
        )
        return ref, rid, handled, outcome, None, key

    fresh_requests = 0
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(requests))) as pool:
        for ref, rid, handled, outcome, entry, key in pool.map(_run, requests):
            done += 1
            if entry is not None:
                # Served from the verdict cache: zero tokens, zero searches.
                result.cached_requests += 1
                per_claim = entry["per_claim"]
                cached_notes = str(entry.get("edition_notes", "") or "")
                cached_sources = [str(u) for u in (entry.get("sources") or [])]
                for handle, claim in handled:
                    fields = per_claim[_normalize_claim(claim["text"])]
                    claim_assessments[(ref, _normalize_claim(claim["text"]))] = CitationAssessment(
                        reference=ref,
                        status=str(fields.get("status", "UNCHECKED")),
                        claim_finding_ids=list(claim["finding_ids"]),
                        note=str(fields.get("note", "") or ""),
                        edition_notes=cached_notes,
                        adopted_edition=editions_line,
                        checked_edition=str(fields.get("checked_edition", "") or ""),
                        current_edition=str(fields.get("current_edition", "") or ""),
                        evidence_url=str(fields.get("evidence_url", "") or ""),
                        sources=cached_sources,
                        request_id=rid,
                    )
                if progress is not None:
                    progress(done, total, f"Checking citation {done}/{total}")
                continue
            fresh_requests += 1
            result.input_tokens += outcome.input_tokens
            result.output_tokens += outcome.output_tokens
            # Exact where the server reported it; else the 1-per-request
            # lower-bound approximation this stage always billed.
            result.web_search_requests += (
                outcome.web_search_requests
                if outcome.web_search_requests is not None
                else 1
            )
            if outcome.error is not None or outcome.raw_text is None:
                result.partial = True
                if outcome.error:
                    result.error = "; ".join(
                        x for x in (result.error, outcome.error) if x
                    )
                per: dict[str, dict] = {}
                edition_notes = ""
                parsed = False
            else:
                per, edition_notes, parsed = _parse_assessments(
                    outcome.raw_text, [h for h, _c in handled]
                )
                if not parsed:
                    result.partial = True
            for handle, claim in handled:
                fields = per.get(
                    handle, {"status": "UNCHECKED", "note": "no verdict for this claim"}
                )
                if fields["status"] == "UNCHECKED":
                    result.partial = True
                claim_assessments[(ref, _normalize_claim(claim["text"]))] = CitationAssessment(
                    reference=ref,
                    status=fields["status"],
                    claim_finding_ids=list(claim["finding_ids"]),
                    note=fields["note"],
                    edition_notes=edition_notes,
                    adopted_edition=editions_line,
                    checked_edition=fields.get("checked_edition", ""),
                    current_edition=fields.get("current_edition", ""),
                    evidence_url=fields.get("evidence_url", ""),
                    sources=list(outcome.sources),
                    request_id=rid,
                )
            # Complete-only admission (Phase B): cache the chunk only when it
            # parsed AND every claim got a valid verdict — a partial/failed
            # chunk always re-runs live, so the cache can never mask PARTIAL.
            if (
                key is not None and parsed and outcome.error is None
                and all(h in per for h, _c in handled)
            ):
                cache.put(key, {
                    "per_claim": {
                        _normalize_claim(c["text"]): dict(per[h])
                        for h, c in handled
                    },
                    "edition_notes": edition_notes,
                    "sources": list(outcome.sources),
                    "web_search_requests": outcome.web_search_requests,
                    "checked_at": float(now()),
                    "model": model,
                    "prompt_version": CITATION_PROMPT_VERSION,
                })
            if progress is not None:
                progress(done, total, f"Checking citation {done}/{total}")

    result.assessments = list(claim_assessments.values())
    result.checked = len(ref_order)
    # ``requests`` = claim-complete API requests actually ISSUED this run;
    # cache-served chunks count in ``cached_requests`` (zero tokens/searches).
    result.requests = fresh_requests

    # Count unique references by dominant verdict (mismatch dominates) and populate
    # the compat ``by_ref`` map (one dominant Citation per reference).
    assessments_by_ref: dict[str, list[CitationAssessment]] = {}
    for a in result.assessments:
        assessments_by_ref.setdefault(a.reference, []).append(a)
    for ref in ref_order:
        group = assessments_by_ref.get(ref, [])
        statuses = {a.status for a in group} or {"UNCHECKED"}
        if "CHECKED_MISMATCH" in statuses:
            result.mismatches += 1
        elif "CHECKED_SUPPORTS" in statuses:
            result.supports += 1
        elif "UNRESOLVABLE" in statuses:
            result.unresolvable += 1
        else:
            result.unchecked += 1
        combined = _combine_finding_citation(group)
        if combined is not None:
            result.by_ref[ref] = combined

    # Attach per-reference assessments to each finding, then derive its summary.
    for f in findings:
        attached: list[CitationAssessment] = []
        seen_refs: set[str] = set()
        for r in f.refs:
            ref = str(r).strip()
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)
            a = claim_assessments.get((ref, _normalize_claim(f.text)))
            if a is not None:
                attached.append(a)
        f.citations = attached
        combined = _combine_finding_citation(attached)
        if combined is not None:
            f.citation = combined

    _log.info(
        "citation check: %d unique ref(s) — %d support, %d mismatch, %d unchecked, "
        "%d unresolvable%s",
        result.checked, result.supports, result.mismatches, result.unchecked,
        result.unresolvable, " (PARTIAL)" if result.partial else "",
    )
    return result


def _attach_unchecked(
    findings: list[Finding], ref_claims: dict, result: CitationCheckResult, *, note: str
) -> None:
    """Attach an UNCHECKED assessment to every finding when the pass could not run
    at all (no client), so the report still shows the reference was not verified.

    Builds one assessment per ``(reference, claim)`` group — with the *full* set of
    finding ids sharing that claim — and records them on ``result.assessments`` so
    the stage's ``items_out`` tally reflects the annotations actually made.
    """
    # (ref, normalized claim text) -> UNCHECKED assessment (shared across findings).
    claim_assessments: dict[tuple[str, str], CitationAssessment] = {}
    for ref, claims in ref_claims.items():
        for claim in claims.values():
            claim_assessments[(ref, _normalize_claim(claim["text"]))] = CitationAssessment(
                reference=ref, status="UNCHECKED",
                claim_finding_ids=list(claim["finding_ids"]), note=note,
            )
    result.assessments = list(claim_assessments.values())

    for f in findings:
        attached: list[CitationAssessment] = []
        seen: set[str] = set()
        for r in f.refs:
            ref = str(r).strip()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            a = claim_assessments.get((ref, _normalize_claim(f.text)))
            if a is not None:
                attached.append(a)
        f.citations = attached
        combined = _combine_finding_citation(attached)
        if combined is not None:
            f.citation = combined
