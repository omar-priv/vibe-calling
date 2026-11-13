@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Vibe Calling — Windows Agent Runtime v2
echo ============================================
echo.

:: Determine Python executable
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)

:: ------------------------------------------------------------------
:: 1. Start the separate worker in the logged-in user's session.
::    The helper resolves the actual Python executable and starts
::    worker.worker as a hidden process. It also prevents duplicate
::    launches and writes logs/PID under LOCALAPPDATA.
:: ------------------------------------------------------------------
echo Starting background agent worker...
call "%~dp0install\start-worker.bat" -quiet
if errorlevel 1 (
  echo   WARNING: The background worker could not be started.
  echo   Check %LOCALAPPDATA%\Vibe Calling\logs\worker-stderr.log
) else (
  echo   Background worker launch checked. Logs: %LOCALAPPDATA%\Vibe Calling\logs\worker.log
)

:: ------------------------------------------------------------------
:: 2. Start the local web server (127.0.0.1 only).
::    It serves the UI and exposes the worker/task management API.
:: ------------------------------------------------------------------
echo Starting Vibe Calling local server...
%PY% server.py
if errorlevel 1 (
  echo.
  echo Vibe Calling could not start. Check that Python 3 is installed.
  pause
)
endlocal
