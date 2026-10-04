@echo off
rem ============================================================
rem  mountainriverechoes launcher (Windows)
rem  App dir : D:\musicdl
rem  Port    : 8766
rem  Log     : webui\server.log
rem  Double-click: if already running -> just open browser;
rem                if not running -> start in background, then open browser.
rem  Note: this PC's curl is a Git Bash shim that always returns 0,
rem        so we use netstat (not curl) to probe the port.
rem ============================================================
title mountainriverechoes - 8766
setlocal
set "APP_DIR=%~dp0"
set "PORT=8766"
set "URL=http://127.0.0.1:8766"
set "PYW=%APP_DIR%venv\Scripts\pythonw.exe"
set "LOG=%APP_DIR%webui\server.log"

netstat -ano | findstr /c:":8766 " | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 goto already

cd /d "%APP_DIR%"
if not exist "%PYW%" goto novenv
start "" /b "%PYW%" webui\mountainriverechoes.py >> "%LOG%" 2>&1
timeout /t 4 /nobreak >nul
goto openurl

:already
echo Already listening on port %PORT%, opening browser...
goto openurl

:novenv
echo [ERROR] venv not found at %PYW%
echo Create it first, then retry.
pause
exit /b 1

:openurl
start "" "%URL%"
exit /b 0
