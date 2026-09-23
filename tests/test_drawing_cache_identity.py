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


def test_both_prompt_hashes_cover_every_shared_user_framing_string():
    # The user-turn framing (how a sheet is introduced, how an omitted tile is
    # disclosed, the overview label, the per-tile label) is model-visible text
    # that sat OUTSIDE both prompt hashes. Editing it changed what was sent
    # while every cache key stayed byte-identical, so warm runs replayed reads
    # taken under the old wording.
    #
    # ``build_user_content_blocks`` is SHARED: the critique passes its own
    # closing instruction and reuses this exact framing, so a string covered by
    # only one hash re-keys that cache while silently replaying the other — the
    # failure CRITIQUE_PROMPT_VERSION's own comment already records.
    import hashlib

    from drawing_analyzer import critique as critique_mod
    from drawing_analyzer import digest as digest_mod

    assert digest_mod.SHARED_USER_FRAMING_STRINGS, "shared framing tuple is empty"

    def _digest_hash(strings):
        return hashlib.sha256(
            "\x00".join(
                (
                    digest_mod.DIGEST_SYSTEM_PROMPT,
                    digest_mod._DIGEST_TASK_INSTRUCTION,
                    *strings,
                    digest_mod._FINDINGS_INSTRUCTION,
                )
            ).encode("utf-8")
        ).hexdigest()[:16]

    def _critique_hash(strings):
        return hashlib.sha256(
            "\x00".join(
                (
                    critique_mod.CRITIQUE_SYSTEM_PROMPT,
                    critique_mod._CRITIQUE_TASK_INSTRUCTION,
                    critique_mod._CRITIQUE_FINDINGS_INSTRUCTION,
                    *strings,
                )
            ).encode("utf-8")
        ).hexdigest()[:16]

    shared = list(digest_mod.SHARED_USER_FRAMING_STRINGS)
    assert _digest_hash(shared) == digest_mod.DIGEST_PROMPT_VERSION
    assert _critique_hash(shared) == critique_mod.CRITIQUE_PROMPT_VERSION

    # Editing any one of them must move BOTH versions, never just one.
    for i in range(len(shared)):
        edited = list(shared)
        edited[i] = edited[i] + " EDITED"
        assert _digest_hash(edited) != digest_mod.DIGEST_PROMPT_VERSION, shared[i]
        assert _critique_hash(edited) != critique_mod.CRITIQUE_PROMPT_VERSION, shared[i]


# --------------------------------------------------------------------------- #
# The render-identity SCHEME bump is the invalidation mechanism (P7 item 28)
# --------------------------------------------------------------------------- #


def test_render_identity_scheme_is_v4_for_the_annotation_free_text_policy(tmp_path):
    """Item 28 changed the text-extraction POLICY, not the document.

    ``_page_dependency_sha256`` hashes the annotation bytes and those bytes did
    not move, so without a scheme bump an already-cached annotated page still
    hits level 1 and is served a digest built from annotation-contaminated
    ``sheet_text`` **without re-extracting the text** — a false hit, which is the
    one failure mode the identity exists to prevent.

    Without this test the bump is invisible: reverting the literal to v3 changes
    nothing else observable, so every other cache-identity test still passes.
    """
    import drawing_analyzer.render as R

    assert R._RENDER_IDENTITY_SCHEME == "render-identity-v4"

    path = tmp_path / "M-101.pdf"
    doc = _base_doc()
    annot = doc[0].add_freetext_annot(
        pymupdf.Rect(200, 300, 500, 360), "QC-014 PRIOR REVIEW MARKUP", fontsize=9
    )
    annot.update()
    doc.save(str(path))
    doc.close()

    current = _identity(path)
    assert current.startswith("render-identity-v4|")
    # The scheme rides the key: a pre-change entry cannot be served to the new
    # extraction policy.
    legacy = "render-identity-v3|" + current.split("|", 1)[1]
    assert current != legacy


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
# Remediation WP-04.1: a critique-scoped contract term, not a schema bump
# --------------------------------------------------------------------------- #
#
# A critique entry stores the POST-MERGE findings of its reads
# (``critique.critique_cache_entry_from_result``), so the host's merge rule is
# part of what a stored critique means. WP-04.1 changed the quantity tokenizer
# behind ``critique.critical_signature``, which changes which reads merge. The
# change had to invalidate the critique namespace, and only it: the v10
# precedent bumped ``_SCHEMA_VERSION`` for a signature change, which feeds every
# key builder and re-billed every digest (plan §2 rule 6).

from types import SimpleNamespace  # noqa: E402

from drawing_analyzer import digest_cache as DC  # noqa: E402

_KEY_SHEET = SimpleNamespace(
    overview=SimpleNamespace(png_bytes=b"OVERVIEW"),
    tiles=[SimpleNamespace(png_bytes=b"TILE00"), SimpleNamespace(png_bytes=b"TILE01")],
)
_KEY_RENDER_IDENTITY = "render-identity-v4|content_dependency=page:abc"
_KEY_REQUEST = dict(
    model="claude-opus-5", prompt_version="p-1", max_tokens=64000,
    effort="high", use_thinking=True,
)
_KEY_SHEET_TEXT = "VAV-3 SERVES ROOM 120"


def _current_keys() -> dict[str, str]:
    """Every key builder over one fixed set of inputs."""
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


# The keys these inputs produced through 1.7.0 and on main before WP-04.1
# (schema 10, no critique contract term), computed from the unchanged builders.
# If a later change moves one of these deliberately, re-pin it in that PR and
# record the move in the migration register (_plans/DECISIONS.md).
_KEYS_BEFORE_WP_04_1 = {
    "digest_l2": "273a27b059cdef930f7900591d9f4387c830bfcd1999a1f2e83fe00cbb3d6b93",
    "digest_l1": "3ffb7565e0c1d400cfa2cdba4fa1445831e51ddcb336ce9aa41fea2748d046d5",
    "critique_l2": "51260a632568fb268d55cf4977aa1e41aa01f80a45eca8e21df0d966db990cec",
    "critique_l1": "946d7517e6636e49ecb8ad2f035d7bfdbdfa6acad2903178bb18ec9779b7b869",
    "critique_l2_profiles_structured":
        "7a9baf0a35dfca4839c5d55b3c24d33e051b338c6a5dcc71bd8976756517d6b7",
    "critique_l1_profiles_structured":
        "483ac70f16253ae4c6e7369780099767b5604457ed9e5e3d53137180e04df59c",
    "identity": "f61f9c79d5af37e47030f77427b04717a10600f22d12f45ae6d29c5de5e78c87",
    "review_plan": "cf72490acb8efe01e25b6d7e46375ecbbc7dd54603bace48e49ebb1d25b870d5",
    "citation": "17396185e1c6aec3d4daf2b4478a7348954f97cb104b2680dd0fe995e0022410",
    "investigation": "dd4994bec0947535e5b86839209c5942506758fecc81e6d5f2822ec2743da631",
}
_CRITIQUE_KEYS = (
    "critique_l2", "critique_l1",
    "critique_l2_profiles_structured", "critique_l1_profiles_structured",
)
_OTHER_KEYS = tuple(k for k in _KEYS_BEFORE_WP_04_1 if k not in _CRITIQUE_KEYS)


def test_wp_04_1_moves_every_critique_key_and_no_other_key():
    now = _current_keys()
    for name in _CRITIQUE_KEYS:
        assert now[name] != _KEYS_BEFORE_WP_04_1[name], f"{name}: an old entry would still hit"
    for name in _OTHER_KEYS:
        assert now[name] == _KEYS_BEFORE_WP_04_1[name], f"{name}: a paid entry was orphaned"


def test_the_critique_contract_rides_both_critique_builders_and_nothing_else(monkeypatch):
    # One term inside BOTH builders, so the pre-render probe (level 1) and the
    # PNG-bytes store (level 2) can never disagree about which contract they
    # serve -- the same reason F-01's structured_key rides both levels.
    before = _current_keys()
    monkeypatch.setattr(DC, "_CRITIQUE_CACHE_CONTRACT", DC._CRITIQUE_CACHE_CONTRACT + 1)
    after = _current_keys()
    for name in _CRITIQUE_KEYS:
        assert after[name] != before[name], name
    for name in _OTHER_KEYS:
        assert after[name] == before[name], name


def test_a_critique_entry_from_before_wp_04_1_misses_and_is_never_deleted(tmp_path):
    path = tmp_path / "digest_cache.json"
    cache = DigestCache(path, persist=True)
    stale = {"findings": [], "claims": [], "runs": 2, "requested_runs": 2,
             "completed_runs": 2, "input_tokens": 1, "output_tokens": 1}
    cache.put(_KEYS_BEFORE_WP_04_1["critique_l1"], stale)
    cache.put(_KEYS_BEFORE_WP_04_1["critique_l2"], stale)
    cache.put(_KEYS_BEFORE_WP_04_1["digest_l1"], {"text": "digest", "stop_reason": "end_turn"})
    cache.close()

    reopened = DigestCache(path, persist=True)
    try:
        now = _current_keys()
        # The old merge is never served: the next exhaustive run re-critiques.
        assert reopened.get(now["critique_l1"]) is None
        assert reopened.get(now["critique_l2"]) is None
        # ...while the digest it sits beside is still a hit.
        assert reopened.get(now["digest_l1"]) == {"text": "digest", "stop_reason": "end_turn"}
        # Nothing is deleted as a "migration" (plan §2 rule 6).
        assert reopened.get(_KEYS_BEFORE_WP_04_1["critique_l1"]) == stale
        assert reopened.get(_KEYS_BEFORE_WP_04_1["critique_l2"]) == stale
    finally:
        reopened.close()


# The merge rule a stored critique was produced under, fingerprinted over a
# fixed corpus: the critical signature of every finding, the pairwise duplicate
# verdict, and the self-consistency merge of the corpus read as two reads. A
# change to any of them changes what a critique entry would hold, so it needs
# a new _CRITIQUE_CACHE_CONTRACT. One fingerprint per contract value, never
# edited in place: to change the rule, bump the contract and pin the new
# fingerprint under the new value.
_MERGE_RULE_CORPUS = (
    ("Provide 6-inch drain at column line 4", ""),
    ("Provide 4-inch drain at column line 4", ""),
    ("Provide 6 in drain at column line 4", ""),
    ("Supply air to AHU-1 is 12,500 cfm per the mechanical schedule", "12,500 CFM"),
    ("Supply air to AHU-1 is 1,500 cfm per the mechanical schedule", "1,500 CFM"),
    ("Supply air to AHU-1 is 12500 cfm per the mechanical schedule", ""),
    ("Return air at RTU-2 reads 1,2,500 cfm on the mechanical schedule", ""),
    ("Setpoint for RTU-2 serving the lab is 90 deg F in the sequence", ""),
    ("Setpoint for RTU-2 serving the lab is 90 deg C in the sequence", ""),
    ("Setpoint for RTU-2 serving the lab is 90°F in the sequence", ""),
    ("Provide 45 deg elbow at the riser offset near grid B", ""),
    ("Provide 45° elbow at the riser offset near grid B", ""),
    ("Duct 24x12 serving VAV-3 conflicts with the beam at grid C", ""),
    ("Duct 24x10 serving VAV-3 conflicts with the beam at grid C", ""),
    ('Duct 24"x12" serving VAV-3 conflicts with the beam at grid C', '24"x12"'),
    ("Provide 20A breaker for exhaust fan EF-1 on panel LP-1", ""),
    ("Provide 30A breaker for exhaust fan EF-1 on panel LP-1", ""),
    ("RTU-1 is scheduled at 480V but is fed from panel HP-1", ""),
    ("RTU-1 is scheduled at 208V but is fed from panel HP-1", ""),
    ("Panel LP-2 is 120/208V on the one-line diagram", ""),
    ("Maintain 4-6 in clearance around the base of pump P-1", ""),
    ("Provide 2,4,6 in floor drains in the mechanical room", ""),
    ("Room 101A: provide 6 in floor drain at the sink", "ROOM 101A"),
    ("Room 101A: provide 4 in floor drain at the sink", "ROOM 101A"),
    ("Pump P-1 flow is 500 gpm at 100 psi per the schedule", "P-1 500 GPM"),
    ("Pump P-1 flow is 550 gpm at 100 psi per the schedule", "P-1 550 GPM"),
    ("maintain 12'-6\" clear at the M-101 riser", ""),
    ("maintain 12'-8\" clear at the M-101 riser", ""),
    ('Provide 1/2" drain at the low point of the loop', ""),
    ('Provide 2 1/2" drain at the low point of the loop', ""),
    ("Provide 4x25 gpm circulating pumps at the central plant", ""),
    ('Board 6"x12\' is cut from the wrong stock', ""),
    ("Detail 5 is not shown on this sheet", "DETAIL 5"),
    ("Detail 5 is shown on this sheet", "DETAIL 5"),
)


def _merge_rule_fingerprint() -> str:
    import hashlib

    from drawing_analyzer.critique import (
        _is_duplicate,
        critical_signature,
        merge_self_consistency,
    )
    from drawing_analyzer.models import Finding

    def corpus():
        return [
            Finding(sheet_id="M-101", source_name="mech.pdf", page_index=0,
                    category="coordination", severity="medium", text=text,
                    source_quote=quote)
            for text, quote in _MERGE_RULE_CORPUS
        ]

    findings = corpus()
    merged = merge_self_consistency([corpus()[0::2], corpus()[1::2]])
    payload = {
        "signatures": [critical_signature(f) for f in findings],
        "duplicates": [[_is_duplicate(a, b) for b in findings] for a in findings],
        "merged": [
            [m.text, m.source_quote, sorted(m.supporting_quotes), m.severity,
             m.confidence, m.reproduced]
            for m in merged
        ],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# Before the term existed (1.7.0 through WP-01.2) this rule fingerprinted as
# 70a2e09c50476f79c5096837430c6b4a5628a66b3df11a7ff03830135404e1e4.
_MERGE_RULE_BY_CRITIQUE_CONTRACT = {
    1: "fa3623035836987525e786ff44597ec1cdf2cc59e1dffbff6a07ef278f3614bb",  # WP-04.1
}


def test_the_critique_contract_is_pinned_to_the_merge_rule():
    fingerprint = _merge_rule_fingerprint()
    pinned = _MERGE_RULE_BY_CRITIQUE_CONTRACT.get(DC._CRITIQUE_CACHE_CONTRACT)
    assert pinned == fingerprint, (
        "the critique merge rule no longer matches the rule pinned for "
        f"_CRITIQUE_CACHE_CONTRACT={DC._CRITIQUE_CACHE_CONTRACT}: a stored critique "
        "would be served under a rule that did not produce it. Bump "
        "digest_cache._CRITIQUE_CACHE_CONTRACT, pin this fingerprint under the "
        f"new value ({fingerprint}), and add a migration-register row."
    )
