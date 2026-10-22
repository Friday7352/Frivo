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

!macro customUnInstall
  ${ifNot} ${isUpdated}
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "Frivo App"
  ${endIf}
!macroend
