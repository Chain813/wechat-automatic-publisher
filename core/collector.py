"""
============================================================
  超级热点聚合引擎 v7.0 (微信适配版)
  支持：微博热搜、IT之家、36氪、百度热搜、知乎、CSDN、RSS
  强化：时效性强制过滤、时政类源、n-gram 去重、源健康监控
============================================================
"""
import time
import random
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from bs4 import BeautifulSoup
from config import (
    NEWS_SOURCES, NEWS_MAX_PER_SOURCE, FILTER_CATEGORIES,
    HOTSPOT_CACHE_TTL_SECONDS, RSS_FEEDS, NEWS_FRESHNESS_HOURS,
    API_60S_BASE,
)

from loguru import logger
from utils.http_client import build_cached_session

# ---- 时区 ----
_CN_TZ = timezone(timedelta(hours=8))

# ---- 模拟真实浏览器头 ----
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

# ---- 源健康状态 ----
_source_health = {}
HTTP_SESSION = build_cached_session("hotspot_cache", HOTSPOT_CACHE_TTL_SECONDS)


def _get_source_health(name):
    """获取或初始化源健康状态"""
    if name not in _source_health:
        _source_health[name] = {"failures": 0, "disabled": False}
    return _source_health[name]


def _mark_source_failure(name):
    """标记源失败，连续 3 次后禁用"""
    h = _get_source_health(name)
    h["failures"] += 1
    if h["failures"] >= 3:
        h["disabled"] = True
        logger.warning("  {} 连续失败 3 次，已自动降级跳过", name)


def _mark_source_success(name):
    """标记源成功，重置失败计数"""
    h = _get_source_health(name)
    h["failures"] = 0
    h["disabled"] = False


def _is_source_disabled(name):
    """检查源是否被禁用"""
    return _get_source_health(name)["disabled"]


def get_headers(referer=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if referer:
        headers["Referer"] = referer
    return headers


def _is_entry_fresh(entry, max_hours=None):
    """
    检查 RSS 条目是否在时效窗口内。
    优先使用 entry 的 published_parsed / updated_parsed 字段。
    """
    if max_hours is None:
        max_hours = NEWS_FRESHNESS_HOURS
    if max_hours <= 0:
        return True  # 0 表示不限制

    # 尝试从 entry 获取发布时间
    pub_time = None
    for field in ("published_parsed", "updated_parsed"):
        t = getattr(entry, field, None) or entry.get(field)
        if t:
            try:
                pub_time = datetime(*t[:6], tzinfo=timezone.utc)
                break
            except Exception:
                continue

    if pub_time is None:
        # 无法判断时间的条目，默认放行（热榜类源本身就是实时的）
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
    return pub_time >= cutoff


def _get_current_date_str():
    """获取当前日期字符串，用于标题级时效性检查"""
    now = datetime.now()
    return now.strftime("%Y年%m月%d日")


def _is_title_fresh(title):
    """
    增强版标题级时效性过滤：剔除包含明显旧时间标记的话题。
    例如 "2024年回顾"、"去年总结" 等。
    """
    import re as _re

    # 匹配过旧年份（非当年）
    current_year = datetime.now().year
    old_year_match = _re.findall(r'(20[12]\d)年', title)
    for y in old_year_match:
        if int(y) < current_year:
            return False

    # 匹配"去年""前年""旧""回顾""总结"等暗示非时效性词汇
    stale_keywords = ["去年", "前年", "回顾", "总结", "盘点", "历年", "曾经", "往期",
                      "经典", "老", "旧版", "传统", "历史", "纪念", "周年"]
    for kw in stale_keywords:
        if kw in title:
            return False

    # 检查是否包含当前日期（增强时效性）
    current_date = _get_current_date_str()
    if current_date in title:
        return True

    # 检查是否包含"今日""今天""昨夜""昨晚"等时效性词汇
    fresh_keywords = ["今日", "今天", "昨夜", "昨晚", "刚刚", "最新", "最新消息",
                      "快讯", "突发", "紧急", "速报", "实时", "即时"]
    for kw in fresh_keywords:
        if kw in title:
            return True

    # 如果标题没有明确的时间标记，默认放行（热榜类源本身就是实时的）
    return True


# ==========================================
#  微博热搜 (60s API 优先，原生 API 降级)
# ==========================================
def fetch_weibo_light():
    """
    微博热搜：60s API 优先（稳定），原生 API 降级。
    """
    if _is_source_disabled("weibo"):
        return []

    logger.info("  正在同步 微博 全网热搜...")
    topics = []

    # 方法1: 60s API（稳定）
    try:
        res = HTTP_SESSION.get(f"{API_60S_BASE}/weibo", headers=get_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get("code") == 200:
            for item in data.get("data", []):
                title = item.get("title", "").strip()
                if title and len(title) > 1:
                    topics.append(title)
            if topics:
                _mark_source_success("weibo")
                return topics[:NEWS_MAX_PER_SOURCE]
    except Exception as e:
        logger.warning("  微博 60s API 失败: {}，降级至原生 API", e)

    # 方法2: 原生 API
    try:
        headers = get_headers(referer="https://weibo.com/")
        res = HTTP_SESSION.get("https://weibo.com/ajax/side/hotSearch", headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        for item in data.get("data", {}).get("realtime", []):
            word = item.get("word", "").strip()
            if word and len(word) > 1 and "公告" not in word:
                topics.append(word)
        if topics:
            _mark_source_success("weibo")
        return topics[:NEWS_MAX_PER_SOURCE]
    except Exception as e:
        logger.warning("  微博原生 API 也失败: {}，降级至 Selenium", e)
        return fetch_weibo()


def fetch_weibo():
    """
    微博热搜 Selenium 版 (fallback)。
    仅在 API 不可用时使用。
    """
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
                topics.append(t)
        _mark_source_success("weibo")
    except Exception as e:
        logger.warning("  微博 Selenium 抓取也失败: {}", e)
        _mark_source_failure("weibo")
    finally:
        if browser:
            browser.quit()
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  IT之家 科技热榜 (RSS 优先，HTML 降级)
# ==========================================
def fetch_ithome():
    """抓取 IT之家 科技热榜（RSS 优先）"""
    if _is_source_disabled("ithome"):
        return []

    logger.info("  正在同步 IT之家 科技资讯...")
    topics = []

    # 方法1: RSS feed（稳定，不受页面改版影响）
    try:
        import feedparser
        res = HTTP_SESSION.get("https://www.ithome.com/rss/", headers=get_headers(), timeout=10)
        res.raise_for_status()
        feed = feedparser.parse(res.content)
        if feed.entries:
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                if title and len(title) > 3 and _is_entry_fresh(entry) and _is_title_fresh(title):
                    topics.append(title)
            if topics:
                _mark_source_success("ithome")
                return topics[:NEWS_MAX_PER_SOURCE]
    except Exception as e:
        logger.warning("  IT之家 RSS 失败: {}，降级至 HTML", e)

    # 方法2: HTML 降级
    try:
        res = HTTP_SESSION.get("https://www.ithome.com/", headers=get_headers(), timeout=10)
        res.raise_for_status()
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select(".rt ul li a, .hot-list a, .sidebar-hot a")
        topics = [item.get_text(strip=True) for item in items if len(item.get_text(strip=True)) > 3]
        if topics:
            _mark_source_success("ithome")
        else:
            _mark_source_failure("ithome")
    except Exception as e:
        logger.warning("  IT之家 HTML 也失败: {}", e)
        _mark_source_failure("ithome")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  36氪 快讯 (RSS 优先，HTML 降级)
# ==========================================
def fetch_36kr():
    """抓取 36氪 商业趋势快讯（RSS 优先）"""
    if _is_source_disabled("36kr"):
        return []

    logger.info("  正在同步 36氪 商业趋势...")
    topics = []

    # 方法1: RSS feed（稳定）
    try:
        import feedparser
        res = HTTP_SESSION.get("https://36kr.com/feed", headers=get_headers(), timeout=10)
        res.raise_for_status()
        feed = feedparser.parse(res.content)
        if feed.entries:
            for entry in feed.entries[:15]:
                title = entry.get("title", "").strip()
                if title and len(title) > 4 and _is_entry_fresh(entry) and _is_title_fresh(title):
                    topics.append(title)
            if topics:
                _mark_source_success("36kr")
                return topics[:NEWS_MAX_PER_SOURCE]
    except Exception as e:
        logger.warning("  36氪 RSS 失败: {}，降级至 HTML", e)

    # 方法2: HTML 降级
    try:
        res = HTTP_SESSION.get("https://36kr.com/newsflashes", headers=get_headers(), timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select(".item-title, .newsflash-title, [class*='title']")
        topics = [item.get_text(strip=True) for item in items if len(item.get_text(strip=True)) > 4]
        if topics:
            _mark_source_success("36kr")
        else:
            _mark_source_failure("36kr")
    except Exception as e:
        logger.warning("  36氪 HTML 也失败: {}", e)
        _mark_source_failure("36kr")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  百度热搜 (JSON API 优先，HTML 降级)
# ==========================================
def fetch_baidu():
    """抓取百度实时热搜榜（JSON API 优先）"""
    if _is_source_disabled("baidu"):
        return []

    logger.info("  正在同步 百度 实时热搜...")
    topics = []

    # 方法1: JSON API（稳定）
    try:
        api_url = "https://top.baidu.com/board?tab=realtime"
        headers = get_headers()
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        res = HTTP_SESSION.get(api_url, headers=headers, timeout=10)
        res.raise_for_status()
        res.encoding = 'utf-8'
        # 百度热搜页面内嵌 JSON 数据
        import re as _re
        match = _re.search(r'<!--s-data:(.*?)-->', res.text)
        if match:
            import json
            data = json.loads(match.group(1))
            cards = data.get("data", {}).get("cards", [])
            for card in cards:
                for item in card.get("content", []):
                    word = item.get("word", "") or item.get("query", "")
                    if word and len(word) > 1:
                        topics.append(word)
            if topics:
                _mark_source_success("baidu")
                return topics[:NEWS_MAX_PER_SOURCE]
    except Exception as e:
        logger.warning("  百度 JSON 解析失败: {}，降级至 HTML", e)

    # 方法2: HTML 降级
    try:
        res = HTTP_SESSION.get("https://top.baidu.com/board?tab=realtime", headers=get_headers(), timeout=10)
        res.raise_for_status()
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        items = soup.select(".c-single-text-ellipsis, .title_dIF3B, [class*='title']")
        for item in items:
            text = item.get_text(strip=True)
            if text and len(text) > 1:
                topics.append(text)
        if topics:
            _mark_source_success("baidu")
        else:
            _mark_source_failure("baidu")
    except Exception as e:
        logger.warning("  百度 HTML 也失败: {}", e)
        _mark_source_failure("baidu")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  知乎热榜
# ==========================================
def fetch_zhihu():
    """
    抓取知乎热榜 (带降级机制)
    """
    if _is_source_disabled("zhihu"):
        return []

    topics = fetch_zhihu_light()
    if not topics:
        topics = fetch_zhihu_selenium()
    return topics[:NEWS_MAX_PER_SOURCE]


def fetch_zhihu_light():
    """
    知乎热榜：60s API 优先，原生 API 降级。
    """
    logger.info("  正在同步 知乎 热榜...")
    topics = []

    # 方法1: 60s API（稳定）
    try:
        res = HTTP_SESSION.get(f"{API_60S_BASE}/zhihu", headers=get_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get("code") == 200:
            for item in data.get("data", []):
                title = item.get("title", "").strip()
                if title and len(title) > 1:
                    topics.append(title)
            if topics:
                _mark_source_success("zhihu")
                return topics
    except Exception as e:
        logger.warning("  知乎 60s API 失败: {}，降级至原生 API", e)

    # 方法2: 原生 API
    try:
        url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=20"
        res = HTTP_SESSION.get(url, headers=get_headers(referer="https://www.zhihu.com/hot"), timeout=10)
        res.raise_for_status()
        data = res.json()
        for item in data.get("data", []):
            target = item.get("target", {})
            title = target.get("title", "")
            if title and len(title) > 1:
                topics.append(title)
        _mark_source_success("zhihu")
    except Exception as e:
        logger.warning("  知乎原生 API 也失败: {}，降级至 Selenium", e)
    return topics


def fetch_zhihu_selenium():
    """
    知乎热榜 Selenium 版 (fallback)
    """
    logger.info("  正在同步 知乎 热榜 (Selenium 降级)...")
    browser = None
    topics = []
    try:
        from utils.spider import build_stealth_browser
        browser = build_stealth_browser(headless=True)
        browser.get("https://www.zhihu.com/explore")
        time.sleep(5)
        soup = BeautifulSoup(browser.page_source, "html.parser")
        # 稳定的选择器：近期热点部分的链接
        items = soup.select(".ExploreHomePage-section:has(a[href*='hot-question']) a[href*='/question/']")
        if not items:
            # 备选选择器：所有包含 question 的链接
            items = soup.select("a[href*='/question/']")
        
        for item in items:
            t = item.get_text(strip=True)
            if t and len(t) > 5:  # 过滤掉太短的标题
                topics.append(t)
        
        if topics:
            _mark_source_success("zhihu")
        else:
            _mark_source_failure("zhihu")
    except Exception as e:
        logger.warning("  知乎 Selenium 抓取也失败: {}", e)
        _mark_source_failure("zhihu")
    finally:
        if browser:
            browser.quit()
    return topics


# ==========================================
#  CSDN 热榜
# ==========================================
def fetch_csdn():
    """抓取 CSDN 全站热榜"""
    if _is_source_disabled("csdn"):
        return []

    logger.info("  正在同步 CSDN 热榜...")
    url = "https://blog.csdn.net/phoenix/web/blog/hot-rank?page=0&pageSize=20"
    topics = []
    try:
        res = HTTP_SESSION.get(url, headers=get_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()
        for item in data.get("data", []):
            title = item.get("articleTitle", "").strip()
            if title:
                topics.append(title)
        _mark_source_success("csdn")
    except Exception as e:
        logger.warning("  CSDN抓取失败: {}", e)
        _mark_source_failure("csdn")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  RSS 聚合
# ==========================================
def fetch_rss():
    """聚合自定义 RSS 订阅源（带超时控制）"""
    if _is_source_disabled("rss"):
        return []

    logger.info("  正在同步 RSS 聚合订阅...")
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
                        topics.append(title)
        except Exception as e:
            logger.warning("  RSS 源 {} 解析失败: {}", feed_url, e)
            
    if has_success:
        _mark_source_success("rss")
    else:
        _mark_source_failure("rss")
        
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  跨源去重 (2-gram Jaccard 相似度)
# ==========================================
def _ngram_set(text: str, n: int = 2) -> set:
    """生成文本的 n-gram 集合（中文按字，英文按词）"""
    import re as _re
    # 英文单词按词级 n-gram，中文按字级 n-gram
    tokens = []
    for m in _re.finditer(r'[a-zA-Z0-9]+|[一-鿿]', text):
        tokens.append(m.group().lower())
    if len(tokens) < n:
        return set(tokens) if tokens else set()
    return {tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)}


def _jaccard_similarity(a: str, b: str) -> float:
    """计算两个字符串的 2-gram Jaccard 相似度（中文按字，英文按词）"""
    set_a = _ngram_set(a, 2)
    set_b = _ngram_set(b, 2)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def deduplicate_topics(topics_list, threshold=0.5):
    """
    跨源语义去重。
    用 2-gram Jaccard 相似度去除不同源的高度相似话题。
    """
    if not topics_list:
        return []
    unique = []
    for item in topics_list:
        is_dup = False
        for existing in unique:
            if _jaccard_similarity(item, existing) >= threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(item)
    return unique


# ==========================================
#  按类别优先排序
# ==========================================
def filter_by_category(topics, categories=None):
    """
    按优先类别排序：匹配 FILTER_CATEGORIES 的话题排前面。
    """
    if categories is None:
        categories = FILTER_CATEGORIES
    if not categories:
        return topics[:30]

    prioritized = []
    rest = []
    for t in topics:
        matched = False
        for cat in categories:
            if cat and cat.lower() in t.lower():
                prioritized.append(t)
                matched = True
                break
        if not matched:
            rest.append(t)

    return prioritized + rest


# ==========================================
#  时政科技交叉源 (澎湃/观察者网/新华网)
# ==========================================
def fetch_politics():
    """
    抓取时政科技交叉类资讯，弥补纯技术源的时政盲区。
    来源：澎湃新闻、观察者网、新华网（直接抓取，不依赖 rsshub）
    """
    if _is_source_disabled("politics"):
        return []

    logger.info("  正在同步 时政科技 资讯...")
    topics = []
    has_success = False

    # ---- 策略1: 直接抓取网站首页 ----
    politics_sites = [
        ("https://www.thepaper.cn/", "澎湃"),
        ("https://www.guancha.cn/", "观察者网"),
    ]

    for site_url, site_name in politics_sites:
        try:
            res = HTTP_SESSION.get(site_url, headers=get_headers(referer=site_url), timeout=12)
            res.raise_for_status()
            res.encoding = 'utf-8'
            soup = BeautifulSoup(res.text, "html.parser")
            # 提取新闻标题链接
            links = soup.select("a[href*='newsDetail'], a[href*='news_detail'], a[href*='/20']")
            for link in links:
                title = link.get_text(strip=True)
                if title and 8 < len(title) < 80 and _is_title_fresh(title):
                    topics.append(title)
            if links:
                has_success = True
        except Exception as e:
            logger.warning("  时政源 {} 抓取失败: {}", site_name, e)

    # ---- 策略2: RSS 降级 (直接 RSS) ----
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
                                topics.append(title)
                except Exception as e:
                    logger.warning("  时政 RSS {} 失败: {}", feed_url, e)
        except ImportError:
            pass

    if has_success:
        _mark_source_success("politics")
    else:
        _mark_source_failure("politics")

    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  今日头条热榜 (60s API 优先，原生 API 降级)
# ==========================================
def fetch_toutiao():
    """抓取今日头条实时热榜"""
    if _is_source_disabled("toutiao"):
        return []

    logger.info("  正在同步 今日头条 热榜...")
    topics = []

    # 方法1: 60s API（稳定）
    try:
        res = HTTP_SESSION.get(f"{API_60S_BASE}/toutiao", headers=get_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get("code") == 200:
            for item in data.get("data", []):
                title = item.get("title", "").strip()
                if title and len(title) > 1:
                    topics.append(title)
            if topics:
                _mark_source_success("toutiao")
                return topics[:NEWS_MAX_PER_SOURCE]
    except Exception as e:
        logger.warning("  头条 60s API 失败: {}，降级至原生 API", e)

    # 方法2: 原生 API
    try:
        url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
        res = HTTP_SESSION.get(url, headers=get_headers(referer="https://www.toutiao.com/"), timeout=10)
        res.raise_for_status()
        data = res.json()
        for item in data.get("data", []):
            title = item.get("Title", "").strip()
            if title and len(title) > 1:
                topics.append(title)
        if topics:
            _mark_source_success("toutiao")
        else:
            _mark_source_failure("toutiao")
    except Exception as e:
        logger.warning("  头条原生 API 也失败: {}", e)
        _mark_source_failure("toutiao")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  澎湃新闻 (直接抓取)
# ==========================================
def fetch_thepaper():
    """抓取澎湃新闻首页热点"""
    if _is_source_disabled("thepaper"):
        return []

    logger.info("  正在同步 澎湃新闻...")
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
                topics.append(title)
        if topics:
            _mark_source_success("thepaper")
        else:
            _mark_source_failure("thepaper")
    except Exception as e:
        logger.warning("  澎湃新闻抓取失败: {}", e)
        _mark_source_failure("thepaper")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  虎嗅网 (首页抓取)
# ==========================================
def fetch_huxiu():
    """抓取虎嗅网首页热点"""
    if _is_source_disabled("huxiu"):
        return []

    logger.info("  正在同步 虎嗅网...")
    topics = []
    try:
        res = HTTP_SESSION.get("https://www.huxiu.com/", headers=get_headers(), timeout=12)
        res.raise_for_status()
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        links = soup.select("a[href*='/article/'], a[href*='/article/']")
        for link in links:
            title = link.get_text(strip=True)
            if title and 8 < len(title) < 80 and _is_title_fresh(title):
                topics.append(title)
        if topics:
            _mark_source_success("huxiu")
        else:
            _mark_source_failure("huxiu")
    except Exception as e:
        logger.warning("  虎嗅网抓取失败: {}", e)
        _mark_source_failure("huxiu")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  抖音热搜 (60s API)
# ==========================================
def fetch_douyin():
    """抓取抖音热搜榜"""
    if _is_source_disabled("douyin"):
        return []

    logger.info("  正在同步 抖音 热搜...")
    topics = []
    try:
        res = HTTP_SESSION.get(f"{API_60S_BASE}/douyin", headers=get_headers(), timeout=10)
        res.raise_for_status()
        data = res.json()
        if data.get("code") == 200:
            for item in data.get("data", []):
                title = item.get("title", "").strip()
                if title and len(title) > 1:
                    topics.append(title)
        if topics:
            _mark_source_success("douyin")
        else:
            _mark_source_failure("douyin")
    except Exception as e:
        logger.warning("  抖音热搜抓取失败: {}", e)
        _mark_source_failure("douyin")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  并行聚合入口
# ==========================================
# 采集源注册表
_SOURCE_FETCHERS = {
    "weibo": fetch_weibo_light,
    "ithome": fetch_ithome,
    "36kr": fetch_36kr,
    "baidu": fetch_baidu,
    "zhihu": fetch_zhihu,
    "csdn": fetch_csdn,
    "rss": fetch_rss,
    "politics": fetch_politics,
    "toutiao": fetch_toutiao,
    "thepaper": fetch_thepaper,
    "huxiu": fetch_huxiu,
    "douyin": fetch_douyin,
}


def fetch_all_hotspots():
    """
    聚合入口：并行抓取所有配置的源（向后兼容）。
    注意：保留串行版本的函数签名，供 main.py 调用。
    """
    return fetch_all_hotspots_parallel()


def fetch_all_hotspots_parallel():
    """
    并行聚合入口：使用 ThreadPoolExecutor 同时抓取所有启用的源。
    """
    sources = [s for s in NEWS_SOURCES if s in _SOURCE_FETCHERS]
    if not sources:
        logger.warning("  没有可用的采集源！")
        return ""

    logger.info("正在启动全网热点并行扫描引擎 ({} 源)...", len(sources))

    results = {}
    with ThreadPoolExecutor(max_workers=len(sources)) as executor:
        future_map = {
            executor.submit(_SOURCE_FETCHERS[s]): s
            for s in sources
        }
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.warning("  {} 并行任务异常: {}", name, e)
                results[name] = []

    # 拼接输出
    source_labels = {
        "weibo": "微博实时热搜",
        "ithome": "IT之家科技热点",
        "36kr": "36氪商业与AI动态",
        "baidu": "百度实时热搜",
        "zhihu": "知乎热榜",
        "csdn": "CSDN 全站热榜",
        "rss": "RSS 聚合精选",
        "politics": "时政科技交叉",
        "toutiao": "今日头条热榜",
        "thepaper": "澎湃新闻",
        "huxiu": "虎嗅网深度",
        "douyin": "抖音热搜",
    }

    all_summary = []
    all_flat = []
    for src in sources:
        topics = results.get(src, [])
        if topics:
            # 标题级时效性过滤：剔除旧时间标记的话题
            original_count = len(topics)
            topics = [t for t in topics if _is_title_fresh(t)]
            filtered_count = original_count - len(topics)
            if filtered_count > 0:
                logger.info("  {} 源过滤掉 {} 条旧内容", src, filtered_count)
            label = source_labels.get(src, src)
            all_summary.append(f"【{label}】")
            all_summary.extend([f"- {t}" for t in deduplicate_topics(topics)[:NEWS_MAX_PER_SOURCE]])

    # 基础校验
    total = sum(len(results.get(s, [])) for s in sources)
    if total == 0:
        logger.warning("  所有源均未采集到数据，请检查网络连接。")
        return ""

    logger.info("  并行扫描完成，共获取 {} 条资讯。", total)
    return "\n".join(all_summary)


def fetch_all_hotspots_sequential():
    """
    串行聚合入口 (向后兼容，供需要严格顺序的场景使用)。
    """
    logger.info("正在启动全网热点串行扫描引擎...")

    all_flat = []
    source_labels = {
        "weibo": ("微博实时热搜", fetch_weibo_light),
        "ithome": ("IT之家科技热点", fetch_ithome),
        "36kr": ("36氪商业与AI动态", fetch_36kr),
        "baidu": ("百度实时热搜", fetch_baidu),
        "zhihu": ("知乎热榜", fetch_zhihu),
        "csdn": ("CSDN 全站热榜", fetch_csdn),
        "rss": ("RSS 聚合精选", fetch_rss),
        "politics": ("时政科技交叉", fetch_politics),
        "toutiao": ("今日头条热榜", fetch_toutiao),
        "thepaper": ("澎湃新闻", fetch_thepaper),
        "huxiu": ("虎嗅网深度", fetch_huxiu),
        "douyin": ("抖音热搜", fetch_douyin),
    }

    all_summary = []
    for src in NEWS_SOURCES:
        if src not in source_labels:
            continue
        label, fetcher = source_labels[src]
        topics = fetcher()
        topics = [t for t in topics if _is_title_fresh(t)]
        all_flat.extend(topics)
        if topics:
            all_summary.append(f"【{label}】")
            all_summary.extend([f"- {t}" for t in deduplicate_topics(topics)])

    if not all_flat:
        logger.warning("  采集到的数据量过少，请检查源网站连接。")
        return ""

    return "\n".join(all_summary)


# ==========================================
#  源健康状态查询
# ==========================================
def get_source_health_report():
    """返回所有源的当前健康状态"""
    report = {}
    for name in NEWS_SOURCES:
        h = _get_source_health(name)
        report[name] = {
            "failures": h["failures"],
            "disabled": h["disabled"],
            "status": "disabled" if h["disabled"] else ("degraded" if h["failures"] > 0 else "healthy")
        }
    return report


def reset_source_health():
    """重置所有源健康状态"""
    global _source_health
    _source_health = {}
