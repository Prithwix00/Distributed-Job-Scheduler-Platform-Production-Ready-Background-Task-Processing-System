@echo off
setlocal
title Distributed Job Scheduler - launcher

rem ============================================================
rem  One-command local run (no Docker). Double-click this file,
rem  or run it from PowerShell / cmd:  .\run-local.bat
rem
rem  It does first-run setup automatically, then opens the four
rem  services in separate windows. Close those windows to stop.
rem  Needs Python 3.11+ and Node.js installed.
rem ============================================================

cd /d "%~dp0"
set "ROOT=%cd%"
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"

where python >nul 2>nul || (echo [ERROR] Python not found. Install Python 3.11+ and re-run. & pause & exit /b 1)
where node   >nul 2>nul || (echo [ERROR] Node.js not found. Install Node.js and re-run. & pause & exit /b 1)

rem ---- backend first-run setup ----
if not exist "%PY%" (
  echo [setup] Creating Python virtual environment ...
  pushd "%BACKEND%"
  python -m venv .venv
  popd
)

rem Ensure dependencies are actually installed. This also heals a half-made
rem venv left by an earlier attempt (folder exists but packages are missing).
"%PY%" -c "import uvicorn, httpx, pydantic_settings, fastapi" 1>nul 2>nul
if errorlevel 1 (
  echo [setup] Installing backend dependencies ^(first run only, please wait^) ...
  "%PY%" -m pip install --upgrade pip >nul
  "%PY%" -m pip install -r "%BACKEND%\requirements.txt"
)

rem ---- frontend first-run setup ----
if not exist "%FRONTEND%\node_modules" (
  echo [setup] Installing frontend dependencies ^(first run only, please wait^) ...
  pushd "%FRONTEND%"
  call npm install
  popd
)

echo.
echo [start] Launching services in separate windows ...

start "scheduler-API"       cmd /k "cd /d "%BACKEND%" && set DATABASE_URL=sqlite:///./dev.db&& "%PY%" -m uvicorn app.main:app --port 8000"
start "scheduler-SCHEDULER"  cmd /k "cd /d "%BACKEND%" && set DATABASE_URL=sqlite:///./dev.db&& "%PY%" -m app.runtime.scheduler"
start "scheduler-WORKER"     cmd /k "cd /d "%BACKEND%" && "%PY%" -m app.runtime.worker --base-url http://localhost:8000 --concurrency 4"
start "scheduler-FRONTEND"   cmd /k "cd /d "%FRONTEND%" && npm run dev"

echo.
echo ============================================================
echo   All four services are starting in their own windows.
echo   The worker waits for the API automatically.
echo.
echo   Dashboard : http://localhost:5173
echo   API docs  : http://localhost:8000/docs
echo.
echo   To stop everything: close the four service windows.
echo ============================================================
echo.
echo (Optional) After the dashboard loads, seed demo data with:
echo   cd backend ^&^& .venv\Scripts\python.exe -m app.runtime.seed
echo.
pause
