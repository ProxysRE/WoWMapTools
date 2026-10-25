@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m wowmap render examples\ashenvale-camp.json --out output\ashenvale
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "output\ashenvale\preview.jpg"
pause
