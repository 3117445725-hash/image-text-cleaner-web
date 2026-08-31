$ErrorActionPreference = 'Stop'

$RepoOwner = '3117445725-hash'
$RepoName = 'image-text-cleaner-web'
$Branch = 'optimize-production-hardening'
$InstallRoot = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerApp'
$PreviousRoot = "$InstallRoot.previous"
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$FastTemp = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\fast-temp'
$UpdateRoot = Join-Path $FastTemp 'update'
$ZipPath = Join-Path $UpdateRoot 'source.zip'
$ExtractRoot = Join-Path $UpdateRoot 'extract'
$ReqHashFile = Join-Path $Runtime 'requirements.sha256'
$PidFile = Join-Path $Runtime 'server.pid'
$HealthUrl = 'http://127.0.0.1:8765/health'

function Step([string]$text) {
    Write-Host "`n==> $text" -ForegroundColor Cyan
}

function Stop-ExistingService {
    if (Test-Path (Join-Path $InstallRoot 'windows\stop-local.ps1')) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'windows\stop-local.ps1') | Out-Host
        return
    }
    if (Test-Path $PidFile) {
        $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

function Restore-PreviousVersion {
    Write-Host '正在恢复上一个可用版本…' -ForegroundColor Yellow
    try { Stop-ExistingService } catch {}
    if (Test-Path $InstallRoot) { Remove-Item $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $PreviousRoot) { Move-Item $PreviousRoot $InstallRoot -Force }
}

New-Item -ItemType Directory -Force -Path $Runtime, $FastTemp | Out-Null

try {
    Step '停止旧 OCR 服务'
    Stop-ExistingService

    Step '从 GitHub 同步最新优化版'
    Remove-Item $UpdateRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $archiveUrl = "https://codeload.github.com/$RepoOwner/$RepoName/zip/refs/heads/$Branch"
    Invoke-WebRequest -Uri $archiveUrl -OutFile $ZipPath -UseBasicParsing
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractRoot -Force
    $sourceRoot = Get-ChildItem $ExtractRoot -Directory | Select-Object -First 1
    if (-not $sourceRoot -or -not (Test-Path (Join-Path $sourceRoot.FullName 'requirements.txt'))) {
        throw 'GitHub 下载包结构异常。'
    }

    Remove-Item $PreviousRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallRoot) { Move-Item $InstallRoot $PreviousRoot -Force }
    Move-Item $sourceRoot.FullName $InstallRoot -Force

    Step '检查 Python 环境与依赖'
    $newHash = (Get-FileHash (Join-Path $InstallRoot 'requirements.txt') -Algorithm SHA256).Hash
    $oldHash = if (Test-Path $ReqHashFile) { (Get-Content $ReqHashFile -ErrorAction SilentlyContinue | Select-Object -First 1) } else { '' }
    $venvPython = Join-Path $Runtime 'venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython) -or $newHash -ne $oldHash) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'windows\setup-local.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Python 环境安装/更新失败。' }
        $newHash | Set-Content -Path $ReqHashFile -Encoding ascii
    } else {
        Write-Host 'Python 依赖未变化，跳过重复安装。' -ForegroundColor DarkGray
    }

    Step '编译检查本机 Python 代码'
    & $venvPython -m compileall -q (Join-Path $InstallRoot 'app')
    if ($LASTEXITCODE -ne 0) { throw 'Python 编译检查失败。' }

    Step 'Turbo 启动 OCR 服务'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'windows\start-local.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'OCR 服务启动失败。' }

    Step '核验实际性能配置'
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 10
    if ($health.status -ne 'ok') { throw '健康检查未通过。' }
    $perf = $health.performance

    $checks = [ordered]@{
        'OCR模型已预热' = [bool]$perf.engine_ready
        'intra-op=6' = ([int]$perf.intra_op_threads -eq 6)
        'inter-op=1' = ([int]$perf.inter_op_threads -eq 1)
        'CPU Memory Arena开启' = [bool]$perf.cpu_mem_arena
        '预热功能开启' = [bool]$perf.prewarm_enabled
        'Excel上限50MB' = ([int]$perf.max_upload_mb -eq 50)
        '单任务5000链接' = ([int]$perf.max_urls_per_job -eq 5000)
        '单图15MB' = ([int]$perf.max_image_mb -eq 15)
        '4000万像素' = ([int64]$perf.max_image_pixels -eq 40000000)
        'NVMe临时目录' = ([string]$perf.temp_dir -like '*ImageTextCleaner\fast-temp*')
    }

    $failed = @($checks.GetEnumerator() | Where-Object { -not $_.Value })
    foreach ($item in $checks.GetEnumerator()) {
        $mark = if ($item.Value) { '[OK]' } else { '[FAIL]' }
        $color = if ($item.Value) { 'Green' } else { 'Red' }
        Write-Host "$mark $($item.Key)" -ForegroundColor $color
    }

    if (Test-Path $PidFile) {
        $pidValue = Get-Content $PidFile | Select-Object -First 1
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[OK] OCR进程 PID=$pidValue，优先级=$($proc.PriorityClass)" -ForegroundColor Green
            if ($proc.PriorityClass -ne 'High') {
                Write-Host '[WARN] 进程未保持 High 优先级，但服务本身可正常运行。' -ForegroundColor Yellow
            }
        }
    }

    if ($failed.Count -gt 0) {
        throw "有 $($failed.Count) 项性能核验未通过。"
    }

    Remove-Item $PreviousRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $UpdateRoot -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host 'GitHub最新优化版已同步并完成Turbo启动。' -ForegroundColor Green
    Write-Host "本机程序：$InstallRoot"
    Write-Host "访问地址：http://127.0.0.1:8765/"
    Write-Host '以后再次运行本脚本即可自动更新并启动。'
    Write-Host '========================================' -ForegroundColor Green
}
catch {
    Write-Host "`n更新/启动失败：$($_.Exception.Message)" -ForegroundColor Red
    if (Test-Path $PreviousRoot) {
        Restore-PreviousVersion
        Write-Host '已恢复更新前版本。' -ForegroundColor Yellow
    }
    exit 1
}
