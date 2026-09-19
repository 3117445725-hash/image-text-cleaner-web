$ErrorActionPreference = 'SilentlyContinue'
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$PidFile = Join-Path $Runtime 'server.pid'

if (-not (Test-Path $PidFile)) {
    Write-Host 'Service is not running.'
    exit 0
}

$pidValue = Get-Content $PidFile | Select-Object -First 1
$proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
if ($proc) {
    Stop-Process -Id $pidValue -Force
    Write-Host "Stopped service PID=$pidValue"
}
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
