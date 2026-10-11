@echo off
setlocal
cd /d "%~dp0"
rem Optional first argument or environment variable supports another machine.
if not "%~1"=="" set "PIPER_PYTHON=%~1"
if not defined PIPER_PYTHON set "PIPER_PYTHON=D:\Miniconda3\envs\piper\python.exe"
if not exist "%PIPER_PYTHON%" (
    echo Missing Windows piper conda environment: %PIPER_PYTHON%
    echo Run setup_windows.ps1 first, then pass the full piper python.exe path as argument.
    pause
    exit /b 1
)
start "Piper Draw UI" cmd /k ""%PIPER_PYTHON%" piper_draw_ui.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
