@echo off
chcp 65001 >nul
cd /d "F:\HM足球比赛预测\project023_足球预测Web应用\02_脚本"
echo 启动足球预测工作台...
echo 浏览器将自动打开 http://127.0.0.1:8765
start "" http://127.0.0.1:8765
python app.py
pause
