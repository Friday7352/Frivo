@echo off
rem ------------------------------------------------------------------
rem  Frivo App — one-click build
rem ------------------------------------------------------------------
rem  Double-click this file from the project folder to create a fresh
rem  desktop\dist\FrivoApp-Setup-<version>.exe. Needs Node.js (LTS) from
rem  https://nodejs.org. The app's version is "version" in
rem  desktop\package.json, separate from Frivo's VERSION file.
rem ------------------------------------------------------------------

setlocal
cd /d "%~dp0desktop"

where npm >nul 2>&1
if errorlevel 1 (
  echo Node.js was not found on this system. Install the LTS version from
  echo https://nodejs.org, then run this again.
  echo.
  pause
  exit /b 1
)

call npm ci
if errorlevel 1 goto failed
call npm test
if errorlevel 1 goto failed
call npm run dist
if errorlevel 1 goto failed

echo.
echo Done. The app's installer is in desktop\dist as FrivoApp-Setup-^<version^>.exe.
echo.
pause
exit /b 0

:failed
echo.
echo The app build did not complete. Review the message above and try again.
echo.
pause
exit /b 1
