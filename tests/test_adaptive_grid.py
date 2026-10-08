"""Per-page grids through real PDF geometry and hermetic vision/QC clients."""
from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace

import pytest

from drawing_analyzer import tiling
from drawing_analyzer.core.tokenizer import estimate_image_tokens_total
from drawing_analyzer.cost import estimate_image_tokens_for_bases
from drawing_analyzer.digest import DIGEST_SYSTEM_PROMPT, parse_findings
from drawing_analyzer.critique import CRITIQUE_SYSTEM_PROMPT
from drawing_analyzer.digest_cache import (
    DigestCache, critique_cache_key_level1, digest_cache_key_level1,
    digest_cache_key, critique_cache_key, _DIGEST_SCHEMA_VERSION,
)
from drawing_analyzer.models import SheetRef
from drawing_analyzer.pipeline import estimate_image_tokens_for_set, extract_drawing_context
from tests.fixtures.fake_anthropic import FakeBatchResult, FakeBatchResultEnvelope
from tests.fixtures.gauntlet import ScriptedQCClient, SheetScript, _system_text

pymupdf = pytest.importorskip("pymupdf")

from drawing_analyzer import render  # noqa: E402


SHAPES = [(8.5, 11), (11, 17), (34, 44), (30, 42), (8.5, 11)]
GRIDS = [(43, 1), (2, 1), (6, 6), (6, 6), (27, 1)]


def _mixed_pdf(path):
    doc = pymupdf.open()
    for i, (w, h) in enumerate(SHAPES):
        page = doc.new_page(width=w * 72, height=h * 72)
        # Content in every tile, including words-free cells. Suppression must
        # depend on pixels, never on the text layer (I-1).
        for j in range(1, 48):
            x, y = page.rect.width * j / 48, page.rect.height * j / 48
            page.draw_line((x, 0), (x, page.rect.height))
            page.draw_line((0, y), (page.rect.width, y))
        if i != 4:
            page.insert_text((30, 50), f"NOTE-{i + 1}")
            page.insert_text((page.rect.width - 80, page.rect.height - 30), f"M-{101 + i}")
    doc.save(path)
    doc.close()
    return path


class _Client(ScriptedQCClient):
    """Run the same scripted reads on real-time and batch transports."""

    def __init__(self, sheet_scripts=None):
        scripts = []
        for i, (rows, cols) in enumerate(GRIDS):
            label = tiling.tile_label_for(rows - 1, cols - 1)
            finding = {
                "sheet_id": f"M-{101 + i}" if i != 4 else "",
                "category": "question", "severity": "medium",
                "text": f"Symbol legend omits equipment marker {i + 1}.",
                "source_quote": "", "tile_label": label,
            }
            critique = dict(finding, category="coordination",
                            text=f"Access route crosses wall {i + 1}.")
            scripts.append(SheetScript(
                token=f"(page {i + 1}/5)", prose=f"Sheet M-{101 + i} - Plan",
                findings=[finding], read1=([critique], []), read2=([critique], []),
            ))
        super().__init__(scripts if sheet_scripts is None else sheet_scripts,
                         verify_verdicts=(("equipment marker 1.", "NOT_VISIBLE"),),
                         cross_findings=[{
                             "sheet_id": "M-101", "category": "conflict", "severity": "high",
                             "text": "The plan notes disagree about equipment placement.",
                             "source_quote": "NOTE-1", "tile_label": "r20c1",
                             "also_on": [{"sheet_id": "M-103", "source_quote": "NOTE-3",
                                          "tile_label": "r6c6"}],
                         }])
        self.vision_requests = []
        self.uploaded = []
        batches = {}

        def upload(*, file):
            fid = f"file-{len(self.uploaded)}"
            self.uploaded.append(fid)
            return SimpleNamespace(id=fid)

        def create(*, requests, **_kw):
            bid = f"batch-{len(batches)}"
            batches[bid] = list(requests)
            return SimpleNamespace(id=bid)

        def retrieve(bid):
            return SimpleNamespace(
                processing_status="ended",
                request_counts=SimpleNamespace(processing=0, succeeded=len(batches[bid]),
                                               errored=0, canceled=0, expired=0),
            )

        def results(bid):
            for req in reversed(batches[bid]):
                yield FakeBatchResult(req["custom_id"],
                                      FakeBatchResultEnvelope(message=self._route(req["params"])))

        self.files = SimpleNamespace(upload=upload, delete=lambda _fid: None)
        self.messages.batches = SimpleNamespace(create=create, retrieve=retrieve, results=results)

    def _route(self, kw):
        system = _system_text(kw.get("system"))
        if system.startswith(DIGEST_SYSTEM_PROMPT) or system.startswith(CRITIQUE_SYSTEM_PROMPT):
            self.vision_requests.append(kw)
        return super()._route(kw)


@pytest.mark.parametrize("batch", [False, True])
def test_mixed_size_set_digest_qc_crops_artifacts_and_warm_cache(tmp_path, monkeypatch, batch):
    pdf = _mixed_pdf(tmp_path / "mixed.pdf")
    cache = DigestCache(tmp_path / "cache.json")
    work = tmp_path / "qc"
    client = _Client()
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    renders = []
    real_render = render.render_sheet

    def recording_render(page, ref, **kwargs):
        sheet = real_render(page, ref, **kwargs)
        renders.append(sheet)
        return sheet

    monkeypatch.setattr(render, "render_sheet", recording_render)
    options = dict(
        cache=cache, max_workers=1, use_batch=batch, critique_use_batch=batch, qc_markups=True,
        synthesize=False, critique=True, cross_qc=True, verify_findings=True,
        investigate=True, identity=False, review_plan=False, citation_check=False,
    )
    ctx = extract_drawing_context([pdf], client=client, qc_work_dir=work,
                                  save_tile_artifacts=True, **options)
    assert not ctx.errors
    assert len(renders) == 5  # critique reuses the per-page spool/uploads
    assert [(g.rows, g.cols) for g in ctx.sheet_geometries] == GRIDS
    assert [(s.rows, s.cols) for s in renders] == GRIDS
    assert len(client.vision_requests) == 15  # digest + both critiques per page
    for sheet in renders:
        matching = [q for q in client.vision_requests
                    if sheet.ref.display_label in q["messages"][0]["content"][0]["text"]]
        assert len(matching) == 3
        contents = [q["messages"][0]["content"] for q in matching]
        # Exact shared image prefix, labels and page-specific grid on all reads.
        assert contents[0][:-1] == contents[1][:-1] == contents[2][:-1]
        images = [b for b in contents[0] if b["type"] == "image"]
        assert len(images) == sheet.rows * sheet.cols + 1
        assert f"{sheet.rows}x{sheet.cols} grid" in contents[0][0]["text"]
        assert any(f"Tile r{sheet.rows}c{sheet.cols}" in b.get("text", "") for b in contents[0])
    if batch:
        # No re-upload for critique; both reads adopt the digest's own IDs.
        assert len(client.uploaded) == sum(r * c + 1 for r, c in GRIDS)
    graphics = [f for f in ctx.findings if "equipment marker" in f.text or "crosses wall" in f.text]
    assert len(graphics) == 10
    for f in graphics:
        geom = ctx.sheet_geometries[f.page_index]
        assert f.tile == [geom.rows - 1, geom.cols - 1]
        rect = tiling.tile_rects(geom.page_width_pt, geom.page_height_pt,
                                rows=geom.rows, cols=geom.cols)[-1]
        assert f.anchor.status == "TILE"
        assert f.anchor.rect_pdf == pytest.approx([rect.x0, rect.y0, rect.x1, rect.y1])
        assert f.verification.status == "VERIFIED"
        # Verify and investigate's initial crop follows that same tile anchor.
        assert f.verification.evidence
        assert f.verification.evidence[0].canonical_anchor_rect == pytest.approx(f.anchor.rect_pdf)
        assert f.verification.evidence[0].page_index == f.page_index
    assert client.investigate_calls == 2  # one evidence tool, then a verdict
    conflict = next(f for f in ctx.findings if f.category == "conflict")
    assert conflict.tile == [19, 0]
    assert conflict.also_on[0].tile == [5, 5]
    assert conflict.anchor.status == conflict.also_on[0].anchor.status == "EXACT"
    inventories = sorted(work.glob("tiles/*/tiles.json"))
    assert len(inventories) == 5
    for p in inventories:
        inv = json.loads(p.read_text())
        rows, cols = GRIDS[inv["sheet"]["page_index"]]
        assert (inv["rows"], inv["cols"]) == (rows, cols)
        assert len(inv["tiles"]) == rows * cols
    before = len(renders)
    warm_client = _Client()
    warm = extract_drawing_context([pdf], client=warm_client, qc_work_dir=tmp_path / "warm",
                                   save_tile_artifacts=False, **options)
    assert not warm.errors
    assert len(renders) == before
    assert warm_client.vision_requests == []
    assert [(g.rows, g.cols) for g in warm.sheet_geometries] == GRIDS
    assert [(f.tile, f.anchor.rect_pdf) for f in warm.findings] == [
        (f.tile, f.anchor.rect_pdf) for f in ctx.findings]


@pytest.mark.parametrize("shape", [(34, 44), (44, 34), (30, 42), (42, 30)])
@pytest.mark.parametrize("raster", [False, True])
def test_large_sheet_cache_keys_and_images_unchanged(shape, raster):
    doc = pymupdf.open()
    page = doc.new_page(width=shape[0] * 72, height=shape[1] * 72)
    page.draw_line((0, 0), (page.rect.width, page.rect.height))
    if not raster:
        page.insert_text((30, 50), "UNCHANGED SHEET")
    ref = SheetRef(pdf_path=None, source_name="set.pdf", page_index=0, page_count=1)
    kw = dict(content_sha256="source", page_index=0, page_count=1)
    legacy = render.sheet_render_identity(page, rows=6, cols=6, **kw)
    adaptive = render.sheet_render_identity(page, **kw)
    assert adaptive == legacy
    # v4 is the annotation-free text-extraction policy; reverting the scheme
    # literal would let an annotated page hit level 1 with contaminated text.
    assert adaptive.startswith("render-identity-v4|")
    assert _DIGEST_SCHEMA_VERSION == 10  # Existing E/E1 cache entries remain admissible.
    params = dict(model="claude-opus-5", prompt_version="unchanged",
                  max_tokens=8000, effort="high", use_thinking=True)
    assert digest_cache_key_level1(adaptive, **params) == digest_cache_key_level1(legacy, **params)
    assert critique_cache_key_level1(adaptive, runs=2, **params) == critique_cache_key_level1(
        legacy, runs=2, **params)
    auto_sheet = render.render_sheet(page, ref)
    pinned_sheet = render.render_sheet(page, ref, rows=6, cols=6)
    assert auto_sheet.overview.png_bytes == pinned_sheet.overview.png_bytes
    assert [t.png_bytes for t in auto_sheet.tiles] == [t.png_bytes for t in pinned_sheet.tiles]
    assert digest_cache_key(auto_sheet, **params) == digest_cache_key(pinned_sheet, **params)
    # Independent oracle for the pre-adaptive level-2 format. Comparing two
    # calls to today's key function alone would miss an accidental key bump.
    for critique, key_fn in ((False, digest_cache_key), (True, critique_cache_key)):
        parts = ["schema=10", "model=claude-opus-5", "prompt=unchanged",
                 "max_tokens=8000", "effort=high", "thinking=1"]
        call_params = dict(params)
        if critique:
            parts.insert(1, "stage=critique")
            parts.append("runs=2")
            call_params["runs"] = 2
        old_hash = hashlib.sha256()
        for part in parts:
            old_hash.update(part.encode("utf-8"))
            old_hash.update(b"\x00")
        old_hash.update(auto_sheet.overview.png_bytes)
        for tile in auto_sheet.tiles:
            old_hash.update(tile.png_bytes)
        assert key_fn(auto_sheet, **call_params) == old_hash.hexdigest()
    doc.close()


def test_cropbox_rotation_controls_grid_and_cost(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=44 * 72, height=34 * 72)
    page.insert_text((30, 50), "VISIBLE TEXT")
    page.draw_line((0, 0), (11 * 72, 17 * 72))
    page.set_cropbox(pymupdf.Rect(0, 0, 11 * 72, 17 * 72))
    page.set_rotation(90)
    pdf = tmp_path / "crop.pdf"
    doc.save(pdf)
    doc.close()
    [(ref, identity, geom)] = render.iter_sheet_prescan([pdf])
    [sheet] = render.iter_rendered_sheets([pdf])
    assert (geom.rows, geom.cols) == (sheet.rows, sheet.cols) == (1, 2)
    assert (geom.page_width_pt, geom.page_height_pt) == (17 * 72, 11 * 72)
    assert "rows=1|cols=2" in identity
    estimate = estimate_image_tokens_for_bases(list(render.iter_sheet_cost_bases([pdf])))
    assert estimate.tokens == estimate_image_tokens_total(sheet.image_sizes, model="claude-opus-5")


def test_cost_prices_chosen_grids_and_unmeasured_allowance_bounds_large_pages(tmp_path):
    pdf = _mixed_pdf(tmp_path / "mixed.pdf")
    bases = list(render.iter_sheet_cost_bases([pdf]))
    est = estimate_image_tokens_for_bases(bases, model="claude-opus-5")
    assert est.tokens == 7_280 + 14_125 + 91_168 + 83_328 + 11_736
    assert est.tokens < estimate_image_tokens_for_bases(bases, rows=6, cols=6,
                                                     model="claude-opus-5").tokens
    for model in ("claude-opus-5", "claude-haiku-4-5"):
        for raster in (False, True):
            tokens = estimate_image_tokens_total(tiling.image_pixel_sizes(
                60 * 72, 80 * 72, is_raster=raster), model=model)
            assert tokens <= estimate_image_tokens_for_set(1, model=model)
    assert estimate_image_tokens_for_set(1, model="claude-opus-5") == 478_400


def _pdf_with_infeasible_page(tmp_path, *, raster):
    paths = [tmp_path / "oversized.pdf", tmp_path / "other.pdf"]
    doc = pymupdf.open()
    for i, size in enumerate([(8.5, 11), (80, 80), (11, 17)]):
        page = doc.new_page(width=size[0] * 72, height=size[1] * 72)
        if i != 1 or not raster:
            page.insert_text((30, 50), f"SHEET H-10{i}")
        page.draw_line((0, 0), (page.rect.width, page.rect.height))
    doc.save(paths[0])
    doc.close()
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((30, 50), "SHEET H-103")
    doc.save(paths[1])
    doc.close()
    return paths


@pytest.mark.parametrize("raster", [False, True])
def test_prescan_reports_one_infeasible_page_and_continues_without_rendering(tmp_path, monkeypatch, raster):
    paths = _pdf_with_infeasible_page(tmp_path, raster=raster)

    def no_pixmap(*args, **kwargs):
        pytest.fail("prescan must not rasterize")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", no_pixmap)
    assert len(render.list_sheets(render.inspect_inputs(paths).accepted_paths)) == 4
    failures = []
    scanned = list(render.iter_sheet_prescan(
        paths, on_page_error=lambda ref, exc: failures.append((ref, exc)),
    ))
    assert [(ref.pdf_path, ref.page_index) for ref, _, _ in scanned] == [
        (paths[0], 0), (paths[0], 2), (paths[1], 0),
    ]
    assert len(failures) == 1
    ref, exc = failures[0]
    assert (ref.pdf_path, ref.page_index) == (paths[0], 1)
    assert isinstance(exc, tiling.InfeasibleGridError)
    assert "DPI floor" in str(exc)


# The raster/vector split of the infeasible page is a prescan concern, covered
# above; the stages' handling of the reported page error does not depend on it.
@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_infeasible_page_keeps_digest_and_critique_partial_while_other_pages_complete(
    tmp_path, monkeypatch, batch, cached,
):
    paths = _pdf_with_infeasible_page(tmp_path, raster=False)
    cache = DigestCache(tmp_path / "cache.json") if cached else None
    scripts = [SheetScript(token=f"(page {i}/3)", prose=f"Sheet H-10{i} - Plan")
               for i in (1, 3)]
    scripts.append(SheetScript(token="other.pdf", prose="Sheet H-103 - Plan"))
    client = _Client(scripts)
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    options = dict(
        cache=cache, use_cache=False, max_workers=1, use_batch=batch,
        critique_use_batch=batch, synthesize=False, critique=True, cross_qc=False,
        verify_findings=False, investigate=False, identity=False, review_plan=False,
        citation_check=False, qc_markups=False,
    )
    ctx = extract_drawing_context(paths, client=client, **options)
    assert ctx.sheet_count == 4 and ctx.ok_sheet_count == 3
    assert [(s.ref.pdf_path, s.ref.page_index) for s in ctx.sheets] == [
        (paths[0], 0), (paths[0], 2), (paths[1], 0),
    ]
    assert len(client.vision_requests) == 9  # Three healthy pages, three reads each.
    assert sum(client.digest_calls.values()) == 3
    assert sum(client.critique_calls.values()) == 6
    for stage in ("digest", "critique"):
        result = next(s for s in ctx.stage_results if s.stage == stage)
        assert result.status == "PARTIAL"
        assert any("oversized.pdf (page 2/3)" in error for error in result.errors)
    assert any("oversized.pdf (page 2/3)" in error for error in ctx.errors)
    if cached:
        warm_client = _Client(scripts)
        warm = extract_drawing_context(paths, client=warm_client, **options)
        assert warm.sheet_count == 4 and warm.ok_sheet_count == 3
        assert warm_client.vision_requests == []
        assert all(s.cached for s in warm.sheets)
        assert all(next(s for s in warm.stage_results if s.stage == name).status == "PARTIAL"
                   for name in ("digest", "critique"))


def test_findings_labels_are_checked_against_each_pages_grid():
    ref = SheetRef(pdf_path=None, source_name="set.pdf", page_index=0, page_count=1)
    def parse(label, rows, cols):
        raw = "```json\n" + json.dumps({"findings": [{
            "category": "question", "severity": "medium", "text": "Graphic omitted.",
            "source_quote": "", "tile_label": label,
        }]}) + "\n```"
        return parse_findings(raw, ref, rows, cols)[1][0].tile
    assert parse("r20c1", 20, 1) == [19, 0]
    assert parse("r20c1", 2, 1) is None
    assert parse("r6c6", 6, 6) == [5, 5]
    assert parse("r6c6", 1, 1) is None
