"""Persistent, content-keyed cache for per-sheet drawing digests.

A digest is the dominant cost in the drawing pipeline — one Opus 4.8 vision
request per sheet (image tokens + minutes of latency). The result is
deterministic given the rendered sheet images + the model + the digest prompt +
the request params, so re-running a set (after editing one sheet, or just
re-opening the project) should not re-pay for the sheets that didn't change.

This mirrors ``verification_cache``'s persistence shape — JSON on disk, atomic
write, defensive load, env-overridable path/toggle — but is far simpler:
entries never expire (the key already invalidates on any content / model /
prompt change) and only the durable digest text + token telemetry are stored.

Thread-safe by design: ``digest_sheet`` calls may run concurrently (the parallel
dispatch follow-up), so ``get`` / ``put`` / save are guarded by a lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

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
# must miss once and be re-derived rather than served as current.
_SCHEMA_VERSION = 7

_FALSEY = {"0", "false", "no", "off", ""}


def _env_truthy(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in _FALSEY


def default_cache_path() -> Path:
    """On-disk digest-cache location.

    Overridable via ``DRAWING_ANALYZER_CACHE_PATH`` (``~`` and ``$VAR``
    expanded); defaults to ``~/.drawing_analyzer/drawing_digest_cache.json``,
    alongside the verification cache.
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
) -> str:
    """Content-address one sheet's digest **before rendering** (Phase 9, level-1).

    The dominant cost of a re-run is rasterization (~4.5 s/sheet, ~2.5 min for a
    33-sheet set). A digest is deterministic given the rendered images, so if the
    images *would* be byte-identical we can serve the cached digest without ever
    rendering. ``render_identity`` is exactly that "would the images match"
    fingerprint, produced from cheap page access alone
    (:func:`drawing_analyzer.render.sheet_render_identity`): the PyMuPDF version,
    grid + overlap + render target, the blank-suppression mode, and a hash of the
    page's content streams + referenced image bytes + rect.

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


class DigestCache:
    """Thread-safe digest store, optionally persisted to ``path``.

    ``persist=False`` (or ``path=None``) keeps it purely in-memory — used by
    tests and by an explicit opt-out — so a hermetic run never touches the
    user's real cache file.
    """

    def __init__(self, path: Path | None = None, *, persist: bool = True) -> None:
        self._path = path
        self._persist = bool(persist and path is not None)
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._hits = 0
        self._misses = 0
        if self._persist:
            self._load()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                self._misses += 1
                return None
            self._hits += 1
            return dict(value)

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._entries[key] = dict(value)
            if self._persist:
                try:
                    self._save_locked()
                except Exception:
                    # A cache-write failure must never sink a run; the digest is
                    # already computed and returned to the caller.
                    pass

    def stats(self) -> dict:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._entries),
            }

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # missing or corrupt → start empty (never raise on load)
        if not isinstance(raw, dict) or raw.get("_schema_version") != _SCHEMA_VERSION:
            return
        entries = raw.get("entries")
        if isinstance(entries, dict):
            self._entries = {k: v for k, v in entries.items() if isinstance(v, dict)}

    def _save_locked(self) -> None:
        target = self._path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"_schema_version": _SCHEMA_VERSION, "entries": self._entries}
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".drawing_digest_cache.", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fp:
                json.dump(payload, fp)
            os.replace(tmp_name, target)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise


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
