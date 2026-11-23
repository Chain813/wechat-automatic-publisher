"""
Runtime bootstrap helpers for console encoding and logging.
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

import sys
import queue
import threading

from loguru import logger

def _now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowOutcome:
    task_type: str
    status: str
    run_id: str = field(default_factory=lambda: uuid4().hex)
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    uncertain: int = 0
    skipped: int = 0
    summary: str = ""
    error: str = ""
    started_at: str = field(default_factory=_now)
    finished_at: str = field(default_factory=_now)

    def to_dict(self):
        return asdict(self)


class LogBuffer:
    """Thread-safe sequence cursor shared by independent Web UI readers."""

    def __init__(self, maxlen=5000):
        self._entries = deque(maxlen=maxlen)
        self._seq = 0
        self._legacy_cursor = 0
        self._lock = threading.Lock()

    def put_nowait(self, message):
        with self._lock:
            self._seq += 1
            self._entries.append((self._seq, str(message)))

    def read_since(self, since=0):
        with self._lock:
            return [msg for seq, msg in self._entries if seq > since], self._seq

    append = put_nowait
    get_since = read_since

    def drain(self):
        with self._lock:
            messages = [msg for seq, msg in self._entries if seq > self._legacy_cursor]
            self._legacy_cursor = self._seq
            return messages

    def get_nowait(self):
        with self._lock:
            for seq, msg in self._entries:
                if seq > self._legacy_cursor:
                    self._legacy_cursor = seq
                    return msg
            raise queue.Empty


log_buffer = LogBuffer()
log_queue = log_buffer

# ---- 全局控制信号 ----
cancel_event = threading.Event()
pause_event = threading.Event()
pause_event.set()  # 默认运行状态 (Set=运行, Clear=暂停)


class WorkflowCancelled(Exception):
    """用户主动中断工作流时抛出"""
    pass


def check_cancelled():
    """在工作流关键节点调用，处理中断和暂停"""
    while not pause_event.is_set() and not cancel_event.is_set():
        pause_event.wait(timeout=0.1)
    if cancel_event.is_set():
        raise WorkflowCancelled("用户手动中断")


def _queue_sink(message):
    try:
        log_queue.put_nowait(message)
    except queue.Full:
        pass


def _reconfigure_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _validate_config(strict=True):
    """启动时校验必要配置项，缺失则立即报错退出"""
    from config import LLM_API_KEY, LLM_API_KEYS, WECHAT_APP_ID, WECHAT_APP_SECRET

    missing = []
    if not (LLM_API_KEY or LLM_API_KEYS):
        missing.append("LLM_API_KEY")
    if not WECHAT_APP_ID:
        missing.append("WECHAT_APP_ID")
    if not WECHAT_APP_SECRET:
        missing.append("WECHAT_APP_SECRET")

    if missing:
        message = "缺少必要配置项: " + ", ".join(missing)
        if strict:
            raise ValueError(message)
        logger.warning(message)
    return missing


def configure_runtime(validate=True):
    """Prepare stdio encoding and a consistent Loguru console sink."""
    _reconfigure_stdio()

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    
    # Add memory queue sink for Web UI
    logger.add(
        _queue_sink,
        format="{time:HH:mm:ss} | {level: <7} | {message}",
        level="INFO",
        colorize=False,
    )

    _validate_config(strict=validate)


__all__ = ["configure_runtime", "WorkflowOutcome", "LogBuffer", "log_buffer", "log_queue", "cancel_event", "pause_event", "check_cancelled", "WorkflowCancelled"]
