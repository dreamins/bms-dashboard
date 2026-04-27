@echo off
cd /d "%~dp0"

set VENV_PYTHON=%~dp0..\.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found.
    echo [INFO]  Run run.bat from the project root to set up the environment.
    pause
    exit /b 1
)

echo [INFO] Launching Lithium Core Dashboard...
echo [INFO] Open http://localhost:8080 in your browser.
echo.
"%VENV_PYTHON%" dashboard.py
pause
