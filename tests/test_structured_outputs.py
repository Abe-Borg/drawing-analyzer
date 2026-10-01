"""Structured outputs & strict tool use (F-01 / F-03) + the effort registry (F-06).

Three changes land here, and the property most of these tests defend is the
same for all three: **nothing changes unless it is asked for.** The pipeline's
caches hold model reads that cost real money per sheet, and every one of them is
keyed on the request shape, so a change that silently moves a prompt version, an
effort level, or a cache key is not a refactor — it is a bill. Several tests
below therefore assert byte-identity rather than behaviour.

Hermetic (I-4): no key, no network, no real schema compiler. What *cannot* be
proved here is whether Anthropic honours ``output_config.format`` on a 37-image
vision request — that is undocumented upstream and needs one live call, which is
why the feature ships opt-in and ``tests/test_live_api_canary.py`` carries the
network-marked proof.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)

from drawing_analyzer import critique as C
from drawing_analyzer import digest as D
from drawing_analyzer import investigate as I
from drawing_analyzer import prose_harvest as H
from drawing_analyzer import verify as V
from drawing_analyzer.core import structured_outputs as SO
from drawing_analyzer.core.api_config import model_supports_structured_outputs
from drawing_analyzer.core import api_config as api
from drawing_analyzer.digest_cache import critique_cache_key, critique_cache_key_level1
from drawing_analyzer.models import FINDINGS_PARSE_OK, Finding, ImageTile, RenderedSheet, SheetRef

OPUS_5 = api.MODEL_OPUS_5
SONNET_5 = api.MODEL_SONNET_5
SONNET_46 = api.MODEL_SONNET_46
HAIKU = api.MODEL_HAIKU_45

# JSON-Schema keywords the structured-outputs compiler rejects outright. A
# schema carrying one is a 400, and on the critique path a 400 is a lost sheet.
UNSUPPORTED_SCHEMA_KEYWORDS = (
    "minimum",
    "maximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "maxItems",
    "pattern",
)


def _rendered(sheet_text: str = "VAV-3 SERVES ROOM 120") -> RenderedSheet:
    ref = SheetRef(pdf_path=Path("s.pdf"), page_index=0, source_name="s.pdf", page_count=1)
    return RenderedSheet(
        ref=ref,
        overview=ImageTile(png_bytes=b"OVERVIEW", width_px=100, height_px=80, kind="overview"),
        tiles=[ImageTile(png_bytes=b"TILE00", width_px=50, height_px=40, kind="tile",
                         row=0, col=0, label="r1c1")],
        page_width_pt=792, page_height_pt=612, rows=1, cols=1, sheet_text=sheet_text,
    )


def _iter_schema_objects(node):
    """Yield every ``{"type": "object"}`` subschema, however nested."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _iter_schema_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_schema_objects(item)


# --------------------------------------------------------------------------- #
# F-06 — effort resolves through the phase registry
# --------------------------------------------------------------------------- #


def test_digest_effort_comes_from_the_registry_not_a_literal():
    # The bug this closes: the registry declared PHASE_REVIEW at xhigh while
    # digest/critique sent a hardcoded "high", and nothing read the registry, so
    # the two never had to agree. Tuning the registry changed no request.
    assert D.DEFAULT_DIGEST_EFFORT == api.default_effort_for_phase(api.PHASE_REVIEW)
    assert C.DEFAULT_CRITIQUE_EFFORT == D.DEFAULT_DIGEST_EFFORT


def test_wiring_the_registry_up_did_not_change_the_request():
    # Raising PHASE_REVIEW would be a cost increase on the highest-volume calls
    # AND a cache-wide invalidation (effort is a cache-key component). The wiring
    # was allowed to land precisely because it is byte-identical.
    assert D.DEFAULT_DIGEST_EFFORT == "high"
    params = D.build_digest_request_params([], model=OPUS_5)
    assert params["output_config"] == {"effort": "high"}


@pytest.mark.parametrize("build", [D.build_digest_request_params, C.build_critique_request_params])
def test_caller_supplied_effort_is_clamped_to_the_model(build):
    # An override is a 400 at submit exactly as a registry default would be, so
    # it gets the same clamp. Sonnet 4.6 accepts `max` but rejects `xhigh`.
    params = build([], model=SONNET_46, effort="xhigh")
    assert params["output_config"] == {"effort": "high"}
    assert build([], model=OPUS_5, effort="xhigh")["output_config"] == {"effort": "xhigh"}


def test_effort_is_still_omitted_for_models_without_support():
    assert "output_config" not in D.build_digest_request_params([], model=HAIKU)


# --------------------------------------------------------------------------- #
# F-03 — strict investigation tool schemas
# --------------------------------------------------------------------------- #


def test_strict_tools_declare_the_flag_and_close_their_objects():
    tools = I.investigation_tools()
    assert [t["name"] for t in tools] == ["crop_region", "find_text", "view_sheet"]
    for tool in tools:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False


def test_strict_schemas_carry_no_keyword_the_compiler_rejects():
    # The whole point of the rewrite. rect's minItems/maxItems, dpi's
    # minimum/maximum, query's minLength and page_number's minimum are all
    # unsupported under strict: sending them is a 400, not a stricter schema.
    blob = json.dumps(I.investigation_tools())
    for keyword in UNSUPPORTED_SCHEMA_KEYWORDS:
        assert keyword not in blob, f"{keyword} is rejected by the schema compiler"


def test_the_constraints_survive_as_prose_in_the_descriptions():
    # Dropping a keyword must not drop the rule. The model still needs to be
    # told, and the host still enforces it.
    tools = {t["name"]: t for t in I.investigation_tools()}
    props = tools["crop_region"]["input_schema"]["properties"]
    assert "4 numbers" in props["rect"]["description"]
    assert "72-300" in props["dpi"]["description"]
    assert "2 characters" in tools["find_text"]["input_schema"]["properties"]["query"]["description"]


def test_strict_cannot_promise_rect_length_so_the_host_check_still_fires():
    # The finding that motivated F-03 wanted strict to guarantee "a 4-number
    # array". It cannot: maxItems is unsupported and minItems is capped at 1, so
    # a 3-number rect is SCHEMA-VALID and still reaches the host. This test
    # exists so nobody deletes the host check believing the schema covers it.
    schema = I.investigation_tools()[0]["input_schema"]["properties"]["rect"]
    assert set(schema) == {"type", "items", "description"}, (
        "rect must not regrow a length constraint the schema compiler rejects"
    )

    executor = I._ToolExecutor(
        finding=Finding(sheet_id="M-101", source_name="s.pdf", page_index=0,
                        category="conflict", severity="high", text="t",
                        source_quote="q"),
        sheet=_rendered(), sheet_id_map={}, evidence_dir=None, dir_name="d",
        next_leg_index=0, render_fn=lambda *a, **k: b"PNG",
    )
    for schema_valid_but_wrong in ([1.0, 2.0, 3.0], [], [1.0, 2.0, 3.0, 4.0, 5.0]):
        content, is_error = executor.execute("crop_region", {"rect": schema_valid_but_wrong})
        assert is_error is True, f"host must still reject {schema_valid_but_wrong!r}"
        assert "x0, y0, x1, y1" in content


def test_relax_strict_tools_reproduces_the_pre_strict_shape_exactly():
    assert I.relax_strict_tools(I.investigation_tools()) == I.investigation_tools(strict=False)


def test_relaxing_preserves_the_cache_breakpoint():
    # The latch relaxes the list it already has rather than rebuilding it,
    # because rebuilding would drop the cache_control breakpoint tools_with_cache
    # placed on the last entry and silently un-cache the tool block.
    tools = api.tools_with_cache(I.investigation_tools(), phase=api.PHASE_INVESTIGATION)
    assert "cache_control" in tools[-1]
    assert "cache_control" in I.relax_strict_tools(tools)[-1]


def test_relaxing_does_not_mutate_the_caller_list():
    tools = I.investigation_tools()
    I.relax_strict_tools(tools)
    assert tools[0]["strict"] is True
    assert tools[0]["input_schema"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "message, expected",
    [
        ("tools.0.input_schema: additionalProperties must be false", True),
        ("strict mode is not supported for this model", True),
        ("credit balance is too low", False),
    ],
)
def test_strict_rejection_is_recognised_only_on_a_400(message, expected):
    class _Err(Exception):
        def __init__(self, status_code, msg):
            super().__init__(msg)
            self.status_code = status_code

    assert I._is_strict_tools_rejection(_Err(400, message)) is expected
    # A 529 naming the same words is an overload blip, not a capability answer.
    assert I._is_strict_tools_rejection(_Err(529, message)) is False


def test_the_two_latches_do_not_share_a_vocabulary():
    # One shared marker list would have a strict 400 disabling task budgets, or
    # the reverse — each latch silently turning off the wrong feature.
    assert not set(I._STRICT_TOOLS_REJECTION_MARKERS) & set(I._TASK_BUDGET_REJECTION_MARKERS)


def test_strict_is_gated_on_the_capability_not_the_model_family():
    assert api.model_supports_structured_outputs(OPUS_5) is True
    assert api.model_supports_structured_outputs(SONNET_5) is True
    assert api.model_supports_structured_outputs(HAIKU) is True
    # Sonnet 4.6 is a current model that is NOT on the roster — exactly the case
    # a generation-shaped check gets wrong.
    assert api.model_supports_structured_outputs(SONNET_46) is False
    assert api.model_supports_structured_outputs("some-future-model") is False


# --------------------------------------------------------------------------- #
# F-01 — critique structured outputs, opt-in
# --------------------------------------------------------------------------- #


def test_structured_outputs_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", raising=False)
    assert C.critique_structured_outputs_enabled(OPUS_5) is False


def test_off_by_default_leaves_the_request_byte_identical(monkeypatch):
    monkeypatch.delenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", raising=False)
    params = C.build_critique_request_params([], model=OPUS_5)
    assert params["output_config"] == {"effort": "high"}
    assert "format" not in params["output_config"]
    assert params["system"] == C.critique_system_prompt()


def test_enabling_it_requires_env_and_capability(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    assert C.critique_structured_outputs_enabled(OPUS_5) is True
    assert C.critique_structured_outputs_enabled(SONNET_46) is False


def test_the_schema_rides_output_config_without_evicting_effort():
    # format and effort share one dict. Assigning a fresh dict here would drop
    # the effort level on every structured request — a quality regression
    # wearing a formatting change's clothes.
    params = C.build_critique_request_params([], model=OPUS_5, structured=True)
    assert params["output_config"]["effort"] == "high"
    assert params["output_config"]["format"] == {
        "type": "json_schema",
        "schema": C.CRITIQUE_FINDINGS_SCHEMA,
    }


def test_the_structured_instruction_is_derived_never_duplicated():
    # Two hand-maintained copies of this text is the drift this codebase has
    # already paid for once. The structured form must be a substitution on the
    # canonical one, so every semantic rule has a single author.
    assert C._CRITIQUE_STRUCTURED_INSTRUCTION != C._CRITIQUE_FINDINGS_INSTRUCTION
    for rule in (
        "cite conservatively",
        "COPY VERBATIM",
        "at most 40 findings",
        "Never compute",
        "one of sum, product, factor",
    ):
        assert rule in C._CRITIQUE_FINDINGS_INSTRUCTION
        assert rule in C._CRITIQUE_STRUCTURED_INSTRUCTION


def test_the_structured_instruction_never_asks_for_a_fence():
    # Telling the model to emit a fenced block while constraining it to a schema
    # that forbids one is the one combination that must be impossible.
    for phrase in ("fenced code block", "inside the block"):
        assert phrase not in C._CRITIQUE_STRUCTURED_INSTRUCTION
    assert "fenced code block" in C._CRITIQUE_FINDINGS_INSTRUCTION  # unchanged


def test_critique_schema_carries_no_keyword_the_compiler_rejects():
    blob = json.dumps(C.CRITIQUE_FINDINGS_SCHEMA)
    for keyword in UNSUPPORTED_SCHEMA_KEYWORDS:
        assert keyword not in blob


def test_every_object_in_the_schema_is_closed():
    objects = list(_iter_schema_objects(C.CRITIQUE_FINDINGS_SCHEMA))
    assert len(objects) == 3  # root, finding item, claim item
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert "required" in obj


def test_the_40_finding_cap_stays_a_prose_rule():
    # maxItems is unsupported, so the cap cannot be expressed in the schema and
    # must remain in the instruction (and enforced host-side).
    assert "maxItems" not in json.dumps(C.CRITIQUE_FINDINGS_SCHEMA)
    assert "at most 40 findings" in C._CRITIQUE_STRUCTURED_INSTRUCTION


def test_optional_finding_fields_stay_out_of_required():
    required = C._CRITIQUE_FINDING_ITEM_SCHEMA["required"]
    for optional in ("anchor_hint", "tile_label", "refs"):
        assert optional in C._CRITIQUE_FINDING_ITEM_SCHEMA["properties"]
        assert optional not in required


def test_claim_scalars_accept_string_or_number():
    # The sheet prints both "1,500 SF" and 1500; the model transcribes what it
    # sees and the deterministic auditor parses it. Forcing one JSON type here
    # would make the model choose, which the never-calculates invariant forbids.
    assert C._CRITIQUE_SCALAR_SCHEMA == {"anyOf": [{"type": "string"}, {"type": "number"}]}


# --------------------------------------------------------------------------- #
# F-01 — the bare-JSON parse path
# --------------------------------------------------------------------------- #


def _ref():
    return SheetRef(pdf_path=Path("s.pdf"), page_index=0, source_name="s.pdf", page_count=1)


_BARE = json.dumps({
    "findings": [{
        "sheet_id": "M-101", "category": "conflict", "severity": "high",
        "text": "Duct conflicts with beam.", "recommended_action": "Coordinate with structural.",
        "source_quote": "VAV-3 SERVES ROOM 120",
    }],
    "claims": [{
        "sheet_id": "M-101", "quote": "20 + 20 = 45", "kind": "sum",
        "terms": ["20", "20"], "expected": "45", "note": "column total",
    }],
})


def test_bare_json_parses_only_when_the_caller_asks():
    assert D.parse_findings_detailed(_BARE, _ref()).findings == []
    parsed = D.parse_findings_detailed(_BARE, _ref(), bare_json=True)
    assert len(parsed.findings) == 1
    assert parsed.status in FINDINGS_PARSE_OK


def test_a_structured_response_has_no_prose_to_protect():
    parsed = D.parse_findings_detailed(_BARE, _ref(), bare_json=True)
    assert parsed.prose == ""


def test_claims_ride_the_same_flag_as_findings():
    # findings and claims arrive in ONE object. Reading one bare and the other
    # fenced drops every claim and leaves the auditor reporting arith=0/0,
    # indistinguishable from a sheet that genuinely had none.
    assert D.parse_numeric_claims(_BARE, _ref()) == []
    assert len(D.parse_numeric_claims(_BARE, _ref(), bare_json=True)) == 1


def test_bare_json_never_reinterprets_a_prose_digest():
    # I-2: the digest is prose then a fenced block. A digest that happens to
    # open with a brace must not have its prose zeroed. The digest path never
    # passes the flag, and even when it is passed a fenced block wins.
    prose = '{"note": "not findings"}\n\nSCOPE: mechanical.\n'
    parsed = D.parse_findings_detailed(prose, _ref(), bare_json=True)
    assert parsed.prose == prose  # byte-for-byte, trailing newline included
    assert parsed.status == D.FINDINGS_ABSENT


def test_a_fenced_reply_still_wins_when_structured_was_requested():
    # The safe-degradation path: the constraint did not take, the model emitted
    # a fence anyway, and the ordinary parser handles it without the latch.
    fenced = "```json\n" + _BARE + "\n```"
    parsed = D.parse_findings_detailed(fenced, _ref(), bare_json=True)
    assert len(parsed.findings) == 1
    assert parsed.prose == ""


def test_bare_json_on_unparseable_text_is_still_absent():
    parsed = D.parse_findings_detailed("not json at all", _ref(), bare_json=True)
    assert parsed.status == D.FINDINGS_ABSENT
    assert parsed.findings == []


# --------------------------------------------------------------------------- #
# F-01 — cache identity
# --------------------------------------------------------------------------- #


def _key(**kw):
    return critique_cache_key(
        _rendered(), model=OPUS_5, prompt_version=C.CRITIQUE_PROMPT_VERSION,
        max_tokens=64_000, effort="high", use_thinking=True, runs=2, **kw
    )


def test_a_fenced_run_keys_exactly_as_it_did_before_this_feature():
    # This is what lets F-01 land with no _SCHEMA_VERSION bump: every entry
    # already paid for stays valid, because an unset structured_key is folded in
    # nowhere at all rather than as an empty string.
    assert _key() == _key(structured_key=None)


def test_a_structured_run_keys_differently():
    # A structured read is a different request — different instruction, and a
    # schema the model decoded against — so it must not be served from, or to, a
    # fenced run's entry.
    assert _key(structured_key=C.CRITIQUE_STRUCTURED_PROMPT_VERSION) != _key()


def test_the_structured_key_covers_the_schema_as_well_as_the_prompt(monkeypatch):
    # I-6: editing either half must re-key. The version is a hash over both.
    import hashlib
    expected = hashlib.sha256(
        "\x00".join((
            C._CRITIQUE_STRUCTURED_INSTRUCTION,
            json.dumps(C.CRITIQUE_FINDINGS_SCHEMA, sort_keys=True),
        )).encode("utf-8")
    ).hexdigest()[:16]
    assert C.CRITIQUE_STRUCTURED_PROMPT_VERSION == expected


def test_the_main_prompt_version_is_untouched_by_the_structured_half():
    # Folding the structured instruction into CRITIQUE_PROMPT_VERSION would
    # discard every cached critique in existence — including those of users who
    # never enable this — for a request shape they never sent.
    assert C.CRITIQUE_STRUCTURED_PROMPT_VERSION not in C.CRITIQUE_PROMPT_VERSION
    assert C._CRITIQUE_STRUCTURED_INSTRUCTION not in (
        C.CRITIQUE_SYSTEM_PROMPT + C._CRITIQUE_TASK_INSTRUCTION + C._CRITIQUE_FINDINGS_INSTRUCTION
    )


# --------------------------------------------------------------------------- #
# F-01 — the batch transport stays out of it
# --------------------------------------------------------------------------- #


def test_the_batch_path_never_opts_in(monkeypatch):
    # A batch item's shape is fixed at submit and a rejection surfaces per item,
    # after the whole batch is built and billed — the latch's re-send cannot
    # help. The transport that cannot degrade does not opt in.
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    params = C.build_critique_request_params([], model=OPUS_5, structured=False)
    assert "format" not in params["output_config"]
    source = Path("src/drawing_analyzer/batch_critique.py").read_text(encoding="utf-8")
    assert "structured=False," in source


# --------------------------------------------------------------------------- #
# Self-healing latches — the reason either feature is safe to enable at all
# --------------------------------------------------------------------------- #
#
# Both features are gated on a registry capability, and the registry can only
# say "the API will accept this parameter". Neither Anthropic's docs nor a
# hermetic suite can say whether a schema constraint survives a 37-image vision
# request, and the investigation model is overridable to an id this registry has
# never seen. So both paths must degrade rather than fail: a stage that 400s on
# every call would take the deliverable down with it (I-3).


_GATES = (C.STRUCTURED_OUTPUTS, H.STRUCTURED_OUTPUTS, V.STRUCTURED_OUTPUTS)


@pytest.fixture(autouse=True)
def _reset_latches():
    """Every latch is process-wide by design; a test must not leak its state."""
    for gate in _GATES:
        gate.reset()
    I._strict_tools_available = True
    yield
    for gate in _GATES:
        gate.reset()
    I._strict_tools_available = True


class _Status400(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.status_code = 400


class _LatchClient(BetaClientMixin):
    """Raises a given exception on the first N calls, then returns ``text``."""

    def __init__(self, exc, *, failures=1, text="```json\n{\"findings\": []}\n```"):
        self.captured: list[dict] = []
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.captured.append(kw)
                if len(outer.captured) <= failures:
                    raise exc
                return FakeMessage(
                    content=[FakeTextBlock(text=text)],
                    usage=FakeUsage(input_tokens=10, output_tokens=5),
                )

        self.messages = _Msgs()


def test_a_structured_rejection_degrades_and_still_returns_findings(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    client = _LatchClient(_Status400("output_config.format is not supported"))

    outcome = C._critique_read(
        _rendered(), run_id="critique_1", client=client, model=OPUS_5, sleep=lambda _s: None,
    )

    assert outcome.status == "COMPLETE"          # the sheet was NOT lost
    assert len(client.captured) == 2             # one rejected, one re-sent
    assert "format" in client.captured[0]["output_config"]
    assert "format" not in client.captured[1].get("output_config", {})
    assert C.STRUCTURED_OUTPUTS.available is False   # latched off for the process


def test_the_degraded_retry_keeps_the_effort_level(monkeypatch):
    # The re-send rebuilds the whole request. Dropping effort along with the
    # schema would turn a formatting fallback into a silent quality change.
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    client = _LatchClient(_Status400("json_schema rejected"))
    C._critique_read(_rendered(), run_id="critique_1", client=client,
                     model=OPUS_5, sleep=lambda _s: None)
    assert client.captured[1]["output_config"] == {"effort": "high"}


def test_the_degraded_retry_swaps_the_prompt_back_to_the_fenced_contract(monkeypatch):
    # Re-sending with the fence-free instruction but no schema would leave the
    # model told to emit bare JSON with nothing enforcing it, and the fenced
    # parser waiting for a block that never comes.
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    client = _LatchClient(_Status400("output_config invalid"))
    C._critique_read(_rendered(), run_id="critique_1", client=client,
                     model=OPUS_5, sleep=lambda _s: None)
    assert client.captured[0]["system"] == C.critique_system_prompt(structured=True)
    assert client.captured[1]["system"] == C.critique_system_prompt(structured=False)


def test_the_structured_retry_does_not_spend_the_transient_budget(monkeypatch):
    # A capability answer is permanent, not a blip. Charging it to max_retries
    # would cost the sheet a real retry on the way to learning something the
    # process now knows for good.
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    client = _LatchClient(_Status400("output_config.format unsupported"))
    outcome = C._critique_read(
        _rendered(), run_id="critique_1", client=client, model=OPUS_5,
        max_retries=0, sleep=lambda _s: None,
    )
    assert outcome.status == "COMPLETE"


def test_an_unrelated_400_is_not_swallowed_by_the_latch(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    client = _LatchClient(_Status400("credit balance is too low"))
    outcome = C._critique_read(
        _rendered(), run_id="critique_1", client=client, model=OPUS_5,
        max_retries=0, sleep=lambda _s: None,
    )
    assert outcome.status == "FAILED"
    assert len(client.captured) == 1
    assert C.STRUCTURED_OUTPUTS.available is True   # nothing was learned


def test_once_latched_off_later_reads_never_ask_again(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    C.STRUCTURED_OUTPUTS.latch_off()
    assert C.critique_structured_outputs_enabled(OPUS_5) is False
    params = C.build_critique_request_params([], model=OPUS_5)
    assert "format" not in params["output_config"]


class _DictCache:
    """Minimal DigestCache stand-in that records what key each put landed on."""

    def __init__(self):
        self.store: dict[str, object] = {}

    def get(self, key):
        return self.store.get(key)

    def put(self, key, entry):
        self.store[key] = entry


def test_a_run_that_degrades_mid_flight_stores_under_the_fenced_key(monkeypatch):
    # The key must describe the request that was actually SENT, not the one the
    # run set out to send. The cache key is built before the reads (to look up)
    # and the latch can flip during them; storing a fenced-produced merge under
    # the structured key would freeze it exactly where the next working
    # structured run looks — serving a result the structured contract never
    # produced. So the store key is recomputed after the reads.
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    cache = _DictCache()
    client = _LatchClient(_Status400("output_config.format is not supported"))

    res = C.critique_sheet_self_consistent(
        _rendered(), client=client, model=OPUS_5, cache=cache,
        runs=1, sleep=lambda _s: None,
    )
    assert res.error is None, res.error
    assert C.STRUCTURED_OUTPUTS.available is False

    (written_key,) = cache.store
    fenced = critique_cache_key(
        _rendered(), model=OPUS_5, prompt_version=C.CRITIQUE_PROMPT_VERSION,
        max_tokens=C.DEFAULT_CRITIQUE_MAX_TOKENS, effort="high",
        use_thinking=True, runs=1, sheet_text="VAV-3 SERVES ROOM 120",
        profiles_key="", structured_key=None,
    )
    structured = critique_cache_key(
        _rendered(), model=OPUS_5, prompt_version=C.CRITIQUE_PROMPT_VERSION,
        max_tokens=C.DEFAULT_CRITIQUE_MAX_TOKENS, effort="high",
        use_thinking=True, runs=1, sheet_text="VAV-3 SERVES ROOM 120",
        profiles_key="", structured_key=C.CRITIQUE_STRUCTURED_PROMPT_VERSION,
    )
    assert written_key == fenced
    assert written_key != structured


def test_a_latched_off_run_never_asks_for_the_schema_again(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS", "1")
    C.STRUCTURED_OUTPUTS.latch_off()
    assert C.critique_structured_outputs_enabled(OPUS_5) is False


def test_the_strict_tools_latch_degrades_and_retries():
    client = _LatchClient(_Status400("tools.0: additionalProperties must be false"))
    kwargs = {
        "model": OPUS_5,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "go"}],
        "tools": api.tools_with_cache(I.investigation_tools(), phase=api.PHASE_INVESTIGATION),
    }

    I._investigation_message(client, kwargs, task_budget=0)

    assert len(client.captured) == 2
    assert client.captured[0]["tools"][0]["strict"] is True
    assert "strict" not in client.captured[1]["tools"][0]
    # The breakpoint must survive the relax, or the closing turn rebuilds the
    # whole tools+system prefix instead of reading it.
    assert "cache_control" in client.captured[1]["tools"][-1]
    assert I._strict_tools_available is False


def test_an_unrelated_400_does_not_disable_strict_tools():
    client = _LatchClient(_Status400("credit balance is too low"))
    kwargs = {
        "model": OPUS_5, "max_tokens": 1024,
        "messages": [{"role": "user", "content": "go"}],
        "tools": I.investigation_tools(),
    }
    with pytest.raises(_Status400):
        I._investigation_message(client, kwargs, task_budget=0)
    assert I._strict_tools_available is True


def test_a_flipped_strict_latch_stops_resending_strict_schemas():
    # `tools` is built once for the whole stage. Without a per-turn re-check, a
    # latch that flipped on the first investigation would keep sending strict
    # schemas on every later turn and pay a 400 plus a retry each time — up to
    # 40 findings x 6 rounds of round trips to re-learn a settled fact.
    tools = I.investigation_tools(strict=I._strict_tools_available)
    assert tools[0]["strict"] is True

    I._strict_tools_available = False
    per_turn = tools if I._strict_tools_available else I.relax_strict_tools(tools)
    assert "strict" not in per_turn[0]
    assert per_turn == I.investigation_tools(strict=False)


# --------------------------------------------------------------------------- #
# F-01 — the LEVEL-1 cache key (probed before rendering)
# --------------------------------------------------------------------------- #
#
# The critique cache has two levels. Level 2 keys on the rendered PNG bytes;
# level 1 keys on a pre-render identity so a warm run can skip rasterizing
# entirely. Level 1 answers FIRST, so separating the contracts only at level 2
# closes nothing: a warm run enabling structured outputs would hit a stored
# fenced entry before any render or request and return it, and the feature would
# read as enabled while changing nothing. (Caught in review on the first commit.)


def _l1(**kw):
    return critique_cache_key_level1(
        "render-identity-abc", model=OPUS_5, prompt_version=C.CRITIQUE_PROMPT_VERSION,
        max_tokens=C.DEFAULT_CRITIQUE_MAX_TOKENS, effort="high",
        use_thinking=True, runs=2, **kw
    )


def test_level1_fenced_key_is_unchanged_by_this_feature():
    assert _l1() == _l1(structured_key=None)


def test_level1_separates_structured_from_fenced():
    assert _l1(structured_key=C.CRITIQUE_STRUCTURED_PROMPT_VERSION) != _l1()


def test_level1_and_level2_do_not_collide_on_the_structured_key():
    # Different namespaces must stay different even with the same extra input.
    assert _l1(structured_key=C.CRITIQUE_STRUCTURED_PROMPT_VERSION) != _key(
        structured_key=C.CRITIQUE_STRUCTURED_PROMPT_VERSION
    )


def test_every_level1_call_site_threads_the_structured_key():
    # Structural, over the AST, rather than an assertion about today's two call
    # sites: the bug was a call site that silently omitted the argument, and a
    # test naming the current ones cannot see the next one added.
    import ast

    source = Path("src/drawing_analyzer/pipeline.py").read_text(encoding="utf-8")
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "critique_cache_key_level1"
    ]
    assert calls, "expected the pipeline to build level-1 critique keys"
    for call in calls:
        assert "structured_key" in {kw.arg for kw in call.keywords}, (
            f"critique_cache_key_level1 at pipeline.py:{call.lineno} omits "
            "structured_key — a warm structured run would serve a fenced result"
        )


def test_the_strict_latch_relaxes_even_once_already_flipped():
    # The guard must not be gated on the latch. Gated, recovery was a
    # once-per-process trick: any later turn still carrying strict schemas hit a
    # guard already False and re-raised the error the latch exists to absorb.
    I._strict_tools_available = False
    client = _LatchClient(_Status400("tools.0: additionalProperties must be false"))
    kwargs = {
        "model": OPUS_5, "max_tokens": 1024,
        "messages": [{"role": "user", "content": "go"}],
        "tools": I.investigation_tools(),          # strict, despite the flipped latch
    }

    I._investigation_message(client, kwargs, task_budget=0)

    assert len(client.captured) == 2
    assert "strict" not in client.captured[1]["tools"][0]


# --------------------------------------------------------------------------- #
# The shared per-stage gate (core.structured_outputs)
# --------------------------------------------------------------------------- #
#
# The critique wrote the rules (env opt-in -> capability -> self-healing latch
# -> cache-key isolation); the harvest and the verifier reuse them through one
# class instead of restating them. The properties below are the ones a restated
# copy would drift on.


class _Err(Exception):
    def __init__(self, status_code, msg):
        super().__init__(msg)
        self.status_code = status_code


def test_gate_is_off_without_its_env_var(monkeypatch):
    monkeypatch.delenv("X_TEST_GATE", raising=False)
    assert SO.StructuredOutputsGate("test", "X_TEST_GATE").enabled(OPUS_5) is False


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("true", True), ("YES", True), (" on ", True),
     ("0", False), ("", False), ("no", False), ("enabled", False)],
)
def test_gate_reads_the_usual_truthy_spellings(monkeypatch, raw, expected):
    monkeypatch.setenv("X_TEST_GATE", raw)
    assert SO.StructuredOutputsGate("test", "X_TEST_GATE").enabled(OPUS_5) is expected


def test_gate_requires_the_capability_not_the_env_alone(monkeypatch):
    monkeypatch.setenv("X_TEST_GATE", "1")
    gate = SO.StructuredOutputsGate("test", "X_TEST_GATE")
    assert gate.enabled(OPUS_5) is True
    assert gate.enabled(SONNET_46) is False          # current model, not on the roster
    assert gate.enabled("some-future-model") is False


def test_gate_latch_is_permanent_until_reset(monkeypatch):
    monkeypatch.setenv("X_TEST_GATE", "1")
    gate = SO.StructuredOutputsGate("test", "X_TEST_GATE")
    gate.latch_off()
    assert gate.available is False and gate.enabled(OPUS_5) is False
    gate.reset()
    assert gate.enabled(OPUS_5) is True


def test_the_three_stage_gates_are_distinct_instances():
    # A vision rejection on the critique must not turn off the text-only
    # harvest, and a harvest rejection must not turn off the verifier.
    assert len({id(g) for g in _GATES}) == 3
    assert len({g.env_var for g in _GATES}) == 3
    assert len({g.stage for g in _GATES}) == 3


def test_gate_latches_are_per_stage(monkeypatch):
    for gate in _GATES:
        monkeypatch.setenv(gate.env_var, "1")
    C.STRUCTURED_OUTPUTS.latch_off()
    assert C.critique_structured_outputs_enabled(OPUS_5) is False
    assert H.harvest_structured_outputs_enabled(SONNET_5) is True
    assert V.verify_structured_outputs_enabled(SONNET_5) is True
    H.STRUCTURED_OUTPUTS.latch_off()
    assert V.verify_structured_outputs_enabled(SONNET_5) is True


@pytest.mark.parametrize(
    "message, expected",
    [
        ("output_config.format is not supported", True),
        ("json_schema: unsupported keyword", True),
        ("Structured Output is unavailable for this model", True),
        ("credit balance is too low", False),
    ],
)
def test_gate_rejection_is_recognised_only_on_a_400(message, expected):
    assert SO.is_structured_outputs_rejection(_Err(400, message)) is expected
    # A 529 naming the same words is an overload blip, not a capability answer.
    assert SO.is_structured_outputs_rejection(_Err(529, message)) is False
    # No status at all (a connection error) is never a capability answer.
    assert SO.is_structured_outputs_rejection(Exception(message)) is False


def test_the_critique_gate_keeps_its_public_surface():
    # ``critique_structured_outputs_enabled`` and the env var are what the
    # pipeline, the README and the canary name; the refactor must not move them.
    assert C.STRUCTURED_OUTPUTS.env_var == "DRAWING_ANALYZER_CRITIQUE_STRUCTURED_OUTPUTS"
    assert C.STRUCTURED_OUTPUTS.stage == "critique"


def test_attach_format_merges_and_detach_restores_byte_for_byte():
    params = {"model": OPUS_5, "output_config": {"effort": "high"}}
    SO.attach_format(params, {"type": "object"})
    assert params["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    SO.detach_format(params)
    assert params == {"model": OPUS_5, "output_config": {"effort": "high"}}


def test_detach_format_drops_an_output_config_it_emptied():
    # A model without effort support had no output_config before the schema;
    # the degraded re-send must not carry an empty one the plain request lacks.
    params = {"model": HAIKU}
    SO.attach_format(params, {"type": "object"})
    SO.detach_format(params)
    assert params == {"model": HAIKU}


# --------------------------------------------------------------------------- #
# Prose harvest — structured outputs, opt-in
# --------------------------------------------------------------------------- #

_HARVEST_REF = SheetRef(
    pdf_path=Path("s.pdf"), page_index=0, source_name="s.pdf", page_count=1,
    source_id="SRC-0001",
)
_HARVEST_ITEM = json.dumps({
    "sheet_id": "M-101", "category": "coordination", "severity": "low",
    "text": "Riser check valve is not on the plan.", "source_quote": "",
    "tile": None, "refs": [],
})
_HARVEST_FENCED = "```json\n" + _HARVEST_ITEM + "\n```"


def _harvest_one(client, *, cache=None, model=SONNET_5):
    return H._structure_item(
        "The riser diagram shows a check valve the plan never draws.", "conflict",
        "CHECK VALVE AT RISER", _HARVEST_REF, "M-101",
        client=client, model=model, max_retries=0, sleep=lambda _s: None, cache=cache,
    )


def test_harvest_structured_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv(H.STRUCTURED_OUTPUTS.env_var, raising=False)
    assert H.harvest_structured_outputs_enabled(SONNET_5) is False
    client = _LatchClient(None, failures=0, text=_HARVEST_FENCED)
    finding, *_ = _harvest_one(client)
    assert finding is not None
    (kw,) = client.captured
    assert kw["system"] == H.HARVEST_SYSTEM_PROMPT
    assert "format" not in kw.get("output_config", {})


def test_harvest_structured_request_carries_the_schema_and_keeps_everything_else(monkeypatch):
    monkeypatch.delenv(H.STRUCTURED_OUTPUTS.env_var, raising=False)
    plain_client = _LatchClient(None, failures=0, text=_HARVEST_FENCED)
    _harvest_one(plain_client)
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    client = _LatchClient(None, failures=0, text=_HARVEST_ITEM)      # bare JSON, no fence
    finding, *_ = _harvest_one(client)
    assert finding is not None and finding.text == "Riser check valve is not on the plan."
    (plain,), (kw,) = plain_client.captured, client.captured
    assert kw["system"] == H.HARVEST_STRUCTURED_SYSTEM_PROMPT
    assert kw["output_config"]["format"] == {
        "type": "json_schema", "schema": H.HARVEST_FINDING_SCHEMA,
    }
    # Only the prompt and the schema differ: effort, thinking, cap, messages
    # are byte-identical to the plain request.
    assert kw["output_config"]["effort"] == plain["output_config"]["effort"]
    strip = lambda d: {k: v for k, v in d.items() if k not in ("system", "output_config")}  # noqa: E731
    assert strip(kw) == strip(plain)


def test_harvest_bare_json_parses_only_under_the_structured_contract(monkeypatch):
    # Today's fenced parser must not start accepting bare objects: a fence is
    # what separates the machine block from prose that merely contains braces.
    monkeypatch.delenv(H.STRUCTURED_OUTPUTS.env_var, raising=False)
    finding, *_ = _harvest_one(_LatchClient(None, failures=0, text=_HARVEST_ITEM))
    assert finding is None
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    finding, *_ = _harvest_one(_LatchClient(None, failures=0, text=_HARVEST_ITEM))
    assert finding is not None


def test_harvest_a_fenced_reply_still_wins_when_structured_was_requested(monkeypatch):
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    fenced = "Here it is:\n" + _HARVEST_FENCED + "\ntrailing prose"
    finding, *_ = _harvest_one(_LatchClient(None, failures=0, text=fenced))
    assert finding is not None


def test_harvest_prompt_is_derived_never_duplicated():
    assert H.HARVEST_STRUCTURED_SYSTEM_PROMPT == H.HARVEST_SYSTEM_PROMPT.replace(
        H._HARVEST_FENCE_SENTENCE, H._HARVEST_FENCE_REPLACEMENT, 1
    )
    assert "fenced" not in H.HARVEST_STRUCTURED_SYSTEM_PROMPT
    assert H.harvest_system_prompt() == H.HARVEST_SYSTEM_PROMPT
    assert H.harvest_system_prompt(structured=True) == H.HARVEST_STRUCTURED_SYSTEM_PROMPT


def test_harvest_schema_is_closed_compiler_safe_and_mirrors_the_prompt():
    blob = json.dumps(H.HARVEST_FINDING_SCHEMA)
    for keyword in UNSUPPORTED_SCHEMA_KEYWORDS:
        assert keyword not in blob
    (root,) = _iter_schema_objects(H.HARVEST_FINDING_SCHEMA)
    assert root["additionalProperties"] is False
    # additionalProperties: false means every field the prompt names must be
    # in the schema, or the grammar forbids what the prose asks for.
    for name in ("sheet_id", "category", "severity", "text", "source_quote", "tile", "refs"):
        assert name in root["properties"] and name in root["required"]
        assert name in H.HARVEST_SYSTEM_PROMPT
    assert set(root["properties"]["category"]["enum"]) == set(D._MODEL_FINDING_CATEGORIES)
    assert set(root["properties"]["severity"]["enum"]) == set(D._FINDING_SEVERITIES)
    assert root["properties"]["tile"] == {"type": "null"}


def test_harvest_structured_version_covers_prompt_and_schema():
    expected = hashlib.sha256("\x00".join((
        H.HARVEST_STRUCTURED_SYSTEM_PROMPT,
        json.dumps(H.HARVEST_FINDING_SCHEMA, sort_keys=True),
    )).encode("utf-8")).hexdigest()[:16]
    assert H.HARVEST_STRUCTURED_PROMPT_VERSION == expected


def test_harvest_structured_key_folds_in_only_when_enabled(monkeypatch):
    def key_for(*, enabled, version):
        if enabled:
            monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
        else:
            monkeypatch.delenv(H.STRUCTURED_OUTPUTS.env_var, raising=False)
        monkeypatch.setattr(H, "HARVEST_STRUCTURED_PROMPT_VERSION", version)
        cache = _DictCache()
        reply = _HARVEST_ITEM if enabled else _HARVEST_FENCED
        _harvest_one(_LatchClient(None, failures=0, text=reply), cache=cache)
        (key,) = cache.store
        return key

    # A fenced key ignores the structured version entirely — byte-identical to
    # every key written before the feature existed.
    assert key_for(enabled=False, version="aaaa") == key_for(enabled=False, version="bbbb")
    # A structured key covers it, and never collides with the fenced key.
    assert key_for(enabled=True, version="aaaa") != key_for(enabled=True, version="bbbb")
    assert key_for(enabled=True, version="aaaa") != key_for(enabled=False, version="aaaa")


def test_harvest_rejection_degrades_and_stores_under_the_fenced_key(monkeypatch):
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    client = _LatchClient(_Status400("output_config.format is not supported"),
                          failures=1, text=_HARVEST_FENCED)
    cache = _DictCache()
    finding, _i, _o, cache_hit, live = _harvest_one(client, cache=cache)
    assert finding is not None and live is True and cache_hit is False
    # One rejected, one re-sent under the fenced contract — with max_retries=0,
    # so the re-send did not spend the transient budget.
    assert len(client.captured) == 2
    first, second = client.captured
    assert "format" in first["output_config"]
    assert first["system"] == H.HARVEST_STRUCTURED_SYSTEM_PROMPT
    assert "format" not in second.get("output_config", {})
    assert second["system"] == H.HARVEST_SYSTEM_PROMPT
    assert second["output_config"]["effort"] == first["output_config"]["effort"]
    assert H.STRUCTURED_OUTPUTS.available is False
    # Stored where a fenced run looks: a plain warm run hits without a call.
    monkeypatch.delenv(H.STRUCTURED_OUTPUTS.env_var, raising=False)
    warm = _LatchClient(None, failures=0, text=_HARVEST_FENCED)
    finding2, _i, _o, hit, live2 = _harvest_one(warm, cache=cache)
    assert finding2 is not None and hit is True and live2 is False
    assert warm.captured == []


def test_harvest_unrelated_400_is_not_swallowed_by_the_latch(monkeypatch):
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    client = _LatchClient(_Status400("credit balance is too low"), failures=1)
    finding, _i, _o, _hit, live = _harvest_one(client)
    assert finding is None and live is True
    assert len(client.captured) == 1
    assert H.STRUCTURED_OUTPUTS.available is True     # nothing was learned


def test_harvest_once_latched_off_never_asks_again(monkeypatch):
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    H.STRUCTURED_OUTPUTS.latch_off()
    client = _LatchClient(None, failures=0, text=_HARVEST_FENCED)
    _harvest_one(client)
    (kw,) = client.captured
    assert "format" not in kw.get("output_config", {})
    assert kw["system"] == H.HARVEST_SYSTEM_PROMPT


def test_harvest_gate_is_on_the_capability_not_the_model_family(monkeypatch):
    monkeypatch.setenv(H.STRUCTURED_OUTPUTS.env_var, "1")
    assert H.harvest_structured_outputs_enabled(SONNET_5) is model_supports_structured_outputs(SONNET_5)
    assert H.harvest_structured_outputs_enabled(SONNET_46) is False
