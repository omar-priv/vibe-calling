[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$stateDir = Join-Path $env:LOCALAPPDATA 'Vibe Calling'
$pidFile = Join-Path $stateDir 'worker.pid'

# Stop a Task Scheduler-managed instance first, so its restart-on-failure
# policy does not immediately respawn the process after taskkill. This does
# not disable the logon trigger; a later sign-in may start it again.
$scheduledTask = Get-ScheduledTask -TaskName 'Vibe Calling Agent Worker' -ErrorAction SilentlyContinue
if ($scheduledTask -and $scheduledTask.State -eq 'Running') {
    Stop-ScheduledTask -TaskName 'Vibe Calling Agent Worker' -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
}

if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host 'No Vibe Calling worker PID file was found. It may already be stopped.'
    exit 0
}

$pidText = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
$workerPid = 0
if (-not [int]::TryParse([string]$pidText, [ref]$workerPid) -or $workerPid -le 0) {
    throw 'The worker PID file is invalid. Refusing to stop any process.'
}

$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $workerPid" -ErrorAction SilentlyContinue
if (-not $processInfo) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    Write-Host 'The recorded worker process is already stopped; stale PID file removed.'
    exit 0
}

if ($processInfo.Name -notmatch '^python(w)?\.exe$' -or
    $processInfo.CommandLine -notlike '*-m worker.worker*' -or
    $processInfo.CommandLine -notlike '*agent-tasks.db*') {
    throw 'PID does not identify the Vibe Calling worker. Refusing to stop it.'
}

& taskkill.exe /PID $workerPid /T /F | Out-Null
if ($LASTEXITCODE -ne 0) { throw "taskkill failed with exit code $LASTEXITCODE." }
Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Write-Host 'Vibe Calling worker stopped. Any in-flight task will be recovered after its lease expires.'
