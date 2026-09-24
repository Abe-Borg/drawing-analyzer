"""Prose harvest (Part III, §17) — the legacy channel's carry-through guarantee.

The digest's prose **Coordination** and **Conflict** sections (and the
cross-sheet **synthesis** prose) predate the structured-findings contract, and a
downstream consumer already relies on them (I-2). Part III's directive is that
nothing QC-flavored may live *only* in prose — every prose item must reach the
findings ledger and therefore the reviewed PDF. Three layered mechanisms:

1. **Prompt coupling** (in :mod:`digest`): the findings instruction tells the
   model every Coordination/Conflict prose item must also appear in the JSON
   block. Soft guarantee only — hence 2 and 3.
2. **Deterministic split + match** (free): the prose sections are split into
   discrete items and fuzzy-matched (token overlap ≥ 0.7) against the same-sheet
   ledger entries. A match tags the existing entry with the prose provenance,
   and only a candidate whose critical signature agrees with the item's can be
   one (remediation WP-09.2, N10): "Provide 4 inch drain" is not "Provide 6
   inch drain", however much of the wording they share.
3. **Structuring fallback** (one small model call per straggler): an unmatched
   item plus the sheet's text layer → one §4.1 finding (verbatim
   ``source_quote`` or ``""``). If even that fails, a **degraded entry** is
   ingested — the prose item verbatim, ``anchor_hint="SHEET"`` — which still
   reaches the PDF as a margin callout.

**Invariant: no prose QC item may fail to produce a ledger entry.**

Synthesis prose is harvested for **conflict statements only**: items naming at
least one in-set sheet, anchored on the first named sheet and dual-anchored
(``also_on``) when a second sheet is named. Per-sheet **Focus findings** sections
are harvested only behind ``focus_findings_to_markups`` (default OFF — a focus
is often not QC).

Section **filler** ("No conflicts noted on this sheet.") and synthesis
**assurances** ("No conflicts were found between M-101 and P-101.") are not QC
items (remediation WP-09.1: B11, N11). One closed vocabulary recognizes both,
so neither costs a structuring call or becomes a ledger entry, and each is
counted observationally (``filtered``, ``assurances``). Anything outside the
vocabulary is kept, the safe direction.

Every enumerated item ends with exactly one recorded outcome (remediation
WP-09.2: :class:`ProseItemOutcome`, ``HarvestResult.outcomes``): matched,
structured, degraded, set-level or missing, with the structuring call it cost,
whether its finding folded into an existing entry, and how many candidates the
signature veto refused. What the filler and assurance rules suppress is
counted per channel, focus filler included (``filtered_focus``).

The prose itself is never modified — it is *mirrored* into the ledger, not
moved (I-2). PDF-engine-free (I-5); real-time only (stragglers are few).
"""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .core.api_config import (
    HARVEST_OUTPUT_CAP,
    MODEL_SONNET_5,
    PHASE_HARVEST,
    apply_effort_config,
    apply_thinking_config,
    call_with_refusal_fallback,
    effort_config_for,
    phase_output_cap,
    thinking_config_for,
)
from .core.structured_outputs import StructuredOutputsGate, attach_format
from .critique import _token_overlap, critical_signature, signature_conflicts
from .diagnostics import get_logger
from .digest import (
    _FINDING_SEVERITIES,
    _MODEL_FINDING_CATEGORIES,
    _clean_error,
    _is_transient_error,
    _message_text,
    _message_usage,
    _retry_backoff_seconds,
    _tolerant_json_object,
    _validate_finding_item,
    scan_structured_blocks,
)
from .html_report import classify_section, split_into_sections
from .ledger import Ledger
from .models import (
    ConflictLeg,
    Finding,
    ProseItem,
    SheetRef,
    Verification,
    compute_prose_item_id,
    source_page_key,
)
from .stage_cache import (
    get_stage_cache_entry,
    put_stage_cache_entry,
    stage_cache_key,
)

# The sheet_id label a set-level synthesis conflict carries (it belongs to no
# single source sheet). Kept short for the review-notes row / report section.
SET_LEVEL_SHEET_LABEL = "(set-level)"

_log = get_logger()

# Mechanism 2's match threshold (§17): token overlap ≥ 0.7 against a same-sheet
# ledger entry's text or quote. It was never evaluated against labelled data
# (U11) and is NOT changed by remediation WP-09.2, which added the signature
# veto beside it (``_match_entry``) and the labelled evidence for any later
# change (``tests/test_prose_paraphrase_corpus.py``: at 0.7, with the veto,
# how many same-claim pairs still match and how many different-claim pairs are
# still absorbed). Lower it only with that evidence, never to save calls.
_MATCH_OVERLAP = 0.7
# The structuring call (mechanism 3): small, low-effort, tolerant-parsed.
#
# The old 800-token cap paired with a comment claiming "thinking off" — but the
# request never set ``thinking`` at all, and on Opus 5 / Sonnet 5 an omitted key
# runs adaptive thinking rather than disabling it. Reasoning and answer shared
# 800 tokens, so a straggler that needed any thought at all came back empty and
# fell through to the degraded sheet-level entry. Thinking is now explicit and
# cheap (EFFORT_LOW, registered for PHASE_HARVEST) with an envelope that fits it.
DEFAULT_HARVEST_MAX_TOKENS = HARVEST_OUTPUT_CAP
DEFAULT_HARVEST_MAX_RETRIES = 2
# The sheet text layer sent with a structuring call (a straggler needs context,
# not the whole sheet).
_HARVEST_TEXT_CAP = 6_000
_HARVEST_CACHE_CONTRACT = 1
DEFAULT_HARVEST_WORKERS = 4
_HARVEST_WORKERS_ENV = "DRAWING_ANALYZER_HARVEST_WORKERS"


def _resolve_harvest_workers(max_workers: int | None, total: int) -> int:
    """Resolve bounded prose-call concurrency (argument, env, then default)."""
    if max_workers is None:
        raw = os.environ.get(_HARVEST_WORKERS_ENV)
        if raw and raw.strip():
            try:
                max_workers = int(raw.strip())
            except ValueError:
                max_workers = DEFAULT_HARVEST_WORKERS
        else:
            max_workers = DEFAULT_HARVEST_WORKERS
    return min(max(1, int(max_workers)), max(1, int(total)))

_LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-*+•]|\d+[.)])\s+(.*)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9(])")
# --------------------------------------------------------------------------- #
# Section filler and synthesis assurances (remediation WP-09.1: B11, N11)
# --------------------------------------------------------------------------- #
#
# One closed vocabulary, used in two anchored forms (the owner's rules):
#
# * ``_TRIVIAL_RE`` is section FILLER: a whole item made of listed words ("No
#   conflicts noted on this sheet.", "None apparent on this sheet.", "No
#   cross-discipline items noted for this sheet."). ``_split_items`` applies it,
#   the one filter site every channel shares, so filler reaches neither the
#   structuring call nor the degraded entry (plan WP-09 step 3).
# * ``_ASSURANCE_RE`` finds the SPANS of a synthesis statement that say a
#   conflict is absent ("no conflicts were found", "there are no
#   discrepancies"). A statement whose every conflict signal sits inside one,
#   and whose every other word is a listed frame word (``_FRAME_WORDS``), is an
#   assurance, not a conflict (``_is_assurance``, N11).
#
# Every word comes from a listed set; nothing guesses at content. An item that
# carries a tag, a number, a sheet id or any unlisted word is not filler; a
# conflict noun qualified by an unlisted word ("no duct conflicts were found")
# is not an assurance, and neither is an assurance beside any unlisted word ("…,
# yet M-101 lists 500 gpm"). Each refusal keeps the item: the safe direction
# (plan section 2.1), at the cost of a structuring call, as before. The same
# words decide which synthesis headings are mere labels (``_LABEL_RE``).
#
# The filler test is anchored at BOTH ends (P8 item 6). Anchored only at the
# start, it discarded every real finding that *opened* with one of these words,
# and an absence finding naturally opens that way:
#
#   "None of the sprinkler heads under the duct have clearance shown"
#   "No conflicts were resolved between M-101 and FP-101; both remain open"
#   "Nothing on this sheet shows the drain size for the 6 inch main"
#   "N/A per the mechanical schedule, but the FP drawings require a 4 inch drain"
#   "No issues flagged earlier are addressed by the revised riser diagram"
#
# Until WP-09.1 it allowed one qualifier after the noun and no modifier before
# it (B11), so the review's four strings passed it. Each cost a structuring
# call and, with no client or a failed call, became a medium sheet-level margin
# callout announcing that nothing was wrong.

# A hyphen, and the Unicode hyphens and dashes a model may type (U+2010-U+2014).
_DASH = r"[\-\u2010-\u2014]"

#: Words that may qualify the noun: "no <modifier> <modifier> <noun>".
_FILLER_MODIFIERS = (
    "other", "further", "additional", "new", "known", "obvious", "apparent",
    "significant", "major", "notable", "specific", "outstanding", "open",
    "remaining", "unresolved", "coordination", "discipline", "disciplinary",
    "trade", "design", "drawing", "sheet", "qc", "code",
    rf"cross{_DASH}?\s?(?:discipline|disciplinary|sheet)",
    rf"(?:inter|multi){_DASH}?(?:discipline|disciplinary)",
)
#: The conflict nouns. Each carries a ``_CONFLICT_SIGNALS`` stem, and every
#: stem with a noun form has one here (both pinned by
#: ``tests/test_prose_filler_and_assurances.py``).
_CONFLICT_NOUNS = (
    r"conflicts?", r"contradictions?", r"disagreements?", r"mismatch(?:es)?",
    r"discrepanc\w*", r"inconsistenc(?:y|ies)", r"divergences?",
)
#: The conflict adjectives of "nothing <adjective>".
_CONFLICT_ADJECTIVES = (
    "inconsistent", "conflicting", "contradictory", "divergent", "mismatched",
)
#: What section filler is about: the conflict nouns and these.
_FILLER_NOUNS = _CONFLICT_NOUNS + (
    r"issues?", r"items?", r"notes?", r"findings?", r"concerns?", r"comments?",
    r"problems?", r"clash(?:es)?", r"deficienc(?:y|ies)", r"errors?",
    r"observations?",
)
_AUXILIARIES = (
    "were", "was", "are", "is", r"ha(?:ve|s|d)\s+been", r"(?:could|can)\s+be",
)
#: What a reviewer did not find: "no conflicts [were] <detected>".
_DETECTED = (
    "noted", "found", "reported", "identified", "observed", "apparent",
    "detected", "seen", "evident", "flagged", r"exists?", r"remains?",
)
_DISCIPLINES = (
    "architectural", "structural", "mechanical", "electrical", "plumbing",
    rf"fire(?:\s|{_DASH})protection", "civil", "landscape",
    r"telecom(?:munications)?", "technology",
)
_DOCUMENTS = (
    r"disciplines?", r"trades?", r"sheets?", r"drawings?", r"plans?",
    r"schedules?", r"backgrounds?", "set",
)
_PLACES = ("sheet", "drawing", "page", "plan", "set", "discipline", "review")
#: A word that carries a digit, read one way only: the characters before its
#: first digit, that digit, the rest. Possessive, so a pattern that repeats it
#: can never re-split one word and backtrack exponentially (an ambiguous form
#: took minutes on "M-101 / " repeated in a heading).
_DIGIT_WORD = r"(?:[^\W\d]|[./-])*+\d[\w./-]*+"
#: A sheet id, or a tag shaped like one: it starts with a letter and carries a
#: digit (``M-101``, ``FP-101``, ``A1.01``). A measurement starts with its value
#: (``500``, ``6in``) and is never one.
_ID = rf"[^\W\d_]{_DIGIT_WORD}"
#: The only words an assurance may carry outside its spans: sheet ids,
#: discipline, document and place names, a few function words, "are
#: consistent", "at this time". Any other word keeps the statement, since it
#: may state the very conflict the assurance denies: a contrast ("but", "yet",
#: "nevertheless", "while"), a value, a component, a "not" (the Codex review of
#: WP-09.1: "No conflicts were found, yet M-101 lists 500 gpm and P-101 lists
#: 550 gpm." was dropped whole). A closed list, like the rest of this
#: vocabulary, so no list of contrast words has to be complete.
_FRAME_WORDS = (
    "the", "a", "an", "and", "or", "of", "on", "in", "at", "to", "for", "from",
    "with", "within", "between", "among", "across", "this", "these", "those",
    "any", "all", "both", "each", "its", "their", "other", "overall",
    "are", "is", "was", "were", "be", "been", r"appears?", r"seems?",
    "consistent", "coordinated", "aligned",
    "time", "present", "currently", "so", "far", "date", "fire", "protection",
) + _DISCIPLINES + _DOCUMENTS + _PLACES


def _alt(words: Iterable[str]) -> str:
    return "(?:" + "|".join(words) + ")"


# Up to two modifiers ("cross-sheet / cross-discipline" writes a slash between).
_MODIFIERS = rf"(?:{_alt(_FILLER_MODIFIERS)}(?:\s*/\s*|\s+)){{0,2}}"


def _no_phrase(nouns: str) -> str:
    """``no`` + up to two modifiers + a noun, optionally ``, / or / and`` another."""
    return (
        rf"no\s+{_MODIFIERS}{nouns}"
        rf"(?:\s*(?:,|/|\bor\b|\band\b)\s*{_MODIFIERS}{nouns})?"
    )


_AUX = _alt(_AUXILIARIES)
_SEEN = _alt(_DETECTED)
_FILLER_QUALIFIER = "|".join((
    rf"(?:{_AUX}\s+)?{_SEEN}",
    r"to\s+(?:report|note)",
    r"at\s+this\s+time|at\s+present|currently|so\s+far|to\s+date",
    rf"(?:on|for|in|within|from)\s+(?:this|the)\s+{_alt(_PLACES)}",
    r"(?:with|between|across|among|and)\s+(?:the\s+)?(?:other\s+)?"
    rf"(?:{_alt(_DISCIPLINES)}(?:\s+{_alt(_DOCUMENTS)})?|{_alt(_DOCUMENTS)})",
))
# Section filler, not findings (B11): the WHOLE item is an optional listed
# label ("Coordination items:"), the subject, then up to four listed
# qualifiers in any order.
_TRIVIAL_RE = re.compile(
    rf"^\W*(?:{_MODIFIERS}{_alt(_FILLER_NOUNS)}\W*?[:\u2013\u2014]\W*)?"
    r"(?:none|n/?a|nothing(?:\s+(?:further|else|more|additional|significant"
    r"|notable))?"
    rf"|{_no_phrase(_alt(_FILLER_NOUNS))})"
    rf"(?:[\s,;]+(?:{_FILLER_QUALIFIER})){{0,4}}\W*$",
    re.I,
)

# The conflict noun must be the head of its phrase: what follows it is the
# end, a punctuation mark, a preposition, a conjunction or the verb. So "no
# conflict resolution is shown" is not an assurance: its head is "resolution".
_HEAD_FOLLOWERS = (
    "between", "among", "across", "with", "on", "in", "within", "for", "at",
    "to", "from", "and", "or",
) + _AUXILIARIES + _DETECTED
_NO_CONFLICT = (
    _no_phrase(_alt(_CONFLICT_NOUNS))
    + rf"(?=\s*(?:[.,;:!?)]|$)|\s+{_alt(_HEAD_FOLLOWERS)}\b)"
)
# Between the noun and its verb, only a phrase of sheet ids, discipline names
# and a few listed words ("between M-101 and P-101", "between the fire
# protection and mechanical sheets"). An open phrase can swallow a clause:
# "No conflicts between M-101 and P-101 resolve the pump question and none
# were found on E-201" is not an assurance.
_PHRASE_WORD = (
    rf"(?:{_DIGIT_WORD}|the|and|or|of|on|in|any|both|these|those|this|its"
    rf"|their|other|{_alt(_DISCIPLINES)}|{_alt(_DOCUMENTS)})"
)
_PHRASE = (
    r"(?:\s+(?:between|among|across|with|on|in|within|for|from)"
    rf"(?:\s+{_PHRASE_WORD}){{1,8}}?)"
)
_ASSURANCE = "|".join((
    # "no conflicts [between M-101 and P-101] [were] found"
    rf"\b{_NO_CONFLICT}{_PHRASE}?(?:\s+{_AUX})?\s+{_SEEN}\b",
    # "nothing inconsistent [was found]"
    rf"\bnothing\s+(?:(?:else|further)\s+)?{_alt(_CONFLICT_ADJECTIVES)}\b"
    rf"(?:\s+{_AUX}\s+{_SEEN}\b)?",
    # "there are no conflicts"
    r"\bthere\s+(?:is|are|was|were|appears?\s+to\s+be|seems?\s+to\s+be)\s+"
    + _NO_CONFLICT,
    # "found no conflicts"
    r"\b(?:found|noted|identified|observed|detected|revealed|shows?|showed"
    r"|indicates?|indicated)\s+" + _NO_CONFLICT,
))
# A label naming a conflict ("Cross-sheet conflicts:") directly before an
# assurance belongs to it.
_ASSURANCE_RE = re.compile(
    rf"^\W*{_MODIFIERS}{_alt(_CONFLICT_NOUNS)}\W*?[:\u2013\u2014]\W*"
    rf"(?={_ASSURANCE})|{_ASSURANCE}",
    re.I,
)
_FRAME_TOKEN_RE = re.compile(rf"{_alt(_FRAME_WORDS)}|{_ID}", re.I)
# A word: starts and ends on a letter or digit, and may carry ' . / - inside
# (``doesn't``, ``M-101``, ``A1.01``); the punctuation around it is not a word.
_WORD_RE = re.compile(r"[^\W_](?:[\w'./-]*[^\W_])?")

# A synthesis heading is a LABEL when it names a section ("Cross-sheet /
# cross-discipline conflicts", "Conflicts between M-101 and P-101", "M-101 /
# P-101 discrepancies"). Any other heading says something ("M-101 conflicts with
# P-101.") and is an item of its own (the Codex review of WP-09.1: dropping
# every heading lost a conflict written as a whole-line bold sentence). A label
# is the noun phrase of the filler vocabulary without its "no": listed
# modifiers, adjectives and nouns, after an optional pair of sheet ids (or a
# single one with no "with" after it) and before listed qualifiers or sheet
# ids. A statement starts with its subject, so an unlisted word before the
# noun, or a single sheet id followed by "with" ("M-101 conflicts with P-101"),
# makes it one. An unlisted label is read as an item: noise, never a lost
# conflict.
_LABEL_ADJECTIVES = (
    "potential", "possible", "key", "critical", "primary", "identified",
    "stale", "tag", "schedule", "reference", "equipment", "dimensional",
    "detail",
) + _CONFLICT_ADJECTIVES
_LABEL_NOUNS = _FILLER_NOUNS + (
    r"references?", rf"cross{_DASH}?\s?references?", r"tags?", "coordination",
)
_IDS = rf"{_ID}(?:\s*(?:/|&|,|\band\b|\bor\b|\bvs\.?|\bversus\b)\s*{_ID})*+"
#: What a label may say it is: "Summary of conflicts", "Conflict review".
_LABEL_KINDS = (
    "summary", "review", "overview", "list", "log", "register", "table",
    "check",
)
_LABEL_PHRASE = (
    rf"{_MODIFIERS}(?:{_alt(_LABEL_ADJECTIVES)}\s+)?{_alt(_LABEL_NOUNS)}"
    rf"(?:\s+{_alt(_LABEL_KINDS)})?"
)
_LABEL_RE = re.compile(
    # An optional pair of sheet ids ("M-101 / P-101 ..."), or a single one when
    # no "with" follows: "FP-101 conflicts" names a section, "M-101 conflicts
    # with P-101" says something.
    rf"^\W*(?:{_ID}(?:\s*(?:/|&|,|\band\b|\bvs\.?|\bversus\b)\s*{_ID})++\s+"
    rf"|{_ID}\s+(?!.*\bwith\b))?"
    rf"(?:{_alt(_LABEL_KINDS)}\s+of\s+(?:the\s+)?)?"
    rf"{_LABEL_PHRASE}(?:\s*(?:,|/|&|\band\b|\bor\b)\s*{_LABEL_PHRASE}){{0,3}}"
    rf"(?:[\s,;]+(?:{_FILLER_QUALIFIER}"
    r"|requiring\s+(?:resolution|coordination|attention|action|review)"
    r"|to\s+(?:resolve|review|coordinate|address|confirm)"
    r"|during\s+(?:the\s+)?(?:review|coordination)"
    r"|\(\s*(?:none|n/?a|nil)\s*\)"
    rf"|(?:between|among|across|with|on|in|for|of|from)\s+{_IDS}"
    rf"|\(\s*{_IDS}\s*\))){{0,4}}\W*$",
    re.I,
)

# A floor low enough to keep a terse real finding. At 20 it discarded
# "Drain is undersized" (19), "6 inch drain wrong" (18), "VAV-3 blocks duct" (17)
# and "No clearance" (12); the filler test above, not a length guess, is what
# removes section filler, so this only has to stop single-token fragments.
_MIN_ITEM_CHARS = 8

# Synthesis harvest keeps conflict statements only (§17): an item must carry one
# of these signals (mirrors the report's conflict classification keywords) and
# carry it outside an assurance (N11, ``_is_assurance``).
_CONFLICT_SIGNALS = (
    "conflict", "contradic", "disagree", "mismatch", "discrepan", "inconsist",
    "differs", "diverg", "does not match", "doesn't match", "stale",
)


def harvest_model() -> str:
    """The structuring-call model (``DRAWING_ANALYZER_HARVEST_MODEL``, else Sonnet 5).

    Turning one prose sentence into a structured ``Finding`` is formatting, not
    judgment: the item has already been found, and the host re-binds it to its
    sheet afterwards. Sonnet 5 covers it at a fraction of the flagship's cost.
    """
    return os.environ.get("DRAWING_ANALYZER_HARVEST_MODEL") or MODEL_SONNET_5


# --------------------------------------------------------------------------- #
# Item extraction (pure)
# --------------------------------------------------------------------------- #


def _split_items(body: str) -> "tuple[list[str], list[str]]":
    """Discrete items from one section body (list markers, else sentences),
    and the filler removed from them.

    The ONE filter site (plan WP-09 steps 1-3): digest, focus and synthesis
    prose all pass through it, so an item it removes (a fragment under
    ``_MIN_ITEM_CHARS``, or whole-item filler, ``_TRIVIAL_RE``) reaches neither
    the structuring call nor the degraded entry.
    """
    lines = (body or "").replace("\r\n", "\n").split("\n")
    items: list[str] = []
    current: list[str] = []
    saw_marker = False
    for line in lines:
        m = _LIST_ITEM_RE.match(line)
        if m:
            saw_marker = True
            if current:
                items.append(" ".join(current).strip())
            current = [m.group(2).strip()]
        elif line.strip() and current:
            current.append(line.strip())      # continuation of the current item
        elif not line.strip() and current:
            items.append(" ".join(current).strip())
            current = []
    if current:
        items.append(" ".join(current).strip())
    if not saw_marker:
        text = " ".join(l.strip() for l in lines if l.strip())
        items = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    kept: list[str] = []
    removed: list[str] = []
    for item in items:
        if len(item) < _MIN_ITEM_CHARS or _TRIVIAL_RE.match(item):
            removed.append(item)
        else:
            kept.append(item)
    return kept, removed


def extract_prose_items(digest_text: str) -> list[tuple[str, str]]:
    """The digest's Coordination/Conflict prose items → ``(source_tag, item)``.

    Sections are located with the **same** splitter and classifier the HTML
    report's "⚠ Issues only" filter uses, so the harvest covers exactly the
    prose the report already treats as QC.
    """
    out: list[tuple[str, str]] = []
    for header, body in split_into_sections(digest_text or ""):
        category = classify_section(header)
        if category not in ("coordination", "conflict"):
            continue
        tag = f"digest_prose_{category}"
        out.extend((tag, item) for item in _split_items(body)[0])
    return out


def count_filtered_prose_lines(digest_text: str) -> int:
    """How many Coordination/Conflict prose lines the filter removed (P8 item 6).

    Purely **observational** — the same contract as WP-02 §7.2's cross-QC discard
    counters. It feeds the harvest accounting so a run can state how much the
    filler/length filter took, and it deliberately feeds neither ``missing``
    nor ``complete``: a line this filter removes is section filler, not a finding
    that went astray, so counting it as a loss would make every clean run
    incomplete. Since remediation WP-09.1 (B11) that includes filler with
    repeated qualifiers or a listed modifier ("No conflicts noted on this
    sheet.", "No cross-discipline items noted for this sheet."), which used to
    pass the filter. Synthesis assurances are counted apart, by
    :func:`count_synthesis_assurances`.

    It exists because the reconcile in :func:`harvest_prose_findings` builds
    ``expected`` from the items that already **survived** the filter, so a dropped
    line never entered the count, ``missing`` read 0 and ``complete`` returned True
    over a real loss. That is precisely what let the unanchored boilerplate regex
    discard genuine findings unnoticed. Routed through the same
    :func:`_split_items` as the harvest, so the two can never disagree about what
    "filtered" means.
    """
    return sum(_filtered_prose_lines_by_channel(digest_text).values())


def _filtered_prose_lines_by_channel(digest_text: str) -> dict[str, int]:
    """:func:`count_filtered_prose_lines`, split by the channel each line's
    section feeds (``digest_prose_coordination`` / ``digest_prose_conflict``),
    for the per-channel table (remediation WP-09.2)."""
    out: dict[str, int] = {}
    for header, body in split_into_sections(digest_text or ""):
        category = classify_section(header)
        if category not in ("coordination", "conflict"):
            continue
        removed = len(_split_items(body)[1])
        if removed:
            tag = f"digest_prose_{category}"
            out[tag] = out.get(tag, 0) + removed
    return out


# The body the focus addendum asks for when a sheet has nothing for the focus
# (``digest._FOCUS_ADDENDUM_TEMPLATE``); such a section is never harvested.
_NOTHING_RELEVANT_TO_THE_FOCUS = "nothing relevant to the focus"


def _focus_split(digest_text: str) -> "tuple[list[str], int]":
    """The Focus-findings items, and how many lines were suppressed as filler.

    Suppressed: what ``_split_items`` removes from a focus section, and every
    item of a section whose body says there is nothing relevant to the focus.
    One helper for :func:`extract_focus_items` and
    :func:`count_filtered_focus_lines`, so they cannot disagree.
    """
    items: list[str] = []
    suppressed = 0
    for header, body in split_into_sections(digest_text or ""):
        if classify_section(header) != "focus":
            continue
        kept, removed = _split_items(body)
        if _NOTHING_RELEVANT_TO_THE_FOCUS in (body or "").lower():
            suppressed += len(kept) + len(removed)
            continue
        items.extend(kept)
        suppressed += len(removed)
    return items, suppressed


def extract_focus_items(digest_text: str) -> list[str]:
    """The digest's per-sheet Focus-findings prose items (opt-in harvest)."""
    return _focus_split(digest_text)[0]


def count_filtered_focus_lines(digest_text: str) -> int:
    """How many Focus-findings lines were suppressed as filler (remediation WP-09.2).

    The lines ``_split_items`` removes from a focus section ("None noted.") and
    the items of a section whose body says "Nothing relevant to the focus on
    this sheet." (the focus addendum's own words for an empty answer). They
    were counted nowhere before. Counted whether or not the focus harvest is
    on (``focus_findings_to_markups``): a suppressed line is filler either way,
    while ``excluded_focus`` counts the real focus items the harvest leaves
    out. The contract of :func:`count_filtered_prose_lines`: purely
    **observational**, it feeds neither ``missing`` nor ``complete``.
    """
    return _focus_split(digest_text)[1]


def _signal_spans(low: str) -> list[tuple[int, int]]:
    """Where each ``_CONFLICT_SIGNALS`` stem occurs in lowercased ``low``."""
    spans: list[tuple[int, int]] = []
    for sig in _CONFLICT_SIGNALS:
        start = 0
        while (pos := low.find(sig, start)) >= 0:
            spans.append((pos, pos + len(sig)))
            start = pos + 1
    return spans


def _has_conflict_signal(item: str) -> bool:
    low = item.lower()
    return any(sig in low for sig in _CONFLICT_SIGNALS)


def _is_assurance(item: str) -> bool:
    """Whether ``item`` only says that a conflict is absent (N11; the owner's rule).

    True when the item carries a conflict signal, every signal it carries sits
    inside an ``_ASSURANCE_RE`` span, and every word outside those spans is a
    listed frame word (``_FRAME_WORDS``: sheet ids, discipline and document
    names, a few function words). So "No conflicts were found between M-101
    and P-101." is an assurance, and these are not: "No conflicts were
    resolved between M-101 and FP-101; both remain open" (resolving is not a
    detection word), "X conflicts with Y; no other conflicts were found" (the
    first signal sits outside), "does not match" (no assurance form), "No
    conflicts were found, but M-101 shows 500 gpm and P-101 shows 550 gpm." and
    "..., yet M-101 lists 500 gpm ..." (unlisted words: a contrast, values).
    """
    low = item.lower()
    signals = _signal_spans(low)
    if not signals:
        return False
    spans = [m.span() for m in _ASSURANCE_RE.finditer(low)]
    starts = [start for start, _end in spans]
    for start, end in signals:
        # Matches never overlap, so only the last span that starts at or
        # before the signal can hold it.
        i = bisect.bisect_right(starts, start) - 1
        if i < 0 or spans[i][1] < end:
            return False
    outside: list[str] = []
    previous = 0
    for start, end in spans:
        outside.append(low[previous:start])
        previous = end
    outside.append(low[previous:])
    return all(
        _FRAME_TOKEN_RE.fullmatch(word)
        for word in _WORD_RE.findall(" ".join(outside))
    )


def _is_label(header: str) -> bool:
    """Whether a synthesis heading names a section rather than saying something."""
    return bool(_LABEL_RE.match(header or ""))


def _synthesis_statements(synthesis_text: str) -> "tuple[list[str], int]":
    """The synthesis's conflict statements, and how many assurances it held.

    Items are split per section with the report's ``split_into_sections``
    (read, not changed), so a section heading never joins an item (N31): glued
    to the previous bullet, a "Cross-sheet conflicts" heading became a conflict
    of its own, and in paragraph layouts the whole run was one item that no
    assurance rule could read. A heading that is not a label (``_is_label``) is
    an item of its own, before its section's items, so a conflict written as a
    whole-line bold sentence ("**M-101 conflicts with P-101.**") is still read
    (the Codex review of WP-09.1). Each section body goes through
    ``_split_items``, the one filter site, and so does such a heading. A
    statement is kept when it carries a conflict signal and is not an
    assurance (``_is_assurance``). Counted as assurances: filler that names a
    conflict ("No conflicts noted.") and every statement ``_is_assurance``
    drops. Both extractors and the count go through this one helper, so they
    cannot disagree.
    """
    statements: list[str] = []
    assurances = 0
    for header, body in split_into_sections(synthesis_text or ""):
        kept, removed = _split_items(body)
        if header and not _is_label(header):
            heading_kept, heading_removed = _split_items(header)
            kept = heading_kept + kept
            removed = heading_removed + removed
        assurances += sum(
            1 for item in removed
            if _TRIVIAL_RE.match(item) and _has_conflict_signal(item)
        )
        for item in kept:
            if not _has_conflict_signal(item):
                continue
            if _is_assurance(item):
                assurances += 1
            else:
                statements.append(item)
    return statements, assurances


def extract_synthesis_conflicts(
    synthesis_text: str, sheet_ids: Iterable[str]
) -> list[tuple[str, list[str]]]:
    """Conflict statements from the synthesis prose → ``(item, named_sheet_ids)``.

    Keeps only items that carry a conflict signal outside an assurance (N11)
    AND name at least one in-set sheet id (order of ids = order of first
    mention, so the first is the primary anchor sheet and the second becomes
    the ``also_on`` leg). Items naming no resolvable sheet are skipped (logged
    by the caller) — a synthesis conflict with no sheet has nowhere on the PDF
    to live. "No conflicts were found between M-101 and P-101." names two
    sheets and is still not a conflict (:func:`_synthesis_statements`).
    """
    ids = sorted({s.upper() for s in sheet_ids if s}, key=lambda s: (-len(s), s))
    if not ids or not (synthesis_text or "").strip():
        return []
    out: list[tuple[str, list[str]]] = []
    for item in _synthesis_statements(synthesis_text)[0]:
        mentioned = _id_mentions(item.upper(), ids)
        if not mentioned:
            continue
        out.append((item, [sid for _pos, sid in sorted(mentioned)]))
    return out


def extract_set_level_synthesis_conflicts(
    synthesis_text: str, sheet_ids: Iterable[str]
) -> list[str]:
    """Synthesis conflict statements that name **no** resolvable in-set sheet (§14.8).

    The complement of :func:`extract_synthesis_conflicts`: same statements
    (a conflict signal outside an assurance, N11), but these items reference
    no sheet the set contains, so they belong to no single source. Instead of
    being dropped (the old behavior — a real conflict silently lost), they
    become **set-level** findings written to the deterministic
    ``Drawing_Set_Review_Notes.pdf``. An assurance ("The sheets are consistent;
    no conflicts were identified at this time.") is not one. Returns the
    verbatim items.
    """
    ids = sorted({s.upper() for s in sheet_ids if s}, key=lambda s: (-len(s), s))
    if not (synthesis_text or "").strip():
        return []
    out: list[str] = []
    for item in _synthesis_statements(synthesis_text)[0]:
        if ids and _id_mentions(item.upper(), ids):
            continue                 # names an in-set sheet → handled as SOURCE-scoped
        out.append(item)
    return out


def count_synthesis_assurances(synthesis_text: str) -> int:
    """How many synthesis statements only said a conflict is absent (N11).

    "No conflicts were found between M-101 and P-101.", "No conflicts noted."
    and the like: statements that carry a conflict signal only inside an
    assurance, so the harvest does not take them as conflicts. The contract of
    :func:`count_filtered_prose_lines`: purely **observational**, it feeds the
    accounting (``HarvestResult.assurances``) and neither ``missing`` nor
    ``complete``, because an assurance is not a finding that went astray. It
    exists so a rule that drops a real conflict can be seen in the manifest.
    """
    return _synthesis_statements(synthesis_text)[1]


# Characters that can continue a drawing id past a candidate match: "A-1"
# followed by ".1" is detail id A-1.1, not sheet A-1. A slash is deliberately
# NOT here — "P-1/P-2" names both sheets and detail-style "5/A-3" genuinely
# lives on sheet A-3.
_ID_CONNECTORS = ".-"


def _extends_id(text: str, index: int, step: int) -> bool:
    """Whether ``text[index]`` continues a larger id in direction ``step`` —
    alphanumeric, or a ``.``/``-`` connector with an alphanumeric beyond it
    (``A-1.1``, ``A-1-1``). A connector with nothing alphanumeric past it is
    sentence punctuation, not a continuation (``"… conflict on A-1."``)."""
    if index < 0 or index >= len(text):
        return False
    ch = text[index]
    if ch.isalnum():
        return True
    if ch in _ID_CONNECTORS:
        far = index + step
        return 0 <= far < len(text) and text[far].isalnum()
    return False


def _bounded_occurrences(text: str, sid: str) -> list[int]:
    """Start offsets where ``sid`` occurs as a whole id — ``A-1`` matches in
    ``"SEE A-1."`` but not inside ``A-10``, ``A-1.1``, or ``2A-15``."""
    out: list[int] = []
    start = 0
    while (pos := text.find(sid, start)) >= 0:
        if not _extends_id(text, pos - 1, -1) and not _extends_id(
            text, pos + len(sid), 1
        ):
            out.append(pos)
        start = pos + 1
    return out


def _id_mentions(text: str, ids: list[str]) -> list[tuple[int, str]]:
    """First genuine mention of each in-set sheet id, as ``(offset, id)``.

    Boundary-aware (``_extends_id``), and a shorter id additionally never
    counts inside a longer in-set id's mention: longer ids — ``ids`` arrives
    longest-first — claim their spans and shorter ids only match outside
    them. The claim pass backs up the boundary check for id alphabets the
    connector list doesn't cover (say a set holding both ``A-1`` and
    ``A-1 EAST``). Without all this, a set holding both ``A-1`` and ``A-10``
    would read a mention of ``A-10`` as naming ``A-1`` too and cloud a sheet
    the prose never named.
    """
    claimed: list[tuple[int, int]] = []
    mentioned: list[tuple[int, str]] = []
    for sid in ids:
        occurrences = _bounded_occurrences(text, sid)
        free = [
            p for p in occurrences
            if not any(c0 <= p and p + len(sid) <= c1 for c0, c1 in claimed)
        ]
        if free:
            mentioned.append((free[0], sid))
        claimed.extend((p, p + len(sid)) for p in occurrences)
    return mentioned


# --------------------------------------------------------------------------- #
# Mechanism 2 — match against the ledger (free)
# --------------------------------------------------------------------------- #


def _match_score(item: str, entry: Finding) -> float:
    """Mechanism 2's textual score: the item's token overlap with the entry's
    text or its quote, whichever is higher (``critique._token_overlap``)."""
    return max(
        _token_overlap(item, entry.text),
        _token_overlap(item, entry.source_quote or ""),
    )


def _veto_axes(
    item: str, entry: Finding, also_on: Iterable[ConflictLeg] = ()
) -> list[str]:
    """The critical axes on which a prose item's claim conflicts with an entry's.

    Remediation WP-09.2 (N10): the ONE rule, ``critique.signature_conflicts``
    over ``critique.critical_signature``, never a second copy of it. What the
    rule is given is the owner's decision, "text against text":

    * the item is signed from its own text and its synthesis legs
      (``also_on``, which feed ``critical_signature["leg_targets"]``);
    * the entry is signed from its text, quote, supporting quotes and legs,
      with its sheet-level placement (``anchor_hint``) set aside.

    ``critique._is_absence`` reads ``anchor_hint == "SHEET"`` as an absence.
    A placement says where a mark goes, not what the finding claims, and a
    prose item has no placement, so polarity is read from both texts. Signing
    the item with the entry's placement instead turns the axis off against
    every SHEET entry: "Isolation valve is shown ..." then joined a degraded
    "Isolation valve is not shown ..." entry. Signing the item as a bare text
    against the placement-aware entry refuses an item's own quote-less twin (5
    of the suite's 17 matches) and bills a structuring call for a
    restatement. Recorded limit: a SHEET absence written with no absence word
    ("Isolation valve at the pump discharge.") reads as presence, so a
    presence item still joins it. The ledger's own merges keep reading SHEET
    as an absence; that reading is not changed here.
    """
    probe = Finding(
        sheet_id=entry.sheet_id,
        source_name=entry.source_name,
        source_id=entry.source_id,
        page_index=entry.page_index,
        category=entry.category,
        severity=entry.severity,
        text=item,
        also_on=list(also_on or ()),
    )
    unplaced = copy.copy(entry)          # never mutate the live ledger entry
    unplaced.anchor_hint = ""
    return signature_conflicts(critical_signature(probe), critical_signature(unplaced))


def _match_entry(
    item: str,
    entries: list[Finding],
    *,
    also_on: Iterable[ConflictLeg] = (),
    refused: "list[Finding] | None" = None,
) -> Finding | None:
    """The same-sheet ledger entry the prose item restates, if any.

    A candidate is an entry whose ``_match_score`` reaches ``_MATCH_OVERLAP``.
    Since remediation WP-09.2 (N10) a candidate whose critical signature
    conflicts with the item's is refused (``_veto_axes``): token overlap is
    blind to a changed value, tag or polarity, so "Provide 4 inch drain at
    column line 4." (0.857) was absorbed into "... 6 inch ..." and the 4 inch
    claim reached no ledger entry. Candidates are tried best score first, ties
    in ledger order (the old rule kept the first entry at the best score), and
    the first compatible one wins: the veto only removes incompatible entries
    from the pool (the owner's rule), so a refused best candidate does not
    stop a lower compatible one at or above the threshold. An item with no
    compatible candidate is a straggler, structured or degraded like any
    other, and the ledger's own rule then decides whether its finding folds.

    Only candidates are signed (plan section 2 rule 14), so an item with none
    pays nothing for the veto. Both callers read this one function: the
    free-match path, which passes ``refused`` to learn how many candidates the
    veto turned away, and ``harvest_prose``'s ``active_chain_count``, which
    decides whether the parallel path runs; so the two always agree.
    """
    legs = list(also_on or ())
    candidates: list[tuple[float, int, Finding]] = []
    for index, entry in enumerate(entries):
        score = _match_score(item, entry)
        if score >= _MATCH_OVERLAP:
            candidates.append((-score, index, entry))
    candidates.sort(key=lambda candidate: candidate[:2])
    for _negative_score, _index, entry in candidates:
        if not _veto_axes(item, entry, legs):
            return entry
        if refused is not None:
            refused.append(entry)
    return None


# --------------------------------------------------------------------------- #
# Mechanism 3 — the structuring call, with the degraded fallback
# --------------------------------------------------------------------------- #

HARVEST_SYSTEM_PROMPT = """\
You convert ONE prose item from a construction-drawing QC review into exactly \
one machine-readable finding. You are given the item and the sheet's verbatim \
text layer. Output ONLY a fenced code block labeled json containing a single \
object with: sheet_id; category (one of code, conflict, coordination, \
question); severity (one of high, medium, low); text (the finding, at most two \
sentences); source_quote (COPY VERBATIM a supporting string from the SHEET TEXT \
LAYER — exact characters — or "" if no on-sheet string supports it); tile \
(null); refs (an array, usually empty). Never invent quotes, tags, or values."""

# Structured-outputs variant of the harvest prompt (opt-in,
# ``DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS``). ONE substitution on the
# fenced prompt, never a second copy — the field list, the verbatim-quote rule
# and the "never invent" rule have exactly one author. Asserted at import so a
# prompt edit that breaks the substitution fails the import, not a live run.
_HARVEST_FENCE_SENTENCE = (
    "Output ONLY a fenced code block labeled json containing a single object with: "
)
_HARVEST_FENCE_REPLACEMENT = "Output ONLY a single JSON object with: "
HARVEST_STRUCTURED_SYSTEM_PROMPT = HARVEST_SYSTEM_PROMPT.replace(
    _HARVEST_FENCE_SENTENCE, _HARVEST_FENCE_REPLACEMENT, 1
)
assert HARVEST_STRUCTURED_SYSTEM_PROMPT != HARVEST_SYSTEM_PROMPT, (
    "harvest fence sentence no longer matches the system prompt"
)
assert "fenced code block" not in HARVEST_STRUCTURED_SYSTEM_PROMPT, (
    "structured harvest prompt still asks for a fenced block"
)

#: The single-finding object the harvest asks for, as a JSON schema for
#: ``output_config.format``. Mirrors the prompt's field list one-for-one:
#: ``additionalProperties: false`` means a field the prompt names must be here
#: or the grammar forbids what the prose asks for. The category and severity
#: enums are the same frozensets the host validator checks against
#: (``digest._validate_finding_item``), sorted so the schema — and the cache
#: key that hashes it — is deterministic (I-7). ``tile`` is pinned to ``null``
#: exactly as the prompt says; the ``at most two sentences`` cap on ``text``
#: stays prose (``maxLength`` is rejected by the schema compiler).
HARVEST_FINDING_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "sheet_id": {"type": "string"},
        "category": {"type": "string", "enum": sorted(_MODEL_FINDING_CATEGORIES)},
        "severity": {"type": "string", "enum": sorted(_FINDING_SEVERITIES)},
        "text": {"type": "string"},
        "source_quote": {"type": "string"},
        "tile": {"type": "null"},
        "refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["sheet_id", "category", "severity", "text", "source_quote", "tile", "refs"],
    "additionalProperties": False,
}

# The structured half of the item cache identity. Folded into the key ONLY
# when the request carries the schema (see ``_structure_item``), so a fenced
# run's key is byte-identical to every key written before this existed, and
# editing the structured prompt or the schema re-structures only the
# structured entries (I-6).
HARVEST_STRUCTURED_PROMPT_VERSION = hashlib.sha256(
    "\x00".join(
        (HARVEST_STRUCTURED_SYSTEM_PROMPT, json.dumps(HARVEST_FINDING_SCHEMA, sort_keys=True))
    ).encode("utf-8")
).hexdigest()[:16]

# Its own latch: this is a text-only Sonnet 5 call, and a rejection on the
# critique's 37-image vision request says nothing about it (nor the reverse).
STRUCTURED_OUTPUTS = StructuredOutputsGate(
    "prose_harvest", "DRAWING_ANALYZER_HARVEST_STRUCTURED_OUTPUTS"
)


def harvest_structured_outputs_enabled(model: str) -> bool:
    """Whether a structuring call should carry ``output_config.format``.

    Three gates (env opt-in, model capability, the process latch) — see
    :class:`drawing_analyzer.core.structured_outputs.StructuredOutputsGate`.
    Off by default until the live canary
    (``tests/test_live_api_canary.py::test_live_harvest_under_output_config_format``)
    has passed on your account; text-only, so the lowest-risk stage to flip.
    """
    return STRUCTURED_OUTPUTS.enabled(model)


def harvest_system_prompt(*, structured: bool = False) -> str:
    """The fenced prompt by default; the fence-free variant for a schema-bound request."""
    return HARVEST_STRUCTURED_SYSTEM_PROMPT if structured else HARVEST_SYSTEM_PROMPT


def _structure_item(
    item: str,
    category_hint: str,
    sheet_text: str,
    ref: SheetRef,
    sheet_id: str,
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
    cache: Any = None,
) -> tuple[Finding | None, int, int, bool, bool]:
    """Structure one item and report token, cache-hit, and live-call telemetry."""
    text = (sheet_text or "")[:_HARVEST_TEXT_CAP]
    user = (
        f"PROSE QC ITEM (from the sheet's {category_hint} section):\n{item}\n\n"
        f"SHEET ID: {sheet_id}\n\n"
        f"SHEET TEXT LAYER (verbatim):\n{text or '[none]'}\n\n"
        "Convert the item into the single finding object now."
    )
    # Resolved ONCE per item and threaded to the key, the request and the
    # parser — never re-derived after the request is sent (the latch can flip
    # in between, and a reply must be parsed under the contract it was asked
    # for).
    structured = harvest_structured_outputs_enabled(model)

    def _cache_key(structured_now: bool) -> str:
        params: dict[str, Any] = {
            "contract": _HARVEST_CACHE_CONTRACT,
            "max_tokens": phase_output_cap(PHASE_HARVEST, model=model),
            "text_cap": _HARVEST_TEXT_CAP,
            # Thinking/effort change the structured result, so they key it.
            "thinking": thinking_config_for(model=model, phase=PHASE_HARVEST),
            "effort": effort_config_for(model=model, phase=PHASE_HARVEST),
        }
        if structured_now:
            # Only when the request carries the schema: a fenced key stays
            # byte-identical to every key written before the feature (I-6).
            params["structured"] = HARVEST_STRUCTURED_PROMPT_VERSION
        return stage_cache_key(
            "prose_harvest_item",
            model=model,
            prompt=HARVEST_SYSTEM_PROMPT,
            inputs={
                "user_text": user,
                # Host binding is part of the durable result even though the
                # model sees only the display sheet id above.
                "source_name": ref.source_name,
                "source_id": ref.source_id,
                "page_index": ref.page_index,
            },
            params=params,
        )

    cache_key = _cache_key(structured)
    cached_entry = get_stage_cache_entry(
        cache, cache_key, stage="prose_harvest_item"
    )
    if cached_entry is not None and isinstance(cached_entry.get("finding"), dict):
        try:
            cached_finding = Finding.from_dict(cached_entry["finding"])
        except (TypeError, ValueError):
            cached_finding = None
        if (
            cached_finding is not None
            and cached_finding.source_name == ref.source_name
            and cached_finding.source_id == ref.source_id
            and cached_finding.page_index == ref.page_index
        ):
            return cached_finding, 0, 0, True, False

    if client is None:
        return None, 0, 0, False, False

    def _params(structured_now: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": phase_output_cap(PHASE_HARVEST, model=model),
            "system": harvest_system_prompt(structured=structured_now),
            "messages": [{"role": "user", "content": user}],
        }
        # Explicit, never implicit: an omitted ``thinking`` key runs adaptive
        # on the current models. Low effort is the cheap setting that keeps
        # it on.
        apply_thinking_config(kwargs, model=model, phase=PHASE_HARVEST)
        apply_effort_config(kwargs, model=model, phase=PHASE_HARVEST)
        if structured_now:
            # Merged into ``output_config``, never assigned over it: ``format``
            # shares that dict with ``effort`` (see ``attach_format``).
            attach_format(kwargs, HARVEST_FINDING_SCHEMA)
        return kwargs

    # Re-checked at send time: another item's rejection may have latched the
    # feature off since ``structured`` was resolved above. Sending plain now
    # saves a guaranteed 400, and the store key below follows this final value.
    if structured and not STRUCTURED_OUTPUTS.available:
        structured = False
    kwargs = _params(structured)
    attempt = 0
    while True:
        try:
            resp = call_with_refusal_fallback(client, kwargs, model=model, method="create")
            break
        except Exception as exc:  # noqa: BLE001 - degrade, never raise
            if structured and STRUCTURED_OUTPUTS.rejects(exc):
                # A capability answer, not a blip: latch off for the process
                # and re-send this same item under the fenced contract without
                # spending a transient retry on learning it.
                STRUCTURED_OUTPUTS.latch_off()
                structured = False
                kwargs = _params(False)
                _log.warning(
                    "prose-harvest: structured outputs rejected (%s); continuing "
                    "with the fenced-block contract for the rest of this run.",
                    _clean_error(exc),
                )
                continue
            if _is_transient_error(exc) and attempt < max_retries:
                sleep(_retry_backoff_seconds(attempt))
                attempt += 1
                continue
            _log.warning("prose-harvest structuring call failed: %s", _clean_error(exc))
            return None, 0, 0, False, True

    in_tok, out_tok = _message_usage(resp)
    raw = _message_text(resp)
    obj: dict | None = None
    for c in scan_structured_blocks(raw or ""):
        candidate = _tolerant_json_object(c.body)
        if isinstance(candidate, dict):
            obj = candidate
    if obj is None and structured:
        # A schema-constrained reply is bare JSON with no fence to find. A
        # fenced reply still wins above: it means the constraint did not take,
        # and the fence is the more specific signal (the critique's rule).
        obj = _tolerant_json_object(raw or "")
    if obj is None:
        return None, in_tok, out_tok, False, True
    if isinstance(obj.get("findings"), list) and obj["findings"]:
        obj = obj["findings"][0] if isinstance(obj["findings"][0], dict) else None
    finding = _validate_finding_item(obj, ref) if isinstance(obj, dict) else None
    if finding is not None:
        put_stage_cache_entry(
            cache,
            # Re-resolved: a read that degraded mid-call came back under the
            # fenced contract and must be stored where a fenced run will look,
            # not where the next working structured run does (I-6).
            _cache_key(structured),
            stage="prose_harvest_item",
            payload={"finding": finding.to_dict()},
        )
    return finding, in_tok, out_tok, False, True


def _degraded_entry(
    item: str, category_hint: str, ref: SheetRef, sheet_id: str
) -> Finding:
    """The §17 last-resort entry: the prose item verbatim, placed sheet-level.

    Still reaches the PDF as a margin callout — the invariant is that no prose
    QC item fails to produce a ledger entry.
    """
    return Finding(
        sheet_id=sheet_id,
        source_name=ref.source_name,
        source_id=ref.source_id,
        page_index=ref.page_index,
        category=category_hint if category_hint in ("conflict", "coordination", "question") else "coordination",
        severity="medium",
        text=item.strip(),
        source_quote="",
        anchor_hint="SHEET",
        verification=Verification(status="SKIPPED", note="degraded prose-harvest entry"),
    )


def _set_level_entry(item: str) -> Finding:
    """A **set-level** finding for a synthesis conflict naming no in-set sheet (§14.8).

    ``source_id`` is empty and ``anchor_hint`` is ``"SET_INDEX"`` (so ``_scope_of``
    treats it as SET), ``page_index`` is ``-1``. It belongs to no source sheet and is
    written to the dedicated ``Drawing_Set_Review_Notes.pdf`` — never pinned onto an
    arbitrary drawing. The verbatim statement stays intact (I-2 — mirrored, not moved).
    """
    return Finding(
        sheet_id=SET_LEVEL_SHEET_LABEL,
        source_name="",
        source_id="",
        page_index=-1,
        category="conflict",
        severity="medium",
        text=item.strip(),
        source_quote="",
        anchor_hint="SET_INDEX",
        verification=Verification(status="SKIPPED", note="set-level synthesis conflict"),
    )


# --------------------------------------------------------------------------- #
# The harvest pass
# --------------------------------------------------------------------------- #


#: What can become of one enumerated prose item (remediation WP-09.2, plan
#: WP-09 step 4). Each is also a ``HarvestResult`` counter of the same name,
#: and the counters are the number of items with that outcome.
PROSE_OUTCOMES = ("matched", "structured", "degraded", "set_level", "missing")


@dataclass(frozen=True)
class ProseItemOutcome:
    """What became of one enumerated prose item (remediation WP-09.2).

    ``outcome`` is one of :data:`PROSE_OUTCOMES`: ``matched`` (it restated an
    existing entry, which gained its provenance for free), ``structured`` (one
    structuring call turned it into a finding), ``degraded`` (the verbatim
    sheet-level entry: no client, a failed call, or a reply with no usable
    finding), ``set_level`` (a synthesis conflict naming no in-set sheet) or
    ``missing`` (it reached no ledger entry at all). ``call`` is the
    structuring request it cost: ``none``, ``cache`` (a warm hit) or ``live``
    (a billed request; kept when the item later degraded). ``folded`` says its
    structured, degraded or set-level finding folded into an entry the ledger
    already held (a duplicate outcome), and ``refused`` counts the candidates
    at or above the match threshold whose critical signature conflicted with
    the item's (N10). Items suppressed as filler or as an assurance are never
    enumerated, so they have no record; they are counted per channel
    (``HarvestResult.suppressed``).
    """

    prose_item_id: str
    channel: str
    outcome: str
    call: str = "none"
    folded: bool = False
    refused: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HarvestResult:
    """Telemetry + carry-through accounting for one run's prose harvest (§14.9).

    Every enumerated prose item has a stable ``prose_item_id``; the harvest
    reconciles the ``expected_ids`` (all enumerated) against the ``accounted_ids``
    (attached to a ledger entry) and degrades — never silently drops — any
    straggler. ``missing`` is the count still unaccounted after the final degraded
    attempt: it must be ``0`` for a complete exhaustive harvest.

    Since remediation WP-09.2 every enumerated item also has exactly one
    :class:`ProseItemOutcome` in ``outcomes`` (keyed by ``prose_item_id``), and
    the counters named in :data:`PROSE_OUTCOMES` are the number of items with
    each outcome (an item used to be counted ``structured`` before the ledger
    took its finding, and ``degraded`` again when the reconcile recovered it).
    ``vetoed``, ``folded``, ``filtered_focus`` and the per-channel table are
    observational (the ``filtered`` contract, D-2): only ``missing`` feeds
    ``complete``.
    """

    items: int = 0            # prose items considered
    matched: int = 0          # mechanism 2 — tagged an existing entry
    structured: int = 0       # mechanism 3 — model structured a straggler
    degraded: int = 0         # last resort — verbatim SHEET entry
    set_level: int = 0        # synthesis conflicts placed in the set-level artifact
    excluded_focus: int = 0   # focus items present but intentionally not harvested
    skipped: int = 0          # retained for back-compat (nothing is dropped now)
    missing: int = 0          # enumerated items with NO ledger entry after reconcile
    #: Prose lines the boilerplate/length filter removed before enumeration
    #: (P8 item 6). Observational only — see :func:`count_filtered_prose_lines`:
    #: it feeds neither ``missing`` nor ``complete``, because filler is not a lost
    #: finding. It is recorded because ``expected`` is built from what SURVIVED
    #: the filter, so without this a filter that ate real findings still reported
    #: ``missing == 0``.
    filtered: int = 0
    #: Synthesis statements that mention a conflict only to say there is none
    #: ("No conflicts were found between M-101 and P-101."), so the harvest did
    #: not take them as conflicts (remediation WP-09.1, N11). The contract of
    #: ``filtered``: observational, it feeds neither ``missing`` nor
    #: ``complete`` (see :func:`count_synthesis_assurances`).
    assurances: int = 0
    #: Focus-findings lines suppressed as filler, counted whether or not the
    #: focus harvest is on (remediation WP-09.2; see
    #: :func:`count_filtered_focus_lines`). Observational, like ``filtered``.
    filtered_focus: int = 0
    #: Enumerated items for which the signature veto refused at least one
    #: candidate at or above the match threshold (N10), whatever became of
    #: them. Observational: a refusal is a claim kept apart, not a loss.
    vetoed: int = 0
    #: Items whose structured, degraded or set-level finding the ledger folded
    #: into an entry it already held (a duplicate outcome, plan WP-09 step 5).
    #: Observational: the item's id still reaches the ledger through the fold.
    folded: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    api_calls: int = 0
    expected_ids: list[str] = field(default_factory=list)
    accounted_ids: list[str] = field(default_factory=list)
    #: One :class:`ProseItemOutcome` per enumerated item, by ``prose_item_id``.
    outcomes: dict[str, ProseItemOutcome] = field(default_factory=dict)
    #: Items suppressed as trivial, per channel (never enumerated, so they
    #: have no id): the digest's filtered lines by the section they came from,
    #: focus filler (``focus_prose``) and synthesis assurances
    #: (``synthesis_prose``).
    suppressed: dict[str, int] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        """True when every enumerated prose item reached a ledger entry."""
        return self.missing == 0

    def by_channel(self) -> dict[str, dict[str, int]]:
        """Per channel, how many items had each outcome and how many were
        suppressed (remediation WP-09.2). Channels sorted, every row carrying
        every outcome, so the table is stable (I-7) and its columns add up to
        the run-level counters."""
        table: dict[str, dict[str, int]] = {}

        def _row(channel: str) -> dict[str, int]:
            return table.setdefault(channel, dict.fromkeys((*PROSE_OUTCOMES, "suppressed"), 0))

        for outcome in self.outcomes.values():
            _row(outcome.channel)[outcome.outcome] += 1
        for channel, count in self.suppressed.items():
            if count:
                _row(channel)["suppressed"] += count
        return {channel: table[channel] for channel in sorted(table)}

    def accounting(self) -> dict:
        """The §14.9 carry-through counts for run.log / ``run_manifest.json``.

        Defined here — at the producer — so a future harvest counter reaches
        the exported accounting without a parallel edit in the pipeline
        (Phase 26A). Token usage, the raw id lists and the per-item outcomes
        stay internal; the per-channel table (``by_channel``) is exported.
        """
        return {
            "items": self.items,
            "matched": self.matched,
            "structured": self.structured,
            "degraded": self.degraded,
            "set_level": self.set_level,
            "excluded_focus": self.excluded_focus,
            "skipped": self.skipped,
            "missing": self.missing,
            "filtered": self.filtered,
            "assurances": self.assurances,
            "filtered_focus": self.filtered_focus,
            "vetoed": self.vetoed,
            "folded": self.folded,
            "by_channel": self.by_channel(),
            "complete": self.complete,
        }


@dataclass
class _Pending:
    """One enumerated prose item plus everything needed to ingest it."""

    item: ProseItem
    ref: SheetRef | None            # None for a set-level item
    sheet_id: str
    sheet_text: str
    tag: str
    hint: str
    also_on: list[ConflictLeg]
    # Filled in as the item is processed, for its ProseItemOutcome: how many
    # match candidates the signature veto refused, and the structuring request
    # it cost (kept if the reconcile later degrades it).
    refused: int = 0
    call: str = "none"

    @property
    def pid(self) -> str:
        return self.item.prose_item_id


def _client_or_none(client: Any) -> Any:
    if client is not None:
        return client
    try:
        from .client import get_client as _get_client

        return _get_client()
    except Exception as exc:  # noqa: BLE001 - no key → structuring degrades
        _log.warning("prose harvest: no client (%s); stragglers degrade", _clean_error(exc))
        return None


def _record_outcome(
    result: HarvestResult, p: _Pending, outcome: str, *, folded: bool = False
) -> None:
    """Record ``p``'s one outcome and count it (remediation WP-09.2).

    The only place an outcome counter moves, so the counters are always the
    number of items with each outcome. Called only once the ledger holds the
    item's finding (or its id), so a failed ingest leaves the item to the
    reconcile instead of counting it twice. A later record for the same item
    (the reconcile, or ``missing``) replaces the earlier one and undoes its
    counts, so an item never holds two.
    """
    previous = result.outcomes.get(p.pid)
    if previous is not None:
        setattr(result, previous.outcome, getattr(result, previous.outcome) - 1)
        result.folded -= int(previous.folded)
        result.vetoed -= int(previous.refused > 0)
    result.outcomes[p.pid] = ProseItemOutcome(
        prose_item_id=p.pid, channel=p.tag, outcome=outcome, call=p.call,
        folded=folded, refused=p.refused,
    )
    setattr(result, outcome, getattr(result, outcome) + 1)
    result.folded += int(folded)
    result.vetoed += int(p.refused > 0)


def _add_to_ledger(ledger: Ledger, finding: Finding, tag: str) -> bool:
    """Ingest one harvested finding; return whether the ledger folded it into
    an entry it already held (it merges or appends; before the seal, only a
    merge leaves the entry count unchanged)."""
    before = len(ledger)
    ledger.add([finding], tag)
    return len(ledger) == before


def _call_of(outcome: tuple[Finding | None, int, int, bool, bool]) -> str:
    """The structuring request one ``_structure_item`` outcome cost."""
    _finding, _in_tok, _out_tok, cache_hit, live_call = outcome
    if cache_hit:
        return "cache"
    return "live" if live_call else "none"


def _process_free_pending(ledger: Ledger, p: _Pending, result: HarvestResult) -> bool:
    """Apply the set-level or existing-ledger path; return whether handled."""
    pid = p.pid
    if p.ref is None:
        finding = _set_level_entry(p.item.verbatim_text)
        finding.prose_item_ids = [pid]
        folded = _add_to_ledger(ledger, finding, p.tag)
        _record_outcome(result, p, "set_level", folded=folded)
        return True

    refused: list[Finding] = []
    match = _match_entry(
        p.item.verbatim_text, ledger.entries_for(p.ref),
        also_on=p.also_on, refused=refused,
    )
    p.refused = len(refused)
    if match is None:
        return False
    if p.tag not in match.sources:
        match.sources.append(p.tag)
    if p.also_on and not match.also_on:
        match.also_on = list(p.also_on)
    if pid not in match.prose_item_ids:
        match.prose_item_ids.append(pid)
    _record_outcome(result, p, "matched")
    return True


def _record_structure_telemetry(
    result: HarvestResult,
    outcome: tuple[Finding | None, int, int, bool, bool],
    *,
    cache_enabled: bool,
) -> None:
    """Account every executed/cache-served request, including an unused one."""
    _finding, in_tok, out_tok, cache_hit, live_call = outcome
    result.input_tokens += in_tok
    result.output_tokens += out_tok
    if cache_hit:
        result.cache_hits += 1
    elif cache_enabled:
        result.cache_misses += 1
    if live_call:
        result.api_calls += 1


def _ingest_structured_pending(
    ledger: Ledger,
    p: _Pending,
    result: HarvestResult,
    finding: Finding | None,
) -> None:
    """Deterministically ingest one precomputed structuring outcome."""
    if finding is not None:
        if not finding.source_quote.strip() and not finding.anchor_hint:
            finding.anchor_hint = "SHEET"
        outcome = "structured"
    else:
        # ``p.ref`` is guaranteed by the caller: set-level items are handled by
        # ``_process_free_pending`` and never enter the structuring pool.
        finding = _degraded_entry(p.item.verbatim_text, p.hint, p.ref, p.sheet_id)
        outcome = "degraded"
    if p.also_on:
        finding.also_on = list(p.also_on)
    finding.prose_item_ids = [p.pid]
    folded = _add_to_ledger(ledger, finding, p.tag)
    # Counted only now that the ledger holds it (remediation WP-09.2): an add
    # that raised used to leave the item counted structured AND, once the
    # reconcile recovered it, degraded.
    _record_outcome(result, p, outcome, folded=folded)


def _process_pending(
    ledger: Ledger,
    p: _Pending,
    result: HarvestResult,
    *,
    client: Any,
    model: str,
    max_retries: int,
    sleep: Any,
    cache: Any = None,
) -> None:
    """Mechanisms 2 → 3 → degraded for one prose item; attach its ``prose_item_id``.

    A set-level item (a synthesis conflict naming no in-set sheet) has no sheet to
    match or structure against, so it degrades directly to a set-level ledger entry.
    """
    if _process_free_pending(ledger, p, result):
        return

    outcome: tuple[Finding | None, int, int, bool, bool] = (
        None, 0, 0, False, False,
    )
    if client is not None or cache is not None:
        outcome = _structure_item(
            p.item.verbatim_text, p.hint, p.sheet_text, p.ref, p.sheet_id,
            client=client, model=model, max_retries=max_retries, sleep=sleep,
            cache=cache,
        )
        _record_structure_telemetry(result, outcome, cache_enabled=cache is not None)
        p.call = _call_of(outcome)
    _ingest_structured_pending(ledger, p, result, outcome[0])


def _accounted_ids(ledger: Ledger) -> set[str]:
    """The set of prose-item ids currently attached to any ledger entry."""
    acc: set[str] = set()
    for e in ledger.entries:
        acc.update(e.prose_item_ids)
    return acc


def _enumerate_pending(
    sheets: list[Any],
    synthesis_text: str,
    id_map: dict[str, Any],
    *,
    focus_findings_to_markups: bool,
    sheet_text_of: Any,
    display_id_of: Any,
    result: HarvestResult,
) -> list[_Pending]:
    """Enumerate every candidate prose item into a stable-id ``_Pending`` (§14.6).

    Nothing is dropped here: a synthesis conflict naming no resolvable in-set sheet
    becomes a **set-level** pending item rather than being discarded. What the
    filler and assurance rules suppress is counted per channel
    (``result.suppressed``) and in ``filtered`` / ``filtered_focus`` /
    ``assurances``; it is never enumerated, so it takes no ordinal.
    """
    pending: list[_Pending] = []

    def _suppress(channel: str, count: int) -> None:
        if count:
            result.suppressed[channel] = result.suppressed.get(channel, 0) + count

    # --- per-sheet digest prose (Coordination / Conflict; Focus when opted in) --
    for sd in sheets or []:
        if getattr(sd, "error", None) or not (getattr(sd, "text", "") or "").strip():
            continue
        ref = sd.ref
        sid_label = display_id_of(ref)
        sheet_text = sheet_text_of(ref)
        counters: dict[str, int] = {}
        for channel, removed in _filtered_prose_lines_by_channel(sd.text).items():
            result.filtered += removed
            _suppress(channel, removed)
        for tag, item in extract_prose_items(sd.text):
            ordinal = counters.get(tag, 0)
            counters[tag] = ordinal + 1
            hint = "conflict" if tag.endswith("conflict") else "coordination"
            pi = ProseItem(
                prose_item_id=compute_prose_item_id(
                    tag, ref.source_id, tag, ordinal, item, page_index=ref.page_index),
                channel=tag, scope="SOURCE", source_id=ref.source_id,
                section=tag, ordinal=ordinal, verbatim_text=item,
            )
            pending.append(_Pending(pi, ref, sid_label, sheet_text, tag, hint, []))
        focus_items, focus_filler = _focus_split(sd.text)
        # Counted whether or not the focus harvest is on (the owner's rule).
        result.filtered_focus += focus_filler
        _suppress("focus_prose", focus_filler)
        if focus_findings_to_markups:
            for ordinal, item in enumerate(focus_items):
                pi = ProseItem(
                    prose_item_id=compute_prose_item_id(
                        "focus_prose", ref.source_id, "focus", ordinal, item,
                        page_index=ref.page_index),
                    channel="focus_prose", scope="SOURCE", source_id=ref.source_id,
                    section="focus", ordinal=ordinal, verbatim_text=item,
                )
                pending.append(_Pending(pi, ref, sid_label, sheet_text, "focus_prose", "question", []))
        else:
            result.excluded_focus += len(focus_items)   # present, intentionally not harvested

    # --- synthesis assurances: counted, never harvested (N11) -------------------
    assurances = count_synthesis_assurances(synthesis_text)
    result.assurances += assurances
    _suppress("synthesis_prose", assurances)

    # --- synthesis conflicts naming an in-set sheet (SOURCE-scoped; dual-anchored) --
    for ordinal, (item, sids) in enumerate(
        extract_synthesis_conflicts(synthesis_text, id_map.keys())
    ):
        primary = id_map.get(sids[0])
        if primary is None:
            # Named an in-set id we cannot map to a geometry — a detect/normalize
            # disagreement. Don't drop it: keep it as set-level (§14.8).
            pi = ProseItem(
                prose_item_id=compute_prose_item_id("synthesis_prose", "", "synthesis", ordinal, item),
                channel="synthesis_prose", scope="SET", source_id=None,
                section="synthesis", ordinal=ordinal, verbatim_text=item,
                mentioned_sheet_ids=list(sids),
            )
            pending.append(_Pending(pi, None, SET_LEVEL_SHEET_LABEL, "", "synthesis_prose", "conflict", []))
            continue
        legs: list[ConflictLeg] = []
        for other in sids[1:2]:                 # dual-anchor: the second named sheet
            geom = id_map.get(other)
            if geom is not None:
                legs.append(ConflictLeg(
                    sheet_id=other,
                    source_name=geom.ref.source_name,
                    source_id=geom.ref.source_id,
                    page_index=geom.ref.page_index,
                ))
        pi = ProseItem(
            prose_item_id=compute_prose_item_id(
                "synthesis_prose", primary.ref.source_id, "synthesis", ordinal, item,
                page_index=primary.ref.page_index),
            channel="synthesis_prose", scope="SOURCE", source_id=primary.ref.source_id,
            section="synthesis", ordinal=ordinal, verbatim_text=item,
            mentioned_sheet_ids=list(sids),
        )
        pending.append(_Pending(
            pi, primary.ref, sids[0], getattr(primary, "sheet_text", "") or "",
            "synthesis_prose", "conflict", legs,
        ))

    # --- synthesis conflicts naming NO in-set sheet at all → set-level (§14.8) ---
    for ordinal, item in enumerate(
        extract_set_level_synthesis_conflicts(synthesis_text, id_map.keys())
    ):
        pi = ProseItem(
            prose_item_id=compute_prose_item_id("synthesis_prose", "", "synthesis_set", ordinal, item),
            channel="synthesis_prose", scope="SET", source_id=None,
            section="synthesis_set", ordinal=ordinal, verbatim_text=item,
        )
        pending.append(_Pending(pi, None, SET_LEVEL_SHEET_LABEL, "", "synthesis_prose", "conflict", []))

    return pending


def harvest_prose(
    ledger: Ledger,
    sheets: list[Any],
    geometries: list[Any],
    *,
    client: Any = None,
    synthesis_text: str = "",
    focus_findings_to_markups: bool = False,
    model: str | None = None,
    max_retries: int = DEFAULT_HARVEST_MAX_RETRIES,
    sleep: Any = time.sleep,
    progress: Any = None,
    cache: Any = None,
    max_workers: int | None = None,
) -> HarvestResult:
    """Mirror every prose QC item into the ledger (§17/§14). Never raises.

    Runs after the digest/critique/cross/auditor ingest and **before** the ledger
    seals. Every candidate item is first enumerated into a stable ``prose_item_id``
    (§14.6); each is then processed under its own try/except (a failure in one item
    can never abandon the rest) — matched items tag an existing entry, stragglers are
    structured by one small model call, and anything else degrades to a verbatim
    entry. A synthesis conflict naming no resolvable in-set sheet becomes a
    **set-level** finding rather than being dropped (§14.8). Finally the harvest
    reconciles the enumerated ids against the ledger and makes one last degraded
    attempt for any straggler, so nothing enumerated is silently lost (§14.9).
    ``synthesis_text`` contributes its conflict statements (dual-anchored when two
    sheets are named); per-sheet Focus sections are harvested only when
    ``focus_findings_to_markups`` is on.
    """
    result = HarvestResult()
    model = model or harvest_model()
    client = _client_or_none(client)

    geom_by_key = {
        source_page_key(g.ref): g
        for g in geometries or []
        if getattr(g, "ref", None) is not None
    }
    # The set's sheet-id map, for synthesis anchoring.
    from .auditors.references import detect_sheet_id

    id_map: dict[str, Any] = {}
    for geom in geometries or []:
        sid = detect_sheet_id(geom)
        if sid and sid not in id_map:
            id_map[sid] = geom

    def _sheet_text(ref: SheetRef) -> str:
        geom = geom_by_key.get(source_page_key(ref))
        return getattr(geom, "sheet_text", "") or "" if geom is not None else ""

    def _display_id(ref: SheetRef) -> str:
        geom = geom_by_key.get(source_page_key(ref))
        return (detect_sheet_id(geom) if geom is not None else None) or ref.source_name

    pending = _enumerate_pending(
        sheets, synthesis_text, id_map,
        focus_findings_to_markups=focus_findings_to_markups,
        sheet_text_of=_sheet_text, display_id_of=_display_id, result=result,
    )
    result.items = len(pending)

    # A structured result can make a later prose item match for free, but only
    # inside that source-page's ledger bucket.  Therefore each collision-safe
    # source/page is one dependency chain: calls within a chain stay sequential,
    # while the next necessary call from different chains may overlap.  This is
    # deliberately stricter than submitting every item that is unmatched against
    # the *initial* ledger — that speculative approach could bill a later duplicate
    # before an earlier result had a chance to absorb it.
    chains: dict[tuple[str, int], list[int]] = {}
    for index, p in enumerate(pending):
        if p.ref is not None:
            chains.setdefault(source_page_key(p.ref), []).append(index)

    # Parallelism is useful only when at least two page chains contain a current
    # straggler.  A one-page harvest follows the original sequential loop exactly.
    # It asks the same ``_match_entry`` the free path does, legs included, so a
    # candidate the signature veto refuses makes its chain active here too
    # (remediation WP-09.2); it passes no ``refused`` sink, being a probe of
    # the initial ledger rather than an item's outcome.
    active_chain_count = sum(
        any(
            _match_entry(
                pending[index].item.verbatim_text,
                ledger.entries_for(pending[index].ref),
                also_on=pending[index].also_on,
            )
            is None
            for index in indices
        )
        for indices in chains.values()
    )
    workers = _resolve_harvest_workers(max_workers, active_chain_count)
    use_parallel = (
        (client is not None or cache is not None)
        and workers > 1
        and active_chain_count > 1
    )

    def _run_structure(index: int) -> tuple[Finding | None, int, int, bool, bool]:
        p = pending[index]
        try:
            return _structure_item(
                p.item.verbatim_text, p.hint, p.sheet_text, p.ref, p.sheet_id,
                client=client, model=model, max_retries=max_retries, sleep=sleep,
                cache=cache,
            )
        except Exception as exc:  # noqa: BLE001 - reconciled to degraded below
            _log.warning(
                "prose harvest: structuring item %s failed (%s)",
                p.pid, _clean_error(exc),
            )
            return None, 0, 0, False, False

    if not use_parallel:
        # Exact legacy path for one dependency chain / one worker / no client.
        for index, p in enumerate(pending):
            try:
                _process_pending(
                    ledger, p, result,
                    client=client, model=model, max_retries=max_retries, sleep=sleep,
                    cache=cache,
                )
            except Exception as exc:  # noqa: BLE001 - reconciled below
                _log.warning(
                    "prose harvest: item %s failed (%s); will reconcile",
                    p.pid, _clean_error(exc),
                )
            if progress is not None:
                progress(index + 1, len(pending), "Harvesting prose findings")
    else:
        # Only the main thread mutates the ledger.  ``_prime_chain`` consumes any
        # now-free matches (which append no entries) and submits at most ONE call
        # for that page.  The next call for the page is considered only after the
        # current outcome has been ingested into the real ledger.
        chain_positions = {key: 0 for key in chains}
        handled_free: set[int] = set()
        futures: dict[int, Any] = {}
        disabled_chains: set[tuple[str, int]] = set()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            def _prime_chain(key: tuple[str, int]) -> None:
                if key in disabled_chains:
                    return
                indices = chains[key]
                position = chain_positions[key]
                while position < len(indices):
                    index = indices[position]
                    chain_positions[key] = position + 1
                    position += 1
                    p = pending[index]
                    try:
                        if _process_free_pending(ledger, p, result):
                            handled_free.add(index)
                            continue
                    except Exception as exc:  # noqa: BLE001 - reconcile later
                        handled_free.add(index)
                        _log.warning(
                            "prose harvest: item %s failed (%s); will reconcile",
                            p.pid, _clean_error(exc),
                        )
                        continue
                    try:
                        futures[index] = pool.submit(_run_structure, index)
                    except Exception as exc:  # noqa: BLE001 - old path remains safe
                        disabled_chains.add(key)
                        _log.warning(
                            "prose harvest: could not schedule item %s (%s); "
                            "continuing sequentially",
                            p.pid, _clean_error(exc),
                        )
                    return

            # Prime in first-occurrence order; executor capacity, not dict/set
            # timing, decides when work runs.  Assembly below remains input-order.
            for key in chains:
                _prime_chain(key)

            for index, p in enumerate(pending):
                try:
                    if index in handled_free:
                        pass
                    elif index in futures:
                        key = source_page_key(p.ref)
                        try:
                            outcome = futures.pop(index).result()
                            _record_structure_telemetry(
                                result, outcome, cache_enabled=cache is not None
                            )
                            p.call = _call_of(outcome)
                            _ingest_structured_pending(ledger, p, result, outcome[0])
                        finally:
                            # Whether this item structured, degraded, or failed,
                            # its page's next dependency can now be evaluated.
                            _prime_chain(key)
                    else:
                        # Set-level items and chains whose executor submission
                        # failed retain the exact original per-item behavior.
                        _process_pending(
                            ledger, p, result,
                            client=client, model=model, max_retries=max_retries,
                            sleep=sleep, cache=cache,
                        )
                except Exception as exc:  # noqa: BLE001 - reconcile below
                    _log.warning(
                        "prose harvest: item %s failed (%s); will reconcile",
                        p.pid, _clean_error(exc),
                    )
                if progress is not None:
                    progress(index + 1, len(pending), "Harvesting prose findings")

    # --- reconcile: every enumerated id must have reached a ledger entry (§14.9) --
    expected = {p.pid for p in pending}
    by_id = {p.pid: p for p in pending}
    accounted = _accounted_ids(ledger)
    missing = expected - accounted
    if missing:
        for pid in sorted(missing):
            p = by_id[pid]
            try:
                if p.ref is None:
                    finding = _set_level_entry(p.item.verbatim_text)
                    finding.prose_item_ids = [pid]
                    folded = _add_to_ledger(ledger, finding, p.tag)
                    # mirror the main-loop set-level tally
                    _record_outcome(result, p, "set_level", folded=folded)
                else:
                    finding = _degraded_entry(p.item.verbatim_text, p.hint, p.ref, p.sheet_id)
                    finding.prose_item_ids = [pid]
                    folded = _add_to_ledger(ledger, finding, p.tag)
                    _record_outcome(result, p, "degraded", folded=folded)
            except Exception as exc:  # noqa: BLE001 - genuinely unrecoverable → reported
                _log.warning("prose harvest: could not recover item %s: %s", pid, _clean_error(exc))
        accounted = _accounted_ids(ledger)

    result.expected_ids = sorted(expected)
    result.accounted_ids = sorted(accounted & expected)
    # Every enumerated item ends with exactly one outcome: what still reached
    # no ledger entry is ``missing`` (the one count that holds the stage off
    # COMPLETE).
    for pid in sorted(expected - accounted):
        _record_outcome(result, by_id[pid], "missing")

    _log.info(
        "prose harvest: %d item(s) — %d matched, %d structured, %d degraded, "
        "%d set-level, %d excluded-focus, %d filtered, %d filtered-focus, "
        "%d assurances, %d vetoed, %d folded, %d MISSING",
        result.items, result.matched, result.structured, result.degraded,
        result.set_level, result.excluded_focus, result.filtered,
        result.filtered_focus, result.assurances, result.vetoed, result.folded,
        result.missing,
    )
    return result
