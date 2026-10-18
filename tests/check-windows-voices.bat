@echo off
rem NEW (1.5.0): runs check-windows-voices.ps1 (see that file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-windows-voices.ps1"
echo.
pause
