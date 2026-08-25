@echo off
setlocal
cd /d "%~dp002_脚本"
call start.bat
exit /b %ERRORLEVEL%
