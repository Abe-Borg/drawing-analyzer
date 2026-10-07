"""Haiku extraction requests and incomplete-response containment."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing_analyzer.core.api_config import MODEL_HAIKU_5_5
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.models import SheetRef
from drawing_analyzer.prose_harvest import _structure_item, harvest_model
from drawing_analyzer.set_identity import default_identity_model, identify_set
from tests.fixtures.fake_anthropic import (
    BetaClientMixin, FakeMessage, FakeTextBlock, FakeUsage,
)


class _Cache:
    def __init__(self):
        self.entries = {}

    def get(self, key):
        return self.entries.get(key)

    def put(self, key, value):
        self.entries[key] = value


class _Client(BetaClientMixin):
    def __init__(self, response):
        self.calls = []

        def create(**params):
            self.calls.append(params)
            return response

        self.messages = SimpleNamespace(create=create)


_REF = SheetRef(
    pdf_path=Path("/tmp/haiku.pdf"), page_index=0, source_name="haiku.pdf",
    page_count=1, source_id="SRC-0001",
)
_PAYLOADS = {
    "identity": {"disciplines": ["mechanical"], "country": "Germany"},
    "harvest": {
        "sheet_id": "M-101", "category": "coordination", "severity": "low",
        "text": "Check valve is absent from the plan.", "source_quote": "CHECK VALVE",
        "tile": None, "refs": [],
    },
}


def _response(stage, *, stop="end_turn", text=None):
    if text is None:
        text = "```json\n" + json.dumps(_PAYLOADS[stage]) + "\n```"
    return FakeMessage(
        model=MODEL_HAIKU_5_5, stop_reason=stop,
        content=[
            SimpleNamespace(type="thinking", thinking="", signature="signed-haiku"),
            FakeTextBlock(text=text),
        ],
        usage=FakeUsage(input_tokens=321, output_tokens=123),
    )


def _run(stage, client, cache):
    if stage == "identity":
        return identify_set(
            [SheetDigest(ref=_REF, text="Sheet M-101 - Mechanical - Plan")], [],
            client=client, cache=cache, max_retries=0,
        )
    return _structure_item(
        "Check valve is absent from the plan.", "coordination", "CHECK VALVE",
        _REF, "M-101", client=client, model=harvest_model(),
        cache=cache, max_retries=0, sleep=lambda _seconds: None,
    )


@pytest.mark.parametrize("stage", ["identity", "harvest"])
def test_haiku_extraction_reads_text_after_signed_thinking_and_caches_success(stage):
    cache = _Cache()
    client = _Client(_response(stage))
    result = _run(stage, client, cache)
    if stage == "identity":
        assert result.identity.country == "Germany"
        assert result.error is None
    else:
        assert result[0].text == _PAYLOADS[stage]["text"]
        assert result[0].source_id == _REF.source_id
        assert result[0].page_index == _REF.page_index
    assert len(cache.entries) == 1
    (request,) = client.calls
    assert request["model"] == MODEL_HAIKU_5_5
    assert request["thinking"] == {"type": "adaptive"}
    assert request["output_config"]["effort"] == "medium"
    assert request["max_tokens"] == 8_000
    assert request["messages"][-1]["role"] == "user"
    assert not {"temperature", "top_p", "top_k", "fallbacks"}.intersection(request)

    warm = _Client(_response(stage))
    cached = _run(stage, warm, cache)
    assert cached.cached if stage == "identity" else cached[3]
    assert warm.calls == []


@pytest.mark.parametrize("stage", ["identity", "harvest"])
@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_incomplete_extraction_rejects_even_parseable_json_without_caching(stage, stop):
    cache = _Cache()
    client = _Client(_response(stage, stop=stop))
    result = _run(stage, client, cache)
    if stage == "identity":
        assert result.identity is None and result.error
        assert (result.input_tokens, result.output_tokens) == (321, 123)
    else:
        assert result == (None, 321, 123, False, True)
    assert cache.entries == {}
    # An HTTP 200 refusal is a completed response, not a transient retry.
    assert len(client.calls) == 1
    # A later complete answer for the same item must make a real call.
    good = _Client(_response(stage))
    _run(stage, good, cache)
    assert len(good.calls) == 1 and len(cache.entries) == 1


@pytest.mark.parametrize("stage", ["identity", "harvest"])
@pytest.mark.parametrize("text", ["", "```json\n{broken\n```"])
def test_empty_or_malformed_extraction_preserves_billed_usage(stage, text):
    cache = _Cache()
    result = _run(stage, _Client(_response(stage, text=text)), cache)
    if stage == "identity":
        assert result.identity is None and result.error
        assert (result.input_tokens, result.output_tokens) == (321, 123)
    else:
        assert result == (None, 321, 123, False, True)
    assert cache.entries == {}


def test_extraction_model_overrides_remain_available(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_IDENTITY_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("DRAWING_ANALYZER_HARVEST_MODEL", "claude-sonnet-5-5")
    assert default_identity_model() == "claude-sonnet-5-5"
    assert harvest_model() == "claude-sonnet-5-5"
