; Inno Setup script for Drawing Analyzer (Windows desktop app).
;
; Compiled by .github/workflows/release.yml with:
;   ISCC /DMyAppVersion=1.2.3 packaging\windows\installer.iss
; and expects the PyInstaller one-folder output at dist\DrawingAnalyzer\.
;
; Produces dist\installer\DrawingAnalyzerSetup.exe — a normal double-click
; installer with a license page, a Start-menu shortcut, an optional desktop
; icon, and a clean uninstaller. The app is NOT code-signed, so Windows
; SmartScreen shows a "Windows protected your PC" notice on first run (More
; info -> Run anyway); that is expected and documented in
; docs/RELEASE_WINDOWS.md and the README.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "Drawing Analyzer"
#define MyAppPublisher "Abraham Borg"
#define MyAppExeName "DrawingAnalyzer.exe"
#define MyAppURL "https://github.com/abe-borg/drawing-analyzer"
; ASCII "(C)": the copyright string lands in the Setup exe's version resource
; and the Add/Remove Programs entry, and must not depend on the .iss encoding.
#define MyAppCopyright "Copyright (C) 2026 Abraham Borg"

[Setup]
; A stable AppId ties every version together so an install upgrades in place
; instead of stacking side-by-side. Do NOT change this GUID across releases.
AppId={{7B3F2A1C-9D4E-4C8B-9F2A-1E6D5C4B3A21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases/latest
; AppCopyright only feeds the Setup exe's version resource (VersionInfoCopyright);
; AppComments is what the Add/Remove Programs entry shows, so it carries the
; copyright as well.
AppCopyright={#MyAppCopyright}
AppComments={#MyAppCopyright}. Free software under the GNU AGPL-3.0-or-later. Source code: {#MyAppURL}
; The license page. An information page, not LicenseFile: LicenseFile's page
; keeps Next disabled until "I accept the agreement" is chosen, and AGPL
; section 9 does not require accepting the license merely to run the program.
; The in-app updater launches this installer through the shell with no
; /SILENT switch, so an update runs the full wizard and shows this page too;
; keep it that way (a silent install skips every wizard page).
InfoBeforeFile=..\..\LICENSE
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
; Retitle the stock "Information" page (InfoBeforeFile above) as the license
; page, with the copyright line above the license text.
WizardInfoBefore=License
InfoBeforeLabel=Please read the license under which {#MyAppName} is distributed.
InfoBeforeClickLabel={#MyAppCopyright}. {#MyAppName} is free software under the GNU Affero General Public License, version 3 or later, shown below: it sets the terms for copying, modifying and redistributing the program. A copy is installed as LICENSE.txt in the program folder, and the complete source code is at {#MyAppURL}. When you are ready to continue with Setup, click Next.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller one-folder output.
Source: "..\..\dist\DrawingAnalyzer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; The AGPL text travels with the program, not only with the source. Installed
; as .txt so a double-click opens it in Notepad.
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} License"; Filename: "{app}\LICENSE.txt"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
