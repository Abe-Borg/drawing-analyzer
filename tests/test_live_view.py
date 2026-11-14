"""The GUI's Live view: the run reducer, the scene, the painter and the loop.

All hermetic and toolkit-free: the model reads a real ``RunJournal`` and a real
``CallTelemetry`` (the recorders a run hands its monitor), responses are the
shared ``FakeMessage`` / ``FakeUsage``, and the canvas is a recording fake
with a real stacking order.
"""
from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing_analyzer import call_telemetry
from drawing_analyzer.call_telemetry import CallTelemetry, sheet_item
from drawing_analyzer.core.pricing import usage_record_cost
from drawing_analyzer.live_panel import (
    AMBIENT_FRAME_MS,
    FRAME_MS,
    HIDDEN_POLL_MS,
    INPUT_QUIET_MS,
    LivePanel,
)
from drawing_analyzer.live_scene import (
    CanvasPainter,
    LiveScene,
    board_layout,
    cell_rect,
    oval,
    rect,
    text,
)
from drawing_analyzer.live_view import (
    PHASE_DONE,
    PHASE_STOPPED,
    SHEET_CACHED,
    SHEET_DONE,
    SHEET_FAILED,
    SHEET_QUEUED,
    SHEET_READING,
    SHEET_RENDERED,
    STAGE_ACTIVE,
    STAGE_DONE,
    STAGE_PLANNED,
    STAGE_SKIPPED,
    LiveRunModel,
    RunMonitor,
    notify_monitor,
    planned_stages,
)
from drawing_analyzer.models import RunUsage, SheetRef, resolve_run_configuration
from drawing_analyzer.run_journal import RunJournal
from tests.fixtures.fake_anthropic import FakeMessage, FakeUsage


class _Clock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _refs(n: int, *, name: str = "M-101.pdf", source: str = "SRC-0001") -> list[SheetRef]:
    return [SheetRef(pdf_path=Path(name), page_index=i, source_name=name, page_count=n,
                     source_id=source) for i in range(n)]


def _live_run(refs, *, qc: bool = True):
    """A model armed for a run, watching a monitor wired like the pipeline wires it."""
    journal, calls = RunJournal(), CallTelemetry()
    monitor = RunMonitor()
    monitor.attach(journal=journal, pressure=SimpleNamespace(calls=calls, requested_speed=None),
                   config=resolve_run_configuration(qc_markups=qc))
    monitor.set_sheets(refs)
    clock = _Clock()
    model = LiveRunModel(clock=clock, wall_clock=lambda: 1_700_000_000.0 + clock.t)
    model.begin()
    return SimpleNamespace(model=model, monitor=monitor, journal=journal, calls=calls, clock=clock)


def _call(calls, stage, item, model="claude-opus-5-5"):
    with call_telemetry.scope(stage, item):
        return calls.begin({"model": model, "max_tokens": 32_000, "messages": []},
                           method="stream")


def _reply(inp=10_000, out=2_000, stop="end_turn"):
    return FakeMessage(content=[], stop_reason=stop,
                       usage=FakeUsage(input_tokens=inp, output_tokens=out))


# --------------------------------------------------------------------------- #
# The reducer
# --------------------------------------------------------------------------- #


def test_sheet_follows_its_real_time_read_and_the_run_outcome_settles_it():
    refs = _refs(3)
    r = _live_run(refs)
    r.journal.emit("RUN_START", files=1)
    r.journal.emit("STAGE_START", stage="digest", sheets=3)
    r.journal.emit("SHEET_RENDERED", stage="digest", sheet=refs[0].display_label)
    rec = _call(r.calls, "digest", sheet_item(refs[0]))
    r.model.poll(r.monitor)
    s0, s1, s2 = r.model.sheets
    assert s0.state == SHEET_READING
    assert r.model.calls_in_flight == 1
    assert r.model._stage("inventory").state == STAGE_DONE    # the read began

    # A cut-off first attempt does not finish the sheet; the retry does.
    r.calls.finish(rec, message=_reply(stop="max_tokens"))
    r.clock.t += 1
    r.model.poll(r.monitor)
    assert s0.state == SHEET_READING and s0.hiccup_at == r.clock.t
    rec = _call(r.calls, "digest", sheet_item(refs[0]))
    r.calls.finish(rec, message=_reply(inp=50_000, out=4_000))
    r.clock.t += 1
    r.model.poll(r.monitor)
    assert s0.state == SHEET_DONE
    assert r.model.calls_in_flight == 0

    # The run's own per-sheet outcome is authoritative for the rest.
    for ref, cached, status in ((refs[1], True, "OK"), (refs[2], False, "FAILED")):
        r.journal.emit("SHEET_DIGESTED", stage="digest", sheet=ref.display_label,
                       source=ref.source_id, status=status, cached=cached)
    r.journal.emit("STAGE_END", stage="digest", status="PARTIAL")
    r.model.poll(r.monitor)
    assert (s1.state, s2.state) == (SHEET_CACHED, SHEET_FAILED)
    digest = r.model._stage("digest")
    assert (digest.state, digest.status, digest.calls_done, digest.calls_failed) == (
        STAGE_DONE, "PARTIAL", 1, 1)


def test_batch_items_queue_on_their_sheets_even_when_labelled_after_listing():
    refs = _refs(2)
    r = _live_run(refs)
    reqs = [{"custom_id": f"c{i}", "params": {"model": "claude-opus-5-5", "max_tokens": 8}}
            for i in range(2)]
    with call_telemetry.scope("digest"):
        # The recorder lists a record a moment before it sets the item on it;
        # the board must still find the sheet on a later poll.
        r.calls.note_batch_submit("b1", reqs, items={})
    r.model.poll(r.monitor)
    assert [s.state for s in r.model.sheets] == ["pending", "pending"]
    for rec, ref in zip(r.calls.records, refs):
        rec.item = sheet_item(ref)
    r.model.poll(r.monitor)
    assert [s.state for s in r.model.sheets] == [SHEET_QUEUED, SHEET_QUEUED]
    assert r.model.calls_queued == 2 and r.model.calls_in_flight == 0

    r.calls.note_batch_results("b1", {"c1": {"result": {"type": "succeeded",
                                                        "message": _reply()}}})
    r.model.poll(r.monitor)
    assert [s.state for s in r.model.sheets] == [SHEET_QUEUED, SHEET_DONE]


@pytest.mark.parametrize("ledger_cost", [Decimal("1.25"), None])
def test_tokens_and_cost_count_once_even_when_polled_mid_update(ledger_cost):
    refs = _refs(1)
    r = _live_run(refs)
    rec = _call(r.calls, "digest", sheet_item(refs[0]))
    # describe_response() sets the outcome before the token counts; a poll can
    # land between the two.
    rec.outcome = "OK"
    r.model.poll(r.monitor)
    assert (r.model.tokens_in, r.model.tokens_out) == (0, 0)
    rec.input_tokens, rec.output_tokens, rec.cache_read_tokens = 30_000, 3_000, 5_000
    r.clock.t += 0.5
    r.model.poll(r.monitor)
    r.clock.t += 0.5
    r.model.poll(r.monitor)
    assert (r.model.tokens_in, r.model.tokens_out) == (35_000, 3_000)
    expected = usage_record_cost(model="claude-opus-5-5", input_tokens=30_000,
                                 output_tokens=3_000, cache_read_tokens=5_000)
    assert r.model.cost == expected and r.model.cost_known and not r.model.cost_final
    assert sum(b[1] + b[2] for b in r.model.series) == 38_000

    # The run's own ledger is final. When it cannot price everything, the
    # spend is unknown — the partial live estimate must not stand in for it.
    ctx = SimpleNamespace(total_estimated_cost=ledger_cost, run_usage=RunUsage(), findings=[],
                          reference_findings=[], qc_status="", coverage_status="", sheets=[])
    r.model.finish(ctx, r.monitor)
    if ledger_cost is None:
        assert not r.model.cost_known
    else:
        assert r.model.cost == ledger_cost and r.model.cost_final and r.model.cost_known


def test_critique_reads_mark_their_sheet_and_shared_basenames_resolve_by_source():
    a, b = _refs(1, source="SRC-0001"), _refs(1, source="SRC-0002")   # same file name
    r = _live_run(a + b)
    rec = _call(r.calls, "critique", f"{sheet_item(b[0])}:critique_1")
    r.model.poll(r.monitor)
    first, second = r.model.sheets
    assert (first.critique_open, second.critique_open) == (0, 1)
    r.calls.finish(rec, message=_reply())
    r.model.poll(r.monitor)
    assert (second.critique_open, second.critique_done) == (0, 1)

    r.journal.emit("SHEET_DIGESTED", stage="digest", sheet=b[0].display_label,
                   source="SRC-0002", status="FAILED", cached=False)
    r.journal.emit("SHEET_DIGESTED", stage="digest", sheet=a[0].display_label,
                   source="SRC-0001", status="OK", cached=True)
    r.model.poll(r.monitor)
    assert (first.state, second.state) == (SHEET_CACHED, SHEET_FAILED)


@pytest.mark.parametrize("qc, audit, expect_in, expect_out", [
    (True, False, {"critique", "verification", "markup", "citation"}, set()),
    (False, True, {"auditors", "anchor"}, {"critique", "verification", "markup"}),
    (False, False, {"inventory", "digest"}, {"critique", "auditors", "markup"}),
])
def test_the_track_follows_the_resolved_configuration(qc, audit, expect_in, expect_out):
    config = resolve_run_configuration(qc_markups=qc, reference_audit=audit, synthesize=True)
    plan = planned_stages(config)
    assert expect_in <= set(plan) and not (expect_out & set(plan))
    assert plan[:2] == ["inventory", "digest"]


def test_unplanned_stages_join_in_order_and_unstarted_ones_end_skipped():
    refs = _refs(2)
    r = _live_run(refs, qc=False)
    r.journal.emit("RUN_START", files=1)
    r.journal.emit("STAGE_START", stage="digest", sheets=2)
    r.journal.emit("STAGE_START", stage="focus")          # not in a no-focus plan
    r.journal.emit("STAGE_START", stage="tile_artifacts")  # never drawn
    _call(r.calls, "digest", sheet_item(refs[1]))         # a read in flight
    r.model.poll(r.monitor)
    assert r.model.sheets[1].state == SHEET_READING
    names = [s.name for s in r.model.stages]
    assert "tile_artifacts" not in names
    assert names.index("digest") < names.index("focus")
    assert r.model._stage("focus").state == STAGE_ACTIVE

    r.model.stop(PHASE_STOPPED, monitor=r.monitor)
    # Stopped mid-read: the sheet was never read, and nothing is in flight.
    assert r.model.sheets[1].state == SHEET_RENDERED and r.model.calls_in_flight == 0
    states = {s.name: (s.state, s.status) for s in r.model.stages}
    assert states["focus"] == (STAGE_DONE, "STOPPED")
    assert all(st == STAGE_SKIPPED for name, (st, _s) in states.items()
               if name not in ("inventory", "digest", "focus"))


def test_preview_survives_option_toggles_but_not_a_new_set():
    model = LiveRunModel(clock=_Clock(), wall_clock=lambda: 0.0)
    rows = [(sheet_item(ref), ref.display_label, ref.source_id) for ref in _refs(4)]
    model.preview(rows, ["inventory", "digest"])
    cells = list(model.sheets)
    model.preview(rows, ["inventory", "digest", "critique"])   # QC ticked
    assert model.sheets == cells and model._stage("critique").state == STAGE_PLANNED

    model.preview(rows, ["inventory", "digest"], revision="rev-1")
    model.begin()
    assert model.sheets == cells                               # no re-cascade
    model.finish(None)
    model.preview(rows, ["inventory", "digest"], revision="rev-1")   # same set: stays
    assert model.phase == PHASE_DONE
    # The same files overwritten in place: same sheet ids, new content.
    model.preview(rows, ["inventory", "digest"], revision="rev-2")
    assert model.phase != PHASE_DONE
    model.finish(None)
    model.preview(rows[:2], ["inventory", "digest"], revision="rev-2")   # a new set
    assert len(model.sheets) == 2 and model.phase != PHASE_DONE


def test_monitor_and_notify_never_raise():
    monitor = RunMonitor()
    monitor.set_sheets([object(), None])          # junk refs
    monitor.attach(journal=object())
    notify_monitor(None, "attach")                # no monitor given
    notify_monitor(SimpleNamespace(attach=lambda **kw: 1 / 0), "attach", journal=1)
    notify_monitor(object(), "set_sheets", [])    # no such method
    model = LiveRunModel()
    model.begin()
    model.poll(monitor)                           # a journal with no events list


# --------------------------------------------------------------------------- #
# Scene + painter
# --------------------------------------------------------------------------- #


class _FakeCanvas:
    """Records Tk calls and keeps a real stacking order."""

    def __init__(self, w: int = 800, h: int = 280) -> None:
        self.items: dict[int, dict] = {}
        self.stack: list[int] = []
        self.calls: list[str] = []
        self.w, self.h = w, h
        self._next = 1

    def _create(self, kind, *coords, **opts):
        iid, self._next = self._next, self._next + 1
        self.items[iid] = {"kind": kind, "coords": coords, "opts": dict(opts)}
        self.stack.append(iid)
        self.calls.append("create")
        return iid

    def __getattr__(self, name):
        if name.startswith("create_"):
            return lambda *c, **o: self._create(name[7:], *c, **o)
        raise AttributeError(name)

    def coords(self, iid, *coords):
        self.items[iid]["coords"] = coords
        self.calls.append("coords")

    def itemconfigure(self, iid, **opts):
        self.items[iid]["opts"].update(opts)
        self.calls.append("itemconfigure")

    def delete(self, iid):
        self.items.pop(iid)
        self.stack.remove(iid)
        self.calls.append("delete")

    def tag_raise(self, iid):
        self.stack.remove(iid)
        self.stack.append(iid)
        self.calls.append("tag_raise")

    def tag_lower(self, iid, below):
        self.stack.remove(iid)
        self.stack.insert(self.stack.index(below), iid)
        self.calls.append("tag_lower")

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h


def test_painter_touches_only_what_changed_and_stacks_in_frame_order():
    canvas = _FakeCanvas()
    painter = CanvasPainter(canvas)
    keys = lambda: [k for iid in canvas.stack for k, (i, _p) in painter._items.items() if i == iid]  # noqa: E731

    frame = [rect("a", 0, 0, 5, 5, fill="#111111"), rect("b", 1, 1, 6, 6, fill="#222222"),
             text("c", 2, 2, "x", fill="#333333", size=10)]
    painter.paint(frame)
    assert keys() == ["a", "b", "c"]
    canvas.calls.clear()
    assert painter.paint(frame) == 0 and canvas.calls == []

    frame2 = [rect("a", 0, 0, 5, 5, fill="#FFFFFF"), oval("d", 3, 3, 2, fill="#444444"),
              text("c", 2, 2, "x", fill="#333333", size=10)]
    painter.paint(frame2)
    # The new item is slotted in with one call, not by raising all above it.
    assert sorted(canvas.calls) == ["create", "delete", "itemconfigure", "tag_lower"]
    assert keys() == ["a", "d", "c"]                 # new item slotted in, not on top
    a_id = painter._items["a"][0]
    assert canvas.items[a_id]["opts"]["fill"] == "#FFFFFF"

    painter.paint([oval("a", 0, 0, 3)] + frame2[1:])   # kind changed: replaced in place
    assert canvas.items[painter._items["a"][0]]["kind"] == "oval"
    assert keys() == ["a", "d", "c"]

    # Several new items between survivors keep their frame order.
    frame3 = [oval("a", 0, 0, 3), rect("e", 0, 0, 1, 1), rect("f", 0, 0, 2, 2),
              oval("d", 3, 3, 2, fill="#444444"), rect("g", 0, 0, 3, 3),
              text("c", 2, 2, "x", fill="#333333", size=10), rect("h", 0, 0, 4, 4)]
    painter.paint(frame3)
    assert keys() == ["a", "e", "f", "d", "g", "c", "h"]
    # Survivors that swap places are restacked whole.
    painter.paint([frame3[5], *frame3[:5], frame3[6]])
    assert keys() == ["c", "a", "e", "f", "d", "g", "h"]

    # A changed option is the only one sent: re-sending a text's font or
    # string makes Tk lay the item out again.
    canvas.calls.clear()
    c_id = painter._items["c"][0]
    canvas.items[c_id]["opts"] = {}
    painter.paint([text("c", 2, 2, "x", fill="#FFFFFF", size=10), *frame3[:5], frame3[6]])
    assert canvas.calls == ["itemconfigure"] and canvas.items[c_id]["opts"] == {"fill": "#FFFFFF"}


@pytest.mark.parametrize("n", [1, 7, 48, 600, 2500])
def test_board_cells_fit_their_area_without_overlapping(n):
    x0, y0, x1, y1 = 12.0, 120.0, 460.0, 240.0
    layout = board_layout(n, x0, y0, x1, y1)
    rects = [cell_rect(layout, i) for i in range(n)]
    assert all(x0 <= a and b <= x1 + 0.01 and y0 <= c and d <= y1 + 0.01
               for a, c, b, d in rects)
    pitch = layout.cell + layout.gap
    assert layout.cell > 0 and pitch * layout.cols <= (x1 - x0) + 0.01
    if n > 1:
        (_, _, ax1, _), (bx0, _, _, _) = rects[0], rects[1 if layout.cols > 1 else 0]
        assert layout.cols == 1 or bx0 >= ax1


def _model_in(phase: str, n: int):
    refs = _refs(n)
    r = _live_run(refs)
    r.journal.emit("RUN_START", files=1)
    r.journal.emit("STAGE_START", stage="digest", sheets=n)
    for ref in refs[: n // 2]:
        rec = _call(r.calls, "digest", sheet_item(ref))
        r.calls.finish(rec, message=_reply())
    _call(r.calls, "digest", sheet_item(refs[-1]))
    r.model.poll(r.monitor)
    if phase == PHASE_DONE:
        findings = [SimpleNamespace(id=f"QC-{i}", severity=sev, verification=SimpleNamespace(
            status=st)) for i, (sev, st) in enumerate(
                [("high", "VERIFIED"), ("low", "REJECTED"), ("medium", "UNCERTAIN")])]
        r.model.finish(SimpleNamespace(total_estimated_cost=Decimal("3"), run_usage=None,
                                       findings=findings, reference_findings=[],
                                       qc_status="COMPLETE", coverage_status="COMPLETE",
                                       sheets=[]), r.monitor)
    return r


@pytest.mark.parametrize("phase", ["RUNNING", PHASE_DONE])
@pytest.mark.parametrize("n, w, h, scale", [(5, 800, 270, 1.0), (300, 1200, 420, 1.5),
                                            (48, 420, 240, 1.0), (24, 800, 170, 1.0),
                                            (24, 800, 120, 1.0)])
def test_every_frame_is_drawable_and_a_finished_board_comes_to_rest(phase, n, w, h, scale):
    r = _model_in(phase, n)
    scene = LiveScene()
    scene.hover = (40.0 * scale, 150.0 * scale)
    prims = scene.build(r.model, w, h, r.clock.t, scale=scale)
    keys = [p.key for p in prims]
    assert len(keys) == len(set(keys))
    assert all(math.isfinite(c) for p in prims for c in p.coords)
    cells = [p for p in prims if p.key.startswith("c") and p.key[1:].isdigit()]
    assert len(cells) == (n if h >= 150 else 0)     # a squeezed panel sheds the board
    assert all(0 <= p.coords[0] and p.coords[2] <= w and p.coords[3] <= h for p in cells)
    if phase == "RUNNING":
        assert scene.animating
    else:
        later = r.clock.t + 30
        scene.build(r.model, w, h, later, scale=scale)
        scene.build(r.model, w, h, later + 0.04, scale=scale)
        assert not scene.animating        # nothing moves, so the loop can rest


def test_hovering_a_cell_names_that_sheet():
    r = _model_in("RUNNING", 10)
    scene = LiveScene()
    scene.build(r.model, 800, 270, r.clock.t)
    layout, _n = scene._cell_hits
    x0, y0, x1, y1 = cell_rect(layout, 7)
    scene.hover = ((x0 + x1) / 2, (y0 + y1) / 2)
    prims = scene.build(r.model, 800, 270, r.clock.t)
    tip = [dict(p.opts)["text"] for p in prims if p.key.startswith("tip_l")]
    assert r.model.sheets[7].label in tip


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #


class _Scheduler:
    def __init__(self) -> None:
        self.pending: list = []

    def schedule(self, delay, fn):
        self.pending.append((delay, fn))
        return len(self.pending)

    def run_next(self):
        delay, fn = self.pending.pop(0)
        fn()
        return delay


def test_loop_draws_while_shown_polls_while_hidden_and_rests_when_idle():
    canvas, sched, clock = _FakeCanvas(), _Scheduler(), _Clock()
    shown = {"on": True}
    panel = LivePanel(canvas, schedule=sched.schedule, cancel=lambda h: None,
                      visible=lambda: shown["on"], clock=clock)
    panel.preview([(sheet_item(ref), ref.display_label, ref.source_id) for ref in _refs(3)],
                  ["inventory", "digest"])
    while sched.pending:                  # the cascade-in plays, then the loop rests
        sched.run_next()
        clock.t += 0.1
    assert canvas.items and not sched.pending

    monitor = panel.begin()
    assert isinstance(monitor, RunMonitor)
    assert sched.run_next() == 0          # kicked
    assert sched.pending and sched.pending[0][0] < HIDDEN_POLL_MS

    # Input elsewhere in the window: the next frame waits instead of drawing,
    # then drawing resumes.
    sched.run_next()
    panel.note_input()
    panel.last_frame_ms = None
    sched.run_next()
    assert panel.last_frame_ms is None                       # polled, not drawn
    assert INPUT_QUIET_MS <= sched.pending[0][0] <= INPUT_QUIET_MS + 1
    clock.t += INPUT_QUIET_MS / 1000.0 + 0.01
    sched.run_next()
    assert panel.last_frame_ms is not None

    shown["on"] = False                   # collapsed mid-run
    canvas.calls.clear()
    sched.run_next()
    assert canvas.calls == [] and sched.pending[0][0] == HIDDEN_POLL_MS

    panel.finish(None)
    assert panel.monitor is None


def test_a_failing_frame_never_escapes_the_loop(monkeypatch):
    canvas, sched = _FakeCanvas(), _Scheduler()
    panel = LivePanel(canvas, schedule=sched.schedule, cancel=lambda h: None)
    panel.begin()

    def boom(*a, **k):
        raise RuntimeError("scene bug")

    monkeypatch.setattr(panel.scene, "build", boom)
    sched.run_next()                      # must not raise
    assert sched.pending                  # and the run keeps being followed


@pytest.mark.parametrize("batch, expected", [(False, FRAME_MS), (True, AMBIENT_FRAME_MS)])
def test_a_batch_wait_is_drawn_at_the_ambient_rate(monkeypatch, batch, expected):
    """A real-time read streams (scan lines, packets) at the full rate; a set
    waiting hours in the batch queue only shimmers, at a fraction of the cost."""
    from drawing_analyzer import live_panel

    monkeypatch.setattr(live_panel.time, "perf_counter", lambda: 0.0)   # free frames
    canvas, sched, clock = _FakeCanvas(), _Scheduler(), _Clock()
    panel = LivePanel(canvas, schedule=sched.schedule, cancel=lambda h: None, clock=clock)
    refs = _refs(4)
    monitor = panel.begin()
    calls = CallTelemetry()
    monitor.attach(journal=RunJournal(), pressure=SimpleNamespace(calls=calls,
                                                                  requested_speed=None))
    monitor.set_sheets(refs)
    if batch:
        reqs = [{"custom_id": f"c{i}", "params": {"model": "claude-opus-5-5"}} for i in range(4)]
        with call_telemetry.scope("digest"):
            calls.note_batch_submit("b", reqs, items={f"c{i}": sheet_item(r)
                                                      for i, r in enumerate(refs)})
    else:
        _call(calls, "digest", sheet_item(refs[0]))
    delay = None
    for _ in range(40):                    # let every one-off transition finish
        delay = sched.run_next()
        clock.t += 0.25
    assert sched.pending[0][0] == expected and delay == expected


# --------------------------------------------------------------------------- #
# The insight tabs: Story, Thinking, Plan, Findings
# --------------------------------------------------------------------------- #


def _finding(i: int, severity: str, *, source: str = "digest_json"):
    from drawing_analyzer.models import Finding

    f = Finding(sheet_id=f"FP-{200 + i}", source_name="M-101.pdf", page_index=i,
                category="conflict", severity=severity, source_id="SRC-0001",
                text=f"Schedule and plan disagree about item {i}, " + "which matters " * 12,
                source_quote=f"quote {i}")
    f.sources = [source]
    return f


def _insight_run(n_sheets: int = 4, *, items: int = 3, findings: int = 4, thoughts: int = 3):
    """A QC run mid-critique that has published its plan, answers, ledger and
    reasoning the way the pipeline does."""
    from drawing_analyzer.ledger import Ledger
    from drawing_analyzer.models import AdoptedCode, SetIdentity
    from drawing_analyzer.profiles import MODEL_PLAN_PREFIX, ChecklistPlan, Profile
    from drawing_analyzer.thought_stream import ThoughtStream

    refs = _refs(n_sheets)
    r = _live_run(refs)
    r.refs = refs
    r.feed = ThoughtStream(clock=r.clock)
    r.monitor.parts().pressure.thoughts = r.feed
    r.journal.emit("RUN_START", files=1)
    r.journal.emit("STAGE_START", stage="digest", sheets=n_sheets)
    r.journal.emit("STAGE_END", stage="digest", status="COMPLETE")
    r.journal.emit("STAGE_START", stage="critique", sheets=n_sheets)
    r.monitor.publish("identity", SetIdentity(
        disciplines=("fire protection", "mechanical"), project_type="Data center",
        jurisdiction="Loudoun County", units="Imperial",
        adopted_codes=(AdoptedCode(code="NFPA 13", edition="2025", origin="operator"),
                       AdoptedCode(code="NFPA 72", edition="2022", origin="model")),
        mentioned_codes=(AdoptedCode(code="NFPA 13", edition="2019", origin="regex"),),
    ))
    r.plan = ChecklistPlan([
        Profile(name="upload:fp.md", title="Office checklist",
                items=tuple(f"Office check number {i} is satisfied" for i in range(items))),
        Profile(name=MODEL_PLAN_PREFIX + "fire-protection", title="Fire protection",
                items=tuple(f"NFPA 13 (2025) section {i}: the plan complies" for i in range(items))),
    ])
    r.answers = {}
    r.monitor.publish("checklist", r.plan)
    r.monitor.publish("checklist_answers", r.answers)
    r.ledger = Ledger()
    r.findings = [_finding(i, ("high", "medium", "low")[i % 3]) for i in range(findings)]
    r.ledger.add(r.findings)
    r.monitor.publish("ledger", r.ledger)
    r.monitor.publish("digests", [SimpleNamespace(findings=[1, 2]) for _ in refs])
    for i in range(thoughts):
        th = r.feed.open(stage="critique", item=sheet_item(refs[i % n_sheets]) + ":1",
                         model="claude-opus-5-5")
        r.feed.add_thinking(th, f"Thought {i}: " + "the schedule and the plan disagree. " * 6)
        r.feed.close(th)
    return r


def test_the_insight_tabs_read_the_runs_own_objects_as_they_fill():
    r = _insight_run(findings=3)
    r.ledger.add([_finding(9, "low", source="auditor_reference")])
    u1, m1 = r.plan.items[0].id, r.plan.items[-1].id
    r.answers[("SRC-0001", 0)] = {u1: ["MET", "VIOLATED"], m1: ["MET", "MET"]}
    r.answers[("SRC-0001", 1)] = {u1: ["MET"]}
    r.model.poll(r.monitor)
    m = r.model

    assert [(c.code, c.edition, c.adopted, c.origin) for c in m.identity.codes] == [
        ("NFPA 13", "2025", True, "operator"), ("NFPA 72", "2022", True, "model"),
        ("NFPA 13", "2019", False, "regex")]
    assert [(g.origin, g.title, len(g.items)) for g in m.checklist] == [
        ("user", "Office checklist", 3), ("model", "Fire protection", 3)]
    by_id = {it.id: it.counts for g in m.checklist for it in g.items}
    # One sheet's two reads disagree: the run's precedence makes that sheet a
    # violation, so the item is flagged on one sheet and met on the other.
    assert by_id[u1] == {"VIOLATED": 1, "MET": 1} and by_id[m1] == {"MET": 1}
    assert m.checklist_sheets == 2
    assert (m.ledger_total, m.ledger_offline, m.found) == (4, 1, {"digest": 8})
    assert m.merged_reports() == 5                       # 8 reported, 3 entries from reads
    assert m.ledger_by["bucket"] == {"unchecked": 4}
    assert [f.severity for f in m.ledger_findings][:2] == ["high", "medium"]
    assert m.item_label(m.thoughts[0].item) == r.refs[0].display_label + " · read 1"
    assert (m.thoughts_seen, m.thoughts_with_text, m.thoughts_enabled) == (3, 3, True)

    # The run keeps working on the same objects: a verdict lands, an anchor is
    # found, a sheet answers. The tabs pick it up on their next refresh, not
    # on every frame.
    r.findings[0].verification.status = "REJECTED"
    r.findings[1].anchor.status = "EXACT"
    r.answers[("SRC-0001", 2)] = {u1: ["VIOLATED"]}
    r.clock.t += 0.1
    m.poll(r.monitor)
    assert m.ledger_by["bucket"] == {"unchecked": 4} and m.checklist_sheets == 2
    changed_before = m.insights_changed_at
    r.clock.t += 1.0
    m.poll(r.monitor)
    assert m.ledger_by["bucket"] == {"rejected": 1, "unchecked": 3}
    assert m.ledger_by["anchor"] == {"exact": 1, "unplaced": 3}
    assert {it.id: it.counts for g in m.checklist for it in g.items}[u1] == {
        "VIOLATED": 2, "MET": 1}
    assert m.insights_changed_at > changed_before

    # The run's last word is read unthrottled when it returns.
    r.findings[2].verification.status = "VERIFIED"
    m.finish(None, r.monitor)
    assert m.ledger_by["bucket"]["verified"] == 1


def test_a_run_without_a_feed_says_so_and_an_odd_published_object_blanks_only_its_tab():
    r = _insight_run()
    r.monitor.parts().pressure.thoughts = None
    r.monitor.publish("checklist", object())             # not a plan
    r.monitor.publish("identity", 42)
    r.model.poll(r.monitor)
    assert r.model.thoughts_enabled is False and r.model.thoughts == []
    assert r.model.checklist == []
    assert r.model.ledger_total == 4                      # the other tabs still filled


_TABS = ["story", "mind", "plan", "findings"]


@pytest.mark.parametrize("tab", _TABS)
@pytest.mark.parametrize("phase", ["RUNNING", PHASE_DONE])
@pytest.mark.parametrize("w, h, scale", [(980, 420, 1.0), (520, 230, 1.0), (1400, 600, 1.5)])
def test_every_tab_is_drawable_stays_inside_the_panel_and_rests_when_the_run_is_over(
        tab, phase, w, h, scale):
    r = _insight_run(findings=40, items=30, thoughts=12)
    r.model.poll(r.monitor)
    if phase == PHASE_DONE:
        r.model.finish(None, r.monitor)
    scene = LiveScene()
    assert scene.set_tab(tab)
    scene.hover = (w * 0.5, h * 0.6)
    prims = scene.build(r.model, w, h, r.clock.t, scale=scale)
    keys = [p.key for p in prims]
    assert len(keys) == len(set(keys))
    assert all(math.isfinite(c) for p in prims for c in p.coords)
    body = [p for p in prims if p.kind == "text" and dict(p.opts)["text"]
            and not p.key.startswith(("tip_", "hud_", "tk_", "tab_"))]
    assert body and all(0 <= p.coords[0] <= w and 0 <= p.coords[1] <= h for p in body)
    assert not any(p.key.startswith("c") and p.key[1:].isdigit() for p in prims)   # no board
    if phase == PHASE_DONE:
        later = r.clock.t + 60
        scene.build(r.model, w, h, later, scale=scale)
        scene.build(r.model, w, h, later + 0.04, scale=scale)
        assert not scene.animating


def _texts(prims, prefix: str) -> list[str]:
    return [dict(p.opts)["text"] for p in prims if p.kind == "text" and p.key.startswith(prefix)]


def _settle(scene, model, clock, w=980, h=300):
    """Draw until the scroll easing has arrived; returns the last frame."""
    prims = []
    for _ in range(40):
        clock.t += 0.1
        prims = scene.build(model, w, h, clock.t)
    return prims


@pytest.mark.parametrize("tab, prefix, first, last", [
    ("plan", "ck", "U1.1", "M1.30"),
    ("findings", "fl", "FP-200", "FP-238"),
])
def test_a_long_list_scrolls_from_its_first_row_to_its_last_and_no_further(
        tab, prefix, first, last):
    r = _insight_run(findings=40, items=30)
    r.model.poll(r.monitor)
    scene = LiveScene()
    scene.set_tab(tab)
    shown = _texts(_settle(scene, r.model, r.clock), prefix)
    assert first in shown and last not in shown
    scene.wheel(+5)                                       # already at the top
    assert scene.scroll[tab] == 0.0
    scene.wheel(-10_000)
    shown = _texts(_settle(scene, r.model, r.clock), prefix)
    assert last in shown and first not in shown
    limit = scene.scroll[tab]
    scene.wheel(-3)
    assert scene.scroll[tab] == limit > 0


def test_the_thinking_feed_follows_the_newest_until_the_reader_scrolls_away():
    r = _insight_run(thoughts=14)
    r.model.poll(r.monitor)
    scene = LiveScene()
    scene.set_tab("mind")
    newest = lambda prims: any("Thought 13:" in t for t in _texts(prims, "mi_l"))   # noqa: E731
    assert newest(_settle(scene, r.model, r.clock))

    scene.wheel(+4)                                       # reading something older
    assert not newest(_settle(scene, r.model, r.clock))
    held = scene.scroll["mind"]
    th = r.feed.open(stage="verify", item="QC-007", model="claude-opus-5-5")
    r.feed.add_thinking(th, "A brand new thought about the riser detail.")
    r.model.poll(r.monitor)
    prims = _settle(scene, r.model, r.clock)
    assert scene.scroll["mind"] == held                   # the page did not jump
    assert not any("brand new thought" in t for t in _texts(prims, "mi_l"))
    assert _texts(prims, "mi_more")                       # ... and says there is more

    scene.wheel(-10_000)                                  # back to the end: follow again
    r.feed.add_thinking(th, " And one more line of it to push the feed along. " * 4)
    r.model.poll(r.monitor)
    prims = _settle(scene, r.model, r.clock)
    assert any("brand new thought" in t for t in _texts(prims, "mi_l"))
    assert not _texts(prims, "mi_more")


def test_a_second_runs_reasoning_is_never_shown_as_the_first_runs():
    """Each run's feed numbers its thoughts from 1, so two runs in one window
    can hold different text at the same number and the same length."""
    scene = LiveScene()
    scene.set_tab("mind")
    for words in ("alpha beta gamma delta eps", "omega zeta kappa theta phi"):
        r = _insight_run(thoughts=0)
        th = r.feed.open(stage="digest", item=sheet_item(r.refs[0]), model="claude-opus-5-5")
        r.feed.add_thinking(th, words)
        r.feed.close(th)
        r.model.poll(r.monitor)
        assert words in _texts(_settle(scene, r.model, r.clock), "mi_l")


def test_hovering_a_clipped_finding_shows_all_of_it():
    r = _insight_run(findings=3)
    r.findings[0].qc_id = "QC-001"
    r.model.poll(r.monitor)
    scene = LiveScene()
    scene.set_tab("findings")
    prims = scene.build(r.model, 700, 320, r.clock.t)
    row = next(p for p in prims if p.key == "fl0_t")
    full = r.model.ledger_findings[0].text
    assert dict(row.opts)["text"] != full                 # the row had to cut it
    scene.hover = (row.coords[0] + 20, row.coords[1])
    tip = " ".join(_texts(scene.build(r.model, 700, 320, r.clock.t), "tip_l"))
    assert full in " ".join(tip.split())


def test_clicking_a_tab_shows_it_and_a_short_panel_keeps_the_board():
    canvas, sched, clock = _FakeCanvas(980, 420), _Scheduler(), _Clock()
    picked: list[str] = []
    panel = LivePanel(canvas, schedule=sched.schedule, cancel=lambda h: None, clock=clock,
                      on_tab=picked.append, tab="findings")
    assert panel.scene.tab == "findings"                  # the remembered tab
    panel.preview([(sheet_item(ref), ref.display_label, ref.source_id) for ref in _refs(6)],
                  ["inventory", "digest"])
    sched.run_next()
    hits = {key: (x0, y0, x1, y1) for x0, y0, x1, y1, key in panel.scene._tab_hits}
    x0, y0, x1, y1 = hits["plan"]
    panel.click((x0 + x1) / 2, (y0 + y1) / 2)
    assert (panel.scene.tab, picked) == ("plan", ["plan"])
    panel.click((x0 + x1) / 2, (y0 + y1) / 2)             # already showing
    panel.click(5, 400)                                   # not a tab
    assert picked == ["plan"]
    panel.scroll(-2)                                      # nothing to scroll: harmless

    # Squeezed by the sections above it, the panel has no room for a tab strip:
    # it shows the board whatever tab was picked.
    scene = panel.scene
    prims = scene.build(panel.model, 800, 170, clock.t)
    assert scene._tab_hits == []
    assert sum(1 for p in prims if p.key.startswith("c") and p.key[1:].isdigit()) == 6


def test_a_new_run_brings_every_view_back_to_following():
    canvas, sched = _FakeCanvas(980, 300), _Scheduler()
    panel = LivePanel(canvas, schedule=sched.schedule, cancel=lambda h: None)
    panel.scene.set_tab("mind")
    panel.scene._scroll_max["mind"] = 500.0
    panel.scroll(+3)
    assert panel.scene.follow["mind"] is False
    panel.begin()
    assert panel.scene.follow.get("mind", True) and not panel.scene.scroll


def test_insights_report_trouble_at_the_level_it_deserves():
    from drawing_analyzer.live_tabs import insights

    r = _insight_run()
    r.model.poll(r.monitor)
    calm = [level for level, _text in insights(r.model)]
    assert calm and "warn" not in calm and "bad" not in calm
    r.journal.emit("API_RETRY", stage="digest", kind="rate_limit", backoff_s=2)
    r.journal.emit("SPEND_LIMIT", stage="digest")
    r.model.poll(r.monitor)
    levels = [level for level, _text in insights(r.model)]
    assert levels.count("warn") == 1 and levels.count("bad") == 1
    assert insights(LiveRunModel()) == []                 # nothing loaded: nothing to say
