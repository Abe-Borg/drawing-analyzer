"""Hermetic citation dedup, admission budget and resumed-prefix regressions."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from drawing_analyzer import citation_check as citation
from drawing_analyzer.core.api_config import MODEL_SONNET_5_5
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import Finding, Verification
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeServerToolUse,
    FakeServerToolUseBlock,
    FakeTextBlock,
    FakeUsage,
    FakeWebSearchResultBlock,
)


class _Client(BetaClientMixin):
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses
        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(deepcopy(kwargs))
                if outer.responses is not None:
                    return outer.responses[len(outer.calls) - 1]
                return FakeMessage(content=[FakeTextBlock(text=json.dumps({
                    "status": "CHECKED_SUPPORTS", "note": "clause supports claim",
                }))])

        self.messages = _Messages()


def _finding(ref, *, text="Spacing exceeds the limit", severity="medium",
             qc_id="QC-001", status="VERIFIED"):
    return Finding(
        sheet_id=qc_id, source_name="plan.pdf", page_index=0,
        category="code", severity=severity, text=text, refs=[ref], qc_id=qc_id,
        verification=Verification(status=status),
    )


@pytest.mark.parametrize("ref", [
    "NFPA 13 §8.15.1", "NFPA 13 Section 8.15.1", "nfpa 13 8.15.1",
    " NFPA\t13, Sec. 8.15.1. ", "NFPA-13: SECTION 8 . 15 . 1",
    "ＮＦＰＡ １３ §８.１５.１", "NFPA\u00a013; §§ 8.15.1", "(NFPA 13 §8.15.1)",
])
def test_normalization_folds_cosmetic_ref_variants(ref):
    assert citation.normalize_reference(ref) == "nfpa 13 8.15.1"


@pytest.mark.parametrize("other", [
    "NFPA 13 §8.151", "NFPA 13 §8151", "NFPA 13 Table 8.15.1",
    "NFPA 13 Chapter 8.15.1", "NFPA 72 §8.15.1", "NFPA 13 2016 §8.15.1",
    "NFPA 13 §8.15.1(a)", "NFPA 13 §§8.15.1–8.15.2", "NFPA 13 §8/15/1",
])
def test_normalization_preserves_meaningful_ref_differences(other):
    assert citation.normalize_reference(other) != citation.normalize_reference("NFPA 13 §8.15.1")


def test_normalization_folds_edition_wrappers_and_lettered_section_markers():
    assert citation.normalize_reference("NFPA 13 (2016), Sec. A.1(a)") == citation.normalize_reference(
        "nfpa 13 2016 §A.1(a)"
    )


@pytest.mark.parametrize("ref", [
    "NFPA 13-2016 §8.15.1", "nfpa 13 - 2016 Section 8.15.1",
    "NFPA-13-2016 Sec. 8.15.1", "NFPA 13–2016 §8.15.1",
])
def test_normalization_folds_code_edition_hyphens(ref):
    assert citation.normalize_reference(ref) == citation.normalize_reference("NFPA 13 (2016) §8.15.1")


@pytest.mark.parametrize("ref", [
    "NFPA 13 §2016-2019", "NFPA 13 Section 2016–2019",
    "NFPA 13 Sec. 2016.1-2019.1", "NFPA 13-2016.1 §8.15.1",
])
def test_edition_hyphen_normalization_preserves_section_ranges(ref):
    normalized = citation.normalize_reference(ref)
    assert "-" in normalized
    assert normalized != citation.normalize_reference(ref.replace("-", " ").replace("–", " "))


def test_edition_aliases_use_one_budget_slot_and_keep_another_ref_eligible(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "2")
    refs = ["NFPA 13-2016 §8.15.1", "NFPA 13 (2016) Section 8.15.1", "NFPA 13 2016 §8.15.1"]
    findings = [_finding(ref, severity="high", qc_id=f"QC-{i:03d}") for i, ref in enumerate(refs)]
    other = _finding("NFPA 72 §1.1", severity="low", qc_id="QC-004")
    client = _Client()
    result = citation.check_citations([*findings, other], [], client=client)
    assert result.checked == result.requests == len(client.calls) == 2
    assert result.skipped_over_budget == 0 and not result.partial
    assert all(f.citation.status == "CHECKED_SUPPORTS" for f in [*findings, other])
    assert [f.citations[0].reference for f in findings] == refs


def test_edition_alias_warm_run_reuses_one_verdict_cache_entry():
    cache = DigestCache(None, persist=False)
    first = _finding("NFPA 13-2016 §8.15.1")
    citation.check_citations([first], [], client=_Client(), cache=cache)
    second = _finding("NFPA 13 (2016) Section 8.15.1")
    client = _Client()
    result = citation.check_citations([second], [], client=client, cache=cache)
    assert result.cached_requests == 1 and result.requests == 0
    assert client.calls == [] and cache.stats()["size"] == 1
    assert second.citations[0].reference == second.refs[0]


def test_variants_share_claim_assessment_and_keep_original_display():
    refs = ["NFPA 13 §8.15.1", "NFPA 13 Section 8.15.1", "nfpa 13 8.15.1"]
    findings = [_finding(ref, qc_id=f"QC-{i:03d}") for i, ref in enumerate(refs)]
    findings[0].refs.append("NFPA 13 Sec. 8.15.1")
    client = _Client()
    result = citation.check_citations(findings, [], client=client)

    assert result.checked == result.requests == len(client.calls) == 1
    assert result.supports == len(result.by_ref) == len(result.assessments) == 1
    assert set(result.assessments[0].claim_finding_ids) == {f.id for f in findings}
    for finding, ref in zip(findings, refs):
        assert len(finding.citations) == 1
        assert finding.citations[0].reference == ref
        assert finding.refs[0] == ref


def test_variant_warm_run_reuses_normalized_verdict_cache():
    cache = DigestCache(None, persist=False)
    first = _finding("NFPA 13 §8.15.1")
    citation.check_citations([first], [], client=_Client(), cache=cache)
    second = _finding("nfpa 13 Section 8.15.1")
    client = _Client()
    result = citation.check_citations([second], [], client=client, cache=cache)
    assert result.cached_requests == 1 and result.requests == 0
    assert client.calls == []
    assert second.citations[0].reference == second.refs[0]
    assert second.citation.status == "CHECKED_SUPPORTS"


def test_all_rejected_claims_skip_before_cache_and_client(monkeypatch):
    def unexpected(*args):
        pytest.fail("rejected claims must not probe the cache or create a client")

    class _Cache:
        get = unexpected

    monkeypatch.setattr("drawing_analyzer.client.get_client", unexpected)
    findings = [_finding("NFPA 13 §8.15.1", status="REJECTED"),
                _finding("NFPA 13 Sec. 8.15.1", qc_id="QC-002", status="REJECTED")]
    result = citation.check_citations(findings, [], cache=_Cache())
    assert result.checked == result.requests == result.cached_requests == 0
    assert result.skipped_rejected == result.unchecked == 1
    assert result.web_search_requests == result.input_tokens == 0
    assert result.error is None and result.partial
    assert len(result.assessments) == len(result.by_ref) == 1
    assert set(result.assessments[0].claim_finding_ids) == {f.id for f in findings}
    for finding in findings:
        assessment = finding.citations[0]
        assert assessment.status == "UNCHECKED"
        assert "all citing findings are REJECTED" in assessment.note
        assert not assessment.request_id


def test_rejected_only_claim_excluded_while_other_claim_checks_shared_ref():
    active = _finding("NFPA 13 §8.15.1", text="active claim")
    rejected = _finding("nfpa 13 Section 8.15.1", text="rejected-only claim", status="REJECTED")
    client = _Client()
    result = citation.check_citations([rejected, active], [], client=client)
    assert result.requests == result.skipped_rejected == 1
    prompt = client.calls[0]["messages"][0]["content"]
    assert "active claim" in prompt and "rejected-only claim" not in prompt
    assert active.citation.status == "CHECKED_SUPPORTS"
    assert rejected.citation.status == "UNCHECKED"
    assert rejected.id not in active.citations[0].claim_finding_ids


def test_shared_claim_with_one_active_finding_is_checked():
    active = _finding("NFPA 13 §8.15.1")
    rejected = _finding("nfpa 13 Sec. 8.15.1", qc_id="QC-002", status="REJECTED")
    result = citation.check_citations([rejected, active], [], client=_Client())
    assert result.requests == 1 and result.skipped_rejected == 0
    assert not result.partial
    assert active.citation.status == rejected.citation.status == "CHECKED_SUPPORTS"


@pytest.mark.parametrize("order", ["forward", "reverse"])
def test_cap_admits_severity_first_and_discloses_every_tail_claim(monkeypatch, order):
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "2")
    # Deterministic sequential capture makes request order directly testable.
    monkeypatch.setattr(citation, "_MAX_WORKERS", 1)
    low = _finding("NFPA 13 §1.1", severity="low", qc_id="QC-001")
    medium = _finding("NFPA 13 §2.1", severity="medium", qc_id="QC-002")
    later_high = _finding("NFPA 13 §3.1", severity="high", qc_id="QC-004")
    first_high = _finding("NFPA 13 §4.1", severity="high", qc_id="QC-003")
    # Duplicate spelling/claim consumes no extra ref slot or assessment.
    alias = _finding("nfpa 13 Section 4.1", severity="low", qc_id="QC-005")
    # Rejected high severity must not elevate an eligible medium ref.
    rejected_high = _finding(medium.refs[0], text="rejected", severity="high",
                             qc_id="QC-000", status="REJECTED")
    findings = [low, medium, later_high, first_high, alias, rejected_high]
    if order == "reverse":
        findings.reverse()
    client = _Client()
    result = citation.check_citations(findings, [], client=client)
    assert result.ref_budget == result.checked == result.requests == 2
    assert result.skipped_over_budget == result.unchecked == 2
    assert result.skipped_rejected == 1 and result.partial
    prompts = [c["messages"][0]["content"] for c in client.calls]
    assert citation.normalize_reference(first_high.refs[0]) in citation.normalize_reference(prompts[0])
    assert citation.normalize_reference(later_high.refs[0]) in citation.normalize_reference(prompts[1])
    for finding in (low, medium):
        assessment = finding.citations[0]
        assert assessment.status == "UNCHECKED" and not assessment.request_id
        assert "reference budget (2) exceeded" in assessment.note
        assert "DRAWING_ANALYZER_CITATION_MAX_REFS" in assessment.note
    assert first_high.citation.status == later_high.citation.status == alias.citation.status == "CHECKED_SUPPORTS"
    assert len(result.assessments) == 5
    assert len(result.by_ref) == 4
    assert rejected_high.citations[0].note.endswith("all citing findings are REJECTED")


def test_ref_cap_retains_all_claim_chunks_for_an_admitted_ref(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "1")
    monkeypatch.setattr(citation, "_MAX_CLAIMS_PER_REQUEST", 2)
    findings = [_finding("NFPA 13 §8.15.1", text=f"claim {i}") for i in range(5)]
    client = _Client()
    result = citation.check_citations(findings, [], client=client)
    assert result.checked == 1 and result.requests == len(client.calls) == 3
    assert len(result.assessments) == 5 and not result.partial
    assert all(f.citation.status == "CHECKED_SUPPORTS" for f in findings)


def test_default_budget_checks_fifty_refs_and_discloses_remaining_five(monkeypatch):
    monkeypatch.delenv("DRAWING_ANALYZER_CITATION_MAX_REFS", raising=False)
    findings = [_finding(f"NFPA 13 §{i}.1", qc_id=f"QC-{i:03d}") for i in range(1, 56)]
    client = _Client()
    result = citation.check_citations(findings, [], client=client)
    assert result.checked == result.requests == len(client.calls) == 50
    assert result.skipped_over_budget == result.unchecked == 5
    assert len(result.assessments) == len(result.by_ref) == 55
    assert all(f.citation.status == "CHECKED_SUPPORTS" for f in findings[:50])
    assert all(f.citation.status == "UNCHECKED" for f in findings[50:])


def test_zero_cap_skips_before_warm_cache_and_preserves_rejection_reason(monkeypatch):
    cache = DigestCache(None, persist=False)
    active = _finding("NFPA 13 §8.15.1")
    citation.check_citations([active], [], client=_Client(), cache=cache)
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "0")

    def unexpected(*args):
        pytest.fail("zero budget must not probe cache or create client")

    monkeypatch.setattr(cache, "get", unexpected)
    monkeypatch.setattr("drawing_analyzer.client.get_client", unexpected)
    rejected = _finding("NFPA 13 §8.15.2", status="REJECTED")
    result = citation.check_citations([active, rejected], [], cache=cache)
    assert result.checked == result.requests == result.cached_requests == 0
    assert result.skipped_over_budget == result.skipped_rejected == 1
    assert result.unchecked == len(result.assessments) == 2
    assert "budget (0)" in active.citations[0].note
    assert "REJECTED" in rejected.citations[0].note


def test_client_failure_preserves_precomputed_skip_reasons(monkeypatch):
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", "1")

    def unavailable():
        raise RuntimeError("offline")

    monkeypatch.setattr("drawing_analyzer.client.get_client", unavailable)
    selected = _finding("NFPA 13 §1", severity="high")
    capped = _finding("NFPA 13 §2", severity="low")
    rejected = _finding("NFPA 13 §3", status="REJECTED")
    result = citation.check_citations([selected, capped, rejected], [])
    assert result.requests == 0 and result.unchecked == 3 and result.partial
    assert "client unavailable" in selected.citations[0].note
    assert "budget (1)" in capped.citations[0].note
    assert "REJECTED" in rejected.citations[0].note


@pytest.mark.parametrize("raw,expected", [(None, 50), ("5", 5), (" 0 ", 0),
                                          ("-1", 50), ("nope", 50)])
def test_ref_cap_override_validation(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("DRAWING_ANALYZER_CITATION_MAX_REFS", raising=False)
    else:
        monkeypatch.setenv("DRAWING_ANALYZER_CITATION_MAX_REFS", raw)
    assert citation.citation_max_refs() == expected


@pytest.mark.parametrize("dict_blocks", [False, True])
@pytest.mark.parametrize("tool_pairs", [1, 12])
def test_pause_resumes_cache_last_assistant_block_and_preserve_payloads(dict_blocks, tool_pairs):
    responses = []
    for turn in range(3):
        blocks = [FakeTextBlock(text=f"searching {turn}")]
        for pair in range(tool_pairs):
            blocks += [
                FakeServerToolUseBlock(name="web_search", input={"query": f"clause {turn}"},
                                       id=f"server-{turn}-{pair}"),
                FakeWebSearchResultBlock(tool_use_id=f"server-{turn}-{pair}", content=[{
                    "type": "web_search_result", "url": f"https://example.org/{turn}/{pair}",
                    "title": "Clause", "encrypted_content": "opaque-server-payload",
                }]),
            ]
        if dict_blocks:
            blocks = [deepcopy(vars(b)) for b in blocks]
        responses.append(FakeMessage(content=blocks, stop_reason="pause_turn", usage=FakeUsage(
            input_tokens=10, output_tokens=5, cache_creation_input_tokens=20,
            cache_read_input_tokens=30, server_tool_use=FakeServerToolUse(web_search_requests=2),
        )))
    responses.append(FakeMessage(content=[FakeTextBlock(text='{"status":"CHECKED_SUPPORTS"}')]))
    originals = deepcopy(responses)
    client = _Client(responses)
    outcome = citation._check_one(
        "NFPA 13 §8.15.1", "NFPA 13 2025", [("C1", "claim")],
        client=client, model=MODEL_SONNET_5_5, max_retries=0, sleep=lambda _: None,
    )
    assert outcome.error is None
    assert [len(c["messages"]) for c in client.calls] == [1, 2, 3, 4]
    assert outcome.cache_write_tokens == 60 and outcome.cache_read_tokens == 90
    assert outcome.web_search_requests == 6
    for request in client.calls:
        assert request["system"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert request["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assistants = request["messages"][1:]
        marked = [(i, j) for i, m in enumerate(assistants)
                  for j, b in enumerate(m["content"]) if "cache_control" in b]
        assert marked == [(i, 2 * tool_pairs) for i in range(max(0, len(assistants) - 2), len(assistants))]
        assert len(marked) + 2 <= 4  # Including system and tool breakpoints.
        for i, message in enumerate(assistants):
            blocks = deepcopy(message["content"])
            for block in blocks:
                block.pop("cache_control", None)
            expected = [b if isinstance(b, dict) else vars(b) for b in originals[i].content]
            assert blocks == expected  # Keep encrypted tool results and IDs intact.
        if assistants:
            assert assistants[-1]["content"][-1]["cache_control"]["ttl"] == "1h"
    assert responses == originals  # Cache decoration never mutates SDK responses.


def test_resume_sdk_blocks_preserve_thinking_signatures():
    from anthropic.types import TextBlock, ThinkingBlock

    blocks = [ThinkingBlock(type="thinking", thinking="reason", signature="signed"),
              TextBlock(type="text", text="searching")]
    messages = [{"role": "assistant", "content": blocks}]
    cached = citation._resume_messages_with_cache(messages)
    assert cached[0]["content"][0] == {"type": "thinking", "thinking": "reason", "signature": "signed"}
    assert cached[0]["content"][-1]["cache_control"]["ttl"] == "1h"
    assert messages[0]["content"] is blocks
