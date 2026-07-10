"""The critique pass — "the reviewer" (Phase 11).

The digest *describes* a sheet; the critique *attacks* it. This is a second
full-coverage vision read of the same sheet (the identical overview + tile grid +
verbatim text layer the digest saw — full coverage is inviolable here too), but
under a different persona and with a single job: find everything a senior
engineer back-checking a check print before issue would mark up — errors, code
concerns, RFI-worthy ambiguities, internal inconsistencies, stale/copy-paste
text, and *absences* (content that should be on the sheet but isn't).

It emits only the machine-readable findings block (the §4.1 contract, extended
with an optional ``anchor_hint`` of ``"SHEET"`` for sheet-level / absence
findings) — no prose digest. The prose digest stays the digest pass's job, so
``combined_text`` is untouched (I-2).

Self-consistency (default ON): the critique runs **twice**. Two independent
reads of the same sheet disagree at the margins, and that disagreement is signal
— a finding both runs surface is corroborated (``reproduced=True``); a singleton
one run raised is kept (more markups is better) but flagged ``reproduced=False``.
The merge (:func:`merge_self_consistency`) deduplicates by position and text; the
downstream verification pass and the report *surface* the ``reproduced`` flag but
it never suppresses a finding.

Caching: the *merged* critique result is cached under its own
(:func:`drawing_analyzer.digest_cache.critique_cache_key`, a distinct namespace
from the digest) so a re-run skips the model calls. The run-to-run sampling
variance the merge feeds on is not reproducible, so only the merged outcome is
stored — never an individual run.

Isolation (I-5): this module imports no PDF engine. It consumes already-rendered
:class:`~drawing_analyzer.models.RenderedSheet` objects and reuses the digest's
request/parse helpers; the pipeline owns rendering.
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .core.api_config import (
    REVIEW_MODEL_DEFAULT,
    model_supports_adaptive_thinking,
    model_supports_effort,
)
from .diagnostics import get_logger
from .digest import (
    DEFAULT_DIGEST_EFFORT,
    DEFAULT_DIGEST_MAX_RETRIES,
    DEFAULT_DIGEST_MAX_TOKENS,
    _clean_error,
    _get,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    build_user_content,
    claims_from_cache,
    findings_from_cache,
    parse_findings,
    parse_numeric_claims,
)
from .digest_cache import critique_cache_key
from .models import Finding, NumericClaim, RenderedSheet, source_page_key
from .profiles import (
    Profile,
    build_checklist_prompt,
    chunk_items,
    flatten_items,
    profiles_cache_fragment,
)

_log = get_logger()

# Above a rough character budget, a long review checklist is spread across the
# self-consistency runs (each run covers a slice; the union is complete — never
# truncated) rather than sent whole every run. Below it — the common case,
# including the shipped profiles — every run gets the full checklist so the reads
# stay directly comparable for self-consistency.
_CHECKLIST_CHUNK_THRESHOLD_CHARS = 6000


def _run_checklists(profiles: list[Profile] | None, runs: int) -> list[str]:
    """The checklist block to inject into each of ``runs`` critique reads.

    Normally the full checklist for every run. Only a checklist past the char
    threshold is chunked across the runs (logged), trading some self-consistency
    for coverage under token pressure, per the plan.
    """
    items = flatten_items(profiles or [])
    full = build_checklist_prompt(items)
    if not full:
        return [""] * runs
    if runs <= 1 or len(full) <= _CHECKLIST_CHUNK_THRESHOLD_CHARS:
        return [full] * runs
    _log.info(
        "critique checklist long (%d chars); chunking %d item(s) across %d run(s)",
        len(full), len(items), runs,
    )
    return [build_checklist_prompt(chunk) for chunk in chunk_items(items, runs)]

# Critique shares the digest's output-shaping defaults: Opus 4.8, adaptive
# thinking, effort high, 16k max_tokens (full coverage, deliberate reasoning).
DEFAULT_CRITIQUE_MAX_TOKENS = DEFAULT_DIGEST_MAX_TOKENS
DEFAULT_CRITIQUE_EFFORT = DEFAULT_DIGEST_EFFORT
DEFAULT_CRITIQUE_MAX_RETRIES = DEFAULT_DIGEST_MAX_RETRIES

# Self-consistency: the critique runs this many independent times and merges.
# Two is the exhaustive-mode default; 1 disables self-consistency (for debugging
# or cost control). Overridable via env.
DEFAULT_CRITIQUE_RUNS = 2


def critique_model() -> str:
    """The critique vision model (``DRAWING_ANALYZER_CRITIQUE_MODEL``, else Opus)."""
    return os.environ.get("DRAWING_ANALYZER_CRITIQUE_MODEL") or REVIEW_MODEL_DEFAULT


def critique_runs() -> int:
    """Self-consistency run count (``DRAWING_ANALYZER_CRITIQUE_RUNS``, default 2).

    Clamped to ``>= 1``; a non-integer value falls back to the default.
    """
    raw = os.environ.get("DRAWING_ANALYZER_CRITIQUE_RUNS")
    if raw is None or not raw.strip():
        return DEFAULT_CRITIQUE_RUNS
    try:
        return max(1, int(raw.strip()))
    except ValueError:
        return DEFAULT_CRITIQUE_RUNS


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

CRITIQUE_SYSTEM_PROMPT = """\
You are a senior engineer performing a rigorous back-check / QA review of ONE \
construction drawing sheet before it is issued for construction. Your job is NOT \
to describe the sheet — it is to find everything wrong with it, the way an \
experienced reviewer marking up a check print does.

Read the machine-extracted SHEET TEXT LAYER as the source of truth for exact \
strings (tags, schedule values, note numbers, references); read the images for \
graphics, symbols, dimensions, and placement. Work the sheet deliberately and \
report every issue you can substantiate, at the appropriate severity:

- errors — something shown on the sheet is wrong.
- code concerns — a likely code or standard violation. Cite conservatively; \
never invent a citation or a section number.
- ambiguities — anything a contractor would have to submit an RFI to resolve \
(missing dimensions, unclear scope, conflicting instructions).
- internal inconsistencies — a value, tag, or note on this sheet that \
contradicts another on THIS sheet.
- stale or copy-paste text — a note that names the wrong area, system, room, or \
sheet (a giveaway that it was copied from another sheet and not updated).
- absences — content that a complete sheet of this discipline is expected to \
show but this one does not (a required test, drain, sign, clearance, note, tag, \
or detail). Phrase each as "expected X; not found on this sheet."

Ground every finding in what is (or is provably not) on the sheet: quote the \
exact supporting string from the SHEET TEXT LAYER when there is one, and never \
invent tags, values, quantities, or citations. Judge only this sheet; a conflict \
you cannot confirm from this sheet alone is at most a low-severity question."""

# The closing user-turn instruction (replaces the digest's "produce the digest").
_CRITIQUE_TASK_INSTRUCTION = (
    "Now perform your back-check of this single sheet and report your findings, "
    "following the FINDINGS format in your instructions. Output only the fenced "
    "json findings block — no prose."
)

# Appended to the critique system prompt. Unlike the digest, the critique emits
# ONLY the findings block (no prose digest), and it may set ``anchor_hint`` to
# "SHEET" for a sheet-level or absence finding that has no on-sheet string to
# quote. Categories match the digest's model set (the deterministic "reference"
# category stays with the reference auditor).
_CRITIQUE_FINDINGS_INSTRUCTION = """\


FINDINGS (machine-read — the ONLY thing you output):
Output a SINGLE fenced code block labeled json and nothing else — no prose \
before or after it — containing {"findings": [ ... ], "claims": [ ... ]}. Each \
finding is an object with: sheet_id; category (one of code, conflict, \
coordination, question); severity (one of high, medium, low); text (the finding, \
at most two sentences); source_quote (COPY VERBATIM from the SHEET TEXT LAYER — \
exact characters — or "" for a purely graphical finding or an absence); \
anchor_hint (set to "SHEET" for a sheet-level finding or an absence — something \
that should be on the sheet but is not — otherwise omit it); tile ([row, col] of \
the tile where you saw it, or omit for a whole-sheet finding); refs (an array of \
any code or spec references you believe apply — cite conservatively). Emit at \
most 40 findings, most important first; emit "findings": [] only if the sheet is \
genuinely clean.

Also include a "claims" array in the SAME object. A claim is a numeric \
relationship shown on the sheet that a reviewer should check by CALCULATION — you \
do NOT do the arithmetic, you only transcribe the numbers exactly as printed and \
say how they should relate. Each claim: sheet_id; quote (COPY VERBATIM the \
on-sheet text the numbers come from); kind (one of sum, product, factor); terms \
(the numbers themselves — the addends of a column that should total, or a base \
value and its multiplier — as they appear on the sheet); expected (the stated \
result those terms should combine to — the printed total, or the stated design \
value); note (a short phrase naming the relationship). Emit claims only for \
relationships actually on the sheet (a column/row total, density × area = demand, \
base area × 1.3 = design area); emit "claims": [] if there are none. Never \
compute or "fix" the numbers — report them as printed and let the reviewer's \
calculation catch any error. Put nothing but the JSON object inside the block."""

# Folded into the critique cache key so any edit to the persona, the task line,
# or the findings instruction re-critiques rather than serving a stale read.
CRITIQUE_PROMPT_VERSION = hashlib.sha256(
    (
        CRITIQUE_SYSTEM_PROMPT
        + "\x00"
        + _CRITIQUE_TASK_INSTRUCTION
        + "\x00"
        + _CRITIQUE_FINDINGS_INSTRUCTION
    ).encode("utf-8")
).hexdigest()[:16]


def critique_system_prompt(checklist: str = "") -> str:
    """The effective critique system prompt: persona, then any review-profile
    ``checklist`` (Phase 12), then the findings instruction.

    The findings instruction stays **last** so the machine-read JSON block is
    emitted after everything (the parser's "last fenced block" rule); the
    checklist rides between the persona and it. Empty ``checklist`` reproduces the
    pre-profiles prompt byte-for-byte.
    """
    return CRITIQUE_SYSTEM_PROMPT + (checklist or "") + _CRITIQUE_FINDINGS_INSTRUCTION


def build_critique_request_params(
    content: list[dict],
    *,
    model: str,
    max_tokens: int = DEFAULT_CRITIQUE_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_CRITIQUE_EFFORT,
    checklist: str = "",
) -> dict[str, Any]:
    """Build the Messages-API request body for one critique read.

    Mirrors :func:`drawing_analyzer.digest.build_digest_request_params` (thinking
    / effort attached only when the model supports them) but with the critique
    system prompt. The user ``content`` is the digest's identical imagery + text
    layer, built with the critique closing instruction. ``checklist`` is the
    review-profile block injected into the system prompt.
    """
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": critique_system_prompt(checklist),
        "messages": [{"role": "user", "content": content}],
    }
    if use_thinking and model_supports_adaptive_thinking(model):
        params["thinking"] = {"type": "adaptive"}
    if effort and model_supports_effort(model):
        params["output_config"] = {"effort": effort}
    return params


# --------------------------------------------------------------------------- #
# Deduplication / merge (pure — no I/O, no PDF engine)
# --------------------------------------------------------------------------- #

# Two findings on the same sheet are duplicates only when they are *semantically*
# the same issue and their **critical signatures are compatible** (Phase 20, §12.1).
# A tile is a search hint, never identity — same-tile alone never merges — and
# geometric overlap alone is not enough either: two unrelated issues can share a
# table cell or a note. Thresholds:
_IOU_DUP_THRESHOLD = 0.5          # rect overlap needed for the geometry branch
_TEXT_DUP_THRESHOLD = 0.7         # strong topical overlap → duplicate
_MODERATE_TEXT_THRESHOLD = 0.4    # moderate overlap that only *supports* geometry

_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common function words carry no discriminating signal, so they are dropped
# before the text-overlap comparison. Without this, two findings that share only
# mandated boilerplate score a spuriously high Jaccard on the boilerplate alone
# and wrongly merge. The sharp case is *absences* — which have no quote and no
# tile, so they can only dedupe on text — phrased per the prompt as "expected X;
# not found on this sheet": two distinct absences ("expected cleanout…" vs
# "expected backflow…") would otherwise overlap >0.7 on the seven boilerplate
# tokens and collapse into one, silently dropping a real finding. Filtering to
# content tokens fixes that while leaving genuine duplicates (which share the
# *content* words) well above the threshold.
_STOPWORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "been", "but", "by",
    "for", "found", "from", "has", "have", "in", "into", "is", "it", "its",
    "no", "not", "of", "on", "or", "shown", "so", "that", "the", "then",
    "there", "this", "to", "was", "were", "with",
})


def _severity_rank(sev: str) -> int:
    return _SEVERITY_RANK.get((sev or "").lower(), 0)


def _most_severe(findings: list[Finding]) -> str:
    return max((f.severity for f in findings), key=_severity_rank, default="low")


def _norm_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS}


def _normalize(text: str) -> str:
    """Light normalization for quote comparison: lowercase + whitespace-collapse.

    Two findings that quote the *same* on-sheet string carry byte-identical quotes
    (both copied verbatim from one text layer), so a case/whitespace fold is enough
    to recognize them without the anchor resolver's full Unicode machinery.
    """
    return " ".join((text or "").lower().split())


def _token_overlap(a: str, b: str) -> float:
    """Jaccard overlap of two texts' normalized token sets (0..1)."""
    ta, tb = _norm_tokens(a), _norm_tokens(b)
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    return len(ta & tb) / union if union else 0.0


def _rect_iou(a: list[float], b: list[float]) -> float:
    """Intersection-over-union of two ``[x0, y0, x1, y1]`` rectangles (0..1)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _same_sheet(a: Finding, b: Finding) -> bool:
    # Collision-safe: two same-basename sheets from different inputs are NOT the
    # same sheet, so their findings are never merged (DA-001).
    return source_page_key(a) == source_page_key(b)


# --- Critical signatures (§12.1): engineering tokens that BLOCK an automatic merge
# when they conflict, even if the surrounding prose is similar. "500 gpm" vs
# "550 gpm", "M-101" vs "M-102", and "shown" vs "not shown" are all different
# findings that happen to read alike.

# Equipment tags / drawing-detail references: letters + (compact | -/. separated)
# digits — VAV-3, M-101, FP101, RV-3, AHU-2, M1.01, E2.1. A space is *not* a
# separator, so "SET 165" is a measurement, not a tag.
_TAG_RE = re.compile(r"\b([A-Za-z]{1,4})(?:-|\.)?(\d{1,4}(?:[.-]\d{1,3})?[A-Za-z]?)\b")
# A number (signed / decimal / fraction) immediately followed by a unit — a
# measurement whose value discriminates the finding.
_UNIT = (
    r"(?:gpm|gpd|gph|psig|psi|cfm|fpm|inch(?:es)?|in|ft|feet|mm|cm|kva|kw|hp|hz|"
    r"amps?|volts?|va|kv|gal|deg|°[fc]?|%|\"|')"
)
_MEAS_RE = re.compile(
    r"([-+]?\d+(?:\.\d+)?(?:\s*\d+\s*/\s*\d+)?)\s*" + _UNIT, re.IGNORECASE
)
# Strong "absence / not-present" phrasing — an absence finding contradicts a
# finding about the same thing being present.
_ABSENCE_RE = re.compile(
    r"\b(?:not\s+(?:shown|provided|indicated|dimensioned|specified|scheduled|"
    r"noted|labell?ed|called|located|found|present|on)|missing|omitted|absent|"
    r"no\s+\w+\s+(?:shown|provided|indicated|is\s+shown))\b",
    re.IGNORECASE,
)


def _sig_text(f: Finding) -> str:
    return f"{f.text or ''} {f.source_quote or ''}"


def _tags(f: Finding) -> set[str]:
    return {
        f"{m.group(1)}{m.group(2)}".upper().replace("-", "").replace(".", "")
        for m in _TAG_RE.finditer(_sig_text(f))
    }


def _measurements(f: Finding) -> set[str]:
    return {re.sub(r"\s+", "", m.group(1)) for m in _MEAS_RE.finditer(_sig_text(f))}


def _is_absence(f: Finding) -> bool:
    if (f.anchor_hint or "").upper() == "SHEET":
        return True
    return bool(_ABSENCE_RE.search(_sig_text(f)))


def _leg_targets(f: Finding) -> frozenset:
    """The set of sheets a cross-sheet finding also touches (its ``also_on`` legs)."""
    return frozenset(
        (leg.sheet_id or "").strip().upper()
        for leg in (getattr(f, "also_on", None) or [])
        if (leg.sheet_id or "").strip()
    )


def _signatures_compatible(a: Finding, b: Finding) -> bool:
    """False when a critical signature conflicts — the merge is then blocked (§12.1).

    Conservative: a conflict needs both findings to carry the signal and disagree
    on it (disjoint tag sets, disjoint measurement sets, or opposite absence
    polarity). A signal present in only one finding never blocks — "keep both" is
    the safe error, but so is "don't over-block a real duplicate".
    """
    ta, tb = _tags(a), _tags(b)
    if ta and tb and ta.isdisjoint(tb):
        return False                       # different equipment / drawing refs
    ma, mb = _measurements(a), _measurements(b)
    if ma and mb and ma.isdisjoint(mb):
        return False                       # different quantities
    if _is_absence(a) != _is_absence(b):
        return False                       # "shown" vs "not shown"
    la, lb = _leg_targets(a), _leg_targets(b)
    if la and lb and la != lb:
        return False                       # same quote, different cross-sheet legs
    return True


def _categories_compatible(a: Finding, b: Finding) -> bool:
    """Two findings can merge only if their categories are the same (or one is the
    catch-all ``question``). A ``code`` violation and a ``coordination`` note about
    the same words are different reviewable items."""
    ca, cb = (a.category or "").lower(), (b.category or "").lower()
    return ca == cb or "question" in (ca, cb)


def _quotes_equal(a: Finding, b: Finding) -> bool:
    qa, qb = _normalize(a.source_quote or ""), _normalize(b.source_quote or "")
    return bool(qa) and qa == qb


def _quote_overlap(a: Finding, b: Finding) -> bool:
    qa, qb = _normalize(a.source_quote or ""), _normalize(b.source_quote or "")
    if not qa or not qb:
        return False
    return qa in qb or qb in qa


def _is_duplicate(a: Finding, b: Finding) -> bool:
    """Whether two findings describe the same issue (Phase 20, §12.1).

    Requires the same source+page and **compatible critical signatures** — a tile
    is never sufficient, and geometric overlap alone is never sufficient. A merge
    fires only when the two are semantically the same: identical non-empty quote
    (same category), strong topical overlap, or — once both are anchored —
    heavily-overlapping rectangles *backed by* at least moderate text/quote
    agreement. When uncertain, keep both (more separate findings is the safe error).
    """
    if not _same_sheet(a, b):
        return False
    if not _signatures_compatible(a, b):
        return False
    # Exact same on-sheet quote, same category → the same grounded issue.
    if _quotes_equal(a, b) and _categories_compatible(a, b):
        return True
    # Strong topical overlap → the same issue restated.
    if _token_overlap(a.text, b.text) >= _TEXT_DUP_THRESHOLD:
        return True
    # Geometry (post-anchor) is only *supporting* evidence, never sufficient alone.
    ra = a.anchor.rect_pdf if a.anchor else None
    rb = b.anchor.rect_pdf if b.anchor else None
    if ra and rb and _rect_iou(ra, rb) > _IOU_DUP_THRESHOLD and _categories_compatible(a, b):
        if _token_overlap(a.text, b.text) >= _MODERATE_TEXT_THRESHOLD or _quote_overlap(a, b):
            return True
    return False


def _union_refs(findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for f in findings:
        for r in f.refs:
            if r not in out:
                out.append(r)
    return out


def _representative(cluster: list[Finding], *, reproduced: bool) -> Finding:
    """Collapse a cluster of duplicate findings into one, preserving **coherent
    grounding** (Phase 20 §12.2).

    One member is the representative and its grounded fields — ``text``,
    ``category``, ``source_quote``, ``tile``, ``anchor_hint`` — are taken together
    as an **atomic bundle**: a merged entry never pairs one finding's text with a
    *different* finding's quote (which would fabricate a text/quote combination that
    never appeared on the sheet). The representative is the member with the longest
    quote (the best anchoring hook), tie-broken by severity then the stable id. The
    other members' distinct quotes are preserved in ``supporting_quotes``; ``refs``
    union; severity is the most severe.

    Deliberately resets ``anchor`` / ``verification`` to their defaults: all current
    callers merge **before** anchoring, so every input carries the default anyway. A
    future caller that pools already-anchored/verified findings (the ledger) must
    re-anchor/re-verify the collapsed result rather than assume this preserved them.
    """
    base = max(
        cluster,
        key=lambda f: (len(f.source_quote or ""), _severity_rank(f.severity), f.id, f.text or ""),
    )
    base_q = _normalize(base.source_quote or "")
    supporting: list[str] = []
    for f in cluster:
        q = (f.source_quote or "").strip()
        if q and _normalize(q) != base_q and q not in supporting:
            supporting.append(q)
    # Preserve a cross-sheet finding's dual-anchor legs (the first non-empty), so
    # merging a conflict finding never silently drops its ``also_on``.
    also_on = next((list(f.also_on) for f in cluster if f.also_on), [])
    return Finding(
        sheet_id=base.sheet_id,
        source_name=base.source_name,
        source_id=base.source_id,
        page_index=base.page_index,
        category=base.category,
        severity=_most_severe(cluster),
        text=base.text,
        source_quote=base.source_quote,     # atomic with text/category/tile below
        tile=base.tile,
        refs=_union_refs(cluster),
        anchor_hint=base.anchor_hint,
        also_on=also_on,
        supporting_quotes=supporting,
        reproduced=reproduced,
        id=base.id,
    )


def _cluster(groups: list[list[Finding]]) -> list[list[tuple[int, Finding]]]:
    """Greedily cluster duplicates across ``groups`` (each a source's findings).

    Returns clusters of ``(group_index, finding)``; a finding joins the first
    existing cluster it duplicates any member of, else starts its own. Order is
    deterministic (groups then within-group order).
    """
    clusters: list[list[tuple[int, Finding]]] = []
    for gi, group in enumerate(groups):
        for f in group:
            for cluster in clusters:
                # Complete-link (§12.1): join only a cluster whose EVERY member is a
                # duplicate of ``f`` — never collapse A+B+C when A and C conflict.
                if all(_is_duplicate(f, cf) for _, cf in cluster):
                    cluster.append((gi, f))
                    break
            else:
                clusters.append([(gi, f)])
    return clusters


def merge_self_consistency(run_groups: list[list[Finding]]) -> list[Finding]:
    """Merge the findings of several critique runs of ONE sheet.

    ``reproduced`` is set from the double-read: with ``>= 2`` runs a finding that
    appears in only one run is ``reproduced=False`` (an uncorroborated singleton)
    and one seen in two or more is ``reproduced=True``. With a single run the
    concept does not apply, so everything stays ``reproduced=True`` (the flag is a
    corroboration signal, not a "single-sample" stamp). Never drops a finding.
    """
    n_runs = len(run_groups)

    def reproduced_of(spans: int) -> bool:
        return True if n_runs < 2 else spans >= 2

    out: list[Finding] = []
    for cluster in _cluster(run_groups):
        spans = len({gi for gi, _ in cluster})
        out.append(
            _representative([f for _, f in cluster], reproduced=reproduced_of(spans))
        )
    return out


def merge_finding_groups(groups: list[list[Finding]]) -> list[Finding]:
    """Pool findings from several sources (e.g. digest + critique) for one sheet.

    Deduplicates the same way, but ``reproduced`` is *upgraded, never downgraded*:
    a cluster is ``reproduced=True`` if any member already was (the critique's
    self-consistency verdict is preserved, and digest/auditor findings default
    ``True``) or the cluster spans two or more sources (cross-source corroboration
    — the digest and the critique independently raised it). Reusable by the later
    findings ledger.
    """
    out: list[Finding] = []
    for cluster in _cluster(groups):
        spans = len({gi for gi, _ in cluster})
        members = [f for _, f in cluster]
        reproduced = spans >= 2 or any(f.reproduced for f in members)
        out.append(_representative(members, reproduced=reproduced))
    return out


# --------------------------------------------------------------------------- #
# Model calls
# --------------------------------------------------------------------------- #


@dataclass
class CritiqueResult:
    """The outcome of critiquing one sheet (findings + token cost + provenance).

    ``claims`` are the numeric relationships the reviewer transcribed (Phase 14);
    the deterministic arithmetic auditor checks them downstream. They ride the
    same cache entry as the merged findings.
    """

    findings: list[Finding] = field(default_factory=list)
    claims: list[NumericClaim] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    runs: int = 0            # runs that returned findings (0 = all failed)
    error: str | None = None
    cached: bool = False


def critique_result_from_entry(entry: dict, ref: Any) -> CritiqueResult:
    """Rebuild a merged :class:`CritiqueResult` from a cache entry (any tier).

    A cache hit is content-keyed, sheet-local model data, so its findings/claims are
    rebound to the current ``ref``'s source identity (§10.3). Shared by the level-2
    (image-bytes) hit inside :func:`critique_sheet_self_consistent` and the level-1
    (pre-render) hit the pipeline serves without rasterizing (Phase 19B) — one
    place, so the two tiers can never drift in how a hit is materialized.
    """
    return CritiqueResult(
        findings=findings_from_cache(entry, ref),
        claims=claims_from_cache(entry, ref),
        input_tokens=int(entry.get("input_tokens", 0) or 0),
        output_tokens=int(entry.get("output_tokens", 0) or 0),
        runs=int(entry.get("runs", 0) or 0),
        error=None,
        cached=True,
    )


def critique_cache_entry_from_result(res: CritiqueResult) -> dict:
    """The cache-entry dict for a **complete** critique result (every tier shares it).

    Only ever called for a full self-consistency result (all requested reads
    succeeded); a partial result is returned to the caller but never cached (a
    1-of-2 read has nothing to disagree with it). Mirrors ``cache_entry_from_digest``.
    """
    return {
        "findings": [f.to_dict() for f in res.findings],
        "claims": [c.to_dict() for c in res.claims],
        "input_tokens": res.input_tokens,
        "output_tokens": res.output_tokens,
        "runs": res.runs,
        "created_ts": time.time(),
    }


def critique_sheet(
    rendered: RenderedSheet,
    *,
    client: Any = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_CRITIQUE_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_CRITIQUE_EFFORT,
    max_retries: int = DEFAULT_CRITIQUE_MAX_RETRIES,
    sleep: Any = time.sleep,
    checklist: str = "",
) -> tuple[list[Finding], list[NumericClaim], int, int, str | None]:
    """One critique read → ``(findings, claims, in_tok, out_tok, err)``.

    Mirrors :func:`drawing_analyzer.digest.digest_sheet`'s call loop (transient
    retry + backoff reused verbatim; a permanent failure returns immediately). On
    any failure ``findings`` / ``claims`` are empty and ``err`` is a sanitized
    message — the caller degrades, the run never dies (I-3). ``checklist`` is the
    review-profile block to inject into the prompt (empty for a plain critique).
    """
    model = model or critique_model()
    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    kwargs = build_critique_request_params(
        build_user_content(rendered, task_instruction=_CRITIQUE_TASK_INSTRUCTION),
        model=model,
        max_tokens=max_tokens,
        use_thinking=use_thinking,
        effort=effort,
        checklist=checklist,
    )

    attempt = 0
    while True:
        try:
            resp = client.messages.create(**kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - report, don't sink the set
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return [], [], 0, 0, _clean_error(exc)

    raw = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    if not raw:
        # An empty body (e.g. adaptive thinking consumed the whole token budget)
        # is a *failed* read, not a clean sheet — mirror digest_sheet's guard, so
        # the run counts as failed (not merged, not cached) and is re-attempted
        # next time rather than being frozen in cache as "reviewed, nothing found".
        stop = _get(resp, "stop_reason")
        return [], [], in_tok, out_tok, f"empty critique (stop_reason={stop!r})"
    # The critique emits only the findings block; parse_findings returns the
    # findings (the empty "prose" before the block is discarded) and
    # parse_numeric_claims lifts the "claims" array from the same block.
    _, findings, note = parse_findings(raw, rendered.ref)
    claims = parse_numeric_claims(raw, rendered.ref)
    if note:
        _log.info("critique parse: %s (%s)", note, rendered.ref.display_label)
    return findings, claims, in_tok, out_tok, None


def critique_sheet_self_consistent(
    rendered: RenderedSheet,
    *,
    client: Any = None,
    runs: int | None = None,
    cache: Any = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_CRITIQUE_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_CRITIQUE_EFFORT,
    max_retries: int = DEFAULT_CRITIQUE_MAX_RETRIES,
    sleep: Any = time.sleep,
    profiles: list[Profile] | None = None,
) -> CritiqueResult:
    """Critique one sheet ``runs`` times and merge (:func:`merge_self_consistency`).

    ``cache`` (a :class:`~drawing_analyzer.digest_cache.DigestCache`, or ``None``)
    is consulted first; on a hit the merged findings are served with no model
    call. Each run's failure is tolerated — the merge runs over whatever runs
    succeeded; only if *every* run fails is an error returned (empty findings).

    ``profiles`` (Phase 12) are review-profile checklists injected into the
    critique prompt; they fold into the cache key (so selecting or editing one
    re-critiques) and, if very long, are chunked across the runs.
    """
    model = model or critique_model()
    runs = critique_runs() if runs is None else max(1, int(runs))
    run_checklists = _run_checklists(profiles, runs)

    cache_key: str | None = None
    if cache is not None:
        cache_key = critique_cache_key(
            rendered,
            model=model,
            prompt_version=CRITIQUE_PROMPT_VERSION,
            max_tokens=max_tokens,
            effort=effort,
            use_thinking=use_thinking,
            runs=runs,
            sheet_text=rendered.sheet_text,
            profiles_key=profiles_cache_fragment(profiles or []),
        )
        hit = cache.get(cache_key)
        if hit is not None:
            return critique_result_from_entry(hit, rendered.ref)

    run_groups: list[list[Finding]] = []
    all_claims: list[NumericClaim] = []
    total_in = total_out = 0
    errors: list[str] = []
    for i in range(runs):
        findings, claims, in_tok, out_tok, err = critique_sheet(
            rendered,
            client=client,
            model=model,
            max_tokens=max_tokens,
            use_thinking=use_thinking,
            effort=effort,
            max_retries=max_retries,
            sleep=sleep,
            checklist=run_checklists[i],
        )
        total_in += in_tok
        total_out += out_tok
        if err is not None:
            errors.append(err)
            continue
        run_groups.append(findings)
        all_claims.extend(claims)

    if not run_groups:
        return CritiqueResult(
            findings=[],
            input_tokens=total_in,
            output_tokens=total_out,
            runs=0,
            error="; ".join(errors) or "critique produced no result",
        )

    merged = merge_self_consistency(run_groups)
    claims = _dedup_claims(all_claims)
    _log.info(
        "critique: %d run(s), %d merged finding(s) (%s)",
        len(run_groups), len(merged), rendered.ref.display_label,
    )

    result = CritiqueResult(
        findings=merged,
        claims=claims,
        input_tokens=total_in,
        output_tokens=total_out,
        runs=len(run_groups),
        error=None,
    )

    # Cache only a *complete* self-consistency result — every requested run
    # succeeded. A partial result (a transient failure dropped a run) is returned
    # to the caller (so this run still produces findings) but never cached: the
    # key was computed for ``runs`` reads, and a 1-of-2 result marks everything
    # ``reproduced=True`` (there was no second read to disagree). Freezing that
    # under the full-runs key would permanently deny the requested self-consistency.
    # Mirrors digest_sheet refusing to cache transient/degraded reads.
    if cache is not None and cache_key is not None and len(run_groups) == runs:
        cache.put(cache_key, critique_cache_entry_from_result(result))

    return result


def _dedup_claims(claims: list[NumericClaim]) -> list[NumericClaim]:
    """Collapse identical claims (the self-consistency runs transcribe the same
    relationship twice) so the arithmetic tally isn't double-counted. Order-stable.
    """
    seen: set[tuple] = set()
    out: list[NumericClaim] = []
    for c in claims:
        key = (
            (c.source_name or "").strip().lower(),
            int(c.page_index or 0),
            (c.sheet_id or "").strip().upper(),
            (c.kind or "").strip().lower(),
            (c.quote or "").strip(),
            tuple(str(t) for t in c.terms),
            str(c.expected),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
