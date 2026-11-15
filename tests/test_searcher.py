import pytest
from unittest.mock import patch, MagicMock
import requests

from core.plugins.base import HotspotItem
from core.hotspots.searcher import (
    search_topic_facts,
    clean_search_snippets,
    build_fact_context,
    parse_duckduckgo_html,
    parse_bing_html,
    _clean_ddg_url,
)


class TestCleanSearchSnippets:
    def test_empty_or_none(self):
        assert clean_search_snippets("") == ""
        assert clean_search_snippets(None) == ""
        assert clean_search_snippets([]) == ""
        assert clean_search_snippets({}) == ""

    def test_single_string_passthrough(self):
        text = "- 标题: 测试\n  摘要: 内容"
        assert clean_search_snippets(text) == text
        assert clean_search_snippets("   单行事实文本   ") == "单行事实文本"

    def test_list_of_strings(self):
        raw = ["事实1: 芯片架构突破", "事实2: 供应链自主化"]
        result = clean_search_snippets(raw)
        assert "- 事实1: 芯片架构突破" in result
        assert "- 事实2: 供应链自主化" in result

    def test_list_of_dicts_standard(self):
        raw = [
            {
                "title": "英伟达发布新一代AI芯片",
                "snippet": "性能较上一代提升3倍，能效比显著优化。",
                "url": "https://example.com/news/1",
            },
            {
                "title": "大模型推理成本大幅下降",
                "snippet": "最新基准测试显示推理价格下调60%。",
                "url": "https://example.com/news/2",
            },
        ]
        result = clean_search_snippets(raw)
        assert "- 标题: 英伟达发布新一代AI芯片" in result
        assert "  摘要: 性能较上一代提升3倍，能效比显著优化。" in result
        assert "  来源: https://example.com/news/1" in result
        assert "- 标题: 大模型推理成本大幅下降" in result
        assert "  摘要: 最新基准测试显示推理价格下调60%。" in result
        assert "  来源: https://example.com/news/2" in result

    def test_dict_with_alias_fields(self):
        raw = {
            "title": "芯片出口管制新规",
            "summary": "有关部门发布最新行业政策导向。",
            "link": "https://example.com/policy/123",
        }
        result = clean_search_snippets(raw)
        assert "- 标题: 芯片出口管制新规" in result
        assert "  摘要: 有关部门发布最新行业政策导向。" in result
        assert "  来源: https://example.com/policy/123" in result

    def test_dict_partial_fields(self):
        # 仅有标题
        r1 = clean_search_snippets([{"title": "纯标题热点"}])
        assert r1 == "- 标题: 纯标题热点"

        # 仅有摘要
        r2 = clean_search_snippets([{"snippet": "纯摘要内容"}])
        assert r2 == "- 摘要: 纯摘要内容"


class TestBuildFactContext:
    def test_all_empty(self):
        assert build_fact_context("选题测试", "", None) == ""
        assert build_fact_context("选题测试", "", []) == ""
        assert build_fact_context("", "", None) == ""

    def test_with_raw_content_only(self):
        topic = "国产先进制程突破"
        raw_content = "业内专家指出，国产EDA和关键材料正在加速落地验证。"
        context = build_fact_context(topic, raw_content=raw_content)

        assert "## 【事实基座与参考背景】" in context
        assert f"核心选题：{topic}" in context
        assert "### 一手信源参考正文" in context
        assert raw_content in context
        assert "### 外部权威检索与补充事实" not in context

    def test_with_search_results_only(self):
        topic = "具身智能产业报告"
        search_results = [
            {
                "title": "机器人产业链进入量产前夜",
                "snippet": "多个核心零部件良品率攀升。",
                "url": "https://example.com/robot",
            }
        ]
        context = build_fact_context(topic, raw_content="", search_results=search_results)

        assert "## 【事实基座与参考背景】" in context
        assert f"核心选题：{topic}" in context
        assert "### 一手信源参考正文" not in context
        assert "### 外部权威检索与补充事实" in context
        assert "- 标题: 机器人产业链进入量产前夜" in context
        assert "  摘要: 多个核心零部件良品率攀升。" in context

    def test_with_both_content_and_search(self):
        topic = "AI开源生态演进"
        raw_content = "一手采集新闻：开源社区近期涌现多款重量级多模态模型。"
        search_results = [
            {"title": "模型轻量化加速", "snippet": "边缘端运行效率持续提高。"}
        ]
        context = build_fact_context(topic, raw_content=raw_content, search_results=search_results)

        assert "## 【事实基座与参考背景】" in context
        assert f"核心选题：{topic}" in context
        assert "### 一手信源参考正文" in context
        assert raw_content in context
        assert "### 外部权威检索与补充事实" in context
        assert "- 标题: 模型轻量化加速" in context

    def test_with_hotspot_item_object(self):
        item = HotspotItem(
            title="量子计算云平台上线",
            url="https://example.com/quantum",
            source_id="ithome",
            raw_content="一手抓取的量子平台详细正文介绍...",
        )
        context = build_fact_context(item)

        assert "核心选题：量子计算云平台上线" in context
        assert "### 一手信源参考正文" in context
        assert "一手抓取的量子平台详细正文介绍..." in context


class TestDuckDuckGoParsing:
    def test_clean_ddg_url(self):
        raw_href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.ithome.com%2F0%2F123%2F456.htm&rut=..."
        cleaned = _clean_ddg_url(raw_href)
        assert cleaned == "https://www.ithome.com/0/123/456.htm"

        normal_href = "https://example.com/direct"
        assert _clean_ddg_url(normal_href) == normal_href
        assert _clean_ddg_url("") == ""

    def test_parse_ddg_html_results(self):
        mock_html = """
        <html>
        <body>
            <div class="result results_links results_links_deep web-result">
                <div class="links_main links_deep result__body">
                    <h2 class="result__title">
                        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.com%2Fa1">新闻标题A</a>
                    </h2>
                    <a class="result__snippet" href="#">新闻摘要A内容，描述了重要进展。</a>
                </div>
            </div>
            <div class="result results_links results_links_deep web-result">
                <div class="links_main links_deep result__body">
                    <h2 class="result__title">
                        <a class="result__a" href="https://news.com/a2">新闻标题B</a>
                    </h2>
                    <div class="result__snippet">新闻摘要B内容。</div>
                </div>
            </div>
            <div class="result result--ad">
                <a class="result__a" href="https://ad.com">广告标题</a>
            </div>
        </body>
        </html>
        """
        results = parse_duckduckgo_html(mock_html, max_results=4)
        assert len(results) == 2
        assert results[0]["title"] == "新闻标题A"
        assert results[0]["snippet"] == "新闻摘要A内容，描述了重要进展。"
        assert results[0]["url"] == "https://news.com/a1"
        assert results[1]["title"] == "新闻标题B"
        assert results[1]["url"] == "https://news.com/a2"

    def test_parse_ddg_lite_results(self):
        mock_html = """
        <html>
        <body>
            <table>
                <tr>
                    <td>1.</td>
                    <td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Flite.com%2F1">Lite新闻标题</a></td>
                </tr>
                <tr>
                    <td>&nbsp;</td>
                    <td class="result-snippet">Lite新闻摘要内容</td>
                </tr>
            </table>
        </body>
        </html>
        """
        results = parse_duckduckgo_html(mock_html, max_results=4)
        assert len(results) == 1
        assert results[0]["title"] == "Lite新闻标题"
        assert results[0]["snippet"] == "Lite新闻摘要内容"
        assert results[0]["url"] == "https://lite.com/1"

    def test_parse_empty_html(self):
        assert parse_duckduckgo_html("") == []
        assert parse_duckduckgo_html("<html><body></body></html>") == []


class TestSearchTopicFacts:
    def test_empty_query(self):
        assert search_topic_facts("") == []
        assert search_topic_facts("   ") == []
        assert search_topic_facts(None) == []

    @patch("core.hotspots.searcher.ENABLE_FACT_SEARCH", False)
    def test_disabled_by_config(self):
        assert search_topic_facts("人工智能") == []

    def test_invalid_max_results(self):
        assert search_topic_facts("人工智能", max_results=0) == []
        assert search_topic_facts("人工智能", max_results=-1) == []

    @patch("core.hotspots.searcher.requests.get", side_effect=requests.RequestException("Bing disabled"))
    @patch("core.hotspots.searcher.requests.post")
    def test_search_exception_safe(self, mock_post, mock_get):
        mock_post.side_effect = requests.RequestException("网络连接异常超时")
        # 异常应被安全捕获，返回空列表，不抛异常
        results = search_topic_facts("重大科技突破")
        assert results == []

    @patch("core.hotspots.searcher.requests.get", side_effect=requests.RequestException("Bing fallback to DDG"))
    @patch("core.hotspots.searcher.requests.post")
    def test_search_success_mock(self, mock_post, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <div class="result web-result">
            <h2 class="result__title">
                <a class="result__a" href="https://example.com/target">权威发布：新规实施</a>
            </h2>
            <div class="result__snippet">自即日起正式执行新标准。</div>
        </div>
        """
        mock_post.return_value = mock_response

        results = search_topic_facts("新规", max_results=2)
        assert len(results) == 1
        assert results[0]["title"] == "权威发布：新规实施"
        assert results[0]["snippet"] == "自即日起正式执行新标准。"
        assert results[0]["url"] == "https://example.com/target"

    def test_search_with_hotspot_item(self):
        item = HotspotItem(title="国产操作系统新版发布")
        with patch("core.hotspots.searcher.requests.get", side_effect=requests.RequestException("Bing fallback to DDG")), \
             patch("core.hotspots.searcher.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = """
            <div class="result web-result">
                <a class="result__a" href="https://os.com">系统发布报道</a>
                <span class="result__snippet">内核全面升级</span>
            </div>
            """
            mock_post.return_value = mock_resp
            results = search_topic_facts(item, max_results=1)
            assert len(results) == 1
            assert results[0]["title"] == "系统发布报道"
