"""
主编审校 Agent 与质量把关门禁 (Critic & Quality Gate)
用于在推文发布前执行多维技术指标审查、套话识别、标题与字数检验，
并提供自动化自愈修剪 (Auto-Remediation) 闭环。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

# 涉及论断和具体语境的套话只提示审校。程序仅删除可独立去掉的段首过渡语。
_REMOVABLE_LEADS = (
    "不仅如此", "换句话说", "不得不提的是", "不可否认", "综上所述",
    "总而言之", "总的来说", "说白了", "毫无疑问", "显而易见",
)
CLICHE_PATTERNS: List[str] = [
    *_REMOVABLE_LEADS, r"在这场没有硝烟的战争中", r"在这场[^。！？]*?背后",
    r"随着[^。！？]*?飞速发展", r"随着[^。！？]*?快速演进", "不得不提(?!的是)",
    "拭目以待", "双刃剑", "既有机遇也有挑战",
]
# 保护引文和代码，同时适配 Markdown 原稿与微信 HTML。
_QUOTED_OR_CODE = (
    r'~~~[\s\S]*?~~~|```[\s\S]*?```'
    r'|<(?P<tag>blockquote|q|pre|code)\b[^>]*>[\s\S]*?</(?P=tag)>'
    r'|^[ \t]*>[^\n]*|“[^”]*”|「[^」]*」'
)
_PARAGRAPH_LEAD = re.compile(
    _QUOTED_OR_CODE +
    r'|(?P<start>^[ \t]*|<p\b[^>]*>)(?P<lead>' + '|'.join(_REMOVABLE_LEADS) + r')[，,][ \t]*(?=[^\s<])',
    flags=re.MULTILINE | re.IGNORECASE,
)
_H2 = re.compile(r'^##[ \t]+\S|<h2\b', re.MULTILINE | re.IGNORECASE)
_SECTION_LABEL = re.compile(
    _QUOTED_OR_CODE +
    r'|(?P<markdown>^###)(?=[ \t]+\S)|(?P<html></?)h3(?=[\s>])'
    r'|^\*\*(?P<label>(?!关注「)[^*{}\n。！？；]{2,32})\*\*[ \t]*$',
    flags=re.MULTILINE | re.IGNORECASE,
)


def _extract_plain_text(text: str) -> str:
    """去除 HTML 标签与格式标记以获得纯文本用于字数和套话审查"""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def auto_repair_article(article_text: str) -> Tuple[str, List[str]]:
    """
    对文稿中的 AI 刻板套话与格式缺陷执行自动化自愈修正。
    返回修复后的正文与具体执行的修复清单。
    """
    if not article_text:
        return article_text, []

    repaired = article_text
    repairs_applied = []

    def strip_lead(match):
        if match.group("lead") is None:
            return match.group()
        repairs_applied.append(f"删除段首套话「{match.group('lead')}」")
        return match.group("start")

    repaired = _PARAGRAPH_LEAD.sub(strip_lead, repaired)

    # 2. 只给已有小标题补层级，保留作者原来的措辞与输出格式。
    if len(repaired) > 1200 and not _H2.search(repaired):
        def promote_label(match):
            if match.group("markdown"):
                return "##"
            if match.group("html"):
                return match.group("html") + "h2"
            if match.group("label"):
                return "## " + match.group("label")
            return match.group()

        with_headings = _SECTION_LABEL.sub(promote_label, repaired)
        if with_headings != repaired:
            repaired = with_headings
            repairs_applied.append("将原有小标题调整为二级标题")

    # 3. 检查并补强正文黑色重点标粗（针对 0~4 处黑字加粗的长文）
    plain_text = _extract_plain_text(repaired)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", plain_text))
    if chinese_chars >= 800:
        from core.shared.article_utils import _apply_bold_fallback, count_black_bold
        before_bolds = count_black_bold(repaired)
        if before_bolds < 5:
            is_html = bool(re.search(r"<(?:p|section|blockquote|div)\b", repaired, flags=re.IGNORECASE))
            repaired = _apply_bold_fallback(repaired, as_html=is_html)
            after_bolds = count_black_bold(repaired)
            if after_bolds > before_bolds:
                repairs_applied.append(f"自动补强正文黑色重点标粗 ({before_bolds} -> {after_bolds} 处)")

    return repaired, repairs_applied


def evaluate_article_quality(
    title: str,
    article_text: str,
    fact_context: str = "",
    min_pass_score: int = 75,
    article_type: str = "long",
) -> Dict[str, Any]:
    """
    多维质量门禁审查：
    1. AI 刻板套话黑名单扫描
    2. 针对文体的弹性汉字字数把关
    3. 标题合法性与微信规范校验
    4. 标题与金句结构完整性审查
    """
    issues: List[str] = []
    score = 100

    plain_text = _extract_plain_text(article_text)

    # 1. 检测 AI 刻板套话黑名单
    cliche_hits: List[str] = []
    for pattern in CLICHE_PATTERNS:
        matches = re.findall(pattern, plain_text)
        if matches:
            cliche_hits.extend(matches)

    if cliche_hits:
        distinct_cliches = sorted(list(set(cliche_hits)))
        deduction = min(35, len(cliche_hits) * 8)
        score -= deduction
        issues.append(f"命中刻板 AI 套话 {len(cliche_hits)} 次: {distinct_cliches}")

    # 2. 汉字字数达标审查（科学分级，避免一刀切扼杀优质资讯）
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", plain_text))
    type_str = article_type.lower()

    if type_str == "github":
        if chinese_chars < 600:
            score -= 15
            issues.append(f"GitHub 推荐文汉字字数偏少 ({chinese_chars} < 600)")
        if chinese_chars < 350:
            score -= 25
            issues.append(f"GitHub 推荐文内容严重过短 ({chinese_chars} < 350)")
    elif type_str in ("daily_knowledge", "daily"):
        if chinese_chars < 300:
            score -= 15
            issues.append(f"每日小知识汉字字数偏少 ({chinese_chars} < 300)")
        if chinese_chars < 180:
            score -= 25
            issues.append(f"每日小知识内容过短 ({chinese_chars} < 180)")
    elif type_str == "aikepu":
        if chinese_chars < 3000:
            score -= 15
            issues.append(f"体系科普长文字数未达深度标准 ({chinese_chars} < 3000)")
        if chinese_chars < 1500:
            score -= 30
            issues.append(f"体系科普长文字数严重不足 ({chinese_chars} < 1500)")
    else:
        # 热点深度快讯 / 资讯分析
        if chinese_chars < 1000:
            score -= 15
            issues.append(f"深度长文汉字字数偏少 ({chinese_chars} < 1000)")
        if chinese_chars < 600:
            score -= 30
            issues.append(f"正文内容严重过短 ({chinese_chars} < 600)")

    # 3. 标题格式与长度审查
    clean_title = (title or "").strip()
    if not clean_title or len(clean_title) < 5:
        score -= 15
        issues.append(f"标题字数过短 ({len(clean_title)} < 5)")
    if len(clean_title) > 64:
        score -= 20
        issues.append(f"标题字数超出微信 64 字符上限 ({len(clean_title)} > 64)")

    forbidden_endings = ("。", "！", "？", "!", "?", "：", ":", "，", ",")
    if clean_title and clean_title.endswith(forbidden_endings):
        score -= 10
        issues.append(f"标题末尾包含禁止的标点符号「{clean_title[-1]}」")

    # 4. 结构完整性审查（二级标题与重点标粗）
    has_h2 = bool(_H2.search(article_text))
    if not has_h2 and chinese_chars >= 800:
        score -= 10
        issues.append("文稿缺少二级小标题 (##)，层级感不足")

    if chinese_chars >= 800:
        from core.shared.article_utils import count_black_bold
        black_bold_cnt = count_black_bold(article_text)
        if black_bold_cnt == 0:
            score -= 26
            issues.append("文稿正文缺少黑色重点标粗 (**...** / <strong>)，缺少扫读视觉锚点 (0/5)")
        elif black_bold_cnt < 5:
            score -= 10
            issues.append(f"文稿正文黑色重点标粗偏少 ({black_bold_cnt} < 5)")

    score = max(0, min(100, score))
    passed = score >= min_pass_score

    return {
        "score": score,
        "passed": passed,
        "critic_issues": issues,
        "char_count": chinese_chars,
        "cliche_hits": sorted(list(set(cliche_hits))),
        "title": clean_title,
    }


def evaluate_and_repair_article(
    title: str,
    article_text: str,
    fact_context: str = "",
    min_pass_score: int = 75,
    article_type: str = "long",
) -> Tuple[str, Dict[str, Any]]:
    """
    执行主编审校并开启自动化自愈闭环：
    初检未达标时，自动调用修剪润色引擎修复套话与排版缺陷，再行复评。
    返回: (最终正文, 评审报告字典)
    """
    initial_review = evaluate_article_quality(
        title=title,
        article_text=article_text,
        fact_context=fact_context,
        min_pass_score=min_pass_score,
        article_type=article_type,
    )

    if initial_review["passed"]:
        initial_review["was_repaired"] = False
        initial_review["repairs_applied"] = []
        return article_text, initial_review

    # 初检未通过，触发自动化自愈修复
    repaired_text, repairs = auto_repair_article(article_text)
    if repairs:
        logger.info(f"  [Critic Agent] 触发自动质量自愈: 执行了 {len(repairs)} 项润色修剪")
        post_review = evaluate_article_quality(
            title=title,
            article_text=repaired_text,
            fact_context=fact_context,
            min_pass_score=min_pass_score,
            article_type=article_type,
        )
        post_review["was_repaired"] = True
        post_review["repairs_applied"] = repairs
        return repaired_text, post_review

    initial_review["was_repaired"] = False
    initial_review["repairs_applied"] = []
    return article_text, initial_review


def format_critic_report(result: Dict[str, Any]) -> str:
    """格式化审校报告 (严谨学术规范，零表情符号)"""
    score = result.get("score", 0)
    passed = result.get("passed", False)
    status_label = "[准予发布]" if passed else "[门禁拦截]"
    status_text = "合格" if passed else "未通过"
    char_count = result.get("char_count", 0)
    issues = result.get("critic_issues", [])
    repairs = result.get("repairs_applied", [])

    lines = [
        "=" * 45,
        "主编审校质量门禁报告 (Review Gate)",
        "=" * 45,
        f"  标题: {result.get('title', '未知')}",
        f"  综合评分: {score} 分 ({status_label} 状态: {status_text})",
        f"  汉字字数: {char_count} 字",
    ]

    if repairs:
        lines.append("  自动修复项目:")
        for idx, rep in enumerate(repairs, 1):
            lines.append(f"     [{idx}] {rep}")

    if issues:
        lines.append("  保留告警事项:")
        for idx, issue in enumerate(issues, 1):
            lines.append(f"     [{idx}] {issue}")
    else:
        lines.append("  评审结论: 各项关键指标均已达标")

    lines.append("=" * 45)
    return "\n".join(lines)
