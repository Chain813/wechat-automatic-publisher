@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ==================================================
echo   智界洞察社 AI内容工厂 - 自动部署与运行脚本
echo ==================================================
echo.

:: 1. 检查 Python 环境
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python 环境，请确保已安装 Python 并添加至系统 PATH。
    pause
    exit /b 1
)

:: 2. 检查或初始化 .env 配置文件
if not exist ".env" (
    if exist ".env.example" (
        echo [配置] 检测到缺失 .env 文件，正在从模板生成...
        copy .env.example .env >nul
        echo [提示] 已自动创建 .env 文件。请在使用前打开它填入你的真实 API 密钥！
        echo.
    ) else (
        echo [警告] 找不到 .env.example 模板文件。
    )
)

:: 3. 检查并创建虚拟环境
if not exist "venv\Scripts\activate.bat" (
    echo [环境] 检测到未配置虚拟环境，正在自动创建隔离环境 (venv)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
)

:: 4. 激活虚拟环境
echo [环境] 正在激活 Python 虚拟环境...
call venv\Scripts\activate.bat

:: 5. 安装或更新依赖
echo [依赖] 正在检查并自动安装所需的依赖包 (使用国内镜像加速)...
python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo [错误] 依赖包安装失败，请检查网络连接或 requirements.txt。
    pause
    exit /b 1
)

:: 6. 运行主程序
echo.
echo ==================================================
echo   环境部署就绪，即将启动核心程序...
echo ==================================================
echo.
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 程序异常退出，请检查上方日志。
)

echo.
pause
