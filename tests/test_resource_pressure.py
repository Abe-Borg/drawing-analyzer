"""The per-run resource-starvation record (``resource_pressure.py``).

Covers the three legs the record is built from — the API-retry notes every
stage loop makes through ``digest.transient_retry_wait``, the host sampler's
aggregates and threshold incidents, and the agent-budget notes — plus the
verdict they derive, the bounded/JSON-ready manifest block, the run.log
section, and one hermetic pipeline run whose fake client is rate-limited.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing_analyzer import export as dx
from drawing_analyzer import resource_pressure as rp
from drawing_analyzer.digest import transient_retry_wait
from drawing_analyzer.run_journal import RunJournal, render_run_log


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


class _Headers(dict):
    """A headers map with the ``.get`` shape httpx exposes."""


def _status_error(status: int, headers: dict | None = None, name: str = "APIStatusError"):
    exc = type(name, (Exception,), {})(f"HTTP {status}")
    exc.status_code = status
    exc.request_id = f"req_{status}_x"
    exc.response = SimpleNamespace(headers=_Headers(headers or {}))
    return exc


@pytest.fixture
def active():
    """A fresh recorder, active for the test, restored afterwards."""
    pressure = rp.ResourcePressure()
    previous = rp.activate(pressure)
    try:
        yield pressure
    finally:
        pressure.close()
        rp.deactivate(previous)


def _events(journal: RunJournal, code: str) -> list:
    return [e for e in journal.events if e.event_code == code]


# --------------------------------------------------------------------------- #
# API leg — the shared retry helper
# --------------------------------------------------------------------------- #


def test_retry_helper_records_waits_and_give_ups(active):
    journal = RunJournal(run_id="RUN-rp")
    active.attach_journal(journal)
    slept: list[float] = []
    exc = _status_error(429, {
        "retry-after": "7",
        "anthropic-ratelimit-requests-remaining": "0",
        "anthropic-ratelimit-input-tokens-remaining": "1200",
    })

    # attempt 0 of max 1: wait, retry.
    assert transient_retry_wait(exc, 0, 1, slept.append, stage="digest") is True
    assert slept == [2.0]
    # attempt 1 of max 1: spent → give up (no sleep).
    assert transient_retry_wait(exc, 1, 1, slept.append, stage="digest") is False
    assert slept == [2.0]
    # A permanent error is neither waited on nor recorded.
    assert transient_retry_wait(RuntimeError("boom"), 0, 5, slept.append, stage="digest") is False
    assert slept == [2.0]

    assert active.api_retries == 1 and active.api_give_ups == 1
    assert active.api_backoff_seconds == 2.0
    assert active.api_by_kind == {rp.KIND_RATE_LIMITED: 2}
    assert active.api_retries_by_stage == {"digest": 1}
    assert active.api_give_ups_by_stage == {"digest": 1}
    assert active.api_retry_after_max == 7.0
    retry, give_up = active.api_events
    assert (retry.status, retry.attempt, retry.backoff_seconds, retry.gave_up) == (429, 1, 2.0, False)
    assert retry.rate_limit == {"requests_remaining": 0, "input_tokens_remaining": 1200}
    assert retry.request_id == "req_429_x"
    assert give_up.gave_up and give_up.attempt == 2

    (ev_retry,) = _events(journal, "API_RETRY")
    (ev_give_up,) = _events(journal, "API_GIVE_UP")
    assert ev_retry.stage == "digest" and ev_retry.fields["status"] == "429"
    assert ev_retry.fields["backoff_s"] == "2.0" and ev_retry.fields["retry_after_s"] == "7.0"
    assert "requests_remaining=0" in ev_retry.fields["remaining"]
    assert ev_give_up.fields["gave_up"] == "True"


def test_retry_helper_still_retries_with_no_active_run():
    assert rp.current() is None
    slept: list[float] = []
    assert transient_retry_wait(_status_error(503), 0, 2, slept.append, stage="upload") is True
    assert slept == [2.0]


@pytest.mark.parametrize("exc,kind", [
    (_status_error(429), rp.KIND_RATE_LIMITED),
    (_status_error(529), rp.KIND_OVERLOADED),
    (_status_error(503), rp.KIND_UNAVAILABLE),
    (_status_error(502), rp.KIND_SERVER_ERROR),
    (_status_error(408), rp.KIND_TIMEOUT),
    (type("APITimeoutError", (Exception,), {})("slow"), rp.KIND_TIMEOUT),
    (type("APIConnectionError", (Exception,), {})("down"), rp.KIND_CONNECTION),
    (RuntimeError("?"), rp.KIND_OTHER),
])
def test_classify_transient(exc, kind):
    assert rp.classify_transient(exc) == kind


@pytest.mark.parametrize("raw,expected", [
    ("12", 12.0),
    (" 0.5 ", 0.5),
    ("-3", 0.0),
    ("inf", None),
    ("soon", None),
    ("Thu, 01 Jan 2026 00:01:00 GMT", 60.0),
])
def test_retry_after_seconds(raw, expected):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exc = _status_error(429, {"retry-after": raw})
    assert rp.retry_after_seconds(exc, now=now) == expected


def test_retry_after_absent_or_headerless_is_none():
    assert rp.retry_after_seconds(_status_error(429)) is None
    assert rp.retry_after_seconds(RuntimeError("no response")) is None


def test_api_signal_thresholds():
    # Two recovered capacity retries are weather.
    p = rp.ResourcePressure()
    for _ in range(2):
        p.note_api_retry(_status_error(429), stage="digest", attempt=1, backoff_seconds=2.0)
    assert p.signals() == [] and p.starvation_status == rp.STARVATION_NOT_DETECTED
    # A third capacity answer is a verdict.
    p.note_api_retry(_status_error(529), stage="critique", attempt=1, backoff_seconds=2.0)
    (sig,) = p.signals()
    assert sig["kind"] == rp.SIGNAL_API_THROTTLED and sig["stages"] == ["critique", "digest"]
    assert "3 capacity answers" in sig["evidence"]
    # Server errors alone never reach the throttle signal...
    q = rp.ResourcePressure()
    for _ in range(5):
        q.note_api_retry(_status_error(502), stage="digest", attempt=1, backoff_seconds=2.0)
    assert q.signals() == []
    # ...until the run has spent real wall-clock waiting on them.
    q.note_api_retry(_status_error(502), stage="digest", attempt=2, backoff_seconds=20.0)
    assert [s["kind"] for s in q.signals()] == [rp.SIGNAL_API_THROTTLED]
    # One give-up is always a verdict: the API refused until the loop stopped asking.
    r = rp.ResourcePressure()
    r.note_api_give_up(_status_error(429), stage="verification", attempts=3)
    assert [s["kind"] for s in r.signals()] == [rp.SIGNAL_API_THROTTLED]
    assert "1 give-up" in r.signals()[0]["evidence"]


# --------------------------------------------------------------------------- #
# Host leg — aggregates, incidents, signals
# --------------------------------------------------------------------------- #


def _sample(wall: float, **kw) -> rp.HostSample:
    base = dict(
        process_cpu_seconds=wall * 0.5, rss_bytes=100 << 20, peak_rss_bytes=120 << 20,
        system_memory_total=16 << 30, system_memory_available=8 << 30,
        system_cpu_times=(wall * 3, wall * 4), load_1m=1.0,
        disk_free={"temp": 50 << 30}, disk_total={"temp": 100 << 30}, threads=6,
    )
    base.update(kw)
    return rp.HostSample(wall=wall, **base)


def _monitored(interval: float = 5.0) -> rp.ResourcePressure:
    p = rp.ResourcePressure()
    p.host.monitored = True
    p.host.interval_seconds = interval
    p.host.cpu_count = 4
    return p


def test_lag_incidents_and_cpu_starved_signal():
    journal = RunJournal(run_id="RUN-lag")
    p = _monitored(5.0)
    p.attach_journal(journal)
    p._ingest_host_sample(_sample(0.0), lag_seconds=0.0)
    p._ingest_host_sample(_sample(5.1), lag_seconds=0.1)       # on time
    p._ingest_host_sample(_sample(12.0), lag_seconds=2.0)      # under the 2.5s threshold (half the interval)
    assert p.host.late_ticks == 0 and p.host.worst_lag_seconds == 2.0
    p._ingest_host_sample(_sample(20.0), lag_seconds=3.0)      # late
    assert p.host.late_ticks == 1 and p.signals() == []        # one late tick: incident, not verdict
    assert len(_events(journal, "RESOURCE_PRESSURE")) == 1
    p._ingest_host_sample(_sample(29.0), lag_seconds=4.0)      # second late tick
    (sig,) = p.signals()
    assert sig["kind"] == rp.SIGNAL_CPU_STARVED
    assert "2 late ticks of 5" in sig["evidence"] and "worst lag 4.0s" in sig["evidence"]
    # Process CPU accounting runs from the first to the latest sample.
    assert p.host.wall_seconds == 29.0 and p.host.process_cpu_seconds == 14.5
    assert p.host.process_cpu_peak_ratio == pytest.approx(0.5)
    assert p.host.system_cpu_busy_max_pct == pytest.approx(25.0)


def test_one_severe_lag_is_a_verdict_on_its_own():
    p = _monitored(5.0)
    p._ingest_host_sample(_sample(0.0), lag_seconds=0.0)
    p._ingest_host_sample(_sample(20.0), lag_seconds=rp.SEVERE_LAG_SECONDS)
    assert [s["kind"] for s in p.signals()] == [rp.SIGNAL_CPU_STARVED]


def test_memory_and_disk_signals_report_labels_never_paths():
    journal = RunJournal(run_id="RUN-mem")
    p = _monitored()
    p.attach_journal(journal)
    p._ingest_host_sample(_sample(0.0), lag_seconds=0.0)
    p._ingest_host_sample(
        _sample(5.0, system_memory_available=1 << 30,
                disk_free={"temp": 50 << 30, "work_dir": 300 << 20}),
        lag_seconds=0.0,
    )
    kinds = {s["kind"]: s for s in p.signals()}
    assert set(kinds) == {rp.SIGNAL_MEMORY_PRESSURE, rp.SIGNAL_LOW_DISK}
    assert "peak load 94%" in kinds[rp.SIGNAL_MEMORY_PRESSURE]["evidence"]
    assert kinds[rp.SIGNAL_LOW_DISK]["evidence"] == "work_dir down to 300.0 MB"
    assert p.host.disk_free_min == {"temp": 50 << 30, "work_dir": 300 << 20}
    assert p.host.system_memory_available_min == 1 << 30
    incidents = _events(journal, "RESOURCE_PRESSURE")
    assert {e.fields["kind"] for e in incidents} == {rp.SIGNAL_MEMORY_PRESSURE, rp.SIGNAL_LOW_DISK}
    assert "/" not in json.dumps(p.to_dict()["host"]["disk_free_min_bytes"])


def test_incident_events_are_bounded_but_counted():
    p = _monitored()
    journal = RunJournal(run_id="RUN-bound")
    p.attach_journal(journal)
    p._ingest_host_sample(_sample(0.0), lag_seconds=0.0)
    for i in range(rp.MAX_INCIDENT_EVENTS + 10):
        p._ingest_host_sample(_sample(5.0 * (i + 1), disk_free={"temp": 1}), lag_seconds=0.0)
    assert len(_events(journal, "RESOURCE_PRESSURE")) == rp.MAX_INCIDENT_EVENTS
    assert p.incidents_unlogged == 10
    assert p.host.low_disk_samples == rp.MAX_INCIDENT_EVENTS + 10


class _ScriptedProbe:
    """A probe whose samples are fed by the test (and may blow up on demand)."""

    cpu_count = 4

    def __init__(self, *, fail: bool = False):
        self.calls = 0
        self.fail = fail

    def sample(self) -> rp.HostSample:
        self.calls += 1
        if self.fail:
            raise OSError("no /proc here")
        return _sample(float(self.calls))


def test_monitor_samples_on_a_thread_and_stops_promptly():
    p = rp.ResourcePressure()
    journal = RunJournal(run_id="RUN-mon")
    p.attach_journal(journal)
    probe = _ScriptedProbe()
    monitor = p.start_host_monitor(interval=0.02, probe=probe)
    assert monitor is not None and p.host.monitored and p.host.interval_seconds == 0.02
    deadline = time.monotonic() + 5.0
    while probe.calls < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    t0 = time.monotonic()
    p.finish()
    assert time.monotonic() - t0 < 2.0
    assert not monitor.running
    assert p.host.samples == probe.calls >= 3          # initial + ticks + final
    assert p.finished_at is not None
    (summary,) = _events(journal, "RESOURCE_SUMMARY")
    assert summary.fields["status"] == rp.STARVATION_NOT_DETECTED
    assert summary.fields["host_samples"] == str(p.host.samples)
    # finish() is idempotent and start after finish is a no-op on the aggregates.
    p.finish()
    assert len(_events(journal, "RESOURCE_SUMMARY")) == 2


def test_monitor_that_cannot_sample_degrades_to_not_monitored():
    p = rp.ResourcePressure()
    assert p.start_host_monitor(interval=0.02, probe=_ScriptedProbe(fail=True)) is None
    assert p.host.monitored is False and "OSError" in p.host.disabled_reason
    p.finish()                                                   # still never raises
    assert "host not sampled" in p.summary_line()


def test_disabled_interval_skips_the_sampler_but_keeps_the_api_leg(monkeypatch):
    monkeypatch.setenv(rp.ENV_SAMPLE_SECONDS, "0")
    p = rp.ResourcePressure()
    assert p.start_host_monitor({"temp": "."}) is None
    assert p.host.monitored is False and rp.ENV_SAMPLE_SECONDS in p.host.disabled_reason
    p.note_api_give_up(_status_error(429), stage="digest", attempts=3)
    assert p.starvation_status == rp.STARVATION_DETECTED


@pytest.mark.parametrize("raw,expected", [
    (None, rp.DEFAULT_SAMPLE_SECONDS),
    ("0", None), ("off", None), ("false", None), ("", None), ("-3", None), ("inf", None),
    ("abc", rp.DEFAULT_SAMPLE_SECONDS),
    ("0.2", rp.MIN_SAMPLE_SECONDS),
    ("900", rp.MAX_SAMPLE_SECONDS),
    ("12", 12.0),
])
def test_resolve_sample_interval(raw, expected, monkeypatch):
    monkeypatch.delenv(rp.ENV_SAMPLE_SECONDS, raising=False)
    assert rp.resolve_sample_interval(raw) == expected


def test_real_probe_never_raises_and_names_what_it_cannot_read(tmp_path):
    probe = rp.HostProbe({"temp": tmp_path, "gone": tmp_path / "missing", "blank": ""})
    sample = probe.sample()
    assert set(sample.disk_free) == {"temp"} and sample.disk_free["temp"] > 0
    assert "disk:gone" in sample.unavailable and "disk:blank" not in sample.unavailable
    assert sample.threads >= 1 and sample.process_cpu_seconds is not None
    # An unsupported platform reads nothing system-wide and says so.
    other = rp.HostProbe({}, platform="plan9").sample()
    assert {"system_memory", "system_cpu", "process_rss"} <= set(other.unavailable)
    assert other.system_memory_total is None and other.system_cpu_times is None


# --------------------------------------------------------------------------- #
# Budget leg
# --------------------------------------------------------------------------- #


def test_budget_notes_ignore_zero_counts_and_fire_the_signal():
    journal = RunJournal(run_id="RUN-budget")
    p = rp.ResourcePressure()
    p.attach_journal(journal)
    assert p.note_budget_exhausted("verification", "output_cap", count=0) is None
    assert p.signals() == [] and not _events(journal, "BUDGET_EXHAUSTED")
    p.note_budget_exhausted("verification", "output_cap", count=2, detail="cut off")
    p.note_budget_exhausted("investigation", "evidence_rounds", count=1)
    (sig,) = p.signals()
    assert sig["kind"] == rp.SIGNAL_BUDGET_EXHAUSTED
    assert sig["evidence"] == "investigation: evidence_rounds x1, verification: output_cap x2"
    assert sig["stages"] == ["investigation", "verification"]
    assert [e.fields["count"] for e in _events(journal, "BUDGET_EXHAUSTED")] == ["2", "1"]


# --------------------------------------------------------------------------- #
# Serialization, bounds, rendering
# --------------------------------------------------------------------------- #


def test_to_dict_is_json_ready_and_bounded():
    p = rp.ResourcePressure()
    journal = RunJournal(run_id="RUN-json")
    p.attach_journal(journal)
    for i in range(rp.MAX_STORED_API_EVENTS + 25):
        p.note_api_retry(_status_error(429), stage="digest", attempt=1, backoff_seconds=2.0)
    d = json.loads(json.dumps(p.to_dict()))
    assert d["api"]["retries"] == rp.MAX_STORED_API_EVENTS + 25
    assert len(d["api"]["events"]) == rp.MAX_STORED_API_EVENTS
    assert d["api"]["events_dropped"] == 25
    assert len(_events(journal, "API_RETRY")) == rp.MAX_STORED_API_EVENTS
    assert d["starvation_status"] == rp.STARVATION_DETECTED
    assert d["signals"][0]["kind"] == rp.SIGNAL_API_THROTTLED
    assert d["thresholds"]["low_disk_bytes"] == rp.LOW_DISK_BYTES
    assert d["host"]["monitored"] is False


def test_concurrent_notes_are_all_counted():
    p = rp.ResourcePressure()

    def worker():
        for _ in range(50):
            p.note_api_retry(_status_error(529), stage="digest", attempt=1, backoff_seconds=1.0)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert p.api_retries == 400 and p.api_backoff_seconds == 400.0
    assert len(p.api_events) == rp.MAX_STORED_API_EVENTS and p.api_events_dropped == 200


class _Ctx:
    qc_status = "NOT_REQUESTED"
    coverage_status = "NOT_REQUESTED"
    sheet_count = 1
    errors: list = []
    sheets: list = []


def test_run_log_renders_the_record_or_an_honest_absence():
    ctx = _Ctx()
    assert "starvation was not assessed" in render_run_log(ctx)
    assert "Starvation:" not in render_run_log(ctx)

    ctx.resource_pressure = rp.ResourcePressure()
    ctx.resource_pressure.note_api_give_up(_status_error(429), stage="digest", attempts=3)
    text = render_run_log(ctx)
    assert "Starvation:  DETECTED" in text
    assert "Resource pressure (starvation check)" in text
    assert "starvation: DETECTED — API_THROTTLED" in text
    assert "by stage: digest 1" in text


def test_manifest_carries_the_record_block():
    ctx = SimpleNamespace(resource_pressure=rp.ResourcePressure())
    ctx.resource_pressure.note_budget_exhausted("citation", "reference_cap", count=4)
    block = dx.build_run_manifest(ctx)["resource_pressure"]
    assert block["starvation_status"] == rp.STARVATION_DETECTED
    assert block["budget"]["exhaustions"] == [
        {"stage": "citation", "kind": "reference_cap", "count": 4, "detail": ""}
    ]
    assert dx.build_run_manifest(SimpleNamespace())["resource_pressure"] is None


def test_tracked_run_scopes_the_active_recorder_and_stops_its_sampler():
    seen: dict = {}

    @rp.tracked_run
    def body(fail: bool = False):
        pressure = rp.current()
        seen["pressure"] = pressure
        seen["monitor"] = pressure.start_host_monitor(interval=0.02, probe=_ScriptedProbe())
        if fail:
            raise RuntimeError("boom")
        return "done"

    assert rp.current() is None
    assert body() == "done"
    assert rp.current() is None and not seen["monitor"].running
    with pytest.raises(RuntimeError):
        body(fail=True)
    assert rp.current() is None and not seen["monitor"].running


# --------------------------------------------------------------------------- #
# Pipeline: a rate-limited fake client leaves its mark in the run record
# --------------------------------------------------------------------------- #


def _make_pdf(path: Path) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "VAV-3 SERVES ROOM 120")
    page.insert_text((650, 560), "M-101")
    doc.save(str(path))
    doc.close()
    return path


def _flaky_client(fail_first: int, *, status: int = 429):
    """A digest-only fake whose first ``fail_first`` calls are rate limited."""
    from tests.fixtures.fake_anthropic import (
        BetaClientMixin, FakeMessage, FakeTextBlock, FakeUsage, StreamingMessagesMixin,
    )

    class _Msgs(StreamingMessagesMixin):
        calls = 0

        def create(self, **kw):
            type(self).calls += 1
            if type(self).calls <= fail_first:
                raise _status_error(status, {"retry-after": "1"})
            return FakeMessage(
                content=[FakeTextBlock(text="Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120.")],
                usage=FakeUsage(input_tokens=500, output_tokens=80),
            )

    class _Client(BetaClientMixin):
        def __init__(self):
            self.messages = _Msgs()

    return _Client()


@pytest.mark.parametrize("fail_first,expected_status", [
    (1, rp.STARVATION_NOT_DETECTED),     # one recovered retry: weather
    (99, rp.STARVATION_DETECTED),        # never recovers: give-up → throttled
])
def test_pipeline_records_rate_limiting_in_the_run_record(tmp_path, monkeypatch, fail_first, expected_status):
    from drawing_analyzer import digest
    from drawing_analyzer.pipeline import extract_drawing_context

    monkeypatch.setattr(digest, "_retry_backoff_seconds", lambda attempt: 0.0)
    src = _make_pdf(tmp_path / "M-101.pdf")
    ctx = extract_drawing_context([src], client=_flaky_client(fail_first), rows=1, cols=1)

    pressure = ctx.resource_pressure
    assert pressure is not None and pressure.finished_at is not None
    assert rp.current() is None                                    # scoped to the call
    assert pressure.starvation_status == expected_status
    if fail_first == 1:
        assert pressure.api_retries == 1 and pressure.api_give_ups == 0
        assert ctx.ok_sheet_count == 1
    else:
        assert pressure.api_retries == digest.DEFAULT_DIGEST_MAX_RETRIES
        assert pressure.api_give_ups == 1
        assert ctx.ok_sheet_count == 0 and any("rate limited" in e for e in ctx.errors)
        assert [s["kind"] for s in pressure.signals()] == [rp.SIGNAL_API_THROTTLED]
    assert pressure.api_retries_by_stage.get("digest", 0) == pressure.api_retries
    assert pressure.host.monitored and pressure.host.samples >= 2   # initial + final

    codes = [e.event_code for e in ctx.run_journal.events]
    assert "API_RETRY" in codes
    assert codes.index("RESOURCE_SUMMARY") < codes.index("USAGE_TOTALS") < codes.index("RUN_END")

    folder = dx.write_drawing_export(ctx, tmp_path, source_names=["M-101.pdf"])
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    block = manifest["resource_pressure"]
    assert block["starvation_status"] == expected_status
    assert block["api"]["retries"] == pressure.api_retries
    assert block["api"]["events"][0]["stage"] == "digest"
    assert block["api"]["events"][0]["retry_after_seconds"] == 1.0
    log = (folder / "run.log").read_text(encoding="utf-8")
    assert "Resource pressure (starvation check)" in log
    assert f"Starvation:  {expected_status}" in log
