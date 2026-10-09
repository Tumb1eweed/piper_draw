@echo off
setlocal
cd /d "%~dp0"
set "PIPER_PYTHON=D:\Miniconda3\envs\piper\python.exe"
if not exist "%PIPER_PYTHON%" (
    echo Missing Windows piper conda environment: %PIPER_PYTHON%
    pause
    exit /b 1
)
start "Piper Draw UI" cmd /k ""%PIPER_PYTHON%" piper_draw_ui.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
