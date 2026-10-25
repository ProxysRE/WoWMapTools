@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if not exist tools\StormLib.dll (
  echo Use the Windows bundle from GitHub Actions: Windows packer.
  echo The source-only ZIP does not include StormLib.dll.
  pause
  exit /b 1
)
if "%~1"=="" (
  .venv\Scripts\python.exe -m wowmap.pack --out output\drive-export
) else (
  .venv\Scripts\python.exe -m wowmap.pack --data "%~1" --out output\drive-export
)
if errorlevel 1 (
  echo Export did not complete. Keep the output folder to resume.
  pause
  exit /b 1
)
echo See output\drive-export\upload\summary.json before uploading.
start "" "output\drive-export\upload"
pause
