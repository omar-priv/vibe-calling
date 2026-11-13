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
:: 1. Start the background worker (independent of the browser UI).
::    It runs as a detached process so agent tasks continue after
::    all browser tabs are closed. It owns the durable SQLite task
::    store and executes browser / computer / sandbox tool calls.
:: ------------------------------------------------------------------
echo Starting background agent worker...
%PY% worker.py --db "%LOCALAPPDATA%\Vibe Calling\agent-tasks.db" --worker-id "worker-%RANDOM%%RANDOM%" > worker-stdout.log 2> worker-stderr.log &
if %errorlevel%==0 (
  echo   Worker started (PID %ERRORLEVEL%). Logs: worker-stdout.log / worker-stderr.log
) else (
  echo   WARNING: Worker could not start. Tasks will not run in the background.
)
timeout /t 2 >nul

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
