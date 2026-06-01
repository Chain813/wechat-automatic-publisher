@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title AutoWeChat - Web UI 启动器

echo ==========================================
echo   🚀 正在启动 AutoWeChat Web GUI ...
echo ==========================================

:: 检查 Python 是否可用
echo [System] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [Error] Python not found.
    pause
    exit /b 1
)

:: 自动创建 .env
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
    )
)

:: 检查并创建 venv
if not exist "venv\Scripts\activate.bat" (
    echo [System] Creating venv...
    python -m venv venv
)

:: 激活 venv
echo [System] Activating venv...
call venv\Scripts\activate.bat

:: 安装依赖
echo [System] Installing requirements...
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

:: 启动 Flask 应用
echo [INFO] 启动后端服务...
python webui.py

pause
