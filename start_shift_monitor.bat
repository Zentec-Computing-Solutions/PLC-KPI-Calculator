@echo off
REM Shift Monitor Startup Script
REM This script starts MediaMTX and the Python RTSP stream publisher
REM If either service fails or crashes, it sends an error notification to n8n

setlocal enabledelayedexpansion

set "WORKSPACE_DIR=c:\Users\Admin\Desktop\KPI Calculator"
set "N8N_WEBHOOK=https://n8n.zentec.co.nz/webhook/inang-error"
set "LOG_FILE=%WORKSPACE_DIR%\shift_monitor.log"
set "TIMESTAMP_FORMAT=%%date:~-4%%%%date:~-10,2%%%%date:~-7,2%% %%time:~0,2%%%%time:~3,2%%%%time:~6,2%%"

cd /d "%WORKSPACE_DIR%" || (
    echo ERROR: Failed to change to workspace directory
    goto handle_error
)

echo. >> "%LOG_FILE%"
echo [%TIMESTAMP_FORMAT%] Starting Shift Monitor >> "%LOG_FILE%"

REM Start MediaMTX
echo [%TIMESTAMP_FORMAT%] Starting MediaMTX... >> "%LOG_FILE%"
start "MediaMTX" cmd /k "mediamtx mediamtx.yml"

if errorlevel 1 (
    echo [%TIMESTAMP_FORMAT%] ERROR: Failed to start MediaMTX >> "%LOG_FILE%"
    set "ERROR_MSG=Failed to start MediaMTX process"
    goto handle_error
)

REM Wait for MediaMTX to initialize
timeout /t 3 /nobreak

REM Start Python RTSP Stream
echo [%TIMESTAMP_FORMAT%] Starting Python RTSP Stream... >> "%LOG_FILE%"
start "RTSP Stream Publisher" cmd /k "python rtsp_stream.py"

if errorlevel 1 (
    echo [%TIMESTAMP_FORMAT%] ERROR: Failed to start Python script >> "%LOG_FILE%"
    set "ERROR_MSG=Failed to start Python RTSP stream publisher"
    goto handle_error
)

echo [%TIMESTAMP_FORMAT%] Both services started successfully >> "%LOG_FILE%"
exit /b 0

:handle_error
echo [!TIMESTAMP_FORMAT!] ERROR: %ERROR_MSG% >> "%LOG_FILE%"

REM Send error notification to n8n
powershell -NoProfile -Command ^
  "try { ^
    $body = @{ ^
      service = 'shift-monitor'; ^
      status = 'startup_failed'; ^
      error = '%ERROR_MSG%'; ^
      timestamp = (Get-Date -Format 'o'); ^
      hostname = [System.Net.Dns]::GetHostName(); ^
      workspace = '%WORKSPACE_DIR%' ^
    } ^| ConvertTo-Json; ^
    $response = Invoke-WebRequest -Uri '%N8N_WEBHOOK%' -Method POST -Body $body -ContentType 'application/json' -TimeoutSec 5; ^
    Write-Output 'Error notification sent to n8n'; ^
  } catch { ^
    Write-Output \"Failed to send error to n8n: $_\"; ^
  }"

exit /b 1

:crash_monitor
REM This section monitors running processes and sends alerts if they crash
:monitor_loop
tasklist | find /i "mediamtx" >nul
if errorlevel 1 (
    echo [%TIMESTAMP_FORMAT%] ALERT: MediaMTX process crashed >> "%LOG_FILE%"
    set "ERROR_MSG=MediaMTX process crashed unexpectedly"
    goto handle_error
)

tasklist | find /i "python" >nul
if errorlevel 1 (
    echo [%TIMESTAMP_FORMAT%] ALERT: Python RTSP stream process crashed >> "%LOG_FILE%"
    set "ERROR_MSG=Python RTSP stream publisher crashed unexpectedly"
    goto handle_error
)

timeout /t 10 /nobreak
goto monitor_loop
