@echo off
cd /d "%~dp0"
if exist "dist\AeroxLite.exe" (
    start "" "dist\AeroxLite.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" aerox_lite.py
    exit /b
)
echo Run build.bat first.
pause
