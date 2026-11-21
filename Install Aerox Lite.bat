@echo off
rem Aerox Lite installer: double-click. A window shows every step; no administrator rights needed.
setlocal
title Aerox Lite installer
set "PS1=%~dp0app\install.ps1"
if not exist "%PS1%" set "PS1=%~dp0packaging\windows\install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
echo.
pause
