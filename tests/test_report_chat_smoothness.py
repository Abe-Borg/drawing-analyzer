"""Headless-Chromium tests for the report chat's paced answer reveal (companion
to ``test_report_browser_security.py`` and ``test_report_chat_tools.py``).

Smoothness is a timing property, so only a real browser can prove it: the thing
under test is how many characters land per animation frame and how far the
messages pane scrolls per frame. A DOM emulator has no frames.

The stub delivers one SSE frame per network chunk on deliberately uneven gaps —
the way the API really behaves, a lump of text then a stall — so the burstiness
reaches the renderer intact. Without pacing the whole answer arrives in a
handful of ~120-character lurches and the pane snaps hundreds of pixels at once;
with it, both are a steady glide.

Hermetic: built in-process, loaded over ``file://``, ``fetch`` stubbed (no
network, no key). Skips cleanly when Playwright or its browser is unavailable.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
from datetime import datetime

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from drawing_analyzer import html_report as hr  # noqa: E402
from tests.fixtures.fake_context import FakeContext as _Ctx  # noqa: E402
from tests.fixtures.fake_context import FakeRef as _Ref  # noqa: E402
from tests.fixtures.fake_context import FakeSheet as _Sheet  # noqa: E402

pytestmark = pytest.mark.browser

NOW = datetime(2026, 7, 21, 8, 0)
KEY = "sk-ant-fake-not-real"

# Every block shape an answer really contains — headings, a loose list, a table,
# a fence, a quote, an ordered list — because the incremental repaint commits
# finished blocks and re-renders only the live tail, and the boundary rules
# differ per shape.
ANSWER = (
    "## Duct sizing conflicts\n\nThree sheets disagree on the main supply duct, and the "
    "disagreement propagates into the terminal-unit schedule.\n\n"
    "- **M-501** calls the main trunk 12 in round\n"
    "- **M-502** shows the same trunk at 14 in round\n"
    "- **M-601** schedules terminal units against a 14 in trunk\n\n"
    "The schedule below lists every affected run.\n\n"
    "| Sheet | Run | Called size | Sev |\n|---|---|---|---|\n"
    "| M-501 | SA-1 | 12 in | high |\n| M-502 | SA-1 | 14 in | high |\n"
    "| M-601 | SA-1 | 14 in | medium |\n\n"
    "The velocity math only closes at 14 in:\n\n"
    "```\nQ = 2400 cfm\nA(12in) = 0.785 sf  ->  3057 fpm\nA(14in) = 1.069 sf  ->  2245 fpm\n```\n\n"
    "> 2245 fpm is inside the 2500 fpm guideline for a main trunk; 3057 fpm is not.\n\n"
    "### Recommendation\n\n1. Confirm the trunk size against the load calc\n"
    "2. Reissue M-501 to match\n3. Re-check the terminal schedule on M-601\n\n"
    "This is the single highest-severity coordination item in the set, and it is the only "
    "one that touches three sheets at once, so it is worth resolving first.\n"
)

# Uneven delta sizes: the model does not hand over fixed-width chunks.
_DELTA_SIZES = [7, 3, 61, 4, 9, 120, 5, 6, 4, 38, 90, 3, 5, 7, 150, 4, 8, 25]


def _launch(p):
    try:
        return p.chromium.launch(headless=True)
    except PlaywrightError:
        root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
        for pat in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-linux64/chrome"):
            hits = sorted(glob.glob(os.path.join(root, pat)))
            if hits:
                return p.chromium.launch(headless=True, executable_path=hits[-1])
        raise


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            b = _launch(p)
        except Exception as exc:  # noqa: BLE001 - no browser here → skip, don't fail
            pytest.skip(f"headless Chromium unavailable: {exc}")
        yield b
        b.close()


def _bursty_sse(text: str) -> str:
    frames = [{"type": "content_block_start", "index": 0,
               "content_block": {"type": "text", "text": ""}}]
    i = k = 0
    while i < len(text):
        n = _DELTA_SIZES[k % len(_DELTA_SIZES)]
        k += 1
        frames.append({"type": "content_block_delta", "index": 0,
                       "delta": {"type": "text_delta", "text": text[i:i + n]}})
        i += n
    frames += [{"type": "content_block_stop", "index": 0},
               {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}]
    return "".join(f"data: {json.dumps(f)}\n\n" for f in frames)


# One SSE frame per network chunk, on uneven gaps (including real stalls), and
# honouring the AbortSignal so the Stop button is testable.
_FETCH_STUB = """
(function(){
  var enc = new TextEncoder();
  var frames = window.__SSE.split('\\n\\n').filter(function(s){ return s.trim(); })
                 .map(function(s){ return enc.encode(s + '\\n\\n'); });
  var gaps = [12, 5, 40, 8, 130, 6, 9, 22, 300, 7, 4, 60, 11, 5, 18, 90, 6, 4];
  // One-chunk mode: the whole response lands in a single read, so the download
  // finishes while the reveal is still far behind — the window where abort()
  // has nothing left to cancel.
  if(window.__SSE_ONECHUNK){ frames = [enc.encode(window.__SSE)]; gaps = [1]; }
  function abortErr(){
    var e = new Error('The user aborted a request.'); e.name = 'AbortError'; return e;
  }
  window.fetch = function(url, opts){
    var sig = opts && opts.signal, i = 0;
    var reader = { read: function(){
      if(sig && sig.aborted) return Promise.reject(abortErr());
      if(i >= frames.length) return Promise.resolve({done:true, value:undefined});
      return new Promise(function(res, rej){
        setTimeout(function(){
          if(sig && sig.aborted){ rej(abortErr()); return; }
          res({done:false, value: frames[i++]});
        }, gaps[i % gaps.length]);
      });
    }};
    return Promise.resolve({ok:true, status:200, body:{getReader:function(){ return reader; }}});
  };
})();
"""

# Sample the rendered character count and the scroll offset on every frame. The
# elements are looked up per tick because this runs before the DOM exists.
_PROBE = """
(function(){
  window.__samples = [];
  function tick(){
    var msgs = document.getElementById('da-chat-msgs');
    var md = document.querySelector('.da-ai .da-md');
    window.__samples.push([md ? md.textContent.length : 0, msgs ? msgs.scrollTop : 0]);
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();
"""

_SETTLED = ("() => { var b = document.getElementById('da-chat-send');"
            " return b && !b.disabled && document.querySelector('.da-user'); }")


def _ctx():
    return _Ctx(
        sheets=[_Sheet(_Ref("mech.pdf", 0, 1), text="duct schedule")],
        combined_text="duct schedule",
    )


def _page(browser, tmp_path, *, answer=ANSWER, probe=True, one_chunk=False, **ctx_kw):
    """A loaded report with the bursty stream armed. Short viewport so the
    messages pane is guaranteed to overflow and the autoscroll path runs."""
    doc = hr.build_html_report(_ctx(), source_names=["mech.pdf"], now=NOW,
                               api_key=KEY, embed_api_key=True)
    ctx = browser.new_context(viewport={"width": 1100, "height": 430}, **ctx_kw)
    pg = ctx.new_page()
    pg.add_init_script("window.__SSE = " + json.dumps(_bursty_sse(answer)) + ";")
    if one_chunk:                       # must precede the stub, which reads it
        pg.add_init_script("window.__SSE_ONECHUNK = true;")
    pg.add_init_script(_FETCH_STUB)
    if probe:
        pg.add_init_script(_PROBE)
    f = tmp_path / "report.html"
    f.write_text(doc, encoding="utf-8")
    pg.goto(f.as_uri())
    return pg, ctx


def _ask(pg, question="what conflicts are there?"):
    pg.click("#da-chat-fab")
    pg.fill("#da-chat-input", question)
    pg.click("#da-chat-send")


def _deltas(samples, idx):
    """Per-frame increments over the window where the answer was painting."""
    live = [s for s in samples if s[0] > 0]
    vals = [s[idx] for s in live]
    return [vals[i] - vals[i - 1] for i in range(1, len(vals))]


def _pct(values, q):
    """Nearest-rank percentile. The smoothness assertions are stated on a high
    percentile rather than the max because a single stalled frame — a GC pause,
    a loaded CI runner — is not a rendering defect, and the renderer's own
    per-frame ceilings already bound what one such frame can do."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


# --------------------------------------------------------------------------- #
# 1. The reveal is paced: many small frames, never a lurch.
# --------------------------------------------------------------------------- #


def test_answer_is_revealed_in_small_steady_steps(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path)
    try:
        _ask(pg)
        pg.wait_for_function(_SETTLED, timeout=20000)
        pg.wait_for_timeout(400)
        painted = [d for d in _deltas(pg.evaluate("window.__samples"), 0) if d > 0]
    finally:
        ctx.close()

    # Unpaced, this answer lands in ~7 frames of ~120 characters each; paced it
    # is ~110 frames averaging 8.
    assert len(painted) >= 25, f"answer painted in only {len(painted)} frames — not paced"
    assert statistics.median(painted) <= 25, (
        f"median {statistics.median(painted)} chars/frame is lumpy, not a glide")
    assert _pct(painted, 0.9) <= 40, (
        f"90th percentile frame painted {_pct(painted, 0.9)} chars — still lurching")
    # MAX_FRAME_CHARS is the renderer's own ceiling; nothing may exceed it, even
    # the frame that comes back from a stall.
    assert max(painted) <= 70, f"a single frame painted {max(painted)} chars"


# --------------------------------------------------------------------------- #
# 2. The pane follows the answer instead of teleporting to the bottom.
# --------------------------------------------------------------------------- #


def test_autoscroll_eases_instead_of_jumping(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path)
    try:
        _ask(pg)
        pg.wait_for_function(_SETTLED, timeout=20000)
        pg.wait_for_timeout(400)
        samples = pg.evaluate("window.__samples")
        moved = [d for d in _deltas(samples, 1) if d > 0]
        end = pg.evaluate("() => { var m = document.getElementById('da-chat-msgs');"
                          " return m.scrollHeight - m.clientHeight - m.scrollTop; }")
    finally:
        ctx.close()

    assert moved, "the pane never scrolled — the overflow case did not run"
    # Unpaced this is a single ~611px snap at the end of the turn.
    assert len(moved) >= 20, f"scroll moved in only {len(moved)} frames — still a jump"
    assert statistics.median(moved) <= 20, (
        f"median {statistics.median(moved)}px per frame is a lurch, not a glide")
    assert _pct(moved, 0.9) <= 45, (
        f"90th percentile frame scrolled {_pct(moved, 0.9)}px — still snapping")
    assert end <= 3, f"did not settle at the bottom ({end}px short)"


# --------------------------------------------------------------------------- #
# 3. The incremental repaint must not change WHAT is rendered. The committed
#    prefix is only sound where render(A) + render(B) === render(A + B), so a
#    bad block boundary would show up as markup that a straight replay of the
#    same turn does not produce.
# --------------------------------------------------------------------------- #


def test_paced_render_matches_the_replayed_transcript(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path, probe=False)
    try:
        _ask(pg)
        pg.wait_for_function(_SETTLED, timeout=20000)
        pg.wait_for_timeout(400)
        streamed = pg.evaluate("document.querySelector('.da-ai .da-md').innerHTML")
        pg.reload()                       # replay renders in one synchronous pass
        pg.wait_for_timeout(900)
        replayed = pg.evaluate(
            "document.querySelector('.da-ai .da-md')?.innerHTML || '(no replay)'")
    finally:
        ctx.close()

    assert "<table" in streamed and "<pre" in streamed and "<ul" in streamed, (
        "the fixture stopped covering the block shapes the split rules care about")
    assert streamed == replayed


# --------------------------------------------------------------------------- #
# 4. A reader who scrolls up mid-answer keeps their place — including when the
#    turn finishes, which used to yank them to the bottom.
# --------------------------------------------------------------------------- #


def test_scrolling_up_mid_answer_stops_the_follow(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path, probe=False)
    try:
        _ask(pg)
        pg.wait_for_timeout(900)          # let it start scrolling, then take over
        pg.evaluate("document.getElementById('da-chat-msgs').scrollTop = 0")
        pg.wait_for_timeout(600)
        during = pg.evaluate("document.getElementById('da-chat-msgs').scrollTop")
        pg.wait_for_function(_SETTLED, timeout=20000)
        pg.wait_for_timeout(400)
        after = pg.evaluate("document.getElementById('da-chat-msgs').scrollTop")
    finally:
        ctx.close()

    assert during < 40, f"the reader's scroll position was overridden ({during})"
    assert after < 40, f"the turn end yanked the reader to the bottom ({after})"


# --------------------------------------------------------------------------- #
# 5. Stop mid-stream: everything received stays on screen (hiding text that
#    arrived would be a lie), the turn is annotated, nothing keeps animating.
# --------------------------------------------------------------------------- #


def test_stop_commits_everything_that_arrived(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path, probe=False)
    try:
        _ask(pg)
        pg.wait_for_timeout(700)
        mid = pg.evaluate("document.querySelector('.da-ai .da-md').textContent.length")
        pg.click("#da-chat-stop")
        pg.wait_for_function(_SETTLED, timeout=10000)
        pg.wait_for_timeout(400)
        after = pg.evaluate("document.querySelector('.da-ai .da-md').textContent.length")
        note = pg.evaluate("document.querySelector('.da-ai .da-note')?.textContent || ''")
        waiting = pg.evaluate("document.querySelectorAll('.da-wait').length")
    finally:
        ctx.close()

    assert mid > 0, "nothing had rendered before the stop"
    assert after >= mid, f"aborting hid text that had already arrived ({mid} -> {after})"
    assert "Stopped" in note, f"the stopped turn was not annotated: {note!r}"
    assert waiting == 0, "the waiting indicator was left spinning"


# --------------------------------------------------------------------------- #
# 6. prefers-reduced-motion opts out of the pacing entirely.
# --------------------------------------------------------------------------- #


def test_reduced_motion_uses_the_instant_path(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path, reduced_motion="reduce")
    try:
        assert pg.evaluate("window.matchMedia('(prefers-reduced-motion: reduce)').matches")
        _ask(pg)
        pg.wait_for_function(_SETTLED, timeout=20000)
        pg.wait_for_timeout(400)
        text = pg.evaluate("document.querySelector('.da-ai .da-md').textContent")
        painted = [d for d in _deltas(pg.evaluate("window.__samples"), 0) if d > 0]
    finally:
        ctx.close()

    assert len(text) > 800, "the answer did not fully render on the unpaced path"
    # The debounce path paints in a handful of big steps — that is the point of
    # the opt-out, and it is what proves the pacer really was bypassed.
    assert len(painted) < 30, f"reduced motion still paced the reveal ({len(painted)} frames)"


# --------------------------------------------------------------------------- #
# 7. The waiting indicator covers time-to-first-token and never outlives it.
# --------------------------------------------------------------------------- #


def test_stop_ends_the_reveal_after_the_download_finished(browser, tmp_path):
    """The response can be fully received while the reveal is still catching up.
    ``abort()`` does nothing to a finished fetch, so Stop must end the reveal
    too — otherwise it sits inert for the whole drain, during which the turn is
    also uncommitted. A large answer makes that window long enough to measure."""
    big = ANSWER * 15                       # ~13k chars: seconds of drain
    pg, ctx = _page(browser, tmp_path, answer=big, probe=False, one_chunk=True)
    try:
        _ask(pg)
        # The whole response is already downloaded; wait for the reveal to be
        # visibly under way but still far behind it.
        pg.wait_for_function(
            "() => { var e = document.querySelector('.da-ai .da-md');"
            " return e && e.textContent.length > 200; }", timeout=20000)
        shown = pg.evaluate("document.querySelector('.da-ai .da-md').textContent.length")
        assert shown < len(big) * 0.9, "the answer revealed too fast to test the window"

        pg.click("#da-chat-stop")
        # Must settle on the Stop, not on the 5s drain backstop.
        pg.wait_for_function(_SETTLED, timeout=2500)
        text = pg.evaluate("document.querySelector('.da-ai .da-md').textContent")
    finally:
        ctx.close()

    # Everything that arrived stays: the whole answer had already been received,
    # so Stop commits it rather than truncating at whatever was on screen.
    # Compared against the rendered text, not the markdown source — the source is
    # longer by every syntax character the renderer consumes.
    assert len(text) > shown * 3, (
        f"Stop did not commit the rest of the answer ({shown} -> {len(text)} chars)")
    assert text.rstrip().endswith("worth resolving first."), (
        "the tail of the received answer was discarded")


def test_turn_settles_even_if_frames_stop_firing(browser, tmp_path):
    """A backgrounded tab fires no animation frames. The reveal drives the turn's
    completion, so without a timer backstop switching away mid-answer would leave
    the composer locked and the transcript unsaved until the reader came back.
    Starving rAF is exactly that condition."""
    pg, ctx = _page(browser, tmp_path, probe=False)
    try:
        _ask(pg)
        pg.evaluate("window.requestAnimationFrame = function(){ return 0; };")
        # polling="interval": wait_for_function polls on rAF by default, which is
        # the very thing being starved here — the default poller would hang too.
        # Timeout well past DRAIN_BACKSTOP_MS: the turn settles on the timer alone.
        pg.wait_for_function(_SETTLED, timeout=25000, polling=250)
        text = pg.evaluate("document.querySelector('.da-ai .da-md').textContent")
        waiting = pg.evaluate("document.querySelectorAll('.da-wait').length")
    finally:
        ctx.close()

    assert len(text) > 800, f"the answer was left partly revealed ({len(text)} chars)"
    assert waiting == 0, "the waiting indicator was left spinning"


def test_waiting_indicator_appears_then_clears(browser, tmp_path):
    pg, ctx = _page(browser, tmp_path, probe=False)
    try:
        pg.add_init_script(
            "(function(){ window.__sawWait = false;"
            " setInterval(function(){"
            "   if(document.querySelector('.da-ai .da-wait')) window.__sawWait = true;"
            " }, 10); })();")
        pg.reload()
        _ask(pg)
        pg.wait_for_function(_SETTLED, timeout=20000)
        pg.wait_for_timeout(400)
        saw = pg.evaluate("window.__sawWait")
        left = pg.evaluate("document.querySelectorAll('.da-wait').length")
    finally:
        ctx.close()

    assert saw, "no waiting indicator was shown while the answer had not started"
    assert left == 0, "the waiting indicator outlived the turn"
