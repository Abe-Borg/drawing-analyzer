"""Phase B — the pre-seal edition audit (`citation_check.reconcile_cited_editions`).

Pure, hermetic unit tests (I-4): the divergence detection matrix, the two-tier
operand-corroboration trust model, dedup, and deterministic ordering. No model,
no PyMuPDF — findings and geometries are lightweight stubs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drawing_analyzer.citation_check import (
    _adopted_basis_map,
    _family_year_re,
    reconcile_cited_editions,
)
from drawing_analyzer.models import AdoptedCode, Finding, SetIdentity, SheetRef


def _ref(page: int = 0, name: str = "FP-101.pdf") -> SheetRef:
    return SheetRef(pdf_path=Path(f"/tmp/{name}"), page_index=page,
                    source_name=name, page_count=9, source_id="SRC-0001")


@dataclass
class _Geom:
    ref: SheetRef
    sheet_text: str = ""


def _finding(text="note cites a code", *, refs, quote="", page=0,
             name="FP-101.pdf", sheet_id="FP-101"):
    return Finding(
        sheet_id=sheet_id, source_name=name, source_id="SRC-0001",
        page_index=page, category="code", severity="medium",
        text=text, source_quote=quote, refs=list(refs),
    )


def _identity(*codes: AdoptedCode) -> SetIdentity:
    return SetIdentity(adopted_codes=tuple(codes))


_STATED = "GENERAL NOTES: ALL SPRINKLER WORK PER NFPA 13, 2016 EDITION."


# --------------------------------------------------------------------------- #
# Detection matrix
# --------------------------------------------------------------------------- #


def test_cited_edition_matching_adopted_is_no_finding():
    geoms = [_Geom(_ref(), _STATED)]
    f = _finding(refs=["NFPA 13 2016 §8.1.2"], quote="PER NFPA 13 2016")
    assert reconcile_cited_editions([f], None, geoms) == []


def test_regex_corroborated_divergence_is_deterministic_medium():
    geoms = [_Geom(_ref(), _STATED + "\nRELIEF PER NFPA 13 2013 §8.15.1")]
    f = _finding(refs=["NFPA 13 2013 §8.15.1"], quote="PER NFPA 13 2013")
    (d,) = reconcile_cited_editions([f], None, geoms)
    assert d.severity == "medium"
    assert d.verification.status == "DETERMINISTIC"
    assert d.sources == ["edition_audit"]
    assert d.category == "code"
    assert '"NFPA 13 2013 §8.15.1" cites NFPA 13 2013' in d.text
    assert "adopts NFPA 13 2016" in d.text
    assert "(stated in the drawing text)" in d.text
    # Anchors to the stale-edition text ITSELF (its own matched span), never
    # the citing finding's whole quote — a copied quote would land on the
    # identical rect and Pass B would fold the two findings into one.
    assert d.source_quote == "NFPA 13 2013"
    assert d.sheet_id == "FP-101" and d.source_id == "SRC-0001"
    assert d.refs == ["NFPA 13 2013 §8.15.1"]


def test_identity_quote_refound_counts_as_corroborated():
    # Worldwide path: the family comes from identity (no US regex hit), but the
    # evidence quote re-finds verbatim in the sheet text → text-grounded basis.
    # The cited side re-finds in the sheet text too → fully corroborated tier.
    text = ("ALLGEMEINE HINWEISE: SPRINKLERANLAGEN NACH DIN EN 12845:2020.\n"
            "ALTBESTAND: SIEHE DIN EN 12845:2009 §11.2.")
    geoms = [_Geom(_ref(), text)]
    identity = _identity(AdoptedCode(
        code="DIN EN 12845", edition="2020",
        quote="SPRINKLERANLAGEN NACH DIN EN 12845:2020", source_sheet="FP-101",
    ))
    f = _finding(refs=["DIN EN 12845:2009 §11.2"],
                 quote="NACH DIN EN 12845:2009")
    (d,) = reconcile_cited_editions([f], identity, geoms)
    assert d.severity == "medium"
    assert d.verification.status == "DETERMINISTIC"
    assert "(stated on FP-101)" in d.text
    assert d.source_quote == "DIN EN 12845:2009"      # the sheet's own span


def test_cited_side_only_in_the_model_quote_stays_advisory():
    # The adopted basis is text-stated, but the cited edition appears ONLY in
    # the model-transcribed quote (not the sheet text): one operand is not a
    # text fact → advisory tier, anchored best-effort to the quote's span.
    geoms = [_Geom(_ref(), "ALLGEMEINE HINWEISE: NACH DIN EN 12845:2020.")]
    identity = _identity(AdoptedCode(
        code="DIN EN 12845", edition="2020", quote="NACH DIN EN 12845:2020",
    ))
    f = _finding(refs=["DIN EN 12845:2009 §11.2"], quote="NACH DIN EN 12845:2009")
    (d,) = reconcile_cited_editions([f], identity, geoms)
    assert d.severity == "low"
    assert d.verification.status != "DETERMINISTIC"
    assert d.source_quote == "DIN EN 12845:2009"      # quote-derived span


def test_identity_only_basis_is_low_severity_advisory():
    # The quote does NOT re-find (scanned set) → advisory tier: low severity,
    # default verification (crop-verified downstream), labeled advisory.
    geoms = [_Geom(_ref(), "OCR FAILED, NO USABLE TEXT")]
    identity = _identity(AdoptedCode(
        code="GB 50016", edition="2014", quote="按 GB 50016 2014 执行",
    ))
    f = _finding(refs=["GB 50016 2006 §5.1"], quote="按 GB 50016 2006")
    (d,) = reconcile_cited_editions([f], identity, geoms)
    assert d.severity == "low"
    assert d.verification.status != "DETERMINISTIC"
    assert "model-detected basis — advisory" in d.text


def test_identity_entry_without_quote_contributes_no_basis():
    identity = _identity(AdoptedCode(code="BS 9251", edition="2021", quote=""))
    f = _finding(refs=["BS 9251 2014 §6"], quote="TO BS 9251 2014")
    assert reconcile_cited_editions([f], identity, []) == []


def test_adopted_entry_without_year_never_asserts_divergence():
    identity = _identity(AdoptedCode(code="NFPA 13", edition="latest",
                                     quote="PER NFPA 13 LATEST EDITION"))
    f = _finding(refs=["NFPA 13 2013 §8.1"], quote="NFPA 13 2013")
    assert reconcile_cited_editions([f], identity, []) == []


def test_ref_without_year_and_unadopted_family_skip():
    geoms = [_Geom(_ref(), _STATED)]
    no_year = _finding(refs=["NFPA 13 §8.1.2"], quote="PER NFPA 13")
    other_code = _finding(refs=["ASCE 7 2010 §12"], quote="ASCE 7 2010")
    assert reconcile_cited_editions([no_year, other_code], None, geoms) == []


def test_multi_edition_adoption_accepts_any_adopted_year():
    text = _STATED + "\nEXISTING AREAS REMAIN PER NFPA 13 2010 EDITION."
    geoms = [_Geom(_ref(), text)]
    ok1 = _finding(refs=["NFPA 13 2016 §9.1"], quote="NFPA 13 2016")
    ok2 = _finding(refs=["NFPA 13 2010 §9.1"], quote="NFPA 13 2010")
    bad = _finding(refs=["NFPA 13 2002 §9.1"], quote="NFPA 13 2002")
    out = reconcile_cited_editions([ok1, ok2, bad], None, geoms)
    assert len(out) == 1
    assert "cites NFPA 13 2002" in out[0].text
    assert "adopts NFPA 13 2010/2016" in out[0].text     # sorted multi-edition


def test_section_number_is_never_read_as_an_edition_year():
    # "IBC §2019.3" — the separator class excludes "." and "§", so a section
    # number that LOOKS like a year can't create a divergence.
    geoms = [_Geom(_ref(), "ALL WORK PER THE 2021 IBC.")]
    f = _finding(refs=["IBC §2019.3"], quote="IBC §2019.3")
    assert reconcile_cited_editions([f], None, geoms) == []
    rx = _family_year_re("IBC")
    assert not rx.search("IBC §2019.3")
    assert rx.search("IBC 2019")
    assert not _family_year_re("NFPA 13").search("NFPA 130 2016 STANDARD")


def test_dedup_one_finding_per_sheet_family_year():
    geoms = [_Geom(_ref(), _STATED)]
    f1 = _finding(refs=["NFPA 13 2013 §8.15.1"], quote="NFPA 13 2013 §8.15.1")
    f2 = _finding("another note", refs=["NFPA 13 2013 §19.2"], quote="")
    out = reconcile_cited_editions([f1, f2], None, geoms)
    assert len(out) == 1
    # Refs union sorted; the quote is the cited edition's own matched span.
    assert out[0].refs == ["NFPA 13 2013 §19.2", "NFPA 13 2013 §8.15.1"]
    assert out[0].source_quote == "NFPA 13 2013"


def test_quoteless_divergence_becomes_sheet_level():
    geoms = [_Geom(_ref(), _STATED)]
    f = _finding(refs=["NFPA 13 2013 §8.15.1"], quote="")
    (d,) = reconcile_cited_editions([f], None, geoms)
    assert d.source_quote == "" and d.anchor_hint == "SHEET"
    # Cited year not re-findable anywhere → advisory tier even though the
    # adopted basis is text-stated (BOTH operands must be corroborated).
    assert d.severity == "low"


def test_deterministic_ordering_across_sheets_and_years():
    geoms = [
        _Geom(_ref(0), _STATED),
        _Geom(_ref(1), ""),
    ]
    findings = [
        _finding(refs=["NFPA 13 2013 §1"], quote="NFPA 13 2013", page=1),
        _finding(refs=["NFPA 13 2010 §1"], quote="NFPA 13 2010", page=0),
        _finding(refs=["NFPA 13 2013 §1"], quote="NFPA 13 2013", page=0),
    ]
    out = reconcile_cited_editions(findings, None, geoms)
    keys = [(f.page_index, f.text.split(" cites ")[1][:12]) for f in out]
    assert keys == sorted(keys)
    out2 = reconcile_cited_editions(list(reversed(findings)), None, geoms)
    assert [f.text for f in out2] == [f.text for f in out]   # order-independent


def test_citation_shaped_mentions_never_enter_the_basis():
    # The stale citation itself ("NFPA 13 2013 §8.15.1" in the text layer) must
    # not launder 2013 into the adopted basis and self-suppress the finding —
    # a mention followed by a section marker is a citation, not an adoption.
    from drawing_analyzer.citation_check import _basis_edition_claims

    geoms = [_Geom(_ref(), _STATED + "\nRELIEF PER NFPA 13 2013 §8.15.1")]
    assert _basis_edition_claims(geoms) == ["NFPA 13 2016"]
    basis = _adopted_basis_map(None, geoms)
    assert basis["NFPA 13"].years == frozenset({"2016"})
    # ...while an adoption-shaped second edition still counts (multi-edition).
    geoms2 = [_Geom(_ref(), _STATED + "\nEXISTING PER NFPA 13 2010 EDITION.")]
    assert set(_adopted_basis_map(None, geoms2)["NFPA 13"].years) == {"2016", "2010"}


def test_identity_none_runs_regex_only():
    geoms = [_Geom(_ref(), _STATED + "\nRELIEF PER NFPA 13 2013 §8.15.1")]
    f = _finding(refs=["NFPA 13 2013 §8.15.1"], quote="NFPA 13 2013")
    out = reconcile_cited_editions([f], None, geoms)
    assert len(out) == 1 and out[0].verification.status == "DETERMINISTIC"
    # And with neither identity nor stated editions there is no basis at all.
    assert reconcile_cited_editions([f], None, [_Geom(_ref(), "no codes")]) == []
    assert _adopted_basis_map(None, []) == {}


def test_reconcile_never_raises_on_malformed_inputs():
    class _Junk:
        refs = ["NFPA 13 2013"]
        source_quote = None
        source_id = ""
        source_name = "x.pdf"
        page_index = 0
        sheet_id = ""
        tile = None

    geoms = [_Geom(_ref(), _STATED)]
    out = reconcile_cited_editions([_Junk()], None, geoms)   # duck-typed entry
    assert isinstance(out, list)
