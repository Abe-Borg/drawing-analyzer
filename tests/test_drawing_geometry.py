"""Phase 19 — canonical page geometry (PAGE_VIEW_V2) characterization + round-trip.

Two layers:

1. **Pure helpers** (no PyMuPDF): :func:`normalize_rect`, :func:`transform_rect`,
   :class:`PageGeometry`, matrix identity — the dependency-free coordinate math.
2. **Characterization + round-trip** (needs PyMuPDF, skipped without it): a minimal
   reproducible fixture that *locks* the actual PyMuPDF coordinate behavior this
   codebase relies on (so a future engine change breaks loudly, not silently), and
   proves a finding survives render → anchor → verify-crop → annotate correctly at
   every page rotation and under a non-default CropBox — the DA-003 defect and its
   fix. These assertions fail on the pre-Phase-19 baseline (anchors in un-rotated
   ``get_text`` space) on rotated pages, and pass now.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from drawing_analyzer.models import (
    COORDINATE_SPACE_VERSION,
    IDENTITY_MATRIX,
    Anchor,
    Finding,
    PageGeometry,
    is_identity_matrix,
    normalize_rect,
    transform_rect,
)

ROTATIONS = (0, 90, 180, 270)


# --------------------------------------------------------------------------- #
# Pure helpers — no PyMuPDF
# --------------------------------------------------------------------------- #


def test_normalize_rect_sorts_inverted_corners():
    # An inverted rect (a transform artifact) is *sorted*, never clamped.
    assert normalize_rect([30, 40, 10, 20]) == [10, 20, 30, 40]
    assert normalize_rect([10, 20, 30, 40]) == [10, 20, 30, 40]


def test_normalize_rect_rejects_non_finite_and_empty():
    for bad in ([0, 0, float("nan"), 10], [0, 0, float("inf"), 10]):
        with pytest.raises(ValueError):
            normalize_rect(bad)
    for empty in ([5, 5, 5, 20], [5, 5, 20, 5], [5, 5, 5, 5]):
        with pytest.raises(ValueError):
            normalize_rect(empty)          # zero / negative area is impossible ink


def test_transform_rect_identity_is_noop():
    assert transform_rect([10, 20, 30, 40], IDENTITY_MATRIX) == [10, 20, 30, 40]


def test_normalize_rect_require_area_false_keeps_zero_area_position():
    # A zero-area rect is a valid POSITION when require_area=False (a degenerate
    # word's bbox), but still rejected when it must become ink.
    assert normalize_rect([5, 5, 5, 20], require_area=False) == [5, 5, 5, 20]
    with pytest.raises(ValueError):
        normalize_rect([5, 5, 5, 20])
    # Non-finite is rejected regardless of require_area.
    with pytest.raises(ValueError):
        normalize_rect([0, 0, float("nan"), 10], require_area=False)


def test_transform_rect_zero_area_word_transforms_into_space():
    # A zero-height word rotated 90° must land in view space (not raise / not stay
    # in page space) — the degenerate-word path _words_to_view relies on.
    m = (0, 1, -1, 0, 792, 0)                       # a 90° rotation matrix
    # A zero-HEIGHT word in page space becomes a zero-WIDTH line in view space
    # (rotation swaps axes) — still a valid transformed position, no raise.
    got = transform_rect([100, 100, 140, 100], m, require_area=False)
    assert got == pytest.approx([692.0, 100.0, 692.0, 140.0])


def test_transform_rect_matches_pymupdf_rect_times_matrix():
    # The pure transform must equal PyMuPDF's own Rect*Matrix for the rotation
    # matrices we use — this is the contract the whole phase leans on.
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.set_rotation(90)
    m = tuple(page.rotation_matrix)
    rect = [60.0, 88.0, 120.0, 116.0]
    expect = pymupdf.Rect(*rect) * page.rotation_matrix
    expect.normalize()
    got = transform_rect(rect, m)
    doc.close()
    assert got == pytest.approx([expect.x0, expect.y0, expect.x1, expect.y1], abs=1e-6)


def test_transform_rect_90_then_derotate_is_involution():
    # rotation then derotation must return the original rect (they are inverses).
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.set_rotation(270)
    rect = [40.0, 700.0, 90.0, 740.0]
    view = transform_rect(rect, tuple(page.rotation_matrix))
    back = transform_rect(view, tuple(page.derotation_matrix))
    doc.close()
    assert back == pytest.approx(rect, abs=1e-6)


def test_is_identity_matrix():
    assert is_identity_matrix(IDENTITY_MATRIX)
    assert is_identity_matrix((1, 0, 0, 1, 0, 0))
    assert not is_identity_matrix((0, 1, -1, 0, 792, 0))
    assert not is_identity_matrix((1, 0, 0, 1))          # wrong arity


def test_page_geometry_roundtrip_and_transforms():
    geom = PageGeometry(
        coordinate_space=COORDINATE_SPACE_VERSION,
        view_width_pt=792.0, view_height_pt=612.0,
        media_box=[0, 0, 612, 792], crop_box=[0, 0, 612, 792], rotation=90,
        page_to_view=[0, 1, -1, 0, 792, 0], view_to_page=[0, -1, 1, 0, 0, 792],
    )
    d = geom.to_dict()
    back = PageGeometry.from_dict(d)
    assert back == geom
    # to_view then to_page is a round trip.
    rect = [100.0, 100.0, 140.0, 130.0]
    assert back.to_page(back.to_view(rect)) == pytest.approx(rect, abs=1e-6)


def test_page_geometry_default_is_identity():
    geom = PageGeometry()
    assert geom.has_identity_transform
    assert geom.to_view([10, 20, 30, 40]) == [10, 20, 30, 40]
    assert geom.to_page([10, 20, 30, 40]) == [10, 20, 30, 40]


# --------------------------------------------------------------------------- #
# Characterization: lock the actual PyMuPDF coordinate behavior (min fixture)
# --------------------------------------------------------------------------- #


def _corner_doc(pymupdf, rot):
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 60), "TL", fontsize=20)
    page.insert_text((500, 60), "TR", fontsize=20)
    page.insert_text((60, 740), "BL", fontsize=20)
    page.insert_text((500, 740), "BR", fontsize=20)
    page.set_rotation(rot)
    return doc, page


def test_characterize_get_text_is_rotation_invariant():
    # get_text('words') reports un-rotated, CropBox-relative coordinates — the
    # SAME rects at every rotation. This asymmetry vs get_pixmap is why PAGE_VIEW_V2
    # exists; if a PyMuPDF upgrade changes it, this test fails and the phase's
    # premise must be re-checked.
    pymupdf = pytest.importorskip("pymupdf")
    baseline = None
    for rot in ROTATIONS:
        doc, page = _corner_doc(pymupdf, rot)
        rects = {w[4]: tuple(round(v, 2) for v in w[:4]) for w in page.get_text("words")}
        doc.close()
        if baseline is None:
            baseline = rects
        assert rects == baseline


def test_characterize_pixmap_clip_uses_view_space_not_gettext():
    # A raw get_text rect clips the WRONG region on a rotated page (the bug); the
    # SAME rect transformed by rotation_matrix clips the visible word (the fix).
    pymupdf = pytest.importorskip("pymupdf")
    for rot in (90, 180, 270):
        doc, page = _corner_doc(pymupdf, rot)
        for w in page.get_text("words"):
            raw = (w[0], w[1], w[2], w[3])
            view = transform_rect(raw, tuple(page.rotation_matrix))
            raw_ink = page.get_pixmap(clip=pymupdf.Rect(*raw)).color_topusage()[0] < 0.999
            view_ink = page.get_pixmap(clip=pymupdf.Rect(*view) & page.rect).color_topusage()[0] < 0.999
            assert view_ink, f"view-space clip must contain ink (rot={rot}, {w[4]})"
        # At least one corner's raw clip is blank on a rotated page (proves the bug).
        blanks = [
            page.get_pixmap(clip=pymupdf.Rect(w[0], w[1], w[2], w[3])).color_topusage()[0] >= 0.999
            for w in page.get_text("words")
        ]
        doc.close()
        assert any(blanks), f"raw get_text clip should be blank somewhere at rot={rot}"


def test_characterize_annot_uses_page_space():
    # add_rect_annot() places ink in un-rotated (get_text) space: an annot at a
    # word's get_text rect overlaps that word's rendered ink at every rotation.
    pymupdf = pytest.importorskip("pymupdf")
    for rot in ROTATIONS:
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((100, 100), "WORD", fontsize=20)
        page.set_rotation(rot)
        w = page.get_text("words")[0]
        word_px = _ink_bbox(page.get_pixmap(), _is_dark)
        annot = page.add_rect_annot(pymupdf.Rect(w[0], w[1], w[2], w[3]))
        annot.set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
        annot.update()
        red_px = _ink_bbox(page.get_pixmap(), _is_red)
        doc.close()
        assert _overlaps(word_px, red_px), f"annot must overlap word at rot={rot}"


# --------------------------------------------------------------------------- #
# End-to-end round trip: render -> anchor -> verify-crop -> annotate
# --------------------------------------------------------------------------- #


def _is_dark(r, g, b):
    return r < 100 and g < 100 and b < 100


def _is_red(r, g, b):
    return r > 150 and g < 90 and b < 90


def _ink_bbox(pix, pred):
    xs, ys = [], []
    n, s = pix.n, pix.samples
    for py in range(pix.height):
        for px in range(pix.width):
            o = (py * pix.width + px) * n
            if pred(s[o], s[o + 1], s[o + 2]):
                xs.append(px)
                ys.append(py)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _overlaps(a, b):
    if not a or not b:
        return False
    ox = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    oy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ox > 0 and oy > 0


def _png_has_ink(pymupdf, png_bytes):
    d = pymupdf.open(stream=png_bytes, filetype="png")
    try:
        frac = d[0].get_pixmap().color_topusage()[0]
    finally:
        d.close()
    return frac < 0.999


def _one_word_doc(pymupdf, tmp_path, rot, word="ZQXJ", at=(60, 740), name="M.pdf"):
    """A page with a single distinctive word near the un-rotated bottom-left."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(at, word, fontsize=22)
    page.set_rotation(rot)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _ref(pymupdf, path):
    from drawing_analyzer.models import SheetRef

    doc = pymupdf.open(str(path))
    n = doc.page_count
    doc.close()
    return SheetRef(pdf_path=path, page_index=0, source_name=path.name, page_count=n)


@pytest.mark.parametrize("rot", ROTATIONS)
def test_render_stores_view_space_geometry(rot, tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import render_sheet

    path = _one_word_doc(pymupdf, tmp_path, rot)
    doc = pymupdf.open(str(path))
    try:
        rs = render_sheet(doc[0], _ref(pymupdf, path), rows=2, cols=2)
    finally:
        doc.close()

    assert rs.geometry is not None
    assert rs.geometry.coordinate_space == COORDINATE_SPACE_VERSION
    assert rs.geometry.rotation == rot
    # page dims are the view (post-rotation) dims.
    if rot in (90, 270):
        assert (rs.page_width_pt, rs.page_height_pt) == pytest.approx((792.0, 612.0))
    else:
        assert (rs.page_width_pt, rs.page_height_pt) == pytest.approx((612.0, 792.0))
    # Every stored word rect is inside the view frame (it was transformed there).
    for w in rs.words:
        assert 0 <= w[0] < w[2] <= rs.page_width_pt + 1
        assert 0 <= w[1] < w[3] <= rs.page_height_pt + 1


@pytest.mark.parametrize("rot", ROTATIONS)
def test_anchor_in_view_bounds_and_crop_contains_word(rot, tmp_path):
    """Test 1 + 3: exact-quote anchor is normalized & in view bounds, and the
    verification crop rendered from it actually contains the word — at every
    rotation. Both fail on the baseline (get_text-space anchor) for rotated pages.
    """
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.anchor import resolve_anchors
    from drawing_analyzer.render import render_sheet, render_region

    path = _one_word_doc(pymupdf, tmp_path, rot)
    doc = pymupdf.open(str(path))
    try:
        rs = render_sheet(doc[0], _ref(pymupdf, path), rows=2, cols=2)
    finally:
        doc.close()

    f = Finding(sheet_id="M-101", source_name="M.pdf", page_index=0,
                category="code", severity="high", text="t", source_quote="ZQXJ")
    resolve_anchors([f], rs)

    assert f.anchor.status == "EXACT"
    x0, y0, x1, y1 = f.anchor.rect_pdf
    # normalized (Test 11) and inside the VIEW frame (Test 1)
    assert x0 < x1 and y0 < y1
    assert 0 <= x0 and x1 <= rs.page_width_pt + 1
    assert 0 <= y0 and y1 <= rs.page_height_pt + 1

    # Test 3: the crop the verifier would send contains the word's ink.
    doc = pymupdf.open(str(path))
    try:
        png, _w, _h = render_region(doc[0], f.anchor.rect_pdf, dpi=200)
    finally:
        doc.close()
    assert _png_has_ink(pymupdf, png), f"verify crop must contain the word at rot={rot}"


@pytest.mark.parametrize("rot", ROTATIONS)
def test_annotation_lands_on_word_after_reopen(rot, tmp_path):
    """Test 2: the reviewed PDF's cloud overlaps the word's rendered ink at every
    rotation, and reopening finds exactly the analyzer's annotations."""
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.anchor import resolve_anchors
    from drawing_analyzer.annotate import annotate_pdf, count_annotations_by_type
    from drawing_analyzer.models import Verification
    from drawing_analyzer.render import render_sheet

    path = _one_word_doc(pymupdf, tmp_path, rot)
    doc = pymupdf.open(str(path))
    try:
        rs = render_sheet(doc[0], _ref(pymupdf, path), rows=2, cols=2)
    finally:
        doc.close()

    f = Finding(sheet_id="M-101", source_name="M.pdf", page_index=0,
                category="code", severity="high", text="t", source_quote="ZQXJ")
    resolve_anchors([f], rs)
    f.verification = Verification(status="VERIFIED", note="ok")
    f.qc_id = "QC-001"

    out = tmp_path / "M_reviewed.pdf"
    annotate_pdf(path, [f], out, include_unverified=False, index_pages=False)

    # The cloud (Square) is present after reopening.
    by_type = count_annotations_by_type(out)
    assert by_type.get("Square", 0) == 1

    # Render the reviewed page (skip the inserted index — there is none here) and
    # assert the red cloud outline overlaps the black word ink.
    doc = pymupdf.open(str(out))
    try:
        page = doc[0]
        word_px = _ink_bbox(page.get_pixmap(), _is_dark)
        red_px = _ink_bbox(page.get_pixmap(), lambda r, g, b: r > 150 and g < 90 and b < 90)
    finally:
        doc.close()
    assert _overlaps(word_px, red_px), f"cloud must overlap the word at rot={rot}"


@pytest.mark.parametrize("rot", (0, 90))
def test_cropbox_nonzero_origin_anchor_and_crop(rot, tmp_path):
    """Test 4: a non-default CropBox (non-zero origin, smaller than MediaBox)
    anchors in view bounds and the crop contains the word."""
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.anchor import resolve_anchors
    from drawing_analyzer.render import render_sheet, render_region

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((160, 260), "CROPWORD", fontsize=20)   # inside the cropbox
    page.set_cropbox(pymupdf.Rect(100, 150, 500, 650))       # 400 x 500
    page.set_rotation(rot)
    path = tmp_path / "C.pdf"
    doc.save(str(path))
    doc.close()

    doc = pymupdf.open(str(path))
    try:
        rs = render_sheet(doc[0], _ref(pymupdf, path), rows=2, cols=2)
    finally:
        doc.close()

    # View dims are the (rotated) CropBox size, not the MediaBox size.
    if rot in (90, 270):
        assert (rs.page_width_pt, rs.page_height_pt) == pytest.approx((500.0, 400.0))
    else:
        assert (rs.page_width_pt, rs.page_height_pt) == pytest.approx((400.0, 500.0))

    f = Finding(sheet_id="M-101", source_name="C.pdf", page_index=0,
                category="code", severity="high", text="t", source_quote="CROPWORD")
    resolve_anchors([f], rs)
    assert f.anchor.status == "EXACT"
    x0, y0, x1, y1 = f.anchor.rect_pdf
    assert 0 <= x0 < x1 <= rs.page_width_pt + 1
    assert 0 <= y0 < y1 <= rs.page_height_pt + 1

    doc = pymupdf.open(str(path))
    try:
        png, _w, _h = render_region(doc[0], f.anchor.rect_pdf, dpi=200)
    finally:
        doc.close()
    assert _png_has_ink(pymupdf, png)


@pytest.mark.parametrize("rot", (90, 270))
def test_degenerate_word_stays_in_view_space(rot):
    """A zero-area word on a rotated page must be transformed into view space, not
    kept verbatim in page space (which would mix coordinate spaces in the anchor
    union). Regression for the adversarial-review finding on _words_to_view."""
    from drawing_analyzer.models import PageGeometry
    from drawing_analyzer.render import _words_to_view

    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.set_rotation(rot)
    geom = PageGeometry(
        view_width_pt=float(page.rect.width), view_height_pt=float(page.rect.height),
        rotation=rot,
        page_to_view=[float(v) for v in page.rotation_matrix],
        view_to_page=[float(v) for v in page.derotation_matrix],
    )
    doc.close()

    # A normal word and a degenerate (zero-height) word at the same x.
    words = [
        (100.0, 100.0, 140.0, 120.0, "NORMAL", 0, 0, 0),
        (100.0, 200.0, 140.0, 200.0, "FLAT", 0, 0, 1),   # zero height
    ]
    out = _words_to_view(words, geom)
    assert len(out) == 2                                # neither dropped
    expect_flat = transform_rect((100.0, 200.0, 140.0, 200.0),
                                 geom.page_to_view, require_area=False)
    assert list(out[1][:4]) == pytest.approx(expect_flat, abs=1e-6)
    assert out[1][4] == "FLAT"                          # tail preserved


@pytest.mark.parametrize("rot", ROTATIONS)
def test_margin_callout_and_leader_on_rotated_page(rot, tmp_path):
    """A rect-less (sheet-level) finding's margin callout + leader line are written
    and land fully on the page at every rotation (FreeText + Line view→page
    transform). On the baseline the callout box/leader are placed with view-dims
    layout but un-transformed, drifting off a rotated page."""
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.annotate import annotate_pdf, count_annotations_by_type
    from drawing_analyzer.models import Verification
    from drawing_analyzer.render import render_sheet

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 400), "M-101 NORTH ELEVATION", fontsize=14)
    page.set_rotation(rot)
    path = tmp_path / "S.pdf"
    doc.save(str(path))
    doc.close()

    doc = pymupdf.open(str(path))
    try:
        rs = render_sheet(doc[0], _ref(pymupdf, path), rows=2, cols=2)
    finally:
        doc.close()

    f = Finding(sheet_id="M-101", source_name="S.pdf", page_index=0,
                category="coordination", severity="medium",
                text="Detail 5 referenced but not provided", source_quote="",
                anchor_hint="SHEET", tile=[0, 0])
    f.verification = Verification(status="DETERMINISTIC")
    f.qc_id = "QC-001"
    meta = {0: {"words": rs.words, "rows": rs.rows, "cols": rs.cols,
                "overlap_frac": rs.overlap_frac,
                "page_width_pt": rs.page_width_pt, "page_height_pt": rs.page_height_pt}}
    out = tmp_path / "S_reviewed.pdf"
    written = annotate_pdf(path, [f], out, include_unverified=True,
                           sheet_meta=meta, index_pages=False).annots_written
    assert written >= 1
    by = count_annotations_by_type(out)
    assert by.get("FreeText", 0) == 1        # the callout box
    # Every analyzer annotation lies within the page rectangle (nothing off-page).
    doc = pymupdf.open(str(out))
    try:
        pg = doc[0]
        for a in pg.annots():
            assert (a.rect & pg.rect).get_area() > 0, f"annot off-page at rot={rot}"
    finally:
        doc.close()


@pytest.mark.parametrize("rot", (90, 270))
def test_tile_disambiguation_uses_view_space(rot, tmp_path):
    """Test 5: a duplicated quote is disambiguated to the occurrence in the
    model-reported tile, using the view-space word positions the model saw. On the
    baseline (get_text-space words vs a view-dims grid) the wrong occurrence is
    chosen on a rotated page."""
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.anchor import _base_cell, resolve_anchors
    from drawing_analyzer.render import render_sheet

    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((60, 80), "DUP", fontsize=20)      # one corner (un-rotated)
    page.insert_text((520, 720), "DUP", fontsize=20)    # opposite corner
    page.set_rotation(rot)
    path = tmp_path / "D.pdf"
    doc.save(str(path))
    doc.close()

    doc = pymupdf.open(str(path))
    try:
        rs = render_sheet(doc[0], _ref(pymupdf, path), rows=2, cols=2)
    finally:
        doc.close()

    dups = [w for w in rs.words if w[4] == "DUP"]
    assert len(dups) == 2
    # Pick the SECOND occurrence's view-space cell as the model-reported tile.
    target = dups[1]
    cx = (target[0] + target[2]) / 2.0
    cy = (target[1] + target[3]) / 2.0
    tile = _base_cell(cx, cy, rs.page_width_pt, rs.page_height_pt, rs.rows, rs.cols)

    f = Finding(sheet_id="M-101", source_name="D.pdf", page_index=0,
                category="code", severity="high", text="t",
                source_quote="DUP", tile=list(tile))
    resolve_anchors([f], rs)
    assert f.anchor.rect_pdf is not None
    axc = (f.anchor.rect_pdf[0] + f.anchor.rect_pdf[2]) / 2.0
    ayc = (f.anchor.rect_pdf[1] + f.anchor.rect_pdf[3]) / 2.0
    # It anchored to the targeted occurrence (its center is near that word).
    assert math.hypot(axc - cx, ayc - cy) < 40.0


# --------------------------------------------------------------------------- #
# GOTO destinations are default user space, not annotation space (P7 item 27)
#
# A ``/XYZ`` destination is expressed in default user space (PDF 32000-1
# §12.3.2.2) and so is an annotation's ``/Rect`` (§12.5.2) — which is what makes
# the annotation the ground truth here: stamp a rect annot at the point the
# annotation path already places correctly (locked by
# ``test_annotation_lands_on_word_after_reopen``), save, read the raw ``/Rect``
# back, and the destination must name the same user-space point.
#
# The matrix is rotation × CropBox × MediaBox-origin, because the shipped bug
# hid in exactly the corners a smaller matrix misses: a rotated page is wrong
# whenever the CropBox *or* the MediaBox has a non-zero origin.
# --------------------------------------------------------------------------- #

_DEST_CROPS = (None, (50, 30, 50, 92), (0, 0, 0, 0))   # inset (l, t, r, b) from MediaBox
_DEST_MEDIA_ORIGINS = ((0, 0), (20, 15))
_DEST_VIEW_PT = (100.0, 120.0)


def _dest_doc(pymupdf, rot, crop, media_origin):
    """A 2-page doc whose page 1 carries ``rot`` / ``crop`` / ``media_origin``."""
    doc = pymupdf.open()
    doc.new_page(width=612, height=792)              # page 0 — the link source
    pg = doc.new_page(width=612, height=792)
    if media_origin != (0, 0):
        x, y = media_origin
        doc.xref_set_key(pg.xref, "MediaBox", f"[{x} {y} {x + 612} {y + 792}]")
        doc = pymupdf.open("pdf", doc.tobytes())
    page = doc[1]
    if crop is not None:
        # set_cropbox takes x in absolute user x, y measured DOWN from mediabox.y1
        mb = page.mediabox
        page.set_cropbox(pymupdf.Rect(mb.x0 + crop[0], crop[1],
                                      mb.x1 - crop[2], (mb.y1 - mb.y0) - crop[3]))
    if rot:
        page.set_rotation(rot)
    return doc, page


def _raw_xyz(pymupdf, doc):
    """The last ``/XYZ x y`` written into the saved file, in default user space."""
    import re
    blob = doc.tobytes(garbage=0, deflate=False, expand=255)
    found = re.findall(rb"/XYZ\s+([\d.\-]+)\s+([\d.\-]+)", blob)
    assert found, "no /XYZ destination was written"
    return tuple(round(float(v), 1) for v in found[-1])


def _annot_truth(pymupdf, rot, crop, media_origin):
    """Ground truth: the user-space top-left of a rect annot at the same point."""
    import re
    from drawing_analyzer.annotate import _derotate_point
    doc, page = _dest_doc(pymupdf, rot, crop, media_origin)
    p = _derotate_point(page, *_DEST_VIEW_PT)
    annot = page.add_rect_annot(pymupdf.Rect(p.x, p.y, p.x + 4, p.y + 4))
    annot.update()
    blob = doc.tobytes(garbage=0, deflate=False, expand=255)
    m = re.search(rb"/Rect\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)", blob)
    doc.close()
    assert m
    g = [float(v) for v in m.groups()]
    # add_rect_annot inflates by the 1pt border; undo it to recover the corner.
    return (round(g[0] + 1, 1), round(g[3] - 1, 1))


def _dest_cases():
    return [(rot, crop, origin)
            for rot in ROTATIONS
            for crop in _DEST_CROPS
            for origin in _DEST_MEDIA_ORIGINS]


def test_characterize_rotation_and_derotation_matrices_are_exact_inverses():
    # _outline_dest_point inverts set_toc's `* rotation_matrix` with
    # derotation_matrix. That is only valid if the two are true inverses — and
    # they are bit-exact, not merely close, at every rotation/CropBox.
    pymupdf = pytest.importorskip("pymupdf")
    for rot, crop, origin in _dest_cases():
        doc, page = _dest_doc(pymupdf, rot, crop, origin)
        product = tuple(page.rotation_matrix * page.derotation_matrix)
        doc.close()
        assert product == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), (
            f"rotation/derotation are not exact inverses at rot={rot} "
            f"crop={crop} origin={origin}: {product}"
        )


def test_dest_point_matches_user_space_truth_for_insert_link():
    # The index-page / overflow-page GOTO route (Page.insert_link).
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.annotate import _dest_point
    for rot, crop, origin in _dest_cases():
        truth = _annot_truth(pymupdf, rot, crop, origin)
        doc, page = _dest_doc(pymupdf, rot, crop, origin)
        doc[0].insert_link({
            "kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 100, 30),
            "page": 1, "to": _dest_point(page, *_DEST_VIEW_PT), "zoom": 0,
        })
        got = _raw_xyz(pymupdf, doc)
        doc.close()
        assert abs(got[0] - truth[0]) < 1.2 and abs(got[1] - truth[1]) < 1.2, (
            f"insert_link /XYZ {got} != user-space truth {truth} at rot={rot} "
            f"crop={crop} origin={origin}"
        )


def test_outline_dest_point_matches_user_space_truth_for_set_toc():
    # The bookmark-outline route (Document.set_toc) — a DIFFERENT internal
    # transform from insert_link's, so it needs its own inversion and its own
    # test. Sharing one helper between the two is the shipped bug.
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.annotate import _outline_dest_point
    for rot, crop, origin in _dest_cases():
        truth = _annot_truth(pymupdf, rot, crop, origin)
        doc, page = _dest_doc(pymupdf, rot, crop, origin)
        doc.set_toc([[1, "top", 1],
                     [2, "mark", 2, {"kind": pymupdf.LINK_GOTO,
                                     "to": _outline_dest_point(page, *_DEST_VIEW_PT),
                                     "zoom": 1.5}]])
        got = _raw_xyz(pymupdf, doc)
        doc.close()
        assert abs(got[0] - truth[0]) < 1.2 and abs(got[1] - truth[1]) < 1.2, (
            f"set_toc /XYZ {got} != user-space truth {truth} at rot={rot} "
            f"crop={crop} origin={origin}"
        )


def test_annotation_space_point_is_not_a_destination_point():
    # The mechanism guard: _derotate_point (annotation space) and the two
    # destination helpers must genuinely disagree on a rotated, cropped page.
    # Without this, a revert to _derotate_point could pass the tests above on a
    # matrix that happened to exclude the failing corners.
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.annotate import (
        _derotate_point, _dest_point, _outline_dest_point,
    )
    doc, page = _dest_doc(pymupdf, 90, (50, 30, 50, 92), (20, 15))
    try:
        annot_pt = _derotate_point(page, *_DEST_VIEW_PT)
        link_pt = _dest_point(page, *_DEST_VIEW_PT)
        toc_pt = _outline_dest_point(page, *_DEST_VIEW_PT)
    finally:
        doc.close()
    assert (round(link_pt.x, 1), round(link_pt.y, 1)) != (round(annot_pt.x, 1), round(annot_pt.y, 1))
    assert (round(toc_pt.x, 1), round(toc_pt.y, 1)) != (round(annot_pt.x, 1), round(annot_pt.y, 1))
    # …and the two destination spaces are not each other either.
    assert (round(link_pt.x, 1), round(link_pt.y, 1)) != (round(toc_pt.x, 1), round(toc_pt.y, 1))
