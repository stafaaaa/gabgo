@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (py -3 -m venv .venv 2>nul || python -m venv .venv)
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
".venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name Tankbelege tankbelege_app.py
if errorlevel 1 (pause & exit /b 1)
copy /y dist\Tankbelege.exe Tankbelege.exe >nul
echo Fertig: %~dp0Tankbelege.exe
pause
