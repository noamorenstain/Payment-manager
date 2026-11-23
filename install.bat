@echo off
rem Payment Manager - one-time installation. Double-click to run.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" %*
echo.
pause
