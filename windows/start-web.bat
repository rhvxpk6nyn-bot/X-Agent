@echo off
setlocal

cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.12 or newer, then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

echo Installing X-Agent...
python -m pip install --upgrade pip
python -m pip install -e .
if errorlevel 1 (
  echo Install failed.
  pause
  exit /b 1
)

echo.
echo Starting X-Agent Windows web UI...
echo Open http://127.0.0.1:9531/
echo.

python -m uvicorn web.backend.server:app --host 127.0.0.1 --port 9531

pause
