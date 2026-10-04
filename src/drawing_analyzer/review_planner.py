"""Model-authored review plan: the set's own specialist checklist (Phase A §20.2).

Given the detected :class:`~drawing_analyzer.models.SetIdentity` and the sheet
digests, ONE text-only call authors the review checklist a specialist for THIS
set would apply — per discipline, in the exact one-line item style the review
profiles use — and the result is injected through the **existing** profile
machinery: each discipline's plan becomes a caller-built
:class:`~drawing_analyzer.profiles.Profile` object appended after the user's
own profiles, so versioning, checklist rendering, the critique cache fragment
(``profiles_cache_fragment``), and the manifest snapshots all apply unchanged.

Grounding contract: every item that relies on a code requirement must name the
code + section + edition inline (and never invent a section number). The
critique echoes an item's refs into ``Finding.refs``, and refs are exactly what
the citation check verifies with web search — so a plan item's code claim is
never trusted, it is checked. Items are bounded host-side (count, length,
severity vocabulary, ref count); an overlong item is **dropped and counted**,
never truncated — a truncated check is a corrupted check.

The plan is advisory and additive: authoring failure degrades this stage only
(I-3) and the critique proceeds with the user's profiles (or none). Plans are
cached content-addressed on the exact corpus + identity. Unchanged sheets also
bind that snapshot to the substantive review scope, so routine revisions retain
the checklist and the critique ``profiles_key`` (the Phase 19B economics).
PDF-engine-free (I-5); deterministic assembly (I-7: plans sort by discipline).
"""
from __future__ import annotations

import hashlib
import json
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
from .digest import (
    DEFAULT_DIGEST_MAX_RETRIES,
    SheetDigest,
    _clean_error,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    stream_message,
    _tolerant_json_object,
    scan_structured_blocks,
)
from .models import ProfileSnapshot
from .set_identity import _as_list
from .profiles import Profile
from .stage_cache import get_stage_cache_entry, put_stage_cache_entry, stage_cache_key

DEFAULT_PLAN_MAX_TOKENS = 32_000
DEFAULT_PLAN_EFFORT = "high"          # judgment work — what WOULD a specialist check?

# Host-enforced bounds on the authored plan (the model's output is never
# trusted to be bounded). The total-items cap is env-overridable because it is
# a real cost lever: every item rides both critique reads of every sheet.
_MAX_PLANS = 8
_MAX_ITEMS_PER_PLAN = 25
_DEFAULT_MAX_PLAN_ITEMS = 60
_ITEM_TEXT_CAP = 300
_MAX_REFS_PER_ITEM = 3
_REF_CAP = 80
_TITLE_CAP = 120
_SEVERITIES = ("high", "medium", "low")

# Planner corpus: identity block + every ok sheet's digest head, loss-aware.
_PLAN_HEAD_SLICE = 800
_PLAN_TOTAL_BUDGET = 200_000


def max_plan_items() -> int:
    """Total-items cap (``DRAWING_ANALYZER_MAX_PLAN_ITEMS``, default 60, min 1)."""
    raw = os.environ.get("DRAWING_ANALYZER_MAX_PLAN_ITEMS", "")
    try:
        value = int(raw.strip())
    except (ValueError, AttributeError):
        return _DEFAULT_MAX_PLAN_ITEMS
    return max(1, value)


def default_review_plan_model() -> str:
    """Model for the planner — the review model by default, overridable via
    ``DRAWING_ANALYZER_REVIEW_PLAN_MODEL``."""
    override = os.environ.get("DRAWING_ANALYZER_REVIEW_PLAN_MODEL")
    if override and override.strip():
        return override.strip()
    return REVIEW_MODEL_DEFAULT


PLANNER_SYSTEM_PROMPT = """\
You are a senior review lead assembling the QC checklist a specialist reviewer \
would apply to ONE specific construction-drawing set. You are given the set's \
detected identity (disciplines, jurisdiction, language, units, adopted codes) \
and a short digest head of every sheet. Author the review plan: for each \
discipline present, the checks an experienced reviewer of that discipline, in \
that jurisdiction, would run against these sheets.

Rules for items:
- Each item is ONE imperative, self-contained check under 300 characters, in \
the form "flag X when Y" (or, for required content, "expected X; flag when not \
found"). Never refer back to "the adopted code" or "the identity" — name \
things explicitly so the item stands alone.
- An item that relies on a code requirement MUST name the code, section, and \
edition it relies on (e.g. "NFPA 13 2016 §19.2.3.2.5") in its refs — and you \
must NEVER invent a section number. If you are not certain of the exact \
section, cite the code and edition only. Cite only codes the set adopts, or \
clearly applicable national/international standards; every ref you emit will \
be independently verified by web search.
- Prioritize: the highest-value checks first within each plan — life-safety \
and cross-discipline coordination failures beat drafting nits. severity is \
"high", "medium", or "low".
- Prefer checks that can be decided from the drawings themselves (schedules, \
notes, plans) — this checklist is applied sheet by sheet by a reviewer who \
sees the full sheet image and text.

Output a SINGLE fenced code block labeled json and nothing after it, \
containing exactly: {"plans": [{"discipline": "...", "title": "...", \
"items": [{"text": "...", "severity": "...", "refs": ["..."]}]}]} — one plan \
per discipline actually present, at most 25 items per plan."""


_PLANNER_TASK_INSTRUCTION = (
    "Above are the set identity and the per-sheet digest heads. Author the "
    "review plan per your instructions and answer in the single required json "
    "block."
)

# Content hash of the static prompt pieces (I-6): an edit re-keys the plan cache.
PLANNER_PROMPT_VERSION = hashlib.sha256(
    (PLANNER_SYSTEM_PROMPT + "\x00" + _PLANNER_TASK_INSTRUCTION).encode("utf-8")
).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Corpus (pure, deterministic)
# --------------------------------------------------------------------------- #


def build_planner_user_text(identity: Any, sheet_digests: list[SheetDigest]) -> tuple[str, int]:
    """Assemble the planner's user turn. Returns ``(text, omitted_chars)``.

    The identity context block leads (or an explicit "unavailable" line — the
    planner still runs identity-less, inferring from the digests, I-3); then
    every ok sheet's digest head in page order, budget-capped and loss-counted.
    """
    parts: list[str] = []
    if identity is not None and getattr(identity, "has_content", False):
        parts.append(identity.context_block())
    else:
        parts.append(
            "SET IDENTITY: unavailable — infer the disciplines and applicable "
            "codes from the digests below."
        )
    parts.append("")
    ok_sheets = [sd for sd in sheet_digests if sd.ok]
    total = len(ok_sheets)
    parts.append(f"PER-SHEET DIGEST HEADS ({total} readable sheet(s)):")
    used = sum(len(p) for p in parts)
    omitted = 0
    for i, sd in enumerate(ok_sheets, start=1):
        head = (sd.text or "").strip()[:_PLAN_HEAD_SLICE]
        block = f"===== Sheet {i}/{total}: {sd.ref.display_label} =====\n{head}"
        if used + len(block) <= _PLAN_TOTAL_BUDGET:
            parts.append(block)
            used += len(block) + 1
        else:
            omitted += len(block)
    parts.append("")
    parts.append(_PLANNER_TASK_INSTRUCTION)
    return "\n".join(parts), omitted


# --------------------------------------------------------------------------- #
# Sanitation → Profile objects (host-side bounds; deterministic)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PlanItem:
    """One bounded checklist item as authored by the model."""

    text: str
    severity: str = "medium"
    refs: tuple[str, ...] = ()


def render_item(item: PlanItem) -> str:
    """The profile-style one-line rendering: ``text [severity] (refs)``.

    Byte-compatible with the hand-written profile item convention, so severity
    tags and parenthesized refs flow through ``build_checklist_prompt`` exactly
    like a user checklist's.
    """
    line = f"{item.text} [{item.severity}]"
    if item.refs:
        line += f" ({', '.join(item.refs)})"
    return line


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _slug(discipline: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", discipline.lower()).strip("-")
    return slug or "general"


@dataclass(frozen=True)
class DisciplinePlan:
    """One discipline's sanitized plan."""

    discipline: str
    title: str
    items: tuple[PlanItem, ...]

    @property
    def slug(self) -> str:
        return _slug(self.discipline)


def sanitize_plans(obj: dict) -> tuple[list[DisciplinePlan], int]:
    """Bound the model's plans payload. Returns ``(plans, dropped_items)``.

    Deterministic (I-7): plans sort by discipline slug; item order within a
    plan is preserved (the prompt asks for value-ordered items). Dropped =
    overlong/empty items, duplicate items (case-folded), items past the caps,
    and every item of a malformed plan entry.
    """
    dropped = 0
    plans: list[DisciplinePlan] = []
    seen_disciplines: set[str] = set()
    total_cap = max_plan_items()
    raw_plans = obj.get("plans") if isinstance(obj, dict) else None
    if not isinstance(raw_plans, list):
        return [], 0
    # Plans past the cap are discarded WHOLE — count their items so the stage
    # reports PARTIAL instead of silently losing entire discipline checklists
    # (an uncounted drop would let the run claim a COMPLETE review plan).
    for raw in raw_plans[_MAX_PLANS:]:
        overflow_items = _as_list(raw.get("items")) if isinstance(raw, dict) else []
        dropped += max(1, len(overflow_items))
    for raw in raw_plans[:_MAX_PLANS]:
        if not isinstance(raw, dict):
            dropped += 1
            continue
        discipline = _one_line(raw.get("discipline")).lower()[:40]
        if not discipline or _slug(discipline) in seen_disciplines:
            dropped += max(1, len(_as_list(raw.get("items"))))
            continue
        seen_disciplines.add(_slug(discipline))
        title = _one_line(raw.get("title"))[:_TITLE_CAP] or f"Model review plan — {discipline}"
        items: list[PlanItem] = []
        seen_texts: set[str] = set()
        raw_items = _as_list(raw.get("items"))
        if len(raw_items) > _MAX_ITEMS_PER_PLAN * 2:
            # Items past the scan window are discarded unseen — count them too.
            dropped += len(raw_items) - _MAX_ITEMS_PER_PLAN * 2
        for entry in raw_items[: _MAX_ITEMS_PER_PLAN * 2]:
            if len(items) >= _MAX_ITEMS_PER_PLAN:
                dropped += 1
                continue
            if not isinstance(entry, dict):
                dropped += 1
                continue
            text = _one_line(entry.get("text"))
            if not text or len(text) > _ITEM_TEXT_CAP:
                # Overlong items are dropped, never truncated — a truncated
                # check is a corrupted check.
                dropped += 1
                continue
            if text.casefold() in seen_texts:
                dropped += 1
                continue
            seen_texts.add(text.casefold())
            severity = _one_line(entry.get("severity")).lower()
            if severity not in _SEVERITIES:
                severity = "medium"
            refs = tuple(
                _one_line(r)[:_REF_CAP]
                for r in _as_list(entry.get("refs"))[:_MAX_REFS_PER_ITEM]
                if _one_line(r)
            )
            items.append(PlanItem(text=text, severity=severity, refs=refs))
        if items:
            plans.append(DisciplinePlan(discipline=discipline, title=title, items=tuple(items)))
        else:
            dropped += 1
    plans.sort(key=lambda p: p.slug)
    # Enforce the TOTAL cap across plans by trimming the LARGEST plan each round,
    # not the last plan's tail (N5). Plans are sorted by slug, so tail-trimming
    # spent the whole overage in alphabetical order and deleted entire
    # disciplines: measured with five disciplines of 20 items against the 60-item
    # cap, `mechanical` and `plumbing` were removed outright — not trimmed,
    # removed — while `architectural`, `electrical` and `fire protection` kept all
    # 20. On a set whose mechanical and plumbing sheets are the point of the
    # review, that is the checklist you needed. Largest-first shares the loss
    # instead: the same input now leaves 12 items on every discipline. Item order
    # within a plan is value-ordered, so the item given up is still the cheapest
    # one in that plan.
    total = sum(len(p.items) for p in plans)
    while total > total_cap and plans:
        # Longest plan; ties go to the earliest slug, so the trim is
        # deterministic (I-7).
        idx = max(range(len(plans)), key=lambda i: (len(plans[i].items), -i))
        longest = plans[idx]
        if len(longest.items) <= 1:
            # Every plan is down to a single item and the cap is smaller than the
            # number of disciplines — only now can a whole plan go, from the end.
            last = plans.pop()
            dropped += len(last.items)
            total -= len(last.items)
            continue
        plans[idx] = DisciplinePlan(
            discipline=longest.discipline, title=longest.title,
            items=longest.items[:-1],
        )
        dropped += 1
        total -= 1
    return plans, dropped


def parse_planner_text(raw_text: str) -> dict | None:
    """The last fenced block that parses to an object with a ``plans`` key."""
    for block in reversed(scan_structured_blocks(raw_text or "")):
        obj = _tolerant_json_object(block.body)
        if obj is not None and "plans" in obj:
            return obj
    return None


def profiles_from_plans(plans: list[DisciplinePlan]) -> list[Profile]:
    """One caller-built :class:`Profile` per discipline plan (the Phase D
    delegation contract: one future reviewer = one plan + its sheet subset).

    ``date`` stays empty deliberately: a timestamp would make the rendered
    checklist — and therefore the critique cache fragment — differ across
    identical runs (I-6/I-7).
    """
    out: list[Profile] = []
    for plan in plans:
        rendered = tuple(render_item(it) for it in plan.items)
        content_hash = hashlib.sha256("\n".join(rendered).encode("utf-8")).hexdigest()[:16]
        out.append(Profile(
            name=f"model-plan-{plan.slug}",
            title=plan.title,
            disciplines=(plan.slug,),
            version="1",
            author="model",
            date="",
            items=rendered,
            content_hash=content_hash,
            source_path=None,
        ))
    return out


def plan_snapshots(profiles: list[Profile]) -> list[ProfileSnapshot]:
    """Manifest snapshots for injected plan profiles — ``source="model"``."""
    return [
        ProfileSnapshot(
            name=p.name, title=p.title, version=p.version,
            content_hash=p.content_hash, source="model",
            disciplines=tuple(p.disciplines),
        )
        for p in profiles
    ]


def render_plan_markdown(profiles: list[Profile], *, model: str, identity: Any = None) -> str:
    """The exported ``review_plan.md`` — the full authored plan, auditable."""
    lines = [
        "# Model-authored review plan",
        "",
        f"_Authored by `{model}` from the set's detected identity"
        + (
            f" (confidence: {identity.confidence or 'unstated'})._"
            if identity is not None and getattr(identity, "confidence", "")
            else "._"
        ),
        "",
    ]
    for p in profiles:
        lines.append(f"## {p.title}")
        lines.append("")
        lines.append(f"_{p.name} v{p.version} · content hash `{p.content_hash}`_")
        lines.append("")
        lines.extend(f"- {item}" for item in p.items)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------- #
# The stage call
# --------------------------------------------------------------------------- #


@dataclass
class PlanResult:
    """Result of the review-plan authoring pass."""

    profiles: list[Profile] = field(default_factory=list)
    markdown: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model_used: str = ""
    error: str | None = None
    dropped_items: int = 0
    cached: bool = False
    reused: bool = False              # snapshot retained from a prior revision

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.profiles)

    @property
    def item_count(self) -> int:
        return sum(len(p.items) for p in self.profiles)


def _identity_hash(identity: Any) -> str:
    if identity is None or not hasattr(identity, "to_dict"):
        return ""
    return hashlib.sha256(
        json.dumps(identity.to_dict(), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _review_scope_hash(identity: Any) -> str | None:
    """Canonical facts that require a new checklist when they change.

    Sheet inventory and detection provenance are not review requirements. Keep
    disciplines, project/set type, locale, and code editions/amendments; discard
    sheet classifications, evidence, confidence, notes, and code source labels.
    Without a usable identity we cannot establish compatible revisions.
    """
    if identity is None or not hasattr(identity, "to_dict"):
        return None
    data = identity.to_dict()

    def normalize(value: Any) -> str:
        return _one_line(value).casefold()

    scope = {
        name: normalize(data.get(name))
        for name in (
            "project_type", "set_type", "jurisdiction", "country", "region",
            "language", "units",
        )
    }
    scope["disciplines"] = sorted({
        normalize(d) for d in data.get("disciplines", []) if normalize(d)
    })
    scope["adopted_codes"] = sorted({
        tuple(normalize(c.get(k)) for k in ("code", "edition", "amendment_note"))
        for c in data.get("adopted_codes", []) if isinstance(c, dict)
    })
    if not any(scope.values()):
        return None
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode("utf-8")).hexdigest()


def _plan_binding_keys(
    identity: Any,
    sheet_digests: list[SheetDigest],
    sheet_keys: dict[tuple[str, int], str] | None,
    *,
    model: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
) -> list[str]:
    """Snapshot pointers keyed by unchanged content + scope + planner settings.

    The pipeline supplies content-addressed prescan keys without page locators.
    Direct callers can establish continuity through identical digest prose.
    Paths/filenames/page counts never identify a binding. This is a separate
    namespace: the exact-request cache and the critique key contract stay intact.
    """
    scope_hash = _review_scope_hash(identity)
    if scope_hash is None:
        return []
    fingerprints = set()
    for sd in sheet_digests:
        if not sd.ok:
            continue
        if sheet_keys is not None:
            key = sheet_keys.get((str(sd.ref.pdf_path), sd.ref.page_index))
            if key:
                fingerprints.add("sheet:" + key)
        else:
            fingerprints.add("digest:" + hashlib.sha256(sd.text.encode("utf-8")).hexdigest())
    return [
        stage_cache_key(
            "review_plan_binding", model=model, prompt=PLANNER_PROMPT_VERSION,
            inputs={"scope": scope_hash, "sheet": fingerprint},
            params={
                "contract": 1, "max_tokens": max_tokens, "effort": effort,
                "use_thinking": use_thinking, "max_items": max_plan_items(),
            },
        )
        for fingerprint in sorted(fingerprints)
    ]


def _cached_plan_result(
    entry: Any, *, model: str, identity: Any, reused: bool = False,
) -> PlanResult | None:
    if not isinstance(entry, dict) or not isinstance(entry.get("plans"), list):
        return None
    plans, dropped = sanitize_plans({"plans": entry["plans"]})
    profiles = profiles_from_plans(plans)
    if not profiles:
        return None
    try:
        original_dropped = max(0, int(entry.get("dropped_items", 0)))
    except (TypeError, ValueError):
        return None
    model_used = str(entry.get("model", model))
    markdown = render_plan_markdown(
        profiles, model=model_used, identity=None if reused else identity,
    )
    if reused:
        markdown += (
            "\n_Checklist retained from a prior revision with the same review scope._\n"
        )
    return PlanResult(
        profiles=profiles, markdown=markdown, model_used=model_used,
        dropped_items=dropped + original_dropped,
        cached=True, reused=reused,
    )


def _bind_plan(cache: Any, keys: list[str], plan_key: str) -> None:
    for key in keys:
        put_stage_cache_entry(
            cache, key, stage="review_plan_binding", payload={"plan_key": plan_key},
        )


def author_review_plan(
    identity: Any,
    sheet_digests: list[SheetDigest],
    *,
    client: Any = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_PLAN_MAX_TOKENS,
    use_thinking: bool = True,
    effort: str | None = DEFAULT_PLAN_EFFORT,
    max_retries: int = DEFAULT_DIGEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    cache: Any = None,
    sheet_keys: dict[tuple[str, int], str] | None = None,
) -> PlanResult:
    """Author the set's review plan in one text-only call (never raises — I-3).

    ``identity`` may be ``None`` (the planner infers from the digests). With a
    ``cache``, the sanitized plans are stored content-addressed on the exact
    corpus + identity + params, so a warm re-run rebuilds identical Profile
    objects — keeping the critique's ``profiles_key`` (and therefore its cached
    reads) stable. An unchanged sheet may also retain a prior revision's plan
    when the substantive identity and planner settings match. Conflicting prior
    snapshots, an unknown identity, or no overlapping sheets require authoring.
    """
    model = model or default_review_plan_model()
    if not any(sd.ok for sd in sheet_digests):
        return PlanResult(model_used=model, error="no readable sheets to plan against")

    user_text, _omitted = build_planner_user_text(identity, sheet_digests)

    cache_key = None
    binding_keys: list[str] = []
    if cache is not None:
        from .digest_cache import review_plan_cache_key

        cache_key = review_plan_cache_key(
            hashlib.sha256(user_text.encode("utf-8")).hexdigest(),
            _identity_hash(identity),
            model=model,
            prompt_version=PLANNER_PROMPT_VERSION,
            max_tokens=max_tokens,
            effort=effort,
            use_thinking=use_thinking,
            max_items=max_plan_items(),
        )
        binding_keys = _plan_binding_keys(
            identity, sheet_digests, sheet_keys, model=model, max_tokens=max_tokens,
            effort=effort, use_thinking=use_thinking,
        )
        cached_result = _cached_plan_result(cache.get(cache_key), model=model, identity=identity)
        if cached_result is not None:
            # Also seeds bindings from legacy exact-corpus entries without
            # invalidating existing critique caches or buying a fresh plan.
            _bind_plan(cache, binding_keys, cache_key)
            return cached_result
        prior_keys = set()
        for key in binding_keys:
            binding = get_stage_cache_entry(cache, key, stage="review_plan_binding")
            if binding is not None and isinstance(binding.get("plan_key"), str):
                prior_keys.add(binding["plan_key"])
        if len(prior_keys) == 1:
            prior_key = next(iter(prior_keys))
            cached_result = _cached_plan_result(
                cache.get(prior_key), model=model, identity=identity, reused=True,
            )
            if cached_result is not None:
                # New/reissued sheets join the same snapshot. Do not store it
                # under this run's exact-corpus key: it was authored previously.
                _bind_plan(cache, binding_keys, prior_key)
                return cached_result

    if client is None:
        from .client import get_client as _get_client

        client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": PLANNER_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
    }
    if use_thinking and model_supports_adaptive_thinking(model):
        kwargs["thinking"] = {"type": "adaptive"}
    if effort and model_supports_effort(model):
        kwargs["output_config"] = {"effort": effort}

    attempt = 0
    while True:
        try:
            resp = stream_message(client, kwargs)
            break
        except Exception as exc:  # noqa: BLE001 - additive stage, never fatal
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            return PlanResult(model_used=model, error=_clean_error(exc))

    text = _message_text(resp)
    in_tok, out_tok = _message_usage(resp)
    obj = parse_planner_text(text)
    if obj is None:
        return PlanResult(
            input_tokens=in_tok, output_tokens=out_tok, model_used=model,
            error="planner reply carried no parseable plans block",
        )
    plans, dropped = sanitize_plans(obj)
    profiles = profiles_from_plans(plans)
    if not profiles:
        return PlanResult(
            input_tokens=in_tok, output_tokens=out_tok, model_used=model,
            dropped_items=dropped,
            error="planner reply contained no usable plan items",
        )
    result = PlanResult(
        profiles=profiles,
        markdown=render_plan_markdown(profiles, model=model, identity=identity),
        input_tokens=in_tok, output_tokens=out_tok, model_used=model,
        dropped_items=dropped,
    )
    if cache is not None and cache_key is not None:
        # Store the SANITIZED plans — what a warm run must rebuild verbatim so
        # the critique profiles_key stays byte-identical across runs.
        cache.put(cache_key, {
            "plans": [
                {
                    "discipline": p.discipline,
                    "title": p.title,
                    "items": [
                        {"text": it.text, "severity": it.severity, "refs": list(it.refs)}
                        for it in p.items
                    ],
                }
                for p in plans
            ],
            "model": model,
            "prompt_version": PLANNER_PROMPT_VERSION,
            "dropped_items": dropped,
        })
        _bind_plan(cache, binding_keys, cache_key)
    return result
