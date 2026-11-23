@echo off
rem Payment Manager - start the local server (minimized) and open the browser.
setlocal
set "PY=%LOCALAPPDATA%\PaymentManager\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Payment Manager is not installed yet. Please run install.bat first.
  pause
  exit /b 1
)
cd /d "%~dp0"
start "Payment Manager" /min "%PY%" -m app
