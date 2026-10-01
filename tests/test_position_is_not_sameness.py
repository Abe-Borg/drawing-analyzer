"""Distinct findings sharing a quote/rectangle survive ingestion and exports.

Tests cover stable QC numbers, coherent evidence, and separate visible PDF tags
using synthetic findings and an offline scripted API client.
"""
from __future__ import annotations

import copy
import itertools

import pytest

from drawing_analyzer.critique import (
    _is_duplicate,
    _signatures_compatible,
    _token_overlap,
)
from drawing_analyzer.ledger import Ledger
from drawing_analyzer.models import Anchor, Finding, Verification

_RECT = [100.0, 200.0, 160.0, 212.0]
_OTHER_RECT = [400.0, 500.0, 460.0, 512.0]

_VOLTAGE = "pump P-1 voltage listed as 480 should be 208"
_IMPELLER = "pump P-1 impeller diameter conflicts with the curve"


def _f(text: str, quote: str, *, cat: str = "coordination", sev: str = "medium",
       rect: list[float] | None = None, sources=(), verdict: str = "") -> Finding:
    finding = Finding(
        sheet_id="M-101", source_name="M-101.pdf", source_id="SRC-0001",
        page_index=0, category=cat, severity=sev, text=text, source_quote=quote,
        anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="exact") if rect else Anchor(),
        sources=list(sources),
    )
    if verdict:
        finding.verification = Verification(status=verdict)
    return finding


def _anchored(finding: Finding, rect: list[float] | None) -> Finding:
    out = copy.deepcopy(finding)
    out.anchor = (Anchor(status="EXACT", rect_pdf=list(rect), method="exact") if rect
                  else Anchor())
    return out


def _exported(entry: Finding) -> str:
    """Everything of a ledger entry that reaches the exports as text."""
    return " ".join([entry.text or "", entry.source_quote or "", *entry.supporting_quotes])


def _lifecycle(findings: list[tuple[Finding, str]], rect: list[float]) -> Ledger:
    """Ingest in the given order, seal, anchor every live entry to ``rect`` (as
    the anchor stage does for findings that quote one string), then number."""
    ledger = Ledger()
    for finding, tag in findings:
        ledger.add([copy.deepcopy(finding)], tag)
    ledger.seal()
    for entry in ledger.entries:
        entry.anchor = Anchor(status="EXACT", rect_pdf=list(rect), method="exact")
    ledger.number()
    return ledger


# --------------------------------------------------------------------------- #
# The N28 pair
# --------------------------------------------------------------------------- #


def test_the_n28_pair_is_not_a_duplicate_on_one_rectangle():
    voltage, impeller = _f(_VOLTAGE, "PUMP P-1"), _f(_IMPELLER, "PUMP P-1")
    # Why no text-overlap threshold separates it from a same-spot paraphrase:
    # it shares more words (0.25) than the CO-1 pair does (0.09).
    assert _token_overlap(_VOLTAGE, _IMPELLER) == pytest.approx(0.25)
    assert _signatures_compatible(voltage, impeller)          # both sign as {P1}
    for rects in ((None, None), (_RECT, _RECT), (_RECT, None)):
        a, b = _anchored(voltage, rects[0]), _anchored(impeller, rects[1])
        assert not _is_duplicate(a, b) and not _is_duplicate(b, a), rects


@pytest.mark.parametrize("order", ["VI", "IV"])
def test_the_n28_pair_survives_the_lifecycle(order):
    items = {"V": (_f(_VOLTAGE, "PUMP P-1"), "digest_json"),
             "I": (_f(_IMPELLER, "PUMP P-1"), "critique_1")}
    ledger = _lifecycle([items[k] for k in order], _RECT)
    assert len(ledger) == 2
    by_text = {e.text: e for e in ledger.entries}
    assert set(by_text) == {_VOLTAGE, _IMPELLER}
    for text, entry in by_text.items():
        assert entry.source_quote == "PUMP P-1"            # each keeps its own bundle
        assert entry.supporting_quotes == []
        assert len(ledger.member_history(entry)) == 1
    exported = " ".join(_exported(e) for e in ledger.entries)
    assert "impeller" in exported and "480" in exported
    assert by_text[_VOLTAGE].qc_id != by_text[_IMPELLER].qc_id


def test_the_n28_pair_gets_the_same_numbers_and_evidence_in_both_orders():
    from drawing_analyzer.verify import _reserve_evidence_dir

    seen = []
    for order in ("VI", "IV"):
        items = {"V": (_f(_VOLTAGE, "PUMP P-1"), "digest_json"),
                 "I": (_f(_IMPELLER, "PUMP P-1"), "critique_1")}
        ledger = _lifecycle([items[k] for k in order], _RECT)
        used: set[str] = set()
        seen.append({e.text: (e.qc_id, _reserve_evidence_dir(e, used))
                     for e in ledger.entries})
    assert seen[0] == seen[1]
    assert len({number for number, _ in seen[0].values()}) == 2
    assert len({folder for _, folder in seen[0].values()}) == 2


# --------------------------------------------------------------------------- #
# Pass A: findings anchored before ingest (the auditors anchor their own)
# --------------------------------------------------------------------------- #

_MISSING = "Sheet reference M-501 is not in the set"
_DRIFT = "M-501 is spelled M501 elsewhere in the set; the naming convention drifts"


@pytest.mark.parametrize("order", ["MD", "DM"])
def test_two_findings_anchored_before_ingest_that_quote_one_tag_stay_apart(order):
    """Two different auditor-shaped issues about one reference, anchored at
    creation to the same rectangle, as the reference and naming auditors do.
    Pass A used to fold them on geometry, since both arrive with a rect."""
    items = {
        "M": (_f(_MISSING, "SEE M-501", cat="reference", rect=_RECT,
                 sources=["auditor_reference"], verdict="DETERMINISTIC"), ""),
        "D": (_f(_DRIFT, "SEE M-501", cat="reference", rect=_RECT,
                 sources=["auditor_naming"], verdict="DETERMINISTIC"), ""),
    }
    assert _token_overlap(_MISSING, _DRIFT) < 0.4
    assert _signatures_compatible(items["M"][0], items["D"][0])   # M-501 == M501
    ledger = Ledger()
    for key in order:
        ledger.add([copy.deepcopy(items[key][0])])
    assert len(ledger) == 2                                      # Pass A
    ledger.seal()
    assert {e.text for e in ledger.entries} == {_MISSING, _DRIFT}


def test_two_arithmetic_mismatches_on_one_row_stay_apart_without_their_discriminators():
    """The WP-03.3 branch matrix's geometry row: the real auditor's two
    mismatches on one row, texts too different for either text branch. Only
    the geometry branch accepted them, so only their claim discriminators kept
    them apart. With the branch gone, the pair stays apart without them too."""
    from tests.test_arithmetic_claim_discriminator import _claim, _pair

    a, b = _pair(
        _claim("sum", [20, 20, 20], 540,
               note="north zone riser flow test column per hydraulic calculation sheet"),
        _claim("sum", [30, 30], 500,
               note="stair pressurization fan schedule totals for level two supply"),
        anchored=True,
    )
    assert a.source_quote == b.source_quote
    assert a.anchor.rect_pdf == b.anchor.rect_pdf is not None
    assert _token_overlap(a.text, b.text) < 0.4
    bare_a, bare_b = copy.deepcopy(a), copy.deepcopy(b)
    bare_a.claim_discriminator = bare_b.claim_discriminator = ""
    assert not _is_duplicate(bare_a, bare_b) and not _is_duplicate(bare_b, bare_a)
    for first, second in ((bare_a, bare_b), (bare_b, bare_a)):
        ledger = Ledger()
        ledger.add([copy.deepcopy(first)])
        ledger.add([copy.deepcopy(second)])
        assert len(ledger) == 2
        ledger.seal()


# --------------------------------------------------------------------------- #
# The predicate reads no rectangle
# --------------------------------------------------------------------------- #

# Same-quote pairs of every shape the suite had folding on geometry, plus the
# shapes that must keep folding on text. For each, the verdict must not depend
# on whether, or where, either finding is anchored.
_SAME_QUOTE_PAIRS = {
    "N28 (different issues, one tag)": (_VOLTAGE, _IMPELLER, "PUMP P-1"),
    "K5 (different issues, one tag)": (
        "pump P-1 has no isolation valve on the suction side",
        "motor horsepower for P-1 disagrees with the pump schedule", "PUMP P-1"),
    "CO-1 same-spot paraphrase": (
        "cleanout required at base of the soil stack per code",
        "provide a cleanout fitting shown on the plumbing detail", "CO-1"),
    "RV-3 same-spot paraphrase": (
        "relief valve setting too high", "RV-3 pressure exceeds vessel MAWP",
        "RV-3 SET 125 PSI"),
    "a reference one side omits": (
        "Pump P-1 suction valve V-3 conflicts with the strainer",
        "Relocate the P-1 inlet strainer", "PUMP P-1 SUCTION"),
    "quote + moderate text (folds)": (
        "relief valve RV-3 setting is too high",
        "relief valve RV-3 setting exceeds maximum", "RV-3 SET 125 PSI"),
    "strong text (folds)": (
        "VAV-3 has no clearance to the wall", "VAV-3 has no clearance to the wall here",
        "VAV-3"),
    "conflicting measurement (never folds)": (
        "chilled water pump flow is 540 gpm", "chilled water pump flow is 560 gpm",
        "CWP-1"),
}


@pytest.mark.parametrize("pair", sorted(_SAME_QUOTE_PAIRS))
def test_the_merge_predicate_reads_no_rectangle(pair):
    ta, tb, quote = _SAME_QUOTE_PAIRS[pair]
    a, b = _f(ta, quote), _f(tb, quote)
    unanchored = _is_duplicate(a, b)
    for ra, rb in ((_RECT, _RECT), (_RECT, [101.0, 201.0, 161.0, 213.0]),
                   (_RECT, _OTHER_RECT), (_RECT, None), (None, _RECT)):
        aa, bb = _anchored(a, ra), _anchored(b, rb)
        assert _is_duplicate(aa, bb) is unanchored, (pair, ra, rb)
        assert _is_duplicate(bb, aa) is unanchored, (pair, ra, rb)


def test_the_pairs_that_fold_on_text_still_fold():
    for pair in ("quote + moderate text (folds)", "strong text (folds)"):
        ta, tb, quote = _SAME_QUOTE_PAIRS[pair]
        ledger = _lifecycle([(_f(ta, quote), "digest_json"),
                                     (_f(tb, quote), "critique_1")], _RECT)
        assert len(ledger) == 1, pair
        assert set(ledger.entries[0].sources) == {"digest_json", "critique_1"}


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #

_CLEARANCE = {
    "sheet_id": "M-101", "category": "coordination", "severity": "medium",
    "text": "VAV-3 clearance to the wall is below the manufacturer minimum",
    "source_quote": "VAV-3", "tile": [0, 0],
}
_AIRFLOW = {
    "sheet_id": "M-101", "category": "coordination", "severity": "medium",
    "text": "VAV-3 airflow disagrees with the schedule",
    "source_quote": "VAV-3", "tile": [0, 0],
}


@pytest.mark.parametrize("order", ["CA", "AC"])
def test_two_digest_findings_quoting_one_tag_stay_two_through_the_pipeline(tmp_path, order):
    """A standard run anchors the digest's findings offline before numbering.
    Both quote the tag, which is printed once, so both anchor EXACT to one
    rectangle; they are two different issues and stay two findings."""
    from drawing_analyzer.pipeline import extract_drawing_context
    from tests.test_drawing_qc_pipeline import _RoutingClient, _make_pdf

    items = {"C": _CLEARANCE, "A": _AIRFLOW}
    assert _token_overlap(_CLEARANCE["text"], _AIRFLOW["text"]) < 0.4
    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([items[k] for k in order])
    ctx = extract_drawing_context([src], client=client, rows=2, cols=2)

    assert sorted(f.text for f in ctx.findings) == sorted(
        [_CLEARANCE["text"], _AIRFLOW["text"]])
    rects = {tuple(f.anchor.rect_pdf) for f in ctx.findings}
    assert len(rects) == 1                                  # one rectangle, two issues
    assert all(f.anchor.status == "EXACT" for f in ctx.findings)
    assert sorted(f.qc_id for f in ctx.findings) == ["QC-001", "QC-002"]


# --------------------------------------------------------------------------- #
# The reviewed PDF: two findings on one rectangle get two readable QC tags
# --------------------------------------------------------------------------- #
#
# Codex review of this slice (P1): keeping the pair apart is only half of it if
# the reviewed drawing cannot show it. A QC tag was laid out from its cloud's
# rectangle alone, so both tags landed at one spot and the later one, drawn
# white-filled over the earlier, hid it. WP-03.3's two arithmetic mismatches on
# one row were already such a pair; this slice made them common.


def _tag_annots(pdf_path) -> list[tuple[str, tuple[float, float, float, float]]]:
    """``(QC number, rect)`` of every QC tag on the reviewed PDF, reopened."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(str(pdf_path))
    try:
        out = []
        for page in doc:
            for annot in page.annots():
                info = annot.info
                if info.get("subject") == "QC tag":
                    r = annot.rect
                    out.append((info.get("content", ""), (r.x0, r.y0, r.x1, r.y1)))
        return out
    finally:
        doc.close()


def _overlap(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("order", ["VI", "IV"])
def test_two_findings_on_one_rectangle_get_two_visible_tags(tmp_path, order, rotation):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.annotate import write_reviewed_pdfs
    from drawing_analyzer.models import assign_qc_ids

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 212), "PUMP P-1")
    if rotation:
        page.set_rotation(rotation)
    src = tmp_path / "M-101.pdf"
    doc.save(str(src))
    doc.close()

    items = {"V": _f(_VOLTAGE, "PUMP P-1", rect=_RECT, verdict="VERIFIED"),
             "I": _f(_IMPELLER, "PUMP P-1", rect=_RECT, verdict="VERIFIED")}
    findings = [items[k] for k in order]
    assign_qc_ids(findings)
    res = write_reviewed_pdfs(findings, [src], tmp_path / "out", include_unverified=True)
    assert res.coverage_status == "COMPLETE"

    tags = _tag_annots(res.reviewed_pdfs[0])
    assert sorted(number for number, _ in tags) == ["QC-001", "QC-002"]
    (_, a), (_, b) = tags
    assert not _overlap(a, b)                           # neither hides the other


def test_a_lone_tag_keeps_its_home_spot():
    from drawing_analyzer.annotate import _home_tag_box, _plan_tag_boxes

    rect = (100.0, 200.0, 160.0, 212.0)
    plan = _plan_tag_boxes([("p1", "QC-001", rect)], 612.0, 792.0)
    # The 1.7.0 layout: above the cloud's top-left corner, 2 pt clear of it.
    assert plan == {"p1": (100.0, 186.0, 144.0, 198.0)}
    assert plan["p1"] == _home_tag_box("QC-001", rect, 612.0, 792.0)


def test_tags_on_one_rectangle_never_overlap_and_follow_the_qc_numbers():
    from drawing_analyzer.annotate import _plan_tag_boxes

    rect = (100.0, 200.0, 160.0, 212.0)
    items = [(f"p{i}", f"QC-{i:03d}", rect) for i in range(1, 13)]
    plans = [_plan_tag_boxes(list(order), 612.0, 792.0)
             for order in (items, items[::-1], items[5:] + items[:5])]
    assert plans[0] == plans[1] == plans[2]             # not the drawing order (I-7)
    boxes = plans[0]
    for a, b in itertools.combinations(boxes.values(), 2):
        assert not _overlap(a, b)
    for box in boxes.values():
        assert 2.0 <= box[0] and box[2] <= 610.0 and 2.0 <= box[1] and box[3] <= 790.0
    assert boxes["p1"] == (100.0, 186.0, 144.0, 198.0)   # QC-001 at home
    assert boxes["p2"][1] == boxes["p1"][1]              # QC-002 beside it


def test_tags_move_away_from_the_cloud_and_never_go_missing():
    from drawing_analyzer.annotate import _home_tag_box, _plan_tag_boxes

    # A cloud at the top edge: tags sit below it, so further rows go down.
    top = (100.0, 4.0, 160.0, 16.0)
    boxes = _plan_tag_boxes([(f"p{i}", f"QC-{i:03d}", top) for i in range(1, 30)],
                            200.0, 792.0)
    assert all(box[1] >= top[3] for box in boxes.values())
    for a, b in itertools.combinations(boxes.values(), 2):
        assert not _overlap(a, b)
    # A page with no room for a second tag: every tag still gets a spot (its
    # home), overlapping rather than dropped.
    tiny = (2.0, 16.0, 60.0, 30.0)
    crowded = _plan_tag_boxes([(f"p{i}", f"QC-{i:03d}", tiny) for i in range(1, 4)],
                              64.0, 32.0)
    assert set(crowded) == {"p1", "p2", "p3"}
    assert crowded["p3"] == _home_tag_box("QC-003", tiny, 64.0, 32.0)


def test_two_digest_findings_quoting_one_tag_get_two_tags_on_the_reviewed_pdf(tmp_path):
    """The pipeline with QC markups on: both findings are clouded on one
    rectangle, and both QC numbers are readable on the reviewed drawing."""
    from drawing_analyzer.pipeline import extract_drawing_context
    from tests.test_drawing_qc_pipeline import _RoutingClient, _make_pdf

    src = _make_pdf(tmp_path / "M-101.pdf")
    client = _RoutingClient([_CLEARANCE, _AIRFLOW])
    ctx = extract_drawing_context(
        [src], client=client, rows=2, cols=2, qc_markups=True,
        qc_work_dir=tmp_path / "qc",
    )
    model = [f for f in ctx.findings if f.source_quote == "VAV-3"]
    assert len(model) == 2 and len({tuple(f.anchor.rect_pdf) for f in model}) == 1
    tags = dict(_tag_annots(ctx.reviewed_pdf_paths[0]))
    numbers = {f.qc_id for f in model}
    assert numbers <= set(tags)
    a, b = (tags[n] for n in sorted(numbers))
    assert not _overlap(a, b)
