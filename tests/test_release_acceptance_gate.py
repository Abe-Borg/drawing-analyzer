"""N8 (remediation WP-23.1) — a stable tag cannot publish past its acceptance record.

``v1.7.0`` was published as the stable ``latest`` release about eight minutes
after ``docs/releases/ACCEPTANCE-1.7.0.md`` merged saying HOLD (plan §1.2), and
``v1.6.0`` shipped ahead of its record too: nothing in ``release.yml`` read the
record. ``scripts/check_release_acceptance.py`` now decides, once, what a tag may
publish, and ``publish`` takes that decision from it:

* an ``rcN`` tag publishes as a GitHub pre-release and needs no record;
* a stable tag needs ``docs/releases/ACCEPTANCE-<version>.md``, titled for that
  version, whose Sign-off ``Release decision:`` reads ``SHIP`` and whose every
  waiver is complete and unexpired. Waivers stand in for sections, never for
  the owner's decision, so they cannot lift a HOLD.

These tests pin three things, in the ``test_browser_suite_gate.py`` shape:

1. the decision, against the **real** record format: the verbatim 1.6.0 and
   1.7.0 sign-offs, the template itself, and every committed record;
2. the failure paths fail closed (nothing written, nothing published);
3. the workflow runs it where it gates: in ``publish``'s own ``needs`` chain,
   with ``publish`` taking the channel from it instead of re-deriving it.

The workflow is read as text, not PyYAML (see ``test_browser_suite_gate``).
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_release_acceptance.py"
_RELEASE = _REPO_ROOT / ".github" / "workflows" / "release.yml"
_TEMPLATE = _REPO_ROOT / "docs" / "RELEASE_ACCEPTANCE_TEMPLATE.md"
_RECORDS = _REPO_ROOT / "docs" / "releases"

_TODAY = date(2026, 9, 23)
_HEADER = "| Item | Scope | Justification | Owner approval / date | Expiry |"


def _load_script():
    """Import the checker by path (it is a script, not a package).

    Registered in ``sys.modules`` first, as importlib's own recipe does: the
    script's dataclasses resolve their string annotations through it.
    """
    spec = importlib.util.spec_from_file_location("_check_release_acceptance", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


@pytest.fixture
def script():
    return _load_script()


# --- the real record format --------------------------------------------------
#
# Verbatim from the records as they stood when each tag was published. They are
# embedded rather than read from docs/releases/ so that the owner's correction of
# those files (PROGRESS.md O-1) cannot quietly retire the incident regressions;
# test_every_committed_record_is_readable_by_the_gate reads the live files.

_V170_TITLE = "# Release acceptance record — 1.7.0"

_V170_WAIVERS = """\
## Deferrals / waivers (owner-approved, in writing)

| Item | Scope | Justification | Owner approval / date | Expiry |
|---|---|---|---|---|
| | | | | |
"""

_V170_SIGN_OFF = """\
## Sign-off

```
Automated gates:   PASS on the merged code 1649ba7 (local run_acceptance.py,
                   build gate deferred to CI; ci.yml run 35654462327 all green).
                   Re-cite the tag run's `gates` / `gates-windows` jobs once tagged.
                   run_acceptance.py on Windows + branch-protection evidence have
                   no CI coverage and are unrecorded.
Live canary:       NOT RUN
Manual sections:   INCOMPLETE       (§§2-6 unstarted)

Stable tag:        HOLD — §§2-6 unrecorded and no waivers filed; an RC tag
                   (1.7.0rc1) is the sanctioned interim.

Release decision:  HOLD   (owner flips to SHIP once §§2-6 are recorded or
                   waived in the table above)

Owner signature: ______________________  Date: __________
```
"""

_V160_DECISION = (
    "Release decision:  SHIPPED 2026-09-15 17:23:55Z, ahead of §§2-6.\n"
    "                   Complete them as catch-up; they no longer gate.\n"
)


def _sign_off(decision_line: str) -> str:
    return (
        "## Sign-off\n\n```\n"
        "Automated gates:   PASS\n"
        "Live canary:       PASS\n"
        "Manual sections:   COMPLETE\n\n"
        f"{decision_line}\n"
        "Owner signature: ______________________  Date: __________\n"
        "```\n"
    )


def _record(
    version: str,
    *,
    decision: str = "SHIP",
    waivers: tuple[tuple[str, ...], ...] = (),
    title: str | None = None,
) -> str:
    """A record in the template's shape: title, waiver table, sign-off."""
    rows = "\n".join("| " + " | ".join(row) + " |" for row in waivers)
    return (
        f"{title if title is not None else f'# Release acceptance record — {version}'}\n\n"
        "Copy of `docs/RELEASE_ACCEPTANCE_TEMPLATE.md` for this candidate.\n\n"
        "## 2. Live API canary (§19.3 — opt-in, billable)\n\n"
        "- [x] Digest request schema + structured findings parse.\n\n"
        "## Deferrals / waivers (owner-approved, in writing)\n\n"
        f"{_HEADER}\n|---|---|---|---|---|\n"
        f"{rows or '| | | | | |'}\n\n"
        + _sign_off(f"Release decision:  {decision}\n")
    )


def _waiver(expiry: str = "2026-10-15", **cells: str) -> tuple[str, ...]:
    row = {
        "item": "§2 live API canary",
        "scope": "1.8.0 only",
        "justification": "No live API budget this cycle",
        "approval": "owner, 2026-09-20",
        "expiry": expiry,
    }
    row.update(cells)
    return (row["item"], row["scope"], row["justification"], row["approval"],
            row["expiry"])


def _write(root: Path, version: str, text: str, *, encoding: str = "utf-8",
           newline: str | None = None) -> Path:
    path = root / "docs" / "releases" / f"ACCEPTANCE-{version}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding=encoding, newline=newline) as fh:
        fh.write(text)
    return path


def _run(script, root: Path, tag: str, *, today: date = _TODAY):
    """``(exit code, $GITHUB_OUTPUT contents)`` for one gate run.

    A fresh output file per run: the script appends, as ``$GITHUB_OUTPUT``
    requires, so a reused file would carry an earlier run's lines.
    """
    out = root / "github_output.txt"
    out.unlink(missing_ok=True)
    rc = script.main(
        ["--tag", tag, "--root", str(root), "--github-output", str(out)],
        today=today,
    )
    return rc, (out.read_text(encoding="utf-8") if out.exists() else None)


# --- release candidates -----------------------------------------------------

def test_an_rc_tag_publishes_as_a_prerelease_without_a_record(script, tmp_path, capsys):
    """RC tags keep publishing: no record exists here at all."""
    rc, output = _run(script, tmp_path, "v1.8.0rc1")
    assert rc == 0
    assert output == "channel=prerelease\nvalid_through=\n"
    assert "pre-release" in capsys.readouterr().out


def test_an_rc_tag_ignores_a_hold_record(script, tmp_path):
    """The record gates the stable tag, not its candidates (the sanctioned interim)."""
    _write(tmp_path, "1.8.0", _record("1.8.0", decision="HOLD"))
    assert _run(script, tmp_path, "v1.8.0rc2") == (0, "channel=prerelease\nvalid_through=\n")


@pytest.mark.parametrize("tag, channel", [
    ("v1.0.0rc1", "prerelease"),
    ("v1.3.0rc1", "prerelease"),
    ("v1.7.0", "stable"),
    ("v10.20.30rc40", "prerelease"),
    ("v10.20.30", "stable"),
])
def test_the_channel_is_decided_by_the_release_grammar(script, tag, channel):
    """Every tag this repository has published parses to the channel it got."""
    assert script.release_channel(tag) == (tag[1:], channel)


def test_the_tag_grammar_is_the_updaters(script):
    """One grammar: the updater parses what the gate lets through.

    The script cannot import the package (the job installs nothing), so the
    pattern is a copy; this is what stops the copy drifting.
    """
    from drawing_analyzer.core import updates

    assert script._VERSION_RE.pattern == updates._VERSION_RE.pattern


@pytest.mark.parametrize("tag", [
    "1.8.0",            # no "v": the manifest URL is built from v<version>
    "V1.8.0",
    "v1.8",
    "v1.8.0-rc1",       # `*rc*` used to publish this as a pre-release
    "v1.8.0rc",
    "v1.8.0.post1",
    "v1.8.0 ",
    "v1.8.0\n",
    "release-1.8.0",
    "v",
    "",
])
def test_a_tag_outside_the_release_grammar_publishes_nothing(script, tmp_path, tag, capsys):
    _write(tmp_path, "1.8.0", _record("1.8.0"))
    assert _run(script, tmp_path, tag) == (1, None)
    assert "MAJOR.MINOR.PATCH" in capsys.readouterr().err


# --- stable tags: the record ------------------------------------------------

def test_a_stable_tag_without_a_record_is_refused(script, tmp_path, capsys):
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    err = capsys.readouterr().err
    assert "docs/releases/ACCEPTANCE-1.8.0.md" in err
    assert "does not exist" in err
    # The remedy names the sanctioned interim, so a refusal is never a dead end.
    assert "v1.8.0rc1" in err


def test_the_incident_record_is_refused(script, tmp_path, capsys):
    """N8, as it happened: tag v1.7.0 against the record that said HOLD."""
    _write(tmp_path, "1.7.0",
           f"{_V170_TITLE}\n\n{_V170_WAIVERS}\n{_V170_SIGN_OFF}")
    assert _run(script, tmp_path, "v1.7.0") == (1, None)
    err = capsys.readouterr().err
    assert "HOLD" in err
    assert "not SHIP" in err


def test_ship_publishes_as_the_stable_latest_release(script, tmp_path, capsys):
    _write(tmp_path, "1.8.0", _record("1.8.0"))
    assert _run(script, tmp_path, "v1.8.0") == (0, "channel=stable\nvalid_through=\n")
    out = capsys.readouterr().out
    assert "ACCEPTANCE-1.8.0.md" in out
    assert "SHIP" in out


def test_shipped_is_not_ship(script, tmp_path):
    """The 1.6.0 record's line, which describes a release that jumped its hold."""
    text = _record("1.6.0").replace(
        "Release decision:  SHIP\n", _V160_DECISION)
    _write(tmp_path, "1.6.0", text)
    assert _run(script, tmp_path, "v1.6.0") == (1, None)


def test_the_templates_placeholder_is_not_a_decision(script, tmp_path, capsys):
    """``SHIP / HOLD`` starts with SHIP; an unfilled copy must still refuse."""
    _write(tmp_path, "1.8.0", _record("1.8.0", decision="SHIP / HOLD"))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    assert "both SHIP and HOLD" in capsys.readouterr().err


@pytest.mark.parametrize("decision", [
    "HOLD",
    "HOLD   (owner flips to SHIP once §§2-6 are recorded)",
    "SHIPPED",
    "Ship",
    "ship",
    "SHIPIT",
    "SHIP (was HOLD until the canary ran)",
    "APPROVED",
    "PASS",
    "",
    "______",
])
def test_anything_but_ship_is_refused(script, tmp_path, decision):
    _write(tmp_path, "1.8.0", _record("1.8.0", decision=decision))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


@pytest.mark.parametrize("decision", [
    "SHIP",
    "SHIP   (§§2-6 recorded 2026-10-02)",
    "SHIP — owner",
    "SHIP.",
])
def test_ship_may_carry_a_note(script, tmp_path, decision):
    _write(tmp_path, "1.8.0", _record("1.8.0", decision=decision))
    assert _run(script, tmp_path, "v1.8.0")[0] == 0


def test_a_record_for_another_version_is_refused(script, tmp_path, capsys):
    """A SHIP record copied forward without being redone is not 1.8.0's record."""
    _write(tmp_path, "1.8.0",
           _record("1.8.0", title="# Release acceptance record — 1.7.0"))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    err = capsys.readouterr().err
    assert "1.7.0" in err
    assert "1.8.0" in err


def test_a_record_the_gate_cannot_identify_is_refused(script, tmp_path):
    for title in ("# Release acceptance record (Phase 27, §19.9)",
                  "Release acceptance record — 1.8.0",
                  "## Release acceptance record — 1.8.0"):
        _write(tmp_path, "1.8.0", _record("1.8.0", title=title))
        assert _run(script, tmp_path, "v1.8.0") == (1, None), title


def test_the_decision_is_read_from_the_sign_off_only(script, tmp_path):
    """A SHIP anywhere else, e.g. a quoted instruction, is not the decision.

    The Sign-off here has no decision line at all, so a reader that scanned the
    whole file would find exactly one, SHIP, and publish.
    """
    text = _record("1.8.0").replace("Release decision:  SHIP\n", "").replace(
        "Copy of", "Release decision:  SHIP\n\nCopy of", 1)
    _write(tmp_path, "1.8.0", text)
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


def test_the_sign_off_needs_exactly_one_decision(script, tmp_path, capsys):
    none = _record("1.8.0").replace("Release decision:  SHIP\n", "")
    _write(tmp_path, "1.8.0", none)
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    assert "no 'Release decision:' line" in capsys.readouterr().err

    two = _record("1.8.0").replace(
        "Release decision:  SHIP\n",
        "Release decision:  SHIP\nRelease decision:  SHIP\n")
    _write(tmp_path, "1.8.0", two)
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


def test_a_record_without_a_sign_off_is_refused(script, tmp_path):
    text = _record("1.8.0").replace("## Sign-off", "## Notes")
    _write(tmp_path, "1.8.0", text)
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


def test_a_heading_inside_a_code_block_is_not_a_section(script, tmp_path):
    """The Sign-off is fenced; a fenced ``## Sign-off`` must not open a section.

    The real Sign-off is renamed away, so the only ``## Sign-off`` left is the
    fenced one: a fence-blind reader would find SHIP there and publish.
    """
    text = _record("1.8.0", decision="HOLD").replace(
        "## Sign-off", "## Notes").replace(
        "## Deferrals",
        "~~~~\n## Sign-off\nRelease decision:  SHIP\n```\n~~~~\n\n## Deferrals", 1)
    _write(tmp_path, "1.8.0", text)
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


def test_windows_line_endings_and_a_bom_are_read(script, tmp_path):
    """The owner edits these records on Windows."""
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(_waiver(),)),
           encoding="utf-8-sig", newline="\r\n")
    assert _run(script, tmp_path, "v1.8.0") == (
        0, "channel=stable\nvalid_through=2026-10-15\n")


def test_an_unreadable_record_is_refused(script, tmp_path, capsys):
    path = _write(tmp_path, "1.8.0", "")
    path.write_bytes(b"# Release acceptance record \xe2\x80 1.8.0\n\xff\xfe")
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    assert "could not read" in capsys.readouterr().err


# --- stable tags: waivers ---------------------------------------------------

def test_an_unexpired_waiver_publishes(script, tmp_path, capsys):
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(_waiver("2026-10-15"),)))
    assert _run(script, tmp_path, "v1.8.0") == (
        0, "channel=stable\nvalid_through=2026-10-15\n")
    assert "§2 live API canary" in capsys.readouterr().out


def test_an_expired_waiver_refuses_even_under_ship(script, tmp_path, capsys):
    """The owner shipped on the waiver's terms; after its expiry those lapse."""
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(_waiver("2026-09-22"),)))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    err = capsys.readouterr().err
    assert "expired" in err
    assert "2026-09-22" in err
    assert "§2 live API canary" in err


def test_a_waiver_is_valid_through_its_expiry_day(script, tmp_path):
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(_waiver("2026-09-23"),)))
    assert _run(script, tmp_path, "v1.8.0", today=date(2026, 9, 23))[0] == 0
    assert _run(script, tmp_path, "v1.8.0", today=date(2026, 9, 24)) == (1, None)


def test_waivers_never_override_hold(script, tmp_path, capsys):
    """Waivers stand in for sections, not for the decision (the records' own rule)."""
    _write(tmp_path, "1.8.0", _record(
        "1.8.0", decision="HOLD", waivers=(_waiver("2027-01-01"),)))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    assert "HOLD" in capsys.readouterr().err


def test_the_earliest_expiry_is_what_publish_rechecks(script, tmp_path):
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(
        _waiver("2026-12-01", item="§4 viewer acceptance"),
        _waiver("2026-10-01", item="§6 performance"),
    )))
    assert _run(script, tmp_path, "v1.8.0") == (
        0, "channel=stable\nvalid_through=2026-10-01\n")


def test_the_blank_template_row_is_not_a_waiver(script, tmp_path):
    """Every record carries ``| | | | | |``; it is an empty table, not a waiver."""
    text = _record("1.8.0").replace("| | | | | |", "| | | | | |\n|  |  |  |  |  |")
    _write(tmp_path, "1.8.0", text)
    assert _run(script, tmp_path, "v1.8.0") == (0, "channel=stable\nvalid_through=\n")


@pytest.mark.parametrize("column", ["item", "scope", "justification", "approval", "expiry"])
@pytest.mark.parametrize("blank", ["", "—", "-", "⬜", "___"])
def test_an_incomplete_waiver_is_refused(script, tmp_path, column, blank, capsys):
    """Scope, justification, approver and expiry are the waiver (plan WP-23 step 9)."""
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(_waiver(**{column: blank}),)))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    assert "waiver" in capsys.readouterr().err


@pytest.mark.parametrize("expiry", [
    "2026-13-01", "2026-02-30", "10/15/2026", "15.10.2026", "20261015",
    "2026-W42-3", "2026-10-15T00:00", "end of October", "none", "never", "n/a",
])
def test_a_waiver_expiry_must_be_an_iso_date(script, tmp_path, expiry, capsys):
    _write(tmp_path, "1.8.0", _record("1.8.0", waivers=(_waiver(expiry),)))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_a_malformed_waiver_table_is_refused(script, tmp_path):
    base = _record("1.8.0", waivers=(_waiver(),))
    cases = {
        "missing section": base.replace("## Deferrals / waivers", "## Deferrals"),
        "no table": re.sub(r"\| Item.*?\n\n", "No waivers.\n\n", base, flags=re.S),
        "short row": base.replace(" | 2026-10-15 |", " |"),
        "no separator": base.replace("|---|---|---|---|---|\n", ""),
        "renamed column": base.replace("| Expiry |", "| Until |"),
        "second table": base.replace(
            "\n\n## Sign-off", "\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n## Sign-off"),
    }
    for name, text in cases.items():
        _write(tmp_path, "1.8.0", text)
        assert _run(script, tmp_path, "v1.8.0") == (1, None), name


def test_the_waiver_columns_are_found_by_name(script, tmp_path):
    """An inserted column does not shift what the gate reads.

    The column inserted before Expiry holds a far-future date, so a reader that
    took the fifth cell would find an unexpired waiver and publish; the real
    Expiry has lapsed.
    """
    text = _record("1.8.0", waivers=(_waiver("2026-09-01"),)).replace(
        "| Owner approval / date | Expiry |",
        "| Owner approval / date | Reviewed | Expiry |").replace(
        "|---|---|---|---|---|", "|---|---|---|---|---|---|").replace(
        " | 2026-09-01 |", " | 2099-01-01 | 2026-09-01 |")
    _write(tmp_path, "1.8.0", text)
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


# --- the template and the committed records ----------------------------------

def _from_template(version: str, decision: str | None, waiver_row: str | None = None) -> str:
    """The shipped template, filled in the way its own instructions say."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    assert lines[0].startswith("# "), lines[0]
    lines[0] = f"# Release acceptance record — {version}\n"
    text = "".join(lines)
    if decision is not None:
        assert text.count("Release decision:  SHIP / HOLD") == 1
        text = text.replace("Release decision:  SHIP / HOLD", f"Release decision:  {decision}")
    if waiver_row is not None:
        assert text.count("| | | | | |") == 1
        text = text.replace("| | | | | |", waiver_row)
    return text


def test_the_template_as_shipped_is_refused(script, tmp_path):
    """Copied and never filled in: no version in the title, no decision."""
    _write(tmp_path, "1.8.0", _TEMPLATE.read_text(encoding="utf-8"))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)
    _write(tmp_path, "1.8.0", _from_template("1.8.0", decision=None))
    assert _run(script, tmp_path, "v1.8.0") == (1, None)


def test_the_template_filled_in_as_documented_passes(script, tmp_path):
    """The gate reads the template's own format: title, Sign-off, waiver table."""
    _write(tmp_path, "1.8.0", _from_template("1.8.0", decision="SHIP"))
    assert _run(script, tmp_path, "v1.8.0") == (0, "channel=stable\nvalid_through=\n")

    row = "| " + " | ".join(_waiver("2026-10-15")) + " |"
    _write(tmp_path, "1.8.0", _from_template("1.8.0", decision="SHIP", waiver_row=row))
    assert _run(script, tmp_path, "v1.8.0") == (
        0, "channel=stable\nvalid_through=2026-10-15\n")
    assert _run(script, tmp_path, "v1.8.0", today=date(2026, 10, 16)) == (1, None)


def test_the_template_documents_what_the_gate_reads():
    """An owner filling the record in must be told the format that gates."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert "scripts/check_release_acceptance.py" in text
    assert "YYYY-MM-DD" in text
    assert "# Release acceptance record — <version>" in text


def _committed_records() -> list[Path]:
    return sorted(_RECORDS.glob("ACCEPTANCE-*.md"))


def test_there_are_committed_records_to_check():
    assert _committed_records(), "no docs/releases/ACCEPTANCE-*.md to read"


@pytest.mark.parametrize("path", _committed_records(), ids=lambda p: p.name)
def test_every_committed_record_is_readable_by_the_gate(script, path):
    """The gate must read the real format, so every real record must parse.

    Structure only: this pins neither record's decision (the 1.7.0 record is
    the owner's to correct, PROGRESS.md O-1). A record added in a release-prep
    PR is checked here, at PR time, rather than first at tag time.
    """
    version = path.stem.removeprefix("ACCEPTANCE-")
    record = script.parse_record(path.read_text(encoding="utf-8-sig"))
    assert record.problems == [], (
        f"the publish gate cannot read {path.name}: {record.problems}"
    )
    assert record.title_version == version
    assert record.decision is not None


# --- running as the workflow does ---------------------------------------------

def test_the_script_needs_nothing_beyond_the_standard_library():
    """The ``acceptance`` job installs nothing: stdlib imports only."""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in a standalone script"
            imported.add((node.module or "").split(".")[0])
    assert imported, "no imports found"
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


def test_the_script_runs_standalone_and_fails_closed(tmp_path):
    """As the job runs it: a subprocess, the repo root as the working directory."""
    out = tmp_path / "out.txt"
    ok = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tag", "v1.8.0rc1",
         "--root", str(tmp_path), "--github-output", str(out)],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert ok.returncode == 0, ok.stderr
    assert out.read_text(encoding="utf-8") == "channel=prerelease\nvalid_through=\n"

    out.unlink()
    refused = subprocess.run(
        [sys.executable, str(_SCRIPT), "--tag", "v1.8.0",
         "--root", str(tmp_path), "--github-output", str(out)],
        cwd=_REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert refused.returncode == 1
    assert "ACCEPTANCE-1.8.0.md" in refused.stderr
    assert not out.exists()


def test_an_unwritable_output_fails_closed(script, tmp_path, capsys):
    """``publish`` needs the channel; a pass that cannot report it is a refusal."""
    _write(tmp_path, "1.8.0", _record("1.8.0"))
    rc = script.main(
        ["--tag", "v1.8.0", "--root", str(tmp_path), "--github-output", str(tmp_path)],
        today=_TODAY,
    )
    assert rc == 1
    assert "could not write" in capsys.readouterr().err


# --- the wiring (the part that makes the rest matter) ----------------------

def _jobs() -> dict[str, str]:
    """Each top-level job's text, keyed by job id."""
    text = _RELEASE.read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z][\w-]*):[ \t]*$", body, flags=re.MULTILINE)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts), 2)}


def _code(block: str) -> str:
    """A job's text without its comment lines (YAML and shell alike)."""
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )


def _job_key(block: str, key: str) -> list[str]:
    """Every job-level ``key:`` value (four-space indent: not a step's)."""
    return re.findall(rf"^    {re.escape(key)}: (.+?)[ \t]*$", block, re.MULTILINE)


def test_publish_needs_the_acceptance_job():
    """The gate is a dependency of ``publish``, not an advisory side job.

    A job in ``needs`` that fails or is skipped skips ``publish`` (plan WP-23
    step 11: gate ``publish``, not merely an advisory check).
    """
    jobs = _jobs()
    assert "acceptance" in jobs, "the acceptance job is gone"
    assert _job_key(jobs["publish"], "needs") == ["[build, gates, gates-windows, acceptance]"]


def test_publish_cannot_run_past_a_failed_gate():
    """A status function in ``publish``'s ``if:`` would run it after a refusal."""
    publish = _jobs()["publish"]
    assert _job_key(publish, "if") == ["startsWith(github.ref, 'refs/tags/')"]
    for escape in ("always()", "cancelled()", "failure()", "continue-on-error"):
        assert escape not in _code(publish), escape


def test_the_acceptance_job_runs_the_gate_on_every_tag():
    """RC tags included: a skipped job in ``needs`` skips ``publish`` as well."""
    job = _jobs()["acceptance"]
    code = _code(job)
    assert _job_key(job, "if") == ["startsWith(github.ref, 'refs/tags/')"]
    # Read-only and credential-free, like `gates`: it runs repo code.
    assert "      contents: read" in code
    assert "write" not in code
    assert "persist-credentials: false" in code
    # The refusal must fail the job: nothing may swallow the exit code.
    assert "continue-on-error" not in code
    assert "\n        id: decide\n        run: python scripts/check_release_acceptance.py" \
           ' --tag "${GITHUB_REF_NAME}" --github-output "${GITHUB_OUTPUT}"\n' in job
    assert "|| true" not in code
    assert "      channel: ${{ steps.decide.outputs.channel }}" in code
    assert "      valid_through: ${{ steps.decide.outputs.valid_through }}" in code


def test_publish_takes_the_channel_from_the_gate():
    """One decision: ``publish`` no longer re-derives RC-ness from the tag text.

    ``*rc*`` matched any tag containing "rc" (``v1.8.0-rc1`` too), while the
    gate reads the updater's grammar. The two agree on every tag the grammar
    admits today, but two rules for one decision drift apart, and the costly
    drift, a tag the gate waves through as a candidate that ``publish`` marks
    ``--latest``, would ship an unaccepted build to every install.
    """
    publish = _jobs()["publish"]
    code = _code(publish)
    assert "          CHANNEL: ${{ needs.acceptance.outputs.channel }}" in code
    assert "          VALID_THROUGH: ${{ needs.acceptance.outputs.valid_through }}" in code
    assert "*rc*" not in code
    assert re.search(r"^\s*prerelease\)\s+channel_flag=--prerelease ;;$", code, re.M)
    assert re.search(r"^\s*stable\)\s+channel_flag=--latest ;;$", code, re.M)
    assert code.count("--latest") == 1 and code.count("--prerelease") == 1
    assert '"${channel_flag}"' in code
    # An unknown channel refuses, and refuses before anything is published.
    case = code.index('case "${CHANNEL}" in')
    default = code.index("*)", case)
    assert "exit 1" in code[default:code.index("esac", case)]
    assert case < code.index("gh release create")


def test_publish_rechecks_waiver_expiry_at_publish_time():
    """Approval can come days after the gate ran; a lapsed waiver still refuses.

    Same rule as the script (valid through the expiry day): lapsed only when
    today's UTC date sorts after it. Checked twice: before anything is
    uploaded, and again after the upload, immediately before the draft is made
    public (Codex review: ``gh release create`` uploads before it publishes,
    so a check ahead of it leaves the whole upload between check and use).
    """
    code = _code(_jobs()["publish"])
    assert '[[ -n "${VALID_THROUGH}" && "$(date -u +%F)" > "${VALID_THROUGH}" ]]' in code
    assert "=~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$" in code
    checks = [m.start() for m in re.finditer(r"if waiver_lapsed; then", code)]
    assert len(checks) == 2, checks
    for check in checks:
        closing = re.search(r"^\s*fi$", code[check:], re.MULTILINE)
        assert closing, "an expiry check is never closed"
        assert "exit 1" in code[check:check + closing.start()]
    create = code.index("gh release create")
    publish = code.index('gh release edit "${tag}"')
    assert checks[0] < create < checks[1] < publish


def test_publish_uploads_into_a_draft_and_publishes_last():
    """The release becomes public in one final call, after every check.

    A draft is invisible to the public and to the updater, so the upload can
    take as long as it takes. A re-run finds what an earlier attempt left: a
    draft is finished and published, while a published release only has its
    assets replaced and keeps its latest/pre-release flags (re-running an old
    tag must not take ``latest`` back from a newer release).
    """
    code = _code(_jobs()["publish"])
    create = re.search(r'^\s*missing\) gh release create "\$\{tag\}" .*$', code, re.M)
    assert create and " --draft " in create.group(0), create
    assert "--latest" not in create.group(0) and "--prerelease" not in create.group(0)
    assert re.search(
        r'^\s*if \[\[ "\$\{state\}" != "false" \]\]; then$', code, re.M)
    assert ('gh release edit "${tag}" --repo "${GITHUB_REPOSITORY}" --draft=false '
            '"${channel_flag}"') in code
    assert code.count('"${channel_flag}"') == 1


def _publish_script() -> str:
    """The ``Publish GitHub Release`` step's shell script, dedented."""
    step = _jobs()["publish"].split("- name: Publish GitHub Release", 1)[1]
    body = step.split("run: |\n", 1)[1]
    lines = []
    for line in body.splitlines():
        if line.strip() and not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    return "\n".join(lines) + "\n"


_FAKE_GH = """\
#!/usr/bin/env bash
args=("${@//$'\\n'/ }")          # one log line per call: --notes spans lines
printf '%s\\n' "${args[*]}" >> "$GH_LOG"
case "$1 $2" in
  "release view")
    if [[ "$GH_STATE" == missing ]]; then echo "release not found" >&2; exit 1; fi
    echo "$GH_STATE" ;;
  "release create"|"release upload")
    # The upload is the slow part: the clock may pass midnight during it.
    if [[ -n "${GH_UPLOAD_ENDS_ON:-}" ]]; then echo "$GH_UPLOAD_ENDS_ON" > "$FAKE_TODAY"; fi ;;
esac
"""

_FAKE_DATE = """\
#!/usr/bin/env bash
[[ "$*" == "-u +%F" ]] || { echo "fake date: unexpected $*" >&2; exit 2; }
cat "$FAKE_TODAY"
"""


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="the publish step runs on ubuntu-latest; this needs a POSIX bash",
)
@pytest.mark.parametrize("channel, valid_through, today, upload_ends_on, state, rc, calls", [
    # A first publish: a draft, then one call that makes it public.
    ("stable", "", "2026-10-01", "", "missing", 0,
     ["release view", "release create --draft", "release edit --draft=false --latest"]),
    ("prerelease", "", "2026-10-01", "", "missing", 0,
     ["release view", "release create --draft", "release edit --draft=false --prerelease"]),
    ("stable", "2026-10-01", "2026-10-01", "", "missing", 0,
     ["release view", "release create --draft", "release edit --draft=false --latest"]),
    # Codex's case: valid when the job starts, lapsed by the time the upload
    # ends. The draft is never published.
    ("stable", "2026-10-01", "2026-10-01", "2026-10-02", "missing", 1,
     ["release view", "release create --draft"]),
    # Refusals before anything is touched.
    ("stable", "2026-09-30", "2026-10-01", "", "missing", 1, []),
    ("stable", "2026-9-30", "2026-10-01", "", "missing", 1, []),
    ("", "", "2026-10-01", "", "missing", 1, []),
    ("Stable", "", "2026-10-01", "", "missing", 1, []),
    # Re-runs: an earlier attempt's draft is finished; a published release only
    # has its assets replaced, and its flags are left alone.
    ("stable", "", "2026-10-01", "", "true", 0,
     ["release view", "release upload --clobber", "release edit --draft=false --latest"]),
    ("stable", "", "2026-10-01", "", "false", 0,
     ["release view", "release upload --clobber"]),
])
def test_the_publish_step_publishes_only_what_it_should(
    tmp_path, channel, valid_through, today, upload_ends_on, state, rc, calls,
):
    """The real step's script, run under a fake ``gh`` and a fake clock."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("no bash on PATH")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (("gh", _FAKE_GH), ("date", _FAKE_DATE)):
        path = bin_dir / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
    (tmp_path / "artifact").mkdir()
    (tmp_path / "artifact" / "DrawingAnalyzerSetup.exe").write_bytes(b"MZ")
    (tmp_path / "artifact" / "latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "today").write_text(today, encoding="utf-8")
    script = tmp_path / "publish.sh"
    script.write_text(_publish_script(), encoding="utf-8")
    log = tmp_path / "gh.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GITHUB_REF_NAME": "v1.8.0rc1" if channel == "prerelease" else "v1.8.0",
        "GITHUB_REPOSITORY": "owner/repo",
        "GH_TOKEN": "placeholder",
        "CHANNEL": channel,
        "VALID_THROUGH": valid_through,
        "GH_STATE": state,
        "GH_LOG": str(log),
        "FAKE_TODAY": str(tmp_path / "today"),
        "GH_UPLOAD_ENDS_ON": upload_ends_on,
    }
    run = subprocess.run([bash, "-e", str(script)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == rc, run.stderr
    made = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    # Each expected call, in order, with its decisive flags.
    assert len(made) == len(calls), made
    for line, expected in zip(made, calls):
        words = expected.split()
        assert line.split()[:2] == words[:2], (line, expected)
        for flag in words[2:]:
            assert flag in line.split(), (line, expected)
    for line in made:
        if line.startswith("release create"):
            assert "--latest" not in line.split() and "--prerelease" not in line.split()


def test_publish_is_a_protected_deployment():
    """``environment:`` is the approval boundary a tag cannot rewrite (O-5).

    The YAML is only half of it: an environment no admin configured is
    auto-created unprotected, so this proves the reference, not the protection.
    """
    assert _job_key(_jobs()["publish"], "environment") == ["release"]


def test_publish_runs_no_repo_code():
    """The write-token job downloads the artifact and calls ``gh``, nothing else.

    That is why the gate is a separate read-only job whose output ``publish``
    consumes, rather than a checkout-and-run step inside ``publish``.
    """
    code = _code(_jobs()["publish"])
    assert "actions/checkout" not in code
    assert "scripts/" not in code
    assert not re.search(r"\bpython\b", code)
