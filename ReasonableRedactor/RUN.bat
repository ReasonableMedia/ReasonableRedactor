@echo off
cd /d "%~dp0"

echo === ReasonableRedactor ===
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add it to PATH.
    pause
    exit /b 1
)

echo Installing / checking dependencies...
py -m pip install -r requirements.txt --quiet

echo.
echo Starting app — your browser will open automatically.
echo To stop, close this window or press Ctrl+C.
echo.

py src\app.py

pause
