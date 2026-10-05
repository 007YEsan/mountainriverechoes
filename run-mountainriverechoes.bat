@echo off
rem ============================================================
rem  mountainriverechoes launcher (Windows)
rem  App dir : D:\musicdl   Port : 8766   Log : webui\server.log
rem
rem  Double-click behaviour:
rem    - service already running -> just open the browser
rem    - service not running     -> start it, wait, then open browser
rem
rem  KEEP THIS FILE CRLF-ENCODED AND ASCII-ONLY.
rem  A .bat that uses LF-only line endings AND contains non-ASCII text
rem  cannot be parsed by cmd.exe: the console flashes and closes with
rem  an error like "was unexpected at this time".
rem
rem  curl on this PC is a Git Bash shim that always returns 0,
rem  so the port is probed with netstat instead.
rem ============================================================
title mountainriverechoes - 8766
setlocal
set "APP_DIR=%~dp0"
set "PORT=8766"
set "URL=http://127.0.0.1:8766"
set "PYW=%APP_DIR%venv\Scripts\pythonw.exe"
set "LOG=%APP_DIR%webui\server.log"

rem --- proxy hardening ---
rem 1) clear proxy vars an AI session may inject: they route fetches through
rem    a filtering proxy that blocks media CDNs -> playback 403.
rem 2) NO_PROXY=* also makes the service ignore the Windows SYSTEM proxy, so
rem    playback survives Clash being closed (or force-killed while its
rem    system-proxy switch stayed on). All music sources are domestic and
rem    are reached directly - playback never needs a proxy.
set "HTTP_PROXY="
set "HTTPS_PROXY="
set "http_proxy="
set "https_proxy="
set "ALL_PROXY="
set "all_proxy="
set "NO_PROXY=*"
set "no_proxy=*"

call :portup
if not errorlevel 1 goto already

cd /d "%APP_DIR%"
if not exist "%PYW%" goto novenv
echo Starting mountainriverechoes on port %PORT% ...
start "" /d "%APP_DIR%" "%PYW%" webui\mountainriverechoes.py >> "%LOG%" 2>&1

set /a _n=0
:wait
call :portup
if not errorlevel 1 goto openurl
set /a _n+=1
if %_n% geq 30 goto openurl
ping -n 2 127.0.0.1 >nul
goto wait

:already
echo Already listening on port %PORT%.

:openurl
echo Opening %URL%
start "" "%URL%"
exit /b 0

:novenv
echo [ERROR] venv not found at %PYW%
echo Create the virtualenv first, then run this again.
pause
exit /b 1

:portup
netstat -ano | findstr /c:":8766 " | findstr /c:"LISTENING" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0
