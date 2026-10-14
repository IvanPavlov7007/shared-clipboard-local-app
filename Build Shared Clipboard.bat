@echo off
setlocal
title Build Shared Clipboard
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo First create the environment: python -m venv .venv
  goto :failed
)

".venv\Scripts\python.exe" -m pip install ".[build]"
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" build_project.py
if errorlevel 1 goto :failed

pause
exit /b 0

:failed
echo.
echo Build failed. Review the message above.
pause
exit /b 1
