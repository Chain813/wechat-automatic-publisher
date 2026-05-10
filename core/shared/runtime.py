"""
Runtime bootstrap helpers for console encoding and logging.
"""
from __future__ import annotations

import sys
import queue
import threading

from loguru import logger

# Global queue to store logs for the Web UI
log_queue = queue.Queue()

# ---- 全局控制信号 ----
cancel_event = threading.Event()
pause_event = threading.Event()
pause_event.set()  # 默认运行状态 (Set=运行, Clear=暂停)


class WorkflowCancelled(Exception):
    """用户主动中断工作流时抛出"""
    pass


def check_cancelled():
    """在工作流关键节点调用，处理中断和暂停"""
    # 1. 检查中断
    if cancel_event.is_set():
        logger.warning("⛔ 用户已中断任务，正在终止...")
        raise WorkflowCancelled("用户手动中断")

    # 2. 检查暂停
    if not pause_event.is_set():
        logger.info("⏸️ 任务已暂停，等待恢复...")
        pause_event.wait()  # 阻塞直到 pause_event.set() 被调用
        logger.info("▶️ 任务已恢复。")

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


def _validate_config():
    """启动时校验必要配置项，缺失则立即报错退出"""
    from config import LLM_API_KEY, WECHAT_APP_ID, WECHAT_APP_SECRET

    missing = []
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not WECHAT_APP_ID:
        missing.append("WECHAT_APP_ID")
    if not WECHAT_APP_SECRET:
        missing.append("WECHAT_APP_SECRET")

    if missing:
        logger.error("以下必要配置项缺失，请在 .env 文件中设置: {}", ", ".join(missing))
        sys.exit(1)


def configure_runtime():
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

    _validate_config()


__all__ = ["configure_runtime", "log_queue", "cancel_event", "pause_event", "check_cancelled", "WorkflowCancelled"]
