"""Execute the report's actual usage handlers without a browser or API key.

Node supplies only the JavaScript runtime. The extracted production handlers
receive the API's cumulative usage events; minimal DOM stubs capture the footer.
These arithmetic checks complement the real-browser suite, which also verifies
file loading, streaming, CSP, and transcript UI behavior.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime

import pytest

from drawing_analyzer import html_report as hr
from tests.fixtures.fake_context import FakeContext


@pytest.fixture(scope="module")
def node():
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("Node is required to execute report JavaScript arithmetic")
    return executable


def _function(name):
    match = re.search(rf"^  function {name}\(.*?^  }}$", hr._CHAT_JS, re.M | re.S)
    assert match is not None, f"production function {name} disappeared"
    return match.group()


def _exercise(node, monkeypatch, actions, *, model="claude-haiku-5-5"):
    monkeypatch.setattr(hr, "CHAT_MODEL_DEFAULT", model)
    doc = hr.build_html_report(
        FakeContext(sheets=[]), source_names=[], now=datetime(2026, 10, 7),
    )
    match = re.search(r'<script id="da-chat-config"[^>]*>(.*?)</script>', doc, re.S)
    assert match is not None
    config = json.loads(match.group(1))
    declarations = []
    for name in ("sessionUsage", "sessionCost", "contextUsage"):
        declaration = re.search(rf"^  var {name} = .*;$", hr._CHAT_JS, re.M)
        assert declaration is not None
        declarations.append(declaration.group())
    clear_listener = re.search(
        r"^  clearBtn\.addEventListener\('click', function\(\)\{.*?^  \}\);$",
        hr._CHAT_JS, re.M | re.S,
    )
    assert clear_listener is not None
    # Only presentation/storage dependencies are stubbed. Accounting, event
    # dispatch, cost formatting, and both thread-reset paths are production JS.
    script = """
      var payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
      var CFG = payload.config;
      var usageEl = {hidden: true, textContent: ''};
      var turnGen = 0, aborter = null, history = [], displays = [], startersRow = null;
      var msgs = {children: [{}]};
      function renderContext(){}
      function paintCompose(){}
      function dropStoredTranscript(){}
      function clearPendingSelection(){}
      function clearTermHighlight(){}
      function scrollDown(){}
      var clearChat;
      var clearBtn = {addEventListener: function(type, listener){clearChat = listener;}};
    """
    script += "\n".join(declarations)
    script += "\n".join(_function(name) for name in (
        "fmtTokens", "renderUsage", "accountMessageUsage", "handleEvent", "replayTranscript",
    ))
    script += clear_listener.group()
    script += """
      var snapshots = [];
      function snapshot(){
        snapshots.push(JSON.parse(JSON.stringify({
          usage: sessionUsage, cost: sessionCost, context: contextUsage,
          text: usageEl.textContent, hidden: usageEl.hidden
        })));
      }
      payload.actions.forEach(function(action){
        if(action.reset){
          if(action.reset === 'new_chat') clearChat();
          else replayTranscript([]);
          snapshot();
          return;
        }
        var st = {};
        action.events.forEach(function(event){
          handleEvent(event, st, null);
          renderUsage();
          snapshot();
        });
      });
      process.stdout.write(JSON.stringify(snapshots));
    """
    result = subprocess.run(
        [node, "-e", script], input=json.dumps({"config": config, "actions": actions}),
        text=True, capture_output=True, check=True, timeout=10,
    )
    return json.loads(result.stdout)


def _message(prompt, outputs=(100_000,), *, cache_read=0, cache_write=0):
    return {"events": [
        {"type": "message_start", "message": {"usage": {
            "input_tokens": prompt, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write}}},
        *({"type": "message_delta", "usage": {"output_tokens": count}} for count in outputs),
    ]}


def test_each_prompt_keeps_its_own_tier_and_cumulative_output(node, monkeypatch):
    snapshots = _exercise(node, monkeypatch, [
        _message(100_000),
        _message(100_001, outputs=(50_000, 100_000, 75_000, 100_000)),
        _message(100_000),
    ])
    assert snapshots[1]["cost"]["lo"] == pytest.approx(0.06)
    assert snapshots[6]["cost"]["lo"] == pytest.approx(0.3600005)
    final = snapshots[-1]
    assert final["cost"] == pytest.approx({"lo": 0.4200005, "hi": 0.4200005})
    assert final["usage"] == {"input": 300_001, "output": 300_000, "cacheRead": 0, "cacheWrite": 0}
    assert "est. $0.42" in final["text"]


def test_final_server_tool_usage_reprices_existing_output_and_retains_prior_messages(node, monkeypatch):
    growing = _message(99_000, outputs=(50_000,))
    growing["events"] += [
        {"type": "message_delta", "usage": {"input_tokens": 101_000}},
        {"type": "message_delta", "usage": {"output_tokens": 100_000}},
        {"type": "message_delta", "usage": {"input_tokens": 101_000, "output_tokens": 100_000}},
    ]
    snapshots = _exercise(node, monkeypatch, [_message(100_000), growing])
    assert snapshots[3]["cost"]["lo"] == pytest.approx(0.0949)
    # Input crosses the threshold after 50k output was already counted. All of
    # this message's output adopts the premium; the previous message stays .06.
    assert snapshots[4]["cost"]["lo"] == pytest.approx(0.2355)
    assert snapshots[-1]["cost"] == pytest.approx({"lo": 0.3605, "hi": 0.3605})
    assert snapshots[-1]["usage"]["input"] == 201_000
    assert snapshots[-1]["usage"]["output"] == 200_000
    assert snapshots[-1]["context"] == {"prompt": 101_000, "output": 100_000}
    assert snapshots[-1] == snapshots[-2]  # repeated final usage adds nothing


def test_final_cache_corrections_select_tier_and_preserve_write_cost_band(node, monkeypatch):
    message = _message(1_000, outputs=(50_000,), cache_read=69_000, cache_write=30_000)
    message["events"] += [
        {"type": "message_delta", "usage": {
            "input_tokens": 500, "cache_read_input_tokens": 70_001,
            "cache_creation_input_tokens": 30_499, "output_tokens": 100_000}},
        {"type": "message_delta", "usage": {"output_tokens": 100_000}},
    ]
    snapshots = _exercise(node, monkeypatch, [message])
    assert snapshots[1]["cost"] == pytest.approx({"lo": 0.02954, "hi": 0.03179})
    final = snapshots[-1]
    assert final["cost"] == pytest.approx({"lo": 0.272811925, "hi": 0.28424905})
    assert final["usage"] == {"input": 500, "output": 100_000, "cacheRead": 70_001, "cacheWrite": 30_499}
    assert final["context"]["prompt"] == 101_000
    assert "est. $0.27-0.28" in final["text"]
    assert snapshots[-1] == snapshots[-2]


@pytest.mark.parametrize("reset", ["new_chat", "load"])
def test_thread_replacement_clears_tokens_and_dollars(node, monkeypatch, reset):
    snapshots = _exercise(node, monkeypatch, [
        _message(100_001), {"reset": reset}, _message(100_000),
    ])
    assert snapshots[1]["cost"]["lo"] == pytest.approx(0.3000005)
    assert snapshots[2]["hidden"] is True
    assert snapshots[2]["cost"] == {"lo": 0, "hi": 0}
    assert snapshots[2]["context"] == {"prompt": 0, "output": 0}
    assert snapshots[-1]["cost"]["lo"] == pytest.approx(0.06)
    assert "est. $0.06" in snapshots[-1]["text"]


@pytest.mark.parametrize("model,expected", [("claude-sonnet-5-5", 0.20), ("claude-opus-5-5", 0.20)])
def test_existing_models_keep_their_cache_read_rates(node, monkeypatch, model, expected):
    snapshots = _exercise(
        node, monkeypatch, [_message(0, outputs=(0,), cache_read=1_000_000)], model=model,
    )
    assert snapshots[-1]["cost"] == pytest.approx({"lo": expected, "hi": expected})
    assert "est. $0.20" in snapshots[-1]["text"]


def test_unknown_model_has_tokens_without_a_dollar_estimate(node, monkeypatch):
    snapshots = _exercise(node, monkeypatch, [_message(10, outputs=(120,))], model="unknown-model")
    assert "120 out" in snapshots[-1]["text"]
    assert "est." not in snapshots[-1]["text"]
