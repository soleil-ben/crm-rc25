@echo off
rem HTTP smoke check against the running UAT servers (run while START_UAT.bat is running).
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uat\uat.ps1" smoke
pause
