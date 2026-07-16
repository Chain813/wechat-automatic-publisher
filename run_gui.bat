@echo off
setlocal
cd /d "%~dp0"
title AutoWeChat - Web UI Launcher

echo ==========================================
echo   Starting AutoWeChat Web GUI ...
echo ==========================================

:: Check if Python is available
echo [System] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found.
    pause
    exit /b 1
)

:: Auto create .env
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
    )
)

:: Check and create venv
if not exist "venv\Scripts\activate.bat" (
    echo [System] Creating venv...
    python -m venv venv
)

:: Activate venv
echo [System] Activating venv...
call venv\Scripts\activate.bat

:: Install requirements
echo [System] Installing requirements...
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: Start Flask App
echo [INFO] Starting Backend Service...
python webui.py

pause
