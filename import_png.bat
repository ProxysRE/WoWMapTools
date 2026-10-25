@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if "%~1"=="" (
  echo Drag the wow.export PNG ZIP onto this file.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m wowmap import-png "%~1" --assets assets
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m wowmap gallery --assets assets --out output\catalog.jpg
if errorlevel 1 goto :fail
echo Import complete. Open output\catalog.jpg or run render_example.bat.
pause
exit /b 0
:fail
pause
exit /b 1
