; Inno Setup script for Drawing Analyzer (Windows desktop app).
;
; Compiled by .github/workflows/release.yml with:
;   ISCC /DMyAppVersion=1.2.3 packaging\windows\installer.iss
; and expects the PyInstaller one-folder output at dist\DrawingAnalyzer\.
;
; Produces dist\installer\DrawingAnalyzerSetup.exe — a normal double-click
; installer with a License Agreement page the user must accept (the AGPL, from
; the repo's LICENSE), a Start-menu shortcut, an optional desktop icon, and a
; clean uninstaller. The app is NOT code-signed, so Windows SmartScreen shows a
; "Windows protected your PC" notice on first run (More info -> Run anyway);
; that is expected and documented in docs/RELEASE_WINDOWS.md and the README.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "Drawing Analyzer"
#define MyAppPublisher "Abraham Borg"
#define MyAppExeName "DrawingAnalyzer.exe"
#define MyAppURL "https://github.com/abe-borg/drawing-analyzer"

[Setup]
; A stable AppId ties every version together so an install upgrades in place
; instead of stacking side-by-side. Do NOT change this GUID across releases.
AppId={{7B3F2A1C-9D4E-4C8B-9F2A-1E6D5C4B3A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Also stamped into Setup.exe's version info (VersionInfoCopyright defaults to
; it). Keep it equal to the README's Licensing section.
AppCopyright=Copyright (C) 2026 {#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases/latest
DefaultDirName={autopf}\Drawing Analyzer
DefaultGroupName=Drawing Analyzer
DisableProgramGroupPage=yes
; The License Agreement page: the full LICENSE text, with "I accept the
; agreement" / "I do not accept the agreement" radio buttons. Inno Setup
; preselects "I do not accept" and keeps Next disabled until the user picks
; "I accept", so installation cannot continue without that click. The in-app
; updater launches this installer interactively, so every update shows the page
; too; only a /SILENT or /VERYSILENT command-line install skips it.
; tests/test_installer_license.py pins this, the page's summary text in
; [Messages], and the copy installed in [Files].
LicenseFile=..\..\LICENSE
; Per-user install: no admin/UAC prompt, which keeps the unsigned experience as
; smooth as possible (the user only sees the one SmartScreen notice, not an
; elevation prompt on top of it).
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist\installer
OutputBaseFilename=DrawingAnalyzerSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Let an in-place update replace the running app: Inno detects a running
; instance and offers to close it. Pairs with the in-app updater, which exits
; the app before launching this installer.
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
; The text above the license on the License Agreement page. It replaces Inno's
; generic "Please read the following License Agreement..." with a plain-words
; summary of what the license is. It must stay consistent with LICENSE, the
; README's Licensing section and the About panel (help_content.py).
LicenseLabel3={#MyAppName} is free software under the GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later), with NO WARRANTY. You may use, share and modify it. Modified versions you distribute or offer over a network must stay under this license, with source available. You must accept the license below to continue with the installation.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller one-folder output.
Source: "..\..\dist\DrawingAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; The license the user accepted, installed next to the app so every installed
; copy carries it (AGPL §4 and §6: give recipients a copy of the License with
; the program). The uninstaller removes it with everything else.
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
