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


if __name__ == "__main__":
    unittest.main()
