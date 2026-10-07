"""Runtime usage for one API response, before a stage aggregates its totals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


@dataclass(frozen=True)
class RequestUsage:
    """Keep request boundaries so long-context rates use that request's prompt.

    This is runtime telemetry only; cached stage results incurred no API charge
    in the current run and do not restore historical request usage.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_id: str = ""
    stop_reason: str | None = None
    parse_success: bool | None = None

    @classmethod
    def from_message(cls, message: Any) -> RequestUsage:
        usage = _get(message, "usage")
        return cls(
            input_tokens=int(_get(usage, "input_tokens", 0) or 0),
            output_tokens=int(_get(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(_get(usage, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(_get(usage, "cache_creation_input_tokens", 0) or 0),
            request_id=str(_get(message, "id", "") or ""),
            stop_reason=_get(message, "stop_reason"),
        )
