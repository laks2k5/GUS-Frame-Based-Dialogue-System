@echo off
echo ============================================
echo   GUS - General User System
echo   Travel Booking Application
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Create .env if it doesn't exist
if not exist .env (
    echo Creating .env from .env.example...
    copy .env.example .env >nul
    echo.
    echo ============================================
    echo  .env file created!
    echo  Please edit .env with your API keys:
    echo    - Amadeus (flights)
    echo    - Railway API (trains)  
    echo    - Razorpay (payments)
    echo  
    echo  The app works without keys (limited features).
    echo  See README.md for setup instructions.
    echo ============================================
    echo.
    notepad .env
    echo Press any key after you've saved .env...
    pause >nul
)

:: Install dependencies
echo.
echo Installing Python dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo WARNING: Some packages may have failed to install.
    echo Try: pip install --user -r requirements.txt
    echo.
)

:: Start server
echo.
echo ============================================
echo  Starting GUS server...
echo  Open http://localhost:5000 in your browser
echo  Press Ctrl+C to stop
echo ============================================
echo.
python server.py
pause

