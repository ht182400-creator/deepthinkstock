@echo off
REM ============================================================
REM  Weekly quant strategy - Friday routine batch
REM  Generates buy-list and compares with last week, then
REM  rebuilds the HTML dashboard.
REM  NOTE: this script only runs analysis. It cannot download
REM  market data - do that in the TDX client first.
REM ============================================================

SETLOCAL
REM ---------- Paths: edit these if you move machines ----------
SET "PROJECT_DIR=E:\AI_Studio\deepthinkstock"
SET "PYTHON=C:\Users\ht182\.workbuddy\binaries\python\versions\3.13.12\python.exe"

REM ---------- Toggles: 1=on, 0=off ----------
SET "REFRESH_FUNDAMENTALS=0"
SET "REFRESH_BACKTEST=1"

REM ---------- Step 0: pre-check, data must be updated ----------
echo ============================================================
echo   Weekly Quant Strategy - Friday Routine  (start: %date% %time%)
echo ============================================================
echo   IMPORTANT: Before running, open the TDX client and let it
echo   download Shanghai / Shenzhen / BSE daily data.
echo   Stale data means the buy-list uses OLD signals.
echo.
pause

REM ---------- Step 1: check python and project dir ----------
if not exist "%PYTHON%" (
    echo ERROR: Python not found: %PYTHON%
    echo Fix the PYTHON path at the top of this script.
    pause
    exit /b 1
)
cd /d "%PROJECT_DIR%"
if errorlevel 1 (
    echo ERROR: Project dir not found: %PROJECT_DIR%
    pause
    exit /b 1
)

REM ---------- Step 2: optional fundamentals refresh ----------
if "%REFRESH_FUNDAMENTALS%"=="1" (
    echo [1of4] Refreshing A-share fundamentals: fetch_fund_broad
    "%PYTHON%" fetch_fund_broad.py
    echo [1of4] Refreshing BSE fundamentals: fetch_fund_bj
    "%PYTHON%" fetch_fund_bj.py
) else (
    echo [1of4] Skipping fundamentals refresh - run quarterly only
)

REM ---------- Step 3: build buy-list and weekly diff ----------
echo [2of4] Building buy-list and weekly diff: live_compare 50000 4
"%PYTHON%" live_compare.py 50000 4
if errorlevel 1 (
    echo WARNING: live_compare failed - check TDX data download
)

REM ---------- Step 4: optional backtest curve refresh ----------
if "%REFRESH_BACKTEST%"=="1" (
    echo [3of4] Refreshing backtest equity curve: dump_curves
    "%PYTHON%" dump_curves.py
) else (
    echo [3of4] Skipping backtest refresh
)

REM ---------- Step 5: rebuild dashboard ----------
echo [4of4] Building HTML dashboard: build_dashboard
"%PYTHON%" build_dashboard.py

echo ============================================================
echo   DONE (end: %date% %time%)
echo ============================================================

REM Open the latest dated dashboard (dashboard_YYYYMMDD.html)
set "DASH="
for %%F in ("%PROJECT_DIR%\dashboard_*.html") do set "DASH=%%~nxF"
if not defined DASH (
    if exist "%PROJECT_DIR%\dashboard.html" set "DASH=dashboard.html"
)
if defined DASH (
    echo   Dashboard: %PROJECT_DIR%\%DASH%
    start "" "%PROJECT_DIR%\%DASH%"
) else (
    echo   Dashboard not found - build_dashboard may have failed
)
echo Browser opened. Review the buy-list and drawdown before any
echo decision. This script is research only, not investment advice.
echo.
pause
ENDLOCAL
