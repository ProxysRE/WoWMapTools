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
echo Ready. Use render_scene.bat for existing resource ZIPs.
echo To export client resources, use pack_for_drive.bat, pack_icons.bat or pack_dbc.bat.
pause
exit /b 0
:fail
pause
exit /b 1
