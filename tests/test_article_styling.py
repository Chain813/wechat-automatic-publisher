import os
import sys
import unittest
from unittest.mock import patch

# 确保测试环境能正确解析项目模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.shared.article_utils import (
    _render_custom_callouts,
    process_article_content,
    _extract_image_placeholders,
)


class DummyPublisher:
    """测试用虚拟发布器"""
    def __init__(self):
        self.uploaded_images = []

    def upload_news_image(self, path):
        url = f"https://mmbiz.qpic.cn/mock_image_{len(self.uploaded_images)}.jpg"
        self.uploaded_images.append((path, url))
        return url


class TestArticleStyling(unittest.TestCase):
    """测试微光视觉排版与组件库升级"""

    def setUp(self):
        self.publisher = DummyPublisher()

    # -------------------------------------------------------------
    # 1. 微光引用容器语法映射 (_render_custom_callouts) 测试
    # -------------------------------------------------------------
    def test_warning_callout_rendering_markdown(self):
        """测试 Markdown 格式的避坑指南/风险预警卡片渲染（琥珀红 #ef4444 / 浅红底 #fef2f2）"""
        md_text = "> ⚠️ **避坑指南 / 风险预警**：严禁在生产环境执行未加锁的高并发写操作。"
        rendered = _render_custom_callouts(md_text)

        self.assertIn("#ef4444", rendered)
        self.assertIn("#fef2f2", rendered)
        self.assertIn("⚠️", rendered)
        self.assertIn("避坑指南 / 风险预警", rendered)
        self.assertIn("严禁在生产环境执行未加锁的高并发写操作", rendered)
        self.assertIn("<section", rendered)

    def test_warning_callout_variants(self):
        """测试避坑指南与风险预警变体语法渲染"""
        for variant in [
            "> ⚠️ **避坑指南**：小心内存泄漏。",
            "> ⚠️ **风险预警**：注意高并发雪崩。",
            "> **避坑指南**：边界条件处理不当。",
        ]:
            rendered = _render_custom_callouts(variant)
            self.assertIn("#ef4444", rendered)
            self.assertIn("#fef2f2", rendered)
            self.assertIn("<section", rendered)

    def test_warning_callout_rendering_html(self):
        """测试已转为 HTML blockquote 的避坑指南/风险预警卡片渲染"""
        html_input = "<blockquote><p>⚠️ <strong>避坑指南 / 风险预警</strong>：数据库连接池溢出风险。</p></blockquote>"
        rendered = _render_custom_callouts(html_input)

        self.assertIn("#ef4444", rendered)
        self.assertIn("#fef2f2", rendered)
        self.assertIn("数据库连接池溢出风险", rendered)
        self.assertIn("<section", rendered)

    def test_insight_callout_rendering_markdown(self):
        """测试核心洞察卡片渲染（微光极客蓝 #3b82f6 / 浅蓝底 #eff6ff）"""
        md_text = "> 💡 **核心洞察**：模型蒸馏与算力适配是端侧 AI 落地的决定性突破口。"
        rendered = _render_custom_callouts(md_text)

        self.assertIn("#3b82f6", rendered)
        self.assertIn("#eff6ff", rendered)
        self.assertIn("💡", rendered)
        self.assertIn("核心洞察", rendered)
        self.assertIn("模型蒸馏与算力适配", rendered)
        self.assertIn("<section", rendered)

    def test_insight_callout_rendering_html(self):
        """测试 HTML blockquote 格式的核心洞察渲染"""
        html_input = "<blockquote><p>💡 <strong>核心洞察</strong>：自注意力机制的稀疏化演化路径。</p></blockquote>"
        rendered = _render_custom_callouts(html_input)

        self.assertIn("#3b82f6", rendered)
        self.assertIn("#eff6ff", rendered)
        self.assertIn("自注意力机制的稀疏化演化路径", rendered)
        self.assertIn("<section", rendered)

    def test_action_list_callout_rendering_markdown(self):
        """测试行动清单卡片渲染（墨绿徽章 #10b981 / 浅绿底 #f0fdf4）"""
        md_text = "> 📌 **行动清单**：\n> 1. 完成基线压测\n> 2. 配置分布式限流"
        rendered = _render_custom_callouts(md_text)

        self.assertIn("#10b981", rendered)
        self.assertIn("#f0fdf4", rendered)
        self.assertIn("📌", rendered)
        self.assertIn("行动清单", rendered)
        self.assertIn("完成基线压测", rendered)
        self.assertIn("<section", rendered)

    def test_action_list_callout_rendering_html(self):
        """测试 HTML blockquote 格式的行动清单渲染"""
        html_input = "<blockquote><p>📌 <strong>行动清单</strong>：升级 Python 运行时并验证环境。</p></blockquote>"
        rendered = _render_custom_callouts(html_input)

        self.assertIn("#10b981", rendered)
        self.assertIn("#f0fdf4", rendered)
        self.assertIn("升级 Python 运行时并验证环境", rendered)
        self.assertIn("<section", rendered)

    def test_regular_blockquote_preservation(self):
        """测试普通引用不被误识别为微光高亮卡片"""
        regular_quote = "> 提出一个问题往往比解决一个问题更重要。—— 爱因斯坦"
        rendered = _render_custom_callouts(regular_quote)

        # 普通引用不应包含自定义卡片容器或特定主题色
        self.assertNotIn("#ef4444", rendered)
        self.assertNotIn("#10b981", rendered)
        self.assertIn("提出一个问题往往比解决一个问题更重要", rendered)

    # -------------------------------------------------------------
    # 2. 全文章处理中的微光组件渲染集成测试
    # -------------------------------------------------------------
    def test_process_article_with_mixed_callouts(self):
        """测试完整文章排版管线中同时渲染多种微光引用卡片"""
        article = """
# 前沿 AI 基础设施实践

在现代大模型工程化体系中，系统稳定性是基石。

> ⚠️ **避坑指南 / 风险预警**：切勿在显存未隔离环境中运行并发测试。

通过高效调度，我们可以显著降低单次推理延迟。

> 💡 **核心洞察**：KV 缓存动态量化技术使得长文本推理吞吐翻倍。

下一步执行落地推荐：

> 📌 **行动清单**：
> 1. 升级 vLLM 核心依赖
> 2. 部署 Prometheus 监控面板
"""
        html_body, stats = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # 验证三种卡片样式均成功生成
        self.assertIn("#ef4444", html_body)  # 避坑红
        self.assertIn("#fef2f2", html_body)
        self.assertIn("#3b82f6", html_body)  # 极客蓝
        self.assertIn("#eff6ff", html_body)
        self.assertIn("#10b981", html_body)  # 墨绿
        self.assertIn("#f0fdf4", html_body)

    # -------------------------------------------------------------
    # 3. 图表关闭时对提示词卡片的平滑替换（删除 AI 提示词草稿字样）
    # -------------------------------------------------------------
    def test_diagram_disabled_smooth_replacement_to_analysis_card(self):
        """测试关闭自动图表生成时，彻底消除 AI 提示词卡片残留，转为高亮分析卡片"""
        article = """
# 架构演进全景图

系统拓扑结构解析如下：

【此处绘制架构图：多智能体协作与动态流转总线】

业务流程时序说明：

【此处绘制流程图：从自然语言意图识别到最终工具调用的全流程】

数据流通核心说明：

【此处绘制图表：模型参数规模与微调收敛速度关联曲线】
"""
        html_body, stats = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # 严格验证：绝不包含草稿阶段的人工待替换提示词字样
        self.assertNotIn("🎨 AI 配图提示词卡片", html_body)
        self.assertNotIn("待网页端生图人工替换", html_body)
        self.assertNotIn("AI 配图提示词", html_body)

        # 验证平滑替换为微光高亮分析卡片
        self.assertIn("📊 核心架构与逻辑拆解", html_body)
        self.assertIn("📊 核心业务流程拆解", html_body)
        self.assertIn("📊 核心逻辑与架构解析", html_body)
        self.assertIn("多智能体协作与动态流转总线", html_body)
        self.assertIn("从自然语言意图识别到最终工具调用的全流程", html_body)
        self.assertIn("#2563eb", html_body)
        self.assertIn("#f8fafc", html_body)

    def test_legacy_draft_prompt_card_text_sanitization(self):
        """测试若旧草稿中直接含有遗留的 AI 配图提示词卡片文本，能被彻底净化"""
        legacy_html = """
<section style="margin: 24px 0;">
<div style="font-size: 13.5px; color: #2563eb;">🎨 AI 配图提示词卡片（待网页端生图人工替换）</div>
<div>系统高并发架构图说明</div>
</section>
"""
        html_body, _ = process_article_content(
            legacy_html,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        self.assertNotIn("🎨 AI 配图提示词卡片（待网页端生图人工替换）", html_body)
        self.assertIn("📊 核心逻辑与架构解析", html_body)

    # -------------------------------------------------------------
    # 4. 配图占位符游标与未下载成功时的平滑消除（无空行断层）
    # -------------------------------------------------------------
    def test_image_placeholder_smooth_elimination_on_failure(self):
        """测试配图未成功下载时，平滑消除占位符且不留多余空行断层"""
        article = """第一段文字介绍深度学习原理。

【此处插入配图：无法搜到配图的超偏门概念XYZ999】

第二段文字紧接着深入解释注意力机制。"""

        with patch("core.shared.article_utils._download_and_upload", return_value=(0, None)):
            html_body, stats = process_article_content(
                article,
                self.publisher,
                skip_photo_images=False,
                generate_diagrams=False,
            )

        # 占位符必须被完全移除
        self.assertNotIn("【此处插入配图", html_body)
        self.assertNotIn("XYZ999", html_body)

        # 验证不会产生空段落标签断层
        self.assertNotIn("<p></p>", html_body)
        self.assertNotIn("<p style=\"margin-bottom: 16px; line-height: 1.85; text-align: justify; font-size: 16px; color: #334155;\"></p>", html_body)

        # 验证第一段与第二段紧凑相连，无突兀多重换行
        self.assertIn("第一段文字介绍深度学习原理", html_body)
        self.assertIn("第二段文字紧接着深入解释注意力机制", html_body)

    def test_slot_cursor_sequential_progression_with_partial_failures(self):
        """测试多配图槽位游标在部分失败、部分成功时的精准顺序对齐"""
        article = """第一部分。
【此处插入配图：第一张图】

第二部分。
【此处插入配图：第二张图失败项】

第三部分。
【此处插入配图：第三张图】"""

        mock_responses = {
            0: (0, "https://mmbiz.qpic.cn/img_slot_1.jpg"),
            1: (1, None),  # 失败槽位
            2: (2, "https://mmbiz.qpic.cn/img_slot_3.jpg"),
        }

        def mock_download_step(kw, pub, use_ai, idx):
            return mock_responses[idx]

        with patch("core.shared.article_utils._download_and_upload", side_effect=mock_download_step):
            html_body, stats = process_article_content(
                article,
                self.publisher,
                skip_photo_images=False,
                generate_diagrams=False,
            )

        # 槽位 1 与 3 正常渲染
        self.assertIn("https://mmbiz.qpic.cn/img_slot_1.jpg", html_body)
        self.assertIn("https://mmbiz.qpic.cn/img_slot_3.jpg", html_body)

        # 槽位 2 平滑消除，不留空段落断层
        self.assertNotIn("第二张图失败项", html_body)
        self.assertNotIn("<p></p>", html_body)
        self.assertEqual(stats["image_count"], 2)

    # -------------------------------------------------------------
    # 5. Linear Modern Light 排版与卡片主题升级测试
    # -------------------------------------------------------------
    def test_linear_light_h2_and_h3_headers(self):
        """测试 Linear Modern Light 的 H2 与 H3 标题样式（#4F5BD5 Indigo 强调色、墨黑主字阶）"""
        article = """
## 第一章：分布式架构设计

### 1.1 节点选举协议

正文段落说明。
"""
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # H2 验证
        self.assertIn("<h2 style=", html_body)
        self.assertIn("#4F5BD5", html_body)
        self.assertIn("rgba(79,91,213,0.08)", html_body)
        self.assertIn("#0C0D0E", html_body)
        self.assertIn("第一章：分布式架构设计", html_body)

        # H3 验证
        self.assertIn("<h3 style=", html_body)
        self.assertIn("border-left: 3px solid #4F5BD5", html_body)
        self.assertIn("1.1 节点选举协议", html_body)

    def test_linear_light_regular_blockquote(self):
        """测试普通引用升级为 Linear Light 浅色微光卡片"""
        article = "> 软件工程的本质是在复杂性、可靠性与演化速度之间寻求动态平衡。"
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        self.assertIn("<blockquote style=", html_body)
        self.assertIn("#F8F9FB", html_body)
        self.assertIn("#4F5BD5", html_body)
        self.assertIn("#5E6470", html_body)
        self.assertIn("box-shadow: 0 1px 2px rgba(0,0,0,0.02)", html_body)

    def test_linear_sunken_code_blocks(self):
        """测试多行与行内代码块渲染为 Linear Modern Light Sunken Code Card"""
        article = """
请在终端中执行 `pip install auto-publish` 安装依赖：

```python
def publish_article(title: str, content: str) -> bool:
    print(f"Publishing {title}")
    return True
```
"""
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # 行内代码验证
        self.assertIn("#F1F3F7", html_body)
        self.assertIn("#4F5BD5", html_body)
        self.assertIn("pip install auto-publish", html_body)

        # 多行代码沉浸式卡片验证
        self.assertIn("#F8F9FB", html_body)
        self.assertIn("#E2E8F0", html_body)
        self.assertIn("#EF4444", html_body)  # 窗口控制红点
        self.assertIn("#F59E0B", html_body)  # 窗口控制黄点
        self.assertIn("#10B981", html_body)  # 窗口控制绿点
        self.assertIn("CODE", html_body)     # 顶部卡片徽标
        self.assertIn("#0C0D0E", html_body)  # 墨黑高对比代码正文
        self.assertIn("publish_article", html_body)

    def test_markdown_table_inline_styling(self):
        """测试 Markdown 表格内联注入微信兼容的 Linear Light 样式与防溢出容器"""
        article = """
| 架构组件 | 职责定位 | 可用性目标 |
| :--- | :--- | :--- |
| 控制中心 | 状态流转与调度 | 99.99% |
| 数据引擎 | 缓存与知识图谱 | 99.9% |
"""
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        self.assertIn("<table", html_body)
        self.assertIn("border-collapse: collapse", html_body)
        self.assertIn("overflow-x: auto", html_body)
        self.assertIn("#F8F9FB", html_body)  # 表头浅灰底
        self.assertIn("#0C0D0E", html_body)  # 表头墨黑文字
        self.assertIn("#E2E8F0", html_body)  # 边框
        self.assertIn("#334155", html_body)  # 单元格文字
        self.assertIn("控制中心", html_body)
        self.assertIn("可用性目标", html_body)

    def test_callout_and_analysis_card_linear_shadow_and_radius(self):
        """测试告警微光卡片与分析卡片均已升级为 10px 圆角与细腻双层 Linear 触觉阴影"""
        article = """
> ⚠️ **避坑指南**：严禁在生产环境明文写入密钥。

【此处绘制架构图：多智能体并发调度图】
"""
        html_body, _ = process_article_content(
            article,
            self.publisher,
            skip_photo_images=True,
            generate_diagrams=False,
        )

        # 验证微光卡片与分析卡片皆应用了 10px 与多层投影
        self.assertIn("border-radius: 10px;", html_body)
        self.assertIn("box-shadow: 0 1px 2px rgba(0,0,0,0.03), 0 4px 16px rgba(15,23,42,0.04);", html_body)

    def test_html_render_linear_light_template_contract(self):
        """测试 utils/html_render.py 中 HTML 渲染模板采用纯白卡片与 Linear Indigo 主题"""
        from utils.html_render import HTML_TEMPLATE

        # 验证 #render-target 容器
        self.assertIn("background-color: #FFFFFF;", HTML_TEMPLATE)
        self.assertIn("color: #0C0D0E;", HTML_TEMPLATE)
        self.assertIn("border: 1px solid rgba(0, 0, 0, 0.08);", HTML_TEMPLATE)
        self.assertIn("border-radius: 16px;", HTML_TEMPLATE)

        # 验证 Mermaid themeVariables
        self.assertIn("theme: 'base'", HTML_TEMPLATE)
        self.assertIn("primaryBorderColor: '#4F5BD5'", HTML_TEMPLATE)
        self.assertIn("lineColor: '#4F5BD5'", HTML_TEMPLATE)

    def test_diagram_gen_linear_light_prompts_and_caption(self):
        """测试 utils/diagram_gen.py 中系统提示词与图解阅读指南遵循 Linear Light"""
        from utils.diagram_gen import UNIFIED_DIAGRAM_SYSTEM_PROMPT, replace_diagram_placeholder

        self.assertIn("fill:#F8F9FB,stroke:#4F5BD5", UNIFIED_DIAGRAM_SYSTEM_PROMPT)
        self.assertIn("bg-white", UNIFIED_DIAGRAM_SYSTEM_PROMPT)
        self.assertIn("#4F5BD5", UNIFIED_DIAGRAM_SYSTEM_PROMPT)

        # 测试图解替换阅读指南
        replaced = replace_diagram_placeholder(
            "【此处绘制图表：系统流程图】",
            "系统流程图",
            "https://mmbiz.qpic.cn/mock_diagram.png"
        )
        self.assertIn("#F8F9FB", replaced)
        self.assertIn("border-left:4px solid #4F5BD5", replaced)
        self.assertIn("💡 <strong>图解阅读指南：</strong> 系统流程图", replaced)

    def test_lite_render_linear_light_card_generation(self):
        """测试 utils/lite_render.py 在本地通过 Matplotlib 成功渲染 Linear Light 卡片图片"""
        import tempfile
        from utils.lite_render import render_formula_card, render_comparison_card, render_text_card

        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. 公式卡片
            formula_png = os.path.join(tmpdir, "formula.png")
            f_ok = render_formula_card(
                title="交叉熵损失函数",
                formula_lines=[r"\mathcal{L} = -\sum_{i=1}^C y_i \log(\hat{y}_i)"],
                notes=["y 为真实标签", r"\hat{y} 为预测概率"],
                output_path=formula_png,
            )
            self.assertTrue(f_ok)
            self.assertTrue(os.path.exists(formula_png) and os.path.getsize(formula_png) > 500)

            # 2. 对比卡片
            compare_png = os.path.join(tmpdir, "compare.png")
            c_ok = render_comparison_card(
                title="架构选型对比",
                columns=["维度", "单体架构", "微服务架构"],
                rows=[
                    ["复杂度", "低", "高"],
                    ["部署灵活性", "一般", "极高"],
                ],
                output_path=compare_png,
            )
            self.assertTrue(c_ok)
            self.assertTrue(os.path.exists(compare_png) and os.path.getsize(compare_png) > 500)

            # 3. 要点卡片
            text_png = os.path.join(tmpdir, "text.png")
            t_ok = render_text_card(
                title="系统核心收益",
                bullet_points=["端到端延迟降低 45%", "内存占用缩减 30%"],
                output_path=text_png,
            )
            self.assertTrue(t_ok)
            self.assertTrue(os.path.exists(text_png) and os.path.getsize(text_png) > 500)


if __name__ == "__main__":
    unittest.main()
