"""The digest never admits a read the model did not finish (WP-01.2: N4 digest, N27).

A digest is a completed read only when its ``stop_reason`` says so. Before
WP-01.2 both transports marked only an EMPTY reply or a ``max_tokens`` stop as a
failure, so three shapes passed as success and were cached at both levels:

* a refusal that carried explanatory text (``stop_reason="refusal"``);
* a stream that ended without ``message_stop`` — the real SDK then returns the
  partial text with ``stop_reason=None`` and raises nothing (N27);
* any stop reason the code did not know, including
  ``model_context_window_exceeded``, ``pause_turn`` and ``tool_use``.

Every cache loader also forced ``error=None`` on whatever it read back, so a
refusal cached once was served as a clean digest on every warm run.

These tests go through the public paths (``digest_sheet``, the batch submit /
collect / rescue functions and ``extract_drawing_context``), so they state the
contract rather than an implementation. The delivery contract is unchanged and
stated here too: ``combined_text`` drops an errored sheet's prose, and the
per-sheet export keeps it under a FAILED status (I-3).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer import batch_digest, pipeline
from drawing_analyzer.batch_digest import collect_drawing_batch, submit_drawing_batch
from drawing_analyzer.digest import digest_sheet
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.export import _sheet_document
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeBatchResult,
    FakeBatchResultEnvelope,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    FinalMessageStream,
    StreamingMessagesMixin,
)

OPUS = "claude-opus-5"
NOSLEEP = lambda _s: None  # noqa: E731 - the batch fakes are terminal on the first poll

REFUSAL_TEXT = "I can't help with reviewing this drawing sheet."
PARTIAL_TEXT = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120 and the duct"
GOOD_TEXT = "Sheet M-101 - Mechanical - Plan\nVAV-3 serves Room 120."
STALE_TEXT = "STALE CACHED TEXT THAT MUST NOT BE SERVED"

#: Replies the digest must never treat as a completed read:
#: ``(stop_reason, reply text, the sheet's error)``.
NOT_FINISHED = [
    pytest.param(
        "refusal", REFUSAL_TEXT, "refused digest (stop_reason='refusal')",
        id="refusal-with-text",
    ),
    pytest.param(
        "refusal", "", "refused digest (stop_reason='refusal')",
        id="refusal-empty",
    ),
    pytest.param(
        None, PARTIAL_TEXT, "unfinished digest (stop_reason=None)",
        id="stream-ended-without-a-stop-reason",
    ),
    pytest.param(
        "model_context_window_exceeded", PARTIAL_TEXT,
        "truncated digest (stop_reason='model_context_window_exceeded')",
        id="context-window",
    ),
    pytest.param(
        "a_stop_reason_from_the_future", PARTIAL_TEXT,
        "unfinished digest (stop_reason='a_stop_reason_from_the_future')",
        id="unknown",
    ),
    pytest.param(
        "pause_turn", PARTIAL_TEXT, "unfinished digest (stop_reason='pause_turn')",
        id="pause-turn",
    ),
    pytest.param(
        "tool_use", PARTIAL_TEXT, "unfinished digest (stop_reason='tool_use')",
        id="tool-use",
    ),
]

#: A marker for "the entry has no ``stop_reason`` key at all".
MISSING = object()

#: What a stored entry may record. Only a finished read is ever served.
STORED_NOT_FINISHED = [
    pytest.param("refusal", id="refusal"),
    pytest.param("max_tokens", id="truncation"),
    pytest.param(None, id="null-the-N27-shape"),
    pytest.param(MISSING, id="no-stop-reason-key"),
    pytest.param("model_context_window_exceeded", id="context-window"),
    pytest.param("pause_turn", id="pause-turn"),
    pytest.param("a_stop_reason_from_the_future", id="unknown"),
]
STORED_FINISHED = [
    pytest.param("end_turn", id="end-turn"),
    pytest.param("stop_sequence", id="stop-sequence"),
]


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


def _reply(text: str, stop, *, in_tok: int = 100, out_tok: int = 20) -> FakeMessage:
    return FakeMessage(
        content=[FakeTextBlock(text=text)] if text else [],
        stop_reason=stop,
        usage=FakeUsage(input_tokens=in_tok, output_tokens=out_tok),
    )


class _Msgs(StreamingMessagesMixin):
    def __init__(self, responder):
        self._responder = responder
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responder(kwargs)


class _RealtimeClient(BetaClientMixin):
    def __init__(self, responder):
        self.messages = _Msgs(responder)


def _ref(index: int = 1) -> SheetRef:
    return SheetRef(
        pdf_path=Path(f"M-10{index}.pdf"), page_index=0,
        source_name=f"M-10{index}.pdf", page_count=1,
    )


def _sheet(index: int = 1) -> RenderedSheet:
    ref = _ref(index)
    overview = ImageTile(
        png_bytes=f"OVERVIEW-{index}".encode(), width_px=2000, height_px=1500,
        kind="overview",
    )
    tiles = [
        ImageTile(
            png_bytes=f"T{index}-{r}{c}".encode(), width_px=2000, height_px=1500,
            kind="tile", row=r, col=c, label=f"r{r}c{c}",
        )
        for r in range(2)
        for c in range(2)
    ]
    return RenderedSheet(
        ref=ref, overview=overview, tiles=tiles, page_width_pt=3168,
        page_height_pt=2448, rows=2, cols=2, sheet_text=f"SHEET M-10{index} TEST",
    )


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _joined_text(params: dict) -> str:
    parts: list[str] = []
    for message in params.get("messages", []) or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content or []:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


class _DualClient:
    """Serves the digest on either transport from one script.

    ``script(request_text) -> (stop_reason, text)``. Real-time requests arrive
    through ``messages.stream`` or, for Opus 5, ``beta.messages.stream`` (the
    refusal fallback's namespace); batch requests through the Files API and
    Message Batches. Every batch is terminal on its first poll.
    """

    def __init__(self, script):
        self.script = script
        self.stream_calls: list[dict] = []
        self.batch_items: list[dict] = []
        self.batches_created = 0
        self._submitted: list[dict] = []
        self._uploads = 0
        self.files = _Obj(upload=self._upload, delete=lambda file_id: None)
        batches = _Obj(
            create=self._create_batch,
            retrieve=self._retrieve,
            results=self._results,
            cancel=lambda batch_id: _Obj(id=batch_id, processing_status="canceling"),
        )
        self.messages = _Obj(stream=self._stream, batches=batches)
        self.beta = _Obj(
            messages=_Obj(stream=self._stream, batches=batches), files=self.files,
        )

    @property
    def api_calls(self) -> int:
        return len(self.stream_calls) + len(self.batch_items)

    def _message(self, params: dict) -> FakeMessage:
        stop, text = self.script(_joined_text(params))
        return _reply(text, stop)

    def _upload(self, *, file):
        self._uploads += 1
        return _Obj(id=f"file_{self._uploads}")

    def _stream(self, **kwargs):
        kwargs.pop("betas", None)
        self.stream_calls.append(kwargs)
        return FinalMessageStream(self._message(kwargs))

    def _create_batch(self, *, requests):
        self.batches_created += 1
        self._submitted = list(requests)
        self.batch_items.extend(requests)
        return _Obj(id=f"batch_{self.batches_created}")

    def _retrieve(self, batch_id):
        n = len(self._submitted)
        return _Obj(
            processing_status="ended",
            request_counts=_Obj(
                succeeded=n, errored=0, canceled=0, expired=0, processing=0,
            ),
        )

    def _results(self, batch_id):
        for req in self._submitted:
            yield FakeBatchResult(
                custom_id=req["custom_id"],
                result=FakeBatchResultEnvelope(
                    type="succeeded", message=self._message(req["params"]),
                ),
            )


def _always(stop, text):
    return lambda _request_text: (stop, text)


def _rewrite(cache: DigestCache, key: str, stored, *, text: str = STALE_TEXT) -> None:
    """Give one stored entry the stop reason ``stored`` (``MISSING`` drops the key)."""
    entry = dict(cache._entries[key])
    entry["text"] = text
    if stored is MISSING:
        entry.pop("stop_reason", None)
    else:
        entry["stop_reason"] = stored
    cache.put(key, entry)


def _make_pdf(path: Path, sheet_ids: list[str]) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for sheet_id in sheet_ids:
        page = doc.new_page(width=792, height=612)
        page.insert_text((72, 72), f"SHEET {sheet_id} TEST")
    doc.save(str(path))
    doc.close()
    return path


def _capture_level1_keys(monkeypatch) -> dict:
    """Record the level-1 keys the pipeline computes (``_refkey`` -> key)."""
    keys: dict = {}
    real = pipeline._level1_partition

    def _spy(*args, **kwargs):
        out = real(*args, **kwargs)
        keys.update(out[2])
        return out

    monkeypatch.setattr(pipeline, "_level1_partition", _spy)
    return keys


def _count_renders(monkeypatch) -> dict:
    from drawing_analyzer import render as render_mod

    real = render_mod.render_sheet
    counter = {"n": 0}

    def _counting(*args, **kwargs):
        counter["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(render_mod, "render_sheet", _counting)
    return counter


def _run(path: Path, client, cache, *, use_batch: bool):
    return pipeline.extract_drawing_context(
        [path], client=client, rows=2, cols=2, cache=cache, use_batch=use_batch,
    )


# --------------------------------------------------------------------------- #
# Real time: digest_sheet
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stop, text, error", NOT_FINISHED)
def test_realtime_digest_never_admits_an_unfinished_read(stop, text, error):
    cache = DigestCache(None, persist=False)
    client = _RealtimeClient(lambda _kw: _reply(text, stop))

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    assert sd.error == error
    assert not sd.ok
    assert sd.stop_reason == stop
    # The text is kept for diagnostics and for the per-sheet export (I-3).
    assert sd.text == text
    # Only a ``max_tokens`` truncation earns the raised-cap retry: a raised cap
    # cannot finish a refusal, a stream that died, or a full context window.
    assert len(client.messages.calls) == 1
    assert cache.stats()["size"] == 0


@pytest.mark.parametrize("stop", ["end_turn", "stop_sequence"])
def test_realtime_finished_read_still_caches_and_is_served(stop):
    cache = DigestCache(None, persist=False)
    client = _RealtimeClient(lambda _kw: _reply(GOOD_TEXT, stop))

    first = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    second = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    assert first.ok and first.error is None and not first.cached
    assert second.ok and second.cached and second.text == GOOD_TEXT
    assert second.stop_reason == stop
    assert len(client.messages.calls) == 1


def test_realtime_max_tokens_truncation_keeps_its_raised_cap_retry():
    # The one truncation a raised cap can finish still gets its single retry;
    # WP-01.2 leaves that path exactly as it was.
    stops = iter(["max_tokens", "end_turn"])
    client = _RealtimeClient(lambda _kw: _reply(GOOD_TEXT, next(stops)))
    sd = digest_sheet(_sheet(), client=client, model=OPUS)
    caps = [kw["max_tokens"] for kw in client.messages.calls]
    assert len(caps) == 2 and caps[1] > caps[0]
    assert sd.ok and sd.stop_reason == "end_turn"


@pytest.mark.parametrize("stored", STORED_NOT_FINISHED)
def test_realtime_level2_hit_serves_only_a_finished_entry(stored):
    cache = DigestCache(None, persist=False)
    client = _RealtimeClient(lambda _kw: _reply(GOOD_TEXT, "end_turn"))
    digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    (key,) = list(cache._entries)
    _rewrite(cache, key, stored)

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    # The stored entry is a miss: the sheet is read again, never served stale.
    assert not sd.cached
    assert sd.ok and sd.text == GOOD_TEXT
    assert len(client.messages.calls) == 2
    # ...and the finished read replaces the entry, so the next run hits.
    assert cache._entries[key]["stop_reason"] == "end_turn"
    assert cache._entries[key]["text"] == GOOD_TEXT


@pytest.mark.parametrize("stored", STORED_FINISHED)
def test_realtime_level2_hit_still_serves_a_finished_entry(stored):
    cache = DigestCache(None, persist=False)
    client = _RealtimeClient(lambda _kw: _reply(GOOD_TEXT, "end_turn"))
    digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)
    (key,) = list(cache._entries)
    _rewrite(cache, key, stored, text=GOOD_TEXT)

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    assert sd.cached and sd.ok and sd.error is None
    assert sd.stop_reason == stored
    assert len(client.messages.calls) == 1


# --------------------------------------------------------------------------- #
# Batch: one parse for the batch item and the direct-call rescue
# --------------------------------------------------------------------------- #


def _slot(index: int = 0, *, cache_key: str | None = "batch-key") -> "batch_digest._Slot":
    return batch_digest._Slot(
        index=index, ref=_ref(index + 1), image_estimate=0, rows=2, cols=2,
        cache_key=cache_key, custom_id=f"sheet__{index}",
    )


@pytest.mark.parametrize("stop, text, error", NOT_FINISHED)
def test_batch_message_never_admits_an_unfinished_read(stop, text, error):
    cache = DigestCache(None, persist=False)
    slot = _slot()

    digest = batch_digest._digest_from_message(slot, _reply(text, stop), cache=cache)

    assert digest.error == error
    assert digest.text == text
    assert cache.stats()["size"] == 0
    # No raised-cap resubmission for any of them (R2, the refusal retry, is
    # WP-01.5's; a raised cap cannot finish a context-window stop).
    params = {"model": OPUS, "max_tokens": 64_000}
    assert batch_digest._item_retry_params(
        slot, {"type": "succeeded"}, digest, params=params,
    ) is None
    # The attempt was billed, so it stays in the ledger — as a failed one.
    (attempt,) = digest.usage_attempts
    assert attempt.billable and attempt.terminal_status == "FAILED"
    assert not attempt.parse_success


def test_batch_dict_message_without_a_stop_reason_is_unfinished():
    # A dict-shaped message (a raw-REST client, or a batch dict result) that
    # carries no ``stop_reason`` at all says nothing about how the read ended.
    cache = DigestCache(None, persist=False)
    message = {
        "content": [{"type": "text", "text": PARTIAL_TEXT}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }
    digest = batch_digest._digest_from_message(_slot(), message, cache=cache)
    assert digest.error == "unfinished digest (stop_reason=None)"
    assert digest.text == PARTIAL_TEXT
    assert cache.stats()["size"] == 0


def test_batch_context_window_stop_gets_no_raised_cap_resubmission():
    # ``model_context_window_exceeded`` is a truncation, but the limit is the
    # context window, not ``max_tokens``: a doubled cap cannot make room.
    slot = _slot()
    digest = batch_digest._digest_from_message(
        slot, _reply(PARTIAL_TEXT, "model_context_window_exceeded"), cache=None,
    )
    params = {"model": OPUS, "max_tokens": 64_000}
    assert batch_digest._item_retry_params(
        slot, {"type": "succeeded"}, digest, params=params,
    ) is None
    # The max_tokens shape keeps the resubmission it always had.
    truncated = batch_digest._digest_from_message(
        slot, _reply(PARTIAL_TEXT, "max_tokens"), cache=None,
    )
    retry = batch_digest._item_retry_params(
        slot, {"type": "succeeded"}, truncated, params=params,
    )
    assert retry is not None and retry["max_tokens"] > 64_000


def test_a_refused_batch_item_fails_and_is_not_cached():
    cache = DigestCache(None, persist=False)

    def script(request_text):
        if "M-101" in request_text:
            return "refusal", REFUSAL_TEXT
        return "end_turn", GOOD_TEXT

    client = _DualClient(script)
    batch = submit_drawing_batch(
        [_sheet(1), _sheet(2)], client=client, model=OPUS, cache=cache,
    )
    refused, good = collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP,
        retry_failed_items=True, recovery_transport=batch_digest.RECOVERY_BATCH,
    )

    assert refused.error == "refused digest (stop_reason='refusal')"
    assert refused.text == REFUSAL_TEXT
    assert good.ok
    # One batch: a refusal is not a raised-cap retry (R2 is WP-01.5).
    assert client.batches_created == 1
    stored = list(cache._entries.values())
    assert len(stored) == 1 and stored[0]["stop_reason"] == "end_turn"
    assert all(REFUSAL_TEXT not in e.get("text", "") for e in stored)


def test_a_direct_call_rescue_that_is_refused_is_not_cached():
    cache = DigestCache(None, persist=False)
    client = _DualClient(_always("refusal", REFUSAL_TEXT))
    slot = _slot()
    params = {
        "model": OPUS, "max_tokens": 64_000,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "x"}]}],
    }
    results: list = [None]

    recovered = batch_digest._rescue_failed_items_sync(
        [(slot, params)], results, client=client, cache=cache, sleep=NOSLEEP,
        max_elapsed_seconds=600,
    )

    assert recovered == 0
    assert results[0].error == "refused digest (stop_reason='refusal')"
    assert results[0].text == REFUSAL_TEXT
    assert cache.stats()["size"] == 0


@pytest.mark.parametrize("stored", STORED_NOT_FINISHED)
def test_batch_level2_hit_serves_only_a_finished_entry(stored):
    cache = DigestCache(None, persist=False)
    client = _DualClient(_always("end_turn", GOOD_TEXT))
    first = submit_drawing_batch([_sheet()], client=client, model=OPUS, cache=cache)
    collect_drawing_batch(first, client=client, cache=cache, sleep=NOSLEEP)
    (key,) = list(cache._entries)
    _rewrite(cache, key, stored)

    second = submit_drawing_batch([_sheet()], client=client, model=OPUS, cache=cache)

    # Not served from the cache: the sheet became a batch item again.
    assert second.batch_id is not None
    assert second.slots[0].digest is None
    (sd,) = collect_drawing_batch(second, client=client, cache=cache, sleep=NOSLEEP)
    assert sd.ok and not sd.cached and sd.text == GOOD_TEXT
    assert cache._entries[key]["stop_reason"] == "end_turn"


@pytest.mark.parametrize("stored", STORED_FINISHED)
def test_batch_level2_hit_still_serves_a_finished_entry(stored):
    cache = DigestCache(None, persist=False)
    client = _DualClient(_always("end_turn", GOOD_TEXT))
    first = submit_drawing_batch([_sheet()], client=client, model=OPUS, cache=cache)
    collect_drawing_batch(first, client=client, cache=cache, sleep=NOSLEEP)
    (key,) = list(cache._entries)
    _rewrite(cache, key, stored, text=GOOD_TEXT)

    second = submit_drawing_batch([_sheet()], client=client, model=OPUS, cache=cache)

    assert second.batch_id is None
    assert second.slots[0].digest.cached and second.slots[0].digest.ok


# --------------------------------------------------------------------------- #
# Level 1 (pre-render) and the pipeline, on both transports
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("use_batch", [False, True], ids=["realtime", "batch"])
@pytest.mark.parametrize(
    "stored",
    [
        pytest.param("refusal", id="refusal"),
        pytest.param("max_tokens", id="truncation"),
        pytest.param(None, id="null-the-N27-shape"),
        pytest.param(MISSING, id="no-stop-reason-key"),
        pytest.param("a_stop_reason_from_the_future", id="unknown"),
    ],
)
def test_level1_hit_serves_only_a_finished_entry(tmp_path, monkeypatch, use_batch, stored):
    path = _make_pdf(tmp_path / "set.pdf", ["M-101"])
    cache = DigestCache(None, persist=False)
    client = _DualClient(_always("end_turn", GOOD_TEXT))
    level1 = _capture_level1_keys(monkeypatch)
    _run(path, client, cache, use_batch=use_batch)
    (l1_key,) = level1.values()
    calls_after_first = client.api_calls
    _rewrite(cache, l1_key, stored)
    renders = _count_renders(monkeypatch)

    ctx = _run(path, client, cache, use_batch=use_batch)

    # The level-1 entry is a miss, so the sheet rasterizes again; its level-2
    # entry is finished, so the digest is served from there without a call.
    assert renders["n"] == 1
    assert client.api_calls == calls_after_first
    assert ctx.ok_sheet_count == 1 and ctx.cached_sheet_count == 1
    assert STALE_TEXT not in ctx.combined_text
    assert GOOD_TEXT in ctx.combined_text
    # Store-under-both repairs the level-1 entry from the finished read.
    assert cache._entries[l1_key]["stop_reason"] == "end_turn"
    assert cache._entries[l1_key]["text"] == GOOD_TEXT


@pytest.mark.parametrize("use_batch", [False, True], ids=["realtime", "batch"])
def test_a_refusal_the_old_code_cached_is_read_again(tmp_path, monkeypatch, use_batch):
    # Before WP-01.2 a refusal that carried text was stored at BOTH levels and
    # every loader forced ``error=None``, so it was served as a clean digest on
    # every warm run. Seed exactly that shape, then run warm.
    path = _make_pdf(tmp_path / "set.pdf", ["M-101"])
    cache = DigestCache(None, persist=False)
    client = _DualClient(_always("end_turn", GOOD_TEXT))
    _run(path, client, cache, use_batch=use_batch)
    assert len(cache._entries) == 2                     # level 1 and level 2
    for key in list(cache._entries):
        entry = dict(cache._entries[key])
        entry.update(text=REFUSAL_TEXT, stop_reason="refusal", findings=[])
        cache.put(key, entry)
    calls_before = client.api_calls

    ctx = _run(path, client, cache, use_batch=use_batch)

    # Re-attempted, and the fresh finished read is what ships.
    assert client.api_calls == calls_before + 1
    assert ctx.ok_sheet_count == 1 and ctx.cached_sheet_count == 0
    assert GOOD_TEXT in ctx.combined_text
    assert REFUSAL_TEXT not in ctx.combined_text
    # Both entries now hold the finished read, so the next run is fully warm.
    for entry in cache._entries.values():
        assert entry["stop_reason"] == "end_turn" and entry["text"] == GOOD_TEXT
    warm = _run(path, client, cache, use_batch=use_batch)
    assert client.api_calls == calls_before + 1
    assert warm.cached_sheet_count == 1


@pytest.mark.parametrize("use_batch", [False, True], ids=["realtime", "batch"])
@pytest.mark.parametrize(
    "stop, text, error",
    [
        pytest.param(
            "refusal", REFUSAL_TEXT, "refused digest (stop_reason='refusal')",
            id="refusal-with-text",
        ),
        pytest.param(
            "refusal", "", "refused digest (stop_reason='refusal')",
            id="refusal-empty",
        ),
        pytest.param(
            None, PARTIAL_TEXT, "unfinished digest (stop_reason=None)",
            id="stream-ended-without-a-stop-reason",
        ),
    ],
)
def test_an_unfinished_sheet_fails_is_never_cached_and_ships_only_in_its_export(
    tmp_path, use_batch, stop, text, error,
):
    path = _make_pdf(tmp_path / "set.pdf", ["M-101", "M-102"])
    cache = DigestCache(None, persist=False)

    def script(request_text):
        if "M-102" in request_text:
            return stop, text
        return "end_turn", GOOD_TEXT

    client = _DualClient(script)
    ctx = _run(path, client, cache, use_batch=use_batch)

    good, failed = ctx.sheets
    assert good.ok and not failed.ok
    assert failed.error == error
    assert ctx.ok_sheet_count == 1
    assert any(error in e for e in ctx.errors), ctx.errors
    digest_stage = next(s for s in ctx.stage_results if s.stage == "digest")
    assert digest_stage.status == "PARTIAL"
    assert (digest_stage.items_in, digest_stage.items_out) == (2, 1)

    # Delivery contract, unchanged: combined_text carries the failure line, not
    # the unfinished prose; the good sheet still ships (I-3).
    assert f"[drawing analysis failed for this sheet: {error}]" in ctx.combined_text
    assert GOOD_TEXT in ctx.combined_text
    if text:
        assert text not in ctx.combined_text
    # ...and the per-sheet export keeps what came back, under FAILED.
    document = _sheet_document(2, 2, failed)
    assert f"**Status:** FAILED — {error}" in document
    if text:
        assert text in document
    else:
        assert f"This sheet could not be analyzed: {error}" in document

    # Neither cache level holds the failed sheet: only the good sheet's two
    # entries exist, and the explanatory text is nowhere in the store.
    stored = list(cache._entries.values())
    assert len(stored) == 2
    assert all(e["stop_reason"] == "end_turn" for e in stored)
    if text:
        assert all(text not in e.get("text", "") for e in stored)


# --------------------------------------------------------------------------- #
# N27 through the real SDK: a stream that ends without ``message_stop``
# --------------------------------------------------------------------------- #


def _sse(events: list[tuple[str, dict]]) -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    ).encode()


_STREAM_HEAD = [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_hermetic", "type": "message", "role": "assistant",
        "model": OPUS, "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 1},
    }}),
    ("content_block_start", {
        "type": "content_block_start", "index": 0,
        "content_block": {"type": "text", "text": ""},
    }),
    ("content_block_delta", {
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": PARTIAL_TEXT},
    }),
]
_STREAM_TAIL = [
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 30},
    }),
    ("message_stop", {"type": "message_stop"}),
]


def _real_sdk_client(body: bytes):
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    seen: list[str] = []

    def handler(request):
        seen.append(request.url.path)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=body,
        )

    client = anthropic.Anthropic(
        api_key="hermetic-placeholder",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    return client, seen


def test_n27_a_real_sdk_stream_that_ends_without_message_stop_is_not_a_digest():
    # The real SDK's accumulator, over an in-process transport (no socket):
    # the body stops after a text delta, with no ``message_delta`` and no
    # ``message_stop``. ``get_final_message()`` returns the partial text with
    # ``stop_reason=None`` and raises nothing, so only the stop reason can say
    # the read is unfinished.
    client, seen = _real_sdk_client(_sse(_STREAM_HEAD))
    cache = DigestCache(None, persist=False)

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache, max_retries=0)

    assert seen == ["/v1/messages"]
    assert sd.stop_reason is None
    assert sd.error == "unfinished digest (stop_reason=None)"
    assert sd.text == PARTIAL_TEXT                      # kept for diagnostics
    assert cache.stats()["size"] == 0


def test_n27_control_the_same_stream_with_message_stop_is_a_digest():
    client, _seen = _real_sdk_client(_sse(_STREAM_HEAD + _STREAM_TAIL))
    cache = DigestCache(None, persist=False)

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache, max_retries=0)

    assert sd.ok and sd.error is None and sd.stop_reason == "end_turn"
    assert cache.stats()["size"] == 1
