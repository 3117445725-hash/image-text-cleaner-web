$ErrorActionPreference = 'SilentlyContinue'

$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
$PidFile = Join-Path $Runtime 'server.pid'
$Port = 8765

Write-Host '=== ImageTextCleaner 本机健康检查 ==='

# Python
$venvPython = Join-Path $Runtime 'venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $ver = & $venvPython --version 2>&1
    Write-Host "[OK] Python venv: $ver"
} else {
    Write-Host '[WARN] 尚未建立独立 venv，请运行 setup-local.ps1'
}

# Port
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen
if ($listener) {
    Write-Host "[OK] 端口 $Port 正在监听，仅建议绑定 127.0.0.1"
} else {
    Write-Host "[INFO] 端口 $Port 当前未监听"
}

# PID/process
if (Test-Path $PidFile) {
    $pidValue = Get-Content $PidFile | Select-Object -First 1
    $proc = Get-Process -Id $pidValue
    if ($proc) { Write-Host "[OK] 服务进程 PID=$pidValue" }
    else { Write-Host '[WARN] 存在失效 PID 文件，可安全删除' }
}

# Disk
$drive = Get-PSDrive -Name ([IO.Path]::GetPathRoot($env:LOCALAPPDATA).Substring(0,1))
if ($drive) {
    $freeGB = [math]::Round($drive.Free / 1GB, 1)
    if ($freeGB -lt 5) { Write-Host "[WARN] 系统盘剩余空间仅 ${freeGB}GB" }
    else { Write-Host "[OK] 系统盘剩余 ${freeGB}GB" }
}

# Project data size
function Get-FolderSizeMB($path) {
    if (-not (Test-Path $path)) { return 0 }
    $sum = (Get-ChildItem $path -File -Recurse | Measure-Object Length -Sum).Sum
    if (-not $sum) { return 0 }
    return [math]::Round($sum / 1MB, 1)
}
$size = Get-FolderSizeMB $Data
if ($size -gt 2048) { Write-Host "[WARN] 项目数据目录已达 ${size}MB，建议清理过期任务" }
else { Write-Host "[OK] 项目数据目录 ${size}MB" }

# Log size
$log = Join-Path $Runtime 'server.log'
if (Test-Path $log) {
    $logMB = [math]::Round((Get-Item $log).Length / 1MB, 1)
    if ($logMB -gt 100) { Write-Host "[WARN] server.log 已达 ${logMB}MB" }
    else { Write-Host "[OK] server.log ${logMB}MB" }
}

# HTTP health
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($health.status -eq 'ok') { Write-Host '[OK] Web 服务健康检查通过' }
} catch {
    Write-Host '[INFO] Web 服务当前未启动或健康检查未通过'
}

Write-Host '=== 检查完成 ==='
