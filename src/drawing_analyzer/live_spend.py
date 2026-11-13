"""Live spend for one run: what is billed, what is in flight, where it will land.

The usage ledger (``ctx.run_usage``) is the run's authoritative bill, but most
stages append to it only when they end, so it cannot drive a display while a
run is working. This module watches the three places every paid request passes
through instead:

- :func:`drawing_analyzer.core.api_config._dispatch_messages` — each real-time
  response is priced the moment it arrives (:func:`note_response`);
- :func:`drawing_analyzer.batch_digest._create_batch` — each accepted batch
  item becomes *in flight* (:func:`note_batch_submit`): submitted, billed only
  when its result exists;
- :func:`drawing_analyzer.batch_recovery.read_batch_results` — a result that is
  read moves its item from in flight to billed (:func:`note_batch_results`).

A caller creates a :class:`SpendMonitor`, hands it to
:func:`~drawing_analyzer.pipeline.extract_drawing_context` as ``spend=``, and
reads :meth:`SpendMonitor.snapshot` whenever it likes (the GUI polls it). The
monitor rides the run's :class:`~drawing_analyzer.resource_pressure.ResourcePressure`
record, so it reaches every worker thread through the existing
``worker_binding()``; outside a run the module-level functions do nothing.

Three figures
-------------
``billed``
    Responses received, priced with the ledger's own rule
    (:func:`~drawing_analyzer.core.pricing.usage_record_cost`, per billed
    attempt of a refusal fallback, batch rate for batch results).
``in flight``
    Batch items submitted and not yet read. Their cost is a band: the
    per-item rate of their stage (below) times the item count.
``projected``
    Where the run's total will land. Per stage it is what the stage has
    billed plus its remaining items at a per-item rate. That rate starts at
    the pre-run estimate's (:class:`StageForecast`, built by
    :func:`drawing_analyzer.cost.spend_forecast`) and moves to the stage's
    own observed mean as its items complete (``k / (k + SHRINK_ITEMS)``), so
    the band narrows as the run proceeds. A finished stage contributes exactly
    what it billed, and :meth:`SpendMonitor.finish` replaces the live figures
    with the ledger's, so the projection ends on the run's recorded cost.

The budget cap
--------------
``budget`` is a dollar cap the caller may set, change or clear at any time,
including while the run works. When ``billed`` plus a floor on what is in
flight reaches it, the monitor stops the run through its kill switch
(:class:`~drawing_analyzer.cancellation.CancelToken`): nothing new is sent,
streams are abandoned and open batches are canceled. The floor is the low
per-item rate, and only where it can be trusted: a quote priced from the
pages' measured shapes, or the stage's own observed cost. A quote built on
the conservative image allowance (``StageForecast.measured`` false) is far
above what a small sheet costs, so it never counts toward the cap. An
over-wide estimate of in-flight work therefore cannot stop a run that is
within its cap. Work already submitted is billed for whatever it completed,
so a batch run can land above the cap by up to the batch that was in flight.

Every figure is this app's price table applied to reported tokens — an
estimate, not the invoice. Advisory and never fatal: every hook swallows its
own failures. Counts and dollars only; no prompt, text, image or key.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from . import cancellation
from .core.pricing import FAST_SPEED, usage_record_cost
from .core.request_usage import RequestUsage

# Completed items after which a stage's own mean per-item cost carries as much
# weight as the pre-run estimate's per-item rate.
SHRINK_ITEMS = 3

STAGE_PENDING = "PENDING"     # no paid request seen yet
STAGE_RUNNING = "RUNNING"
STAGE_DONE = "DONE"

BUDGET_STOP_REASON = "the budget cap was reached"


@dataclass(frozen=True)
class StageForecast:
    """The pre-run estimate for one usage family, in dollars and work items.

    ``items_*`` is how many work items the estimate assumed at each end of
    its band (sheets for the digest, reads for critique, findings for
    verification); the monitor divides to get a per-item rate.
    """

    family: str
    low: float
    high: float
    items_low: float = 1.0
    items_high: float = 1.0
    #: False when the figures rest on the conservative image allowance rather
    #: than the pages' measured shapes: then ``low`` is not a floor.
    measured: bool = True


@dataclass(frozen=True)
class BudgetHit:
    """The moment the budget cap stopped the run."""

    limit: float
    committed: float      # billed + the floor on what was in flight
    billed: float
    stage: str            # the family whose spend crossed the cap ("" = a cap change)


@dataclass(frozen=True)
class StageSpend:
    """One usage family's live figures."""

    family: str
    state: str
    billed: float
    items_done: int
    in_flight_items: int
    projected_low: float
    projected_high: float


@dataclass(frozen=True)
class SpendSnapshot:
    """A consistent reading of the monitor."""

    billed: float = 0.0
    calls: int = 0
    #: Responses that used tokens on a model the price table does not know;
    #: ``billed`` is a floor while this is non-zero.
    unpriced_calls: int = 0
    in_flight_items: int = 0
    #: ``None`` when items are in flight in a stage with no rate to price them.
    in_flight_low: float | None = 0.0
    in_flight_high: float | None = 0.0
    #: What in-flight work is certain to cost at least (see the module docstring).
    in_flight_floor: float = 0.0
    #: ``None`` until a forecast is supplied or the run has finished.
    projected_low: float | None = None
    projected_high: float | None = None
    #: The pre-run estimate the projection started from.
    quoted_low: float | None = None
    quoted_high: float | None = None
    budget: float | None = None
    budget_hit: BudgetHit | None = None
    #: The run ended and the figures are the usage ledger's.
    final: bool = False
    stages: tuple[StageSpend, ...] = ()

    @property
    def committed(self) -> float:
        """What the budget cap is compared with."""
        return self.billed + self.in_flight_floor


class _Stage:
    __slots__ = ("family", "forecast", "billed", "items", "unlabeled",
                 "in_flight", "expected", "started", "finished")

    def __init__(self, family: str, forecast: StageForecast | None = None) -> None:
        self.family = family
        self.forecast = forecast
        self.billed = Decimal("0")
        self.items: set[str] = set()
        self.unlabeled = 0
        self.in_flight = 0
        self.expected: int | None = None
        self.started = False
        self.finished = False

    @property
    def items_done(self) -> int:
        return len(self.items) + self.unlabeled

    def per_item(self) -> tuple[float, float] | None:
        """The (low, high) rate for one more item of this stage, or ``None``."""
        done = self.items_done
        mean = float(self.billed) / done if done else None
        forecast = self.forecast
        if forecast is None or forecast.items_low <= 0 or forecast.items_high <= 0:
            return None if mean is None else (mean, mean)
        low = forecast.low / forecast.items_low
        high = forecast.high / forecast.items_high
        if mean is None:
            return low, high
        weight = done / (done + SHRINK_ITEMS)
        return low + weight * (mean - low), high + weight * (mean - high)

    def floor_rate(self) -> float:
        """What one in-flight item is certain to cost at least."""
        forecast = self.forecast
        if forecast is not None and forecast.measured and forecast.items_low > 0:
            return self.per_item()[0]            # type: ignore[index]
        done = self.items_done
        if not done:
            return 0.0
        return float(self.billed) / done * (done / (done + SHRINK_ITEMS))

    def remaining(self) -> tuple[float, float]:
        """Items still to be billed, at each end of the band (in flight included)."""
        if self.finished:
            return float(self.in_flight), float(self.in_flight)
        if self.expected is not None:
            low = high = float(self.expected)
        elif self.forecast is not None:
            low, high = self.forecast.items_low, self.forecast.items_high
        else:
            return float(self.in_flight), float(self.in_flight)
        done = self.items_done
        return max(low - done, self.in_flight), max(high - done, self.in_flight)

    def state(self) -> str:
        if self.finished:
            return STAGE_DONE
        return STAGE_RUNNING if self.started else STAGE_PENDING


def _get(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def response_cost(message: Any, *, model: str, batch: bool = False) -> tuple[Decimal, bool]:
    """Price one response the way the ledger will: ``(cost, unpriced)``.

    ``unpriced`` is true when a billed attempt used tokens on a model the
    price table does not know; that attempt adds nothing to ``cost``.
    """
    from .core.api_config import fast_mode_active_for

    usage = RequestUsage.from_message(message)
    searches = int(
        _get(_get(_get(message, "usage"), "server_tool_use"), "web_search_requests", 0) or 0
    )
    speed = None
    if not batch:
        speed = usage.speed or (FAST_SPEED if fast_mode_active_for(model) else None)
    parts: tuple[Any, ...] = usage.hops or (usage,)
    total = Decimal("0")
    unpriced = False
    for index, part in enumerate(parts):
        if part is usage:
            billed_model = model
        else:
            billed_model = part.model or (usage.served_model if part.served else None) or model
        cost = usage_record_cost(
            model=billed_model,
            input_tokens=part.input_tokens,
            output_tokens=part.output_tokens,
            cache_read_tokens=part.cache_read_tokens,
            cache_write_tokens=part.cache_write_tokens,
            billable_tool_uses=(
                {"web_search": searches} if searches and index == len(parts) - 1 else None
            ),
            batch=batch,
            speed=speed,
        )
        if cost is None:
            unpriced = unpriced or bool(
                part.input_tokens or part.output_tokens
                or part.cache_read_tokens or part.cache_write_tokens
            )
        else:
            total += cost
    return total, unpriced


class SpendMonitor:
    """One run's live spend and its budget cap. Thread-safe."""

    def __init__(
        self,
        *,
        budget: float | None = None,
        forecast: Iterable[StageForecast] = (),
    ) -> None:
        self._lock = threading.Lock()
        self._stages: dict[str, _Stage] = {}
        # (batch id, custom id) -> (stage, model, item label) of each batch
        # item submitted and not yet read.
        self._in_flight: dict[tuple[str, str], tuple[str, str, str]] = {}
        self._calls = 0
        self._unpriced = 0
        self._budget: float | None = None
        self._hit: BudgetHit | None = None
        self._cancel: cancellation.CancelToken | None = None
        self._final = False
        self._final_billed: Decimal | None = None
        self._quoted: tuple[float, float] | None = None
        self.set_forecast(forecast)
        self.set_budget(budget)

    # -- configuration ------------------------------------------------------ #

    def set_forecast(self, forecast: Iterable[StageForecast]) -> None:
        """Supply the pre-run estimate the projection starts from."""
        entries = [f for f in forecast or () if f is not None]
        with self._lock:
            for entry in entries:
                self._stage(entry.family).forecast = entry
            self._quoted = (
                (sum(f.low for f in entries), sum(f.high for f in entries))
                if entries else None
            )

    def bind_cancel(self, token: "cancellation.CancelToken | None") -> None:
        """Give the monitor the run's kill switch (the pipeline does this)."""
        with self._lock:
            self._cancel = token
        self._enforce("")

    @property
    def budget(self) -> float | None:
        with self._lock:
            return self._budget

    def set_budget(self, amount: float | None) -> None:
        """Set, change or clear (``None``) the cap. Takes effect at once.

        A cap at or below what the run has already committed stops the run.
        Raises ``ValueError`` for a cap that is not a positive finite number.
        """
        if amount is not None:
            amount = float(amount)
            if not (amount > 0) or amount == float("inf"):
                raise ValueError("a budget cap must be a positive dollar amount")
        with self._lock:
            self._budget = amount
        self._enforce("")

    # -- events ------------------------------------------------------------- #

    def note_response(
        self, message: Any, *, stage: str, item: str = "", model: str = "",
        batch: bool = False,
    ) -> None:
        """One response arrived: price it and count its item as done."""
        try:
            cost, unpriced = response_cost(message, model=model, batch=batch)
        except Exception:  # noqa: BLE001 - advisory, never fatal
            return
        with self._lock:
            entry = self._stage(stage)
            entry.started = True
            entry.billed += cost
            if item:
                entry.items.add(item)
            else:
                entry.unlabeled += 1
            self._calls += 1
            if unpriced:
                self._unpriced += 1
        self._enforce(stage)

    def note_batch_submit(
        self, batch_id: str, requests: Iterable[Any], *, stage: str,
        items: dict | None = None,
    ) -> None:
        """A Message Batch was accepted: its items are in flight."""
        try:
            labels = dict(items or {})
            with self._lock:
                entry = self._stage(stage)
                entry.started = True
                for request in requests or ():
                    custom_id = str(_get(request, "custom_id") or "")
                    key = (str(batch_id or ""), custom_id)
                    if key in self._in_flight:
                        continue
                    model = str(_get(_get(request, "params") or {}, "model") or "")
                    self._in_flight[key] = (stage, model, str(labels.get(custom_id) or ""))
                    entry.in_flight += 1
        except Exception:  # noqa: BLE001
            return
        self._enforce(stage)

    def note_batch_results(self, batch_id: str, results: dict) -> None:
        """A batch's results were read: settle each item this run submitted.

        A result for an item this monitor never saw submitted (receipt
        recovery collecting an earlier run's batch) is not this run's spend
        and is ignored, as is a second read of the same batch.
        """
        touched = ""
        try:
            # Settle the whole read first: every item leaves in flight before
            # any is billed, so the cap never sees an item counted both ways
            # (or a half-read batch) while the results are priced.
            settled: list[tuple[str, str, str, Any]] = []
            with self._lock:
                for custom_id, entry in dict(results or {}).items():
                    submitted = self._in_flight.pop(
                        (str(batch_id or ""), str(custom_id or "")), None,
                    )
                    if submitted is None:
                        continue
                    self._stage(submitted[0]).in_flight -= 1
                    settled.append((*submitted, entry))
            for stage, model, label, entry in settled:
                touched = stage
                result = _get(entry, "result")
                if str(_get(result, "type") or "") != "succeeded":
                    continue        # errored / canceled / expired: not billed
                message = _get(result, "message")
                self.note_response(
                    message, stage=stage, item=label,
                    model=model or str(_get(message, "model") or ""), batch=True,
                )
        except Exception:  # noqa: BLE001
            return
        self._enforce(touched)

    def expect(self, family: str, items: int) -> None:
        """The stage now knows how many paid items it has (cache hits excluded)."""
        try:
            count = max(0, int(items))
        except (TypeError, ValueError):
            return
        with self._lock:
            self._stage(family).expected = count

    def stage_finished(self, family: str) -> None:
        """The stage ended: from here it contributes exactly what it billed."""
        with self._lock:
            self._stage(family).finished = True

    def finish(self, run_usage: Any = None) -> None:
        """The run ended. With its ledger, the figures become the ledger's."""
        try:
            total = getattr(run_usage, "total_estimated_cost", None)
            by_family = run_usage.by_family() if total is not None else {}
        except Exception:  # noqa: BLE001
            total, by_family = None, {}
        with self._lock:
            for entry in self._stages.values():
                entry.finished = True
            if total is not None:
                self._final_billed = Decimal(total)
                for family, group in by_family.items():
                    cost = group.get("estimated_cost")
                    if cost is not None:
                        self._stage(family).billed = Decimal(cost)
                for family, entry in self._stages.items():
                    if family not in by_family:
                        entry.billed = Decimal("0")
            self._final = True

    # -- reading ------------------------------------------------------------ #

    def snapshot(self) -> SpendSnapshot:
        with self._lock:
            return self._snapshot_locked()

    # -- internals ---------------------------------------------------------- #

    def _stage(self, family: str) -> _Stage:
        family = str(family or "unattributed")
        entry = self._stages.get(family)
        if entry is None:
            entry = self._stages[family] = _Stage(family)
        return entry

    def _snapshot_locked(self) -> SpendSnapshot:
        stages: list[StageSpend] = []
        billed = Decimal("0")
        in_flight_items = 0
        flight_low = flight_high = flight_floor = 0.0
        flight_known = True
        projected_low = projected_high = 0.0
        for entry in self._stages.values():
            billed += entry.billed
            rate = entry.per_item()
            rem_low, rem_high = entry.remaining()
            spent = float(entry.billed)
            if rate is None:
                low = high = spent
                if entry.in_flight:
                    flight_known = False
            else:
                low = spent + rem_low * rate[0]
                high = spent + rem_high * rate[1]
                flight_low += entry.in_flight * rate[0]
                flight_high += entry.in_flight * rate[1]
            in_flight_items += entry.in_flight
            flight_floor += entry.in_flight * entry.floor_rate()
            projected_low += low
            projected_high += high
            if entry.started or entry.forecast is not None or entry.billed:
                stages.append(StageSpend(
                    family=entry.family, state=entry.state(), billed=spent,
                    items_done=entry.items_done, in_flight_items=entry.in_flight,
                    projected_low=low, projected_high=high,
                ))
        if self._final_billed is not None:
            # The ledger total is authoritative; per-family figures were
            # replaced with it, so the sum and the projection follow.
            billed = self._final_billed
        can_project = self._quoted is not None or self._final
        return SpendSnapshot(
            billed=float(billed),
            calls=self._calls,
            unpriced_calls=self._unpriced,
            in_flight_items=in_flight_items,
            in_flight_low=flight_low if flight_known else None,
            in_flight_high=flight_high if flight_known else None,
            in_flight_floor=flight_floor,
            projected_low=projected_low if can_project else None,
            projected_high=projected_high if can_project else None,
            quoted_low=None if self._quoted is None else self._quoted[0],
            quoted_high=None if self._quoted is None else self._quoted[1],
            budget=self._budget,
            budget_hit=self._hit,
            final=self._final,
            stages=tuple(stages),
        )

    def _enforce(self, stage: str) -> None:
        """Stop the run if the cap is reached. Never raises."""
        try:
            with self._lock:
                if self._budget is None or self._hit is not None or self._final:
                    return
                token = self._cancel
                if token is None:
                    return
                snap = self._snapshot_locked()
                if snap.committed < self._budget:
                    return
                self._hit = BudgetHit(
                    limit=self._budget, committed=snap.committed,
                    billed=snap.billed, stage=stage,
                )
            token.cancel(BUDGET_STOP_REASON)
        except Exception:  # noqa: BLE001
            pass


def format_money(amount: float) -> str:
    return f"${amount:,.2f}"


def _band(low: float, high: float) -> str:
    if round(low, 2) == round(high, 2):
        return format_money(high)
    return f"{format_money(low)}–{format_money(high)}"


def format_spend_line(snap: SpendSnapshot) -> str:
    """The one-line reading a status display shows."""
    spent = format_money(snap.billed)
    if snap.unpriced_calls:
        spent = f"at least {spent}"
    parts = [f"Spent {spent}"]
    if snap.in_flight_items:
        if snap.in_flight_low is None or snap.in_flight_high is None:
            parts.append(f"{snap.in_flight_items} batch request(s) in flight")
        else:
            parts.append(
                f"in flight ~{_band(snap.in_flight_low, snap.in_flight_high)} "
                f"({snap.in_flight_items} batch request(s))"
            )
    if snap.final:
        parts[0] = f"Final cost {spent}"
    elif snap.projected_low is not None and snap.projected_high is not None:
        parts.append(f"projected {_band(snap.projected_low, snap.projected_high)}")
    if snap.quoted_low is not None and snap.quoted_high is not None:
        parts.append(f"quoted {_band(snap.quoted_low, snap.quoted_high)}")
    if snap.budget is not None:
        parts.append(f"cap {format_money(snap.budget)}")
    return "  ·  ".join(parts)


# --------------------------------------------------------------------------- #
# Module-level forwarding to the run's monitor (no-op outside a run).
# --------------------------------------------------------------------------- #


def current() -> SpendMonitor | None:
    """The calling thread's run monitor, via the resource-pressure binding."""
    from . import resource_pressure

    return getattr(resource_pressure.current(), "spend", None)


def _scope() -> tuple[str, str]:
    from . import call_telemetry

    return call_telemetry.current_scope()


def note_response(kwargs: dict, message: Any) -> None:
    monitor = current()
    if monitor is not None:
        stage, item = _scope()
        monitor.note_response(
            message, stage=stage, item=item, model=str((kwargs or {}).get("model") or ""),
        )


def note_batch_submit(batch_id: str, requests: Iterable[Any], *, items: dict | None = None) -> None:
    monitor = current()
    if monitor is not None:
        monitor.note_batch_submit(batch_id, requests, stage=_scope()[0], items=items)


def note_batch_results(batch_id: str, results: dict) -> None:
    monitor = current()
    if monitor is not None:
        monitor.note_batch_results(batch_id, results)


def expect(family: str, items: int) -> None:
    monitor = current()
    if monitor is not None:
        monitor.expect(family, items)


def stage_finished(stage: str) -> None:
    monitor = current()
    if monitor is not None:
        from .call_telemetry import canonical_stage

        monitor.stage_finished(canonical_stage(stage))
