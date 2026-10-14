@echo off
setlocal
title Shared Clipboard Local App
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  call :find_python
  if errorlevel 1 goto :failed
  call :create_environment
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -c "import aiohttp, segno" >nul 2>&1
if errorlevel 1 (
  echo Installing Shared Clipboard dependencies...
  ".venv\Scripts\python.exe" -m pip install .
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" shared_clipboard.py %*
if errorlevel 1 goto :failed
exit /b 0

:find_python
set "PYTHON_EXE="
for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON_EXE=%%P"
)
if not defined PYTHON_EXE (
  echo Python could not be found. Install Python 3.9 or newer and try again.
  exit /b 1
)
exit /b 0

:create_environment
echo Creating a local Python environment...
"%PYTHON_EXE%" -m venv .venv
exit /b %errorlevel%

:failed
echo.
echo Shared Clipboard could not start. Review the message above.
pause
exit /b 1
