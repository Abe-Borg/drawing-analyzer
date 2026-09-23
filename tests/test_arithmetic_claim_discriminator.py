"""Remediation WP-03.3 (review B7): distinct same-row arithmetic mismatches.

Two numeric claims transcribed off ONE row of a table quote the same string, so
before WP-03.3 their mismatch findings shared an id (``compute_finding_id``
hashes sheet, category and quote). Two things then destroyed the second one:

* ``run_auditors`` de-duplicated the battery's findings by that id, keeping one
  while ``stats["arithmetic_mismatched"]`` still counted two;
* with the coordinator bypassed, the ledger merged them anyway, in both arrival
  orders: unitless numbers give an empty critical signature, and the two texts
  share the auditor's boilerplate (Jaccard 0.667 on an equal quote), so the
  quote branch of ``_is_duplicate`` fired. Once anchored (the auditor anchors its
  own findings) the geometry branch fired too, until remediation WP-03.7
  removed it (N28). The UNCERTAIN claim vanished into the DETERMINISTIC
  survivor.

The fix: the coordinator's id dedup is gone; every arithmetic finding carries a
claim discriminator (the host operation, the Decimal-canonical terms as a
multiset, the Decimal-canonical expected value), which blocks the merge in
Pass A and Pass B and is folded into the finding's id. Findings that carry no
discriminator (every model finding) are unaffected. The claim dedups key on
parsed Decimals.

Pure and hermetic: synthetic words and findings, no PyMuPDF, no network.
"""
from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

import pytest

from drawing_analyzer.auditors import run_auditors
from drawing_analyzer.auditors.arithmetic import audit_arithmetic
from drawing_analyzer.critique import _is_duplicate, _token_overlap
from drawing_analyzer.ledger import Ledger, reconcile_post_anchor
from drawing_analyzer.models import (
    Anchor,
    Finding,
    ImageTile,
    NumericClaim,
    RenderedSheet,
    SheetRef,
    Verification,
    compute_finding_id,
)

W, H = 3168.0, 2448.0

# One flow-test row. It carries 20, 20, 20 and 540, so a claim over exactly
# those numbers is TEXT_EXTRACTED (DETERMINISTIC); a claim over 30 + 30 = 500 on
# the same quote is MODEL_TRANSCRIBED (UNCERTAIN), which is the review's shape.
ROW = "20 20 20 TOTAL 540"
SHEET_ID = "F-D-01-1"


def _w(x, y, text, width=64, height=14):
    return (float(x), float(y), float(x + width), float(y + height), text, 0, 0, 0)


def _sheet(source="s.pdf", page=0):
    words = [_w(100, 300, "20"), _w(170, 300, "20"), _w(240, 300, "20"),
             _w(310, 300, "TOTAL"), _w(380, 300, "540"),
             _w(W - 300, H - 160, SHEET_ID)]
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=1, cols=1, words=words,
    )


def _claim(kind, terms, expected, *, quote=ROW, sheet_id=SHEET_ID, source="s.pdf",
           note=""):
    return NumericClaim(
        sheet_id=sheet_id, quote=quote, kind=kind, terms=list(terms),
        expected=expected, note=note, source_name=source, page_index=0,
    )


def _det():
    return _claim("sum", [20, 20, 20], 540)          # 60 ≠ 540, operands on the row


def _unc():
    return _claim("sum", [30, 30], 500)              # 60 ≠ 500, operands not on the row


def _factor():
    return _claim("factor", [1500, "1.3"], 2000)     # the review's second claim


def _arith(findings):
    return [f for f in findings if "auditor_arithmetic" in f.sources]


# --------------------------------------------------------------------------- #
# The auditor and the coordinator
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("second", [_unc, _factor], ids=["sum-30-30", "factor-1500-1.3"])
def test_two_mismatches_on_one_row_get_distinct_ids(second):
    res = audit_arithmetic([_det(), second()], [_sheet()])
    assert res.mismatched == 2 and len(res.findings) == 2
    a, b = res.findings
    assert a.source_quote == b.source_quote == ROW
    assert a.id != b.id


@pytest.mark.parametrize("second", [_unc, _factor], ids=["sum-30-30", "factor-1500-1.3"])
def test_run_auditors_keeps_both_mismatches_and_its_tally(second):
    res = run_auditors([_sheet()], claims=[_det(), second()])
    arith = _arith(res.findings)
    assert len(arith) == 2
    assert res.stats["arithmetic_mismatched"] == len(arith) == 2
    assert len({f.id for f in arith}) == 2


def test_the_mismatch_tally_matches_the_findings_that_leave_the_coordinator():
    # §7.1 B7: the counter and the retained findings agree. Seven claims: one
    # match, one unusable, one repeated, four distinct mismatches, three of them
    # on one row.
    claims = [
        _claim("sum", [20, 20], 40),                        # matches
        _claim("sum", ["abc"], 3),                          # unusable
        _det(), _det(),                                     # the same claim twice
        _unc(), _factor(),
        _claim("sum", [1, 1], 9, quote="OTHER ROW 9"),
    ]
    res = run_auditors([_sheet()], claims=claims)
    arith = _arith(res.findings)
    assert res.stats["arithmetic_checked"] == 5
    assert res.stats["arithmetic_matched"] == 1
    assert res.stats["arithmetic_unusable"] == 1
    assert res.stats["arithmetic_mismatched"] == len(arith) == 4


def test_the_coordinator_hands_every_auditor_finding_to_the_ledger(monkeypatch):
    """The coordinator no longer adjudicates duplicates; the ledger does. Two
    auditors reporting the same thing reach it separately, and it still folds
    them into one entry that names both."""
    import drawing_analyzer.auditors as A

    def _twin(tag):
        return Finding(
            sheet_id=SHEET_ID, source_name="s.pdf", page_index=0,
            category="reference", severity="low",
            text="The drawing index lists F-D-09-9, which is not present in the set.",
            source_quote="F-D-09-9",
            anchor=Anchor(status="EXACT", rect_pdf=[10, 10, 60, 24], method="t"),
            verification=Verification(status="DETERMINISTIC"),
            sources=[tag],
        )

    monkeypatch.setattr(A, "audit_references", lambda _s, stats=None: [_twin("auditor_reference")])
    monkeypatch.setattr(A, "audit_sheet_index", lambda _s: [_twin("auditor_sheet_index")])
    monkeypatch.setattr(A, "audit_naming", lambda _s: [])
    monkeypatch.setattr(A, "audit_titleblock", lambda _s: [])
    res = run_auditors([_sheet()])
    assert len(res.findings) == 2
    assert res.stats["reference_findings"] == res.stats["sheet_index_findings"] == 1

    led = Ledger()
    led.add(res.findings)
    assert len(led) == 1
    assert set(led.entries[0].sources) == {"auditor_reference", "auditor_sheet_index"}


def _tb_labeled(source, page, sheet_id, lines):
    """A title-block band with labelled fields (as in ``test_drawing_auditors``)."""
    words = [_w(W - 300, H - 160, sheet_id)]
    y = 300
    for line_words in lines:
        x = 2320
        for tok in line_words:
            words.append(_w(x, y, tok, width=90))
            x += 110
        y += 40
    ref = SheetRef(pdf_path=Path(source), page_index=page, source_name=source, page_count=1)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=W, page_height_pt=H,
        rows=1, cols=1, words=words,
    )


def test_titleblock_dedups_on_sheet_and_quote_not_on_the_id(monkeypatch):
    """Both title-block paths catch one drifting value on one sheet. The dedup
    is keyed on (sheet, quote), so it does not depend on what the content id
    happens to hash: with an id that folds the text, the old id dedup kept
    both copies."""
    import drawing_analyzer.auditors.titleblock as T

    sheets = [_tb_labeled("s.pdf", i, f"F-D-0{i}-1", [["PROJECT", "NO.", "2021-045"]])
              for i in range(3)]
    sheets.append(_tb_labeled("s.pdf", 3, "F-D-03-1", [["PROJECT", "NO.", "2021-046"]]))

    assert [f.source_quote for f in T.audit_titleblock(sheets)] == ["2021-046"]

    made = T._make_tb_finding

    def _id_by_text(*args, **kwargs):
        f = made(*args, **kwargs)
        f.id = hashlib.sha1(f.text.encode("utf-8")).hexdigest()[:12]
        return f

    monkeypatch.setattr(T, "_make_tb_finding", _id_by_text)
    findings = T.audit_titleblock(sheets)
    assert [f.source_quote for f in findings] == ["2021-046"]
    # First wins: the labelled path, which names the field.
    assert findings[0].text.startswith("Title-block project number")


# --------------------------------------------------------------------------- #
# The ledger: Pass A, Pass B, numbering
# --------------------------------------------------------------------------- #


def _lifecycle(claims, sheets):
    """``run_auditors`` → ``Ledger.add`` → seal → Pass B → ``number()``."""
    res = run_auditors(sheets, claims=claims)
    led = Ledger()
    led.add(res.findings)
    led.seal()
    reconcile_post_anchor(led)
    led.number()
    return res, _arith(led.entries)


def _alone(claims, stated, sheets):
    """The finding the auditor produces for the one claim stating ``stated``."""
    claim = next(c for c in claims if str(c.expected) == stated)
    (finding,) = audit_arithmetic([claim], sheets).findings
    return finding


@pytest.mark.parametrize("anchored", [True, False], ids=["anchored", "unresolved-sheet"])
def test_both_mismatches_survive_the_whole_lifecycle_in_both_orders(anchored):
    by_order = []
    for order in ([_det(), _unc()], [_unc(), _det()]):
        if anchored:
            claims, sheets = order, [_sheet()]
        else:
            # A sheet id the set does not contain and no emitting source: the
            # claim resolves to no sheet, so neither finding is anchored.
            claims = [NumericClaim(sheet_id="Z-999", quote=c.quote, kind=c.kind,
                                   terms=c.terms, expected=c.expected) for c in order]
            sheets = []
        res, entries = _lifecycle(claims, sheets)
        assert res.stats["arithmetic_mismatched"] == 2
        assert len(entries) == 2, [e.text for e in entries]
        for e in entries:
            assert (e.anchor.rect_pdf is not None) == anchored
            assert e.sources == ["auditor_arithmetic"]
            assert e.supporting_quotes == []
        by_text = {e.text: e for e in entries}
        det = next(e for t, e in by_text.items() if "states 540" in t)
        unc = next(e for t, e in by_text.items() if "states 500" in t)
        assert "20, 20, 20" in det.text and "30, 30" in unc.text
        # Each keeps the verdict the auditor gives its claim alone. Operand
        # provenance itself is WP-07.1's (N3), so it is compared, not restated.
        for entry, alone in ((det, _alone(claims, "540", sheets)),
                             (unc, _alone(claims, "500", sheets))):
            assert entry.verification.status == alone.verification.status
            assert entry.verification.operand_origin == alone.verification.operand_origin
            assert entry.id == alone.id
        if anchored:
            # The review's shape: a DETERMINISTIC mismatch beside an UNCERTAIN
            # one. The UNCERTAIN claim used to vanish into the other.
            assert det.verification.status == "DETERMINISTIC"
        assert unc.verification.status == "UNCERTAIN"
        assert det.id != unc.id and det.qc_id != unc.qc_id
        by_order.append({e.text: (e.id, e.qc_id) for e in entries})
    # The same claims get the same ids and numbers whatever order they arrive in.
    assert by_order[0] == by_order[1]


def test_three_mismatches_on_one_row_survive_in_every_order():
    claims = [_det(), _unc(), _factor()]
    seen = set()
    for order in itertools.permutations(claims):
        _res, entries = _lifecycle(list(order), [_sheet()])
        assert len(entries) == 3
        seen.add(tuple(sorted((e.text, e.qc_id) for e in entries)))
    assert len(seen) == 1


def _pair(a_claim, b_claim, *, anchored):
    sheets = [_sheet()] if anchored else []
    res = audit_arithmetic([a_claim, b_claim], sheets)
    assert len(res.findings) == 2
    return res.findings


@pytest.mark.parametrize(
    "branch, a_claim, b_claim, anchored",
    [
        # Strong topical overlap (>= 0.7): only the stated total differs.
        ("text", _claim("sum", [20, 20, 20], 540, quote=""),
         _claim("sum", [20, 20, 20], 550, quote=""), False),
        # An equal quote with moderate overlap (0.4 .. 0.7).
        ("quote", _det(), _unc(), False),
        # WP-03.3 had a third row: an equal quote on one rectangle, texts too
        # different for either text branch, accepted only by the geometry
        # branch. Remediation WP-03.7 (N28) removed that branch, so no branch
        # accepts the pair and its discriminators have nothing left to block:
        # it stays apart without them
        # (tests/test_position_is_not_sameness.py).
    ],
)
def test_the_discriminator_holds_against_every_accepting_branch(branch, a_claim, b_claim, anchored):
    a, b = _pair(a_claim, b_claim, anchored=anchored)
    tov = _token_overlap(a.text, b.text)
    if branch == "text":
        assert tov >= 0.7
    else:
        assert a.source_quote == b.source_quote and 0.4 <= tov < 0.7

    # Precondition: without their discriminators the branch accepts the pair.
    bare_a, bare_b = _strip(a), _strip(b)
    assert _is_duplicate(bare_a, bare_b) and _is_duplicate(bare_b, bare_a)

    assert not _is_duplicate(a, b) and not _is_duplicate(b, a)
    for first, second in ((a, b), (b, a)):
        led = Ledger()
        led.add([_copy(first)])
        led.add([_copy(second)])
        assert len(led) == 2                       # Pass A
        led.seal()
        assert reconcile_post_anchor(led) == 0     # Pass B
        assert len(led) == 2


def _strip(f: Finding) -> Finding:
    """``f`` as it would read without a claim discriminator (the 1.7.0 shape)."""
    out = _copy(f)
    if hasattr(out, "claim_discriminator"):
        out.claim_discriminator = ""
    return out


def _copy(f: Finding) -> Finding:
    import copy

    return copy.deepcopy(f)


def test_pass_b_does_not_fold_two_mismatches_anchored_after_ingest():
    """Two mismatches on one row, too different in text for either text
    branch, arrive unanchored and then anchor to the row. Before remediation
    WP-03.7 (N28) Pass B's geometry branch accepted them and only their claim
    discriminators kept them apart; no branch reads a rectangle now."""
    a, b = _pair(
        _claim("sum", [20, 20, 20], 540,
               note="north zone riser flow test column per hydraulic calculation sheet"),
        _claim("sum", [30, 30], 500,
               note="stair pressurization fan schedule totals for level two supply"),
        anchored=False,
    )
    for first, second in ((a, b), (b, a)):
        led = Ledger()
        led.add([_copy(first)])
        led.add([_copy(second)])
        assert len(led) == 2                       # no rectangle yet, weak text
        led.seal()
        for e in led.entries:                      # as resolve_anchors would
            e.anchor = Anchor(status="EXACT", rect_pdf=[100, 300, 444, 314], method="t")
        assert reconcile_post_anchor(led) == 0
        led.number()
        assert len(led) == 2
        assert len({e.id for e in led.entries}) == 2
        assert len({e.qc_id for e in led.entries}) == 2


def test_an_absorbed_members_discriminator_still_blocks_a_different_claim():
    """A merged entry's live bundle can belong to a model member that carries
    no discriminator. The arithmetic member it absorbed still blocks a
    different claim, because Pass A compares every member's snapshot. The
    model member here is a generic bridge: a duplicate of BOTH mismatches."""
    unc = audit_arithmetic([_unc()], []).findings[0]
    det = audit_arithmetic([_det()], []).findings[0]
    bridge = Finding(
        sheet_id=SHEET_ID, source_name="s.pdf", page_index=0, category="conflict",
        severity="high",
        text="Arithmetic does not check out: the sum is 60, but the sheet states otherwise",
        source_quote="20 20 20 TOTAL 540 GPM AT RISER 3",   # longer: wins the bundle
    )
    assert _is_duplicate(bridge, unc) and _is_duplicate(bridge, det)
    assert unc.verification.status == "UNCERTAIN"

    led = Ledger()
    led.add([_copy(bridge)], "critique_1")
    led.add([_copy(unc)])
    assert len(led) == 1
    entry = led.entries[0]
    assert entry.text == bridge.text
    assert getattr(entry, "claim_discriminator", "") == ""   # the bridge's bundle
    led.add([_copy(det)])
    assert len(led) == 2
    texts = sorted(e.text for e in led.entries)
    assert texts == sorted([bridge.text, det.text])


# --------------------------------------------------------------------------- #
# Scope: true duplicates still merge; model findings are unaffected
# --------------------------------------------------------------------------- #


def test_an_auditor_mismatch_still_merges_with_its_model_twin_and_wins_the_bundle():
    det = audit_arithmetic([_det()], [_sheet()]).findings[0]
    twin = Finding(
        sheet_id=SHEET_ID, source_name="s.pdf", page_index=0, category="conflict",
        severity="medium",
        text="Flow test column: the sum of 20, 20, 20 is 60, but the sheet states 540",
        source_quote=ROW,
    )
    for order in ((twin, "critique_1"), (det, "")), ((det, ""), (twin, "critique_1")):
        led = Ledger()
        for finding, tag in order:
            led.add([_copy(finding)], tag)
        assert len(led) == 1
        e = led.entries[0]
        assert e.text == det.text and e.id == det.id
        assert e.verification.status == "DETERMINISTIC"
        assert e.anchor.rect_pdf == det.anchor.rect_pdf
        assert set(e.sources) == {"auditor_arithmetic", "critique_1"}


def test_a_model_twin_joins_its_own_mismatch_and_the_other_survives():
    det, unc = audit_arithmetic([_det(), _unc()], [_sheet()]).findings
    twin = Finding(
        sheet_id=SHEET_ID, source_name="s.pdf", page_index=0, category="conflict",
        severity="medium",
        text="Flow test column: the sum of 20, 20, 20 is 60, but the sheet states 540",
        source_quote=ROW,
    )
    for order in itertools.permutations([(twin, "critique_1"), (det, ""), (unc, "")]):
        led = Ledger()
        for finding, tag in order:
            led.add([_copy(finding)], tag)
        led.seal()
        reconcile_post_anchor(led)
        led.number()
        assert len(led) == 2
        by_id = {e.id: e for e in led.entries}
        assert set(by_id) == {det.id, unc.id}
        assert set(by_id[det.id].sources) == {"auditor_arithmetic", "critique_1"}
        assert by_id[unc.id].sources == ["auditor_arithmetic"]


def test_one_claim_read_twice_is_one_finding():
    # Both critique reads transcribe the row, once as JSON numbers and once as
    # strings: one claim, one check, one finding.
    res = run_auditors([_sheet()], claims=[
        _claim("sum", [20, 20, 20], 540),
        _claim("sum", ["20.0", "20", 20.0], "540"),
    ])
    assert res.stats["arithmetic_checked"] == 1
    assert len(_arith(res.findings)) == 1


def test_findings_without_a_discriminator_merge_exactly_as_before():
    a = Finding(sheet_id="M-101", source_name="m.pdf", page_index=0, category="conflict",
                severity="low", text="the sum of the terms is 540", source_quote="TOTAL CFM 540")
    b = Finding(sheet_id="M-101", source_name="m.pdf", page_index=0, category="conflict",
                severity="low", text="the sum of the terms is 560", source_quote="TOTAL CFM 540")
    assert _is_duplicate(a, b)
    one = _copy(a)
    one.claim_discriminator = "arithmetic/1:sum:20,20,20=540"
    # A discriminator on ONE side never blocks: a model twin has none.
    assert _is_duplicate(one, b) and _is_duplicate(b, one)


# --------------------------------------------------------------------------- #
# Identity and serialization
# --------------------------------------------------------------------------- #


def test_the_discriminator_is_folded_into_the_id_and_nothing_else_moves():
    plain = Finding(sheet_id="M-101", source_name="m.pdf", page_index=0,
                    category="conflict", severity="low", text="t", source_quote="Q",
                    source_id="SRC-0001")
    assert plain.id == compute_finding_id("M-101", "conflict", "Q", "SRC-0001")
    assert compute_finding_id("M-101", "conflict", "Q") == compute_finding_id(
        "M-101", "conflict", "Q", "", "")

    tagged = Finding(sheet_id="M-101", source_name="m.pdf", page_index=0,
                     category="conflict", severity="low", text="t", source_quote="Q",
                     source_id="SRC-0001", claim_discriminator="arithmetic/1:sum:1,1=9")
    assert tagged.id == compute_finding_id(
        "M-101", "conflict", "Q", "SRC-0001", "arithmetic/1:sum:1,1=9")
    assert tagged.id != plain.id
    # Domain-separated from the source id: a discriminator is never read as one.
    assert compute_finding_id("M-101", "conflict", "Q", "", "X") != compute_finding_id(
        "M-101", "conflict", "Q", "X")


def test_the_discriminator_round_trips_and_an_old_payload_defaults_cleanly():
    f = audit_arithmetic([_det()], [_sheet()]).findings[0]
    assert f.claim_discriminator
    d = f.to_dict()
    assert d["claim_discriminator"] == f.claim_discriminator
    back = Finding.from_dict(d)
    assert back.claim_discriminator == f.claim_discriminator and back.id == f.id

    d.pop("claim_discriminator")
    old = Finding.from_dict(d)
    assert old.claim_discriminator == "" and old.id == f.id    # stored id kept

    # Every finding without one serializes exactly as before: no new key.
    plain = Finding(sheet_id="M-101", source_name="m.pdf", page_index=0,
                    category="code", severity="low", text="t")
    assert "claim_discriminator" not in plain.to_dict()


def test_the_discriminator_rides_the_winning_bundle():
    det = audit_arithmetic([_det()], [_sheet()]).findings[0]
    twin = Finding(
        sheet_id=SHEET_ID, source_name="s.pdf", page_index=0, category="conflict",
        severity="medium",
        text="Flow test column: the sum of 20, 20, 20 is 60, but the sheet states 540",
        source_quote=ROW,
    )
    led = Ledger()
    led.add([twin], "critique_1")
    led.add([det])
    e = led.entries[0]
    assert e.claim_discriminator == det.claim_discriminator and e.id == det.id


# --------------------------------------------------------------------------- #
# The discriminator and the Decimal claim keys
# --------------------------------------------------------------------------- #


def test_the_discriminator_names_the_operation_the_terms_and_the_total():
    from drawing_analyzer.auditors.arithmetic import arithmetic_claim_discriminator

    d = arithmetic_claim_discriminator
    base = d("sum", [20, 20, 20], 540)
    # Decimal-canonical: every spelling of the same values is one claim.
    assert d("sum", ["20.0", 20.0, " 20 "], "540") == base
    assert d("SUM", [20, 20, 20], "540.00") == base
    # A multiset: sum and product commute, so read order is not the claim.
    assert d("sum", [30, 20], 60) == d("sum", [20, 30], 60)
    # factor is the product the host computes.
    assert d("factor", [1500, "1.3"], 2000) == d("product", ["1.3", 1500], 2000)
    # Everything the host computes with discriminates.
    assert d("product", [20, 20, 20], 540) != base
    assert d("sum", [20, 20], 540) != base
    assert d("sum", [20, 20, 20, 0], 540) != base
    assert d("sum", [20, 20, 20], 550) != base
    assert d("sum", ["1,200", 1], 5) == d("sum", [1200, 1], 5)


def test_arithmetic_dedups_on_parsed_decimals():
    pairs = [
        ([20, 20], ["20.0", 20]),               # a decimal spelling
        ([20, 20], [20.0, 20]),                 # a JSON float
        ([1200, 1], ["1,200", 1]),              # a thousands group
        ([20, 30], [30, 20]),                   # read in the other order
    ]
    for left, right in pairs:
        res = audit_arithmetic([_claim("sum", left, 99), _claim("sum", right, "99.0")], [])
        assert res.checked == 1 and res.mismatched == 1 and len(res.findings) == 1, (left, right)
    res = audit_arithmetic([_claim("factor", [1500, "1.3"], 2000),
                            _claim("product", [1500, "1.3"], 2000)], [])
    assert res.checked == 1 and len(res.findings) == 1


def test_an_unparseable_term_never_collapses_two_different_claims():
    res = audit_arithmetic([_claim("sum", ["abc", 1], 2), _claim("sum", ["abd", 1], 2)], [])
    assert res.unusable == 2 and res.checked == 0
    # "12,5" is not one value (a tight binder), so it is kept raw, never read as 12.5.
    res = audit_arithmetic([_claim("sum", [20], "12,5"), _claim("sum", [20], "12.5")], [])
    assert res.unusable == 1 and res.checked == 1 and len(res.findings) == 1
    res = audit_arithmetic([_claim("sum", ["abc", 1], 2), _claim("sum", ["abc", 1], 2)], [])
    assert res.unusable == 1                     # an identical raw term is one claim


def test_the_claim_value_key_is_exact_and_tags_raw_terms():
    from drawing_analyzer.auditors.arithmetic import claim_value_key

    k = claim_value_key
    assert k(20) == k("20.0") == k(20.0) == k(" 20 ") == k("20.000") == "20"
    assert k(0) == k("-0") == k("0.0") == "0"
    assert k("0.50") == "0.5" and k("1,950") == "1950"
    assert k("2 1/2") == k("2.5")
    # No rounding at the decimal context's 28 digits.
    long_a, long_b = "1234567890123456789012345678901", "1234567890123456789012345678902"
    assert k(long_a) != k(long_b)
    # Never raises, even past the default context's exponent limit: two of the
    # dedups that use it have no per-claim guard.
    huge = "1" + "0" * 1_000_001
    assert k(huge) == huge and k(huge) != k(huge[:-1])
    # Raw terms are tagged, so no raw spelling can equal a parsed value.
    assert k("abc") == "raw:abc" and k(None) == "raw:None"
    assert k("abc") != k("abd")
    assert k("12,5") != k("12.5")


def test_the_critique_claim_dedup_keys_on_parsed_decimals():
    from drawing_analyzer.critique import _dedup_claims

    same = [_claim("sum", [20, 20], 540), _claim("sum", ["20.0", 20.0], "540.0"),
            _claim("sum", [20, 20], "540")]
    assert len(_dedup_claims(same)) == 1
    different = [_claim("sum", ["abc", 1], 2), _claim("sum", ["abd", 1], 2),
                 _claim("sum", [20, 20], 541)]
    assert len(_dedup_claims(different)) == 3


def test_the_cross_qc_claim_dedup_keys_on_parsed_decimals():
    from drawing_analyzer.cross_qc import _dedup_claims

    same = [_claim("sum", [20, 20], 540), _claim("sum", ["20.0", 20.0], "540.0")]
    assert len(_dedup_claims(same)) == 1
    different = [_claim("sum", ["abc", 1], 2), _claim("sum", ["abd", 1], 2)]
    assert len(_dedup_claims(different)) == 2
