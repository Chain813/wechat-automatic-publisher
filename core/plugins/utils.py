import os
import random
import threading
from datetime import datetime, timezone, timedelta
import re
from loguru import logger
from utils.http_client import build_cached_session
from config import HOTSPOT_CACHE_TTL_SECONDS, NEWS_FRESHNESS_HOURS

_CN_TZ = timezone(timedelta(hours=8))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

_source_health = {}
_source_health_lock = threading.Lock()
HTTP_SESSION = build_cached_session(os.path.join("data", "cache", "hotspots", "hotspot_cache"), HOTSPOT_CACHE_TTL_SECONDS)

def get_source_health_report():
    from config import NEWS_SOURCES
    report = {}
    with _source_health_lock:
        # 预先用配置的信源初始化健康状态，避免初始状态为空
        for src in NEWS_SOURCES:
            if src not in _source_health:
                _source_health[src] = {"failures": 0, "disabled": False}
                
        for k, v in _source_health.items():
            if v["disabled"]:
                status = "disabled"
            elif v["failures"] > 0:
                status = "degraded"
            else:
                status = "healthy"
            report[k] = {
                "failures": v["failures"],
                "status": status
            }
    return report

def _get_source_health(name):
    if name not in _source_health:
        _source_health[name] = {"failures": 0, "disabled": False}
    return _source_health[name]

def _mark_source_failure(name):
    with _source_health_lock:
        h = _get_source_health(name)
        h["failures"] += 1
        if h["failures"] >= 3:
            h["disabled"] = True
            logger.warning(f"  {name} 连续失败 3 次，已自动降级跳过")

def _mark_source_success(name):
    with _source_health_lock:
        h = _get_source_health(name)
        h["failures"] = 0
        h["disabled"] = False

def _is_source_disabled(name):
    with _source_health_lock:
        return _get_source_health(name)["disabled"]

def reset_source_health():
    """重置所有数据源的健康状态（每次运行开始时调用）"""
    with _source_health_lock:
        _source_health.clear()

def get_headers(referer=None):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    if referer:
        headers["Referer"] = referer
    return headers

def _is_entry_fresh(entry, max_hours=None):
    if max_hours is None:
        max_hours = NEWS_FRESHNESS_HOURS
    if max_hours <= 0:
        return True

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
        return True

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
    return pub_time >= cutoff

def _get_current_date_str():
    now = datetime.now()
    return now.strftime("%Y年%m月%d日")

def _is_title_fresh(title):
    current_year = datetime.now().year
    old_year_match = re.findall(r'(20\d{2})年', title)
    for y in old_year_match:
        if int(y) < current_year:
            return False

    stale_keywords = ["去年", "前年", "回顾", "总结", "盘点", "历年", "曾经", "往期",
                      "经典", "老", "旧版", "传统", "历史", "纪念", "周年"]
    for kw in stale_keywords:
        if kw in title:
            return False

    current_date = _get_current_date_str()
    if current_date in title:
        return True

    fresh_keywords = ["今日", "今天", "昨夜", "昨晚", "刚刚", "最新", "最新消息",
                      "快讯", "突发", "紧急", "速报", "实时", "即时"]
    for kw in fresh_keywords:
        if kw in title:
            return True

    return True

def _ngram_set(text: str, n: int = 2) -> set:
    tokens = []
    for m in re.finditer(r'[a-zA-Z0-9]+|[一-鿿㐀-䶿]', text):
        tokens.append(m.group().lower())
    if len(tokens) < n:
        return set(tokens) if tokens else set()
    return {tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)}

def deduplicate_topics(topics_list, threshold=0.5):
    if not topics_list:
        return []
    unique = []
    unique_ng = []
    for item in topics_list:
        item_ng = _ngram_set(item, 2)
        is_dup = False
        for eng in unique_ng:
            if not item_ng or not eng:
                continue
            inter = len(item_ng & eng)
            union = len(item_ng | eng)
            if union > 0 and inter / union >= threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(item)
            unique_ng.append(item_ng)
    return unique
