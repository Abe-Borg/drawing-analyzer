# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for the Drawing Analyzer Windows desktop app.

Build (on Windows, from the repo root) with:

    pip install -e ".[gui]" pyinstaller
    pyinstaller packaging/windows/drawing-analyzer.spec --noconfirm --clean

Output: ``dist/DrawingAnalyzer/`` (a folder containing ``DrawingAnalyzer.exe``
plus its bundled interpreter and dependencies). ``packaging/windows/installer.iss``
wraps that folder into ``DrawingAnalyzerSetup.exe``.

The spec is exec'd by PyInstaller with globals like ``Analysis``/``PYZ``/``EXE``/
``COLLECT``/``SPECPATH`` injected — that is why linters flag "undefined name"
here; the file is intentionally outside ``src``/``tests``/``scripts`` so the
repo's ruff gate never sees it.

One-folder (not one-file) is deliberate: it starts faster, updates more
reliably, and trips antivirus far less than a self-extracting one-file exe —
and the Inno Setup installer makes it a normal double-click "install" for the
user regardless.
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = []
binaries = []
hiddenimports = []

# customtkinter ships theme JSON assets; tkinterdnd2 ships the native tkdnd
# library — both must be collected or the app renders wrong / drag-and-drop
# fails to load at runtime.
for _pkg in ("customtkinter", "tkinterdnd2"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# tiktoken discovers its encodings through the ``tiktoken_ext`` namespace
# package via dynamic import — a classic PyInstaller miss.
hiddenimports += collect_submodules("tiktoken_ext")
hiddenimports += ["tiktoken_ext.openai_public"]

# keyring resolves its backend (Windows Credential Manager) dynamically; bundle
# every backend plus the metadata it reads to enumerate them.
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += ["keyring.backends.Windows"]

# Distribution metadata read at runtime. Including our own means
# ``importlib.metadata.version('drawing-analyzer')`` keeps working in the frozen
# app (the run manifest reports it), matching the source install.
for _dist in ("drawing-analyzer", "anthropic", "keyring", "tiktoken"):
    try:
        datas += copy_metadata(_dist)
    except Exception:
        # A missing dist here is non-fatal — the app still runs; only the
        # metadata-derived version string would fall back.
        pass

# Package data (the profiles dir ships even though it is empty by design) plus
# any dynamically imported submodules of the app itself.
_d, _b, _h = collect_all("drawing_analyzer")
datas += _d
binaries += _b
hiddenimports += _h

a = Analysis(
    [os.path.join(SPECPATH, "app_entry.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Test-only / dev-only packages must never be pulled into the shipped app.
    excludes=["pytest", "playwright", "_pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DrawingAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed GUI app — no console window behind it
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # drop an .ico here (icon="app.ico") once one exists
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DrawingAnalyzer",
)
