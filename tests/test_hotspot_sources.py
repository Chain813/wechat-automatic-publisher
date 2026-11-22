import time
import unittest
from unittest.mock import MagicMock, patch

import config
from core.plugins.base import HotspotItem


class TestExpandedHotspotSources(unittest.TestCase):
    def test_config_and_plugin_manager_register_new_direct_sources(self):
        from core.plugins.manager import plugin_manager

        self.assertIn("hackernews", config.NEWS_SOURCES)
        self.assertIn("wallstreetcn", config.NEWS_SOURCES)
        self.assertNotIn("https://36kr.com/feed", config.RSS_FEEDS)
        for expected_feed in (
            "https://www.infoq.cn/feed",
            "https://www.solidot.org/index.rss",
            "https://www.oschina.net/news/rss",
            "https://www.tmtpost.com/rss.xml",
            "https://www.leiphone.com/feed",
            "https://github.blog/feed/",
        ):
            self.assertIn(expected_feed, config.RSS_FEEDS)

        self.assertIsNotNone(plugin_manager.get_plugin("hackernews"))
        self.assertIsNotNone(plugin_manager.get_plugin("wallstreetcn"))

    def test_hackernews_plugin_primary_and_rss_fallback(self):
        from core.plugins import hotspots_sources as hs

        plugin = hs.HackerNewsPlugin()

        algolia_resp = MagicMock()
        algolia_resp.raise_for_status.return_value = None
        algolia_resp.json.return_value = {
            "hits": [
                {
                    "objectID": "42001",
                    "title": "Lean verification of the Riemann Hypothesis",
                    "url": "https://example.org/lean-rh",
                    "points": 812,
                    "num_comments": 240,
                    "created_at": "2026-11-22T01:00:00Z",
                }
            ]
        }

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", return_value=algolia_resp),
            patch.object(hs, "_mark_source_success") as mock_ok,
        ):
            items = plugin.fetch_data()

        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], HotspotItem)
        self.assertEqual(items[0].source_id, "hackernews")
        self.assertEqual(items[0].url, "https://example.org/lean-rh")
        self.assertIn("812", items[0].summary)
        mock_ok.assert_called_once_with("hackernews")

        # Algolia fails -> fallback to HN RSS
        rss_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><item>
          <title>Fallback HN Story</title>
          <link>https://example.org/fallback-hn</link>
        </item></channel></rss>"""
        rss_resp = MagicMock()
        rss_resp.raise_for_status.return_value = None
        rss_resp.content = rss_xml

        def side_effect(url, **kwargs):
            if "algolia" in url:
                raise RuntimeError("algolia down")
            return rss_resp

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", side_effect=side_effect),
            patch.object(hs, "_mark_source_success") as mock_ok2,
        ):
            fallback_items = plugin.fetch_data()

        self.assertEqual(len(fallback_items), 1)
        self.assertEqual(fallback_items[0].title, "Fallback HN Story")
        mock_ok2.assert_called_once_with("hackernews")

        # Both Algolia and RSS fail -> fallback to Firebase topstories
        fb_ids_resp = MagicMock()
        fb_ids_resp.raise_for_status.return_value = None
        fb_ids_resp.json.return_value = [99001]

        fb_item_resp = MagicMock()
        fb_item_resp.raise_for_status.return_value = None
        fb_item_resp.json.return_value = {
            "id": 99001,
            "title": "Firebase HN Story",
            "url": "https://example.org/fb-hn",
            "score": 321,
            "descendants": 88,
        }

        def fb_side_effect(url, **kwargs):
            if "algolia" in url or "ycombinator.com/rss" in url:
                raise RuntimeError("primary and rss down")
            if "topstories.json" in url:
                return fb_ids_resp
            return fb_item_resp

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", side_effect=fb_side_effect),
            patch.object(hs, "_mark_source_success") as mock_ok3,
        ):
            fb_items = plugin.fetch_data()

        self.assertEqual(len(fb_items), 1)
        self.assertEqual(fb_items[0].title, "Firebase HN Story")
        mock_ok3.assert_called_once_with("hackernews")

    def test_wallstreetcn_plugin_primary_and_fallback(self):
        from core.plugins import hotspots_sources as hs

        plugin = hs.WallStreetCNPlugin()
        live_resp = MagicMock()
        live_resp.raise_for_status.return_value = None
        live_resp.json.return_value = {
            "code": 20000,
            "data": {
                "items": [
                    {
                        "title": "英伟达新一代数据中心芯片开始向头部云厂送样",
                        "content_text": "英伟达新一代数据中心芯片开始向头部云厂送样，预计明年上半年量产。",
                        "uri": "https://wallstreetcn.com/livenews/12345",
                        "display_time": 1795320000,
                    },
                    {
                        "title": "",
                        "content_text": "美联储多位官员释放谨慎降息信号，市场重新定价明年利率路径。",
                        "uri": "https://wallstreetcn.com/livenews/12346",
                        "display_time": 1795320001,
                    },
                ]
            },
        }

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", return_value=live_resp),
            patch.object(hs, "_mark_source_success") as mock_ok,
        ):
            items = plugin.fetch_data()

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_id, "wallstreetcn")
        self.assertIn("英伟达", items[0].title)
        self.assertIn("美联储", items[1].title)
        mock_ok.assert_called_once_with("wallstreetcn")

        # Lives endpoint fails -> fallback to information-flow
        flow_resp = MagicMock()
        flow_resp.raise_for_status.return_value = None
        flow_resp.json.return_value = {
            "code": 20000,
            "data": {
                "items": [
                    {
                        "resource": {
                            "title": "台积电 2nm 产能明年全面爬坡，AI 客户订单排至年底",
                            "content_short": "供应链消息称 2nm 首批客户涵盖多家头部 AI 芯片厂。",
                            "uri": "https://wallstreetcn.com/articles/88888",
                        }
                    }
                ]
            },
        }

        def wscn_side_effect(url, **kwargs):
            if "/lives" in url:
                raise RuntimeError("lives endpoint error")
            return flow_resp

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", side_effect=wscn_side_effect),
            patch.object(hs, "_mark_source_success") as mock_ok2,
        ):
            fb_items = plugin.fetch_data()

        self.assertEqual(len(fb_items), 1)
        self.assertIn("台积电", fb_items[0].title)
        mock_ok2.assert_called_once_with("wallstreetcn")

    def test_rss_plugin_interleaves_feeds_fairly_and_isolates_failures(self):
        from core.plugins import hotspots_sources as hs

        def make_rss(prefix, count):
            items_xml = "".join(
                f"<item><title>{prefix} 新闻条目 {i}</title><link>https://example.org/{prefix}/{i}</link></item>"
                for i in range(count)
            )
            r = MagicMock()
            r.raise_for_status.return_value = None
            r.content = f'<?xml version="1.0"?><rss version="2.0"><channel>{items_xml}</channel></rss>'.encode("utf-8")
            return r

        def fake_get(url, **kwargs):
            if "feed1" in url:
                return make_rss("FeedA", 20)
            if "feed_broken" in url:
                raise RuntimeError("timeout")
            if "feed2" in url:
                return make_rss("FeedB", 20)
            return make_rss("FeedC", 5)

        plugin = hs.RssPlugin()
        with (
            patch.object(
                hs,
                "RSS_FEEDS",
                [
                    "https://feed1.test/rss",
                    "https://feed_broken.test/rss",
                    "https://feed2.test/rss",
                    "https://feed3.test/rss",
                ],
            ),
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", side_effect=fake_get),
            patch.object(hs, "_mark_source_success") as mock_ok,
        ):
            items = plugin.fetch_data()

        titles = [i.title for i in items]
        self.assertTrue(any(t.startswith("FeedA") for t in titles))
        self.assertTrue(any(t.startswith("FeedB") for t in titles))
        self.assertTrue(any(t.startswith("FeedC") for t in titles))
        # Round-robin interleaving: top 3 entries come from 3 distinct feeds
        self.assertTrue(titles[0].startswith("FeedA"))
        self.assertTrue(titles[1].startswith("FeedB"))
        self.assertTrue(titles[2].startswith("FeedC"))
        mock_ok.assert_called_once_with("rss")

    def test_circuit_breaker_auto_recovers_after_cooldown(self):
        from core.plugins import utils as pu

        pu.reset_source_health()
        with patch.object(pu, "SOURCE_CIRCUIT_COOLDOWN_SECONDS", 60):
            pu._mark_source_failure("test_src")
            pu._mark_source_failure("test_src")
            self.assertFalse(pu._is_source_disabled("test_src"))
            pu._mark_source_failure("test_src")
            self.assertTrue(pu._is_source_disabled("test_src"))

            # Simulate cooldown expiry -> auto half-open recovery
            with pu._source_health_lock:
                pu._source_health["test_src"]["disabled_until"] = time.time() - 1
            self.assertFalse(pu._is_source_disabled("test_src"))
            report = pu.get_source_health_report()
            self.assertEqual(report["test_src"]["status"], "healthy")

    def test_36kr_plugin_uses_gateway_api_primary(self):
        from core.plugins import hotspots_sources as hs

        plugin = hs.ThirtySixKrPlugin()
        gw_resp = MagicMock()
        gw_resp.raise_for_status.return_value = None
        gw_resp.json.return_value = {
            "code": 0,
            "data": {
                "itemList": [
                    {
                        "itemId": 4080470183253125,
                        "templateMaterial": {
                            "itemId": 4080470183253125,
                            "widgetTitle": "丘成桐回应AI辅助证明黎曼猜想",
                            "widgetContent": "丘成桐表示这是一个很兴奋的时代。",
                            "publishTime": 1795325448000,
                        },
                    }
                ]
            },
        }

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "post", return_value=gw_resp),
            patch.object(hs, "_mark_source_success") as mock_ok,
        ):
            items = plugin.fetch_data()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_id, "36kr")
        self.assertIn("丘成桐", items[0].title)
        self.assertEqual(items[0].url, "https://36kr.com/newsflashes/4080470183253125")
        mock_ok.assert_called_once_with("36kr")

    def test_huxiu_plugin_uses_rss_and_article_api_fallback(self):
        from core.plugins import hotspots_sources as hs

        plugin = hs.HuxiuPlugin()
        rss_resp = MagicMock()
        rss_resp.raise_for_status.return_value = None
        rss_resp.content = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b"<rss version=\"2.0\"><channel><item>"
            b"<title>\xe4\xb8\xad\xe5\x9b\xbdAI\xe5\x9c\xa8\xe6\xb5\xb7\xe5\xa4\x96\xef\xbc\x9a\xe6\x8e\x8c\xe5\xa3\xb0\xe5\xbe\x88\xe5\x93\x8d\xef\xbc\x8c\xe8\xb4\xa6\xe5\x8d\x95\xe8\xb0\x81\xe4\xbb\x98\xef\xbc\x9f</title>"
            b"<link>https://www.huxiu.com/article/4907475.html</link>"
            b"</item></channel></rss>"
        )

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", return_value=rss_resp),
            patch.object(hs, "_mark_source_success") as mock_ok,
        ):
            items = plugin.fetch_data()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source_id, "huxiu")
        self.assertIn("中国AI在海外", items[0].title)
        mock_ok.assert_called_once_with("huxiu")

        # RSS fails -> fallback to official articleList POST API
        api_resp = MagicMock()
        api_resp.raise_for_status.return_value = None
        api_resp.json.return_value = {
            "success": True,
            "data": {
                "dataList": [
                    {
                        "aid": "4907475",
                        "title": "大模型推理成本一年降九成，云厂商如何重构定价体系",
                        "share_url": "https://m.huxiu.com/article/4907475.html",
                    }
                ]
            },
        }

        with (
            patch.object(hs, "_is_source_disabled", return_value=False),
            patch.object(hs.HTTP_SESSION, "get", side_effect=RuntimeError("rss down")),
            patch.object(hs.HTTP_SESSION, "post", return_value=api_resp),
            patch.object(hs, "_mark_source_success") as mock_ok2,
        ):
            fb_items = plugin.fetch_data()

        self.assertEqual(len(fb_items), 1)
        self.assertIn("推理成本", fb_items[0].title)
        self.assertEqual(fb_items[0].url, "https://www.huxiu.com/article/4907475.html")
        mock_ok2.assert_called_once_with("huxiu")


if __name__ == "__main__":
    unittest.main()
