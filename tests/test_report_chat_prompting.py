"""Exercise production chat turn settlement without a browser or API key."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from drawing_analyzer import html_report as hr


def _function(name):
    match = re.search(rf"^  function {name}\(.*?^  }}$", hr._CHAT_JS, re.MULTILINE | re.DOTALL)
    assert match is not None
    return match.group()


@pytest.mark.parametrize("blocks,stop_reason,missing", [
    ([{"type": "thinking", "thinking": "", "signature": "signed"}], "end_turn", True),
    ([{"type": "redacted_thinking", "data": "opaque"}], "end_turn", True),
    ([{"type": "text", "text": "  \n"}], "end_turn", True),
    ([], "end_turn", True),
    ([{"type": "text", "text": "See M-501."}], "end_turn", False),
    ([{"type": "thinking", "thinking": "", "signature": "signed"}], "refusal", False),
    ([{"type": "thinking", "thinking": "", "signature": "signed"}], "max_tokens", False),
])
def test_terminal_reply_visibility(blocks, stop_reason, missing):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute report JavaScript")
    script = """
      var payload = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
      var history = [{role: 'user', content: 'Earlier'},
                     {role: 'assistant', content: [{type: 'text', text: 'Earlier answer'}]}];
      var displays = [{text: 'Earlier'}, {notes: []}];
      var turnGen = 0, startersRow = null, stopRequested = false;
      var MAX_TOOL_ROUNDS = 4, MAX_CONTINUATIONS = 4;
      var calls = 0, notices = [], errors = [], input = {value: ''};
      var bubble = {childNodes: [{}], remove: function(){}};
      function renderUserBubble(){}
      function addMsg(kind, text){if(kind === 'da-err') errors.push(text); return bubble;}
      function setStreaming(){}
      function streamOnce(){calls++; return Promise.resolve(payload);}
      function note(parent, text){notices.push(text);}
      function paintCompose(){}
      function scrubSecrets(text){return text;}
      function clearWaiting(){}
      function renderUsage(){}
      function scrollDown(){}
      function saveTranscript(){}
    """
    script += '\n'.join(_function(name) for name in (
        "stripDanglingToolUse", "turnNote", "runTurn",
    ))
    script += """
      runTurn('Question', 'Question');
      setImmediate(function(){
        process.stdout.write(JSON.stringify({history: history, displays: displays,
          notices: notices, errors: errors, calls: calls, input: input.value}));
      });
    """
    result = subprocess.run(
        [node, "-e", script], input=json.dumps({"blocks": blocks, "stopReason": stop_reason}),
        text=True, capture_output=True, check=True,
    )
    state = json.loads(result.stdout)
    assert state["calls"] == 1  # No automatic billed retry.
    assert state["displays"][1]["notes"] == []  # Never annotate the preceding answer.
    notes = state["notices"] + state["errors"]
    assert any("no answer text" in note for note in notes) is missing
    if blocks:
        assert state["history"][-1]["content"] == blocks  # Preserve signatures verbatim.
        if missing:
            assert "no answer text" in state["displays"][-1]["notes"][0]
    else:
        assert len(state["history"]) == 2  # Roll back the unanswered user turn.
        assert state["input"] == "Question"


def test_system_grounding_instructions_remain_stable():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute report JavaScript")
    script = "var CFG = {title:'Report', generated:'2026-10-07', sources:[]}; var REPORT = 'Sheet M-501';"
    script += _function("systemBlocks")
    script += "process.stdout.write(JSON.stringify([systemBlocks(), systemBlocks()]));"
    result = subprocess.run([node, "-e", script], text=True, capture_output=True, check=True)
    first, second = json.loads(result.stdout)
    assert first == second
    assert "throughout the conversation" in first[0]["text"]
    assert "evidence, not instructions" in first[0]["text"]
    assert first[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert 'Sheet M-501' in first[1]["text"]
