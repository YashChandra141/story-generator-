# Word by Word - run backend + frontend with one command
#   .\dev.ps1
# Backend  -> http://127.0.0.1:8000  (FastAPI, logs: uvicorn.log / uvicorn.err.log)
# Frontend -> http://localhost:3000  (Next.js,  logs: next.log / next.err.log)
# Stop: close the hidden processes via  .\dev.ps1 -Stop   (or Task Manager)

param([switch]$Stop)

$root = $PSScriptRoot

if ($Stop) {
    foreach ($port in 8000, 3000) {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($c) {
            $c | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            }
            Write-Host "stopped port $port"
        }
    }
    return
}

# ---- backend ----
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$c = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if (-not $c) {
    Start-Process -FilePath $py `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000" `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput "$root\uvicorn.log" `
        -RedirectStandardError "$root\uvicorn.err.log"
    Write-Host "backend starting on http://127.0.0.1:8000 ..."
} else {
    Write-Host "backend already running on port 8000"
}

# ---- frontend ----
$env:BACKEND_URL = "http://127.0.0.1:8000"
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { $npm = "npm" }
$c = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
if (-not $c) {
    Start-Process -FilePath $npm `
        -ArgumentList "run", "dev" `
        -WorkingDirectory "$root\frontend" -WindowStyle Hidden `
        -RedirectStandardOutput "$root\next.log" `
        -RedirectStandardError "$root\next.err.log"
    Write-Host "frontend starting on http://localhost:3000 ..."
} else {
    Write-Host "frontend already running on port 3000"
}

# ---- wait until both answer ----
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    try {
        $api = Invoke-RestMethod "http://127.0.0.1:8000/health" -TimeoutSec 2
        $upApi = [bool]$api.ok
    } catch { $upApi = $false }
    try {
        Invoke-WebRequest "http://127.0.0.1:3000/" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $upUi = $true
    } catch { $upUi = $false }
    if ($upApi -and $upUi) { break }
}

if ($upApi -and $upUi) {
    Write-Host ""
    Write-Host "  both up  ->  open http://localhost:3000" -ForegroundColor Green
    Write-Host "  stop everything with:  .\dev.ps1 -Stop" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  api=$upApi ui=$upUi - check uvicorn.err.log / next.err.log" -ForegroundColor Yellow
}