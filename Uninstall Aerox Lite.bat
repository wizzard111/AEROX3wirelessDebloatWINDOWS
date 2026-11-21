@echo off
rem Removes Aerox Lite and asks whether to also remove the settings and this folder.
setlocal
title Aerox Lite uninstaller
rem Prefer the uninstaller that came with this folder (same version as its installer).
set "PS1=%~dp0app\uninstall.ps1"
if not exist "%PS1%" set "PS1=%~dp0packaging\windows\uninstall.ps1"
if not exist "%PS1%" set "PS1=%LOCALAPPDATA%\Programs\AeroxLite\uninstall.ps1"
rem The copy in %LOCALAPPDATA% is deleted while it runs, so run a temporary copy of it.
copy /y "%PS1%" "%TEMP%\aerox-lite-uninstall.ps1" >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\aerox-lite-uninstall.ps1" -PackageDir "%~dp0." %*
set RC=%ERRORLEVEL%
del "%TEMP%\aerox-lite-uninstall.ps1" >nul 2>&1
echo.
pause
if "%RC%"=="10" (
    rem Delete this folder, including this file: leave it first, then end the script while removing it.
    cd /d "%TEMP%"
    (goto) 2>nul & rmdir /s /q "%~dp0"
)
