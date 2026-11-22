@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto noenv
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b
:noenv
echo .venv\Scripts\pythonw.exe not found. See README.
pause
