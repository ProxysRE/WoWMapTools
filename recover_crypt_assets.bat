@echo off
cd /d "%~dp0"
py -3 -m wowmap.recover_assets
echo.
echo Send output\missing-crypt-assets\recovery-report.json and recovered-crypt-assets.zip if created.
pause
