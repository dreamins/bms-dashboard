@echo off
setlocal
cd /d "%~dp0"

echo ########################################
echo # Lithium Core -- Test Suite           #
echo ########################################

set VENV_PYTHON=%~dp0python.exe
set APP_DIR=%~dp0dashboard_app

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python not found in venv
    pause
    exit /b 1
)

echo [INFO] Running test suite...
echo.
cd /d "%APP_DIR%"
call "%VENV_PYTHON%" -m unittest discover -s tests -v
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
