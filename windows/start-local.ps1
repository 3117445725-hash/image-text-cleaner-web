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
    if ($LASTEXITCODE -ne 0) { throw 'Local Python setup failed.' }
}

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "Service is already running. PID=$oldPid"
        Start-Process "http://127.0.0.1:$Port/"
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "Port $Port is already in use."
}

New-Item -ItemType Directory -Force -Path $Runtime, $Data, $FastTemp | Out-Null

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

$env:OMP_NUM_THREADS = '6'
$env:OMP_WAIT_POLICY = 'ACTIVE'
$env:MKL_NUM_THREADS = '6'
$env:OPENBLAS_NUM_THREADS = '6'
$env:NUMEXPR_NUM_THREADS = '6'
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'

Remove-Item $StdoutLog, $StderrLog -Force -ErrorAction SilentlyContinue
$argList = @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',"$Port",'--workers','1','--no-access-log')
$process = Start-Process -FilePath $VenvPython -ArgumentList $argList -WorkingDirectory $Root -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru -WindowStyle Hidden
$process.Id | Set-Content -Path $PidFile -Encoding ascii

try {
    $process.PriorityClass = 'High'
} catch {
    Write-Warning 'Could not raise OCR process priority. Continuing with the default priority.'
}

$deadline = (Get-Date).AddSeconds(90)
do {
    Start-Sleep -Milliseconds 750
    if ($process.HasExited) {
        $err = if (Test-Path $StderrLog) { Get-Content $StderrLog -Raw -ErrorAction SilentlyContinue } else { '' }
        throw "OCR service exited during startup. $err"
    }
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        if ($health.status -eq 'ok') {
            Write-Host "OCR Turbo service started: http://127.0.0.1:$Port/"
            Write-Host 'ONNX Runtime: 6 intra-op threads, 1 inter-op thread, CPU memory arena enabled.'
            Write-Host "Fast temp: $FastTemp"
            Start-Process "http://127.0.0.1:$Port/"
            exit 0
        }
    } catch {}
} while ((Get-Date) -lt $deadline)

Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
$lastError = if (Test-Path $StderrLog) { Get-Content $StderrLog -Tail 30 -ErrorAction SilentlyContinue | Out-String } else { '' }
throw "OCR service startup timed out. See: $StderrLog`n$lastError"
