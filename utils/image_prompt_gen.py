"""
============================================================
  图片提示词生成器 — 将中文关键词转化为 Imagen 3 英文 Prompt
  供用户手动在 Gemini 网页版生图后拖拽到 WebUI 图片工作台
============================================================
"""
import re
import json
from loguru import logger
from config import IMAGE_GEN_MODEL
from core.shared.llm import call_deepseek_with_retry

# 配图/图表占位符正则（同时支持照片配图与技术图表占位符）
PLACEHOLDER_PATTERN = re.compile(r"【\s*此处(?:插入配图|绘制图表)\s*[：:]\s*(.*?)\s*】")


def extract_placeholders(article_text: str) -> list[str]:
    """
    从 Markdown 文章文本中提取所有 【此处插入配图：xxx】 占位符关键词。
    返回去重且保序的关键词列表。
    """
    seen = set()
    result = []
    for match in PLACEHOLDER_PATTERN.findall(article_text or ""):
        kw = match.strip()
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result


def generate_image_prompts(article_title: str, placeholders: list[str]) -> list[dict]:
    """
    输入文章标题 + 占位符关键词列表，
    调用 LLM 批量翻译为目标生图模型 (如 IMAGE_GEN_MODEL) 的英文 Prompt。

    返回:
        [{"index": 1, "keyword": "原中文", "prompt": "English prompt..."}, ...]
    """
    if not placeholders:
        return []

    keywords_text = "\n".join(f"{i+1}. {kw}" for i, kw in enumerate(placeholders))

    user_prompt = (
        f"文章标题：{article_title}\n\n"
        f"以下是文章中需要配图的关键词列表：\n{keywords_text}\n\n"
        f"请为每个关键词生成一段适合 {IMAGE_GEN_MODEL} 模型的英文生图 Prompt。\n\n"
        "要求：\n"
        "1. 每个 Prompt 为 1-2 句精炼英文，描述一幅高清 16:9 科技感/现代感图片\n"
        "2. 包含画面风格、色彩感与视角（如 cinematic, 8k, modern tech style）\n"
        "3. 与文章主题和关键词语义高度契合\n"
        "4. 严格按 JSON 数组格式输出，不要多余文字\n\n"
        "输出格式：\n"
        "```json\n"
        '[\n'
        '  {"index": 1, "prompt": "英文提示词..."},\n'
        '  {"index": 2, "prompt": "英文提示词..."}\n'
        ']\n'
        "```"
    )

    system = "你是一个专业 AI 绘图提示词专家。将中文关键词转化为高质量英文图片生成提示词。严格输出 JSON 数组。"

    try:
        result = call_deepseek_with_retry(
            user_prompt,
            system_content=system,
            max_retries=2,
            backoff_base=0.5,
        )
        if not result:
            logger.warning("[图片提示词] LLM 返回为空")
            return _fallback_prompts(placeholders)

        # 提取 JSON
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', result, re.DOTALL)
        json_text = json_match.group(1) if json_match else result

        prompts_data = json.loads(json_text)
        if not isinstance(prompts_data, list):
            raise ValueError("非数组格式")

        # 合并关键词
        prompts = []
        for i, kw in enumerate(placeholders):
            entry = {"index": i + 1, "keyword": kw, "prompt": ""}
            for item in prompts_data:
                if item.get("index") == i + 1:
                    entry["prompt"] = item.get("prompt", "")
                    break
            if not entry["prompt"]:
                entry["prompt"] = f"High resolution 16:9 cinematic photo about {kw}, modern tech style, 8k"
            prompts.append(entry)

        logger.info("[图片提示词] 成功生成 {} 条英文 Prompt", len(prompts))
        return prompts

    except Exception as e:
        logger.warning("[图片提示词] 生成异常: {}", e)
        return _fallback_prompts(placeholders)


def _fallback_prompts(placeholders: list[str]) -> list[dict]:
    """LLM 失败时的兜底提示词"""
    return [
        {
            "index": i + 1,
            "keyword": kw,
            "prompt": f"High resolution 16:9 cinematic illustration of {kw}, modern digital art style, vibrant colors, 8k resolution"
        }
        for i, kw in enumerate(placeholders)
    ]


def render_article_preview(article_text: str, article_title: str, images_mapping: dict) -> str:
    """
    Render article Markdown to WeChat-styled HTML, embedding local/uploaded images.
    images_mapping is a dict of {str(index): image_url_or_filepath}
    """
    import markdown
    
    # 1. Clean markdown code blocks if needed
    lines = article_text.strip().splitlines()
    if len(lines) >= 2 and lines[0].strip() in ("```markdown", "```") and lines[-1].strip() == "```":
        cleaned = "\n".join(lines[1:-1]).strip()
    else:
        cleaned = article_text.strip()
        
    cleaned = re.sub(r'([^\n])\n(```[a-zA-Z]*)', r'\1\n\n\2', cleaned)
    
    # Clean structures (from article_utils.py)
    from core.shared.article_utils import _STRUCTURAL_LABEL_PATTERNS
    for pattern in _STRUCTURAL_LABEL_PATTERNS:
        cleaned = pattern.sub('', cleaned)
        
    # Bold styles
    cleaned = re.sub(r'\*\*\{+(.*?)\}+\*\*', r'<redbold>\1</redbold>', cleaned)
    
    # Clean spacing
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r'^(#{1,4}\s+[^\n]+)[:：]\s*$', r'\1', cleaned, flags=re.MULTILINE)
    
    # 2. Extract placeholders to map index to keyword
    placeholders = extract_placeholders(cleaned)
    
    # 3. Convert Markdown to HTML
    html_body = markdown.markdown(cleaned, extensions=["fenced_code", "tables", "sane_lists"])
    
    # Clean <p> around placeholders
    html_body = re.sub(
        r'<p>\s*(【\s*此处(?:插入配图|绘制图表)\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )
    
    # 4. Replace placeholders with images or placeholder block
    for i, kw in enumerate(placeholders):
        idx_str = str(i + 1)
        img_url = images_mapping.get(idx_str)
        
        if img_url:
            image_html = (
                '<p style="text-align:center;margin: 20px 0;">'
                f'<img src="{img_url}" style="width:100%;max-width:600px;border-radius:12px;'
                'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                "</p>"
            )
        else:
            # Render a nice placeholder box in the preview
            image_html = (
                '<div style="margin: 20px auto; max-width: 600px; padding: 30px; text-align: center; '
                'border: 2px dashed rgba(148, 163, 184, 0.3); border-radius: 12px; background: rgba(30, 41, 59, 0.2); '
                'color: #94a3b8; font-family: sans-serif;">'
                f'<div style="font-size: 24px; margin-bottom: 8px;">📷</div>'
                f'<div style="font-size: 14px; font-weight: 600;">配图 #{i+1}：{kw}</div>'
                '<div style="font-size: 12px; margin-top: 4px; color: rgba(148, 163, 184, 0.6);">（尚未上传图片，拖拽图片到上方卡片进行配图）</div>'
                '</div>'
            )
        
        # Replace this placeholder
        pattern = re.compile(rf"【\s*此处(?:插入配图|绘制图表)\s*[：:]\s*{re.escape(kw)}\s*】")
        html_body = pattern.sub(lambda m, h=image_html: h, html_body)
        
    # 5. Apply styling identical to article_utils.py
    html_body = html_body.replace(
        '<p>', 
        '<p style="margin-bottom: 15px; line-height: 1.8; text-align: justify; font-size: 16px; color: #333;">'
    )
    html_body = html_body.replace(
        '<blockquote>', 
        '<blockquote style="margin: 20px 0; padding: 15px 20px; border-left: 5px solid #0366d6; background-color: #f6f8fa; color: #586069; border-radius: 4px; font-size: 15px;">'
    )
    html_body = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="margin-top: 35px; margin-bottom: 20px; padding-bottom: 8px; border-bottom: 2px solid #eaecef; font-size: 22px; color: #24292e; font-weight: bold;">\1</h2>',
        html_body
    )
    html_body = re.sub(
        r'<h3>(.*?)</h3>',
        r'<h3 style="margin-top: 25px; margin-bottom: 15px; font-size: 18px; color: #0366d6; font-weight: bold; border-left: 4px solid #0366d6; padding-left: 10px;">\1</h3>',
        html_body
    )
    html_body = html_body.replace(
        '<ul>',
        '<ul style="margin-bottom: 20px; padding-left: 25px; line-height: 1.8; color: #333;">'
    )
    html_body = html_body.replace(
        '<redbold>', '<strong style="color: #d73a49; font-weight: bold;">'
    ).replace(
        '</redbold>', '</strong>'
    )
    html_body = re.sub(
        r'<strong>(.*?)</strong>',
        r'<strong style="color: #1a1a1a; font-weight: bold;">\1</strong>',
        html_body
    )
    
    # Mac code terminal style
    mac_dots = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:10px;"><span style="width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block;"></span><span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;display:inline-block;"></span><span style="width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block;"></span></div>'
    code_container_style = (
        'margin: 20px 0; padding: 14px 18px; background-color: #1e293b; color: #f8fafc; '
        'border-radius: 12px; font-family: Consolas, Monaco, "Courier New", monospace; '
        'font-size: 13.5px; line-height: 1.65; overflow-x: auto; box-shadow: 0 6px 18px rgba(0,0,0,0.25);'
    )
    html_body = re.sub(
        r'<pre>\s*<code[^>]*>(.*?)</code>\s*</pre>',
        r'<div style="' + code_container_style + r'">' + mac_dots + r'<pre style="margin:0;padding:0;background:transparent;border:none;color:#f8fafc;font-family:inherit;white-space:pre-wrap;word-break:break-all;">\1</pre></div>',
        html_body,
        flags=re.DOTALL
    )
    
    font_stack = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif"
    html_body = html_body.replace(
        '<code>',
        f'<code style="font-family: {font_stack}; background-color: #f1f5f9; padding: 2px 5px; border-radius: 4px; color: #2563eb; font-size: 0.95em;">'
    )
    
    # Wrap in a standard mobile preview wrapper
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{
                margin: 0;
                padding: 20px;
                font-family: {font_stack};
                background-color: #fff;
                color: #333;
                max-width: 677px;
                margin: 0 auto;
                box-sizing: border-box;
            }}
        </style>
    </head>
    <body>
        <h1 style="font-size: 22px; line-height: 1.4; margin-bottom: 20px; font-weight: bold; color: #333;">{article_title}</h1>
        {html_body}
    </body>
    </html>
    """
    return full_html

