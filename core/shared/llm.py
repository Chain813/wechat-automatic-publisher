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


def _interruptible_sleep(seconds):
    """可中断的 sleep：每 0.5 秒检查一次 cancel_event"""
    from core.shared.runtime import cancel_event
    steps = int(seconds / 0.5)
    for _ in range(max(steps, 1)):
        if cancel_event.is_set():
            return
        time.sleep(0.5)


def call_deepseek_with_retry(prompt, system_content="", max_retries=None, backoff_base=1.0, timeout=None, max_tokens=None):
    """带指数退避的 API 调用。timeout/max_tokens 可覆盖全局默认值。支持中断。"""
    from core.shared.runtime import cancel_event, WorkflowCancelled

    if max_retries is None:
        max_retries = LLM_MAX_RETRIES
    if timeout is None:
        timeout = LLM_TIMEOUT
    if max_tokens is None:
        max_tokens = LLM_MAX_TOKENS

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }

    for attempt in range(1, max_retries + 1):
        # 每次重试前检查中断信号
        if cancel_event.is_set():
            raise WorkflowCancelled("AI 调用被用户中断")

        try:
            data = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": prompt}
                ],
                "temperature": LLM_TEMPERATURE,
                "max_tokens": max_tokens
            }
            response = API_SESSION.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=data,
                timeout=timeout
            )
            response.raise_for_status()
            result = response.json()
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
