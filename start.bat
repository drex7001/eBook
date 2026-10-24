@echo off
setlocal
cd /d %~dp0
title eBook translator
set CHECK=import uvicorn, fastapi, pymupdf, httpx, dotenv

if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment...
  py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo Could not create .venv. Install Python 3.11 or newer from python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
set PY=.venv\Scripts\python.exe

%PY% -c "%CHECK%" 2>nul
if errorlevel 1 (
  echo Installing packages...
  if exist wheels %PY% -m pip install --disable-pip-version-check --no-index --find-links wheels -r requirements.txt
  %PY% -c "%CHECK%" 2>nul || %PY% -m pip install --disable-pip-version-check --timeout 180 --retries 10 -r requirements.txt
  %PY% -c "%CHECK%" 2>nul
  if errorlevel 1 (
    echo.
    echo Package install did not finish. Check the internet connection and run start.bat again.
    pause
    exit /b 1
  )
)

%PY% run.py
pause
