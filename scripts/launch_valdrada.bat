@echo off
:: ============================================================================
:: GarudaOS — Launch Valdrada (Boundless NYC) on Unreal Engine 5.8.4
:: ============================================================================
:: Launches the Valdrada NYC digital twin simulation environment and leaves it
:: running so GarudaOS can connect on TCP port 2000.
::
:: Prerequisites:
::   * Valdrada UE 5.8.4 environment downloaded from
::     https://github.com/mkturkcan/boundless-nyc/releases
::   * Extracted to a folder (default: D:\Valdrada\UE_5.8.4)
:: ============================================================================

setlocal enabledelayedexpansion

:: ---- Configure this to your Valdrada install folder -----------------------
:: Extracted from Valdrada-0.6.2-win64.zip (plus tiles + terrain zips)
set "VALDRADA_DIR=D:\Valdrada\server"
:: ---------------------------------------------------------------------------

if not exist "%VALDRADA_DIR%" (
    echo [ERROR] Valdrada directory not found: %VALDRADA_DIR%
    echo       Edit scripts/launch_valdrada.bat and set VALDRADA_DIR.
    echo       Download from: https://github.com/mkturkcan/boundless-nyc/releases
    exit /b 1
)

echo [1/2] Checking for a running Valdrada instance (port 2000)...
netstat -an 2>nul | findstr ":2000 " >nul
if %errorlevel% equ 0 (
    echo [WARN] Port 2000 is already in use — a Valdrada instance may be running.
    echo       Only one instance can bind port 2000. Aborting to avoid a port conflict.
    exit /b 1
)

echo [2/2] Launching Valdrada (Unreal Engine 5.8.4)...
cd /d "%VALDRADA_DIR%"

:: The Valdrada server binary name depends on your release build. Adjust
:: VALDARADA_BIN below to match (e.g. ValdradaServer.exe, ValdradaUE.exe, etc.).
:: Run headless with -nullrhi by default; remove -nullrhi for a visible viewport.
set "VALDARADA_BIN=ValradaServer.exe"
start "" "%VALDARADA_BIN%" -nullrhi -Port=2000

echo.
echo Valdrada launched. Wait for the server to bind port 2000, then run:
echo   venv\Scripts\python.exe scripts\valdrada_follow.py --duration 30 --conf 0.15
echo.
echo Press Ctrl+C to stop this launcher (the server keeps running in its own window).
