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
#define AppVersion "1.1.2"
#define AppPublisher "Friday"

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
Source: "..\app\*";       DestDir: "{tmp}\FrivoSetupPayload\app";       Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall; Excludes: "config.json,profiles.json,usage.json,launcher.json,*.log,__pycache__\*,*.pyc"
Source: "..\installer\*"; DestDir: "{tmp}\FrivoSetupPayload\installer"; Flags: ignoreversion recursesubdirs createallsubdirs deleteafterinstall
Source: "FrivoHost.exe";   DestDir: "{tmp}\FrivoSetupPayload\installer"; Flags: ignoreversion deleteafterinstall
Source: "..\README.md";   DestDir: "{tmp}\FrivoSetupPayload";           Flags: ignoreversion deleteafterinstall

[Run]
; hidewizard keeps Inno's internal extraction window out of sight while the
; Frivo-styled wizard runs. waituntilterminated also keeps the payload alive
; while FrivoHost.exe runs the custom Frivo wizard in its own native process.
Filename: "{tmp}\FrivoSetupPayload\installer\FrivoHost.exe"; \
  Parameters: "--script ""{tmp}\FrivoSetupPayload\installer\Install.ps1"" --data ""{userappdata}\Frivo"""; \
  Flags: waituntilterminated hidewizard 64bit

[Code]
function PostMessage(hWnd: HWND; Msg, wParam, lParam: Longint): Boolean;
  external 'PostMessageW@user32.dll stdcall';

procedure CurPageChanged(CurPageID: Integer);
begin
  // Inno may show a Ready page even when it is disabled; submit it automatically.
  if CurPageID = wpReady then
  begin
    WizardForm.Hide;
    PostMessage(WizardForm.NextButton.Handle, $00F5, 0, 0); // BM_CLICK
  end;
end;
