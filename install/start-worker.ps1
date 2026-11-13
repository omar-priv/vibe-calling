[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$AppDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$stateDir = Join-Path $env:LOCALAPPDATA 'Vibe Calling'
$logDir = Join-Path $stateDir 'logs'
$dbPath = Join-Path $stateDir 'agent-tasks.db'
$pidFile = Join-Path $stateDir 'worker.pid'
$stdoutLog = Join-Path $logDir 'worker-stdout.log'
$stderrLog = Join-Path $logDir 'worker-stderr.log'

New-Item -ItemType Directory -Force -Path $stateDir, $logDir | Out-Null

# Resolve the real python.exe. Starting the py.exe launcher itself can make
# PID tracking unreliable because it may spawn a separate interpreter.
$pythonExe = $null
$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $candidate = & $pyLauncher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0 -and $candidate) {
        $pythonExe = ([string]($candidate | Select-Object -First 1)).Trim()
    }
}
if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    $pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonExe = $pythonCommand.Source }
}
if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Python 3 was not found. Install Python 3.10+ and enable the Python launcher or add python.exe to PATH.'
}

$versionOutput = & $pythonExe -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Python could not be started.' }
$versionParts = ([string]$versionOutput).Trim().Split('.')
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 10)) {
    throw "Python 3.10 or newer is required. Found $versionOutput."
}

# Do not spawn a second worker when the logon task and start.bat race.
if (Test-Path -LiteralPath $pidFile) {
    $oldPidText = (Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    $oldPid = 0
    if ([int]::TryParse([string]$oldPidText, [ref]$oldPid) -and $oldPid -gt 0) {
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $oldPid" -ErrorAction SilentlyContinue
        if ($existing -and $existing.Name -match '^python(w)?\.exe$' -and
            $existing.CommandLine -like '*-m worker.worker*' -and
            $existing.CommandLine -like '*agent-tasks.db*') {
            if (-not $Quiet) { Write-Host "Vibe Calling worker is already running (PID $oldPid)." }
            exit 0
        }
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$workerId = 'vibe-calling-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$argumentLine = '-m worker.worker --db "' + $dbPath + '" --pid-file "' + $pidFile + '" --worker-id ' + $workerId
$process = Start-Process -FilePath $pythonExe -ArgumentList $argumentLine -WorkingDirectory $AppDir -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru

Start-Sleep -Milliseconds 900
$stillRunning = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
if (-not $stillRunning) {
    $tail = ''
    if (Test-Path -LiteralPath $stderrLog) { $tail = (Get-Content -LiteralPath $stderrLog -Tail 12 -ErrorAction SilentlyContinue) -join [Environment]::NewLine }
    throw "Worker exited during startup. $tail"
}
# worker.worker writes/removes its own PID file. Re-write it here as a
# defensive fallback in case the process was started with an older build.
if (-not (Test-Path -LiteralPath $pidFile)) {
    Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII
}
if (-not $Quiet) {
    Write-Host "Vibe Calling worker started (PID $($process.Id))."
    Write-Host "Database: $dbPath"
    Write-Host "Log: $(Join-Path $logDir 'worker.log')"
}
exit 0
