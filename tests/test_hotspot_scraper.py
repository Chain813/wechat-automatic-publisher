import pytest
from unittest.mock import patch, MagicMock

from core.plugins.base import HotspotItem
from core.hotspots.scraper import extract_article_content
from core.plugins.hotspots_sources import ITHomePlugin, ThirtySixKrPlugin, RssPlugin, PoliticsPlugin
from core.hotspots.collector import fetch_all_hotspots_parallel, fetch_all_hotspot_items


class TestHotspotItem:
    def test_hotspot_item_defaults(self):
        item = HotspotItem(title="测试标题")
        assert item.title == "测试标题"
        assert item.url == ""
        assert item.source_id == ""
        assert item.summary == ""
        assert item.publish_time is None
        assert item.raw_content == ""
        assert item.tier == 2

    def test_hotspot_item_custom_fields(self):
        item = HotspotItem(
            title="深度解读",
            url="https://example.com/article/1",
            source_id="ithome",
            summary="这是一篇测试摘要",
            publish_time="2026-10-08T12:00:00",
            raw_content="正文内容...",
            tier=1
        )
        assert item.title == "深度解读"
        assert item.url == "https://example.com/article/1"
        assert item.source_id == "ithome"
        assert item.summary == "这是一篇测试摘要"
        assert item.publish_time == "2026-10-08T12:00:00"
        assert item.raw_content == "正文内容..."
        assert item.tier == 1

    def test_hotspot_item_str_compatibility(self):
        item = HotspotItem(title="  前沿科技热点  ")
        assert str(item) == "  前沿科技热点  "
        assert len(item) == len("  前沿科技热点  ")
        assert item.strip() == "前沿科技热点"
        assert f"标题: {item}" == "标题:   前沿科技热点  "


class TestArticleScraper:
    def test_extract_empty_or_none_url(self):
        assert extract_article_content("") == ""
        assert extract_article_content(None) == ""
        assert extract_article_content("   ") == ""

    @patch("core.hotspots.scraper.trafilatura.fetch_url")
    @patch("core.hotspots.scraper.trafilatura.extract")
    def test_extract_success(self, mock_extract, mock_fetch):
        mock_fetch.return_value = "<html><body><p>文章主要内容</p></body></html>"
        mock_extract.return_value = "文章主要内容"

        content = extract_article_content("https://example.com/news/1")
        assert content == "文章主要内容"
        mock_fetch.assert_called_once_with("https://example.com/news/1")
        mock_extract.assert_called_once()

    @patch("core.hotspots.scraper.trafilatura.fetch_url")
    def test_extract_fetch_url_none(self, mock_fetch):
        mock_fetch.return_value = None
        content = extract_article_content("https://example.com/404")
        assert content == ""

    @patch("core.hotspots.scraper.trafilatura.fetch_url")
    @patch("core.hotspots.scraper.trafilatura.extract")
    def test_extract_max_chars_truncation(self, mock_extract, mock_fetch):
        long_text = "A" * 3000
        mock_fetch.return_value = "<html>content</html>"
        mock_extract.return_value = long_text

        content = extract_article_content("https://example.com/long", max_chars=2500)
        assert len(content) == 2500
        assert content == "A" * 2500

    @patch("core.hotspots.scraper.trafilatura.fetch_url", side_effect=Exception("Network error"))
    def test_extract_exception_handling(self, mock_fetch):
        content = extract_article_content("https://example.com/error")
        assert content == ""


class TestPluginHotspotItemOutput:
    @patch("core.plugins.hotspots_sources.HTTP_SESSION.get")
    def test_ithome_rss_returns_hotspot_items(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0">
            <channel>
                <title>ITHome</title>
                <item>
                    <title>2026年最新AI芯片架构发布</title>
                    <link>https://www.ithome.com/0/123/456.htm</link>
                    <description>全新芯片性能提升300%</description>
                    <pubDate>Mon, 08 Oct 2026 10:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>""".encode("utf-8")
        mock_get.return_value = mock_resp

        plugin = ITHomePlugin()
        items = plugin.fetch_data()
        assert len(items) > 0
        first = items[0]
        assert isinstance(first, HotspotItem)
        assert first.title == "2026年最新AI芯片架构发布"
        assert first.url == "https://www.ithome.com/0/123/456.htm"
        assert "全新芯片" in first.summary
        assert first.source_id == "ithome"

    @patch("core.plugins.hotspots_sources.HTTP_SESSION.get")
    def test_36kr_rss_returns_hotspot_items(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0">
            <channel>
                <title>36Kr</title>
                <item>
                    <title>大模型落地应用最新进展</title>
                    <link>https://36kr.com/p/123456</link>
                    <description>企业级智能体迎来爆发</description>
                    <pubDate>Mon, 08 Oct 2026 10:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>""".encode("utf-8")
        mock_get.return_value = mock_resp

        plugin = ThirtySixKrPlugin()
        items = plugin.fetch_data()
        assert len(items) > 0
        first = items[0]
        assert isinstance(first, HotspotItem)
        assert first.title == "大模型落地应用最新进展"
        assert first.url == "https://36kr.com/p/123456"
        assert "企业级智能体" in first.summary
        assert first.source_id == "36kr"


class TestCollectorCompatibility:
    @patch("core.hotspots.collector.plugin_manager.get_plugin")
    @patch("core.hotspots.collector.NEWS_SOURCES", ["ithome", "weibo"])
    def test_collector_mixed_hotspot_item_and_str(self, mock_get_plugin):
        # mock ithome plugin returning HotspotItem
        plugin_ithome = MagicMock()
        plugin_ithome.display_name = "IT之家"
        plugin_ithome.fetch_data.return_value = [
            HotspotItem(title="全新大模型技术突破", url="https://example.com/1", source_id="ithome")
        ]

        # mock weibo plugin returning legacy str
        plugin_weibo = MagicMock()
        plugin_weibo.display_name = "微博热搜"
        plugin_weibo.fetch_data.return_value = ["今日科技大事件"]

        def side_effect(src):
            if src == "ithome":
                return plugin_ithome
            if src == "weibo":
                return plugin_weibo
            return None

        mock_get_plugin.side_effect = side_effect

        output_str = fetch_all_hotspots_parallel()
        assert "【IT之家】" in output_str
        assert "全新大模型技术突破" in output_str
        assert "【微博热搜】" in output_str
        assert "今日科技大事件" in output_str

        # Test structured items collector
        items = fetch_all_hotspot_items()
        assert len(items) == 2
        assert all(isinstance(i, HotspotItem) for i in items)
        assert items[0].title == "全新大模型技术突破"
        assert items[1].title == "今日科技大事件"
