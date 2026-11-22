import os
import random
import threading
import time
from datetime import datetime, timezone, timedelta
import re
from loguru import logger
from utils.http_client import build_cached_session
import config as _config
from config import HOTSPOT_CACHE_TTL_SECONDS, NEWS_FRESHNESS_HOURS

SOURCE_CIRCUIT_COOLDOWN_SECONDS = getattr(_config, "SOURCE_CIRCUIT_COOLDOWN_SECONDS", 1800)

_CN_TZ = timezone(timedelta(hours=8))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
]

_source_health = {}
_source_health_lock = threading.Lock()
HTTP_SESSION = build_cached_session(os.path.join("data", "cache", "hotspots", "hotspot_cache"), HOTSPOT_CACHE_TTL_SECONDS)


def _new_health_entry():
    return {
        "failures": 0,
        "disabled": False,
        "disabled_until": 0.0,
        "latency_ms": None,
        "detail": "",
    }


def _maybe_recover_source(name, h):
    if h.get("disabled"):
        disabled_until = h.get("disabled_until", 0.0)
        if disabled_until > 0 and time.time() >= disabled_until:
            h["disabled"] = False
            h["failures"] = 0
            h["disabled_until"] = 0.0
            h["detail"] = "冷却期满，已自动恢复半开探测"
            logger.info(f"  {name} 熔断冷却已到期，自动恢复半开探测")


def get_source_health_report():
    from config import NEWS_SOURCES
    display_names = {}
    try:
        from core.plugins.manager import plugin_manager
        for sid, plugin in plugin_manager.get_all_plugins().items():
            display_names[sid] = getattr(plugin, "display_name", sid)
    except Exception:
        pass

    report = {}
    with _source_health_lock:
        # 预先用配置的信源初始化健康状态，避免初始状态为空
        for src in NEWS_SOURCES:
            if src not in _source_health:
                _source_health[src] = _new_health_entry()

        for k, v in _source_health.items():
            _maybe_recover_source(k, v)
            if v["disabled"]:
                status = "disabled"
            elif v["failures"] > 0:
                status = "degraded"
            else:
                status = "healthy"
            entry = {
                "failures": v["failures"],
                "status": status,
            }
            if k in display_names:
                entry["display_name"] = display_names[k]
            if v.get("latency_ms") is not None:
                entry["latency_ms"] = v["latency_ms"]
            if v.get("detail"):
                entry["detail"] = v["detail"]
            report[k] = entry
    return report


def _get_source_health(name):
    if name not in _source_health:
        _source_health[name] = _new_health_entry()
    return _source_health[name]


def _mark_source_failure(name, detail=""):
    with _source_health_lock:
        h = _get_source_health(name)
        h["failures"] += 1
        if detail:
            h["detail"] = detail
        if h["failures"] >= 3:
            h["disabled"] = True
            h["disabled_until"] = time.time() + max(1, int(SOURCE_CIRCUIT_COOLDOWN_SECONDS))
            logger.warning(
                f"  {name} 连续失败 {h['failures']} 次，已自动熔断冷却 {SOURCE_CIRCUIT_COOLDOWN_SECONDS} 秒后恢复"
            )


def _mark_source_success(name, latency_ms=None, detail=""):
    with _source_health_lock:
        h = _get_source_health(name)
        h["failures"] = 0
        h["disabled"] = False
        h["disabled_until"] = 0.0
        if latency_ms is not None:
            h["latency_ms"] = int(latency_ms)
        if detail:
            h["detail"] = detail


def _is_source_disabled(name):
    with _source_health_lock:
        h = _get_source_health(name)
        _maybe_recover_source(name, h)
        return h["disabled"]

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
    if isinstance(title, str):
        pass
    elif hasattr(title, "title"):
        title = title.title
    else:
        title = str(title)

    # 1. 严格限定陈旧/复盘类复合词，严禁使用单字（如“老”会误杀“老板/养老/老牌/老师”）或宽泛词（如“历史”）
    stale_phrases = [
        "历史上的今天", "去年", "前年", "往年", "往期", "历年盘点", "历年回顾",
        "年终盘点", "年终总结", "季度回顾", "老旧版本", "陈旧过时", "经典回顾"
    ]
    for kw in stale_phrases:
        if kw in title:
            return False

    # 2. 检查明显早于当年的年份（如 2023年、2022年）
    current_year = datetime.now().year
    old_year_match = re.findall(r'(20\d{2})年', title)
    for y in old_year_match:
        if int(y) < current_year:
            return False

    # 3. 强时效性豁免白名单：放行包含最新突破、创纪录或突发信号的内容
    fresh_keywords = [
        "历史新高", "历史新低", "创历史", "创造历史", "见证历史", "历史性",
        "突破传统", "颠覆传统", "今日", "今天", "昨夜", "昨晚",
        "刚刚", "最新", "最新消息", "快讯", "突发", "紧急", "速报", "实时", "即时"
    ]
    for fw in fresh_keywords:
        if fw in title:
            return True

    current_date = _get_current_date_str()
    if current_date in title:
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
