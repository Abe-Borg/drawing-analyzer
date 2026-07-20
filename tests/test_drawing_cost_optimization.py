"""Tests for the two cost optimizations that preserve output byte-for-byte:

- **L1** — the Batch transport can be opted into globally via
  ``DRAWING_ANALYZER_USE_BATCH`` without editing call sites, and running the
  exhaustive stack real-time surfaces a one-time cost nudge.
- **L2** — the self-consistency critique reads cache their shared image prefix
  (gated on ``runs >= 2``; the parallel batch path stays uncached), and the
  cache write/read tokens are threaded into the usage ledger so the priced
  estimate stays honest.

Mostly hermetic (no PyMuPDF); the two pipeline nudge tests render a synthetic
PDF and skip when PyMuPDF is unavailable (I-4).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from drawing_analyzer.critique import (
    build_critique_request_params,
    critique_sheet_self_consistent,
    outcome_from_message,
    result_from_outcomes,
)
from drawing_analyzer.models import ImageTile, RenderedSheet, SheetRef
from drawing_analyzer.pipeline import (
    _resolve_use_batch,
    _transport_plan_name,
    extract_drawing_context,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

_NOOP = lambda *_a, **_k: None  # noqa: E731 - injectable no-op sleep


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _rendered(*, source="s.pdf", page=0, sheet_text="VAV-3 SERVES ROOM 120") -> RenderedSheet:
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)
    ov = ImageTile(png_bytes=b"OVERVIEW", width_px=100, height_px=80, kind="overview")
    tile = ImageTile(png_bytes=b"TILE00", width_px=50, height_px=40, kind="tile",
                     row=0, col=0, label="top-left")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[tile], page_width_pt=792, page_height_pt=612,
        rows=1, cols=1, sheet_text=sheet_text,
    )


def _findings_block(findings=None) -> str:
    return "```json\n" + json.dumps({"findings": findings or []}) + "\n```"


def _read_message(*, cache_read=0, cache_write=0) -> FakeMessage:
    """A valid empty-findings critique read whose usage carries cache tokens."""
    return FakeMessage(
        content=[FakeTextBlock(text=_findings_block())],
        usage=FakeUsage(
            input_tokens=7, output_tokens=3,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


class _CapturingCritiqueClient:
    """Captures every request; returns a valid empty read whose usage carries the
    given cache tokens (to exercise the L2 breakpoint + accounting)."""

    def __init__(self, *, cache_read: int = 0, cache_write: int = 0):
        self.captured: list[dict] = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.captured.append(kw)
                return _read_message(cache_read=cache_read, cache_write=cache_write)

        self.messages = _Msgs()


def _content(kw: dict) -> list:
    return kw["messages"][0]["content"]


def _cache_block_count(kw: dict) -> int:
    return sum("cache_control" in b for b in _content(kw))


# --------------------------------------------------------------------------- #
# L2 — the caching breakpoint is gated on runs >= 2
# --------------------------------------------------------------------------- #


def test_selfconsistency_two_reads_cache_shared_prefix():
    client = _CapturingCritiqueClient()
    critique_sheet_self_consistent(_rendered(), client=client, runs=2, max_retries=0, sleep=_NOOP)

    assert len(client.captured) == 2
    for kw in client.captured:
        # Exactly one breakpoint, on the LAST content block, so read 2 serves the
        # whole ~90k-image-token prefix from read 1's cache.
        assert _cache_block_count(kw) == 1
        assert "cache_control" in _content(kw)[-1]
        assert _content(kw)[-1]["cache_control"] == {"type": "ephemeral"}
        # System prompt stays a plain string (portable + keeps existing request
        # -shape assertions valid).
        assert isinstance(kw["system"], str)


def test_single_read_is_not_cached():
    # runs == 1 disables self-consistency; caching a prefix nobody re-reads would
    # only pay the ~1.25x cache-write premium for nothing.
    client = _CapturingCritiqueClient()
    critique_sheet_self_consistent(_rendered(), client=client, runs=1, max_retries=0, sleep=_NOOP)

    assert len(client.captured) == 1
    assert _cache_block_count(client.captured[0]) == 0


def test_builder_cache_prefix_flag_default_off():
    content = [{"type": "text", "text": "a"}, {"type": "image", "source": {}},
               {"type": "text", "text": "b"}]

    # Default (what the parallel batch path uses) must NOT cache — parallel items
    # would each cache-WRITE the same prefix, making a batch strictly costlier.
    off = build_critique_request_params(list(content), model="claude-opus-4-8")
    assert all("cache_control" not in b for b in off["messages"][0]["content"])

    on = build_critique_request_params(list(content), model="claude-opus-4-8", cache_prefix=True)
    blocks = on["messages"][0]["content"]
    assert "cache_control" in blocks[-1]
    assert all("cache_control" not in b for b in blocks[:-1])
    # Copy-on-write: the caller's list (reused verbatim across the batch path's
    # reads) is never mutated in place.
    assert all("cache_control" not in b for b in content)


# --------------------------------------------------------------------------- #
# L2 — cache tokens are threaded into the accounting (ledger stays honest)
# --------------------------------------------------------------------------- #


def test_outcome_captures_cache_tokens():
    ref = _rendered().ref
    oc = outcome_from_message(_read_message(cache_read=900, cache_write=90),
                              run_id="critique_1", ref=ref)
    assert oc.status == "COMPLETE"
    assert oc.cache_read_tokens == 900
    assert oc.cache_write_tokens == 90


def test_outcome_captures_cache_tokens_dict_shaped_usage():
    # Regression (Codex P2): a dict-shaped ``usage`` — raw-REST clients, batch dict
    # results, the ``dict_shape`` fixtures — must still count cache tokens. Input/
    # output are read dict-tolerantly (``_get``), so the cache counters must be too,
    # or prompt-cached runs silently undercount ``total_estimated_cost``.
    ref = _rendered().ref
    msg = FakeMessage(
        content=[FakeTextBlock(text=_findings_block())],
        usage={
            "input_tokens": 7, "output_tokens": 3,
            "cache_read_input_tokens": 900, "cache_creation_input_tokens": 90,
        },
    )
    oc = outcome_from_message(msg, run_id="critique_1", ref=ref)
    assert oc.status == "COMPLETE"
    assert (oc.input_tokens, oc.output_tokens) == (7, 3)
    assert oc.cache_read_tokens == 900
    assert oc.cache_write_tokens == 90


def test_result_sums_cache_tokens_across_reads():
    ref = _rendered().ref
    # Realistic split: read 1 WRITES the prefix, read 2 READS it.
    o1 = outcome_from_message(_read_message(cache_write=1000), run_id="critique_1", ref=ref)
    o2 = outcome_from_message(_read_message(cache_read=1000), run_id="critique_2", ref=ref)
    res = result_from_outcomes([o1, o2], requested_runs=2)
    assert res.cache_write_tokens == 1000
    assert res.cache_read_tokens == 1000


def test_selfconsistency_result_carries_cache_tokens():
    client = _CapturingCritiqueClient(cache_read=500, cache_write=50)
    res = critique_sheet_self_consistent(
        _rendered(), client=client, runs=2, max_retries=0, sleep=_NOOP
    )
    # Both reads reported (read=500, write=50); the merged result sums them so the
    # usage ledger can price the write at 1.25x and the read at 0.1x.
    assert res.cache_read_tokens == 1000
    assert res.cache_write_tokens == 100


# --------------------------------------------------------------------------- #
# L1 — batch transport resolution (explicit > env > real-time)
# --------------------------------------------------------------------------- #


def test_resolve_use_batch_explicit_wins(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_USE_BATCH", "1")
    # An explicit choice always beats the env opt-in, in both directions.
    assert _resolve_use_batch(False) is False
    assert _resolve_use_batch(True) is True


def test_resolve_use_batch_env_opt_in(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_USE_BATCH", "1")
    assert _resolve_use_batch(None) is True
    monkeypatch.setenv("DRAWING_ANALYZER_USE_BATCH", "off")
    assert _resolve_use_batch(None) is False


def test_resolve_use_batch_default_realtime(monkeypatch):
    monkeypatch.delenv("DRAWING_ANALYZER_USE_BATCH", raising=False)
    assert _resolve_use_batch(None) is False


def test_independent_transport_pairs_have_stable_mode_names():
    assert _transport_plan_name(True, True) == "economy"
    assert _transport_plan_name(False, True) == "hybrid"
    assert _transport_plan_name(False, False) == "fast"
    assert _transport_plan_name(True, False) == "custom-batch-digest"


# --------------------------------------------------------------------------- #
# L1 — the real-time-exhaustive cost nudge (needs PyMuPDF)
# --------------------------------------------------------------------------- #


def test_exhaustive_realtime_emits_cost_hint(tmp_path, monkeypatch):
    pytest.importorskip("pymupdf")
    monkeypatch.delenv("DRAWING_ANALYZER_USE_BATCH", raising=False)
    from tests.test_drawing_qc_pipeline import _RoutingClient, _VAV_FINDING, _make_pdf

    src = _make_pdf(tmp_path / "M-101.pdf")
    ctx = extract_drawing_context(
        [src], client=_RoutingClient([_VAV_FINDING]), qc_markups=True, rows=2, cols=2
    )
    codes = [e.event_code for e in ctx.run_journal.events]
    assert "COST_HINT" in codes


def test_standard_run_no_cost_hint(tmp_path, monkeypatch):
    pytest.importorskip("pymupdf")
    monkeypatch.delenv("DRAWING_ANALYZER_USE_BATCH", raising=False)
    from tests.test_drawing_qc_pipeline import _RoutingClient, _make_pdf

    src = _make_pdf(tmp_path / "M-101.pdf")
    ctx = extract_drawing_context([src], client=_RoutingClient([]), rows=2, cols=2)
    codes = [e.event_code for e in ctx.run_journal.events]
    assert "COST_HINT" not in codes
