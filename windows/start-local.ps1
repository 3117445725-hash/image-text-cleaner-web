$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$VenvPython = Join-Path $Runtime 'venv\Scripts\python.exe'
$PidFile = Join-Path $Runtime 'server.pid'
$LogFile = Join-Path $Runtime 'server.log'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
$Port = 8765

if (-not (Test-Path $VenvPython)) {
    & (Join-Path $PSScriptRoot 'setup-local.ps1')
}

if (Test-Path $PidFile) {
    $oldPid = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "服务已在运行，PID=$oldPid"
        Start-Process "http://127.0.0.1:$Port/"
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "端口 $Port 已被其他程序占用。请先关闭占用程序。"
}

# Full-capability local profile: keep the original service limits instead of reducing functionality.
$env:DATA_DIR = $Data
$env:MAX_UPLOAD_MB = '50'
$env:MAX_URLS_PER_JOB = '5000'
$env:MAX_IMAGE_MB = '15'
$env:MAX_IMAGE_PIXELS = '40000000'
$env:MAX_CONCURRENT_JOBS = '1'
$env:JOB_TTL_HOURS = '24'

New-Item -ItemType Directory -Force -Path $Runtime, $Data | Out-Null

$argList = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$Port",'--workers','1','--no-access-log')
$process = Start-Process -FilePath $VenvPython -ArgumentList $argList -WorkingDirectory $Root -RedirectStandardOutput $LogFile -RedirectStandardError $LogFile -PassThru -WindowStyle Hidden
$process.Id | Set-Content -Path $PidFile -Encoding ascii

$deadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Host "服务启动成功：http://127.0.0.1:$Port/"
            Start-Process "http://127.0.0.1:$Port/"
            exit 0
        }
    } catch {}
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
throw "服务启动失败，请查看日志：$LogFile"
