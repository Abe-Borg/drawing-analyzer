"""Host-owned source identity and input inventory for the drawing set.

Two input PDFs that share a basename (``M-101.pdf`` in two different folders)
must never be confused for one another — a finding from one can otherwise be
anchored, verified, or clouded onto the other. The fix is a **host-generated**
identity that the model never sees and that does not depend on the filename:
each accepted input gets an opaque, run-local ``SRC-####`` id in input order.

``source_name`` (the basename) remains display metadata; ``source_id`` is the
authority every internal ``(source, page)`` lookup keys on
(:func:`drawing_analyzer.models.source_page_key`).

DA-001 (Phase 18A) added the pure ``SRC-####`` assignment. **Phase 18B** grows
this into the input inventory: :class:`SourceDocument` records classify every
selected path (``ACCEPTED`` / ``DUPLICATE`` / ``UNREADABLE`` / ``ENCRYPTED`` /
``EMPTY``) so a corrupt or locked file degrades individually and *visibly*
instead of silently vanishing, and a preflight bounds pathological/oversized
sets before they exhaust memory or disk. Phase 18C adds mid-run mutation
detection on top of the ``content_sha256`` captured here.

This module stays **dependency-free (no PyMuPDF)** — the identity, hashing, and
bounds logic work on paths and bytes. The one step that must open a PDF
(classifying encrypted / zero-page / corrupt and counting pages) lives in
:mod:`render` under the I-5 PyMuPDF isolation; it fills in the
:class:`SourceDocument` fields this module defines. ``source_id`` is assigned
over the **accepted** inputs in order, so :func:`render.list_sheets` and the
reviewed-PDF writer derive the same ids from the same accepted path list without
sharing a registry object.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable


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


# --------------------------------------------------------------------------- #
# Input inventory (Phase 18B, DA-002) — classify every selected path once, so a
# bad file degrades individually and visibly rather than silently vanishing.
# --------------------------------------------------------------------------- #

# SourceDocument.status values.
ACCEPTED = "ACCEPTED"
DUPLICATE = "DUPLICATE"      # same canonical path already accepted this run
UNREADABLE = "UNREADABLE"    # missing / permission-denied / corrupt / not a PDF
ENCRYPTED = "ENCRYPTED"      # password-required (distinct from plain-corrupt)
EMPTY = "EMPTY"              # opened, but zero pages
_REJECTED_STATUSES = frozenset({DUPLICATE, UNREADABLE, ENCRYPTED, EMPTY})


@dataclass
class SourceDocument:
    """One selected input path, classified (§6.1).

    ``pdf_path`` is internal only (never exported into a public artifact by
    default); ``display_name`` (the basename) is the user-facing label. An
    ``ACCEPTED`` doc carries the revision identity (``content_sha256`` /
    ``byte_size`` / ``initial_mtime_ns``) Phase 18C uses to detect mid-run
    mutation, plus ``page_count``. A rejected doc carries a sanitized ``error``
    and, for a ``DUPLICATE``, the ``duplicate_of`` source id.
    """

    source_id: str
    pdf_path: Path
    display_name: str
    input_order: int                    # 1-based position in the accepted stream (0 if rejected)
    status: str = UNREADABLE
    page_count: int = 0
    content_sha256: str = ""
    byte_size: int = 0
    initial_mtime_ns: int = 0
    error: str = ""
    duplicate_of: str = ""              # source_id of the first occurrence (DUPLICATE only)

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED

    def summary_line(self) -> str:
        """A user-facing one-liner (never leaks the absolute path)."""
        if self.accepted:
            return f"{self.display_name}: accepted ({self.page_count} page(s))"
        detail = self.error or self.status.lower()
        return f"{self.display_name}: {self.status} — {detail}"


@dataclass
class InputInventory:
    """The result of :func:`render.inspect_inputs`: every path, classified."""

    documents: list[SourceDocument] = field(default_factory=list)

    @property
    def accepted_documents(self) -> list[SourceDocument]:
        return [d for d in self.documents if d.accepted]

    @property
    def rejected_documents(self) -> list[SourceDocument]:
        return [d for d in self.documents if not d.accepted]

    @property
    def accepted_paths(self) -> list[Path]:
        return [d.pdf_path for d in self.accepted_documents]

    def error_lines(self) -> list[str]:
        """Sanitized one-liners for every rejected input (for ctx.errors / GUI)."""
        return [d.summary_line() for d in self.rejected_documents]

    def source_id_for(self, path: os.PathLike[str] | str) -> str:
        canon = canonical_path(path)
        for d in self.documents:
            if d.accepted and canonical_path(d.pdf_path) == canon:
                return d.source_id
        return ""


# --------------------------------------------------------------------------- #
# Stat-guarded content hash — the revision identity. If the file changes while
# we read it, the hash would describe a mixture of revisions; detect that and
# retry once from a stable state, else signal a changing file (§10.1).
# --------------------------------------------------------------------------- #

_HASH_CHUNK = 1 << 20


def _stat_tuple(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns)


def content_sha256(path: os.PathLike[str] | str) -> tuple[str, int, int]:
    """Return ``(sha256_hex, byte_size, mtime_ns)`` for ``path``.

    Compares stat data before and after hashing; if the file changed mid-read it
    retries once, then raises :class:`OSError` rather than register a hash that
    may span two revisions. Reads in bounded chunks so a large PDF never loads
    whole into memory.
    """
    p = str(path)
    last_exc: OSError | None = None
    for _ in range(2):
        try:
            before = _stat_tuple(p)
            h = hashlib.sha256()
            with open(p, "rb") as fh:
                while True:
                    chunk = fh.read(_HASH_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
            after = _stat_tuple(p)
            if before == after:
                return h.hexdigest(), before[0], before[1]
        except OSError as exc:
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise OSError(f"file changed while hashing: {Path(p).name}")


# --------------------------------------------------------------------------- #
# Preflight bounds (Phase 18B, DA-035) — fail visibly on pathological or
# oversized inputs before they exhaust memory or disk. Injectable seams so tests
# drive limit/disk failures without real giant files.
# --------------------------------------------------------------------------- #

def _env_num(name: str, default, cast):
    """Parse a numeric env override, falling back to ``default`` on a bad value.

    A blank or non-numeric override must never crash the app at import time (a
    config typo should degrade to the default, matching the worker-count env
    handling), so a failed parse is swallowed.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw.strip())
    except (TypeError, ValueError):
        return default


# A page far larger than any real sheet (200 in × 200 in = 14 400 pt) is almost
# certainly a malformed/attack box; render cost scales with its area.
MAX_PAGE_DIMENSION_PT = _env_num("DRAWING_ANALYZER_MAX_PAGE_PT", 20000.0, float)
# Above these, a run needs explicit confirmation rather than silently churning.
DEFAULT_MAX_SHEETS = _env_num("DRAWING_ANALYZER_MAX_SHEETS", 2000, int)
DEFAULT_MAX_FILES = _env_num("DRAWING_ANALYZER_MAX_FILES", 500, int)
# Rough per-sheet temp/output budget used by the pipeline's disk preflight
# (evidence crops, reviewed-PDF copies) — deliberately conservative.
EST_BYTES_PER_SHEET = _env_num("DRAWING_ANALYZER_EST_BYTES_PER_SHEET", 3 << 20, int)


def page_dimensions_ok(width_pt: float, height_pt: float) -> bool:
    """True when a page box is finite and within :data:`MAX_PAGE_DIMENSION_PT`."""
    import math

    for v in (width_pt, height_pt):
        if not math.isfinite(v) or v <= 0 or v > MAX_PAGE_DIMENSION_PT:
            return False
    return True


def check_set_limits(
    accepted_documents: list[SourceDocument],
    *,
    confirmed: bool = False,
    max_sheets: int = DEFAULT_MAX_SHEETS,
    max_files: int = DEFAULT_MAX_FILES,
) -> str | None:
    """Return a blocking reason when an accepted set is over the safe bound.

    A large *legitimate* set is not truncated silently — it requires explicit
    approval (``confirmed=True``), which the GUI/API surfaces as a confirm
    prompt. Returns ``None`` when the set is within bounds or confirmed.
    """
    if confirmed:
        return None
    n_files = len(accepted_documents)
    n_sheets = sum(d.page_count for d in accepted_documents)
    if n_files > max_files:
        return (
            f"{n_files} input files exceeds the {max_files}-file confirmation "
            "threshold; re-run with explicit confirmation to proceed."
        )
    if n_sheets > max_sheets:
        return (
            f"{n_sheets} sheets exceeds the {max_sheets}-sheet confirmation "
            "threshold; re-run with explicit confirmation to proceed."
        )
    return None


def check_work_disk(
    needed_bytes: int,
    target_dir: os.PathLike[str] | str,
    *,
    free_bytes_probe: Callable[[str], int] | None = None,
) -> str | None:
    """Return a blocking reason when ``target_dir`` lacks room for the run.

    ``free_bytes_probe`` is injectable (tests drive a disk-full condition
    without a real full disk); it defaults to :func:`shutil.disk_usage`. A probe
    failure is non-fatal (returns ``None``) — a real write failure downstream is
    still caught — so a quirky filesystem never blocks a legitimate run.
    """
    probe = free_bytes_probe
    if probe is None:
        import shutil

        def probe(d: str) -> int:  # type: ignore[misc]
            return shutil.disk_usage(d).free

    try:
        free = probe(str(target_dir))
    except Exception:  # noqa: BLE001 - probe failure must not block a run
        return None
    if free < needed_bytes:
        return (
            f"insufficient free space in the work/export location "
            f"(need ~{needed_bytes // (1 << 20)} MB, have {free // (1 << 20)} MB)"
        )
    return None
