import concurrent.futures
import json
import re
import time
import urllib.parse
from bs4 import BeautifulSoup
from loguru import logger
from typing import List, Any

from core.plugins.base import BaseSourcePlugin, HotspotItem
from config import NEWS_FRESHNESS_HOURS, NEWS_MAX_PER_SOURCE, API_60S_BASE, RSS_FEEDS
from core.plugins.utils import (
    _is_source_disabled,
    _mark_source_success,
    _mark_source_failure,
    get_headers,
    HTTP_SESSION,
    _is_entry_fresh,
    _is_title_fresh,
)

class ITHomePlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "ithome"

    @property
    def display_name(self) -> str:
        return "IT之家科技热点"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        try:
            import feedparser
            res = HTTP_SESSION.get("https://www.ithome.com/rss/", headers=get_headers(), timeout=10)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            if feed.entries:
                for entry in feed.entries[:15]:
                    title = entry.get("title", "").strip()
                    if title and len(title) > 3 and _is_entry_fresh(entry) and _is_title_fresh(title):
                        url = entry.get("link", "").strip()
                        summary = entry.get("summary", "") or entry.get("description", "")
                        pub_time = entry.get("published", "") or entry.get("updated", "")
                        topics.append(HotspotItem(
                            title=title,
                            url=url,
                            source_id=self.source_id,
                            summary=summary.strip(),
                            publish_time=pub_time,
                            tier=1
                        ))
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} RSS 失败: {e}，降级至 HTML")

        try:
            res = HTTP_SESSION.get("https://www.ithome.com/", headers=get_headers(), timeout=10)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select(".rt ul li a, .hot-list a, .sidebar-hot a")
            topics = []
            for item in items:
                text = item.get_text(strip=True)
                if len(text) > 3 and _is_title_fresh(text):
                    href = item.get("href", "").strip()
                    url = urllib.parse.urljoin("https://www.ithome.com/", href) if href else ""
                    topics.append(HotspotItem(
                        title=text,
                        url=url,
                        source_id=self.source_id,
                        tier=1
                    ))
            if topics:
                _mark_source_success(self.source_id)
            else:
                _mark_source_failure(self.source_id)
        except Exception as e:
            logger.warning(f"  {self.display_name} HTML 也失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class ThirtySixKrPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "36kr"

    @property
    def display_name(self) -> str:
        return "36氪商业与AI动态"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []

        # 主通道：36氪官方 Gateway 快讯流 JSON API（国内直连无 WAF）
        try:
            gw_headers = get_headers(referer="https://36kr.com/newsflashes")
            gw_headers["Content-Type"] = "application/json"
            gw_headers["Origin"] = "https://36kr.com"
            payload = {
                "partner_id": "web",
                "timestamp": int(time.time() * 1000),
                "param": {
                    "pageSize": max(NEWS_MAX_PER_SOURCE, 15),
                    "pageEvent": 0,
                    "siteId": 1,
                    "platformId": 2,
                },
            }
            res = HTTP_SESSION.post(
                "https://gateway.36kr.com/api/mis/nav/newsflash/flow",
                json=payload,
                headers=gw_headers,
                timeout=10,
            )
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", {}).get("itemList", []):
                mat = item.get("templateMaterial") or {}
                title = (mat.get("widgetTitle") or "").strip()
                if title and len(title) > 4 and _is_title_fresh(title):
                    item_id = mat.get("itemId") or item.get("itemId")
                    url = f"https://36kr.com/newsflashes/{item_id}" if item_id else ""
                    summary = (mat.get("widgetContent") or "").strip()[:240]
                    pub_time = str(mat.get("publishTime") or "")
                    topics.append(HotspotItem(
                        title=title,
                        url=url,
                        source_id=self.source_id,
                        summary=summary,
                        publish_time=pub_time,
                        tier=1,
                    ))
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} Gateway API 失败: {e}，降级至 RSS")

        # 备选通道 1：RSS
        try:
            import feedparser
            res = HTTP_SESSION.get("https://36kr.com/feed", headers=get_headers(), timeout=10)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            if feed.entries:
                for entry in feed.entries[:15]:
                    title = entry.get("title", "").strip()
                    if title and len(title) > 4 and _is_entry_fresh(entry) and _is_title_fresh(title):
                        url = entry.get("link", "").strip()
                        summary = entry.get("summary", "") or entry.get("description", "")
                        pub_time = entry.get("published", "") or entry.get("updated", "")
                        topics.append(HotspotItem(
                            title=title,
                            url=url,
                            source_id=self.source_id,
                            summary=summary.strip(),
                            publish_time=pub_time,
                            tier=1
                        ))
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} RSS 失败: {e}，降级至 HTML")

        # 备选通道 2：HTML（强制 UTF-8 解码并过滤 WAF 安全校验页）
        try:
            res = HTTP_SESSION.get("https://36kr.com/newsflashes", headers=get_headers(), timeout=10)
            res.raise_for_status()
            res.encoding = "utf-8"
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select(".item-title, .newsflash-title, [class*='title']")
            topics = []
            for item in items:
                text = item.get_text(strip=True)
                if (
                    len(text) > 4
                    and "安全检测" not in text
                    and "验证码" not in text
                    and _is_title_fresh(text)
                ):
                    href = item.get("href", "").strip() or (item.find_parent("a").get("href", "").strip() if item.find_parent("a") else "")
                    url = urllib.parse.urljoin("https://36kr.com", href) if href else ""
                    topics.append(HotspotItem(
                        title=text,
                        url=url,
                        source_id=self.source_id,
                        tier=1
                    ))
            if topics:
                _mark_source_success(self.source_id)
            else:
                _mark_source_failure(self.source_id)
        except Exception as e:
            logger.warning(f"  {self.display_name} HTML 也失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class BaiduPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "baidu"

    @property
    def display_name(self) -> str:
        return "百度实时热搜"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        try:
            api_url = "https://top.baidu.com/board?tab=realtime"
            headers = get_headers()
            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            res = HTTP_SESSION.get(api_url, headers=headers, timeout=10)
            res.raise_for_status()
            res.encoding = 'utf-8'
            match = re.search(r'<!--s-data:(.*?)-->', res.text)
            if match:
                data = json.loads(match.group(1))
                cards = data.get("data", {}).get("cards", [])
                for card in cards:
                    for item in card.get("content", []):
                        word = item.get("word", "") or item.get("query", "")
                        raw_url = item.get("rawUrl", "") or item.get("url", "")
                        desc = item.get("desc", "")
                        if word and len(word) > 1:
                            topics.append(HotspotItem(
                                title=word,
                                url=raw_url,
                                source_id=self.source_id,
                                summary=desc,
                                tier=2
                            ))
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} JSON 解析失败: {e}，降级至 HTML")

        try:
            res = HTTP_SESSION.get("https://top.baidu.com/board?tab=realtime", headers=get_headers(), timeout=10)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select(".c-single-text-ellipsis, .title_dIF3B, [class*='title']")
            for item in items:
                text = item.get_text(strip=True)
                if text and len(text) > 1:
                    href = item.get("href", "") or (item.find_parent("a").get("href", "") if item.find_parent("a") else "")
                    topics.append(HotspotItem(
                        title=text,
                        url=href,
                        source_id=self.source_id,
                        tier=2
                    ))
            if topics:
                _mark_source_success(self.source_id)
            else:
                _mark_source_failure(self.source_id)
        except Exception as e:
            logger.warning(f"  {self.display_name} HTML 也失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class ZhihuPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "zhihu"

    @property
    def display_name(self) -> str:
        return "知乎热榜"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        try:
            url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=20"
            res = HTTP_SESSION.get(url, headers=get_headers(referer="https://www.zhihu.com/hot"), timeout=10)
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", []):
                target = item.get("target", {})
                title = target.get("title", "")
                link = target.get("url", "")
                if not link and target.get("id"):
                    link = f"https://www.zhihu.com/question/{target.get('id')}"
                excerpt = target.get("excerpt", "")
                if title and len(title) > 1:
                    topics.append(HotspotItem(
                        title=title,
                        url=link,
                        source_id=self.source_id,
                        summary=excerpt,
                        tier=2
                    ))
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} 原生 API 失败: {e}，降级至 60s API")

        try:
            res = HTTP_SESSION.get(f"{API_60S_BASE}/zhihu", headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get("code") == 200:
                for item in data.get("data", []):
                    title = item.get("title", "").strip()
                    link = item.get("url", "").strip()
                    if title and len(title) > 1:
                        topics.append(HotspotItem(
                            title=title,
                            url=link,
                            source_id=self.source_id,
                            tier=2
                        ))
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} 60s API 也失败: {e}")
            
        return topics[:NEWS_MAX_PER_SOURCE]


class CsdnPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "csdn"

    @property
    def display_name(self) -> str:
        return "CSDN全站热榜"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        url = "https://blog.csdn.net/phoenix/web/blog/hot-rank?page=0&pageSize=20"
        topics = []
        try:
            res = HTTP_SESSION.get(url, headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", []):
                title = item.get("articleTitle", "").strip()
                link = item.get("articleDetailUrl", "").strip()
                desc = item.get("description", "").strip()
                if title:
                    topics.append(HotspotItem(
                        title=title,
                        url=link,
                        source_id=self.source_id,
                        summary=desc,
                        tier=2
                    ))
            _mark_source_success(self.source_id)
        except Exception as e:
            logger.warning(f"  {self.display_name}抓取失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class RssPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "rss"

    @property
    def display_name(self) -> str:
        return "RSS聚合精选"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        if not RSS_FEEDS:
            return []
        try:
            import feedparser
        except ImportError:
            logger.warning("  未安装 feedparser，无法解析 RSS")
            return []

        per_feed_limit = 6
        fallback_window_hours = max(NEWS_FRESHNESS_HOURS, 72) if NEWS_FRESHNESS_HOURS > 0 else 0

        def _fetch_single_feed(feed_url: str) -> List[HotspotItem]:
            try:
                res = HTTP_SESSION.get(feed_url, headers=get_headers(), timeout=8)
                res.raise_for_status()
                feed = feedparser.parse(res.content)
                entries = getattr(feed, "entries", None) or []
                if not entries:
                    logger.warning(f"  RSS 源 {feed_url} 返回空条目 (0 entries)")
                    return []

                fresh_items: List[HotspotItem] = []
                recent_fallback: List[HotspotItem] = []
                for entry in entries[:12]:
                    title = entry.get("title", "").strip()
                    if not title or len(title) <= 3 or not _is_title_fresh(title):
                        continue
                    url = entry.get("link", "").strip()
                    summary = (entry.get("summary", "") or entry.get("description", "")).strip()
                    pub_time = entry.get("published", "") or entry.get("updated", "")
                    item = HotspotItem(
                        title=title,
                        url=url,
                        source_id=self.source_id,
                        summary=summary[:300],
                        publish_time=pub_time,
                        tier=1,
                    )
                    if _is_entry_fresh(entry):
                        fresh_items.append(item)
                        if len(fresh_items) >= per_feed_limit:
                            break
                    elif fallback_window_hours > 0 and len(recent_fallback) < 2 and _is_entry_fresh(entry, max_hours=fallback_window_hours):
                        recent_fallback.append(item)
                return fresh_items or recent_fallback
            except Exception as e:
                logger.warning(f"  RSS 源 {feed_url} 解析失败: {e}")
                return []

        feed_buckets: dict[str, List[HotspotItem]] = {}
        workers = max(1, min(len(RSS_FEEDS), 8))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(_fetch_single_feed, url): url for url in RSS_FEEDS}
            for future in concurrent.futures.as_completed(future_map):
                url = future_map[future]
                try:
                    feed_buckets[url] = future.result()
                except Exception as e:
                    logger.warning(f"  RSS 源 {url} 并发抓取异常: {e}")
                    feed_buckets[url] = []

        # 按配置顺序轮询交错合并，确保高产源不挤占其它优质 RSS 源配额
        ordered_buckets = [feed_buckets.get(url, []) for url in RSS_FEEDS if feed_buckets.get(url)]
        max_total = max(NEWS_MAX_PER_SOURCE * 2, 30)
        topics: List[HotspotItem] = []
        seen_titles: set[str] = set()
        round_idx = 0
        while len(topics) < max_total:
            added_in_round = False
            for bucket in ordered_buckets:
                if round_idx < len(bucket):
                    item = bucket[round_idx]
                    norm_title = item.title.strip().lower()
                    if norm_title not in seen_titles:
                        seen_titles.add(norm_title)
                        topics.append(item)
                        if len(topics) >= max_total:
                            break
                    added_in_round = True
            if not added_in_round:
                break
            round_idx += 1

        if topics:
            _mark_source_success(self.source_id)
        else:
            _mark_source_failure(self.source_id)

        return topics


class PoliticsPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "politics"

    @property
    def display_name(self) -> str:
        return "时政科技交叉"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        has_success = False

        politics_sites = [
            ("https://www.guancha.cn/", "观察者网"),
        ]

        for site_url, site_name in politics_sites:
            try:
                res = HTTP_SESSION.get(site_url, headers=get_headers(referer=site_url), timeout=12)
                res.raise_for_status()
                res.encoding = 'utf-8'
                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.select("a[href*='newsDetail'], a[href*='news_detail'], a[href*='/20']")
                for link in links:
                    title = link.get_text(strip=True)
                    if title and 8 < len(title) < 80 and _is_title_fresh(title):
                        href = link.get("href", "").strip()
                        url = urllib.parse.urljoin(site_url, href) if href else ""
                        topics.append(HotspotItem(
                            title=title,
                            url=url,
                            source_id=self.source_id,
                            tier=1
                        ))
                if links:
                    has_success = True
            except Exception as e:
                logger.warning(f"  时政源 {site_name} 抓取失败: {e}")

        if not has_success:
            try:
                import feedparser
                rss_fallbacks = [
                    "https://www.thepaper.cn/rss_newsDetail_channel_25",
                ]
                for feed_url in rss_fallbacks:
                    try:
                        res = HTTP_SESSION.get(feed_url, headers=get_headers(), timeout=10)
                        res.raise_for_status()
                        feed = feedparser.parse(res.content)
                        if feed.entries:
                            has_success = True
                            for entry in feed.entries[:10]:
                                title = entry.get("title", "").strip()
                                if title and len(title) > 4 and _is_entry_fresh(entry) and _is_title_fresh(title):
                                    url = entry.get("link", "").strip()
                                    summary = entry.get("summary", "") or entry.get("description", "")
                                    pub_time = entry.get("published", "") or entry.get("updated", "")
                                    topics.append(HotspotItem(
                                        title=title,
                                        url=url,
                                        source_id=self.source_id,
                                        summary=summary.strip(),
                                        publish_time=pub_time,
                                        tier=1
                                    ))
                    except Exception as e:
                        logger.warning(f"  时政 RSS {feed_url} 失败: {e}")
            except ImportError:
                pass

        if has_success:
            _mark_source_success(self.source_id)
        else:
            _mark_source_failure(self.source_id)

        return topics[:NEWS_MAX_PER_SOURCE]


class ToutiaoPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "toutiao"

    @property
    def display_name(self) -> str:
        return "今日头条热榜"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        try:
            url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
            res = HTTP_SESSION.get(url, headers=get_headers(referer="https://www.toutiao.com/"), timeout=10)
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", []):
                title = item.get("Title", "").strip()
                link = item.get("Url", "").strip()
                if title and len(title) > 1:
                    topics.append(HotspotItem(
                        title=title,
                        url=link,
                        source_id=self.source_id,
                        tier=2
                    ))
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  头条原生 API 失败: {e}，降级至 60s API")

        try:
            res = HTTP_SESSION.get(f"{API_60S_BASE}/toutiao", headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get("code") == 200:
                for item in data.get("data", []):
                    title = item.get("title", "").strip()
                    url = item.get("url", "").strip()
                    if title and len(title) > 1:
                        topics.append(HotspotItem(
                            title=title,
                            url=url,
                            source_id=self.source_id,
                            tier=2
                        ))
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  头条 60s API 也失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class ThePaperPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "thepaper"

    @property
    def display_name(self) -> str:
        return "澎湃新闻"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        try:
            url = "https://www.thepaper.cn/"
            res = HTTP_SESSION.get(url, headers=get_headers(referer=url), timeout=12)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, "html.parser")
            links = soup.select("a[href*='newsDetail'], a[href*='news_detail']")
            for link in links:
                title = link.get_text(strip=True)
                if title and 8 < len(title) < 80 and _is_title_fresh(title):
                    href = link.get("href", "").strip()
                    full_url = urllib.parse.urljoin(url, href) if href else ""
                    topics.append(HotspotItem(
                        title=title,
                        url=full_url,
                        source_id=self.source_id,
                        tier=1
                    ))
            if topics:
                _mark_source_success(self.source_id)
            else:
                _mark_source_failure(self.source_id)
        except Exception as e:
            logger.warning(f"  {self.display_name}抓取失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class HuxiuPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "huxiu"

    @property
    def display_name(self) -> str:
        return "虎嗅网深度"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics: List[HotspotItem] = []
        seen_titles: set[str] = set()

        # 主通道：虎嗅官方 RSS（国内直连无阿里云 WAF，稳定返回 25+ 篇深度稿）
        try:
            import feedparser
            res = HTTP_SESSION.get("https://rss.huxiu.com/", headers=get_headers(), timeout=10)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            fallback_window = max(NEWS_FRESHNESS_HOURS, 72) if NEWS_FRESHNESS_HOURS > 0 else 0
            recent_fallback: List[HotspotItem] = []
            for entry in (getattr(feed, "entries", None) or [])[:25]:
                title = (entry.get("title") or "").strip()
                if not title or len(title) <= 6 or title in seen_titles or not _is_title_fresh(title):
                    continue
                seen_titles.add(title)
                item = HotspotItem(
                    title=title,
                    url=(entry.get("link") or "").strip(),
                    source_id=self.source_id,
                    summary=(entry.get("summary") or entry.get("description") or "").strip()[:240],
                    publish_time=entry.get("published") or entry.get("updated") or "",
                    tier=1,
                )
                if _is_entry_fresh(entry):
                    topics.append(item)
                elif fallback_window > 0 and len(recent_fallback) < 5 and _is_entry_fresh(entry, max_hours=fallback_window):
                    recent_fallback.append(item)
            if not topics and recent_fallback:
                topics = recent_fallback
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} RSS 主通道失败: {e}，降级至官方文章流 API")

        # 备选通道 1：虎嗅官方 articleList POST API
        try:
            api_headers = get_headers(referer="https://www.huxiu.com/")
            api_headers["Origin"] = "https://www.huxiu.com"
            res = HTTP_SESSION.post(
                "https://api-article.huxiu.com/web/article/articleList",
                data={
                    "platform": "www",
                    "recommend_time": int(time.time()),
                    "pagesize": max(NEWS_MAX_PER_SOURCE, 15),
                },
                headers=api_headers,
                timeout=10,
            )
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", {}).get("dataList", []):
                title = (item.get("title") or "").strip()
                if not title or len(title) <= 6 or title in seen_titles or not _is_title_fresh(title):
                    continue
                seen_titles.add(title)
                aid = str(item.get("aid") or "").strip()
                url = f"https://www.huxiu.com/article/{aid}.html" if aid else (item.get("share_url") or "").strip()
                topics.append(HotspotItem(
                    title=title,
                    url=url,
                    source_id=self.source_id,
                    summary=(item.get("summary") or "").strip()[:240],
                    publish_time=str(item.get("dateline") or ""),
                    tier=1,
                ))
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name} 官方 API 失败: {e}，降级至 HTML")

        # 备选通道 2：首页 HTML
        try:
            res = HTTP_SESSION.get("https://www.huxiu.com/", headers=get_headers(), timeout=12)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, "html.parser")
            links = soup.select("a[href*='/article/']")
            for link in links:
                title = link.get_text(strip=True)
                if title and 8 < len(title) < 80 and _is_title_fresh(title) and title not in seen_titles:
                    seen_titles.add(title)
                    href = link.get("href", "").strip()
                    full_url = urllib.parse.urljoin("https://www.huxiu.com/", href) if href else ""
                    topics.append(HotspotItem(
                        title=title,
                        url=full_url,
                        source_id=self.source_id,
                        tier=1
                    ))
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  {self.display_name}抓取失败: {e}，将尝试 Selenium 降级")

        # 降级至 Selenium 前先检测环境支持
        from utils.spider import is_browser_available
        if not is_browser_available():
            logger.info("  虎嗅网深度 HTTP 触发防护，当前环境未安装无头浏览器，安全跳过 Selenium 尝试")
            _mark_source_failure(self.source_id)
            return []
        return self._fetch_huxiu_selenium()

    def _fetch_huxiu_selenium(self) -> List[Any]:
        logger.info("  正在同步 虎嗅网 (Selenium 降级)...")
        browser = None
        topics = []
        seen_titles = set()
        try:
            from utils.spider import build_stealth_browser
            browser = build_stealth_browser(headless=True)
            browser.get("https://www.huxiu.com/")
            time.sleep(5)
            soup = BeautifulSoup(browser.page_source, "html.parser")
            links = soup.find_all("a")
            for a in links:
                href = a.get("href", "")
                if "/article/" in href:
                    title = a.get_text(strip=True)
                    if title and 8 < len(title) < 80 and _is_title_fresh(title) and title not in seen_titles:
                        seen_titles.add(title)
                        full_url = urllib.parse.urljoin("https://www.huxiu.com/", href) if href else ""
                        topics.append(HotspotItem(
                            title=title,
                            url=full_url,
                            source_id=self.source_id,
                            tier=1
                        ))
            if topics:
                _mark_source_success(self.source_id)
            else:
                _mark_source_failure(self.source_id)
        except Exception as e:
            logger.warning(f"  虎嗅 Selenium 抓取也失败: {e}")
            _mark_source_failure(self.source_id)
        finally:
            if browser:
                try:
                    browser.quit()
                except Exception:
                    pass
        return topics[:NEWS_MAX_PER_SOURCE]


class DouyinPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "douyin"

    @property
    def display_name(self) -> str:
        return "抖音热搜"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")
        topics = []
        try:
            res = HTTP_SESSION.get(f"{API_60S_BASE}/douyin", headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get("code") == 200:
                for item in data.get("data", []):
                    title = item.get("title", "").strip()
                    url = item.get("url", "").strip()
                    if title and len(title) > 1:
                        topics.append(HotspotItem(
                            title=title,
                            url=url,
                            source_id=self.source_id,
                            tier=2
                        ))
            if topics:
                _mark_source_success(self.source_id)
            else:
                _mark_source_failure(self.source_id)
        except Exception as e:
            logger.warning(f"  {self.display_name}抓取失败: {e}")
            _mark_source_failure(self.source_id)
        return topics[:NEWS_MAX_PER_SOURCE]


class WeiboPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "weibo"

    @property
    def display_name(self) -> str:
        return "微博实时热搜"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []

        logger.info(f"  正在同步 {self.display_name}...")
        topics = []

        try:
            headers = get_headers(referer="https://weibo.com/")
            res = HTTP_SESSION.get("https://weibo.com/ajax/side/hotSearch", headers=headers, timeout=10)
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", {}).get("realtime", []):
                word = item.get("word", "").strip()
                if word and len(word) > 1 and "公告" not in word:
                    url = f"https://s.weibo.com/weibo?q={urllib.parse.quote(word)}"
                    topics.append(HotspotItem(
                        title=word,
                        url=url,
                        source_id=self.source_id,
                        tier=2
                    ))
            if topics:
                _mark_source_success(self.source_id)
                return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  微博原生 API 失败: {e}，降级至 60s API")

        try:
            res = HTTP_SESSION.get(f"{API_60S_BASE}/weibo", headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            if data.get("code") == 200:
                for item in data.get("data", []):
                    title = item.get("title", "").strip()
                    url = item.get("url", "").strip()
                    if title and len(title) > 1:
                        topics.append(HotspotItem(
                            title=title,
                            url=url,
                            source_id=self.source_id,
                            tier=2
                        ))
                if topics:
                    _mark_source_success(self.source_id)
                    return topics[:NEWS_MAX_PER_SOURCE]
        except Exception as e:
            logger.warning(f"  微博 60s API 也失败: {e}，准备尝试 Selenium 降级")
            from utils.spider import is_browser_available
            if not is_browser_available():
                logger.info("  微博热搜 当前环境未安装无头浏览器，安全跳过 Selenium 尝试")
                _mark_source_failure(self.source_id)
                return []
            return self._fetch_weibo_selenium()
        
        return topics

    def _fetch_weibo_selenium(self):
        logger.info("  正在同步 微博 全网热搜 (Selenium 降级)...")
        browser = None
        topics = []
        try:
            from utils.spider import build_stealth_browser
            browser = build_stealth_browser(headless=True)
            browser.get("https://s.weibo.com/top/summary")
            time.sleep(4)
            soup = BeautifulSoup(browser.page_source, "html.parser")
            items = soup.select(".td-02 a")
            for item in items:
                t = item.get_text(strip=True)
                if t and t != "公告" and not t.startswith("直播"):
                    href = item.get("href", "")
                    full_url = urllib.parse.urljoin("https://s.weibo.com", href) if href else ""
                    topics.append(HotspotItem(
                        title=t,
                        url=full_url,
                        source_id=self.source_id,
                        tier=2
                    ))
            _mark_source_success(self.source_id)
        except Exception as e:
            logger.warning(f"  微博 Selenium 抓取也失败: {e}")
            _mark_source_failure(self.source_id)
        finally:
            if browser:
                try:
                    browser.quit()
                except Exception:
                    pass
        return topics[:NEWS_MAX_PER_SOURCE]


class HackerNewsPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "hackernews"

    @property
    def display_name(self) -> str:
        return "Hacker News 一手技术"

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")

        # 主通道：Algolia HN Front Page API（国内服务器实测直连 ~600ms，自带热度与评论数）
        topics = self._fetch_from_algolia()
        if topics:
            _mark_source_success(self.source_id)
            return topics[:NEWS_MAX_PER_SOURCE]

        # 备选通道 1：官方 HN RSS
        topics = self._fetch_from_rss()
        if topics:
            _mark_source_success(self.source_id)
            return topics[:NEWS_MAX_PER_SOURCE]

        # 备选通道 2：官方 Firebase HN Top Stories API
        topics = self._fetch_from_firebase()
        if topics:
            _mark_source_success(self.source_id)
            return topics[:NEWS_MAX_PER_SOURCE]

        _mark_source_failure(self.source_id)
        return []

    def _fetch_from_algolia(self) -> List[HotspotItem]:
        topics: List[HotspotItem] = []
        try:
            url = f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={max(NEWS_MAX_PER_SOURCE, 15)}"
            res = HTTP_SESSION.get(url, headers=get_headers(), timeout=10)
            res.raise_for_status()
            data = res.json()
            for hit in data.get("hits", []):
                title = (hit.get("title") or "").strip()
                if not title or len(title) <= 3 or not _is_title_fresh(title):
                    continue
                object_id = hit.get("objectID", "")
                story_url = (hit.get("url") or "").strip()
                if not story_url and object_id:
                    story_url = f"https://news.ycombinator.com/item?id={object_id}"
                points = hit.get("points") or 0
                comments = hit.get("num_comments") or 0
                topics.append(
                    HotspotItem(
                        title=title,
                        url=story_url,
                        source_id=self.source_id,
                        summary=f"HN 热度 {points} 分 / {comments} 评论",
                        publish_time=hit.get("created_at") or "",
                        tier=1,
                    )
                )
        except Exception as e:
            logger.warning(f"  {self.display_name} Algolia 主通道失败: {e}，降级至官方 RSS")
        return topics

    def _fetch_from_rss(self) -> List[HotspotItem]:
        topics: List[HotspotItem] = []
        try:
            import feedparser

            res = HTTP_SESSION.get("https://news.ycombinator.com/rss", headers=get_headers(), timeout=10)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            for entry in (getattr(feed, "entries", None) or [])[:NEWS_MAX_PER_SOURCE]:
                title = (entry.get("title") or "").strip()
                if not title or len(title) <= 3 or not _is_title_fresh(title):
                    continue
                topics.append(
                    HotspotItem(
                        title=title,
                        url=(entry.get("link") or "").strip(),
                        source_id=self.source_id,
                        summary=(entry.get("summary") or "").strip()[:240],
                        publish_time=entry.get("published") or "",
                        tier=1,
                    )
                )
        except Exception as e:
            logger.warning(f"  {self.display_name} RSS 备选通道失败: {e}，降级至 Firebase API")
        return topics

    def _fetch_from_firebase(self) -> List[HotspotItem]:
        topics: List[HotspotItem] = []
        try:
            res = HTTP_SESSION.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json",
                headers=get_headers(),
                timeout=10,
            )
            res.raise_for_status()
            story_ids = (res.json() or [])[: min(NEWS_MAX_PER_SOURCE, 10)]
            if not story_ids:
                return []

            def _fetch_item(sid: int) -> Any:
                try:
                    r = HTTP_SESSION.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                        headers=get_headers(),
                        timeout=8,
                    )
                    r.raise_for_status()
                    return r.json()
                except Exception:
                    return None

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(story_ids), 6)) as executor:
                items = list(executor.map(_fetch_item, story_ids))

            for item in items:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                if not title or len(title) <= 3 or not _is_title_fresh(title):
                    continue
                sid = item.get("id", "")
                story_url = (item.get("url") or "").strip() or f"https://news.ycombinator.com/item?id={sid}"
                score = item.get("score") or 0
                descendants = item.get("descendants") or 0
                topics.append(
                    HotspotItem(
                        title=title,
                        url=story_url,
                        source_id=self.source_id,
                        summary=f"HN 热度 {score} 分 / {descendants} 评论",
                        tier=1,
                    )
                )
        except Exception as e:
            logger.warning(f"  {self.display_name} Firebase 兜底通道也失败: {e}")
        return topics


class WallStreetCNPlugin(BaseSourcePlugin):
    @property
    def source_id(self) -> str:
        return "wallstreetcn"

    @property
    def display_name(self) -> str:
        return "华尔街见闻全球快讯"

    @staticmethod
    def _extract_headline(title: str, content_text: str) -> str:
        clean_title = (title or "").strip()
        if len(clean_title) >= 8:
            return clean_title
        clean_body = re.sub(r"\s+", " ", (content_text or "").strip())
        if not clean_body:
            return clean_title
        bracket = re.match(r"^【([^】]{6,80})】", clean_body)
        if bracket:
            return bracket.group(1).strip()
        first_sentence = re.split(r"[。！？\n]", clean_body, maxsplit=1)[0].strip()
        if len(first_sentence) >= 8:
            return first_sentence[:72]
        return clean_body[:72]

    def fetch_data(self) -> List[Any]:
        if _is_source_disabled(self.source_id):
            return []
        logger.info(f"  正在同步 {self.display_name}...")

        # 主通道：华尔街见闻全球 7x24 快讯 API（国内直连 ~300ms）
        topics = self._fetch_lives()
        if topics:
            _mark_source_success(self.source_id)
            return topics[:NEWS_MAX_PER_SOURCE]

        # 备选通道：华尔街见闻全球精选文章流 API
        topics = self._fetch_information_flow()
        if topics:
            _mark_source_success(self.source_id)
            return topics[:NEWS_MAX_PER_SOURCE]

        _mark_source_failure(self.source_id)
        return []

    def _fetch_lives(self) -> List[HotspotItem]:
        topics: List[HotspotItem] = []
        seen: set[str] = set()
        try:
            url = "https://api-one-wscn.awtmt.com/apiv1/content/lives?channel=global-channel&limit=20"
            res = HTTP_SESSION.get(url, headers=get_headers(referer="https://wallstreetcn.com/"), timeout=10)
            res.raise_for_status()
            data = res.json()
            for item in data.get("data", {}).get("items", []):
                content_text = (item.get("content_text") or "").strip()
                headline = self._extract_headline(item.get("title") or "", content_text)
                if len(headline) < 8 or headline in seen or not _is_title_fresh(headline):
                    continue
                seen.add(headline)
                topics.append(
                    HotspotItem(
                        title=headline,
                        url=(item.get("uri") or "").strip(),
                        source_id=self.source_id,
                        summary=content_text[:240],
                        publish_time=str(item.get("display_time") or ""),
                        tier=1,
                    )
                )
        except Exception as e:
            logger.warning(f"  {self.display_name} 快讯主通道失败: {e}，降级至资讯流通道")
        return topics

    def _fetch_information_flow(self) -> List[HotspotItem]:
        topics: List[HotspotItem] = []
        seen: set[str] = set()
        try:
            url = "https://api-one-wscn.awtmt.com/apiv1/content/information-flow?channel=global&accept=article&limit=15"
            res = HTTP_SESSION.get(url, headers=get_headers(referer="https://wallstreetcn.com/"), timeout=10)
            res.raise_for_status()
            data = res.json()
            for entry in data.get("data", {}).get("items", []):
                resource = entry.get("resource") if isinstance(entry, dict) else None
                if not isinstance(resource, dict):
                    resource = entry if isinstance(entry, dict) else {}
                title = (resource.get("title") or "").strip()
                if len(title) < 8 or title in seen or not _is_title_fresh(title):
                    continue
                seen.add(title)
                topics.append(
                    HotspotItem(
                        title=title,
                        url=(resource.get("uri") or "").strip(),
                        source_id=self.source_id,
                        summary=(resource.get("content_short") or "").strip()[:240],
                        publish_time=str(resource.get("display_time") or ""),
                        tier=1,
                    )
                )
        except Exception as e:
            logger.warning(f"  {self.display_name} 资讯流备选通道也失败: {e}")
        return topics
