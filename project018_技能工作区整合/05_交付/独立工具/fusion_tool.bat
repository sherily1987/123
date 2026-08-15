@echo off
rem ============================================================
rem  Football Quant Fusion - standalone launcher
rem  Usage: double-click this file (menu text is Chinese, but
rem  this launcher itself must stay ASCII-only for cmd.exe).
rem ============================================================
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH.
    echo Trying py launcher...
    where py >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] neither python nor py launcher found.
        echo Install Python 3.x and add it to PATH, then retry.
        pause
        exit /b 1
    )
    py -3 "%~dp0fusion_menu.py"
) else (
    python "%~dp0fusion_menu.py"
)
echo.
pause
