"""
HTTP session helpers with retry and optional cache support.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from config import HTTP_RETRY_BACKOFF, HTTP_RETRY_TOTAL


def _mount_retry(session: requests.Session) -> requests.Session:
    retry = Retry(
        total=HTTP_RETRY_TOTAL,
        connect=HTTP_RETRY_TOTAL,
        read=HTTP_RETRY_TOTAL,
        status=HTTP_RETRY_TOTAL,
        backoff_factor=HTTP_RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def build_cached_session(cache_name: str, expire_after: int) -> requests.Session:
    try:
        from requests_cache import CachedSession

        session = CachedSession(
            cache_name=cache_name,
            expire_after=expire_after,
            allowable_methods=("GET",),
            stale_if_error=True,
        )
    except ImportError:
        logger.warning("requests-cache 未安装，热点采集将退化为普通请求")
        session = requests.Session()

    return _mount_retry(session)


def build_api_session() -> requests.Session:
    return _mount_retry(requests.Session())
