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
    Write-Host 'Restoring previous local version...' -ForegroundColor Yellow
    try { Stop-ExistingService } catch {}
    if (Test-Path $InstallRoot) { Remove-Item $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if (Test-Path $PreviousRoot) { Move-Item $PreviousRoot $InstallRoot -Force }
}

New-Item -ItemType Directory -Force -Path $Runtime, $FastTemp | Out-Null

try {
    Step 'Stop existing OCR service'
    Stop-ExistingService

    Step 'Sync latest optimized build from GitHub'
    Remove-Item $UpdateRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $archiveUrl = "https://codeload.github.com/$RepoOwner/$RepoName/zip/refs/heads/$Branch"
    Invoke-WebRequest -Uri $archiveUrl -OutFile $ZipPath -UseBasicParsing
    Expand-Archive -Path $ZipPath -DestinationPath $ExtractRoot -Force
    $sourceRoot = Get-ChildItem $ExtractRoot -Directory | Select-Object -First 1
    if (-not $sourceRoot -or -not (Test-Path (Join-Path $sourceRoot.FullName 'requirements.txt'))) {
        throw 'Unexpected GitHub archive structure.'
    }

    Remove-Item $PreviousRoot -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $InstallRoot) { Move-Item $InstallRoot $PreviousRoot -Force }
    Move-Item $sourceRoot.FullName $InstallRoot -Force

    Step 'Check Python environment and dependencies'
    $newHash = (Get-FileHash (Join-Path $InstallRoot 'requirements.txt') -Algorithm SHA256).Hash
    $oldHash = if (Test-Path $ReqHashFile) { (Get-Content $ReqHashFile -ErrorAction SilentlyContinue | Select-Object -First 1) } else { '' }
    $venvPython = Join-Path $Runtime 'venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython) -or $newHash -ne $oldHash) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'windows\setup-local.ps1')
        if ($LASTEXITCODE -ne 0) { throw 'Python environment install/update failed.' }
        $newHash | Set-Content -Path $ReqHashFile -Encoding ascii
    } else {
        Write-Host 'Python dependencies are unchanged; skipping reinstall.' -ForegroundColor DarkGray
    }

    Step 'Compile-check local Python code'
    & $venvPython -m compileall -q (Join-Path $InstallRoot 'app')
    if ($LASTEXITCODE -ne 0) { throw 'Python compile check failed.' }

    Step 'Turbo-start OCR service'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $InstallRoot 'windows\start-local.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'OCR service startup failed.' }

    Step 'Verify live performance configuration'
    $health = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 10
    if ($health.status -ne 'ok') { throw 'Health check failed.' }
    $perf = $health.performance

    $checks = [ordered]@{
        'OCR engine prewarmed' = [bool]$perf.engine_ready
        'intra-op=6' = ([int]$perf.intra_op_threads -eq 6)
        'inter-op=1' = ([int]$perf.inter_op_threads -eq 1)
        'CPU Memory Arena enabled' = [bool]$perf.cpu_mem_arena
        'Prewarm enabled' = [bool]$perf.prewarm_enabled
        'Excel limit 50MB' = ([int]$perf.max_upload_mb -eq 50)
        '5000 links per job' = ([int]$perf.max_urls_per_job -eq 5000)
        'Image limit 15MB' = ([int]$perf.max_image_mb -eq 15)
        '40M image pixels' = ([int64]$perf.max_image_pixels -eq 40000000)
        'NVMe fast temp' = ([string]$perf.temp_dir -like '*ImageTextCleaner\fast-temp*')
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
            Write-Host "[OK] OCR PID=$pidValue Priority=$($proc.PriorityClass)" -ForegroundColor Green
            if ($proc.PriorityClass -ne 'High') {
                Write-Host '[WARN] OCR process is not running at High priority.' -ForegroundColor Yellow
            }
        }
    }

    if ($failed.Count -gt 0) {
        throw "$($failed.Count) performance checks failed."
    }

    Remove-Item $PreviousRoot -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item $UpdateRoot -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host 'Latest optimized GitHub build is synced and running.' -ForegroundColor Green
    Write-Host "Local app: $InstallRoot"
    Write-Host 'URL: http://127.0.0.1:8765/'
    Write-Host 'Run this script again anytime to update and start.'
    Write-Host '========================================' -ForegroundColor Green
}
catch {
    Write-Host "`nUpdate/start failed: $($_.Exception.Message)" -ForegroundColor Red
    if (Test-Path $PreviousRoot) {
        Restore-PreviousVersion
        Write-Host 'Previous local version restored.' -ForegroundColor Yellow
    }
    exit 1
}
