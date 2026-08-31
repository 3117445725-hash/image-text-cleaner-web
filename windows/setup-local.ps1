$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$Venv = Join-Path $Runtime 'venv'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
New-Item -ItemType Directory -Force -Path $Runtime, $Data | Out-Null

function Test-PythonExe([string]$Exe, [string[]]$PrefixArgs) {
    try {
        $argsList = @()
        if ($PrefixArgs) { $argsList += $PrefixArgs }
        $argsList += @('-c', 'import sys; assert sys.version_info >= (3,11); print(sys.executable)')
        & $Exe $argsList *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    try {
        $py = (Get-Command 'py.exe' -ErrorAction Stop).Source
        if (Test-PythonExe $py @('-3.11')) {
            return @{ Exe = $py; Prefix = @('-3.11') }
        }
    } catch {}

    try {
        $python = (Get-Command 'python.exe' -ErrorAction Stop).Source
        if (Test-PythonExe $python @()) {
            return @{ Exe = $python; Prefix = @() }
        }
    } catch {}

    $known = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:ProgramFiles 'Python311\python.exe')
    )
    foreach ($candidate in $known) {
        if ((Test-Path $candidate) -and (Test-PythonExe $candidate @())) {
            return @{ Exe = $candidate; Prefix = @() }
        }
    }
    return $null
}

$pythonInfo = Find-Python
if (-not $pythonInfo) {
    Write-Host 'Python 3.11+ was not found. Trying official Python 3.11 via winget...'
    $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Python 3.11+ is required and winget is unavailable. Install official 64-bit Python 3.11 or newer.'
    }
    & $winget.Source install --id Python.Python.3.11 -e --scope user --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw 'Automatic Python installation failed.'
    }
    $pythonInfo = Find-Python
    if (-not $pythonInfo) {
        throw 'Python was installed but could not be detected. Reopen the terminal and retry.'
    }
}

$pythonExe = $pythonInfo.Exe
$prefix = @($pythonInfo.Prefix)

if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    $venvArgs = @()
    $venvArgs += $prefix
    $venvArgs += @('-m', 'venv', $Venv)
    & $pythonExe $venvArgs
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python virtual environment.' }
}

$venvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw 'Virtual environment python.exe is missing.' }

& $venvPython -m ensurepip --upgrade
if ($LASTEXITCODE -ne 0) { throw 'ensurepip failed.' }

& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed.' }

& $venvPython -m pip install -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

Write-Host "Local Python runtime is ready: $Venv"
Write-Host "Data directory: $Data"
