@echo off
:: AI Bulk Remix Studio Launcher (Windows)
setlocal enabledelayedexpansion

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed or not in PATH.
    echo    Please install Python 3.9 or later from https://python.org
    pause
    exit /b 1
)

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ⚠️  FFmpeg not found in PATH. Video processing will not work.
    echo    Download from https://ffmpeg.org/download.html
)

:: Create venv if not exists
if not exist ".venv" (
    echo 📦 Creating virtual environment...
    python -m venv .venv
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Install/update dependencies
if not exist ".venv\installed" (
    echo 📦 Installing dependencies...
    pip install -r requirements.txt -q
    type nul > .venv\installed
)

:: Launch app
echo 🚀 Starting AI Bulk Remix Studio...
python main.py %*

pause
