"""Batch-mode critique tests (Files-API upload reuse + Message Batches, Phase 23C).

Hermetic: a fake client provides ``.beta.files.upload/delete``,
``.beta.messages.batches.create``, ``.messages.batches.retrieve/results/cancel``,
and ``.messages.create`` (the real-time fallback), so the whole submit → poll →
collect path — and every DA-034 cleanup exit — runs without PyMuPDF or the
network. The critique responder returns a real findings block, so a batched read
is parsed by the exact same code a real-time read is.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer.batch_critique import (
    collect_critique_batch,
    submit_critique_batch,
)
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import (
    CONFIDENCE_NOT_ASSESSED_PARTIAL,
    CONFIDENCE_REPRODUCED,
    ImageTile,
    RenderedSheet,
    SheetRef,
)
from tests.fixtures.fake_anthropic import (
    FakeBatchResult,
    FakeBatchResultEnvelope,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
)

OPUS = "claude-opus-4-8"
NOSLEEP = lambda _s: None  # noqa: E731 - tests never wait on the poll
IMAGES_PER_SHEET = 5  # overview + 2x2 tiles


@pytest.fixture(autouse=True)
def _sequential_uploads(monkeypatch):
    # The upload fakes here are simple and not thread-safe; pin the per-sheet
    # upload pool to 1 so id assignment is deterministic.
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeFiles:
    def __init__(self):
        self.uploaded_ids: list[str] = []
        self.deleted: list[str] = []
        self._n = 0

    def upload(self, *, file):
        _name, _data, ctype = file
        assert ctype == "image/png"
        fid = f"file_{self._n}"
        self._n += 1
        self.uploaded_ids.append(fid)
        return _Obj(id=fid)

    def delete(self, file_id):
        self.deleted.append(file_id)


class _FakeBatches:
    def __init__(self, client):
        self._c = client

    def create(self, *, requests, betas=None):
        if self._c.create_raises is not None:
            raise self._c.create_raises
        self._c.create_calls.append({"requests": list(requests), "betas": betas})
        self._c.submitted = list(requests)
        return _Obj(id="batch_crit")

    def retrieve(self, batch_id):
        n = len(self._c.submitted)
        return _Obj(
            processing_status=self._c.status,
            request_counts=_Obj(succeeded=n, errored=0, canceled=0, expired=0, processing=0),
        )

    def cancel(self, batch_id):
        self._c.cancel_calls.append(batch_id)
        if self._c.cancel_raises is not None:
            raise self._c.cancel_raises
        return _Obj(id=batch_id, processing_status="canceling")

    def results(self, batch_id):
        if self._c.results_raises is not None:
            raise self._c.results_raises
        order = self._c.submitted
        if self._c.reverse_results:
            order = list(reversed(order))
        for req in order:
            yield self._c.responder(req)


class _FakeClient:
    def __init__(
        self,
        responder,
        *,
        status="ended",
        reverse_results=False,
        create_raises=None,
        results_raises=None,
        cancel_raises=None,
        inline_responder=None,
    ):
        self.responder = responder
        self.status = status
        self.reverse_results = reverse_results
        self.create_raises = create_raises
        self.results_raises = results_raises
        self.cancel_raises = cancel_raises
        self.inline_responder = inline_responder
        self.create_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self.submitted: list[dict] = []
        self.messages_create_calls: list[dict] = []
        self.files = _FakeFiles()
        batches = _FakeBatches(self)
        self.beta = _Obj(files=self.files, messages=_Obj(batches=batches))
        self.messages = _Obj(batches=batches, create=self._messages_create)

    def _messages_create(self, **kwargs):
        self.messages_create_calls.append(kwargs)
        return (self.inline_responder or _crit_message)(kwargs)


class _FlakyUploadFiles(_FakeFiles):
    """Every upload raises — forces the per-sheet real-time fallback."""

    def upload(self, *, file):
        raise RuntimeError("upload exploded")


class _Fatal404(Exception):
    """A run-fatal Files-API rejection (the /v1/files route not resolving)."""

    status_code = 404


class _DeadRouteFiles(_FakeFiles):
    """Every upload 404s (route down); counts how many upload calls were made."""

    def __init__(self):
        super().__init__()
        self.attempts = 0

    def upload(self, *, file):
        self.attempts += 1
        raise _Fatal404()


# --------------------------------------------------------------------------- #
# Response helpers
# --------------------------------------------------------------------------- #


def _finding(text, *, sev="medium", cat="code"):
    return {"sheet_id": "F-D-01-1", "category": cat, "severity": sev, "text": text}


def _block(findings):
    return "```json\n" + json.dumps({"findings": findings}) + "\n```"


def _crit_message(_kwargs, *, findings=None, in_tok=100, out_tok=20):
    body = _block(findings if findings is not None else [_finding("issue A")])
    return FakeMessage(
        content=[FakeTextBlock(text=body)],
        usage=FakeUsage(input_tokens=in_tok, output_tokens=out_tok),
        stop_reason="end_turn",
    )


def _succeed(req, *, findings=None, in_tok=100, out_tok=20):
    cid = req["custom_id"]
    msg = _crit_message(None, findings=findings, in_tok=in_tok, out_tok=out_tok)
    return FakeBatchResult(
        custom_id=cid, result=FakeBatchResultEnvelope(type="succeeded", message=msg)
    )


def _make_sheet(index: int, *, rows: int = 2, cols: int = 2) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=Path(f"M-10{index}.pdf"),
        page_index=0,
        source_name=f"M-10{index}.pdf",
        page_count=1,
    )
    overview = ImageTile(png_bytes=f"OV-{index}".encode(), width_px=2000,
                         height_px=1500, kind="overview")
    tiles = [
        ImageTile(png_bytes=f"T{index}-{r}{c}".encode(), width_px=2000, height_px=1500,
                  kind="tile", row=r, col=c, label=f"r{r}c{c}")
        for r in range(rows) for c in range(cols)
    ]
    return RenderedSheet(ref=ref, overview=overview, tiles=tiles, page_width_pt=3168,
                         page_height_pt=2448, rows=rows, cols=cols, sheet_text=f"TEXT {index}")


def _run(client, sheets, *, cache=None, runs=2, **collect_kw):
    batch = submit_critique_batch(
        iter(sheets), client=client, cache=cache, model=OPUS, runs=runs,
        total=len(sheets),
    )
    results = collect_critique_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP, **collect_kw
    )
    return batch, results


# --------------------------------------------------------------------------- #
# Reuse + custom-id contract (DA-030)
# --------------------------------------------------------------------------- #


def test_two_custom_ids_per_uncached_sheet():
    client = _FakeClient(_succeed)
    batch, _ = _run(client, [_make_sheet(1), _make_sheet(2)], runs=2)

    ids = [r["custom_id"] for r in client.submitted]
    assert ids == ["sheet__0__r1", "sheet__0__r2", "sheet__1__r1", "sheet__1__r2"]
    # The batch was created once, with the Files-API beta attached.
    assert len(client.create_calls) == 1
    assert client.create_calls[0]["betas"] == ["files-api-2025-04-14"]


def test_one_upload_per_sheet_feeds_both_reads():
    client = _FakeClient(_succeed)
    _run(client, [_make_sheet(1), _make_sheet(2)], runs=2)

    # Each sheet is uploaded ONCE (not once per read): 2 sheets x 5 images.
    assert len(client.files.uploaded_ids) == 2 * IMAGES_PER_SHEET
    # Both reads of a sheet reference the *same* file_ids — real image reuse.
    by_id = {r["custom_id"]: r for r in client.submitted}
    r1_ids = _image_file_ids(by_id["sheet__0__r1"])
    r2_ids = _image_file_ids(by_id["sheet__0__r2"])
    assert r1_ids and r1_ids == r2_ids
    # Sheet 1's ids are disjoint from sheet 0's.
    assert not (set(r1_ids) & set(_image_file_ids(by_id["sheet__1__r1"])))


def _image_file_ids(req):
    content = req["params"]["messages"][0]["content"]
    return [b["source"]["file_id"] for b in content if b.get("type") == "image"]


def test_reads_reference_file_ids_not_base64():
    client = _FakeClient(_succeed)
    _run(client, [_make_sheet(1)], runs=2)
    for req in client.submitted:
        content = req["params"]["messages"][0]["content"]
        images = [b for b in content if b.get("type") == "image"]
        assert len(images) == IMAGES_PER_SHEET
        for b in images:
            assert b["source"]["type"] == "file"
            assert "data" not in b["source"]
        # The CRITIQUE closing instruction rode the shared upload's content
        # (not the digest's) — proof the shared upload was built for the reviewer.
        texts = " ".join(b["text"] for b in content if b.get("type") == "text")
        assert "back-check" in texts.lower() and "findings" in texts.lower()


# --------------------------------------------------------------------------- #
# Merge + usage from actual batch responses
# --------------------------------------------------------------------------- #


def test_collect_merges_reads_and_bills_from_responses():
    # Both reads surface the same finding -> reproduced; usage is summed from the
    # actual batch responses (each read billed 100/20).
    client = _FakeClient(_succeed)
    _batch, results = _run(client, [_make_sheet(1)], runs=2)

    assert len(results) == 1
    ref, res = results[0]
    assert ref.source_name == "M-101.pdf"
    assert res.completed_runs == 2 and res.error is None and not res.cached and not res.rescued
    assert len(res.findings) == 1
    assert res.findings[0].confidence == CONFIDENCE_REPRODUCED
    # Usage reflects the two actual batch responses, not a re-estimate.
    assert res.input_tokens == 200 and res.output_tokens == 40


def test_deterministic_order_independent_of_result_arrival():
    # Results arriving in reverse order must not reorder the page-ordered output.
    client = _FakeClient(_succeed, reverse_results=True)
    _batch, results = _run(client, [_make_sheet(1), _make_sheet(2), _make_sheet(3)], runs=2)
    assert [ref.source_name for ref, _ in results] == [
        "M-101.pdf", "M-102.pdf", "M-103.pdf",
    ]


def test_partial_read_failure_merges_survivor_and_marks_partial():
    # r1 errors, r2 succeeds -> the surviving read's finding ships, marked
    # NOT_ASSESSED_PARTIAL (never REPRODUCED), and the sheet is NOT cached.
    def responder(req):
        if req["custom_id"].endswith("__r1"):
            return FakeBatchResult(
                custom_id=req["custom_id"],
                result=FakeBatchResultEnvelope(
                    type="errored",
                    error=_Obj(error=_Obj(type="api_error", message="boom")),
                ),
            )
        return _succeed(req)

    cache = DigestCache(None, persist=False)
    client = _FakeClient(responder)
    _batch, results = _run(client, [_make_sheet(1)], cache=cache, runs=2)
    _ref, res = results[0]
    assert res.completed_runs == 1 and res.requested_runs == 2
    assert len(res.findings) == 1
    assert res.findings[0].confidence == CONFIDENCE_NOT_ASSESSED_PARTIAL
    # A partial result is never frozen under the full-runs key (DA-008): a second
    # run over the same cache must re-upload and re-submit, not serve a cached hit.
    c2 = _FakeClient(_succeed)
    _run(c2, [_make_sheet(1)], cache=cache, runs=2)
    assert c2.files.uploaded_ids and c2.create_calls


def test_complete_result_is_cached_and_second_run_is_a_hit():
    cache = DigestCache(None, persist=False)
    c1 = _FakeClient(_succeed)
    _run(c1, [_make_sheet(1)], cache=cache, runs=2)
    assert len(c1.create_calls) == 1  # first run submitted a batch

    c2 = _FakeClient(_succeed)
    _batch, results = _run(c2, [_make_sheet(1)], cache=cache, runs=2)
    # Second run: level-2 hit -> no upload, no batch, result served cached.
    assert c2.files.uploaded_ids == [] and c2.create_calls == []
    _ref, res = results[0]
    assert res.cached and res.completed_runs == 2 and len(res.findings) == 1


# --------------------------------------------------------------------------- #
# Files-API cleanup on every exit (DA-034)
# --------------------------------------------------------------------------- #


def test_cleanup_releases_all_files_after_terminal_collect():
    client = _FakeClient(_succeed)
    batch, _ = _run(client, [_make_sheet(1), _make_sheet(2)], runs=2)
    # All uploaded files are deleted once both reads of every sheet are collected.
    assert sorted(client.files.deleted) == sorted(batch.all_file_ids)
    assert len(client.files.deleted) == 2 * IMAGES_PER_SHEET


def test_submit_create_failure_is_nonfatal_deletes_files_and_degrades_batched():
    # DA-034 + I-3: batches.create raising AFTER the uploads landed must delete
    # every uploaded file (no leak) AND degrade only the would-be-batched sheets —
    # NOT re-raise (which would fail the whole critique stage).
    client = _FakeClient(_succeed, create_raises=RuntimeError("batch backend down"))
    batch = submit_critique_batch(
        iter([_make_sheet(1), _make_sheet(2)]), client=client, model=OPUS,
        runs=2, total=2,
    )
    assert batch.batch_id is None
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)
    assert len(client.files.deleted) == 2 * IMAGES_PER_SHEET
    results = collect_critique_batch(batch, client=client, sleep=NOSLEEP)
    assert len(results) == 2
    for _ref, res in results:
        assert res.findings == [] and res.error and "submit failed" in res.error


def test_submit_create_failure_preserves_cache_hit_and_rescued_results():
    # I-3: a create failure degrades ONLY the would-be-batched sheet; the free
    # cache-hit findings and the already-PAID real-time fallback findings on the
    # other slots survive.
    cache = DigestCache(None, persist=False)
    _run(_FakeClient(_succeed), [_make_sheet(1)], cache=cache, runs=2)  # warm sheet 1

    class _Sheet2BadUpload(_FakeFiles):
        def upload(self, *, file):
            _n, data, _c = file
            if data.startswith(b"OV-2") or data.startswith(b"T2-"):
                raise RuntimeError("sheet 2 upload down")
            return super().upload(file=file)

    client = _FakeClient(_succeed, create_raises=RuntimeError("create 500"))
    client.files = _Sheet2BadUpload()
    client.beta.files = client.files
    batch = submit_critique_batch(
        iter([_make_sheet(1), _make_sheet(2), _make_sheet(3)]),
        client=client, cache=cache, model=OPUS, runs=2, total=3,
    )
    by_name = {ref.source_name: res for ref, res in
               collect_critique_batch(batch, client=client, cache=cache, sleep=NOSLEEP)}
    assert by_name["M-101.pdf"].cached and by_name["M-101.pdf"].findings      # free hit kept
    assert by_name["M-102.pdf"].rescued and by_name["M-102.pdf"].findings     # paid fallback kept
    assert by_name["M-103.pdf"].findings == []                                # only C degraded
    assert "submit failed" in by_name["M-103.pdf"].error
    assert client.files.deleted                                               # C's uploads freed


class _GetBoomCache:
    """Cache whose ``get`` raises on the Nth call — an unexpected mid-submit error."""

    def __init__(self, boom_on_call):
        self.calls = 0
        self.boom_on_call = boom_on_call

    def get(self, key):
        self.calls += 1
        if self.calls == self.boom_on_call:
            raise RuntimeError("cache read exploded")
        return None

    def put(self, key, value):
        pass


def test_unexpected_loop_error_frees_orphaned_uploads_before_propagating():
    # DA-034: an unexpected error in the submit loop (here a cache-read failure on
    # sheet 2) AFTER sheet 1 already uploaded must delete sheet 1's orphaned uploads
    # — no batch will ever reference them — then propagate.
    client = _FakeClient(_succeed)
    cache = _GetBoomCache(boom_on_call=2)  # sheet 1 miss→uploads; sheet 2 get raises
    with pytest.raises(RuntimeError, match="cache read exploded"):
        submit_critique_batch(
            iter([_make_sheet(1), _make_sheet(2)]), client=client, cache=cache,
            model=OPUS, runs=2, total=2,
        )
    assert client.files.deleted == client.files.uploaded_ids
    assert len(client.files.deleted) == IMAGES_PER_SHEET


def test_collect_results_error_releases_files_without_leaking():
    # results() raising while collecting a *terminal* batch must not leak files:
    # the batch is already ended, so its files are released. Additive/non-fatal —
    # the sheets degrade rather than the collect call raising.
    client = _FakeClient(_succeed, results_raises=RuntimeError("results exploded"))
    batch, results = _run(client, [_make_sheet(1)], runs=2)
    assert sorted(client.files.deleted) == sorted(batch.all_file_ids)
    assert len(client.files.deleted) == IMAGES_PER_SHEET
    _ref, res = results[0]
    assert res.error and res.findings == []


def test_non_terminal_cancel_succeeds_releases_files():
    # A batch that never terminates is canceled and its files released.
    client = _FakeClient(_succeed, status="in_progress")
    batch = submit_critique_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, runs=2, total=1,
    )
    results = collect_critique_batch(
        batch, client=client, sleep=NOSLEEP, max_elapsed_seconds=-1,
    )
    assert client.cancel_calls == ["batch_crit"]
    assert sorted(client.files.deleted) == sorted(batch.all_file_ids)
    _ref, res = results[0]
    assert "not collected" in res.error


def test_non_terminal_cancel_fails_retains_files():
    # If the abandoned batch cannot be canceled it may still be running, so its
    # files are RETAINED (safe detach) rather than deleted out from under it.
    client = _FakeClient(
        _succeed, status="in_progress", cancel_raises=RuntimeError("cancel refused")
    )
    batch = submit_critique_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, runs=2, total=1,
    )
    results = collect_critique_batch(
        batch, client=client, sleep=NOSLEEP, max_elapsed_seconds=-1,
    )
    assert client.cancel_calls == ["batch_crit"]
    assert client.files.deleted == []          # retained
    assert batch.all_file_ids                   # there were files to retain
    _ref, res = results[0]
    assert "may still be running" in res.error


# --------------------------------------------------------------------------- #
# Upload-failure fallback (per-sheet, non-fatal)
# --------------------------------------------------------------------------- #


def test_upload_failure_falls_back_to_real_time_and_marks_rescued():
    client = _FakeClient(_succeed)
    client.files = _FlakyUploadFiles()
    client.beta.files = client.files
    batch = submit_critique_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, runs=2, total=1,
    )
    # No batch item was created (the sheet was served inline instead).
    assert batch.batch_id is None and client.create_calls == []
    # Two real-time messages.create calls (the self-consistency reads).
    assert len(client.messages_create_calls) == 2
    results = collect_critique_batch(batch, client=client, sleep=NOSLEEP)
    _ref, res = results[0]
    assert res.rescued and res.completed_runs == 2 and len(res.findings) == 1


def test_upload_failure_on_one_sheet_still_batches_the_other():
    # A mixed run: sheet 0 uploads fine (batched), sheet 1's upload fails (inline).
    class _OneBadUpload(_FakeFiles):
        def upload(self, *, file):
            _name, data, _ctype = file
            if data.startswith(b"OV-2") or data.startswith(b"T2-"):
                raise RuntimeError("sheet 2 upload down")
            return super().upload(file=file)

    client = _FakeClient(_succeed)
    client.files = _OneBadUpload()
    client.beta.files = client.files
    batch, results = _run(client, [_make_sheet(1), _make_sheet(2)], runs=2)
    # Only sheet 0's two reads were batched.
    assert [r["custom_id"] for r in client.submitted] == ["sheet__0__r1", "sheet__0__r2"]
    # Sheet 1 was served inline (2 real-time reads) and is marked rescued.
    assert len(client.messages_create_calls) == 2
    by_name = {ref.source_name: res for ref, res in results}
    assert not by_name["M-101.pdf"].rescued
    assert by_name["M-102.pdf"].rescued
    # Both sheets still produce findings; page order is preserved.
    assert [ref.source_name for ref, _ in results] == ["M-101.pdf", "M-102.pdf"]


def test_dead_files_route_trips_breaker_and_stops_uploading():
    # A whole-run Files-API outage (consecutive 404s) must trip the circuit
    # breaker: after MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES sheets, the rest skip
    # the doomed upload and go straight to the real-time fallback — not one dead
    # upload round-trip per sheet.
    from drawing_analyzer.batch_digest import MAX_CONSECUTIVE_FATAL_UPLOAD_FAILURES as K

    client = _FakeClient(_succeed)
    client.files = _DeadRouteFiles()
    client.beta.files = client.files
    n_sheets = K + 3
    batch = submit_critique_batch(
        iter([_make_sheet(i) for i in range(n_sheets)]),
        client=client, model=OPUS, runs=2, total=n_sheets,
    )
    # Nothing was batched; every sheet was critiqued real-time.
    assert batch.batch_id is None and client.create_calls == []
    # Only the first K sheets attempted an upload; the breaker stopped the rest.
    assert client.files.attempts == K
    # Every sheet still got a rescued real-time critique (2 reads each).
    results = collect_critique_batch(batch, client=client, sleep=NOSLEEP)
    assert len(results) == n_sheets
    assert all(res.rescued and res.completed_runs == 2 for _ref, res in results)
    assert len(client.messages_create_calls) == 2 * n_sheets


# --------------------------------------------------------------------------- #
# Pipeline wiring: the critique stage records BATCH usage in a use_batch run
# --------------------------------------------------------------------------- #

try:
    import pymupdf  # noqa: F401
    _HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover - env-dependent
    _HAVE_PYMUPDF = False


@pytest.mark.skipif(not _HAVE_PYMUPDF, reason="needs PyMuPDF to render a real sheet")
def test_pipeline_critique_stage_records_transport_batch(tmp_path):
    # End-to-end through the pipeline stage: a use_batch critique run routes the
    # two reads through ONE Message Batch and prices them BATCH (§15.6 / DA-030).
    from drawing_analyzer.models import RunUsage
    from drawing_analyzer.pipeline import _run_critique_stage

    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((80, 120), "VAV-3 SERVES ROOM 120")
    pdf = tmp_path / "M-101.pdf"
    doc.save(str(pdf))
    doc.close()

    client = _FakeClient(_succeed)
    run_usage = RunUsage()
    findings, _claims, degraded = _run_critique_stage(
        [pdf], rows=2, cols=2, overlap_frac=0.1, client=client, cache=None,
        progress=None, total=1, max_workers=1, run_usage=run_usage, use_batch=True,
    )
    assert degraded == []                      # a clean batch run degrades nothing
    # Both reads rode one batch off a single shared upload.
    assert len(client.create_calls) == 1
    assert [r["custom_id"] for r in client.submitted] == ["sheet__0__r1", "sheet__0__r2"]
    assert client.files.uploaded_ids  # the sheet uploaded once
    # The critique usage is recorded at the BATCH rate — the discount is real.
    crit = [r for r in run_usage.records if r.stage_family == "critique"]
    assert crit and all(r.transport == "BATCH" for r in crit)
    assert findings  # the batched reads produced a finding
