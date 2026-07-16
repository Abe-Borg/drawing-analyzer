"""Phase 15 tests: QC numbering, markup richness, index pages, citation check.

The pure pieces (id assignment, clear-band computation, citation parsing/harvest)
run without PyMuPDF; the PDF-writing pieces build synthetic PDFs and are gated on
it, mirroring ``test_drawing_annotate.py``. Hermetic — no network, no key.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from drawing_analyzer.models import (
    Anchor,
    Citation,
    Finding,
    Verification,
    assign_qc_ids,
)

# --------------------------------------------------------------------------- #
# QC-id assignment (pure)
# --------------------------------------------------------------------------- #


def _f(text, *, source="a.pdf", page=0, rect=None, hint="", sev="medium",
       cat="code", status="VERIFIED", quote="q", refs=None, tile=None):
    anchor = Anchor(status="EXACT", rect_pdf=list(rect), method="t") if rect else Anchor()
    return Finding(
        sheet_id="S-1", source_name=source, page_index=page, category=cat,
        severity=sev, text=text, source_quote=quote, tile=tile,
        refs=list(refs or []), anchor_hint=hint, anchor=anchor,
        verification=Verification(status=status),
    )


def test_qc_ids_ordered_sheet_then_position():
    a = _f("second on page", rect=[10, 500, 60, 520])     # lower on the page
    b = _f("first on page", rect=[10, 40, 60, 60])        # top of the page
    c = _f("later sheet", source="b.pdf", rect=[5, 5, 20, 20])
    d = _f("sheet-level, sorts last on its sheet", hint="SHEET")
    assign_qc_ids([a, b, c, d])
    assert b.qc_id == "QC-001"      # top of a.pdf
    assert a.qc_id == "QC-002"      # below it
    assert d.qc_id == "QC-003"      # rect-less: after anchored ones on a.pdf
    assert c.qc_id == "QC-004"      # next source file


def test_qc_ids_stable_regardless_of_input_order():
    def build():
        return [
            _f("one", rect=[10, 40, 60, 60]),
            _f("two", rect=[10, 500, 60, 520]),
            _f("three", source="b.pdf", rect=[5, 5, 20, 20]),
            _f("four", hint="SHEET"),
        ]

    base = build()
    assign_qc_ids(base)
    expected = {f.text: f.qc_id for f in base}
    for seed in (1, 7, 42):
        shuffled = build()
        random.Random(seed).shuffle(shuffled)
        assign_qc_ids(shuffled)
        assert {f.text: f.qc_id for f in shuffled} == expected


def test_qc_id_round_trips_through_dict():
    f = _f("x", rect=[1, 2, 3, 4], refs=["NFPA 13"])
    f.citation = Citation(status="CHECKED_SUPPORTS", note="ok", edition_notes="2019+")
    assign_qc_ids([f])
    d = f.to_dict()
    back = Finding.from_dict(d)
    assert back.qc_id == f.qc_id == "QC-001"
    assert back.citation is not None and back.citation.status == "CHECKED_SUPPORTS"
    # A finding without a citation omits the key entirely (compact JSON).
    bare = _f("y")
    assert "citation" not in bare.to_dict()
    assert Finding.from_dict(bare.to_dict()).citation is None


# --------------------------------------------------------------------------- #
# Clear-margin-band computation (pure)
# --------------------------------------------------------------------------- #

from drawing_analyzer.annotate import find_clear_band  # noqa: E402

W, H = 3168.0, 2448.0


def _w(x, y, text="w", width=64, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _overlaps(band, word):
    bx0, by0, bx1, by1 = band
    x0, y0, x1, y1 = float(word[0]), float(word[1]), float(word[2]), float(word[3])
    return x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0


def test_clear_band_avoids_every_word():
    # Words dense in the top half; a clean gap in the lower middle; more words at
    # the very bottom (a title strip). The band must land in the clean gap.
    words = [_w(50 + 200 * i, 40 + 30 * j) for i in range(10) for j in range(30)]
    words += [_w(50 + 200 * i, H - 60) for i in range(10)]
    band = find_clear_band(words, W, H)
    assert all(not _overlaps(band, w) for w in words)
    bx0, by0, bx1, by1 = band
    assert by1 - by0 >= 40           # a usable height
    assert bx1 - bx0 > 0.8 * W       # spans (most of) the sheet width


def test_clear_band_falls_back_without_words():
    band = find_clear_band([], W, H)
    bx0, by0, bx1, by1 = band
    assert 0 < bx0 < bx1 < W and 0 < by0 < by1 <= H


# --------------------------------------------------------------------------- #
# Plain-words popup composition (pure)
# --------------------------------------------------------------------------- #

from drawing_analyzer.annotate import (  # noqa: E402
    _annot_content,
    _status_label,
    _truncate_at_word,
)


@pytest.mark.parametrize(
    "status,origin,unverified,rejected,expected",
    [
        ("VERIFIED", "", False, False, "AI-verified against the drawing."),
        ("UNCERTAIN", "", True, False, "Not yet verified - double-check on the sheet."),
        ("REJECTED", "", False, True, "Rejected on AI re-check - kept for the record only."),
        ("DETERMINISTIC", "TEXT_EXTRACTED", False, False,
         "Math checked by computer from the sheet's own printed numbers."),
        ("UNCERTAIN", "MODEL_TRANSCRIBED", True, False,
         "Computed from numbers as read by the AI - re-check the math against the sheet."),
        ("DETERMINISTIC", "", False, False,
         "Found by an exact text check of the drawings - not an AI judgment."),
    ],
)
def test_popup_trust_note_speaks_plain_words(status, origin, unverified, rejected, expected):
    f = _f("an issue", status=status)
    f.verification.operand_origin = origin
    content = _annot_content(f, unverified=unverified, rejected=rejected)
    assert content.rstrip().endswith(expected)


def test_popup_names_the_checked_edition():
    # Phase B: the reviewer sees which edition the verdict was checked against;
    # URLs and raw provenance stay in the CSV/HTML report, never on the drawing.
    from drawing_analyzer.models import Citation, CitationAssessment

    f = _f("cites relief valve", status="VERIFIED")
    f.citation = Citation(status="CHECKED_SUPPORTS", note="ok")
    f.citations = [CitationAssessment(
        reference="NFPA 13 2016 §8.1.2", status="CHECKED_SUPPORTS",
        checked_edition="NFPA 13 2016",
        evidence_url="https://codes.example.org/x",
    )]
    content = _annot_content(f, unverified=False)
    assert "checked against NFPA 13 2016 §8.1.2: NFPA 13 2016" in content
    assert "https://" not in content              # links never ink the drawing


def test_popup_single_read_folds_into_the_unverified_note():
    f = _f("an issue", status="UNCERTAIN")
    f.reproduced = False
    content = _annot_content(f, unverified=True)
    assert content.rstrip().endswith(
        "Not yet verified (seen in one AI read) - double-check on the sheet."
    )


def test_popup_conflict_pointer_is_ascii():
    from drawing_analyzer.models import ConflictLeg

    f = _f("rating conflict", rect=[1, 2, 3, 4], quote="165 PSI")
    f.also_on = [ConflictLeg(sheet_id="P-201", source_name="P-201.pdf",
                             page_index=0, source_quote="150 PSI MAX")]
    assign_qc_ids([f])
    content = _annot_content(f, unverified=False)
    assert 'Conflicts with P-201: "150 PSI MAX" - see QC-001 there' in content
    assert "—" not in content       # ASCII-only: safe on Base-14 pages too


def test_index_status_labels_are_reviewer_words():
    assert _status_label(_f("x", status="VERIFIED")) == "Verified"
    assert _status_label(_f("x", status="DETERMINISTIC")) == "Computed"
    assert _status_label(_f("x", status="UNCERTAIN")) == "Check"
    assert _status_label(_f("x", status="SKIPPED")) == "Check"
    assert _status_label(_f("x", status="REJECTED")) == "Rejected"


def test_truncate_at_word_never_cuts_mid_word():
    text = "Confirm the relief-valve setpoint with the mechanical engineer and revise"
    out = _truncate_at_word(text, 40)
    assert len(out) <= 40
    assert out.endswith("...")
    assert text.startswith(out[:-3])
    assert text[len(out) - 3] == " "     # the cut landed on a word boundary
    # Short text passes through unchanged; a giant token falls back to a hard cut.
    assert _truncate_at_word("short", 40) == "short"
    giant = "x" * 100
    assert _truncate_at_word(giant, 40) == "x" * 37 + "..."


# --------------------------------------------------------------------------- #
# Citation check (pure parsing + fake-client pass)
# --------------------------------------------------------------------------- #

from drawing_analyzer.citation_check import (  # noqa: E402
    check_citations,
    harvest_code_editions,
    web_search_tool,
)
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage  # noqa: E402


class _Geom:
    def __init__(self, text):
        self.sheet_text = text


def test_harvest_code_editions_both_orders_and_dedup():
    geoms = [
        _Geom("ALL WORK PER NFPA 13, 2016 EDITION. SEE THE 2022 CBC."),
        _Geom("NFPA 13-2016 (repeat) AND NFPA 72 2019"),
    ]
    assert harvest_code_editions(geoms) == ["NFPA 13 2016", "CBC 2022", "NFPA 72 2019"]


def test_web_search_tool_type_is_current_and_overridable(monkeypatch):
    assert web_search_tool()["type"] == "web_search_20260209"
    assert web_search_tool()["name"] == "web_search"
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_TOOL_TYPE", "web_search_99990101")
    assert web_search_tool()["type"] == "web_search_99990101"


def test_web_search_max_uses_is_bounded_and_overridable(monkeypatch):
    from drawing_analyzer.citation_check import web_search_max_uses

    assert web_search_tool()["max_uses"] == 5
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_MAX_USES", "9")
    assert web_search_max_uses() == 9 and web_search_tool()["max_uses"] == 9
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_MAX_USES", "0")
    assert web_search_max_uses() == 5                    # sub-1 -> default
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_MAX_USES", "lots")
    assert web_search_max_uses() == 5                    # junk -> default


def test_server_web_search_requests_reader_is_shape_tolerant():
    # Phase B exact billing: the reader must distinguish "server reported 0"
    # from "this response shape carries no count" (None).
    from drawing_analyzer.digest import _server_web_search_requests
    from tests.fixtures.fake_anthropic import FakeServerToolUse

    obj = FakeMessage(content=[], usage=FakeUsage(
        server_tool_use=FakeServerToolUse(web_search_requests=4)))
    assert _server_web_search_requests(obj) == 4
    as_dict = {"usage": {"server_tool_use": {"web_search_requests": 2}}}
    assert _server_web_search_requests(as_dict) == 2
    assert _server_web_search_requests({"usage": {"server_tool_use": {"web_search_requests": 0}}}) == 0
    assert _server_web_search_requests(FakeMessage(content=[], usage=FakeUsage())) is None
    assert _server_web_search_requests({"usage": {}}) is None
    assert _server_web_search_requests({}) is None
    assert _server_web_search_requests(
        {"usage": {"server_tool_use": {"web_search_requests": "junk"}}}
    ) is None


class _CitationClient:
    """Scripted responses; captures request kwargs.

    ``routes`` (an ordered list of ``(substring, text)``) routes by REQUEST BODY —
    deterministic regardless of worker-thread arrival order; the first route whose
    substring is in the body wins. Without routes it cycles ``texts`` by call count
    (fine only for single-request tests). ``server_searches`` (when not None)
    attaches a server-reported web-search count to every response's usage.
    """

    def __init__(self, texts=None, *, routes=None, server_searches=None):
        self._texts = list(texts or [])
        self._routes = list(routes or [])
        self._server_searches = server_searches
        self.captured = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.captured.append(kw)
                body = kw["messages"][0]["content"]
                text = None
                for sub, route_text in outer._routes:
                    if sub in body:
                        text = route_text
                        break
                if text is None:
                    text = outer._texts[min(len(outer.captured) - 1, len(outer._texts) - 1)]
                usage = FakeUsage(input_tokens=200, output_tokens=40)
                if outer._server_searches is not None:
                    from tests.fixtures.fake_anthropic import FakeServerToolUse

                    usage.server_tool_use = FakeServerToolUse(
                        web_search_requests=outer._server_searches
                    )
                return FakeMessage(
                    content=[FakeTextBlock(text=text)],
                    usage=usage,
                )

        self.messages = _Msgs()


def _verdict_block(status, note="n", editions="e"):
    return "searched...\n```json\n" + json.dumps(
        {"status": status, "note": note, "edition_notes": editions}
    ) + "\n```"


def test_check_citations_attaches_verdicts_per_unique_ref():
    f1 = _f("cites table", refs=["NFPA 13 Table 13.2.1"])
    f2 = _f("cites same table", refs=["NFPA 13 Table 13.2.1"])
    f3 = _f("cites relief", refs=["NFPA 13 §8.1.2"])
    # Route by reference (deterministic): the table mismatches, the relief supports.
    client = _CitationClient(routes=[
        ("Table 13.2.1", _verdict_block("CHECKED_MISMATCH", note="2016 numbering", editions="4.3.1.7 in 2019+")),
        ("§8.1.2", _verdict_block("CHECKED_SUPPORTS", note="supports")),
    ])
    res = check_citations(
        [f1, f2, f3], [_Geom("PER NFPA 13, 2016 EDITION")],
        client=client, sleep=lambda *_: None,
    )
    # One call per UNIQUE ref (two, not three).
    assert res.checked == 2 and len(client.captured) == 2
    assert res.mismatches == 1 and res.supports == 1
    assert f1.citation is not None and f1.citation.status == "CHECKED_MISMATCH"
    assert f2.citation is not None and f2.citation.status == "CHECKED_MISMATCH"
    assert f3.citation is not None and f3.citation.status == "CHECKED_SUPPORTS"
    # The request carried the web-search tool and the harvested edition.
    kw = client.captured[0]
    assert kw["tools"][0]["name"] == "web_search"
    user_text = kw["messages"][0]["content"]
    assert "NFPA 13 2016" in user_text


def test_check_citations_populates_structured_provenance():
    # Phase B: the new-shape reply's checked/current edition + evidence URL
    # land as structured CitationAssessment fields.
    f = _f("cites relief valve", refs=["NFPA 13 §8.1.2"])
    reply = "searched...\n```json\n" + json.dumps({
        "assessments": [{
            "claim": "C1", "status": "CHECKED_SUPPORTS", "note": "supports",
            "checked_edition": "NFPA 13 2016",
            "current_edition": "NFPA 13 2025",
            "evidence_url": "https://example.org/nfpa13-8-1-2",
        }],
        "edition_notes": "renumbered in 2019",
    }) + "\n```"
    res = check_citations([f], [], client=_CitationClient([reply]), sleep=lambda *_: None)
    (a,) = f.citations
    assert a.checked_edition == "NFPA 13 2016"
    assert a.current_edition == "NFPA 13 2025"
    assert a.evidence_url == "https://example.org/nfpa13-8-1-2"
    assert res.supports == 1
    # Round-trips additively.
    from drawing_analyzer.models import CitationAssessment

    again = CitationAssessment.from_dict(a.to_dict())
    assert again.checked_edition == a.checked_edition
    assert again.evidence_url == a.evidence_url


def test_check_citations_old_shape_reply_defaults_new_fields():
    # A pre-Phase-B reply (no new keys) still parses; provenance stays "".
    f = _f("cites relief valve", refs=["NFPA 13 §8.1.2"])
    res = check_citations(
        [f], [], client=_CitationClient([_verdict_block("CHECKED_SUPPORTS")]),
        sleep=lambda *_: None,
    )
    (a,) = f.citations
    assert a.status == "CHECKED_SUPPORTS"
    assert a.checked_edition == "" and a.current_edition == "" and a.evidence_url == ""
    assert not res.partial


def test_citation_provenance_fields_are_bounded_and_https_only():
    f = _f("cites", refs=["CMC 310"])
    reply = "```json\n" + json.dumps({
        "assessments": [{
            "claim": "C1", "status": "CHECKED_MISMATCH", "note": "n" * 900,
            "checked_edition": "E" * 300,
            "current_edition": "javascript:alert(1)",
            "evidence_url": "http://insecure.example.org/x",   # not https -> dropped
        }],
    }) + "\n```"
    check_citations([f], [], client=_CitationClient([reply]), sleep=lambda *_: None)
    (a,) = f.citations
    assert len(a.note) <= 300
    assert len(a.checked_edition) == 80                    # capped
    assert a.evidence_url == ""                            # non-https dropped
    # current_edition is a display string, not a link — capped only.
    assert len(a.current_edition) <= 80


def test_check_citations_bills_exact_server_search_counts():
    # Phase B: when responses carry usage.server_tool_use.web_search_requests,
    # the result sums the exact figures instead of approximating.
    f1 = _f("cites table", refs=["NFPA 13 Table 13.2.1"])
    f2 = _f("cites relief", refs=["NFPA 13 §8.1.2"])
    client = _CitationClient(
        routes=[
            ("Table 13.2.1", _verdict_block("CHECKED_MISMATCH")),
            ("§8.1.2", _verdict_block("CHECKED_SUPPORTS")),
        ],
        server_searches=4,
    )
    res = check_citations([f1, f2], [], client=client, sleep=lambda *_: None)
    assert res.requests == 2
    assert res.web_search_requests == 8          # 2 requests × 4 reported each


def test_check_citations_falls_back_to_one_search_per_request():
    # No server-reported count anywhere -> the pre-Phase-B lower bound
    # (1 per issued request) keeps the fee honest rather than zero.
    f1 = _f("cites table", refs=["NFPA 13 Table 13.2.1"])
    f2 = _f("cites relief", refs=["NFPA 13 §8.1.2"])
    client = _CitationClient(routes=[
        ("Table 13.2.1", _verdict_block("CHECKED_SUPPORTS")),
        ("§8.1.2", _verdict_block("CHECKED_SUPPORTS")),
    ])
    res = check_citations([f1, f2], [], client=client, sleep=lambda *_: None)
    assert res.requests == 2 and res.web_search_requests == 2


# --- Phase B: the per-request TTL verdict cache ------------------------------ #


def _cited_finding():
    return _f("cites relief valve", refs=["NFPA 13 §8.1.2"])


def test_citation_ttl_days_env(monkeypatch):
    from drawing_analyzer.citation_check import citation_ttl_days

    assert citation_ttl_days() == 30                       # default
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_TTL_DAYS", "7")
    assert citation_ttl_days() == 7
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_TTL_DAYS", "0")
    assert citation_ttl_days() == 0                        # 0 = cache disabled
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_TTL_DAYS", "-3")
    assert citation_ttl_days() == 30                       # invalid -> default
    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_TTL_DAYS", "forever")
    assert citation_ttl_days() == 30


def test_citation_cache_hit_reconstructs_and_expires():
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    t = {"now": 1_000_000.0}
    clock = lambda: t["now"]  # noqa: E731 - injectable test clock (I-4)

    f1 = _cited_finding()
    c1 = _CitationClient([_verdict_block("CHECKED_MISMATCH", note="moved")])
    r1 = check_citations([f1], [], client=c1, sleep=lambda *_: None,
                         cache=cache, now=clock)
    assert r1.requests == 1 and r1.cached_requests == 0

    # Warm within the TTL: served from cache, no API call, verdict identical —
    # a cached MISMATCH still reads mismatched.
    f2 = _cited_finding()
    c2 = _CitationClient([_verdict_block("CHECKED_SUPPORTS")])   # would flip if called
    r2 = check_citations([f2], [], client=c2, sleep=lambda *_: None,
                         cache=cache, now=clock)
    assert c2.captured == []
    assert r2.cached_requests == 1 and r2.requests == 0
    assert r2.web_search_requests == 0 and not r2.partial
    assert f2.citation.status == "CHECKED_MISMATCH"
    assert f2.citations[0].note == "moved"

    # 31 days later the entry is stale: a live re-check runs and overwrites.
    t["now"] += 31 * 86400
    f3 = _cited_finding()
    c3 = _CitationClient([_verdict_block("CHECKED_SUPPORTS")])
    r3 = check_citations([f3], [], client=c3, sleep=lambda *_: None,
                         cache=cache, now=clock)
    assert len(c3.captured) == 1
    assert r3.requests == 1 and r3.cached_requests == 0
    assert f3.citation.status == "CHECKED_SUPPORTS"


def test_citation_cache_ttl_zero_disables_read_and_write(monkeypatch):
    from drawing_analyzer.digest_cache import DigestCache

    monkeypatch.setenv("DRAWING_ANALYZER_CITATION_TTL_DAYS", "0")
    cache = DigestCache(None, persist=False)
    for _ in range(2):
        f = _cited_finding()
        c = _CitationClient([_verdict_block("CHECKED_SUPPORTS")])
        res = check_citations([f], [], client=c, sleep=lambda *_: None, cache=cache)
        assert len(c.captured) == 1 and res.cached_requests == 0
    assert cache.stats()["size"] == 0                     # nothing was written


def test_citation_cache_fully_warm_run_needs_no_client(monkeypatch):
    # A fully warm run must serve every chunk from cache even when no API
    # key/client can be constructed — the client is created only on a cache
    # miss (mirrors the identity/review-plan caches).
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    f1 = _cited_finding()
    c1 = _CitationClient([_verdict_block("CHECKED_MISMATCH", note="moved")])
    check_citations([f1], [], client=c1, sleep=lambda *_: None, cache=cache)

    def _boom():
        raise RuntimeError("no API key configured")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _boom)
    f2 = _cited_finding()
    res = check_citations([f2], [], client=None, sleep=lambda *_: None, cache=cache)
    assert res.cached_requests == 1 and res.requests == 0
    assert not res.partial and res.error is None
    assert res.web_search_requests == 0
    assert f2.citation.status == "CHECKED_MISMATCH"


def test_citation_cache_partial_warm_run_serves_hits_without_client(monkeypatch):
    # Mixed warm/cold with no client available: the cached chunk is served,
    # the uncached one degrades to UNCHECKED without billing, stage PARTIAL.
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    f1 = _cited_finding()
    c1 = _CitationClient([_verdict_block("CHECKED_MISMATCH", note="moved")])
    check_citations([f1], [], client=c1, sleep=lambda *_: None, cache=cache)

    def _boom():
        raise RuntimeError("no API key configured")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _boom)
    f2 = _cited_finding()
    f3 = _f("cites the pump table", refs=["NFPA 20 Table 4.27"])
    res = check_citations([f2, f3], [], client=None, sleep=lambda *_: None,
                          cache=cache)
    assert res.cached_requests == 1 and res.requests == 0
    assert res.partial and "no API key" in (res.error or "")
    assert res.web_search_requests == 0                    # no live call billed
    assert f2.citation.status == "CHECKED_MISMATCH"
    assert f3.citation.status == "UNCHECKED"
    assert "client unavailable" in f3.citations[0].note
    assert res.unchecked == 1 and res.mismatches == 1


def test_citation_no_client_and_no_cache_degrades_everything_unchecked(monkeypatch):
    # Zero-hit path unchanged: the pass cannot run at all → every ref UNCHECKED.
    def _boom():
        raise RuntimeError("no API key configured")

    monkeypatch.setattr("drawing_analyzer.client.get_client", _boom)
    f = _cited_finding()
    res = check_citations([f], [], client=None, sleep=lambda *_: None)
    assert res.partial and res.unchecked == 1 and res.requests == 0
    assert f.citation is not None and f.citation.status == "UNCHECKED"


def test_citation_cache_never_stores_partial_chunks():
    from drawing_analyzer.digest_cache import DigestCache

    cache = DigestCache(None, persist=False)
    f = _cited_finding()
    res = check_citations([f], [], client=_CitationClient(["garbled, no json"]),
                          sleep=lambda *_: None, cache=cache)
    assert res.partial and cache.stats()["size"] == 0
    # The next run re-checks live (no stale UNCHECKED can ever be served).
    f2 = _cited_finding()
    c2 = _CitationClient([_verdict_block("CHECKED_SUPPORTS")])
    res2 = check_citations([f2], [], client=c2, sleep=lambda *_: None, cache=cache)
    assert len(c2.captured) == 1 and not res2.partial


def test_citation_cache_key_sensitivity(monkeypatch):
    # Any change to editions context, jurisdiction, claim text, model, or the
    # search budget must MISS — never serve a verdict computed under different
    # conditions.
    from drawing_analyzer.digest_cache import DigestCache
    from drawing_analyzer.models import SetIdentity

    cache = DigestCache(None, persist=False)

    def _live_run(**kw):
        f = kw.pop("finding", None) or _cited_finding()
        c = _CitationClient([_verdict_block("CHECKED_SUPPORTS")])
        check_citations([f], kw.pop("geometries", []), client=c,
                        sleep=lambda *_: None, cache=cache, **kw)
        return len(c.captured)

    assert _live_run() == 1                                # populate
    assert _live_run() == 0                                # identical -> hit
    assert _live_run(geometries=[_Geom("PER NFPA 13 2016")]) == 1   # editions differ
    assert _live_run(identity=SetIdentity(jurisdiction="Berlin, Germany")) == 1
    assert _live_run(finding=_f("different claim text", refs=["NFPA 13 §8.1.2"])) == 1
    assert _live_run(model="claude-haiku-4-5") == 1        # model rides the key
    monkeypatch.setenv("DRAWING_ANALYZER_WEB_SEARCH_MAX_USES", "9")
    assert _live_run() == 1                                # search budget re-keys


def test_check_citations_garbled_reply_degrades_to_unchecked():
    f = _f("cites", refs=["CMC 310"])
    client = _CitationClient(["no json here at all"])
    res = check_citations([f], [], client=client, sleep=lambda *_: None)
    assert res.unchecked == 1
    assert f.citation is not None and f.citation.status == "UNCHECKED"


def test_check_citations_no_refs_is_a_noop():
    f = _f("no refs")
    res = check_citations([f], [], client=None)
    assert res.checked == 0 and f.citation is None


# --------------------------------------------------------------------------- #
# Claim-completeness (Phase 24 §16.5, DA-017)
# --------------------------------------------------------------------------- #

import re as _re  # noqa: E402


class _PerClaimClient:
    """A content-aware fake: echoes each claim handle in the request with a status.

    ``status_for(handle, body)`` decides the per-claim verdict from the REQUEST BODY
    (which carries the reference and each claim's text), so routing is deterministic
    and independent of worker-thread arrival order — a test can return mixed
    SUPPORTS/MISMATCH keyed by the claim text or the reference, not the call index.
    """

    def __init__(self, status_for):
        self._status_for = status_for
        self.captured: list[dict] = []
        outer = self

        class _Msgs:
            def create(self, **kw):  # noqa: ANN001, ANN202
                outer.captured.append(kw)
                body = kw["messages"][0]["content"]
                handles = _re.findall(r"\[(C\d+)\]", body)
                entries = [
                    {"claim": h, "status": outer._status_for(h, body), "note": "n"}
                    for h in handles
                ]
                text = "searched...\n```json\n" + json.dumps(
                    {"assessments": entries, "edition_notes": "e"}
                ) + "\n```"
                return FakeMessage(
                    content=[FakeTextBlock(text=text)],
                    usage=FakeUsage(input_tokens=200, output_tokens=40),
                )

        self.messages = _Msgs()


def _claim_text_for(handle: str, body: str) -> str:
    """The claim text paired with ``handle`` in a citation request body ([C1] text)."""
    m = _re.search(rf"\[{handle}\] (.+)", body)
    return m.group(1) if m else ""


def test_check_citations_checks_every_claim_no_truncation():
    # DA-017: five distinct claims sharing one reference are ALL sent (no
    # finding_texts[:3] drop) and every finding gets a verdict.
    ref = "NFPA 13 §8.1.2"
    fs = [_f(f"claim number {i}", refs=[ref]) for i in range(5)]
    client = _PerClaimClient(lambda h, body: "CHECKED_SUPPORTS")
    res = check_citations(fs, [], client=client, sleep=lambda *_: None)
    assert len(client.captured) == 1          # five claims fit in one request
    body = client.captured[0]["messages"][0]["content"]
    for i in range(5):
        assert f"claim number {i}" in body     # none truncated away
    assert all(f.citation.status == "CHECKED_SUPPORTS" for f in fs)
    assert res.partial is False


def test_check_citations_mixed_verdicts_are_claim_specific():
    # DA-017: two different claims under one reference keep their own verdicts.
    ref = "NFPA 13 Table 13.2.1"
    f_ok = _f("sprinkler count is fine", refs=[ref])
    f_bad = _f("density is wrong", refs=[ref])
    # Route by the CLAIM TEXT (deterministic), not by handle position: 'density'
    # mismatches, everything else supports.
    client = _PerClaimClient(
        lambda h, body: "CHECKED_MISMATCH" if "density" in _claim_text_for(h, body)
        else "CHECKED_SUPPORTS"
    )
    res = check_citations([f_ok, f_bad], [], client=client, sleep=lambda *_: None)
    assert f_ok.citation.status == "CHECKED_SUPPORTS"
    assert f_bad.citation.status == "CHECKED_MISMATCH"
    assert len(f_ok.citations) == 1 and f_ok.citations[0].reference == ref
    # The reference's dominant verdict counts as one mismatch (mismatch dominates).
    assert res.mismatches == 1 and res.supports == 0


def test_check_citations_verdict_only_covers_the_request_that_included_the_claim(monkeypatch):
    # DA-017 core: a finding's verdict comes from the request that actually
    # contained its claim — never one that omitted it. Force a chunk boundary so
    # the two chunks return DIFFERENT verdicts, keyed by claim text (deterministic,
    # thread-order-independent). The old defect (one verdict fanned out to every
    # finding citing the ref) would give the second-chunk finding the first chunk's
    # verdict; here it must get its own.
    import drawing_analyzer.citation_check as C
    monkeypatch.setattr(C, "_MAX_CLAIMS_PER_REQUEST", 2)
    ref = "NFPA 13 §19.2"
    f_alpha = _f("alpha claim", refs=[ref])
    f_beta = _f("beta claim", refs=[ref])
    f_gamma = _f("gamma claim", refs=[ref])   # falls in the SECOND chunk
    # First chunk's claims (alpha/beta) mismatch; the second chunk's (gamma) supports.
    client = _PerClaimClient(
        lambda h, body: "CHECKED_SUPPORTS" if "gamma" in _claim_text_for(h, body)
        else "CHECKED_MISMATCH"
    )
    res = C.check_citations([f_alpha, f_beta, f_gamma], [], client=client, sleep=lambda *_: None)
    assert len(client.captured) == 2          # 3 claims / 2 per request → 2 requests
    assert res.partial is False
    assert f_alpha.citation.status == "CHECKED_MISMATCH"
    assert f_beta.citation.status == "CHECKED_MISMATCH"
    # gamma's verdict comes from ITS request (the 2nd chunk), not the 1st chunk's.
    assert f_gamma.citation.status == "CHECKED_SUPPORTS"


def test_check_citations_multi_reference_finding_keeps_each_assessment():
    f = _f("cites two codes", refs=["NFPA 13 §8.1", "IBC 903.3"])
    # Route by REFERENCE (each request is for one ref): IBC mismatches, NFPA supports.
    client = _PerClaimClient(
        lambda h, body: "CHECKED_MISMATCH" if "IBC 903.3" in body else "CHECKED_SUPPORTS"
    )
    check_citations([f], [], client=client, sleep=lambda *_: None)
    # DA-017: per-reference assessments are retained, not collapsed into one status.
    assert len(f.citations) == 2
    refs = {a.reference: a.status for a in f.citations}
    assert refs == {"NFPA 13 §8.1": "CHECKED_SUPPORTS", "IBC 903.3": "CHECKED_MISMATCH"}
    # The combined summary reports the dominant (mismatch) reference, attributed.
    assert f.citation.status == "CHECKED_MISMATCH"
    assert "IBC 903.3" in f.citation.note


def test_check_citations_garbled_reply_marks_partial():
    f = _f("cites", refs=["CMC 310"])
    client = _CitationClient(["no json here at all"])
    res = check_citations([f], [], client=client, sleep=lambda *_: None)
    assert res.unchecked == 1 and res.partial is True
    assert f.citation.status == "UNCHECKED"


# --------------------------------------------------------------------------- #
# PDF-writing pieces (need PyMuPDF)
# --------------------------------------------------------------------------- #

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import (  # noqa: E402
    INDEX_PAGE_LABEL,
    annotate_pdf,
    count_annotations,
    count_annotations_by_type,
)


def _pdf(tmp_path, name="M-101.pdf", pages=1):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=792, height=612)
        page.insert_text((80, 120), "VAV-3 SERVES ROOM 120")
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _meta(words=None):
    return {0: {
        "words": list(words or []), "rows": 2, "cols": 2,
        "page_width_pt": 792.0, "page_height_pt": 612.0, "overlap_frac": 0.08,
    }}


def test_reviewed_pdf_has_tag_index_and_correct_link_targets(tmp_path):
    src = _pdf(tmp_path, pages=2)
    findings = [
        _f("page one issue", source="M-101.pdf", page=0, rect=[10, 10, 60, 30]),
        _f("page two issue", source="M-101.pdf", page=1, rect=[100, 100, 180, 130]),
    ]
    assign_qc_ids(findings)
    out = tmp_path / "M-101_reviewed.pdf"
    res = annotate_pdf(src, findings, out)
    written = res.annots_written
    assert written == 4                      # 2 clouds + 2 QC tags
    assert count_annotations(out) == written  # round-trip intact
    assert res.coverage_status == "COMPLETE"

    doc = pymupdf.open(str(out))
    try:
        assert doc.page_count == 3            # 1 index + 2 source pages
        assert INDEX_PAGE_LABEL in doc[0].get_text()
        assert "QC-001" in doc[0].get_text() and "QC-002" in doc[0].get_text()
        links = sorted(doc[0].get_links(), key=lambda l: l["from"].y0)
        assert len(links) == 2
        # Index pages shift the originals by one: page 0 -> 1, page 1 -> 2.
        assert links[0]["page"] == 1 and links[1]["page"] == 2
        # The link lands at the finding's anchor point.
        assert abs(links[1]["to"].x - 100) < 1 and abs(links[1]["to"].y - 100) < 1
        # The QC tag rides beside the cloud, in the severity color.
        types = count_annotations_by_type(out)
        assert types.get("Square") == 2 and types.get("FreeText") == 2
    finally:
        doc.close()


def test_margin_callouts_stack_in_band_and_never_overlap_words(tmp_path):
    src = _pdf(tmp_path)
    # Words fill the top of the sheet; the band must sit clear of all of them.
    words = [_w(40 + 150 * i, 20 + 24 * j, width=100, height=12)
             for i in range(5) for j in range(10)]
    absences = [
        _f(f"expected item {i}; not found on this sheet", source="M-101.pdf",
           hint="SHEET", tile=[1, 1], quote="")
        for i in range(3)
    ]
    assign_qc_ids(absences)
    out = tmp_path / "M-101_reviewed.pdf"
    written = annotate_pdf(src, absences, out, sheet_meta=_meta(words)).annots_written
    # 3 callout boxes + 3 leader lines (tile known).
    types = count_annotations_by_type(out)
    assert types.get("FreeText") == 3 and types.get("Line") == 3
    assert written == 6

    doc = pymupdf.open(str(out))
    try:
        page = doc[1]                          # after the index page
        boxes = [a.rect for a in page.annots() if a.type[1] == "FreeText"]
        assert len(boxes) == 3
        for box in boxes:
            for w in words:
                wrect = pymupdf.Rect(w[0], w[1], w[2], w[3])
                assert not box.intersects(wrect), f"callout {box} overlaps word {wrect}"
        # Stacked: boxes don't overlap each other either.
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                assert not boxes[i].intersects(boxes[j])
    finally:
        doc.close()


def test_deterministic_solid_model_cloudy_unverified_dashed(tmp_path):
    src = _pdf(tmp_path)
    verified = _f("model", source="M-101.pdf", rect=[10, 10, 60, 30], status="VERIFIED")
    determ = _f("auditor", source="M-101.pdf", rect=[100, 100, 160, 130],
                status="DETERMINISTIC", cat="reference")
    uncertain = _f("maybe", source="M-101.pdf", rect=[200, 200, 260, 230],
                   status="UNCERTAIN", cat="question")
    assign_qc_ids([verified, determ, uncertain])
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, [verified, determ, uncertain], out, include_unverified=True)

    doc = pymupdf.open(str(out))
    try:
        # Snapshot properties during iteration — PyMuPDF unbinds an annot object
        # once the generator advances past it.
        squares = {}
        for a in doc[1].annots():
            if a.type[1] == "Square":
                squares[a.info.get("content", "")[:40]] = (
                    dict(a.border), a.info.get("content", ""), dict(a.colors)
                )
        border, _c, _cl = next(v for k, v in squares.items() if "model" in k)
        assert border.get("clouds") == 2                          # revision cloud
        border, _c, _cl = next(v for k, v in squares.items() if "auditor" in k)
        assert border.get("clouds") in (0, -1)                    # solid
        assert not border.get("dashes")
        border, content, colors = next(v for k, v in squares.items() if "maybe" in k)
        assert tuple(border.get("dashes") or ()) == (4, 3)        # dashed
        assert content.startswith("[CHECK]")
        # question category renders blue regardless of severity.
        assert abs(colors["stroke"][2] - 0.82) < 0.01
    finally:
        doc.close()


def test_popup_carries_the_lean_template(tmp_path):
    # The popup speaks to a human reviewer: issue, what to do, where to look,
    # plain-words citation verdict, and a closing trust note. Machine detail
    # (ids, provenance, evidence paths, raw statuses) stays OFF the drawing —
    # it lives in the CSV/HTML report instead.
    src = _pdf(tmp_path)
    f = _f("clearance issue", source="M-101.pdf", rect=[10, 10, 60, 30],
           refs=["CMC 310"], quote="VAV-3")
    f.recommended_action = "Confirm the clearance with the mechanical engineer."
    f.verification = Verification(status="VERIFIED", note="seen", evidence_png="evidence/x.png")
    f.citation = Citation(status="CHECKED_MISMATCH", note="renumbered", edition_notes="2019+")
    f.reproduced = False
    assign_qc_ids([f])
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, [f], out)
    doc = pymupdf.open(str(out))
    try:
        square = next(a for a in doc[1].annots() if a.type[1] == "Square")
        content = square.info.get("content", "")
        assert content.startswith("QC-001: clearance issue")
        assert "Action: Confirm the clearance with the mechanical engineer." in content
        assert 'Look for: "VAV-3"' in content
        assert "Refs: CMC 310" in content
        assert "Code ref may be outdated - renumbered (2019+ editions)" in content
        assert "AI-verified against the drawing." in content
        # Machine detail must NOT reach the PDF popup.
        for machine in ("Finding ID:", "Sources:", "Verification:",
                        "Citation check:", "Reproduced:", "Evidence:",
                        "Provenance:", "Quote:"):
            assert machine not in content
    finally:
        doc.close()


def test_popup_action_line_absent_when_no_action(tmp_path):
    src = _pdf(tmp_path)
    f = _f("clearance issue", source="M-101.pdf", rect=[10, 10, 60, 30], quote="VAV-3")
    f.verification = Verification(status="VERIFIED", note="seen")
    assign_qc_ids([f])
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, [f], out)
    doc = pymupdf.open(str(out))
    try:
        square = next(a for a in doc[1].annots() if a.type[1] == "Square")
        content = square.info.get("content", "")
        # No fallback action is ever invented.
        assert "Action:" not in content
    finally:
        doc.close()


def test_appendix_page_off_by_default_and_on_when_asked(tmp_path):
    src = _pdf(tmp_path)
    f = _f("x", source="M-101.pdf", rect=[10, 10, 60, 30])
    assign_qc_ids([f])
    out1 = tmp_path / "r1.pdf"
    annotate_pdf(src, [f], out1)
    doc = pymupdf.open(str(out1))
    assert doc.page_count == 2                 # index + source; no appendix
    doc.close()

    out2 = tmp_path / "r2.pdf"
    annotate_pdf(src, [f], out2, include_appendix=True,
                 audit_stats={"arithmetic_checked": 4, "arithmetic_matched": 4,
                              "references_resolved": 9})
    doc = pymupdf.open(str(out2))
    try:
        assert doc.page_count == 3
        tail = doc[2].get_text()
        assert "CHECKED AND CONSISTENT" in tail
        assert "4 of 4" in tail and "9" in tail
    finally:
        doc.close()


def test_callouts_overflow_to_review_notes_page_never_obscure_content(tmp_path):
    # REVERSED (§17.6): the old behavior stacked overflow rows UPWARD, overlapping
    # drawing content ("visible beats hidden"). Now a callout that will not fit a
    # clear band overflows to an appended 'AI Review Notes' page instead — every
    # on-sheet callout stays in-bounds and clear of the words, and every overflow
    # item is still accounted with a successful receipt (coverage COMPLETE).
    src = _pdf(tmp_path)                       # 792 x 612
    # Words fill almost the whole sheet — only a shallow bottom band remains, so
    # only a few callouts fit and the rest must overflow.
    words = [_w(30 + 150 * i, 20 + 24 * j, width=100, height=12)
             for i in range(5) for j in range(22)]
    absences = [
        _f(f"expected item {i}; not found on this sheet", source="M-101.pdf",
           hint="SHEET", quote="")
        for i in range(7)
    ]
    assign_qc_ids(absences)
    out = tmp_path / "M-101_reviewed.pdf"
    res = annotate_pdf(src, absences, out, sheet_meta=_meta(words))
    # Every finding accounted, nothing failed.
    assert res.coverage_status == "COMPLETE"
    assert res.tally.get("failed", 0) == 0
    assert res.tally.get("review_notes", 0) >= 1     # some overflowed
    doc = pymupdf.open(str(out))
    try:
        # Locate the review-notes page by its analyzer label.
        notes_pno = next(
            p for p in range(doc.page_count)
            if "AI REVIEW NOTES" in doc[p].get_text().upper()
        )
        wordrects = [pymupdf.Rect(w[0], w[1], w[2], w[3]) for w in words]
        # On the SOURCE page (index=1, after the front index): every callout is
        # in-bounds and never intersects a word.
        src_page = doc[1]
        for a in src_page.annots():
            if a.type[1] != "FreeText":
                continue
            box = pymupdf.Rect(a.rect)
            assert 0 <= box.y0 and box.y1 <= src_page.rect.height + 0.5
            for wr in wordrects:
                assert not box.intersects(wr), f"callout {box} obscures a word"
        # The review-notes page carries the overflow rows, each with a GOTO link
        # back to a source page.
        notes_page = doc[notes_pno]
        note_boxes = [a for a in notes_page.annots() if a.type[1] == "FreeText"]
        assert len(note_boxes) >= 1
        gotos = [lk for lk in notes_page.get_links() if lk.get("kind") == pymupdf.LINK_GOTO]
        assert len(gotos) >= 1
    finally:
        doc.close()


def test_callout_over_drawing_ink_overflows_even_in_a_text_free_band(tmp_path):
    # §17.6: a text-free band is not automatically visually clear. The source PDF
    # draws a dense ink block across the band the word list leaves open; occupancy
    # analysis must reject a callout there and overflow it to the notes page.
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    # A solid black block filling the middle band (y 200-360) — no text there.
    page.draw_rect(pymupdf.Rect(30, 200, 762, 360), color=(0, 0, 0), fill=(0, 0, 0))
    src = tmp_path / "M-101.pdf"
    doc.save(str(src)); doc.close()
    # Word list: text only at the very top and bottom, leaving the inked middle
    # "text-free" to a word-only analysis.
    words = [_w(40 + 150 * i, 20 + 20 * j, width=100, height=12) for i in range(5) for j in range(8)]
    words += [_w(40 + 150 * i, 580, width=100, height=12) for i in range(5)]
    absences = [_f("expected item; not found", source="M-101.pdf", hint="SHEET", quote="")]
    assign_qc_ids(absences)
    out = tmp_path / "M-101_reviewed.pdf"
    res = annotate_pdf(src, absences, out, sheet_meta=_meta(words))
    assert res.coverage_status == "COMPLETE"
    # The one callout could not sit on the inked band, so it is a review note.
    assert res.tally.get("review_notes", 0) == 1
    assert res.tally.get("margin", 0) == 0


def test_multi_page_index_links_work_on_every_index_page(tmp_path):
    # Regression (Codex review): rows used to be drawn while later index pages
    # were still missing, so the first page's link targets failed the bounds
    # guard and were silently dropped. Every index page must carry its links.
    src = _pdf(tmp_path)
    findings = [
        _f(f"finding number {i}", source="M-101.pdf", rect=[10, 10 + 5 * i, 60, 22 + 5 * i])
        for i in range(50)                     # > one index page of rows
    ]
    assign_qc_ids(findings)
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, findings, out)
    doc = pymupdf.open(str(out))
    try:
        assert doc.page_count == 3             # 2 index pages + 1 source page
        assert "(page 1/2)" in doc[0].get_text()
        assert "(page 2/2)" in doc[1].get_text()
        links0 = doc[0].get_links()
        links1 = doc[1].get_links()
        assert len(links0) > 0 and len(links1) > 0
        assert len(links0) + len(links1) == 50
        # Every link targets the (shifted) source page.
        assert all(l["page"] == 2 for l in links0 + links1)
    finally:
        doc.close()


def test_rejected_not_inked_by_default_but_indexed(tmp_path):
    # §18: a REJECTED finding carries no ink by default, but is never invisible —
    # the index page lists it under "Rejected by verification (n)" with a link.
    src = _pdf(tmp_path)
    rejected = _f("wrong", source="M-101.pdf", rect=[10, 10, 60, 30], status="REJECTED")
    assign_qc_ids([rejected])
    out = tmp_path / "r.pdf"
    res = annotate_pdf(src, [rejected], out, include_unverified=True)
    assert res.annots_written == 0             # no ink drawn
    # The rejected-index row is a proven placement — coverage is COMPLETE.
    assert res.coverage_status == "COMPLETE"
    assert [r.status for r in res.receipts] == ["INDEXED"]
    doc = pymupdf.open(str(out))
    try:
        assert doc.page_count == 2             # index page + source
        text = doc[0].get_text()
        assert "Rejected by verification (1)" in text and "wrong" in text
        links = doc[0].get_links()
        assert len(links) == 1 and links[0]["page"] == 1
    finally:
        doc.close()


def test_ink_rejected_draws_grey_struck_markup(tmp_path):
    src = _pdf(tmp_path)
    rejected = _f("wrong", source="M-101.pdf", rect=[10, 10, 60, 30], status="REJECTED")
    assign_qc_ids([rejected])
    out = tmp_path / "r.pdf"
    written = annotate_pdf(
        src, [rejected], out, include_unverified=True, ink_rejected=True
    ).annots_written
    assert written == 2                        # grey cloud + its QC tag
    doc = pymupdf.open(str(out))
    try:
        # Snapshot properties during iteration — PyMuPDF unbinds annot objects
        # once the generator that produced them is released.
        squares = [
            (a.info.get("content", ""), dict(a.colors), dict(a.border))
            for a in doc[1].annots() if a.type[1] == "Square"
        ]
        assert len(squares) == 1
        content, colors, border = squares[0]
        assert content.startswith("[REJECTED]")
        stroke = colors["stroke"]
        assert abs(stroke[0] - 0.45) < 0.01 and abs(stroke[1] - 0.45) < 0.01
        assert tuple(border.get("dashes") or ()) == (4, 3)
    finally:
        doc.close()


def test_unanchored_finding_gets_margin_callout_with_prefix(tmp_path):
    # §18: a quote that matched nothing (the hallucination signal) is flagged on
    # the page as a [QUOTE NOT FOUND] margin callout — never silently dropped.
    src = _pdf(tmp_path)
    f = _f("quote matched nothing", source="M-101.pdf", status="UNCERTAIN")
    f.anchor = Anchor(status="UNANCHORED", method="quote_not_found")
    assign_qc_ids([f])
    out = tmp_path / "r.pdf"
    written = annotate_pdf(src, [f], out, include_unverified=True).annots_written
    assert written == 1
    doc = pymupdf.open(str(out))
    try:
        box = next(a for a in doc[1].annots() if a.type[1] == "FreeText")
        # For FreeText annots /Contents IS the displayed text — the placement
        # and trust prefixes must both be there.
        content = box.info.get("content", "")
        assert content.startswith("[CHECK] [QUOTE NOT FOUND]")
        # The unlocatable quote carries its plain-words caution inline.
        assert "treat with caution" in content
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# QC Findings bookmark outline — Codex review follow-ups (HTML↔PDF links)
# --------------------------------------------------------------------------- #


def test_overflow_review_note_bookmark_targets_the_notes_page(tmp_path):
    # A rect-less finding that overflows to the appended AI Review Notes page
    # must get a bookmark pointing at THAT page (where its callout landed), not
    # its source sheet — the same page its receipt and HTML deep link point at.
    src = _pdf(tmp_path)
    words = [_w(30 + 150 * i, 20 + 24 * j, width=100, height=12)
             for i in range(5) for j in range(22)]
    absences = [
        _f(f"expected item {i}; not found on this sheet", source="M-101.pdf",
           hint="SHEET", quote="")
        for i in range(7)
    ]
    assign_qc_ids(absences)
    out = tmp_path / "M-101_reviewed.pdf"
    res = annotate_pdf(src, absences, out, sheet_meta=_meta(words))
    assert res.tally.get("review_notes", 0) >= 1          # some overflowed

    doc = pymupdf.open(str(out))
    try:
        notes_pno = next(p for p in range(doc.page_count)
                         if "AI REVIEW NOTES" in doc[p].get_text().upper())
        child_pages = {t[2] for t in doc.get_toc(simple=False) if t[0] == 2}
    finally:
        doc.close()

    # Overflow findings are bookmarked to the notes page (1-based), agreeing with
    # their receipts — and never dangle past the document.
    notes_receipts = [r for r in res.receipts if r.placement.expected == "REVIEW_NOTES"]
    assert notes_receipts
    assert all(r.output_page_index == notes_pno for r in notes_receipts)
    assert (notes_pno + 1) in child_pages


def test_bookmark_outline_preserves_existing_source_outline(tmp_path):
    # A source set with its own sheet-navigation bookmarks keeps them in the
    # reviewed copy — the QC Findings section is appended, never substituted.
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page(width=792, height=612).insert_text((80, 120), "VAV-3")
    doc.set_toc([[1, "Sheet Index", 1], [2, "M-101", 1], [2, "M-102", 2]])
    src = tmp_path / "M-101.pdf"
    doc.save(str(src))
    doc.close()

    f = _f("clearance", source="M-101.pdf", page=0, rect=[100, 100, 220, 140])
    assign_qc_ids([f])
    out = tmp_path / "M-101_reviewed.pdf"
    annotate_pdf(src, [f], out)

    rd = pymupdf.open(str(out))
    try:
        titles = [t[1] for t in rd.get_toc(simple=False)]
    finally:
        rd.close()
    # Original outline survived …
    assert "Sheet Index" in titles and "M-101" in titles and "M-102" in titles
    # … and the QC section was appended.
    assert any(t.startswith("QC Findings") for t in titles)
