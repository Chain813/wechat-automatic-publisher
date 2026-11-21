import pytest
from core.pipeline.critic import evaluate_article_quality, format_critic_report, CLICHE_PATTERNS


class TestReviewGate:
    def test_critic_rejects_hallucination_or_cliche(self):
        """测试套话与字数不足文章被拦截"""
        bad_article = (
            "在这场看似平静的背后，不仅如此，换句话说，不得不提的是，"
            "不可否认随着科技飞速发展，毫无疑问这是一把双刃剑，综上所述总而言之让我们拭目以待。"
        )
        result = evaluate_article_quality(title="测试标题", article_text=bad_article)
        assert result["score"] < 75
        assert result["passed"] is False
        assert len(result["critic_issues"]) > 0
        assert len(result["cliche_hits"]) >= 3

    def test_critic_passes_high_quality_article(self):
        """测试高分合规深度文章顺利通过门禁"""
        content = "## 3400 亿美金账单落地：先进制程扩产背后的隐秘买单者\n\n"
        content += "> 台积电先进制程产能排期已至2027年，真正的成本转嫁链路正在悄然展开。\n\n"
        # 填充足够汉字深度长文
        paragraph = (
            "晶圆制造的底层物理极限在于光刻精度与金属互连延迟。当先进制程推进到两纳米节点，"
            "传统的全环绕栅极晶体管架构面临着极其苛刻的漏电流控制难题。工程师们必须在极低的工作电压下"
            "维持极高的开关速度，这使得研发成本呈指数级膨胀，每一座新晶圆厂的建设开销都是天文数字。"
        )
        content += (paragraph + "\n\n") * 15
        content += "文末：**关注「极研JiYan」，先人一步洞悉未来。**"

        result = evaluate_article_quality(title="先进制程扩产背后的隐秘买单者", article_text=content)
        assert result["score"] >= 75
        assert result["passed"] is True
        assert len(result["cliche_hits"]) == 0

    def test_critic_penalizes_invalid_title(self):
        """测试标题带结尾标点符号或过短时扣分"""
        article = "这是一篇测试文章正文。" * 200
        res = evaluate_article_quality(title="标题末尾绝不能带句号。", article_text=article)
        assert any("标题末尾" in issue for issue in res["critic_issues"])

    def test_format_critic_report(self):
        """测试审核报告格式化输出"""
        result = {
            "score": 60,
            "passed": False,
            "critic_issues": ["正文汉字字数不足", "命中刻板 AI 套话 2 次: ['不仅如此']"],
            "char_count": 500,
            "cliche_hits": ["不仅如此"],
            "title": "测试文章",
        }
        report = format_critic_report(result)
        assert "60 分" in report
        assert "未通过" in report
        assert "正文汉字字数不足" in report
