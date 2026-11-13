@echo off
rem Double-click to start PC Doctor on this computer (the master PC).
rem Add -Lan to let other PCs on your network use it:  Start-PCDoctor.cmd -Lan
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-PCDoctor.ps1" %*
if errorlevel 1 pause
