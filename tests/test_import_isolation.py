"""Enforce invariant I-5: only ``render.py`` and ``annotate.py`` import PyMuPDF.

The README's AGPL licensing story and the coordinate-model design both depend on
PyMuPDF being confined to exactly those two modules — ``anchor.py`` and
``tiling.py`` work on extracted word rectangles precisely to preserve it. A stray
``import pymupdf`` anywhere else silently breaks that boundary, so this test
fails loudly the moment it happens.

Static (AST) rather than runtime: importing ``render`` legitimately pulls
PyMuPDF into ``sys.modules``, which would mask a second importer. Scanning each
source file's import statements answers the real question — *which modules
declare the dependency* — hermetically, with no PyMuPDF install required.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent / "src" / "drawing_analyzer"
_PYMUPDF_NAMES = {"pymupdf", "fitz"}
# The two deliberate importers (I-5, CLAUDE.md).
_ALLOWED = {"render.py", "annotate.py"}


def _imports_pymupdf(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _PYMUPDF_NAMES:
                    return True
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _PYMUPDF_NAMES:
                return True
    return False


def test_only_render_and_annotate_import_pymupdf():
    offenders = []
    for path in sorted(_PKG_ROOT.rglob("*.py")):
        if _imports_pymupdf(path.read_text(encoding="utf-8")):
            rel = path.relative_to(_PKG_ROOT).as_posix()
            if path.name not in _ALLOWED:
                offenders.append(rel)
    assert not offenders, (
        "PyMuPDF (I-5) must be imported only by render.py / annotate.py; "
        f"found imports in: {offenders}"
    )


def test_the_blessed_importers_actually_import_it():
    # Guard against the scan silently passing because it stopped detecting the
    # import at all (e.g. a refactor that hid it behind an indirection).
    for name in _ALLOWED:
        src = (_PKG_ROOT / name).read_text(encoding="utf-8")
        assert _imports_pymupdf(src), f"{name} should import PyMuPDF but the scan missed it"
