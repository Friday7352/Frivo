; Frivo App: extra steps for the uninstaller electron-builder makes.
;
; Starting with Windows, when the app connects to Frivo on another PC, is
; the "Frivo App" entry in the signed-in person's Run key (app.setLoginItemSettings
; in src/main.js). Uninstalling takes it out, so nothing tries to start an
; app that's gone. Not when this "uninstall" is really an update replacing
; the old version: the setting is kept then.
;
; Frivo's own sign-in entry ("Frivo") is Frivo's and stays. With the app
; gone, Frivo's launcher notices (appPath in launcher.json points at
; nothing) and goes back to its own window and tray icon.

; CHANGED (2.0.0): the app is listed as "Frivo". Installed on a PC where
; Frivo itself is installed too, it isn't listed in Apps & features at all:
; there's one Frivo there, and uninstalling it offers to remove the app as
; well. Written on every install, so an app update (which replaces this
; entry) keeps it that way. Frivo's setup and uninstaller set it the same
; way (Set-FrivoAppListed in installer\Frivo.Setup.psm1).
!macro customInstall
  ClearErrors
  ReadRegStr $0 HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Frivo" "DisplayName"
  ${ifNot} ${Errors}
    WriteRegDWORD SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "SystemComponent" 1
  ${endIf}
!macroend

!macro customUnInstall
  ${ifNot} ${isUpdated}
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Frivo App"
  ${endIf}
!macroend
