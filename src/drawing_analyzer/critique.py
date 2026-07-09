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
    findings_from_cache,
    parse_findings,
)
from .digest_cache import critique_cache_key
from .models import Finding, RenderedSheet
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
before or after it — containing {"findings": [ ... ]}. Each finding is an object \
with: sheet_id; category (one of code, conflict, coordination, question); \
severity (one of high, medium, low); text (the finding, at most two sentences); \
source_quote (COPY VERBATIM from the SHEET TEXT LAYER — exact characters — or "" \
for a purely graphical finding or an absence); anchor_hint (set to "SHEET" for a \
sheet-level finding or an absence — something that should be on the sheet but is \
not — otherwise omit it); tile ([row, col] of the tile where you saw it, or omit \
for a whole-sheet finding); refs (an array of any code or spec references you \
believe apply — cite conservatively). Emit at most 40 findings, most important \
first; emit {"findings": []} only if the sheet is genuinely clean. Put nothing \
but the JSON object inside the block."""

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

# Two findings on the same sheet are duplicates when they overlap geometrically
# (anchor-rect IoU once anchored, else the same reported tile) OR their normalized
# text overlaps strongly. Thresholds per the plan (§ Phase 11).
_IOU_DUP_THRESHOLD = 0.5
_TEXT_DUP_THRESHOLD = 0.7

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
    return (a.source_name, a.page_index) == (b.source_name, b.page_index)


def _is_duplicate(a: Finding, b: Finding) -> bool:
    """Whether two findings describe the same issue (same sheet + overlap)."""
    if not _same_sheet(a, b):
        return False
    ra = a.anchor.rect_pdf if a.anchor else None
    rb = b.anchor.rect_pdf if b.anchor else None
    if ra and rb:
        geo = _rect_iou(ra, rb) > _IOU_DUP_THRESHOLD
    elif a.tile is not None and b.tile is not None:
        # Pre-anchor (the critique merge runs before anchoring): the reported
        # tile is the coarse position proxy for the IoU rule.
        geo = list(a.tile) == list(b.tile)
    else:
        geo = False
    return geo or _token_overlap(a.text, b.text) > _TEXT_DUP_THRESHOLD


def _union_refs(findings: list[Finding]) -> list[str]:
    out: list[str] = []
    for f in findings:
        for r in f.refs:
            if r not in out:
                out.append(r)
    return out


def _representative(cluster: list[Finding], *, reproduced: bool) -> Finding:
    """Collapse a cluster of duplicate findings into one.

    Keeps the most severe severity, the longest ``source_quote`` (the best
    anchoring hook), the union of ``refs``, and the first non-empty
    ``anchor_hint`` / non-null ``tile``. The base finding (its text and id) is the
    one with the longest quote, so a collapsed finding keeps a stable, content-
    derived id.

    Deliberately resets ``anchor`` / ``verification`` to their defaults: all
    current callers merge **before** anchoring, so every input carries the default
    anyway. A future caller that pools already-anchored/verified findings (the
    ledger) must re-anchor/re-verify the collapsed result rather than assume this
    preserved them.
    """
    base = max(
        cluster,
        key=lambda f: (len(f.source_quote or ""), _severity_rank(f.severity)),
    )
    quote = max((f.source_quote or "" for f in cluster), key=len)
    tile = next((f.tile for f in cluster if f.tile is not None), None)
    anchor_hint = next((f.anchor_hint for f in cluster if f.anchor_hint), "")
    # Preserve a cross-sheet finding's dual-anchor legs (the first non-empty), so
    # merging a conflict finding never silently drops its ``also_on``.
    also_on = next((list(f.also_on) for f in cluster if f.also_on), [])
    return Finding(
        sheet_id=base.sheet_id,
        source_name=base.source_name,
        page_index=base.page_index,
        category=base.category,
        severity=_most_severe(cluster),
        text=base.text,
        source_quote=quote,
        tile=tile,
        refs=_union_refs(cluster),
        anchor_hint=anchor_hint,
        also_on=also_on,
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
                if any(_is_duplicate(f, cf) for _, cf in cluster):
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
    """The outcome of critiquing one sheet (findings + token cost + provenance)."""

    findings: list[Finding] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    runs: int = 0            # runs that returned findings (0 = all failed)
    error: str | None = None
    cached: bool = False


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
) -> tuple[list[Finding], int, int, str | None]:
    """One critique read of a rendered sheet → ``(findings, in_tok, out_tok, err)``.

    Mirrors :func:`drawing_analyzer.digest.digest_sheet`'s call loop (transient
    retry + backoff reused verbatim; a permanent failure returns immediately). On
    any failure ``findings`` is empty and ``err`` is a sanitized message — the
    caller degrades, the run never dies (I-3). ``checklist`` is the review-profile
    block to inject into the prompt (empty for a plain critique).
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
            return [], 0, 0, _clean_error(exc)

    raw = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    if not raw:
        # An empty body (e.g. adaptive thinking consumed the whole token budget)
        # is a *failed* read, not a clean sheet — mirror digest_sheet's guard, so
        # the run counts as failed (not merged, not cached) and is re-attempted
        # next time rather than being frozen in cache as "reviewed, nothing found".
        stop = _get(resp, "stop_reason")
        return [], in_tok, out_tok, f"empty critique (stop_reason={stop!r})"
    # The critique emits only the findings block; parse_findings returns the
    # findings (the empty "prose" before the block is discarded).
    _, findings, note = parse_findings(raw, rendered.ref)
    if note:
        _log.info("critique parse: %s (%s)", note, rendered.ref.display_label)
    return findings, in_tok, out_tok, None


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
            return CritiqueResult(
                findings=findings_from_cache(hit, rendered.ref),
                input_tokens=int(hit.get("input_tokens", 0) or 0),
                output_tokens=int(hit.get("output_tokens", 0) or 0),
                runs=int(hit.get("runs", runs) or runs),
                error=None,
                cached=True,
            )

    run_groups: list[list[Finding]] = []
    total_in = total_out = 0
    errors: list[str] = []
    for i in range(runs):
        findings, in_tok, out_tok, err = critique_sheet(
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

    if not run_groups:
        return CritiqueResult(
            findings=[],
            input_tokens=total_in,
            output_tokens=total_out,
            runs=0,
            error="; ".join(errors) or "critique produced no result",
        )

    merged = merge_self_consistency(run_groups)
    _log.info(
        "critique: %d run(s), %d merged finding(s) (%s)",
        len(run_groups), len(merged), rendered.ref.display_label,
    )

    # Cache only a *complete* self-consistency result — every requested run
    # succeeded. A partial result (a transient failure dropped a run) is returned
    # to the caller (so this run still produces findings) but never cached: the
    # key was computed for ``runs`` reads, and a 1-of-2 result marks everything
    # ``reproduced=True`` (there was no second read to disagree). Freezing that
    # under the full-runs key would permanently deny the requested self-consistency.
    # Mirrors digest_sheet refusing to cache transient/degraded reads.
    if cache is not None and cache_key is not None and len(run_groups) == runs:
        cache.put(
            cache_key,
            {
                "findings": [f.to_dict() for f in merged],
                "input_tokens": total_in,
                "output_tokens": total_out,
                "runs": len(run_groups),
                "created_ts": time.time(),
            },
        )

    return CritiqueResult(
        findings=merged,
        input_tokens=total_in,
        output_tokens=total_out,
        runs=len(run_groups),
        error=None,
    )
