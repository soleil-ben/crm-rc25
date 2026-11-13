@echo off
rem Solaris Express CRM - RC-UAT-25. Builds what is missing, seeds synthetic UAT data if
rem there is no UAT database yet, starts backend :8000 and frontend :5173, opens the browser.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uat\uat.ps1" start %*
if errorlevel 1 pause
