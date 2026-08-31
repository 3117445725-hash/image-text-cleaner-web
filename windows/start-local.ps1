$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $env:LOCALAPPDATA 'ImageTextCleanerRuntime'
$VenvPython = Join-Path $Runtime 'venv\Scripts\python.exe'
$PidFile = Join-Path $Runtime 'server.pid'
$StdoutLog = Join-Path $Runtime 'server-out.log'
$StderrLog = Join-Path $Runtime 'server-error.log'
$Data = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\data'
$FastTemp = Join-Path $env:LOCALAPPDATA 'ImageTextCleaner\fast-temp'
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

New-Item -ItemType Directory -Force -Path $Runtime, $Data, $FastTemp | Out-Null

# i5-12500 / 6 physical cores / 12 logical threads / 24GB RAM workstation profile.
# Preserve full product capability while tuning the inference engine around physical cores.
$env:DATA_DIR = $Data
$env:TEMP = $FastTemp
$env:TMP = $FastTemp
$env:MAX_UPLOAD_MB = '50'
$env:MAX_URLS_PER_JOB = '5000'
$env:MAX_IMAGE_MB = '15'
$env:MAX_IMAGE_PIXELS = '40000000'
$env:MAX_CONCURRENT_JOBS = '1'
$env:JOB_TTL_HOURS = '24'

$env:OCR_INTRA_OP_THREADS = '6'
$env:OCR_INTER_OP_THREADS = '1'
$env:OCR_CPU_MEM_ARENA = '1'
$env:OCR_PREWARM = '1'

# Keep common numerical backends from over-subscribing the 6 physical cores.
$env:OMP_NUM_THREADS = '6'
$env:OMP_WAIT_POLICY = 'ACTIVE'
$env:MKL_NUM_THREADS = '6'
$env:OPENBLAS_NUM_THREADS = '6'
$env:NUMEXPR_NUM_THREADS = '6'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

$argList = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$Port",'--workers','1','--no-access-log')
$process = Start-Process -FilePath $VenvPython -ArgumentList $argList -WorkingDirectory $Root -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru -WindowStyle Hidden
$process.Id | Set-Content -Path $PidFile -Encoding ascii

try {
    # High is intentional for dedicated OCR throughput; never use RealTime priority.
    $process.PriorityClass = 'High'
} catch {
    Write-Warning "无法提升 OCR 进程优先级，将继续使用系统默认优先级。"
}

$deadline = (Get-Date).AddSeconds(45)
do {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.status -eq 'ok') {
            Write-Host "OCR Turbo 服务启动成功：http://127.0.0.1:$Port/"
            Write-Host "CPU: 6 个物理核用于 ONNX Runtime；内存 arena 已开启；临时目录位于 NVMe。"
            Start-Process "http://127.0.0.1:$Port/"
            exit 0
        }
    } catch {}
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
throw "服务启动失败，请查看日志：$StderrLog"
