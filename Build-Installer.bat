@echo off
rem ------------------------------------------------------------------
rem  Frivo — one-click installer build
rem ------------------------------------------------------------------
rem  Double-click this file from the project folder to create a fresh
rem  dist\FrivoSetup.exe. The PowerShell build script compiles FrivoHost
rem  and uses Inno Setup; it installs Inno Setup if it is missing.
rem ------------------------------------------------------------------

setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo Windows PowerShell was not found on this system.
  echo FrivoSetup.exe could not be built.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\Build-Installer.ps1"
set "BUILD_EXIT=%ERRORLEVEL%"

echo.
if not "%BUILD_EXIT%"=="0" (
  echo The installer build did not complete. Review the message above and try again.
) else (
  echo Done. Your new installer is in the dist folder as FrivoSetup.exe.
)
echo.
pause
exit /b %BUILD_EXIT%
