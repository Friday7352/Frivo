@echo off
rem ------------------------------------------------------------------
rem  Frivo - setup launcher
rem ------------------------------------------------------------------
rem  Starts the wizard with no console window. A VBScript shim is used
rem  because "start /min" and -WindowStyle Hidden both still flash a
rem  console briefly; WScript.Shell.Run with a window style of 0 does
rem  not create one at all.
rem
rem  -STA is required: the wizard is a WinForms window, and WinForms
rem  will not start on a multi-threaded apartment.
rem ------------------------------------------------------------------

setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo Windows PowerShell was not found on this system.
  echo Frivo Setup cannot continue.
  pause
  exit /b 1
)

set "SHIM=%TEMP%\vc-setup-launch.vbs"
> "%SHIM%" echo Set s = CreateObject("WScript.Shell")
>>"%SHIM%" echo s.Run "powershell -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File ""%~dp0installer\Install.ps1""", 0, False
cscript //nologo "%SHIM%" >nul 2>&1
del "%SHIM%" >nul 2>&1

endlocal
