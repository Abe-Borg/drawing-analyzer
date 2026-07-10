"""Host-owned source identity for the drawing set (DA-001, Phase 18A).

Two input PDFs that share a basename (``M-101.pdf`` in two different folders)
must never be confused for one another — a finding from one can otherwise be
anchored, verified, or clouded onto the other. The fix is a **host-generated**
identity that the model never sees and that does not depend on the filename:
each accepted input gets an opaque, run-local ``SRC-####`` id in input order.

``source_name`` (the basename) remains display metadata; ``source_id`` is the
authority every internal ``(source, page)`` lookup keys on
(:func:`drawing_analyzer.models.source_page_key`).

This module is deliberately small and dependency-free (no PyMuPDF): it assigns
identity from the *path list* alone. Phase 18B grows it into the full
``inspect_inputs`` inventory (encrypted / zero-page / corrupt classification,
content hashes, page counts); Phase 18C adds mid-run mutation detection. Keeping
the id-assignment pure means :func:`render.list_sheets` and the reviewed-PDF
writer can both derive the *same* ids from the *same* ordered path list without
threading a registry object through every call.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def canonical_path(path: os.PathLike[str] | str) -> str:
    """A private, normalized key for deciding whether two paths are one file.

    ``realpath`` + ``normcase`` so a relative and an absolute reference to the
    same file — and, on Windows, two case-different spellings — dedupe to one
    id. Never exported into a public artifact (it can be an absolute path); used
    only as an in-memory dedup key. Falls back to a plain normcase when the path
    cannot be resolved (e.g. it does not exist yet), so id assignment never
    raises.
    """
    p = str(path)
    try:
        return os.path.normcase(os.path.realpath(p))
    except OSError:
        return os.path.normcase(os.path.abspath(p))


def format_source_id(order: int) -> str:
    """The canonical ``SRC-####`` spelling for a 1-based input position."""
    return f"SRC-{order:04d}"


def assign_source_ids(paths: Iterable[os.PathLike[str] | str]) -> dict[str, str]:
    """Map each input path (by ``str(Path(p))``) to its host-owned ``SRC-####``.

    Deterministic in input order and **stable under dedup**: two distinct paths
    that share a basename receive *different* ids (the whole point), while the
    same canonical path supplied twice maps to the *same* id (so a duplicated
    selection doesn't fork identity). The returned dict is keyed by the path's
    ``str(Path(...))`` form so a caller iterating the same ``paths`` list — the
    sheet enumerators in :mod:`render`, the reviewed-PDF writer in
    :mod:`annotate` — looks up the id it needs by the same key.

    Because it is a pure function of the ordered path list, every stage that
    receives that list computes an identical mapping without sharing state.
    """
    canon_to_id: dict[str, str] = {}
    path_to_id: dict[str, str] = {}
    order = 0
    for raw in paths:
        key = str(Path(raw))
        canon = canonical_path(raw)
        sid = canon_to_id.get(canon)
        if sid is None:
            order += 1
            sid = format_source_id(order)
            canon_to_id[canon] = sid
        path_to_id[key] = sid
    return path_to_id
