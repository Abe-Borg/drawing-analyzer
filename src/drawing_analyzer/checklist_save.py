"""Keep checks from a run's review checklist as the user's own checklist.

The Live view's *Plan* tab lists the checklist a run applied — usually the
model's own review plan — and lets a reader pick checks and save them
(:mod:`~drawing_analyzer.live_tabs`). This module turns those picks into a
checklist file in the user's profiles folder
(:func:`~drawing_analyzer.profiles.user_profiles_dir`): a new file, or one
that is already there. A saved file is an ordinary profile, so the profile
panel lists it, suggests it for sets whose sheet numbers carry its prefixes,
and the critique applies it item by item on later runs.

Each save is planned first (:func:`plan_new` / :func:`plan_append`, which the
dialog shows) and then re-planned against the disk at the moment of writing
(:func:`save_new` / :func:`save_append`), so a file edited in between is never
clobbered with a stale copy. A check whose text is already in the target
checklist, in one of the user's checklists the run applied, or earlier in the
same selection is skipped and reported, never written twice. Text is compared
case-folded with whitespace collapsed and trailing punctuation ignored.

Writes go through a temporary file and :func:`os.replace`; a new checklist
never overwrites an existing file and takes the next free file name and
profile name instead. Toolkit-free, PDF-free, no model calls.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .profiles import (
    _ITEM_RE,
    _load_dir,
    _split_tags,
    builtin_profiles_dir,
    parse_profile,
    user_profiles_dir,
)

DEFAULT_TITLE = "Saved review checks"
_MAX_TITLE_CHARS = 120
_MAX_SLUG_CHARS = 60
_PREFIX_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,14}[a-z0-9])?")
_VERSION_RE = re.compile(r"^(\s*version\s*:\s*)(\d+)\s*$", re.IGNORECASE)
_DATE_RE = re.compile(r"^(\s*date\s*:\s*).*$", re.IGNORECASE)
_NEW_FILE_NOTE = (
    "Checks kept from a run's review checklist (Live view, Plan tab). One check "
    "per bullet: edit, reorder or delete them freely."
)


@dataclass(frozen=True)
class PickedCheck:
    """One check picked in the Plan tab: its id in that run and its exact line."""

    id: str
    text: str


@dataclass(frozen=True)
class SavedChecklist:
    """A checklist file already in the user's profiles folder."""

    name: str
    title: str
    path: Path
    disciplines: tuple[str, ...]
    items: tuple[str, ...]


@dataclass(frozen=True)
class SavePlan:
    """What a save writes (or, from ``save_*``, wrote).

    ``skipped`` pairs each check left out with where its text already is: a run
    id (``"U1.2"``), ``"item 3"`` of the target checklist, or the id picked
    earlier in the same selection. ``text`` is the whole file after the save.
    """

    path: Path
    name: str
    title: str
    disciplines: tuple[str, ...]
    adding: tuple[PickedCheck, ...]
    skipped: tuple[tuple[PickedCheck, str], ...]
    appending: bool
    text: str


# --------------------------------------------------------------------------- #
# Small rules.
# --------------------------------------------------------------------------- #


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_check(text: Any) -> str:
    """The form two checks are compared in: case-folded, whitespace collapsed,
    trailing punctuation ignored."""
    return _one_line(text).casefold().rstrip(" .;:,")


def clean_title(title: Any) -> str:
    """A checklist title as it is written into the file: one line, bounded."""
    value = _one_line(title).strip("-").strip()[:_MAX_TITLE_CHARS].strip()
    return value or DEFAULT_TITLE


def file_slug(title: Any) -> str:
    """The file stem (and profile name) a title suggests: ``Data center FP``
    → ``data-center-fp``."""
    slug = re.sub(r"[^a-z0-9]+", "-", clean_title(title).casefold()).strip("-")
    return slug[:_MAX_SLUG_CHARS].strip("-") or "saved-checks"


def clean_prefixes(raw: Any) -> tuple[str, ...]:
    """Sheet-number prefixes from ``"FP, f; FS"`` or an iterable of them:
    lower-cased, de-duplicated in order, anything that is not a prefix dropped."""
    if isinstance(raw, str):
        tags: Iterable[str] = _split_tags(raw)
    else:
        tags = (str(t).strip().lower() for t in (raw or ()))
    out: list[str] = []
    for tag in tags:
        if _PREFIX_RE.fullmatch(tag) and tag not in out:
            out.append(tag)
    return tuple(out)


def _clean_checks(checks: Iterable[Any]) -> list[PickedCheck]:
    out = []
    for c in checks or ():
        text = _one_line(getattr(c, "text", ""))
        if text:
            out.append(PickedCheck(id=str(getattr(c, "id", "") or ""), text=text))
    return out


def _split(checks: list[PickedCheck], present: list[tuple[str, str]]):
    """``(adding, skipped)``: a check whose text is already ``present`` (a list
    of ``(where, text)``) or was picked earlier is skipped, with where it is."""
    seen: dict[str, str] = {}
    for where, text in present:
        seen.setdefault(normalize_check(text), where)
    adding: list[PickedCheck] = []
    skipped: list[tuple[PickedCheck, str]] = []
    for check in checks:
        key = normalize_check(check.text)
        if key in seen:
            skipped.append((check, seen[key]))
            continue
        seen[key] = check.id or "this selection"
        adding.append(check)
    return tuple(adding), tuple(skipped)


def _known(known: Iterable[Any]) -> list[tuple[str, str]]:
    """``(label, text)`` pairs; tolerates anything with ``id`` / ``text``."""
    out = []
    for k in known or ():
        if isinstance(k, (tuple, list)) and len(k) == 2:
            out.append((str(k[0]), str(k[1])))
        else:
            out.append((str(getattr(k, "id", "")), str(getattr(k, "text", ""))))
    return out


def _today(today: "date | None") -> str:
    return (today or date.today()).isoformat()


# --------------------------------------------------------------------------- #
# Reading the folder.
# --------------------------------------------------------------------------- #


def saved_checklists(directory: "Path | None" = None) -> list[SavedChecklist]:
    """The checklists already in the user's profiles folder, by title.

    Only the folder's own ``*.md`` files: an uploaded checklist (a Word file,
    a spreadsheet) is not a file this module may append to.
    """
    folder = Path(directory) if directory is not None else user_profiles_dir()
    out = [
        SavedChecklist(name=p.name, title=p.title, path=p.source_path,
                       disciplines=tuple(p.disciplines), items=tuple(p.items))
        for p in _load_dir(folder).values() if p.source_path is not None
    ]
    return sorted(out, key=lambda c: (c.title.casefold(), c.name))


def _taken_names(folder: Path) -> set[str]:
    names = set(_load_dir(folder)) | set(_load_dir(builtin_profiles_dir()))
    return {n.casefold() for n in names}


def _free_name(folder: Path, slug: str) -> tuple[str, Path]:
    taken = _taken_names(folder)
    n = 1
    while True:
        name = slug if n == 1 else f"{slug}-{n}"
        path = folder / f"{name}.md"
        if name.casefold() not in taken and not path.exists():
            return name, path
        n += 1


# --------------------------------------------------------------------------- #
# Planning.
# --------------------------------------------------------------------------- #


def plan_new(
    title: Any,
    checks: Iterable[Any],
    *,
    disciplines: Any = (),
    known: Iterable[Any] = (),
    directory: "Path | None" = None,
    today: "date | None" = None,
) -> SavePlan:
    """A new checklist named ``title`` holding ``checks``.

    ``known`` is the user's own checklist items the run applied, as
    ``(run id, text)``; a check already among them is skipped. ``disciplines``
    are the sheet-number prefixes it applies to (none: every sheet).
    """
    folder = Path(directory) if directory is not None else user_profiles_dir()
    title = clean_title(title)
    prefixes = clean_prefixes(disciplines)
    adding, skipped = _split(_clean_checks(checks), _known(known))
    name, path = _free_name(folder, file_slug(title))
    lines = ["---", f"name: {name}", f"title: {title}"]
    if prefixes:
        lines.append(f"disciplines: {', '.join(p.upper() for p in prefixes)}")
    lines += ["version: 1", f"date: {_today(today)}", "---", "", f"# {title}", "",
              _NEW_FILE_NOTE, ""]
    lines += [f"- {c.text}" for c in adding]
    return SavePlan(path=path, name=name, title=title, disciplines=prefixes, adding=adding,
                    skipped=skipped, appending=False, text="\n".join(lines) + "\n")


def plan_append(
    target: "SavedChecklist | Path | str",
    checks: Iterable[Any],
    *,
    known: Iterable[Any] = (),
    today: "date | None" = None,
) -> SavePlan:
    """``checks`` added to the end of an existing checklist file.

    Read fresh from disk. The file's own lines are kept as they are; an
    integer ``version`` in its header is bumped and its ``date`` set to today,
    and its line endings are kept. A check already in the file is skipped.
    """
    path = Path(getattr(target, "path", target))
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    profile = parse_profile(raw, source_path=path, fallback_name=path.stem)
    present = [(f"item {i}", text) for i, text in enumerate(profile.items, 1)]
    adding, skipped = _split(_clean_checks(checks), present + _known(known))
    text = _appended(raw, adding, newline, _today(today)) if adding else raw
    return SavePlan(path=path, name=profile.name, title=profile.title,
                    disciplines=tuple(profile.disciplines), adding=adding, skipped=skipped,
                    appending=True, text=text)


def _appended(raw: str, adding: tuple[PickedCheck, ...], newline: str, today: str) -> str:
    lines = raw.splitlines()
    if lines and lines[0].lstrip("﻿").strip() == "---":
        close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        for i in range(1, close or 0):
            version = _VERSION_RE.match(lines[i])
            if version:
                lines[i] = f"{version.group(1)}{int(version.group(2)) + 1}"
            elif _DATE_RE.match(lines[i]):
                lines[i] = _DATE_RE.match(lines[i]).group(1) + today
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and not _ITEM_RE.match(lines[-1]):
        lines.append("")
    lines += [f"- {c.text}" for c in adding]
    return newline.join(lines) + newline


# --------------------------------------------------------------------------- #
# Writing.
# --------------------------------------------------------------------------- #


def _write(path: Path, text: str, *, replace: bool) -> None:
    """Write ``text`` to ``path`` through a temp file in the same folder.

    ``replace=False`` refuses to overwrite, atomically: the finished temp file
    is hard-linked into place, which fails with ``FileExistsError`` if
    ``path`` exists, however recently it appeared (two windows saving the
    same name at once). A folder that has no hard links (FAT, some network
    shares) gets an exclusive create instead, which refuses the same way.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".saving-", suffix=".md.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        if replace:
            os.replace(tmp, path)
            return
        try:
            os.link(tmp, path)
        except FileExistsError:
            raise
        except OSError:
            with open(path, "xb") as fh:
                fh.write(data)
    finally:
        try:
            os.unlink(tmp)            # moved by os.replace, or a link to drop
        except OSError:
            pass


def save_new(
    title: Any,
    checks: Iterable[Any],
    *,
    disciplines: Any = (),
    known: Iterable[Any] = (),
    directory: "Path | None" = None,
    today: "date | None" = None,
) -> SavePlan:
    """Plan a new checklist against the folder as it is now, and write it.

    Raises ``ValueError`` when every check is skipped (nothing to write) and
    ``OSError`` when the folder cannot be written.
    """
    for _attempt in range(5):
        plan = plan_new(title, checks, disciplines=disciplines, known=known,
                        directory=directory, today=today)
        if not plan.adding:
            raise ValueError("every picked check is already saved")
        try:
            _write(plan.path, plan.text, replace=False)
        except FileExistsError:
            continue                      # taken meanwhile: plan the next free name
        return plan
    raise OSError("could not find a free file name in the profiles folder")


def save_append(
    target: "SavedChecklist | Path | str",
    checks: Iterable[Any],
    *,
    known: Iterable[Any] = (),
    today: "date | None" = None,
) -> SavePlan:
    """Re-read the target, add the checks it does not already hold, and write it.

    Raises ``ValueError`` when every check is skipped and ``OSError`` when the
    file cannot be read or written.
    """
    plan = plan_append(target, checks, known=known, today=today)
    if not plan.adding:
        raise ValueError("every picked check is already in that checklist")
    _write(plan.path, plan.text, replace=True)
    return plan
