"""WP-03A — a genuine quote past the prompt cap is still source evidence.

`docs/REVIEW_IMPLEMENTATION_PLAN.md` §2.1 trigger 1: `render` caps `sheet_text`
at `SHEET_TEXT_MAX_CHARS` for the *prompt*, but the sharded cross-QC validators
grounded quotes against that capped string. A quote the model transcribed from
pixels past character 15,000 exists in the source and in the full word stream —
yet `_finding_from_handles` and `_parse_facts` dropped it, and a finding losing
a leg that way falls below the two-grounded-sheets bar and disappears entirely.

These tests pin the fix and, just as importantly, the things it must **not**
change: fabricated quotes still fail, the whole-set (<=40) path is untouched,
prompt bytes are identical, and every cross-QC cache key for an untruncated
sheet stays byte-for-byte what it was — WP-03A deliberately throws away no
stored result (§2.3, §8.5).

Hermetic: fake clients only, no key, no network.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import drawing_analyzer.cross_qc as X
from drawing_analyzer.cross_qc import (
    MAX_SHEETS_SINGLE_CALL,
    _cross_qc_cache_key,
    cross_sheet_qc,
)
from drawing_analyzer.digest import SheetDigest
from drawing_analyzer.models import (
    RenderedSheet,
    SheetGeometry,
    SheetRef,
    sheet_evidence_text,
)
from drawing_analyzer.render import SHEET_TEXT_MAX_CHARS, _cap_sheet_text
from tests.fixtures.fake_anthropic import FakeMessage, FakeTextBlock, FakeUsage

from tests.test_drawing_cross_qc import BetaClientMixin, StreamingMessagesMixin

W, H = 792.0, 612.0

# A quote a model could plausibly transcribe from pixels on a dense notes sheet.
TAIL_QUOTE = "PRE-ACTION VALVE PV-3 SERVES DATA HALL 2"
FILLER = "GENERAL NOTE LINE. "


def _w(x, y, text, w=60, h=12):
    return (float(x), float(y), float(x + w), float(y + h), text, 0, 0, 0)


def _ref(source: str) -> SheetRef:
    return SheetRef(pdf_path=Path(source), page_index=0, source_name=source,
                    page_count=1)


def _geom(source: str, sid: str, *, full_text: str | None = None,
          sheet_text: str | None = None) -> SheetGeometry:
    """A geometry whose capped and full texts can be set independently.

    When ``full_text`` is given, ``sheet_text`` defaults to the *real* capped
    form of it, so the fixture reproduces what the renderer actually produces
    rather than an impossible hand-built pairing.
    """
    if full_text is not None and sheet_text is None:
        sheet_text = _cap_sheet_text(full_text)
    return SheetGeometry(
        ref=_ref(source), page_width_pt=W, page_height_pt=H, rows=2, cols=2,
        words=[_w(W - 300, H - 160, sid)],
        sheet_text=sheet_text if sheet_text is not None else f"{sid} sheet text",
        full_sheet_text=full_text,
    )


def _dense_full_text(sid: str, tail: str) -> str:
    """Text long enough that ``tail`` lands past the cap, as on a notes sheet."""
    body = FILLER * ((SHEET_TEXT_MAX_CHARS // len(FILLER)) + 40)
    return f"{sid} title. {body} {tail}"


def _digest(source: str, text: str = "Sheet - FP - Plan") -> SheetDigest:
    return SheetDigest(ref=_ref(source), text=text)


# --------------------------------------------------------------------------- #
# The fixture itself must be honest before anything is asserted through it
# --------------------------------------------------------------------------- #


def test_the_tail_quote_really_is_past_the_cap():
    """Guard the premise: if this stops holding, every test below is vacuous."""
    full = _dense_full_text("F-D-00-1", TAIL_QUOTE)
    capped = _cap_sheet_text(full)
    assert TAIL_QUOTE in full
    assert TAIL_QUOTE not in capped
    assert len(full) > SHEET_TEXT_MAX_CHARS


# --------------------------------------------------------------------------- #
# Case 1 + 2 — tail evidence accepted, fabrication still rejected
# --------------------------------------------------------------------------- #


class _TailClient(BetaClientMixin):
    """Content-aware sharded fake.

    Emits a fact for a sheet only when that sheet's handle actually reached the
    shard, and reports the reconciled conflict only when BOTH its handles reached
    the reconcile call — so a pass proves the evidence travelled, not that the
    fake echoes unconditionally.
    """

    def __init__(self, quote_a: str, quote_b: str):
        self.map_calls = 0
        self.reconcile_calls = 0
        self.whole_set_calls = 0
        self._qa, self._qb = quote_a, quote_b
        outer = self

        class _Msgs(StreamingMessagesMixin):
            def create(self, **kw):  # noqa: ANN001, ANN202
                system = kw.get("system", "")
                body = kw["messages"][0]["content"][0]["text"]
                if system.startswith(X.CROSS_QC_RECONCILE_SYSTEM_PROMPT[:60]):
                    outer.reconcile_calls += 1
                    present = all(re.search(rf"\b{h}\b", body) for h in ("S001", "S022"))
                    fin = {
                        "sheet_handle": "S001", "category": "conflict",
                        "severity": "high", "text": "valve assignment disagrees",
                        "recommended_action": "Reconcile PV-3.",
                        "source_quote": outer._qa,
                        "also_on": [{"sheet_handle": "S022", "source_quote": outer._qb}],
                    }
                    obj = {"findings": [fin] if present else [], "claims": []}
                elif not body.startswith("DRAWING SET SHARD"):
                    # The whole-set and shard-map system prompts share the same
                    # persona prefix, so they cannot be told apart by ``system``.
                    # The shard body is the reliable discriminator.
                    outer.whole_set_calls += 1
                    obj = {"findings": [], "claims": []}
                else:
                    outer.map_calls += 1
                    facts = []
                    for h in re.findall(r"SHEET (S\d+)", body):
                        quote = {"S001": outer._qa, "S022": outer._qb}.get(h)
                        if quote is None:
                            continue
                        facts.append({
                            "sheet_handle": h, "entity_or_tag": "PV-3",
                            "attribute": "serves", "value": "hall",
                            "exact_quote": quote, "context": "note",
                        })
                    obj = {"findings": [], "claims": [], "facts": facts}
                return FakeMessage(
                    content=[FakeTextBlock(text="```json\n" + json.dumps(obj) + "\n```")],
                    usage=FakeUsage(input_tokens=800, output_tokens=60),
                )

        self.messages = _Msgs()


def _sharded_set(embed_a: str, embed_b: str):
    """42 entries (> 40) across two disciplines; sheets 1 and 22 carry evidence.

    ``embed_a`` is placed past sheet 1's cap and ``embed_b`` inside sheet 22's,
    so a test isolates the tail case rather than changing two things at once.
    What the sheets *contain* is deliberately separate from what the fake client
    later *claims* — otherwise a "fabricated quote" test would be handed a
    grounded quote and pass for the wrong reason.
    """
    sheets, geoms = [], []
    sheets.append(_digest("f0.pdf"))
    geoms.append(_geom("f0.pdf", "F-D-00-1",
                       full_text=_dense_full_text("F-D-00-1", embed_a)))
    for i in range(1, 21):
        sheets.append(_digest(f"f{i}.pdf"))
        geoms.append(_geom(f"f{i}.pdf", f"F-D-{i:02d}-1"))
    sheets.append(_digest("m0.pdf"))
    geoms.append(_geom("m0.pdf", "M-D-00-1",
                       full_text=f"M-D-00-1 title. {embed_b} more text"))
    for i in range(1, 21):
        sheets.append(_digest(f"m{i}.pdf"))
        geoms.append(_geom(f"m{i}.pdf", f"M-D-{i:02d}-1"))
    assert len(sheets) == 42 > MAX_SHEETS_SINGLE_CALL
    return sheets, geoms


def test_tail_quote_survives_the_sharded_path():
    """Case 1: the finding this package exists to stop losing."""
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    client = _TailClient(TAIL_QUOTE, TAIL_QUOTE)
    res = cross_sheet_qc(sheets, geoms, client=client, sleep=lambda *_: None)

    assert client.reconcile_calls >= 1, "the cross-shard reconcile never ran"
    assert len(res.findings) == 1, res.error
    finding = res.findings[0]
    assert finding.source_quote == TAIL_QUOTE
    assert len(finding.also_on) == 1, "the second grounded leg was dropped"


def test_tail_quote_was_dropped_before_the_fix():
    """The same set, with the full text unavailable, still loses the finding.

    Pins the defect itself: with ``full_sheet_text=None`` the validator falls
    back to the capped string — exactly the pre-WP-03A behaviour — and the
    finding disappears. If this ever starts passing, the fallback broke.
    """
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    for g in geoms:
        g.full_sheet_text = None                     # pre-WP-03A geometry
    res = cross_sheet_qc(sheets, geoms, client=_TailClient(TAIL_QUOTE, TAIL_QUOTE),
                         sleep=lambda *_: None)
    assert res.findings == [], "the capped-text fallback should still reject it"


def test_fabricated_quote_is_still_rejected():
    """Case 2: the fix must not become "accept everything"."""
    ghost = "ZONE ZZ-99 SERVES NOTHING AT ALL"
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)   # real evidence embedded
    for g in geoms:                                        # ...but never the ghost
        assert ghost not in sheet_evidence_text(g)
    res = cross_sheet_qc(sheets, geoms, client=_TailClient(ghost, ghost),
                         sleep=lambda *_: None)
    assert res.findings == [], "an ungrounded quote must not become a trusted leg"


def test_quote_present_only_on_another_sheet_is_rejected():
    """Grounding is per sheet: the right words on the wrong sheet is not evidence."""
    # Sheet 1 holds the tail quote; sheet 22 holds something else entirely.
    sheets, geoms = _sharded_set(TAIL_QUOTE, "UNRELATED NOTE ABOUT DUCTWORK")
    # The client claims the tail quote for BOTH, so S022's leg is ungrounded.
    res = cross_sheet_qc(sheets, geoms, client=_TailClient(TAIL_QUOTE, TAIL_QUOTE),
                         sleep=lambda *_: None)
    assert res.findings == [], "a quote absent from its own sheet is not a leg"


# --------------------------------------------------------------------------- #
# Case 3 — threshold scope: the whole-set path is untouched
# --------------------------------------------------------------------------- #


def test_forty_entries_take_the_whole_set_path_unchanged():
    """<=40 entries must not gain a capped-text check (that would import §2.1)."""
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    sheets, geoms = sheets[:MAX_SHEETS_SINGLE_CALL], geoms[:MAX_SHEETS_SINGLE_CALL]
    client = _TailClient(TAIL_QUOTE, TAIL_QUOTE)
    cross_sheet_qc(sheets, geoms, client=client, sleep=lambda *_: None)
    assert client.whole_set_calls == 1, "40 entries take the single whole-set call"
    assert client.map_calls == 0, "40 entries must not shard"
    assert client.reconcile_calls == 0


def test_forty_one_entries_take_the_sharded_path():
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    n = MAX_SHEETS_SINGLE_CALL + 1
    client = _TailClient(TAIL_QUOTE, TAIL_QUOTE)
    cross_sheet_qc(sheets[:n], geoms[:n], client=client, sleep=lambda *_: None)
    assert client.map_calls >= 1


def test_failed_and_empty_digests_do_not_count_toward_the_threshold():
    """The bar is *retained readable entries*, not selected pages.

    42 pages are selected — above the threshold — but two digests are unusable,
    leaving exactly 40 retained entries, so this set takes the **whole-set**
    path. Reading the page count as the retained count would predict sharding
    and be wrong, which is the trap §8.7 case 3 names.
    """
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    assert len(sheets) == MAX_SHEETS_SINGLE_CALL + 2
    sheets[5].text = ""                               # empty digest → not retained
    sheets[6].error = "boom"                          # failed digest → not retained
    client = _TailClient(TAIL_QUOTE, TAIL_QUOTE)
    cross_sheet_qc(sheets, geoms, client=client, sleep=lambda *_: None)
    assert client.whole_set_calls == 1, "40 retained entries is not > 40"
    assert client.map_calls == 0

    # One fewer unusable digest → 41 retained → the sharded path really does open.
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    sheets[5].text = ""
    client = _TailClient(TAIL_QUOTE, TAIL_QUOTE)
    cross_sheet_qc(sheets, geoms, client=client, sleep=lambda *_: None)
    assert client.map_calls >= 1, "41 retained entries must shard"


# --------------------------------------------------------------------------- #
# Case 4 + 5 — the field itself: fidelity and compatibility
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text", [
    "line one\nline two\r\nline three",
    "COLONNE Ø50 — DÉTAIL n°3 · 25 °C",
    "tab\tseparated\tcolumns",
    "",
])
def test_full_text_survives_geometry_and_spool_untouched(text, tmp_path):
    """Case 4: no truncation, no normalization, through every hop."""
    from drawing_analyzer.models import ImageTile
    from drawing_analyzer.render_spool import RenderedSheetSpool

    tile = ImageTile(png_bytes=b"\x89PNG\r\n", width_px=1, height_px=1, kind="overview")
    rendered = RenderedSheet(
        ref=_ref("s.pdf"), overview=tile, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=2, cols=2, sheet_text=_cap_sheet_text(text), full_sheet_text=text,
        text_chars_total=len(text),
    )
    assert SheetGeometry.from_rendered(rendered).full_sheet_text == text

    spool = RenderedSheetSpool(parent=tmp_path)
    try:
        assert spool.put("k", rendered) is True
        restored = spool.pop("k")
        assert restored is not None
        assert restored.full_sheet_text == text
        assert restored.text_chars_total == len(text)
    finally:
        spool.close()


def test_spool_preserves_unavailable_as_unavailable(tmp_path):
    """``None`` must not become ``""`` in transit — they mean different things."""
    from drawing_analyzer.models import ImageTile
    from drawing_analyzer.render_spool import RenderedSheetSpool

    tile = ImageTile(png_bytes=b"\x89PNG\r\n", width_px=1, height_px=1, kind="overview")
    rendered = RenderedSheet(
        ref=_ref("s.pdf"), overview=tile, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=2, cols=2, sheet_text="capped", full_sheet_text=None,
    )
    spool = RenderedSheetSpool(parent=tmp_path)
    try:
        spool.put("k", rendered)
        restored = spool.pop("k")
        assert restored.full_sheet_text is None
        assert sheet_evidence_text(restored) == "capped"
    finally:
        spool.close()


def test_prescan_geometry_carries_the_uncapped_text(tmp_path):
    """The level-1 / cache-hit path must supply evidence too, not just rendering.

    Both routes into ``sheet_geometries`` are covered: ``from_rendered`` above,
    and ``_sheet_geometry_no_render`` here. A sheet that skipped rasterization on
    a warm run would otherwise ground against capped text again.
    """
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import iter_sheet_prescan

    full = _dense_full_text("F-D-00-1", TAIL_QUOTE)
    path = tmp_path / "dense.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    y = 10.0
    for chunk in (full[i:i + 110] for i in range(0, len(full), 110)):
        if y > H - 10:
            break
        page.insert_text((8, y), chunk, fontsize=4)
        y += 5.0
    doc.save(str(path))
    doc.close()

    (_ref_out, _identity, geom), = list(iter_sheet_prescan([path]))
    assert geom.full_sheet_text is not None, "prescan lost the host evidence"
    assert len(geom.full_sheet_text) > len(geom.sheet_text.rstrip("[TRUNCATED]\n "))
    assert geom.text_chars_total == len(geom.full_sheet_text)
    # And the evidence helper prefers it over the capped string.
    assert sheet_evidence_text(geom) == geom.full_sheet_text


def test_empty_full_text_does_not_fall_back_to_capped_text():
    """Case 5: a textless sheet has no textual evidence — say so, don't substitute."""
    geom = _geom("s.pdf", "A-1", sheet_text="LEFTOVER CAPPED TEXT", full_text="")
    assert sheet_evidence_text(geom) == ""


def test_absent_full_text_falls_back_for_compatibility():
    geom = _geom("s.pdf", "A-1", sheet_text="CAPPED", full_text=None)
    assert sheet_evidence_text(geom) == "CAPPED"


# --------------------------------------------------------------------------- #
# Case 7 — prompt stability: the model sees exactly what it saw before
# --------------------------------------------------------------------------- #


def test_full_text_never_reaches_a_prompt():
    """The tail is host-side evidence only; adding the field must not widen input.

    Asserted on a sentinel embedded ONLY past sheet 1's cap. Using ``TAIL_QUOTE``
    would be a false alarm: sheet 22 carries it legitimately inside its capped
    text, so it belongs in the prompt from there.
    """
    sentinel = "SENTINEL-BEYOND-THE-CAP-ZQX"
    sheets, geoms = _sharded_set(sentinel, "UNRELATED NOTE")
    assert sentinel in sheet_evidence_text(geoms[0])
    assert sentinel not in geoms[0].sheet_text, "sentinel must be past the cap"
    seen: list[str] = []

    class _Recorder(_TailClient):
        def __init__(self):
            super().__init__(TAIL_QUOTE, TAIL_QUOTE)
            inner = self.messages

            class _Msgs(StreamingMessagesMixin):
                def create(self, **kw):  # noqa: ANN001, ANN202
                    seen.append(kw["messages"][0]["content"][0]["text"])
                    return inner.create(**kw)

            self.messages = _Msgs()

    cross_sheet_qc(sheets, geoms, client=_Recorder(), sleep=lambda *_: None)
    assert seen, "no prompt was captured"
    for body in seen:
        assert sentinel not in body, "the uncapped tail leaked into a prompt"


# --------------------------------------------------------------------------- #
# Case 8 — cache keys: preserved for every untruncated sheet (§2.3)
# --------------------------------------------------------------------------- #


def _key(geoms) -> str:
    entries = [
        (f"SID-{i}", "digest text", g.sheet_text, g)
        for i, g in enumerate(geoms)
    ]
    return _cross_qc_cache_key(entries, model="m", preamble="")


def test_untruncated_sheets_keep_a_byte_identical_cache_key():
    """The whole point of the conditional hash: no stored result is discarded."""
    before = [_geom("a.pdf", "A-1"), _geom("b.pdf", "B-1")]
    for g in before:
        g.full_sheet_text = None                      # a pre-WP-03A geometry
    after = [_geom("a.pdf", "A-1"), _geom("b.pdf", "B-1")]
    for g in after:
        g.full_sheet_text = g.sheet_text              # untruncated: full == capped
    assert _key(before) == _key(after)


def test_a_truncated_sheet_keys_distinctly():
    """Two sets identical in the prompt but differing past the cap must not collide."""
    base = _dense_full_text("A-1", "TAIL ALPHA")
    other = _dense_full_text("A-1", "TAIL BETA")
    assert _cap_sheet_text(base) == _cap_sheet_text(other), "prefixes must match"
    a = [_geom("a.pdf", "A-1", full_text=base)]
    b = [_geom("a.pdf", "A-1", full_text=other)]
    assert _key(a) != _key(b)


def test_no_cross_qc_contract_bump_was_needed():
    """WP-03A must not invalidate stored results; WP-03B is where that happens."""
    assert X._CROSS_QC_CACHE_CONTRACT == 2


# --------------------------------------------------------------------------- #
# Case 11 — the tail must not leak anywhere it is not evidence
# --------------------------------------------------------------------------- #


def test_result_carries_no_raw_tail_text():
    sheets, geoms = _sharded_set(TAIL_QUOTE, TAIL_QUOTE)
    res = cross_sheet_qc(sheets, geoms, client=_TailClient(TAIL_QUOTE, TAIL_QUOTE),
                         sleep=lambda *_: None)
    blob = json.dumps(res.discards.to_dict() if res.discards else {})
    assert TAIL_QUOTE not in blob
    assert FILLER.strip() not in blob
