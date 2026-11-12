@echo off
setlocal
cd /d "%~dp0"
echo Installing optional Vibe Calling automation features...
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)
%PY% --version
if errorlevel 1 goto :failed
%PY% -m pip install -r automation-requirements.txt
if errorlevel 1 goto :failed
%PY% -m playwright install chromium
if errorlevel 1 goto :failed
echo.
echo Optional automation dependencies installed.
echo Restart Vibe Calling, then enable the features in Agent tools.
goto :done
:failed
echo.
echo Installation failed. Check Python, pip, and network access, then retry.
:done
pause
endlocal
