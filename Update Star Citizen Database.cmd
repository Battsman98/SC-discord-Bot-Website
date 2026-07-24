@echo off
title Update Star Citizen Database
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update-and-publish-game-data.ps1"
set "UPDATER_EXIT=%ERRORLEVEL%"
echo.
if not "%UPDATER_EXIT%"=="0" echo The update did not finish. Review the message above.
pause
exit /b %UPDATER_EXIT%
