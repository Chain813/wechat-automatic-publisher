"""
Runtime bootstrap helpers for console encoding and logging.
"""
from __future__ import annotations

import sys

from loguru import logger


def _reconfigure_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


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


__all__ = ["configure_runtime"]
