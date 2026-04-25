@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo [System] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found.
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
    )
)

if not exist "venv\Scripts\activate.bat" (
    echo [System] Creating venv...
    python -m venv venv
)

echo [System] Activating venv...
call venv\Scripts\activate.bat

echo [System] Installing requirements...
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

echo [System] Starting main.py...
python main.py

pause
