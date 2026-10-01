"""Offline usage propagation; these checks do not measure cache eligibility."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing_analyzer import cross_qc as cross, pipeline, verify
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import Anchor, ConflictLeg, Finding, SheetGeometry, SheetRef
from tests.fixtures.fake_anthropic import (
    BetaClientMixin, FakeMessage, FakeTextBlock, FakeUsage, StreamingMessagesMixin,
)


MODEL = "claude-opus-5-5"


class _Client(BetaClientMixin):
    def __init__(self, responder):
        self.calls = []
        outer = self

        class _Messages(StreamingMessagesMixin):
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return responder(kwargs)

        self.messages = _Messages()


def _reply(text, *, shape="object", stop="end_turn", read=700, write=900):
    message = FakeMessage(
        content=[FakeTextBlock(text=text)], stop_reason=stop,
        usage=FakeUsage(input_tokens=10, output_tokens=1,
                        cache_read_input_tokens=read, cache_creation_input_tokens=write),
    )
    return message.model_dump() if shape == "dict" else message


def _geoms():
    return [SheetGeometry(
        ref=SheetRef(pdf_path=Path("set.pdf"), page_index=i, page_count=3,
                     source_name="set.pdf", source_id="SRC-0001"),
        page_width_pt=800, page_height_pt=600, rows=2, cols=2,
        sheet_text="PUMP", full_sheet_text="PUMP",
        words=[(500, 440, 560, 452, f"M-10{i + 1}", 0, 0, 0),
               (40, 40, 100, 52, "PUMP", 1, 0, 0)],
    ) for i in range(3)]


def _finding(index, *, dual=False):
    finding = Finding(
        sheet_id="M-101", source_id="SRC-0001", source_name="set.pdf", page_index=0,
        category="coordination", severity="high", text=f"Check pump {index}",
        source_quote="PUMP", anchor=Anchor(status="EXACT", rect_pdf=[40, 40, 100, 52]),
    )
    if dual:
        finding.also_on = [ConflictLeg(
            sheet_id="M-102", source_id="SRC-0001", source_name="set.pdf", page_index=1,
            source_quote="PUMP", anchor=Anchor(status="EXACT", rect_pdf=[40, 40, 100, 52]),
        )]
    return finding


def _verify_run(findings, client, *, dual, monkeypatch, **kwargs):
    kwargs.update(client=client, model=MODEL, max_workers=3, max_retries=0, sleep=lambda _: None)
    if dual:
        monkeypatch.setattr(verify, "_render_leg_crops", lambda requests, dpi: [b"crop"] * len(requests))
        return verify.verify_cross_findings(findings, _geoms(), **kwargs)

    def crops(items):
        for finding, *_ in items:
            yield finding, b"crop"

    return verify.verify_findings(findings, _geoms(), crop_renderer=crops, **kwargs)


@pytest.mark.parametrize("shape", ["object", "dict"])
@pytest.mark.parametrize("text", ['{"findings":[],"claims":[]}', "not JSON", ""])
def test_whole_cross_qc_keeps_cache_usage_even_without_a_parseable_reply(shape, text):
    geoms = _geoms()[:2]
    result = cross.cross_sheet_qc(
        [SheetDigest(ref=g.ref, text="PUMP") for g in geoms], geoms,
        client=_Client(lambda _: _reply("```json\n" + text + "\n```" if text.startswith("{") else text,
                                       shape=shape)), model=MODEL,
    )
    assert (result.input_tokens, result.output_tokens) == (10, 1)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (700, 900)
    assert result.complete == bool(text.startswith("{"))


@pytest.mark.parametrize("workers", [1, 3])
@pytest.mark.parametrize("fact_cap", [2, 8], ids=["pairs", "single-reconcile"])
@pytest.mark.parametrize("degraded", [False, True], ids=["complete", "malformed-reconcile"])
def test_shards_and_reconcile_pairs_sum_cache_usage_without_shared_worker_counters(workers, fact_cap, degraded, monkeypatch):
    monkeypatch.setattr(cross, "MAX_SHEETS_SINGLE_CALL", 1)
    monkeypatch.setattr(cross, "MAX_FACTS_PER_RECONCILE", fact_cap)
    geoms = _geoms()

    def respond(kwargs):
        user = kwargs["messages"][0]["content"][0]["text"]
        payload = {"findings": [], "claims": []}
        if "<sheet_text_layer>" in user:
            handle = re.search(r"===== SHEET (S\d+)", user).group(1)
            payload["facts"] = [{"sheet_handle": handle, "entity_or_tag": "PUMP",
                                 "attribute": "size", "value": "large", "exact_quote": "PUMP"}]
        elif degraded:
            return _reply("not JSON")
        return _reply("```json\n" + json.dumps(payload) + "\n```")

    result = cross.cross_sheet_qc(
        [SheetDigest(ref=g.ref, text="PUMP") for g in geoms], geoms,
        client=_Client(respond), model=MODEL, max_workers=workers,
    )
    assert result.complete == result.reconciliation_completed == (not degraded)
    assert result.facts_collected == result.shards_completed == 3
    # Three maps plus either one reconcile or all three half-cap group pairs.
    calls = 6 if fact_cap == 2 else 4
    assert (result.input_tokens, result.output_tokens) == (10 * calls, calls)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (700 * calls, 900 * calls)


def test_cross_qc_warm_verdict_cache_does_not_rebill_prompt_cache_usage():
    geoms = _geoms()[:2]
    digests = [SheetDigest(ref=g.ref, text="PUMP") for g in geoms]
    cache = DigestCache(None, persist=False)
    cold = cross.cross_sheet_qc(digests, geoms, client=_Client(lambda _: _reply('```json\n{"findings":[]}\n```')),
                               model=MODEL, cache=cache)
    warm = cross.cross_sheet_qc(digests, geoms, client=_Client(lambda _: pytest.fail("warm API call")),
                               model=MODEL, cache=cache)
    assert (cold.cache_read_tokens, cold.cache_write_tokens) == (700, 900)
    assert warm.cached and warm.complete
    assert (warm.input_tokens, warm.output_tokens, warm.cache_read_tokens, warm.cache_write_tokens) == (0, 0, 0, 0)


@pytest.mark.parametrize("dual", [False, True], ids=["single", "cross"])
@pytest.mark.parametrize("shape", ["object", "dict"])
@pytest.mark.parametrize("text,stop", [('{"verdict":"CONFIRMED"}', "end_turn"),
                                       ("not JSON", "end_turn"),
                                       ('{"verdict":"CONFIRMED"}', "max_tokens")])
def test_both_verifiers_keep_billed_cache_usage_on_settled_and_degraded_replies(dual, shape, text, stop, monkeypatch):
    result = _verify_run([_finding(i, dual=dual) for i in range(3)],
                         _Client(lambda _: _reply(text, shape=shape, stop=stop)),
                         dual=dual, monkeypatch=monkeypatch)
    assert result.api_calls == 3
    assert (result.input_tokens, result.output_tokens) == (30, 3)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (2100, 2700)
    assert result.judged == (3 if text.startswith("{") and stop == "end_turn" else 0)
    combined = verify.VerifyResult.combined(result, result)
    assert (combined.cache_read_tokens, combined.cache_write_tokens) == (4200, 5400)


@pytest.mark.parametrize("dual", [False, True], ids=["single", "cross"])
def test_mixed_live_and_warm_verification_counts_only_current_api_usage(dual, monkeypatch, tmp_path):
    cache = DigestCache(None, persist=False)
    kwargs = dict(dual=dual, monkeypatch=monkeypatch, cache=cache, evidence_dir=tmp_path)
    client = _Client(lambda _: _reply('{"verdict":"CONFIRMED"}'))
    cold = _verify_run([_finding(i, dual=dual) for i in range(2)], client, **kwargs)
    assert (cold.cache_read_tokens, cold.cache_write_tokens) == (1400, 1800)
    mixed = _verify_run([_finding(i, dual=dual) for i in range(3)], client, **kwargs)
    assert (mixed.cache_hits, mixed.api_calls) == (2, 1)
    assert (mixed.cache_read_tokens, mixed.cache_write_tokens) == (700, 900)
    warm = _verify_run([_finding(i, dual=dual) for i in range(3)],
                       _Client(lambda _: pytest.fail("warm API call")), **kwargs)
    assert (warm.cache_hits, warm.api_calls) == (3, 0)
    assert (warm.input_tokens, warm.output_tokens, warm.cache_read_tokens, warm.cache_write_tokens) == (0, 0, 0, 0)


@pytest.mark.parametrize("stage", ["cross_qc", "single", "cross"])
@pytest.mark.parametrize("shape", ["object", "dict"])
def test_optional_null_cache_counters_follow_the_existing_usage_reader(stage, shape, monkeypatch):
    client = _Client(lambda _: _reply('```json\n{"findings":[],"verdict":"CONFIRMED"}\n```',
                                     shape=shape, read=None, write=None))
    if stage == "cross_qc":
        geoms = _geoms()[:2]
        result = cross.cross_sheet_qc([SheetDigest(ref=g.ref, text="PUMP") for g in geoms],
                                     geoms, client=client, model=MODEL)
    else:
        result = _verify_run([_finding(0, dual=stage == "cross")], client,
                             dual=stage == "cross", monkeypatch=monkeypatch)
    assert (result.input_tokens, result.output_tokens) == (10, 1)
    assert (result.cache_read_tokens, result.cache_write_tokens) == (0, 0)


@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("model", [MODEL, "unknown-model"])
def test_pipeline_prices_prompt_cache_usage_and_keeps_local_hits_free(warm, model, monkeypatch, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    pdf = tmp_path / "set.pdf"
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"M-10{i + 1} PUMP")
    doc.save(pdf)
    doc.close()
    monkeypatch.setenv("DRAWING_ANALYZER_CROSS_QC_MODEL", model)
    monkeypatch.setenv("DRAWING_ANALYZER_VERIFY_MODEL", model)

    def digests(paths, **kwargs):
        return [SheetDigest(ref=ref, text="PUMP", findings=[_finding(i)])
                for i, ref in enumerate(pipeline.list_sheets(paths))]

    monkeypatch.setattr(pipeline, "_digest_sheets_concurrent", digests)
    # Unknown-model coverage uses cache-only usage: dropping these counters
    # must not turn real, unpriceable spend into a reported zero-cost run.
    ordinary = (10, 1) if not warm and model == MODEL else (0, 0)
    qc = cross.CrossQCResult(complete=True, cached=warm)
    # Include counters even on the cached stub to hold the ledger's CACHE path
    # to zero billing; producers normally already zero them on a warm hit.
    cross_result = SimpleNamespace(**{**vars(qc), "cache_read_tokens": 700, "cache_write_tokens": 900})
    cross_result.input_tokens, cross_result.output_tokens = ordinary
    monkeypatch.setattr(cross, "cross_sheet_qc", lambda *a, **k: cross_result)

    def verification(*args, **kwargs):
        # A subclass permits the new counters on the pre-fix slotted tally,
        # so the regression exercises the ledger instead of failing in setup.
        class UsageResult(verify.VerifyResult):
            pass

        result = UsageResult()
        result.eligible = result.verified = 1
        result.api_calls = 0 if warm else 1
        result.cache_hits = 1
        result.input_tokens, result.output_tokens = ordinary
        result.cache_read_tokens, result.cache_write_tokens = 700, 900
        return result

    monkeypatch.setattr(verify, "verify_findings", verification)
    monkeypatch.setattr(verify, "verify_cross_findings", verification)
    context = pipeline.extract_drawing_context(
        [pdf], client=object(), rows=2, cols=2, max_workers=1,
        synthesize=False, critique=False, cross_qc=True, qc_markups=True,
        verify_findings=True, reference_audit=False, citation_check=False,
        identity=False, review_plan=False, investigate=False, qc_work_dir=tmp_path / "qc",
    )
    records = {r.stage_instance: r for r in context.run_usage.records
               if r.stage_family in {"cross_qc", "verify"}}
    assert {"cross_qc", "verify_cache", "verify_cross_cache"} <= records.keys()
    if warm:
        assert all(r.transport == "CACHE" and r.estimated_cost in (0, None) for r in records.values())
        assert context.run_usage.total_cache_read_tokens == context.run_usage.total_cache_write_tokens == 0
        assert context.run_usage.total_estimated_cost == 0
    else:
        for name in ("cross_qc", "verify", "verify_cross"):
            record = records[name]
            assert (record.input_tokens, record.output_tokens) == ordinary
            assert (record.cache_read_tokens, record.cache_write_tokens) == (700, 900)
            # Opus 5.5: $4 input, $20 output, cache read 0.05x, write 1.25x.
            assert record.estimated_cost == (Decimal("0.004700") if model == MODEL else None)
        serialized = context.run_usage.to_dict()
        assert (serialized["total_cache_read_tokens"], serialized["total_cache_write_tokens"]) == (2100, 2700)
        assert context.run_usage.total_estimated_cost == (Decimal("0.014100") if model == MODEL else None)
