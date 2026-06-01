"""
Selenium browser bootstrap helpers used by the collector fallback path.
支持 Chrome 和 Edge 浏览器，自动检测已安装的浏览器。
"""
from __future__ import annotations

import os
import random
import shutil

from loguru import logger

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
)

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
window.chrome = { runtime: {} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : originalQuery(parameters)
);
"""


def _is_chrome_installed():
    """检查 Chrome 是否已安装"""
    # PATH 中有 chrome
    if shutil.which("chrome") or shutil.which("google-chrome"):
        return True
    # Windows 常见安装路径
    for path in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if os.path.exists(path):
            return True
    return False


def _is_edge_installed():
    """检查 Edge 是否已安装"""
    if shutil.which("msedge"):
        return True
    for path in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]:
        if os.path.exists(path):
            return True
    return False


def _build_common_options(headless: bool):
    """构建通用浏览器选项"""
    from selenium.webdriver.chrome.options import Options as ChromeOptions

    options = ChromeOptions()
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=zh-CN")
    options.add_argument("--window-size=1440,960")
    options.page_load_strategy = 'eager'
    if headless:
        options.add_argument("--headless=new")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return options


def _try_chrome(headless: bool):
    """启动 Chrome"""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    options = _build_common_options(headless)
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def _try_edge(headless: bool):
    """启动 Edge"""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.edge.service import Service
    from webdriver_manager.microsoft import EdgeChromiumDriverManager

    options = EdgeOptions()
    options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=zh-CN")
    options.add_argument("--window-size=1440,960")
    options.page_load_strategy = 'eager'
    if headless:
        options.add_argument("--headless=new")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(EdgeChromiumDriverManager().install())
    return webdriver.Edge(service=service, options=options)


def build_stealth_browser(headless: bool = False):
    """
    创建隐身浏览器实例，自动检测已安装的浏览器。
    优先级：Chrome → Edge（只尝试已安装的浏览器）。
    """
    logger.info("初始化 Selenium 隐身浏览器...")

    # 只尝试已安装的浏览器，避免下载驱动后发现浏览器不存在
    candidates = []
    if _is_chrome_installed():
        candidates.append(("Chrome", _try_chrome))
    if _is_edge_installed():
        candidates.append(("Edge", _try_edge))

    if not candidates:
        raise RuntimeError("未找到 Chrome 或 Edge 浏览器，请安装其中之一。")

    for name, factory in candidates:
        try:
            driver = factory(headless)
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": STEALTH_SCRIPT},
            )
            logger.info("  使用 {} 浏览器", name)
            return driver
        except Exception as e:
            logger.warning("  {} 启动失败: {}", name, str(e)[:100])

    raise RuntimeError(
        f"已安装的浏览器 ({', '.join(n for n, _ in candidates)}) 启动失败，请检查浏览器状态。"
    )


__all__ = ["build_stealth_browser"]
