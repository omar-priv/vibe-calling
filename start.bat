@echo off
setlocal
cd /d "%~dp0"
echo Starting Vibe Calling local server...
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py
) else (
  python server.py
)
if errorlevel 1 (
  echo.
  echo Vibe Calling could not start. Check that Python 3 is installed.
  pause
)
endlocal
