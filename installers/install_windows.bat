@echo off
REM Double-click launcher for the Windows installer. Runs the PowerShell
REM installer with an execution policy that allows it to run this once.
setlocal
echo Installing the Equity Portfolio Withdrawal Simulator...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
set RC=%ERRORLEVEL%
echo.
if %RC% NEQ 0 (
  echo Installation reported an error ^(exit code %RC%^).
) else (
  echo Installation finished.
)
echo.
pause
endlocal
