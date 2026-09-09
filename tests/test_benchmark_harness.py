"""The release benchmark's offline fake must track the production transport.

`scripts/benchmark_drawing_analyzer.py --check` is a release gate: it asserts
that a warm run makes zero digest calls and rasterizes nothing, and that editing
one source re-digests exactly one sheet. Those assertions are only worth
anything if the fake client is actually being *called*.

It stopped being called, and nothing noticed. Two production changes landed
after the fake was written:

- `digest.stream_message` issues every digest / critique / review-plan /
  synthesis / focus request over `messages.stream` — unconditionally, not only
  above the ~21k cap that made streaming mandatory.
- `core.api_config.call_with_refusal_fallback` re-routes every Opus-5 real-time
  call through `client.beta.messages`.

The fake had neither, so every sheet raised `'OfflineClient' object has no
attribute 'beta'`. I-3 caught it per sheet and let the run finish, which is
exactly right for a real run and exactly wrong here: the benchmark reported
`digest_api_calls=0` everywhere and failed its gates with messages that read
like app regressions — "cached run still rasterized", "expected exactly 1
digest call, got 0" — while measuring nothing at all.

These tests fail the moment that happens again. They run the real pipeline
against the real fake and assert work was actually done, rather than asserting
the fake has particular attributes, because the attribute names are exactly what
production is free to change.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT / "scripts", _REPO_ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import benchmark_drawing_analyzer as bench  # noqa: E402

from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from drawing_analyzer.pipeline import extract_drawing_context  # noqa: E402


def _run(tmp_path, client, cache, *, sheets=2):
    paths = bench._build_offline_set(tmp_path, sheets)
    ctx = extract_drawing_context(
        paths, client=client, rows=2, cols=2, cache=cache, use_cache=True,
    )
    return ctx


def test_the_offline_fake_actually_serves_the_digest(tmp_path):
    """The whole benchmark rests on this one fact.

    Not "the fake has a .beta attribute" — production may rename that tomorrow.
    The assertion is that a real pipeline run reached the fake and came back
    with digested sheets and no errors.
    """
    client = bench.OfflineClient()
    ctx = _run(tmp_path, client, DigestCache(None, persist=False))

    assert client.digest_calls == 2, "the fake was never reached"
    assert ctx.ok_sheet_count == 2
    assert ctx.errors == [], f"pipeline errors: {ctx.errors}"


def test_a_transport_the_fake_cannot_answer_is_visible_as_errors(tmp_path):
    """The failure mode this file exists for, reproduced deliberately.

    A fake missing the beta namespace does not raise — I-3 turns it into one
    `ctx.errors` entry per sheet and the run still "succeeds" with zero digests.
    That is why the gate's own counters could not catch it, and why the check
    above asserts on work done rather than on a green exit code.
    """
    class _NoBeta(bench.OfflineClient):
        @property
        def beta(self):
            raise AttributeError("'_NoBeta' object has no attribute 'beta'")

    client = _NoBeta()
    ctx = _run(tmp_path, client, DigestCache(None, persist=False))

    assert client.digest_calls == 0
    assert ctx.ok_sheet_count == 0
    assert len(ctx.errors) == 2
    assert all("beta" in str(e) for e in ctx.errors)


def test_a_warm_run_makes_no_calls_and_renders_nothing(tmp_path):
    """The `standard-warm` gate, at test speed.

    Pins the property the benchmark asserts, so a cache regression fails here
    in seconds rather than only in a release run someone has to remember to do.
    """
    cache = DigestCache(None, persist=False)
    seed = bench.OfflineClient()
    _run(tmp_path, seed, cache)
    assert seed.digest_calls == 2

    warm = bench.OfflineClient()
    ctx = _run(tmp_path, warm, cache)

    assert warm.digest_calls == 0, "a warm run re-digested"
    assert warm.critique_calls == 0
    assert ctx.ok_sheet_count == 2
    assert ctx.errors == []


def test_the_non_beta_streaming_path_is_answered_too():
    """`messages.stream` is reached by every stage NOT routed to Opus 5.

    `call_with_refusal_fallback` only re-routes through `beta.messages` when the
    model is Opus 5. A Sonnet-routed streaming stage therefore lands on
    `client.messages.stream` directly, and a fake carrying only the beta proxy
    would fail those stages while the Opus ones sailed through — a partial
    outage that the standard scenario cannot see, since it is Opus end to end.

    Asserted directly rather than through a full exhaustive run: the point is
    the transport surface, and a targeted call names the missing attribute
    instead of surfacing it as one more swallowed `ctx.errors` entry.
    """
    from drawing_analyzer.core.api_config import MODEL_SONNET_5
    from drawing_analyzer.digest import stream_message

    client = bench.OfflineClient()
    resp = stream_message(client, {
        "model": MODEL_SONNET_5,
        "max_tokens": 1024,
        "system": "anything",
        "messages": [{"role": "user", "content": "hi"}],
    })
    assert resp is not None
    assert getattr(resp, "content", None), "the fake returned no content block"
