@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

:restart
echo [%date% %time%] Starting MediaMTX
"%SCRIPT_DIR%mediamtx.exe" "%PROJECT_DIR%\config\mediamtx.yml"
echo [%date% %time%] MediaMTX stopped with exit code %errorlevel%. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto restart
