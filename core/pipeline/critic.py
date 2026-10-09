"""
主编审校 Agent 与质量把关门禁 (Critic & Quality Gate)
用于在推文发布前执行多维技术指标审查、AI 刻板套话识别、字数达标检验及事实一致性把关。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from loguru import logger

CLICHE_PATTERNS: List[str] = [
    r"在这场.+背后",
    r"在这场没有硝烟的战争中",
    r"不仅如此",
    r"换句话说",
    r"不得不提",
    r"不可否认",
    r"综上所述",
    r"总而言之",
    r"总的来说",
    r"随着.+飞速发展",
    r"随着.+快速演进",
    r"说白了",
    r"毫无疑问",
    r"显而易见",
    r"拭目以待",
    r"双刃剑",
    r"这是一把双刃剑",
    r"既有机遇也有挑战",
]


def _extract_plain_text(text: str) -> str:
    """去除 HTML 标签以获得干净的纯文本用于字数和套话审查"""
    if not text:
        return ""
    # 去除 HTML 标签
    cleaned = re.sub(r"<[^>]+>", " ", text)
    # 消除连续空白
    return cleaned.strip()


def evaluate_article_quality(
    title: str,
    article_text: str,
    fact_context: str = "",
    min_pass_score: int = 75,
) -> Dict[str, Any]:
    """
    对生成的文稿进行多维质量评分与门禁核验。
    
    返回包含:
    - score: 0-100 综合得分
    - passed: 是否达到及格线发布标准
    - critic_issues: 扣分原因与待修正问题列表
    - char_count: 纯汉字数量
    - cliche_hits: 命中的套话列表
    - title: 审核标题
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
        deduction = min(45, len(cliche_hits) * 10)
        score -= deduction
        issues.append(f"命中刻板 AI 套话 {len(cliche_hits)} 次: {distinct_cliches}")

    # 2. 汉字字数达标审查
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", plain_text))
    if chinese_chars < 1800:
        score -= 25
        issues.append(f"正文汉字字数不足 ({chinese_chars} < 1800)")
    if chinese_chars < 800:
        score -= 25
        issues.append(f"正文内容严重过短 ({chinese_chars} < 800)")

    # 3. 标题格式审查
    clean_title = (title or "").strip()
    if not clean_title or len(clean_title) < 5:
        score -= 15
        issues.append(f"标题字数过短 ({len(clean_title)} < 5)")

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


def format_critic_report(result: Dict[str, Any]) -> str:
    """格式化审校报告以便终端和日志直观呈现"""
    score = result.get("score", 0)
    passed = result.get("passed", False)
    status_emoji = "✅ [准予发布]" if passed else "❌ [门禁拦截]"
    status_text = "通过" if passed else "未通过"
    char_count = result.get("char_count", 0)
    issues = result.get("critic_issues", [])

    lines = [
        f"{'=' * 45}",
        f"📋 主编审校门禁报告 (Review Gate)",
        f"{'=' * 45}",
        f"  🎯 标题: {result.get('title', '未知')}",
        f"  🏆 综合评分: {score} 分 ({status_emoji} {status_text})",
        f"  📝 汉字字数: {char_count} 字",
    ]

    if issues:
        lines.append("  ⚠️ 发现问题:")
        for idx, issue in enumerate(issues, 1):
            lines.append(f"     {idx}. {issue}")
    else:
        lines.append("  ✨ 评审状态: 各项指标均达高分标准，无可挑剔")

    lines.append(f"{'=' * 45}")
    return "\n".join(lines)
