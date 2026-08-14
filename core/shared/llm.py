import re
import time
import requests
from loguru import logger
from utils.http_client import build_api_session
from config import (
    LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT,
    LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_MAX_RETRIES,
    WECHAT_TITLE_MAX_LEN, SENSITIVE_WORDS
)

API_SESSION = build_api_session()


class LLMCacheMetrics:
    def __init__(self):
        self.total_requests = 0
        self.prompt_cache_hit_tokens = 0
        self.prompt_cache_miss_tokens = 0
        self.last_latency_ms = 0
        self.last_warmup_time = None

    def record(self, hit_tokens, miss_tokens, latency_ms):
        self.total_requests += 1
        self.prompt_cache_hit_tokens += hit_tokens
        self.prompt_cache_miss_tokens += miss_tokens
        self.last_latency_ms = latency_ms

    def get_stats(self):
        total_tokens = self.prompt_cache_hit_tokens + self.prompt_cache_miss_tokens
        hit_rate = (self.prompt_cache_hit_tokens / total_tokens * 100) if total_tokens > 0 else 0.0
        saving_rate = calculate_cache_saving_rate()
        saved_cny = round(self.prompt_cache_hit_tokens * saving_rate, 4)
        return {
            "total_requests": self.total_requests,
            "hit_tokens": self.prompt_cache_hit_tokens,
            "miss_tokens": self.prompt_cache_miss_tokens,
            "hit_rate_pct": round(hit_rate, 1),
            "saved_cny": saved_cny,
            "last_latency_ms": self.last_latency_ms,
            "is_warm": self.last_warmup_time is not None and (time.time() - self.last_warmup_time < 300),
            "is_peak_hour": is_beijing_peak_hour()
        }


def is_beijing_peak_hour():
    """判断当前时间（北京时间 UTC+8）是否属于 DeepSeek API 峰值时段 (9:00-12:00, 14:00-18:00)"""
    from datetime import datetime, timezone, timedelta
    bj_time = datetime.now(timezone(timedelta(hours=8)))
    hour = bj_time.hour
    return (9 <= hour < 12) or (14 <= hour < 18)


def calculate_cache_saving_rate(model_name: str = None):
    """
    根据模型与峰谷时段（2026-08-17生效）计算每 hit 1 个 token 节省的金额（元）。
    - Flash: 空闲 1.45元/1M (miss 1.5 - hit 0.05), 高峰 2.90元/1M (miss 3.0 - hit 0.10)
    - Pro:   空闲 4.35元/1M (miss 4.5 - hit 0.15), 高峰 8.70元/1M (miss 9.0 - hit 0.30)
    """
    if not model_name:
        from config import LLM_MODEL
        model_name = LLM_MODEL

    is_peak = is_beijing_peak_hour()
    model_lower = str(model_name).lower()

    if "flash" in model_lower:
        saving_per_1m = 2.90 if is_peak else 1.45
    else:
        saving_per_1m = 8.70 if is_peak else 4.35

    return saving_per_1m / 1_000_000


cache_metrics = LLMCacheMetrics()


def warmup_deepseek_cache():
    """轻量级预热 DeepSeek 节点 Prompt Cache"""
    try:
        from core.aikepu.processor import SYSTEM_PROMPT
        call_deepseek_with_retry("ping warmup", system_content=SYSTEM_PROMPT, max_tokens=1)
        cache_metrics.last_warmup_time = time.time()
        return True
    except Exception as e:
        logger.warning("DeepSeek 预热请求失败: {}", e)
        return False


def _interruptible_sleep(seconds):
    """可中断的 sleep：每 0.5 秒检查一次 cancel_event"""
    from core.shared.runtime import cancel_event
    steps = int(seconds / 0.5)
    for _ in range(max(steps, 1)):
        if cancel_event.is_set():
            return
        time.sleep(0.5)


def call_deepseek_with_retry(prompt, system_content="", max_retries=None, backoff_base=1.0, timeout=None, max_tokens=None, model=None):
    """带指数退避的 API 调用。timeout/max_tokens/model 可覆盖全局默认值。支持中断和暂停。"""
    from core.shared.runtime import check_cancelled, WorkflowCancelled

    check_cancelled()

    if max_retries is None:
        max_retries = LLM_MAX_RETRIES
    if timeout is None:
        timeout = LLM_TIMEOUT
    if max_tokens is None:
        max_tokens = LLM_MAX_TOKENS
    
    target_model = model or LLM_MODEL

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }

    for attempt in range(1, max_retries + 1):
        # 每次重试前和调用前检查中断/暂停信号
        check_cancelled()

        try:
            data = {
                "model": target_model,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": LLM_TEMPERATURE,
                "max_tokens": max_tokens
            }
            start_t = time.time()
            response = API_SESSION.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=data,
                timeout=timeout
            )
            response.raise_for_status()
            latency_ms = int((time.time() - start_t) * 1000)
            result = response.json()
            usage = result.get('usage', {})
            prompt_tokens = usage.get('prompt_tokens', 0)
            hit_tokens = usage.get('prompt_cache_hit_tokens', 0)
            if not hit_tokens and 'prompt_tokens_details' in usage:
                details = usage.get('prompt_tokens_details') or {}
                hit_tokens = details.get('cached_tokens', 0)
            miss_tokens = usage.get('prompt_cache_miss_tokens', max(0, prompt_tokens - hit_tokens))
            
            cache_metrics.record(hit_tokens, miss_tokens, latency_ms)

            # 控制台实时打出 Prompt Cache 命中与加速监控日志
            if prompt_tokens > 0:
                stats = cache_metrics.get_stats()
                logger.info(
                    "⚡ [DeepSeek Cache] 响应: {}ms | 缓存命中: {} tokens | 未命中: {} tokens | 累计命中率: {}% (估算已省 ¥{})",
                    latency_ms, hit_tokens, miss_tokens, stats['hit_rate_pct'], stats['saved_cny']
                )

            return result['choices'][0]['message']['content']

        except Exception as e:
            # WorkflowCancelled 不应被捕获，直接向上抛
            if isinstance(e, WorkflowCancelled):
                raise
            if isinstance(e, requests.exceptions.Timeout):
                logger.warning("AI 调用超时 (第 {}/{} 次)", attempt, max_retries)
                if attempt < max_retries:
                    _interruptible_sleep(backoff_base * (2 ** (attempt - 1)))
                continue
            if isinstance(e, requests.exceptions.HTTPError):
                status = getattr(e.response, 'status_code', 500)
                if status == 429:
                    logger.warning("AI 限流 429 (第 {}/{} 次)，退避重试", attempt, max_retries)
                    if attempt < max_retries:
                        _interruptible_sleep(backoff_base * (2 ** attempt))
                    continue
                if status >= 500:
                    logger.error("AI 服务端错误 {} (第 {}/{} 次)", status, attempt, max_retries)
                    if attempt < max_retries:
                        _interruptible_sleep(backoff_base * (2 ** (attempt - 1)))
                    continue
                logger.error("AI 客户端错误 {}，不重试: {}", status, e)
                return ""
            if isinstance(e, (KeyError, IndexError)):
                logger.error("AI 响应格式异常: {}", e)
                return ""
            logger.error("AI 调用失败: {} (第 {}/{} 次)", e, attempt, max_retries)
            if attempt < max_retries:
                _interruptible_sleep(backoff_base * (2 ** (attempt - 1)))

    logger.error("AI 调用在 {} 次重试后全部失败，返回空响应", max_retries)
    return ""


def validate_title(title: str):
    """
    校验标题是否符合微信规范。
    返回 (处理后的标题, 警告信息列表)
    """
    warnings = []
    clean_title = title.strip()

    clickbait = ["震惊", "突发", "速看", "重磅", "紧急", "刚刚",
                 "不看后悔", "深度好文", "干货", "收藏"]
    for word in clickbait:
        if word in clean_title:
            clean_title = clean_title.replace(word, "")
            warnings.append(f"已移除标题党词汇: '{word}'")

    if len(clean_title) > WECHAT_TITLE_MAX_LEN:
        warnings.append(f"标题超长 ({len(clean_title)} > {WECHAT_TITLE_MAX_LEN})，已截断")
        clean_title = clean_title[:WECHAT_TITLE_MAX_LEN]

    return clean_title, warnings


def validate_article_length(text: str):
    """
    校验文章字数。
    返回 (实际字数, 是否达标, 消息)
    """
    word_count = len(text.replace('\n', '').replace(' ', ''))
    if word_count < 2000:
        return word_count, False, f"字数不足 ({word_count} < 2000)"
    elif word_count < 2500:
        return word_count, True, f"字数略低 ({word_count})"
    elif word_count > 4000:
        return word_count, True, f"字数偏多 ({word_count} > 4000，微信阅读体验可能不佳)"
    else:
        return word_count, True, f"字数达标 ({word_count})"


def filter_sensitive(text: str):
    """
    敏感词检测与过滤（使用正则词边界，避免误匹配子串）。
    返回 (过滤后文本, 命中敏感词列表)
    """
    if not SENSITIVE_WORDS:
        return text, []

    hit_words = []
    filtered = text
    for word in SENSITIVE_WORDS:
        if not word:
            continue
        if re.search(r'[一-鿿]', word):
            pattern = re.compile(
                r'(?<![一-鿿])' + re.escape(word) + r'(?![一-鿿])'
            )
        else:
            pattern = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)

        if pattern.search(filtered):
            hit_words.append(word)
            filtered = pattern.sub('*' * len(word), filtered)

    return filtered, hit_words

def simplify_keyword(complex_kw):
    """本地快速简化关键词，不调用 LLM。"""
    kw = complex_kw.strip()
    if not kw:
        return ""

    # 截断过长关键词（取前 15 字符，保留核心名词）
    if len(kw) > 15:
        # 尝试在标点/助词处截断
        for sep in ["的", "与", "和", "、", "，", " "]:
            idx = kw.find(sep)
            if 3 < idx < 15:
                kw = kw[:idx]
                break
        else:
            kw = kw[:15]

    # 去除常见无意义后缀
    for suffix in ["相关", "话题", "新闻", "资讯", "分析", "解读", "事件", "最新"]:
        if kw.endswith(suffix) and len(kw) > len(suffix) + 1:
            kw = kw[:-len(suffix)]
            break

    logger.info("  关键词简化: '{}' -> '{}'", complex_kw, kw)
    return kw
