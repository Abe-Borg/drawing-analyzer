"""A retry never loses a better read; an unfinished read's findings stay out of the review.

Remediation WP-01.3 (N16, N15; plan WP-01 steps 3 and 5; D-1, D-2 notes). The
owner's rules, decided with measured options before any code:

* **N16, which read a sheet keeps.** Every read of one sheet is ranked: a
  finished read, then a partial read that carries content (prose or findings:
  truncated, unfinished, an unknown or continuation stop), then a refusal, then
  nothing (an empty reply, an errored batch envelope, a call that raised). A
  later read replaces the kept one only when it ranks at least as high, so a
  refusal, an empty reply or a failure never displaces a partial read, and of
  two partial reads the later (raised-cap) one wins. One helper,
  ``digest.keep_digest_read``, decides for both transports: the real-time
  raised-cap retry in ``digest_sheet`` and every batch site that folds a new
  read into a sheet's result (``batch_digest._replace_result_with_attempt_history``:
  the primary collect, the follow-up batch, the fresh-batch rounds, the direct
  rescue and the abandoned-batch harvest). The kept read's text, findings, stop
  reason and error move together (I-2: never spliced), and every attempt's
  usage is kept (rule 8).
* **Its error names the discarded attempt**: "<own error>; retry: <its error>",
  "; retry failed: <cleaned error>" for a call that raised, and
  "; N retries, the last: ..." for several.
* **The stalled-batch harvest holds a partial read**, so the rescue can only
  improve on it; one it never reaches leaves the partial read, not "not
  collected".
* **N15: an unfinished read's findings are held out of the review.** They are
  never numbered, anchored, verified, marked up or exported as findings; the
  sheet's own export file and its report card list them under FAILED (as they
  keep its prose), and they are counted per sheet and per run
  (``ctx.digest_findings_held_out``, a digest-stage warning, the sheet's
  ``SHEET_DIGESTED`` line in run.log, ``run_manifest.json``). The count is
  observational (D-2 note): the sheet is already a failed one.

Nothing is cached that was not before: only a finished read is ever admitted,
at either level (D-4), whichever read a sheet keeps.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer import batch_digest, pipeline
from drawing_analyzer.batch_digest import collect_drawing_batch, submit_drawing_batch
from drawing_analyzer.digest import SheetDigest, digest_sheet
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from tests.fixtures import gauntlet as G
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
NOSLEEP = lambda _s: None  # noqa: E731

TRUNC = "truncated digest (stop_reason='max_tokens')"
REFUSED = "refused digest (stop_reason='refusal')"
EMPTY_MT = "empty digest (stop_reason='max_tokens')"


def _block(*texts: str, quote: str = "VAV-3", closed: bool = True) -> str:
    items = [
        {"category": "code", "severity": "high", "text": t, "source_quote": quote}
        for t in texts
    ]
    return "```json\n" + json.dumps({"findings": items}) + ("\n```" if closed else "")


FIRST_PROSE = "FIRST READ: M-101 mechanical plan, VAV-3 serves Room 120."
FIRST = FIRST_PROSE + "\n\n" + _block("first-read finding")
FIRST_UNCLOSED = FIRST_PROSE + "\n\n" + _block("first-read finding", closed=False)
SECOND_PROSE = "SECOND READ: M-101 mechanical plan, VAV-3 serves Room 120 and 121."
SECOND = SECOND_PROSE + "\n\n" + _block("second-read finding")
REFUSAL_TEXT = "I can't help with reviewing this drawing sheet."


def _reply(text: str, stop, *, in_tok: int = 100, out_tok: int = 20) -> FakeMessage:
    return FakeMessage(
        content=[FakeTextBlock(text=text)] if text else [],
        stop_reason=stop,
        usage=FakeUsage(input_tokens=in_tok, output_tokens=out_tok),
    )


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _Msgs(StreamingMessagesMixin):
    """Answers each call with the next scripted reply (an Exception raises)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


class _RT(BetaClientMixin):
    def __init__(self, *replies):
        self.messages = _Msgs(replies)


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
        page_height_pt=2448, rows=2, cols=2, sheet_text=f"SHEET M-10{index} VAV-3",
    )


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


API_ERROR = "API_ERROR"            # an errored envelope a batch retries (api_error)
INVALID = "INVALID"                # an errored envelope it never retries


class _BatchClient:
    """One sheet (``sheet__0``); every attempt at it, batch item or direct
    (streamed) call, takes the next reply from one script. Every batch is
    terminal on its first poll unless ``stall_primary`` is set, in which case
    the first batch reports ``in_progress`` (burning ``tick`` fake seconds per
    poll) until it is canceled, and is then readable."""

    def __init__(self, script, *, stall_primary=False, clock=None, tick=600.0,
                 create_raises_after=None):
        self.script = list(script)
        self.n = 0
        self.batches: dict[str, list] = {}
        self.order: list[str] = []
        self.stream_calls: list[dict] = []
        self.canceled: set[str] = set()
        self.stall_primary = stall_primary
        self.clock = clock
        self.tick = tick
        self.create_raises_after = create_raises_after
        self.files = _Obj(upload=self._upload, delete=lambda file_id: None)
        batches = _Obj(
            create=self._create, retrieve=self._retrieve,
            results=self._results, cancel=self._cancel,
        )
        self.messages = _Obj(stream=self._stream, batches=batches)
        self.beta = _Obj(
            messages=_Obj(stream=self._stream, batches=batches), files=self.files,
        )

    def _next(self):
        reply = self.script[min(self.n, len(self.script) - 1)]
        self.n += 1
        return reply

    def _upload(self, *, file):
        return _Obj(id=f"file_{len(self.order)}_{id(file)}")

    def _stream(self, **kwargs):
        kwargs.pop("betas", None)
        self.stream_calls.append(kwargs)
        reply = self._next()
        if isinstance(reply, Exception):
            raise reply
        if reply in (API_ERROR, INVALID):
            raise ValueError("direct call failed")
        return FinalMessageStream(reply)

    def _create(self, *, requests, betas=None):
        if (
            self.create_raises_after is not None
            and len(self.order) >= self.create_raises_after
        ):
            raise RuntimeError("batch submit rejected")
        bid = f"batch_{len(self.order) + 1}"
        self.order.append(bid)
        self.batches[bid] = [(r, self._next()) for r in requests]
        return _Obj(id=bid)

    def _retrieve(self, batch_id):
        n = len(self.batches[batch_id])
        if (
            self.stall_primary and batch_id == self.order[0]
            and batch_id not in self.canceled
        ):
            self.clock["t"] += self.tick
            return _Obj(
                processing_status="in_progress",
                request_counts=_Obj(
                    succeeded=0, errored=0, canceled=0, expired=0, processing=n,
                ),
            )
        return _Obj(
            processing_status="canceled" if batch_id in self.canceled else "ended",
            request_counts=_Obj(
                succeeded=n, errored=0, canceled=0, expired=0, processing=0,
            ),
        )

    def _cancel(self, batch_id):
        self.canceled.add(batch_id)
        return _Obj(id=batch_id, processing_status="canceling")

    def _results(self, batch_id):
        for req, reply in self.batches[batch_id]:
            if reply == API_ERROR:
                env = FakeBatchResultEnvelope(
                    type="errored",
                    error=_Obj(type="api_error", message="Internal Server Error"),
                )
            elif reply == INVALID or isinstance(reply, Exception):
                env = FakeBatchResultEnvelope(
                    type="errored",
                    error=_Obj(type="invalid_request_error", message="prompt too long"),
                )
            else:
                env = FakeBatchResultEnvelope(type="succeeded", message=reply)
            yield FakeBatchResult(custom_id=req["custom_id"], result=env)


def _collect(client, *, transport, cache=None, **kw):
    batch = submit_drawing_batch([_sheet()], client=client, model=OPUS, cache=cache)
    (sd,) = collect_drawing_batch(
        batch, client=client, cache=cache, sleep=NOSLEEP,
        retry_failed_items=True, recovery_transport=transport, **kw,
    )
    return sd


def _texts(sd) -> list[str]:
    return [f.text for f in (sd.findings or [])]


def _attempts(sd) -> list[tuple]:
    return [
        (a.transport, a.terminal_status, a.input_tokens, a.output_tokens)
        for a in (getattr(sd, "usage_attempts", ()) or ())
        if a.billable
    ]


# --------------------------------------------------------------------------- #
# N16, real time: digest_sheet's raised-cap retry
# --------------------------------------------------------------------------- #

#: A retry that ranks below a partial read: ``(id, reply, the retry's error)``.
_WORSE_RETRIES = [
    pytest.param(_reply("", "max_tokens", in_tok=300, out_tok=60), EMPTY_MT, id="empty"),
    pytest.param(_reply(REFUSAL_TEXT, "refusal", in_tok=300, out_tok=60), REFUSED,
                 id="refused-with-text"),
    pytest.param(_reply("", "refusal", in_tok=300, out_tok=60), REFUSED, id="refused-empty"),
]


@pytest.mark.parametrize("first", [FIRST, FIRST_UNCLOSED], ids=["closed", "salvaged"])
@pytest.mark.parametrize("retry, retry_error", _WORSE_RETRIES)
def test_rt_worse_retry_keeps_first_read(first, retry, retry_error):
    cache = DigestCache(None, persist=False)
    client = _RT(_reply(first, "max_tokens"), retry)

    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    assert len(client.messages.calls) == 2
    # The first read, whole: its prose, its findings, its stop reason.
    assert sd.text == FIRST_PROSE
    assert _texts(sd) == ["first-read finding"]
    assert sd.stop_reason == "max_tokens"
    # Its own error, then the discarded retry's.
    assert sd.error == f"{TRUNC}; retry: {retry_error}"
    assert not sd.ok
    # Both attempts were billed.
    assert (sd.input_tokens, sd.output_tokens) == (400, 80)
    assert cache.stats()["size"] == 0


def test_rt_raising_retry_names_the_failure():
    client = _RT(
        _reply(FIRST, "max_tokens"), ValueError("permanent 400 on the raised cap"),
    )
    sd = digest_sheet(_sheet(), client=client, model=OPUS, max_retries=0)

    assert sd.text == FIRST_PROSE and _texts(sd) == ["first-read finding"]
    assert sd.error == f"{TRUNC}; retry failed: permanent 400 on the raised cap"
    assert (sd.input_tokens, sd.output_tokens) == (100, 20)


#: A retry that is itself a partial read: it ranks with the first read, and the
#: later (raised-cap) one wins. ``(id, stop reason, its own error)``.
_PARTIAL_RETRIES = [
    pytest.param("max_tokens", TRUNC, id="truncated-again"),
    pytest.param(None, "unfinished digest (stop_reason=None)", id="stream-ended"),
    pytest.param(
        "a_stop_reason_from_the_future",
        "unfinished digest (stop_reason='a_stop_reason_from_the_future')",
        id="unknown",
    ),
    pytest.param(
        "model_context_window_exceeded",
        "truncated digest (stop_reason='model_context_window_exceeded')",
        id="context-window",
    ),
]


@pytest.mark.parametrize("stop, error", _PARTIAL_RETRIES)
def test_rt_partial_retry_replaces_partial_first(stop, error):
    cache = DigestCache(None, persist=False)
    client = _RT(
        _reply(FIRST, "max_tokens"), _reply(SECOND, stop, in_tok=300, out_tok=60),
    )
    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    # The later read, whole, with its own error and no retry named.
    assert sd.text == SECOND_PROSE
    assert _texts(sd) == ["second-read finding"]
    assert sd.stop_reason == stop
    assert sd.error == error
    assert (sd.input_tokens, sd.output_tokens) == (400, 80)
    assert cache.stats()["size"] == 0


def test_rt_finished_retry_wins_and_is_cached():
    cache = DigestCache(None, persist=False)
    client = _RT(
        _reply(FIRST, "max_tokens"), _reply(SECOND, "end_turn", in_tok=300, out_tok=60),
    )
    sd = digest_sheet(_sheet(), client=client, model=OPUS, cache=cache)

    assert sd.ok and sd.error is None
    assert sd.text == SECOND_PROSE and _texts(sd) == ["second-read finding"]
    (entry,) = cache._entries.values()
    assert entry["stop_reason"] == "end_turn" and entry["text"] == SECOND_PROSE
    assert (entry["input_tokens"], entry["output_tokens"]) == (400, 80)


@pytest.mark.parametrize(
    "retry, error, text",
    [
        pytest.param(_reply(SECOND, "max_tokens"), TRUNC, SECOND_PROSE,
                     id="truncated-with-prose"),
        pytest.param(_reply(REFUSAL_TEXT, "refusal"), REFUSED, REFUSAL_TEXT, id="refused"),
        pytest.param(_reply("", "max_tokens"), EMPTY_MT, "", id="empty-again"),
    ],
)
def test_rt_empty_first_read_takes_the_retry(retry, error, text):
    # An empty first read has nothing to lose: the retry's read is kept, with
    # its own error (a refusal is named; a second empty read is the fresher one).
    client = _RT(_reply("", "max_tokens"), retry)
    sd = digest_sheet(_sheet(), client=client, model=OPUS)
    assert sd.error == error
    assert sd.text == text


def test_rt_never_splices_two_reads():
    # Whichever read is kept, its prose, findings, note and stop reason come
    # from that one read (I-2).
    first = FIRST_PROSE + "\n\n" + _block("first-read finding", closed=False)
    client = _RT(_reply(first, "max_tokens"), _reply(REFUSAL_TEXT, "refusal"))
    kept = digest_sheet(_sheet(), client=client, model=OPUS)
    assert kept.text == FIRST_PROSE
    assert _texts(kept) == ["first-read finding"]
    assert "unclosed" in kept.findings_note
    assert kept.stop_reason == "max_tokens"

    client = _RT(_reply(first, "max_tokens"), _reply(SECOND, "max_tokens"))
    later = digest_sheet(_sheet(), client=client, model=OPUS)
    assert later.text == SECOND_PROSE
    assert _texts(later) == ["second-read finding"]
    assert later.findings_note == ""


# --------------------------------------------------------------------------- #
# N16, batch: every site that folds a new read into a sheet's result
# --------------------------------------------------------------------------- #

_TRUNC_FIRST = _reply(FIRST, "max_tokens")


@pytest.mark.parametrize(
    "transport", [batch_digest.RECOVERY_DIRECT, batch_digest.RECOVERY_BATCH],
    ids=["direct", "batch"],
)
@pytest.mark.parametrize(
    "retry, named",
    [
        pytest.param(_reply("", "max_tokens", in_tok=300, out_tok=60), EMPTY_MT, id="empty"),
        pytest.param(_reply(REFUSAL_TEXT, "refusal", in_tok=300, out_tok=60), REFUSED,
                     id="refused"),
        pytest.param(INVALID, "invalid_request_error: prompt too long", id="errored-envelope"),
    ],
)
def test_batch_worse_retry_keeps_first_read(transport, retry, named):
    # The primary item comes back truncated with prose; its raised-cap
    # resubmission (the follow-up batch, or a fresh-batch round) comes back
    # worse. Before WP-01.3 the resubmission replaced the result wholesale.
    cache = DigestCache(None, persist=False)
    client = _BatchClient([_TRUNC_FIRST, retry])
    sd = _collect(client, transport=transport, cache=cache)

    assert sd.text == FIRST_PROSE and _texts(sd) == ["first-read finding"]
    assert sd.stop_reason == "max_tokens"
    assert sd.error.startswith(f"{TRUNC}; ")
    assert named in sd.error
    assert not sd.ok
    # Every billed attempt is kept on the kept read (rule 8).
    billed = _attempts(sd)
    assert billed[0] == ("BATCH", "FAILED", 100, 20)
    if retry != INVALID:
        assert billed[1] == ("BATCH", "FAILED", 300, 60)
    assert cache.stats()["size"] == 0


@pytest.mark.parametrize(
    "transport", [batch_digest.RECOVERY_DIRECT, batch_digest.RECOVERY_BATCH],
    ids=["direct", "batch"],
)
def test_batch_partial_retry_replaces_partial_first(transport):
    client = _BatchClient([_TRUNC_FIRST, _reply(SECOND, None, in_tok=300, out_tok=60)])
    sd = _collect(client, transport=transport)
    assert sd.text == SECOND_PROSE and _texts(sd) == ["second-read finding"]
    assert sd.error == "unfinished digest (stop_reason=None)"
    assert _attempts(sd) == [("BATCH", "FAILED", 100, 20), ("BATCH", "FAILED", 300, 60)]


@pytest.mark.parametrize(
    "transport", [batch_digest.RECOVERY_DIRECT, batch_digest.RECOVERY_BATCH],
    ids=["direct", "batch"],
)
def test_batch_finished_retry_wins_and_is_cached(transport):
    cache = DigestCache(None, persist=False)
    client = _BatchClient([_TRUNC_FIRST, _reply(SECOND, "end_turn", in_tok=300, out_tok=60)])
    sd = _collect(client, transport=transport, cache=cache)
    assert sd.ok and sd.text == SECOND_PROSE
    (entry,) = cache._entries.values()
    assert entry["stop_reason"] == "end_turn"


def test_direct_rescue_worse_read_keeps_the_batch_read():
    # The follow-up batch lands the item truncated again, so the direct rescue
    # (a real-time call at a higher cap) runs; it is refused.
    client = _BatchClient([
        _reply(FIRST, "max_tokens", in_tok=100, out_tok=20),
        _reply(SECOND, "max_tokens", in_tok=200, out_tok=40),
        _reply(REFUSAL_TEXT, "refusal", in_tok=300, out_tok=60),
    ])
    batch = submit_drawing_batch(
        [_sheet()], client=client, model=OPUS, max_tokens=16_000,
    )
    (sd,) = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True,
    )
    assert len(client.stream_calls) == 1                  # the rescue ran
    # The follow-up's partial read (the later of two partials) is kept; the
    # refused rescue is named, never shipped.
    assert sd.text == SECOND_PROSE and _texts(sd) == ["second-read finding"]
    assert sd.error == f"{TRUNC}; retry: {REFUSED}"
    assert not getattr(sd, "rescued", False)
    assert _attempts(sd) == [
        ("BATCH", "FAILED", 100, 20), ("BATCH", "FAILED", 200, 40),
        ("REAL_TIME", "FAILED", 300, 60),
    ]


def test_direct_rescue_that_raises_is_named_on_the_kept_read():
    client = _BatchClient([
        _reply(FIRST, "max_tokens"), _reply(SECOND, "max_tokens"),
        ValueError("permanent 400 on the raised cap"),
    ])
    batch = submit_drawing_batch([_sheet()], client=client, model=OPUS, max_tokens=16_000)
    (sd,) = collect_drawing_batch(
        batch, client=client, sleep=NOSLEEP, retry_failed_items=True,
    )
    assert sd.text == SECOND_PROSE
    assert sd.error == f"{TRUNC}; retry failed: permanent 400 on the raised cap"


def test_several_discarded_retries_are_counted(monkeypatch):
    # Fresh-batch rounds: the primary errors (api_error, retried at its cap),
    # round 1 lands a partial read, round 2 (raised cap) comes back with an
    # api_error, round 3 is refused. Two discarded attempts: the count and the
    # last one are named.
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "4")
    client = _BatchClient([
        API_ERROR,
        _reply(FIRST, "max_tokens", in_tok=100, out_tok=20),
        API_ERROR,
        _reply(REFUSAL_TEXT, "refusal", in_tok=300, out_tok=60),
    ])
    sd = _collect(client, transport=batch_digest.RECOVERY_BATCH)
    assert sd.text == FIRST_PROSE and _texts(sd) == ["first-read finding"]
    assert sd.error == f"{TRUNC}; 2 retries, the last: {REFUSED}"
    assert _attempts(sd) == [("BATCH", "FAILED", 100, 20), ("BATCH", "FAILED", 300, 60)]


def test_multiround_keeps_the_best_read_so_far():
    # Primary: an errored envelope (nothing). Round 1: a partial read. Round 2
    # (raised cap): empty. The partial read survives the empty one.
    client = _BatchClient([
        API_ERROR, _reply(FIRST, "max_tokens"), _reply("", "max_tokens", in_tok=300, out_tok=60),
    ])
    sd = _collect(client, transport=batch_digest.RECOVERY_BATCH)
    assert sd.text == FIRST_PROSE and _texts(sd) == ["first-read finding"]
    assert sd.error == f"{TRUNC}; retry: {EMPTY_MT}"


def test_a_later_errored_envelope_still_wins_over_nothing():
    # Two reads with no content: the fresher error stands (it is the one that
    # says why recovery stopped; pinned on the follow-up batch by
    # test_drawing_batch.py::test_rescue_skipped_when_followup_rejects_permanently).
    # Here on the fresh-batch rounds (a lone sheet whose every item failed
    # server-side skips the follow-up batch on the direct transport).
    client = _BatchClient([API_ERROR, INVALID])
    sd = _collect(client, transport=batch_digest.RECOVERY_BATCH)
    assert sd.error == "invalid_request_error: prompt too long"


# --------------------------------------------------------------------------- #
# N16, batch: the abandoned-batch harvest holds a partial read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "transport, rescue, error",
    [
        pytest.param(
            batch_digest.RECOVERY_DIRECT,
            _reply(REFUSAL_TEXT, "refusal", in_tok=300, out_tok=60),
            f"{TRUNC}; retry: {REFUSED}", id="direct-refused",
        ),
        pytest.param(
            batch_digest.RECOVERY_BATCH,
            _reply(REFUSAL_TEXT, "refusal", in_tok=300, out_tok=60),
            f"{TRUNC}; retry: {REFUSED}", id="batch-refused",
        ),
        pytest.param(
            batch_digest.RECOVERY_DIRECT,
            _reply("", "max_tokens", in_tok=300, out_tok=60),
            f"{TRUNC}; retry: {EMPTY_MT}", id="direct-empty",
        ),
        # The fresh-batch rescue of an empty max_tokens read raises the cap for
        # one more round, which comes back empty too: two discarded attempts.
        pytest.param(
            batch_digest.RECOVERY_BATCH,
            _reply("", "max_tokens", in_tok=300, out_tok=60),
            f"{TRUNC}; 2 retries, the last: {EMPTY_MT}", id="batch-empty",
        ),
    ],
)
def test_harvested_partial_read_survives_a_worse_rescue(monkeypatch, transport, rescue, error):
    # The primary batch stalls; once canceled, the harvest reads the sheet back
    # truncated with prose (billed). The rescue then comes back worse. Before
    # WP-01.3 the harvested read was dropped and the rescue's read shipped.
    clock = {"t": 0.0}
    monkeypatch.setattr(batch_digest.time, "monotonic", lambda: clock["t"])
    client = _BatchClient([_TRUNC_FIRST, rescue], stall_primary=True, clock=clock)
    sd = _collect(client, transport=transport, max_elapsed_seconds=100_000)

    assert "batch_1" in client.canceled
    assert sd.text == FIRST_PROSE and _texts(sd) == ["first-read finding"]
    assert sd.error == error
    billed = _attempts(sd)
    assert billed[0][2:] == (100, 20)
    assert billed[-1][2:] == (300, 60)


def test_harvested_partial_read_survives_an_unreached_rescue(monkeypatch):
    # The rescue never lands (every fresh-batch submit is rejected): the sheet
    # keeps the harvested partial read and its own error, not "not collected".
    monkeypatch.setenv("DRAWING_ANALYZER_MAX_BATCH_RESUBMIT_ROUNDS", "1")
    clock = {"t": 0.0}
    monkeypatch.setattr(batch_digest.time, "monotonic", lambda: clock["t"])
    client = _BatchClient(
        [_TRUNC_FIRST], stall_primary=True, clock=clock, create_raises_after=1,
    )
    sd = _collect(
        client, transport=batch_digest.RECOVERY_BATCH, max_elapsed_seconds=100_000,
    )
    assert sd.text == FIRST_PROSE and _texts(sd) == ["first-read finding"]
    assert sd.error == TRUNC
    assert "not collected" not in sd.error


def test_harvested_read_with_no_content_is_still_parked(monkeypatch):
    # Only a read with content is held: an empty one is parked for its usage
    # as before, and the finished rescue ships.
    clock = {"t": 0.0}
    monkeypatch.setattr(batch_digest.time, "monotonic", lambda: clock["t"])
    client = _BatchClient(
        [_reply("", "max_tokens"), _reply(SECOND, "end_turn", in_tok=300, out_tok=60)],
        stall_primary=True, clock=clock,
    )
    sd = _collect(
        client, transport=batch_digest.RECOVERY_BATCH, max_elapsed_seconds=100_000,
    )
    assert sd.ok and sd.text == SECOND_PROSE
    assert [a[2:] for a in _attempts(sd)] == [(100, 20), (300, 60)]


# --------------------------------------------------------------------------- #
# The one helper, over the whole case table (both directions)
# --------------------------------------------------------------------------- #


def _sd(text="", *, error=None, stop=None, findings=0) -> SheetDigest:
    from drawing_analyzer.models import Finding

    return SheetDigest(
        ref=_ref(), text=text, error=error, stop_reason=stop,
        findings=[
            Finding(sheet_id="M-101", source_name="M-101.pdf", page_index=0,
                    category="code", severity="low", text=f"f{i}")
            for i in range(findings)
        ],
    )


_FINISHED = dict(text="done", error=None, stop="end_turn")
_PARTIAL = dict(text="partial", error=TRUNC, stop="max_tokens")
_PARTIAL_FINDINGS_ONLY = dict(text="", error=TRUNC, stop="max_tokens", findings=1)
_UNFINISHED = dict(text="partial", error="unfinished digest (stop_reason=None)", stop=None)
_REFUSED_TEXT = dict(text=REFUSAL_TEXT, error=REFUSED, stop="refusal")
_REFUSED_EMPTY = dict(text="", error=REFUSED, stop="refusal")
_EMPTY = dict(text="", error=EMPTY_MT, stop="max_tokens")
_ENVELOPE = dict(text="", error="api_error: Internal Server Error", stop=None)

#: ``(kept, later, which one the sheet keeps)``
_TABLE = [
    (_PARTIAL, _FINISHED, "later"),
    (_PARTIAL, _PARTIAL, "later"),
    (_PARTIAL, _UNFINISHED, "later"),
    (_PARTIAL, _PARTIAL_FINDINGS_ONLY, "later"),
    (_PARTIAL, _REFUSED_TEXT, "kept"),
    (_PARTIAL, _REFUSED_EMPTY, "kept"),
    (_PARTIAL, _EMPTY, "kept"),
    (_PARTIAL, _ENVELOPE, "kept"),
    (_UNFINISHED, _EMPTY, "kept"),
    (_PARTIAL_FINDINGS_ONLY, _ENVELOPE, "kept"),
    (_REFUSED_TEXT, _EMPTY, "kept"),
    (_REFUSED_TEXT, _PARTIAL, "later"),
    (_EMPTY, _REFUSED_EMPTY, "later"),
    (_EMPTY, _PARTIAL, "later"),
    (_EMPTY, _EMPTY, "later"),
    (_EMPTY, _ENVELOPE, "later"),
    (_ENVELOPE, _ENVELOPE, "later"),
    (_ENVELOPE, _FINISHED, "later"),
    (None, _EMPTY, "later"),
    (None, _REFUSED_EMPTY, "later"),
]


@pytest.mark.parametrize("kept, later, winner", _TABLE)
def test_keep_digest_read_table(kept, later, winner):
    from drawing_analyzer.digest import keep_digest_read

    a = _sd(**kept) if kept is not None else None
    b = _sd(**later)
    before = a.error if a is not None else None
    out = keep_digest_read(a, b)
    if winner == "later":
        assert out is b
        assert b.error == later["error"]            # its own error, unchanged
    else:
        assert out is a
        assert a.error == f"{before}; retry: {later['error']}"


def test_keep_digest_read_never_names_a_retry_on_a_finished_read():
    from drawing_analyzer.digest import keep_digest_read

    finished = _sd(**_FINISHED)
    # A finished read ranks highest; a later worse read never gets here in the
    # pipelines, but if it did, the finished read keeps error None.
    assert keep_digest_read(finished, _sd(**_EMPTY)) is finished
    assert finished.error is None and finished.ok


# --------------------------------------------------------------------------- #
# N15: an unfinished read's findings are held out of the review
# --------------------------------------------------------------------------- #

HELD_TEXT = "Errored-read finding on M-102."
HELD_ITEM = {
    "sheet_id": "M-102", "category": "code", "severity": "high",
    "text": HELD_TEXT, "source_quote": "EQUIPMENT SCHEDULE SHOWN", "tile_label": "r1c1",
}


def _sabotaged_client(stop):
    """The gauntlet mini set, with M-102's digest ending in ``stop`` after a
    complete findings block (every attempt, retries included)."""
    client = G.mini_client()
    scripted = client._digest

    def _digest(text):
        if "EQUIPMENT SCHEDULE" in text:
            body = (
                "Sheet M-102 - Mechanical - Schedules\nEquipment sche\n\n"
                "```json\n" + json.dumps({"findings": [HELD_ITEM]}) + "\n```"
            )
            return FakeMessage(
                content=[FakeTextBlock(text=body)], stop_reason=stop,
                usage=FakeUsage(input_tokens=400, output_tokens=30),
            )
        return scripted(text)

    client._digest = _digest
    return client


def _run(tmp_path, client, *, exhaustive: bool):
    srcs = G.build_mini_set(tmp_path / "set")
    kw = (
        dict(reference_audit=True, qc_markups=True, qc_work_dir=tmp_path / "qc")
        if exhaustive else {}
    )
    ctx = pipeline.extract_drawing_context(srcs, client=client, rows=2, cols=2, **kw)
    from drawing_analyzer.export import write_drawing_export

    out = Path(write_drawing_export(
        ctx, tmp_path / "out", source_names=[p.name for p in srcs],
    ))
    return ctx, out


_UNFINISHED_STOPS = [
    pytest.param("max_tokens", id="truncated"),
    pytest.param("refusal", id="refused"),
    pytest.param(None, id="stream-ended"),
    pytest.param("model_context_window_exceeded", id="context-window"),
]


@pytest.mark.parametrize("stop", _UNFINISHED_STOPS)
def test_n15_exhaustive_run_holds_the_findings_out(tmp_path, stop):
    ctx, out = _run(tmp_path, _sabotaged_client(stop), exhaustive=True)

    # Not in the review: no ledger entry, so no QC number, anchor, verification
    # or markup placement.
    assert not [f for f in ctx.all_findings if HELD_TEXT in f.text]
    placements = getattr(getattr(ctx, "markup_run", None), "placements", None) or []
    assert all(HELD_TEXT not in (getattr(p, "text", "") or "") for p in placements)
    # The finished sheet's own finding is unchanged, numbered and in the review.
    kept = [f for f in ctx.all_findings if "VAV-3 has no shown clearance" in f.text]
    assert len(kept) == 1 and kept[0].qc_id

    # Counted per sheet and per run.
    (key,) = list(ctx.digest_findings_held_out)
    assert key.endswith(":p0")
    assert ctx.digest_findings_held_out == {key: 1}
    digest_stage = next(s for s in ctx.stage_results if s.stage == "digest")
    assert digest_stage.status == "PARTIAL"
    assert any("held out 1 finding(s)" in w for w in digest_stage.warnings), (
        digest_stage.warnings
    )

    # The exports: not a review finding anywhere...
    assert HELD_TEXT not in (out / "findings.json").read_text(encoding="utf-8")
    assert HELD_TEXT not in (out / "findings.csv").read_text(encoding="utf-8-sig")
    assert HELD_TEXT not in (out / "markup_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["digest_findings_held_out"] == {"total": 1, "by_sheet": {key: 1}}
    run_log = (out / "run.log").read_text(encoding="utf-8")
    assert "findings_held_out=1" in run_log
    # ...but listed in the sheet's own file under its FAILED status, and in its
    # report card, never in the report's findings table.
    (sheet_md,) = [p for p in out.glob("*_M_102_p1.md")]
    doc = sheet_md.read_text(encoding="utf-8")
    assert "**Status:** FAILED" in doc
    assert HELD_TEXT in doc and "held out" in doc.lower()
    report = (out / "report.html").read_text(encoding="utf-8")
    assert HELD_TEXT in report
    rows = [ln for ln in report.splitlines() if 'class="finding-row"' in ln]
    assert all(HELD_TEXT not in ln for ln in rows)


def test_n15_standard_run_holds_the_findings_out(tmp_path):
    ctx, out = _run(tmp_path, _sabotaged_client("max_tokens"), exhaustive=False)
    assert not [f for f in ctx.all_findings if HELD_TEXT in f.text]
    assert HELD_TEXT not in (out / "findings.json").read_text(encoding="utf-8")
    assert sum(ctx.digest_findings_held_out.values()) == 1
    (sheet_md,) = [p for p in out.glob("*_M_102_p1.md")]
    assert HELD_TEXT in sheet_md.read_text(encoding="utf-8")


def test_n15_a_finished_run_holds_nothing_out(tmp_path):
    ctx, out = _run(tmp_path, G.mini_client(), exhaustive=True)
    assert ctx.digest_findings_held_out == {}
    digest_stage = next(s for s in ctx.stage_results if s.stage == "digest")
    assert digest_stage.status == "COMPLETE" and not digest_stage.warnings
    manifest = json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["digest_findings_held_out"] == {"total": 0, "by_sheet": {}}
    assert [f.text for f in ctx.all_findings if f.sources == ["digest_json"]] == [
        "VAV-3 has no shown clearance."
    ]


def test_n15_and_n16_the_kept_first_read_is_held_out(tmp_path):
    # M-102's first read is truncated with a findings block and its raised-cap
    # retry is refused: the first read is kept (N16), named, and its findings
    # are held out of the review (N15).
    client = G.mini_client()
    scripted = client._digest
    calls = {"n": 0}

    def _digest(text):
        if "EQUIPMENT SCHEDULE" in text:
            calls["n"] += 1
            if calls["n"] == 1:
                body = (
                    "Sheet M-102 - Mechanical - Schedules\nEquipment sche\n\n"
                    "```json\n" + json.dumps({"findings": [HELD_ITEM]}) + "\n```"
                )
                return FakeMessage(content=[FakeTextBlock(text=body)],
                                   stop_reason="max_tokens",
                                   usage=FakeUsage(input_tokens=400, output_tokens=30))
            return FakeMessage(content=[FakeTextBlock(text=REFUSAL_TEXT)],
                               stop_reason="refusal",
                               usage=FakeUsage(input_tokens=400, output_tokens=10))
        return scripted(text)

    client._digest = _digest
    ctx, out = _run(tmp_path, client, exhaustive=True)
    m102 = next(s for s in ctx.sheets if "M-102" in s.ref.display_label)
    assert m102.error == f"{TRUNC}; retry: {REFUSED}"
    assert "Equipment sche" in m102.text
    assert (m102.input_tokens, m102.output_tokens) == (800, 40)
    assert any(f"{TRUNC}; retry: {REFUSED}" in e for e in ctx.errors)
    assert not [f for f in ctx.all_findings if HELD_TEXT in f.text]
    assert sum(ctx.digest_findings_held_out.values()) == 1
    doc = next(out.glob("*_M_102_p1.md")).read_text(encoding="utf-8")
    assert f"FAILED — {TRUNC}; retry: {REFUSED}" in doc
    assert "Equipment sche" in doc and HELD_TEXT in doc
    assert REFUSAL_TEXT not in doc


# --------------------------------------------------------------------------- #
# Caches: nothing is stored that was not before
# --------------------------------------------------------------------------- #


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


class _PipelineClient:
    """Both transports for a two-sheet PDF set: each sheet answers its
    attempts, in order, from its own script (keyed by a token of its text
    layer); every batch is terminal on its first poll."""

    def __init__(self, scripts: dict):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.seen: dict[str, int] = {}
        self._submitted: list = []
        self._n = 0
        self.files = _Obj(upload=self._upload, delete=lambda file_id: None)
        batches = _Obj(
            create=self._create, retrieve=self._retrieve, results=self._results,
            cancel=lambda batch_id: _Obj(id=batch_id, processing_status="canceling"),
        )
        self.messages = _Obj(stream=self._stream, batches=batches)
        self.beta = _Obj(
            messages=_Obj(stream=self._stream, batches=batches), files=self.files,
        )

    def _reply_for(self, params: dict):
        text = _joined_text(params)
        token = next(t for t in self.scripts if t in text)
        n = self.seen.get(token, 0)
        self.seen[token] = n + 1
        seq = self.scripts[token]
        return seq[min(n, len(seq) - 1)]

    def _upload(self, *, file):
        self._n += 1
        return _Obj(id=f"file_{self._n}")

    def _stream(self, **kwargs):
        kwargs.pop("betas", None)
        return FinalMessageStream(self._reply_for(kwargs))

    def _create(self, *, requests, betas=None):
        self._submitted = [(r, self._reply_for(r["params"])) for r in requests]
        return _Obj(id=f"batch_{self._n}")

    def _retrieve(self, batch_id):
        n = len(self._submitted)
        return _Obj(
            processing_status="ended",
            request_counts=_Obj(
                succeeded=n, errored=0, canceled=0, expired=0, processing=0,
            ),
        )

    def _results(self, batch_id):
        for req, reply in self._submitted:
            yield FakeBatchResult(
                custom_id=req["custom_id"],
                result=FakeBatchResultEnvelope(type="succeeded", message=reply),
            )


def _two_sheet_pdf(path: Path) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for token in ("SHEET M-101 GOOD", "SHEET M-102 CUTOFF"):
        page = doc.new_page(width=792, height=612)
        page.insert_text((72, 72), token)
    doc.save(str(path))
    doc.close()
    return path


@pytest.mark.parametrize("use_batch", [False, True], ids=["realtime", "batch"])
def test_a_kept_partial_read_is_never_cached(tmp_path, use_batch):
    # M-102's first read is truncated with a findings block; its raised-cap
    # retry is refused. The sheet keeps the first read (N16), holds its
    # findings out (N15), and neither cache level stores it: only the finished
    # sheet's read is stored, as before.
    path = _two_sheet_pdf(tmp_path / "set.pdf")
    body = "Sheet M-102 partial prose\n\n" + _block(HELD_TEXT, quote="CUTOFF")
    client = _PipelineClient({
        "M-101 GOOD": [_reply("Sheet M-101 finished prose.", "end_turn")],
        "M-102 CUTOFF": [_reply(body, "max_tokens"), _reply(REFUSAL_TEXT, "refusal")],
    })
    cache = DigestCache(None, persist=False)
    ctx = pipeline.extract_drawing_context(
        [path], client=client, rows=2, cols=2, cache=cache, use_batch=use_batch,
    )

    good, cut = ctx.sheets
    assert good.ok
    assert cut.error == f"{TRUNC}; retry: {REFUSED}"
    assert "partial prose" in cut.text and _texts(cut) == [HELD_TEXT]
    assert not [f for f in ctx.all_findings if HELD_TEXT in f.text]
    stored = list(cache._entries.values())
    assert len(stored) == 2                            # the good sheet, both levels
    assert all(e["stop_reason"] == "end_turn" for e in stored)
    assert all("partial prose" not in e.get("text", "") for e in stored)
    assert all(REFUSAL_TEXT not in e.get("text", "") for e in stored)


# --------------------------------------------------------------------------- #
# N15: the listing and the counts, unit level
# --------------------------------------------------------------------------- #


def _held_sheet(text: str = "partial prose") -> SheetDigest:
    from drawing_analyzer.models import Finding

    return SheetDigest(
        ref=_ref(2), text=text, stop_reason="max_tokens", error=TRUNC,
        findings=[
            Finding(sheet_id="M-102", source_name="M-102.pdf", page_index=0,
                    category="code", severity="high",
                    text='Pump <script>alert("x")</script> & P-1',
                    source_quote="P-1 <b>"),
        ],
    )


def test_report_card_lists_held_out_findings_escaped():
    from drawing_analyzer.html_report import _held_out_block

    block = _held_out_block(_held_sheet())
    assert "Findings held out of the review (1)" in block
    assert "<script>" not in block and "&lt;script&gt;" in block
    assert "<b>" not in block and "P-1 &lt;b&gt;" in block
    # A finished sheet, or a failed one with no findings, lists nothing.
    finished = SheetDigest(ref=_ref(), text="ok", stop_reason="end_turn")
    assert _held_out_block(finished) == ""
    assert _held_out_block(SheetDigest(ref=_ref(), text="", error=EMPTY_MT)) == ""


def test_sheet_file_lists_held_out_findings_under_failed():
    from drawing_analyzer.export import _sheet_document

    doc = _sheet_document(2, 2, _held_sheet())
    assert f"**Status:** FAILED — {TRUNC}" in doc
    assert doc.index("partial prose") < doc.index("## Findings held out of the review (1)")
    assert '- **high** · code: Pump <script>alert("x")</script> & P-1 (quote: "P-1 <b>")' in doc


def test_run_log_sheet_line_counts_held_out_findings():
    from types import SimpleNamespace

    from drawing_analyzer.run_journal import _sheet_lines

    ctx = SimpleNamespace(
        sheets=[_held_sheet(), SheetDigest(ref=_ref(), text="ok", stop_reason="end_turn")],
        sheet_geometries=[],
    )
    lines = _sheet_lines(ctx)
    assert any("1 finding(s) held out of the review" in ln and "FAILED" in ln for ln in lines)
    assert sum("held out" in ln for ln in lines) == 1


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param({}, {"total": 0, "by_sheet": {}}, id="none"),
        pytest.param(None, {"total": 0, "by_sheet": {}}, id="missing"),
        pytest.param({"SRC-0002:p0": 2, "SRC-0001:p3": 1},
                     {"total": 3, "by_sheet": {"SRC-0001:p3": 1, "SRC-0002:p0": 2}},
                     id="sorted"),
        pytest.param({"SRC-0001:p0": "x", "SRC-0002:p0": 0, "SRC-0003:p0": 1},
                     {"total": 1, "by_sheet": {"SRC-0003:p0": 1}}, id="malformed"),
        pytest.param(["not", "a", "dict"], {"total": 0, "by_sheet": {}}, id="not-a-dict"),
    ],
)
def test_manifest_held_out_summary(raw, expected):
    from types import SimpleNamespace

    from drawing_analyzer.export import _held_out_summary

    assert _held_out_summary(SimpleNamespace(digest_findings_held_out=raw)) == expected
