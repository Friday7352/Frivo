@echo off
rem Frivo dictation speed test. Run it on the PC Frivo runs on.
rem Makes a private Python environment in %TEMP%\frivo-dictation-bench,
rem downloads Moonshine (about 400 MB the first time) and times it.
rem Optional: drag .wav files of your own speech onto this file.
setlocal
set "HERE=%~dp0"
set "VENV=%TEMP%\frivo-dictation-bench"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 isn't installed on this PC. Install it from python.org, then run this again.
  pause
  exit /b 1
)
if not exist "%VENV%\Scripts\python.exe" (
  echo Making a private Python environment...
  %PY% -m venv "%VENV%" || goto :fail
)
echo Installing Moonshine...
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check moonshine-voice psutil || goto :fail
echo.
"%VENV%\Scripts\python.exe" -u "%HERE%bench_dictation.py" %*
echo.
echo Saved to %HERE%results.txt
pause
exit /b 0
:fail
echo Something went wrong. The text above says what.
pause
exit /b 1
