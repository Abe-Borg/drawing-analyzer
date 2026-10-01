"""Cache identity follows rendered page content, configuration and schema.

Page-local changes preserve unaffected siblings; changed critique contracts
miss at both cache levels without invalidating unrelated paid stages.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from drawing_analyzer.digest_cache import (
    DigestCache,
    _SCHEMA_VERSION,
    critique_cache_key_level1,
    digest_cache_key_level1,
)
from drawing_analyzer.models import (
    COORDINATE_SPACE_VERSION, ImageTile, RenderedSheet, SheetGeometry, SheetRef,
)

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer.render import (  # noqa: E402
    _renderer_environment_fingerprint,
    sheet_render_identity,
)
from drawing_analyzer.source_registry import content_sha256  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers — build a PDF file and compute its page render identity
# --------------------------------------------------------------------------- #


def _base_doc():
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((80, 120), "SHEET M-101 RELIEF VALVE RV-3", fontsize=14)
    return doc


def _identity(path: Path, *, page_index: int = 0, rows: int = 2, cols: int = 2) -> str:
    """The full level-1 render identity for a page of ``path`` (as the prescan builds it)."""
    sha, _size, _mtime = content_sha256(path)
    doc = pymupdf.open(str(path))
    try:
        count = doc.page_count
        return sheet_render_identity(
            doc[page_index], content_sha256=sha, page_index=page_index,
            page_count=count, rows=rows, cols=cols,
        )
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# DA-004: page dependencies catch rotation / CropBox / annotations
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rot", (90, 180, 270))
def test_rotation_change_rekeys(tmp_path, rot):
    # 180° is the case the old per-page fingerprint MISSED: it hashed content
    # streams + page.rect dims, and a 180° rotation changes neither (dims are the
    # same, /Rotate is a page-dict attribute, not a content stream). The whole-file
    # dependency hash catches every rotation.
    d0 = _base_doc()
    a = tmp_path / "a.pdf"
    d0.save(str(a))
    d0.close()
    d1 = _base_doc()
    d1[0].set_rotation(rot)
    b = tmp_path / f"b{rot}.pdf"
    d1.save(str(b))
    d1.close()
    assert _identity(a) != _identity(b)


def test_cropbox_offset_change_rekeys_even_at_same_size(tmp_path):
    # Two CropBoxes with the SAME width/height but a different ORIGIN — the old
    # fingerprint (which hashed only page.rect *dimensions*) would MISS this; the
    # page dependency hash catches it because the CropBox differs.
    d0 = _base_doc()
    d0[0].set_cropbox(pymupdf.Rect(0, 0, 400, 500))
    a = tmp_path / "a.pdf"
    d0.save(str(a))
    d0.close()
    d1 = _base_doc()
    d1[0].set_cropbox(pymupdf.Rect(100, 150, 500, 650))    # same 400x500, offset
    b = tmp_path / "b.pdf"
    d1.save(str(b))
    d1.close()
    assert _identity(a) != _identity(b)


def test_adding_a_rendered_annotation_rekeys(tmp_path):
    d0 = _base_doc()
    a = tmp_path / "a.pdf"
    d0.save(str(a))
    d0.close()
    d1 = _base_doc()
    annot = d1[0].add_rect_annot(pymupdf.Rect(80, 100, 260, 140))
    annot.update()
    b = tmp_path / "b.pdf"
    d1.save(str(b))
    d1.close()
    assert _identity(a) != _identity(b)          # annotations render into the image


def test_annotation_appearance_change_rekeys(tmp_path):
    # Same annotation text/rect, DIFFERENT appearance (color) — the appearance
    # appearance-stream bytes differ, so the page dependency hash differs.
    def _with_color(color):
        d = _base_doc()
        an = d[0].add_rect_annot(pymupdf.Rect(80, 100, 260, 140))
        an.set_colors(stroke=color)
        an.update()
        return d

    d1 = _with_color((1, 0, 0))
    d2 = _with_color((0, 0, 1))
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    d1.save(str(a))
    d1.close()
    d2.save(str(b))
    d2.close()
    assert _identity(a) != _identity(b)


def test_drawing_content_change_rekeys(tmp_path):
    d0 = _base_doc()
    a = tmp_path / "a.pdf"
    d0.save(str(a))
    d0.close()
    d1 = pymupdf.open()
    p = d1.new_page(width=612, height=792)
    p.insert_text((80, 120), "SHEET M-102 DIFFERENT CONTENT", fontsize=14)
    b = tmp_path / "b.pdf"
    d1.save(str(b))
    d1.close()
    assert _identity(a) != _identity(b)


def test_identical_bytes_same_identity_regardless_of_mtime(tmp_path):
    # The identity is content-only: a byte-identical copy (and a touched mtime)
    # produce the SAME identity — an irrelevant timestamp never re-keys (§11 test 9).
    # (A byte copy, not a re-save: PyMuPDF stamps non-deterministic metadata each
    # save, which — correctly — the content hash would treat as a real change.)
    import shutil

    d = _base_doc()
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    d.save(str(a))
    d.close()
    shutil.copyfile(a, b)
    id_a = _identity(a)
    # Bump a's mtime far into the past; the content hash — and identity — is unchanged.
    os.utime(a, (1_000_000, 1_000_000))
    assert _identity(a) == id_a
    assert _identity(a) == _identity(b)


def test_renderer_environment_folded_in(tmp_path):
    # A cache moved between installations with a different renderer must miss: the
    # platform + PyMuPDF/MuPDF build is part of the identity (§11 test 14).
    import platform

    d = _base_doc()
    a = tmp_path / "a.pdf"
    d.save(str(a))
    d.close()
    ident = _identity(a)
    env = _renderer_environment_fingerprint()
    assert platform.system() in env
    assert pymupdf.__version__ in env
    assert env in ident
    assert COORDINATE_SPACE_VERSION in ident


def test_page_index_and_count_distinguish_pages(tmp_path):
    d = _base_doc()
    d.new_page(width=612, height=792).insert_text((80, 120), "SHEET M-102", fontsize=14)
    a = tmp_path / "a.pdf"
    d.save(str(a))
    d.close()
    assert _identity(a, page_index=0) != _identity(a, page_index=1)


def test_editing_one_page_preserves_unchanged_sibling_identity(tmp_path):
    """The transitive page graph localizes an incremental multi-page revision."""
    doc = pymupdf.open()
    doc.new_page(width=612, height=792).insert_text((80, 120), "SHEET A-101", fontsize=14)
    doc.new_page(width=612, height=792).insert_text((80, 120), "SHEET A-102", fontsize=14)
    path = tmp_path / "set.pdf"
    doc.save(str(path))
    doc.close()

    before = [_identity(path, page_index=i) for i in range(2)]
    doc = pymupdf.open(str(path))
    doc[1].insert_text((80, 160), "REVISION ON SECOND SHEET ONLY", fontsize=12)
    doc.saveIncr()
    doc.close()
    after = [_identity(path, page_index=i) for i in range(2)]

    assert after[0] == before[0]
    assert after[1] != before[1]


def test_annotation_change_invalidates_only_its_page(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=612, height=792).insert_text((80, 120), "SHEET M-101", fontsize=14)
    doc.new_page(width=612, height=792).insert_text((80, 120), "SHEET M-102", fontsize=14)
    path = tmp_path / "set.pdf"
    doc.save(str(path))
    doc.close()
    before = [_identity(path, page_index=i) for i in range(2)]

    doc = pymupdf.open(str(path))
    annot = doc[0].add_rect_annot(pymupdf.Rect(70, 90, 240, 145))
    annot.update()
    doc.saveIncr()
    doc.close()
    after = [_identity(path, page_index=i) for i in range(2)]

    assert after[0] != before[0]
    assert after[1] == before[1]


def test_unhashable_sources_do_not_collide(tmp_path, monkeypatch):
    # If the content genuinely can't be hashed, two DIFFERENT (but geometry-identical)
    # sources must not share a level-1 identity — a stale sentinel would otherwise
    # serve one file's digest for another. The prescan falls back to the source's
    # canonical path so the identities stay distinct. (Unreachable via the pipeline,
    # which only prescans accepted sources that always carry a real hash — this
    # guards direct/future callers of iter_sheet_prescan.)
    import shutil

    import drawing_analyzer.render as render_mod

    # Two byte-identical, geometry-identical, openable PDFs at different paths.
    d = _base_doc()
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    d.save(str(a))
    d.close()
    shutil.copyfile(a, b)

    # The prescan asks source_registry.current_content_sha256 for the on-disk hash;
    # simulate an unhashable (mid-rewrite) source so the canonical-path fallback fires.
    monkeypatch.setattr(render_mod, "current_content_sha256", lambda *_a, **_k: "")

    ids = {
        ref.pdf_path.name: identity
        for ref, identity, _geom in render_mod.iter_sheet_prescan([a, b], rows=2, cols=2)
    }
    assert ids["a.pdf"] != ids["b.pdf"]        # no cross-source collision
    assert "unhashed:" in ids["a.pdf"]


def test_prescan_rehashes_a_source_changed_since_the_snapshot(tmp_path):
    # DA-004 §10.6 / Codex P1: a source rewritten AFTER the inventory captured its
    # hash but BEFORE the prescan must key on its CURRENT revision, not the stale
    # snapshot — otherwise a level-1 hit serves the previous revision's digest with
    # no render. The prescan stat-gates the snapshot and re-hashes on drift.
    from drawing_analyzer.render import iter_sheet_prescan

    d0 = _base_doc()
    a = tmp_path / "a.pdf"
    d0.save(str(a))
    d0.close()
    sha0, size0, mtime0 = content_sha256(a)
    stale_snapshot = {str(a): (sha0, size0, mtime0)}
    id_before = next(iter_sheet_prescan([a], rows=2, cols=2,
                                        snapshot_by_path=stale_snapshot))[1]

    # Rewrite the file in place (new content) — the snapshot is now stale.
    d1 = pymupdf.open()
    d1.new_page(width=612, height=792).insert_text((80, 120), "SHEET M-999 REVISED", fontsize=14)
    d1.save(str(a))
    d1.close()

    # The SAME (now stale) snapshot is passed, exactly as the pipeline would after
    # its inventory. The prescan must detect the stat drift, re-hash, and re-key.
    id_after = next(iter_sheet_prescan([a], rows=2, cols=2,
                                       snapshot_by_path=stale_snapshot))[1]
    assert id_after != id_before                 # re-keyed to the current revision
    assert sha0 not in id_after                  # the stale hash is not reused


# --------------------------------------------------------------------------- #
# Older cache schemas are not served as current results
# --------------------------------------------------------------------------- #


def test_old_schema_entries_are_discarded(tmp_path):
    # A cache file written under an older schema must miss (never be served as
    # current) — the whole point of bumping _SCHEMA_VERSION on a shape change.
    cache_path = tmp_path / "digest_cache.json"
    key = "some-key"
    cache_path.write_text(json.dumps({
        "_schema_version": _SCHEMA_VERSION - 1,
        "entries": {key: {"text": "stale digest", "findings": []}},
    }), encoding="utf-8")
    cache = DigestCache(cache_path, persist=True)
    assert cache.get(key) is None                # discarded on load


def test_level1_keys_fold_schema_version():
    # Both level-1 keys namespace on the schema version, so a bump invalidates them.
    render_identity = "render-identity-v3|content_dependency=page:abc|..."
    d = digest_cache_key_level1(
        render_identity, model="m", prompt_version="p", max_tokens=1,
        effort=None, use_thinking=True,
    )
    c = critique_cache_key_level1(
        render_identity, model="m", prompt_version="p", max_tokens=1,
        effort=None, use_thinking=True, runs=2,
    )
    assert d != c                                # digest vs critique never collide
    # A different render identity yields a different key on both.
    d2 = digest_cache_key_level1(
        render_identity + "X", model="m", prompt_version="p", max_tokens=1,
        effort=None, use_thinking=True,
    )
    assert d != d2


def test_critique_level1_key_sensitive_to_runs_and_profiles():
    ri = "render-identity-v3|content_dependency=page:abc"
    base = dict(model="m", prompt_version="p", max_tokens=1, effort=None, use_thinking=True)
    k1 = critique_cache_key_level1(ri, runs=1, **base)
    k2 = critique_cache_key_level1(ri, runs=2, **base)
    kp = critique_cache_key_level1(ri, runs=2, profiles_key="fp@1@hash", **base)
    assert k1 != k2                              # one-read vs two-read differ
    assert k2 != kp                              # a profile selection re-critiques


# --------------------------------------------------------------------------- #
# A GOTO link must not collapse per-page identity to the whole document (N23)
#
# A link annot carries a reference to its destination PAGE. That page's /Parent
# is not stripped the way the hashed page's own is, so the walk reached the
# page-tree root, /Kids, and every sibling. A set carrying the internal
# navigation hyperlinks an issued PDF normally has therefore lost per-page
# caching entirely: re-exporting one sheet re-rendered and re-digested them all.
# --------------------------------------------------------------------------- #


def _linked_set(path: Path, *, link_to: int | None, tail_text: str) -> Path:
    """A 3-page set; page 0 optionally carries a GOTO link to ``link_to``."""
    doc = pymupdf.open()
    for i in range(3):
        doc.new_page(width=612, height=792).insert_text((72, 100), f"SHEET {i}")
    doc[2].insert_text((72, 300), tail_text)
    if link_to is not None:
        doc[0].insert_link({
            "kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 10, 100, 30),
            "page": link_to, "to": pymupdf.Point(72, 100), "zoom": 0,
        })
    doc.save(str(path))
    doc.close()
    return path


def test_editing_another_page_does_not_rekey_a_linked_page(tmp_path):
    a = _linked_set(tmp_path / "a.pdf", link_to=1, tail_text="ORIGINAL")
    b = _linked_set(tmp_path / "b.pdf", link_to=1, tail_text="EDITED LATER")
    # A page-local dependency hash, not the whole-source fallback — otherwise this
    # test would pass for the wrong reason (every page sharing one identity).
    assert "content_dependency=page:" in _identity(a), (
        "identity fell back to the whole source"
    )
    assert _identity(a) == _identity(b), (
        "page 0's identity changed because page 2 was edited — a GOTO link "
        "collapsed per-page identity to the whole document"
    )


def test_page_without_links_is_still_page_local(tmp_path):
    # The control: this already worked, and must keep working.
    a = _linked_set(tmp_path / "a.pdf", link_to=None, tail_text="ORIGINAL")
    b = _linked_set(tmp_path / "b.pdf", link_to=None, tail_text="EDITED LATER")
    assert _identity(a) == _identity(b)


def test_retargeting_the_link_still_rekeys_the_linking_page(tmp_path):
    # The false-hit guard. Only the destination REFERENCE is hashed, not the
    # destination's content — so retargeting must still move the key, because it
    # rewrites this page's own annot object.
    a = _linked_set(tmp_path / "a.pdf", link_to=1, tail_text="SAME")
    b = _linked_set(tmp_path / "b.pdf", link_to=2, tail_text="SAME")
    assert _identity(a) != _identity(b), (
        "retargeting the link left page 0's identity unchanged — a false hit"
    )


def test_the_edited_page_itself_still_rekeys(tmp_path):
    # The other false-hit guard: treating a page as an opaque leaf must not stop
    # that page's OWN identity from tracking its own content.
    a = _linked_set(tmp_path / "a.pdf", link_to=1, tail_text="ORIGINAL")
    b = _linked_set(tmp_path / "b.pdf", link_to=1, tail_text="EDITED LATER")
    assert _identity(a, page_index=2) != _identity(b, page_index=2)


def test_annotation_content_on_the_page_itself_still_rekeys(tmp_path):
    # Only /Type /Page objects are opaque. Everything else a page references —
    # including its own annotations and their appearance streams — is still
    # hashed, so a prior-review markup on THIS page moves its key.
    plain = _linked_set(tmp_path / "plain.pdf", link_to=1, tail_text="SAME")
    marked = _linked_set(tmp_path / "marked.pdf", link_to=1, tail_text="SAME")
    doc = pymupdf.open(str(marked))
    annot = doc[0].add_freetext_annot(
        pymupdf.Rect(200, 400, 500, 460), "QC-014 PRIOR REVIEW MARKUP", fontsize=9
    )
    annot.update()
    doc.saveIncr()
    doc.close()
    assert _identity(plain) != _identity(marked)


# --------------------------------------------------------------------------- #
# A critique contract change must leave other paid stages reusable.
# --------------------------------------------------------------------------- #

from drawing_analyzer import digest_cache as DC  # noqa: E402

_KEY_SHEET = RenderedSheet(
    ref=SheetRef(Path("M-101.pdf"), 0, "M-101.pdf", 1),
    overview=ImageTile(b"OVERVIEW", 100, 80, "overview"),
    tiles=[ImageTile(b"TILE00", 50, 80, "tile", 0, 0, "left"),
           ImageTile(b"TILE01", 50, 80, "tile", 0, 1, "right")],
    page_width_pt=100, page_height_pt=80, rows=1, cols=2,
)
_KEY_RENDER_IDENTITY = "render-identity-v4|content_dependency=page:abc"
_KEY_REQUEST = dict(
    model="claude-opus-5", prompt_version="p-1", max_tokens=64000,
    effort="high", use_thinking=True,
)
_KEY_SHEET_TEXT = "VAV-3 SERVES ROOM 120"


def _current_keys() -> dict[str, str]:
    """Representative keys for each independently cached stage."""
    return {
        "digest_l2": DC.digest_cache_key(
            _KEY_SHEET, sheet_text=_KEY_SHEET_TEXT, **_KEY_REQUEST),
        "digest_l1": DC.digest_cache_key_level1(_KEY_RENDER_IDENTITY, **_KEY_REQUEST),
        "critique_l2": DC.critique_cache_key(
            _KEY_SHEET, runs=2, sheet_text=_KEY_SHEET_TEXT, **_KEY_REQUEST),
        "critique_l1": DC.critique_cache_key_level1(
            _KEY_RENDER_IDENTITY, runs=2, **_KEY_REQUEST),
        "critique_l2_profiles_structured": DC.critique_cache_key(
            _KEY_SHEET, runs=2, sheet_text=_KEY_SHEET_TEXT, profiles_key="fp@1@h",
            structured_key="s-1", **_KEY_REQUEST),
        "critique_l1_profiles_structured": DC.critique_cache_key_level1(
            _KEY_RENDER_IDENTITY, runs=2, profiles_key="fp@1@h",
            structured_key="s-1", **_KEY_REQUEST),
        "identity": DC.identity_cache_key("corpus-1", **_KEY_REQUEST),
        "review_plan": DC.review_plan_cache_key(
            "corpus-1", "identity-1", max_items=60, **_KEY_REQUEST),
        "citation": DC.citation_cache_key(
            "payload-1", model="claude-sonnet-5", prompt_version="p-1",
            request_shape={"tools": ["web_search"], "max_tokens": 8000}),
        "investigation": DC.investigation_cache_key(
            "payload-1", model="claude-opus-5", prompt_version="p-1",
            max_rounds=6, task_budget=0),
    }


_CRITIQUE_KEYS = (
    "critique_l2", "critique_l1",
    "critique_l2_profiles_structured", "critique_l1_profiles_structured",
)
_OTHER_KEYS = tuple(k for k in _current_keys() if k not in _CRITIQUE_KEYS)


@pytest.mark.parametrize("change", [
    lambda s: replace(s, ref=replace(s.ref, source_name="renamed.pdf")),
    lambda s: replace(s, ref=replace(s.ref, page_count=2)),
    lambda s: replace(s, tiles=[replace(s.tiles[0], label="upper-left"), s.tiles[1]]),
    lambda s: replace(s, tiles=[replace(s.tiles[0], row=1), s.tiles[1]]),
    lambda s: replace(s, cols=3),
    lambda s: replace(s, omitted_tiles=[(0, 2)]),
])
def test_model_visible_labels_rekey_digest_and_critique(change):
    from drawing_analyzer.digest import build_user_content

    changed = change(_KEY_SHEET)
    assert build_user_content(changed) != build_user_content(_KEY_SHEET)
    for builder, extra in ((DC.digest_cache_key, {}), (DC.critique_cache_key, {"runs": 2})):
        key = builder(_KEY_SHEET, **_KEY_REQUEST, **extra)
        assert builder(replace(_KEY_SHEET), **_KEY_REQUEST, **extra) == key
        assert builder(changed, **_KEY_REQUEST, **extra) != key


def test_prerender_keys_include_display_and_generated_tile_labels(monkeypatch):
    from drawing_analyzer import tiling

    geometry = SheetGeometry.from_rendered(_KEY_SHEET)
    labels = DC.prescan_request_labels(geometry)
    renamed = replace(geometry, ref=replace(geometry.ref, source_name="renamed.pdf"))
    renamed_labels = DC.prescan_request_labels(renamed)
    monkeypatch.setattr(tiling, "position_label", lambda *_a: "new placement wording")
    regenerated = DC.prescan_request_labels(geometry)
    for builder, extra in ((DC.digest_cache_key_level1, {}),
                           (DC.critique_cache_key_level1, {"runs": 2})):
        def key(fragment):
            return builder(_KEY_RENDER_IDENTITY, request_labels=fragment, **_KEY_REQUEST, **extra)
        assert key(labels) != key(renamed_labels)
        assert key(labels) != key(regenerated)
        assert key(labels) != key("")


def test_pipeline_prerender_probes_change_when_identical_pdf_is_renamed(tmp_path, monkeypatch):
    import shutil
    from drawing_analyzer import pipeline

    original, renamed = tmp_path / "original.pdf", tmp_path / "renamed.pdf"
    doc = _base_doc()
    doc.save(str(original))
    doc.close()
    shutil.copyfile(original, renamed)
    assert _identity(original) == _identity(renamed)
    cache = DigestCache(None, persist=False)
    seen = []
    monkeypatch.setattr(cache, "get", lambda key: seen.append(key))
    common = dict(rows=2, cols=2, overlap_frac=.08, cache=cache, model="m")
    for partition, extra in (
        (pipeline._level1_partition, dict(max_tokens=100, use_thinking=False,
                                         effort=None, focus=None)),
        (pipeline._critique_level1_partition, dict(runs=1, profiles_key=None)),
    ):
        seen.clear()
        for path in (original, original, renamed):
            partition([path], **common, **extra)
        assert seen[0] == seen[1] != seen[2]


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_prerender_labels_match_rendered_labels_on_cropped_rotated_pages(tmp_path, rotation):
    from drawing_analyzer.render import iter_rendered_sheets, iter_sheet_prescan

    path = tmp_path / "sheet.pdf"
    doc = _base_doc()
    doc[0].set_cropbox(pymupdf.Rect(20, 30, 600, 700))
    doc[0].set_rotation(rotation)
    doc.save(str(path))
    doc.close()
    (_, _, geometry), = iter_sheet_prescan([path], rows=2, cols=2)
    sheet, = iter_rendered_sheets([path], rows=2, cols=2)
    assert sheet.tiles
    display, rows, cols, projected = json.loads(DC.prescan_request_labels(geometry))
    assert (display, rows, cols) == (sheet.ref.display_label, sheet.rows, sheet.cols)
    assert all([tile.row, tile.col, tile.label] in projected for tile in sheet.tiles)


def test_the_critique_contract_rides_both_critique_builders_and_nothing_else(monkeypatch):
    before = _current_keys()
    monkeypatch.setattr(DC, "_CRITIQUE_CACHE_CONTRACT", DC._CRITIQUE_CACHE_CONTRACT + 1)
    after = _current_keys()
    for name in _CRITIQUE_KEYS:
        assert after[name] != before[name], name
    for name in _OTHER_KEYS:
        assert after[name] == before[name], name


def test_changed_critique_entries_miss_without_deleting_paid_results(tmp_path, monkeypatch):
    path = tmp_path / "digest_cache.json"
    before = _current_keys()
    cache = DigestCache(path, persist=True)
    stale = {"findings": [], "claims": [], "runs": 2, "requested_runs": 2,
             "completed_runs": 2, "input_tokens": 1, "output_tokens": 1}
    digest = {"text": "digest", "stop_reason": "end_turn"}
    cache.put(before["critique_l1"], stale)
    cache.put(before["critique_l2"], stale)
    cache.put(before["digest_l1"], digest)
    cache.close()

    monkeypatch.setattr(DC, "_CRITIQUE_CACHE_CONTRACT", DC._CRITIQUE_CACHE_CONTRACT + 1)
    reopened = DigestCache(path, persist=True)
    try:
        after = _current_keys()
        assert reopened.get(after["critique_l1"]) is None
        assert reopened.get(after["critique_l2"]) is None
        assert reopened.get(after["digest_l1"]) == digest
        assert reopened.get(before["critique_l1"]) == stale
        assert reopened.get(before["critique_l2"]) == stale
    finally:
        reopened.close()
