@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 goto launch_with_py

where python >nul 2>nul
if not errorlevel 1 goto launch_with_python

echo Python 3 was not found.
echo Install Python 3 or add it to PATH, then run this file again.
pause
exit /b 1

:launch_with_py
py -3 "%~dp0builder_app.py" --self-test
if errorlevel 1 goto self_test_failed
where pyw >nul 2>nul
if errorlevel 1 (
    py -3 "%~dp0builder_app.py"
    exit /b %errorlevel%
)
start "" pyw -3 "%~dp0builder_app.py"
exit /b 0

:launch_with_python
python "%~dp0builder_app.py" --self-test
if errorlevel 1 goto self_test_failed
where pythonw >nul 2>nul
if errorlevel 1 (
    python "%~dp0builder_app.py"
    exit /b %errorlevel%
)
start "" pythonw "%~dp0builder_app.py"
exit /b 0

:self_test_failed
echo.
echo Builder self-test failed. The application was not started.
pause
exit /b 1
