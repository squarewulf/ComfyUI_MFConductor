@echo off
title MF Conductor - Custom Node Manager
cd /d "%~dp0"

REM ============================================================
REM  MF Conductor - Standalone Launcher
REM  Custom Node Manager for ComfyUI
REM ============================================================

echo.
echo  ============================================================
echo   MF Conductor - Custom Node Manager
echo  ============================================================
echo.

REM Find Python - check for embedded Python first
set PYTHON_PATH=

REM Check ComfyUI portable embedded Python (relative paths)
if exist "..\..\..\python_embeded\python.exe" (
    set PYTHON_PATH=..\..\..\python_embeded\python.exe
    echo  Found: ComfyUI Embedded Python
    goto :run_server
)

REM Check alternative location
if exist "..\..\..\..\python_embeded\python.exe" (
    set PYTHON_PATH=..\..\..\..\python_embeded\python.exe
    echo  Found: ComfyUI Embedded Python (alt)
    goto :run_server
)

REM Check system Python
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_PATH=python
    echo  Found: System Python
    goto :run_server
)

REM No Python found
echo  ERROR: Python not found!
echo.
echo  Please ensure Python is installed or run from ComfyUI portable.
echo.
pause
exit /b 1

:run_server
echo  Starting server...
echo  ------------------------------------------------------------
echo.

REM Run the standalone server
"%PYTHON_PATH%" standalone_server.py --host localhost --port 8199

REM If server exits, pause to see any errors
echo.
echo  Server stopped.
pause

