param(
    [int]$OlderThanHours = 24
)

$ErrorActionPreference = 'SilentlyContinue'
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
$cutoff = (Get-Date).AddHours(-[math]::Abs($OlderThanHours))

$removed = 0
if (Test-Path $Data) {
    Get-ChildItem $Data -Directory -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt $cutoff } | ForEach-Object {
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $_.FullName)) { $removed++ }
    }
}

foreach ($logName in @('server-out.log','server-error.log')) {
    $log = Join-Path $Runtime $logName
    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 100MB)) {
        $baseName = [IO.Path]::GetFileNameWithoutExtension($logName)
        $archive = Join-Path $Runtime ("{0}-{1}.log" -f $baseName, (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Move-Item $log $archive -Force
        Get-ChildItem $Runtime -Filter "$baseName-*.log" -File | Sort-Object LastWriteTime -Descending | Select-Object -Skip 3 | Remove-Item -Force
    }
}

$pidFile = Join-Path $Runtime 'server.pid'
if (Test-Path $pidFile) {
    $pidValue = Get-Content $pidFile | Select-Object -First 1
    if (-not (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
        Remove-Item $pidFile -Force
    }
}

Write-Host "Cleanup complete. Removed $removed job directories older than $OlderThanHours hours."
