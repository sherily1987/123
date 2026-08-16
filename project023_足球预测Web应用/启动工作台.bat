@echo off
cd /d "%~dp0"
if exist "02_scripts\start.bat" (
  cd /d "02_scripts"
  call start.bat
  goto :eof
)
for /d %%D in (02_*) do (
  if exist "%%D\start.bat" (
    cd /d "%%D"
    call start.bat
    goto :eof
  )
)
echo Cannot find start.bat
echo cwd=%CD%
pause
exit /b 1
