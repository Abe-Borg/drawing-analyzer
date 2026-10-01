"""The Windows installer shows the license, and cannot continue until it is accepted.

``packaging/windows/installer.iss`` names the repository ``LICENSE`` as its
``LicenseFile``. Inno Setup then adds a License Agreement page that shows the
full text with "I accept the agreement" / "I do not accept the agreement" radio
buttons, preselects "I do not accept", and keeps Next disabled until the user
accepts. Before this, the installer had no such page: nothing in the wizard
named the AGPL, and the installed app folder held no copy of it.

Text checks, not a compile: ISCC runs only in release.yml's Windows ``build``
job, which compiles this script on every PR that touches it. What the page
looks like is a manual check (docs/WINDOWS_ACCEPTANCE.md, row 3A.1).
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ISS = _REPO_ROOT / "packaging" / "windows" / "installer.iss"
_LICENSE = _REPO_ROOT / "LICENSE"


def _sections() -> dict[str, list[str]]:
    """Each ``[Section]``'s entry lines, lower-cased names, comments dropped.

    Inno comments are whole lines starting with ``;``; preprocessor lines
    (``#define`` and friends) start with ``#``.
    """
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in _ISS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        header = re.fullmatch(r"\[([^\]]+)\]", line)
        if header:
            current = sections.setdefault(header.group(1).lower(), [])
        elif current is not None:
            current.append(line)
    return sections


def _directives(section: str) -> dict[str, str]:
    """``Key=Value`` entries of a directive section, keys lower-cased."""
    pairs = (line.split("=", 1) for line in _sections().get(section, []) if "=" in line)
    return {key.strip().lower(): value.strip() for key, value in pairs}


def _resolve(script_relative: str) -> Path:
    """A source path as ISCC resolves it: relative to the script's folder."""
    return (_ISS.parent / script_relative.replace("\\", "/")).resolve()


def test_the_license_page_shows_the_repository_license():
    license_file = _directives("setup").get("licensefile")
    assert license_file, "installer.iss has no LicenseFile, so no License Agreement page"
    assert _resolve(license_file) == _LICENSE.resolve(), license_file
    head = _LICENSE.read_text(encoding="utf-8").splitlines()[:3]
    assert head[0].strip() == "GNU AFFERO GENERAL PUBLIC LICENSE", head
    assert head[1].strip().startswith("Version 3"), head


def test_the_license_text_reads_the_same_in_any_encoding():
    """ASCII shows identically whether ISCC reads the .txt as UTF-8 or as an
    ANSI code page, so the page never shows mangled characters."""
    _LICENSE.read_bytes().decode("ascii")


def test_the_script_text_the_installer_shows_is_ascii():
    """The license summary and the copyright come from the script itself, so
    they are held to the same rule as LICENSE: plain ASCII, so a stray ``©`` or
    curly quote cannot be mangled by however ISCC decodes the script."""
    label = _directives("messages").get("licenselabel3", "")
    copyright_ = _directives("setup").get("appcopyright", "")
    (label + copyright_).encode("ascii")


def test_the_copyright_matches_the_readme():
    """``AppCopyright`` goes into Setup.exe's version info; it names the same
    year and holder as the README's Licensing section."""
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    year, holder = re.search(r"Copyright © (\d{4}) ([^;.]+)", readme).groups()
    script = _ISS.read_text(encoding="utf-8")
    defines = dict(re.findall(r'^#define\s+(\w+)\s+"([^"]*)"', script, re.MULTILINE))
    copyright_ = re.sub(
        r"\{#(\w+)\}", lambda m: defines[m.group(1)], _directives("setup").get("appcopyright", "")
    )
    assert copyright_ == f"Copyright (C) {year} {holder.strip()}", copyright_


def test_the_license_page_summarises_the_license():
    """The text above the license names it and the missing warranty, like the
    About panel (tests/test_help_content.py) and the README do."""
    label = _directives("messages").get("licenselabel3", "")
    for needle in ("AGPL-3.0-or-later", "NO WARRANTY", "accept"):
        assert needle in label, f"the license page summary lost {needle!r}: {label!r}"


def test_nothing_skips_or_preselects_acceptance():
    """Only the user's click accepts: no [Code] skips the page or ticks the radio."""
    code = "\n".join(_sections().get("code", []))
    for name in ("wpLicense", "LicenseAcceptedRadio", "LicenseNotAcceptedRadio"):
        assert name not in code, f"[Code] touches {name}"


def test_the_installed_app_carries_the_license():
    entries = [
        dict(re.findall(r'(\w+):\s*"([^"]*)"', line)) for line in _sections().get("files", [])
    ]
    copies = [e for e in entries if e.get("Source") and _resolve(e["Source"]) == _LICENSE.resolve()]
    assert copies, "[Files] no longer installs LICENSE with the app"
    assert copies[0].get("DestDir") == "{app}", copies[0]
