"""Live view scene: the animated picture the GUI paints from a LiveRunModel.

Tk-free (like :mod:`~drawing_analyzer.live_view`): :meth:`LiveScene.build`
turns a model, a canvas size and a clock reading into a list of :class:`Prim`
— plain drawing primitives keyed by a stable id — and :class:`CanvasPainter`
applies them to any Tk-like canvas, creating, moving or recoloring only the
items whose key, coordinates or options changed since the last frame. So the
whole picture is a pure function of its inputs (and of the few eased numbers
the scene keeps between frames), and the painter's diff keeps a frame cheap:
a sheet cell that is not animating costs a tuple compare, not a Tk call.

The panel, top to bottom:

* **HUD** — run state pill, elapsed clock, the active stages, and the live
  figures: estimated spend, tokens, calls in flight, throughput.
* **Pipeline track** — one node per planned stage. Active nodes pulse and
  spin; data packets stream along the track into them (fast blue while
  real-time reads stream, slow amber while work waits in the batch queue);
  finished nodes burst and settle green / amber / red.
* **Sheet board** — one cell per sheet. Cells cascade in when a set loads,
  shimmer while queued, run a scan line while being read, flash and settle
  when done (green), cached (teal) or failed (red); purple marks the
  critique reads. A sweep crosses the board when the run completes.
* **Telemetry** — a live token-throughput chart with call counters; at the
  end of a QC run, the findings breakdown by verification status.
* **Ticker** — the latest notable event, typed out.

Hovering a cell or a node shows a tooltip (the host passes the pointer).

Under the HUD sits a **tab strip**. The board above is the first tab; the
others (*Story*, *Thinking*, *Plan*, *Findings*) are built by
:mod:`~drawing_analyzer.live_tabs` into the same space. The scene keeps which
tab is showing, each view's scroll offset, and the hover regions a view
registers for tooltips; :meth:`LiveScene.click` and :meth:`LiveScene.wheel`
are the host's two inputs.
"""
from __future__ import annotations

import math
from decimal import Decimal
from functools import lru_cache
from typing import Any, Callable, Iterable, NamedTuple

from .live_view import (
    FINDING_BUCKETS,
    PHASE_DONE,
    PHASE_FAILED,
    PHASE_IDLE,
    PHASE_RUNNING,
    PHASE_STOPPED,
    SHEET_CACHED,
    SHEET_DONE,
    SHEET_FAILED,
    SHEET_PENDING,
    SHEET_QUEUED,
    SHEET_READING,
    SHEET_RENDERED,
    SHEET_TERMINAL,
    STAGE_ACTIVE,
    STAGE_DONE,
    STAGE_PLANNED,
    STAGE_SKIPPED,
)

# --------------------------------------------------------------------------- #
# Palette: a dark blueprint sheet, with the app's accent / status colors.
# --------------------------------------------------------------------------- #

BG = "#0A1322"
GRID_MINOR = "#0E192B"
GRID_MAJOR = "#122039"
PANEL = "#0D182A"
INK = "#D6E2F5"
INK_DIM = "#7F90AC"
INK_FAINT = "#34445F"
WHITE = "#FFFFFF"
ACCENT = "#3B82F6"
ACCENT_GLOW = "#93C5FD"
CYAN = "#22D3EE"
TEAL = "#0E8FA8"
GREEN = "#22C55E"
GREEN_SETTLED = "#1C9A4F"
GREEN_GLOW = "#86EFAC"
AMBER = "#F59E0B"
AMBER_DIM = "#5A3E0E"
RED = "#EF4444"
RED_SETTLED = "#B42323"
PURPLE = "#A855F7"
PURPLE_GLOW = "#D8B4FE"
CELL_PENDING = "#15233A"
CELL_RENDERED = "#1D355A"

FONT = "Segoe UI"
MONO = "Consolas"

STATUS_COLOR = {
    "COMPLETE": GREEN,
    "SKIPPED_VALID": GREEN,
    "PARTIAL": AMBER,
    "FAILED": RED,
    "STOPPED": AMBER,
}
BUCKET_COLOR = {
    "verified": GREEN,
    "uncertain": AMBER,
    "unchecked": "#5B7BA8",
    "rejected": "#6B5560",
}
SHEET_STATE_TEXT = {
    SHEET_PENDING: "waiting",
    SHEET_RENDERED: "rendered — overview + tiles ready",
    SHEET_QUEUED: "queued in the batch",
    SHEET_READING: "being read now",
    SHEET_DONE: "read",
    SHEET_CACHED: "from cache (no charge)",
    SHEET_FAILED: "failed",
}

TWO_PI = 2.0 * math.pi
TIP_LINES = 10              # the most lines a tooltip shows


# --------------------------------------------------------------------------- #
# Primitives.
# --------------------------------------------------------------------------- #


class Prim(NamedTuple):
    """One canvas item. ``opts`` is a tuple of ``(option, value)`` pairs in a
    fixed order, so an unchanged item compares equal frame to frame."""

    key: str
    kind: str                      # rect | oval | line | poly | text | arc
    coords: tuple
    opts: tuple


def _r(v: float) -> float:
    return round(v, 1)


def rect(key, x0, y0, x1, y1, *, fill="", outline="", width=0.0) -> Prim:
    return Prim(key, "rect", (_r(x0), _r(y0), _r(x1), _r(y1)),
                (("fill", fill), ("outline", outline), ("width", _r(width))))


def oval(key, cx, cy, r, *, fill="", outline="", width=0.0) -> Prim:
    return Prim(key, "oval", (_r(cx - r), _r(cy - r), _r(cx + r), _r(cy + r)),
                (("fill", fill), ("outline", outline), ("width", _r(width))))


def line(key, points: Iterable[float], *, fill, width=1.0, smooth=False,
         dash: tuple = (), capstyle="round") -> Prim:
    return Prim(key, "line", tuple(_r(p) for p in points),
                (("fill", fill), ("width", _r(width)), ("smooth", bool(smooth)),
                 ("dash", tuple(dash)), ("capstyle", capstyle)))


def poly(key, points: Iterable[float], *, fill, outline="", width=0.0, smooth=False) -> Prim:
    return Prim(key, "poly", tuple(_r(p) for p in points),
                (("fill", fill), ("outline", outline), ("width", _r(width)),
                 ("smooth", bool(smooth))))


def text(key, x, y, value, *, fill, size, weight="normal", anchor="w", family=FONT) -> Prim:
    return Prim(key, "text", (_r(x), _r(y)),
                (("text", str(value)), ("fill", fill),
                 ("font", (family, -int(round(size)), weight)), ("anchor", anchor)))


def arc(key, cx, cy, r, *, start, extent, outline, width=1.0) -> Prim:
    return Prim(key, "arc", (_r(cx - r), _r(cy - r), _r(cx + r), _r(cy + r)),
                (("start", _r(start)), ("extent", _r(extent)), ("style", "arc"),
                 ("outline", outline), ("width", _r(width))))


def rounded_rect_points(x0, y0, x1, y1, r) -> list[float]:
    """A smooth polygon outline for a rounded rectangle (Tk has none built in)."""
    r = max(0.0, min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    return [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]


# --------------------------------------------------------------------------- #
# Color + format helpers.
# --------------------------------------------------------------------------- #


def _rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


@lru_cache(maxsize=8192)
def _mix_q(a: str, b: str, q: int) -> str:
    t = q / 32.0
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#%02X%02X%02X" % (
        round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t),
    )


def mix(a: str, b: str, t: float) -> str:
    """Blend two ``#RRGGBB`` colors; ``t`` is quantized to 1/32 steps so an
    animated color repeats exactly and the painter can skip the Tk call."""
    t = 0.0 if t != t else max(0.0, min(1.0, t))
    return _mix_q(a, b, int(round(t * 32)))


def pulse(t: float, period: float, phase: float = 0.0) -> float:
    """0..1..0 over ``period`` seconds."""
    return 0.5 - 0.5 * math.cos(TWO_PI * ((t / period) + phase))


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1.0 - (1.0 - x) ** 3


def fmt_tokens(n: float) -> str:
    n = float(n or 0)
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n >= 1e4:
        return f"{n / 1e3:.0f}k"
    if n >= 1e3:
        return f"{n / 1e3:.1f}k"
    return f"{n:.0f}"


def fmt_clock(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_duration(seconds: "float | None") -> str:
    if seconds is None:
        return "—"
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def fmt_money(value: "Decimal | float", *, estimate: bool) -> str:
    return ("≈$" if estimate else "$") + f"{float(value):,.2f}"


def text_width(value: str, size: float, *, mono: bool = False) -> float:
    """A layout estimate of rendered text width (the scene cannot ask Tk)."""
    return len(str(value)) * size * (0.6 if mono else 0.56)


def fit(value: str, width: float, size: float) -> str:
    """``value`` cut with an ellipsis so it fits ``width`` (by the estimate)."""
    value = str(value)
    if text_width(value, size) <= width:
        return value
    keep = max(0, int(width / (size * 0.56)) - 1)
    return value[:keep].rstrip() + "…" if keep else ""


# --------------------------------------------------------------------------- #
# Layout.
# --------------------------------------------------------------------------- #


class BoardLayout(NamedTuple):
    cols: int
    rows: int
    cell: float
    gap: float
    x0: float
    y0: float


def board_layout(n: int, x0: float, y0: float, x1: float, y1: float,
                 *, max_cell: float = 26.0) -> BoardLayout:
    """The largest square cells that fit ``n`` sheets in the rectangle."""
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    if n <= 0:
        return BoardLayout(0, 0, 0.0, 0.0, x0, y0)
    best = (0.0, 1, n)
    for cols in range(1, n + 1):
        rows = -(-n // cols)
        size = min(w / cols, h / rows)
        if size > best[0]:
            best = (size, cols, rows)
        if cols * size > w and size < best[0]:
            break
    pitch, cols, rows = best
    pitch = min(pitch, max_cell)
    gap = max(1.0, round(pitch * 0.16, 1)) if pitch >= 4 else 0.5
    return BoardLayout(cols, rows, max(0.5, pitch - gap), gap, x0, y0)


def cell_rect(layout: BoardLayout, i: int) -> tuple[float, float, float, float]:
    row, col = divmod(i, max(1, layout.cols))
    pitch = layout.cell + layout.gap
    x = layout.x0 + col * pitch
    y = layout.y0 + row * pitch
    return x, y, x + layout.cell, y + layout.cell


def track_xs(n: int, x0: float, x1: float, *, max_pitch: float = 150.0) -> list[float]:
    """Node centers for ``n`` stages, evenly spread (centered when sparse)."""
    if n <= 0:
        return []
    if n == 1:
        return [(x0 + x1) / 2.0]
    pitch = min((x1 - x0) / (n - 1), max_pitch)
    start = (x0 + x1) / 2.0 - pitch * (n - 1) / 2.0
    return [start + i * pitch for i in range(n)]


def smoothed_rates(series: Iterable[Any], now_s: int, seconds: int,
                   window: int = 10) -> list[float]:
    """Tokens/s for each of the last ``seconds`` seconds (``window``-s average)."""
    buckets: dict[int, float] = {}
    for b in series:
        buckets[int(b[0])] = buckets.get(int(b[0]), 0.0) + float(b[1]) + float(b[2])
    out = []
    start = now_s - seconds + 1
    for s in range(start, now_s + 1):
        total = sum(buckets.get(k, 0.0) for k in range(s - window + 1, s + 1))
        out.append(total / float(window))
    return out


# --------------------------------------------------------------------------- #
# The scene.
# --------------------------------------------------------------------------- #


class LiveScene:
    """Builds one frame at a time; keeps only display easing between frames."""

    CHART_SECONDS = 150

    def __init__(self) -> None:
        self.hover: "tuple[float, float] | None" = None
        # ``animating``: something on the last frame moves, so another frame is
        # wanted. ``fast``: that motion is quick (a scan line, a flash, packets
        # streaming, a number rolling) and wants the full frame rate; slow
        # ambient motion alone (pulses, the batch-queue shimmer) is drawn at a
        # lower rate, which matters through an hours-long batch wait.
        self.animating = False
        self.fast = False
        self._last_t: "float | None" = None
        self._shown: dict[str, float] = {}
        self._chart_max = 1.0
        self._node_hits: list[tuple[float, float, float, Any]] = []
        self._cell_hits: "tuple[BoardLayout, int] | None" = None
        self._shimmer_steps = 32
        # The tabs (live_tabs.py): which view is showing, each scrolling
        # view's offset, and whether it still follows its newest content.
        self.tab = "board"
        self.scroll: dict[str, float] = {}
        self.follow: dict[str, bool] = {}
        self._scroll_max: dict[str, float] = {}
        self._tab_hits: list[tuple[float, float, float, float, str]] = []
        self._tab_seen: dict[str, float] = {}
        self._tips: list[tuple[float, float, float, float, list]] = []
        self._wrapped: dict[Any, list[str]] = {}
        self._scale = 1.0
        # Clickable regions a view registered on the last frame (add_hit), and
        # the Plan tab's checklist picks (live_tabs.ChecklistPicks).
        self._hits: list[tuple] = []        # (x0, y0, x1, y1, action, menu, pointer)
        self.picks = live_tabs.ChecklistPicks()
        self.hot = False        # the pointer is over something clickable

    # -- tabs --------------------------------------------------------------- #

    def set_tab(self, tab: str) -> bool:
        """Show ``tab``; ``False`` if it is unknown or already showing."""
        if tab not in live_tabs.TAB_KEYS or tab == self.tab:
            return False
        self.tab = tab
        self.picks.menu = None
        self._hits = []
        return True

    def click(self, x: float, y: float) -> bool:
        """A click at canvas ``(x, y)``; ``True`` when it switched the tab.

        A tab under it is shown. Otherwise the topmost region a view registered
        on the last frame acts (``add_hit``). While a menu is open only the
        menu's own regions act; a click anywhere else just closes it.
        """
        for x0, y0, x1, y1, key in self._tab_hits:
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.picks.menu = None
                return self.set_tab(key)
        menu_open = self.picks.menu is not None
        for x0, y0, x1, y1, action, menu, _pointer in reversed(self._hits):
            if menu_open and not menu:
                continue
            if x0 <= x <= x1 and y0 <= y <= y1:
                action()
                return False
        self.picks.menu = None
        return False

    def add_hit(self, x0: float, y0: float, x1: float, y1: float,
                action: Callable[[], None], *, menu: bool = False,
                pointer: bool = True) -> None:
        """Register a clickable region for this frame; the last one registered
        wins where regions overlap. ``menu``: part of an open menu.
        ``pointer=False``: a region that only swallows clicks (no hand cursor)."""
        self._hits.append((x0, y0, x1, y1, action, menu, pointer))

    def take_request(self) -> Any:
        """A request a click left for the host (save or copy checks), once."""
        return self.picks.take_request()

    def wheel(self, steps: float) -> None:
        """Scroll the showing view by ``steps`` notches (positive = up)."""
        tab = self.tab
        self.picks.menu = None              # a menu does not scroll with its row
        limit = self._scroll_max.get(tab, 0.0)
        cur = min(max(self.scroll.get(tab, 0.0), 0.0), limit)
        new = min(max(cur - float(steps) * 42.0 * self._scale, 0.0), limit)
        self.scroll[tab] = new
        # Scrolling away stops a view following its newest content; reaching
        # the end again (the Thinking feed) resumes it.
        self.follow[tab] = tab == live_tabs.TAB_MIND and new >= limit - 1.0

    def reset_views(self) -> None:
        """A new run: every view follows its newest content again."""
        self.scroll.clear()
        self.follow.clear()
        self._tab_seen.clear()
        self._wrapped.clear()
        self.picks.clear()

    def scroll_offset(self, tab: str, content: float, view: float, dt: float,
                      *, follow: "float | None" = None) -> float:
        """The eased scroll offset of ``tab`` for this frame.

        ``follow`` is where the view wants to be while the user has not
        scrolled it (the newest thought, the active stage); ``None`` leaves
        the offset where the user put it.
        """
        limit = max(0.0, content - view)
        self._scroll_max[tab] = limit
        if follow is not None and self.follow.get(tab, True):
            target = min(max(follow, 0.0), limit)
        else:
            target = min(max(self.scroll.get(tab, 0.0), 0.0), limit)
        self.scroll[tab] = target
        return self._ease(f"scroll_{tab}", target, dt, rate=14.0)

    def wrap(self, key: Any, value: str, cols: int) -> list[str]:
        """``value`` wrapped to ``cols`` characters (memoized by ``key``)."""
        hit = self._wrapped.get(key)
        if hit is None:
            if len(self._wrapped) > 800:
                self._wrapped.clear()
            hit = self._wrapped[key] = live_tabs.wrap_text(value, cols)
        return hit

    def add_tip(self, x0: float, y0: float, x1: float, y1: float, lines: list) -> None:
        """Register a hover region whose tooltip is ``lines``."""
        self._tips.append((x0, y0, x1, y1, lines))

    def _moving(self) -> None:
        """Mark this frame as carrying fast motion."""
        self.animating = True
        self.fast = True

    # -- easing ------------------------------------------------------------- #

    def _ease(self, name: str, target: float, dt: float, rate: float = 7.0) -> float:
        cur = self._shown.get(name)
        if cur is None or dt <= 0:
            self._shown[name] = float(target)
            return float(target)
        cur += (float(target) - cur) * min(1.0, dt * rate)
        if abs(cur - target) < max(1e-3, abs(target) * 1e-4):
            cur = float(target)
        else:
            self._moving()
        self._shown[name] = cur
        return cur

    # -- frame -------------------------------------------------------------- #

    def build(self, model: Any, width: float, height: float, t: float,
              *, scale: float = 1.0) -> list[Prim]:
        """Everything to draw at time ``t`` (the model's animation clock)."""
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        self.animating = model.phase == PHASE_RUNNING
        self.fast = False
        s = max(0.5, float(scale))
        self._scale = s
        w, h = max(40.0, float(width)), max(40.0, float(height))
        out: list[Prim] = []
        self._background(out, w, h, s)

        m = 12 * s
        hud_h = 44 * s
        tabs_h = 22 * s
        ticker_y = h - 11 * s
        bottom_bottom = ticker_y - 14 * s

        self._hud(out, model, m, w - m, 6 * s, s, t, dt)
        self._node_hits, self._cell_hits, self._tips, self._hits = [], None, [], []
        # The tab strip sits under the HUD: the board, and the four insight
        # views (live_tabs.py) that share its space. A panel too short to fit
        # the strip above the track and a row of cells shows the board alone.
        tabbed = h >= 192 * s
        if tabbed:
            live_tabs.tab_strip(self, out, model, m, w - m, hud_h + tabs_h / 2.0, s, t, dt)
        else:
            self._tab_hits = []
        body_top = hud_h + (tabs_h if tabbed else 0.0) + 4 * s
        view = live_tabs.VIEWS.get(self.tab) if tabbed else None
        if view is not None:
            if bottom_bottom - body_top >= 40 * s:
                view(self, out, model, m, body_top, w - m, bottom_bottom, s, t, dt)
        else:
            self._board_view(out, model, m, w, h, body_top, bottom_bottom, s, t, dt)
        self._ticker(out, model, m, w - m, ticker_y, s, t)
        self._tooltip(out, model, w, h, s, t)
        self.hot = self._pointer_hot()
        return out

    def _pointer_hot(self) -> bool:
        if self.hover is None:
            return False
        hx, hy = self.hover
        if any(x0 <= hx <= x1 and y0 <= hy <= y1 for x0, y0, x1, y1, _k in self._tab_hits):
            return True
        menu_open = self.picks.menu is not None
        for x0, y0, x1, y1, _a, menu, pointer in reversed(self._hits):
            if menu_open and not menu:
                continue
            if x0 <= hx <= x1 and y0 <= hy <= y1:
                return pointer
        return False

    def _board_view(self, out, model, m, w, h, top, bottom_bottom, s, t, dt) -> None:
        """The board tab: the pipeline track, the sheet board and telemetry."""
        track_top, track_h = top, 58 * s
        bottom_top = track_top + track_h + 8 * s
        # A short panel (another section expanded above it) sheds whole rows
        # rather than overlapping them: first the board + telemetry, then the
        # track. The HUD and the ticker always stay.
        if h >= track_top + track_h + 8 * s:
            self._track(out, model, m + 14 * s, w - m - 14 * s, track_top + 28 * s, s, t)
        if bottom_bottom - bottom_top >= 30 * s:
            split = w >= 520 * s
            board_right = (w * 0.6) if split else (w - m)
            self._board(out, model, m, bottom_top, board_right - 8 * s, bottom_bottom, s, t)
            if split:
                self._telemetry(out, model, board_right + 10 * s, bottom_top, w - m,
                                bottom_bottom, s, t, dt)

    # -- background --------------------------------------------------------- #

    def _background(self, out: list[Prim], w: float, h: float, s: float) -> None:
        out.append(rect("bg", 0, 0, w, h, fill=BG))
        step = 16 * s
        i = 1
        x = step
        while x < w:
            major = i % 4 == 0
            out.append(line(f"gx{i}", (x, 0, x, h), fill=GRID_MAJOR if major else GRID_MINOR,
                            width=1, capstyle="butt"))
            x += step
            i += 1
        j = 1
        y = step
        while y < h:
            major = j % 4 == 0
            out.append(line(f"gy{j}", (0, y, w, y), fill=GRID_MAJOR if major else GRID_MINOR,
                            width=1, capstyle="butt"))
            y += step
            j += 1

    # -- HUD ---------------------------------------------------------------- #

    def _hud(self, out, model, x0, x1, y0, s, t, dt) -> None:
        phase = model.phase
        if phase == PHASE_RUNNING:
            label, dot = "LIVE", mix(RED, "#FFB4B4", pulse(t, 1.2))
            pill_fg = INK
        elif phase == PHASE_DONE:
            outcome = (model.outcome or "COMPLETE").upper()
            label, dot = outcome, STATUS_COLOR.get(outcome, GREEN)
            pill_fg = dot
        elif phase == PHASE_STOPPED:
            label, dot, pill_fg = "STOPPED", AMBER, AMBER
        elif phase == PHASE_FAILED:
            label, dot, pill_fg = "FAILED", RED, RED
        else:
            label = "READY" if model.sheets else "IDLE"
            dot, pill_fg = (ACCENT if model.sheets else INK_FAINT), INK_DIM
        size = 11 * s
        pw = text_width(label, size) + 30 * s
        py = y0 + 12 * s
        out.append(poly("hud_pill", rounded_rect_points(x0, py - 10 * s, x0 + pw, py + 10 * s, 10 * s),
                        fill=PANEL, outline=mix(dot, BG, 0.45), width=1, smooth=True))
        if phase == PHASE_RUNNING:
            ring = pulse(t, 1.2)
            out.append(oval("hud_dot_ring", x0 + 12 * s, py, (4 + 5 * ring) * s,
                            outline=mix(RED, PANEL, ring), width=1.2 * s))
        else:
            out.append(oval("hud_dot_ring", x0 + 12 * s, py, 4 * s, outline=PANEL, width=1))
        out.append(oval("hud_dot", x0 + 12 * s, py, 4 * s, fill=dot))
        out.append(text("hud_pill_t", x0 + 21 * s, py, label, fill=pill_fg, size=size,
                        weight="bold"))

        cx = x0 + pw + 12 * s
        clock = fmt_clock(model.elapsed())
        out.append(text("hud_clock", cx, py, clock, fill=INK, size=18 * s, weight="bold",
                        family=MONO))
        cx += text_width(clock, 18 * s, mono=True) + 14 * s
        room = (x1 - cx) * (1.0 if phase == PHASE_IDLE else 0.5)
        stage_line = fit(self._stage_line(model), max(60 * s, room), 12 * s)
        out.append(text("hud_stage", cx, py, stage_line, fill=ACCENT_GLOW
                        if phase == PHASE_RUNNING else INK_DIM, size=12 * s))

        # Right-aligned figures: value over caption, most important rightmost;
        # what does not fit beside the stage line is dropped from the left.
        stats = self._stats(model, dt)
        rx = x1
        min_left = cx + text_width(stage_line, 12 * s) + 16 * s
        for key, value, caption, color in reversed(stats):
            vw = max(text_width(value, 17 * s, mono=True), text_width(caption, 9 * s))
            if rx - vw < min_left:
                break
            out.append(text(f"hud_v_{key}", rx, py - 1 * s, value, fill=color, size=17 * s,
                            weight="bold", anchor="e", family=MONO))
            out.append(text(f"hud_c_{key}", rx, py + 16 * s, caption.upper(), fill=INK_DIM,
                            size=9 * s, anchor="e"))
            rx -= vw + 20 * s

    def _stage_line(self, model) -> str:
        phase = model.phase
        if phase == PHASE_IDLE:
            n = len(model.sheets)
            if not n:
                return "Drop drawing PDFs to light up the board"
            files = len({sh.source_id or sh.label.rsplit(" (page", 1)[0] for sh in model.sheets})
            return f"{n} sheet(s) · {files} file(s) · {len(model.stages)} stage(s) planned"
        if phase == PHASE_RUNNING:
            active = model.active_stages()
            if not active:
                return "Starting…"
            parts = []
            for st in active[:3]:
                parts.append(f"▸ {st.label} {self._stage_progress(model, st)}".rstrip())
            return "   ".join(parts)
        if phase == PHASE_DONE:
            return f"Finished in {fmt_duration(model.elapsed())}"
        if phase == PHASE_STOPPED:
            return f"Stopped after {fmt_duration(model.elapsed())}"
        return model.error[:60] if model.error else "The run raised an error"

    @staticmethod
    def _stage_progress(model, st) -> str:
        if st.name == "digest" and model.sheets:
            done = sum(1 for sh in model.sheets if sh.state in SHEET_TERMINAL)
            return f"{done}/{len(model.sheets)}"
        if st.name == "verification" and model.findings_sealed:
            return f"{model.findings_verified}/{model.findings_sealed}"
        if st.calls_done or st.calls_open or st.calls_queued:
            total = st.calls_done + st.calls_open + st.calls_queued
            return f"{st.calls_done}/{total}"
        return ""

    def _stats(self, model, dt) -> list[tuple[str, str, str, str]]:
        phase = model.phase
        stats: list[tuple[str, str, str, str]] = []
        if phase == PHASE_IDLE:
            return stats              # the stage line already says what is loaded
        rate = self._ease("rate", model.throughput(), dt, rate=3.0)
        if phase == PHASE_RUNNING:
            stats.append(("rate", fmt_tokens(rate) + "/s", "tokens / s", CYAN))
            live = model.calls_in_flight
            queued = model.calls_queued
            if queued and not live:
                stats.append(("calls", str(queued), "in batch queue", AMBER))
            else:
                stats.append(("calls", str(live), "calls in flight", ACCENT_GLOW))
        else:
            done = sum(1 for sh in model.sheets if sh.state in SHEET_TERMINAL)
            stats.append(("sheets", f"{done}/{len(model.sheets)}", "sheets", INK))
            if model.findings is not None:
                stats.append(("findings", str(model.findings.total), "findings", PURPLE_GLOW))
        tokens = self._ease("tokens", model.tokens_in + model.tokens_out, dt, rate=5.0)
        stats.append(("tokens", fmt_tokens(tokens), "tokens", INK))
        if model.cost_known:
            cost = self._ease("cost", float(model.cost), dt, rate=5.0)
            stats.append(("cost", fmt_money(cost, estimate=not model.cost_final),
                          "spend" if model.cost_final else "est. spend", GREEN_GLOW))
        return stats

    # -- pipeline track ----------------------------------------------------- #

    def _track(self, out, model, x0, x1, y, s, t) -> None:
        stages = list(model.stages)
        self._node_hits = []
        xs = track_xs(len(stages), x0, x1)
        if not stages:
            return
        r = 7 * s
        # Rails: a faint full-length rail, lit segments over it.
        out.append(line("trk_rail", (xs[0], y, xs[-1], y), fill=INK_FAINT, width=2 * s,
                        dash=(int(3 * s), int(4 * s)) if len(xs) > 1 else ()))
        reach = -1
        for i, st in enumerate(stages):
            if st.state in (STAGE_ACTIVE, STAGE_DONE):
                reach = i
        for i in range(len(stages) - 1):
            b = stages[i + 1]
            if i + 1 <= reach and b.state != STAGE_SKIPPED:
                lit = GREEN_SETTLED if b.state == STAGE_DONE else ACCENT
                out.append(line(f"trk_seg{i}", (xs[i], y, xs[i + 1], y), fill=lit,
                                width=3 * s))
            else:
                out.append(line(f"trk_seg{i}", (xs[i], y, xs[i], y), fill=BG, width=1))
        self._packets(out, model, stages, xs, y, s, t, reach)

        wide = len(stages) > 1 and (xs[1] - xs[0]) < 74 * s
        for i, (st, x) in enumerate(zip(stages, xs)):
            self._node(out, model, i, st, x, y, r, s, t)
            above = wide and i % 2 == 1
            ly = y - (r + 6 * s) if above else y + r + 6 * s
            color = {STAGE_ACTIVE: ACCENT_GLOW, STAGE_DONE: INK,
                     STAGE_SKIPPED: INK_FAINT}.get(st.state, INK_DIM)
            out.append(text(f"trk_lbl{i}", x, ly, st.label, fill=color, size=10 * s,
                            weight="bold" if st.state == STAGE_ACTIVE else "normal",
                            anchor="s" if above else "n"))
            self._node_hits.append((x, y, r + 6 * s, st))

    def _node(self, out, model, i, st, x, y, r, s, t) -> None:
        age = t - st.changed_at
        k = f"trk_n{i}"
        appear = ease_out(age / 0.35) if st.state == STAGE_PLANNED else 1.0
        if appear < 1.0:
            self._moving()
        rr = r * (0.3 + 0.7 * appear)
        if st.state == STAGE_ACTIVE:
            for j, period in enumerate((1.6, 1.6)):
                p = ((t / period) + j * 0.5) % 1.0
                out.append(oval(f"{k}_halo{j}", x, y, rr + (3 + 12 * p) * s,
                                outline=mix(ACCENT_GLOW, BG, p), width=1.5 * s))
            out.append(oval(f"{k}_body", x, y, rr, fill=ACCENT, outline=ACCENT_GLOW, width=1.5 * s))
            spin = 240 if model.calls_in_flight else 70     # deg/s: slow while queued
            out.append(arc(f"{k}_spin", x, y, rr + 3.5 * s, start=(-t * spin) % 360, extent=110,
                           outline=WHITE, width=2 * s))
            out.append(oval(f"{k}_core", x, y, 2.2 * s, fill=mix(WHITE, ACCENT_GLOW, pulse(t, 0.8))))
            return
        burst = age / 0.7 if st.state == STAGE_DONE else 1.0
        if burst < 1.0:
            # The moment a stage finishes: a ring bursts out of the node.
            self._moving()
            out.append(oval(f"{k}_halo0", x, y, rr + 16 * s * ease_out(burst),
                            outline=mix(WHITE, BG, burst), width=2 * s))
        else:
            out.append(oval(f"{k}_halo0", x, y, 0, outline=BG, width=1))
        out.append(oval(f"{k}_halo1", x, y, 0, outline=BG, width=1))
        if st.state == STAGE_DONE:
            color = STATUS_COLOR.get(st.status, GREEN)
            fill = mix(WHITE, color, min(1.0, age / 0.4))
            out.append(oval(f"{k}_body", x, y, rr, fill=fill, outline=mix(color, WHITE, 0.25),
                            width=1.2 * s))
            out.append(arc(f"{k}_spin", x, y, rr + 3.5 * s, start=0, extent=0, outline=BG, width=1))
            self._glyph(out, f"{k}_core", st.status, x, y, s)
            return
        dim = st.state == STAGE_SKIPPED
        out.append(oval(f"{k}_body", x, y, rr * (0.6 if dim else 1.0), fill=BG,
                        outline=INK_FAINT if dim else INK_DIM, width=1.5 * s))
        out.append(arc(f"{k}_spin", x, y, rr + 3.5 * s, start=0, extent=0, outline=BG, width=1))
        out.append(oval(f"{k}_core", x, y, 0, fill=BG))

    @staticmethod
    def _glyph(out, key, status, x, y, s) -> None:
        """A drawn status mark (font-independent): check, bang, cross or dash."""
        if status in ("COMPLETE", "SKIPPED_VALID", ""):
            pts = (x - 3.2 * s, y + 0.2 * s, x - 0.8 * s, y + 2.8 * s, x + 3.6 * s, y - 2.8 * s)
            out.append(line(key, pts, fill=BG, width=2 * s))
        elif status == "PARTIAL":
            # A "!" without dashes (Windows draws a wide dashed line solid):
            # the stem only — the node's amber says the rest.
            out.append(line(key, (x, y - 3.6 * s, x, y + 1.2 * s), fill=BG, width=2.2 * s))
        elif status == "FAILED":
            out.append(line(key, (x - 3 * s, y - 3 * s, x + 3 * s, y + 3 * s, x, y,
                                  x + 3 * s, y - 3 * s, x - 3 * s, y + 3 * s),
                            fill=BG, width=2 * s))
        else:
            out.append(line(key, (x - 3 * s, y, x + 3 * s, y), fill=BG, width=2 * s))

    def _packets(self, out, model, stages, xs, y, s, t, reach) -> None:
        """Data packets streaming along the lit track into the furthest active node."""
        count = 0
        active = [i for i, st in enumerate(stages) if st.state == STAGE_ACTIVE]
        if model.phase == PHASE_RUNNING and active and xs:
            target = max(active)
            x_start, x_end = xs[0], xs[target]
            span = x_end - x_start
            live, queued = model.calls_in_flight, model.calls_queued
            waiting = queued and not live
            if span > 6 * s:
                count = max(3, min(14, 3 + live + queued // 8))
                if not waiting:
                    self._moving()
                speed = (22.0 if waiting else 95.0) * s
                color = AMBER if waiting else ACCENT_GLOW
                tail = (6.0 if waiting else 14.0) * s
                period = max(span / speed, 0.5)
                for i in range(count):
                    p = ((t / period) + i / count) % 1.0
                    px = x_start + p * span
                    fade = min(1.0, (1.0 - p) * 6.0, p * 8.0)
                    head = mix(BG, color, fade)
                    out.append(line(f"pk{i}_tail", (max(x_start, px - tail), y, px, y),
                                    fill=mix(BG, color, fade * 0.45), width=3 * s))
                    out.append(oval(f"pk{i}", px, y, 2.6 * s, fill=head))
        for i in range(count, 14):
            out.append(line(f"pk{i}_tail", (0, -10, 0, -10), fill=BG, width=1))
            out.append(oval(f"pk{i}", 0, -10, 0, fill=BG))

    # -- sheet board -------------------------------------------------------- #

    def _board(self, out, model, x0, y0, x1, y1, s, t) -> None:
        sheets = model.sheets
        n = len(sheets)
        counts = model.sheet_counts()
        cap_y = y0 + 6 * s
        out.append(text("brd_title", x0, cap_y, "SHEETS", fill=INK_DIM, size=9.5 * s,
                        weight="bold"))
        if n:
            done = counts.get(SHEET_DONE, 0)
            cached = counts.get(SHEET_CACHED, 0)
            failed = counts.get(SHEET_FAILED, 0)
            bits = [f"{done + cached + failed}/{n}"]
            if counts.get(SHEET_READING):
                bits.append(f"{counts[SHEET_READING]} reading")
            if counts.get(SHEET_QUEUED):
                bits.append(f"{counts[SHEET_QUEUED]} queued")
            if cached:
                bits.append(f"{cached} cached")
            if failed:
                bits.append(f"{failed} failed")
            crit = sum(sh.critique_done for sh in sheets)
            pending = sum(sh.critique_open + sh.critique_queued for sh in sheets)
            if crit or pending:
                bits.append(f"{crit} critique reads"
                            + (f" (+{pending} pending)" if pending else ""))
            caption = "  ·  ".join(bits)
        else:
            caption = "none loaded"
        out.append(text("brd_caption", x0 + 52 * s, cap_y,
                        fit(caption, x1 - x0 - 52 * s, 9.5 * s), fill=INK, size=9.5 * s))

        grid_top = y0 + 16 * s
        if not n:
            self._cell_hits = None
            if y1 - grid_top >= 36 * s:          # only where the placeholder fits
                cx, cy = (x0 + x1) / 2.0, (grid_top + y1) / 2.0
                out.append(poly("brd_empty", rounded_rect_points(x0, grid_top, x1, y1, 8 * s),
                                fill="", outline=INK_FAINT, width=1, smooth=True))
                out.append(text("brd_empty_t", cx, cy, "No sheets yet", fill=INK_FAINT,
                                size=12 * s, anchor="center"))
            return
        out.append(poly("brd_empty", (0, 0, 0, 0, 0, 0), fill=""))
        out.append(text("brd_empty_t", -100, -100, "", fill=BG, size=9))
        layout = board_layout(n, x0, grid_top, x1, y1)
        self._cell_hits = (layout, n)
        # A big board's shimmer moves in coarser color steps: each step is a
        # Tk call per cell, and on hundreds of tiny cells nobody sees 32.
        self._shimmer_steps = 32 if n <= 150 else 12 if n <= 600 else 6
        stagger = min(0.012, 1.4 / max(1, n))
        sweep = None
        if model.phase == PHASE_DONE and model.ended_at is not None:
            sp = (t - model.ended_at) / 1.1
            if 0.0 <= sp <= 1.25:
                sweep = layout.x0 + sp * (layout.cols * (layout.cell + layout.gap) + 30 * s)
                self._moving()
        hover_idx = self._hover_cell()
        for i, sh in enumerate(sheets):
            cx0, cy0, cx1, cy1 = cell_rect(layout, i)
            appear = (t - model.sheets_since - i * stagger) / 0.3
            if appear < 1.0:
                self._moving()
            if appear <= 0.0:
                out.append(rect(f"c{i}", cx0, cy0, cx0, cy0, fill=BG))
                continue
            grow = ease_out(appear)
            fill, fx = self._cell_style(sh, i, layout, t, s, live=model.phase == PHASE_RUNNING)
            if sweep is not None:
                d = abs((cx0 + cx1) / 2.0 - sweep) / (40 * s)
                if d < 1.0:
                    fill = mix(fill, WHITE, 0.55 * (1.0 - d))
            pad = (1.0 - grow) * layout.cell / 2.0
            pop = 0.0
            age = t - sh.changed_at
            if sh.state in SHEET_TERMINAL and age < 0.5 and model.phase != PHASE_IDLE:
                pop = 1.6 * s * (1.0 - age / 0.5)
                self._moving()
            outline = ""
            width = 0.0
            if i == hover_idx:
                outline, width = WHITE, 1.5 * s
            out.append(rect(f"c{i}", cx0 + pad - pop, cy0 + pad - pop, cx1 - pad + pop,
                            cy1 - pad + pop, fill=fill, outline=outline, width=width))
            if fx is not None:
                out.append(fx)
        if sweep is not None:
            top, bottom = layout.y0 - 2 * s, layout.y0 + layout.rows * (layout.cell + layout.gap)
            out.append(line("brd_sweep", (sweep, top, sweep, bottom), fill=GREEN_GLOW, width=2 * s))
        else:
            out.append(line("brd_sweep", (0, -10, 0, -10), fill=BG, width=1))

    def _steps(self, x: float) -> float:
        """Quantize a shimmer to the frame's step count (see ``_board``)."""
        q = self._shimmer_steps
        return round(x * q) / q

    def _cell_style(self, sh, i, layout, t, s, live=True) -> tuple[str, "Prim | None"]:
        """A cell's fill at time ``t``, plus its overlay (scan line / critique mark).

        ``live`` is whether a run is in flight: only then do queued and reading
        cells move (a finished board must come to rest)."""
        state = sh.state
        age = t - sh.changed_at
        cx0, cy0, cx1, cy1 = cell_rect(layout, i)
        size = layout.cell
        fx: "Prim | None" = None
        if state == SHEET_PENDING:
            fill = CELL_PENDING
        elif state == SHEET_RENDERED:
            fill = mix(ACCENT_GLOW, CELL_RENDERED, min(1.0, age / 0.6))
            if age < 0.6:
                self._moving()
        elif state == SHEET_QUEUED and not live:
            fill = AMBER_DIM
        elif state == SHEET_READING and not live:
            fill = ACCENT
        elif state == SHEET_QUEUED:
            row, col = divmod(i, max(1, layout.cols))
            wave = pulse(t, 3.2, phase=-(row + col) * 0.035)
            fill = mix(AMBER_DIM, "#9A6A12", self._steps(wave))
        elif state == SHEET_READING:
            self._moving()
            fill = mix(ACCENT, "#2756B8", pulse(t, 1.1, phase=i * 0.13))
            if size >= 7:
                frac = ((t * 0.9) + i * 0.37) % 1.0
                sx = cx0 + frac * size
                fx = line(f"c{i}_fx", (sx, cy0 + 1, sx, cy1 - 1), fill=WHITE,
                          width=max(1.0, size * 0.12))
        elif state == SHEET_DONE:
            fill = mix(WHITE, GREEN_SETTLED, min(1.0, age / 0.8))
        elif state == SHEET_CACHED:
            fill = mix(CYAN, TEAL, min(1.0, age / 0.8))
        else:
            fill = mix(WHITE, RED_SETTLED, min(1.0, age / 0.8))
        if state in SHEET_TERMINAL and age < 0.8:
            self._moving()
        if sh.hiccup_at is not None and t - sh.hiccup_at < 1.2:
            self._moving()
            if int((t - sh.hiccup_at) * 6) % 2 == 0:
                fill = RED
        # Critique: a purple mark in the corner (or a purple wash on tiny cells).
        if sh.critique_open or sh.critique_queued:
            glow = self._steps(pulse(t, 0.9 if sh.critique_open else 2.8, phase=i * 0.11))
            if fx is None and size >= 7:
                k = max(2.5, size * 0.38)
                fx = poly(f"c{i}_fx", (cx1 - k, cy0, cx1, cy0, cx1, cy0 + k),
                          fill=mix(PURPLE, PURPLE_GLOW, glow))
            else:
                fill = mix(fill, PURPLE, 0.35 + 0.35 * glow)
        elif sh.critique_done:
            if fx is None and size >= 7:
                k = max(2.5, size * 0.38)
                c_age = t - sh.critique_changed_at
                fx = poly(f"c{i}_fx", (cx1 - k, cy0, cx1, cy0, cx1, cy0 + k),
                          fill=mix(WHITE, PURPLE, min(1.0, c_age / 0.6)))
                if c_age < 0.6:
                    self._moving()
        return fill, fx

    def _hover_cell(self) -> "int | None":
        if self.hover is None or self._cell_hits is None:
            return None
        layout, n = self._cell_hits
        if not layout.cols:
            return None
        hx, hy = self.hover
        pitch = layout.cell + layout.gap
        col = int((hx - layout.x0) // pitch)
        row = int((hy - layout.y0) // pitch)
        if col < 0 or row < 0 or col >= layout.cols:
            return None
        i = row * layout.cols + col
        if i >= n:
            return None
        x0, y0, x1, y1 = cell_rect(layout, i)
        if x0 - layout.gap <= hx <= x1 + layout.gap and y0 - layout.gap <= hy <= y1 + layout.gap:
            return i
        return None

    # -- telemetry ---------------------------------------------------------- #

    def _telemetry(self, out, model, x0, y0, x1, y1, s, t, dt) -> None:
        cap_y = y0 + 6 * s
        show_findings = (model.phase == PHASE_DONE and model.findings is not None
                         and model.findings.total > 0)
        if show_findings:
            self._findings(out, model, x0, y0, x1, y1, s, t)
            return
        out.append(text("tm_title", x0, cap_y, "THROUGHPUT", fill=INK_DIM, size=9.5 * s,
                        weight="bold"))
        rate = self._shown.get("rate", model.throughput())
        out.append(text("tm_rate", x0 + 82 * s, cap_y, f"{fmt_tokens(rate)} tokens/s",
                        fill=CYAN, size=9.5 * s))
        top, bottom = y0 + 18 * s, y1 - 22 * s
        if bottom - top < 34 * s:
            # Compact panel: no room for a chart — the rate above and the
            # counters below still tell the story.
            self._chips(out, model, x0, y1 - 8 * s, s, t)
            return
        out.append(poly("tm_frame", rounded_rect_points(x0, top, x1, bottom, 6 * s),
                        fill=PANEL, outline=INK_FAINT, width=1, smooth=True))
        now_s = int(t)
        # The window grows with the run (20 s .. CHART_SECONDS), so the first
        # minute fills the chart instead of hugging its right edge.
        first = int(model.series[0][0]) if model.series else now_s
        span = max(20, min(self.CHART_SECONDS, now_s - first + 4))
        rates = smoothed_rates(model.series, now_s, span)
        peak = max(rates) if rates else 0.0
        target_max = max(peak * 1.18, 1.0)
        self._chart_max = self._ease("chart_max", target_max, dt, rate=2.5)
        cmax = max(self._chart_max, 1.0)
        ix0, ix1 = x0 + 6 * s, x1 - 6 * s
        iy0, iy1 = top + 8 * s, bottom - 4 * s
        n = len(rates)
        # Sub-second scroll so the chart glides instead of stepping.
        frac = (t - now_s) if model.phase == PHASE_RUNNING else 0.0
        step = (ix1 - ix0) / max(1, n - 1)
        pts: list[float] = []
        for i, v in enumerate(rates):
            px = ix0 + (i - frac) * step
            if px < ix0:
                px = ix0
            py = iy1 - (iy1 - iy0) * min(1.0, v / cmax)
            pts += [px, py]
        for gi, frac_y in enumerate((0.25, 0.5, 0.75)):
            gy = iy0 + (iy1 - iy0) * frac_y
            out.append(line(f"tm_g{gi}", (ix0, gy, ix1, gy), fill=GRID_MAJOR, width=1,
                            capstyle="butt"))
        if peak > 0 and len(pts) >= 4:
            area = [pts[0], iy1] + pts + [pts[-2], iy1]
            out.append(poly("tm_area", area, fill="#123A63", smooth=False))
            out.append(line("tm_line", pts, fill=CYAN, width=2 * s, smooth=True))
            hx, hy = pts[-2], pts[-1]
            glow = pulse(t, 1.0) if model.phase == PHASE_RUNNING else 0.0
            out.append(oval("tm_head_halo", hx, hy, (3 + 4 * glow) * s,
                            outline=mix(CYAN, PANEL, glow), width=1.2 * s))
            out.append(oval("tm_head", hx, hy, 2.6 * s, fill=WHITE))
            out.append(text("tm_max", ix0 + 2 * s, iy0 + 1 * s, f"{fmt_tokens(cmax)}/s",
                            fill=INK_FAINT, size=8.5 * s, anchor="nw"))
            out.append(text("tm_idle", -100, -100, "", fill=BG, size=9))
        else:
            out.append(poly("tm_area", (0, -10, 1, -10, 0, -11), fill=BG))
            out.append(line("tm_line", (0, -10, 1, -10), fill=BG, width=1))
            out.append(oval("tm_head_halo", 0, -10, 0, outline=BG))
            out.append(oval("tm_head", 0, -10, 0, fill=BG))
            out.append(text("tm_max", -100, -100, "", fill=BG, size=9))
            msg = ("Waiting for the first replies…" if model.phase == PHASE_RUNNING
                   else "Token flow appears here during a run")
            out.append(text("tm_idle", (ix0 + ix1) / 2, (iy0 + iy1) / 2, msg,
                            fill=INK_FAINT, size=10 * s, anchor="center"))
        self._chips(out, model, x0, y1 - 8 * s, s, t)

    def _chips(self, out, model, x, y, s, t) -> None:
        recent_retry = model.last_retry_at is not None and t - model.last_retry_at < 3.0
        if recent_retry:
            self._moving()
        chips = [
            ("ok", f"{model.calls_done} done", GREEN),
            ("live", f"{model.calls_in_flight} live", ACCENT_GLOW),
            ("queue", f"{model.calls_queued} queued", AMBER),
            ("retry", f"{model.retries} retries",
             mix(AMBER, WHITE, pulse(t, 0.5)) if recent_retry else
             (AMBER if model.retries else INK_DIM)),
        ]
        cx = x
        for key, label, color in chips:
            out.append(oval(f"chip_{key}_dot", cx + 4 * s, y, 3 * s, fill=color))
            out.append(text(f"chip_{key}", cx + 11 * s, y, label, fill=INK, size=9.5 * s))
            cx += 18 * s + text_width(label, 9.5 * s)

    def _findings(self, out, model, x0, y0, x1, y1, s, t) -> None:
        f = model.findings
        cap_y = y0 + 6 * s
        out.append(text("fd_title", x0, cap_y, "FINDINGS", fill=INK_DIM, size=9.5 * s,
                        weight="bold"))
        sev = f.by_severity
        sev_line = "  ·  ".join(
            f"{sev.get(k, 0)} {k}" for k in ("high", "medium", "low") if sev.get(k)
        )
        out.append(text("fd_total", x0 + 66 * s, cap_y,
                        fit(f"{f.total} total" + (f"  ·  {sev_line}" if sev_line else ""),
                            x1 - x0 - 66 * s, 9.5 * s),
                        fill=INK, size=9.5 * s))
        top, bottom = y0 + 18 * s, y1 - 22 * s
        out.append(poly("tm_frame", rounded_rect_points(x0, top, x1, bottom, 6 * s),
                        fill=PANEL, outline=INK_FAINT, width=1, smooth=True))
        grow = ease_out((t - (model.ended_at or t)) / 0.9)
        if grow < 1.0:
            self._moving()
        bx0, bx1 = x0 + 10 * s, x1 - 10 * s
        by0 = top + 12 * s
        by1 = by0 + 16 * s
        total = max(1, f.total)
        cursor = bx0
        span = (bx1 - bx0) * grow
        legend_y = by1 + 14 * s
        lx = bx0
        for key, label in FINDING_BUCKETS:
            n = f.by_status.get(key, 0)
            wseg = span * n / total
            color = BUCKET_COLOR[key]
            out.append(rect(f"fd_seg_{key}", cursor, by0, cursor + max(0.0, wseg - 1), by1,
                            fill=color if n else BG))
            cursor += wseg
            legend = f"{n} {label.lower()}"
            item_w = 11 * s + text_width(legend, 9.5 * s)
            if lx > bx0 and lx + item_w > bx1:
                lx, legend_y = bx0, legend_y + 15 * s      # wrap onto the next row
            out.append(oval(f"fd_dot_{key}", lx + 4 * s, legend_y, 3.5 * s,
                            fill=color if n else INK_FAINT))
            out.append(text(f"fd_leg_{key}", lx + 11 * s, legend_y, legend,
                            fill=INK if n else INK_FAINT, size=9.5 * s))
            lx += 11 * s + item_w
        cov = model.coverage
        if model.markup_expected:
            msg = (f"Markups proven in the PDF: {model.markup_written}/{model.markup_expected}"
                   + ("  ✓" if cov == "COMPLETE" else ""))
            color = GREEN_GLOW if cov == "COMPLETE" else AMBER
        else:
            msg, color = "", INK_DIM
        out.append(text("fd_cov", bx0, legend_y + 19 * s, msg, fill=color, size=9.5 * s))
        self._chips(out, model, x0, y1 - 8 * s, s, t)

    # -- ticker ------------------------------------------------------------- #

    def _ticker(self, out, model, x0, x1, y, s, t) -> None:
        item = model.ticker[-1] if model.ticker else None
        if item is None:
            return                     # nothing has happened yet: no caret either
        age = t - item.at
        color = {"good": GREEN_GLOW, "warn": AMBER, "bad": RED}.get(item.level, ACCENT_GLOW)
        reveal = min(1.0, age / 0.45)
        if reveal < 1.0 or age < 2.5:
            self._moving()
        shown = item.text[: max(1, int(len(item.text) * reveal))]
        caret = "▌" if reveal < 1.0 else ""
        out.append(text("tk_mark", x0, y, "›", fill=color, size=12 * s, weight="bold"))
        faded = mix(color, INK_DIM, min(1.0, max(0.0, (age - 1.0) / 1.5)))
        max_chars = int(max(10, (x1 - x0 - 16 * s) / (10.5 * s * 0.56)))
        out.append(text("tk_text", x0 + 12 * s, y, (shown + caret)[:max_chars], fill=faded,
                        size=10.5 * s))

    # -- tooltip ------------------------------------------------------------ #

    def _tooltip(self, out, model, w, h, s, t) -> None:
        lines: list[str] = []
        if self.hover is not None:
            hx, hy = self.hover
            idx = self._hover_cell()
            if idx is not None and idx < len(model.sheets):
                sh = model.sheets[idx]
                lines = [sh.label or sh.item, SHEET_STATE_TEXT.get(sh.state, sh.state)]
                if sh.critique_done or sh.critique_open or sh.critique_queued:
                    lines.append(f"critique reads: {sh.critique_done} done"
                                 + (f", {sh.critique_open + sh.critique_queued} pending"
                                    if sh.critique_open or sh.critique_queued else ""))
                if sh.tokens:
                    lines.append(f"{fmt_tokens(sh.tokens)} tokens this run")
            else:
                for nx, ny, nr, st in self._node_hits:
                    if (hx - nx) ** 2 + (hy - ny) ** 2 <= nr * nr:
                        lines = [st.long_label, self._stage_status_text(st)]
                        dur = st.duration(model._wall()) if st.started_at else None
                        if dur is not None:
                            lines.append(f"time: {fmt_duration(dur)}")
                        calls = st.calls_done + st.calls_open + st.calls_queued + st.calls_failed
                        if calls:
                            lines.append(f"calls: {st.calls_done} done"
                                         + (f", {st.calls_open} live" if st.calls_open else "")
                                         + (f", {st.calls_queued} queued" if st.calls_queued else "")
                                         + (f", {st.calls_failed} unfinished"
                                            if st.calls_failed else ""))
                        if st.note:
                            lines.append(st.note[:70])
                        break
            if not lines:
                # A view's own hover regions (live_tabs.py): the last one
                # registered wins, long lines are wrapped to fit the box.
                for tx0, ty0, tx1, ty1, tip in reversed(self._tips):
                    if tx0 <= hx <= tx1 and ty0 <= hy <= ty1:
                        for ln in tip:
                            lines.extend(self.wrap(("tip", ln), ln, 64)[:5] or [""])
                        break
        if not lines:
            out.append(poly("tip_box", (0, 0, 0, 0, 0, 0), fill=""))
            for i in range(TIP_LINES):
                out.append(text(f"tip_l{i}", -100, -100, "", fill=BG, size=9))
            return
        lines = lines[:TIP_LINES]
        size = 10 * s
        pad = 8 * s
        lh = 15 * s
        bw = max(text_width(ln, size) for ln in lines) + 2 * pad
        bh = len(lines) * lh + 2 * pad - 3 * s
        bx = min(max(4 * s, self.hover[0] + 14 * s), w - bw - 4 * s)
        by = self.hover[1] + 14 * s
        if by + bh > h - 4 * s:
            by = self.hover[1] - bh - 10 * s
        by = max(4 * s, by)
        out.append(poly("tip_box", rounded_rect_points(bx, by, bx + bw, by + bh, 6 * s),
                        fill="#0F2038", outline=ACCENT, width=1, smooth=True))
        for i in range(TIP_LINES):
            if i < len(lines):
                out.append(text(f"tip_l{i}", bx + pad, by + pad + i * lh + 5 * s, lines[i],
                                fill=INK if i == 0 else INK_DIM, size=size,
                                weight="bold" if i == 0 else "normal"))
            else:
                out.append(text(f"tip_l{i}", -100, -100, "", fill=BG, size=9))

    @staticmethod
    def _stage_status_text(st) -> str:
        if st.state == STAGE_ACTIVE:
            return "running now"
        if st.state == STAGE_DONE:
            return {"COMPLETE": "complete", "PARTIAL": "partial — see the run log",
                    "FAILED": "failed — the deliverable still ships",
                    "STOPPED": "stopped", "SKIPPED_VALID": "nothing to do"}.get(
                        st.status, st.status.lower() or "done")
        if st.state == STAGE_SKIPPED:
            return "did not run"
        return "planned"


# --------------------------------------------------------------------------- #
# The painter.
# --------------------------------------------------------------------------- #

_CREATE = {
    "rect": "create_rectangle",
    "oval": "create_oval",
    "line": "create_line",
    "poly": "create_polygon",
    "text": "create_text",
    "arc": "create_arc",
}


def _tk_opts(prim: Prim) -> dict:
    opts = dict(prim.opts)
    if prim.kind == "line":
        if not opts.get("dash"):
            opts["dash"] = ""
    return opts


class CanvasPainter:
    """Applies frames of :class:`Prim` to a Tk-like canvas, diffing by key.

    Only an item whose coordinates or options changed gets a Tk call; a key
    that disappears is deleted; when new items were created the canvas is
    restacked in frame order (later prims draw on top). ``canvas`` needs
    ``create_*``, ``coords``, ``itemconfigure``, ``delete`` and ``tag_raise``.
    """

    def __init__(self, canvas: Any) -> None:
        self.canvas = canvas
        self._items: dict[str, tuple[Any, Prim]] = {}
        self.calls = 0          # Tk calls made by the last paint (for pacing)

    def paint(self, prims: Iterable[Prim]) -> int:
        canvas = self.canvas
        calls = 0
        seen: set[str] = set()
        order: list[Any] = []
        first_new: "int | None" = None
        for p in prims:
            if p.key in seen:
                continue
            seen.add(p.key)
            cur = self._items.get(p.key)
            if cur is None or cur[1].kind != p.kind:
                if cur is not None:
                    canvas.delete(cur[0])
                    calls += 1
                iid = getattr(canvas, _CREATE[p.kind])(*p.coords, **_tk_opts(p))
                calls += 1
                if first_new is None:
                    first_new = len(order)
            else:
                iid, old = cur
                if old.coords != p.coords:
                    canvas.coords(iid, *p.coords)
                    calls += 1
                if old.opts != p.opts:
                    canvas.itemconfigure(iid, **_tk_opts(p))
                    calls += 1
            self._items[p.key] = (iid, p)
            order.append(iid)
        for key in [k for k in self._items if k not in seen]:
            canvas.delete(self._items.pop(key)[0])
            calls += 1
        if first_new is not None:
            # A new item lands on top of the stack; everything that follows it
            # in frame order is raised after it, so the stack matches the frame.
            # Items before the first new one are already in order.
            for iid in order[first_new:]:
                canvas.tag_raise(iid)
            calls += len(order) - first_new
        self.calls = calls
        return calls

    def clear(self) -> None:
        for iid, _p in self._items.values():
            try:
                self.canvas.delete(iid)
            except Exception:  # noqa: BLE001 - a destroyed canvas has nothing to clear
                pass
        self._items.clear()


# The insight tabs build on the primitives above, so this import comes last.
from . import live_tabs  # noqa: E402
