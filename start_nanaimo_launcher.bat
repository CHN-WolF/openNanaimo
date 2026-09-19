@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0gui_launcher\nanaimo_launcher.ps1" %*
exit /b %errorlevel%
