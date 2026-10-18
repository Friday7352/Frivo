; ------------------------------------------------------------------
;  Frivo — single-file setup launcher
; ------------------------------------------------------------------
;  Inno Setup supplies the signed, single .exe container. The actual
;  install experience is Frivo's own Install.ps1 window, so the public
;  download looks exactly like the standalone Frivo setup wizard rather
;  than Inno Setup's stock pages. Install.ps1 owns the app files,
;  shortcuts, Apps & features entry, launcher, and custom uninstaller.
; ------------------------------------------------------------------

#define AppName    "Frivo"
#define AppPublisher "Friday"

; The version comes from one file at the repo root, so bumping it before a
; release is a one-line edit rather than a hunt through three files that
; had already drifted apart. A missing or empty VERSION stops the build
; here, loudly, rather than shipping an installer labelled "0.0.0".
#define VersionFile AddBackslash(SourcePath) + "..\VERSION"
#define VersionHandle FileOpen(VersionFile)
#define AppVersion Trim(FileRead(VersionHandle))
#expr FileClose(VersionHandle)
#if AppVersion == ""
  #error VERSION at the repo root is empty. Put a version number in it.
#endif

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
OutputDir=..\dist
OutputBaseFilename=FrivoSetup
Compression=lzma2/max
SolidCompression=yes
SetupIconFile=..\app\static\Frivo.ico
; The FrivoSetup.exe itself requests elevation, so Windows identifies this
; installer—not PowerShell—in the administrator confirmation.
PrivilegesRequired=admin
CreateAppDir=no
Uninstallable=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableReadyMemo=yes
DisableFinishedPage=yes
DisableStartupPrompt=yes
MinVersion=10.0

[Files]
; Keep the complete setup payload together under {tmp}. It is deleted as
; soon as the Frivo installer window closes; only the selected Frivo folder
; and its per-user data remain afterwards.
; CHANGED (1.5.0): voices\ is excluded. Setup downloads Frivo's voices (voice_pack.py), so a
; copy made for testing in app\voices never ends up inside FrivoSetup.exe.
Source: "..\app\*";       DestDir: "{tmp}\FrivoSetupPayload\app";       Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall; Excludes: "config.json,profiles.json,usage.json,launcher.json,*.log,__pycache__\*,*.pyc,\voices\*"
Source: "..\installer\*"; DestDir: "{tmp}\FrivoSetupPayload\installer"; Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall
Source: "FrivoHost.exe";   DestDir: "{tmp}\FrivoSetupPayload\installer"; Flags: ignoreversion deleteafterinstall
Source: "..\README.md";   DestDir: "{tmp}\FrivoSetupPayload";           Flags: ignoreversion deleteafterinstall
; Install.ps1 reads this for the Apps & features entry and the welcome page.
Source: "..\VERSION";     DestDir: "{tmp}\FrivoSetupPayload";           Flags: ignoreversion deleteafterinstall

[Run]
; hidewizard keeps Inno's internal extraction window out of sight while the
; Frivo-styled wizard runs. waituntilterminated also keeps the payload alive
; while FrivoHost.exe runs the custom Frivo wizard in its own native process.
; CHANGED (updates): not when silent. A silent run is an in-app update,
; started as SYSTEM with no desktop: the wizard would open where nobody can
; see it and wait for ever. RunSilentUpdate in [Code] runs that case.
Filename: "{tmp}\FrivoSetupPayload\installer\FrivoHost.exe"; \
  Parameters: "--script ""{tmp}\FrivoSetupPayload\installer\Install.ps1"" --data ""{userappdata}\Frivo"""; \
  Flags: waituntilterminated hidewizard 64bit; Check: not WizardSilent

[Code]
function PostMessage(hWnd: HWND; Msg, wParam, lParam: Longint): Boolean;
  external 'PostMessageW@user32.dll stdcall';

{ NEW (updates): FrivoSetup.exe /VERYSILENT is how Frivo updates itself (see
  installer\Update-Frivo.ps1). It runs Install.ps1's silent update path
  through FrivoHost --silent, which shows nothing and never waits on a
  message box, and hands its result back as Setup's exit code:
    0   updated
    10  FrivoHost could not be started
    11  the update failed; Install.ps1 logged "FAILED: <reason>"
  A silent run only ever updates an existing install. It is not a way to
  install Frivo fresh without the wizard. }
var
  SilentExitCode: Integer;

procedure RunSilentUpdate;
var
  ResultCode: Integer;
  Payload: String;
begin
  Payload := ExpandConstant('{tmp}\FrivoSetupPayload\installer\');
  if not Exec(Payload + 'FrivoHost.exe',
      '--silent --action Update --script "' + Payload + 'Install.ps1" --data "' + ExpandConstant('{userappdata}\Frivo') + '"',
      Payload, SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    SilentExitCode := 10
  else if ResultCode <> 0 then
    SilentExitCode := 11;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardSilent then
    RunSilentUpdate;
end;

function GetCustomSetupExitCode: Integer;
begin
  Result := SilentExitCode;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // Inno may show a Ready page even when it is disabled; submit it automatically.
  if CurPageID = wpReady then
  begin
    WizardForm.Hide;
    PostMessage(WizardForm.NextButton.Handle, $00F5, 0, 0); // BM_CLICK
  end;
end;
