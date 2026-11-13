@echo off
rem Solaris Express CRM - RC-UAT-25. Stops the servers, rebuilds the UAT database from
rem scratch (synthetic data only, captured emails cleared), then starts everything again.
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0uat\uat.ps1" reset %*
if errorlevel 1 pause
