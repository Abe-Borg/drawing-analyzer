"""Batch-mode drawing digest tests (Files-API upload + Message Batches).

Hermetic: a fake client provides ``.beta.files.upload/delete``,
``.beta.messages.batches.create``, and ``.messages.batches.retrieve/results``,
so the whole submit → poll → collect path runs without PyMuPDF or the network.
One end-to-end pipeline test renders a synthetic PDF and is skipped when PyMuPDF
is absent.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from drawing_analyzer import batch_digest, diagnostics
from drawing_analyzer.batch_digest import collect_drawing_batch, submit_drawing_batch
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.file_upload import FILES_API_BETA, upload_sheet_images
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from tests.fixtures.fake_anthropic import (
    FakeBatchResult,
    FakeBatchResultEnvelope,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    batch_errored_result,
)

OPUS = "claude-opus-4-8"
NOSLEEP = lambda _s: None  # noqa: E731 - tests never actually wait on the poll


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
        name, data, ctype = file
        assert ctype == "image/png"
        fid = f"file_{self._n}"
        self._n += 1
        self.uploaded_ids.append(fid)
        return _Obj(id=fid)

    def delete(self, file_id):
        self.deleted.append(file_id)


class _Transient503(Exception):
    """A Files-API ``503 overloaded_error`` lookalike (carries ``status_code``).

    ``_is_transient_error`` classifies by the ``status_code`` attribute the SDK
    errors expose, so this triggers the upload retry path; a plain
    ``RuntimeError`` (used elsewhere) is treated as permanent and never retried.
    """

    status_code = 503

    def __init__(self, message: str = "File storage is temporarily unavailable."):
        super().__init__(message)
        self.message = message


class _FlakyFiles(_FakeFiles):
    """Raise a transient 503 on the first ``fail_times`` upload calls, then OK."""

    def __init__(self, fail_times: int):
        super().__init__()
        self.fail_times = fail_times
        self.attempts = 0

    def upload(self, *, file):
        if self.attempts < self.fail_times:
            self.attempts += 1
            raise _Transient503()
        return super().upload(file=file)


class _FakeBatches:
    """Serves both the beta (create) and sync (retrieve/results) namespaces."""

    def __init__(self, client):
        self._c = client

    def create(self, *, requests, betas=None):
        self._c.create_calls.append({"requests": list(requests), "betas": betas})
        self._c.submitted = list(requests)
        return _Obj(id="batch_abc")

    def retrieve(self, batch_id):
        self._c.retrieve_calls.append(batch_id)
        n = len(self._c.submitted)
        return _Obj(
            processing_status=self._c.status,
            request_counts=_Obj(
                succeeded=n, errored=0, canceled=0, expired=0, processing=0
            ),
        )

    def results(self, batch_id):
        order = self._c.submitted
        if self._c.reverse_results:
            order = list(reversed(order))
        for req in order:
            yield self._c.responder(req)


class _FakeClient:
    def __init__(self, responder, *, status="ended", reverse_results=False):
        self.responder = responder
        self.status = status
        self.reverse_results = reverse_results
        self.create_calls: list[dict] = []
        self.retrieve_calls: list[str] = []
        self.submitted: list[dict] = []
        self.files = _FakeFiles()
        batches = _FakeBatches(self)
        self.beta = _Obj(files=self.files, messages=_Obj(batches=batches))
        self.messages = _Obj(batches=batches)


def _succeed(req, *, in_tok=100, out_tok=20):
    cid = req["custom_id"]
    msg = FakeMessage(
        content=[FakeTextBlock(text=f"digest body for {cid}")],
        usage=FakeUsage(input_tokens=in_tok, output_tokens=out_tok),
        stop_reason="end_turn",
    )
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
    overview = ImageTile(
        png_bytes=f"OVERVIEW-{index}".encode(),
        width_px=2000,
        height_px=1500,
        kind="overview",
    )
    tiles = [
        ImageTile(
            png_bytes=f"T{index}-{r}{c}".encode(),
            width_px=2000,
            height_px=1500,
            kind="tile",
            row=r,
            col=c,
            label=f"r{r}c{c}",
        )
        for r in range(rows)
        for c in range(cols)
    ]
    return RenderedSheet(
        ref=ref,
        overview=overview,
        tiles=tiles,
        page_width_pt=3168,
        page_height_pt=2448,
        rows=rows,
        cols=cols,
    )


def _run_batch(client, sheets, *, cache=None):
    batch = submit_drawing_batch(
        iter(sheets), client=client, model=OPUS, cache=cache, total=len(sheets)
    )
    return batch, collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP
    )


# --------------------------------------------------------------------------- #
# Files-API upload helper
# --------------------------------------------------------------------------- #


def test_upload_sheet_images_uses_file_ids_not_base64():
    client = _FakeClient(_succeed)
    sheet = _make_sheet(1, rows=2, cols=2)  # overview + 4 tiles = 5 images

    up = upload_sheet_images(client, sheet)

    images = [b for b in up.content if b["type"] == "image"]
    assert len(images) == 5
    # Every image is a file_id reference — no inline base64 in the request body.
    for blk in images:
        assert blk["source"]["type"] == "file"
        assert "data" not in blk["source"]
        assert blk["source"]["file_id"].startswith("file_")
    assert len(up.file_ids) == 5
    # The framing + per-tile labels + task instruction are preserved.
    texts = " ".join(b["text"] for b in up.content if b["type"] == "text")
    assert "OVERVIEW" in texts and "Tile r1c1" in texts and "digest" in texts.lower()


def test_upload_failure_cleans_up_partial_upload():
    class _Boom(_FakeFiles):
        def upload(self, *, file):
            if len(self.uploaded_ids) >= 2:
                raise RuntimeError("upload exploded")
            return super().upload(file=file)

    client = _FakeClient(_succeed)
    client.files = _Boom()
    client.beta.files = client.files

    with pytest.raises(RuntimeError, match="upload exploded"):
        upload_sheet_images(client, _make_sheet(1))
    # The two images uploaded before the failure are deleted — no leak.
    assert client.files.deleted == ["file_0", "file_1"]


def test_upload_retries_transient_503_then_succeeds():
    # The first image 503s twice, then uploads — the exact Files-API
    # "temporarily unavailable" wave that previously failed the whole sheet.
    slept: list[float] = []
    client = _FakeClient(_succeed)
    client.files = _FlakyFiles(fail_times=2)
    client.beta.files = client.files

    up = upload_sheet_images(
        client, _make_sheet(1, rows=2, cols=2),  # overview + 4 tiles = 5 images
        max_retries=3, sleep=slept.append,
    )

    # All five images land despite the transient blips, and the backoff grew
    # exponentially between attempts (2s, 4s) before the retry succeeded.
    assert len(up.file_ids) == 5
    assert slept == [2.0, 4.0]
    assert client.files.deleted == []  # nothing discarded — the sheet completed


def test_upload_retries_exhausted_then_raises_and_cleans_up():
    # First image 503s forever; with max_retries=2 that is 3 attempts then raise.
    slept: list[float] = []
    client = _FakeClient(_succeed)
    client.files = _FlakyFiles(fail_times=99)
    client.beta.files = client.files

    with pytest.raises(_Transient503):
        upload_sheet_images(client, _make_sheet(1), max_retries=2, sleep=slept.append)
    assert slept == [2.0, 4.0]  # two backoffs, then gave up
    # The first image never uploaded, so there is nothing to clean up.
    assert client.files.deleted == []


def test_upload_does_not_retry_permanent_error():
    # A non-transient error (no transient status / connection class) must fail
    # fast — never sleep, never retry — so a genuine 4xx ends the sheet at once.
    slept: list[float] = []

    class _PermanentBoom(_FakeFiles):
        def upload(self, *, file):
            raise RuntimeError("bad request")

    client = _FakeClient(_succeed)
    client.files = _PermanentBoom()
    client.beta.files = client.files

    with pytest.raises(RuntimeError, match="bad request"):
        upload_sheet_images(client, _make_sheet(1), max_retries=5, sleep=slept.append)
    assert slept == []  # never retried


def test_upload_does_not_retry_ambiguous_timeout():
    # A lost-response timeout is ambiguous: the server may have already stored
    # the file. Re-issuing as a fresh upload would orphan that first id (it never
    # lands in file_ids, so neither cleanup path can delete it), so the app-level
    # loop retries transient *status* rejections only — connection/timeout
    # classes are left to the SDK's idempotent internal retries.
    slept: list[float] = []

    class APITimeoutError(Exception):  # name matches the SDK's timeout class
        pass

    class _TimeoutFiles(_FakeFiles):
        def upload(self, *, file):
            raise APITimeoutError("response lost")

    client = _FakeClient(_succeed)
    client.files = _TimeoutFiles()
    client.beta.files = client.files

    with pytest.raises(APITimeoutError):
        upload_sheet_images(client, _make_sheet(1), max_retries=5, sleep=slept.append)
    assert slept == []  # ambiguous timeout is not app-retried


def test_upload_reports_per_image_progress():
    # A sheet's multi-image upload is otherwise a silent, tens-of-seconds stall;
    # ``on_image`` lets a GUI keep its status line alive, one tick per image.
    client = _FakeClient(_succeed)
    events: list[tuple[int, int, bool]] = []
    up = upload_sheet_images(
        client,
        _make_sheet(1, rows=2, cols=2),  # overview + 4 tiles = 5 images
        on_image=lambda pos, total, retrying: events.append((pos, total, retrying)),
    )
    assert len(up.file_ids) == 5
    # One success tick per image, in order, with the running 1..5 of 5 counter.
    assert events == [(1, 5, False), (2, 5, False), (3, 5, False), (4, 5, False), (5, 5, False)]


def test_upload_progress_surfaces_transient_retry():
    # The first image 503s twice before landing; the retry wave is surfaced
    # (retrying=True) so the status line shows motion rather than freezing.
    client = _FakeClient(_succeed)
    client.files = _FlakyFiles(fail_times=2)
    client.beta.files = client.files
    events: list[tuple[int, bool]] = []
    up = upload_sheet_images(
        client,
        _make_sheet(1, rows=2, cols=2),
        max_retries=3,
        sleep=lambda _s: None,
        on_image=lambda pos, total, retrying: events.append((pos, retrying)),
    )
    assert len(up.file_ids) == 5
    assert events.count((1, True)) == 2          # two retry notices for image #1
    assert [retrying for _, retrying in events].count(False) == 5  # five successes


# --------------------------------------------------------------------------- #
# submit + collect
# --------------------------------------------------------------------------- #


def test_submit_emits_per_image_status_text():
    client = _FakeClient(_succeed)
    statuses: list[str] = []
    submit_drawing_batch(
        iter([_make_sheet(1, rows=2, cols=2)]),  # 5 images
        client=client,
        model=OPUS,
        total=1,
        on_status=statuses.append,
    )
    # One status-line update per image, naming the image counter and the sheet.
    assert len(statuses) == 5
    assert all("Uploading image" in s and "/5" in s for s in statuses)
    assert all("M-101.pdf" in s for s in statuses)


def test_batch_happy_path_parses_all_sheets():
    client = _FakeClient(_succeed)
    sheets = [_make_sheet(i) for i in (1, 2, 3)]

    batch, digests = _run_batch(client, sheets)

    assert len(digests) == 3
    assert all(d.ok for d in digests)
    assert [d.ref.source_name for d in digests] == ["M-101.pdf", "M-102.pdf", "M-103.pdf"]
    assert digests[0].text == "digest body for sheet__0"
    assert digests[0].input_tokens == 100 and digests[0].output_tokens == 20
    assert digests[0].image_token_estimate > 0
    # One batch, created on the beta namespace with the Files-API beta header.
    assert len(client.create_calls) == 1
    assert client.create_calls[0]["betas"] == [FILES_API_BETA]
    # 3 sheets × 5 images uploaded, all deleted after a successful collect.
    assert len(client.files.uploaded_ids) == 15
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_batch_request_shape_matches_digest():
    client = _FakeClient(_succeed)
    _run_batch(client, [_make_sheet(1)])

    params = client.create_calls[0]["requests"][0]["params"]
    assert params["model"] == OPUS
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "high"}
    assert params["messages"][0]["role"] == "user"
    # Body carries file-id images, never base64.
    images = [b for b in params["messages"][0]["content"] if b["type"] == "image"]
    assert images and all(b["source"]["type"] == "file" for b in images)


def test_batch_page_order_independent_of_result_order():
    client = _FakeClient(_succeed, reverse_results=True)  # results stream reversed
    sheets = [_make_sheet(i) for i in (1, 2, 3)]

    _, digests = _run_batch(client, sheets)

    # Still assembled in page order despite out-of-order results.
    assert [d.ref.source_name for d in digests] == ["M-101.pdf", "M-102.pdf", "M-103.pdf"]


def test_batch_errored_item_fails_only_that_sheet():
    def responder(req):
        if req["custom_id"] == "sheet__1":
            return batch_errored_result(
                custom_id="sheet__1", error_message="overloaded"
            )
        return _succeed(req)

    client = _FakeClient(responder)
    _, digests = _run_batch(client, [_make_sheet(i) for i in (1, 2, 3)])

    assert digests[0].ok and digests[2].ok
    assert not digests[1].ok
    assert "overloaded" in digests[1].error
    # Files are still cleaned up even with a mixed-result batch.
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_batch_missing_result_marks_sheet_failed():
    # Responder drops one custom_id entirely (no envelope returned for it).
    def responder(req):
        return _succeed(req) if req["custom_id"] != "sheet__1" else None

    client = _FakeClient(responder)

    class _Filtering(_FakeBatches):
        def results(self, batch_id):
            for req in self._c.submitted:
                r = self._c.responder(req)
                if r is not None:
                    yield r

    batches = _Filtering(client)
    client.beta.messages.batches = batches
    client.messages.batches = batches

    batch = submit_drawing_batch(
        iter([_make_sheet(i) for i in (1, 2)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(batch, client=client, sleep=NOSLEEP)

    assert digests[0].ok
    assert not digests[1].ok and "no result" in digests[1].error


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #


def test_cache_hit_skips_upload_and_batch_item():
    cache = DigestCache(None, persist=False)
    sheets = [_make_sheet(i) for i in (1, 2)]

    # First run digests both and writes the cache.
    client1 = _FakeClient(_succeed)
    _run_batch(client1, sheets, cache=cache)
    assert len(client1.create_calls) == 1
    assert len(client1.submitted) == 2

    # Second, identical run: both served from cache — no upload, no batch.
    client2 = _FakeClient(_succeed)
    _, digests = _run_batch(client2, sheets, cache=cache)
    assert [d.cached for d in digests] == [True, True]
    assert client2.create_calls == []  # nothing submitted
    assert client2.files.uploaded_ids == []  # nothing uploaded
    assert all(d.ok for d in digests)


def test_partial_cache_only_submits_the_miss():
    cache = DigestCache(None, persist=False)
    sheets = [_make_sheet(i) for i in (1, 2)]

    # Warm the cache for sheet 1 only by running it alone first.
    _run_batch(_FakeClient(_succeed), [sheets[0]], cache=cache)

    client = _FakeClient(_succeed)
    _, digests = _run_batch(client, sheets, cache=cache)

    assert digests[0].cached is True
    assert digests[1].cached is False and digests[1].ok
    # Only sheet 2 was uploaded + submitted.
    assert len(client.submitted) == 1
    assert client.submitted[0]["custom_id"] == "sheet__1"
    assert len(client.files.uploaded_ids) == 5  # one sheet's worth of images


# --------------------------------------------------------------------------- #
# Per-run focus (batch path)
# --------------------------------------------------------------------------- #

FOCUS = "the rooms, and what types of plumbing fixtures each has"


def test_batch_focus_rides_on_system_prompt_only():
    from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT

    plain = _FakeClient(_succeed)
    submit_drawing_batch(iter([_make_sheet(1)]), client=plain, model=OPUS, total=1)
    focused = _FakeClient(_succeed)
    submit_drawing_batch(
        iter([_make_sheet(1)]), client=focused, model=OPUS, total=1, focus=FOCUS
    )

    p_params = plain.create_calls[0]["requests"][0]["params"]
    f_params = focused.create_calls[0]["requests"][0]["params"]
    assert p_params["system"] == DIGEST_SYSTEM_PROMPT
    assert f_params["system"].startswith(DIGEST_SYSTEM_PROMPT)
    assert FOCUS in f_params["system"]
    # The user content (and so the uploaded images) is identical either way.
    assert p_params["messages"] == f_params["messages"]


def test_batch_focus_is_cache_isolated():
    cache = DigestCache(None, persist=False)
    sheets = [_make_sheet(1)]

    # Warm the cache with a no-focus run.
    _run_batch(_FakeClient(_succeed), sheets, cache=cache)

    # A focused run must not be served the no-focus digest — it re-submits.
    client = _FakeClient(_succeed)
    batch = submit_drawing_batch(
        iter(sheets), client=client, model=OPUS, cache=cache, total=1, focus=FOCUS
    )
    digests = collect_drawing_batch(batch, client=client, cache=cache, sleep=NOSLEEP)
    assert digests[0].cached is False and digests[0].ok
    assert len(client.submitted) == 1

    # Same focus again: now served from the (focus-keyed) cache.
    client2 = _FakeClient(_succeed)
    batch2 = submit_drawing_batch(
        iter(sheets), client=client2, model=OPUS, cache=cache, total=1, focus=FOCUS
    )
    digests2 = collect_drawing_batch(batch2, client=client2, cache=cache, sleep=NOSLEEP)
    assert digests2[0].cached is True
    assert client2.create_calls == []

    # And the original no-focus entry is still intact.
    client3 = _FakeClient(_succeed)
    batch3 = submit_drawing_batch(
        iter(sheets), client=client3, model=OPUS, cache=cache, total=1
    )
    digests3 = collect_drawing_batch(batch3, client=client3, cache=cache, sleep=NOSLEEP)
    assert digests3[0].cached is True


# --------------------------------------------------------------------------- #
# Upload-failure handling at submit time
# --------------------------------------------------------------------------- #


def test_submit_upload_failure_captures_sheet_and_continues():
    state = {"n": 0}
    lock = threading.Lock()

    class _OneBadUpload(_FakeFiles):
        def upload(self, *, file):
            with lock:
                state["n"] += 1
                # Fail the first image of the SECOND sheet (6th upload overall).
                fail = state["n"] == 6
            if fail:
                raise RuntimeError("boom upload")
            return super().upload(file=file)

    client = _FakeClient(_succeed)
    client.files = _OneBadUpload()
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(1), _make_sheet(2)])

    assert digests[0].ok  # first sheet fine
    assert not digests[1].ok and "upload failed" in digests[1].error
    # Only the good sheet became a batch item.
    assert len(client.submitted) == 1


class _RouteLevel404(Exception):
    """A Files-API ``404 not_found_error`` lookalike (route/credential-level).

    Carries ``status_code`` like the SDK's ``NotFoundError``; permanent, so the
    upload helper fails the sheet on the first image without retrying.
    """

    status_code = 404

    def __init__(self, message: str = "Not found"):
        super().__init__(message)
        self.message = message


class _CountingBrokenFiles(_FakeFiles):
    """Every upload raises ``exc_type``; counts the attempts."""

    def __init__(self, exc_type=_RouteLevel404):
        super().__init__()
        self.exc_type = exc_type
        self.attempts = 0

    def upload(self, *, file):
        self.attempts += 1
        raise self.exc_type()


def test_submit_stops_uploading_after_consecutive_route_level_failures():
    # A 404 on /v1/files is credential/route-level: every upload in the run is
    # doomed identically. After three sheets fail the same way, the remaining
    # sheets must be marked skipped without further API calls (a real 33-sheet
    # run previously spent minutes failing every sheet one request at a time).
    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles()
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(i) for i in range(6)])

    # Each tripping sheet failed on its first image: exactly 3 attempts total.
    assert client.files.attempts == 3
    assert len(digests) == 6 and not any(d.ok for d in digests)
    for d in digests[:3]:
        assert "upload failed" in d.error
    for d in digests[3:]:
        assert "upload skipped" in d.error
        assert "3 consecutive HTTP 404" in d.error
    # Nothing was submitted — and no batch exists to poll.
    assert client.submitted == [] and client.create_calls == []


def test_submit_404_error_carries_actionable_hint():
    # "HTTP 404: Not found" alone says nothing about where to look; the sheet
    # error must name the realistic causes (base-URL/proxy override, beta
    # header, SDK install) so the operator can act without reading source.
    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles()
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(1)])

    assert not digests[0].ok
    assert "ANTHROPIC_BASE_URL" in digests[0].error
    assert "files-api-2025-04-14" in digests[0].error


def test_submit_payload_4xx_does_not_trip_the_breaker():
    # A 400 is payload-shaped (one bad image), not run-fatal: every sheet must
    # still get its own upload attempt even when several fail in a row.
    class _BadRequest(Exception):
        status_code = 400

        def __init__(self):
            super().__init__("invalid image")
            self.message = "invalid image"

    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles(exc_type=_BadRequest)
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(i) for i in range(5)])

    assert client.files.attempts == 5  # one attempt per sheet, no skipping
    assert all("upload failed" in d.error for d in digests)
    assert not any("upload skipped" in d.error for d in digests)


def test_submit_breaker_resets_on_successful_upload():
    # The breaker's contract is CONSECUTIVE failures. A successful upload in
    # between proves the Files API is reachable, so 404 / ok / 404 / ok / 404
    # must NOT trip it — every sheet still gets its own attempt.
    class _IntermittentFiles(_FakeFiles):
        """404 on chosen attempt numbers (1-based); succeed otherwise."""

        def __init__(self, failing_attempts: set[int]):
            super().__init__()
            self.failing_attempts = failing_attempts
            self.attempts = 0

        def upload(self, *, file):
            self.attempts += 1
            if self.attempts in self.failing_attempts:
                raise _RouteLevel404()
            return super().upload(file=file)

    client = _FakeClient(_succeed)
    # 2x2-grid sheets upload 5 images each; a 404 kills a sheet on its first
    # image. Failing attempts 1/7/13 fails sheets 0/2/4 and lets 1/3/5 land.
    client.files = _IntermittentFiles({1, 7, 13})
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(i) for i in range(6)])

    assert [d.ok for d in digests] == [False, True, False, True, False, True]
    assert not any(d.error and "upload skipped" in d.error for d in digests)
    assert len(client.submitted) == 3  # every successful sheet became an item


def test_submit_breaker_still_serves_cache_hits(tmp_path):
    # With uploads disabled, a sheet whose digest is already cached must still
    # resolve from the cache — the breaker only stops Files-API calls.
    cache = DigestCache(tmp_path / "cache.json")
    warm_client = _FakeClient(_succeed)
    _run_batch(warm_client, [_make_sheet(9)], cache=cache)  # seed sheet 9

    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles()
    client.beta.files = client.files

    # Three doomed sheets trip the breaker; the cached sheet follows.
    _, digests = _run_batch(
        client, [_make_sheet(0), _make_sheet(1), _make_sheet(2), _make_sheet(9)],
        cache=cache,
    )

    assert client.files.attempts == 3
    assert [d.ok for d in digests] == [False, False, False, True]
    assert digests[3].cached


# --------------------------------------------------------------------------- #
# Follow-up batch for retryable per-item failures
# --------------------------------------------------------------------------- #


def _flaky_then_ok(first_failures: dict[str, FakeBatchResult]):
    """Responder serving ``first_failures`` once per custom_id, then success.

    The fake batch ``results()`` iterates whatever the LAST ``create`` call
    submitted, so this naturally models a first round with failures followed
    by a follow-up round that succeeds.
    """
    served: set[str] = set()

    def responder(req):
        cid = req["custom_id"]
        if cid in first_failures and cid not in served:
            served.add(cid)
            return first_failures[cid]
        return _succeed(req)

    return responder


def test_collect_resubmits_server_errored_items_in_followup_batch():
    # An api_error/overloaded_error batch item is a server blip ("safe to
    # retry" per the Batches docs): one follow-up batch reusing the same
    # uploaded file_ids must recover it, and the files must only be deleted
    # after that round (the retry items still reference them).
    client = _FakeClient(
        _flaky_then_ok(
            {"sheet__0": batch_errored_result("sheet__0", error_message="Internal Server Error")}
        )
    )
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert all(d.ok for d in digests)
    # Exactly one follow-up round, containing only the failed item, byte-same params.
    assert len(client.create_calls) == 2
    retry_reqs = client.create_calls[1]["requests"]
    assert [r["custom_id"] for r in retry_reqs] == ["sheet__0"]
    first_params = next(
        r["params"] for r in client.create_calls[0]["requests"]
        if r["custom_id"] == "sheet__0"
    )
    assert retry_reqs[0]["params"] == first_params
    assert client.create_calls[1]["betas"] == [FILES_API_BETA]
    # Every uploaded image was still released exactly once, after the retry.
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_collect_retries_empty_max_tokens_digest_with_raised_cap():
    # A "succeeded" item whose digest is EMPTY at stop_reason=max_tokens means
    # adaptive thinking consumed the whole output budget. The follow-up round
    # must resubmit it with the cap doubled so the digest has room to land.
    empty = FakeBatchResult(
        custom_id="sheet__0",
        result=FakeBatchResultEnvelope(
            type="succeeded",
            message=FakeMessage(content=[], stop_reason="max_tokens"),
        ),
    )
    client = _FakeClient(_flaky_then_ok({"sheet__0": empty}))
    batch = submit_drawing_batch(
        iter([_make_sheet(0)]), client=client, model=OPUS, total=1
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert digests[0].ok
    first_cap = client.create_calls[0]["requests"][0]["params"]["max_tokens"]
    retry_cap = client.create_calls[1]["requests"][0]["params"]["max_tokens"]
    assert retry_cap == min(first_cap * 2, batch_digest.MAX_TOKENS_RETRY_CEILING)


def test_collect_does_not_resubmit_permanently_rejected_items():
    # An invalid_request_error item would fail identically on resubmission —
    # no follow-up batch may be created for it, and its error must stand.
    bad_request = type(
        "FakeError", (), {"message": "prompt too long", "type": "invalid_request_error"}
    )()
    always_bad = FakeBatchResult(
        custom_id="sheet__0",
        result=FakeBatchResultEnvelope(type="errored", error=bad_request),
    )

    client = _FakeClient(
        lambda req: always_bad if req["custom_id"] == "sheet__0" else _succeed(req)
    )
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert not digests[0].ok and "prompt too long" in digests[0].error
    assert digests[1].ok
    assert len(client.create_calls) == 1  # no follow-up round
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_followup_round_shares_the_collect_elapsed_budget(monkeypatch):
    # The caller's max_elapsed_seconds bounds the WHOLE collect. When the
    # primary poll drains it, the follow-up round must be skipped (no second
    # create, no restarted clock) and the files still released — instead of
    # blocking for up to another full budget.
    client = _FakeClient(
        _flaky_then_ok(
            {"sheet__0": batch_errored_result("sheet__0", error_message="Internal Server Error")}
        )
    )
    batch = submit_drawing_batch(
        iter([_make_sheet(0)]), client=client, model=OPUS, total=1
    )

    clock = {"now": 0.0}

    def fake_monotonic():
        clock["now"] += 60.0  # every look at the clock burns a minute
        return clock["now"]

    monkeypatch.setattr(batch_digest.time, "monotonic", fake_monotonic)

    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True,
        max_elapsed_seconds=100,
    )

    assert not digests[0].ok and "Internal Server Error" in digests[0].error
    assert len(client.create_calls) == 1  # follow-up skipped, budget exhausted
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_collect_keeps_fresher_error_when_followup_also_fails():
    # One round only: a sheet that fails in BOTH rounds ends with a clean
    # error (no infinite retry loop), and no third batch is created.
    def responder(req):
        if req["custom_id"] == "sheet__0":
            return batch_errored_result("sheet__0", error_message="Internal Server Error")
        return _succeed(req)

    client = _FakeClient(responder)
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert not digests[0].ok and "Internal Server Error" in digests[0].error
    assert digests[1].ok
    assert len(client.create_calls) == 2


# --------------------------------------------------------------------------- #
# Cleanup (post-batch file deletion)
# --------------------------------------------------------------------------- #


def test_cleanup_in_background_returns_without_blocking_and_still_deletes(monkeypatch):
    # The pipeline opts into background cleanup so the digests return immediately
    # instead of stalling behind a long file-by-file delete. Stub the daemon-
    # thread seam to run inline so the deletion is assertable deterministically.
    ran: list[bool] = []
    monkeypatch.setattr(
        batch_digest, "_run_in_background", lambda fn: (ran.append(True), fn())
    )
    client = _FakeClient(_succeed)
    batch = submit_drawing_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, total=1
    )
    logs: list[tuple[str, str]] = []
    digests = collect_drawing_batch(
        batch,
        client=client,
        sleep=NOSLEEP,
        cleanup_in_background=True,
        on_log=lambda msg, level="info": logs.append((level, msg)),
    )

    assert digests[0].ok
    assert ran == [True]  # the background seam was taken, not the inline delete
    # Cleanup still happens (here, synchronously via the stub) — no file leak.
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)
    assert any("background" in msg.lower() for _, msg in logs)


def test_cleanup_synchronous_when_not_backgrounded():
    # The default (used by direct callers and the rest of the suite) deletes
    # inline before returning — no daemon thread, no leaked files.
    client = _FakeClient(_succeed)
    batch = submit_drawing_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, total=1
    )
    digests = collect_drawing_batch(batch, client=client, sleep=NOSLEEP)
    assert digests[0].ok
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


# --------------------------------------------------------------------------- #
# Detach / not-collected handling
# --------------------------------------------------------------------------- #


def test_batch_detach_marks_sheets_and_leaves_files():
    client = _FakeClient(_succeed)
    batch = submit_drawing_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, total=1
    )
    # Force the poll to immediately exceed the elapsed bound → "detached".
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, max_elapsed_seconds=-1
    )

    assert not digests[0].ok
    assert "not collected" in digests[0].error
    assert "batch_abc" in digests[0].error
    # Files left in place for the still-running remote batch — not deleted.
    assert client.files.deleted == []


def test_batch_detach_reports_diagnostics_via_on_log():
    """An uncollectable batch emits a leveled diagnostic through ``on_log``.

    This is the channel the GUI routes to its activity log, so the operator can
    see *why* a run came back incomplete rather than just losing the sheets.
    """
    client = _FakeClient(_succeed)
    batch = submit_drawing_batch(
        iter([_make_sheet(1)]), client=client, model=OPUS, total=1
    )
    logs: list[tuple[str, str]] = []
    collect_drawing_batch(
        batch,
        client=client,
        sleep=NOSLEEP,
        max_elapsed_seconds=-1,  # force the poll past its bound → "detached"
        on_log=lambda msg, level="info": logs.append((level, msg)),
    )
    assert any(
        level == "warning" and "still processing" in msg for level, msg in logs
    )


# --------------------------------------------------------------------------- #
# Diagnostics trace
# --------------------------------------------------------------------------- #


def test_diagnostics_file_records_batch_run_detail(tmp_path):
    """The on-disk diagnostics trace names everything needed to explain a partial
    run: the batch id, the custom_id -> sheet rosetta map, and the failing item
    attributed to its sheet with the cleaned error (an `api_error` 500 here)."""
    diagnostics.reset_for_tests()
    log_path = tmp_path / "diag.log"
    assert diagnostics.configure_file_logging(log_path) == log_path
    try:
        def responder(req):
            if req["custom_id"] == "sheet__1":
                return batch_errored_result(
                    custom_id="sheet__1", error_message="Internal Server Error"
                )
            return _succeed(req)

        client = _FakeClient(responder)
        _run_batch(client, [_make_sheet(i) for i in (1, 2, 3)])
    finally:
        diagnostics.reset_for_tests()

    text = log_path.read_text(encoding="utf-8")
    assert "batch submitted" in text and "batch_abc" in text
    assert "sheet__1 -> M-102.pdf" in text            # custom_id -> human label
    assert "FAILED" in text and "Internal Server Error" in text  # item attribution
    assert "collect done" in text                      # ok/failed tally


# --------------------------------------------------------------------------- #
# End-to-end via the pipeline (renders a synthetic PDF; needs PyMuPDF)
# --------------------------------------------------------------------------- #


def test_pipeline_use_batch_combines_digests(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.pipeline import extract_drawing_context

    doc = pymupdf.open()
    for i in range(2):
        page = doc.new_page(width=792, height=612)
        page.insert_text((72, 72), f"SHEET M-10{i + 1} TEST")
    path = tmp_path / "set.pdf"
    doc.save(str(path))
    doc.close()

    client = _FakeClient(_succeed)
    progress: list[tuple] = []
    ctx = extract_drawing_context(
        [path],
        client=client,
        rows=2,
        cols=2,
        use_batch=True,
        progress=lambda d, t, label: progress.append((d, t, label)),
    )

    assert ctx.sheet_count == 2
    assert ctx.ok_sheet_count == 2
    assert "## Sheet 1/2" in ctx.combined_text
    assert "digest body for sheet__0" in ctx.combined_text
    assert ctx.total_input_tokens == 200  # 2 sheets × 100
    assert len(client.create_calls) == 1  # one batch for the set
    assert progress[-1] == (2, 2, "Done")
