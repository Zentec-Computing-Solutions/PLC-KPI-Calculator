@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."

if not defined FFMPEG_PATH set "FFMPEG_PATH=C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"

if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

:restart
echo [%date% %time%] Starting RTSP publisher
"%PYTHON%" "%PROJECT_DIR%\common\rtsp_stream.py"
echo [%date% %time%] Publisher stopped with exit code %errorlevel%. Restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto restart
