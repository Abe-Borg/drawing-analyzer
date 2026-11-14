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


def scoped_to(profile: Profile, raw: str) -> Profile:
    """``profile`` limited to the sheet-number prefixes in ``raw`` (``"F, FP"``).

    A blank ``raw`` clears the scope, so the checklist applies to every sheet.
    The checklist's content — and so its content hash — is unchanged; which
    sheets receive it is what moves their critique cache keys.
    """
    from dataclasses import replace

    return replace(profile, disciplines=_split_tags(raw))


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
# Uploaded checklist files (GUI "Load checklists…")
# --------------------------------------------------------------------------- #

CHECKLIST_FILE_EXTENSIONS = frozenset(
    {".md", ".txt", ".docx", ".pdf", ".xlsx", ".xlsm", ".csv"}
)
# Uploaded checklists are named apart from the profiles folder's, so loading a
# file can never shadow (or be shadowed by) an installed profile of the same
# stem. ``snapshot_profiles`` reports their source as ``uploaded``.
UPLOADED_PROFILE_PREFIX = "upload:"
_MAX_CHECKLIST_ITEM_CHARS = 600
_SPREADSHEET_HEADER_RE = re.compile(
    r"^(items?|no\.?|#|id|description|check\s*(list)?\s*items?|checks?|"
    r"requirements?|status|category|section|reference|comments?|notes?|remarks?)$",
    re.IGNORECASE,
)
_ITEM_NUMBER_RE = re.compile(r"^[\d.()-]{1,8}$")


def _spreadsheet_lines(path: Path) -> list[str]:
    """One line per non-empty row (cells joined), header row and item numbers dropped."""
    rows: list[list[str]] = []
    if path.suffix.lower() == ".csv":
        import csv

        from .spec_documents import _decode_text_bytes

        rows = [list(r) for r in csv.reader(_decode_text_bytes(path.read_bytes()).splitlines())]
    else:
        import openpyxl  # lazy: only a spreadsheet checklist needs it

        book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            for ws in book.worksheets:
                for row in ws.iter_rows(max_col=40, values_only=True):
                    rows.append(["" if c is None else str(c) for c in row])
                    if len(rows) >= 5_000:
                        break
        finally:
            book.close()
    lines: list[str] = []
    seen_header = False
    for row in rows:
        cells = [" ".join(c.split()) for c in row if c and str(c).strip()]
        if not cells:
            continue
        if not seen_header:
            seen_header = True
            if any(_SPREADSHEET_HEADER_RE.match(c) for c in cells):
                continue
        cells = [c for c in cells if not _ITEM_NUMBER_RE.match(c)]
        if cells:
            lines.append(" — ".join(cells))
    return lines


def _plain_items(lines: Iterable[str]) -> tuple[str, ...]:
    """Checklist items from text with no list bullets: one per substantive line."""
    items: list[str] = []
    for raw in lines:
        line = " ".join(str(raw).split())
        if not line or line.startswith("#") or line == "---":
            continue
        if len(line) < 4 or len(line) > _MAX_CHECKLIST_ITEM_CHARS:
            continue
        items.append(line)
    return tuple(items)


def load_checklist_file(path: Any) -> Profile:
    """Read an uploaded checklist file into a :class:`Profile`.

    A Markdown/text file in the profile format (frontmatter + list bullets)
    parses exactly as a profiles-folder file would. Anything else — a Word or
    PDF checklist, a spreadsheet (one item per row), or plain lines with no
    bullets — becomes one item per substantive line. Raises ``ValueError``
    with a readable reason when the file yields no items.
    """
    from .spec_documents import extract_spec_text

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in CHECKLIST_FILE_EXTENSIONS:
        raise ValueError(
            f"unsupported file type {suffix or '(none)'} "
            f"(accepted: {', '.join(sorted(CHECKLIST_FILE_EXTENSIONS))})"
        )
    if suffix in (".xlsx", ".xlsm", ".csv"):
        lines = _spreadsheet_lines(path)
        text = "\n".join(lines)
        items = _plain_items(lines)
        meta: dict[str, str] = {}
    else:
        doc = extract_spec_text(path)
        if not doc.ok:
            raise ValueError(doc.error or "no extractable text")
        text = doc.text
        meta, body = _parse_frontmatter(text)
        items = _parse_items(body) or _plain_items(body.splitlines())
    if not items:
        raise ValueError("no checklist items found")
    # The file name, extension included, so check.xlsx and check.docx loaded
    # together stay two checklists.
    name = UPLOADED_PROFILE_PREFIX + ((meta.get("name") or path.name).strip() or path.name)
    return Profile(
        name=name,
        title=(meta.get("title") or path.name).strip(),
        disciplines=_split_tags(meta.get("disciplines", "")),
        version=(meta.get("version") or "0").strip(),
        author=meta.get("author", "").strip(),
        date=meta.get("date", "").strip(),
        items=items,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        source_path=path,
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
    """The discipline token of a sheet id (``"F-D-01-1"`` → ``"f"``).

    Delegates to the shared, host-owned :func:`sheet_ids.discipline_token`
    (Phase 24 §16.0), which is **project-prefix aware** — a project-coded id like
    ``AVC10-F-D-01-1`` yields the meaningful discipline segment ``"f"`` rather
    than the project code ``"avc"`` (DA-018). Plain hyphenated/compact/dotted
    forms are unchanged (``FP-101``/``FP101`` → ``"fp"``, ``E1.01`` → ``"e"``).
    """
    from .auditors.sheet_ids import discipline_token

    return discipline_token(sheet_id)


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


def preflight_sheet_ids(paths: Iterable[Any]) -> list[str]:
    """Cheaply extract each page's likely sheet id from a set of PDFs.

    A lightweight, text-only preflight for GUI profile auto-suggest (§16.4): it
    reads each page's word list and detects the title-block sheet id via the shared
    detector — **without** rasterizing the full overview + tile grid. PyMuPDF-isolated
    (it defers to :mod:`render`); any unreadable file is skipped silently (this is a
    best-effort hint, never authoritative). Returns the detected ids in page order.
    """
    from pathlib import Path

    from .auditors.references import detect_sheet_id

    return preflight_scan(paths).sheet_ids


@dataclass(frozen=True)
class PreflightScan:
    """Everything one walk over the input PDFs can yield (WP-05 §10.3).

    The preflight already opens every page and builds a full ``SheetGeometry``
    to read its title-block sheet id — then discards the geometry. Every fact a
    :class:`~drawing_analyzer.models.SheetCostBasis` needs is in the object it
    throws away, so producing both costs one extra attribute read per page.

    Measured (`scripts/measure_scan_time.py`, 120 sheets x 4,000 words): a fresh
    cost scan of that set takes **6,896 ms** and waits up to **22,457 ms** behind
    a running preflight; deriving the same records from geometry the preflight
    already holds takes **0.4 ms** — 0.01% of a fresh scan, inside the lock that
    is already held, with no second PDF owner. That is why there is no separate
    scan: the measurement §10.3 asks for made the choice.
    """

    sheet_ids: list[str]
    cost_bases: list  # of models.SheetCostBasis; untyped to keep imports shallow


def preflight_scan(paths: Iterable[Any]) -> PreflightScan:
    """One text-only walk; both of its products.

    Same cost as :func:`preflight_sheet_ids` — which now delegates here — and the
    same tolerance: an unreadable file is skipped with a log line, never raised,
    because this is a best-effort hint and never authoritative.
    """
    from pathlib import Path

    from .auditors.references import detect_sheet_id
    from .models import sheet_cost_basis

    ids: list[str] = []
    bases: list = []
    for path in paths or []:
        try:
            from . import render

            for _ref, _identity, geometry in render.iter_sheet_prescan([Path(path)]):
                sid = detect_sheet_id(geometry)
                if sid:
                    ids.append(sid)
                bases.append(sheet_cost_basis(geometry))
        except Exception as exc:  # noqa: BLE001 - a bad file must not sink preflight
            _log.info("profile preflight skipped %s: %s", path, exc)
    return PreflightScan(sheet_ids=ids, cost_bases=bases)


def suggest_profiles_for_paths(
    paths: Iterable[Any], *, available: dict[str, Profile] | None = None
) -> list[Profile]:
    """Auto-suggest profiles for a set of input PDFs (preflight + discipline match)."""
    return suggest_profiles(preflight_sheet_ids(paths), available=available)


def suggest_profiles_and_cost_bases(
    paths: Iterable[Any], *, available: dict[str, Profile] | None = None
) -> tuple[list[Profile], list]:
    """``(profiles, cost_bases)`` from a **single** walk over ``paths``.

    What the GUI preflight calls, so the confirmation dialog can price the set
    from each page's real shape without a second pass over the PDFs (§10.3).
    """
    scan = preflight_scan(paths)
    return suggest_profiles(scan.sheet_ids, available=available), scan.cost_bases


def resolve_profile_selection(
    suggested: Iterable[str],
    *,
    user_selected: Iterable[str] | None = None,
    user_deselected: Iterable[str] | None = None,
) -> list[str]:
    """The effective selected profile names given auto-suggestions + user overrides.

    Applicable suggestions are on by default; an explicit user selection adds a
    profile and an explicit deselection removes it — **manual choice always wins**,
    including across a later preflight refresh (a name the user deselected stays off
    even if it is re-suggested). Deterministic order: suggested first (in order),
    then any extra user selections. (§16.4)
    """
    deselected = {str(n) for n in (user_deselected or [])}
    selected = [str(n) for n in (user_selected or [])]
    out: list[str] = []
    seen: set[str] = set()
    for name in list(suggested) + selected:
        name = str(name)
        if name in deselected or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def snapshot_profiles(profiles: Iterable[Profile]) -> list:
    """Immutable :class:`~drawing_analyzer.models.ProfileSnapshot` for each profile.

    Captured at Analyze time (§16.4) so the run manifest / report can show exactly
    which profile version + content hash was injected. ``source`` is coarse
    (builtin / user) — never an absolute path.
    """
    from .models import ProfileSnapshot

    builtin_dir = builtin_profiles_dir()
    snaps = []
    for p in profiles:
        source = ""
        if p.name.startswith(UPLOADED_PROFILE_PREFIX):
            source = "uploaded"
        elif p.source_path is not None:
            try:
                source = "builtin" if p.source_path.resolve().parent == builtin_dir.resolve() else "user"
            except OSError:
                source = "user"
        snaps.append(ProfileSnapshot(
            name=p.name, title=p.title, version=p.version,
            content_hash=p.content_hash, source=source,
            disciplines=tuple(p.disciplines),
        ))
    return snaps


# --------------------------------------------------------------------------- #
# Cache fragment + prompt assembly
# --------------------------------------------------------------------------- #


MODEL_PLAN_PREFIX = "model-plan-"
"""Name prefix of the profiles the review planner authors (``source="model"``)."""

_GENERAL_DISCIPLINE = "general"


def is_model_plan(profile: Profile) -> bool:
    """Whether ``profile`` was authored by the review planner, not a person."""
    return str(profile.name).startswith(MODEL_PLAN_PREFIX)


@dataclass(frozen=True)
class ChecklistItem:
    """One checklist line with the id the reviewer answers it by.

    Ids are assigned over the **whole** selection (``U1.3`` = the third item of
    the first user checklist, ``M2.7`` = the seventh of the second model plan),
    never per sheet, so an item keeps one id on every sheet it is applied to and
    scoping a checklist to a discipline cannot renumber another checklist.
    """

    id: str
    text: str
    profile: str          # the owning profile's ``name``
    title: str            # the owning profile's ``title``
    origin: str           # "user" | "model"
    number: int           # 1-based position within its profile


def _items_per_profile(profiles: Iterable[Profile]) -> list[list[ChecklistItem]]:
    """Each selected profile's items, parallel to ``profiles``.

    Grouped by **position in the selection**, never by name: two uploaded
    checklists can share a file name (``fire/checklist.md`` and
    ``electrical/checklist.md``) and still be two checklists with two scopes.
    """
    out: list[list[ChecklistItem]] = []
    counters = {"user": 0, "model": 0}
    for profile in profiles or []:
        origin = "model" if is_model_plan(profile) else "user"
        counters[origin] += 1
        prefix = f"{'M' if origin == 'model' else 'U'}{counters[origin]}"
        items: list[ChecklistItem] = []
        for raw in profile.items:
            text = (raw or "").strip()
            if not text:
                continue
            items.append(ChecklistItem(
                id=f"{prefix}.{len(items) + 1}", text=text, profile=profile.name,
                title=profile.title, origin=origin, number=len(items) + 1,
            ))
        out.append(items)
    return out


def checklist_items(profiles: Iterable[Profile]) -> list[ChecklistItem]:
    """Every non-blank item across ``profiles``, in order, with its id."""
    return [item for items in _items_per_profile(profiles) for item in items]


_ITEM_ID_RE = re.compile(r"^[UM]\d{1,3}\.\d{1,4}$")


def normalize_item_id(raw: Any) -> str:
    """A model-reported item id in canonical form (``""`` when it is not one).

    Tolerates the brackets the checklist block prints around an id, stray
    whitespace and lower case; anything else is not an id and is dropped by the
    caller rather than guessed at.
    """
    text = str(raw or "").strip().strip("[]").strip().upper()
    return text if _ITEM_ID_RE.match(text) else ""


@dataclass(frozen=True)
class SheetScope:
    """What is known about one sheet's discipline (either field may be ``""``).

    ``token`` is the discipline prefix of the sheet's own number (``FP-101`` →
    ``"fp"``), which a person's checklist is scoped by. ``discipline`` is the
    slug of the discipline the set-identity stage classified the sheet under
    (``"fire-protection"``), which a model-authored plan is scoped by.
    """

    token: str = ""
    discipline: str = ""


def discipline_slug(name: Any) -> str:
    """The slug a discipline name is compared by (``"Fire Protection"`` →
    ``"fire-protection"``); the review planner names its plans the same way."""
    return re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")


def profile_applies(
    profile: Profile, scope: SheetScope | None, *, model_slugs: frozenset = frozenset()
) -> bool:
    """Whether ``profile``'s items are applied to a sheet with ``scope``.

    Scoping only ever *narrows on evidence* and fails open everywhere else: a
    profile with no discipline tags, a sheet whose discipline is unknown, and a
    sheet classified under a discipline no model plan was written for all get
    the profile. A wrong guess must cost attention, never a skipped check.
    """
    tags = profile.disciplines
    if scope is None or not tags:
        return True
    if is_model_plan(profile):
        if not scope.discipline or scope.discipline not in model_slugs:
            return True
        return scope.discipline in tags or _GENERAL_DISCIPLINE in tags
    if not scope.token:
        return True
    return scope.token in tags


_CHECKLIST_HEADER = (
    "APPLY THIS REVIEW CHECKLIST EXPLICITLY, ITEM BY ITEM, in addition to your "
    "own judgment. Each item below starts with its id in square brackets. Treat "
    "each item as a check to run against this sheet: report a finding when the "
    "item is violated (or, for an item about required content, when that content "
    "is absent), and give that finding a checklist_items array holding the id of "
    "every item it reports against. A finding that comes from your own judgment "
    "carries no checklist_items. Do not write a finding for an item that is met "
    "or does not apply.\n\n"
    "Then account for EVERY item. In the same JSON object as the findings "
    "described below, add \"checklist\": {\"violated\": [...], \"met\": [...], "
    "\"not_applicable\": [...], \"undetermined\": [...]} and place each item id "
    "in exactly one list: violated - you reported a finding against it; met - "
    "the sheet shows what the item concerns and you confirmed it complies; "
    "not_applicable - the sheet does not show what the item concerns; "
    "undetermined - the sheet shows what the item concerns but this sheet alone "
    "cannot settle it. Never list an item as met without having looked for it."
)


def render_checklist_block(items: Iterable[ChecklistItem]) -> str:
    """The checklist block appended to the critique prompt (``""`` if no items)."""
    kept = [it for it in items if it.text]
    if not kept:
        return ""
    body = "\n".join(f"- [{it.id}] {it.text}" for it in kept)
    return "\n\n" + _CHECKLIST_HEADER + "\n\n" + body


@dataclass(frozen=True)
class SheetChecklist:
    """The checklist one sheet's critique reads receive (possibly empty)."""

    items: tuple[ChecklistItem, ...] = ()

    @property
    def prompt(self) -> str:
        return render_checklist_block(self.items)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(it.id for it in self.items)

    @property
    def key(self) -> str | None:
        """The critique-cache-key component: a hash of the **exact text
        injected**, ``None`` when nothing is. Any edit to an item, the item
        order, the ids or the instructions above moves it; an empty checklist
        leaves the critique key byte-identical to a no-checklist one."""
        text = self.prompt
        if not text:
            return None
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ChecklistPlan:
    """The run's whole checklist plus which part of it each sheet receives.

    Built once per run. ``scopes`` maps a sheet's ``models.sheet_ref_key`` to
    its :class:`SheetScope`; a sheet with no entry is unscoped and receives
    every item. Each sheet's cache key is derived from its own injected block,
    so editing a fire-protection checklist re-critiques only the sheets that
    received it.
    """

    def __init__(self, profiles: Iterable[Profile] | None = None, scopes: Any = None):
        self.profiles: list[Profile] = list(profiles or [])
        self._per_profile = _items_per_profile(self.profiles)
        self.items: list[ChecklistItem] = [
            item for items in self._per_profile for item in items
        ]
        self._scopes: dict = dict(scopes or {})
        self._model_slugs = frozenset(
            tag for p in self.profiles if is_model_plan(p) for tag in p.disciplines
        )
        self._memo: dict = {}

    def __bool__(self) -> bool:
        return bool(self.items)

    @property
    def scoped(self) -> bool:
        return bool(self._scopes)

    def for_scope(self, scope: SheetScope | None) -> SheetChecklist:
        if scope not in self._memo:
            items: list[ChecklistItem] = []
            # Each selected profile is scoped on its own, by position.
            for profile, own in zip(self.profiles, self._per_profile):
                if profile_applies(profile, scope, model_slugs=self._model_slugs):
                    items.extend(own)
            self._memo[scope] = SheetChecklist(tuple(items))
        return self._memo[scope]

    def for_key(self, key: Any) -> SheetChecklist:
        return self.for_scope(self._scopes.get(key))

    def for_ref(self, ref: Any) -> SheetChecklist:
        from .models import sheet_ref_key

        return self.for_key(sheet_ref_key(ref))


def build_sheet_scopes(geometries: Iterable[Any], identity: Any = None) -> tuple[dict, dict]:
    """``(scopes, sheet_ids)`` for a run, both keyed by ``models.sheet_ref_key``.

    ``scopes`` is what :class:`ChecklistPlan` narrows by; ``sheet_ids`` is each
    sheet's own title-block number where one was found, for labelling results.
    A sheet's number prefix comes from the shared title-block detector (text
    only, deterministic). Its discipline comes from the set-identity stage's
    ``sheet_disciplines``, matched on the sheet number or the display label —
    whichever of the two the identity used to name the sheet. Anything that
    cannot be established is left ``""``, which never narrows.
    """
    from .auditors.references import detect_sheet_id
    from .auditors.sheet_ids import discipline_token, normalize_sheet_id
    from .models import sheet_ref_key

    classified: dict[str, str] = {}
    for pair in getattr(identity, "sheet_disciplines", None) or ():
        try:
            named, discipline = pair
        except (TypeError, ValueError):
            continue
        slug = discipline_slug(discipline)
        if not slug:
            continue
        for form in (normalize_sheet_id(named), str(named or "").strip().casefold()):
            if form:
                # Two entries naming one sheet differently is a contradiction
                # the identity cannot settle; that sheet stays unclassified.
                classified[form] = slug if classified.get(form, slug) == slug else ""

    scopes: dict = {}
    sheet_ids: dict = {}
    for geom in geometries or []:
        ref = getattr(geom, "ref", None)
        if ref is None:
            continue
        try:
            sheet_id = detect_sheet_id(geom) or ""
        except Exception:  # noqa: BLE001 - an unreadable page is simply unscoped
            sheet_id = ""
        label = str(getattr(ref, "display_label", "") or "")
        discipline = ""
        for form in (normalize_sheet_id(sheet_id), sheet_id.casefold(), label.casefold()):
            if form and classified.get(form):
                discipline = classified[form]
                break
        key = sheet_ref_key(ref)
        scopes[key] = SheetScope(
            token=discipline_token(sheet_id) if sheet_id else "", discipline=discipline,
        )
        if sheet_id:
            sheet_ids[key] = sheet_id
    return scopes, sheet_ids


def profiles_cache_fragment(profiles: list[Profile]) -> str | None:
    """The critique-cache-key component for an **unscoped** set of profiles.

    ``None`` when there is no checklist to inject (no profiles, or profiles
    with no items), so the critique key stays byte-identical to a no-profiles
    one. A run that scopes checklists per sheet uses
    :attr:`SheetChecklist.key` for each sheet instead.
    """
    return ChecklistPlan(profiles or []).for_scope(None).key


def flatten_items(profiles: Iterable[Profile]) -> list[str]:
    """Every checklist item across ``profiles``, in order."""
    return [item for p in profiles for item in p.items]


def build_checklist_prompt(items: Iterable[str]) -> str:
    """The checklist block for a bare list of item strings (``""`` if none).

    The strings are numbered as one user checklist. Callers that hold profiles
    use :class:`ChecklistPlan`, which numbers across all of them.
    """
    return ChecklistPlan(
        [Profile(name="checklist", title="checklist", items=tuple(items))]
    ).for_scope(None).prompt


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
