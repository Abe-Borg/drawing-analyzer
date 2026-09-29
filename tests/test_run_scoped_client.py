"""A run's client is the one it was given: no stage re-reads the environment (G2).

Remediation WP-16.2. The GUI used to call ``extract_drawing_context`` with no
client, so every stage resolved one lazily through ``client.get_client()``,
which reads ``ANTHROPIC_API_KEY`` on each call and rebuilds its cached client
when the value changes. A GUI run called it 13-14 times (per sheet in the
digest, per critique read); an edit to the environment after the paid digest
sent every later stage to the new value, and an emptied one made them raise.
The GUI now builds one real client from the key snapshotted at Analyze and
passes it (``tests/test_gui_lifecycle.py`` covers that side).

These pin the pipeline side the GUI relies on, measured on every transport:
a real ``anthropic.Anthropic`` passed in serves every stage, the investigation
included; no lazy fallback is reached; the environment can change or vanish
mid-run without effect; and a real client keeps the set-level stage overlap
(a wrapper would not: ``_stage_overlap_enabled``). The client's resources are
the suite's fakes, so nothing leaves the machine.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("pymupdf")

import anthropic  # noqa: E402

import drawing_analyzer.batch_digest as BD  # noqa: E402
import drawing_analyzer.client as client_mod  # noqa: E402
import drawing_analyzer.pipeline as pl  # noqa: E402
from drawing_analyzer.digest_cache import DigestCache  # noqa: E402
from tests.fixtures.gauntlet import build_mini_set, mini_client  # noqa: E402
from tests.test_source_page_isolation import _Pipe  # noqa: E402

# Built at runtime: scripts/scan_secrets.py (run by CI) refuses a literal.
_KEY = "sk-ant-api03-" + "A" * 86 + "AA"
_KEY_B = "sk-ant-api03-" + "B" * 86 + "BB"

_TRANSPORTS = {
    "fast": (False, False),
    "batch": (True, False),
    "hybrid": (False, True),
    "economy": (True, True),
}


class _Answers(_Pipe):
    """``_Pipe`` (real time, batches, files) answering through the gauntlet's
    mini-set script, with one UNCERTAIN verdict so the investigation runs."""

    def __init__(self, requests: list[str]):
        super().__init__()
        self._requests = requests
        self._script = mini_client(verify_verdicts=(("VAV-3", "NOT_VISIBLE"),))

    def _reply(self, params):
        self._requests.append("request")
        return self._script._route(dict(params))


def _real_client(requests: list[str]) -> anthropic.Anthropic:
    """A real SDK client (its class decides the overlap) whose resources are
    fakes. ``messages``, ``beta`` and ``files`` are cached properties, so the
    instance attribute wins."""
    client = anthropic.Anthropic(api_key=_KEY)
    fake = _Answers(requests)
    client.messages = fake.messages
    client.beta = fake.beta
    client.files = fake.files
    return client


@pytest.fixture
def lazy_calls(monkeypatch):
    """Every ``get_client()`` the run reaches, by caller; each one raises."""
    calls: list[str] = []

    def _get_client():
        import sys

        calls.append(sys._getframe(1).f_code.co_name)
        raise AssertionError("a stage re-read the environment")

    monkeypatch.setattr(client_mod, "get_client", _get_client)
    monkeypatch.setenv("DRAWING_ANALYZER_UPLOAD_WORKERS", "1")
    monkeypatch.setattr(BD, "_run_in_background", lambda fn: fn())
    return calls


def _edit_after_digest(monkeypatch, edit):
    for name in ("_digest_sheets_concurrent", "_digest_sheets_via_batch"):
        real = getattr(pl, name)

        def _wrapped(*a, _real=real, **k):
            out = _real(*a, **k)
            edit()
            return out

        monkeypatch.setattr(pl, name, _wrapped)


@pytest.mark.parametrize("transport", sorted(_TRANSPORTS))
@pytest.mark.parametrize(
    "edit", ["env set to key B", "env removed"], ids=["env-key-b", "env-removed"],
)
def test_a_passed_client_serves_every_stage_whatever_the_environment_does(
    tmp_path, monkeypatch, lazy_calls, transport, edit,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)
    if edit == "env set to key B":
        _edit_after_digest(monkeypatch, lambda: os.environ.__setitem__("ANTHROPIC_API_KEY", _KEY_B))
    else:
        _edit_after_digest(monkeypatch, lambda: os.environ.pop("ANTHROPIC_API_KEY", None))
    use_batch, critique_batch = _TRANSPORTS[transport]
    work = tmp_path / "work"
    work.mkdir()
    requests: list[str] = []

    ctx = pl.extract_drawing_context(
        build_mini_set(tmp_path), client=_real_client(requests), rows=2, cols=2,
        cache=DigestCache(tmp_path / "cache.sqlite"), synthesize=True,
        use_batch=use_batch, critique_use_batch=critique_batch,
        focus="equipment coordination", qc_markups=True, qc_work_dir=work,
    )

    assert lazy_calls == []
    assert requests, "the fake client served nothing"
    statuses = {s.stage: s.status for s in ctx.stage_results}
    assert statuses["investigation"] == "COMPLETE"      # the escalation ran too
    assert ctx.qc_status == "COMPLETE", statuses
    assert not [e for e in ctx.errors if "ANTHROPIC_API_KEY" in e]


def test_a_real_client_keeps_stage_overlap_with_no_key_in_the_environment(
    tmp_path, monkeypatch,
):
    """The GUI's overlap decision does not move: ``client=None`` with a key in
    the environment answered True, and so does the real client it now passes.
    A wrapper would answer False (the plan's warning, measured)."""
    monkeypatch.delenv("DRAWING_ANALYZER_STAGE_OVERLAP", raising=False)
    cache = DigestCache(tmp_path / "cache.sqlite")

    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)
    before = pl._stage_overlap_enabled(max_workers=None, total=2, client=None, cache=cache)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    real = anthropic.Anthropic(api_key=_KEY)
    after = pl._stage_overlap_enabled(max_workers=None, total=2, client=real, cache=cache)

    class _Wrapper:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

    wrapped = pl._stage_overlap_enabled(
        max_workers=None, total=2, client=_Wrapper(real), cache=cache,
    )
    assert (before, after, wrapped) == (True, True, False)


def test_new_client_is_the_one_construction_get_client_uses(monkeypatch):
    """``get_client`` keeps its contract for library and script callers (it
    reads the environment on each call); it builds through ``new_client``,
    which the GUI uses for a run, so both send the same requests."""
    built: list[str] = []
    real_new = client_mod.new_client

    def _recording(api_key):
        built.append("key A" if api_key == _KEY else "other")
        return real_new(api_key)

    monkeypatch.setattr(client_mod, "new_client", _recording)
    monkeypatch.setattr(client_mod, "_cached_client", None)
    monkeypatch.setattr(client_mod, "_cached_key", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)

    first = client_mod.get_client()
    assert client_mod.get_client() is first            # cached per key
    assert built == ["key A"]
    assert isinstance(first, anthropic.Anthropic)
    same_key = real_new(_KEY).api_key == _KEY           # no value in a failure
    assert same_key

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY environment variable not set"):
        client_mod.get_client()
