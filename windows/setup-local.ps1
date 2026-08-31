$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$Venv = Join-Path $Runtime 'venv'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
New-Item -ItemType Directory -Force -Path $Runtime, $Data | Out-Null

function Get-PythonCommand {
    $candidates = @(
        @{Cmd='py'; Args=@('-3.11')},
        @{Cmd='python'; Args=@()},
        @{Cmd=(Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime\python311-embed\python.exe'); Args=@()}
    )
    foreach ($candidate in $candidates) {
        try {
            $cmd = Get-Command $candidate.Cmd -ErrorAction Stop
            & $cmd.Source @($candidate.Args) -c "import sys; assert sys.version_info >= (3,11); print(sys.executable)" *> $null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        } catch {}
    }
    throw '未找到可用的 Python 3.11+。建议安装官方 64 位 Python，并勾选 Add Python to PATH。'
}

$py = Get-PythonCommand
$pythonExe = (Get-Command $py.Cmd -ErrorAction Stop).Source

if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    & $pythonExe @($py.Args) -m venv $Venv
}

$venvPython = Join-Path $Venv 'Scripts\python.exe'
& $venvPython -m ensurepip --upgrade
& $venvPython -m pip install --upgrade pip setuptools wheel
& $venvPython -m pip install -r (Join-Path $Root 'requirements.txt')

Write-Host "本机运行环境已准备完成：$Venv"
Write-Host "数据目录：$Data"
