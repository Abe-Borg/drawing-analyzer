"""Temporary, opt-in prompt experiments (F2 / F3 of the prompt review).

Two candidate prompt changes, each behind its own environment variable and
**off by default**. They exist to be measured, not shipped: adopt one only if an
A/B on real sets shows fewer unanchored or malformed findings without a rise in
total findings (``scripts/compare_prompt_experiment.py`` compares two exports).
Then fold it into the prompts and delete it from here; otherwise delete it.

- ``DRAWING_ANALYZER_EXPERIMENT_QUOTE_FIRST`` (F2): every findings field list
  (digest, critique, cross-QC whole-set / shard / reconcile) asks for the
  evidence — ``source_quote``, ``also_on``, ``anchor_hint``, ``tile_label`` —
  straight after the sheet id and before the judgment (``category``,
  ``severity``, ``text``, ...). The critique's structured-outputs schema moves
  ``source_quote`` up too; structured outputs emit required properties first in
  schema order, then optional ones, so the optional ``tile_label`` /
  ``anchor_hint`` still come after the required judgment fields there.
- ``DRAWING_ANALYZER_EXPERIMENT_CRITIQUE_EXAMPLE`` (F3): the critique findings
  instruction gains one illustrative ``<example>``: a quoted finding, a
  sheet-level absence, and a sum claim, on deliberately generic content.

Both are read **once, at import**, unlike the per-call knobs elsewhere. Each one
changes module-level prompt strings, and every prompt-version hash and cache key
is computed from those strings, so resolving at import is what guarantees that
a process never sends one arm while keying the other (I-6): a variant run
re-keys the stages it touches and never serves, or overwrites, a baseline
entry. Set the variable before the process starts. Unset, every request and
every key is byte-identical to a build without this module.
"""
from __future__ import annotations

import os

QUOTE_FIRST_ENV = "DRAWING_ANALYZER_EXPERIMENT_QUOTE_FIRST"
CRITIQUE_EXAMPLE_ENV = "DRAWING_ANALYZER_EXPERIMENT_CRITIQUE_EXAMPLE"

# The same spelling the structured-outputs gates accept.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _requested(env_var: str) -> bool:
    return os.environ.get(env_var, "").strip().lower() in _TRUTHY


QUOTE_FIRST = _requested(QUOTE_FIRST_ENV)
CRITIQUE_EXAMPLE = _requested(CRITIQUE_EXAMPLE_ENV)


def active() -> tuple[str, ...]:
    """The experiments this process runs, for run.log and the run manifest."""
    return tuple(name for name, on in (
        ("quote_first", QUOTE_FIRST),
        ("critique_example", CRITIQUE_EXAMPLE),
    ) if on)


#: Evidence fields, in the order F2 asks for them right after the id field.
EVIDENCE_FIELDS = ("source_quote", "also_on", "anchor_hint", "tile_label")


def _field_name(clause: str) -> str:
    return clause.split(" (", 1)[0].strip()


def _clause_list_span(text: str, start: int) -> tuple[int, list[str]]:
    """The ``a (...); b (...); c (...)`` list starting at ``start``.

    Splits on ``;`` and stops at ``.`` only outside parentheses and double
    quotes, so a description's own punctuation (``e.g. "..."``, ``(<= 2
    sentences)``) stays inside its clause. Returns the end offset (the closing
    period) and the clauses, each verbatim.
    """
    depth = 0
    in_quote = False
    clauses: list[str] = []
    clause_start = start
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '"':
            in_quote = not in_quote
        elif in_quote:
            continue
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and ch == ";":
            clauses.append(text[clause_start:i].strip())
            clause_start = i + 1
        elif depth == 0 and ch == ".":
            clauses.append(text[clause_start:i].strip())
            return i, clauses
    raise ValueError("field list has no closing period")


def evidence_first(instruction: str, marker: str) -> str:
    """``instruction`` with the field list after ``marker`` reordered for F2.

    The first field (the sheet id or handle) stays first; the evidence fields
    follow in :data:`EVIDENCE_FIELDS` order; everything else keeps its original
    relative order. Every clause is moved verbatim — none is reworded — and a
    marker that is missing or ambiguous raises, so an edit to a source prompt
    cannot silently leave the variant unchanged or half-reordered.
    """
    if instruction.count(marker) != 1:
        raise ValueError(f"field-list marker must occur exactly once: {marker!r}")
    start = instruction.index(marker) + len(marker)
    end, clauses = _clause_list_span(instruction, start)
    head, rest = clauses[0], clauses[1:]
    rank = {name: i for i, name in enumerate(EVIDENCE_FIELDS)}
    evidence = sorted(
        (c for c in rest if _field_name(c) in rank), key=lambda c: rank[_field_name(c)]
    )
    if not evidence:
        raise ValueError(f"no evidence field in the list after {marker!r}")
    judgment = [c for c in rest if _field_name(c) not in rank]
    return (
        instruction[:start]
        + "; ".join([head, *evidence, *judgment])
        + instruction[end:]
    )


def apply_quote_first(instruction: str, marker: str) -> str:
    """F2 when its flag is on; ``instruction`` itself (the same object) when off."""
    return evidence_first(instruction, marker) if QUOTE_FIRST else instruction


def order_keys(item: dict, first_key: str) -> dict:
    """``item`` with keys in the active field order (F2 evidence-first when on)."""
    if not QUOTE_FIRST:
        return dict(item)
    head = {k: item[k] for k in (first_key, *EVIDENCE_FIELDS) if k in item}
    return {**head, **{k: v for k, v in item.items() if k not in head}}
