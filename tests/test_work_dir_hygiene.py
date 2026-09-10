"""P9 item 46 — the ``drawing_qc_*`` work directories had no owner.

Three of them are created **lazily** (the verify, investigate and markup stages
each make one when the caller supplied no ``work_dir``), and nothing ever removed
them. They hold the high-DPI evidence crops, so on a set reviewed repeatedly they
are the largest thing the tool leaves behind — in ``%TEMP%``, invisible, forever.

Age-pruning on the way *in* rather than deleting at run end, and that is a design
decision: ``extract_drawing_context`` returns **before** the caller exports, and
the export *copies* the evidence out (DA-033), so a work dir deleted when the run
ends would destroy the crops before anything saved them.

Hermetic: these drive the pruner and the zero-sheet exit directly against real
temp directories. No PDF, no API, no key.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from drawing_analyzer import pipeline as P

_OLD = 40 * 3600            # comfortably past the 24h default
_PREFIX = P._WORKDIR_PREFIX


@pytest.fixture
def temp_root(monkeypatch):
    """A private temp root, so a real ``%TEMP%`` is never scanned or pruned."""
    root = Path(tempfile.mkdtemp(prefix="prune_root_"))
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(root))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _work_dir(root: Path, *, name: str = "", age: float = 0.0,
              nested_crop_age: float | None = None) -> Path:
    """A ``drawing_qc_*`` dir with an ``evidence/QC-001/leg-00.png`` inside it.

    ``age`` back-dates every path in the tree; ``nested_crop_age`` overrides the
    crop's own age, which is how a live run looks: a fresh file two levels down
    under a directory whose *own* mtime has not moved.
    """
    path = Path(tempfile.mkdtemp(prefix=name or _PREFIX, dir=root))
    crop_dir = path / "evidence" / "QC-001"
    crop_dir.mkdir(parents=True)
    crop = crop_dir / "leg-00__M-101_p1.png"
    crop.write_bytes(b"crop bytes")
    stamp = time.time() - age
    for target in (crop, crop_dir, crop_dir.parent, path):
        os.utime(target, (stamp, stamp))
    if nested_crop_age is not None:
        fresh = time.time() - nested_crop_age
        os.utime(crop, (fresh, fresh))
    return path


def test_a_leaked_work_dir_is_pruned(temp_root):
    leaked = _work_dir(temp_root, age=_OLD)
    assert P._prune_stale_work_dirs() == 1
    assert not leaked.exists()


def test_a_young_work_dir_is_left_alone(temp_root):
    young = _work_dir(temp_root, age=60)
    assert P._prune_stale_work_dirs() == 0
    assert young.exists()


def test_the_live_runs_own_dir_is_never_pruned(temp_root):
    """``keep`` wins over age — a long run must not delete its own crops."""
    mine = _work_dir(temp_root, age=_OLD)
    other = _work_dir(temp_root, age=_OLD)
    assert P._prune_stale_work_dirs(keep=mine) == 1
    assert mine.exists()
    assert not other.exists()


def test_an_empty_young_work_dir_is_left_alone(temp_root):
    """A work dir the current run has not written to yet has no entries at all.

    Every QC stage creates its dir and then works, so "empty and seconds old" is
    the normal state at the moment a *second* run starts. The nested recency scan
    cannot see age here — there is nothing inside to date — so the directory's own
    mtime has to be checked as well.
    """
    fresh = Path(tempfile.mkdtemp(prefix=_PREFIX, dir=temp_root))
    assert not any(fresh.iterdir())
    assert P._prune_stale_work_dirs() == 0
    assert fresh.exists()


def test_an_unreadable_entry_keeps_the_directory(temp_root, monkeypatch):
    """Fail safe: cannot date it, so do not delete it."""
    leaked = _work_dir(temp_root, age=_OLD)

    class _Blind:
        path = str(leaked / "evidence")
        name = "evidence"

        def stat(self, follow_symlinks=True):
            raise OSError("permission denied")

        def is_dir(self, follow_symlinks=True):
            return True

    class _Scan:
        def __enter__(self):
            return iter([_Blind()])

        def __exit__(self, *exc):
            return False

    real_scandir = os.scandir

    def only_this_dir(path):
        # Targeted: shutil.rmtree walks with os.scandir too, and a global patch
        # would make the deletion itself fail — the test would then pass because
        # nothing could be deleted rather than because nothing was chosen.
        if str(path) == str(leaked):
            return _Scan()
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", only_this_dir)
    assert P._prune_stale_work_dirs() == 0
    assert leaked.exists()


def test_an_unscannable_directory_keeps_the_directory(temp_root, monkeypatch):
    """The same fail-safe one level up: the directory itself will not open.

    Two branches, one rule — a directory whose contents cannot be dated is kept,
    whether the failure is on one entry or on the whole listing.
    """
    leaked = _work_dir(temp_root, age=_OLD)
    real_scandir = os.scandir

    def refuse(path):
        if str(path) == str(leaked):
            raise OSError("permission denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", refuse)
    # The count is the signal: rmtree(ignore_errors=True) would swallow its own
    # failure here, so a pruner that decided to delete would report having done so.
    assert P._prune_stale_work_dirs() == 0


def test_a_concurrent_run_writing_crops_is_not_pruned(temp_root):
    """The bug in the first version of this fix.

    A directory's mtime moves only when an entry is added *directly* in it, and
    the verifier writes to ``evidence/<QC-###>/<leg>.png`` — two levels down. So a
    work dir whose crop was written **0 seconds ago** but whose own mtime was 40
    hours old was pruned out from under the live run. A run can outlive the prune
    age (the batch collection bound alone is 24h), so this is reachable.
    """
    live = _work_dir(temp_root, age=_OLD, nested_crop_age=0)
    leaked = _work_dir(temp_root, age=_OLD)
    assert P._prune_stale_work_dirs() == 1
    assert live.exists(), "an in-use work dir was deleted"
    assert not leaked.exists()


def test_unrelated_temp_directories_are_never_touched(temp_root):
    """The glob is the whole safety story — it must not widen."""
    other_tool = _work_dir(temp_root, name="someone_elses_", age=_OLD)
    assert P._prune_stale_work_dirs() == 0
    assert other_tool.exists()


def test_a_stray_file_named_like_a_work_dir_is_ignored(temp_root):
    stray = temp_root / f"{_PREFIX}not_a_dir"
    stray.write_text("x", encoding="utf-8")
    os.utime(stray, (time.time() - _OLD, time.time() - _OLD))
    assert P._prune_stale_work_dirs() == 0
    assert stray.exists()


def test_a_symlink_is_never_followed(temp_root):
    """Otherwise a symlink in %TEMP% aims rmtree at whatever it points to."""
    real = Path(tempfile.mkdtemp(prefix="precious_", dir=temp_root))
    keep = real / "keep.txt"
    keep.write_text("do not delete", encoding="utf-8")
    # The TARGET is back-dated too: ``path.stat()`` follows a symlink, so a fresh
    # target would spare the link by age and hide whether the guard exists.
    stamp = time.time() - _OLD
    for target in (keep, real):
        os.utime(target, (stamp, stamp))
    link = temp_root / f"{_PREFIX}link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):          # pragma: no cover - no symlinks
        pytest.skip("this filesystem does not support symlinks")
    os.utime(link, (time.time() - _OLD, time.time() - _OLD), follow_symlinks=False)
    # ``rmtree(ignore_errors=True)`` already refuses a symlink, so the target is
    # safe either way; what the guard buys is an honest tally. Without it the run
    # log reports "pruned 1 stale work dir" having deleted nothing, and the next
    # person to chase disk usage is looking in the wrong place.
    assert P._prune_stale_work_dirs() == 0
    assert link.exists()
    assert (real / "keep.txt").exists()


def test_zero_disables_pruning_entirely(temp_root, monkeypatch):
    leaked = _work_dir(temp_root, age=_OLD)
    monkeypatch.setenv(P._WORKDIR_MAX_AGE_ENV, "0")
    assert P._prune_stale_work_dirs() == 0
    assert leaked.exists()


@pytest.mark.parametrize("raw", ["", "   ", "abc", "-5", "None", "1e", "24h"])
def test_a_garbage_age_override_falls_back_to_the_default(monkeypatch, raw):
    """A typo in an env var must not silently disable or invert the policy."""
    monkeypatch.setenv(P._WORKDIR_MAX_AGE_ENV, raw)
    seconds = P._workdir_max_age_seconds()
    if raw.strip() == "-5":
        assert seconds == 0.0, "a negative age is clamped, never negative"
    else:
        assert seconds == P._WORKDIR_MAX_AGE_HOURS * 3600.0


def test_the_age_override_is_read_at_call_time(monkeypatch):
    """Frozen at import, an env var set by the GUI before a run would be ignored."""
    monkeypatch.setenv(P._WORKDIR_MAX_AGE_ENV, "1")
    assert P._workdir_max_age_seconds() == 3600.0
    monkeypatch.setenv(P._WORKDIR_MAX_AGE_ENV, "2")
    assert P._workdir_max_age_seconds() == 7200.0


def test_pruning_never_raises_on_an_unreadable_temp_dir(monkeypatch):
    """I-3: nothing here may sink a run."""
    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "glob", boom)
    assert P._prune_stale_work_dirs() == 0


def test_the_scan_budget_keeps_rather_than_deletes(temp_root, monkeypatch):
    """Exhausting the bound must fail safe: keeping costs disk, deleting costs evidence."""
    leaked = _work_dir(temp_root, age=_OLD)
    monkeypatch.setattr(P, "_WORKDIR_SCAN_BUDGET", 0)
    assert P._prune_stale_work_dirs() == 0
    assert leaked.exists()


def test_the_zero_sheet_exit_removes_the_dir_it_created():
    """The twin of the ``block_reason`` exit, which already cleaned up.

    Selecting files that yield no readable pages left a work dir behind on every
    attempt — the same rule applied on one exit path and not the other. Asserted
    from the source, because reaching that return needs a PDF reader; the branch
    is three lines and its absence is the whole bug.
    """
    source = Path(P.__file__).read_text(encoding="utf-8")
    head, _, tail = source.partition("    if total == 0:")
    assert tail, "the zero-sheet early return moved"
    branch = tail.split("return DrawingContext", 1)[0]
    assert "_created_work_dir" in branch, branch
    assert "rmtree" in branch, branch
    # ...and its twin still does the same thing, so the two cannot drift apart
    # without this failing.
    assert "if _created_work_dir:" in head, (
        "the block_reason exit stopped cleaning up its work dir"
    )
    # Byte-identical cleanup on both exits, so the twins cannot drift.
    assert source.count("        if _created_work_dir:\n            import shutil") == 2
