@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-worker.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo Could not safely stop the Vibe Calling worker. Exit code: %RC%
endlocal & exit /b %RC%
