@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
start "MediaMTX" /min cmd /c call "%SCRIPT_DIR%run_mediamtx.bat"
timeout /t 2 /nobreak >nul
start "Shift RTSP Publisher" /min cmd /c call "%SCRIPT_DIR%run_publisher.bat"

echo Shift monitor services started.
