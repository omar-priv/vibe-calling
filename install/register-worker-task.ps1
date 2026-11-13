[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir
)

$ErrorActionPreference = 'Stop'
$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
$pythonExe = $null
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
    throw 'Python 3 was not found. Install Python 3.10+ before registering the worker task.'
}

$versionText = & $pythonExe -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Python could not be started.' }
$version = ([string]$versionText).Trim().Split('.')
if ([int]$version[0] -lt 3 -or ([int]$version[0] -eq 3 -and [int]$version[1] -lt 10)) {
    throw "Python 3.10 or newer is required. Found $versionText."
}

$stateDir = Join-Path $env:LOCALAPPDATA 'Vibe Calling'
$dbPath = Join-Path $stateDir 'agent-tasks.db'
$pidFile = Join-Path $stateDir 'worker.pid'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$currentUser = "$env:USERDOMAIN\$env:USERNAME"
$argumentLine = '-m worker.worker --db "' + $dbPath + '" --pid-file "' + $pidFile + '" --worker-id "scheduled-worker"'
$action = New-ScheduledTaskAction -Execute $pythonExe -Argument $argumentLine -WorkingDirectory $AppDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName 'Vibe Calling Agent Worker' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Runs the Vibe Calling agent worker in the signed-in user session.' -Force | Out-Null
Write-Host 'Task Scheduler worker task registered for the signed-in interactive user.'
