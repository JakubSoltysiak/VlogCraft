@echo off
setlocal
cd /d "%~dp0"
title VlogCraft Studio 3 - Private Video Editor
color 0B
echo.
echo  ============================================================
echo      VLOGCRAFT STUDIO 3   /   KENYA PRIVATE EDITION
 echo     Large files, layered timeline, 4K editing, AI review
 echo     LOCAL ONLY - Your original footage stays on your PC
 echo  ============================================================
echo.
where ffmpeg >nul 2>&1
if errorlevel 1 (
 echo [MISSING] FFmpeg was not found on your PATH.
 echo Run INSTALL_WINDOWS_DEPS.cmd once. Close this window and retry.
 pause
 exit /b 1
)
where py >nul 2>&1
if not errorlevel 1 (
 py -3 "%~dp0server.py"
 goto :finish
)
where python >nul 2>&1
if errorlevel 1 (
 echo [MISSING] Python 3 was not found on your PATH.
 echo Run INSTALL_WINDOWS_DEPS.cmd once, or install Python 3.11+.
 pause
 exit /b 1
)
python "%~dp0server.py"
:finish
if errorlevel 1 (
 echo.
 echo [ERROR] Could not start VlogCraft. Read the message above.
 pause
)
endlocal
