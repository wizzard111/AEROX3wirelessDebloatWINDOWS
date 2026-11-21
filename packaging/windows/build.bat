@echo off
rem Developer build: creates build\dist\AeroxLite.exe (see build.ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
set RC=%ERRORLEVEL%
pause
exit /b %RC%
