@echo off
setlocal
cd /d "%~dp0"
start "Piper Draw UI" cmd /k "py -3 piper_draw_ui.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765"
