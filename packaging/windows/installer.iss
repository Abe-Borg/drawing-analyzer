; Inno Setup script for Drawing Analyzer (Windows desktop app).
;
; Compiled by .github/workflows/release.yml with:
;   ISCC /DMyAppVersion=1.2.3 packaging\windows\installer.iss
; and expects the PyInstaller one-folder output at dist\DrawingAnalyzer\.
;
; Produces dist\installer\DrawingAnalyzerSetup.exe — a normal double-click
; installer with a license page the user must accept, a Start-menu shortcut, an
; optional desktop icon, and a clean uninstaller. The app is NOT code-signed, so
; Windows SmartScreen shows a "Windows protected your PC" notice on first run
; (More info -> Run anyway); that is expected and documented in
; docs/RELEASE_WINDOWS.md and the README.

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
; The License Agreement page: the repo's own LICENSE (AGPL-3.0), shown verbatim
; in a scroll box with "I accept" / "I do not accept". Next stays disabled until
; the user accepts. Every interactive run of the installer shows it, an in-app
; update included (the updater launches it with no switches). A /SILENT or
; /VERYSILENT install skips it, as it skips every wizard page. The file is
; plain ASCII on purpose: Inno Setup reads a text file without a BOM as ANSI,
; so any other character would print wrongly on the page
; (tests/test_installer_license.py).
LicenseFile=..\..\LICENSE
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
; The text above the license box. The default only says "Please read the
; following License Agreement", which does not say what the license is. Keep it
; no longer than that default (129 characters): the page sizes this label for
; it, and longer text risks being clipped (tests/test_installer_license.py).
LicenseLabel3={#MyAppName} is free software under the GNU AGPL-3.0-or-later, with NO WARRANTY. You must accept the license to continue.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller one-folder output.
Source: "..\..\dist\DrawingAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; The license travels with the program (AGPL section 4: give every recipient a
; copy of the License). Named .txt so a double-click opens it in Notepad.
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
