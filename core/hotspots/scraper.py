"""
轻量文章正文提取器
基于 Trafilatura 实现快速提取网页正文
"""
from typing import Optional
from loguru import logger
import trafilatura


def extract_article_content(url: Optional[str], timeout: int = 10, max_chars: int = 2500) -> str:
    """
    使用 trafilatura 提取网页文章正文
    :param url: 文章URL
    :param timeout: 超时时间（保留参数供扩展）
    :param max_chars: 最大返回字符数，超过截断
    :return: 提取的正文字符串，失败返回空字符串
    """
    if not url or not url.strip():
        return ""

    url = url.strip()
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""

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
