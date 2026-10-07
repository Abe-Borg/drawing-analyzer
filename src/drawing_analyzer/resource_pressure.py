"""Resource-starvation diagnostics for one analysis run (run.log / manifest).

The run journal records *what* each stage did and how long it took; the usage
ledger records what it billed. Neither could answer the question a slow or
partial run raises first: **were the agents starved of resources while they
worked?** Were the model calls throttled by the API (429 / 529 / 503 retry
waves), did the host run out of CPU, memory or disk underneath the worker
threads, did an agent exhaust its own allotment (output cap, evidence rounds,
reference cap, batch time bound) before it could finish? Every transient retry
in every stage used to ``sleep()`` and ``continue`` silently, and nothing
sampled the host at all, so a run that spent forty minutes in rate-limit
backoff was indistinguishable in ``run.log`` from one that spent them reading.

This module is the per-run **resource pressure** record. The pipeline attaches
it to the ``DrawingContext`` as ``resource_pressure``; it is rendered into
``run.log`` (a *Resource pressure* section), ``run_manifest.json`` (a
``resource_pressure`` block), the report's run-record block and the GUI's
completion summary. Three legs feed it:

1. **API capacity.** Every transient retry reports here through
   :func:`drawing_analyzer.digest.transient_retry_wait` (the shared helper the
   stage retry loops call): stage, kind (rate limited / overloaded / server
   error / connection / timeout), HTTP status, attempt, backoff slept, the
   ``retry-after`` the server asked for, the ``anthropic-ratelimit-*-remaining``
   headers when the error carried them, and whether the loop finally gave up.
   The Files-API upload retry and the batch results-stream retry report too.
2. **Host resources.** A daemon sampler (:class:`HostResourceMonitor`) ticks on
   a fixed interval and records *scheduling lag* (how late it woke — the direct
   sign that this process could not get CPU), process CPU time, resident and
   peak memory, system memory load, system CPU busy, free disk on the run's
   working locations, and the thread count. Platform readers are stdlib +
   ``ctypes`` (Windows ``psapi``/``kernel32``, Linux ``/proc``); a metric a
   platform cannot read is reported as *unavailable*, never guessed.
3. **Agent budgets.** The pipeline notes every allotment an agent exhausted:
   digest output caps that stayed truncated, verifier replies cut off at
   ``max_tokens``, investigations that hit the evidence-round cap or the
   per-run finding cap, citation references beyond the per-run cap, and batch
   attempts abandoned by the stall watch or the time bound.

The record derives a one-word verdict — ``starvation_status`` of ``DETECTED``
or ``NOT_DETECTED`` — from named **signals** (:data:`SIGNAL_API_THROTTLED`,
:data:`SIGNAL_CPU_STARVED`, :data:`SIGNAL_MEMORY_PRESSURE`,
:data:`SIGNAL_LOW_DISK`, :data:`SIGNAL_BUDGET_EXHAUSTED`), each carrying the
evidence that fired it. Thresholds are the module constants below.

Design rules:

- **Advisory, never fatal** (I-3 spirit): every public entry swallows its own
  failures, and a probe that cannot read a metric degrades to ``None``.
- **Counts, labels and byte totals only.** Disk is reported by *label*
  (``work_dir`` / ``temp`` / ``cache``), never by path; no prompt, no drawing
  text, no secret. Journal events pass the journal's own sanitize boundary.
- **Bounded.** The stored API-event list, the budget list and the per-run
  journal incident events are capped so a pathological run cannot bloat the
  manifest or drown ``run.log``; the aggregates still count everything.
- **Dependency-free.** No ``psutil``, no PyMuPDF (I-5).
- **Run-scoped active recorder**, reached like the diagnostics logger: the
  pipeline activates one for the duration of ``extract_drawing_context``
  (:func:`tracked_run`), which binds the calling thread to it; every thread
  pool a run opens binds its workers to the same recorder through
  :func:`worker_binding` (an ``initializer``), so retry loops reach it through
  :func:`note_api_retry` without plumbing a handle through every signature,
  and two runs in one process (the pipeline keeps per-run executor state for
  exactly that) never see each other's retries. A thread bound to no run
  falls back to the one live recorder when exactly one run is live, and
  records nothing — rather than guessing — when several are.
"""
from __future__ import annotations

import math
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
from typing import Any, Callable

from . import cancellation
from .diagnostics import get_logger, request_id_of, status_of

_log = get_logger()

# Host sampler cadence. ``0`` (or any disable token) turns the sampler off; the
# API and budget legs still record. Clamped so a typo cannot spin a hot loop or
# sample once an hour.
ENV_SAMPLE_SECONDS = "DRAWING_ANALYZER_RESOURCE_SAMPLE_SECONDS"
DEFAULT_SAMPLE_SECONDS = 5.0
MIN_SAMPLE_SECONDS = 1.0
MAX_SAMPLE_SECONDS = 300.0
_DISABLE_TOKENS = frozenset({"0", "false", "no", "off", "none"})

# Verdict vocabulary (``starvation_status``).
STARVATION_DETECTED = "DETECTED"
STARVATION_NOT_DETECTED = "NOT_DETECTED"

# Signal kinds.
SIGNAL_API_THROTTLED = "API_THROTTLED"
SIGNAL_CPU_STARVED = "CPU_STARVED"
SIGNAL_MEMORY_PRESSURE = "MEMORY_PRESSURE"
SIGNAL_LOW_DISK = "LOW_DISK"
SIGNAL_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"

# Transient-failure kinds (``ApiRetryEvent.kind``). The first three are
# *capacity* answers — the API had no room for the request — and drive the
# throttle signal; connection / timeout / server errors are recorded and
# counted but are not, by themselves, evidence of starvation.
KIND_RATE_LIMITED = "rate_limited"       # 429
KIND_OVERLOADED = "overloaded"           # 529 (Messages) — the API is saturated
KIND_UNAVAILABLE = "unavailable"         # 503 — the Files API's "overloaded" shape
KIND_SERVER_ERROR = "server_error"       # 500 / 502 / 504
KIND_TIMEOUT = "timeout"                 # 408, APITimeoutError, ReadTimeout
KIND_CONNECTION = "connection"           # APIConnectionError, transport errors
KIND_OTHER = "other"
THROTTLE_KINDS = frozenset({KIND_RATE_LIMITED, KIND_OVERLOADED, KIND_UNAVAILABLE})

# Signal thresholds. A couple of recovered retries over a long run are weather,
# not starvation; the signal fires when the API refused a request until the
# loop stopped asking (a give-up), when capacity answers pile up, or when the
# run spent real wall-clock in backoff.
API_THROTTLE_RETRIES_FOR_SIGNAL = 3
API_BACKOFF_SECONDS_FOR_SIGNAL = 30.0
# A tick is "late" when the sampler woke this much after it asked to: at least
# a second, and at least half an interval, so GC pauses and the ~16 ms Windows
# timer granularity never register. Two late ticks, or one severe one, is CPU
# starvation; one late tick is logged as an incident but is not a verdict.
LAG_FRACTION_OF_INTERVAL = 0.5
MIN_LAG_SECONDS = 1.0
SEVERE_LAG_SECONDS = 10.0
LATE_TICKS_FOR_SIGNAL = 2
MEMORY_LOAD_PCT_FOR_SIGNAL = 90.0
MEMORY_AVAILABLE_BYTES_FOR_SIGNAL = 512 * 1024 * 1024
LOW_DISK_BYTES = 1024 ** 3

# Bounds (the aggregates keep counting past them).
MAX_STORED_API_EVENTS = 200
MAX_STORED_EXHAUSTIONS = 100
MAX_INCIDENT_EVENTS = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# --------------------------------------------------------------------------- #
# Transient-failure classification and the headers that explain a 429.
# --------------------------------------------------------------------------- #


def classify_transient(exc: BaseException) -> str:
    """Name the kind of transient failure ``exc`` is (duck-typed, never raises)."""
    try:
        status = status_of(exc)
    except Exception:  # noqa: BLE001
        status = None
    if status == 429:
        return KIND_RATE_LIMITED
    if status == 529:
        return KIND_OVERLOADED
    if status == 503:
        return KIND_UNAVAILABLE
    if status == 408:
        return KIND_TIMEOUT
    if status is not None and status >= 500:
        return KIND_SERVER_ERROR
    if status is not None:
        return KIND_OTHER
    names = {cls.__name__ for cls in type(exc).__mro__}
    joined = " ".join(names)
    if "Timeout" in joined:
        return KIND_TIMEOUT
    if any(tag in joined for tag in ("Connection", "Network", "Transport", "Protocol", "ReadError")):
        return KIND_CONNECTION
    return KIND_OTHER


def _header(exc: Any, name: str) -> str | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except Exception:  # noqa: BLE001 - a headers map of any shape
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", "replace")
    return value.strip() if isinstance(value, str) and value.strip() else None


def retry_after_seconds(exc: Any, *, now: datetime | None = None) -> float | None:
    """The ``Retry-After`` an error carried, in seconds, or ``None``.

    Both RFC 7231 forms are accepted: a delta in seconds and an HTTP-date,
    which is converted against ``now`` (injectable). Non-finite or negative
    answers read as ``None`` / ``0`` rather than poisoning a maximum.
    """
    raw = _header(exc, "retry-after")
    if raw is None:
        return None
    try:
        delta = float(raw)
    except ValueError:
        delta = None
    if delta is not None:
        return max(0.0, delta) if math.isfinite(delta) else None
    try:
        when = parsedate_to_datetime(raw)
    except Exception:  # noqa: BLE001 - malformed date
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    now = now or _utc_now()
    return max(0.0, (when - now).total_seconds())


# The remaining-capacity headers Anthropic returns; recorded when an error
# carries them so a 429 can be read as "requests exhausted" vs "tokens
# exhausted" after the fact. Key → header.
RATE_LIMIT_HEADERS: tuple[tuple[str, str], ...] = (
    ("requests_remaining", "anthropic-ratelimit-requests-remaining"),
    ("tokens_remaining", "anthropic-ratelimit-tokens-remaining"),
    ("input_tokens_remaining", "anthropic-ratelimit-input-tokens-remaining"),
    ("output_tokens_remaining", "anthropic-ratelimit-output-tokens-remaining"),
)


def rate_limit_snapshot(exc: Any) -> dict[str, int]:
    """The integer ``anthropic-ratelimit-*-remaining`` headers on ``exc``, if any."""
    out: dict[str, int] = {}
    for key, header in RATE_LIMIT_HEADERS:
        raw = _header(exc, header)
        if raw is None:
            continue
        try:
            out[key] = int(raw)
        except ValueError:
            continue
    return out


# --------------------------------------------------------------------------- #
# Records.
# --------------------------------------------------------------------------- #


@dataclass
class ApiRetryEvent:
    """One transient API failure the run waited out (or gave up on)."""

    stage: str
    kind: str
    status: int | None
    attempt: int                       # 1-based: the retry this wait precedes
    backoff_seconds: float
    retry_after_seconds: float | None = None
    request_id: str = ""
    rate_limit: dict = field(default_factory=dict)
    gave_up: bool = False              # the loop stopped asking after this failure
    at: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "kind": self.kind,
            "status": self.status,
            "attempt": self.attempt,
            "backoff_seconds": round(float(self.backoff_seconds), 3),
            "retry_after_seconds": (
                None if self.retry_after_seconds is None
                else round(float(self.retry_after_seconds), 3)
            ),
            "request_id": self.request_id,
            "rate_limit": dict(self.rate_limit),
            "gave_up": self.gave_up,
            "at": self.at,
        }


@dataclass
class BudgetExhaustion:
    """An allotment an agent ran out of before it could finish."""

    stage: str
    kind: str          # output_cap | evidence_rounds | finding_cap | reference_cap | batch_abandoned
    count: int = 1
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage, "kind": self.kind,
            "count": int(self.count), "detail": self.detail,
        }


@dataclass
class HostSample:
    """One reading of the host, as the probe saw it. ``None`` = unreadable."""

    wall: float                                     # monotonic seconds
    process_cpu_seconds: float | None = None
    rss_bytes: int | None = None
    peak_rss_bytes: int | None = None
    system_memory_total: int | None = None
    system_memory_available: int | None = None
    system_cpu_times: tuple[float, float] | None = None   # cumulative (idle, total)
    load_1m: float | None = None
    disk_free: dict[str, int] = field(default_factory=dict)
    disk_total: dict[str, int] = field(default_factory=dict)
    threads: int = 0
    unavailable: tuple[str, ...] = ()


@dataclass
class HostStats:
    """The sampler's aggregates — what the manifest keeps instead of the series."""

    monitored: bool = False
    disabled_reason: str = ""
    interval_seconds: float = 0.0
    samples: int = 0
    late_ticks: int = 0
    worst_lag_seconds: float = 0.0
    total_lag_seconds: float = 0.0
    cpu_count: int = 0
    wall_seconds: float = 0.0
    process_cpu_seconds: float = 0.0
    process_cpu_peak_ratio: float = 0.0          # busiest interval: cpu / wall
    rss_max_bytes: int | None = None
    peak_rss_bytes: int | None = None
    system_memory_total: int | None = None
    system_memory_available_min: int | None = None
    system_memory_load_max_pct: float | None = None
    system_cpu_busy_max_pct: float | None = None
    system_cpu_busy_sum_pct: float = 0.0
    system_cpu_busy_samples: int = 0
    load_1m_max: float | None = None
    disk_free_min: dict[str, int] = field(default_factory=dict)
    disk_total: dict[str, int] = field(default_factory=dict)
    threads_max: int = 0
    memory_pressure_samples: int = 0
    low_disk_samples: int = 0
    unavailable: set = field(default_factory=set)

    @property
    def process_cpu_mean_ratio(self) -> float:
        return self.process_cpu_seconds / self.wall_seconds if self.wall_seconds > 0 else 0.0

    @property
    def system_cpu_busy_mean_pct(self) -> float | None:
        if not self.system_cpu_busy_samples:
            return None
        return self.system_cpu_busy_sum_pct / self.system_cpu_busy_samples

    def to_dict(self) -> dict:
        return {
            "monitored": self.monitored,
            "disabled_reason": self.disabled_reason,
            "interval_seconds": self.interval_seconds,
            "samples": self.samples,
            "late_ticks": self.late_ticks,
            "worst_lag_seconds": round(self.worst_lag_seconds, 3),
            "total_lag_seconds": round(self.total_lag_seconds, 3),
            "cpu_count": self.cpu_count,
            "wall_seconds": round(self.wall_seconds, 3),
            "process_cpu_seconds": round(self.process_cpu_seconds, 3),
            "process_cpu_mean_ratio": round(self.process_cpu_mean_ratio, 4),
            "process_cpu_peak_ratio": round(self.process_cpu_peak_ratio, 4),
            "rss_max_bytes": self.rss_max_bytes,
            "peak_rss_bytes": self.peak_rss_bytes,
            "system_memory_total_bytes": self.system_memory_total,
            "system_memory_available_min_bytes": self.system_memory_available_min,
            "system_memory_load_max_pct": (
                None if self.system_memory_load_max_pct is None
                else round(self.system_memory_load_max_pct, 1)
            ),
            "system_cpu_busy_max_pct": (
                None if self.system_cpu_busy_max_pct is None
                else round(self.system_cpu_busy_max_pct, 1)
            ),
            "system_cpu_busy_mean_pct": (
                None if self.system_cpu_busy_mean_pct is None
                else round(self.system_cpu_busy_mean_pct, 1)
            ),
            "load_1m_max": None if self.load_1m_max is None else round(self.load_1m_max, 2),
            "disk_free_min_bytes": dict(sorted(self.disk_free_min.items())),
            "disk_total_bytes": dict(sorted(self.disk_total.items())),
            "threads_max": self.threads_max,
            "memory_pressure_samples": self.memory_pressure_samples,
            "low_disk_samples": self.low_disk_samples,
            "unavailable": sorted(self.unavailable),
        }


# --------------------------------------------------------------------------- #
# The host probe: platform readers, each degrading to None.
# --------------------------------------------------------------------------- #


class HostProbe:
    """Read one :class:`HostSample`.

    ``paths`` maps a *label* (``work_dir`` / ``temp`` / ``cache``) to a
    directory whose free space is sampled; only the label ever leaves this
    class. Every reader is wrapped: an unreadable metric is ``None`` and its
    name lands in ``unavailable``, so the record says what it could not
    measure instead of reporting a comforting zero.
    """

    def __init__(self, paths: dict[str, Any] | None = None, *, platform: str | None = None) -> None:
        self.paths: dict[str, str] = {}
        for label, path in (paths or {}).items():
            if path:
                self.paths[str(label)] = str(path)
        self.platform = platform or sys.platform
        self.cpu_count = os.cpu_count() or 1
        self._page_size = self._read_page_size()
        self._win: Any = None
        if self.platform == "win32":
            try:
                self._win = _WindowsApi()
            except Exception:  # noqa: BLE001 - probe stays usable without it
                self._win = None

    @staticmethod
    def _read_page_size() -> int:
        try:
            return int(os.sysconf("SC_PAGE_SIZE"))
        except (AttributeError, ValueError, OSError):
            return 4096

    # -- readers ------------------------------------------------------------ #

    def _process_cpu(self) -> float | None:
        try:
            return float(time.process_time())
        except Exception:  # noqa: BLE001
            return None

    def _process_memory(self) -> tuple[int | None, int | None]:
        """``(rss_bytes, peak_rss_bytes)``."""
        if self.platform == "win32":
            if self._win is None:
                return None, None
            try:
                return self._win.process_memory()
            except Exception:  # noqa: BLE001
                return None, None
        rss: int | None = None
        peak: int | None = None
        if self.platform.startswith("linux"):
            try:
                with open("/proc/self/statm", encoding="ascii") as fh:
                    rss = int(fh.read().split()[1]) * self._page_size
            except Exception:  # noqa: BLE001
                rss = None
        try:
            import resource

            maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux reports kilobytes, macOS bytes.
            peak = int(maxrss) if self.platform == "darwin" else int(maxrss) * 1024
        except Exception:  # noqa: BLE001
            peak = None
        return rss, peak

    def _system_memory(self) -> tuple[int | None, int | None]:
        """``(total_bytes, available_bytes)``."""
        if self.platform == "win32":
            if self._win is None:
                return None, None
            try:
                return self._win.system_memory()
            except Exception:  # noqa: BLE001
                return None, None
        if self.platform.startswith("linux"):
            try:
                total = avail = None
                with open("/proc/meminfo", encoding="ascii") as fh:
                    for line in fh:
                        if line.startswith("MemTotal:"):
                            total = int(line.split()[1]) * 1024
                        elif line.startswith("MemAvailable:"):
                            avail = int(line.split()[1]) * 1024
                        if total is not None and avail is not None:
                            break
                return total, avail
            except Exception:  # noqa: BLE001
                return None, None
        return None, None

    def _system_cpu_times(self) -> tuple[float, float] | None:
        """Cumulative ``(idle, total)`` seconds; busy% is derived between samples."""
        if self.platform == "win32":
            if self._win is None:
                return None
            try:
                return self._win.system_cpu_times()
            except Exception:  # noqa: BLE001
                return None
        if self.platform.startswith("linux"):
            try:
                with open("/proc/stat", encoding="ascii") as fh:
                    fields = fh.readline().split()
                if fields[0] != "cpu":
                    return None
                values = [float(v) for v in fields[1:9]]   # user..steal
                idle = values[3] + values[4]               # idle + iowait
                return idle, sum(values)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _load(self) -> float | None:
        getloadavg = getattr(os, "getloadavg", None)
        if getloadavg is None:
            return None
        try:
            return float(getloadavg()[0])
        except (OSError, ValueError):
            return None

    def _disk(self) -> tuple[dict[str, int], dict[str, int], list[str]]:
        free: dict[str, int] = {}
        total: dict[str, int] = {}
        missing: list[str] = []
        for label, path in self.paths.items():
            try:
                usage = shutil.disk_usage(path)
            except Exception:  # noqa: BLE001 - a vanished dir is not an error
                missing.append(f"disk:{label}")
                continue
            free[label] = int(usage.free)
            total[label] = int(usage.total)
        return free, total, missing

    def sample(self) -> HostSample:
        unavailable: list[str] = []
        cpu = self._process_cpu()
        if cpu is None:
            unavailable.append("process_cpu")
        rss, peak = self._process_memory()
        if rss is None:
            unavailable.append("process_rss")
        if peak is None:
            unavailable.append("process_peak_rss")
        mem_total, mem_avail = self._system_memory()
        if mem_total is None or mem_avail is None:
            unavailable.append("system_memory")
        cpu_times = self._system_cpu_times()
        if cpu_times is None:
            unavailable.append("system_cpu")
        load = self._load()
        free, total, missing = self._disk()
        unavailable.extend(missing)
        try:
            threads = threading.active_count()
        except Exception:  # noqa: BLE001
            threads = 0
        return HostSample(
            wall=time.monotonic(),
            process_cpu_seconds=cpu,
            rss_bytes=rss,
            peak_rss_bytes=peak,
            system_memory_total=mem_total,
            system_memory_available=mem_avail,
            system_cpu_times=cpu_times,
            load_1m=load,
            disk_free=free,
            disk_total=total,
            threads=threads,
            unavailable=tuple(unavailable),
        )


class _WindowsApi:
    """``psapi`` / ``kernel32`` readers via ctypes (constructed only on win32)."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        self._wintypes = wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        self.PROCESS_MEMORY_COUNTERS = PROCESS_MEMORY_COUNTERS
        self.MEMORYSTATUSEX = MEMORYSTATUSEX
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self.psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD,
        ]
        self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self.kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
        self.kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        self.kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(wintypes.FILETIME)] * 3
        self.kernel32.GetSystemTimes.restype = wintypes.BOOL

    def process_memory(self) -> tuple[int | None, int | None]:
        counters = self.PROCESS_MEMORY_COUNTERS()
        counters.cb = self._ctypes.sizeof(counters)
        ok = self.psapi.GetProcessMemoryInfo(
            self.kernel32.GetCurrentProcess(), self._ctypes.byref(counters), counters.cb
        )
        if not ok:
            return None, None
        return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)

    def system_memory(self) -> tuple[int | None, int | None]:
        status = self.MEMORYSTATUSEX()
        status.dwLength = self._ctypes.sizeof(status)
        if not self.kernel32.GlobalMemoryStatusEx(self._ctypes.byref(status)):
            return None, None
        return int(status.ullTotalPhys), int(status.ullAvailPhys)

    def system_cpu_times(self) -> tuple[float, float] | None:
        ft = self._wintypes.FILETIME
        idle, kernel, user = ft(), ft(), ft()
        ok = self.kernel32.GetSystemTimes(
            self._ctypes.byref(idle), self._ctypes.byref(kernel), self._ctypes.byref(user)
        )
        if not ok:
            return None

        def seconds(value: Any) -> float:
            return ((int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)) / 1e7

        # Kernel time includes idle time, so kernel + user is the total.
        return seconds(idle), seconds(kernel) + seconds(user)


# --------------------------------------------------------------------------- #
# The sampler thread.
# --------------------------------------------------------------------------- #


def resolve_sample_interval(raw: str | None = None) -> float | None:
    """The sampler interval from the environment: ``None`` when disabled.

    ``raw`` defaults to :data:`ENV_SAMPLE_SECONDS`. Disable tokens and ``0``
    turn the sampler off; a malformed value keeps the default; a positive value
    is clamped to ``[MIN_SAMPLE_SECONDS, MAX_SAMPLE_SECONDS]``.
    """
    if raw is None:
        raw = os.environ.get(ENV_SAMPLE_SECONDS)
    if raw is None:
        return DEFAULT_SAMPLE_SECONDS
    text = raw.strip().lower()
    if text in _DISABLE_TOKENS or text == "":
        return None
    try:
        value = float(text)
    except ValueError:
        return DEFAULT_SAMPLE_SECONDS
    if not math.isfinite(value) or value <= 0:
        return None
    return min(max(value, MIN_SAMPLE_SECONDS), MAX_SAMPLE_SECONDS)


class HostResourceMonitor:
    """A daemon thread that samples the host every ``interval`` seconds.

    Each wake measures its own *scheduling lag* — how much later than asked it
    actually ran — which is the one signal that reads CPU starvation of **this
    process** directly, whatever its cause (a saturated machine, a GIL held by
    a long native call, a laptop throttling). The reading is handed to the
    owning :class:`ResourcePressure`, which keeps aggregates and decides what
    counts as an incident. ``stop()`` is prompt (``Event.wait``) and takes one
    final sample on the caller's thread so a short run still has two readings.
    """

    def __init__(
        self,
        owner: "ResourcePressure",
        *,
        interval: float,
        probe: HostProbe,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._owner = owner
        self.interval = float(interval)
        self._probe = probe
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._owner._ingest_host_sample(self._probe.sample(), lag_seconds=0.0)
        self._thread = threading.Thread(
            target=self._loop, name="drawing-analyzer-resource-monitor", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        last = self._clock()
        while not self._stop.wait(self.interval):
            now = self._clock()
            lag = max(0.0, (now - last) - self.interval)
            try:
                self._owner._ingest_host_sample(self._probe.sample(), lag_seconds=lag)
            except Exception:  # noqa: BLE001 - the sampler must never die noisily
                _log.debug("resource monitor sample failed", exc_info=True)
            last = self._clock()

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        try:
            self._owner._ingest_host_sample(self._probe.sample(), lag_seconds=0.0)
        except Exception:  # noqa: BLE001
            _log.debug("resource monitor final sample failed", exc_info=True)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# --------------------------------------------------------------------------- #
# The per-run record.
# --------------------------------------------------------------------------- #


def _fmt_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:,.0f} {unit}" if unit == "B" else f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} TB"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or singular + "s")


class ResourcePressure:
    """The run's resource-starvation record (API retries, host samples, budgets).

    Thread-safe: retry notes arrive from the digest pool and the sampler
    thread while the main thread wires stages. Every public method swallows
    its own failures — this is a diagnostic, and a diagnostic that fails a
    run has inverted its purpose.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = threading.RLock()
        self._clock = clock or _utc_now
        self._journal: Any = None
        self.started_at: datetime = self._clock()
        self.finished_at: datetime | None = None
        # API leg.
        self.api_events: list[ApiRetryEvent] = []
        self.api_events_dropped = 0
        self.api_retries = 0
        self.api_give_ups = 0
        self.api_backoff_seconds = 0.0
        self.api_retry_after_max: float | None = None
        self.api_by_kind: dict[str, int] = {}
        self.api_retries_by_stage: dict[str, int] = {}
        self.api_give_ups_by_stage: dict[str, int] = {}
        # Budget leg.
        self.exhaustions: list[BudgetExhaustion] = []
        self.exhaustions_dropped = 0
        # Host leg.
        self.host = HostStats()
        self._monitor: HostResourceMonitor | None = None
        self._first_sample: HostSample | None = None
        self._prev_sample: HostSample | None = None
        self._incident_events = 0
        self.incidents_unlogged = 0

    # -- wiring ------------------------------------------------------------- #

    def attach_journal(self, journal: Any) -> None:
        """Mirror future notes as journal events (the journal sanitizes them)."""
        with self._lock:
            self._journal = journal

    def _emit(self, code: str, *, stage: str, level: str, **fields: Any) -> None:
        journal = self._journal
        if journal is None:
            return
        try:
            journal.emit(code, stage=stage, level=level, **fields)
        except Exception:  # noqa: BLE001 - the journal's own emit never raises either
            pass

    def start_host_monitor(
        self,
        paths: dict[str, Any] | None = None,
        *,
        interval: float | None = None,
        probe: HostProbe | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> HostResourceMonitor | None:
        """Start sampling the host; returns the monitor, or ``None`` when disabled.

        ``interval`` defaults to :func:`resolve_sample_interval` (the env var);
        ``probe`` and ``clock`` are injectable for tests.
        """
        try:
            with self._lock:
                if self._monitor is not None:
                    return self._monitor
                resolved = resolve_sample_interval() if interval is None else float(interval)
                if resolved is None or resolved <= 0:
                    self.host.monitored = False
                    self.host.disabled_reason = f"disabled via {ENV_SAMPLE_SECONDS}"
                    return None
                probe = probe or HostProbe(paths)
                self.host.monitored = True
                self.host.interval_seconds = resolved
                self.host.cpu_count = int(getattr(probe, "cpu_count", 0) or os.cpu_count() or 1)
                monitor = HostResourceMonitor(self, interval=resolved, probe=probe, clock=clock)
                self._monitor = monitor
            monitor.start()
            return monitor
        except Exception as exc:  # noqa: BLE001 - advisory, never fatal
            _log.debug("host resource monitor could not start: %s", exc)
            with self._lock:
                self.host.monitored = False
                self.host.disabled_reason = f"monitor failed to start ({type(exc).__name__})"
                self._monitor = None
            return None

    def stop_host_monitor(self) -> None:
        with self._lock:
            monitor = self._monitor
            self._monitor = None
        if monitor is not None:
            try:
                monitor.stop()
            except Exception:  # noqa: BLE001
                pass

    def finish(self) -> None:
        """Stop sampling and journal the verdict (idempotent; the last call wins)."""
        try:
            self.stop_host_monitor()
            with self._lock:
                self.finished_at = self._clock()
                status = self.starvation_status
                signals = self.signals()
            self._emit(
                "RESOURCE_SUMMARY", stage="resources",
                level="WARNING" if status == STARVATION_DETECTED else "INFO",
                status=status,
                signals=",".join(s["kind"] for s in signals) or "none",
                api_retries=self.api_retries, api_give_ups=self.api_give_ups,
                backoff_s=round(self.api_backoff_seconds, 1),
                host_samples=self.host.samples, late_ticks=self.host.late_ticks,
                worst_lag_s=round(self.host.worst_lag_seconds, 2),
                peak_rss=_fmt_bytes(self.host.peak_rss_bytes),
                budget_exhaustions=sum(e.count for e in self.exhaustions),
            )
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """Safety net for the decorator: stop the sampler without a summary."""
        self.stop_host_monitor()

    # -- notes -------------------------------------------------------------- #

    def note_api_retry(
        self, exc: BaseException, *, stage: str, attempt: int, backoff_seconds: float,
    ) -> ApiRetryEvent | None:
        """Record one transient failure the caller is about to wait out."""
        return self._note_api(exc, stage=stage, attempt=attempt,
                              backoff_seconds=backoff_seconds, gave_up=False)

    def note_api_give_up(
        self, exc: BaseException, *, stage: str, attempts: int,
    ) -> ApiRetryEvent | None:
        """Record a transient failure whose retries are spent (the call failed)."""
        return self._note_api(exc, stage=stage, attempt=attempts,
                              backoff_seconds=0.0, gave_up=True)

    def _note_api(self, exc, *, stage, attempt, backoff_seconds, gave_up) -> ApiRetryEvent | None:
        try:
            kind = classify_transient(exc)
            try:
                status = status_of(exc)
            except Exception:  # noqa: BLE001
                status = None
            try:
                rid = request_id_of(exc) or ""
            except Exception:  # noqa: BLE001
                rid = ""
            event = ApiRetryEvent(
                stage=str(stage)[:40] or "?",
                kind=kind,
                status=status,
                attempt=int(attempt),
                backoff_seconds=float(backoff_seconds or 0.0),
                retry_after_seconds=retry_after_seconds(exc),
                request_id=rid,
                rate_limit=rate_limit_snapshot(exc),
                gave_up=bool(gave_up),
                at=_iso(self._clock()),
            )
            with self._lock:
                if gave_up:
                    self.api_give_ups += 1
                    self.api_give_ups_by_stage[event.stage] = (
                        self.api_give_ups_by_stage.get(event.stage, 0) + 1
                    )
                else:
                    self.api_retries += 1
                    self.api_backoff_seconds += event.backoff_seconds
                    self.api_retries_by_stage[event.stage] = (
                        self.api_retries_by_stage.get(event.stage, 0) + 1
                    )
                self.api_by_kind[kind] = self.api_by_kind.get(kind, 0) + 1
                if event.retry_after_seconds is not None:
                    self.api_retry_after_max = max(
                        self.api_retry_after_max or 0.0, event.retry_after_seconds
                    )
                stored = len(self.api_events) < MAX_STORED_API_EVENTS
                if stored:
                    self.api_events.append(event)
                else:
                    self.api_events_dropped += 1
            # Journal only the events that were stored, so run.log and the
            # manifest list the same bounded set; the aggregates count all.
            if stored:
                fields: dict[str, Any] = {
                    "kind": kind, "status": status if status is not None else "-",
                    "attempt": event.attempt,
                }
                if gave_up:
                    fields["gave_up"] = True
                else:
                    fields["backoff_s"] = round(event.backoff_seconds, 1)
                if event.retry_after_seconds is not None:
                    fields["retry_after_s"] = round(event.retry_after_seconds, 1)
                if event.rate_limit:
                    fields["remaining"] = ",".join(
                        f"{k}={v}" for k, v in sorted(event.rate_limit.items())
                    )
                if rid:
                    fields["request_id"] = rid
                self._emit(
                    "API_GIVE_UP" if gave_up else "API_RETRY",
                    stage=event.stage, level="WARNING", **fields,
                )
            return event
        except Exception:  # noqa: BLE001 - never fail the retry loop that called us
            return None

    def note_budget_exhausted(
        self, stage: str, kind: str, *, count: int = 1, detail: str = "",
    ) -> BudgetExhaustion | None:
        """Record an allotment an agent ran out of (a zero count records nothing)."""
        try:
            count = int(count)
            if count <= 0:
                return None
            item = BudgetExhaustion(
                stage=str(stage)[:40] or "?", kind=str(kind)[:40] or "?",
                count=count, detail=str(detail)[:200],
            )
            with self._lock:
                if len(self.exhaustions) < MAX_STORED_EXHAUSTIONS:
                    self.exhaustions.append(item)
                else:
                    self.exhaustions_dropped += 1
                    return None
            fields: dict[str, Any] = {"kind": item.kind, "count": item.count}
            if item.detail:
                fields["detail"] = item.detail
            self._emit("BUDGET_EXHAUSTED", stage=item.stage, level="WARNING", **fields)
            return item
        except Exception:  # noqa: BLE001
            return None

    # -- host samples ------------------------------------------------------- #

    def _ingest_host_sample(self, sample: HostSample, *, lag_seconds: float) -> None:
        """Fold one probe reading into the aggregates; journal threshold breaches."""
        incidents: list[tuple[str, dict[str, Any]]] = []
        with self._lock:
            h = self.host
            h.samples += 1
            h.unavailable.update(sample.unavailable)
            h.threads_max = max(h.threads_max, int(sample.threads or 0))
            if sample.peak_rss_bytes is not None:
                h.peak_rss_bytes = max(h.peak_rss_bytes or 0, sample.peak_rss_bytes)
            if sample.rss_bytes is not None:
                h.rss_max_bytes = max(h.rss_max_bytes or 0, sample.rss_bytes)
                # The peak is at least the largest current reading we saw.
                h.peak_rss_bytes = max(h.peak_rss_bytes or 0, sample.rss_bytes)
            if sample.load_1m is not None:
                h.load_1m_max = max(h.load_1m_max or 0.0, sample.load_1m)
            for label, total in sample.disk_total.items():
                h.disk_total[label] = int(total)
            for label, free in sample.disk_free.items():
                prev = h.disk_free_min.get(label)
                h.disk_free_min[label] = int(free) if prev is None else min(prev, int(free))
                if free < LOW_DISK_BYTES:
                    h.low_disk_samples += 1
                    incidents.append((SIGNAL_LOW_DISK, {"location": label, "free": _fmt_bytes(int(free))}))
            if sample.system_memory_total and sample.system_memory_available is not None:
                total = int(sample.system_memory_total)
                avail = int(sample.system_memory_available)
                h.system_memory_total = total
                h.system_memory_available_min = (
                    avail if h.system_memory_available_min is None
                    else min(h.system_memory_available_min, avail)
                )
                load = 100.0 * (1.0 - avail / total) if total > 0 else 0.0
                h.system_memory_load_max_pct = max(h.system_memory_load_max_pct or 0.0, load)
                if load >= MEMORY_LOAD_PCT_FOR_SIGNAL or avail < MEMORY_AVAILABLE_BYTES_FOR_SIGNAL:
                    h.memory_pressure_samples += 1
                    incidents.append((SIGNAL_MEMORY_PRESSURE, {
                        "load_pct": round(load, 1), "available": _fmt_bytes(avail),
                    }))
            if self._first_sample is None:
                self._first_sample = sample
            else:
                first = self._first_sample
                h.wall_seconds = max(0.0, sample.wall - first.wall)
                if sample.process_cpu_seconds is not None and first.process_cpu_seconds is not None:
                    h.process_cpu_seconds = max(0.0, sample.process_cpu_seconds - first.process_cpu_seconds)
                prev = self._prev_sample
                if prev is not None:
                    d_wall = sample.wall - prev.wall
                    if d_wall > 0:
                        if sample.process_cpu_seconds is not None and prev.process_cpu_seconds is not None:
                            ratio = max(0.0, sample.process_cpu_seconds - prev.process_cpu_seconds) / d_wall
                            h.process_cpu_peak_ratio = max(h.process_cpu_peak_ratio, ratio)
                        if sample.system_cpu_times is not None and prev.system_cpu_times is not None:
                            d_idle = sample.system_cpu_times[0] - prev.system_cpu_times[0]
                            d_total = sample.system_cpu_times[1] - prev.system_cpu_times[1]
                            if d_total > 0:
                                busy = 100.0 * max(0.0, min(1.0, 1.0 - d_idle / d_total))
                                h.system_cpu_busy_max_pct = max(h.system_cpu_busy_max_pct or 0.0, busy)
                                h.system_cpu_busy_sum_pct += busy
                                h.system_cpu_busy_samples += 1
                # Scheduling lag is judged only on timed ticks (never the first
                # or the final sample, which carry lag 0 by construction).
                if lag_seconds > 0:
                    threshold = max(MIN_LAG_SECONDS, LAG_FRACTION_OF_INTERVAL * h.interval_seconds)
                    h.total_lag_seconds += lag_seconds
                    h.worst_lag_seconds = max(h.worst_lag_seconds, lag_seconds)
                    if lag_seconds >= threshold:
                        h.late_ticks += 1
                        incidents.append((SIGNAL_CPU_STARVED, {"lag_s": round(lag_seconds, 2)}))
            self._prev_sample = sample
            to_log: list[tuple[str, dict[str, Any]]] = []
            for incident in incidents:
                if self._incident_events < MAX_INCIDENT_EVENTS:
                    self._incident_events += 1
                    to_log.append(incident)
                else:
                    self.incidents_unlogged += 1
        for kind, fields in to_log:
            self._emit("RESOURCE_PRESSURE", stage="host", level="WARNING", kind=kind, **fields)

    # -- verdict ------------------------------------------------------------ #

    @property
    def api_throttle_retries(self) -> int:
        """Retries answered by a *capacity* status (429 / 529 / 503)."""
        return sum(self.api_by_kind.get(k, 0) for k in THROTTLE_KINDS)

    def signals(self) -> list[dict[str, Any]]:
        """The named starvation signals this run's evidence supports (ordered)."""
        out: list[dict[str, Any]] = []
        with self._lock:
            throttled = self.api_throttle_retries
            if (
                self.api_give_ups
                or throttled >= API_THROTTLE_RETRIES_FOR_SIGNAL
                or self.api_backoff_seconds >= API_BACKOFF_SECONDS_FOR_SIGNAL
            ):
                bits = [f"{self.api_retries} transient {_plural(self.api_retries, 'retry', 'retries')}"]
                if throttled:
                    # Counts retries AND give-ups answered 429/529/503, so it
                    # can exceed the retry count by the give-ups.
                    bits.append(
                        f"{throttled} capacity {_plural(throttled, 'answer')} (429/529/503)"
                    )
                if self.api_give_ups:
                    bits.append(f"{self.api_give_ups} {_plural(self.api_give_ups, 'give-up')}")
                bits.append(f"{self.api_backoff_seconds:.0f}s in backoff")
                if self.api_retry_after_max is not None:
                    bits.append(f"worst retry-after {self.api_retry_after_max:.0f}s")
                stages = sorted(set(self.api_retries_by_stage) | set(self.api_give_ups_by_stage))
                out.append({
                    "kind": SIGNAL_API_THROTTLED, "evidence": ", ".join(bits), "stages": stages,
                })
            h = self.host
            if h.late_ticks >= LATE_TICKS_FOR_SIGNAL or h.worst_lag_seconds >= SEVERE_LAG_SECONDS:
                evidence = (
                    f"{h.late_ticks} late {_plural(h.late_ticks, 'tick')} of {h.samples} "
                    f"(worst lag {h.worst_lag_seconds:.1f}s, total {h.total_lag_seconds:.1f}s)"
                )
                if h.system_cpu_busy_max_pct is not None:
                    evidence += f", system CPU peaked at {h.system_cpu_busy_max_pct:.0f}%"
                out.append({"kind": SIGNAL_CPU_STARVED, "evidence": evidence, "stages": ["host"]})
            if h.memory_pressure_samples:
                evidence = (
                    f"{h.memory_pressure_samples} {_plural(h.memory_pressure_samples, 'sample')} "
                    f"at or above {MEMORY_LOAD_PCT_FOR_SIGNAL:.0f}% load or under "
                    f"{_fmt_bytes(MEMORY_AVAILABLE_BYTES_FOR_SIGNAL)} available "
                    f"(peak load {h.system_memory_load_max_pct or 0:.0f}%, "
                    f"min available {_fmt_bytes(h.system_memory_available_min)}, "
                    f"this process peaked at {_fmt_bytes(h.peak_rss_bytes)})"
                )
                out.append({"kind": SIGNAL_MEMORY_PRESSURE, "evidence": evidence, "stages": ["host"]})
            if h.low_disk_samples:
                low = {
                    label: free for label, free in h.disk_free_min.items() if free < LOW_DISK_BYTES
                }
                evidence = ", ".join(
                    f"{label} down to {_fmt_bytes(free)}" for label, free in sorted(low.items())
                ) or f"{h.low_disk_samples} low-disk sample(s)"
                out.append({"kind": SIGNAL_LOW_DISK, "evidence": evidence, "stages": ["host"]})
            if self.exhaustions:
                by_key: dict[tuple[str, str], int] = {}
                for e in self.exhaustions:
                    by_key[(e.stage, e.kind)] = by_key.get((e.stage, e.kind), 0) + e.count
                evidence = ", ".join(
                    f"{stage}: {kind} x{count}" for (stage, kind), count in sorted(by_key.items())
                )
                out.append({
                    "kind": SIGNAL_BUDGET_EXHAUSTED, "evidence": evidence,
                    "stages": sorted({e.stage for e in self.exhaustions}),
                })
        return out

    @property
    def starvation_status(self) -> str:
        return STARVATION_DETECTED if self.signals() else STARVATION_NOT_DETECTED

    # -- rendering ---------------------------------------------------------- #

    def summary_line(self) -> str:
        """One line for the GUI / report: the verdict and what fired it (or didn't)."""
        signals = self.signals()
        if signals:
            return STARVATION_DETECTED + " — " + "; ".join(
                f"{s['kind']} ({s['evidence']})" for s in signals
            )
        h = self.host
        bits = [f"{self.api_retries} transient API {_plural(self.api_retries, 'retry', 'retries')}"]
        if h.monitored:
            host_bits = [f"host sampled {h.samples}x @{h.interval_seconds:g}s"]
            if h.samples > 1:
                host_bits.append(f"worst lag {h.worst_lag_seconds:.1f}s")
            if h.peak_rss_bytes is not None:
                host_bits.append(f"peak RSS {_fmt_bytes(h.peak_rss_bytes)}")
            bits.append(", ".join(host_bits))
        else:
            bits.append(f"host not sampled ({h.disabled_reason or 'not started'})")
        bits.append("no budget exhaustion")
        return STARVATION_NOT_DETECTED + " — " + " · ".join(bits)

    def render_lines(self) -> list[str]:
        """The run.log *Resource pressure* section body (two-space indented)."""
        lines = [f"  starvation: {self.summary_line()}"]
        kinds = ", ".join(f"{k} {v}" for k, v in sorted(self.api_by_kind.items()))
        api = [
            f"{self.api_retries} transient {_plural(self.api_retries, 'retry', 'retries')}"
            + (f" ({kinds})" if kinds else ""),
            f"{self.api_give_ups} {_plural(self.api_give_ups, 'give-up')}",
            f"{self.api_backoff_seconds:.1f}s in backoff",
        ]
        if self.api_retry_after_max is not None:
            api.append(f"worst retry-after {self.api_retry_after_max:.0f}s")
        stages = {**self.api_retries_by_stage}
        for stage, n in self.api_give_ups_by_stage.items():
            stages[stage] = stages.get(stage, 0) + n
        if stages:
            api.append("by stage: " + ", ".join(f"{s} {n}" for s, n in sorted(stages.items())))
        if self.api_events_dropped:
            api.append(f"{self.api_events_dropped} more not listed")
        lines.append("  api: " + " · ".join(api))
        h = self.host
        if not h.monitored:
            lines.append(f"  host: not sampled ({h.disabled_reason or 'monitor not started'})")
        else:
            host = [
                f"{h.samples} {_plural(h.samples, 'sample')} @{h.interval_seconds:g}s",
                f"late ticks {h.late_ticks} (worst lag {h.worst_lag_seconds:.1f}s)",
            ]
            if h.wall_seconds > 0:
                host.append(
                    f"process CPU {100 * h.process_cpu_mean_ratio:.0f}% of one core on average, "
                    f"peak {100 * h.process_cpu_peak_ratio:.0f}%, {h.cpu_count} cores"
                )
            host.append(f"peak RSS {_fmt_bytes(h.peak_rss_bytes)}")
            if h.system_memory_load_max_pct is not None:
                host.append(
                    f"system memory load peak {h.system_memory_load_max_pct:.0f}% "
                    f"(min available {_fmt_bytes(h.system_memory_available_min)} "
                    f"of {_fmt_bytes(h.system_memory_total)})"
                )
            if h.system_cpu_busy_max_pct is not None:
                host.append(f"system CPU busy peak {h.system_cpu_busy_max_pct:.0f}%")
            if h.load_1m_max is not None:
                host.append(f"load average peak {h.load_1m_max:.2f}")
            if h.disk_free_min:
                host.append("min free disk " + ", ".join(
                    f"{label} {_fmt_bytes(free)}" for label, free in sorted(h.disk_free_min.items())
                ))
            host.append(f"threads peak {h.threads_max}")
            if h.unavailable:
                host.append("unavailable: " + ", ".join(sorted(h.unavailable)))
            if self.incidents_unlogged:
                host.append(f"{self.incidents_unlogged} further incidents not journaled")
            lines.append("  host: " + " · ".join(host))
        if self.exhaustions:
            budget = ", ".join(
                f"{e.stage} {e.kind} x{e.count}" + (f" ({e.detail})" if e.detail else "")
                for e in self.exhaustions
            )
            if self.exhaustions_dropped:
                budget += f", +{self.exhaustions_dropped} more"
            lines.append("  budget: " + budget)
        else:
            lines.append("  budget: no agent exhausted its output cap, evidence rounds, "
                         "reference cap or batch time bound")
        return lines

    def to_dict(self) -> dict:
        """JSON-ready record for ``run_manifest.json`` (labels and counts only)."""
        with self._lock:
            signals = self.signals()
            return {
                "starvation_status": STARVATION_DETECTED if signals else STARVATION_NOT_DETECTED,
                "signals": signals,
                "summary": self.summary_line(),
                "started_at": _iso(self.started_at),
                "finished_at": _iso(self.finished_at) if self.finished_at else None,
                "api": {
                    "retries": self.api_retries,
                    "give_ups": self.api_give_ups,
                    "throttle_retries": self.api_throttle_retries,
                    "backoff_seconds": round(self.api_backoff_seconds, 3),
                    "retry_after_max_seconds": (
                        None if self.api_retry_after_max is None
                        else round(self.api_retry_after_max, 3)
                    ),
                    "by_kind": dict(sorted(self.api_by_kind.items())),
                    "retries_by_stage": dict(sorted(self.api_retries_by_stage.items())),
                    "give_ups_by_stage": dict(sorted(self.api_give_ups_by_stage.items())),
                    "events": [e.to_dict() for e in self.api_events],
                    "events_dropped": self.api_events_dropped,
                },
                "host": self.host.to_dict(),
                "budget": {
                    "exhaustions": [e.to_dict() for e in self.exhaustions],
                    "dropped": self.exhaustions_dropped,
                },
                "thresholds": {
                    "api_throttle_retries": API_THROTTLE_RETRIES_FOR_SIGNAL,
                    "api_backoff_seconds": API_BACKOFF_SECONDS_FOR_SIGNAL,
                    "late_ticks": LATE_TICKS_FOR_SIGNAL,
                    "severe_lag_seconds": SEVERE_LAG_SECONDS,
                    "memory_load_pct": MEMORY_LOAD_PCT_FOR_SIGNAL,
                    "memory_available_bytes": MEMORY_AVAILABLE_BYTES_FOR_SIGNAL,
                    "low_disk_bytes": LOW_DISK_BYTES,
                },
            }


# --------------------------------------------------------------------------- #
# The active recorder: thread-bound, with a live registry as the fallback.
#
# A single process-wide value would let two concurrent runs (library callers;
# the pipeline keeps per-run executor state to allow them) attribute each
# other's retries, and finishing out of order would clear the live run's
# recorder or restore a finished one. So the binding is per thread: the run's
# own thread is bound by ``tracked_run``, and every pool the run opens binds
# its workers through ``worker_binding``. A thread bound to no run resolves to
# the one live recorder only when exactly one run is live — never a guess.
# --------------------------------------------------------------------------- #

_binding = threading.local()
_live_lock = threading.Lock()
_live: list[ResourcePressure] = []


def current() -> ResourcePressure | None:
    """The recorder for the calling thread's run, or ``None``.

    The thread's own binding wins; an unbound thread gets the single live
    recorder when exactly one run is live, else ``None`` (no attribution
    rather than a wrong one).
    """
    bound = getattr(_binding, "pressure", None)
    if bound is not None:
        return bound
    with _live_lock:
        return _live[0] if len(_live) == 1 else None


def bind_thread(pressure: ResourcePressure | None) -> ResourcePressure | None:
    """Bind the calling thread to ``pressure``; returns its previous binding."""
    previous = getattr(_binding, "pressure", None)
    _binding.pressure = pressure
    return previous


def _bind_worker(
    pressure: ResourcePressure | None, token: "cancellation.CancelToken | None",
) -> None:
    bind_thread(pressure)
    cancellation.bind_thread(token)


def worker_binding() -> dict[str, Any]:
    """``ThreadPoolExecutor`` kwargs that bind each worker to the caller's run.

    Splat into every pool a run opens: ``ThreadPoolExecutor(max_workers=n,
    **worker_binding())``. The initializer runs once per worker thread and
    gives it the recorder the creating thread resolves to *now*, so retries
    on those workers land on their own run even when another run is live.
    It binds the run's kill switch (:mod:`~drawing_analyzer.cancellation`)
    the same way, so a stop reaches that run's workers and no one else's.
    """
    return {
        "initializer": _bind_worker,
        "initargs": (current(), cancellation.current()),
    }


def activate(pressure: ResourcePressure) -> ResourcePressure | None:
    """Register ``pressure`` as live and bind this thread to it.

    Returns the thread's previous binding, to hand back to :func:`deactivate`.
    """
    with _live_lock:
        _live.append(pressure)
    return bind_thread(pressure)


def deactivate(pressure: ResourcePressure, previous: ResourcePressure | None = None) -> None:
    """Retire ``pressure`` from the live set and restore this thread's binding."""
    with _live_lock:
        try:
            _live.remove(pressure)
        except ValueError:
            pass
    bind_thread(previous)


def tracked_run(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: run ``fn`` with a fresh :class:`ResourcePressure` bound to it.

    The pipeline's entry point wears this so every retry loop on the run's
    thread and on its pools (see :func:`worker_binding`) finds the run's
    recorder through :func:`current` for exactly the duration of the call.
    The sampler is stopped on any exit — return or raise — the recorder leaves
    the live set, and the thread's previous binding (normally none) returns.
    """
    @wraps(fn)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        pressure = ResourcePressure()
        previous = activate(pressure)
        try:
            return fn(*args, **kwargs)
        finally:
            pressure.close()
            deactivate(pressure, previous)

    return _wrapped


def note_api_retry(exc: BaseException, *, stage: str, attempt: int, backoff_seconds: float) -> None:
    """Forward a transient retry to this thread's run recorder (no-op outside a run)."""
    pressure = current()
    if pressure is not None:
        pressure.note_api_retry(exc, stage=stage, attempt=attempt, backoff_seconds=backoff_seconds)


def note_api_give_up(exc: BaseException, *, stage: str, attempts: int) -> None:
    """Forward a spent transient retry loop to the active run's recorder."""
    pressure = current()
    if pressure is not None:
        pressure.note_api_give_up(exc, stage=stage, attempts=attempts)


def note_budget_exhausted(stage: str, kind: str, *, count: int = 1, detail: str = "") -> None:
    """Forward an exhausted agent allotment to the active run's recorder."""
    pressure = current()
    if pressure is not None:
        pressure.note_budget_exhausted(stage, kind, count=count, detail=detail)
