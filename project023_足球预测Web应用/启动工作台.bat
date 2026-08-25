@echo off
echo [提示] 旧入口已废弃，正在转到 B3 正式工作台。
call "%~dp0启动B3工作台.bat"
exit /b %ERRORLEVEL%
