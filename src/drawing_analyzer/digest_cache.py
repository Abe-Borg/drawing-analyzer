"""Persistent, content-keyed cache for per-sheet drawing digests.

A digest is the dominant cost in the drawing pipeline — one Opus 4.8 vision
request per sheet (image tokens + minutes of latency). The result is
deterministic given the rendered sheet images + the model + the digest prompt +
the request params, so re-running a set (after editing one sheet, or just
re-opening the project) should not re-pay for the sheets that didn't change.

Persistent caches use a transactional SQLite/WAL store.  Older releases wrote
one JSON object and replaced the whole file on every ``put``; that made a cold
multi-sheet run rewrite an ever-growing cache many times.  The first open of a
legacy JSON cache migrates its current-schema entries in place, atomically, so
existing ``DRAWING_ANALYZER_CACHE_PATH`` values remain valid even when their
filename ends in ``.json``.

Thread-safe by design: ``digest_sheet`` calls may run concurrently (the parallel
dispatch follow-up), so each instance guards its connection with a lock while
SQLite coordinates transactions across instances and processes.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Bumped to 2 when the cache entry gained a serialized ``findings`` list (Phase
# 3); to 3 for the two-level key (Phase 9) — a digest is now also stored under a
# cheap *pre-render* key (``digest_cache_key_level1``) so an unchanged sheet is
# recognized before rendering and skips rasterization entirely. Blank-tile
# suppression also changed the rendered image set, so the old PNG-bytes (level-2)
# keys shift too. The version folds into every key, so every pre-v3 entry is
# discarded on load and re-digested once. Bumped to 4 (Phase 18A, DA-001): a
# cached ``Finding``/``NumericClaim`` now carries a ``source_id`` and its content
# ``id`` folds source identity in, so pre-v4 entries (which lack it and would be
# rebound to a mismatched id) are discarded on load and re-digested once. Bumped to
# 5 (Phase 19B, DA-004): the level-1 render identity was rebased on the whole
# source's ``content_sha256`` + the canonical coordinate space + the renderer
# environment (the old per-page object-graph fingerprint missed page rotation,
# CropBox origin, and rendered annotation appearance streams), and a critique
# level-1 key was added — so every pre-v5 level-1 / critique entry must miss once
# rather than serve a stale, possibly wrong-space digest. Bumped to 6 (Phase 22):
# a stored ``Finding`` gained ``confidence`` and ``prose_item_ids``; the critique
# cache entry now records ``requested_runs`` / ``completed_runs``; and the parser
# was rebuilt (a truncated/unclosed findings block is now recognised and stripped),
# so a pre-v6 entry — parsed under the old rules or lacking the new fields — must
# miss once and be re-derived rather than served as current. Bumped to 7 (Phase 25):
# the tile contract changed (the model now returns ``tile_label`` and a legacy
# ``tile`` array is read as explicit zero-based, §17.1) and a stored
# ``Verification`` gained ``computation_method`` / ``operand_origin`` (§17.5), so a
# pre-v7 entry — cached under the old tile parse or lacking the provenance fields —
# must miss once and be re-derived rather than served as current. Bumped to 8 for
# two independent reasons landing together: (a) a stored ``Finding`` gained
# ``recommended_action`` and the digest/critique prompts now request it, so a
# pre-v8 entry would serve action-less findings; and (b) the digest request can
# now carry an uploaded project-specifications block (folded into
# ``digest_cache_key``/``digest_cache_key_level1`` via a new ``specs`` param,
# mirroring ``focus``), and the request's system prompt may switch shape (plain
# string -> cached content-block list). A pre-v8 entry predates both and must
# miss once and be re-digested.
_SCHEMA_VERSION = 8

# Storage format and concurrency settings are intentionally separate from the
# content schema above.  ``_SCHEMA_VERSION`` invalidates cached model results;
# ``_DB_FORMAT_VERSION`` describes only the SQLite tables that hold them.
_DB_FORMAT_VERSION = 1
_SQLITE_HEADER = b"SQLite format 3\x00"
_BUSY_TIMEOUT_SECONDS = 30.0
_INIT_LOCK_TIMEOUT_SECONDS = 30.0
_STALE_INIT_LOCK_SECONDS = 10 * 60.0

_FALSEY = {"0", "false", "no", "off", ""}


def _env_truthy(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in _FALSEY


def default_cache_path() -> Path:
    """On-disk digest-cache location.

    Overridable via ``DRAWING_ANALYZER_CACHE_PATH`` (``~`` and ``$VAR``
    expanded); defaults to ``~/.drawing_analyzer/drawing_digest_cache.json``,
    alongside the verification cache.  The legacy filename is retained for
    compatibility; persistent contents are SQLite after first open.
    """
    override = os.environ.get("DRAWING_ANALYZER_CACHE_PATH")
    if override and override.strip():
        return Path(os.path.expandvars(os.path.expanduser(override.strip())))
    return Path.home() / ".drawing_analyzer" / "drawing_digest_cache.json"


def persistence_enabled() -> bool:
    """Whether the default digest cache persists to disk (default on)."""
    return _env_truthy(os.environ.get("DRAWING_ANALYZER_CACHE_PERSIST"), default=True)


def digest_cache_key(
    sheet: Any,
    *,
    model: str,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
    focus: str | None = None,
    specs: str | None = None,
    sheet_text: str | None = None,
) -> str:
    """Content-address one sheet's digest request.

    The rendered images are a model input, so hashing them captures the page
    content *and* every tiling parameter at once (different rows / cols / overlap
    → different crops → different bytes → different key). Folding in the model,
    prompt fingerprint, and output-shaping params means a model swap or a prompt
    edit re-digests rather than serving a stale cached read.

    ``sheet_text`` is the sheet's verbatim vector text layer, now sent in the
    prompt as a *second* model input. It is normally implied by the pixels (both
    derive from the same page), but not always: a scanned sheet's hidden OCR
    layer can be corrected/regenerated **without changing the rendered pixels**,
    so the text must be folded into the key too or a corrected re-run would serve
    the stale digest. Folded **only when non-empty**, so a text-free (raster)
    sheet's key is unaffected — its rendered pixels already key it, and empty
    text ⟺ raster render target, which changes the pixels anyway.

    ``focus`` carries the per-run focus prompt fragment
    (:func:`drawing_analyzer.digest.focus_cache_fragment`) when one is set. It is
    folded in **only when non-empty**, so a no-focus key is byte-identical to a
    key produced before the focus feature existed — pre-existing cache entries
    stay valid — while any focus (or a change to it) re-digests.

    ``specs`` carries the uploaded project-specifications prompt fragment
    (:func:`drawing_analyzer.digest.specs_cache_fragment`) when specs are
    attached — folded in **only when non-empty**, same rationale as ``focus``,
    and independent of it (a run can vary focus and specs on separate axes).
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_tokens={int(max_tokens)}",
        f"effort={effort or ''}",
        f"thinking={'1' if use_thinking else '0'}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    if focus:
        h.update(f"focus={focus}".encode("utf-8"))
        h.update(b"\x00")
    if specs:
        h.update(f"specs={specs}".encode("utf-8"))
        h.update(b"\x00")
    if sheet_text:
        h.update(b"sheet_text=")
        h.update(sheet_text.encode("utf-8"))
        h.update(b"\x00")
    h.update(sheet.overview.png_bytes)
    for tile in sheet.tiles:
        h.update(tile.png_bytes)
    return h.hexdigest()


def digest_cache_key_level1(
    render_identity: str,
    *,
    model: str,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
    focus: str | None = None,
    specs: str | None = None,
) -> str:
    """Content-address one sheet's digest **before rendering** (Phase 9, level-1).

    The dominant cost of a re-run is rasterization (~4.5 s/sheet, ~2.5 min for a
    33-sheet set). A digest is deterministic given the rendered images, so if the
    images *would* be byte-identical we can serve the cached digest without ever
    rendering. ``render_identity`` is exactly that "would the images match"
    fingerprint, produced from cheap page access alone
    (:func:`drawing_analyzer.render.sheet_render_identity`): the PyMuPDF version,
    grid + overlap + render target, the blank-suppression mode, and a conservative
    hash of every page dependency that can affect rendered pixels or extracted text
    (with whole-source fallback when isolation is uncertain).

    This folds the *same* request/model params as :func:`digest_cache_key` around
    that identity, plus a ``level=1`` namespace tag so a level-1 key can never
    collide with a level-2 (PNG-bytes) key. On a hit the pipeline skips rendering;
    on a miss it renders, computes the level-2 key for continuity, and stores the
    fresh digest under **both**.
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "level=1",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_tokens={int(max_tokens)}",
        f"effort={effort or ''}",
        f"thinking={'1' if use_thinking else '0'}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    if focus:
        h.update(f"focus={focus}".encode("utf-8"))
        h.update(b"\x00")
    if specs:
        h.update(f"specs={specs}".encode("utf-8"))
        h.update(b"\x00")
    h.update(b"render_identity=")
    h.update(render_identity.encode("utf-8"))
    h.update(b"\x00")
    return h.hexdigest()


def critique_cache_key_level1(
    render_identity: str,
    *,
    model: str,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
    runs: int,
    profiles_key: str | None = None,
) -> str:
    """Content-address one sheet's *critique* **before rendering** (Phase 19B, §11.5).

    The critique reads the same rendered images the digest does, so an unchanged
    exhaustive re-run would otherwise have to rasterize every sheet merely to
    compute the level-2 (PNG-bytes) :func:`critique_cache_key` and discover the
    critique was already cached — contradicting the warm-run fast path. This keys
    the critique on the *same* pre-render ``render_identity``
    (:func:`drawing_analyzer.render.sheet_render_identity`) the digest level-1 key
    uses, plus the critique's own request params — the critique prompt version, the
    self-consistency ``runs`` count (a one-read and a two-read merge differ), and the
    profile fingerprint (Phase 12; selecting or editing a profile re-critiques). The
    ``stage=critique level=1`` namespace tags keep it from ever colliding with the
    digest level-1 key or the level-2 critique key. On a hit the pipeline serves the
    merged critique with neither a render nor an API call; on a miss it renders,
    critiques, and stores under this key too (store-under-both).

    ``profiles_key`` is folded **only when non-empty**, so a no-profiles critique
    level-1 key stays byte-identical to a run that never selected one.
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "stage=critique",
        "level=1",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_tokens={int(max_tokens)}",
        f"effort={effort or ''}",
        f"thinking={'1' if use_thinking else '0'}",
        f"runs={int(runs)}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    if profiles_key:
        h.update(b"profiles=")
        h.update(profiles_key.encode("utf-8"))
        h.update(b"\x00")
    h.update(b"render_identity=")
    h.update(render_identity.encode("utf-8"))
    h.update(b"\x00")
    return h.hexdigest()


def critique_cache_key(
    sheet: Any,
    *,
    model: str,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
    runs: int,
    sheet_text: str | None = None,
    profiles_key: str | None = None,
) -> str:
    """Content-address one sheet's *critique* (Phase 11) — a separate model read
    from the digest, over the same images.

    Mirrors :func:`digest_cache_key` (the rendered images key the page content
    and every tiling parameter at once, and a non-empty ``sheet_text`` is folded
    in so a corrected text layer re-critiques even when the pixels are unchanged),
    but adds a ``stage=critique`` namespace tag, the critique prompt fingerprint,
    and the self-consistency ``runs`` count — a one-run critique and a two-run
    merge are different results. The distinct stage tag and prompt version mean a
    critique key can never collide with a digest key over the same images. The
    *merged* critique findings are cached under this key, so a re-run skips the
    model calls; the run-to-run sampling variance the merge feeds on is not itself
    reproducible, so only the merged outcome is stored (never an individual run).

    ``profiles_key`` (Phase 12) is the fingerprint of the review profiles injected
    into the critique prompt (:func:`drawing_analyzer.profiles.profiles_cache_fragment`
    — sorted ``name@version@hash`` triples). Folded in **only when non-empty**, so
    a no-profiles critique key stays byte-identical to a pre-profiles one (existing
    entries valid), while selecting a profile — or editing one — re-critiques.
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "stage=critique",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_tokens={int(max_tokens)}",
        f"effort={effort or ''}",
        f"thinking={'1' if use_thinking else '0'}",
        f"runs={int(runs)}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    if sheet_text:
        h.update(b"sheet_text=")
        h.update(sheet_text.encode("utf-8"))
        h.update(b"\x00")
    if profiles_key:
        h.update(b"profiles=")
        h.update(profiles_key.encode("utf-8"))
        h.update(b"\x00")
    h.update(sheet.overview.png_bytes)
    for tile in sheet.tiles:
        h.update(tile.png_bytes)
    return h.hexdigest()


def identity_cache_key(
    corpus_hash: str,
    *,
    model: str,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
) -> str:
    """Content-address one run's *set identity* (Phase A §20.1).

    ``corpus_hash`` is the sha256 of the exact built identity corpus (already
    deterministic — page-ordered, budgeted), so the same set re-identifies for
    free and any content/prompt/param change re-runs. The ``stage=identity``
    namespace tag keeps this from ever colliding with digest/critique keys, so
    adding it needs no ``_SCHEMA_VERSION`` bump (nothing stored under existing
    keys changes shape). Keeping the identity — and therefore the model-authored
    review plan derived from it — warm-run stable is what protects the critique
    ``profiles_key`` cache economics.
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "stage=identity",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_tokens={int(max_tokens)}",
        f"effort={effort or ''}",
        f"thinking={'1' if use_thinking else '0'}",
        f"corpus={corpus_hash or ''}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def review_plan_cache_key(
    corpus_hash: str,
    identity_hash: str,
    *,
    model: str,
    prompt_version: str,
    max_tokens: int,
    effort: str | None,
    use_thinking: bool,
    max_items: int,
) -> str:
    """Content-address one run's *model-authored review plan* (Phase A §20.2).

    Keyed on the exact planner corpus AND the identity it consumed (a changed
    identity must re-plan even over identical digests), plus the request params
    and the total-items cap (a different cap yields a different plan). Same
    namespace-isolation rationale as :func:`identity_cache_key` — no
    ``_SCHEMA_VERSION`` bump. A stable cached plan is what keeps the critique's
    ``profiles_key`` byte-identical across warm runs, preserving the Phase 19B
    cached-critique fast path.
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "stage=review_plan",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_tokens={int(max_tokens)}",
        f"effort={effort or ''}",
        f"thinking={'1' if use_thinking else '0'}",
        f"max_items={int(max_items)}",
        f"identity={identity_hash or ''}",
        f"corpus={corpus_hash or ''}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def citation_cache_key(
    payload_hash: str,
    *,
    model: str,
    prompt_version: str,
    max_uses: int,
) -> str:
    """Content-address one *citation request chunk*'s verdicts (Phase B).

    ``payload_hash`` is the sha256 of the exact request payload — the ref
    string, the chunk's normalized claim texts in request order, and the
    editions/jurisdiction context lines — so an identity change, a reworded
    claim, or different chunking all miss. ``max_uses`` (the per-request
    web-search budget) and the prompt version ride the key: verdicts searched
    under a different budget or prompt are different verdicts. Same
    namespace-isolation rationale as :func:`identity_cache_key` — the
    ``stage=citation`` tag means no ``_SCHEMA_VERSION`` bump. Entries carry a
    ``checked_at`` timestamp the CALLER compares against its TTL (this module
    stays time-blind; the I-7 carve-out is documented in
    :mod:`drawing_analyzer.citation_check`).
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "stage=citation",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_uses={int(max_uses)}",
        f"payload={payload_hash or ''}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def investigation_cache_key(
    payload_hash: str,
    *,
    model: str,
    prompt_version: str,
    max_rounds: int,
) -> str:
    """Content-address one investigation's *concluded* verdict (Phase C).

    ``payload_hash`` is the sha256 of the investigated finding's identity
    (id/text/quote/category/severity/anchor rect/prior verdict note) plus the
    caller's whole-set fingerprint — the tools can roam every sheet, so the
    whole set is an input and any source edit misses. ``max_rounds`` rides the
    key: a verdict reached under a different evidence budget is a different
    verdict. Only clean conclusions are admitted (never budget-capped/garbled
    outcomes), and a warm hit deterministically REPLAYS the stored tool trace
    (re-render + sha-compare) so the evidence bytes exist on disk this run —
    a mismatch falls back to a live investigation. No TTL, unlike the citation
    cache: citation's ground truth drifts with the live web, while every
    investigation input is folded into this key. Same namespace-isolation
    rationale as :func:`identity_cache_key` — the ``stage=investigation`` tag
    means no ``_SCHEMA_VERSION`` bump.
    """
    h = hashlib.sha256()
    for part in (
        f"schema={_SCHEMA_VERSION}",
        "stage=investigation",
        f"model={model or ''}",
        f"prompt={prompt_version or ''}",
        f"max_rounds={int(max_rounds)}",
        f"payload={payload_hash or ''}",
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _serialize_entry(value: dict) -> str:
    """Serialize one cache row without coupling unrelated writes together."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _read_legacy_json(path: Path) -> dict[str, dict]:
    """Read a pre-SQLite cache defensively.

    Only entries from the current content schema are eligible for migration.
    This preserves the old loader's fail-closed behavior: malformed files,
    stale schemas, and non-dict row values all become cache misses.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("_schema_version") != _SCHEMA_VERSION:
        return {}
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {str(key): dict(value) for key, value in entries.items() if isinstance(value, dict)}


def _is_sqlite_database(path: Path) -> bool:
    try:
        with path.open("rb") as fp:
            return fp.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


@contextmanager
def _initialization_lock(path: Path) -> Iterator[None]:
    """Serialize first-open creation/migration across processes.

    Normal reads and writes are coordinated by SQLite.  A tiny adjacent lock is
    needed only before SQLite exists, when several application processes could
    otherwise try to replace the same legacy JSON file concurrently.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.migration.lock")
    deadline = time.monotonic() + _INIT_LOCK_TIMEOUT_SECONDS

    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
                if age > _STALE_INIT_LOCK_SECONDS:
                    lock_path.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out initializing cache at {path}")
            time.sleep(0.05)
            continue

        try:
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
            yield
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass
        return


def _create_database_file(path: Path, entries: dict[str, dict]) -> None:
    """Create a complete SQLite cache at ``path`` in one transaction."""
    connection = sqlite3.connect(str(path), timeout=_BUSY_TIMEOUT_SECONDS)
    try:
        # Migration is private until os.replace(), so a rollback journal keeps
        # the temporary artifact self-contained.  The live connection switches
        # the installed database to WAL after the replacement.
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE cache_metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        connection.execute(
            """
            CREATE TABLE cache_entries (
                cache_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        connection.execute(
            "INSERT INTO cache_metadata(name, value) VALUES (?, ?)",
            ("cache_schema_version", str(_SCHEMA_VERSION)),
        )
        connection.executemany(
            "INSERT INTO cache_entries(cache_key, value_json) VALUES (?, ?)",
            ((key, _serialize_entry(value)) for key, value in entries.items()),
        )
        connection.execute(f"PRAGMA user_version={_DB_FORMAT_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    # Flush the complete temporary database before its atomic replacement.
    # Windows' CRT rejects fsync() on a read-only descriptor, so open the
    # already-complete file read/write without modifying it.
    with path.open("r+b") as fp:
        os.fsync(fp.fileno())


def _atomic_replace_database(target: Path, entries: dict[str, dict]) -> None:
    """Atomically replace ``target`` with a freshly built SQLite database."""
    fd, temporary_name = tempfile.mkstemp(
        prefix=".drawing_digest_cache.", suffix=".sqlite3.tmp", dir=str(target.parent)
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        _create_database_file(temporary, entries)
        os.replace(temporary, target)
    finally:
        # A failed migration leaves the source JSON untouched.  SQLite can also
        # leave a journal beside the private temporary file after an I/O error.
        for candidate in (
            temporary,
            Path(f"{temporary}-journal"),
            Path(f"{temporary}-wal"),
            Path(f"{temporary}-shm"),
        ):
            try:
                candidate.unlink()
            except OSError:
                pass


def _prepare_database_path(path: Path) -> None:
    """Create or migrate ``path`` while preserving the configured filename."""
    with _initialization_lock(path):
        # Another process may have completed migration while this one waited.
        if _is_sqlite_database(path):
            return
        _atomic_replace_database(path, _read_legacy_json(path))


def _ensure_database_schema(connection: sqlite3.Connection) -> None:
    """Create tables and transactionally invalidate incompatible cache rows."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_metadata (
                name TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            ) WITHOUT ROWID
            """
        )

        db_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        schema_row = connection.execute(
            "SELECT value FROM cache_metadata WHERE name = ?",
            ("cache_schema_version",),
        ).fetchone()
        try:
            cache_schema = int(schema_row[0]) if schema_row is not None else None
        except (TypeError, ValueError):
            cache_schema = None

        if db_version != _DB_FORMAT_VERSION or cache_schema != _SCHEMA_VERSION:
            # Cache invalidation is all-or-nothing.  No reader can observe old
            # and current-schema rows mixed together.
            connection.execute("DELETE FROM cache_entries")
        connection.execute(
            """
            INSERT INTO cache_metadata(name, value) VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET value=excluded.value
            """,
            ("cache_schema_version", str(_SCHEMA_VERSION)),
        )
        connection.execute(f"PRAGMA user_version={_DB_FORMAT_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(path),
        timeout=_BUSY_TIMEOUT_SECONDS,
        isolation_level=None,
        check_same_thread=False,
    )
    try:
        connection.execute(f"PRAGMA busy_timeout={int(_BUSY_TIMEOUT_SECONDS * 1000)}")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        _ensure_database_schema(connection)
    except Exception:
        connection.close()
        raise
    return connection


class DigestCache:
    """Thread-safe digest store, optionally persisted to ``path``.

    ``persist=False`` (or ``path=None``) keeps it purely in-memory — used by
    tests and by an explicit opt-out — so a hermetic run never touches the
    user's real cache file.  Persistent stores use one transactional SQLite row
    per key; the configured path is intentionally unchanged for compatibility
    with legacy ``*.json`` cache paths and environment overrides.

    Cache I/O is best-effort.  A failed database write is retained in this
    instance's in-memory overlay, matching the historical guarantee that cache
    failures never sink an otherwise successful analysis run.
    """

    def __init__(self, path: Path | None = None, *, persist: bool = True) -> None:
        self._path = Path(path) if path is not None else None
        self._persist = bool(persist and path is not None)
        self._lock = threading.Lock()
        # In memory-only mode this is the complete store.  In persistent mode it
        # contains only legacy/failure fallback rows whose newest value has not
        # reached SQLite.
        self._entries: dict[str, dict] = {}
        self._connection: sqlite3.Connection | None = None
        self._hits = 0
        self._misses = 0
        if self._persist:
            self._load()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._hits += 1
                return dict(value)

            if self._connection is None:
                self._misses += 1
                return None

            try:
                row = self._connection.execute(
                    "SELECT value_json FROM cache_entries WHERE cache_key = ?", (key,)
                ).fetchone()
            except sqlite3.Error:
                self._misses += 1
                return None
            if row is None:
                self._misses += 1
                return None

            raw_value = row[0]
            try:
                decoded = json.loads(raw_value)
            except (TypeError, ValueError):
                decoded = None
            if not isinstance(decoded, dict):
                # Discard only the exact corrupt value read.  A concurrent writer
                # that already repaired the key must not have its row removed.
                try:
                    self._connection.execute(
                        "DELETE FROM cache_entries WHERE cache_key = ? AND value_json = ?",
                        (key, raw_value),
                    )
                except sqlite3.Error:
                    pass
                self._misses += 1
                return None

            self._hits += 1
            return dict(decoded)

    def put(self, key: str, value: dict) -> None:
        copied = dict(value)
        with self._lock:
            # Stage the newest value first.  Besides preserving the historical
            # nonfatal-write semantics, this overlay lets a later successful
            # put retry rows held back by a transient SQLite error.
            self._entries[key] = copied
            if self._connection is None:
                return

            pending: list[tuple[str, str]] = []
            for pending_key, pending_value in self._entries.items():
                try:
                    pending.append((pending_key, _serialize_entry(pending_value)))
                except Exception:
                    # A malformed/non-JSON value remains usable in memory but
                    # must not prevent independent serializable rows persisting.
                    continue
            if not pending:
                return

            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.executemany(
                    """
                    INSERT INTO cache_entries(cache_key, value_json) VALUES (?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET value_json=excluded.value_json
                    """,
                    pending,
                )
                self._connection.commit()
            except Exception:
                try:
                    self._connection.rollback()
                except sqlite3.Error:
                    pass
                # A cache-write failure must never sink a run; the digest is
                # already computed and returned to the caller.
                pass
            else:
                for persisted_key, _encoded in pending:
                    self._entries.pop(persisted_key, None)

    def stats(self) -> dict:
        with self._lock:
            size = len(self._entries)
            if self._connection is not None:
                try:
                    size = int(
                        self._connection.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
                    )
                    # A failed overwrite may shadow an existing durable row;
                    # count only genuinely new overlay keys in addition to SQL.
                    for key in self._entries:
                        exists = self._connection.execute(
                            "SELECT 1 FROM cache_entries WHERE cache_key = ?", (key,)
                        ).fetchone()
                        if exists is None:
                            size += 1
                except sqlite3.Error:
                    size = len(self._entries)
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": size,
            }

    def close(self) -> None:
        """Close this instance's database connection.

        The process-wide cache normally lives until interpreter shutdown.  The
        explicit hook is useful for short-lived cache instances and guarantees
        timely release of SQLite/WAL file handles on Windows.
        """
        with self._lock:
            connection = self._connection
            self._connection = None
        if connection is not None:
            connection.close()

    def __del__(self) -> None:
        # Avoid acquiring locks during interpreter teardown, when modules and
        # synchronization primitives may already be partially finalized.
        connection = getattr(self, "_connection", None)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        assert self._path is not None
        try:
            _prepare_database_path(self._path)
            self._connection = _open_database(self._path)
        except Exception:
            # Missing permissions, a failed atomic migration, or a malformed
            # database must not abort analysis.  If the original artifact is a
            # valid legacy JSON cache, continue serving it in memory this run.
            self._entries = _read_legacy_json(self._path)


_default_cache: DigestCache | None = None
_default_lock = threading.Lock()


def get_default_digest_cache() -> DigestCache:
    """Process-wide digest cache, built once from the env config.

    Only the real run paths (the GUI / standalone analyzer, via
    ``extract_drawing_context(use_cache=True)``) reach this; unit tests inject
    their own :class:`DigestCache` so they never touch the on-disk file.
    """
    global _default_cache
    with _default_lock:
        if _default_cache is None:
            persist = persistence_enabled()
            path = default_cache_path() if persist else None
            _default_cache = DigestCache(path, persist=persist)
        return _default_cache
