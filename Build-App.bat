@echo off
rem ------------------------------------------------------------------
rem  Frivo App — one-click build
rem ------------------------------------------------------------------
rem  Double-click this file from the project folder to create a fresh
rem  desktop\dist\FrivoApp-Setup-<version>.exe. Nothing needs installing
rem  first: build\Build-App.ps1 downloads its own copy of Node.js into
rem  desktop\.tools the first time. The app's version is "version" in
rem  desktop\package.json, separate from Frivo's VERSION file.
rem ------------------------------------------------------------------

setlocal
cd /d "%~dp0"

where powershell >nul 2>&1
if errorlevel 1 (
  echo Windows PowerShell was not found on this system.
  echo The app could not be built.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\Build-App.ps1"
set "BUILD_EXIT=%ERRORLEVEL%"

echo.
if not "%BUILD_EXIT%"=="0" (
  echo The app build did not complete. Review the message above and try again.
) else (
  echo Done. The app's installer is in desktop\dist.
)
echo.
pause
exit /b %BUILD_EXIT%
