@echo off
setlocal
cd /d "%~dp0"

echo.
echo === ReasonableRedactor (Windows) ===
echo Runs locally on YOUR computer, it does not upload your PDFs.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher (py) not found.
  echo Install Python from https://www.python.org/downloads/ then tick "Add to PATH".
  pause
  exit /b 1
)

echo Installing or updating requirements...
py -m pip install --upgrade pip >nul 2>nul
py -m pip install -r requirements.txt

echo.
echo Starting ReasonableRedactor...
py src\reasonableredactor.py

echo.
pause
