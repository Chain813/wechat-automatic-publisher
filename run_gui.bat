@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"
title AutoWeChat - Web UI Launcher

echo ==========================================
echo   Starting AutoWeChat Web GUI
echo ==========================================

REM Check Python
echo [System] Checking Python environment
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found. Please install Python 3.8+ and add it to PATH.
    pause
    exit /b 1
)

REM Auto create .env
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
    )
)

REM Check and create venv
if not exist "venv\Scripts\activate.bat" (
    echo [System] Creating virtual environment
    python -m venv venv
    echo [System] Activating venv
    call "%~dp0venv\Scripts\activate.bat"
    echo [System] Installing dependencies
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
    REM Activate venv
    echo [System] Activating venv
    call "%~dp0venv\Scripts\activate.bat"
)

REM Start Web UI Service
echo [INFO] Starting Backend Service
echo [INFO] Web UI will open in browser at http://127.0.0.1:5000
python webui.py

pause
