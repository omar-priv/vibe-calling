@echo off
setlocal
cd /d "%~dp0.."

echo ============================================
echo  Vibe Calling Windows Agent Runtime v2
echo  Installer
echo ============================================
echo.

:: Determine Python executable
where py >nul 2>nul
if %errorlevel%==0 (
  set PY=py -3
) else (
  set PY=python
)

echo [1/4] Installing Python dependencies...
%PY% -m pip install -r install/requirements-windows.txt
if %errorlevel% neq 0 (
  echo ERROR: Failed to install Python dependencies.
  pause
  exit /b 1
)

echo [2/4] Installing Chromium browser for Playwright automation...
%PY% -m playwright install chromium
if %errorlevel% neq 0 (
  echo WARNING: Playwright Chromium install failed. Browser automation will be unavailable.
)

echo [3/4] Registering Windows Task Scheduler task (runs worker at user logon)...
set APP_DIR=%CD%
set LOG_DIR=%LOCALAPPDATA%\Vibe Calling\logs

:: Create log directories
if not exist "%LOCALAPPDATA%\Vibe Calling" mkdir "%LOCALAPPDATA%\Vibe Calling"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Delete existing task if present
schtasks /delete /tn "Vibe Calling Agent Worker" /f >nul 2>&1

:: Register the actual Python module as an interactive per-user task. The
:: scheduled task supervises the long-running worker instead of launching a
:: detached child that Task Scheduler cannot restart.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-worker-task.ps1" -AppDir "%APP_DIR%"
if %errorlevel% neq 0 (
  echo ERROR: Failed to create Task Scheduler task.
  pause
  exit /b 1
)

echo [4/4] Creating Startup shortcut (optional auto-launch of the UI)...
set SHORTCUT="%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Vibe Calling.lnk"
if not exist %SHORTCUT% (
  echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\vc-shortcut.vbs"
  echo sLinkFile = "%SHORTCUT%" >> "%TEMP%\vc-shortcut.vbs"
  echo oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\vc-shortcut.vbs"
  echo oLink.TargetPath = "%APP_DIR%\start.bat" >> "%TEMP%\vc-shortcut.vbs"
  echo oLink.WorkingDirectory = "%APP_DIR%" >> "%TEMP%\vc-shortcut.vbs"
  echo oLink.Description = "Vibe Calling local agent runtime" >> "%TEMP%\vc-shortcut.vbs"
  echo oLink.Save >> "%TEMP%\vc-shortcut.vbs"
  cscript //nologo "%TEMP%\vc-shortcut.vbs"
  del "%TEMP%\vc-shortcut.vbs"
)

echo.
echo ============================================
echo  Installation complete.
echo ============================================
echo.
echo  The background worker is registered as an interactive Task Scheduler task:
echo    "Vibe Calling Agent Worker" (runs in your signed-in Windows session).
echo  To start Vibe Calling now, double-click start.bat.
echo  To start only the worker, run: install/start-worker.bat
echo  To uninstall, run: install/uninstall.bat
echo.
pause
endlocal
