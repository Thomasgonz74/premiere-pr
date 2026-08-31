; Inno Setup script for Torrent 2000.
; Requires Inno Setup 6 (https://jrsoftware.org/isdl.php) to compile:
;   ISCC.exe torrent2000_installer.iss
; Expects the PyInstaller build to already exist at ..\dist\Torrent2000\
; (run packaging\torrent2000.spec first) -- a --onedir tree, not a single exe.
;
; Silent / unattended installation:
;   Torrent2000-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
;
; Without a /TASKS or /MERGETASKS argument, a (very)silent install still
; selects all 3 tasks below (desktop icon + both file associations), since
; none of them are marked "unchecked" -- this can surprise a scripted
; deployment that doesn't want them all. To pick tasks explicitly, use one
; of:
;   /TASKS="desktopicon,associatetorrent,associatemagnet"
;     A positive list: only the named tasks are selected, everything else
;     is deselected.
;   /MERGETASKS="!associatetorrent,!associatemagnet"
;     Deselects the named tasks (the "!" prefix) while leaving any other
;     task, e.g. desktopicon, at its default (selected).

#define MyAppName "Torrent 2000"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Torrent 2000"
#define MyAppExeName "Torrent2000.exe"

[Setup]
AppId={{1CD4AB75-1332-4ADC-978D-17A8F2B39DC4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install under %LocalAppData%\Programs -- no admin rights/UAC
; prompt required, matching how the app already stores its own data under
; %APPDATA%\Torrent2000 rather than assuming a machine-wide install.
DefaultDirName={localappdata}\Programs\Torrent2000
PrivilegesRequired=lowest
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Torrent2000-Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; No "checked"/"unchecked" flag needed on any of these -- a task's checkbox
; is checked by default unless explicitly marked "unchecked".
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "associatetorrent"; Description: "Associer les fichiers .torrent à {#MyAppName}"; GroupDescription: "Associations de fichiers :"
Name: "associatemagnet"; Description: "Associer les liens magnet: à {#MyAppName}"; GroupDescription: "Associations de fichiers :"

[Files]
; --onedir build: the whole dist\Torrent2000\ tree (Torrent2000.exe plus
; _internal\ with QtWebEngineProcess.exe, PySide6\, resources\, assets\,
; locales, etc.), not a single onefile exe.
Source: "..\dist\Torrent2000\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; .torrent file association -- HKCU (not HKCR/HKLM) since the whole install
; is per-user and admin-free; each Task is opt-in, same convention every
; other torrent client's installer uses since it can override an existing
; association.
Root: HKCU; Subkey: "Software\Classes\.torrent"; ValueType: string; ValueName: ""; ValueData: "Torrent2000.AssocFile.torrent"; Flags: uninsdeletevalue; Tasks: associatetorrent
Root: HKCU; Subkey: "Software\Classes\Torrent2000.AssocFile.torrent"; ValueType: string; ValueName: ""; ValueData: "Fichier Torrent 2000"; Flags: uninsdeletekey; Tasks: associatetorrent
Root: HKCU; Subkey: "Software\Classes\Torrent2000.AssocFile.torrent\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associatetorrent
Root: HKCU; Subkey: "Software\Classes\Torrent2000.AssocFile.torrent\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatetorrent

; magnet: protocol association
Root: HKCU; Subkey: "Software\Classes\magnet"; ValueType: string; ValueName: ""; ValueData: "URL:Magnet Link"; Flags: uninsdeletekey; Tasks: associatemagnet
Root: HKCU; Subkey: "Software\Classes\magnet"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: associatemagnet
Root: HKCU; Subkey: "Software\Classes\magnet\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: associatemagnet
Root: HKCU; Subkey: "Software\Classes\magnet\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associatemagnet

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; Note: uninstalling removes the program files, shortcuts, and the
; associations above, but deliberately leaves %APPDATA%\Torrent2000 (config,
; stats database, download resume data) in place -- standard convention so a
; reinstall doesn't lose the user's settings and torrent history.
