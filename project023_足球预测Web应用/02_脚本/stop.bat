@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\Administrator\AppData\Local\Temp\hm-train-venv\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo 找不到可运行 FastAPI 的 Python；请关闭原启动窗口。
  pause
  exit /b 1
)
echo 正在核验工作台 PID、动态端口与构建身份...
"%PY%" -u launch.py --stop
if errorlevel 1 (
  echo 未停止任何进程；身份无法完整核验，请关闭原启动窗口。
  pause
  exit /b 1
)
pause
