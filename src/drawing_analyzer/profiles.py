"""Review profiles — the owner's QC knowledge as versioned, injectable checklists
(Phase 12).

A *profile* is a Markdown file: a small frontmatter header (name, disciplines,
version, author, date) delimited by ``---`` lines, followed by a flat checklist
of one-line items (Markdown list bullets). The critique pass ("the reviewer")
injects the selected profiles' items verbatim into its prompt, so an experienced
engineer's back-check becomes literal instructions the model applies item by
item — not just its incidental judgment.

Profiles load from two roots, later winning on a name collision:

1. the built-in starter set shipped inside the package
   (``drawing_analyzer/profiles/``), and
2. a user directory, ``~/.drawing_analyzer/profiles/`` (override with
   ``DRAWING_ANALYZER_PROFILES_DIR``),

so a user can drop in their own office's checklists, or shadow a built-in one by
reusing its ``name``.

This module is pure and dependency-free (no PDF engine, no model calls, no
network) — the frontmatter parser is a deliberately small ``key: value`` reader,
not a YAML dependency. A profile's ``content_hash`` folds into the critique cache
key, so *editing* a checklist re-critiques rather than serving a stale read.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .diagnostics import get_logger

_log = get_logger()

# A checklist item is any Markdown list bullet — ``-``, ``*``, ``+`` — or a
# numbered-list marker (``1.`` / ``1)``); the marker is stripped, the text kept.
_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
# Leading 1-3 letters of a sheet id → discipline hint. No trailing ``\b``: there
# is no word boundary between a letter and a digit, so a *concatenated* id like
# ``F101`` / ``FP201`` (as common as the hyphenated ``F-101``) would otherwise
# yield "" and silently defeat auto-suggest.
_ID_DISCIPLINE_RE = re.compile(r"^\s*([A-Za-z]{1,3})")


@dataclass(frozen=True)
class Profile:
    """One review profile: metadata + a flat checklist of one-line items.

    ``content_hash`` is a digest of the *entire* source file, so any edit — to an
    item, the header, anything — changes it and re-keys the critique cache.
    ``disciplines`` are lower-cased tags used to auto-suggest a profile for a set
    (matched against the leading letters of the set's sheet ids).
    """

    name: str
    title: str
    disciplines: tuple[str, ...] = ()
    version: str = "0"
    author: str = ""
    date: str = ""
    items: tuple[str, ...] = ()
    content_hash: str = ""
    source_path: Path | None = None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split leading ``---`` frontmatter from the body.

    Returns ``(meta, body)``. With no frontmatter the whole text is the body and
    ``meta`` is empty. The parser reads flat ``key: value`` lines only (no nested
    YAML), which is all a profile header needs.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    # Only treat the head as frontmatter when there is a *closing* ``---``.
    # Otherwise the file is malformed (an unclosed header); fall back to "no
    # frontmatter" so its checklist items are still parsed from the body rather
    # than the whole file being swallowed as a header (a silent zero-item profile).
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if close is None:
        return {}, text
    meta: dict[str, str] = {}
    for line in lines[1:close]:
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip().lower()] = value.strip()
    body = "\n".join(lines[close + 1:])
    return meta, body


def _parse_items(body: str) -> tuple[str, ...]:
    items = []
    for line in body.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            item = m.group(1).strip()
            if item:
                items.append(item)
    return tuple(items)


def _split_tags(raw: str) -> tuple[str, ...]:
    return tuple(
        t.strip().lower()
        for t in (raw or "").replace(";", ",").split(",")
        if t.strip()
    )


def parse_profile(text: str, *, source_path: Any = None, fallback_name: str = "profile") -> Profile:
    """Parse a profile's Markdown source into a :class:`Profile`.

    ``fallback_name`` (normally the file stem) is used when the frontmatter omits
    ``name``. The ``content_hash`` covers the raw ``text`` verbatim.
    """
    meta, body = _parse_frontmatter(text)
    name = (meta.get("name") or fallback_name).strip() or fallback_name
    return Profile(
        name=name,
        title=(meta.get("title") or name).strip(),
        disciplines=_split_tags(meta.get("disciplines", "")),
        version=(meta.get("version") or "0").strip(),
        author=meta.get("author", "").strip(),
        date=meta.get("date", "").strip(),
        items=_parse_items(body),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        source_path=Path(source_path) if source_path else None,
    )


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def builtin_profiles_dir() -> Path:
    """The starter profiles shipped inside the package."""
    return Path(__file__).resolve().parent / "profiles"


def user_profiles_dir() -> Path:
    """The user's profiles dir (``DRAWING_ANALYZER_PROFILES_DIR`` or the default)."""
    override = os.environ.get("DRAWING_ANALYZER_PROFILES_DIR")
    if override and override.strip():
        return Path(os.path.expandvars(os.path.expanduser(override.strip())))
    return Path.home() / ".drawing_analyzer" / "profiles"


def _load_dir(directory: Path) -> dict[str, Profile]:
    out: dict[str, Profile] = {}
    try:
        if not directory.is_dir():
            return out
        paths = sorted(directory.glob("*.md"))
    except OSError:
        return out
    for path in paths:
        try:
            # A bad file — unreadable, or not UTF-8 (``UnicodeDecodeError`` is a
            # ``ValueError``, not an ``OSError``) — must never sink discovery of
            # the *other* profiles, so the whole per-file read+parse is guarded.
            text = path.read_text(encoding="utf-8")
            prof = parse_profile(text, source_path=path, fallback_name=path.stem)
        except Exception as exc:  # noqa: BLE001 - one bad file can't sink the set
            _log.warning("skipping unreadable/invalid profile %s: %s", path, exc)
            continue
        out[prof.name] = prof
    return out


def load_profiles() -> dict[str, Profile]:
    """All available profiles, ``name`` → :class:`Profile`.

    Built-ins load first; the user dir loads second and **wins on a name
    collision**, so a user can shadow a shipped profile by reusing its ``name``.
    """
    profiles = _load_dir(builtin_profiles_dir())
    profiles.update(_load_dir(user_profiles_dir()))
    return profiles


def list_profiles() -> list[Profile]:
    """All available profiles, sorted by name."""
    return sorted(load_profiles().values(), key=lambda p: p.name)


def get_profile(name: str) -> Profile | None:
    return load_profiles().get(name)


def resolve_profiles(
    names: Iterable[Any] | None, *, available: dict[str, Profile] | None = None
) -> list[Profile]:
    """Resolve a mix of profile names and :class:`Profile` objects to profiles.

    Unknown names are dropped with a logged warning (a stale profile reference
    must never sink a run — additive, non-fatal). Order follows ``names``.
    """
    if not names:
        return []
    table = available
    out: list[Profile] = []
    for n in names:
        if isinstance(n, Profile):
            out.append(n)
            continue
        if table is None:                 # only touch the filesystem if a name needs it
            table = load_profiles()
        prof = table.get(str(n))
        if prof is None:
            _log.warning("unknown review profile requested: %r (skipped)", n)
            continue
        out.append(prof)
    return out


# --------------------------------------------------------------------------- #
# Auto-suggest by discipline
# --------------------------------------------------------------------------- #


def discipline_hint(sheet_id: str) -> str:
    """The leading discipline token of a sheet id (``"F-D-01-1"`` → ``"f"``)."""
    m = _ID_DISCIPLINE_RE.match(sheet_id or "")
    return m.group(1).lower() if m else ""


def suggest_profiles(
    sheet_ids: Iterable[str], *, available: dict[str, Profile] | None = None
) -> list[Profile]:
    """Profiles whose disciplines match any sheet id's leading discipline token."""
    table = available if available is not None else load_profiles()
    hints = {discipline_hint(s) for s in (sheet_ids or []) if s}
    hints.discard("")
    return sorted(
        (p for p in table.values() if any(h in p.disciplines for h in hints)),
        key=lambda p: p.name,
    )


# --------------------------------------------------------------------------- #
# Cache fragment + prompt assembly
# --------------------------------------------------------------------------- #


def profiles_cache_fragment(profiles: list[Profile]) -> str | None:
    """The critique-cache-key component for a set of profiles (``None`` if empty).

    Sorted ``name@version@hash`` triples, so the key is order-independent, and any
    profile edit (new ``content_hash``) or version bump re-critiques. ``None`` (no
    profiles) leaves the critique key byte-identical to a pre-profiles key, so
    existing cache entries stay valid.
    """
    if not profiles:
        return None
    return "|".join(sorted(f"{p.name}@{p.version}@{p.content_hash}" for p in profiles))


_CHECKLIST_HEADER = (
    "APPLY THIS REVIEW CHECKLIST EXPLICITLY, ITEM BY ITEM, in addition to your "
    "own judgment. Treat each item as a check to run against this sheet: report a "
    "finding when the item is violated (or, for an item about required content, "
    "when that content is absent), and move on otherwise. Do not restate the "
    "checklist or report an item that passes."
)


def flatten_items(profiles: Iterable[Profile]) -> list[str]:
    """Every checklist item across ``profiles``, in order."""
    return [item for p in profiles for item in p.items]


def build_checklist_prompt(items: Iterable[str]) -> str:
    """The checklist block appended to the critique prompt (``""`` if no items)."""
    kept = [it.strip() for it in items if it and it.strip()]
    if not kept:
        return ""
    body = "\n".join(f"- {it}" for it in kept)
    return "\n\n" + _CHECKLIST_HEADER + "\n\n" + body


def chunk_items(items: list[str], n: int) -> list[list[str]]:
    """Split ``items`` into exactly ``n`` near-even contiguous chunks.

    Used to spread a long checklist across the self-consistency runs under token
    pressure (each run covers a slice, the union covers all — never truncated).
    Some chunks may be empty when ``items`` is shorter than ``n``.
    """
    n = max(1, n)
    items = list(items)
    k, r = divmod(len(items), n)
    chunks: list[list[str]] = []
    start = 0
    for i in range(n):
        size = k + (1 if i < r else 0)
        chunks.append(items[start:start + size])
        start += size
    return chunks
