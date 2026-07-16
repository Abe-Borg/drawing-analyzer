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
from .models import (
    Citation,
    CitationAssessment,
    Finding,
    Verification,
    source_page_key,
)

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
# Pre-seal edition audit (Phase B) — adopted-vs-cited edition divergence
# --------------------------------------------------------------------------- #
#
# The deterministically detectable divergence class: a finding's ref cites
# edition X of a code family the set adopts at edition Y. No web search is
# needed — it is a string comparison between the cited edition tokens and the
# adopted-editions basis — so it runs BEFORE the ledger seals and its findings
# anchor/number/verify/ink like any other (the post-seal add ban never trips).
#
# Trust model (mirrors the arithmetic §17.5 operand rule): the comparison's
# host OPERATION is always deterministic, but each OPERAND is trusted only when
# the drawing text independently carries it. The adopted side is corroborated
# by a regex-harvest hit or by re-finding the identity entry's evidence quote
# verbatim in a sheet text layer; the cited side by re-finding the family+year
# in the citing finding's quote or its sheet's text. Fully corroborated →
# medium severity + a DETERMINISTIC verdict (auto-ink, like the auditors);
# anything model-asserted → a low-severity, explicitly-labeled advisory that
# rides the normal crop-verify + web-check paths. An identity entry with NO
# evidence quote never contributes a basis at all.

_YEAR_TOKEN_RE = re.compile(r"\b((?:19|20)\d{2})\b")
# Separators allowed between a family and its edition year. Deliberately
# excludes "." and "§" so a section number like "IBC §2019.3" can never read
# as an edition year; ":" is included for the EN convention ("EN 12845:2020").
_EDITION_SEP = r"[\s,:()–-]{0,4}"
# A code+year mention immediately followed by a section marker is a CITATION
# ("NFPA 13 2013 §8.15.1"), not an adoption statement — it must never enter
# the adopted basis, or the stale citation would launder its own edition into
# "adopted" and self-suppress the divergence it should trigger.
_SECTION_AFTER_RE = re.compile(
    r"^\s*(?:§|SEC\b|SECTION\b|TABLE\b|CHAPTER\b|CH\.)", re.IGNORECASE
)


def _basis_edition_claims(geometries: Iterable[Any]) -> list[str]:
    """Adoption-shaped ``"CODE YEAR"`` claims for the edition-audit basis.

    Same scan as :func:`harvest_code_editions` (which stays loose — for the
    citation PROMPT a passing mention is still useful context), but mentions
    followed by a section marker are excluded here: they are citations, not
    adoptions. A citation-shaped mention without a section marker still slips
    in — the conservative direction (it can only SUPPRESS a divergence
    finding, never fabricate one).
    """
    out: list[str] = []
    seen: set[str] = set()
    for geom in geometries or []:
        text = getattr(geom, "sheet_text", "") or ""
        for m in _EDITION_RE.finditer(text):
            if _SECTION_AFTER_RE.match(text[m.end():m.end() + 12]):
                continue
            code = re.sub(
                r"\s+", " ", (m.group("code") or m.group("code2") or "").upper()
            ).strip()
            year = m.group("year") or m.group("year2") or ""
            claim = (code + " " + year).strip()
            if claim and claim not in seen:
                seen.add(claim)
                out.append(claim)
    return out


def _norm_family(code: str) -> str:
    return " ".join(str(code or "").split()).upper()


def _fold_text(text: str) -> str:
    return " ".join(str(text or "").split()).upper()


def _family_year_re(family: str) -> "re.Pattern[str]":
    """A per-family variant of ``_EDITION_RE``: this family adjacent to a year.

    Family tokens may be joined by spaces or hyphens on the drawings
    ("NFPA 13" / "NFPA-13"); the trailing ``\\b`` keeps "NFPA 13" from matching
    inside "NFPA 130".
    """
    fam = r"[\s-]*".join(re.escape(t) for t in family.split())
    return re.compile(
        rf"\b{fam}\b{_EDITION_SEP}\b((?:19|20)\d{{2}})\b"
        rf"|\b((?:19|20)\d{{2}})\b{_EDITION_SEP}\b{fam}\b",
        re.IGNORECASE,
    )


def _cited_years(rx: "re.Pattern[str]", text: str) -> set[str]:
    return {m.group(1) or m.group(2) for m in rx.finditer(text or "")}


@dataclass(frozen=True)
class _AdoptedBasis:
    """One code family's adopted-edition ground truth."""

    display: str                     # family as displayed ("NFPA 13")
    years: frozenset
    corroborated: bool               # any contributing entry is text-grounded
    basis_label: str                 # human wording for the finding text


def _adopted_basis_map(identity: Any, geometries: list) -> dict:
    """``{normalized_family: _AdoptedBasis}`` from identity ∪ regex harvest.

    Regex-harvest entries are text facts (always corroborated). An identity
    entry contributes only when its edition carries a 4-digit year AND it has
    a non-empty evidence quote (or ``origin="regex"``); its corroboration is
    decided by re-finding that quote verbatim (whitespace-folded) in a sheet
    text layer — converting the model's containment claim into a checked fact.
    """
    folded_texts = [
        _fold_text(getattr(g, "sheet_text", "") or "") for g in (geometries or [])
    ]
    raw: dict[str, dict] = {}

    def _bucket(fam: str, display: str) -> dict:
        return raw.setdefault(fam, {
            "display": display, "years": set(),
            "corroborated": False, "advisory_only": True, "label": "",
        })

    for claim in _basis_edition_claims(geometries or []):
        code, _, year = claim.rpartition(" ")
        if not code or not _YEAR_TOKEN_RE.fullmatch(year):
            continue
        b = _bucket(_norm_family(code), code)
        b["years"].add(year)
        b["corroborated"] = True
        b["advisory_only"] = False
        b["label"] = b["label"] or "stated in the drawing text"

    for ac in getattr(identity, "adopted_codes", ()) or ():
        code = str(getattr(ac, "code", "") or "").strip()
        edition = str(getattr(ac, "edition", "") or "")
        quote = str(getattr(ac, "quote", "") or "").strip()
        origin = str(getattr(ac, "origin", "model") or "model")
        if origin == "regex":
            # Redundant here: identity's regex-union entries are the LOOSE
            # harvest (Phase A containment for the prompt line), which would
            # re-launder citation-shaped mentions into the basis. This audit's
            # regex ground truth is the citation-shape-filtered
            # ``_basis_edition_claims`` scan above.
            continue
        m = _YEAR_TOKEN_RE.search(edition)
        if not code or m is None:
            continue                      # no basis year → never assert divergence
        if not quote:
            continue                      # bare model assertion → no finding basis
        corroborated = False
        label = "model-detected basis — advisory"
        folded = _fold_text(quote)
        if folded and any(folded in t for t in folded_texts):
            corroborated = True
            src = str(getattr(ac, "source_sheet", "") or "")
            label = f"stated on {src}" if src else "stated in the drawing text"
        b = _bucket(_norm_family(code), code)
        b["years"].add(m.group(1))
        if corroborated:
            b["corroborated"] = True
            b["advisory_only"] = False
            b["label"] = label if not b["label"] else b["label"]
        elif b["advisory_only"]:
            b["label"] = b["label"] or label

    return {
        fam: _AdoptedBasis(
            display=b["display"], years=frozenset(b["years"]),
            corroborated=b["corroborated"], basis_label=b["label"],
        )
        for fam, b in raw.items() if b["years"]
    }


def reconcile_cited_editions(
    findings: Iterable[Finding], identity: Any, geometries: list
) -> list[Finding]:
    """Divergence findings: refs citing an edition the set does not adopt.

    Zero-API and pre-seal by contract — the caller adds the returned findings
    to the OPEN ledger, where they anchor (to the citing note's own quote),
    number, verify, and ink like any other entry. Deduped one finding per
    ``(source, page, family, cited year)``; deterministic ordering (I-7).
    Never raises on malformed inputs; returns ``[]`` when there is no adopted
    basis or no refs.
    """
    basis_map = _adopted_basis_map(identity, geometries)
    if not basis_map:
        return []
    family_res = {fam: _family_year_re(b.display) for fam, b in basis_map.items()}
    geom_text_by_key = {
        source_page_key(g.ref): getattr(g, "sheet_text", "") or ""
        for g in (geometries or [])
        if getattr(g, "ref", None) is not None
    }

    def _cited_span(rx: "re.Pattern[str]", year: str, text: str) -> str:
        """The exact matched ``FAMILY … YEAR`` snippet for this year ("" if none)."""
        for m in rx.finditer(text or ""):
            if (m.group(1) or m.group(2)) == year:
                return " ".join(m.group(0).split())
        return ""

    # key -> {"refs": set, "rep": Finding, "sheet_span": str, "quote_span": str}
    hits: dict[tuple, dict] = {}
    for f in findings or []:
        refs = list(getattr(f, "refs", None) or [])
        if not refs:
            continue
        skey = source_page_key(f)
        sheet_text = geom_text_by_key.get(skey, "")
        quote = str(getattr(f, "source_quote", "") or "")
        for ref in refs:
            ref_text = str(ref or "")
            for fam, rx in family_res.items():
                b = basis_map[fam]
                for year in _cited_years(rx, ref_text):
                    if year in b.years:
                        continue          # cited an adopted edition → fine
                    key = (skey[0], skey[1], fam, year)
                    rec = hits.setdefault(key, {
                        "refs": set(), "rep": None,
                        "sheet_span": "", "quote_span": "",
                    })
                    rec["refs"].add(" ".join(ref_text.split()))
                    if rec["rep"] is None:
                        rec["rep"] = f
                    # The divergence anchors to the stale-edition text ITSELF —
                    # its own matched span, never the citing finding's whole
                    # quote (a copied quote would anchor to the identical rect
                    # and Pass B would fold the two findings into one).
                    if not rec["sheet_span"]:
                        rec["sheet_span"] = _cited_span(rx, year, sheet_text)
                    if not rec["quote_span"]:
                        rec["quote_span"] = _cited_span(rx, year, quote)

    out: list[Finding] = []
    for key in sorted(hits, key=lambda k: (str(k[0]), int(k[1]), str(k[2]), str(k[3]))):
        _src, _page, fam, year = key
        rec = hits[key]
        b = basis_map[fam]
        rep = rec["rep"]
        refs_sorted = sorted(rec["refs"])
        adopted_years = "/".join(sorted(b.years))
        # Cited-side corroboration = the family+year re-finds in the sheet's
        # OWN text layer (a quote-only span is model-transcribed — advisory).
        tier1 = b.corroborated and bool(rec["sheet_span"])
        divergence_quote = rec["sheet_span"] or rec["quote_span"]
        suffix = f" ({b.basis_label})" if b.basis_label else ""
        text = (
            f'Cited edition divergence: "{refs_sorted[0]}" cites {b.display} {year}, '
            f"but the set adopts {b.display} {adopted_years}{suffix}. "
            "Verify the cited section against the adopted edition."
        )
        divergence = Finding(
            sheet_id=str(getattr(rep, "sheet_id", "") or ""),
            source_name=str(getattr(rep, "source_name", "") or ""),
            source_id=str(getattr(rep, "source_id", "") or ""),
            page_index=int(getattr(rep, "page_index", 0) or 0),
            category="code",
            severity="medium" if tier1 else "low",
            text=text,
            source_quote=divergence_quote,
            anchor_hint="" if divergence_quote else "SHEET",
            refs=refs_sorted,
            sources=["edition_audit"],
        )
        if tier1:
            # Both operands text-grounded: the comparison is a checked fact,
            # trusted like the offline auditors (deterministic-only ink gate).
            divergence.verification = Verification(
                status="DETERMINISTIC",
                note=(
                    f"host edition comparison: cited {b.display} {year} vs adopted "
                    f"{b.display} {adopted_years}, both re-found in the drawing text"
                ),
            )
        out.append(divergence)
    return out


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
