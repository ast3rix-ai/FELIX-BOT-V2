from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict

from loguru import logger


_LOG_QUEUE: asyncio.Queue[Dict[str, Any]] | None = None


def get_log_queue() -> asyncio.Queue[Dict[str, Any]]:
    global _LOG_QUEUE
    if _LOG_QUEUE is None:
        _LOG_QUEUE = asyncio.Queue()
    return _LOG_QUEUE


def _queue_sink(message):
    try:
        record = message.record
        q = get_log_queue()
        payload = {
            "ts": record["time"].timestamp(),
            "level": record["level"].name,
            "message": record["message"],
            "extra": dict(record.get("extra", {})),
        }
        q.put_nowait(payload)
    except Exception:
        pass


def configure_logging(level: str | int = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stdout,
        level=level,
        serialize=True,
        backtrace=os.getenv("LOG_BACKTRACE", "0") == "1",
        diagnose=os.getenv("LOG_DIAGNOSE", "0") == "1",
        enqueue=True,
    )
    # Structured queue sink for UI
    logger.add(_queue_sink, level=level, enqueue=True)


__all__ = ["logger", "configure_logging", "get_log_queue"]


