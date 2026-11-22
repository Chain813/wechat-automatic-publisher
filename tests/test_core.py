import os
import re
import runpy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import config
from core.shared.llm import (
    validate_title,
    validate_article_length,
    filter_sensitive,
    is_beijing_peak_hour,
    calculate_cache_saving_rate,
    LLMCacheMetrics
)


class TestCoreLLMLogic(unittest.TestCase):
    def test_validate_title_clickbait_removal(self):
        title, warnings = validate_title("震惊！重磅最新AI突破技术")
        self.assertNotIn("震惊", title)
        self.assertNotIn("重磅", title)
        self.assertTrue(len(warnings) > 0)

    def test_validate_article_length(self):
        count, ok, msg = validate_article_length("测试" * 1200)
        self.assertTrue(ok)
        self.assertEqual(count, 2400)

    def test_cache_metrics_calculation(self):
        metrics = LLMCacheMetrics()
        metrics.record(1000, 500, 150)
        stats = metrics.get_stats()
        self.assertEqual(stats["total_requests"], 1)
        self.assertEqual(stats["hit_tokens"], 1000)
        self.assertEqual(stats["miss_tokens"], 500)
        self.assertGreater(stats["saved_cny"], 0)

    def test_beijing_peak_hour_boolean(self):
        res = is_beijing_peak_hour()
        self.assertIsInstance(res, bool)

    def test_cache_saving_rate_computation(self):
        rate_flash = calculate_cache_saving_rate("deepseek-v4-flash")
        rate_pro = calculate_cache_saving_rate("deepseek-v4-pro")
        self.assertGreater(rate_pro, rate_flash)


class TestAccountBrand(unittest.TestCase):
    def test_brand_and_author_configuration(self):
        cases = [
            ({}, ("极研JiYan", "极研JiYan")),
            ({"BRAND_NAME": "   "}, ("极研JiYan", "极研JiYan")),
            ({"BRAND_NAME": " 测试号 "}, ("测试号", "测试号")),
            ({"BRAND_NAME": "测试号", "ARTICLE_AUTHOR": "  "}, ("测试号", "测试号")),
            ({"BRAND_NAME": "测试号", "ARTICLE_AUTHOR": " 独立作者 "}, ("测试号", "独立作者")),
        ]
        for env, expected in cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch("dotenv.load_dotenv"):
                settings = runpy.run_path(config.__file__)
                self.assertEqual((settings["BRAND_NAME"], settings["ARTICLE_AUTHOR"]), expected)

    def test_article_signature_configuration(self):
        with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv"):
            settings = runpy.run_path(config.__file__)
        self.assertEqual(
            settings["ARTICLE_SIGNATURE"],
            "**关注「极研JiYan」，只讲有出处的科技门道与深度拆解。**",
        )
        with patch.dict(os.environ, {"BRAND_NAME": "测试号"}, clear=True), patch("dotenv.load_dotenv"):
            settings_brand = runpy.run_path(config.__file__)
        self.assertEqual(
            settings_brand["ARTICLE_SIGNATURE"],
            "**关注「测试号」，只讲有出处的科技门道与深度拆解。**",
        )
        with patch.dict(os.environ, {"ARTICLE_SIGNATURE": "**自定义落款**"}, clear=True), patch("dotenv.load_dotenv"):
            settings_custom = runpy.run_path(config.__file__)
        self.assertEqual(settings_custom["ARTICLE_SIGNATURE"], "**自定义落款**")

    def test_builtin_system_prompts_use_configured_brand(self):
        from core.aikepu.processor import build_system_prompt
        from core.github.processor import SYSTEM_PROMPT as GITHUB_SYSTEM_PROMPT
        from core.hotspots.processor import SYSTEM_PROMPT as HOTSPOTS_SYSTEM_PROMPT

        self.assertIn(config.BRAND_NAME, build_system_prompt())
        self.assertIn(config.BRAND_NAME, GITHUB_SYSTEM_PROMPT)
        self.assertIn(config.BRAND_NAME, HOTSPOTS_SYSTEM_PROMPT)

    def test_aikepu_file_prompt_uses_custom_brand(self):
        from core.aikepu import processor

        with patch.dict(os.environ, KNOWLEDGE_TREE="aikepu"), patch.object(processor, "BRAND_NAME", "测试号"):
            prompt = processor.load_aikepu_skill_prompt()
        self.assertIn("「测试号」AI 科普长文写作 Skill", prompt.splitlines()[0])
        self.assertIn("你是「测试号」的资深 AI 技术专栏作者", prompt)

    def test_daily_knowledge_sends_branded_photo_search_prompt(self):
        from daily_knowledge import engine

        with (
            patch.object(engine, "BRAND_NAME", "测试号"),
            patch.object(engine, "get_recent_concepts", return_value=[]),
            patch.object(engine.LLMClient, "generate", return_value="正文\n[CONCEPT_TAG: 示例]") as generate,
        ):
            self.assertEqual(engine.generate_daily_knowledge(max_retries=1), ("正文", "示例"))
        system_prompt, user_prompt = generate.call_args.args
        self.assertIn("「测试号」每日小知识", system_prompt.splitlines()[0])
        self.assertIn("英文检索词", user_prompt)
        self.assertIn("英文检索词", system_prompt)
        examples = re.findall(r"^【此处插入配图：([^】]+)】$", system_prompt, re.MULTILINE)
        self.assertIn(len(examples), (2, 3))
        for query in examples:
            self.assertRegex(query, r"^[A-Za-z0-9][\w.+-]*(?: [\w.+-]+){0,4}$")

    def test_local_cover_draws_custom_brand(self):
        from PIL import ImageDraw
        from utils import image_handler

        with (
            TemporaryDirectory() as temp,
            patch.object(image_handler, "BRAND_NAME", "测试号"),
            patch.object(ImageDraw.ImageDraw, "text", autospec=True, side_effect=ImageDraw.ImageDraw.text) as draw_text,
        ):
            cover = Path(temp) / "cover.jpg"
            image_handler.generate_default_cover("示例文章", cover)
            self.assertGreater(cover.stat().st_size, 0)
            labels = [call.args[2] for call in draw_text.call_args_list]
        self.assertIn("测试号", labels)
        self.assertIn("测试号 • AI AUTOMATION", labels)


class TestHotspotFilterConfig(unittest.TestCase):
    def test_hotspot_tiers_cover_tech_policy_and_kaoyan_research(self):
        self.assertTrue(hasattr(config, "HOTSPOT_TIERS"))
        self.assertEqual(len(config.HOTSPOT_TIERS), 3)
        flattened = [kw for tier in config.HOTSPOT_TIERS for kw in tier["keywords"]]
        self.assertEqual(config.FILTER_CATEGORIES, flattened)
        # 方向一：2026 前沿科技与政策
        for kw in ("AI监管", "国产算力", "Coding Agent", "推理模型"):
            self.assertIn(kw, config.FILTER_CATEGORIES)
        # 方向二：极研考研 / 高校科研 / 计算机与校招
        for kw in ("考研", "408", "高校实验室", "校招"):
            self.assertIn(kw, config.FILTER_CATEGORIES)

    def test_filter_tech_hotspots_injects_configured_tiers_into_prompt(self):
        from core.hotspots import processor

        custom_tiers = [
            {
                "name": "测试第一梯队",
                "description": "测试专用描述",
                "keywords": ["SENTINEL_TECH_KW", "SENTINEL_KAOYAN_KW"],
            }
        ]
        with (
            patch.object(processor, "HOTSPOT_TIERS", custom_tiers),
            patch.object(
                processor,
                "call_deepseek",
                return_value="【话题】示例热点\n【雷达分析】测试理由",
            ) as mock_llm,
        ):
            topics = processor.filter_tech_hotspots(["示例热点"])
        self.assertEqual(topics, ["示例热点"])
        sent_prompt = mock_llm.call_args.args[0]
        self.assertIn("测试第一梯队", sent_prompt)
        self.assertIn("SENTINEL_TECH_KW", sent_prompt)
        self.assertIn("SENTINEL_KAOYAN_KW", sent_prompt)


class TestLLMThinkingAndTokenBudget(unittest.TestCase):
    def test_llm_default_config_avoids_reasoning_starvation(self):
        with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv"):
            settings = runpy.run_path(config.__file__)
        self.assertGreaterEqual(settings["LLM_MAX_TOKENS"], 16384)
        self.assertFalse(settings["LLM_ENABLE_THINKING"])

        with patch.dict(os.environ, {"LLM_ENABLE_THINKING": "true"}, clear=True), patch("dotenv.load_dotenv"):
            settings_on = runpy.run_path(config.__file__)
        self.assertTrue(settings_on["LLM_ENABLE_THINKING"])

    def test_call_deepseek_disables_thinking_by_default_and_falls_back_on_400(self):
        from unittest.mock import MagicMock
        import requests
        from core.shared import llm

        resp_400 = MagicMock()
        resp_400.status_code = 400
        http_err = requests.exceptions.HTTPError("400 Bad Request", response=resp_400)
        resp_400.raise_for_status.side_effect = http_err

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.raise_for_status.return_value = None
        resp_200.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": "正常返回正文"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

        sent_payloads = []

        def fake_post(url, headers=None, json=None, timeout=None):
            sent_payloads.append(dict(json))
            return resp_400 if len(sent_payloads) == 1 else resp_200

        fake_pool = MagicMock()
        fake_pool.size = 1
        fake_pool.get_key.return_value = "test-only-key"

        with (
            patch.object(llm, "LLM_ENABLE_THINKING", False),
            patch.object(llm, "_get_llm_key_pool", return_value=fake_pool),
            patch.object(llm.API_SESSION, "post", side_effect=fake_post),
        ):
            out = llm.call_deepseek_with_retry("测试", max_retries=2)

        self.assertEqual(out, "正常返回正文")
        self.assertEqual(len(sent_payloads), 2)
        self.assertEqual(sent_payloads[0].get("thinking"), {"type": "disabled"})
        self.assertNotIn("thinking", sent_payloads[1])

    def test_call_deepseek_recovers_when_reasoning_tokens_exhaust_max_tokens(self):
        from unittest.mock import MagicMock
        from core.shared import llm

        starved_resp = MagicMock()
        starved_resp.status_code = 200
        starved_resp.raise_for_status.return_value = None
        starved_resp.json.return_value = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning_content": "长思考..." * 500},
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 8192,
                "completion_tokens_details": {"reasoning_tokens": 8192},
            },
        }

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.raise_for_status.return_value = None
        ok_resp.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": "恢复后的完整正文"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 1200},
        }

        sent_payloads = []

        def fake_post(url, headers=None, json=None, timeout=None):
            sent_payloads.append(dict(json))
            return starved_resp if len(sent_payloads) == 1 else ok_resp

        fake_pool = MagicMock()
        fake_pool.size = 1
        fake_pool.get_key.return_value = "test-only-key"

        with (
            patch.object(llm, "_get_llm_key_pool", return_value=fake_pool),
            patch.object(llm.API_SESSION, "post", side_effect=fake_post),
        ):
            out = llm.call_deepseek_with_retry("写一篇深度文章", max_retries=2, enable_thinking=True)

        self.assertEqual(out, "恢复后的完整正文")
        self.assertEqual(len(sent_payloads), 2)
        self.assertNotIn("thinking", sent_payloads[0])
        self.assertEqual(sent_payloads[1].get("thinking"), {"type": "disabled"})

    def test_call_deepseek_supports_reasoning_effort_and_tools_with_400_fallback(self):
        from unittest.mock import MagicMock
        import requests
        from core.shared import llm

        resp_400 = MagicMock()
        resp_400.status_code = 400
        resp_400.raise_for_status.side_effect = requests.exceptions.HTTPError("400", response=resp_400)

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.raise_for_status.return_value = None
        resp_200.json.return_value = {
            "choices": [{"finish_reason": "stop", "message": {"content": "调研结果"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        }

        sent_payloads = []

        def fake_post(url, headers=None, json=None, timeout=None):
            sent_payloads.append(dict(json))
            return resp_400 if len(sent_payloads) == 1 else resp_200

        fake_pool = MagicMock()
        fake_pool.size = 1
        fake_pool.get_key.return_value = "test-only-key"

        tools = [{"type": "deepseek_web_search"}, {"type": "deepseek_read_url"}]
        with (
            patch.object(llm, "_get_llm_key_pool", return_value=fake_pool),
            patch.object(llm.API_SESSION, "post", side_effect=fake_post),
        ):
            out = llm.call_deepseek_with_retry(
                "调研", max_retries=2, reasoning_effort="low", tools=tools
            )

        self.assertEqual(out, "调研结果")
        self.assertEqual(sent_payloads[0].get("reasoning_effort"), "low")
        self.assertEqual(sent_payloads[0].get("tools"), tools)
        self.assertNotIn("thinking", sent_payloads[0])
        self.assertNotIn("reasoning_effort", sent_payloads[1])
        self.assertNotIn("tools", sent_payloads[1])


class TestThreeStageHotspotPipeline(unittest.TestCase):
    def test_default_three_stage_model_config(self):
        with patch.dict(os.environ, {}, clear=True), patch("dotenv.load_dotenv"):
            settings = runpy.run_path(config.__file__)
        self.assertEqual(settings["LLM_RESEARCH_MODEL"], "deepseek-flash")
        self.assertEqual(settings["LLM_WRITER_MODEL"], "deepseek-v4-pro")
        self.assertEqual(settings["LLM_WRITER_REASONING_EFFORT"], "low")
        self.assertTrue(settings["LLM_ENABLE_WEB_SEARCH"])

    def test_research_stage_uses_web_search_tools_and_writer_uses_pro_low(self):
        from core.hotspots import processor
        from core.plugins.base import HotspotItem

        prose = (
            "## 第一节具体冲突\n\n" + ("这是有事实依据的深度分析段落，拆解技术机制与实际影响。" * 25) + "\n\n"
            "## 第二节技术与制度博弈\n\n" + ("这是第二部分关于硬件识别与信号探测盲区的详细拆解。" * 25) + "\n\n"
            "## 第三节对国内考试与研学的镜鉴\n\n" + ("这是第三部分关于标准化考试机制演进的理性讨论。" * 25) + "\n\n"
            f"{config.ARTICLE_SIGNATURE}"
        )
        formatted = (
            "## 第一节具体冲突\n\n"
            "**{{核心判断一保留限定条件。}}**\n\n"
            + ("这是有 **事实依据** 的 **深度分析** 段落，涉及 **111 名** 考生与 **54 起** 案例。" * 22)
            + "\n\n> 第一条凝练的观点摘录，用来凸显核心反差而非照抄正文。\n\n"
            "【此处插入配图：exam hall security】\n\n"
            "## 第二节技术与制度博弈\n\n"
            + ("这是第二部分关于 **AI 眼镜** 与 **WiFi 探测** 盲区的详细拆解。" * 22)
            + "\n\n> 第二条凝练的观点摘录，点明技术对抗的边界。\n\n"
            "【此处插入配图：smart glasses hardware】\n\n"
            "## 第三节对国内考试与研学的镜鉴\n\n"
            + ("这是第三部分关于 **标准化考试** 与 **考研安检** 演进的理性讨论。" * 22)
            + "\n\n> 第三条凝练的观点摘录，聚焦人才筛选本身。\n\n"
            "【此处插入配图：university examination room】\n\n"
            f"{config.ARTICLE_SIGNATURE}"
        )

        topic = HotspotItem(title="测试热点话题", url="https://example.org/news", raw_content="原始短快讯。")
        with (
            patch.object(processor, "LLM_ENABLE_WEB_SEARCH", True),
            patch.object(processor, "research_topic_dossier", return_value="多信源深调研简报内容") as mock_research,
            patch.object(processor, "call_deepseek", return_value=prose) as mock_writer,
            patch.object(processor, "format_article_for_wechat", return_value=formatted) as mock_fmt,
        ):
            result = processor.generate_article(topic)

        mock_research.assert_called_once()
        mock_writer.assert_called_once()
        self.assertEqual(mock_writer.call_args.kwargs.get("model"), processor.LLM_WRITER_MODEL)
        self.assertEqual(mock_writer.call_args.kwargs.get("reasoning_effort"), processor.LLM_WRITER_REASONING_EFFORT)
        self.assertIn("多信源深调研简报内容", mock_writer.call_args.args[0])
        mock_fmt.assert_called_once()
        self.assertIn("【此处插入配图：", result)
        self.assertIn(config.ARTICLE_SIGNATURE, result)

    def test_critic_penalizes_ai_meta_language_disclaimers(self):
        from core.pipeline.critic import evaluate_article_quality

        meta_article = (
            "## 标题一\n\n"
            + ("这是 **测试** 段落，包含 **关键数字 100** 与 **具体细节**。" * 45)
            + "\n\n材料没有说明单个考点覆盖多少考生，材料在此处截断，其完整说法尚不可见。"
        )
        res = evaluate_article_quality(title="正常合规的测试标题", article_text=meta_article, article_type="hotspots")
        self.assertTrue(any("审稿" in i or "元话语" in i or "套话" in i for i in res["critic_issues"]), res)


if __name__ == "__main__":
    unittest.main()
