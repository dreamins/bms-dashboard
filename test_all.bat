@echo off
setlocal
cd /d "%~dp0"

echo ########################################
echo # Lithium Core -- Test Suite           #
echo ########################################

set VENV_PYTHON=%~dp0.venv\Scripts\python.exe
set APP_DIR=%~dp0dashboard_app

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found. Run run.bat first to set it up.
    pause
    exit /b 1
)

echo [INFO] Running test suite...
echo.
cd /d "%APP_DIR%"
"%VENV_PYTHON%" -m unittest discover -s tests -v
set RESULT=%errorlevel%
cd /d "%~dp0"

echo.
if %RESULT% equ 0 (
    echo ##################################
    echo # ALL TESTS PASSED               #
    echo ##################################
) else (
    echo ##################################
    echo # TESTS FAILED                   #
    echo ##################################
)
pause
exit /b %RESULT%
