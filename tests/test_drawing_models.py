"""Tests for the QC Finding data contract (§4.1). Pure — no PyMuPDF, no network."""
from __future__ import annotations

from drawing_analyzer.models import (
    Anchor,
    Finding,
    Verification,
    compute_finding_id,
)


def test_finding_id_is_content_derived_and_stable():
    f1 = Finding(
        sheet_id="F-D-01-1", source_name="set.pdf", page_index=0,
        category="reference", severity="medium", text="whatever",
        source_quote="SEE DRAWING F-D-01-0",
    )
    # Derived from sheet_id + category + source_quote (quote preferred over text).
    assert f1.id == compute_finding_id("F-D-01-1", "reference", "SEE DRAWING F-D-01-0")
    # Same content -> same id (dedup relies on this).
    f2 = Finding(
        sheet_id="F-D-01-1", source_name="other.pdf", page_index=9,
        category="reference", severity="low", text="different text",
        source_quote="SEE DRAWING F-D-01-0",
    )
    assert f2.id == f1.id
    # A different quote -> different id.
    f3 = Finding(
        sheet_id="F-D-01-1", source_name="set.pdf", page_index=0,
        category="reference", severity="medium", text="whatever",
        source_quote="SEE DRAWING F-D-02-0",
    )
    assert f3.id != f1.id


def test_finding_id_falls_back_to_text_when_no_quote():
    f = Finding(
        sheet_id="M-101", source_name="set.pdf", page_index=0,
        category="question", severity="low", text="graphics-only finding",
    )
    assert f.id == compute_finding_id("M-101", "question", "graphics-only finding")


def test_finding_explicit_id_is_respected():
    f = Finding(
        sheet_id="M-101", source_name="set.pdf", page_index=0,
        category="code", severity="high", text="x", id="QC-CUSTOM",
    )
    assert f.id == "QC-CUSTOM"


def test_finding_to_dict_round_trips_the_contract():
    f = Finding(
        sheet_id="F-D-01-1", source_name="set.pdf", page_index=2,
        category="reference", severity="medium",
        text="References F-D-01-0; not present in the provided set.",
        source_quote="SEE DRAWING F-D-01-0",
        anchor=Anchor(status="EXACT", rect_pdf=[1.0, 2.0, 3.0, 4.0], method="ref"),
        verification=Verification(status="DETERMINISTIC", note="audit"),
    )
    d = f.to_dict()
    assert d["id"] == f.id
    assert d["category"] == "reference"
    assert d["tile"] is None
    assert d["refs"] == []
    assert d["anchor"] == {"status": "EXACT", "rect_pdf": [1.0, 2.0, 3.0, 4.0], "method": "ref"}
    assert d["verification"] == {
        "status": "DETERMINISTIC", "note": "audit", "evidence_png": "", "evidence": [],
        "computation_method": "", "operand_origin": "",
        "investigated": False, "investigation_rounds": 0,
    }


def test_finding_defaults_are_unanchored_and_skipped():
    f = Finding(
        sheet_id="M-101", source_name="s.pdf", page_index=0,
        category="code", severity="low", text="x",
    )
    assert f.anchor.status == "UNANCHORED" and f.anchor.rect_pdf is None
    assert f.verification.status == "SKIPPED"
    assert f.tile is None and f.refs == []


def test_finding_dict_round_trips_including_id():
    f = Finding(
        sheet_id="F-D-01-1", source_name="set.pdf", page_index=2,
        category="conflict", severity="high", text="VAV-3 conflicts with duct.",
        source_quote="VAV-3", tile=[4, 5], refs=["CMC 310", "NFPA 90A"],
        anchor=Anchor(status="TILE", rect_pdf=[10.5, 20.0, 88.0, 33.0], method="tile"),
        verification=Verification(status="VERIFIED", note="ok", evidence_png="evidence/x.png"),
    )
    back = Finding.from_dict(f.to_dict())
    assert back == f                    # exact round-trip (dataclass equality)
    assert back.id == f.id              # id preserved, not recomputed


def test_finding_from_dict_tolerates_missing_optional_fields():
    minimal = {
        "sheet_id": "M-101", "source_name": "s.pdf", "page_index": 0,
        "category": "code", "severity": "low", "text": "x",
    }
    f = Finding.from_dict(minimal)
    assert f.tile is None and f.refs == []
    assert f.anchor.status == "UNANCHORED"
    assert f.verification.status == "SKIPPED"
    assert f.id  # recomputed from content when absent
    # Additive serialization: a pre-field cached payload defaults cleanly.
    assert f.recommended_action == ""


def test_finding_recommended_action_round_trips_and_defaults():
    f = Finding(
        sheet_id="M-101", source_name="s.pdf", page_index=0,
        category="code", severity="low", text="x",
        recommended_action="Confirm the setpoint with the engineer.",
    )
    d = f.to_dict()
    assert d["recommended_action"] == "Confirm the setpoint with the engineer."
    back = Finding.from_dict(d)
    assert back.recommended_action == f.recommended_action
    assert back == f
    # The action never participates in the content id (I-7: ids stay stable
    # across cache generations that predate the field).
    bare = Finding(
        sheet_id="M-101", source_name="s.pdf", page_index=0,
        category="code", severity="low", text="x",
    )
    assert bare.id == f.id
    # None round-trips to the empty-string default, not the string "None".
    assert Finding.from_dict({**d, "recommended_action": None}).recommended_action == ""
