"""Level-1 cache identity and schema migration (DA-004, §11.5).

The render identity conservatively hashes the transitive PDF dependencies that
can affect one page's pixels, plus render configuration and environment. A local
page edit rekeys that page while preserving unchanged siblings; any ambiguity
falls back to the whole-source hash, so stale hits remain impossible. The same
identity supports digest and critique pre-render cache hits.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from drawing_analyzer.digest_cache import (
    DigestCache,
    _SCHEMA_VERSION,
    critique_cache_key_level1,
    digest_cache_key_level1,
)
from drawing_analyzer.models import COORDINATE_SPACE_VERSION, SheetRef

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
# Schema migration: a pre-v5 cache entry is discarded on load
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
