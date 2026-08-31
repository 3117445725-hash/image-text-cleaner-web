$ErrorActionPreference = 'SilentlyContinue'
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$PidFile = Join-Path $Runtime 'server.pid'

if (-not (Test-Path $PidFile)) {
    Write-Host '服务未运行。'
    exit 0
}

$pidValue = Get-Content $PidFile | Select-Object -First 1
$proc = Get-Process -Id $pidValue
if ($proc) {
    Stop-Process -Id $pidValue -Force
    Write-Host "已停止服务 PID=$pidValue"
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
