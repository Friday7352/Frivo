@echo off
rem ------------------------------------------------------------------
rem  Frivo — build everything
rem ------------------------------------------------------------------
rem  Double-click this file from the project folder. It writes
rem  dist\FrivoSetup.exe, the one installer (Frivo, the Frivo app, or both),
rem  and the app file setup installs from. Nothing needs installing first:
rem  it fetches Inno Setup and its own private Node.js when it needs them.
rem  The app is only rebuilt when desktop\ changed; "Build.bat /app" forces it.
rem ------------------------------------------------------------------

setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo Windows PowerShell was not found on this system.
  echo Frivo could not be built.
  echo.
  pause
  exit /b 1
)

set "EXTRA="
if /i "%~1"=="/app" set "EXTRA=-RebuildApp"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\Build.ps1" %EXTRA%
set "BUILD_EXIT=%ERRORLEVEL%"

echo.
if not "%BUILD_EXIT%"=="0" (
  echo The build did not complete. Review the message above and try again.
)
echo.
pause
exit /b %BUILD_EXIT%
