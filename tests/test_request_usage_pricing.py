"""Stage telemetry must preserve Haiku's per-request 100k billing threshold."""

from decimal import Decimal
import json
from pathlib import Path

import pytest

from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.core.request_usage import RequestUsage
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import RunUsage, SheetRef
from drawing_analyzer.pipeline import _record_usage
from drawing_analyzer.prose_harvest import harvest_prose
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)


@pytest.mark.parametrize(
    ("prompt_sizes", "expected"),
    [
        ((60_000, 60_000), Decimal("0.014")),
        ((60_000, 100_001), Decimal("0.0620005")),
    ],
)
def test_harvest_ledger_prices_actual_request_boundaries(prompt_sizes, expected):
    responses = iter(prompt_sizes)

    class Messages(StreamingMessagesMixin):
        def create(self, **kwargs):
            return FakeMessage(
                content=[FakeTextBlock(text="```json\n" + json.dumps({
                    "findings": [{
                        "category": "coordination", "severity": "medium",
                        "text": "Coordinate equipment clearance with the structure.",
                        "source_quote": "", "anchor_hint": "SHEET",
                    }],
                }) + "\n```")],
                usage=FakeUsage(input_tokens=next(responses), output_tokens=2_000),
            )

    class Client(BetaClientMixin):
        messages = Messages()

    sheets = [
        SheetDigest(
            ref=SheetRef(
                pdf_path=Path("drawings.pdf"), source_name="drawings.pdf",
                source_id="SRC-0001", page_index=index, page_count=2,
            ),
            text=("**Coordination items**\n"
                  "- Equipment clearance must be coordinated with the structural framing."),
        )
        for index in range(2)
    ]
    result = harvest_prose(
        Ledger(), sheets, [], client=Client(), model="claude-haiku-5-5",
        max_workers=1, sleep=lambda *_: None,
    )
    assert result.api_calls == 2 and result.missing == 0
    assert [request.input_tokens for request in result.request_usage] == list(prompt_sizes)
    usage = RunUsage()
    _record_usage(
        usage, family="harvest", instance="prose_harvest", model="claude-haiku-5-5",
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        request_usage=result.request_usage,
    )
    assert len(usage.records) == 2
    assert usage.total_input_tokens == sum(prompt_sizes)
    assert usage.total_estimated_cost == expected


def test_refused_response_is_billed_and_failed_when_stage_fallback_completes():
    request = RequestUsage.from_message({
        "stop_reason": "refusal", "id": "msg_refused",
        "usage": {"input_tokens": 60_000, "output_tokens": 2_000},
    })
    usage = RunUsage()
    _record_usage(
        usage, family="harvest", instance="prose_harvest", model="claude-haiku-5-5",
        request_usage=[request], terminal_status="COMPLETE",
    )
    (record,) = usage.records
    assert not record.parse_success and record.terminal_status == "FAILED"
    assert record.request_or_custom_id == "msg_refused"
    assert usage.total_estimated_cost == Decimal("0.007")
