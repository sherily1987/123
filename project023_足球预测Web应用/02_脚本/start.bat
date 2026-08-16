@echo off
cd /d "%~dp0"
title Football Workbench
set "LOG=%~dp0launch_error.txt"

set "PY=C:\Users\Administrator\AppData\Local\Temp\hm-train-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Python with FastAPI not found.>"%LOG%"
  echo Python with FastAPI not found.
  echo Need hm-train-venv or hermes-agent venv.
  pause
  exit /b 1
)

if not exist "%~dp0launch.py" (
  echo launch.py missing in %CD%>"%LOG%"
  echo launch.py missing.
  pause
  exit /b 1
)

echo Starting workbench
echo PY=%PY%
echo URL=http://127.0.0.1:8765
echo Close this window to stop.
echo.
"%PY%" -u launch.py 1>"%LOG%" 2>&1
set ERR=%ERRORLEVEL%
echo.
echo Stopped. exit=%ERR%
if not "%ERR%"=="0" (
  echo See launch_error.txt
  type "%LOG%"
)
pause
