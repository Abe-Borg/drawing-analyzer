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
    """Serves both the beta (create) and sync (retrieve/results/cancel) namespaces."""

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

    def cancel(self, batch_id):
        self._c.cancel_calls.append(batch_id)
        return _Obj(id=batch_id, processing_status="canceling")

    def results(self, batch_id):
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
        inline_responder=None,
        rescue_responder=None,
    ):
        self.responder = responder
        self.status = status
        self.reverse_results = reverse_results
        self.inline_responder = inline_responder or _inline_ok
        self.rescue_responder = rescue_responder or _rescue_ok
        self.create_calls: list[dict] = []
        self.retrieve_calls: list[str] = []
        self.cancel_calls: list[str] = []
        self.submitted: list[dict] = []
        # Synchronous ``messages.create`` calls (the inline-base64 fallback path).
        self.messages_create_calls: list[dict] = []
        # Streamed ``beta.messages.stream`` calls (the direct-call rescue).
        self.rescue_calls: list[dict] = []
        self.files = _FakeFiles()
        batches = _FakeBatches(self)
        self.beta = _Obj(
            files=self.files,
            messages=_Obj(batches=batches, stream=self._beta_messages_stream),
        )
        self.messages = _Obj(batches=batches, create=self._messages_create)

    def _messages_create(self, **kwargs):
        self.messages_create_calls.append(kwargs)
        return self.inline_responder(kwargs)

    def _beta_messages_stream(self, *, betas=None, **kwargs):
        self.rescue_calls.append({"betas": betas, "params": kwargs})
        return _FakeStreamManager(self.rescue_responder, kwargs)


class _FakeStreamManager:
    """Context-manager stand-in for ``beta.messages.stream(...)``.

    Mirrors the SDK: the request is issued on ``__enter__`` (that is where a
    status/connection error raises) and ``get_final_message()`` returns the
    accumulated Message.
    """

    def __init__(self, responder, kwargs):
        self._responder = responder
        self._kwargs = kwargs
        self._message = None

    def __enter__(self):
        self._message = self._responder(self._kwargs)
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


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


def _inline_ok(_kwargs):
    """Default ``messages.create`` response for the inline-base64 fallback path.

    The Files-API outage fallback digests a sheet via the real-time
    ``digest_sheet`` (one synchronous ``messages.create``); this returns a
    non-empty digest so the inlined sheet resolves OK.
    """
    return FakeMessage(
        content=[FakeTextBlock(text="inline digest body")],
        usage=FakeUsage(input_tokens=70, output_tokens=15),
        stop_reason="end_turn",
    )


def _rescue_ok(_kwargs):
    """Default ``beta.messages.stream`` final message for the direct-call rescue.

    The batch-backend outage fallback re-issues a still-failed batch item as
    one streamed call on the same params/file_ids; this returns a non-empty
    digest so the rescued sheet resolves OK.
    """
    return FakeMessage(
        content=[FakeTextBlock(text="rescued digest body")],
        usage=FakeUsage(input_tokens=90, output_tokens=25),
        stop_reason="end_turn",
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
    """A Files-API ``404 not_found_error`` lookalike (route-level).

    Carries ``status_code`` like the SDK's ``NotFoundError``; permanent, so the
    upload helper fails the sheet on the first image without retrying. A 404 is
    the inline-fallback-eligible status: the upload route is down but the
    Messages/Batches API still works.
    """

    status_code = 404

    def __init__(self, message: str = "Not found"):
        super().__init__(message)
        self.message = message


class _Credential401(Exception):
    """A Files-API ``401 authentication_error`` lookalike (credential-level).

    Carries ``status_code`` like the SDK's ``AuthenticationError``. Unlike a
    404, an inline request would hit the same rejection, so the breaker keeps
    the stop-and-skip behavior for this status.
    """

    status_code = 401

    def __init__(self, message: str = "invalid x-api-key"):
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


def test_submit_inlines_sheets_after_consecutive_404_failures():
    # A 404 on /v1/files means the upload route is unavailable while the
    # Messages/Batches API is healthy, so every 404'd sheet is digested INLINE
    # (base64, one synchronous vision call) instead of lost. After three
    # consecutive 404s the doomed upload attempts stop and the remaining sheets
    # go straight to the inline path — no sheet is dropped, only uploads stop.
    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles()  # every upload 404s
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(i) for i in range(6)])

    # Uploads stop after the breaker trips at 3; the rest skip the upload.
    assert client.files.attempts == 3
    # Every sheet still produced a digest — inline, via the real-time path.
    assert len(digests) == 6 and all(d.ok for d in digests)
    assert len(client.messages_create_calls) == 6
    # No batch was submitted and nothing was uploaded/left behind.
    assert client.submitted == [] and client.create_calls == []
    assert client.files.uploaded_ids == [] and client.files.deleted == []


def test_submit_credential_401_skips_with_actionable_hint():
    # A 401 is credential-level: an inline request would hit the same rejection,
    # so the breaker keeps the stop-and-skip behavior. The doomed sheets carry
    # the actionable hint, and once tripped the rest are skipped with it too.
    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles(exc_type=_Credential401)
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(i) for i in range(5)])

    assert client.files.attempts == 3  # breaker stops further uploads
    assert not any(d.ok for d in digests)
    assert len(client.messages_create_calls) == 0  # never inlined
    for d in digests[:3]:
        assert "upload failed" in d.error and "rotate the key" in d.error
    for d in digests[3:]:
        assert "upload skipped" in d.error and "3 consecutive HTTP 401" in d.error
    assert client.submitted == [] and client.create_calls == []


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
    # must NOT trip the all-inline switch — each 404'd sheet is inlined
    # individually while the reachable sheets keep uploading as batch items.
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

    # Every sheet resolves OK: 0/2/4 inlined, 1/3/5 uploaded as batch items.
    assert all(d.ok for d in digests)
    assert len(client.messages_create_calls) == 3  # the three 404'd sheets
    assert len(client.submitted) == 3  # every reachable sheet became an item
    assert not any(d.error and "upload skipped" in d.error for d in digests)


def test_submit_breaker_still_serves_cache_hits(tmp_path):
    # A sheet whose digest is already cached must resolve from the cache even
    # when the Files API is down — the cache check sits ahead of both the upload
    # and the inline fallback, so a cached sheet costs nothing either way.
    cache = DigestCache(tmp_path / "cache.json")
    warm_client = _FakeClient(_succeed)
    _run_batch(warm_client, [_make_sheet(9)], cache=cache)  # seed sheet 9

    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles()
    client.beta.files = client.files

    # Three uncached sheets 404 and are inlined; the cached sheet is served free.
    _, digests = _run_batch(
        client, [_make_sheet(0), _make_sheet(1), _make_sheet(2), _make_sheet(9)],
        cache=cache,
    )

    assert client.files.attempts == 3
    assert all(d.ok for d in digests)
    assert len(client.messages_create_calls) == 3  # the three uncached sheets
    assert digests[3].cached and not any(d.cached for d in digests[:3])


def test_submit_inline_fallback_coexists_with_uploaded_sheets():
    # The Files API works for the first sheet, then starts 404ing. The uploaded
    # sheet rides the batch (file_id); the 404'd sheets are inlined. Both
    # resolve, and only the uploaded sheet's files are cleaned up.
    class _DiesAfterFirstSheet(_FakeFiles):
        """Upload OK for the first ``ok_uploads`` images, then 404 every upload."""

        def __init__(self, ok_uploads: int):
            super().__init__()
            self.ok_uploads = ok_uploads
            self.attempts = 0

        def upload(self, *, file):
            self.attempts += 1
            if self.attempts <= self.ok_uploads:
                return super().upload(file=file)
            raise _RouteLevel404()

    client = _FakeClient(_succeed)
    # 2x2 sheets = 5 images each; let the first sheet's 5 images land, then die.
    client.files = _DiesAfterFirstSheet(ok_uploads=5)
    client.beta.files = client.files

    _, digests = _run_batch(client, [_make_sheet(i) for i in range(4)])

    assert all(d.ok for d in digests)
    assert len(client.submitted) == 1  # only sheet 0 became a batch item
    assert len(client.messages_create_calls) == 3  # sheets 1-3 inlined
    # Only the uploaded sheet's images exist and are cleaned up afterwards.
    assert len(client.files.uploaded_ids) == 5
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_submit_inline_fallback_digest_is_cached(tmp_path):
    # An inlined sheet's digest is written to the cache under the SAME key a
    # batch digest would use, so a later run is served from cache — proving the
    # fallback path stays cache-compatible with the Files-API path.
    cache = DigestCache(tmp_path / "cache.json")
    client = _FakeClient(_succeed)
    client.files = _CountingBrokenFiles()  # every upload 404s -> inline
    client.beta.files = client.files

    _, first = _run_batch(client, [_make_sheet(7)], cache=cache)
    assert first[0].ok and not first[0].cached
    assert client.files.attempts == 1 and len(client.messages_create_calls) == 1

    # Re-run against a still-broken Files API: the cache hit serves the sheet,
    # so neither an upload nor an inline call is made.
    client2 = _FakeClient(_succeed)
    client2.files = _CountingBrokenFiles()
    client2.beta.files = client2.files
    _, second = _run_batch(client2, [_make_sheet(7)], cache=cache)

    assert second[0].ok and second[0].cached
    assert client2.files.attempts == 0  # never even attempted an upload
    assert len(client2.messages_create_calls) == 0  # served from cache


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


# --------------------------------------------------------------------------- #
# Direct-call rescue (the batch backend erroring in every round)
# --------------------------------------------------------------------------- #


def _always_errored(req):
    """Batch responder for a full batch-backend outage: every item errors."""
    return batch_errored_result(
        req["custom_id"], error_message="Internal Server Error"
    )


def test_collect_rescues_batch_backend_outage_via_direct_calls():
    # The incident this guards: EVERY item failed with `api_error: Internal
    # Server Error` while the same run's uploads had all just succeeded — the
    # batch backend was the sick component, and the run ended 0/8 (a real run
    # also watched a follow-up batch fail identically, wasting ~10 minutes).
    # A batch whose every item fails retryably server-side therefore skips
    # the doomed follow-up round entirely and digests via synchronous
    # streamed beta.messages.stream calls carrying the byte-same params (and
    # the Files-API beta, since they reference file_ids), with the uploaded
    # files deleted only after the rescue.
    client = _FakeClient(_always_errored)
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert all(d.ok for d in digests)
    assert len(client.create_calls) == 1  # systemic failure: no doomed follow-up
    assert [c["params"] for c in client.rescue_calls] == [
        r["params"] for r in client.create_calls[0]["requests"]
    ]
    assert all(c["betas"] == [FILES_API_BETA] for c in client.rescue_calls)
    # The rescued digests carry the direct calls' usage, and the files were
    # still released exactly once, after the rescue.
    assert all(d.input_tokens == 90 and d.output_tokens == 25 for d in digests)
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_rescue_failure_keeps_the_batch_error():
    # A sheet that fails in both batch rounds AND whose direct call fails
    # permanently ends with its clean batch error — no infinite retry loop, no
    # third batch, exactly one direct attempt (a permanent error is not
    # re-issued).
    def rescue_responder(_kwargs):
        raise RuntimeError("still broken")

    def responder(req):
        if req["custom_id"] == "sheet__0":
            return _always_errored(req)
        return _succeed(req)

    client = _FakeClient(responder, rescue_responder=rescue_responder)
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert not digests[0].ok and "Internal Server Error" in digests[0].error
    assert digests[1].ok
    assert len(client.create_calls) == 2
    assert len(client.rescue_calls) == 1  # only the failed sheet, no retry loop
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_rescue_retries_transient_error_then_succeeds():
    # The rescue call itself rides out a transient blip (the same 429/5xx
    # policy as the real-time digest) instead of abandoning the sheet.
    state = {"n": 0}

    def rescue_responder(kwargs):
        state["n"] += 1
        if state["n"] == 1:
            raise _Transient503("Overloaded")
        return _rescue_ok(kwargs)

    slept: list[float] = []
    client = _FakeClient(_always_errored, rescue_responder=rescue_responder)
    batch = submit_drawing_batch(
        iter([_make_sheet(0)]), client=client, model=OPUS, total=1
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=slept.append, retry_failed_items=True
    )

    assert digests[0].ok
    assert len(client.rescue_calls) == 2  # first attempt + one retry
    assert slept  # backed off between the attempts


def test_rescue_skipped_when_followup_rejects_permanently():
    # Round 1: retryable api_error. Round 2: invalid_request_error — a
    # permanent request rejection a direct call would only repeat. No direct
    # call is made and the fresher (permanent) error stands.
    bad = type(
        "FakeError", (), {"message": "prompt too long", "type": "invalid_request_error"}
    )()
    state = {"round": 0}

    def responder(req):
        if req["custom_id"] != "sheet__0":
            return _succeed(req)
        state["round"] += 1
        if state["round"] == 1:
            return _always_errored(req)
        return FakeBatchResult(
            custom_id="sheet__0",
            result=FakeBatchResultEnvelope(type="errored", error=bad),
        )

    client = _FakeClient(responder)
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert not digests[0].ok and "prompt too long" in digests[0].error
    assert digests[1].ok
    assert client.rescue_calls == []


def test_rescue_raises_the_cap_again_after_two_empty_max_tokens_rounds():
    # Empty-at-max_tokens in BOTH rounds: the follow-up already ran at 2x, so
    # the direct rescue must double from the follow-up's cap (4x, bounded by
    # the ceiling) instead of re-proposing the cap that just came back empty.
    def responder(req):
        return FakeBatchResult(
            custom_id=req["custom_id"],
            result=FakeBatchResultEnvelope(
                type="succeeded",
                message=FakeMessage(content=[], stop_reason="max_tokens"),
            ),
        )

    client = _FakeClient(responder)
    batch = submit_drawing_batch(
        iter([_make_sheet(0)]), client=client, model=OPUS, total=1
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert digests[0].ok  # the direct call landed the digest
    base = client.create_calls[0]["requests"][0]["params"]["max_tokens"]
    followup = client.create_calls[1]["requests"][0]["params"]["max_tokens"]
    rescued = client.rescue_calls[0]["params"]["max_tokens"]
    assert followup == min(base * 2, batch_digest.MAX_TOKENS_RETRY_CEILING)
    assert rescued == min(followup * 2, batch_digest.MAX_TOKENS_RETRY_CEILING)
    assert rescued > followup


def test_followup_submit_failure_falls_back_to_direct_calls():
    # The batch backend rejecting even the follow-up submit is the strongest
    # signal that batch processing is the sick component: recovery must skip
    # straight to the direct calls instead of giving up. (Mixed results — one
    # ok, one api_error — so the follow-up round is genuinely attempted
    # rather than short-circuited by the all-items-failed fast path.)
    class _SecondCreateFails(_FakeBatches):
        def __init__(self, client):
            super().__init__(client)
            self.creates = 0

        def create(self, *, requests, betas=None):
            self.creates += 1
            if self.creates >= 2:
                raise RuntimeError("batch backend down")
            return super().create(requests=requests, betas=betas)

    def responder(req):
        return _always_errored(req) if req["custom_id"] == "sheet__0" else _succeed(req)

    client = _FakeClient(responder)
    batches = _SecondCreateFails(client)
    client.beta.messages.batches = batches
    client.messages.batches = batches
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert all(d.ok for d in digests)
    assert batches.creates == 2  # the follow-up round was attempted and rejected
    assert len(client.rescue_calls) == 1
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_followup_poll_failure_falls_back_to_direct_calls():
    # Ten consecutive retrieve failures on the FOLLOW-UP batch are themselves
    # a batch-backend-sick signal: its results are unreachable whether or not
    # it is still running, so the direct rescue must still recover the sheets.
    # The cancel is attempted but fails on the same dark endpoint, so the
    # uploaded files stay retained (the remote batch may still be running and
    # referencing them) — only the digests are rescued. (Mixed results so the
    # follow-up round is genuinely submitted rather than short-circuited by
    # the all-items-failed fast path.)
    class _FollowupDark(_FakeBatches):
        def retrieve(self, batch_id):
            if len(self._c.create_calls) >= 2:
                raise RuntimeError("batches.retrieve down")
            return super().retrieve(batch_id)

        def cancel(self, batch_id):
            raise RuntimeError("batches.cancel down")

    def responder(req):
        return _always_errored(req) if req["custom_id"] == "sheet__0" else _succeed(req)

    client = _FakeClient(responder)
    batches = _FollowupDark(client)
    client.beta.messages.batches = batches
    client.messages.batches = batches
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert all(d.ok for d in digests)
    assert len(client.rescue_calls) == 1
    assert client.files.deleted == []  # retained for the unreachable batch


def test_rescue_covers_items_missing_from_the_followup_results():
    # The follow-up round returns NO envelope for the item. Its first-round
    # error was retryable (that is why it was resubmitted), so the direct
    # rescue still gets a shot at it. (Mixed results so the follow-up round
    # actually runs instead of the all-items-failed fast path.)
    class _DropsRetryResults(_FakeBatches):
        def results(self, batch_id):
            # Primary round serves normally; the follow-up round yields nothing.
            if len(self._c.create_calls) >= 2:
                return iter(())
            return super().results(batch_id)

    def responder(req):
        return _always_errored(req) if req["custom_id"] == "sheet__0" else _succeed(req)

    client = _FakeClient(responder)
    batches = _DropsRetryResults(client)
    client.beta.messages.batches = batches
    client.messages.batches = batches
    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert all(d.ok for d in digests)
    assert len(client.create_calls) == 2  # the follow-up round did run
    assert len(client.rescue_calls) == 1


def test_rescued_digest_is_cached(tmp_path):
    # A rescued digest is written to the cache under the SAME key the batch
    # digest would have used, so a later run is served from cache.
    cache = DigestCache(tmp_path / "cache.json")
    client = _FakeClient(_always_errored)
    batch = submit_drawing_batch(
        iter([_make_sheet(3)]), client=client, model=OPUS, cache=cache, total=1
    )
    digests = collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP, retry_failed_items=True
    )
    assert digests[0].ok and not digests[0].cached

    # Re-run: served from cache — no upload, no batch, no rescue call.
    client2 = _FakeClient(_succeed)
    _, second = _run_batch(client2, [_make_sheet(3)], cache=cache)
    assert second[0].ok and second[0].cached
    assert client2.create_calls == [] and client2.rescue_calls == []
    assert client2.files.uploaded_ids == []


def test_rescue_respects_exhausted_budget():
    # With no collection budget left the rescue attempts nothing: the batch
    # errors stand and no direct call is made.
    client = _FakeClient(_succeed)
    ref = _make_sheet(0).ref
    slot = batch_digest._Slot(
        index=0, ref=ref, image_estimate=5, custom_id="sheet__0",
        params={"model": OPUS},
    )
    failed = batch_digest.SheetDigest(
        ref=ref, text="", error="api_error: Internal Server Error"
    )
    results: list = [failed]

    recovered = batch_digest._rescue_failed_items_sync(
        [(slot, slot.params)], results,
        client=client, cache=None, sleep=NOSLEEP, max_elapsed_seconds=0.0,
    )

    assert recovered == 0
    assert results[0] is failed
    assert client.rescue_calls == []


def test_rescue_stops_instead_of_sleeping_past_the_budget():
    # A transient error whose backoff would overrun the remaining collection
    # budget must NOT be slept through: the failing sheet keeps its batch
    # error, no backoff sleep happens, and the remaining sheets are not
    # attempted — the collect bound outranks the retry policy.
    def rescue_responder(_kwargs):
        raise _Transient503("Overloaded")

    client = _FakeClient(_succeed, rescue_responder=rescue_responder)
    ref0, ref1 = _make_sheet(0).ref, _make_sheet(1).ref
    slots = [
        batch_digest._Slot(
            index=i, ref=ref, image_estimate=5, custom_id=f"sheet__{i}",
            params={"model": OPUS},
        )
        for i, ref in enumerate([ref0, ref1])
    ]
    failed = [
        batch_digest.SheetDigest(
            ref=s.ref, text="", error="api_error: Internal Server Error"
        )
        for s in slots
    ]
    results: list = list(failed)
    slept: list[float] = []

    recovered = batch_digest._rescue_failed_items_sync(
        [(s, s.params) for s in slots], results,
        client=client, cache=None, sleep=slept.append,
        # Tiny but non-zero: the first attempt is allowed, but the 2s backoff
        # after its transient failure exceeds what is left.
        max_elapsed_seconds=1.0,
    )

    assert recovered == 0
    assert slept == []  # never slept past the bound
    assert len(client.rescue_calls) == 1  # sheet 0 attempted once; sheet 1 never
    assert results[0] is failed[0] and results[1] is failed[1]


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
    # Without the recovery opt-in, the batch is neither canceled nor rescued —
    # the original detach semantics stand for direct callers.
    assert client.cancel_calls == [] and client.rescue_calls == []


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
# Stuck-batch recovery (stall / detach / poll failure on the PRIMARY batch)
# --------------------------------------------------------------------------- #


class _NeverEndingBatches(_FakeBatches):
    """``retrieve`` always reports ``in_progress`` with zero completions,
    burning ``tick`` fake-seconds per poll on a scripted clock — the exact
    shape of the two real stuck batches (``processing=N``, nothing moving)."""

    def __init__(self, client, clock, tick):
        super().__init__(client)
        self._clock = clock
        self._tick = tick

    def retrieve(self, batch_id):
        self._c.retrieve_calls.append(batch_id)
        self._clock["t"] += self._tick
        n = len(self._c.submitted)
        return _Obj(
            processing_status="in_progress",
            request_counts=_Obj(
                succeeded=0, errored=0, canceled=0, expired=0, processing=n
            ),
        )


def _install_batches(client, batches):
    client.beta.messages.batches = batches
    client.messages.batches = batches


def test_detached_batch_is_canceled_and_rescued_directly(monkeypatch):
    # THE incident: a batch sits `in_progress` until the elapsed bound and the
    # run previously came back 0/N — every sheet "not collected" — despite
    # every upload and request in hand being valid. With recovery enabled the
    # poll holds back a rescue reserve, the never-ending batch is canceled,
    # and every sheet is digested via direct streamed calls on the same
    # still-uploaded file_ids; the files are then released.
    clock = {"t": 0.0}
    monkeypatch.setattr(batch_digest.time, "monotonic", lambda: clock["t"])
    client = _FakeClient(_succeed)
    _install_batches(client, _NeverEndingBatches(client, clock, tick=200.0))

    batch = submit_drawing_batch(
        iter([_make_sheet(0), _make_sheet(1)]), client=client, model=OPUS, total=2
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True,
        max_elapsed_seconds=1000,  # reserve=250 → the poll detaches past 750
    )

    assert all(d.ok for d in digests)
    assert client.cancel_calls == ["batch_abc"]
    assert len(client.rescue_calls) == 2
    # The rescued digests carry the direct calls' usage, and the canceled
    # batch's files were released.
    assert all(d.input_tokens == 90 and d.output_tokens == 25 for d in digests)
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_zero_progress_batch_stalls_before_the_elapsed_bound(monkeypatch):
    # A batch with NO per-item progress for the stall window is presumed
    # stuck (both real stuck batches showed zero completions from submit to
    # the 4h bound). The poll gives up EARLY — well before the elapsed bound —
    # cancels the batch, and the direct rescue completes the run.
    clock = {"t": 0.0}
    monkeypatch.setattr(batch_digest.time, "monotonic", lambda: clock["t"])
    client = _FakeClient(_succeed)
    _install_batches(client, _NeverEndingBatches(client, clock, tick=600.0))

    batch = submit_drawing_batch(
        iter([_make_sheet(0)]), client=client, model=OPUS, total=1
    )
    logs: list[tuple[str, str]] = []
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True,
        max_elapsed_seconds=100_000,
        on_log=lambda msg, level="info": logs.append((level, msg)),
    )

    assert digests[0].ok
    assert client.cancel_calls == ["batch_abc"]
    # Gave up at the stall window (1h of frozen counts), NOT the elapsed
    # bound: 7 polls × 600s ≈ 70 min, a fraction of the ~98k-second budget.
    assert len(client.retrieve_calls) == 7
    assert clock["t"] < 10_000
    assert any(level == "warning" and "no progress" in msg for level, msg in logs)
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


def test_primary_poll_failure_rescues_directly_and_retains_files():
    # Repeated retrieve failures on the PRIMARY batch previously marked every
    # sheet "not collected" and gave up. The direct rescue must still recover
    # the run — the Messages API can be healthy while the batches endpoints
    # are dark (exactly the shape of a real outage where identical direct
    # calls succeeded 8/8). The cancel fails on the same dark endpoint, so
    # the uploaded files stay retained for the maybe-still-running batch.
    class _DarkBatches(_FakeBatches):
        def retrieve(self, batch_id):
            raise RuntimeError("batches.retrieve down")

        def cancel(self, batch_id):
            raise RuntimeError("batches.cancel down")

    client = _FakeClient(_succeed)
    _install_batches(client, _DarkBatches(client))
    batch = submit_drawing_batch(
        iter([_make_sheet(0)]), client=client, model=OPUS, total=1
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True
    )

    assert digests[0].ok
    assert len(client.rescue_calls) == 1
    assert client.files.deleted == []  # cancel failed → batch may still be running


def test_stuck_batch_rescue_shortfall_keeps_clear_errors(monkeypatch):
    # When the rescue budget runs out before every sheet is reached, the
    # unreached sheets keep the "not collected" error — now naming the
    # canceled batch — and the files are still released (the cancel landed,
    # so nothing references them anymore).
    clock = {"t": 0.0}
    monkeypatch.setattr(batch_digest.time, "monotonic", lambda: clock["t"])
    client = _FakeClient(_succeed)
    _install_batches(client, _NeverEndingBatches(client, clock, tick=400.0))

    def slow_rescue(kwargs):
        clock["t"] += 300.0  # each direct call burns fake time
        return _rescue_ok(kwargs)

    client.rescue_responder = slow_rescue
    batch = submit_drawing_batch(
        iter([_make_sheet(i) for i in range(3)]), client=client, model=OPUS, total=3
    )
    digests = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True,
        # reserve=250 → poll detaches past 750 (t=800 after 2 polls); the
        # ~200s left allow one 300s rescue call, then the budget is spent.
        max_elapsed_seconds=1000,
    )

    assert digests[0].ok  # rescued before the budget ran out
    assert not digests[1].ok and not digests[2].ok
    assert "was canceled" in digests[1].error
    assert sorted(client.files.deleted) == sorted(client.files.uploaded_ids)


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
