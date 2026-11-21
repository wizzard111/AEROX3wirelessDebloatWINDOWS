@echo off
rem Developer run: the built program if present, otherwise from source in .venv.
cd /d "%~dp0..\.."
if exist "build\dist\AeroxLite\AeroxLite.exe" (
    start "" "build\dist\AeroxLite\AeroxLite.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" src\aerox_lite.py
    exit /b
)
echo Run packaging\windows\build.bat first.
pause
