"""
============================================================
  HTML/Mermaid/LaTeX 本地渲染引擎 v1.0
  基于 Headless Selenium 将 HTML、Mermaid.js 图表和 KaTeX 公式
  渲染并截图保存为高质量的 PNG 图片
============================================================
"""
import os
import time
import tempfile
from loguru import logger
from selenium.webdriver.common.by import By
from utils.spider import build_stealth_browser

# 用于包装内容的通用 HTML 模板，集成 Tailwind CSS, KaTeX 和 Mermaid.js
HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex/dist/katex.min.css">
    <script src="https://cdn.jsdelivr.net/npm/katex/dist/katex.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/katex/dist/contrib/auto-render.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 10px;
            background-color: transparent;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            overflow: hidden;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        #render-target {{
            display: inline-block;
            background-color: #0b0e14;
            color: #e2e8f0;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            max-width: 100%;
            box-sizing: border-box;
            {container_style}
        }}
        /* 自定义 Mermaid 样式 */
        .mermaid {{
            background: transparent !important;
        }}
        .mermaid svg {{
            max-width: 100% !important;
            height: auto !important;
        }}
    </style>
</head>
<body>
    <div id="render-target">
        {content}
    </div>
    
    <script>
        // 初始化 Mermaid (使用 dark 主题适配公众号暗色卡片样式)
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'dark',
            securityLevel: 'loose',
            flowchart: {{ useMaxWidth: false, htmlLabels: true }},
            themeVariables: {{
                background: 'transparent',
                primaryColor: '#1f2937',
                primaryTextColor: '#f3f4f6',
                lineColor: '#3b82f6'
            }}
        }});
        
        // 渲染数学公式
        document.addEventListener("DOMContentLoaded", function() {{
            renderMathInElement(document.body, {{
                delimiters: [
                    {{left: "$$", right: "$$", display: true}},
                    {{left: "$", right: "$", display: false}}
                ]
            }});
        }});
    </script>
</body>
</html>
"""

def render_html_to_png(html_body: str, output_path: str, width: int = 850) -> bool:
    """
    将 HTML 片段（含 Mermaid 代码或 LaTeX 公式）在本地渲染为 PNG
    
    Args:
        html_body: 包含要渲染的主体 HTML
        output_path: 保存的 PNG 路径
        width: 浏览器视口宽度（默认 850px，容纳 700px 卡片及外边距）
        
    Returns:
        bool: 渲染是否成功
    """
    # 自动识别是否为自包含卡片，防止双重背景和边框嵌套
    is_card = any(x in html_body for x in ["w-[", "bg-", "rounded-", "border-"])
    container_style = "background-color:transparent;border:none;padding:0;box-shadow:none;border-radius:0;" if is_card else ""

    # 组合为完整 HTML
    full_html = HTML_TEMPLATE.format(content=html_body, container_style=container_style)
    
    temp_file = None
    browser = None
    try:
        # 1. 写入临时文件
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
            f.write(full_html)
            temp_file = f.name
            
        # 2. 启动 Headless 浏览器（宽度设为 850px 充裕视口，避免卡片阴影/外边距右侧截断）
        viewport_w = max(width, 850)
        browser = build_stealth_browser(headless=True)
        browser.set_window_size(viewport_w, 1200)
        
        # 3. 加载页面
        file_url = "file:///" + temp_file.replace(os.sep, "/")
        browser.get(file_url)
        
        # 4. 动态等待 DOM 渲染完成与高度稳定（解决 CDN/Mermaid/KaTeX 延迟加载导致底部截断）
        last_h = -1
        stable_count = 0
        target = None
        for _ in range(25):  # 最多等待 5 秒 (25 * 0.2s)
            try:
                target = browser.find_element(By.ID, "render-target")
                curr_h = target.size.get('height', 0)
                if curr_h > 50 and curr_h == last_h:
                    stable_count += 1
                    if stable_count >= 2:  # 高度连续 2 次保持稳定，说明渲染完毕
                        break
                else:
                    stable_count = 0
                    last_h = curr_h
            except Exception:
                pass
            time.sleep(0.2)

        if not target:
            target = browser.find_element(By.ID, "render-target")

        # 5. 动态调整浏览器高度以完美契合元素
        size = target.size
        needed_height = max(int(size['height']) + 50, 200)
        browser.set_window_size(viewport_w, needed_height)
        time.sleep(0.2)  # 稳定尺寸
        
        # 6. 保存截图（Selenium 的 element.screenshot 会自动裁剪出该元素的区域）
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        target.screenshot(output_path)
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100:
            logger.info("  [html_render] 渲染成功: {} ({:.1f} KB)", os.path.basename(output_path), os.path.getsize(output_path)/1024)
            return True
        return False
        
    except Exception as e:
        logger.error("  [html_render] 渲染失败: {}", e)
        return False
        
    finally:
        if browser:
            try:
                browser.quit()
            except Exception:
                pass
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
