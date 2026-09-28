@echo off
setlocal

rem Double-click launcher for mount_piper_can.ps1.
rem The PowerShell script finds candleLight, attaches it to Ubuntu WSL,
rem then prompts for the Ubuntu sudo password to configure can0 at 1 Mbps.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0mount_piper_can.ps1"
set "exit_code=%ERRORLEVEL%"

if not "%exit_code%"=="0" (
    echo.
    echo Mount failed with exit code %exit_code%.
    echo Check that the Windows upper-controller is closed and the USB-CAN is connected.
)

echo.
pause
exit /b %exit_code%
