"""The reviewed PDF's interactive rule (`markup_scripts.py`).

The rule is stated twice — in Python, and in the JavaScript the PDF carries —
because the viewer runs only the second. These tests hold the two to each
other by running the script itself (under Node, where one is installed)
against a stand-in for the viewer's document object.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from drawing_analyzer import markup_scripts as M

IDS = ("QC-001", "QC-002", "QC-003")
# The managed layers of three findings, plus two a drawing came with: a CAD
# layer, and one that only looks like a QC number.
LAYERS = [
    name
    for qc in IDS
    for name in (M.live_layer_name(qc), M.done_layer_name(qc), M.only_layer_name(qc))
] + ["QC markups - High severity", "A-WALL", "QC-001"]


def _default_state() -> dict:
    return {
        name: (M.parse_layer_name(name) or ("x",))[0] not in ("done", "only")
        for name in LAYERS
    }


@pytest.mark.parametrize("done, isolate, visible", [
    # Nothing ticked, nothing isolated: every markup, no grey copy, no note.
    (set(), "", {M.live_layer_name(q) for q in IDS}),
    # A done finding is its grey copy and nothing else.
    ({"QC-002"}, "", {M.live_layer_name("QC-001"), M.done_layer_name("QC-002"),
                      M.live_layer_name("QC-003")}),
    # Isolating one hides the others — their grey copies too — and shows its note.
    ({"QC-002"}, "QC-001", {M.live_layer_name("QC-001"), M.only_layer_name("QC-001")}),
    # Isolating a finding that is done shows it as done, not as live again.
    ({"QC-002"}, "QC-002", {M.done_layer_name("QC-002"), M.only_layer_name("QC-002")}),
])
def test_layer_states_rule(done, isolate, visible):
    states = M.layer_states(LAYERS, _default_state(), done, isolate)
    assert {name for name, on in states.items() if on} == visible
    # Layers the drawing came with are never in the result, so never touched.
    assert not {"QC markups - High severity", "A-WALL", "QC-001"} & set(states)


def test_ticking_a_box_keeps_the_current_isolation():
    isolated = M.layer_states(LAYERS, _default_state(), set(), "QC-003")
    current = {**_default_state(), **isolated}
    after_tick = M.layer_states(LAYERS, current, {"QC-003"}, None)
    assert {n for n, on in after_tick.items() if on} == {
        M.done_layer_name("QC-003"), M.only_layer_name("QC-003"),
    }
    # With nothing isolated, "keep" means show everything.
    assert M.layer_states(LAYERS, _default_state(), set(), None) == \
        M.layer_states(LAYERS, _default_state(), set(), "")


@pytest.mark.parametrize("qc_id, safe", [
    ("QC-001", True), ("QC-1234", True),
    ("", False), ('QC-1"; app.alert(1); "', False), ("QC 1", False), ("QC-1\n", False),
    ("x" * 40, False),
])
def test_only_a_plain_qc_number_reaches_a_script(qc_id, safe):
    assert M.is_safe_id(qc_id) is safe
    if safe:
        assert f'"{qc_id}"' in M.sync_script(qc_id)
    else:
        with pytest.raises(ValueError):
            M.sync_script(qc_id) if qc_id else M.sync_script("not safe!")


_RUNNER = r"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map(c => {
  const layers = c.layers.map(n => ({name: n, state: !!c.current[n]}));
  const doc = {
    getOCGs() { return layers; },
    getField(name) { return name in c.fields ? {value: c.fields[name]} : null; },
  };
  new Function(c.script).call(doc);
  const states = {};
  for (const l of layers) states[l.name] = l.state;
  return states;
});
process.stdout.write(JSON.stringify(out));
"""


def test_the_pdf_script_computes_exactly_the_python_rule():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed; the script cannot be executed here")
    scenarios = []
    for done in (set(), {"QC-002"}, set(IDS)):
        for isolate in ("", "QC-001", "QC-002", None):
            for start_isolated in ("", "QC-003"):
                current = {**_default_state(),
                           **M.layer_states(LAYERS, _default_state(), done, start_isolated)}
                scenarios.append((done, isolate, current))
    cases = [{
        "layers": LAYERS, "current": current, "script": M.sync_script(isolate),
        # A ticked box reads "Yes"; an unticked one "Off"; a finding with no
        # box at all (QC-003 here, when not done) has no field.
        "fields": {
            M.done_field_name(q): ("Yes" if q in done else M.FIELD_OFF)
            for q in IDS if q in done or q != "QC-003"
        },
    } for done, isolate, current in scenarios]
    proc = subprocess.run(
        [node, "-e", _RUNNER], input=json.dumps(cases), capture_output=True,
        text=True, timeout=60, check=True,
    )
    results = json.loads(proc.stdout)
    assert len(results) == len(scenarios) == 24
    for (done, isolate, current), got in zip(scenarios, results):
        expected = {**current, **M.layer_states(LAYERS, current, done, isolate)}
        assert got == expected, (sorted(done), isolate)
