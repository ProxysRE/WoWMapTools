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
  .venv\Scripts\python.exe -m wowmap.pack --profile dbc --part-mib 32 --out output\dbc-export
) else (
  .venv\Scripts\python.exe -m wowmap.pack --profile dbc --part-mib 32 --data "%~1" --out output\dbc-export
)
if errorlevel 1 (
  echo Export did not complete. See the error above.
  echo If nothing was found, send output\dbc-export\scan-diagnostic.json.
  echo Keep the output folder to resume with the same settings.
  pause
  exit /b 1
)
echo Upload the contents to a SEPARATE Drive folder: WoW DBC.
echo Do not replace the existing graphics or icon catalogs.
start "" "output\dbc-export\upload"
pause
