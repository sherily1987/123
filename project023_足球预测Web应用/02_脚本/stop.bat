@echo off
chcp 65001 >nul
echo 正在结束占用 8765 的工作台进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do taskkill /PID %%p /F >nul 2>&1
echo 已停止（若本来没开，可忽略）。
pause
