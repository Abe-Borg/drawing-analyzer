"""The GUI's *Live view* driver: model + scene + painter + frame loop.

Toolkit-free like :mod:`live_view` and :mod:`live_scene`: the host hands it a
Tk-like canvas and its own ``after`` / ``after_cancel`` as ``schedule`` /
``cancel``, so the whole loop is testable with a fake canvas and a fake
scheduler. Every entry point swallows its own failures — the panel is
decoration, and nothing it does may disturb a run or the window (I-3).

The loop paces itself. While a run is in flight it polls the run's recorders
and repaints at up to 25 frames a second when something on the board moves
quickly, at 10 when only slow ambient motion is showing (an hours-long batch
wait), backing off so drawing never takes more than about a third of the UI
thread; while the panel is hidden — collapsed, switched to the log, or the
window minimized — it keeps
polling once a second (so the collapsed header's one-line summary stays live)
and draws nothing. With no run and nothing animating it stops entirely, and
restarts on the next event that changes the picture (a hover, a resize, a new
file list, a run starting).

The canvas carries five tabs (the board, and the *Story*, *Thinking*, *Plan*
and *Findings* views of :mod:`live_tabs`). The host forwards a click and the
mouse wheel (:meth:`LivePanel.click`, :meth:`LivePanel.scroll`); ``on_tab`` is
told when the showing tab changes, so the host can remember it. The Plan tab's
checklist can be picked from; a click that asks to save checks or copy one
hands ``on_request`` a :class:`~drawing_analyzer.live_tabs.SaveRequest` or
:class:`~drawing_analyzer.live_tabs.CopyRequest`, and the host reports a save
back with :meth:`LivePanel.mark_saved`. The canvas cursor becomes a hand over
anything clickable.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .diagnostics import get_logger
from .live_scene import CanvasPainter, LiveScene
from .live_view import (
    PHASE_FAILED,
    PHASE_RUNNING,
    PHASE_STOPPED,
    LiveRunModel,
    RunMonitor,
)

_log = get_logger()

FRAME_MS = 40              # fastest pace: 25 frames a second
AMBIENT_FRAME_MS = 100     # only slow motion on screen (e.g. a batch wait): 10/s
SLOWEST_FRAME_MS = 250     # a slow machine still gets 4 frames a second
HIDDEN_POLL_MS = 1000      # panel collapsed during a run: poll, don't draw
DRAW_BUDGET_FACTOR = 3     # wait >= 3x the last frame's cost before the next


class LivePanel:
    """Drives one *Live view* canvas for the life of the window."""

    def __init__(
        self,
        canvas: Any,
        *,
        schedule: Callable[[int, Callable[[], None]], Any],
        cancel: Callable[[Any], None],
        visible: Callable[[], bool] = lambda: True,
        on_summary: "Callable[[], None] | None" = None,
        on_tab: "Callable[[str], None] | None" = None,
        on_request: "Callable[[Any], None] | None" = None,
        tab: str = "",
        scale: float = 1.0,
        enabled: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.canvas = canvas
        self.model = LiveRunModel(clock=clock)
        self.scene = LiveScene()
        self.painter = CanvasPainter(canvas)
        self.monitor: "RunMonitor | None" = None
        self.scale = float(scale)
        self.enabled = bool(enabled)
        self._schedule = schedule
        self._cancel = cancel
        self._visible = visible
        self._on_summary = on_summary
        self._on_tab = on_tab
        self._on_request = on_request
        self._hot = False
        if tab:
            self.scene.set_tab(tab)
        self._clock = clock
        self._handle: Any = None
        self._last_summary = float("-inf")
        self._reported = False
        self.last_frame_ms: "float | None" = None

    # -- host events -------------------------------------------------------- #

    def set_enabled(self, enabled: bool) -> None:
        """Show (and animate) or hide the panel; hidden costs no drawing."""
        self.enabled = bool(enabled)
        self.kick()

    def preview(self, sheets: list, stages: list, revision: Any = None) -> None:
        self._guard(lambda: self.model.preview(sheets, stages, revision=revision))
        self.kick()

    def begin(self) -> RunMonitor:
        """A run is starting: returns the monitor to hand ``extract_drawing_context``."""
        self.monitor = RunMonitor()
        self._guard(self.model.begin)
        self._guard(self.scene.reset_views)
        self.kick()
        return self.monitor

    def finish(self, ctx: Any) -> None:
        monitor, self.monitor = self.monitor, None
        self._guard(self.model.finish, ctx, monitor)
        self.kick()

    def stop(self, failed: bool = False, message: str = "") -> None:
        monitor, self.monitor = self.monitor, None
        phase = PHASE_FAILED if failed else PHASE_STOPPED
        self._guard(self.model.stop, phase, message, monitor)
        self.kick()

    def hover(self, x: "float | None", y: "float | None" = None) -> None:
        self.scene.hover = None if x is None or y is None else (float(x), float(y))
        self.kick()

    def click(self, x: float, y: float) -> None:
        """A click on the canvas: a tab under it becomes the showing view; on
        the Plan tab it picks checks, opens a check's menu or asks to save."""
        request = None
        try:
            changed = self.scene.click(float(x), float(y))
            request = self.scene.take_request()
        except Exception:  # noqa: BLE001 - the panel is decoration
            changed = False
        if changed and self._on_tab is not None:
            try:
                self._on_tab(self.scene.tab)
            except Exception:  # noqa: BLE001 - a host that cannot remember it
                pass
        self.kick()
        if request is not None and self._on_request is not None:
            try:
                self._on_request(request)
            except Exception:  # noqa: BLE001 - a host that cannot act on it
                _log.exception("live view request failed")

    def mark_saved(self, ids: Any, label: str, held: "dict | None" = None,
                   message: str = "") -> None:
        """The host saved checks: tag them ``saved · label``; ``held`` (id ->
        where) were skipped as already kept. ``message`` goes on the ticker."""
        self._guard(self.scene.picks.mark_saved, ids, label, held)
        if message:
            self._guard(self.model.announce, message)
        self.kick()

    def announce(self, message: str, level: str = "good") -> None:
        """A line from the host on the ticker."""
        self._guard(self.model.announce, message, level)
        self.kick()

    def scroll(self, steps: float) -> None:
        """Mouse-wheel notches over the canvas (positive scrolls up)."""
        self._guard(self.scene.wheel, steps)
        self.kick()

    def close(self) -> None:
        """Cancel the pending frame (the window is going away)."""
        handle, self._handle = self._handle, None
        if handle is not None:
            try:
                self._cancel(handle)
            except Exception:  # noqa: BLE001 - a dying window may refuse
                pass

    # -- the loop ----------------------------------------------------------- #

    def kick(self) -> None:
        """Make sure a frame is coming (no-op if one is already scheduled)."""
        if self._handle is not None:
            return
        try:
            self._handle = self._schedule(0, self._frame)
        except Exception:  # noqa: BLE001 - no scheduler (window closing)
            self._handle = None

    def _frame(self) -> None:
        self._handle = None
        drawn_ms: "float | None" = None
        try:
            if self.monitor is not None:
                self.model.poll(self.monitor)
            if self.enabled and self._is_visible():
                drawn_ms = self._draw()
            now = self._clock()
            if self._on_summary is not None and now - self._last_summary >= 1.0:
                self._last_summary = now
                self._on_summary()
        except Exception:  # noqa: BLE001 - never let decoration break the window
            if not self._reported:
                self._reported = True
                _log.exception("live view frame failed; the panel will keep trying quietly")
        delay = self._next_delay(drawn_ms)
        if delay is not None:
            try:
                self._handle = self._schedule(delay, self._frame)
            except Exception:  # noqa: BLE001
                self._handle = None

    def _is_visible(self) -> bool:
        try:
            return bool(self._visible())
        except Exception:  # noqa: BLE001
            return False

    def _draw(self) -> "float | None":
        try:
            w = int(self.canvas.winfo_width())
            h = int(self.canvas.winfo_height())
        except Exception:  # noqa: BLE001
            return None
        if w <= 20 or h <= 20:
            return None
        started = time.perf_counter()
        prims = self.scene.build(self.model, w, h, self._clock(), scale=self.scale)
        self.painter.paint(prims)
        if self.scene.hot != self._hot:
            self._hot = self.scene.hot
            try:
                self.canvas.configure(cursor="hand2" if self._hot else "")
            except Exception:  # noqa: BLE001 - a canvas without cursors
                pass
        self.last_frame_ms = (time.perf_counter() - started) * 1000.0
        return self.last_frame_ms

    def _next_delay(self, drawn_ms: "float | None") -> "int | None":
        running = self.model.phase == PHASE_RUNNING
        if drawn_ms is None:
            # Nothing drawn (hidden, or not laid out yet). A run still needs
            # polling for the header summary; otherwise rest until kicked.
            return HIDDEN_POLL_MS if running or self.monitor is not None else None
        if not running and not self.scene.animating:
            return None
        base = FRAME_MS if self.scene.fast else AMBIENT_FRAME_MS
        paced = int(max(base, DRAW_BUDGET_FACTOR * drawn_ms))
        return min(paced, SLOWEST_FRAME_MS)

    def _guard(self, fn: Callable[..., Any], *args: Any) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 - the board is decoration
            _log.debug("live view update failed", exc_info=True)
