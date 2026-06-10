@echo off
REM ============================================================
REM  MU VPMO Dashboard - Windows launcher (double-click me)
REM  Runs start.ps1, which stores your Jira token DPAPI-encrypted.
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
