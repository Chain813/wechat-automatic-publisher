@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"
title AutoWeChat

REM Check Python
echo [System] Checking Python
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
    echo [System] Creating venv
    python -m venv venv
    echo [System] Activating venv
    call "%~dp0venv\Scripts\activate.bat"
    echo [System] Installing requirements
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
    REM Activate venv
    echo [System] Activating venv
    call "%~dp0venv\Scripts\activate.bat"
)

REM Start Web UI
echo [System] Starting Web UI
python webui.py

pause
