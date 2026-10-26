"""The opt-in prompt experiments (F2 evidence-first, F3 critique example).

What must hold, arm by arm: off is byte-identical to a build without them; each
arm re-keys exactly the stages whose prompts it changes (so an A/B never serves
one arm's cached read to the other); the F2 reorder moves every field clause
verbatim; and the F3 example is a reply the host's own parsers accept. The flags
are read at import, so the per-arm checks run in a child interpreter. The
comparison script is driven over two synthetic export folders. Hermetic (I-4).
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from drawing_analyzer import critique, cross_qc, digest, prompt_experiments
from drawing_analyzer.absence_check import is_sheet_absence
from drawing_analyzer.digest import parse_findings_detailed, parse_numeric_claims
from drawing_analyzer.models import FINDINGS_PARSE_OK, SheetRef

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
import compare_prompt_experiment as compare  # noqa: E402

# --------------------------------------------------------------------------- #
# Which caches each arm re-keys (child interpreter: flags are import-time)
# --------------------------------------------------------------------------- #

_PROBE = """
import json
import drawing_analyzer.critique as C, drawing_analyzer.cross_qc as X
import drawing_analyzer.digest as D, drawing_analyzer.prompt_experiments as E
from drawing_analyzer.pipeline import _journal_environment
item = C.CRITIQUE_FINDINGS_SCHEMA["properties"]["findings"]["items"]
print(json.dumps({
    "active": list(E.active()),
    "recorded": _journal_environment(model="m", use_batch=False).get("prompt_experiments"),
    "digest": [D.DIGEST_PROMPT_VERSION, D.digest_system_prompt()],
    "critique": [C.CRITIQUE_PROMPT_VERSION, C.CRITIQUE_STRUCTURED_PROMPT_VERSION,
                 json.dumps(C.CRITIQUE_FINDINGS_SCHEMA)],
    "cross_qc": [X.cross_qc_system_prompt(), X.cross_qc_map_system_prompt(),
                 X.CROSS_QC_RECONCILE_SYSTEM_PROMPT],
    "required_first": [k for k in item["properties"] if k in item["required"]][:2],
}))
"""


def _probe(**flags: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("DRAWING_ANALYZER_EXPERIMENT_")}
    env["PYTHONPATH"] = str(_REPO / "src")
    env.update(flags)
    child = subprocess.run([sys.executable, "-c", _PROBE], cwd=_REPO, env=env,
                           capture_output=True, text=True, timeout=120)
    assert child.returncode == 0, child.stderr
    return json.loads(child.stdout)


@pytest.fixture(scope="module")
def baseline() -> dict:
    return _probe()


@pytest.mark.parametrize("flags, active, rekeyed", [
    # A falsy spelling is off: byte-identical everywhere.
    ({prompt_experiments.QUOTE_FIRST_ENV: "0",
      prompt_experiments.CRITIQUE_EXAMPLE_ENV: "no"}, [], set()),
    ({prompt_experiments.QUOTE_FIRST_ENV: "1"}, ["quote_first"],
     {"digest", "critique", "cross_qc"}),
    # The example touches the critique alone, so digests and cross-QC stay warm.
    ({prompt_experiments.CRITIQUE_EXAMPLE_ENV: "true"}, ["critique_example"],
     {"critique"}),
])
def test_each_arm_rekeys_exactly_the_stages_it_changes(baseline, flags, active, rekeyed):
    arm = _probe(**flags)
    assert arm["active"] == active
    # The run record names the arm, and a baseline run's record is unchanged.
    assert arm["recorded"] == (",".join(active) or None)
    changed = {stage for stage in ("digest", "critique", "cross_qc")
               if arm[stage] != baseline[stage]}
    assert changed == rekeyed
    # Every changed stage changes its cache identity, not only its text: the
    # version hashes are what the keys are built from.
    if "digest" in changed:
        assert arm["digest"][0] != baseline["digest"][0]
    if "critique" in changed:
        assert arm["critique"][0] != baseline["critique"][0]
        assert arm["critique"][1] != baseline["critique"][1]


def test_quote_first_moves_the_quote_ahead_of_the_judgment_in_structured_replies(baseline):
    # Structured outputs emit required properties first, in schema order.
    assert baseline["required_first"] == ["sheet_id", "category"]
    arm = _probe(**{prompt_experiments.QUOTE_FIRST_ENV: "1"})
    assert arm["required_first"] == ["sheet_id", "source_quote"]


# --------------------------------------------------------------------------- #
# The F2 derivation moves clauses, it never rewrites them
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(prompt_experiments.QUOTE_FIRST,
                    reason="this process already runs the evidence-first arm")
@pytest.mark.parametrize("instruction, marker, fields", [
    (digest._FINDINGS_INSTRUCTION, "Each finding is an object with: ",
     ["sheet_id", "category", "severity", "text", "recommended_action",
      "source_quote", "tile_label", "refs"]),
    (critique._CRITIQUE_FINDINGS_INSTRUCTION, "Each finding is an object with: ",
     ["sheet_id", "category", "severity", "text", "recommended_action",
      "source_quote", "anchor_hint", "tile_label", "refs"]),
    (cross_qc._CROSS_QC_FINDINGS_INSTRUCTION, "Each finding is a CROSS-SHEET conflict with: ",
     ["sheet_id", "category", "severity", "text", "recommended_action",
      "source_quote", "also_on", "refs"]),
    (cross_qc._CROSS_QC_MAP_INSTRUCTION, "cross-sheet conflict: ",
     ["sheet_handle", "category", "severity", "text", "recommended_action",
      "source_quote", "also_on", "refs"]),
    (cross_qc.CROSS_QC_RECONCILE_SYSTEM_PROMPT, "Each finding: ",
     ["sheet_handle", "category", "severity", "text", "recommended_action",
      "source_quote", "also_on", "refs"]),
], ids=["digest", "critique", "cross_qc", "cross_qc_map", "cross_qc_reconcile"])
def test_evidence_first_reorders_every_clause_verbatim(instruction, marker, fields):
    start = instruction.index(marker) + len(marker)
    end, clauses = prompt_experiments._clause_list_span(instruction, start)
    # The splitter found exactly the fields the host validates, in prompt order.
    assert [prompt_experiments._field_name(c) for c in clauses] == fields

    variant = prompt_experiments.evidence_first(instruction, marker)
    evidence = [f for f in prompt_experiments.EVIDENCE_FIELDS if f in fields]
    expected = [fields[0], *evidence, *(f for f in fields[1:] if f not in evidence)]
    by_name = {prompt_experiments._field_name(c): c for c in clauses}
    assert variant == (
        instruction[:start] + "; ".join(by_name[f] for f in expected) + instruction[end:]
    )
    # Idempotent: an already-reordered prompt is left as it is.
    assert prompt_experiments.evidence_first(variant, marker) == variant


def test_evidence_first_refuses_a_marker_it_cannot_place():
    with pytest.raises(ValueError):
        prompt_experiments.evidence_first(digest._FINDINGS_INSTRUCTION, "no such marker: ")


# --------------------------------------------------------------------------- #
# The F3 example teaches a reply the host accepts
# --------------------------------------------------------------------------- #

def test_critique_example_is_a_reply_the_host_parsers_accept():
    block = critique._critique_example_block()
    body = block.split(":\n", 1)[1].rsplit("\n</example>", 1)[0]
    ref = SheetRef(pdf_path=Path("x.pdf"), page_index=0, source_name="x.pdf",
                   page_count=1, source_id="SRC-0001")
    parsed = parse_findings_detailed(body, ref, rows=3, cols=4, bare_json=True)
    assert parsed.status in FINDINGS_PARSE_OK
    assert parsed.raw_item_count == len(parsed.findings) == 2   # nothing dropped
    quoted, absence = parsed.findings
    assert quoted.source_quote and quoted.tile == [1, 2]          # "r2c3", zero-based
    assert not absence.source_quote and is_sheet_absence(absence)
    claim, = parse_numeric_claims(body, ref, bare_json=True)
    assert claim.kind == "sum"


# --------------------------------------------------------------------------- #
# The comparison script
# --------------------------------------------------------------------------- #

def _export(folder: Path, *, experiments: str | None, findings: list[dict],
            dropped: int = 0, sources=(("set.pdf", 3, 1000),)) -> Path:
    folder.mkdir(parents=True)
    environment = {"python": "3.12"}
    if experiments:
        environment["prompt_experiments"] = experiments
    (folder / "run_manifest.json").write_text(json.dumps({
        "run": {"environment": environment},
        "sources": [{"display_name": n, "page_count": p, "byte_size": b}
                    for n, p, b in sources],
    }), encoding="utf-8")
    (folder / "findings.json").write_text(json.dumps({"findings": findings}),
                                          encoding="utf-8")
    (folder / "diagnostics").mkdir()
    with open(folder / "diagnostics" / "events.csv", "w", encoding="utf-8-sig",
              newline="") as fp:
        w = csv.DictWriter(fp, fieldnames=["sequence", "event_code", "fields"])
        w.writeheader()
        w.writerow({"sequence": 1, "event_code": "SHEET_DIGESTED",
                    "fields": "sheet=p1; parser_note=dropped "
                              f"{dropped} invalid finding(s)" if dropped else "sheet=p1"})
        w.writerow({"sequence": 2, "event_code": "SHEET_DIGESTED", "fields": "sheet=p2"})
    return folder


def _f(status: str, quote: str = "Q", *sources: str) -> dict:
    return {"anchor": {"status": status}, "source_quote": quote,
            "sources": list(sources) or ["digest_json"]}


def test_comparison_reports_the_adoption_metrics_and_applies_the_rule(tmp_path):
    base = _export(tmp_path / "a", experiments=None, dropped=2, findings=[
        _f("EXACT"), _f("UNANCHORED"), _f("UNANCHORED", "Q", "critique_1", "critique_2"),
        _f("UNANCHORED", ""),  # no quote: not the hallucinated-quote signal
    ])
    variant = _export(tmp_path / "b", experiments="quote_first", dropped=1, findings=[
        _f("EXACT"), _f("FUZZY"), _f("UNANCHORED", "Q", "critique_1"), _f("TILE", ""),
    ])
    a, b = compare.load_arm(base), compare.load_arm(variant)
    assert (a["experiments"], b["experiments"]) == ("none", "quote_first")
    assert (a["quoted"], a["quoted_unanchored"]) == (3, 2)
    assert (b["quoted"], b["quoted_unanchored"]) == (3, 1)
    assert a["channels"] == {"critique": 1, "digest_json": 3}     # two runs, one channel
    assert (a["digest_dropped_invalid"], b["digest_dropped_invalid"]) == (2, 1)
    assert compare.verdict(a, b)[0] == "ADOPT"

    # More findings fails the rule even when quotes anchor better.
    more = _export(tmp_path / "c", experiments="quote_first", findings=[
        *[_f("EXACT")] * 5,
    ])
    decision, reasons = compare.verdict(a, compare.load_arm(more))
    assert decision == "KEEP BASELINE" and any("rose" in r for r in reasons)


def test_comparison_refuses_exports_of_different_inputs(tmp_path, capsys):
    base = _export(tmp_path / "a", experiments=None, findings=[])
    other = _export(tmp_path / "b", experiments="quote_first", findings=[],
                    sources=(("other.pdf", 3, 1000),))
    assert compare.main([str(base), str(other)]) == 2
    assert compare.main([str(base), str(base)]) == 0
