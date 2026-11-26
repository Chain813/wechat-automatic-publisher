import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image


class TestPureVisualAndCostControl(unittest.TestCase):
    def test_local_editorial_prompt_enforces_zero_text_and_bans_flowcharts(self):
        from utils import image_handler

        with patch.object(image_handler, "_can_use_llm_prompt_director", return_value=False):
            prompt = image_handler._build_qwen_image_prompt(
                "可信数据空间｜数据提供方 → 隐私计算 → 数据使用方"
            )

        self.assertIn("纯视觉无字", prompt)
        self.assertIn("严禁流程图", prompt)
        self.assertIn("严禁竖版", prompt)
        self.assertIn("2.35:1", prompt)
        self.assertNotIn("主标题“", prompt)
        self.assertNotIn("卡片之间用", prompt)

    def test_llm_visual_director_uses_thread_context_and_disables_prompt_extend(self):
        from utils import image_handler

        rich_prompt = (
            "一幅16:9宽屏横版《经济学人》风格纯视觉概念插画，浅灰白微纹理纸面留白，"
            "中央70%安全区内描绘两座磨砂玻璃门之间被一枚深岩灰与珊瑚红封条隔断的金属海缆接口，"
            "柔和棚拍漫射光，极简雕塑质感。"
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
                section_context="## 切断直连意味着什么\n中国三大运营商此前可直接申请北美号码段，FCC 新规拟取消该直连资格。",
                slot_index=1,
            ):
                out = image_handler._try_qwen_image_gen(
                    "海缆号段直连受阻的金属门封条隐喻",
                    "tmp_dir",
                )

        self.assertEqual(out, "mocked.png")
        self.assertIn("商务部回应 FCC", captured_args["prompt"])
        self.assertIn("切断直连意味着什么", captured_args["prompt"])
        self.assertIn("100% 纯视觉无字", captured_args["system_content"])

        posted_body = mock_post.call_args.args[1]
        sent_text = posted_body["input"]["messages"][0]["content"][0]["text"]
        self.assertIn(rich_prompt, sent_text)
        self.assertIn("严禁流程图", sent_text)
        self.assertIn("严禁竖版", sent_text)
        self.assertFalse(posted_body["parameters"]["prompt_extend"])

    def test_llm_visual_director_rejects_flowchart_or_text_render_output(self):
        from utils import image_handler

        bad_llm_prompt = (
            "顶部粗体主标题“三步走架构”，下方三张卡片从左到右箭头串联流程图，标注简体中文“第一阶段”。"
        )
        with (
            patch.object(image_handler, "_can_use_llm_prompt_director", return_value=True),
            patch("core.shared.llm.call_deepseek_with_retry", return_value=bad_llm_prompt),
        ):
            out = image_handler._build_qwen_image_prompt("数据中心算力博弈", slot_index=0)

        self.assertNotIn("三步走架构", out)
        self.assertIn("纯视觉无字", out)
        self.assertIn("严禁流程图", out)

    def test_per_article_ai_cap_limits_paid_images_to_one_and_renders_html_cards(self):
        import config
        from core.shared import article_photos
        from core.shared.article_utils import process_article_content

        called_keywords = []

        def fake_download(keyword, directory, *, allow_title_card):
            self.assertFalse(allow_title_card)
            called_keywords.append(keyword)
            Path(directory).mkdir(parents=True, exist_ok=True)
            p = Path(directory) / "hero.jpg"
            Image.new("RGB", (900, 500), "white").save(p)
            return str(p)

        article = (
            "## 核心隐喻\n\n正文第一段。\n\n"
            "【此处插入配图：孤立无窗的数据中心外立面】\n\n"
            "## 估值与口径对比\n\n正文第二段。\n\n"
            "【此处插入配图：估值折价对比｜英伟达 8.4x vs AMD 29x】\n\n"
            "## 链路演进\n\n正文第三段。\n\n"
            "【此处插入配图：营收归集链路｜账单地址 → 总部地址 → 最终买家】\n"
        )
        publisher = Mock()
        publisher.upload_news_image.return_value = "https://mmbiz.qpic.cn/hero.jpg"
        publisher.upload_image.return_value = "cover-1"

        with (
            patch.object(config, "MAX_AI_IMAGES_PER_ARTICLE", 1),
            patch.object(article_photos, "find_source_photo", return_value=None),
            patch.object(article_photos, "download_image", side_effect=fake_download),
        ):
            body, stats = process_article_content(article, publisher, cover_title="数据中心暗战")

        # 仅允许第 1 个缺图槽位调用 AI 生图，其余 2 个结构化槽位转零成本 HTML 卡片
        self.assertEqual(called_keywords, ["孤立无窗的数据中心外立面"])
        self.assertEqual(stats["image_count"], 1)
        self.assertIn("英伟达 8.4x", body)
        self.assertIn("AMD 29x", body)
        self.assertIn("对照维度 A", body)
        self.assertIn("01", body)
        self.assertIn("账单地址", body)

    def test_persistent_daily_quota_breaker_and_http_failure_refund(self):
        import config
        from utils import image_handler

        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "qwen_quota.json"
            fake_resp = {"output": {"choices": [{"message": {"content": [{"image": "https://img.example/x.png"}]}}]}}

            with (
                patch.object(config, "QWEN_IMAGE_DAILY_LIMIT", 2),
                patch.object(image_handler, "_QWEN_QUOTA_FILE", quota_file),
                patch.object(image_handler, "_get_qwen_key_pool", return_value=SimpleNamespace(size=1)),
                patch.object(image_handler, "_save_image_from_url", return_value=str(Path(tmpdir) / "ok.png")),
            ):
                image_handler.reset_qwen_daily_quota()

                # 1. HTTP 500 失败必须退还配额，不得白扣额度
                with patch.object(image_handler, "_qwen_post_with_rotation", return_value=(500, None)):
                    self.assertIsNone(image_handler._try_qwen_image_gen("测试失败退款", tmpdir))
                self.assertEqual(image_handler.get_qwen_daily_usage()["used"], 0)

                # 2. 连续成功 2 次后触发当日 2 张硬上限熔断
                with patch.object(image_handler, "_qwen_post_with_rotation", return_value=(200, fake_resp)) as mock_post:
                    self.assertIsNotNone(image_handler._try_qwen_image_gen("图一", tmpdir))
                    self.assertIsNotNone(image_handler._try_qwen_image_gen("图二", tmpdir))
                    self.assertEqual(image_handler.get_qwen_daily_usage()["used"], 2)
                    self.assertTrue(image_handler.is_qwen_quota_exhausted())
                    # 第 3 次必须被本地成本熔断直接拦截，不再发起 HTTP 请求
                    self.assertIsNone(image_handler._download_free_image("图三", tmpdir))
                    self.assertEqual(mock_post.call_count, 2)

    def test_hotspots_pre_image_critic_rejects_draft_with_zero_image_spend(self):
        from core.hotspots.workflow import ParallelPublishNode
        from core.plugins.base import HotspotItem

        node = ParallelPublishNode()
        pub = Mock()
        pub.access_token = "tok"
        topic = HotspotItem(title="测试低质草稿门禁拦截", url="https://example.com/1")

        with (
            patch("core.hotspots.workflow.generate_article", return_value="## 短\n\n太短了\n\n【此处插入配图：测试】"),
            patch("core.hotspots.workflow.generate_digest", return_value="摘要"),
            patch("core.hotspots.workflow._save_publish_result") as mock_save,
            patch("core.shared.article_photos.prepare_article_photos") as mock_photos,
        ):
            _, ok, err = node._publish_single_topic(topic, pub)

        self.assertFalse(ok)
        self.assertIn("前置质量门禁", err)
        mock_photos.assert_not_called()
        mock_save.assert_called_once()
        self.assertEqual(mock_save.call_args.kwargs["status"], "REJECTED")

    def test_stage3_formatter_and_structure_validator_use_one_hero_and_two_cards(self):
        from core.hotspots import processor

        captured = {}

        def fake_call(prompt, system_content="", **kwargs):
            captured["prompt"] = prompt
            return "a" * 1600

        with patch.object(processor, "call_deepseek_with_retry", side_effect=fake_call):
            processor.format_article_for_wechat("正文内容" * 400, "测试选题")

        self.assertIn("【此处插入配图：", captured["prompt"])
        self.assertIn("【此处绘制图表：", captured["prompt"])
        self.assertIn("阿拉伯数字", captured["prompt"])

        sample = (
            "## 标题一\n\n正文 **加粗1** 与 **加粗2**。\n\n> 金句一。\n\n【此处插入配图：核心物理隐喻】\n\n"
            "## 标题二\n\n正文 **加粗3** 与 **加粗4**。\n\n> 金句二。\n\n【此处绘制图表：对比｜A 8.4x vs B 29x】\n\n"
            "## 标题三\n\n正文 **加粗5** 与 **加粗6**。\n\n> 金句三。\n\n【此处绘制图表：链路｜步骤1 → 步骤2】\n"
        )
        ok, missing = processor.validate_article_structure(sample)
        self.assertTrue(ok, missing)


if __name__ == "__main__":
    unittest.main()
