"""Live spend: billed / in flight / projected, and the budget cap (hermetic, I-4)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from drawing_analyzer.cancellation import CancelToken, RunCancelled
from drawing_analyzer.core.pricing import usage_record_cost
from drawing_analyzer.live_spend import BUDGET_STOP_REASON, SpendMonitor, StageForecast
from drawing_analyzer.pipeline import extract_drawing_context
from tests.fixtures import gauntlet as G
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage
from tests.test_drawing_batch import _FakeClient, _succeed

OPUS = "claude-opus-5"      # $5 in / $25 out per million tokens


def _message(input_tokens: int = 1_000_000, output_tokens: int = 0) -> FakeMessage:
    return FakeMessage(
        content=[FakeTextBlock(text="ok")],
        usage=FakeUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def _batch(*custom_ids: str, model: str = OPUS) -> list[dict]:
    return [{"custom_id": cid, "params": {"model": model}} for cid in custom_ids]


def _results(**outcomes) -> dict:
    """custom_id -> a succeeded message, or a non-billed result type by name."""
    return {
        cid: SimpleNamespace(result=(
            SimpleNamespace(type=outcome) if isinstance(outcome, str)
            else SimpleNamespace(type="succeeded", message=outcome)
        ))
        for cid, outcome in outcomes.items()
    }


def test_a_batch_item_is_in_flight_until_read_then_billed_at_the_batch_rate():
    spend = SpendMonitor(forecast=[StageForecast("digest", 3.0, 9.0, 3, 3)])
    spend.note_batch_submit("b1", _batch("a", "b", "c"), stage="digest",
                            items={"a": "S:p0", "b": "S:p1", "c": "S:p2"})
    queued = spend.snapshot()
    assert (queued.billed, queued.in_flight_items) == (0.0, 3)
    assert (queued.in_flight_low, queued.in_flight_high) == (3.0, 9.0)

    spend.note_batch_results("b1", _results(a=_message(), b="errored", c="expired"))
    read = spend.snapshot()
    half_rate = float(usage_record_cost(model=OPUS, input_tokens=1_000_000, batch=True))
    assert read.billed == half_rate == 2.5
    assert read.in_flight_items == 0

    # A second read of the same batch, and a batch this run never submitted
    # (receipt recovery collecting an earlier run's work), bill nothing more.
    spend.note_batch_results("b1", _results(a=_message()))
    spend.note_batch_results("earlier-run", _results(z=_message()))
    assert spend.snapshot().billed == 2.5


def test_the_projection_narrows_onto_what_the_stage_really_costs():
    """Ten $5 items against a $10–$200 quote: the band closes on $50."""
    spend = SpendMonitor(forecast=[StageForecast("digest", 10.0, 200.0, 10, 10)])
    widths = []
    for done in range(10):
        snap = spend.snapshot()
        assert snap.projected_low <= 50.0 <= snap.projected_high
        widths.append(snap.projected_high - snap.projected_low)
        spend.note_response(_message(), stage="digest", item=f"S:p{done}", model=OPUS)
    assert widths == sorted(widths, reverse=True) and widths[5] < widths[0] / 4
    spend.stage_finished("digest")
    done = spend.snapshot()
    assert done.projected_low == done.projected_high == done.billed == 50.0
    assert (done.quoted_low, done.quoted_high) == (10.0, 200.0)


def test_a_stage_that_ends_without_spending_leaves_the_projection():
    """A fully cached stage, or one the run never needed, costs nothing."""
    spend = SpendMonitor(forecast=[
        StageForecast("digest", 4.0, 8.0, 4, 4), StageForecast("critique", 8.0, 16.0, 8, 8),
    ])
    spend.expect("digest", 1)                       # three of four sheets cached
    one_sheet = spend.snapshot()
    assert (one_sheet.projected_low, one_sheet.projected_high) == (9.0, 18.0)
    spend.stage_finished("critique")
    assert spend.snapshot().projected_high == 2.0


def test_the_finished_run_reads_as_its_ledger():
    from drawing_analyzer.models import RunUsage, UsageRecord

    spend = SpendMonitor(forecast=[StageForecast("digest", 1.0, 2.0)])
    spend.note_response(_message(), stage="digest", item="S:p0", model=OPUS)
    ledger = RunUsage()
    ledger.add(UsageRecord("digest", "digest:S:p0", model=OPUS,
                           estimated_cost=usage_record_cost(model=OPUS, input_tokens=900_000)))
    spend.finish(ledger)
    final = spend.snapshot()
    assert final.final and final.billed == final.projected_low == final.projected_high == 4.5


def test_tokens_on_an_unpriced_model_are_flagged_not_counted_as_free():
    spend = SpendMonitor()
    spend.note_response(_message(), stage="digest", item="S:p0", model="some-unknown-model")
    snap = spend.snapshot()
    assert (snap.billed, snap.unpriced_calls) == (0.0, 1)


@pytest.mark.parametrize("scenario", [
    "billed reaches the cap",
    "a submitted batch's floor reaches the cap",
    "the cap is lowered under the spend",
])
def test_the_budget_cap_stops_the_run_through_its_kill_switch(scenario):
    token = CancelToken()
    spend = SpendMonitor(budget=8.0, forecast=[StageForecast("digest", 4.0, 40.0, 4, 4)])
    spend.bind_cancel(token)
    spend.note_response(_message(), stage="digest", item="S:p0", model=OPUS)     # $5
    assert not token.cancelled
    if scenario == "billed reaches the cap":
        spend.note_response(_message(), stage="digest", item="S:p1", model=OPUS)
    elif scenario == "a submitted batch's floor reaches the cap":
        spend.note_batch_submit("b1", _batch("x", "y", "z"), stage="digest")
    else:
        spend.set_budget(5.0)
    assert token.cancelled and token.reason == BUDGET_STOP_REASON
    hit = spend.snapshot().budget_hit
    assert hit.limit <= hit.committed and hit.billed >= 5.0


def test_a_quote_on_the_conservative_allowance_is_not_a_floor_for_the_cap():
    """Unmeasured pages are quoted far above their cost; only observed cost counts."""
    token = CancelToken()
    spend = SpendMonitor(
        budget=8.0, forecast=[StageForecast("digest", 400.0, 900.0, 4, 4, measured=False)],
    )
    spend.bind_cancel(token)
    spend.note_batch_submit("b1", _batch("a", "b", "c", "d"), stage="digest")
    assert not token.cancelled and spend.snapshot().committed == 0.0
    spend.note_batch_results(
        "b1", _results(a=_message(), b=_message(), c=_message(), d="errored"),
    )
    assert not token.cancelled                              # 3 x $2.50 billed
    # A second batch of the same sheets now has an observed cost to stand on.
    spend.note_batch_submit("b2", _batch("e", "f"), stage="digest")
    assert token.cancelled


@pytest.mark.parametrize("change", [20.0, None])
def test_raising_or_clearing_the_cap_mid_run_lets_the_run_continue(change):
    token = CancelToken()
    spend = SpendMonitor(budget=8.0)
    spend.bind_cancel(token)
    spend.note_response(_message(), stage="digest", item="S:p0", model=OPUS)     # $5
    spend.set_budget(change)
    spend.note_response(_message(), stage="digest", item="S:p1", model=OPUS)     # $10
    assert not token.cancelled and spend.snapshot().budget_hit is None


@pytest.mark.parametrize("amount", [0, -5, float("nan"), float("inf")])
def test_a_cap_that_is_not_a_positive_amount_is_refused(amount):
    spend = SpendMonitor(budget=3.0)
    with pytest.raises(ValueError):
        spend.set_budget(amount)
    assert spend.budget == 3.0


# --------------------------------------------------------------------------- #
# Through the pipeline
# --------------------------------------------------------------------------- #


def test_the_cap_stops_a_real_time_run_after_the_response_that_crossed_it(tmp_path):
    token = CancelToken()
    spend = SpendMonitor(budget=0.000001)
    client = G.mini_client()
    with pytest.raises(RunCancelled):
        extract_drawing_context(
            G.build_mini_set(tmp_path / "set"), client=client, rows=2, cols=2,
            qc_markups=True, max_workers=1, qc_work_dir=tmp_path / "qc",
            cancel=token, spend=spend,
        )
    assert sum(client.digest_calls.values()) == 1          # nothing sent after it
    snap = spend.snapshot()
    assert snap.budget_hit.stage == "digest" and snap.billed > 0
    assert token.reason == BUDGET_STOP_REASON


def test_the_cap_cancels_a_batch_whose_floor_already_exceeds_it(tmp_path, monkeypatch):
    from tests.test_cancellation import _two_sheet_pdf

    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    token = CancelToken()
    spend = SpendMonitor(budget=1.0, forecast=[StageForecast("digest", 4.0, 9.0, 2, 2)])
    client = _FakeClient(_succeed)
    with pytest.raises(RunCancelled):
        extract_drawing_context(
            [_two_sheet_pdf(tmp_path)], client=client, rows=2, cols=2,
            synthesize=False, use_batch=True, cancel=token, spend=spend,
        )
    assert token.wait_for_remote_cancels(5)
    assert client.cancel_calls == ["batch_abc"]
    assert len(client.create_calls) == 1


def test_a_budget_without_a_kill_switch_is_refused_before_anything_is_sent(tmp_path):
    client = G.mini_client()
    with pytest.raises(ValueError):
        extract_drawing_context(
            G.build_mini_set(tmp_path / "set"), client=client, rows=2, cols=2,
            spend=SpendMonitor(budget=5.0),
        )
    assert sum(client.digest_calls.values()) == 0
