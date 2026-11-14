"""Interactive reviewed PDFs: isolate a finding, mark a finding done.

What the viewer does with the file cannot be run here, so these tests pin what
the viewer is given: which layers exist and how they start, what each markup's
visibility depends on, which script each control runs, and that one Done field
spans the cover page and the sheets. The rule those scripts compute is tested
on its own in ``tests/test_markup_scripts.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from drawing_analyzer import markup_scripts as M
from drawing_analyzer.models import Anchor, Finding, Verification, assign_qc_ids

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.annotate import (  # noqa: E402
    _SEVERITY_LAYER_NAMES,
    _SHEET_NOTES_LAYER,
    annotate_pdf,
)


def _pdf(tmp_path: Path, name: str = "M-101.pdf") -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((300, 300), "TOTAL DEMAND 1250 GPM", fontsize=10)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _finding(text, *, rect=None, status="VERIFIED", severity="high", hint="", quote="q"):
    f = Finding(
        sheet_id="M-101", source_name="M-101.pdf", page_index=0, category="conflict",
        severity=severity, text=text, source_quote=quote, anchor_hint=hint,
        anchor=Anchor(status="EXACT", rect_pdf=list(rect), method="t") if rect else Anchor(),
    )
    f.verification = Verification(status=status)
    return f


def _refs(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"(\d+) 0 R", text or "")]


def _script_of(doc, action_xref: int) -> str:
    """The JavaScript an action object carries, as the viewer would read it."""
    obj = doc.xref_object(action_xref, compressed=True)
    body = re.search(r"/JS\((.*)\)", obj, re.S).group(1)
    return (
        body.replace("\\n", "\n").replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
    )


def _layers(doc) -> dict:
    return {info["name"]: (xref, info["on"]) for xref, info in doc.get_ocgs().items()}


def _panel(doc) -> list[str]:
    """The layer names the viewer's Layers panel lists."""
    names = {xref: info["name"] for xref, info in doc.get_ocgs().items()}
    order = doc.xref_get_key(doc.pdf_catalog(), "OCProperties/D/Order")[1]
    return [names[x] for x in _refs(order)]


def _fields(doc) -> dict:
    """``{field name: [(page index, widget xref), …]}`` over the whole document."""
    out: dict = {}
    for pno in range(doc.page_count):
        for w in doc[pno].widgets():
            out.setdefault(w.field_name, []).append((pno, w.xref))
    return out


def _text_with_every_layer_on(doc, pno: int) -> str:
    """A page's text as it reads with every layer showing. Text on a layer that
    starts off is skipped by a plain read, exactly as a viewer skips drawing it."""
    copy = pymupdf.open("pdf", doc.tobytes())
    try:
        copy.xref_set_key(copy.pdf_catalog(), "OCProperties/D/OFF", "[]")
        shown = pymupdf.open("pdf", copy.tobytes())
        try:
            return shown[pno].get_text()
        finally:
            shown.close()
    finally:
        copy.close()


def _page_layer_refs(doc, page) -> set[int]:
    """Every object the page's content can name as a layer (its
    ``/Resources /Properties``)."""
    kind, value = doc.xref_get_key(page.xref, "Resources")
    if kind == "xref":
        value = doc.xref_object(_refs(value)[0], compressed=True)
    props = re.search(r"/Properties\s*<<(.*?)>>", value or "", re.S)
    if props is None:
        ref = re.search(r"/Properties\s+(\d+) 0 R", value or "")
        return set(_refs(doc.xref_object(int(ref.group(1)), compressed=True))) if ref else set()
    return set(_refs(props.group(1)))


def _page_annots(doc, page) -> list[int]:
    return _refs(doc.xref_get_key(page.xref, "Annots")[1])


def test_each_drawn_finding_can_be_isolated_and_marked_done(tmp_path):
    src = _pdf(tmp_path)
    cloud = _finding("total does not add up", rect=[296, 288, 420, 306])
    callout = _finding("no hanger note on this sheet", status="UNCERTAIN",
                       severity="low", hint="SHEET", quote="")
    ruled_out = _finding("riser tag duplicated", rect=[100, 100, 160, 120], status="REJECTED")
    findings = [cloud, callout, ruled_out]
    assign_qc_ids(findings)
    out = tmp_path / "r.pdf"
    res = annotate_pdf(src, findings, out, include_unverified=True, interactive=True)
    # Interactivity is additive: the same placements, the same proof.
    assert res.coverage_status == "COMPLETE"
    assert res.tally == {"cloud": 1, "margin": 1, "rejected": 1}

    doc = pymupdf.open(str(out))
    try:
        layers = _layers(doc)
        drawn = (cloud.qc_id, callout.qc_id)
        # Four layers per drawn finding, starting as "nothing done, nothing
        # isolated"; none for the finding that is not in the PDF.
        for qc in drawn:
            assert layers[M.live_layer_name(qc)][1] is True
            assert layers[M.done_layer_name(qc)][1] is False
            assert layers[M.only_layer_name(qc)][1] is False
            assert layers[M.tick_layer_name(qc)][1] is False
        assert M.live_layer_name(ruled_out.qc_id) not in layers
        # The Layers panel still lists only the layers a person uses.
        assert sorted(_panel(doc)) == sorted([
            _SEVERITY_LAYER_NAMES["high"], _SEVERITY_LAYER_NAMES["low"], _SHEET_NOTES_LAYER,
        ])

        # A markup shows only while BOTH its severity layer and its own layer
        # are on: the panel's severity switch and a cover-page click both work.
        sheet = doc[1]
        square = next(a for a in sheet.annots() if a.type[1] == "Square")
        membership = doc.xref_object(
            _refs(doc.xref_get_key(square.xref, "OC")[1])[0], compressed=True,
        )
        assert "/AllOn" in membership
        assert set(_refs(membership)) == {
            layers[_SEVERITY_LAYER_NAMES["high"]][0], layers[M.live_layer_name(cloud.qc_id)][0],
        }

        # One Done FIELD per drawn finding, with a box on the cover page and a
        # box by the markup: the same field, so one tick is both ticks.
        fields = _fields(doc)
        assert set(fields) == {M.done_field_name(qc) for qc in drawn}
        for qc in drawn:
            pages = sorted(pno for pno, _x in fields[M.done_field_name(qc)])
            assert pages == [0, 1]
        sync = M.sync_script(None)
        for _pno, widget in fields[M.done_field_name(cloud.qc_id)]:
            action = _refs(doc.xref_get_key(widget, "A")[1])[0]
            assert _script_of(doc, action) == sync
        # Ticks are saved; layer visibility is not. The same script re-applies
        # the ticks every time the document opens.
        opener = _refs(doc.xref_get_key(doc.pdf_catalog(), "Names/JavaScript/Names")[1])[0]
        assert _script_of(doc, opener) == sync

        # A cover row jumps to its markup FIRST and isolates it second, so a
        # viewer that runs no scripts still navigates.
        cover = doc[0]
        row_actions = [
            doc.xref_get_key(x, "A")[1] for x in _page_annots(doc, cover)
            if "/Link" in doc.xref_object(x, compressed=True)
        ]
        jumps = [a for a in row_actions if "/GoTo" in a]
        assert len(jumps) == 2
        isolated = {
            _script_of(doc, _refs(a.split("/Next")[1])[0]) for a in jumps
        }
        assert all(a.index("/GoTo") < a.index("/Next") for a in jumps)
        assert isolated == {M.sync_script(qc) for qc in drawn}
        # ...and the way back is on the cover page and on the sheet.
        show_all = M.sync_script("")
        for page in (cover, sheet):
            scripts_here = set()
            for x in _page_annots(doc, page):
                action = doc.xref_get_key(x, "A")
                if "/Link" in doc.xref_object(x, compressed=True) and action[0] == "xref":
                    scripts_here.add(_script_of(doc, _refs(action[1])[0]))
            assert show_all in scripts_here

        # A cover row is shaded on its finding's TICK layer, which isolating
        # another finding leaves alone, so the cover page keeps showing what is
        # done. Nothing on the cover page hangs on a layer isolation switches.
        cover_layers = _page_layer_refs(doc, cover)
        for qc in drawn:
            assert layers[M.tick_layer_name(qc)][0] in cover_layers
            assert layers[M.done_layer_name(qc)][0] not in cover_layers
            assert layers[M.live_layer_name(qc)][0] not in cover_layers

        # The grey copy and the "showing this one only" note are page content
        # on the finding's own done / only layers, so they add no markup.
        text = _text_with_every_layer_on(doc, 1)
        sheet_layers = _page_layer_refs(doc, sheet)
        for qc in drawn:
            assert f"{qc} DONE" in text and f"SHOWING {qc} ONLY" in text
            for name in (M.done_layer_name(qc), M.only_layer_name(qc)):
                assert layers[name][0] in sheet_layers
        assert f"{ruled_out.qc_id} DONE" not in text
        # As the file opens, neither is showing.
        assert "DONE" not in sheet.get_text() and "ONLY" not in sheet.get_text()
        assert sum(1 for a in sheet.annots() if a.type[1] == "Square") == 1
    finally:
        doc.close()


def test_a_plain_file_and_an_unusable_qc_number_get_no_interactive_parts(tmp_path):
    src = _pdf(tmp_path)
    f = _finding("total does not add up", rect=[296, 288, 420, 306])
    assign_qc_ids([f])

    def summary(path):
        doc = pymupdf.open(str(path))
        try:
            catalog = doc.xref_object(doc.pdf_catalog(), compressed=True)
            return (
                [n for n in _layers(doc) if n.startswith(M.LAYER_PREFIX)],
                _fields(doc), "JavaScript" in catalog,
                sum(1 for a in doc[1].annots() if a.type[1] == "Square"),
            )
        finally:
            doc.close()

    # Not asked for: nothing added to the file.
    annotate_pdf(src, [f], tmp_path / "plain.pdf")
    assert summary(tmp_path / "plain.pdf") == ([], {}, False, 1)

    # Asked for, but the id cannot be written into a layer name, a field name
    # and a script safely: the finding is still drawn, as a plain markup.
    f.qc_id = 'QC-1"); app.alert(1); ("'
    res = annotate_pdf(src, [f], tmp_path / "odd.pdf", interactive=True)
    assert res.coverage_status == "COMPLETE"
    assert summary(tmp_path / "odd.pdf") == ([], {}, False, 1)


def test_the_drawings_own_layers_fields_and_scripts_are_kept(tmp_path):
    # A CAD export arrives with layers of its own, and a form or a script is
    # possible. The reviewed copy must still have every one of them.
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((300, 300), "TOTAL DEMAND 1250 GPM", fontsize=10)
    wall = doc.add_ocg("A-WALL", on=True)
    page.draw_line((50, 50), (700, 50), oc=wall)
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "reviewer_initials"
    widget.rect = pymupdf.Rect(600, 560, 700, 580)
    page.add_widget(widget)
    theirs = doc.get_new_xref()
    doc.update_object(theirs, "<</S/JavaScript/JS(var theirs = 1;)>>")
    doc.xref_set_key(doc.pdf_catalog(), "Names", f"<</JavaScript<</Names[(theirs) {theirs} 0 R]>>>>")
    src = tmp_path / "M-101.pdf"
    doc.save(str(src))
    doc.close()

    f = _finding("total does not add up", rect=[296, 288, 420, 306])
    assign_qc_ids([f])
    out = tmp_path / "r.pdf"
    annotate_pdf(src, [f], out, interactive=True)

    doc = pymupdf.open(str(out))
    try:
        assert "A-WALL" in _panel(doc)
        assert M.live_layer_name(f.qc_id) not in _panel(doc)
        fields = _fields(doc)
        assert "reviewer_initials" in fields and M.done_field_name(f.qc_id) in fields
        names = doc.xref_get_key(doc.pdf_catalog(), "Names/JavaScript/Names")[1]
        scripts = [_script_of(doc, x) for x in _refs(names)]
        assert scripts == ["var theirs = 1;"]        # theirs kept, ours not forced in
    finally:
        doc.close()
