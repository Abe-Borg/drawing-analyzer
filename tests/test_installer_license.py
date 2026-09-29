"""The Windows installer shows the license and requires the user to accept it.

``packaging/windows/installer.iss`` is compiled only on the Windows release
runner, so nothing else in the suite reads it. These tests pin what the
installer must keep doing:

- ``LicenseFile`` is the repo's own ``LICENSE`` (AGPL-3.0). That directive is
  what gives Inno Setup's License Agreement page, with "I accept" / "I do not
  accept" and Next disabled until the user accepts.
- The text above the license box names this software's license.
- ``LICENSE`` is installed beside the app.
- Everything the page displays is ASCII, because Inno Setup reads a text file
  without a BOM as ANSI.
"""
from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ISS = _REPO_ROOT / "packaging" / "windows" / "installer.iss"


def _sections() -> dict[str, list[str]]:
    """The script's non-comment lines, grouped by ``[Section]``."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in _ISS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        header = re.fullmatch(r"\[(\w+)\]", line)
        if header:
            current = header.group(1)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _directives(section: str) -> dict[str, str]:
    """``Key=Value`` lines of one section (``[Setup]``, ``[Messages]``)."""
    out: dict[str, str] = {}
    for line in _sections().get(section, []):
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _defines() -> dict[str, str]:
    """The ``#define Name "value"`` preprocessor constants."""
    text = _ISS.read_text(encoding="utf-8")
    return dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', text, re.MULTILINE))


def _expand(value: str) -> str:
    """Expand ``{#Name}`` the way ISPP does, for the constants defined here."""
    defines = _defines()
    return re.sub(r"\{#(\w+)\}", lambda m: defines[m.group(1)], value)


def _repo_path(iss_relative: str) -> Path:
    """A path written in the script, relative to the script's own directory."""
    return (_ISS.parent / Path(*PureWindowsPath(iss_relative).parts)).resolve()


def _file_entries() -> list[dict[str, str]]:
    """``[Files]`` entries as ``{"Source": ..., "DestDir": ..., ...}``."""
    entries = []
    for line in _sections().get("Files", []):
        params = dict(re.findall(r'(\w+):\s*"?([^";]*)"?', line))
        entries.append(params)
    return entries


def test_installer_shows_the_repo_license_for_acceptance():
    setup = _directives("Setup")
    assert "LicenseFile" in setup, "installer.iss has no License Agreement page"
    license_path = _repo_path(setup["LicenseFile"])
    assert license_path == (_REPO_ROOT / "LICENSE").resolve()
    text = license_path.read_text(encoding="utf-8")
    assert text.startswith("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3")
    # A [Code] ShouldSkipPage(wpLicense) is the one way a script can drop the
    # page while LicenseFile is still set.
    assert "wpLicense" not in _ISS.read_text(encoding="utf-8")


def test_license_page_names_this_softwares_license():
    label = _expand(_directives("Messages").get("LicenseLabel3", ""))
    assert label, "the license page keeps Inno Setup's generic label"
    for needle in (
        "Drawing Analyzer",
        "GNU Affero General Public License",
        "AGPL-3.0-or-later",
        "NO WARRANTY",
        "https://github.com/abe-borg/drawing-analyzer",
        "accept",
    ):
        assert needle in label, needle


def test_installer_installs_the_license_beside_the_app():
    licensed = [
        e for e in _file_entries()
        if _repo_path(e["Source"]) == (_REPO_ROOT / "LICENSE").resolve()
    ]
    assert len(licensed) == 1, _file_entries()
    assert licensed[0]["DestDir"] == "{app}"
    assert licensed[0].get("DestName") == "LICENSE.txt"


def test_copyright_matches_the_readme():
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    year, holder = re.search(r"Copyright © (\d{4}) ([^;.]+)", readme).groups()
    copyright_ = _expand(_directives("Setup")["AppCopyright"])
    assert copyright_ == f"Copyright (C) {year} {holder.strip()}"


def test_text_the_license_page_displays_is_ascii():
    """Inno Setup reads a BOM-less text file as ANSI (the system code page), so
    a ``©`` or a curly quote in ``LICENSE`` would print as two wrong characters
    on the page. The label and copyright come from the script, read the same way.
    """
    (_REPO_ROOT / "LICENSE").read_bytes().decode("ascii")
    for value in (
        _directives("Messages")["LicenseLabel3"],
        _directives("Setup")["AppCopyright"],
    ):
        _expand(value).encode("ascii")
