from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from drawing_analyzer.critique import CritiqueResult
from drawing_analyzer.file_upload import ReusableSheetUpload
from drawing_analyzer.models import ImageTile, RenderedSheet, RunUsage, SheetRef
import drawing_analyzer.pipeline as pipeline


def _sheet(name: str, index: int) -> RenderedSheet:
    ref = SheetRef(
        pdf_path=Path(f"{name}.pdf"), source_name=f"{name}.pdf",
        page_index=index, page_count=3, source_id=f"SRC-{index + 1:04d}",
    )
    return RenderedSheet(
        ref=ref,
        overview=ImageTile(name.encode(), 10, 10, "overview"),
        tiles=[], page_width_pt=100, page_height_pt=100, rows=1, cols=1,
    )


def _complete_result() -> CritiqueResult:
    return CritiqueResult(
        findings=[], runs=2, requested_runs=2, completed_runs=2,
    )


def _run_realtime(monkeypatch, sheets, spool, renderer):
    seen: list[str] = []
    monkeypatch.setattr(pipeline, "list_sheets", lambda _paths: [s.ref for s in sheets])
    monkeypatch.setattr(pipeline, "iter_rendered_sheets", renderer)

    def _critique(sheet, **_kwargs):
        seen.append(sheet.ref.source_name)
        return _complete_result()

    monkeypatch.setattr(
        "drawing_analyzer.critique.critique_sheet_self_consistent", _critique,
    )
    pipeline._run_critique_stage(
        [Path("set.pdf")], rows=1, cols=1, overlap_frac=0.0,
        client=object(), cache=None, progress=None, total=len(sheets),
        max_workers=1, run_usage=RunUsage(), use_batch=False,
        render_spool=spool,
    )
    return seen


def test_spool_hits_and_fresh_miss_are_consumed_in_page_order(monkeypatch) -> None:
    a, b, c = (_sheet("A", 0), _sheet("B", 1), _sheet("C", 2))
    stored = {
        pipeline._refkey(a.ref): a,
        pipeline._refkey(c.ref): c,
    }

    class _Spool:
        def __contains__(self, key):
            return key in stored

        def pop(self, key):
            return stored.pop(key, None)

    render_calls = []

    def _render(_paths, **kwargs):
        render_calls.append(set(kwargs["only"]))
        yield b

    assert _run_realtime(monkeypatch, [a, b, c], _Spool(), _render) == [
        "A.pdf", "B.pdf", "C.pdf",
    ]
    assert render_calls == [{pipeline._refkey(b.ref)}]


def test_spool_load_failure_uses_exact_one_page_fallback(monkeypatch) -> None:
    a, b, c = (_sheet("A", 0), _sheet("B", 1), _sheet("C", 2))
    stored = {
        pipeline._refkey(a.ref): a,
        pipeline._refkey(b.ref): None,
        pipeline._refkey(c.ref): c,
    }

    class _Spool:
        def __contains__(self, key):
            return key in stored

        def pop(self, key):
            return stored.pop(key, None)

    requested = []

    def _render(_paths, **kwargs):
        requested.append(set(kwargs["only"]))
        if pipeline._refkey(b.ref) in kwargs["only"]:
            yield b

    assert _run_realtime(monkeypatch, [a, b, c], _Spool(), _render) == [
        "A.pdf", "B.pdf", "C.pdf",
    ]
    assert requested == [{pipeline._refkey(b.ref)}]


def test_skipped_fresh_page_does_not_shift_later_render(monkeypatch) -> None:
    a, b, c = (_sheet("A", 0), _sheet("B", 1), _sheet("C", 2))
    stored = {pipeline._refkey(a.ref): a}

    class _Spool:
        def __contains__(self, key):
            return key in stored

        def pop(self, key):
            return stored.pop(key, None)

    def _render(_paths, **_kwargs):
        # B was pathological and skipped; C must stay attached to C.
        yield c

    assert _run_realtime(monkeypatch, [a, b, c], _Spool(), _render) == [
        "A.pdf", "C.pdf",
    ]


def test_batch_reusable_and_fresh_inputs_keep_page_order(monkeypatch) -> None:
    a, b, c = (_sheet("A", 0), _sheet("B", 1), _sheet("C", 2))
    reusable = [
        ReusableSheetUpload(
            ref=sheet.ref, rows=1, cols=1,
            content=[{"type": "text", "text": "digest"}],
            file_ids=[f"file-{sheet.ref.source_name}"],
        )
        for sheet in (a, c)
    ]
    monkeypatch.setattr(pipeline, "list_sheets", lambda _paths: [a.ref, b.ref, c.ref])
    monkeypatch.setattr(
        pipeline, "iter_rendered_sheets", lambda _paths, **_kwargs: iter([b]),
    )
    seen = []

    def _submit(inputs, **_kwargs):
        seen.extend(item.ref.source_name for item in inputs)
        return SimpleNamespace()

    monkeypatch.setattr("drawing_analyzer.batch_critique.submit_critique_batch", _submit)
    monkeypatch.setattr(
        "drawing_analyzer.batch_critique.collect_critique_batch",
        lambda *_args, **_kwargs: [],
    )

    pipeline._run_critique_stage(
        [Path("set.pdf")], rows=1, cols=1, overlap_frac=0.0,
        client=object(), cache=None, progress=None, total=3, max_workers=1,
        run_usage=RunUsage(), use_batch=True, reusable_uploads=reusable,
    )

    assert seen == ["A.pdf", "B.pdf", "C.pdf"]
