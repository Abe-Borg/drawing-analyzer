"""Frozen-app entry point for the Windows PyInstaller build.

PyInstaller freezes a *script*, not a module, so this thin wrapper calls
``drawing_analyzer.gui.main``. It also adds two headless flags the release
workflow uses to smoke-test the frozen executable without opening a window:

    DrawingAnalyzer.exe --version     print the version and exit
    DrawingAnalyzer.exe --selfcheck   import the app's heavy modules — proving
                                      PyInstaller bundled every hidden import —
                                      and exit 0 (non-zero on any import error)

The GUI build is windowed (``console=False``), so ``sys.stdout`` may be ``None``
in the frozen app; ``_emit`` writes results to the file named by
``DRAWING_ANALYZER_SELFCHECK_OUT`` (set by CI) as well as printing when it can,
so the smoke step can read the outcome regardless.
"""
from __future__ import annotations

import multiprocessing
import os
import sys


def _emit(message: str) -> None:
    try:
        if sys.stdout is not None:
            print(message)
    except Exception:
        pass
    out = os.environ.get("DRAWING_ANALYZER_SELFCHECK_OUT")
    if out:
        try:
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(message + "\n")
        except OSError:
            pass


def _print_version() -> int:
    import drawing_analyzer

    _emit(drawing_analyzer.__version__)
    return 0


def _selfcheck() -> int:
    try:
        import drawing_analyzer
        from drawing_analyzer import pipeline  # noqa: F401 - proves the engine froze
        from drawing_analyzer.core import updates  # noqa: F401 - proves the updater froze
        import drawing_analyzer.gui  # noqa: F401 - pulls customtkinter + tkinterdnd2
    except Exception:
        import traceback

        _emit("SELFCHECK FAILED:\n" + traceback.format_exc())
        return 1
    _emit(f"DrawingAnalyzer {drawing_analyzer.__version__} selfcheck ok")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--version" in args:
        return _print_version()
    if "--selfcheck" in args:
        return _selfcheck()
    from drawing_analyzer.gui import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    # Required by PyInstaller before a frozen executable creates spawned worker
    # processes. Without this dispatch hook, a child can relaunch the GUI entry
    # point recursively instead of entering multiprocessing's worker bootstrap.
    multiprocessing.freeze_support()
    raise SystemExit(main())
