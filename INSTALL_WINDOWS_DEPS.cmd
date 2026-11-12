@echo off
setlocal
cd /d "%~dp0"
title Install VlogCraft Studio Requirements
color 0B
echo.
echo   VLOGCRAFT STUDIO 3 - INSTALL FREE DEPENDENCIES
 echo   Requires Python 3.11 or newer and FFmpeg/FFprobe.
echo.
where winget >nul 2>&1
if errorlevel 1 (
 echo Windows Package Manager winget is not available.
 echo Install Python from https://www.python.org/downloads/
 echo and FFmpeg from https://ffmpeg.org/download.html
 pause
 exit /b 1
)
echo [1/2] Installing or updating Python...
winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements
echo.
echo [2/2] Installing or updating FFmpeg...
winget install --id Gyan.FFmpeg --exact --source winget --accept-source-agreements --accept-package-agreements
echo.
echo Installation steps finished. Close all CMD windows before starting VlogCraft.
 echo If winget reports an existing package, use winget upgrade instead.
pause
endlocal
