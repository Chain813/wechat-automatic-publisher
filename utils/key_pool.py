"""
============================================================
  API Key 轮询池 — 多 Key 轮询 + 故障退避 + 限流自动切换
  解决：单 Key 限流(429)/欠费(401)/被禁(403)时自动切下一个
  注意：同一账号下多个 Key 共享账号级 QPM 配额，
        要提升并发上限需多账号 Key 或百炼控制台提额
============================================================
"""
import threading
import time
from loguru import logger


class RateLimiter:
    """全局请求节流器：保证两次请求间的最小间隔（线程安全）
    用于千问生图等 QPM 受限接口，防多线程并行时突发限流。"""

    def __init__(self, min_interval_seconds=4.0):
        self._min = max(0.0, float(min_interval_seconds))
        self._lock = threading.Lock()
        self._last = float("-inf")

    def wait(self):
        """Wait for a slot without reserving capacity for cancelled callers."""
        from core.shared.runtime import cancel_event, check_cancelled

        while True:
            check_cancelled()
            with self._lock:
                now = time.monotonic()
                remaining = self._last + self._min - now
                if remaining <= 0:
                    self._last = now
                    return
            cancel_event.wait(remaining)


class ApiKeyPool:
    """线程安全的多 Key 轮询池：轮询取 Key，失败进入冷却，到期自动恢复"""

    def __init__(self, keys, cooldown_seconds=60):
        self._keys = [str(k).strip() for k in (keys or []) if k and str(k).strip()]
        self._lock = threading.Lock()
        self._index = 0
        self._failed_until = {}   # key -> 恢复时间戳
        self._cooldown = cooldown_seconds

    @property
    def size(self):
        return len(self._keys)

    def get_key(self):
        """取下一个可用 Key（自动跳过冷却中的 Key）"""
        with self._lock:
            if not self._keys:
                return ""
            now = time.monotonic()
            for _ in range(len(self._keys)):
                key = self._keys[self._index]
                self._index = (self._index + 1) % len(self._keys)
                if self._failed_until.get(key, 0) <= now:
                    return key
            return ""

    def report_failure(self, key, cooldown_seconds=None):
        """标记 Key 失败，冷却 N 秒后自动恢复"""
        with self._lock:
            delay = self._cooldown if cooldown_seconds is None else cooldown_seconds
            until = time.monotonic() + delay
            self._failed_until[key] = max(self._failed_until.get(key, 0), until)
            logger.warning("API credential cooling down for {}s", delay)

    def report_success(self, key):
        # An earlier in-flight request can succeed after a newer one was rejected.
        with self._lock:
            if self._failed_until.get(key, 0) <= time.monotonic():
                self._failed_until.pop(key, None)
