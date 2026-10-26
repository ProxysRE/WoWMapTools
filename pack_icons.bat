@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if not exist tools\StormLib.dll (
  echo Use the Windows packer bundle from GitHub Actions.
  echo The source-only ZIP does not include StormLib.dll.
  pause
  exit /b 1
)
if "%~1"=="" (
  .venv\Scripts\python.exe -m wowmap.pack --profile icons --out output\icons-export
) else (
  .venv\Scripts\python.exe -m wowmap.pack --profile icons --data "%~1" --out output\icons-export
)
if errorlevel 1 (
  echo Export did not complete. See the error above.
  echo If no icons were found, send output\icons-export\scan-diagnostic.json.
  echo Keep this folder to resume with the same settings.
  pause
  exit /b 1
)
echo Upload the contents to a SEPARATE Drive folder: WoW Icons.
echo Do not replace the existing model and texture catalog.
start "" "output\icons-export\upload"
pause
