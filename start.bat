@echo off
title AniDub Studio v4.0
color 0A

echo.
echo  ==========================================
echo   AniDub Studio v4.0 — Starting...
echo  ==========================================
echo.

cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Install from https://python.org
    pause
    exit /b 1
)

REM Run system check
echo  Running system check...
python backend\check.py
if errorlevel 1 (
    echo.
    echo  [ERROR] System check failed. Fix the issues above.
    echo  Install requirements: pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo.
echo  ==========================================
echo   Backend starting on http://localhost:5050
echo   Open frontend\index.html in your browser
echo  ==========================================
echo.

REM Try to open browser automatically
start "" "frontend\index.html"

python backend\app.py

pause