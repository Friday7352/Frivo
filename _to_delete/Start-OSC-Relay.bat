@echo off
rem ------------------------------------------------------------------
rem  Frivo - OSC relay
rem ------------------------------------------------------------------
rem  Run this on the SAME PC as VRChat when Frivo's own server runs on
rem  a different PC. VRChat's OSC output always goes to 127.0.0.1 with
rem  no setting to redirect it, so mute-synced dictation (Settings >
rem  OSC controls) can't see anything across machines without this
rem  relaying it over. Not needed at all if Frivo and VRChat run on
rem  the same PC.
rem
rem  Usage: double-click and enter the Frivo server's address when
rem  asked, or run `Start-OSC-Relay.bat 192.168.1.50` directly.
rem ------------------------------------------------------------------

setlocal enabledelayedexpansion
cd /d "%~dp0app"

if "%~1"=="" (
  echo Frivo OSC relay
  echo ================
  echo.
  echo Forwards VRChat's OSC output to a Frivo server running on another PC,
  echo so mute-synced dictation ^(Settings ^> OSC controls^) works across
  echo machines. Only needed when VRChat and Frivo run on different PCs.
  echo.
  set /p TARGET="Frivo server's LAN address (e.g. 192.168.1.50): "
) else (
  set "TARGET=%~1"
)

if "!TARGET!"=="" (
  echo No address entered. Exiting.
  pause
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on this PC.
  echo.
  echo Install Python from python.org and run this again. The relay needs
  echo nothing else — no pip install, none of Frivo's other requirements.
  pause
  exit /b 1
)

echo.
echo Starting relay -^> !TARGET!:9001
echo In VRChat, make sure OSC is enabled under the Options menu.
echo Press CTRL+C to stop.
echo.
python osc_relay.py --target "!TARGET!"

echo.
pause
endlocal
