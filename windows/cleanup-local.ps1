param(
    [int]$OlderThanHours = 24
)

$ErrorActionPreference = 'SilentlyContinue'
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
$cutoff = (Get-Date).AddHours(-[math]::Abs($OlderThanHours))

$removed = 0
if (Test-Path $Data) {
    Get-ChildItem $Data -Directory | Where-Object { $_.LastWriteTime -lt $cutoff } | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force
        if (-not (Test-Path $_.FullName)) { $removed++ }
    }
}

$log = Join-Path $Runtime 'server.log'
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 100MB)) {
    $archive = Join-Path $Runtime ("server-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Move-Item $log $archive -Force
    Get-ChildItem $Runtime -Filter 'server-*.log' -File | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 | Remove-Item -Force
}

$pidFile = Join-Path $Runtime 'server.pid'
if (Test-Path $pidFile) {
    $pidValue = Get-Content $pidFile | Select-Object -First 1
    if (-not (Get-Process -Id $pidValue)) { Remove-Item $pidFile -Force }
}

Write-Host "清理完成：删除 $removed 个超过 $OlderThanHours 小时的项目任务目录。"
