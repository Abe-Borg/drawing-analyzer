"""Verification-pass tests.

The parse/geometry/orchestration tests use fakes and run without PyMuPDF; the
``render_region`` tests render a synthetic PDF and are skipped without it.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from drawing_analyzer.models import (
    Anchor,
    Finding,
    ImageTile,
    RenderedSheet,
    SheetRef,
    Verification,
)
from drawing_analyzer.verify import (
    VERIFY_SYSTEM_PROMPT,
    _is_verifiable,
    context_rect,
    default_verify_model,
    parse_verdict,
    verify_findings,
)

OPUS = "claude-opus-4-8"
PAGE_W, PAGE_H = 800.0, 600.0


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeUsage:
    def __init__(self, i=50, o=10):
        self.input_tokens = i
        self.output_tokens = o


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResp:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()


class _FakeClient:
    """Scripts a verdict by matching a marker embedded in the finding text."""

    def __init__(self, script: dict[str, str], *, default='{"verdict":"NOT_VISIBLE"}'):
        self.calls: list[dict] = []
        self._script = script
        self._default = default

        class _Msgs:
            def create(_self, **kw):
                self.calls.append(kw)
                probe = kw["messages"][0]["content"][0]["text"]
                for marker, verdict in self._script.items():
                    if marker in probe:
                        return _FakeResp(verdict)
                return _FakeResp(self._default)

        self.messages = _Msgs()


class _StatusError(Exception):
    def __init__(self, status_code, message=""):
        super().__init__(message or f"HTTP {status_code}")
        self.status_code = status_code


def _sheet(source="s.pdf"):
    ref = SheetRef(pdf_path=Path(source), page_index=0, source_name=source, page_count=1)
    ov = ImageTile(png_bytes=b"O", width_px=10, height_px=10, kind="overview")
    return RenderedSheet(
        ref=ref, overview=ov, tiles=[], page_width_pt=PAGE_W, page_height_pt=PAGE_H,
        rows=6, cols=6,
    )


def _finding(marker, *, status="EXACT", rect=(100.0, 100.0, 160.0, 114.0), source="s.pdf", verif=None):
    f = Finding(
        sheet_id="M-101", source_name=source, page_index=0, category="code",
        severity="high", text=marker, source_quote=marker,
        anchor=Anchor(status=status, rect_pdf=list(rect) if rect else None, method="exact"),
    )
    if verif is not None:
        f.verification = verif
    return f


def _crop_renderer(items):
    for finding, sheet, rect, dpi in items:
        yield finding, b"\x89PNG-crop"


def _run(findings, sheets=None, **kw):
    kw.setdefault("crop_renderer", _crop_renderer)
    kw.setdefault("sleep", lambda _s: None)
    return verify_findings(findings, sheets or [_sheet()], model=OPUS, **kw)


# --------------------------------------------------------------------------- #
# parse_verdict
# --------------------------------------------------------------------------- #


def test_parse_verdict_maps_the_three_outcomes():
    assert parse_verdict('{"verdict":"CONFIRMED","note":"clear"}') == ("VERIFIED", "clear")
    assert parse_verdict('{"verdict":"CONTRADICTED","note":"no"}') == ("REJECTED", "no")
    assert parse_verdict('{"verdict":"NOT_VISIBLE","note":"?"}') == ("UNCERTAIN", "?")


def test_parse_verdict_tolerates_fences_and_prose():
    assert parse_verdict('Here: ```json\n{"verdict": "CONFIRMED", "note": "ok"}\n```')[0] == "VERIFIED"


def test_parse_verdict_malformed_or_unknown_is_uncertain():
    assert parse_verdict("not json") == ("UNCERTAIN", "unparseable verdict")
    status, note = parse_verdict('{"verdict":"MAYBE"}')
    assert status == "UNCERTAIN" and "unrecognized" in note
    # An unrecognized verdict must never be REJECTED (don't cloud on a garble).
    assert status != "REJECTED"


# --------------------------------------------------------------------------- #
# context_rect / _is_verifiable
# --------------------------------------------------------------------------- #


def test_context_rect_enforces_minimum_and_clamps():
    # A tiny central anchor grows to the minimum window, centered.
    r = context_rect([390.0, 290.0, 410.0, 310.0], PAGE_W, PAGE_H)
    assert (r[2] - r[0]) == pytest.approx(350.0)   # min width
    assert (r[3] - r[1]) == pytest.approx(250.0)   # min height
    # A corner anchor clamps to the page (never negative, never past the edge).
    c = context_rect([5.0, 5.0, 15.0, 15.0], PAGE_W, PAGE_H)
    assert c[0] == 0.0 and c[1] == 0.0
    assert c[2] <= PAGE_W and c[3] <= PAGE_H


def test_is_verifiable_excludes_deterministic_and_unanchored():
    assert _is_verifiable(_finding("x")) is True
    assert _is_verifiable(_finding("x", status="UNANCHORED", rect=None)) is False
    assert _is_verifiable(
        _finding("x", verif=Verification(status="DETERMINISTIC", note="ref"))
    ) is False


def test_default_verify_model_env_override(monkeypatch):
    from drawing_analyzer.core.api_config import REVIEW_MODEL_DEFAULT

    monkeypatch.delenv("DRAWING_ANALYZER_VERIFY_MODEL", raising=False)
    assert default_verify_model() == REVIEW_MODEL_DEFAULT
    monkeypatch.setenv("DRAWING_ANALYZER_VERIFY_MODEL", "claude-sonnet-4-6")
    assert default_verify_model() == "claude-sonnet-4-6"


# --------------------------------------------------------------------------- #
# verify_findings — happy path
# --------------------------------------------------------------------------- #


def test_verify_maps_verdicts_and_tallies(tmp_path):
    client = _FakeClient({
        "conf": '{"verdict":"CONFIRMED","note":"ok"}',
        "contra": '{"verdict":"CONTRADICTED","note":"wrong"}',
        "novis": '{"verdict":"NOT_VISIBLE","note":"needs schedule"}',
        "garble": "totally not json",
    })
    findings = [_finding("conf"), _finding("contra"), _finding("novis"), _finding("garble")]
    res = _run(findings, client=client, evidence_dir=tmp_path / "evidence")

    got = {f.text: f.verification.status for f in findings}
    assert got == {"conf": "VERIFIED", "contra": "REJECTED",
                   "novis": "UNCERTAIN", "garble": "UNCERTAIN"}
    assert (res.verified, res.rejected, res.uncertain, res.skipped) == (1, 1, 2, 0)
    assert res.input_tokens == 200 and res.output_tokens == 40   # 4 * (50, 10)


def test_verify_writes_evidence_png_per_finding(tmp_path):
    ev = tmp_path / "evidence"
    findings = [_finding("conf"), _finding("contra")]
    _run(findings, client=_FakeClient({"conf": '{"verdict":"CONFIRMED"}'}), evidence_dir=ev)
    for f in findings:
        assert f.verification.evidence_png == f"evidence/{f.id}.png"
        assert (ev / f"{f.id}.png").exists()
        assert (ev / f"{f.id}.png").read_bytes() == b"\x89PNG-crop"


def test_verify_no_evidence_dir_leaves_path_empty():
    findings = [_finding("conf")]
    _run(findings, client=_FakeClient({"conf": '{"verdict":"CONFIRMED"}'}), evidence_dir=None)
    assert findings[0].verification.status == "VERIFIED"
    assert findings[0].verification.evidence_png == ""


def test_verify_skips_deterministic_and_unanchored():
    det = _finding("det", verif=Verification(status="DETERMINISTIC", note="ref"))
    unan = _finding("unan", status="UNANCHORED", rect=None)
    ok = _finding("conf")
    client = _FakeClient({"conf": '{"verdict":"CONFIRMED"}'})
    res = _run([det, unan, ok], client=client)
    assert det.verification.status == "DETERMINISTIC"   # untouched
    assert unan.verification.status == "SKIPPED"        # default, never called
    assert ok.verification.status == "VERIFIED"
    assert len(client.calls) == 1                       # only the verifiable one


def test_verify_skips_finding_with_no_matching_sheet():
    f = _finding("conf", source="other.pdf")            # no sheet for other.pdf
    res = _run([f], sheets=[_sheet("s.pdf")], client=_FakeClient({}))
    assert f.verification.status == "SKIPPED"
    assert "sheet not available" in f.verification.note
    assert res.skipped == 1


def test_verify_skips_when_crop_render_fails():
    def none_renderer(items):
        for finding, sheet, rect, dpi in items:
            yield finding, None
    f = _finding("conf")
    res = verify_findings([f], [_sheet()], client=_FakeClient({}), crop_renderer=none_renderer)
    assert f.verification.status == "SKIPPED" and "crop render failed" in f.verification.note


# --------------------------------------------------------------------------- #
# verify_findings — failure handling
# --------------------------------------------------------------------------- #


def test_verify_retries_transient_then_succeeds(tmp_path):
    state = {"n": 0}

    class _Retry:
        def __init__(self):
            class _M:
                def create(_s, **kw):
                    state["n"] += 1
                    if state["n"] == 1:
                        raise _StatusError(503, "overloaded")
                    return _FakeResp('{"verdict":"CONFIRMED","note":"ok"}')
            self.messages = _M()

    f = _finding("conf")
    _run([f], client=_Retry())
    assert f.verification.status == "VERIFIED"
    assert state["n"] == 2   # one transient, one success


def test_verify_permanent_error_is_uncertain_not_fatal():
    class _Boom:
        def __init__(self):
            class _M:
                def create(_s, **kw):
                    raise _StatusError(400, "bad request")
            self.messages = _M()
    f = _finding("conf")
    res = _run([f], client=_Boom())
    assert f.verification.status == "UNCERTAIN"   # kept, not skipped, not rejected
    assert res.uncertain == 1


def test_verify_fatal_auth_skips_remaining():
    class _Auth:
        def __init__(self):
            self.calls = 0

            class _M:
                def create(_s, **kw):
                    self.calls += 1
                    raise _StatusError(403, "forbidden")
            self.messages = _M()

    client = _Auth()
    findings = [_finding("a"), _finding("b"), _finding("c")]
    res = _run(findings, client=client, max_workers=1)
    assert all(f.verification.status == "SKIPPED" for f in findings)
    # The fatal error short-circuits the rest — not every finding is called.
    assert client.calls < len(findings)
    assert res.skipped == 3


def test_verify_client_unavailable_skips_all(monkeypatch):
    # Inject a fake client module (the real one needs the anthropic SDK) whose
    # factory raises, so the whole pass skips gracefully without any real call.
    import sys
    import types

    fake = types.ModuleType("drawing_analyzer.client")

    def _boom():
        raise RuntimeError("no api key configured")

    fake.get_client = _boom
    monkeypatch.setitem(sys.modules, "drawing_analyzer.client", fake)

    findings = [_finding("a"), _finding("b")]
    res = verify_findings(findings, [_sheet()], client=None, crop_renderer=_crop_renderer)
    assert all(f.verification.status == "SKIPPED" for f in findings)
    assert "no api key" in findings[0].verification.note
    assert res.skipped == 2


def test_verify_never_raises_on_unopenable_pdf(tmp_path):
    # The default renderer opens the source PDF; a missing/corrupt file must
    # degrade every crop to SKIPPED, not raise out of verify_findings (I-3).
    findings = [_finding("a"), _finding("b")]
    res = verify_findings(
        findings, [_sheet("does-not-exist.pdf")], client=_FakeClient({}),
        sleep=lambda _s: None,  # default (real) crop renderer -> tries to open the file
    )
    assert all(f.verification.status == "SKIPPED" for f in findings)
    assert res.skipped == 2


def test_verify_renderer_exception_skips_remaining_not_raises():
    def _boom_renderer(items):
        yield items[0][0], b"CROPPNG"   # first finding renders fine
        raise RuntimeError("renderer blew up")  # then the renderer dies

    findings = [_finding("a"), _finding("b"), _finding("c")]
    res = verify_findings(
        findings, [_sheet()], client=_FakeClient({}, default='{"verdict":"CONFIRMED"}'),
        crop_renderer=_boom_renderer, sleep=lambda _s: None,
    )
    # First is verified; the two the renderer never yielded are SKIPPED, counted.
    assert findings[0].verification.status == "VERIFIED"
    assert findings[1].verification.status == "SKIPPED"
    assert findings[2].verification.status == "SKIPPED"
    assert res.verified == 1 and res.skipped == 2


def test_verify_colliding_finding_ids_are_not_dropped_or_double_counted():
    # Two DISTINCT findings sharing a content-derived id (same sheet/category/
    # quote, different text) must each be verified exactly once — the default
    # crop renderer keys by position, not id.
    f1 = _finding("same-quote")
    f2 = _finding("same-quote")
    f2.text = "a different problem, same quoted line"
    assert f1.id == f2.id                       # collision (Phase-3 content id)
    res = _run([f1, f2], client=_FakeClient({}, default='{"verdict":"CONFIRMED"}'))
    assert f1.verification.status == "VERIFIED"
    assert f2.verification.status == "VERIFIED"
    assert res.verified == 2 and res.skipped == 0   # neither dropped nor doubled


def test_verify_empty_when_nothing_verifiable():
    det = _finding("det", verif=Verification(status="DETERMINISTIC", note="ref"))
    res = verify_findings([det], [_sheet()], client=_FakeClient({}), crop_renderer=_crop_renderer)
    assert (res.verified, res.rejected, res.uncertain, res.skipped) == (0, 0, 0, 0)


# --------------------------------------------------------------------------- #
# Concurrency + progress
# --------------------------------------------------------------------------- #


def test_verify_runs_concurrently():
    barrier = threading.Barrier(3, timeout=8)

    class _Barriered:
        def __init__(self):
            class _M:
                def create(_s, **kw):
                    barrier.wait()   # only releases if 3 calls are in flight at once
                    return _FakeResp('{"verdict":"CONFIRMED"}')
            self.messages = _M()

    findings = [_finding("a"), _finding("b"), _finding("c")]
    res = _run(findings, client=_Barriered(), max_workers=3)
    assert res.verified == 3   # all cleared the barrier => true concurrency


def test_verify_progress_reports_k_of_n():
    seen: list[tuple] = []
    findings = [_finding("a"), _finding("b")]
    _run(findings, client=_FakeClient({}, default='{"verdict":"CONFIRMED"}'),
         progress=lambda d, t, label: seen.append((d, t, label)))
    assert seen[-1][0] == 2 and seen[-1][1] == 2
    assert "Verifying finding" in seen[-1][2]


# --------------------------------------------------------------------------- #
# render_region (needs PyMuPDF)
# --------------------------------------------------------------------------- #


def test_render_region_and_iter_crops(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    from drawing_analyzer.render import iter_region_crops, render_region

    doc = pymupdf.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((100, 100), "RELIEF VALVE 165 PSI")
    path = tmp_path / "t.pdf"
    doc.save(str(path))

    png, w, h = render_region(doc[0], [80, 80, 400, 140], dpi=300)
    assert png[:4] == b"\x89PNG"
    assert w == pytest.approx(1334, abs=3)   # 320 pt * 300/72
    doc.close()

    # A big region is capped at the max long edge; a bad page index yields None.
    crops = dict(iter_region_crops(path, [
        ("ok", 0, [80, 80, 400, 140], 300),
        ("huge", 0, [0, 0, 792, 612], 300),
        ("bad", 9, [0, 0, 10, 10], 300),
    ]))
    assert crops["ok"][:4] == b"\x89PNG"
    assert crops["bad"] is None


def test_verify_request_shape_has_image_and_system():
    client = _FakeClient({}, default='{"verdict":"CONFIRMED"}')
    _run([_finding("conf")], client=client)
    kw = client.calls[0]
    assert kw["model"] == OPUS
    assert kw["system"] == VERIFY_SYSTEM_PROMPT
    assert "thinking" not in kw                     # verification thinking is OFF
    blocks = kw["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in blocks)
