@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required. Install Python with the py launcher.
  pause
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo Ready. Drag PNG.zip onto import_png.bat, then run render_example.bat.
pause
exit /b 0
:fail
pause
exit /b 1
