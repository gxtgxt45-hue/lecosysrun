@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Install Python 3.12 64-bit from python.org. Enable Add Python to PATH.
        pause
        exit /b 1
    )
    python run_local.py
) else (
    py -3 run_local.py
)
pause
