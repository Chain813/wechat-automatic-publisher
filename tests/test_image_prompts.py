import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from PIL import Image


class TestDeepenedImagePrompts(unittest.TestCase):
    def test_local_infographic_prompt_includes_chinese_text_and_light_style(self):
        from utils import image_handler

        with patch.object(image_handler, "_can_use_llm_prompt_director", return_value=False):
            prompt = image_handler._build_qwen_image_prompt(
                "可信数据空间三层架构｜数据提供方 → 隐私计算与使用控制 → 数据使用方"
            )

        self.assertNotIn("绝对不包含任何文字", prompt)
        self.assertNotIn("无文字", prompt)
        self.assertIn("可信数据空间三层架构", prompt)
        self.assertIn("数据提供方", prompt)
        self.assertIn("数据使用方", prompt)
        self.assertIn("信息图", prompt)

    def test_llm_visual_director_uses_thread_context_and_disables_prompt_extend(self):
        from utils import image_handler

        rich_prompt = (
            "一幅16:9现代科技商业杂志编辑信息图，纯净浅灰白底色，顶部粗体黑字主标题“跨境号码接入路径对比”，"
            "左右双栏对比卡片：左栏“直接获号模式”标注“三大运营商直连”，右栏“FCC新规限制”标注“中转代理与合规成本上升”，"
            "科技靛蓝与克制珊瑚红配色，扁平矢量图标，四周充足留白，无水印。"
        )

        captured_args = {}

        def fake_llm(prompt, system_content="", **kwargs):
            captured_args["prompt"] = prompt
            captured_args["system_content"] = system_content
            return rich_prompt

        fake_resp_body = {"output": {"choices": [{"message": {"content": [{"image": "https://img.example/a.png"}]}}]}}

        with (
            patch.object(image_handler, "_can_use_llm_prompt_director", return_value=True),
            patch("core.shared.llm.call_deepseek_with_retry", side_effect=fake_llm),
            patch.object(image_handler, "_qwen_post_with_rotation", return_value=(200, fake_resp_body)) as mock_post,
            patch.object(image_handler, "_save_image_from_url", return_value="mocked.png"),
        ):
            with image_handler.qwen_prompt_context(
                article_title="商务部回应 FCC 拟禁止中国三大运营商直接获取美国互联网电话号码资源",
                section_context="## 切断直连意味着什么\n中国三大运营商此前可直接申请北美号码段，FCC 新规拟取消该直连资格，迫使跨境通信转向代理中转。",
                slot_index=1,
            ):
                out = image_handler._try_qwen_image_gen(
                    "跨境号码接入路径对比｜直连获号 vs 代理中转",
                    "tmp_dir",
                )

        self.assertEqual(out, "mocked.png")
        self.assertIn("商务部回应 FCC", captured_args["prompt"])
        self.assertIn("切断直连意味着什么", captured_args["prompt"])
        self.assertIn("对比", captured_args["prompt"])

        # Verify rich Chinese infographic prompt preserves exact labels, appends landscape guardrail, and disables prompt_extend
        posted_body = mock_post.call_args.args[1]
        sent_text = posted_body["input"]["messages"][0]["content"][0]["text"]
        self.assertIn(rich_prompt, sent_text)
        self.assertIn("严禁竖版", sent_text)
        self.assertFalse(posted_body["parameters"]["prompt_extend"])

    def test_article_pipeline_propagates_section_context_and_skips_openverse_for_infographics(self):
        from core.shared import article_photos
        from core.shared.article_utils import process_article_content
        from utils import image_handler

        observed_contexts = []

        def fake_download(keyword, directory, *, allow_title_card):
            self.assertFalse(allow_title_card)
            observed_contexts.append((keyword, dict(image_handler.get_qwen_prompt_context())))
            Path(directory).mkdir(parents=True, exist_ok=True)
            p = Path(directory) / "infographic.jpg"
            Image.new("RGB", (900, 500), "white").save(p)
            return str(p)

        article = (
            "## 数据要素怎么流通\n\n"
            "国家数据局推进首批可信数据空间试点，通过隐私计算实现数据可用不可见。\n\n"
            "【此处插入配图：可信数据空间架构｜数据提供方 → 隐私计算 → 数据使用方】\n\n"
            "## 现场实拍参考\n\n"
            "这是一段配普通实体图的文字。\n\n"
            "【此处插入配图：data center server】\n"
        )
        publisher = Mock()
        publisher.upload_news_image.return_value = "https://mmbiz.qpic.cn/info.jpg"
        publisher.upload_image.return_value = "cover-1"

        with (
            patch.object(article_photos, "find_source_photo", return_value=None) as mock_openverse,
            patch.object(article_photos, "download_image", side_effect=fake_download),
        ):
            body, stats = process_article_content(article, publisher, cover_title="可信数据空间试点进展")

        self.assertEqual(stats["image_count"], 2)
        # Infographic brief with '｜' skips Openverse; plain noun still queries Openverse once
        self.assertEqual(mock_openverse.call_count, 1)
        self.assertEqual(mock_openverse.call_args.args[0], "data center server")

        ctx_by_kw = {kw: ctx for kw, ctx in observed_contexts}
        info_ctx = ctx_by_kw["可信数据空间架构｜数据提供方 → 隐私计算 → 数据使用方"]
        self.assertEqual(info_ctx["article_title"], "可信数据空间试点进展")
        self.assertIn("数据要素怎么流通", info_ctx["section_context"])
        self.assertIn("隐私计算", info_ctx["section_context"])
        self.assertEqual(info_ctx["slot_index"], 0)

    def test_stage3_formatter_and_skill_guide_structured_infographic_placeholders(self):
        from core.hotspots import processor

        captured = {}

        def fake_call(prompt, system_content="", **kwargs):
            captured["prompt"] = prompt
            return "a" * 1600

        with patch.object(processor, "call_deepseek_with_retry", side_effect=fake_call):
            processor.format_article_for_wechat("正文内容" * 400, "测试选题")

        self.assertIn("｜", captured["prompt"])
        self.assertIn("信息图", captured["prompt"])

    def test_prompts_strictly_enforce_horizontal_landscape_and_ban_vertical_stacks(self):
        from utils import image_handler

        # Slot 0 archetype must enforce horizontal left-to-right layout, never vertical top-to-bottom stacking
        slot0_name, slot0_desc = image_handler._SLOT_LAYOUT_ARCHETYPES[0]
        self.assertIn("横向", slot0_desc)
        self.assertIn("从左到右", slot0_desc)
        self.assertIn("严禁", slot0_desc)
        self.assertNotIn("三层架构", slot0_name)

        with patch.object(image_handler, "_can_use_llm_prompt_director", return_value=False):
            local_p = image_handler._build_qwen_image_prompt(
                "资本在岸，控制权在水下｜资本登岸 → PropCo分离 → 控制链穿透",
                slot_index=0,
            )
        self.assertIn("横向", local_p)
        self.assertIn("严禁竖版", local_p)

        captured_sys = {}

        def fake_llm(prompt, system_content="", **kwargs):
            captured_sys["sys"] = system_content
            return "16:9 宽屏横向三栏编辑信息图，主标题“测试”，左中右并排三张卡片，严禁竖版堆叠。"

        with (
            patch.object(image_handler, "_can_use_llm_prompt_director", return_value=True),
            patch("core.shared.llm.call_deepseek_with_retry", side_effect=fake_llm),
        ):
            image_handler._build_qwen_image_prompt("测试主题｜要点A → 要点B → 要点C", slot_index=0)

        self.assertIn("严禁竖版", captured_sys["sys"])
        self.assertIn("自上而下", captured_sys["sys"])
        self.assertIn("多行", captured_sys["sys"])


if __name__ == "__main__":
    unittest.main()
