@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if "%~1"=="" (
  .venv\Scripts\python.exe -m wowmap.run_scene
) else (
  .venv\Scripts\python.exe -m wowmap.run_scene "%~1"
)
if errorlevel 1 (
  pause
  exit /b 1
)
pause
