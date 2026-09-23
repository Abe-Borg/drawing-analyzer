"""Why a Messages response stopped, and whether that makes it finished work (D-1).

One classifier for every stage that has to decide whether a reply is a
completed read. It looks at ``stop_reason`` and nothing else, and callers ask it
FIRST, before any text or JSON is considered, because the shape of a reply
cannot tell the difference:

* a refusal can carry a paragraph of explanation, which reads like a digest;
* a truncated digest reads as prose until the sentence it was cut in;
* a stream that ends without ``message_stop`` hands back its partial text with
  ``stop_reason=None`` and raises nothing (``get_final_message()`` in SDK
  1.7.0; review N27).

So a successful HTTP envelope, nonempty text or a parseable JSON object never
overrides the stop reason. The kinds:

``FINISHED``
    ``end_turn``, ``stop_sequence``: the model reached a stopping point. The
    only kind a stage may treat as a completed read or admit to a cache.
``TRUNCATED``
    ``max_tokens`` and ``model_context_window_exceeded``: output was cut off.
    Only ``max_tokens`` can be finished by resubmitting with a raised cap
    (:attr:`TerminalOutcome.raised_cap_may_finish`). A context-window stop is a
    truncation too, but the limit it hit is the window, not the cap, and a
    larger cap cannot make room in it.
``REFUSED``
    ``refusal``: the request was declined, whether or not text came back.
``UNFINISHED``
    ``None``: the response never said how it ended. That is what the SDK
    returns for a stream that stopped before ``message_delta`` delivered a stop
    reason. (In non-streaming mode the API always sets one.)
``CONTINUATION``
    ``tool_use``, ``pause_turn`` and the beta ``compaction``: the turn handed
    control back for the caller to continue. Each stage decides what that
    means. A stage that declares no tools and never resumes a paused turn (the
    digest) treats it as not finished.
``UNKNOWN``
    Anything else: a value no SDK names yet, an empty string, a non-string.
    Never finished.

The vocabulary is the installed SDK's, not a list from memory:
``anthropic.types.StopReason`` in SDK 1.7.0, plus ``BetaStopReason``'s
``compaction``. Every call that carries the refusal-fallback beta travels
``client.beta.messages`` (:func:`drawing_analyzer.core.api_config.messages_namespace`),
so the beta vocabulary is the one a response can actually carry.
``tests/test_terminal_outcome.py`` pins this table to both literals, so an SDK
upgrade that adds a reason fails there until it is classified here. Until then
the new reason is ``UNKNOWN``, which is the safe answer.

What this module does not decide, because it cannot be read from a stop
reason: a transport failure (the call raised, and there is no response to
classify), a malformed result (a finished reply whose content the stage cannot
parse), and a valid inconclusive judgment (a finished reply that parses and
says "cannot tell"). Those belong to each stage's own parser, applied only to a
``FINISHED`` reply. ``DECISIONS.md`` D-1 records the whole contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

FINISHED = "finished"
TRUNCATED = "truncated"
REFUSED = "refused"
UNFINISHED = "unfinished"
CONTINUATION = "continuation"
UNKNOWN = "unknown"

#: Every kind :func:`classify_stop_reason` can return.
KINDS: frozenset[str] = frozenset(
    {FINISHED, TRUNCATED, REFUSED, UNFINISHED, CONTINUATION, UNKNOWN}
)

#: The SDK's stop-reason vocabulary, classified. Read-only on purpose: a stage
#: that wants different handling decides it from the kind, never by editing
#: the table.
STOP_REASON_KINDS: Mapping[str, str] = MappingProxyType({
    "end_turn": FINISHED,
    "stop_sequence": FINISHED,
    "max_tokens": TRUNCATED,
    "model_context_window_exceeded": TRUNCATED,
    "refusal": REFUSED,
    "tool_use": CONTINUATION,
    "pause_turn": CONTINUATION,
    "compaction": CONTINUATION,
})

# The one truncation a resubmission at a raised ``max_tokens`` can finish.
_RAISED_CAP_MAY_FINISH = frozenset({"max_tokens"})


@dataclass(frozen=True)
class TerminalOutcome:
    """One response's terminal state: its kind and the raw ``stop_reason``."""

    kind: str
    stop_reason: Any = None

    @property
    def finished(self) -> bool:
        """True only for :data:`FINISHED`. Unknown is never finished."""
        return self.kind == FINISHED

    @property
    def raised_cap_may_finish(self) -> bool:
        """True only for a ``max_tokens`` truncation.

        The one case a resubmission with a larger ``max_tokens`` can complete.
        Neither a context-window stop nor anything that is not a truncation
        qualifies.
        """
        return self.kind == TRUNCATED and self.stop_reason in _RAISED_CAP_MAY_FINISH


def classify_stop_reason(stop_reason: Any) -> TerminalOutcome:
    """Classify one response's ``stop_reason`` (the raw value, any type).

    Strict: only the exact strings the SDK names are recognised, so ``None`` is
    :data:`UNFINISHED` and any other value, a near-miss spelling included, is
    :data:`UNKNOWN`. Callers read the value with their own shape-tolerant
    accessor (``digest._get`` for SDK objects and plain dicts alike).
    """
    if stop_reason is None:
        return TerminalOutcome(UNFINISHED, None)
    if isinstance(stop_reason, str):
        kind = STOP_REASON_KINDS.get(stop_reason)
        if kind is not None:
            return TerminalOutcome(kind, stop_reason)
    return TerminalOutcome(UNKNOWN, stop_reason)
