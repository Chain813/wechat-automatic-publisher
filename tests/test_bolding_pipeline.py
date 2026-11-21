import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class DummyPublisher:
    def upload_news_image(self, path):
        return "https://mmbiz.qpic.cn/mock_test_img.jpg"


class TestBoldingPipeline(unittest.TestCase):
    def setUp(self):
        self.publisher = DummyPublisher()

    def test_redbold_does_not_bypass_black_bold_fallback_and_chinese_units_work(self):
        """回归测试：6 处 **{{红字}}** + 0 处普通 **黑字** 不应跳过兜底，且贴汉字的数字/百分比应正常加粗"""
        from core.shared.article_utils import (
            BLACKBOLD_STRONG_STYLE,
            REDBOLD_STRONG_STYLE,
            count_black_bold,
            process_article_content,
        )

        article = """## 塔臂合拢前那七分钟，火箭已经把所有退路烧掉了

2024年10月13日清晨，146米高的发射塔上36米长的机械臂合拢，33台猛禽发动机把地面震出一层白雾，助推器在距地面约80米处用“筷子”接住箭体。

**{{结论一：筷子捕获真正改写的不是成本表，而是火箭的属性。}}**

热分离发生在约70公里高空，B14-2 助推器复用了上百次参数验证。

**{{结论二：把死重从火箭挪到地面，本质是把“边际成本”换成“固定成本”。}}**

猎鹰9的公开报价约6700万美元，星舰单次成本有望压降50% 以上，同时减重 30%、载荷提升 20%。

**{{结论三：真正的工程成熟，不是把成功率刷到100%，而是知道哪一次不该接。}}**

第九次试飞采取了主动的“捕获中止”策略，这比单纯追求“捕获失败”后的事后复盘更考验“边界感”。

**{{结论四：星舰不是为“发射市场”造的，它是为星链的资产负债表造的。}}**

**{{结论五：筷子捕获证明的是“助推器能回来”，不是“星舰能登月”。}}**

**{{结论六：当火箭开始按班次发车，太空就从“目的地”变成了“航线”。}}**

关注「极研JiYan」，先人一步洞悉未来。
"""
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # 不应遗留未渲染的 ** Markdown
        plain_no_tags = re.sub(r"<[^>]+>", "", html_body)
        self.assertNotIn("**", plain_no_tags)

        # 红字 6 处保留
        self.assertEqual(html_body.count(REDBOLD_STRONG_STYLE), 6)

        # 黑字兜底成功触发，贴中文数字/百分比/引号/落款均被渲染为醒目黑字徽章
        black_cnt = count_black_bold(html_body)
        self.assertGreaterEqual(black_cnt, 8)
        self.assertIn(f'<strong style="{BLACKBOLD_STRONG_STYLE}">6700万美元</strong>', html_body)
        self.assertIn(f'<strong style="{BLACKBOLD_STRONG_STYLE}">146米</strong>', html_body)
        self.assertIn(f'<strong style="{BLACKBOLD_STRONG_STYLE}">50%</strong>', html_body)
        self.assertIn("关注「极研JiYan」，先人一步洞悉未来。", html_body)
        self.assertIn(f'<strong style="{BLACKBOLD_STRONG_STYLE}">关注「极研JiYan」，先人一步洞悉未来。</strong>', html_body)

    def test_fallback_protects_code_headings_urls_and_placeholders(self):
        """回归测试：兜底加粗绝不能破坏代码块、行内代码、标题、URL、占位符或已有 HTML 属性"""
        from core.shared.article_utils import process_article_content

        article = """## 耗资3400亿美元的“核心工程”详解

详见说明 https://example.com/path/50%/100GB/test 页面与 `cost_50% = "hello_world"` 变量。

【此处插入配图：100米高塔与“机械臂”特写】

```python
price = "6700万美元"
ratio = "50%"
```

正文第一段介绍工程参数，实际投资额达到3400亿美元，核心逻辑在于“降本增效”。
"""
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # 标题、URL、行内代码、代码块内部都不应出现 ** 或被强塞 <strong>
        import html as html_lib

        unescaped_html = html_lib.unescape(html_body)
        self.assertIn("https://example.com/path/50%/100GB/test", html_body)
        self.assertNotIn('https://example.com/path/<strong', html_body)
        self.assertIn('price = "6700万美元"', unescaped_html)
        self.assertIn('ratio = "50%"', unescaped_html)
        self.assertIn('cost_50% = "hello_world"', unescaped_html)
        pre_match = re.search(r'<pre\b[^>]*>[\s\S]*?</pre>', html_body)
        self.assertIsNotNone(pre_match)
        self.assertNotIn('<strong', pre_match.group(0))
        # H2 不被 <strong> 破坏
        self.assertRegex(html_body, r'<h2[^>]*>耗资3400亿美元的“核心工程”详解</h2>')

    def test_tier3_punchline_fallback_for_text_without_numbers_or_quotes(self):
        """回归测试：无数字、无引号的纯论述长文也能触发兜底生成黑字标粗"""
        from core.shared.article_utils import count_black_bold, process_article_content

        article = """## 纯论述文章测试标题

第一段拆解组织架构演化与研发协同机制，说明工程决策背后的权衡成本。

真正的瓶颈从来不是代码行数，而是跨团队沟通损耗。

- 核心约束：组织边界往往直接决定了软件系统的模块边界。
- 关键转折：降低协调复杂度才能释放工程迭代效率。
- 长期影响：标准化接口成为跨部门协作的唯一基准。

**{{唯一一条红字结论：结构设计决定长期演化上限。}}**

关注「极研JiYan」，先人一步洞悉未来。
""" * 2

        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )
        self.assertGreaterEqual(count_black_bold(html_body), 5)

    def test_placeholder_after_blockquote_is_not_trapped_inside_blockquote(self):
        """回归测试：紧跟 > 引用块后的配图占位符不会被吞进 <blockquote> 造成 DOM 嵌套畸形"""
        from unittest.mock import patch
        from core.shared.article_utils import process_article_content

        article = """> 这套系统的核心不是机械臂的力气，而是导航精度。
【此处插入配图：发射塔机械臂特写】
> 火箭回收的难点从来不在落下来。
"""
        with patch("core.shared.article_photos.download_image", return_value="illustration.jpg"):
            html_body, stats = process_article_content(
                article,
                self.publisher,
                use_ai_first=True,
                skip_photo_images=False,
                generate_diagrams=False,
            )

        self.assertEqual(stats["image_count"], 1)
        # 图片不能被包在 <blockquote> 内部
        for bq in re.findall(r"<blockquote.*?</blockquote>", html_body, flags=re.DOTALL):
            self.assertNotIn("<img", bq)
        # 所有 <p> 标签成对闭合
        self.assertEqual(len(re.findall(r"<p\b", html_body)), len(re.findall(r"</p>", html_body)))

    def test_studio_preview_shares_bold_fallback_and_contrast_style(self):
        """回归测试：Studio 预览渲染与正式发布渲染使用一致的强对比加粗样式和兜底逻辑"""
        from core.shared.article_utils import BLACKBOLD_STRONG_STYLE
        from utils.image_prompt_gen import render_article_preview

        md = "## 测试章节\n\n本轮投资达到3400亿美元，覆盖核心研发。\n\n**{{红字判断}}**\n"
        html = render_article_preview(md, "测试", {})
        self.assertIn(BLACKBOLD_STRONG_STYLE, html)
        self.assertIn("3400亿美元", html)

    def test_hotspots_skill_prompt_and_structure_validator(self):
        """回归测试：hotspots_skill.md 包含具体黑字加粗示例与品牌占位替换，结构校验拦截缺少黑字加粗的稿件"""
        import config
        from core.hotspots.processor import load_hotspots_skill_prompt, validate_article_structure

        skill_prompt = load_hotspots_skill_prompt()
        self.assertIn(config.BRAND_NAME, skill_prompt)
        self.assertIn("**3400", skill_prompt)
        self.assertIn("黑色加粗", skill_prompt)

        # 构造一个只有红字、缺乏黑字的稿件（模拟 SpaceX 问题场景）
        no_black_bold_article = (
            "## 标题一\n正文段落一。\n\n> 金句一。\n\n【此处插入配图：图一】\n\n"
            "## 标题二\n正文段落二。\n\n> 金句二。\n\n【此处插入配图：图二】\n\n"
            "## 标题三\n正文段落三。\n\n> 金句三。\n\n【此处插入配图：图三】\n\n"
            "## 标题四\n正文段落四。\n\n"
            "**{{红字一}}**\n**{{红字二}}**\n**{{红字三}}**\n**{{红字四}}**\n**{{红字五}}**\n"
        )
        ok, missing = validate_article_structure(no_black_bold_article)
        self.assertFalse(ok)
        self.assertTrue(any("黑色重点加粗不足" in m for m in missing), f"missing={missing}")

    def test_critic_flags_and_repairs_zero_black_bold_long_article(self):
        """回归测试：Critic 门禁能发现长文 0 黑色加粗并自动修复"""
        from core.pipeline.critic import evaluate_and_repair_article, evaluate_article_quality
        from core.shared.article_utils import count_black_bold

        no_bold_long_article = "## 深度工程剖析：先进制造体系的真实成本结构\n\n" + (
            "现代晶圆厂的资本开支已攀升至200亿美元量级，良率每波动5%都会对毛利产生巨大冲击。"
            "行业所谓的“垂直整合”，本质上是通过重资产壁垒锁定产业链话语权。\n\n"
        ) * 18

        initial = evaluate_article_quality(title="先进制造体系的真实成本结构", article_text=no_bold_long_article)
        self.assertFalse(initial["passed"])
        self.assertTrue(any("加粗" in issue or "标粗" in issue for issue in initial["critic_issues"]))

        repaired_text, final_res = evaluate_and_repair_article(
            title="先进制造体系的真实成本结构",
            article_text=no_bold_long_article,
            article_type="hotspots",
        )
        self.assertTrue(final_res["was_repaired"])
        self.assertTrue(final_res["passed"])
        self.assertGreaterEqual(count_black_bold(repaired_text), 5)


if __name__ == "__main__":
    unittest.main()
