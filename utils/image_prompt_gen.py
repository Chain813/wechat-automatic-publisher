"""
============================================================
  图片提示词生成器 — 将中文关键词转化为目标生图模型的英文 Prompt
  供用户用 Qwen-Image 等模型生图后拖拽到 WebUI 图片工作台
============================================================
"""
import re
import json
from loguru import logger
import config
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

    active_model = getattr(config, "IMAGE_GEN_MODEL", "gemini-nano-banana-2.1") or "gemini-nano-banana-2.1"
    user_prompt = (
        f"文章标题：{article_title}\n\n"
        f"以下是文章中需要配图的主题列表：\n{keywords_text}\n\n"
        f"请为每一项生成一段适合 {active_model} 模型的【纯视觉无字】16:9 杂志级概念插画提示词。\n\n"
        "要求：\n"
        "1. 融合《经济学人》编辑插画叙事张力与 Linear 浅灰白微纹理纸面质感（深岩灰主调 + 少量靛蓝与珊瑚红焦点），严禁赛博黑底霓虹与写实人脸\n"
        "2. 100% 纯视觉无字画面：绝对禁止渲染任何汉字、英文字母、数字、标点、标签胶囊或水印\n"
        "3. 严禁流程图、箭头连线与多栏卡片排版，每张图仅聚焦 1 个具象物理/空间视觉隐喻，主体居中落在 2.35:1 封面安全区内，四周保留 ≥35% 留白\n"
        "4. 严格按 JSON 数组格式输出，不要多余文字\n\n"
        "输出格式：\n"
        "```json\n"
        '[\n'
        '  {"index": 1, "prompt": "16:9 纯视觉无字概念插画提示词..."},\n'
        '  {"index": 2, "prompt": "16:9 纯视觉无字概念插画提示词..."}\n'
        ']\n'
        "```"
    )

    system = "你是一位顶级科技商业杂志的插画艺术总监，擅长编写《经济学人》风格、100% 纯视觉无字且兼容封面裁切的 16:9 概念插画提示词。严格输出 JSON 数组。"

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
    
    # Clean structures & apply shared bold pipeline (from article_utils.py)
    from core.shared.article_utils import (
        _STRUCTURAL_LABEL_PATTERNS,
        _apply_bold_fallback,
        _apply_inline_strong_styles,
        extract_redbold_tags,
    )
    for pattern in _STRUCTURAL_LABEL_PATTERNS:
        cleaned = pattern.sub('', cleaned)

    cleaned = extract_redbold_tags(cleaned)
    cleaned = _apply_bold_fallback(cleaned)
    
    # Clean spacing
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r'^(#{1,4}\s+[^\n]+)[:：]\s*$', r'\1', cleaned, flags=re.MULTILINE)
    
    # 2. Extract placeholders to map index to keyword
    placeholders = extract_placeholders(cleaned)
    
    # 3. Isolate standalone placeholders so blockquotes don't swallow them, then convert Markdown
    cleaned = re.sub(
        r'(?m)^[ \t]*(?:>\s*)?(【\s*(?:此处插入配图|此处绘制(?:图表|架构图|流程图|示意图|逻辑图)?)\s*[：:].*?】)[ \t]*$',
        r'\n\n\1\n\n',
        cleaned,
    )
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    html_body = markdown.markdown(cleaned, extensions=["fenced_code", "tables", "sane_lists"])
    
    # Clean <p> around placeholders
    html_body = re.sub(
        r'<p>\s*(【\s*此处(?:插入配图|绘制图表)\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )
    
    # 4. Replace placeholders sequentially with single-pass matching
    slot_cursor = 0
    pattern_placeholder = re.compile(r"【\s*此处(?:插入配图|绘制图表)\s*[：:]\s*(.*?)\s*】")

    def _replace_preview_placeholder(match):
        nonlocal slot_cursor
        current_idx = slot_cursor
        slot_cursor += 1
        idx_str = str(current_idx + 1)
        kw = match.group(1).strip()
        img_url = images_mapping.get(idx_str) or images_mapping.get(current_idx)

        if img_url:
            return (
                '<p style="text-align:center;margin: 20px 0;">'
                f'<img src="{img_url}" style="width:100%;max-width:600px;border-radius:12px;'
                'box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.06);">'
                '</p>'
            )
        else:
            return (
                '<section style="margin: 24px auto; max-width: 600px; padding: 24px 20px; text-align: center; '
                'border: 1.5px dashed rgba(79, 91, 213, 0.3); border-radius: 14px; background: #F8F9FB; '
                'color: #5E6470; box-shadow: 0 1px 2px rgba(0,0,0,0.02), inset 0 1px 0 rgba(255,255,255,1);">'
                '<div style="display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px; border-radius: 50%; background: rgba(79,91,213,0.08); margin-bottom: 8px;">'
                '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#4F5BD5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>'
                '</div>'
                f'<div style="font-size: 14.5px; font-weight: 600; color: #0C0D0E;">配图 #{current_idx+1}：{kw}</div>'
                '<div style="font-size: 12px; margin-top: 4px; color: #8C919E;">（尚未配置图片，可直接上传或生成配图）</div>'
                '</section>'
            )

    html_body = pattern_placeholder.sub(_replace_preview_placeholder, html_body)
        
    # 5. Apply Linear Modern Light styling aligned with article_utils.py
    from core.shared.article_utils import _render_custom_callouts, _format_markdown_tables

    html_body = _render_custom_callouts(html_body)
    html_body = _format_markdown_tables(html_body)

    html_body = html_body.replace(
        '<p>', 
        '<p style="margin-bottom: 16px; line-height: 1.85; text-align: justify; font-size: 16px; color: #334155;">'
    )
    # Remove empty paragraphs
    html_body = re.sub(r'<p style="[^"]*">\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*', '', html_body)
    html_body = re.sub(r'<p[^>]*>\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*', '', html_body)

    bq_style = (
        'margin: 22px 0; padding: 16px 20px; border: 1px solid rgba(0,0,0,0.06); '
        'border-left: 4px solid #4F5BD5; background-color: #F8F9FB; color: #5E6470; '
        'border-radius: 8px; font-size: 15px; line-height: 1.75; box-shadow: 0 1px 2px rgba(0,0,0,0.02);'
    )
    html_body = re.sub(
        r'<blockquote>(.*?)</blockquote>',
        lambda m: f'<blockquote style="{bq_style}">{m.group(1).strip()}</blockquote>',
        html_body,
        flags=re.DOTALL
    )

    html_body = re.sub(
        r'<h1>(.*?)</h1>',
        r'<h1 style="margin-top: 36px; margin-bottom: 20px; font-size: 24px; color: #0C0D0E; font-weight: 700; line-height: 1.4; letter-spacing: -0.02em; border-bottom: 1px solid #E2E8F0; padding-bottom: 12px;">\1</h1>',
        html_body
    )
    html_body = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="margin-top: 38px; margin-bottom: 22px; padding: 10px 16px; border-left: 4px solid #4F5BD5; background: linear-gradient(90deg, rgba(79,91,213,0.08) 0%, rgba(248,249,251,0) 100%); border-radius: 6px; font-size: 20px; color: #0C0D0E; font-weight: 700; letter-spacing: -0.01em;">\1</h2>',
        html_body
    )
    html_body = re.sub(
        r'<h3>(.*?)</h3>',
        r'<h3 style="margin-top: 28px; margin-bottom: 16px; font-size: 17px; color: #0C0D0E; font-weight: 600; border-left: 3px solid #4F5BD5; padding-left: 10px;">\1</h3>',
        html_body
    )
    html_body = html_body.replace(
        '<ul>',
        '<ul style="margin-bottom: 20px; padding-left: 22px; line-height: 1.85; color: #334155;">'
    )
    html_body = html_body.replace(
        '<ol>',
        '<ol style="margin-bottom: 20px; padding-left: 22px; line-height: 1.85; color: #334155;">'
    )
    html_body = html_body.replace(
        '<li>',
        '<li style="margin-bottom: 8px; line-height: 1.85; color: #334155;">'
    )
    html_body = re.sub(
        r'<hr\s*/?>',
        '<hr style="border: none; border-top: 1px solid #E2E8F0; margin: 32px 0;">',
        html_body
    )
    html_body = _apply_inline_strong_styles(html_body)
    
    # Linear Modern Light Sunken Code Card
    code_header = (
        '<div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 14px; background-color: #F1F3F7; border-bottom: 1px solid #E2E8F0;">'
        '<div style="display: flex; align-items: center; gap: 6px;">'
        '<span style="width: 10px; height: 10px; border-radius: 50%; background: #EF4444; display: inline-block;"></span>'
        '<span style="width: 10px; height: 10px; border-radius: 50%; background: #F59E0B; display: inline-block;"></span>'
        '<span style="width: 10px; height: 10px; border-radius: 50%; background: #10B981; display: inline-block;"></span>'
        '</div>'
        '<span style="font-size: 11px; font-weight: 600; color: #5E6470; letter-spacing: 0.05em; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">CODE</span>'
        '</div>'
    )
    def _format_code_block(match):
        code_content = match.group(1)
        return (
            '<section style="margin: 22px 0; border: 1px solid #E2E8F0; border-radius: 10px; '
            'background-color: #F8F9FB; box-shadow: 0 1px 2px rgba(0,0,0,0.03), inset 0 1px 0 rgba(255,255,255,1); '
            'overflow: hidden; display: block;">'
            f'{code_header}'
            f'<pre style="margin: 0; padding: 14px 18px; background-color: #F8F9FB; color: #0C0D0E; '
            f'font-family: Consolas, Monaco, \'Courier New\', monospace; font-size: 13.5px; line-height: 1.65; '
            f'white-space: pre-wrap; word-break: break-all; border: none; overflow-x: auto; display: block;">{code_content}</pre>'
            '</section>'
        )

    html_body = re.sub(
        r'<pre>\s*<code[^>]*>(.*?)</code>\s*</pre>',
        _format_code_block,
        html_body,
        flags=re.DOTALL
    )
    
    html_body = re.sub(
        r'<code>(.*?)</code>',
        r'<code style="font-family: Consolas, Monaco, \'Courier New\', monospace; background-color: #F1F3F7; padding: 2px 6px; border-radius: 4px; color: #4F5BD5; border: 1px solid rgba(79,91,213,0.15); font-size: 0.92em;">\1</code>',
        html_body
    )
    
    # Wrap in a Linear Modern Light mobile preview wrapper
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 24px 16px;
                font-family: "Inter", "Geist Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
                background-color: #F8F9FB;
                color: #0C0D0E;
                box-sizing: border-box;
                display: flex;
                justify-content: center;
            }}
            .article-preview-container {{
                width: 100%;
                max-width: 677px;
                background-color: #FFFFFF;
                border: 1px solid rgba(0, 0, 0, 0.06);
                border-radius: 16px;
                padding: 32px 28px;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03), 0 4px 16px rgba(15, 23, 42, 0.04), inset 0 1px 0 rgba(255, 255, 255, 1);
                box-sizing: border-box;
            }}
        </style>
    </head>
    <body>
        <div class="article-preview-container">
            <h1 style="font-size: 24px; line-height: 1.4; margin-top: 0; margin-bottom: 24px; font-weight: 700; color: #0C0D0E; border-bottom: 1px solid #E2E8F0; padding-bottom: 16px; letter-spacing: -0.02em;">{article_title}</h1>
            {html_body}
        </div>
    </body>
    </html>
    """
    return full_html

