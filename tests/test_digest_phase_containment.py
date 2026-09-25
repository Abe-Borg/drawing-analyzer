"""An unexpected error in the digest phase ends the phase, not the run (R1).

Remediation WP-11.2. WP-11.1 made a source or page that fails after the
inventory an unread page instead of an abort. Any other exception inside the
digest phase still ended the run with nothing: an exception out of the prescan,
either transport, the level-1 store or the accounting propagated out of
``extract_drawing_context``, so the paid digests it had collected, their usage
and their journal events were lost, no run.log or run_manifest.json was
written, the batch uploads leaked (``submit_drawing_batch`` had no outer DA-034
guard, and the collect's poll sat outside its guard), and the render spool and
the uploads retained for the critique were released only in the critique
stage's ``finally``.

The owner's rules (two rounds, measured first):

- a contained failure **stops after the digest phase**: the digests in hand
  ship (usage, ``SHEET_DIGESTED``, the export); every other page the run owed
  is an ``UnreadPage`` with one ``PAGE_UNREAD``; no later stage makes a call,
  reopens a source or writes a reviewed PDF, while the read sheets' digest
  findings are still ingested and anchored offline as on every standard run;
  the stages that did not run are not recorded; the journal closes with
  ``RUN_END``; the context goes to the exporter;
- the digest stage is **FAILED** whatever was read (D-2: the stage's own
  failure flag before its counts), its items still pages owed -> pages read;
- the collect side **harvests, then releases** (the abandon path's rule: a
  terminal batch is released; a running one is canceled first and released
  only once the cancel is accepted); ``collect_drawing_batch`` and
  ``submit_drawing_batch`` still raise after their cleanup;
- **``Exception`` only** is contained: ``KeyboardInterrupt`` and ``SystemExit``
  still end the run, and the spool and retained uploads are released on the
  way out anyway;
- **one run-level line**, the exception's **type name only**, which says what
  was exported and, with a cache, that a re-run does not pay for it again;
  each page the phase never reached carries ``not read: the digest phase
  stopped early (<Type>)``;
- **reads in flight are kept**: nothing new is rendered or submitted, and each
  read already running is waited for and kept.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

import drawing_analyzer.batch_digest as BD  # noqa: E402
import drawing_analyzer.pipeline as pl  # noqa: E402
import drawing_analyzer.render_spool as RS  # noqa: E402
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from drawing_analyzer.export import write_drawing_export  # noqa: E402
from drawing_analyzer.render import iter_rendered_sheets  # noqa: E402
from tests.test_source_page_isolation import _message, _Obj, _Pipe, _pdf, _system_text  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

FINDING_DIGEST = (
    "Sheet M-101 - Mechanical - Plan\nVAV-3 serves the room.\n\n```json\n"
    + json.dumps({"findings": [{
        "category": "coordination", "severity": "low",
        "text": "VAV serves room 12 with no damper shown", "quote": "SERVES ROOM",
    }]})
    + "\n```\n"
)


class _HttpError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class _Client(_Pipe):
    """``_Pipe`` that counts deletes and cancels, and can hold a batch running.

    ``running``: the batch reports ``in_progress`` until it is canceled.
    ``cancel_error``: the cancel request raises (the batch keeps running).
    ``results_error``: ``results()`` raises. ``upload_status``: every upload
    fails with that HTTP status (404 inlines the sheet, real time).
    """

    def __init__(self, *, running=False, cancel_error=None, results_error=None,
                 upload_status=None, digest_text=None):
        super().__init__()
        self.deleted: list[str] = []
        self.cancels: list[str] = []
        self.results_reads = 0
        self.running = running
        self.cancel_error = cancel_error
        self.results_error = results_error
        self.upload_status = upload_status
        self.digest_text = digest_text
        self.files = _Obj(upload=self._upload_or_fail, delete=self.deleted.append)
        self.beta.files = self.files
        batches = self.messages.batches
        batches.cancel = self._cancel_batch
        batches.retrieve = self._retrieve_batch
        batches.results = self._results_batch

    def _reply(self, params):
        if self.digest_text and _system_text(params.get("system", "")).startswith(
            DIGEST_SYSTEM_PROMPT
        ):
            self.digest_calls += 1
            return _message(self.digest_text, in_tok=500, out_tok=80)
        return super()._reply(params)

    def _upload_or_fail(self, *, file):
        if self.upload_status is not None:
            raise _HttpError(self.upload_status)
        return self._upload(file=file)

    def _cancel_batch(self, batch_id):
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancels.append(batch_id)
        self.running = False
        return _Obj(id=batch_id, processing_status="canceling")

    def _retrieve_batch(self, batch_id):
        if self.running:
            return _Obj(processing_status="in_progress", request_counts=_Obj(
                succeeded=0, errored=0, canceled=0, expired=0,
                processing=len(self._submitted)))
        return self._retrieve(batch_id)

    def _results_batch(self, batch_id):
        self.results_reads += 1
        if self.results_error is not None:
            raise self.results_error
        return self._results(batch_id)


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    # Background file releases run inline, so the tests see them at once.
    monkeypatch.setattr(BD, "_run_in_background", lambda fn: fn())


@pytest.fixture
def spools(monkeypatch):
    """Every render spool created during the test, by directory."""
    created: list[Path] = []
    real_init = RS.RenderedSheetSpool.__init__

    def _init(self, *a, **k):
        real_init(self, *a, **k)
        created.append(Path(self.root))

    monkeypatch.setattr(RS.RenderedSheetSpool, "__init__", _init)
    return created


def _three(tmp_path, n=3):
    return [_pdf(tmp_path / f"{c}.pdf", 1) for c in "ABCDE"[:n]]


def _run(paths, client, *, transport="realtime", work=None, **kw):
    """``work`` set means an exhaustive (QC markups) run."""
    kwargs: dict = dict(client=client, rows=2, cols=2, max_workers=1)
    kwargs.update({
        "realtime": dict(use_batch=False, critique_use_batch=False),
        "batch": dict(use_batch=True, critique_use_batch=False),
        "hybrid": dict(use_batch=False, critique_use_batch=True),
        "economy": dict(use_batch=True, critique_use_batch=True),
    }[transport])
    if work is not None:
        kwargs.update(qc_markups=True, qc_work_dir=work)
    kwargs.update(kw)
    return pl.extract_drawing_context(list(paths), **kwargs)


def _raise_for(monkeypatch, name, exc=None):
    """``digest_sheet`` raises for the sheet of source ``name``."""
    real = pl.digest_sheet

    def _digest(rendered, **kw):
        if rendered.ref.source_name == name:
            raise exc if exc is not None else RuntimeError("boom")
        return real(rendered, **kw)

    monkeypatch.setattr(pl, "digest_sheet", _digest)
    return real


def _raise_at(match):
    """A progress callback that raises on the first label containing ``match``."""
    seen: list[str] = []

    def progress(done, total, label):
        seen.append(label)
        if match in label and not any(match in s for s in seen[:-1]):
            raise RuntimeError("progress callback failed")

    progress.seen = seen
    return progress


def _stage(ctx, name="digest"):
    return next(s for s in ctx.stage_results if s.stage == name)


def _events(ctx, code):
    return [e for e in ctx.run_journal.events if e.event_code == code]


def _line(etype, *, total, unread, read, cached=False):
    """The run-level line, as the owner decided it."""
    if unread:
        text = (
            f"Digest phase stopped early by an unexpected error ({etype}): "
            f"{unread} of {total} page(s) were not read; no later stage ran"
        )
    else:
        text = (
            f"Digest phase hit an unexpected error ({etype}) after reaching every "
            "page; no later stage ran"
        )
    if read:
        text += f"; the {read} page(s) read are exported"
        if cached:
            text += " and cached, so a re-run does not pay for them again"
    return text


def _reason(etype):
    return f"not read: the digest phase stopped early ({etype})"


def _per_page_events(ctx):
    return [
        (e.event_code, e.fields.get("sheet"))
        for e in ctx.run_journal.events
        if e.event_code in ("SHEET_DIGESTED", "PAGE_UNREAD")
    ]


def _assert_closed(ctx, outcome):
    run_end = _events(ctx, "RUN_END")
    assert len(run_end) == 1
    assert run_end[0].fields["outcome"] == outcome
    assert run_end[0].fields["stopped"] == "digest"
    assert ctx.run_journal.final_status == outcome
    assert ctx.run_journal.ended_at is not None


def _export(ctx, tmp_path):
    folder = write_drawing_export(ctx, tmp_path / "export", source_names=["A.pdf"])
    run_log = (folder / "run.log").read_text(encoding="utf-8")
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    return folder, run_log, manifest


# --------------------------------------------------------------------------- #
# Real time
# --------------------------------------------------------------------------- #


def test_rt_a_raising_digest_keeps_the_paid_read(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    client = _Client(digest_text=FINDING_DIGEST)
    _raise_for(monkeypatch, "B.pdf")
    ctx = _run(paths, client)

    assert client.digest_calls == 1 and client.critique_calls == 0
    assert [s.ref.source_name for s in ctx.sheets] == ["A.pdf"]
    assert ctx.ok_sheet_count == 1 and ctx.sheet_count == 3
    assert [(p.display_label, p.reason) for p in ctx.unread_pages] == [
        ("B.pdf (page 1/1)", _reason("RuntimeError")),
        ("C.pdf (page 1/1)", _reason("RuntimeError")),
    ]
    line = _line("RuntimeError", total=3, unread=2, read=1)
    assert ctx.errors == [line]
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("FAILED", 3, 1)
    assert stage.errors[0] == line
    # No stage after the digest ran, and none is recorded.
    assert [s.stage for s in ctx.stage_results] == ["digest"]
    # The only work after it is the free, offline anchoring of the ledger.
    assert [e.stage for e in _events(ctx, "STAGE_START")] == ["digest", "anchor"]
    assert ctx.qc_status == "NOT_REQUESTED"
    _assert_closed(ctx, "PARTIAL")
    # Exactly one per-page event for every page the run owed.
    assert _per_page_events(ctx) == [
        ("SHEET_DIGESTED", "A.pdf (page 1/1)"),
        ("PAGE_UNREAD", "B.pdf (page 1/1)"),
        ("PAGE_UNREAD", "C.pdf (page 1/1)"),
    ]
    stopped = _events(ctx, "DIGEST_PHASE_STOPPED")
    assert len(stopped) == 1
    assert stopped[0].level == "ERROR"
    assert stopped[0].fields == {
        "error_type": "RuntimeError", "pages_read": "1", "pages_not_read": "2",
    }
    # The paid read keeps its usage record, and its findings reach the ledger
    # offline (ingested, anchored, numbered), as on every standard run.
    digest_records = [r for r in ctx.run_usage.records if r.stage_family == "digest"]
    assert [(r.stage_instance, r.input_tokens) for r in digest_records] == [
        ("digest:SRC-0001:p0", 500)
    ]
    assert [(f.qc_id, f.source_name) for f in ctx.findings] == [("QC-001", "A.pdf")]
    assert ctx.findings[0].anchor is not None
    assert ctx.combined_text.count("## Sheet ") == 1


def test_rt_the_stopped_run_exports(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    client = _Client(digest_text=FINDING_DIGEST)
    _raise_for(monkeypatch, "B.pdf")
    ctx = _run(paths, client)
    folder, run_log, manifest = _export(ctx, tmp_path)

    assert "NOT READ  not read: the digest phase stopped early (RuntimeError)" in run_log
    assert run_log.count("NOT READ") == 2
    assert "Outcome:     PARTIAL" in run_log
    assert "digest         FAILED" in run_log
    assert _line("RuntimeError", total=3, unread=2, read=1) in run_log
    assert manifest["run"]["final_status"] == "PARTIAL"
    assert [p["reason"] for p in manifest["unread_pages"]] == [_reason("RuntimeError")] * 2
    assert [s["status"] for s in manifest["stages"]] == ["FAILED"]
    findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
    assert [f["source_name"] for f in findings["findings"]] == ["A.pdf"]


def test_rt_a_cached_rerun_reads_only_what_was_not_read(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    cache = DigestCache(tmp_path / "cache.sqlite")
    real = _raise_for(monkeypatch, "B.pdf")
    ctx = _run(paths, _Client(), cache=cache)
    assert ctx.errors == [_line("RuntimeError", total=3, unread=2, read=1, cached=True)]

    monkeypatch.setattr(pl, "digest_sheet", real)
    rendered: list[str] = []
    real_iter = pl.iter_rendered_sheets

    def _counting(*a, **k):
        for sheet in real_iter(*a, **k):
            rendered.append(sheet.ref.source_name)
            yield sheet

    monkeypatch.setattr(pl, "iter_rendered_sheets", _counting)
    again = _Client()
    ctx2 = _run(paths, again, cache=cache)
    # The paid read is served from the cache without rendering: the level-1
    # store ran over the digests in hand.
    assert sorted(rendered) == ["B.pdf", "C.pdf"]
    assert again.digest_calls == 2
    assert ctx2.cached_sheet_count == 1
    assert ctx2.run_journal.final_status == "COMPLETE"


def test_rt_a_read_in_flight_is_kept(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    client = _Client()
    real = pl.digest_sheet
    a_done, b_raised = threading.Event(), threading.Event()

    def _digest(rendered, **kw):
        name = rendered.ref.source_name
        if name == "A.pdf":
            out = real(rendered, **kw)
            a_done.set()
            return out
        if name == "B.pdf":
            a_done.wait(5)
            time.sleep(0.2)         # A is collected and C submitted first
            b_raised.set()
            raise RuntimeError("boom")
        b_raised.wait(5)            # C's read is still running when B fails
        time.sleep(0.2)
        return real(rendered, **kw)

    monkeypatch.setattr(pl, "digest_sheet", _digest)
    ctx = _run(paths, client, max_workers=2)

    assert client.digest_calls == 2
    assert [s.ref.source_name for s in ctx.sheets] == ["A.pdf", "C.pdf"]
    assert [p.display_label for p in ctx.unread_pages] == ["B.pdf (page 1/1)"]
    assert ctx.errors == [_line("RuntimeError", total=3, unread=1, read=2)]
    assert len([r for r in ctx.run_usage.records if r.stage_family == "digest"]) == 2


def test_rt_a_raising_progress_callback_is_contained(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    progress = _raise_at("Analyzed")
    ctx = _run(paths, client, progress=progress)

    assert client.digest_calls == 1
    assert [s.ref.source_name for s in ctx.sheets] == ["A.pdf"]
    assert ctx.errors == [_line("RuntimeError", total=3, unread=2, read=1)]
    # The callback that raised is never called again.
    assert sum("Analyzed" in s for s in progress.seen) == 1
    assert progress.seen[-1].startswith("Analyzed")
    _assert_closed(ctx, "PARTIAL")


def test_rt_nothing_read_is_a_failed_run(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    _raise_for(monkeypatch, "A.pdf")
    ctx = _run(paths, _Client())

    assert ctx.sheets == [] and ctx.ok_sheet_count == 0
    assert [p.reason for p in ctx.unread_pages] == [_reason("RuntimeError")] * 3
    assert ctx.errors == [_line("RuntimeError", total=3, unread=3, read=0)]
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("FAILED", 3, 0)
    _assert_closed(ctx, "FAILED")
    assert _per_page_events(ctx) == [
        ("PAGE_UNREAD", f"{c}.pdf (page 1/1)") for c in "ABC"
    ]
    _folder, run_log, manifest = _export(ctx, tmp_path)
    assert "Outcome:     FAILED" in run_log
    assert manifest["run"]["final_status"] == "FAILED"


class _Level1PutFails(DigestCache):
    """A cache whose level-1 writes raise (the level-2 writes succeed)."""

    def __init__(self, level1_keys):
        super().__init__(None, persist=False)
        self.level1_keys = level1_keys

    def put(self, key, value):
        if key in self.level1_keys:
            raise RuntimeError("level-1 store failed")
        return super().put(key, value)


def test_a_failure_after_every_page_was_reached(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    keys: set = set()
    real_key = pl.digest_cache_key_level1

    def _key(*a, **k):
        out = real_key(*a, **k)
        keys.add(out)
        return out

    monkeypatch.setattr(pl, "digest_cache_key_level1", _key)
    client = _Client()
    ctx = _run(paths, client, cache=_Level1PutFails(keys))

    assert client.digest_calls == 3
    assert ctx.ok_sheet_count == 3 and ctx.unread_pages == []
    # The cache is what failed, so the line does not promise a free re-run.
    assert ctx.errors == [_line("RuntimeError", total=3, unread=0, read=3)]
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("FAILED", 3, 3)
    _assert_closed(ctx, "PARTIAL")


class _PutFails(DigestCache):
    """A cache whose every write raises (and whose reads find nothing)."""

    def __init__(self):
        super().__init__(None, persist=False)

    def put(self, key, value):
        raise RuntimeError("cache write failed")


@pytest.mark.parametrize("transport", ["realtime", "batch"])
def test_a_cache_whose_writes_fail_loses_no_paid_read(tmp_path, transport):
    paths = _three(tmp_path)
    client = _Client()
    ctx = _run(paths, client, transport=transport, cache=_PutFails())

    # A digest's own cache write is advisory: every paid read is kept, with
    # its usage, on both transports (the batch harvest included).
    assert client.digest_calls == 3
    assert ctx.ok_sheet_count == 3 and ctx.unread_pages == []
    assert len([r for r in ctx.run_usage.records if r.stage_family == "digest"]) == 3
    # The level-1 store still raises, which stops the run after the phase,
    # and the line does not promise a free re-run.
    assert ctx.errors == [_line("RuntimeError", total=3, unread=0, read=3)]
    assert _stage(ctx).status == "FAILED"
    _assert_closed(ctx, "PARTIAL")


def test_an_accounting_failure_still_closes_the_run(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    real = pl._record_usage
    calls = {"digest": 0}

    def _record(run_usage, **kw):
        if kw.get("family") == "digest":
            calls["digest"] += 1
            if calls["digest"] == 2:
                raise TypeError("a usage number was not a number")
        return real(run_usage, **kw)

    monkeypatch.setattr(pl, "_record_usage", _record)
    ctx = _run(paths, _Client())

    assert ctx.ok_sheet_count == 3
    assert ctx.errors == [_line("TypeError", total=3, unread=0, read=3)]
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("FAILED", 3, 3)
    assert stage.errors[0] == ctx.errors[0]
    # Only the failing record is missing: the sheets after it are still billed.
    assert [r.stage_instance for r in ctx.run_usage.records if r.stage_family == "digest"] == [
        "digest:SRC-0001:p0", "digest:SRC-0003:p0",
    ]
    # Every page still ends with exactly one per-page event.
    assert _per_page_events(ctx) == [
        ("SHEET_DIGESTED", f"{c}.pdf (page 1/1)") for c in "ABC"
    ]
    _assert_closed(ctx, "PARTIAL")


def test_an_event_failure_costs_only_its_own_page(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    real = pl.held_out_findings

    def _held(sd):
        if sd.ref.source_name == "B.pdf":
            raise TypeError("a finding could not be read")
        return real(sd)

    monkeypatch.setattr(pl, "held_out_findings", _held)
    ctx = _run(paths, _Client())

    assert ctx.ok_sheet_count == 3
    assert ctx.errors == [_line("TypeError", total=3, unread=0, read=3)]
    assert _stage(ctx).status == "FAILED"
    # B's event is the one lost; the pages after it keep theirs, and every
    # sheet keeps its usage record.
    assert _per_page_events(ctx) == [
        ("SHEET_DIGESTED", "A.pdf (page 1/1)"), ("SHEET_DIGESTED", "C.pdf (page 1/1)"),
    ]
    assert len([r for r in ctx.run_usage.records if r.stage_family == "digest"]) == 3
    _assert_closed(ctx, "PARTIAL")


class _GetFails(DigestCache):
    def get(self, key):
        raise RuntimeError("cache backend unavailable")


def test_a_prescan_failure_leaves_every_page_unread(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    ctx = _run(paths, client, cache=_GetFails(None, persist=False))

    assert client.digest_calls == 0
    assert [p.reason for p in ctx.unread_pages] == [_reason("RuntimeError")] * 3
    assert ctx.errors == [_line("RuntimeError", total=3, unread=3, read=0)]
    _assert_closed(ctx, "FAILED")


def test_a_cached_run_keeps_every_cached_digest(tmp_path):
    paths = _three(tmp_path)
    cache = DigestCache(tmp_path / "cache.sqlite")
    _run(paths, _Client(), cache=cache)
    client = _Client()
    ctx = _run(paths, client, cache=cache, progress=_raise_at("from cache"))

    assert client.digest_calls == 0
    assert ctx.cached_sheet_count == 3 and ctx.ok_sheet_count == 3
    assert ctx.errors == [_line("RuntimeError", total=3, unread=0, read=3, cached=True)]
    _assert_closed(ctx, "PARTIAL")


def test_keyboard_interrupt_still_ends_the_run(tmp_path, monkeypatch, spools):
    paths = _three(tmp_path)
    _raise_for(monkeypatch, "B.pdf", KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        _run(paths, _Client(), work=tmp_path / "work")
    # Not contained, but the spool is still removed on the way out.
    assert spools and not any(p.exists() for p in spools)


# --------------------------------------------------------------------------- #
# Batch
# --------------------------------------------------------------------------- #


def _rendered(paths):
    return iter_rendered_sheets(list(paths), rows=2, cols=2)


def test_submit_loop_failure_deletes_every_upload(tmp_path):
    # DA-034, the guard submit_critique_batch already had: an exception out of
    # the upload loop deletes every upload no batch will reference, then
    # propagates (the function's own contract; the pipeline contains).
    paths = _three(tmp_path)
    client = _Client()
    with pytest.raises(RuntimeError, match="progress callback failed"):
        BD.submit_drawing_batch(
            _rendered(paths), client=client, total=3,
            progress=_raise_at("Uploaded B.pdf"),
        )
    assert len(client.uploads) == 4
    assert sorted(client.deleted) == sorted(client.uploads)
    assert client.batch_creates == 0


def test_submit_hands_the_caller_what_it_resolved(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    slots: list = []
    with pytest.raises(RuntimeError):
        BD.submit_drawing_batch(
            _rendered(paths), client=client, total=3,
            progress=_raise_at("Uploaded B.pdf"), slots_out=slots,
        )
    assert [s.ref.source_name for s in slots] == ["A.pdf", "B.pdf"]


def test_submit_failure_between_upload_and_slot_deletes_it(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    client = _Client()
    real = BD.build_digest_request_params
    calls = {"n": 0}

    def _params(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValueError("request could not be built")
        return real(*a, **k)

    monkeypatch.setattr(BD, "build_digest_request_params", _params)
    with pytest.raises(ValueError):
        BD.submit_drawing_batch(_rendered(paths), client=client, total=3)
    assert len(client.uploads) == 4          # A's two images and B's two
    assert sorted(client.deleted) == sorted(client.uploads)


def test_batch_upload_loop_failure_through_the_pipeline(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    ctx = _run(paths, client, transport="batch", progress=_raise_at("Uploaded B.pdf"))

    assert client.batch_creates == 0 and client.digest_calls == 0
    assert sorted(client.deleted) == sorted(client.uploads) and client.uploads
    assert ctx.ok_sheet_count == 0
    assert [p.reason for p in ctx.unread_pages] == [_reason("RuntimeError")] * 3
    assert ctx.errors == [_line("RuntimeError", total=3, unread=3, read=0)]
    _assert_closed(ctx, "FAILED")


def test_an_inline_read_survives_a_submit_failure(tmp_path):
    # The Files API 404s, so each sheet is digested inline (real time, paid);
    # the loop then fails after B. A's and B's reads are kept.
    paths = _three(tmp_path)
    client = _Client(upload_status=404)
    ctx = _run(paths, client, transport="batch", progress=_raise_at("Inlined B.pdf"))

    assert client.digest_calls == 2
    assert [s.ref.source_name for s in ctx.sheets] == ["A.pdf", "B.pdf"]
    assert [p.display_label for p in ctx.unread_pages] == ["C.pdf (page 1/1)"]
    records = [r for r in ctx.run_usage.records if r.stage_family == "digest"]
    assert [r.transport for r in records] == ["REAL_TIME", "REAL_TIME"]
    assert ctx.errors == [_line("RuntimeError", total=3, unread=1, read=2)]


def _submitted(paths, client, cache=None):
    """A submitted batch; the same cache goes to both calls, as the pipeline does."""
    return BD.submit_drawing_batch(_rendered(paths), client=client, total=3, cache=cache)


def test_collect_poll_failure_reads_back_the_finished_batch(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    cache = DigestCache(None, persist=False)
    batch = _submitted(paths, client, cache)
    with pytest.raises(RuntimeError, match="progress callback failed"):
        BD.collect_drawing_batch(
            batch, client=client, cache=cache, sleep=lambda s: None,
            progress=_raise_at("batch ended"),
        )
    # The three reads the batch billed are read back (and cached, so a re-run
    # does not pay for them), then the uploads are released; an ended batch is
    # never canceled. collect still raises: its contract (DA-034).
    assert client.results_reads == 1
    assert cache.stats()["size"] == 3
    assert sorted(client.deleted) == sorted(client.uploads) and client.uploads
    assert client.cancels == []


def test_collect_hands_the_caller_what_it_read_back(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    batch = _submitted(paths, client)
    results: list = []
    with pytest.raises(RuntimeError):
        BD.collect_drawing_batch(
            batch, client=client, sleep=lambda s: None,
            progress=_raise_at("batch ended"), results_out=results,
        )
    assert [r.ref.source_name for r in results if r is not None and r.ok] == [
        "A.pdf", "B.pdf", "C.pdf"
    ]


def test_collect_poll_failure_cancels_a_running_batch(tmp_path):
    paths = _three(tmp_path)
    client = _Client(running=True)
    cache = DigestCache(None, persist=False)
    batch = _submitted(paths, client, cache)
    with pytest.raises(RuntimeError, match="progress callback failed"):
        BD.collect_drawing_batch(
            batch, client=client, cache=cache, sleep=lambda s: None,
            progress=_raise_at("batch in_progress"),
        )
    # Canceled first; once the cancel is accepted, what finished is read back
    # and the files are released.
    assert client.cancels == [batch.batch_id]
    assert cache.stats()["size"] == 3
    assert sorted(client.deleted) == sorted(client.uploads) and client.uploads


def test_collect_poll_failure_keeps_the_files_of_a_batch_it_cannot_cancel(tmp_path):
    paths = _three(tmp_path)
    client = _Client(running=True, cancel_error=RuntimeError("cancel refused"))
    batch = _submitted(paths, client)
    with pytest.raises(RuntimeError, match="progress callback failed"):
        BD.collect_drawing_batch(
            batch, client=client, sleep=lambda s: None,
            progress=_raise_at("batch in_progress"),
        )
    # The batch may still be running and needs its files: nothing is deleted,
    # and nothing is read back from a batch that has not ended.
    assert client.deleted == []
    assert client.results_reads == 0


def test_batch_poll_failure_through_the_pipeline(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    ctx = _run(paths, client, transport="batch", progress=_raise_at("batch ended"))

    assert client.digest_calls == 3
    assert ctx.ok_sheet_count == 3 and ctx.unread_pages == []
    assert ctx.errors == [_line("RuntimeError", total=3, unread=0, read=3)]
    assert sorted(client.deleted) == sorted(client.uploads) and client.uploads
    assert len([r for r in ctx.run_usage.records if r.stage_family == "digest"]) == 3
    _assert_closed(ctx, "PARTIAL")


def test_batch_results_failure_through_the_pipeline(tmp_path):
    paths = _three(tmp_path)
    client = _Client(results_error=RuntimeError("results unreadable"))
    ctx = _run(paths, client, transport="batch")

    assert ctx.ok_sheet_count == 0
    assert [p.reason for p in ctx.unread_pages] == [_reason("RuntimeError")] * 3
    assert sorted(client.deleted) == sorted(client.uploads) and client.uploads
    _assert_closed(ctx, "FAILED")


# --------------------------------------------------------------------------- #
# Exhaustive runs on every transport
# --------------------------------------------------------------------------- #


def test_fast_exhaustive_stops_and_releases_the_spool(tmp_path, monkeypatch, spools):
    paths = _three(tmp_path)
    client = _Client(digest_text=FINDING_DIGEST)
    _raise_for(monkeypatch, "B.pdf")
    ctx = _run(paths, client, work=tmp_path / "work")

    assert client.critique_calls == 0
    assert spools and not any(p.exists() for p in spools)
    assert [s.stage for s in ctx.stage_results] == ["digest"]
    assert ctx.qc_status == "FAILED"
    assert ctx.reviewed_pdf_paths == []
    assert [f.source_name for f in ctx.findings] == ["A.pdf"]
    assert ctx.errors == [_line("RuntimeError", total=3, unread=2, read=1)]
    _assert_closed(ctx, "PARTIAL")


def test_hybrid_exhaustive_stops_and_releases_the_spool(tmp_path, monkeypatch, spools):
    paths = _three(tmp_path)
    client = _Client()
    _raise_for(monkeypatch, "B.pdf")
    ctx = _run(paths, client, transport="hybrid", work=tmp_path / "work")

    assert client.critique_calls == 0 and client.uploads == []
    assert spools and not any(p.exists() for p in spools)
    assert ctx.qc_status == "FAILED"
    _assert_closed(ctx, "PARTIAL")


def test_economy_exhaustive_collect_failure_releases_every_upload(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    ctx = _run(paths, client, transport="economy", work=tmp_path / "work",
               progress=_raise_at("batch ended"))

    assert client.critique_calls == 0 and client.batch_creates == 1
    assert ctx.ok_sheet_count == 3
    assert sorted(client.deleted) == sorted(client.uploads) and client.uploads
    assert ctx.qc_status == "FAILED"
    _assert_closed(ctx, "PARTIAL")


def test_an_exception_after_the_phase_still_releases_the_spool(tmp_path, spools):
    # Outside the digest phase nothing is contained (each stage guards itself),
    # but the spool is removed on every exit: before the exception propagates,
    # not whenever the spool object happens to be collected.
    paths = _three(tmp_path)
    with pytest.raises(RuntimeError, match="progress callback failed") as held:
        _run(paths, _Client(), work=tmp_path / "work",
             progress=_raise_at("Identifying the set"))
    assert spools and not any(p.exists() for p in spools)
    assert held.value is not None


def test_an_exception_after_the_phase_still_releases_retained_uploads(tmp_path):
    paths = _three(tmp_path)
    client = _Client()
    with pytest.raises(RuntimeError, match="progress callback failed"):
        _run(paths, client, transport="economy", work=tmp_path / "work",
             progress=_raise_at("Critiquing sheets"))
    # The digest's uploads were retained for the critique, which never ran.
    assert len(client.uploads) == 6
    assert sorted(client.deleted) == sorted(client.uploads)


@pytest.mark.parametrize("transport", ["realtime", "economy"])
def test_a_callback_that_stays_broken_does_not_lose_the_run(tmp_path, transport):
    paths = _three(tmp_path)
    client = _Client()
    state = {"broken": False}
    match = "Analyzed" if transport == "realtime" else "batch ended"

    def progress(done, total, label):
        if state["broken"] or match in label:
            state["broken"] = True
            raise RuntimeError("progress callback failed")

    ctx = _run(paths, client, transport=transport, work=tmp_path / "work",
               progress=progress)
    assert ctx.ok_sheet_count >= 1
    assert ctx.qc_status == "FAILED"
    _assert_closed(ctx, "PARTIAL")


# --------------------------------------------------------------------------- #
# Wording, cardinality and the normal path
# --------------------------------------------------------------------------- #


def test_the_line_and_the_reasons_are_path_free(tmp_path, monkeypatch):
    paths = _three(tmp_path)
    secret = tmp_path / "Client Secret" / "B.pdf"
    _raise_for(monkeypatch, "B.pdf", FileNotFoundError(2, "No such file", str(secret)))
    ctx = _run(paths, _Client())
    _folder, run_log, manifest = _export(ctx, tmp_path)

    texts = list(ctx.errors) + [e for s in ctx.stage_results for e in s.errors]
    texts += [p.reason for p in ctx.unread_pages]
    texts += [json.dumps(e.fields) for e in ctx.run_journal.events]
    texts += [run_log, json.dumps(manifest)]
    assert not [t for t in texts if "Client Secret" in t or str(tmp_path) in t]
    assert ctx.errors == [_line("FileNotFoundError", total=3, unread=2, read=1)]


def test_one_line_for_every_page_not_read(tmp_path, monkeypatch):
    paths = [_pdf(tmp_path / "A.pdf", 5)]
    real = pl.digest_sheet

    def _digest(rendered, **kw):
        if rendered.ref.page_index == 1:
            raise RuntimeError("boom")
        return real(rendered, **kw)

    monkeypatch.setattr(pl, "digest_sheet", _digest)
    ctx = _run(paths, _Client())
    assert ctx.errors == [_line("RuntimeError", total=5, unread=4, read=1)]
    assert len(ctx.unread_pages) == 4
    assert len(_events(ctx, "PAGE_UNREAD")) == 4


def test_a_page_that_failed_on_its_own_keeps_its_reason(tmp_path, monkeypatch):
    paths = [_pdf(tmp_path / f"{c}.pdf", 1) for c in "ABCD"]
    real_inspect = pl.inspect_inputs

    def _inspect(p):
        inventory = real_inspect(p)
        paths[1].unlink()                       # B is lost after the inventory
        return inventory

    monkeypatch.setattr(pl, "inspect_inputs", _inspect)
    _raise_for(monkeypatch, "C.pdf")
    ctx = _run(paths, _Client())

    reasons = {p.source_name: p.reason for p in ctx.unread_pages}
    assert reasons["B.pdf"].startswith("the source could not be opened again")
    assert reasons["C.pdf"] == reasons["D.pdf"] == _reason("RuntimeError")
    assert ctx.errors[0] == _line("RuntimeError", total=4, unread=2, read=1)
    assert len(ctx.errors) == 2 and ctx.errors[1].startswith("B.pdf: ")


def test_a_clean_run_is_unchanged(tmp_path):
    paths = _three(tmp_path)
    ctx = _run(paths, _Client())
    assert ctx.errors == [] and _stage(ctx).status == "COMPLETE"
    assert _events(ctx, "DIGEST_PHASE_STOPPED") == []
    run_end = _events(ctx, "RUN_END")[0]
    assert "stopped" not in run_end.fields
    assert ctx.run_journal.final_status == "COMPLETE"
