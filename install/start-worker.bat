@echo off
setlocal
cd /d "%~dp0.."
set "QUIET="
if /i "%~1"=="-quiet" set "QUIET=-Quiet"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-worker.ps1" -AppDir "%CD%" %QUIET%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo ERROR: Vibe Calling Agent Worker did not start. Exit code: %RC%
  echo Check "%LOCALAPPDATA%\Vibe Calling\logs\worker-stderr.log".
  if not defined QUIET pause
)
endlocal & exit /b %RC%
