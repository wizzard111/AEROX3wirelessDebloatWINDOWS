@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.12+ for Windows with Tcl/Tk and add it to PATH.
    goto fail
)
python -m venv .venv
if errorlevel 1 goto fail
:install
".venv\Scripts\python.exe" -X utf8 -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -X utf8 -m unittest discover -s tests -v
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -X utf8 -m PyInstaller --clean --noconfirm AeroxLite.spec
if errorlevel 1 goto fail
if not exist "dist\AeroxLite.exe" goto fail
echo.
echo Built successfully: dist\AeroxLite.exe
pause
exit /b 0
:fail
echo.
echo Build failed. See the error above; a new EXE has not been confirmed.
pause
exit /b 1
