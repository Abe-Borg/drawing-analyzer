#!/usr/bin/env python3
"""Refuse a stable publish whose acceptance record does not say SHIP (N8).

``docs/releases/ACCEPTANCE-1.7.0.md`` put the stable ``v1.7.0`` tag on HOLD, and
about eight minutes after that record merged, ``v1.7.0`` was published as the
stable ``latest`` release anyway: the release every installed copy is offered
within a day. ``v1.6.0`` had shipped ahead of its record the same way. Nothing in
``release.yml`` read the record. ``publish`` needed only the build and the
automated gates, and a green automated suite is not acceptance (§19 Definition
of done).

This script is the one place that decides what a tag may publish:

* ``vX.Y.ZrcN`` publishes as a GitHub **pre-release** and needs no record. The
  updater reads ``releases/latest``, which never resolves to a pre-release, so a
  release candidate reaches testers without reaching installs. That is the
  sanctioned way to get a build out before its acceptance is recorded.
* ``vX.Y.Z`` publishes as the stable ``latest`` release only when
  ``docs/releases/ACCEPTANCE-X.Y.Z.md``:

  - is titled ``# Release acceptance record — X.Y.Z``;
  - has exactly one ``Release decision:`` line in its ``## Sign-off`` section,
    whose first word is ``SHIP`` and which does not also say ``HOLD``;
  - has a ``Deferrals / waivers`` table whose every filled row names an item,
    a scope, a justification and the owner's approval, and an ``Expiry`` date
    written ``YYYY-MM-DD`` that has not passed. The expiry is the last UTC day
    the waiver counts.

Waivers stand in for sections, never for the owner's decision. Both records say
a stable tag waits until "the Release decision line in the sign-off reads SHIP",
so a HOLD record with waivers still refuses. An expired waiver refuses even
under SHIP, because the owner shipped on the waiver's terms and those lapsed.
Anything the script cannot read also refuses: a record it cannot parse is not
a record that says SHIP.

The record is read from the tagged commit. Nothing here asks the record to name
its own commit (plan WP-23 step 10): a tracked file cannot contain the hash of
the commit that contains it. Binding the record to the tested commit and to the
built artifacts is later work. A tag runs the workflow file from the tagged
commit, so this check stops accidents, not a determined pusher. The independent
boundary is the protected ``release`` environment that ``publish`` deploys to
(``_plans/PROGRESS.md`` O-5).

On success, ``--github-output`` appends ``channel=prerelease|stable`` and
``valid_through=`` (the earliest waiver expiry, or empty) for ``publish``, which
takes the channel from here instead of re-deriving it and re-checks the expiry
just before publishing, since an environment approval can come days later. On
a refusal the script writes nothing and exits 1.

Pure standard library. It never imports the package, because the job that runs
it installs nothing.

Usage:  python scripts/check_release_acceptance.py --tag v1.8.0
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

CHANNEL_PRERELEASE = "prerelease"
CHANNEL_STABLE = "stable"

# MAJOR.MINOR.PATCH with an optional release-candidate suffix: a copy of
# ``drawing_analyzer.core.updates._VERSION_RE``, since this script cannot import
# the package. tests/test_release_acceptance_gate.py pins the two equal, so the
# gate passes only versions the updater can parse. Always ``fullmatch``: ``$``
# also matches before a trailing newline.
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?$")

_TITLE_RE = re.compile(
    "Release acceptance record[ \\t]*[\u2014\u2013-][ \\t]*`?([^\\s`]+)`?"
)
_H1_RE = re.compile(r"^#[ \t]+(.*?)[ \t]*$")
_H2_RE = re.compile(r"^##[ \t]+(.*?)[ \t]*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_DECISION_RE = re.compile(r"^\s*Release decision:(.*)$")
_SEPARATOR_CELL_RE = re.compile(r":?-+:?")
# A cell holding nothing but whitespace, dashes, underscores or the records'
# "unfilled" box is empty.
_BLANK_CELL_RE = re.compile("[\\s\\-_\u2013\u2014\u2b1c]*")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WORD_RE = re.compile(r"[^\W\d_]+")

_SIGN_OFF = "sign-off"
_WAIVERS = "deferrals / waivers"
# (attribute, header) for every column the gate reads, found by header name.
_COLUMNS = (
    ("item", "Item"),
    ("scope", "Scope"),
    ("justification", "Justification"),
    ("approval", "Owner approval / date"),
    ("expiry", "Expiry"),
)


@dataclass(frozen=True)
class Waiver:
    """One filled row of a record's Deferrals / waivers table."""

    item: str
    scope: str
    justification: str
    approval: str
    expiry: date
    line: int


@dataclass
class Record:
    """What the gate reads from an acceptance record.

    ``problems`` lists what could not be read. A record with any problem never
    publishes, however the rest of it reads.
    """

    title_version: str | None = None
    decision: str | None = None
    waivers: list[Waiver] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    """What one tag may publish. ``channel`` is None when it may publish nothing."""

    tag: str
    channel: str | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    valid_through: date | None = None

    @property
    def allowed(self) -> bool:
        return self.channel is not None and not self.problems


def release_channel(tag: str) -> tuple[str, str]:
    """``(version, channel)`` for a release tag. Raises ``ValueError`` otherwise."""
    version = tag[1:] if tag.startswith("v") else None
    match = _VERSION_RE.fullmatch(version) if version is not None else None
    if match is None:
        raise ValueError(
            f"{tag!r} is not a release tag. Release tags are 'v' + "
            "MAJOR.MINOR.PATCH with an optional rcN suffix (v1.8.0, v1.8.0rc1), "
            "the grammar the updater parses"
        )
    channel = CHANNEL_PRERELEASE if match.group(4) is not None else CHANNEL_STABLE
    return version, channel


def record_relpath(version: str) -> str:
    """The record's path in the repository, written with ``/`` on every OS."""
    return f"docs/releases/ACCEPTANCE-{version}.md"


def decision_problem(value: str) -> str | None:
    """Why a ``Release decision:`` value is not SHIP, or ``None`` when it is.

    The first word decides, and it must be exactly ``SHIP``. ``SHIPPED`` is not
    SHIP: the 1.6.0 record uses it for a release that jumped its hold. ``Ship``
    is not SHIP either. A value that also says ``HOLD`` is ambiguous: that is the
    template's own unfilled ``SHIP / HOLD``, which starts with SHIP. Anything
    after the word is a note, so ``HOLD   (owner flips to SHIP once ...)`` is a
    HOLD.
    """
    words = _WORD_RE.findall(value)
    shown = value if len(value) <= 80 else value[:77] + "..."
    if not words:
        return "its Release decision is empty; the owner writes SHIP or HOLD"
    if words[0] != "SHIP":
        return f"its Release decision reads '{shown}', not SHIP"
    if "HOLD" in words:
        return (
            f"its Release decision '{shown}' names both SHIP and HOLD (the "
            "template's unfilled 'SHIP / HOLD'?); the owner writes exactly one"
        )
    return None


def _heading_is(heading: str, name: str) -> bool:
    return heading.strip().lower().startswith(name)


def _is_closer(line: str, fence: str) -> bool:
    """Whether ``line`` closes a block opened by ``fence``: same character, at
    least as long, and nothing else on the line."""
    return re.fullmatch(
        r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*", line
    ) is not None


def _outline(lines: list[str]):
    """``(h1 texts, [(h2 text, body)])``, where body is ``[(line, text, fenced)]``.

    A ``#`` line inside a fenced code block is not a heading. The Sign-off is
    itself a fenced block, and a fenced ``## Sign-off`` must not open a section.
    """
    h1s: list[str] = []
    sections: list[tuple[str, list[tuple[int, str, bool]]]] = []
    body: list[tuple[int, str, bool]] | None = None
    fence: str | None = None
    for number, line in enumerate(lines, start=1):
        if fence is not None:
            if _is_closer(line, fence):
                fence = None
            if body is not None:
                body.append((number, line, True))
            continue
        marker = _FENCE_RE.match(line)
        if marker:
            fence = marker.group(1)
            if body is not None:
                body.append((number, line, True))
            continue
        h1 = _H1_RE.match(line)
        if h1:
            h1s.append(h1.group(1))
            body = None
            continue
        h2 = _H2_RE.match(line)
        if h2:
            body = []
            sections.append((h2.group(1), body))
            continue
        if body is not None:
            body.append((number, line, False))
    return h1s, sections


def _cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", inner)]


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def _is_blank(cell: str) -> bool:
    return _BLANK_CELL_RE.fullmatch(cell) is not None


def _read_waivers(body: list[tuple[int, str, bool]]) -> tuple[list[Waiver], list[str]]:
    """The waivers of one Deferrals / waivers section, and what could not be read."""
    tables: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] | None = None
    for number, line, fenced in body:
        if not fenced and line.lstrip().startswith("|"):
            if current is None:
                current = []
                tables.append(current)
            current.append((number, line))
        else:
            current = None
    if not tables:
        return [], [
            "its Deferrals / waivers section has no table (keep the table, with "
            "its blank row, when nothing is waived)"
        ]
    if len(tables) > 1:
        return [], [
            f"its Deferrals / waivers section has {len(tables)} tables; the gate "
            "reads exactly one"
        ]
    rows = tables[0]
    header = [_normalized(cell) for cell in _cells(rows[0][1])]
    separator = _cells(rows[1][1]) if len(rows) > 1 else []
    if len(separator) != len(header) or not all(
        _SEPARATOR_CELL_RE.fullmatch(cell) for cell in separator
    ):
        return [], ["its waiver table has no header separator row (|---|---|...)"]
    index: dict[str, int] = {}
    for attribute, name in _COLUMNS:
        positions = [i for i, cell in enumerate(header) if cell == _normalized(name)]
        if len(positions) == 1:
            index[attribute] = positions[0]
    if len(index) != len(_COLUMNS):
        expected = " | ".join(name for _attribute, name in _COLUMNS)
        return [], [
            f"its waiver table header does not name each column once (expected "
            f"| {expected} |)"
        ]

    waivers: list[Waiver] = []
    problems: list[str] = []
    for number, line in rows[2:]:
        cells = _cells(line)
        if len(cells) != len(header):
            problems.append(
                f"the waiver row on line {number} has {len(cells)} cells; its "
                f"header has {len(header)}"
            )
            continue
        if all(_is_blank(cell) for cell in cells):
            continue  # the template's empty row: an empty table, not a waiver
        values = {attribute: cells[i] for attribute, i in index.items()}
        missing = [name for attribute, name in _COLUMNS if _is_blank(values[attribute])]
        label = values["item"] if not _is_blank(values["item"]) else "(no item)"
        if missing:
            problems.append(
                f"the waiver '{label}' on line {number} is incomplete: it has no "
                f"{', '.join(missing)}"
            )
            continue
        expiry = None
        if _ISO_DATE_RE.fullmatch(values["expiry"]):
            try:
                expiry = date.fromisoformat(values["expiry"])
            except ValueError:
                expiry = None
        if expiry is None:
            problems.append(
                f"the waiver '{label}' on line {number} has Expiry "
                f"'{values['expiry']}', which is not a date written YYYY-MM-DD"
            )
            continue
        waivers.append(Waiver(
            item=values["item"],
            scope=values["scope"],
            justification=values["justification"],
            approval=values["approval"],
            expiry=expiry,
            line=number,
        ))
    return waivers, problems


def parse_record(text: str) -> Record:
    """Read the title, the Sign-off decision and the waivers of one record."""
    record = Record()
    h1s, sections = _outline(text.splitlines())

    if not h1s:
        record.problems.append(
            "it has no title; its first line should read "
            "'# Release acceptance record \u2014 <version>'"
        )
    else:
        title = _TITLE_RE.fullmatch(h1s[0].strip())
        if title is None:
            record.problems.append(
                f"its title '{h1s[0]}' does not name a version (expected "
                "'# Release acceptance record \u2014 <version>')"
            )
        else:
            record.title_version = title.group(1)

    sign_offs = [body for heading, body in sections if _heading_is(heading, _SIGN_OFF)]
    if len(sign_offs) != 1:
        record.problems.append(
            "it has no '## Sign-off' section" if not sign_offs
            else f"it has {len(sign_offs)} '## Sign-off' sections; the gate reads exactly one"
        )
    else:
        decisions = [
            (number, match.group(1).strip())
            for number, line, _fenced in sign_offs[0]
            if (match := _DECISION_RE.match(line))
        ]
        if not decisions:
            record.problems.append("its Sign-off has no 'Release decision:' line")
        elif len(decisions) > 1:
            where = ", ".join(str(number) for number, _value in decisions)
            record.problems.append(
                f"its Sign-off has {len(decisions)} 'Release decision:' lines "
                f"(lines {where}); the gate reads exactly one"
            )
        else:
            record.decision = decisions[0][1]

    waiver_sections = [body for heading, body in sections if _heading_is(heading, _WAIVERS)]
    if len(waiver_sections) != 1:
        record.problems.append(
            "it has no '## Deferrals / waivers' section" if not waiver_sections
            else f"it has {len(waiver_sections)} '## Deferrals / waivers' sections; "
                 "the gate reads exactly one"
        )
    else:
        record.waivers, problems = _read_waivers(waiver_sections[0])
        record.problems.extend(problems)
    return record


def evaluate(tag: str, *, root: Path, today: date) -> Verdict:
    """What ``tag`` may publish, judged against the records under ``root``."""
    verdict = Verdict(tag=tag)
    try:
        version, channel = release_channel(tag)
    except ValueError as exc:
        verdict.problems.append(str(exc))
        return verdict

    if channel == CHANNEL_PRERELEASE:
        stable = re.sub(r"rc\d+$", "", version)
        verdict.channel = channel
        verdict.notes.append(
            f"{tag} is a release candidate. It publishes as a GitHub pre-release, "
            "which the updater never offers to installed copies, so it needs no "
            f"acceptance record. The stable v{stable} tag will need "
            f"{record_relpath(stable)} to say SHIP."
        )
        return verdict

    relpath = record_relpath(version)
    path = root / "docs" / "releases" / f"ACCEPTANCE-{version}.md"
    if not path.is_file():
        verdict.problems.append(
            f"{relpath} does not exist, and a stable tag needs its acceptance record"
        )
        return verdict
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        verdict.problems.append(f"could not read {relpath}: {exc}")
        return verdict

    record = parse_record(text)
    verdict.problems.extend(f"{relpath}: {problem}" for problem in record.problems)
    if record.title_version is not None and record.title_version != version:
        verdict.problems.append(
            f"{relpath} is titled for {record.title_version}, not {version}; a "
            "record copied forward is not this release's record"
        )
    if record.decision is not None:
        problem = decision_problem(record.decision)
        if problem is not None:
            verdict.problems.append(f"{relpath}: {problem}")
    for waiver in record.waivers:
        if waiver.expiry < today:
            verdict.problems.append(
                f"{relpath}: the waiver '{waiver.item}' expired on "
                f"{waiver.expiry.isoformat()} (today is {today.isoformat()} UTC); "
                "the owner renews it or the section is recorded"
            )
    if verdict.problems:
        return verdict

    verdict.channel = CHANNEL_STABLE
    verdict.valid_through = min((w.expiry for w in record.waivers), default=None)
    verdict.notes.append(
        f"{tag} publishes as the stable latest release: {relpath} is titled for "
        f"{version} and its Release decision reads SHIP."
    )
    if record.waivers:
        verdict.notes.append(
            f"{len(record.waivers)} waiver(s), none expired. publish re-checks the "
            f"earliest expiry, {verdict.valid_through.isoformat()}, just before it "
            "publishes:"
        )
        verdict.notes.extend(
            f"  - {w.item} (scope: {w.scope}; approved: {w.approval}; "
            f"valid through {w.expiry.isoformat()})"
            for w in record.waivers
        )
    else:
        verdict.notes.append("It lists no waivers.")
    return verdict


def _remedy(tag: str) -> str:
    try:
        version, _channel = release_channel(tag)
    except ValueError:
        return (
            "Nothing was published. Push a tag of the form v1.8.0 (stable) or "
            "v1.8.0rc1 (release candidate)."
        )
    return (
        "Nothing was published. A stable tag is offered to every installed copy, "
        f"so {record_relpath(version)} must say SHIP: record its sections 2-6, or "
        "have the owner waive them in its Deferrals / waivers table (every column "
        "filled, Expiry written YYYY-MM-DD), set its Sign-off 'Release decision:' "
        "to SHIP, and tag the commit that carries that record. To get this build "
        "to testers first, tag a release candidate instead (both version literals "
        f"set to {version}rc1, tag v{version}rc1): it publishes as a pre-release "
        "and needs no record."
    )


def main(argv: list[str] | None = None, *, today: date | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--tag", required=True, help="the pushed tag, e.g. v1.8.0 or v1.8.0rc1")
    parser.add_argument(
        "--root", type=Path, default=_REPO_ROOT,
        help="the checkout whose docs/releases/ is read (default: this one)",
    )
    parser.add_argument(
        "--github-output", type=Path, default=None, metavar="PATH",
        help="on success, append channel= and valid_through= here (the job's $GITHUB_OUTPUT)",
    )
    args = parser.parse_args(argv)
    if today is None:
        today = datetime.now(timezone.utc).date()

    verdict = evaluate(args.tag, root=args.root, today=today)
    if not verdict.allowed:
        print(
            f"release acceptance check FAILED: {args.tag!r} may not publish.",
            file=sys.stderr,
        )
        for problem in verdict.problems:
            print(f"  - {problem}", file=sys.stderr)
        print(_remedy(args.tag), file=sys.stderr)
        return 1

    for note in verdict.notes:
        print(note)
    if args.github_output is not None:
        valid_through = verdict.valid_through.isoformat() if verdict.valid_through else ""
        try:
            with open(args.github_output, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(f"channel={verdict.channel}\nvalid_through={valid_through}\n")
        except OSError as exc:
            print(
                f"release acceptance check FAILED: could not write "
                f"{args.github_output}: {exc}",
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
