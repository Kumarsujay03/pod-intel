@echo off
cd /d "%~dp0"

:: Ensure virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo   Creating virtual environment (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo   [FAIL] Could not create virtual environment.
        pause
        exit /b 1
    )
    echo   [OK] Virtual environment created
)

:: Activate venv and launch PowerShell control panel
call .venv\Scripts\activate.bat
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0pipeline.ps1"
