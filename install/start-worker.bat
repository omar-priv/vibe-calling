@echo off
setlocal
cd /d "%~dp0.."

echo Starting Vibe Calling background worker...
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)

:: Run the worker as a detached process (no console window).
start "Vibe Calling Worker" /b %PY% worker.py --db "%LOCALAPPDATA%\Vibe Calling\agent-tasks.db" --worker-id "worker-%RANDOM%%RANDOM%"
echo Worker started. Logs: %LOCALAPPDATA%\Vibe Calling\logs\worker.log
endlocal
