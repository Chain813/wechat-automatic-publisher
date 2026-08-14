import unittest
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


if __name__ == "__main__":
    unittest.main()
