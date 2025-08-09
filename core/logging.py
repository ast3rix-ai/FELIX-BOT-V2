from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from loguru import logger


def _json_serializer(message: Dict[str, Any]) -> str:
    return json.dumps(message, ensure_ascii=False)


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


__all__ = ["logger", "configure_logging"]


