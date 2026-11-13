@echo off
rem Stops the backend and frontend that START_UAT.bat / RESET_UAT.bat started.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uat\uat.ps1" stop
