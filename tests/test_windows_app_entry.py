"""Regression checks for the PyInstaller Windows entry point."""
from __future__ import annotations

import builtins
import multiprocessing
import runpy
import sys
from pathlib import Path

import pytest


def test_frozen_entry_enables_multiprocessing_before_dispatch(monkeypatch):
    entry = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "app_entry.py"
    events: list[str] = []

    monkeypatch.setattr(multiprocessing, "freeze_support", lambda: events.append("freeze"))
    monkeypatch.setattr(
        builtins,
        "print",
        lambda *args, **kwargs: events.append("dispatch"),
    )
    monkeypatch.setattr(sys, "argv", [str(entry), "--version"])
    monkeypatch.delenv("DRAWING_ANALYZER_SELFCHECK_OUT", raising=False)

    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(entry), run_name="__main__")

    assert stopped.value.code == 0
    assert events == ["freeze", "dispatch"]
