"""Runtime usage for one API response, before a stage aggregates its totals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _count(value: Any, key: str) -> int:
    return int(_get(value, key, 0) or 0)


# The served-by signal of a server-side refusal fallback: the terminal
# ``usage.iterations`` entry of a turn a fallback model produced. Sticky turns
# (served by the fallback model directly, ~1h after a decline) carry it too but
# no ``fallback`` content block, so the block is not a reliable signal.
_FALLBACK_ITERATION = "fallback_message"


@dataclass(frozen=True)
class UsageHop:
    """One billed attempt inside a fallback-served response.

    ``model`` is the model that ran it. ``None`` means the iteration named no
    model, which is the requested model's own declined attempt.
    """

    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    served: bool = False


def fallback_served_model(message: Any) -> str | None:
    """The model a server-side refusal fallback served ``message`` with, or ``None``.

    ``None`` when the requested model answered (or the response carries no
    ``usage.iterations``). The top-level ``model`` is not compared against the
    request: a model alias echoes back canonical, so a mismatch is not a
    fallback.
    """
    for entry in _get(_get(message, "usage"), "iterations", None) or ():
        if _get(entry, "type") == _FALLBACK_ITERATION:
            return str(_get(entry, "model", "") or _get(message, "model", "") or "") or None
    return None


@dataclass(frozen=True)
class RequestUsage:
    """Keep request boundaries so long-context rates use that request's prompt.

    This is runtime telemetry only; cached stage results incurred no API charge
    in the current run and do not restore historical request usage.

    ``served_model`` and ``hops`` are set only when a server-side refusal
    fallback served the response (``fallbacks: "default"``,
    :func:`~drawing_analyzer.core.api_config.apply_refusal_fallback`). Then the
    top-level usage covers only the serving attempt, so ``hops`` carries every
    billed attempt from ``usage.iterations`` — the declined ones first — and the
    ledger prices each at the model that ran it.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_id: str = ""
    stop_reason: str | None = None
    parse_success: bool | None = None
    served_model: str | None = None
    hops: tuple[UsageHop, ...] = ()

    @classmethod
    def from_message(cls, message: Any) -> RequestUsage:
        usage = _get(message, "usage")
        served = fallback_served_model(message)
        hops: tuple[UsageHop, ...] = ()
        if served is not None:
            hops = tuple(
                UsageHop(
                    model=str(_get(entry, "model", "") or "") or None,
                    input_tokens=_count(entry, "input_tokens"),
                    output_tokens=_count(entry, "output_tokens"),
                    cache_read_tokens=_count(entry, "cache_read_input_tokens"),
                    cache_write_tokens=_count(entry, "cache_creation_input_tokens"),
                    served=_get(entry, "type") == _FALLBACK_ITERATION,
                )
                for entry in _get(usage, "iterations", None) or ()
            )
        return cls(
            input_tokens=_count(usage, "input_tokens"),
            output_tokens=_count(usage, "output_tokens"),
            cache_read_tokens=_count(usage, "cache_read_input_tokens"),
            cache_write_tokens=_count(usage, "cache_creation_input_tokens"),
            request_id=str(_get(message, "id", "") or ""),
            stop_reason=_get(message, "stop_reason"),
            served_model=served,
            hops=hops,
        )


def any_fallback_served(usages: Iterable[RequestUsage | None]) -> bool:
    """True when a refusal fallback served any of ``usages``.

    Stages check this before a cache write: a fallback answer came from a
    different model than the one the cache key names, so storing it would serve
    that model's work as the requested model's on every later run.
    """
    return any(u is not None and u.served_model for u in usages)
