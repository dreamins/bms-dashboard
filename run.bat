@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ########################################
echo # Lithium Core Dashboard               #
echo ########################################

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.9+ from python.org
    pause
    exit /b 1
)

:: Create venv if missing
if not exist ".venv" (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

:: Install / sync dependencies
echo [INFO] Checking dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Launch (run from dashboard_app so relative imports resolve)
echo [INFO] Launching Lithium Core Dashboard...
echo [INFO] Open http://localhost:8080 in your browser.
echo.
cd /d "%~dp0dashboard_app"
"%~dp0.venv\Scripts\python.exe" dashboard.py

pause
