@echo off
REM ============================================================
REM  MU VPMO Dashboard - Windows launcher
REM  Double-click this file to start the dashboard with live Jira.
REM ============================================================
setlocal
cd /d "%~dp0"
title MU VPMO Dashboard

REM --- non-sensitive defaults (edit if needed) ---
set "JIRA_BASE_URL=https://methodist.atlassian.net"
set "JIRA_EMAIL=jgreene@methodist.edu"
set "JIRA_PROJECT=ITPM"
set "PORT=8787"

REM --- check Node is installed ---
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo  [!] Node.js is not installed or not on your PATH.
  echo      Download the LTS installer from https://nodejs.org , run it,
  echo      then double-click this file again.
  echo.
  pause
  exit /b 1
)

REM --- load saved credentials if present, else prompt ---
if exist "jira-credentials.bat" (
  call "jira-credentials.bat"
)

if "%JIRA_TOKEN%"=="" (
  echo.
  echo  Enter your Atlassian API token.
  echo  Create one at: https://id.atlassian.com/manage-profile/security/api-tokens
  echo.
  set /p "JIRA_TOKEN=API token: "
  echo.
  set /p "SAVE=Save it so you don't have to paste it next time? (y/n): "
  if /i "%SAVE%"=="y" (
    >  "jira-credentials.bat" echo @echo off
    >> "jira-credentials.bat" echo set "JIRA_TOKEN=%JIRA_TOKEN%"
    echo  Saved to jira-credentials.bat ^(this file is git-ignored^).
  )
)

if "%JIRA_TOKEN%"=="" (
  echo  [!] No token entered - the "Load from Jira" button will not work,
  echo      but the dashboard will still open with the built-in data.
)

echo.
echo  Starting dashboard at http://localhost:%PORT%
echo  ^(Close this window or press Ctrl+C to stop.^)
echo.

REM --- open the browser shortly after the server boots ---
start "" /b cmd /c "timeout /t 2 >nul & start "" http://localhost:%PORT%"

REM --- run the server (blocks until you close it) ---
node server.js

echo.
echo  Server stopped.
pause
endlocal
