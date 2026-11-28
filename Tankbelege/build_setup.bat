@echo off
setlocal
cd /d "%~dp0"
rem Baut die App (PyInstaller, Ordner-Variante) und daraus mit Inno Setup Output\Tankbelege-Setup.exe.
rem Tesseract wird mitgeliefert, wenn es unter vendor\tesseract oder C:\Program Files\Tesseract-OCR liegt.

if not exist ".venv\Scripts\python.exe" (py -3 -m venv .venv 2>nul || python -m venv .venv)
if not exist ".venv\Scripts\python.exe" (echo Python 3 nicht gefunden. & goto fehler)
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fehler
".venv\Scripts\pyinstaller.exe" --noconfirm --onedir --windowed --add-data "Tanken_neu - Kopie.xlsx;." --icon assets\anna.ico --add-data "assets\anna.ico;assets" --add-data "assets\anna.png;assets" --name Tankbelege tankbelege_app.py
if errorlevel 1 goto fehler

if not exist "vendor\tesseract\tesseract.exe" if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" (
  echo Kopiere Tesseract nach vendor\tesseract ...
  robocopy "%ProgramFiles%\Tesseract-OCR" "vendor\tesseract" /E /NFL /NDL /NJH /NJS /XF unins*.* >nul
)
if not exist "vendor\tesseract\tesseract.exe" echo WARNUNG: Tesseract nicht gefunden - Setup enthaelt kein OCR.

set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
  if not defined ISCC if exist %%P set "ISCC=%%~P"
)
if not defined ISCC for /f "delims=" %%P in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%P"
if not defined ISCC (
  echo Inno Setup 6 nicht gefunden. Bitte von https://jrsoftware.org/isdl.php installieren.
  goto fehler
)
"%ISCC%" installer.iss
if errorlevel 1 goto fehler
echo Fertig: %~dp0Output\Tankbelege-Setup.exe
if not defined CI pause
exit /b 0

:fehler
if not defined CI pause
exit /b 1
