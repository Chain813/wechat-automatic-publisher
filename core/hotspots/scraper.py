"""
轻量文章正文提取器
基于 Trafilatura 实现快速提取网页正文
"""
from typing import Optional
from loguru import logger
import requests
import trafilatura

DEFAULT_SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def extract_article_content(url: Optional[str], timeout: int = 10, max_chars: int = 2500) -> str:
    """
    使用 trafilatura 提取网页文章正文，具备请求头反爬兜底
    :param url: 文章URL
    :param timeout: 超时时间
    :param max_chars: 最大返回字符数，超过截断
    :return: 提取的正文字符串，失败返回空字符串
    """
    if not url or not url.strip():
        return ""

    url = url.strip()
    downloaded = None

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as fe:
        logger.debug(f"trafilatura.fetch_url 尝试失败 ({url}): {fe}")

    # 若原生抓取失败，自动使用带真实浏览器头的 requests 备选抓取（防止 403 / 反爬拦截）
    if not downloaded:
        try:
            resp = requests.get(url, headers=DEFAULT_SCRAPER_HEADERS, timeout=timeout)
            if resp.status_code == 200 and resp.text:
                downloaded = resp.text
        except Exception as re_err:
            logger.debug(f"requests 备选抓取失败 ({url}): {re_err}")

    if not downloaded:
        return ""

    try:
        extracted = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            no_fallback=False
        )
        if not extracted:
            return ""

        content = extracted.strip()
        if max_chars and len(content) > max_chars:
            content = content[:max_chars]
        return content
    except Exception as e:
        logger.warning(f"提取文章正文失败 ({url}): {e}")
        return ""
