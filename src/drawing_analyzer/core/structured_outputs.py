"""Per-stage opt-in gate for ``output_config.format`` (structured outputs).

One author for the rules every stage that constrains its reply to a JSON schema
must follow. The critique wrote them first (F-01) and proved the shape; the
prose harvest and the crop verifier reuse this module rather than restating
them — a second copy of a latch is the drift this codebase has already paid
for once.

1. **Opt-in by environment variable, off by default.** The one thing that
   would make the feature unsafe — whether a schema constraint holds on the
   stage's real request shape (a 37-image vision read, a crop plus a finding)
   — is undocumented upstream and cannot be settled from inside a hermetic
   suite. Each stage settles it with one live canary call, and flips its own
   default only after that passes.
2. **Gated on the capability registry**, never on a model-id test:
   :func:`drawing_analyzer.core.api_config.model_supports_structured_outputs`.
3. **A self-healing latch, per stage.** The first 400 naming the
   structured-output contract turns the feature off for the rest of the
   process — for *this* stage only. A rejection on the vision-carrying
   critique says nothing about the text-only harvest, so the latches are
   independent instances rather than one process-wide flag. A stage that
   400s on every call would take its deliverable down with it (I-3); a stage
   that learns once and re-sends unconstrained loses nothing.
4. **Cache identity stays byte-stable when the feature is off.** Callers fold
   their structured key (instruction + schema hash, or the ``format`` block
   itself) into the cache key *only when enabled*, so every entry written
   before the feature existed is still found by a fenced run, and a
   structured run never serves a fenced result or vice versa (I-6).

The gate does not build requests or parse replies: :func:`attach_format` is
the one shared request rule (``format`` shares ``output_config`` with
``effort`` and must be merged, never assigned over), and each stage keeps its
own parser, because "no fence to find" means something different to a
findings block, a single finding and a two-field verdict.
"""
from __future__ import annotations

import os
from typing import Any

from .api_config import model_supports_structured_outputs

_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Substrings a 400 body carries when the API rejects the structured-output
#: contract (the parameter, the schema, or the feature by name). Shared by every
#: gate because every gate guards the same feature. It overlaps the strict-tools
#: and task-budget vocabularies in ``investigate.py`` on purpose-neutral words
#: (``json_schema``, ``output_config``), and that is safe only because no request
#: carries both: the investigation loop never opts into ``output_config.format``,
#: and no gated stage declares client tools or a task budget. A stage that ever
#: does both needs its own latch vocabulary, as ``investigate.py``'s two do.
STRUCTURED_OUTPUTS_REJECTION_MARKERS: tuple[str, ...] = (
    "output_config",
    "json_schema",
    "output_format",
    "structured output",
    "schema",
)


def error_status(exc: Exception) -> int | None:
    """Return the HTTP status carried by an SDK error, if any (duck-typed).

    Same shape as ``digest._error_status``; restated here only because ``core``
    must not import the pipeline package it underpins.
    """
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def is_structured_outputs_rejection(exc: Exception) -> bool:
    """True for a 400 that names the structured-output contract.

    Only a 400: a 529 carrying the same words is an overload blip, not a
    capability answer, and must go to the transient retry instead.
    """
    if error_status(exc) != 400:
        return False
    text = str(exc).lower()
    return any(marker in text for marker in STRUCTURED_OUTPUTS_REJECTION_MARKERS)


def attach_format(params: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Merge ``output_config.format`` into ``params`` in place and return it.

    ``format`` shares ``output_config`` with ``effort``, so it is merged into
    whatever the effort branch left rather than assigned over it — a fresh dict
    here silently drops the effort level on every structured request, which is
    a quality change disguised as a formatting one.
    """
    config = dict(params.get("output_config") or {})
    config["format"] = {"type": "json_schema", "schema": schema}
    params["output_config"] = config
    return params


class StructuredOutputsGate:
    """The three-gate decision for one stage, plus its process-wide latch.

    ``enabled(model)`` is meant to be resolved **once per request** and threaded
    to both the request builder and the parser: re-deriving it at the parse
    site would let the latch flip mid-call and have the reply parsed under a
    contract the request never carried.
    """

    __slots__ = ("stage", "env_var", "available")

    def __init__(self, stage: str, env_var: str) -> None:
        self.stage = stage
        self.env_var = env_var
        #: The self-healing latch: ``False`` once this process has seen the API
        #: reject the contract for this stage. Reset only by :meth:`reset`
        #: (tests) — a capability answer is permanent for the process.
        self.available = True

    def requested(self) -> bool:
        """Gate 1: the operator asked for it (environment variable truthy)."""
        raw = os.environ.get(self.env_var, "")
        return raw.strip().lower() in _TRUTHY

    def enabled(self, model: str) -> bool:
        """All three gates: requested, not latched off, model declares support."""
        if not self.requested():
            return False
        return self.available and model_supports_structured_outputs(model)

    def rejects(self, exc: Exception) -> bool:
        """Whether ``exc`` is the API refusing this stage's structured request."""
        return is_structured_outputs_rejection(exc)

    def latch_off(self) -> None:
        """Record a rejection: no later request from this stage asks again."""
        self.available = False

    def reset(self) -> None:
        """Forget a rejection. For tests and canaries only."""
        self.available = True

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"StructuredOutputsGate(stage={self.stage!r}, env_var={self.env_var!r}, "
            f"available={self.available})"
        )


def detach_format(params: dict[str, Any]) -> dict[str, Any]:
    """Remove ``output_config.format`` from ``params`` in place and return it.

    The inverse of :func:`attach_format` for a stage whose fenced and structured
    requests differ *only* by the schema (the verifier: its prompt already asks
    for a bare JSON object, so there is no instruction to swap). Leaves
    ``effort`` untouched and drops an ``output_config`` that the removal has
    emptied, so the result is byte-identical to the request the stage would
    have built with the feature off — which is what a degraded re-send must be.
    """
    config = dict(params.get("output_config") or {})
    config.pop("format", None)
    if config:
        params["output_config"] = config
    else:
        params.pop("output_config", None)
    return params
