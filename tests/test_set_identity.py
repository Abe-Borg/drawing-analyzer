"""Phase A §20.1 — the set-identity stage (`set_identity.py`) + its models.

Pure, hermetic unit tests (I-4): the corpus builder and parser are exercised
directly; the stage call uses fake clients from ``fake_anthropic``. No PyMuPDF,
no network — sheets are lightweight ``SheetDigest``/geometry stubs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.digest_cache import DigestCache
from drawing_analyzer.models import AdoptedCode, SetIdentity, SheetRef
from drawing_analyzer.set_identity import (
    _FULL_SLICE_SHEETS,
    _HEADER_SLICE,
    _TOTAL_BUDGET,
    IDENTITY_PROMPT_VERSION,
    IDENTITY_SYSTEM_PROMPT,
    IdentityResult,
    build_identity_user_text,
    identify_set,
    parse_identity_text,
    union_regex_editions,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@dataclass
class _Geom:
    """Just enough geometry for the corpus builder: a ref + a text layer."""

    ref: SheetRef
    sheet_text: str = ""


def _ref(i: int, name: str = "set.pdf") -> SheetRef:
    return SheetRef(
        pdf_path=Path(f"/tmp/{name}"), page_index=i, source_name=name,
        page_count=99, source_id="SRC-0001",
    )


def _sheet(i: int, text: str, *, error: str | None = None) -> SheetDigest:
    return SheetDigest(ref=_ref(i), text=text, error=error)


_PAYLOAD = {
    "disciplines": ["Fire Protection", "electrical"],
    "sheet_disciplines": [
        {"sheet_id": "E-201", "discipline": "Electrical"},
        {"sheet_id": "FP-101", "discipline": "fire protection"},
    ],
    "project_type": "hospital fit-out",
    "set_type": "issued for construction",
    "jurisdiction": "Munich, Bavaria, Germany",
    "country": "Germany",
    "region": "Bavaria",
    "language": "DE",
    "units": "Metric",
    "adopted_codes": [
        {"code": "DIN EN 12845", "edition": "2020", "amendment_note": "",
         "quote": "Sprinkleranlagen nach DIN EN 12845:2020", "source_sheet": "FP-101"},
    ],
    "confidence": "High",
    "evidence": ["DIN EN 12845:2020"],
    "notes": "cover sheet in German",
}


def _identity_reply(payload: dict | None = None) -> str:
    return "```json\n" + json.dumps(payload or _PAYLOAD) + "\n```"


class _FakeClient:
    """Answers every call with a fixed reply; records requests."""

    def __init__(self, reply_text: str):
        self.calls: list[dict] = []
        outer = self

        class _Msgs:
            def create(_self, **kw):
                outer.calls.append(kw)
                return FakeMessage(
                    content=[FakeTextBlock(text=reply_text)],
                    usage=FakeUsage(input_tokens=120, output_tokens=40),
                )

        self.messages = _Msgs()


class _RaisingClient:
    def __init__(self, exc: Exception | None = None):
        self._exc = exc or RuntimeError("permanent failure")
        outer = self

        class _Msgs:
            def create(_self, **kw):
                raise outer._exc

        self.messages = _Msgs()


# --------------------------------------------------------------------------- #
# Corpus builder (pure)
# --------------------------------------------------------------------------- #


def test_corpus_is_deterministic_and_page_ordered():
    sheets = [_sheet(i, f"Sheet X-{i} - Discipline - Title\nbody {i}") for i in range(12)]
    geoms = [_Geom(ref=s.ref, sheet_text=f"TEXT LAYER {i}") for i, s in enumerate(sheets)]
    text1, b1 = build_identity_user_text(sheets, geoms)
    text2, b2 = build_identity_user_text(sheets, geoms)
    assert text1 == text2 and b1.omitted_chars == b2.omitted_chars
    # Page order: sheet 1 appears before sheet 12.
    assert text1.index("Sheet 1/12") < text1.index("Sheet 12/12")
    assert not b1.degraded


def test_corpus_deep_slices_only_for_early_sheets():
    long_body = "A" * 3_000
    sheets = [
        _sheet(i, f"Sheet X-{i} - D - T\n{long_body}") for i in range(_FULL_SLICE_SHEETS + 4)
    ]
    geoms = [_Geom(ref=s.ref, sheet_text="LAYER-" + str(i) + " " + "t" * 500)
             for i, s in enumerate(sheets)]
    text, _ = build_identity_user_text(sheets, geoms)
    # Early sheets carry their text layer verbatim; late sheets do not.
    assert text.count("TEXT LAYER (verbatim") == _FULL_SLICE_SHEETS
    assert "LAYER-0" in text
    assert f"LAYER-{_FULL_SLICE_SHEETS + 2}" not in text
    # A late sheet's digest is capped at the header slice (+ slack for its label).
    late_block = text.split(f"Sheet {_FULL_SLICE_SHEETS + 3}/")[1]
    assert len(late_block.split("=====")[0]) < _HEADER_SLICE + 200


def test_corpus_edition_windows_reach_late_sheets():
    # The adopted-codes statement lives on sheet 40 — far past the deep slices —
    # but its ±window slice must still reach the corpus verbatim.
    sheets = [_sheet(i, f"Sheet X-{i} - D - T\nbody") for i in range(40)]
    geoms = [_Geom(ref=s.ref, sheet_text="") for s in sheets]
    geoms[-1] = _Geom(
        ref=sheets[-1].ref,
        sheet_text="GENERAL NOTES: ALL WORK PER NFPA 13 2016 EDITION AS AMENDED.",
    )
    text, _ = build_identity_user_text(sheets, geoms)
    assert "EDITION MENTIONS" in text
    assert "ALL WORK PER NFPA 13 2016 EDITION" in text
    assert "REGEX-HARVESTED EDITION HINTS: NFPA 13 2016" in text


def test_corpus_edition_windows_reach_international_codes():
    # Codex review (PR #70): a non-US adopted-codes note on a LATE sheet must
    # still get verbatim windows — the US-only citation regex can't see these.
    from drawing_analyzer.set_identity import _edition_windows

    sheets = [_sheet(i, f"Sheet X-{i} - D - T\nbody") for i in range(20)]
    geoms = [_Geom(ref=s.ref, sheet_text="") for s in sheets]
    geoms[-1] = _Geom(
        ref=sheets[-1].ref,
        sheet_text=(
            "ALLGEMEINE HINWEISE: SPRINKLERANLAGEN NACH DIN EN 12845:2020.\n"
            "ELEKTRO NACH IEC 60364."
        ),
    )
    text, _ = build_identity_user_text(sheets, geoms)
    assert "EDITION MENTIONS" in text
    assert "DIN EN 12845:2020" in text
    assert "IEC 60364" in text
    # Direct window checks across families; a year is optional evidence
    # ("designed to BS 9251" counts), and US behavior is unchanged.
    assert _edition_windows("RESIDENTIAL SPRINKLERS DESIGNED TO BS 9251.")
    assert _edition_windows("STRUCTURE PER AS/NZS 1170 2002 LOADING.")
    assert _edition_windows("防火设计符合 GB 50016 (2014).")
    assert _edition_windows("PER NFPA 13 2016.")
    assert _edition_windows("no codes mentioned here at all") == []


def test_corpus_budget_is_loss_aware_never_silent():
    huge = "B" * 6_000
    n = (_TOTAL_BUDGET // (_HEADER_SLICE + 100)) + 60   # comfortably over budget
    sheets = [_sheet(i, f"Sheet X-{i} - D - T\n{huge}") for i in range(n)]
    text, budget = build_identity_user_text(sheets, [])
    assert len(text) <= _TOTAL_BUDGET + 5_000            # bounded (small framing slack)
    assert budget.degraded and budget.omitted_chars > 0
    assert budget.included_chars + budget.omitted_chars == budget.total_chars


def test_corpus_notes_failed_sheets():
    sheets = [_sheet(0, "", error="render exploded")]
    text, _ = build_identity_user_text(sheets, [])
    assert "[digest failed: render exploded]" in text


# --------------------------------------------------------------------------- #
# Parsing + sanitation
# --------------------------------------------------------------------------- #


def test_parse_clean_reply_normalizes_fields():
    si = parse_identity_text(_identity_reply())
    assert si is not None
    assert si.disciplines == ("electrical", "fire protection")   # sorted, lowered
    assert ("E-201", "electrical") in si.sheet_disciplines
    assert si.language == "de" and si.units == "metric"
    assert si.confidence == "high"
    assert si.adopted_codes[0].code == "DIN EN 12845"
    assert si.adopted_codes[0].origin == "model"
    assert si.has_content


def test_parse_takes_last_json_block_and_tolerates_prose():
    text = (
        "Some thinking prose first.\n```json\n{\"unrelated\": 1}\n```\n"
        "more prose\n" + _identity_reply()
    )
    si = parse_identity_text(text)
    assert si is not None and si.country == "Germany"


def test_parse_malformed_returns_none():
    assert parse_identity_text("no json here at all") is None
    assert parse_identity_text("```json\n{broken\n```") is None
    assert parse_identity_text("") is None


def test_parse_partial_fields_default_cleanly():
    si = parse_identity_text('```json\n{"disciplines": ["civil"]}\n```')
    assert si is not None
    assert si.disciplines == ("civil",)
    assert si.jurisdiction == "" and si.adopted_codes == ()
    assert si.has_content


def test_parse_bounds_hostile_payload():
    hostile = {
        "disciplines": [f"d{i}" * 50 for i in range(50)],
        "adopted_codes": [
            {"code": "C" * 500, "quote": "q" * 5_000} for _ in range(200)
        ],
        "evidence": ["e" * 5_000] * 50,
        "notes": "n" * 5_000,
        "confidence": "certainly!!",
    }
    si = parse_identity_text("```json\n" + json.dumps(hostile) + "\n```")
    assert si is not None
    assert len(si.disciplines) <= 12
    assert len(si.adopted_codes) <= 40
    assert all(len(c.code) <= 60 and len(c.quote) <= 200 for c in si.adopted_codes)
    assert len(si.evidence) <= 5 and all(len(e) <= 200 for e in si.evidence)
    assert len(si.notes) <= 400
    assert si.confidence == ""                       # unknown level -> unstated


# --------------------------------------------------------------------------- #
# Regex-union containment (I-7 ordering included)
# --------------------------------------------------------------------------- #


def test_union_appends_regex_only_hits_and_keeps_model_wins():
    si = parse_identity_text(_identity_reply())
    geoms = [
        _Geom(ref=_ref(0), sheet_text="PER NFPA 13 2016 AND DIN EN 12845 2020"),
    ]
    # NFPA 13 2016 is regex-matchable and NOT in the model's list -> appended.
    # DIN EN 12845 is not regex-matchable (non-US token) but the model has it.
    merged = union_regex_editions(si, geoms)
    by_display = {c.display: c for c in merged.adopted_codes}
    assert "NFPA 13 2016" in by_display
    assert by_display["NFPA 13 2016"].origin == "regex"
    assert by_display["DIN EN 12845 2020"].origin == "model"
    # Sorted at construction (I-7): stable order regardless of merge order.
    assert [c.display for c in merged.adopted_codes] == sorted(
        c.display for c in merged.adopted_codes
    )


def test_union_dedupes_case_insensitively():
    si = SetIdentity(adopted_codes=(AdoptedCode(code="NFPA 13", edition="2016"),))
    geoms = [_Geom(ref=_ref(0), sheet_text="nfpa 13 2016")]
    merged = union_regex_editions(si, geoms)
    assert len(merged.adopted_codes) == 1
    assert merged.adopted_codes[0].origin == "model"      # the model entry wins


# --------------------------------------------------------------------------- #
# SetIdentity model surface
# --------------------------------------------------------------------------- #


def test_set_identity_round_trip_and_unknown_keys():
    si = parse_identity_text(_identity_reply())
    data = si.to_dict()
    data["some_future_field"] = {"ignored": True}         # additive serialization
    si2 = SetIdentity.from_dict(data)
    assert si2 == si


def test_context_block_and_citation_line():
    si = parse_identity_text(_identity_reply())
    block = si.context_block()
    assert block.startswith("SET IDENTITY (model-detected):")
    assert "Munich, Bavaria, Germany" in block
    assert "DIN EN 12845 2020" in block and "[per FP-101]" in block
    assert "language: de" in block and "units: metric" in block
    line = si.citation_context_line()
    assert "Munich, Bavaria, Germany" in line and "units metric" in line
    # An empty identity renders an empty citation line and a bare header.
    assert SetIdentity().citation_context_line() == ""
    assert not SetIdentity().has_content


# --------------------------------------------------------------------------- #
# identify_set — the stage call
# --------------------------------------------------------------------------- #


def _one_sheet_setup():
    sheets = [_sheet(0, "Sheet FP-101 - Fire Protection - Plan\nnotes")]
    geoms = [_Geom(ref=sheets[0].ref, sheet_text="PER NFPA 13 2016")]
    return sheets, geoms


def test_identify_set_happy_path_unions_regex():
    sheets, geoms = _one_sheet_setup()
    client = _FakeClient(_identity_reply())
    res = identify_set(sheets, geoms, client=client)
    assert res.ok and not res.cached
    assert res.model_used
    assert res.input_tokens == 120 and res.output_tokens == 40
    # The system prompt is the verbatim constant (test routers key on this).
    assert client.calls[0]["system"] == IDENTITY_SYSTEM_PROMPT
    # Regex union happened on the way out.
    assert any(c.origin == "regex" for c in res.identity.adopted_codes)


def test_identify_set_never_raises_on_client_failure():
    sheets, geoms = _one_sheet_setup()
    res = identify_set(sheets, geoms, client=_RaisingClient())
    assert res.identity is None and not res.ok
    assert "permanent failure" in (res.error or "")


def test_identify_set_unparseable_reply_is_an_error():
    sheets, geoms = _one_sheet_setup()
    res = identify_set(sheets, geoms, client=_FakeClient("total nonsense"))
    assert not res.ok and res.identity is None
    assert "no parseable identity block" in (res.error or "")


def test_identify_set_no_readable_sheets_short_circuits():
    res = identify_set([], [], client=_RaisingClient())
    assert not res.ok and "no readable sheets" in (res.error or "")
    res2 = identify_set([_sheet(0, "", error="boom")], [], client=_RaisingClient())
    assert not res2.ok and "no readable sheets" in (res2.error or "")


def test_identify_set_cache_hit_makes_no_call():
    sheets, geoms = _one_sheet_setup()
    cache = DigestCache(None, persist=False)
    first = identify_set(sheets, geoms, client=_FakeClient(_identity_reply()), cache=cache)
    assert first.ok and not first.cached

    client2 = _FakeClient(_identity_reply())
    second = identify_set(sheets, geoms, client=client2, cache=cache)
    assert second.ok and second.cached
    assert client2.calls == []                       # served without an API call
    # The cached record is the finished (sanitized + unioned) identity.
    assert second.identity == first.identity


def test_identify_set_failure_is_not_cached():
    sheets, geoms = _one_sheet_setup()
    cache = DigestCache(None, persist=False)
    bad = identify_set(sheets, geoms, client=_FakeClient("junk"), cache=cache)
    assert not bad.ok
    good = identify_set(sheets, geoms, client=_FakeClient(_identity_reply()), cache=cache)
    assert good.ok and not good.cached               # the miss re-ran live


def test_prompt_version_is_a_content_hash():
    assert len(IDENTITY_PROMPT_VERSION) == 16
    assert IdentityResult().ok is False


# --------------------------------------------------------------------------- #
# Identity consumers: citation editions/jurisdiction + cross-QC preamble
# --------------------------------------------------------------------------- #


def test_merged_editions_identity_first_regex_backstop():
    from drawing_analyzer.citation_check import merged_editions

    si = parse_identity_text(_identity_reply())        # DIN EN 12845 2020 (model)
    geoms = [_Geom(ref=_ref(0), sheet_text="PER NFPA 13 2016.")]
    line = merged_editions(si, geoms)
    # Identity entries lead; regex-only extras follow as the backstop.
    assert line.index("DIN EN 12845 2020") < line.index("NFPA 13 2016")
    # No identity -> byte-identical to the pre-Phase-A pure-regex line.
    assert merged_editions(None, geoms) == "NFPA 13 2016"
    assert merged_editions(SetIdentity(), geoms) == "NFPA 13 2016"


def test_merged_editions_dedupes_and_carries_amendments():
    from drawing_analyzer.citation_check import merged_editions

    si = SetIdentity(adopted_codes=(
        AdoptedCode(code="NFPA 13", edition="2016", amendment_note="LA amendments"),
    ))
    geoms = [_Geom(ref=_ref(0), sheet_text="NFPA 13 2016")]
    line = merged_editions(si, geoms)
    assert line == "NFPA 13 2016 (LA amendments)"       # regex duplicate folded in


def test_citation_prompt_carries_jurisdiction_line():
    from drawing_analyzer.citation_check import _build_citation_prompt

    with_line = _build_citation_prompt(
        "NFPA 13 §8.1.2", "NFPA 13 2016", [("C1", "relief valve at 150 psi")],
        jurisdiction_line="Munich, Bavaria, Germany; language de; units metric",
    )
    assert "PROJECT JURISDICTION/LOCALE: Munich, Bavaria, Germany" in with_line
    without = _build_citation_prompt(
        "NFPA 13 §8.1.2", "NFPA 13 2016", [("C1", "relief valve at 150 psi")],
    )
    assert "JURISDICTION" not in without                # None -> byte-identical shape


def test_cross_qc_preamble_present_only_with_identity():
    from drawing_analyzer.cross_qc import _identity_preamble

    si = parse_identity_text(_identity_reply())
    pre = _identity_preamble(si)
    assert pre.startswith("SET IDENTITY (model-detected):") and pre.endswith("\n\n")
    assert "units: metric" in pre
    assert _identity_preamble(None) == ""
    assert _identity_preamble(SetIdentity()) == ""      # empty identity adds nothing
