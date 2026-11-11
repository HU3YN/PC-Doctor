@echo off
rem PC Doctor collector launcher - double-click this file.
rem
rem It asks Windows for administrator rights (needed to read disk health
rem counters and frame times) and then runs Collect-PCDoctor.ps1.
rem The collector is read-only: it changes nothing on this PC.
rem
rem Anything you add after the file name is passed on, for example:
rem   PCDoctor.cmd -Mode Capture -Seconds 300
setlocal

rem "fltmc" only works for an administrator, so it is a quick way to check.
fltmc >nul 2>&1
if %errorlevel%==0 goto run
if "%PCDOCTOR_NO_ELEVATE%"=="1" goto run

echo PC Doctor needs administrator rights to read disk health and frame times.
echo Windows will ask you to allow it.
powershell -NoProfile -Command "try { $a = '%*'; if ($a.Trim()) { Start-Process -FilePath '%~f0' -ArgumentList $a -Verb RunAs } else { Start-Process -FilePath '%~f0' -Verb RunAs }; exit 0 } catch { exit 1 }"
if %errorlevel%==0 exit /b 0
echo.
echo Continuing without administrator rights - some checks will be skipped.

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Collect-PCDoctor.ps1" %*
echo.
pause
