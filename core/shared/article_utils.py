import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import markdown
import requests
from loguru import logger

from config import BRAND_NAME, WECHAT_TITLE_MAX_LEN, ASSET_RETENTION_DAYS
from core.shared.llm import filter_sensitive, simplify_keyword, call_deepseek_with_retry

PLACEHOLDER_PATTERN = re.compile(r"【\s*此处插入配图\s*[：:]\s*(.*?)\s*】")
GITHUB_IMAGE_PATTERN = re.compile(r"【\s*GITHUB配图\s*[：:]\s*(https?://.*?)\s*】")

# 预编译结构性标签清理正则（避免每篇文章重复编译 30 个正则）
_STRUCTURAL_LABELS = [
    "事件钩子", "拆解博弈", "技术逻辑", "预判观点", "互动收尾",
    "核心特性", "适用场景", "项目亮点", "技术/产业逻辑", "技术与产业深挖",
]
_STRUCTURAL_LABEL_PATTERNS = []
for _label in _STRUCTURAL_LABELS:
    _escaped = re.escape(_label)
    _STRUCTURAL_LABEL_PATTERNS.append(re.compile(rf'#+\s*{_escaped}\s*[:：]?\s*\n?'))
    _STRUCTURAL_LABEL_PATTERNS.append(re.compile(rf'\*\*{_escaped}\*\*\s*[:：]?\s*'))
    _STRUCTURAL_LABEL_PATTERNS.append(re.compile(rf'{_escaped}[：:]\s*'))


def _optimize_image_keyword_with_llm(original_keyword):
    """
    当常规搜索无法找到高质量图片时，调用 LLM 将抽象的政策/技术术语
    转化为更具视觉表现力的搜索词。
    例如：'AI 监管政策' -> '科技感天平 电路纹理 蓝色光效'
    仅在 simplify_keyword 也失败后触发，token 消耗极低 (~100 tokens)。
    """
    if not original_keyword or len(original_keyword) < 2:
        return ""
    prompt = (
        f"原始关键词：{original_keyword}\n\n"
        "请将这个关键词转化为一个适合在图片搜索引擎中使用的、具有强烈视觉画面感的搜索词。\n"
        "要求：\n"
        "- 输出 3-5 个中文关键词，用空格分隔\n"
        "- 关键词要具象化、有画面感（如'芯片电路板特写'、'数据流光效'）\n"
        "- 避免抽象概念词（如'政策'、'监管'、'趋势'）\n"
        "- 直接输出关键词，不要有其他文字"
    )
    try:
        result = call_deepseek_with_retry(
            prompt,
            system_content="你是一个图片搜索优化专家。只输出优化后的搜索关键词。",
            max_retries=1,
            backoff_base=0.3,
        )
        if result:
            optimized = result.strip().split('\n')[0].strip()
            logger.info("  LLM 图像关键词优化: '{}' -> '{}'", original_keyword, optimized)
            return optimized
    except Exception as e:
        logger.debug("  LLM 图像关键词优化失败: {}", e)
    return ""


def _download_and_upload(keyword, publisher, use_ai_first=False):
    """下载图片并立即上传到微信，合并为单步操作（供并行调用）"""
    keyword = keyword.strip()
    if not keyword:
        return keyword, None

    from utils.image_handler import download_image as _dl

    logger.info("正在为段落关键词 '{}' 搜寻最佳配图...", keyword)
    image_path = _dl(keyword)

    # 降级：简化关键词重试
    if not image_path:
        simplified = simplify_keyword(keyword)
        if simplified and simplified.strip():
            image_path = _dl(simplified)

    # LLM 关键词优化兜底：将抽象概念转化为视觉化搜索词
    if not image_path:
        optimized = _optimize_image_keyword_with_llm(keyword)
        if optimized:
            image_path = _dl(optimized)

    if not image_path:
        return keyword, None

    image_url = publisher.upload_news_image(image_path)
    return keyword, image_url

def _extract_image_placeholders(article_text):
    placeholders = []
    seen = set()
    for match in PLACEHOLDER_PATTERN.findall(article_text or ""):
        keyword = match.strip()
        if keyword and keyword not in seen:
            seen.add(keyword)
            placeholders.append(keyword)
    return placeholders

def _replace_placeholder(html_body, keyword, replacement):
    # 使用正则表达式进行不区分空格的替换
    pattern = re.compile(rf"【\s*此处插入配图\s*[：:]\s*{re.escape(keyword)}\s*】")
    return pattern.sub(replacement, html_body)

def _clean_latex_math(text: str) -> str:
    """清理并转换文章中未渲染的原生 LaTeX 数学符号及 $...$ 标记为普通可读字符"""
    if not text:
        return text

    # 1. 处理块级数学公式与环境
    text = re.sub(r'\\\[\s*(.*?)\s*\\\]', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\$\$\s*(.*?)\s*\$\$', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\\\(\s*(.*?)\s*\\\)', r'\1', text, flags=re.DOTALL)

    # 2. 移除 LaTeX 格式化包装宏及定界符
    text = re.sub(r'\\(?:text|mathrm|mathbf|mathit|mathcal|mathbb|mathsf)\s*\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\left\s*\\\{', '{', text)
    text = re.sub(r'\\right\s*\\\}', '}', text)
    text = re.sub(r'\\left\s*([(\[{|.])', r'\1', text)
    text = re.sub(r'\\right\s*([)\]}|.])', r'\1', text)

    # 3. 根号与分数
    def _clean_frac(match):
        num, den = match.group(1).strip(), match.group(2).strip()
        num_str = f"({num})" if (" " in num or "+" in num or "-" in num) and not (num.startswith("(") and num.endswith(")")) else num
        den_str = f"({den})" if (" " in den or "+" in den or "-" in den) and not (den.startswith("(") and den.endswith(")")) else den
        return f"{num_str} / {den_str}"

    text = re.sub(r'\\frac\s*\{([^}]+)\}\s*\{([^}]+)\}', _clean_frac, text)
    text = re.sub(r'\\sqrt\s*\{([^}]+)\}', r'√(\1)', text)
    text = re.sub(r'\\sqrt\s+([a-zA-Z0-9]+)', r'√\1', text)

    # 4. 符号与运算符替换
    text = re.sub(r'\\hat\{([a-zA-Z0-9]+)\}', r'\1̂', text)
    text = re.sub(r'\\hat\s+([a-zA-Z0-9]+)', r'\1̂', text)
    replacements = [
        (r'\\cdot', '·'),
        (r'\\times', '×'),
        (r'\\div', '÷'),
        (r'\\pm', '±'),
        (r'\\sum', '∑'),
        (r'\\prod', '∏'),
        (r'\\log', 'log'),
        (r'\\exp', 'exp'),
        (r'\\nabla', '∇'),
        (r'\\partial', '∂'),
        (r'\\infty', '∞'),
        (r'\\approx', '≈'),
        (r'\\neq', '≠'),
        (r'\\ne\b', '≠'),
        (r'\\geq', '≥'),
        (r'\\leq', '≤'),
        (r'\\ge\b', '≥'),
        (r'\\le\b', '≤'),
        (r'\\to\b', '→'),
        (r'\\rightarrow\b', '→'),
        (r'\\leftarrow\b', '←'),
        (r'\\Rightarrow\b', '⇒'),
        (r'\\Leftarrow\b', '⇐'),
        (r'\\alpha\b', 'α'),
        (r'\\beta\b', 'β'),
        (r'\\gamma\b', 'γ'),
        (r'\\delta\b', 'δ'),
        (r'\\epsilon\b', 'ε'),
        (r'\\zeta\b', 'ζ'),
        (r'\\eta\b', 'η'),
        (r'\\theta\b', 'θ'),
        (r'\\iota\b', 'ι'),
        (r'\\kappa\b', 'κ'),
        (r'\\lambda\b', 'λ'),
        (r'\\mu\b', 'μ'),
        (r'\\nu\b', 'ν'),
        (r'\\xi\b', 'ξ'),
        (r'\\pi\b', 'π'),
        (r'\\rho\b', 'ρ'),
        (r'\\sigma\b', 'σ'),
        (r'\\tau\b', 'τ'),
        (r'\\phi\b', 'φ'),
        (r'\\chi\b', 'χ'),
        (r'\\psi\b', 'ψ'),
        (r'\\omega\b', 'ω'),
        (r'\\Delta\b', 'Δ'),
        (r'\\Theta\b', 'Θ'),
        (r'\\Lambda\b', 'Λ'),
        (r'\\Sigma\b', 'Σ'),
        (r'\\Phi\b', 'Φ'),
        (r'\\Psi\b', 'Ψ'),
        (r'\\Omega\b', 'Ω'),
        (r'\\Gamma\b', 'Γ'),
        (r'\\Pi\b', 'Π'),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)

    # 5. 转义转义符清理与残留反斜杠
    text = re.sub(r'\\([_%\&#])', r'\1', text)
    text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)
    text = re.sub(r'\[\s*([^\]]*?=\s*[^\]]*?)\s*\]', r'\1', text)

    # 6. 剥离行内 $...$ 数学标记（例如 $K$, $x_i$, $p(x_i) ≥ draft(x_i)$），保护普通货币
    def _strip_dollar_math(match):
        inner = match.group(1).strip()
        # 保护金额数字如 $100, $50.5 元
        if re.match(r'^\d+(\.\d+)?(\s*元|\s*美元|\s*RMB)?$', inner):
            return f"${inner}$"
        return inner

    text = re.sub(r'(?<!\\)\$([^\$\n]+?)(?<!\\)\$', _strip_dollar_math, text)
    return text


def process_article_content(article_text, publisher, use_ai_first=False, skip_photo_images=False, generate_diagrams=False):
    from core.shared.runtime import check_cancelled
    check_cancelled()
    if not article_text:
        return "", {"word_count": 0, "image_count": 0, "sensitive_words": []}

    lines = article_text.strip().splitlines()
    if len(lines) >= 2 and lines[0].strip() in ("```markdown", "```") and lines[-1].strip() == "```":
        # 确保中间没有未配对的单独 ``` 冲突，再解包
        cleaned = "\n".join(lines[1:-1]).strip()
    else:
        cleaned = article_text.strip()

    # 自动修复 LLM 未在代码块前插入空行的低级格式问题 (Anti-Missing-Blankline)
    cleaned = re.sub(r'([^\n])\n(```[a-zA-Z]*)', r'\1\n\n\2', cleaned)
    for pattern in _STRUCTURAL_LABEL_PATTERNS:
        cleaned = pattern.sub('', cleaned)

    # 清理并转换原生 LaTeX 数学代码
    cleaned = _clean_latex_math(cleaned)

    # ---- 粗体兜底：如果 LLM 未输出足够粗体，自动标注关键语句 ----
    bold_count = len(re.findall(r'\*\*[^*]+\*\*', cleaned))
    if bold_count < 5:
        # 自动加粗：带单位的数字（如 3400 亿美元、50%、10 倍）
        cleaned = re.sub(
            r'(?<!\*)\b(\d[\d,.]*\s*(?:亿|万|千|百|倍|%|美元|元|人民币|欧元|英镑|日元|亿美元|万元))\b(?!\*)',
            r'**\1**', cleaned
        )
        # 自动加粗：引号内的关键短句（3-15 字的引用）
        cleaned = re.sub(
            r'(?<!\*)["“]([^"”]{3,15})["”](?!\*)',
            r'**"\1"**', cleaned
        )

    # 重点分级：识别红字重点，自动剥离可能存在的多层花括号 (Anti-Brace-Overflow)
    cleaned = re.sub(r'\*\*\{+(.*?)\}+\*\*', r'<redbold>\1</redbold>', cleaned)

    # ---- 修复低级格式错误 (Anti-Low-Level-Errors V2) ----
    # 1. 修复冒号出现在行首的问题：将行首的冒号合并到上一行末尾
    #    负向前瞻 (?!\d) 避免破坏时间戳（如 10:30）和比例（如 3:1）
    cleaned = re.sub(r'\n\s*[:：](?!\d)', '：', cleaned)

    # 1b. 修复加粗文本后换行再跟冒号的情况（如 **概念**\n：解释）
    cleaned = re.sub(r'(\*\*[^*]+\*\*)\s*\n\s*[:：](?!\d)', r'\1：', cleaned)
    
    # 2. 修复空列表项：移除只有列表符号但没内容的行（含空白字符）
    cleaned = re.sub(r'^\s*[-*+]\s*$', '', cleaned, flags=re.MULTILINE)
    
    # 2b. 修复列表符号后只有空格/标点但无实质内容的行
    cleaned = re.sub(r'^\s*[-*+]\s*[：:。，,]\s*$', '', cleaned, flags=re.MULTILINE)
    
    # 3. 修复列表项内部的换行问题：如果列表符号后面紧跟换行，则合并
    #    使用 [ \t]* 而非 \s* 避免吞噬列表项之间的空行导致合并不同列表项
    cleaned = re.sub(r'([-*+]\s*)\n[ \t]*', r'\1', cleaned)

    # 4. 移除多余的空行（连续 3 个及以上合并为 2 个）
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    
    # 5. 修复标题后紧跟冒号的问题（如 ## 标题：）
    cleaned = re.sub(r'^(#{1,4}\s+[^\n]+)[:：]\s*$', r'\1', cleaned, flags=re.MULTILINE)
    # ---------------------------------------------

    cleaned, hit_words = filter_sensitive(cleaned)
    if hit_words:
        logger.warning("  检测到敏感词: {}", hit_words)

    # 科普长文模式：强制清除所有普通照片/AI生图占位符，仅保留图表占位符
    if skip_photo_images:
        stripped_count = len(PLACEHOLDER_PATTERN.findall(cleaned))
        if stripped_count > 0:
            logger.info("  [skip_photo_images] 清除 {} 个照片配图占位符（仅保留图表）", stripped_count)
            cleaned = PLACEHOLDER_PATTERN.sub('', cleaned)
        # 同时清除 GitHub 配图占位符（科普长文不需要）
        cleaned = GITHUB_IMAGE_PATTERN.sub('', cleaned)

    placeholders = _extract_image_placeholders(cleaned)

    github_images = []
    seen_gh = set()
    for match in GITHUB_IMAGE_PATTERN.findall(cleaned or ""):
        url = match.strip()
        if url and url not in seen_gh:
            seen_gh.add(url)
            github_images.append(url)

    logger.info("  配图诊断: 普通占位符={}, GitHub配图={}", len(placeholders), len(github_images))

    html_body = markdown.markdown(cleaned, extensions=["fenced_code", "tables", "sane_lists"])

    # 更加鲁棒地移除占位符周围的 P 标签（兼容带 class/style 属性的 p 标签及多行嵌套）
    CARD_REGEX_PATTERN = r'[【\[]\s*(?:此处绘制图表|此处插入配图|此处绘制架构图|此处绘制流程图|此处绘制示意图|此处绘制逻辑图|此处绘制|配图|图表|图片|插图|Chart|Diagram|Image)[^：:\n\]】]*[：:]?\s*(.*?)\s*[】\]]'

    html_body = re.sub(
        r'<p[^>]*>\s*(' + CARD_REGEX_PATTERN + r')\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )
    html_body = re.sub(
        r'<p[^>]*>\s*(【\s*GITHUB配图\s*[：:].*?\s*】)\s*</p>',
        r'\1',
        html_body,
        flags=re.DOTALL
    )

    image_results = {}
    if placeholders:
        check_cancelled()
        logger.info("启动并行图片下载+上传引擎 ({} 张)...", len(placeholders))
        with ThreadPoolExecutor(max_workers=min(3, len(placeholders))) as executor:
            futures = {executor.submit(_download_and_upload, kw, publisher, use_ai_first): kw for kw in placeholders}
            for future in as_completed(futures):
                try:
                    keyword, image_url = future.result()
                    image_results[keyword] = image_url
                except Exception as exc:
                    logger.warning("  并行图片处理异常: {}", exc)

    image_count = 0
    for keyword in placeholders:
        image_url = image_results.get(keyword)
        if image_url:
            image_html = (
                '<p style="text-align:center;margin: 20px 0;">'
                f'<img src="{image_url}" style="width:100%;max-width:600px;border-radius:12px;'
                'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                "</p>"
            )
            html_body = _replace_placeholder(html_body, keyword, image_html)
            image_count += 1
            logger.info("  配图已成功嵌入文章")
        else:
            html_body = _replace_placeholder(html_body, keyword, "")
            logger.info("  最终未匹配到合适配图，已移除占位符")

    # GitHub 配图并行下载上传
    if github_images:
        check_cancelled()
        def _process_gh_image(gh_url):
            tmp_path = None
            try:
                logger.info("正在下载 GitHub 配图: {}", gh_url)
                res = requests.get(gh_url, timeout=10)
                if res.status_code == 200:
                    tmp_path = os.path.join("assets", f"gh_{int(time.time()*1000)}_{id(gh_url)}.jpg")
                    with open(tmp_path, 'wb') as f:
                        f.write(res.content)
                    image_url = publisher.upload_news_image(tmp_path)
                    return gh_url, image_url
            except Exception as e:
                logger.warning("  GitHub 配图处理失败: {}", e)
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
            return gh_url, None

        logger.info("并行处理 {} 张 GitHub 配图...", len(github_images))
        with ThreadPoolExecutor(max_workers=min(3, len(github_images))) as gh_pool:
            gh_results = list(gh_pool.map(_process_gh_image, github_images))

        for gh_url, image_url in gh_results:
            pattern = re.compile(rf"【GITHUB配图：\s*{re.escape(gh_url)}】")
            if image_url:
                image_html = (
                    '<p style="text-align:center;margin: 20px 0;">'
                    f'<img src="{image_url}" style="width:100%;max-width:600px;border-radius:12px;'
                    'box-shadow: 0 4px 12px rgba(0,0,0,0.1);">'
                    "</p>"
                )
                html_body = pattern.sub(lambda m: image_html, html_body)
                image_count += 1
                logger.info("  GitHub 配图已成功嵌入文章")
            else:
                html_body = pattern.sub("", html_body)

    # ---- 技术图表处理（支持关闭 LLM 图表代码生成与 Selenium 渲染，节约 Token） ----
    if generate_diagrams:
        try:
            from utils.diagram_gen import process_diagram_placeholders
            html_body, diagram_count = process_diagram_placeholders(html_body, publisher)
            if diagram_count > 0:
                image_count += diagram_count
                logger.info("  📐 图表生成完成: {} 张", diagram_count)
        except ImportError:
            logger.debug("  diagram_gen 模块不可用，跳过图表生成")
        except Exception as e:
            logger.warning("  图表生成失败: {}", e)
    else:
        # 当关闭自动代码绘图时，将【此处绘制图表：...】及变体直接转为合规精致的「AI 绘图提示词卡片」（零 Token 消耗、零浏览器启动）
        card_matches = re.findall(CARD_REGEX_PATTERN, html_body, flags=re.DOTALL)
        if card_matches:
            image_count += len(card_matches)

        def _format_diagram_card(match):
            desc = match.group(1).strip()
            return (
                '<section style="margin: 24px 0; padding: 14px 18px; background-color: #f8fafc; '
                'border-left: 4px solid #2563eb; border-radius: 8px; border: 1px solid #e2e8f0; border-left: 4px solid #2563eb;">'
                '<div style="font-size: 13.5px; color: #2563eb; font-weight: bold; margin-bottom: 6px;">'
                '🎨 AI 配图提示词卡片（待网页端生图人工替换）</div>'
                f'<div style="font-size: 13px; color: #475569; line-height: 1.6;">{desc}</div>'
                '</section>'
            )

        html_body = re.sub(
            r'【\s*(?:此处绘制图表|此处插入配图|此处绘制架构图|此处绘制流程图|配图|图表)\s*[：:]\s*(.*?)\s*】',
            _format_diagram_card,
            html_body,
            flags=re.DOTALL
        )

    # 统一增加段落缩进和间距 (统一设计系统：高清深灰文本)
    html_body = html_body.replace(
        '<p>', 
        '<p style="margin-bottom: 16px; line-height: 1.85; text-align: justify; font-size: 16px; color: #334155;">'
    )
    
    # 统一引用块样式 (科技蓝轻量阴影卡片)，并防止单次引用超过 220 字（微信单次引用不能超过 300 字限制）
    bq_style = (
        'margin: 22px 0; padding: 16px 20px; border-left: 4px solid #2563eb; '
        'background-color: #f8fafc; color: #475569; border-radius: 8px; font-size: 15px; '
        'line-height: 1.75; border: 1px solid #e2e8f0; border-left: 4px solid #2563eb;'
    )
    def _format_blockquote(match):
        content = match.group(1).strip()
        clean_text = re.sub(r'<[^>]+>', '', content)
        if len(clean_text) <= 220:
            return f'<blockquote style="{bq_style}">{content}</blockquote>'
        
        # 自动拆分超长引用（> 220 字），防止触发微信单次引用不超过 300 字的拦截
        sentences = re.split(r'(?<=[。！!？?\n])', content)
        chunks = []
        curr = ""
        for s in sentences:
            if not s.strip():
                continue
            if len(curr) + len(s) > 180 and curr.strip():
                chunks.append(curr.strip())
                curr = s
            else:
                curr += s
        if curr.strip():
            chunks.append(curr.strip())
        
        res = [f'<blockquote style="{bq_style}">{c}</blockquote>' for c in chunks]
        return "\n".join(res)

    html_body = re.sub(
        r'<blockquote>(.*?)</blockquote>',
        _format_blockquote,
        html_body,
        flags=re.DOTALL
    )

    # 统一 H2 标题样式 (左侧蓝条 + 渐变微光底色)
    html_body = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="margin-top: 38px; margin-bottom: 22px; padding: 8px 14px; border-left: 5px solid #2563eb; background: linear-gradient(90deg, rgba(37,99,235,0.08) 0%, rgba(255,255,255,0) 100%); border-radius: 4px; font-size: 21px; color: #1e293b; font-weight: bold;">\1</h2>',
        html_body
    )

    # 统一 H3 标题样式
    html_body = re.sub(
        r'<h3>(.*?)</h3>',
        r'<h3 style="margin-top: 28px; margin-bottom: 16px; font-size: 17.5px; color: #2563eb; font-weight: bold; border-left: 3px solid #3b82f6; padding-left: 10px;">\1</h3>',
        html_body
    )

    # 统一无序列表样式
    html_body = html_body.replace(
        '<ul>',
        '<ul style="margin-bottom: 20px; padding-left: 25px; line-height: 1.85; color: #334155;">'
    )

    # 重点分级样式：红色加粗微光卡片（最核心顿悟时刻） → 黑色加粗徽章（重要术语）
    html_body = html_body.replace(
        '<redbold>', '<strong style="color: #e11d48; background-color: #ffe4e6; padding: 2px 6px; border-radius: 4px; font-weight: bold; border: 1px solid #fecdd3;">'
    ).replace(
        '</redbold>', '</strong>'
    )
    html_body = re.sub(
        r'<strong>(.*?)</strong>',
        r'<strong style="color: #0f172a; font-weight: bold; background-color: rgba(241,245,249,0.8); padding: 1px 4px; border-radius: 3px;">\1</strong>',
        html_body
    )

    # 优化多行代码块 (<pre><code>) 样式：渲染为 Mac 终端暗黑高档风格 (微信防剥离双重防护)
    mac_dots = '<div style="display:flex;align-items:center;gap:6px;margin-bottom:10px;"><span style="width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block;"></span><span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;display:inline-block;"></span><span style="width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block;"></span></div>'
    
    def _format_code_block(match):
        code_content = match.group(1)
        return (
            '<section style="margin: 20px 0; padding: 16px 18px; background-color: #1e293b; color: #f8fafc; '
            'border-radius: 12px; font-family: Consolas, Monaco, \'Courier New\', monospace; '
            'font-size: 13.5px; line-height: 1.65; overflow-x: auto; box-shadow: 0 6px 18px rgba(0,0,0,0.25); display: block;">'
            f'{mac_dots}'
            f'<pre style="margin: 0; padding: 0; background-color: #1e293b; color: #f8fafc; '
            f'font-family: Consolas, Monaco, \'Courier New\', monospace; font-size: 13.5px; line-height: 1.65; '
            f'white-space: pre-wrap; word-break: break-all; border: none; background: #1e293b; display: block;">{code_content}</pre>'
            '</section>'
        )

    html_body = re.sub(
        r'<pre>\s*<code[^>]*>(.*?)</code>\s*</pre>',
        _format_code_block,
        html_body,
        flags=re.DOTALL
    )

    # 统一行内代码（英文字体）样式：由于多行代码块已替换为 <pre>，剩下的 <code> 均为行内代码
    font_stack = "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', Arial, sans-serif"
    html_body = re.sub(
        r'<code>(.*?)</code>',
        f'<code style="font-family: {font_stack}; background-color: #f1f5f9; padding: 2px 5px; border-radius: 4px; color: #2563eb; font-size: 0.95em;">\\1</code>',
        html_body
    )

    word_count = len(cleaned.replace("\n", "").replace(" ", ""))
    html_bytes = len(html_body.encode('utf-8'))
    return html_body, {
        "word_count": word_count,
        "image_count": image_count,
        "sensitive_words": hit_words,
        "html_bytes": html_bytes,
    }


def cleanup_old_assets(base_dir="assets", max_age_days=ASSET_RETENTION_DAYS):
    if not os.path.exists(base_dir):
        return

    now = time.time()
    cutoff = now - max_age_days * 86400
    removed_count = 0
    removed_dirs = 0

    for root, dirs, files in os.walk(base_dir, topdown=False):
        for filename in files:
            if filename.startswith("default_"):
                continue
            filepath = os.path.join(root, filename)
            try:
                if os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
                    removed_count += 1
            except OSError as e:
                logger.debug("  清理文件失败 {}: {}", filepath, e)

        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            try:
                if not os.listdir(dirpath):
                    os.rmdir(dirpath)
                    removed_dirs += 1
            except OSError as e:
                logger.debug("  清理目录失败 {}: {}", dirpath, e)

    if removed_count > 0:
        logger.info(
            "🧹 自动清理：已删除 {} 个过期文件和 {} 个空目录 (>{}天)",
            removed_count,
            removed_dirs,
            max_age_days,
        )

def _print_banner():
    print("\n" + "=" * 60)
    print(f"  🚀 「{BRAND_NAME}」全自动 AI 内容工厂 v6.0")
    print("=" * 60 + "\n")

def _print_review_report(title, word_count, image_count, sensitive_words, cover_ok, digest, is_long_article=False, ignore_word_count=False, html_bytes=0):
    print(f"\n{'─' * 50}")
    print("  📋 发布前审核报告")
    print(f"{'─' * 50}")

    title_ok = len(title) <= WECHAT_TITLE_MAX_LEN
    title_icon = "✅" if title_ok else "⚠️"
    print(f"  标题：{title} ({len(title)} 字 {title_icon})")

    if ignore_word_count:
        wc_ok = True
    elif is_long_article:
        wc_ok = word_count >= 15000
    else:
        wc_ok = 2000 <= word_count <= 4000
    wc_icon = "✅" if wc_ok else "⚠️"
    print(f"  字数：{word_count:,} 字 ({wc_icon})")

    bytes_ok = (html_bytes == 0) or (html_bytes <= 10 * 1024 * 1024)
    bytes_icon = "✅" if bytes_ok else "❌"
    if html_bytes > 0:
        print(f"  正文体积：{html_bytes / (1024 * 1024):.2f} MB ({bytes_icon} ≤10MB)")

    image_icon = "✅" if image_count >= 3 else "⚠️"
    print(f"  配图：{image_count} 张 ({image_icon})")

    sensitive_icon = "❌" if sensitive_words else "✅"
    sensitive_msg = f"命中 {len(sensitive_words)} 词: {sensitive_words}" if sensitive_words else "无"
    print(f"  敏感词：{sensitive_msg} ({sensitive_icon})")

    cover_icon = "✅" if cover_ok else "⚠️"
    print(f"  封面图：{'已上传' if cover_ok else '未上传'} ({cover_icon})")

    if digest:
        print(f"  摘要：{digest[:80]}{'...' if len(digest) > 80 else ''}")

    all_ok = title_ok and wc_ok and bytes_ok and image_count >= 3 and not sensitive_words and cover_ok
    print(f"{'─' * 50}")
    print("  🎉 审核通过，可以发布！" if all_ok else "  ⚠️ 存在警告项，请手动检查后再发布。")
    print(f"{'─' * 50}\n")
    return all_ok
