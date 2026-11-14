"""Live run view: the data behind the GUI's animated *Live view* panel.

Tk-free and PyMuPDF-free (I-5), so it imports anywhere and every rule in it
is testable hermetically. Two pieces:

* :class:`RunMonitor` — a caller-owned attach point, passed as
  ``extract_drawing_context(monitor=...)``. The pipeline hands it the run's own
  recorders: the :class:`~drawing_analyzer.run_journal.RunJournal` (already
  sanitized at emit — no key, no path), the
  :class:`~drawing_analyzer.resource_pressure.ResourcePressure` record (whose
  ``calls`` is the per-call telemetry), the resolved configuration, and the
  sheet list. It holds references only; nothing a host does through it can
  change the run, and every method swallows its own failures (I-3) — a display
  hook must never fail a paid run.

* :class:`LiveRunModel` — the host-side reducer. :meth:`LiveRunModel.poll`
  reads only what is new since the last poll (journal events and call records
  are append-only) and folds it into view state: one :class:`LiveStage` per
  pipeline stage, one :class:`LiveSheet` per sheet, call/token counters, a
  live cost figure, a throughput series and a short ticker of notable events.
  It runs on the host's UI thread and never writes to the run.

Beyond the board, the model keeps what the insight tabs show (*Story*,
*Thinking*, *Plan*, *Findings*): per-stage tokens / spend / model, the set
identity and the review checklist with its per-sheet answers, the findings
ledger as it fills, and the models' reasoning summaries
(:mod:`~drawing_analyzer.thought_stream`). The pipeline hands those over with
:meth:`RunMonitor.publish`; they are the run's own objects, read here and never
written.

The live cost is an *estimate*: each settled call record is priced at the
model that answered it, through :func:`core.pricing.usage_record_cost`. The
run's own usage ledger is the authority and replaces the estimate in
:meth:`LiveRunModel.finish`.
"""
from __future__ import annotations

import re
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, NamedTuple

from .call_telemetry import (
    OUTCOME_CANCELLED,
    OUTCOME_OK,
    OUTCOME_PENDING,
    OUTCOME_TOOL_USE,
    TRANSPORT_BATCH,
    canonical_stage,
)

# --------------------------------------------------------------------------- #
# Vocabulary.
# --------------------------------------------------------------------------- #

# Run phases (the model's own lifecycle; not the pipeline's QC status).
PHASE_IDLE = "IDLE"            # no run: the board previews the loaded set
PHASE_RUNNING = "RUNNING"
PHASE_DONE = "DONE"
PHASE_STOPPED = "STOPPED"
PHASE_FAILED = "FAILED"

# Stage states on the track.
STAGE_PLANNED = "planned"
STAGE_ACTIVE = "active"
STAGE_DONE = "done"
STAGE_SKIPPED = "skipped"      # planned, but the run ended without starting it

# Sheet states on the board, in the order a sheet moves through them. A state
# only ever moves forward, except that the run's own per-sheet outcome
# (``SHEET_DIGESTED``) is authoritative and may settle any of the last three.
SHEET_PENDING = "pending"
SHEET_RENDERED = "rendered"    # rasterized; overview + tiles exist
SHEET_QUEUED = "queued"        # waiting in a Message Batch (the shared queue)
SHEET_READING = "reading"      # a real-time read is streaming
SHEET_DONE = "done"
SHEET_CACHED = "cached"        # served from the digest cache: no call
SHEET_FAILED = "failed"
_SHEET_RANK = {
    SHEET_PENDING: 0, SHEET_RENDERED: 1, SHEET_QUEUED: 2, SHEET_READING: 3,
    SHEET_DONE: 4, SHEET_CACHED: 4, SHEET_FAILED: 4,
}
SHEET_TERMINAL = frozenset({SHEET_DONE, SHEET_CACHED, SHEET_FAILED})

# The pipeline's stages in run order: journal stage name, short track label,
# and the longer name a tooltip shows. Stages outside this list (tile
# artifacts, the profiles bookkeeping stage, the ledger events) are not drawn.
STAGE_CATALOG: tuple[tuple[str, str, str], ...] = (
    ("inventory", "Inputs", "Input inventory"),
    ("digest", "Read", "Sheet reads (vision digest)"),
    ("identity", "Identify", "Set identity"),
    ("review_plan", "Plan", "Review plan"),
    ("critique", "Critique", "Reviewer critique reads"),
    ("cross_qc", "X-Sheet", "Cross-sheet conflict hunt"),
    ("synthesis", "Overview", "Set overview synthesis"),
    ("focus", "Focus", "Focus report"),
    ("auditors", "Audit", "Deterministic auditors"),
    ("prose_harvest", "Harvest", "Prose findings harvest"),
    ("edition_audit", "Editions", "Code-edition audit"),
    ("anchor", "Anchor", "Anchoring findings on the PDF"),
    ("absence_check", "Absence", "Absence cross-check"),
    ("verification", "Verify", "Crop verification"),
    ("investigation", "Probe", "Agentic investigation"),
    ("citation", "Cite", "Code citation check"),
    ("markup", "Markup", "Writing marked-up PDFs"),
)
_STAGE_ORDER = {name: i for i, (name, _s, _l) in enumerate(STAGE_CATALOG)}
_STAGE_LABELS = {name: (short, long) for name, short, long in STAGE_CATALOG}

# Call-telemetry stage families (the usage ledger's names) → track stages.
_FAMILY_STAGE = {
    "digest": "digest",
    "critique": "critique",
    "identity": "identity",
    "review_plan": "review_plan",
    "cross_qc": "cross_qc",
    "synthesis": "synthesis",
    "focus": "focus",
    "harvest": "prose_harvest",
    "absence_check": "absence_check",
    "verify": "verification",
    "investigate": "investigation",
    "citation": "citation",
}



def family_label(family: str) -> str:
    """The short track label of a usage family (``verify`` → ``Verify``)."""
    name = _FAMILY_STAGE.get(canonical_stage(str(family or "")))
    if name is None:
        return str(family or "call").replace("_", " ")
    return _STAGE_LABELS[name][0]


_COMPLETING = frozenset({OUTCOME_OK, OUTCOME_TOOL_USE})
# A sheet item is ``SRC-0001:p0``; critique reads append ``:<read id>``.
_SHEET_ITEM_RE = re.compile(r"^(.+?:p\d+)(?::|$)")

# How long a settled call record stays re-readable: describe_response() sets a
# record's ``outcome`` before its token counts, so a poll can land between the
# two. Re-reading a settled record for a short window picks up the rest.
_SETTLE_WINDOW_SECONDS = 2.0
# Throughput series: one bucket per second, this many kept.
SERIES_SECONDS = 240
TICKER_LENGTH = 8


def planned_stages(config: Any, *, focus: bool = False) -> list[str]:
    """The track stages a resolved :class:`RunConfiguration` will run, in order.

    A ``None`` config (nothing resolved yet) plans the two stages every run
    has. Reality still wins at run time: a stage that starts without being
    planned joins the track, and one that never starts ends as skipped.
    """
    if config is None:
        return ["inventory", "digest"]
    flag = lambda name: bool(getattr(config, name, False))  # noqa: E731
    on = {
        "inventory": True,
        "digest": True,
        "identity": flag("run_identity"),
        "review_plan": flag("run_review_plan"),
        "critique": flag("run_critique"),
        "cross_qc": flag("run_cross_qc"),
        "synthesis": flag("run_synthesis"),
        "focus": bool(focus),
        "auditors": flag("run_auditors"),
        "prose_harvest": flag("run_prose_harvest"),
        "edition_audit": flag("run_citation") or flag("run_auditors"),
        "anchor": flag("run_anchoring"),
        "absence_check": flag("run_absence_check"),
        "verification": flag("run_verification"),
        "investigation": flag("run_investigation"),
        "citation": flag("run_citation"),
        "markup": flag("run_markup"),
    }
    return [name for name, _s, _l in STAGE_CATALOG if on.get(name)]


def sheet_key_of(item: str) -> str:
    """The sheet a call-telemetry item names (``SRC-0001:p0``), or ``""``."""
    m = _SHEET_ITEM_RE.match(str(item or ""))
    return m.group(1) if m else ""


def call_record_cost(record: Any, *, fast: bool = False) -> "Decimal | None":
    """Estimated USD cost of one settled call record, or ``None`` if unpriced.

    Priced at the model that answered (a refusal fallback's substitute when
    one ran), at the batch rate for a batch item, and at the fast-mode rate on
    a real-time call of an XFast run (``fast``). Cache writes take the default
    5-minute rate: a record does not say which TTL it asked for. An estimate
    for a live display — the run's usage ledger is the authority.
    """
    from .core.pricing import usage_record_cost

    try:
        model = str(getattr(record, "served_model", None) or getattr(record, "model", "") or "")
        if not model:
            return None
        server = getattr(record, "server_tool_requests", None) or {}
        searches = int(server.get("web_search_requests", 0) or 0)
        batch = getattr(record, "transport", "") == TRANSPORT_BATCH
        return usage_record_cost(
            model=model,
            input_tokens=int(getattr(record, "input_tokens", 0) or 0),
            output_tokens=int(getattr(record, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(record, "cache_read_tokens", 0) or 0),
            cache_write_tokens=int(getattr(record, "cache_write_tokens", 0) or 0),
            billable_tool_uses={"web_search": searches} if searches else None,
            batch=batch,
            speed="fast" if fast and not batch else None,
        )
    except Exception:  # noqa: BLE001 - an unpriceable record shows tokens only
        return None


# --------------------------------------------------------------------------- #
# The attach point the pipeline fills.
# --------------------------------------------------------------------------- #


class MonitorParts(NamedTuple):
    """One consistent read of what a :class:`RunMonitor` has been handed."""

    journal: Any
    pressure: Any
    config: Any
    focus: bool
    sheets: "tuple[tuple[str, str, str], ...] | None"


class RunMonitor:
    """A caller-owned window onto one live run (``extract_drawing_context(monitor=)``).

    The pipeline calls :meth:`attach` with the run's journal, resource record
    and configuration as soon as they exist, and :meth:`set_sheets` once the
    sheet list is known. A host reads :meth:`parts` from any thread. Holds
    references only and never raises.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._journal: Any = None
        self._pressure: Any = None
        self._config: Any = None
        self._focus = False
        self._sheets: "tuple[tuple[str, str, str], ...] | None" = None
        self._facts: dict[str, Any] = {}

    def publish(self, kind: str, value: Any) -> None:
        """Hand the host one of the run's own objects by name.

        ``identity`` (the ``SetIdentity``), ``checklist`` (the
        ``ChecklistPlan``), ``checklist_answers`` (the dict the critique fills
        per sheet), ``digests`` (the sheet digests), ``critique_findings`` /
        ``cross_findings`` and ``ledger`` (the findings ledger). References
        only: the host reads them and must never write.
        """
        try:
            with self._lock:
                self._facts[str(kind)] = value
        except Exception:  # noqa: BLE001 - a display hook never fails a run (I-3)
            pass

    def facts(self) -> dict:
        """What has been published so far (a copy of the name → object map)."""
        with self._lock:
            return dict(self._facts)

    def attach(
        self,
        *,
        journal: Any = None,
        pressure: Any = None,
        config: Any = None,
        focus: "bool | None" = None,
    ) -> None:
        try:
            with self._lock:
                if journal is not None:
                    self._journal = journal
                if pressure is not None:
                    self._pressure = pressure
                if config is not None:
                    self._config = config
                if focus is not None:
                    self._focus = bool(focus)
        except Exception:  # noqa: BLE001 - a display hook never fails a run (I-3)
            pass

    def set_sheets(self, refs: Iterable[Any]) -> None:
        """Record the run's sheets as ``(item, display label, source id)``.

        ``item`` is the portable call-telemetry label (``SRC-0001:p0``) the
        run's own call records carry, so the board can follow each sheet.
        """
        try:
            from .call_telemetry import sheet_item

            sheets = tuple(
                (sheet_item(ref), str(getattr(ref, "display_label", "") or ""),
                 str(getattr(ref, "source_id", "") or ""))
                for ref in refs
            )
            with self._lock:
                self._sheets = sheets
        except Exception:  # noqa: BLE001
            pass

    def parts(self) -> MonitorParts:
        with self._lock:
            return MonitorParts(
                self._journal, self._pressure, self._config, self._focus, self._sheets,
            )


def notify_monitor(monitor: Any, method: str, *args: Any, **kwargs: Any) -> None:
    """Call ``monitor.<method>`` if a monitor was given; never raises (I-3)."""
    if monitor is None:
        return
    try:
        getattr(monitor, method)(*args, **kwargs)
    except Exception:  # noqa: BLE001 - a caller-supplied object may be anything
        pass


# --------------------------------------------------------------------------- #
# View state.
# --------------------------------------------------------------------------- #


@dataclass
class LiveStage:
    name: str
    label: str
    long_label: str
    state: str = STAGE_PLANNED
    status: str = ""                  # the run's STAGE_END status, when it ended
    started_at: "float | None" = None   # wall-clock epoch seconds (event time)
    ended_at: "float | None" = None
    changed_at: float = 0.0           # animation clock: when the state last moved
    calls_open: int = 0               # real-time calls in flight
    calls_queued: int = 0             # batch items awaiting results
    calls_done: int = 0
    calls_failed: int = 0
    note: str = ""                    # the end event's error / warning, if any
    tokens_in: int = 0                # input + cache tokens its calls used
    tokens_out: int = 0
    cost: Decimal = Decimal(0)        # estimated spend of its settled calls
    model: str = ""                   # the model its latest call named
    effort: str = ""                  # ... and the effort that call asked for
    thinking: str = ""                # ... and its thinking mode
    batch: bool = False               # its latest call went through the batch queue

    def duration(self, wall_now: float) -> "float | None":
        if self.started_at is None:
            return None
        end = self.ended_at if self.ended_at is not None else wall_now
        return max(0.0, end - self.started_at)


@dataclass
class LiveSheet:
    item: str                         # ``SRC-0001:p0`` — the run's portable id
    label: str                        # display label (file name + page)
    source_id: str = ""
    index: int = 0
    state: str = SHEET_PENDING
    changed_at: float = 0.0
    digested: bool = False            # the run's own outcome has landed
    critique_open: int = 0
    critique_queued: int = 0
    critique_done: int = 0
    critique_changed_at: float = 0.0
    hiccup_at: "float | None" = None  # a read came back unfinished / errored
    tokens: int = 0                   # input + output tokens spent on it this run


@dataclass
class TickerItem:
    at: float                         # animation clock
    level: str                        # info | good | warn | bad
    text: str


@dataclass
class FindingsSummary:
    """The run's findings as the board shows them (filled at the end)."""

    total: int = 0
    by_status: dict = field(default_factory=dict)     # display bucket -> count
    by_severity: dict = field(default_factory=dict)   # high/medium/low -> count


@dataclass
class LiveCode:
    """One code edition the set names (the Plan tab)."""

    code: str
    edition: str = ""
    origin: str = ""                  # model | regex | operator
    adopted: bool = True              # False: mentioned on the set, not adopted


@dataclass
class LiveIdentity:
    """What the identity stage worked out about the set."""

    project_type: str = ""
    set_type: str = ""
    place: str = ""                   # jurisdiction / region / country
    language: str = ""
    units: str = ""
    confidence: str = ""
    disciplines: tuple = ()
    classified_sheets: int = 0
    codes: list = field(default_factory=list)       # LiveCode


@dataclass
class LiveCheckItem:
    id: str
    text: str
    counts: dict = field(default_factory=dict)       # answer status -> sheets


@dataclass
class LiveCheckGroup:
    """One checklist: a person's own, or a plan the model authored."""

    title: str
    origin: str                       # user | model
    items: list = field(default_factory=list)        # LiveCheckItem


@dataclass
class LiveFinding:
    """One ledger entry as the Findings tab lists it."""

    key: int
    qc_id: str
    severity: str
    category: str
    sheet: str
    text: str
    anchor: str                       # exact | fuzzy | tile | unplaced
    bucket: str                       # a FINDING_BUCKETS key
    sources: tuple = ()
    reproduced: bool = False


# Checklist answer statuses, in the order the Plan tab stacks them.
CHECK_STATUSES: tuple[tuple[str, str], ...] = (
    ("VIOLATED", "violated"),
    ("UNDETERMINED", "undetermined"),
    ("MET", "reported met"),
    ("NOT_APPLICABLE", "n/a"),
    ("UNANSWERED", "unanswered"),
)
# Anchor outcomes, in the order the Findings tab stacks them.
ANCHOR_BUCKETS: tuple[tuple[str, str], ...] = (
    ("exact", "exact quote"),
    ("fuzzy", "close match"),
    ("tile", "tile only"),
    ("unplaced", "not placed"),
)
_ANCHOR_BUCKET = {"EXACT": "exact", "FUZZY": "fuzzy", "TILE": "tile"}
# Findings channels (ledger source tags → the label the tab shows).
SOURCE_LABELS: tuple[tuple[str, str], ...] = (
    ("digest", "first read"),
    ("critique", "critique reads"),
    ("cross_qc", "cross-sheet"),
    ("auditor", "auditors"),
    ("prose", "prose harvest"),
    ("other", "other"),
)
# The channels that are model reads (the rest are offline checks).
_READ_CHANNELS = frozenset({"digest", "critique", "cross_qc"})
# How often the insight tabs re-read the run's published objects.
INSIGHT_REFRESH_SECONDS = 0.5
MAX_LIVE_FINDINGS = 400


def source_family(tag: str) -> str:
    """The channel a ledger source tag belongs to (``critique_2`` → critique)."""
    tag = str(tag or "").lower()
    if tag.startswith("digest"):
        return "digest"
    if tag.startswith("critique"):
        return "critique"
    if tag.startswith("cross"):
        return "cross_qc"
    if tag.startswith(("audit", "reference", "arithmetic", "naming", "title", "sheet_index",
                       "edition", "deterministic")):
        return "auditor"
    if tag.startswith(("prose", "synthesis", "focus", "harvest")):
        return "prose"
    return "other"


# Verification status → the board's bucket. DETERMINISTIC folds into verified
# (host-proven); FAILED / SKIPPED read as "not checked".
FINDING_BUCKETS: tuple[tuple[str, str], ...] = (
    ("verified", "Verified"),
    ("uncertain", "Uncertain"),
    ("unchecked", "Not checked"),
    ("rejected", "Rejected"),
)
_STATUS_BUCKET = {
    "VERIFIED": "verified",
    "DETERMINISTIC": "verified",
    "UNCERTAIN": "uncertain",
    "REJECTED": "rejected",
}


def summarize_findings(findings: Iterable[Any]) -> FindingsSummary:
    """Bucket findings by verification status and severity (each id once)."""
    seen: set = set()
    by_status: Counter = Counter()
    by_severity: Counter = Counter()
    total = 0
    for f in findings or ():
        key = getattr(f, "id", None) or id(f)
        if key in seen:
            continue
        seen.add(key)
        total += 1
        status = str(getattr(getattr(f, "verification", None), "status", "") or "")
        by_status[_STATUS_BUCKET.get(status, "unchecked")] += 1
        sev = str(getattr(f, "severity", "") or "").lower()
        if sev:
            by_severity[sev] += 1
    return FindingsSummary(total=total, by_status=dict(by_status), by_severity=dict(by_severity))


def _event_epoch(timestamp: str) -> "float | None":
    try:
        return datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
            tzinfo=timezone.utc,
        ).timestamp()
    except (TypeError, ValueError):
        return None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# The reducer.
# --------------------------------------------------------------------------- #


class LiveRunModel:
    """Folds a live run's journal and call records into view state.

    ``clock`` is the animation clock (monotonic seconds) every ``*_at`` /
    ``changed_at`` field is stamped with; ``wall_clock`` is epoch seconds, for
    durations measured against the journal's own event timestamps. Both are
    injectable so tests are deterministic.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._wall = wall_clock
        self.phase = PHASE_IDLE
        self.stages: list[LiveStage] = []
        self.sheets: list[LiveSheet] = []
        self.sheets_since: float = 0.0          # when the board's cells last appeared
        self.ticker: deque[TickerItem] = deque(maxlen=TICKER_LENGTH)
        self.files = 0
        self.files_rejected = 0
        self.cache_hits: "int | None" = None
        self.calls_done = 0
        self.calls_failed = 0
        self.tokens_in = 0                      # input + cache read + cache write
        self.tokens_out = 0
        self.cost = Decimal(0)
        self.cost_known = False                 # at least one call was priced
        self.cost_final = False                 # ``cost`` is the run ledger's figure
        self.retries = 0
        self.give_ups = 0
        self.last_retry_at: "float | None" = None
        self.spend_limit = False
        self.findings_sealed: "int | None" = None
        self.findings_verified = 0              # verify items settled so far
        self.findings: "FindingsSummary | None" = None
        self.markup_written: "int | None" = None
        self.markup_expected: "int | None" = None
        self.outcome = ""                       # RUN_END outcome (COMPLETE/PARTIAL/FAILED)
        self.qc_status = ""
        self.coverage = ""
        self.error = ""
        self.run_started_at: "float | None" = None   # wall
        self.run_ended_at: "float | None" = None     # wall
        self.ended_at: "float | None" = None         # animation clock
        self.series: deque = deque(maxlen=SERIES_SECONDS)   # [second, in, out]
        # The loaded files' revision (the host's fingerprint) the board was
        # previewed from: sheet ids encode order and page, not file content.
        self.revision: Any = None
        # What the insight tabs show (see ``_poll_insights``).
        self.config: Any = None                 # the run's resolved configuration
        self.identity: "LiveIdentity | None" = None
        self.checklist: list[LiveCheckGroup] = []
        self.checklist_sheets = 0               # sheets whose critique answered
        self.found: dict = {}                   # channel -> findings reported so far
        self.ledger_state = ""                  # "" | OPEN | SEALED | NUMBERED
        self.ledger_findings: list[LiveFinding] = []
        self.ledger_total = 0
        self.ledger_offline = 0                 # entries no model read reported
        self.ledger_by: dict = {"severity": {}, "anchor": {}, "bucket": {}, "source": {}}
        self.insights_changed_at = 0.0          # animation clock: last insight change
        self.thoughts: list = []                # thought_stream.Thought copies
        self.thoughts_enabled: "bool | None" = None   # None: no run has said yet
        self.thoughts_seen = 0
        self.thoughts_with_text = 0
        self.thoughts_changed_at = 0.0
        self._focus = False
        self._reset_cursors()

    # -- lifecycle ---------------------------------------------------------- #

    def _reset_cursors(self) -> None:
        self._event_cursor = 0
        self._call_cursor = 0
        self._open: dict[int, Any] = {}
        self._unplaced: set[int] = set()      # open records not yet tied to a sheet
        self._settling: dict[int, tuple[Any, float]] = {}
        self._counted: dict[int, tuple[int, int, Decimal]] = {}
        self._verify_items: set[str] = set()
        self._sheet_by_item: dict[str, int] = {}
        self._sheet_by_label: dict[str, list[int]] = {}
        self._sheets_from_run = False
        self._planned_from_run = False
        self._journal_roots: tuple = ()
        self._thought_version = -1
        self._insights_at = float("-inf")
        self._insight_sig: Any = None

    def preview(
        self,
        sheets: "Iterable[tuple[str, str] | tuple[str, str, str]]",
        stages: "Iterable[str]",
        *,
        revision: Any = None,
    ) -> None:
        """Show a not-yet-run set: every sheet pending, the planned track.

        Ignored while a run is in flight. A finished board stays up until the
        loaded set actually changes, so its results are not wiped by an
        unrelated option toggle; the track follows the options only while idle.
        ``revision`` identifies the files' content (the GUI passes
        ``sources_fingerprint``): a PDF overwritten in place keeps its sheet
        ids, so without it a revised set would keep the old run's board.
        Cells and stage nodes that were already on the board keep their
        identity, so only what is new animates in.
        """
        if self.phase == PHASE_RUNNING:
            return
        rows = [tuple(s) for s in sheets]
        same_set = ([r[0] for r in rows] == [s.item for s in self.sheets]
                    and revision == self.revision)
        self.revision = revision
        if self.phase != PHASE_IDLE:
            if same_set:
                return
            self._clear_run_state()
            self.phase = PHASE_IDLE
        now = self._clock()
        self._plan(list(stages), now)
        if not same_set:
            self._set_sheets(rows, now)

    def begin(self) -> None:
        """A run was launched: clear the last run, keep the previewed board."""
        self._clear_run_state()
        self.phase = PHASE_RUNNING
        self.run_started_at = self._wall()
        self._push("info", "Run launched — waiting for the pipeline…")

    def _clear_run_state(self) -> None:
        """Forget the last run's figures; keep the board's cells and nodes."""
        stages, sheets, since = self.stages, self.sheets, self.sheets_since
        revision = self.revision
        fresh = LiveRunModel(clock=self._clock, wall_clock=self._wall)
        self.__dict__.update(fresh.__dict__)
        self.revision = revision
        now = self._clock()
        for st in stages:
            st.state, st.status, st.note = STAGE_PLANNED, "", ""
            st.started_at = st.ended_at = None
            st.calls_open = st.calls_queued = st.calls_done = st.calls_failed = 0
            st.tokens_in = st.tokens_out = 0
            st.cost, st.model, st.effort, st.thinking, st.batch = Decimal(0), "", "", "", False
            st.changed_at = now
        for sh in sheets:
            sh.state, sh.changed_at, sh.digested = SHEET_PENDING, now, False
            sh.critique_open = sh.critique_queued = sh.critique_done = 0
            sh.hiccup_at, sh.tokens = None, 0
        self.stages, self.sheets, self.sheets_since = stages, sheets, since
        self._index_sheets()

    def finish(self, ctx: Any = None, monitor: "RunMonitor | None" = None) -> None:
        """The run returned: take its own figures as final."""
        if monitor is not None:
            self._insights_at = float("-inf")       # the last read is unthrottled
            self.poll(monitor)
        now = self._clock()
        self.phase = PHASE_DONE
        self.ended_at = now
        if self.run_ended_at is None:
            self.run_ended_at = self._wall()
        if ctx is not None:
            try:
                cost = getattr(ctx, "total_estimated_cost", None)
                usage = getattr(ctx, "run_usage", None)
                if cost is not None:
                    self.cost, self.cost_known, self.cost_final = Decimal(cost), True, True
                elif usage is not None:
                    # The run's ledger could not price everything: the spend is
                    # unknown, and a partial live estimate must not stand in.
                    self.cost, self.cost_known, self.cost_final = Decimal(0), False, True
                if usage is not None:
                    self.tokens_in = int(
                        usage.total_input_tokens + usage.total_cache_read_tokens
                        + usage.total_cache_write_tokens
                    )
                    self.tokens_out = int(usage.total_output_tokens)
                if getattr(ctx, "findings", None) or getattr(ctx, "reference_findings", None):
                    self.findings = summarize_findings(
                        list(getattr(ctx, "findings", None) or [])
                        + list(getattr(ctx, "reference_findings", None) or [])
                    )
                self.qc_status = str(getattr(ctx, "qc_status", "") or self.qc_status)
                self.coverage = str(getattr(ctx, "coverage_status", "") or self.coverage)
                for sd in getattr(ctx, "sheets", None) or ():
                    self._settle_sheet_from_digest(sd, now)
            except Exception:  # noqa: BLE001 - the board is decoration; never raise
                pass
        self._close_track(now)
        if not self.outcome:
            self.outcome = "COMPLETE"
        level = {"COMPLETE": "good", "PARTIAL": "warn"}.get(self.outcome, "bad")
        self._push(level, f"Run {self.outcome.lower()}.")

    def stop(self, phase: str = PHASE_STOPPED, message: str = "",
             monitor: "RunMonitor | None" = None) -> None:
        """The run was stopped (``PHASE_STOPPED``) or raised (``PHASE_FAILED``)."""
        if monitor is not None:
            self._insights_at = float("-inf")
            self.poll(monitor)
        now = self._clock()
        self.phase = phase
        self.ended_at = now
        self.error = str(message or "")[:300]
        if self.run_ended_at is None:
            self.run_ended_at = self._wall()
        self._close_track(now)
        if phase == PHASE_STOPPED:
            self._push("warn", "Run stopped — nothing further is sent.")
        else:
            self._push("bad", "Run failed: " + (self.error or "unexpected error"))

    def _close_track(self, now: float) -> None:
        # Nothing is in flight once the run has returned: a sheet still shown
        # reading or queued (stopped mid-read, or never reached) goes back to
        # "rendered", and pending critique reads are dropped.
        for sh in self.sheets:
            if sh.state in (SHEET_QUEUED, SHEET_READING):
                sh.state, sh.changed_at = SHEET_RENDERED, now
            if sh.critique_open or sh.critique_queued:
                sh.critique_open = sh.critique_queued = 0
                sh.critique_changed_at = now
        self._open.clear()
        self._unplaced.clear()
        for st in self.stages:
            if st.state == STAGE_PLANNED:
                st.state, st.changed_at = STAGE_SKIPPED, now
            elif st.state == STAGE_ACTIVE and self.phase != PHASE_DONE:
                # Left mid-flight by a stop or a crash.
                st.state, st.status, st.changed_at = STAGE_DONE, "STOPPED", now
                st.ended_at = st.ended_at or self._wall()
            elif st.state == STAGE_ACTIVE:
                st.state, st.changed_at = STAGE_DONE, now
                st.status = st.status or "COMPLETE"
                st.ended_at = st.ended_at or self.run_ended_at

    # -- derived reads ------------------------------------------------------ #

    @property
    def calls_in_flight(self) -> int:
        return sum(1 for r in self._open.values() if getattr(r, "transport", "") != TRANSPORT_BATCH)

    @property
    def calls_queued(self) -> int:
        return sum(1 for r in self._open.values() if getattr(r, "transport", "") == TRANSPORT_BATCH)

    def elapsed(self) -> float:
        if self.run_started_at is None:
            return 0.0
        end = self.run_ended_at if self.run_ended_at is not None else self._wall()
        return max(0.0, end - self.run_started_at)

    def active_stages(self) -> list[LiveStage]:
        return [s for s in self.stages if s.state == STAGE_ACTIVE]

    def sheet_counts(self) -> Counter:
        return Counter(s.state for s in self.sheets)

    def throughput(self, window: int = 10) -> float:
        """Tokens per second (input + output) over the last ``window`` seconds."""
        if not self.series:
            return 0.0
        now_s = int(self._clock())
        total = sum(b[1] + b[2] for b in self.series if now_s - b[0] < window)
        return total / float(window)

    def summary_line(self) -> str:
        """One line for a collapsed panel header."""
        counts = self.sheet_counts()
        n = len(self.sheets)
        finished = sum(counts.get(s, 0) for s in SHEET_TERMINAL)
        if self.phase == PHASE_IDLE:
            return f"{n} sheet(s) ready" if n else ""
        parts = []
        active = self.active_stages()
        if self.phase == PHASE_RUNNING and active:
            parts.append(" + ".join(s.label for s in active))
        elif self.phase != PHASE_RUNNING:
            parts.append({PHASE_DONE: (self.outcome or "done").lower(),
                          PHASE_STOPPED: "stopped", PHASE_FAILED: "failed"}[self.phase])
        if n:
            parts.append(f"{finished}/{n} sheets")
        if self.cost_known:
            parts.append(("$" if self.cost_final else "≈$") + f"{self.cost:,.2f}")
        return "  ·  ".join(parts)

    # -- polling ------------------------------------------------------------ #

    def poll(self, monitor: "RunMonitor | None") -> None:
        """Fold everything new on ``monitor`` into the view state. Never raises."""
        if monitor is None:
            return
        try:
            parts = monitor.parts()
        except Exception:  # noqa: BLE001
            return
        now = self._clock()
        try:
            if parts.config is not None and not self._planned_from_run:
                # The run's own resolved configuration replaces the preview's
                # plan once; stages it already started stay on the track.
                self._planned_from_run = True
                self._focus = parts.focus
                self.config = parts.config
                self._plan(planned_stages(parts.config, focus=parts.focus), now,
                           keep_started=True)
            if parts.journal is not None:
                self._journal_roots = tuple(getattr(parts.journal, "private_roots", ()) or ())
            if parts.sheets is not None and not self._sheets_from_run:
                self._sheets_from_run = True
                rows = list(parts.sheets)
                same = [r[0] for r in rows] == [s.item for s in self.sheets]
                if same:
                    for s, r in zip(self.sheets, rows):
                        s.label, s.source_id = r[1], r[2]
                    self._index_sheets()
                else:
                    self._set_sheets(rows, now)
            if parts.journal is not None:
                self._poll_journal(parts.journal, now)
            calls = getattr(parts.pressure, "calls", None)
            if calls is not None:
                fast = getattr(parts.pressure, "requested_speed", None) == "fast"
                self._poll_calls(calls, now, fast=fast)
        except Exception:  # noqa: BLE001 - the board is decoration; never raise
            pass
        try:
            self._poll_thoughts(parts.pressure, now)
        except Exception:  # noqa: BLE001
            pass
        if now - self._insights_at >= INSIGHT_REFRESH_SECONDS:
            self._insights_at = now
            try:
                facts = monitor.facts()
            except Exception:  # noqa: BLE001 - a monitor without facts shows none
                facts = {}
            # Each part is read on its own: the run's threads are still writing
            # these objects, and one odd read must not blank the other tabs.
            for read in (self._read_identity, self._read_checklist, self._read_findings):
                try:
                    read(facts)
                except Exception:  # noqa: BLE001
                    continue
            sig = (
                id(self.identity) if self.identity is None else len(self.identity.codes),
                self.checklist_sheets, sum(len(g.items) for g in self.checklist),
                self.ledger_total, self.ledger_state, tuple(sorted(self.found.items())),
                tuple(sorted(self.ledger_by["bucket"].items())),
                tuple(sorted(self.ledger_by["anchor"].items())),
            )
            if sig != self._insight_sig:
                self._insight_sig, self.insights_changed_at = sig, now

    # -- insight tabs --------------------------------------------------------- #

    def item_label(self, item: str) -> str:
        """A call item as a person reads it: the sheet's label, else the item."""
        item = str(item or "")
        key = sheet_key_of(item)
        idx = self._sheet_by_item.get(key) if key else None
        if idx is None:
            return item
        label = self.sheets[idx].label or key
        read = item[len(key):].lstrip(":")
        return f"{label} · read {read}" if read else label

    def merged_reports(self) -> int:
        """How many reports the ledger folded into an entry that already said
        the same thing (0 until the ledger exists, or when it cannot be told)."""
        if not self.ledger_total:
            return 0
        from_reads = self.ledger_total - self.ledger_offline
        return max(0, sum(self.found.values()) - from_reads)

    def _poll_thoughts(self, pressure: Any, now: float) -> None:
        stream = getattr(pressure, "thoughts", None)
        if pressure is None:
            return
        if stream is None or not hasattr(stream, "snapshot"):
            self.thoughts_enabled = False
            return
        self.thoughts_enabled = True
        snap = stream.snapshot(self._thought_version)
        if snap is None:
            return
        self._thought_version, self.thoughts = snap
        self.thoughts_seen = int(getattr(stream, "seen", 0) or 0)
        self.thoughts_with_text = int(getattr(stream, "with_text", 0) or 0)
        self.thoughts_changed_at = now

    def _read_identity(self, facts: dict) -> None:
        ident = facts.get("identity")
        if ident is None:
            return
        codes = [
            LiveCode(code=str(getattr(c, "code", "") or ""),
                     edition=str(getattr(c, "edition", "") or ""),
                     origin=str(getattr(c, "origin", "") or ""), adopted=adopted)
            for adopted, name in ((True, "adopted_codes"), (False, "mentioned_codes"))
            for c in getattr(ident, name, None) or ()
        ]
        place = ", ".join(
            p for p in (str(getattr(ident, n, "") or "").strip()
                        for n in ("jurisdiction", "region", "country")) if p
        )
        self.identity = LiveIdentity(
            project_type=str(getattr(ident, "project_type", "") or ""),
            set_type=str(getattr(ident, "set_type", "") or ""),
            place=place,
            language=str(getattr(ident, "language", "") or ""),
            units=str(getattr(ident, "units", "") or ""),
            confidence=str(getattr(ident, "confidence", "") or ""),
            disciplines=tuple(str(d) for d in getattr(ident, "disciplines", None) or ()),
            classified_sheets=len(getattr(ident, "sheet_disciplines", None) or ()),
            codes=codes,
        )

    def _read_checklist(self, facts: dict) -> None:
        plan = facts.get("checklist")
        items = list(getattr(plan, "items", None) or ())
        if not items:
            return
        # One sheet's answer to an item is its reads' answers folded by the
        # run's own precedence; the tab counts sheets per answer.
        from .models import merged_check_status

        answers = facts.get("checklist_answers")
        per_sheet = list(dict(answers).values()) if answers else []
        tallies: dict[str, Counter] = {}
        for sheet_answers in per_sheet:
            for item_id, reads in dict(sheet_answers or {}).items():
                tallies.setdefault(str(item_id), Counter())[
                    merged_check_status(list(reads or ()))] += 1
        groups: list[LiveCheckGroup] = []
        by_key: dict[tuple, LiveCheckGroup] = {}
        for it in items:
            item_id = str(getattr(it, "id", "") or "")
            # A checklist is identified by its position in the selection (the
            # id's prefix): two uploads can share a name and a title.
            key = (str(getattr(it, "origin", "") or ""), item_id.split(".", 1)[0])
            group = by_key.get(key)
            if group is None:
                group = LiveCheckGroup(
                    title=str(getattr(it, "title", "") or getattr(it, "profile", "") or key[1]),
                    origin=key[0],
                )
                by_key[key] = group
                groups.append(group)
            group.items.append(LiveCheckItem(
                id=item_id, text=str(getattr(it, "text", "") or ""),
                counts=dict(tallies.get(item_id, ())),
            ))
        self.checklist = groups
        self.checklist_sheets = len(per_sheet)

    def _read_findings(self, facts: dict) -> None:
        found: dict[str, int] = {}
        digests = facts.get("digests")
        if digests is not None:
            found["digest"] = sum(len(getattr(sd, "findings", None) or ()) for sd in list(digests))
        for kind, channel in (("critique_findings", "critique"), ("cross_findings", "cross_qc")):
            value = facts.get(kind)
            if value is not None:
                found[channel] = len(list(value))
        self.found = found
        ledger = facts.get("ledger")
        if ledger is None:
            return
        entries = list(getattr(ledger, "entries", None) or ())
        self.ledger_state = str(getattr(ledger, "state", "") or "")
        by: dict[str, Counter] = {k: Counter() for k in ("severity", "anchor", "bucket", "source")}
        rows: list[LiveFinding] = []
        offline = 0
        for f in entries:
            severity = str(getattr(f, "severity", "") or "").lower()
            anchor = _ANCHOR_BUCKET.get(
                str(getattr(getattr(f, "anchor", None), "status", "") or "").upper(), "unplaced")
            bucket = _STATUS_BUCKET.get(
                str(getattr(getattr(f, "verification", None), "status", "") or ""), "unchecked")
            sources = tuple(sorted({source_family(t) for t in getattr(f, "sources", None) or ()}))
            by["severity"][severity] += 1
            by["anchor"][anchor] += 1
            by["bucket"][bucket] += 1
            for src in sources:
                by["source"][src] += 1
            if sources and not set(sources) & _READ_CHANNELS:
                offline += 1
            rows.append(LiveFinding(
                key=id(f), qc_id=str(getattr(f, "qc_id", "") or ""), severity=severity,
                category=str(getattr(f, "category", "") or ""),
                sheet=str(getattr(f, "sheet_id", "") or getattr(f, "source_name", "") or ""),
                text=" ".join(str(getattr(f, "text", "") or "").split())[:240],
                anchor=anchor, bucket=bucket, sources=sources,
                reproduced=bool(getattr(f, "reproduced", False)),
            ))
        rank = {"high": 0, "medium": 1, "low": 2}
        rows.sort(key=lambda r: (rank.get(r.severity, 3), r.qc_id or "~", r.sheet, r.text))
        self.ledger_total = len(rows)
        self.ledger_offline = offline
        self.ledger_findings = rows[:MAX_LIVE_FINDINGS]
        self.ledger_by = {k: dict(v) for k, v in by.items()}

    # -- journal ------------------------------------------------------------ #

    def _poll_journal(self, journal: Any, now: float) -> None:
        events = getattr(journal, "events", None)
        if events is None:
            return
        new = events[self._event_cursor:]
        self._event_cursor += len(new)
        for ev in new:
            try:
                self._on_event(ev, now)
            except Exception:  # noqa: BLE001 - one odd event never stalls the board
                continue

    def _on_event(self, ev: Any, now: float) -> None:
        code = str(getattr(ev, "event_code", "") or "")
        stage = str(getattr(ev, "stage", "") or "")
        f = dict(getattr(ev, "fields", None) or {})
        at = _event_epoch(getattr(ev, "timestamp", "")) or self._wall()
        if code == "RUN_START":
            self.run_started_at = self.run_started_at or at
            self.files = _int(f.get("files"))
            self._start_stage("inventory", at, now)
        elif code in ("INPUT_ACCEPTED", "INPUT_REJECTED"):
            if code == "INPUT_REJECTED":
                self.files_rejected += 1
                self._push("warn", f"Input rejected: {f.get('name', '?')} ({f.get('status', '?')})")
        elif code == "STAGE_START":
            if stage == "digest":
                inv = self._stage("inventory")
                if inv is not None and inv.state == STAGE_ACTIVE:
                    self._end_stage(inv, "PARTIAL" if self.files_rejected else "COMPLETE", at, now)
                self._push("info", f"Reading {_int(f.get('sheets'))} sheet(s)…")
            st = self._start_stage(stage, at, now)
            if st is not None and stage != "digest":
                self._push("info", f"{st.long_label}…")
        elif code == "STAGE_END":
            st = self._stage(stage)
            if st is not None:
                status = str(f.get("status", "") or "COMPLETE")
                st.note = str(f.get("error") or f.get("warning") or "")
                self._end_stage(st, status, at, now)
                if status in ("PARTIAL", "FAILED"):
                    self._push("warn" if status == "PARTIAL" else "bad",
                               f"{st.long_label}: {status.lower()}"
                               + (f" — {st.note}" if st.note else ""))
        elif code == "SHEET_RENDERED":
            idx = self._match_label(str(f.get("sheet", "")))
            if idx is not None:
                self._advance(self.sheets[idx], SHEET_RENDERED, now)
        elif code == "CACHE_PRESCAN":
            hits, total = _int(f.get("hits")), _int(f.get("total"))
            self.cache_hits = hits
            if hits:
                self._push("good", f"{hits} of {total} sheet(s) already in the cache — free")
        elif code == "SHEET_DIGESTED":
            idx = self._match_label(str(f.get("sheet", "")), source=str(f.get("source", "")),
                                    digested=False)
            if idx is not None:
                sheet = self.sheets[idx]
                sheet.digested = True
                if str(f.get("status")) != "OK":
                    self._settle(sheet, SHEET_FAILED, now)
                elif str(f.get("cached")).lower() == "true":
                    self._settle(sheet, SHEET_CACHED, now)
                else:
                    self._settle(sheet, SHEET_DONE, now)
        elif code == "SET_IDENTIFIED":
            self._push("good", f"Set identified: {f.get('disciplines', '?')} discipline(s), "
                               f"{f.get('adopted_codes', '?')} adopted code(s)")
        elif code == "REVIEW_PLAN_AUTHORED":
            self._push("good", f"Review plan: {f.get('items', '?')} checklist item(s)")
        elif code == "LEDGER_SEALED":
            self.findings_sealed = _int(f.get("entries"))
            self._push("good", f"Findings ledger sealed: {self.findings_sealed} finding(s)")
        elif code == "MARKUP_RECEIPTS":
            self.markup_written = _int(f.get("written")) + _int(f.get("indexed"))
            self.markup_expected = _int(f.get("expected"))
            self.coverage = str(f.get("coverage", "") or self.coverage)
            self._push("good" if self.coverage == "COMPLETE" else "warn",
                       f"Markups proven in the PDF: {self.markup_written}/{self.markup_expected}")
        elif code == "API_RETRY":
            self.retries += 1
            self.last_retry_at = now
            self._push("warn", f"API busy ({f.get('kind', 'transient')}) — backing off "
                               f"{f.get('backoff_s', '?')}s, then retrying")
        elif code == "API_GIVE_UP":
            self.give_ups += 1
            self._push("bad", f"Gave up on a request after {f.get('attempt', '?')} attempt(s)")
        elif code == "SPEND_LIMIT":
            self.spend_limit = True
            self._push("bad", "API spend limit reached — paid requests stopped")
        elif code == "BUDGET_EXHAUSTED":
            self._push("warn", f"{stage}: {f.get('kind', 'budget')} allotment used up")
        elif code == "RESOURCE_PRESSURE":
            self._push("warn", f"This computer is under pressure ({f.get('kind', '?')})")
        elif code == "RUN_BLOCKED":
            self.outcome = "FAILED"
            self._push("bad", f"Run blocked: {f.get('reason', '?')}")
        elif code == "RUN_END":
            self.outcome = str(f.get("outcome") or f.get("status") or "")
            self.qc_status = str(f.get("status", "") or "")
            self.coverage = str(f.get("coverage", "") or self.coverage)
            self.run_ended_at = at

    # -- call records -------------------------------------------------------- #

    def _poll_calls(self, calls: Any, now: float, *, fast: bool) -> None:
        records = getattr(calls, "records", None)
        if records is None:
            return
        new = records[self._call_cursor:]
        self._call_cursor += len(new)
        for rec in new:
            seq = getattr(rec, "seq", None)
            if seq is None:
                continue
            self._open[seq] = rec
            self._unplaced.add(seq)
            self._on_call_opened(rec)
        # A batch record is listed a moment before its sheet label is set on
        # it, so an open record that named no sheet yet is retried each poll.
        for seq in list(self._unplaced):
            rec = self._open.get(seq)
            if rec is None:
                self._unplaced.discard(seq)
            elif self._place_call(rec, now):
                self._unplaced.discard(seq)
        for seq, rec in list(self._open.items()):
            if str(getattr(rec, "outcome", "") or "") in ("", OUTCOME_PENDING):
                continue
            del self._open[seq]
            if seq in self._unplaced:
                self._unplaced.discard(seq)
                self._place_call(rec, now)
            self._settling[seq] = (rec, now)
            self._on_call_settled(rec, now)
        for seq, (rec, since) in list(self._settling.items()):
            self._account(seq, rec, now, fast=fast)
            if now - since > _SETTLE_WINDOW_SECONDS:
                del self._settling[seq]
                self._counted.pop(seq, None)

    def _call_stage(self, rec: Any) -> "LiveStage | None":
        family = canonical_stage(str(getattr(rec, "stage", "") or ""))
        name = _FAMILY_STAGE.get(family)
        if name is None:
            return None
        st = self._stage(name)
        if st is None:
            st = self._insert_stage(name, now=self._clock())
        if st is not None and st.state == STAGE_PLANNED and self.phase == PHASE_RUNNING:
            st.state, st.changed_at = STAGE_ACTIVE, self._clock()
            st.started_at = st.started_at or self._wall()
        return st

    def _on_call_opened(self, rec: Any) -> None:
        batch = getattr(rec, "transport", "") == TRANSPORT_BATCH
        st = self._call_stage(rec)
        if st is not None:
            if batch:
                st.calls_queued += 1
            else:
                st.calls_open += 1
            st.model = str(getattr(rec, "model", "") or st.model)
            st.effort = str(getattr(rec, "effort", "") or "")
            st.thinking = str(getattr(rec, "thinking", "") or "")
            st.batch = batch

    def _place_call(self, rec: Any, now: float) -> bool:
        """Show an open call on its sheet; ``False`` while it names none yet."""
        family = canonical_stage(str(getattr(rec, "stage", "") or ""))
        if family not in ("digest", "critique"):
            return True                       # not a per-sheet call
        sheet = self._sheet_for(rec)
        if sheet is None:
            return False
        batch = getattr(rec, "transport", "") == TRANSPORT_BATCH
        if family == "digest":
            self._advance(sheet, SHEET_QUEUED if batch else SHEET_READING, now)
        else:
            if batch:
                sheet.critique_queued += 1
            else:
                sheet.critique_open += 1
            sheet.critique_changed_at = now
        return True

    def _on_call_settled(self, rec: Any, now: float) -> None:
        batch = getattr(rec, "transport", "") == TRANSPORT_BATCH
        outcome = str(getattr(rec, "outcome", "") or "")
        ok = outcome in _COMPLETING
        st = self._call_stage(rec)
        if st is not None:
            if batch:
                st.calls_queued = max(0, st.calls_queued - 1)
            else:
                st.calls_open = max(0, st.calls_open - 1)
            if ok:
                st.calls_done += 1
            elif outcome != OUTCOME_CANCELLED:
                st.calls_failed += 1
        if ok:
            self.calls_done += 1
        elif outcome != OUTCOME_CANCELLED:
            self.calls_failed += 1
        family = canonical_stage(str(getattr(rec, "stage", "") or ""))
        if family == "verify" and ok:
            base = str(getattr(rec, "item", "") or "").split(":", 1)[0]
            if base:
                self._verify_items.add(base)
                self.findings_verified = len(self._verify_items)
        sheet = self._sheet_for(rec)
        if sheet is None:
            return
        if family == "digest":
            if ok:
                self._advance(sheet, SHEET_DONE, now)
            elif outcome != OUTCOME_CANCELLED:
                sheet.hiccup_at = now
        elif family == "critique":
            if batch:
                sheet.critique_queued = max(0, sheet.critique_queued - 1)
            else:
                sheet.critique_open = max(0, sheet.critique_open - 1)
            if ok:
                sheet.critique_done += 1
            elif outcome != OUTCOME_CANCELLED:
                sheet.hiccup_at = now
            sheet.critique_changed_at = now

    def _account(self, seq: int, rec: Any, now: float, *, fast: bool) -> None:
        tin = (int(getattr(rec, "input_tokens", 0) or 0)
               + int(getattr(rec, "cache_read_tokens", 0) or 0)
               + int(getattr(rec, "cache_write_tokens", 0) or 0))
        tout = int(getattr(rec, "output_tokens", 0) or 0)
        cost = call_record_cost(rec, fast=fast)
        prev_in, prev_out, prev_cost = self._counted.get(seq, (0, 0, Decimal(0)))
        d_in, d_out = tin - prev_in, tout - prev_out
        d_cost = (cost or Decimal(0)) - prev_cost
        if not (d_in or d_out or d_cost):
            return
        self._counted[seq] = (tin, tout, cost or Decimal(0))
        self.tokens_in += d_in
        self.tokens_out += d_out
        if cost is not None:
            self.cost_known = True
        self.cost += d_cost
        sheet = self._sheet_for(rec)
        if sheet is not None:
            sheet.tokens += d_in + d_out
        st = self._stage(_FAMILY_STAGE.get(
            canonical_stage(str(getattr(rec, "stage", "") or "")), ""))
        if st is not None:
            st.tokens_in += d_in
            st.tokens_out += d_out
            st.cost += d_cost
        second = int(now)
        if self.series and self.series[-1][0] == second:
            self.series[-1][1] += d_in
            self.series[-1][2] += d_out
        else:
            self.series.append([second, d_in, d_out])

    # -- stage helpers ------------------------------------------------------- #

    def _plan(self, names: list[str], now: float, *, keep_started: bool = False) -> None:
        """Lay the track out for ``names``; a node already on it keeps its object
        (and so its animation state) — only a newly planned node pops in."""
        existing = {s.name: s for s in self.stages}
        stages = []
        for name in names:
            if name not in _STAGE_LABELS or any(s.name == name for s in stages):
                continue
            st = existing.get(name)
            if st is None:
                short, long = _STAGE_LABELS[name]
                st = LiveStage(name=name, label=short, long_label=long, changed_at=now)
            stages.append(st)
        if keep_started:
            # A stage the run already started stays, even if the plan dropped it.
            for st in self.stages:
                if st.state != STAGE_PLANNED and st not in stages:
                    stages.append(st)
        stages.sort(key=lambda s: _STAGE_ORDER.get(s.name, 999))
        self.stages = stages

    def _stage(self, name: str) -> "LiveStage | None":
        for st in self.stages:
            if st.name == name:
                return st
        return None

    def _insert_stage(self, name: str, now: float) -> "LiveStage | None":
        if name not in _STAGE_LABELS:
            return None
        short, long = _STAGE_LABELS[name]
        st = LiveStage(name=name, label=short, long_label=long, changed_at=now)
        self.stages.append(st)
        self.stages.sort(key=lambda s: _STAGE_ORDER.get(s.name, 999))
        return st

    def _start_stage(self, name: str, at: float, now: float) -> "LiveStage | None":
        st = self._stage(name) or self._insert_stage(name, now)
        if st is None:
            return None
        if st.state in (STAGE_PLANNED, STAGE_SKIPPED, STAGE_DONE):
            # A stage can run twice (cross-QC / synthesis on the overlap path):
            # the second start re-opens it; its duration spans both.
            st.state, st.changed_at = STAGE_ACTIVE, now
            st.started_at = st.started_at or at
            st.ended_at = None
        return st

    def _end_stage(self, st: LiveStage, status: str, at: float, now: float) -> None:
        st.state, st.status, st.changed_at = STAGE_DONE, status, now
        if st.started_at is None:
            st.started_at = at
        st.ended_at = at

    # -- sheet helpers ------------------------------------------------------- #

    def _set_sheets(self, rows: list, now: float, *, appear: bool = True) -> None:
        self.sheets = []
        for i, row in enumerate(rows):
            item, label = str(row[0]), str(row[1])
            source = str(row[2]) if len(row) > 2 else ""
            self.sheets.append(LiveSheet(
                item=item, label=label, source_id=source, index=i, changed_at=now,
            ))
        if appear:
            self.sheets_since = now
        self._index_sheets()

    def _index_sheets(self) -> None:
        from .run_journal import sanitize_text

        self._sheet_by_item = {s.item: s.index for s in self.sheets}
        self._sheet_by_label = {}
        for s in self.sheets:
            keys = {s.label}
            try:
                keys.add(sanitize_text(s.label, private_roots=self._journal_roots))
            except Exception:  # noqa: BLE001
                pass
            for key in keys:
                self._sheet_by_label.setdefault(key, []).append(s.index)

    def _match_label(self, label: str, *, source: str = "",
                     digested: "bool | None" = None) -> "int | None":
        """The sheet a journal label names (labels are display text, not ids).

        Two inputs can share a basename, so a label may name several sheets:
        ``source`` narrows by source id, and ``digested=False`` prefers a
        sheet whose outcome has not landed yet.
        """
        if not self._sheet_by_label and self.sheets:
            self._index_sheets()
        candidates = self._sheet_by_label.get(label, [])
        if source:
            narrowed = [i for i in candidates if self.sheets[i].source_id in ("", source)]
            candidates = narrowed or candidates
        if digested is False:
            fresh = [i for i in candidates if not self.sheets[i].digested]
            candidates = fresh or candidates
        return candidates[0] if candidates else None

    def _sheet_for(self, rec: Any) -> "LiveSheet | None":
        key = sheet_key_of(str(getattr(rec, "item", "") or ""))
        idx = self._sheet_by_item.get(key) if key else None
        return self.sheets[idx] if idx is not None else None

    def _advance(self, sheet: LiveSheet, state: str, now: float) -> None:
        if _SHEET_RANK[state] > _SHEET_RANK.get(sheet.state, 0):
            sheet.state, sheet.changed_at = state, now

    def _settle(self, sheet: LiveSheet, state: str, now: float) -> None:
        if sheet.state != state:
            sheet.state, sheet.changed_at = state, now

    def _settle_sheet_from_digest(self, sd: Any, now: float) -> None:
        ref = getattr(sd, "ref", None)
        if ref is None:
            return
        from .call_telemetry import sheet_item

        idx = self._sheet_by_item.get(sheet_item(ref))
        if idx is None:
            return
        sheet = self.sheets[idx]
        if sheet.digested:
            return
        sheet.digested = True
        if not getattr(sd, "ok", False):
            self._settle(sheet, SHEET_FAILED, now)
        elif getattr(sd, "cached", False):
            self._settle(sheet, SHEET_CACHED, now)
        else:
            self._settle(sheet, SHEET_DONE, now)

    def _push(self, level: str, text: str) -> None:
        self.ticker.append(TickerItem(at=self._clock(), level=level, text=str(text)[:160]))
