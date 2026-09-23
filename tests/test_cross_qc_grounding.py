"""Remediation WP-05.1: cross-QC grounding is a real match at word boundaries.

Three defects in the sharded cross-QC validators (`_finding_from_handles`,
`_parse_facts`, both through `classify_quote_evidence`), which decide whether a
leg or fact the model returned is kept, dropped, or kept at reduced trust:

- **B5.** `_grounded` returned True for any quote under six folded characters,
  and the classifier asked it before asking whether the sheet had any text. So
  a short tag (`P-1`, `AHU-1`, `M-101`) was TEXT_GROUNDED on a sheet with no
  text layer and on a sheet that does not print it: a hallucinated tag leg was
  kept and counted as grounded, and on a scanned or hybrid sheet the tile
  fallback (for TEXT_EVIDENCE_UNAVAILABLE only) never fired, so the tags
  cross-QC quotes most went UNANCHORED and never reached verification.
- **N12 (cross-QC part).** At six characters and more `_grounded` was a plain
  substring test, so `AHU-10` grounded inside `AHU-101`.
- **N13.** `_norm_for_match` was `fold_text` only, and disagreed with
  `anchor._normalize` on curly quotes, primes, vulgar fractions, the
  multiplication and diameter signs and infix hyphens, so valid legs were
  dropped as NOT_MATCHED.

The rules, decided by the owner before any code:

- **A match covers whole source words.** A source word is a whitespace-delimited
  run of the sheet's text. Only its leading `( [ { < " '` and trailing
  `) ] } > , ; : . ! ? " '` may stay outside the match; the match may never
  start or end inside what is between them. Defined once in `anchor.py`
  (`word_core`), for WP-05.2 to apply to the anchor's own words.
- **One normalizer.** The evidence is normalized one source word at a time with
  the unchanged `anchor._normalize`, which gives the anchor's exact result and
  the word boundaries together; the tile join uses it too.
- **Any length.** Every non-empty quote gets a real match; there is no length
  below which a quote counts as grounded, or as no quote.

Hermetic: fake clients only, no key, no network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import drawing_analyzer.cross_qc as X
from drawing_analyzer.anchor import _normalize, resolve_anchors, resolve_conflict_legs
from drawing_analyzer.cross_qc import (
    CrossQCDiscardCounts,
    CrossQCFact,
    _finding_from_handles,
    _parse_facts,
    classify_quote_evidence,
    cross_sheet_qc,
    fact_tile_lookup,
)
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.investigate import _candidates
from drawing_analyzer.models import (
    EVIDENCE_NOT_MATCHED,
    EVIDENCE_TEXT_GROUNDED,
    EVIDENCE_UNAVAILABLE,
    SheetGeometry,
    SheetRef,
    Verification,
)
from drawing_analyzer.verify import _has_anchored_legs
from tests.fixtures.fake_anthropic import (
    BetaClientMixin,
    FakeMessage,
    FakeTextBlock,
    FakeUsage,
    StreamingMessagesMixin,
)

W, H = 792.0, 612.0
SHORT_TAGS = ["P-1", "AHU-1", "M-101"]


def _w(x, y, text, w=60, h=12):
    return (float(x), float(y), float(x + w), float(y + h), text, 0, 0, 0)


def _ref(source: str) -> SheetRef:
    return SheetRef(pdf_path=Path(source), page_index=0, source_name=source,
                    page_count=1)


def _geom(source: str, text: str, *, words=None) -> SheetGeometry:
    """A sheet whose uncapped text layer is ``text``; ``""`` is a scanned sheet."""
    if words is None:
        words = [_w(10 + 70 * i, 40, w) for i, w in enumerate(text.split())]
    return SheetGeometry(
        ref=_ref(source), page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=list(words), sheet_text=text, full_sheet_text=text,
        is_raster=not text,
    )


def _entries(**sheets: SheetGeometry) -> dict:
    return {handle: (handle, geom) for handle, geom in sheets.items()}


def _item(primary: str, quote: str, legs: list[tuple[str, str]], **extra) -> dict:
    item = {
        "category": "conflict", "severity": "high", "text": "values disagree",
        "sheet_handle": primary, "source_quote": quote,
        "also_on": [{"sheet_handle": h, "source_quote": q} for h, q in legs],
    }
    item.update(extra)
    return item


# --------------------------------------------------------------------------- #
# B5: a short quote is checked like any other, and no text means unavailable
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tag", SHORT_TAGS)
def test_b5_a_short_tag_on_a_textless_sheet_is_unavailable(tag):
    """Nothing could have matched, so the quote is neither grounded nor refuted."""
    assert classify_quote_evidence(tag, _geom("scan.pdf", "", words=[])) == EVIDENCE_UNAVAILABLE


@pytest.mark.parametrize("tag", SHORT_TAGS)
def test_b5_a_short_tag_the_sheet_prints_is_still_grounded(tag):
    geom = _geom("m.pdf", f"SEE {tag} SCHEDULE FOR CAPACITY")
    assert classify_quote_evidence(tag, geom) == EVIDENCE_TEXT_GROUNDED


def test_b5_a_short_tag_the_sheet_does_not_print_is_not_matched():
    geom = _geom("m.pdf", "AHU-1 AND AHU-2 SERVE LEVEL 2")
    assert classify_quote_evidence("AHU-7", geom) == EVIDENCE_NOT_MATCHED


def test_b5_the_absent_tag_leg_is_dropped_and_counted_as_ungrounded():
    """The hallucinated tag leg is dropped, and the counters say why.

    It used to be kept and counted in ``legs_accepted_grounded``, so the WP-02
    counters were wrong for the most common quote form.
    """
    entries = _entries(
        S001=_geom("a.pdf", "AHU-1 AND AHU-2 SERVE LEVEL 2"),
        S002=_geom("b.pdf", "AHU-7 SUPPLIES 2000 CFM"),
        S003=_geom("c.pdf", "AHU-7 SUPPLIES 2500 CFM"),
    )
    counts = CrossQCDiscardCounts()
    finding = _finding_from_handles(
        _item("S001", "AHU-7", [("S002", "AHU-7 SUPPLIES 2000 CFM"),
                                ("S003", "AHU-7 SUPPLIES 2500 CFM")]),
        entries, counts,
    )
    assert finding is not None, "the two legs that ground still make a conflict"
    assert finding.source_name == "b.pdf", "the dropped primary never became the finding's sheet"
    assert [leg.source_name for leg in finding.also_on] == ["c.pdf"]
    assert counts.legs_ungrounded_quote_text_bearing_sheet == 1
    assert counts.legs_accepted_grounded == 2


def test_b5_a_conflict_left_with_one_grounded_leg_is_dropped():
    entries = _entries(
        S001=_geom("a.pdf", "AHU-1 AND AHU-2 SERVE LEVEL 2"),
        S002=_geom("b.pdf", "AHU-7 SUPPLIES 2000 CFM"),
    )
    counts = CrossQCDiscardCounts()
    finding = _finding_from_handles(
        _item("S001", "AHU-7", [("S002", "AHU-7 SUPPLIES 2000 CFM")]), entries, counts,
    )
    assert finding is None
    assert counts.findings_dropped_under_two_legs == 1
    assert counts.legs_ungrounded_quote_text_bearing_sheet == 1


@pytest.mark.parametrize("tag", SHORT_TAGS)
def test_b5_a_textless_short_tag_leg_reaches_the_tile_fallback_and_verification(tag):
    """Admitted at reduced trust, TILE-anchored, and eligible for the crop check.

    Asserted against the real gatekeepers. Before the fix the leg was
    TEXT_GROUNDED, so the anchor's tile fallback (TEXT_EVIDENCE_UNAVAILABLE
    only) never fired, the leg went UNANCHORED, and no crop check could see it.
    """
    scanned = _geom("scan.pdf", "", words=[])
    other = _geom("b.pdf", f"SEE {tag} SCHEDULE FOR CAPACITY")
    entries = _entries(S001=scanned, S002=other)
    finding = _finding_from_handles(
        _item("S001", tag, [("S002", f"SEE {tag} SCHEDULE")], tile_label="r1c2"),
        entries,
    )
    assert finding is not None
    assert finding.evidence_state == EVIDENCE_UNAVAILABLE
    assert finding.also_on[0].evidence_state == EVIDENCE_TEXT_GROUNDED

    resolve_anchors([finding], scanned)
    resolve_conflict_legs([finding], {("scan.pdf", 0): scanned, ("b.pdf", 0): other})
    assert finding.anchor.status == "TILE"
    assert finding.anchor.method == "tile_no_text_evidence"
    assert finding.also_on[0].anchor.status == "EXACT"
    assert _has_anchored_legs(finding), "the dual-crop check cannot see it"
    finding.verification = Verification(status="UNCERTAIN")
    assert finding in _candidates([finding]), "the investigation loop cannot see it"


@pytest.mark.parametrize("tag", SHORT_TAGS)
def test_b5_a_short_tag_fact_on_a_textless_sheet_is_admitted_at_reduced_trust(tag):
    counts = CrossQCDiscardCounts()
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": tag, "tile_label": "r1c1"}]},
        _entries(S001=_geom("scan.pdf", "", words=[])), {}, counts,
    )
    assert [f.evidence_state for f in facts] == [EVIDENCE_UNAVAILABLE]
    assert facts[0].tile == [0, 0]
    assert counts.facts_admitted_no_text_evidence == 1
    assert counts.facts_accepted == 0


def test_b5_a_short_tag_fact_the_sheet_does_not_print_is_dropped():
    counts = CrossQCDiscardCounts()
    facts = _parse_facts(
        {"facts": [{"sheet_handle": "S001", "exact_quote": "AHU-7"},
                   {"sheet_handle": "S001", "exact_quote": "AHU-1"}]},
        _entries(S001=_geom("a.pdf", "AHU-1 AND AHU-2 SERVE LEVEL 2")), {}, counts,
    )
    assert [f.exact_quote for f in facts] == ["AHU-1"]
    assert counts.facts_ungrounded_quote_text_bearing_sheet == 1
    assert counts.facts_accepted == 1


def test_b5_a_text_layer_of_only_invisible_characters_is_no_text():
    """Usable text is text the normalizer leaves something of."""
    geom = _geom("inv.pdf", "\u200b \u00ad\ufeff", words=[])
    assert classify_quote_evidence("P-1", geom) == EVIDENCE_UNAVAILABLE
    assert X._sheet_is_textless(geom) is True


def test_b5_a_quote_that_normalizes_to_nothing_matches_nothing():
    """Not blank (so not "no quote"), and it cannot be found in any text."""
    assert classify_quote_evidence("\u200b", _geom("m.pdf", "P-1 SERVES AREA A")) == EVIDENCE_NOT_MATCHED
    assert classify_quote_evidence("\u200b", _geom("scan.pdf", "", words=[])) == EVIDENCE_UNAVAILABLE


def test_b5_a_blank_quote_is_still_unavailable_on_every_sheet():
    for geom in (_geom("m.pdf", "P-1 SERVES AREA A"), _geom("scan.pdf", "", words=[])):
        assert classify_quote_evidence("", geom) == EVIDENCE_UNAVAILABLE
        assert classify_quote_evidence("   ", geom) == EVIDENCE_UNAVAILABLE


@pytest.mark.parametrize(("quote", "text", "state"), [
    ("3", "SEE NOTE 3 BELOW", EVIDENCE_TEXT_GROUNDED),
    ("3", "SEE NOTE 30 BELOW", EVIDENCE_NOT_MATCHED),
    ("3", "SEE M-3 AND 3A BELOW", EVIDENCE_NOT_MATCHED),
    ("TYP", "6 IN DRAIN, TYP.", EVIDENCE_TEXT_GROUNDED),
    ("TYP", "6 IN DRAIN TYPICAL", EVIDENCE_NOT_MATCHED),
    ("q", "P-1 SERVES AREA A", EVIDENCE_NOT_MATCHED),
])
def test_b5_any_length_gets_a_real_match(quote, text, state):
    """No length floor: a bare number or word grounds only where it is printed."""
    assert classify_quote_evidence(quote, _geom("m.pdf", text)) == state


# --------------------------------------------------------------------------- #
# N12: a match covers whole source words, at every length
# --------------------------------------------------------------------------- #

_CUT_A_WORD = [
    ("AHU-10", "PROVIDE AHU-101 ON ROOF"),
    ("VAV-2-1", "VAV-2-10 SERVES ROOM 12"),
    ("VAV-2", "VAV-2-1 SERVES ROOM 12"),
    ("AHU-1", "SEE AHU-1-2 SCHEDULE"),
    ("P-1", "PUMP P-10 TYP"),
    ("P-1", "PUMP XP-1 TYP"),
    ("M-101", "SEE M-101A FOR DETAIL"),
    ("SUPPLY FROM AHU-10", "SUPPLY FROM AHU-101 TO LEVEL 2"),
    ("ACCESS PANEL AT VAV-2", "PROVIDE ACCESS PANEL AT VAV-2-1 TYP"),
    ("ROVIDE ACCESS PANEL", "PROVIDE ACCESS PANEL"),
    ("P-2", "PUMPS P-1,P-2 TYP"),
    ("M-102", "SEE M-101/M-102"),
]


@pytest.mark.parametrize(("quote", "text"), _CUT_A_WORD)
def test_n12_a_quote_that_cuts_a_source_word_never_grounds(quote, text):
    geom = _geom("m.pdf", text)
    assert X._grounded(quote, text) is False
    assert classify_quote_evidence(quote, geom) == EVIDENCE_NOT_MATCHED


_WHOLE_WORDS = [
    ("P-1", "PUMPS P-1, P-2 AND P-3"),
    ("P-1", "PUMP (P-1) ON SLAB"),
    ("P-1", "SEE PUMP P-1."),
    ("P-1", "PUMP P-1: 150 GPM"),
    ("NOTE 3", "SEE NOTE 3: PROVIDE ACCESS"),
    ("(P-1)", "PUMP (P-1) ON SLAB"),
    ("VAV-2-1", "VAV-2-1 SERVES ROOM 12"),
    ("VAV-2", "VAV-2 AND VAV-2-1 SERVE ROOM 12"),
    ("ACCESS PANEL AT VAV-2-1", "PROVIDE ACCESS PANEL AT VAV-2-1, TYP"),
    ("PROVIDE ACCESS PANEL", '"PROVIDE ACCESS PANEL"'),
    ("568 L/MIN", "FLOW 150 GPM (568 L/MIN) AT"),
    ("2E1", "PANEL 2E1 FEEDS"),
]


@pytest.mark.parametrize(("quote", "text"), _WHOLE_WORDS)
def test_n12_a_quote_that_covers_whole_words_grounds(quote, text):
    """Edge punctuation around a word does not count; the word itself must."""
    assert X._grounded(quote, text) is True
    assert classify_quote_evidence(quote, _geom("m.pdf", text)) == EVIDENCE_TEXT_GROUNDED


def test_n12_a_leg_quoting_part_of_a_longer_tag_is_dropped():
    entries = _entries(
        S001=_geom("a.pdf", "PROVIDE AHU-101 ON ROOF"),
        S002=_geom("b.pdf", "AHU-10 SUPPLIES 2000 CFM"),
    )
    counts = CrossQCDiscardCounts()
    assert _finding_from_handles(
        _item("S001", "AHU-10", [("S002", "AHU-10 SUPPLIES 2000 CFM")]), entries, counts,
    ) is None
    assert counts.legs_ungrounded_quote_text_bearing_sheet == 1


# --------------------------------------------------------------------------- #
# N13: one normalizer, the anchor's
# --------------------------------------------------------------------------- #

_SAME_TEXT = [
    ("PROVIDE 6\u201d DRAIN", 'PROVIDE 6" DRAIN AT LOW POINT'),         # curly inch mark
    ('PROVIDE 6" DRAIN', "PROVIDE 6\u201d DRAIN AT LOW POINT"),
    ('2\u00bd" PIPE', 'PROVIDE 2-1/2" PIPE'),                           # vulgar fraction
    ('2-1/2" PIPE', 'PROVIDE 2\u00bd" PIPE'),
    ('2\u00bd" PIPE', 'PROVIDE 2 1/2" PIPE'),
    ("O6 PIPE", "PROVIDE \u00d86 PIPE"),                                # diameter sign
    ("\u00d86 PIPE", "PROVIDE O6 PIPE"),
    ("300\u00d7200 DUCT", "PROVIDE 300x200 DUCT"),                      # multiplication sign
    ("300x200 DUCT", "PROVIDE 300\u00d7200 DUCT"),
    ("CLG 12\u2032-6\u2033 AFF", "CLG 12'-6\" AFF"),                    # primes
    ("\u201cQUOTED\u201d", 'NOTE "QUOTED" HERE'),                       # curly quotes
    ('1\u20442" VALVE', 'PROVIDE 1/2" VALVE'),                          # fraction slash
    ("VAV\u20113 SERVES", "VAV-3 SERVES ROOM 12"),                      # non-breaking hyphen
    ("VAV 3 SERVES", "VAV-3 SERVES ROOM 12"),                           # infix hyphen as a space
    ("M-101", "SEE M\u200b-101 FOR DETAIL"),                            # zero-width space
]


@pytest.mark.parametrize(("quote", "text"), _SAME_TEXT)
def test_n13_what_the_anchor_folds_grounds(quote, text):
    geom = _geom("m.pdf", text)
    assert classify_quote_evidence(quote, geom) == EVIDENCE_TEXT_GROUNDED


_CHANGED = [
    ("5", "GAP .5 IN"),                  # a leading decimal is not 5
    (".5", "GAP 5 IN"),
    ("5", "GAP 0.5 IN"),
    ("5", "ELEV -5 FT"),                 # a sign
    ("-5 FT", "ELEV 5 FT"),
    ("1", "SLOPE 1.5 PCT"),
    ("12", "12,500 CFM"),                # a thousands group
    ("500", "12,500 CFM"),
    ('2"', 'PROVIDE 1/2" VALVE'),        # a fraction
    ("1", 'PROVIDE 1/2" VALVE'),
    ("2", 'PROVIDE 2\u00bd" PIPE'),
    ("12", "CLG 12'-6\" AFF"),           # feet and inches
    ("12'", "CLG 12'-6\" AFF"),
    ('6"', "CLG 12'-6\" AFF"),
    ("30", "OPEN AREA 30% MIN"),         # a percent
    ('PROVIDE 4" DRAIN', 'PROVIDE 6" DRAIN'),   # a changed number
    ('PROVIDE 6" DRAIN', "PROVIDE 6' DRAIN"),   # a changed unit
    ("300x200 DUCT", "PROVIDE 300x250 DUCT"),
]


@pytest.mark.parametrize(("quote", "text"), _CHANGED)
def test_n13_a_changed_number_never_grounds(quote, text):
    assert classify_quote_evidence(quote, _geom("m.pdf", text)) == EVIDENCE_NOT_MATCHED


_NORMALIZER_CORPUS = [
    "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2",
    "PROVIDE 6\u201d DRAIN",
    '2\u00bd" PIPE, TYP.',
    "\u00d86 PIPE",
    "300 \u00d7 200 DUCT",
    "CLG 12\u2032-6\u2033 AFF",
    "  RELIEF\nVALVE  ",
    "150 gpm",
    "TYP.",
]


def test_n13_cross_qc_matches_with_the_anchors_normalizer():
    """One policy: the grounding match and the tile join both use it."""
    for text in _NORMALIZER_CORPUS:
        assert X._norm_for_match(text) == _normalize(text), text


def test_n13_per_word_normalization_is_exactly_the_anchors_result():
    """Normalizing one source word at a time changes nothing about the result.

    It is how the word boundaries come for free; this pins that it costs
    nothing in fidelity, including where Unicode could make the two differ:
    spaces that NFKC or the fraction rewrite create inside a word, whitespace
    variants, words that normalize to nothing, a doubled apostrophe, final
    sigma, a dotted capital I and a ligature.
    """
    from drawing_analyzer.anchor import source_words

    corpus = _NORMALIZER_CORPUS + [
        "A\u00b4B C",                          # NFKC puts a space inside a word
        "2\u00bd\" AND 3\u00bc\"",             # the fraction rewrite does too
        "A\u00a0B\u3000C\u2003D\tE\nF",        # whitespace variants
        "X \u200b Y \u00ad Z",                 # words of invisibles only
        "IT''S 6''",                           # '' is an inch mark
        "\u039f\u0394\u039f\u03a3 \u039f\u0394\u039f\u03a3",   # final sigma
        "\u0130-5 VAV-3",                      # dotted capital I
        "\ufb01RE DAMPER",                     # a ligature
        "\uff21\uff28\uff35\uff0d\uff11",      # fullwidth AHU-1
        "",
        "   ",
    ]
    for text in corpus:
        assert source_words(text).normalized == _normalize(text), repr(text)


def test_the_boundary_rule_is_defined_once_in_anchor():
    """The edge punctuation sets and the word core the owner decided."""
    from drawing_analyzer import anchor

    assert anchor.WORD_LEADING_PUNCTUATION == frozenset("([{<\"'")
    assert anchor.WORD_TRAILING_PUNCTUATION == frozenset(")]}>,;:.!?\"'")
    assert anchor.word_core("(p 1),") == (1, 4)
    assert anchor.word_core("vav 2 1") == (0, 7)
    assert anchor.word_core("12'-6\"") == (0, 5)
    assert anchor.word_core(".5") == (0, 2)
    assert anchor.word_core("-5") == (0, 2)
    assert anchor.word_core("30%") == (0, 3)
    assert anchor.word_core("((") == (2, 2)


# --------------------------------------------------------------------------- #
# The tile join uses the same normalizer
# --------------------------------------------------------------------------- #


def _fact(handle: str, quote: str, tile) -> CrossQCFact:
    return CrossQCFact(sheet_handle=handle, sheet_id="M-1", discipline="m",
                       entity_or_tag="DRAIN", attribute="size", value="6",
                       exact_quote=quote, tile=tile)


def test_a_reconciled_leg_joins_its_fact_across_a_curly_inch_mark():
    """The reconcile contract carries no tile; the leg inherits its fact's."""
    entries = _entries(
        S001=_geom("a.pdf", 'PROVIDE 6" DRAIN AT LOW POINT'),
        S002=_geom("b.pdf", 'PROVIDE 4" DRAIN AT LOW POINT'),
    )
    lookup = fact_tile_lookup([
        _fact("S001", 'PROVIDE 6" DRAIN', [1, 1]),
        _fact("S002", 'PROVIDE 4" DRAIN', [0, 1]),
    ])
    finding = _finding_from_handles(
        _item("S001", "PROVIDE 6\u201d DRAIN", [("S002", "PROVIDE 4\u201d DRAIN")]),
        entries, None, lookup,
    )
    assert finding is not None
    assert finding.tile == [1, 1]
    assert finding.also_on[0].tile == [0, 1]


def test_two_facts_that_normalize_alike_with_different_tiles_give_no_tile():
    """The same quote twice is ambiguous, now also when it is spelled two ways."""
    facts = [_fact("S001", 'PROVIDE 6" DRAIN', [0, 0]),
             _fact("S001", "PROVIDE 6\u201d DRAIN", [1, 1])]
    assert fact_tile_lookup(facts) == {}
    assert fact_tile_lookup(list(reversed(facts))) == {}


# --------------------------------------------------------------------------- #
# End to end on the sharded path
# --------------------------------------------------------------------------- #


def _digest(source: str) -> SheetDigest:
    return SheetDigest(ref=_ref(source), text="Sheet - M - Plan")


class _ShardedClient(BetaClientMixin):
    """Map calls emit one fact per sheet; the reconcile call returns ``finding``."""

    def __init__(self, finding: dict, facts: dict):
        self.map_calls = 0
        self.reconcile_calls = 0
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                body = kw["messages"][0]["content"][0]["text"]
                if system.startswith(X.CROSS_QC_RECONCILE_SYSTEM_PROMPT[:60]):
                    outer.reconcile_calls += 1
                    obj = {"findings": [finding], "claims": []}
                else:
                    outer.map_calls += 1
                    obj = {"findings": [], "claims": [], "facts": [
                        {"sheet_handle": h, "entity_or_tag": "P-1", "attribute": "a",
                         "value": "v", **facts[h]}
                        for h in re.findall(r"SHEET (S\d+)", body)
                    ]}
                return FakeMessage(
                    content=[FakeTextBlock(text="```json\n" + json.dumps(obj) + "\n```")],
                    usage=FakeUsage(input_tokens=100, output_tokens=20),
                )

        self.messages = _Msgs()


def test_sharded_run_keeps_a_scanned_short_tag_leg_at_reduced_trust(monkeypatch):
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)      # two sheets, two shards
    geoms = [_geom("scan.pdf", "", words=[]), _geom("b.pdf", "PUMP P-1 SERVES AREA A")]
    client = _ShardedClient(
        finding=_item("S001", "P-1", [("S002", "PUMP P-1 SERVES AREA A")]),
        facts={"S001": {"exact_quote": "P-1", "tile_label": "r2c1"},
               "S002": {"exact_quote": "PUMP P-1 SERVES AREA A", "tile_label": "r1c1"}},
    )
    res = cross_sheet_qc([_digest("scan.pdf"), _digest("b.pdf")], geoms,
                         client=client, max_retries=0, sleep=lambda *_: None)
    assert client.map_calls == 2 and client.reconcile_calls == 1
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.source_name == "scan.pdf"
    assert f.evidence_state == EVIDENCE_UNAVAILABLE
    assert f.tile == [1, 0], "the leg inherits the tile its fact reported"
    assert res.discards.legs_admitted_no_text_evidence == 1
    assert res.discards.facts_admitted_no_text_evidence == 1
    assert res.discards.legs_accepted_grounded == 1


def test_sharded_run_drops_a_tag_leg_the_sheet_does_not_print(monkeypatch):
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
    geoms = [_geom("a.pdf", "AHU-1 AND AHU-2 SERVE LEVEL 2"),
             _geom("b.pdf", "AHU-7 SUPPLIES 2000 CFM")]
    client = _ShardedClient(
        finding=_item("S001", "AHU-7", [("S002", "AHU-7 SUPPLIES 2000 CFM")]),
        facts={"S001": {"exact_quote": "AHU-7"},
               "S002": {"exact_quote": "AHU-7 SUPPLIES 2000 CFM"}},
    )
    res = cross_sheet_qc([_digest("a.pdf"), _digest("b.pdf")], geoms,
                         client=client, max_retries=0, sleep=lambda *_: None)
    assert res.findings == []
    assert res.discards.facts_ungrounded_quote_text_bearing_sheet == 1
    assert res.discards.legs_ungrounded_quote_text_bearing_sheet == 1
    assert res.discards.findings_dropped_under_two_legs == 1


# --------------------------------------------------------------------------- #
# Through the pipeline: a recovered leg is new paid work, by design
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402
from drawing_analyzer.verify import VERIFY_SYSTEM_PROMPT  # noqa: E402


def _text_pdf(path: Path, body: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((80, 120), body)
    doc.save(str(path))
    doc.close()
    return path


def _scanned_pdf(path: Path) -> Path:
    """Line work and no text layer: what a scanned sheet offers a text search."""
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.draw_rect(pymupdf.Rect(80, 80, 320, 260), color=(0, 0, 0), width=2)
    page.draw_line((80, 80), (320, 260), color=(0, 0, 0), width=2)
    doc.save(str(path))
    doc.close()
    return path


class _PipelineClient(BetaClientMixin):
    """Digest, sharded cross-QC (map + reconcile) and the crop verifier."""

    def __init__(self, finding: dict, fact_quotes: dict):
        self.verify_image_counts: list[int] = []
        self.reconcile_calls = 0
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                if system == VERIFY_SYSTEM_PROMPT:
                    outer.verify_image_counts.append(sum(
                        1 for b in kw["messages"][0]["content"]
                        if isinstance(b, dict) and b.get("type") == "image"))
                    text = '{"verdict":"CONFIRMED","note":"x"}'
                elif isinstance(system, str) and system.startswith(
                        X.CROSS_QC_RECONCILE_SYSTEM_PROMPT[:60]):
                    outer.reconcile_calls += 1
                    text = "```json\n" + json.dumps({"findings": [finding], "claims": []}) + "\n```"
                elif isinstance(system, str) and system.startswith(X.CROSS_QC_SYSTEM_PROMPT):
                    body = kw["messages"][0]["content"][0]["text"]
                    facts = []
                    for handle, chunk in re.findall(
                            r"===== SHEET (S\d+) =====(.*?)(?======|\Z)", body, re.S):
                        textless = "TEXT LAYER:\n\n" in chunk or chunk.rstrip().endswith("TEXT LAYER:")
                        facts.append({"sheet_handle": handle, "entity_or_tag": "P-1",
                                      "attribute": "a", "value": "v", "tile_label": "r1c1",
                                      "exact_quote": fact_quotes["scanned" if textless else "text"]})
                    text = "```json\n" + json.dumps(
                        {"findings": [], "claims": [], "facts": facts}) + "\n```"
                elif isinstance(system, str) and system.startswith(DIGEST_SYSTEM_PROMPT):
                    text = "Sheet - M - Plan\nPump room.\n\n```json\n{\"findings\": []}\n```"
                else:
                    text = "ok"
                return FakeMessage(content=[FakeTextBlock(text=text)],
                                   usage=FakeUsage(input_tokens=100, output_tokens=20))

        self.messages = _Msgs()


def test_pipeline_a_scanned_short_tag_leg_is_crop_verified(tmp_path, monkeypatch):
    """The recovered leg reaches the dual-crop check: one call, a crop per sheet."""
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
    scanned = _scanned_pdf(tmp_path / "scan.pdf")
    text = _text_pdf(tmp_path / "b.pdf", "PUMP P-1 SERVES AREA A")
    client = _PipelineClient(
        finding=_item("S001", "P-1", [("S002", "PUMP P-1 SERVES AREA A")]),
        fact_quotes={"scanned": "P-1", "text": "PUMP P-1 SERVES AREA A"},
    )
    ctx = extract_drawing_context(
        [scanned, text], client=client, rows=2, cols=2, cross_qc=True,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    assert client.reconcile_calls == 1
    conflict = next(f for f in ctx.findings if f.also_on)
    assert conflict.source_name == "scan.pdf"
    assert conflict.evidence_state == EVIDENCE_UNAVAILABLE
    assert conflict.anchor.status == "TILE"
    assert conflict.anchor.method == "tile_no_text_evidence"
    assert client.verify_image_counts == [2], "one dual-crop call, a crop per sheet"
    assert conflict.verification.status == "VERIFIED"


def test_pipeline_a_tag_leg_the_sheet_does_not_print_never_becomes_a_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(X, "MAX_SHEETS_SINGLE_CALL", 1)
    a = _text_pdf(tmp_path / "a.pdf", "AHU-1 AND AHU-2 SERVE LEVEL 2")
    b = _text_pdf(tmp_path / "b.pdf", "AHU-7 SUPPLIES 2000 CFM")
    client = _PipelineClient(
        finding=_item("S001", "AHU-7", [("S002", "AHU-7 SUPPLIES 2000 CFM")]),
        fact_quotes={"scanned": "AHU-7", "text": "AHU-7 SUPPLIES 2000 CFM"},
    )
    ctx = extract_drawing_context(
        [a, b], client=client, rows=2, cols=2, cross_qc=True,
        qc_markups=True, qc_work_dir=tmp_path / "qc",
    )
    assert client.reconcile_calls == 1
    assert [f for f in ctx.findings if f.also_on] == []
    assert client.verify_image_counts == []


# --------------------------------------------------------------------------- #
# Cost: a quote recurring inside one long run (Codex review)
# --------------------------------------------------------------------------- #


def _reference_contains(quote: str, text: str) -> bool:
    """The rule read directly: every occurrence tried, every core re-derived."""
    from drawing_analyzer.anchor import word_core

    words = [w for w in (_normalize(t) for t in text.split()) if w]
    joined = " ".join(words)
    spans, at = [], 0
    for w in words:
        spans.append((at, at + len(w)))
        at += len(w) + 1
    query = _normalize(quote)
    if not query:
        return False

    def word_at(pos):
        return next(s for s in spans if s[0] <= pos < s[1])

    for start in range(len(joined)):
        if not joined.startswith(query, start):
            continue
        ws, we = word_at(start)
        es, ee = word_at(start + len(query) - 1)
        if (start - ws <= word_core(joined[ws:we])[0]
                and start + len(query) - es >= word_core(joined[es:ee])[1]):
            return True
    return False


_GENERATED_TOKENS = [
    "P-1", "(P-1)", "P-1,", "P-10", "XP-1", "P-1.", "VAV-2-1", "VAV-2", "VAV-2,",
    "12'-6\"", ".5", "5", "-5", "0.5", "12,500", "1/2\"", "2\u00bd\"", "2-1/2\"",
    "NOTE", "3:", "TYP.", "\u201c6\u201d", "M-101/M-102", "P-1,P-2", "((", "))", "\"",
    "\u00d86", "300\u00d7200", "SEE", "AHU-10", "AHU-101",
]


def _generated_pairs(n: int = 600):
    import random

    rng = random.Random(51)
    pairs = []
    for _ in range(n):
        tokens = [rng.choice(_GENERATED_TOKENS) for _ in range(rng.randint(1, 7))]
        text = " ".join(tokens)
        if rng.random() < 0.5:
            lo = rng.randrange(len(tokens))
            hi = rng.randint(lo + 1, len(tokens))
            quote = " ".join(tokens[lo:hi])
        else:
            quote = rng.choice(_GENERATED_TOKENS)
        if rng.random() < 0.3 and len(quote) > 2:          # cut into a word
            quote = quote[1:] if rng.random() < 0.5 else quote[:-1]
        pairs.append((quote, text))
    return pairs


def test_the_matcher_gives_the_rules_answer_everywhere():
    """The fast scan changes the cost, never an answer."""
    from drawing_analyzer.anchor import SourceWords

    tables = (_CUT_A_WORD + _WHOLE_WORDS + _SAME_TEXT + _CHANGED
              + [("3", "SEE NOTE 3 BELOW"), ("3", "SEE M-3 AND 3A BELOW"),
                 ("TYP", "6 IN DRAIN, TYP."), ("q", "P-1 SERVES AREA A")])
    pairs = tables + _generated_pairs()
    grounded = 0
    for quote, text in pairs:
        expected = _reference_contains(quote, text)
        assert SourceWords(text).contains(quote) is expected, (quote, text)
        grounded += expected
    assert 0 < grounded < len(pairs), "the pairs must exercise both answers"


def test_the_boundary_check_never_rederives_a_words_core(monkeypatch):
    """Each word's core is found once, when the text is indexed."""
    from drawing_analyzer import anchor

    words = anchor.SourceWords("SEE (P-1), XP-1 AND P-10; NOTE 3: VAV-2-1 TYP.")

    def _refuse(_word):
        raise AssertionError("word_core re-derived during a match")

    monkeypatch.setattr(anchor, "word_core", _refuse)
    assert words.contains("P-1") is True
    assert words.contains("NOTE 3") is True
    assert words.contains("VAV-2") is False
    assert words.contains("P-10") is True
    assert words.contains("AHU-7") is False


@pytest.mark.parametrize("run", [
    "XP-1" * 250_000,             # the quote recurs inside the run, never at its start
    "P-1X" * 250_000,             # it starts the run and recurs through it
])
def test_a_quote_recurring_inside_one_long_run_costs_linear_time(run):
    """A garbled or per-glyph text layer can be one whitespace-free run.

    The quote recurs 250,000 times inside this 1,000,000-character word.
    Re-deriving the word's core at every occurrence copied the whole word each
    time: about 7 s here, and quadratic in the run's length. Only the matching
    is timed; indexing the text is linear and happens once per sheet.
    """
    import time

    from drawing_analyzer.anchor import SourceWords

    words = SourceWords("NOTE " + run + " PUMP P-1 END")
    t0 = time.perf_counter()
    assert words.contains("P-1") is True            # the real one, after the run
    assert words.contains("P-1 SERVES") is False
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"matching is superlinear again: {elapsed:.2f}s"
