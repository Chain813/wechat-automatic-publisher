"""
热点事实核验与检索基座模块
支持从 DuckDuckGo (HTML / Lite) 及公开搜索引擎提取权威新闻标题与片段，
并对一手信源正文与外部检索内容进行清洗、拼接与结构化事实基座构建。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup
from loguru import logger
import requests

from config import ENABLE_FACT_SEARCH, MAX_FACT_SNIPPETS

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _clean_ddg_url(href: str) -> str:
    """提取 DuckDuckGo 跳转链接中的真实目标 URL"""
    if not href:
        return ""
    if "uddg=" in href:
        try:
            parsed = urllib.parse.urlsplit(href)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                return qs["uddg"][0]
        except Exception:
            pass
    return href


def parse_duckduckgo_html(html_text: str, max_results: int = 4) -> List[Dict[str, str]]:
    """
    解析 DuckDuckGo HTML / Lite 搜索结果页面
    """
    if not html_text:
        return []

    results: List[Dict[str, str]] = []
    soup = BeautifulSoup(html_text, "html.parser")

    # 1. 尝试 DuckDuckGo HTML 结构 (.web-result, .result, .result__body)
    containers = soup.find_all("div", class_=re.compile(r"\bresult\b|\bweb-result\b"))
    if not containers:
        containers = soup.find_all("div", class_="result__body")

    for c in containers:
        # 跳过广告或反爬异常提示
        classes = c.get("class", [])
        if "result--ad" in classes or any("anomaly" in cls for cls in classes):
            continue

        title_tag = c.find("a", class_="result__a") or c.find("h2", class_="result__title")
        snippet_tag = (
            c.find("a", class_="result__snippet")
            or c.find("div", class_="result__snippet")
            or c.find("span", class_="result__snippet")
        )

        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)
        href = title_tag.get("href", "")
        url = _clean_ddg_url(href)
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

        if title and (snippet or url):
            results.append({
                "title": title,
                "snippet": snippet,
                "url": url,
            })
            if len(results) >= max_results:
                return results

    if results:
        return results

    # 2. 尝试 DuckDuckGo Lite 结构
    for a in soup.find_all("a", class_="result-link"):
        title = a.get_text(strip=True)
        url = _clean_ddg_url(a.get("href", ""))
        snippet = ""
        tr = a.find_parent("tr")
        if tr:
            next_tr = tr.find_next_sibling("tr")
            if next_tr:
                snippet_td = next_tr.find("td", class_="result-snippet")
                if snippet_td:
                    snippet = snippet_td.get_text(strip=True)

        if title:
            results.append({
                "title": title,
                "snippet": snippet,
                "url": url,
            })
            if len(results) >= max_results:
                return results

    return results


def parse_bing_html(html_text: str, max_results: int = 4) -> List[Dict[str, str]]:
    """
    解析 Bing 搜索结果页面作为公开引擎兜底
    """
    if not html_text:
        return []

    results: List[Dict[str, str]] = []
    soup = BeautifulSoup(html_text, "html.parser")

    items = soup.find_all("li", class_="b_algo")
    for item in items:
        h2 = item.find("h2")
        if not h2:
            continue
        a = h2.find("a")
        if not a:
            continue

        title = a.get_text(strip=True)
        url = a.get("href", "").strip()

        # 提取摘要
        snippet_elem = item.find("p") or item.find("div", class_="b_caption")
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        if title:
            results.append({
                "title": title,
                "snippet": snippet,
                "url": url,
            })
            if len(results) >= max_results:
                break

    return results


def search_topic_facts(query: Any, max_results: Optional[int] = None) -> List[Dict[str, str]]:
    """
    轻量从公开引擎（DuckDuckGo html/lite，兜底公开搜索引擎）提取权威新闻标题与片段。
    异常安全捕获，失败返回空列表。

    :param query: 搜索关键词或 HotspotItem 对象
    :param max_results: 最大返回条数，默认使用 MAX_FACT_SNIPPETS
    :return: 包含 title, snippet, url 的字典列表
    """
    if not ENABLE_FACT_SEARCH:
        logger.debug("事实检索已通过配置关闭 (ENABLE_FACT_SEARCH=False)")
        return []

    if isinstance(query, str):
        search_query = query.strip()
    elif hasattr(query, "title") and isinstance(query.title, str):
        search_query = query.title.strip()
    elif query is not None:
        search_query = str(query).strip()
    else:
        search_query = ""

    if not search_query:
        return []

    limit = max_results if max_results is not None else MAX_FACT_SNIPPETS
    if limit <= 0:
        return []

    try:
        # 1. 优先尝试 DuckDuckGo HTML 搜索
        ddg_resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": search_query, "b": ""},
            headers=DEFAULT_HEADERS,
            timeout=8,
        )
        if ddg_resp.status_code == 200 and ddg_resp.text:
            ddg_results = parse_duckduckgo_html(ddg_resp.text, limit)
            if ddg_results:
                return ddg_results[:limit]

        # 2. 尝试 DuckDuckGo Lite 搜索
        ddg_lite_resp = requests.post(
            "https://lite.duckduckgo.com/lite/",
            data={"q": search_query},
            headers=DEFAULT_HEADERS,
            timeout=8,
        )
        if ddg_lite_resp.status_code == 200 and ddg_lite_resp.text:
            ddg_lite_results = parse_duckduckgo_html(ddg_lite_resp.text, limit)
            if ddg_lite_results:
                return ddg_lite_results[:limit]

        # 3. 公开引擎兜底（Bing HTML）
        bing_resp = requests.get(
            f"https://cn.bing.com/search?q={urllib.parse.quote(search_query)}",
            headers=DEFAULT_HEADERS,
            timeout=8,
        )
        if bing_resp.status_code == 200 and bing_resp.text:
            bing_results = parse_bing_html(bing_resp.text, limit)
            if bing_results:
                return bing_results[:limit]

    except Exception as e:
        logger.warning(f"事实检索异常 ({search_query}): {e}")

    return []


def clean_search_snippets(raw_results: Any) -> str:
    """
    清洗并拼接检索到的事实片段为结构化文本。
    :param raw_results: 搜索结果（可为字典列表、字符串列表、单字典或单字符串）
    :return: 规范格式化的 Markdown 事实片段文本
    """
    if not raw_results:
        return ""

    if isinstance(raw_results, str):
        return raw_results.strip()

    if isinstance(raw_results, dict):
        raw_results = [raw_results]

    if not isinstance(raw_results, (list, tuple)):
        return str(raw_results).strip()

    formatted_items = []
    for item in raw_results:
        if isinstance(item, dict):
            title = (item.get("title") or "").strip()
            snippet = (item.get("snippet") or item.get("summary") or item.get("content") or "").strip()
            url = (item.get("url") or item.get("link") or "").strip()

            lines = []
            if title:
                lines.append(f"- 标题: {title}")
                if snippet:
                    lines.append(f"  摘要: {snippet}")
            elif snippet:
                lines.append(f"- 摘要: {snippet}")

            if url:
                if lines:
                    lines.append(f"  来源: {url}")
                else:
                    lines.append(f"- 来源: {url}")

            if lines:
                formatted_items.append("\n".join(lines))
        elif isinstance(item, str) and item.strip():
            formatted_items.append(f"- {item.strip()}")

    return "\n\n".join(formatted_items).strip()


def build_fact_context(topic: Any, raw_content: str = "", search_results: Any = None) -> str:
    """
    组合一手正文与外部检索，构建真实事实基座。

    :param topic: 选题名称或 HotspotItem
    :param raw_content: 采集器抓取的一手正文内容
    :param search_results: 外部搜索引擎提取的事实结果（列表或已清洗文本）
    :return: 结构化事实上下文 Markdown 字符串
    """
    topic_str = ""
    if isinstance(topic, str):
        topic_str = topic.strip()
    elif hasattr(topic, "title") and isinstance(topic.title, str):
        topic_str = topic.title.strip()
        if not raw_content and hasattr(topic, "raw_content") and topic.raw_content:
            raw_content = topic.raw_content
    elif topic is not None:
        topic_str = str(topic).strip()

    raw_content_str = (raw_content or "").strip()
    search_text = clean_search_snippets(search_results)

    if not raw_content_str and not search_text:
        return ""

    sections = [
        "## 【事实基座与参考背景】",
    ]
    if topic_str:
        sections.append(f"核心选题：{topic_str}")

    if raw_content_str:
        sections.append("### 一手信源参考正文")
        sections.append(raw_content_str)

    if search_text:
        sections.append("### 外部权威检索与补充事实")
        sections.append(search_text)

    return "\n\n".join(sections).strip()
