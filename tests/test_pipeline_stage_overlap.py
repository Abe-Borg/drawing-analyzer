from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from pathlib import Path
import threading

import pytest

import drawing_analyzer.pipeline as pipeline
from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT
from drawing_analyzer.cross_qc import CrossQCResult
from drawing_analyzer.focus import FocusReportResult
from drawing_analyzer.models import SetIdentity
from drawing_analyzer.profiles import Profile
from drawing_analyzer.review_planner import PlanResult
from drawing_analyzer.set_identity import IdentityResult
from drawing_analyzer.synthesis import SynthesisResult


def _make_pdf(path: Path) -> Path:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((72, 72), path.stem)
    doc.save(str(path))
    doc.close()
    return path


def _install_digest_stub(monkeypatch) -> None:
    def _digests(paths, **_kwargs):
        from drawing_analyzer.digest import SheetDigest

        return [
            SheetDigest(ref=ref, text=f"Digest for {ref.source_name}")
            for ref in pipeline.list_sheets(paths)
        ]

    monkeypatch.setattr(pipeline, "_digest_sheets_concurrent", _digests)


def _identity_result() -> IdentityResult:
    return IdentityResult(
        identity=SetIdentity(disciplines=("mechanical",), confidence="high"),
        input_tokens=11,
        output_tokens=3,
        model_used=REVIEW_MODEL_DEFAULT,
    )


def _plan_result() -> PlanResult:
    profile = Profile(
        name="model-plan",
        title="Model plan",
        disciplines=("mechanical",),
        items=("Flag conflicting equipment tags.",),
        content_hash="plan-hash",
    )
    return PlanResult(
        profiles=[profile], markdown="# Model plan\n", input_tokens=12,
        output_tokens=4, model_used=REVIEW_MODEL_DEFAULT,
    )


def _record_critique_usage(run_usage) -> None:
    pipeline._record_usage(
        run_usage,
        family="critique",
        instance="critique:test:p1",
        model=REVIEW_MODEL_DEFAULT,
        input_tokens=13,
        output_tokens=5,
    )


def _run_enabled_pipeline(tmp_path: Path, *, max_workers: int = 4):
    return pipeline.extract_drawing_context(
        [_make_pdf(tmp_path / "M-101.pdf"), _make_pdf(tmp_path / "M-102.pdf")],
        client=object(),
        rows=2,
        cols=2,
        max_workers=max_workers,
        synthesize=True,
        critique=True,
        cross_qc=True,
        identity=True,
        review_plan=True,
        focus="equipment coordination",
    )


def test_independent_set_stages_overlap_but_record_in_deterministic_order(
    tmp_path, monkeypatch,
) -> None:
    _install_digest_stub(monkeypatch)
    monkeypatch.setenv("DRAWING_ANALYZER_STAGE_OVERLAP", "1")
    synth_started = threading.Event()
    focus_started = threading.Event()
    cross_started = threading.Event()
    release_background = threading.Event()
    calls = {name: 0 for name in ("identity", "plan", "critique", "cross", "synth", "focus")}

    def _synthesis(*_args, **_kwargs):
        calls["synth"] += 1
        synth_started.set()
        assert release_background.wait(3)
        return SynthesisResult(
            text="SYNTHESIS", input_tokens=21, output_tokens=6,
            model_used=REVIEW_MODEL_DEFAULT,
        )

    def _focus(*_args, **_kwargs):
        calls["focus"] += 1
        focus_started.set()
        assert release_background.wait(3)
        return FocusReportResult(
            text="FOCUS", input_tokens=22, output_tokens=7,
            model_used=REVIEW_MODEL_DEFAULT,
        )

    def _identity(*_args, **_kwargs):
        calls["identity"] += 1
        assert synth_started.wait(3)
        assert focus_started.wait(3)
        return _identity_result()

    def _cross(*_args, **_kwargs):
        calls["cross"] += 1
        cross_started.set()
        assert release_background.wait(3)
        return CrossQCResult(
            input_tokens=23, output_tokens=8, shards_planned=1,
            shards_completed=1, reconciliation_completed=True,
        )

    def _plan(*_args, **_kwargs):
        calls["plan"] += 1
        assert cross_started.wait(3)
        return _plan_result()

    def _critique(*_args, **kwargs):
        calls["critique"] += 1
        assert synth_started.is_set() and focus_started.is_set() and cross_started.is_set()
        _record_critique_usage(kwargs["run_usage"])
        release_background.set()
        return [], [], []

    monkeypatch.setattr("drawing_analyzer.synthesis.synthesize_drawing_set", _synthesis)
    monkeypatch.setattr("drawing_analyzer.focus.generate_focus_report", _focus)
    monkeypatch.setattr("drawing_analyzer.set_identity.identify_set", _identity)
    monkeypatch.setattr("drawing_analyzer.cross_qc.cross_sheet_qc", _cross)
    monkeypatch.setattr("drawing_analyzer.review_planner.author_review_plan", _plan)
    monkeypatch.setattr(pipeline, "_run_critique_stage", _critique)

    ctx = _run_enabled_pipeline(tmp_path)

    assert calls == {name: 1 for name in calls}
    assert ctx.synthesis_text == "SYNTHESIS"
    assert ctx.focus_report_text == "FOCUS"
    stages = [stage.stage for stage in ctx.stage_results]
    assert [stages.index(name) for name in (
        "identity", "review_plan", "profiles", "critique", "cross_qc", "synthesis",
    )] == sorted(stages.index(name) for name in (
        "identity", "review_plan", "profiles", "critique", "cross_qc", "synthesis",
    ))
    assert [record.stage_family for record in ctx.run_usage.records] == [
        "digest", "digest", "identity", "review_plan", "critique",
        "cross_qc", "synthesis", "focus",
    ]

    events = [(event.event_code, event.stage) for event in ctx.run_journal.events]
    assert events.index(("STAGE_START", "synthesis")) < events.index(("STAGE_START", "identity"))
    assert events.index(("STAGE_END", "identity")) < events.index(("STAGE_START", "cross_qc"))
    assert events.index(("STAGE_START", "cross_qc")) < events.index(("STAGE_START", "review_plan"))


def test_max_workers_one_keeps_set_stages_sequential_and_single_call(
    tmp_path, monkeypatch,
) -> None:
    _install_digest_stub(monkeypatch)
    order: list[str] = []

    def _identity(*_args, **_kwargs):
        order.append("identity")
        return _identity_result()

    def _plan(*_args, **_kwargs):
        order.append("plan")
        return _plan_result()

    def _critique(*_args, **kwargs):
        order.append("critique")
        _record_critique_usage(kwargs["run_usage"])
        return [], [], []

    def _cross(*_args, **_kwargs):
        order.append("cross")
        return CrossQCResult(shards_planned=1, shards_completed=1)

    def _synthesis(*_args, **_kwargs):
        order.append("synth")
        return SynthesisResult(text="S", model_used=REVIEW_MODEL_DEFAULT)

    def _focus(*_args, **_kwargs):
        order.append("focus")
        return FocusReportResult(text="F", model_used=REVIEW_MODEL_DEFAULT)

    monkeypatch.setattr("drawing_analyzer.set_identity.identify_set", _identity)
    monkeypatch.setattr("drawing_analyzer.review_planner.author_review_plan", _plan)
    monkeypatch.setattr(pipeline, "_run_critique_stage", _critique)
    monkeypatch.setattr("drawing_analyzer.cross_qc.cross_sheet_qc", _cross)
    monkeypatch.setattr("drawing_analyzer.synthesis.synthesize_drawing_set", _synthesis)
    monkeypatch.setattr("drawing_analyzer.focus.generate_focus_report", _focus)

    _run_enabled_pipeline(tmp_path, max_workers=1)

    assert order == ["identity", "plan", "critique", "cross", "synth", "focus"]


def test_background_failure_is_additive_and_executor_shuts_down_once(
    tmp_path, monkeypatch,
) -> None:
    _install_digest_stub(monkeypatch)
    monkeypatch.setenv("DRAWING_ANALYZER_STAGE_OVERLAP", "1")
    shutdown_calls: list[bool] = []

    class _TrackingExecutor(RealThreadPoolExecutor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            shutdown_calls.append(bool(wait))
            return super().shutdown(wait=wait, cancel_futures=cancel_futures)

    monkeypatch.setattr(pipeline, "ThreadPoolExecutor", _TrackingExecutor)
    monkeypatch.setattr(
        "drawing_analyzer.set_identity.identify_set",
        lambda *_a, **_k: _identity_result(),
    )
    monkeypatch.setattr(
        "drawing_analyzer.review_planner.author_review_plan",
        lambda *_a, **_k: _plan_result(),
    )
    monkeypatch.setattr(
        pipeline, "_run_critique_stage", lambda *_a, **_k: ([], [], []),
    )
    monkeypatch.setattr(
        "drawing_analyzer.cross_qc.cross_sheet_qc",
        lambda *_a, **_k: CrossQCResult(shards_planned=1, shards_completed=1),
    )

    def _synthesis_boom(*_args, **_kwargs):
        raise RuntimeError("synthesis worker exploded")

    monkeypatch.setattr(
        "drawing_analyzer.synthesis.synthesize_drawing_set", _synthesis_boom,
    )
    monkeypatch.setattr(
        "drawing_analyzer.focus.generate_focus_report",
        lambda *_a, **_k: FocusReportResult(
            text="FOCUS SURVIVES", model_used=REVIEW_MODEL_DEFAULT,
        ),
    )

    ctx = _run_enabled_pipeline(tmp_path)

    assert ctx.synthesis_text == ""
    assert ctx.focus_report_text == "FOCUS SURVIVES"
    assert any("synthesis worker exploded" in error for error in ctx.errors)
    assert {stage.stage: stage.status for stage in ctx.stage_results}["synthesis"] == "FAILED"
    assert shutdown_calls == [True]
