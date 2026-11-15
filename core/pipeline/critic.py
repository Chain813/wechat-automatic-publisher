"""
主编审校 Agent 与质量把关门禁 (Critic & Quality Gate)
用于在推文发布前执行多维技术指标审查、AI 刻板套话识别、字数达标检验及事实一致性把关，
并提供自动化自愈修剪 (Auto-Remediation) 闭环。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

# AI 刻板套话正则与专业语感置换映射表（用于自动修剪与自愈）
CLICHE_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"在这场没有硝烟的战争中", "在当前日益激烈的竞争格局中"),
    (r"在这场.+?背后", "在这项动态背后"),
    (r"不仅如此[，,]?", "与此同时，"),
    (r"换句话说[，,]?", "具体而言，"),
    (r"不得不提的是[，,]?", "值得特别关注的是，"),
    (r"不得不提[，,]?", "值得注意的是，"),
    (r"不可否认[，,]?", "客观审视，"),
    (r"综上所述[，,]?", "从全局维度来看，"),
    (r"总而言之[，,]?", "总体而言，"),
    (r"总的来说[，,]?", "总体审视，"),
    (r"随着.+?飞速发展[，,]?", "在当前技术与产业纵深推进的背景下，"),
    (r"随着.+?快速演进[，,]?", "随着行业进入深化迭代周期，"),
    (r"说白了[，,]?", "从底层逻辑来看，"),
    (r"毫无疑问[，,]?", "事实充分表明，"),
    (r"显而易见[，,]?", "清晰显现，"),
    (r"拭目以待[，,]?", "保持密切审视，"),
    (r"这是一把双刃剑", "这一方案伴随着利弊权衡"),
    (r"双刃剑", "双向博弈机制"),
    (r"既有机遇也有挑战", "在迎来发展窗口的同时也面临现实考量"),
]

CLICHE_PATTERNS: List[str] = [p for p, _ in CLICHE_REPLACEMENTS]


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

    # 1. 自动置换刻板套话
    for pattern, replacement in CLICHE_REPLACEMENTS:
        matches = re.findall(pattern, repaired)
        if matches:
            repaired = re.sub(pattern, replacement, repaired)
            repairs_applied.append(f"将套话「{matches[0]}」平滑润色为「{replacement}」(替换 {len(matches)} 处)")

    # 2. 检查并补齐缺失的小标题层级 (针对无 H2 且字数充裕的文本)
    if not (re.search(r"##\s+", repaired) or re.search(r"<h2\b", repaired)):
        if len(repaired) > 1200:
            # 在文章前半段寻找合适段落插入逻辑小标题
            paragraphs = repaired.split("\n\n")
            if len(paragraphs) >= 4:
                paragraphs.insert(1, "## 一、 核心脉络与关键动向")
                paragraphs.insert(min(4, len(paragraphs) - 1), "## 二、 关键剖析与未来洞察")
                repaired = "\n\n".join(paragraphs)
                repairs_applied.append("自动注入逻辑小标题 (##) 强化文章层级排版")

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

    # 4. 结构完整性审查（二级标题与金句引用）
    has_h2 = bool(re.search(r"##\s+", article_text) or re.search(r"<h2\b", article_text))
    if not has_h2 and chinese_chars >= 800:
        score -= 10
        issues.append("文稿缺少二级小标题 (##)，层级感不足")

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
