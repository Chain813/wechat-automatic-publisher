@echo off
chcp 65001 >nul
title AutoWeChat - Web UI 启动器

echo ==========================================
echo   🚀 正在启动 AutoWeChat Web GUI ...
echo ==========================================

:: 检查是否存在 venv 虚拟环境
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

:: 启动 Flask 应用
echo [INFO] 启动后端服务...
start http://127.0.0.1:5000
python webui.py

pause
