"""
============================================================
  超级热点聚合引擎 v5.0 (微信适配版)
  支持：微博热搜、IT之家、36氪、百度热搜
  新增：并行采集、百度源、跨源去重、源健康监控、轻量API
============================================================
"""
import time
import requests
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import NEWS_SOURCES, NEWS_MAX_PER_SOURCE, FILTER_CATEGORIES

from loguru import logger

# ---- 模拟真实浏览器头 ----
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

# ---- 源健康状态 ----
_source_health = {}


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


def get_headers():
    return {"User-Agent": random.choice(USER_AGENTS)}


# ==========================================
#  微博热搜 (轻量 API 版)
# ==========================================
def fetch_weibo_light():
    """
    微博热搜轻量版：通过 API 接口直接获取，无需 Selenium。
    接口来源：https://weibo.com/ajax/side/hotSearch
    """
    if _is_source_disabled("weibo"):
        return []

    logger.info("  正在同步 微博 全网热搜 (轻量 API)...")
    url = "https://weibo.com/ajax/side/hotSearch"
    topics = []
    try:
        res = requests.get(url, headers=get_headers(), timeout=10)
        data = res.json()
        for item in data.get("data", {}).get("realtime", []):
            word = item.get("word", "").strip()
            if word and len(word) > 1 and "公告" not in word:
                topics.append(word)
        _mark_source_success("weibo")
    except Exception as e:
        logger.warning("  微博轻量 API 失败: {}，降级至 Selenium", e)
        _mark_source_failure("weibo")
        # 降级至 Selenium 版本
        return fetch_weibo()

    return topics[:NEWS_MAX_PER_SOURCE]


def fetch_weibo():
    """
    微博热搜 Selenium 版 (fallback)。
    仅在 API 不可用时使用。
    """
    from bs4 import BeautifulSoup

    logger.info("  正在同步 微博 全网热搜 (Selenium 降级)...")
    browser = None
    topics = []
    try:
        from spider_engine import build_stealth_browser
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
#  IT之家 科技热榜
# ==========================================
def fetch_ithome():
    """抓取 IT之家 科技热榜"""
    if _is_source_disabled("ithome"):
        return []

    logger.info("  正在同步 IT之家 科技资讯...")
    url = "https://www.ithome.com/"
    topics = []
    try:
        res = requests.get(url, headers=get_headers(), timeout=10)
        res.encoding = 'utf-8'
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, "html.parser")
        # 多选择器兼容
        items = soup.select(".rt ul li a")
        if not items:
            items = soup.select(".hot-list a")
        if not items:
            items = soup.select(".sidebar-hot a")
        topics = [item.get_text(strip=True) for item in items if len(item.get_text(strip=True)) > 3]
        _mark_source_success("ithome")
    except Exception as e:
        logger.warning("  IT之家抓取失败: {}", e)
        _mark_source_failure("ithome")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  36氪 快讯
# ==========================================
def fetch_36kr():
    """抓取 36氪 商业趋势快讯"""
    if _is_source_disabled("36kr"):
        return []

    logger.info("  正在同步 36氪 商业趋势...")
    url = "https://36kr.com/newsflashes"
    topics = []
    try:
        res = requests.get(url, headers=get_headers(), timeout=10)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, "html.parser")
        # 多选择器兼容
        items = soup.select(".item-title")
        if not items:
            items = soup.select(".newsflash-title")
        if not items:
            items = soup.select("[class*='title']")
        topics = [item.get_text(strip=True) for item in items if len(item.get_text(strip=True)) > 4]
        _mark_source_success("36kr")
    except Exception as e:
        logger.warning("  36氪抓取失败: {}", e)
        _mark_source_failure("36kr")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  百度热搜 (新增)
# ==========================================
def fetch_baidu():
    """抓取百度实时热搜榜"""
    if _is_source_disabled("baidu"):
        return []

    logger.info("  正在同步 百度 实时热搜...")
    url = "https://top.baidu.com/board?tab=realtime"
    topics = []
    try:
        res = requests.get(url, headers=get_headers(), timeout=10)
        res.encoding = 'utf-8'
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(res.text, "html.parser")
        # 百度热搜的标题选择器
        items = soup.select(".c-single-text-ellipsis")
        if not items:
            items = soup.select(".title_dIF3B")
        if not items:
            items = soup.select("[class*='title']")
        for item in items:
            text = item.get_text(strip=True)
            if text and len(text) > 1:
                topics.append(text)
        _mark_source_success("baidu")
    except Exception as e:
        logger.warning("  百度热搜抓取失败: {}", e)
        _mark_source_failure("baidu")
    return topics[:NEWS_MAX_PER_SOURCE]


# ==========================================
#  跨源去重 (Jaccard 相似度)
# ==========================================
def _jaccard_similarity(a: str, b: str) -> float:
    """计算两个字符串的 Jaccard 相似度"""
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def deduplicate_topics(topics_list, threshold=0.7):
    """
    跨源语义去重。
    用 Jaccard 相似度去除不同源的高度相似话题。
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
#  并行聚合入口
# ==========================================
# 采集源注册表
_SOURCE_FETCHERS = {
    "weibo": fetch_weibo_light,
    "ithome": fetch_ithome,
    "36kr": fetch_36kr,
    "baidu": fetch_baidu,
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
    }

    all_summary = []
    all_flat = []
    for src in sources:
        topics = results.get(src, [])
        if topics:
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
    }

    all_summary = []
    for src in NEWS_SOURCES:
        if src not in source_labels:
            continue
        label, fetcher = source_labels[src]
        topics = fetcher()
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
