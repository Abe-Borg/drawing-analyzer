"""A source or page that fails after the inventory never ends the run (R1 core).

Remediation WP-11.1. The input inventory (``render.inspect_inputs``) records
every ACCEPTED document's page count and revision; the pipeline then reopened
every file to count again (``list_sheets``, which skips a file it cannot open),
and both page iterators opened their sources unguarded. So a source that
vanished or locked after the inventory aborted the whole run (on real time
after a paid digest, on batch after its uploads), one page the prescan could
not read did the same, and a page the run owed could drop out of every account
without a word (a source rewritten with fewer pages read ``COMPLETE``).

The owner's rules (two rounds, measured first):

- the inventory's pages are the workload (D-8, decided narrowly: a sheet the
  run owes is one page ``(source_id, page_index)`` of an ACCEPTED inventory
  document), built without reopening any file (``render.inventory_sheet_refs``);
- both iterators take the expected page counts; a source that will not open
  again fails every expected page (``SourceUnreadableError``), a page past the
  source's current end fails (``PageNotInSourceError``), and one bad page never
  removes the good pages of its document;
- an unread page is a typed record (``DrawingContext.unread_pages``, exported
  as ``unread_pages`` in ``run_manifest.json`` and listed in run.log's Sheets
  section) plus one ``PAGE_UNREAD`` journal event, so every expected page ends
  with exactly one per-page event (``SHEET_DIGESTED`` or ``PAGE_UNREAD``);
- a source-level failure is one line in ``ctx.errors`` and the digest stage's
  errors; a page-level failure stays one line per page;
- the prescan is best effort: a page it cannot scan (or a source it cannot
  open) goes to the render path, which decides the outcome, and the geometry
  sink adds a routed page's render-time geometry in page order;
- a source with more pages than the inventory counted is read for the
  inventoried pages only, with one line naming it (the run reads PARTIAL);
  labels keep the inventory's count while the render identity keeps the
  opened file's (the level-1 keys are unchanged);
- the critique takes the inventory's pages too (``list_sheets`` stays only as
  the fallback for a caller that passes none).

Sources are removed, rewritten or locked only while no document is open on
them (inside a wrapper around ``pipeline.inspect_inputs``, which has closed
everything by the time it returns, or between two stages), so the tests run on
the Windows CI leg too; a lock is a monkeypatched ``PermissionError``, since
chmod does not bind root.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

import drawing_analyzer.pipeline as pl  # noqa: E402
import drawing_analyzer.render as R  # noqa: E402
from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from drawing_analyzer.render import inspect_inputs as _real_inspect  # noqa: E402
from drawing_analyzer.render import iter_rendered_sheets, iter_sheet_prescan, list_sheets  # noqa: E402
from drawing_analyzer.review_planner import PLANNER_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.set_identity import IDENTITY_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402
from tests.fixtures.fake_anthropic import (  # noqa: E402
    FakeBatchResult,
    FakeBatchResultEnvelope,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    FinalMessageStream,
)


# --------------------------------------------------------------------------- #
# Fixtures: small PDFs and one fake that answers every stage on both transports
# --------------------------------------------------------------------------- #


def _pdf(path: Path, pages: int, text: str = "SHEET") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i in range(pages):
        # The stem makes every page unique across sources, so no level-2
        # (image-keyed) cache serves one source's page for another's.
        doc.new_page(width=792, height=612).insert_text(
            (72, 100), f"{text} {path.stem} VAV-{i + 1} SERVES ROOM 12{i}"
        )
    doc.save(str(path))
    doc.close()
    return path


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _system_text(system) -> str:
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        return "".join(b.get("text", "") for b in system if isinstance(b, dict))
    return ""


def _message(text: str, *, in_tok: int = 100, out_tok: int = 20) -> FakeMessage:
    return FakeMessage(
        content=[FakeTextBlock(text=text)],
        usage=FakeUsage(input_tokens=in_tok, output_tokens=out_tok),
        stop_reason="end_turn",
    )


DIGEST_TEXT = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves the room."


class _Pipe:
    """Every stage of a run over a small set, real time and batch, counted."""

    def __init__(self):
        self.digest_calls = 0
        self.critique_calls = 0
        self.uploads: list[str] = []
        self.batch_creates = 0
        self._submitted: list = []
        self.files = _Obj(upload=self._upload, delete=lambda file_id: None)
        batches = _Obj(
            create=self._create, retrieve=self._retrieve, results=self._results,
            cancel=lambda batch_id: _Obj(id=batch_id, processing_status="canceling"),
        )
        self.messages = _Obj(stream=self._stream, create=self._direct, batches=batches)
        self.beta = _Obj(
            messages=_Obj(stream=self._stream, create=self._direct, batches=batches),
            files=self.files,
        )

    def _reply(self, params):
        system = _system_text(params.get("system", ""))
        if system == VERIFY_SYSTEM_PROMPT:
            return _message('{"verdict":"CONFIRMED","note":"seen"}', in_tok=40, out_tok=8)
        if system.startswith(CRITIQUE_SYSTEM_PROMPT):
            self.critique_calls += 1
            return _message('```json\n{"findings":[]}\n```', in_tok=10, out_tok=4)
        if system.startswith(DIGEST_SYSTEM_PROMPT):
            self.digest_calls += 1
            return _message(DIGEST_TEXT, in_tok=500, out_tok=80)
        if system == IDENTITY_SYSTEM_PROMPT:
            payload = {"disciplines": ["mechanical"], "jurisdiction": "", "language": "en",
                       "units": "imperial", "adopted_codes": [], "confidence": "medium"}
            return _message("```json\n" + json.dumps(payload) + "\n```", in_tok=30, out_tok=10)
        if system == PLANNER_SYSTEM_PROMPT:
            plan = {"plans": [{"discipline": "mechanical", "title": "Mech QC", "items": [
                {"text": "Flag a relief valve set above its rated pressure.",
                 "severity": "medium", "refs": []}]}]}
            return _message("```json\n" + json.dumps(plan) + "\n```", in_tok=30, out_tok=10)
        return _message("ok", in_tok=1, out_tok=1)

    def _stream(self, **kw):
        kw.pop("betas", None)
        kw.pop("fallbacks", None)
        return FinalMessageStream(self._reply(kw))

    def _direct(self, **kw):
        kw.pop("betas", None)
        kw.pop("fallbacks", None)
        return self._reply(kw)

    def _upload(self, *, file):
        fid = f"file_{len(self.uploads) + 1}"
        self.uploads.append(fid)
        return _Obj(id=fid)

    def _create(self, *, requests, betas=None):
        self.batch_creates += 1
        self._submitted = [
            (r, FakeBatchResultEnvelope(type="succeeded", message=self._reply(r["params"])))
            for r in requests
        ]
        return _Obj(id=f"batch_{self.batch_creates}")

    def _retrieve(self, batch_id):
        n = len(self._submitted)
        return _Obj(processing_status="ended", request_counts=_Obj(
            succeeded=n, errored=0, canceled=0, expired=0, processing=0))

    def _results(self, batch_id):
        for req, env in self._submitted:
            yield FakeBatchResult(custom_id=req["custom_id"], result=env)


@pytest.fixture(autouse=True)
def _sequential(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")


def _run(paths, client, *, transport="realtime", cache=None, work=None):
    """``work`` set means an exhaustive (QC markups) run."""
    kwargs: dict = dict(client=client, rows=2, cols=2, cache=cache, max_workers=1)
    if transport == "batch":
        kwargs.update(use_batch=True, critique_use_batch=False)
    elif transport == "hybrid":
        kwargs.update(use_batch=False, critique_use_batch=True)
    elif transport == "economy":
        kwargs.update(use_batch=True, critique_use_batch=True)
    else:
        kwargs.update(use_batch=False, critique_use_batch=False)
    if work is not None:
        kwargs.update(qc_markups=True, qc_work_dir=work)
    return pl.extract_drawing_context(list(paths), **kwargs)


def _after_inventory(monkeypatch, action):
    """Run ``action`` once the real inventory has closed every document."""
    def _wrapped(paths):
        inventory = _real_inspect(paths)
        action()
        return inventory
    monkeypatch.setattr(pl, "inspect_inputs", _wrapped)


def _lock_after_inventory(monkeypatch, victim: Path):
    """Every later open of ``victim`` raises ``PermissionError`` (a Windows lock)."""
    state = {"armed": False}
    real_open = pymupdf.open

    def _open(*args, **kwargs):
        target = args[0] if args else kwargs.get("filename")
        if state["armed"] and target is not None and Path(str(target)) == victim:
            raise PermissionError(13, "Permission denied", str(target))
        return real_open(*args, **kwargs)

    monkeypatch.setattr(pymupdf, "open", _open)
    _after_inventory(monkeypatch, lambda: state.__setitem__("armed", True))


def _stage(ctx, name="digest"):
    return next(s for s in ctx.stage_results if s.stage == name)


def _events(ctx, code):
    return [e for e in ctx.run_journal.events if e.event_code == code]


def _lines_for(lines, name):
    return [line for line in lines if line.startswith(f"{name}:") or line.startswith(f"{name} (")]


def _assert_path_free(ctx, tmp_path):
    texts = list(ctx.errors) + [e for s in ctx.stage_results for e in (s.errors + s.warnings)]
    texts += [json.dumps(p.to_dict()) for p in ctx.unread_pages]
    texts += [json.dumps(e.fields) for e in ctx.run_journal.events]
    leaks = [t for t in texts if str(tmp_path) in t or tmp_path.name in t]
    assert not leaks, leaks


# --------------------------------------------------------------------------- #
# The workload is the inventory's pages, built without reopening any file
# --------------------------------------------------------------------------- #


def test_refs_equal_list_sheets(tmp_path):
    from drawing_analyzer.render import inventory_sheet_refs

    a = _pdf(tmp_path / "a" / "M-101.pdf", 2)
    b = _pdf(tmp_path / "b" / "M-101.pdf", 3)
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"%PDF-1.7 not really")
    inventory = _real_inspect([bad, a, b, a])
    refs = inventory_sheet_refs(inventory)
    assert refs == list_sheets(inventory.accepted_paths)
    assert [r.source_id for r in refs] == ["SRC-0001"] * 2 + ["SRC-0002"] * 3
    assert inventory.expected_page_counts() == {str(a): 2, str(b): 3}


def test_refs_open_nothing(tmp_path, monkeypatch):
    from drawing_analyzer.render import inventory_sheet_refs

    a = _pdf(tmp_path / "A.pdf", 2)
    inventory = _real_inspect([a])

    def _no_open(*_a, **_k):
        raise AssertionError("the workload must be built without reopening a file")

    monkeypatch.setattr(pymupdf, "open", _no_open)
    refs = inventory_sheet_refs(inventory)
    assert [r.display_label for r in refs] == ["A.pdf (page 1/2)", "A.pdf (page 2/2)"]


# --------------------------------------------------------------------------- #
# The iterators: attributable failures for the expected pages, one bad page
# never removes the good ones
# --------------------------------------------------------------------------- #


def test_render_iter_missing_source(tmp_path):
    from drawing_analyzer.render import SourceUnreadableError

    a = _pdf(tmp_path / "A.pdf", 1)
    gone = tmp_path / "B.pdf"
    errors: list = []
    sheets = list(iter_rendered_sheets(
        [a, gone], rows=2, cols=2, expected_pages={str(a): 1, str(gone): 3},
        on_page_error=lambda ref, exc: errors.append((ref, exc)),
    ))
    assert [s.ref.display_label for s in sheets] == ["A.pdf (page 1/1)"]
    assert [r.display_label for r, _ in errors] == [
        "B.pdf (page 1/3)", "B.pdf (page 2/3)", "B.pdf (page 3/3)"
    ]
    assert [r.source_id for r, _ in errors] == ["SRC-0002"] * 3
    excs = {id(exc) for _, exc in errors}
    assert len(excs) == 1                      # one failure, reported per page
    exc = errors[0][1]
    assert isinstance(exc, SourceUnreadableError)
    assert (exc.cause_type, exc.expected) == ("FileNotFoundError", 3)
    assert str(tmp_path) not in str(exc) and "B.pdf" not in str(exc)


def test_render_iter_legacy_raises(tmp_path):
    # A caller that passes no expected pages keeps the old contract: with no
    # page count there is nothing to attribute the failure to.
    with pytest.raises(Exception):
        list(iter_rendered_sheets([tmp_path / "gone.pdf"], rows=2, cols=2))


def test_render_iter_skips_unwanted(tmp_path, monkeypatch):
    # A source none of whose expected pages is wanted is never opened, so a
    # source that vanished after its pages were served from the cache costs
    # nothing here.
    a = _pdf(tmp_path / "A.pdf", 2)
    gone = tmp_path / "B.pdf"
    opened: list = []
    real_open = pymupdf.open

    def _open(*args, **kwargs):
        opened.append(Path(str(args[0])).name)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(pymupdf, "open", _open)
    errors: list = []
    sheets = list(iter_rendered_sheets(
        [a, gone], rows=2, cols=2, only={(str(a), 1)},
        expected_pages={str(a): 2, str(gone): 1},
        on_page_error=lambda ref, exc: errors.append(ref),
    ))
    assert [s.ref.page_index for s in sheets] == [1]
    assert opened == ["A.pdf"] and errors == []


def test_render_iter_only_filters_failures(tmp_path):
    gone = tmp_path / "B.pdf"
    errors: list = []
    list(iter_rendered_sheets(
        [gone], rows=2, cols=2, only={(str(gone), 1), (str(gone), 3)},
        expected_pages={str(gone): 5},
        on_page_error=lambda ref, exc: errors.append(ref.page_index),
    ))
    assert errors == [1, 3]


def test_render_iter_fewer_pages(tmp_path):
    from drawing_analyzer.render import PageNotInSourceError

    a = _pdf(tmp_path / "A.pdf", 2)
    errors: list = []
    changed: list = []
    sheets = list(iter_rendered_sheets(
        [a], rows=2, cols=2, expected_pages={str(a): 3},
        on_page_error=lambda ref, exc: errors.append((ref, exc)),
        on_page_count_changed=lambda path, expected, actual: changed.append(
            (Path(path).name, expected, actual)),
    ))
    assert [s.ref.display_label for s in sheets] == ["A.pdf (page 1/3)", "A.pdf (page 2/3)"]
    (ref, exc), = errors
    assert ref.display_label == "A.pdf (page 3/3)"
    assert isinstance(exc, PageNotInSourceError)
    assert (exc.page_index, exc.expected, exc.actual) == (2, 3, 2)
    assert changed == [("A.pdf", 3, 2)]


def test_render_iter_more_pages(tmp_path):
    a = _pdf(tmp_path / "A.pdf", 4)
    errors: list = []
    changed: list = []
    sheets = list(iter_rendered_sheets(
        [a], rows=2, cols=2, expected_pages={str(a): 3},
        on_page_error=lambda ref, exc: errors.append(ref),
        on_page_count_changed=lambda path, expected, actual: changed.append((expected, actual)),
    ))
    assert [s.ref.display_label for s in sheets] == [
        "A.pdf (page 1/3)", "A.pdf (page 2/3)", "A.pdf (page 3/3)"
    ]
    assert errors == [] and changed == [(3, 4)]


def test_render_iter_bad_page_keeps_good(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 3)
    real = R.render_sheet

    def _boom(page, ref, **kw):
        if ref.page_index == 1:
            raise RuntimeError("render boom")
        return real(page, ref, **kw)

    monkeypatch.setattr(R, "render_sheet", _boom)
    errors: list = []
    sheets = list(iter_rendered_sheets(
        [a], rows=2, cols=2, expected_pages={str(a): 3},
        on_page_error=lambda ref, exc: errors.append(ref.page_index),
    ))
    assert [s.ref.page_index for s in sheets] == [0, 2] and errors == [1]


def test_prescan_skips_unscannable(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 3)
    gone = tmp_path / "B.pdf"
    real = R._sheet_geometry_no_render

    def _boom(page, ref, **kw):
        if ref.page_index == 1:
            raise RuntimeError("geometry boom")
        return real(page, ref, **kw)

    monkeypatch.setattr(R, "_sheet_geometry_no_render", _boom)
    scanned = list(iter_sheet_prescan(
        [a, gone], rows=2, cols=2, expected_pages={str(a): 3, str(gone): 2},
    ))
    assert [ref.display_label for ref, _i, _g in scanned] == [
        "A.pdf (page 1/3)", "A.pdf (page 3/3)"
    ]


def test_prescan_legacy_raises(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 2)
    real = R._sheet_geometry_no_render

    def _boom(page, ref, **kw):
        raise RuntimeError("geometry boom")

    monkeypatch.setattr(R, "_sheet_geometry_no_render", _boom)
    with pytest.raises(RuntimeError):
        list(iter_sheet_prescan([a], rows=2, cols=2))
    monkeypatch.setattr(R, "_sheet_geometry_no_render", real)
    with pytest.raises(Exception):
        list(iter_sheet_prescan([tmp_path / "gone.pdf"], rows=2, cols=2))


def test_prescan_identity_uses_file_count(tmp_path):
    # The label follows the inventory; the render identity (and so every
    # level-1 key) keeps reading the opened document's own count.
    a = _pdf(tmp_path / "A.pdf", 4)
    (ref, identity, geom), *_ = list(iter_sheet_prescan(
        [a], rows=2, cols=2, expected_pages={str(a): 3},
    ))
    assert ref.display_label == "A.pdf (page 1/3)"
    assert geom.ref.display_label == "A.pdf (page 1/3)"
    assert "page_count=4" in identity.split("|")
    unchanged = next(iter(iter_sheet_prescan([a], rows=2, cols=2)))[1]
    assert identity == unchanged


def test_prescan_unchanged_identity(tmp_path):
    a = _pdf(tmp_path / "A.pdf", 2)
    with_expected = list(iter_sheet_prescan([a], rows=2, cols=2, expected_pages={str(a): 2}))
    legacy = list(iter_sheet_prescan([a], rows=2, cols=2))
    assert [(r, i) for r, i, _ in with_expected] == [(r, i) for r, i, _ in legacy]


def test_sink_inserts_in_page_order(tmp_path):
    from drawing_analyzer.models import SheetGeometry, SheetRef
    from drawing_analyzer.pipeline import _GeometryOmissionSink, _refkey

    def _ref(i):
        return SheetRef(pdf_path=tmp_path / "A.pdf", page_index=i, source_name="A.pdf",
                        page_count=3, source_id="SRC-0001")

    def _geom(i, omitted=None):
        return SheetGeometry(ref=_ref(i), page_width_pt=612, page_height_pt=792,
                             rows=2, cols=2, omitted_tile_count=omitted)

    prescan = [_geom(0), _geom(2)]
    order = {_refkey(_ref(i)): i for i in range(3)}
    sink = _GeometryOmissionSink(prescan, order=order)
    sink.append(_geom(1, omitted=4))            # a routed page: added in order
    sink.append(_geom(2, omitted=1))            # a known page: merged
    stray = SheetGeometry(ref=SheetRef(pdf_path=tmp_path / "X.pdf", page_index=0,
                                       source_name="X.pdf", page_count=1),
                          page_width_pt=612, page_height_pt=792, rows=2, cols=2)
    sink.append(stray)                          # not an expected page: ignored
    assert [g.ref.page_index for g in prescan] == [0, 1, 2]
    assert [g.omitted_tile_count for g in prescan] == [None, 4, 1]


# --------------------------------------------------------------------------- #
# A source lost after the inventory: real time, batch and Hybrid, cold and
# cached, the second, the first, or every source
# --------------------------------------------------------------------------- #

TRANSPORTS = ["realtime", "batch", "hybrid"]


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("which", ["second", "first", "all"])
def test_lost_source(tmp_path, monkeypatch, transport, cached, which):
    a = _pdf(tmp_path / "A.pdf", 2)
    b = _pdf(tmp_path / "B.pdf", 2)
    lost = {"second": [b], "first": [a], "all": [a, b]}[which]
    kept = [p for p in (a, b) if p not in lost]
    _after_inventory(monkeypatch, lambda: [p.unlink() for p in lost])
    client = _Pipe()
    work = tmp_path / "qc" if transport == "hybrid" else None
    ctx = _run([a, b], client, transport=transport,
               cache=DigestCache(None, persist=False) if cached else None, work=work)

    # The run returns a context and a journal that closed.
    assert ctx.run_journal is not None and ctx.run_journal.final_status
    stage = _stage(ctx)
    assert (stage.items_in, stage.items_out) == (4, 2 * len(kept))
    assert ctx.sheet_count == 4
    assert stage.status == ("FAILED" if not kept else "PARTIAL")
    assert ctx.run_journal.final_status == ("FAILED" if not kept else "PARTIAL")
    # The surviving sheets were digested.
    assert [s.ref.display_label for s in ctx.sheets] == [
        f"{p.name} (page {i}/2)" for p in kept for i in (1, 2)
    ]
    assert all(s.ok for s in ctx.sheets)
    assert client.digest_calls == 2 * len(kept)
    # Every expected page of a lost source has its record ...
    assert [(p.source_name, p.page_index) for p in ctx.unread_pages] == [
        (p.name, i) for p in lost for i in (0, 1)
    ]
    assert {p.reason for p in ctx.unread_pages} == {
        "the source could not be opened again (FileNotFoundError)"
    }
    # ... one source line in ctx.errors and in the digest stage's errors ...
    for p in lost:
        line = (f"{p.name}: the source could not be opened again (FileNotFoundError); "
                "its 2 page(s) were not read")
        assert _lines_for(ctx.errors, p.name)[:1] == [line], ctx.errors
        assert _lines_for(stage.errors, p.name) == [line], stage.errors
    # ... and every expected page ends with exactly one per-page event.
    digested = [e.fields["sheet"] for e in _events(ctx, "SHEET_DIGESTED")]
    unread = [e.fields["sheet"] for e in _events(ctx, "PAGE_UNREAD")]
    assert sorted(digested + unread) == sorted(
        f"{p.name} (page {i}/2)" for p in (a, b) for i in (1, 2)
    )
    assert unread == [f"{p.name} (page {i}/2)" for p in lost for i in (1, 2)]
    _assert_path_free(ctx, tmp_path)


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("cached", [False, True])
def test_locked_source(tmp_path, monkeypatch, transport, cached):
    a = _pdf(tmp_path / "A.pdf", 2)
    b = _pdf(tmp_path / "B.pdf", 2)
    _lock_after_inventory(monkeypatch, b)
    client = _Pipe()
    work = tmp_path / "qc" if transport == "hybrid" else None
    ctx = _run([a, b], client, transport=transport,
               cache=DigestCache(None, persist=False) if cached else None, work=work)
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("PARTIAL", 4, 2)
    line = ("B.pdf: the source could not be opened again (PermissionError); "
            "its 2 page(s) were not read")
    assert line in ctx.errors and line in stage.errors
    assert [p.display_label for p in ctx.unread_pages] == ["B.pdf (page 1/2)", "B.pdf (page 2/2)"]
    assert [s.ref.display_label for s in ctx.sheets] == ["A.pdf (page 1/2)", "A.pdf (page 2/2)"]
    _assert_path_free(ctx, tmp_path)


def test_batch_uploads_only_survivors(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 2)
    b = _pdf(tmp_path / "B.pdf", 2)
    _after_inventory(monkeypatch, b.unlink)
    client = _Pipe()
    ctx = _run([a, b], client, transport="batch")
    assert client.batch_creates == 1
    assert client.digest_calls == 2
    assert len(client.uploads) > 0
    assert [s.ref.source_name for s in ctx.sheets] == ["A.pdf", "A.pdf"]


def test_paid_read_is_kept(tmp_path, monkeypatch):
    # The source that goes missing comes second, after a paid digest: the run
    # used to raise and discard it.
    from drawing_analyzer.export import write_drawing_export

    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 1)
    _after_inventory(monkeypatch, b.unlink)
    client = _Pipe()
    ctx = _run([a, b], client)
    assert client.digest_calls == 1
    (sheet,) = ctx.sheets
    assert sheet.ok and DIGEST_TEXT.splitlines()[1] in ctx.combined_text
    records = [r for r in ctx.run_usage.records if r.stage_family == "digest"]
    assert [(r.stage_instance, r.input_tokens) for r in records] == [("digest:SRC-0001:p0", 500)]
    folder = write_drawing_export(ctx, tmp_path / "out", source_names=["A.pdf", "B.pdf"])
    manifest = json.loads((folder / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["unread_pages"] == [{
        "source_id": "SRC-0002", "sheet": "B.pdf (page 1/1)", "page_index": 0,
        "page_count": 1,
        "reason": "the source could not be opened again (FileNotFoundError)",
    }]
    assert manifest["status"]["sheet_count"] == 2
    assert any(p.name.endswith("_p1.md") and "A" in p.name for p in folder.iterdir())
    log = (folder / "run.log").read_text(encoding="utf-8")
    assert "1 page(s) not read" in log
    assert "B.pdf (page 1/1)" in log and "NOT READ" in log
    assert str(tmp_path) not in log and str(tmp_path) not in json.dumps(manifest)


def test_all_lost_is_not_zero_sheet_exit(tmp_path, monkeypatch):
    from drawing_analyzer.run_journal import render_run_log

    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 1)
    _after_inventory(monkeypatch, lambda: (a.unlink(), b.unlink()))
    ctx = _run([a, b], _Pipe())
    assert "No readable PDF pages found in the selected files." not in ctx.errors
    assert (_stage(ctx).status, _stage(ctx).items_in, _stage(ctx).items_out) == ("FAILED", 2, 0)
    assert ctx.run_journal.final_status == "FAILED"
    assert "FAILED — no sheets were analyzed" in render_run_log(ctx)
    assert len(ctx.unread_pages) == 2


def test_nothing_accepted_keeps_zero_exit(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    ctx = _run([bad], _Pipe())
    assert "No readable PDF pages found in the selected files." in ctx.errors
    assert ctx.sheet_count == 0 and getattr(ctx, "unread_pages", []) == []


def test_all_lost_exhaustive(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 1)
    _after_inventory(monkeypatch, lambda: (a.unlink(), b.unlink()))
    ctx = _run([a, b], _Pipe(), transport="hybrid", work=tmp_path / "qc")
    assert _stage(ctx).status == "FAILED"
    critique = _stage(ctx, "critique")
    assert (critique.status, critique.items_in, critique.items_out) == ("FAILED", 4, 0)
    assert ctx.run_journal.final_status == "FAILED"
    _assert_path_free(ctx, tmp_path)


# --------------------------------------------------------------------------- #
# Cardinality: one line per source, one record and one event per page
# --------------------------------------------------------------------------- #


def test_five_page_source_is_one_line(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 5)
    _after_inventory(monkeypatch, b.unlink)
    ctx = _run([a, b], _Pipe())
    stage = _stage(ctx)
    line = ("B.pdf: the source could not be opened again (FileNotFoundError); "
            "its 5 page(s) were not read")
    assert _lines_for(ctx.errors, "B.pdf") == [line]
    assert _lines_for(stage.errors, "B.pdf") == [line]
    assert len(ctx.unread_pages) == 5
    assert len(_events(ctx, "PAGE_UNREAD")) == 5
    _assert_path_free(ctx, tmp_path)


def test_page_level_stays_per_page(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 3)
    real = R.render_sheet

    def _boom(page, ref, **kw):
        if ref.page_index in (0, 2):
            raise RuntimeError("render boom")
        return real(page, ref, **kw)

    monkeypatch.setattr(R, "render_sheet", _boom)
    ctx = _run([a], _Pipe())
    assert _lines_for(ctx.errors, "A.pdf") == [
        "A.pdf (page 1/3): page could not be rendered (RuntimeError)",
        "A.pdf (page 3/3): page could not be rendered (RuntimeError)",
    ]
    assert [p.reason for p in ctx.unread_pages] == [
        "page could not be rendered (RuntimeError)"
    ] * 2


def test_partial_source_line():
    from drawing_analyzer.models import SheetRef
    from drawing_analyzer.pipeline import _UnreadPages
    from drawing_analyzer.render import SourceUnreadableError

    unread = _UnreadPages()
    refs = [SheetRef(pdf_path=Path("B.pdf"), page_index=i, source_name="B.pdf",
                     page_count=5, source_id="SRC-0001") for i in range(5)]
    failure = SourceUnreadableError(FileNotFoundError("gone"), 5)
    for i in (1, 3):
        unread.page_failed(refs[i], failure)
    unread.settle(refs, read={pl._refkey(refs[i]) for i in (0, 2, 4)})
    assert unread.lines(refs) == [
        "B.pdf: the source could not be opened again (FileNotFoundError); "
        "2 of its 5 page(s) were not read"
    ]


def test_first_outcome_wins():
    from drawing_analyzer.models import SheetRef
    from drawing_analyzer.pipeline import _UnreadPages

    unread = _UnreadPages()
    ref = SheetRef(pdf_path=Path("A.pdf"), page_index=0, source_name="A.pdf",
                   page_count=1, source_id="SRC-0001")
    unread.page_failed(ref, RuntimeError("first"))
    unread.page_failed(ref, ValueError("second"))
    (record,) = unread.settle([ref], read=set())
    assert record.reason == "page could not be rendered (RuntimeError)"


def test_unreached_page_has_outcome(tmp_path, monkeypatch):
    # A page the render path neither yields nor reports still gets an outcome.
    a = _pdf(tmp_path / "A.pdf", 3)
    real = pl.iter_rendered_sheets

    def _drops_page_two(paths, **kwargs):
        return (s for s in real(paths, **kwargs) if s.ref.page_index != 1)

    monkeypatch.setattr(pl, "iter_rendered_sheets", _drops_page_two)
    ctx = _run([a], _Pipe())
    assert "A.pdf (page 2/3): page was not read (no render outcome was recorded)" in ctx.errors
    assert (_stage(ctx).status, _stage(ctx).items_in, _stage(ctx).items_out) == ("PARTIAL", 3, 2)
    (record,) = ctx.unread_pages
    assert (record.display_label, record.reason) == (
        "A.pdf (page 2/3)", "no render outcome was recorded"
    )


# --------------------------------------------------------------------------- #
# The prescan is best effort: what it cannot scan goes to the render path
# --------------------------------------------------------------------------- #


def _break_prescan(monkeypatch, kind):
    if kind == "identity":
        real = R.sheet_render_identity

        def _boom(page, **kw):
            if kw.get("page_index") == 1:
                raise RuntimeError("identity boom")
            return real(page, **kw)
        monkeypatch.setattr(R, "sheet_render_identity", _boom)
    elif kind == "word_count":
        real_wc = R._page_word_count

        def _wc(page):
            if page.number == 1:
                raise RuntimeError("word count boom")
            return real_wc(page)
        monkeypatch.setattr(R, "_page_word_count", _wc)
    elif kind == "geometry":
        real_g = R._sheet_geometry_no_render

        def _geom(page, ref, **kw):
            if ref.page_index == 1:
                raise RuntimeError("geometry boom")
            return real_g(page, ref, **kw)
        monkeypatch.setattr(R, "_sheet_geometry_no_render", _geom)
    elif kind == "page_load":
        real_get = pymupdf.Document.__getitem__

        def _getitem(self, index):
            if index == 1:
                raise RuntimeError("page load boom")
            return real_get(self, index)
        monkeypatch.setattr(pymupdf.Document, "__getitem__", _getitem)
    elif kind == "text":
        real_t = R._page_text_and_view_words

        def _text(page, geometry):
            if page.number == 1:
                raise RuntimeError("text boom")
            return real_t(page, geometry)
        monkeypatch.setattr(R, "_page_text_and_view_words", _text)


@pytest.mark.parametrize("kind", ["identity", "word_count", "geometry"])
def test_prescan_only_failure_is_read(tmp_path, monkeypatch, kind):
    a = _pdf(tmp_path / "A.pdf", 3)
    _break_prescan(monkeypatch, kind)
    client = _Pipe()
    ctx = _run([a], client, cache=DigestCache(None, persist=False))
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("COMPLETE", 3, 3)
    assert client.digest_calls == 3 and ctx.unread_pages == [] and ctx.errors == []
    # The routed page's geometry came from its render, in page order.
    assert [g.ref.page_index for g in ctx.sheet_geometries] == [0, 1, 2]
    assert ctx.sheet_geometries[1].words


@pytest.mark.parametrize("kind", ["page_load", "text"])
def test_prescan_and_render_fail(tmp_path, monkeypatch, kind):
    a = _pdf(tmp_path / "A.pdf", 3)
    _break_prescan(monkeypatch, kind)
    ctx = _run([a], _Pipe(), cache=DigestCache(None, persist=False))
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("PARTIAL", 3, 2)
    assert _lines_for(ctx.errors, "A.pdf") == [
        "A.pdf (page 2/3): page could not be rendered (RuntimeError)"
    ]                                           # one outcome, from the render
    assert [p.display_label for p in ctx.unread_pages] == ["A.pdf (page 2/3)"]
    assert [s.ref.page_index for s in ctx.sheets] == [0, 2]


def test_render_only_failure(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 3)
    real = R.render_sheet

    def _boom(page, ref, **kw):
        if ref.page_index == 1:
            raise RuntimeError("render boom")
        return real(page, ref, **kw)

    monkeypatch.setattr(R, "render_sheet", _boom)
    ctx = _run([a], _Pipe(), cache=DigestCache(None, persist=False))
    assert [s.ref.page_index for s in ctx.sheets] == [0, 2]
    assert [p.display_label for p in ctx.unread_pages] == ["A.pdf (page 2/3)"]
    assert [e.fields["sheet"] for e in _events(ctx, "PAGE_UNREAD")] == ["A.pdf (page 2/3)"]


def test_cached_source_vanishing_costs_nothing(tmp_path, monkeypatch):
    # B's pages hit the level-1 cache, so B vanishing after the prescan asks
    # nothing of the render path: the run still reads A's changed page.
    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 2)
    cache = DigestCache(None, persist=False)
    _run([a, b], _Pipe(), cache=cache)
    _pdf(a, 1, text="REVISED")                  # A changes: its page misses
    real = pl._level1_partition

    def _then_lose_b(*args, **kwargs):
        out = real(*args, **kwargs)
        b.unlink()
        return out

    monkeypatch.setattr(pl, "_level1_partition", _then_lose_b)
    client = _Pipe()
    ctx = _run([a, b], client, cache=cache)
    assert client.digest_calls == 1
    assert (_stage(ctx).status, _stage(ctx).items_in, _stage(ctx).items_out) == ("COMPLETE", 3, 3)
    assert ctx.cached_sheet_count == 2 and ctx.unread_pages == []


# --------------------------------------------------------------------------- #
# The page count changed after the inventory
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("transport", ["realtime", "batch"])
@pytest.mark.parametrize("cached", [False, True])
def test_fewer_pages(tmp_path, monkeypatch, transport, cached):
    a = _pdf(tmp_path / "A.pdf", 3)
    _after_inventory(monkeypatch, lambda: _pdf(a, 2, text="REWRITTEN"))
    ctx = _run([a], _Pipe(), transport=transport,
               cache=DigestCache(None, persist=False) if cached else None)
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("PARTIAL", 3, 2)
    line = "A.pdf: has 2 page(s) now, 3 at the inventory; page 3 was not read"
    assert _lines_for(ctx.errors, "A.pdf") == [line]
    assert stage.errors == [line]
    (record,) = ctx.unread_pages
    assert record.display_label == "A.pdf (page 3/3)"
    assert record.reason == (
        "page 3 is not in the source now: it has 2 page(s), the inventory counted 3"
    )
    assert [s.ref.display_label for s in ctx.sheets] == ["A.pdf (page 1/3)", "A.pdf (page 2/3)"]
    assert ctx.run_journal.final_status == "PARTIAL"


@pytest.mark.parametrize("transport", ["realtime", "batch"])
@pytest.mark.parametrize("cached", [False, True])
def test_more_pages(tmp_path, monkeypatch, transport, cached):
    a = _pdf(tmp_path / "A.pdf", 3)
    _after_inventory(monkeypatch, lambda: _pdf(a, 4, text="REWRITTEN"))
    client = _Pipe()
    ctx = _run([a], client, transport=transport,
               cache=DigestCache(None, persist=False) if cached else None)
    stage = _stage(ctx)
    assert (stage.status, stage.items_in, stage.items_out) == ("COMPLETE", 3, 3)
    assert client.digest_calls == 3
    line = ("A.pdf: has 4 page(s) now, 3 at the inventory; "
            "only the 3 inventoried page(s) were read")
    assert ctx.errors == [line]
    assert stage.warnings == [line] and stage.errors == []
    assert ctx.unread_pages == []
    assert [s.ref.display_label for s in ctx.sheets] == [
        "A.pdf (page 1/3)", "A.pdf (page 2/3)", "A.pdf (page 3/3)"
    ]
    assert ctx.run_journal.final_status == "PARTIAL"


def test_more_pages_one_line(tmp_path, monkeypatch):
    # The prescan and the render both open the source; the change is said once.
    a = _pdf(tmp_path / "A.pdf", 2)
    b = _pdf(tmp_path / "B.pdf", 1)
    _after_inventory(monkeypatch, lambda: _pdf(a, 5, text="REWRITTEN"))
    ctx = _run([a, b], _Pipe(), cache=DigestCache(None, persist=False))
    assert _lines_for(ctx.errors, "A.pdf") == [
        "A.pdf: has 5 page(s) now, 2 at the inventory; only the 2 inventoried page(s) were read"
    ]


# --------------------------------------------------------------------------- #
# The critique takes the inventory's pages
# --------------------------------------------------------------------------- #


def _lose_before_critique(monkeypatch, victim: Path):
    real = pl._run_critique_stage

    def _wrapped(paths, **kwargs):
        victim.unlink()                         # no document is open between stages
        return real(paths, **kwargs)

    monkeypatch.setattr(pl, "_run_critique_stage", _wrapped)


@pytest.mark.parametrize("transport", ["realtime", "economy"])
@pytest.mark.parametrize("cached", [False, True])
def test_critique_reuses_digest_images(tmp_path, monkeypatch, transport, cached):
    # Real time spools the digest's own renders and Economy keeps its uploads:
    # the critique reads those exact images although the file is gone.
    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 2)
    _lose_before_critique(monkeypatch, b)
    client = _Pipe()
    ctx = _run([a, b], client, transport=transport, work=tmp_path / "qc",
               cache=DigestCache(None, persist=False) if cached else None)
    critique = _stage(ctx, "critique")
    assert (critique.status, critique.items_in, critique.items_out) == ("COMPLETE", 6, 6)
    assert client.critique_calls == 6
    _assert_path_free(ctx, tmp_path)


@pytest.mark.parametrize("cached", [False, True])
def test_critique_hybrid_names_pages(tmp_path, monkeypatch, cached):
    # Hybrid re-renders every page for the critique: each page it cannot
    # obtain is named with the reason, never a raw path or a silent gap.
    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 2)
    _lose_before_critique(monkeypatch, b)
    ctx = _run([a, b], _Pipe(), transport="hybrid", work=tmp_path / "qc",
               cache=DigestCache(None, persist=False) if cached else None)
    critique = _stage(ctx, "critique")
    assert (critique.status, critique.items_in, critique.items_out) == ("PARTIAL", 6, 2)
    assert critique.errors == [
        f"B.pdf (page {i}/2): no critique input could be obtained: "
        "the source could not be opened again (FileNotFoundError)"
        for i in (1, 2)
    ]
    assert critique.warnings[0] == (
        "critique: 2 of 6 requested read(s) judged; 4 skipped, 0 returned no judgment"
    )
    _assert_path_free(ctx, tmp_path)


def test_critique_fallback_list_sheets(tmp_path, monkeypatch):
    # A direct caller that passes no pages keeps the old enumeration.
    from drawing_analyzer.models import RunUsage

    a = _pdf(tmp_path / "A.pdf", 2)
    calls: list = []
    real = pl.list_sheets

    def _counting(paths):
        calls.append(len(paths))
        return real(paths)

    monkeypatch.setattr(pl, "list_sheets", _counting)
    pl._run_critique_stage(
        [a], rows=2, cols=2, overlap_frac=0.0, client=_Pipe(), cache=None,
        progress=None, total=2, max_workers=1, run_usage=RunUsage(),
    )
    assert calls == [1]


def test_critique_uses_inventory_pages(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 2)

    def _no_list(_paths):
        raise AssertionError("the run's critique must not reopen files to count")

    monkeypatch.setattr(pl, "list_sheets", _no_list)
    ctx = _run([a], _Pipe(), work=tmp_path / "qc")
    assert _stage(ctx, "critique").status == "COMPLETE"


# --------------------------------------------------------------------------- #
# The record, run.log and the manifest
# --------------------------------------------------------------------------- #


def test_record_is_portable():
    from drawing_analyzer.models import UnreadPage

    page = UnreadPage(source_id="SRC-0002", source_name="B.pdf", page_index=1,
                      page_count=3, reason="page could not be rendered (ValueError)")
    assert page.display_label == "B.pdf (page 2/3)"
    assert page.to_dict() == {
        "source_id": "SRC-0002", "sheet": "B.pdf (page 2/3)", "page_index": 1,
        "page_count": 3, "reason": "page could not be rendered (ValueError)",
    }


def test_events_in_page_order(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 2)
    c = _pdf(tmp_path / "C.pdf", 1)
    _after_inventory(monkeypatch, b.unlink)
    ctx = _run([a, b, c], _Pipe())
    per_page = [(e.event_code, e.fields["sheet"]) for e in ctx.run_journal.events
                if e.event_code in ("SHEET_DIGESTED", "PAGE_UNREAD")]
    assert per_page == [
        ("SHEET_DIGESTED", "A.pdf (page 1/1)"),
        ("PAGE_UNREAD", "B.pdf (page 1/2)"),
        ("PAGE_UNREAD", "B.pdf (page 2/2)"),
        ("SHEET_DIGESTED", "C.pdf (page 1/1)"),
    ]
    (event, _) = _events(ctx, "PAGE_UNREAD")
    assert event.level == "WARNING" and event.fields["source"] == "SRC-0002"
    assert event.fields["reason"] == "the source could not be opened again (FileNotFoundError)"
    run_end = _events(ctx, "RUN_END")[0].fields
    assert (run_end["sheets_total"], run_end["sheets_ok"]) == ("4", "2")


def test_run_log_lists_unread(tmp_path, monkeypatch):
    from drawing_analyzer.run_journal import render_run_log

    a = _pdf(tmp_path / "A.pdf", 1)
    b = _pdf(tmp_path / "B.pdf", 2)
    _after_inventory(monkeypatch, b.unlink)
    log = render_run_log(_run([a, b], _Pipe()))
    sheets = log.split("\nSheets\n", 1)[1].split("\n\n", 1)[0]
    assert "1 sheet(s): 1 ok, 0 failed, 0 from cache; 2 page(s) not read" in sheets
    for label in ("B.pdf (page 1/2)", "B.pdf (page 2/2)"):
        line = next(l for l in sheets.splitlines() if label in l)
        assert "NOT READ" in line and "could not be opened again (FileNotFoundError)" in line


# --------------------------------------------------------------------------- #
# No regression for an unchanged set
# --------------------------------------------------------------------------- #


def test_unchanged_set_is_unchanged(tmp_path):
    a = _pdf(tmp_path / "A.pdf", 2)
    b = _pdf(tmp_path / "B.pdf", 1)
    ctx = _run([a, b], _Pipe())
    headers = [l for l in ctx.combined_text.splitlines() if l.startswith("## Sheet ")]
    assert headers == [
        "## Sheet 1/3: A.pdf (page 1/2)",
        "## Sheet 2/3: A.pdf (page 2/2)",
        "## Sheet 3/3: B.pdf (page 1/1)",
    ]
    assert getattr(ctx, "unread_pages", []) == [] and ctx.errors == []
    assert _events(ctx, "PAGE_UNREAD") == []
    assert ctx.run_journal.final_status == "COMPLETE"


def test_cached_rerun_renders_nothing(tmp_path, monkeypatch):
    a = _pdf(tmp_path / "A.pdf", 2)
    b = _pdf(tmp_path / "B.pdf", 1)
    cache = DigestCache(None, persist=False)
    first = _run([a, b], _Pipe(), cache=cache)
    renders = {"n": 0}
    real = R.render_sheet

    def _counting(*args, **kwargs):
        renders["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(R, "render_sheet", _counting)
    client = _Pipe()
    second = _run([a, b], client, cache=cache)
    assert renders["n"] == 0 and client.digest_calls == 0
    assert second.combined_text == first.combined_text
    assert second.cached_sheet_count == 3
