import os
import re
import time
from html import unescape
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
import markdown
import requests
from loguru import logger

from config import BRAND_NAME, WECHAT_TITLE_MAX_LEN, ASSET_RETENTION_DAYS
from core.shared.llm import filter_sensitive

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


def _extract_image_placeholders(article_text):
    """提取文章中按顺序排列的所有配图占位符关键词（保留位置与重复项）"""
    placeholders = []
    for match in PLACEHOLDER_PATTERN.findall(article_text or ""):
        placeholders.append(match.strip())
    return placeholders


def _replace_placeholder(html_body, keyword, replacement):
    # 替换单个占位符（首个匹配项）
    pattern = re.compile(rf"【\s*此处插入配图\s*[：:]\s*{re.escape(keyword)}\s*】")
    return pattern.sub(replacement, html_body, count=1)

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


CALLOUT_PATTERN = re.compile(
    r'^\s*(?:<p[^>]*>\s*)?'
    r'(?:(⚠️|💡|📌)\s*)?'
    r'(?:<strong>|\*\*)?\s*'
    r'(避坑指南(?:\s*/\s*风险预警)?|风险预警|风险提示|核心洞察|核心观点|深度洞察|行动清单|实操清单|行动指南|落地清单)'
    r'\s*(?:</strong>|\*\*)?\s*[:：]?(?:\s*</p>)?',
    flags=re.IGNORECASE
)


def _determine_callout_type(title_text: str, icon: str = None) -> str:
    """根据标题文本或图标判断微光卡片类型"""
    if any(k in title_text for k in ["避坑", "风险"]) or icon == "⚠️":
        return "warning"
    elif any(k in title_text for k in ["洞察", "观点"]) or icon == "💡":
        return "insight"
    elif any(k in title_text for k in ["清单", "行动", "实操", "落地"]) or icon == "📌":
        return "action"
    return "warning"


def _build_callout_card(callout_type: str, icon: str, title: str, body: str) -> str:
    """构建微光卡片 HTML"""
    configs = {
        "warning": {
            "border_color": "#ef4444",
            "bg_color": "#fef2f2",
            "border_outer": "#fee2e2",
            "default_icon": "⚠️",
            "default_title": "避坑指南 / 风险预警",
        },
        "insight": {
            "border_color": "#3b82f6",
            "bg_color": "#eff6ff",
            "border_outer": "#dbeafe",
            "default_icon": "💡",
            "default_title": "核心洞察",
        },
        "action": {
            "border_color": "#10b981",
            "bg_color": "#f0fdf4",
            "border_outer": "#d1fae5",
            "default_icon": "📌",
            "default_title": "行动清单",
        },
    }
    cfg = configs.get(callout_type, configs["warning"])
    b_color = cfg["border_color"]
    bg = cfg["bg_color"]
    border_outer = cfg["border_outer"]
    use_icon = icon or cfg["default_icon"]
    use_title = title or cfg["default_title"]

    if body and not body.startswith("<p") and not body.startswith("<ol") and not body.startswith("<ul"):
        body_html = f'<div style="font-size: 14.5px; color: #334155; line-height: 1.75;">{body}</div>'
    else:
        body_html = f'<div style="font-size: 14.5px; color: #334155; line-height: 1.75;">{body}</div>' if body else ''

    return (
        f'<section style="margin: 22px 0; padding: 16px 20px; background-color: {bg}; '
        f'border: 1px solid {border_outer}; border-left: 4px solid {b_color}; border-radius: 10px; '
        f'font-size: 15px; line-height: 1.75; color: #334155; box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.04);">'
        f'<div style="font-size: 14.5px; color: {b_color}; font-weight: bold; margin-bottom: 8px; '
        f'display: flex; align-items: center; gap: 6px;">'
        f'<span>{use_icon}</span> <span>{use_title}</span>'
        f'</div>'
        f'{body_html}'
        f'</section>'
    )


def _render_custom_callouts(text: str) -> str:
    """
    微光引用容器语法映射：
    - > ⚠️ **避坑指南 / 风险预警**：-> 渲染为琥珀红告警卡片（#ef4444 / 浅红底 #fef2f2）
    - > 💡 **核心洞察**：-> 渲染为微光极客蓝卡片（#3b82f6 / 浅蓝底 #eff6ff）
    - > 📌 **行动清单**：-> 渲染为墨绿徽章卡片（#10b981 / 浅绿底 #f0fdf4）
    支持 Markdown 原文与解析后的 HTML <blockquote> 容器。
    """
    if not text:
        return text

    # 若输入为纯 Markdown 引用语法且尚未被 blockquote 包装，先转为 HTML
    if re.search(r'(?:^|\n)\s*>\s*', text) and not re.search(r'</?(?:blockquote|section)\b', text, re.I):
        text = markdown.markdown(text, extensions=["fenced_code", "tables", "sane_lists"])

    def _replace_callout(match):
        content = match.group(1).strip()
        m = CALLOUT_PATTERN.search(content)
        if not m:
            return match.group(0)

        icon = m.group(1)
        title = m.group(2)
        callout_type = _determine_callout_type(title, icon)
        body = content[m.end():].strip()
        if body.endswith("</p>") and not body.startswith("<p"):
            body = body[:-4].strip()
        if body.startswith("<p>") and body.endswith("</p>") and body.count("<p>") == 1:
            body = body[3:-4].strip()
        if body.startswith("：") or body.startswith(":"):
            body = body[1:].strip()
        if "<p>" not in body and "<ol>" not in body and "<ul>" not in body:
            body = body.replace("\n", "<br>")

        return _build_callout_card(callout_type, icon, title, body)

    return re.sub(r'<blockquote[^>]*>(.*?)</blockquote>', _replace_callout, text, flags=re.DOTALL)


def _format_markdown_tables(html_body: str) -> str:
    """为 markdown 生成的 <table> 注入微信兼容的 Linear Modern Light 行内样式与横向滚动保护"""
    if "<table" not in html_body:
        return html_body

    table_style = (
        "border-collapse: collapse; width: 100%; margin: 0; font-size: 14px; "
        "border: 1px solid #E2E8F0; border-radius: 8px; overflow: hidden; "
        "background-color: #FFFFFF;"
    )
    th_base_style = (
        "background-color: #F8F9FB; color: #0C0D0E; font-weight: 600; "
        "padding: 10px 14px; border-bottom: 1px solid #E2E8F0;"
    )
    td_base_style = (
        "padding: 10px 14px; border-bottom: 1px solid #F1F3F7; color: #334155; "
        "line-height: 1.6;"
    )

    def _merge_style(tag_attrs: str, new_style: str) -> str:
        m = re.search(r'style="([^"]*)"', tag_attrs)
        if m:
            existing = m.group(1).strip()
            if existing and not existing.endswith(';'):
                existing += ';'
            merged = f"{existing} {new_style}".strip()
            return tag_attrs[:m.start()] + f'style="{merged}"' + tag_attrs[m.end():]
        else:
            return f'{tag_attrs} style="{new_style}"'

    def _replace_table(match):
        table_content = match.group(0)
        table_content = re.sub(
            r'<th\b([^>]*)>',
            lambda m: f"<th{_merge_style(m.group(1), th_base_style)}>",
            table_content
        )
        table_content = re.sub(
            r'<td\b([^>]*)>',
            lambda m: f"<td{_merge_style(m.group(1), td_base_style)}>",
            table_content
        )
        table_content = re.sub(
            r'<table\b([^>]*)>',
            lambda m: f"<table{_merge_style(m.group(1), table_style)}>",
            table_content,
            count=1
        )
        return f'<section style="width: 100%; margin: 22px 0; overflow-x: auto; box-sizing: border-box;">{table_content}</section>'

    return re.sub(r'<table\b[^>]*>.*?</table>', _replace_table, html_body, flags=re.DOTALL)


REDBOLD_STRONG_STYLE = (
    "color: #e11d48; background-color: #ffe4e6; padding: 2px 6px; "
    "border-radius: 4px; font-weight: bold; border: 1px solid #fecdd3;"
)
BLACKBOLD_STRONG_STYLE = (
    "color: #0C0D0E; font-weight: bold; background-color: rgba(79,91,213,0.13); "
    "padding: 1px 5px; border-radius: 4px;"
)

_PROTECTED_SPAN_PATTERN = re.compile(
    r'```[\s\S]*?```'
    r'|<redbold>[\s\S]*?</redbold>'
    r'|<blockquote\b[\s\S]*?</blockquote>'
    r'|<section\b[\s\S]*?</section>'
    r'|<table\b[\s\S]*?</table>'
    r'|<h[1-6]\b[\s\S]*?</h[1-6]>'
    r'|<pre\b[\s\S]*?</pre>'
    r'|<code\b[\s\S]*?</code>'
    r'|<strong\b[\s\S]*?</strong>'
    r'|\*\*\{+[\s\S]*?\}+\*\*'
    r'|<[^>]+>'
    r'|&[a-zA-Z0-9#]+;'
    r'|^[ \t]*>[^\n]*'
    r'|^[ \t]*#{1,6}[ \t]+[^\n]*'
    r'|\*\*[^*\n]+\*\*'
    r'|(?<!\*)\*[^*\n]+\*(?!\*)'
    r'|`[^`\n]+`'
    r'|【[^】\n]+】'
    r'|https?://[^\s)>\]」》"\']+',
    flags=re.MULTILINE,
)

_NUMBER_UNIT_PATTERN = re.compile(
    r'(?<![\d.\*a-zA-Z\uE000-\uE01F])'
    r'(\d[\d,.]*\s*(?:'
    r'(?:万亿|千亿|百亿|十亿|千万|百万|十万|亿|万|千|百)\s*(?:人民币|美元|欧元|英镑|日元|港元|千瓦时|公里|千米|纳米|毫米|厘米|米|吨|台|颗|枚|座|家|个|项|次|倍|元)'
    r'|亿美元|万美元|万亿元|万元|人民币|美元|欧元|英镑|日元|港元|千瓦时|百分比|公里|千米|纳米|毫米|厘米|米|吨|台|颗|枚|座|家|个|项|次|倍|元|%|GB|TB|MB|PB|GW|MW|kW|nm|GHz|MHz'
    r'|万亿|千亿|百亿|十亿|千万|百万|十万|亿|万'
    r'))'
    r'(?![\d.%*a-zA-Z\uE000-\uE01F])'
)
_QUOTED_PHRASE_PATTERN = re.compile(r'“([^“”\n\uE000\uE001]{2,15})”|"([^"\n\uE000\uE001]{2,15})"')
_BULLET_COLON_PATTERN = re.compile(r'^([ \t]*(?:[-*+]|\d+\.)[ \t]+)([^：\n*<\uE000\uE001]{2,16})(：)', flags=re.MULTILINE)
_STANDALONE_PUNCHLINE_PATTERN = re.compile(r'^([ \t]*)([^>\n#*【`\-•\d<\uE000\uE001][^>\n*<\uE000\uE001]{5,28}[。！])([ \t]*)$', flags=re.MULTILINE)
_SIGNATURE_LINE_PATTERN = re.compile(r'^([ \t]*)(关注「[^」\n]{1,30}」[^\n*<\uE000\uE001]{0,30}[。！!]?)([ \t]*)$', flags=re.MULTILINE)


def extract_redbold_tags(text: str) -> str:
    """识别 **{{红字重点}}** 并剥离多余花括号，转换为 <redbold> 临时标记"""
    if not text:
        return text
    return re.sub(r'\*\*\{+(.*?)\}+\*\*', r'<redbold>\1</redbold>', text)


def count_black_bold(text: str) -> int:
    """统计正文中的普通黑色加粗数量（排除红字重点 **{{...}}** / <redbold> / #e11d48 与标题）"""
    if not text:
        return 0
    stripped = re.sub(r'<redbold>[\s\S]*?</redbold>', '', text)
    stripped = re.sub(r'\*\*\{+[\s\S]*?\}+\*\*', '', stripped)
    stripped = re.sub(r'<strong\b[^>]*#e11d48[^>]*>[\s\S]*?</strong>', '', stripped, flags=re.IGNORECASE)
    stripped_body = re.sub(r'^[ \t]*#{1,6}[ \t]+.*$', '', stripped, flags=re.MULTILINE)
    stripped_body = re.sub(r'<h[1-6]\b[^>]*>[\s\S]*?</h[1-6]>', '', stripped_body, flags=re.IGNORECASE)
    md_bolds = len(re.findall(r'\*\*[^*\n]+\*\*', stripped_body))
    html_bolds = len(re.findall(r'<strong\b[^>]*>[\s\S]*?</strong>', stripped_body, flags=re.IGNORECASE))
    return md_bolds + html_bolds


def _replace_outside_protected(text: str, transform_fn) -> str:
    """仅对非代码块、非标题、非标签、非引用块、非链接、非已加粗/红字的纯正文字段执行替换（保留完整行边界）"""
    if not text:
        return text
    protected_tokens = []

    def _stash(match):
        idx = len(protected_tokens)
        protected_tokens.append(match.group(0))
        encoded = "".join(chr(0xE010 + int(ch)) for ch in str(idx))
        return f"\uE000{encoded}\uE001"

    masked = _PROTECTED_SPAN_PATTERN.sub(_stash, text)
    transformed = transform_fn(masked)
    if not protected_tokens:
        return transformed

    def _restore(match):
        digits = "".join(str(ord(ch) - 0xE010) for ch in match.group(0)[1:-1])
        idx = int(digits)
        return protected_tokens[idx] if idx < len(protected_tokens) else match.group(0)

    return re.sub(r"\uE000[\uE010-\uE019]+\uE001", _restore, transformed)


def _apply_bold_fallback(text: str, as_html: bool = False) -> str:
    """
    黑色粗体兜底：在排除红色重点后，若正文中普通黑色加粗仍偏少，
    依次补充：1) 关键数字+单位，2) 引号短语，3) 列表标签/独立金句/品牌落款。
    """
    if not text:
        return text

    def _wrap(content: str) -> str:
        if as_html:
            return f'<strong style="{BLACKBOLD_STRONG_STYLE}">{content}</strong>'
        return f'**{content}**'

    # 始终顺手加粗未加粗的文末品牌关注语（独立成行或段落末尾）
    text = _replace_outside_protected(
        text,
        lambda seg: _SIGNATURE_LINE_PATTERN.sub(lambda m: f"{m.group(1)}{_wrap(m.group(2))}{m.group(3)}", seg),
    )

    plain_text = re.sub(r'<[^>]+>', '', text)
    chinese_chars = len(re.findall(r'[\u4e00-\u9fa5]', plain_text))
    target_min = 5 if chinese_chars < 600 else 10

    if count_black_bold(text) >= target_min:
        return text

    # Tier 1: 带单位的关键数字/百分比（适配中文无空格邻接）
    added_t1 = 0

    def _sub_numbers(seg: str) -> str:
        nonlocal added_t1

        def _rep(m):
            nonlocal added_t1
            if added_t1 >= 15:
                return m.group(0)
            added_t1 += 1
            return _wrap(m.group(1))

        return _NUMBER_UNIT_PATTERN.sub(_rep, seg)

    text = _replace_outside_protected(text, _sub_numbers)
    if count_black_bold(text) >= target_min:
        return text

    # Tier 2: 引号内的关键概念/短语（2-15 字）
    added_t2 = 0
    needed_t2 = max(0, max(target_min, 10) - count_black_bold(text))

    def _sub_quotes(seg: str) -> str:
        nonlocal added_t2

        def _rep(m):
            nonlocal added_t2
            if added_t2 >= min(10, needed_t2 + 2):
                return m.group(0)
            added_t2 += 1
            return _wrap(m.group(0))

        return _QUOTED_PHRASE_PATTERN.sub(_rep, seg)

    text = _replace_outside_protected(text, _sub_quotes)
    if count_black_bold(text) >= target_min:
        return text

    # Tier 3: 列表冒号标签与短小核心结论句（针对无数字无引号文章）
    def _sub_bullets(seg: str) -> str:
        return _BULLET_COLON_PATTERN.sub(lambda m: f"{m.group(1)}{_wrap(m.group(2))}{m.group(3)}", seg)

    text = _replace_outside_protected(text, _sub_bullets)
    if count_black_bold(text) >= target_min:
        return text

    remaining = max(0, target_min - count_black_bold(text))

    def _sub_punchlines(seg: str) -> str:
        nonlocal remaining

        def _rep(m):
            nonlocal remaining
            if remaining <= 0:
                return m.group(0)
            remaining -= 1
            return f"{m.group(1)}{_wrap(m.group(2))}{m.group(3)}"

        return _STANDALONE_PUNCHLINE_PATTERN.sub(_rep, seg)

    text = _replace_outside_protected(text, _sub_punchlines)
    return text


def _apply_inline_strong_styles(html_body: str) -> str:
    """统一渲染红字核心重点 (<redbold>) 与黑色加粗徽章 (<strong>)"""
    html_body = html_body.replace(
        '<redbold>', f'<strong style="{REDBOLD_STRONG_STYLE}">'
    ).replace(
        '</redbold>', '</strong>'
    )
    return re.sub(
        r'<strong>([\s\S]*?)</strong>',
        lambda m: f'<strong style="{BLACKBOLD_STRONG_STYLE}">{m.group(1)}</strong>',
        html_body,
    )


def process_article_content(article_text, publisher, use_ai_first=False, skip_photo_images=False,
                            generate_diagrams=False, *, cover_title=None, github_sources=None):
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

    # 重点分级：先识别红字重点并自动剥离多余花括号，避免其虚增普通黑色加粗计数
    cleaned = extract_redbold_tags(cleaned)

    # ---- 粗体兜底：在排除红字重点后，若正文中黑色加粗仍不足则自动补标 ----
    cleaned = _apply_bold_fallback(cleaned)

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

    # 确保独立占位符行前后存在空行，避免紧跟 > 引用块时被 markdown 吞并导致 <p> 未闭合与图片被关进 <blockquote>
    cleaned = re.sub(
        r'(?m)^[ \t]*(?:>\s*)?(【\s*(?:此处插入配图|此处绘制(?:图表|架构图|流程图|示意图|逻辑图)?|GITHUB配图)\s*[：:].*?】)[ \t]*$',
        r'\n\n\1\n\n',
        cleaned,
    )
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

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

    from core.shared.article_photos import image_html, prepare_article_photos, source_caption
    photo_figures = {}
    thumb_id = None
    cover_caption = ""
    if not skip_photo_images and (placeholders or cover_title):
        photo_figures, thumb_id, cover_caption = prepare_article_photos(
            placeholders, publisher, cover_title, use_ai_first=use_ai_first,
        )

    image_count = 0
    slot_cursor = 0
    pattern_placeholder = re.compile(
        r'(?:<p[^>]*>\s*)?【\s*此处插入配图\s*[：:]\s*.*?】(?:\s*</p>)?',
        flags=re.DOTALL
    )

    def _replace_next_placeholder(match):
        nonlocal image_count, slot_cursor
        current_idx = slot_cursor
        slot_cursor += 1
        if current_idx in photo_figures:
            image_count += 1
            return photo_figures[current_idx]
        logger.info("  最终未匹配到合适配图，已移除占位符 #{}", current_idx + 1)
        return ""

    html_body = pattern_placeholder.sub(_replace_next_placeholder, html_body)
    # 平滑消除可能残留的空段落与换行断层
    html_body = re.sub(r'<p[^>]*>\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*', '', html_body)
    html_body = re.sub(r'\n{3,}', '\n\n', html_body)

    # GitHub 配图并行下载上传
    if github_images:
        check_cancelled()
        def _process_gh_image(gh_url):
            tmp_path = None
            try:
                if github_sources is not None:
                    if gh_url not in github_sources:
                        return gh_url, None
                    if urlsplit(gh_url).hostname in {"mmbiz.qpic.cn", "mmbiz.qlogo.cn"}:
                        return gh_url, gh_url
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

        uploaded = dict(gh_results)

        def replace_github_image(match):
            nonlocal image_count
            url = unescape(match.group(1)).strip()
            cdn_url = uploaded.get(url)
            if not cdn_url:
                return ""
            source = github_sources[url] if github_sources is not None else url
            image_count += 1
            return image_html(cdn_url, source_caption(source))

        html_body = GITHUB_IMAGE_PATTERN.sub(replace_github_image, html_body)

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
        # 当关闭自动代码绘图时，将【此处绘制图表：...】及变体转为优雅的「高亮分析卡片」
        DIAGRAM_CARD_PATTERN = re.compile(
            r'[【\[]\s*(?:此处绘制图表|此处绘制架构图|此处绘制流程图|此处绘制示意图|此处绘制逻辑图|此处绘制|图表|架构图|流程图|Chart|Diagram)[^：:\n\]】]*[：:]?\s*(.*?)\s*[】\]]',
            flags=re.DOTALL
        )
        card_matches = DIAGRAM_CARD_PATTERN.findall(html_body)
        if card_matches:
            logger.info("  已将 {} 个图表占位符替换为微光高亮分析卡片", len(card_matches))

        def _format_diagram_card(match):
            full_tag = match.group(0)
            desc = match.group(1).strip()
            if "流程" in full_tag:
                title = "📊 核心业务流程拆解"
            elif "架构" in full_tag:
                title = "📊 核心架构与逻辑拆解"
            elif "示意" in full_tag or "图解" in full_tag:
                title = "📊 原理图解与深度分析"
            else:
                title = "📊 核心逻辑与架构解析"

            return (
                '<section style="margin: 24px 0; padding: 18px 20px; background-color: #f8fafc; '
                'border: 1px solid #e2e8f0; border-left: 4px solid #2563eb; border-radius: 10px; '
                'box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.04);">'
                f'<div style="font-size: 14.5px; color: #2563eb; font-weight: bold; margin-bottom: 8px; '
                'display: flex; align-items: center; gap: 6px;">'
                f'<span>{title}</span>'
                '</div>'
                f'<div style="font-size: 14px; color: #334155; line-height: 1.75; text-align: justify;">{desc}</div>'
                '</section>'
            )

        html_body = DIAGRAM_CARD_PATTERN.sub(_format_diagram_card, html_body)

        # 彻底清理可能残留的遗留旧草稿提示词文本
        html_body = re.sub(
            r'🎨\s*AI\s*配图提示词卡片[（(]待网页端生图人工替换[）)]',
            '📊 核心逻辑与架构解析',
            html_body
        )

    # 渲染微光自定义引用卡片（避坑指南、核心洞察、行动清单）
    html_body = _render_custom_callouts(html_body)

    # 统一渲染 Markdown 表格行内样式与移动端防溢出保护
    html_body = _format_markdown_tables(html_body)

    # 统一增加段落缩进和间距 (统一设计系统：高清深灰文本)
    html_body = html_body.replace(
        '<p>', 
        '<p style="margin-bottom: 16px; line-height: 1.85; text-align: justify; font-size: 16px; color: #334155;">'
    )
    # 平滑消除可能残留的空段落（避免微信排版出现突兀的空行断层）
    html_body = re.sub(r'<p style="[^"]*">\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*', '', html_body)
    html_body = re.sub(r'<p[^>]*>\s*(?:&nbsp;|<br\s*/?>)?\s*</p>\s*', '', html_body)
    
    # 统一引用块样式 (Linear Light 浅灰微光卡片)，并防止单次引用超过 220 字（微信单次引用不能超过 300 字限制）
    bq_style = (
        'margin: 22px 0; padding: 16px 20px; border: 1px solid rgba(0,0,0,0.06); '
        'border-left: 4px solid #4F5BD5; background-color: #F8F9FB; color: #5E6470; '
        'border-radius: 8px; font-size: 15px; line-height: 1.75; box-shadow: 0 1px 2px rgba(0,0,0,0.02);'
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

    # 统一 H1 标题样式 (Linear Modern Light: 墨黑字体 + 底边淡灰精致分隔)
    html_body = re.sub(
        r'<h1>(.*?)</h1>',
        r'<h1 style="margin-top: 40px; margin-bottom: 24px; font-size: 24px; color: #0C0D0E; font-weight: 700; line-height: 1.4; letter-spacing: -0.02em; border-bottom: 1px solid #E2E8F0; padding-bottom: 12px;">\1</h1>',
        html_body
    )

    # 统一 H2 标题样式 (Linear Modern Light: Indigo 左侧条 + 渐变微光底色 + 墨黑字体)
    html_body = re.sub(
        r'<h2>(.*?)</h2>',
        r'<h2 style="margin-top: 38px; margin-bottom: 22px; padding: 10px 16px; border-left: 4px solid #4F5BD5; background: linear-gradient(90deg, rgba(79,91,213,0.08) 0%, rgba(248,249,251,0) 100%); border-radius: 6px; font-size: 20px; color: #0C0D0E; font-weight: 700; letter-spacing: -0.01em;">\1</h2>',
        html_body
    )

    # 统一 H3 标题样式 (Linear Indigo 子标题)
    html_body = re.sub(
        r'<h3>(.*?)</h3>',
        r'<h3 style="margin-top: 28px; margin-bottom: 16px; font-size: 17px; color: #0C0D0E; font-weight: 600; border-left: 3px solid #4F5BD5; padding-left: 10px;">\1</h3>',
        html_body
    )

    # 统一列表样式 (包含 ul, ol 以及 li 单项间距与墨深颜色)
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

    # 统一分隔线样式 (Linear Modern Light 淡灰细线)
    html_body = re.sub(
        r'<hr\s*/?>',
        '<hr style="border: none; border-top: 1px solid #E2E8F0; margin: 32px 0;">',
        html_body
    )

    # 重点分级样式：红色加粗微光卡片（最核心顿悟时刻） → 黑色加粗徽章（重要术语）
    html_body = _apply_inline_strong_styles(html_body)

    # 优化多行代码块 (<pre><code>) 样式：渲染为 Linear Modern Light Sunken Code Card (微信防剥离多层容器防护)
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

    # 统一行内代码样式：由于多行代码块已替换为 <pre>，剩下的 <code> 均为行内代码
    html_body = re.sub(
        r'<code>(.*?)</code>',
        r'<code style="font-family: Consolas, Monaco, \'Courier New\', monospace; background-color: #F1F3F7; padding: 2px 6px; border-radius: 4px; color: #4F5BD5; border: 1px solid rgba(79,91,213,0.15); font-size: 0.92em;">\1</code>',
        html_body
    )

    word_count = len(cleaned.replace("\n", "").replace(" ", ""))
    html_body += cover_caption
    html_bytes = len(html_body.encode('utf-8'))
    return html_body, {
        "word_count": word_count,
        "image_count": image_count,
        **({"thumb_id": thumb_id} if cover_title else {}),
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
        wc_ok = word_count >= 1500
    else:
        wc_ok = word_count >= 800
    wc_icon = "✅" if wc_ok else "⚠️"
    print(f"  字数：{word_count:,} 字 ({wc_icon})")

    bytes_ok = (html_bytes == 0) or (html_bytes <= 10 * 1024 * 1024)
    bytes_icon = "✅" if bytes_ok else "❌"
    if html_bytes > 0:
        print(f"  正文体积：{html_bytes / (1024 * 1024):.2f} MB ({bytes_icon} ≤10MB)")

    image_icon = "✅" if image_count >= 1 else "⚠️"
    print(f"  配图：{image_count} 张 ({image_icon})")

    sensitive_icon = "❌" if sensitive_words else "✅"
    sensitive_msg = f"命中 {len(sensitive_words)} 词: {sensitive_words}" if sensitive_words else "无"
    print(f"  敏感词：{sensitive_msg} ({sensitive_icon})")

    cover_icon = "✅" if cover_ok else "⚠️"
    print(f"  封面图：{'已上传' if cover_ok else '未上传'} ({cover_icon})")

    if digest:
        print(f"  摘要：{digest[:80]}{'...' if len(digest) > 80 else ''}")

    # 底线硬性指标：标题不超长、正文不超过10MB、无敏感词、封面图已上传
    all_ok = title_ok and bytes_ok and not sensitive_words and cover_ok
    print(f"{'─' * 50}")
    print("  🎉 格式校验通过，准予进入门禁审核！" if all_ok else "  ⚠️ 存在严重合规/格式问题，已拦截。")
    print(f"{'─' * 50}\n")
    return all_ok
