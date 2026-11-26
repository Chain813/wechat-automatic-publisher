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

    def test_llm_visual_director_accepts_negated_bans_and_strips_decorative_quotes(self):
        from utils import image_handler

        valid_prompt = (
            "一幅16:9宽屏横版纯视觉概念插画，浅灰白留白，中央展示“悬浮的天平”与一枚深岩灰石块，"
            "严禁流程图、箭头连线，无主标题与副标题，柔和棚拍漫射光。"
        )
        with (
            patch.object(image_handler, "_can_use_llm_prompt_director", return_value=True),
            patch("core.shared.llm.call_deepseek_with_retry", return_value=valid_prompt),
        ):
            out = image_handler._build_qwen_image_prompt("算力估值天平", slot_index=0)

        self.assertIn("悬浮的天平", out)
        self.assertNotIn("“", out)
        self.assertNotIn("”", out)
        self.assertIn("严禁竖版", out)

    def test_structured_card_strips_markdown_html_without_leaking_escaped_tags(self):
        from core.shared.article_utils import process_article_content

        md_article = (
            "## 对比\n\n正文段落。\n\n"
            "【此处绘制图表：估值对比｜**英伟达 8.4x** vs `AMD 29x`】\n\n"
            "【此处绘制图表：链路｜*步骤1* → **步骤2** → `步骤3`】\n"
        )
        html_body, _ = process_article_content(md_article, Mock(), skip_photo_images=True)
        self.assertIn("英伟达 8.4x", html_body)
        self.assertIn("AMD 29x", html_body)
        self.assertIn("步骤2", html_body)
        self.assertNotIn("&lt;strong&gt;", html_body)
        self.assertNotIn("&lt;code&gt;", html_body)
        self.assertNotIn("&lt;em&gt;", html_body)

    def test_hotspots_workflow_passes_use_ai_first_for_single_hero_after_critic(self):
        from core.hotspots.workflow import ParallelPublishNode
        from core.plugins.base import HotspotItem

        node = ParallelPublishNode()
        pub = Mock()
        pub.access_token = "tok"
        topic = HotspotItem(title="英伟达市值波动与算力格局", url="https://example.com/nv")

        valid_article = (
            "## 第一节冲突\n\n" + ("这是有 **事实依据** 的 **深度分析** 段落，涉及 **111 名** 与 **54 起**。" * 25) + "\n\n"
            "> 金句一。\n\n【此处插入配图：悬在玻璃门前的铜锁隐喻】\n\n"
            "## 第二节对照\n\n" + ("这是 **第二部分** 关于 **算力芯片** 与 **估值** 的拆解。" * 25) + "\n\n"
            "> 金句二。\n\n【此处绘制图表：对比｜A 8.4x vs B 29x】\n\n"
            "## 第三节收束\n\n" + ("这是 **第三部分** 关于 **工程落地** 的讨论。" * 25) + "\n\n"
            "> 金句三。\n\n【此处绘制图表：链路｜步骤1 → 步骤2】\n"
        )

        with (
            patch("core.hotspots.workflow.generate_article", return_value=f"```markdown\n{valid_article}\n```"),
            patch("core.hotspots.workflow.generate_digest", return_value="冷静摘要"),
            patch("core.hotspots.workflow.process_article_content", return_value=("<h2>OK</h2>", {
                "word_count": 2000, "image_count": 1, "sensitive_words": [], "thumb_id": "thumb-1", "html_bytes": 1024,
            })) as mock_proc,
            patch("core.hotspots.workflow.publish_article", return_value=(True, None)),
        ):
            _, ok, err = node._publish_single_topic(topic, pub)

        self.assertTrue(ok, err)
        mock_proc.assert_called_once()
        self.assertTrue(mock_proc.call_args.kwargs.get("use_ai_first"))
        self.assertNotIn("```markdown", mock_proc.call_args.args[0])

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


class TestGeminiImageProvider(unittest.TestCase):
    def _make_jpeg_b64(self, size=(64, 36), color="indigo"):
        import base64
        from io import BytesIO

        buf = BytesIO()
        Image.new("RGB", size, color).save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    def test_gemini_payload_headers_and_aspect_ratios(self):
        import requests
        import config
        from utils import image_handler
        from utils.key_pool import ApiKeyPool, RateLimiter
        from threading import Semaphore

        b64_img = self._make_jpeg_b64()
        captured_calls = []

        def fake_post(url, headers=None, json=None, timeout=None):
            captured_calls.append({"url": url, "headers": dict(headers or {}), "json": dict(json or {}), "timeout": timeout})
            resp = Mock()
            resp.status_code = 200
            resp.json.return_value = {
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "image", "data": b64_img, "mime_type": "image/jpeg"}],
                    }
                ]
            }
            return resp

        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            with (
                patch.object(config, "IMAGE_PROVIDER", "auto"),
                patch.object(config, "IMAGE_GEN_MODEL", "gemini-nano-banana-2.1"),
                patch.object(config, "GEMINI_IMAGE_SERVICE_URL", ""),
                patch.object(config, "GEMINI_API_BASE", "https://gemini.239020.xyz/"),
                patch.object(config, "GEMINI_PROXY_TOKEN", "proxy-secret-token"),
                patch.object(config, "GEMINI_IMAGE_SIZE", "1K"),
                patch.object(config, "GEMINI_IMAGE_BODY_ASPECT_RATIO", "16:9"),
                patch.object(config, "GEMINI_IMAGE_COVER_ASPECT_RATIO", "21:9"),
                patch.object(config, "GEMINI_IMAGE_THINKING_LEVEL", "minimal"),
                patch.object(config, "QWEN_IMAGE_DAILY_LIMIT", 6),
                patch.object(image_handler, "_QWEN_QUOTA_FILE", quota_file),
                patch.object(image_handler, "_get_gemini_key_pool", return_value=ApiKeyPool(["gem-key-1234"])),
                patch.object(image_handler, "_qwen_image_limiter", RateLimiter(0)),
                patch.object(image_handler, "_qwen_image_sem", Semaphore(1)),
                patch.object(requests, "post", side_effect=fake_post),
            ):
                image_handler.reset_qwen_daily_quota()
                body_path = image_handler._try_gemini_image_gen("玻璃天平隐喻", tmpdir, purpose="body")
                cover_path = image_handler._try_gemini_image_gen("玻璃天平隐喻", tmpdir, purpose="cover")

            self.assertIsNotNone(body_path)
            self.assertTrue(Path(body_path).exists())
            self.assertIsNotNone(cover_path)
            self.assertTrue(Path(cover_path).exists())

        self.assertEqual(len(captured_calls), 2)
        body_req, cover_req = captured_calls
        self.assertEqual(body_req["url"], "https://gemini.239020.xyz/v1beta/interactions")
        self.assertEqual(body_req["headers"]["Api-Revision"], "2026-05-20")
        self.assertEqual(body_req["headers"]["x-goog-api-key"], "gem-key-1234")
        self.assertEqual(body_req["headers"]["X-Proxy-Token"], "proxy-secret-token")
        self.assertEqual(body_req["json"]["model"], "gemini-nano-banana-2.1")
        self.assertEqual(
            body_req["json"]["response_format"],
            {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "16:9", "image_size": "1K"},
        )
        self.assertEqual(body_req["json"]["generation_config"], {"thinking_level": "minimal"})
        self.assertEqual(
            cover_req["json"]["response_format"],
            {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "21:9", "image_size": "1K"},
        )

    def test_gemini_response_parser_supports_all_schemas_and_rejects_corrupt_bytes(self):
        import base64
        from utils import image_handler

        b64_img = self._make_jpeg_b64()
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = image_handler._parse_gemini_image_response(
                {"steps": [{"content": [{"type": "text", "text": "ok"}, {"type": "image", "data": b64_img}]}]},
                tmpdir,
                "steps",
            )
            p2 = image_handler._parse_gemini_image_response(
                {"outputs": [{"type": "image", "data": b64_img}]},
                tmpdir,
                "outputs",
            )
            p3 = image_handler._parse_gemini_image_response(
                {"output_image": {"data": f"data:image/jpeg;base64,{b64_img}"}},
                tmpdir,
                "direct",
            )
            bad_b64 = base64.b64encode(b"not-an-image-at-all" * 40).decode("ascii")
            p_bad = image_handler._parse_gemini_image_response(
                {"output_image": {"data": bad_b64}},
                tmpdir,
                "bad",
            )
            self.assertIsNotNone(p1)
            self.assertIsNotNone(p2)
            self.assertIsNotNone(p3)
            self.assertIsNone(p_bad)

    def test_gemini_failure_refunds_quota_and_falls_back_to_qwen(self):
        import requests
        import config
        from utils import image_handler
        from utils.key_pool import ApiKeyPool, RateLimiter
        from threading import Semaphore

        b64_img = self._make_jpeg_b64()
        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            qwen_out = Path(tmpdir) / "qwen_fallback.jpg"
            Image.new("RGB", (64, 36), "teal").save(qwen_out)
            qwen_resp = {"output": {"choices": [{"message": {"content": [{"image": f"data:image/jpeg;base64,{b64_img}"}]}}]}}

            with (
                patch.object(config, "IMAGE_PROVIDER", "auto"),
                patch.object(config, "IMAGE_GEN_MODEL", "gemini-nano-banana-2.1"),
                patch.object(config, "GEMINI_IMAGE_SERVICE_URL", ""),
                patch.object(config, "GEMINI_IMAGE_FALLBACK_TO_QWEN", True),
                patch.object(config, "QWEN_IMAGE_DAILY_LIMIT", 6),
                patch.object(image_handler, "_QWEN_QUOTA_FILE", quota_file),
                patch.object(image_handler, "_get_gemini_key_pool", return_value=ApiKeyPool(["gem-1"])),
                patch.object(image_handler, "_get_qwen_key_pool", return_value=ApiKeyPool(["qwen-1"])),
                patch.object(image_handler, "_qwen_image_limiter", RateLimiter(0)),
                patch.object(image_handler, "_qwen_image_sem", Semaphore(1)),
                patch.object(image_handler, "_image_sources_status", {
                    "gemini": {"status": True, "last_check": 0},
                    "qwen": {"status": True, "last_check": 0},
                }),
                patch.object(requests, "post", return_value=Mock(status_code=503, text="upstream down")),
                patch.object(image_handler, "_qwen_post_with_rotation", return_value=(200, qwen_resp)) as mock_qwen_post,
                patch("core.shared.runtime.cancel_event.wait", return_value=False),
            ):
                image_handler.reset_qwen_daily_quota()
                result = image_handler._download_free_image("算力边界", tmpdir, purpose="body", max_retries=2)
                usage = image_handler.get_qwen_daily_usage()

            self.assertIsNotNone(result)
            self.assertTrue(Path(result).exists())
            mock_qwen_post.assert_called_once()
            # 2 次 Gemini 503 失败均全额退还配额，最终仅 Qwen 成功消耗 1 次
            self.assertEqual(usage["used"], 1)

    def test_redraw_reference_image_falls_back_to_qwen(self):
        import config
        from utils import image_handler

        with tempfile.TemporaryDirectory() as tmpdir:
            ref = Path(tmpdir) / "ref.jpg"
            Image.new("RGB", (64, 36), "gray").save(ref)
            with (
                patch.object(config, "IMAGE_PROVIDER", "auto"),
                patch.object(config, "IMAGE_GEN_MODEL", "gemini-nano-banana-2.1"),
                patch.object(config, "GEMINI_IMAGE_SERVICE_URL", ""),
                patch.object(config, "GEMINI_IMAGE_FALLBACK_TO_QWEN", True),
                patch.object(image_handler, "_get_gemini_key_pool", return_value=SimpleNamespace(size=1)),
                patch.object(image_handler, "_get_qwen_key_pool", return_value=SimpleNamespace(size=1)),
                patch.object(image_handler, "_try_gemini_image_redraw", return_value=None) as mock_gem_redraw,
                patch.object(image_handler, "_try_qwen_image_redraw", return_value=str(ref)) as mock_qwen_redraw,
            ):
                out = image_handler.redraw_reference_image(str(ref), "重绘", tmpdir)

            self.assertEqual(out, str(ref))
            mock_gem_redraw.assert_called_once()
            mock_qwen_redraw.assert_called_once()

    def test_api_config_masks_gemini_secrets_and_hot_reloads_model(self):
        import os
        import config
        import webui
        from utils import image_handler

        with tempfile.TemporaryDirectory() as tmpdir:
            orig_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                Path(".env").write_text(
                    "GEMINI_API_KEY=AIzaSySecretKey9999\n"
                    "GEMINI_PROXY_TOKEN=superproxysecret7777\n"
                    "IMAGE_GEN_MODEL=gemini-nano-banana-2.1\n",
                    encoding="utf-8",
                )
                with (
                    patch.object(webui, "CLOUD_MODE", False),
                    patch.object(config, "IMAGE_GEN_MODEL", config.IMAGE_GEN_MODEL),
                    patch.object(config, "GEMINI_API_KEY", config.GEMINI_API_KEY),
                    patch.object(config, "GEMINI_PROXY_TOKEN", config.GEMINI_PROXY_TOKEN),
                    patch.object(config, "GEMINI_IMAGE_MODEL", config.GEMINI_IMAGE_MODEL),
                    patch.object(config, "GEMINI_IMAGE_SIZE", config.GEMINI_IMAGE_SIZE),
                    patch.object(config, "IMAGE_PROVIDER", config.IMAGE_PROVIDER),
                ):
                    webui.app.config["TESTING"] = True
                    client = webui.app.test_client()

                    get_res = client.get("/api/config")
                    self.assertEqual(get_res.status_code, 200)
                    payload = get_res.get_json()
                    self.assertIn("****", payload["GEMINI_API_KEY"])
                    self.assertTrue(payload["GEMINI_API_KEY"].endswith("9999"))
                    self.assertIn("****", payload["GEMINI_PROXY_TOKEN"])
                    self.assertTrue(payload["GEMINI_PROXY_TOKEN"].endswith("7777"))

                    post_res = client.post(
                        "/api/config",
                        json={
                            "IMAGE_GEN_MODEL": "gemini-3-pro-image",
                            "GEMINI_API_KEY": "****9999",
                            "GEMINI_PROXY_TOKEN": "****7777",
                            "GEMINI_IMAGE_SIZE": "2k",
                            "IMAGE_PROVIDER": "gemini",
                        },
                    )
                    self.assertEqual(post_res.status_code, 200)
                    self.assertEqual(config.IMAGE_GEN_MODEL, "gemini-3-pro-image")
                    self.assertEqual(config.GEMINI_IMAGE_SIZE, "2K")
                    self.assertEqual(config.IMAGE_PROVIDER, "gemini")
                    self.assertEqual(config.GEMINI_API_KEY, "AIzaSySecretKey9999")
                    self.assertEqual(config.GEMINI_PROXY_TOKEN, "superproxysecret7777")
            finally:
                os.chdir(orig_cwd)
                image_handler.reset_gemini_key_pool()
                image_handler.reset_qwen_key_pool()

    def test_private_image_service_mode_sends_zero_google_key_and_saves_binary_jpeg(self):
        from io import BytesIO
        import requests
        import config
        from utils import image_handler
        from utils.key_pool import ApiKeyPool, RateLimiter
        from threading import Semaphore

        buf = BytesIO()
        Image.new("RGB", (1376, 768), "navy").save(buf, format="JPEG")
        jpeg_bytes = buf.getvalue()
        calls = []

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append({"url": url, "headers": dict(headers or {}), "json": dict(json or {})})
            resp = Mock()
            resp.status_code = 200
            resp.headers = {"Content-Type": "image/jpeg"}
            resp.content = jpeg_bytes
            return resp

        with tempfile.TemporaryDirectory() as tmpdir:
            quota_file = Path(tmpdir) / "quota.json"
            with (
                patch.object(config, "IMAGE_PROVIDER", "auto"),
                patch.object(config, "IMAGE_GEN_MODEL", "gemini-nano-banana-2.1"),
                patch.object(config, "GEMINI_IMAGE_SERVICE_URL", "https://gemini.239020.xyz/api/generate"),
                patch.object(config, "GEMINI_PROXY_TOKEN", "edge-token-only"),
                patch.object(config, "GEMINI_IMAGE_SIZE", "1K"),
                patch.object(config, "QWEN_IMAGE_DAILY_LIMIT", 6),
                patch.object(image_handler, "_QWEN_QUOTA_FILE", quota_file),
                patch.object(image_handler, "_get_gemini_key_pool", return_value=ApiKeyPool([])),
                patch.object(image_handler, "_qwen_image_limiter", RateLimiter(0)),
                patch.object(image_handler, "_qwen_image_sem", Semaphore(1)),
                patch.object(requests, "post", side_effect=fake_post),
            ):
                image_handler.reset_qwen_daily_quota()
                body_path = image_handler._try_gemini_image_gen("磨砂玻璃天平", tmpdir, purpose="body")
                cover_path = image_handler._try_gemini_image_gen("磨砂玻璃天平", tmpdir, purpose="cover")

            self.assertIsNotNone(body_path)
            self.assertIsNotNone(cover_path)
            with Image.open(body_path) as img:
                self.assertEqual(img.size, (1376, 768))

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["url"], "https://gemini.239020.xyz/api/generate")
        self.assertEqual(calls[0]["headers"].get("X-Proxy-Token"), "edge-token-only")
        self.assertNotIn("x-goog-api-key", {k.lower() for k in calls[0]["headers"]})
        self.assertEqual(calls[0]["json"]["aspect_ratio"], "16:9")
        self.assertEqual(calls[1]["json"]["aspect_ratio"], "21:9")


if __name__ == "__main__":
    unittest.main()
