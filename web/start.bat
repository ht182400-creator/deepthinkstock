REM ============================================================
REM  Quantitative Strategy - Web Dashboard Launcher
REM  Double-click to start, then open http://localhost:8899
REM ============================================================
@echo off
SETLOCAL EnableDelayedExpansion

echo ============================================================
echo   Quantitative Strategy - Web Dashboard
echo ============================================================

REM ---------- Config ----------
set "PORT=8899"
set "WEB_DIR=%~dp0"
set "MANAGED_PYTHON=C:\Users\ht182\.workbuddy\binaries\python\versions\3.13.12\python.exe"

REM Fallback to system Python if managed not found
if not exist "%MANAGED_PYTHON%" (
    for %%p in (python3.exe python.exe py.exe) do (
        for /f "delims=" %%x in ('where %%p 2^>nul') do (
            if not defined FOUND set "MANAGED_PYTHON=%%x" & set "FOUND=1"
        )
    )
    if not defined FOUND (
        echo [ERROR] Python not found. Install Python 3.9+ first.
        pause
        exit /b 1
    )
)
echo    Python: %MANAGED_PYTHON%

REM ---------- Kill existing process on the port ----------
echo.
echo [0/3] Killing existing process on port %PORT% ...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr /c:":%PORT% " ^| findstr /i "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1 && echo    Killed PID %%p
)
ping -n 2 127.0.0.1 >nul
echo    Port %PORT% clear.

REM ---------- Install dependencies ----------
echo.
echo [1/3] Checking dependencies ...
"%MANAGED_PYTHON%" -c "import fastapi,uvicorn" 2>nul
if errorlevel 1 (
    echo    Installing FastAPI + uvicorn ...
    "%MANAGED_PYTHON%" -m pip install fastapi uvicorn -q
    if errorlevel 1 (
        echo    [WARN] pip install failed. Trying without -q ...
        "%MANAGED_PYTHON%" -m pip install fastapi uvicorn
    )
)

REM ---------- Start ----------
echo.
echo [START] Server: http://localhost:%PORT%
echo         API docs: http://localhost:%PORT%/docs
echo         Dashboard: http://localhost:%PORT%
echo         Press Ctrl+C to stop
echo ============================================================
echo.

cd /d "%WEB_DIR%"
"%MANAGED_PYTHON%" server.py --port %PORT%

echo.
echo    Server stopped.
pause
ENDLOCAL
