@echo off
setlocal
echo Uninstalling Vibe Calling Windows Agent Runtime v2...

:: Remove Task Scheduler task
schtasks /delete /tn "Vibe Calling Agent Worker" /f >nul 2>&1
if %errorlevel%==0 (
  echo   Task Scheduler task removed.
) else (
  echo   Task Scheduler task not found (already removed).
)

:: Remove Startup shortcut
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Vibe Calling.lnk" (
  del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Vibe Calling.lnk"
  echo   Startup shortcut removed.
)

echo.
echo Uninstall complete. Your data (tasks, logs, browser profile) is preserved under:
echo   %LOCALAPPDATA%\Vibe Calling\
endlocal
pause
