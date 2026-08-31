$ErrorActionPreference = 'SilentlyContinue'

$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
$PidFile = Join-Path $Runtime 'server.pid'
$Port = 8765

Write-Host '=== ImageTextCleaner Local Health Check ==='

$venvPython = Join-Path $Runtime 'venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $ver = & $venvPython --version 2>&1
    Write-Host "[OK] Python venv: $ver"
} else {
    Write-Host '[WARN] Local venv is missing. Run setup-local.ps1.'
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    Write-Host "[OK] Port $Port is listening. Localhost-only binding is recommended."
} else {
    Write-Host "[INFO] Port $Port is not listening."
}

if (Test-Path $PidFile) {
    $pidValue = Get-Content $PidFile | Select-Object -First 1
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($proc) { Write-Host "[OK] Service PID=$pidValue Priority=$($proc.PriorityClass)" }
    else { Write-Host '[WARN] Stale PID file found.' }
}

$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($env:LOCALAPPDATA).Substring(0,1))
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt 5) { Write-Host "[WARN] System drive free space: ${freeGB}GB" }
    else { Write-Host "[OK] System drive free space: ${freeGB}GB" }
}

function Get-FolderSizeMB($path) {
    if (-not (Test-Path $path)) { return 0 }
    $sum = (Get-ChildItem $path -File -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    if (-not $sum) { return 0 }
    return [math]::Round($sum / 1MB, 1)
}

$size = Get-FolderSizeMB $Data
if ($size -gt 2048) { Write-Host "[WARN] Project data size: ${size}MB. Cleanup is recommended." }
else { Write-Host "[OK] Project data size: ${size}MB" }

foreach ($logName in @('server-out.log','server-error.log')) {
    $log = Join-Path $Runtime $logName
    if (Test-Path $log) {
        $logMB = [math]::Round((Get-Item $log).Length / 1MB, 1)
        if ($logMB -gt 100) { Write-Host "[WARN] $logName size: ${logMB}MB" }
        else { Write-Host "[OK] $logName size: ${logMB}MB" }
    }
}

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($health.status -eq 'ok') {
        Write-Host '[OK] Web service health check passed.'
        if ($health.performance) {
            Write-Host "[OK] OCR intra=$($health.performance.intra_op_threads) inter=$($health.performance.inter_op_threads) arena=$($health.performance.cpu_mem_arena)"
        }
    }
} catch {
    Write-Host '[INFO] Web service is not running or health check failed.'
}

Write-Host '=== Health Check Complete ==='
