# One-command local run (no Docker).
#
# Usage from PowerShell, inside the scheduler folder:
#     powershell -ExecutionPolicy Bypass -File .\run-local.ps1
#
# Does first-run setup automatically, then opens the four services in
# separate windows. The worker waits for the API on its own, so start
# order does not matter. Needs Python 3.11+ and Node.js.

$ErrorActionPreference = "Stop"
$root     = $PSScriptRoot
$backend  = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$py       = Join-Path $backend ".venv\Scripts\python.exe"

function Require-Command($cmd, $name) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "[ERROR] $name not found. Install it and re-run." -ForegroundColor Red
        exit 1
    }
}

Write-Host "== Distributed Job Scheduler: local launcher (SQLite, no Docker) ==" -ForegroundColor Cyan
Require-Command python "Python 3.11+"
Require-Command node   "Node.js"

# ---- backend first-run setup ----
if (-not (Test-Path $py)) {
    Write-Host "[setup] Creating venv..." -ForegroundColor Yellow
    Push-Location $backend
    python -m venv .venv
    Pop-Location
}

# Ensure deps are actually installed (heals a half-made venv from an earlier try).
& $py -c "import uvicorn, httpx, pydantic_settings, fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[setup] Installing backend deps (first run only, please wait)..." -ForegroundColor Yellow
    & $py -m pip install --upgrade pip | Out-Null
    & $py -m pip install -r (Join-Path $backend "requirements.txt")
}

# ---- frontend first-run setup ----
if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
    Write-Host "[setup] Installing frontend deps (first run only)..." -ForegroundColor Yellow
    Push-Location $frontend
    npm install
    Pop-Location
}

Write-Host "[start] Launching four services in separate windows..." -ForegroundColor Green

Start-Process powershell -ArgumentList @("-NoExit","-Command",
    "cd '$backend'; `$env:DATABASE_URL='sqlite:///./dev.db'; & '$py' -m uvicorn app.main:app --port 8000")

Start-Process powershell -ArgumentList @("-NoExit","-Command",
    "cd '$backend'; `$env:DATABASE_URL='sqlite:///./dev.db'; & '$py' -m app.runtime.scheduler")

Start-Process powershell -ArgumentList @("-NoExit","-Command",
    "cd '$backend'; & '$py' -m app.runtime.worker --base-url http://localhost:8000 --concurrency 4")

Start-Process powershell -ArgumentList @("-NoExit","-Command",
    "cd '$frontend'; npm run dev")

Write-Host ""
Write-Host "All four services are starting." -ForegroundColor Cyan
Write-Host "  Dashboard : http://localhost:5173" -ForegroundColor Cyan
Write-Host "  API docs  : http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "  Stop      : close the four service windows."
Write-Host ""
Write-Host "Optional demo data: cd backend; .venv\Scripts\python.exe -m app.runtime.seed"
