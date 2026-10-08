import json
import re
import urllib.parse
from bs4 import BeautifulSoup
from loguru import logger
from typing import List, Any

from core.plugins.base import BaseSourcePlugin, HotspotItem
from config import NEWS_MAX_PER_SOURCE, API_60S_BASE, RSS_FEEDS
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

        try:
            res = HTTP_SESSION.get("https://36kr.com/newsflashes", headers=get_headers(), timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            items = soup.select(".item-title, .newsflash-title, [class*='title']")
            topics = []
            for item in items:
                text = item.get_text(strip=True)
                if len(text) > 4 and _is_title_fresh(text):
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
        try:
            import feedparser
        except ImportError:
            logger.warning("  未安装 feedparser，无法解析 RSS")
            return []

        topics = []
        has_success = False

        for feed_url in RSS_FEEDS:
            try:
                res = HTTP_SESSION.get(feed_url, headers=get_headers(), timeout=15)
                res.raise_for_status()
                feed = feedparser.parse(res.content)
                if feed.entries:
                    has_success = True
                    for entry in feed.entries[:10]:
                        title = entry.get("title", "").strip()
                        if title and _is_entry_fresh(entry) and _is_title_fresh(title):
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
                logger.warning(f"  RSS 源 {feed_url} 解析失败: {e}")
                
        if has_success:
            _mark_source_success(self.source_id)
        else:
            _mark_source_failure(self.source_id)
            
        return topics[:NEWS_MAX_PER_SOURCE]


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
        topics = []
        seen_titles = set()
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

        # 降级至 Selenium
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
            import time
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
                browser.quit()
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
            logger.warning(f"  微博 60s API 也失败: {e}，降级至 Selenium")
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
            import time
            time.sleep(4)
            from bs4 import BeautifulSoup
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
                browser.quit()
        return topics[:NEWS_MAX_PER_SOURCE]
