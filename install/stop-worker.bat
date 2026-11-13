@echo off
setlocal
echo Stopping Vibe Calling background worker...
taskkill /IM python.exe /F >nul 2>&1
taskkill /IM py.exe /F >nul 2>&1
echo Worker processes stopped.
echo NOTE: This also stops any co-running python/py processes.
endlocal
